"""⑤ 실행 흐름 시험용 가짜 claude CLI. 실행: python fake_claude_flow.py <시나리오들> <상태 폴더> [CLI 인자...].

tests/fake_claude/fake_claude.py의 이벤트 모양을 그대로 쓰되 두 가지를 더한다.
- 호출 순서별 시나리오: '<시나리오들>'은 쉼표로 이은 목록(예: ok,ok,rejected). n번째 호출이 n번째 것을 쓰고, 목록보다 많이
  부르면 마지막 것을 계속 쓴다. 번호는 상태 폴더에 call-<n> 파일을 배타적으로 만들어 매긴다(동시 호출에서도 겹치지 않음).
- ok 계열은 stdin에서 물은 편차마다 시나리오 하나씩 담은 structured_output을 낸다(⑤ 칸이 실제로 채워지게).
시나리오: ok · slow(4초 뒤 ok) · warning · rejected · rejected_noreset · overage · notlogged · console(init의
apiKeySource가 API 키) · transient · hang(멈춤). 실제 모델·네트워크를 부르지 않는다.
"""

import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")  # 실제 CLI처럼 UTF-8로 낸다(콘솔 코드 페이지와 무관하게)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude"))
import fake_claude as fc  # noqa: E402

ASK_MARK = "다음 편차를 분석하라(JSON).\n"


def asked(data):
    text = data.decode("utf-8")
    return [d["deviation_id"] for d in json.loads(text.split(ASK_MARK, 1)[1])]


def output_for(ids, n):
    return {"deviations": [{"deviation_id": d, "applicable": True, "note": "",
                            "scenarios": [{"cause": "가짜 CLI 원인 %s (호출 %d)" % (d, n), "consequence": "결과",
                                           "safeguards": ["보호"], "recommendation": "권고", "severity": 3,
                                           "frequency": 2, "equipment_tags": [], "kg_paths": [], "sources": []}]}
                           for d in ids]}


def call_number(state):
    i = 1
    while True:
        try:
            os.close(os.open(os.path.join(state, "call-%d" % i), os.O_CREAT | os.O_EXCL))
            return i
        except FileExistsError:
            i += 1


def main():
    seq, state, args = sys.argv[1].split(","), sys.argv[2], sys.argv[3:]
    os.makedirs(state, exist_ok=True)
    if args[:1] == ["--version"]:
        print("2.1.319 (Claude Code)")
        return 0
    if args[:3] == ["auth", "status", "--json"]:
        auth = {"logged_out": {"loggedIn": False}}.get(seq[0], fc.AUTH_OK)
        print(json.dumps(auth))
        return 0 if auth.get("loggedIn") else 1
    data = fc.read_stdin(state)
    n = call_number(state)
    scenario = seq[min(n, len(seq)) - 1]
    model = args[args.index("--model") + 1] if "--model" in args else "claude-opus-5-5"
    if scenario == "hang":
        fc.init(model=model)
        time.sleep(120)
        return 0
    if scenario == "console":
        fc.init(source="ANTHROPIC_API_KEY", model=model)
        time.sleep(30)
        return 0
    if scenario.startswith("slow"):
        time.sleep(float(scenario[4:] or 4))
        scenario = "ok"
    fc.init(model=model)
    out = output_for(asked(data), n)
    if scenario == "ok":
        fc.limit()
        fc.result(structured_output=out, modelUsage={model: {}})
    elif scenario == "warning":
        fc.limit(status="allowed_warning", unifiedWindows={"seven_day": {"utilization": 0.86}})
        fc.result(structured_output=out, modelUsage={model: {}})
    elif scenario == "overage":
        fc.limit(status="allowed", overageStatus="allowed", isUsingOverage=True)
        fc.result(structured_output=out, modelUsage={model: {}})
    elif scenario == "rejected":
        fc.limit(status="rejected", resetsAt=int(time.time()) + 3600)
        fc.result(is_error=True, result="You've hit your limit", structured_output=None)
        return 1
    elif scenario == "rejected_noreset":
        fc.limit(status="rejected", resetsAt=None)
        fc.result(is_error=True, result="limit", structured_output=None)
        return 1
    elif scenario == "notlogged":
        fc.result(is_error=True, result="Not logged in · Please run /login", structured_output=None)
        return 1
    elif scenario == "transient":
        fc.emit({"type": "system", "subtype": "api_retry", "error": "overloaded"})
        fc.result(subtype="error_during_execution", is_error=True, result="Overloaded", structured_output=None)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
