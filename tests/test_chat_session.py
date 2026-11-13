"""채팅 세션 시험(규격 docs/specs/chat-panel.md §2.4·§2.5·§9.1). 실제 구독 호출 없음.

가짜 CLI(tests/fake_claude/fake_claude.py, 'chat' 시나리오)가 stream-json 입력을 받고, 앱이 쓴 MCP 설정대로 가짜 도구 서버
(tests/fake_claude/fake_tools.py → hazop.chat.mcp_server)를 실제로 띄워 tool_use·tool_result·init 이벤트를 낸다.
보안 경계는 '주입이 성공해도 할 수 없는 일'로 고정한다: 도구 검문 실패(더 있음·덜 있음·이름 다름·서버 둘·실패한 서버·
권한 모드·API 키), 허용 목록 밖 도구 호출, 경로 인자, 상한 넘는 호출.
실행: python -m unittest tests.test_chat_session
"""

import ctypes
import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from hazop.chat import mcp_server, session
from hazop.study import claude_cli, providers

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(REPO_ROOT, "tests", "fake_claude", "fake_claude.py")
FAKE_TOOLS = os.path.join(REPO_ROOT, "tests", "fake_claude", "fake_tools.py")
sys.path.insert(0, os.path.dirname(FAKE_TOOLS))
import fake_tools  # noqa: E402

ALLOWED = mcp_server.tool_names(fake_tools.REGISTRY)
PATH_Q = [{"name": "trace_path", "args": {"start": "RC-PZ01", "end": "RC-PSV101"}},
          {"name": "get_component", "args": {"id": "g1/e-pv101"}}]


def alive(pid):
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value == 259


