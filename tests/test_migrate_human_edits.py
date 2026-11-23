"""사람 고침(덧바르는 연산) 하나를 저장해도 검토구간 판 이전이 그 구성요소를 잃지 않는다.

앱 길 그대로: api_corrections.apply_edit(defer=False) → corrections.save_fp → sheet_refresh.refresh → 그래프 다시 짓기
→ data.notify_graph_changed → Engine.auto_catch_up → 판 이전(idmap.compute).
가상 도면 SNP-M-101의 벡터 PDF(순번 id, id_basis sequence)와 drawio(파일 id, id_basis source) 각각에서 본다.
덧바르는 연산은 기준 추출(번호를 매긴 입력)을 바꾸지 않으므로 순번 id가 그대로다. 지운 기호는 묘비, 남은 기호는 같은 순번 id의 구성요소로 간다.
"""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_titleblock import BY, P, Base  # noqa: E402

from hazop.app import project_ctx  # noqa: E402
from hazop.extract import confirmation, rules  # noqa: E402
from hazop.kg.schema import REGISTRY  # noqa: E402
from hazop.shell import api, api_corrections as AC, api_nodes  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402


def tagged_symbol(n):
    return bool(n.get("tag")) and n.get("kind") not in (None, "tee", "continuation")


def other_kind(kind):
    cat = rules.KIND_CATEGORY.get(kind)
    return next(k for k in sorted(rules.KIND_CATEGORY) if k != kind and rules.KIND_CATEGORY[k] == cat), cat


class Sheet(Base):
    EXT = None
    LEGACY = False

    def setUp(self):
        super().setUp()
        if self.LEGACY:   # 기준 추출 판을 남기기 전 앱이 지은 그래프와 집합
            old = mock.patch("hazop.graph.build.base_version", lambda extraction: None)
            old.start()
            self.addCleanup(old.stop)
            self.legacy = old
        self.mid = self.add("SNP-M-101", self.EXT)
        s = self.sheet(self.mid)
        self.name, self.gid = s["name"], s["graph_id"]
        with open(confirmation.extraction_path(self.name), encoding="utf-8") as fh:
            self.ex = json.load(fh)
        self.picked = [n for n in self.ex["nodes"] if tagged_symbol(n)][:6]
        self.assertGreaterEqual(len(self.picked), 3, "시험 전제: 태그와 상자가 있는 기호")
        self.eng = api.Engine(settings_path=os.path.join(self.tmp, "eng.json"), emit=lambda *a, **k: None, run_jobs=lambda jid, fn: fn())
        self.eng.settings.update(reviewer_name=BY, project_id=P)
        cmds = {}
        api_nodes.register(cmds)
        c = cmds["nodes.create"]
        out = c.handler(self.eng, api.check_args(c.spec, {"project_id": P, "set_rev": (sn.load(self.pg()) or {}).get("set_rev") or 0,
                                                          "sheet": self.gid, "ids": [n["local_id"] for n in self.picked], "name": "S-probe"}))
        self.assertNotEqual((out or {}).get("ok"), False, out)
        self.ns0 = sn.load(self.pg())
        self.assertEqual(len(self.ns0["nodes"]), 1)

    def pg(self):
        return project_ctx.project_graph(P)

    def sids(self, eids):
        by = {n["entity_id"]: n.get("source_object_id") for n in self.pg()["nodes"]}
        return sorted(by[e] for e in eids)

    def save(self, op, local_id, value):
        v = AC.view(self.eng, self.gid)
        self.assertTrue(v.get("ok"), v)
        r = AC.apply_edit(self.eng, self.gid, op, local_id, value, v["ver"], defer=False)
        if r.get("code") == "needs_confirm":
            r = AC.apply_edit(self.eng, self.gid, op, local_id, value, v["ver"], confirm=r["message"], defer=False)
        self.assertTrue(r.get("ok"), r)
        ns = sn.read_as_is(self.pg())
        self.assertFalse(sn.is_stale(ns, self.pg()), "앱이 판 이전을 이어서 했다")
        return ns

    def lost(self, ns):
        row = next(h.get("detail") or {} for h in reversed(ns.get("history") or [])
                   if isinstance(h, dict) and h.get("op") == "migrate_version")
        return sorted((row.get("lost") or {}).keys())

    def assert_kept(self, op, local_id, value):
        ns = self.save(op, local_id, value)
        self.assertNotEqual(ns.get("graph_version"), self.ns0.get("graph_version"), "시험 전제: 판이 바뀌어 판 이전이 돌았다")
        seg = ns["nodes"][0]
        self.assertEqual((self.lost(ns), seg.get("lost") or [], ns.get("tombstones") or {}), ([], [], {}),
                         "사람이 %s만 한 구성요소를 판 이전이 잃음" % op)
        self.assertEqual(self.sids(seg["members"]), sorted(n["source_object_id"] for n in self.picked))
        return ns

    def relation(self):
        sids = {n.get("source_object_id") for n in self.pg()["nodes"] if n.get("sheet") == self.gid}
        rel = next((r for r in self.ex.get("relations") or [] if r.get("kind") == "physical_connection"
                    and r["source_object_id"] in sids), None)
        if rel is None:
            self.skipTest("프로젝트 그래프에 노드로 나오는 배관이 없음")
        return rel


