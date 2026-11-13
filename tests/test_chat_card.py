"""채팅 답 카드 검사와 도면 변환(단위 C2, docs/specs/chat-panel.md §5.2·§6.4). 실행: python -m unittest tests.test_chat_card

Qt와 실제 CLI 없이 가짜 환경(CardEnv)으로 본다: 종류별 존재·근거 확인, 경로 다시 계산, 앱이 계산하는 경고,
출처 구분, 경로 칩 접기, 도면별 목록, 프로젝트 ID ↔ 도면 local_id 변환.
"""

import unittest

from hazop.chat import card, view

S1, S2 = "graph-A", "graph-B"


def comp(sheet, n):
    return "%s/e%d" % (sheet, n)


class FakeEnv(card.CardEnv):
    """RC-PZ01(e1) — 배관 L1(p1) — 티(e2) — 배관 L2(p2, 방향 미확인) — RC-PSV101(e3, 다른 도면 B). e9는 못 읽은 기호."""

    def __init__(self):
        self.items = {
            comp(S1, 1): dict(tag="RC-PZ01", kind="vessel", sheet=S1),
            comp(S1, 2): dict(tag="RC-T2", kind="tee", sheet=S1),
            comp(S2, 3): dict(tag="RC-PSV101", kind="safety_valve", sheet=S2),
            comp(S1, 9): dict(tag=None, kind="unclassified", sheet=S1),
            comp(S1, 11): dict(tag="RC-L1", kind="pipe_segment", sheet=S1),
            comp(S1, 12): dict(tag="RC-L2", kind="pipe_segment", sheet=S1),
        }
        self.bad = {comp(S1, 9): {"unknown_symbol"}, comp(S2, 3): {"valve_position_ignored"}}
        self.tags = {"rc-pz01": comp(S1, 1)}
        self.nodes, self.cells, self.chunks = {"S3"}, {"S3/D05/e2"}, {"doc#12"}
        self.version = "v1"
        self.steps = [dict(id=comp(S1, 1), kind="vessel", flow=None), dict(id=comp(S1, 11), kind="pipe_segment", flow="with"),
                      dict(id=comp(S1, 2), kind="tee", flow=None), dict(id=comp(S1, 12), kind="pipe_segment", flow="unknown"),
                      dict(id=comp(S2, 3), kind="safety_valve", flow=None)]

    def component(self, ref):
        if ref in self.items:
            return ref
        return self.tags.get(str(ref).lower())

    def exists(self, kind, ident):
        return ident in {"node": self.nodes, "cell": self.cells, "chunk": self.chunks}.get(kind, ())

    def describe(self, ident):
        d = self.items.get(ident)
        return dict(d, id=ident) if d else None

    def reasons(self, ident):
        return set(self.bad.get(ident, ()))

    def path_steps(self, ref):
        return None if ref.get("graph_version") != self.version else list(self.steps)


REF = {"start": comp(S1, 1), "end": comp(S2, 3), "mode": "physical", "basis": "ignoring_direction", "graph_version": "v1"}


def answer(**kw):
    base = {"text": "경로는 티 하나를 거칩니다.", "general": "", "refs": [], "paths": [], "highlight": [], "warnings": [], "actions": []}
    base.update(kw)
    return base


TOOL_IDS = {"component": {comp(S1, 1), comp(S1, 2), comp(S2, 3), comp(S1, 9)}}


