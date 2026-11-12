"""F1-4(신호선 외톨이 빗금과 안전밸브 스프링선 가르기)의 측정 스크립트.

  python f1-4-lone-ticks.py cache --out <폴더> [--input-dir <쪽별 PDF 폴더>] [--jobs 6]
      143쪽의 원시 요소(pdf_vector.load_page 결과)를 <폴더>/<순번>.pickle로 떠 둔다. 뒤의 명령이 이것을 읽는다.
  python f1-4-lone-ticks.py scan <cache 폴더> [--csv <목록.csv>] [--host-min 2.5] [--jobs 6]
      선 하나에 묶음이 하나뿐인 빗금(외톨이)을 모두 찾아, 추출기가 그 빗금을 어떻게 처리하는지 센다:
      몸체 있는 기호에 흡수됨(그 기호의 종류), 빗금만으로 된 선 기호가 됨, 낱 선으로 남음.
      자기 고리 미확인이 어느 노드에서 나는지도 같이 센다. --host-min은 빗금이 걸린 선의 길이 하한을 바꿔 찾는다.
  python f1-4-lone-ticks.py run <cache 폴더> --out <폴더> [--variant <이름>] [--jobs 6]
      후보 규칙(VARIANTS)을 끼워 143쪽을 추출해 <폴더>/<순번>.json을 쓴다. --variant를 주지 않으면 코드 그대로다.
      쪽마다 외톨이 묶음 목록(f14_lone_groups: 후보를 끼우기 전의 선에서 찾은 것)을 같이 적는다.
  python f1-4-lone-ticks.py table <기준 폴더> <이름=폴더> ...
      후보별 추출 결과를 기준과 나란히 놓고 노드·관계 수, 미확인 사유별 수, 빗금으로 지워진 묶음 수,
      스프링 묶음이 든 기호의 종류를 표로 낸다.

--repo로 코드 폴더를 바꿀 수 있다(기본: 이 스크립트가 든 저장소). 이 스크립트는 저장소 파일을 고치지 않는다.
쪽별 PDF는 저장소에 없다(resources/references/APR1400_DCD/by-drawing).

scan과 후보(--variant)는 외톨이 규칙을 넣기 전 코드(81bc203)에 맞춰 썼다. 그 뒤 코드에서는 저장소의 _line_ticks가
외톨이 // 도 돌려주므로, 후보 비교를 다시 하려면 --repo에 81bc203을 꺼낸 분리 작업트리를 준다.
F1-4의 후보 비교 결과는 f1-4-candidates.txt, 외톨이 묶음 목록은 f1-4-lone-groups.csv에 있다.
"""

import argparse
import collections
import csv
import glob
import hashlib
import json
import math
import multiprocessing
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def _load(job):
    repo, path, dst = job
    sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector
    with open(path, "rb") as fh:
        data = fh.read()
    page_count, width, height, words, prims = pdf_vector.load_page(path, 0)
    with open(dst, "wb") as fh:
        pickle.dump({"file": os.path.basename(path), "sha": hashlib.sha256(data).hexdigest(),
                     "page_count": page_count, "width": width, "height": height, "words": words, "prims": prims}, fh)
    return os.path.basename(dst)


def cache(args):
    sys.path.insert(0, args.repo)
    from hazop import paths
    src = args.input_dir or paths.folder("APR1400", "by-drawing")
    files = sorted(glob.glob(os.path.join(src, "*.pdf")))
    if not files:
        sys.exit("쪽별 PDF가 없음: %s" % src)
    os.makedirs(args.out, exist_ok=True)
    jobs = [(args.repo, f, os.path.join(args.out, os.path.basename(f).split("_")[0] + ".pickle")) for f in files]
    with multiprocessing.Pool(args.jobs) as pool:
        done = pool.map(_load, jobs, chunksize=1)
    print("%d쪽 → %s" % (len(done), args.out))


def _cached(folder):
    files = sorted(glob.glob(os.path.join(folder, "[0-9]*.pickle")))
    if not files:
        sys.exit("cache 폴더가 비었음: %s" % folder)
    return files


