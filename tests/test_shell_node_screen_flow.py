"""도면 패널의 '분석에서 빼기'·'다시 넣기'(범례·기호표 도면)를 실제 새 화면(화면 밖)에서 누른다.
실행: python -m unittest tests.test_shell_node_screen_flow

연 도면 아래 상자에서 이유를 적고 빼면, 그 도면 구성요소를 품은 구간이 있을 때 엔진이 확인 글을 돌려주고 화면이 그 글을 보인 뒤
'확인하고 빼기'로 저장한다. 목록 행에 '분석 제외' 칩이 붙고, '다시 넣기'로 돌아온다. 구간 카드에는 구간 단위 '분석에서 제외'가 없다.
HAZOP_CAPTURE_DIR가 있으면 확인 글과 뺀 상태의 창을 그 폴더에 PNG로 남긴다.
"""

import copy
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.shell import api_nodes  # noqa: E402
from hazop.study import nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_node_tools import DEVS, snp_graph  # noqa: E402

pump, wait_for = W.pump, W.wait_for
tearDownModule = W.shell_teardown
S102 = "graph-SNP-M-102"


class DrawingExcludePanelTest(W.ShellBase):
    def setUp(self):
        from hazop.app import project_ctx
        self.pg = snp_graph()
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)

    def click_label(self, win, label):
        return wait_for(lambda: self.js(win, "(() => { const b = document.querySelector('.panel button[aria-label=%s]');"
                                             " if (!b || b.disabled) return false; b.click(); return true; })()"
                                        % repr(label).replace("'", '"')), 60)

    def capture(self, win, name):
        out = os.environ.get("HAZOP_CAPTURE_DIR")
        if out:
            os.makedirs(out, exist_ok=True)
            pump(2.0)   # 화면 밖 웹 화면은 그림이 늦게 따라온다
            win.grab().save(os.path.join(out, name))

    def test_exclude_a_drawing_from_the_drawings_panel_then_put_it_back(self):
        win = self.window()
        self.switch_project(win, "SNP")
        ids = [n["local_id"] for n in self.pg["nodes"] if n.get("sheet") == S102][:6]
        r = win.engine.dispatch("nodes.create", {"project_id": "SNP", "set_rev": api_nodes.summary(win.engine)["set_rev"], "sheet": S102,
                                                 "ids": ids, "name": "가압기 범례"})
        self.assertTrue(r["ok"], r)
        nid = r["data"]["node_ids"][0]
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        self.assertTrue(wait_for(lambda: "가압기 범례" in self.text(win), 30))
        self.assertNotIn("분석에서 제외", self.text(win), "구간 카드에는 구간 단위 제외가 없다")
        self.js(win, "window.__hz.store.set({panel: 'drawings', sheet: '%s'})" % S102)
        self.assertTrue(self.click_label(win, "SNP-M-102 분석에서 빼기"), self.text(win)[-300:])
        self.assertTrue(self.click_label(win, "빼기 실행"))
        self.assertTrue(wait_for(lambda: "%s 6개" % nid in self.text(win), 30), self.text(win)[-400:])
        self.assertEqual(nodes.exclusion_for(self.pg)[0], frozenset(), "확인 전에는 저장하지 않음")
        self.capture(win, "drawing-ask.png")
        self.assertTrue(self.click_label(win, "확인하고 빼기"))
        self.assertTrue(wait_for(lambda: nodes.exclusion_for(self.pg)[0] == frozenset({S102}), 30))
        self.assertTrue(wait_for(lambda: "구간 분석에서 뺌" in self.text(win) and "분석 제외" in self.text(win), 30), self.text(win)[-400:])
        self.capture(win, "drawing-excluded.png")
        self.assertTrue(self.click_label(win, "SNP-M-102 분석에 다시 넣기"))
        self.assertTrue(wait_for(lambda: nodes.exclusion_for(self.pg)[0] == frozenset(), 30))


if __name__ == "__main__":
    unittest.main()
