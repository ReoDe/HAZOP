"""채팅 동작 A11 2차: 지식그래프 판단·찾기, AI 후보 수락·거절·되돌리기·묶음 수락, 원본 형식 고르기, Excel 범위, 새 패널 이동.
실행: python -m unittest tests.test_shell_chat_screens

가짜 응답만 쓴다(구독 호출 없음). 화면 엔진 함수(api_kg·api_aireview·sources)는 경계에서 가짜로 바꿔, 연결부가 1차 검토에서 정한 규칙을
지키는지 본다: 확인 없이는 저장하지 않음, 확인 상자에 저장될 값 전부, 확인 상자에서 본 대조 값(digest·상태·판, 후보 ID·판)을 그대로 넘김,
그 사이 바뀌면 stale, 엔진 거절도 기록.
"""

import copy
from unittest import mock

from hazop.shell import api_kg, chat_screens
from tests.test_shell_chat_run import RunBase

REVIEWER = "홍길동"


class KgBase(RunBase):
    def setUp(self):
        super().setUp()
        self.item = {"id": "exp-1", "digest": "d" * 64, "state": "expected", "label": "가압기 압력 경보", "rule_id": "R-ALARM",
                     "target_tag": "RC-PZ01", "target": "graph-SNP-M-102/entity-node-001"}
        self.ctx = {"ver": "SNP|aaaa", "judge_problem": None, "expectations": {"items": [self.item]}}
        p = mock.patch.object(api_kg, "_context", lambda engine: (copy.deepcopy(self.ctx), None))
        p.start()
        self.addCleanup(p.stop)
        self.judged = []
        p = mock.patch.object(api_kg, "judge", lambda engine, *a, **k: self.judged.append((a, k)) or {"ver": "SNP|bbbb", "state": "confirmed_absent",
                                                                                                    "state_label": "부재 확정"})
        p.start()
        self.addCleanup(p.stop)


class KgJudgeTest(KgBase):
    def test_judgement_needs_confirmation_shows_ai_text_and_passes_what_was_seen(self):
        item = self.one("kg.judge", "부재 확정해 줘", id="exp-1", judgement="absent", reason="AI가 쓴 사유: 경보 없음", evidence="SNP-M-102 1쪽")
        self.assertEqual(item["status"], "confirm")
        self.assertEqual(self.judged, [], "확인 전에는 저장하지 않는다")
        rows = {r["label"]: r for r in item["details"]}
        self.assertEqual((rows["판단"]["before"], rows["판단"]["after"]), ("기대됨", "부재 확정(부재 확정)"))
        self.assertEqual(rows["사유(AI가 씀)"]["after"], "AI가 쓴 사유: 경보 없음")
        self.assertEqual(rows["근거(AI가 씀)"]["after"], "SNP-M-102 1쪽")
        self.assertIn("RC-PZ01", rows["잠재 후보"]["after"])
        self.assertTrue(self.approve(item)["ok"])
        (args, kw), = self.judged
        self.assertEqual(args, ("exp-1", "absent", "d" * 64, "expected", "AI가 쓴 사유: 경보 없음", "SNP-M-102 1쪽"))
        self.assertEqual(kw, {"ver": "SNP|aaaa", "by": REVIEWER})
        self.assertEqual(self.last_record("kg.judge")["confirmed_by"], REVIEWER)

    def test_missing_required_input_or_bad_transition_is_refused_before_the_box(self):
        self.assertIn("근거", self.one("kg.judge", id="exp-1", judgement="absent", reason="x")["reason"])
        self.assertIn("허용되지 않는", self.one("kg.judge", id="exp-1", judgement="confirm")["reason"])
        self.assertIn("없는 잠재 후보", self.one("kg.judge", id="exp-9", judgement="undo")["reason"])
        self.assertEqual(self.judged, [])

    def test_item_changed_after_the_box_is_stale(self):
        item = self.one("kg.judge", id="exp-1", judgement="not_applicable", reason="해당 없음")
        self.item["digest"] = "e" * 64          # 다시 추출해 후보 내용이 바뀜
        self.ctx["expectations"]["items"] = [self.item]
        self.approve(item)
        self.assertEqual(self.judged, [])
        self.assertEqual(self.events.of("chat.action.result")[-1]["item"]["status"], "stale")

    def test_engine_refusal_is_recorded(self):
        from hazop.shell import api
        with mock.patch.object(api_kg, "judge", mock.Mock(side_effect=api.CommandError("stale", "다른 곳에서 바뀜"))):
            item = self.one("kg.judge", id="exp-1", judgement="not_applicable", reason="해당 없음")
            self.approve(item)
        self.assertEqual(self.last_record("kg.judge")["result"], "rejected")
        self.assertIn("다른 곳에서 바뀜", self.events.of("chat.action.result")[-1]["item"]["reason"])

    def test_find_opens_the_panel_on_the_first_hit(self):
        opened = []
        with mock.patch.object(api_kg, "find_nodes", lambda engine, text, limit=5: [{"id": "kn-7", "label": "RC-PZ01 경보"}]), \
                mock.patch.object(api_kg, "open_panel", lambda engine, node_id=None: opened.append(node_id) or {"opened": True}):
            self.answers.append(self.answer([self.act("kg.find", text="가압기 경보"), self.act("goto", target="kg", id="kn-9")]))
            self.assertTrue(self.chat.ask("지식그래프에서 가압기 경보 찾아 줘"))
        items = self.events.of("chat.display")[-1]["items"]
        self.assertEqual([(i["op"], i["panel"]) for i in items], [("panel", "kg"), ("panel", "kg")])
        self.assertEqual(opened, ["kn-7", "kn-7"])
        self.assertEqual(self.records, [], "찾기·이동은 기록하지 않는다")


