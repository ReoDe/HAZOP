"""시험용 가짜 claude CLI. 실행: python fake_claude.py <시나리오> <기록 폴더> [CLI 인자...].

받은 인자·작업 폴더·환경변수·stdin을 <기록 폴더>/call.json에 남기고, 시나리오대로 stream-json을 낸다.
이벤트 모양은 기획서/AI연결-구독제.md §2.2의 실측을 본뜬다. 실제 모델·네트워크를 부르지 않는다.
"""

import json
import os
import subprocess
import sys
import threading
import time

# 실제 claude CLI는 콘솔 코드 페이지와 관계없이 UTF-8로 쓴다(기획서/AI연결-구독제.md 실측). 가짜도 같게 해야
# 한국어가 든 이벤트가 cp949 콘솔에서 깨지지 않는다.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

OUTPUT ={"deviations": [{"deviation_id": "D01", "applicable": False, "note": "해당 없음", "scenarios": []}]}
USAGE = {"input_tokens": 2, "output_tokens": 453, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1688}
LIMIT_OK = {"status": "allowed", "resetsAt": 4102444800, "rateLimitType": "seven_day", "overageStatus": "rejected",
            "isUsingOverage": False, "unifiedWindows": {"seven_day": {"utilization": 0.04, "resetsAt": 4102444800,
                                                                      "status": "allowed"}}}
AUTH_OK = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max",
           "planTier": "max_20x", "email": "someone@example.com", "orgId": "org-secret"}


def emit(ev):
    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def init(source="none", model="claude-opus-5-5"):
    emit({"type": "system", "subtype": "init", "apiKeySource": source, "model": model, "tools": ["StructuredOutput"]})


def limit(**over):
    emit({"type": "rate_limit_event", "rate_limit_info": dict(LIMIT_OK, **over)})


def result(**over):
    base = {"type": "result", "subtype": "success", "is_error": False, "stop_reason": "tool_use", "usage": USAGE,
            "total_cost_usd": 0.0005643, "modelUsage": {"claude-opus-5-5": {}}, "structured_output": OUTPUT}
    base.update(over)
    emit(base)


def read_stdin(log):
    got = {}
    t = threading.Thread(target=lambda: got.setdefault("data", sys.stdin.buffer.read()), daemon=True)
    t.start()
    t.join(3.0)
    if "data" not in got:
        sys.stderr.write("Warning: no stdin data received in 3s, proceeding without it\n")
        sys.exit(1)
    return got["data"]


def _arg(args, flag):
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


class _McpClient:
    """MCP 설정 파일의 hazop 서버를 실제로 띄워 tools/call을 보낸다(앱 서버까지 이어진 왕복 시험)."""

    def __init__(self, config_path):
        with open(config_path, encoding="utf-8") as fh:
            spec = json.load(fh)["mcpServers"]["hazop"]
        self.proc = subprocess.Popen([spec["command"]] + list(spec.get("args") or []), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)
        self.next_id = 0
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "fake-claude", "version": "0"}})
        self.proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        self.proc.stdin.flush()

    def request(self, method, params):
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params},
                                         ensure_ascii=False).encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline().decode("utf-8"))

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


CHAT_ENV_PRESENT = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE",
                    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_OAUTH_TOKEN")
CHAT_ENV_VALUES = ("DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING", "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY",
                   "DISABLE_FEEDBACK_COMMAND")
# 실측 init(2.1.323, --setting-sources "")의 plugins 모양
BUILTIN_PLUGINS = [{"name": "cc-plugin-agents-md", "path": "builtin", "source": "cc-plugin-agents-md@builtin"},
                   {"name": "cc-plugin-privacy", "path": "builtin", "source": "cc-plugin-privacy@builtin"}]


