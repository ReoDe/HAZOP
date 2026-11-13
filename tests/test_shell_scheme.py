"""새 웹 화면의 주소 체계 `hazop-app://`(단위 새 화면 1단계, docs/design/app-shell-web.md §5.1·§5.5). 실행: python -m unittest tests.test_shell_scheme

주소 처리기의 순수 부분(`Router`)을 웹 없이 시험한다: 정해진 폴더의 파일만 돌려주고(절대 경로·`..`·역슬래시·드라이브·이중 인코딩·
끝점/공백·대체 스트림·예약 이름·링크 탈출·단축 이름 작업 루트), 읽기 API는 GET만, 오류 글에 내부 경로를 싣지 않는다.
마지막 시험은 오프스크린 웹 엔진에서 맞춤 주소 체계로 ES 모듈(`import` 사슬)이 읽히는지 본다(규격 §9 첫 시험).
"""

import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from hazop.shell import scheme  # noqa: E402


class FakeApi:
    def __init__(self):
        self.calls = []

    def read(self, parts, query):
        self.calls.append((list(parts), dict(query)))
        if parts[:1] == ["boom"]:
            raise RuntimeError("내부 오류 C:\\secret\\path")
        if parts[:1] == ["bytes"]:
            return scheme.Response(200, "image/png", b"\x89PNG")
        if parts[:1] == ["missing"]:
            return None
        return scheme.Response(200, "application/json", json.dumps({"parts": parts}).encode("utf-8"))


class RouterBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-scheme-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.web = os.path.join(self.tmp, "web")
        os.makedirs(os.path.join(self.web, "js", "ui"))
        os.makedirs(os.path.join(self.web, "vendor"))
        for rel, text in {"index.html": "<!doctype html><title>x</title>", "app.css": "a{}", "js/main.js": "export const a = 1;",
                          "js/ui/button.js": "export default 1;", "vendor/preact.module.js": "export {};",
                          "logo.svg": "<svg/>", "data.json": "{}", "note.txt": "x", "run.exe": "MZ"}.items():
            with open(os.path.join(self.web, *rel.split("/")), "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(self.tmp, "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("비밀")
        self.icons = os.path.join(self.tmp, "icons")
        os.makedirs(self.icons)
        with open(os.path.join(self.icons, "send.svg"), "w", encoding="utf-8") as fh:
            fh.write("<svg>send</svg>")
        self.api = FakeApi()
        self.router = scheme.Router(self.web, api=self.api, icons_dir=self.icons, icon_names=("send",))

    def get(self, url, method="GET"):
        return self.router.resolve(url, method)


class StaticFileTest(RouterBase):
    def test_index_at_root_and_explicit(self):
        for url in ("hazop-app://shell/", "hazop-app://shell", "hazop-app://shell/index.html"):
            r = self.get(url)
            self.assertEqual((r.status, r.mime), (200, "text/html"), url)
            self.assertIn(b"<title>x</title>", r.body)

    def test_mime_table(self):
        for rel, mime in (("app.css", "text/css"), ("js/main.js", "text/javascript"), ("logo.svg", "image/svg+xml"),
                          ("data.json", "application/json")):
            r = self.get("hazop-app://shell/" + rel)
            self.assertEqual((r.status, r.mime), (200, mime), rel)

    def test_unknown_extension_is_refused(self):
        for rel in ("note.txt", "run.exe"):
            self.assertEqual(self.get("hazop-app://shell/" + rel).status, 415, rel)

    def test_nested_and_vendor(self):
        self.assertEqual(self.get("hazop-app://shell/js/ui/button.js").status, 200)
        self.assertEqual(self.get("hazop-app://shell/vendor/preact.module.js").status, 200)

    def test_query_and_fragment_are_ignored(self):
        self.assertEqual(self.get("hazop-app://shell/js/main.js?v=3").status, 200)
        self.assertEqual(self.get("hazop-app://shell/js/main.js#x").status, 200)

    def test_missing_file_and_directory(self):
        self.assertEqual(self.get("hazop-app://shell/nope.js").status, 404)
        self.assertEqual(self.get("hazop-app://shell/js/").status, 404)
        self.assertEqual(self.get("hazop-app://shell/js").status, 404)

    def test_html_gets_a_content_security_policy(self):
        r = self.get("hazop-app://shell/index.html")
        csp = r.headers.get("Content-Security-Policy", "")
        for part in ("default-src 'none'", "script-src 'self'", "connect-src 'self'", "font-src 'none'", "base-uri 'none'", "form-action 'none'"):
            self.assertIn(part, csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn("Content-Security-Policy", self.get("hazop-app://shell/app.css").headers)

    def test_not_cached_forever(self):
        self.assertIn("no-cache", self.get("hazop-app://shell/js/main.js").headers.get("Cache-Control", ""))


class PathAttackTest(RouterBase):
    ATTACKS = (
        "hazop-app://shell/../secret.txt", "hazop-app://shell/js/../../secret.txt", "hazop-app://shell/%2e%2e/secret.txt",
        "hazop-app://shell/%2E%2E%2Fsecret.txt", "hazop-app://shell/..%2fsecret.txt", "hazop-app://shell/js/..%5c..%5csecret.txt",
        "hazop-app://shell/js\\main.js", "hazop-app://shell/js%5Cmain.js", "hazop-app://shell/%252e%252e/secret.txt",
        "hazop-app://shell//index.html", "hazop-app://shell/js//main.js", "hazop-app://shell/C:/Windows/win.ini",
        "hazop-app://shell/C%3A/Windows/win.ini", "hazop-app://shell/%00index.html", "hazop-app://shell/index.html%00.js",
        "hazop-app://shell/index.html.", "hazop-app://shell/index.html%20", "hazop-app://shell/index.html::$DATA",
        "hazop-app://shell/js/main.js:stream", "hazop-app://shell/con", "hazop-app://shell/NUL.js", "hazop-app://shell/js/aux.js",
        "hazop-app://shell/./index.html", "hazop-app://shell/js/./main.js", "hazop-app://shell/COM1",
        "hazop-app://shell/%ff%fe.js", "hazop-app://shell/" + "a/" * 200 + "main.js",
    )

    def test_attacks_never_return_a_file(self):
        for url in self.ATTACKS:
            r = self.get(url)
            self.assertIn(r.status, (400, 403, 404, 415), url)
            self.assertNotIn("비밀".encode("utf-8"), r.body, url)
            self.assertNotEqual(r.body, b"export const a = 1;", url)

    def test_error_text_has_no_internal_path(self):
        for url in self.ATTACKS[:6]:
            r = self.get(url)
            self.assertNotIn(self.tmp.encode("utf-8"), r.body, url)

    def test_symlink_that_leaves_the_root_is_refused(self):
        link = os.path.join(self.web, "js", "escape.js")
        try:
            os.symlink(os.path.join(self.tmp, "secret.txt"), link)
        except (OSError, NotImplementedError):
            self.skipTest("이 계정은 심볼릭 링크를 만들 수 없음")
        r = self.get("hazop-app://shell/js/escape.js")
        self.assertIn(r.status, (403, 404, 415))
        self.assertNotIn("비밀".encode("utf-8"), r.body)

    def test_directory_junction_that_leaves_the_root_is_refused(self):
        if os.name != "nt":
            self.skipTest("Windows 전용")
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "x.js"), "w", encoding="utf-8") as fh:
            fh.write("export const stolen = 1;")
        junction = os.path.join(self.web, "js", "link")
        import subprocess
        res = subprocess.run(["cmd", "/c", "mklink", "/J", junction, outside], capture_output=True)
        if res.returncode != 0:
            self.skipTest("정션을 만들 수 없음")
        r = self.get("hazop-app://shell/js/link/x.js")
        self.assertIn(r.status, (403, 404))
        self.assertNotIn(b"stolen", r.body)

    def test_short_8_3_work_root_still_serves(self):
        if os.name != "nt":
            self.skipTest("Windows 전용")
        long_root = os.path.join(self.tmp, "A long folder name for 8dot3")
        os.makedirs(os.path.join(long_root, "js"))
        with open(os.path.join(long_root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html/>")
        buf = ctypes.create_unicode_buffer(260)
        if not ctypes.windll.kernel32.GetShortPathNameW(long_root, buf, 260) or buf.value == long_root:
            self.skipTest("이 볼륨은 단축 이름을 만들지 않음")
        r = scheme.Router(buf.value).resolve("hazop-app://shell/index.html")
        self.assertEqual(r.status, 200)
        self.assertEqual(scheme.Router(buf.value).resolve("hazop-app://shell/../x.js").status in (400, 403, 404), True)

    def test_upper_and_lower_case_do_not_open_other_files(self):
        self.assertEqual(self.get("hazop-app://shell/INDEX.HTML").status in (200, 404), True)
        self.assertNotIn("비밀".encode("utf-8"), self.get("hazop-app://shell/..%2FSECRET.TXT").body)


class RoutingTest(RouterBase):
    def test_only_get_and_head(self):
        for m in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(self.get("hazop-app://shell/index.html", m).status, 405, m)
            self.assertEqual(self.get("hazop-app://shell/api/x", m).status, 405, m)
        self.assertEqual(self.get("hazop-app://shell/index.html", "HEAD").status, 200)

    def test_other_scheme_or_host(self):
        self.assertEqual(self.get("https://shell/index.html").status, 400)
        self.assertEqual(self.get("file:///C:/Windows/win.ini").status, 400)
        self.assertEqual(self.get("hazop-app://evil/index.html").status, 404)
        self.assertEqual(self.get("hazop-app://shell:8080/index.html").status in (400, 404), True)
        self.assertEqual(self.get("hazop-app://user@shell/index.html").status in (400, 404), True)

    def test_garbage_url(self):
        for url in ("", "hazop-app:", "hazop-app://", "::::", "hazop-app://shell/\x00", None, 5):
            self.assertIn(self.get(url).status, (400, 404), repr(url))

    def test_api_route_passes_parts_and_query(self):
        r = self.get("hazop-app://shell/api/sheet/graph-A?rev=7&x=1")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(r.body)["parts"], ["sheet", "graph-A"])
        self.assertEqual(self.api.calls[-1], (["sheet", "graph-A"], {"rev": "7", "x": "1"}))

    def test_api_gets_the_same_path_checks(self):
        for url in ("hazop-app://shell/api/../x", "hazop-app://shell/api/sheet/%2e%2e/x", "hazop-app://shell/api/a\\b", "hazop-app://shell/api//x"):
            self.assertIn(self.get(url).status, (400, 403, 404), url)
        self.assertEqual(self.api.calls, [])

    def test_same_origin_alias_reaches_api_and_icons(self):
        r = self.get("hazop-app://shell/api/sheet/graph-A?rev=1")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(r.body)["parts"], ["sheet", "graph-A"])
        self.assertEqual(self.get("hazop-app://shell/icons/send.svg").status, 200)
        self.assertEqual(self.get("hazop-app://shell/api/%2e%2e/x").status in (400, 403, 404), True)
        self.assertEqual(self.get("hazop-app://shell/api/x", "POST").status, 405)
        self.assertEqual(self.get("hazop-app://shell/apiary.js").status, 404)

    def test_api_binary_and_missing_and_error(self):
        self.assertEqual(self.get("hazop-app://shell/api/bytes").mime, "image/png")
        self.assertEqual(self.get("hazop-app://shell/api/missing").status, 404)
        r = self.get("hazop-app://shell/api/boom")
        self.assertEqual(r.status, 500)
        self.assertNotIn(b"secret", r.body)
        self.assertNotIn(b"RuntimeError", r.body)

    def test_one_host_only_and_test_folder_gate(self):
        for url in ("hazop-app://api/state", "hazop-app://icons/send.svg"):
            self.assertEqual(self.get(url).status, 404, "api·icons 호스트는 없다(한 호스트)")
        os.makedirs(os.path.join(self.web, "test"))
        with open(os.path.join(self.web, "test", "run.html"), "w", encoding="utf-8") as fh:
            fh.write("<html/>")
        self.assertEqual(self.get("hazop-app://shell/test/run.html").status, 404, "시험 모드가 아니면 web/test/는 내주지 않는다")
        on = scheme.Router(self.web, allow_test=True)
        self.assertEqual(on.resolve("hazop-app://shell/test/run.html").status, 200)

    def test_no_api_means_404(self):
        self.assertEqual(scheme.Router(self.web).resolve("hazop-app://shell/api/x").status, 404)

    def test_icons_host_serves_only_listed_names(self):
        r = self.get("hazop-app://shell/icons/send.svg")
        self.assertEqual((r.status, r.mime), (200, "image/svg+xml"))
        self.assertEqual(self.get("hazop-app://shell/icons/other.svg").status, 404)
        self.assertEqual(self.get("hazop-app://shell/icons/..%2Fsecret.svg").status in (400, 403, 404), True)
        self.assertEqual(self.get("hazop-app://shell/icons/send.png").status in (404, 415), True)