def gone(pid, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def wait_file(path, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if os.path.exists(path) and os.path.getsize(path):
            return True
        time.sleep(0.05)
    return False


class Clock:
    def __init__(self):
        self.extra = 0.0

    def __call__(self):
        return time.monotonic() + self.extra


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-chat-session-")
        self.log = os.path.join(self.tmp, "log")
        self.run_root = os.path.join(self.tmp, "run")
        self.limits = os.path.join(self.tmp, "ai_limits.json")
        self.events = queue.Queue()
        self.sessions = []
        self.slots = claude_cli.SubscriptionSlots()

    def tearDown(self):
        for s in self.sessions:
            s.close()
        self.assertEqual(self.slots.chat, 0, "채팅 자리를 돌려주지 않음")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, turns, script_extra=None, **kw):
        script = self.script = os.path.join(self.tmp, "script-%d.json" % len(self.sessions))
        with open(script, "w", encoding="utf-8") as fh:
            json.dump(dict({"turns": turns}, **(script_extra or {})), fh, ensure_ascii=False)
        kw.setdefault("slots", self.slots)
        kw.setdefault("idle_poll", 0.1)
        ev = self.events
        kw.setdefault("registry", fake_tools.REGISTRY)
        s = session.ChatSession(
            "p", argv_prefix=[sys.executable, FAKE, "chat@" + script, self.log],
            server_cmd=lambda pid, qf: [sys.executable, "-E", "-s", FAKE_TOOLS, "--project", pid, "--question-file", qf],
            run_root=self.run_root, limits_path=self.limits,
            on_tool_event=lambda *a: ev.put(("tool",) + a), on_answer=lambda *a: ev.put(("answer",) + a),
            on_error=lambda *a: ev.put(("error",) + a), on_state=lambda *a: ev.put(("state",) + a), **kw)
        self.sessions.append(s)
        return s

    def until(self, kind, seconds=30):
        """kind 이벤트까지 모은 목록. answer·error는 질문의 끝."""
        got, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                e = self.events.get(timeout=0.1)
            except queue.Empty:
                continue
            got.append(e)
            if e[0] == kind:
                return got
        self.fail("%s 이벤트가 오지 않음: %s" % (kind, got))

    def finish(self, seconds=30):
        got = self.until_any(("answer", "error"), seconds)
        return got, got[-1]

    def until_any(self, kinds, seconds=30):
        got, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                e = self.events.get(timeout=0.1)
            except queue.Empty:
                continue
            got.append(e)
            if e[0] in kinds:
                return got
        self.fail("%s 이벤트가 오지 않음: %s" % (kinds, got))

    def call_args(self):
        with open(os.path.join(self.log, "call.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def messages(self):
        with open(os.path.join(self.log, "messages.jsonl"), encoding="utf-8") as fh:
            return [json.loads(x) for x in fh]


class FlowTest(SessionCase):
    def test_answer_with_tools(self):
        s = self.make([{"calls": PATH_Q, "answer": {"text": "밸브는 RC-PV101", "general": ""}}])
        view = {"stage": "③", "sheet": "SNP-M-102", "selected": ["g1/n%02d" % i for i in range(25)]}
        qid = s.ask("RC-PZ01에서 RC-PSV101까지 밸브는?", view)
        got, last = self.finish()
        self.assertEqual(last[0], "answer", got)
        self.assertEqual(last[1], qid)
        self.assertEqual(last[2], {"text": "밸브는 RC-PV101", "general": ""})
        tool_ids = last[3]
        self.assertEqual(tool_ids["component"], {"g1/e-pz01", "g1/e-pv101", "g1/e-psv101"})
        self.assertEqual(len(tool_ids["path_ref"]), 1)
        tools = [e for e in got if e[0] == "tool"]
        self.assertEqual([(e[1], e[2]) for e in tools], [(qid, "trace_path"), (qid, "get_component")])
        self.assertEqual(tools[0][3], {"start": "RC-PZ01", "end": "RC-PSV101"})
        self.assertTrue(tools[0][4]["ok"])
        msg = self.messages()[0]["message"]["content"]
        self.assertTrue(msg.startswith("사용자 질문:\nRC-PZ01에서 RC-PSV101까지 밸브는?\n\n지금 화면: ③ · 도면 SNP-M-102"))
        self.assertIn("g1/n19 외 5개", msg)
        self.assertNotIn("g1/n20", msg)

    def test_command_and_mcp_config(self):
        s = self.make([{}])
        s.ask("안녕")
        self.finish()
        args = self.call_args()["args"]
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--allowedTools") + 1].split(","), ALLOWED)
        self.assertNotIn("*", args[args.index("--allowedTools") + 1])
        self.assertNotIn("--disallowedTools", args)
        for flag, value in (("--input-format", "stream-json"), ("--output-format", "stream-json"),
                            ("--permission-mode", "dontAsk"), ("--permission-prompts", "none"),
                            ("--setting-sources", ""), ("--model", "claude-haiku-5-5"), ("--effort", "low"),
                            ("--max-turns", "200")):
            self.assertEqual(args[args.index(flag) + 1], value, flag)
        for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--verbose"):
            self.assertIn(flag, args)
        with open(args[args.index("--mcp-config") + 1], encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertEqual(list(cfg["mcpServers"]), ["hazop"])
        self.assertEqual(cfg["mcpServers"]["hazop"]["args"][-4:-2], ["--project", "p"])
        call = self.call_args()
        self.assertEqual(call["cwd_files"], [])
        self.assertNotIn("ANTHROPIC_API_KEY", call["env"])

    def test_two_questions_one_process(self):
        s = self.make([{"calls": PATH_Q}, {"calls": [{"name": "count", "args": {"limit": 2}}]}])
        q1 = s.ask("첫 질문")
        self.assertEqual(self.finish()[1][0], "answer")
        pid = s._tree.proc.pid
        q2 = s.ask("둘째 질문")
        got, last = self.finish()
        self.assertEqual(last[0], "answer")
        self.assertNotEqual(q1, q2)
        self.assertEqual(s._tree.proc.pid, pid)
        self.assertEqual(set(last[3]), set())  # count는 ID를 돌려주지 않는다: 앞 질문의 ID가 섞이지 않음
        self.assertEqual(len(self.messages()), 2)

    def test_prestart_then_ask(self):
        s = self.make([{}])
        self.assertTrue(s.start())
        pid = s._tree.proc.pid
        s.ask("질문")
        self.assertEqual(self.finish()[1][0], "answer")
        self.assertEqual(s._tree.proc.pid, pid)

    def test_model_change_new_process(self):
        s = self.make([{}])
        s.ask("하나")
        self.finish()
        pid = s._tree.proc.pid
        s.set_model("normal")
        s.ask("둘")
        got, last = self.finish()
        self.assertEqual(last[0], "answer")
        self.assertNotEqual(s._tree.proc.pid, pid)
        self.assertTrue(gone(pid))
        args = self.call_args()["args"]
        self.assertEqual(args[args.index("--model") + 1], "claude-sonnet-5-5")
        self.assertIn(("state", "renewed", session.RENEWED_MESSAGE), got)

    def test_idle_renew(self):
        clock = Clock()
        s = self.make([{}], clock=clock)
        s.ask("하나")
        self.finish()
        pid = s._tree.proc.pid
        clock.extra = session.IDLE_RENEW + 1
        s.ask("둘")
        got, last = self.finish()
        self.assertEqual(last[0], "answer")
        self.assertNotEqual(s._tree.proc.pid, pid)

    def test_token_renew(self):
        big = {"input_tokens": 10, "cache_read_input_tokens": session.TOKEN_RENEW, "output_tokens": 1}
        s = self.make([{"result": {"usage": big}}, {}])
        s.ask("하나")
        self.finish()
        pid = s._tree.proc.pid
        s.ask("둘")
        self.assertEqual(self.finish()[1][0], "answer")
        self.assertNotEqual(s._tree.proc.pid, pid)


class GuardTest(SessionCase):
    """도구 검문: 대화 시작 이벤트가 허용과 정확히 같지 않으면 그 대화를 쓰지 않고 끊는다."""

    def guarded(self, turn, kind="tool_guard_failed"):
        turn = dict(turn, calls=PATH_Q, answer={"text": "주입된 답"})
        s = self.make([turn])
        qid = s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[0], "error", got)
        self.assertEqual(last[1], qid)
        self.assertEqual(last[2]["error_kind"], kind)
        self.assertFalse([e for e in got if e[0] in ("answer", "tool")], got)
        pid = self.call_args()["pid"]
        self.assertTrue(gone(pid), "검문 실패 뒤 CLI가 남음")
        self.assertIsNone(s._tree)
        self.assertTrue(providers.halts([kind]))
        return s

    def test_extra_tool(self):
        self.guarded({"init": {"tools": ["StructuredOutput"] + ALLOWED + ["Bash"]}})

    def test_extra_mcp_tool(self):
        self.guarded({"init": {"tools": ["StructuredOutput"] + ALLOWED + ["mcp__other__read_file"]}})

    def test_missing_tool(self):
        self.guarded({"init": {"tools": ["StructuredOutput"] + ALLOWED[1:]}})

    def test_missing_structured_output(self):
        self.guarded({"init": {"tools": list(ALLOWED)}})

    def test_renamed_tool(self):
        self.guarded({"init": {"tools": ["StructuredOutput"] + [n + "2" for n in ALLOWED]}})

    def test_duplicate_tool(self):
        self.guarded({"init": {"tools": ["StructuredOutput"] + ALLOWED + ALLOWED[:1]}})

    def test_two_servers(self):
        self.guarded({"init": {"mcp_servers": [{"name": "hazop", "status": "connected"},
                                               {"name": "other", "status": "connected"}]}})

    def test_failed_server(self):
        self.guarded({"init": {"mcp_servers": [{"name": "hazop", "status": "failed"}]}})

    def test_permission_mode(self):
        self.guarded({"init": {"permissionMode": "bypassPermissions"}})
        self.guarded({"init": {"permissionMode": None}})

    def test_no_init(self):
        self.guarded({"skip_init": True})

    def test_api_key_source(self):
        self.guarded({"init": {"apiKeySource": "ANTHROPIC_API_KEY"}}, kind="auth_mismatch")

    def test_second_question_guarded_too(self):
        s = self.make([{}, {"init": {"tools": ["StructuredOutput", "Bash"] + ALLOWED}, "calls": PATH_Q}])
        s.ask("하나")
        self.assertEqual(self.finish()[1][0], "answer")
        s.ask("둘")
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "tool_guard_failed")
        self.assertFalse([e for e in got if e[0] == "tool"])

    def test_tool_use_outside_allowlist(self):
        s = self.make([{"calls": [{"name": "count"}, {"raw": "Bash", "args": {"command": "type C:\\x"}},
                                  {"name": "count"}]}])
        s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "tool_guard_failed")
        self.assertIn("Bash", last[2]["message"])
        self.assertEqual([e[2] for e in got if e[0] == "tool"], ["count"])
        self.assertFalse([e for e in got if e[0] == "answer"])

    def test_guard_unit(self):
        init = {"tools": ["StructuredOutput"] + ALLOWED, "permissionMode": "dontAsk",
                "mcp_servers": [{"name": "hazop", "status": "connected", "source": "dynamic"}]}
        self.assertIsNone(session.guard(init, ALLOWED))
        self.assertIsNone(session.guard(dict(init, tools=list(reversed(init["tools"]))), ALLOWED))
        self.assertIsNotNone(session.guard(dict(init, tools=None), ALLOWED))
        self.assertIsNotNone(session.guard(dict(init, mcp_servers=[]), ALLOWED))
        self.assertIsNone(session.guard(dict(init, tools=["StructuredOutput"]), []))


class InjectionTest(SessionCase):
    """주입이 성공해 모델이 무엇을 불러도 도구 서버가 하지 않는 일(세션 → CLI → 서버 왕복)."""

    def test_path_args_rejected(self):
        calls = [{"name": "get_component", "args": {"id": "..\\..\\Windows\\win.ini"}},
                 {"name": "get_component", "args": {"id": "C:/Users/x/.ssh/id_rsa"}},
                 {"name": "get_component", "args": {"id": "g1/e-pz01", "path": "C:/x"}},
                 {"name": "count", "args": {"filter": {"tag": "%APPDATA%"}}},
                 {"name": "count", "args": {"cursor": "c-000000000000"}}]
        s = self.make([{"calls": calls}])
        s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[0], "answer")
        results = [e[4] for e in got if e[0] == "tool"]
        self.assertEqual([r["error"]["code"] for r in results], ["bad_args"] * 5)
        self.assertEqual(last[3], {})  # 거절된 결과의 ID는 근거가 되지 않는다

    def test_server_call_limit(self):
        calls = [{"name": "get_component", "args": {"id": "g1/e-pz01"}}] * 10
        s = self.make([{"calls": calls}])
        s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[0], "answer")
        codes = [(e[4].get("error") or {}).get("code") for e in got if e[0] == "tool"]
        self.assertEqual(codes, [None] * 8 + ["limit_reached"] * 2)

    def test_app_tool_use_halt(self):
        calls = [{"name": "count"}] * (session.TOOL_USE_HALT + 3)
        s = self.make([{"calls": calls, "child": True, "sleep": 30}])
        s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "tool_limit")
        self.assertFalse([e for e in got if e[0] == "answer"])
        self.assertTrue(gone(self.call_args()["pid"]))


