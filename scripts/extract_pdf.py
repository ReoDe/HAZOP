"""벡터 PDF P&ID -> output/adapter/pdf_vector/<도면번호>/extraction.json + validation_report.md (T3 W3)

사용 예:
  python scripts/extract_pdf.py "resources/references/pid-samples/SNP-M-102_RCS-pressurizer/SNP-M-102_RCS-pressurizer.pdf"
  python scripts/extract_pdf.py --samples          # 샘플 6개 PDF 전체
  python scripts/extract_pdf.py 도면.pdf --pages all   # 모든 쪽(또는 --pages 0,2 처럼 0부터 센 쪽 번호)
  python scripts/extract_pdf.py --registration store/<프로젝트>/registrations/<자료 ID>/<버전>.json
--registration(① 등록 완료 자료)이면 보관 원본의 등록된 모든 쪽을 <--out-root>/<프로젝트>__<자료 ID>-r<등록 버전>-p<쪽>/에
쓰고 PDF에서 그린 page.svg를 함께 만든다(쪽을 고르면 그 쪽만). 글자·벡터 경로가 없거나 읽지 못한 쪽은 그 쪽 폴더에
extraction.json 대신 not_extracted.json(사유)을 남긴다. 등록 없이 두 쪽 이상이면 폴더 이름 끝에 -p<쪽>을 붙인다(0쪽 제외).
추출했든 못 했든 쪽 폴더에 extraction_run.json(이 실행이 읽은 기호 사전 판, hazop/extract/runinfo.py)을 함께 남긴다.
pdfplumber가 필요하다(결정 D1). 없으면 종료 코드 2로 끝난다.
출력은 drawio 추출 결과(output/extract/)와 섞이지 않도록 기본값을 output/adapter/pdf_vector/ 로 둔다.
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
from hazop.extract import report, runinfo, symbols  # noqa: E402
from hazop.extract.adapters import pdf_svg, pdf_vector  # noqa: E402
from hazop.register import registry  # noqa: E402

SAMPLE_GLOB = paths.folder("references", "pid-samples", "*", "*.pdf")
DEFAULT_OUT = paths.output_root("adapter", "pdf_vector")
SVG_NAME = "page.svg"
SVG_SOURCE = "rendered_from_pdf"
NOT_EXTRACTED = "not_extracted.json"  # 추출하지 않은 쪽의 사유 기록(extraction.json 대신)
EXTRACTOR = "pdf_vector"  # 실행 정보(extraction_run.json)에 적는 추출기 종류


def not_extracted_reason(result):
    """이 쪽을 추출하지 않은 사유(글자·벡터 경로 없음). 추출했으면 None."""
    return next((b["reason"] for b in result["validation"]["blockers"] if b["check"] == "no_vector_content"), None)


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _clear(out_dir, names):
    """다시 추출할 때 이전 상태(추출됨/미추출) 파일이 함께 남아 두 상태로 집계되지 않게 지운다."""
    for name in names:
        p = os.path.join(out_dir, name)
        if os.path.isfile(p):
            os.remove(p)


def _skip(out_dir, page, reason, symbol_versions):
    os.makedirs(out_dir, exist_ok=True)
    _clear(out_dir, ("extraction.json", "validation_report.md", SVG_NAME))
    _write_json(os.path.join(out_dir, NOT_EXTRACTED), {"page_index": page, "page_id": "page-%d" % (page + 1),
                                                       "reason": reason})
    runinfo.write(out_dir, EXTRACTOR, None, symbol_versions)


def _default_name(path, page, drawing_number=None):
    name = drawing_number or os.path.splitext(os.path.basename(path))[0]
    return paths.safe_name(name + ("-p%d" % page if page else ""))  # 여러 쪽이 같은 도면번호여도 폴더가 겹치지 않게


def run_one(path, out_root, page=0, registration=None, out_name=None):
    """registration(① 등록정보)을 주면 등록 경로: 식별 정보를 채우고(pdf_vector.apply_registration), out_name 폴더에
    쓰며, PDF에서 그린 도면 SVG(page.svg, pdf_svg)를 함께 저장하고 기호 bbox 대조로 ② 뷰어 정렬을 측정한다.
    글자·벡터 경로가 없는 쪽은 extraction.json 대신 not_extracted.json(사유)을 쓴다(not_extracted_reason)."""
    result = pdf_vector.extract(path, page=page, repo_root=paths.work_root(), registration=registration)
    symbol_versions = pdf_vector.symbol_library().versions  # 사전을 읽지 못하면 이 쪽 폴더를 건드리기 전에 멈춘다
    out_dir = paths.safe_join(out_root, out_name or _default_name(path, page, result["drawing"]["drawing_number"]))
    reason = not_extracted_reason(result)
    if reason:
        _skip(out_dir, page, reason, symbol_versions)
        return result, out_dir
    os.makedirs(out_dir, exist_ok=True)
    _clear(out_dir, (NOT_EXTRACTED,))
    if registration is not None:
        svg_path = os.path.join(out_dir, SVG_NAME)
        svg_text = pdf_svg.render_page_svg(path, page, result)
        with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg_text)
        root = ET.fromstring(svg_text)
        al = {"svg_file": paths.rel_or_abs(svg_path, paths.work_root()), "source": SVG_SOURCE,
              "viewBox": root.get("viewBox"), "width": root.get("width"), "height": root.get("height")}
        al.update(pdf_svg.measure_alignment(svg_text, result))
        result["coordinate_system"]["svg_alignment"] = al
    _write_json(os.path.join(out_dir, "extraction.json"), result)
    with open(os.path.join(out_dir, "validation_report.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report.render(result))
    runinfo.write(out_dir, EXTRACTOR, result, symbol_versions)
    return result, out_dir


def run_pages(path, out_root, pages, registration=None, out_name=None):
    """여러 쪽을 차례로 run_one. out_name: 쪽 번호 → 폴더 이름(없으면 run_one 기본 이름).
    반환 (추출한 쪽 [(쪽, result, out_dir)], 추출하지 않은 쪽 [{"page_index", "page_id", "reason"}])."""
    done, skipped = [], []
    symbol_versions = pdf_vector.symbol_library().versions  # 기호 사전이 없거나 깨졌으면 어떤 쪽의 이전 결과도 지우기 전에 멈춘다
    for page in pages:
        name = out_name(page) if out_name else None
        try:
            result, out_dir = run_one(path, out_root, page, registration, name)
        except (ImportError, symbols.SymbolLibraryError):
            raise
        except Exception as exc:  # 쪽 하나를 읽지 못해도 그 쪽만 미추출로 남기고 다음 쪽을 읽는다
            reason = "추출 오류: %s" % exc
            _skip(paths.safe_join(out_root, name or _default_name(path, page)), page, reason, symbol_versions)
        else:
            reason = not_extracted_reason(result)
            if reason is None:
                done.append((page, result, out_dir))
                continue
        skipped.append({"page_index": page, "page_id": "page-%d" % (page + 1), "reason": reason})
    return done, skipped


def page_count(path):
    import pdfplumber  # 지연 import(pdf_vector와 같음)
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


def registered_pages(record):
    """등록정보 page_ids(page-<번호>) → 쪽 번호(0부터)."""
    return [int(pid.rsplit("-", 1)[1]) - 1 for d in record.get("documents") or [] for pid in d.get("page_ids") or []]


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="*", help="벡터 PDF 경로")
    ap.add_argument("--samples", action="store_true", help="참고자료 샘플 PDF 전체")
    ap.add_argument("--registration", action="append", default=[],
                    help="① 등록정보 JSON (등록 완료 자료만, 여러 번 지정 가능). 쪽을 고르지 않으면 등록된 모든 쪽")
    ap.add_argument("--page", type=int, help="페이지 번호(0부터, 기본 0)")
    ap.add_argument("--pages", help="여러 쪽: all 또는 0,2 처럼 쉼표로(0부터)")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if args.pages is not None and args.page is not None:
        ap.error("--page와 --pages는 함께 쓸 수 없음")
    if args.pages not in (None, "all") and not all(v.strip().isdigit() for v in args.pages.split(",")):
        ap.error("--pages는 all 또는 0부터 센 쪽 번호를 쉼표로: %r" % args.pages)
    jobs = [(p, None) for p in list(args.pdf) + (sorted(glob.glob(SAMPLE_GLOB)) if args.samples else [])]
    for reg_path in args.registration:
        try:
            record, original = registry.load_for_extraction(reg_path)
        except (OSError, ValueError) as exc:
            ap.error("%s: %s" % (reg_path, exc))
        jobs.append((original, record))
    if not jobs:
        ap.error("PDF 파일, --samples 또는 --registration 필요")
    if importlib.util.find_spec("pdfplumber") is None:
        print("pdfplumber가 없어 실행할 수 없음(결정 D1). pdfplumber가 설치된 Python으로 실행할 것.")
        return 2
    failed = 0
    for path, record in jobs:
        if args.pages == "all":
            pages = list(range(page_count(path)))
        elif args.pages is not None:
            pages = [int(v) for v in args.pages.split(",")]
        elif args.page is not None:
            pages = [args.page]
        else:
            pages = registered_pages(record) if record else [0]
        out_name = None
        if record is not None:
            import extract_drawio  # 등록 출력 폴더 이름은 drawio 등록 경로와 같은 규칙
            out_name = lambda i, r=record: extract_drawio.registered_out_name(r, i)  # noqa: E731
        done, skipped = run_pages(path, args.out_root, pages, record, out_name)
        for page, result, out_dir in done:
            s = result["summary"]
            print("%s p%d: %s nodes=%d relations=%d unresolved=%d texts=%d unknowns=%d blockers=%d -> %s"
                  % (result["drawing"]["drawing_number"] or os.path.basename(out_dir), page,
                     result["validation"]["status"], s["nodes"], s["relations"], s["unresolved_connectors"],
                     s["texts"], s["unknowns"], s["blockers"], paths.plain_rel(out_dir, paths.work_root())))
            failed += result["validation"]["status"] == "blocked"
        for sk in skipped:
            print("%s p%d: 미추출 — %s" % (os.path.basename(path), sk["page_index"], sk["reason"]))
        failed += not done
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
