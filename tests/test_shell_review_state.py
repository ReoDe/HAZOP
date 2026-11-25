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

    # ------------------------------------------------------------ 멈추기·취소(aireview.stop, 실제 창 확인에서 미룬 것)
    def test_cancel_while_waiting_asks_nothing_and_goes_back(self):
        client = StubClient(TA.kind_answers)
        self.start(client)
        self.assertEqual(self.row()["review"], "waiting")
        out = self.call("aireview.stop", graph_id=self.gid)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["was"], "waiting")
        self.run_held()
        self.assertEqual(len(client.requests), 0, "취소한 도면은 묻지 않는다")
        self.assertEqual(self.row()["review"], "not_run")
        failed = [e for e in self.events.items if e.get("name") == "job.failed" and not e["data"].get("stopped")]
        self.assertEqual(failed, [], "취소는 실패가 아니다(차례가 비어 있으면 묻지 않고 끝나고, 기다리는 중이면 '중지'로 끝난다)")

    def test_cancel_while_another_ai_job_holds_the_turn(self):
        import threading
        import time
        release, held = threading.Event(), threading.Event()

        def other():
            with self.engine.ai_turn("다른 AI 작업", lambda *a, **k: None):
                held.set()
                release.wait(20)
        t = threading.Thread(target=other)
        t.start()
        held.wait(10)
        client = StubClient(TA.kind_answers)
        self.start(client)
        runner = threading.Thread(target=self.run_held)
        runner.start()
        time.sleep(0.3)
        self.assertEqual(self.row()["review"], "waiting")
        self.assertTrue(self.call("aireview.stop", graph_id=self.gid)["ok"])
        runner.join(10)
        self.assertFalse(runner.is_alive(), "차례를 기다리던 검토가 취소로 빠지지 않음")
        release.set()
        t.join(10)
        self.assertEqual(len(client.requests), 0)
        self.assertEqual(self.row()["review"], "not_run")

    def test_stop_while_running_ends_after_the_current_call(self):
        def answers(request):
            if not hasattr(self, "_stopped"):
                self._stopped = self.call("aireview.stop", graph_id=self.gid)
            return TA.kind_answers(request)
        client = StubClient(answers)
        self.start(client)
        self.run_held()
        self.assertEqual(self._stopped["data"]["was"], "running")
        self.assertEqual(len(client.requests), 1, "지금 호출 하나를 마치고 멈춤(상한 2회)")
        self.assertIn(self.row()["review"], ("candidates", "partial"))
        self.assertGreater(self.row()["left"] or 0, 0, "남은 곳이 있다")

    def test_stop_on_an_idle_drawing_is_refused(self):
        out = self.call("aireview.stop", graph_id=self.gid)
        self.assertEqual(out["error"]["code"], "not_found")

    def test_stopping_one_drawing_leaves_the_engine_running(self):
        self.start(StubClient(TA.kind_answers))
        self.call("aireview.stop", graph_id=self.gid)
        self.assertFalse(self.engine.stop_requested(), "엔진 전체 멈춤(등록·분석)을 걸지 않는다")

    def test_next_shows_unreviewed_then_candidates(self):
        from unittest import mock
        with mock.patch.object(api_next, "_ai_ready", lambda engine: True):      # AI 연결이 있을 때만 'AI 검토 시작'을 권한다(실제 창 5차)
            items = api_next.summary(self.engine)["items"]
        kinds = [i["kind"] for i in items]
        un = next((i for i in items if i["kind"] == "ai_unreviewed"), None)
        if un is None:                                   # 쪽 확정이 남았으면 그 줄의 곁 단추로 들어간다(실제 창 5차)
            self.assertEqual(items[0]["kind"], "sheet_confirm", kinds)
            self.assertEqual(items[0]["alt"], {"label": "AI 검토 시작", "go": "confirm:aireview.run", "target": self.gid})
        else:
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


