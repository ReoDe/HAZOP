"""drawio P&ID -> 출력/추출/<도면번호>/extraction.json + validation_report.md

사용 예:
  python scripts/extract_drawio.py "참고자료/P&ID 도면 샘플/SNP-M-101_RCS-main-loop/SNP-M-101_RCS-main-loop.drawio"
  python scripts/extract_drawio.py --samples          # 샘플 6개 전체
옵션 --svg를 생략하면 같은 폴더의 *.drawio.svg가 하나일 때 그것을 좌표 대응 측정에 쓴다.
"""

import argparse
import glob
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import drawio, report, svg_align  # noqa: E402

SAMPLE_GLOB = os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio")
DEFAULT_OUT = os.path.join(REPO_ROOT, "출력", "추출")


def find_svg(drawio_path):
    found = glob.glob(os.path.join(os.path.dirname(drawio_path), "*.drawio.svg"))
    return found[0] if len(found) == 1 else None


def run_one(path, out_root, svg="auto", page=0):
    result = drawio.extract(path, page=page, repo_root=REPO_ROOT)
    svg_path = find_svg(path) if svg == "auto" else svg
    if svg_path:
        al = svg_align.align(svg_path, result)
        al["svg_file"] = os.path.relpath(svg_path, REPO_ROOT).replace("\\", "/")
        result["coordinate_system"]["svg_alignment"] = al
    name = paths.safe_name(result["drawing"]["drawing_number"] or os.path.splitext(os.path.basename(path))[0])
    out_dir = paths.safe_join(out_root, name)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "extraction.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    with open(os.path.join(out_dir, "validation_report.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report.render(result))
    return result, out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("drawio", nargs="*", help="drawio 파일 경로")
    ap.add_argument("--samples", action="store_true", help="참고자료 샘플 전체 추출")
    ap.add_argument("--svg", default="auto", help="대응 SVG 경로 (기본 auto, 'none'이면 생략)")
    ap.add_argument("--page", default="0", help="페이지 번호(0부터) 또는 이름")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    paths = list(args.drawio)
    if args.samples:
        paths += sorted(glob.glob(SAMPLE_GLOB))
    if not paths:
        ap.error("drawio 파일 또는 --samples 필요")
    if len(paths) > 1 and args.svg not in ("auto", "none"):
        ap.error("--svg 경로는 파일 하나일 때만 지정")
    page = int(args.page) if args.page.isdigit() else args.page
    svg = None if args.svg == "none" else args.svg
    blocked = 0
    for path in paths:
        result, out_dir = run_one(path, args.out_root, svg=svg, page=page)
        s = result["summary"]
        al = result["coordinate_system"]["svg_alignment"]
        print("%s: %s nodes=%d relations=%d unresolved=%d texts=%d unknowns=%d blockers=%d svg=%s %s -> %s"
              % (result["drawing"]["drawing_number"], result["validation"]["status"], s["nodes"],
                 s["relations"], s["unresolved_connectors"], s["texts"], s["unknowns"],
                 s["blockers"], al["status"] if al else None, al["offset"] if al else None,
                 os.path.relpath(out_dir, REPO_ROOT)))
        blocked += result["validation"]["status"] == "blocked"
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
