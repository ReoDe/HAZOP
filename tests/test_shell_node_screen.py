"""구간 스크리닝 제외와 도면 빼기(B2): 명령 `nodes.screen`·`nodes.exclude_drawing`과 읽기 `nodes/drawings`.
실행: python -m unittest tests.test_shell_node_screen

제외한 구간은 분석 행(행렬·일괄 분석·Excel 범위)에서 빠지고, 다시 넣으면 돌아온다. 확정·잠금 구간이나 결과가 있는 구간을 뺄 때는
엔진이 확인 글을 돌려주고 같은 글이 다시 와야 저장한다. 결과는 지우지 않는다. 낡은 판은 거절한다.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.shell import api_nodes, api_results  # noqa: E402
from hazop.study import node_commands, node_tools, nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_shell_nodes import S101, S102, Env, _rb  # noqa: E402
from tests.test_study_results import entry  # noqa: E402


class Base(Env):
    def node(self, nid):
        return next(n for n in api_nodes.summary(self.engine)["nodes"] if n["node_id"] == nid)

    def rows(self):
        return [n["node_id"] for n in api_results.scope_rows(nodes.load(self.pg))]

    def screen(self, nid, status, reason=None, **kw):
        args = {"node_id": nid, "status": status}
        if reason is not None:
            args["reason"] = reason
        return self.call("screen", args, **kw)

    def confirmed_node(self):
        r = self.create("가압기 계통")
        nid = r["data"]["node_ids"][0]
        self.assertTrue(self.call("confirm", {"node_ids": [nid]})["ok"])
        return nid

    def with_entries(self, nid, n=1):
        """그 구간의 칸 n개에 항목을 넣는다(시험 편차표는 편차 하나라 구간마다 칸 하나)."""
        ns = nodes.load(self.pg)
        doc, fp = res.load_fp(ns)
        doc = doc or res.empty_results(ns, res.load_deviations())
        cells = [c for c in doc["cells"] if c["node_id"] == nid][:n]
        for i, c in enumerate(cells):
            c["entries"] = [entry("e-%s-%d" % (nid, i))]
            c["state"] = "analyzed"
        res.save_fp(doc, ns["project_id"], expect=fp)
        return res.store_path(ns["project_id"], ns["graph_id"])


class NodeScreenTest(Base):
    def test_exclude_and_restore_a_draft_node(self):
        nid = self.create()["data"]["node_ids"][0]
        r = self.screen(nid, "excluded", "범례 기호만 든 구간")
        self.assertTrue(r["ok"], r)
        row = self.node(nid)
        self.assertEqual((row["screen"], row["screen_reason"], row["screen_by"]), ("excluded", "범례 기호만 든 구간", "홍길동"))
        self.assertEqual(row["state"], "applied", "판정만 바뀌고 상태는 그대로")
        r = self.screen(nid, "keep")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.node(nid)["screen"], "keep")

    def test_reason_is_required_to_exclude(self):
        nid = self.create()["data"]["node_ids"][0]
        before = self.rev()
        r = self.screen(nid, "excluded", "  ")
        self.assertFalse(r["ok"])
        self.assertIn("이유", r["error"]["message"])
        self.assertEqual(self.rev(), before, "저장하지 않음")

    def test_stale_set_rev_is_refused(self):
        nid = self.create()["data"]["node_ids"][0]
        old = self.rev()
        self.call("rename", {"node_id": nid, "name": "새 이름"})
        r = self.screen(nid, "excluded", "이유", set_rev=old)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)
        self.assertIsNone(self.node(nid)["screen"])

    def test_confirmed_node_asks_first_then_leaves_rows_and_keeps_results(self):
        nid = self.confirmed_node()
        path = self.with_entries(nid)
        self.assertIn(nid, self.rows())
        before_bytes, rev_before, node_rev = _rb(path), self.rev(), self.node(nid)["rev"]
        r = self.screen(nid, "excluded", "보조 계통이라 범위 밖")
        self.assertTrue(r["ok"], r)
        ask = r["data"]["needs_confirm"]
        self.assertIn("확정", ask)
        self.assertIn("결과 1칸", ask)
        self.assertEqual(self.rev(), rev_before, "확인 전에는 저장하지 않음")
        r = self.screen(nid, "excluded", "보조 계통이라 범위 밖", confirm="다른 글")
        self.assertEqual(r["data"].get("needs_confirm"), ask, "글이 다르면 다시 묻는다")
        r = self.screen(nid, "excluded", "보조 계통이라 범위 밖", confirm=ask)
        self.assertTrue(r["ok"] and not r["data"].get("needs_confirm"), r)
        self.assertNotIn(nid, self.rows(), "분석 행에서 빠짐")
        row = self.node(nid)
        self.assertEqual((row["state"], row["rev"]), ("confirmed", node_rev), "확정·rev는 그대로(칸이 '범위 바뀜'이 되지 않게)")
        self.assertEqual(_rb(path), before_bytes, "결과 파일은 그대로")
        r = self.screen(nid, "keep")
        self.assertTrue(r["ok"] and not r["data"].get("needs_confirm"), "다시 넣기는 묻지 않는다")
        self.assertIn(nid, self.rows(), "다시 분석 행에 들어옴")

    def test_locked_node_can_be_excluded_with_confirmation(self):
        nid = self.confirmed_node()
        ns = nodes.load(self.pg)
        node = next(n for n in ns["nodes"] if n["node_id"] == nid)
        node["state"], node["locked"] = "locked", {"by": "홍길동", "at": "2026-11-14T00:00:00Z"}
        nodes.save(ns)
        r = self.screen(nid, "excluded", "중복 구간")
        self.assertIn("잠긴", r["data"]["needs_confirm"])
        r = self.screen(nid, "excluded", "중복 구간", confirm=r["data"]["needs_confirm"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.node(nid)["state"], "locked")
        self.assertNotIn(nid, self.rows())

    def test_unconfirmed_node_with_results_asks(self):
        """확정을 풀어도 칸의 결과는 남는다. 그 구간을 뺄 때도 묻는다."""
        nid = self.confirmed_node()
        self.with_entries(nid, 1)
        self.assertTrue(self.call("unconfirm", {"node_ids": [nid]})["ok"])
        r = self.screen(nid, "excluded", "이유")
        self.assertIn("결과 1칸", r["data"]["needs_confirm"])

    def test_history_records_who_and_why(self):
        nid = self.create()["data"]["node_ids"][0]
        self.screen(nid, "excluded", "범례")
        h = nodes.load(self.pg)["history"][-1]
        self.assertEqual(h["op"], "screen_set")
        self.assertEqual((h["detail"]["node_id"], h["detail"]["to"], h["detail"]["by"], h["detail"]["reason"]),
                         (nid, "excluded", "홍길동", "범례"))

    def test_reviewer_is_required(self):
        nid = self.create()["data"]["node_ids"][0]
        self.engine.settings["reviewer_name"] = ""
        r = self.screen(nid, "excluded", "이유")
        self.assertEqual(r["error"]["code"], "bad_args")

    def test_engine_entry_for_chat(self):
        """채팅이 부를 실행 길: AI 동작은 사람이 확인 상자를 눌렀을 때(confirmed_by)만 쓴다."""
        nid = self.create()["data"]["node_ids"][0]
        rev = self.rev()
        out = node_commands.execute(self.pg, "screen", {"node_id": nid, "status": "excluded", "reason": "범례"}, author="ai",
                                    set_rev=rev)
        self.assertEqual(out["refused"][0]["code"], "bad_actor")
        out = node_commands.execute(self.pg, "screen", {"node_id": nid, "status": "excluded", "reason": "범례"}, author="ai",
                                    confirmed_by="홍길동", set_rev=rev)
        self.assertTrue(out["ok"], out)
        nid2 = self.create("둘째", a=8, b=14)["data"]["node_ids"][0]
        self.assertTrue(self.call("confirm", {"node_ids": [nid2]})["ok"])
        out = node_commands.execute(self.pg, "screen", {"node_id": nid2, "status": "excluded", "reason": "x"}, author="user",
                                    confirmed_by="홍길동", set_rev=self.rev())
        self.assertEqual((out["ok"], out["refused"][0]["code"]), (False, "confirm"))
        self.assertTrue(out["needs_confirm"])


class EditPathTest(Base):
    """검토 지적(B2 1회): 웹의 합치기·나누기(apply_nodes)가 사람의 제외 판정을 말없이 바꾸지 않는다. 초기사건 인계도 제외 구간을 뺀다."""

    def test_merge_of_excluded_and_kept_nodes_is_refused(self):
        a = self.create("가", a=0, b=6)["data"]["node_ids"][0]
        b = self.create("나", a=6, b=12)["data"]["node_ids"][0]
        self.assertTrue(self.screen(a, "excluded", "범례")["ok"])
        for order in ([a, b], [b, a]):
            r = self.call("merge", {"node_ids": order})
            self.assertFalse(r["ok"], order)
            self.assertIn("제외", r["error"]["message"])
        self.assertEqual(self.node(a)["screen"], "excluded")

    def test_split_of_an_excluded_node_keeps_the_piece_excluded(self):
        from tests.test_shell_nodes import S101 as sheet
        nid = self.create("가", a=0, b=6)["data"]["node_ids"][0]
        self.assertTrue(self.screen(nid, "excluded", "범례")["ok"])
        r = self.call("split", {"node_id": nid, "sheet": sheet, "ids": self.local(sheet, 0, 2)})
        self.assertTrue(r["ok"], r)
        new = r["data"]["node_ids"][0]
        self.assertEqual((self.node(nid)["screen"], self.node(new)["screen"]), ("excluded", "excluded"))
        self.assertEqual(self.node(new)["screen_reason"], "범례")

    def test_handover_bundle_leaves_out_an_excluded_node(self):
        from hazop.ie import bundle
        nid = self.confirmed_node()
        ns = nodes.load(self.pg)
        doc, fp = res.load_fp(ns)
        doc = doc or res.empty_results(ns, res.load_deviations())
        cell = next(c for c in doc["cells"] if c["node_id"] == nid)
        cell["entries"], cell["state"] = [entry("e1", status="approved")], "analyzed"
        res.save_fp(doc, ns["project_id"], expect=fp)
        picked, _left = bundle.approved_entries(res.load_fp(nodes.load(self.pg))[0], nodes.load(self.pg))
        self.assertEqual([p[0] for p in picked], [nid])
        ask = self.screen(nid, "excluded", "범위 밖")["data"]["needs_confirm"]
        self.assertIn("초기사건 인계", ask)
        self.assertTrue(self.screen(nid, "excluded", "범위 밖", confirm=ask)["ok"])
        picked, left = bundle.approved_entries(res.load_fp(nodes.load(self.pg))[0], nodes.load(self.pg))
        self.assertEqual((picked, left), ([], 1), "제외 구간의 승인 항목은 넣지 않은 수로 센다")


class DrawingExcludeTest(Base):
    def drawings(self):
        return {d["graph_id"]: d for d in api_nodes.drawings_view(self.engine)["drawings"]}

    def exclude(self, gid, excluded=True, reason="범례·기호표 도면", **kw):
        d = self.drawings()[gid]
        args = {"project_id": self.engine.project_id(), "graph_id": gid, "excluded": excluded, "ver": d["ver"]}
        if reason is not None:
            args["reason"] = reason
        args.update(kw)
        return self.engine.dispatch("nodes.exclude_drawing", args)

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
        sheets, problem = nodes.exclusion_for(self.pg)
        self.assertEqual((sheets, problem), (frozenset({S102}), None))
        self.assertEqual(only_102(), [], "그 도면만의 구간 후보가 빠짐")
        r = self.exclude(S102, excluded=False, reason=None)
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.drawings()[S102]["excluded"])

    def test_nodes_that_hold_its_components_are_shown_and_asked(self):
        nid = self.create(sheet=S102)["data"]["node_ids"][0]
        d = self.drawings()[S102]
        self.assertEqual([x["node_id"] for x in d["nodes"]], [nid])
        r = self.exclude(S102)
        ask = r["data"]["needs_confirm"]
        self.assertIn(nid, ask)
        self.assertIn("그대로", ask, "도면을 빼도 그 구간은 그대로 분석된다고 알림")
        self.assertFalse(self.drawings()[S102]["excluded"], "확인 전에는 저장하지 않음")
        r = self.exclude(S102, confirm=ask)
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.drawings()[S102]["excluded"])
        self.assertIn(nid, [n["node_id"] for n in api_nodes.summary(self.engine)["nodes"]])

    def test_stale_ver_is_refused(self):
        old = self.drawings()[S101]["ver"]
        self.assertTrue(self.exclude(S102)["ok"])
        r = self.exclude(S101, ver=old)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)
        self.assertFalse(self.drawings()[S101]["excluded"])

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


if __name__ == "__main__":
    unittest.main()
