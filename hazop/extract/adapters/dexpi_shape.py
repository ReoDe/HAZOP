"""DEXPI 기호 모양을 도면에 놓는 셈: 모양의 크기 × 배율 × 뒤집기 × 회전 -> 도면에서 차지하는 상자(HZ-PLN-22 §5.3·§6.7).
읽기(dexpi_read)와 쓰기(hazop.export.dexpi_diagram)가 같은 셈을 쓴다. XML은 다루지 않는다.

좌표는 위가 0이고 y가 아래로 커진다. 모양을 배율만큼 늘이고, 뒤집기(x의 부호)를 한 다음, 회전 각도(도)만큼 화면에서 시계 방향으로 돌려
자리에 놓는다. 차례와 방향은 2.0.1 Reference P&ID의 기호와 노드 위치로 확인했다(뒤집힌 각형 안전밸브의 출구, 270도로 놓인 구동부의 끝).
"""

import collections
import math

Bounds = collections.namedtuple("Bounds", "x0 y0 x1 y1 stroke")  # 모양 안 좌표의 상자와 가장 굵은 선(없으면 0)
Placement = collections.namedtuple("Placement", "x y scale_x scale_y rotation mirrored")

UNIT = Bounds(-0.5, -0.5, 0.5, 0.5, 0.0)  # 내보내는 모양: 가운데가 원점인 1 × 1 상자
_RIGHT = {0.0: (1.0, 0.0), 90.0: (0.0, 1.0), 180.0: (-1.0, 0.0), 270.0: (0.0, -1.0)}
THIN = 1e-9


def is_right(rotation):
    return rotation % 360.0 in _RIGHT


def quarter(rotation):
    """가로와 세로가 바뀌는 회전(90·270도)인가."""
    return rotation % 360.0 in (90.0, 270.0)


def _finite(values):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def local_size(bounds, p):
    """회전하기 전의 (너비, 높이). 선 하나로 그린 모양은 선 굵기를 두께로 본다."""
    w, h = (bounds.x1 - bounds.x0) * p.scale_x, (bounds.y1 - bounds.y0) * p.scale_y
    return (w if w > THIN else bounds.stroke), (h if h > THIN else bounds.stroke)


def placed(bounds, p):
    """놓인 상자 (x, y, 너비, 높이). 배율이 0 이하이거나 값이 수가 아니거나 점 하나짜리 모양이면 None."""
    if not _finite((p.x, p.y, p.scale_x, p.scale_y, p.rotation)) or p.scale_x <= 0 or p.scale_y <= 0:
        return None
    if (bounds.x1 - bounds.x0) * p.scale_x <= THIN and (bounds.y1 - bounds.y0) * p.scale_y <= THIN:
        return None
    turn = p.rotation % 360.0
    c, s = _RIGHT.get(turn) or (math.cos(math.radians(turn)), math.sin(math.radians(turn)))
    flip = -1.0 if p.mirrored else 1.0
    corners = [(x * p.scale_x * flip, y * p.scale_y) for x in (bounds.x0, bounds.x1) for y in (bounds.y0, bounds.y1)]
    xs, ys = [p.x + x * c - y * s for x, y in corners], [p.y + x * s + y * c for x, y in corners]
    x0, y0, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    if w <= THIN:
        x0, w = x0 - bounds.stroke / 2.0, bounds.stroke
    if h <= THIN:
        y0, h = y0 - bounds.stroke / 2.0, bounds.stroke
    return (x0, y0, w, h) if _finite((x0, y0, w, h)) else None


def ellipse_points(center, a, b, rotation, start, end):
    """타원호(start에서 end까지 각도가 커지는 쪽)의 두 끝과 그 사이 축 끝점. 점은 가운데 + (a cos, b sin)이고 y는 아래로 커진다(2.0.1 Reference
    P&ID의 접시형 머리와 계기 풍선의 호가 이어진 직선과 만나는 것으로 확인). 값이 수가 아니면 빈 목록."""
    if not _finite((center[0], center[1], a, b, rotation, start, end)):
        return []
    sweep = end - start if 0.0 <= end - start <= 360.0 else (end - start) % 360.0
    angles = [start, start + sweep] + [90.0 * k for k in range(math.ceil(start / 90.0), math.floor((start + sweep) / 90.0) + 1)]
    turn = math.radians(rotation)
    out = []
    for t in angles:
        x, y = a * math.cos(math.radians(t)), b * math.sin(math.radians(t))
        out.append((center[0] + x * math.cos(turn) - y * math.sin(turn), center[1] + x * math.sin(turn) + y * math.cos(turn)))
    return out


def unit_placement(box, rotation=0.0, mirrored=False):
    """도면의 상자 (x, y, 너비, 높이)를 1 × 1 모양으로 채우는 놓임. 90·270도면 배율의 가로세로를 바꾼다."""
    x, y, w, h = box
    sx, sy = (h, w) if quarter(rotation) else (w, h)
    return Placement(x + w / 2.0, y + h / 2.0, sx, sy, rotation % 360.0, bool(mirrored))