class StopTest(SessionCase):
    def test_stop_kills_tree_and_next_question_is_new(self):
        s = self.make([{"calls": [{"name": "count"}], "child": True, "sleep": 60}, {}])
        s.ask("오래 걸리는 질문")
        self.until("tool")
        self.assertTrue(wait_file(os.path.join(self.log, "child.pid")))
        with open(os.path.join(self.log, "child.pid")) as fh:
            child = int(fh.read())
        cli = self.call_args()["pid"]
        s.stop()
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "cancelled")
        self.assertTrue(gone(cli))
        self.assertTrue(gone(child), "자손 프로세스가 남음")
        self.assertTrue(providers.halts(["cancelled"]))
        with open(self.script, "w", encoding="utf-8") as fh:  # 새 프로세스는 대본을 처음부터 읽는다
            json.dump({"turns": [{}]}, fh)
        s.ask("다시")
        got, last = self.finish()
        self.assertEqual(last[0], "answer")
        self.assertNotEqual(self.call_args()["pid"], cli)

    def test_close_leaves_nothing(self):
        s = self.make([{"calls": [{"name": "count"}], "child": True, "sleep": 60}])
        s.ask("질문")
        self.until("tool")
        self.assertTrue(wait_file(os.path.join(self.log, "child.pid")))
        with open(os.path.join(self.log, "child.pid")) as fh:
            child = int(fh.read())
        cli = self.call_args()["pid"]
        run_dir = s._run_dir
        s.close()
        self.assertTrue(gone(cli))
        self.assertTrue(gone(child))
        self.assertFalse(os.path.exists(run_dir))
        self.assertEqual(s.state, "closed")
        s.close()  # 두 번 닫아도 된다
        s.ask("닫힌 뒤")
        self.assertEqual(self.finish()[1][2]["error_kind"], "cancelled")

    def test_atexit_closes_live_sessions(self):
        s = self.make([{"calls": [{"name": "count"}], "sleep": 60}])
        s.ask("질문")
        self.until("tool")
        cli = self.call_args()["pid"]
        session._close_all()
        self.assertTrue(gone(cli))

    def test_timeout(self):
        fast = dict(session.MODELS, fast=("claude-haiku-5-5", "low", 1))
        with mock.patch.dict(session.MODELS, fast):
            s = self.make([{"sleep": 30}])
            s.ask("질문")
            got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "timeout")
        self.assertTrue(gone(self.call_args()["pid"]))


