"""⑤ 분석 결과 화면의 프로젝트(도면 간) 표시: 행 이름 도면 범위, 워크시트 머리말, 다른 도면 태그, 옛 결과 이전,
고른 행 없는 A 안내. 실행: python -m unittest tests.test_results_project_ui

두 도면(SNP-M-101 → SNP-M-102)을 잇는 합성 그래프를 임시 작업 루트에 둔다. 네트워크·AI 호출 없음.
"""

import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_project_graph import cont, sheet  # noqa: E402

AT = "2026-11-07T00:00:00Z"
HEADER = r"^도면 SNP-M-10[12] → SNP-M-10[12] · 시작: .+\(SNP-M-10[12]\) / 끝: .+\(SNP-M-10[12]\)$"


class StubApp:
    def __init__(self):
        self.messages, self.toasts = [], []

    def status_message(self, text):
        self.messages.append(text)

    def toast(self, text, undo=None, actions=(), ms=5000):
        self.toasts.append(text)
        self.toast_actions = [label for label, _fn in actions]

    def log_error(self, title, exc):
        raise AssertionError("%s: %s" % (title, exc))

    def mark_saved(self, _at):
        pass

    def update_header(self):
        pass

    def set_selection(self, _sel):
        pass


class ResultsProjectUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication(["test"])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-res-proj-")
        self._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = self.tmp
        self.a = sheet("SNP-M-101", cont("C1", "TO SNP-M-102\nL-1"), valve=True)
        self.b = sheet("SNP-M-102", cont("C1", "FROM SNP-M-101\nL-1"), valve=True)
        for g in (self.a, self.b):
            d = paths.output_in(self.tmp, "graph", g["source"]["drawing_number"])
            os.makedirs(d)
            with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as fh:
                json.dump(g, fh)

    def tearDown(self):
        if self._env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def screen(self, drawing="SNP-M-102"):
        from hazop.app.screens.results import ResultsScreen
        app = StubApp()
        scr = ResultsScreen(app)
        self.addCleanup(scr.deleteLater)
        scr.combo.blockSignals(True)
        scr.combo.addItems(["SNP-M-101", "SNP-M-102"])
        scr.combo.setCurrentText(drawing)
        scr.combo.blockSignals(False)
        scr._load()
        return app, scr

    def confirm_project_set(self):
        from hazop.app import project_ctx
        ctx = project_ctx.load("SNP-M-102")
        ns, _ = ctx.load_set()
        ns = sn.confirm(ns, ctx.pg, "EJ", at=AT)
        sn.save(ns)
        return ns

    def spanning(self, scr):
        return next(n for n in scr.node_set["nodes"] if scr.view[n["node_id"]]["spans_drawings"])

    def test_row_label_header_and_other_drawing_tags(self):
        self.confirm_project_set()
        app, scr = self.screen()
        self.assertEqual(scr.stack.currentIndex(), 1)
        node = self.spanning(scr)
        row = scr._row_of(node["node_id"])
        head = scr.matrix.verticalHeaderItem(row)
        self.assertTrue(head.text().endswith("[101 → 102] ⇄"), head.text())
        self.assertIn("시작:", head.toolTip())
        self.assertRegex(head.toolTip(), r"이 도면 \d+ / 전체 \d+")
        self.assertIs(scr.main_focus(), scr.matrix, "칸을 열기 전 초점은 행렬")

        did = scr.deviations[0]["deviation_id"]
        doc = json.loads(json.dumps(scr.results))
        cell = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (node["node_id"], did))
        cell.update(state="analyzed", entries=[
            {"entry_id": "E1", "cause": "SNP-M-101-E 누설", "consequence": "SNP-M-102-E 수위 저하", "safeguards": [],
             "recommendation": "권고", "risk": None, "origin": "ai_draft", "status": "proposed"}])
        scr.set_results(doc)
        self.assertTrue(scr.open_cell(node["node_id"], did))
        self.assertRegex(scr.sheet_span.text(), HEADER)
        self.assertIn("[101 → 102] ⇄", scr.sheet_title.text())
        self.assertEqual(scr.table.item(0, 0).text(), "SNP-M-101-E(101) 누설", "다른 도면 태그에 도면 번호")
        self.assertEqual(scr.table.item(0, 1).text(), "SNP-M-102-E 수위 저하", "보는 도면 태그는 그대로")
        self.assertEqual(scr._cell_doc()["entries"][0]["cause"], "SNP-M-101-E 누설", "저장값은 그대로")
        self.assertIs(scr.main_focus(), scr.table, "칸이 열리면 초점은 워크시트")
        self.assertEqual(scr.selected_entry()["entry_id"], "E1", "칸을 열면 첫 미검토 항목을 골라 둠")

        scr.table.clearSelection()
        self.assertFalse(scr.set_entry_status("approved"))
        self.assertEqual(app.messages[-1], "승인할 항목 행을 먼저 고르세요 (↑↓ 또는 클릭).")
        self.assertFalse(scr.edit_selected({"cause": "x"}))
        self.assertIn("수정할 항목 행을 먼저", app.messages[-1])
        scr.select_entry(0)
        self.assertTrue(scr.set_entry_status("approved"))
        saved = next(c for c in res.load(scr.node_set)["cells"] if c["entries"])
        self.assertEqual(saved["entries"][0]["status"], "approved")

    def test_excel_export_button_palette_and_toast(self):
        import openpyxl
        from hazop.export import study_xlsx
        self.confirm_project_set()
        app, scr = self.screen()
        self.assertTrue(scr.export_btn.isEnabled())
        self.assertIn("Excel로 내보내기…", [c[0] for c in scr.commands()])
        node = self.spanning(scr)
        doc = json.loads(json.dumps(scr.results))
        cell = next(c for c in doc["cells"] if c["node_id"] == node["node_id"])
        cell.update(state="analyzed", entries=[
            {"entry_id": "E1", "cause": "SNP-M-101-E 누설", "consequence": "c", "safeguards": [], "recommendation": "r",
             "severity": 4, "frequency": 3, "risk": 5, "origin": "ai_draft", "status": "approved"}])
        scr.set_results(doc)
        out = os.path.join(self.tmp, "export", "x.xlsx")
        os.makedirs(os.path.dirname(out))
        self.assertEqual(scr.export_excel(path=out, scope="all"), out)
        self.assertEqual(app.toast_actions, ["열기", "폴더 열기"])
        ws = openpyxl.load_workbook(out)[study_xlsx.SHEETS[2]]
        head = [c.value for c in ws[1]]
        self.assertEqual(ws.cell(row=2, column=head.index("위험도") + 1).value, "5 불허")
        self.assertEqual(ws.cell(row=2, column=2).value, "SNP-M-101, SNP-M-102")

    def test_old_results_wait_for_confirm_then_move_with_flags(self):
        old = sn.confirm(sn.propose(self.a, at=AT), self.a, "EJ", at=AT)
        sn.save(old)
        r = res.empty_results(old, res.load_deviations())
        r["cells"][0].update(state="analyzed", entries=[
            {"entry_id": "e1", "origin": "ai_draft", "status": "approved", "cause": "c"}])
        old_res_path = res.save(r, old["project_id"])
        with open(old_res_path, "rb") as fh:
            before = fh.read()

        _app, scr = self.screen("SNP-M-101")
        self.assertEqual(scr.stack.currentIndex(), 0, "옮긴 프로젝트 집합은 제안 상태라 결과를 보이지 않음")
        self.assertIn("④ 검토구간에서 구간을 확정", scr.empty.text())
        self.assertFalse(scr.banner.isHidden())
        self.assertIn("백업", scr.banner.label.text())

        ns = sn.load(scr.ctx.pg)
        sn.save(sn.confirm(ns, scr.ctx.pg, "EJ", at=AT))
        app, scr = self.screen("SNP-M-101")
        self.assertEqual(scr.stack.currentIndex(), 1)
        self.assertIn("분석 결과를 옮김", scr.banner.label.text())
        self.assertTrue(app.toasts, "이전 알림 토스트")
        moved = [(c["node_id"], c["deviation_id"], e) for c in scr.results["cells"] for e in c["entries"]]
        self.assertEqual(len(moved), 1)
        nid, did, entry = moved[0]
        self.assertEqual(entry["status"], "approved", "사람 상태는 그대로")
        self.assertTrue(entry.get("scope_changed"), "도면을 넘어 넓어진 구간으로 옮긴 항목")
        scr.open_cell(nid, did)
        status = scr.table.item(0, 6)
        self.assertEqual(status.text(), "범위 바뀜 · 다시 확인 · 승인")
        self.assertIn("범위", status.toolTip())
        with open(old_res_path, "rb") as fh:
            self.assertEqual(fh.read(), before, "옛 결과 파일은 그대로")
        backups = os.listdir(paths.folder_in(self.tmp, "backup"))
        self.assertTrue(any(b.endswith("분석결과-이전") for b in backups), backups)

        _app, again = self.screen("SNP-M-101")
        self.assertTrue(again.banner.isHidden(), "두 번째에는 다시 옮기지 않음")
        self.assertEqual([e["status"] for c in again.results["cells"] for e in c["entries"]], ["approved"])

    def test_reconfirmed_set_keeps_approved_entries(self):
        """확정 해제 → 다시 확정해도 사람이 승인한 항목이 ⑤에서 사라지지 않는다(§4.6, D11)."""
        ns = self.confirm_project_set()
        r = res.empty_results(ns, res.load_deviations())
        r["cells"][0].update(state="analyzed", entries=[
            {"entry_id": "e1", "origin": "ai_draft", "status": "approved", "cause": "c"}])
        res.save(r, ns["project_id"])
        from hazop.app import project_ctx
        pg = project_ctx.load("SNP-M-102").pg
        sn.save(sn.confirm(sn.reopen(ns, at=AT), pg, "EJ", at="2026-11-10T00:00:00Z"))
        _app, scr = self.screen()
        self.assertEqual([e["status"] for c in scr.results["cells"] for e in c["entries"]], ["approved"])
        saved = res.load(sn.load(pg))
        self.assertFalse(res.is_stale(saved, sn.load(pg)), "옮긴 결과를 바로 저장해 다른 화면도 같은 결과를 읽음")
        self.assertEqual([e["status"] for c in saved["cells"] for e in c["entries"]], ["approved"])

    def test_screening_buckets_have_no_rows_and_low_nodes_come_last(self):
        """⑤ 행렬·AI 일괄·Excel 범위는 확정·잠금 구간이고 낮음 구간은 맨 아래(규격 v2 S4·D6). 옛 '스크리닝 제외'로 확정한
        구간은 읽을 때 미확정으로 내려와(§2.5, nodes.settle_screen) 행이 없다."""
        ns = self.confirm_project_set()
        status = {n["node_id"]: n["screen"]["status"] for n in ns["nodes"]}
        from hazop.app import project_ctx
        pg = project_ctx.load("SNP-M-102").pg
        keeps = [nid for nid, st in status.items() if st == "keep"]
        bucket_like = sn.reopen(ns, at=AT)
        bucket_like = sn.screen_override(bucket_like, keeps[0], "excluded", "검토 범위 밖", at=AT)
        bucket_like = sn.screen_override(bucket_like, keeps[1], "low", "부속 배관", at=AT)
        sn.save(sn.confirm(bucket_like, pg, "EJ", at="2026-11-10T00:00:00Z"))
        _app, scr = self.screen()
        rows = [scr._node_at(r) for r in range(scr.matrix.rowCount())]
        self.assertNotIn(keeps[0], rows, "제외 구간은 행이 없음")
        self.assertEqual(rows[-1], keeps[1], "낮음 구간은 맨 아래")
        self.assertEqual(sn.node_state(next(n for n in sn.load(pg)["nodes"] if n["node_id"] == keeps[0])), "applied",
                         "옛 제외 구간은 미확정으로 읽힘")
        self.assertNotIn("스크리닝 제외", scr.kpi.text(), "v2에는 제외 묶음 수가 없음")
        self.assertNotIn(keeps[0], {u["node_id"] for u in scr._plan("all")}, "AI 일괄 범위에서 뺌")
        self.assertIn(keeps[1], {u["node_id"] for u in scr._plan("all")}, "낮음은 AI 일괄 범위에 넣음")
        path = scr.export_excel(os.path.join(self.tmp, "x.xlsx"), scope="all", reviewer="EJ")
        import openpyxl
        names = [c.value for c in openpyxl.load_workbook(path).worksheets[1]["A"]]
        self.assertFalse(any(v and keeps[0] == v for v in names), "Excel 구간 목록에도 없음")
        cover = {r[0].value: r[1].value for r in openpyxl.load_workbook(path).worksheets[0].iter_rows() if r[0].value}
        self.assertEqual(cover.get("구간 수", len(rows)), len(rows), "표지 구간 수 = 내보낸 구간")
        did = scr.deviations[0]["deviation_id"]
        self.assertFalse(scr.open_cell(keeps[0], did), "미확정 구간 칸은 열지 않고 안내만")
        self.assertNotIn(keeps[0], {u["node_id"] for u in scr._plan("failed")}, "미확정 구간은 다시 실행 범위에 없음")

    def test_no_cell_open_hint(self):
        self.confirm_project_set()
        app, scr = self.screen()
        self.assertFalse(scr.set_entry_status("rejected"))
        self.assertIn("칸을 먼저 여세요", app.messages[-1])


if __name__ == "__main__":
    unittest.main()
