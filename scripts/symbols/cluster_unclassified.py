"""벡터 PDF 도면의 미분류 기호를 모양별로 묶어 사람이 이름 붙일 후보 목록과 그림판을 만든다(기획서/PID-기호사전.md §6 2번).

  python scripts/symbols/cluster_unclassified.py --set APR1400 [--input-dir <도면 폴더>] [--pages 5-143] [--parity odd]
         [--library <사전 폴더> | --no-library] [--jobs 8] [--top 60] [--out <폴더>] [--black-fills] [--dist 0.8]

1. 쪽마다 지금 추출기(pdf_vector)로 기호를 묶고, 기호마다 kind·상자·상자 안 글자·모양 서명을 `<out>/쪽/<순번>.jsonl`에 남긴다.
   PDF와 추출기·서명 코드가 같으면 다시 계산하지 않는다(다시 돌려도 같은 끝 상태).
2. kind 없는 기호를 사전(기본: resources/library/symbols)에 대 보고, 맞음·애매함·후보 없음을 센다.
3. 사전에 맞지 않은 미분류를 구성 키가 같고 크기 비 1.25 안이며 8방향 챔퍼 거리 --dist 칸 이하인 것끼리 묶는다.
   대표에 붙이는 탐욕 묶음이라 입력 순서(쪽, 기호 번호)에 대해 결정적이다.
결과: <out>/요약.json, 묶음.csv, 묶음.json, 그림판.html(+ 그림/c###.png). 기본 <out>은 작업 루트의 symbol-candidates/<묶음>/.

--black-fills: 기호 대신 검은 채움 도형(화살촉 같은 표식과 검은 몸체)을 맞닿은 것끼리 묶어 같은 방식으로 센다.
검게 칠한 닫힌 밸브의 견본을 모으는 데 쓴다(§4.2 1번). 묶음과 서명은 추출기가 검은 채움을 기호 몸체로 올릴지 정할 때 쓰는
것과 같은 함수(pdf_vector._black_fills, _black_fill_groups, _black_fill_signature)로 만든다. 채움은 속이 차 있어 서로
다른 기호도 격자가 비슷하다. --dist를 0.1 안팎으로 좁혀 묶는다. 기본 <out>은 symbol-candidates/<묶음>-black-fills/.
"""

import argparse
import collections
import csv
import glob
import hashlib
import html
import json
import multiprocessing
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import symbols  # noqa: E402

SIZE_TOL = 1.25


def code_fingerprint():
    from hazop.extract.adapters import pdf_vector
    h = hashlib.sha256()
    for mod in (pdf_vector, symbols):
        with open(mod.__file__, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:12]


def parse_pages(spec):
    out = set()
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        out.update(range(int(lo), int(hi or lo) + 1))
    return out


def black_fill_rows(data):
    """한 쪽의 검은 채움 묶음 → 행 목록. 사전에 대 보기 전의 후보 전부다."""
    import io
    from hazop.extract.adapters import pdf_vector as pv
    _, width, height, _, prims = pv.load_page(io.BytesIO(data), 0)
    fills = pv._black_fills(pv._classify_primitives(width, height, prims, pv.PARAMS))
    rows = []
    for i, g in enumerate(pv._black_fill_groups(fills, pv.PARAMS)):
        sig = pv._black_fill_signature(g)
        rows.append({"i": i, "kind": None, "label": "", "inside": [], "bbox": [round(v, 2) for v in g["bbox"]],
                     "key": sig.comp_key, "size": list(sig.size), "zero": sig.zero, "grid": symbols.grid_text(sig.cells)})
    return rows


def write_rows(dst, head, rows):
    tmp = dst + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(head, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, dst)
    return dst