class ErrorTest(SessionCase):
    def test_limit_rejected_halts(self):
        limit = {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 4102444800,
                                                                 "rateLimitType": "five_hour"}}
        s = self.make([{"pre": [limit], "result": {"is_error": True, "subtype": "error_during_execution",
                                                   "structured_output": None, "result": "limit"}}])
        s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "limit_reached")
        self.assertTrue(os.path.exists(self.limits))
        s.ask("또")
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "limit_reached")
        self.assertTrue(providers.halts(["limit_reached"]))

    def test_overage_answer_then_halt(self):
        over = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "isUsingOverage": True,
                                                                "overageStatus": "allowed"}}
        s = self.make([{"pre": [over]}])
        s.ask("질문")
        got = self.until("error")
        kinds = [e[0] for e in got if e[0] in ("answer", "error")]
        self.assertEqual(kinds, ["answer", "error"])
        self.assertEqual(got[-1][2]["error_kind"], "overage")
        self.assertIsNone(s._tree)

    def test_crash(self):
        s = self.make([{"exit": 3}])
        s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[0], "error")
        self.assertEqual(last[2]["error_kind"], "other")

    def test_refusal(self):
        s = self.make([{"result": {"is_error": True, "stop_reason": "refusal", "structured_output": None}}])
        s.ask("질문")
        self.assertEqual(self.finish()[1][2]["error_kind"], "refused")

    def test_not_installed(self):
        with mock.patch.object(claude_cli, "find_cli", return_value=(None, "not_installed")):
            s = session.ChatSession("p", registry=fake_tools.REGISTRY, run_root=self.run_root,
                                    limits_path=self.limits, on_error=lambda *a: self.events.put(("error",) + a))
            self.sessions.append(s)
            self.assertFalse(s.start())
        got, last = self.finish()
        self.assertEqual(last[2]["conn_state"], "not_installed")

    def test_busy(self):
        s = self.make([{"sleep": 5}])
        s.ask("하나")
        s.ask("둘")
        got = self.until("error", 10)
        self.assertEqual(got[-1][2]["error_kind"], "other")