class PerDrawingStopTest(TA.Base):
    """검토 지적 1(739ce95): 한 실행에 도면 [A, B, C]가 있을 때 멈추기·취소는 그 도면만. 취소한 도면은 한 번도 묻지 않고, 다른 도면은 그대로 묻는다.
    도면 셋을 따로 만들지 않고 run_pages에 가짜 쪽 셋을 넣고 도면 하나의 실행(ai_review.run)을 호출 세 번짜리 가짜로 바꾼다."""

    def setUp(self):
        super().setUp()
        from hazop.shell import ai_image_flow
        self.flow = ai_image_flow
        self.engine.settings[ai_image_flow.KEY] = False           # 그림 입력 끔(가짜 쪽에는 PDF가 없다)
        self.asked = []
        self.on_call = None

        def fake_run(ex, client, cap=None, budget=None, exclude=None, on_progress=None, should_stop=None, images=None, kinds=None, project_id=None):
            stats = {"calls": 0, "left": 0, "halted": False, "refused": False, "stopped": False}
            for i in range(3):
                if should_stop and should_stop():
                    stats["stopped"] = True
                    stats["left"] = 3 - i
                    break
                self.asked.append(ex["name"])
                stats["calls"] += 1
                if self.on_call:
                    self.on_call(ex["name"], i)
                if on_progress:
                    on_progress(i + 1, 3, 3 - i - 1)
            return {"candidates": [], "stats": stats}
        for p_ in (mock.patch.object(ar, "run", fake_run), mock.patch.object(ar, "merge_and_save", lambda *a, **k: None),
                   mock.patch.object(ar, "decided_targets", lambda name: set())):
            p_.start()
            self.addCleanup(p_.stop)

    def run_three(self, token):
        pages = [(n, {"name": n}) for n in ("A", "B", "C")]
        return self.flow.run_pages(self.engine, pages, object(), 3, 300,
                                   lambda name, d, t, left: AR._progress(self.engine, token, lambda *a, **k: None, name, d, t),
                                   AR._stopper(self.engine, token), skip=AR._skipper(self.engine, token),
                                   on_page=lambda name: AR._page_started(self.engine, token, name))

    def stop(self, name):
        with AR._LIVE_LOCK:
            AR._live(self.engine)["cancel"].add(name)

    def test_stopping_a_stops_only_a(self):
        token = AR._mark_waiting(self.engine, ["A", "B", "C"])
        self.on_call = lambda name, i: self.stop("A") if (name, i) == ("A", 0) else None
        self.run_three(token)
        self.assertEqual(self.asked, ["A", "B", "B", "B", "C", "C", "C"], "A만 멈추고 B·C는 묻는다")

    def test_cancelling_waiting_b_never_asks_b(self):
        token = AR._mark_waiting(self.engine, ["A", "B", "C"])
        self.on_call = lambda name, i: self.stop("B") if (name, i) == ("A", 0) else None
        self.run_three(token)
        self.assertEqual(self.asked, ["A", "A", "A", "C", "C", "C"], "취소한 B는 한 번도 묻지 않고 A·C는 끝까지")

    def test_the_engine_stop_still_stops_everything(self):
        token = AR._mark_waiting(self.engine, ["A", "B", "C"])
        self.on_call = lambda name, i: self.engine.stop_jobs() if (name, i) == ("A", 0) else None
        self.addCleanup(self.engine._stop.clear)
        self.run_three(token)
        self.assertEqual(self.asked, ["A"], "창 닫기 등 엔진 전체 멈춤은 남은 도면을 모두 그만둔다")

    def test_auto_review_drawings_have_no_cancel(self):
        """검토 지적 2: 추출 뒤 자동 검토가 잡은 도면(이 실행 기록 없음)은 aireview.stop이 닿지 않으므로 칩에 취소를 싣지 않는다."""
        held = self.engine.reserve_review([self.name])
        self.addCleanup(self.engine.release_review, held)
        r = json.loads(AR.read(self.engine, ["aireview"], {}).body.decode("utf-8"))
        row = next(d for d in r["drawings"] if d["graph_id"] == self.gid)
        self.assertEqual((row["review"], row["stoppable"]), ("waiting", False))
        self.assertEqual(self.call("aireview.stop", graph_id=self.gid)["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
