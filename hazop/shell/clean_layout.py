"""정리된 보기의 정돈(docs/design/app-shell-web.md §10.11, 사용자 요구 2026-11-14): 읽은 결과를 원본과 같은 자리에 두되 작은 어긋남을 바로잡아 가지런히 그린다.
Qt를 import하지 않는다. 순수 함수라 시험하기 쉽다.

원칙: **정돈하다 틀리느니 정돈하지 않는다.** 정돈이 그림의 이어짐(배관 끝이 닿는 기호·배관)을 바꾸거나, 정돈 전에 없던 겹침을 만들거나,
허용 거리보다 멀리 옮기면, 그 묶음(그래프로 이어진 기호·배관 한 덩이)은 정돈을 버리고 읽은 좌표로 그린다.

규칙(§10.11의 순서)
1 허용 범위: 축 맞춤은 `AXIS_TOL`, 기호를 배관 축에 맞추는 이동은 `MOVE_LIMIT`, 겹침 풀기는 `PUSH_LIMIT` 안에서만.
2 직각: 거의 수평·수직인 선분을 정확히 수평·수직으로(`ANGLE_TOL`).
3 오와 열: 배관 꼭짓점끼리, 기호 중심끼리 폭 `AXIS_TOL` 안의 값을 하나로(가장 긴 선분의 값, 없으면 평균). 묶음은 이어 붙지 않는다.
4 인라인 기기는 배관 축 위: 기호 자리는 공정 배관의 축이 정한다. 신호선(계장·전기)은 자리를 정하지 않고 구동부 연결점에 따로 붙는다.
5 같은 kind는 같은 크기.
6 배관 끝은 기호 연결점에: 그래프가 그 끝을 이은 기호의, 읽은 그림에서 그 끝이 닿던 연결점(정돈 전에 한 번 정한다)에만 붙인다.
  열린 끝과 미확인 기호에 붙은 끝은 옮기지 않는다.
7 겹침: 기호끼리 겹치면 작은 쪽을 밀어낸다.
8 엇갈림은 건너뜀(hops).
글자·화살촉은 웹이 확대 값에 맞춰 정한다(clean_view.js의 layoutLabels·arrowsAlong).

입력: items(`sheet_items.build_items`의 items), extras(`clean_items.build`의 items), symbols(symbols.json의 symbols).
출력 `tidy(...)`: {"symbols": {id: bbox}, "pipes": {id: {"polyline", "ends"}}, "hops": [{"id", "x", "y"}], "lint": {...}, "moved", "reverted"}.
`layout_lint(...)`는 정돈 결과의 품질을 §10.11 표의 이름으로 센다.
"""

import copy
import math
import re
import statistics

AXIS_TOL = 6.0          # 한 값으로 맞추는 묶음의 폭 상한(이 거리 넘게 떨어진 값은 같은 묶음이 아니다)
ANGLE_TOL = 0.12        # |작은 변| <= max(3, 0.12·긴 변)이면 수평·수직으로 본다
MOVE_LIMIT = 48.0       # 기호를 붙은 공정 배관의 축에 맞추려고 옮기는 거리 상한(읽은 상자가 표준 기호와 비율이 달라 연결점이 상자 가운데에 없는 경우, 예: drawio 펌프)
PUSH_LIMIT = 24.0       # 겹침을 풀려고 기호를 미는 거리 상한(읽은 자리에서 잰 전체 이동)
SNAP_LIMIT = 24.0       # 배관 끝을 연결점으로 옮기는 거리 상한(넘으면 옮기지 않고 port_miss로 센다)
PORT_TOL = 0.5          # 연결점에 닿았다고 보는 오차
EPS = 0.5               # 같은 값으로 보는 오차
GRID = 64.0             # 겹침·접촉을 찾는 격자 칸 크기
SIGNAL_TYPES = ("instrument_tap", "signal_electric", "pdf_dashed")       # 기호 자리를 정하지 않는 선(계장 신호·전기 신호)
INSTRUMENTS = ("transmitter", "indicator", "temperature_element", "controller")     # 원 안에 두 줄을 쓰는 계기: 원이 작으면 표준 크기로 키운다
INSTR_MIN = 48.0
CONT_SIZE = (160.0, 44.0)      # 다른 도면 연결 오각형의 표준 크기(원본 글자가 두 줄 들어간다)
FIXED = ("continuation", "annotation")          # 크기 묶음·축 맞춤에서 빼는 기호
BODY_KINDS = ("manual_valve", "isolation_valve", "check_valve", "orifice", "damper", "reducer")      # 대칭 몸통을 가진 인라인 기호(붙은 선이 몸통 가운데를 지나야 한다)


# ---------------------------------------------------------------- 기호 그림 좌표

def _rot90(rot):
    return round(((rot % 360) + 360) % 360 / 90) % 2 == 1


def placement(sym, bbox, orient):
    """clean_view.js의 placement와 같은 계산(그림 좌표 → 도면 좌표)."""
    vw, vh = sym["vb"]
    w, h = max(bbox[2] - bbox[0], 0.5), max(bbox[3] - bbox[1], 0.5)
    rot = (orient or {}).get("rot", 0)
    W, H = (h, w) if _rot90(rot) else (w, h)
    if sym.get("fit") == "stretch":
        sx, sy = W / vw, H / vh
    else:
        sx = sy = min(W / vw, H / vh)
    fx = -1 if (orient or {}).get("flip_h") else 1
    fy = -1 if (orient or {}).get("flip_v") else 1
    return {"cx": (bbox[0] + bbox[2]) / 2, "cy": (bbox[1] + bbox[3]) / 2, "rot": rot, "sx": sx * fx, "sy": sy * fy, "vw": vw, "vh": vh}


def to_world(p, x, y):
    lx, ly = (x - p["vw"] / 2) * p["sx"], (y - p["vh"] / 2) * p["sy"]
    a = math.radians(p["rot"])
    c, s = math.cos(a), math.sin(a)
    return [p["cx"] + lx * c - ly * s, p["cy"] + lx * s + ly * c]