class ReviewFixTest(SessionCase):
    """검토 지적(2026-11-13) 1·2·4·5·6·9·10·11번."""

    OVER = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "isUsingOverage": True,
                                                            "overageStatus": "allowed"}}

    def test_halt_blocks_next_question_until_resume(self):
        s = self.make([{"pre": [self.OVER]}, {}])
        s.ask("질문")
        got = self.until("error")
        self.assertEqual(got[-1][2]["error_kind"], "overage")
        self.assertTrue(gone(self.call_args()["pid"]))
        self.assertIsNone(s._tree)
        self.assertEqual(s.halted["error_kind"], "overage")
        self.assertEqual(s.state, "failed")
        s.ask("또")
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "overage")
        self.assertIsNone(s._tree, "멈춘 뒤 새 프로세스를 띄움")
        self.assertEqual(len(self.messages()), 1)
        self.assertFalse(s.start())
        self.finish()
        s.resume(allow_overage=True)
        self.assertIsNone(s.halted)
        s.ask("풀린 뒤")
        got, last = self.finish()
        self.assertEqual(last[0], "answer")

    def test_auth_and_guard_failures_halt(self):
        for turn, kind in (({"init": {"apiKeySource": "ANTHROPIC_API_KEY"}}, "auth_mismatch"),
                           ({"init": {"tools": ["StructuredOutput", "Bash"] + ALLOWED}}, "tool_guard_failed"),
                           ({"result": {"is_error": True, "result": "Not logged in", "structured_output": None}},
                            "not_ready")):
            s = self.make([turn])
            s.ask("하나")
            self.assertEqual(self.finish()[1][2]["error_kind"], kind)
            self.assertTrue(gone(self.call_args()["pid"]), kind)
            s.ask("둘")
            self.assertEqual(self.finish()[1][2]["error_kind"], kind)
            self.assertIsNone(s._tree)

    def test_blocked_write_times_out_and_stop_does_not_hang(self):
        fast = dict(session.MODELS, fast=("claude-haiku-5-5", "low", 1))
        with mock.patch.dict(session.MODELS, fast):
            s = self.make([{}], script_extra={"no_read": 60})
            t0 = time.monotonic()
            s.ask("가" * (4 * 1024 * 1024))
            self.assertLess(time.monotonic() - t0, 1.0, "ask가 쓰기에 막힘")
            got, last = self.finish(20)
        self.assertEqual(last[2]["error_kind"], "timeout")
        self.assertTrue(gone(self.call_args()["pid"]))
        s2 = self.make([{}], script_extra={"no_read": 60})
        s2.ask("나" * (4 * 1024 * 1024))
        time.sleep(0.5)
        t0 = time.monotonic()
        s2.stop()
        self.assertLess(time.monotonic() - t0, 12)
        self.assertEqual(self.until("error")[-1][2]["error_kind"], "cancelled")

    def test_callback_exception_does_not_kill_reader(self):
        def bad_tool(*a):
            raise RuntimeError("화면 결함")
        s = self.make([{"calls": PATH_Q}, {}])
        s.on_tool_event = bad_tool
        with self.assertLogs("hazop.chat.session", "ERROR"):
            s.ask("하나")
            self.assertEqual(self.finish()[1][0], "answer")
        s.ask("둘")
        self.assertEqual(self.finish()[1][0], "answer")

    def test_handler_exception_ends_question(self):
        s = self.make([{"calls": PATH_Q}])
        with mock.patch.object(session.ChatSession, "_on_user", side_effect=KeyError("x")), \
                self.assertLogs("hazop.chat.session", "ERROR"):
            t0 = time.monotonic()
            s.ask("질문")
            got, last = self.finish(10)
        self.assertEqual(last[2]["error_kind"], "other")
        self.assertLess(time.monotonic() - t0, 8)
        self.assertFalse(s.busy)

    def test_question_file_error_not_stuck(self):
        s = self.make([{}])
        with mock.patch.object(session.ChatSession, "_write_question", side_effect=OSError("disk")):
            s.ask("하나")
            self.assertEqual(self.finish()[1][2]["error_kind"], "other")
        self.assertFalse(s.busy)
        s.ask("둘")
        self.assertEqual(self.finish()[1][0], "answer")

    def test_idle_timer_reaps_prestarted_process(self):
        clock = Clock()
        s = self.make([{}], clock=clock)
        self.assertTrue(s.start())
        pid = s._tree.proc.pid
        clock.extra = session.IDLE_RENEW + 1
        got = self.until("state", 5)
        self.assertEqual(got[-1][1:], ("idle", session.RENEWED_MESSAGE))
        self.assertTrue(gone(pid))
        self.assertIsNone(s._tree)

    def test_cli_exits_by_itself(self):
        s = self.make([{"quit": True}])
        s.ask("질문")
        self.assertEqual(self.finish()[1][0], "answer")
        end = time.monotonic() + 10
        while True:
            e = self.until("state", 10)[-1]
            if e[1] == "idle" or time.monotonic() > end:
                break
        self.assertEqual(e[1], "idle")
        self.assertIsNone(s._tree)

    def test_guard_plugins_skills_hooks(self):
        for init in ({"plugins": [{"name": "evil", "path": "C:/x", "source": "evil@market"}]},
                     {"skills": ["deploy"]}, {"slash_commands": ["x"]}, {"additional_directories": ["C:/"]},
                     {"hooks": {"PreToolUse": ["x"]}}):
            s = self.make([{"init": init, "calls": PATH_Q}])
            s.ask("질문")
            got, last = self.finish()
            self.assertEqual(last[2]["error_kind"], "tool_guard_failed", init)
            self.assertFalse([e for e in got if e[0] == "tool"])

    def test_tool_results_before_guard_ignored(self):
        early = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_x", "content": [{"type": "text", "text": "{}"}]}]}}
        s = self.make([{"skip_init": True, "pre": [early], "calls": PATH_Q, "answer": {"text": "검문 전 답"}}])
        s.ask("질문")
        got, last = self.finish()
        self.assertEqual(last[2]["error_kind"], "tool_guard_failed")
        self.assertFalse([e for e in got if e[0] in ("tool", "answer")])

    def test_chat_waits_for_analysis_slot(self):
        self.slots.acquire_analysis(lambda: True)
        self.slots.acquire_analysis(lambda: True)
        s = self.make([{}])
        s.ask("질문")
        time.sleep(1.0)
        self.assertFalse(os.path.exists(os.path.join(self.log, "messages.jsonl")), "분석 2건 중에 채팅이 보냄")
        self.slots.release_analysis()
        self.assertEqual(self.finish()[1][0], "answer")
        self.slots.release_analysis()


