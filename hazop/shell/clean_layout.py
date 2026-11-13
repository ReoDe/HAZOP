"""정리된 보기의 정돈(docs/design/app-shell-web.md §10, 사용자 요구 2026-11-14): 읽은 결과를 원본과 같은 자리에 두되 작은 어긋남을 바로잡아 가지런히 그린다.
Qt를 import하지 않는다. 순수 함수라 시험하기 쉽다.

지키는 것: **위상은 바꾸지 않는다**(그래프에서 이어진 것을 끊지 않고, 이어지지 않은 것을 잇지 않는다). 옮기는 거리는 허용 범위 안이다(`MAX_SHIFT`).

규칙(번호는 사용자 요구 정리 순서)
1 축 맞춤: 기호 중심과 배관 꼭짓점의 거의 같은 x·y를 하나의 값으로(`AXIS_TOL`).
2 직각: 거의 수평·수직인 선분을 정확히 수평·수직으로(`ANGLE_TOL`).
3 기기를 선의 정중앙에: 배관에 붙은 기호의 중심을 붙은 선의 축에, 분기점은 만나는 선의 교점에.
4 선이 기기에 정확히 닿음: 그 기호에 연결된 배관 끝을 기호 연결점(표준 기호 정의의 구멍)에, 설비는 가장자리에.
5 같은 종류는 같은 크기: 같은 kind(같은 방향 무리)는 중앙값 크기로, 설비는 격자(10)로.
6 겹침: 기호끼리 겹치면 정돈 범위 안에서 밀어내고, 못 풀면 센다. 기호와 지나가는 배관의 겹침도 센다.
9 교차: 이어지지 않고 엇갈리는 두 배관은 한쪽에 작은 건너뜀(hops) 자리를 준다.
7·8(글자·화살촉)은 웹이 확대 값에 맞춰 정한다(clean_view.js의 layoutLabels·arrowsAlong).

입력: items(`sheet_items.build_items`의 items), extras(`clean_items.build`의 items), symbols(symbols.json의 symbols).
출력 `tidy(...)`: {"symbols": {id: bbox}, "pipes": {id: {"polyline", "ends"}}, "hops": [{"id", "x", "y"}], "lint": {...}, "moved": 최대 이동 거리}.
`layout_lint(...)`는 정돈 품질을 센다(겹침 종류별, 축 벗어남, 연결점에 안 닿음, 수평·수직 아닌 선분, 같은 kind인데 크기 다름, 이동 거리).
"""

import copy
import math
import statistics

AXIS_TOL = 6.0          # 이 안의 x·y 차이는 하나로 합친다(도면 단위)
ANGLE_TOL = 0.12        # |작은 변| <= max(3, 0.12·긴 변)이면 수평·수직으로 본다
MAX_SHIFT = 16.0        # 겹침을 풀려고 기호를 미는 거리의 허용 상한
CENTER_SHIFT = 48.0     # 기호를 붙은 선의 축에 맞추려고 옮기는 거리의 허용 상한(원본 그림이 기호와 연결점을 어긋나게 그린 경우)
EPS = 0.5               # 같은 값으로 보는 오차
INLINE = ("manual_valve", "isolation_valve", "check_valve", "control_valve", "motor_operated_valve", "damper", "reducer", "orifice", "psv",
          "pipe_cap", "vent", "drain", "test_connection")
FIXED = ("continuation", "annotation")      # 크기·자리를 원본대로 두는 기호(오각형 연결 표시 등)


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


def _ports(sym, bbox, orient):
    p = placement(sym, bbox, orient)
    return [to_world(p, x, y) for x, y, _n in sym.get("ports") or []]


def _cluster(values, tol):
    """1차원 값을 가까운 것끼리 묶어 {옛 값: 묶음 대표값(평균)}. 대표값은 묶인 값들의 평균이다."""
    vs = sorted(set(round(v, 3) for v in values))
    mapping, group = {}, []
    for v in vs:
        if group and v - group[-1] > tol:
            m = sum(group) / len(group)
            for g in group:
                mapping[g] = m
            group = []
        group.append(v)
    if group:
        m = sum(group) / len(group)
        for g in group:
            mapping[g] = m
    return mapping


