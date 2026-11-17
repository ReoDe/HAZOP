"""벡터 PDF 흐름 방향(pdf_vector에서 나눔). 규격: docs/specs/extraction.md '읽기 품질 지표' 연결 (나).

1. 화살촉: 기호에 묶이지 않고 남은 채운 삼각형(leftover markers)의 뾰족한 쪽(가장 짧은 변 맞은편 꼭짓점)이 가리키는
   방향을, 그 삼각형이 얹힌 사슬 선분의 방향과 견준다. 사슬 위 화살촉이 모두 같은 쪽이면 그 방향, 엇갈리면 정하지 않는다.
2. 흐름 보존: 방향을 아는 배관에서 시작해, 2포트 배관 기호(밸브·배관 부속)는 들어온 만큼 나가고, 분기점(티)에서
   아는 배관이 모두 들어오는(또는 모두 나가는) 쪽이고 모르는 배관이 하나뿐이면 그 하나는 반대쪽이다. 설비(탱크·펌프
   등)는 입출구가 여럿일 수 있어 지나가지 않는다. 배관 둘이 맞은편에서 꿰고 지나가는 미분류 노드(_inline_unclassified)는
   2포트처럼 지나간다. 바뀌지 않을 때까지 되풀이한다.
3. 방향 기호: 흐름 보존 전에, 방향을 그림으로 그린 기호(덕트 끝 공기 흐름 화살표, 체크 밸브 경첩 점)에 닿은 배관에 그
   방향을 매긴다.
쪽 번호·좌표로 가르는 예외는 두지 않는다.
"""

import math

from .pdf_vector_common import _inside, _seg_dist, _segs

# 흐름이 그대로 지나가는 2포트 기호(관계가 꼭 2개일 때만). 펌프·압축기·팬·필터·탈염기는 흡입 하나 토출 하나라 넣고,
# 탱크·용기·열교환기(두 유체)는 입출구가 여럿이거나 흐름이 둘이라 넣지 않는다
PASS_KINDS = {"manual_valve", "motor_operated_valve", "control_valve", "check_valve", "isolation_valve",
              "air_operated_valve", "solenoid_valve", "orifice", "reducer", "strainer", "flow_element",
              "pump", "compressor", "fan", "filter", "demineralizer"}
ALIGN_MIN = 0.85   # 화살촉 축과 선분 방향의 |cos| 하한
NEAR_FACTOR = 0.9  # 화살촉 가운데가 선분에서 떨어져도 되는 거리(화살촉 긴 변 대비)


def arrow_axis(m):
    """채운 삼각형 marker → (뾰족한 꼭짓점, 단위 방향 벡터) 또는 None(삼각형이 아님·납작함)."""
    pts = [tuple(p) for p in m.get("pts") or []]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) != 3:
        return None
    sides = [(math.dist(pts[(i + 1) % 3], pts[(i + 2) % 3]), i) for i in range(3)]  # i 맞은편 변
    sides.sort()
    short, tip_i = sides[0]
    tip = pts[tip_i]
    a, b = pts[(tip_i + 1) % 3], pts[(tip_i + 2) % 3]
    base = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    L = math.dist(tip, base)
    if L == 0 or short > 1.6 * L or sides[1][0] - short < 0.05 * L and sides[2][0] - short < 0.05 * L and short > L:
        return None
    return tip, ((tip[0] - base[0]) / L, (tip[1] - base[1]) / L)


def _chain_flow(ch, markers, prm):
    """사슬 하나의 흐름: +1(pts 첫 점 → 끝 점), -1(반대), None(화살촉 없음·엇갈림)."""
    pts = ch["pts"]
    if len(pts) < 2:
        return None
    votes = set()
    for m in markers:
        ax = arrow_axis(m)
        if ax is None:
            continue
        tip, d = ax
        size = max(m["bbox"][2] - m["bbox"][0], m["bbox"][3] - m["bbox"][1])
        c = ((m["bbox"][0] + m["bbox"][2]) / 2.0, (m["bbox"][1] + m["bbox"][3]) / 2.0)
        best = None
        for a, b in _segs(pts):
            dist = min(_seg_dist(c, a, b)[0], _seg_dist(tip, a, b)[0])
            if best is None or dist < best[0]:
                best = (dist, a, b)
        dist, a, b = best
        if dist > max(1.5, NEAR_FACTOR * size):
            continue
        L = math.dist(a, b)
        if L == 0:
            continue
        cos = (d[0] * (b[0] - a[0]) + d[1] * (b[1] - a[1])) / L
        if abs(cos) < ALIGN_MIN:
            continue
        votes.add(1 if cos > 0 else -1)
    return votes.pop() if len(votes) == 1 else None


