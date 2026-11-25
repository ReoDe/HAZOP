"""등록된 DEXPI 도면의 사람 고침을 같은 도면의 새 파일로 옮긴다(hazop.extract.edit_link, HZ-PLN-22 §4.2.1).

사용 예(이름은 output/extract 아래의 폴더 이름):
  python scripts/link_dexpi_edits.py <옛 추출 이름> <새 추출 이름> --by 홍길동 --dry-run
  python scripts/link_dexpi_edits.py <옛 추출 이름> <새 추출 이름> --by 홍길동
옮긴 뒤 새 도면의 그래프를 다시 짓는다(scripts/build_graph.py). 같은 도면이 아니면 아무것도 쓰지 않고 1을 돌려준다.
"""

import argparse
import collections
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop.extract import edit_link  # noqa: E402

STATES = {"none": "옮길 고침이 없음", "already": "이미 옮김", "preview": "미리 보기(쓰지 않음)", "carried": "옮김"}


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--by", required=True, help="옮긴 사람 이름")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        out = edit_link.carry(args.old, args.new, args.by, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print("옮기지 않음: %s" % exc)
        return 1
    count = collections.Counter(r["outcome"] for r in out["rows"])
    print("%s: 그대로 적용 %d, 이어짐 %d, 적용 안 됨 %d" % (STATES[out["state"]], count["same"], count["linked"], count["left"]))
    for r in out["rows"]:
        if r["outcome"] == "left":
            print("  %s %s: %s" % (r["op_id"], r["target"] or "-", edit_link.WHY[r["why"]]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
