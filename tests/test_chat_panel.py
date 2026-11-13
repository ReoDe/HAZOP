"""채팅 창 위젯(단위 C2). 실행: python -m unittest tests.test_chat_panel

가짜 세션(`hazop.chat.view.SessionPort` 모양)과 가짜 뷰어를 끼워 오프스크린으로 본다. 실제 CLI·구독·창 조작은 없다.
예시 질문, Enter 보내기, 멈추기, 모델 드롭다운, 다른 스레드에서 오는 답, 카드의 경로 칩·도면별 목록·경고, 구독이 없는 PC의 안내,
새 대화, 1366 폭에서 가로로 잘리지 않는지.
"""

import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from hazop.chat import card as cardmod  # noqa: E402
from tests.test_app import pump, tearDownModule, wait_for  # noqa: E402,F401
from tests.test_chat_card import REF, S1, S2, TOOL_IDS, FakeEnv, answer, comp, small_pg  # noqa: E402


class FakeSession:
    def __init__(self, model, callbacks):
        self.model, self.cb = model, callbacks
        self.asked, self.started, self.stopped, self.closed, self.models = [], 0, 0, False, []

    def start(self):
        self.started += 1
        return True

    def ask(self, text, view=None):
        self.asked.append((text, view))
        return "q%d" % len(self.asked)

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed = True

    def set_model(self, model):
        self.models.append(model)


class FakeHost:
    def __init__(self):
        self.calls, self.sheet, self.cleared = [], S1, []

    def current_sheet(self):
        return self.sheet

    def show_marks(self, rid, marks, sheet=None):
        self.calls.append((rid, marks, sheet))

    def show_sheet(self, graph_id, then=None):
        self.sheet = graph_id
        if then:
            then()

    def clear(self, rid=None):
        self.cleared.append(rid)


class PanelBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    def panel(self, width=420, host=None, **kw):
        from hazop.app.chat_panel import ChatPanel
        self.sessions = []

        def factory(model, callbacks):
            s = FakeSession(model, callbacks)
            self.sessions.append(s)
            return s

        env = FakeEnv()
        p = ChatPanel(factory, env_provider=lambda: (env, small_pg()), host=host,
                      view_fn=lambda: {"stage": "②", "sheet": S1, "selected": []}, **kw)
        p.resize(width, 700)
        p.show()
        self.addCleanup(p.deleteLater)
        pump(seconds=0.05)
        return p

    def deliver(self, p, qid="q1", ans=None, tool_ids=None, tools=1, from_thread=True):
        """세션이 읽기 스레드에서 도구 이벤트와 답을 보낸다."""
        s = self.sessions[-1]

        def run():
            for _ in range(tools):
                s.cb["on_tool_event"](qid, "trace_path", {"start": "a"}, {"ok": True, "data": {"path_ref": REF}})
            s.cb["on_answer"](qid, ans if ans is not None else answer(paths=[{"label": "RC-PZ01 → RC-PSV101", "path_ref": REF}]),
                              TOOL_IDS if tool_ids is None else tool_ids)
        if from_thread:
            t = threading.Thread(target=run)
            t.start()
            t.join()
        else:
            run()
        pump(seconds=0.1)

    def texts(self, p):
        return " | ".join(w.text() for w in p.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))

    def buttons(self, p):
        return [b.text() for b in p.findChildren(QPushButton) if b.isVisibleTo(p)]


