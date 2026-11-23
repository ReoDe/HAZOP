"""AI 분석 실행이 받은 답을 결과 파일에 저장하지 못할 때. 실행: python -m unittest tests.test_analysis_save_failed

AI는 부르지 않는다(ai_cells.run_unit 대역). 본다: 저장이 OSError로 실패하거나 충돌이 세 번 이어져도 방금 받은 답은
결과 폴더 unsaved/에 '저장 실패' 사유와 함께 남고, 그 단위의 칸은 이어서 실행할 칸에 들며, 실행은 save_failed로 멈춘다
(그 뒤 단위를 부르지 않는다). unsaved/ 쓰기마저 실패하면 지금처럼 작업이 실패로 끝난다.
"""

import json
import os
import stat
import tempfile
import time
import unittest
from unittest import mock

from hazop import store_io
from hazop.study import results as res
from hazop.shell import analysis_run
from tests.test_shell_results import Base, FakeAi, fake_run_unit


class SaveFailedTest(Base):
    def setUp(self):
        super().setUp()
        self.appdata = os.path.join(self.tmp, "appdata")             # 둘째 자리(설정 폴더 쪽)도 임시 폴더로
        p = mock.patch.dict(os.environ, {"APPDATA": self.appdata})
        p.start()
        self.addCleanup(p.stop)
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

    def last(self):
        return self.engine.analysis.last

    def test_non_os_errors_while_saving_keep_the_answer(self):
        """결과를 읽거나 합치다 ValueError(새 판 파일·깨진 JSON·결과에 없는 칸)가 나도 그 답을 남기고 멈춘다."""
        for target, patch_at in ((res, "load_fp"), (analysis_run.ai_cells, "apply_unit")):
            self.events.items.clear()
            seen, run = self.calls()
            real = getattr(target, patch_at)

            def failing(*a, _real=real, **k):
                if len(seen) >= 2:
                    raise ValueError("결과 파일을 읽을 수 없음")
                return _real(*a, **k)
            with mock.patch.object(target, patch_at, failing):
                self.run_with(run)
            ended = self.ended()
            self.assertEqual(ended["name"], "job.done", (patch_at, ended["data"]))
            done = ended["data"]["result"]
            self.assertEqual((done["reason"], len(seen), len(done["unsaved"])), ("save_failed", 2, 1), patch_at)
            self.assertEqual((done["ok_calls"], done["failed_calls"]), (1, 1), "저장하지 못한 단위는 반영한 수에 세지 않는다")

    def test_a_failing_final_read_still_reports_save_failed(self):
        seen, run = self.calls()
        real = res.load_fp

        def load_fp(*a, **k):
            if seen:
                raise OSError("읽을 수 없음")
            return real(*a, **k)
        with mock.patch.object(res, "load_fp", load_fp):
            self.run_with(run)
        ended = self.ended()
        self.assertEqual(ended["name"], "job.done", ended["data"])
        self.assertEqual(self.last()["reason"], "save_failed")
        self.assertEqual(len(self.last()["unsaved"]), 1)

    def test_kept_answer_falls_back_to_the_settings_folder(self):
        seen, run = self.calls()
        real = store_io.write_json
        results_root = os.path.dirname(res.store_path(self.project, self.ns["graph_id"]))

        def write_json(path, *a, **k):
            if path.startswith(os.path.join(results_root, "unsaved")):
                raise OSError(28, "디스크 공간이 부족합니다")
            return real(path, *a, **k)
        with mock.patch.object(res, "save_fp", side_effect=OSError(28, "디스크 공간이 부족합니다")),                 mock.patch.object(store_io, "write_json", write_json):
            self.run_with(run)
        done = self.ended()["data"]["result"]
        self.assertEqual(done["reason"], "save_failed")
        self.assertEqual(done["unsaved_where"], ["settings"])
        self.assertTrue(done["unsaved"][0].startswith(os.path.join(self.appdata, "HAZOP")), done["unsaved"])
        with open(done["unsaved"][0], encoding="utf-8") as fh:
            kept = json.load(fh)
        self.assertEqual(kept["project_id"], self.project)
        self.assertEqual(kept["set_rev"], self.ns.get("set_rev") or 0)
        self.assertTrue(kept["prompt_sha"])
        self.assertFalse({"key", "api_key", "token", "authorization"} & {k.lower() for k in kept}, "키·토큰은 남기지 않는다")

    def test_save_failed_and_halted_together_keep_the_limit(self):
        seen = []
        inner = fake_run_unit(kind="limit_reached", limit={"resets_at": "2026-11-24T09:00:00Z"})

        def run(client, unit, ctx, devs, at):
            seen.append(1)
            return inner(client, unit, ctx, devs, at)
        with mock.patch.object(res, "save_fp", side_effect=PermissionError(13, "액세스가 거부되었습니다")):
            self.run_with(run)
        done = self.ended()["data"]["result"]
        self.assertEqual((done["reason"], done["halted"], done["error_kind"]), ("save_failed", True, "limit_reached"), done)
        self.assertEqual(done["limit"], {"resets_at": "2026-11-24T09:00:00Z"})

    def test_test_runs_keep_answers_beside_the_test_file(self):
        ur = fake_run_unit()(None, {"unit_id": "u1", "node_id": "S1", "deviation_ids": ["D01"]}, {}, [], "2026-11-23T00:00:00Z")
        path, where = analysis_run._keep_unsaved(self.ns, self.project, ur, True, why=analysis_run.SAVE_FAILED_WHY)
        self.assertEqual(where, "results")
        test_dir = os.path.dirname(res.test_store_path(self.project, self.ns["graph_id"]))
        self.assertTrue(path.startswith(os.path.join(test_dir, "unsaved")), path)
        self.assertNotEqual(os.path.dirname(res.store_path(self.project, self.ns["graph_id"])), test_dir)

    def test_if_keeping_also_fails_the_job_fails_as_before(self):
        seen, run = self.calls()
        real = store_io.write_json

        def write_json(path, *a, **k):
            if os.sep + "unsaved" in path:
                raise PermissionError(13, "액세스가 거부되었습니다")
            return real(path, *a, **k)
        with mock.patch.object(res, "save_fp", side_effect=PermissionError(13, "액세스가 거부되었습니다")), \
                mock.patch.object(store_io, "write_json", write_json):
            self.run_with(run)
        self.assertEqual(self.ended()["name"], "job.failed")
        self.assertFalse(self.engine.analysis.running)


class ReadOnlyTargetTest(unittest.TestCase):
    """대상 파일이 읽기 전용이면 공유 위반과 같은 WinError 5라도 다시 하지 않고 바로 실패한다."""

    def test_read_only_target_fails_at_once(self):
        d = tempfile.mkdtemp(prefix="hazop-ro-")
        path = os.path.join(d, "x.json")
        store_io.write_json(path, {"n": 0})
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(lambda: (os.chmod(path, stat.S_IWRITE | stat.S_IREAD), __import__("shutil").rmtree(d, True)))
        started = time.monotonic()
        with self.assertRaises(PermissionError):
            store_io.write_json(path, {"n": 1})
        self.assertLess(time.monotonic() - started, 0.5, "읽기 전용 대상을 2초 동안 다시 시도함")
        self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
