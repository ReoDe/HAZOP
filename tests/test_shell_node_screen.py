"""범례·기호표 도면을 구간 분석에서 빼기(B2)와 옛 스크리닝 값 읽기. 실행: python -m unittest tests.test_shell_node_screen

- 도면 빼기: 명령 `nodes.exclude_drawing`과 읽기 `nodes/drawings`. 표시 파일의 판(ver)을 대조하고, 그 도면의 구성요소를 품은 구간이
  있으면 확인 글(걸리는 구간·승인 항목·초기사건 그룹 수)을 돌려받아 같은 글을 다시 보내야 저장한다. 도면을 빼도 이미 있는 구간·결과·
  초기사건 인계는 그대로다(새 구간 제안에서만 빠진다).
- 구간 단위 '분석에서 제외'는 규격 v2(study-node-segmentation §0, 총괄 판정 2026-11-14)대로 없다. ⑤ 행은 확정·잠금 구간 전부다.
  0.2 집합에 남은 옛 `screen.status: excluded` 구간은 '적용됨'(미확정)으로 읽는다: 칸은 지우지 않고 다시 확정하면 ⑤에 들어온다.
- 구간 명령과 도면 빼기는 프로젝트 잠금 안에서 읽기 → 대조 → 쓰기를 하고, 쓰기는 읽은 지문과 대조한다.
"""

import json
import os
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop import store_io  # noqa: E402
from hazop.shell import api, api_nodes, api_results  # noqa: E402
from hazop.study import node_commands, node_tools, nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_shell_nodes import S101, S102, Env  # noqa: E402
from tests.test_study_results import entry  # noqa: E402


class Base(Env):
    def node(self, nid):
        return next(n for n in api_nodes.summary(self.engine)["nodes"] if n["node_id"] == nid)

    def rows(self):
        return [n["node_id"] for n in api_results.scope_rows(nodes.load(self.pg))]

    def confirmed_node(self, sheet=S101, name="가압기 계통", a=0, b=6):
        nid = self.create(name, a=a, b=b, sheet=sheet)["data"]["node_ids"][0]
        self.assertTrue(self.call("confirm", {"node_ids": [nid]})["ok"])
        return nid

    def approve_one(self, nid):
        ns = nodes.load(self.pg)
        doc, fp = res.load_fp(ns)
        doc = doc or res.empty_results(ns, res.load_deviations())
        cell = next(c for c in doc["cells"] if c["node_id"] == nid)
        e = entry("e-" + nid, status="approved")
        e["ie_hint"] = {"origin": "human", "candidate": "yes", "category": None}
        cell["entries"], cell["state"] = [e], "analyzed"
        res.save_fp(doc, ns["project_id"], expect=fp)

    def drawings(self):
        return {d["graph_id"]: d for d in api_nodes.drawings_view(self.engine)["drawings"]}

    def exclude(self, gid, excluded=True, reason="범례·기호표 도면", **kw):
        d = self.drawings()[gid]
        args = {"project_id": self.engine.project_id(), "graph_id": gid, "excluded": excluded, "ver": d["ver"]}
        if reason is not None:
            args["reason"] = reason
        args.update(kw)
        return self.engine.dispatch("nodes.exclude_drawing", args)


class NoNodeScreenTest(Base):
    def test_there_is_no_node_level_exclusion(self):
        self.assertNotIn("nodes.screen", api.COMMANDS)
        self.assertNotIn("screen", node_commands.COMMANDS)

    def test_rows_are_every_confirmed_and_locked_node(self):
        """규격 D6: ⑤ 행은 확정·잠금 구간 전부. 등급 '낮음'은 정렬에만 쓴다(뒤로)."""
        a = self.confirmed_node(name="가", a=0, b=6)
        b = self.confirmed_node(name="나", a=6, b=12)
        ns = nodes.load(self.pg)
        next(n for n in ns["nodes"] if n["node_id"] == a)["screen"] = {"status": "low", "score": 1, "grade": "낮음", "rule": "R4",
                                                                       "reason": None, "by": "rule"}
        self.assertEqual([n["node_id"] for n in api_results.scope_rows(ns)], [b, a])