def _near(a, b, tol=EPS):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- 정돈


def _orthogonalize(line):
    """거의 수평·수직인 선분을 정확히 수평·수직으로(꼭짓점을 평균 높이·평균 x로)."""
    pts = [list(p) for p in line]
    for _ in range(2):
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if dy <= max(3.0, ANGLE_TOL * dx) and dx >= dy:
                a[1] = b[1] = (a[1] + b[1]) / 2
            elif dx <= max(3.0, ANGLE_TOL * dy):
                a[0] = b[0] = (a[0] + b[0]) / 2
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out if len(out) >= 2 else pts


def _end_index(e, line):
    return 0 if e.get("end") == "source" else len(line) - 1


def tidy(items, extras, symbols):
    """정돈한 자료. items·extras는 바꾸지 않는다."""
    sym = {}      # id -> {kind, bbox, orient, category}
    for it in items:
        if it["layer"] != "symbol" or it.get("unknown") or not it.get("kind"):
            continue
        s = symbols.get(it["kind"])
        orient = (extras.get(it["id"]) or {}).get("orient") or {"rot": 0}
        sym[it["id"]] = {"kind": it["kind"], "bbox": list(it["bbox"]), "orient": orient, "category": it.get("category"), "def": s}
    pipes = {}
    for it in items:
        if it["layer"] == "pipe" and it.get("polyline") and len(it["polyline"]) >= 2:
            pipes[it["id"]] = {"line": [list(p) for p in it["polyline"]], "ends": copy.deepcopy((extras.get(it["id"]) or {}).get("ends") or [])}
    original_centers = {i: ((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2) for i, s in sym.items()}

    # 5 같은 종류는 같은 크기
    groups = {}
    for i, s in sym.items():
        if s["kind"] in FIXED or (s["def"] or {}).get("junction"):
            continue
        groups.setdefault((s["kind"], _rot90(s["orient"].get("rot", 0))), []).append(i)
    for (kind, _r), ids in groups.items():
        d = sym[ids[0]]["def"] or {}
        if d.get("fit") == "stretch":
            for i in ids:
                b = sym[i]["bbox"]
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                w, h = max(10, round((b[2] - b[0]) / 10) * 10), max(10, round((b[3] - b[1]) / 10) * 10)
                sym[i]["bbox"] = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
        elif len(ids) > 1:
            mw = statistics.median(sym[i]["bbox"][2] - sym[i]["bbox"][0] for i in ids)
            mh = statistics.median(sym[i]["bbox"][3] - sym[i]["bbox"][1] for i in ids)
            for i in ids:
                b = sym[i]["bbox"]
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                sym[i]["bbox"] = [cx - mw / 2, cy - mh / 2, cx + mw / 2, cy + mh / 2]
    # 2 직각
    for p in pipes.values():
        p["line"] = _orthogonalize(p["line"])
    # 1 축 맞춤: 기호 중심과 배관 꼭짓점의 x·y를 같은 값으로
    # 배관 꼭짓점끼리, 기호 중심끼리 따로 묶는다(배관이 기호 중심에 끌려가지 않게: 기호가 붙은 선의 축으로 가는 것은 아래 3번이다)
    mx = _cluster([pt[0] for p in pipes.values() for pt in p["line"]], AXIS_TOL)
    my = _cluster([pt[1] for p in pipes.values() for pt in p["line"]], AXIS_TOL)
    for p in pipes.values():
        for pt in p["line"]:
            pt[0], pt[1] = mx.get(round(pt[0], 3), pt[0]), my.get(round(pt[1], 3), pt[1])
    free = [s for s in sym.values() if s["kind"] not in FIXED]
    sx = _cluster([(s["bbox"][0] + s["bbox"][2]) / 2 for s in free], AXIS_TOL)
    sy = _cluster([(s["bbox"][1] + s["bbox"][3]) / 2 for s in free], AXIS_TOL)
    for s in free:
        b = s["bbox"]
        dx = sx.get(round((b[0] + b[2]) / 2, 3), (b[0] + b[2]) / 2) - (b[0] + b[2]) / 2
        dy = sy.get(round((b[1] + b[3]) / 2, 3), (b[1] + b[3]) / 2) - (b[1] + b[3]) / 2
        s["bbox"] = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]
    # 3 기기를 선의 정중앙에: 붙은 선분의 축에 중심을 맞춘다(분기점은 교점)
    attached = {}
    for pid, p in pipes.items():
        for e in p["ends"]:
            if e.get("node") in sym and e.get("status") == "connected":
                idx = _end_index(e, p["line"])
                q = p["line"][idx]
                nb = p["line"][1] if idx == 0 else p["line"][-2]
                axis = "h" if abs(nb[1] - q[1]) <= abs(nb[0] - q[0]) else "v"
                attached.setdefault(e["node"], []).append((axis, q))
    for i, s in sym.items():
        if s["kind"] in FIXED or (s["def"] or {}).get("fit") == "stretch" and not (s["def"] or {}).get("junction"):
            continue
        att = attached.get(i)
        if not att:
            continue
        b = s["bbox"]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        d = s["def"] or {}
        if d.get("ports"):                                  # 연결점이 중심에 없는 기호(제어밸브 등)도 연결점이 붙은 선의 축에 놓이게 한다
            ports = _ports(d, b, s["orient"])
            dxs, dys = [], []
            for ax, q in att:
                w = min(ports, key=lambda w: math.hypot(w[0] - q[0], w[1] - q[1]))
                (dxs if ax == "v" else dys).append(q[0] - w[0] if ax == "v" else q[1] - w[1])
            nx = cx + (sum(dxs) / len(dxs) if dxs else 0.0)
            ny = cy + (sum(dys) / len(dys) if dys else 0.0)
        else:
            vx = [q[0] for a, q in att if a == "v"]
            hy = [q[1] for a, q in att if a == "h"]
            nx = sum(vx) / len(vx) if vx else cx
            ny = sum(hy) / len(hy) if hy else cy
        if math.hypot(nx - cx, ny - cy) > CENTER_SHIFT:        # 허용 범위를 넘게 어긋난 기호는 옮기지 않는다(연결점이 멀면 lint가 loose_ends로 센다)
            continue
        for cand in ((nx, ny), (nx, cy), (cx, ny)):                # 옮긴 자리가 다른 배관을 지나면 한 축씩, 그래도 안 되면 옮기지 않는다
            nb = [b[0] + cand[0] - cx, b[1] + cand[1] - cy, b[2] + cand[0] - cx, b[3] + cand[1] - cy]
            if not _hits_other_pipe(nb, i, pipes):
                s["bbox"] = nb
                break
    # 4 선이 기기에 정확히 닿음
    for pid, p in pipes.items():
        line = p["line"]
        for e in p["ends"]:
            s = sym.get(e.get("node"))
            if not s or e.get("status") != "connected":
                continue
            idx = _end_index(e, line)
            q = line[idx]
            d = s["def"] or {}
            if d.get("junction"):
                b = s["bbox"]
                target = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]
            elif d.get("ports"):
                ports = _ports(d, s["bbox"], s["orient"])
                target = min(ports, key=lambda w: math.hypot(w[0] - q[0], w[1] - q[1]))
                if math.hypot(target[0] - q[0], target[1] - q[1]) > 20:
                    continue
            else:                                           # 연결점 정의가 없는 설비: 가장자리로
                b = s["bbox"]
                tx, ty = min(max(q[0], b[0]), b[2]), min(max(q[1], b[1]), b[3])
                if b[0] < q[0] < b[2] and b[1] < q[1] < b[3]:
                    d4 = [(q[0] - b[0], "l"), (b[2] - q[0], "r"), (q[1] - b[1], "t"), (b[3] - q[1], "b")]
                    _, side = min(d4)
                    tx, ty = {"l": (b[0], q[1]), "r": (b[2], q[1]), "t": (q[0], b[1]), "b": (q[0], b[3])}[side]
                target = [tx, ty]
            nb_i = 1 if idx == 0 else len(line) - 2
            nb = line[nb_i]
            horizontal = abs(nb[1] - q[1]) <= abs(nb[0] - q[0])
            line[idx] = [target[0], target[1]]
            if len(line) > 2 or nb_i not in (0, len(line) - 1):
                if horizontal:
                    nb[1] = target[1]
                else:
                    nb[0] = target[0]
    # 2 개 끝이 모두 붙은 두 점 선이 어긋나면 꺾임을 하나 넣어 직각을 지킨다(다른 기호를 지나게 되면 넣지 않고 그대로 둔다)
    for pid, p in pipes.items():
        line = p["line"]
        if len(line) != 2:
            continue
        a, b = line
        if not (abs(a[0] - b[0]) > EPS and abs(a[1] - b[1]) > EPS and (abs(a[0] - b[0]) <= 24 or abs(a[1] - b[1]) <= 24)):
            continue
        mine = {e.get("node") for e in p["ends"] if e.get("node")}
        mxp, myp = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        cands = [[a, [mxp, a[1]], [mxp, b[1]], b], [a, [a[0], myp], [b[0], myp], b]]
        if abs(b[0] - a[0]) < abs(b[1] - a[1]):
            cands.reverse()
        for c in cands:
            if not any(_seg_hits_box(u, v, [s["bbox"][0] + 2, s["bbox"][1] + 2, s["bbox"][2] - 2, s["bbox"][3] - 2])
                       for i, s in sym.items() if i not in mine and not (s["def"] or {}).get("junction") for u, v in _segments(c)):
                p["line"] = c
                break
    # 6 기호끼리 겹침: 작은 쪽을 정돈 범위 안에서 밀어낸다
    ids = sorted(sym)
    for _ in range(3):
        for ai in range(len(ids)):
            for bi in range(ai + 1, len(ids)):
                a, b = sym[ids[ai]], sym[ids[bi]]
                if a["kind"] in FIXED and b["kind"] in FIXED:
                    continue
                ov = _overlap(a["bbox"], b["bbox"])
                if not ov or _contains(a, b):
                    continue
                small = a if _area(a["bbox"]) <= _area(b["bbox"]) else b
                big = b if small is a else a
                ox, oy = ov
                if ox <= oy and ox <= MAX_SHIFT:
                    d = ox if (small["bbox"][0] + small["bbox"][2]) / 2 >= (big["bbox"][0] + big["bbox"][2]) / 2 else -ox
                    small["bbox"] = [small["bbox"][0] + d, small["bbox"][1], small["bbox"][2] + d, small["bbox"][3]]
                elif oy <= MAX_SHIFT:
                    d = oy if (small["bbox"][1] + small["bbox"][3]) / 2 >= (big["bbox"][1] + big["bbox"][3]) / 2 else -oy
                    small["bbox"] = [small["bbox"][0], small["bbox"][1] + d, small["bbox"][2], small["bbox"][3] + d]
    # 9 교차(건너뜀 자리)
    hops = _hops(pipes)
    moved = max([math.hypot(((s["bbox"][0] + s["bbox"][2]) / 2) - original_centers[i][0], ((s["bbox"][1] + s["bbox"][3]) / 2) - original_centers[i][1])
                 for i, s in sym.items()] or [0.0])
    for it in items:                                     # 옮긴 거리는 배관 끝점도 센다
        if it["layer"] == "pipe" and it["id"] in pipes:
            a, b = it["polyline"], pipes[it["id"]]["line"]
            for idx in (0, -1):
                moved = max(moved, math.hypot(a[idx][0] - b[idx][0], a[idx][1] - b[idx][1]))
    out_pipes = {}
    for pid, p in pipes.items():
        ends = p["ends"]
        for e in ends:
            e["point"] = list(p["line"][_end_index(e, p["line"])])
        out_pipes[pid] = {"polyline": p["line"], "ends": ends}
    result = {"symbols": {i: s["bbox"] for i, s in sym.items()}, "pipes": out_pipes, "hops": hops, "moved": round(moved, 2)}
    result["lint"] = layout_lint(items, extras, symbols, result)
    return result


