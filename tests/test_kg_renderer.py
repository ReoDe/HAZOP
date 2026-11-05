"""지식그래프 렌더러(force-graph) 오프라인 확인 테스트 (기획서/그래프활용.md §5.2, §7.2 V2 일부, WP0).

scripts/check_kg_renderer.py의 함수를 쓴다. 웹뷰는 QT_QPA_PLATFORM=offscreen에서 hazop/app/webview.py의 HazopWebView
(외부 요청 차단 설정 그대로)로 띄운다. 테스트 HTML은 임시 폴더에 만든다. 네트워크 호출 없음.
"""

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from scripts import check_kg_renderer as kr  # noqa: E402


def tearDownModule():
    """남은 웹뷰 페이지를 인터프리터 종료 전에 정리한다(tests/test_app.py와 같은 방식)."""
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


class VendorTest(unittest.TestCase):
    def test_hashes_match_source_record(self):
        rec = kr.recorded_hashes()
        self.assertEqual(kr.sha256(kr.VENDOR_JS), rec["force-graph.min.js"])
        self.assertEqual(kr.sha256(kr.VENDOR_LICENSE), rec["LICENSE"])

    def test_license_present(self):
        with open(kr.VENDOR_LICENSE, encoding="utf-8") as fh:
            self.assertIn("MIT", fh.read())


class UrlRuleTest(unittest.TestCase):
    def setUp(self):
        self.vendor = kr.vendor_text()
        self.html = kr.build_page(kr.synthetic_graph(10))

    def test_generated_page_passes(self):
        self.assertEqual(kr.url_violations(self.html, self.vendor), [])

    def test_vendor_namespace_strings_not_flagged(self):
        self.assertIn("http://www.w3.org/2000/svg", self.vendor)
        self.assertEqual(kr.url_violations(self.html, self.vendor), [])

    def test_url_outside_vendor_flagged(self):
        html = self.html.replace("<title>", '<link rel="stylesheet" href="https://cdn.example/x.css"><title>')
        self.assertTrue(any("cdn.example" in b for b in kr.url_violations(html, self.vendor)))

    def test_w3_namespace_outside_vendor_flagged(self):
        """허용 목록은 vendor 본문에만 적용된다. 생성 부분의 w3.org 문자열도 위반으로 본다."""
        html = self.html.replace("<body>", '<body><svg xmlns="http://www.w3.org/2000/svg"></svg>')
        self.assertTrue(kr.url_violations(html, self.vendor))

    def test_protocol_relative_and_websocket_flagged(self):
        for inj in ('<script src="//cdn.example/a.js"></script>', "<script>new WebSocket('ws://h.example/s')</script>",
                    "<script>new WebSocket('wss://h.example/s')</script>", '<div style="background:url(//h.example/x)">'):
            html = self.html.replace("<body>", "<body>" + inj)
            self.assertTrue(kr.url_violations(html, self.vendor), inj)

    def test_js_line_comment_not_flagged(self):
        html = self.html.replace("<body>", "<body><script>var a = 1; // note.example comment\n</script>")
        self.assertEqual(kr.url_violations(html, self.vendor), [])

    def test_unknown_url_in_vendor_flagged(self):
        vendor = self.vendor + "//https://evil.example/a.js"
        html = kr.build_page(kr.synthetic_graph(10)).replace(self.vendor, vendor)
        self.assertTrue(any("evil.example" in b for b in kr.url_violations(html, vendor)))

    def test_vendor_missing_flagged(self):
        self.assertTrue(kr.url_violations("<html></html>", self.vendor))


