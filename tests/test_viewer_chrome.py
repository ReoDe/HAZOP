"""뷰어 도면 위 표시(U-12 칩 줄, U-13 태그 최소 글자). 실행: python -m unittest discover -s tests -t .

QT_QPA_PLATFORM=offscreen에서 샘플 도면(SNP-M-102) 뷰어 HTML을 임시 폴더에 만들어 띄운다. 네트워크 사용 없음.
"""

import json
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.test_viewer import SAMPLES, extraction_with_svg  # noqa: E402
from tests.test_viewer_panel import wait_for  # noqa: E402
from hazop.graph import build as graph_build  # noqa: E402
from hazop.viewer import build  # noqa: E402

PZR_LABEL = "local-node-001"  # SNP-M-102 RC-PZ01(라벨 글자 크기 10)


class ViewerChromeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        ex, svg = extraction_with_svg([p for p in SAMPLES if "SNP-M-102" in p][0])
        cls.ex = ex
        path = os.path.join(cls.tmp.name, "SNP-M-102.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(build.build_drawing_html(ex, svg, graph_build.build_graph(ex)))
        cls.view = QWebEngineView()
        cls.view.resize(1366, 768)
        cls.view.show()
        loaded = []
        cls.view.loadFinished.connect(loaded.append)
        cls.view.load(QUrl.fromLocalFile(path))
        assert wait_for(lambda: loaded) and loaded[-1], "페이지 로드 안 됨"

    @classmethod
    def tearDownClass(cls):
        cls.view.close()
        cls.view.deleteLater()
        wait_for(lambda: False, 0.2)
        cls.tmp.cleanup()

    def setUp(self):
        self.js("document.getElementById('zfit').click(); 1")

    def js(self, expr):
        out = []
        self.view.page().runJavaScript(expr, 0, out.append)
        self.assertTrue(wait_for(lambda: out, 10), "runJavaScript 결과 없음: %s" % expr)
        return out[0]

    def display(self, el_id):
        return self.js("getComputedStyle(document.getElementById('%s')).display" % el_id)

    def tag_state(self):
        return json.loads(self.js("JSON.stringify(window.hzTags.state())"))

    def test_readable_threshold_is_11px(self):
        self.assertEqual(self.js("window.hzTags.MIN_PX"), 11)
        self.assertTrue(self.js("window.hzTags.readable(10, 1.1)"))
        self.assertFalse(self.js("window.hzTags.readable(10, 1.09)"))

    def test_fit_zoom_collapses_tags_and_zoom_in_reveals(self):
        st = self.tag_state()
        sizes = [n["label_location"]["style"]["fontSize"] for n in self.ex["nodes"] if n.get("label_location")]
        self.assertLess(max(sizes) * st["scale"], 11, "맞춤 배율에서 이미 11px 이상: 검사 전제가 틀림")
        self.assertGreater(st["total"], 0)
        self.assertEqual(st["collapsed"], st["total"])
        self.assertGreater(st["hidden_text"], 0)
        label = ("(function(){var g=null;document.querySelectorAll('#stage > svg:not(#overlay) [data-cell-id]').forEach("
                 "function(e){if(!g&&e.getAttribute('data-cell-id')==='%s')g=e;});"
                 "return getComputedStyle(g.querySelector('switch, text')).visibility;})()")
        cell = next(n["source_object_id"] for n in self.ex["nodes"] if n["local_id"] == PZR_LABEL)
        self.assertEqual(self.js(label % cell), "hidden")
        self.assertTrue(self.js("document.querySelector('#layer-tag [data-local-id=\"%s\"]')"
                                ".classList.contains('tag-collapsed')" % PZR_LABEL))
        labels = ("JSON.stringify(Array.prototype.filter.call(document.querySelectorAll('#taglabels span'),"
                  "function(s){return s.style.display!=='none';}).map(function(s){"
                  "return [s.textContent, parseFloat(getComputedStyle(s).fontSize)];}))")
        shown = json.loads(self.js(labels))
        self.assertEqual(len(shown), st["total"], "숨긴 도면 글자 대신 태그를 확대하지 않는 글자 층에 쓴다(U-13)")
        self.assertTrue(all(px >= 11 for _t, px in shown), shown)
        self.assertTrue(all(t for t, _px in shown))
        self.js("window.hzView.set({s: 11 / %s, x: 0, y: 0}); 1" % min(sizes))
        self.assertEqual(self.tag_state()["collapsed"], 0)
        self.assertEqual(self.js(label % cell), "visible")
        self.assertEqual(json.loads(self.js(labels)), [], "읽히는 배율이면 덧쓴 글자는 숨김")

    def test_hidden_tag_layer_keeps_drawing_text(self):
        self.js("window.hzToggleLayer('tag'); 1")
        try:
            self.assertEqual(self.tag_state()["collapsed"], 0)
        finally:
            self.js("window.hzToggleLayer('tag'); 1")
        self.assertEqual(self.tag_state()["collapsed"], self.tag_state()["total"])

    def test_layer_chips_are_one_line_and_legend_collapsed(self):
        self.assertLess(self.js("document.getElementById('layers').getBoundingClientRect().height"), 40)
        self.assertEqual(self.display("legend-drop"), "none")
        self.js("document.getElementById('legend-btn').click(); 1")
        self.assertEqual(self.display("legend-drop"), "block")
        self.js("document.getElementById('legend-btn').click(); 1")
        self.assertEqual(self.display("legend-drop"), "none")
        self.assertFalse(self.js("window.hzToggleLayer('symbol')"))
        self.assertTrue(self.js("document.getElementById('layer-symbol').classList.contains('hidden')"))
        self.assertTrue(self.js("window.hzToggleLayer('symbol')"))

    def test_path_query_hidden_until_opened(self):
        self.assertEqual(self.display("pathq"), "none")
        self.assertTrue(self.js("window.openPathQuery()"))
        self.assertEqual(self.display("pathq"), "block")
        self.assertEqual(self.js("document.activeElement.id"), "pq-a")
        self.js("document.getElementById('pq-close').click(); 1")
        self.assertEqual(self.display("pathq"), "none")
        self.js("document.getElementById('pq-chip').click(); 1")
        self.assertEqual(self.display("pathq"), "block")
        self.js("document.getElementById('pq-chip').click(); 1")
        self.assertEqual(self.display("pathq"), "none")

    def test_segment_legend_follows_groups(self):
        self.assertEqual(self.display("seglegend"), "none")
        self.js("window.hzSegLegend([{label: 'S1', color: 'var(--ink)', active: true, ids: ['a', 'b']},"
                "{label: 'S2', color: 'var(--muted)', active: false, ids: ['c']}], 3); 1")
        try:
            self.assertEqual(self.display("seglegend"), "flex")
            self.assertEqual(self.js("document.getElementById('seglegend').innerText.replace(/\\s+/g, ' ').trim()"),
                             "구간 S1 S2 미포함 3")
            self.assertEqual(self.js("document.querySelectorAll('#seglegend .segchip.active').length"), 1)
            search_top = self.js("document.getElementById('search').getBoundingClientRect().top")
            seg_bottom = self.js("document.getElementById('seglegend').getBoundingClientRect().bottom")
            self.assertGreaterEqual(search_top, seg_bottom, "구간 칩 줄이 검색 상자와 겹침")
        finally:
            self.js("window.hzSegLegend([], 0); 1")
        self.assertEqual(self.display("seglegend"), "none")


if __name__ == "__main__":
    unittest.main()