class RefCheckTest(unittest.TestCase):
    def build(self, ans, tool_ids=None, path_refs=(REF,)):
        return card.build_card(ans, TOOL_IDS if tool_ids is None else tool_ids, FakeEnv(), path_refs=path_refs)

    def test_missing_ids_are_dropped_and_counted(self):
        c = self.build(answer(refs=[{"kind": "component", "id": comp(S1, 1)}, {"kind": "component", "id": "graph-A/없음"},
                                    {"kind": "node", "id": "S99"}]))
        self.assertEqual(c.dropped, 2)
        self.assertEqual([r["id"] for r in c.refs], [comp(S1, 1)])

    def test_tag_resolves_to_id(self):
        c = self.build(answer(refs=[{"kind": "component", "id": "RC-PZ01"}]))
        self.assertEqual([r["id"] for r in c.refs], [comp(S1, 1)])
        self.assertEqual(c.dropped, 0)

    def test_id_not_in_this_question_tool_results_is_ungrounded(self):
        c = self.build(answer(refs=[{"kind": "component", "id": comp(S1, 11)}, {"kind": "node", "id": "S3"}]),
                       tool_ids={"component": {comp(S1, 1)}})
        self.assertEqual(c.ungrounded, 2)
        self.assertEqual(c.refs, [])
        self.assertIn("근거 확인 안 됨 2개", c.footer_notes())

    def test_kind_must_match_the_tool_kind(self):
        # S3가 component 도구 결과에만 나왔다면 node 근거가 아니다
        c = self.build(answer(refs=[{"kind": "node", "id": "S3"}]), tool_ids={"component": {"S3"}})
        self.assertEqual(c.ungrounded, 1)

    def test_grounded_node_cell_chunk_pass(self):
        ids = {"component": set(), "node": {"S3"}, "cell": {"S3/D05/e2"}, "chunk": {"doc#12"}}
        c = self.build(answer(refs=[{"kind": "node", "id": "S3"}, {"kind": "cell", "id": "S3/D05/e2"},
                                    {"kind": "chunk", "id": "doc#12"}]), tool_ids=ids)
        self.assertEqual((c.dropped, c.ungrounded, len(c.refs)), (0, 0, 3))
        self.assertEqual(c.badges, ["도면", "결과", "문서"])

    def test_highlight_ungrounded_is_not_drawn(self):
        c = self.build(answer(highlight=[{"ids": [comp(S1, 1), comp(S1, 11)], "style": "focus"}]),
                       tool_ids={"component": {comp(S1, 1)}})
        self.assertEqual(c.highlight, [{"ids": [comp(S1, 1)], "style": "focus"}])
        self.assertEqual(c.ungrounded, 1)

    def test_unknown_style_falls_back_to_focus(self):
        c = self.build(answer(highlight=[{"ids": [comp(S1, 1)], "style": "<script>"}]))
        self.assertEqual(c.highlight[0]["style"], "focus")


