"""F1-6 검토(2026-11-12): 새 견본(검정 플러그 3개, 앵글형 psv 8개)이 143쪽에서 실제로 맞는 거리를 견본마다 센다.

    python f1-6-threshold-probe.py <저장소> <캐시 폴더> <출력.csv> [--jobs 4]

캐시는 f1-4-lone-ticks.py cache가 만든 <순번>.pickle이다. 사전의 max_distance와 관계없이 그 항목 견본 가운데 가장
가까운 거리를 적는다(문턱을 0.8로 넓혀 다시 대 본다). 열: 쪽, 기호 상자, 항목, 견본 번호, 거리, 지금 판정.
"""
import argparse
import csv
import glob
import multiprocessing
import os
import pickle
import sys

ENTRIES = ("apr1400.plug_valve", "apr1400.angle_relief_valve")
NEW = {"apr1400.plug_valve": (5, 6, 7), "apr1400.angle_relief_valve": tuple(range(8))}


def _page(job):
    repo, path = job
    sys.path.insert(0, repo)
    from hazop.extract import symbols
    from hazop.extract.adapters import pdf_vector as pv
    lib = pv.symbol_library()
    rows = []
    orig = pv._symbol_match

    def wrap(sym, blocks):
        hit = orig(sym, blocks)
        sig = symbols.sym_signature(sym)
        dt = None
        for eid in ENTRIES:
            e = lib.entries.get(eid)
            for i, t in enumerate(e.templates):
                if i not in NEW[eid] or getattr(t, "comp_key", None) != sig.comp_key or not t.variants:
                    continue
                if not (1 / t.size_ratio <= sig.size[1] / t.size <= t.size_ratio):
                    continue
                if dt is None:
                    dt = symbols.distance_table(sig.cells)
                d = min(symbols.chamfer(sig.cells, dt, cs, tdt) for _, cs, tdt in t.variants)
                if d <= 0.8:
                    rows.append((page["file"][:3], [round(v, 1) for v in sym.bbox], eid, i, round(d, 3),
                                 hit.outcome, hit.entry.id if hit.entry else ""))
        return hit

    with open(path, "rb") as fh:
        page = pickle.load(fh)
    pv._symbol_match = wrap
    try:
        analysis = pv.analyze(page["width"], page["height"], page["words"], page["prims"])
        pv.build_extraction(analysis, page["width"], page["height"], page["page_count"], 0, page["file"], page["sha"])
    finally:
        pv._symbol_match = orig
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("cache")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.cache, "[0-9]*.pickle")))
    with multiprocessing.Pool(a.jobs) as pool:
        pages = pool.map(_page, [(a.repo, f) for f in files], chunksize=1)
    rows = [r for p in pages for r in p]
    with open(a.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["page", "bbox", "entry", "template", "distance", "outcome", "matched_entry"])
        w.writerows(rows)
    for eid in ENTRIES:
        ds = sorted(r[4] for r in rows if r[2] == eid and r[6] == eid)
        print("%s 지금 맞음 %d, 거리 최대 %s" % (eid, len(ds), ds[-1] if ds else "-"))
        for cut in (0.1, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.8):
            print("  거리 <= %.2f: 맞음 %d, 다른 판정 %d" % (
                cut, sum(1 for r in rows if r[2] == eid and r[6] == eid and r[4] <= cut),
                sum(1 for r in rows if r[2] == eid and r[6] != eid and r[4] <= cut)))


if __name__ == "__main__":
    main()