def scan_page(job):
    """한 쪽 → 기호 행 목록(black이면 작은 검은 채움 묶음 행 목록). 캐시가 맞으면 읽기만 한다."""
    path, dst, fp, black = job
    import pdfplumber
    from hazop.extract.adapters import pdf_vector as pv
    with open(path, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    head = {"file": os.path.basename(path), "sha256": sha, "code": fp}
    if black:
        head["rows"] = "black_fills"
    if os.path.isfile(dst):
        with open(dst, encoding="utf-8") as f:
            if json.loads(f.readline()) == head:
                return dst
    if black:
        return write_rows(dst, head, black_fill_rows(data))
    _, page_count, width, height, analysis = pv.analyze_bytes(data, 0)
    ex = pv.build_extraction(analysis, width, height, page_count, 0, os.path.basename(path), sha)
    syms = analysis["symbols"]
    with pdfplumber.open(path) as pdf:
        fine = symbols.page_fine_points(pdf.pages[0])
    blocks = analysis["blocks"]
    rows = []
    for i, (node, s) in enumerate(zip(ex["nodes"], syms)):
        x0, y0, x1, y1 = s.bbox
        inside = [b["text"] for b in blocks
                  if x0 <= (b["bbox"][0] + b["bbox"][2]) / 2 <= x1 and y0 <= (b["bbox"][1] + b["bbox"][3]) / 2 <= y1]
        sig = symbols.sym_signature(s, fine)
        rows.append({"i": i, "kind": node["kind"], "label": node["label_text"], "inside": inside,
                     "bbox": [round(v, 2) for v in s.bbox], "key": sig.comp_key, "size": list(sig.size),
                     "zero": sig.zero, "grid": symbols.grid_text(sig.cells)})
    return write_rows(dst, head, rows)


def load_rows(page_dir):
    for fn in sorted(glob.glob(os.path.join(page_dir, "*.jsonl"))):
        seq = os.path.basename(fn)[:-6]
        with open(fn, encoding="utf-8") as f:
            head = json.loads(f.readline())
            for line in f:
                r = json.loads(line)
                r["seq"], r["file"] = seq, head["file"]
                yield r


def as_signature(r):
    return symbols.Signature(r["key"], tuple(r["size"]), symbols.cells_of(r["grid"]), r["zero"])


def cluster(rows, dist_max):
    """→ [{key, leader, members}] (입력 순서에 대해 결정적)."""
    leaders = collections.defaultdict(list)
    clusters, exact = [], {}
    for r in rows:
        h = (r["key"], tuple(r["grid"]), round(r["size"][1]))
        if h in exact:
            clusters[exact[h]]["members"].append(r)
            continue
        cells = symbols.cells_of(r["grid"])
        dt = symbols.distance_table(cells)
        best = None
        for ci, size, variants in leaders[r["key"]]:
            if not (1 / SIZE_TOL <= r["size"][1] / max(size, 1e-6) <= SIZE_TOL):
                continue
            d = min(symbols.chamfer(cells, dt, vc, vdt) for vc, vdt in variants)
            if d <= dist_max and (best is None or d < best[0]):
                best = (d, ci)
        if best is None:
            ci = len(clusters)
            clusters.append({"key": r["key"], "leader": r, "members": [r]})
            variants = []
            for _, f in symbols.TRANSFORMS:
                vc = frozenset(f(a, b) for a, b in cells)
                variants.append((vc, symbols.distance_table(vc)))
            leaders[r["key"]].append((ci, r["size"][1], variants))
        else:
            ci = best[1]
            clusters[ci]["members"].append(r)
        exact[h] = ci
    clusters.sort(key=lambda c: (-len(c["members"]), c["leader"]["seq"], c["leader"]["i"]))
    return clusters


def strip(members, input_dir, dst, n=8, res=220, pad=11.0):
    """묶음 예시 n개(쪽이 다른 것부터)를 가로로 붙인 그림. 빨간 테 = 추출기가 묶은 기호 상자."""
    import pdfplumber
    from PIL import Image, ImageDraw
    picks, seen = [], set()
    for m in members:
        if m["seq"] not in seen:
            picks.append(m)
            seen.add(m["seq"])
    picks += [m for m in members if m not in picks]
    ims = []
    for m in picks[:n]:
        with pdfplumber.open(os.path.join(input_dir, m["file"])) as pdf:
            pg = pdf.pages[0]
            x0, y0, x1, y1 = m["bbox"]
            cx, cy, half = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2 + pad
            box = (max(0, cx - half), max(0, cy - half), min(pg.width, cx + half), min(pg.height, cy + half))
            if box[0] >= box[2] or box[1] >= box[3]:
                continue  # 쪽 밖에 그린 도형은 예시 그림을 만들 수 없다
            im = pg.crop(box).to_image(resolution=res).original.convert("RGB")
        s = res / 72.0
        ImageDraw.Draw(im).rectangle([(x0 - box[0]) * s - 1, (y0 - box[1]) * s - 1, (x1 - box[0]) * s + 1,
                                      (y1 - box[1]) * s + 1], outline=(230, 0, 0))
        ims.append(im.resize((120, 120)))
    out = Image.new("RGB", (124 * max(1, len(ims)), 124), "white")
    for k, im in enumerate(ims):
        out.paste(im, (2 + 124 * k, 2))
    out.save(dst, optimize=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", default="APR1400")
    ap.add_argument("--input-dir")
    ap.add_argument("--pages", help="순번 범위(예: 5-143 또는 6,9,12). 기본 전체")
    ap.add_argument("--parity", choices=("all", "odd", "even"), default="all")
    ap.add_argument("--library", help="사전 폴더(기본: %s)" % paths.folder_rel("symbols"))
    ap.add_argument("--no-library", action="store_true", help="사전에 대 보지 않고 미분류 전부를 묶음")
    ap.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--top", type=int, default=60, help="그림을 만들 상위 묶음 수")
    ap.add_argument("--dist", type=float, default=0.8)
    ap.add_argument("--black-fills", action="store_true",
                    help="기호 대신 작은 검은 채움 묶음을 센다(검게 칠한 닫힌 밸브 견본 모으기)")
    ap.add_argument("--out")
    a = ap.parse_args()
    input_dir = a.input_dir or paths.folder("APR1400", "by-drawing")
    out = a.out or paths.folder("symbol-candidates", a.set + ("-black-fills" if a.black_fills else ""))
    page_dir = os.path.join(out, "쪽")
    os.makedirs(page_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
    want = parse_pages(a.pages) if a.pages else None
    jobs = []
    for f in files:
        seq = os.path.basename(f).split("_")[0]
        n = int(seq) if seq.isdigit() else None
        if want is not None and n not in want:
            continue
        if n is not None and a.parity != "all" and (n % 2 == 1) != (a.parity == "odd"):
            continue
        jobs.append((f, os.path.join(page_dir, seq + ".jsonl"), code_fingerprint(), a.black_fills))
    if not jobs:
        sys.exit("대상 PDF가 없음: %s" % input_dir)
    with multiprocessing.Pool(a.jobs) as pool:
        done = set(os.path.basename(p) for p in pool.map(scan_page, jobs, chunksize=1))
    rows = [r for r in load_rows(page_dir) if r["seq"] + ".jsonl" in done]
    unclassified = [r for r in rows if r["kind"] is None]

    lib = None if a.no_library else symbols.Library.load(a.library)
    outcome, per_entry, rest = collections.Counter(), collections.Counter(), []
    for r in unclassified:
        if lib is None:
            rest.append(r)
            continue
        m = lib.match(as_signature(r), r["inside"])
        outcome[m.outcome] += 1
        if m.outcome == "matched":
            per_entry[m.entry.id] += 1
        else:
            rest.append(r)

    clusters = cluster(rest, a.dist)
    img_dir = os.path.join(out, "그림")
    os.makedirs(img_dir, exist_ok=True)
    for k, c in enumerate(clusters[:a.top], 1):
        strip(c["members"], input_dir, os.path.join(img_dir, "c%03d.png" % k))
    with open(os.path.join(out, "묶음.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["순위", "기호 수", "쪽 수", "구성 키", "대표 크기(pt)", "대표(쪽#기호)", "상자 안 글자(많은 순)"])
        for k, c in enumerate(clusters, 1):
            texts = collections.Counter(" ".join(m["inside"]).replace("\n", " ") for m in c["members"] if m["inside"])
            w.writerow([k, len(c["members"]), len({m["seq"] for m in c["members"]}), c["key"],
                        "x".join("%.1f" % v for v in c["leader"]["size"]), "%s#%d" % (c["leader"]["seq"], c["leader"]["i"]),
                        "; ".join("%s(%d)" % t for t in texts.most_common(3))])
    with open(os.path.join(out, "묶음.json"), "w", encoding="utf-8") as f:
        json.dump([{"rank": k, "count": len(c["members"]), "key": c["key"],
                    "members": [[m["seq"], m["i"]] for m in c["members"]]} for k, c in enumerate(clusters, 1)],
                  f, ensure_ascii=False)
    cover, cum = {}, 0
    for k, c in enumerate(clusters, 1):
        cum += len(c["members"])
        if k in (10, 50, 200):
            cover[str(k)] = round(cum / max(1, len(rest)), 3)
    summary = {"set": a.set, "input_dir": input_dir, "pages": len(done), "parity": a.parity, "symbols": len(rows),
               "unclassified": len(unclassified), "library": None if lib is None else lib.versions,
               "library_outcome": dict(outcome), "library_per_entry": dict(per_entry.most_common()),
               "remaining": len(rest), "clusters": len(clusters), "top_cover": cover,
               "rows": "black_fills" if a.black_fills else "symbols", "dist": a.dist}
    with open(os.path.join(out, "요약.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    rows_html = "\n".join(
        "<tr><td>%d</td><td>%d</td><td>%s</td><td><img src=\"그림/c%03d.png\" alt=\"묶음 %d\"></td></tr>"
        % (k, len(c["members"]), html.escape(c["key"]), k, k) for k, c in enumerate(clusters[:a.top], 1))
    with open(os.path.join(out, "그림판.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=\"utf-8\"><title>미분류 묶음 %s</title>"
                "<style>body{font-family:sans-serif}td{padding:4px;border-bottom:1px solid #ddd}</style>"
                "<h1>미분류 묶음: %s</h1><p>%s</p><table><tr><th>순위</th><th>기호 수</th><th>구성 키</th>"
                "<th>예시(빨간 테 = 기호 상자)</th></tr>%s</table>"
                % (html.escape(a.set), html.escape(a.set), html.escape(json.dumps(summary, ensure_ascii=False)), rows_html))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
