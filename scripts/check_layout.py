"""정리된 보기 정돈 검사(docs/design/app-shell-web.md §10.11). 가상 도면 SNP 6장과 APR1400 표본(tests/fixtures/apr1400/pdf)을 새로 읽어
정돈하고, 쪽마다 layout_lint 값과 정돈 전후 기호 겹침 수, 정돈을 버린 덩이 수를 보고한다.

  python scripts/check_layout.py            # 보고하고 판정(종료 코드 0 = 통과)
  python scripts/check_layout.py --json     # 쪽마다 한 줄 JSON

판정: SNP는 모든 항목이 0. 어느 쪽이든 topology_changed는 0이고, 정돈 뒤 기호 겹침이 정돈 전보다 늘지 않는다.
APR1400 표본은 그 밖의 항목이 0이 아니어도 된다(PDF 읽기가 남긴 어긋남은 정돈을 버리고 읽은 좌표로 그린다).
"""

import argparse
import copy
import glob
import json
import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

SNP = ("SNP-M-101", "SNP-M-102", "SNP-M-201", "SNP-M-301", "SNP-M-401", "SNP-M-501")
COUNTS = ("topology_changed", "moved_too_far", "off_axis", "inline_off_center", "size_mismatch", "port_miss", "symbol_overlap",
          "pipe_through_symbol", "pipe_overlap", "crossing_without_hop", "visual_off_axis")


def snp_extractions(work):
    from check_edit_screen import install_sample
    from hazop.app import data
    return {d: data.load_extraction(install_sample(work, d))[1] for d in SNP}


def apr_extractions():
    from hazop.extract.adapters import pdf_vector
    out = {}
    for f in sorted(glob.glob(os.path.join(REPO_ROOT, "tests", "fixtures", "apr1400", "pdf", "*.pdf"))):
        out[os.path.basename(f)[:40]] = pdf_vector.extract(f, page=0, repo_root=REPO_ROOT)
    return out


def check_page(name, extraction, symbols):
    from hazop.shell import clean_items, clean_layout, sheet_items
    items = sheet_items.build_items(extraction)["items"]
    extras = clean_items.build(extraction)["items"]
    t0 = time.perf_counter()
    t = clean_layout.tidy(items, extras, symbols)
    took = time.perf_counter() - t0
    untouched = {"symbols": {i["id"]: i["bbox"] for i in items if i["layer"] == "symbol" and i["id"] in t["symbols"]},
                 "pipes": {pid: {"polyline": [i["polyline"] for i in items if i["id"] == pid][0], "ends": p["ends"]} for pid, p in t["pipes"].items()},
                 "hops": t["hops"], "moved": 0, "reverted": 0}
    before = clean_layout.layout_lint(items, extras, symbols, copy.deepcopy(untouched))
    return {"page": name, "lint": {k: t["lint"][k] for k in COUNTS}, "moved": t["lint"]["moved"], "reverted": t["reverted"],
            "symbol_overlap_before": before["symbol_overlap"], "symbols": len(t["symbols"]), "pipes": len(t["pipes"]), "tidy_s": round(took, 3)}


def judge(row, snp):
    bad = []
    if row["lint"]["topology_changed"]:
        bad.append("topology_changed %d" % row["lint"]["topology_changed"])
    if row["lint"]["symbol_overlap"] > row["symbol_overlap_before"]:
        bad.append("겹침 %d → %d" % (row["symbol_overlap_before"], row["lint"]["symbol_overlap"]))
    if snp:
        bad += ["%s %d" % (k, v) for k, v in row["lint"].items() if v]
        if row["reverted"]:
            bad.append("정돈을 버린 덩이 %d" % row["reverted"])
    return bad


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from hazop.shell import clean_items
    symbols = clean_items._symbols()
    tmp = tempfile.mkdtemp(prefix="hazop-layout-")
    old = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    os.makedirs(os.environ["HAZOP_WORK_ROOT"])
    failed = 0
    try:
        pages = [(n, e, True) for n, e in snp_extractions(os.environ["HAZOP_WORK_ROOT"]).items()] + [(n, e, False) for n, e in apr_extractions().items()]
        reverted_pdf = 0
        for name, ex, snp in pages:
            row = check_page(name, ex, symbols)
            bad = judge(row, snp)
            failed += bool(bad)
            if not snp and row["reverted"]:
                reverted_pdf += 1
            if args.json:
                print(json.dumps(dict(row, failures=bad), ensure_ascii=False))
            else:
                nz = {k: v for k, v in row["lint"].items() if v}
                print("%-40s %s  겹침 %d→%d  버린 덩이 %d  최대 이동 %.1f  %.2fs  %s" % (
                    name, "통과" if not bad else "실패", row["symbol_overlap_before"], row["lint"]["symbol_overlap"], row["reverted"], row["moved"],
                    row["tidy_s"], json.dumps(nz, ensure_ascii=False) if nz else "모두 0"))
                for b in bad:
                    print("    - " + b)
        if not args.json:
            print("PDF 쪽 가운데 정돈을 일부라도 버린 쪽: %d / %d" % (reverted_pdf, sum(1 for p in pages if not p[2])))
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