def chat(scenario, log_dir, args):
    """--input-format stream-json(채팅) 흉내. 시나리오 'chat' 또는 'chat@<대본 JSON>'.

    대본: {"turns": [차례, ...], "no_read": 초}. no_read면 stdin을 읽지 않고 그만큼 잔다. 질문 i에는 turns[min(i, 끝)]을 쓴다. 차례 키:
      init: system/init 덮어쓰기(tools·mcp_servers·permissionMode·apiKeySource). 기본은 허용 목록 그대로
      skip_init: true면 init 없이 시작, pre: 먼저 낼 이벤트 목록
      calls: [{"name": 도구 이름(접두 없음) 또는 "raw": 전체 이름, "args": {...}}] → tool_use, MCP 서버 호출, tool_result
      sleep: 답 전에 잠자는 초, child: true면 오래 자는 자식을 띄우고 child.pid를 남김
      answer: 구조화 출력, result: result 이벤트 덮어쓰기, exit: 이 차례 뒤 이 코드로 끝냄(result 없음),
      quit: true면 답을 낸 뒤 끝냄
    """
    script = {"turns": [{"calls": [{"name": "count", "args": {"limit": 2}}]}]}
    if "@" in scenario:
        with open(scenario.split("@", 1)[1], encoding="utf-8") as fh:
            script = json.load(fh)
    allowed = [x for x in (_arg(args, "--allowedTools") or "").split(",") if x]
    # 상속 환경변수는 통째로 남기지 않는다. 시험이 보는 키의 '있음'과 조용히 하기 값만 남긴다(값에 키·경로가 섞일 수 있음).
    env = {k: True for k in CHAT_ENV_PRESENT if k in os.environ}
    env.update({k: os.environ[k] for k in CHAT_ENV_VALUES if k in os.environ})
    with open(os.path.join(log_dir, "call.json"), "w", encoding="utf-8") as fh:
        json.dump({"args": args, "cwd": os.getcwd(), "cwd_files": os.listdir(os.getcwd()), "env": env,
                   "pid": os.getpid()}, fh, ensure_ascii=False)
    if script.get("no_read"):  # stdin을 읽지 않는 CLI(앱의 쓰기가 막히는 경우)
        time.sleep(script["no_read"])
        return 0
    server = None
    tool_n = 0
    try:
        for i, raw in enumerate(sys.stdin.buffer):
            msg = json.loads(raw.decode("utf-8"))
            with open(os.path.join(log_dir, "messages.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(msg, ensure_ascii=False) + "\n")
            turn = script["turns"][min(i, len(script["turns"]) - 1)]
            if server is None and _arg(args, "--mcp-config"):
                server = _McpClient(_arg(args, "--mcp-config"))
            if not turn.get("skip_init"):
                ev = {"type": "system", "subtype": "init", "apiKeySource": "none", "model": _arg(args, "--model"),
                      "permissionMode": _arg(args, "--permission-mode"), "tools": ["StructuredOutput"] + allowed,
                      "mcp_servers": [{"name": "hazop", "status": "connected", "source": "dynamic"}],
                      "plugins": BUILTIN_PLUGINS, "skills": [], "slash_commands": [], "additional_directories": []}
                ev.update(turn.get("init") or {})
                emit(ev)
            for ev in turn.get("pre") or []:
                emit(ev)
            for call in turn.get("calls") or []:
                tool_n += 1
                name = call.get("raw") or "mcp__hazop__" + call["name"]
                uid = "toolu_%04d" % tool_n
                emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": uid, "name": name,
                                                                    "input": call.get("args") or {}}]}})
                if name.startswith("mcp__hazop__") and server is not None:
                    rep = server.request("tools/call", {"name": name[len("mcp__hazop__"):],
                                                        "arguments": call.get("args") or {}})
                    res = rep.get("result") or {"content": [{"type": "text", "text": json.dumps(rep)}], "isError": True}
                else:
                    res = {"content": [{"type": "text", "text": "No such tool available: %s" % name}], "isError": True}
                emit({"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": uid, "content": res["content"], "is_error": res["isError"]}]}})
            if turn.get("child"):
                kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
                with open(os.path.join(log_dir, "child.pid"), "w") as fh:
                    fh.write(str(kid.pid))
            if turn.get("sleep"):
                time.sleep(turn["sleep"])
            if "exit" in turn:
                return turn["exit"]
            answer = turn.get("answer") or {"text": "답 %d" % i}
            emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_so%d" % i,
                                                                "name": "StructuredOutput", "input": answer}]}})
            base = {"type": "result", "subtype": "success", "is_error": False, "stop_reason": "tool_use",
                    "num_turns": len(turn.get("calls") or []) + 1, "usage": USAGE, "structured_output": answer}
            base.update(turn.get("result") or {})
            emit(base)
            if turn.get("quit"):  # 답 뒤에 CLI가 혼자 끝남
                return 0
    finally:
        if server is not None:
            server.close()
    return 0