class AiReviewBase(RunBase):
    def setUp(self):
        super().setUp()
        self.rows = {"c1": {"cand_id": "c1", "task": "tag", "field": "tag", "field_label": "태그", "current": "", "values": ["RC-V010"],
                            "confidence": 0.93, "reason": "AI 근거: 옆 글자", "status": "proposed", "status_label": "제안", "local_id": "local-node-008"},
                     "c2": {"cand_id": "c2", "task": "kind", "field": "kind", "field_label": "종류", "current": "unknown", "values": ["gate_valve"],
                            "confidence": 0.71, "reason": "모양", "status": "accepted", "status_label": "수락", "local_id": "local-node-009"}}
        self.ver = "v1"
        self.bulk = ["c1"]
        view = lambda engine, gid: {"ok": True, "available": True, "ver": self.ver,  # noqa: E731
                                    "groups": [{"items": [copy.deepcopy(r) for r in self.rows.values()]}]}
        for target, fn in (("candidates", view), ("bulk_ids", lambda engine, gid, task: list(self.bulk) if task == "tag" else [])):
            p = mock.patch("hazop.shell.api_aireview." + target, fn)
            p.start()
            self.addCleanup(p.stop)
        self.calls = []

        def decide(action):
            return lambda engine, gid, ids, ver=None, by=None: self.calls.append((action, gid, list(ids), ver, by)) or \
                {"ok": True, "changed": list(ids), "failed": [], "notes": []}
        for action in ("accept", "reject", "revert"):
            p = mock.patch("hazop.shell.api_aireview." + action, decide(action))
            p.start()
            self.addCleanup(p.stop)


