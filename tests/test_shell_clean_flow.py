"""정리된 보기를 새 화면 틀에 이은 통합 시험(실제 새 화면 창 + 실제 읽기 API, 모델 쪽만 가짜 세션). 실행: python -m unittest tests.test_shell_clean_flow

읽기 API `clean/<도면 ID>`가 도면 ID로만 읽히고, 도면을 열면 읽은 방법에 맞는 기본 보기로 열리며, 키 O와 단추로 원본 ↔ 정리를 바꿔도 화면 이동·확대가 그대로이고,
채팅 답의 경로 표시와 구간 색, 고른 것이 정리된 보기에서도 같은 저장소 키로 그려지는지 본다(도면 구성요소 자체의 그리기 시험은 tests/test_shell_clean.py).
"""

import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.shell import api  # noqa: E402

pump, wait_for = W.pump, W.wait_for
S1 = W.S1


class CleanFlowTest(W.ShellBase):
    def open_sheet(self, win, gid=None):
        gid = gid or sorted(win.engine.graph_names())[0]
        self.js(win, "window.__hz.store.set({sheet: %s, panel: null})" % json.dumps(gid))
        win.engine.dispatch("sheet.open", {"graph_id": gid})
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.hz-cv-world') !== null") is True, 20), "도면이 그려지지 않음")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.viewswitch') !== null") is True, 20), "원본·정리 단추가 없음")
        pump(1.0)
        return gid

    def pressed(self, win, label):
        return self.js(win, "(() => { const b = [...document.querySelectorAll('.clean-toggle button')].find((x) => x.textContent.trim() === %s); return b ? b.getAttribute('aria-pressed') : null; })()" % json.dumps(label))

    def world(self, win):
        return self.js(win, "document.querySelector('.hz-cv-world').style.transform")

    def key(self, win, k, shift=False):
        self.js(win, "window.dispatchEvent(new KeyboardEvent('keydown', {key: %s, shiftKey: %s, bubbles: true}))" % (json.dumps(k), "true" if shift else "false"))
        pump(0.5)

    def test_read_api_serves_clean_data_by_graph_id_only(self):
        win = self.window()
        gid = sorted(win.engine.graph_names())[0]
        r = api.ReadApi(win.engine).read(["clean", gid], {})
        self.assertIsNotNone(r)
        data = json.loads(r.body.decode("utf-8"))
        self.assertIn(data["source_format"], ("drawio", "dexpi", "pdf_vector"))
        self.assertIn("unconfirmed", data)
        self.assertIn("counts", data)
        for bad in ("없는-도면", "../x", "graph-NOPE"):
            self.assertIsNone(api.ReadApi(win.engine).read(["clean", bad], {}), bad)
        self.assertIsNone(api.ReadApi(win.engine).read(["clean"], {}))
        self.assertIsNone(api.ReadApi(win.engine).read(["clean", gid, "x"], {}))

    def test_a_drawio_sheet_opens_in_the_clean_view_and_o_toggles_without_moving(self):
        win = self.window()
        self.open_sheet(win)
        self.assertEqual(self.pressed(win, "정리"), "true", "drawio는 정리가 기본")
        self.assertEqual(self.pressed(win, "원본"), "false")
        t0 = self.world(win)
        self.assertTrue(t0)
        self.key(win, "o")
        self.assertEqual(self.pressed(win, "원본"), "true")
        self.assertEqual(self.world(win), t0, "바꿔도 이동·확대가 그대로")
        self.key(win, "O")
        self.assertEqual(self.pressed(win, "정리"), "true")
        self.assertEqual(self.world(win), t0)
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [], "콘솔 오류 없음")

    def test_the_choice_is_kept_per_sheet_until_the_app_closes_and_buttons_switch(self):
        win = self.window()
        g1 = self.open_sheet(win)
        self.assertTrue(self.click(win, ".clean-toggle button", 0))
        pump(0.5)
        self.assertEqual(self.pressed(win, "원본"), "true")
        g2 = sorted(win.engine.graph_names())[1]
        self.open_sheet(win, g2)
        self.assertEqual(self.pressed(win, "정리"), "true", "다른 도면은 자기 기본 보기")
        self.js(win, "window.__hz.store.set({sheet: %s})" % json.dumps(g1))
        pump(1.0)
        self.assertEqual(self.pressed(win, "원본"), "true", "앞 도면의 고른 보기는 기억한다")

    def test_the_status_chip_is_drawn_in_the_frame(self):
        win = self.window()
        self.open_sheet(win)
        chip = self.js(win, "(() => { const c = document.querySelector('.viewswitch .chip'); return c ? c.textContent.trim() : ''; })()")
        self.assertTrue("미확인" in chip or "drawio" in chip, chip)      # 미확인이 있으면 '미확인 n곳', 모두 읽었으면 읽은 방법 꼬리표
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])

    def test_marks_use_the_same_store_key_and_are_drawn_in_both_views(self):
        """표시(채팅 답의 경로·강조가 만드는 것과 같은 모양)는 store.marks.bySheet[도면]에 그대로 두고, 원본은 겹쳐 그리고 정리는 그 객체의 색을 바꾼다."""
        win = self.window()
        gid = self.open_sheet(win)
        self.js(win, "window.__hz.read('sheet/' + %s).then((d) => { window.__ids = d.items.filter((i) => i.kind !== 'pipe').slice(0, 3).map((i) => i.id); })" % json.dumps(gid))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "(window.__ids || []).length")), 10))
        ids = self.jsj(win, "window.__ids")
        self.assertTrue(ids)
        self.js(win, "window.__hz.store.set({marks: {rid: 'm1', bySheet: {%s: [{op: 'mark', ids: %s, style: 'focus'}]}}})" % (json.dumps(gid), json.dumps(ids)))
        self.assertEqual(self.pressed(win, "정리"), "true")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.hz-cv-marks rect[fill-opacity]').length") or 0) > 0, 10),
                        "정리된 보기에서 표시되지 않은 것은 흰 막으로 흐려진다")
        self.assertEqual(self.js(win, "document.querySelector('.hz-cv-host, [data-view]').getAttribute('data-view')"), "clean")
        self.key(win, "o")
        self.assertEqual(self.pressed(win, "원본"), "true")
        self.assertEqual(self.js(win, "document.querySelector('[data-view]').getAttribute('data-view')"), "orig")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.hz-cv-marks *').length") or 0) > 0, 10), "원본 보기는 겹쳐 그린다")
        self.assertEqual(self.jsj(win, "Object.keys(window.__hz.store.get().marks.bySheet)"), [gid], "같은 저장소 키")
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])

    def test_project_switch_forgets_the_cached_clean_data(self):
        win = self.window()
        self.open_sheet(win)
        self.assertTrue(self.click(win, ".clean-toggle button", 0))
        pump(0.3)
        self.assertGreater(self.js(win, "Object.keys(window.__hz.clean.get().data).length"), 0)
        self.switch_project(win, "OTHER-PROJECT")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.hz-cv-world') === null") is True, 10), "프로젝트를 바꾸면 도면이 닫힌다")
        self.assertEqual(self.js(win, "Object.keys(window.__hz.clean.get().data).length + Object.keys(window.__hz.clean.get().choice).length"), 0,
                         "앞 프로젝트의 정리 자료와 고른 보기도 비워진다")


