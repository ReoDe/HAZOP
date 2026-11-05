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


class ViewerColorTest(unittest.TestCase):
    """독립 뷰어 템플릿과 앱 토큰(web_css)의 색 비교(W4, D5). Qt 없이 문자열만 본다."""
    APP = (":root { --ui: #2563eb; --card: #ffffff; --valve: #0f766e; --selected: #2563eb; --hl-dim: 0.16; }\n"
           ".selected.sym, .selected.tagbox { stroke: var(--ui) !important; fill: rgba(37,99,235,.12); }")

    def tpl(self, root="--ui: #2563eb; --card: #fff; --valve: #0f766e; --selected: #2563eb;", body="", html=""):
        data = " ".join("--%s: #000000;" % k for k in cd.VIEWER_DATA_VARS if k != "valve")
        app = self.APP.replace(":root { ", ":root { %s " % data)
        return ("<style>:root { %s %s }\n.selected.sym, .selected.tagbox { stroke: var(--selected) !important; "
                "fill: rgba(37,99,235,.12); }\n%s</style><b style=\"color:var(--ui)\"></b>%s" % (root, data, body, html)), app

    def bad(self, **kw):
        tpl, app = self.tpl(**kw)
        return cd.viewer_color_problems(tpl, app)

    def test_real_template_matches_app_tokens(self):
        from hazop.app import tokens
        from hazop.viewer import build
        with open(build.TEMPLATE, encoding="utf-8") as fh:
            tpl = fh.read()
        self.assertEqual(cd.viewer_color_problems(tpl, tokens.web_css()), [])
        root = cd.css_root_vars(tpl.split("<style>", 1)[1].split("</style>", 1)[0])
        self.assertEqual(root["valve"], tokens.COLORS["valve"])
        self.assertEqual(root["selected"], tokens.COLORS["ui"])

    def test_pre_w4_template_fails(self):
        """W4 이전 템플릿(2178ddf, a0df5ef와 같음)은 실패한다. git이 없으면 건너뛴다."""
        import subprocess
        from hazop.app import tokens
        try:
            old = subprocess.run(["git", "show", "2178ddf:hazop/viewer/template.html"],
                                 cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 capture_output=True, check=True).stdout.decode("utf-8")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git 또는 커밋 2178ddf 없음")
        bad = cd.viewer_color_problems(old, tokens.web_css())
        w5 = ("--muted:", "--instrument:", "--unclassified:", "--measurement_connection:")  # W5 명암비 조정(D7)분
        self.assertEqual(sum(b.startswith(w5) for b in bad), 4, bad)
        self.assertEqual(len([b for b in bad if not b.startswith(w5)]), 10, bad)
        for k in ("--valve:", "--selected:", "클릭 선택 채움"):
            self.assertTrue(any(b.startswith(k) for b in bad), (k, bad))

    def test_clean_names_in_html_js_pass(self):
        html = ('<script>if (p.getAttribute("fill") !== "none") {} var color = "var(--" + k + ")";'
                ' el("path", { fill: "none", style: "stroke:" + color });</script><rect fill="transparent"></rect>')
        self.assertEqual(self.bad(html=html), [])

    def test_clean_synthetic_passes(self):
        self.assertEqual(self.bad(body=".a { color: var(--card); box-shadow: 0 1px 2px rgba(0,0,0,.1); }"), [])

    def test_comments_and_whitespace_syntax_pass(self):
        body = ("/* :root { --valve: red; } #123456 rgb(1,2,3) */\n"
                ".a { color: var( --card ); border-color: var( --undefined-primary , var( --ui ) ); }\n"
                ".b { fill: rgba( 37 99 235 / .12 ); stroke: var(--ui,var(--card)); }")
        bad = self.bad(body=body)
        self.assertEqual(bad, ["var(--undefined-primary): 템플릿 :root에 정의 없음"])  # 앞 변수는 정의돼야 함
        self.assertEqual(self.bad(body=body.replace("--undefined-primary", "--card")), [])

    def test_value_mismatch_and_unknown_var(self):
        bad = self.bad(root="--ui: #2563eb; --card: #fff; --valve: #2563eb; --selected: #dc2626; --extra: #123456;")
        for k in ("--valve:", "--selected:", "--extra:"):
            self.assertTrue(any(b.startswith(k) for b in bad), (k, bad))

    def test_reproductions_fail(self):
        """재검토에서 지적한 재현 입력이 모두 실패한다."""
        cases = {
            "뒤쪽 :root 재선언": dict(body=":root { --valve: #2563eb; }"),
            "다른 규칙의 변수 재선언": dict(body="html { --valve: #2563eb; }"),
            "인라인 변수 재선언": dict(html='<i style="--valve:#2563eb"></i>'),
            "정의 없는 var(공백)": dict(body=".a { color: var( --does-not-exist ); }"),
            "정의 없는 var(대체값 안)": dict(body=".a { color: var(--card, var(--does-not-exist)); }"),
            "8자리 hex": dict(body=".a { color: #123456ff; }"),
            "4자리 hex": dict(body=".a { color: #fffa; }"),
            "허용 목록 밖 위치의 #b45309": dict(body=".a { color: #b45309; }"),
            "허용 규칙의 다른 속성": dict(body="aside .warn { color: #b45309; background: #b45309; }"),
            "인라인 style hex": dict(html='<i style="color:#ff0000"></i>'),
            "JS 문자열 hex": dict(html='<script>el.setAttribute("style", "fill:#00ff00");</script>'),
            "이름 색 red": dict(body=".a { color: red; }"),
            "인라인 이름 색": dict(html='<i style="background: white"></i>'),
            "var 대체값의 이름 색": dict(body=".a { stroke: var(--card, red); }"),
            "rgb()": dict(body=".a { color: rgb(1, 2, 3); }"),
            "rgb() 공백 없음": dict(body=".a { color: rgb(1,2,3); }"),
            "SVG 속성 이름 색": dict(html='<rect fill="red"></rect>'),
            "JS 대입 이름 색": dict(html='<script>el.style.stroke = "red";</script>'),
            "JS 객체 이름 색": dict(html='<script>el("rect", { fill: "red" });</script>'),
            "JS setAttribute 이름 색": dict(html='<script>el.setAttribute("stroke", "red");</script>'),
            "토큰 색이라도 불투명 rgb()": dict(body=".a { color: rgb(37, 99, 235); }"),
            "공백형 rgba": dict(body=".a { fill: rgba(1 2 3 / .5); }"),
            "hsl()": dict(body=".a { color: hsl(0 0% 50%); }"),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertNotEqual(self.bad(**kw), [], name)
        self.assertTrue(any(b.startswith(":root 규칙 2개") for b in self.bad(**cases["뒤쪽 :root 재선언"])))

    def test_allow_list_is_rule_bound(self):
        self.assertEqual(self.bad(body="aside .warn { color: #b45309; } #pathq .res .bad { color: #B45309; }"), [])
        self.assertEqual(self.bad(body=".chip.passed::before { content: 'x'; color: #16a34a; }"), [])
        self.assertTrue(all(len(k) == 3 for k in cd.VIEWER_COLOR_ALLOW))

    def test_selected_fill_and_missing_data_var(self):
        tpl, app = self.tpl()
        bad = cd.viewer_color_problems(tpl.replace("fill: rgba(37,99,235,.12)", "fill: rgba(220,38,38,.12)"), app)
        self.assertTrue(any(b.startswith("클릭 선택 채움") for b in bad), bad)
        self.assertIn("var(--instrument): 템플릿 :root에 정의 없음",
                      cd.viewer_color_problems(tpl.replace("--instrument: #000000;", ""), app))

    def test_selected_fill_redeclared_fails(self):
        """재작업 2회차: 선택 채움을 뒤 규칙·같은 규칙 중복·더 구체적인 선택자로 덮으면 실패한다."""
        cases = {
            "뒤 규칙 재선언": ".selected.sym, .selected.tagbox { fill: rgba(220,38,38,.12); }",
            "일부 선택자 재선언": ".selected.sym { fill: rgba(0,0,0,.2); }",
            "더 구체적인 선택자": "svg .selected.tagbox:hover { fill: rgba(0,0,0,.2); }",
            # Codex 최종 재검토(총괄 수정): 클래스 순서를 바꾼 선택자, 같은 선택자의 !important 선언 뒤 정상 값
            "클래스 순서 바꿈": ".sym.selected { fill: rgba(0,0,0,.2) !important; }",
            "추가 클래스": ".tagbox.big.selected { fill: rgba(0,0,0,.2); }",
            "같은 선택자 두 번(정상 값)": ".selected.sym, .selected.tagbox { fill: rgba(37,99,235,.12); }",
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.assertTrue(any(b.startswith("클릭 선택 채움") for b in self.bad(body=body)), name)
        tpl, app = self.tpl()
        # 앞 선언을 잘못된 값 + !important로 두고 뒤에 정상 값을 다시 선언해도 실패해야 한다
        imp = tpl.replace("fill: rgba(37,99,235,.12); }", "fill: rgba(220,38,38,.12) !important; }", 1) \
            .replace("</style>", ".selected.sym, .selected.tagbox { fill: rgba(37,99,235,.12); }</style>", 1)
        self.assertTrue(any("fill이 2번 선언됨" in b for b in cd.viewer_color_problems(imp, app)))
        # fill 없는 같은 선택자 재선언은 허용
        ok = tpl.replace("</style>", ".selected.sym, .selected.tagbox { stroke-width: 2; }</style>", 1)
        self.assertEqual(cd.viewer_color_problems(ok, app), [])
        dup = tpl.replace("fill: rgba(37,99,235,.12); }", "fill: rgba(37,99,235,.12); fill: rgba(220,38,38,.12); }", 1)
        bad = cd.viewer_color_problems(dup, app)
        self.assertIn("'.selected.sym, .selected.tagbox' fill: 한 규칙 안에서 중복 선언", bad)
        self.assertTrue(any(b.startswith("클릭 선택 채움: 템플릿 rgba(220,38,38,.12)") for b in bad), bad)  # 마지막 값 비교

    def test_var_case(self):
        """--변수 이름은 대소문자를 구분하고, var 함수명은 대소문자를 무시한다."""
        bad = self.bad(root="--ui: #2563eb; --card: #fff; --valve: #0f766e; --selected: #2563eb; --UI: #2563eb;")
        self.assertIn("--UI: 앱 토큰에 없음(템플릿 #2563eb)", bad)
        self.assertIn("var(--Card): 템플릿 :root에 정의 없음", self.bad(body=".a { color: var(--Card); }"))
        self.assertIn("var(--nope): 템플릿 :root에 정의 없음", self.bad(body=".a { color: VAR( --nope ); }"))
        self.assertIn("var(--nope): 템플릿 :root에 정의 없음", self.bad(html='<i style="color:Var(--nope)"></i>'))
        self.assertEqual(self.bad(body=".a { color: VAR(--card); }"), [])

    def test_more_color_props(self):
        """box-shadow·text-shadow·stop-color·flood-color, JS camelCase 속성의 이름 색도 잡는다."""
        cases = {
            "box-shadow": dict(body=".a { box-shadow: 0 1px 2px red; }"),
            "text-shadow": dict(body=".a { text-shadow: 0 0 1px white; }"),
            "stop-color": dict(body=".a { stop-color: red; }"),
            "flood-color": dict(body=".a { flood-color: red; }"),
            "SVG stop-color 속성": dict(html='<stop stop-color="red"/>'),
            "JS backgroundColor": dict(html='<script>el.style.backgroundColor = "red";</script>'),
            "JS borderTopColor": dict(html='<script>el.style.borderTopColor = "red";</script>'),
            "JS stopColor 객체": dict(html='<script>el("stop", { stopColor: "red" });</script>'),
            "JS boxShadow": dict(html='<script>el.style.boxShadow = "0 0 2px red";</script>'),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertNotEqual(self.bad(**kw), [], name)
        self.assertEqual(self.bad(body=".a { box-shadow: inset 0 1px 2px rgba(0,0,0,.1); }",
                                  html='<script>el.style.borderRadius = "4px"; el.style.strokeWidth = "2";</script>'), [])

    def test_html_js_line_numbers_match_source(self):
        tpl, app = self.tpl(body=".a { color: var(--card); }\n\n\n")
        tpl += '\n<p>x</p>\n<i style="color:#ff0000"></i>'
        line = tpl.split("\n").index('<i style="color:#ff0000"></i>') + 1
        bad = cd.viewer_color_problems(tpl, app)
        self.assertEqual(bad, ["색 리터럴 #ff0000 (HTML·JS, 스타일 밖 %d번째 줄): var(--토큰)으로 바꿀 것" % line])

    def test_result_json_matches_exit_code(self):
        """색 비교 실패는 결과 JSON의 rc·verdict에도 들어가고, JSON rc = 돌려준 종료 코드."""
        import contextlib
        import io
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for rc0, color_bad, want in ((0, [], 0), (0, ["x"], 1), (1, ["x"], 1), (2, ["x"], 2), (1, [], 1)):
                with self.subTest(rc0=rc0, color_bad=color_bad):
                    out = os.path.join(tmp, "r.json")
                    with contextlib.redirect_stdout(io.StringIO()):
                        rc, verdict = cd.write_result(out, {}, (1366, 689), [], rc0, "배치", color_bad)
                    with open(out, encoding="utf-8") as fh:
                        data = json.load(fh)
                    self.assertEqual((rc, data["rc"]), (want, want))
                    self.assertEqual(data["verdict"], verdict)
                    self.assertEqual(data["color_problems"], color_bad)
                    self.assertEqual("색 검사 실패" in verdict, bool(color_bad))

    def test_color_literals(self):
        self.assertEqual(cd.color_literals("0 1px 2px rgba(0, 0, 0, .1), #abc red --red solid", named=True),
                         ["#abc", "rgba(0, 0, 0, .1)", "red"])
        self.assertEqual(cd.color_literals("1px solid red", named=False), [])
        self.assertEqual(cd._translucent_rgb("rgba(37 99 235 / 12%)"), (37, 99, 235))
        self.assertIsNone(cd._translucent_rgb("rgb(37, 99, 235)"))


class AppColorTest(unittest.TestCase):
    """앱 코드 색 리터럴 0개 검사(W6, D8). 대상은 hazop/app/**/*.py(T1 파일 제외, tokens.py는 COLORS 블록만 제외)와
    hazop/viewer/build.py. 주석은 보지 않고 문자열 리터럴과 QColor·Qt 전역 색만 본다."""

    def lits(self, *lines, exclude=()):
        return cd.app_color_literals("\n".join(lines) + "\n", exclude)

    def test_files(self):
        files = cd.app_color_files()
        for f in ("hazop/viewer/build.py", "hazop/app/tokens.py", "hazop/app/widgets.py", "hazop/app/render.py",
                  "hazop/app/data.py", "hazop/app/screens/register.py", "hazop/app/screens/analysis.py",
                  "hazop/app/screens/review.py"):
            self.assertIn(f, files)
        for f in cd.APP_COLOR_T1:
            self.assertNotIn(f, files)
        self.assertEqual(set(cd.APP_COLOR_T1), {"hazop/app/screens/knowledge.py", "hazop/app/webview.py"})
        self.assertFalse(any("__pycache__" in f or not f.endswith(".py") for f in files), files)

    def test_real_code_has_none(self):
        self.assertEqual(cd.app_color_problems(), [])

    def test_allow_list_used_and_reasoned(self):
        """허용 목록은 tokens.py 반투명 rgba 3개뿐이고, 모두 사유가 있으며 실제로 쓰인다."""
        self.assertEqual({k[0] for k in cd.APP_COLOR_ALLOW}, {"hazop/app/tokens.py"})
        self.assertTrue(all(v for v in cd.APP_COLOR_ALLOW.values()))
        from hazop.app import tokens
        with open(tokens.__file__, encoding="utf-8") as fh:
            found = {lit for _n, lit in cd.app_color_literals(fh.read(), ("COLORS",))}
        self.assertEqual(found, {k[1] for k in cd.APP_COLOR_ALLOW})

    def test_tokens_colors_block_only_excluded(self):
        src = ("COLORS = {\n    'card': '#ffffff',\n    'ui': '#2563eb',\n}\n"
               "def qss():\n    return 'QFrame { background: #ffffff; }'\n")
        self.assertEqual(cd.app_color_literals(src, ("COLORS",)), [(6, "#ffffff")])
        self.assertEqual(len(cd.app_color_literals(src)), 3)
        # 같은 행에 이어 쓴 다른 대입은 제외 범위 밖(AST 노드 위치·열 기준)
        self.assertEqual(cd.app_color_literals("COLORS = {'a': '#fff'}; OTHER = '#000'\n", ("COLORS",)), [(1, "#000")])
        self.assertEqual(len(cd.app_color_problems({"hazop/app/tokens.py": "COLORS = {'a': '#fff'}; OTHER = '#000'\n"})), 1)

    def test_literals_found(self):
        got = self.lits(
            "a = \"<span style='color:#92400e'>x</span>\"",  # 1 hex 6
            "b = 'background:#fff; border: 1px solid #ABCDEF80'",  # 2 hex 3·8
            "c = 'box-shadow: 0 2px 10px rgba(0,0,0,.06)'",  # 3 rgba
            "d = 'color: HSL(0 0% 50%)'",  # 4 대문자 함수
            "e = '<circle fill=\"white\" stroke=\"transparent\"/>'",  # 5 속성 값 이름 색(transparent는 아님)
            "f = 'QListWidget { color: red; border-color: none; }'",  # 6
            "g = QColor('navy'), QColor(1, 2, 3), QColor(tokens.c('muted'))",  # 7 두 개
            "h = Qt.white if x else Qt.GlobalColor.darkRed",  # 8 두 개
            "i = ('#15803d' if ok else '#b91c1c')",  # 9 문자열 전체가 색
            "j = 'el.style.color = \"red\";'",  # 10 JS 대입(따옴표 값)
        )
        self.assertEqual(got, [(1, "#92400e"), (2, "#ABCDEF80"), (2, "#fff"), (3, "rgba(0,0,0,.06)"),
                               (4, "HSL(0 0% 50%)"), (5, "white"), (6, "red"), (7, "QColor('navy'"), (7, "QColor(1"),
                               (8, "Qt.GlobalColor.darkRed"), (8, "Qt.white"), (9, "#15803d"), (9, "#b91c1c"),
                               (10, "red")])

    def test_whole_declaration_value(self):
        """선언 값의 첫 단어만이 아니라 값 전체에서 이름 색을 찾는다."""
        self.assertEqual(self.lits("a = 'border: 1px solid red; outline: 2px dashed Navy'",
                                   "b = 'th { border-bottom: 1px solid %(line)s; color: var(--red, %(ink)s) }'"),
                         [(1, "Navy"), (1, "red")])

    def test_multiline(self):
        """여러 줄 문자열·이어 붙인 문자열·여러 줄 호출도 통째로 보고, 원본 행을 보고한다."""
        got = self.lits(
            "a = '''x {",  # 1
            "  fill: rgba(1,",  # 2
            "    2, 3, .5);",  # 3
            "  color: #abcdef; }'''",  # 4
            "b = QColor(",  # 5
            "    \"red\")",  # 6
            "c = ('box-shadow: 0 0 1px rgb(1, '",  # 7
            "     '2, 3)')",  # 8
            "d = f'<p style=\"color:{c}\">#123456</p>'",  # 9 f-string 안 hex(기본은 색)
        )
        self.assertEqual(got, [(2, "rgba(1, 2, 3, .5)"), (4, "#abcdef"), (6, "QColor('red'"),
                               (7, "rgb(1, 2, 3)"), (9, "#123456")])

    def test_not_colors(self):
        """주석, 코드의 식별자 대입, CSS 선택자, href·id 참조, 위젯 이름, 문자 참조, 자리표시자는 색이 아니다."""
        self.assertEqual(self.lits(
            "# color: red  #fff  rgb(1,2,3)",
            "x = 1  # border: 1px solid #abc",
            "color = red",
            "fill = col['physical_connection'] if seg else col.get(n.get('category'))",
            "a = \"<p style='color:%s'>x</p>\" % tokens.c(\"muted\")",
            "b = 'fill=\"%s\" stroke=\"%s\"' % (fill, col[\"card\"])",
            "c = 'QFrame#banner_err QLabel { color: %(err-ink)s; }'",
            "d = '#abc { margin: 0 }'",
            "e = '''",  # 다음 줄 맨 앞 선택자
            "#abc .x, #def > p {}'''",
            "f = \"<a href='#abc'>x</a><use href=\\\"#fed\\\"/>\"",
            "g = '&#160; #fade-in #viewport'",
            "h = 'background: transparent; color: currentcolor'",
            "i = 'JS: color = red; var red = 1'",
        ), [])

    def test_hex_default_is_color(self):
        """hex는 기본이 색이다(재작업 2회차): 1차 때 잡던 세 경우와 공백·괄호 뒤."""
        self.assertEqual(self.lits(
            "a = 'el.setAttribute(\"fill\", \"#fff\");'",
            "b = \"var c = '#fff'\"",
            "c = '<rect fill=#ffffff>'",
            "d = setAttribute('fill', '#abc')",
        ), [(1, "#fff"), (2, "#fff"), (3, "#ffffff"), (4, "#abc")])

    def test_hex_before_format_placeholder(self):
        """f-string·format 자리표시자 '{' 앞의 hex도 색이다(최종 재검토, 총괄 수정)."""
        self.assertEqual(self.lits(
            "a = f\"<span style='color:#b91c1c'>{msg}</span>\"",
            "b = f\"<circle fill='#fff' r='{r}'/>\"",
            "c = \"<span style='color:#b91c1c'>{}</span>\".format(m)",
        ), [(1, "#b91c1c"), (2, "#fff"), (3, "#b91c1c")])
        # url(…) 안의 '#'·rgb(…)는 파일 경로다(Codex 최종 재검토, 총괄 수정). url 밖 색은 그대로 잡는다
        self.assertEqual(self.lits(
            "a = 'background: url(images/#fff.svg)'",
            "b = 'background: url(rgb(1,2,3).png) #123'",
        ), [(2, "#123")])

    def test_hex_exceptions(self):
        """예외만 색이 아니다: href=·src=·url( 뒤, 객체 이름 선택자, CSS 선택자 문맥(:not( 포함)."""
        self.assertEqual(self.lits(
            "a = '#abc:not(.active) { color: %s }'",
            "b = 'p:not(#abc) > span, a#def { margin: 0 }'",
            "c = 'background: url(#abc); mask: url(\"#fed\")'",
            "d = '<img src=\"#abc\"><a href=#abc>'",
            "e = 'QFrame#bad { border: 0 }'",
        ), [])

    def test_css_comment_and_url(self):
        """CSS 주석 안과 url(파일명)은 이름 색으로 보지 않는다. 주석 밖은 잡는다."""
        self.assertEqual(self.lits(
            "a = 'p { /* color: red; #fff */ color: %s; background: url(red.png) }'",
            "b = '''/* fill: navy",
            "   still comment */ q { color: blue }'''",
        ), [(3, "blue")])

    def test_allow_list_context(self):
        """허용 목록은 (경로, 리터럴, 최상위 문장, 선택자)가 모두 맞아야 한다. 같은 rgba도 다른 함수·규칙이면 실패."""
        ok = {"hazop/app/tokens.py": ("CARD_SHADOW = '0 2px 10px rgba(0,0,0,.06)'\n"
                                      "def web_css():\n    return '.selected.sym, .selected.tagbox { fill: rgba(37,99,235,.12); }'\n")}
        self.assertEqual(cd.app_color_problems(ok), [])
        bad = {"hazop/app/tokens.py": ("def qss():\n    return 'QFrame { background: rgba(0,0,0,.06); }'\n"
                                       "def web_css():\n    return '.other { fill: rgba(37,99,235,.12); }'\n"
                                       "OTHER = 'rgba(0,0,0,.06)'\n")}
        self.assertEqual(len(cd.app_color_problems(bad)), 3)
        self.assertEqual(len(cd.app_color_problems({"hazop/app/widgets.py": ok["hazop/app/tokens.py"]})), 2)

    def test_allow_list_and_message(self):
        src = {"hazop/app/x.py": "a = '#fff'\nb = '#000'\n"}
        bad = cd.app_color_problems(src)
        self.assertEqual(len(bad), 2)
        self.assertIn("hazop/app/x.py:1 #fff", bad[0])
        allow = dict(cd.APP_COLOR_ALLOW)
        try:
            cd.APP_COLOR_ALLOW[("hazop/app/x.py", "#fff", "a", None)] = "테스트"
            self.assertEqual(len(cd.app_color_problems(src)), 1)
            self.assertEqual(len(cd.app_color_problems({"hazop/app/y.py": "a = '#fff'\n"})), 1)  # 경로에 묶임
        finally:
            cd.APP_COLOR_ALLOW.clear()
            cd.APP_COLOR_ALLOW.update(allow)

    def test_pre_w6_code_fails(self):
        """W6 이전 코드(2727e56)는 50건 실패한다(tokens.py qss·web_css 9건 포함, 허용 2건 제외). git이나 커밋이 없으면 건너뛰고,
        그 뒤 새로 생긴 파일은 빈 문자열로 본다."""
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            subprocess.run(["git", "cat-file", "-e", "2727e56^{commit}"], cwd=root, capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git 또는 커밋 2727e56 없음")
        src = {}
        for rel in cd.app_color_files():
            r = subprocess.run(["git", "show", "2727e56:" + rel], cwd=root, capture_output=True)
            src[rel] = r.stdout.decode("utf-8") if r.returncode == 0 else ""
        bad = cd.app_color_problems(src)
        self.assertEqual(len(bad), 50, bad)
        for k in ("hazop/app/widgets.py:116 #ffffff", "hazop/app/render.py:146 #9ca3af",
                  "hazop/viewer/build.py:84 rgba(0,0,0,.06)", "hazop/app/screens/review.py:808 #fca5a5",
                  "hazop/app/tokens.py:131 #dcfce7", "hazop/app/tokens.py:100 #fff",
                  "hazop/app/tokens.py:105 rgba(0,0,0,.06)"):
            self.assertTrue(any(k in b for b in bad), (k, bad))


class ContrastTest(unittest.TestCase):
    """명암비 검사(W5, D7). WCAG 2.1 상대 휘도 공식과 지정 쌍 통과."""

    def test_known_values(self):
        self.assertAlmostEqual(cd.contrast_ratio("#000000", "#ffffff"), 21.0, places=6)
        self.assertAlmostEqual(cd.contrast_ratio("#ffffff", "#000"), 21.0, places=6)  # 순서·3자리 무관
        self.assertAlmostEqual(cd.contrast_ratio("#777777", "#ffffff"), 4.48, places=2)
        self.assertAlmostEqual(cd.contrast_ratio("#123456", "#123456"), 1.0, places=6)
        self.assertAlmostEqual(cd.relative_luminance("#ffffff"), 1.0, places=6)
        self.assertAlmostEqual(cd.relative_luminance("#000000"), 0.0, places=6)
        with self.assertRaises(ValueError):
            cd.relative_luminance("#ffffff80")

    def test_threshold_and_problems(self):
        colors = {"a": "#777777", "w": "#ffffff"}
        self.assertEqual(len(cd.contrast_problems(colors, [("a", "w", cd.TEXT, "글자")])), 1)  # 4.48 < 4.5
        self.assertEqual(cd.contrast_problems(colors, [("a", "w", cd.GRAPHIC, "그래픽")]), [])
        self.assertEqual(cd.contrast_problems(colors, [("#767676", "#ffffff", cd.TEXT, "리터럴")]), [])  # 4.54

    # D7 필수 쌍과 기준(숫자로 고정: 기준을 낮추거나 쌍을 빼면 실패)
    REQUIRED_TEXT = [
        ("ink", "card"), ("ink", "bg"), ("ink", "ui-weak"), ("ink", "ai-hatch-a"), ("ink-2", "bg"), ("ink-2", "card"),
        ("ink", "kg-canvas"), ("ink-2", "kg-canvas"), ("muted", "kg-canvas"),
        ("muted", "card"), ("muted", "bg"), ("muted", "ui-weak"), ("ui", "card"), ("on-fill", "ui"),
        ("ui-ink", "ui-weak"), ("ok", "ok-bg"), ("err-ink", "err-bg"), ("warn-ink", "warn-bg"),
        ("warn-ink", "card"), ("err-ink", "card"), ("ai-ink", "ai-hatch-a"), ("on-fill", "human-line"),
        ("risk-ok-ink", "risk-ok-bg"), ("risk-cond-ink", "risk-cond-bg"), ("risk-deny-ink", "risk-deny-bg"),
        ("risk-ok-ink", "card"), ("risk-cond-line", "card"), ("risk-deny-line", "card"),
        ("on-fill", "hl-safeguard"), ("hl-safeguard", "card"), ("#b45309", "card")]
    REQUIRED_GRAPHIC = (
        [(k, b) for k in ("equipment", "valve", "instrument", "piping_element", "unclassified", "physical_connection",
                          "signal_connection", "measurement_connection", "unresolved")
         for b in ("card", "bg", "kg-canvas")]
        + [(k, b) for k in ("hl-cause", "hl-path", "hl-safeguard") for b in ("card", "bg")
           if (k, b) != ("hl-safeguard", "card")]  # hl-safeguard/card는 REQUIRED_TEXT 4.5:1이 대신함
        + [("ui", "bg"), ("tag", "card"), ("#16a34a", "bg")]
        + [("card", "equipment")])  # W7 그래프 선택 노드 흰 띠/설비 채움(고리는 ui/card·ui/bg)

    def test_required_pairs_and_thresholds(self):
        self.assertEqual((cd.TEXT, cd.GRAPHIC), (4.5, 3.0))
        have = {}
        for fg, bg, need, _u in cd.CONTRAST_PAIRS:
            self.assertNotIn((fg, bg), have, "쌍 중복")
            have[(fg, bg)] = need
        for pairs, need in ((self.REQUIRED_TEXT, 4.5), (self.REQUIRED_GRAPHIC, 3.0)):
            for pair in pairs:
                self.assertEqual(have.get(pair), need, pair)

    def test_boundary(self):
        """판정은 정확값 ≥ 기준. 계산값을 고정해 4.5·3.0은 통과, 4.4999·2.9999는 실패."""
        from unittest import mock
        colors = {"a": "#000000", "b": "#ffffff"}
        for ratio, need, ok in ((4.5, cd.TEXT, True), (4.4999, cd.TEXT, False),
                                (3.0, cd.GRAPHIC, True), (2.9999, cd.GRAPHIC, False)):
            with self.subTest(ratio=ratio, need=need), mock.patch.object(cd, "contrast_ratio", return_value=ratio):
                bad = cd.contrast_problems(colors, [("a", "b", need, "경계")])
                self.assertEqual(bad == [], ok, bad)
                if not ok:
                    self.assertIn("%.4f:1" % ratio, bad[0])

    def test_designated_pairs_pass(self):
        from hazop.app import tokens
        self.assertEqual(cd.contrast_problems(tokens.COLORS), [])

    def test_pre_w5_tokens_fail(self):
        """W5 이전 값(dbcc855)에서 미달하는 쌍과 기준."""
        from hazop.app import tokens
        old = dict(tokens.COLORS)
        old.update({"muted": "#6b7280", "instrument": "#0ea5e9", "unclassified": "#9ca3af",
                    "measurement_connection": "#d97706", "risk-cond-line": "#d97706"})
        failed = {(fg, bg, need) for fg, bg, _f, _b, r, need, _u in cd.contrast_rows(old) if r < need}
        self.assertEqual(failed, {
            ("muted", "bg", 4.5), ("muted", "ui-weak", 4.5), ("risk-cond-line", "card", 4.5),
            ("instrument", "card", 3.0), ("instrument", "bg", 3.0), ("instrument", "kg-canvas", 3.0),
            ("unclassified", "card", 3.0), ("unclassified", "bg", 3.0), ("unclassified", "kg-canvas", 3.0),
            ("measurement_connection", "bg", 3.0)})

    def test_translucent_text_color_fails(self):
        """반투명 rgba는 채움·그림자에만 허용하고, 글자색(color)에 쓰면 실패한다."""
        vt = ViewerColorTest()
        self.assertEqual(vt.bad(body=".x { fill: rgba(37,99,235,.2); box-shadow: 0 1px 2px rgba(0,0,0,.1); }"), [])
        bad = vt.bad(body=".x { color: rgba(37,99,235,.5); }")
        self.assertEqual(len(bad), 1, bad)
        self.assertTrue(bad[0].startswith("반투명 글자색"), bad)

    def test_translucent_report(self):
        """반투명 선·채움 합성 대비는 보고 전용(값 계산만). 실제 템플릿의 관계선은 3:1 미만이 있다(열린 항목)."""
        from hazop.app import tokens
        from hazop.viewer import build
        self.assertEqual(cd._over((0, 0, 0), 0.5, "#ffffff"), "#808080")
        with open(build.TEMPLATE, encoding="utf-8") as fh:
            rows = cd.translucent_rows(fh.read(), tokens.COLORS)
        gedge = [r for sel, _k, _c, _a, _m, _b, r in rows if sel == ".gedge"]
        pipe = [r for sel, _k, _c, _a, _m, _b, r in rows if sel == ".pipe-line"]
        self.assertEqual((len(gedge), len(pipe)), (3, 4))
        self.assertLess(min(gedge), 3.0)
        self.assertTrue(any(sel == ".selected.sym, .selected.tagbox" and k == "fill" for sel, k, *_ in rows))
        tpl = "<style>.gedge { stroke-opacity: 1; }</style>"
        self.assertEqual(cd.translucent_rows(tpl, tokens.COLORS), [])
        # Codex 재검토(총괄 수정): 백분율 불투명도도 해석하고, 알파는 [0,1]로 제한한다
        pct = cd.translucent_rows("<style>.gedge { stroke-opacity: 50%; }</style>", tokens.COLORS)
        self.assertEqual({a for _s, _k, _c, a, *_ in pct}, {0.5})
        self.assertEqual(cd._over((0, 0, 0), -0.1, "#ffffff"), "#ffffff")
        self.assertEqual(cd._over((0, 0, 0), 1.5, "#ffffff"), "#000000")
        neg = cd.translucent_rows("<style>.gedge { stroke-opacity: -0.1; }</style>", tokens.COLORS)
        self.assertTrue(all(a == 0.0 for _s, _k, _c, a, *_ in neg))


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
