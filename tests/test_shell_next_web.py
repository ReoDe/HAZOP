"""'다음에 할 일' 한 줄이 실제 화면(오프스크린 웹, 1366×768)의 위 막대에 엔진 값대로 뜨고 잘리지 않는지(HZ-DSN-06 G1 (1)(6)).
실행: python -m unittest tests.test_shell_next_web"""

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


if __name__ == "__main__":
    unittest.main()