def _hits_other_pipe(bbox, sid, pipes):
    """그 기호에 붙지 않은 배관이 bbox 안을 지나는가."""
    inner = [bbox[0] + 2, bbox[1] + 2, bbox[2] - 2, bbox[3] - 2]
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        return False
    for p in pipes.values():
        if any(e.get("node") == sid for e in p["ends"]):
            continue
        if any(_seg_hits_box(a, b, inner) for a, b in _segments(p["line"])):
            return True
    return False


def _area(b):
    return max(b[2] - b[0], 0) * max(b[3] - b[1], 0)


def _overlap(a, b):
    ox, oy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return (ox, oy) if ox > 1.0 and oy > 1.0 else None


def _contains(a, b):
    """큰 설비가 작은 기호를 품은 경우(예: 용기 안의 표시)는 겹침으로 세지 않는다."""
    for big, small in ((a, b), (b, a)):
        if (big["def"] or {}).get("fit") == "stretch" and big["bbox"][0] <= small["bbox"][0] and big["bbox"][1] <= small["bbox"][1] \
                and big["bbox"][2] >= small["bbox"][2] and big["bbox"][3] >= small["bbox"][3]:
            return True
    return False


def _segments(line):
    return [(line[i], line[i + 1]) for i in range(len(line) - 1)]