class PathTest(unittest.TestCase):
    def build(self, **kw):
        paths = [{"label": "RC-PZ01 → RC-PSV101", "path_ref": REF}]
        return card.build_card(answer(paths=paths, **kw), TOOL_IDS, FakeEnv(), path_refs=(REF,))

    def test_chips_are_objects_and_pipes_label_the_next_chip(self):
        p = self.build().paths[0]
        self.assertEqual([c["tag"] for c in p.chips], ["RC-PZ01", "RC-T2", "RC-PSV101"])
        self.assertEqual([c["via"] for c in p.chips], [None, "RC-L1", "RC-L2"])

    def test_sheet_list_in_path_order(self):
        p = self.build().paths[0]
        self.assertEqual(p.sheets, [(S1, 2), (S2, 1)])

    def test_path_not_found_by_tools_is_not_drawn(self):
        c = card.build_card(answer(paths=[{"label": "x", "path_ref": REF}]), TOOL_IDS, FakeEnv(), path_refs=())
        self.assertEqual(c.paths, [])
        self.assertTrue(any("이번 질문" in n for n in c.path_notes))

    def test_changed_graph_version_is_not_drawn(self):
        stale = dict(REF, graph_version="v0")
        c = card.build_card(answer(paths=[{"label": "x", "path_ref": stale}]), TOOL_IDS, FakeEnv(), path_refs=(stale,))
        self.assertEqual(c.paths, [])
        self.assertTrue(any("도면이 바뀌어" in n for n in c.path_notes))

    def test_ids_instead_of_path_ref_are_refused(self):
        c = card.build_card(answer(paths=[{"label": "x", "ids": [comp(S1, 1)]}]), TOOL_IDS, FakeEnv(), path_refs=(REF,))
        self.assertEqual(c.paths, [])

    def test_app_warnings_come_from_the_raw_steps(self):
        c = self.build(warnings=[])  # 모델이 경고를 안 적어도 앱이 낸다
        reasons = {w["reason"] for w in c.warnings}
        self.assertEqual(reasons, {"direction_unknown", "valve_position_ignored"})
        text = " ".join(w["text"] for w in c.warnings)
        self.assertIn("흐름 방향 미확인 배관 1개", text)

    def test_model_warnings_stay_separate(self):
        c = self.build(warnings=["모델의 주의"])
        self.assertEqual(c.model_warnings, ["모델의 주의"])
        self.assertTrue(c.warnings)

    def test_unknown_symbol_chip_gets_warn_border(self):
        env = FakeEnv()
        env.steps.insert(2, dict(id=comp(S1, 9), kind="unclassified", flow=None))
        c = card.build_card(answer(paths=[{"label": "x", "path_ref": REF}]), TOOL_IDS, env, path_refs=(REF,))
        chips = {ch["id"]: ch for ch in c.paths[0].chips}
        self.assertTrue(chips[comp(S1, 9)]["warn"])
        self.assertFalse(chips[comp(S1, 1)]["warn"])
        self.assertIn("unknown_symbol", {w["reason"] for w in c.warnings})

    def test_against_flow_is_warned(self):
        env = FakeEnv()
        env.steps[1]["flow"] = "against"
        c = card.build_card(answer(paths=[{"label": "x", "path_ref": REF}]), TOOL_IDS, env, path_refs=(REF,))
        self.assertIn("flow_against", {w["reason"] for w in c.warnings})

    def test_warning_order_is_fixed(self):
        c = self.build()
        order = [w["reason"] for w in c.warnings]
        self.assertEqual(order, sorted(order, key=card.REASON_ORDER.index))


class SourceSplitTest(unittest.TestCase):
    def test_general_only_shows_no_evidence_header(self):
        c = card.build_card(answer(text="", general="안전밸브는 보통 …"), {}, FakeEnv())
        self.assertTrue(c.no_evidence)
        self.assertEqual(c.badges, [])

    def test_text_with_general_keeps_both(self):
        c = card.build_card(answer(general="일반 지식"), TOOL_IDS, FakeEnv())
        self.assertFalse(c.no_evidence)
        self.assertEqual(c.general, "일반 지식")

    def test_text_is_plain(self):
        c = card.build_card(answer(text="<b>굵게</b> **별표**"), TOOL_IDS, FakeEnv())
        self.assertEqual(c.text, "<b>굵게</b> **별표**")  # 해석하지 않고 그대로 두며, 그릴 때 PlainText로 그린다

    def test_garbage_answer_does_not_crash(self):
        c = card.build_card({"text": None, "refs": "x", "paths": [None, 3], "highlight": [{"ids": "a"}]}, {}, FakeEnv())
        self.assertEqual((c.text, c.refs, c.paths), ("", [], []))

    def test_actions_pass_through_for_later_unit(self):
        c = card.build_card(answer(actions=[{"action": "x"}]), TOOL_IDS, FakeEnv())
        self.assertEqual(c.actions, [{"action": "x"}])


class FoldTest(unittest.TestCase):
    def chips(self, n):
        return [{"id": str(i)} for i in range(n)]

    def test_short_list_not_folded(self):
        self.assertEqual(len(card.fold_chips(self.chips(12))), 12)

    def test_long_list_folds_middle(self):
        out = card.fold_chips(self.chips(20))
        self.assertEqual([c.get("id") for c in out[:5]], ["0", "1", "2", "3", "4"])
        self.assertEqual(out[5], {"fold": 10})
        self.assertEqual([c.get("id") for c in out[6:]], ["15", "16", "17", "18", "19"])

    def test_expanded_shows_all(self):
        self.assertEqual(len(card.fold_chips(self.chips(20), expanded=True)), 20)


