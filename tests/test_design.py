"""지원 화면 배치 검사 함수 테스트 (scripts/check_design.py, docs/2026-11-05-design-system D1·D3·D4안, W2·W3).
실행: python -m unittest discover -s tests -t .

offscreen 플랫폼. 작업·저장 루트와 설정 파일은 임시 폴더(scripts/check_design.TempRoots). 네트워크 사용 없음.
offscreen 폭은 글꼴 대체로 과대하므로 여기서는 수치 기준(작업 영역)을 판정하지 않고 측정·탐색 로직과
줄임표 라벨 구조(최소 폭 축소·툴팁 = 전체 문구)만 확인한다. 수치 판정은 --platform windows(D4안).
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


def ink_pixels(img):
    """그림에서 왼쪽 위 모서리 색과 다른 화소 수(빈 그림이면 0)."""
    bg = img.pixel(0, 0)
    return sum(img.pixel(x, y) != bg for x in range(img.width()) for y in range(img.height()))


class ElidedLabelTest(unittest.TestCase):
    """widgets.ElidedLabel·Chip(elide=…): 최소 폭은 줄고, text()·접근성 이름은 전체 문구, 줄였을 때만 툴팁(W3)."""

    FULL = "실행 analysis-20261104T000000Z-fixture (읽기 전용)"

    def make(self, cls=None, font=None, **kw):
        """화면에 그리지 않고 띄운 라벨(보이는 위젯이라야 resize 때 resizeEvent가 바로 온다)."""
        from PySide6.QtCore import Qt
        from hazop.app.widgets import ElidedLabel
        w = (cls or ElidedLabel)(self.FULL, **kw)
        if font is not None:
            w.setFont(font)
        w.setAttribute(Qt.WA_DontShowOnScreen, True)
        w.show()
        self.addCleanup(w.deleteLater)
        self.addCleanup(w.close)
        return w

    def real_font(self):
        """offscreen은 글자를 모두 같은 네모로 그려 문구 차이가 그림에 안 나온다. 이 테스트 동안만 맑은 고딕 파일을
        등록해 쓴다(없으면 건너뜀). 측정 판정에는 쓰지 않는다(D4).

        부작용: 등록을 해제해도 같은 프로세스의 offscreen 기본 글꼴 해석이 맑은 고딕으로 남을 수 있다(글꼴을 지정하지
        않은 QLabel 폭이 돌아오지 않음, T6 W3 재검토). 스타일시트로 글꼴을 정한 앱 위젯은 영향이 없다. 순서에 민감한
        측정 테스트를 이 클래스 뒤에 둘 때는 하위 프로세스로 분리한다."""
        from PySide6.QtGui import QFont, QFontDatabase
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "malgun.ttf")
        fid = QFontDatabase.addApplicationFont(path) if os.path.isfile(path) else -1
        if fid < 0:
            self.skipTest("맑은 고딕 글꼴 파일 없음: %s" % path)
        self.addCleanup(QFontDatabase.removeApplicationFont, fid)
        return QFont(QFontDatabase.applicationFontFamilies(fid)[0], 10)

    def test_elide_keeps_full_text(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAccessible
        from hazop.app.widgets import Chip, plain_label
        plain, lab = self.make(), self.make(elide=Qt.ElideRight, min_chars=8)
        self.assertEqual(plain.minimumSizeHint().width(), plain.sizeHint().width())   # elide 없음 = 기존 QLabel
        self.assertLess(lab.minimumSizeHint().width(), lab.sizeHint().width() // 2)
        lab.resize(lab.sizeHint())
        self.assertFalse(lab.is_elided())
        self.assertEqual(lab.toolTip(), "")                                         # 다 보이면 툴팁 없음
        lab.resize(lab.minimumSizeHint().width(), lab.sizeHint().height())
        self.assertTrue(lab.is_elided())
        self.assertEqual((lab.text(), lab.toolTip()), (self.FULL, self.FULL))       # 줄이면 툴팁에 전체 문구
        acc = QAccessible.queryAccessibleInterface(lab)
        self.assertEqual(acc.text(QAccessible.Name), self.FULL)                     # 접근성 이름도 전체 문구
        chip = Chip(elide=Qt.ElideMiddle)
        self.addCleanup(chip.deleteLater)
        self.assertEqual(chip.objectName(), "chip")
        p = plain_label(self.FULL, "muted", elide=Qt.ElideMiddle, min_chars=4)
        self.addCleanup(p.deleteLater)
        self.assertFalse(p.wordWrap())

    def test_render(self):
        """줄여 그린 그림: 빈 그림 아님, 줄이지 않은 QLabel·뒤 줄임과 다름, 넓히면 원래 그림, 글꼴을 키우면 다시 줄임."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        font = self.real_font()
        right, middle, clip = (self.make(elide=Qt.ElideRight, font=font), self.make(elide=Qt.ElideMiddle, font=font),
                               self.make(QLabel, font=font))
        full_w, h = right.sizeHint().width(), right.sizeHint().height()
        right.resize(full_w, h)
        before = right.grab().toImage()
        self.assertGreater(ink_pixels(before), 0)
        narrow = full_w // 2
        for w in (right, middle, clip):
            w.resize(narrow, h)
        img_r, img_m, img_c = (w.grab().toImage() for w in (right, middle, clip))
        self.assertGreater(ink_pixels(img_r), 0)
        self.assertGreater(ink_pixels(img_m), 0)
        self.assertNotEqual(img_r, img_c)        # 줄임표로 그림(잘리기만 한 QLabel과 다름)
        self.assertNotEqual(img_r, img_m)        # 가운데 줄임은 뒤 줄임과 다름
        self.assertEqual(middle.toolTip(), self.FULL)
        right.resize(full_w, h)                   # 줄였다가 다시 넓히기
        self.assertEqual(right.grab().toImage(), before)
        self.assertEqual(right.toolTip(), "")
        f = right.font()
        f.setPointSizeF(f.pointSizeF() * 1.5)
        right.setFont(f)                          # 글꼴 변경: 같은 폭에서 줄임으로 바뀌고 툴팁도 따라감
        self.assertTrue(right.is_elided())
        self.assertEqual(right.toolTip(), self.FULL)
        img_f = right.grab().toImage()
        self.assertGreater(ink_pixels(img_f), 0)
        self.assertNotEqual(img_f, before)


