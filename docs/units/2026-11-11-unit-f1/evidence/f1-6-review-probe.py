"""F1-6 검토 지적(Codex)을 재현하는 스크립트. 원시 요소 캐시(f1-4-lone-ticks.py cache)를 읽는다.

  python f1-6-review-probe.py springs <cache 폴더> [--csv <목록.csv>]
      apr1400.angle_relief_valve(psv)에 맞은 기호마다 스프링선(4pt 이하 평행 사선 셋 이상)이 있는지 센다.
  python f1-6-review-probe.py plugs <cache 폴더>
      검게 칠한 마름모(플러그 밸브 닫힘 몸통) 꼴의 검은 채움을 모두 찾아, 추출 결과에서 NC 밸브가 됐는지, 표식으로
      남았는지 센다.

--repo로 코드 폴더를 바꿀 수 있다(기본: 이 스크립트가 든 저장소). 저장소 파일을 고치지 않는다.
"""

import argparse
import collections
import csv
import glob
import math
import multiprocessing
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))


def _load(repo, path):
    sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector as pv
    with open(path, "rb") as fh:
        pg = pickle.load(fh)
    a = pv.analyze(pg["width"], pg["height"], pg["words"], pg["prims"])
    ex = pv.build_extraction(a, pg["width"], pg["height"], pg["page_count"], 0, pg["file"], pg["sha"])
    return pv, a, ex


def spring_groups(strokes):
    """4pt 이하 직선 조각을 기울기(10도 안)로 묶어 가장 큰 묶음의 수."""
    short = []
    for s in strokes:
        if len(s["pts"]) != 2:
            continue
        (x0, y0), (x1, y1) = s["pts"]
        length = math.hypot(x1 - x0, y1 - y0)
        if 0.5 <= length <= 4.0:
            short.append(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180)
    best = 0
    for a in short:
        best = max(best, sum(1 for b in short if min(abs(a - b), 180 - abs(a - b)) <= 10))
    return best


def _springs(job):
    repo, path = job
    pv, a, ex = _load(repo, path)
    seq = os.path.basename(path)[:3]
    by_obj = {}
    for s in a["symbols"]:
        for o in s.evidence():
            by_obj[o] = s
    rows = []
    for n in ex["nodes"]:
        if n["evidence"].get("symbol_id") != "apr1400.angle_relief_valve":
            continue
        sym = by_obj.get(n["evidence"]["pdf_objects"][0])
        g = n["geometry"]
        rows.append({"seq": seq, "node": n["source_object_id"], "x": round(g["x"] + g["width"] / 2, 1),
                     "y": round(g["y"] + g["height"] / 2, 1), "spring": spring_groups(sym.strokes) if sym else -1})
    return rows


def springs(args):
    files = sorted(glob.glob(os.path.join(args.cache, "[0-9]*.pickle")))
    with multiprocessing.Pool(args.jobs) as pool:
        rows = [r for rs in pool.map(_springs, [(args.repo, f) for f in files], chunksize=1) for r in rs]
    c = collections.Counter("스프링선 %s" % ("3개 이상" if r["spring"] >= 3 else "%d개" % r["spring"]) for r in rows)
    print("apr1400.angle_relief_valve에 맞은 기호 %d: %s" % (len(rows), dict(c)))
    for r in rows:
        if r["spring"] < 3:
            print("  스프링선 없음:", r)
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


def is_diamond(m):
    pts = m["pts"][:-1] if m["pts"][0] == m["pts"][-1] else m["pts"]
    if len(pts) != 4 or m.get("curved"):
        return False
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if not (2.0 <= max(w, h) <= 12.0 and min(w, h) >= 0.3 * max(w, h)):
        return False
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    # 마름모: 꼭짓점 넷이 상자의 네 변 가운데에 있다(사각형은 네 모서리에 있다)
    return all(min(abs(p[0] - cx), abs(p[1] - cy)) <= 0.15 * max(w, h) for p in pts)


def _plugs(job):
    repo, path = job
    pv, a, ex = _load(repo, path)
    seq = os.path.basename(path)[:3]
    cls = a["classified"]
    fills = [m for m in cls["markers"] if is_diamond(m)] + [b for b in cls["bodies"] if b.get("solid") and is_diamond(b)]
    out = collections.Counter()
    for f in fills:
        c = pv._center(f["bbox"])
        hit = [n for n in ex["nodes"] if n.get("geometry") and pv._inside(c, (
            n["geometry"]["x"], n["geometry"]["y"], n["geometry"]["x"] + n["geometry"]["width"],
            n["geometry"]["y"] + n["geometry"]["height"]))]
        size = "긴 변 %s" % ("7pt 넘음" if max(pv._w(f["bbox"]), pv._h(f["bbox"])) > 7.0 else "7pt 이하")
        if any((n["attributes"] or {}).get("normal_position") == "NC" and n["category"] == "valve" for n in hit):
            out[(size, "NC 밸브")] += 1
        elif hit:
            out[(size, "다른 노드(%s)" % (hit[0]["kind"] or "종류 없음"))] += 1
        else:
            out[(size, "노드 없음(표식으로 남음)")] += 1
    return out


def plugs(args):
    files = sorted(glob.glob(os.path.join(args.cache, "[0-9]*.pickle")))
    with multiprocessing.Pool(args.jobs) as pool:
        total = collections.Counter()
        for c in pool.map(_plugs, [(args.repo, f) for f in files], chunksize=1):
            total.update(c)
    print("검게 칠한 마름모 %d" % sum(total.values()))
    for k, v in sorted(total.items()):
        print("  %s | %s | %d" % (k[0], k[1], v))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--jobs", type=int, default=4)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("springs")
    p.add_argument("cache")
    p.add_argument("--csv")
    p.set_defaults(fn=springs)
    p = sub.add_parser("plugs")
    p.add_argument("cache")
    p.set_defaults(fn=plugs)
    args = ap.parse_args()
    args.repo = os.path.abspath(args.repo)
    args.fn(args)


if __name__ == "__main__":
    main()