class InputTest(PanelBase):
    def test_empty_state_shows_examples_and_clicking_asks(self):
        p = self.panel()
        ex = [b for b in p.findChildren(QPushButton) if b.objectName() == "chat_example"]
        self.assertGreaterEqual(len(ex), 4)
        text = ex[0].text()
        ex[0].click()
        pump(seconds=0.05)
        self.assertEqual(self.sessions[-1].asked[0][0], text)
        self.assertEqual(self.sessions[-1].asked[0][1]["sheet"], S1)
        self.assertTrue(all(not b.isVisible() for b in ex), "질문하면 예시는 숨는다")

    def test_enter_sends_shift_enter_newlines(self):
        p = self.panel()
        p.input.insertPlainText("첫 줄")  # 한글은 QTest.keyClicks로 치면 오프스크린에서 프로세스가 죽는다
        QTest.keyClick(p.input, Qt.Key_Return, Qt.ShiftModifier)
        p.input.insertPlainText("둘째 줄")
        self.assertTrue(not self.sessions or self.sessions[-1].asked == [])
        QTest.keyClick(p.input, Qt.Key_Return)
        pump(seconds=0.05)
        self.assertEqual(self.sessions[-1].asked[0][0], "첫 줄\n둘째 줄")
        self.assertEqual(p.input.toPlainText(), "")

    def test_empty_input_is_not_sent(self):
        p = self.panel()
        QTest.keyClick(p.input, Qt.Key_Return)
        self.assertEqual(self.sessions, [])

    def test_typing_prewarms_the_session_once(self):
        p = self.panel()
        QTest.keyClicks(p.input, "ab")
        self.assertTrue(wait_for(lambda: self.sessions and self.sessions[-1].started == 1, 3))
        QTest.keyClicks(p.input, "cd")
        pump(seconds=0.05)
        self.assertEqual(self.sessions[-1].started, 1)
        self.assertEqual(len(self.sessions), 1)

    def test_send_button_becomes_stop_while_busy(self):
        p = self.panel()
        p.input.insertPlainText("질문")
        QTest.keyClick(p.input, Qt.Key_Return)
        pump(seconds=0.05)
        self.assertEqual(p.send_button.text(), "멈추기")
        self.assertTrue(p.busy())
        p.send_button.click()
        pump(seconds=0.05)
        self.assertEqual(self.sessions[-1].stopped, 1)
        self.assertFalse(p.busy())
        self.assertEqual(p.send_button.text(), "보내기")
        self.assertIn("그 대화는 사라", self.texts(p))

    def test_cannot_send_second_question_while_busy(self):
        p = self.panel()
        p.ask("하나")
        p.ask("둘")
        self.assertEqual(len(self.sessions[-1].asked), 1)


class FactoryFailureTest(PanelBase):
    def test_factory_error_becomes_a_notice(self):
        from hazop.app.chat_panel import ChatPanel

        def boom(model, cb):
            raise ValueError("프로젝트가 없습니다. 먼저 도면을 등록하세요.")
        p = ChatPanel(boom)
        p.resize(400, 600)
        p.show()
        self.addCleanup(p.deleteLater)
        self.assertFalse(p.ask("질문"))
        self.assertFalse(p.busy())
        self.assertIn("프로젝트가 없습니다", self.texts(p))

    def test_examples_refill_from_project(self):
        pg = {"nodes": [dict(entity_id="a", tag="RC-AAA", kind="vessel"), dict(entity_id="b", tag="RC-BBB", kind="valve")]}
        p = self.panel()
        p._env_provider = lambda: (FakeEnv(), pg)
        p.refresh_examples()
        self.assertIn("RC-AAA", " ".join(b.text() for b in p.findChildren(QPushButton) if b.objectName() == "chat_example"))


class KeyboardTest(PanelBase):
    def test_escape_in_input_signals_return_to_center(self):
        p = self.panel()
        got = []
        p.escaped.connect(lambda: got.append(1))
        QTest.keyClick(p.input, Qt.Key_Escape)
        self.assertEqual(got, [1])

    def test_focus_input_when_open_not_when_blocked(self):
        p = self.panel()
        p.focus_input()
        self.assertTrue(p.input.hasFocus())
        p2 = self.panel()
        p2.set_availability("not_installed")
        p2.focus_input()
        self.assertFalse(p2.input.hasFocus())


class ModelTest(PanelBase):
    def test_default_is_fast_and_change_goes_to_session(self):
        p = self.panel()
        self.assertEqual(p.model_combo.currentText(), "빠름")
        self.assertEqual([p.model_combo.itemText(i) for i in range(3)], ["빠름", "보통", "깊게"])
        p.ask("처음")
        self.assertEqual(self.sessions[-1].model, "fast")
        p.model_combo.setCurrentText("깊게")
        self.assertEqual(self.sessions[-1].models, ["deep"])
        self.assertEqual(p.model(), "deep")

    def test_model_change_is_reported_for_saving(self):
        p = self.panel()
        got = []
        p.modelChanged.connect(got.append)
        p.model_combo.setCurrentText("보통")
        self.assertEqual(got, ["normal"])

    def test_initial_model_from_settings(self):
        p = self.panel(model="normal")
        self.assertEqual(p.model_combo.currentText(), "보통")


