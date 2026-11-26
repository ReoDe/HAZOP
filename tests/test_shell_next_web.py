"""'다음에 할 일' 한 줄이 실제 화면(오프스크린 웹, 1366×768)의 위 막대에 엔진 값대로 뜨고 잘리지 않는지(HZ-DSN-06 G1 (1)(6)).
실행: python -m unittest tests.test_shell_next_web"""

import json
import unittest

from tests.test_shell_web import ShellBase, pump, wait_for

LONGEST = "도면이 바뀌어 3곳을 다시 확인해야 합니다"


class NextLineTest(ShellBase):
    def test_the_top_bar_has_no_next_line(self):
        """화면 단순화(사용자 결정 2026-11-25): 맨 위 '다음에 할 일' 한 줄은 화면에서 내렸다(코드와 엔진 읽기는 남김)."""
        win = self.window((1366, 768))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.topbar .crumb')"), 15))
        pump(0.5)
        self.assertEqual(self.js(win, "document.querySelectorAll('.topbar .next').length"), 0)


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

    @unittest.skip("화면 단순화: 표제란·AI 검토 시작·쪽 확정 단추를 화면에서 뺐다. 자동 확정(C2)이 들어올 때 새 흐름으로 다시 쓴다")
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


class QueueFocusTest(ShellBase):
    """실제 창 결함 1(2026-11-23 real-window-check): 도면 위 칩으로 연 대기열에서 E를 누르면 입력칸에 포커스가 가야 하고,
    Enter가 칩을 다시 눌러 대기열을 처음부터 다시 열면 안 된다. 클릭 흉내는 포커스를 옮기지 않으므로 칩에 포커스를 두고 진짜 키(QTest)를 보낸다."""

    def key(self, win, k, text=""):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        target = win.view.focusProxy() or win.view
        QTest.keyClick(target, getattr(Qt, "Key_" + k), Qt.NoModifier)
        pump(0.3)

    @unittest.skip("화면 단순화: 표제란·AI 검토 시작·쪽 확정 단추를 화면에서 뺐다. 자동 확정(C2)이 들어올 때 새 흐름으로 다시 쓴다")
    def test_e_moves_focus_into_the_field_and_enter_saves_not_reopens(self):
        from hazop.app import data
        from hazop.extract import ai_review as ar
        win = self.window((1366, 768))
        win.activateWindow()
        win.view.setFocus()
        gid = self.js(win, "window.__hz.store.get().drawings.drawings[0].graph_id")
        name = win.engine.graph_names()[gid]
        ex = data.read_json(data.extraction_path(name))
        valves = [n for n in ex["nodes"] if n.get("kind") and n.get("kind") != "tee"][:2]
        doc = ar.new_doc(name, ex)
        ar.merge_run(doc, {"candidates": [ar.make_candidate("t-%d" % i, "tag", n, "tag", ["V90%d" % i], 0.95, "주변 글자") for i, n in enumerate(valves)],
                           "stats": {"calls": 1, "left": 0}})
        ar.save_doc(doc)
        win.engine.changed("aireview", None)
        self.js(win, "window.__hz.store.set({ sheet: '%s', panel: null })" % gid)
        chip = ".confbar .chip.review.act"
        self.assertTrue(wait_for(lambda: "검토하기" in (self.js(win, "(document.querySelector('%s') || {}).textContent || ''" % chip) or ""), 20))
        self.js(win, "document.querySelector('%s').focus()" % chip)
        self.key(win, "Return")                                    # 진짜 Enter로 칩을 누른다(포커스가 칩에 남는 길)
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('aside.chat.queue .qacts')"), 15), "대기열이 열리지 않음")
        self.assertTrue(wait_for(lambda: self.js(win, "!(document.activeElement && document.activeElement.closest && document.activeElement.closest('.confbar'))"), 5),
                        "대기열이 열린 뒤에도 포커스가 칩에 남음")
        self.key(win, "E")
        self.assertTrue(wait_for(lambda: self.js(win, "document.activeElement && document.activeElement.classList.contains('qedit')"), 5),
                        "E 뒤 포커스: %s" % self.js(win, "document.activeElement && document.activeElement.className"))
        self.js(win, "document.querySelector('.qedit').focus()")
        before = self.js(win, "window.__hz.queue.get().undo.length")
        self.key(win, "Return")
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.queue.get().undo.length") == before + 1, 15), "Enter가 고친 값을 저장하지 않음")
        self.assertEqual(self.js(win, "window.__hz.queue.get().open"), True)
        # 대기열이 열린 동안 칩에 포커스가 돌아가도 Enter가 대기열을 다시 열지 않는다
        self.js(win, "document.querySelector('%s') && document.querySelector('%s').focus()" % (chip, chip))
        self.key(win, "Return")
        self.assertEqual(self.js(win, "window.__hz.queue.get().undo.length"), before + 1, "대기열이 처음부터 다시 열림")


