"""AI 나누기(split) 후보 수락이 끝까지 가도 검토구간이 구성요소를 잃지 않는다(split 후보 켜기 전 조건, 2026-11-24).

앱 길 그대로: 등록·추출 → 검토구간 만들기(nodes.create) → api_aireview.accept(판 확인) → ai_review.accept가 split 입력 연산 저장
→ api_inputs 짓기 작업(corrections.ensure_base로 기준 추출 다시 짓기 → sheet_refresh.refresh로 그래프·프로젝트 그래프 다시 만들기)
→ 판 이전(idmap.compute). 기준 추출이 바뀌므로 기준 판(base_version)이 달라진다.

도면은 tests.test_corrections_inputs의 합성 1쪽 PDF다: 맞닿은 수동 밸브 셋이 한 덩어리(BLOB)로 읽히고, 그 옆에 밸브 둘(sym-0002·0003).
AI split이 실제로 겨누는 꼴(기호 여럿을 품은 큰 미분류 노드)이다. 공개 표본 SNP-M-101에는 이런 덩어리가 없다.

- 덩어리에서 밸브 하나를 떼어 냄: 몸체가 남은 덩어리와 옆 밸브 둘은 구성원으로 남고 묘비가 없다. 새 조각은 구간에 들지 않는다.
  기준 추출이 몸체에 덩어리 순번을 잇고(pdf_vector._sym_numbers), 판 이전이 같은 원본에서 매긴 sym 순번을 참조로 잇는다(idmap).
- 셋을 다 떼어 냄: 덩어리는 없어지니 그 하나만 '찾지 못한 구성요소'로 남고(사람에게 알림), 옆 밸브 둘은 그대로다.
- 수락을 되돌리면 덩어리가 돌아오고 구성원도 돌아온다.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_titleblock import BY, P, Base  # noqa: E402
from tests.test_corrections_inputs import BLOB, GROUPS, HAS_PDFPLUMBER, page  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.app import data, project_ctx  # noqa: E402
from hazop.extract import ai_review, ai_split, corrections  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from hazop.register import registry  # noqa: E402
from hazop.shell import api, api_aireview, api_inputs, api_nodes, sheet_refresh  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402

OTHERS = ["pdf-p0-sym-0002", "pdf-p0-sym-0003"]


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 필요")
class SplitAcceptMigration(Base):
    def setUp(self):
        super().setUp()
        with pdf_vector._cache_lock:
            pdf_vector._cache.clear()
        src = os.path.join(self.tmp, "in", "SYN-LUMP-001.pdf")
        os.makedirs(os.path.dirname(src))
        with open(src, "wb") as fh:
            fh.write(page())
        res = registry.register(src, P, "P&ID", paths.store_root(), None, BY)
        self.assertEqual(res["outcome"], "registered", res.get("notes"))
        data.extract_and_graph(res["registration_file"])
        s = self.sheet(res["record"]["material_id"])
        self.name, self.gid = s["name"], s["graph_id"]
        self.ex = corrections.resolve(self.name)["base"]
        self.pdf = paths.resolve_rel(self.ex["source"]["file"], paths.work_root())
        by = {n["source_object_id"]: n for n in self.ex["nodes"]}
        self.assertTrue(set([BLOB] + OTHERS) <= set(by), sorted(by))
        self.picked = [by[BLOB]] + [by[s] for s in OTHERS]
        self.eng = api.Engine(settings_path=os.path.join(self.tmp, "eng.json"), emit=lambda *a, **k: None, run_jobs=lambda jid, fn: fn())
        self.eng.settings.update(reviewer_name=BY, project_id=P)
        self.addCleanup(lambda: api_inputs.of(self.eng).stop())
        cmds = {}
        api_nodes.register(cmds)
        c = cmds["nodes.create"]
        out = c.handler(self.eng, api.check_args(c.spec, {"project_id": P, "set_rev": (sn.load(self.pg()) or {}).get("set_rev") or 0,
                                                          "sheet": self.gid, "ids": [n["local_id"] for n in self.picked], "name": "S-probe"}))
        self.assertNotEqual((out or {}).get("ok"), False, out)
        self.ns0 = sn.load(self.pg())
        self.assertEqual(self.sids(self.ns0["nodes"][0]["members"]), sorted([BLOB] + OTHERS))
        blob = by[BLOB]
        members = pdf_vector.member_shapes(self.pdf, 0)
        doc = ai_review.new_doc(self.name, self.ex)
        for g in GROUPS:
            box = ai_split._union([members[p][0] for p in g])
            item = {"target": BLOB, "local_id": blob["local_id"], "bbox": box}
            doc["candidates"].append(ai_review.make_candidate(
                ai_split.item_id(blob, g), "split", item, "split", ["manual_valve"], 0.9, "범례 수동 밸브",
                {"match": "legend", "pdf_objects": list(g), "new_bbox": box, "ai_box": box, "node_bbox": ai_split._box(blob)}))
        ai_review.save_doc(doc)
        self.cands = [x["cand_id"] for x in doc["candidates"]]

    def pg(self):
        return project_ctx.project_graph(P)

    def sids(self, eids):
        by = {n["entity_id"]: n.get("source_object_id") for n in self.pg()["nodes"]}
        return sorted(by[e] for e in eids)

    def build(self):
        self.assertIn(self.name, api_inputs.of(self.eng).waiting(), "그래프는 짓기 작업이 맡는다")
        self.assertEqual(api_inputs.of(self.eng).flush([self.name]), [self.name])
        self.assertEqual(corrections.resolve(self.name)["inputs"]["waiting"], [], "기준 추출을 지었다")
        ns = sn.read_as_is(self.pg())
        self.assertFalse(sn.is_stale(ns, self.pg()), "앱이 판 이전을 이어서 했다")
        return ns

    def accept(self, ids):
        r = api_aireview.accept(self.eng, self.gid, ids, sheet_refresh.ver_of(self.name))
        self.assertTrue(r.get("ok"), r)
        self.assertEqual((sorted(r["changed"]), r["failed"]), (sorted(ids), []), r)
        ns = self.build()
        self.assertNotEqual(ns.get("graph_version"), self.ns0.get("graph_version"), "시험 전제: 판이 바뀌어 판 이전이 돌았다")
        return ns

    def pieces(self):
        return [n for n in self.pg()["nodes"] if "-split-" in str(n.get("source_object_id"))]

    def test_one_valve_split_off_keeps_every_member(self):
        ns = self.accept(self.cands[:1])
        seg = ns["nodes"][0]
        self.assertEqual((seg.get("lost") or [], ns.get("tombstones") or {}), ([], {}), "덩어리에서 하나를 떼어 낸 수락이 구성요소를 잃음")
        self.assertEqual(self.sids(seg["members"]), sorted([BLOB] + OTHERS))
        got = self.pieces()
        self.assertEqual(len(got), 1, "떼어 낸 밸브가 새 구성요소 하나가 된다")
        self.assertNotIn(got[0]["entity_id"], seg["members"], "새 조각은 사람이 넣기 전에는 구간에 들지 않는다")

    def test_two_acceptances_one_after_the_other_keep_every_member(self):
        self.accept(self.cands[:1])
        ns = self.accept(self.cands[1:2])
        seg = ns["nodes"][0]
        self.assertEqual((seg.get("lost") or [], ns.get("tombstones") or {}), ([], {}))
        self.assertEqual(self.sids(seg["members"]), sorted([BLOB] + OTHERS))
        self.assertEqual(len(self.pieces()), 2)

    def test_splitting_the_whole_lump_loses_only_the_lump(self):
        ns = self.accept(self.cands)
        seg = ns["nodes"][0]
        self.assertEqual(self.sids(seg["members"]), sorted(OTHERS), "옆 밸브 둘은 그대로")
        self.assertEqual(len(seg.get("lost") or []), 1, "없어진 덩어리 하나만 '찾지 못한 구성요소'로 남는다")
        self.assertEqual(len(self.pieces()), 3)

    def test_reverting_the_acceptance_brings_the_members_back(self):
        self.accept(self.cands)
        doc = ai_review.load_doc(self.name)
        r = api_aireview._decide(self.eng, self.gid, self.cands, "revert", sheet_refresh.ver_of(self.name))
        self.assertTrue(r.get("ok"), r)
        self.assertIsNotNone(doc)
        ns = self.build()
        seg = ns["nodes"][0]
        self.assertEqual(self.sids(seg["members"]), sorted([BLOB] + OTHERS), "되돌리면 덩어리가 돌아와 구성원으로 다시 든다")
        self.assertEqual(seg.get("lost") or [], [])
        self.assertEqual(self.pieces(), [])

    def test_candidate_place_is_found_again_after_the_build(self):
        self.accept(self.cands[:1])
        shown = {n["source_object_id"]: n for n in corrections.resolve(self.name)["corrected"]["nodes"]}
        c = next(x for x in ai_review.load_doc(self.name)["candidates"] if x["cand_id"] == self.cands[1])
        body = next(n for n in shown.values() if set(c["pdf_objects"]) <= set((n.get("evidence") or {}).get("pdf_objects") or ()))
        self.assertEqual(body["source_object_id"], BLOB, "몸체가 덩어리 순번을 잇는다")
        self.assertEqual(api_aireview._row(c, shown)["local_id"], body["local_id"], "남은 나누기 후보는 그 개체를 품은 몸체 자리로 다시 찾는다")


del Base

if __name__ == "__main__":
    unittest.main()
