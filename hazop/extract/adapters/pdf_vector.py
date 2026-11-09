"""벡터 PDF P&ID → 추출 결과(extraction.json, drawio 경로와 같은 스키마) (T3 W3, 결정 D1).

읽기는 pdfplumber(MIT)만 쓴다(함수 안에서 지연 import). PDF에는 객체 경계가 없으므로 선·곡선·글자를
아래 일반 형상 규칙으로 다시 묶는다. 샘플 파일별 분기는 두지 않는다.

1. 원시 요소: 흰 채움+검은 외곽(닫힌 경로) = 기호 몸체, 검은 채움 작은 조각 = 점선 조각·화살촉(표식),
   열린 검은 선 = 배관·기호 내부선 후보. 페이지 크기의 배경·테두리와 칸이 이어 붙은 표(표제란)는 제외한다.
2. 기호: 겹치는 몸체를 묶고, 몸체 안에 들어가는 선, 끝이 몸체 깊숙이 들어간 선(구동부 축),
   끝이 아무 데도 닿지 않는 선(스프링·체크밸브 선 등 장식)을 기호에 흡수한다. 몸체 없이 장식선만 모인 것은
   선 기호(체크밸브·오리피스·벤트 등)로 둔다.
3. 연결: 남은 열린 선의 끝이 기호 경계(허용 오차 안)·화살촉·다른 선 끝·다른 선 중간에 닿는지로 그래프를 만든다.
   선 끝 3개 이상이 만나거나 선 끝이 다른 선 중간에 닿으면 분기점(tee) 노드로 둔다. 교차만 하는 선은 잇지 않는다.
   점선 조각 사슬은 신호선이며 양 끝이 기호 둘에 닿을 때만 관계로 둔다. 근거가 모자라면 미해결 커넥터로 남긴다.
4. 관계 종류: 점선 = signal_connection, 실선이 계기 원에 닿음 = measurement_connection, 그 밖의 실선 = physical_connection.
   흐름 방향은 만들지 않는다(화살촉은 방향 근거로 쓰지 않음, 미확인 기록).
5. 글자: 단어 → 줄 → 문단. 표 안 글자는 표제란, 선 위(흰 바탕 마스크 안이거나 선과 겹침)는 선 라벨(texts),
   나머지는 가장 가까운 기호 하나에 1:1로 붙인다(거리 상한 있음). 붙지 않은 글자는 texts로 남긴다.
6. 종류: 형상(계기 원, 나비 모양 밸브와 구동부, 스프링, 표식 있는 선 기호) + 일반 P&ID 표기(ISA 계기 문자,
   장비 이름 낱말, 도면 연결 표기 TO/FROM). 근거가 없으면 kind 없음(unclassified)으로 둔다.
7. 태그: 보이는 글자로만 정한다(_assign_tags). 관계마다 실제 선 점(evidence.pdf_path)을 남겨 ② 배경 SVG가 그린다.

좌표: PDF 페이지 pt, 원점 왼쪽 위, x 오른쪽·y 아래쪽 증가(pdfplumber top 기준). drawio 좌표로의 변환은
추정하지 않는다(평가 쪽 align.py가 기준점으로 추정).
"""

import collections
import hashlib
import io
import math
import os
import re
import threading

from hazop import paths
from hazop.kg.docextract import TAG_RE

from .. import drawio, rules, symbols

SCHEMA_VERSION = drawio.SCHEMA_VERSION
SCRIPT_NAME = "hazop.extract.adapters.pdf_vector"
SCRIPT_VERSION = "0.3.0"
RULES_VERSION = "pdf-vector-rules-0.4.0"  # 0.4.0: 보이는 글자로 tag 지정(_assign_tags)
SOURCE_FORMAT = "pdf_vector"
COORDINATE_SPACE = "pdf_page_pt"
UNIT = "pt"

# 형상 규칙 문턱(pt·비율). 샘플 6세트로 조정한 값(표본 내), 근거 evidence/w3-pdf.md §8.
PARAMS = {
    "page_cover_ratio": 0.8,     # 이 비율 이상 페이지를 덮는 채움·외곽은 배경·테두리
    "twin_tol": 0.8,             # 흰 채움과 외곽이 같은 도형인지(bbox 차)
    "dash_thick_max": 1.5,       # 점선 조각: 짧은 변 상한
    "dash_long_max": 8.0,        # 점선 조각: 긴 변 상한
    "dash_corner_max": 4.5,      # 꺾인 점선 모서리 조각(꼭짓점 6개 이상 다각형): 긴 변 상한
    "marker_max": 7.0,           # 화살촉·작은 표식: 긴 변 상한(검은 채움)
    "touch_tol": 0.5,            # 몸체끼리 겹침 판정
    "attach_tol": 2.5,           # 선 끝이 기호 경계에 닿음
    "end_tol": 1.5,              # 선 끝끼리·선 끝과 선 중간이 만남
    "inner_tol_ratio": 0.1,      # 기호 안 선 흡수 여유 = 몸체 긴 변 × 비율 (아래 범위로 자름)
    "inner_tol_min": 2.0,
    "inner_tol_max": 8.0,
    "deep_min": 3.0,             # 선 끝이 몸체 안쪽 깊이(경계에서) 이상이면 기호 내부선(구동부 축 등)
    "deep_ratio": 0.2,           # 깊이 = max(deep_min, 몸체 짧은 변 × 비율)
    "decor_group_tol": 3.0,      # 장식선끼리 묶음 거리
    "decor_extent_ratio": 0.6,   # 장식선이 기호 밖으로 나간 길이 상한 = 기호 긴 변 × 비율
    "stroke_symbol_min": 4.0,    # 선 기호 최소 크기
    "stroke_symbol_max": 60.0,   # 선 기호 최대 크기(넘으면 끊긴 배관으로 본다)
    "dash_gap_max": 3.0,         # 점선 조각 사이 간격 상한
    "dash_attach_tol": 8.0,      # 점선 끝 조각과 기호 사이 거리 상한(점선 끝 빈칸·구동부 여백 포함)
    "label_gap_max": 15.0,       # 글자 문단과 기호 사이 거리 상한
    "bare_code_gap_max": 5.0,    # 쌍점 없는 두 글자 계통 약어를 연결 표시 글자로 볼 거리 상한(바로 옆만)
    "appendage_gap_ratio": 0.1,  # 연결 없는 작은 기호를 옆 큰 기호에 합치는 거리 = 큰 기호 긴 변 × 비율
    "tee_half": 1.0,             # 분기점 노드 bbox 반폭
    "max_iterations": 10,
    "axis_rect_tol": 0.3,        # 축 정렬 사각형 판정: 꼭짓점과 bbox 변의 차 상한
    "table_edge_tol": 0.6,       # 표 칸: 맞닿은 변·같은 행/열 좌표 차 상한
    "circle_aspect_tol": 0.1,    # 원 판정: |폭-높이| ≤ 긴 변 × 비율
    "pipe_cap_max": 15.0,        # 배관 끝막음: 작은 닫힌 몸체 긴 변 상한
    "dash_stroke_step": 4.0,     # 스트로크 점선(dash 배열)을 점선 조각으로 나눌 길이
    "dash_angle_tol": 20.0,      # 채운 점선 조각 이웃: 장축 방향 차 상한(도)
    "dash_collinear_tol": 1.5,   # 채운 점선 조각 이웃: 같은 방향 조각 중심의 직선 밖 거리 상한
    "line_size_tol": 0.5,        # 글자 줄·문단: 글자 크기 차 상한(pt)
    "line_top_ratio": 0.3,       # 같은 줄: 윗변 차 ≤ 글자 크기 × 비율
    "word_gap_ratio": 0.6,       # 같은 줄: 단어 사이 간격 ≤ 글자 크기 × 비율
    "block_gap_min_ratio": -0.2,  # 같은 문단: 줄 사이 간격 ≥ 글자 크기 × 비율
    "block_gap_max_ratio": 0.5,  # 같은 문단: 줄 사이 간격 ≤ 글자 크기 × 비율
    "tick_len_max": 4.0,         # 신호선 빗금(//): 짧은 직선 조각 길이 상한(APR1400 범례 1.7-1 4/4 공압 신호선)
    "tick_host_dist": 1.0,       # 빗금 가운데와 가로지르는 선 사이 거리 상한
    "tick_angle_min": 30.0,      # 빗금과 선 사이 각도 범위(도). 직각(오리피스 판)은 빗금으로 보지 않는다
    "tick_angle_max": 80.0,
    "tick_pair_gap": 3.0,        # 같은 선 위 빗금 둘 이상이 이 거리 안에 나란히 있어야 빗금 묶음
    "tick_host_min": 10.0,       # 빗금이 가로지르는 선의 최소 길이
    "tick_pairs_min": 2,         # 한 선에 빗금 묶음이 이 수 이상이어야 신호선(교차점 옆 빗금 한 묶음으로 배관을 바꾸지 않게)
}

INSTRUMENT_FUNCTION = {"T": "transmitter", "C": "controller", "I": "indicator", "S": "switch",
                       "R": "recorder"}  # ISA 5.1 뒤 글자(기능)
# 장비 이름 낱말 → kind (일반 P&ID 표기). 순서대로 먼저 맞는 것을 쓴다.
EQUIPMENT_WORDS = [
    (("REACTOR", "VESSEL"), "reactor_vessel"),
    (("STEAM", "GENERATOR"), "steam_generator"),
    (("PRESSURIZER",), "pressurizer"),
    (("CONDENSER",), "condenser"),
    (("TURBINE",), "turbine"),
    (("DEMINERALIZER",), "demineralizer"),
    (("FILTER",), "filter"),
    (("EXCHANGER",), "heat_exchanger"),
    (("HX",), "heat_exchanger"),
    (("COOLER",), "heat_exchanger"),
    (("PUMP",), "pump"),
    (("TANK",), "tank"),
    (("VENT",), "vent"),
    (("ATM",), "vent"),
]
CONTINUATION_RE = re.compile(r"^(TO|FROM)\s+\S*\d")
SYSTEM_LABEL_RE = re.compile(r"^([A-Z]{2,3}):\S")  # 'CV:RDT', 'SI:SAFETY INJECTION LINE 3' — 다른 계통 도면으로 가는 표시
# 쌍점 없이 화살표 바로 옆에 두 글자만 쓴 계통 약어(범례 1.7-1 'MS / SHEET 2"A"'). 밸브 위치 약어(범례 같은 쪽)는 뺀다
BARE_SYSTEM_RE = re.compile(r"^(?!(?:FC|FO|FL|LO|LC|LT|NO|NC)$)[A-Z]{2}$")
# ISA 계기 글자(기능 문자 + 번호, 예: 'PT 110'·'PIC 110'). 태그 앞 계통 접두는 글자에 없다.
ISA_LABEL_RE = re.compile(r"([A-Z]{1,4})[ \-]*(\d{1,5}[A-Z]?)")


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


