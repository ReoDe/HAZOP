"""drawio P&ID -> 출력/추출/<도면번호>/extraction.json + validation_report.md

사용 예:
  python scripts/extract_drawio.py "참고자료/P&ID 도면 샘플/SNP-M-101_RCS-main-loop/SNP-M-101_RCS-main-loop.drawio"
  python scripts/extract_drawio.py --samples          # 샘플 6개 전체
  python scripts/extract_drawio.py --registration 자료저장소/<프로젝트>/registrations/<자료 ID>/<버전>.json
옵션 --svg를 생략하면 원본 옆 SVG를 좌표 대응 측정에 쓴다(hazop.extract.svg_align.find_svg, 등록과 같은 규칙):
  한 페이지 문서는 같은 이름 <파일명>.svg·<stem>.svg -> <NN>_<페이지 이름>.drawio.svg -> 폴더에 하나뿐인 *.drawio.svg,
  여러 페이지 문서는 <NN>_<페이지 이름>.drawio.svg만. 경로로 해석될 수 있는 페이지 이름·원본 폴더 밖 파일은 쓰지 않는다.
--registration(① 등록 완료 자료)이면 보관 원본을 읽어 출력/추출/<프로젝트>__<자료 ID>-r<등록 버전>-p<페이지>/에 쓴다.
  SVG는 등록정보의 파생 자료(derived_files, role svg)를 먼저 쓰고(svg_alignment.source = registered_derived),
  없을 때만 등록 당시 입력 경로(input_path) 옆에서 찾는다(source = "input_path_sibling, unregistered").
경로: 출력·입력 표시 경로는 작업 루트(HAZOP_WORK_ROOT, 기본 저장소 루트), 샘플은 자원 루트(HAZOP_RESOURCE_ROOT) 기준.
"""

import argparse
import glob
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.extract import drawio, report, svg_align  # noqa: E402
from hazop.register import registry  # noqa: E402

SAMPLE_GLOB = paths.resource_path("참고자료", "P&ID 도면 샘플", "*", "*.drawio")
DEFAULT_OUT = paths.output_root("추출")


def find_svg(drawio_path, page_index=0, page_name=None, page_count=1):
    """원본 옆 SVG 찾기. 등록(hazop/register)과 같은 함수(svg_align.find_svg)를 쓴다."""
    return svg_align.find_svg(drawio_path, page_index, page_name, page_count)


def registered_out_name(registration, page_index, limit=120):
    """등록 경로 출력 폴더 이름 <프로젝트>__<자료>-r<버전>-p<페이지>.
    safe_name의 길이 제한(120자)에 걸리면 뒤쪽 식별자(자료·버전·페이지)는 그대로 두고 프로젝트 부분만 줄인 뒤
    원래 프로젝트 ID의 해시 12자리를 붙여 서로 다른 프로젝트가 같은 이름이 되지 않게 한다."""
    tail = paths.safe_name("%s-r%s-p%d" % (registration["material_id"], registration["registration_version"],
                                            page_index))
    project = paths.safe_name(registration["project_id"])
    room = limit - len(tail) - 2  # '__'
    if len(project) > room:
        digest = hashlib.sha256(str(registration["project_id"]).encode("utf-8")).hexdigest()[:12]
        project = project[:room - 13].rstrip("._") + "-" + digest
    return project + "__" + tail


def run_one(path, out_root, svg="auto", page=0, registration=None, registered_svgs=None):
    """registered_svgs: 등록정보의 파생 SVG {페이지 ID: 경로}(registry.registered_svgs, 해시 확인 끝난 것).
    svg가 auto이고 추출한 페이지의 파생 SVG가 있으면 먼저 쓴다."""
    root = paths.work_root()
    result = drawio.extract(path, page=page, repo_root=root, registration=registration)
    svg_path = svg
    svg_source = None
    if svg == "auto":
        near = path
        reg_svg = (registered_svgs or {}).get(result["source_context"]["page_id"])
        if registration is not None and reg_svg:
            svg_path, svg_source = reg_svg, "registered_derived"
        elif registration is not None:
            # 한계: 이 등록에는 파생 SVG가 없다. 등록 당시 입력 경로 옆에서 찾으므로
            # 그 SVG가 등록 원본과 같은 판인지 등록 단계가 보증하지 않는다(결과 JSON의 source로 표시).
            near = os.path.join(root, registration["input_path"])  # 작업 루트 밖이면 절대 경로가 그대로 쓰임
            svg_source = "input_path_sibling, unregistered"
        if svg_source != "registered_derived":
            svg_path = find_svg(near, result["run"]["settings"]["page_index"], result["source_context"]["page_name"],
                                result["source"]["page_count"])
    if svg_path:
        al = svg_align.align(svg_path, result)
        al["svg_file"] = paths.rel_or_abs(svg_path, root)
        if svg_source:
            al["source"] = svg_source
        result["coordinate_system"]["svg_alignment"] = al
    if registration is not None:
        # 등록 경로: 프로젝트·자료 ID·등록 버전·페이지별 폴더에 저장해 다른 프로젝트·버전·페이지 결과를 덮어쓰지 않는다.
        # 그래프·뷰어가 추출 폴더를 한 단계만 읽으므로 계층 대신 한 폴더 이름(<프로젝트>__<자료>-r<버전>-p<페이지>)으로 둔다.
        name = registered_out_name(registration, result["run"]["settings"]["page_index"])
    else:
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
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("drawio", nargs="*", help="drawio 파일 경로")
    ap.add_argument("--samples", action="store_true", help="참고자료 샘플 전체 추출")
    ap.add_argument("--registration", action="append", default=[],
                    help="① 등록정보 JSON (등록 완료 자료만, 여러 번 지정 가능)")
    ap.add_argument("--svg", default="auto", help="대응 SVG 경로 (기본 auto, 'none'이면 생략)")
    ap.add_argument("--page", default="0", help="페이지 번호(0부터) 또는 이름")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    jobs = [(p, None, None) for p in args.drawio]
    if args.samples:
        jobs += [(p, None, None) for p in sorted(glob.glob(SAMPLE_GLOB))]
    for reg_path in args.registration:
        try:
            record, original = registry.load_for_extraction(reg_path)
            reg_svg = registry.registered_svgs(reg_path, record)
        except (OSError, ValueError) as exc:
            ap.error("%s: %s" % (reg_path, exc))
        jobs.append((original, record, reg_svg))
    if not jobs:
        ap.error("drawio 파일, --samples 또는 --registration 필요")
    if len(jobs) > 1 and args.svg not in ("auto", "none"):
        ap.error("--svg 경로는 파일 하나일 때만 지정")
    page = int(args.page) if args.page.isdigit() else args.page
    svg = None if args.svg == "none" else args.svg
    blocked = 0
    for path, record, reg_svg in jobs:
        result, out_dir = run_one(path, args.out_root, svg=svg, page=page, registration=record, registered_svgs=reg_svg)
        s = result["summary"]
        al = result["coordinate_system"]["svg_alignment"]
        print("%s: %s nodes=%d relations=%d unresolved=%d texts=%d unknowns=%d blockers=%d svg=%s %s -> %s"
              % (result["drawing"]["drawing_number"] or os.path.basename(out_dir), result["validation"]["status"], s["nodes"],
                 s["relations"], s["unresolved_connectors"], s["texts"], s["unknowns"],
                 s["blockers"], al["status"] if al else None, al["offset"] if al else None,
                 paths.rel_or_abs(out_dir, paths.work_root())))
        blocked += result["validation"]["status"] == "blocked"
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
