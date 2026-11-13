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
        for target, fn in (("candidates", view), ("_load", lambda name: ({"candidates": []}, {}))):
            p = mock.patch("hazop.shell.api_aireview." + target, fn)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("hazop.extract.ai_review.bulk_groups", lambda doc, by="task", **k: {"tag": list(self.bulk)})
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
            self.assertEqual(A.ACTIONS[name].klass, A.CONFIRM, "사람 판단을 저장하는 동작은 확인")