def main():
    scenario, log_dir, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    if scenario.split("@", 1)[0] == "chat" and _arg(args, "--input-format") == "stream-json":
        os.makedirs(log_dir, exist_ok=True)
        return chat(scenario, log_dir, args)
    if "@" in scenario:  # '<시나리오>@<JSON 파일>': structured_output을 그 파일 내용으로(구간 검토 등 다른 스키마 시험)
        scenario, out_path = scenario.split("@", 1)
        with open(out_path, encoding="utf-8") as fh:
            OUTPUT.clear()
            OUTPUT.update(json.load(fh))
    os.makedirs(log_dir, exist_ok=True)
    if args[:1] == ["--version"]:
        print("%s (Claude Code)" % ("2.1.200" if scenario == "old" else "2.1.319"))
        return 0
    if args[:3] == ["auth", "status", "--json"]:
        auth = {"logged_out": {"loggedIn": False}, "console": dict(AUTH_OK, authMethod="console"),
                "expired": dict(AUTH_OK, loginExpiresAt="2001-01-01T00:00:00Z")}.get(scenario, AUTH_OK)
        print(json.dumps(auth))
        return 0 if auth.get("loggedIn") else 1
    if scenario == "argerr":
        sys.stderr.write("error: unknown option '--no-such-flag'\n")
        return 1
    data = read_stdin(log_dir)
    with open(os.path.join(log_dir, "call.json"), "w", encoding="utf-8") as fh:
        json.dump({"args": args, "cwd": os.getcwd(), "cwd_files": os.listdir(os.getcwd()), "env": dict(os.environ),
                   "stdin": data.decode("utf-8")}, fh, ensure_ascii=False)
    if scenario == "mismatch":
        init(source="ANTHROPIC_API_KEY")
        time.sleep(30)
        open(os.path.join(log_dir, "model_called"), "w").close()
        result()
        return 0
    if scenario == "hang":
        time.sleep(60)
        return 0
    if scenario == "child":
        kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        with open(os.path.join(log_dir, "child.pid"), "w") as fh:
            fh.write(str(kid.pid))
        init()
        time.sleep(60)
        return 0
    if scenario == "held":
        init()
        result()
        kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=sys.stdout)
        with open(os.path.join(log_dir, "child.pid"), "w") as fh:
            fh.write(str(kid.pid))
        return 0
    if scenario == "crash":
        sys.stderr.write("Segmentation fault\n")
        return 3
    init()
    if scenario == "ok":
        limit()
        result()
    elif scenario == "garbage":
        sys.stdout.write("not json at all\n{broken\n")
        emit({"type": "assistant", "message": {}})
        limit()
        result()
    elif scenario == "warning":
        limit(status="allowed_warning", unifiedWindows={"seven_day": {"utilization": 0.85}})
        result()
    elif scenario == "overage":
        limit(status="allowed", overageStatus="allowed", isUsingOverage=True)
        result()
    elif scenario == "rejected":
        limit(status="rejected", resetsAt=4102444800)
        result(is_error=True, result="You've hit your limit", structured_output=None)
        return 1
    elif scenario == "overage_fail":
        limit(overageStatus="allowed", isUsingOverage=True)
        emit({"type": "system", "subtype": "api_retry", "error": "overloaded"})
        result(subtype="error_during_execution", is_error=True, result="Overloaded", structured_output=None)
        return 1
    elif scenario == "rejected_ok":
        limit(status="rejected")
        result()
    elif scenario == "rejected_noreset":
        limit(status="rejected", resetsAt=None)
        result(is_error=True, result="limit", structured_output=None)
        return 1
    elif scenario == "notlogged":
        result(is_error=True, result="Not logged in · Please run /login", structured_output=None)
        return 1
    elif scenario == "account":
        emit({"type": "system", "subtype": "api_retry", "error": "account_on_hold"})
        result(subtype="error_during_execution", is_error=True, result="account on hold", structured_output=None)
        return 1
    elif scenario == "transient":
        emit({"type": "system", "subtype": "api_retry", "error": "overloaded"})
        result(subtype="error_during_execution", is_error=True, result="Overloaded", structured_output=None)
        return 1
    elif scenario == "retries":
        result(subtype="error_max_structured_output_retries", is_error=True, structured_output=None)
        return 1
    elif scenario == "no_output":
        result(structured_output=None)
    elif scenario == "schema400":
        result(is_error=True, api_error_status=400, structured_output=None,
               result="API Error: 400 tools.1.custom.input_schema.properties: Property keys should match pattern")
        return 1
    elif scenario == "refusal":
        result(is_error=True, stop_reason="refusal", structured_output=None)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
