"""AI 분석 실행이 받은 답을 결과 파일에 저장하지 못할 때. 실행: python -m unittest tests.test_analysis_save_failed

AI는 부르지 않는다(ai_cells.run_unit 대역). 본다: 저장이 OSError로 실패하거나 충돌이 세 번 이어져도 방금 받은 답은
결과 폴더 unsaved/에 '저장 실패' 사유와 함께 남고, 그 단위의 칸은 이어서 실행할 칸에 들며, 실행은 save_failed로 멈춘다
(그 뒤 단위를 부르지 않는다). unsaved/ 쓰기마저 실패하면 지금처럼 작업이 실패로 끝난다.
"""

import json
import os
import unittest
from unittest import mock

from hazop import store_io
from hazop.study import results as res
from hazop.shell import analysis_run
from tests.test_shell_results import Base, FakeAi, fake_run_unit


class SaveFailedTest(Base):
    def setUp(self):
        super().setUp()
        self.engine.ai = FakeAi()
        p = mock.patch.object(analysis_run, "contexts", lambda units, ns, pg, intent_of: {u["node_id"]: {} for u in units})
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, run_unit):
        with mock.patch("hazop.study.ai_cells.run_unit", run_unit):
            return self.call("results.run", {"scope": "all"})

    def calls(self):
        seen = []
        inner = fake_run_unit()

        def run(client, unit, ctx, devs, at):
            seen.append(unit["unit_id"])
            return inner(client, unit, ctx, devs, at)
        return seen, run

    def ended(self):
        return [e for e in self.events.items if e.get("name") in ("job.done", "job.failed")][-1]

    def check_kept(self, seen, done):
        self.assertEqual(done["reason"], "save_failed", done)
        self.assertEqual(len(seen), 1, "저장하지 못한 뒤 다음 단위를 부르지 않는다")
        self.assertEqual(len(done["unsaved"]), 1, done)
        with open(done["unsaved"][0], encoding="utf-8") as fh:
            kept = json.load(fh)
        self.assertEqual((kept["kind"], kept["unit_id"]), ("hazop_unsaved_analysis", seen[0]))
        self.assertIn("저장", kept["why"])
        self.assertTrue(kept["cells"], "받은 답이 그대로 남는다")
        cells = {tuple(c) for c in done["rest"]}
        for did in kept["cells"]:
            self.assertIn((kept["node_id"], did), cells, "저장하지 못한 칸은 이어서 실행할 칸이다")
        planned = self.call("results.run_plan", {"scope": "all"})["data"]["calls"]
        self.assertEqual(done["planned"], planned)

    def test_os_error_keeps_the_answer_and_stops(self):
        seen, run = self.calls()
        with mock.patch.object(res, "save_fp", side_effect=PermissionError(13, "액세스가 거부되었습니다")):
            r = self.run_with(run)
        self.assertTrue(r["ok"], r)
        ended = self.ended()
        self.assertEqual(ended["name"], "job.done", ended["data"])
        self.check_kept(seen, ended["data"]["result"])

    def test_three_conflicts_keep_the_answer_and_stop(self):
        seen, run = self.calls()
        with mock.patch.object(res, "save_fp", side_effect=store_io.Conflict("겹침")):
            self.run_with(run)
        ended = self.ended()
        self.assertEqual(ended["name"], "job.done", ended["data"])
        self.check_kept(seen, ended["data"]["result"])

    def test_if_keeping_also_fails_the_job_fails_as_before(self):
        seen, run = self.calls()
        real = store_io.write_json

        def write_json(path, *a, **k):
            if os.sep + "unsaved" + os.sep in path:
                raise PermissionError(13, "액세스가 거부되었습니다")
            return real(path, *a, **k)
        with mock.patch.object(res, "save_fp", side_effect=PermissionError(13, "액세스가 거부되었습니다")), \
                mock.patch.object(store_io, "write_json", write_json):
            self.run_with(run)
        self.assertEqual(self.ended()["name"], "job.failed")
        self.assertFalse(self.engine.analysis.running)


if __name__ == "__main__":
    unittest.main()
