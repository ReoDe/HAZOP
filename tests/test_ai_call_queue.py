"""구독 AI 호출을 한꺼번에 여러 개 돌리지 않는지와 일시 오류를 견디는지. 실행: python -m unittest tests.test_ai_call_queue

AI는 부르지 않는다(가짜 클라이언트). 작업은 실제 스레드로 돌린다(엔진 기본 run_jobs). 본다:
- (a) AI 검토 작업 두 개를 잇달아 시작해도 호출은 한 번에 하나이고, 뒤 작업은 '앞 작업을 기다리는 중'을 보인다.
- (b) 같은 도면 후보 문서를 두 쪽이 동시에 저장해도 한쪽 후보를 잃지 않는다(지문 확인과 교체 사이의 틈). 같은 도면 두 번째 실행은 busy.
- (c) 추출 뒤 자동 검토·AI 분석도 같은 차례를 탄다. 기다리는 작업도 멈추기가 바로 먹는다.
- 일시 오류(rate_limited·transient·timeout)는 기다렸다 다시 묻고, 다시 묻기도 상한에 센다. 한도·초과 사용은 그대로 멈춘다.
"""

import json
import threading
import time
import unittest
from unittest import mock

from hazop import store_io
from hazop.extract import ai_review as ar
from hazop.shell import api, api_aireview as AR
from tests.test_ai_review import StubClient, good_answers
from tests.test_shell_aireview import Base, FakeAi, kind_answers, tearDownModule  # noqa: F401  (tearDownModule: 틀 정리)


class BlockingClient(StubClient):
    """release가 서기 전까지 호출이 끝나지 않는다. 동시에 돈 호출 수의 최댓값을 센다."""

    def __init__(self):
        super().__init__(kind_answers)
        self.release = threading.Event()
        self.active = self.peak = 0
        self._guard = threading.Lock()

    def analyze(self, request):
        with self._guard:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            self.release.wait(10)
            return super().analyze(request)
        finally:
            with self._guard:
                self.active -= 1


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class QueueBase(Base):
    def setUp(self):
        super().setUp()
        self.engine = api.Engine(settings_path=self.engine.settings_path, emit=self.events)   # 실제 스레드로 작업을 돌린다
        self.engine.settings["reviewer_name"] = "검토자A"
        self.client = BlockingClient()
        self.engine.ai = FakeAi(self.client)
        self.addCleanup(self.finish)

    def finish(self):
        self.client.release.set()
        self.assertTrue(self.engine.wait_jobs(20), "작업이 끝나지 않음")

    def review_job(self):
        return self.engine.start_job("AI 검토", lambda progress: AR.run_review(self.engine, [self.gid], 1, progress), kind="ai_review")

    def texts(self, job):
        return [(e["data"] or {}).get("text") or "" for e in self.events.items
                if e.get("name") == "job.progress" and (e.get("data") or {}).get("id") == job]

    def ended(self, job):
        return next((e for e in self.events.items if e.get("name") in ("job.done", "job.failed") and e["data"]["id"] == job), None)


