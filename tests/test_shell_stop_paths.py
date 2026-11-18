"""새 화면 실행 길의 멈추기(작업 멈춤 요청)가 멈춘 뒤 호출을 더 내지 않고, 이미 받은 답을 잃지 않는지. 실행: python -m unittest tests.test_shell_stop_paths

새 화면은 이전 화면(AiRunner)처럼 진행 중인 호출을 끊지 않는다: 멈추라는 신호(engine.stop_jobs·분석의 run.stop)는 호출 사이에서만 듣고 진행 중인 호출은
끝까지 받는다(규격 '진행 중인 호출은 끝까지 받는다'). 그래서 '끊을 프로세스를 못 찾는' 틈(4f9ca4a)은 없다. 대신 본다:
- 멈춘 뒤 새 호출이 나가지 않는다(멈춤 신호가 선 뒤 호출은 이미 시작한 하나까지만).
- 멈춰도 그때까지 받은 답은 후보 문서에 저장된다(호출 사이의 진행 알림이 멈춤을 올려 받은 답을 버리지 않는다).
가짜 클라이언트만 쓴다.
"""

import json
import unittest
from unittest import mock

from hazop.extract import ai_review as ar
from hazop.shell import api_aireview as AR
from tests.test_ai_review import StubClient
from tests.test_shell_aireview import Base, FakeAi, kind_answers, tearDownModule  # noqa: F401


class AiReviewStopTest(Base):
    def setUp(self):
        super().setUp()
        self.stopper = {"after": 1}

        def answers(request):
            if len(self.client.requests) >= self.stopper["after"]:
                self.engine.stop_jobs()                       # 호출 도중(응답을 만드는 사이)에 멈추라고 한다: 이 호출은 끝까지 받는다
            return kind_answers(request)
        self.client = StubClient(answers)
        self.engine.ai = FakeAi(self.client)

    def run_job(self):
        est = json.loads(AR.read(self.engine, ["aireview", "estimate"], {"cap": "20"}).body.decode("utf-8"))
        self.events.items.clear()
        out = self.call("aireview.run", graph_ids=[self.gid], cap=20, conn_ver=est["conn"]["conn_ver"])
        self.assertTrue(out["ok"], out)

    def test_stop_during_a_call_sends_no_further_call_and_keeps_the_received_answers(self):
        with mock.patch.object(ar, "DEFAULT_BATCH", 1):        # 호출이 여럿이 되게
            self.run_job()
        self.assertEqual(len(self.client.requests), 1, "멈춘 뒤에는 새 호출이 나가지 않는다")
        doc = ar.load_doc(self.name)
        self.assertIsNotNone(doc, "멈춰도 받은 답은 후보 문서에 저장된다")
        self.assertEqual(doc["runs"][-1]["calls"], 1)
        self.assertTrue(doc["runs"][-1]["stopped"])

    def test_auto_review_after_extraction_stops_the_same_way(self):
        from hazop.shell import api, register_flow
        self.engine.settings["extract_ai_review"] = True

        def progress(text, done=None, total=None):                # 작업 진행 알림과 같은 규칙: 멈춤 요청이 서 있으면 JobStopped
            if self.engine.stop_requested():
                raise api.JobStopped("중지했습니다")
        with mock.patch.object(ar, "DEFAULT_BATCH", 1):
            out = register_flow.review_if_wanted(self.engine, [(self.name, self.ex)], progress)
        self.assertEqual(len(self.client.requests), 1)
        self.assertTrue(out["ran"], out)
        self.assertEqual(ar.load_doc(self.name)["runs"][-1]["calls"], 1)

    def test_a_stop_set_before_the_run_sends_no_call_at_all(self):
        from hazop.shell import ai_image_flow
        self.engine.stop_jobs()
        done, _images = ai_image_flow.run_pages(self.engine, [(self.name, self.ex)], self.client, 20, ar.RUN_CAP, None, self.engine.stop_requested)
        self.assertEqual(self.client.requests, [])
        self.assertEqual(done, [])


if __name__ == "__main__":
    unittest.main()