class SlotsTest(unittest.TestCase):
    def test_chat_one_plus_analysis_one(self):
        slots = claude_cli.SubscriptionSlots()
        self.assertTrue(slots.acquire_analysis(lambda: True))
        self.assertTrue(slots.acquire_analysis(lambda: True))  # 채팅이 없으면 막지 않는다(U8)
        slots.release_analysis()
        self.assertTrue(slots.acquire_chat(lambda: True))
        n = {"tries": 0}

        def give_up():
            n["tries"] += 1
            return n["tries"] < 3
        self.assertFalse(slots.acquire_analysis(give_up), "채팅 중 두 번째 분석")
        self.assertFalse(slots.acquire_chat(lambda: False), "채팅 둘")
        slots.release_chat()
        self.assertTrue(slots.acquire_analysis(lambda: True))
        slots.release_analysis()
        slots.release_analysis()
        self.assertEqual((slots.chat, slots.analysis), (0, 0))

    def test_analysis_cancel_while_waiting(self):
        slots = claude_cli.SubscriptionSlots()
        slots.acquire_chat(lambda: True)
        slots.acquire_analysis(lambda: True)
        client = claude_cli.ClaudeCliClient(argv_prefix=[sys.executable, FAKE, "ok", tempfile.gettempdir()])
        out = {}
        with mock.patch.object(claude_cli, "SLOTS", slots):
            t = threading.Thread(target=lambda: out.setdefault(
                "r", client.analyze({"schema": {}, "system": "s", "user": "u"})))
            t.start()
            time.sleep(0.5)
            client.cancel()
            t.join(5)
        self.assertEqual(out["r"]["error_kind"], "cancelled")


