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

OUTPUT = {"deviations": [{"deviation_id": "D01", "applicable": False, "note": "해당 없음", "scenarios": []}]}
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


def main():
    scenario, log_dir, args = sys.argv[1], sys.argv[2], sys.argv[3:]
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