class AiReviewTest(AiReviewBase):
    def test_accept_shows_value_before_after_and_ai_reason_then_passes_ids_and_ver(self):
        item = self.one("aireview.accept", "c1 수락해 줘", graph_id="graph-SNP-M-101", cand_ids=["c1"])
        self.assertEqual(item["status"], "confirm")
        self.assertEqual(self.calls, [])
        row = item["details"][0]
        self.assertEqual(row["before"], "(비어 있음)")
        self.assertIn("RC-V010", row["after"])
        self.assertIn("AI 근거: 옆 글자", row["after"])
        self.assertIn("0.93", row["after"])
        self.assertTrue(self.approve(item)["ok"])
        self.assertEqual(self.calls, [("accept", "graph-SNP-M-101", ["c1"], "v1", REVIEWER)])
        self.assertIn("수락", self.events.of("chat.action.result")[-1]["item"]["text"])
        self.assertEqual(self.last_record("aireview.accept")["confirmed_by"], REVIEWER)

    def test_wrong_status_and_unknown_ids_are_refused_before_the_box(self):
        self.assertIn("상태", self.one("aireview.accept", graph_id="graph-SNP-M-101", cand_ids=["c2"])["reason"])
        self.assertIn("없는 후보", self.one("aireview.reject", graph_id="graph-SNP-M-101", cand_ids=["c9"])["reason"])
        self.assertIn("상태", self.one("aireview.revert", graph_id="graph-SNP-M-101", cand_ids=["c1"])["reason"])
        self.assertEqual(self.calls, [])

    def test_reject_and_revert(self):
        self.approve(self.one("aireview.reject", graph_id="graph-SNP-M-101", cand_ids=["c1"]))
        self.approve(self.one("aireview.revert", graph_id="graph-SNP-M-101", cand_ids=["c2"]))
        self.assertEqual([c[0] for c in self.calls], ["reject", "revert"])

    def test_bulk_accepts_only_the_ids_shown_in_the_box(self):
        item = self.one("aireview.accept_bulk", graph_id="graph-SNP-M-101", task="tag")
        self.assertEqual([r["label"].split(" ")[1] for r in item["details"][:-1]], ["c1"])
        self.bulk = ["c1", "c3"]                 # 그 사이 묶음이 늘면 보인 것과 달라 실행하지 않는다
        self.approve(item)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events.of("chat.action.result")[-1]["item"]["status"], "stale")

    def test_candidate_file_changed_after_the_box_is_stale(self):
        item = self.one("aireview.accept", graph_id="graph-SNP-M-101", cand_ids=["c1"])
        self.ver = "v2"
        self.approve(item)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events.of("chat.action.result")[-1]["item"]["status"], "stale")

    def test_engine_failure_is_recorded(self):
        with mock.patch("hazop.shell.api_aireview.accept", lambda *a, **k: {"ok": False, "code": "stale", "message": "다른 곳에서 바뀜"}):
            self.approve(self.one("aireview.accept", graph_id="graph-SNP-M-101", cand_ids=["c1"]))
        self.assertEqual(self.last_record("aireview.accept")["result"], "rejected")

    def test_graph_stale_and_recheck_are_told(self):
        """730cbd7: 저장은 됐지만 그래프를 다시 만들지 못함(graph_stale)과 ④·⑤ 재확인 안내(recheck)를 답에 싣는다."""
        out = {"ok": True, "changed": ["c1"], "failed": [], "notes": [], "graph_stale": True,
               "recheck": ["④ 검토구간 확정본이 고치기 전 도면 기준입니다. 재확인이 필요합니다."]}
        with mock.patch("hazop.shell.api_aireview.accept", lambda *a, **k: out):
            self.approve(self.one("aireview.accept", graph_id="graph-SNP-M-101", cand_ids=["c1"]))
        done = self.events.of("chat.action.result")[-1]["item"]
        self.assertEqual(done["status"], "applied")
        self.assertIn("그래프를 다시 만들지 못해", done["text"])
        self.assertIn("재확인이 필요합니다", done["text"])

    def test_goto_aireview_with_a_drawing(self):
        self.answers.append(self.answer([self.act("goto", target="aireview", id="SNP-M-101"), self.act("goto", target="actionlog")]))
        self.assertTrue(self.chat.ask("AI 후보 보여 줘"))
        items = self.events.of("chat.display")[-1]["items"]
        self.assertEqual((items[0]["panel"], items[0]["sheet"]), ("aireview", "graph-SNP-M-101"))
        self.assertEqual(items[1]["panel"], "actionlog")


