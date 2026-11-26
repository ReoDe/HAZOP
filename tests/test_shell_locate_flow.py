"""구성요소를 '찾아가는' 모든 길은 확대하지 않는다. 실행: python -m unittest tests.test_shell_locate_flow

어느 길이든 도면 한 장 전체가 가운데에 맞은 채로, 걸려 있던 강조(구간 고름·Ctrl 고름·앞선 강조)를 풀고 누른 대상만 일시 강조한다.
그 강조는 빈 곳 누름·Esc·다른 것 누름으로 풀린다.
"""

import json
import unittest

from tests.test_shell_view_flow import BADGES, PRESS_AT, PRESS_ID, ViewBase
from tests.test_shell_web import pump, wait_for

from hazop.shell import api

# 지금 도면에 일시 강조한 구성요소 id(정렬)
LIT = """(() => { const s = window.__hz.store.get(), out = new Set();
  for (const m of (s.marks.bySheet || {})[s.sheet] || []) { for (const g of m.groups || []) for (const i of g.ids || []) out.add(i); for (const p of m.steps || []) out.add(p.id); }
  return [...out].sort(); })()"""
VIEW = "(() => { const w = document.querySelector('.hz-cv-world'); return w ? w.style.transform : ''; })()"
MODULES = {"R": "panels/results_state.js", "N": "panels/nodes_state.js", "K": "panels/kg_state.js", "IE": "panels/ie_judge.js", "LOG": "panels/actionlog.js",
           "CHAT": "chat/actions.js", "AI": "panels/aireview_state.js", "Q": "queue/queue.js", "CL": "canvas/clean_ui.js"}


