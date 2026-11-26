"""전체 되돌리기(Ctrl+Z): 사용자가 방금 한 행동을 하나씩 되돌린다. 실행: python -m unittest tests.test_shell_undo_flow

보기 동작(이동·확대, 도면 바꿈, 원본·정리, Ctrl 고름, 구간 고름)은 직전 상태로 돌아가고 Ctrl+Y·Ctrl+Shift+Z로 다시 한다.
저장되는 행동(구간 만들기·수정·지우기·이름, 도면 삭제)은 엔진의 되돌리기 길을 부른다. 입력 칸에 초점이 있으면 그 칸의 글자 되돌리기다.
"""

import json
import unittest

from tests.test_shell_edit_flow import PRESS_AT_ID, load_boxes
from tests.test_shell_view_flow import BADGES, PRESS_AT, ViewBase
from tests.test_shell_web import pump, wait_for

from hazop.shell import api_nodes

VIEW = "(() => { const w = document.querySelector('.hz-cv-world'); if (!w) return null; const m = /translate\\(([-\\d.]+)px, ([-\\d.]+)px\\) scale\\(([-\\d.]+)\\)/.exec(w.style.transform); return m ? [+m[1], +m[2], +m[3]] : null; })()"
KEY = "(([k, ctrl, shift]) => { (document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', {key: k, ctrlKey: ctrl, shiftKey: shift, bubbles: true, cancelable: true})); return true; })(%s)"
WHEEL_ONE = "(() => { const vp = document.querySelector('.hz-cv-vp'), v = vp.getBoundingClientRect(); vp.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, deltaY: -150, clientX: v.left + 200, clientY: v.top + 150})); return true; })()"
SETTLE = 1.3


class UndoBase(ViewBase):
    def start(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        self.js(win, "window.__ns = null; import('hazop-app://shell/js/panels/nodes_state.js').then((m) => { window.__ns = m; })")
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__ns") is True, 10))
        self.g1, self.g2 = self.gid["SNP-M-101"], self.gid["SNP-M-102"]
        pump(SETTLE)
        return win

    def view(self, win):
        return self.jsj(win, VIEW)

    def same_view(self, win, want, where):
        self.assertTrue(wait_for(lambda: self.view(win) is not None and all(abs(a - b) < 0.6 for a, b in zip(self.view(win)[:2], want[:2])) and abs(self.view(win)[2] - want[2]) < 0.002, 10),
                        "%s: %s != %s" % (where, self.view(win), want))

    def key(self, win, k, ctrl=True, shift=False):
        self.js(win, KEY % json.dumps([k, ctrl, shift]))
        pump(SETTLE)

    def undo(self, win):
        self.key(win, "z")

    def redo(self, win, shift=False):
        if shift:
            self.key(win, "Z", True, True)
        else:
            self.key(win, "y")

    def drag(self, win, dx):
        self.js(win, PRESS_AT % json.dumps([0.02, 0.95, dx, False]))
        pump(SETTLE)

    def picks(self, win):
        return sorted(i for p in self.jsj(win, "window.__ns.pickParts()") or [] for i in p["ids"])

    def summary(self, win):
        return {n["node_id"]: n for n in api_nodes.summary(win.engine)["nodes"]}

    def members(self, win, nid, number="SNP-M-101"):
        v = api_nodes.sheet_view(win.engine, self.gid[number])
        return sorted(next((s["ids"] for s in v["segments"] if s["node_id"] == nid), []))

    def ctrl_press(self, win, local):
        self.assertTrue(wait_for(lambda: self.js(win, PRESS_AT_ID % json.dumps([local, True])) is True, 20), local)
        pump(SETTLE)

    def pickable(self, win, count, skip=()):
        out = []
        for local in self.sheet_ids(win, "SNP-M-101"):
            if local in skip:
                continue
            self.js(win, "window.__ns.clearSelection()")
            pump(0.2)
            if self.js(win, PRESS_AT_ID % json.dumps([local, True])) is True:
                pump(0.3)
                if (self.jsj(win, "window.__ns.nodes.get().selection") or []) == [local]:
                    out.append(local)
            if len(out) == count:
                break
        self.js(win, "window.__ns.clearSelection()")
        pump(SETTLE)
        self.js(win, "import('hazop-app://shell/js/undo.js').then((m) => m.reset())")      # 누를 자리를 찾으며 한 것은 되돌리기에 남기지 않는다
        pump(0.5)
        return out


class ViewUndoTest(UndoBase):
    def test_pan_zoom_sheet_and_view_changes_come_back_one_step_at_a_time_and_redo(self):
        win = self.start()
        self.js(win, "import('hazop-app://shell/js/undo.js').then((m) => m.reset())")
        pump(0.5)
        v0 = self.view(win)
        self.drag(win, 140)
        v1 = self.view(win)
        self.assertNotEqual(v0, v1)
        for _ in range(4):
            self.js(win, WHEEL_ONE)
            pump(0.1)
        pump(SETTLE)
        v2 = self.view(win)
        self.assertNotAlmostEqual(v2[2], v1[2], 3)
        self.undo(win)
        self.same_view(win, v1, "휠 연속은 한 묶음")
        self.undo(win)
        self.same_view(win, v0, "끌기 한 번")
        self.redo(win)
        self.same_view(win, v1, "Ctrl+Y")
        self.redo(win, shift=True)
        self.same_view(win, v2, "Ctrl+Shift+Z")
        # 도면 바꿈: 칩으로 넘어간 것을 되돌리면 앞 도면의 보던 자리로
        self.click_chip(win, "SNP-M-102")
        pump(SETTLE)
        self.undo(win)
        self.ready(win, "SNP-M-101")
        self.same_view(win, v2, "도면 바꿈")
        self.open_row(win, "SNP-M-102")
        pump(SETTLE)
        self.undo(win)
        self.ready(win, "SNP-M-101")
        self.same_view(win, v2, "도면 줄 누름")
        # 원본·정리
        mode = "document.querySelector('.hz-cv').getAttribute('data-view')"
        was = self.js(win, mode)
        self.js(win, "[...document.querySelectorAll('.clean-toggle button')].find((b) => b.textContent.startsWith(%s)).click()" % json.dumps("원본" if was == "clean" else "정리"))
        self.assertTrue(wait_for(lambda: self.js(win, mode) != was, 10))
        pump(SETTLE)
        self.undo(win)
        self.assertTrue(wait_for(lambda: self.js(win, mode) == was, 10), "보기 바꿈")
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])


