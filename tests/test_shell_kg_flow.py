"""지식그래프 패널을 실제 틀 창(ShellWindow, 오프스크린)에 임시로 이어 본다. 실행: python -m unittest tests.test_shell_kg_flow

패널 등록 줄(api.py의 kg 읽기·명령 등록, main.js의 메뉴)은 틀 담당(s-frame)이 넣는다. 그 전에도 확인할 수 있게 이 시험은 읽기 API에 kg 길을,
명령 표에 kg.* 를 시험 안에서만 잇고, 패널은 웹에서 모듈을 읽어 화면 가운데에 따로 그린다. 등록 줄이 들어오면 같은 시험이 그대로 통한다.
샘플 SNP-M-101·102(가상 도면)를 임시 작업 루트에 추출한다. 실제 창 조작은 없다.
"""

import json
import os
import unittest
from unittest import mock

from hazop.kg import expect
from hazop.shell import api, api_kg
from tests.test_shell_web import ShellBase, pump, wait_for

MOUNT = """(async () => {
  if (!document.querySelector('.kg')) {
    const H = await import(new URL('js/ui/html.js', document.baseURI).href);
    const M = await import(new URL('js/panels/kg.js', document.baseURI).href);
    const host = document.createElement('div'); host.id = 'kg-host';
    document.querySelector('.center').appendChild(host);
    H.render(H.html`<${M.KgPanel} onClose=${() => { H.render(null, host); }} />`, host);
  }
  return true; })()"""


class KgPanelFlowTest(ShellBase):
    def setUp(self):
        real = api.ReadApi.read

        def read(this, parts, query):
            if parts and parts[0] == "kg":
                return api_kg.read(this.engine, parts, query)
            return real(this, parts, query)
        for p in (mock.patch.object(api.ReadApi, "read", read), mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        if "kg.judge" not in api.COMMANDS:
            api_kg.register(api.COMMANDS)
        expect._EVALUATED[:] = []
        api_kg._CACHE.clear()

    def mount(self, win):
        self.js(win, MOUNT)
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.kg .kg-canvas canvas')"), 20), "그래프가 그려지지 않음")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.kg-chips .chip').length") or 0) >= 3, 10))

    def search_and_pick(self, win, text):
        self.js(win, "(() => { const i = document.querySelector('.kg-search input'); i.value = %s; i.dispatchEvent(new Event('input', {bubbles: true})); })()" % json.dumps(text))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.kg-hit').length") or 0) > 0, 10), "찾은 것이 없음: " + text)
        self.click(win, ".kg-hit")
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.kg-side .kg-dh')"), 10))

    def test_open_pick_judge_and_undo(self):
        win = self.window()
        self.mount(win)
        text = self.text(win)
        self.assertIn("지식그래프", text)
        self.assertIn("잠재 후보 공백", text)
        # 도면 노드를 고르면 근거와 '도면에서 보기'가 나온다
        pg = __import__("hazop.app.project_ctx", fromlist=["x"]).project_graph(win.engine.project_id())
        tag = next(n["tag"] for n in pg["nodes"] if n.get("tag") and n.get("category") == "equipment" and n.get("local_id"))
        self.search_and_pick(win, tag)
        side = self.js(win, "document.querySelector('.kg-side').innerText")
        self.assertIn("근거", side)
        self.assertIn("도면에서 보기", side)
        # 잠재 후보 하나를 골라 판단하고 되돌린다
        m = api_kg._context(win.engine)[0]
        item = next(i for i in m["expectations"]["items"] if i["state"] == "candidate_found" and i["target_entity"] in m["model"]["nodes"])
        self.js(win, "import(new URL('js/panels/kg_state.js', document.baseURI).href).then((K) => K.focus(%s))" % json.dumps(item["id"]))
        self.assertTrue(wait_for(lambda: "후보 확인" in (self.js(win, "document.querySelector('.kg-side').innerText") or ""), 10))
        self.click(win, ".kg-judge .btn.primary")
        self.assertTrue(wait_for(lambda: "판단을 저장했습니다" in self.text(win), 10), self.text(win)[-400:])
        self.assertTrue(wait_for(lambda: "판단 되돌리기" in (self.js(win, "document.querySelector('.kg-side').innerText") or ""), 10))
        pid = win.engine.project_id()
        rec = expect.load_judgements(expect.store_path(pid), pid)[item["key"]]
        self.assertEqual((rec["state"], rec["by"]), ("confirmed_present", "검토자A"))
        self.click(win, ".kg-judge .btn")
        self.assertTrue(wait_for(lambda: expect.load_judgements(expect.store_path(pid), pid)[item["key"]]["action"] == "undo", 10))
        self.assertTrue(wait_for(lambda: "후보 확인" in (self.js(win, "document.querySelector('.kg-side').innerText") or ""), 10))

    def test_show_on_sheet_closes_panel_and_opens_that_drawing(self):
        win = self.window()
        self.mount(win)
        pg = __import__("hazop.app.project_ctx", fromlist=["x"]).project_graph(win.engine.project_id())
        n = next(x for x in pg["nodes"] if x.get("tag") and x.get("local_id") and x.get("sheet"))
        self.search_and_pick(win, n["tag"])
        self.js(win, "import(new URL('js/panels/kg_state.js', document.baseURI).href).then((K) => K.showOnSheet(K.kg.get().detail.at))")
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().sheet") == n["sheet"], 10))
        self.assertEqual(self.js(win, "window.__hz.store.get().command.type"), "zoomTo")

    def test_chat_open_event_opens_the_panel_state(self):
        win = self.window()
        self.js(win, "import(new URL('js/panels/kg_state.js', document.baseURI).href)")
        pump(0.5)
        api_kg.open_panel(win.engine)
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().panel") == "kg", 10))

    def test_no_console_errors_or_remote_requests_while_drawing(self):
        win = self.window()
        self.mount(win)
        self.search_and_pick(win, "P")
        pump(1.5)
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])
        self.assertEqual(win.view.interceptor.blocked, [], "실행 중 원격 요청 0")


if __name__ == "__main__":
    unittest.main()
