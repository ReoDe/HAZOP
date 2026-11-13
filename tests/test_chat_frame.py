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
        first = win.chat_widget()
        self.assertIn("준비 중", first.text() if isinstance(first, QLabel) else first.findChild(QLabel).text())
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


if __name__ == "__main__":
    unittest.main()