class LegacyScreenTest(Base):
    """0.2 집합에 남은 옛 '스크리닝 제외' 구간(규칙 R3 또는 B2 시험판의 사람 판정)."""

    def legacy_excluded(self, nid):
        path = nodes.store_path(self.pg["project_id"], self.pg["graph_id"])
        raw = json.loads(store_io.read_bytes(path)[0].decode("utf-8"))
        n = next(x for x in raw["nodes"] if x["node_id"] == nid)
        n["screen"] = {"status": "excluded", "score": None, "grade": None, "rule": None, "by": "human", "reason": "범위 밖",
                       "decided_by": "홍길동", "at": "2026-11-14T00:00:00Z"}
        store_io.write_json(path, raw, sort_keys=False)

    def test_old_excluded_node_reads_as_unconfirmed_and_keeps_its_results(self):
        nid = self.confirmed_node()
        self.approve_one(nid)
        rpath = res.store_path(self.pg["project_id"], self.pg["graph_id"])
        before = store_io.read_bytes(rpath)[0]
        self.legacy_excluded(nid)
        ns = nodes.load(self.pg)
        n = next(x for x in ns["nodes"] if x["node_id"] == nid)
        self.assertEqual((nodes.node_state(n), n.get("screen")), ("applied", None), "미확정으로 읽고 옛 판정은 떼어 둔다")
        self.assertEqual(n["legacy_screen"]["reason"], "범위 밖", "옛 판정은 기록으로 남는다")
        self.assertNotIn(nid, self.rows(), "조용히 분석에 들어가지 않는다")
        self.assertEqual(store_io.read_bytes(rpath)[0], before, "결과 파일은 읽기만으로 바뀌지 않는다")
        self.assertEqual(self.node(nid)["state"], "applied", "화면도 같은 상태를 본다")
        self.assertTrue(self.call("confirm", {"node_ids": [nid]})["ok"], "사람이 다시 확정할 수 있다")
        self.assertIn(nid, self.rows())
        doc = res.load_fp(nodes.load(self.pg))[0]
        self.assertEqual([e["status"] for c in doc["cells"] if c["node_id"] == nid for e in c["entries"]], ["approved"],
                         "승인 항목이 그대로 돌아온다")


