"""같은 번호 자리의 다른 파일 고르기와 열 때 정착(시트 정체 U4 저장 쪽). 실행: python -m unittest tests.test_shell_sheet_choose

가상 도면 SNP의 원본을 임시 작업·저장 루트에 실제로 등록·추출한다. 셸 명령(sources.choose material_id)과 엔진의 열 때 정착(settle_on_open)이
지금 있는 엔진 함수(hazop.graph.sources.choose, hazop.app.data.settle_sheets)를 그대로 부르고, 갈아타면 검토구간이 이어서 맞춰지며
잃은 것이 있으면 study.lost가 가는지, 정착은 열 때 한 번만 쓰고 두 번째는 아무것도 쓰지 않는지, 도는 작업이 있으면 하지 않는지 본다.
AI·구독 호출 없음.
"""

import os
import re
import unittest
from unittest import mock

from tests.test_sheet_gid_paths import NUMBER, SheetCase
from tests.test_titleblock import BY, P

from hazop.app import data, project_ctx
from hazop.graph import sources
from hazop.study import nodes

TEMP = re.compile(r"graph-material-|SCN__|material-[0-9a-f]{12}-p\d")


class ShellSheetBase(SheetCase):
    def engine(self):
        from hazop.shell import api
        self.events = []
        eng = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"),
                         emit=lambda m: self.events.append(m), run_jobs=lambda job_id, fn: fn())
        eng.settings.update(reviewer_name=BY, project_id=P)
        return eng

    def lost(self):
        pg = project_ctx.project_graph(P)
        return sum(len(n.get("lost") or []) for n in nodes.load(pg)["nodes"])


class FileChoiceTest(ShellSheetBase):
    def setUp(self):
        super().setUp()
        self.a = self.register(self.copy_in("SNP-M-101", "pdf", "in-a"), NUMBER)
        self.make_nodes(self.a)
        self.b = self.register(self.copy_in("SNP-M-102", "pdf", "in-b"), dict(NUMBER))
        self.eng = self.engine()

    def test_the_read_carries_files_names_and_the_preview_count(self):
        from hazop.shell import api_drawings
        rows = api_drawings.source_conflicts(self.eng)["conflicts"]
        self.assertEqual(len(rows), 1, rows)
        c = rows[0]
        self.assertEqual((c["kind"], c["reason"], c["display"], c["in_use_material"]), ("file", "same_number_other_file", "SNP-M-101", self.a))
        self.assertEqual(sorted(x["material_id"] for x in c["candidates"]), sorted([self.a, self.b]))
        self.assertTrue(all(x["file"] and x["file"].endswith(".pdf") for x in c["candidates"]), c["candidates"])
        self.assertEqual([x["in_use"] for x in c["candidates"] if x["material_id"] == self.a], [True])
        self.assertEqual(c["nodes_on_sheet"], 1, "갈아타면 다시 확인할 구간 수")
        for t in [c["text"] or "", c["display"], c["in_use_file"] or ""] + [x["file"] for x in c["candidates"]]:
            self.assertNotRegex(t, TEMP)
        self.assertNotIn("name", c["candidates"][0], "폴더 이름은 싣지 않는다")

    def test_choosing_another_file_switches_and_reports_what_was_lost_then_back(self):
        refused = self.eng.dispatch("sources.choose", {"drawing_number": "graph-SNP-M-101", "format": "pdf_vector"})
        self.assertEqual(refused["error"]["code"], "failed", "같은 형식이라 형식으로는 고를 수 없음")
        self.assertEqual(self.eng.dispatch("sources.choose", {"drawing_number": "graph-SNP-M-101"})["error"]["code"], "bad_args")
        out = self.eng.dispatch("sources.choose", {"drawing_number": "graph-SNP-M-101", "material_id": self.b})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["chosen"]["material_id"], self.b)
        self.assertEqual(project_ctx.graph_names(P)["graph-SNP-M-101"], self.sheet(self.b)["name"], "고른 파일로 갈아탐")
        self.assertGreater(self.lost(), 0, "다른 파일의 같은 id로 잇지 않고 찾지 못한 구성요소로 남김(설계 §5)")
        lost = [m for m in self.events if m.get("t") == "event" and m.get("name") == "study.lost"]
        self.assertTrue(lost, "갈아탄 뒤 잃은 것을 알림")
        back = self.eng.dispatch("sources.choose", {"drawing_number": "graph-SNP-M-101", "material_id": self.a})
        self.assertTrue(back["ok"], back)
        self.assertEqual(project_ctx.graph_names(P)["graph-SNP-M-101"], self.sheet(self.a)["name"])
        self.assertEqual(self.lost(), 0, "원래 파일로 돌아오면 되찾는다")


