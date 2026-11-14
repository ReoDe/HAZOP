"""① 등록 화면의 'AI 검토' 토글·진행 줄과 AI 후보 확정 창(hazop.app.screens.ai_review_panel). 실제 Claude를 부르지 않는다."""

import glob
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop import paths  # noqa: E402
from hazop.extract import ai_review as ar  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from tests import test_app as base  # noqa: E402
from tests.test_ai_review import StubClient, ex_fixture, good_answers  # noqa: E402

tearDownModule = base.tearDownModule
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wait_for(signal, ms=10000):
    from PySide6.QtCore import QEventLoop, QTimer
    got = []
    loop = QEventLoop()
    signal.connect(lambda *a: (got.append(a), loop.quit()))
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    return got


class AiReviewBarTest(base.AppTestBase):
    def bar(self, ok=True, state="ok"):
        win = self.make_window()
        win.show()
        conn = win.ai_conn
        p1 = mock.patch.object(conn, "can_start", lambda method=None: ok)
        p2 = mock.patch.object(conn, "status", lambda method=None: {"state": state, "detail": ""})
        for p in (p1, p2):
            p.start()
            self.addCleanup(p.stop)
        scr = win.screens[0]
        scr.ai_bar.refresh_availability()
        return win, scr.ai_bar

    def test_unavailable_shows_notice_only(self):
        _, bar = self.bar(ok=False, state="not_installed")
        self.assertFalse(bar.toggle.isVisibleTo(bar))
        self.assertTrue(bar.notice.isVisibleTo(bar))
        self.assertIn("Claude Code가 없습니다", bar.notice.text())
        self.assertIn("스크립트만", bar.notice.text())
        self.assertFalse(bar.enabled())

    def test_toggle_default_off_and_estimate(self):
        _, bar = self.bar()
        self.assertTrue(bar.toggle.isVisibleTo(bar))
        self.assertFalse(bar.toggle.isChecked())
        self.assertFalse(bar.enabled())
        self.assertIn("스크립트만", bar.estimate.text())
        bar.toggle.setChecked(True)
        bar.cap.setValue(5)
        self.assertTrue(bar.enabled())
        self.assertIn("많아도 5회", bar.estimate.text())

    def test_run_saves_candidates_and_reports(self):
        win, bar = self.bar()
        client = StubClient(good_answers)
        with mock.patch.object(win.ai_conn, "make_client", lambda method=None: client):
            bar.toggle.setChecked(True)
            self.assertTrue(bar.start([("ui-run", ex_fixture())]))
            self.assertTrue(bar.running())
            got = wait_for(bar.reviewed)
        self.assertTrue(got)
        (done,), = got
        self.assertEqual(done[0][0], "ui-run")
        self.assertGreater(done[0][1], 0)
        self.assertFalse(bar.running())
        doc = ar.load_doc("ui-run")
        self.assertEqual(len(doc["candidates"]), done[0][1])
        self.assertEqual(doc["runs"][-1]["calls"], 1)
        from hazop.app.screens.ai_review_panel import summary_text
        self.assertIn("AI 후보", summary_text(done))

    def test_first_page_only(self):
        win, bar = self.bar()
        client = StubClient(good_answers)
        bar.pages.setCurrentIndex(1)
        with mock.patch.object(win.ai_conn, "make_client", lambda method=None: client):
            bar.start([("ui-p1", ex_fixture()), ("ui-p2", ex_fixture())])
            (done,), = wait_for(bar.reviewed)
        self.assertEqual([d[0] for d in done], ["ui-p1"])


class AiReviewDialogTest(base.AppTestBase):
    def test_accept_bulk_and_revert(self):
        from hazop.extract.adapters import pdf_vector
        from hazop.app.screens.ai_review_panel import AiReviewDialog
        win = self.make_window()
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        name = "ui-dialog"
        ex = pdf_vector.extract(pdf, page=0, repo_root=os.environ["HAZOP_WORK_ROOT"])
        os.makedirs(paths.output_root("extract", name), exist_ok=True)
        with open(paths.output_root("extract", name, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        valves = [n for n in ex["nodes"] if n.get("kind") == "manual_valve"][:1]
        doc = ar.new_doc(name, ex)
        doc["candidates"] = [ar.make_candidate("t-%d" % i, "tag", v, "tag", ["V90%d" % i], 0.95, "시험")
                             for i, v in enumerate(valves)]
        ar.save_doc(doc)
        dlg = AiReviewDialog(win, name)
        self.addCleanup(dlg.close)
        self.assertEqual(dlg.table.rowCount(), len(valves))
        self.assertTrue(dlg.btn_bulk.isEnabled())
        from PySide6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            dlg.accept_bulk()
        self.assertTrue(all(c["status"] == "accepted" for c in dlg.doc["candidates"]))
        self.assertEqual(len(corrections.load(name)["ops"]), len(valves))
        dlg.table.selectRow(0)
        dlg.decide("revert")
        self.assertEqual(dlg.doc["candidates"][0]["status"], "proposed")
        self.assertEqual(corrections.load(name)["ops"], [])
        dlg.table.selectRow(0)
        dlg.decide("reject")
        self.assertEqual(ar.load_doc(name)["candidates"][0]["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