VENT_ALIGN_MIN = 0.9   # 끝 화살촉 방향과 배관 끝 선분 방향의 cos 하한(바깥을 가리켜야 한다)


def end_arrow(pts, k, markers, prm):
    """선 pts의 끝 k(0: 첫 점, 1: 끝 점)가 바깥쪽(선이 나아가던 방향)을 가리키는 채운 삼각형 화살촉 하나 안에 있으면
    (화살촉, 뾰족한 끝 점), 아니면 None. 이런 끝은 화살촉 끝까지가 배관 끝이다."""
    seq = pts if k == 1 else pts[::-1]
    pt = seq[-1]
    prev = next((p for p in reversed(seq[:-1]) if math.dist(p, pt) > 0.5), None)
    hits = [m for m in markers if arrow_axis(m) is not None and _inside(pt, m["bbox"], prm["end_tol"])]
    if prev is None or len(hits) != 1:
        return None
    tip, d = arrow_axis(hits[0])
    if (d[0] * (pt[0] - prev[0]) + d[1] * (pt[1] - prev[1])) / math.dist(prev, pt) < VENT_ALIGN_MIN:
        return None
    return hits[0], tip


def _outlet_host(ch, k, m, prm):
    """화살촉 m에서 끝나는 사슬 ch의 반대 끝이 몸체 없는 작은 선 기호에 붙고, 사슬과 화살촉이 그 기호의 장식선 범위
    (decor_extent_ratio) 안에 있으면 그 기호. 기기 드레인 깔때기의 'DE' 출구 화살표(범례 1.7-1, APR1400 025·033쪽)처럼
    기호의 일부다. 끝 기호를 따로 만들지 않고 그 기호에 넣는다."""
    v = ch["ends"][1 - k][0]
    if v[0] != "sym" or not v[1].stroke_only or v[1].bodies:
        return None
    host = v[1]
    reach = prm["decor_extent_ratio"] * max(host.core[2] - host.core[0], host.core[3] - host.core[1])
    pts = list(ch["pts"]) + [m["bbox"][:2], m["bbox"][2:]]
    return host if all(_inside(p, host.bbox, reach) for p in pts) else None


def _vent_ends(chains, markers, polys, prm):
    """기호에 닿지 않은 실선 배관 끝이 바깥을 가리키는 화살촉 안에 있고(end_arrow) 화살촉 끝이 빈 곳을 가리키면 대기
    방출 끝(범례의 VENT·ATM 화살표, APR1400 046·063·105쪽)이다. 그 화살촉을 몸체로 하는 끝 기호를 만들어 사슬 끝을
    잇는다(제자리에서 고침). 배관 안쪽을 가리키는 화살촉(흘러드는 쪽), 점선(신호선)·공압 신호선 끝, 화살촉 끝이 다른
    선에 닿는 것(선을 가리키는 지시선)은 끝 기호로 보지 않는다. 작은 선 기호에서 나온 짧은 출구는 그 기호에 넣는다
    (_outlet_host). 화살촉은 흐름 방향 근거로도 남긴다(markers에서 빼지 않는다). → (새 기호 목록, 남은 사슬 목록)."""
    from .pdf_vector_grouping import _Sym
    made, absorbed = {}, set()
    poly_of = {p["id"]: p for p in polys}
    segs = None
    for ch in chains:
        if ch.get("dashed") or ch.get("pneumatic") or len(ch["pts"]) < 2:
            continue
        for k in (0, 1):
            v, pt, _ = ch["ends"][k]
            hit = end_arrow(ch["pts"], k, markers, prm) if v[0] == "free" else None
            if hit is None:
                continue
            m, tip = hit
            if segs is None:
                segs = [(a, b, id(c)) for c in chains for a, b in _segs(c["pts"])]
            if any(_seg_dist(tip, a, b)[0] <= prm["end_tol"] for a, b, c in segs if c != id(ch)):
                continue
            host = _outlet_host(ch, k, m, prm)
            if host is not None and all(e in poly_of for e in ch["evidence"]):
                host.add([dict(poly_of[e], kind_="poly") for e in ch["evidence"]], "strokes")
                host.add([m], "dashes" if m.get("thin_tip") else "markers")
                absorbed.add(id(ch))
                break
            s = made.get(id(m))
            if s is None:
                s = made[id(m)] = _Sym([dict(m, kind_="body")])
            ch["ends"][k] = (("sym", s), pt, "pdf_arrowhead")
    return list(made.values()), [ch for ch in chains if id(ch) not in absorbed]