class SettleOnOpenTest(ShellSheetBase):
    def setUp(self):
        super().setUp()
        self.a, self.b, _n = self.collided("pdf")
        self.assertFalse(sources.load_seats(P)[1], "시험 전제: 정착 전 프로젝트")
        self.eng = self.engine()

    def test_open_settles_once_and_brings_the_hidden_drawing_in(self):
        before = sorted(project_ctx.graph_names(P))
        res = self.eng.settle_on_open()
        self.assertTrue(res and res["changed"], res)
        self.assertTrue(sources.load_seats(P)[1])
        after = sorted(project_ctx.graph_names(P))
        self.assertEqual(len(after), len(before) + 1, "가려졌던 도면이 들어옴: %s → %s" % (before, after))
        self.assertTrue(set(before) <= set(after), "보이던 도면의 이름은 그대로")
        again = self.eng.settle_on_open()
        self.assertFalse(again["changed"], "두 번째는 아무것도 쓰지 않음")

    def test_it_waits_for_running_work(self):
        self.eng._jobs["j1"] = {"label": "등록", "state": "running", "kind": "register"}
        self.assertIsNone(self.eng.settle_on_open())
        self.assertFalse(sources.load_seats(P)[1], "작업이 도는 동안은 정착하지 않음(추출 맨 앞이 한다)")

    def test_a_sheet_that_cannot_be_rebuilt_is_shown_with_its_reason(self):
        bg = data.script_module("build_graph")
        with mock.patch.object(bg, "render_one", side_effect=ValueError("추출 결과가 깨졌습니다")):
            res = self.eng.settle_on_open()
        self.assertTrue(res and res["skipped"], res)
        from hazop.shell import api_next
        items = {i["kind"]: i for i in api_next.summary(self.eng)["items"]}
        self.assertIn("sheet_skipped", items, list(items))
        self.assertTrue(items["sheet_skipped"]["detail"])
        self.assertNotRegex(items["sheet_skipped"]["text"] + (items["sheet_skipped"]["detail"] or ""), TEMP)


