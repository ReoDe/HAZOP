"""run_ci의 시험 모듈 시간 한도(scripts/run_ci.py ModuleWatch). 실행: python -m unittest tests.test_run_ci_watch

검토 2026-11-14: 새 화면이 기본 시작이 된 뒤 앱을 띄우는 시험이 이벤트 루프에서 끝나지 않아 run_ci가 한 모듈에서 영원히 멈췄다.
이제 한도를 넘으면 그 모듈을 실패로 적고 다음으로 간다.
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import run_ci  # noqa: E402


def fake_discover(*_a, **_k):
    """멈추는 시험 하나와 통과하는 시험 하나를 모듈 둘로 낸다(시험 목록에 걸리지 않게 여기서 클래스를 만든다)."""
    class HangsInTheEventLoop(unittest.TestCase):
        def test_exec_never_returns(self):
            from hazop.app import make_application
            make_application(["test"]).exec()

    class Quick(unittest.TestCase):
        def test_passes(self):
            pass

    hang, quick = unittest.TestSuite(), unittest.TestSuite()
    hang.addTest(HangsInTheEventLoop("test_exec_never_returns"))
    quick.addTest(Quick("test_passes"))
    top = unittest.TestSuite()
    top.addTest(hang)
    top.addTest(quick)
    return top


class ModuleWatchTest(unittest.TestCase):
    def test_the_watch_fires_after_the_limit_and_forces_after_the_grace_and_cancel_stops_it(self):
        forced = []
        with mock.patch("sys.stdout", open(os.devnull, "w")), mock.patch.object(run_ci.faulthandler, "dump_traceback"):
            watch = run_ci.ModuleWatch("tests.fake", 0.2, forced.append, grace=0.2).start()
            time.sleep(0.15)
            self.assertFalse(watch.fired)
            time.sleep(0.8)
        self.assertTrue(watch.fired)
        self.assertEqual(forced, ["tests.fake"])
        quiet = []
        again = run_ci.ModuleWatch("tests.fake2", 0.2, quiet.append, grace=0.2).start()
        again.cancel()
        time.sleep(0.6)
        self.assertEqual((again.fired, quiet), (False, []))

    def test_a_module_that_ends_the_moment_the_loop_is_quit_is_never_forced_later(self):
        """한도가 지난 순간 모듈이 끝나 cancel()이 먼저 불려도(앞서 run_ci 전체가 60초 뒤 강제 종료로 끊긴 일) 둘째 타이머가 나가지 않는다."""
        forced = []
        watch = run_ci.ModuleWatch("tests.fake", 0.05, forced.append, grace=0.15)
        with mock.patch.object(run_ci, "_quit_qt", watch.cancel), mock.patch.object(run_ci.faulthandler, "dump_traceback"),                 mock.patch("sys.stdout", open(os.devnull, "w")):
            watch.start()
            time.sleep(0.5)
        self.assertEqual(forced, [])

    def test_a_module_stuck_in_the_event_loop_is_ended_marked_failed_and_the_next_module_runs(self):
        with mock.patch.object(unittest.defaultTestLoader, "discover", fake_discover), mock.patch.object(run_ci, "MODULE_TIMEOUT_S", 2), \
                mock.patch("sys.stderr", open(os.devnull, "w")):
            started = time.time()
            result, modules = run_ci.run_unittests()
        self.assertLess(time.time() - started, 30, "멈추지 않고 돌아온다")
        names = [m[0] for m in modules]
        self.assertEqual(len(names), 2, modules)
        bad = [t.id() for t, _ in result.failures]
        self.assertTrue(any("모듈 시간 초과" in b for b in bad), bad)
        self.assertEqual(modules[1][2], 0, "다음 모듈은 그대로 통과한다")
        self.assertGreaterEqual(modules[0][2], 1, "멈춘 모듈은 실패로 적힌다")

    def test_a_module_that_cannot_be_ended_writes_the_summary_runs_the_checks_apart_and_exits_failed(self):
        result = unittest.TextTestResult(unittest.runner._WritelnDecorator(open(os.devnull, "w")), True, 1)
        modules = [("tests.ok", 3, 0, 0, 1.0)]
        calls = []
        written = []

        class Done(Exception):
            pass

        def fake_exit(code):
            calls.append(("exit", code))
            raise Done()

        def fake_run(cmd, **kw):
            calls.append(("run", cmd[1:]))
            return mock.Mock(returncode=0)
        with mock.patch.object(run_ci.subprocess, "run", fake_run), mock.patch.object(run_ci.os, "_exit", fake_exit),                 mock.patch.object(run_ci, "write_summary", written.append), mock.patch("sys.stdout", open(os.devnull, "w")):      # 시험이 CI 기록에 가짜 '강제 종료' 줄을 남기지 않게
            with self.assertRaises(Done):
                run_ci._force_finish("tests.stuck", result, modules, 5)
        self.assertEqual(calls[0][0], "run")
        self.assertIn("--checks-only", calls[0][1][1:], "검사 스크립트 단계만 따로 돈다")
        self.assertEqual(calls[-1], ("exit", 1))
        self.assertIn("tests.stuck.모듈 시간 초과", written[0])
        self.assertEqual(modules[-1][0], "tests.stuck")


if __name__ == "__main__":
    unittest.main()
