"""표제란을 확정하지 않은 도면(확정 도면번호 없음)이 든 프로젝트의 내보내기(시나리오 N10 결함 재현).
실행: python -m unittest tests.test_export_unnumbered

표제란 확정은 사람이 나중에 하는 일이라 미확정 도면이 있는 것이 보통이다. 프로젝트 그래프의 그 도면은 drawing_number가 None이다.
Excel 내보내기는 세 범위 모두 멈추지 않고, 그 도면을 '(번호 미확정)'과 그래프 ID로 적는다(미확정 번호를 확정값처럼 적지 않음).
인계 묶음 내보내기도 멈추지 않는다. 실제 명령(results.export_excel·results.export_ie)과 저장 길로 돈다. 임시 작업 루트만 쓴다.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import copy  # noqa: E402
from unittest import mock  # noqa: E402

import openpyxl  # noqa: E402

from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_shell_results import Base  # noqa: E402


class UnnumberedDrawingExportTest(Base):
    def setUp(self):
        super().setUp()
        from hazop.app import project_ctx
        from tests.test_study_export import DEVS as XDEVS, sample
        r, ns, pg, _span, _single = sample()     # 내보내기 시험과 같은 표본(두 도면, 걸친 구간)
        for p in (mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(XDEVS)),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: pg)):
            p.start()
            self.addCleanup(p.stop)
        self.ns, self.g = ns, pg
        sn.save(ns)
        res.save(r, ns.get("project_id"))
        self.engine.settings["project_id"] = ns.get("project_id")
        sheet = self.g["sheets"][0]
        self.gid = sheet["graph_id"]
        sheet["drawing_number"] = None          # 표제란을 아직 확정하지 않은 도면
        self.engine.hooks["save_path"] = self.paths

    def paths(self, kind, name):
        self.save_to = os.path.join(self.tmp, "out-" + kind + ".xlsx")
        return self.save_to

    def export(self, **a):
        r = self.call("results.export_excel", a)
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["data"].get("cancelled"), r)
        return openpyxl.load_workbook(self.save_to)

    def cover(self, wb):
        ws = wb.worksheets[0]
        return {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(1, ws.max_row + 1)}

    def test_all_three_scopes_export_and_name_the_unnumbered_drawing(self):
        node = self.read("results")["nodes"][0]["node_id"]
        for a in ({"scope": "all"}, {"scope": "approved"}, {"scope": "nodes", "node_ids": [node]}):
            wb = self.export(**a)
            listed = self.cover(wb)["도면 목록"]
            self.assertIn("(번호 미확정) %s" % self.gid, listed, a)
            self.assertNotIn("None", listed, a)
            seen = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    self.assertFalse(any(isinstance(v, str) and ("None" in v) for v in row), (a, ws.title, row))
                    seen += [ws.title for v in row if isinstance(v, str) and "(번호 미확정) " + self.gid in v]
            self.assertTrue(set(seen) - {wb.worksheets[0].title}, "워크시트(도면 열·구간 표기)에도 번호 미확정 도면이 그 표기로 남는다: %s" % a)

    def test_ie_bundle_still_exports(self):
        r = self.call("results.export_ie", {})
        self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isfile(self.save_to))


if __name__ == "__main__":
    unittest.main()