if __name__ == "__main__":
    unittest.main()


class CleanWithNodesTest(W.ShellBase):
    """정리된 보기에서도 구간 꼬리표·고르기·구간 만들기가 같은 저장소 키로 되는지(원본 보기는 겹쳐 그리고 정리된 보기는 객체 색을 바꿈)."""

    S101 = "graph-SNP-M-101"

    def setUp(self):
        import copy
        from unittest import mock
        from hazop.app import project_ctx
        from hazop.study import results as res
        from tests.test_study_node_tools import DEVS, snp_graph
        self.pg = snp_graph()
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)
        import shutil
        from hazop.study import nodes as sn
        shutil.rmtree(os.path.join(sn.store_dir(), "SNP"), ignore_errors=True)

    def open_clean_sheet(self, win):
        self.switch_project(win, "SNP")
        self.js(win, "window.__hz.store.set({sheet: %s, panel: null})" % json.dumps(self.S101))
        win.engine.dispatch("sheet.open", {"graph_id": self.S101})
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('[data-view]') !== null") is True, 20))
        pump(1.0)

    def test_created_node_shows_its_tag_in_both_views_and_a_pick_selection_works_in_clean(self):
        from hazop.shell import api_nodes
        win = self.window()
        self.switch_project(win, "SNP")
        local = [n["local_id"] for n in self.pg["nodes"] if n.get("sheet") == self.S101][:6]
        rev = api_nodes.summary(win.engine)["set_rev"]
        r = win.engine.dispatch("nodes.create", {"project_id": "SNP", "set_rev": rev, "sheet": self.S101, "ids": local, "name": "구간 가"})
        self.assertTrue(r["ok"], r)
        self.open_clean_sheet(win)
        self.assertEqual(self.js(win, "document.querySelector('[data-view]').getAttribute('data-view')"), "clean")
        self.assertTrue(wait_for(lambda: "S1" in (self.js(win, "document.querySelector('.hz-cv-vp').textContent") or "") or
                                 (self.js(win, "document.querySelectorAll('.hz-cv-marks *').length") or 0) > 0, 15), "구간이 정리된 보기에도 그려진다")
        self.key_o(win)
        self.assertEqual(self.js(win, "document.querySelector('[data-view]').getAttribute('data-view')"), "orig")
        self.key_o(win)
        # 정리된 보기에서 네모 고르기 모드로 바꾸면 도구 막대가 눌린 상태이고 같은 저장소에 선택이 들어간다
        self.assertTrue(self.click(win, "button[aria-label^='네모로 고르기']"))
        pump(0.3)
        self.js(win, "(() => { const vp = document.querySelector('.hz-cv-vp'); const r = vp.getBoundingClientRect();"
                     "const ev = (t, x, y) => vp.dispatchEvent(new PointerEvent(t, {clientX: x, clientY: y, pointerId: 1, bubbles: true, button: 0, buttons: 1, isPrimary: true}));"
                     "ev('pointerdown', r.left + 5, r.top + 5); ev('pointermove', r.right - 5, r.bottom - 5); ev('pointerup', r.right - 5, r.bottom - 5); })()")
        self.assertTrue(wait_for(lambda: "개 고름" in self.text(win), 10), "정리된 보기에서도 고른 것 막대가 뜬다")
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])

    def key_o(self, win):
        self.js(win, "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'o', bubbles: true}))")
        pump(0.5)