class SchemeFlagsTest(unittest.TestCase):
    def test_flags_follow_the_spec(self):
        """Syntax.Host와 FetchApiAllowed가 있다(화면·읽기 API는 같은 호스트의 같은 출처). LocalAccessAllowed는 규격과 달리 남겨 둔다(scheme.py 주석: 빼면 틀 창이 안 그려짐)."""
        import inspect
        src = inspect.getsource(scheme.register)
        self.assertIn("Syntax.Host", src)
        self.assertIn("FetchApiAllowed", src)


class RealEngineTest(unittest.TestCase):
    """실제 웹 엔진 요청으로 본다: ES 모듈 사슬, 원격 차단, file 읽기 둘째 겹(가로채기), meta CSP, 읽기 API가 화면 스레드를 막지 않는지,
    정션·단축 이름(8.3) 작업 루트. 새 화면이 쓰는 ShellView(전용 프로필·가로채기·처리기)를 그대로 쓴다."""

    @classmethod
    def setUpClass(cls):
        scheme.register()   # QApplication보다 먼저
        from hazop.app import make_application
        cls.qapp = make_application(["t"])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-realsec-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.web = os.path.join(self.tmp, "web")
        os.makedirs(os.path.join(self.web, "js"))

    def write(self, rel, text, root=None):
        p = os.path.join(root or self.web, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    @staticmethod
    def until(cond, seconds):
        from PySide6.QtCore import QCoreApplication
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QCoreApplication.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return bool(cond())

    def view(self, router):
        from hazop.shell.window import SHELL_URL, ShellBridge, ShellView

        class Dead:
            def dispatch(self, *a):
                return {"ok": False}
        v = ShellView(ShellBridge(Dead()), router)
        self.addCleanup(v.dispose)
        loaded = []
        v.page().loadFinished.connect(loaded.append)
        from PySide6.QtCore import QUrl
        v.load(QUrl(SHELL_URL))
        self.assertTrue(self.until(lambda: bool(loaded), 20), "페이지가 열리지 않음")
        return v

    def result(self, v, expr, seconds=10):
        """expr가 undefined/null이 아닐 때까지 기다려 JSON 값으로 돌려준다(없으면 None)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            out = []
            v.page().runJavaScript("JSON.stringify(%s) || 'undefined'" % expr, 0, out.append)
            self.until(lambda: bool(out), 3)
            if out and out[0] not in (None, "", "undefined", "null"):
                return json.loads(out[0])
            self.until(lambda: False, 0.1)
        return None

    def test_es_module_chain_runs_and_remote_is_blocked(self):
        self.write("index.html", '<!doctype html><meta charset="utf-8"><script type="module" src="./js/main.js"></script>')
        self.write("js/main.js", 'import {b} from "./dep.js"; import {c} from "../vendor/v.js"; window.__ok = b + c;'
                   ' fetch("https://example.com/x").catch(()=>{ window.__fetchBlocked = true; });')
        self.write("js/dep.js", 'export const b = "B";')
        self.write("vendor/v.js", 'export const c = "C";')
        v = self.view(scheme.Router(self.web))
        self.assertEqual(self.result(v, "window.__ok"), "BC", "ES 모듈 import 사슬이 hazop-app://에서 읽혀야 한다")
        self.assertEqual(self.result(v, "window.__fetchBlocked === true || undefined"), True, "원격 주소 fetch는 실패해야 한다")
        self.assertFalse(any(u.startswith("hazop-app:") for u in v.interceptor.blocked), "앱 주소는 막지 않는다")

    def test_without_csp_a_page_still_cannot_read_a_file_url(self):
        """CSP가 없는 페이지(meta를 못 믿는 경우)도 file:// 읽기는 가로채기(둘째 겹)가 막는다."""
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("SECRET-OUTSIDE")
        url = "file:///" + outside.replace("\\", "/") + "/secret.txt"
        self.write("index.html", '<!doctype html><meta charset="utf-8"><script type="module" src="js/m.js"></script>')   # CSP 없음
        self.write("js/m.js", "window.__r = {};"
                   "fetch(%r).then(r => r.text()).then(t => { window.__r.fetch = t; }).catch(e => { window.__r.fetch = 'ERR'; });"
                   "try { const x = new XMLHttpRequest(); x.open('GET', %r, false); x.send(); window.__r.xhr = x.responseText || 'EMPTY'; }"
                   " catch (e) { window.__r.xhr = 'ERR'; }" % (url, url))
        v = self.view(scheme.Router(self.web))
        got = self.result(v, "window.__r && window.__r.fetch && window.__r.xhr ? window.__r : undefined")
        self.assertIsNotNone(got, "m.js가 돌지 않음")
        self.assertNotIn("SECRET", json.dumps(got))
        self.assertTrue(any(u.startswith("file:") for u in v.interceptor.blocked), "둘째 겹: 가로채기가 file 요청을 막았다")

    def test_meta_csp_blocks_inline_script_and_remote(self):
        """응답 머리는 웹 엔진에 닿지 않으므로 meta CSP가 실제로 걸리는지 본다(인라인 스크립트·원격 연결 차단)."""
        self.write("index.html", '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="%s">'
                   '<script>window.__inline = 1;</script><script type="module" src="js/m.js"></script>' % scheme.CSP)
        self.write("js/m.js", "window.__r = {inline: window.__inline === undefined ? 'blocked' : 'ran'};"
                   "fetch('https://example.com/x').catch(() => { window.__r.remote = 'blocked'; });")
        v = self.view(scheme.Router(self.web))
        got = self.result(v, "window.__r && window.__r.remote ? window.__r : undefined")
        self.assertEqual(got, {"inline": "blocked", "remote": "blocked"})

    def test_slow_read_api_does_not_freeze_the_gui_thread(self):
        class Slow:
            def read(self, parts, query):
                time.sleep(0.8)
                return scheme.Response(200, "application/json", b'{"ok": 1}')
        self.write("index.html", '<!doctype html><meta charset="utf-8"><script type="module" src="js/m.js"></script>')
        self.write("js/m.js", "fetch('/api/slow').then(r => r.json()).then(d => { window.__r = d; });")
        from PySide6.QtCore import QTimer
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        self.addCleanup(timer.stop)
        v = self.view(scheme.Router(self.web, api=Slow()))
        t0 = time.monotonic()
        got = self.result(v, "window.__r", seconds=15)
        self.assertEqual(got, {"ok": 1})
        inside = [x for x in ticks if t0 <= x <= t0 + 0.8]
        self.assertGreaterEqual(len(inside), 25, "읽기 API가 도는 0.8초 동안 화면 스레드가 돌아야 한다: %d" % len(inside))

    def test_junction_out_of_the_root_is_refused_for_real_requests(self):
        if os.name != "nt":
            self.skipTest("Windows 전용")
        import subprocess
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "x.js"), "w", encoding="utf-8") as fh:
            fh.write("window.__stolen = 1; export const a = 1;")
        res = subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(self.web, "js", "link"), outside], capture_output=True)
        if res.returncode != 0:
            self.skipTest("정션을 만들 수 없음")
        self.write("index.html", '<!doctype html><meta charset="utf-8"><script type="module" src="js/m.js"></script>')
        self.write("js/m.js", "window.__r = {};"
                   "import('/js/link/x.js').then(() => { window.__r.imp = 'LOADED'; }).catch(() => { window.__r.imp = 'refused'; });"
                   "fetch('/js/link/x.js').then(r => { window.__r.fetch = r.status; }).catch(() => { window.__r.fetch = 'refused'; });")
        v = self.view(scheme.Router(self.web))
        got = self.result(v, "window.__r && window.__r.imp && window.__r.fetch ? window.__r : undefined")
        self.assertIsNotNone(got)
        self.assertEqual(got["imp"], "refused")
        self.assertIn(got["fetch"], ("refused", 403, 404))
        self.assertIsNone(self.result(v, "window.__stolen", seconds=0.5))

    def test_short_8_3_work_root_loads_the_module_chain(self):
        if os.name != "nt":
            self.skipTest("Windows 전용")
        long_root = os.path.join(self.tmp, "A long folder name for 8dot3", "web")
        self.write("index.html", '<!doctype html><meta charset="utf-8"><script type="module" src="js/m.js"></script>', long_root)
        self.write("js/m.js", 'import {b} from "./dep.js"; window.__r = b;', long_root)
        self.write("js/dep.js", 'export const b = "SHORT-OK";', long_root)
        buf = ctypes.create_unicode_buffer(260)
        if not ctypes.windll.kernel32.GetShortPathNameW(long_root, buf, 260) or buf.value == long_root:
            self.skipTest("이 볼륨은 단축 이름을 만들지 않음")
        v = self.view(scheme.Router(buf.value))
        self.assertEqual(self.result(v, "window.__r"), "SHORT-OK")


if __name__ == "__main__":
    unittest.main()
