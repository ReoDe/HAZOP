"""구간 상세: 그 자리에서 바로 고치기, 사람이 쓰는 것만 남긴 상세, 묶음 되돌리기는 설정의 작업 기록.
실행: python -m unittest tests.test_shell_detail_flow
"""

import json
import unittest

from tests.test_shell_view_flow import BADGES, ViewBase
from tests.test_shell_web import pump, wait_for

from hazop.shell import api_nodes

# 값을 넣고 입력 사건을 보낸다(지금 초점이 있는 칸)
TYPE = """((v) => { const el = document.activeElement; if (!el || !/INPUT|TEXTAREA/.test(el.tagName)) return false;
  const set = Object.getOwnPropertyDescriptor(el.tagName === 'INPUT' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype, 'value').set; set.call(el, v);
  el.dispatchEvent(new Event('input', {bubbles: true})); return true; })(%s)"""
KEY = "(([k, ctrl]) => { (document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', {key: k, ctrlKey: ctrl, bubbles: true, cancelable: true})); return true; })(%s)"


class DetailBase(ViewBase):
    def start(self, *nodes):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        ids = [self.make_node(win, name, parts, skip=skip) for name, parts, skip in nodes]
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.nrow').length") == len(ids), 30))
        pump(0.8)
        return win, ids

    def row(self, win, nid):
        return next(n for n in api_nodes.summary(win.engine)["nodes"] if n["node_id"] == nid)

    def intent(self, win, nid):
        return (self.row(win, nid).get("design_intent") or {}).get("text") or ""

    def focus(self, win, nid):
        js = "(() => { const b = [...document.querySelectorAll('.nrow .nrow-b')].find((x) => x.getAttribute('aria-label').startsWith(%s)); if (!b) return false; if (b.getAttribute('aria-pressed') !== 'true') b.click(); return true; })()"
        self.assertTrue(wait_for(lambda: self.js(win, js % json.dumps(nid + " ")) is True, 20), nid)
        self.assertTrue(wait_for(lambda: self.js(win, "(() => { const d = document.querySelector('.ndetail'); return !!d && d.getAttribute('aria-label') === %s; })()" % json.dumps(nid + " 상세")) is True, 20))
        pump(1.0)

    def pencil(self, win, label):
        self.assertTrue(wait_for(lambda: self.js(win, "(() => { const b = document.querySelector('.ndetail button[aria-label=\"%s 고치기\"]'); if (!b || b.disabled) return false; b.click(); return true; })()" % label) is True, 10),
                        label + " 연필")
        tag = "TEXTAREA" if label == "설계 의도" else "INPUT"
        self.assertTrue(wait_for(lambda: self.js(win, "document.activeElement && document.activeElement.tagName === %s && document.activeElement.getAttribute('aria-label') === %s" % (json.dumps(tag), json.dumps(label))) is True, 10),
                        label + ": 그 자리에 입력 칸이 뜨고 초점이 간다")

    def type(self, win, text):
        self.assertTrue(self.js(win, TYPE % json.dumps(text)))
        pump(0.2)

    def key(self, win, key, ctrl=False):
        self.js(win, KEY % json.dumps([key, ctrl]))
        pump(0.4)

    def editing(self, win):
        return self.js(win, "document.querySelectorAll('.ndetail input.textbox, .ndetail textarea.textbox').length")


class InlineEditTest(DetailBase):
    def test_the_pencils_edit_in_place_enter_ctrl_enter_and_leaving_save_and_escape_discards(self):
        win, (a, b) = self.start(("첫 구간", [("SNP-M-101", 3)], 0), ("둘째 구간", [("SNP-M-101", 3)], 3))
        # 옛 확정 기록이 있는 구간도 바로 고친다(사용자가 본 화면에서 아무 일도 없던 까닭)
        self.cmd(win, "nodes.confirm", {"project_id": win.engine.project_id(), "set_rev": api_nodes.summary(win.engine)["set_rev"], "node_ids": [a],
                                        "targets": [{"node_id": a, "rev": self.row(win, a)["rev"], "state": "applied"}]})
        win.engine.changed("nodes")
        pump(1.0)
        self.focus(win, a)
        self.pencil(win, "이름")
        self.assertFalse(self.js(win, "[...document.querySelectorAll('.ndetail .field button')].some((x) => /저장|취소/.test(x.textContent))"), "저장·취소 단추 없이 그 자리에서")
        self.type(win, "고친 이름")
        self.key(win, "Enter")
        self.assertTrue(wait_for(lambda: self.row(win, a)["name"] == "고친 이름", 15), "Enter로 저장")
        self.assertEqual(self.editing(win), 0)
        self.pencil(win, "이름")
        self.type(win, "버릴 이름")
        self.key(win, "Escape")
        pump(0.8)
        self.assertEqual((self.row(win, a)["name"], self.editing(win)), ("고친 이름", 0), "Esc는 버린다")
        self.assertEqual(self.js(win, "(document.querySelector('.ndetail') || {getAttribute: () => ''}).getAttribute('aria-label')"), a + " 상세", "Esc가 구간 고름까지 풀지 않는다")
        self.pencil(win, "이름")
        self.type(win, "바깥을 눌러 저장")
        self.js(win, "document.activeElement.blur()")
        self.assertTrue(wait_for(lambda: self.row(win, a)["name"] == "바깥을 눌러 저장", 15), "바깥 누름으로 저장")
        self.pencil(win, "설계 의도")
        self.type(win, "첫 줄")
        self.key(win, "Enter")
        pump(0.5)
        self.assertEqual((self.intent(win, a), self.editing(win)), ("", 1), "설계 의도의 Enter는 줄 바꿈이라 저장하지 않는다")
        self.type(win, "냉각재를 보낸다")
        self.key(win, "Enter", True)
        self.assertTrue(wait_for(lambda: self.intent(win, a) == "냉각재를 보낸다", 15), "Ctrl+Enter로 저장")
        self.pencil(win, "설계 의도")
        self.type(win, "버릴 의도")
        self.key(win, "Escape")
        pump(0.8)
        self.assertEqual(self.intent(win, a), "냉각재를 보낸다")
        self.pencil(win, "설계 의도")
        self.type(win, "바깥에서 저장한 의도")
        self.js(win, "document.activeElement.blur()")
        self.assertTrue(wait_for(lambda: self.intent(win, a) == "바깥에서 저장한 의도", 15))
        # 고치다가 다른 구간을 고르면 그 글이 다른 구간에 들어가지 않는다
        self.pencil(win, "이름")
        self.type(win, "첫 구간에 쓰던 글")
        self.focus(win, b)
        self.assertEqual(self.editing(win), 0, "다른 구간의 상세는 고치는 중이 아니다")
        self.key(win, "Enter")
        pump(1.0)
        self.assertEqual(self.row(win, b)["name"], "둘째 구간", "다른 구간에 저장되지 않는다")
        self.assertIn(self.row(win, a)["name"], ("바깥을 눌러 저장", "첫 구간에 쓰던 글"))
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])