def continuation_flow(sym, point):
    """연결 표시 화살표(오각 깃발)에 닿은 배관 끝 point → 'into'(배관이 화살표로 흘러듦), 'out'(화살표에서 나옴), None.
    긴 축 양 끝 가운데 꼭짓점이 하나인 쪽이 뾰족한 쪽, 둘인 쪽이 평평한 쪽이다. 화살표는 흐름 방향을 가리키므로 평평한
    쪽으로 들어온 배관은 다른 도면으로 나가고, 뾰족한 쪽에서 나온 배관은 다른 도면에서 들어온다. 양 끝이 다 뾰족하거나
    다 평평하면, 또는 배관이 긴 변 쪽에 닿으면 정하지 않는다."""
    bodies = [b for b in sym.bodies if b.get("pts")]
    if not bodies:
        return None
    body = max(bodies, key=lambda b: (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]))
    x0, y0, x1, y1 = body["bbox"]
    ax = 0 if x1 - x0 >= y1 - y0 else 1
    lo, hi = (x0, x1) if ax == 0 else (y0, y1)
    span = hi - lo
    if span <= 0:
        return None
    pts = {(round(p[0], 2), round(p[1], 2)) for p in body["pts"]}
    tol = 0.08 * span
    at_lo = sum(1 for p in pts if p[ax] - lo <= tol)
    at_hi = sum(1 for p in pts if hi - p[ax] <= tol)
    if {at_lo, at_hi} != {1, 2}:
        return None
    t = (point[ax] - lo) / span
    if 0.25 < t < 0.75:
        return None
    pointed_end_is_hi = at_hi == 1
    return "out" if (t >= 0.75) == pointed_end_is_hi else "into"


def air_arrow_flow(sym, point):
    """덕트 끝 공기 흐름 화살표(범례 1.7-1 2 of 4 DUCTED AIR FLOW)에 닿은 덕트 끝 point → 'out'(화살촉이 덕트 쪽을 가리킴:
    공기가 방에서 덕트로 들어감), 'in'(화살촉이 덕트 반대쪽: 덕트에서 방으로 나옴), None(화살촉이 하나가 아니거나 덕트가
    화살표 축 옆에 닿음)."""
    axes = [ax for ax in (arrow_axis(m) for m in sym.markers) if ax]
    if len(axes) != 1:
        return None
    _, d = axes[0]
    x0, y0, x1, y1 = sym.bbox
    along = (point[0] - (x0 + x1) / 2.0) * d[0] + (point[1] - (y0 + y1) / 2.0) * d[1]
    if abs(along) < 0.25 * max(x1 - x0, y1 - y0):
        return None
    return "out" if along > 0 else "in"


CHECK_DOT_MAX = 1.3    # 체크 밸브 경첩 점(채운 작은 원)의 긴 변 상한(pt). APR1400 상자형 체크 밸브 점 약 0.9
CHECK_END_FRAC = 0.25  # 긴 축 양 끝에서 이 비율 안이어야 끝으로 본다(경첩 점·배관 끝 모두)


