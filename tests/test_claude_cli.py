"""구독 연결(로컬 claude CLI) 시험. 실제 구독 호출 없음: tests/fake_claude/fake_claude.py를 argv_prefix로 주입한다.
근거: 기획서/AI연결-구독제.md §5·§6·§8.1. 실행: python -m unittest tests.test_claude_cli
"""

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from hazop.study import ai_cells, claude_cli, claude_http, providers

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude", "fake_claude.py")
REQUEST = {"system": "시스템 지시", "context": "구간 맥락 한국어", "user": "편차 묶음", "schema": ai_cells.RESPONSE_SCHEMA}


def alive(pid):
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def wait_for(path, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if os.path.exists(path) and os.path.getsize(path):
            return True
        time.sleep(0.05)
    return False


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "log")
        self.run_root = os.path.join(self.tmp, "run")
        self.limits = os.path.join(self.tmp, "ai_limits.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, scenario, **kw):
        return claude_cli.ClaudeCliClient(argv_prefix=[sys.executable, FAKE, scenario, self.log],
                                          limits_path=self.limits, run_root=self.run_root, **kw)

    def call(self):
        with open(os.path.join(self.log, "call.json"), encoding="utf-8") as fh:
            return json.load(fh)


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object")
class AnalyzeTest(CliCase):
    def test_ok_fills_contract_and_record_fields(self):
        r = self.client("ok").analyze(REQUEST)
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["output"]["deviations"][0]["deviation_id"], "D01")
        self.assertEqual((r["via"], r["billing"], r["error_kind"], r["cost_usd"]), ("subscription", "plan", None, None))
        self.assertEqual(r["api_equiv_usd"], 0.0005643)
        self.assertEqual((r["model_requested"], r["model"]), ("claude-opus-5-5", "claude-opus-5-5"))
        self.assertEqual(r["usage"]["cache_creation_input_tokens"], 1688)
        self.assertEqual(r["limit"]["status"], "limit_ok")
        self.assertEqual(r["limit"]["resets_at"], 4102444800)
        self.assertTrue(os.path.isfile(self.limits), "한도 정보가 저장됨")

    def test_isolation_flags_env_stdin_and_cwd(self):
        env = dict(os.environ, ANTHROPIC_API_KEY="sk-ant-secret", CLAUDE_CODE_OAUTH_TOKEN="tok", ANTHROPIC_BASE_URL="x")
        with mock.patch.dict(os.environ, env):
            self.client("ok").analyze(REQUEST)
        c = self.call()
        for k in claude_cli.SCRUB_ENV:
            self.assertNotIn(k, c["env"])
        self.assertEqual(c["env"]["DISABLE_TELEMETRY"], "1")
        args = c["args"]
        for flag, value in (("--tools", ""), ("--setting-sources", ""), ("--permission-mode", "dontAsk"),
                            ("--permission-prompts", "none"), ("--disallowedTools", "mcp__*"),
                            ("--output-format", "stream-json"), ("--model", "claude-opus-5-5")):
            self.assertEqual(args[args.index(flag) + 1], value, flag)
        for flag in ("-p", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
            self.assertIn(flag, args)
        self.assertFalse([a for a in args if "dangerously" in a or a == "bypassPermissions"], "권한 우회 없음")
        self.assertEqual(json.loads(args[args.index("--json-schema") + 1]), ai_cells.RESPONSE_SCHEMA)
        self.assertEqual(c["stdin"], "구간 맥락 한국어\n\n편차 묶음")
        self.assertEqual(c["cwd_files"], [], "작업 폴더는 빈 임시 폴더")
        self.assertTrue(os.path.normcase(c["cwd"]).startswith(os.path.normcase(self.run_root)))
        self.assertEqual(os.listdir(self.run_root), [], "끝나면 작업 폴더를 지움")

    def test_garbage_lines_skipped(self):
        self.assertEqual(self.client("garbage").analyze(REQUEST)["status"], "completed")

    def test_classification_table(self):
        cases = {
            "retries": ("parse_error", "bad_output", None),
            "no_output": ("parse_error", "bad_output", None),
            "schema400": ("parse_error", "bad_output", None),
            "refusal": ("refused", "refused", None),
            "notlogged": ("api_error", "not_ready", "login_required"),
            "account": ("api_error", "not_ready", "account_blocked"),
            "transient": ("api_error", "transient", None),
            "rejected": ("api_error", "limit_reached", None),
            "crash": ("api_error", "other", None),
            "argerr": ("api_error", "other", None),
        }
        for scenario, want in cases.items():
            with self.subTest(scenario):
                r = self.client(scenario).analyze(REQUEST)
                self.assertEqual((r["status"], r["error_kind"], r["conn_state"]), want)
                self.assertTrue(r["error"])

    def test_limit_reached_has_reset_time_and_halts(self):
        r = self.client("rejected").analyze(REQUEST)
        self.assertIn("재설정", r["error"])
        self.assertEqual(r["limit"]["status"], "limit_reached")
        self.assertTrue(providers.halts([None, r["error_kind"]]))

    def test_argerr_keeps_stderr(self):
        self.assertIn("unknown option", self.client("argerr").analyze(REQUEST)["error"])

    def test_warning_completes(self):
        r = self.client("warning").analyze(REQUEST)
        self.assertEqual((r["status"], r["limit"]["status"]), ("completed", "limit_warning"))

    def test_overage_applies_result_but_halts(self):
        r = self.client("overage").analyze(REQUEST)
        self.assertEqual((r["status"], r["billing"], r["error_kind"]), ("completed", "overage", "overage"))
        self.assertTrue(providers.halts([r["error_kind"]]))
        allowed = self.client("overage", allow_overage=True).analyze(REQUEST)
        self.assertEqual((allowed["billing"], allowed["error_kind"]), ("overage", None))

    def test_auth_mismatch_kills_before_model_request(self):
        t0 = time.monotonic()
        r = self.client("mismatch").analyze(REQUEST)
        self.assertLess(time.monotonic() - t0, 15)
        self.assertEqual((r["error_kind"], r["conn_state"]), ("auth_mismatch", "not_subscription"))
        time.sleep(0.5)
        self.assertFalse(os.path.exists(os.path.join(self.log, "model_called")))

    def test_timeout_kills_tree(self):
        c = self.client("hang", timeout=2)
        t0 = time.monotonic()
        r = c.analyze(REQUEST)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(r["error_kind"], "timeout")

    def _child_scenario(self, stop, **kw):
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            c = self.client("child", **kw)
            box = {}
            import threading
            t = threading.Thread(target=lambda: box.setdefault("r", c.analyze(REQUEST)))
            t.start()
            pid_file = os.path.join(self.log, "child.pid")
            self.assertTrue(wait_for(pid_file), "가짜가 손자 프로세스를 띄움")
            with open(pid_file) as fh:
                kid = int(fh.read())
            self.assertTrue(alive(kid))
            stop(c)
            t.join(20)
            self.assertFalse(t.is_alive())
            time.sleep(0.5)
            self.assertFalse(alive(kid), "손자까지 끝남")
            self.assertTrue(alive(bystander.pid), "앱이 띄우지 않은 같은 이름의 프로세스는 살아 있음")
            return box["r"]
        finally:
            bystander.kill()
            bystander.wait()

    def test_cancel_kills_grandchild_only(self):
        r = self._child_scenario(lambda c: c.cancel())
        self.assertEqual(r["error_kind"], "cancelled")

    def test_timeout_kills_grandchild(self):
        r = self._child_scenario(lambda c: None, timeout=4)
        self.assertEqual(r["error_kind"], "timeout")

    def test_taskkill_fallback_when_job_fails(self):
        r = self._child_scenario(lambda c: c.cancel(), job_factory=lambda proc: None)
        self.assertEqual(r["error_kind"], "cancelled")

    def test_overage_on_failed_call_halts(self):
        r = self.client("overage_fail").analyze(REQUEST)
        self.assertEqual((r["billing"], r["error_kind"]), ("overage", "overage"))
        self.assertTrue(providers.halts([r["error_kind"]]))

    def test_rejected_with_result_keeps_output_and_halts(self):
        r = self.client("rejected_ok").analyze(REQUEST)
        self.assertEqual((r["status"], r["error_kind"]), ("completed", "limit_reached"))

    def test_rejected_without_reset_blocks_check(self):
        self.client("rejected_noreset").analyze(REQUEST)
        self.assertEqual(self.client("ok").check()["state"], "limit_reached")

    def test_descendant_holding_stdout_does_not_hang(self):
        t0 = time.monotonic()
        r = self.client("held", timeout=30).analyze(REQUEST)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(r["status"], "completed")
        with open(os.path.join(self.log, "child.pid")) as fh:
            kid = int(fh.read())
        time.sleep(0.5)
        self.assertFalse(alive(kid), "남은 자손은 Job으로 끝냄")

    def test_cancel_during_setup(self):
        c = self.client("hang", timeout=30)
        real = claude_cli._run_dir

        def slow(root):
            c.cancel()
            return real(root)

        with mock.patch.object(claude_cli, "_run_dir", slow):
            t0 = time.monotonic()
            r = c.analyze(REQUEST)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(r["error_kind"], "cancelled")

    def test_stdin_written_after_job_assignment(self):
        order = []

        def factory(proc):
            order.append("job")
            return claude_cli.create_job(proc)

        real = claude_cli._write_stdin
        with mock.patch.object(claude_cli, "_write_stdin", lambda p, d: (order.append("stdin"), real(p, d))):
            r = self.client("ok", job_factory=factory).analyze(REQUEST)
        self.assertEqual(r["status"], "completed")
        self.assertEqual(order, ["job", "stdin"])


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object")
class CheckTest(CliCase):
    def test_states(self):
        for scenario, state in (("ok", "ok"), ("old", "cli_too_old"), ("logged_out", "login_required"),
                                ("console", "not_subscription"), ("expired", "login_expired")):
            with self.subTest(scenario):
                s = self.client(scenario).check()
                self.assertEqual(s["state"], state)
                self.assertEqual(s["via"], "subscription")
                self.assertNotIn("someone@example.com", json.dumps(s, ensure_ascii=False))
        self.assertEqual(self.client("ok").check()["plan"], "max_20x")

    def test_stored_limit_states(self):
        future = int(time.time()) + 3600
        for info, state in (({"status": "limit_reached"}, "limit_reached"),
                            ({"status": "limit_ok", "utilization": 0.95, "overage": "on"}, "overage_risk"),
                            ({"status": "limit_warning", "overage": "off"}, "limit_warning"),
                            ({"status": "limit_ok", "overage": "in_use"}, "overage_risk"),
                            ({"status": "limit_warning", "overage": None}, "overage_risk"),
                            ({"status": "limit_ok", "utilization": 0.1}, "ok")):
            with self.subTest(state):
                claude_cli.save_limit(self.limits, dict(info, resets_at=future))
                self.assertEqual(self.client("ok").check()["state"], state)
        claude_cli.save_limit(self.limits, {"status": "limit_reached", "resets_at": int(time.time()) - 1})
        self.assertEqual(self.client("ok").check()["state"], "ok", "재설정 시각이 지나면 무시")


class FindTest(unittest.TestCase):
    def test_find_prefers_exe_and_rejects_cmd(self):
        tmp = tempfile.mkdtemp()
        try:
            cmd = os.path.join(tmp, "claude.cmd")
            exe = os.path.join(tmp, "claude.exe")
            open(cmd, "w").close()
            home = os.path.join(tmp, "home")
            self.assertEqual(claude_cli.find_cli(None, which=lambda _n: cmd, home=home), (None, "cli_unsupported"))
            self.assertEqual(claude_cli.find_cli(None, which=lambda _n: None, home=home), (None, "not_installed"))
            open(exe, "w").close()
            self.assertEqual(claude_cli.find_cli(exe, which=lambda _n: cmd, home=home), (exe, "ok"))
            os.makedirs(os.path.join(home, ".local", "bin"))
            native = os.path.join(home, ".local", "bin", "claude.exe")
            open(native, "w").close()
            self.assertEqual(claude_cli.find_cli(None, which=lambda _n: cmd, home=home), (native, "ok"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_not_installed_analyze(self):
        c = claude_cli.ClaudeCliClient(cli_path=None)
        with mock.patch.object(claude_cli, "find_cli", return_value=(None, "not_installed")):
            r = c.analyze(REQUEST)
            self.assertEqual((r["error_kind"], r["conn_state"]), ("not_ready", "not_installed"))
            self.assertEqual(c.check()["state"], "not_installed")


class ProvidersTest(unittest.TestCase):
    def test_frozen_hides_subscription(self):
        with mock.patch("hazop.paths.frozen_bundle_dir", return_value="C:/bundle"):
            self.assertEqual(providers.available_methods(), ("api",))
            self.assertEqual(providers.default_method("ok"), "api")
            with self.assertRaises(ValueError):
                providers.make_client("subscription")
        with mock.patch("hazop.paths.frozen_bundle_dir", return_value=None):
            self.assertEqual(providers.default_method("ok"), "subscription")
            self.assertEqual(providers.default_method("login_required"), "api")
            self.assertIsInstance(providers.make_client("subscription"), claude_cli.ClaudeCliClient)
            self.assertIsInstance(providers.make_client("api", key_provider=lambda: None), claude_http.ClaudeHttpClient)

    def test_halts_streak(self):
        self.assertFalse(providers.halts(["timeout", "timeout"]))
        self.assertTrue(providers.halts(["timeout", "timeout", "timeout"]))
        self.assertFalse(providers.halts(["timeout", None, "timeout", "timeout"]))
        self.assertTrue(providers.halts(["not_ready"]))

    def test_api_error_kinds(self):
        for resp, want in (({"status": "no_key"}, ("not_ready", "no_key")),
                           ({"status": "api_error", "error_type": "auth", "status_code": 401}, ("not_ready", "key_invalid")),
                           ({"status": "api_error", "error_type": "rate_limit", "status_code": 429},
                            ("rate_limited", "rate_limited")),
                           ({"status": "api_error", "error_type": "timeout"}, ("timeout", None)),
                           ({"status": "api_error", "error_type": "overloaded", "status_code": 529}, ("transient", None)),
                           ({"status": "completed"}, (None, None))):
            self.assertEqual(providers.api_error_kind(resp), want)

    def test_fixed_client(self):
        tmp = tempfile.mkdtemp()
        try:
            c = providers.FixedCellsClient(tmp)
            self.assertEqual(c.analyze(REQUEST)["conn_state"], "no_folder")
            with open(os.path.join(tmp, providers.fixed_key(REQUEST) + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"output": {"deviations": []}}, fh)
            r = c.analyze(REQUEST)
            self.assertEqual((r["status"], r["via"], r["billing"]), ("completed", "fixed", "none"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SchemaRuleTest(unittest.TestCase):
    def test_response_schema_property_names(self):
        """CLI 구조화 출력은 속성 이름이 ^[a-zA-Z0-9_.-]{1,64}$만 된다(§2.2 실측, 한글 키는 400)."""
        bad = []

        def walk(node):
            if isinstance(node, dict):
                for name in (node.get("properties") or {}):
                    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", name):
                        bad.append(name)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(ai_cells.RESPONSE_SCHEMA)
        self.assertEqual(bad, [])


class RecordTest(unittest.TestCase):
    """⑤ 결과 기록: 구독 필드를 남기고, API 경로 기록은 옛 필드 값이 그대로이며, 옛 파일(via 없음)은 api로 읽힌다."""

    UNIT = {"unit_id": "N1/flow", "node_id": "N1", "deviation_ids": ["D01"]}
    DEVS = [{"deviation_id": "D01", "parameter": "flow", "guideword": "no", "label": "흐름 없음"}]
    CTX = {"prompt": {}, "allowed": {}, "adjacency": {}}

    class Fake:
        def __init__(self, resp):
            self.resp = resp

        def analyze(self, _request):
            return dict(self.resp)

    def run_unit(self, resp):
        with mock.patch.object(ai_cells, "_cells", return_value={}):
            return ai_cells.run_unit(self.Fake(resp), self.UNIT, self.CTX, self.DEVS, "T1")

    def test_api_path_keeps_old_values(self):
        usage = {"input_tokens": 1000, "output_tokens": 100}
        ur = self.run_unit({"status": "completed", "output": {"deviations": []}, "usage": usage,
                            "model": "claude-opus-5-5"})
        self.assertEqual(ur["cost_usd"], claude_http.cost_usd(usage, "claude-opus-5-5"))
        self.assertEqual((ur["via"], ur["billing"], ur["error_kind"], ur["api_equiv_usd"]), ("api", "per_call", None, None))
        self.assertEqual(ur["model_requested"], "claude-opus-5-5")

    def test_overage_kind_survives_bad_output(self):
        ur = self.run_unit({"status": "completed", "output": {"foo": 1}, "via": "subscription", "error_kind": "overage",
                            "billing": "overage", "cost_usd": None})
        self.assertEqual((ur["status"], ur["error_kind"]), ("failed", "overage"))

    def test_subscription_cost_not_in_total(self):
        ur = self.run_unit({"status": "completed", "output": {"deviations": []}, "usage": {"input_tokens": 5},
                            "model": "claude-opus-5-5", "via": "subscription", "billing": "plan", "error_kind": None,
                            "cost_usd": None, "api_equiv_usd": 0.25, "model_requested": "claude-opus-5-5"})
        results = {"cells": [], "ai_log": [{"cost_usd": 0.5, "usage": {}}]}
        with mock.patch.object(ai_cells, "_cells", return_value={}):
            out = ai_cells.apply_unit(results, ur)
        rec = out["ai_log"][-1]
        self.assertEqual((rec["via"], rec["cost_usd"], rec["api_equiv_usd"]), ("subscription", None, 0.25))
        total = ai_cells.usage_total(out)
        self.assertEqual((total["cost_usd"], total["api_equiv_usd"], total["calls"]), (0.5, 0.25, 2))
        self.assertEqual(providers.record_via(results["ai_log"][0]), "api", "via 없는 옛 기록은 api")


if __name__ == "__main__":
    unittest.main()
