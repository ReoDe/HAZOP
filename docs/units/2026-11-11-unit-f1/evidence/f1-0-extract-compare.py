"""F1-0(`pdf_vector.py` 나누기) 전후 추출 결과를 바이트로 견주는 스크립트.

  python f1-0-extract-compare.py snp --out <폴더>          # SNP 샘플 6장(drawio·pdf) 추출 JSON·그래프 JSON을 쓰고 해시 목록을 남김
  python f1-0-extract-compare.py apr1400 --out <폴더>      # APR1400 143쪽의 쪽별 추출·그래프 해시 목록을 남김
  python f1-0-extract-compare.py compare <전 폴더> <후 폴더> [--csv 전.csv 후.csv]

해시 목록은 <폴더>/snp-hashes.json, <폴더>/apr1400-hashes.json 이다. compare는 두 폴더에 있는 해시 목록과 SNP JSON
파일을 바이트로 견주고, --csv를 주면 check_apr1400.py --out 의 쪽별 CSV도 seconds 열을 빼고 견준다.
다르면 종료 코드 1.

추출 JSON은 json.dumps(ensure_ascii=False, indent=1)로 쓴다. 키를 정렬하지 않으므로 dict에 넣은 순서가 달라져도 잡힌다.
작업 루트는 <폴더>/work(HAZOP_WORK_ROOT)이고 끝나면 지운다. 전후에 같은 --out 이름 규칙(…/before, …/after)을 쓰면
source.file의 상대 경로도 같다.
"""

import argparse
import csv
import glob
import hashlib
import json
import multiprocessing
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

SNP_HASHES = "snp-hashes.json"
APR_HASHES = "apr1400-hashes.json"