def tick_groups(pv, polys, prm):
    """pdf_vector._line_ticks와 같은 조건으로 빗금 후보를 찾되, 선마다 묶음을 모두 돌려준다.
    → {선 id: [묶음]}, 묶음 = 빗금 조각(poly) 목록. 묶음 크기는 거르지 않는다(1개짜리·4개 이상도 나온다)."""
    def length(p):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pv._segs(p["pts"]))
    hosts = [p for p in polys if length(p) >= prm["tick_host_min"]]
    lo, hi = math.cos(math.radians(prm["tick_angle_max"])), math.cos(math.radians(prm["tick_angle_min"]))
    cand = collections.defaultdict(list)
    for p in polys:
        tl = length(p)
        if len(p["pts"]) != 2 or not 0.3 <= tl <= prm["tick_len_max"]:
            continue
        (x0, y0), (x1, y1) = p["pts"]
        mid, dx, dy = ((x0 + x1) / 2, (y0 + y1) / 2), x1 - x0, y1 - y0
        best = None
        for q in hosts:
            if q is p:
                continue
            for a, b in pv._segs(q["pts"]):
                d = pv._seg_dist(mid, a, b)[0]
                if d > prm["tick_host_dist"] or (best is not None and d >= best[0]):
                    continue
                ex, ey = b[0] - a[0], b[1] - a[1]
                el = math.hypot(ex, ey)
                if el <= 0:
                    continue
                cos = abs(dx * ex + dy * ey) / (math.hypot(dx, dy) * el)
                s0 = (ex * (y0 - a[1]) - ey * (x0 - a[0])) / el
                s1 = (ex * (y1 - a[1]) - ey * (x1 - a[0])) / el
                if lo <= cos <= hi and s0 * s1 < 0 and min(abs(s0), abs(s1)) >= 0.25 * tl:
                    best = (d, q["id"])
        if best is not None:
            cand[best[1]].append((mid, (dx, dy), p))
    out = {}
    for host, items in cand.items():
        def near(i, j):
            (m, d, _), (m2, d2, _) = items[i], items[j]
            return (math.hypot(m[0] - m2[0], m[1] - m2[1]) <= prm["tick_pair_gap"]
                    and abs(d[0] * d2[1] - d[1] * d2[0]) <= 0.2 * math.hypot(*d) * math.hypot(*d2))
        out[host] = [[items[i][2] for i in g] for g in pv._uf_groups(len(items), near)]
    return out


def lone_groups(pv, polys, prm, host_min=None):
    """외톨이 빗금 묶음: 2~3개짜리 묶음이 선에 하나뿐인 것. → [(선 id, 묶음)]. 지금 규칙은 이것을 빗금으로 보지 않는다.
    host_min을 주면 빗금이 걸린 선의 길이 하한(tick_host_min, 10pt)을 그 값으로 바꿔 찾는다."""
    out = []
    if host_min is not None:
        prm = dict(prm, tick_host_min=host_min)
    for host, groups in tick_groups(pv, polys, prm).items():
        sized = [g for g in groups if 2 <= len(g) <= 3]
        if len(sized) == 1 and prm["tick_pairs_min"] > 1:
            out.append((host, sized[0]))
    return out


def _check_copy(pv, polys, prm):
    """tick_groups가 저장소의 _line_ticks와 같은 빗금을 내는지(사본이 어긋나지 않았는지) 본다."""
    mine = set()
    for groups in tick_groups(pv, polys, prm).values():
        sized = [g for g in groups if 2 <= len(g) <= 3]
        if len(sized) >= prm["tick_pairs_min"]:
            mine.update(p["id"] for g in sized for p in g)
    return mine == pv._line_ticks(polys, prm)[0]


def _center(group):
    xs = [(p["pts"][0][0] + p["pts"][1][0]) / 2 for p in group]
    ys = [(p["pts"][0][1] + p["pts"][1][1]) / 2 for p in group]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _body_shape(pv, body, prm):
    if pv._is_circle(body, prm):
        return "원"
    if pv._is_triangle(body):
        return "삼각형"
    n = len(body["pts"]) - (1 if body["pts"][0] == body["pts"][-1] else 0)
    return "%d각형" % n if n <= 6 and not body.get("curved") else "그 밖"