class DrawingExcludeTest(Base):
    def test_exclude_and_restore_a_drawing(self):
        self.assertFalse(self.drawings()[S102]["excluded"])

        def only_102():
            node_tools._CACHE.clear()
            cands = node_tools.make_candidates(self.pg, nodes.new_set(self.pg), limit=500)["candidates"]
            return [c for c in cands if c.get("drawings") == ["SNP-M-102"]]
        self.assertTrue(only_102(), "빼기 전에는 그 도면만의 후보가 있음")
        r = self.exclude(S102)
        self.assertTrue(r["ok"] and not r["data"].get("needs_confirm"), r)
        d = self.drawings()[S102]
        self.assertEqual((d["excluded"], d["reason"], d["by"]), (True, "범례·기호표 도면", "홍길동"))
        self.assertEqual(nodes.exclusion_for(self.pg), (frozenset({S102}), None))
        self.assertEqual(only_102(), [], "그 도면만의 구간 후보가 빠짐")
        r = self.exclude(S102, excluded=False, reason=None)
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.drawings()[S102]["excluded"])

    def grouped(self, sheet=S102, confirm=False):
        from hazop.ie import model
        nid = self.confirmed_node(sheet=sheet)
        self.approve_one(nid)
        ns = nodes.load(self.pg)
        doc = res.load_fp(ns)[0]
        ie = model.sync(model.empty(ns["project_id"]), doc, node_set=ns)
        ie, gid = model.create_group(ie, "그룹 가", list(ie["candidates"]))
        if confirm:
            ie = model.confirm(ie, gid, doc, "검토자", node_set=ns)
        return nid, ie

    def test_confirm_text_counts_what_holds_the_drawing(self):
        from hazop.ie import store as ie_store
        nid, ie = self.grouped()
        ie_store.save(ie, expect=None)
        self.assertEqual([x["node_id"] for x in self.drawings()[S102]["nodes"]], [nid])
        ask = self.exclude(S102)["data"]["needs_confirm"]
        for part in ("구간 1곳", "승인 항목 1건", "초기사건 그룹 1개", "그대로"):
            self.assertIn(part, ask)
        self.assertFalse(self.drawings()[S102]["excluded"], "확인 전에는 저장하지 않음")
        self.assertTrue(self.exclude(S102, confirm="다른 글")["data"].get("needs_confirm"), "글이 다르면 다시 묻는다")
        r = self.exclude(S102, confirm=ask)
        self.assertTrue(r["ok"] and not r["data"].get("needs_confirm"), r)
        self.assertTrue(self.drawings()[S102]["excluded"])

    def test_excluding_a_drawing_leaves_the_handover_bundle_alone(self):
        """총괄 재현(repro_b2_bundle)을 도면 빼기로 옮긴 것: 그룹 구성원이 묶음 후보를 그대로 가리키고 확정도 그대로다."""
        from hazop.ie import bundle, model
        _nid, ie = self.grouped(confirm=True)
        ns = nodes.load(self.pg)
        doc = res.load_fp(ns)[0]
        before = bundle.build_bundle(doc, ns, self.pg, ie, "2026-11-14T00:00:00Z")
        ask = self.exclude(S102)["data"]["needs_confirm"]
        self.assertTrue(self.exclude(S102, confirm=ask)["ok"])
        ns = nodes.load(self.pg)
        doc = res.load_fp(ns)[0]
        after = bundle.build_bundle(doc, ns, self.pg, model.sync(ie, doc, node_set=ns), "2026-11-14T00:00:00Z")
        cands = {c["candidate_id"] for c in after["candidates"]}
        self.assertTrue(cands)
        self.assertEqual(cands, {c["candidate_id"] for c in before["candidates"]})
        self.assertEqual([m for g in after["groups"] for m in g["members"] if m not in cands], [])
        self.assertEqual([g["status"] for g in after["groups"]], [g["status"] for g in before["groups"]])

    def test_stale_ver_is_refused(self):
        old = self.drawings()[S101]["ver"]
        self.assertTrue(self.exclude(S102)["ok"])
        r = self.exclude(S101, ver=old)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)
        self.assertFalse(self.drawings()[S101]["excluded"])

    def test_a_write_between_check_and_save_is_not_overwritten(self):
        """총괄 재현(repro_b1_b2_misc B2): 판 대조 뒤 다른 쪽이 102를 빼면, 101 빼기는 거절되고 102 표시는 남는다."""
        ver = self.drawings()[S101]["ver"]
        real = nodes._read_excluded
        done = []

        def other_writer(pid):
            out = real(pid)
            if not done:
                done.append(1)
                nodes.set_excluded(pid, "SNP-M-102", True, "다른 사람", "범례", expect=out[2])
            return out
        with mock.patch.object(nodes, "_read_excluded", side_effect=other_writer):
            out = node_commands.exclude_drawing(self.pg, S101, True, by="홍길동", reason="범례", ver=ver)
        self.assertEqual((out["ok"], out["refused"][0]["code"]), (False, "stale"), out)
        self.assertEqual(sorted(nodes.load_excluded(self.pg["project_id"])), ["SNP-M-102"])

    def test_dry_run_gives_the_same_question_and_saves_nothing(self):
        """채팅 확인 상자용: dry는 실제 저장 때와 같은 확인 글을 돌려주고 파일을 쓰지 않는다."""
        from hazop.ie import store as ie_store
        _nid, ie = self.grouped()
        ie_store.save(ie, expect=None)
        ver = self.drawings()[S102]["ver"]
        dry = node_commands.exclude_drawing(self.pg, S102, True, by="홍길동", ver=ver, dry=True)
        self.assertEqual((dry["ok"], dry["dry"], dry["changed"]), (True, True, True))
        real = self.exclude(S102)["data"]["needs_confirm"]
        self.assertEqual(dry["needs_confirm"], real)
        self.assertFalse(self.drawings()[S102]["excluded"])
        self.assertEqual(node_commands.exclude_drawing(self.pg, S101, True, by="홍길동", ver=ver, dry=True)["needs_confirm"], None,
                         "품은 구간이 없으면 묻지 않는다")

    def test_ver_is_required(self):
        with self.assertRaises(TypeError):
            node_commands.exclude_drawing(self.pg, S101, True, by="홍길동")
        out = node_commands.exclude_drawing(self.pg, S101, True, by="홍길동", ver=None)
        self.assertEqual((out["ok"], out["refused"][0]["target"]), (False, "ver"))

    def test_drawing_without_a_number_is_refused(self):
        self.pg = dict(self.pg, sheets=[dict(s, drawing_number=None) if s["graph_id"] == S101 else s for s in self.pg["sheets"]])
        r = self.exclude(S101)
        self.assertFalse(r["ok"])
        self.assertIn("도면 번호", r["error"]["message"])

    def test_wrong_project_is_refused(self):
        d = self.drawings()[S102]
        r = self.engine.dispatch("nodes.exclude_drawing", {"project_id": "OTHER", "graph_id": S102, "excluded": True,
                                                            "reason": "x", "ver": d["ver"]})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"))

    def test_legend_looking_drawing_gets_a_hint(self):
        with mock.patch.object(api_nodes, "_drawing_texts", lambda: {"SNP-M-102": ("SNP-M-102 Legend.drawio", "기호표")}):
            d = self.drawings()
        self.assertTrue(d[S102]["legend_hint"])
        self.assertFalse(d[S101]["legend_hint"])

    def test_excel_cover_lists_excluded_drawings(self):
        import openpyxl
        nid = self.confirmed_node()
        self.approve_one(nid)
        self.assertTrue(self.exclude(S102, reason="기호표뿐")["ok"])
        out = os.path.join(self.tmp, "x.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        r = self.engine.dispatch("results.export_excel", {"scope": "all"})
        self.assertTrue(r["ok"], r)
        cover = [tuple(c for c in row if c is not None) for row in openpyxl.load_workbook(out).worksheets[0].iter_rows(values_only=True)]
        hit = [row for row in cover if row and row[0] == "분석에서 뺀 도면"]
        self.assertEqual(len(hit), 1, cover)
        self.assertIn("SNP-M-102", hit[0][1])
        self.assertIn("기호표뿐", hit[0][1])


class LockTest(Base):
    def test_node_commands_wait_for_the_project_lock(self):
        rev = self.rev()
        members = [n["entity_id"] for n in self.pg["nodes"] if n.get("sheet") == S101][:4]
        done = []
        with node_commands.project_lock(self.pg["project_id"]):
            t = threading.Thread(target=lambda: done.append(node_commands.execute(
                self.pg, "create", {"items": [{"members": members, "name": "가"}]}, author="user", confirmed_by="홍길동", set_rev=rev)))
            t.start()
            t.join(0.5)
            self.assertTrue(t.is_alive(), "잠금을 쥔 동안에는 기다린다")
        t.join(10)
        self.assertTrue(done and done[0]["ok"], done)

    def test_ai_commands_need_the_set_rev(self):
        out = node_commands.execute(self.pg, "rename", {"node_id": "S1", "name": "x"}, author="ai", set_rev=None)
        self.assertFalse(out["ok"])
        self.assertEqual(out["refused"][0]["target"], "set_rev")


if __name__ == "__main__":
    unittest.main()
