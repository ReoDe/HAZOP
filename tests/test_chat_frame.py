"""3단 배치의 오른쪽 채팅 창 틀(단위 S-frame). 실행: python -m unittest tests.test_chat_frame

채팅 창 내용물은 뒤 단위(C2)가 `set_chat_widget`으로 끼운다. 여기서는 틀만 본다: 접기·펴기, 창 폭에 따른 처음 상태,
접힘·폭 기억, 위젯 교체, 단계·도면 바뀜 신호. 오프스크린이며 실제 창 조작은 하지 않는다.
"""

import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from PySide6.QtWidgets import QLabel  # noqa: E402

from tests.test_app import pump, tearDownModule  # noqa: E402,F401


class ChatFrameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-chatframe-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.settings = os.path.join(tempfile.mkdtemp(dir=self.tmp), "settings.json")

    def window(self, width=1366, settings=None):
        from hazop.app.main_window import MainWindow
        if settings is not None:
            with open(self.settings, "w", encoding="utf-8") as fh:
                json.dump(settings, fh)
        win = MainWindow(settings_path=self.settings, ask_reviewer=False)
        win.resize(width, 768)
        win.show()
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.webview.dispose)
        self.addCleanup(win.close)
        pump(win, 0.1)
        return win

    def saved(self):
        with open(self.settings, encoding="utf-8") as fh:
            return json.load(fh)

    def test_collapsed_at_1366_expanded_at_1920(self):
        small = self.window(1366)
        self.assertTrue(small.chat_collapsed())
        self.assertTrue(small.chat_column.strip.isVisible(), "접힌 채로 펴기 띠는 남는다")
        self.assertFalse(small.chat_column.body.isVisible())
        big = self.window(1920)
        self.assertFalse(big.chat_collapsed())
        self.assertTrue(big.chat_column.body.isVisible())

    def test_toggle_by_method_and_shortcut(self):
        win = self.window(1366)
        win.toggle_chat()
        pump(win, 0.05)
        self.assertFalse(win.chat_collapsed())
        self.assertGreaterEqual(win.chat_column.width(), 240)
        win.shortcuts["Ctrl+Alt+K"].activated.emit()
        pump(win, 0.05)
        self.assertTrue(win.chat_collapsed())
        win.shortcuts["Ctrl+K"].activated.emit()
        pump(win, 0.05)
        self.assertFalse(win.chat_collapsed())

    def test_user_choice_is_remembered_and_wins_over_width(self):
        win = self.window(1366)
        win.toggle_chat()  # 1366에서 사용자가 폈다
        self.assertIs(self.saved().get("chat_collapsed"), False)
        again = self.window(1366, settings=self.saved())
        self.assertFalse(again.chat_collapsed(), "저장된 선택은 창 폭 규칙보다 앞선다")
        again.toggle_chat()
        self.assertIs(self.saved().get("chat_collapsed"), True)

    def test_width_is_remembered(self):
        win = self.window(1920)
        win.set_chat_width(400)
        pump(win, 0.05)
        self.assertTrue(abs(win.chat_column.width() - 400) <= 2, win.chat_column.width())
        self.assertEqual(self.saved().get("chat_width"), win.chat_width())
        again = self.window(1920, settings=self.saved())
        self.assertTrue(abs(again.chat_column.width() - win.chat_width()) <= 2)

    def test_auto_state_is_not_saved(self):
        self.window(1366)
        self.assertNotIn("chat_collapsed", self.saved() if os.path.exists(self.settings) else {})

    def test_center_keeps_minimum_width_when_chat_open_at_1366(self):
        win = self.window(1366)
        win.toggle_chat()
        pump(win, 0.05)
        self.assertGreaterEqual(win.stack.width(), win.stack.minimumSizeHint().width())

    def test_set_chat_widget_replaces_placeholder(self):
        win = self.window(1920)
        self.assertIs(win.chat_widget(), win.chat_panel, "처음에는 채팅 창(C2)이 들어 있다")
        mine = QLabel("내용물")
        win.set_chat_widget(mine)
        self.assertIs(win.chat_widget(), mine)
        self.assertTrue(mine.isVisible())
        other = QLabel("다른 내용물")
        win.set_chat_widget(other)
        self.assertIs(win.chat_widget(), other)
        win.set_chat_widget(None)  # 비우면 안내 위젯으로 돌아간다
        self.assertIn("준비 중", win.chat_widget().text() if isinstance(win.chat_widget(), QLabel)
                      else win.chat_widget().findChild(QLabel).text())

    def test_stage_and_drawing_signals(self):
        win = self.window(1366)
        stages, drawings = [], []
        win.stage_changed.connect(lambda idx, k: stages.append((idx, k)))
        win.drawing_changed.connect(drawings.append)
        win.go(4)
        win.go(4)  # 같은 화면 다시: 신호 없음
        win.go(5)
        self.assertEqual(stages, [(4, 2), (5, 3)])
        win.drawing = None
        win._chat_view = (win.stack.currentIndex(), None)
        win.set_drawing("SNP-M-101")
        win.set_drawing("SNP-M-101")
        self.assertEqual(drawings, ["SNP-M-101"])
        self.assertEqual(win.chat_view(), {"index": 5, "stage": 3, "drawing": "SNP-M-101"})

    # ---- 검토 반려 수정(1366 폭에서 창이 넓어지는 결함, 접는 순서, 관련 항목 탭, 폭 값, 첫 창 크기)
    def test_widths_follow_the_spec(self):
        from hazop.app import main_window as mw
        self.assertEqual((mw.CHAT_DEFAULT, mw.CHAT_MIN, mw.CHAT_MAX, mw.CHAT_STRIP), (360, 320, 480, 36))
        self.assertEqual(mw.CENTER_MIN, 640)

    def test_plan_columns_collapses_right_column_before_left_list(self):
        from hazop.app.main_window import CHAT_MIN, CHAT_STRIP, EXPLORER_MIN, plan_columns
        cmin = 640
        wide = cmin + EXPLORER_MIN + CHAT_MIN
        self.assertEqual(plan_columns(wide, cmin, True, True), (True, True))
        self.assertEqual(plan_columns(wide - 1, cmin, True, True), (True, False), "오른쪽 열이 먼저 접힌다")
        self.assertEqual(plan_columns(cmin + EXPLORER_MIN + CHAT_STRIP, cmin, True, True), (True, False))
        self.assertEqual(plan_columns(cmin + EXPLORER_MIN + CHAT_STRIP - 1, cmin, True, True), (False, False), "그다음 왼쪽 목록")
        self.assertEqual(plan_columns(wide - 1, cmin, True, False), (True, False))
        self.assertEqual(plan_columns(cmin + CHAT_MIN, cmin, False, True), (False, True))

    def test_start_size_opens_chat_on_wide_screens(self):
        from hazop.app.main_window import CHAT_OPEN_FROM, start_size
        self.assertEqual(start_size(1366, 728), (1440, 860))
        self.assertEqual(start_size(CHAT_OPEN_FROM - 1, 900), (1440, 860))
        self.assertEqual(start_size(1920, 1040), (1600, 860))
        self.assertGreaterEqual(start_size(1536, 800)[0], CHAT_OPEN_FROM)
        self.assertEqual(start_size(1536, 800), (1536, 800))

    def test_all_screens_keep_1366_with_chat_and_related_open(self):
        from hazop.app.main_window import CENTER_MIN, STEPS
        for idx in range(len(STEPS)):
            for rel in (False, True):
                win = self.window(1366)
                win.go(idx)
                win.related_shown[idx] = rel
                win.open_chat()
                if rel:
                    win.open_related()
                pump(win, 0.05)
                tag = "화면 %d 관련 항목 %s [mw %d min %d stack %d colon %s ex %s col %d/%d]" % (idx, rel, win.minimumWidth(), win.minimumSizeHint().width(), win.stack.minimumSizeHint().width(), win._col_on, win.explorer_panel.isVisible(), win.chat_column.width(), win.chat_column.minimumWidth())
                self.assertEqual(win.width(), 1366, tag + " 창 폭")
                self.assertLessEqual(win.minimumSizeHint().width(), 1366, tag + " 최소 폭")
                self.assertGreaterEqual(win.stack.width(), CENTER_MIN, tag + " 가운데")

    def test_related_is_second_tab_of_the_right_column(self):
        win = self.window(1366)
        self.assertIs(win.related.parentWidget().parentWidget(), win.chat_column.body)
        win.toggle_related()
        pump(win, 0.05)
        self.assertTrue(win.related.isVisible())
        self.assertTrue(win.chat_column.tab_related.isChecked())
        win.chat_column.tab_chat.click()
        pump(win, 0.05)
        self.assertFalse(win.related.isVisible())
        self.assertFalse(win.chat_collapsed())
        self.assertTrue(win.chat_column.tab_chat.isChecked())
        win.chat_column.tab_related.click()
        pump(win, 0.05)
        self.assertTrue(win.related.isVisible())

    def test_strip_has_chat_and_related_buttons(self):
        win = self.window(1366)
        self.assertTrue(win.chat_column.strip.isVisible())
        win.chat_column.strip_related.click()
        pump(win, 0.05)
        self.assertTrue(win.related.isVisible())
        win.toggle_chat()  # 오른쪽 열 접기: 관련 항목도 함께 접힌다
        pump(win, 0.05)
        self.assertFalse(win.related.isVisible())
        win.chat_column.strip_chat.click()
        pump(win, 0.05)
        self.assertTrue(win.chat_column.body.isVisible())

    def test_shrinking_window_collapses_column_first(self):
        from hazop.app.main_window import CHAT_MIN, CHAT_STRIP, EXPLORER_MIN, RAIL_W
        win = self.window(1920)
        self.assertFalse(win.chat_collapsed())
        cmin = max(640, win.stack.minimumSizeHint().width())
        w = RAIL_W + cmin + EXPLORER_MIN + CHAT_MIN - 30
        win.resize(w, 768)
        pump(win, 0.1)
        if win.width() != w:
            self.skipTest("창 최소 폭이 더 커서 이 폭으로 줄이지 못함")
        self.assertTrue(win.explorer_panel.isVisible(), "왼쪽 목록은 남는다")
        self.assertFalse(win.chat_column.body.isVisible(), "오른쪽 열이 먼저 접힌다")
        self.assertFalse(win.chat_collapsed(), "사용자 선택은 그대로(자리가 생기면 다시 펴짐)")
        win.resize(1920, 768)
        pump(win, 0.1)
        self.assertTrue(win.chat_column.body.isVisible())

    def test_panel_in_frame_at_1366_keeps_center_and_does_not_overflow(self):
        from tests.test_chat_card import REF, TOOL_IDS, FakeEnv, answer, small_pg
        from tests.test_chat_panel import FakeSession
        win = self.window(1366)
        win.toggle_chat()
        pump(win, 0.1)
        sessions = []
        win.chat_panel._factory = lambda model, cb: sessions.append(FakeSession(model, cb)) or sessions[-1]
        env = FakeEnv()
        win.chat_panel._env_provider = lambda: (env, small_pg())
        win.chat_panel.ask("경로 알려줘")
        sessions[0].cb["on_tool_event"]("q1", "trace_path", {}, {"data": {"path_ref": REF}})
        sessions[0].cb["on_answer"]("q1", answer(general="일반 " * 40, paths=[{"label": "경로", "path_ref": REF}]), TOOL_IDS)
        pump(win, 0.2)
        self.assertEqual(win.chat_panel.scroll.horizontalScrollBar().maximum(), 0)
        self.assertGreaterEqual(win.stack.width(), win.stack.minimumSizeHint().width())
        self.assertTrue(win.chat_panel.cards())

    def test_closing_the_window_closes_the_chat_session(self):
        from tests.test_chat_panel import FakeSession
        win = self.window(1920)
        sessions = []
        win.chat_panel._factory = lambda model, cb: sessions.append(FakeSession(model, cb)) or sessions[-1]
        win.chat_panel.ask("질문")
        win.close()
        self.assertTrue(sessions[0].closed)

    def test_model_choice_is_saved_to_settings(self):
        win = self.window(1920)
        win.chat_panel.model_combo.setCurrentText("깊게")
        self.assertEqual(self.saved().get("chat_model"), "deep")
        again = self.window(1920, settings=self.saved())
        self.assertEqual(again.chat_panel.model(), "deep")


if __name__ == "__main__":
    unittest.main()
