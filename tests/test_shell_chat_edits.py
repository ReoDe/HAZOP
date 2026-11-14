"""채팅 동작 A11 2차 마무리(표제란·도면 고치기·FMEA·MLD·문서 판 대응) 시험. 실행: python -m unittest tests.test_shell_chat_edits

엔진 함수는 가짜로 바꾸고, 채팅 연결부가 지키는 것만 본다: 확인 상자에 저장될 값이 모두 보이고, 상자에서 본 판·지문·확인 글을
실행 때 그대로 넘기고, 같은 자료의 작업을 겹쳐 시작하지 않고, 작업 끝과 거절을 기록에 남긴다. 구독 호출 없음.
"""

import copy
import inspect
from unittest import mock

from hazop.chat import actions as A
from hazop.shell import api_corrections, chat_edits
from tests.test_shell_chat_run import RunBase

TB_ROW = {"material_id": "M-101", "name": "SNP-M-101.pdf", "version": 2, "ver": "sha256:tb-ver-1", "state": "partial",
          "fields": [{"field": "drawing_number", "label": "도면 번호", "value": "SNP-M-101", "candidate": "SNP-M-101"},
                     {"field": "design_revision", "label": "개정", "value": None, "candidate": "3"},
                     {"field": "title", "label": "제목", "value": None, "candidate": "가압기 계통"}],
          "sheets": [{"page": 0, "version": 2, "graph_id": "graph-SNP-M-101"}], "review_data": ["구간 2곳"]}


