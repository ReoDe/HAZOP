"""F1-4 검토 지적 수정의 근거를 세는 스크립트(저장소 코드 그대로, f1-4-lone-ticks.py cache로 뜬 원시 요소를 읽는다).

  python f1-4-review-probe.py guards <cache 폴더> <81bc203 추출 폴더> <고친 뒤 추출 폴더>
      (1) 한 묶음 안 두 빗금이 옆으로 떨어진 거리, (2) 신호 표시로 읽은 외톨이 // 와 선이 닿은 작은 각진 몸체 사이 간격,
      (3) 외톨이 // 꼴인데 판정하지 않은 것, (4) 묶음이 여럿인 선에도 '선 끝점 밖' 조건을 넣으면 빠지는 빗금,
      (5) 나란한 두 빗금이 서로 다른 두 선에 하나씩 딸려 표시가 빠진 것, (6) 새로 공압 신호선이 된 선의 양 끝 종류.
  python f1-4-review-probe.py diff <전 추출 폴더> <후 추출 폴더>
      달라진 쪽마다 빗금과 공압 신호선이 어떻게 달라졌는지 적는다.

추출 폴더는 f1-4-lone-ticks.py run으로 만든 것(쪽마다 f14_lone_groups가 든 JSON)이다. 저장소 파일을 고치지 않는다.
"""

import collections
import glob
import importlib.util
import json
import math
import multiprocessing
import os
import pickle
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, REPO)


