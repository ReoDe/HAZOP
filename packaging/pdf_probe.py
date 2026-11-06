"""패키징 W9: 묶인 실행(HAZOP-check.exe)에서 PDF 어댑터(pdfplumber·pdfminer.six·pypdfium2·Pillow)가 동작하는지 본다.

사용: HAZOP-check.exe <사본>/pdf_probe.py --pdf <샘플 PDF 사본> --result <결과 JSON>
- 묶음 안 hazop.extract.adapters.pdf_vector로 PDF 한 쪽을 추출하고(pdfplumber·pdfminer.six), pypdfium2(pdfium.dll)로
  같은 쪽을 그려 Pillow 이미지 크기를 얻는다.
- 읽힌 모듈 파일(PROBE_MODULES)과, pypdfium2_raw가 실제로 읽은 pdfium.dll의 경로(읽은 모듈 핸들에서
  GetModuleFileNameW)를 기록한다. 판정(묶음 안인지,
  개발 실행의 추출 결과와 같은지)은 packaging/verify_bundle.py가 한다.
- 결과 JSON을 쓰고 종료 코드 0. 예외가 나면 결과 JSON에 오류를 남기고 종료 코드 1. 네트워크·AI 호출 없음.
"""

import argparse
import json
import os
import sys
import traceback

PROBE_MODULES = ("pdfplumber", "pdfminer", "pypdfium2", "pypdfium2_raw", "PIL", "cryptography", "charset_normalizer")


def digest(result):
    """추출 결과에서 비교할 부분: 실행 ID(파일 해시·규칙 판 포함), 요약, 항목 수."""
    return {"extraction_run_id": result["extraction_run_id"], "summary": result["summary"],
            "counts": {k: len(result[k]) for k in ("nodes", "relations", "texts", "unclassified",
                                                   "unresolved_connectors", "source_locations")}}


def probe(pdf):
    from hazop.extract.adapters import pdf_vector
    import pypdfium2
    import pypdfium2_raw

    out = {"frozen": bool(getattr(sys, "frozen", False)), "meipass": getattr(sys, "_MEIPASS", None)}
    out["extraction"] = digest(pdf_vector.extract(pdf))
    doc = pypdfium2.PdfDocument(pdf)
    try:
        out["render_size"] = list(doc[0].render(scale=0.25).to_pil().size)
    finally:
        doc.close()
    out["module_files"] = {m: getattr(sys.modules.get(m), "__file__", None) for m in PROBE_MODULES}
    out["pdfium_dll"] = loaded_pdfium_path(pypdfium2_raw)
    out["pdfium_dll_exists"] = bool(out["pdfium_dll"]) and os.path.isfile(out["pdfium_dll"])
    return out


def loaded_pdfium_path(raw):
    """pypdfium2_raw가 실제로 읽은 pdfium 모듈의 경로(Windows GetModuleFileNameW, 읽은 핸들 기준). 모르면 None."""
    import ctypes
    try:
        handle = raw.bindings._libs["pdfium"]._handle  # pypdfium2_raw 내부 이름(5.8.0)
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetModuleFileNameW(ctypes.c_void_p(handle), buf, 32768)
    except (AttributeError, KeyError, OSError):
        return None
    return buf.value if 0 < n < 32768 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--result", required=True)
    args = ap.parse_args(argv)
    try:
        out, rc = probe(os.path.abspath(args.pdf)), 0
    except Exception as e:  # 결과 JSON에 남기고 실패로 끝낸다
        out, rc = {"error": "%s: %s" % (type(e).__name__, e), "traceback": traceback.format_exc()}, 1
    with open(args.result, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("pdf_probe rc=%d" % rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
