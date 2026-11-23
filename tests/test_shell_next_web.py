"""'다음에 할 일' 한 줄이 실제 화면(오프스크린 웹, 1366×768)의 위 막대에 엔진 값대로 뜨고 잘리지 않는지(HZ-DSN-06 G1 (1)(6)).
실행: python -m unittest tests.test_shell_next_web"""

import json
import unittest

from tests.test_shell_web import ShellBase, wait_for

LONGEST = "도면이 바뀌어 3곳을 다시 확인해야 합니다"


class NextLineTest(ShellBase):
    def test_the_line_shows_the_engine_item_in_the_top_bar(self):
        win = self.window((1366, 768))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.topbar .next .line')"), 15), "줄이 뜨지 않음")
        from hazop.shell import api_next
        first = api_next.summary(win.engine)["items"][0]["text"]
        self.assertTrue(wait_for(lambda: first in (self.js(win, "document.querySelector('.topbar .next .line .txt').textContent") or ""), 10))

    def test_the_longest_sentence_is_not_cut_at_1366(self):
        win = self.window((1366, 768))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.topbar .next .line')"), 15))
        # 가장 긴 문장·단추·'그 밖에 n건'을 넣고 잘림을 잰다
        self.js(win, """window.__hz.next.set(({ running: null, open: false, items: [
            { kind: 'recheck', count: 3, text: '%s', detail: null, action: { label: '확인하기', go: 'queue:lost' }, tone: 'warn' },
            { kind: 'titleblock', count: 1, text: '표제란을 확정하지 않은 도면이 1장 있습니다', detail: null, action: { label: '표제란 확정', go: 'panel:drawings#titleblock' }, tone: '' },
            { kind: 'nodes_draft', count: 2, text: '확정하지 않은 검토구간이 2개 있습니다', detail: null, action: { label: '모두 확정', go: 'confirm:nodes.confirm' }, tone: '' }] }))""" % LONGEST)
        self.assertTrue(wait_for(lambda: LONGEST in (self.js(win, "document.querySelector('.topbar .next .line .txt').textContent") or ""), 10))
        m = self.js(win, """(() => { const t = document.querySelector('.topbar .next .line .txt'); const l = t.closest('.line'); const b = document.querySelector('.topbar').getBoundingClientRect();
            const r = l.getBoundingClientRect(); return JSON.stringify({ cut: t.scrollWidth > t.clientWidth + 1, inside: r.left >= b.left && r.right <= b.right,
            more: !!l.querySelector('.more') }); })()""")
        import json
        self.assertEqual(json.loads(m), {"cut": False, "inside": True, "more": True}, m)


class QueueCardTest(ShellBase):
    """대기열을 열면 오른쪽 칸이 채팅 대신 카드가 되고(둘을 함께 띄우지 않음), 위 줄은 진행으로 바뀐다. 닫으면 채팅이 돌아온다(HZ-DSN-06 G3·G5)."""

    def test_the_card_takes_the_chat_place_and_fits_at_1366(self):
        import json
        win = self.window((1366, 768))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('aside.chat')"), 15))
        self.js(win, """window.__hz.queue.set({ open: true, kind: 'ai', i: 0, done: false, items: [
            { qid: 'ai|G|c1', kind: 'ai', graph_id: null, sheet: 'SNP-M-101', ver: 'v', cand_id: 'c1', local_id: null, label: 'RC-V010',
              task: '못 읽은 기호의 종류', field: 'kind', field_label: '종류', now: '밸브(종류 모름)', proposal: '체크 밸브', confidence: 0.96,
              why: '기호 안의 삼각형과 막대가 체크 밸브 모양과 같습니다.', bulk: false, edit_op: null, state: 'open' },
            { qid: 'ai|G|c2', kind: 'ai', graph_id: null, sheet: 'SNP-M-101', ver: 'v', cand_id: 'c2', local_id: null, label: 'RC-V011',
              task: '태그·속성', field: 'tag', field_label: '태그', now: '(비어 있음)', proposal: 'RC-V011', confidence: 0.97, why: '', bulk: true,
              edit_op: 'set_tag', state: 'open' }] })""")
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('aside.chat.queue .qacts')"), 10), "카드가 뜨지 않음")
        m = json.loads(self.js(win, """(() => { const a = document.querySelectorAll('aside.chat'); const c = document.querySelector('aside.chat.queue');
            const r = c.getBoundingClientRect(); const cut = [...c.querySelectorAll('.btn, .txt, b')].filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent);
            return JSON.stringify({ asides: a.length, chatInput: !!document.querySelector('.chat-input'), width: Math.round(r.width), inside: r.right <= innerWidth + 1,
              line: (document.querySelector('.topbar .next .txt') || {}).textContent || '', cut }); })()"""))
        self.assertEqual((m["asides"], m["chatInput"], m["inside"], m["cut"]), (1, False, True, []), m)
        self.assertIn("AI 후보 검토 · 2건 중 1번째", m["line"])
        self.js(win, "document.querySelector('aside.chat.queue .chat-h .btn').click()")
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.chat-input') && !document.querySelector('aside.chat.queue')"), 10),
                        "채팅으로 돌아오지 않음")


class ReviewFlowTest(ShellBase):
    """도면별 AI 검토 한 바퀴(HZ-DSN-06 G7): 도면 위 'AI 검토 시작' → 확인 창 → 시작 → 끝 알림 → 검토하기 → 그 도면 대기열. 가짜 구독 클라이언트."""

    def test_start_on_the_drawing_then_review_the_queue(self):
        from tests.test_ai_review import StubClient
        from tests.test_shell_aireview import FakeAi, kind_answers
        win = self.window((1366, 768))
        win.engine.ai = FakeAi(StubClient(kind_answers))
        gid = self.js(win, "window.__hz.store.get().drawings.drawings[0].graph_id")
        self.js(win, "window.__hz.store.set({ sheet: '%s', panel: null })" % gid)
        chip = ".confbar .chip.review.act"
        self.assertTrue(wait_for(lambda: "AI 검토 시작" in (self.js(win, "(document.querySelector('%s') || {}).textContent || ''" % chip) or ""), 20),
                        "도면 위 칩이 뜨지 않음")
        self.js(win, "document.querySelector('%s').click()" % chip)
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.rv-modal .btn.primary') && !document.querySelector('.rv-modal .btn.primary').disabled"), 15),
                        "확인 창의 검토 시작이 켜지지 않음: %s" % self.js(win, "(document.querySelector('.rv-modal') || {}).textContent"))
        self.js(win, "document.querySelector('.rv-modal .btn.primary').click()")
        notice = "[...document.querySelectorAll('.notice-row')].find((x) => x.textContent.includes('AI 검토가 끝났습니다'))"
        self.assertTrue(wait_for(lambda: self.js(win, "!!" + notice), 60), "끝 알림이 뜨지 않음")
        self.assertTrue(wait_for(lambda: "AI 후보" in (self.js(win, "(document.querySelector('%s') || {}).textContent || ''" % ".confbar .chip.review") or ""), 15))
        self.js(win, "%s.querySelector('button').click()" % notice)
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('aside.chat.queue .qacts')"), 20), "대기열이 열리지 않음")
        line = self.js(win, "document.querySelector('.topbar .next .txt').textContent")
        self.assertIn("AI 후보 검토", line)
        sheets = json.loads(self.js(win, "JSON.stringify([...new Set(window.__hz.queue.get().items.map((x) => x.graph_id))])"))
        self.assertEqual(sheets, [gid], "대기열은 그 도면의 후보만")


if __name__ == "__main__":
    unittest.main()