def outline(sym):
    """큰 설비(연결점 정의가 없는 stretch 그림)의 겉모양: 첫 도형을 그림 좌표의 다각형으로 어림한다(사각형·원·M/L/Q/Z 경로). 못 읽으면 None."""
    if not sym or not sym.get("shapes"):
        return None
    tag, a = sym["shapes"][0]
    if tag == "rect":
        x, y, w, h = float(a["x"]), float(a["y"]), float(a["width"]), float(a["height"])
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if tag == "circle":
        cx, cy, r = float(a["cx"]), float(a["cy"]), float(a["r"])
        return [(cx + r * math.cos(t * math.pi / 16), cy + r * math.sin(t * math.pi / 16)) for t in range(32)]
    if tag == "polygon":
        nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", a["points"])]
        return list(zip(nums[0::2], nums[1::2]))
    if tag == "path":
        pts, cur = [], None
        for cmd, args in re.findall(r"([MLQZ])([^MLQZ]*)", a["d"]):
            nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", args)]
            if cmd in "ML" and len(nums) >= 2:
                cur = (nums[0], nums[1])
                pts.append(cur)
            elif cmd == "Q" and len(nums) >= 4 and cur:
                c, e = (nums[0], nums[1]), (nums[2], nums[3])
                for i in range(1, 9):
                    t = i / 8
                    pts.append(((1 - t) ** 2 * cur[0] + 2 * (1 - t) * t * c[0] + t * t * e[0], (1 - t) ** 2 * cur[1] + 2 * (1 - t) * t * c[1] + t * t * e[1]))
                cur = e
        return pts if len(pts) >= 3 else None
    return None


def _world_outline(sym, bbox, orient):
    poly = outline(sym)
    if not poly:
        return None
    p = placement(sym, bbox, orient)
    return [to_world(p, x, y) for x, y in poly]


def _nearest_on_polygon(poly, q):
    """다각형 둘레에서 q에 가장 가까운 점과 거리."""
    best = (None, 1e18)
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2))
        c = (a[0] + t * dx, a[1] + t * dy)
        d = math.hypot(c[0] - q[0], c[1] - q[1])
        if d < best[1]:
            best = (c, d)
    return best


def _ray_hits(poly, o, v):
    """점 o에서 방향 v(양쪽)로 뻗은 직선이 다각형 둘레와 만나는 점들."""
    hits = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ex, ey = b[0] - a[0], b[1] - a[1]
        den = v[0] * ey - v[1] * ex
        if abs(den) < 1e-9:
            continue
        t = ((a[0] - o[0]) * ey - (a[1] - o[1]) * ex) / den
        u = ((a[0] - o[0]) * v[1] - (a[1] - o[1]) * v[0]) / den
        if 0 <= u <= 1:
            hits.append((o[0] + v[0] * t, o[1] + v[1] * t))
    return hits


def _ports(sym, bbox, orient):
    p = placement(sym, bbox, orient)
    return [to_world(p, x, y) for x, y, _n in sym.get("ports") or []]


# ---------------------------------------------------------------- 작은 도구

def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _near(a, b, tol=EPS):
    return abs(a - b) <= tol


def _area(b):
    return max(b[2] - b[0], 0) * max(b[3] - b[1], 0)


def _overlap(a, b):
    ox, oy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return (ox, oy) if ox > 1.0 and oy > 1.0 else None


def _inside(q, b, m=1.0):
    return b[0] + m < q[0] < b[2] - m and b[1] + m < q[1] < b[3] - m


def _segments(line):
    return [(line[i], line[i + 1]) for i in range(len(line) - 1)]


def _seg_box(a, b, m=0.0):
    return (min(a[0], b[0]) - m, min(a[1], b[1]) - m, max(a[0], b[0]) + m, max(a[1], b[1]) + m)


def _seg_dist(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2))
    return math.hypot(a[0] + t * dx - q[0], a[1] + t * dy - q[1])


