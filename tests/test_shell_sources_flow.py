"""같은 도면 번호의 원본이 형식 둘 이상일 때 도면 패널의 선택 카드(실제 새 화면 창 + 실제 엔진). 실행: python -m unittest tests.test_shell_sources_flow

SNP-M-101(drawio)과 같은 번호의 DEXPI 그래프를 같은 작업 루트에 더하면 카드가 뜨고, DEXPI를 고르면 '쓰는 중'으로 바뀌며 선택이 기록된다.
"""

import json
import os
import shutil
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.graph import build, sources  # noqa: E402

pump, wait_for = W.pump, W.wait_for
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEXPI = os.path.join(REPO, "tests", "fixtures", "dexpi", "small-pid-dexpi2.xml")


class SourceChoiceFlowTest(W.ShellBase):
    def add_dexpi_twin(self, win, number):
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import extract_dexpi
        with open(DEXPI, encoding="utf-8") as fh:
            text = fh.read().replace("TEST-1", number)
        src = os.path.join(self.tmp, "twin", number + ".xml")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(text)
        res, out = extract_dexpi.run_one(src, paths.output_root("extract"))
        name = os.path.basename(out)
        res = dict(res, project_id=win.engine.project_id())
        graph = build.build_graph(res)
        folder = os.path.join(paths.output_root("graph"), name)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "graph.json"), "w", encoding="utf-8") as fh:
            json.dump(graph, fh, ensure_ascii=False)
        self.addCleanup(shutil.rmtree, folder, True)
        self.addCleanup(shutil.rmtree, out, True)
        self.addCleanup(lambda: os.path.exists(sources.choices_path(win.engine.project_id())) and os.remove(sources.choices_path(win.engine.project_id())))
        return name

    def test_card_appears_for_mixed_formats_and_choosing_records_the_choice(self):
        win = self.window()
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        pump(0.5)
        self.assertEqual(self.js(win, "document.querySelector('.src-card') === null"), True, "충돌이 없으면 카드가 없다")
        number = [d["drawing_number"] for d in self.jsj(win, "window.__hz.store.get().drawings.drawings") if d["name"] == self.names[0]][0]
        self.add_dexpi_twin(win, number)
        win.engine.changed("drawings", None)
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.src-card') !== null") is True, 15), self.text(win)[-400:])
        text = self.text(win)
        self.assertIn("같은 도면 번호의 원본이 여러 형식으로 있습니다", text)
        self.assertIn("먼저 있던 형식", text)
        self.assertTrue(self.click(win, "button[aria-label='%s: DEXPI 쓰기']" % number))
        self.assertTrue(wait_for(lambda: "사람이 고름" in self.text(win), 15), self.text(win)[-400:])
        self.assertEqual(sources.load_choices(win.engine.project_id())[number]["format"], "dexpi")
        self.assertEqual(sources.load_choices(win.engine.project_id())[number]["by"], "검토자A")
        self.assertNotIn(self.tmp, self.text(win), "웹에는 경로를 보이지 않는다")


if __name__ == "__main__":
    unittest.main()