class LocateBase(ViewBase):
    def start(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        for name, path in MODULES.items():
            self.js(win, "import('hazop-app://shell/js/%s').then((m) => { (window.__m = window.__m || {}).%s = m; })" % (path, name))
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__m && Object.keys(window.__m).length === %d" % len(MODULES)) is True, 15), "모듈")
        self.g1, self.g2 = self.gid["SNP-M-101"], self.gid["SNP-M-102"]
        self.ids = {n: self.sheet_ids(win, n) for n in ("SNP-M-101", "SNP-M-102")}
        self.node = self.make_node(win, "미리 고른 구간", [("SNP-M-101", 3)], skip=6)
        self.assertTrue(wait_for(lambda: self.js(win, "window.__m.N.nodes.get().list.nodes.length") == 1, 20))
        return win

    def dirty(self, win):
        """앞선 강조를 걸어 둔다: 구간 고름, 다른 도면의 Ctrl 고름, 앞선 일시 강조."""
        self.js(win, "window.__m.N.nodes.set({focus: %s, picks: {[%s]: [%s]}}); window.__hz.store.set({marks: {rid: 'old', bySheet: {[window.__hz.store.get().sheet]: [{id: 'old', op: 'mark', groups: [{ids: [%s], style: 'focus'}]}]}}})"
                % (json.dumps(self.node), json.dumps(self.g2), json.dumps(self.ids["SNP-M-102"][5]), json.dumps(self.ids["SNP-M-101"][8])))
        pump(0.4)

    def located(self, win, where, number, expected, node=None):
        gid = self.gid[number]
        self.assertTrue(wait_for(lambda: self.sheet(win) == gid and self.jsj(win, LIT) == sorted(expected), 20),
                        "%s: 도면 %s, 강조 %s (기대 %s)" % (where, self.sheet(win), self.jsj(win, LIT), sorted(expected)))
        pump(1.2)
        self.fitted(win, where + ": 전체 맞춤 배율")
        self.assertEqual(self.jsj(win, "window.__m.N.pickParts()"), [], where + ": 앞선 Ctrl 고름이 남지 않는다")
        self.assertEqual(self.js(win, "window.__m.N.nodes.get().focus || ''"), node or "", where + ": 앞선 구간 고름이 남지 않는다")
        if not node:
            self.assertEqual(self.jsj(win, BADGES), [], where + ": 구간 강조 0")

    def back_to(self, win, number="SNP-M-101"):
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        self.open_row(win, number)
        self.zoom_away(win)

    def card(self, win, local):
        card = {"badges": [], "text": "", "path_notes": [], "warnings": [], "model_warnings": [], "general": "", "no_evidence": False,
                "paths": [{"label": "경로 1", "chips": [{"tag": "대상", "sheet": self.g2, "local_id": local}],
                           "sheets": [[self.g2, 2]], "sheet_labels": {self.g2: "SNP-M-102"},
                           "marks": {self.g2: [{"op": "path", "style": "path", "numbered": True,
                                                "steps": [{"id": i, "flow": None} for i in self.ids["SNP-M-102"][:2]]}]}}]}
        self.js(win, "window.__hz.store.set((s) => ({chatCollapsed: false, chat: Object.assign({}, s.chat, {msgs: [{key: 'k1', kind: 'answer', card: %s, footer: {tools: 0, model: 'x', seconds: 1, notes: [], calls: []}}]})}))" % json.dumps(card))
        pump(0.6)


class LocateEveryWayTest(LocateBase):
    def test_every_way_of_going_to_a_component_keeps_the_whole_sheet_and_lights_only_the_target(self):
        win = self.start()
        t1, t2 = self.ids["SNP-M-102"][0], self.ids["SNP-M-102"][1]
        mark = lambda ids: {self.g2: [{"op": "mark", "groups": [{"ids": ids, "style": "focus"}], "dim_others": True}]}
        self.card(win, t1)
        calls = [
            ("채팅 답의 구성요소 칩", "document.querySelector('.ans .steps .chip, .ans .steps button').click()", [t1]),
            ("채팅 답의 도면 칩", "[...document.querySelectorAll('.ans .sheets .chip, .ans .sheets button')].find((b) => b.textContent.includes('SNP-M-102')).click()", [t1, t2]),
            ("채팅의 도면에 보이기", "window.__m.CHAT.applyDisplay({op: 'show', ok: true, sheet: %s, ids: [%s], marks: %s}, 'disp:1')" % (json.dumps(self.g2), json.dumps(t2), json.dumps(mark([t2]))), [t2]),
            ("지식그래프의 도면에서 보기", "window.__m.K.showOnSheet({sheet: %s, local_id: %s})" % (json.dumps(self.g2), json.dumps(t1)), [t1]),
            ("초기사건 추적", "window.__m.IE.go({kind: 'location', sheet: %s, marks: %s}, {})" % (json.dumps(self.g2), json.dumps(mark([t2]))), [t2]),
            ("분석 결과의 근거 경로", "window.__m.R.showBasisPath({sheet: %s, marks: %s})" % (json.dumps(self.g2), json.dumps(mark([t1, t2]))), [t1, t2]),
            ("실행 기록의 구성요소", "window.__m.LOG.go({kind: 'component', sheet: %s, local_id: %s})" % (json.dumps(self.g2), json.dumps(t1)), [t1]),
            ("AI 후보 자리", "window.__m.AI.ai.set({graphId: %s}); window.__m.AI.showOnSheet({local_id: %s, cand_id: 'c', field_label: 'f'})" % (json.dumps(self.g2), json.dumps(t2)), [t2]),
        ]
        for where, code, expected in calls:
            self.back_to(win)
            self.dirty(win)
            self.js(win, code)
            self.located(win, where, "SNP-M-102", expected)
            # 같은 도면에서 확대해 둔 채 다시 누르면 전체 맞춤으로 돌아온다
            self.zoom_away(win)
            self.dirty(win)
            self.js(win, code)
            self.located(win, where + "(같은 도면)", "SNP-M-102", expected)
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [], "웹 콘솔 오류 없음")


