"""도면 그래프(output/graph/<이름>/graph.json) -> DEXPI XML 2.0.1 파일 + 뺀 목록 + 곁 파일 + 묶음 목록(HZ-PLN-22 §6).

사용 예:
  python scripts/export_dexpi.py --out D:/내보내기                 # 그래프가 있는 모든 도면
  python scripts/export_dexpi.py --out D:/내보내기 SNP-M-101 SNP-M-102
도면마다 `<이름>.dexpi.xml`, `<이름>.excluded.json`(뺀 구성요소·연결·속성과 근사), `<이름>.hazop.json`(곁 파일)을 쓰고
묶음 목록 `manifest.json`을 쓴다. **쪽 확정이 `confirmed`인 도면만** 내보내고(`sheet_confirmation`, 화면 규격 V3) 나머지는
`manifest.json`의 `not_exported`에 적는다. 도면 번호는 등록에서 사람이 확정한 것만 내보낸다. `--assume-confirmed`는 쪽 확정과 도면 번호
확정을 모두 확정으로 보는 개발·시험용이다.
검사(스키마 규칙·클래스 목록·참조·되읽기)에 걸리면 아무 파일도 쓰지 않고 사유를 보인다. 쓸 파일이 --out에 이미 있으면 쓰지 않고
목록을 보인다(--overwrite를 주면 덮음). 종료 코드 0은 성공, 1은 내보내지 못함.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.export import dexpi_export  # noqa: E402


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="output/graph 아래 도면 이름(없으면 전부)")
    ap.add_argument("--out", required=True, help="파일을 쓸 폴더")
    ap.add_argument("--graph-root", default=None)
    ap.add_argument("--extract-root", default=None)
    ap.add_argument("--assume-confirmed", action="store_true", help="쪽 확정·도면 번호 확정을 모두 확정으로 보고 내보낸다(개발·시험용)")
    ap.add_argument("--overwrite", action="store_true", help="--out에 앞 내보내기 파일이 있으면 덮는다")
    args = ap.parse_args(argv)
    try:
        res = dexpi_export.export_names(args.names or None, args.out, graph_root=args.graph_root, extract_root=args.extract_root,
                                        require_confirmed_number=not args.assume_confirmed,
                                        confirmation="assume" if args.assume_confirmed else "auto", overwrite=args.overwrite)
    except dexpi_export.ExportError as exc:
        print("내보내지 못함:")
        for reason in exc.reasons:
            print("  - %s" % reason)
        return 1
    if res["status"] == "exists":
        print("이미 있는 파일이 있어 쓰지 않음(--overwrite로 덮음): %s" % ", ".join(res["existing"]))
        return 1
    for d in res["drawings"]:
        s = d["stats"]
        print("%s: 구성요소 %d, 연결 %d, 뺀 구성요소 %d·연결 %d·속성 %d, 뺀 것 때문에 끊긴 배관 %d, 근사 %d -> %s"
              % (d["drawing_number"], s["components"], s["connections"], s["excluded_components"], s["excluded_connections"],
                 s["excluded_attributes"], s["cut_pipes"], s["approximations"], paths.plain_rel(args.out, paths.work_root())))
    for x in res["not_exported"]:
        print("내보내지 않음: %s(쪽 확정 %s, 남은 미확인 %d)" % (x["name"], x["state"], x["unconfirmed"]))
    print("묶음 목록: %s" % res["manifest"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
