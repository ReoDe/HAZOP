"""벡터 PDF 어댑터의 기호 묶기(pdf_vector 설명글 2번).

분류된 원시 요소(몸체·열린 선·표식·점선 조각)를 기호(_Sym)로 묶는다. 겹치는 몸체, 몸체 안 선, 구동부 축,
끝이 뜬 장식선, 플랜지 판 조립(_plate_assemblies), 관계에 닿지 않은 부속 기호 합치기(_merge_appendages)를 다룬다.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""

import collections
import math

from .pdf_vector_common import (
    _union, _inside, _pt_box_dist, _box_gap, _depth, _w, _h, _seg_dist, _segs, _poly_dist, _poly_box_dist,
    _uf_groups, _center, _is_circle, _is_chevron, _pt_circle_dist,
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


def _cut_through(pts, box):
    """꺾은선 pts가 상자의 긴 축 방향으로 상자를 끊기지 않고 지나가면 들어가는 변과 나가는 변에서 나눈 두 조각.
    지나가지 않으면 None. 옆으로 가로지르는 선이나 상자 안에서 끝나는 선은 나누지 않는다."""
    axis = 0 if _w(box) >= _h(box) else 1
    lo, hi, side_lo, side_hi = box[axis], box[axis + 2], box[1 - axis], box[3 - axis]
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


def _plate_assemblies(syms, polys, markers, dashes, prm):
    """배관을 가로지르는 짧은 판(범례 1.7-1 1/4 FLANGED CONNECTION '—| |—', 1.7-1 VALVE SYMBOLS의 BUTTERFLY '|\\●|'·
    BALL '|○|'·'|●|') 찾기 → (밸브 기호 [_Sym], 남은 선, 남은 표식, 플랜지 [(판, 판, (점, 점))]).
    판: 길이 plate_len_min~max의 직선 조각. 같은 길이·나란한 판이 같은 축 위에 있으면 한 줄로 본다.
    - 두 판 사이가 비었고 간격이 flange_gap_max 이하이며, 두 판 가운데에 바깥에서 배관 끝이 하나씩 닿고 판 끝에는 아무
      선도 닿지 않으면 플랜지 연결이다. 판은 기호 묶기가 끝난 뒤 지우고 두 배관 끝을 잇는다(배관이 끊기지 않게).
      먼저 지우면 판에 닿아 있던 배관 끝이 떠 보여 장식선으로 흡수된다.
    - 두 판 사이에 둥근 점 하나와 그 점을 지나는 빗금이 있으면 버터플라이, 빗금 없이 점이나 원 하나만 있으면 볼 밸브다.
      바로 바깥의 플랜지 판까지 한 기호로 묶는다.
    판 사이에 다른 것(오리피스의 짧은 선, 플러그 밸브의 마름모)이 있으면 건드리지 않는다."""
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

    def touched(a, allow):
        """판 a에 (allow 말고) 다른 선이 닿는지. 오리피스 탭선·계기 지시선이 닿은 판은 플랜지로 보지 않는다."""
        seg = a["p"]["pts"]
        return any(q is not None and q not in allow and _poly_dist(q["pts"], seg) <= tol
                   for q in others)

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
        if lines or dots or bodies or crossing or sep > prm["flange_gap_max"]:
            continue
        ea, eb = pipe_end(a, False), pipe_end(b, True)
        if ea is None or eb is None or touched(a, (ea[0],)) or touched(b, (eb[0],)):
            continue
        used.update((i, j))
        flanges.append((a["p"], b["p"], (ea, eb)))
    return (valves, [q for q in polys if id(q) not in removed_lines],
            [m for m in markers if id(m) not in removed_marks], flanges)


def _group_symbols(cls, prm):
    syms = _cluster_bodies(cls["bodies"], prm)
    valves, polys, markers, flange_pairs = _plate_assemblies(syms, list(cls["polys"]), list(cls["markers"]),
                                                             cls["dashes"], prm)
    fed, polys = _bar_fed_strokes(polys, prm)
    syms = [s for s in syms if s.alive] + valves + fed
    for p in polys:
        p["kind_"] = "poly"
    dashes = list(cls["dashes"])
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
                 if any(_end_status(p, k, polys, live, markers, prm) is None for k in (0, 1))]
        if decor:
            ids = {id(p) for p in decor}
            groups = _uf_groups(len(decor), lambda i, j: _poly_dist(decor[i]["pts"], decor[j]["pts"])
                                <= prm["decor_group_tol"])
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
