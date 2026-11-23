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


if __name__ == "__main__":
    unittest.main()
