"""Excel 워크시트 출력 (기획서/인터페이스.md §6) -> 출력/워크시트/<구간 ID>/<실행 ID>/worksheet-<출력 시각>.xlsx

사용 예:
  python scripts/export_worksheet.py --run 출력/분석/region-SNP-M-102-pzr/<실행 ID>
  python scripts/export_worksheet.py --run <실행 폴더> --scope accepted_modified   # 수용·수정 행만
  python scripts/export_worksheet.py --run <실행 폴더> --store-root <저장 루트> --out-root <워크시트 루트>

검토 기록은 <저장 루트>/reviews/<구간 ID>/<실행 ID>/에서 읽고, 출력 기록을 같은 곳의 exports/<출력 시각>.json에 남긴다.
blocked 결과, analysis.json 해시가 검토 기록과 다르면 출력하지 않는다. 같은 이름의 파일은 덮어쓰지 않는다.
종료 코드 0 = 출력함, 1 = 차단·오류.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop import review as rv  # noqa: E402
from hazop.export import SCOPES, export_worksheet  # noqa: E402


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="분석 실행 폴더(analysis.json이 있는 곳)")
    ap.add_argument("--store-root", default=paths.store_root(), help="검토 기록 저장 루트 (기본 %(default)s)")
    ap.add_argument("--out-root", default=paths.output_root("워크시트"), help="워크시트 출력 루트 (기본 %(default)s)")
    ap.add_argument("--scope", default="all", choices=sorted(SCOPES), help="all=전체(기본), accepted_modified=수용·수정 행만")
    args = ap.parse_args(argv)
    try:
        res = export_worksheet(args.run, args.store_root, args.out_root, scope=args.scope)
    except rv.ReviewError as exc:  # ExportError 포함
        print("출력하지 않음:")
        for e in exc.errors:
            print("  -", e)
        return 1
    rows = res["record"]["rows"]
    print("워크시트 %d행, 개선 권고 %d건 (범위: %s)" % (len(rows["worksheet"]), len(rows["recommendations"]),
                                              res["record"]["scope_label"]))
    print("파일:", res["path"])
    print("출력 기록:", res["export_record_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
