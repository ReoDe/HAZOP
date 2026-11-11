"""벡터 PDF 도면 묶음의 미확인을 사유(check)·사유 문구 유형·대상 종류별로 나눈다(docs/2026-11-10-apr1400-unknowns).

  python -X utf8 scripts/unknowns_breakdown.py --out <폴더> [--input-dir <도면 폴더>] [--jobs 8]
결과: <out>/rows.jsonl(쪽마다 미확인 목록), <out>/표.md(사유별 수·대표 쪽), <out>/요약.json
check_apr1400.py와 같은 경로(pdf_vector.extract)로 추출한다. 같은 코드면 같은 결과.
"""

import argparse
import collections
import glob
import json
import multiprocessing
import os
import re
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def target_kind(ex):
    by_sid = {}
    for n in ex["nodes"]:
        by_sid[n["source_object_id"]] = ("node", n.get("kind") or "(kind 없음)", n["evidence"].get("symbol_id"))
    for key in ("relations", "unresolved_connectors"):
        for r in ex.get(key, []):
            by_sid[r["source_object_id"]] = (key, r.get("kind") or "(kind 없음)", None)
    return by_sid


def reason_pattern(reason):
    """사유 문구에서 숫자·태그·인용을 지워 유형으로 묶는다."""
    s = re.sub(r"'[^']*'|\"[^\"]*\"|\([^)]*\)", "…", reason or "")
    s = re.sub(r"[A-Z0-9][A-Z0-9_\-]{2,}", "#", s)
    return re.sub(r"\d+", "#", s)[:70]


def one(job):
    repo, path = job
    sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector
    seq = os.path.basename(path)[:3]
    work = tempfile.mkdtemp(prefix="unk-")
    try:
        ex = pdf_vector.extract(path, page=0, repo_root=work)
    except Exception as e:  # 이미지 쪽 등
        return seq, None, str(e)
    finally:
        shutil.rmtree(work, ignore_errors=True)  # 쪽마다 빈 폴더가 남아 2,000개 넘게 쌓였다(2026-11-10)
    kinds = target_kind(ex)
    rows = []
    for u in ex["validation"]["unknowns"]:
        t = kinds.get(u.get("source_object_id"), ("(대상 없음)", "-", None))
        rows.append({"seq": seq, "check": u["check"], "pattern": reason_pattern(u.get("reason")), "field": u.get("field"),
                     "target": t[0], "target_kind": t[1], "symbol_id": t[2], "sid": u.get("source_object_id")})
    return seq, {"nodes": len(ex["nodes"]), "relations": len(ex.get("relations", [])), "unknowns": len(rows)}, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", help="도면 PDF 폴더(기본: 폴더 표 APR1400의 by-drawing)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.input_dir is None:
        sys.path.insert(0, REPO_ROOT)
        from hazop import paths
        a.input_dir = paths.folder("APR1400", "by-drawing")
    files = sorted(glob.glob(os.path.join(a.input_dir, "*.pdf")))
    with multiprocessing.Pool(a.jobs) as pool:
        res = pool.map(one, [(REPO_ROOT, f) for f in files], chunksize=1)
    by_check, by_pat, by_target, examples, pages = (collections.Counter(), collections.Counter(), collections.Counter(),
                                                    collections.defaultdict(collections.Counter), {})
    with open(os.path.join(a.out, "rows.jsonl"), "w", encoding="utf-8") as f:
        for seq, meta, rows in res:
            pages[seq] = meta if meta else {"error": rows}
            if not meta:
                continue
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                by_check[r["check"]] += 1
                by_pat[(r["check"], r["pattern"])] += 1
                by_target[(r["check"], r["target"], r["target_kind"], r["symbol_id"] or "")] += 1
                examples[r["check"]][r["seq"]] += 1
    total = sum(by_check.values())
    lines = ["# APR1400 미확인 분해", "", "쪽 %d, 미확인 %d" % (len(pages), total), "",
             "## 사유별", "", "| 사유(check) | 수 | 비율 | 많은 쪽(수) |", "| --- | --- | --- | --- |"]
    for c, n in by_check.most_common():
        top = ", ".join("%s(%d)" % x for x in examples[c].most_common(3))
        lines.append("| `%s` | %d | %.1f%% | %s |" % (c, n, 100 * n / total, top))
    lines += ["", "## 사유 × 대상 종류 (상위 40)", "", "| 사유 | 대상 | 대상 kind | 사전 항목 | 수 |", "| --- | --- | --- | --- | --- |"]
    for (c, t, k, s), n in by_target.most_common(40):
        lines.append("| `%s` | %s | %s | %s | %d |" % (c, t, k, s, n))
    lines += ["", "## 사유 문구 유형 (상위 30)", "", "| 사유 | 문구 | 수 |", "| --- | --- | --- |"]
    for (c, p), n in by_pat.most_common(30):
        lines.append("| `%s` | %s | %d |" % (c, p.replace("|", "/"), n))
    with open(os.path.join(a.out, "표.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(a.out, "요약.json"), "w", encoding="utf-8") as f:
        json.dump({"pages": pages, "by_check": dict(by_check.most_common()), "total": total}, f, ensure_ascii=False, indent=1)
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main()