def _is_white(color):
    if color is None:
        return False
    if isinstance(color, (int, float)):
        return color >= 0.95
    try:
        vals = [float(v) for v in color]
    except (TypeError, ValueError):
        return False
    if len(vals) == 4:  # CMYK
        return all(v <= 0.05 for v in vals)
    return bool(vals) and all(v >= 0.95 for v in vals)


# ---------------------------------------------------------------- PDF 읽기 (pdfplumber, 지연 import)

def _subpaths(obj):
    """pdfplumber 경로 객체 → [(점 목록, 닫힘 여부, bbox용 점 목록, 곡선 포함 여부)]."""
    path = obj.get("path")
    if not path:
        pts = [tuple(map(float, p)) for p in obj.get("pts") or []]
        if not pts:
            return []
        closed = obj.get("object_type") == "rect" or (len(pts) >= 3 and pts[0] == pts[-1])
        return [(pts, closed, pts, False)]
    out, cur, ext, closed, curved = [], None, None, False, False
    for cmd in path:
        op = cmd[0]
        if op == "m":
            if cur:
                out.append((cur, closed, ext, curved))
            cur, ext, closed, curved = [tuple(map(float, cmd[1]))], [tuple(map(float, cmd[1]))], False, False
        elif op == "l" and cur is not None:
            cur.append(tuple(map(float, cmd[1])))
            ext.append(cur[-1])
        elif op == "c" and cur is not None:
            ext += [tuple(map(float, c)) for c in cmd[1:]]
            cur.append(tuple(map(float, cmd[-1])))
            curved = True
        elif op == "h" and cur is not None:
            closed = True
    if cur:
        out.append((cur, closed, ext, curved))
    return out


def _dash(value):
    """pdfplumber dash((배열, 위상)) → [배열 목록, 위상] 또는 None(실선). 길이가 0보다 큰 값이 없으면 실선."""
    if not value:
        return None
    try:
        arr, phase = value
        arr = [float(v) for v in (arr or [])]
        phase = float(phase or 0)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v >= 0 for v in arr) or not math.isfinite(phase):
        return None  # 음수·비유한 값은 규격 밖 → 실선으로 취급(0 나눔·무한 반복 방지)
    if not any(v > 0 for v in arr):
        return None
    return [arr, phase]


def _dash_intervals(total, dash):
    """길이 total인 경로에 dash 배열·위상(PDF 8.4.3.6)을 적용한 보이는 구간 [(시작, 끝)] (경로 길이 기준)."""
    arr, phase = dash
    arr = list(arr) * (2 if len(arr) % 2 else 1)  # 홀수 개 배열은 두 번 이어 쓴 것과 같다
    period = sum(arr)
    if period <= 0 or any(v < 0 for v in arr):  # 방어: _dash를 거치지 않은 비정상 입력(무한 반복 방지)
        return []
    pos, idx = phase % period, 0
    while pos >= arr[idx]:  # 위상만큼 무늬를 건너뛴다
        pos -= arr[idx]
        idx = (idx + 1) % len(arr)
    out, at, remaining = [], 0.0, arr[idx] - pos
    while at < total:
        end = min(total, at + remaining)
        if idx % 2 == 0 and end > at:  # 짝수 번째 = 그리는 구간(길이 0은 보이지 않는다)
            out.append((at, end))
        at = end
        idx = (idx + 1) % len(arr)
        remaining = arr[idx]
    return out


def _dash_pieces(pid, pts, dash, step):
    """스트로크 점선 꺾은선의 보이는 구간만 step 길이 이하 조각으로 나눈다. 보이는 구간이 없으면 빈 목록.

    조각에는 원본 경로 ID(src)와 경로 순서(seq)를 남겨, 점선 사슬을 같은 경로 안에서만 잇는다."""
    segs = list(zip(pts[:-1], pts[1:]))
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs]
    starts = [sum(lens[:k]) for k in range(len(lens))]
    total = sum(lens)

    def at(d):
        for (a, b), s0, L in zip(segs, starts, lens):
            if L > 0 and d <= s0 + L + 1e-9:
                t = max(0.0, min(1.0, (d - s0) / L))
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return pts[-1]

    out = []
    for s0, s1 in _dash_intervals(total, dash) if total > 0 else []:
        cuts = sorted({s0, s1} | {v for v in starts[1:] if s0 < v < s1})
        for c0, c1 in zip(cuts[:-1], cuts[1:]):
            n = max(1, int(math.ceil((c1 - c0) / step)))
            for k in range(n):
                p, q = at(c0 + (c1 - c0) * k / n), at(c0 + (c1 - c0) * (k + 1) / n)
                out.append({"id": "%s-d%03d" % (pid, len(out)), "pts": [p, q], "bbox": _bbox_pts([p, q]),
                            "closed": False, "curved": False, "src": pid, "seq": len(out)})
    for d in out:  # 사슬 나누기·경로 간 잇기에 쓰는 원본 경로 정보
        d["nseq"], d["path_ends"] = len(out), (tuple(pts[0]), tuple(pts[-1]))
    return out


def load_page(path, page=0):
    """PDF 한 쪽의 원시 요소. path는 파일 경로 또는 바이너리 파일 객체.
    반환: (page_count, width, height, words, paths)."""
    import pdfplumber  # 지연 import: 전용 venv에는 없을 수 있다(결정 D1)

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        if not 0 <= page < page_count:
            raise ValueError("페이지 %r 없음(전체 %d쪽)" % (page, page_count))
        pg = pdf.pages[page]
        width, height = float(pg.width), float(pg.height)
        words = [{"text": w["text"], "x0": float(w["x0"]), "x1": float(w["x1"]), "top": float(w["top"]),
                  "bottom": float(w["bottom"]), "size": float(w.get("size") or (w["bottom"] - w["top"])),
                  "upright": True}
                 for w in pg.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"])
                 if w.get("upright", True)]
        # 90° 돌린 글자(아래→위로 읽음)는 char_dir_rotated="btt"로 따로 읽는다. 기본값으로 읽으면 거꾸로·한 자씩 끊긴다
        # (APR1400 DCD 'CV:RDT' → 'TDR:VC'). 돌린 글자는 글자마다 size 값이 달라 size로 낱말을 나누지 않고,
        # 줄 높이에 해당하는 낱말 폭을 size로 쓴다.
        for direction, sign in (("btt", 1), ("ttb", -1)):  # 아래→위(글자 행렬 b > 0)와 위→아래(b < 0)를 따로 읽는다
            words += [{"text": w["text"], "x0": float(w["x0"]), "x1": float(w["x1"]), "top": float(w["top"]),
                       "bottom": float(w["bottom"]), "size": float(w["x1"] - w["x0"]), "upright": False,
                       "direction": direction}
                      for w in pg.extract_words(keep_blank_chars=False, use_text_flow=False,
                                                char_dir_rotated=direction, return_chars=True)
                      if not w.get("upright", True) and all((c.get("matrix") or (0, 0))[1] * sign > 0
                                                            for c in w["chars"])]
        prims = []
        for obj in list(pg.lines) + list(pg.rects) + list(pg.curves):
            prims.append({"fill": bool(obj.get("fill")), "stroke": bool(obj.get("stroke", True)),
                          "fill_white": _is_white(obj.get("non_stroking_color")),
                          "stroke_white": _is_white(obj.get("stroking_color")),
                          "dash": _dash(obj.get("dash")), "subpaths": _subpaths(obj),
                          "fine": symbols.sample_subpaths(obj)})  # 기호 사전 서명용: 곡선을 표본점으로 편 점
    return page_count, width, height, words, prims


# ① 미리보기·등록·추출이 같은 쪽을 거듭 분석하지 않도록 최근 분석 결과를 프로세스 안에 둔다(화면 작업 스레드와 공유).
_CACHE_MAX = 8
_cache = collections.OrderedDict()
_cache_lock = threading.Lock()


def analyze_bytes(data, page=0, params=None):
    """PDF 바이트 한 쪽 → (sha256, page_count, width, height, analysis). (해시, 쪽, 문턱)이 같으면 다시 분석하지 않는다.
    analysis는 호출끼리 함께 쓰므로 고치지 않는다(build_extraction은 읽기만 한다)."""
    sha = hashlib.sha256(data).hexdigest()
    key = (sha, page, tuple(sorted((params or {}).items())))
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return (sha,) + hit
    page_count, width, height, words, prims = load_page(io.BytesIO(data), page)
    hit = (page_count, width, height, analyze(width, height, words, prims, params))
    with _cache_lock:
        _cache[key] = hit
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return (sha,) + hit


# ---------------------------------------------------------------- 1. 원시 요소 분류

def _classify_primitives(width, height, prims, prm):
    """→ dict(bodies, polys, markers, dashes, masks, frames, cells). 각 항목에 결정적 id."""
    page_area = width * height
    bodies, polys, markers, dashes, white_fills, frames, outlines, invisible = [], [], [], [], [], [], [], []
    for i, pr in enumerate(prims):
        for k, (pts, closed, ext, curved) in enumerate(pr["subpaths"]):
            if len(pts) < 1:
                continue
            pid = "pdf-path-%04d" % i + ("" if k == 0 else "-%d" % k)
            b = _bbox_pts(ext)
            covers = _w(b) * _h(b) >= prm["page_cover_ratio"] * page_area
            item = {"id": pid, "pts": pts, "bbox": b, "closed": closed and len(pts) >= 3, "curved": curved}
            if pr.get("fine") and k < len(pr["fine"]):
                item["fine"] = pr["fine"][k]
            if pr["fill"] and pr["fill_white"]:
                if not covers:
                    white_fills.append(item)
            elif pr["fill"]:
                small, large = min(_w(b), _h(b)), max(_w(b), _h(b))
                corner = len(pts) >= 6 and not curved and large <= prm["dash_corner_max"]  # 꺾인 점선 모서리(L자)
                if (small <= prm["dash_thick_max"] and large <= prm["dash_long_max"]) or corner:
                    dashes.append(item)
                elif large <= prm["marker_max"]:
                    markers.append(item)
                elif not covers:
                    bodies.append(dict(item, solid=True))
                continue  # 검은 채움은 외곽을 따로 보지 않는다(같은 도형)
            if not pr["stroke"] or pr["stroke_white"]:
                continue
            item = dict(item, id=pid + "s") if pr["fill"] else item
            if item["closed"]:
                if covers or (_w(b) >= prm["page_cover_ratio"] * width and _h(b) >= prm["page_cover_ratio"] * height):
                    frames.append(item)
                else:
                    outlines.append(item)
            elif len(pts) >= 2 and pr.get("dash"):
                pieces = _dash_pieces(item["id"], pts, pr["dash"], prm["dash_stroke_step"])  # 보이는 조각만
                dashes += pieces
                if not pieces:
                    invisible.append(item["id"])
            elif len(pts) >= 2:
                polys.append(item)

    # 검은 채움(화살촉·점선 조각·검은 몸체)과 같은 도형의 외곽선은 채움 쪽으로 본다
    def twin(a, b):
        return max(abs(a["bbox"][j] - b["bbox"][j]) for j in range(4)) <= prm["twin_tol"]
    inked = markers + dashes + bodies
    outlines = [o for o in outlines if not any(twin(o, f) for f in inked)]
    cells = _table_cells(outlines, prm)
    cell_ids = {c["id"] for c in cells}
    bodies += [dict(o, solid=False) for o in outlines if o["id"] not in cell_ids]
    # 흰 채움: 같은 bbox의 외곽(또는 표 칸)이 있으면 그 도형의 채움, 없으면 글자 바탕 마스크
    shapes = [o["bbox"] for o in outlines] + [p["bbox"] for p in polys]
    masks = [f for f in white_fills
             if not any(max(abs(f["bbox"][j] - s[j]) for j in range(4)) <= prm["twin_tol"] for s in shapes)]
    return {"bodies": bodies, "polys": polys, "markers": markers, "dashes": dashes, "masks": masks,
            "frames": frames, "cells": cells, "invisible_dashed": invisible}


