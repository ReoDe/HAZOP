"""채팅 도구 MCP 서버 시험(규격 docs/specs/chat-panel.md §2.5·§3.1·§9.1). 실제 구독 호출 없음.

도구는 C1의 실제 도구 대신 tests/fake_claude/fake_tools.py의 가짜 목록을 쓴다. 보안 경계는 '주입이 성공해 모델이 무엇을
보내도 서버가 하지 않는 일'로 고정한다: 목록 밖 도구, 서명 밖 인자, 경로 인자, 서버가 내지 않은 cursor, 상한 넘는 호출.
실행: python -m unittest tests.test_chat_mcp_server
"""

import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from hazop.chat import mcp_server

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_TOOLS = os.path.join(REPO_ROOT, "tests", "fake_claude", "fake_tools.py")
sys.path.insert(0, os.path.dirname(FAKE_TOOLS))
import fake_tools  # noqa: E402


class Spy:
    """도구가 실제로 불렸는지 세는 가짜 도구."""

    def __init__(self):
        self.calls = []

    def __call__(self, ctx, id=None, filter=None, cursor=None, limit=50):
        self.calls.append({"id": id, "filter": filter, "cursor": cursor})
        return {"ok": True, "data": {"id": id}, "cursor": None, "error": None}


def spy_registry(spy):
    reg = dict(fake_tools.REGISTRY)
    reg["probe"] = {"fn": spy, "returns": ("component",),
                    "input_schema": fake_tools._schema(id="string", filter="object", cursor="string", limit="integer")}
    return reg


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-chat-mcp-")
        self.qfile = os.path.join(self.tmp, "question.json")
        self.version = "v1"
        self.spy = Spy()
        self.server = mcp_server.Server(spy_registry(self.spy), "p", self.qfile,
                                        loader=lambda pid: fake_tools.FakeCtx(pid, self.version),
                                        refresher=lambda ctx: ctx if ctx.pg["graph_version"] == self.version
                                        else fake_tools.FakeCtx(ctx.project_id, self.version))
        self.ask("q-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ask(self, qid):
        with open(self.qfile, "w", encoding="utf-8") as fh:
            json.dump({"question_id": qid}, fh)

    def call(self, name, **args):
        return self.server.call(name, args)

    def rpc(self, method, params=None, mid=1):
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        return self.server.handle(msg)


class ProtocolTest(ServerCase):
    def test_initialize_and_list(self):
        rep = self.rpc("initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(rep["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(rep["result"]["serverInfo"]["name"], "hazop")
        self.assertIn("tools", rep["result"]["capabilities"])
        odd = self.rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertIn(odd["result"]["protocolVersion"], mcp_server.PROTOCOL_VERSIONS)
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(names, sorted(spy_registry(self.spy)))
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_notification_unknown_method(self):
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.rpc("resources/list")["error"]["code"], -32601)  # 경로문자열-허용: MCP 메서드 이름이지 경로가 아님
        self.assertEqual(self.server.handle({"id": 1, "method": "ping"})["error"]["code"], -32600)

    def test_call_text_has_prefix(self):
        rep = self.rpc("tools/call", {"name": "count", "arguments": {"limit": 2}})
        text = rep["result"]["content"][0]["text"]
        self.assertTrue(text.startswith(mcp_server.PREFIX + "\n"))
        env = json.loads(text.split("\n", 1)[1])
        self.assertTrue(env["ok"])
        self.assertFalse(rep["result"]["isError"])

    def test_tool_names_for_cli(self):
        self.assertEqual(mcp_server.tool_names({"b": 1, "a": 2}), ["mcp__hazop__a", "mcp__hazop__b"])

    def test_normalize_skips_bad_entries(self):
        reg = mcp_server.normalize({"ok_tool": {"fn": len}, "Bad-Name": {"fn": len}, "no_fn": {"description": "x"},
                                    "plain": lambda ctx: {"ok": True}})
        self.assertEqual(sorted(reg), ["ok_tool", "plain"])


class BoundaryTest(ServerCase):
    """주입이 성공해도 서버가 하지 않는 일."""

    def test_unknown_tool_not_run(self):
        for name in ("Bash", "Read", "mcp__hazop__count", "../count", "", None, "write_file"):
            env = self.call(name) if name is not None else self.server.call(None, {})
            self.assertFalse(env["ok"], name)
            self.assertEqual(env["error"]["code"], "not_found", name)
        rep = self.rpc("tools/call", {"name": "Bash", "arguments": {"command": "dir"}})
        self.assertTrue(rep["result"]["isError"])

    def test_args_outside_signature_rejected(self):
        env = self.call("probe", id="g1/e-pz01", path="C:/Windows/win.ini")
        self.assertEqual(env["error"]["code"], "bad_args")
        self.assertEqual(self.spy.calls, [])

    def test_pathlike_values_rejected_before_tool(self):
        bad = ["..\\..\\Windows\\win.ini", "../../etc/passwd", "g1/../../x", "C:\\Users", "C:/Users", "/etc/passwd",
               "\\\\server\\share", "~/secret", "%APPDATA%", "file:///C:/x", "a\x00b"]
        for i, value in enumerate(bad):
            self.ask("q-path-%d" % i)  # 질문 상한에 걸리지 않게
            env = self.call("probe", id=value)
            self.assertEqual(env["error"]["code"], "bad_args", value)
            env = self.call("probe", filter={"tag": value})
            self.assertEqual(env["error"]["code"], "bad_args", value)
            env = self.call("probe", filter={"sheets": ["ok", value]})
            self.assertEqual(env["error"]["code"], "bad_args", value)
        self.assertEqual(self.spy.calls, [])

    def test_id_charset(self):
        self.assertEqual(self.call("probe", id="RC PZ01")["error"]["code"], "bad_args")
        self.assertEqual(self.call("probe", id="x" * 201)["error"]["code"], "bad_args")
        self.assertTrue(self.call("probe", id="graph-SNP-M-102/entity-node-001")["ok"])
        self.assertTrue(self.call("probe", filter={"tag": "RC-PV*"})["ok"])
        self.assertEqual(len(self.spy.calls), 2)

    def test_limit_arg_bounded(self):
        for bad in (0, 201, 10 ** 9, -1, True, "50", 2.5):
            self.ask("q-limit-%r" % (bad,))
            self.assertEqual(self.call("probe", id="g1/a", limit=bad)["error"]["code"], "bad_args", bad)
        self.assertTrue(self.call("probe", id="g1/a", limit=200)["ok"])
        self.assertEqual(len(self.spy.calls), 1)

    def test_call_limit_per_question(self):
        for _ in range(mcp_server.CALL_LIMIT):
            self.assertTrue(self.call("probe", id="g1/a")["ok"])
        env = self.call("probe", id="g1/a")
        self.assertEqual(env["error"]["code"], "limit_reached")
        self.assertEqual(len(self.spy.calls), mcp_server.CALL_LIMIT)
        self.ask("q-2")
        self.assertTrue(self.call("probe", id="g1/a")["ok"])

    def test_bad_calls_count_toward_limit(self):
        for _ in range(mcp_server.CALL_LIMIT):
            self.call("probe", id="../x")
        self.assertEqual(self.call("probe", id="g1/a")["error"]["code"], "limit_reached")

    def test_missing_question_file_still_limited(self):
        os.remove(self.qfile)
        for _ in range(mcp_server.CALL_LIMIT):
            self.call("count")
        self.assertEqual(self.call("count")["error"]["code"], "limit_reached")


class CursorTest(ServerCase):
    def test_paging_with_server_cursor(self):
        env = self.call("count", limit=2)
        token = env["cursor"]
        self.assertRegex(token, r"^c-[0-9a-f]{12}$")
        env2 = self.call("count", limit=2, cursor=token)
        self.assertEqual([g["key"] for g in env2["data"]["groups"]], ["pump", "tank"])
        env3 = self.call("count", limit=2, cursor=env2["cursor"])
        self.assertIsNone(env3["cursor"])

    def test_forged_cursor(self):
        for forged in ("c-000000000000", "2", "c-zzz", "../x"):
            env = self.call("count", limit=2, cursor=forged)
            self.assertEqual(env["error"]["code"], "bad_args", forged)

    def test_cursor_bound_to_tool_question_and_version(self):
        token = self.call("count", limit=2)["cursor"]
        self.assertEqual(self.call("trace_path", start="RC-PZ01", end="RC-PSV101", cursor=token)["error"]["code"],
                         "bad_args")
        self.version = "v2"
        self.assertEqual(self.call("count", limit=2, cursor=token)["error"]["code"], "bad_args")
        token = self.call("count", limit=2)["cursor"]
        self.ask("q-2")
        self.assertEqual(self.call("count", limit=2, cursor=token)["error"]["code"], "bad_args")

    def test_cursor_table_bounded(self):
        for i in range(mcp_server.CURSOR_TABLE_MAX + 20):
            self.server._give_cursor(self.server.registry["count"], "q-1", "{}", {"cursor": i}, "v1")
        self.assertLessEqual(len(self.server.cursors), mcp_server.CURSOR_TABLE_MAX)


class ReviewFixTest(ServerCase):
    """검토 지적(2026-11-13) 7번·3번."""

    def test_id_args_only_strings(self):
        for bad in ({"x": 1}, 12, 1.5, True, [{"id": "a"}], ["g1/a", 3]):
            self.ask("q-%r" % (bad,))
            self.assertEqual(self.call("probe", id=bad)["error"]["code"], "bad_args", bad)
        self.assertEqual(self.spy.calls, [])

    def test_id_charset_narrowed(self):
        for i, bad in enumerate(("a/C:/Windows/win.ini", "a:b", "g1/./x", "g1//x", "g1/", "a b", "가/나")):
            self.ask("q-n%d" % i)
            self.assertEqual(self.call("probe", id=bad)["error"]["code"], "bad_args", bad)
        self.ask("q-ok")
        for good in ("graph-SNP-M-102/entity-node-001", "S3", "S3/D05/e2", "doc-reg-1#12", "RC-PV101"):
            self.assertTrue(self.call("probe", id=good)["ok"], good)

    def test_nested_id_keys(self):
        for i, flt in enumerate(({"in_node": "C:x"}, {"in_node": 3}, {"near": {"id": "a/C:/x"}},
                                 {"sheets": ["ok", {"a": 1}]}, {"scope": "..\\x"}, {"cut_at": ["g1/a", "a:b"]})):
            self.ask("q-f%d" % i)
            self.assertEqual(self.call("probe", filter=flt)["error"]["code"], "bad_args", flt)
        self.assertEqual(self.spy.calls, [])
        self.assertIn("in_node", mcp_server.ID_ARGS)
        self.assertTrue({"scope", "cut_at"} <= mcp_server.ID_ARGS)

    def test_cursor_bound_to_args(self):
        token = self.call("count", limit=2, group_by="kind")["cursor"]
        self.assertEqual(self.call("count", limit=2, group_by="sheet", cursor=token)["error"]["code"], "bad_args")
        self.assertEqual(self.call("count", limit=3, group_by="kind", cursor=token)["error"]["code"], "bad_args")
        self.assertTrue(self.call("count", limit=2, group_by="kind", cursor=token)["ok"])

    def test_large_result_is_paged_not_dropped(self):
        env, text = self.server.call_text("rows", {})
        self.assertTrue(env["ok"])
        self.assertLessEqual(len(text) - len(mcp_server.PREFIX) - 1, mcp_server.MAX_RESULT_CHARS)
        self.assertRegex(env["cursor"], r"^c-[0-9a-f]{12}$")
        first = [r["id"] for r in env["data"]["rows"]]
        self.assertGreater(len(first), 1)
        self.assertLess(len(first), 50)
        nxt = self.server.call("rows", {"cursor": env["cursor"]})
        self.assertTrue(nxt["ok"])
        self.assertEqual(nxt["data"]["rows"][0]["id"], "g1/r%03d" % len(first))

    def test_errors_fixed_text_and_masked_log(self):
        lines = []
        server = mcp_server.Server(fake_tools.REGISTRY, "p", self.qfile,
                                   loader=lambda pid: fake_tools.FakeCtx(pid), log=lines.append)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            env, text = server.call_text("boom", {})
        self.assertEqual(env["error"], {"code": "bad_args", "message": mcp_server.MSG["tool_failed"]})
        self.assertEqual(stderr.getvalue(), "")
        home = os.path.expanduser("~")
        self.assertNotIn(home, text)
        self.assertNotIn("SECRET", text)
        self.assertEqual(len(lines), 1)
        logged = mcp_server.mask(lines[0])
        self.assertIn("RuntimeError", logged)
        self.assertNotIn(home, logged)
        self.assertNotIn("SECRETSECRET", logged)
        bad = mcp_server.Server(fake_tools.REGISTRY, "p", self.qfile, log=lines.append,
                                loader=lambda pid: (_ for _ in ()).throw(ValueError("C:\\Users\\someone 없음")))
        env = bad.call("count", {})
        self.assertEqual(env["error"], {"code": "no_data", "message": mcp_server.MSG["no_data"]})

    def test_read_lines_caps_size(self):
        data = b"x" * (mcp_server.MAX_REQUEST_BYTES + 10) + b"\n" + b'{"a":1}\n'
        got = list(mcp_server.read_lines(io.BytesIO(data)))
        self.assertEqual(got, [None, b'{"a":1}\n'])


class ResultTest(ServerCase):
    def test_too_large(self):
        env, text = self.server.call_text("big", {})
        self.assertEqual(env["error"]["code"], "too_large")
        self.assertLessEqual(len(text), mcp_server.MAX_RESULT_CHARS + len(mcp_server.PREFIX) + 1)

    def test_tool_exception_hidden(self):
        with contextlib.redirect_stderr(io.StringIO()):
            env, text = self.server.call_text("boom", {})
        self.assertEqual(env["error"]["code"], "bad_args")
        self.assertNotIn("Traceback", text)
        self.assertNotIn(REPO_ROOT, text)

    def test_loader_failure(self):
        server = mcp_server.Server(fake_tools.REGISTRY, "p", self.qfile,
                                   loader=lambda pid: (_ for _ in ()).throw(ValueError("추출한 도면이 없음")))
        self.assertEqual(server.call("count", {})["error"]["code"], "no_data")


def run_stdio(argv, lines, cwd=REPO_ROOT, timeout=60):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    data = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines).encode("utf-8")
    p = subprocess.run(argv, input=data, capture_output=True, cwd=cwd, env=env, timeout=timeout)
    out = [json.loads(x) for x in p.stdout.decode("utf-8").splitlines() if x.strip()]
    return p, out


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
INITED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


class StdioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-chat-mcp-")
        self.qfile = os.path.join(self.tmp, "question.json")
        with open(self.qfile, "w", encoding="utf-8") as fh:
            json.dump({"question_id": "q-1"}, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        calls = [{"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call",
                  "params": {"name": "get_component", "arguments": {"id": "g1/e-pz01"}}} for i in range(9)]
        p, out = run_stdio([sys.executable, "-E", "-s", FAKE_TOOLS, "--project", "p", "--question-file", self.qfile],
                           [INIT, INITED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}] + calls)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual([m["id"] for m in out], [1, 2] + [10 + i for i in range(9)])
        self.assertIn("trace_path", [t["name"] for t in out[1]["result"]["tools"]])
        envs = [json.loads(m["result"]["content"][0]["text"].split("\n", 1)[1]) for m in out[2:]]
        self.assertTrue(all(e["ok"] for e in envs[:8]))
        self.assertEqual(envs[8]["error"]["code"], "limit_reached")

    def test_reread_when_data_changes(self):
        vfile = os.path.join(self.tmp, "version.txt")
        with open(vfile, "w") as fh:
            fh.write("v1")
        argv = [sys.executable, "-E", "-s", FAKE_TOOLS, "--project", "p", "--question-file", self.qfile,
                "--version-file", vfile]
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=REPO_ROOT)
        try:
            def send(msg):
                proc.stdin.write(json.dumps(msg).encode("utf-8") + b"\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            def tool(mid, args):
                rep = send({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                            "params": {"name": "trace_path", "arguments": args}})
                return json.loads(rep["result"]["content"][0]["text"].split("\n", 1)[1])

            send(INIT)
            one = tool(2, {"start": "RC-PZ01", "end": "RC-PSV101"})
            self.assertEqual(one["data"]["path_ref"]["graph_version"], "v1")
            with open(vfile, "w") as fh:
                fh.write("v2")
            two = tool(3, {"start": "RC-PZ01", "end": "RC-PSV101"})
            self.assertEqual(two["data"]["path_ref"]["graph_version"], "v2")
        finally:
            proc.stdin.close()
            proc.wait(20)
            proc.stdout.close()
            proc.stderr.close()

    def test_oversized_request_and_quiet_stderr(self):
        big = {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
               "params": {"name": "count", "arguments": {"filter": {"tag": "x" * (mcp_server.MAX_REQUEST_BYTES + 1)}}}}
        boom = {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "boom", "arguments": {}}}
        env = dict(os.environ, HAZOP_WORK_ROOT=self.tmp)
        data = "".join(json.dumps(x) + "\n" for x in (INIT, big, boom, {"jsonrpc": "2.0", "id": 7, "method": "ping"}))
        p = subprocess.run([sys.executable, "-E", "-s", FAKE_TOOLS, "--project", "p", "--question-file", self.qfile],
                           input=data.encode("utf-8"), capture_output=True, cwd=REPO_ROOT, env=env, timeout=60)
        out = [json.loads(x) for x in p.stdout.decode("utf-8").splitlines() if x.strip()]
        self.assertEqual(out[1]["error"]["code"], -32600)
        self.assertTrue(out[2]["result"]["isError"])
        self.assertEqual(out[3]["result"], {})
        self.assertEqual(p.stderr, b"")

    def test_dev_entry_script(self):
        p, out = run_stdio([sys.executable, "-E", "-s", os.path.join(REPO_ROOT, "scripts", "run_chat_tools_server.py"),
                            "--project", "p", "--question-file", self.qfile],
                           [INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "hazop")
        self.assertIn("tools", out[1]["result"])

    def test_app_entry_without_qt(self):
        """앱 진입점 --chat-tools: Qt를 import하지 않고 서버만 돈다(배포본 HAZOP.exe --chat-tools와 같은 길)."""
        code = ("import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location('run_app', %r)\n"
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                "rc = m.main(['--chat-tools', '--project', 'p', '--question-file', %r])\n"
                "sys.stderr.write('QT=%%s RC=%%s\\n' %% (any(k.startswith('PySide6') for k in sys.modules), rc))\n"
                % (os.path.join(REPO_ROOT, "scripts", "run_app.py"), self.qfile))
        p, out = run_stdio([sys.executable, "-E", "-s", "-c", code],
                           [INIT, INITED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        err = p.stderr.decode("utf-8", "replace")
        self.assertIn("QT=False RC=0", err)
        self.assertEqual([m["id"] for m in out], [1, 2])


FORBIDDEN = ("PySide6", "PyQt5", "PyQt6", "shiboken6", "subprocess", "socket", "ssl", "urllib", "http", "requests",
             "httpx", "anthropic", "ftplib", "smtplib", "asyncio", "multiprocessing", "ctypes")


def imports(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


class StaticTest(unittest.TestCase):
    def test_chat_package_imports(self):
        """hazop/chat 전체: Qt·하위 프로세스·네트워크 모듈을 직접 import하지 않는다(규격 §2.6·§9.1)."""
        root = os.path.join(REPO_ROOT, "hazop", "chat")
        files = sorted(f for f in os.listdir(root) if f.endswith(".py"))
        self.assertIn("mcp_server.py", files)
        for f in files:
            bad = imports(os.path.join(root, f)) & set(FORBIDDEN)
            self.assertFalse(bad, "%s: %s" % (f, sorted(bad)))

    def test_server_entry_imports(self):
        bad = imports(os.path.join(REPO_ROOT, "scripts", "run_chat_tools_server.py")) & set(FORBIDDEN)
        self.assertFalse(bad)


if __name__ == "__main__":
    unittest.main()