class SerialTest(QueueBase):
    def test_a_two_ai_reviews_call_one_at_a_time(self):
        first = self.review_job()
        self.assertTrue(wait_for(lambda: self.client.active == 1))
        second = self.review_job()
        time.sleep(0.5)
        self.assertEqual(self.client.peak, 1, "두 작업의 구독 호출이 겹침")
        self.assertTrue(wait_for(lambda: any("기다리는 중" in t for t in self.texts(second))), self.texts(second))
        self.client.release.set()
        self.assertTrue(self.engine.wait_jobs(20))
        self.assertEqual((self.ended(first)["name"], self.ended(second)["name"]), ("job.done", "job.done"))
        self.assertEqual(len(self.client.requests), 2)
        self.assertEqual(self.client.peak, 1)

    def test_c_auto_review_after_register_waits_its_turn(self):
        from hazop.app import data
        from hazop.shell import register_flow
        self.engine.settings["extract_ai_review"] = True
        self.engine.settings["extract_ai_cap"] = 1
        ex = data.read_json(data.extraction_path(self.name))
        first = self.review_job()
        self.assertTrue(wait_for(lambda: self.client.active == 1))
        auto = self.engine.start_job("등록", lambda progress: register_flow.review_if_wanted(self.engine, [(self.name + "-copy", ex)], progress))
        time.sleep(0.5)
        self.assertEqual(self.client.peak, 1, "자동 검토가 AI 검토와 겹침")
        self.assertTrue(wait_for(lambda: any("기다리는 중" in t for t in self.texts(auto))), self.texts(auto))
        self.client.release.set()
        self.assertTrue(self.engine.wait_jobs(20))
        self.assertEqual(self.ended(first)["name"], "job.done")
        self.assertTrue(self.ended(auto)["data"]["result"]["ran"], self.ended(auto))
        self.assertEqual(self.client.peak, 1)

    def test_c_analysis_run_waits_its_turn(self):
        from hazop.shell import analysis_run, api_results

        def fake_run(client, ns, pg, units, intent_of, progress, should_stop, on_saved=None, test=False):
            client.analyze({"context": json.dumps({"items": []}), "user": "", "system": ""})
            return {"calls": 1, "rest": [], "reason": "done"}

        unit = {"node_id": "S1", "deviation_ids": ["D01"], "unit_id": "u1"}
        with mock.patch.object(api_results, "_plan", lambda engine, a: ({}, {"graph_id": "g"}, None, [unit])), \
                mock.patch.object(analysis_run, "run", fake_run):
            first = self.review_job()
            self.assertTrue(wait_for(lambda: self.client.active == 1))
            out = self.engine.dispatch("results.run", {"scope": "all"})
            self.assertTrue(out["ok"], out)
            second = out["data"]["job"]
            time.sleep(0.5)
            self.assertEqual(self.client.peak, 1, "AI 분석이 AI 검토와 겹침")
            self.assertTrue(wait_for(lambda: any("기다리는 중" in t for t in self.texts(second))), self.texts(second))
            self.client.release.set()
            self.assertTrue(self.engine.wait_jobs(20))
        self.assertEqual((self.ended(first)["name"], self.ended(second)["name"]), ("job.done", "job.done"))
        self.assertEqual(self.client.peak, 1)

    def test_waiting_review_reads_the_drawing_after_its_turn(self):
        """기다리는 동안 다시 추출되면(추출 결과가 바뀌면) 차례를 잡은 뒤의 판으로 묻는다."""
        from hazop.app import data
        self.review_job()
        self.assertTrue(wait_for(lambda: self.client.active == 1))
        second = self.review_job()
        self.assertTrue(wait_for(lambda: any("기다리는 중" in t for t in self.texts(second))))
        path = data.extraction_path(self.name)
        ex = data.read_json(path)
        for it in ar.collect_items(ex):
            cx, cy = (it["bbox"][0] + it["bbox"][2]) / 2.0, (it["bbox"][1] + it["bbox"][3]) / 2.0
            ex.setdefault("texts", []).append({"text": "ZZ999", "geometry": {"x": cx, "y": cy, "width": 1, "height": 1}})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        self.client.release.set()
        self.assertTrue(self.engine.wait_jobs(20))
        self.assertEqual(self.ended(second)["name"], "job.done", self.ended(second))
        later = self.client.requests[1:]
        self.assertTrue(later)
        self.assertTrue(all("ZZ999" in r["context"] for r in later), "기다리기 전에 읽은 낡은 판으로 물음")

    def test_analysis_stop_reaches_it_while_waiting(self):
        from hazop.shell import analysis_run, api_results
        calls = []

        def fake_run(client, ns, pg, units, intent_of, progress, should_stop, on_saved=None, test=False):
            calls.append(1)
            return {"calls": 0, "rest": [], "reason": "done"}

        unit = {"node_id": "S1", "deviation_ids": ["D01"], "unit_id": "u1"}
        with mock.patch.object(api_results, "_plan", lambda engine, a: ({}, {"graph_id": "g"}, None, [unit])),                 mock.patch.object(analysis_run, "run", fake_run):
            self.review_job()
            self.assertTrue(wait_for(lambda: self.client.active == 1))
            second = self.engine.dispatch("results.run", {"scope": "all"})["data"]["job"]
            self.assertTrue(wait_for(lambda: any("기다리는 중" in t for t in self.texts(second))))
            self.assertTrue(self.engine.dispatch("results.stop", {})["data"]["stopping"])
            self.assertTrue(wait_for(lambda: self.ended(second) is not None, 3), "기다리는 분석이 멈추지 않음")
            self.assertTrue(self.ended(second)["data"].get("stopped"), self.ended(second))
            self.assertFalse(self.engine.analysis.running)
            self.assertEqual(self.client.active, 1, "AI 검토는 그대로 돈다(분석 멈춤은 분석만)")
        self.assertEqual(calls, [])

    def test_stop_reaches_a_waiting_job_at_once(self):
        self.review_job()
        self.assertTrue(wait_for(lambda: self.client.active == 1))
        second = self.review_job()
        self.assertTrue(wait_for(lambda: any("기다리는 중" in t for t in self.texts(second))))
        self.engine.stop_jobs()
        self.assertTrue(wait_for(lambda: self.ended(second) is not None, 3), "기다리는 작업이 멈추지 않음")
        self.assertTrue(self.ended(second)["data"].get("stopped"), self.ended(second))
        self.assertEqual(self.client.active, 1, "앞 작업의 호출은 그대로 돈다")
        self.assertEqual(len(self.client.requests), 0)