def _is_axis_rect(o, tol):
    b = o["bbox"]
    return all(min(abs(p[0] - b[0]), abs(p[0] - b[2])) < tol and min(abs(p[1] - b[1]), abs(p[1] - b[3])) < tol
               for p in o["pts"])


def _table_cells(outlines, prm):
    """변 하나를 통째로 공유하며 이어 붙은 축 정렬 사각형 = 표 칸(표제란 등)."""
    tol = prm["table_edge_tol"]
    rects = [o for o in outlines if _is_axis_rect(o, prm["axis_rect_tol"])]
    cells = set()
    for i, a in enumerate(rects):
        A = a["bbox"]
        for b in rects[i + 1:]:
            B = b["bbox"]
            same_row = abs(A[1] - B[1]) <= tol and abs(A[3] - B[3]) <= tol and \
                (abs(A[2] - B[0]) <= tol or abs(B[2] - A[0]) <= tol)
            same_col = abs(A[0] - B[0]) <= tol and abs(A[2] - B[2]) <= tol and \
                (abs(A[3] - B[1]) <= tol or abs(B[3] - A[1]) <= tol)
            if same_row or same_col:
                cells.update((a["id"], b["id"]))
    return [o for o in rects if o["id"] in cells]


# ---------------------------------------------------------------- 2. 기호 묶기

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
        return _depth(p, self.core) > max(prm["deep_min"], prm["deep_ratio"] * min(_w(self.core), _h(self.core)))

    def evidence(self):
        return sorted(m["id"] for m in self.bodies + self.strokes + self.markers + self.dashes)


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


def _cluster_bodies(bodies, prm):
    for b in bodies:
        b["kind_"] = "body"
    # 연결 표시 화살표는 맞닿은 밸브·축소관 몸체와 한 기호로 묶지 않는다(묶이면 화살표도 밸브도 종류를 잃는다)
    alone = [_is_chevron(b) for b in bodies]
    groups = _uf_groups(len(bodies), lambda i, j: not (alone[i] or alone[j]) and
                        _box_gap(bodies[i]["bbox"], bodies[j]["bbox"]) <= prm["touch_tol"])
    return [_Sym([bodies[i] for i in g]) for g in groups]


def _nearest_sym(p, syms, tol):
    best = None
    for s in syms:
        if not s.alive:
            continue
        d = _pt_box_dist(p, s.bbox)
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


def _line_ticks(polys, prm):
    """신호선 빗금(//) 찾기(범례 1.7-1 4/4 공압 신호선). → (빗금 id 집합, {선 id: [빗금 묶음 가운데]}).
    빗금: 4pt 이하 직선 조각이 긴 열린 선을 비스듬히(30~80도) 실제로 가로지른다(두 끝이 선의 양쪽에 떨어져 있음).
    가장 가까운 선 하나에만 딸린다. 서로 가까운 평행 빗금 2~3개가 묶음 하나이고, 묶음이 tick_pairs_min개 이상인 선만
    신호선 후보다. 선에 한 끝만 닿은 짧은 탭·가지는 가로지르지 않으므로 빗금이 아니다."""
    def length(p):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in _segs(p["pts"]))
    hosts = [p for p in polys if length(p) >= prm["tick_host_min"]]
    lo, hi = math.cos(math.radians(prm["tick_angle_max"])), math.cos(math.radians(prm["tick_angle_min"]))
    cand = collections.defaultdict(list)  # 선 id → [(빗금 가운데, 빗금 방향, 빗금 id)]
    for p in polys:
        tl = length(p)
        if len(p["pts"]) != 2 or not 0.3 <= tl <= prm["tick_len_max"]:
            continue
        (x0, y0), (x1, y1) = p["pts"]
        mid, dx, dy = ((x0 + x1) / 2, (y0 + y1) / 2), x1 - x0, y1 - y0
        best = None  # 가장 가까운 선 하나(교차점 옆 빗금이 배관까지 신호선으로 만들지 않게)
        for q in hosts:
            if q is p:
                continue
            for a, b in _segs(q["pts"]):
                d = _seg_dist(mid, a, b)[0]
                if d > prm["tick_host_dist"] or (best is not None and d >= best[0]):
                    continue
                ex, ey = b[0] - a[0], b[1] - a[1]
                el = math.hypot(ex, ey)
                if el <= 0:
                    continue
                cos = abs(dx * ex + dy * ey) / (math.hypot(dx, dy) * el)
                s0 = (ex * (y0 - a[1]) - ey * (x0 - a[0])) / el  # 두 끝의 선 기준 부호 있는 거리
                s1 = (ex * (y1 - a[1]) - ey * (x1 - a[0])) / el
                if lo <= cos <= hi and s0 * s1 < 0 and min(abs(s0), abs(s1)) >= 0.25 * tl:
                    best = (d, q["id"])
        if best is not None:
            cand[best[1]].append((mid, (dx, dy), p["id"]))
    ticks, marked = set(), {}
    for host, items in cand.items():
        def near(i, j):
            (m, d, _), (m2, d2, _) = items[i], items[j]
            return (math.hypot(m[0] - m2[0], m[1] - m2[1]) <= prm["tick_pair_gap"]
                    and abs(d[0] * d2[1] - d[1] * d2[0]) <= 0.2 * math.hypot(*d) * math.hypot(*d2))
        groups = [g for g in _uf_groups(len(items), near) if 2 <= len(g) <= 3]  # 4개 이상 = 빗금이 아닌 해칭
        if len(groups) >= prm["tick_pairs_min"]:
            for g in groups:
                ticks.update(items[i][2] for i in g)
            marked[host] = [(sum(items[i][0][0] for i in g) / len(g), sum(items[i][0][1] for i in g) / len(g))
                            for g in groups]
    return ticks, marked


def _group_symbols(cls, prm):
    syms = _cluster_bodies(cls["bodies"], prm)
    polys = list(cls["polys"])
    for p in polys:
        p["kind_"] = "poly"
    markers = list(cls["markers"])
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
                        any(_nearest_sym(e, [t for t in live if t is not host], prm["attach_tol"]) for e in ends):
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
                host = next((s for s in syms if s.alive and
                             _inside((m["bbox"][0], m["bbox"][1]), s.bbox, prm["touch_tol"]) and
                             _inside((m["bbox"][2], m["bbox"][3]), s.bbox, prm["touch_tol"])), None)
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
    return syms, polys, markers, dashes


# ---------------------------------------------------------------- 3. 연결

def _attach(p, syms, markers, prm):
    s = _nearest_sym(p, syms, prm["attach_tol"])
    if s is not None:
        return s, "pdf_path_endpoint"
    for m in markers:
        if _inside(p, m["bbox"], prm["end_tol"]):
            s = None
            best = None
            for c in syms:
                d = _box_gap(m["bbox"], c.bbox)
                if d <= prm["attach_tol"] and (best is None or d < best):
                    best, s = d, c
            if s is not None:
                return s, "pdf_arrowhead"
    return None, None


