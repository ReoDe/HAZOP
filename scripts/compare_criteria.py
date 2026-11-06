"""평가 기준 비교 (기획서/평가기준비교.md) -> 출력/평가비교/<구간 ID>/<실행 ID>/compare-<기준 ID>-v<버전>-<basis>-<시각>.json·.xlsx

사용 예:
  python scripts/compare_criteria.py --criteria 데이터/평가기준/criteria-SNP-M-102-pzr-sample.json --run 출력/분석/region-SNP-M-102-pzr/<실행 ID>
  python scripts/compare_criteria.py --criteria <기준.xlsx> --format xlsx_sheet --run <실행 폴더> --basis reviewed
  python scripts/compare_criteria.py --criteria <기준> --run <실행 폴더> --export <저장 루트>/reviews/.../exports/<시각>.json

결과 위치는 <작업 루트>/출력/평가비교(작업 루트는 HAZOP_WORK_ROOT로 바꿀 수 있음). 같은 이름 파일은 덮어쓰지 않는다.
AI·네트워크를 쓰지 않는다. 종료 코드 0 = 비교함(status ok), 1 = 차단(blocked 보고를 썼거나 쓸 수 없음)·오류.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop import review as rv  # noqa: E402
from hazop.evaluate import BASES, CompareError, run_compare  # noqa: E402
from hazop.evaluate.adapters import ADAPTERS  # noqa: E402


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--criteria", required=True, help="평가 기준 파일(정본 JSON 또는 Excel 양식)")
    ap.add_argument("--run", required=True, help="분석 실행 폴더(analysis.json이 있는 곳)")
    ap.add_argument("--store-root", default=paths.store_root(), help="검토 기록 저장 루트 (기본 %(default)s)")
    ap.add_argument("--basis", default="draft", choices=BASES, help="draft=도구 초안(기본), reviewed=검토 반영")
    ap.add_argument("--export", default=None, help="출력 기록 JSON(워크시트 행 번호 연결·해시 확인)")
    ap.add_argument("--format", default="json", choices=sorted(ADAPTERS), help="기준 파일 형식 (기본 json)")
    ap.add_argument("--now", default=None, help="비교 시각 UTC 'YYYY-MM-DDTHH:MM:SSZ' (기본 현재)")
    args = ap.parse_args(argv)
    try:
        res = run_compare(args.criteria, args.run, args.store_root, paths.output_root("평가비교"),
                          basis=args.basis, export_path=args.export, fmt=args.format, now=args.now)
    except (CompareError, rv.ReviewError) as exc:
        print("비교하지 않음:")
        for e in exc.errors:
            print("  -", e)
        return 1
    rep = res["report"]
    if rep.get("notice"):
        print("[주의] %s" % rep["notice"])
    print("상태: %s  비교 ID: %s" % (rep["status"], rep["comparison_id"]))
    for r in rep["reasons"]:
        print("  - 차단 사유:", r)
    if rep["metrics"]:
        for k in ("deviation_recall", "cause_recall", "cause_precision", "consequence_match", "safeguard_match",
                  "recommendation_match"):
            print("  %s: %s" % (k, rep["metrics"][k]))
        print("  counts: %s" % rep["metrics"]["counts"])
        print("  기준 경고: %d건" % len(rep["criteria_warnings"]))
    print("JSON: %s" % res["json_path"])
    print("Excel: %s" % res["xlsx_path"])
    return 0 if rep["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
