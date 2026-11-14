"""벡터 PDF 어댑터의 기호 묶기(pdf_vector 설명글 2번).

분류된 원시 요소(몸체·열린 선·표식·점선 조각)를 기호(_Sym)로 묶는다. 겹치는 몸체, 몸체 안 선, 구동부 축,
끝이 뜬 장식선, 플랜지 판 조립(_plate_assemblies), 관계에 닿지 않은 부속 기호 합치기(_merge_appendages)를 다룬다.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""

import collections
import math

from .pdf_vector_common import (
    _union, _inside, _pt_box_dist, _box_gap, _depth, _w, _h, _seg_dist, _segs, _poly_dist, _poly_box_dist,
    _uf_groups, _center, _is_circle, _is_chevron, _is_triangle, _pt_circle_dist, _bbox_pts,
    _end_runs, _meets_at_end,
)


class _Sym:
    def __init__(self, members, stroke_only=False):
        self.bodies = [m for m in members if m.get("kind_") == "body"]
        self.strokes = [m for m in members if m.get("kind_") == "poly"]
        self.markers, self.dashes = [], []
        self.stroke_only = stroke_only
        self.alive = True
        self.core = None
        self.bbox = None
        self._recalc()

    def _recalc(self):
        bodies = self.bodies or self.strokes
        core = bodies[0]["bbox"]
        for m in bodies[1:]:
            core = _union(core, m["bbox"])
        self.core = core
        box = core
        for m in self.bodies + self.strokes + self.markers + self.dashes:
            box = _union(box, m["bbox"])
        self.bbox = box

    def add(self, items, kind):
        getattr(self, kind).extend(items)
        self._recalc()

    def merge(self, other):
        self.bodies += other.bodies
        self.strokes += other.strokes
        self.markers += other.markers
        self.dashes += other.dashes
        self.stroke_only = self.stroke_only and other.stroke_only
        other.alive = False
        self._recalc()

    def inner_tol(self, prm):
        return max(prm["inner_tol_min"], min(prm["inner_tol_max"],
                                             prm["inner_tol_ratio"] * max(_w(self.core), _h(self.core))))

    def arrow_only(self):
        """도면 연결 표시 화살표만으로 된 기호. 주변 선을 몸체 일부로 받아들이지 않는다(선은 배관 연결이다)."""
        return bool(self.bodies) and all(_is_chevron(b) for b in self.bodies)

    def deep(self, p, prm):
        if self.stroke_only or self.arrow_only():
            return False  # 화살표 안으로 들어간 배관은 연결이지 화살표의 일부가 아니다
        if _depth(p, self.core) <= max(prm["deep_min"], prm["deep_ratio"] * min(_w(self.core), _h(self.core))):
            return False
        return self.seed is None  # 검정 견본으로 올린 몸통은 이미 한 기호다. 안으로 들어온 선을 제 일부로 삼지 않는다

    def evidence(self):
        return sorted(m["id"] for m in self.bodies + self.strokes + self.markers + self.dashes)

    @property
    def seed(self):
        """몸체가 모두 사전의 같은 검정 견본 묶음(pdf_vector._promote_black_symbols)이면 그 번호, 아니면 None."""
        ids = {b.get("seed") for b in self.bodies}
        return next(iter(ids)) if len(ids) == 1 else None


def _cluster_bodies(bodies, prm):
    for b in bodies:
        b["kind_"] = "body"
    # 연결 표시 화살표는 맞닿은 밸브·축소관 몸체와 한 기호로 묶지 않는다(묶이면 화살표도 밸브도 종류를 잃는다)
    alone = [_is_chevron(b) for b in bodies]
    # 사전의 검정 견본에 통째로 맞은 몸체(seed)는 이미 한 기호다. 맞닿은 축소관·구동부 몸체와 묶지 않는다.
    # 안전등급 경계 마름모(class_mark, _mark_class_boundaries)도 그 두 삼각형끼리만 묶는다
    groups = _uf_groups(len(bodies), lambda i, j: not (alone[i] or alone[j]) and
                        bodies[i].get("seed") == bodies[j].get("seed") and
                        bodies[i].get("class_mark") == bodies[j].get("class_mark") and
                        _box_gap(bodies[i]["bbox"], bodies[j]["bbox"]) <= prm["touch_tol"])
    return [_Sym([bodies[i] for i in g]) for g in groups]


def _black_fill_groups(fills, prm):
    """검은 채움 도형(표식과 검은 몸체)을 맞닿은 것끼리 묶는다 → [{"straight", "round", "bbox"}], 묶음의 첫 채움 id 순.
    APR1400은 정상 운전 중 닫힌 밸브를 검게 칠한다(범례 1.7-1 1/4). 몸통은 채운 나비 하나이거나 채운 삼각형 둘이고,
    글로브는 가운데에 둥근 점이 겹친다. 곧은 변으로 된 채움(straight)이 몸통, 둥근 채움(round)이 그 위의 점이다."""
    groups = _uf_groups(len(fills), lambda i, j: _box_gap(fills[i]["bbox"], fills[j]["bbox"]) <= prm["touch_tol"])
    out = []
    for g in groups:
        items = sorted((fills[i] for i in g), key=lambda m: m["id"])
        box = items[0]["bbox"]
        for m in items[1:]:
            box = _union(box, m["bbox"])
        out.append({"straight": [m for m in items if not m["curved"]], "round": [m for m in items if m["curved"]],
                    "bbox": box, "first": items[0]["id"]})
    out.sort(key=lambda g: g["first"])
    return out


def _cut_through(pts, box, axis=None, lateral=None):
    """꺾은선 pts가 상자의 축(axis, 없으면 긴 축) 방향으로 상자를 끊기지 않고 지나가면 들어가는 변과 나가는 변에서
    나눈 두 조각. 지나가지 않으면 None. 옆으로 가로지르는 선이나 상자 안에서 끝나는 선은 나누지 않는다. lateral을
    주면 들어가고 나가는 두 점이 모두 상자 가운데 줄에서 그 거리 안이어야 한다."""
    if axis is None:
        axis = 0 if _w(box) >= _h(box) else 1
    lo, hi, side_lo, side_hi = box[axis], box[axis + 2], box[1 - axis], box[3 - axis]
    if lateral is not None:
        mid = (side_lo + side_hi) / 2
        side_lo, side_hi = mid - lateral, mid + lateral
    for k, (a, b) in enumerate(_segs(pts)):
        if not (min(a[axis], b[axis]) < lo and max(a[axis], b[axis]) > hi):
            continue

        def at(v):
            t = (v - a[axis]) / (b[axis] - a[axis])
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        first, second = (at(lo), at(hi)) if a[axis] < b[axis] else (at(hi), at(lo))
        if all(side_lo <= q[1 - axis] <= side_hi for q in (first, second)):
            return pts[:k + 1] + [first], [second] + pts[k + 1:]
    return None


def _cut_at_boxes(polys, boxes):
    """검게 칠한 밸브 몸통(boxes) 밑을 끊지 않고 그린 배관을 몸통 양 끝에서 나눈다. 채움이 선을 덮어 그림으로는 끊긴 것과
    같지만, 선이 하나면 양쪽 배관이 밸브를 건너 이어지고 밸브 노드에는 배관이 닿지 않는다. 폭과 높이가 거의 같은 몸통은
    배관 방향을 알 수 없어 나누지 않는다."""
    boxes = [b for b in boxes if abs(_w(b) - _h(b)) > 0.3]
    if not boxes:
        return polys
    out = []
    for p in polys:
        pieces = [p["pts"]]
        for box in boxes:
            if _box_gap(p["bbox"], box) > 0:
                continue
            cut = []
            for pts in pieces:
                halves = _cut_through(pts, box)
                cut += list(halves) if halves else [pts]
            pieces = cut
        if len(pieces) == 1:
            out.append(p)
        else:
            out += [dict(p, pts=pts, bbox=(min(q[0] for q in pts), min(q[1] for q in pts), max(q[0] for q in pts),
                                           max(q[1] for q in pts))) for pts in pieces]
    return out


FLOW_LONG_RATIO = 1.5  # 몸체 긴 변이 짧은 변의 이 배 이상이면 긴 축을 흐름 축으로 본다(_flow_axis)
FLOW_LONG_MAX = 3.0    # 긴 변이 짧은 변의 이 배를 넘는 띠(바닥 격자, 건물 경계 화살표)는 배관 부품이 아니다
END_EDGE_RATIO = 0.3   # 몸체 끝 변: 축에 수직이고 길이가 몸체 옆 폭의 이 비율 이상인 변


def _flow_axis(sym, prm):
    """기호 몸체의 흐름 축(0 = 가로, 1 = 세로). 몸체 양 끝 모두에 그 축과 수직인 변이 있는 축이 하나뿐이면 그 축이다
    (나비꼴 게이트 밸브는 좌우 끝의 세로 변, 축소관 사다리꼴은 위아래 변). 그렇지 않으면 긴 변이 짧은 변의
    FLOW_LONG_RATIO배 이상일 때 긴 축이다. 곧은 변이 없는 몸체(원·계기), 정사각형처럼 두 축 모두 끝 변이 있는
    납작한 몸체, FLOW_LONG_MAX배보다 긴 띠, 삼각형 하나뿐인 몸체(화살촉), 선으로만 그린 기호는 축을 모른다(None)."""
    straight = [b for b in sym.bodies if not b.get("curved")]
    c, tol = sym.core, prm["axis_rect_tol"]
    w, h = _w(c), _h(c)
    if not straight or sym.stroke_only or sym.arrow_only() or max(w, h) > FLOW_LONG_MAX * min(w, h):
        return None
    ended = []
    for ax in (0, 1):
        side = c[3 - ax] - c[1 - ax]
        at = set()
        for b in straight:
            pts = b["pts"]
            for p, q in zip(pts, pts[1:] + pts[:1]):
                if abs(p[ax] - q[ax]) > tol or abs(p[1 - ax] - q[1 - ax]) < END_EDGE_RATIO * side:
                    continue
                for end, v in ((0, c[ax]), (1, c[ax + 2])):
                    if abs(p[ax] - v) <= tol and abs(q[ax] - v) <= tol:
                        at.add(end)
        if at == {0, 1}:
            ended.append(ax)
    if len(ended) == 1:
        return ended[0]
    if max(w, h) >= FLOW_LONG_RATIO * min(w, h) and not all(_is_triangle(b) for b in straight):
        return 0 if w >= h else 1
    return None


def _contact_chains(syms, prm):
    """검정 견본으로 올린 몸통(seed)의 배관 방향 끝에 다른 기호가 맞닿아 있으면 두 기호를 잇는 길이 0인 사슬을 만든다.
    밸브에 축소관을 붙여 그리면 둘 사이에 선이 없다. 올린 몸통은 맞닿은 몸체와 한 기호로 묶지 않으므로, 이 사슬이 없으면
    배관이 그 자리에서 끊긴다. 몸통 옆에 붙은 기호(구동부 등)와 몸통을 품은 큰 기호는 잇지 않는다. 폭과 높이가 거의
    같은 몸통은 배관 방향을 알 수 없어 잇지 않는다."""
    out = []
    for i, v in enumerate(syms):
        if v.seed is None or abs(_w(v.core) - _h(v.core)) <= 0.3:
            continue
        axis = 0 if _w(v.core) >= _h(v.core) else 1
        lo, hi = v.core[axis], v.core[axis + 2]
        for j, t in enumerate(syms):
            if t is v or (t.seed is not None and j < i) or _box_gap(v.core, t.bbox) > prm["touch_tol"]:
                continue
            if t.bbox[axis] >= hi - prm["touch_tol"]:
                at = hi
            elif t.bbox[axis + 2] <= lo + prm["touch_tol"]:
                at = lo
            else:
                continue
            a, b = max(v.core[1 - axis], t.bbox[1 - axis]), min(v.core[3 - axis], t.bbox[3 - axis])
            if b < a:
                continue
            pt = (at, (a + b) / 2) if axis == 0 else ((a + b) / 2, at)
            out.append({"pts": [pt, pt], "ends": [(("sym", v), pt, "pdf_touching_bodies"),
                                                  (("sym", t), pt, "pdf_touching_bodies")],
                        "evidence": sorted({v.evidence()[0], t.evidence()[0]}), "contact": True})
    return out


def _sym_dist(p, s, prm=None):
    """점과 기호 사이 거리. 몸체가 원 하나뿐인 기호(밸브 번호·계기 원)는 상자 귀퉁이가 비어 있어 원 모양 그대로 잰다.
    상자로 재면 밸브 번호 원 귀퉁이 옆에 그린 안전밸브 스프링 빗금이 그 원에 닿은 연결선으로 읽혀 밸브에 들지
    못한다(APR1400 008쪽 POSRV 파일럿 밸브). prm이 없으면 상자 거리다."""
    if prm is not None and len(s.bodies) == 1 and _is_circle(s.bodies[0], prm):
        d = _pt_circle_dist(p, s.bodies[0])
        for m in s.strokes + s.markers + s.dashes:
            d = min(d, _pt_box_dist(p, m["bbox"]))
        return d
    return _pt_box_dist(p, s.bbox)


def _nearest_sym(p, syms, tol, prm=None):
    best = None
    for s in syms:
        if not s.alive:
            continue
        d = _sym_dist(p, s, prm)
        if d <= tol:
            key = (d, _w(s.bbox) * _h(s.bbox))
            if best is None or key < best[0]:
                best = (key, s)
    return best[1] if best else None


def _end_status(poly, k, polys, syms, markers, prm):
    """선 끝 k(0/1)의 붙음: 'sym' / 'marker' / 'end' / 'interior' / None(자유)."""
    p = poly["pts"][0] if k == 0 else poly["pts"][-1]
    if _nearest_sym(p, syms, prm["attach_tol"]) is not None:
        return "sym"
    for m in markers:
        if _inside(p, m["bbox"], prm["end_tol"]):
            return "marker"
    for q in polys:
        if q is poly:
            continue
        for e in (q["pts"][0], q["pts"][-1]):
            if math.hypot(p[0] - e[0], p[1] - e[1]) <= prm["end_tol"]:
                return "end"
        for a, b in _segs(q["pts"]):
            if _seg_dist(p, a, b)[0] <= prm["end_tol"]:
                return "interior"
    return None


BAR_MID_LO, BAR_MID_HI = 0.25, 0.75  # 막대 길이의 이 비율 구간에 선 끝이 얹히면 막대 가운데에 닿은 것(_lands_mid_bar)
BAR_ON_TOL = 0.2                       # 선 끝이 막대 위에 있다고 보는 거리(pt)
BAR_CROSS_SIN = 0.5                    # 선이 막대에 이 사인값(30도) 이상 비스듬히 들어와야 가운데에 닿은 것으로 본다


def _lands_mid_bar(q, bar):
    """선 q의 한 끝이 선분 bar의 가운데 구간에 비스듬히 정확히 얹혔으면 q의 다음 점(배관이 뻗는 쪽), 아니면 None.
    같은 줄 위에 겹쳐 그린 두 선은 해당하지 않는다."""
    a, b = bar
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if length == 0:
        return None
    for k in (0, -1):
        e, nxt = q["pts"][k], q["pts"][1 if k == 0 else -2]
        d, near = _seg_dist(e, a, b)
        run = math.hypot(nxt[0] - e[0], nxt[1] - e[1])
        if d > BAR_ON_TOL or run == 0 or \
                not BAR_MID_LO <= math.hypot(near[0] - a[0], near[1] - a[1]) / length <= BAR_MID_HI:
            continue
        if abs((b[0] - a[0]) * (nxt[1] - e[1]) - (b[1] - a[1]) * (nxt[0] - e[0])) / (length * run) >= BAR_CROSS_SIN:
            return nxt
    return None


def _bar_fed_strokes(polys, prm):
    """한 번에 그린 열린 선 기호(APR1400 상자형 체크밸브 '|\\|': 세로 막대, 빗변, 세로 막대)를 찾아 기호로 세운다 →
    (기호 [_Sym], 남은 선). 선의 첫 토막과 끝 토막이 막대이고, 두 막대 가운데에 서로 다른 배관 끝이 바깥에서 하나씩
    닿으면 배관 사이에 낀 기호다. 막대가 짧으면(길이의 반이 end_tol 이하) 선 끝과 배관 끝이 서로 가까워 그대로 두면
    배관 조각으로 이어지고(_end_status가 두 끝을 모두 '붙음'으로 본다) 기호가 생기지 않는다."""
    found, rest = [], []
    for p in polys:
        pts = p["pts"]
        if len(pts) < 3 or p.get("curved") or not \
                prm["stroke_symbol_min"] <= max(_w(p["bbox"]), _h(p["bbox"])) <= prm["stroke_symbol_max"]:
            rest.append(p)
            continue
        feeders = []
        near = [q for q in polys if q is not p and _box_gap(q["bbox"], p["bbox"]) <= BAR_ON_TOL]
        for bar in ((pts[0], pts[1]), (pts[-1], pts[-2])):
            hits = []
            for q in near:
                nxt = _lands_mid_bar(q, bar)
                if nxt is not None and not _inside(nxt, p["bbox"]):  # 배관은 기호 바깥으로 뻗는다
                    hits.append(q)
            feeders.append(hits[0] if len(hits) == 1 else None)
        if feeders[0] is not None and feeders[1] is not None and feeders[0] is not feeders[1]:
            found.append(_Sym([dict(p, kind_="poly")], stroke_only=True))
        else:
            rest.append(p)
    return found, rest


def _pockets(polys, prm):
    """배관 옆에 매단 작은 주머니(APR1400 105쪽 주증기 배관 아래 드레인 포트: 짧은 세로선 둘과 둥근 바닥)를 기호로
    세운다 → (기호 [_Sym], 주머니 입구 [(점, 기호)], 남은 선). 끝끼리 이어진 짧은 선 무리(긴 변 pocket_max 이하)에서
    다른 선과 닿지 않은 끝이 꼭 둘이고, 그 둘이 같은 배관의 중간에 떨어져 닿으며, 무리가 그 배관 한쪽으로 나와 있으면
    주머니다. 입구 양쪽 선을 배관 두 가닥으로 읽으면 주머니가 배관과 드레인 선을 잇는 고리가 되어 배관 위 기호가 모두
    드레인 쪽 기호와 이어진다. 주머니는 기호 하나이고 배관과는 입구 한 곳에서 만난다."""
    small = [p for p in polys if max(_w(p["bbox"]), _h(p["bbox"])) <= prm["pocket_max"]]
    tol = prm["end_tol"]

    def ends(p):
        return (p["pts"][0], p["pts"][-1])

    def touch(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol
    groups = _uf_groups(len(small), lambda i, j: any(touch(a, b) for a in ends(small[i]) for b in ends(small[j])))
    found, mouths, used = [], [], set()
    for g in groups:
        items = [small[i] for i in g]
        loose = [e for it in items for k, e in enumerate(ends(it))
                 if not any(touch(e, f) for o in items for kk, f in enumerate(ends(o)) if not (o is it and kk == k))]
        if len(loose) != 2 or touch(*loose):
            continue
        box = items[0]["bbox"]
        for it in items[1:]:
            box = _union(box, it["bbox"])
        if max(_w(box), _h(box)) > prm["pocket_max"]:
            continue
        host = None
        for h in polys:
            if _box_gap(h["bbox"], box) > tol or any(h is it for it in items):
                continue
            hits = []
            for e in loose:
                for a, b in _segs(h["pts"]):
                    d, q = _seg_dist(e, a, b)
                    if d <= tol and min(math.hypot(q[0] - x[0], q[1] - x[1]) for x in ends(h)) > tol:
                        hits.append((a, b))
                        break
            if len(hits) == 2:
                host = (h, hits[0])
                break
        if host is None:
            continue
        (a, b) = host[1]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        sides = [((b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])) / L
                 for it in items for q in it["pts"]]
        if not (min(sides) >= -tol and max(sides) > tol or max(sides) <= tol and min(sides) < -tol):
            continue
        sym = _Sym([dict(it, kind_="poly") for it in items], stroke_only=True)
        sym.pocket = True  # 주머니 벽 두 줄은 오리피스 판이 아니다(_shape_features)
        found.append(sym)
        mouths.append((((loose[0][0] + loose[1][0]) / 2, (loose[0][1] + loose[1][1]) / 2), sym))
        used.update(id(it) for it in items)
    return found, mouths, [p for p in polys if id(p) not in used]


ORIFICE_BOX_RATIO = 1.5  # 오리피스 상자: 두 판 사이 간격 상한 = 판 길이 × 비율(판과 간격이 비슷한 네모꼴)


def _orifice_box(a, sep, lines, dots, bodies, crossing, prm):
    """판 a와 축 방향으로 sep 떨어진 짝 판 사이 칸이 오리피스 상자('|-|' 가운데 짧은 선, APR1400 OR01B 등)인지.
    칸 안에 판과 나란하고 판보다 짧은 직선 하나만 칸 가운데에 있어야 한다. 점·몸체·가로지르는 선이 있으면 아니다."""
    if dots or bodies or crossing or len(lines) != 1 or abs(sep) > ORIFICE_BOX_RATIO * a["L"]:
        return False
    q = lines[0]
    if len(q["pts"]) != 2 or q.get("curved"):
        return False
    (x0, y0), (x1, y1) = q["pts"]
    length = math.hypot(x1 - x0, y1 - y0)
    if not 0 < length < a["L"] or abs((x1 - x0) * a["u"][1] - (y1 - y0) * a["u"][0]) / length > prm["plate_par_tol"]:
        return False
    m = ((x0 + x1) / 2 - a["c"][0], (y0 + y1) / 2 - a["c"][1])
    along = m[0] * -a["u"][1] + m[1] * a["u"][0]  # 배관 축 방향 위치(sep과 같은 부호)
    side = m[0] * a["u"][0] + m[1] * a["u"][1]
    return abs(side) <= prm["plate_align_tol"] and 0.25 <= along / sep <= 0.75


def _plate_assemblies(syms, polys, markers, dashes, prm):
    """배관을 가로지르는 짧은 판(범례 1.7-1 1/4 FLANGED CONNECTION '—| |—', 1.7-1 VALVE SYMBOLS의 BUTTERFLY '|\\●|'·
    BALL '|○|'·'|●|') 찾기 → (밸브 기호 [_Sym], 남은 선, 남은 표식, 플랜지 [(판, 판, (점, 점))]).
    판: 길이 plate_len_min~max의 직선 조각. 같은 길이·나란한 판이 같은 축 위에 있으면 한 줄로 본다.
    - 두 판 사이가 비었고 간격이 flange_gap_max 이하이며, 두 판 가운데에 바깥에서 배관 끝이 하나씩 닿고 판 끝에는 아무
      선도 닿지 않으면 플랜지 연결이다. 판은 기호 묶기가 끝난 뒤 지우고 두 배관 끝을 잇는다(배관이 끊기지 않게).
      먼저 지우면 판에 닿아 있던 배관 끝이 떠 보여 장식선으로 흡수된다.
    - 두 판 사이에 둥근 점 하나와 그 점을 지나는 빗금이 있으면 버터플라이, 빗금 없이 점이나 원 하나만 있으면 볼 밸브다.
      바로 바깥의 플랜지 판까지 한 기호로 묶는다.
    - 두 판 사이 가운데에 판보다 짧은 나란한 선 하나만 있고 두 판 가운데에 바깥에서 배관 끝이 하나씩 닿으면 오리피스
      상자(_orifice_box, 범례 1.7-1 1/4 RESTRICTION ORIFICE)다. 두 판과 가운데 선을 한 선 기호로 묶는다(판 길이가 짧아
      선 기호 최소 크기에 못 미친다). 판 가운데 말고 다른 자리(판 끝·상자 귀퉁이)에 다른 선이 닿으면 묶지 않는다
      (차압 탭선이 달린 유량 측정 상자, 판 끝에 이어지는 엇갈림 끊긴 배관).
    판 사이에 그 밖의 것(플러그 밸브의 마름모 등)이 있으면 건드리지 않는다."""
    plates = []
    for p in polys:
        if len(p["pts"]) != 2 or p.get("curved"):
            continue
        (x0, y0), (x1, y1) = p["pts"]
        length = math.hypot(x1 - x0, y1 - y0)
        if prm["plate_len_min"] <= length <= prm["plate_len_max"]:
            u = ((x1 - x0) / length, (y1 - y0) / length)
            if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):  # 점 순서와 상관없이 같은 방향(축 부호를 맞춘다)
                u = (-u[0], -u[1])
            plates.append({"p": p, "L": length, "u": u,
                           "c": ((x0 + x1) / 2, (y0 + y1) / 2)})
    if not plates:
        return [], polys, markers, []
    reach = prm["valve_gap_max"]
    cell = collections.defaultdict(list)
    for i, a in enumerate(plates):
        cell[(int(a["c"][0] // reach), int(a["c"][1] // reach))].append(i)

    def axial(a, q):  # 판 a의 법선(배관 축) 방향 좌표
        return (q[0] - a["c"][0]) * -a["u"][1] + (q[1] - a["c"][1]) * a["u"][0]

    def lateral(a, q):  # 판 a의 길이 방향 좌표
        return (q[0] - a["c"][0]) * a["u"][0] + (q[1] - a["c"][1]) * a["u"][1]

    nbr = collections.defaultdict(list)
    for i, a in enumerate(plates):
        gx, gy = int(a["c"][0] // reach), int(a["c"][1] // reach)
        for j in (j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in cell[(gx + dx, gy + dy)] if j != i):
            b = plates[j]
            if abs(a["u"][0] * b["u"][1] - a["u"][1] * b["u"][0]) > prm["plate_par_tol"] or \
                    abs(a["L"] - b["L"]) > prm["plate_len_tol"] or abs(lateral(a, b["c"])) > prm["plate_align_tol"]:
                continue
            sep = axial(a, b["c"])
            if 0.5 <= abs(sep) <= reach:
                nbr[i].append((abs(sep), j, sep > 0))
    # 판마다 축 양쪽으로 가장 가까운 이웃 하나씩
    side = {}
    for i, lst in nbr.items():
        for positive in (True, False):
            near = [x for x in lst if x[2] == positive]
            if near:
                side[(i, positive)] = min(near)[1]
    plate_ids = {id(plates[i]["p"]) for i, lst in nbr.items() if lst}  # 짝 판이 있는 것만 판(빗금 반쪽 등은 칸 안 선)
    others = [q for q in polys if id(q) not in plate_ids]
    tol = prm["end_tol"]

    def gap_items(a, b):
        """판 a·b 사이 칸 안의 (선, 표식, 몸체 기호)와 칸을 가로지르는 다른 선이 있는지."""
        lo, hi = sorted((0.0, axial(a, b["c"])))
        half = a["L"] / 2 + prm["plate_touch_tol"]
        pad = prm["plate_touch_tol"]

        def inside(q):
            return lo - pad <= axial(a, q) <= hi + pad and abs(lateral(a, q)) <= half

        def core(q):
            return lo + 0.1 < axial(a, q) < hi - 0.1 and abs(lateral(a, q)) < a["L"] / 2
        lines, crossing = [], []
        for q in others:
            if all(inside(t) for t in q["pts"]):
                lines.append(q)
            elif any(core(t) for t in q["pts"]) or any(core(m) for m in
                                                     (((s[0] + e[0]) / 2, (s[1] + e[1]) / 2) for s, e in _segs(q["pts"]))):
                crossing.append(q)
        dots = [m for m in markers if core(_center(m["bbox"]))]
        bodies = [s for s in syms if s.alive and core(_center(s.bbox))]
        crossing += [d for d in dashes if core(_center(d["bbox"]))]  # 채운 짧은 선(오리피스 표시 등)도 빈칸이 아니다
        return lines, dots, bodies, crossing

    def pipe_end(a, away):
        """판 a 가운데에 바깥(away 쪽, 배관 축 부호)에서 닿는 배관 끝. 하나일 때만 그 (선, 끝 점)."""
        hits = []
        for q in others:
            for k in (0, -1):
                e, nxt = q["pts"][k], q["pts"][1 if k == 0 else -2]
                if math.hypot(e[0] - a["c"][0], e[1] - a["c"][1]) <= prm["plate_touch_tol"]:
                    d = axial(a, nxt)
                    if (d > 0) == away and abs(lateral(a, nxt)) <= 0.3 * abs(d):
                        hits.append((q, e))
        return hits[0] if len(hits) == 1 else None

    def touched(a, allow, branch_ok=False):
        """판 a에 (allow 말고) 다른 선이 닿는지. 오리피스 탭선·계기 지시선이 닿은 판은 플랜지로 보지 않는다.
        branch_ok면 끝이 판 가운데(배관 끝이 닿는 자리)에 닿는 선은 그 자리의 배관 분기로 보고 세지 않는다."""
        seg = a["p"]["pts"]
        return any(q is not None and q not in allow and _poly_dist(q["pts"], seg) <= tol and not (
            branch_ok and any(math.hypot(e[0] - a["c"][0], e[1] - a["c"][1]) <= prm["plate_touch_tol"]
                              for e in (q["pts"][0], q["pts"][-1]))) for q in others)

    def round_dot(m):
        w, h = _w(m["bbox"]), _h(m["bbox"])
        return bool(m.get("curved")) and max(w, h) <= prm["plate_dot_max"] and max(w, h) <= 1.3 * max(min(w, h), 1e-6)

    used, valves, flanges = set(), [], []
    removed_lines, removed_marks = set(), set()

    def flange_out(i, outward):
        """판 i 바깥쪽(outward 부호)에 붙은 플랜지 판 → 그 판 번호. 없으면 None."""
        j = side.get((i, outward))
        if j is None or j in used or side.get((j, not outward)) != i:
            return None
        a = plates[i]
        if abs(axial(a, plates[j]["c"])) > prm["flange_gap_max"]:
            return None
        lines, dots, bodies, crossing = gap_items(a, plates[j])
        return None if lines or dots or bodies or crossing else j

    for i in sorted(range(len(plates)), key=lambda i: plates[i]["p"]["id"]):
        if i in used:
            continue
        j = side.get((i, True))
        if j is None or j in used or side.get((j, False)) != i:
            continue
        a, b = plates[i], plates[j]
        lines, dots, bodies, crossing = gap_items(a, b)
        sep = axial(a, b["c"])
        mid = ((a["c"][0] + b["c"][0]) / 2, (a["c"][1] + b["c"][1]) / 2)
        centred = [m for m in dots if round_dot(m) and math.hypot(*(_center(m["bbox"])[k] - mid[k] for k in (0, 1)))
                   <= prm["plate_touch_tol"]]
        # 구동부 축: 한 끝이 가운데 점에 닿고 판 길이 방향으로 빠져나가는 선. 칸을 가로지르는 선으로 치지 않는다
        # (빗금을 점에서 둘로 나눠 그린 반쪽은 판 길이 안에 머무르므로 축이 아니다)
        stems = [q for q in crossing if centred and any(
            math.hypot(e[0] - _center(centred[0]["bbox"])[0], e[1] - _center(centred[0]["bbox"])[1])
            <= prm["plate_touch_tol"] + max(_w(centred[0]["bbox"]), _h(centred[0]["bbox"])) / 2
            for e in (q["pts"][0], q["pts"][-1])) and max(abs(lateral(a, t)) for t in q["pts"]) > a["L"] / 2 + 1.0]
        if len(crossing) > len(stems):
            continue
        circles = [s for s in bodies if len(s.bodies) == 1 and _is_circle(s.bodies[0], prm)
                   and math.hypot(*(_center(s.bbox)[k] - mid[k] for k in (0, 1))) <= prm["plate_touch_tol"]]
        def diagonal(q):  # 판과도 배관 축과도 나란하지 않은 선(빗금). 점에서 둘로 나눠 그린 반쪽도 같다
            d = (q["pts"][-1][0] - q["pts"][0][0], q["pts"][-1][1] - q["pts"][0][1])
            n = math.hypot(*d)
            return n > 0 and min(abs(d[0] * a["u"][0] + d[1] * a["u"][1]),
                                 abs(-d[0] * a["u"][1] + d[1] * a["u"][0])) > 0.3 * n
        slashes = [q for q in lines if centred and diagonal(q)
                   and _poly_dist(q["pts"], [_center(centred[0]["bbox"])] * 2) <= prm["plate_touch_tol"]]
        valve = None
        if len(centred) == 1 and len(dots) == 1 and not bodies and lines and len(slashes) == len(lines) <= 2:
            valve = "butterfly"
        elif not lines and ((len(centred) == 1 and len(dots) == 1 and not bodies) or
                            (len(circles) == 1 and len(bodies) == 1 and not dots)):
            valve = "ball"
        if valve is not None:
            group = [i, j]
            out_a, out_b = flange_out(i, False), flange_out(j, True)
            group += [k for k in (out_a, out_b) if k is not None]
            used.update(group)
            members = [dict(plates[k]["p"]) for k in group] + [dict(q) for q in lines]
            for q in members:
                q["kind_"] = "poly"
            if circles:
                circles[0].alive = False
                members += circles[0].bodies
            s = _Sym(members, stroke_only=True)
            s.add([m for m in dots], "markers")
            s.plate_valve = valve
            s.plate_center = mid
            valves.append(s)
            removed_lines.update(id(plates[k]["p"]) for k in group)
            removed_lines.update(id(q) for q in lines)
            removed_marks.update(id(m) for m in dots)
            continue
        ea, eb = pipe_end(a, False), pipe_end(b, True)
        # 판 가운데 말고 다른 자리에 선이 닿으면(상자 귀퉁이의 차압 탭선, 판 끝에 이어지는 엇갈림 끊긴 배관) 상자로 보지
        # 않는다. 탭선이 달린 상자는 FE 원과 묶이는 유량 요소이고, 판 끝에 닿은 선은 그 판이 배관 끝인지 흐리게 한다
        if _orifice_box(a, sep, lines, dots, bodies, crossing, prm) and ea and eb and \
                not any(touched(t, (ea[0], eb[0], lines[0]), branch_ok=True) for t in (a, b)):
            used.update((i, j))
            members = [dict(q, kind_="poly") for q in (a["p"], b["p"], lines[0])]
            valves.append(_Sym(members, stroke_only=True))
            removed_lines.update(id(q) for q in (a["p"], b["p"], lines[0]))
            continue
        if lines or dots or bodies or crossing or sep > prm["flange_gap_max"]:
            continue
        if ea is None or eb is None or touched(a, (ea[0],)) or touched(b, (eb[0],)):
            continue
        used.update((i, j))
        flanges.append((a["p"], b["p"], (ea, eb)))
    return (valves, [q for q in polys if id(q) not in removed_lines],
            [m for m in markers if id(m) not in removed_marks], flanges)


CROSSING_JOIN_MAX = 4.0     # 엇갈림으로 끊은 한 배관의 두 조각 사이 간격을 가로지르는 선에 수직으로 잰 값의 상한(pt)
CROSSING_JOIN_REACH = 32.0  # 두 조각 끝 사이 거리 상한(pt). 비스듬히 가로지르는 선(약 7도 이상)까지 본다
CROSSING_JOIN_WIDTH = 1.1   # 두 조각 굵기 비 상한(같은 선)
CROSSING_JOIN_LATERAL = 0.3  # 두 끝이 한 줄 위: 옆으로 어긋난 거리 상한(pt)


def _dash_paths(dashes):
    """스트로크 점선 조각을 원래 경로 순서대로 이은 꺾은선 목록. 조각 사이 빈칸도 곧게 이어 메운다."""
    by_src = collections.defaultdict(list)
    for d in dashes:
        if "src" in d:
            by_src[d["src"]].append(d)
    return [[q for d in sorted(items, key=lambda d: d["seq"]) for q in d["pts"]] for items in by_src.values()]


def _join_crossing_gaps(polys, dashes, syms, prm):
    """엇갈림 표기('LINE NOT CONNECTED': 잇지 않는 선을 끊어 그림)로 끊은 한 배관의 두 조각을 한 선으로 잇는다.
    두 조각의 마주 보는 끝이 굵기가 같고 한 줄 위에 있으며(바깥 방향이 반대) 간격이 end_tol보다 크고
    다른 선(실선이나 점선 경로)이 그 빈칸을 가로지르며, 그 선에 수직으로 잰 빈칸 폭(간격 × 사인)이 CROSSING_JOIN_MAX
    이하이면 한 배관이다. 비스듬히 가로지르는 선일수록 같은 여백을 두려고 빈칸을 길게 끊는다. 두 끝은 다른 선 중간에
    닿거나 기호를 향해 끝나지 않아야 하고(다른 선 끝만 맞댄 모서리와 기호 상자 옆을 나란히 지나는 끝은 괜찮다), 가로지르는 실선이 조각보다 굵으면 잇지 않는다(가는 곁가지가 굵은 주관 양쪽에서 끝난
    자리는 분기다, APR1400 025쪽 1" 관이 주관 x 662를 만나는 자리). 잇지 않으면 끝이 뜬 두 조각이 장식선으로 묶여 선 기호(오리피스 등)가 되거나, 비스듬한
    선 가까이 끝난 두 끝이 그 선의 분기가 된다(APR1400 008쪽: POSRV 배출 상승관이 파일럿 일점쇄선 가로선 자리에서
    2~4pt, y 263.9 배출관이 7.5도로 기운 입구관 자리에서 19pt 끊긴다) → 이은 선 목록."""
    def end(p, k):
        return p["pts"][0] if k == 0 else p["pts"][-1]

    def out_dir(p, k):
        a, b = (p["pts"][1], p["pts"][0]) if k == 0 else (p["pts"][-2], p["pts"][-1])
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        return None if L == 0 else ((b[0] - a[0]) / L, (b[1] - a[1]) / L)

    cell = CROSSING_JOIN_REACH
    grid = collections.defaultdict(list)
    for i, p in enumerate(polys):
        if len(p["pts"]) >= 2 and not p.get("curved"):
            for k in (0, 1):
                e = end(p, k)
                grid[(int(e[0] // cell), int(e[1] // cell))].append((i, k))

    def near_ends(e, r):
        cx, cy = int(e[0] // cell), int(e[1] // cell)
        return [(j, kj) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j, kj in grid.get((cx + dx, cy + dy), ())
                if math.hypot(end(polys[j], kj)[0] - e[0], end(polys[j], kj)[1] - e[1]) <= r]

    lines = [(i, p.get("width"), p["pts"]) for i, p in enumerate(polys)] + \
        [(-1, None, pts) for pts in _dash_paths(dashes)]
    segs = [(o, w, a, b) for o, w, pts in lines for a, b in _segs(pts)]

    def beside_sym(e):
        return _nearest_sym(e, syms, prm["attach_tol"]) is not None

    def toward_sym(e, u):
        # 기호에 닿거나 기호를 향해 끝난 끝. 기호 상자 옆을 나란히 지나 끝난 끝은 그 기호와 상관없다(APR1400 008쪽:
        # MOV 상승관이 TEW 상자 오른쪽 변 2.1pt 옆을 지나 가로관 자리에서 끊긴다)
        f = (e[0] + u[0] * prm["attach_tol"], e[1] + u[1] * prm["attach_tol"])
        return any(s.alive and _poly_box_dist([e, f], s.bbox) <= prm["touch_tol"] for s in syms)

    def free(i, k):
        # 끊어 그린 끝은 다른 선 중간에 닿지 않는다. 판(플랜지·판 밸브)이나 기호 선에 얹힌 끝은 엇갈림이 아니다. 다른 선의
        # 끝만 맞댄 끝(계기 지시선이 꺾여 들어와 끝난 모서리)은 그대로 끊어 그린 끝으로 본다. 이으면 그 모서리가 분기가
        # 된다(APR1400 008쪽: TEW 지시선 끝이 엇갈림 자리 바로 위 상승관 끝에 맞닿는다)
        e, u = end(polys[i], k), out_dir(polys[i], k)
        near = [(j, kj) for j, kj in near_ends(e, prm["end_tol"]) if j != i]
        def into_gap(j, kj):
            # 맞댄 선이 빈칸 쪽으로 뻗으면 빈칸을 메우는 선(겹쳐 그린 배관)이다(APR1400 065쪽 플랜지 자리)
            v = out_dir(polys[j], kj)
            return v is None or -(v[0] * u[0] + v[1] * u[1]) >= 0.5
        mates = {j for j, kj in near if _meets_at_end(e, polys[j]["pts"], end(polys[j], kj)) and not into_gap(j, kj)}
        return len(mates) == len(near) and not toward_sym(e, u) and \
            all(o == i or o in mates or _seg_dist(e, a, b)[0] > prm["touch_tol"] for o, _, a, b in segs)

    def inside_sym(e):
        # 반대 끝이 기호 몸체 깊숙이 든 조각은 기호의 안쪽 선일 수 있다. 이으면 그 선이 다른 기호까지 닿아 두 기호가
        # 한 기호로 합쳐진다(_group_symbols B, APR1400 023쪽)
        return any(s.deep(e, prm) for s in syms)

    def crossed(e, f, u, g, width):
        lo = (min(e[0], f[0]), min(e[1], f[1]))
        hi = (max(e[0], f[0]), max(e[1], f[1]))
        for _, w, a, b in segs:
            if w and w > CROSSING_JOIN_WIDTH * width:
                continue
            if max(a[0], b[0]) < lo[0] or min(a[0], b[0]) > hi[0] or max(a[1], b[1]) < lo[1] or min(a[1], b[1]) > hi[1]:
                continue
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            sin = 0 if L == 0 else abs((b[0] - a[0]) * u[1] - (b[1] - a[1]) * u[0]) / L
            if sin == 0 or g * sin > CROSSING_JOIN_MAX:
                continue
            # 빈칸 ef 안쪽(양 끝 제외)에서 선분 ab(양 끝 포함)와 만나는가. 점선 경로는 조각 끝이 교점에 놓일 수 있다
            den = (f[0] - e[0]) * (b[1] - a[1]) - (f[1] - e[1]) * (b[0] - a[0])
            if den == 0:
                continue
            s = ((a[0] - e[0]) * (b[1] - a[1]) - (a[1] - e[1]) * (b[0] - a[0])) / den
            t = ((a[0] - e[0]) * (f[1] - e[1]) - (a[1] - e[1]) * (f[0] - e[0])) / den
            if 0 < s < 1 and 0 <= t <= 1:
                return True
        return False

    cands = []
    for i, p in enumerate(polys):
        if len(p["pts"]) < 2 or p.get("curved") or not p.get("width"):
            continue
        for k in (0, 1):
            e, u = end(p, k), out_dir(p, k)
            if u is None:
                continue
            for j, kj in near_ends(e, CROSSING_JOIN_REACH):
                q = polys[j]
                if j <= i or q.get("curved") or not q.get("width") or \
                        max(p["width"], q["width"]) > CROSSING_JOIN_WIDTH * min(p["width"], q["width"]):
                    continue
                f, v = end(q, kj), out_dir(q, kj)
                g = math.hypot(f[0] - e[0], f[1] - e[1])
                if v is None or g <= prm["end_tol"] or u[0] * v[0] + u[1] * v[1] > -0.99:
                    continue
                if abs((f[0] - e[0]) * u[1] - (f[1] - e[1]) * u[0]) > CROSSING_JOIN_LATERAL or \
                        (f[0] - e[0]) * u[0] + (f[1] - e[1]) * u[1] <= 0:
                    continue
                # 빈칸 양쪽 끝이 모두 기호 옆이면 그 기호 자리의 빈칸일 수 있어 잇지 않는다(APR1400 134쪽 LS 013 원 옆)
                if crossed(e, f, u, g, p["width"]) and free(i, k) and free(j, kj) and \
                        not (beside_sym(e) and beside_sym(f)) and \
                        not inside_sym(end(p, 1 - k)) and not inside_sym(end(q, 1 - kj)):
                    cands.append((g, (i, k), (j, kj)))
    mate = {}
    for _, a, b in sorted(cands):
        if a not in mate and b not in mate:
            mate[a], mate[b] = b, a
    if not mate:
        return polys
    out = []
    for run in _end_runs(len(polys), mate):
        if len(run) == 1:
            out.append(polys[run[0][0]])
            continue
        pts = [q for m, mk in run for q in (polys[m]["pts"] if mk == 0 else polys[m]["pts"][::-1])]
        out.append(dict(polys[min(m for m, _ in run)], pts=pts, bbox=_bbox_pts(pts)))
    return out


def _group_symbols(cls, prm):
    syms = _cluster_bodies(cls["bodies"], prm)
    polys = _join_crossing_gaps(list(cls["polys"]), cls["dashes"], syms, prm)
    valves, polys, markers, flange_pairs = _plate_assemblies(syms, polys, list(cls["markers"]),
                                                             cls["dashes"], prm)
    fed, polys = _bar_fed_strokes(polys, prm)
    pockets, cls["mouths"], polys = _pockets(polys, prm)
    syms = [s for s in syms if s.alive] + valves + fed + pockets
    for p in polys:
        p["kind_"] = "poly"
    dashes = list(cls["dashes"])
    # 점선 경로 끝점에 끝을 맞댄 선 끝은 떠 있지 않다. 점선이 그 배관을 이어 그린 것이다(_dashed_continuations)
    tips = {e for d in dashes for e in d.get("path_ends", ())}

    def dash_tip(e):
        return any(math.hypot(e[0] - t[0], e[1] - t[1]) <= prm["end_tol"] for t in tips)
    for _ in range(prm["max_iterations"]):
        changed = False
        live = [s for s in syms if s.alive]
        # A. 기호 bbox(여유 포함) 안에 통째로 들어가는 선. 끝이 화살촉이나 다른 기호에 닿는 선은 연결선이라 제외
        rest = []
        for p in polys:
            host = None
            for s in live:
                if s.alive and not s.arrow_only() and all(_inside(q, s.bbox, s.inner_tol(prm)) for q in p["pts"]):
                    if host is None or _w(s.bbox) * _h(s.bbox) < _w(host.bbox) * _h(host.bbox):
                        host = s
            if host is not None:
                ends = (p["pts"][0], p["pts"][-1])
                if any(_inside(e, m["bbox"], prm["end_tol"]) for e in ends for m in markers) or \
                        any(_nearest_sym(e, [t for t in live if t is not host], prm["attach_tol"], prm) for e in ends):
                    host = None
            if host is not None:
                host.add([p], "strokes")
                changed = True
            else:
                rest.append(p)
        polys = rest
        # B. 끝이 몸체 깊숙이 들어간 선(구동부 축 등): 그 기호의 일부, 반대 끝이 닿은 기호와 합친다
        rest = []
        for p in polys:
            ends = (p["pts"][0], p["pts"][-1])
            host = next((s for s in syms if s.alive and any(s.deep(e, prm) for e in ends)), None)
            if host is None:
                rest.append(p)
                continue
            reached = [_nearest_sym(e, [s for s in syms if s is not host], prm["attach_tol"]) for e in ends]
            if any(s is not None and s.seed is not None for s in reached):
                rest.append(p)  # 검정 견본으로 올린 몸통(seed)에 닿은 선은 연결선이다. 그 몸통을 다른 기호에 합치지 않는다
                continue
            host.add([p], "strokes")
            for e in ends:
                other = _nearest_sym(e, [s for s in syms if s is not host], prm["attach_tol"])
                if other is not None:
                    host.merge(other)
            changed = True
        polys = rest
        # C. 끝이 아무 데도 닿지 않는 선 = 장식(스프링·체크밸브 선 등)
        live = [s for s in syms if s.alive]
        decor = [p for p in polys
                 if any(_end_status(p, k, polys, live, markers, prm) is None and not dash_tip(p["pts"][-k])
                        for k in (0, 1))]
        if decor:
            ids = {id(p) for p in decor}
            # 장식선들 사이에 놓인 화살촉(체크밸브 사선 끝 삼각형)도 장식선을 잇는 조각이다. 그림에서 읽으면 사선이 화살촉
            # 앞에서 끊기고 화살촉과 판 사이가 묶음 거리보다 멀어져, 화살촉 없이는 판 하나가 따로 떨어진다. 가까운 장식선들이
            # 이루는 상자 안에 든 화살촉만 잇는다(두 배관 끝 사이의 검은 마름모처럼 선 밖으로 나온 표식은 잇지 않는다)
            near = []
            for m in markers:
                box = None
                for p in decor:
                    if _poly_box_dist(p["pts"], m["bbox"]) <= prm["decor_group_tol"]:
                        box = p["bbox"] if box is None else _union(box, p["bbox"])
                if box and all(_inside(c, box, prm["touch_tol"]) for c in (m["bbox"][:2], m["bbox"][2:])):
                    near.append(m)
            pieces = decor + near

            def linked(i, j):  # i < j: 장식선끼리, 장식선과 화살촉(화살촉끼리는 잇지 않는다)
                if i >= len(decor):
                    return False
                if j >= len(decor):
                    return _poly_box_dist(decor[i]["pts"], pieces[j]["bbox"]) <= prm["decor_group_tol"]
                return _poly_dist(decor[i]["pts"], decor[j]["pts"]) <= prm["decor_group_tol"]
            groups = [[i for i in g if i < len(decor)] for g in _uf_groups(len(pieces), linked)]
            keep = []
            for g in groups:
                items = [decor[i] for i in g]
                box = items[0]["bbox"]
                for it in items[1:]:
                    box = _union(box, it["bbox"])
                touching = [s for s in live if s.alive and
                            min(_poly_box_dist(it["pts"], s.bbox) for it in items) <= prm["attach_tol"]]
                host = None
                for s in (t for t in touching if not t.arrow_only()):
                    out = max(s.bbox[0] - box[0], box[2] - s.bbox[2], s.bbox[1] - box[1], box[3] - s.bbox[3], 0.0)
                    if out <= prm["decor_extent_ratio"] * max(_w(s.core), _h(s.core)):
                        if host is None or _w(s.bbox) * _h(s.bbox) > _w(host.bbox) * _h(host.bbox):
                            host = s
                if host is not None:
                    host.add(items, "strokes")
                    changed = True
                    continue
                # 흡수할 기호가 없으면: 기호에 닿는 선은 연결선으로 남기고, 나머지가 적당한 크기면 선 기호로 묶는다
                free_items = [it for it in items if all(_poly_box_dist(it["pts"], t.bbox) > prm["attach_tol"]
                                                        for t in touching)]
                fbox = None
                for it in free_items:
                    fbox = it["bbox"] if fbox is None else _union(fbox, it["bbox"])
                if fbox and prm["stroke_symbol_min"] <= max(_w(fbox), _h(fbox)) <= prm["stroke_symbol_max"]:
                    syms.append(_Sym(free_items, stroke_only=True))
                    keep += [it for it in items if it not in free_items]
                    changed = True
                else:
                    keep += items  # 끊긴 배관 등: 연결 단계에서 미해결로 남긴다
            polys = [p for p in polys if id(p) not in ids] + keep
            polys.sort(key=lambda p: p["id"])
        # 표식(화살촉·체크밸브 삼각형)과 점선 조각: 기호 bbox 안이면 기호의 일부
        for bucket, name in ((markers, "markers"), (dashes, "dashes")):
            rest = []
            for m in bucket:
                # 스트로크 점선 경로가 한 끝은 기호 상자 안, 다른 끝은 밖이면 그 기호에서 끝나는 점선 배관이다. 그 끝
                # 조각은 기호의 일부가 아니다. 기호에 넣으면 상자가 조각만큼 자라 옆 조각까지 끌어들이고, 모양 서명에
                # 점선 조각이 섞여 사전 견본에 맞지 않는다(APR1400 008쪽 POSRV 파일럿 안전밸브). 두 끝이 다 밖인 경로
                # (기호를 꿰뚫는 점선)의 안쪽 조각은 그대로 기호에 넣어 그 자리에서 사슬을 끊는다(_stroke_chains)
                inside = [s for s in syms if s.alive and
                          _inside((m["bbox"][0], m["bbox"][1]), s.bbox, prm["touch_tol"]) and
                          _inside((m["bbox"][2], m["bbox"][3]), s.bbox, prm["touch_tol"]) and
                          len({_inside(e, s.bbox, prm["touch_tol"]) for e in m.get("path_ends", ())}) < 2]
                # 검정 견본으로 올린 몸통 위의 점(seed)은 그 몸통의 기호로 간다. 그 밖에는 상자에 드는 첫 기호
                own = [s for s in inside if "seed" in m and any(b.get("seed") == m["seed"] for b in s.bodies)]
                host = (own or inside or [None])[0]
                if host is not None:
                    host.add([m], name)
                    changed = True
                else:
                    rest.append(m)
            bucket[:] = rest
        if not changed:
            break
    syms = [s for s in syms if s.alive]
    syms.sort(key=lambda s: (round(s.bbox[1], 2), round(s.bbox[0], 2), s.evidence()[0]))
    # 플랜지 판은 두 판과 양쪽 배관이 모두 낱 선으로 남았을 때만 지우고 잇는다(기호에 흡수됐으면 그대로 둔다)
    loose = {id(p) for p in polys}
    cls["flanges"], cls["bridges"] = [], []
    for a, b, ends in flange_pairs:
        if all(id(x) in loose for x in (a, b) + tuple(q for q, _ in ends)) and \
                all(_nearest_sym(e, syms, prm["attach_tol"]) is None for _, e in ends):
            cls["flanges"] += [a, b]
            cls["bridges"].append(tuple(e for _, e in ends))
    gone = {id(p) for p in cls["flanges"]}
    polys = [p for p in polys if id(p) not in gone]
    return syms, polys, markers, dashes


def _merge_appendages(syms, chains, prm):
    """연결이 하나도 없는 기호가 더 큰 기호 바로 옆(큰 기호 긴 변 × 비율 안)에 있으면 그 기호의 부속(히터 등)으로 합친다."""
    linked = {id(v[1]) for ch in chains for v, _, _ in ch["ends"] if v[0] == "sym"}
    for s in sorted(syms, key=lambda s: _w(s.bbox) * _h(s.bbox)):
        if id(s) in linked or not s.alive or s.seed is not None:
            continue  # 검정 견본으로 올린 몸통(seed)은 배관이 닿지 않아도 제 기호다. 옆 기호의 부속으로 합치지 않는다
        best = None
        for t in syms:
            if t is s or not t.alive or t.seed is not None or _w(t.bbox) * _h(t.bbox) <= _w(s.bbox) * _h(s.bbox):
                continue
            gap = _box_gap(s.bbox, t.bbox)
            if gap <= prm["appendage_gap_ratio"] * max(_w(t.bbox), _h(t.bbox)) and (best is None or gap < best[0]):
                best = (gap, t)
        if best is not None:
            best[1].merge(s)
    return [s for s in syms if s.alive]