def _build_solid(syms, polys, markers, prm):
    """→ (tees [(x, y)], chains [{pts, ends:[(vertex, point, basis)], evidence}])."""
    # 선 끝 분류
    pieces = [{"pts": list(p["pts"]), "id": p["id"]} for p in polys]
    ends = []  # (piece index, k, point)
    for i, pc in enumerate(pieces):
        ends += [(i, 0, pc["pts"][0]), (i, 1, pc["pts"][-1])]
    att = {}
    free = []
    for i, k, pt in ends:
        s, basis = _attach(pt, syms, markers, prm)
        if s is not None:
            att[(i, k)] = (s, basis)
        else:
            free.append((i, k, pt))
    # 선 끝이 다른 선 중간에 닿으면 그 선을 나눈다(분기)
    splits = {}
    for i, k, pt in free:
        for j, pc in enumerate(pieces):
            if j == i:
                continue
            if min(math.hypot(pt[0] - e[0], pt[1] - e[1]) for e in (pc["pts"][0], pc["pts"][-1])) <= prm["end_tol"]:
                continue
            for s_idx, (a, b) in enumerate(_segs(pc["pts"])):
                d, q = _seg_dist(pt, a, b)
                if d <= prm["end_tol"]:
                    splits.setdefault(j, []).append((s_idx, math.hypot(q[0] - a[0], q[1] - a[1]), q))
                    break
    if splits:
        new_pieces, remap = [], {}
        for j, pc in enumerate(pieces):
            if j not in splits:
                remap[j] = [len(new_pieces)]
                new_pieces.append(pc)
                continue
            cuts = sorted(splits[j])
            cur, seg_start = [pc["pts"][0]], 0
            out = []
            for s_idx, _, q in cuts:
                cur += pc["pts"][seg_start + 1:s_idx + 1] + [q]
                out.append(cur)
                cur, seg_start = [q], s_idx
            cur += pc["pts"][seg_start + 1:]
            out.append(cur)
            remap[j] = []
            for pts in out:
                if len(pts) >= 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 0 or len(pts) > 2:
                    remap[j].append(len(new_pieces))
                    new_pieces.append({"pts": pts, "id": pc["id"]})
        # 붙음 정보 다시 매핑: 원래 첫 끝 → 첫 조각 시작, 원래 끝 → 마지막 조각 끝
        new_att = {}
        for (i, k), v in att.items():
            idx = remap[i][0] if k == 0 else remap[i][-1]
            new_att[(idx, k)] = v
        att, pieces = new_att, new_pieces
    # 자유 끝(기호에 안 붙은 끝) 묶기
    pend = [(i, k, pc["pts"][0] if k == 0 else pc["pts"][-1])
            for i, pc in enumerate(pieces) for k in (0, 1) if (i, k) not in att]
    def same_marker(p, q):  # 두 선 끝 사이에 화살촉 하나가 끼어 있으면 이어진 것으로 본다
        return any(_inside(p, m["bbox"], prm["end_tol"]) and _inside(q, m["bbox"], prm["end_tol"]) for m in markers)
    groups = _uf_groups(len(pend), lambda a, b: math.hypot(pend[a][2][0] - pend[b][2][0],
                                                           pend[a][2][1] - pend[b][2][1]) <= prm["end_tol"]
                        or same_marker(pend[a][2], pend[b][2]))
    vertex = {}
    tees = []
    for g in groups:
        members = [pend[a] for a in g]
        cx = sum(m[2][0] for m in members) / len(members)
        cy = sum(m[2][1] for m in members) / len(members)
        if len(members) >= 3:
            v = ("tee", len(tees))
            tees.append((cx, cy))
        elif len(members) == 2:
            v = ("pass", g[0])
        else:
            v = ("free", g[0])
        for m in members:
            vertex[(m[0], m[1])] = (v, (cx, cy), "pdf_path_junction")
    for (i, k), (s, basis) in att.items():
        pt = pieces[i]["pts"][0] if k == 0 else pieces[i]["pts"][-1]
        vertex[(i, k)] = (("sym", s), pt, basis)
    # 통과점(끝 2개)을 이어 사슬로
    incident = {}
    for (i, k), (v, _, _) in vertex.items():
        if v[0] == "pass":
            incident.setdefault(v, []).append((i, k))
    used = set()
    chains = []
    order = sorted(range(len(pieces)), key=lambda i: pieces[i]["id"])
    for start in order:
        if start in used:
            continue
        # 사슬의 한쪽 끝을 찾을 때까지 거슬러 간다
        i, k = start, 0
        seen = {start}
        while vertex[(i, k)][0][0] == "pass":
            nxt = [x for x in incident[vertex[(i, k)][0]] if x != (i, k)]
            j, kj = nxt[0]
            if j in seen:
                break
            seen.add(j)
            i, k = j, 1 - kj
        # 정방향으로 걸으며 모은다
        first = vertex[(i, k)]
        pts = []
        evid = []
        cur, ck = i, k
        while True:
            used.add(cur)
            seq = pieces[cur]["pts"] if ck == 0 else list(reversed(pieces[cur]["pts"]))
            pts += seq if not pts else seq[1:]
            evid.append(pieces[cur]["id"])
            far = vertex[(cur, 1 - ck)]
            if far[0][0] != "pass":
                break
            nxt = [x for x in incident[far[0]] if x != (cur, 1 - ck)]
            j, kj = nxt[0]
            if j in used:
                break
            cur, ck = j, kj
        chains.append({"pts": pts, "ends": [first, far], "evidence": sorted(set(evid))})
    return tees, chains


def _piece_dir(d):
    """채운 점선 조각의 장축 단위 벡터(부호 고정). 꺾인 모서리 조각·정사각형에 가까운 조각은 None(방향 없음)."""
    pts = [tuple(q) for q in d["pts"]]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    w, h = _w(d["bbox"]), _h(d["bbox"])
    if len(pts) >= 6 or len(pts) < 2 or max(w, h) < 1.5 * min(w, h):
        return None
    edges = [(pts[k], pts[(k + 1) % len(pts)]) for k in range(len(pts))]
    a, b = max(edges, key=lambda e: math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1]))
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L == 0:
        return None
    if dx < 0 or (dx == 0 and dy < 0):
        dx, dy = -dx, -dy
    return (dx / L, dy / L)


def _filled_chains(filled, prm):
    """채운 사각형 점선 조각 → [(조각 목록, 끝 [(상자, 점)])].

    이웃: 간격 dash_gap_max 안이면서 (같은 방향이고 같은 직선 위) 이거나, 한쪽이 방향 없는 모서리 조각이거나,
    방향이 다르면 두 조각 모두 자기 직선 구간의 끝(같은 직선 이웃이 1개 이하)일 때만(꺾임). 교차점에서는 각 점선이
    교차점 양쪽으로 이어지므로 직선 구간 끝이 아니어서 서로 잇지 않는다."""
    n = len(filled)
    dirs = [_piece_dir(d) for d in filled]
    cos_tol = math.cos(math.radians(prm["dash_angle_tol"]))

    def close(i, j):
        return _box_gap(filled[i]["bbox"], filled[j]["bbox"]) <= prm["dash_gap_max"]

    def collinear(i, j):
        di, dj = dirs[i], dirs[j]
        if di is None or dj is None or abs(di[0] * dj[0] + di[1] * dj[1]) < cos_tol:
            return False
        ci, cj = _center(filled[i]["bbox"]), _center(filled[j]["bbox"])
        return abs((cj[0] - ci[0]) * di[1] - (cj[1] - ci[1]) * di[0]) <= prm["dash_collinear_tol"]

    near = [[j for j in range(n) if j != i and close(i, j)] for i in range(n)]
    straight = [sum(1 for j in near[i] if collinear(i, j)) for i in range(n)]

    def linked(i, j):
        if j not in near[i]:
            return False
        if dirs[i] is None or dirs[j] is None or collinear(i, j):
            return True
        return straight[i] <= 1 and straight[j] <= 1

    links = [[j for j in near[i] if linked(i, j)] for i in range(n)]
    out = []
    for g in _uf_groups(n, lambda i, j: j in links[i]):
        g = sorted(g, key=lambda i: filled[i]["id"])
        terms = [i for i in g if len(links[i]) <= 1] if len(g) > 1 else g * 2
        out.append(([filled[i] for i in g], [(filled[i]["bbox"], _center(filled[i]["bbox"])) for i in terms]))
    return out


def _stroke_chains(pieces, prm):
    """스트로크 점선 조각 → [(조각 목록, 끝 [(상자, 점)])].

    같은 원본 경로의 연속 조각(seq가 1씩 이어짐)만 한 구간이다. 기호 안에서 흡수된 조각이 있으면 그 자리에서
    구간을 끊는다(A–B–C를 관통하는 점선이 A–C로 이어지지 않게). 서로 다른 경로는 경로 끝점끼리 정확히 두 개가
    end_tol 안에서 만날 때만 잇는다(꺾임). 한 경로의 중간에서 만나는 교차는 잇지 않는다."""
    by_src = {}
    for d in pieces:
        by_src.setdefault(d["src"], []).append(d)
    runs = []  # (조각 목록, [(시작 끝: 보이는 점, 경로 끝점 또는 None), (마지막 끝: ...)])
    for src in sorted(by_src):
        items = sorted(by_src[src], key=lambda d: d["seq"])
        cur = [items[0]]
        for d in items[1:]:
            if d["seq"] != cur[-1]["seq"] + 1:
                runs.append(cur)
                cur = []
            cur.append(d)
        runs.append(cur)
    ends = []  # (run 번호, 0/1, 보이는 점, 경로 끝점 또는 None)
    for r, items in enumerate(runs):
        first, last = items[0], items[-1]
        ends.append((r, 0, first["pts"][0], first["path_ends"][0] if first["seq"] == 0 else None))
        ends.append((r, 1, last["pts"][-1], last["path_ends"][1] if last["seq"] == last["nseq"] - 1 else None))
    tips = [e for e in ends if e[3] is not None]
    joined, pairs = set(), []
    for g in _uf_groups(len(tips), lambda a, b: math.hypot(tips[a][3][0] - tips[b][3][0],
                                                           tips[a][3][1] - tips[b][3][1]) <= prm["end_tol"]):
        if len(g) == 2 and tips[g[0]][0] != tips[g[1]][0]:
            pairs.append((tips[g[0]][0], tips[g[1]][0]))
            joined.update({(tips[g[0]][0], tips[g[0]][1]), (tips[g[1]][0], tips[g[1]][1])})
    out = []
    for comp in _uf_groups(len(runs), lambda a, b: (a, b) in pairs or (b, a) in pairs):
        items = [d for r in comp for d in runs[r]]
        free = [e for e in ends if e[0] in comp and (e[0], e[1]) not in joined]
        out.append((items, [((e[2][0], e[2][1], e[2][0], e[2][1]), e[2]) for e in free]))
    return out


def _build_dashed(syms, dashes, markers, prm):
    """점선 조각 사슬 → [{pts, ends:[(vertex, point, basis)], evidence, dashed}].

    사슬 묶기는 _filled_chains(채운 사각형 점선)·_stroke_chains(스트로크 점선)를 따른다. 사슬 끝마다 가장 가까운
    기호(dash_attach_tol 안)에 붙이고, 끝이 정확히 둘이며 서로 다른 기호에 붙을 때만 관계가 되고 아니면 미해결로 남긴다.
    """
    chains = _filled_chains([d for d in dashes if "src" not in d], prm)
    chains += _stroke_chains([d for d in dashes if "src" in d], prm)
    out = []
    for items, terms in chains:
        hits = []
        for box, point in terms:
            for m in markers:  # 점선 끝 화살촉이 있으면 화살촉까지 이어 본다
                if _box_gap(m["bbox"], box) <= prm["dash_gap_max"]:
                    box = _union(box, m["bbox"])
            best = None
            for s in syms:
                gap = _box_gap(box, s.bbox)
                if gap <= prm["dash_attach_tol"] and (best is None or gap < best[0]):
                    best = (gap, s)
            hits.append((best[1] if best else None, point))
        if len(hits) == 2 and hits[0][0] is not None and hits[1][0] is not None and hits[0][0] is not hits[1][0]:
            ends = [(("sym", h[0]), h[1], "pdf_dash_chain") for h in hits]
        else:
            pts = [h[1] for h in hits] or [_center(items[0]["bbox"]), _center(items[-1]["bbox"])]
            ends = [(("free", -1), pts[0], "pdf_dash_chain"), (("free", -1), pts[-1], "pdf_dash_chain")]
        out.append({"pts": [_center(d["bbox"]) for d in items], "ends": ends,
                    "evidence": [d["id"] for d in items], "dashed": True})
    return out