class AnswerTest(PanelBase):
    def test_answer_from_reader_thread_becomes_a_card(self):
        host = FakeHost()
        p = self.panel(host=host)
        p.ask("경로 알려줘")
        self.deliver(p, tools=2)
        self.assertFalse(p.busy())
        self.assertEqual(len(p.cards()), 1)
        t = self.texts(p)
        self.assertIn("경로는 티 하나를 거칩니다.", t)
        self.assertIn("도구 2회", t)
        chips = [b for b in p.findChildren(QPushButton) if b.objectName() == "chat_chip"]
        self.assertEqual([b.text() for b in chips], ["RC-PZ01", "RC-T2", "RC-PSV101"])

    def test_warning_strip_and_sheet_list_and_general(self):
        p = self.panel(host=FakeHost())
        p.ask("q")
        self.deliver(p, ans=answer(general="일반 지식 글", paths=[{"label": "경로", "path_ref": REF}]))
        t = self.texts(p)
        self.assertIn("흐름 방향 미확인 배관 1개", t)
        self.assertIn("일반 지식", t)
        sheets = [b.text() for b in p.findChildren(QPushButton) if b.objectName() == "chat_sheet"]
        self.assertEqual(sheets, [S1 + " · 2", S2 + " · 1"])

    def test_general_only_answer_shows_no_evidence_header(self):
        p = self.panel()
        p.ask("q")
        self.deliver(p, ans=answer(text="", general="그냥 일반 지식"), tool_ids={})
        self.assertIn("도면·문서에서 확인한 내용 없음", self.texts(p))

    def test_text_is_plain_not_html(self):
        p = self.panel()
        p.ask("q")
        self.deliver(p, ans=answer(text="<b>굵게</b>"))
        from PySide6.QtWidgets import QLabel
        lab = next(w for w in p.findChildren(QLabel) if "굵게" in w.text())
        self.assertEqual(lab.textFormat(), Qt.PlainText)

    def test_ungrounded_count_in_footer(self):
        p = self.panel()
        p.ask("q")
        self.deliver(p, ans=answer(refs=[{"kind": "component", "id": comp(S1, 11)}]), tool_ids={"component": {comp(S1, 1)}})
        self.assertIn("근거 확인 안 됨 1개", self.texts(p))

    def test_error_shows_notice_and_reenables_input(self):
        p = self.panel()
        p.ask("q")
        s = self.sessions[-1]
        threading.Thread(target=lambda: s.cb["on_error"]("q1", {"error_kind": "timeout", "conn_state": None,
                                                                  "message": "응답 시간을 넘겨 끊음", "limit": None})).start()
        self.assertTrue(wait_for(lambda: not p.busy(), 3))
        self.assertIn("응답 시간을 넘겨 끊음", self.texts(p))
        self.assertTrue(p.input.isEnabled())

    def test_limit_error_blocks_input_with_reset_time(self):
        p = self.panel()
        p.ask("q")
        s = self.sessions[-1]
        s.cb["on_error"]("q1", {"error_kind": "limit_reached", "conn_state": "limit_reached", "message": "한도",
                                  "limit": {"resets_at_text": "오후 3시"}})
        pump(seconds=0.1)
        self.assertFalse(p.input.isEnabled())
        self.assertIn("한도에 닿았습니다", self.texts(p))

    def test_overage_and_auth_errors_block_further_questions(self):
        for kind in ("overage", "auth_mismatch", "tool_guard_failed"):
            p = self.panel()
            p.ask("q")
            self.sessions[-1].cb["on_error"]("q1", {"error_kind": kind, "conn_state": kind, "message": "멈춤 " + kind, "limit": None})
            pump(seconds=0.1)
            self.assertFalse(p.ask("다시"), kind)
            self.assertEqual(len(self.sessions[-1].asked), 1, kind)

    def test_renewed_state_adds_a_line(self):
        p = self.panel()
        p.ask("q")
        self.sessions[-1].cb["on_state"]("renewed", "대화를 새로 시작했습니다.")
        pump(seconds=0.05)
        self.assertIn("대화를 새로 시작했습니다.", self.texts(p))

    def test_new_conversation_clears_transcript(self):
        p = self.panel(host=FakeHost())
        p.ask("q")
        self.deliver(p)
        p.new_conversation()
        pump(seconds=0.05)
        self.assertEqual(p.cards(), [])
        self.assertEqual(self.sessions[-1].stopped, 1)
        self.assertTrue(any(b.objectName() == "chat_example" and b.isVisible() for b in p.findChildren(QPushButton)))

    def test_shutdown_closes_session(self):
        p = self.panel()
        p.ask("q")
        p.shutdown()
        self.assertTrue(self.sessions[-1].closed)