def _scan_page(job):
    repo, path, host_min = job
    sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector as pv
    with open(path, "rb") as fh:
        page = pickle.load(fh)
    seq = os.path.basename(path)[:3]
    prm = dict(pv.PARAMS)
    cls = pv._classify_primitives(page["width"], page["height"], page["prims"], prm)
    pv._promote_black_symbols(cls, prm)
    polys = cls["polys"]
    same = _check_copy(pv, polys, prm)
    by_id = {p["id"]: p for p in polys}
    lone = lone_groups(pv, polys, prm, host_min)
    analysis = pv.analyze(page["width"], page["height"], page["words"], page["prims"])
    ex = pv.build_extraction(analysis, page["width"], page["height"], page["page_count"], 0, page["file"], page["sha"])
    node_of = {}
    for n in ex["nodes"]:
        for oid in n["evidence"]["pdf_objects"]:
            node_of[oid] = n
    lone_ids = {p["id"] for _, g in lone for p in g}
    bodies = cls["bodies"]
    rows = []
    for host, group in lone:
        h = by_id[host]
        hl = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pv._segs(h["pts"]))
        c = _center(group)
        to_end = min(math.hypot(c[0] - e[0], c[1] - e[1]) for e in (h["pts"][0], h["pts"][-1]))
        nodes = {id(node_of[p["id"]]): node_of[p["id"]] for p in group if p["id"] in node_of}
        if not nodes:
            fate, kind, basis, others = "loose", "", "", 0
        else:
            n = max(nodes.values(), key=lambda n: len(n["evidence"]["pdf_objects"]))
            kind, basis = n["kind"] or "", n["evidence"]["classification_basis"] or ""
            others = len([o for o in n["evidence"]["pdf_objects"] if o not in lone_ids])
            if n["evidence"]["stroke_only"]:
                fate = "stroke_symbol_ticks_only" if others == 0 else "stroke_symbol_mixed"
            else:
                fate = "in_body_symbol"
        box = group[0]["bbox"]
        for p in group[1:]:
            box = pv._union(box, p["bbox"])
        near = min(bodies, key=lambda b: pv._box_gap(box, b["bbox"]), default=None)
        rows.append({"seq": seq, "host": host, "host_len": round(hl, 1), "ticks": len(group),
                     "tick_len": round(max(math.hypot(p["pts"][1][0] - p["pts"][0][0],
                                                      p["pts"][1][1] - p["pts"][0][1]) for p in group), 1),
                     "x": round(c[0], 1), "y": round(c[1], 1), "to_host_end": round(to_end, 1),
                     "body_gap": round(pv._box_gap(box, near["bbox"]), 1) if near else 999.0,
                     "body_shape": _body_shape(pv, near, prm) if near else "",
                     "body_size": round(max(pv._w(near["bbox"]), pv._h(near["bbox"])), 1) if near else 0.0,
                     "fate": fate, "kind": kind, "basis": basis, "other_objects": others})
    loops = collections.Counter()
    by_local = {n["local_id"]: n for n in ex["nodes"]}
    rel = {r["local_id"]: r for r in ex["relations"] + ex["unresolved_connectors"]}  # 자기 고리는 미해결 쪽에 든다
    for u in ex["validation"]["unknowns"]:
        if u["check"] != "self_loop":
            continue
        r = rel.get(u["target"])
        n = by_local.get(r["endpoints"][0]["node_local_id"]) if r else None
        if n is None:
            loops[("?", "")] += 1
            continue
        objs = n["evidence"]["pdf_objects"]
        (x0, y0), (x1, y1) = (e["point"] for e in r["endpoints"])
        gap = math.hypot(x1 - x0, y1 - y0)
        span = "두 끝이 같은 점" if gap <= 0.5 else "두 끝 사이 %s" % ("5pt 이하" if gap <= 5 else "5pt 넘음")
        if objs and all(o in lone_ids for o in objs):
            where = "외톨이 빗금만으로 된 선 기호"
        elif any(o in lone_ids for o in objs):
            where = "외톨이 빗금이 섞인 기호(%s)" % (n["kind"] or "종류 없음")
        elif n["kind"] == "tee":
            where = "분기점"
        elif n["evidence"]["stroke_only"]:
            where = "선 기호(%s)" % (n["kind"] or "종류 없음")
        else:
            where = "몸체 있는 기호(%s)" % (n["kind"] or "종류 없음")
        loops[(where, span)] += 1
    unknowns = collections.Counter(u["check"] for u in ex["validation"]["unknowns"])
    return seq, same, rows, loops, unknowns