class JudgeTest(unittest.TestCase):
    def test_work_area(self):
        self.assertEqual(cd.work_area(1.0), (1366, 768 - cd.TASKBAR_H - cd.TITLEBAR_H))
        self.assertEqual(cd.work_area(1.25), (1536, 864 - cd.TASKBAR_H - cd.TITLEBAR_H))
        self.assertIsNone(cd.work_area(1.5))

    def test_over_limit_and_baseline(self):
        rows = [{"state": "B", "screen": "④", "win_min_w": 1282, "win_min_h": 673},
                {"state": "B", "screen": "⑤", "win_min_w": 1367, "win_min_h": 600},
                {"state": "B", "screen": "①", "win_min_w": 900, "win_min_h": 700}]
        self.assertEqual(cd.over_limit(rows, cd.work_area(1.0)), [("B", "⑤", 1367, 600), ("B", "①", 900, 700)])
        self.assertEqual(cd.over_limit(rows, cd.work_area(1.25)), [])
        base = [{"state": "B", "screen": "④", "win_min_w": 1282, "win_min_h": 680},
                {"state": "B", "screen": "⑤", "win_min_w": 1300, "win_min_h": 600}]
        self.assertEqual(cd.baseline_increases(rows, base), [("B", "⑤", "win_min_w", 1300, 1367)])

    def test_elide_problems(self):
        rows = [{"state": "B", "screen": "⑤", "elided": [{"objectName": "chip", "tooltip_ok": True},
                                                          {"objectName": "muted", "tooltip_ok": False}]},
                {"state": "A", "screen": "①", "elided": []}]
        self.assertEqual(cd.elide_problems(rows), [("B", "⑤", "muted")])
        rows[1]["at_area"] = {"elided": [{"objectName": "chip", "tooltip_ok": False}]}
        self.assertEqual(cd.elide_problems(rows), [("B", "⑤", "muted"), ("A", "①", "chip")])

    def test_form_problems(self):
        rows = [{"state": "B", "screen": "⑤", "form": {"need": 380, "have": 606},
                 "at_area": {"form": {"need": 700, "have": 606}}},
                {"state": "B", "screen": "④", "form": None, "at_area": {"form": None}}]
        self.assertEqual(cd.form_problems(rows), [("B", "⑤", "작업 영역", 700, 606)])


def bar_min_width(label):
    """label이 든 도구줄(가로 레이아웃)의 최소 폭."""
    from PySide6.QtWidgets import QHBoxLayout
    scr = label.parentWidget()
    for i in range(scr.layout().count()):
        lay = scr.layout().itemAt(i).layout()
        if isinstance(lay, QHBoxLayout) and lay.indexOf(label) >= 0:
            lay.invalidate()
            return lay.minimumSize().width()
    raise AssertionError("도구줄 없음: %s" % label)