class BusyTest(QueueBase):
    def conn_ver(self):
        r = json.loads(AR.read(self.engine, ["aireview", "estimate"], {"cap": "1"}).body.decode("utf-8"))
        return r["conn"]["conn_ver"]

    def test_b_second_run_on_the_same_drawing_is_busy(self):
        ver = self.conn_ver()
        out = self.engine.dispatch("aireview.run", {"graph_ids": [self.gid], "cap": 1, "conn_ver": ver})
        self.assertTrue(out["ok"], out)
        self.assertTrue(wait_for(lambda: self.client.active == 1))
        again = self.engine.dispatch("aireview.run", {"graph_ids": [self.gid], "cap": 1, "conn_ver": ver})
        self.assertEqual((again["ok"], again.get("error", {}).get("code")), (False, "busy"), again)
        self.client.release.set()
        self.assertTrue(self.engine.wait_jobs(20))
        out = self.engine.dispatch("aireview.run", {"graph_ids": [self.gid], "cap": 1, "conn_ver": ver})   # 끝나면 다시 받는다
        self.assertTrue(out["ok"], out)


    def test_auto_review_skips_the_drawing_a_manual_review_holds(self):
        from hazop.app import data
        from hazop.shell import register_flow
        self.engine.settings["extract_ai_review"] = True
        self.engine.settings["extract_ai_cap"] = 1
        ex = data.read_json(data.extraction_path(self.name))
        out = self.engine.dispatch("aireview.run", {"graph_ids": [self.gid], "cap": 1, "conn_ver": self.conn_ver()})
        self.assertTrue(out["ok"], out)
        self.assertTrue(wait_for(lambda: self.client.active == 1))
        only = register_flow.review_if_wanted(self.engine, [(self.name, ex)], lambda *a: None)
        self.assertEqual((only["ran"], only["skipped"], only.get("busy")), (False, "busy", [self.name]), only)
        self.client.release.set()                       # 아래 실행이 차례를 기다리지 않게 앞 작업을 끝낸다
        self.assertTrue(self.engine.wait_jobs(20))
        held = self.engine.reserve_review([self.name])  # 수동 검토가 그 도면을 잡은 채로
        try:
            mixed = register_flow.review_if_wanted(self.engine, [(self.name, ex), (self.name + "-copy", ex)], lambda *a: None)
        finally:
            self.engine.release_review(held)
        self.assertTrue(mixed["ran"], mixed)
        self.assertEqual(mixed.get("busy"), [self.name], mixed)   # 건너뛴 도면이 결과에 남는다


class GateTest(unittest.TestCase):
    def test_same_thread_taking_the_turn_again_fails_at_once(self):
        from hazop.shell import ai_gate
        gate = ai_gate.Gate()
        started = time.monotonic()
        with gate.turn("앞", lambda: False, RuntimeError):
            with self.assertRaises(ai_gate.Reentry):
                with gate.turn("다시", lambda: False, RuntimeError):
                    pass
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(gate.waiting(), [])
        with gate.turn("뒤", lambda: False, RuntimeError):   # 차례가 비어 다음 작업이 잡는다
            pass


