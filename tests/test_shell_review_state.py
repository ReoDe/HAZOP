"""도면별 AI 검토 상태(api_aireview.overview의 review, HZ-DSN-06 §3.7 U10). 실행: python -m unittest tests.test_shell_review_state

가짜 구독 클라이언트로 aireview.run을 불러 not_run → waiting → running → candidates → partial·done, nothing, failed, 다시 추출 뒤 not_run,
같은 도면 두 번 시작은 busy를 본다. 실제 구독 호출 없음. 저장은 임시 작업 루트에만.
"""

import json
import os
import time
import unittest
from unittest import mock

from hazop.extract import ai_review as ar
from hazop.shell import api_aireview as AR, api_next
from tests import test_shell_aireview as TA
from tests.test_ai_review import StubClient


def tearDownModule():
    TA.tearDownModule()


class ReviewStateTest(TA.Base):
    def setUp(self):
        super().setUp()
        self.later = []
        self.engine._run_jobs = lambda job_id, fn: self.later.append(fn)      # 작업을 바로 돌리지 않고 붙잡아 둔다(기다림을 보려고)

    def row(self):
        r = json.loads(AR.read(self.engine, ["aireview"], {}).body.decode("utf-8"))
        return next(d for d in r["drawings"] if d["graph_id"] == self.gid)

    def conn_ver(self):
        return json.loads(AR.read(self.engine, ["aireview", "estimate"], {"cap": "2"}).body.decode("utf-8"))["conn"]["conn_ver"]

    def start(self, client):
        self.engine.ai = TA.FakeAi(client)
        with mock.patch.object(ar, "plan", lambda its, cap=ar.DEFAULT_CAP, batch=ar.DEFAULT_BATCH, _p=ar.plan: _p(its, cap, 2)):
            out = self.call("aireview.run", graph_ids=[self.gid], cap=2, conn_ver=self.conn_ver())
        self.assertTrue(out["ok"], out)
        return out

    def run_held(self):
        with mock.patch.object(ar, "plan", lambda its, cap=ar.DEFAULT_CAP, batch=ar.DEFAULT_BATCH, _p=ar.plan: _p(its, cap, 2)):
            while self.later:
                self.later.pop(0)()

    def test_the_whole_path_not_run_waiting_running_candidates_partial(self):
        r = self.row()
        self.assertEqual(r["review"], "not_run")
        self.assertGreater(r["calls"], 0)
        seen = []

        def answers(request):
            seen.append(self.row()["review"])
            return TA.kind_answers(request)
        self.start(StubClient(answers))
        self.assertEqual(self.row()["review"], "waiting")
        self.assertEqual(self.row()["ahead"], 0)
        busy = self.call("aireview.run", graph_ids=[self.gid], cap=2, conn_ver=self.conn_ver())
        self.assertEqual(busy["error"]["code"], "busy", "기다리는 도면을 다시 시작하면 busy")
        self.run_held()
        self.assertTrue(seen and set(seen) == {"running"}, seen)
        r = self.row()
        self.assertEqual((r["review"], r["calls"]), ("candidates", 2))
        self.assertGreater(r["left"], 0)
        ids = [c["cand_id"] for g in self.view()["groups"] for c in g["items"]]
        self.assertTrue(self.call("aireview.reject", graph_id=self.gid, cand_ids=ids, ver=self.view()["ver"])["ok"])
        r = self.row()
        self.assertEqual(r["review"], "partial", "후보를 다 판정했는데 물을 곳이 남음")
        self.assertGreater(r["left"], 0)

    def test_done_when_nothing_is_left(self):
        doc = ar.new_doc(self.name, self.ex)
        ar.merge_run(doc, {"candidates": [], "stats": {"calls": 3, "left": 0}})
        ar.save_doc(doc)
        self.assertEqual(self.row()["review"], "done")

    def test_nothing_to_ask(self):
        with mock.patch.object(AR, "_left", lambda engine, name: (0, 0)):
            self.assertEqual(self.row()["review"], "nothing")

    def test_failed_run_is_shown_until_the_next_start(self):
        self.start(StubClient(TA.kind_answers))
        with mock.patch.object(AR, "run_review", side_effect=RuntimeError("연결이 끊겼습니다")):
            self.run_held()
        self.assertTrue([e for e in self.events.items if e.get("name") == "job.failed"])
        self.assertEqual(self.row()["review"], "failed")
        self.start(StubClient(TA.kind_answers))
        self.assertEqual(self.row()["review"], "waiting", "다시 시작하면 실패 표시를 지운다")

    def test_re_extract_makes_it_not_run_again(self):
        doc = ar.new_doc(self.name, self.ex)
        ar.merge_run(doc, {"candidates": [], "stats": {"calls": 3, "left": 0}}, at="2026-01-01T00:00:00Z")
        ar.save_doc(doc)
        from hazop.app import data
        p = data.extraction_path(self.name)
        os.utime(p, (time.time(), time.time()))
        self.assertEqual(self.row()["review"], "not_run")

    def test_next_shows_unreviewed_then_candidates(self):
        items = api_next.summary(self.engine)["items"]
        kinds = [i["kind"] for i in items]
        un = next(i for i in items if i["kind"] == "ai_unreviewed")
        self.assertEqual(un["action"], {"label": "AI 검토 시작", "go": "confirm:aireview.run", "target": self.gid})
        self.assertIn("아직 AI 검토를 하지 않았습니다", un["text"])
        if "titleblock" in kinds:
            self.assertLess(kinds.index("titleblock"), kinds.index("ai_unreviewed"))
        self.seed([self.tag(1, self.valves[0], "V901")])
        items = api_next.summary(self.engine)["items"]
        self.assertNotIn("ai_unreviewed", [i["kind"] for i in items])
        c = next(i for i in items if i["kind"] == "ai_candidates")
        self.assertEqual(c["action"], {"label": "검토하기", "go": "queue:ai", "target": self.gid})
        self.assertIn("AI 후보 1건을 확인해 주세요", c["text"])


if __name__ == "__main__":
    unittest.main()