class LocateReleaseTest(LocateBase):
    def test_the_temporary_highlight_goes_away_on_a_blank_press_escape_or_another_target(self):
        win = self.start()
        t1, t2 = self.ids["SNP-M-102"][0], self.ids["SNP-M-102"][1]
        show = lambda i: self.js(win, "window.__m.K.showOnSheet({sheet: %s, local_id: %s})" % (json.dumps(self.g2), json.dumps(i)))
        show(t1)
        self.located(win, "처음", "SNP-M-102", [t1])
        pump(2.5)
        self.assertEqual(self.jsj(win, LIT), [t1], "시간이 지나도 저절로 사라지지 않는다")
        show(t2)
        self.located(win, "다른 대상", "SNP-M-102", [t2])
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 40, False]))
        pump(0.5)
        self.assertEqual(self.jsj(win, LIT), [t2], "도면을 끄는 것은 풀지 않는다")
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 0, False]))
        self.assertTrue(wait_for(lambda: self.jsj(win, LIT) == [], 10), "빈 곳 누름")
        show(t1)
        self.located(win, "다시", "SNP-M-102", [t1])
        self.js(win, "document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}))")
        self.assertTrue(wait_for(lambda: self.jsj(win, LIT) == [], 10), "Esc")
        show(t1)
        self.located(win, "머리 줄 전", "SNP-M-102", [t1])
        self.js(win, "(() => { const h = document.querySelector('header') || document.body; for (const t of ['pointerdown', 'pointerup']) h.dispatchEvent(new PointerEvent(t, {bubbles: true, clientX: 300, clientY: 5, button: 0})); })()")
        self.assertTrue(wait_for(lambda: self.jsj(win, LIT) == [], 10), "도면 바깥 누름")


