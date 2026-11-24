"""⑤ AI 분석이 실제 프로젝트 꼴에서 정상으로 시작하는지와, 거절은 정말 집합이 바뀐 때만 나오는지. 실행: python -m unittest tests.test_shell_run_start

fb176b1은 분석 시작 직전(판 이전 잠금 안)에 계획에 쓴 집합과 지금 파일이 같은 판인지 다시 본다. 이 검사가 '견줄 수 없는' 꼴(옛 판에서 만들어 판 이전을 거친
집합, 집합 판 표지가 없는 옛 파일)을 다름으로 보면 분석이 '다시 눌러 주세요'로 영영 돌지 않는다. 여기서는 그런 꼴에서 끝까지 도는 것과, AI 차례를 기다리는
사이 다른 작업이 집합을 고친 때만 부르지 않고 멈추는 것을 고정한다. 가짜 AI만 쓴다(실제 구독 호출 없음). 저장은 임시 작업 루트에만 한다.
"""

import json
import threading
import time
import unittest
from unittest import mock

from hazop.study import nodes as sn
from tests.test_shell_catch_up import PID
from tests.test_shell_catch_up_race import Base
from tests.test_shell_results import fake_run_unit


class RunStartTest(Base):
    def run_all(self):
        with mock.patch("hazop.study.ai_cells.run_unit", fake_run_unit()):
            out = self.engine.dispatch("results.run", {"scope": "all"}, project=PID)
        self.assertTrue(out["ok"], out)
        self.assertTrue(self.engine.wait_jobs(20))
        return [e["data"] for e in self.events if e.get("name") == "job.done"][-1]["result"]

    def test_a_confirmed_set_starts_and_finishes(self):
        done = self.run_all()
        self.assertEqual(done["reason"], "done", done)
        self.assertGreaterEqual(done["calls"], 1)

    def test_a_set_made_on_an_older_version_and_brought_up_starts(self):
        self.re_extract()
        self.assertTrue(self.catch_up()["ok"])
        ns = sn.read_as_is(self.g)
        self.assertTrue(any(h.get("op") == "migrate_version" for h in ns["history"]), "판 이전을 거친 집합(시험의 전제)")
        done = self.run_all()
        self.assertEqual(done["reason"], "done", done)

    def test_an_old_file_without_a_set_revision_is_refused_by_the_reader_not_by_the_start_check(self):
        """집합 판 표지(set_rev)가 없는 파일은 읽기(모양 검사)가 거절해 분석 계획부터 서지 않는다. 시작 검사가 따로 만드는 거절이 아니다.
        읽기가 받아 주는 꼴이면 끝까지 돌아야 한다."""
        path = sn.store_path(PID, self.g["graph_id"])
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc.pop("set_rev", None)                       # 집합 판 표지가 생기기 전 파일
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        try:
            sn.read_as_is(self.g)
        except ValueError:
            out = self.engine.dispatch("results.run_plan", {"scope": "all"}, project=PID)
            self.assertFalse(out["ok"])
            self.assertNotIn("분석을 준비하는 사이", out["error"]["message"])
            return
        done = self.run_all()
        self.assertEqual(done["reason"], "done", done)


class WaitingTurnTest(Base):
    def setUp(self):
        super().setUp()
        import os
        from hazop.shell import api
        from tests.test_shell_results import FakeAi
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings3.json"), emit=self.events.append)    # 작업을 실제 스레드로 돌린다
        self.engine.settings.update(project_id=PID, reviewer_name="검토자A")
        self.engine.ai = FakeAi()
        self.addCleanup(lambda: self.engine.wait_jobs(20))

    def hold_turn(self):
        held, release = threading.Event(), threading.Event()

        def hold():
            with self.engine.ai_gate.turn("AI 검토", lambda: False, lambda: RuntimeError("stop")):
                held.set()
                release.wait(10)
        threading.Thread(target=hold, daemon=True).start()
        self.assertTrue(held.wait(5))
        return release

    def start_waiting(self, calls):
        inner = fake_run_unit()

        def run_unit(*a):
            calls.append(1)
            return inner(*a)
        p = mock.patch("hazop.study.ai_cells.run_unit", run_unit)
        p.start()
        self.addCleanup(p.stop)
        out = self.engine.dispatch("results.run", {"scope": "all"}, project=PID)
        self.assertTrue(out["ok"], out)
        return out["data"]["job"]

    def done(self):
        self.assertTrue(self.engine.wait_jobs(20))
        return [e["data"] for e in self.events if e.get("name") == "job.done"][-1]["result"]

    def test_waiting_for_the_turn_without_any_change_runs_normally(self):
        release = self.hold_turn()
        calls = []
        self.start_waiting(calls)
        time.sleep(0.5)
        self.assertEqual(calls, [], "차례를 기다리는 중")
        release.set()
        d = self.done()
        self.assertEqual(d["reason"], "done", d)
        self.assertTrue(calls)

    def test_an_edit_while_waiting_stops_it_without_calling(self):
        release = self.hold_turn()
        calls = []
        self.start_waiting(calls)
        path = sn.store_path(PID, self.g["graph_id"])
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["set_rev"] = (doc.get("set_rev") or 0) + 1      # 기다리는 사이 다른 작업이 구간을 고쳤다
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        release.set()
        d = self.done()
        self.assertEqual((d["reason"], d["calls"]), ("stale", 0), d)
        self.assertEqual(calls, [], "옛 집합으로 AI를 부르지 않는다")
        self.assertTrue(d["rest"], "남은 칸은 이어서 실행으로 남는다")
        self.assertFalse(self.engine.analysis.running)


if __name__ == "__main__":
    unittest.main()
