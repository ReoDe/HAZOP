"""구간 패널의 '분석에서 제외'·'다시 넣기'를 실제 새 화면(화면 밖)에서 누른다. 실행: python -m unittest tests.test_shell_node_screen_flow

확정된 구간을 고르고 이유를 적어 제외하면 엔진이 확인 글을 돌려주고, 화면이 그 글을 보인 뒤 '확인하고 제외'로 저장한다. 목록 행에 '분석 제외'
칩이 붙고 분석 행에서 빠지며, '다시 넣기'로 돌아온다. HAZOP_CAPTURE_DIR가 있으면 제외한 상태의 창을 그 폴더에 PNG로 남긴다.
"""

import copy
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.shell import api_nodes, api_results  # noqa: E402
from hazop.study import nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_node_tools import DEVS, snp_graph  # noqa: E402

pump, wait_for = W.pump, W.wait_for
tearDownModule = W.shell_teardown
S101 = "graph-SNP-M-101"


class NodeScreenPanelTest(W.ShellBase):
    def setUp(self):
        from hazop.app import project_ctx
        self.pg = snp_graph()
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)

    def rows(self):
        return [n["node_id"] for n in api_results.scope_rows(nodes.load(self.pg))]

    def make_confirmed(self, win):
        ids = [n["local_id"] for n in self.pg["nodes"] if n.get("sheet") == S101][:6]
        eng = win.engine
        r = eng.dispatch("nodes.create", {"project_id": "SNP", "set_rev": api_nodes.summary(eng)["set_rev"], "sheet": S101, "ids": ids,
                                          "name": "가압기 계통"})
        self.assertTrue(r["ok"], r)
        nid = r["data"]["node_ids"][0]
        row = next(n for n in api_nodes.summary(eng)["nodes"] if n["node_id"] == nid)
        r = eng.dispatch("nodes.confirm", {"project_id": "SNP", "set_rev": api_nodes.summary(eng)["set_rev"], "node_ids": [nid],
                                           "targets": [{"node_id": nid, "rev": row["rev"], "state": row["state"]}]})
        self.assertTrue(r["ok"], r)
        return nid

    def wait_js(self, win, code, timeout=60):
        return wait_for(lambda: self.js(win, code), timeout)

    def click_label(self, win, label):
        return self.wait_js(win, "(() => { const b = document.querySelector('.panel button[aria-label=%s]'); if (!b || b.disabled) return false;"
                                 " b.click(); return true; })()" % repr(label).replace("'", '"'))

    def capture(self, win, name):
        out = os.environ.get("HAZOP_CAPTURE_DIR")
        if out:
            os.makedirs(out, exist_ok=True)
            pump(0.5)
            win.grab().save(os.path.join(out, name))

    def test_exclude_confirmed_node_from_the_card_then_put_it_back(self):
        win = self.window()
        self.switch_project(win, "SNP")
        nid = self.make_confirmed(win)
        self.assertIn(nid, self.rows())
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        self.assertTrue(self.click_label(win, "%s 가압기 계통" % nid), "목록 행")
        self.assertTrue(self.click_label(win, "%s 분석에서 제외" % nid), "제외 단추")
        self.assertTrue(self.wait_js(win, """(() => { const i = document.getElementById('screen-reason-%s'); if (!i) return false;
            if (i.value !== '보조 계통이라 범위 밖') { i.value = '보조 계통이라 범위 밖'; i.dispatchEvent(new Event('input', {bubbles: true})); }
            return i.value === '보조 계통이라 범위 밖'; })()""" % nid), "이유 입력")
        self.assertTrue(self.click_label(win, "%s 제외 실행" % nid))
        self.assertTrue(wait_for(lambda: "확정된 구간" in self.text(win), 30), self.text(win)[-400:])
        self.assertIn(nid, self.rows(), "확인 전에는 저장하지 않음")
        self.capture(win, "nodes-ask.png")
        self.assertTrue(self.click_label(win, "%s 확인하고 제외" % nid))
        self.assertTrue(wait_for(lambda: nid not in self.rows(), 30), "분석 행에서 빠짐")
        self.assertTrue(wait_for(lambda: "분석 제외" in self.text(win) and "보조 계통이라 범위 밖" in self.text(win), 30), self.text(win)[-400:])
        self.capture(win, "nodes-excluded.png")
        self.assertTrue(self.click_label(win, "%s 분석에 다시 넣기" % nid))
        self.assertTrue(wait_for(lambda: nid in self.rows(), 30), "다시 분석 행에 들어옴")
        self.assertTrue(wait_for(lambda: "분석에서 제외" in self.text(win) and "보조 계통이라" not in self.text(win), 30))


    def test_drawing_exclude_box_asks_when_nodes_hold_its_components(self):
        """도면 패널에 붙일 상자(nodes_screen.DrawingExclude)를 화면에 직접 붙여 누른다(도면 패널 자리는 s-frame이 넣는다)."""
        S102 = "graph-SNP-M-102"
        win = self.window()
        self.switch_project(win, "SNP")
        ids = [n["local_id"] for n in self.pg["nodes"] if n.get("sheet") == S102][:6]
        r = win.engine.dispatch("nodes.create", {"project_id": "SNP", "set_rev": api_nodes.summary(win.engine)["set_rev"], "sheet": S102,
                                                 "ids": ids, "name": "가압기 범례"})
        self.assertTrue(r["ok"], r)
        nid = r["data"]["node_ids"][0]
        self.js(win, """(async () => {
            const [{ html, render }, m] = await Promise.all([import(new URL('js/ui/html.js', location.href)),
                                                           import(new URL('js/panels/nodes_screen.js', location.href))]);
            const box = document.createElement('div'); box.id = 'dx-test'; box.className = 'panel';
            box.style.cssText = 'position:fixed;left:60px;top:60px;width:360px;z-index:99;background:var(--bg,#fff)';
            document.body.appendChild(box);
            render(html`<${m.DrawingExclude} graphId=${'%s'} />`, box); })()""" % S102)
        self.assertTrue(self.click_label(win, "SNP-M-102 분석에서 빼기"), self.text(win)[-300:])
        self.assertTrue(self.click_label(win, "빼기 실행"))
        self.assertTrue(wait_for(lambda: "%s(6개)" % nid in self.text(win), 30), self.text(win)[-400:])
        self.assertEqual(nodes.exclusion_for(self.pg)[0], frozenset(), "확인 전에는 저장하지 않음")
        self.capture(win, "drawing-ask.png")
        self.assertTrue(self.click_label(win, "확인하고 빼기"))
        self.assertTrue(wait_for(lambda: nodes.exclusion_for(self.pg)[0] == frozenset({S102}), 30))
        self.assertTrue(wait_for(lambda: "구간 분석에서 뺌" in self.text(win), 30), self.text(win)[-400:])
        self.capture(win, "drawing-excluded.png")
        self.assertTrue(self.click_label(win, "SNP-M-102 분석에 다시 넣기"))
        self.assertTrue(wait_for(lambda: nodes.exclusion_for(self.pg)[0] == frozenset(), 30))


if __name__ == "__main__":
    unittest.main()