class SaveRaceTest(Base):
    def test_b_two_saves_of_one_drawing_keep_both_candidates(self):
        """A가 지문을 확인한 뒤 교체하기 전에 B가 같은 판을 읽고 저장에 들어온다. A는 B가 확인 지점(잠금이 있으면 잠금 앞)에
        닿은 것을 사건으로 본 뒤에 교체한다. 틈을 막지 않은 쓰기는 B가 같은 판으로 확인을 통과해 A나 B의 후보를 잃는다."""
        a_at_replace, b_arrived = threading.Event(), threading.Event()
        real_replace, real_fp = store_io.os.replace, store_io.fingerprint
        real_lock = getattr(store_io, "_path_lock", None)
        who = threading.local()

        class Announce:
            def __init__(self, lk):
                self.lk = lk

            def __enter__(self):
                b_arrived.set()          # B가 확인 지점 앞(잠금)에 닿음. 잠금이 있으면 A가 놓을 때까지 여기서 기다린다
                self.lk.acquire()

            def __exit__(self, *exc):
                self.lk.release()

        def path_lock(path):
            lk = real_lock(path)
            return Announce(lk) if getattr(who, "name", None) == "B" else lk

        def replace(src, dst):
            if getattr(who, "name", None) == "A" and not a_at_replace.is_set():
                a_at_replace.set()
                self.assertTrue(b_arrived.wait(10), "B가 저장에 닿지 않음")
            return real_replace(src, dst)

        def fingerprint(path):
            if getattr(who, "name", None) == "B":
                b_arrived.set()          # 잠금이 없으면 B는 곧장 지문을 확인한다
            return real_fp(path)

        errors = []

        def save(tag, cand_id):
            who.name = tag
            try:
                cand = ar.make_candidate(cand_id, "tag", self.valves[0], "tag", ["V9" + cand_id[-1]], 0.9, "시험")
                ar.merge_and_save(self.name, self.ex, {"candidates": [cand], "stats": {"calls": 1}})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        patches = [mock.patch.object(store_io.os, "replace", replace), mock.patch.object(store_io, "fingerprint", fingerprint)]
        if real_lock is not None:
            patches.append(mock.patch.object(store_io, "_path_lock", path_lock))
        for p in patches:
            p.start()
        try:
            ta = threading.Thread(target=save, args=("A", "t-1"))
            ta.start()
            self.assertTrue(a_at_replace.wait(10))
            tb = threading.Thread(target=save, args=("B", "t-2"))
            tb.start()
            ta.join(20)
            tb.join(20)
        finally:
            for p in patches:
                p.stop()
        self.assertFalse(ta.is_alive() or tb.is_alive(), "저장 스레드가 끝나지 않음")
        self.assertEqual(errors, [])
        doc = ar.load_doc(self.name)
        self.assertEqual(sorted(c["cand_id"] for c in doc["candidates"]), ["t-1:tag", "t-2:tag"])
        self.assertEqual(len(doc["runs"]), 2)


class RealWaitTest(unittest.TestCase):
    """기다림을 대역으로 바꾸지 않고, 실제로 기다리는 동안 멈추기가 바로 먹는지 본다."""

    def test_stop_during_a_real_wait(self):
        from tests.test_ai_review import ex_fixture
        client = StubClient(good_answers, errors=["rate_limited"])
        started = time.monotonic()
        threading.Timer(0.3, lambda: stop.set()).start()
        stop = threading.Event()
        with mock.patch.dict(ar.RETRY_DELAYS, {"rate_limited": (30,)}):
            st = ar.run(ex_fixture(), client, cap=5, recheck=0, should_stop=stop.is_set)["stats"]
        took = time.monotonic() - started
        self.assertLess(took, 3, "30초 기다림이 멈추기에 끊기지 않음")
        self.assertGreaterEqual(took, 0.25)
        self.assertEqual((st["calls"], st["retries"], st["stopped"]), (1, 0, True))