class LocateKeysTest(LocateBase):
    def test_member_chips_the_trace_button_double_click_and_f_do_not_zoom_in_and_there_is_no_unread_popup_or_n_key(self):
        win = self.start()
        # 못 읽은 곳 말풍선과 N·Shift+N은 없다(잘못 읽은 것은 채팅으로 고친다). 빨간 추출 네모는 남는다
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__m.CL.clean.get().data[%s]" % json.dumps(self.g1)) is True, 30))
        unread = self.jsj(win, "window.__m.CL.clean.get().data[%s].unconfirmed.map((u) => u.id)" % json.dumps(self.g1))
        self.assertTrue(unread, "시험 자료: 읽지 못한 곳")
        reds = "[...document.querySelectorAll('.hz-cv-marks [data-check]')].filter((e) => (e.getAttribute('stroke') || '').includes('chk-unknown')).length"
        self.assertTrue(wait_for(lambda: (self.js(win, reds) or 0) > 0, 20), "못 읽은 구성요소의 빨간 추출 네모")
        self.zoom_away(win)
        before = self.js(win, VIEW)
        for shift in ("false", "true"):
            self.js(win, "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'n', shiftKey: %s, bubbles: true}))" % shift)
        pump(1.0)
        self.assertEqual((self.js(win, VIEW), self.jsj(win, LIT)), (before, []), "N 키는 아무 일도 하지 않는다")
        self.assertFalse(self.js(win, "!!document.querySelector('.cleanpop')"))
        # 못 읽은 구성요소를 눌러도 뜨는 것은 속성 말풍선 하나뿐
        self.back_to(win)
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        pressed = None
        for local in unread:
            if self.js(win, PRESS_ID % json.dumps([local, False])) is True:
                pump(0.8)
                if self.js(win, "(window.__hz.store.get().bubble || {}).id") == local:
                    pressed = local
                    break
        self.assertTrue(pressed, "못 읽은 구성요소를 누름")
        self.assertEqual(self.js(win, "document.querySelectorAll('.cleanpop').length"), 0)
        self.assertEqual(self.js(win, "document.querySelectorAll('.float.bubble').length"), 1, "말풍선은 하나")
        self.assertGreater(self.js(win, reds), 0)
        self.js(win, "window.__hz.store.set({bubble: null, panel: 'drawings'})")
        # 구간 상세의 구성요소 칩(다른 도면의 것도 그 도면으로 가서)
        other = self.make_node(win, "두 도면", [("SNP-M-101", 2), ("SNP-M-102", 1)])
        self.js(win, "window.__hz.store.set({panel: 'nodes'}); window.__m.N.nodes.set({scope: 'all'})")
        self.assertTrue(wait_for(lambda: self.js(win, "window.__m.N.nodes.get().list.nodes.length") == 2, 20))
        pump(0.8)
        self.js(win, "window.__m.N.focusNode(%s)" % json.dumps(other))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.memlist .chip').length") or 0) >= 3, 20))
        self.zoom_away(win)
        members = self.jsj(win, "window.__m.N.nodes.get().detail.members.map((m) => [m.sheet, m.id])")
        at = next(i for i, (sheet, _id) in enumerate(members) if sheet == self.g2)
        self.js(win, "(() => { const d = document.querySelector('.memlist').closest('details'); d.open = true; document.querySelectorAll('.memlist .chip')[%d].click(); })()" % at)
        self.located(win, "구간 상세의 구성요소 칩", "SNP-M-102", [members[at][1]])
        # 두 번 누르기는 확대하지 않는다
        self.back_to(win)
        self.js(win, PRESS_AT % json.dumps([0.5, 0.5, 0, False]))
        before = self.js(win, VIEW)
        local = self.ids["SNP-M-101"][0]
        self.js(win, "(() => { const el = document.querySelector('.hz-cv-marks [data-check=\"%s\"]'), r = el.getBoundingClientRect(); document.querySelector('.hz-cv-vp').dispatchEvent(new MouseEvent('dblclick', {bubbles: true, cancelable: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2})); })()" % local)
        pump(0.8)
        self.assertEqual(self.js(win, VIEW), before, "두 번 눌러도 보기가 그대로")
        # F: 고른 것으로 확대하지 않고 전체 맞춤(고름은 그대로)
        self.js(win, "window.__hz.store.set({bubble: null})")
        self.assertTrue(wait_for(lambda: self.js(win, PRESS_ID % json.dumps([local, True])) is True, 10))
        pump(0.5)
        picked = self.jsj(win, "window.__m.N.nodes.get().selection")
        self.assertTrue(picked)
        self.zoom_away(win)
        self.js(win, "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'f', bubbles: true}))")
        self.fitted(win, "F")
        self.assertEqual(self.jsj(win, "window.__m.N.nodes.get().selection"), picked, "F는 고름을 풀지 않는다")
        # 속성 말풍선의 '분석 결과 추적': 그 구성요소만 강조하고 확대하지 않는다
        self.js(win, "window.__m.N.clearSelection()")
        pump(0.3)
        self.zoom_away(win)
        self.js(win, "window.__hz.store.set({bubble: {sheet: %s, id: %s, tag: 'X', kind: 'x', kind_label: '기기', rect: {x: 300, y: 300, w: 20, h: 20}, view: {x: 0, y: 0, k: 1}}})" % (json.dumps(self.g1), json.dumps(local)))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector(\"button[aria-label='분석 결과 추적']\")") is True, 10))
        self.dirty(win)
        self.js(win, "document.querySelector(\"button[aria-label='분석 결과 추적']\").click()")
        self.assertTrue(wait_for(lambda: self.jsj(win, LIT) == [local], 10), "추적한 구성요소만: %s" % self.jsj(win, LIT))
        self.assertEqual(self.jsj(win, "window.__m.N.pickParts()"), [])
        self.assertEqual(self.js(win, "window.__m.N.nodes.get().focus || ''"), "")


class LocateNodeTest(LocateBase):
    def test_viewing_a_node_from_the_results_clears_other_highlights_and_keeps_the_whole_sheet(self):
        win = self.start()
        self.back_to(win, "SNP-M-102")
        self.dirty(win)
        self.js(win, "window.__m.N.nodes.set({focus: null})")
        self.js(win, "window.__m.R.viewOnSheet(%s)" % json.dumps(self.node))
        self.located(win, "분석 결과의 도면에서 보기", "SNP-M-101", [], node=self.node)
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [self.node], 15), "그 구간만 강조")


if __name__ == "__main__":
    unittest.main()