class RenderTest(unittest.TestCase):
    """offscreen QtWebEngine에서 실제 렌더링."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kg-renderer-test-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_small_graph_renders_offline(self):
        g = kr.synthetic_graph(kr.SMALL_NODES)
        st = kr.render(kr.build_page(g), self.tmp)
        self.assertEqual(kr.render_problems(st, g), [], st)
        self.assertEqual(st["errors"], [])
        self.assertEqual(st["blocked_requests"], [])
        self.assertTrue(st["canvas"])
        self.assertGreater(st["painted"], 0)
        self.assertEqual(st["nodes"], kr.SMALL_NODES)
        self.assertEqual(st["net"], [])
        self.assertEqual([c for c in st["console"] if c["level"] == "error"], [])

    def test_loopback_requests_judged_as_failure(self):
        """음성 대조: 루프백 img·fetch를 넣으면 가로채기 기록은 비어 있어도(웹뷰 설정이 먼저 막음) 페이지 계측으로 실패 판정."""
        g = kr.synthetic_graph(5)
        st = kr.render(kr.violating_page(g), self.tmp, timeout=30)
        self.assertTrue(any("fetch https://127.0.0.1:9/" in n for n in st["net"]), st["net"])
        self.assertTrue(any("127.0.0.1:9/hz-probe.png" in n for n in st["net"]), st["net"])
        self.assertTrue(any("요청 시도" in p for p in kr.render_problems(st, g)))
        self.assertTrue(kr.url_violations(kr.violating_page(g), kr.vendor_text()))

    def test_qt_console_messages_collected(self):
        """Qt 콘솔(javaScriptConsoleMessage) 수집 확인: console.warn은 기록만, Qt 콘솔 error는 실패 판정."""
        g = kr.synthetic_graph(5)
        html = kr.build_page(g).replace("<body>", "<body><script>console.warn('hz-warn-probe');</script>")
        st = kr.render(html, self.tmp, timeout=30)
        self.assertTrue(any(c["message"] == "hz-warn-probe" and c["level"] == "warning" for c in st["console"]), st["console"])
        self.assertEqual(kr.render_problems(st, g), [])
        st["console"].append({"level": "error", "message": "x", "line": 1})
        self.assertTrue(any("콘솔 오류" in p for p in kr.render_problems(st, g)))

    def test_blank_canvas_judged_as_failure(self):
        g = kr.synthetic_graph(5)
        html = kr.build_page(g).replace(".nodeId(\"id\")", ".nodeId(\"id\").nodeCanvasObject(function () {})"
                                        ".linkVisibility(false)")
        st = kr.render(html, self.tmp, timeout=30)
        self.assertEqual(st["painted"], 0, st)
        self.assertIn("canvas에 그려진 픽셀 없음", kr.render_problems(st, g))

    def test_page_errors_are_collected(self):
        """판정 장치 확인: 스크립트 오류가 나면 errors에 잡혀 실패로 판정된다."""
        g = kr.synthetic_graph(5)
        html = kr.build_page(g).replace("ForceGraph()(", "NoSuchRenderer()(")
        st = kr.render(html, self.tmp, timeout=20)
        self.assertTrue(st["errors"])
        self.assertTrue(kr.render_problems(st, g))

    def test_separate_script_file_is_not_loaded(self):
        """웹뷰는 LocalContentCanAccessFileUrls를 끄므로 <script src="파일">로는 vendor를 읽지 못한다(인라인 필요)."""
        g = kr.synthetic_graph(5)
        html = kr.build_page(g).replace("<script>" + kr.vendor_text() + "</script>",
                                        '<script src="force-graph.min.js"></script>')
        d = tempfile.mkdtemp(dir=self.tmp)
        shutil.copy(kr.VENDOR_JS, d)
        st = kr.render(html, d, timeout=20)
        self.assertTrue(any("ForceGraph" in e for e in st["errors"]), st)
        # 원인 대조: 같은 HTML을 이 테스트의 웹뷰에서만 LocalContentCanAccessFileUrls=True로 열면 읽힌다(앱 설정은 그대로)
        from PySide6.QtWebEngineCore import QWebEngineSettings
        st = kr.render(html, d, timeout=30, page_attrs={QWebEngineSettings.LocalContentCanAccessFileUrls: True})
        self.assertEqual(kr.render_problems(st, g), [], st)


if __name__ == "__main__":
    unittest.main()