def _hops(pipes):
    """이어지지 않고 엇갈리는 두 배관의 교차점. 수평 선분 쪽에 건너뜀 자리를 준다."""
    nodes = {pid: {e.get("node") for e in p["ends"] if e.get("node")} for pid, p in pipes.items()}
    out, seen = [], set()
    ids = sorted(pipes)
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            if nodes[a] & nodes[b]:
                continue
            for s1 in _segments(pipes[a]["line"]):
                for s2 in _segments(pipes[b]["line"]):
                    for h, v, hid in ((s1, s2, a), (s2, s1, b)):
                        if _near(h[0][1], h[1][1]) and _near(v[0][0], v[1][0]):
                            x, y = v[0][0], h[0][1]
                            if min(h[0][0], h[1][0]) + 3 < x < max(h[0][0], h[1][0]) - 3 and min(v[0][1], v[1][1]) + 3 < y < max(v[0][1], v[1][1]) - 3:
                                key = (hid, round(x), round(y))
                                if key not in seen:
                                    seen.add(key)
                                    out.append({"id": hid, "x": round(x, 2), "y": round(y, 2)})
    return out


# ---------------------------------------------------------------- 정돈 품질 세기

def layout_lint(items, extras, symbols, tidied):
    """정돈한 결과의 품질을 센다. 0이 좋다(이동 거리는 허용 범위 안이어야 한다).
    overlap_symbols 기호끼리 겹침 · overlap_pipe_symbol 연결되지 않은 배관이 기호를 지남 · off_axis 인라인 기호가 붙은 선의 축에서 벗어남 ·
    loose_ends 연결 끝이 기호 연결점·가장자리에 안 닿음 · non_orthogonal 수평·수직이 아닌 근사 선분 · size_mismatch 같은 kind인데 크기가 다름 · moved 최대 이동 거리."""
    kinds = {it["id"]: it for it in items if it["layer"] == "symbol"}
    sym = {}
    for i, b in tidied["symbols"].items():
        it = kinds[i]
        sym[i] = {"kind": it["kind"], "bbox": b, "orient": (extras.get(i) or {}).get("orient") or {"rot": 0}, "def": symbols.get(it["kind"])}
    lint = {"overlap_symbols": 0, "overlap_pipe_symbol": 0, "off_axis": 0, "loose_ends": 0, "non_orthogonal": 0, "size_mismatch": 0, "moved": tidied.get("moved", 0)}
    ids = sorted(sym)
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = sym[ids[ai]], sym[ids[bi]]
            if a["kind"] in FIXED and b["kind"] in FIXED:
                continue
            if _overlap(a["bbox"], b["bbox"]) and not _contains(a, b):
                lint["overlap_symbols"] += 1
    for pid, p in tidied["pipes"].items():
        line = p["polyline"]
        for a, b in _segments(line):
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if dx > EPS and dy > EPS and (dx < 24 or dy < 24 or min(dx, dy) <= 0.2 * max(dx, dy)):
                lint["non_orthogonal"] += 1
        mine = {e.get("node") for e in p["ends"] if e.get("node")}
        for e in p["ends"]:
            s = sym.get(e.get("node"))
            if not s or e.get("status") != "connected":
                continue
            q = line[_end_index(e, line)]
            d = s["def"] or {}
            b = s["bbox"]
            if d.get("junction"):
                ok = _near(q[0], (b[0] + b[2]) / 2) and _near(q[1], (b[1] + b[3]) / 2)
            elif d.get("ports"):
                ok = min(math.hypot(w[0] - q[0], w[1] - q[1]) for w in _ports(d, b, s["orient"])) <= 1.0 or \
                    min(math.hypot(w[0] - q[0], w[1] - q[1]) for w in _ports(d, b, s["orient"])) > 20       # 20 넘게 먼 것은 같은 기호의 연결이 아니다(규격: 8 단위 넘으면 port_gap)
            else:
                ok = (b[0] - 1 <= q[0] <= b[2] + 1 and b[1] - 1 <= q[1] <= b[3] + 1) and \
                    (_near(q[0], b[0], 1) or _near(q[0], b[2], 1) or _near(q[1], b[1], 1) or _near(q[1], b[3], 1))
            if not ok:
                lint["loose_ends"] += 1
        for i, s in sym.items():
            if i in mine or (s["def"] or {}).get("junction"):
                continue
            inner = [s["bbox"][0] + 2, s["bbox"][1] + 2, s["bbox"][2] - 2, s["bbox"][3] - 2]
            if inner[2] > inner[0] and inner[3] > inner[1] and any(_seg_hits_box(a, b, inner) for a, b in _segments(line)):
                lint["overlap_pipe_symbol"] += 1
    # 인라인 기호의 축: 붙은 수평 선분의 y, 수직 선분의 x와 중심이 같아야 한다
    att = {}
    for pid, p in tidied["pipes"].items():
        line = p["polyline"]
        for e in p["ends"]:
            if e.get("node") in sym and e.get("status") == "connected":
                idx = _end_index(e, line)
                q, nb = line[idx], (line[1] if idx == 0 else line[-2])
                att.setdefault(e["node"], []).append(("h" if abs(nb[1] - q[1]) <= abs(nb[0] - q[0]) else "v", q))
    for i, a in att.items():
        s = sym[i]
        d = s["def"] or {}
        if s["kind"] in FIXED or d.get("fit") == "stretch" or d.get("junction") or not d.get("ports"):
            continue
        ports = _ports(d, s["bbox"], s["orient"])
        for ax, q in a:
            w = min(ports, key=lambda w: math.hypot(w[0] - q[0], w[1] - q[1]))
            if math.hypot(w[0] - q[0], w[1] - q[1]) <= 20 and ((ax == "v" and not _near(q[0], w[0], 1.0)) or (ax == "h" and not _near(q[1], w[1], 1.0))):
                lint["off_axis"] += 1
                break
    by = {}
    for i, s in sym.items():
        if s["kind"] in FIXED or (s["def"] or {}).get("junction") or (s["def"] or {}).get("fit") == "stretch":
            continue
        by.setdefault((s["kind"], _rot90(s["orient"].get("rot", 0))), set()).add((round(s["bbox"][2] - s["bbox"][0], 1), round(s["bbox"][3] - s["bbox"][1], 1)))
    lint["size_mismatch"] = sum(len(v) - 1 for v in by.values() if len(v) > 1)
    return lint


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