class HumanEditMigration(Sheet):
    def test_set_tag(self):
        n = self.picked[0]
        self.assert_kept("set_tag", n["local_id"], {"tag": n["tag"] + "-HUMAN"})

    def test_set_kind(self):
        n = self.picked[1]
        k, cat = other_kind(n["kind"])
        self.assert_kept("set_kind", n["local_id"], {"kind": k, "category": cat})

    def test_set_normal_position(self):
        n = next((x for x in self.picked if "normal_position" in REGISTRY.class_properties(REGISTRY.kind_class.get(x["kind"]) or "")), None)
        if n is None:
            self.skipTest("정상 위치를 둘 기호가 없음")
        cur = (n.get("attributes") or {}).get("normal_position")
        self.assert_kept("set_normal_position", n["local_id"],
                         {"value": next(a for a in REGISTRY.properties["normal_position"]["values"] if a != cur)})

    def test_pipe_line_no(self):
        self.assert_kept("set_tag", self.relation()["local_id"], {"tag": "L-HUMAN-1"})

    def test_pipe_path(self):
        rel = self.relation()
        a, b = (ep["point"] for ep in rel["endpoints"])
        self.assert_kept("set_path", rel["local_id"], {"points": [a, [(a[0] + b[0]) / 2 + 7, (a[1] + b[1]) / 2 + 7], b]})

    def test_pipe_endpoint(self):
        rel = self.relation()
        ends = {ep["node_local_id"] for ep in rel["endpoints"]}
        other = next(n for n in self.ex["nodes"] if n["local_id"] not in ends and n.get("kind") not in (None, "continuation"))
        self.assert_kept("set_endpoint", rel["local_id"], {"end": "target", "node": other["local_id"]})

    def test_undo_leaves_no_open_tombstone(self):
        n = self.picked[0]
        self.assert_kept("set_tag", n["local_id"], {"tag": n["tag"] + "-HUMAN"})
        v = AC.view(self.eng, self.gid)
        r = AC.undo(self.eng, self.gid, v["ops"][-1]["op_id"], v["ver"])
        self.assertTrue(r.get("ok"), r)
        ns = sn.read_as_is(self.pg())
        seg = ns["nodes"][0]
        self.assertEqual((seg.get("lost") or [], ns.get("tombstones") or {}), ([], {}))
        self.assertEqual(self.sids(seg["members"]), sorted(x["source_object_id"] for x in self.picked))

    def test_delete_shifts_entity_ids_but_members_follow_their_own_symbol(self):
        """지우기는 뒤 기호의 entity 순번을 당긴다. 남은 구성원은 순번이 아니라 같은 기호(같은 source_object_id)로 가고, 지운 기호만 묘비다."""
        gone = self.picked[0]
        ns = self.save("delete_node", gone["local_id"], {})
        seg = ns["nodes"][0]
        self.assertEqual(self.sids(seg["members"]), sorted(n["source_object_id"] for n in self.picked[1:]))
        self.assertEqual(len(seg.get("lost") or []), 1)
        n = self.picked[1]
        ns = self.save("set_tag", n["local_id"], {"tag": n["tag"] + "-HUMAN"})
        seg = ns["nodes"][0]
        self.assertEqual(self.sids(seg["members"]), sorted(x["source_object_id"] for x in self.picked[1:]))
        self.assertEqual(len(seg.get("lost") or []), 1, "태그 고침이 묘비를 더 만들지 않는다")

    def test_add_node_does_not_take_a_member_seat(self):
        box = next(loc["bbox"] for loc in self.ex["source_locations"] if loc["local_id"] == self.picked[0]["local_id"])
        self.save("add_node", None, {"kind": self.picked[0]["kind"], "tag": self.picked[0]["tag"],
                                     "at": [box[0] + box[2] / 2 + 300, box[1] + box[3] / 2 + 300]})
        n = self.picked[1]
        self.assert_kept("set_tag", n["local_id"], {"tag": n["tag"] + "-HUMAN"})


class LegacyVectorPdf(Sheet):
    """고친 코드 전에 사람 고침으로 잃은 순번 구성요소: 그 시트가 기준 판을 남긴 뒤 고침을 되돌리면 묘비를 되찾는다."""
    EXT = "pdf"
    LEGACY = True

    def test_tomb_from_before_the_fix_comes_back_on_undo(self):
        n = self.picked[0]
        ns = self.save("set_tag", n["local_id"], {"tag": n["tag"] + "-HUMAN"})
        self.assertEqual(len(ns["nodes"][0].get("lost") or []), 1, "시험 전제: 기준 판이 없으면 전처럼 표시로 잇다가 잃는다")
        self.legacy.stop()
        m = next((x for x in self.picked[1:] if "normal_position" in REGISTRY.class_properties(REGISTRY.kind_class.get(x["kind"]) or "")), None)
        if m is None:
            self.skipTest("정상 위치를 둘 기호가 없음")
        cur = (m.get("attributes") or {}).get("normal_position")
        self.save("set_normal_position", m["local_id"], {"value": next(a for a in REGISTRY.properties["normal_position"]["values"] if a != cur)})
        ns = sn.read_as_is(self.pg())
        self.assertIn(self.gid, ns.get("graph_member_bases") or {}, "시험 전제: 이제 시트가 기준 판을 남겼다")
        v = AC.view(self.eng, self.gid)
        r = AC.undo(self.eng, self.gid, next(o for o in v["ops"] if o.get("op") == "set_tag")["op_id"], v["ver"])
        self.assertTrue(r.get("ok"), r)
        ns = sn.read_as_is(self.pg())
        seg = ns["nodes"][0]
        self.assertEqual(seg.get("lost") or [], [])
        self.assertEqual(self.sids(seg["members"]), sorted(x["source_object_id"] for x in self.picked))
        self.assertEqual([t for t, rec in (ns.get("tombstones") or {}).items() if rec.get("found") is None], [])


class VectorPdf(HumanEditMigration):
    EXT = "pdf"


class Drawio(HumanEditMigration):
    EXT = "drawio"


del Sheet, HumanEditMigration

if __name__ == "__main__":
    unittest.main()