DETAIL = """(() => { const d = document.querySelector('.ndetail'); if (!d) return null;
  return {text: d.innerText, labels: [...d.querySelectorAll('.field > label, .field > summary')].map((x) => x.textContent.trim()),
          sheets: [...d.querySelectorAll('[aria-label="도면별로 보기"] button')].map((b) => b.textContent.trim()),
          open: [...d.querySelectorAll('details')].map((x) => x.open)}; })()"""


class SlimDetailTest(DetailBase):
    def test_the_detail_keeps_what_people_use_and_the_batch_history_moves_to_the_settings(self):
        win, (a, b) = self.start(("두 도면 구간", [("SNP-M-101", 3), ("SNP-M-102", 4)], 0), ("한 도면 구간", [("SNP-M-101", 3)], 3))
        self.js(win, "[...document.querySelectorAll('.pwrap .seg-toggle button')].find((x) => x.textContent.trim() === '전체').click()")      # 두 구간을 함께 본다
        pump(0.8)
        self.focus(win, a)
        d = self.jsj(win, DETAIL)
        for gone in ("이어짐", "에서 계속", "이 구간을 건드린 묶음", "확정", "적용됨", "수정 1회", "만듦"):
            self.assertNotIn(gone, d["text"], gone)
        for kept in ("이름", "설계 의도"):
            self.assertIn(kept, d["labels"])
        self.assertEqual(d["sheets"], ["SNP-M-101", "SNP-M-102"])
        self.assertTrue(any(x.startswith("구성요소 ") for x in d["labels"]), d["labels"])
        self.assertEqual(d["open"], [False], "구성요소 목록은 접혀 있다")
        self.focus(win, b)
        self.assertEqual(self.jsj(win, DETAIL)["sheets"], ["SNP-M-101"], "도면이 하나여도 도면 칩을 둔다")
        text = self.js(win, "document.querySelector('.ndetail').innerText")
        self.assertNotRegex(text, "비어 있음|주요 기기", "자리표 글과 요약 줄은 없다")
        # 도면 칩: 그 도면을 전체 맞춤으로 열고 구간 강조
        self.focus(win, a)
        self.ready(win, "SNP-M-102")
        self.zoom_away(win)
        self.js(win, "[...document.querySelectorAll('[aria-label=\"도면별로 보기\"] button')].find((x) => x.textContent.includes('SNP-M-101')).click()")
        self.ready(win, "SNP-M-101")
        self.fitted(win, "도면 칩")
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [a], 15))
        # 구간 탭에는 묶음 목록도 되돌리기 단추도 없다
        panel = self.js(win, "document.querySelector('.pwrap').innerText")
        self.assertNotIn("최근 묶음", panel)
        self.assertEqual(self.js(win, "[...document.querySelectorAll('.pwrap button')].filter((x) => /되돌리기/.test((x.getAttribute('aria-label') || '') + x.textContent)).length"), 0)
        # 설정의 '작업 기록'에서 묶음 단위로 되돌린다
        count = len(api_nodes.summary(win.engine)["nodes"])
        self.js(win, "window.__hz.store.set({panel: 'settings'})")
        self.assertTrue(wait_for(lambda: "작업 기록" in self.text(win), 20), self.text(win)[-300:])
        last = next(x for x in api_nodes.summary(win.engine)["batches"] if not x["undone"])
        js = "(() => { const b = document.querySelector('.settings button[aria-label=\"%s 되돌리기\"]'); if (!b || b.disabled) return false; b.click(); return true; })()" % last["batch_id"]
        self.assertTrue(wait_for(lambda: self.js(win, js) is True, 20), "작업 기록의 되돌리기 %s" % last["batch_id"])
        self.assertTrue(wait_for(lambda: len(api_nodes.summary(win.engine)["nodes"]) == count - 1, 20), "묶음 되돌리기")
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])


if __name__ == "__main__":
    unittest.main()
