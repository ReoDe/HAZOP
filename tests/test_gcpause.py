"""큰 자료를 지을 때 순환 수거를 멈추는 장치(hazop.gcpause)가 상태를 되돌려 놓고 결과를 바꾸지 않는지. 실행: python -m unittest tests.test_gcpause"""

import gc
import os
import sys
import threading
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import gcpause  # noqa: E402


class PausedTest(unittest.TestCase):
    def setUp(self):
        self.was = gc.isenabled()
        gc.enable()
        self.addCleanup(lambda: gc.enable() if self.was else gc.disable())

    def test_off_inside_on_after(self):
        with gcpause.paused():
            self.assertFalse(gc.isenabled())
        self.assertTrue(gc.isenabled())

    def test_nested_calls_turn_it_back_on_only_at_the_outermost_exit(self):
        with gcpause.paused():
            with gcpause.paused():
                self.assertFalse(gc.isenabled())
            self.assertFalse(gc.isenabled())
        self.assertTrue(gc.isenabled())

    def test_an_error_still_turns_it_back_on(self):
        with self.assertRaises(RuntimeError):
            with gcpause.paused():
                raise RuntimeError("x")
        self.assertTrue(gc.isenabled())

    def test_it_does_not_turn_on_what_the_caller_had_turned_off(self):
        gc.disable()
        with gcpause.paused():
            self.assertFalse(gc.isenabled())
        self.assertFalse(gc.isenabled())

    def test_overlapping_threads_keep_it_off_until_the_last_one_leaves(self):
        inside, release, seen = threading.Event(), threading.Event(), []

        def worker():
            with gcpause.paused():
                inside.set()
                release.wait(5)

        t = threading.Thread(target=worker)
        t.start()
        self.assertTrue(inside.wait(5))
        with gcpause.paused():
            pass                       # 이 호출이 먼저 나와도
        seen.append(gc.isenabled())    # 다른 스레드가 아직 안에 있으니 꺼진 채여야 한다
        release.set()
        t.join(5)
        self.assertEqual(seen, [False])
        self.assertTrue(gc.isenabled())


if __name__ == "__main__":
    unittest.main()