class WindowMeasureTest(unittest.TestCase):
    """실제 주 창: W1 원인(④ 결과 검증 칩, ⑤ 실행 라벨·진행 칩)이 더는 최소 폭을 정하지 않는지(W3)."""

    def test_sample_run_causes(self):
        with cd.TempRoots() as roots:
            run_dir = roots.install_sample_run()
            win = cd.new_window(roots)
            try:
                win.open_run(run_dir)
                cd.pump(win, 0.3)
                cd.visit_all(win)
                rows = {r["screen"]: r for r in cd.measure_all(win, "B", top=3)}
                s4, s5 = win.screens[2], win.screens[3]
                # ⑤: 줄임표를 끄면 도구줄 최소 폭이 (전체 폭 − 줄인 최소 폭)만큼 늘어난다
                for lab in (s5.run_label, s5.chip_progress):
                    full, small, with_elide = lab.sizeHint().width(), lab.minimumSizeHint().width(), bar_min_width(lab)
                    self.assertLess(small, full, lab.text())
                    orig, lab.elide = lab.elide, None
                    lab.updateGeometry()
                    self.assertEqual(bar_min_width(lab) - with_elide, full - small, lab.text())
                    lab.elide = orig
                    lab.updateGeometry()
                # ④: 결과 검증 칩은 줄이지 않고, 단서 라벨은 줄바꿈으로 최소 폭을 줄인다
                win.go(2)
                cd.pump(win, 0.1)
                self.assertIsNone(s4.chip_valid.elide)
                self.assertEqual(s4.chip_valid.text(), "결과 검증 통과")
                note = s4.valid_note
                self.assertIn("보류 항목이 없다는 뜻이 아님", note.text())
                with_wrap = bar_min_width(note)
                note.setWordWrap(False)
                self.assertGreater(bar_min_width(note), with_wrap)
                note.setWordWrap(True)
                # 창을 최소 폭으로 줄여도 단서는 잘리지 않고 다 그려진다
                win.resize(win.minimumSizeHint().width(), cd.work_area(1.0)[1])
                cd.pump(win, 0.2)
                self.assertTrue(note.isVisibleTo(win))
                self.assertGreater(note.width(), 0)
                self.assertGreaterEqual(note.height(), note.heightForWidth(note.width()))
                self.assertLessEqual(note.mapTo(s4, note.rect().bottomRight()).x(), s4.width())
                self.assertGreater(ink_pixels(note.grab().toImage()), 0)
            finally:
                cd.close_window(win)
        self.assertEqual([r["screen"] for r in rows.values()], ["①", "②", "③", "④", "⑤"])
        for r in rows.values():
            self.assertGreater(r["win_min_w"], 0)
            self.assertGreater(r["win_min_h"], 0)
            self.assertGreaterEqual(r["win_min_w"], r["screen_min_w"])
            self.assertEqual(r["at_area"]["area"], list(cd.work_area(1.0)))
        self.assertEqual({e["objectName"] for e in rows["⑤"]["elided"]}, {"muted", "chip"})
        self.assertTrue(all(e["tooltip_ok"] for e in rows["⑤"]["elided"] + rows["⑤"]["at_area"]["elided"]))
        self.assertEqual(cd.form_problems(list(rows.values())), [])
        # 쌓인 화면이라 창 최소 폭은 어느 화면에서나 같고 ④·⑤ 중 큰 쪽 이상
        widths = {r["win_min_w"] for r in rows.values()}
        self.assertEqual(len(widths), 1)
        self.assertGreaterEqual(widths.pop(), max(rows["④"]["screen_min_w"], rows["⑤"]["screen_min_w"]))

    def test_knowledge_run(self):
        """지식그래프 실행(T1 W7): ⑤ 지식 버전 칩도 줄임표 라벨, 관련 지식을 펼쳐도 폼이 가로로 잘리지 않음."""
        with cd.TempRoots() as roots:
            runs = cd.install_kg_runs(roots)
            win = cd.new_window(roots)
            try:
                win.open_run(runs["kg"])
                cd.pump(win, 0.3)
                cd.visit_all(win, cd.REVIEW_KG_CANDIDATE)
                win.go(3)
                cd.expand_knowledge(win)
                forms = list(win.screens[3].sforms.values())
                self.assertTrue(forms and all(f.knowledge.view.isVisibleTo(f) for f in forms))
                row = cd.measure(win, "⑤")
                row["state"] = "D"
            finally:
                cd.close_window(win)
        chips = [e for e in row["elided"] if e["text"].startswith("지식 ")]
        self.assertEqual(len(chips), 1, row["elided"])
        self.assertEqual(cd.elide_problems([row]), [])
        self.assertEqual(cd.form_problems([row]), [])


if __name__ == "__main__":
    unittest.main()