class TitleblockTest(RunBase):
    def setUp(self):
        super().setUp()
        self.calls = []

        def dry(pid, mid, fields, by, ver, reason=None, **k):
            self.calls.append(("dry", mid, ver))
            return {"ok": True, "changed": True, "dry": True, "re_extract": True, "refused": []}
        for target, fn in (("hazop.register.titleblock.row", lambda pid, mid, store_root=None: copy.deepcopy(TB_ROW) if mid == "M-101" else None),
                           ("hazop.register.titleblock.view", lambda pid, store_root=None, material_type="P&ID": [copy.deepcopy(TB_ROW)]),
                           ("hazop.register.titleblock.confirm", dry), ("hazop.register.titleblock.unconfirm", dry),
                           ("hazop.shell.api_titleblock._h_confirm", lambda engine, a: self.calls.append(("confirm", a)) or {"changed": True, "job": "j9"}),
                           ("hazop.shell.api_titleblock._h_unconfirm", lambda engine, a: self.calls.append(("unconfirm", a)) or {"changed": True, "row": {}})):
            p = mock.patch(target, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_confirm_shows_every_value_passes_ver_and_runs_once(self):
        item = self.one("titleblock.confirm", "M-101 표제란 확정해 줘", graph_id="graph-SNP-M-101",
                        fields={"design_revision": "3", "title": "가압기 계통(수정)"}, reason="표제란 그림과 대조함")
        self.assertEqual(item["status"], "confirm")
        rows = {r["label"]: r for r in item["details"]}
        self.assertEqual((rows["개정"]["before"], rows["개정"]["after"]), ("(미확정)", "3 (후보 그대로)"))
        self.assertIn("후보 가압기 계통와 다름", rows["제목"]["after"])
        self.assertNotIn("도면 번호", rows, "보내지 않은 항목은 바뀌지 않으니 줄도 없다")
        self.assertIn("다시 추출", rows)
        self.assertEqual(rows["사유(AI가 씀)"]["after"], "표제란 그림과 대조함")
        self.actions.runner.watch = False
        self.assertTrue(self.approve(item)["ok"])
        (_k, a), = [c for c in self.calls if c[0] == "confirm"]
        self.assertEqual((a["material_id"], a["ver"]), ("M-101", "sha256:tb-ver-1"), "상자에서 본 등록정보 판을 그대로 넘긴다")
        again = self.one("titleblock.confirm", material_id="M-101", fields={"title": "다른 제목"})
        self.assertIn("이미 돌고", again["reason"])
        self.engine._jobs["j9"] = {"state": "done"}
        for run in self.actions.runner.pending:
            run()
        self.assertEqual([r["result"] for r in self.records if r["proposal"]["action"] == "titleblock.confirm"][-1], "done")
        self.assertEqual(self.actions._tb_running, set())

    def test_engine_refusal_is_shown_before_the_box(self):
        refuse = lambda *a, **k: {"ok": False, "changed": False, "refused": [{"reason": "번호를 바꾸면 구간 2곳이 끊김"}]}   # noqa: E731
        with mock.patch("hazop.register.titleblock.confirm", refuse):
            item = self.one("titleblock.confirm", material_id="M-101", fields={"drawing_number": "SNP-M-999"})
        self.assertEqual(item["status"], "rejected")
        self.assertIn("끊김", item["reason"])
        self.assertIn("없는 도면 자료", self.one("titleblock.confirm", material_id="M-404", fields={"title": "x"})["reason"])

    def test_unconfirm_without_reextract_saves_directly(self):
        item = self.one("titleblock.unconfirm", material_id="M-101", fields=["drawing_number"])
        self.assertIn("확정 취소", {r["label"]: r["after"] for r in item["details"]}["도면 번호"])
        self.assertTrue(self.approve(item)["ok"])
        (_k, a), = [c for c in self.calls if c[0] == "unconfirm"]
        self.assertEqual(a["fields"], ["drawing_number"])


VIEW = {"ok": True, "graph_id": "graph-SNP-M-101", "ver": "v-edit-1", "ops": [
    {"op_id": "op-0001", "op": "set_tag", "label": "태그", "local_id": "local-node-003", "by": "홍길동", "at": "2026-11-14T00:00:00Z"}],
    "undoable": ["op-0001"], "redo": None, "graph_stale": False}
ITEM = {"ok": True, "graph_id": "graph-SNP-M-101", "local_id": "local-node-003", "type": "node", "kind": "pump", "kind_label": "펌프",
        "tag": "RC-PP01", "base": "fp-item-1", "impact": {"sheet": "confirmed", "nodes": [{"node_id": "S1", "state": "applied"}]}, "positions": []}


class DrawingTest(RunBase):
    def setUp(self):
        super().setUp()
        self.view, self.ask_text, self.saved = copy.deepcopy(VIEW), None, []
        ok = {"ok": True, "notes": ["저장했습니다."], "op_id": "op-0002", "label": "태그"}
        for target, fn in (("hazop.shell.api_corrections.view", lambda engine, gid: copy.deepcopy(self.view)),
                           ("hazop.shell.api_corrections.item", lambda engine, gid, lid: copy.deepcopy(ITEM)),
                           ("hazop.shell.api_corrections.apply_edit", lambda *a, **k: self.saved.append(("apply", a, k)) or dict(ok)),
                           ("hazop.shell.api_corrections.undo", lambda *a, **k: self.saved.append(("undo", a, k)) or dict(ok, op_id="op-0001")),
                           ("hazop.shell.chat_edits._ask_text", lambda *a: self.ask_text),
                           ("hazop.shell.chat_edits._undo_ask", lambda *a: None),
                           ("hazop.app.project_ctx.project_graph", lambda pid: self.pg)):
            p = mock.patch(target, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_tag_edit_by_component_id_shows_before_after_and_passes_ver_base(self):
        item = self.one("drawing.edit", "RC-PP01 태그를 RC-PP01A로 고쳐 줘", op="set_tag", id="rc-pp01", value={"tag": "RC-PP01A"})
        self.assertEqual(item["status"], "confirm")
        rows = {r["label"]: r for r in item["details"]}
        self.assertEqual((rows["태그"]["before"], rows["태그"]["after"]), ("RC-PP01", "RC-PP01A"))
        self.assertIn("확정이 풀릴", rows["쪽 확정"]["after"])
        self.assertIn("S1", rows["이 항목이 든 구간"]["after"])
        self.assertTrue(self.approve(item)["ok"])
        (_k, a, k), = self.saved
        self.assertEqual(a[1:6], ("graph-SNP-M-101", "set_tag", "local-node-003", {"tag": "RC-PP01A"}, "v-edit-1"))
        self.assertEqual((k["base"], k["confirm"]), ("fp-item-1", None))

    def test_engine_question_seen_in_the_box_is_passed_as_confirm(self):
        self.ask_text = "지우기: local-node-003을(를) 지웁니다. 되돌리기로 살릴 수 있습니다."
        item = self.one("drawing.edit", op="delete_node", id="rc-pp01")
        self.assertEqual({r["label"]: r["after"] for r in item["details"]}["엔진 확인"], self.ask_text)
        self.approve(item)
        (_k, _a, k), = self.saved
        self.assertEqual(k["confirm"], self.ask_text, "엔진이 물은 글을 상자에서 본 그대로 넘긴다")

    def test_question_changed_after_the_box_is_stale_and_engine_needs_confirm_is_refused(self):
        item = self.one("drawing.edit", op="delete_node", id="rc-pp01")
        self.ask_text = "지우기: … 확정·잠금 구간 S1에 든 구성요소입니다."
        self.approve(item)
        self.assertEqual(self.saved, [], "확인 상자 줄이 바뀌면 실행하지 않는다")
        self.ask_text = None
        with mock.patch("hazop.shell.api_corrections.apply_edit", lambda *a, **k: {"ok": False, "code": "needs_confirm", "message": "새 물음"}):
            self.approve(self.one("drawing.edit", op="set_tag", id="rc-pp01", value={"tag": "X"}))
        done = self.events.of("chat.action.result")[-1]["item"]
        self.assertEqual(done["status"], "rejected")
        self.assertIn("새 물음", done["reason"])

    def test_undo_picks_the_last_undoable_and_redo_needs_something(self):
        item = self.one("drawing.undo", "방금 고친 거 되돌려 줘", graph_id="graph-SNP-M-101")
        self.assertIn("op-0001 태그", {r["label"]: r["after"] for r in item["details"]}["되돌릴 고침"])
        self.approve(item)
        (k, a, kw), = self.saved
        self.assertEqual((k, a[1], a[2], a[3]), ("undo", "graph-SNP-M-101", "op-0001", "v-edit-1"))
        self.assertIn("다시 할 고침이 없음", self.one("drawing.redo", graph_id="graph-SNP-M-101")["reason"])
        self.assertIn("되돌릴 수 없는", self.one("drawing.undo", graph_id="graph-SNP-M-101", op_id="op-0099")["reason"])

    def test_unknown_op_and_missing_target_are_refused(self):
        self.assertIn("모르는 고침", self.one("drawing.edit", op="paint", id="rc-pp01")["reason"])
        self.assertIn("고칠 항목", self.one("drawing.edit", op="set_tag", graph_id="graph-SNP-M-101", value={"tag": "X"})["reason"])

    def test_tag_question_text_is_the_engine_text(self):
        src = inspect.getsource(api_corrections)
        self.assertIn(chat_edits.TAG_ASK.split("%s")[0], src)
        self.assertIn(chat_edits.TAG_ASK.split("%s")[-1], src)


class P5Test(RunBase):
    def setUp(self):
        super().setUp()
        self.fmea = {"fver": "fv1", "rows": [{"row_id": "FM-001", "status": "imported", "tag": "RC-PP01", "failure_mode": "정지",
                                              "effect": "유량 상실", "fp": "sha256:r1"}],
                     "ec_nodes": [{"node_id": "S1", "mark": None, "rule": True}]}
        self.mld = {"mver": "mv1", "loaded": True, "branches": [{"id": "B-1", "group_ids": [], "fp": "sha256:b1"}],
                    "groups": [{"group_id": "IEG-01", "name": "급수 상실"}]}
        self.saved = []
        ctx = (self.pg, {"nodes": [{"node_id": "S1"}, {"node_id": "S2"}]}, {}, {}, None)
        for target, fn in (("hazop.shell.api_ie.fmea_view", lambda engine: copy.deepcopy(self.fmea)),
                           ("hazop.shell.api_ie.mld_view", lambda engine: copy.deepcopy(self.mld)),
                           ("hazop.shell.api_ie._context", lambda engine: (ctx, None)),
                           ("hazop.shell.api_ie.set_fmea_status", lambda engine, a: self.saved.append(a) or {"changed": True}),
                           ("hazop.shell.api_ie.mark_ec_node", lambda engine, a: self.saved.append(a) or {"changed": True}),
                           ("hazop.shell.api_ie.link_mld_branch", lambda engine, a: self.saved.append(a) or {"changed": True})):
            p = mock.patch(target, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_fmea_status_passes_fver_and_row_fingerprints(self):
        item = self.one("ie.fmea_status", row_ids=["FM-001"], status="approved")
        row = {r["label"]: r for r in item["details"]}["FMEA FM-001"]
        self.assertEqual(row["before"], "imported")
        self.assertIn("RC-PP01 · 정지 · 유량 상실", row["after"])
        self.approve(item)
        self.assertEqual((self.saved[0]["fver"], self.saved[0]["seen"]), ("fv1", {"fmea:FM-001": "sha256:r1"}))
        self.assertIn("없는 FMEA 행", self.one("ie.fmea_status", row_ids=["FM-404"], status="approved")["reason"])
        self.assertIn("상태는", self.one("ie.fmea_status", row_ids=["FM-001"], status="done")["reason"])

    def test_mark_and_mld_link(self):
        self.approve(self.one("ie.fmea_mark", node_id="S2", mark="include"))
        self.assertEqual(self.saved[-1], {"node_id": "S2", "mark": "include", "fver": "fv1"})
        item = self.one("ie.mld_link", branch_id="B-1", group_ids=["IEG-01"])
        self.assertIn("IEG-01 급수 상실", {r["label"]: r["after"] for r in item["details"]}["MLD 가지 B-1"])
        self.approve(item)
        self.assertEqual((self.saved[-1]["mver"], self.saved[-1]["seen"]), ("mv1", {"coverage:MLD:B-1": "sha256:b1"}))
        self.assertIn("없는 초기사건 그룹", self.one("ie.mld_link", branch_id="B-1", group_ids=["IEG-99"])["reason"])
        self.mld["loaded"] = False
        self.assertIn("가져오지 않음", self.one("ie.mld_link", branch_id="B-1", group_ids=["IEG-01"])["reason"])

    def test_file_picking_stays_in_the_panel(self):
        for name in ("ie.fmea_import", "ie.mld_import"):
            self.assertEqual(self.one(name)["status"], "rejected")


class DocsRevisionTest(RunBase):
    def test_revision_answer_needs_the_question_and_shows_what_is_replaced(self):
        docs = [{"material_id": "D-002", "title": "설계 기준 Rev.1", "ask_revision": [{"material_id": "D-001", "title": "설계 기준 Rev.0"}]},
                {"material_id": "D-001", "title": "설계 기준 Rev.0", "ask_revision": []}]
        jobs = []
        with mock.patch("hazop.shell.api_docs.list_documents", lambda engine: copy.deepcopy(docs)), \
                mock.patch("hazop.shell.api_docs._h_revision", lambda engine, a: jobs.append(a) or {"job": "j5"}):
            item = self.one("docs.revision", material_id="D-002", answer="replace", old="D-001")
            self.assertIn("설계 기준 Rev.0", {r["label"]: r["after"] for r in item["details"]}["대신할 옛 판"])
            self.actions.runner.watch = False
            self.approve(item)
            self.assertEqual(jobs, [{"material_id": "D-002", "answer": "replace", "old": "D-001"}])
            self.assertIn("물음이 없음", self.one("docs.revision", material_id="D-001", answer="separate")["reason"])


class TableTest(RunBase):
    def test_new_actions_are_confirm_and_in_the_prompt(self):
        from hazop.chat import card
        for name in chat_edits.RUN_ACTIONS:
            self.assertEqual(A.ACTIONS[name].klass, A.CONFIRM, name)
            self.assertIn(name, card.PROMPT_ACTIONS)


from tests import test_shell_corrections as _real   # noqa: E402


class RealEngineQuestionTest(_real.Base):
    """확인 상자에 미리 보이는 엔진 확인 글이, 실제 엔진(api_corrections)이 묻는 글과 글자 그대로 같다(지우기·태그 겹침)."""

    def asked(self, op, local_id, value=None):
        r = self.edit(op, local_id, value)
        self.assertEqual(r["error"]["code"], "needs_confirm")
        return r["error"]["message"]

    def test_delete_and_duplicate_tag_texts_match_the_engine(self):
        n = self.tagged()
        self.assertEqual(chat_edits._ask_text(self.engine, self.gid, "delete_node", n["local_id"], {}), self.asked("delete_node", n["local_id"]))
        a, b = [x for x in self.ex["nodes"] if x.get("tag") and x.get("kind") not in (None, "tee", "continuation")][:2]
        self.assertEqual(chat_edits._ask_text(self.engine, self.gid, "set_tag", a["local_id"], {"tag": b["tag"]}),
                         self.asked("set_tag", a["local_id"], {"tag": b["tag"]}))
        self.assertIsNone(chat_edits._ask_text(self.engine, self.gid, "set_tag", a["local_id"], {"tag": "NEW-TAG-1"}))


from tests import test_shell_ie_edit as _ie   # noqa: E402


class RealIeLostGroupsTest(_ie.ReviewFixTest):
    """확인 상자에 미리 보이는 '확정이 풀리는 그룹'과 항목 지문이, 실제 ⑥ 엔진(api_ie)이 되묻는 목록·화면 지문과 같다."""

    def preview(self, action, **args):
        from hazop.shell import chat_screens
        from types import SimpleNamespace
        ctx, base, fps, _b = chat_screens._ie_ctx(self.engine)
        item = SimpleNamespace(action=action, args=args)
        return chat_screens._ie_lost(self.engine, item, ctx, base), fps

    def test_lost_groups_and_fingerprints_match_the_engine(self):
        gid = self.human_group()
        self.ok("ie.confirm", group_id=gid)
        c1 = self.iec("c1")
        lost, fps = self.preview("ie.move", iecs=[c1], to="")
        _a, ask = self.ask("ie.move", iecs=[c1], to="")
        self.assertEqual(lost, ask["groups"])
        seen = self.seen_all()
        self.assertEqual({k: fps[k] for k in seen}, seen, "채팅 지문은 화면 지문과 같다(FMEA·MLD까지 넣은 묶음)")

    # 부모의 다른 시험은 이 클래스에서 다시 돌리지 않는다
    for _n in [n for n in dir(_ie.ReviewFixTest) if n.startswith("test_")]:
        locals()[_n] = None
    del _n


from tests import test_shell_links as _links   # noqa: E402


class RealLinksQuestionTest(_links.Base):
    """도면 연결 짝(B1): 확인 상자에 미리 보이는 엔진 확인 글이 api_links가 묻는 글과 글자 그대로 같고, 묻지 않을 때는 None이다."""

    def chat(self, action, me, peer=None, op_id=None):
        from types import SimpleNamespace
        return chat_edits._link_ask(self.engine, SimpleNamespace(action=action, args={}), me, peer, op_id)

    def asked(self, name, at, **args):
        r = self.web(name, at, **args)
        self.assertEqual(r["error"]["code"], "needs_confirm", r)
        return r["error"]["message"]

    def test_unlink_pair_and_clear_texts_match_the_engine(self):
        a, b = self.linked_pair()
        self.assertEqual(self.chat("links.unlink", a), self.asked("unlink", a))
        pg = self.pg()
        other = next(n for n in pg["nodes"] if n.get("kind") == "continuation" and n.get("sheet") not in (_links.S101, a[0])
                     and (n.get("sheet_link") or {}).get("status") == "linked" and n.get("local_id"))
        peer = (other["sheet"], other["local_id"])
        self.assertEqual(self.chat("links.pair", a, peer), self.asked("pair", a, peer_graph_id=peer[0], peer_local_id=peer[1]))
        self.confirmed("unlink", a)
        self.assertIsNone(self.chat("links.pair", a, b), "짝 없는 둘을 이을 때는 묻지 않는다")
        self.confirmed("pair", a, peer_graph_id=b[0], peer_local_id=b[1])
        op = _links.project.load_manual(_links.PID)["ops"][0]["op_id"]
        self.assertEqual(self.chat("links.clear", a, op_id=op), self.asked("clear", a, op_id=op))


class LinksChatTest(RunBase):
    def setUp(self):
        super().setUp()
        self.view = {"ok": True, "ver": "lv-1", "point": {"local_id": "c1", "label": "→ M-102", "drawing_number": "SNP-M-101", "line_no": "2-RC-01",
                                                           "to_drawing": "SNP-M-102", "base": "pb-1", "peer": None, "op": None},
                     "candidates": [{"graph_id": "graph-SNP-M-102", "local_id": "c9", "drawing_number": "SNP-M-102", "label": "← M-101",
                                     "line_no": "2-RC-02", "to_drawing": "SNP-M-101", "linked": False, "warn": ["배관 번호가 다름(2-RC-02 ≠ 2-RC-01)"]}]}
        self.ask_text, self.saved = None, []
        for target, fn in (("hazop.shell.api_links.view", lambda engine, g, l, q=None: copy.deepcopy(self.view)),
                           ("hazop.shell.chat_edits._link_ask", lambda *a: self.ask_text),
                           ("hazop.shell.api_links.pair", lambda *a, **k: self.saved.append((a, k)) or {"ok": True, "notes": ["짝을 지정했습니다."], "recheck": []})):
            p = mock.patch(target, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_pair_shows_warnings_and_passes_ver_base_confirm(self):
        self.ask_text = "SNP-M-102 ← M-101 ↔ SNP-M-103 x 짝이 풀립니다."
        item = self.one("links.pair", "이 연결을 102에 이어 줘", graph_id="graph-SNP-M-101", local_id="c1",
                        peer_graph_id="graph-SNP-M-102", peer_local_id="c9", reason="배관 번호 확인")
        rows = {r["label"]: r for r in item["details"]}
        self.assertEqual(rows["짝"]["before"], "(짝 없음)")
        self.assertIn("SNP-M-102 ← M-101", rows["짝"]["after"])
        self.assertIn("배관 번호가 다름", rows["주의"]["after"])
        self.assertEqual(rows["엔진 확인"]["after"], self.ask_text)
        self.approve(item)
        (a, k), = self.saved
        self.assertEqual(a[1:6], ("graph-SNP-M-101", "c1", "graph-SNP-M-102", "c9", "lv-1"))
        self.assertEqual((k["base"], k["confirm"]), ("pb-1", self.ask_text))

    def test_same_drawing_and_missing_points_are_refused(self):
        self.assertIn("같은 도면", self.one("links.pair", graph_id="graph-SNP-M-101", local_id="c1",
                                         peer_graph_id="graph-SNP-M-101", peer_local_id="c2")["reason"])
        self.assertIn("맞은편 연결점", self.one("links.pair", graph_id="graph-SNP-M-101", local_id="c1")["reason"])
        self.assertIn("뺄 지정이 없음", self.one("links.clear", graph_id="graph-SNP-M-101", local_id="c1")["reason"])
