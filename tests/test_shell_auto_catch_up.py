"""다시 추출 뒤 판 이전을 앱이 이어서 한다(사용자가 '판 이전 지금 하기'를 누르지 않아도). 실행: python -m unittest tests.test_shell_auto_catch_up

사용자 지시(INTENT §3.8): 엔진 사정을 사용자에게 시키지 않는다. 그래프 판이 바뀌는 길(다시 추출, 사람 수정 뒤 다시 짓기)이 끝나면 앱이 nodes.catch_up과 같은 판 이전을
한다. 잃은 것이 없으면 아무것도 묻지 않고, 새로 찾지 못한 구성요소가 있으면 알림 이벤트(study.lost) 하나를 보낸다. 자동 판 이전이 실패하면 지금의 막음과 단추가 그대로
남는다. AI 분석·AI 검토가 도는 중이면 끝난 뒤에 한다. 저장은 임시 작업 루트에만 한다. 실제 구독 호출 없음.
"""

import os
import threading
import time
import unittest
from unittest import mock

from hazop import store_io  # noqa: F401
from hazop.app import data
from hazop.shell import api, sheet_refresh
from tests.test_shell_catch_up import Base as CatchBase, PID, PLACES, world


class Base(CatchBase):
    def setUp(self):
        super().setUp()
        self.events = []
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings2.json"), emit=self.events.append, run_jobs=lambda jid, fn: fn())
        self.engine.settings.update(project_id=PID, reviewer_name="검토자A")

    def lost_events(self):
        return [e for e in self.events if e.get("name") == "study.lost"]

    def stale(self):
        return self.read("nodes")["stale"]

    def re_extract_losing_v2(self):
        g2 = world("v-2", dict(PLACES, V2=[200, 0, 5, 5]))     # V2가 다른 자리로 간 다시 추출: 그 자리 구성요소는 찾지 못한다
        self.g.clear()
        self.g.update(g2)


class AutoCatchUpTest(Base):
    def test_after_a_re_extract_nothing_has_to_be_pressed(self):
        self.re_extract()
        self.assertTrue(self.stale())
        self.assertFalse(self.read("ie")["available"])
        data.notify_graph_changed(PID)                    # 다시 추출이 끝났을 때 앱이 부르는 곳
        self.assertFalse(self.stale())
        self.assertTrue(self.read("ie")["available"], "⑥이 열린다")
        self.assertFalse(self.read("results")["stale"])

    def test_when_nothing_is_lost_nothing_is_said(self):
        self.re_extract()
        data.notify_graph_changed(PID)
        self.assertEqual(self.lost_events(), [])

    def test_when_a_member_is_lost_one_notice_is_sent_with_the_place_to_go(self):
        self.re_extract_losing_v2()
        data.notify_graph_changed(PID)
        got = self.lost_events()
        self.assertEqual(len(got), 1, self.events)
        d = got[0]["data"]
        self.assertGreaterEqual(d["sections"], 1)
        self.assertGreaterEqual(d["members"], 1)
        self.assertTrue(d["first_node"], "그 자리로 가는 단추가 열 구간")
        self.assertNotIn("lost:", str(got[0]), "묘비 id는 이벤트에도 나가지 않는다")

    def test_a_second_graph_change_does_not_repeat_the_same_notice(self):
        self.re_extract_losing_v2()
        data.notify_graph_changed(PID)
        data.notify_graph_changed(PID)
        self.assertEqual(len(self.lost_events()), 1)

    def test_a_failed_automatic_migration_keeps_the_guards(self):
        self.re_extract()
        with mock.patch.object(data, "migrate_study", side_effect=OSError("디스크 가득")):
            data.notify_graph_changed(PID)               # 예외를 올리지 않는다
        self.assertTrue(self.stale())
        self.assertFalse(self.read("ie")["available"], "막음이 그대로다")
        out = self.engine.dispatch("results.run_plan", {"scope": "all"}, project=PID)
        self.assertEqual(out["error"]["code"], "stale")
        self.assertEqual(self.lost_events(), [])
        self.assertTrue(self.catch_up()["ok"], "단추(명령)는 그대로 쓸 수 있다")

    def test_it_waits_while_an_ai_job_holds_the_turn_and_runs_after(self):
        self.re_extract()
        held, release = threading.Event(), threading.Event()

        def hold():
            with self.engine.ai_gate.turn("AI 분석", lambda: False, lambda: RuntimeError("stop")):
                held.set()
                release.wait(10)
        t = threading.Thread(target=hold, daemon=True)
        t.start()
        self.assertTrue(held.wait(5))
        data.notify_graph_changed(PID)
        self.assertTrue(self.stale(), "AI 작업이 도는 중에는 판 이전을 하지 않는다")
        release.set()
        end = time.monotonic() + 8
        while self.stale() and time.monotonic() < end:
            time.sleep(0.1)
        t.join(5)
        self.assertFalse(self.stale(), "끝난 뒤에 이어서 한다")

    def test_a_project_that_is_already_stale_when_opened_is_brought_up_once(self):
        self.re_extract()
        self.assertTrue(self.engine.catch_up_on_open())
        self.assertFalse(self.stale())
        self.assertFalse(self.engine.catch_up_on_open(), "이미 지금 판이면 할 것이 없다")

    def test_a_project_without_a_node_set_is_left_alone(self):
        os.remove(self.set_path())
        self.re_extract()
        data.notify_graph_changed(PID)
        self.assertEqual(self.events, [])


class HooksTest(Base):
    """그래프 판이 바뀌는 길이 끝에서 notify_graph_changed를 부른다."""

    def test_extract_and_graph_notifies_at_the_end(self):
        from tests.test_prepare_reextract import Stubs
        s = Stubs(self, "pdf")
        with mock.patch.object(data, "notify_graph_changed") as spy:
            data.extract_and_graph("reg.json")
        spy.assert_called_once_with("P-REEXTRACT")
        self.assertEqual(s.log[-1], ("extract", "pdf"))

    def test_extract_and_graph_failure_does_not_notify(self):
        from tests.test_prepare_reextract import Stubs
        Stubs(self, "pdf")
        with mock.patch.object(data, "_extract_pdf_pages", side_effect=ValueError("추출 실패")), \
                mock.patch.object(data, "notify_graph_changed") as spy:
            with self.assertRaises(ValueError):
                data.extract_and_graph("reg.json")
        spy.assert_not_called()

    def test_rebuild_after_a_human_edit_notifies_before_it_checks_for_stale_sets(self):
        order = []

        class Builder:
            def build_one(self, path, root):
                order.append("build")
                return {"project_id": PID}, root
        with mock.patch.object(data, "script_module", lambda name: Builder()), \
                mock.patch.object(data, "extraction_path", lambda name: name), \
                mock.patch.object(data, "build_project_kg", lambda pid: order.append("kg")), \
                mock.patch.object(data, "notify_graph_changed", lambda pid: order.append("notify")), \
                mock.patch.object(sheet_refresh, "project_recheck", lambda pid: order.append("recheck") or []):
            sheet_refresh.rebuild("x")
        self.assertEqual(order, ["build", "kg", "notify", "recheck"], "판 이전을 먼저 해야 재확인 안내가 낡은 상태를 말하지 않는다")


if __name__ == "__main__":
    unittest.main()
