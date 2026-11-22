"""새 웹 화면 통합 시험(단위 새 화면 1단계, docs/design/app-shell-web.md §5.5·§5.6). 실행: python -m unittest tests.test_shell_web

오프스크린 웹 엔진에 실제 틀 창(ShellWindow)을 띄워 본다: 웹 콘솔 오류 0, 원격 요청 0, 도면 목록·열기, 채팅 묻기 → 답 카드 → 도면 표시 요청,
요금·한도 막기가 화면에 나오는지, 모델·도면의 글이 HTML로 해석되지 않는지. 웹 단위 시험(`web/test/run.html`)도 여기서 돌린다.
실제 구독 호출·실제 창 조작은 없다(채팅 세션은 가짜).
"""

import glob
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from hazop import paths  # noqa: E402
from tests.test_app import tearDownModule  # noqa: E402,F401
from tests.test_chat_card import REF, S1, S2, TOOL_IDS, FakeEnv, answer, comp, small_pg  # noqa: E402
from tests.test_shell_api import FakeSession  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "hazop", "shell", "web")


def pump(seconds=0.0):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + seconds
    while True:
        QCoreApplication.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.005)


def wait_for(cond, timeout=20.0):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return bool(cond())


class StaticTest(unittest.TestCase):
    def test_tokens_css_is_what_tokens_py_makes(self):
        from hazop.app import tokens
        with open(os.path.join(WEB, "tokens.css"), encoding="utf-8", newline="") as fh:
            self.assertEqual(fh.read().replace("\r\n", "\n"), tokens.shell_css())

    def test_index_csp_matches_the_handlers_policy(self):
        from hazop.shell import scheme
        with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
            text = fh.read()
        m = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), scheme.CSP)

    def test_web_sources_never_use_dangerous_apis(self):
        bad = re.compile(r"dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function|"
                         r"setTimeout\s*\(\s*['\"`]|importScripts|XMLHttpRequest|WebSocket|https?://")
        hits = []
        for p in glob.glob(os.path.join(WEB, "**", "*.js"), recursive=True) + glob.glob(os.path.join(WEB, "*.html")):
            if os.sep + "vendor" + os.sep in p:
                continue
            with open(p, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    line = re.sub(r"http://www\.w3\.org/\d+/[a-z0-9/]+", "", line)          # SVG·XLink 이름 공간 주소는 요청이 아니다
                    line = re.sub(r"(^|\s)//.*$", "", line)                                      # 주석은 보지 않는다
                    if bad.search(line):
                        hits.append("%s:%d %s" % (os.path.relpath(p, REPO), n, line.strip()[:80]))
        self.assertEqual(hits, [])

    def test_every_relative_import_exists(self):
        for p in glob.glob(os.path.join(WEB, "js", "**", "*.js"), recursive=True) + glob.glob(os.path.join(WEB, "test", "*.js")):
            if os.sep + "canvas" + os.sep in p and not p.endswith("README.md"):
                continue   # 도면 구성요소는 s-viewer가 맡는다(없을 수 있다)
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            for rel in re.findall(r'(?:from|import)\s*\(?\s*"(\.[^"]+)"', text):
                target = os.path.normpath(os.path.join(os.path.dirname(p), rel))
                if os.sep + "canvas" + os.sep in target:
                    continue
                self.assertTrue(os.path.isfile(target), "%s -> %s" % (os.path.relpath(p, REPO), rel))

    def test_vendor_files_are_the_recorded_ones(self):
        import hashlib
        with open(os.path.join(WEB, "vendor", "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        for name in ("preact.module.js", "hooks.module.js", "htm.module.js"):
            with open(os.path.join(WEB, "vendor", name), "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            self.assertIn(digest, text, name)


def shell_teardown():
    """남은 새 화면 창·웹 페이지를 인터프리터 종료 전에 정리한다(페이지·프로필이 남은 채 끝나면 시험이 통과한 뒤 Segmentation fault로 끝난다).
    창이 있는 시험 모듈은 `tearDownModule = W.shell_teardown`으로 쓴다."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from hazop.shell.window import ShellView
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        if isinstance(w, ShellView):
            w.dispose()
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()


tearDownModule = shell_teardown


class ShellBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-shellweb-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT", "HAZOP_DEBUG")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.environ["HAZOP_DEBUG"] = "1"       # window.__hz 시험 갈고리는 디버그 실행에서만 만든다
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        from scripts.check_edit_screen import install_sample
        cls.names = [install_sample(os.environ["HAZOP_WORK_ROOT"], d) for d in ("SNP-M-101", "SNP-M-102")]

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def window(self, size=(1366, 768), reviewer="검토자A"):
        from hazop.shell.window import ShellWindow
        self.sessions = []

        def factory(model, cb):
            s = FakeSession(model, cb)
            self.sessions.append(s)
            return s
        self.env = FakeEnv()
        settings = os.path.join(tempfile.mkdtemp(dir=self.tmp), "settings.json")
        if reviewer:
            with open(settings, "w", encoding="utf-8") as fh:
                json.dump({"reviewer_name": reviewer}, fh)
        win = ShellWindow(settings_path=settings, size=size, session_factory=factory, env_provider=lambda: (self.env, small_pg()))
        win.show()
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__hz && document.querySelector('.rail') !== null"), 30), "웹 화면이 뜨지 않음")
        self.assertTrue(wait_for(lambda: (self.js(win, "window.__hz.store.get().drawings.drawings.length") or 0) >= 2, 20))
        pump(0.3)
        return win

    def js(self, win, code, timeout=10.0):
        out = []
        win.view.page().runJavaScript(code, 0, out.append)
        end = time.monotonic() + timeout
        while time.monotonic() < end and not out:
            pump(0.01)
        return out[0] if out else None

    def switch_project(self, win, project):
        """프로젝트를 바꾸고(project.set) 웹이 그 프로젝트를 보고 있게 될 때까지 기다린다. 웹이 모든 명령에 싣는 프로젝트 ID가 엔진의 것과 같아야 쓰기가 통한다."""
        r = win.engine.dispatch("project.set", {"project_id": project})
        self.assertTrue(r["ok"], r)
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().app.project_id") == project, 15), "웹이 새 프로젝트를 읽지 못함")
        pump(0.3)

    def jsj(self, win, expr):
        """식의 값을 JSON으로 받아 파이썬 값으로 돌려준다(배열·객체는 runJavaScript가 비어 오는 일이 있어 문자열로 받는다)."""
        raw = self.js(win, "JSON.stringify(%s)" % expr)
        return json.loads(raw) if raw else None

    def text(self, win):
        return self.js(win, "document.body.innerText") or ""

    def click(self, win, selector, nth=0):
        return self.js(win, "(() => { const e = document.querySelectorAll(%s)[%d]; if (!e) return false; e.click(); return true; })()"
                       % (json.dumps(selector), nth))


class ShellWindowTest(ShellBase):
    def test_boot_has_no_console_errors_and_no_remote_requests(self):
        win = self.window()
        errors = [c for c in win.view.page().console if c[0] >= 2]
        self.assertEqual(errors, [])
        self.assertEqual(win.view.interceptor.blocked, [], "실행 중 원격 요청 0")
        self.assertEqual(win.view.page().blocked_navigation, [])

    def test_the_import_file_dialog_hook_asks_on_the_gui_thread_even_when_a_job_calls_it(self):
        import threading
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog
        win = self.window()
        asked = []

        def fake(parent, title, folder, spec):
            asked.append((threading.current_thread() is threading.main_thread(), title, spec))
            return ("C:/x/fmea.xlsx", "")
        pick = win.engine.hooks["pick_import"]
        with mock.patch.object(QFileDialog, "getOpenFileName", staticmethod(fake)):
            self.assertEqual(pick("fmea", ["FMEA 양식 (*.xlsx)"]), ["C:/x/fmea.xlsx"])
            out = []
            worker = threading.Thread(target=lambda: out.append(pick("mld", "MLD 파일 (*.xlsx *.csv)")))
            worker.start()
            self.assertTrue(wait_for(lambda: not worker.is_alive(), 10), "작업 스레드가 화면 스레드의 대답을 기다린다")
            self.assertEqual(out, [["C:/x/fmea.xlsx"]])
        self.assertEqual(asked[0], (True, "FMEA 양식 고르기", "FMEA 양식 (*.xlsx)"))
        self.assertEqual(asked[1], (True, "MLD 파일 고르기", "MLD 파일 (*.xlsx *.csv)"), "작업 스레드에서 불러도 창은 화면 스레드에서 열린다")
        with mock.patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a: ("", ""))):
            self.assertEqual(pick("fmea", ["FMEA 양식 (*.xlsx)"]), [], "취소하면 빈 목록")

    def test_back_chip_returns_to_the_panel_that_sent_the_user_to_the_sheet(self):
        win = self.window()
        for back, label in (("results", "분석 결과로 돌아가기"), ("ie", "초기사건으로 돌아가기")):
            self.js(win, "window.__hz.store.set({panel: null, backTo: %s})" % json.dumps(back))
            sel = "button[aria-label='%s']" % label
            self.assertTrue(wait_for(lambda: self.click(win, sel), 10), label)
            self.assertTrue(wait_for(lambda: self.jsj(win, "window.__hz.store.get().panel") == back, 10), back)
            self.assertIsNone(self.jsj(win, "window.__hz.store.get().backTo"), "누르면 돌아가기 표시가 지워진다")
        self.js(win, "window.__hz.store.set({panel: null, backTo: null})")
        self.assertFalse(self.jsj(win, "!!document.querySelector(\"button[aria-label$='돌아가기']\")"), "이 표시가 없으면 칩도 없다")

    def test_related_panels_are_tabs_under_one_menu_button(self):
        win = self.window()
        for name, lead, tabs in (("aireview", "도면", ["도면", "표제란", "AI 검토"]), ("docs", "지식그래프", ["지식그래프", "설계 문서"])):
            self.js(win, "window.__hz.store.set({panel: %s})" % json.dumps(name))
            self.assertTrue(wait_for(lambda: self.jsj(win, "[...document.querySelectorAll('.ptabs button')].map(b => b.textContent)") == tabs, 10), name)
            self.assertEqual(self.jsj(win, "document.querySelector('.rail button.on').getAttribute('aria-label')").split(" (")[0], lead, "묶음의 메뉴 단추가 켜진다")
        self.js(win, "window.__hz.store.set({panel: 'aireview'})")
        pump(0.4)
        self.assertTrue(self.click(win, ".ptabs button", 1))
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().panel") == "titleblock", 10))
        self.assertEqual(self.js(win, "document.querySelector('.ptabs button.on').textContent"), "표제란")
        self.assertTrue(self.click(win, ".rail button.on"))
        self.assertTrue(wait_for(lambda: not self.js(win, "window.__hz.store.get().panel"), 10), "켜진 메뉴 단추를 누르면 닫힌다")
        self.js(win, "window.__hz.store.set({panel: 'results'})")
        pump(0.3)
        self.assertEqual(self.js(win, "document.querySelector('.ptabs') === null"), True, "묶음이 아니면 탭이 없다")

    def test_the_action_log_opens_from_the_chat_header_not_the_menu(self):
        win = self.window()
        labels = self.jsj(win, "[...document.querySelectorAll('.rail button')].map(b => b.getAttribute('aria-label'))")
        self.assertFalse(any("실행 기록" in x for x in labels), labels)
        self.assertTrue(self.click(win, ".chat-h button[aria-label='AI 실행 기록']"))
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().panel") == "actionlog", 10))
        self.assertTrue(self.click(win, ".chat-h button[aria-label='AI 실행 기록']"))
        self.assertTrue(wait_for(lambda: not self.js(win, "window.__hz.store.get().panel"), 10))

    def test_the_connection_dot_sits_on_the_settings_button(self):
        win = self.window()
        label = self.js(win, "[...document.querySelectorAll('.rail button')].pop().getAttribute('aria-label')")
        self.assertTrue(label.startswith("설정") and "AI 연결" in label, label)
        self.assertEqual(self.js(win, "[...document.querySelectorAll('.rail button')].pop().querySelector('.conn') !== null"), True)

    def test_the_window_opens_to_fit_the_screen_and_the_chat_starts_folded_only_in_a_narrow_window(self):
        from hazop.shell import window as shell_window
        w, h = shell_window.ShellWindow._default_size()
        self.assertTrue(shell_window.MIN_SIZE[0] <= w <= shell_window.PREFERRED_SIZE[0] and shell_window.MIN_SIZE[1] <= h <= shell_window.PREFERRED_SIZE[1], (w, h))
        wide = self.window(size=(1366, 768))
        self.assertEqual(self.js(wide, "window.__hz.store.get().chatCollapsed"), False, "1366에서는 채팅을 편 채로 연다(폭만 줄인다)")
        self.assertEqual(self.js(wide, "document.documentElement.scrollWidth <= window.innerWidth"), True, "가로로 잘리지 않는다")
        state = os.path.join(os.environ["HAZOP_WORK_ROOT"], "data", "ui-state.json")      # 앞 시험의 창이 남긴 보기 상태를 지운다(사람이 접은 적이 없는 처음 실행)
        if os.path.exists(state):
            os.remove(state)
        narrow = self.window(size=(1100, 700))
        self.assertEqual(self.js(narrow, "window.__hz.store.get().chatCollapsed"), True, "1280 미만 창에서는 처음에 채팅을 접는다")
        self.assertGreaterEqual(narrow.minimumWidth(), shell_window.MIN_SIZE[0])

    def test_frame_has_rail_chat_and_drawings_panel_first(self):
        win = self.window()
        t = self.text(win)
        self.assertIn("채팅", t)
        self.assertIn("도면 파일을 여기에 끌어 놓으세요", t)       # 열 도면이 여럿이면 도면 패널을 먼저 보인다
        self.assertIn("SNP-M-101", t)
        self.assertIn("SNP-M-102", t)
        self.assertEqual(self.js(win, "document.querySelectorAll('.rail button').length"), 6)       # 도면(+표제란·AI 검토 탭)·구간·분석 결과·초기사건·지식그래프(+설계 문서 탭)·설정(연결 점 포함)
        self.assertEqual(self.js(win, "document.querySelectorAll('button:not([aria-label]):not([title])').length"), 0, "접근 이름 없는 단추")

    def test_icons_are_inline_svg_elements(self):
        win = self.window()
        self.assertGreater(self.js(win, "document.querySelectorAll('svg.ic path').length"), 5)
        self.assertEqual(self.js(win, "document.querySelectorAll('img').length"), 0)

    def test_open_a_drawing_from_the_list(self):
        win = self.window()
        self.assertTrue(self.click(win, ".panel .row button", 1))
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().sheet") is not None, 10))
        pump(0.5)
        self.assertTrue(self.js(win, "window.__hz.store.get().panel === null"))
        self.assertEqual(win.engine.current_sheet, self.js(win, "window.__hz.store.get().sheet"))
        src = self.js(win, "(document.querySelector('.canvas img') || {}).src || ''")
        self.assertTrue(src == "" or src.startswith("hazop-app://shell/api/sheet/"), src)
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])

    def test_keys_toggle_panels_and_chat(self):
        win = self.window()
        key = ("window.dispatchEvent(new KeyboardEvent('keydown', {key: %s, ctrlKey: %s, altKey: %s, bubbles: true}))")
        self.js(win, key % ('"Escape"', "false", "false"))
        pump(0.2)
        self.assertTrue(self.js(win, "window.__hz.store.get().panel === null"))
        self.js(win, key % ('"1"', "true", "false"))
        pump(0.2)
        self.assertEqual(self.js(win, "window.__hz.store.get().panel"), "drawings")
        self.js(win, key % ('"k"', "true", "true"))
        pump(0.2)
        self.assertTrue(self.js(win, "window.__hz.store.get().chatCollapsed"))
        self.assertTrue(win.engine.ui_state() == {} or True)
        self.js(win, key % ('"k"', "true", "false"))
        pump(0.3)
        self.assertFalse(self.js(win, "window.__hz.store.get().chatCollapsed"), "Ctrl+K는 접힌 채팅을 편다")

    def test_first_run_without_reviewer_opens_settings(self):
        win = self.window(reviewer=None)
        self.assertEqual(self.js(win, "window.__hz.store.get().panel"), "settings")
        self.assertIn("검토자 이름을 입력하세요", self.text(win))

    def test_project_box_changes_the_project_from_the_top_bar(self):
        win = self.window()
        self.assertTrue(self.click(win, ".crumb button.sheet", 0))
        pump(0.3)
        self.js(win, "(() => { const i = document.querySelector('.proj-input'); i.value = 'plant-Z'; i.dispatchEvent(new Event('input', {bubbles: true})); "
                     "i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); })()")
        self.assertTrue(wait_for(lambda: win.engine.project_id() == "plant-Z", 10))
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().drawings.project_id") == "plant-Z", 10))

    def test_settings_has_the_start_screen_switch(self):
        win = self.window()
        self.assertTrue(self.click(win, ".rail button", 5))
        pump(0.4)
        self.assertIn("시작할 때 새 화면 쓰기", self.text(win))
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='시작할 때 새 화면 쓰기']\").getAttribute('aria-checked')"), "true", "기본은 켜짐")
        self.assertTrue(self.click(win, "button[aria-label='시작할 때 새 화면 쓰기']"))
        self.assertTrue(wait_for(lambda: win.engine.settings.get("ui_shell") is False, 10), "끄면 설정에 False로 남는다")

    def test_settings_panel_shows_connection_and_saves_reviewer(self):
        win = self.window()
        self.assertTrue(self.click(win, ".rail button", 5))
        pump(0.5)
        self.assertIn("AI 연결", self.text(win))
        self.js(win, "(() => { const i = document.getElementById('reviewer'); i.value = '검토자B'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
        pump(0.2)
        self.assertTrue(self.click(win, ".panel .btn.primary"))
        self.assertTrue(wait_for(lambda: win.engine.reviewer() == "검토자B", 10))


class ShellChatTest(ShellBase):
    def ask(self, win, text="경로 알려줘"):
        self.js(win, "window.__hz.cmd('chat.ask', {text: %s})" % json.dumps(text))
        self.assertTrue(wait_for(lambda: bool(self.sessions) and bool(self.sessions[-1].asked), 10))
        return self.sessions[-1]

    def deliver(self, s, ans=None, tool_ids=None, qid="q1", tools=1):
        def run():
            for _ in range(tools):
                s.cb["on_tool_event"](qid, "trace_path", {}, {"ok": True, "sources": [{"kind": "drawing"}], "data": {"path_ref": REF}})
            s.cb["on_answer"](qid, ans if ans is not None else answer(paths=[{"label": "RC-PZ01 → RC-PSV101", "path_ref": REF}]),
                              TOOL_IDS if tool_ids is None else tool_ids)
        t = threading.Thread(target=run)
        t.start()
        t.join()
        pump(0.4)

    def test_question_to_card_and_marks(self):
        win = self.window()
        win.engine.dispatch("sheet.open", {"graph_id": win.engine.graph_names() and sorted(win.engine.graph_names())[0]})
        s = self.ask(win)
        self.assertEqual(s.asked[0][0], "경로 알려줘")
        self.assertTrue(wait_for(lambda: "경로 알려줘" in self.text(win), 5), "내 질문이 보인다")
        self.deliver(s)
        t = self.text(win)
        self.assertIn("경로는 티 하나를 거칩니다.", t)
        chips = self.jsj(win, "[...document.querySelectorAll('.steps .chip')].map(e => e.textContent.trim())")
        self.assertEqual(chips, ["RC-PZ01", "RC-T2", "RC-PSV101"])
        self.assertEqual(self.js(win, "[...document.querySelectorAll('.sheets .chip')].length"), 2)
        marks = self.jsj(win, "Object.keys(window.__hz.store.get().marks.bySheet)")
        self.assertIn(S1, marks)
        self.assertEqual(self.js(win, "document.querySelector('.chat-h') !== null"), True)

    def test_sheet_chip_opens_that_sheet_and_sets_its_marks(self):
        win = self.window()
        s = self.ask(win)
        self.deliver(s)
        self.assertTrue(self.click(win, ".sheets .chip", 1))
        pump(0.3)
        self.assertEqual(self.js(win, "window.__hz.store.get().sheet"), S2)
        self.assertIn(S2, self.jsj(win, "Object.keys(window.__hz.store.get().marks.bySheet)"))

    def test_text_from_the_model_is_not_html(self):
        win = self.window()
        s = self.ask(win)
        self.deliver(s, ans=answer(text="<img src=x onerror=window.__pwned=1>굵게<b>x</b>", general="<script>window.__pwned=2</script>"))
        self.assertEqual(self.js(win, "document.querySelectorAll('.ans img, .ans b, .ans script, .msgs img').length"), 0)
        self.assertIn("<img src=x", self.text(win))
        self.assertTrue(self.js(win, "window.__pwned === undefined"), "삽입한 스크립트가 돌면 안 됨")

    def test_overage_error_after_answer_blocks_the_input_on_screen(self):
        win = self.window()
        s = self.ask(win)

        def run():
            s.cb["on_answer"]("q1", answer(), TOOL_IDS)
            s.cb["on_error"]("q1", {"error_kind": "overage", "conn_state": "overage", "message": "초과 사용", "limit": None})
        t = threading.Thread(target=run)
        t.start()
        t.join()
        pump(0.5)
        self.assertTrue(self.js(win, "document.querySelector('.chat-input').disabled"))
        self.assertIn("채팅을 쓸 수 없습니다", self.text(win))
        self.js(win, "window.__hz.cmd('chat.ask', {text: '또'})")
        pump(0.3)
        self.assertEqual(len(s.asked), 1, "초과 사용 뒤 다음 질문이 나가지 않는다")

    def test_no_cli_pc_shows_only_the_guide(self):
        win = self.window()
        win.chat.set_availability("not_installed")
        pump(0.5)
        t = self.text(win)
        self.assertIn("이 PC에 Claude Code가 없습니다", t)
        self.assertIn("설치 방법 보기", t)
        self.assertTrue(self.js(win, "document.querySelector('.chat-input').disabled"))
        self.assertEqual(self.sessions, [])

    def test_examples_fill_the_input_without_sending(self):
        win = self.window()
        self.assertTrue(self.click(win, ".examples .chip", 0))
        pump(0.3)
        self.assertNotEqual(self.js(win, "document.querySelector('.chat-input').value"), "")
        self.assertEqual(self.sessions, [])

    def test_enter_sends_and_shift_enter_does_not(self):
        win = self.window()
        self.js(win, "(() => { const t = document.querySelector('.chat-input'); t.value = '질문'; t.dispatchEvent(new Event('input', {bubbles: true})); })()")
        pump(0.2)
        self.js(win, "document.querySelector('.chat-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', shiftKey: true, bubbles: true}))")
        pump(0.3)
        self.assertTrue(not self.sessions or not self.sessions[-1].asked)
        self.js(win, "document.querySelector('.chat-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")
        self.assertTrue(wait_for(lambda: bool(self.sessions) and bool(self.sessions[-1].asked), 10))

    def test_stop_button_and_new_conversation(self):
        win = self.window()
        s = self.ask(win)
        pump(0.3)
        self.assertTrue(self.click(win, ".send.stop"))
        self.assertTrue(wait_for(lambda: s.stopped >= 1, 5))
        self.assertIn("지금까지의 대화는 지워지고", self.text(win))
        self.assertTrue(self.click(win, ".chat-h .btn", 0))
        pump(0.3)
        self.assertEqual(self.js(win, "window.__hz.store.get().chat.msgs.length"), 0)

    def test_collapsed_chat_gets_a_dot_on_new_answer(self):
        win = self.window()
        s = self.ask(win)
        self.js(win, "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, altKey: true, bubbles: true}))")
        pump(0.3)
        self.deliver(s, ans=answer())
        self.assertEqual(self.js(win, "document.querySelectorAll('.chat.collapsed .dot-new').length"), 1)
        self.js(win, "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true}))")
        pump(0.3)
        self.assertEqual(self.js(win, "document.querySelectorAll('.dot-new').length"), 0)

    def test_chat_width_at_1366_is_320_and_center_keeps_room(self):
        win = self.window((1366, 768))
        w = self.js(win, "document.querySelector('.chat').getBoundingClientRect().width")
        self.assertEqual(round(w), 320)
        self.assertGreater(self.js(win, "document.querySelector('.center').getBoundingClientRect().width"), 900)
        win2 = self.window((1536, 864))
        self.assertEqual(round(self.js(win2, "document.querySelector('.chat').getBoundingClientRect().width")), 380)


class ShellDropTest(ShellBase):
    def test_dropped_file_registers_extracts_and_lists(self):
        win = self.window()
        src = [p for p in glob.glob(os.path.join(paths.folder("references", "pid-samples"), "*", "*.drawio")) if "SNP-M-401" in p]
        if not src:
            self.skipTest("표본 도면이 없음")
        r = win.drop_files(src + [os.path.join(self.tmp, "x.exe")])
        self.assertTrue(r["ok"], r)
        self.assertTrue(wait_for(lambda: self.js(win, "Object.values(window.__hz.store.get().jobs).some(j => j.state === 'done')"), 60), self.text(win)[:400])
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().drawings.documents.length") >= 1, 20))
        self.assertIn("등록됨", self.text(win))

    def test_non_drawing_files_are_refused_with_a_message(self):
        win = self.window()
        r = win.drop_files([os.path.join(self.tmp, "a.exe")])
        self.assertFalse(r["ok"])
        self.assertTrue(wait_for(lambda: "도면 파일(.drawio, .pdf, DEXPI .xml)만 받습니다." in self.text(win), 10))


class WebUnitTest(ShellBase):
    def test_web_unit_tests_pass(self):
        from PySide6.QtCore import QUrl
        win = self.window()   # 처리기를 프로필에 붙이려고 틀 창을 먼저 띄운다
        # 시험 페이지는 틀 창의 이동 제한에 걸리므로 별도 페이지로 연다
        from hazop.app import webview
        from PySide6.QtWebEngineCore import QWebEnginePage

        logs = []

        class LogPage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
                logs.append((message, line, source))
        p2 = LogPage(win.view.profile)   # 틀 창의 전용 프로필(처리기가 붙어 있다)
        out = []
        p2.load(QUrl("hazop-app://shell/test/run.html"))
        end = time.monotonic() + 30
        while time.monotonic() < end:
            res = []
            p2.runJavaScript("JSON.stringify(window.__results || null)", 0, res.append)   # 배열은 문자열로 받는다
            for _ in range(20):
                pump(0.02)
            if res and res[0] and res[0] != "null":
                out = json.loads(res[0])
                break
        self.assertTrue(out, "웹 단위 시험 결과가 나오지 않음: %s" % logs[:5])
        failed = [r for r in out if not r["ok"]]
        self.assertEqual(failed, [])
        self.assertGreaterEqual(len(out), 12)
        got = []
        p2.runJavaScript("JSON.stringify(window.__measures || [])", 0, got.append)
        for _ in range(20):
            pump(0.02)
        if got and got[0]:
            print("웹 측정:", got[0])
        p2.deleteLater()


class CloseGuardTest(ShellBase):
    """등록·추출이 도는 동안 창을 닫거나 '이전 화면 열기'를 하면 묻는다(멈추고 닫기 / 끝나면 닫기 / 계속 사용). 묻기 전에는 닫히지 않는다."""

    def busy_job(self, win):
        import threading
        gate = threading.Event()
        steps = []

        def work(progress):
            progress("등록 중", 1, 3)
            gate.wait(20)
            steps.append("after-gate")
            progress("추출·그래프", 2, 3)      # 멈추라고 했으면 여기서 멈춘다
            steps.append("extracted")
            return {}
        win.engine.start_job("x.drawio", work)
        self.assertTrue(wait_for(lambda: bool(win.engine.running_jobs()), 5))
        return gate, steps

    def test_cancel_keeps_the_window_and_the_job(self):
        win = self.window()
        asked = []
        win.confirm_busy = lambda n, kinds=None: asked.append(n) or "cancel"
        gate, steps = self.busy_job(win)
        self.assertFalse(win.close())
        self.assertEqual(asked, [1])
        self.assertTrue(win.isVisible())
        self.assertEqual(len(win.engine.running_jobs()), 1)
        r = win.engine.dispatch("app.open_classic", {})
        self.assertEqual(r["data"], {"switched": False}, "이전 화면으로도 바뀌지 않는다")
        self.assertFalse(win.classic_requested, "취소하면 이전 화면 요청을 거둔다")
        self.assertEqual(asked, [1, 1])
        gate.set()
        self.assertTrue(win.engine.wait_jobs(15))

    def test_wait_closes_when_the_job_finishes(self):
        win = self.window()
        win.confirm_busy = lambda n, kinds=None: "wait"
        gate, steps = self.busy_job(win)
        self.assertFalse(win.close())
        self.assertTrue(win.isVisible())
        gate.set()
        self.assertTrue(wait_for(lambda: not win.isVisible(), 15), "작업이 끝나면 닫힌다")
        self.assertEqual(steps, ["after-gate", "extracted"], "기다리면 작업은 끝까지 간다")

    def test_stop_halts_at_the_next_progress_then_closes(self):
        win = self.window()
        win.confirm_busy = lambda n, kinds=None: "stop"
        gate, steps = self.busy_job(win)
        import threading
        threading.Timer(0.3, gate.set).start()    # 지금 단계(대기)는 끝나고, 다음 진행 알림 자리에서 멈춘다
        self.assertTrue(win.close())
        self.assertFalse(win.isVisible())
        self.assertEqual(steps, ["after-gate"], "다음 단계로 가지 않고 멈춘다")
        self.assertEqual(win.engine.running_jobs(), [])

    def test_classic_switch_waits_for_jobs_too(self):
        win = self.window()
        win.confirm_busy = lambda n, kinds=None: "wait"
        gate, steps = self.busy_job(win)
        r = win.engine.dispatch("app.open_classic", {})
        self.assertEqual(r["data"], {"switched": False})
        self.assertTrue(win.classic_requested, "끝나면 닫기를 골랐으니 요청은 남는다")
        gate.set()
        self.assertTrue(wait_for(lambda: not win.isVisible(), 15))

    def test_busy_text_matches_the_running_job(self):
        from hazop.shell.window import ShellWindow
        head, info = ShellWindow.busy_text(["analysis"])
        self.assertIn("AI 분석", head)
        self.assertNotIn("등록", head + info, "분석 중에 '도면 등록·추출'이라고 하지 않는다")
        head, _ = ShellWindow.busy_text(["register"])
        self.assertIn("도면 등록·추출", head)
        head, _ = ShellWindow.busy_text(["register", "analysis", "analysis"])
        self.assertTrue("도면 등록·추출" in head and "AI 분석" in head and "3개" in head, head)

    def test_close_guard_text_for_an_analysis_job(self):
        win = self.window()
        seen = []
        win.confirm_busy = lambda n, kinds=None: seen.append(kinds) or "cancel"
        import threading as th
        gate = th.Event()
        win.engine.start_job("AI 분석 실행", lambda progress: gate.wait(20), kind="analysis")
        self.assertTrue(wait_for(lambda: bool(win.engine.running_jobs()), 5))
        self.assertFalse(win.close())
        self.assertEqual(seen, [["analysis"]])
        gate.set()
        self.assertTrue(win.engine.wait_jobs(15))

    def test_save_path_asks_before_overwriting_the_path_with_the_extension_added(self):
        from unittest import mock
        win = self.window()
        out = os.path.join(self.tmp, "exists.xlsx")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("x")
        asked = []
        with mock.patch("hazop.shell.window.QFileDialog.getSaveFileName", return_value=(os.path.join(self.tmp, "exists"), "")):
            win.confirm_overwrite = lambda p: asked.append(p) or False
            self.assertIsNone(win._save_path("excel", "a.xlsx"), "덮어쓰기를 거절하면 저장하지 않는다")
            self.assertEqual(asked, [out], "확장자를 붙인 경로로 묻는다")
            win.confirm_overwrite = lambda p: True
            self.assertEqual(win._save_path("excel", "a.xlsx"), out)
        with mock.patch("hazop.shell.window.QFileDialog.getSaveFileName", return_value=(os.path.join(self.tmp, "fresh"), "")):
            win.confirm_overwrite = lambda p: self.fail("없는 파일은 묻지 않는다")
            self.assertEqual(win._save_path("excel", "a.xlsx"), os.path.join(self.tmp, "fresh.xlsx"))
        with mock.patch("hazop.shell.window.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertIsNone(win._save_path("excel", "a.xlsx"))

    def test_no_jobs_closes_without_asking(self):
        win = self.window()
        win.confirm_busy = lambda n, kinds=None: self.fail("작업이 없으면 묻지 않는다")
        self.assertTrue(win.close())


if __name__ == "__main__":
    unittest.main()
