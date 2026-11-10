"""래스터(PNG·JPG) P&ID -> 출력/어댑터/raster/<도면번호>/extraction.json + validation_report.md (T3 W4)

사용 예:
  python scripts/extract_raster.py "참고자료/P&ID 도면 샘플/SNP-M-102_RCS-pressurizer/01_SNP-M-102.png"
  python scripts/extract_raster.py --samples       # 샘플 6개 PNG 전체(.drawio.png 제외, 결정 D1 블라인드)
  python scripts/extract_raster.py --no-ocr 그림.png  # 글자 인식 없이(미확인 ocr_unavailable 기록)
OpenCV(opencv-python-headless)가 필요하다(결정 D7, packaging/requirements-raster.txt의 별도 venv). 없으면 종료 코드 2.
빈 파일·손상 파일·상한(파일 100 MB, 50 MP)을 넘는 입력은 형식 오류로 알리고 종료 코드 2(blocker로 기록하지 않음).
글자 인식(rapidocr-onnxruntime)이 없으면 글자 없이 추출하고 미확인으로 남긴다.
출력은 drawio 추출 결과(출력/추출/)와 섞이지 않도록 기본값을 출력/어댑터/raster/ 로 둔다.
평가(drawio 정답 대비 지표)는 scripts/check_adapter.py가 한다.
"""

import argparse
import glob
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402
from hazop.extract import report  # noqa: E402
from hazop.extract.adapters import raster  # noqa: E402

SAMPLE_GLOB = paths.folder("참고", "P&ID 도면 샘플", "*", "*.png")
DEFAULT_OUT = paths.output_root("어댑터", "raster")


def sample_images():
    """샘플 PNG 목록. `.drawio.png`는 다이어그램 XML을 품고 있어 블라인드 시험에서 뺀다(결정 D1)."""
    return [p for p in sorted(glob.glob(SAMPLE_GLOB)) if not p.lower().endswith(".drawio.png")]


def run_one(path, out_root, use_ocr=True):
    result = raster.extract(path, repo_root=paths.work_root(), use_ocr=use_ocr)
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
    ap.add_argument("image", nargs="*", help="PNG·JPG 경로")
    ap.add_argument("--samples", action="store_true", help="참고자료 샘플 PNG 전체(.drawio.png 제외)")
    ap.add_argument("--no-ocr", action="store_true", help="글자 인식을 쓰지 않는다")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    jobs = list(args.image) + (sample_images() if args.samples else [])
    if not jobs:
        ap.error("PNG·JPG 파일 또는 --samples 필요")
    has_cv, has_ocr = raster.available()
    if not has_cv:
        print("OpenCV(cv2)·numpy가 없어 실행할 수 없음(결정 D7). packaging/requirements-raster.txt를 설치한 Python으로 "
              "실행할 것.")
        return 2
    if not has_ocr and not args.no_ocr:
        print("글자 인식(rapidocr-onnxruntime) 없음: 글자 없이 추출하고 미확인 ocr_unavailable을 남긴다.")
    blocked = bad_input = 0
    for path in jobs:
        try:
            result, out_dir = run_one(path, args.out_root, use_ocr=not args.no_ocr)
        except (OSError, raster.RasterInputError) as exc:  # 빈·손상·너무 큰 입력: 추출 결과가 아니라 형식 오류
            print("입력 형식 오류: %s: %s" % (os.path.basename(path), exc))
            bad_input += 1
            continue
        s = result["summary"]
        print("%s: %s nodes=%d relations=%d unresolved=%d texts=%d unknowns=%d blockers=%d -> %s"
              % (result["drawing"]["drawing_number"] or os.path.basename(out_dir), result["validation"]["status"],
                 s["nodes"], s["relations"], s["unresolved_connectors"], s["texts"], s["unknowns"], s["blockers"],
                 paths.rel_or_abs(out_dir, paths.work_root())))
        blocked += result["validation"]["status"] == "blocked"
    return 2 if bad_input else (1 if blocked else 0)


if __name__ == "__main__":
    sys.exit(main())