class ViewerTest(PanelBase):
    def test_first_path_is_marked_on_current_sheet(self):
        host = FakeHost()
        p = self.panel(host=host)
        p.ask("q")
        self.deliver(p)
        self.assertEqual(len(host.calls), 1)
        rid, marks, sheet = host.calls[0]
        self.assertIn(S1, marks)
        self.assertIsNone(sheet, "카드가 나타날 때 도면을 갑자기 바꾸지 않는다")

    def test_sheet_button_opens_that_sheet_and_draws(self):
        host = FakeHost()
        p = self.panel(host=host)
        p.ask("q")
        self.deliver(p)
        btn = next(b for b in p.findChildren(QPushButton) if b.objectName() == "chat_sheet" and b.text().startswith(S2))
        btn.click()
        self.assertEqual(host.calls[-1][2], S2)

    def test_chip_click_goes_to_the_object(self):
        host = FakeHost()
        zoomed = []
        host.webview = type("W", (), {"zoom_to": lambda self, ids, pad=0.15: zoomed.append(ids)})()
        p = self.panel(host=host)
        p.ask("q")
        self.deliver(p)
        next(b for b in p.findChildren(QPushButton) if b.objectName() == "chat_chip" and b.text() == "RC-PZ01").click()
        self.assertEqual(zoomed, [["L1"]])

    def test_new_answer_clears_the_previous_marks(self):
        host = FakeHost()
        p = self.panel(host=host)
        p.ask("q")
        self.deliver(p)
        p.ask("두번째")
        self.deliver(p, qid="q2")
        self.assertEqual(len(host.cleared), 1)


class AvailabilityPanelTest(PanelBase):
    def test_no_cli_hides_input_and_shows_guide(self):
        p = self.panel()
        p.set_availability("not_installed")
        pump(seconds=0.05)
        self.assertFalse(p.input.isVisible())
        self.assertIn("이 PC에 Claude Code가 없습니다", self.texts(p))
        self.assertIn("설치 방법 보기", self.buttons(p))
        self.assertEqual([b for b in p.findChildren(QPushButton) if b.objectName() == "chat_example" and b.isVisible()], [])

    def test_install_button_emits_signal(self):
        p = self.panel()
        got = []
        p.guideRequested.connect(got.append)
        p.set_availability("not_installed")
        next(b for b in p.findChildren(QPushButton) if b.text() == "설치 방법 보기").click()
        self.assertEqual(got, ["install"])

    def test_logged_out_shows_login_button(self):
        p = self.panel()
        p.set_availability("login_required")
        self.assertIn("로그인 창 열기", self.buttons(p))

    def test_back_to_ok_restores_input(self):
        p = self.panel()
        p.set_availability("not_installed")
        p.set_availability("ok")
        pump(seconds=0.05)
        self.assertTrue(p.input.isVisible())

    def test_no_session_is_started_while_blocked(self):
        p = self.panel()
        p.set_availability("not_installed")
        p.ask("q")
        p.prewarm()
        self.assertEqual(self.sessions, [])


class WidthTest(PanelBase):
    def test_no_horizontal_overflow_at_narrow_width(self):
        host = FakeHost()
        p = self.panel(width=300, host=host)
        p.ask("긴 질문 " * 20)
        self.deliver(p, ans=answer(text="긴 답변 " * 60, general="일반 지식 " * 40, paths=[{"label": "경로", "path_ref": REF}]))
        pump(seconds=0.1)
        bar = p.scroll.horizontalScrollBar()
        self.assertEqual(bar.maximum(), 0, "가로로 잘리거나 밀리지 않는다")
        for c in p.cards():
            self.assertLessEqual(c.width(), p.scroll.viewport().width())
        for b in p.findChildren(QPushButton):
            if b.isVisible() and b.objectName().startswith("chat_"):
                tl = b.mapTo(p, b.rect().topLeft())
                self.assertGreaterEqual(tl.x(), 0, b.text())
                self.assertLessEqual(tl.x() + b.width(), p.width() + 1, b.text())

    def test_long_chip_list_folds_and_expands(self):
        p = self.panel(width=360, host=FakeHost())
        env = FakeEnv()
        steps = []
        for i in range(30):
            env.items[comp(S1, 100 + i)] = dict(tag="T%d" % i, kind="valve", sheet=S1)
            steps.append(dict(id=comp(S1, 100 + i), kind="valve", flow=None))
        env.steps = steps
        p._env_provider = lambda: (env, small_pg())
        p.ask("q")
        self.deliver(p)
        chips = [b for b in p.findChildren(QPushButton) if b.objectName() == "chat_chip"]
        self.assertEqual(len(chips), 10)
        fold = next(b for b in p.findChildren(QPushButton) if b.objectName() == "chat_fold_chips")
        self.assertIn("20개", fold.text())
        fold.click()
        pump(seconds=0.05)
        self.assertEqual(len([b for b in p.findChildren(QPushButton) if b.objectName() == "chat_chip"]), 30)


if __name__ == "__main__":
    unittest.main()