class PickUndoTest(UndoBase):
    def test_ctrl_picks_their_release_and_the_node_pick_come_back_and_inputs_keep_their_own_undo(self):
        win = self.start()
        nid = self.make_node(win, "되돌릴 구간", [("SNP-M-101", 3)], skip=6)
        load_boxes(self, win, "SNP-M-101")
        a, b = self.pickable(win, 2)
        self.ctrl_press(win, a)
        self.ctrl_press(win, b)
        self.assertEqual(self.picks(win), sorted([a, b]))
        self.undo(win)
        self.assertEqual(self.picks(win), [a], "Ctrl 고름 하나")
        self.undo(win)
        self.assertEqual(self.picks(win), [])
        self.redo(win)
        self.redo(win)
        self.assertEqual(self.picks(win), sorted([a, b]), "다시 하기")
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 0, False]))
        pump(SETTLE)
        self.assertEqual(self.picks(win), [])
        self.undo(win)
        self.assertEqual(self.picks(win), sorted([a, b]), "모두 풀린 것도 되돌린다")
        self.js(win, "window.__ns.clearSelection()")
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        pump(SETTLE)
        self.assertTrue(wait_for(lambda: self.js(win, "(() => { const b = document.querySelector('.nrow .nrow-b'); if (!b) return false; b.click(); return true; })()") is True, 20))
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [nid], 15))
        pump(SETTLE)
        self.undo(win)
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [] and self.js(win, "window.__ns.nodes.get().focus === null") is True, 10), "구간 고름")
        # 입력 칸의 Ctrl+Z는 그 칸의 글자 되돌리기: 앱은 아무것도 되돌리지 않고 기본 동작도 막지 않는다
        self.drag(win, 90)
        moved = self.view(win)
        prevented = self.js(win, """(() => { const t = document.querySelector('textarea, input.chat-input, .chat input, .chat textarea'); if (!t) return '입력 칸 없음'; t.focus();
          const e = new KeyboardEvent('keydown', {key: 'z', ctrlKey: true, bubbles: true, cancelable: true}); t.dispatchEvent(e); t.blur(); return e.defaultPrevented; })()""")
        self.assertIs(prevented, False, prevented)
        pump(SETTLE)
        self.same_view(win, moved, "입력 칸에서는 되돌리지 않는다")


