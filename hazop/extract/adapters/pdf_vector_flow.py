"""벡터 PDF 흐름 방향(pdf_vector에서 나눔). 규격: docs/specs/extraction.md '읽기 품질 지표' 연결 (나).

1. 화살촉: 기호에 묶이지 않고 남은 채운 삼각형(leftover markers)의 뾰족한 쪽(가장 짧은 변 맞은편 꼭짓점)이 가리키는
   방향을, 그 삼각형이 얹힌 사슬 선분의 방향과 견준다. 사슬 위 화살촉이 모두 같은 쪽이면 그 방향, 엇갈리면 정하지 않는다.
2. 흐름 보존: 방향을 아는 배관에서 시작해, 2포트 배관 기호(밸브·배관 부속)는 들어온 만큼 나가고, 분기점(티)에서
   아는 배관이 모두 들어오는(또는 모두 나가는) 쪽이고 모르는 배관이 하나뿐이면 그 하나는 반대쪽이다. 설비(탱크·펌프
   등)는 입출구가 여럿일 수 있어 지나가지 않는다. 바뀌지 않을 때까지 되풀이한다.
쪽 번호·좌표로 가르는 예외는 두지 않는다.
"""

import math

from .pdf_vector_common import _seg_dist, _segs

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


def _ends(r):
    return [e.get("node_local_id") for e in r["endpoints"]]


def _propagate_flows(relations, kind_of):
    """방향 없는 물리 배관에 흐름 보존으로 방향을 매긴다(제자리에서 고침). kind_of: {node_local_id: kind}.
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
            if kind in PASS_KINDS and len(rs) == 2 and len(known) == 1:
                want = "out" if known[0] == "in" else "in"
            elif kind == "tee" and known and len(set(known)) == 1:
                want = "in" if known[0] == "out" else "out"
            else:
                continue
            r = unknown[0]
            other = next(x for x in _ends(r) if x != n)
            set_flow(r, n, other) if want == "out" else set_flow(r, other, n)
            added += 1
            changed = True
    return added
