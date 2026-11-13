"""벡터 PDF 어댑터(pdf_vector)의 여러 단계가 함께 쓰는 보조 함수.

상자·선분 기하(_bbox_pts, _seg_dist, _poly_dist 등), 몸체 모양 판별(_is_circle, _is_chevron 등), 묶음 찾기(_uf_groups),
미확인·차단 기록 한 줄(_issue). pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""

import math

# ---------------------------------------------------------------- 기하 보조

def _num(v):
    v = float(v)
    return int(v) if v.is_integer() else round(v, 3)


def _bbox_pts(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _expand(b, t):
    return (b[0] - t, b[1] - t, b[2] + t, b[3] + t)


def _inside(p, b, t=0.0):
    return b[0] - t <= p[0] <= b[2] + t and b[1] - t <= p[1] <= b[3] + t


def _pt_box_dist(p, b):
    dx = max(b[0] - p[0], 0.0, p[0] - b[2])
    dy = max(b[1] - p[1], 0.0, p[1] - b[3])
    return math.hypot(dx, dy)


def _box_gap(a, b):
    dx = max(b[0] - a[2], 0.0, a[0] - b[2])
    dy = max(b[1] - a[3], 0.0, a[1] - b[3])
    return math.hypot(dx, dy)


def _depth(p, b):
    """점이 bbox 안쪽으로 들어간 깊이(밖이면 음수)."""
    return min(p[0] - b[0], b[2] - p[0], p[1] - b[1], b[3] - p[1])


def _w(b):
    return b[2] - b[0]


def _h(b):
    return b[3] - b[1]


def _seg_dist(p, a, b):
    """점 p와 선분 ab 사이 거리, 선분 위 최근점."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    q = (ax + t * dx, ay + t * dy)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q


def _segs(pts):
    return list(zip(pts[:-1], pts[1:]))


def _poly_dist(pts_a, pts_b):
    """두 꺾은선 사이 최소 거리(끝점-선분 기준 근사, 교차하면 0)."""
    best = float("inf")
    for a1, a2 in _segs(pts_a) or [(pts_a[0], pts_a[0])]:
        for b1, b2 in _segs(pts_b) or [(pts_b[0], pts_b[0])]:
            if _seg_cross(a1, a2, b1, b2):
                return 0.0
            for p, (s1, s2) in ((a1, (b1, b2)), (a2, (b1, b2)), (b1, (a1, a2)), (b2, (a1, a2))):
                best = min(best, _seg_dist(p, s1, s2)[0])
    return best


def _seg_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4)


def _poly_box_dist(pts, b):
    """꺾은선과 bbox 사이 최소 거리(선분이 bbox를 지나면 0)."""
    best = min(_pt_box_dist(p, b) for p in pts)
    if best == 0.0:
        return 0.0
    corners = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    for a1, a2 in _segs(pts):
        for e1, e2 in edges:
            if _seg_cross(a1, a2, e1, e2):
                return 0.0
        for c in corners:
            best = min(best, _seg_dist(c, a1, a2)[0])
    return best


# ---------------------------------------------------------------- 묶음 찾기

def _uf_groups(n, linked):
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if linked(i, j):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [groups[k] for k in sorted(groups)]


# ---------------------------------------------------------------- 몸체 모양

def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _is_circle(body, prm):
    b = body["bbox"]
    w, h = _w(b), _h(b)
    return body["closed"] and bool(body.get("curved")) and w > 0 and abs(w - h) <= prm["circle_aspect_tol"] * max(w, h)


def _pt_circle_dist(p, body):
    """점과 원 몸체 사이 거리(원 안이면 0). 원은 상자 네 귀퉁이가 비어 있어 상자 거리보다 멀다."""
    b = body["bbox"]
    c, r = _center(b), (_w(b) + _h(b)) / 4
    return max(0.0, math.hypot(p[0] - c[0], p[1] - c[1]) - r)


def _is_tombstone(body):
    """비석 모양 계기 기호(APR1400 DCD 범례 그림 1.7-1): 위는 반원, 아래는 네모. 닫힌 곡선 하나로 그려지고
    아래 두 모서리가 상자 아래 모서리에, 반원 꼭대기가 상자 위 가운데에 있다. 높이/폭 0.95~1.45."""
    if not (body["closed"] and body.get("curved")):
        return False
    x0, y0, x1, y1 = body["bbox"]
    w, h = x1 - x0, y1 - y0
    if w <= 0 or not 0.95 <= h / w <= 1.45:
        return False
    tol = 0.05 * w
    near = lambda px, py: any(abs(x - px) <= tol and abs(y - py) <= tol for x, y in body["pts"])  # noqa: E731
    return near(x0, y1) and near(x1, y1) and near((x0 + x1) / 2, y0)


def _is_chevron(body):
    """도면 연결 표시 화살표(APR1400 DCD 범례 그림 1.7-1): 꼭짓점 6개짜리 닫힌 직선 도형, 긴 변이 짧은 변의 2.5배
    이상이고 짧은 변 4~14pt(가로·세로 모두). 두 가지 모양이 있다.
    - 같은 그림의 다른 시트: 꼬리가 안으로 파인 갈매기(파인 꼭짓점 정확히 하나)
    - 다른 그림: 양 끝이 뾰족한 볼록 육각형(두 끝 꼭짓점이 짧은 변 가운데)
    파인 꼭짓점이 둘 이상인 도형(9.4.1 등의 세로 펌프 기둥)은 아니다."""
    pts = body["pts"][:-1] if body["pts"][0] == body["pts"][-1] else body["pts"]
    x0, y0, x1, y1 = body["bbox"]
    w, h = x1 - x0, y1 - y0
    short, long_ = min(w, h), max(w, h)
    if not (body["closed"] and not body.get("curved") and len(pts) == 6 and 4 <= short <= 14 and long_ >= 2.5 * short):
        return False
    turns = [(b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
             for a, b, c in zip(pts, pts[1:] + pts[:1], pts[2:] + pts[:2])]
    signs = [t > 0 for t in turns if abs(t) > 1e-6]
    if len(signs) != 6:
        return False
    reflex = min(signs.count(True), signs.count(False))
    if reflex == 1:
        return True
    if reflex:
        return False
    tol = 0.15 * short
    if w >= h:  # 가로: 왼쪽·오른쪽 끝 꼭짓점이 세로 가운데
        tips = [p for p in pts if abs(p[0] - x0) <= tol or abs(p[0] - x1) <= tol]
        return len(tips) == 2 and all(abs(p[1] - (y0 + y1) / 2) <= tol for p in tips)
    tips = [p for p in pts if abs(p[1] - y0) <= tol or abs(p[1] - y1) <= tol]
    return len(tips) == 2 and all(abs(p[0] - (x0 + x1) / 2) <= tol for p in tips)


def _is_triangle(body):
    pts = body["pts"][:-1] if body["pts"][0] == body["pts"][-1] else body["pts"]
    return body["closed"] and not body.get("curved") and len(pts) == 3


# ---------------------------------------------------------------- 미확인·차단 기록

def _issue(lst, check, reason, source_object_id=None, target=None, field=None):
    lst.append({"check": check, "target": target, "source_object_id": source_object_id,
                "field": field, "reason": reason})