def scan(args):
    jobs = [(args.repo, f, args.host_min) for f in _cached(args.cache)]
    with multiprocessing.Pool(args.jobs) as pool:
        results = pool.map(_scan_page, jobs, chunksize=1)
    rows = [r for _, _, page_rows, _, _ in results for r in page_rows]
    bad = [seq for seq, same, _, _, _ in results if not same]
    print("쪽 %d · 빗금 사본이 저장소 _line_ticks와 다른 쪽 %d %s" % (len(results), len(bad), bad[:10]))
    print("외톨이 빗금 묶음 %d (쪽 %d곳)" % (len(rows), len({r["seq"] for r in rows})))
    fate = collections.Counter((r["ticks"], r["fate"], r["kind"] or "종류 없음") for r in rows)
    print("\n빗금 수 | 지금 추출기의 처리 | 노드 종류 | 묶음 수")
    for (t, f, k), n in sorted(fate.items(), key=lambda kv: (kv[0][0], -kv[1], kv[0])):
        print("  %d | %-26s | %-22s | %d" % (t, f, k, n))
    near = collections.Counter((r["ticks"], "10pt 이상" if r["host_len"] >= 10 else "10pt 미만",
                                r["body_shape"] if r["body_gap"] <= 3.0 else "3pt 안에 몸체 없음") for r in rows)
    print("\n빗금 수 | 걸린 선 길이 | 3pt 안의 가장 가까운 몸체 | 묶음 수")
    for (t, h, b), n in sorted(near.items()):
        print("  %d | %-8s | %-16s | %d" % (t, h, b, n))
    loops = collections.Counter()
    unknowns = collections.Counter()
    for _, _, _, lp, un in results:
        loops.update(lp)
        unknowns.update(un)
    print("\n자기 고리 미확인 %d — 고리가 걸린 노드" % sum(loops.values()))
    for (where, span), n in loops.most_common(30) if all(isinstance(k, tuple) for k in loops) else ():
        print("  %-34s | %-18s | %d" % (where, span, n))
    print("\n미확인 합계 %d: %s" % (sum(unknowns.values()), dict(unknowns.most_common())))
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("목록: %s" % args.csv)


def _length(pv, p):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pv._segs(p["pts"]))


def _group_box(pv, group):
    box = group[0]["bbox"]
    for p in group[1:]:
        box = pv._union(box, p["bbox"])
    return box


def _by_triangle(pv, group, bodies, gap=3.0):
    box = _group_box(pv, group)
    return any(pv._is_triangle(b) and pv._box_gap(box, b["bbox"]) <= gap for b in bodies)


def _longer_host(pv, host, group):
    return _length(pv, host) > max(_length(pv, p) for p in group)


# 외톨이 묶음 가운데 어느 것을 신호 표시 빗금으로 볼지 정하는 후보. host_min: 빗금이 걸린 선의 길이 하한(None = 저장소 값 10pt).
# take(pv, 선, 묶음, 몸체들): 참이면 빗금으로 본다. first: 기호 묶기 전에 선에서 뺀다(없으면 지금 빗금처럼 묶기 뒤에 뺀다).
VARIANTS = {
    "naive": {"about": "3f 재현: 외톨이 묶음(2~3개)을 모두 빗금으로, 선 10pt 이상",
              "host_min": None, "take": lambda pv, host, group, bodies: True},
    "pair10": {"about": "빗금이 정확히 2개인 외톨이 묶음만, 선 10pt 이상",
               "host_min": None, "take": lambda pv, host, group, bodies: len(group) == 2},
    "pair": {"about": "빗금이 정확히 2개이고 선이 빗금보다 긴 외톨이 묶음(선 길이 하한 없음)",
             "host_min": 2.5, "take": lambda pv, host, group, bodies: len(group) == 2 and _longer_host(pv, host, group)},
    "pair_first": {"about": "pair와 같되 기호 묶기 전에 뺀다",
                   "host_min": 2.5, "first": True,
                   "take": lambda pv, host, group, bodies: len(group) == 2 and _longer_host(pv, host, group)},
    "nobody": {"about": "삼각형 몸체 3pt 안에 있지 않은 외톨이 묶음(2~3개), 선이 빗금보다 김",
               "host_min": 2.5,
               "take": lambda pv, host, group, bodies: _longer_host(pv, host, group)
               and not _by_triangle(pv, group, bodies)},
    "nobody_first": {"about": "nobody와 같되 기호 묶기 전에 뺀다",
                     "host_min": 2.5, "first": True,
                     "take": lambda pv, host, group, bodies: _longer_host(pv, host, group)
                     and not _by_triangle(pv, group, bodies)},
}