def check_valve_flow(sym, point):
    """체크 밸브(범례 1.7-1 CHECK: 경첩 점에서 원판 사선이 반대쪽 막대로 내려간다)에 닿은 배관 끝 point → 'in'(경첩 점
    쪽: 흘러 들어옴), 'out'(반대쪽: 흘러 나감), None(경첩 점이 하나가 아니거나 긴 축 가운데에 있음, 배관이 긴 축 가운데로
    닿음). 개발용 12쪽에서 화살촉·깃발·흐름 보존으로 이미 방향이 정해진 체크 밸브 배관 62개가 모두 이 규칙과 같았다."""
    dots = [m for m in sym.dashes + sym.markers
            if max(m["bbox"][2] - m["bbox"][0], m["bbox"][3] - m["bbox"][1]) <= CHECK_DOT_MAX]
    x0, y0, x1, y1 = sym.bbox
    ax = 0 if x1 - x0 >= y1 - y0 else 1
    lo, hi = sym.bbox[ax], sym.bbox[ax + 2]
    if len(dots) != 1 or hi <= lo:
        return None
    t_dot = ((dots[0]["bbox"][ax] + dots[0]["bbox"][ax + 2]) / 2.0 - lo) / (hi - lo)
    t_pt = (point[ax] - lo) / (hi - lo)
    if CHECK_END_FRAC < t_dot < 1 - CHECK_END_FRAC or CHECK_END_FRAC < t_pt < 1 - CHECK_END_FRAC:
        return None
    return "in" if (t_dot > 0.5) == (t_pt > 0.5) else "out"


def _end_symbol_flows(relations, sym_of, kind_of):
    """방향 없는 물리 배관에 기호가 그린 방향을 매긴다(제자리에서 고침). sym_of: {node_local_id: _Sym}.
    공기 흐름 화살표는 덕트 하나만 닿은 것, 체크 밸브는 배관 둘이 하나는 경첩 쪽, 하나는 반대쪽 끝에 닿은 것만 본다.
    한 관계에 두 기호가 다른 방향을 말하면 정하지 않고, 화살촉 등으로 이미 방향이 있는 관계는 건드리지 않는다.
    → 새로 정한 관계 수. basis는 기호 이름(air_flow_arrow, check_valve_hinge)."""
    pipes = [r for r in relations if r.get("kind") == "physical_connection" and None not in _ends(r)
             and _ends(r)[0] != _ends(r)[1]]
    at = {}
    for r in pipes:
        for e in r["endpoints"]:
            at.setdefault(e["node_local_id"], []).append((r, e))
    votes = {}

    def vote(r, n, sense, basis):
        other = next(x for x in _ends(r) if x != n)
        votes.setdefault(id(r), (r, set()))[1].add(((n, other) if sense == "out" else (other, n), basis))
    for n, hits in at.items():
        if n not in sym_of:
            continue
        if kind_of.get(n) == "air_flow_arrow" and len(hits) == 1:
            sense = air_arrow_flow(sym_of[n], hits[0][1]["point"])
            if sense:
                vote(hits[0][0], n, sense, "air_flow_arrow")
        elif kind_of.get(n) == "check_valve" and len(hits) == 2:
            senses = [check_valve_flow(sym_of[n], e["point"]) for _, e in hits]
            # 화살촉·깃발이 경첩 점과 반대로 말하는 밸브는 정하지 않는다(056쪽 V2008처럼 경첩 점을 거꾸로 그린 곳이 있다)
            drawn = [(r.get("flow_direction") or {}).get("to") for r, _ in hits]
            if sorted(senses, key=str) == ["in", "out"] and not any(
                    to is not None and (to == n) != (s == "in") for to, s in zip(drawn, senses)):
                for (r, _), sense in zip(hits, senses):
                    vote(r, n, sense, "check_valve_hinge")
    added = 0
    for r, vs in votes.values():
        if r.get("flow_direction") or len({v[0] for v in vs}) != 1:
            continue
        (frm, to), basis = next(iter(vs))
        ends = dict(zip(_ends(r), ("source", "target")))
        r["flow_direction"] = {"from": frm, "to": to, "from_end": ends[frm], "to_end": ends[to], "basis": basis}
        added += 1
    return added


