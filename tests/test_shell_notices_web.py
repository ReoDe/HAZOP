"""닫을 수 있는 알림 줄(web/js/notices.js)이 실제 화면(오프스크린 웹)에 뜨고, '그 자리로'가 구간 패널을 열고, 닫으면 사라지는지. 실행: python -m unittest tests.test_shell_notices_web"""

import unittest

from tests.test_shell_web import ShellBase, wait_for


class NoticeBarTest(ShellBase):
    def test_study_lost_event_shows_a_bar_with_go_and_close_buttons(self):
        win = self.window()
        win.bridge.send({"t": "event", "name": "study.lost", "data": {"sections": 2, "members": 3, "first_node": "S1"}})
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.notice-row').length") == 1, 10), "알림 줄이 뜨지 않음")
        text = self.js(win, "document.querySelector('.notice-row .nt').textContent")
        self.assertIn("도면이 바뀌어 2곳을 다시 확인해야 합니다", text)
        self.assertNotIn("lost:", text)
        self.js(win, "[...document.querySelectorAll('.notice-row button')].find(b => b.textContent.includes('그 자리로')).click()")
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().panel") == "nodes", 10), "구간 패널로 가지 않음")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.notice-row').length") == 0, 10), "처리하면 알림이 사라진다")

    def test_closing_removes_it_and_the_same_text_does_not_come_back(self):
        win = self.window()
        ev = {"t": "event", "name": "study.lost", "data": {"sections": 1, "members": 1, "first_node": "S1"}}
        win.bridge.send(ev)
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.notice-row').length") == 1, 10))
        self.js(win, "document.querySelector('.notice-row button[aria-label=\"알림 닫기\"]').click()")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.notice-row').length") == 0, 10))
        win.bridge.send(ev)
        self.assertFalse(wait_for(lambda: self.js(win, "document.querySelectorAll('.notice-row').length") == 1, 1.5), "닫은 같은 글은 다시 뜨지 않는다")
        again = {"t": "event", "name": "study.lost", "data": dict(ev["data"], graph_version="v-new")}
        win.bridge.send(again)        # 다시 추출해 같은 수를 새로 잃었다: 판이 다르니 다시 알린다
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.notice-row').length") == 1, 10), "새 판에서 같은 글은 다시 뜬다")

    def test_a_demoted_confirmed_section_gets_its_own_notice(self):
        win = self.window()
        win.bridge.send({"t": "event", "name": "study.lost", "data": {"sections": 0, "members": 0, "first_node": None, "demoted": ["S2"], "graph_version": "v-2"}})
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.notice-row').length") == 1, 10))
        text = self.js(win, "document.querySelector('.notice-row .nt').textContent")
        self.assertIn("확정했던 구간 S2의 확정을 풀었습니다", text)


if __name__ == "__main__":
    unittest.main()