class MixedRowTest(ShellSheetBase):
    """검토 지적 1·3: 같은 번호에 pdf a(작업 있음)·drawio b·pdf c. 형식 줄에서도 파일로 a로 돌아갈 수 있고, 미리 알림 수는 후보마다다."""

    def setUp(self):
        super().setUp()
        self.a = self.register(self.copy_in("SNP-M-101", "pdf", "in-a"), NUMBER)
        pg, before = self.make_nodes(self.a)
        self.members = before["nodes"][0]["members"]
        self.b = self.register(self.copy_in("SNP-M-101", "drawio", "in-b"), dict(NUMBER))
        self.c = self.register(self.copy_in("SNP-M-102", "pdf", "in-c"), dict(NUMBER))
        self.eng = self.engine()

    def conflict_row(self):
        from hazop.shell import api_drawings
        rows = api_drawings.source_conflicts(self.eng)["conflicts"]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_files_of_a_format_row_can_be_chosen_and_the_preview_counts_per_candidate(self):
        r = self.conflict_row()
        self.assertEqual((r["kind"], len(r["candidates"])), ("format", 3))
        using = [x for x in r["candidates"] if x["in_use"]]
        self.assertEqual(len(using), 1)
        self.assertEqual(using[0]["recheck"], 0, "지금 쓰는 파일을 고르면 다시 확인할 것이 없다")
        self.assertTrue(all(x["recheck"] == r["nodes_on_sheet"] for x in r["candidates"] if not x["in_use"]), r["candidates"])
        other = next(x["material_id"] for x in r["candidates"] if not x["in_use"] and x["format"] == "pdf_vector") if using[0]["material_id"] == self.a else self.a
        out = self.eng.dispatch("sources.choose", {"drawing_number": r["graph_id"], "material_id": other})
        self.assertTrue(out["ok"] and out["data"]["applied"], out)
        back = self.eng.dispatch("sources.choose", {"drawing_number": r["graph_id"], "material_id": self.a})
        self.assertTrue(back["ok"] and back["data"]["applied"], back)
        self.assertEqual(project_ctx.graph_names(P)[r["graph_id"]], self.sheet(self.a)["name"], "형식 줄에서도 파일 a로 돌아옴")
        pg = project_ctx.project_graph(P)
        n = nodes.load(pg)["nodes"][0]
        self.assertEqual((n["members"], n.get("lost") or []), (self.members, []), "a로 돌아오면 구간을 되찾음")

    def test_a_confirmed_section_switched_away_and_back(self):
        pg, ns = project_ctx.project_graph(P), None
        ns = nodes.load(pg)
        nid = ns["nodes"][0]["node_id"]
        r = self.eng.dispatch("nodes.confirm", {"project_id": P, "set_rev": ns.get("set_rev") or 0, "node_ids": [nid],
                                                "targets": [{"node_id": nid, "rev": ns["nodes"][0].get("rev") or 1, "state": "applied"}]},
                              project=P, via_web=True)
        self.assertTrue(r["ok"], r)
        row = self.conflict_row()
        # 실제 창 4차: 미리 알림이 '확정이 풀린다'를 밝히도록 바꾸면 풀릴 확정 구간 수를 싣는다
        self.assertEqual(row["confirmed_on_sheet"], 1)
        self.assertEqual({x["material_id"]: x["released"] for x in row["candidates"]}[self.a], 0, "지금 쓰는 파일은 풀릴 것이 없다")
        self.assertTrue(all(x["released"] == 1 for x in row["candidates"] if x["material_id"] != self.a), row["candidates"])
        away = next(x["material_id"] for x in row["candidates"] if x["material_id"] != self.a)
        self.assertTrue(self.eng.dispatch("sources.choose", {"drawing_number": row["graph_id"], "material_id": away})["ok"])
        self.assertTrue(self.eng.dispatch("sources.choose", {"drawing_number": row["graph_id"], "material_id": self.a})["ok"])
        n = nodes.load(project_ctx.project_graph(P))["nodes"][0]
        self.assertEqual((n["members"], n.get("lost") or []), (self.members, []), "확정 구간도 되찾음")


class FormatVersusFileTest(MixedRowTest):
    """검토 확인 항목: 형식 고르기(chosen)와 파일 고르기(seats)가 서로 다른 원본을 가리키면 파일이 이긴다(설계 §3 차례 2).
    형식을 다시 고르면 앞서 고른 파일을 내려놓고 그 형식을 쓴다."""

    def test_the_card_text_has_no_format_codes_or_folder_names(self):
        """실제 창 3차 D: 카드 글 "…원본이 drawio·pdf_vector 형식으로 함께 있습니다…"(형식 코드), 번호 전 폴더 이름."""
        row = self.conflict_row()
        self.assertIn("PDF 파일", row["text"])
        self.assertIn("파일과 ", row["text"], "조사: 파일과(실제 창 4차)")
        self.assertNotRegex(row["text"], r"pdf_vector|graph-|SCN__|material-")

    def test_file_choice_wins_over_format_and_format_choice_drops_it(self):
        row = self.conflict_row()
        gid = row["graph_id"]
        drawio = next(x["material_id"] for x in row["candidates"] if x["format"] == "drawio")
        self.assertTrue(self.eng.dispatch("sources.choose", {"drawing_number": gid, "format": "drawio"})["ok"])
        self.assertEqual(project_ctx.graph_names(P)[gid], self.sheet(drawio)["name"])
        self.assertTrue(self.eng.dispatch("sources.choose", {"drawing_number": gid, "material_id": self.c})["ok"])
        self.assertEqual(project_ctx.graph_names(P)[gid], self.sheet(self.c)["name"], "형식으로 drawio를 골라 두었어도 고른 파일(c, PDF)을 쓴다")
        r = self.conflict_row()
        self.assertEqual((r["chosen"], r["chosen_material"]), (None, self.c), "화면에는 파일을 고른 것으로만 보인다")
        self.assertTrue(self.eng.dispatch("sources.choose", {"drawing_number": gid, "format": "drawio"})["ok"])
        self.assertEqual(project_ctx.graph_names(P)[gid], self.sheet(drawio)["name"], "형식을 다시 고르면 고른 파일을 내려놓는다")

    test_files_of_a_format_row_can_be_chosen_and_the_preview_counts_per_candidate = None
    test_a_confirmed_section_switched_away_and_back = None

