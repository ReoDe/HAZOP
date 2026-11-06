"""벡터 PDF P&ID -> 출력/어댑터/pdf_vector/<도면번호>/extraction.json + validation_report.md (T3 W3)

사용 예:
  python scripts/extract_pdf.py "참고자료/P&ID 도면 샘플/SNP-M-102_RCS-pressurizer/SNP-M-102_RCS-pressurizer.pdf"
  python scripts/extract_pdf.py --samples          # 샘플 6개 PDF 전체
pdfplumber가 필요하다(결정 D1). 없으면 종료 코드 2로 끝난다.
출력은 drawio 추출 결과(출력/추출/)와 섞이지 않도록 기본값을 출력/어댑터/pdf_vector/ 로 둔다.
평가(drawio 정답 대비 지표)는 scripts/check_adapter.py가 한다.
"""

import argparse
import glob
import importlib.util
import json
import os
import sys
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402
from hazop.extract import report  # noqa: E402
from hazop.extract.adapters import pdf_svg, pdf_vector  # noqa: E402

SAMPLE_GLOB = paths.resource_path("참고자료", "P&ID 도면 샘플", "*", "*.pdf")
DEFAULT_OUT = paths.output_root("어댑터", "pdf_vector")
SVG_NAME = "page.svg"
SVG_SOURCE = "rendered_from_pdf"


def run_one(path, out_root, page=0, registration=None, out_name=None):
    """registration(① 등록정보)을 주면 등록 경로: 식별 정보를 채우고(pdf_vector.apply_registration), out_name 폴더에
    쓰며, PDF에서 그린 도면 SVG(page.svg, pdf_svg)를 함께 저장해 ② 뷰어 정렬(offset 0, 같은 좌표)을 기록한다."""
    result = pdf_vector.extract(path, page=page, repo_root=paths.work_root(), registration=registration)
    name = out_name or paths.safe_name(result["drawing"]["drawing_number"] or os.path.splitext(os.path.basename(path))[0])
    out_dir = paths.safe_join(out_root, name)
    os.makedirs(out_dir, exist_ok=True)
    if registration is not None:
        svg_path = os.path.join(out_dir, SVG_NAME)
        svg_text = pdf_svg.render_page_svg(path, page)
        with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg_text)
        root = ET.fromstring(svg_text)
        result["coordinate_system"]["svg_alignment"] = {
            "svg_file": paths.rel_or_abs(svg_path, paths.work_root()), "source": SVG_SOURCE,
            "viewBox": root.get("viewBox"), "width": root.get("width"), "height": root.get("height"), "status": "verified", "reasons": [],
            "offset": [0, 0], "transform": "svg_x = pdf_x, svg_y = pdf_y (같은 pdfplumber 좌표로 그림)",
            "compared_cells": 0, "consistent_cells": 0, "inconsistent_offsets": [], "unsupported_transform_cells": [],
            "excluded_local_transform_cells": [], "cells_missing_in_svg": [],
            "note": "PDF 벡터 요소(선·곡선·사각형·글자)를 추출과 같은 좌표로 그린 SVG라 셀 비교 없이 일치. "
                    "이미지·클리핑은 그리지 않음"}
    with open(os.path.join(out_dir, "extraction.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    with open(os.path.join(out_dir, "validation_report.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report.render(result))
    return result, out_dir


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="*", help="벡터 PDF 경로")
    ap.add_argument("--samples", action="store_true", help="참고자료 샘플 PDF 전체")
    ap.add_argument("--page", type=int, default=0, help="페이지 번호(0부터)")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    jobs = list(args.pdf) + (sorted(glob.glob(SAMPLE_GLOB)) if args.samples else [])
    if not jobs:
        ap.error("PDF 파일 또는 --samples 필요")
    if importlib.util.find_spec("pdfplumber") is None:
        print("pdfplumber가 없어 실행할 수 없음(결정 D1). pdfplumber가 설치된 Python으로 실행할 것.")
        return 2
    blocked = 0
    for path in jobs:
        result, out_dir = run_one(path, args.out_root, args.page)
        s = result["summary"]
        print("%s: %s nodes=%d relations=%d unresolved=%d texts=%d unknowns=%d blockers=%d -> %s"
              % (result["drawing"]["drawing_number"] or os.path.basename(out_dir), result["validation"]["status"],
                 s["nodes"], s["relations"], s["unresolved_connectors"], s["texts"], s["unknowns"], s["blockers"],
                 paths.rel_or_abs(out_dir, paths.work_root())))
        blocked += result["validation"]["status"] == "blocked"
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