class PathRefCollectTest(unittest.TestCase):
    def test_collects_path_ref_from_tool_result(self):
        seen = view.QuestionLog()
        seen.tool_event("q1", "trace_path", {"start": "a"}, {"ok": True, "data": {"path_ref": REF}})
        seen.tool_event("q1", "find", {"query": "x"}, {"ok": True, "data": {}})
        self.assertEqual(seen.path_refs("q1"), [REF])
        self.assertEqual(seen.tool_count("q1"), 2)
        self.assertEqual(seen.tool_names("q1"), ["trace_path", "find"])

    def test_other_question_is_separate(self):
        seen = view.QuestionLog()
        seen.tool_event("q1", "trace_path", {}, {"data": {"path_ref": REF}})
        self.assertEqual(seen.path_refs("q2"), [])

    def test_malformed_result_ignored(self):
        seen = view.QuestionLog()
        seen.tool_event("q1", "trace_path", None, "not a dict")
        self.assertEqual(seen.path_refs("q1"), [])
        self.assertEqual(seen.tool_count("q1"), 1)


def small_pg():
    nodes = [dict(entity_id=comp(S1, 1), sheet=S1, local_id="L1"), dict(entity_id=comp(S1, 11), sheet=S1, local_id="L11"),
             dict(entity_id=comp(S1, 2), sheet=S1, local_id="L2"), dict(entity_id=comp(S2, 3), sheet=S2, local_id="M3"),
             dict(entity_id="link-1", sheet=None)]
    return {"graph_version": "v1", "nodes": nodes, "edges": []}


class ViewConvertTest(unittest.TestCase):
    def test_split_by_sheet_keeps_order(self):
        pg = small_pg()
        out = view.split_by_sheet(pg, [comp(S2, 3), comp(S1, 1), comp(S1, 2), "nope", "link-1"])
        self.assertEqual(out, {S2: ["M3"], S1: ["L1", "L2"]})

    def test_path_steps_per_sheet_with_flow(self):
        pg = small_pg()
        steps = [dict(id=comp(S1, 1), flow=None), dict(id=comp(S1, 11), flow="with"), dict(id="link-1", flow="unknown"),
                 dict(id=comp(S2, 3), flow=None)]
        out = view.path_steps(pg, steps)
        self.assertEqual(out[S1], [{"id": "L1", "flow": None}, {"id": "L11", "flow": "with"}])
        self.assertEqual(out[S2], [{"id": "M3", "flow": None}])
        self.assertEqual(list(out), [S1, S2])

    def test_lift_back_to_project_ids(self):
        pg = small_pg()
        self.assertEqual(view.lift(pg, S1, ["L2", "L1", "zzz"]), [comp(S1, 2), comp(S1, 1)])

    def test_marks_for_card_builds_mark_and_path_items(self):
        pg = small_pg()
        env = FakeEnv()
        c = card.build_card(answer(paths=[{"label": "x", "path_ref": REF}],
                                   highlight=[{"ids": [comp(S1, 1)], "style": "focus"}]), TOOL_IDS, env, path_refs=(REF,))
        marks = view.marks_for_card(pg, c, path_index=0)
        self.assertEqual([i["op"] for i in marks[S1]], ["path", "mark"])
        self.assertEqual(marks[S1][1]["groups"], [{"ids": ["L1"], "style": "focus", "label": None}])