class SourcesTest(RunBase):
    def setUp(self):
        super().setUp()
        self.conf = [{"drawing_number": "SNP-M-101", "formats": ["drawio", "pdf_vector"], "in_use_format": "drawio", "chosen": None}]
        p = mock.patch("hazop.graph.sources.conflicts", lambda pid, *a, **k: copy.deepcopy(self.conf))
        p.start()
        self.addCleanup(p.stop)
        self.chosen = []
        p = mock.patch("hazop.shell.api_drawings._choose_source",
                       lambda engine, a: self.chosen.append(a) or {"chosen": {"drawing_number": a["drawing_number"], "format": a["format"]}})
        p.start()
        self.addCleanup(p.stop)

    def test_choose_needs_confirmation_and_shows_the_switch(self):
        item = self.one("sources.choose", "101은 PDF 원본을 써 줘", drawing_number="SNP-M-101", format="pdf_vector")
        self.assertEqual(item["status"], "confirm")
        rows = {r["label"]: r for r in item["details"]}
        self.assertEqual((rows["쓸 원본 형식"]["before"], rows["쓸 원본 형식"]["after"]), ("drawio", "pdf_vector"))
        self.assertEqual(self.chosen, [])
        self.assertTrue(self.approve(item)["ok"])
        self.assertEqual(self.chosen, [{"drawing_number": "SNP-M-101", "format": "pdf_vector"}])

    def test_no_conflict_or_missing_format_is_refused(self):
        self.assertIn("없음", self.one("sources.choose", drawing_number="SNP-M-101", format="dexpi")["reason"])
        self.assertIn("겹치지 않음", self.one("sources.choose", drawing_number="SNP-M-999", format="drawio")["reason"])

    def test_someone_else_chose_meanwhile_is_stale(self):
        item = self.one("sources.choose", drawing_number="SNP-M-101", format="pdf_vector")
        self.conf[0]["chosen"] = {"format": "drawio"}
        self.approve(item)
        self.assertEqual(self.chosen, [])
        self.assertEqual(self.events.of("chat.action.result")[-1]["item"]["status"], "stale")


class ExcelScopeTest(RunBase):
    def test_scope_is_checked_and_passed_through(self):
        seen = []
        with mock.patch("hazop.shell.api_results._export_excel", lambda engine, a: seen.append(a) or {"path": "x.xlsx", "rows": 3}):
            ok = self.one("export.excel", "S1만 엑셀로", scope="nodes", node_ids=["S1"])
            approved = self.one("export.excel", scope="approved")
            bad = [self.one("export.excel", scope="nodes"), self.one("export.excel", scope="all", node_ids=["S1"]),
                   self.one("export.excel", scope="nodes", node_ids=["S9"]), self.one("export.excel", scope="everything")]
        self.assertEqual(seen, [{"scope": "nodes", "node_ids": ["S1"]}, {"scope": "approved", "node_ids": None}])
        self.assertIn("고른 구간 S1", ok["text"])
        self.assertIn("승인 항목만", approved["text"])
        self.assertEqual([b["status"] for b in bad], ["rejected"] * 4)


class TableTest(RunBase):
    def test_new_actions_are_in_the_table_and_prompt(self):
        from hazop.chat import actions as A
        from hazop.chat import card
        for name in chat_screens.RUN_ACTIONS + ("kg.find",):
            self.assertIn(name, A.ACTIONS)
            self.assertIn(name + "(", card.SYSTEM_PROMPT)
        for name in chat_screens.RUN_ACTIONS:
            want = A.AUTO if name in ("ie.draft_rules", "ie.export") else A.CONFIRM   # 초안은 더하기만, 내보내기는 새 파일
            self.assertEqual(A.ACTIONS[name].klass, want, "사람 판단을 저장하는 동작은 확인: " + name)