def install(pv, variant):
    """후보 규칙을 pv._line_ticks에 끼운다. 저장소 규칙이 찾은 빗금은 그대로 두고 외톨이 묶음만 더한다."""
    spec = VARIANTS[variant]
    base_ticks, base_promote = pv._line_ticks, pv._promote_black_symbols
    state = {}

    def promote(cls, prm):
        base_promote(cls, prm)
        state["bodies"] = cls["bodies"]

    def line_ticks(polys, prm):
        ticks, marked = base_ticks(polys, prm)
        by_id = {p["id"]: p for p in polys}
        added = [(host, group) for host, group in lone_groups(pv, polys, prm, spec["host_min"])
                 if host not in marked and spec["take"](pv, by_id[host], group, state["bodies"])]
        for host, group in added:
            ticks.update(p["id"] for p in group)
            marked[host] = [_center(group)]
        if spec.get("first"):
            gone = {p["id"] for _, group in added for p in group}
            polys[:] = [p for p in polys if p["id"] not in gone]
        return ticks, marked

    pv._promote_black_symbols, pv._line_ticks = promote, line_ticks


def _run_page(job):
    repo, path, variant, dst = job
    sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector as pv
    with open(path, "rb") as fh:
        page = pickle.load(fh)
    prm = dict(pv.PARAMS)
    cls = pv._classify_primitives(page["width"], page["height"], page["prims"], prm)
    pv._promote_black_symbols(cls, prm)  # 표본 목록은 후보를 끼우기 전의 선으로 만든다
    groups = [{"host": host, "ticks": [p["id"] for p in group], "by_triangle": _by_triangle(pv, group, cls["bodies"]),
               "at": [round(c, 1) for c in _center(group)]} for host, group in lone_groups(pv, cls["polys"], prm, 2.5)]
    if variant and not getattr(pv, "_f14_installed", False):
        install(pv, variant)
        pv._f14_installed = True
    analysis = pv.analyze(page["width"], page["height"], page["words"], page["prims"])
    ex = pv.build_extraction(analysis, page["width"], page["height"], page["page_count"], 0, page["file"], page["sha"])
    ex["f14_lone_groups"] = groups
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(ex, fh, ensure_ascii=False)
    return os.path.basename(dst)


def run(args):
    os.makedirs(args.out, exist_ok=True)
    jobs = [(args.repo, f, args.variant, os.path.join(args.out, os.path.basename(f)[:3] + ".json"))
            for f in _cached(args.cache)]
    with multiprocessing.Pool(args.jobs) as pool:
        done = pool.map(_run_page, jobs, chunksize=1)
    print("%d쪽 → %s (후보: %s)" % (len(done), args.out, args.variant or "저장소 코드 그대로"))


def _pages(folder):
    out = {}
    for f in sorted(glob.glob(os.path.join(folder, "[0-9]*.json"))):
        with open(f, encoding="utf-8") as fh:
            out[os.path.basename(f)[:3]] = json.load(fh)
    return out


