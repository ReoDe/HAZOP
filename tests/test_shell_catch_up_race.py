"""자동 판 이전과 ⑤ AI 분석이 겹치지 않는지(081373a 검토 차단 1). 실행: python -m unittest tests.test_shell_catch_up_race

판 이전은 검토구간 집합과 ⑤ 결과의 참조를 새 그래프 판으로 옮긴다. 옛 집합을 쥔 AI 분석이 그 뒤에 결과를 저장하면 옮겨진 참조가 덮이거나 옛 참조가 새로 쓰인다.
그래서 (1) 분석이 도는 동안에는 자동 판 이전이 시간 제한으로 밀고 들어가지 않고, (2) 손으로 누르는 판 이전도 거절하며, (3) 분석을 시작하는 검사와
'도는 중' 표시 사이에 판 이전이 끼면 시작하지 않고, (4) 그래도 분석 중에 집합 판이 바뀌면 분석은 저장하지 않고 멈추며 받은 답은 따로 남긴다.
가짜 AI만 쓴다(실제 구독 호출 없음).
"""

import json
import os
import threading
import time
import unittest
from unittest import mock

from hazop.app import data
from hazop.shell import api_results
from hazop.study import idmap
from hazop.study import results as res
from hazop.study import nodes as sn
from tests.test_shell_auto_catch_up import Base as AutoBase
from tests.test_shell_catch_up import PID, V1_REF
from tests.test_shell_results import FakeAi, fake_run_unit


class Base(AutoBase):
    def setUp(self):
        super().setUp()
        self.engine.ai = FakeAi()
        rpath = res.store_path(PID, self.g["graph_id"])
        with open(rpath, encoding="utf-8") as fh:
            doc = json.load(fh)
        e = doc["cells"][0]["entries"][0]
        e.update(origin="human", status="approved")     # 사람이 쓴 항목: AI 분석이 덮지 않는다(참조만 판 이전 대상)
        res.write(rpath, doc)
        self.rpath = rpath

    def cause_ref(self):
        with open(self.rpath, encoding="utf-8") as fh:
            doc = json.load(fh)
        e = next(x for c in doc["cells"] for x in c["entries"] if x["entry_id"] == "e1")
        return e["cause_refs"][0]["ref"]

    def wait(self, cond, seconds=8):
        """cond가 참이 될 때까지. 뒤에서 판 이전이 파일을 바꾸는 순간 읽기가 Windows 공유 위반으로 한 번 실패할 수 있어 그때는 다시 본다."""
        from hazop.shell import api

        def ok():
            try:
                return cond()
            except api.CommandError:
                return False
        end = time.monotonic() + seconds
        while not ok() and time.monotonic() < end:
            time.sleep(0.05)
        return ok()


class NoPushInTest(Base):
    def test_a_long_running_analysis_is_never_overtaken_by_the_waiting_migration(self):
        self.engine.analysis.running = True
        self.re_extract()
        data.notify_graph_changed(PID)
        real = time.monotonic
        with mock.patch("time.monotonic", lambda: real() + 4000):        # 한 시간이 넘게 지나도
            time.sleep(1.0)
            self.assertTrue(self.stale(), "분석이 도는 동안에는 판 이전을 하지 않는다")
        self.engine.analysis.running = False
        self.assertTrue(self.wait(lambda: not self.stale()), "분석이 끝나면 이어서 한다")

    def test_the_manual_button_is_refused_while_an_analysis_runs(self):
        self.re_extract()
        self.engine.analysis.running = True
        out = self.catch_up()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "busy")
        self.assertTrue(self.stale())
        self.engine.analysis.running = False
        self.assertTrue(self.catch_up()["ok"])


class StartGapTest(Base):
    def test_a_migration_between_the_check_and_the_start_stops_the_start(self):
        """_run은 계획(_plan: 판 검사)을 한 뒤 연결을 보고 '도는 중'을 세운다. 그 사이에 판 이전이 끝나면 옛 집합으로 시작하지 않는다."""
        real_conn = api_results._run_conn

        def conn_then_migrate(engine, units, method=None):
            self.re_extract()
            data.migrate_study(self.g)                   # 다른 스레드의 판 이전이 이 틈에 끝났다
            return real_conn(engine, units, method)
        with mock.patch.object(api_results, "_run_conn", conn_then_migrate), \
                mock.patch("hazop.study.ai_cells.run_unit", fake_run_unit()):
            out = self.engine.dispatch("results.run", {"scope": "all"}, project=PID)
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["error"]["code"], "stale")
        self.assertFalse(self.engine.analysis.running)


class SaveGuardTest(Base):
    def test_an_analysis_does_not_save_after_the_set_moved_to_a_new_version_and_keeps_the_answer(self):
        moved = {}
        inner = fake_run_unit()

        def run_unit(client, unit, ctx, devs, at):
            if not moved:                                 # 첫 호출 도중에 도면이 다시 읽혀 판 이전이 끝났다(어떤 막음도 못 본 경우)
                self.re_extract()
                data.migrate_study(self.g)
                moved["ref"] = self.cause_ref()
            return inner(client, unit, ctx, devs, at)
        with mock.patch("hazop.study.ai_cells.run_unit", run_unit):
            out = self.engine.dispatch("results.run", {"scope": "all"}, project=PID)
        self.assertTrue(out["ok"], out)
        done = [e["data"] for e in self.events if e.get("name") == "job.done"][-1]["result"]
        self.assertNotEqual(moved["ref"], V1_REF, "판 이전이 참조를 옮겼다(시험의 전제)")
        self.assertFalse(idmap.is_tomb(self.cause_ref()), "옮겨진 참조가 묘비로 덮이지 않는다")
        self.assertEqual(self.cause_ref(), moved["ref"])
        self.assertEqual(done["reason"], "stale", done)
        self.assertTrue(done.get("unsaved"), "받은 답은 따로 남긴다")
        for p in done["unsaved"]:
            self.assertTrue(os.path.isfile(p), p)
        with open(done["unsaved"][0], encoding="utf-8") as fh:
            kept = json.load(fh)
        self.assertTrue(kept["cells"], "받은 칸이 그대로 있다")
        self.assertTrue(done["rest"], "그 칸은 이어서 실행할 칸으로 남는다")


class ProjectSwitchTest(Base):
    def test_switching_project_while_waiting_drops_the_old_projects_notice(self):
        self.re_extract_losing_v2()
        self.engine.analysis.running = True
        data.notify_graph_changed(PID)
        self.engine.settings["project_id"] = "OTHER"               # 기다리는 사이에 다른 프로젝트로 바꿈
        self.engine.analysis.running = False
        time.sleep(1.0)
        self.assertEqual(self.lost_events(), [], "다른 프로젝트 화면에 옛 프로젝트의 알림을 띄우지 않는다")

    def test_the_lost_event_names_its_project_and_version(self):
        self.re_extract_losing_v2()
        data.notify_graph_changed(PID)
        d = self.lost_events()[0]["data"]
        self.assertEqual(d["project_id"], PID)
        self.assertEqual(d["graph_version"], self.g["graph_version"])


if __name__ == "__main__":
    unittest.main()