class ApplyFailTest(FileChoiceTest):
    """검토 지적 2: 고른 뒤 판 이전이 실패하면 답에 싣는다(화면은 '도면 변경 반영하기'를 보인다)."""

    def test_a_failed_catch_up_is_in_the_answer(self):
        with mock.patch.object(data, "catch_up_study", lambda pid: {"error": "디스크 가득"}):
            out = self.eng.dispatch("sources.choose", {"drawing_number": "graph-SNP-M-101", "material_id": self.b})
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["data"]["applied"], out)
        self.assertIn("도면 변경 반영하기", out["data"]["apply_text"])
        from hazop.shell import api_nodes
        self.assertTrue(api_nodes.summary(self.eng).get("stale"), "구간은 옛 판 그대로(안전망이 막는다)")
        fixed = self.eng.dispatch("nodes.catch_up", {"project_id": P}, project=P, via_web=True)
        self.assertTrue(fixed["ok"] and fixed["data"]["changed"], fixed)

    test_the_read_carries_files_names_and_the_preview_count = None
    test_choosing_another_file_switches_and_reports_what_was_lost_then_back = None


class OpenThreadTest(ShellSheetBase):
    """검토 확인 항목·지적 5: 열 때 정착은 실제 스레드 길(project.open_check·project.set)에서 돌고 창 닫기(wait_jobs)가 기다린다.
    통째로 실패하면 알림 한 줄. 정착이 도는 동안 시작한 등록 작업은 끝날 때까지 기다린다."""

    def setUp(self):
        super().setUp()
        self.collided("pdf")
        self.eng = self.engine()

    def test_open_check_runs_in_a_tracked_thread(self):
        out = self.eng.dispatch("project.open_check", {})
        self.assertTrue(out["ok"], out)
        self.assertTrue(any(t.name == "catch-up-on-open" for t in self.eng._threads), "닫을 때 기다릴 스레드 목록에 있다")
        self.assertTrue(self.eng.wait_jobs(60))
        self.assertTrue(sources.load_seats(P)[1], "열 때 정착함")

    def test_project_set_runs_the_same_path(self):
        out = self.eng.dispatch("project.set", {"project_id": P})
        self.assertTrue(out["ok"], out)
        self.assertTrue(self.eng.wait_jobs(60))
        self.assertTrue(sources.load_seats(P)[1])

    def test_a_failed_settle_tells_the_user(self):
        with mock.patch.object(data, "settle_sheets", side_effect=OSError("디스크 가득")):
            self.assertIsNone(self.eng.settle_on_open())
        notes = [m["data"]["text"] for m in self.events if m.get("t") == "event" and m.get("name") == "app.notice"]
        self.assertTrue(notes and "정리하지 못했습니다" in notes[-1], notes)

    def test_a_register_job_waits_for_a_running_settle(self):
        import threading
        import time
        order, real = [], data.settle_sheets

        def slow(pid, *a, **k):
            order.append("settle-start")
            time.sleep(0.6)
            out = real(pid, *a, **k)
            order.append("settle-end")
            return out
        with mock.patch.object(data, "settle_sheets", slow):
            t = threading.Thread(target=self.eng.settle_on_open)
            t.start()
            time.sleep(0.2)
            self.eng.start_job("등록", lambda progress: order.append("job"), kind="register")
            t.join(30)
        self.assertEqual(order, ["settle-start", "settle-end", "job"], "등록 작업이 정착과 겹침")


if __name__ == "__main__":
    unittest.main()