def _legacy():
    spec = importlib.util.spec_from_file_location(
        "f14", os.path.join(REPO, "docs/units/2026-11-11-unit-f1/evidence/f1-4-lone-ticks.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _side_gap(a, b):
    (m, d, _), (m2, _, _) = a, b
    return abs((m2[0] - m[0]) * d[1] - (m2[1] - m[1]) * d[0]) / math.hypot(*d)


def page(path):
    from hazop.extract.adapters import pdf_vector as pv
    f14 = _legacy()
    with open(path, "rb") as fh:
        pg = pickle.load(fh)
    seq = os.path.basename(path)[:3]
    prm = dict(pv.PARAMS)
    cls = pv._classify_primitives(pg["width"], pg["height"], pg["prims"], prm)
    pv._promote_black_symbols(cls, prm)
    polys, bodies = cls["polys"], cls["bodies"]
    ticks, marked = pv._line_ticks(polys, prm, bodies)
    out = {"seq": seq, "side": [], "body_gap": [], "blocked": [], "split": [], "strict": []}
    hosts = [p for p in polys if pv._poly_length(p) >= prm["tick_host_min"]]
    first = set()
    for host, groups in pv._tick_groups(polys, hosts, prm).items():
        if len(groups) >= prm["tick_pairs_min"]:
            for g in groups:
                first.update(p["id"] for _, _, p in g)
                out["side"] += [("묶음 여럿", round(_side_gap(g[i], g[i + 1]), 2)) for i in range(len(g) - 1)]
    # 묶음이 여럿인 선에도 '선 끝점 밖' 조건을 넣으면 빠지는 빗금
    kept = set()
    for host, groups in pv._tick_groups(polys, hosts, prm, within_ends=True).items():
        if len(groups) >= prm["tick_pairs_min"]:
            kept.update(p["id"] for g in groups for _, _, p in g)
    by_all = {p["id"]: p for p in polys}
    for t in sorted(first - kept):
        b = by_all[t]["bbox"]
        out["strict"].append((seq, t, round((b[0] + b[2]) / 2, 1), round((b[1] + b[3]) / 2, 1)))
    rest = [p for p in polys if p["id"] not in first]
    by_id = {p["id"]: p for p in rest}
    for host, groups in pv._tick_groups(rest, rest, prm, within_ends=True).items():
        if host in first or len(groups) != 1 or len(groups[0]) != pv.LONE_TICK_STROKES:
            continue
        line, pair = by_id[host], [p for _, _, p in groups[0]]
        if any(pv._poly_length(p) >= pv._poly_length(line) for p in pair):
            continue
        c = pv._group_center(groups[0])
        crowded, on_body = pv._crowded(line, pair, rest, prm), pv._on_small_body(line, pair, bodies, prm)
        if crowded or on_body:
            out["blocked"].append((seq, host, round(c[0], 1), round(c[1], 1), "crowded" if crowded else "small_body"))
            continue
        out["side"].append(("외톨이", round(_side_gap(groups[0][0], groups[0][1]), 2)))
        box = pv._union(pair[0]["bbox"], pair[1]["bbox"])
        gaps = [pv._box_gap(box, b["bbox"]) for b in bodies
                if not b.get("curved") and max(pv._w(b["bbox"]), pv._h(b["bbox"])) <= prm["pipe_cap_max"]
                and pv._poly_box_dist(line["pts"], b["bbox"]) <= prm["attach_tol"]]
        out["body_gap"].append((seq, round(c[0], 1), round(c[1], 1), round(min(gaps), 2) if gaps else None))
    # 바: 한 묶음의 두 빗금이 끝을 맞댄 서로 다른 두 선에 하나씩 딸려 표시가 빠진 것(옛 후보 조건으로 낱 빗금을 찾는다)
    singles = []
    for host, groups in f14.tick_groups(pv, rest, dict(prm, tick_host_min=0.0)).items():
        for g in groups:
            if len(g) == 1 and g[0]["id"] not in ticks and host not in marked:
                singles.append((host, g[0]))
    for i, (h1, p1) in enumerate(singles):
        for h2, p2 in singles[i + 1:]:
            if h1 == h2:
                continue
            m1 = ((p1["pts"][0][0] + p1["pts"][1][0]) / 2, (p1["pts"][0][1] + p1["pts"][1][1]) / 2)
            m2 = ((p2["pts"][0][0] + p2["pts"][1][0]) / 2, (p2["pts"][0][1] + p2["pts"][1][1]) / 2)
            d1 = (p1["pts"][1][0] - p1["pts"][0][0], p1["pts"][1][1] - p1["pts"][0][1])
            d2 = (p2["pts"][1][0] - p2["pts"][0][0], p2["pts"][1][1] - p2["pts"][0][1])
            if math.hypot(m1[0] - m2[0], m1[1] - m2[1]) > prm["tick_pair_gap"]:
                continue
            if abs(d1[0] * d2[1] - d1[1] * d2[0]) > 0.2 * math.hypot(*d1) * math.hypot(*d2):
                continue
            if _side_gap((m1, d1, None), (m2, d2, None)) < pv.TICK_SIDE_GAP_MIN:
                continue
            e1 = (by_id[h1]["pts"][0], by_id[h1]["pts"][-1])
            e2 = (by_id[h2]["pts"][0], by_id[h2]["pts"][-1])
            joined = any(math.hypot(a[0] - b[0], a[1] - b[1]) <= prm["end_tol"] for a in e1 for b in e2)
            out["split"].append((seq, h1, h2, round((m1[0] + m2[0]) / 2, 1), round((m1[1] + m2[1]) / 2, 1),
                                 "끝을 맞댄 두 선" if joined else "떨어진 두 선"))
    return out


def end_kind(ex, e):
    if not e["node_local_id"]:
        return "닿지 않음"
    n = ex["_by"][e["node_local_id"]]
    if n["kind"] == "tee":
        return "분기점"
    if n["category"] == "instrument":
        return "계기"
    if n["category"] == "valve":
        return "밸브(구동부 포함)"
    return "종류 없는 기호" if n["kind"] is None else n["kind"]


def guards(cache, base_dir, fix_dir):
    files = sorted(glob.glob(os.path.join(cache, "[0-9]*.pickle")))
    with multiprocessing.Pool(6) as pool:
        results = pool.map(page, files, chunksize=1)
    side = collections.defaultdict(list)
    for r in results:
        for kind, v in r["side"]:
            side[kind].append(v)
    print("1. 한 묶음 안 이웃한 두 빗금이 옆으로 떨어진 거리(pt). 하한 TICK_SIDE_GAP_MIN = 0.2")
    for kind, vals in sorted(side.items()):
        vals.sort()
        print("  %s: %d쌍 · 최소 %.2f · 5%% %.2f · 가운데 %.2f · 최대 %.2f" % (
            kind, len(vals), vals[0], vals[len(vals) // 20], vals[len(vals) // 2], vals[-1]))
    gaps = [g for r in results for g in r["body_gap"]]
    near = sorted((g for g in gaps if g[3] is not None), key=lambda g: g[3])
    print("\n2. 신호 표시로 읽은 외톨이 // %d묶음과, 그 선이 닿은 작은 각진 몸체 사이 간격(pt). 문턱 SPRING_BODY_GAP = 0.5" % len(gaps))
    print("  선이 그런 몸체에 닿지 않음 %d · 닿음 %d(간격 최소 %s)" % (
        len(gaps) - len(near), len(near), near[0][3] if near else "-"))
    for g in near[:6]:
        print("    %s쪽 (%.1f,%.1f) 간격 %.2f" % g)
    blocked = [b for r in results for b in r["blocked"]]
    print("\n3. 외톨이 // 꼴인데 판정하지 않은 것 %d" % len(blocked))
    for b in blocked:
        print("    %s쪽 선 %s (%.1f,%.1f) %s" % b)
    strict = [s for r in results for s in r["strict"]]
    print("\n4. 묶음이 여럿인 선에도 '선 끝점 밖' 조건을 넣으면 빗금에서 빠지는 조각 %d" % len(strict))
    for s in strict:
        print("    %s쪽 %s (%.1f,%.1f)" % s)
    split = [s for r in results for s in r["split"]]
    print("\n5. (바) 나란한 두 빗금이 서로 다른 두 선에 하나씩 딸려 표시가 빠진 것 %d" % len(split))
    for s in split:
        print("    %s쪽 선 %s·%s (%.1f,%.1f) %s" % s)
    table = collections.Counter()
    lines = 0
    for f in sorted(glob.glob(os.path.join(fix_dir, "[0-9]*.json"))):
        a = json.load(open(f, encoding="utf-8"))
        b = json.load(open(os.path.join(base_dir, os.path.basename(f)), encoding="utf-8"))
        a["_by"] = {n["local_id"]: n for n in a["nodes"]}
        was = {o for r in b["relations"] + b["unresolved_connectors"] if r["line_type"] == "pdf_pneumatic"
               for o in r["evidence"]["pdf_objects"]}
        for r in a["relations"] + a["unresolved_connectors"]:
            if r["line_type"] != "pdf_pneumatic" or set(r["evidence"]["pdf_objects"]) & was:
                continue
            lines += 1
            table[tuple(sorted(end_kind(a, e) for e in r["endpoints"]))] += 1
    print("\n6. (마) 81bc203에서는 공압 신호선이 아니었다가 공압 신호선이 된 선 %d개의 양 끝" % lines)
    for (x, y), n in sorted(table.items(), key=lambda kv: (-kv[1], kv[0])):
        print("    %-18s — %-18s %d" % (x, y, n))
    both_plain = sum(n for (x, y), n in table.items()
                     if all(k not in ("계기", "밸브(구동부 포함)", "종류 없는 기호", "닿지 않음") for k in (x, y)))
    print("  두 끝이 모두 분기점이거나 종류가 정해진 기기인 선: %d" % both_plain)


def _ticks(ex):
    return {o["source_object_id"]: o["bbox"] for o in ex["drawing"]["ignored_objects"] if o.get("reason") == "line_tick"}


def _lines(ex):
    out = {}
    for r in ex["relations"] + ex["unresolved_connectors"]:
        out[tuple(r["evidence"]["pdf_objects"])] = (r["kind"], r["line_type"],
                                                    tuple(tuple(round(c, 1) for c in e["point"]) for e in r["endpoints"]))
    return out


def diff(before_dir, after_dir):
    total = {"빗금에서 빠짐": 0, "빗금이 됨": 0}
    for f in sorted(glob.glob(os.path.join(before_dir, "[0-9]*.json"))):
        seq = os.path.basename(f)[:3]
        raw_b = open(f, encoding="utf-8").read()
        raw_a = open(os.path.join(after_dir, seq + ".json"), encoding="utf-8").read()
        if raw_b == raw_a:
            continue
        b, a = json.loads(raw_b), json.loads(raw_a)
        tb, ta = _ticks(b), _ticks(a)
        lone = {t: g for g in b["f14_lone_groups"] for t in g["ticks"]}
        print("== %s쪽: 노드 %d → %d · 관계 %d → %d · 미해결 %d → %d · 미확인 %d → %d" % (
            seq, len(b["nodes"]), len(a["nodes"]), len(b["relations"]), len(a["relations"]),
            len(b["unresolved_connectors"]), len(a["unresolved_connectors"]),
            len(b["validation"]["unknowns"]), len(a["validation"]["unknowns"])))
        for t in sorted(set(tb) - set(ta)):
            total["빗금에서 빠짐"] += 1
            g = lone.get(t)
            print("  빗금에서 빠짐 %s (%.1f,%.1f) %s" % (t, tb[t][0] + tb[t][2] / 2, tb[t][1] + tb[t][3] / 2,
                                                   "외톨이 묶음(%d개) 선 %s" % (len(g["ticks"]), g["host"]) if g else "묶음 여럿인 선의 빗금"))
        for t in sorted(set(ta) - set(tb)):
            total["빗금이 됨"] += 1
            print("  빗금이 됨 %s (%.1f,%.1f)" % (t, ta[t][0] + ta[t][2] / 2, ta[t][1] + ta[t][3] / 2))
        lb, la = _lines(b), _lines(a)
        pb = {k: v for k, v in lb.items() if v[1] == "pdf_pneumatic"}
        pa = {k: v for k, v in la.items() if v[1] == "pdf_pneumatic"}
        for k in sorted(set(pb) - set(pa)):
            now = [v for kk, v in la.items() if set(kk) & set(k)]
            print("  공압 신호선이 아니게 됨 %s %s → %s" % (list(k), pb[k][2], [(v[0], v[1]) for v in now]))
        for k in sorted(set(pa) - set(pb)):
            print("  공압 신호선이 됨 %s %s" % (list(k), pa[k][2]))
        kb = {n["source_object_id"]: (n["kind"], n["tag"]) for n in b["nodes"] if "-sym-" in n["source_object_id"]}
        ka = {n["source_object_id"]: (n["kind"], n["tag"]) for n in a["nodes"] if "-sym-" in n["source_object_id"]}
        if kb != ka:
            print("  기호 노드가 달라짐: 전 %d개, 후 %d개, 다른 항목 %d" % (len(kb), len(ka), len(set(kb.items()) ^ set(ka.items()))))
    print(total)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "guards":
        guards(*sys.argv[2:5])
    elif len(sys.argv) == 4 and sys.argv[1] == "diff":
        diff(*sys.argv[2:4])
    else:
        sys.exit(__doc__)