class IeBase(RunBase):
    def setUp(self):
        super().setUp()
        self.base = {"groups": {"IEG-01": {"name": "급수 상실", "status": "draft", "definition": "옛 정의"},
                                "IEG-02": {"name": "냉각재 상실", "status": "confirmed"}},
                     "candidates": {"IEC-001": {"group_id": "IEG-01"}, "IEC-002": {"group_id": None}},
                     "coverage": {}}
        self.fps = {"group:IEG-01": "sha256:g1", "group:IEG-02": "sha256:g2", "member:IEC-001": "sha256:m1",
                    "member:IEC-002": "sha256:m2", "coverage:LOCCW": "sha256:c1"}
        ctx = (None, {"nodes": []}, {"cells": []}, {}, "sha256:IE")
        self.new_doc = None           # 실행하면 저장될 ⑥ 문서(미리 계산). None이면 확정이 풀리는 그룹 없음
        for target, fn in (("hazop.shell.chat_screens._ie_ctx", lambda engine: (ctx, copy.deepcopy(self.base), dict(self.fps), None)),
                           ("hazop.shell.chat_screens._ie_new", lambda engine, item, c, base: copy.deepcopy(self.new_doc)),
                           ("hazop.shell.api_ie._rver", lambda c: "rv1")):
            p = mock.patch(target, fn)
            p.start()
            self.addCleanup(p.stop)
        self.writes = []

        def handler(name):
            return lambda engine, a: self.writes.append((name, a)) or {"ver": "sha256:IE2", "changed": True, "value": None}
        for name in ("_move", "_split", "_edit_group", "_accept_members", "_confirm", "_reopen", "_set_coverage"):
            p = mock.patch("hazop.shell.api_ie." + name, handler(name))
            p.start()
            self.addCleanup(p.stop)


class IeTest(IeBase):
    def test_move_needs_confirmation_and_passes_ver_rver_and_seen(self):
        item = self.one("ie.move", "IEC-002를 급수 상실로 옮겨 줘", iecs=["IEC-002"], to="IEG-01")
        self.assertEqual(item["status"], "confirm")
        self.assertEqual(self.writes, [])
        row = item["details"][0]
        self.assertEqual((row["before"], row["after"]), ("(묶이지 않음)", "IEG-01 급수 상실"))
        self.assertTrue(self.approve(item)["ok"])
        (name, a), = self.writes
        self.assertEqual(name, "_move")
        self.assertEqual((a["ver"], a["rver"], a["to"]), ("sha256:IE", "rv1", "IEG-01"))
        self.assertEqual(a["seen"], {"member:IEC-002": "sha256:m2", "group:IEG-01": "sha256:g1"})
        self.assertNotIn("confirmed", a, "채팅은 엔진의 되묻기를 건너뛰지 않는다")
        self.assertEqual(self.last_record("ie.move")["confirmed_by"], REVIEWER)

    def test_edit_group_shows_old_and_new_values(self):
        item = self.one("ie.edit_group", group_id="IEG-01", fields={"definition": "AI가 쓴 새 정의"})
        rows = {r["label"]: r for r in item["details"]}
        self.assertEqual((rows["definition(AI가 씀)"]["before"], rows["definition(AI가 씀)"]["after"]), ("옛 정의", "AI가 쓴 새 정의"))
        self.assertIn("고칠 수 없는 필드", self.one("ie.edit_group", group_id="IEG-01", fields={"status": "confirmed"})["reason"])

    def test_item_changed_after_the_box_is_stale(self):
        item = self.one("ie.split", group_id="IEG-01", moved=["IEC-001"])
        self.fps["group:IEG-01"] = "sha256:g1-changed"
        self.approve(item)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.events.of("chat.action.result")[-1]["item"]["status"], "stale")

    def test_engine_question_is_passed_on_not_answered(self):
        from hazop.shell import api
        with mock.patch("hazop.shell.api_ie._reopen", mock.Mock(side_effect=api.CommandError("confirm", "확정한 그룹 IEG-02가 초안으로 돌아갑니다."))):
            self.approve(self.one("ie.reopen_group", group_id="IEG-02"))
        done = self.events.of("chat.action.result")[-1]["item"]
        self.assertEqual(done["status"], "rejected")
        self.assertIn("⑥ 초기사건 패널에서", done["reason"])
        self.assertEqual(self.last_record("ie.reopen_group")["result"], "rejected")

    def test_groups_losing_confirmation_are_shown_and_passed_as_seen(self):
        """확정이 풀리는 그룹은 확인 상자에 미리 보이고, 실행 때 그 목록을 confirm_groups로 넘긴다(엔진이 지금 목록과 대조)."""
        self.base["candidates"]["IEC-003"] = {"group_id": "IEG-02"}
        self.fps["member:IEC-003"] = "sha256:m3"
        self.new_doc = copy.deepcopy(self.base)
        self.new_doc["groups"]["IEG-02"]["status"] = "draft"
        item = self.one("ie.move", iecs=["IEC-003"], to="IEG-01")
        rows = {r["label"]: r["after"] for r in item["details"]}
        self.assertIn("IEG-02 냉각재 상실", rows["확정이 풀리는 그룹"])
        self.approve(item)
        (_name, a), = self.writes
        self.assertEqual((a["confirmed"], a["confirm_groups"]), (True, ["IEG-02"]))

    def test_new_engine_question_after_the_box_is_refused_not_saved(self):
        """상자에 없던 '확정 풀림'이 실행 때 생기면 엔진은 저장하지 않고 되묻는다: 채팅은 '바뀐 것 없음'이 아니라 거절로 알린다."""
        with mock.patch("hazop.shell.api_ie._move", lambda engine, a: {"changed": False, "ask": {"message": "?", "groups": ["IEG-02"]}}):
            self.approve(self.one("ie.move", iecs=["IEC-002"], to="IEG-01"))
        done = self.events.of("chat.action.result")[-1]["item"]
        self.assertEqual(done["status"], "rejected")
        self.assertIn("IEG-02", done["reason"])

    def test_coverage_reason_required_and_unknown_ids_refused(self):
        self.assertIn("사유", self.one("ie.set_coverage", code="LOCCW", disposition="out_of_scope")["reason"])
        item = self.one("ie.set_coverage", code="LOCCW", disposition="out_of_scope", reason="AI 사유: 이 발전소 설계에 없음")
        self.assertEqual({r["label"]: r["after"] for r in item["details"]}["사유(AI가 씀)"], "AI 사유: 이 발전소 설계에 없음")
        self.assertIn("없는 그룹", self.one("ie.confirm_group", group_id="IEG-99")["reason"])
        self.assertIn("없는 후보", self.one("ie.accept_members", iecs=["IEC-999"])["reason"])


