"""F1-5(밸브 라벨 고르기)의 측정 스크립트. 원시 요소 캐시(f1-4-lone-ticks.py cache)를 읽는다.

  python f1-5-valve-labels.py scan <cache 폴더> [--csv <목록.csv>] [--jobs 6]
      쪽마다 추출해 글자 문단을 가른다: 밸브 번호(V1681 꼴), 위치 약어(NO·NC·LO·LC·FO·FC·FL·FAI와 그 조합),
      그 밖. 밸브 번호 문단이 어느 노드의 라벨이 됐는지(밸브, 다른 기호, 아무 기호도 아님), 밸브 분류 노드의 라벨이
      무엇인지(밸브 번호, 위치 약어, 그 밖, 없음), 위치 약어 라벨인 밸브 옆 label_gap_max 안에 밸브 번호가 있는지 센다.

--repo로 코드 폴더를 바꿀 수 있다(기본: 이 스크립트가 든 저장소). 이 스크립트는 저장소 파일을 고치지 않는다.
"""

import argparse
import collections
import csv
import glob
import os
import pickle
import re
import sys
import multiprocessing

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
VALVE_NO = re.compile(r"V\d{3,5}[A-Z]?")
POSITION = re.compile(r"(NO|NC|LO|LC|FO|FC|FL|FAI)(\s*[,/]\s*(NO|NC|LO|LC|FO|FC|FL|FAI))*")


def block_kind(text):
    t = " ".join(text.split())
    if VALVE_NO.fullmatch(t):
        return "valve_no"
    if POSITION.fullmatch(t):
        return "position"
    return "other"


def _page(job):
    repo, path = job
    sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector as pv
    with open(path, "rb") as fh:
        pg = pickle.load(fh)
    seq = os.path.basename(path)[:3]
    a = pv.analyze(pg["width"], pg["height"], pg["words"], pg["prims"])
    ex = pv.build_extraction(a, pg["width"], pg["height"], pg["page_count"], 0, pg["file"], pg["sha"])
    prm = a["params"]
    blocks = a["blocks"]
    nodes = [n for n in ex["nodes"] if n.get("geometry") and "-sym-" in n["source_object_id"]]

    def box(n):
        g = n["geometry"]
        return (g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"])
    label_owner = {}
    for n in nodes:
        loc = n.get("label_location")
        if loc:
            x, y, w, h = loc["bbox"]
            label_owner[(round(x, 2), round(y, 2))] = n
    stat = collections.Counter()
    rows = []
    for b in blocks:
        k = block_kind(b["text"])
        if k != "valve_no":
            continue
        owner = label_owner.get((round(b["bbox"][0], 2), round(b["bbox"][1], 2)))
        where = "없음" if owner is None else ("밸브" if owner["category"] == "valve" else "기호(%s)" % (owner["kind"] or "종류 없음"))
        stat["밸브 번호 문단 → 라벨: " + where] += 1
    for n in nodes:
        if n["category"] != "valve":
            continue
        k = block_kind(n["label_text"]) if n["label_text"].strip() else "none"
        stat["밸브 노드 라벨: " + k] += 1
        if k == "valve_no" and n["tag"]:
            stat["밸브 번호 라벨인데 태그 있음"] += 1
        if k in ("position", "none", "other"):
            bx = box(n)
            near = [b for b in blocks if block_kind(b["text"]) == "valve_no"
                    and pv._box_gap(b["bbox"], bx) <= prm["label_gap_max"]]
            if near:
                stat["라벨이 %s인 밸브 옆 15pt 안에 밸브 번호 있음" % k] += 1
                rows.append({"seq": seq, "node": n["source_object_id"], "kind": n["kind"] or "",
                             "label": " ".join(n["label_text"].split()),
                             "near_numbers": " ".join(" ".join(b["text"].split()) for b in near),
                             "x": round(bx[0], 1), "y": round(bx[1], 1)})
    for b in blocks:
        stat["문단: " + block_kind(b["text"])] += 1
    return seq, stat, rows


def scan(args):
    files = sorted(glob.glob(os.path.join(args.cache, "[0-9]*.pickle")))
    with multiprocessing.Pool(args.jobs) as pool:
        res = pool.map(_page, [(args.repo, f) for f in files], chunksize=1)
    total = collections.Counter()
    rows = []
    for _, st, r in res:
        total.update(st)
        rows += r
    print("쪽 %d" % len(res))
    for k in sorted(total):
        print("  %-48s %d" % (k, total[k]))
    if args.csv and rows:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("목록 %d줄: %s" % (len(rows), args.csv))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("cache")
    p.add_argument("--csv")
    p.add_argument("--jobs", type=int, default=6)
    p.set_defaults(fn=scan)
    args = ap.parse_args()
    args.repo = os.path.abspath(args.repo)
    args.fn(args)


if __name__ == "__main__":
    main()