def _merge_appendages(syms, chains, prm):
    """연결이 하나도 없는 기호가 더 큰 기호 바로 옆(큰 기호 긴 변 × 비율 안)에 있으면 그 기호의 부속(히터 등)으로 합친다."""
    linked = {id(v[1]) for ch in chains for v, _, _ in ch["ends"] if v[0] == "sym"}
    for s in sorted(syms, key=lambda s: _w(s.bbox) * _h(s.bbox)):
        if id(s) in linked or not s.alive:
            continue
        best = None
        for t in syms:
            if t is s or not t.alive or _w(t.bbox) * _h(t.bbox) <= _w(s.bbox) * _h(s.bbox):
                continue
            gap = _box_gap(s.bbox, t.bbox)
            if gap <= prm["appendage_gap_ratio"] * max(_w(t.bbox), _h(t.bbox)) and (best is None or gap < best[0]):
                best = (gap, t)
        if best is not None:
            best[1].merge(s)
    return [s for s in syms if s.alive]


# ---------------------------------------------------------------- 5. 글자

def _text_blocks(words, prm):
    """단어 → 줄 → 문단. 반환: [{text, bbox, size}] (위→아래, 왼→오 순).
    90° 돌린 낱말(upright 거짓, 아래→위 또는 위→아래로 읽음)은 읽는 방향이 가로가 되게 좌표를 돌려 같은 규칙으로
    묶은 뒤 되돌린다."""
    upright = [w for w in words if w.get("upright", True)]
    up_turn = [dict(w, x0=-w["bottom"], x1=-w["top"], top=w["x0"], bottom=w["x1"])  # 아래→위: x' = -y, y' = x
               for w in words if not w.get("upright", True) and w.get("direction", "btt") == "btt"]
    down_turn = [dict(w, x0=w["top"], x1=w["bottom"], top=-w["x1"], bottom=-w["x0"])  # 위→아래: x' = y, y' = -x
                 for w in words if not w.get("upright", True) and w.get("direction") == "ttb"]
    out = _upright_blocks(upright, prm)
    for b in _upright_blocks(up_turn, prm):
        x0, y0, x1, y1 = b["bbox"]
        out.append(dict(b, bbox=(y0, -x1, y1, -x0), rotated=True))
    for b in _upright_blocks(down_turn, prm):
        x0, y0, x1, y1 = b["bbox"]
        out.append(dict(b, bbox=(-y1, x0, -y0, x1), rotated=True))
    out.sort(key=lambda b: (round(b["bbox"][1], 2), round(b["bbox"][0], 2)))
    return out


def _upright_blocks(words, prm):
    """가로 글자 단어 → 줄 → 문단."""
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines = []
    for w in words:
        for ln in lines:
            if abs(ln["size"] - w["size"]) <= prm["line_size_tol"] and \
                    abs(ln["top"] - w["top"]) <= prm["line_top_ratio"] * w["size"] and \
                    0 <= w["x0"] - ln["x1"] <= prm["word_gap_ratio"] * w["size"]:
                ln["words"].append(w)
                ln["x1"] = w["x1"]
                ln["bottom"] = max(ln["bottom"], w["bottom"])
                break
        else:
            lines.append({"words": [w], "x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"],
                          "size": w["size"]})
    lines.sort(key=lambda ln: (round(ln["top"], 1), ln["x0"]))
    blocks = []
    for ln in lines:
        for b in blocks:
            last = b["lines"][-1]
            gap = ln["top"] - last["bottom"]
            overlap = min(ln["x1"], last["x1"]) - max(ln["x0"], last["x0"])
            if abs(last["size"] - ln["size"]) <= prm["line_size_tol"] and overlap > 0 and \
                    prm["block_gap_min_ratio"] * ln["size"] <= gap <= prm["block_gap_max_ratio"] * ln["size"]:
                b["lines"].append(ln)
                break
        else:
            blocks.append({"lines": [ln]})
    out = []
    for b in blocks:
        box = (min(l["x0"] for l in b["lines"]), min(l["top"] for l in b["lines"]),
               max(l["x1"] for l in b["lines"]), max(l["bottom"] for l in b["lines"]))
        text = "\n".join(" ".join(w["text"] for w in l["words"]) for l in b["lines"])
        out.append({"text": text, "bbox": box, "size": b["lines"][0]["size"]})
    out.sort(key=lambda b: (round(b["bbox"][1], 2), round(b["bbox"][0], 2)))
    return out


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


# ---------------------------------------------------------------- 6. 종류

def _is_circle(body, prm):
    b = body["bbox"]
    w, h = _w(b), _h(b)
    return body["closed"] and bool(body.get("curved")) and w > 0 and abs(w - h) <= prm["circle_aspect_tol"] * max(w, h)


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


def _shape_kind(sym, prm):
    """형상만으로 정하는 종류와 근거. 없으면 (None, None)."""
    circles = [b for b in sym.bodies if _is_circle(b, prm)]
    tris = [b for b in sym.bodies if _is_triangle(b)]
    others = [b for b in sym.bodies if b not in circles and b not in tris]
    if len(tris) == 2:  # 나비 모양(두 삼각형이 꼭짓점을 맞댐) = 밸브 몸통
        bow = _union(tris[0]["bbox"], tris[1]["bbox"])
        # 몸통 bbox 밖에 중심이 있는 몸체 = 구동부(안쪽 원은 글로브 표시라 구동부가 아니다)
        outside = [b for b in sym.bodies if b not in tris and not _inside(_center(b["bbox"]), bow)]
        if any(_is_circle(b, prm) for b in outside):
            return "motor_operated_valve", "valve_body+circle_actuator"
        if outside:
            return "control_valve", "valve_body+diaphragm_actuator"
        return "manual_valve", "valve_body"
    springs = [s for s in sym.strokes if len(s["pts"]) == 2 and abs(s["pts"][0][0] - s["pts"][1][0]) > 1
               and abs(s["pts"][0][1] - s["pts"][1][1]) > 1]
    if sym.bodies and len(springs) >= 2 and len({(round(s["pts"][0][1] - s["pts"][1][1], 1),
                                                    round(s["pts"][0][0] - s["pts"][1][0], 1)) for s in springs}) == 1:
        return "psv", "body+spring"
    if sym.stroke_only and sym.markers:
        return "check_valve", "lines+marker"
    straight = [s for s in sym.strokes if len(s["pts"]) == 2 and not s.get("curved")]
    if sym.stroke_only and straight and len(straight) == len(sym.strokes):
        vertical = [s for s in straight if abs(s["pts"][0][0] - s["pts"][1][0]) < 0.5]
        horizontal = [s for s in straight if abs(s["pts"][0][1] - s["pts"][1][1]) < 0.5]
        if max(len(vertical), len(horizontal)) >= 2:  # 축 정렬 평행 판 여러 개 = 오리피스 판
            return "orifice", "parallel_plates"
    if len(circles) == 1 and not tris and not others and len(sym.bodies) == 1:
        return "instrument", "circle"
    if len(sym.bodies) == 1 and _is_tombstone(sym.bodies[0]):
        return "instrument", "tombstone"
    if sym.bodies and all(_is_chevron(b) for b in sym.bodies):
        return "continuation", "chevron_arrow"
    return None, None


def _kind_from_text(text):
    up = text.upper()
    tokens = re.findall(r"[A-Z]+", up)
    if CONTINUATION_RE.match(up.strip()):
        return "continuation", "text_to_from"
    for words, kind in EQUIPMENT_WORDS:
        if all(w in tokens for w in words):
            return kind, "text_word:%s" % "+".join(words)
    return None, None


def _instrument_kind(text):
    """ISA 5.1 식 계기 표기(기능 문자 + 번호)를 나눠 읽는다: 'PT\n101'·'PT\n101\nA1'·'PT-101'·'PT 101'·'PT'.
    글자가 여러 줄이면 첫 두 줄(기능 문자·번호)로, 맞지 않으면 첫 줄로 판정한다."""
    lines = [" ".join(l.upper().split()) for l in text.split("\n") if l.strip()]
    m = None
    for flat in ([" ".join(lines[:2])] if len(lines) >= 2 else []) + lines[:1]:
        m = re.fullmatch(r"([A-Z]{1,4})(?:[ \-]*\d+[A-Z]?)?", flat)
        if m:
            break
    if not m:
        return None, None
    letters = m.group(1)
    if len(letters) >= 2 and letters[-1] == "E" and letters[0] == "T":
        return "temperature_element", "isa_letters:%s" % letters
    if len(letters) >= 2 and letters[-1] in INSTRUMENT_FUNCTION:
        return INSTRUMENT_FUNCTION[letters[-1]], "isa_letters:%s" % letters
    return None, None


_symbol_library = None
PIPE_CAP_BASIS = "small_closed_body_single_connection"
ACTUATOR_REACH_RATIO = 2.0  # 밸브 몸통 긴 변 × 비율 안에 구동부 기호가 있으면 구동 밸브로 본다(APR1400 축 길이 기준)


def symbol_library():
    """기호 사전(자원/기준/기호). 프로세스마다 한 번 읽는다. 없거나 깨졌으면 SymbolLibraryError로 멈춘다."""
    global _symbol_library
    with _cache_lock:
        if _symbol_library is None:
            lib = symbols.Library.load()
            _check_against_registry(lib)
            _symbol_library = lib
        return _symbol_library


def _check_against_registry(lib):
    """켜진 항목의 kind와 열거형 속성값이 타입 레지스트리에 있어야 한다. 아니면 SymbolLibraryError(조용히 넘어가지 않음)."""
    problems = []
    for e in sorted(lib.entries.values(), key=lambda e: e.id):
        if not e.enabled:
            continue
        if e.kind is not None and e.kind not in rules.KIND_CATEGORY:
            problems.append("%s: kind %r가 레지스트리에 없음" % (e.id, e.kind))
        for attrs in [e.attributes] + [t.set_attributes for t in e.templates]:
            for prop, value in attrs.items():
                spec = rules.REGISTRY.properties.get(prop)
                if spec and spec.get("type") == "enum" and value not in spec.get("values", ()):
                    problems.append("%s: %s=%r는 허용값 밖" % (e.id, prop, value))
    if problems:
        raise symbols.SymbolLibraryError("기호 사전이 레지스트리와 맞지 않음: " + "; ".join(problems))


def _symbol_match(sym, blocks):
    """기호 상자 안에 가운데가 든 글자 문단을 글자 조건으로 넘겨 사전에 대 본다."""
    x0, y0, x1, y1 = sym.bbox
    inside = [b["text"] for b in blocks if x0 <= (b["bbox"][0] + b["bbox"][2]) / 2 <= x1
              and y0 <= (b["bbox"][1] + b["bbox"][3]) / 2 <= y1]
    return symbol_library().match(symbols.sym_signature(sym), inside)


