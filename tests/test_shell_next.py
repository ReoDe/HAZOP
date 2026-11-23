"""'다음에 할 일' 읽기(next, hazop/shell/api_next.py, 규격 HZ-DSN-06 §3.1·G1 엔진 쪽). 실행: python -m unittest tests.test_shell_next

(1) 규칙 표의 차례가 규격 §3.1 표와 같다. (2) 실제 프로젝트 꼴에서 엔진 값대로 나온다: 도면 없음, 등록 직후(표제란), 다시 확인, 반영 실패, 작업 중.
(3) 영역이 바뀌었다고 알리면 next도 알린다. (4) 읽기는 파일을 쓰지 않는다. 저장은 임시 작업 루트에만 한다. 실제 구독 호출 없음.
"""

import os
import re
import shutil
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.app import data  # noqa: E402
from hazop.shell import api, api_next  # noqa: E402
from tests.test_screen_words import BANNED  # noqa: E402
from tests.test_shell_auto_catch_up import Base as AutoBase  # noqa: E402
from tests.test_shell_catch_up import PID  # noqa: E402

SPEC_ORDER = ["apply_failed", "no_sheets", "recheck", "titleblock", "ai_candidates", "sheet_confirm", "nodes_none", "nodes_draft",
              "nodes_unrun", "results_unjudged", "ie_draft"]
GO = re.compile(r"^(panel:[a-z]+(#[a-z_]+)?|queue:(ai|lost)|confirm:[a-z_]+\.[a-z_]+)$")


class RulesTest(unittest.TestCase):
    def test_the_order_matches_the_spec_table(self):
        self.assertEqual([r[0] for r in api_next.RULES], SPEC_ORDER)

    def test_everything_at_once_comes_in_that_order(self):
        f = {"apply_failed": True, "sheets": 0, "running": [], "lost_members": 2, "lost_refs": 1, "lost_nodes": ["S1"], "titleblock": 1,
             "ai_candidates": 3, "sheet_confirm": 2, "sheets_confirmed": 1, "nodes_total": 0, "nodes_draft": 2, "nodes_unrun": 1,
             "results_unjudged": 4, "ie_draft": 1}
        kinds = [i["kind"] for i in api_next.items(f)]
        self.assertEqual(kinds, [k for k in SPEC_ORDER if k != "sheet_confirm"], "표제란이 남으면 쪽 확정은 아직 띄우지 않는다")
        rc = next(i for i in api_next.items(f) if i["kind"] == "recheck")
        self.assertEqual((rc["count"], rc["text"], rc["tone"]), (3, "도면이 바뀌어 3곳을 다시 확인해야 합니다", "warn"))
        self.assertIn("S1", rc["detail"])

    def test_nothing_to_do(self):
        out = api_next.items({"sheets": 2, "running": []})
        self.assertEqual([i["kind"] for i in out], ["none"])
        self.assertEqual(out[0]["text"], "지금 할 일이 없습니다")

    def test_no_sheets_waits_while_a_drawing_is_being_read(self):
        self.assertNotIn("no_sheets", [i["kind"] for i in api_next.items({"sheets": 0, "running": [{"kind": "register"}]})])

    def test_texts_are_screen_words_and_targets_are_well_formed(self):
        f = {k: 1 for k in ("titleblock", "ai_candidates", "nodes_draft", "nodes_unrun", "results_unjudged", "ie_draft", "lost_members")}
        f.update(apply_failed=True, sheets=0, running=[], sheets_confirmed=1, nodes_total=0)
        for i in api_next.items(f) + [api_next.NONE_ITEM]:
            for w in BANNED:
                self.assertNotIn(w, i["text"])
            self.assertRegex(i["action"]["go"], GO)


class EmptyProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-next-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        p.start()
        self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.events = []
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events.append)
        self.engine.settings.update(project_id="P-EMPTY", reviewer_name="검토자A")

    def read(self):
        import json
        r = api.ReadApi(self.engine).read(["next"], {})
        return json.loads(r.body.decode("utf-8"))

    def test_no_drawings_says_so_first(self):
        out = self.read()
        self.assertEqual(out["items"][0]["kind"], "no_sheets")
        self.assertIsNone(out["running"])

    def test_a_running_job_shows_its_progress(self):
        started, release = threading.Event(), threading.Event()

        def work(progress):
            progress("SNP-M-102를 읽고 있습니다", 2, 3)
            started.set()
            release.wait(5)
        self.engine.start_job("등록", work)
        self.assertTrue(started.wait(5))
        out = self.read()
        release.set()
        self.engine.wait_jobs(5)
        self.assertEqual((out["running"]["label"], out["running"]["done"], out["running"]["total"]), ("SNP-M-102를 읽고 있습니다", 2, 3))
        self.assertNotIn("no_sheets", [i["kind"] for i in out["items"]], "읽는 중에는 '도면이 없습니다'를 띄우지 않는다")

    def test_an_area_change_also_announces_next(self):
        self.engine.changed("nodes")
        topics = [e.get("topic") for e in self.events if e.get("t") == "changed"]
        self.assertEqual(topics, ["nodes", "next"])
        self.events.clear()
        self.engine.changed("chat")
        self.assertEqual([e.get("topic") for e in self.events if e.get("t") == "changed"], ["chat"])


class StudyProjectTest(AutoBase):
    def setUp(self):
        super().setUp()
        # 이 틀은 프로젝트 그래프만 바꿔 넣어 도면 그래프 폴더가 없다: 도면 한 장이 등록된 것으로 본다
        p = mock.patch.object(self.engine, "graph_names", lambda: {self.g["graph_id"]: "T-1"})
        p.start()
        self.addCleanup(p.stop)

    def kinds(self):
        return [i["kind"] for i in api_next.summary(self.engine)["items"]]

    def test_lost_members_after_a_re_extract_come_first(self):
        self.re_extract_losing_v2()
        data.notify_graph_changed(PID)
        out = api_next.summary(self.engine)["items"][0]
        self.assertEqual(out["kind"], "recheck")
        self.assertGreaterEqual(out["count"], 1)
        self.assertEqual(out["action"]["go"], "queue:lost")

    def test_a_failed_automatic_migration_comes_before_everything(self):
        with mock.patch.object(data, "migrate_study", side_effect=OSError("디스크 가득")):
            self.re_extract()
            data.notify_graph_changed(PID)
        self.assertEqual(self.kinds()[0], "apply_failed")

    def test_waiting_for_an_ai_job_is_not_called_a_failure(self):
        self.re_extract()
        with self.engine._lock:
            self.engine._catching.add(PID)
        self.assertNotIn("apply_failed", self.kinds())

    def test_reading_writes_no_file(self):
        def snap():
            out = {}
            for d, _s, files in os.walk(self.tmp):
                for n in files:
                    p = os.path.join(d, n)
                    out[p] = os.stat(p).st_mtime_ns
            return out
        before = snap()
        api_next.summary(self.engine)
        self.assertEqual(snap(), before)


class RegisteredDrawingTest(unittest.TestCase):
    def test_right_after_registering_the_first_thing_is_the_title_block(self):
        from tests.test_shell_corrections import RegisteredPathTest
        t = RegisteredPathTest("test_a_web_edit_rebuilds_the_sheet_once")
        t.setUp()
        try:
            out = api_next.summary(t.engine)["items"]
            self.assertEqual(out[0]["kind"], "titleblock", out)
            self.assertEqual(out[0]["action"]["go"], "panel:drawings#titleblock")
            self.assertNotIn("sheet_confirm", [i["kind"] for i in out], "표제란 전에는 쪽 확정을 띄우지 않는다")
        finally:
            t.doCleanups()


if __name__ == "__main__":
    unittest.main()