def _summary(pages):
    """한 추출 결과 묶음의 수: 노드·관계, 종류별 노드, 미확인 사유별, 스프링 묶음(빗금 3개, 삼각형 옆)과 신호 표시
    묶음(빗금 2개)이 어떻게 됐는지."""
    s = collections.Counter()
    spring_nodes = {}
    for seq, ex in pages.items():
        s["노드"] += len(ex["nodes"])
        s["관계"] += len(ex["relations"])
        s["미해결 연결"] += len(ex["unresolved_connectors"])
        for n in ex["nodes"]:
            if n["kind"] in ("psv", "pipe_cap", "tee"):
                s["종류 " + n["kind"]] += 1
            if n["kind"] is None:
                s["종류 없음"] += 1
        for r in ex["relations"]:
            if r["line_type"] == "pdf_pneumatic":
                s["공압 신호선 관계"] += 1
        for u in ex["validation"]["unknowns"]:
            s["미확인 " + u["check"]] += 1
            s["미확인 합계"] += 1
        node_of = {o: n for n in ex["nodes"] for o in n["evidence"]["pdf_objects"]}
        on_line = {o for r in ex["relations"] + ex["unresolved_connectors"] for o in r["evidence"]["pdf_objects"]}
        for g in ex["f14_lone_groups"]:
            spring = len(g["ticks"]) == 3 and g["by_triangle"]
            name = "스프링 묶음(3개, 삼각형 옆)" if spring else "빗금 %d개 묶음(그 밖)" % len(g["ticks"])
            s[name] += 1
            kept = [t for t in g["ticks"] if t in node_of or t in on_line]
            if len(kept) < len(g["ticks"]):
                s[name + " 가운데 빗금으로 지워짐"] += 1
            if spring:
                nodes = {id(node_of[t]): node_of[t] for t in g["ticks"] if t in node_of}
                n = max(nodes.values(), key=lambda n: len(n["evidence"]["pdf_objects"])) if nodes else None
                spring_nodes[(seq, g["host"])] = n["kind"] if n else "(기호 없음)"
    for kind, n in collections.Counter(spring_nodes.values()).items():
        s["스프링 묶음이 든 기호의 종류: %s" % kind] = n
    return s, spring_nodes


def table(args):
    names = ["기준"] + [spec.split("=", 1)[0] for spec in args.variants]
    folders = [args.base] + [spec.split("=", 1)[1] for spec in args.variants]
    results = [_summary(_pages(f)) for f in folders]
    keys = []
    for s, _ in results:
        keys += [k for k in s if k not in keys]
    print("| 항목 | " + " | ".join(names) + " |")
    print("| --- |" + " --- |" * len(names))
    for k in sorted(keys, key=lambda k: (not k.startswith(("노드", "관계", "미해결")), k)):
        base = results[0][0][k]
        cells = ["%d" % base] + ["%d (%+d)" % (s[k], s[k] - base) if s[k] != base else "%d" % s[k] for s, _ in results[1:]]
        print("| %s | %s |" % (k, " | ".join(cells)))
    base_nodes = results[0][1]
    for name, (_, nodes) in zip(names[1:], results[1:]):
        changed = sorted((seq, host, base_nodes[(seq, host)], kind) for (seq, host), kind in nodes.items()
                         if base_nodes.get((seq, host)) != kind)
        print("\n%s: 스프링 묶음이 든 기호의 종류가 기준과 달라진 것 %d" % (name, len(changed)))
        for seq, host, was, now in changed[:40]:
            print("  %s %s: %s → %s" % (seq, host, was, now))


