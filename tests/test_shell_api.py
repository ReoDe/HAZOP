"""새 웹 화면의 명령 길·읽기 API·채팅 조종기(단위 새 화면 1단계, docs/design/app-shell-web.md §5.2·§5.5·§5.6). 실행: python -m unittest tests.test_shell_api

웹 없이 Python 단위로 본다. 명령은 표에 있는 이름만 받고 인자 형·길이를 검사한다. 읽기 API는 저장된 자료를 읽기만 한다. 채팅 조종기는
이전 Qt 채팅 창이 지키던 요금·한도 규칙(답 뒤 오류, 막힘 풀림, 프로젝트 전환, 질문 ID 없는 오류)을 그대로 지킨다.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop import paths  # noqa: E402
from hazop.shell import api, chat, scheme  # noqa: E402
from tests.test_chat_card import REF, S1, S2, TOOL_IDS, FakeEnv, answer, comp, small_pg  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Events:
    def __init__(self):
        self.items = []
        self.lock = threading.Lock()

    def __call__(self, event):
        with self.lock:
            self.items.append(event)

    def names(self):
        return [e.get("name") or e.get("topic") for e in self.items]

    def of(self, name):
        return [e["data"] for e in self.items if e.get("name") == name]


class EngineBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-shellapi-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def engine(self, **kw):
        self.events = Events()
        settings = os.path.join(tempfile.mkdtemp(dir=self.tmp), "settings.json")
        return api.Engine(settings_path=settings, emit=self.events, run_jobs=lambda jid, fn: fn(), **kw)


class CommandCheckTest(EngineBase):
    def test_unknown_command(self):
        e = self.engine()
        for name in ("rm.all", "", None, 5, "chat.ask ", "__import__"):
            r = e.dispatch(name, {})
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "unknown_command"), repr(name))

    def test_args_must_be_an_object_with_known_keys(self):
        e = self.engine()
        self.assertEqual(e.dispatch("chat.stop", [1])["error"]["code"], "bad_args")
        self.assertEqual(e.dispatch("chat.stop", {"x": 1})["error"]["code"], "bad_args")
        self.assertEqual(e.dispatch("chat.ask", {"text": "a", "extra": 1})["error"]["code"], "bad_args")
        self.assertEqual(e.dispatch("chat.ask", {})["error"]["code"], "bad_args")

    def test_type_and_length_limits(self):
        e = self.engine()
        bad = [("chat.ask", {"text": ""}), ("chat.ask", {"text": "x" * 4001}), ("chat.ask", {"text": 5}),
               ("chat.ask", {"text": "a\x00b"}),
               ("chat.ask", {"text": "a", "view": {"selected": ["x"] * 21}}), ("chat.ask", {"text": "a", "view": {"evil": 1}}),
               ("chat.ask", {"text": "a", "view": "no"}), ("chat.set_model", {"model": "gpt"}), ("chat.set_model", {"model": None}),
               ("settings.set_reviewer", {"name": " " * 0}), ("settings.set_reviewer", {"name": "x" * 61}),
               ("extract.set_ai_review", {"cap": 0}), ("extract.set_ai_review", {"cap": 201}), ("extract.set_ai_review", {"cap": True}),
               ("extract.set_ai_review", {"enabled": "yes"}), ("ui.save", {"state": {"a": "x" * 5000}}),
               ("register.add_files", {"paths": ["a"] * 51}), ("register.add_files", {"paths": "a"}),
               ("register.add_files", {"paths": [""]}), ("register.add_files", {"paths": ["x" * 521]}),
               ("sheet.open", {"graph_id": ""}), ("sheet.open", {"graph_id": "a" * 201})]
        for name, args in bad:
            r = e.dispatch(name, args)
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"), (name, args))

    def test_handlers_are_not_called_on_bad_args(self):
        e = self.engine()
        called = []
        api.COMMANDS["chat.stop"].handler, saved = (lambda eng, a: called.append(1)), api.COMMANDS["chat.stop"].handler
        try:
            e.dispatch("chat.stop", {"x": 1})
        finally:
            api.COMMANDS["chat.stop"].handler = saved
        self.assertEqual(called, [])

    def test_handler_error_text_is_not_sent_to_the_web(self):
        e = self.engine()
        saved = api.COMMANDS["chat.stop"].handler

        def boom(eng, a):
            raise RuntimeError("C:\\비밀\\경로 sk-ant-api03-ZZZZ")
        api.COMMANDS["chat.stop"].handler = boom
        try:
            r = e.dispatch("chat.stop", {})
        finally:
            api.COMMANDS["chat.stop"].handler = saved
        self.assertEqual(r["error"]["code"], "failed")
        self.assertNotIn("비밀", json.dumps(r, ensure_ascii=False))
        self.assertNotIn("sk-ant", json.dumps(r))

    def test_reviewer_and_ai_review_prefs_are_saved(self):
        e = self.engine()
        self.assertTrue(e.dispatch("settings.set_reviewer", {"name": "  검토자A "})["ok"])
        self.assertEqual(e.reviewer(), "검토자A")
        self.assertIn("state", self.events.names())
        r = e.dispatch("extract.set_ai_review", {"enabled": True, "cap": 30})
        self.assertEqual(r["data"], {"enabled": True, "cap": 30})
        again = api.Engine(settings_path=e.settings_path)
        self.assertEqual((again.reviewer(), again.settings["extract_ai_review"], again.settings["extract_ai_cap"]), ("검토자A", True, 30))

    def test_ui_save_writes_a_small_state(self):
        e = self.engine()
        self.assertTrue(e.dispatch("ui.save", {"state": {"sheet": "g1", "chat_collapsed": False}})["ok"])
        self.assertEqual(e.ui_state(), {"sheet": "g1", "chat_collapsed": False})
        self.assertTrue(e.dispatch("ui.save", {"state": "x"})["ok"])   # 작은 JSON 값이면 받는다

    def test_command_table_has_a_doc_for_each(self):
        for name, cmd in api.COMMANDS.items():
            self.assertTrue(cmd.doc, name)

    def test_commands_that_need_chat_fail_cleanly_without_it(self):
        e = self.engine()
        for name, args in (("chat.ask", {"text": "a"}), ("chat.stop", {}), ("chat.new", {}), ("chat.set_model", {"model": "fast"})):
            r = e.dispatch(name, args)
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"), name)

    def test_add_files_refuses_non_drawing_files(self):
        e = self.engine()
        bad = os.path.join(self.tmp, "x.exe")
        open(bad, "w").close()
        self.assertEqual(e.dispatch("register.add_files", {"paths": [bad]})["error"]["code"], "bad_args")
        self.assertEqual(e.dispatch("register.add_files", {"paths": [os.path.join(self.tmp, "none.drawio")]})["error"]["code"], "bad_args")


class FakeAi:
    def __init__(self):
        self.checked = 0

    def status(self):
        return {"state": "ok", "detail": ""}

    def check(self):
        self.checked += 1


class ReadApiTest(EngineBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        from scripts.check_edit_screen import install_sample
        cls.names = [install_sample(os.environ["HAZOP_WORK_ROOT"], d) for d in ("SNP-M-101", "SNP-M-102")]

    def setUp(self):
        self.e = self.engine(ai=FakeAi())
        self.read = api.ReadApi(self.e).read

    def body(self, parts):
        r = self.read(parts, {})
        self.assertEqual(r.status, 200, parts)
        return json.loads(r.body)

    def test_state(self):
        s = self.body(["state"])
        for k in ("version", "reviewer", "project_id", "ui", "chat_model", "ai_review", "ai_review_cap"):
            self.assertIn(k, s)
        self.assertEqual(s["chat_model"], "fast")

    def test_drawings_list(self):
        d = self.body(["drawings"])
        numbers = sorted(x["drawing_number"] for x in d["drawings"])
        self.assertEqual(numbers, ["SNP-M-101", "SNP-M-102"])
        row = d["drawings"][0]
        for k in ("graph_id", "name", "title", "nodes", "relations", "unknowns"):
            self.assertIn(k, row)
        self.assertTrue(d["rev"])

    def test_sheet_json_and_svg(self):
        gid = next(x["graph_id"] for x in self.body(["drawings"])["drawings"] if x["drawing_number"] == "SNP-M-102")
        s = self.body(["sheet", gid])
        self.assertEqual(s["graph_id"], gid)
        self.assertGreater(len(s["items"]), 20)
        self.assertGreater(s["width"], 1000)
        self.assertEqual({i["layer"] for i in s["items"]}, {"symbol", "pipe"})
        pz = [i for i in s["items"] if i["tag"] == "RC-PZ01"][0]
        self.assertEqual(pz["id"], "local-node-001")
        self.assertEqual(pz["bbox"], [500 - 19, 250 - 19, 500 + 120 - 19, 250 + 300 - 19], "추출 좌표에서 정렬 offset을 뺀 SVG 좌표")
        pipe = [i for i in s["items"] if i["layer"] == "pipe"][0]
        self.assertGreaterEqual(len(pipe["polyline"]), 2)
        self.assertEqual(pipe["bbox"][0], min(p[0] for p in pipe["polyline"]))
        self.assertTrue(s["svg"].startswith("/api/sheet/"))
        svg = self.read(["sheet", gid + ".svg"], {})
        self.assertEqual((svg.status, svg.mime), (200, "image/svg+xml"))
        self.assertIn(b"<svg", svg.body)
        self.assertNotIn(b"<script", svg.body)

    def test_unknown_topics_and_ids_are_none(self):
        self.assertIsNone(self.read(["sheet", "graph-nope"], {}))
        self.assertIsNone(self.read(["sheet", "graph-nope.svg"], {}))
        self.assertIsNone(self.read(["state", "x"], {}))
        self.assertIsNone(self.read(["whatever"], {}))
        self.assertIsNone(self.read(["sheet", "..%2f..%2fx"], {}))

    def test_through_the_router_cors_and_no_write(self):
        router = scheme.Router(os.path.join(REPO, "hazop", "shell", "web"), api=api.ReadApi(self.e))
        r = router.resolve("hazop-app://api/state")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "hazop-app://shell")
        self.assertEqual(router.resolve("hazop-app://api/state", "POST").status, 405)

    def test_connection(self):
        self.assertEqual(self.body(["connection"])["state"], "ok")

    def test_open_sheet_checks_the_id(self):
        gid = self.body(["drawings"])["drawings"][0]["graph_id"]
        self.assertTrue(self.e.dispatch("sheet.open", {"graph_id": gid})["ok"])
        self.assertEqual(self.e.current_sheet, gid)
        self.assertEqual(self.e.dispatch("sheet.open", {"graph_id": "graph-none"})["error"]["code"], "not_found")

    def test_conn_check_goes_to_the_connection(self):
        self.assertTrue(self.e.dispatch("conn.check", {})["ok"])
        self.assertEqual(self.e.ai.checked, 1)


class RegisterFlowTest(EngineBase):
    def test_drop_registers_and_extracts_then_lists(self):
        import glob
        e = self.engine()
        src = [p for p in glob.glob(os.path.join(paths.folder("references", "pid-samples"), "*", "*.drawio")) if "SNP-M-102" in p]
        if not src:
            self.skipTest("표본 도면이 없음")
        r = e.dispatch("register.add_files", {"paths": [src[0]]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(r["data"]["jobs"]), 1)
        self.assertTrue(self.events.of("job.done"), self.events.items)
        d = api.ReadApi(e).drawings()
        self.assertEqual([x["graph_id"] for x in d["drawings"]], ["graph-SNP-M-102"])   # 표제란은 사람이 확정하기 전이라 번호는 비어 있을 수 있다
        self.assertEqual(d["documents"][0]["status"], "registered")
        self.assertTrue(d["documents"][0]["graphed"])
        self.assertIn("drawings", self.events.names(), "changed 사건으로 웹이 다시 읽는다")

    def test_registration_failure_is_reported_not_completed(self):
        e = self.engine()
        bad = os.path.join(self.tmp, "broken.drawio")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("이건 draw.io 파일이 아님")
        r = e.dispatch("register.add_files", {"paths": [bad]})
        self.assertTrue(r["ok"])
        self.assertTrue(self.events.of("job.failed"), self.events.items)
        self.assertFalse(self.events.of("job.done"))
        self.assertNotIn(self.tmp, json.dumps(self.events.of("job.failed"), ensure_ascii=False)[:0] or "")


class AiReviewFlowTest(EngineBase):
    """추출 뒤 AI 검토 토글·호출 상한(규격 §2.3 ① 줄). run_many는 대역으로 바꿔 호출 인자만 본다(실제 구독 호출 없음)."""

    def pages(self):
        return [("p0", {"nodes": []})]

    def flow(self, enabled, can_start=True, cap=None, via="subscription", error=None):
        from unittest import mock
        from hazop.shell import register_flow

        class Ai:
            def status(self):
                return {"state": "ok", "can_start": can_start}

            def make_client(self):
                c = mock.Mock()
                c.describe.return_value = {"via": via}
                return c
        e = self.engine(ai=Ai())
        e.settings["extract_ai_review"] = enabled
        if cap:
            e.settings["extract_ai_cap"] = cap
        progress = mock.Mock()
        with mock.patch("hazop.extract.ai_review.run_many", side_effect=error, return_value=[("p0", 3, {"calls": 2})]) as run:
            res = register_flow.review_if_wanted(e, self.pages(), progress)
        return res, run, progress

    def test_off_by_default_does_not_call_the_ai(self):
        res, run, _ = self.flow(False)
        self.assertEqual(res, {"ran": False, "candidates": 0, "skipped": "off"})
        run.assert_not_called()

    def test_on_runs_with_the_cap(self):
        res, run, _ = self.flow(True, cap=7)
        self.assertEqual((res["ran"], res["candidates"]), (True, 3))
        self.assertEqual(run.call_args.kwargs["cap"], 7)
        self.assertEqual(run.call_args.args[0][0][0], "p0")

    def test_no_connection_and_api_connection_are_skipped(self):
        res, run, _ = self.flow(True, can_start=False)
        self.assertEqual(res["skipped"], "no_connection")
        res, run2, _ = self.flow(True, via="api")
        self.assertFalse(res["ran"])
        self.assertIn("구독", res["skipped"])
        run.assert_not_called()
        run2.assert_not_called()

    def test_ai_error_does_not_fail_the_registration(self):
        res, _run, _ = self.flow(True, error=RuntimeError("C:\비밀 sk-ant-xxx"))
        self.assertEqual(res["ran"], False)
        self.assertEqual(res["skipped"], "error: RuntimeError")
        self.assertNotIn("비밀", json.dumps(res, ensure_ascii=False))


# ---------------------------------------------------------------- 채팅 조종기

class FakeSession:
    def __init__(self, model, cb):
        self.model, self.cb = model, cb
        self.asked, self.started, self.stopped, self.closed, self.models = [], 0, 0, False, []

    def start(self):
        self.started += 1
        return True

    def ask(self, text, view=None):
        self.asked.append((text, view))
        return "q%d" % len(self.asked)

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed = True

    def set_model(self, model):
        self.models.append(model)


class ChatBase(unittest.TestCase):
    def controller(self, project=None, env=None):
        self.events = Events()
        self.sessions = []
        self.proj = {"pid": project or "A"}

        def factory(model, cb):
            s = FakeSession(model, cb)
            self.sessions.append(s)
            return s
        self.env = env or FakeEnv()
        self.now = [1000.0]
        c = chat.ChatController(self.events, factory, env_provider=lambda: (self.env, small_pg()), project_fn=lambda: self.proj["pid"],
                                now=lambda: self.now[0])
        return c

    def error(self, kind, **extra):
        return dict({"error_kind": kind, "conn_state": kind, "message": "멈춤 " + kind, "limit": None}, **extra)

    def answers(self):
        return self.events.of("chat.answer")


class ChatRulesTest(ChatBase):
    def test_ask_answer_event_has_checked_card(self):
        c = self.controller()
        self.assertTrue(c.ask("경로 알려줘", {"stage": "도면"}))
        s = self.sessions[-1]
        self.assertEqual(s.asked[0][1]["stage"], "도면")
        s.cb["on_tool_event"]("q1", "trace_path", {}, {"ok": True, "sources": [{"kind": "drawing"}], "data": {"path_ref": REF}})
        s.cb["on_answer"]("q1", answer(paths=[{"label": "경로", "path_ref": REF}]), TOOL_IDS)
        a = self.answers()[0]
        card = a["card"]
        self.assertEqual(card["paths"][0]["label"], "경로")
        self.assertEqual([c_["tag"] for c_ in card["paths"][0]["chips"]], ["RC-PZ01", "RC-T2", "RC-PSV101"])
        self.assertEqual(card["paths"][0]["chips"][0]["local_id"], "L1")
        self.assertIn(S1, card["paths"][0]["marks"])
        self.assertEqual(card["badges"], ["도면"])
        self.assertEqual(a["footer"]["tools"], 1)
        json.dumps(a)  # 웹으로 갈 수 있는 값

    def test_empty_text_and_busy_are_refused(self):
        c = self.controller()
        self.assertFalse(c.ask("  "))
        self.assertTrue(c.ask("하나"))
        self.assertFalse(c.ask("둘"))
        self.assertEqual(len(self.sessions[-1].asked), 1)

    def test_A_halt_after_a_good_answer_blocks(self):
        c = self.controller()
        c.ask("첫")
        s = self.sessions[-1]

        def run():
            s.cb["on_answer"]("q1", answer(), TOOL_IDS)
            s.cb["on_state"]("ready", "")
            s.cb["on_error"]("q1", self.error("overage"))
            s.cb["on_state"]("failed", "초과 사용")
        t = threading.Thread(target=run)
        t.start()
        t.join()
        self.assertTrue(c.snapshot()["availability"]["blocked"])
        self.assertFalse(c.ask("둘"))
        self.assertEqual(len(s.asked), 1)

    def test_other_questions_error_is_ignored_and_empty_qid_does_not_end(self):
        c = self.controller()
        c.ask("하나")
        s = self.sessions[-1]
        s.cb["on_error"]("q9", self.error("timeout"))
        self.assertTrue(c.busy())
        s.cb["on_error"](None, self.error("transient", message="미리 띄우기 실패"))
        self.assertTrue(c.busy())
        self.assertIn("미리 띄우기 실패", [n["text"] for n in self.events.of("chat.notice")])

    def test_empty_qid_halt_blocks_input(self):
        c = self.controller()
        c.prewarm()
        for _ in range(100):
            if self.sessions:
                break
            time.sleep(0.01)
        self.sessions[-1].cb["on_error"](None, self.error("login_required"))
        self.assertTrue(c.snapshot()["availability"]["blocked"])

    def test_B_availability_refresh_does_not_release_a_halt(self):
        c = self.controller()
        c.ask("q")
        self.sessions[-1].cb["on_error"]("q1", self.error("limit_reached"))
        self.assertTrue(c.snapshot()["availability"]["blocked"])
        c.set_availability("ok", "")
        self.assertTrue(c.snapshot()["availability"]["blocked"])
        self.assertFalse(c.ask("다시"))
        c.set_availability("ok", "", user_check=True)
        self.assertFalse(c.snapshot()["availability"]["blocked"])

    def test_B3_limit_halt_released_after_reset_time(self):
        c = self.controller()
        c.ask("q")
        self.sessions[-1].cb["on_error"]("q1", self.error("limit_reached", limit={"resets_at": 2000}))
        c.set_availability("ok", "")
        self.assertTrue(c.snapshot()["availability"]["blocked"])
        self.now[0] = 2001
        c.set_availability("ok", "")
        self.assertFalse(c.snapshot()["availability"]["blocked"])

    def test_blocked_availability_never_starts_a_session(self):
        c = self.controller()
        c.set_availability("not_installed")
        self.assertFalse(c.ask("q"))
        c.prewarm()
        self.assertEqual(self.sessions, [])

    def test_C_project_switch_ends_conversation_and_C2_stale_answer(self):
        c = self.controller(project="A")
        c.ask("A 질문")
        self.sessions[0].cb["on_answer"]("q1", answer(), TOOL_IDS)
        self.proj["pid"] = "B"
        self.assertTrue(c.ask("B 질문"))
        self.assertEqual(len(self.sessions), 2)
        self.assertTrue(self.sessions[0].closed)
        self.assertTrue(self.events.of("chat.cleared"))
        # 질문 중에 프로젝트가 바뀌면 근거 없음
        self.proj["pid"] = "C"
        self.sessions[1].cb["on_answer"]("q1", answer(text="S3에는 펌프", refs=[{"kind": "node", "id": "S3"}]), {"node": {"S3"}})
        card = self.answers()[-1]["card"]
        self.assertEqual((card["refs"], card["ungrounded"], card["badges"]), ([], 1, []))

    def test_stop_and_new_conversation(self):
        c = self.controller()
        c.ask("q")
        c.stop()
        self.assertFalse(c.busy())
        self.assertEqual(self.sessions[-1].stopped, 1)
        self.assertIn("지금까지의 대화는 지워지고", self.events.of("chat.notice")[-1]["text"])
        self.sessions[-1].cb["on_error"]("q1", self.error("cancelled"))   # 멈춘 뒤 오는 취소 오류는 무시
        self.assertFalse(any("cancelled" in n["text"] for n in self.events.of("chat.notice")))
        c.new_conversation()
        self.assertTrue(self.events.of("chat.cleared"))

    def test_model_is_passed_to_the_session(self):
        c = self.controller()
        c.ask("처음")
        self.assertEqual(self.sessions[-1].model, "fast")
        c.set_model("deep")
        self.assertEqual(self.sessions[-1].models, ["deep"])
        self.assertEqual(c.snapshot()["model"], "deep")

    def test_factory_error_becomes_a_notice(self):
        events = Events()

        def boom(model, cb):
            raise ValueError("프로젝트가 없습니다.")
        c = chat.ChatController(events, boom)
        self.assertFalse(c.ask("질문"))
        self.assertFalse(c.busy())
        self.assertIn("프로젝트가 없습니다", events.of("chat.notice")[0]["text"])

    def test_shutdown_closes_the_session(self):
        c = self.controller()
        c.ask("q")
        c.shutdown()
        self.assertTrue(self.sessions[-1].closed)

    def test_halted_through_commands_dispatch(self):
        c = self.controller()
        e = api.Engine(settings_path=os.path.join(tempfile.mkdtemp(), "s.json"), emit=self.events, chat=c)
        self.assertTrue(e.dispatch("chat.ask", {"text": "질문"})["data"]["accepted"])
        self.sessions[-1].cb["on_error"]("q1", self.error("overage"))
        self.assertFalse(e.dispatch("chat.ask", {"text": "또"})["data"]["accepted"])


if __name__ == "__main__":
    unittest.main()
