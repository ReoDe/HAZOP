"""총괄 검토(2026-11-18) 차단 1~4와 함께 고친 것의 시험. 실행: python -m unittest tests.test_shell_aireview_blockers

1 과금: 추출 뒤 자동 AI 검토와 수동 실행 모두 실제 API 클라이언트 클래스(네트워크는 막음)로는 돌지 않는다.
2 안내 전 전송: 자동 검토는 설정이 명시적으로 켜졌을 때만 그림을 싣고, 수동 실행은 누를 때의 스위치 값을 설정에 적는다.
3 유실: 범례판 출처는 실행 기록과 같은 저장에 들어가 따로 다시 쓰지 않는다.
4 예상 초과: 그림 입력을 만들지 못한 도면은 글로 돌리되 그 도면의 예상 호출 수에서 자른다.
"""

import json
import unittest
from unittest import mock

from hazop.extract import ai_review as ar
from hazop.shell import api, api_aireview as AR
from hazop.study import claude_http
from tests.test_ai_review import StubClient
from tests.test_shell_aireview import FakeAi, kind_answers, tearDownModule  # noqa: F401  (tearDownModule: 틀 정리)
from tests.test_shell_aireview_images import PdfBase


class BlockedHttp(claude_http.ClaudeHttpClient):
    """실제 API 클라이언트 클래스(describe에 via가 없다). 네트워크는 막고 부른 횟수만 센다."""

    def __init__(self):
        super().__init__(key_provider=lambda: "sk-ant-test")
        self.sent = []

    def analyze(self, request):
        self.sent.append(request)
        return {"status": "completed", "error_kind": None, "output": {"answers": []}, "via": "api"}


class FakeConn:
    """AiConnection 대역: 구독·API 클라이언트를 따로 돌려주고 어느 방식으로 불렀는지 남긴다."""

    def __init__(self, subscription, api_client, methods=("subscription", "api")):
        self.clients, self.asked, self._methods, self.method = {"subscription": subscription, "api": api_client}, [], methods, "api"

    def methods(self):
        return self._methods

    def make_client(self, method=None):
        self.asked.append(method)
        return self.clients[method or self.method]


class ConnAi(FakeAi):
    def __init__(self, conn):
        super().__init__(conn.clients["api"])
        self.conn = conn

    def make_client(self):
        return self.conn.make_client()


