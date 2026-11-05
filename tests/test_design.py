"""1366×768 배치 검사 함수 테스트 (scripts/check_design.py, docs/2026-11-05-design-system D1·W2).
실행: python -m unittest discover -s tests -t .

offscreen 플랫폼. 작업·저장 루트와 설정 파일은 임시 폴더(scripts/check_design.TempRoots). 네트워크 사용 없음.
offscreen 폭은 글꼴 대체로 과대하므로 여기서는 수치 기준(≤1366)을 판정하지 않고 측정·탐색 로직만 확인한다.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from scripts import check_design as cd  # noqa: E402


def setUpModule():
    from hazop.app import make_application
    make_application(["test_design"])


def tearDownModule():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from hazop.app.webview import HazopWebView
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        if isinstance(w, HazopWebView):
            w.dispose()
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()


class WidestWidgetsTest(unittest.TestCase):
    """합성 위젯 트리: 숨김·쌓인 페이지·스크롤 내용 처리."""

    def test_contribution_rules(self):
        from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout,
                                       QWidget)
        root = QWidget()
        self.addCleanup(root.deleteLater)
        lay = QVBoxLayout(root)
        row = QHBoxLayout()
        lay.addLayout(row)
        row.addWidget(QLabel("짧음"))
        fixed = QPushButton("고정")
        fixed.setMinimumWidth(400)
        row.addWidget(fixed)
        hidden = QLabel("숨김")
        hidden.setMinimumWidth(900)
        row.addWidget(hidden)
        hidden.hide()
        stack = QStackedWidget()
        lay.addWidget(stack)
        stack.addWidget(QLabel("현재 페이지"))
        page2 = QLabel("숨은 페이지")
        page2.setObjectName("page2")
        page2.setMinimumWidth(600)
        stack.addWidget(page2)
        scroll = QScrollArea()
        inner = QLabel("스크롤 안")
        inner.setMinimumWidth(1200)
        scroll.setWidget(inner)
        lay.addWidget(scroll)

        rows = cd.widest_widgets(root, top=3)
        self.assertEqual([(r["objectName"], r["width"]) for r in rows[:2]], [("page2", 600), ("", 400)])
        self.assertEqual(rows[1]["class"], "QPushButton")
        self.assertEqual(rows[1]["text"], "고정")
        texts = {r["text"] for r in cd.widest_widgets(root, top=50)}
        self.assertNotIn("숨김", texts)       # 명시적으로 숨긴 위젯은 최소 폭에 들어가지 않음
        self.assertNotIn("스크롤 안", texts)   # 스크롤 영역 내용도 들어가지 않음
        self.assertTrue(cd.contributes(page2, root))
        self.assertFalse(cd.contributes(hidden, root))
        self.assertFalse(cd.contributes(inner, root))
        self.assertGreaterEqual(root.minimumSizeHint().width(), 600)

    def test_text_head_truncated(self):
        from PySide6.QtWidgets import QLabel
        w = QLabel("가" * 100)
        self.addCleanup(w.deleteLater)
        t = cd.widget_text(w)
        self.assertEqual(len(t), cd.TEXT_HEAD + 1)
        self.assertTrue(t.endswith("…"))


class JudgeTest(unittest.TestCase):
    def test_over_limit_and_baseline(self):
        rows = [{"state": "B", "screen": "④", "win_min_w": 1282, "win_min_h": 673},
                {"state": "B", "screen": "⑤", "win_min_w": 1367, "win_min_h": 600}]
        self.assertEqual(cd.over_limit(rows), [("B", "⑤", 1367, 600)])
        self.assertEqual([b[:2] for b in cd.over_limit(rows, dpr=1.25)], [("B", "④"), ("B", "⑤")])
        base = [{"state": "B", "screen": "④", "win_min_w": 1282, "win_min_h": 680},
                {"state": "B", "screen": "⑤", "win_min_w": 1300, "win_min_h": 600}]
        self.assertEqual(cd.baseline_increases(rows, base), [("B", "⑤", "win_min_w", 1300, 1367)])


class WindowMeasureTest(unittest.TestCase):
    """실제 주 창(샘플 분석 실행 열림)에서 가장 넓은 위젯이 W1에서 찾은 원인과 같은지."""

    def test_sample_run_causes(self):
        with cd.TempRoots() as roots:
            run_dir = roots.install_sample_run()
            win = cd.new_window(roots)
            try:
                win.open_run(run_dir)
                cd.pump(win, 0.3)
                cd.visit_all(win)
                rows = {r["screen"]: r for r in cd.measure_all(win, "B", top=3)}
            finally:
                cd.close_window(win)
        self.assertEqual([r["screen"] for r in rows.values()], ["①", "②", "③", "④", "⑤"])
        for r in rows.values():
            self.assertGreater(r["win_min_w"], 0)
            self.assertGreater(r["win_min_h"], 0)
            self.assertGreaterEqual(r["win_min_w"], r["screen_min_w"])
        # ④: 도구줄 결과 검증 칩(hazop/app/screens/analysis.py show_ctx의 chip_valid)
        top4 = rows["④"]["screen_widest"][0]
        self.assertEqual((top4["class"], top4["objectName"]), ("Chip", "chip"))
        self.assertTrue(top4["text"].startswith("결과 검증 통과 — 형식"), top4)
        # ⑤: 줄바꿈 없는 실행 라벨과 진행 칩이 상위 2개
        top5 = {w["text"][:3] for w in rows["⑤"]["screen_widest"][:2]}
        self.assertEqual(top5, {"실행 ", "미검토"})
        # 쌓인 화면이라 창 최소 폭은 어느 화면에서나 같고 ④·⑤ 중 큰 쪽 이상
        widths = {r["win_min_w"] for r in rows.values()}
        self.assertEqual(len(widths), 1)
        self.assertGreaterEqual(widths.pop(), max(rows["④"]["screen_min_w"], rows["⑤"]["screen_min_w"]))


if __name__ == "__main__":
    unittest.main()
