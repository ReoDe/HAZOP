"""수락 뒤 도면 반영을 짓기 작업으로(입력 연산 U2 셸 몫, 설계 fix-input-ops-design.md §11.3 1~3·§11.5). 실행: python -m unittest tests.test_shell_input_builds

(1) 수락은 그래프를 그 자리에서 다시 만들지 않는다(도면 잠금을 오래 쥐지 않음). 조용해지거나 대기열을 닫으면 한 번 짓는다.
(2) 기준 추출(corrections.ensure_base)은 도면 잠금 밖에서, 그래프 다시 만들기만 잠금 안에서.
(3) 짓는 중 그 도면에 수락이 오면 멈추고, 다시 조용해지면 짓는다. 대기열이 열려 있는 동안은 시작하지 않는다.
(4) 앱을 닫을 때 남은 것은 열 때 찾아 '다음에 할 일'에 올리고, 누르면 짓는다. 저장은 임시 작업 루트에만. 실제 구독 호출 없음.
"""

import os
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop import paths  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.shell import api_inputs, api_next, sheet_refresh  # noqa: E402
from tests.test_shell_aireview import Base  # noqa: E402
from tests import test_shell_drawings as _tsd  # noqa: E402,F401


def tearDownModule():
    _tsd.tearDownModule()
    _tsd._TPL.clear()


class BuildsTest(Base):
    def setUp(self):
        super().setUp()
        self.b = api_inputs.of(self.engine)
        self.b.quiet = 3600            # 시험은 타이머를 기다리지 않고 flush·_tick으로 부른다
        self.addCleanup(lambda: self.b.timer and self.b.timer.cancel())
        self.addCleanup(sheet_refresh.undefer, self.name)
        self.graph = os.path.join(paths.output_root("graph"), self.name, "graph.json")

    def accept(self, n=1):
        self.seed([self.tag(i, self.valves[i], "V90%d" % i) for i in range(1, n + 1)])
        for i in range(1, n + 1):
            out = self.call("aireview.accept", graph_id=self.gid, cand_ids=["t-%d:tag" % i], ver=self.view()["ver"])
            self.assertTrue(out["ok"], out)

    def test_accept_saves_at_once_and_the_graph_waits_for_the_build(self):
        before = os.stat(self.graph).st_mtime_ns
        self.accept(2)
        self.assertEqual(len(self.ops()), 2, "수락은 바로 저장")
        self.assertEqual(os.stat(self.graph).st_mtime_ns, before, "수락마다 그래프를 그 자리에서 다시 만들지 않는다")
        self.assertNotIn("V901", self.graph_text())
        self.assertEqual(self.b.waiting(), [self.name])
        self.assertEqual(self.b.flush(), [self.name])
        self.assertIn("V901", self.graph_text())
        self.assertIn("V902", self.graph_text())
        self.assertEqual(self.b.waiting(), [])
        self.assertFalse(sheet_refresh.graph_stale(self.name), "지은 뒤 낡은 표시가 없다")

    def test_the_base_is_built_outside_the_lock_and_the_graph_inside(self):
        seen = {}

        def fake_base(name, original=None, *, should_stop=None):
            got = []
            t = threading.Thread(target=lambda: got.append(sheet_refresh._LOCKS[name].acquire(timeout=0.5) and sheet_refresh._LOCKS[name].release() is None))
            t.start()
            t.join()
            seen["free"] = got == [True]
            return "none"
        real_refresh = sheet_refresh.refresh

        def checked_refresh(name):
            got = []
            t = threading.Thread(target=lambda: got.append(sheet_refresh._LOCKS[name].acquire(timeout=0.2)))
            t.start()
            t.join()
            seen["held"] = got == [False]
            return real_refresh(name)
        self.accept(1)
        with mock.patch.object(corrections, "ensure_base", fake_base), mock.patch.object(sheet_refresh, "refresh", checked_refresh):
            self.b.flush()
        self.assertEqual(seen, {"free": True, "held": True})

    def test_an_accept_during_the_build_stops_it_and_it_builds_again_later(self):
        self.accept(1)
        calls = []

        def fake_base(name, original=None, *, should_stop=None):
            calls.append(name)
            if len(calls) == 1:
                self.b.note(name)                      # 짓는 중 수락이 옴
                self.assertTrue(should_stop(), "멈춤 신호")
                return "pending"
            return "none"
        before = os.stat(self.graph).st_mtime_ns
        with mock.patch.object(corrections, "ensure_base", fake_base):
            self.b.flush()
            self.assertEqual(os.stat(self.graph).st_mtime_ns, before, "멈춘 짓기는 그래프를 다시 만들지 않는다")
            self.assertEqual(self.b.waiting(), [self.name], "다시 조용해지면 지을 차례")
            self.b.flush()
        self.assertEqual(len(calls), 2)
        self.assertIn("V901", self.graph_text())

    def test_the_queue_holds_the_build_until_it_closes(self):
        self.accept(1)
        self.call("inputs.hold", on=True)
        self.b.quiet = 0
        self.b._tick()
        self.assertNotIn("V901", self.graph_text(), "대기열이 열려 있는 동안은 짓지 않는다")
        self.call("inputs.hold", on=False)
        self.assertIn("V901", self.graph_text(), "대기열을 닫으면 바로 짓는다")

    def test_a_second_accept_does_not_rebuild_the_graph_in_place(self):
        """앞 수락이 남긴 '반영 대기' 표시를 다음 수락(ensure_graph)이 그 자리에서 다시 만들지 않는다."""
        self.accept(1)
        with mock.patch.object(sheet_refresh, "rebuild", side_effect=AssertionError("그 자리에서 다시 만듦")):
            out = self.call("aireview.reject", graph_id=self.gid, cand_ids=["t-1:tag"], ver=self.view()["ver"])
        self.assertTrue(out["ok"], out)

    def test_left_over_inputs_are_found_on_open_and_built_on_press(self):
        with mock.patch.object(corrections, "load", lambda name: {"ops": [{"op_id": "c-0001", "op": "split"}]} if name == self.name else None), \
                mock.patch.object(corrections, "is_input", lambda o: o.get("op") == "split"), \
                mock.patch.object(corrections, "resolve", lambda name, *a, **k: {"inputs": {"waiting": ["c-0001"]}}):
            self.assertEqual(api_inputs.scan_on_open(self.engine), [self.name])
        items = api_next.summary(self.engine)["items"]
        first = next(i for i in items if i["kind"] == "inputs_pending")
        self.assertEqual((first["count"], first["action"]["go"], first["action"]["target"]), (1, "confirm:inputs.build", self.gid))
        built = []
        with mock.patch.object(corrections, "ensure_base", lambda name, original=None, *, should_stop=None: built.append(name) or "ready"):
            out = self.call("inputs.build", graph_id=self.gid)
        self.assertTrue(out["ok"], out)
        self.assertEqual(built, [self.name])
        self.assertNotIn("inputs_pending", [i["kind"] for i in api_next.summary(self.engine)["items"]])


if __name__ == "__main__":
    unittest.main()