class UnitTest(unittest.TestCase):
    def test_halt_kinds_match_providers(self):
        want = {k for k, halt in providers.ERROR_KINDS.items() if halt} - {"cancelled"}
        self.assertEqual(set(session.HALT_KINDS), want)

    def test_chat_command_rejects_wide_names(self):
        for bad in (["mcp__*"], ["mcp__hazop__*"], ["Bash"], ["mcp__other__x"], ["mcp__hazop__A"], ["mcp__hazop__a,b"]):
            with self.assertRaises(ValueError):
                claude_cli.chat_command("m", "low", {}, "s", "c", bad)
        argv = claude_cli.chat_command("m", "low", {}, "s", "c", [])
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "mcp__*")

    def test_analysis_command_unchanged(self):
        argv = claude_cli.ClaudeCliClient().command({"schema": {}}, "s")
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "mcp__*")
        self.assertEqual(argv[argv.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertNotIn("--input-format", argv)

    def test_server_command(self):
        with mock.patch("hazop.paths.frozen_bundle_dir", return_value="C:/HAZOP"):
            cmd = session.server_command("p", "q.json")
        self.assertEqual(cmd[1:], ["--chat-tools", "--project", "p", "--question-file", "q.json"])
        with mock.patch("hazop.paths.frozen_bundle_dir", return_value=None):
            cmd = session.server_command("p", "q.json")
        self.assertEqual(cmd[1:3], ["-E", "-s"])
        self.assertTrue(cmd[3].endswith(os.path.join("scripts", "run_chat_tools_server.py")))
        self.assertNotIn("-I", cmd)

    def test_collect_ids(self):
        env = {"ok": True, "data": {"path_ref": {"start": "a", "end": "b"}, "steps": [{"id": "a"}, {"id": "b"}],
                                    "node_id": "S1"}}
        got = session.collect_ids(env, ("component", "path_ref"))
        self.assertEqual(got["component"], {"a", "b"})
        self.assertEqual(len(got["path_ref"]), 1)
        self.assertNotIn("node", got)
        self.assertEqual(session.collect_ids(dict(env, ok=False), ("component",)), {})
        self.assertEqual(session.collect_ids(env, ()), {})
        both = session.collect_ids({"ok": True, "data": {"items": [{"id": "x", "node_id": "S2"}]}}, ("component", "node"))
        self.assertEqual(both, {"component": {"x"}, "node": {"S2"}})
        node = session.collect_ids({"ok": True, "data": {"items": [{"id": "S1"}]}}, ("node",))
        self.assertEqual(node, {"node": {"S1"}})

    def test_parse_tool_text(self):
        text = mcp_server.PREFIX + "\n" + json.dumps({"ok": True})
        self.assertEqual(session.parse_tool_text([{"type": "text", "text": text}]), {"ok": True})
        self.assertIsNone(session.parse_tool_text("not json"))


if __name__ == "__main__":
    unittest.main()
