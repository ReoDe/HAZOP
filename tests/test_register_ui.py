"""① 자료 등록 화면의 빈 상태·버튼 위계·진행/실패 행(UIUX 개선 U-09·U-10·U-11)."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import test_app as base  # noqa: E402

tearDownModule = base.tearDownModule


def primaries(scr):
    from PySide6.QtWidgets import QPushButton
    return [b.text() for b in scr.findChildren(QPushButton) if b.objectName() == "primary" and b.isVisibleTo(scr)]


class RegisterUiTest(base.AppTestBase):
    def screen(self):
        win = self.make_window()
        win.show()
        return win, win.screens[0]

    def test_empty_state_has_one_action_and_no_result_box(self):
        win, scr = self.screen()
        self.assertEqual(scr.list_stack.currentIndex(), 0)
        self.assertFalse(scr.result.isVisibleTo(scr))
        self.assertEqual(primaries(scr), ["파일 선택…"])
        self.assertFalse(scr.btn_register.isEnabled())
        self.assertIn("파일을 고르면", scr.register_hint.text())
        from PySide6.QtWidgets import QLabel
        texts = " ".join(lab.text() for lab in scr.list_stack.widget(0).findChildren(QLabel))
        self.assertIn("등록된 자료가 없습니다", texts)
        for internal in (os.sep, "자료저장소", os.environ["HAZOP_STORE_ROOT"]):
            self.assertNotIn(internal, texts)
        self.assertTrue(all(label and callable(fn) for label, _, fn in scr.commands()))
        self.assertIn("파일 선택…", [c[0] for c in scr.commands()])

    def test_clicking_drop_zone_opens_file_picker(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from hazop.app.screens import register
        win, scr = self.screen()
        sample = base.sample_file("SNP-M-102", "drawio")
        with mock.patch.object(register.QFileDialog, "getOpenFileName", return_value=(sample, "")) as dlg:
            QTest.mouseClick(scr.drop, Qt.LeftButton)
        dlg.assert_called_once()
        base.pump(win)
        self.assertEqual(scr.source_path, sample)

    def test_candidate_buttons_and_primary_follow_state(self):
        win, scr = self.screen()
        self.assertFalse(scr.set_files([base.sample_file("SNP-M-102", "drawio")] * 2))
        self.assertTrue(all(not b.isVisibleTo(scr) for b in scr.meta_btns.values()))
        self.assertIn("한 개만", scr.register_hint.text())
        self.assertTrue(scr.set_files([base.sample_file("SNP-M-102", "drawio")]))
        self.assertIn("확인이 끝나면", scr.register_hint.text())
        base.pump(win)
        cands = scr.preview.get("auto_candidates") or {}
        for key, btn in scr.meta_btns.items():
            if cands.get(key):
                self.assertTrue(btn.isVisibleTo(scr), key)
                self.assertIn("후보 '%s" % cands[key]["value"][:10], btn.text())
                self.assertEqual(btn.toolTip(), cands[key]["value"])        # 긴 값은 버튼에서 줄이고 전체는 툴팁
            else:
                self.assertFalse(btn.isVisibleTo(scr), key)
        self.assertTrue(cands.get("drawing_number"))
        self.assertEqual(primaries(scr), ["등록"])                       # 빈 목록 안내의 '파일 선택'은 주 버튼에서 내려감
        self.assertEqual(scr.register_hint.text(), "")
        scr.do_register()
        base.pump(win, 0.1)
        self.assertEqual(scr.rows[0]["record"]["status"], "registered")
        self.assertFalse(scr.job.isVisibleTo(scr))
        self.assertIsNone(scr.source_path)                                # 등록한 파일은 내려놓음
        self.assertEqual(primaries(scr), ["추출·그래프 만들기"])

    def test_progress_row_then_failure_with_retry(self):
        from hazop.app.screens import register
        win, scr = self.screen()
        self.assertTrue(scr.set_files([base.sample_file("SNP-M-102", "drawio")]))
        base.pump(win)
        scr.do_register()
        base.pump(win, 0.1)
        scr.table.selectRow(0)
        with mock.patch.object(register.data, "extract_and_graph", side_effect=ValueError("등록 해시 불일치")):
            scr.do_extract()
            self.assertTrue(scr.job.isVisibleTo(scr))
            self.assertTrue(scr.job.bar.isVisibleTo(scr))
            self.assertIn("선·기호 추출", scr.job.step.text())
            self.assertIn("선·기호 추출", win.msg_label.text())
            self.assertFalse(scr.btn_register.isEnabled() or scr.btn_extract.isEnabled())
            self.assertIn("진행 중인 작업", scr.register_hint.text())
            base.pump(win, 0.1)
        self.assertTrue(scr.job.retry_btn.isVisibleTo(scr))
        self.assertFalse(scr.job.bar.isVisibleTo(scr))
        self.assertIn("등록 해시 불일치", scr.job.cause.text())
        self.assertNotIn("자세한 내용", scr.job.cause.text())
        self.assertIn("실패", win.msg_label.text())
        self.assertIn("완료로 표시하지 않음", scr.result.toPlainText())
        scr.job.retry_btn.click()
        base.pump(win, 0.1)
        self.assertFalse(scr.job.isVisibleTo(scr))
        self.assertIn("추출·그래프 생성 완료", scr.result.toPlainText())
        self.assertEqual(win.msg_label.text(), "")


if __name__ == "__main__":
    unittest.main()