def _classify(sym, text, degree, prm, marks=()):
    """(kind, basis) — 근거가 없으면 kind None. marks: 기호 안 표기 글자(밸브 구동부의 M 등)."""
    shape, sbasis = _shape_kind(sym, prm)
    if shape in ("control_valve", "motor_operated_valve") and "M" in [m.strip().upper() for m in marks]:
        return "motor_operated_valve", "valve_body+actuator_mark:M"
    if shape == "instrument":
        kind, basis = _instrument_kind(text)
        if kind is None:  # 원형이지만 계기 문자가 아니면 장비 이름 낱말(예: 원형 펌프 기호에 PUMP)을 본다
            kind, basis = _kind_from_text(text)
        return kind, basis or "circle_without_isa_letters"
    if shape is not None:
        return shape, sbasis
    kind, basis = _kind_from_text(text)
    if kind is not None:
        return kind, basis
    if not text and degree == 1 and not sym.stroke_only and max(_w(sym.bbox), _h(sym.bbox)) <= prm["pipe_cap_max"]:
        return "pipe_cap", PIPE_CAP_BASIS
    return None, None


def _continuation_attributes(sym, blocks, prm, own=None, arrows=()):
    """연결 표시 화살표 옆 글자에서 상대 계통을 읽는다. 화살표에 붙은 글자 문단(own)에 'CV:RDT'처럼 계통 약어로
    시작하는 줄이 있으면 그것을, 없으면 그런 줄이 있는 문단 중 화살표에서 label_gap_max 안으로 가장 가까운 것을 쓴다.
    DCD는 가로 화살표의 글자를 화살표 위에, 세로 화살표의 글자를 왼쪽에 쓰므로 그 자리(또는 화살표 안)의 문단만 보고,
    다른 화살표(arrows)가 그 문단에 더 가까우면 그 화살표의 글자로 보아 쓰지 않는다. 화살표가 촘촘히 쌓인 곳에서
    이웃 화살표의 계통을 가져오지 않게 하려는 것이다(같은 계통의 다른 시트로 가면 약어를 생략한다, 범례 1.7-1).
    약어를 to_system, 그 줄부터의 글자를 to_label로 둔다. 없으면 빈 dict
    (계통 약어 없이 'MAKE-UP DEMIN. WATER'처럼 쓴 표시는 상대를 정하지 않는다). 쪽끼리 짝짓기는 하지 않는다."""
    ax0, ay0, ax1, ay1 = sym.bbox
    across = ax1 - ax0 >= ay1 - ay0

    def code_line(text):
        lines = text.split("\n")
        k = next((k for k, line in enumerate(lines) if SYSTEM_LABEL_RE.match(line)), None)
        return None if k is None else (SYSTEM_LABEL_RE.match(lines[k]).group(1), " ".join(" ".join(lines[k:]).split()))

    def in_place(b):
        bx0, by0, bx1, by1 = b["bbox"]
        if _inside(_center(b["bbox"]), sym.bbox):
            return True
        if across:
            return (by0 + by1) / 2 < (ay0 + ay1) / 2 and bx0 < ax1 and bx1 > ax0  # 문단 가운데가 화살표 가운데보다 위
        return (bx0 + bx1) / 2 < (ax0 + ax1) / 2 and by0 < ay1 and by1 > ay0

    def mine(b, gap):
        return in_place(b) and all(_box_gap(b["bbox"], a.bbox) >= gap for a in arrows if a is not sym)

    if own is not None and code_line(own["text"]) and mine(own, _box_gap(own["bbox"], sym.bbox)):
        code, text = code_line(own["text"])
        return {"to_system": code, "to_label": text}
    near = []
    sheet_ref = own is not None and re.search(r"SHEET\s*\d", own["text"])  # 범례 꼴: 화살표 안에 시트 번호가 있을 때만
    for b in blocks:
        hit = code_line(b["text"])
        gap = _box_gap(b["bbox"], sym.bbox)
        if not hit and sheet_ref and BARE_SYSTEM_RE.match(b["text"].strip()) and gap <= prm["bare_code_gap_max"]:
            hit = (b["text"].strip(), b["text"].strip())  # 범례 'MS / SHEET 2"A"'처럼 쌍점 없이 바로 옆에 쓴 계통 약어
        if hit and gap <= prm["label_gap_max"] and mine(b, gap):
            near.append((gap,) + hit)
    if not near:
        return {}
    _, code, text = min(near)
    return {"to_system": code, "to_label": text}


# ---------------------------------------------------------------- 태그

def _bubble_like(node, letters):
    """종류를 못 정한 계기 모양 기호가 계기 원으로 볼 만한가: 기능 문자 두 자 이상이고 기호 짧은 변 8pt 이상.
    밸브 힌지 점·댐퍼 축 점처럼 작은 원 옆 밸브 번호('V5402', 'Y0013A')를 계기 태그로 읽지 않게 한다."""
    g = node.get("geometry") or {}
    return len(letters) >= 2 and min(g.get("width", 0), g.get("height", 0)) >= 8


def _assign_tags(nodes, unknowns, instrument_ids=()):
    """기호 노드의 tag를 같은 쪽의 보이는 글자로 정한다.
    (a) 글자가 태그 모양(③ 문서 언급과 같은 hazop.kg.docextract.TAG_RE)으로 시작하면 그 낱말.
    (b) 계기(분류가 계기이거나 instrument_ids의 계기 모양 기호)의 ISA 글자(예: 'PT 110')면 <접두>-<문자><번호>.
        접두는 같은 쪽 (a) 태그 두 개 이상이 함께 쓰는 계통 접두 중 가장 많은 것이다. 글자에 없는 값을 고른 것이라
        근거에 [추론]을 남기고, 가장 많은 접두가 둘 이상이면 정하지 않는다. 가장 많은 접두도 태그 하나뿐이거나
        (a) 태그가 없으면(APR1400 DCD처럼 계기 원에 접두를 쓰지 않는 도면) 원 안 글자 그대로 <문자>-<번호>로 둔다.
    같은 tag가 두 노드 이상에 나오면 모두 비우고 duplicate_tag 미확인을 남긴다. 정하지 못한 노드는 missing_tag 미확인."""
    tags, isa = {}, {}
    for i, n in enumerate(nodes):
        if n["kind"] in rules.KINDS_WITHOUT_TAG:
            continue
        m = TAG_RE.match(n["label_text"].strip())
        if m:
            tags[i] = (m.group(0), "label_tag_token")
            continue
        lines = [" ".join(l.split()) for l in n["label_text"].splitlines() if l.strip()]
        m = ISA_LABEL_RE.fullmatch(" ".join(lines[:2]))
        if m and (n["category"] == "instrument" or n["local_id"] in instrument_ids and _bubble_like(n, m.group(1))):
            isa[i] = (m.group(1), m.group(2))
    counts = collections.Counter(t.split("-")[0] for t, _ in tags.values()).most_common(2)
    tied = len(counts) == 2 and counts[0][1] == counts[1][1]
    prefix = counts[0][0] if counts and not tied and counts[0][1] >= 2 else None
    for i, (letters, number) in isa.items():
        if prefix:
            tags[i] = ("%s-%s%s" % (prefix, letters, number), "isa_label+page_prefix:%s [추론]" % prefix)
        elif not tied:
            tags[i] = ("%s-%s" % (letters, number), "isa_label")
    seen = collections.Counter(t.casefold() for t, _ in tags.values())
    for i, n in enumerate(nodes):
        if n["kind"] in rules.KINDS_WITHOUT_TAG:
            continue
        tag, basis = tags.get(i, (None, None))
        if tag is not None and seen[tag.casefold()] > 1:
            _issue(unknowns, "duplicate_tag", "같은 쪽에서 태그 %r 가 두 노드 이상에 나옴(어느 것인지 정하지 않음)" % tag,
                   n["source_object_id"], n["local_id"], "tag")
            tag, basis = None, "duplicate_on_page"
        n["tag"] = tag
        n["evidence"]["tag_basis"] = basis
        if tag is None and basis is None:
            reason = ("ISA 계기 글자는 있으나 같은 쪽 계통 접두를 하나로 정할 수 없음" if i in isa
                      else "보이는 글자에서 태그를 정하지 못함(글자는 label_text에 보존)")
            _issue(unknowns, "missing_tag", reason, n["source_object_id"], n["local_id"], "tag")


# ---------------------------------------------------------------- 조립

def _issue(lst, check, reason, source_object_id=None, target=None, field=None):
    lst.append({"check": check, "target": target, "source_object_id": source_object_id,
                "field": field, "reason": reason})


def _box_out(b):
    return [_num(b[0]), _num(b[1]), _num(b[2] - b[0]), _num(b[3] - b[1])]


def _title_block(cells, blocks):
    """표 칸의 같은 행 두 칸(왼쪽 키·오른쪽 값)을 표제란 쌍으로 읽는다(drawio._title_block과 같은 규칙)."""
    def text_in(cell):
        inside = [b for b in blocks if _inside(_center(b["bbox"]), cell["bbox"])]
        return " ".join(b["text"].replace("\n", " ") for b in inside)
    rows = {}
    for c in cells:
        rows.setdefault(round(c["bbox"][1], 1), []).append(c)
    block = {}
    for _, items in sorted(rows.items()):
        if len(items) != 2:
            continue
        items.sort(key=lambda c: c["bbox"][0])
        key, value = text_in(items[0]), text_in(items[1])
        if key:
            block[key] = {"value": value, "key_object_id": items[0]["id"], "value_object_id": items[1]["id"]}
    return block


def analyze(width, height, words, prims, params=None):
    """원시 요소(load_page 결과) → 중간 결과 dict. pdfplumber 없이 합성 입력으로 시험할 수 있다."""
    prm = dict(PARAMS)
    prm.update(params or {})
    cls = _classify_primitives(width, height, prims, prm)
    ticks, marked = _line_ticks(cls["polys"], prm)
    syms, polys, markers, dashes = _group_symbols(cls, prm)
    # 빗금은 기호 묶기가 끝난 뒤에 남은 선에서만 뺀다. 기호 장식선으로 흡수된 빗금은 그대로 두어 기호 모양과 번호가
    # 빗금 처리 전과 같게 한다(빗금을 먼저 빼면 안전밸브 규칙이 응축기 몸통에 맞는 등 기호 판정이 바뀜)
    cls["ticks"] = [p for p in polys if p["id"] in ticks]
    polys = [p for p in polys if p["id"] not in ticks]
    tees, chains = _build_solid(syms, polys, markers, prm)
    for ch in chains:
        # 빗금 선으로만 되고 그 사슬 위에 빗금 묶음이 실제로 있는 사슬 = 공압 신호선. 배관과 섞이거나, 원래 경로가
        # 분기점에서 나뉘어 빗금 없는 쪽 토막이면 배관으로 둔다
        if ch["evidence"] and all(e in marked for e in ch["evidence"]) and any(
                _seg_dist(c, a, b)[0] <= prm["tick_host_dist"] for e in ch["evidence"] for c in marked[e]
                for a, b in _segs(ch["pts"])):
            ch["pneumatic"] = True
    chains += _build_dashed(syms, dashes, markers, prm)
    syms = _merge_appendages(syms, chains, prm)
    blocks = _text_blocks(words, prm)
    return {"params": prm, "classified": cls, "symbols": syms, "tees": tees, "chains": chains,
            "blocks": blocks, "leftover_markers": markers}


