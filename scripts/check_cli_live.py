"""구독 연결 실측(사용자가 직접 실행, 구독 사용량을 조금 씀). 기획서/AI연결-구독제.md §8.2 M4~M7.

    python scripts/check_cli_live.py            연결 확인만(토큰 안 씀)
    python scripts/check_cli_live.py --live     표본 문장으로 2회 호출(실제 발전소 자료 없음)

결과에 이메일·조직 ID는 남기지 않는다. 호출 뒤 claude.ai 사용량 화면과 Console 요금을 확인한다(M5).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.study import ai_cells, claude_cli  # noqa: E402

SAMPLE = {"system": ai_cells.SYSTEM_PROMPT,
          "context": ai_cells.CONTEXT_PREFIX + json.dumps({"node": "표본 구간: 물탱크와 배수 밸브"}, ensure_ascii=False),
          "user": ai_cells.USER_PREFIX + json.dumps([{"deviation_id": "D01", "parameter": "level", "guideword": "more",
                                                       "label": "수위 높음"}], ensure_ascii=False),
          "schema": ai_cells.RESPONSE_SCHEMA}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="실제 구독으로 2회 호출")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    client = claude_cli.ClaudeCliClient(model=args.model, effort=args.effort)
    status = client.check()
    print(json.dumps(status, ensure_ascii=False, indent=1))
    if not args.live:
        return 0
    if status["state"] not in ("ok", "limit_warning"):
        print("연결 확인을 통과하지 못해 호출하지 않음: %s" % status["state"])
        return 1
    for i in (1, 2):
        r = client.analyze(SAMPLE)
        keep = {k: r[k] for k in ("status", "error_kind", "error", "model_requested", "model", "billing", "usage",
                                  "api_equiv_usd", "limit")}
        print("호출 %d: %s" % (i, json.dumps(keep, ensure_ascii=False)))
        if r["status"] != "completed":
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
