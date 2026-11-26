"""도면 패널의 휴지통 '삭제'를 실제 새 화면(화면 밖)에서 누른다. 엔진은 '구간 분석에서 빼기'를 쓴다(파일은 지우지 않는다).

줄 옆 체크로 고르면 위쪽에 '삭제'(아이콘만)와 '해제'가 나온다. 확인 창 없이 저장하고 그 도면은 목록에서 없어진다. 구간 카드에는 구간 단위
'분석에서 제외'가 없다.
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

    def pick_row(self, win, label):
        """도면 줄 옆 체크 상자를 누른다(체크 상자는 단추가 아니라 click_label로 못 누른다)."""
        return wait_for(lambda: self.js(win, "(() => { const b = document.querySelector('.panel input[aria-label=\"%s\"]'); if (!b) return false; b.click(); return true; })()" % label), 60)

    def capture(self, win, name):
        out = os.environ.get("HAZOP_CAPTURE_DIR")
        if out:
            os.makedirs(out, exist_ok=True)
            pump(2.0)   # 화면 밖 웹 화면은 그림이 늦게 따라온다
            win.grab().save(os.path.join(out, name))

    def test_the_trash_button_removes_a_drawing_from_the_list_without_a_confirm_box(self):
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
        self.assertTrue(self.pick_row(win, "SNP-M-102 고르기"), self.text(win)[-300:])          # 줄 옆 체크 → 위쪽 한 줄 도구(화면 단순화)
        row = "!!document.querySelector('.panel input[aria-label=\\'SNP-M-102 고르기\\']')"
        self.assertTrue(self.click_label(win, "삭제"))
        self.assertTrue(wait_for(lambda: nodes.exclusion_for(self.pg)[0] == frozenset({S102}), 30), "확인 창 없이 바로 저장한다")
        self.assertTrue(wait_for(lambda: self.js(win, row) is False, 30), "지운 도면은 목록에서 없어진다: " + self.text(win)[-300:])
        for gone in ("확인하고 빼기", "분석 제외", "다시 넣기", "%s 6개" % nid):
            self.assertNotIn(gone, self.text(win), "확인 창·안내 글·칩이 없다")
        self.assertTrue(wait_for(lambda: not self.js(win, "window.__hz.store.get().sheet"), 10), "열어 둔 도면이 지운 것이면 화면에서도 내린다")
        self.capture(win, "drawing-removed.png")


class NodeRowWrapTest(W.ShellBase):
    """1366폭의 좁은 구간 패널에서 경고·자물쇠 아이콘이 함께 붙어도 구간 번호·이름이 잘리지 않는다(상태 꼬리표는 줄에서 뺐다)."""

    setUp = DrawingExcludePanelTest.setUp

    def test_the_name_keeps_its_width_beside_both_icons(self):
        win = self.window((1366, 768))
        self.switch_project(win, "SNP")
        ids = [n["local_id"] for n in self.pg["nodes"] if n.get("sheet") == S102][10:14]
        r = win.engine.dispatch("nodes.create", {"project_id": "SNP", "set_rev": api_nodes.summary(win.engine)["set_rev"], "sheet": S102,
                                                 "ids": ids, "name": "가압기 살수 배관"})
        self.assertTrue(r["ok"], r)
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.nrow .nm')"), 30))
        self.js(win, """(() => { const row = document.querySelector('.nrow');
            for (const cls of ['warn-mark', 'lock-mark']) { const c = document.createElement('span'); c.className = cls; c.style.width = '15px'; c.style.height = '15px'; row.appendChild(c); } })()""")
        pump(0.3)
        cut = self.js(win, "(() => { const b = document.querySelector('.nrow .main b'); return b.scrollWidth > b.clientWidth + 1; })()")
        self.assertFalse(cut, "구간 이름이 줄어듦: %s" % self.js(win, "document.querySelector('.nrow .main b').getBoundingClientRect().width"))


if __name__ == "__main__":
    unittest.main()
