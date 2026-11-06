"""뷰어 속성 패널: 체크밸브 허용 방향 표시(기획서/정보추출.md #rules-code-diff). 실행: python -m unittest discover -s tests -t .

QT_QPA_PLATFORM=offscreen에서 실제 뷰어 HTML을 띄워 체크밸브 노드를 클릭하고 패널 글자를 읽는다. 네트워크 사용 없음.
환경 변수 HAZOP_VIEWER_PANEL_SHOTS=<폴더>가 있으면 사례별 스크린샷을 저장한다(기본은 저장하지 않음).
"""

import copy
import glob
import json
import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.test_viewer import SAMPLES, extraction_with_svg  # noqa: E402
from hazop.graph import build as graph_build  # noqa: E402
from hazop.viewer import build  # noqa: E402

VALVE = "local-node-020"      # SNP-M-101 RC-V020: flow_direction 속성으로 판정된 체크밸브(declared)
OTHER = "local-node-001"      # 체크밸브가 아닌 노드
DECLARED = "(작성자 선언, 사람 확인 전)"


def wait_for(cond, timeout=40.0):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return bool(cond())


class CheckDirectionPanelTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView
        cls.app = QApplication.instance() or QApplication([])
        cls.view = QWebEngineView()
        cls.view.resize(1440, 860)
        cls.view.show()
        cls.tmp = tempfile.TemporaryDirectory()
        path = [p for p in SAMPLES if "SNP-M-101" in p][0]
        cls.ex, cls.svg = extraction_with_svg(path)
        cls.graph = graph_build.build_graph(cls.ex)

    @classmethod
    def tearDownClass(cls):
        cls.view.close()
        cls.view.deleteLater()
        wait_for(lambda: False, 0.2)
        cls.tmp.cleanup()

    def panel_text(self, name, graph, local_id, extraction=None):
        """뷰어를 만들어 띄우고 local_id 요소를 클릭한 뒤 #panel 글자를 돌려준다."""
        from PySide6.QtCore import QUrl
        page = build.build_drawing_html(extraction or self.ex, self.svg, graph)
        path = os.path.join(self.tmp.name, name + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)
        loaded = []
        self.view.loadFinished.connect(loaded.append)
        try:
            self.view.load(QUrl.fromLocalFile(path))
            self.assertTrue(wait_for(lambda: loaded), "페이지 로드 안 됨")
        finally:
            self.view.loadFinished.disconnect(loaded.append)
        self.assertTrue(loaded[-1])
        got = []
        self.view.page().runJavaScript(
            "(function(){var e=document.querySelector('#overlay [data-local-id=\"%s\"]');"
            "if(!e) return null; e.dispatchEvent(new MouseEvent('click',{bubbles:true}));"
            "return document.getElementById('panel').innerText;})()" % local_id, 0, got.append)
        self.assertTrue(wait_for(lambda: got), "runJavaScript 결과 없음")
        self.assertIsNotNone(got[-1], "오버레이에 %s 없음" % local_id)
        shots = os.environ.get("HAZOP_VIEWER_PANEL_SHOTS")
        if shots:
            os.makedirs(shots, exist_ok=True)
            wait_for(lambda: False, 0.5)
            self.view.grab().save(os.path.join(shots, name + ".png"))
        return got[-1]

    def graph_with(self, cd):
        g = copy.deepcopy(self.graph)
        n = [n for n in g["nodes"] if n["local_id"] == VALVE][0]
        n["check_direction"] = cd
        return g

    def test_declared_from_graph(self):
        n = [n for n in self.graph["nodes"] if n["local_id"] == VALVE][0]
        self.assertEqual(n["check_direction"]["status"], "declared")
        loc = {g["entity_id"]: g["local_id"] for g in self.graph["nodes"]}
        text = self.panel_text("declared", self.graph, VALVE)
        line = [l for l in text.splitlines() if l.startswith("허용 방향")][-1]
        self.assertTrue(line.endswith(DECLARED), line)
        self.assertIn("입구 ", line)
        self.assertIn(loc[n["check_direction"]["inlet"]], line.split("→")[0])
        self.assertIn(loc[n["check_direction"]["outlet"]], line.split("→")[1])

    def test_symbol_status(self):
        cd = dict([n for n in self.graph["nodes"] if n["local_id"] == VALVE][0]["check_direction"], status="symbol")
        text = self.panel_text("symbol", self.graph_with(cd), VALVE)
        self.assertIn("(기호 기반)", text)
        self.assertNotIn(DECLARED, text)

    def test_null_is_unknown(self):
        text = self.panel_text("null", self.graph_with(None), VALVE)
        self.assertIn("허용 방향 미확인", text)
        self.assertNotIn("허용 방향: 입구", text)

    def test_unknown_status_not_shown_as_confirmed(self):
        cd = dict([n for n in self.graph["nodes"] if n["local_id"] == VALVE][0]["check_direction"], status="other")
        self.assertIn("(상태 미확인: other)", self.panel_text("other", self.graph_with(cd), VALVE))

    def test_without_graph_uses_extraction(self):
        src = [n for n in self.ex["nodes"] if n["local_id"] == VALVE][0]["check_direction"]
        text = self.panel_text("nograph", None, VALVE)
        line = [l for l in text.splitlines() if l.startswith("허용 방향")][-1]
        self.assertTrue(line.endswith(DECLARED), line)
        self.assertIn(src["inlet"], line.split("→")[0])
        self.assertIn(src["outlet"], line.split("→")[1])

    def test_other_node_has_no_direction_section(self):
        n = [n for n in self.ex["nodes"] if n["local_id"] == OTHER][0]
        self.assertNotEqual(n["kind"], "check_valve")
        self.assertNotIn("허용 방향", self.panel_text("other-node", self.graph, OTHER))


if __name__ == "__main__":
    unittest.main()
