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


class SaveRaceTest(Base):
    def test_b_two_saves_of_one_drawing_keep_both_candidates(self):
        """A가 지문을 확인한 뒤 교체하기 전에 B가 같은 판을 읽고 확인·교체하면, 틈을 막지 않은 쓰기는 B의 후보를 잃는다."""
        a_at_replace, b_checked = threading.Event(), threading.Event()
        real_replace, real_fp = store_io.os.replace, store_io.fingerprint
        who = threading.local()

        def replace(src, dst):
            if getattr(who, "name", None) == "A" and not a_at_replace.is_set():
                a_at_replace.set()
                b_checked.wait(1.0)          # 틈을 막았으면 B가 확인에 들어오지 못해 1초 뒤 그대로 간다
            return real_replace(src, dst)

        def fingerprint(path):
            out = real_fp(path)
            if getattr(who, "name", None) == "B":
                b_checked.set()
            return out

        def save(tag, cand_id):
            who.name = tag
            cand = ar.make_candidate(cand_id, "tag", self.valves[0], "tag", ["V9" + cand_id[-1]], 0.9, "시험")
            ar.merge_and_save(self.name, self.ex, {"candidates": [cand], "stats": {"calls": 1}})

        with mock.patch.object(store_io.os, "replace", replace), mock.patch.object(store_io, "fingerprint", fingerprint):
            ta = threading.Thread(target=save, args=("A", "t-1"))
            ta.start()
            self.assertTrue(a_at_replace.wait(5))
            tb = threading.Thread(target=save, args=("B", "t-2"))
            tb.start()
            ta.join(10)
            tb.join(10)
        doc = ar.load_doc(self.name)
        self.assertEqual(sorted(c["cand_id"] for c in doc["candidates"]), ["t-1:tag", "t-2:tag"])
        self.assertEqual(len(doc["runs"]), 2)


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

    def test_stats_saved_in_runs_hold_no_callables(self):
        st = ar.run(self.ex, StubClient(good_answers, errors=["transient"]), cap=5, recheck=0, should_stop=lambda: False)["stats"]
        json.dumps(st)


if __name__ == "__main__":
    unittest.main()
