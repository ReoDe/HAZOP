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
from tests.test_shell_web import ShellBase, pump, wait_for, shell_teardown as tearDownModule  # noqa: F401

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
        self.assertTrue(wait_for(lambda: "노드" in (self.js(win, "(document.querySelector('.kg-chips')||{}).innerText") or ""), 10))

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

    def test_tag_and_document_names_are_text_not_html(self):
        """검토 차단 2: 이름표(라이브러리가 innerHTML로 넣는 말풍선)와 상세에 도면 태그·문서 이름이 HTML로 해석되지 않는다."""
        evil_style = "<style>.kg-judge{display:none}</style>RC-STY"
        evil_img = "<img src=x onerror=\"window.__pwned=1\">RC-IMG"
        kg = {"kg_version": "v-evil", "nodes": [
            {"id": "evil-1", "node_type": "requirement", "name": evil_style, "knowledge_status": "confirmed"},
            {"id": "evil-2", "node_type": "requirement", "name": evil_img, "knowledge_status": "unknown"}], "links": []}
        with mock.patch.object(api_kg, "_load_kg", lambda pid: (kg, None)):
            api_kg._CACHE.clear()
            win = self.window()
            self.mount(win)
            labels = self.jsj(win, "window.__hzKg.graphData().nodes.filter((n) => n.id.startsWith('kn:evil')).map((n) => window.__hzKg.nodeLabel()(n))")
            self.assertEqual(len(labels), 2, labels)
            self.assertTrue(all("<" not in x and "&lt;" in x for x in labels), labels)
            styles = self.js(win, "document.querySelectorAll('style').length")
            self.js(win, "import(new URL('js/panels/kg_state.js', document.baseURI).href).then((K) => K.select('kn:evil-1'))")
            self.assertTrue(wait_for(lambda: "RC-STY" in (self.js(win, "(document.querySelector('.kg-side')||{}).innerText") or ""), 10))
            self.assertIn("<style>", self.js(win, "document.querySelector('.kg-side').innerText"))       # 글자 그대로 보인다
            self.js(win, "import(new URL('js/panels/kg_state.js', document.baseURI).href).then((K) => K.select('kn:evil-2'))")
            self.assertTrue(wait_for(lambda: "RC-IMG" in (self.js(win, "(document.querySelector('.kg-side')||{}).innerText") or ""), 10))
            pump(0.5)
            self.assertEqual(self.js(win, "document.querySelectorAll('style').length"), styles)
            self.assertEqual(self.js(win, "document.querySelectorAll('.kg img').length"), 0)
            self.assertEqual(self.js(win, "String(window.__pwned)"), "undefined")

    def test_node_picked_before_layout_settles_ends_up_in_view(self):
        """다른 패널(설계 문서 '지식그래프에서 보기')이나 채팅이 패널을 열자마자 노드를 고르면, 배치가 멈춘 뒤 그 노드가 화면 가운데 근처에 있다."""
        win = self.window()
        pg = __import__("hazop.app.project_ctx", fromlist=["x"]).project_graph(win.engine.project_id())
        nid = sorted(n["entity_id"] for n in pg["nodes"] if n.get("tag") and n.get("local_id") and n.get("node_type") == "drawing_object")[-1]
        self.js(win, MOUNT)
        self.js(win, "import(new URL('js/panels/kg_state.js', document.baseURI).href).then(async (K) => { await K.loadSummary(); await K.focus(%s); })"
                % json.dumps(nid))
        where = "JSON.stringify((() => { const g = window.__hzKg; if (!g) return null; const n = g.graphData().nodes.find((x) => x.id === %s); if (!n || n.x === undefined) return null; const c = document.querySelector('.kg-canvas').getBoundingClientRect(); const p = g.graph2ScreenCoords(n.x, n.y); return [p.x / c.width, p.y / c.height]; })())" % json.dumps(nid)
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__hzKg && window.__hzKg.__running === false && !window.__hzKg.__centerAfter"), 60),
                        "배치가 멈추지 않음")
        pump(1.0)                                     # 가운데 맞추기 움직임(0.5초)이 끝나게
        pos = json.loads(self.js(win, where) or "null")
        self.assertIsNotNone(pos)
        self.assertTrue(0.25 < pos[0] < 0.75 and 0.25 < pos[1] < 0.75, pos)

    def test_labels_show_at_fit_zoom_without_overlap(self):
        """맞춤 배율에서도 큰 노드(설비·문서)의 이름이 보이고, 그린 이름표끼리 겹치지 않는다."""
        win = self.window()
        self.mount(win)
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__hzKg && window.__hzKg.__running === false"), 60))
        self.js(win, "window.__hzKg.zoomToFit(0, 40)")
        pump(1.0)
        boxes = self.jsj(win, "window.__hzKg.__labels") or []
        self.assertGreater(len(boxes), 0)
        overlap = [(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:] if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]]
        self.assertEqual(overlap, [])

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

    def pick_explore(self, win, what):
        self.js(win, "(() => { const s = document.querySelector('.kg-explore-pick'); s.value = %s; s.dispatchEvent(new Event('change', {bubbles: true})); })()"
                % json.dumps(what))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.kg-explore')"), 15), "살펴보기 결과 줄이 나오지 않음")
        return self.js(win, "document.querySelector('.kg-explore').innerText")

    def test_explore_menu_highlights_what_the_engine_counted(self):
        """완료 목록 3 B6: '살펴보기'에서 고르면 엔진이 센 건수가 보이고 그 노드가 강조된다. 고른 구성요소 없이 도달 범위를 고르면 사유가 나온다."""
        win = self.window()
        self.mount(win)
        for what, label in (("orphans", "고아 지식"), ("gaps", "근거 공백")):
            text = self.pick_explore(win, what)
            self.assertIn(label, text)
            r = api_kg.explore(win.engine, what)
            if r["active"]:
                self.assertIn("%s곳" % format(r["count"], ","), text)
            else:
                self.assertIn(r["reason"][:20], text)
        text = self.pick_explore(win, "reach")
        self.assertIn("고르면", text)
        self.click(win, ".kg-explore button")
        self.assertTrue(wait_for(lambda: not self.js(win, "!!document.querySelector('.kg-explore')"), 10))
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])

    def test_study_toggle_and_link_detail(self):
        """완료 목록 3 B6: '검토 결과'를 켜면 검토 층을 엔진에서 다시 읽고, 선을 누르면 오른쪽에 그 선의 근거가 나온다."""
        win = self.window()
        self.mount(win)
        btn = "[...document.querySelectorAll('.kg-tools button')].find((b) => b.innerText.trim() === '검토 결과')"
        self.js(win, btn + ".click()")
        self.assertTrue(wait_for(lambda: self.js(win, btn + ".getAttribute('aria-pressed')") == "true", 10))
        self.assertTrue(wait_for(lambda: "검토 결과:" in self.text(win), 10), self.text(win)[-300:])
        lid = self.js(win, "(() => { const l = window.__hzKg.graphData().links.find((x) => x.kind === 'pipe'); return l && l.id; })()")
        self.assertTrue(lid)
        self.js(win, "import(new URL('js/panels/kg_state.js', document.baseURI).href).then((K) => K.selectLink(%s))" % json.dumps(lid))
        self.assertTrue(wait_for(lambda: "배관" in (self.js(win, "(document.querySelector('.kg-side')||{}).innerText") or ""), 10))
        side = self.js(win, "document.querySelector('.kg-side').innerText")
        self.assertIn("근거", side)
        self.assertIn("→", side)
        self.js(win, btn + ".click()")
        self.assertTrue(wait_for(lambda: self.js(win, btn + ".getAttribute('aria-pressed')") == "false", 10))
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])


if __name__ == "__main__":
    unittest.main()