def build_extraction(analysis, width, height, page_count, page, file_label, sha):
    """중간 결과 → extraction dict(drawio.extract와 같은 최상위·노드·관계 키)."""
    prm = analysis["params"]
    syms, tees, chains, blocks = analysis["symbols"], analysis["tees"], analysis["chains"], analysis["blocks"]
    cls = analysis["classified"]
    blockers, unknowns = [], []
    if not words_or_paths(analysis):
        _issue(blockers, "no_vector_content", "페이지에 글자·벡터 경로가 없음(스캔 PDF 등, 이 어댑터로 읽을 수 없음)")

    # 글자: 표제란·선 라벨·기호 라벨·나머지
    cell_boxes = [c["bbox"] for c in cls["cells"]]
    # 글자 줄과 같은 방향(가로)으로 글자 위를 지나는 선만 선 라벨 근거로 본다(세로로 가로지르는 선은 우연한 겹침)
    solid_segments = [(a, b) for ch in chains if not ch.get("dashed") for a, b in _segs(ch["pts"])
                      if abs(b[1] - a[1]) <= 0.2 * abs(b[0] - a[0])]
    roles = {}
    for bi, b in enumerate(blocks):
        c = _center(b["bbox"])
        if any(_inside(c, cb) for cb in cell_boxes):
            roles[bi] = "title_block"
        elif any(_inside(c, m["bbox"]) for m in cls["masks"]) or \
                any(_poly_box_dist([s1, s2], _expand(b["bbox"], -0.5)) == 0.0 for s1, s2 in solid_segments):
            roles[bi] = "line_label"
    # 밸브 몸통·구동부 안 글자(M, E/H 등)는 태그가 아니라 기호 표기로 본다
    shape_of = [_shape_kind(s, prm) for s in syms]
    marks = {}
    for bi, b in enumerate(blocks):
        if bi in roles:
            continue
        for si, s in enumerate(syms):
            if rules.KIND_CATEGORY.get(shape_of[si][0]) == "valve" and _inside(_center(b["bbox"]), s.bbox):
                marks.setdefault(si, []).append(b["text"])
                roles[bi] = "symbol_mark"
                break
    degree = {}
    for ch in chains:
        for v, _, _ in ch["ends"]:
            if v[0] == "sym":
                degree[id(v[1])] = degree.get(id(v[1]), 0) + 1
    # 형상 규칙이 못 정한 기호는 사전에 먼저 대 본다. 사전이 연결 표시로 본 기호도 화살표 목록에 넣어야 이웃 화살표의
    # 계통 글자를 가져가지 않는다(_continuation_attributes). 버릴 기호(무늬 점)는 글자를 가져가지 않게 후보에서 뺀다
    hits = {si: _symbol_match(s, blocks) for si, s in enumerate(syms) if shape_of[si][0] in (None, "instrument")}
    drop = {si for si, h in hits.items() if h.outcome == "matched" and h.entry.role == "drop"
            and not degree.get(id(syms[si]))}
    actuators = [syms[si] for si, h in sorted(hits.items()) if h.outcome == "matched" and h.entry.role == "actuator"]
    cand = []
    for bi, b in enumerate(blocks):
        if bi in roles:
            continue
        for si, s in enumerate(syms):
            if si in drop:
                continue
            if b.get("rotated") and shape_of[si][0] not in ("instrument", "continuation"):
                continue  # 돌린 글자는 대개 행선지·위치 설명이라 다른 기호의 종류를 정하는 글자로 쓰지 않는다
            inside = _inside(_center(b["bbox"]), s.bbox)
            gap = -1.0 if inside else _box_gap(b["bbox"], s.bbox)
            if gap <= prm["label_gap_max"]:
                cand.append((round(gap, 6), bi, si))
    arrows = [s for si, s in enumerate(syms) if shape_of[si][0] == "continuation" or
              (si in hits and hits[si].outcome == "matched" and hits[si].entry.role == "continuation")]
    label_of, taken = {}, set()
    for gap, bi, si in sorted(cand):
        if si in label_of or bi in taken:
            continue
        label_of[si] = bi
        taken.add(bi)

    node_out, locations, local_of, instrument_ids, dropped = [], [], {}, set(), []
    for n, s in enumerate(syms, 1):
        local_id = "local-node-%03d" % n
        sid = "pdf-p%d-sym-%04d" % (page, n)
        local_of[id(s)] = (local_id, sid)
        bi = label_of.get(n - 1)
        text = blocks[bi]["text"] if bi is not None else ""
        kind, basis = _classify(s, text, degree.get(id(s), 0), prm, marks.get(n - 1, []))
        symbol_id, symbol_attrs = None, {}
        fallback = basis == PIPE_CAP_BASIS  # 끝막음은 형상 규칙이 아니라 뒤처리 규칙: 사전에 후보가 없을 때만 남긴다(§4.2 5번)
        if kind is None or fallback:  # 기존 규칙이 못 정한 기호에만 기호 사전을 쓴다(기획서/PID-기호사전.md §4.2)
            hit = hits.get(n - 1) or _symbol_match(s, blocks)
            if fallback and hit.outcome != "none":
                kind, basis = None, None
            if hit.outcome == "matched":
                entry = hit.entry
                symbol_id, basis = entry.id, "symbol:%s" % entry.id
                if entry.role == "drop" and not degree.get(id(s)):
                    dropped.append({"source_object_id": sid, "label_text": "", "bbox": _box_out(s.bbox),
                                    "reason": basis})
                    continue  # 노드 번호는 비워 둔다(다른 기호 번호가 밀리지 않게)
                if entry.role in ("symbol", "continuation") and entry.kind_from == "isa_letters":
                    kind, isa_basis = _instrument_kind(text)
                    basis = "%s+%s" % (basis, isa_basis) if kind else basis
                    instrument_ids.add(local_id)
                elif entry.role in ("symbol", "continuation"):
                    kind = entry.kind
                    symbol_attrs = {k: v for k, v in sorted(hit.attributes.items()) if k in rules.REGISTRY.properties}
                    reach = ACTUATOR_REACH_RATIO * max(_w(s.bbox), _h(s.bbox))
                    if kind == "manual_valve" and any(_box_gap(a.bbox, s.bbox) <= reach for a in actuators):
                        kind = None  # 몸통만으로는 수동인지 모른다. 구동부를 밸브에 합치는 단계(S5) 전에는 정하지 않는다
                        _issue(unknowns, "actuated_valve_pending", "구동부 기호가 붙은 밸브 몸통: 구동 방식은 아직 정하지 않음",
                               sid, local_id, "kind")
            elif hit.outcome == "ambiguous":
                _issue(unknowns, "ambiguous_symbol", "기호 사전 후보가 둘 이상이라 정하지 않음: %s"
                       % ", ".join(c for c, _ in hit.candidates[:3]), sid, local_id, "kind")
        if rules.KIND_CATEGORY.get(kind) == "instrument" or (kind is None and shape_of[n - 1][0] == "instrument"):
            instrument_ids.add(local_id)  # 측정 연결 판정: 계기로 분류됐거나 원형이고 다른 종류 근거가 없는 기호
        category = rules.KIND_CATEGORY.get(kind)
        classification = "classified" if category else "unclassified"
        if kind is None:
            _issue(unknowns, "missing_kind", "형상·글자 규칙으로 종류를 정할 근거 없음", sid, local_id, "kind")
        node_out.append({
            "local_id": local_id, "source_object_id": sid, "classification": classification,
            "category": category, "kind": kind, "tag": None, "label": text, "label_text": text,
            "label_location": ({"bbox": _box_out(blocks[bi]["bbox"]), "approximate": False,
                                "method": "pdf_text_block"} if bi is not None else None),
            "attributes": (_continuation_attributes(s, blocks, prm, blocks[bi] if bi is not None else None, arrows)
                           if kind == "continuation" else symbol_attrs),
            "style": None, "parent": None,
            "geometry": dict(zip(("x", "y", "width", "height"), _box_out(s.bbox))),
            "evidence": dict({"classification_basis": basis, "pdf_objects": s.evidence(),
                              "stroke_only": s.stroke_only, "symbol_marks": marks.get(n - 1, [])},
                             **({"symbol_id": symbol_id} if symbol_id else {})),
        })
        locations.append({"object_id": sid, "local_id": local_id, "coordinate_space": COORDINATE_SPACE,
                          "unit": UNIT, "bbox": _box_out(s.bbox), "approximate": False})
    _assign_tags(node_out, unknowns, instrument_ids)
    tee_ids = {}
    for k, (x, y) in enumerate(tees):
        n = len(syms) + k + 1  # 사전이 버린 기호가 있어도 기호 노드 번호와 겹치지 않게
        local_id, sid = "local-node-%03d" % n, "pdf-p%d-junction-%04d" % (page, k + 1)
        tee_ids[k] = (local_id, sid)
        box = (x - prm["tee_half"], y - prm["tee_half"], x + prm["tee_half"], y + prm["tee_half"])
        node_out.append({
            "local_id": local_id, "source_object_id": sid, "classification": "classified",
            "category": rules.KIND_CATEGORY["tee"], "kind": "tee", "tag": None, "label": "", "label_text": "",
            "label_location": None, "attributes": {}, "style": None, "parent": None,
            "geometry": dict(zip(("x", "y", "width", "height"), _box_out(box))),
            "evidence": {"classification_basis": "line_junction_3plus", "pdf_objects": [], "stroke_only": False,
                         "symbol_marks": []},
        })  # 분기점은 선이 만나는 자리를 계산해 만든 노드라 태그가 있을 수 없다(태그 없음 미확인을 남기지 않음)
        locations.append({"object_id": sid, "local_id": local_id, "coordinate_space": COORDINATE_SPACE,
                          "unit": UNIT, "bbox": _box_out(box), "approximate": True,
                          "method": "line_junction_point"})


    def ref(v):
        if v[0] == "sym":
            return local_of[id(v[1])]
        if v[0] == "tee":
            return tee_ids[v[1]]
        return None

    ordered = sorted(chains, key=lambda c: (bool(c.get("dashed")), c["evidence"][0]))
    relations, unresolved = [], []
    for n, ch in enumerate(ordered, 1):
        local_id, sid = "local-edge-%03d" % n, "pdf-p%d-conn-%04d" % (page, n)
        endpoints, resolved = [], True
        for end, (v, pt, basis) in zip(("source", "target"), ch["ends"]):
            r = ref(v)
            ep = {"end": end, "node_local_id": r[0] if r else None, "source_object_id": r[1] if r else None,
                  "constraint": None, "point": [_num(pt[0]), _num(pt[1])], "point_basis": basis,
                  "status": "connected" if r else "unconnected",
                  "port": None}  # drawio 추출과 같은 끝점 키(기획서/정보추출.md #port-rule). PDF에는 포트 근거 없음
            if r is None:
                resolved = False
                _issue(unknowns, "unconnected_endpoint", "%s 끝이 기호·분기점에 닿지 않음(미확인 끝점)" % end,
                       sid, local_id, end)
            endpoints.append(ep)
        ids = [e["node_local_id"] for e in endpoints]
        if resolved and ids[0] == ids[1]:
            resolved = False
            _issue(unknowns, "self_loop", "양 끝이 같은 기호에 닿음(기호 내부선일 수 있음)", sid, local_id)
        if ch.get("dashed"):
            rel_kind, line_type = "signal_connection", "pdf_dashed"
        elif ch.get("pneumatic"):
            rel_kind, line_type = "signal_connection", "pdf_pneumatic"
        elif any(i in instrument_ids for i in ids if i):
            rel_kind, line_type = "measurement_connection", "pdf_solid"
        else:
            rel_kind, line_type = "physical_connection", "pdf_solid"
        if rel_kind in rules.RELATION_KINDS_WITH_FLOW:
            _issue(unknowns, "unknown_flow_direction", "PDF 선에서 흐름 방향을 정하지 않음", sid, local_id,
                   "flow_direction")
        record = {
            "local_id": local_id, "source_object_id": sid, "kind": rel_kind, "line_type": line_type,
            "line_no": None, "endpoints": endpoints, "flow_direction": None,
            "waypoints": [[_num(p[0]), _num(p[1])] for p in ch["pts"][1:-1]] if not ch.get("dashed") else [],
            "label": "", "label_text": "", "label_cells": [], "attributes": {}, "style": None, "parent": None,
            "geometry": None,
            "evidence": {"classification_basis": "dash_chain" if ch.get("dashed") else "solid_path",
                         "pdf_objects": list(ch["evidence"]),
                         # 선이 지나는 실제 점(양 끝 포함, 점선은 조각 중심). ② 배경 SVG의 관계 경로로 그린다
                         "pdf_path": [[_num(p[0]), _num(p[1])] for p in ch["pts"]]},
        }
        (relations if resolved else unresolved).append(record)
        pts = ch["pts"] + [tuple(e["point"]) for e in endpoints]
        locations.append({"object_id": sid, "local_id": local_id, "coordinate_space": COORDINATE_SPACE,
                          "unit": UNIT, "bbox": _box_out(_bbox_pts(pts)), "approximate": True,
                          "method": "pdf_path_points"})

    text_out = []
    for bi, b in enumerate(blocks):
        if bi in taken or roles.get(bi) in ("title_block", "symbol_mark"):
            continue
        n = len(text_out) + 1
        local_id, sid = "local-text-%03d" % n, "pdf-p%d-text-%04d" % (page, bi + 1)
        text_out.append({"local_id": local_id, "source_object_id": sid, "label": b["text"], "text": b["text"],
                         "attributes": {}, "style": None, "parent": None,
                         "geometry": dict(zip(("x", "y", "width", "height"), _box_out(b["bbox"]))),
                         "knowledge_status": "unknown",
                         "note": "선 라벨 후보(선 위·흰 바탕)" if roles.get(bi) == "line_label"
                         else "소속 대상 미확정(거리 상한 밖)"})
        locations.append({"object_id": sid, "local_id": local_id, "coordinate_space": COORDINATE_SPACE,
                          "unit": UNIT, "bbox": _box_out(b["bbox"]), "approximate": False})

    title_block = _title_block(cls["cells"], blocks)
    drawing = {"page_width": _num(width), "page_height": _num(height), "title_block": title_block}
    for key, field in rules.TITLE_BLOCK_FIELDS.items():
        drawing[field] = title_block[key]["value"] if key in title_block else None
    if drawing["drawing_number"] is None:
        _issue(unknowns, "missing_drawing_number", "표제란에서 DWG NO.를 찾지 못함", field="drawing_number")
    drawing["ignored_objects"] = [{"source_object_id": o["id"], "label_text": "", "bbox": _box_out(o["bbox"])}
                                  for o in cls["frames"] + cls["cells"]] + dropped + [
        {"source_object_id": o["id"], "label_text": "", "bbox": _box_out(o["bbox"]), "reason": "line_tick"}
        for o in cls.get("ticks", [])]
    for pid in cls["invisible_dashed"]:
        _issue(unknowns, "dashed_path_no_visible_piece", "점선 무늬·위상 때문에 그려지는 구간이 없는 경로(선으로 보지 않음)",
               pid)
    for field in ("project_id", "material_id", "registration_version"):
        _issue(unknowns, "not_registered", "자료 등록 단계 미연동으로 %s 없음" % field, field=field)

    # 구조 검사: 중복 id, 잘못된 참조, 유한하지 않은 좌표
    seen = set()
    for rec in node_out + text_out + relations + unresolved:
        if rec["local_id"] in seen:
            _issue(blockers, "duplicate_id", "같은 local_id가 두 번 이상", rec["source_object_id"], rec["local_id"])
        seen.add(rec["local_id"])
    node_ids = {n["local_id"] for n in node_out}
    for r in relations:
        for ep in r["endpoints"]:
            if ep["node_local_id"] not in node_ids:
                _issue(blockers, "missing_reference", "끝점이 없는 노드를 가리킴", r["source_object_id"],
                       r["local_id"], ep["end"])
    for loc in locations:
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in loc["bbox"]):
            _issue(blockers, "invalid_number", "좌표가 유한한 수가 아님", loc["object_id"], loc["local_id"], "bbox")

    stem = os.path.splitext(os.path.basename(file_label))[0]
    run_id = "extract-pdf-%s-p%d-%s-%s" % (drawing["drawing_number"] or stem, page, RULES_VERSION, sha[:12])
    result = {
        "schema_version": SCHEMA_VERSION,
        "project_id": None,
        "extraction_run_id": run_id,
        "run": {"script": SCRIPT_NAME, "script_version": SCRIPT_VERSION, "rules_version": RULES_VERSION,
                "scope": "full", "settings": {"page_index": page, "params": dict(prm)}},
        "source": {"material_id": None, "registration_version": None, "format": SOURCE_FORMAT,
                   "file": file_label, "sha256": sha, "compressed": None, "page_count": page_count},
        "source_context": {"document_id": None, "page_id": "page-%d" % (page + 1), "page_name": None},
        "review_status": "not_reviewed",
        "drawing": drawing,
        "coordinate_system": {"coordinate_space": COORDINATE_SPACE, "unit": UNIT,
                              "origin": "PDF 페이지 왼쪽 위, x 오른쪽·y 아래쪽 증가(pdfplumber top 기준)",
                              "svg_alignment": None},
        "nodes": node_out,
        "relations": relations,
        "unresolved_connectors": unresolved,
        "texts": text_out,
        "unclassified": [],
        "source_locations": locations,
        "validation": {"status": "blocked" if blockers else "passed", "blockers": blockers, "unknowns": unknowns},
    }
    result["summary"] = drawio.summarize(result)
    return result


