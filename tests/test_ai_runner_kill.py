"""AI 실행기(hazop/app/ai_runner.py)의 '바로 끊기'가 호출이 막 시작되려던 때에도 듣는지. 실행: python -m unittest tests.test_ai_runner_kill

배경: 작업자가 대기열에서 호출 하나를 꺼낸 순간부터 calls_in_flight()는 1이지만, 클라이언트가 취소 세대를 읽고 프로세스를 띄우는 것은 조금 뒤다.
그 사이에 kill()이 와서 client.cancel()이 끊을 프로세스를 못 찾으면, 뒤늦게 뜬 호출은 끝까지(시간 제한까지) 살아 있어 '바로 끊고 닫기'가 닫히지 않았다
(tests.test_ai_run_flow ... test_close_now_kills_and_closes의 간헐 실패, 2026-11-18 조사). 실제 클라이언트 클래스와 오래 자는 가짜 프로세스를 쓴다.
"""

import os
import sys
import tempfile
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402  (다른 시험과 같은 종류의 앱 객체를 쓴다)

from hazop.app.ai_runner import AiRunner  # noqa: E402
from hazop.study import claude_cli  # noqa: E402

REQUEST = {"system": "s", "context": "{}", "user": "u", "schema": {"type": "object"}}


class KillBeforeSpawnTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.tmp = tempfile.mkdtemp(prefix="hazop-runner-kill-")
        self.client = claude_cli.ClaudeCliClient(argv_prefix=[sys.executable, "-c", "import time; time.sleep(60)"],
                                                 limits_path=os.path.join(self.tmp, "limits.json"), run_root=os.path.join(self.tmp, "run"))
        self.addCleanup(self.client.cancel)

    def runner(self, delay):
        """작업자가 호출을 꺼낸 뒤 클라이언트를 부르기 전에 delay초 걸리는 실행기(요청을 만드는 시간을 흉내)."""
        def run(client, unit, ctx, at):
            time.sleep(delay)
            res = client.analyze(REQUEST)
            return {"error_kind": res.get("error_kind")}
        return AiRunner([({"unit_id": "u1"}, None)], None, self.client, run=run)

    def pump_until(self, cond, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        return cond()

    def test_kill_during_the_gap_before_the_call_starts_still_ends_the_run(self):
        r = self.runner(delay=0.6)
        r.start()
        self.assertTrue(self.pump_until(lambda: r.calls_in_flight() == 1, 5))
        t0 = time.monotonic()
        self.assertTrue(r.kill())                                  # 호출은 아직 시작 전이라 끊을 프로세스가 없다
        self.assertTrue(self.pump_until(lambda: not r.is_running(), 15), "끊기를 보냈는데 호출이 끝나지 않음(뒤늦게 뜬 프로세스가 살아 있음)")
        self.assertLess(time.monotonic() - t0, 10)

    def test_kill_while_the_process_is_running_ends_it_at_once(self):
        r = self.runner(delay=0)
        r.start()
        self.assertTrue(self.pump_until(lambda: r.calls_in_flight() == 1 and self.client._active, 10))
        r.kill()
        self.assertTrue(self.pump_until(lambda: not r.is_running(), 10))

    def test_the_retry_thread_stops_when_the_run_is_over(self):
        r = self.runner(delay=0)
        r.start()
        self.assertTrue(self.pump_until(lambda: self.client._active, 10))
        r.kill()
        self.assertTrue(self.pump_until(lambda: not r.is_running(), 10))
        time.sleep(0.6)
        self.assertFalse([t for t in threading.enumerate() if t.name == "ai-kill-retry" and t.is_alive()])


if __name__ == "__main__":
    unittest.main()