INLINE_OPPOSITE_COS = -0.7  # 미분류 노드 가운데에서 본 두 배관 끝 방향의 cos 상한(맞은편에서 닿음)
INLINE_TICK_MAX = 12.0      # 한 끝이 노드 가운데에 닿아도 되는 작은 노드(눈금)의 긴 변 상한(pt)


def _inline_unclassified(relations, nodes):
    """배관이 꿰고 지나가는 미분류 노드 id 집합(흐름 보존의 passes). 물리 배관이 꼭 2개 닿고, 두 배관 끝이 노드
    가운데에서 보아 맞은편에 있는 것(관 끝·플랜지 눈금, 벽 관통 표시, 이름 모를 배관 부속. APR1400 099·133쪽).
    두 끝이 한쪽에 몰리거나 직각으로 닿는 것은 이름 모를 설비의 입출구일 수 있어 넣지 않는다."""
    ends = {}
    for r in relations:
        if r.get("kind") != "physical_connection" or None in _ends(r) or _ends(r)[0] == _ends(r)[1]:
            continue
        for e in r["endpoints"]:
            ends.setdefault(e["node_local_id"], []).append(e.get("point"))
    out = set()
    for n in nodes:
        pts = ends.get(n["local_id"], [])
        if n.get("kind") is not None or len(pts) != 2 or None in pts:
            continue
        g = n["geometry"]
        c = (g["x"] + g["width"] / 2.0, g["y"] + g["height"] / 2.0)
        v = [(p[0] - c[0], p[1] - c[1]) for p in pts]
        L = [math.hypot(*x) for x in v]
        if min(L) < 1e-6:
            if max(g["width"], g["height"]) <= INLINE_TICK_MAX:
                out.add(n["local_id"])
        elif (v[0][0] * v[1][0] + v[0][1] * v[1][1]) / (L[0] * L[1]) <= INLINE_OPPOSITE_COS:
            out.add(n["local_id"])
    return out


INSTR_FACING_COS = -0.9   # 계기에 닿는 두 실선의 마지막 토막이 마주 본다고 보는 cos 상한
INSTR_OFFSET = 1.5        # 마주 본 두 토막이 한 줄이라고 보는 옆 어긋남 상한(pt)
INSTR_GAP_RATIO = 0.5     # 두 선 끝 사이 거리 ≤ 계기 긴 변 × 비율(배관이 상자 한 귀퉁이를 꿰고 지나감)


def _through_instruments(meas, instruments):
    """배관이 꿰고 지나가는 계기 id 집합. instruments: {node_local_id: 노드}. 계기에 닿는 실선 측정선 가운데 둘의
    마지막 토막이 한 줄 위에서 마주 보고, 두 끝 사이가 계기 크기보다 훨씬 짧은 것(129쪽 FIT 상자 밑변을 지나는 급수
    배관, 두 끝 사이 약 3pt·상자 긴 변 44pt). 계기 원 위아래로 들어오는 차압 탭은 두 끝 사이가 원 지름이라 넣지 않는다."""
    last = {}
    for r in meas:
        path = [tuple(p) for p in r["evidence"]["pdf_path"]]
        for e, seq in zip(r["endpoints"], (path, path[::-1])):
            n = e["node_local_id"]
            if n not in instruments:
                continue
            q = next((p for p in seq[1:] if math.dist(p, seq[0]) > 0.5), None)
            if q is not None:
                last.setdefault(n, []).append((seq[0], q))

    def unit(p, q):
        return (p[0] - q[0]) / math.dist(p, q), (p[1] - q[1]) / math.dist(p, q)

    out = set()
    for n, segs in last.items():
        g = instruments[n]["geometry"]
        gap = INSTR_GAP_RATIO * max(g["width"], g["height"])
        for i, (p1, q1) in enumerate(segs):
            u1 = unit(p1, q1)
            for p2, q2 in segs[i + 1:]:
                u2 = unit(p2, q2)
                if u1[0] * u2[0] + u1[1] * u2[1] <= INSTR_FACING_COS and math.dist(p1, p2) <= gap and \
                        abs((p2[0] - p1[0]) * u1[1] - (p2[1] - p1[1]) * u1[0]) <= INSTR_OFFSET:
                    out.add(n)
    return out