def _box(n):
    g = n["geometry"]
    return (g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"])


def _components(ex):
    """물리 배관 관계(양 끝이 서로 다른 노드에 붙은 것)로 이은 연결요소 → {노드 local_id: 요소 번호}.
    f1-3-node-diff.py links와 같은 정의다."""
    parent = {n["local_id"]: n["local_id"] for n in ex["nodes"]}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in ex["relations"]:
        if r["kind"] == "physical_connection":
            a, b = (e["node_local_id"] for e in r["endpoints"])
            if a and b and a != b:
                parent[find(a)] = find(b)
    return {x: find(x) for x in parent}


def splits(args):
    """'전'의 물리 배관 관계 가운데, 두 끝 노드가 '후'에서 서로 다른 연결요소에 든 것(= 배관 이어짐을 끊은 자리)을 찾아
    그 선이 '후'에 무엇이 됐는지 적는다. 같은 선은 근거 선 조각(pdf_objects)이 겹치는 관계로 찾는다."""
    before, after = _pages(args.before), _pages(args.after)
    became = collections.Counter()
    for seq in sorted(before):
        b, a = before[seq], after[seq]
        comp_a = _components(a)
        after_at = collections.defaultdict(list)
        for n in a["nodes"]:
            if n.get("geometry"):
                after_at[tuple(round(v) for v in _box(n))].append(n)
        match = {}
        for n in b["nodes"]:
            if not n.get("geometry"):
                continue
            box = _box(n)
            near = [m for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    for m in after_at.get((round(box[0]) + dx, round(box[1]) + dy, round(box[2]) + dx, round(box[3]) + dy), ())
                    if max(abs(p - q) for p, q in zip(box, _box(m))) <= 0.5]
            if near:
                match[n["local_id"]] = near[0]["local_id"]
        by_object = collections.defaultdict(list)
        for r in a["relations"] + a["unresolved_connectors"]:
            for o in r["evidence"]["pdf_objects"]:
                by_object[o].append(r)
        ticks = {o["source_object_id"] for o in a["drawing"]["ignored_objects"] if o.get("reason") == "line_tick"}
        ticks -= {o["source_object_id"] for o in b["drawing"]["ignored_objects"] if o.get("reason") == "line_tick"}
        kind_b = {n["local_id"]: n["kind"] for n in b["nodes"]}
        for r in b["relations"]:
            if r["kind"] != "physical_connection":
                continue
            ends = [e["node_local_id"] for e in r["endpoints"]]
            if None in ends or ends[0] == ends[1]:
                continue
            if not all(e in match for e in ends):
                # 끝 노드가 '후'에 없다: // 가 선을 자르던 자리의 분기점이다. 선 자체가 '후'에 무엇인지만 본다
                gone = True
            else:
                gone = False
                if comp_a[match[ends[0]]] == comp_a[match[ends[1]]]:
                    continue
            now = {id(x): x for o in r["evidence"]["pdf_objects"] for x in by_object.get(o, ())}.values()
            if gone and all(x["kind"] == "physical_connection" for x in now) and now:
                continue
            what = sorted({"%s/%s" % (x["kind"], x["line_type"]) for x in now}) or ["(선 없음)"]
            near_tick = any(o in ticks for o in r["evidence"]["pdf_objects"])
            why = "끝 노드가 없어짐" if gone else "두 끝이 다른 연결요소"
            became[(", ".join(what), why)] += 1
            if args.verbose:
                print("  %s %s (%s–%s) %s %s → %s%s" % (seq, r["source_object_id"], kind_b[ends[0]], kind_b[ends[1]],
                                                     [round(c, 1) for c in r["endpoints"][0]["point"]], why,
                                                     ", ".join(what), " · 선 자체가 새 빗금" if near_tick else ""))
    print("'전'의 물리 배관 관계 가운데 '후'에 배관으로 이어지지 않는 것 %d" % sum(became.values()))
    for (what, why), n in became.most_common():
        print("  %-52s | %-18s | %d" % (what, why, n))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cache")
    p.add_argument("--out", required=True)
    p.add_argument("--input-dir")
    p.add_argument("--jobs", type=int, default=6)
    p.set_defaults(fn=cache)
    p = sub.add_parser("scan")
    p.add_argument("cache")
    p.add_argument("--csv")
    p.add_argument("--host-min", type=float, help="빗금이 걸린 선의 길이 하한을 바꿔 찾는다(기본: 저장소 값 10pt)")
    p.add_argument("--jobs", type=int, default=6)
    p.set_defaults(fn=scan)
    p = sub.add_parser("run")
    p.add_argument("cache")
    p.add_argument("--out", required=True)
    p.add_argument("--variant", choices=sorted(VARIANTS))
    p.add_argument("--jobs", type=int, default=6)
    p.set_defaults(fn=run)
    p = sub.add_parser("table")
    p.add_argument("base")
    p.add_argument("variants", nargs="*", help="이름=폴더")
    p.set_defaults(fn=table)
    p = sub.add_parser("splits")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=splits)
    args = ap.parse_args()
    args.repo = os.path.abspath(args.repo)
    args.fn(args)


if __name__ == "__main__":
    main()