def dumps(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


def with_work_root(out):
    work = os.path.join(out, "work")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    os.environ["HAZOP_WORK_ROOT"] = work
    return work


def run_snp(out):
    os.makedirs(out, exist_ok=True)
    work = with_work_root(out)
    import extract_drawio
    from hazop import paths
    from hazop.extract.adapters import pdf_vector
    from hazop.graph import build
    samples = paths.folder("references", "pid-samples")
    folders = sorted(d for d in glob.glob(os.path.join(samples, "*")) if os.path.isdir(d))
    hashes = {}
    try:
        for folder in folders:
            name = os.path.basename(folder)
            for fmt, pattern in (("drawio", "*.drawio"), ("pdf", "*.pdf")):
                files = sorted(glob.glob(os.path.join(folder, pattern)))
                if not files:
                    continue
                if fmt == "drawio":
                    ex, _ = extract_drawio.run_one(files[0], os.path.join(work, "extract"))
                else:
                    ex = pdf_vector.extract(files[0], page=0, repo_root=work)
                graph = build.build_graph(ex)
                ex_bytes, graph_bytes = dumps(ex), dumps(graph)
                stem = "%s.%s" % (name, fmt)
                with open(os.path.join(out, stem + ".extraction.json"), "wb") as fh:
                    fh.write(ex_bytes)
                with open(os.path.join(out, stem + ".graph.json"), "wb") as fh:
                    fh.write(graph_bytes)
                hashes[stem] = {"extraction_sha256": sha(ex_bytes), "graph_sha256": sha(graph_bytes),
                                "graph_version": graph["graph_version"], "nodes": len(ex["nodes"]),
                                "relations": len(ex["relations"])}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    write_json(os.path.join(out, SNP_HASHES), hashes)
    print("SNP %d건 → %s" % (len(hashes), os.path.join(out, SNP_HASHES)))
    return 0


def _apr_page(job):
    path, dwg, work = job
    os.environ["HAZOP_WORK_ROOT"] = work
    from hazop.extract.adapters import pdf_vector
    from hazop.graph import build
    try:
        ex = pdf_vector.extract(path, page=0, repo_root=work)
        ex_sha = sha(dumps(ex))
        ex["drawing"]["drawing_number"] = dwg  # check_apr1400._work와 같은 조건으로 그래프를 만든다
        ex["project_id"] = "APR1400"
        graph = build.build_graph(ex)
        return {"extraction_sha256": ex_sha, "graph_sha256": sha(dumps(graph)), "graph_version": graph["graph_version"],
                "nodes": len(ex["nodes"]), "relations": len(ex["relations"]),
                "unknowns": len(ex["validation"]["unknowns"])}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def run_apr1400(out, jobs):
    os.makedirs(out, exist_ok=True)
    work = with_work_root(out)
    from hazop import paths
    input_dir = paths.folder("APR1400", "by-drawing")
    with open(os.path.join(os.path.dirname(input_dir), "drawing-list.csv"), encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    todo = [(os.path.join(input_dir, r["개별파일"]), "%s-S%s" % (r["그림번호"], r["시트"]), work) for r in rows]
    try:
        pool = multiprocessing.Pool(jobs)
        try:
            done = pool.map(_apr_page, todo, chunksize=1)
        finally:
            pool.close()
            pool.join()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    hashes = {"%03d %s" % (int(r["순번"]), r["개별파일"]): d for r, d in zip(rows, done)}
    write_json(os.path.join(out, APR_HASHES), hashes)
    failed = sum(1 for d in done if "error" in d)
    print("APR1400 %d쪽(실패 %d) → %s" % (len(hashes), failed, os.path.join(out, APR_HASHES)))
    return 0


def _csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return [{k: v for k, v in row.items() if k != "seconds"} for row in csv.DictReader(fh)]


def compare(before, after, csvs):
    diffs = []
    checked = []
    for name in (SNP_HASHES, APR_HASHES):
        a, b = os.path.join(before, name), os.path.join(after, name)
        if not (os.path.isfile(a) and os.path.isfile(b)):
            checked.append("%s: 한쪽에 없어 건너뜀" % name)
            continue
        with open(a, encoding="utf-8") as fh:
            ja = json.load(fh)
        with open(b, encoding="utf-8") as fh:
            jb = json.load(fh)
        bad = sorted(k for k in set(ja) | set(jb) if ja.get(k) != jb.get(k))
        diffs += ["%s: %s" % (name, k) for k in bad]
        checked.append("%s: %d건 중 다른 것 %d" % (name, len(set(ja) | set(jb)), len(bad)))
    files = sorted({os.path.basename(p) for d in (before, after) for p in glob.glob(os.path.join(d, "*.json"))
                    if os.path.basename(p) not in (SNP_HASHES, APR_HASHES)})
    same = 0
    for name in files:
        a, b = os.path.join(before, name), os.path.join(after, name)
        if not (os.path.isfile(a) and os.path.isfile(b)):
            diffs.append("파일이 한쪽에만 있음: %s" % name)
            continue
        with open(a, "rb") as fa, open(b, "rb") as fb:
            if fa.read() == fb.read():
                same += 1
            else:
                diffs.append("바이트가 다름: %s" % name)
    checked.append("SNP JSON 파일: %d개 중 바이트 같음 %d" % (len(files), same))
    if csvs:
        ra, rb = _csv_rows(csvs[0]), _csv_rows(csvs[1])
        bad = [str(x.get("seq") or y.get("seq")) for x, y in zip(ra, rb) if x != y]
        if len(ra) != len(rb):
            diffs.append("쪽별 CSV 행 수가 다름: %d / %d" % (len(ra), len(rb)))
        diffs += ["쪽별 CSV seq %s" % s for s in bad]
        checked.append("쪽별 CSV(seconds 열 제외): %d행 중 다른 행 %d" % (len(ra), len(bad)))
    for line in checked:
        print(line)
    for line in diffs:
        print("다름: %s" % line)
    print("결과: %s" % ("다름 %d건" % len(diffs) if diffs else "전후가 같음"))
    return 1 if diffs else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snp")
    p.add_argument("--out", required=True)
    p = sub.add_parser("apr1400")
    p.add_argument("--out", required=True)
    p.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2)))
    p = sub.add_parser("compare")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--csv", nargs=2, metavar=("BEFORE_CSV", "AFTER_CSV"))
    args = ap.parse_args(argv)
    if args.cmd == "snp":
        return run_snp(os.path.abspath(args.out))
    if args.cmd == "apr1400":
        return run_apr1400(os.path.abspath(args.out), args.jobs)
    return compare(args.before, args.after, args.csv)


if __name__ == "__main__":
    sys.exit(main())