def words_or_paths(analysis):
    cls = analysis["classified"]
    return bool(analysis["blocks"] or cls["bodies"] or cls["polys"] or cls["dashes"])


def apply_registration(result, registration):
    """① 등록정보를 추출 결과에 반영한다(drawio.extract의 registration 경로와 같은 규칙).
    식별 값은 ①에서 사람이 확정한 값만 쓰고 표제란 값은 title_block_candidates로만 남긴다."""
    reg = registration
    val = result["validation"]
    # 등록 경로의 식별 값은 등록정보가 정한다(drawio 등록 경로와 같이 표제란 누락은 미확인으로 남기지 않음)
    blockers = val["blockers"]
    unknowns = [u for u in val["unknowns"] if u["check"] not in ("not_registered", "missing_drawing_number")]
    drawing = result["drawing"]
    drawing["identification_basis"] = "registration_confirmed"
    drawing["title_block_candidates"] = {f: drawing.get(f) for f in ("drawing_number", "revision", "title")}
    for field, reg_field in (("drawing_number", "drawing_number"), ("revision", "design_revision"),
                             ("title", "title")):
        drawing[field] = reg.get(reg_field)
    reg_val = reg.get("validation") or {}
    if reg.get("status") != "registered" or reg_val.get("status") != "passed" or reg_val.get("blockers"):
        _issue(blockers, "registration_not_completed", "등록 완료(registered·passed)가 아닌 등록정보: status=%r"
               % reg.get("status"), field="status")
    if reg.get("sha256") != result["source"]["sha256"]:
        _issue(blockers, "registration_hash_mismatch", "입력 파일 해시가 등록정보의 sha256과 다름", field="sha256")
    page_id = result["source_context"]["page_id"]
    registered_pages = [pid for d in reg.get("documents") or [] for pid in d.get("page_ids") or []]
    if page_id not in registered_pages:
        _issue(blockers, "registration_page_mismatch", "추출한 페이지 %r 가 등록정보 page_ids %r 에 없음"
               % (page_id, registered_pages), field="page_id")
    for u in reg_val.get("unknowns", []):
        _issue(unknowns, "registration_unknown", "등록 단계 미확인: %s" % u["reason"], field=u["field"])
    val["unknowns"] = unknowns
    val["status"] = "blocked" if blockers else "passed"
    result["project_id"] = reg.get("project_id")
    result["source"]["material_id"] = reg.get("material_id")
    result["source"]["registration_version"] = reg.get("registration_version")
    result["source_context"]["document_id"] = (reg.get("documents") or [{}])[0].get("document_id")
    stem = os.path.splitext(os.path.basename(result["source"]["file"]))[0]
    result["extraction_run_id"] = "extract-pdf-%s-p%d-%s-%s-%s-%s-r%s" % (
        drawing["drawing_number"] or stem, result["run"]["settings"]["page_index"], RULES_VERSION,
        result["source"]["sha256"][:12], reg.get("project_id"), reg.get("material_id"), reg.get("registration_version"))
    result["summary"] = drawio.summarize(result)
    return result


def extract(path, page=0, repo_root=None, params=None, registration=None):
    """벡터 PDF 한 쪽 → extraction dict. pdfplumber가 없으면 ImportError.
    registration: ① 등록정보(dict). 주면 apply_registration으로 식별 정보를 채우고 검사한다."""
    with open(path, "rb") as fh:
        sha, page_count, width, height, analysis = analyze_bytes(fh.read(), page, params)
    label = paths.rel_or_abs(path, repo_root) if repo_root else path
    result = build_extraction(analysis, width, height, page_count, page, label, sha)
    return apply_registration(result, registration) if registration is not None else result