class DocsTest(RunBase):
    def setUp(self):
        super().setUp()
        self.docs = [{"material_id": "D-001", "title": "가압기 설계 기준", "counts": {"setpoint": 4}}]
        self.jobs = []
        for target, fn in (("list_documents", lambda engine: copy.deepcopy(self.docs)),
                           ("run_extraction", lambda engine, mid: self.jobs.append(mid) or {"job": "j3"})):
            p = mock.patch("hazop.shell.api_docs." + target, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_extract_needs_confirmation_runs_once_and_records_the_end(self):
        item = self.one("docs.extract", "가압기 설계 기준 다시 추출해 줘", material_id="D-001")
        self.assertEqual(item["status"], "confirm")
        self.assertIn("setpoint 4", {r["label"]: r["after"] for r in item["details"]}["지금 뽑힌 항목"])
        self.actions.runner.watch = False
        self.assertTrue(self.approve(item)["ok"])
        self.assertEqual(self.jobs, ["D-001"])
        again = self.one("docs.extract", material_id="D-001")
        self.assertIn("이미 돌고", again["reason"], "추출이 도는 동안 같은 문서를 다시 시작하지 않는다")
        self.engine._jobs["j3"] = {"state": "failed"}
        for run in self.actions.runner.pending:
            run()
        rows = [r["result"] for r in self.records if r["proposal"]["action"] == "docs.extract"]
        self.assertEqual(rows[-1], "failed")
        self.assertEqual(self.actions._docs_running, set(), "끝나면 다시 할 수 있다")

    def test_unknown_document_and_add_by_chat_are_refused(self):
        self.assertIn("없는 설계 문서", self.one("docs.extract", material_id="D-404")["reason"])
        self.assertEqual(self.one("docs.add")["status"], "rejected")