class SavedUndoTest(UndoBase):
    def test_node_create_edit_rename_and_delete_and_drawing_delete_are_undone_through_the_engine(self):
        win = self.start()
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        pump(SETTLE)
        load_boxes(self, win, "SNP-M-101")
        a, b, c = self.pickable(win, 3)
        # 만들기: Ctrl 고름 → Enter. Ctrl+Z 한 번에 만든 것이 사라진다
        self.ctrl_press(win, a)
        self.ctrl_press(win, b)
        self.key(win, "Enter", ctrl=False)
        self.assertTrue(wait_for(lambda: len(self.summary(win)) == 1, 20))
        pump(SETTLE)
        nid = next(iter(self.summary(win)))
        self.js(win, "window.__ns.closeCard()")
        pump(SETTLE)
        # 수정: 고른 구간에 Ctrl로 더함 → Enter
        if self.js(win, "window.__ns.nodes.get().focus") != nid:
            self.js(win, "document.querySelector('.nrow .nrow-b').click()")
            pump(SETTLE)
        load_boxes(self, win, "SNP-M-101")
        before = self.members(win, nid)
        self.ctrl_press(win, c)
        self.key(win, "Enter", ctrl=False)
        self.assertTrue(wait_for(lambda: c in self.members(win, nid), 20))
        pump(SETTLE)
        self.undo(win)
        self.assertTrue(wait_for(lambda: self.members(win, nid) == before, 20), "수정 되돌리기 한 번: %s" % self.members(win, nid))
        # 이름
        old = self.summary(win)[nid]["name"]
        self.assertTrue(wait_for(lambda: self.js(win, "(() => { const x = document.querySelector('.ndetail button[aria-label=\"이름 고치기\"]'); if (!x) return false; x.click(); return true; })()") is True, 20))
        pump(0.5)
        self.js(win, "(() => { const el = document.activeElement; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, '바꾼 이름'); el.dispatchEvent(new Event('input', {bubbles: true})); })()")
        pump(0.2)
        self.key(win, "Enter", ctrl=False)
        self.assertTrue(wait_for(lambda: self.summary(win)[nid]["name"] == "바꾼 이름", 20))
        pump(SETTLE)
        self.undo(win)
        self.assertTrue(wait_for(lambda: self.summary(win)[nid]["name"] == old, 20), "이름 되돌리기")
        # 지우기: 둘을 휴지통으로 지우면 Ctrl+Z 한 번에 둘 다 돌아온다
        other = self.make_node(win, "둘째", [("SNP-M-101", 3)], skip=9)
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.nrow').length") == 2, 20))
        pump(SETTLE)
        self.js(win, "document.querySelector('.pwrap input[aria-label=\"구간 전체 선택\"]').click()")
        pump(SETTLE)
        self.js(win, "document.querySelector('.pwrap .picks button[aria-label=\"삭제\"]').click()")
        self.assertTrue(wait_for(lambda: len(self.summary(win)) == 0, 30))
        pump(SETTLE)
        self.undo(win)
        self.assertTrue(wait_for(lambda: sorted(self.summary(win)) == sorted([nid, other]), 30), "지운 둘을 한 번에: %s" % sorted(self.summary(win)))
        # 만들기까지 되돌리기: 앞에 쌓인 저장 행동을 차례로(이 구간의 만들기 묶음)
        # 도면 삭제 → Ctrl+Z로 되살리기
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        pump(SETTLE)
        count = "document.querySelectorAll('.drow input[type=checkbox]').length"
        self.assertEqual(self.js(win, count), 2)
        self.js(win, "[...document.querySelectorAll('.drow')].find((r) => r.textContent.includes('SNP-M-102')).querySelector('input[type=checkbox]').click()")
        pump(SETTLE)
        self.js(win, "document.querySelector('.pwrap .picks button[aria-label=\"삭제\"]').click()")
        self.assertTrue(wait_for(lambda: self.js(win, count) == 1, 30))
        pump(SETTLE)
        self.undo(win)
        self.assertTrue(wait_for(lambda: self.js(win, count) == 2, 30), "도면 삭제 되돌리기")
        from hazop.study import nodes as sn
        from hazop.app import project_ctx
        self.assertEqual(sn.exclusion_for(project_ctx.project_graph(win.engine.project_id()))[0], frozenset())
        self.assertEqual([x for x in win.view.page().console if x[0] >= 2], [])


class CreateUndoTest(UndoBase):
    def test_undo_right_after_creating_removes_the_node_in_one_step_then_goes_on_to_the_picks(self):
        win = self.start()
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        pump(SETTLE)
        load_boxes(self, win, "SNP-M-101")
        a, b = self.pickable(win, 2)
        self.ctrl_press(win, a)
        self.ctrl_press(win, b)
        self.key(win, "Enter", ctrl=False)
        self.assertTrue(wait_for(lambda: len(self.summary(win)) == 1, 20))
        pump(SETTLE)
        self.assertTrue(self.js(win, "!!document.querySelector('.newnode') && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)"), "만든 직후 카드는 열려 있고 초점은 입력 칸에 없다")
        self.undo(win)
        self.assertTrue(wait_for(lambda: len(self.summary(win)) == 0, 20), "카드가 열려 있어도 Ctrl+Z 한 번에 만든 구간이 사라진다")
        self.assertTrue(wait_for(lambda: self.js(win, "!document.querySelector('.newnode')") is True, 10), "카드도 닫힌다")
        self.undo(win)
        self.assertEqual(self.picks(win), [a], "그 앞의 행동(둘째 Ctrl 고름)")


if __name__ == "__main__":
    unittest.main()