class LayoutTest(ShellBase):
    """실제 창 결함 2·3·6: 열린 패널이 다음에 할 일 줄을 가리지 않고, 알림 줄은 도면·보기 도구를 덮지 않으며 패널에 잘리지 않고,
    대기열이 열린 동안은 숨는다. '그 밖에 n건' 펼침은 Esc로 닫힌다(1366×768)."""

    def rect(self, win, sel):
        r = self.js(win, "(() => { const e = document.querySelector(%s); if (!e) return null; const r = e.getBoundingClientRect();"
                         " return JSON.stringify([r.left, r.top, r.right, r.bottom]); })()" % json.dumps(sel))
        return json.loads(r) if r else None

    def test_panel_and_notice_do_not_cover_the_line_or_the_drawing(self):
        win = self.window((1366, 768))
        gid = self.js(win, "window.__hz.store.get().drawings.drawings[0].graph_id")
        self.js(win, "window.__hz.store.set({ sheet: '%s', panel: 'nodes', notices: [{ id: 't', kind: 'warn', text: '도면이 바뀌어 2곳을 다시 확인해야 합니다(찾지 못한 구성요소 2개)' }] })" % gid)
        self.assertTrue(wait_for(lambda: self.rect(win, ".pwrap") and self.rect(win, ".notice-row") and self.rect(win, ".topbar"), 15))
        line, panel, row, canvas = (self.rect(win, s) for s in (".topbar", ".pwrap", ".notice-row", ".canvas"))
        self.assertGreaterEqual(panel[1], line[3] - 1, "패널은 위 막대 아래에서 시작")
        self.assertGreaterEqual(row[0], panel[2] - 1, "알림은 패널 오른쪽에서 시작(글이 패널에 잘리지 않음)")
        self.assertGreaterEqual(canvas[1], row[3] - 1, "알림이 도면을 덮지 않음")
        nt = self.js(win, "(() => { const t = document.querySelector('.notice-row .nt'); return t.scrollWidth <= t.clientWidth + 1; })()")
        self.assertTrue(nt, "알림 글이 잘림")
        self.js(win, "window.__hz.store.set({ panel: null })")
        self.js(win, "window.__hz.queue.set({ open: true, kind: 'lost', i: 0, done: false, items: [{ qid: 'lost|S1|L-1', kind: 'lost', node_id: 'S1', node_name: 'S1',"
                     " key: 'L-1', label: '밸브', graph_id: null, sheet: null, target: { node_id: 'S1', rev: 1, state: 'applied' }, held: false, cands: [], state: 'open' }] })")
        self.assertTrue(wait_for(lambda: self.rect(win, "aside.chat.queue") is not None, 10))
        self.assertTrue(wait_for(lambda: self.js(win, "getComputedStyle(document.querySelector('.notice-bar')).display") == "none", 5), "대기열 동안 알림이 남음")


class CloseWaitTest(ShellBase):
    """검토 지적 3(a2a3711): 창을 닫을 때 뒤 스레드(열 때 정착·판 이전, engine.spawn)만 돌고 있어도 끝나기를 기다린다(30초 상한)."""

    def test_close_waits_for_a_spawned_thread(self):
        import threading
        import time
        win = self.window((1366, 768))
        done = threading.Event()

        def work():
            time.sleep(1.0)
            done.set()
        win.engine.spawn(work, "settle-like")
        self.assertEqual(win.engine.running_jobs(), [], "작업은 없고 뒤 스레드만 돈다")
        win.close()
        self.assertTrue(done.is_set(), "닫기가 뒤 스레드를 기다리지 않음")


if __name__ == "__main__":
    unittest.main()