def _ends(r):
    return [e.get("node_local_id") for e in r["endpoints"]]


def _propagate_flows(relations, kind_of, passes=(), side_branches=()):
    """방향 없는 물리 배관에 흐름 보존으로 방향을 매긴다(제자리에서 고침). kind_of: {node_local_id: kind}.
    passes: 종류와 상관없이 공기·유체가 지나가는 노드 id(공조기 칸, pdf_vector_grouping._housing_chains).
    side_branches: 물리 배관 말고도 배관 가지(계기 상자를 꿰는 배관, _through_instruments)가 더 있는 분기점 id. 그
    가지의 흐름을 모르므로 분기점 규칙을 쓰지 않는다(129쪽 유량계 상자로 가는 급수 배관).
    → 새로 정한 관계 수. 매긴 관계의 flow_direction basis는 'flow_continuity'."""
    pipes = [r for r in relations if r.get("kind") == "physical_connection" and None not in _ends(r)
             and _ends(r)[0] != _ends(r)[1]]
    at = {}
    for r in pipes:
        for n in _ends(r):
            at.setdefault(n, []).append(r)

    def side(r, n):  # n에서 보아 들어옴 'in', 나감 'out', 모름 None
        fd = r.get("flow_direction")
        if not fd:
            return None
        return "in" if fd.get("to") == n else "out" if fd.get("from") == n else None

    def set_flow(r, frm, to):
        ends = dict(zip(_ends(r), ("source", "target")))
        r["flow_direction"] = {"from": frm, "to": to, "from_end": ends[frm], "to_end": ends[to],
                               "basis": "flow_continuity"}

    added = 0
    changed = True
    while changed:
        changed = False
        for n, rs in at.items():
            kind = kind_of.get(n)
            sides = [side(r, n) for r in rs]
            unknown = [r for r, s in zip(rs, sides) if s is None]
            if len(unknown) != 1:
                continue
            known = [s for s in sides if s]
            if (kind in PASS_KINDS or n in passes) and len(rs) == 2 and len(known) == 1:
                want = "out" if known[0] == "in" else "in"
            elif kind == "tee" and n not in side_branches and known and len(set(known)) == 1:
                want = "in" if known[0] == "out" else "out"
            else:
                continue
            r = unknown[0]
            other = next(x for x in _ends(r) if x != n)
            set_flow(r, n, other) if want == "out" else set_flow(r, other, n)
            added += 1
            changed = True
    return added


def _revert_contradictions(relations, kind_of, passes=(), side_branches=()):
    """흐름 보존이 매긴 방향이 그림의 방향과 부딪친 곳을 되돌린다(제자리에서 고침). 흐름이 지나가는 노드(관계 2개인
    2포트 기호·passes, 가지가 모두 물리 배관인 분기점)에 닿은 배관이 모두 방향을 알고 모두 들어오거나 모두 나가면, 그
    노드에 닿은 'flow_continuity' 관계를 방향 모름으로 둔다. 그림이 그린 방향(화살촉·깃발·기호)은 남긴다.
    → 되돌린 관계 수."""
    at = {}
    for r in relations:
        if r.get("kind") == "physical_connection" and None not in _ends(r) and _ends(r)[0] != _ends(r)[1]:
            for n in _ends(r):
                at.setdefault(n, []).append(r)
    undo = {}
    for n, rs in at.items():
        kind = kind_of.get(n)
        if not ((kind in PASS_KINDS or n in passes) and len(rs) == 2 or
                kind == "tee" and n not in side_branches and len(rs) >= 2):
            continue
        fds = [r.get("flow_direction") for r in rs]
        if None in fds or len({fd.get("to") == n for fd in fds}) != 1:
            continue
        undo.update((id(r), r) for r, fd in zip(rs, fds) if fd.get("basis") == "flow_continuity")
    for r in undo.values():
        r["flow_direction"] = None
    return len(undo)