def _seg_hits_box(a, b, box):
    """선분 a-b가 상자 box 안을 지나는가(Liang–Barsky)."""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - box[0]), (dx, box[2] - a[0]), (-dy, a[1] - box[1]), (dy, box[3] - a[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def _collinear(l1, l2):
    """두 선이 같은 줄에서 겹치는 길이(수평·수직 선분만)."""
    tot = 0.0
    for a, b in _segments(l1):
        for c, d in _segments(l2):
            if _near(a[1], b[1]) and _near(c[1], d[1]) and _near(a[1], c[1]):
                tot += max(0.0, min(max(a[0], b[0]), max(c[0], d[0])) - max(min(a[0], b[0]), min(c[0], d[0])))
            elif _near(a[0], b[0]) and _near(c[0], d[0]) and _near(a[0], c[0]):
                tot += max(0.0, min(max(a[1], b[1]), max(c[1], d[1])) - max(min(a[1], b[1]), min(c[1], d[1])))
    return tot


class _Grid:
    """상자를 격자 칸에 나눠 담아 가까운 것만 찾는다(쪽 하나에 기호 수천 개여도 짝을 모두 보지 않게)."""

    def __init__(self, cell=GRID):
        self.cell = cell
        self.cells = {}

    def _keys(self, b):
        c = self.cell
        for gx in range(math.floor(b[0] / c), math.floor(b[2] / c) + 1):
            for gy in range(math.floor(b[1] / c), math.floor(b[3] / c) + 1):
                yield gx, gy

    def add(self, key, b):
        for k in self._keys(b):
            self.cells.setdefault(k, []).append(key)

    def near(self, b):
        out = set()
        for k in self._keys(b):
            out.update(self.cells.get(k, ()))
        return out


def _end_index(e, line=None):
    """배관 끝의 자리: 0(source) 또는 -1(target). 꺾임을 더하거나 줄여도 끝은 늘 첫·마지막 점이다."""
    return 0 if e.get("end") == "source" else -1


# ---------------------------------------------------------------- 정돈 상태

class _Sheet:
    """정돈하는 동안의 상태. 기호(sym)·미확인 기호 상자(fixed)·배관(pipes)과 읽은 좌표(orig)."""

    def __init__(self, items, extras, symbols):
        self.sym, self.fixed, self.pipes = {}, {}, {}
        for it in items:
            if it["layer"] != "symbol" or not it.get("bbox"):
                continue
            if it.get("unknown") or not it.get("kind"):
                self.fixed[it["id"]] = list(it["bbox"])
                continue
            orient = (extras.get(it["id"]) or {}).get("orient") or {"rot": 0}
            self.sym[it["id"]] = {"kind": it["kind"], "bbox": list(it["bbox"]), "orig": list(it["bbox"]), "orient": orient,
                                  "def": symbols.get(it["kind"]), "pushed": False}
        for it in items:
            if it["layer"] != "pipe" or not it.get("polyline") or len(it["polyline"]) < 2:
                continue
            ex = extras.get(it["id"]) or {}
            ends = copy.deepcopy(ex.get("ends") or [])
            line = [list(p) for p in it["polyline"]]
            att = {}
            for e in ends:
                if e.get("status") == "connected" and e.get("node") in self.sym:
                    att[_end_index(e, line)] = e["node"]
            self.pipes[it["id"]] = {"line": line, "orig": [list(p) for p in line], "ends": ends, "att": att, "port": {},
                                    "signal": ex.get("line_type") in SIGNAL_TYPES,
                                    "nodes": {e.get("node") for e in ends if e.get("node")}}

    def pinned(self, pid, idx):
        """옮기면 안 되는 배관 끝: 열린 끝, 미확인 기호·없는 기호에 붙은 끝."""
        p = self.pipes[pid]
        if idx == len(p["line"]) - 1:
            idx = -1
        return idx in (0, -1) and idx not in p["att"]


def _assign_ports(sh):
    """읽은 그림에서 각 연결 끝이 닿던 연결점을 정돈 전에 한 번 정한다(정돈하며 기호가 움직여도 반대편 연결점으로 넘어가지 않게).
    신호선은 구동부 연결점(이름 actuator)이 있으면 그것만, 공정 배관은 구동부가 아닌 연결점 가운데서 고른다.
    끝이 기호 안(drawio가 기호 가운데에 이은 선)에 있으면 배관이 들어오는 쪽(끝 선분 위에 가까운) 연결점을 고른다.
    한 기호의 여러 끝은 연결점이 모자라지 않는 한 서로 다른 연결점을 받는다."""
    by_sym = {}
    for pid, p in sh.pipes.items():
        for idx, nid in p["att"].items():
            by_sym.setdefault(nid, []).append((pid, idx))
    for nid, ends in sorted(by_sym.items()):
        s = sh.sym[nid]
        d = s["def"] or {}
        if d.get("junction") or not d.get("ports"):
            continue
        names = [pt[2] for pt in d["ports"]]
        act = [k for k, n in enumerate(names) if n == "actuator"]
        world = _ports(d, s["bbox"], s["orient"])
        scored, cands = [], {}
        for pid, idx in ends:
            p = sh.pipes[pid]
            cand = act if (p["signal"] and act) else ([k for k in range(len(names)) if k not in act] or list(range(len(names))))
            cands[(pid, idx)] = cand
            line = p["line"]
            q, nb = line[idx], (line[1] if idx == 0 else line[-2])
            inside = _inside(q, s["bbox"])
            for k in cand:
                score = (_seg_dist(world[k], nb, q), _dist(world[k], q)) if inside else (_dist(world[k], q), 0.0)
                scored.append((score, pid, idx, k))
        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        used, done = set(), set()
        for _score, pid, idx, k in scored:
            if (pid, idx) in done:
                continue
            free = [c for c in cands[(pid, idx)] if c not in used]
            if k in used and free:
                continue
            sh.pipes[pid]["port"][idx] = k
            used.add(k)
            done.add((pid, idx))


def _standardize_sizes(sh):
    """5 같은 종류는 같은 크기(가운데는 그대로)."""
    groups = {}
    for i, s in sh.sym.items():
        if s["kind"] in FIXED or (s["def"] or {}).get("junction"):
            continue
        groups.setdefault((s["kind"], _rot90(s["orient"].get("rot", 0))), []).append(i)
    for (kind, _r), ids in sorted(groups.items()):
        d = sh.sym[ids[0]]["def"] or {}
        if d.get("fit") == "stretch":
            for i in ids:
                b = sh.sym[i]["bbox"]
                cx, cy = _center(b)
                w, h = max(10, round((b[2] - b[0]) / 10) * 10), max(10, round((b[3] - b[1]) / 10) * 10)
                sh.sym[i]["bbox"] = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
        elif len(ids) > 1 or kind in INSTRUMENTS:
            mw = statistics.median(sh.sym[i]["bbox"][2] - sh.sym[i]["bbox"][0] for i in ids)
            mh = statistics.median(sh.sym[i]["bbox"][3] - sh.sym[i]["bbox"][1] for i in ids)
            if kind in INSTRUMENTS:
                mw, mh = max(mw, INSTR_MIN), max(mh, INSTR_MIN)
            for i in ids:
                cx, cy = _center(sh.sym[i]["bbox"])
                sh.sym[i]["bbox"] = [cx - mw / 2, cy - mh / 2, cx + mw / 2, cy + mh / 2]
    for s in sh.sym.values():
        if s["kind"] == "continuation":
            cx, cy = _center(s["bbox"])
            s["bbox"] = [cx - CONT_SIZE[0] / 2, cy - CONT_SIZE[1] / 2, cx + CONT_SIZE[0] / 2, cy + CONT_SIZE[1] / 2]


def _orthogonalize(line, pins):
    """2 거의 수평·수직인 선분을 정확히 수평·수직으로. 옮기면 안 되는 끝(pins)은 그대로 두고 이웃 꼭짓점을 맞춘다."""
    pts = [list(p) for p in line]
    for _ in range(2):
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if dy <= max(3.0, ANGLE_TOL * dx) and dx >= dy:
                k = 1
            elif dx <= max(3.0, ANGLE_TOL * dy):
                k = 0
            else:
                continue
            pa, pb = i in pins, i + 1 in pins
            if pa and pb:
                continue
            v = a[k] if pa else b[k] if pb else (a[k] + b[k]) / 2
            a[k] = b[k] = v
    out = [pts[0]]
    for p in pts[1:-1]:
        if abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    if len(out) >= 2 and abs(pts[-1][0] - out[-1][0]) <= 1e-6 and abs(pts[-1][1] - out[-1][1]) <= 1e-6:
        out.pop()
    out.append(pts[-1])
    return out


def _cluster(entries, tol):
    """1차원 값 묶기. entries: [(값, 무게, 고정)]. 묶음 폭은 tol을 넘지 않는다(이어 붙지 않음).
    대표값: 고정 값이 있으면 그 값, 아니면 무게(선분 길이)가 가장 큰 값, 무게가 없으면 평균. → {round(값, 3): 대표값}."""
    by = {}
    for v, w, pin in entries:
        k = round(v, 3)
        e = by.setdefault(k, [0.0, False])
        e[0] += w
        e[1] = e[1] or pin
    keys = sorted(by)
    mapping, i = {}, 0
    while i < len(keys):
        j = i
        while j + 1 < len(keys) and keys[j + 1] - keys[i] <= tol:
            j += 1
        group = keys[i:j + 1]
        pinned = [k for k in group if by[k][1]]
        if len(group) == 1:
            rep = group[0]
        elif pinned:
            rep = max(pinned, key=lambda k: (by[k][0], -k))
        elif any(by[k][0] > 0 for k in group):
            rep = max(group, key=lambda k: (by[k][0], -k))
        else:
            rep = sum(group) / len(group)
        for k in group:
            mapping[k] = rep
        i = j + 1
    return mapping


def _align_axes(sh):
    """3 오와 열. 배관 꼭짓점끼리, 기호 중심끼리 따로 묶는다(기호가 곁을 지나는 배관 축으로 끌려가 그 배관 위에 앉지 않게)."""
    ex, ey = [], []
    for pid, p in sh.pipes.items():
        line = p["line"]
        for j, q in enumerate(line):
            wx = sum(_dist(line[k], line[k + 1]) for k in (j - 1, j) if 0 <= k < len(line) - 1 and _near(line[k][0], line[k + 1][0], 1e-6))
            wy = sum(_dist(line[k], line[k + 1]) for k in (j - 1, j) if 0 <= k < len(line) - 1 and _near(line[k][1], line[k + 1][1], 1e-6))
            pin = sh.pinned(pid, j)
            ex.append((q[0], wx, pin))
            ey.append((q[1], wy, pin))
    mx, my = _cluster(ex, AXIS_TOL), _cluster(ey, AXIS_TOL)
    for pid, p in sh.pipes.items():
        for j, q in enumerate(p["line"]):
            if not sh.pinned(pid, j):
                q[0], q[1] = mx.get(round(q[0], 3), q[0]), my.get(round(q[1], 3), q[1])
    # 붙은 배관이 정하는 축(세로 배관이 붙으면 x, 가로 배관이 붙으면 y)은 기호끼리 맞추지 않는다: 그 축은 4번(배관 축 위)이 정한다
    held = {}
    for i, ends in _attached(sh).items():
        held[i] = {_end_axis(sh.pipes[pid]["line"], idx) for pid, idx in ends}
    free = [(i, s) for i, s in sorted(sh.sym.items()) if s["kind"] not in FIXED]
    fx = [(i, s) for i, s in free if "v" not in held.get(i, ())]
    fy = [(i, s) for i, s in free if "h" not in held.get(i, ())]
    sx = _cluster([(_center(s["bbox"])[0], 0.0, False) for _i, s in fx], AXIS_TOL)
    sy = _cluster([(_center(s["bbox"])[1], 0.0, False) for _i, s in fy], AXIS_TOL)
    for _i, s in fx:
        b = s["bbox"]
        cx = _center(b)[0]
        dx = sx.get(round(cx, 3), cx) - cx
        s["bbox"] = [b[0] + dx, b[1], b[2] + dx, b[3]]
    for _i, s in fy:
        b = s["bbox"]
        cy = _center(b)[1]
        dy = sy.get(round(cy, 3), cy) - cy
        s["bbox"] = [b[0], b[1] + dy, b[2], b[3] + dy]


def _end_axis(line, idx):
    q = line[idx]
    nb = line[1] if idx == 0 else line[-2]
    return "h" if abs(nb[1] - q[1]) <= abs(nb[0] - q[0]) else "v"


def _attached(sh):
    """기호마다 붙은 배관 끝 [(pid, idx)]."""
    out = {}
    for pid, p in sh.pipes.items():
        for idx, nid in p["att"].items():
            out.setdefault(nid, []).append((pid, idx))
    return out


def _center_on_pipes(sh, pipe_grid):
    """4 기기를 배관 축 위에. 공정 배관이 붙은 기호는 공정 배관만으로 자리를 정한다(신호선은 자리를 정하지 않는다)."""
    for i, ends in sorted(_attached(sh).items()):
        s = sh.sym[i]
        d = s["def"] or {}
        if s["kind"] in FIXED or (d.get("fit") == "stretch" and not d.get("junction")):
            continue
        b = s["bbox"]
        cx, cy = _center(b)
        ports = _ports(d, b, s["orient"]) if d.get("ports") and not d.get("junction") else None
        shift = {"v": ([], []), "h": ([], [])}           # 축마다 (공정 배관이 원하는 이동, 신호선이 원하는 이동)
        for pid, idx in ends:
            p = sh.pipes[pid]
            ax = _end_axis(p["line"], idx)
            q = p["line"][idx]
            if ports is not None:
                if idx not in p["port"]:
                    continue
                w = ports[p["port"][idx]]
                want = q[0] - w[0] if ax == "v" else q[1] - w[1]
            else:
                want = q[0] - cx if ax == "v" else q[1] - cy
            shift[ax][1 if p["signal"] else 0].append(want)

        def pick(ax):
            process, signal = shift[ax]
            vals = process or signal
            return sum(vals) / len(vals) if vals else 0.0
        nx, ny = cx + pick("v"), cy + pick("h")
        if math.hypot(nx - cx, ny - cy) > MOVE_LIMIT:
            continue
        for cand in ((nx, ny), (nx, cy), (cx, ny)):          # 옮긴 자리가 다른 배관을 지나면 한 축씩, 그래도 안 되면 옮기지 않는다
            nb = [b[0] + cand[0] - cx, b[1] + cand[1] - cy, b[2] + cand[0] - cx, b[3] + cand[1] - cy]
            if not _hits_other_pipe(nb, i, sh, pipe_grid):
                s["bbox"] = nb
                break


def _hits_other_pipe(bbox, sid, sh, pipe_grid):
    """그 기호에 붙지 않은 배관이 bbox 안을 지나는가."""
    inner = [bbox[0] + 2, bbox[1] + 2, bbox[2] - 2, bbox[3] - 2]
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        return False
    for pid in pipe_grid.near(inner):
        p = sh.pipes[pid]
        if sid in p["nodes"]:
            continue
        if any(_seg_hits_box(a, b, inner) for a, b in _segments(p["line"])):
            return True
    return False


def _pipe_grid(pipes):
    g = _Grid()
    for pid, p in pipes.items():
        for a, b in _segments(p["line"]):
            g.add(pid, _seg_box(a, b, 1.0))
    return g


def _snap_target(sh, pid, idx):
    """그 끝이 닿을 자리: 분기점은 가운데, 연결점 정의가 있으면 정해 둔 연결점, 큰 설비는 배관이 오던 축 위의 겉모양."""
    p = sh.pipes[pid]
    s = sh.sym[p["att"][idx]]
    d = s["def"] or {}
    line = p["line"]
    q = line[idx]
    if d.get("junction"):
        return list(_center(s["bbox"]))
    if d.get("ports"):
        if idx not in p["port"]:
            return None
        w = _ports(d, s["bbox"], s["orient"])[p["port"][idx]]
        if _port_reachable(line, idx, w) or not outline(d) or d["ports"][p["port"][idx]][2] == "actuator":
            return w
    return _outline_hit(s, line, idx)


def _port_reachable(line, idx, w):
    """연결점이 배관 끝 선분의 축 위에 있는가(끝을 축을 따라 옮겨 닿을 수 있는가)."""
    return _end_axis(line, idx) == "h" and _near(line[idx][1], w[1]) or _end_axis(line, idx) == "v" and _near(line[idx][0], w[0])


def _outline_hit(s, line, idx):
    """배관이 오던 축 위에서 기호의 그려진 겉모양과 만나는 가장 가까운 점. 겉모양이 없으면 상자 가장자리."""
    d = s["def"] or {}
    b = s["bbox"]
    q = line[idx]
    poly = _world_outline(d, b, s["orient"]) if d else None
    if poly:
        nb = line[1] if idx == 0 else line[-2]
        v = (q[0] - nb[0], q[1] - nb[1])
        n = math.hypot(v[0], v[1])
        if n > 1e-6:
            hits = _ray_hits(poly, q, (v[0] / n, v[1] / n))
            if hits:
                return list(min(hits, key=lambda c: _dist(c, q)))
        c, dist = _nearest_on_polygon(poly, q)          # 축이 겉모양을 살짝 비껴가면(축 맞춤으로 0.5 옮겨진 끝 등) 가장 가까운 둘레 점, 축 맞춤 폭 안에서만
        return list(c) if dist <= AXIS_TOL else None
    return [min(max(q[0], b[0]), b[2]), min(max(q[1], b[1]), b[3])]


def _snap_ends(sh):
    """6 선이 기기에 정확히 닿음. 끝을 옮기면 끝 선분이 직각을 지키도록 이웃 꼭짓점을 함께 맞춘다."""
    for pid, p in sh.pipes.items():
        line = p["line"]
        for idx in sorted(p["att"]):
            target = _snap_target(sh, pid, idx)
            q = line[idx]
            s = sh.sym[p["att"][idx]]
            if target is None or (_dist(target, q) > SNAP_LIMIT and not _inside(q, s["bbox"], -1.0) and not _inside(q, s["orig"], -1.0)):
                continue                                    # 기호 안에 그려진 끝(drawio 가운데 연결)은 멀어도 연결점으로 옮긴다
            nb_i = 1 if idx == 0 else len(line) - 2
            nb = line[nb_i]
            horizontal = abs(nb[1] - q[1]) <= abs(nb[0] - q[0])
            line[idx] = [target[0], target[1]]
            if 0 < nb_i < len(line) - 1:
                if horizontal:
                    nb[1] = target[1]
                else:
                    nb[0] = target[0]


def _add_elbows(sh, sym_grid):
    """두 끝이 모두 붙은 두 점 선이 조금 어긋나면 꺾임을 하나 넣어 직각을 지킨다(다른 기호를 지나게 되면 넣지 않는다)."""
    for pid, p in sh.pipes.items():
        line = p["line"]
        if len(line) != 2:
            continue
        a, b = line
        if not (abs(a[0] - b[0]) > EPS and abs(a[1] - b[1]) > EPS and (abs(a[0] - b[0]) <= 24 or abs(a[1] - b[1]) <= 24)):
            continue
        mxp, myp = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        cands = [[a, [mxp, a[1]], [mxp, b[1]], b], [a, [a[0], myp], [b[0], myp], b]]
        if abs(b[0] - a[0]) < abs(b[1] - a[1]):
            cands.reverse()
        for c in cands:
            hit = False
            for u, v in _segments(c):
                for i in sym_grid.near(_seg_box(u, v)):
                    s = sh.sym.get(i)
                    box = s["bbox"] if s else sh.fixed[i]
                    if i in p["nodes"] or (s and (s["def"] or {}).get("junction")):
                        continue
                    if _seg_hits_box(u, v, [box[0] + 2, box[1] + 2, box[2] - 2, box[3] - 2]):
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                p["line"] = c
                break


def _square_diagonals(sh, sym_grid):
    """기운 선분을 꺾임 하나로 수평·수직 두 선분으로 바꾼다(다른 기호를 지나게 되면 그대로 둔다). 끝점은 움직이지 않는다."""
    for pid, p in sh.pipes.items():
        line, out = p["line"], [p["line"][0]]
        for a, b in _segments(line):
            if abs(a[0] - b[0]) > EPS and abs(a[1] - b[1]) > EPS:
                corners = [[b[0], a[1]], [a[0], b[1]]]
                if abs(b[1] - a[1]) > abs(b[0] - a[0]):
                    corners.reverse()
                for c in corners:
                    if not any(_crosses_symbol(sh, sym_grid, p, u, v) for u, v in ((a, c), (c, b))):
                        out.append(c)
                        break
            out.append(b)
        p["line"] = out


def _crosses_symbol(sh, sym_grid, p, u, v):
    for i in sym_grid.near(_seg_box(u, v)):
        s = sh.sym.get(i)
        if i in p["nodes"] or (s and (s["def"] or {}).get("junction")):
            continue
        box = s["bbox"] if s else sh.fixed[i]
        if _seg_hits_box(u, v, [box[0] + 2, box[1] + 2, box[2] - 2, box[3] - 2]):
            return True
    return False


def _sym_grid(sh):
    g = _Grid()
    for i, s in sh.sym.items():
        g.add(i, s["bbox"])
    for i, b in sh.fixed.items():
        g.add(i, b)
    return g


def _contains(big_def, big, small):
    """큰 설비가 작은 기호를 품은 경우(예: 용기 안의 표시)는 겹침으로 세지 않는다."""
    return (big_def or {}).get("fit") == "stretch" and big[0] <= small[0] and big[1] <= small[1] and big[2] >= small[2] and big[3] >= small[3]


def _push_apart(sh):
    """7 기호끼리 겹침: 작은 쪽을 밀어낸다. 읽은 자리에서 잰 이동이 PUSH_LIMIT를 넘으면 밀지 않는다(미확인 기호는 움직이지 않는 장애물)."""
    for _ in range(3):
        g = _sym_grid(sh)
        for ai in sorted(sh.sym):
            a = sh.sym[ai]
            for bi in sorted(g.near(a["bbox"])):
                if bi == ai or (bi in sh.sym and bi < ai):
                    continue
                b = sh.sym.get(bi)
                bb = b["bbox"] if b else sh.fixed[bi]
                ov = _overlap(a["bbox"], bb)
                if not ov or _contains(a["def"], a["bbox"], bb) or (b and _contains(b["def"], bb, a["bbox"])):
                    continue
                if b is None or a["kind"] == "annotation":
                    small, big = (a, bb) if b is None else (b, a["bbox"])
                else:
                    small = a if _area(a["bbox"]) <= _area(bb) else b
                    big = bb if small is a else a["bbox"]
                if small["kind"] == "annotation":
                    continue
                ox, oy = ov
                sb = small["bbox"]
                if ox <= oy:
                    d = ox if _center(sb)[0] >= _center(big)[0] else -ox
                    nb = [sb[0] + d, sb[1], sb[2] + d, sb[3]]
                else:
                    d = oy if _center(sb)[1] >= _center(big)[1] else -oy
                    nb = [sb[0], sb[1] + d, sb[2], sb[3] + d]
                if _dist(_center(nb), _center(small["orig"])) <= PUSH_LIMIT:
                    small["bbox"] = nb
                    small["pushed"] = True


# ---------------------------------------------------------------- 그림 비교(정돈 전후)

class _Picture:
    """한 상태의 그림: 기호 상자·배관 선과 그 격자. 접촉·겹침을 센다."""

    def __init__(self, boxes, lines, nodes, defs):
        self.boxes, self.lines, self.nodes, self.defs = boxes, lines, nodes, defs
        self.sg = _Grid()
        for i, b in boxes.items():
            self.sg.add(i, b)
        self.pg = _Grid()
        for pid, line in lines.items():
            for a, b in _segments(line):
                self.pg.add(pid, _seg_box(a, b, 1.0))

    def contacts(self, pid, idx):
        """배관 끝이 닿은 것 가운데 그래프로 설명되지 않는 것: 다른 기호 안, 같은 기호를 잇지 않은 다른 배관 위."""
        q = self.lines[pid][idx]
        mine = self.nodes[pid]
        out = set()
        box = (q[0] - 1, q[1] - 1, q[0] + 1, q[1] + 1)
        for sid in self.sg.near(box):
            if sid not in mine and _inside(q, self.boxes[sid]):
                out.add(("s", sid))
        for other in self.pg.near(box):
            if other != pid and not (mine & self.nodes[other]):
                if min(_seg_dist(q, a, b) for a, b in _segments(self.lines[other])) < 0.75:
                    out.add(("p", other))
        return out

    def symbol_overlaps(self):
        out = set()
        for a in self.boxes:
            for b in self.sg.near(self.boxes[a]):
                if a < b and _overlap(self.boxes[a], self.boxes[b]) and not _contains(self.defs.get(a), self.boxes[a], self.boxes[b]) \
                        and not _contains(self.defs.get(b), self.boxes[b], self.boxes[a]):
                    out.add((a, b))
        return out

    def pipes_through(self):
        out = set()
        for pid, line in self.lines.items():
            for a, b in _segments(line):
                for sid in self.sg.near(_seg_box(a, b)):
                    if sid in self.nodes[pid] or (self.defs.get(sid) or {}).get("junction"):
                        continue
                    bx = self.boxes[sid]
                    inner = [bx[0] + 2, bx[1] + 2, bx[2] - 2, bx[3] - 2]
                    if inner[2] > inner[0] and inner[3] > inner[1] and _seg_hits_box(a, b, inner):
                        out.add((pid, sid))
        return out

    def pipe_overlaps(self):
        """같은 줄에서 겹치는 배관 쌍(같은 기호를 잇는 배관끼리는 빼고) → {(a, b): 겹친 길이}."""
        out = {}
        for a, line in self.lines.items():
            near = set()
            for u, v in _segments(line):
                near |= self.pg.near(_seg_box(u, v, 1.0))
            for b in near:
                if a < b and not (self.nodes[a] & self.nodes[b]):
                    ov = _collinear(line, self.lines[b])
                    if ov > 2:
                        out[(a, b)] = ov
        return out


def _picture(sh, now):
    """now=False: 읽은 그림, now=True: 지금(정돈한) 그림."""
    boxes = {i: list(s["bbox"] if now else s["orig"]) for i, s in sh.sym.items()}
    boxes.update(sh.fixed)
    lines = {pid: (p["line"] if now else p["orig"]) for pid, p in sh.pipes.items()}
    nodes = {pid: p["nodes"] for pid, p in sh.pipes.items()}
    defs = {i: s["def"] for i, s in sh.sym.items()}
    return _Picture(boxes, lines, nodes, defs)


def _offenders(sh, before, after):
    """정돈이 그림을 나쁘게 만든 대상: 새 접촉, 새 기호 겹침, 새로 기호를 지나는 배관, 새 같은 줄 겹침, 너무 먼 이동, 움직인 고정 끝."""
    bad = set()
    for pid, p in sh.pipes.items():
        for idx in (0, -1):
            new = after.contacts(pid, idx) - before.contacts_cache.get((pid, idx), set())
            if new:
                bad.add(pid)
                bad.update(x for _k, x in new)
            if sh.pinned(pid, idx) and _dist(p["line"][idx], p["orig"][idx]) > 1e-6:
                bad.add(pid)
    for a, b in after.symbol_overlaps() - before.overlaps_cache:
        bad.update((a, b))
    for pid, sid in after.pipes_through() - before.through_cache:
        bad.update((pid, sid))
    for k, v in after.pipe_overlaps().items():
        if v > before.pipe_overlap_cache.get(k, 0.0) + 2:
            bad.update(k)
    for i, s in sh.sym.items():
        limit = PUSH_LIMIT if s["pushed"] else MOVE_LIMIT
        if _dist(_center(s["bbox"]), _center(s["orig"])) > limit + 1e-6:
            bad.add(i)
    for pid, p in sh.pipes.items():
        if len(p["line"]) == len(p["orig"]):
            for j in range(1, len(p["line"]) - 1):
                if _dist(p["line"][j], p["orig"][j]) > PUSH_LIMIT + 1e-6:
                    bad.add(pid)
    return bad


def _components(sh):
    """그래프로 이어진 덩이(기호·미확인 기호·배관). 정돈을 버릴 때 함께 버리는 단위."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for pid, p in sh.pipes.items():
        find(pid)
        for n in p["nodes"]:
            parent[find(n)] = find(pid)
    for i in list(sh.sym) + list(sh.fixed):
        find(i)
    comp = {}
    for x in list(parent):
        comp.setdefault(find(x), set()).add(x)
    return {x: comp[find(x)] for x in parent}


def _verify_and_revert(sh):
    """정돈이 그림을 나쁘게 만든 덩이는 읽은 좌표로 되돌린다. 되돌린 뒤에 또 생긴 것도 없어질 때까지 되풀이한다. → 되돌린 덩이 수."""
    before = _picture(sh, False)
    before.contacts_cache = {(pid, idx): before.contacts(pid, idx) for pid in sh.pipes for idx in (0, -1)}
    before.overlaps_cache = before.symbol_overlaps()
    before.through_cache = before.pipes_through()
    before.pipe_overlap_cache = before.pipe_overlaps()
    comp = _components(sh)
    reverted = set()
    for _ in range(len(comp) + 1):
        bad = _offenders(sh, before, _picture(sh, True))
        groups = {frozenset(comp[x]) for x in bad if x in comp} - reverted
        if not groups:
            break
        for g in groups:
            reverted.add(g)
            for x in g:
                if x in sh.sym:
                    sh.sym[x]["bbox"] = list(sh.sym[x]["orig"])
                    sh.sym[x]["pushed"] = False
                if x in sh.pipes:
                    sh.pipes[x]["line"] = [list(q) for q in sh.pipes[x]["orig"]]
    return len(reverted)


def _hops(lines, nodes):
    """이어지지 않고 엇갈리는 두 배관의 교차점. 수평 선분 쪽에 건너뜀 자리를 준다."""
    g = _Grid()
    for pid, line in lines.items():
        for a, b in _segments(line):
            g.add(pid, _seg_box(a, b, 1.0))
    out, seen = [], set()
    for a in sorted(lines):
        near = set()
        for u, v in _segments(lines[a]):
            near |= g.near(_seg_box(u, v, 1.0))
        for b in sorted(near):
            if b <= a or nodes[a] & nodes[b]:
                continue
            for s1 in _segments(lines[a]):
                for s2 in _segments(lines[b]):
                    for h, v, hid in ((s1, s2, a), (s2, s1, b)):
                        if _near(h[0][1], h[1][1]) and _near(v[0][0], v[1][0]):
                            x, y = v[0][0], h[0][1]
                            if min(h[0][0], h[1][0]) + 3 < x < max(h[0][0], h[1][0]) - 3 and min(v[0][1], v[1][1]) + 3 < y < max(v[0][1], v[1][1]) - 3:
                                key = (hid, round(x), round(y))
                                if key not in seen:
                                    seen.add(key)
                                    out.append({"id": hid, "x": round(x, 2), "y": round(y, 2)})
    out.sort(key=lambda h: (h["id"], h["x"], h["y"]))
    return out


# ---------------------------------------------------------------- 정돈

def tidy(items, extras, symbols):
    """정돈한 자료. items·extras는 바꾸지 않는다."""
    sh = _Sheet(items, extras, symbols)
    _assign_ports(sh)
    _standardize_sizes(sh)
    for pid, p in sh.pipes.items():
        p["line"] = _orthogonalize(p["line"], {k for k in (0, len(p["line"]) - 1) if sh.pinned(pid, k)})
    _align_axes(sh)
    _center_on_pipes(sh, _pipe_grid(sh.pipes))
    _snap_ends(sh)
    _add_elbows(sh, _sym_grid(sh))
    _push_apart(sh)
    _snap_ends(sh)
    _add_elbows(sh, _sym_grid(sh))
    _square_diagonals(sh, _sym_grid(sh))
    reverted = _verify_and_revert(sh)
    lines = {pid: p["line"] for pid, p in sh.pipes.items()}
    hops = _hops(lines, {pid: p["nodes"] for pid, p in sh.pipes.items()})
    moved = max([_dist(_center(s["bbox"]), _center(s["orig"])) for s in sh.sym.values()] or [0.0])
    out_pipes = {}
    for pid, p in sh.pipes.items():
        for e in p["ends"]:
            e["point"] = list(p["line"][_end_index(e)])
        out_pipes[pid] = {"polyline": p["line"], "ends": p["ends"]}
    result = {"symbols": {i: s["bbox"] for i, s in sh.sym.items()}, "pipes": out_pipes, "hops": hops, "moved": round(moved, 2), "reverted": reverted}
    result["lint"] = layout_lint(items, extras, symbols, result)
    return result


# ---------------------------------------------------------------- 정돈 품질 세기

def layout_lint(items, extras, symbols, tidied):
    """정돈한 결과의 품질을 §10.11 표의 이름으로 센다. 0이 좋다(moved는 최대 이동 거리, reverted는 정돈을 버린 덩이 수).
    topology_changed 배관 끝이 정돈 전에 안 닿던 기호·배관에 닿음 · moved_too_far 허용 거리를 넘은 기호·꺾임점·움직인 고정 끝 ·
    off_axis 수평·수직이 아닌 배관 선분 · inline_off_center 연결점이 붙은 선의 축에서 벗어난 기호 · size_mismatch 같은 kind인데 크기가 다름 ·
    port_miss 그래프로 이어진 끝이 그 기호의 연결점·겉모양에 안 닿음(거리 상관없이) · symbol_overlap 기호끼리 겹침(오각형끼리, 미확인 기호 포함) ·
    pipe_through_symbol 이어지지 않은 기호를 지나는 배관 · pipe_overlap 같은 줄에서 겹치는 배관 · crossing_without_hop 건너뜀 없는 엇갈림 ·
    visual_off_axis 몸통 그림의 가운데가 붙은 배관 축에서 벗어남."""
    sh = _Sheet(items, extras, symbols)
    for i, b in tidied["symbols"].items():
        if i in sh.sym:
            sh.sym[i]["bbox"] = list(b)
    for pid, p in tidied["pipes"].items():
        if pid in sh.pipes:
            sh.pipes[pid]["line"] = [list(q) for q in p["polyline"]]
    before, after = _picture(sh, False), _picture(sh, True)
    lint = {"topology_changed": 0, "moved_too_far": 0, "off_axis": 0, "inline_off_center": 0, "size_mismatch": 0, "port_miss": 0,
            "symbol_overlap": 0, "pipe_through_symbol": 0, "pipe_overlap": 0, "crossing_without_hop": 0, "visual_off_axis": 0,
            "moved": tidied.get("moved", 0), "reverted": tidied.get("reverted", 0)}
    for pid, p in sh.pipes.items():
        for idx in (0, -1):
            if after.contacts(pid, idx) - before.contacts(pid, idx):
                lint["topology_changed"] += 1
            if sh.pinned(pid, idx) and _dist(p["line"][idx], p["orig"][idx]) > 1e-6:
                lint["moved_too_far"] += 1
    for i, s in sh.sym.items():
        if _dist(_center(s["bbox"]), _center(s["orig"])) > max(MOVE_LIMIT, PUSH_LIMIT) + 1e-6:
            lint["moved_too_far"] += 1
    lint["symbol_overlap"] = len(after.symbol_overlaps())
    lint["pipe_through_symbol"] = len(after.pipes_through())
    lint["pipe_overlap"] = len(after.pipe_overlaps())
    hop_keys = {(round(h["x"]), round(h["y"])) for h in tidied.get("hops") or []}
    lines = {pid: p["line"] for pid, p in sh.pipes.items()}
    lint["crossing_without_hop"] = sum(1 for h in _hops(lines, {pid: p["nodes"] for pid, p in sh.pipes.items()}) if (round(h["x"]), round(h["y"])) not in hop_keys)
    _assign_ports_from(sh, items, extras, symbols)
    for pid, p in sh.pipes.items():
        line = p["line"]
        for a, b in _segments(line):
            if abs(b[0] - a[0]) > EPS and abs(b[1] - a[1]) > EPS:
                lint["off_axis"] += 1
        for idx in p["att"]:
            s = sh.sym[p["att"][idx]]
            d = s["def"] or {}
            target = _snap_target(sh, pid, idx)
            ok = target is not None and _dist(target, line[idx]) <= PORT_TOL
            if not ok and not d.get("junction") and (not d.get("ports") or idx in p["port"] and not _port_reachable(line, idx, _ports(d, s["bbox"], s["orient"])[p["port"][idx]])):
                poly = _world_outline(d, s["bbox"], s["orient"]) if d else None      # 연결점에 닿을 수 없는 끝(다른 쪽에서 들어온 배관)은 그려진 겉모양에 닿으면 된다
                ok = bool(poly) and _nearest_on_polygon(poly, line[idx])[1] <= PORT_TOL
            if not ok:
                lint["port_miss"] += 1
    for i, ends in _attached(sh).items():
        s = sh.sym[i]
        d = s["def"] or {}
        if s["kind"] in FIXED or d.get("fit") == "stretch" or d.get("junction") or not d.get("ports"):
            continue
        ports = _ports(d, s["bbox"], s["orient"])
        for pid, idx in ends:
            p = sh.pipes[pid]
            if p["signal"] or idx not in p["port"]:
                continue
            q, w = p["line"][idx], ports[p["port"][idx]]
            if outline(d) and _dist(q, w) > PORT_TOL:
                continue                                    # 연결점이 아닌 겉모양에 닿은 끝(port_miss가 따로 본다)
            ax = _end_axis(p["line"], idx)
            if (ax == "v" and not _near(q[0], w[0], PORT_TOL)) or (ax == "h" and not _near(q[1], w[1], PORT_TOL)):
                lint["inline_off_center"] += 1
                break
        if s["kind"] in BODY_KINDS and d.get("shapes"):
            pl = placement(d, s["bbox"], s["orient"])
            pts = []
            for tag, at in d["shapes"]:
                if tag == "line":
                    pts += [(float(at["x1"]), float(at["y1"])), (float(at["x2"]), float(at["y2"]))]
                elif tag in ("polygon", "polyline"):
                    nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", at["points"])]
                    pts += list(zip(nums[0::2], nums[1::2]))
                elif tag == "rect":
                    pts += [(float(at["x"]), float(at["y"])), (float(at["x"]) + float(at["width"]), float(at["y"]) + float(at["height"]))]
            if pts:
                wp = [to_world(pl, x, y) for x, y in pts]
                vcx, vcy = (min(q[0] for q in wp) + max(q[0] for q in wp)) / 2, (min(q[1] for q in wp) + max(q[1] for q in wp)) / 2
                for pid, idx in ends:
                    q, ax = sh.pipes[pid]["line"][idx], _end_axis(sh.pipes[pid]["line"], idx)
                    if (ax == "v" and abs(q[0] - vcx) > 1.5) or (ax == "h" and abs(q[1] - vcy) > 1.5):
                        lint["visual_off_axis"] += 1
                        break
    by = {}
    for i, s in sh.sym.items():
        if s["kind"] in FIXED or (s["def"] or {}).get("junction") or (s["def"] or {}).get("fit") == "stretch":
            continue
        by.setdefault((s["kind"], _rot90(s["orient"].get("rot", 0))), set()).add((round(s["bbox"][2] - s["bbox"][0], 1), round(s["bbox"][3] - s["bbox"][1], 1)))
    lint["size_mismatch"] = sum(len(v) - 1 for v in by.values() if len(v) > 1)
    return lint


def _assign_ports_from(sh, items, extras, symbols):
    """검사용: 연결점 배정은 정돈과 똑같이 읽은 좌표에서 한다."""
    fresh = _Sheet(items, extras, symbols)
    _assign_ports(fresh)
    for pid, p in sh.pipes.items():
        p["port"] = fresh.pipes[pid]["port"]
