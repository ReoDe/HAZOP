"""단계 연쇄 검사: ①등록 → ②추출 → ③그래프 → ④분석 → ⑤검토·출력의 저장 결과가 ID·버전·해시·상태대로 이어지는지 본다.

  python scripts/check_contract.py [--region <region_id>] [--run latest|all|<analysis_run_id>]
                                   [--work-root <폴더>] [--store-root <폴더>] [--report <JSON 경로>]

근거: 기획서/단계연쇄검사.md. 읽기 전용(--report로 지정한 보고 파일만 씀, 입력 폴더 안이면 거부). 네트워크·AI 호출 없음.
작업 루트·저장 루트 기본값은 hazop.paths.work_root()와 HAZOP_STORE_ROOT 또는 <작업 루트>/자료저장소.
종료 코드: 0 = FAIL 없음, 1 = FAIL 1개 이상, 2 = 실행 오류(입력 폴더 없음, JSON 읽기 실패 등).
실행 오류가 있으면 FAIL이 있어도 2.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402
from hazop import contract  # noqa: E402


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", help="검사할 구간 ID (기본: 데이터/구간/*.json 전체)")
    ap.add_argument("--run", default="latest", help="latest(기본, 구간별 최신 실행) | all | <analysis_run_id>")
    ap.add_argument("--work-root", help="작업 루트 (기본 hazop.paths.work_root())")
    ap.add_argument("--store-root", help="저장 루트 (기본 HAZOP_STORE_ROOT 또는 <작업 루트>/자료저장소)")
    ap.add_argument("--report", help="결과 JSON을 쓸 경로 (입력 폴더 안이면 거부)")
    args = ap.parse_args(argv)
    try:
        result = contract.check(args.work_root, args.store_root, args.region, args.run)
    except (contract.ContractError, OSError) as exc:
        print("[ERROR] %s" % exc)
        return 2
    for line in contract.render_console(result):
        print(line)
    if args.report:
        try:
            contract.write_report(result, args.report)
        except (contract.ContractError, OSError) as exc:
            print("[ERROR] %s" % exc)
            return 2
        print("보고: %s" % args.report)
    return contract.exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