class BlockerTest(PdfBase):
    def pages(self):
        from hazop.app import data
        return [(self.pname, data.read_json(data.extraction_path(self.pname)))]

    def auto(self):
        from hazop.shell import register_flow
        self.engine.settings["extract_ai_review"] = True
        return register_flow.review_if_wanted(self.engine, self.pages(), lambda *a: None)

    def test_1_auto_review_never_uses_an_api_client(self):
        api_client = BlockedHttp()
        self.engine.ai = FakeAi(api_client)                  # conn이 없는 창구: make_client()가 API 클라이언트를 준다
        out = self.auto()
        self.assertFalse(out["ran"], out)
        self.assertEqual(api_client.sent, [])

    def test_1_auto_review_asks_the_connection_for_subscription(self):
        api_client, sub = BlockedHttp(), StubClient(kind_answers)
        conn = FakeConn(sub, api_client)
        self.engine.ai = ConnAi(conn)
        out = self.auto()
        self.assertTrue(out["ran"], out)
        self.assertEqual(conn.asked, ["subscription"])
        self.assertEqual(api_client.sent, [])
        self.assertTrue(sub.requests)

    def test_1_auto_review_is_skipped_without_a_subscription_method(self):
        api_client = BlockedHttp()
        self.engine.ai = ConnAi(FakeConn(StubClient(kind_answers), api_client, methods=("api",)))
        out = self.auto()
        self.assertFalse(out["ran"])
        self.assertTrue(out["skipped"])
        self.assertEqual(api_client.sent, [])

    def test_1_manual_run_never_uses_an_api_client_either(self):
        api_client = BlockedHttp()
        self.engine.ai = FakeAi(api_client)
        with self.assertRaises(RuntimeError):
            AR.run_review(self.engine, [self.pgid], 20, lambda *a: None)
        self.assertEqual(api_client.sent, [])

    def test_2_auto_review_sends_pictures_only_when_the_setting_is_explicitly_on(self):
        self.engine.settings.pop("ai_review_images", None)      # 값이 없다 = 안내를 본 적 없다
        self.assertTrue(self.auto()["ran"])
        self.assertTrue(self.client.requests)
        self.assertFalse(any(q.get("images") for q in self.client.requests))
        self.client.requests.clear()
        self.engine.settings["ai_review_images"] = True
        self.auto()
        self.assertTrue(any(q.get("images") for q in self.client.requests))

    def test_2_pressing_run_writes_the_switch_value_explicitly(self):
        self.engine.settings.pop("ai_review_images", None)
        self.run_job([self.pgid])
        self.assertIs(self.engine.settings.get("ai_review_images"), True)
        self.assertTrue(self.call("extract.set_ai_review", images=False)["ok"])
        self.run_job([self.pgid])
        self.assertIs(self.engine.settings.get("ai_review_images"), False)

    def test_2_state_tells_the_drawing_panel_only_an_explicit_on(self):
        self.engine.settings.pop("ai_review_images", None)
        self.assertIs(api.ReadApi(self.engine).state()["ai_review_images"], False)
        self.engine.settings["ai_review_images"] = True
        self.assertIs(api.ReadApi(self.engine).state()["ai_review_images"], True)

    def test_3_the_picture_info_is_saved_with_the_run_in_one_write(self):
        from hazop.shell import ai_image_flow
        self.assertFalse(hasattr(ai_image_flow, "stamp_run"), "실행 기록을 따로 다시 쓰지 않는다")
        saves, orig = [], ar.save_doc
        with mock.patch.object(ar, "save_doc", lambda d: (saves.append(d["extraction_name"]), orig(d))[1]):
            self.run_job([self.pgid])
        self.assertEqual(saves, [self.pname])
        self.assertIn("legend_source", ar.load_doc(self.pname)["runs"][-1]["images"])

    def test_3_each_run_keeps_its_own_picture_info(self):
        self.run_job([self.pgid])
        self.call("extract.set_ai_review", images=False)
        self.run_job([self.pgid])
        runs = ar.load_doc(self.pname)["runs"]
        self.assertEqual(len(runs), 2)
        self.assertIn("legend_source", runs[0]["images"])
        self.assertNotIn("images", runs[1])

    def test_4_failed_picture_input_is_cut_to_the_drawings_estimate(self):
        from hazop.extract import ai_images
        est = {p["graph_id"]: p for p in self.estimate()["pages"]}[self.pgid]["calls"]
        with mock.patch.object(ai_images, "image_input_for", side_effect=RuntimeError("그림 실패")), \
                mock.patch.object(ar, "DEFAULT_BATCH", 1):      # 글 입력이 호출을 많이 쓰는 경우(그림 입력 예상은 IMAGE_BATCH라 그대로)
            done = self.run_job([self.pgid])
        self.assertGreater(done["calls"], 0)
        self.assertLessEqual(done["calls"], est)
        self.assertTrue(ar.load_doc(self.pname)["runs"][-1]["images"]["failed"])
        self.assertEqual(self.view_of(self.pgid)["last_run"]["legend"], "그림을 만들지 못해 글만 보냄")

    def test_x_project_drawing_list_failure_is_remembered_not_retried(self):
        from hazop.shell import ai_image_flow
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("도면 목록 실패")
        f = ai_image_flow.Factory(self.engine)
        with mock.patch.object(self.engine, "graph_names", boom):
            self.assertEqual(f.drawings(), [])
            self.assertEqual(f.drawings(), [])
        self.assertEqual(len(calls), 1)

    def test_x_the_text_only_reason_matches_the_drawing_kind(self):
        from hazop.app import data
        by = {p["graph_id"]: p for p in self.estimate()["pages"]}
        self.assertIn("PDF 도면이 아니라", by[self.gid]["text_reason"])
        self.assertIsNone(by[self.pgid]["text_reason"])
        ex = data.read_json(data.extraction_path(self.pname))
        ex["source"]["file"] = "없는/원본.pdf"
        with open(data.extraction_path(self.pname), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        by = {p["graph_id"]: p for p in self.estimate()["pages"]}
        self.assertIn("원본 PDF가 없어", by[self.pgid]["text_reason"])

    def test_x_no_picture_input_is_built_once_the_run_budget_is_spent(self):
        from hazop.extract import ai_images
        real = ai_images.image_input_for
        with mock.patch.object(ar, "RUN_CAP", 1), mock.patch.object(ai_images, "image_input_for", wraps=real) as spy:
            done = self.run_job([self.gid, self.pgid])
        self.assertEqual(done["calls"], 1)
        spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