class AvailabilityTest(unittest.TestCase):
    def test_ok_and_unchecked_open_the_input(self):
        for st in ("ok", "unchecked", "checking", "limit_warning", None):
            self.assertFalse(view.availability(st)["blocked"], st)

    def test_no_cli_message_and_install_button(self):
        for st in ("not_installed", "cli_unsupported"):
            a = view.availability(st)
            self.assertTrue(a["blocked"])
            self.assertIn("이 PC에 Claude Code가 없습니다", a["text"])
            self.assertIn("도면 보기·추출·분석 기록은 그대로 쓸 수 있습니다", a["text"])
            self.assertEqual(a["button"], "install")

    def test_logged_out_has_login_button(self):
        a = view.availability("login_required")
        self.assertEqual((a["blocked"], a["button"]), (True, "login"))

    def test_limit_shows_reset_time(self):
        a = view.availability("limit_reached", reset_text="오후 3시")
        self.assertIn("한도에 닿았습니다", a["text"])
        self.assertIn("오후 3시", a["text"])
        self.assertTrue(a["blocked"])

    def test_disabled_asks_before_enabling(self):
        self.assertEqual(view.availability("disabled")["button"], "enable")

    def test_other_states_use_the_chip_message(self):
        a = view.availability("network", message="연결 못 함")
        self.assertEqual((a["blocked"], a["text"]), (True, "연결 못 함"))


class ExamplesTest(unittest.TestCase):
    def test_tags_come_from_the_project(self):
        pg = {"nodes": [dict(entity_id="a", tag="RC-PZ01", kind="vessel"), dict(entity_id="p", tag="RC-L1", kind="pipe_segment"),
                        dict(entity_id="b", tag="RC-PSV101", kind="safety_valve")]}
        text = " ".join(q for _, qs in view.examples(pg) for q in qs)
        self.assertIn("RC-PZ01", text)
        self.assertIn("RC-PSV101", text)
        self.assertNotIn("RC-L1", text)

    def test_without_project_still_gives_kinds(self):
        groups = view.examples(None)
        self.assertEqual([g for g, _ in groups], ["찾기", "경로", "개수", "확인할 곳"])
        self.assertTrue(all(qs for _, qs in groups))


class ContextEnvTest(unittest.TestCase):
    def env(self):
        import types
        nodes = {comp(S1, 1): dict(entity_id=comp(S1, 1), tag="RC-PZ01", kind="vessel", sheet=S1),
                 comp(S1, 11): dict(entity_id=comp(S1, 11), tag="RC-L1", line_no="RC-L001", node_type="pipe_segment",
                                    kind="pipe_segment", sheet=S1),
                 comp(S2, 3): dict(entity_id=comp(S2, 3), tag="RC-PSV101", kind="safety_valve", sheet=S2)}
        idx = types.SimpleNamespace(nodes=nodes, by_tag={"rc-pz01": [comp(S1, 1)], "dup": ["a", "b"]},
                                    uncertain={comp(S1, 11): {"direction_unknown"}})
        ctx = types.SimpleNamespace(index=idx, pg={"graph_version": "v1"}, node_sets=[{"nodes": [{"node_id": "S3"}]}])
        return card.ContextEnv(ctx)

    def test_component_by_id_and_unique_tag_only(self):
        e = self.env()
        self.assertEqual(e.component(comp(S1, 1)), comp(S1, 1))
        self.assertEqual(e.component("rc-pz01"), comp(S1, 1))
        self.assertIsNone(e.component("dup"))
        self.assertIsNone(e.component("nope"))

    def test_node_exists_and_describe_pipe_uses_line_no(self):
        e = self.env()
        self.assertTrue(e.exists("node", "S3"))
        self.assertFalse(e.exists("node", "S9"))
        self.assertFalse(e.exists("chunk", "x"))
        self.assertEqual(e.describe(comp(S1, 11))["tag"], "RC-L001")

    def test_reasons_include_valve_note(self):
        e = self.env()
        self.assertEqual(e.reasons(comp(S1, 11)), {"direction_unknown"})
        self.assertEqual(e.reasons(comp(S2, 3)), {"valve_position_ignored"})

    def test_stale_graph_version_gives_no_steps(self):
        self.assertIsNone(self.env().path_steps(dict(REF, graph_version="v0")))


if __name__ == "__main__":
    unittest.main()