class RetryTest(unittest.TestCase):
    """ai_review.run 안의 다시 묻기. 기다림은 대역으로 바꿔 시간을 쓰지 않는다."""

    def setUp(self):
        from tests.test_ai_review import ex_fixture
        self.ex = ex_fixture()
        self.waits = []
        p = mock.patch.object(ar, "_wait", lambda seconds, should_stop: self.waits.append(seconds) or not (should_stop and should_stop()))
        p.start()
        self.addCleanup(p.stop)

    def test_transient_kinds_wait_and_ask_again(self):
        for kind in ("rate_limited", "transient", "timeout"):
            client = StubClient(good_answers, errors=[kind])
            self.waits.clear()
            out = ar.run(self.ex, client, cap=5, recheck=0)
            st = out["stats"]
            self.assertEqual(st["retries"], 1, kind)
            self.assertEqual(self.waits, [ar.RETRY_DELAYS[kind][0]], kind)
            self.assertEqual(len(client.requests), st["calls"], kind)
            self.assertFalse(st["halted"], kind)
            self.assertEqual(st["left"], 0, kind)           # 실패한 묶음도 다시 물어 남은 항목이 없다
            self.assertTrue(out["candidates"], kind)

    def test_retry_counts_against_the_cap(self):
        client = StubClient(good_answers, errors=["transient"])
        st = ar.run(self.ex, client, cap=1, recheck=0)["stats"]
        self.assertEqual((st["calls"], st["retries"], len(client.requests)), (1, 0, 1))

    def test_retry_has_an_upper_bound(self):
        client = StubClient(good_answers, errors=["rate_limited"] * 10)
        st = ar.run(self.ex, client, cap=50, recheck=0)["stats"]
        self.assertEqual(st["retries"], len(ar.RETRY_DELAYS["rate_limited"]))
        self.assertTrue(st["halted"])                       # 같은 오류가 이어지면 지금처럼 멈춘다
        self.assertEqual(len(client.requests), st["calls"])

    def test_halting_kinds_do_not_retry(self):
        for kind in ("limit_reached", "overage"):
            client = StubClient(good_answers, errors=[kind])
            self.waits.clear()
            st = ar.run(self.ex, client, cap=5, recheck=0)["stats"]
            self.assertEqual((st["calls"], st.get("retries"), st["halted"], self.waits), (1, 0, True, []), kind)

    def test_stop_during_the_wait_asks_no_more(self):
        client = StubClient(good_answers, errors=["rate_limited"])
        stop = {"on": False}

        def wait(seconds, should_stop):
            stop["on"] = True
            return not should_stop()
        with mock.patch.object(ar, "_wait", wait):
            st = ar.run(self.ex, client, cap=5, recheck=0, should_stop=lambda: stop["on"])["stats"]
        self.assertEqual((st["calls"], st["retries"], st["stopped"]), (1, 0, True))

    def test_retry_does_not_push_the_next_batch_over_the_cap(self):
        """다시 묻기로 상한을 다 쓰면 다음 묶음을 부르지 않는다(도면 상한·실행 상한 모두)."""
        for kw in ({"cap": 2}, {"cap": 20, "budget": 2}):
            client = StubClient(good_answers, errors=["transient"])
            st = ar.run(self.ex, client, recheck=0, batch=2, **kw)["stats"]
            self.assertGreaterEqual(st["planned_calls"], 2, kw)
            self.assertEqual((st["calls"], len(client.requests), st["retries"]), (2, 2, 1), kw)

    def test_retries_in_many_batches_stay_within_the_cap(self):
        """묶음마다 '일시 오류 한 번 뒤 성공'이 되풀이돼도 호출은 상한을 넘지 않는다."""
        planned = ar.run(self.ex, StubClient(good_answers), cap=50, recheck=0, batch=1)["stats"]["planned_calls"]
        self.assertGreaterEqual(planned, 3)
        client = StubClient(good_answers, errors=["transient", None] * 50)
        st = ar.run(self.ex, client, cap=planned, recheck=0, batch=1)["stats"]
        self.assertEqual((st["calls"], len(client.requests)), (planned, planned))
        self.assertGreater(st["left"], 0)                    # 다시 묻기로 쓴 만큼 남은 항목이 남는다
        self.assertFalse(st["halted"])

    def test_later_passes_stop_at_the_cap_after_retries(self):
        """첫 묻기 뒤 단계(넓혀 다시 묻기·규칙 다시 확인·나누기·연결 묻기)도 누적 호출로 상한을 지킨다."""
        from hazop.extract import ai_connect, ai_split
        for mod in (ai_connect, ai_split):
            self.assertIn('stats["calls"] >= limit', open(mod.__file__, encoding="utf-8").read(), mod.__name__)
        import inspect
        for fn in (ar._wide_pass, ar._recheck_pass):
            self.assertIn('stats["calls"] >= limit', inspect.getsource(fn), fn.__name__)

    def test_same_error_streak_runs_across_drawings(self):
        """같은 오류 3번이면 멈춤은 도면이 바뀌어도 이어진다. cap=2 세 도면에서 timeout만 오면 세 번째 호출에서 멈춘다."""
        from types import SimpleNamespace
        from hazop.shell import ai_image_flow
        client = StubClient(good_answers, errors=["timeout"] * 20)
        engine = SimpleNamespace(settings={ai_image_flow.KEY: False})
        pages = [("A", self.ex), ("B", self.ex), ("C", self.ex)]
        with mock.patch.object(ar, "decided_targets", lambda name: set()), mock.patch.object(ar, "merge_and_save", lambda *a, **k: None):
            done, _ = ai_image_flow.run_pages(engine, pages, client, 2, ar.RUN_CAP, None, None)
            self.assertEqual(len(client.requests), 3)
            self.assertTrue(done[-1][2]["halted"])
            client = StubClient(good_answers, errors=["timeout"] * 20)
            many = ar.run_many(pages, client, cap=2, save=False)
            self.assertEqual(len(client.requests), 3)
            self.assertTrue(many[-1][2]["halted"])

    def test_stats_saved_in_runs_hold_no_callables(self):
        st = ar.run(self.ex, StubClient(good_answers, errors=["transient"]), cap=5, recheck=0, should_stop=lambda: False)["stats"]
        json.dumps(st)


if __name__ == "__main__":
    unittest.main()
