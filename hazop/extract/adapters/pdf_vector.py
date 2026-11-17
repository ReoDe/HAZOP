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
   장비 이름 낱말, 도면 연결 표기 TO/FROM). 근거가 없으면 kind 없음(unclassified)으로 둔다. 형상과 장비 이름 낱말이
   어느 종류인지는 기호 사전 공통 묶음(resources/library/symbols/common)이 정하고, 여기서는 구조 특징만 판정한다.
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

# 나눈 모듈(F1-0). 옮긴 이름을 예전 경로(pdf_vector.이름)로도 쓸 수 있게 모두 다시 내보낸다
from .pdf_vector_common import (
    _num, _bbox_pts, _union, _expand, _inside, _pt_box_dist, _box_gap, _depth, _w, _h, _seg_dist, _segs, _poly_dist,
    _seg_cross, _poly_box_dist, _uf_groups, _center, _is_circle, _is_tombstone, _is_chevron, _is_triangle, _is_half_disc, _issue,
    _is_convex,
    _pt_circle_dist, _end_runs, _meets_at_end,
)
from .pdf_vector_grouping import (
    _Sym, _cluster_bodies, _nearest_sym, _end_status, _plate_assemblies, _group_symbols, _merge_appendages,
    _black_fill_groups, _cut_at_boxes, _contact_chains, _housing_chains, _cut_through, _flow_axis, _reach_box, FLOW_LONG_RATIO,
    _pt_ring_dist,
)
from .pdf_vector_connectors import (
    SHEET_WORD_RE, CONTINUATION_RE, SYSTEM_LABEL_RE, BARE_SYSTEM_RE, _continuation_attributes, same_sheet_letter_pairs,
)
from .pdf_vector_flow import (_chain_flow, _end_symbol_flows, _inline_unclassified, _propagate_flows, _revert_contradictions,
                               _through_instruments, _vent_ends, arrow_axis,
                               continuation_flow, end_arrow)
from .pdf_vector_lines import attach_continuation_line_numbers, attach_line_labels, parse_label
from .pdf_vector_labels import (ALARM_COLUMN_TOL, ALARM_RE, ISA_LABEL_RE, PAREN_TOKEN_RE, PLATE_PART_RE, POSITION_CODE_RE, POSITION_TEXT_RE, NUMBER_PLATE_RE,
                                VALVE_TAG_RE,
                                _text_blocks, _upright_blocks, _bubble_like, _assign_tags, _join_bubble_number)

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
    "crossing_gap_max": 12.0,    # 엇갈림 끊김: 다른 선 양쪽에서 마주 보는 두 선 끝 사이 거리 상한(pt)
    "crossing_width_ratio": 2.0,  # 네 갈래 교차에서 곧게 지나는 두 선의 굵기 비가 이 이상이면 잇지 않는다
    "inner_tol_ratio": 0.1,      # 기호 안 선 흡수 여유 = 몸체 긴 변 × 비율 (아래 범위로 자름)
    "inner_tol_min": 2.0,
    "inner_tol_max": 8.0,
    "deep_min": 3.0,             # 선 끝이 몸체 안쪽 깊이(경계에서) 이상이면 기호 내부선(구동부 축 등)
    "deep_ratio": 0.2,           # 깊이 = max(deep_min, 몸체 짧은 변 × 비율)
    "decor_group_tol": 3.0,      # 장식선끼리 묶음 거리
    "decor_extent_ratio": 0.6,   # 장식선이 기호 밖으로 나간 길이 상한 = 기호 긴 변 × 비율
    "stroke_symbol_min": 4.0,    # 선 기호 최소 크기
    "stroke_symbol_max": 60.0,   # 선 기호 최대 크기(넘으면 끊긴 배관으로 본다)
    "pocket_max": 8.0,           # 배관 옆 주머니(드레인 포트) 선 무리 긴 변 상한
    "dash_gap_max": 3.0,         # 점선 조각 사이 간격 상한
    "dash_attach_tol": 8.0,      # 점선 끝 조각과 기호 사이 거리 상한(점선 끝 빈칸·구동부 여백 포함)
    "dash_pipe_axis_ratio": 1.5,    # 점선 배관: 밸브 몸통의 긴 변/짧은 변이 이만큼은 돼야 흐름 축을 안다
    "label_gap_max": 15.0,       # 글자 문단과 기호 사이 거리 상한
    "bare_code_gap_max": 5.0,    # 쌍점 없는 두 글자 계통 약어를 연결 표시 글자로 볼 거리 상한(바로 옆만)
    "appendage_gap_ratio": 0.1,  # 연결 없는 작은 기호를 옆 큰 기호에 합치는 거리 = 큰 기호 긴 변 × 비율
    "container_min": 20.0,       # 담는 외곽: 짧은 변이 이 이상인 곧은 변 닫힌 외곽(밸브·계기 원은 11pt 안팎)
    "container_hold_ratio": 0.5,  # 담는 외곽 안의 몸체가 담긴 것: 넓이가 외곽의 이 비율 이하(겹선 외곽은 담긴 것이 아니다)
    "container_beside_ratio": 0.15,  # 담는 외곽 변 바깥에 붙은 곧은 변 상자를 따로 두는 넓이 상한(외곽 넓이 × 비율)
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
    "word_overlap_ratio": 0.1,   # 같은 줄: 단어가 앞 단어와 겹쳐도 되는 폭 ≤ 글자 크기 × 비율(커닝)
    "word_join_ratio": 0.02,     # 같은 줄: 간격이 글자 크기 × 비율보다 작으면 띄어 쓰지 않는다(한 자씩 끊긴 조각은
                                 # |간격| < 0.01×크기에 몰리고, 'AFW PUMP'처럼 좁게 띄어 쓴 낱말은 0.03×크기 이상이다)
    "block_gap_min_ratio": -0.2,  # 같은 문단: 줄 사이 간격 ≥ 글자 크기 × 비율
    "block_gap_max_ratio": 0.5,  # 같은 문단: 줄 사이 간격 ≤ 글자 크기 × 비율
    "tick_len_max": 4.0,         # 신호선 빗금(//): 짧은 직선 조각 길이 상한(APR1400 범례 1.7-1 4/4 공압 신호선)
    "tick_host_dist": 1.0,       # 빗금 가운데와 가로지르는 선 사이 거리 상한
    "tick_angle_min": 30.0,      # 빗금과 선 사이 각도 범위(도). 직각(오리피스 판)은 빗금으로 보지 않는다
    "tick_angle_max": 80.0,
    "tick_pair_gap": 3.0,        # 같은 선 위 빗금 둘 이상이 이 거리 안에 나란히 있어야 빗금 묶음
    "tick_host_min": 10.0,       # 빗금 묶음이 여럿인 신호선의 최소 길이(묶음이 하나뿐인 선은 빗금보다 길면 된다)
    "tick_pairs_min": 2,         # 한 선에 빗금 묶음이 이 수 이상이면 신호선. 하나뿐이면 빗금이 정확히 둘일 때만(_line_ticks)
    "dot_max": 1.5,              # 매설 배관 점(범례 1.7-1 1/4 BURIED PIPE): 작은 채운 점의 긴 변 상한
    "dot_host_dist": 1.0,        # 점 가운데와 그 점이 얹힌 선 사이 거리 상한
    "dots_min": 2,               # 한 선에 점이 이 수 이상이어야 선 장식(외톨이 조각 하나는 지우지 않음)
    "plate_len_min": 2.0,        # 배관을 가로지르는 판(플랜지·버터플라이·볼 밸브 몸통 판) 길이 범위
    "plate_len_max": 5.0,
    "plate_par_tol": 0.09,       # 두 판이 나란함: 방향 벡터 외적 상한(약 5도)
    "plate_len_tol": 0.35,       # 두 판 길이 차 상한
    "plate_align_tol": 0.35,     # 두 판 가운데가 같은 배관 축 위: 판 방향으로 어긋난 거리 상한
    "plate_touch_tol": 0.6,      # 배관 끝이 판 가운데에 닿음·점이 판 사이 가운데에 있음
    "flange_gap_max": 2.6,       # 플랜지 두 판 사이 간격 상한(범례 FLANGED CONNECTION)
    "valve_gap_max": 8.0,        # 밸브 몸통 두 판 사이 간격 상한
    "plate_dot_max": 6.0,        # 판 사이 둥근 점(버터플라이 축·볼) 긴 변 상한
    "actuator_body_max": 8.0,    # 혼자 구동부 견본에 대 보는 곡선 몸체 긴 변 상한(pt). 다이어프램 5.4~5.7, 전동기 원 3.7~4.2
    "number_reach": 6.0,         # 밸브 번호 원 지시선의 떠 있는 끝에서 밸브 상자까지 거리 상한
}

VARIABLE_MODIFIERS_ISA = frozenset("DFJKQ")  # hazop.extract.isa.VARIABLE_MODIFIERS와 같은 ISA 변수 수식 문자
INSTRUMENT_FUNCTION = {"T": "transmitter", "C": "controller", "I": "indicator", "S": "switch",
                       "R": "recorder"}  # ISA 5.1 뒤 글자(기능)
# 구동부 사전 항목의 actuator_type → 밸브 kind. 범례 1.7-1이 정한 경우만 합치고 kind를 올린다(기획서/PID-기호사전.md
# §4.2 4번). 솔레노이드는 다이어프램과 같이 붙을 때만 공기구동 밸브의 파일럿으로 합친다(4/4). 솔레노이드 혼자는 스프링
# 복귀·복동 실린더 구동부(4/4)의 파일럿일 수 있어 여기서는 합치지 않는다. 축 위 묶음이 S 상자 하나뿐인지, 다른 조각과
# 함께인지는 _operator_stacks·_stack_entry가 가린다. 전기유압(1/4)은 kind를 정할 근거가 없어 합치지 않는다.
# 속성 값은 사전 항목의 attributes다
ACTUATED_KIND = {"motor": "motor_operated_valve", "diaphragm": "air_operated_valve"}
OPERATED_VALVES = frozenset({"motor_operated_valve", "air_operated_valve", "control_valve", "solenoid_valve"})
VALVE_NUMBER_RE = re.compile(r"\d{2,4}[A-Z]?")  # 범례 1.7-1 1/4 VALVE IDENT. NUMBER(사전 apr1400.ident_bubble_circle)
# 밸브 옆 위치 약어(범례 1.7-1 1/4·4/4): 정상 위치 NO·NC·LO·LC·LT(LOCKED THROTTLED), 고장 위치 FO·FC·FL·FAI. 'NC,FO'처럼 둘을 함께 쓴다.
# 태그가 아니라 밸브 속성(속성 사전 normal_position·fail_position)이다
POSITION_FIELD = {"NO": "normal_position", "NC": "normal_position", "LO": "normal_position", "LC": "normal_position",
                  "LT": "normal_position", "FO": "fail_position", "FC": "fail_position", "FL": "fail_position", "FAI": "fail_position"}
ACTUATOR_MARK_RE = re.compile(r"[A-Z](?: ?/ ?[A-Z])?")  # 밸브 몸통·구동부 안 표기(M, E/H 등)
POSITION_REFINES = {("NC", "LC"), ("NO", "LO")}  # (기호 모양의 값, 글자 값): 글자가 같은 상태를 더 자세히 쓴 것


def _actuated_kind(entries):
    """밸브 하나에 붙은 구동부 사전 항목들 → (kind, attributes). 범례가 정하지 않은 조합이면 (None, {})."""
    stacked = [e for e in entries if isinstance(e, _StackEntry)]
    if stacked:
        return stacked[0].kind, dict(stacked[0].attributes)
    by_type = {e.attributes.get("actuator_type"): e for e in entries}
    found = set(by_type)
    if "diaphragm" in found and found <= {"diaphragm", "solenoid"}:
        attrs = dict(by_type["diaphragm"].attributes)
        if "solenoid" in found:
            attrs["actuator_type"] = "diaphragm+solenoid_pilot"
        return "air_operated_valve", attrs
    if len(found) != 1 or not found <= set(ACTUATED_KIND):
        return None, {}  # 솔레노이드·전기유압 혼자, 전동+다이어프램 등
    return ACTUATED_KIND[next(iter(found))], dict(next(iter(entries)).attributes)


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
    return [(pts, True, ext, True) if not curved and _polygon_circle(pts) else (pts, closed, ext, curved)
            for pts, closed, ext, curved in out]


POLYGON_CIRCLE_MIN_PTS = 12      # 원을 짧은 직선으로 그린 꺾은선의 꼭짓점 수 하한(APR1400 051쪽 계기 원 65점)
POLYGON_CIRCLE_RADIUS_TOL = 0.06  # 꼭짓점의 중심 거리가 평균 반지름에서 벗어나도 되는 비율
POLYGON_CIRCLE_MAX = 15.0        # 지름 상한(pt). 계기 원(APR1400 9~14pt)만 본다


def _polygon_circle(pts):
    """짧은 직선 여러 개로 그린 원인가: 끝점이 시작점으로 돌아오고 꼭짓점이 모두 한 원 위에 있다. 이런 원은 'h' 없이
    끝나고 곡선 명령이 없어 닫힌 곡선 원으로 읽히지 않았다(051쪽 PI·HS 원 60개가 계기 원이 아니게 됨)."""
    if len(pts) < POLYGON_CIRCLE_MIN_PTS or math.dist(pts[0], pts[-1]) > 0.05:
        return False
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if not ISA_BUBBLE_MIN <= w <= POLYGON_CIRCLE_MAX or abs(w - h) > 0.1 * max(w, h):
        # 계기 원 크기만 원으로 올린다. 014쪽처럼 배관이 가운데까지 들어오는 큰 펌프 원(16pt)을 몸체로 올리면 그 배관과
        # 이웃 밸브까지 한 기호로 묶여 전동 밸브 여섯이 수동 밸브가 되었다
        return False
    c = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
    r = [math.dist(p, c) for p in pts]
    mean = sum(r) / len(r)
    return max(abs(v - mean) for v in r) <= POLYGON_CIRCLE_RADIUS_TOL * mean


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


# 글자를 낱말로 묶을 때 윗변 차 상한(pt). pdfplumber 기본값 3은 APR1400 계기 비석의 3pt 글자 두 줄(줄 간격 2.85pt,
# 'FT' 위 '1011X')을 한 낱말 '10F1T1X'로 섞는다. 같은 줄의 들쭉날쭉한 윗변은 _upright_blocks가 다시 한 줄로 묶는다
WORD_Y_TOLERANCE = 1.5


def _split_paren_tail(w):
    """'PDIS(3053)'처럼 글자에 괄호 번호가 빈칸 없이 붙은 낱말을 둘로 나눈다. 괄호 번호는 계기 원 옆 다른 계열
    번호라 _upright_blocks가 따로 두는데, 한 낱말로 오면 가를 수 없다(APR1400 9.4.5-1-S1 PDIS 3051)."""
    text = w["text"]
    i = text.find("(")
    if i <= 0 or not PAREN_TOKEN_RE.fullmatch(text[i:]) or len(w.get("chars") or ()) != len(text):
        return [w]
    head, tail = w["chars"][:i], w["chars"][i:]
    return [dict(w, text=text[:i], x1=max(c["x1"] for c in head)), dict(w, text=text[i:], x0=min(c["x0"] for c in tail))]


def _split_alarm_tails(words):
    """계기 원 옆에 줄마다 쌓아 적은 경보 표기(HHL / HL / LL)의 한 줄이 원 안 글자와 같은 줄에 틈 없이 붙어 한 낱말로 온
    것('3043AHL', 'TISHHL')을 원 안 글자와 경보 표기로 나눈다(APR1400 070·072쪽 TIS 3043A). 끝 글자가 경보 표기 꼴이고,
    그 글자의 왼쪽 끝이 바로 위나 아래 줄 경보 표기의 왼쪽 끝과 같을 때만 나눈다. 같은 열에 쌓인 표기여야 '3043H'의 H 같은
    번호 끝 문자와 가를 수 있다. 떼어 낸 표기가 다시 이웃 줄의 열 근거가 되므로 바뀌지 않을 때까지 되풀이한다.
    words: pdfplumber 낱말(chars 포함)."""
    def box(cs):
        return {"x0": min(float(c["x0"]) for c in cs), "x1": max(float(c["x1"]) for c in cs),
                "top": min(float(c["top"]) for c in cs), "bottom": max(float(c["bottom"]) for c in cs)}

    def stacked(a, x, y):  # a가 (x, y)에서 시작하는 글자의 바로 위나 아래 줄에 왼쪽 끝을 맞춰 쌓였다
        h = float(a["bottom"]) - float(a["top"])
        return abs(float(a["x0"]) - x) <= ALARM_COLUMN_TOL and \
            0.5 * h <= abs((float(a["top"]) + float(a["bottom"])) / 2 - y) <= 2 * h
    for _ in range(3):
        alarms = [w for w in words if ALARM_RE.fullmatch(w["text"])]
        out, changed = [], False
        for w in words:
            text, chars = w["text"], w.get("chars") or ()
            cut = None
            if len(chars) == len(text) and not ALARM_RE.fullmatch(text):
                for k in range(1, len(text)):
                    if ALARM_RE.fullmatch(text[k:]) and any(stacked(a, float(chars[k]["x0"]), (
                            float(chars[k]["top"]) + float(chars[k]["bottom"])) / 2) for a in alarms if a is not w):
                        cut = k
                        break
            if cut is None:
                out.append(w)
                continue
            out += [dict(w, text=text[:cut], chars=chars[:cut], **box(chars[:cut])),
                    dict(w, text=text[cut:], chars=chars[cut:], **box(chars[cut:]))]
            changed = True
        words = out
        if not changed:
            break
    return words


def _split_plates(w):
    """빈칸 없이 붙어 한 낱말로 온 밸브 번호 여럿('V705V703', 돌린 글자 'V707V717')을 번호마다 나눈다. 이웃한 두 밸브의
    번호가 글자 사이 틈 없이 찍혀 pdfplumber가 한 낱말로 읽는다(APR1400 016쪽 V703·V717, 097쪽 V4320A)."""
    text, chars = w["text"], w.get("chars") or ()
    parts = [m.span() for m in PLATE_PART_RE.finditer(text)]
    if len(parts) < 2 or "".join(text[a:b] for a, b in parts) != text or len(chars) != len(text):
        return [w]
    out = []
    for a, b in parts:
        cs = chars[a:b]
        box = {"x0": min(c["x0"] for c in cs), "x1": max(c["x1"] for c in cs),
               "top": min(c["top"] for c in cs), "bottom": max(c["bottom"] for c in cs)}
        out.append(dict(w, text=text[a:b], chars=cs, **box))
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
        upright = [w for w0 in pg.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"],
                                                y_tolerance=WORD_Y_TOLERANCE, return_chars=True)
                   if w0.get("upright", True) for w1 in _split_plates(w0) for w in _split_paren_tail(w1)]
        words = [{"text": w["text"], "x0": float(w["x0"]), "x1": float(w["x1"]), "top": float(w["top"]),
                  "bottom": float(w["bottom"]), "size": float(w.get("size") or (w["bottom"] - w["top"])),
                  "upright": True}
                 for w in _split_alarm_tails(upright)]
        # 90° 돌린 글자(아래→위로 읽음)는 char_dir_rotated="btt"로 따로 읽는다. 기본값으로 읽으면 거꾸로·한 자씩 끊긴다
        # (APR1400 DCD 'CV:RDT' → 'TDR:VC'). 돌린 글자는 글자마다 size 값이 달라 size로 낱말을 나누지 않고,
        # 줄 높이에 해당하는 낱말 폭을 size로 쓴다.
        # 돌린 글자의 줄 구분은 x_tolerance가 맡는다. 기본값 3이면 3pt 글자 두 줄('V315' 옆 'LO')을 한 낱말 'VL3O15'로
        # 섞는다(APR1400 008쪽 V310~V317, 016쪽 V715). 가로 글자의 WORD_Y_TOLERANCE와 같은 값을 쓴다
        for direction, sign in (("btt", 1), ("ttb", -1)):  # 아래→위(글자 행렬 b > 0)와 위→아래(b < 0)를 따로 읽는다
            words += [{"text": w["text"], "x0": float(w["x0"]), "x1": float(w["x1"]), "top": float(w["top"]),
                       "bottom": float(w["bottom"]), "size": float(w["x1"] - w["x0"]), "upright": False,
                       "direction": direction}
                      for w0 in pg.extract_words(keep_blank_chars=False, use_text_flow=False,
                                                 char_dir_rotated=direction, return_chars=True,
                                                 x_tolerance=WORD_Y_TOLERANCE)
                      if not w0.get("upright", True) and all((c.get("matrix") or (0, 0))[1] * sign > 0
                                                             for c in w0["chars"])
                      for w in _split_plates(w0)]
        prims = []
        for obj in list(pg.lines) + list(pg.rects) + list(pg.curves):
            prims.append({"fill": bool(obj.get("fill")), "stroke": bool(obj.get("stroke", True)),
                          "fill_white": _is_white(obj.get("non_stroking_color")),
                          "stroke_white": _is_white(obj.get("stroking_color")),
                          "dash": _dash(obj.get("dash")), "subpaths": _subpaths(obj),
                          "width": None if obj.get("linewidth") is None else _num(obj["linewidth"]),
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
            item = {"id": pid, "pts": pts, "bbox": b, "closed": closed and len(pts) >= 3, "curved": curved,
                    "pen": pr.get("width")}
            if pr.get("fine") and k < len(pr["fine"]):
                item["fine"] = pr["fine"][k]
            if pr["fill"] and pr["fill_white"]:
                if not covers:
                    white_fills.append(item)
            elif pr["fill"]:
                small, large = min(_w(b), _h(b)), max(_w(b), _h(b))
                corner = len(pts) >= 6 and not curved and large <= prm["dash_corner_max"] \
                    and not _is_convex(pts)  # 꺾인 점선 모서리(L자)는 오목하다. 볼록하면 화살촉
                thin = small <= prm["dash_thick_max"] and large <= prm["dash_long_max"]
                if thin and _is_triangle(item):
                    # 닫힌 삼각형은 점선 조각(선분을 굵게 칠한 사각형)이 아니라 화살촉이다(APR1400 105쪽 벤트 끝 1.4×2.9pt).
                    # 밸브 몸통이 되기엔 얇아 검정 견본 묶음(_black_fills)에는 넣지 않는다
                    markers.append(dict(item, thin_tip=True))
                elif thin or corner:
                    dashes.append(item)
                elif _is_half_disc(item):
                    # 검게 칠한 반달꼴은 화살촉이 아니라 다이어프램 구동부다(APR1400 063·105쪽 공기구동 밸브 위). 속 빈
                    # 반달꼴과 같이 몸체로 두어 기호 사전의 구동부 견본에 대 보게 한다
                    bodies.append(dict(item, closed=True, solid=False))
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
                polys.append(dict(item, width=pr.get("width")))

    # 검은 채움(화살촉·점선 조각·검은 몸체)과 같은 도형의 외곽선은 채움 쪽으로 본다
    def twin(a, b):
        return max(abs(a["bbox"][j] - b["bbox"][j]) for j in range(4)) <= prm["twin_tol"]
    # 외곽선을 따로 그은 검은 얇은 사각형은 점선 조각이 아니라 기호 몸체다. 실린더 구동부의 칠한 칸(범례 1.7-1 1/4 OPERATOR
    # LOADED)을 점선 조각으로 보면 옆의 흰 칸과 밸브 몸통이 떨어져 조각 노드가 된다(APR1400 134쪽 솔레노이드 밸브)
    boxed = {id(d) for d in dashes if d["closed"] and any(twin(o, d) for o in outlines)}
    bodies += [dict(d, solid=True) for d in dashes if id(d) in boxed]
    dashes = [d for d in dashes if id(d) not in boxed]
    inked = markers + dashes + bodies
    outlines = [o for o in outlines if not any(twin(o, f) for f in inked)]
    panels = _panels(outlines, white_fills, polys, outlines + bodies + dashes + markers, prm)
    used = {id(p["rect"]) for p in panels} | {id(m) for p in panels for m in p["members"]}
    rects = [p["rect"] for p in panels]
    # 판 외곽도 표 칸 찾기에는 넣는다. 판과 변을 맞댄 공조기 빈 칸은 예전처럼 표 칸으로 빠져, 칸 위로 내려온 계기 선이 칸을
    # 계기 기호에 합치지 않는다(081쪽 TI 3003)
    cells = [c for c in _table_cells(outlines, prm) if id(c) not in used]
    outlines, polys, bodies, dashes, markers = ([o for o in group if id(o) not in used]
                                                for group in (outlines, polys, bodies, dashes, markers))
    white_fills = [f for f in white_fills if id(f) not in used and not any(twin(f, r) for r in rects)]
    cell_ids = {c["id"] for c in cells}
    bodies += [dict(o, solid=False) for o in outlines if o["id"] not in cell_ids]
    traced, edge_ids = _traced_fills(white_fills, polys, prm)
    bodies += traced
    polys = [p for p in polys if p["id"] not in edge_ids]
    white_fills = [f for f in white_fills if f["id"] not in {t["id"] for t in traced}]
    domes, dome_ids = _arc_chord_bodies(polys, prm)
    bodies += domes
    polys = [p for p in polys if p["id"] not in dome_ids]
    waves, polys = _wave_bodies(polys, bodies, prm)
    bodies += waves
    # 흰 채움: 같은 bbox의 외곽(또는 표 칸)이 있으면 그 도형의 채움, 없으면 글자 바탕 마스크
    shapes = [o["bbox"] for o in outlines] + [p["bbox"] for p in polys] + [d["bbox"] for d in domes]
    masks = [f for f in white_fills
             if not any(max(abs(f["bbox"][j] - s[j]) for j in range(4)) <= prm["twin_tol"] for s in shapes)]
    return {"bodies": bodies, "polys": polys, "markers": markers, "dashes": dashes, "masks": masks,
            "frames": frames, "cells": cells, "invisible_dashed": invisible, "panels": panels}


TRACED_FILL_MIN = 10.0  # 장비 외곽으로 보는 흰 채움의 짧은 변 하한(pt). 글자 바탕 마스크·밸브 몸통 채움은 이보다 작거나 외곽선과 한 도형이다
TRACE_TOL = 0.3         # 선 위 점이 흰 채움 가장자리 위에 있다고 보는 거리(pt)
TRACE_COVER = 0.7       # 가장자리를 따라 그린 선 길이 합 ≥ 채움 묶음 상자 둘레 × 비율


def _traced_fills(white_fills, polys, prm):
    """흰 채움 도형의 가장자리를 따로 그은 열린 선들이 거의 다 덮으면 그 채움은 장비(탱크·용기) 외곽이다. APR1400 DCD는
    탱크·용기를 겹친 흰 채움 둘과, 그 가장자리를 따라 그은 열린 선(둥근 끝·곧은 변)으로 그린다. 선을 그대로 두면 외곽이
    배관 고리로 읽혀 장비 노드가 생기지 않고, 장비에 닿은 배관은 고리 위 분기점에 붙는다.
    → ([외곽 몸체(채움 도형 그대로)], {가장자리 선 id})."""
    cand = [f for f in white_fills if f["closed"] and min(_w(f["bbox"]), _h(f["bbox"])) >= TRACED_FILL_MIN]
    groups = _uf_groups(len(cand), lambda i, j: _box_gap(cand[i]["bbox"], cand[j]["bbox"]) <= prm["touch_tol"])
    bodies, edge_ids = [], set()
    for g in groups:
        fills = [cand[i] for i in g]
        if not any(f["curved"] for f in fills):
            continue  # 곧은 변뿐인 흰 상자는 설비 묶음(밸브 랙·건물 구역) 경계일 수 있다. 장비 외곽은 둥근 끝이 있다(055쪽 밸브 랙)
        edges = []
        for f in fills:
            ring = list(f.get("fine") or f["pts"])
            edges += _segs(ring + [ring[0]])
        box = fills[0]["bbox"]
        for f in fills[1:]:
            box = _union(box, f["bbox"])

        def on_edge(p):
            return any(_seg_dist(p, a, b)[0] <= TRACE_TOL for a, b in edges)

        def traces(p):
            pts = p.get("fine") or p["pts"]
            return _inside(p["bbox"][:2], box, TRACE_TOL) and _inside(p["bbox"][2:], box, TRACE_TOL) and all(
                on_edge(q) for a, b in _segs(pts) for q in (a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), b))
        found = [p for p in polys if p["id"] not in edge_ids and traces(p)]
        if sum(_poly_length(p) for p in found) < TRACE_COVER * 2 * (_w(box) + _h(box)):
            continue
        edge_ids |= {p["id"] for p in found}
        bodies += [dict(f, solid=False, traced=True) for f in fills]
    return bodies, edge_ids


def _arc_chord_bodies(polys, prm):
    """작은 곡선 선과, 그 두 끝을 잇는 곧은 선 하나가 함께 닫힌 반달꼴을 이루면 한 몸체다. APR1400 DCD는 배관 끝막음
    (범례 1.7-1 1/4 PIPE CAP)을 곧은 막음선과 반원 곡선 두 경로로 따로 긋는다. 따로 두면 배관이 막음선 가운데에 닿아
    분기점이 되고 끝막음 노드가 생기지 않는다. 종류는 몸체가 된 뒤 _classify가 정한다(끝막음 규칙은 연결 하나·글자 없음).
    → ([몸체], {쓴 선 id})."""
    tol = TRACE_TOL
    chords = [p for p in polys if len(p["pts"]) == 2 and not p.get("curved")]
    bodies, used = [], set()
    for arc in polys:
        if not arc.get("curved") or arc["id"] in used or max(_w(arc["bbox"]), _h(arc["bbox"])) > prm["pipe_cap_max"]:
            continue
        a0, a1 = arc["pts"][0], arc["pts"][-1]
        if math.hypot(a1[0] - a0[0], a1[1] - a0[1]) <= tol:
            continue  # 이미 닫힌 곡선(원)은 반달꼴이 아니다
        for ch in chords:
            c0, c1 = ch["pts"]
            if ch["id"] in used or not any(
                    math.hypot(p[0] - q[0], p[1] - q[1]) <= tol and math.hypot(r[0] - s[0], r[1] - s[1]) <= tol
                    for (p, r), (q, s) in (((a0, a1), (c0, c1)), ((a0, a1), (c1, c0)))):
                continue
            ring = list(arc.get("fine") or arc["pts"])
            bodies.append({"id": arc["id"], "pts": list(arc["pts"]), "fine": ring + [ring[0]],
                           "bbox": _union(arc["bbox"], ch["bbox"]), "closed": True, "curved": True, "solid": False})
            used |= {arc["id"], ch["id"]}
            break
    return bodies, used


WAVE_LOBES_MIN = 3      # 물결: 축 양쪽으로 번갈아 나온 굽이 수 하한(범례 1.7-1 1/4 FLEXIBLE HOSE는 굽이 셋)
WAVE_LOBE_RATIO = 0.25  # 굽이로 세는 점: 축에서 떨어진 거리 > 가장 큰 굽이 높이 × 비율
WAVE_EDGE_RATIO = 0.05  # 물결 끝: 축에서 떨어진 거리 ≤ 가장 큰 굽이 높이 × 비율인 점
WAVE_AMP_MIN = 0.5      # 굽이 높이 하한(pt). 곧은 선의 작은 떨림은 물결이 아니다


def _wave_split(pts):
    """곧은 축을 따라 가다 좌우로 번갈아 굽이친 뒤 다시 같은 축으로 곧게 나가는 꺾은선 → (들어오는 선, 물결, 나가는 선)
    점 목록. 아니면 None. 축은 두 끝점을 잇는 직선이고, 물결 앞뒤에 축 위의 곧은 선이 있어야 한다."""
    a, b = pts[0], pts[-1]
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    if L <= 0:
        return None
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    off = [(p[0] - a[0]) * -uy + (p[1] - a[1]) * ux for p in pts]
    amp = max(abs(o) for o in off)
    if amp < WAVE_AMP_MIN:
        return None
    lobes, sides = [i for i, o in enumerate(off) if abs(o) > WAVE_LOBE_RATIO * amp], []
    for i in lobes:
        s = off[i] > 0
        if not sides or sides[-1] != s:
            sides.append(s)
    if len(sides) < WAVE_LOBES_MIN:
        return None
    edge = WAVE_EDGE_RATIO * amp
    i0 = max((i for i in range(lobes[0]) if abs(off[i]) <= edge), default=None)
    i1 = min((i for i in range(lobes[-1] + 1, len(pts)) if abs(off[i]) <= edge), default=None)
    if i0 is None or i1 is None or i0 == 0 or i1 == len(pts) - 1:
        return None  # 물결 앞이나 뒤에 곧은 선이 없다(상자 안에 그린 물결 무늬 등)
    if any(abs(o) > edge for o in off[:i0] + off[i1 + 1:]):
        return None
    return pts[:i0 + 1], pts[i0:i1 + 1], pts[i1:]


def _wave_bodies(polys, shapes, prm):
    """배관 선 가운데에 그린 물결을 몸체로 떼어 낸다. APR1400 DCD는 유연 호스(범례 1.7-1 1/4 FLEXIBLE HOSE)를 배관과
    한 경로로 긋는다(곧은 선 → 반원 셋 → 곧은 선). 그대로 두면 호스가 배관의 한 토막이 되어 노드가 생기지 않고, 호스
    양쪽 기호가 바로 이어진다. 물결은 몸체로, 앞뒤 곧은 선은 같은 경로 id의 배관 조각으로 둔다. 닫힌 몸체 안에 통째로
    든 물결은 그 기호의 무늬다(062쪽 다이어프램 씰 상자 안 물결). → ([물결 몸체], 남은 선 목록)."""
    bodies, out = [], []
    for p in polys:
        cut = _wave_split(p.get("fine") or p["pts"]) if p.get("curved") else None
        if cut is not None and any(_inside(p["bbox"][:2], s["bbox"], prm["touch_tol"]) and
                                   _inside(p["bbox"][2:], s["bbox"], prm["touch_tol"]) for s in shapes):
            cut = None
        if cut is None:
            out.append(p)
            continue
        lead_in, wave, lead_out = cut
        bodies.append({"id": p["id"], "pts": list(wave), "fine": list(wave) + [wave[0]], "bbox": _bbox_pts(wave),
                       "closed": True, "curved": True, "solid": False, "wave": True})
        for pts in ((lead_in[0], lead_in[-1]), (lead_out[0], lead_out[-1])):
            out.append(dict(p, pts=list(pts), fine=list(pts), bbox=_bbox_pts(pts), curved=False))
    return bodies, out


def _is_axis_rect(o, tol):
    b = o["bbox"]
    return all(min(abs(p[0] - b[0]), abs(p[0] - b[2])) < tol and min(abs(p[1] - b[1]), abs(p[1] - b[3])) < tol
               for p in o["pts"])


def _table_cells(outlines, prm):
    """변 하나를 통째로 공유하며 이어 붙은 축 정렬 사각형 = 표 칸(표제란 등)."""
    tol = prm["table_edge_tol"]
    # 표식 크기(marker_max) 안의 작은 상자끼리 붙은 것은 표가 아니라 기호다. 실린더 구동부(범례 1.7-1 1/4 CYLINDER OPERATOR)는
    # 두 칸 상자를 밸브 몸통 옆에 그린다. 표 칸으로 빼면 밸브 몸통이 조각 노드로 남는다(APR1400 054쪽 공기 구동 밸브)
    rects = [o for o in outlines if _is_axis_rect(o, prm["axis_rect_tol"])
             and max(_w(o["bbox"]), _h(o["bbox"])) > prm["marker_max"]]
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


PANEL_LONG_MAX = 60.0   # 공조기 판: 긴 변 상한(pt). 범례 1.7-1 2/4는 7×14pt, 도면은 10~50pt
PANEL_SHORT_MIN = 5.0   # 공조기 판: 짧은 변 하한(pt). 밸브 몸통·작은 표식 칸은 판이 아니다
PANEL_LINES_MIN = 6     # 무늬 선: 두 끝이 모두 판 변에 닿은 곧은 선 수 하한(PREFILTER 빗금 19, HEPA 격자 11)
PANEL_DOTS_MIN = 12     # 무늬 점·작은 원 수 하한(CARBON ADSORBER 점 85, POSTFILTER 원 32)
PANEL_DOT_RATIO = 0.3   # 무늬 점·원: 긴 변 ≤ 판 짧은 변 × 비율
PANEL_DOT_SPREAD = 1.5  # 무늬 점·원: 가장 큰 것 ≤ 가운데 크기 × 배수(+ PANEL_EDGE_TOL)
PANEL_SNAKE_PTS = 8    # 판 폭을 가로지르며 굽이친 꺾은선의 점 수 하한(MOISTURE SEPARATOR 갈매기, 코일 지그재그)
PANEL_EDGE_TOL = 0.3    # 선 끝이 판 변 위에 있다고 보는 거리(pt)
PANEL_HOUSING_TOL = 1.0  # 공조기 칸끼리 긴 변 방향 두 변이 같다고 보는 차(pt)
PANEL_COIL_WORDS = frozenset({"HC", "CC"})  # 범례 1.7-1 2/4 HEATING COIL(HC)·COOLING COIL(CC)


def _panels(outlines, white_fills, polys, others, prm):
    """공조기(AHU) 안의 여과·코일 판(범례 1.7-1 2/4 PREFILTER·HEPA FILTER·CARBON ADSORBER·POSTFILTER·MOISTURE
    SEPARATOR·HEATING/COOLING COIL)을 찾는다. 판은 좁은 축 정렬 사각형이고 안이 무늬(변에서 변까지 그은 빗금·격자,
    작은 점·원 여럿, 폭을 가로지르며 굽이친 꺾은선)로 차 있다. 공조기 칸들과 변을 맞대고 이어 그려 표 칸으로 빠지거나,
    무늬가 낱 선·점으로 흩어져 판 하나가 노드가 되지 못하던 자리다(APR1400 072쪽). 작은 판부터 무늬를 차지해, 판을 품은
    공조기 칸은 판이 되지 않는다. 판 외곽은 사각형 외곽선이거나, 변 하나를 코일 선이 대신 그은 흰 채움(코일)이다.
    판은 공조기 칸 줄 안에 있어야 한다. 따로 선 빗금 사각형(007쪽 유연 이음 단면)·펌프 상자는 판이 아니다.
    → [{"rect": 외곽, "members": 무늬 원소들}]."""
    tol = prm["axis_rect_tol"]

    def twin(a, b):
        return max(abs(a["bbox"][j] - b["bbox"][j]) for j in range(4)) <= prm["twin_tol"]

    def boxed(f):  # 꼭짓점이 모두 상자 변 위에 있는 닫힌 채움(코일 판은 변 가운데에 꺾임 점이 더 있다)
        b = f["bbox"]
        return f["closed"] and not f["curved"] and all(min(abs(p[0] - b[0]), abs(p[0] - b[2]), abs(p[1] - b[1]), abs(p[1] - b[3])) < tol
                                   for p in f["pts"])
    rects = [o for o in outlines if _is_axis_rect(o, tol)]
    rects += [f for f in white_fills if boxed(f) and not any(twin(f, o) for o in rects)]

    def in_housing(r):  # 공조기 칸: 긴 변 방향 두 변이 같은 상자와 흐름 축으로 맞닿아 있다(판 하나만 따로 그린 범례·빗금 단면은 아니다)
        B, k = r["bbox"], 1 if _w(r["bbox"]) <= _h(r["bbox"]) else 0
        return any(o is not r and not twin(o, r) and abs(o["bbox"][k] - B[k]) <= PANEL_HOUSING_TOL
                   and abs(o["bbox"][k + 2] - B[k + 2]) <= PANEL_HOUSING_TOL and _box_gap(o["bbox"], B) <= prm["touch_tol"]
                   for o in rects)
    cands = [c for c in rects if in_housing(c) and min(_w(c["bbox"]), _h(c["bbox"])) >= PANEL_SHORT_MIN
             and max(_w(c["bbox"]), _h(c["bbox"])) <= PANEL_LONG_MAX]
    cands.sort(key=lambda c: (_w(c["bbox"]) * _h(c["bbox"]), c["id"]))
    taken, found = set(), []
    for r in cands:
        if id(r) in taken:
            continue
        B = r["bbox"]
        short = min(_w(B), _h(B))
        inner = [it for it in polys + others if id(it) not in taken and it is not r and not (it["closed"] and twin(it, r))
                 and _inside(it["bbox"][:2], B, PANEL_EDGE_TOL) and _inside(it["bbox"][2:], B, PANEL_EDGE_TOL)]

        def on_edge(p):
            return _inside(p, B, PANEL_EDGE_TOL) and min(abs(p[0] - B[0]), abs(p[0] - B[2]),
                                                         abs(p[1] - B[1]), abs(p[1] - B[3])) <= PANEL_EDGE_TOL
        strokes = [p for p in inner if any(p is q for q in polys)]
        lines = [p for p in strokes if not p["closed"] and len(p["pts"]) == 2 and not p.get("curved")
                 and on_edge(p["pts"][0]) and on_edge(p["pts"][1])]
        slopes = {round(math.degrees(math.atan2(p["pts"][1][1] - p["pts"][0][1], p["pts"][1][0] - p["pts"][0][0])) % 180 / 15)
                  % 12 for p in lines}
        if len(slopes) < 2:
            lines = []  # 범례의 여과 판 빗금은 엇갈림(PREFILTER)·격자(HEPA)다. 한 방향 빗금은 단면 표시다(_hatch_block)
        dots = [b for b in inner if b["closed"] and max(_w(b["bbox"]), _h(b["bbox"])) <= PANEL_DOT_RATIO * short]
        across = 0 if _w(B) <= _h(B) else 1
        sizes = sorted(max(_w(b["bbox"]), _h(b["bbox"])) for b in dots)
        if sizes and sizes[-1] > PANEL_DOT_SPREAD * sizes[len(sizes) // 2] + PANEL_EDGE_TOL:
            dots = []  # 무늬 점·원은 크기가 고르다. 크기가 제각각인 작은 닫힌 도형은 글자를 그린 경로다(097쪽 계기 비석)
        snakes = [p for p in strokes if not p["closed"] and not p.get("curved") and len(p["pts"]) >= PANEL_SNAKE_PTS and
                  p["bbox"][across] - B[across] <= PANEL_EDGE_TOL and B[across + 2] - p["bbox"][across + 2] <= PANEL_EDGE_TOL]
        if len(lines) < PANEL_LINES_MIN and len(dots) < PANEL_DOTS_MIN and not snakes:
            continue
        taken.add(id(r))
        taken.update(id(it) for it in inner)
        found.append({"rect": r, "members": inner})
    return found


# ---------------------------------------------------------------- 2. 선 위 빗금·점 (기호 묶기는 pdf_vector_grouping)


LONE_TICK_STROKES = 2  # 선에 묶음이 하나뿐일 때 신호 표시로 보는 빗금 수(//). 셋은 안전밸브 스프링선이다
TICK_TIE = 1e-6        # 빗금 가운데에서 두 선까지의 거리가 이 안에서 같으면 어느 선의 빗금인지 정하지 않는다(pt)
TICK_SIDE_GAP_MIN = 0.2  # 한 묶음의 두 빗금이 옆으로 떨어진 거리 하한(pt). 같은 자리에 겹쳐 그린 두 선은 // 가 아니다
SPRING_BODY_GAP = 0.5  # 외톨이 // 가 선이 닿은 작은 각진 몸체에 이 거리 안으로 붙어 있으면 스프링 자리로 본다(pt)
_EPS = 1e-9            # 각도·교차 위치 경계를 포함하게 하는 부동소수 여유


def _poly_length(p):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in _segs(p["pts"]))


def _crosses(stroke, pts):
    """직선 조각 stroke가 꺾은선 pts와 조각의 안쪽에서 만나는가. 꺾은선의 꼭짓점과 끝점 위에서 만나는 것도 센다."""
    (x0, y0), (x1, y1) = stroke
    dx, dy = x1 - x0, y1 - y0
    for a, b in _segs(pts):
        ex, ey = b[0] - a[0], b[1] - a[1]
        den = ex * dy - ey * dx
        if den == 0:
            continue
        on_line = ((x0 - a[0]) * dy - (y0 - a[1]) * dx) / den    # 만나는 점의 선분 위 자리(0~1)
        on_stroke = ((x0 - a[0]) * ey - (y0 - a[1]) * ex) / den  # 만나는 점의 조각 위 자리(0~1)
        if -_EPS <= on_line <= 1 + _EPS and 0 < on_stroke < 1:
            return True
    return False


def _beyond_ends(stroke, pts, k):
    """직선 조각 stroke가 꺾은선 pts의 k번째 선분을 그 꺾은선의 끝점 밖(연장선 위)에서 지나는가.
    꺾이는 자리(안쪽 꼭짓점) 바로 밖을 지나는 것은 끝점 밖이 아니다."""
    (x0, y0), (x1, y1) = stroke
    dx, dy = x1 - x0, y1 - y0
    a, b = pts[k], pts[k + 1]
    ex, ey = b[0] - a[0], b[1] - a[1]
    at = ((x0 - a[0]) * dy - (y0 - a[1]) * dx) / (ex * dy - ey * dx)  # 만나는 점의 선분 위 자리(0~1)
    return (k == 0 and at < -_EPS) or (k == len(pts) - 2 and at > 1 + _EPS)


def _tick_groups(polys, hosts, prm, within_ends=False):
    """빗금 후보를 걸린 선마다 묶는다 → {선 id: [묶음]}, 묶음 = [(빗금 가운데, 빗금 방향, 빗금 조각)].
    빗금 후보: 4pt 이하 직선 조각이 열린 선(hosts)을 비스듬히(30~80도, 경계 포함) 가로지른다(두 끝이 선의 양쪽에 떨어져
    있음). 선에 한 끝만 닿은 짧은 탭·가지는 가로지르지 않으므로 후보가 아니다. 각도와 가로지름은 가장 가까운 선분의
    연장선으로 본다. 꺾이는 자리에 걸친 빗금은 꼭짓점 바로 밖을 지나기 때문이다(032·120·135쪽).
    within_ends: 선의 끝점 밖(연장선 위)을 지나는 조각을 뺀다. 묶음 하나로 판정하는 외톨이 // 에만 쓴다. 묶음이 여럿인
    신호선에는 선 끝 바로 밖에 그린 // 가 있다(121·126쪽, 다른 선과 만나는 자리).
    후보는 가장 가까운 선 하나에만 딸린다. 두 선까지의 거리가 같으면(두 선이 만나는 점 위) 어느 선에도 붙이지 않는다.
    먼저 그린 선에 붙이면 그리는 순서에 따라 판정이 달라진다.
    서로 가깝고 평행하며 옆으로 떨어진 후보 2~3개가 묶음 하나다(4개 이상은 해칭)."""
    lo, hi = math.cos(math.radians(prm["tick_angle_max"])), math.cos(math.radians(prm["tick_angle_min"]))
    reach = prm["tick_host_dist"]
    cand = collections.defaultdict(list)
    for p in polys:
        tl = _poly_length(p)
        if len(p["pts"]) != 2 or not 0.3 <= tl <= prm["tick_len_max"]:
            continue
        (x0, y0), (x1, y1) = p["pts"]
        mid, dx, dy = ((x0 + x1) / 2, (y0 + y1) / 2), x1 - x0, y1 - y0
        crossed = {}  # 가로지른 선 id → (빗금 가운데와의 거리, 선분 번호). 그 선의 선분 가운데 가장 가까운 것
        for q in hosts:
            box = q["bbox"]
            if q is p or not (box[0] - reach <= mid[0] <= box[2] + reach and box[1] - reach <= mid[1] <= box[3] + reach):
                continue
            for k, (a, b) in enumerate(_segs(q["pts"])):
                d = _seg_dist(mid, a, b)[0]
                if d > reach or (q["id"] in crossed and d >= crossed[q["id"]][0]):
                    continue
                ex, ey = b[0] - a[0], b[1] - a[1]
                el = math.hypot(ex, ey)
                if el <= 0:
                    continue
                cos = abs(dx * ex + dy * ey) / (math.hypot(dx, dy) * el)
                s0 = (ex * (y0 - a[1]) - ey * (x0 - a[0])) / el  # 두 끝의 선 기준 부호 있는 거리
                s1 = (ex * (y1 - a[1]) - ey * (x1 - a[0])) / el
                # 30도로 가운데를 지나는 빗금은 두 끝이 선에서 정확히 길이의 1/4만큼 떨어진다(경계가 겹친다)
                if lo - _EPS <= cos <= hi + _EPS and s0 * s1 < 0 and min(abs(s0), abs(s1)) >= 0.25 * tl - _EPS:
                    crossed[q["id"]] = (d, k)
            if within_ends and q["id"] in crossed and _beyond_ends(p["pts"], q["pts"], crossed[q["id"]][1]):
                del crossed[q["id"]]
        if crossed:
            nearest = min(d for d, _ in crossed.values())
            owners = [h for h, (d, _) in crossed.items() if d <= nearest + TICK_TIE]
            if len(owners) == 1:
                cand[owners[0]].append((mid, (dx, dy), p))
    out = {}
    for host, items in cand.items():
        def near(i, j):
            (m, d, _), (m2, d2, _) = items[i], items[j]
            gap, size = (m2[0] - m[0], m2[1] - m[1]), math.hypot(*d)
            return (math.hypot(*gap) <= prm["tick_pair_gap"]
                    and abs(d[0] * d2[1] - d[1] * d2[0]) <= 0.2 * size * math.hypot(*d2)
                    and abs(gap[0] * d[1] - gap[1] * d[0]) >= TICK_SIDE_GAP_MIN * size)
        out[host] = [[items[i] for i in g] for g in _uf_groups(len(items), near) if 2 <= len(g) <= 3]
    return out


def _group_center(group):
    return (sum(m[0] for m, _, _ in group) / len(group), sum(m[1] for m, _, _ in group) / len(group))


def _crowded(line, pair, polys, prm):
    """외톨이 // 의 두 빗금 말고도 그 선을 가로지르거나 선에 닿은 짧은 직선 조각이 있는가.
    셋째 스프링선이 길이·각도·묶음 거리 때문에 빗금 후보에서 빠졌거나, 한 선에 해칭이 같이 있거나, 탭이 닿아 있는
    자리다. 꺾이는 자리에서 선의 끝에 제 끝을 맞댄 조각은 선의 이어짐이라 세지 않는다(끝이 조금 삐져나와 선을 넘어도)."""
    reach, longest = prm["tick_host_dist"], 2 * prm["tick_len_max"]
    box, segs, ends = line["bbox"], list(_segs(line["pts"])), (line["pts"][0], line["pts"][-1])
    for s in polys:
        if s is line or any(s is p for p in pair) or len(s["pts"]) != 2 or _poly_length(s) > longest:
            continue
        if _box_gap(s["bbox"], box) > reach:
            continue
        off = [min(_seg_dist(e, c, d)[0] for c, d in segs) for e in s["pts"]]  # 조각의 두 끝과 선 사이 거리
        at_end = [any(math.hypot(e[0] - h[0], e[1] - h[1]) <= prm["end_tol"] for h in ends) for e in s["pts"]]
        if any(o <= reach and not e for o, e in zip(off, at_end)):
            return True  # 한 끝이 선 가운데에 닿아 있다
        corner = any(o <= prm["touch_tol"] and e for o, e in zip(off, at_end))
        if not corner and _crosses(s["pts"], line["pts"]):
            return True
    return False


def _on_small_body(line, pair, bodies, prm):
    """외톨이 // 가 그 선이 닿은 작은 각진 몸체(밸브 몸통)에 붙어 있는가. 스프링선은 몸통 바로 위 줄기에 걸리고,
    공압 신호 표시는 선 가운데에 있다. 스프링선을 둘만 그린 안전밸브의 줄기를 공압 신호선으로 읽지 않으려는 조건이다."""
    box = _union(pair[0]["bbox"], pair[1]["bbox"])
    return any(not b.get("curved") and max(_w(b["bbox"]), _h(b["bbox"])) <= prm["pipe_cap_max"]
               and _box_gap(box, b["bbox"]) <= SPRING_BODY_GAP
               and _poly_box_dist(line["pts"], b["bbox"]) <= prm["attach_tol"] for b in bodies)


def _line_ticks(polys, prm, bodies=()):
    """신호선 빗금(//) 찾기(범례 1.7-1 4/4 공압 신호선). → (빗금 id 집합, {선 id: [빗금 묶음 가운데]}).
    빗금 묶음이 tick_pairs_min개 이상인 tick_host_min 이상 선은 신호선이고, 그 묶음은 모두 빗금이다.
    묶음이 하나뿐인 선(외톨이)은 빗금이 정확히 둘(//)이고 선이 빗금보다 길 때만 신호 표시로 본다. 계기 공기 공급선과
    I/P 변환기~구동부 선처럼 짧은 공압선이 이렇다(선 길이 하한 없음). 빗금 셋은 안전밸브 줄기의 스프링선이라 건드리지
    않는다(APR1400 104쪽 안전밸브, docs/units/2026-11-11-unit-f1/README.md F1-4). 헷갈리는 자리는 판정하지 않고 선을 그대로
    둔다: 빗금이 선의 끝점 밖을 지나거나, 그 선에 빗금 비슷한 조각이 더 있거나(_crowded), // 가 밸브 몸통에 붙어
    있을 때다(_on_small_body)."""
    ticks, marked = set(), {}
    hosts = [p for p in polys if _poly_length(p) >= prm["tick_host_min"]]
    for host, groups in _tick_groups(polys, hosts, prm).items():
        if len(groups) >= prm["tick_pairs_min"]:
            ticks.update(p["id"] for g in groups for _, _, p in g)
            marked[host] = [_group_center(g) for g in groups]
    rest = [p for p in polys if p["id"] not in ticks]
    by_id = {p["id"]: p for p in rest}
    for host, groups in _tick_groups(rest, rest, prm, within_ends=True).items():
        if host in marked or len(groups) != 1 or len(groups[0]) != LONE_TICK_STROKES:
            continue
        line, pair = by_id[host], [p for _, _, p in groups[0]]
        if any(_poly_length(p) >= _poly_length(line) for p in pair):
            continue
        if _crowded(line, pair, rest, prm) or _on_small_body(line, pair, bodies, prm):
            continue
        ticks.update(p["id"] for p in pair)
        marked[host] = [_group_center(groups[0])]
    return ticks, marked


def _line_dots(dashes, polys, prm):
    """실선 위 점(매설 배관 무늬, 범례 1.7-1 1/4 BURIED PIPE) 찾기 → 점 id 집합.
    점: 긴 변 dot_max 이하이고 꽉 찬(면적이 상자의 절반 이상) 정사각형에 가까운 채운 조각이 실선 조각 위 dot_host_dist
    안에 있다. 같은 선에 dots_min개 이상일 때만 장식으로 본다. 점선 경로 위 점(신호선 분기점 점)과 선에서 떨어진 점
    (열선 추적 표시)은 건드리지 않는다. APR1400의 매설 배관은 실선이나 채운 조각으로 그려져 선 종류는 바꾸지 않는다."""
    hosts = [(p["id"], a, b) for p in polys for a, b in _segs(p["pts"])]
    on = collections.defaultdict(list)
    for d in dashes:
        if "src" in d:
            continue
        w, h = _w(d["bbox"]), _h(d["bbox"])
        if max(w, h) > prm["dot_max"] or max(w, h) > 1.6 * max(min(w, h), 1e-6):
            continue
        pts = d.get("fine") or d["pts"]
        area = abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))) / 2
        if area < 0.5 * w * h:  # 꽉 찬 점·작은 네모만. 상자만 정사각형인 가는 대각 대시는 점이 아니다
            continue
        c = _center(d["bbox"])
        best = None
        for hid, a, b in hosts:
            dist = _seg_dist(c, a, b)[0]
            if dist <= prm["dot_host_dist"] and (best is None or dist < best[0]):
                best = (dist, hid)
        if best is not None:
            on[best[1]].append(d["id"])
    return {i for ids in on.values() if len(ids) >= prm["dots_min"] for i in ids}


# ---------------------------------------------------------------- 3. 연결

def _attach(p, syms, markers, prm):
    s = _nearest_sym(p, syms, prm["attach_tol"])
    if s is not None and s.seed is None:
        # 큰 묶음 기호의 상자 안에 닫힌 밸브(seed)가 들어 있으면 상자 거리로는 큰 기호가 이긴다. 선 끝이 그 밸브에
        # 닿았으면 밸브에 붙인다
        s = _nearest_sym(p, [t for t in syms if t.seed is not None], prm["end_tol"]) or s
    if s is not None:
        return s, "pdf_path_endpoint"
    for m in markers:
        if _inside(p, m["bbox"], prm["end_tol"]):
            s = None
            best = None
            for c in syms:
                d = _reach_box(m["bbox"], c)
                if d <= prm["attach_tol"] and (best is None or d < best):
                    best, s = d, c
            if s is not None:
                return s, "pdf_arrowhead"
    return None, None


def _crossing_gaps(pieces, free, prm):
    """엇갈림 끊김 찾기. 기호에 붙지 않은 선 끝 둘이 같은 제3의 선 한 자리를 사이에 두고 양쪽에서 그 선에 닿고(end_tol 안),
    두 끝이 서로 마주 보며 한 줄로 놓이고(바깥 방향이 반대, 제3의 선과 거의 수직), 두 끝 거리가 crossing_gap_max 안이면
    끊어 그린 엇갈림이다. → (분기로 나누지 않을 끝 {(조각, k)}, 이어 줄 끝 점 짝 [(p, q)])."""
    near = []
    for i, k, pt in free:
        pts = pieces[i]["pts"]
        if len(pts) < 2:
            continue
        prev = pts[1] if k == 0 else pts[-2]
        L = math.hypot(pt[0] - prev[0], pt[1] - prev[1])
        if L == 0:
            continue
        out = ((pt[0] - prev[0]) / L, (pt[1] - prev[1]) / L)
        for j, pc in enumerate(pieces):
            if j == i:
                continue
            for a, b in _segs(pc["pts"]):
                d, q = _seg_dist(pt, a, b)
                if d > prm["end_tol"]:
                    continue
                sl = math.hypot(b[0] - a[0], b[1] - a[1])
                if sl == 0 or min(math.hypot(q[0] - e[0], q[1] - e[1]) for e in (a, b)) <= prm["end_tol"]:
                    continue
                u = ((b[0] - a[0]) / sl, (b[1] - a[1]) / sl)
                if abs(out[0] * u[0] + out[1] * u[1]) > 0.5:
                    continue
                side = u[0] * (pt[1] - a[1]) - u[1] * (pt[0] - a[0])
                near.append((i, k, pt, out, j, q, side))
                break
    crossed, pairs = set(), []
    for n1, (i1, k1, p1, o1, j1, q1, s1) in enumerate(near):
        for i2, k2, p2, o2, j2, q2, s2 in near[n1 + 1:]:
            if j1 != j2 or i1 == i2 or s1 * s2 >= 0 or (i1, k1) in crossed or (i2, k2) in crossed:
                continue
            if o1[0] * o2[0] + o1[1] * o2[1] > -0.9 or math.hypot(q1[0] - q2[0], q1[1] - q2[1]) > prm["end_tol"] * 2:
                continue
            if math.hypot(p1[0] - p2[0], p1[1] - p2[1]) > prm["crossing_gap_max"]:
                continue
            crossed.update({(i1, k1), (i2, k2)})
            pairs.append((p1, p2))
    return crossed, pairs


def _crossing_strokes(pieces, att, prm):
    """기호에 붙인 선 끝 둘이 그 기호의 곧은 선 하나를 사이에 두고 끊어 그린 엇갈림(_crossing_gaps와 같은 모양)이면
    {(조각, k): (짝 (조각, k), 점)}. 가로지른 선이 기호에 묶인 선이라 끝이 기호에 붙었을 뿐, 배관은 그 선을 건너간다
    (APR1400 134쪽: LS 012 지시선이 LS 원·플랜지와 한 기호로 묶이고, 그 선을 끊어 건너는 AOV 256 배관의 두 끝이 그
    기호에 붙어 탱크·배수 깔때기와 AOV가 이어진다). 두 끝이 같은 굵기·한 줄·맞은편이고 선에 거의 수직일 때만 본다."""
    by_sym = collections.defaultdict(list)
    for (i, k), (s, basis) in att.items():
        if basis == "pdf_path_endpoint" and len(pieces[i]["pts"]) >= 2:
            by_sym[id(s)].append((i, k, s))
    out = {}
    for ends in by_sym.values():
        if len(ends) < 2:
            continue
        segs = [(a, b) for m in ends[0][2].strokes for a, b in _segs(m["pts"])]
        near = []
        for i, k, _ in ends:
            pts = pieces[i]["pts"]
            pt, prev = (pts[0], pts[1]) if k == 0 else (pts[-1], pts[-2])
            L = math.hypot(pt[0] - prev[0], pt[1] - prev[1])
            if L == 0:
                continue
            o = ((pt[0] - prev[0]) / L, (pt[1] - prev[1]) / L)
            for n, (a, b) in enumerate(segs):
                d, q = _seg_dist(pt, a, b)
                sl = math.hypot(b[0] - a[0], b[1] - a[1])
                if d > prm["end_tol"] or sl == 0 or \
                        min(math.hypot(q[0] - e[0], q[1] - e[1]) for e in (a, b)) <= prm["end_tol"]:
                    continue
                u = ((b[0] - a[0]) / sl, (b[1] - a[1]) / sl)
                if abs(o[0] * u[0] + o[1] * u[1]) > 0.5:
                    continue
                near.append((i, k, pt, o, n, q, u[0] * (pt[1] - a[1]) - u[1] * (pt[0] - a[0])))
                break
        for x, (i1, k1, p1, o1, n1, q1, s1) in enumerate(near):
            for i2, k2, p2, o2, n2, q2, s2 in near[x + 1:]:
                if n1 != n2 or i1 == i2 or s1 * s2 >= 0 or (i1, k1) in out or (i2, k2) in out:
                    continue
                if o1[0] * o2[0] + o1[1] * o2[1] > -0.9 or math.hypot(q1[0] - q2[0], q1[1] - q2[1]) > prm["end_tol"] * 2:
                    continue
                if math.hypot(p1[0] - p2[0], p1[1] - p2[1]) > prm["crossing_gap_max"] or \
                        pieces[i1].get("width") != pieces[i2].get("width"):
                    continue
                out[(i1, k1)] = ((i2, k2), p1)
                out[(i2, k2)] = ((i1, k1), p2)
    return out


def _arm_dir(pts, k):
    """꺾은선 pts의 끝 k(0 = 처음, 1 = 마지막)에서 선 안쪽으로 향하는 단위 벡터. 길이가 없으면 None."""
    seq = pts if k == 0 else pts[::-1]
    for q in seq[1:]:
        dx, dy = q[0] - seq[0][0], q[1] - seq[0][1]
        L = math.hypot(dx, dy)
        if L > 1e-6:
            return dx / L, dy / L
    return None


def _width_crossing(members, pieces, prm):
    """한 자리에 모인 선 끝 무리가 굵기가 뚜렷이 다른 두 선의 네 갈래 교차인지 본다. 끝들의 방향이 네 갈래이고 마주 보는
    두 갈래씩 두 선으로 나뉘며, 한 선 안의 굵기는 같고 두 선의 굵기 비가 crossing_width_ratio 이상이면 교차다(APR1400
    072쪽: 0.13pt 방 경계선이 1.08pt 덕트를 가로지른다. 경계선은 같은 자리에 두 번 그려 끝이 겹치기도 한다). 배관 분기는
    같은 굵기로 그리므로 굵기가 다른 두 선은 이 자리에서 잇지 않는다. → 교차면 두 선의 무리 안 순번 목록, 아니면 None."""
    if len(members) < 4:
        return None
    dirs = [_arm_dir(pieces[i]["pts"], k) for i, k, _ in members]
    widths = [pieces[i].get("width") for i, _, _ in members]
    if any(d is None for d in dirs) or any(not w for w in widths):
        return None
    arms = []  # 같은 방향 끝 순번 목록
    for a, d in enumerate(dirs):
        arm = next((m for m in arms if d[0] * dirs[m[0]][0] + d[1] * dirs[m[0]][1] > 0.97), None)
        if arm is None:
            arms.append([a])
        else:
            arm.append(a)
    if len(arms) != 4:
        return None

    def opposite(p, q):
        u, v = dirs[p[0]], dirs[q[0]]
        return u[0] * v[0] + u[1] * v[1] < -0.97
    mate = [j for j in (1, 2, 3) if opposite(arms[0], arms[j])]
    if len(mate) != 1:
        return None
    rest = [arms[j] for j in (1, 2, 3) if j != mate[0]]
    if not opposite(*rest):
        return None
    lines = [arms[0] + arms[mate[0]], rest[0] + rest[1]]
    line_w = []
    for line in lines:
        ws = [widths[a] for a in line]
        if max(ws) > 1.25 * min(ws):
            return None
        line_w.append(min(ws))
    if max(line_w) < prm["crossing_width_ratio"] * min(line_w):
        return None
    return lines


THROUGH_CENTER_RATIO = 0.15  # 몸체를 지나가는 배관: 가운데 줄에서 벗어난 거리 ≤ 몸체 옆 폭 × 비율
THROUGH_WALL_COS = 0.95      # 담는 외곽 변에서 끝을 맞댄 두 선이 곧게 이어진다고 보는 방향 코사인(약 18도 안)


def _cut_through_bodies(pieces, syms, prm):
    """기호 몸체를 흐름 축(_flow_axis) 방향으로 가운데 줄을 따라 끊기지 않고 지나가는 배관을 몸체 양 끝에서 나눈다.
    선 하나로 그은 배관 위에 밸브를 얹어 그리면 선 끝이 몸체에 닿지 않아 밸브에 배관이 붙지 않고, 양쪽 이웃이 밸브를
    건너 바로 이어진다(APR1400 105쪽 전동 밸브, 128쪽 축소관). 축을 가로지르는 선, 몸체 옆이나 모서리를 지나는 선,
    축을 모르는 몸체는 나누지 않는다. → (새 조각 목록, 몸체에 붙인 끝 {(조각, k): (기호, basis)})."""
    # 담는 외곽(방 경계·탱크)을 지나는 선은 그 안으로 들어가는 배관이다. 외곽 변에서 나누지 않는다.
    # 곧은 변 정사각형 몸체(댐퍼·마름모 밸브)는 흐름 축을 모른다. 가운데 줄을 따라 마주 보는 두 변을 꿰뚫는 선은 어느 축이든
    # 그 몸체 밑을 지나는 배관이다(APR1400 072쪽 댐퍼 Y1202A: 덕트 하나가 흰 채움 몸체 밑을 지나간다)
    axes = []
    for s in syms:
        if not s.alive or s.seed is not None or s.rings:
            continue
        ax = _flow_axis(s, prm)
        if ax is not None:
            axes.append((s, (ax,)))
        elif s.bodies and not s.stroke_only and not any(b.get("curved") for b in s.bodies) and \
                max(_w(s.core), _h(s.core)) < FLOW_LONG_RATIO * min(_w(s.core), _h(s.core)):
            # 두 축 모두로 선이 꿰뚫는 상자는 두 배관이 엇갈리는 자리에 얹은 글자 상자다(105쪽 PC 0612). 나누지 않는다
            crossed = {ax for ax in (0, 1) for pc in pieces if _box_gap(_bbox_pts(pc["pts"]), s.core) <= 0
                       and _cut_through(pc["pts"], s.core, ax, THROUGH_CENTER_RATIO * (s.core[3 - ax] - s.core[1 - ax]))}
            if len(crossed) == 1:
                axes.append((s, tuple(crossed)))
    out, att = [], {}
    for pc in pieces:
        parts = [(pc["pts"], None, None)]  # (점, 앞 끝 기호, 뒤 끝 기호)
        box = _bbox_pts(pc["pts"])
        for s, sides in axes:
            if _box_gap(box, s.core) > 0:
                continue
            for ax in sides:
                lateral = THROUGH_CENTER_RATIO * (s.core[3 - ax] - s.core[1 - ax])
                cut = []
                for pts, s0, s1 in parts:
                    halves = _cut_through(pts, s.core, ax, lateral)
                    cut += [(halves[0], s0, s), (halves[1], s, s1)] if halves else [(pts, s0, s1)]
                parts = cut
        for pts, s0, s1 in parts:
            for k, s in ((0, s0), (1, s1)):
                if s is not None:
                    att[(len(out), k)] = (s, "pdf_path_through_body")
            out.append(dict(pc, pts=pts))
    return out, att


def _arrow_lands(arrow, i, pieces, prm):
    """조각 i 끝의 바깥 화살촉(화살촉, 끝 점)의 끝이 다른 조각에 비스듬히(화살촉 축과 나란하지 않게) 닿는가.
    화살촉 축과 나란한 선은 그 화살촉이 얹힌 같은 배관이다. 화살촉 너머로 이어지는 토막(SNP-M-401 스캔: 체크밸브 앞
    1.7pt 토막)이나 화살촉 밑에 겹쳐 그은 배관(APR1400 32번 쪽)은 늘이지 않아도 이어져 있고, 늘이면 되돌아가는 사슬이
    된다."""
    tip, d = arrow[1], arrow_axis(arrow[0])[1]
    for j, pc in enumerate(pieces):
        if j == i:
            continue
        for a, b in _segs(pc["pts"]):
            L = math.dist(a, b)
            if L > 0 and _seg_dist(tip, a, b)[0] <= prm["end_tol"] and \
                    abs((b[0] - a[0]) * d[0] + (b[1] - a[1]) * d[1]) / L <= 0.9:
                return True
    return False


def _build_solid(syms, polys, markers, prm, bridges=(), mouths=()):
    """→ (tees [(x, y)], chains [{pts, ends:[(vertex, point, basis)], evidence}])."""
    # 선 끝 분류
    pieces = [{"pts": list(p["pts"]), "id": p["id"], "width": p.get("width")} for p in polys]
    pieces, att = _cut_through_bodies(pieces, syms, prm)
    ends = []  # (piece index, k, point)
    for i, pc in enumerate(pieces):
        ends += [(i, k, pt) for k, pt in ((0, pc["pts"][0]), (1, pc["pts"][-1])) if (i, k) not in att]
    free = []
    # 주머니 입구(_pockets): 입구에서 주머니 안쪽으로 짧은 선을 두어 배관을 그 자리에서 나누고 주머니 기호에 잇는다
    for pt, s in mouths:
        if s.alive:
            pieces.append({"pts": [pt, _center(s.bbox)], "id": s.evidence()[0], "width": None})
            att[(len(pieces) - 1, 1)] = (s, "pdf_path_endpoint")
            free.append((len(pieces) - 1, 0, pt))
    cell = 4 * prm["end_tol"]
    end_grid = collections.defaultdict(list)
    for i, k, pt in ends:
        end_grid[(int(pt[0] // cell), int(pt[1] // cell))].append((i, pt))

    def corner_beside(i, pt, s):
        # 선들이 끝끼리만 맞닿고(서로 상대 선 중간에 얹히지 않음) 그 자리가 기호에 닿지 않는가. 셋 이상이 끝끼리 만나는
        # 분기점도 같다(APR1400 134쪽 AOV 001 오른쪽: 6" 관 셋이 만나는 자리가 번호 원 001에서 1.3pt 떨어져 있다)
        cx, cy = int(pt[0] // cell), int(pt[1] // cell)
        others = [(j, q) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j, q in end_grid.get((cx + dx, cy + dy), ())
                  if j != i and math.hypot(q[0] - pt[0], q[1] - pt[1]) <= prm["end_tol"]]
        if not others or _pt_box_dist(pt, s.bbox) <= prm["touch_tol"]:
            return False
        # 셋 이상이 만나는 분기점은 원 하나(짧은 빗금만 곁들인 번호 원·계기 원)인 기호 옆일 때만 본다. 밸브·오리피스
        # 몸통 옆 분기점은 몸통 포트에 붙은 분기라 예전처럼 몸통에 붙인다. 구동부 크기 원(전동기 M 원 약 4pt, 정상 위치
        # N 원)은 밸브 축에 붙는 기호라 넣지 않는다(actuator_body_max 이하. 번호 원·계기 원은 9pt 이상)
        circle = s.bodies[0] if len(s.bodies) == 1 and _is_circle(s.bodies[0], prm) else None
        if len(others) > 1 and not (circle and not circle.get("actuator") and
                                    _w(circle["bbox"]) > prm["actuator_body_max"] and
                                    all(_poly_length(m) < 0.5 * _w(circle["bbox"]) for m in s.strokes)):
            return False
        return all(_pt_box_dist(q, s.bbox) > prm["touch_tol"] and _meets_at_end(pt, pieces[j]["pts"], q) and
                   _meets_at_end(q, pieces[i]["pts"], pt) for j, q in others)
    def through_wall(i, k, pt):
        # 담는 외곽 변에서 두 선이 끝을 맞대고 곧게 이어지면 배관이 벽을 지나 안으로 들어간다(012쪽 IRWST 위에서 살포기로
        # 내려가는 배관이 탱크 윗변에서 두 경로로 나뉘어 그려진다). 외곽에 붙이면 배관이 외곽에서 끊긴다
        def out_dir(pts, kk):
            a, b = (pts[1], pts[0]) if kk == 0 else (pts[-2], pts[-1])
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            return ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L else None
        d = out_dir(pieces[i]["pts"], k)
        cx, cy = int(pt[0] // cell), int(pt[1] // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j, q in end_grid.get((cx + dx, cy + dy), ()):
                    if j == i or math.hypot(q[0] - pt[0], q[1] - pt[1]) > prm["end_tol"]:
                        continue
                    pj = pieces[j]["pts"]
                    e = out_dir(pj, 0 if pj[0] == q else 1)
                    if d and e and d[0] * e[0] + d[1] * e[1] <= -THROUGH_WALL_COS:
                        return True
        return False
    for i, k, pt in ends:
        # 바깥을 가리키는 화살촉 안에서 끝난 선은 화살촉 끝이 배관 끝이다. 그 끝에 닿은 기호에만 붙이고, 화살촉 밑동 옆을
        # 스치는 기호에는 붙이지 않는다(APR1400 105쪽 벤트 관이 지붕 빗금 묶음 사이 틈을 지나 화살촉에서 끝난다)
        arrow = end_arrow(pieces[i]["pts"], k, markers, prm)
        s, basis = _attach(arrow[1], syms, (), prm) if arrow else _attach(pt, syms, markers, prm)
        # 두 선이 끝을 맞댄 모서리가 기호 옆을 닿지 않고 지나면 그 모서리는 배관이 꺾이는 자리다. 기호에 붙이면 배관이
        # 그 기호에서 둘로 갈린다(APR1400 008쪽: MOV 상승관 꼭대기 모서리가 TEW 상자 변에서 1.8pt 떨어져 있다)
        if s is not None and basis == "pdf_path_endpoint" and corner_beside(i, pt, s):
            s = None
        if s is not None and s.rings and through_wall(i, k, pt):
            s = None
        if s is not None:
            att[(i, k)] = (s, basis)
        elif arrow and _arrow_lands(arrow, i, pieces, prm):
            # 화살촉 끝이 다른 배관에 닿으면 그 배관으로 흘러드는 분기·꺾임이다(APR1400 033쪽 V1022A 위). 선 끝을 화살촉
            # 끝까지 늘여 분기·끝 묶기가 화살촉 끝에서 이뤄지게 한다
            pts = pieces[i]["pts"]
            pieces[i]["pts"] = [arrow[1]] + pts[1:] if k == 0 else pts[:-1] + [arrow[1]]
            free.append((i, k, arrow[1]))
        else:
            free.append((i, k, pt))
    # 엇갈림 끊김(도면 관례: 한쪽 선을 다른 선 앞뒤에서 끊어 그림)은 분기가 아니라 그 선을 건너 이어지는 배관이다
    over = _crossing_strokes(pieces, att, prm)
    for ik in over:
        del att[ik]
    free += [(i, k, pt) for (i, k), (_, pt) in over.items()]
    crossed, gap_bridges = _crossing_gaps(pieces, free, prm)
    crossed |= set(over)
    gap_bridges += [(pt, over[mate][1]) for ik, (mate, pt) in over.items() if ik < mate]
    bridges = list(bridges) + gap_bridges
    # 선 끝이 다른 선 중간에 닿으면 그 선을 나눈다(분기)
    splits = {}
    for i, k, pt in free:
        if (i, k) in crossed:
            continue
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
                    new_pieces.append({"pts": pts, "id": pc["id"], "width": pc["width"]})
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
    def bridged(p, q):  # 플랜지 연결로 지운 판 양쪽의 배관 끝(_plate_assemblies)
        return any((p == x and q == y) or (p == y and q == x) for x, y in bridges)
    groups = _uf_groups(len(pend), lambda a, b: math.hypot(pend[a][2][0] - pend[b][2][0],
                                                           pend[a][2][1] - pend[b][2][1]) <= prm["end_tol"]
                        or same_marker(pend[a][2], pend[b][2]) or bridged(pend[a][2], pend[b][2]))
    vertex = {}
    tees = []
    for g in groups:
        members = [pend[a] for a in g]
        cx = sum(m[2][0] for m in members) / len(members)
        cy = sum(m[2][1] for m in members) / len(members)
        through = _width_crossing(members, pieces, prm)
        if through:  # 굵기가 다른 두 선의 네 갈래 교차: 분기가 아니라 각 선이 곧게 지나간다(겹쳐 그린 선은 제 분기점)
            parts = []
            for n, line in enumerate(through):
                if len(line) == 2:
                    parts.append(([members[a] for a in line], ("pass", (g[0], n))))
                else:
                    parts.append(([members[a] for a in line], ("tee", len(tees))))
                    tees.append((cx, cy))
        elif len(members) >= 3:
            parts = [(members, ("tee", len(tees)))]
            tees.append((cx, cy))
        else:
            parts = [(members, ("pass" if len(members) == 2 else "free", g[0]))]
        for part, v in parts:
            for m in part:
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


STUB_LEN_MAX = 6.0  # 배관 끝 장식의 짧은 선 길이 상한(pt). 097쪽 호스 연결 ⊔ 팔 약 5pt, 128쪽 벤트 끝 눈금 반쪽 약 1pt


def _stub_ends(tees, chains):
    """배관 하나가 끝나는 분기점에 짧은 선 둘 이상이 매달려 끝이 비어 있으면, 그 분기점은 배관이 갈라지는 자리가 아니라
    배관 끝에 그린 끝 기호다(범례 1.7-1의 호스 연결 ⊔, 벤트 끝 눈금, 시험 연결 등). 그대로 두면 배관이 갈래 없는
    분기점에서 끝나 끝 기호 노드가 생기지 않는다. 매달린 짧은 선들로 선 기호를 만들어 배관 끝을 잇는다(종류는 _classify가
    정한다). → (새 기호 목록, 남은 사슬 목록, 남은 분기점 목록). 남은 분기점 번호에 맞춰 사슬 끝을 고쳐 쓴다."""
    at = collections.defaultdict(list)
    for ch in chains:
        for k in (0, 1):
            if ch["ends"][k][0][0] == "tee":
                at[ch["ends"][k][0][1]].append((ch, k))
    made, gone, dead = [], set(), set()
    for t, inc in sorted(at.items()):
        # 짧은 선의 두 끝이 모두 이 분기점에 묶인 것(벤트 끝 눈금처럼 짧아 양 끝이 배관 끝 가까이 모인 것)도 매달린 선이다
        stubs = [(ch, k) for ch, k in inc if not ch.get("dashed") and _poly_length({"pts": ch["pts"]}) <= STUB_LEN_MAX
                 and (ch["ends"][1 - k][0][0] == "free" or ch["ends"][1 - k][0] == ("tee", t))]
        rest = [(ch, k) for ch, k in inc if all(ch is not s for s, _ in stubs)]
        # 남은 하나가 짧은 선이면 배관이 아니라 옆 기호의 축이다(008쪽 V236 위 T자 손잡이: 밸브에서 5.7pt 올라온 축 끝의 가로대)
        if len(stubs) < 2 or len(rest) != 1 or len(inc) != len(stubs) + 1 or \
                _poly_length({"pts": rest[0][0]["pts"]}) <= STUB_LEN_MAX:
            continue
        own = list({id(ch): ch for ch, _ in stubs}.values())
        s = _Sym([{"id": ch["evidence"][0], "pts": ch["pts"], "bbox": _bbox_pts(ch["pts"]), "kind_": "poly",
                   "curved": False} for ch in own], stroke_only=True)
        made.append(s)
        gone |= {id(ch) for ch, _ in stubs}
        ch, k = rest[0]
        ch["ends"][k] = (("sym", s), ch["ends"][k][1], "pdf_path_endpoint")
        dead.add(t)
    if not dead:
        return made, chains, tees
    renum = {}
    for t in range(len(tees)):
        if t not in dead:
            renum[t] = len(renum)
    chains = [ch for ch in chains if id(ch) not in gone]
    for ch in chains:
        ch["ends"] = [((v[0], renum[v[1]]) if v[0] == "tee" else v, pt, basis) for v, pt, basis in ch["ends"]]
    return made, chains, [p for t, p in enumerate(tees) if t not in dead]


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
    """채운 사각형 점선 조각 → [(조각 목록, 끝 [(상자, 점, None)])].

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
        out.append(([filled[i] for i in g], [(filled[i]["bbox"], _center(filled[i]["bbox"]), None) for i in terms]))
    return out


def _stroke_chains(pieces, prm, boxes=()):
    """스트로크 점선 조각 → [(조각 목록, 끝 [(상자, 점, 경로 끝점 또는 None)])].

    같은 원본 경로의 연속 조각(seq가 1씩 이어짐)만 한 구간이다. 기호 안에서 흡수된 조각이 있으면 그 자리에서
    구간을 끊는다(A–B–C를 관통하는 점선이 A–C로 이어지지 않게). 서로 다른 경로는 경로 끝점끼리 정확히 두 개가
    end_tol 안에서 만날 때만 잇는다(꺾임). 한 경로의 중간에서 만나는 교차는 잇지 않는다. 기호 상자(boxes) 안의
    경로 끝점은 그 기호에 닿은 끝이지 꺾임이 아니어서 잇지 않는다. 이으면 밸브 한 변에서 따로 나가는 두 점선 배관이
    한 사슬이 되어 밸브를 건너뛴다(APR1400 008쪽 POSRV 파일럿 안전밸브와 MOV)."""
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
    tips = [e for e in ends if e[3] is not None and not any(_inside(e[3], b, prm["touch_tol"]) for b in boxes)]
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
        out.append((items, [((e[2][0], e[2][1], e[2][0], e[2][1]), e[2], e[3]) for e in free]))
    return out


def _build_dashed(syms, dashes, markers, prm):
    """점선 조각 사슬 → [{pts, ends:[(vertex, point, basis)], evidence, dashed}].

    사슬 묶기는 _filled_chains(채운 사각형 점선)·_stroke_chains(스트로크 점선)를 따른다. 사슬 끝마다 가장 가까운
    기호(dash_attach_tol 안)에 붙이고, 끝이 정확히 둘이며 서로 다른 기호에 붙을 때만 관계가 되고 아니면 미해결로 남긴다.
    """
    chains = _filled_chains([d for d in dashes if "src" not in d], prm)
    chains += _stroke_chains([d for d in dashes if "src" in d], prm, [s.bbox for s in syms])
    out = []
    for items, terms in chains:
        hits = []
        for box, point, tip in terms:
            for m in markers:  # 점선 끝 화살촉이 있으면 화살촉까지 이어 본다
                if _box_gap(m["bbox"], box) <= prm["dash_gap_max"]:
                    box = _union(box, m["bbox"])
            # 경로 끝점이 기호 상자에 닿으면 선은 그 기호에서 끝난다. 끝 조각은 점선 무늬의 빈칸만큼 끝점보다 짧아서, 조각만
            # 보면 옆에 붙은 다른 기호가 더 가까울 수 있다(APR1400 008쪽: V310 밑에서 내려오는 일점쇄선의 끝 조각이 V310보다
            # 바로 옆 계기 원 '300'에 가깝다)
            best = None
            if tip is not None:
                for s in syms:
                    gap = _pt_box_dist(tip, s.bbox)
                    if gap <= prm["touch_tol"] and (best is None or gap < best[0]):
                        best = (gap, s)
            for s in syms if best is None else ():
                gap = _box_gap(box, s.bbox)
                if gap <= prm["dash_attach_tol"] and (best is None or gap < best[0]):
                    best = (gap, s)
            hits.append((best[1] if best else None, point))
        if len(hits) == 2 and hits[0][0] is not None and hits[1][0] is not None and hits[0][0] is not hits[1][0]:
            ends = [(("sym", h[0]), h[1], "pdf_dash_chain") for h in hits]
        else:
            pts = [h[1] for h in hits] or [_center(items[0]["bbox"]), _center(items[-1]["bbox"])]
            ends = [(("free", -1), pts[0], "pdf_dash_chain"), (("free", -1), pts[-1], "pdf_dash_chain")]
        out.append({"pts": [_center(d["bbox"]) for d in items], "ends": ends, "boxes": [d["bbox"] for d in items],
                    "evidence": [d["id"] for d in items], "dashed": True,
                    "tips": [t[2] for t in terms] if len(terms) == 2 else None, "hits": [h[0] for h in hits]})
    return out


def _dashed_continuations(chains, prm):
    """점선이 실선 배관을 잇는 자리. 점선 사슬의 경로 끝점(tips)이 실선 사슬의 떠 있는 끝(기호·분기점·다른 선에 닿지
    않은 끝)에 end_tol 안으로 끝을 맞대면, 그 점선은 끊긴 배관을 이어 그린 것이다. 신호선은 계기나 구동부에서 끝나지
    배관 끝에서 끝나지 않는다(APR1400 008쪽: 파일럿 밸브 옆 출구 일점쇄선이 배출 상승관 아래 끝으로 이어진다). 맞댄
    사슬은 하나로 합쳐 continues_pipe를 단다. 합친 사슬은 점선으로 남겨 계기에 닿으면 신호선으로 둔다(_dashed_pipe).
    점선 사슬의 반대 끝은 _build_dashed가 찾은 기호(hits)에 붙인다. 반대 끝도 경로 끝점이어야 한다. 기호 상자 옆을
    스쳐 조각이 기호에 흡수되며 끊긴 토막은 그 기호를 지나가는 선일 수 있어 잇지 않는다(008쪽 303 파일럿 출구선이
    V313 밸브 상자 가장자리를 0.4pt 옆으로 지난다)."""
    cell = 4 * prm["end_tol"]
    grid = collections.defaultdict(list)
    for i, ch in enumerate(chains):
        if ch.get("dashed") or ch.get("pneumatic") or ch.get("contact"):
            continue
        for j, (v, pt, _) in enumerate(ch["ends"]):
            if v[0] == "free":
                grid[(int(pt[0] // cell), int(pt[1] // cell))].append((i, j))
    cands = []
    for i, ch in enumerate(chains):
        if not ch.get("dashed") or not ch.get("tips"):
            continue
        for k, tip in enumerate(ch["tips"]):
            if tip is None or ch["tips"][1 - k] is None:
                continue
            cx, cy = int(tip[0] // cell), int(tip[1] // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j, kj in grid.get((cx + dx, cy + dy), ()):
                        pt = chains[j]["ends"][kj][1]
                        g = math.hypot(pt[0] - tip[0], pt[1] - tip[1])
                        if g <= prm["end_tol"]:
                            cands.append((g, (i, k), (j, kj)))
    mate = {}
    for _, a, b in sorted(cands):
        if a not in mate and b not in mate:
            mate[a], mate[b] = b, a
    if not mate:
        return chains
    out = []
    for run in _end_runs(len(chains), mate):
        if len(run) == 1:
            out.append(chains[run[0][0]])
            continue
        pts, evid, boxes, ends = [], set(), [], []
        for n, (m, mk) in enumerate(run):
            ch = chains[m]
            pts += ch["pts"] if mk == 0 else ch["pts"][::-1]
            evid.update(ch["evidence"])
            boxes += ch.get("boxes", [])
            for k in ((mk,) if n == 0 else ()) + ((1 - mk,) if n == len(run) - 1 else ()):
                v, pt, basis = ch["ends"][k]
                hit = (ch.get("hits") or (None, None))[k]
                if v[0] == "free" and hit is not None:  # 한 끝만 기호에 닿아 미해결로 둔 점선 사슬의 그 끝
                    v = ("sym", hit)
                ends.append((v, pt, basis))
        out.append({"pts": pts, "ends": ends, "boxes": boxes, "evidence": sorted(evid), "dashed": True,
                    "continues_pipe": True})
    return out


def _continuation_sense(ch, ids, nodes):
    """연결 표시 화살표에 닿은 배관의 흐름: +1(ids[0] → ids[1]), -1(반대), None. 두 끝이 다르게 말하면 정하지 않는다."""
    votes = set()
    for i, ((v, pt, _), nid) in enumerate(zip(ch["ends"], ids)):
        if v[0] != "sym" or nodes[nid]["kind"] != "continuation":
            continue
        d = continuation_flow(v[1], pt)
        if d:
            votes.add(1 if (d == "into") == (i == 1) else -1)
    return votes.pop() if len(votes) == 1 else None


def _dashed_pipe(ch, nodes, ids, instrument_ids, prm):
    """점선이지만 배관인가. 점선 끝이 밸브 몸통에 그 몸통의 긴 축(흐름 방향)을 따라 들어가면 배관이다. 신호선은 밸브의
    구동부나 몸통 옆으로 닿고, 몸통을 흐름 방향으로 꿰지 않는다(APR1400 가압기 안전밸브 묶음처럼 점선으로 그린 배관).
    배관은 꺾여 지날 수 있으므로 사슬 전체가 아니라 밸브에 닿는 끝 조각의 방향을 본다(008쪽 POSRV 파일럿 일점쇄선이
    밸브에서 P 상자까지 두세 번 꺾인다). 계기에 닿은 점선은 신호·측정선으로 둔다."""
    if any(i in instrument_ids for i in ids):
        return False
    if ch.get("continues_pipe"):
        return True
    valves = 0
    for (v, pt, _), nid in zip(ch["ends"], ids):
        if v[0] != "sym" or nodes[nid]["category"] != "valve":
            continue
        b = v[1].bbox
        # 몸통의 긴 축이 없는 밸브(앵글형 안전밸브처럼 입구와 출구가 직각인 몸통)는 흐름 방향을 몸통으로 알 수 없어 뺀다
        if max(_w(b), _h(b)) < prm["dash_pipe_axis_ratio"] * min(_w(b), _h(b)):
            continue
        piece = min(ch["boxes"], key=lambda q: _pt_box_dist(pt, q))  # 밸브에 닿는 끝 조각
        if _w(piece) == _h(piece) or (_h(piece) > _w(piece)) != (_h(b) > _w(b)):
            return False
        vertical = _h(b) > _w(b)
        c = _center(b)
        if abs(pt[0] - c[0] if vertical else pt[1] - c[1]) > 0.5 * min(_w(b), _h(b)):
            return False
        valves += 1
    return valves > 0


# ---------------------------------------------------------------- 6. 종류


def _side_by_side(strokes, axis):
    """축(axis 0 = 세로 판의 x, 1 = 가로 판의 y)에 나란한 곧은 선 가운데 서로 0.5pt 넘게 떨어져 길이 방향으로 겹치는
    두 선이 있는가. 오리피스 판은 배관을 가로질러 나란히 선 두 판이다. 한 줄 위에 이어 놓인 두 조각(엇갈림 자리에서
    끊은 배관)은 판이 아니다."""
    spans = [(s["pts"][0][axis], sorted((s["pts"][0][1 - axis], s["pts"][1][1 - axis]))) for s in strokes]
    return any(abs(a[0] - b[0]) > 0.5 and min(a[1][1], b[1][1]) > max(a[1][0], b[1][0])
               for n, a in enumerate(spans) for b in spans[n + 1:])


def _apex(tri):
    """밑변이 가로·세로로 놓인 삼각형의 (꼭짓점, 밑변 가운데). 그런 밑변이 없으면 None."""
    pts = tri["pts"][:-1] if tri["pts"][0] == tri["pts"][-1] else tri["pts"]
    for i in range(3):
        a, b, c = pts[i], pts[(i + 1) % 3], pts[(i + 2) % 3]
        if (abs(a[0] - b[0]) < 0.05 or abs(a[1] - b[1]) < 0.05) and math.dist(a, b) > 0.05:
            return c, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return None


def _apexes_meet(a, b):
    """나비 몸통의 두 삼각형은 꼭짓점을 맞대고, 안전등급 경계 마름모는 밑변을 맞댄다. 위아래로 쌓은 신호 상자 끝의
    같은 쪽을 가리키는 화살촉 둘(APR1400 056쪽 'A▶ / B▶')은 꼭짓점도 밑변도 삼각형 크기만큼 떨어져 있다. 밑변이 기운
    삼각형은 예전처럼 본다."""
    ea, eb = _apex(a), _apex(b)
    if ea is None or eb is None:
        return True
    size = min(max(_w(t["bbox"]), _h(t["bbox"])) for t in (a, b))
    return math.dist(ea[0], eb[0]) <= 0.5 * size or math.dist(ea[1], eb[1]) <= 0.5 * size


SPRING_HOST_RATIO = 3.0  # 스프링 기호 긴 변 / 스프링이 붙은 곧은 몸체 긴 변 상한(APR1400 방출 밸브 약 1.5, SNP 1.7)
SPRING_LEN_RATIO = 0.3   # 스프링 사선 길이 / 그 몸체 긴 변 하한(방출 밸브 0.55~0.7, 공조기 틀의 빗금 0.07)


def _shape_features(sym, prm):
    """기호의 구조 특징(이름과 뜻은 symbols.STRUCTURE_FEATURES). 어느 특징이 어느 종류인지와 보는 순서는
    기호 사전 공통 묶음의 구조 규칙 견본이 정한다."""
    circles = [b for b in sym.bodies if _is_circle(b, prm)]
    # 검정 견본으로 올린 몸체(seed)는 그 견본이 종류와 정상 위치를 정한다. 삼각형 둘이어도 나비 규칙에 넣지 않는다
    tris = [b for b in sym.bodies if _is_triangle(b) and "seed" not in b]
    found = set()
    if getattr(sym, "panel", None):  # 공조기 판(_panels)
        found.add("%s_panel" % sym.panel)
    if _is_air_arrow(sym, prm):  # 덕트 끝 공기 흐름 화살표. '선과 표식' 체크밸브가 아니다
        found.add("flow_arrow")
    if getattr(sym, "plate_valve", None):  # 판 사이 원판·공(_plate_assemblies)
        found.add("plate_valve:%s" % sym.plate_valve)
    # 나비 몸통의 두 삼각형은 붙어 있다. 사이에 글로브·볼의 점이 끼어도 간격은 삼각형 크기보다 작다. 큰 묶음 기호 안에 멀리
    # 떨어진 삼각형이 우연히 둘 남은 것은 밸브 몸통이 아니다(APR1400 132쪽, docs/units/2026-11-11-unit-f1/README.md F1-3 검토)
    if len(tris) == 2 and _box_gap(tris[0]["bbox"], tris[1]["bbox"]) <= max(
            max(_w(t["bbox"]), _h(t["bbox"])) for t in tris) and _apexes_meet(*tris):
        found.add("bowtie")
        bow = _union(tris[0]["bbox"], tris[1]["bbox"])
        # 몸통 bbox 밖에 중심이 있는 몸체 = 구동부(안쪽 원은 글로브 표시라 구동부가 아니다)
        outside = [b for b in sym.bodies if b not in tris and not _inside(_center(b["bbox"]), bow)]
        if any(_is_circle(b, prm) for b in outside):
            found.add("outside_circle")
        if outside:
            found.add("outside_body")
    springs = [s for s in sym.strokes if len(s["pts"]) == 2 and abs(s["pts"][0][0] - s["pts"][1][0]) > 1
               and abs(s["pts"][0][1] - s["pts"][1][1]) > 1]
    # 스프링은 곧은 변 몸체(삼각형·나비 몸통) 바로 밖으로 뻗은 사선이고, 기호는 그 몸체와 스프링만 한 크기다. 몸체 안의
    # 빗금(장비 상자·공조기 칸), 둥근 몸체(번호 원·펌프 몸통)에 걸린 빗금, 곧은 몸체에서 먼 빗금(펌프 패키지 틀)은 스프링이
    # 아니고, 방출 밸브를 품은 큰 묶음(공조기 한 벌)은 안전밸브가 아니다. 143쪽에서 몸체 안 빗금까지 센 규칙이 정한 36건이
    # 모두 이런 자리였다
    side = max(_w(sym.bbox), _h(sym.bbox))
    hosts = [b for b in sym.bodies if not b.get("curved")
             and side <= SPRING_HOST_RATIO * max(_w(b["bbox"]), _h(b["bbox"]))]
    springs = [s for s in springs if all(b.get("curved") or _pt_ring_dist(_center(s["bbox"]), b["pts"]) > 0
                                         for b in sym.bodies)
               and any(_pt_box_dist(_center(s["bbox"]), b["bbox"]) <= max(_w(b["bbox"]), _h(b["bbox"]))
                       and math.dist(*s["pts"][:2]) >= SPRING_LEN_RATIO * max(_w(b["bbox"]), _h(b["bbox"])) for b in hosts)]
    if len(springs) >= 2 and len({(round(s["pts"][0][1] - s["pts"][1][1], 1),
                                                    round(s["pts"][0][0] - s["pts"][1][0], 1)) for s in springs}) == 1:
        found.add("body_with_springs")
    if sym.stroke_only:
        found.add("stroke_only")
    if sym.markers:
        found.add("markers")
    straight = [s for s in sym.strokes if len(s["pts"]) == 2 and not s.get("curved")]
    if sym.stroke_only and straight and len(straight) == len(sym.strokes) and not getattr(sym, "pocket", False) \
            and not getattr(sym, "between_plates", False):
        vertical = [s for s in straight if abs(s["pts"][0][0] - s["pts"][1][0]) < 0.5]
        horizontal = [s for s in straight if abs(s["pts"][0][1] - s["pts"][1][1]) < 0.5]
        if _side_by_side(vertical, 0) or _side_by_side(horizontal, 1):
            found.add("parallel_plates")
    if len(sym.bodies) == 1 and len(circles) == 1 and not tris:
        found.add("single_circle")
    if len(sym.bodies) == 1 and _is_tombstone(sym.bodies[0]):
        found.add("single_tombstone")
    if sym.bodies and all(_is_chevron(b) for b in sym.bodies):
        found.add("chevrons")
    if sym.bodies and all(b.get("wave") for b in sym.bodies):
        found.add("wave")
    return found


def _shape_rule(sym, prm):
    """형상만으로 정하는 종류와 근거. 없으면 (None, None). 계기 모양은 종류 자리에 'instrument'를 돌려준다(종류는 ISA 글자로)."""
    entry, basis = symbol_library().shape_rule(_shape_features(sym, prm))
    if entry is None:
        return None, None
    return ("instrument" if entry.kind_from == "isa_letters" else entry.kind), basis


NAME_NOTE_RE = re.compile(r"\([^)]*\)")
NAME_DESTINATION_RE = re.compile(r"(?<=[A-Z])\s+TO\s.*", re.S)  # 낱말 뒤 'TO …'부터 끝까지(맨 앞 'TO …'는 행선지 표시라 남긴다)
PACKAGE_TEXT_RE = re.compile(r"\bSKID\b")
SIGNAL_TEXT_RE = re.compile(r"\b(?:LOW\s*/\s*HIGH|HIGH\s*/\s*LOW|START\s*/\s*STOP|STOP\s*/\s*START|OPEN\s*/\s*CLOSE)\b")


def _kind_from_text(text):
    up = text.upper()
    if CONTINUATION_RE.match(up.strip()):
        return "continuation", "text_to_from"
    if SIGNAL_TEXT_RE.search(up):
        return None, None  # 'DAY TANK LEVEL LOW/HIGH'·'PUMP START/STOP'은 경보·명령 상자의 글자다. 설비 이름이 아니다
    if PACKAGE_TEXT_RE.search(up):
        return None, None  # 'AIR COMPRESSOR SKID'(099쪽)는 여러 기기를 얹은 묶음의 경계 상자다. 안의 설비 하나가 아니다
    up = NAME_NOTE_RE.sub(" ", up)  # 괄호 안 주석('(NOTE 1)', '(7EA)')은 이름이 아니다
    up = NAME_DESTINATION_RE.sub(" ", up)  # 'VENT TO ATMOSPHERE'의 'TO …'는 행선지다. 이름은 그 앞에서 끝난다
    entry, words = symbol_library().word_rule(re.findall(r"[A-Z]+", up), up)
    if entry is None:
        return None, None
    return entry.kind, "text_word:%s" % "+".join(words)


def _instrument_kind(text, min_side=None):
    """ISA 5.1 식 계기 표기(기능 문자 + 번호)를 나눠 읽는다: 'PT\n101'·'PT\n101\nA1'·'PT-101'·'PT 101'·'PT'.
    글자가 여러 줄이면 첫 두 줄(기능 문자·번호)로, 맞지 않으면 첫 줄로 판정한다."""
    lines = [" ".join(l.upper().split()) for l in text.split("\n") if l.strip()]
    m = None
    for flat in ([" ".join(lines[:2])] if len(lines) >= 2 else []) + lines[:1]:
        m = re.fullmatch(r"([A-Z]{1,4})(?:[ \-]*\d+[A-Z]?)?", flat)
        if m:
            break
    if not m:
        return _isa_bubble_kind(lines, min_side)
    letters = m.group(1)
    if letters in LEGEND_FAIL_POSITIONS and m.group(0) == letters:
        return None, None  # 번호 없는 FC·FO·FL은 밸브 고장 위치 표기다(054쪽 빈 번호 원 옆 FC). 유량 조절계가 아니다
    if len(letters) >= 2 and letters[-1] == "E" and letters[0] == "T":
        return "temperature_element", "isa_letters:%s" % letters
    if letters.startswith("TEW"):
        # 보호관 온도 측정점(범례 1.7-1 TEW THERMOWELL, 뒤에 경보·지시 글자가 붙기도 함: TEWIS). 레지스트리에 보호관 종류가 없어
        # 온도 측정점을 뜻하는 temperature_element로 본다(R3 개선 4, 2026-11-13. 3e에서는 종류를 비웠다)
        return "temperature_element", "isa_letters:%s" % letters
    if len(letters) >= 2 and letters[-1] in INSTRUMENT_FUNCTION:
        return INSTRUMENT_FUNCTION[letters[-1]], "isa_letters:%s" % letters
    # 마지막 글자 규칙 뒤에 본다: ZAC는 AC(ALARM CLOSED)로도, C(CONTROLLER)로도 읽혀 앞 규칙의 판정을 바꾸지 않는다
    legend = _legend_code_kind(letters, numbered=m.group(0) != letters, min_side=min_side)
    if legend is not None:
        return legend, "isa_legend_code:%s" % letters
    return _isa_bubble_kind(lines, min_side)


# ISA 5.1 뒤 글자(기능)에서 kind를 고르는 순서. 위 규칙(마지막 글자)이 못 정한 계기 원에만 쓴다(기존 판정은 그대로).
# G(유리·게이지)·L(표시등)은 지시 기능이라 indicator로 본다. E(검출부)는 정하지 않는다: 원 안 FE를 배관 부품
# flow_element로 두면 검토구간 나누기에서 배관 핵심 조각이 되어 계기 원마다 따로 검토구간이 생긴다(3e 검토).
ISA_FUNCTION_ORDER = (("T", "transmitter"), ("C", "controller"), ("S", "switch"), ("R", "recorder"),
                      ("I", "indicator"), ("G", "indicator"), ("L", "indicator"))  # 출력(T·C·S) > 판독(R·I·G·L)
ISA_LAST_FUNCTIONS = frozenset("TCSRIGLAK")  # 계기 표기의 마지막 기능 문자로 볼 수 있는 글자(A 경보, K 조작반 포함)
ISA_BUBBLE_MIN = 8.0  # 계기 원 짧은 변 하한(pt)

# APR1400 범례가 이름을 준 계기 표기. 범례 1.7-1(3/4) INSTRUMENT TYPE CODES의 뒤 글자(기능): A·AC·AH·AHH·AHL·AL·ALL·AO는
# 경보, L은 LIGHT (PILOT). 앞 글자까지 정해야 뜻이 서는 표기는 범례 기호로 정한다: AX는 1.7-1(2/4) SAMPLE PROBE의 원,
# FG는 1.7-9 FLOW SIGHT GLASS의 원, LE는 3/4의 L(LEVEL) + E(PRIMARY ELEMENT). FE는 정하지 않는다(ISA_FUNCTION_ORDER 위 설명).
# TW는 3/4 TW THERMOWELL FOR TEST로, 같은 표의 TEW THERMOWELL처럼 온도 측정점 temperature_element로 본다
LEGEND_ALARM_FUNCTIONS = frozenset({"A", "AC", "AH", "AHH", "AHL", "AL", "ALL", "AO"})
# Y는 3/4 INSTRUMENT TYPE CODES의 RELAY, CONVERTER, COMPUTING(SY·PY·TY 등, 레지스트리 0.11.0 relay_converter)
# G는 유리·게이지(LG 수위계 등)로 지시 기능이다(ISA_FUNCTION_ORDER와 같음)
LEGEND_FUNCTION_KIND = {"L": "pilot_light", "Y": "relay_converter", "G": "indicator"}
LEGEND_CODE_MIN = 5.0  # LEGEND_CODE_KIND 표기 원의 짧은 변 하한(pt)
LEGEND_FAIL_POSITIONS = frozenset({"FC", "FO", "FL"})  # 범례 1.7-1(2/4) FAIL CLOSED·OPEN·LOCKED
LEGEND_CODE_KIND = {"AX": "sample_probe", "FG": "sight_glass", "LE": "level_element", "TW": "temperature_element"}
# 범례 1.7-1(3/4) CLARIFYING SYMBOL LIST의 글자. 번호 없이 원 안에 홀로 적히면 계기 표기가 아니라 한계·고장 위치 같은
# 덧붙임 표기다(LL LOW LIMIT, FL FAIL LOCK 등)
LEGEND_CLARIFYING = frozenset({"A", "ADD", "AVG", "BI", "C", "CC", "D", "DIFF", "DIR", "FC", "FI", "FL", "FO", "HE", "HHL",
                               "HL", "HP", "INT", "ISO", "LL", "LLL", "LP", "M", "MAX", "MIN", "NA", "NAK", "RES", "REN",
                               "SC", "SI", "SM", "SQRT", "TURB", "VOL", "X", "REF", "DC", "IPS"})


def _legend_code_kind(letters, numbered, min_side):
    """범례가 정한 계기 표기(LEGEND_*)의 kind. 계기 원 크기(ISA_BUBBLE_MIN)가 아니거나, 번호 없는 글자가 범례 덧붙임
    글자(LEGEND_CLARIFYING)이면 정하지 않는다. → kind 또는 None"""
    if min_side is None or len(letters) < 2:
        return None
    if not numbered and letters in LEGEND_CLARIFYING:
        return None
    if letters in LEGEND_CODE_KIND:
        # 글자 둘이 기호 하나를 가리키는 범례 표기는 원이 작아도 그 기호다(FG 투시창 원은 도면에서 6~7pt, 범례 8.6pt)
        return LEGEND_CODE_KIND[letters] if min_side >= LEGEND_CODE_MIN else None
    if min_side < ISA_BUBBLE_MIN:
        return None
    funcs = letters[1:]
    if funcs[:1] in VARIABLE_MODIFIERS_ISA and len(funcs) > 1:
        funcs = funcs[1:]  # 변수 수식 문자(PDAH의 D 차압)
    if funcs in LEGEND_ALARM_FUNCTIONS:
        return "alarm"
    return LEGEND_FUNCTION_KIND.get(funcs)


def _isa_bubble_kind(lines, min_side=None):
    """계기 원 글자가 '기능 문자 2~6자 + 루프 번호' 꼴일 때만(예: 'TEW 4', 'FICKS 101', 'ZL 202C', 줄바꿈으로 나뉨)
    ISA 뒤 글자로 kind를 정한다. 번호 없는 글자('LL', 'HHL', 'NO' 같은 경보·위치 표기)는 보지 않는다. → (kind, basis) 또는 (None, None)."""
    if min_side is None or min_side < ISA_BUBBLE_MIN:
        return None, None  # 작은 원(밸브 힌지 점 등)은 계기 원이 아니다(_bubble_like와 같은 8pt 기준)
    flat = " ".join(lines[:2])
    m = re.fullmatch(r"([A-Z]{2,6})[ \-]*\d+[A-Z]?\d?", flat)
    if not m:
        return None, None
    letters = m.group(1)
    if letters.startswith("TEW"):
        return "temperature_element", "isa_function:%s" % letters  # 보호관 온도 측정점(TEWIS 등, _instrument_kind와 같음)
    if "W" in letters or "V" in letters:
        return None, None  # V 밸브(PSV·PCV)와 W가 든 다른 글자: 계기 kind가 아니다(TEW는 위 _instrument_kind에서 정함)
    rest = letters[1:]
    if rest[:1] in VARIABLE_MODIFIERS_ISA and len(rest) > 1:
        rest = rest[1:]  # 변수 수식 문자(D 차압 등)
    funcs = rest.rstrip("HLM") or rest  # 끝의 H·L·M은 높음·낮음·중간 수식 문자(PSAL → SA)
    if funcs[-1:] not in ISA_LAST_FUNCTIONS:
        return None, None  # 마지막 글자가 기능 문자가 아니면(RCP 1A 같은 설비 번호, PSE 파열판) 계기 표기로 보지 않는다
    for letter, kind in ISA_FUNCTION_ORDER:
        if letter in funcs:
            return kind, "isa_function:%s" % letters
    return None, None


_symbol_library = None
PIPE_CAP_BASIS = "small_closed_body_single_connection"
SPRING_BASIS = "body+spring"  # 사전 공통 묶음 common.psv_body의 근거 글자
# 범례 1.7-1 1/4 QUALITY GROUP/SAFETY CLASS/SEISMIC CATEGORY 경계: 마름모를 세로선으로 가르고 양쪽에 등급('CI|DII')을 적는다.
# 나비 규칙에 밸브로 걸리지만 공정 기호가 아니라 경계 표시다
SAFETY_CLASS_BASIS = "safety_class_boundary"
SAFETY_CLASS_RE = re.compile(r"(?:[A-G](?:I{1,3}|Ⅰ|Ⅱ|Ⅲ)){2}")
# 검은 채움을 기호 몸체로 올릴 때의 견본 거리 상한(칸). 견본의 max_distance보다 좁게 본다. 잘못 올리면 화살촉이 밸브가 되어
# 열린 배관이 닫힌 밸브로 읽힌다. APR1400 143쪽에서 게이트·글로브 묶음은 견본에서 0.06칸 안, 밸브가 아닌 검은 채움(반만 칠한
# 밸브, 건물 경계 표시, 화살촉 등)은 0.24칸 이상 떨어져 있었다(docs/units/2026-11-11-unit-f1/README.md F1-3)
SPRING_KINDS = frozenset({"psv"})  # 사전 격자 견본만으로 정하지 않고 스프링선(_has_spring)을 함께 보는 종류
BLACK_SEED_DISTANCE = 0.1
ACTUATOR_REACH_RATIO = 2.0  # 밸브 몸통 긴 변 × 비율 안에 구동부 기호가 있으면 구동 밸브로 본다(APR1400 축 길이 기준)


def _on_stem_line(actuator, valve, prm):
    """구동부 가운데가 밸브 축 자리에 있는가. 축은 몸통 가운데에서 배관과 수직으로 나가므로, 흐름 축 방향으로 본 구동부
    가운데가 몸통 폭 안에 들어야 한다. 흐름 축을 모르는 몸통은 축 자리에 있다고 본다(판정을 바꾸지 않는다)."""
    ax = _flow_axis(valve, prm)
    if ax is None:
        return True
    mid = _center(actuator.bbox)[ax]
    return valve.core[ax] <= mid <= valve.core[ax + 2]


HAND_BAR_LEN = (0.15, 1.0)  # 손잡이 가로대 길이 / 몸통 길이(APR1400 016쪽 0.24 ~ 063쪽 0.63)
HAND_BAR_REACH = 2.0  # 몸통 가운데에서 가로대까지 / 몸통 길이 상한(APR1400 0.5 ~ 1.27)
HAND_LINE_TOL = 0.25  # 가로대·축이 곧은지, 축이 몸통 가운데 줄에 있는지 보는 허용(pt)


def _valve_body_part(sym, cls):
    """기호에서 밸브 몸통만 뗀 기호와 그 사전 항목. 검정 견본으로 올린 몸통은 그 견본 항목이고, 아니면 곧은 닫힌 몸통 중 가장
    큰 것과 그 안의 표식(글로브 가운데 점)만으로 사전에 대 본다. 몸통 옆에 붙어 함께 묶인 글자 원(063쪽 'N')·축·화살표·
    벨로스 선은 뺀다. 수동 밸브 항목이 아니면 None."""
    if sym.seed is not None:
        entry = cls["seeds"][sym.seed].entry
        part = _Sym(list(sym.bodies))
        part.markers = [m for m in sym.markers if _inside(_center(m["bbox"]), part.core)]
    else:
        straight = [b for b in sym.bodies if not b.get("curved")]
        if not straight:
            return None
        part = _Sym([max(straight, key=lambda b: _w(b["bbox"]) * _h(b["bbox"]))])
        part.markers = [m for m in sym.markers if _inside(_center(m["bbox"]), part.core)]
        part._recalc()
        hit = symbol_library().match(symbols.sym_signature(part), [])
        if hit.outcome != "matched" or hit.entry.role != "symbol":
            return None
        entry = hit.entry
    return (part, entry) if entry.kind == "manual_valve" else None


def _hand_wheel(part, cls, blocks, prm):
    """몸통 가운데에서 배관과 수직으로 나간 축 끝에 가로대가 있는가(범례 1.7-1 1/4 HAND ACTUATOR 'T'). 몸통과 가로대 사이
    축 자리에는 벨로스 같은 열린 선과 화살표만 있어야 한다. 닫힌 도형(구동부 머리·원·상자)이나 글자(M·S)가 있으면 구동부가
    끼어 있을 수 있어 손잡이로 보지 않는다."""
    ax = _flow_axis(part, prm)
    if ax is None:
        w, h = _w(part.core), _h(part.core)
        ax = 0 if w >= 1.5 * h else 1 if h >= 1.5 * w else None
    if ax is None:
        return False
    st, tol = 1 - ax, HAND_LINE_TOL
    c = _center(part.core)
    length, half = part.core[ax + 2] - part.core[ax], (part.core[st + 2] - part.core[st]) / 2
    lines = [p["pts"] for p in cls["polys"] if len(p["pts"]) == 2]
    own = {b["id"] for b in part.bodies} | {m["id"] for m in part.markers}
    for a, b in lines:
        bar = a[st]
        if abs(a[st] - b[st]) > tol or abs((a[ax] + b[ax]) / 2 - c[ax]) > 0.1 * length:
            continue
        if not HAND_BAR_LEN[0] * length <= abs(a[ax] - b[ax]) <= HAND_BAR_LEN[1] * length:
            continue
        if not half < abs(bar - c[st]) <= HAND_BAR_REACH * length:
            continue
        sign = 1 if bar > c[st] else -1
        stem = any(abs(p[ax] - c[ax]) <= tol and abs(q[ax] - c[ax]) <= tol and abs(p[st] - bar) <= tol
                   and 0 < sign * (bar - q[st]) for p, q in lines + [(y, x) for x, y in lines])
        if not stem:
            continue
        lo, hi = sorted((bar, c[st] + sign * half))
        col = [0.0] * 4
        col[ax], col[ax + 2], col[st], col[st + 2] = part.core[ax], part.core[ax + 2], lo, hi
        if any(_inside(_center(m["bbox"]), col) for m in cls["bodies"] + cls["markers"]
               if m["id"] not in own and not _is_triangle(m)):
            continue
        if any(_inside(_center(bk["bbox"]), col) for bk in blocks):
            continue
        return True
    return False


def symbol_library():
    """기호 사전(resources/library/symbols). 프로세스마다 한 번 읽는다. 없거나 깨졌으면 SymbolLibraryError로 멈춘다."""
    global _symbol_library
    with _cache_lock:
        if _symbol_library is None:
            lib = symbols.Library.load()
            _check_has_rules(lib)
            _check_against_registry(lib)
            _symbol_library = lib
        return _symbol_library


def _check_has_rules(lib):
    """형상 규칙과 장비 이름 낱말은 사전에만 있다(S7). 그 견본이 없는 사전은 코드보다 옛 판이고, 그대로 쓰면
    밸브·계기·설비가 오류 없이 미분류로 나온다. SymbolLibraryError로 멈춘다."""
    missing = lib.missing_rule_shapes()
    if missing:
        raise symbols.SymbolLibraryError(
            "기호 사전에 %s 견본이 하나도 없음: %s. 코드보다 옛 판 사전이다(형상 규칙과 장비 이름 낱말을 사전으로 "
            "옮기기 전). 이 코드와 함께 배포된 사전으로 바꿔야 한다" % ("·".join(missing), lib.root))


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


def _black_fills(cls):
    """검은 채움 도형 전부: 표식(작은 것), 검은 몸체(큰 것), 점선 조각으로 분류된 둥근 점. 글로브 밸브 가운데 점은
    1.5pt보다 작으면 점선 조각이 된다."""
    return [m for m in cls["markers"] if not m.get("thin_tip")] + [b for b in cls["bodies"] if b.get("solid")] + \
        [d for d in cls["dashes"] if d["curved"]]


def _mark_actuator_bodies(cls, prm):
    """작은 곡선 몸체 하나가 혼자서 사전 구동부 견본(다이어프램·전동기 등)에 맞으면 actuator로 표시한다. 기호를 묶을 때
    맞닿은 다른 몸체와 묶지 않고(_cluster_bodies), 구동부로 따로 사전에 대어 축으로 이어진 밸브에 합친다(_apply_merges)."""
    lib = symbol_library()
    for b in cls["bodies"]:
        if not b.get("curved") or b.get("traced") or b.get("seed") is not None or \
                max(_w(b["bbox"]), _h(b["bbox"])) > prm["actuator_body_max"]:
            continue
        hit = lib.match(symbols.signature([b], [], [], [], b["bbox"]))
        if hit.outcome == "matched" and hit.entry.role == "actuator":
            b["actuator"] = True


def _promote_black_symbols(cls, prm):
    """검은 채움 묶음이 사전의 검정 견본에 맞으면 그 몸통을 한 기호의 몸체로 표시한다(seed). 표식이던 것은 몸체로 올린다
    (기획서 §4.2 1번). 표식으로 두면 닫힌 밸브 자리에 밸브 노드 없이 양쪽 배관이 이어진다(_build_solid의 same_marker).
    가운데 둥근 점은 표식으로 두어, 기호를 묶을 때 같은 seed의 기호에 들어가게 한다. 묶음과 같은 자리에 따로 그린 외곽선은
    채움과 같은 도형이라 뺀다(_classify_primitives의 twin과 같은 규칙). 견본에 맞지 않거나 애매한 묶음은 그대로 둔다.
    맞은 결과는 cls["seeds"]({seed 번호: symbols.Match})에 남긴다."""
    cls["seeds"] = {}
    groups = [g for g in _black_fill_groups(_black_fills(cls), prm) if g["straight"]]
    if not groups:
        return
    lib = symbol_library()
    seed, boxes = {}, []
    for k, g in enumerate(groups):
        hit = lib.match(_black_fill_signature(g))
        if hit.outcome == "matched" and hit.entry.role == "symbol" and hit.distance <= BLACK_SEED_DISTANCE:
            seed.update((id(m), k) for m in g["straight"] + g["round"])
            boxes.append(g["bbox"])
            cls["seeds"][k] = hit
    if not seed:
        return

    def outline_of_seed(b):
        return not b.get("solid") and any(max(abs(b["bbox"][j] - box[j]) for j in range(4)) <= prm["twin_tol"]
                                          for box in boxes)

    def body(m):
        return id(m) in seed and not m["curved"]

    def tagged(items):
        return [dict(m, seed=seed[id(m)]) if id(m) in seed else m for m in items]
    cls["bodies"] = [dict(b, seed=seed[id(b)]) if body(b) else b for b in cls["bodies"] if not outline_of_seed(b)] +         [dict(m, solid=True, closed=True, seed=seed[id(m)]) for m in cls["markers"] if body(m)]
    cls["markers"] = tagged(m for m in cls["markers"] if not body(m)) + tagged(d for d in cls["dashes"] if id(d) in seed)
    cls["dashes"] = [d for d in cls["dashes"] if id(d) not in seed]
    # 기호를 묶기 전에 나눈다. 뒤에 나누면 큰 기호 상자 안을 지나는 선이 그 기호의 내부선으로 먼저 흡수된다
    cls["polys"] = _cut_at_boxes(cls["polys"], boxes)


def _class_mark_text(text):
    """글자 문단의 첫 줄을 빈칸 없이 이은 것(밸브 몸통 안 표기와 같은 꼴, build_extraction의 mark_lines)."""
    return "".join(text.partition("\n")[0].split())


def _mark_class_boundaries(cls, blocks, prm):
    """안전등급 경계 마름모(범례 1.7-1 1/4 QUALITY GROUP/SAFETY CLASS/SEISMIC CATEGORY)의 두 삼각형에 같은
    class_mark 번호를 단다. 마름모는 맞닿은 삼각형 둘이고, 그 안에 등급 글자('BI|DII')가 있다. 경계 표시는 공정 기호의
    일부가 아니므로 _cluster_bodies가 이 두 삼각형을 다른 몸체와 묶지 않는다. 상자 거리로 묶으면 바로 옆 밸브 번호 원의
    상자 귀퉁이가 마름모 상자에 겹쳐 한 기호가 되고, 그 큰 상자 한가운데 놓인 배관 끝이 몸체 깊숙이 든 선(_group_symbols
    B)으로 읽혀 아래 안전밸브까지 끌어들인다(APR1400 105쪽 주증기 안전밸브)."""
    tris = [i for i, b in enumerate(cls["bodies"]) if _is_triangle(b) and "seed" not in b and not b.get("solid")]
    marks = [b for b in blocks if SAFETY_CLASS_RE.fullmatch(_class_mark_text(b["text"]))]
    if not marks:
        return
    n = 0
    for k, i in enumerate(tris):
        for j in tris[k + 1:]:
            a, b = cls["bodies"][i], cls["bodies"][j]
            if "class_mark" in a or "class_mark" in b or _box_gap(a["bbox"], b["bbox"]) > prm["touch_tol"]:
                continue
            box = _union(a["bbox"], b["bbox"])
            if any(_inside(_center(m["bbox"]), box) for m in marks):
                n += 1
                cls["bodies"][i] = dict(a, class_mark=n)
                cls["bodies"][j] = dict(b, class_mark=n)


CLASS_THROUGH_COS = -0.7  # 마름모를 꿰는 배관: 마름모 가운데에서 본 두 선 끝 방향의 cos 상한(맞은편)
CLASS_BODY_TOL = 1.0      # 지시선 끝이 마름모 몸통(삼각형 둘) 상자에 닿았다고 보는 여유(pt)
CLASS_REATTACH = 4.0      # 마름모 칸막이선에서 떼어 낸 배관 끝을 옆 기호에 다시 잇는 거리 상한(pt, 플랜지 틈)


def _class_mark_lines(chains, class_marks, dropped, others=()):
    """안전등급 경계 마름모(class_marks: {id(기호): 등급 글자})에 닿은 선을 정리한다. 마름모를 맞은편으로 꿰는 실선 둘은
    한 배관으로 잇고, 그 밖의 선(마름모에서 배관·밸브로 긋는 지시선, 신호선)은 관계로 두지 않는다. 지시선을 배관으로
    두면 배관에 가짜 분기와 가짜 연결이 생긴다(APR1400 134쪽 DII|DIII). → (새 사슬 목록, [(지시선 반대 끝, 등급 글자)])."""
    if not class_marks:
        return chains, []
    at = {}
    for ch in chains:
        for k, (v, _, _) in enumerate(ch["ends"]):
            if v[0] == "sym" and id(v[1]) in class_marks:
                at.setdefault(id(v[1]), []).append((ch, k))
    gone, joined, marked = set(), [], []
    for key, hits in at.items():
        solid = [(ch, k) for ch, k in hits if not ch.get("dashed")]
        sym = hits[0][0]["ends"][hits[0][1]][0][1]
        c = _center(sym.bbox)
        body = _expand(_union(*[b["bbox"] for b in sym.bodies]), CLASS_BODY_TOL) if sym.bodies else sym.bbox
        if len(hits) == 2 and len(solid) == 2 and all(id(ch) not in gone and _inside(ch["ends"][k][1], body)
                                                      for ch, k in solid):
            (a, ka), (b, kb) = solid
            pa, pb = a["ends"][ka][1], b["ends"][kb][1]
            u = (pa[0] - c[0], pa[1] - c[1])
            w = (pb[0] - c[0], pb[1] - c[1])
            la, lb = math.hypot(*u), math.hypot(*w)
            if a is not b and la > 0 and lb > 0 and (u[0] * w[0] + u[1] * w[1]) / (la * lb) <= CLASS_THROUGH_COS:
                pts_a = a["pts"] if ka == 1 else a["pts"][::-1]  # 마름모 쪽 끝이 마지막
                pts_b = b["pts"] if kb == 0 else b["pts"][::-1]  # 마름모 쪽 끝이 처음
                fa = a.get("flow") if ka == 1 else (-a["flow"] if a.get("flow") else None)
                fb = b.get("flow") if kb == 0 else (-b["flow"] if b.get("flow") else None)
                joined.append(dict(a, pts=list(pts_a) + list(pts_b), evidence=list(a["evidence"]) + list(b["evidence"]),
                                   ends=[a["ends"][1 - ka], b["ends"][1 - kb]],
                                   flow=fa if fa == fb or fb is None else fb if fa is None else None))
                gone.update((id(a), id(b)))
                continue
        for ch, k in hits:
            if id(ch) in gone:
                continue
            gone.add(id(ch))
            if not _inside(ch["ends"][k][1], body):
                # 마름모 몸통 밖(칸막이선 끝)에 닿은 선은 지시선이 아니라 그 끝을 지나던 배관이다(141쪽 RD01 뒤 2"). 배관은
                # 남기고 그 끝은 바로 옆(CLASS_REATTACH 안) 다른 기호에 잇는다. 없으면 닿지 않은 끝으로 둔다(분석 결과는
                # 함께 쓰므로 사슬을 고치지 않고 새로 만든다)
                ends = list(ch["ends"])
                pt = ends[k][1]
                near = min(((_pt_box_dist(pt, o.bbox), i) for i, o in enumerate(others) if o is not sym), default=None)
                v = ("sym", others[near[1]]) if near and near[0] <= CLASS_REATTACH else ("free", None)
                ends[k] = (v, pt, ends[k][2])
                joined.append(dict(ch, ends=ends))
                continue
            other = ch["ends"][1 - k][0]
            if not ch.get("dashed") and other[0] in ("sym", "tee"):
                marked.append((other, class_marks[key]))
            dropped.append({"source_object_id": ch["evidence"][0] if ch["evidence"] else "",
                            "label_text": class_marks[key], "bbox": _box_out(_bbox_pts(ch["pts"])),
                            "reason": "safety_class_leader"})
    return [ch for ch in chains if id(ch) not in gone] + joined, marked


BOUNDARY_TIP_TOL = 0.1      # 두 화살촉 꼭짓점이 한 점에서 만난다고 보는 거리(pt)
BOUNDARY_ELONGATION = 1.5   # 경계 표시 화살촉: 축 방향 길이 ≥ 폭 × 이 값(검게 칠한 나비 밸브 삼각형은 축 방향이 더 짧다)
BOUNDARY_PARALLEL = 0.05    # 선 방향과 화살촉 축이 나란하다고 보는 사인 값 상한


def _boundary_marks(cls, prm):
    """건물·구역 경계 표시(▶◀)를 공정 기호 재료에서 뺀다. 경계 표시는 가는 선 하나 위에 얇은 화살촉 둘을 꼭짓점끼리
    마주 대어 그리고, 양옆에 구역 이름(YARD|UCT, INDOORS|OUTDOORS, DE|WM)을 쓴다(APR1400 025·046·062·097·105쪽).
    표시선은 배관이 아닌데도 남겨 두면 장식선이나 선 기호가 되어 옆 배관 끝을 붙잡고(046쪽 CB SUPPLY 분기),
    가로선 둘과 세로 눈금은 오리피스 판으로 읽힌다(046쪽 TGB|UCT|AB). 화살촉을 맞댄 축과 나란히 두 화살촉을 다
    지나는 선이 있어야 경계 표시로 본다. 그 선, 그 선에 끝을 이어 그린 토막과 두 화살촉을 뺀다. 꼭짓점을 가로지르는
    눈금은 남긴다. 눈금은 배관 위에 그리기도 하고(105쪽 MSVH 경계), 지역 경계선과 이어지기도 해서 빼면 남은 선 토막이
    옆 글자의 설비 낱말로 종류를 얻는다(025쪽 CCW HX BLDG.).
    → 뺀 요소 목록(cls["boundary_marks"])."""
    tips = [m for m in cls["markers"] if m.get("thin_tip") and len(m["pts"]) >= 3]
    gone, used, taken = [], set(), set()

    def corners(m):
        pts = [tuple(p) for p in m["pts"]]
        return pts[:-1] if len(pts) > 3 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= BOUNDARY_TIP_TOL \
            else pts
    for i, a in enumerate(tips):
        for b in tips[i + 1:]:
            if id(a) in used or id(b) in used or _box_gap(a["bbox"], b["bbox"]) > BOUNDARY_TIP_TOL:
                continue
            meet = [(p, q) for p in corners(a) for q in corners(b) if math.hypot(p[0] - q[0], p[1] - q[1]) <= BOUNDARY_TIP_TOL]
            if len(meet) != 1:
                continue  # 꼭짓점 하나에서만 만나야 마주 본 화살촉이다(밑변을 맞대면 두 점이 겹친다)
            apex = meet[0][0]
            ca, cb = _center(a["bbox"]), _center(b["bbox"])
            L = math.hypot(cb[0] - ca[0], cb[1] - ca[1])
            if L == 0:
                continue
            u = ((cb[0] - ca[0]) / L, (cb[1] - ca[1]) / L)

            def along(m):
                xs = [(p[0] - apex[0]) * u[0] + (p[1] - apex[1]) * u[1] for p in corners(m)]
                ys = [-(p[0] - apex[0]) * u[1] + (p[1] - apex[1]) * u[0] for p in corners(m)]
                return max(xs) - min(xs), max(ys) - min(ys), min(xs), max(xs)
            la, wa, lo, _ = along(a)
            lb, wb, _, hi = along(b)
            if la < BOUNDARY_ELONGATION * wa or lb < BOUNDARY_ELONGATION * wb:
                continue
            straight = [p for p in cls["polys"] if len(p["pts"]) == 2 and
                        math.hypot(p["pts"][1][0] - p["pts"][0][0], p["pts"][1][1] - p["pts"][0][1]) > 0]

            def on_axis(p):
                (x0, y0), (x1, y1) = p["pts"]
                return abs(((x1 - x0) * u[1] - (y1 - y0) * u[0]) / math.hypot(x1 - x0, y1 - y0)) <= BOUNDARY_PARALLEL
            lines = []
            for p in straight:
                if on_axis(p) and _seg_dist(apex, *p["pts"])[0] <= prm["touch_tol"]:
                    s = sorted((x - apex[0]) * u[0] + (y - apex[1]) * u[1] for x, y in p["pts"])
                    if s[0] <= lo + BOUNDARY_TIP_TOL and s[1] >= hi - BOUNDARY_TIP_TOL:
                        lines.append(p)
            if not lines:
                continue
            # 표시선을 끝끼리 이어 그린 토막도 표시선이다(025쪽 CCW HX BLDG.|YARD 선은 세 토막). 표시선보다 긴 선은 넣지 않는다
            reach = max(_poly_length(p) for p in lines)
            grown = True
            while grown:
                grown = False
                for p in straight:
                    if any(p is q for q in lines) or _poly_length(p) > reach or not on_axis(p):
                        continue
                    if any(min(_seg_dist(e, *q["pts"])[0] for e in p["pts"]) <= prm["touch_tol"] and
                           min(_seg_dist(e, *p["pts"])[0] for e in q["pts"]) <= prm["touch_tol"] for q in lines):
                        lines.append(p)
                        grown = True
            used.update((id(a), id(b)))
            gone += [a, b] + [p for p in lines if id(p) not in taken]
            taken.update(id(p) for p in lines)
    gone += _arrow_brackets(cls, prm, used)
    ids = {id(m) for m in gone}
    cls["markers"] = [m for m in cls["markers"] if id(m) not in ids]
    cls["polys"] = [p for p in cls["polys"] if id(p) not in ids]
    cls["boundary_marks"] = gone


BRACKET_MAX = 12.0     # 화살 괄호 표시의 긴 변 상한(pt). 091쪽 지하 배관 구간 표시는 약 5×5
BRACKET_SAME_COS = 0.9  # 두 화살촉이 같은 쪽을 가리킨다고 보는 cos 하한


def _arrow_brackets(cls, prm, used):
    """선 하나(원시 경로 하나)의 두 끝이 모두 바깥을 가리키는 화살촉 안에 있고, 두 화살촉이 같은 쪽을 가리키는 작은
    괄호(ㄇ 모양)는 배관이 아니라 표시다. 배관이 괄호 가운데를 지나며 구간이 바뀌는 곳을 가리킨다(APR1400 091쪽 지하
    배관 시작). 남겨 두면 괄호 두 다리가 배관 분기와 대기 방출 끝으로 읽혀 흐름이 거꾸로 퍼진다. → 뺄 선·화살촉 목록."""
    tips = [m for m in cls["markers"] if id(m) not in used]
    out = []
    for p in cls["polys"]:
        pts = p["pts"]
        if len(pts) < 3 or p.get("closed") or max(p["bbox"][2] - p["bbox"][0], p["bbox"][3] - p["bbox"][1]) > BRACKET_MAX:
            continue
        hits = [end_arrow(pts, k, tips, prm) for k in (0, 1)]
        if None in hits or hits[0][0] is hits[1][0]:
            continue
        (_, d0), (_, d1) = (arrow_axis(h[0]) for h in hits)
        if d0[0] * d1[0] + d0[1] * d1[1] < BRACKET_SAME_COS:
            continue
        out += [p, hits[0][0], hits[1][0]]
        used.update(id(h[0]) for h in hits)
    return out


def _black_fill_signature(group):
    """검은 채움 묶음(_black_fill_groups)의 모양 서명. 곧은 채움은 검은 몸체로, 둥근 점은 표식으로 센다. 몸체로 올린 뒤
    기호로 묶였을 때의 서명(symbols.sym_signature)과 같아야 같은 견본에 다시 맞는다."""
    solid = [dict(m, solid=True, closed=True) for m in group["straight"]]
    return symbols.signature(solid, [], group["round"], [], group["bbox"])


def _has_spring(sym):
    """스프링선: 4pt 이하 직선 조각 둘 이상이 같은 기울기(10도 안)로 비스듬하다(가로·세로 15도 안은 아님).
    범례 1.7-1 1/4 SELF-ACTUATED VALVES의 안전·방출 밸브 줄기 위 사선이다. 보통 셋이지만 025·033·037·040쪽처럼 둘만 남는
    방출 밸브가 있다."""
    slants = []
    for st in sym.strokes:
        if len(st["pts"]) != 2:
            continue
        (x0, y0), (x1, y1) = st["pts"]
        if not 0.5 <= math.hypot(x1 - x0, y1 - y0) <= 4.0:
            continue
        a = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180
        if min(a, 180 - a) > 15 and abs(a - 90) > 15:
            slants.append(a)
    return any(sum(1 for b in slants if min(abs(a - b), 180 - abs(a - b)) <= 10) >= 2 for a in slants)


def _symbol_match(sym, blocks):
    """기호 상자 안에 가운데가 든 글자 문단을 글자 조건으로 넘겨 사전에 대 본다. 격자 견본은 모양이 비슷한 다른 기호에도
    맞을 수 있어, 스프링이 뜻인 종류(SPRING_KINDS)는 스프링선이 실제로 있을 때만 맞은 것으로 본다(F1-6 검토)."""
    x0, y0, x1, y1 = sym.bbox
    inside = [b["text"] for b in blocks if x0 <= (b["bbox"][0] + b["bbox"][2]) / 2 <= x1
              and y0 <= (b["bbox"][1] + b["bbox"][3]) / 2 <= y1]
    hit = symbol_library().match(symbols.sym_signature(sym), inside)
    if hit.outcome == "matched" and hit.entry.kind in SPRING_KINDS and not _has_spring(sym):
        return symbols.Match("none", None, None, None, hit.candidates, None)
    return hit


def _classify(sym, text, degree, prm, marks=()):
    """(kind, basis) — 근거가 없으면 kind None. marks: 기호 안 표기 글자(밸브 구동부의 M 등)."""
    if getattr(sym, "sparger", False):
        return "sparger", SPARGER_BASIS
    shape, sbasis = _shape_rule(sym, prm)
    if getattr(sym, "flow_arrow", False) and shape != "air_flow_arrow":
        return None, None  # 흐름 화살표(_arrow_heads)는 '선과 표식' 체크밸브가 아니고, 옆 글자의 설비 낱말로 종류를 정하지도 않는다
    if shape in ("control_valve", "motor_operated_valve") and "M" in [m.strip().upper() for m in marks]:
        return "motor_operated_valve", "valve_body+actuator_mark:M"
    if shape == "instrument":
        kind, basis = _instrument_kind(text, min(_w(sym.bbox), _h(sym.bbox)))
        if kind is None:  # 원형이지만 계기 문자가 아니면 장비 이름 낱말(예: 원형 펌프 기호에 PUMP)을 본다
            kind, basis = _kind_from_text(text)
        return kind, basis or "circle_without_isa_letters"
    if shape is not None:
        return shape, sbasis
    if sym.seed is not None:  # 검정 견본으로 올린 몸통은 사전이 정한다. 라벨의 장비 낱말이나 끝막음 규칙으로 정하지 않는다
        return None, None
    if sym.stroke_only and min(_w(sym.bbox), _h(sym.bbox)) == 0:
        # 곧은 선 하나로 된 선 기호는 설비 외곽이 아니다. 옆 글자의 설비 낱말로 종류를 정하지 않는다(APR1400 025쪽
        # 'CCW HX BLDG.' 경계 표시 옆에 남은 눈금 토막이 열교환기가 되던 자리)
        return None, None
    kind, basis = _kind_from_text(text)
    if kind is not None and rules.KIND_CATEGORY.get(kind) == "equipment" and \
            max(_w(sym.bbox), _h(sym.bbox)) < NAME_EQUIPMENT_MIN:
        # 설비 이름 낱말은 긴 변이 몇 pt인 조각(이름 글자 옆 배관 끝 막대·화살촉, 'LEAK CHASE PIPING … TANK' 옆 토막)의
        # 종류를 정하지 않는다. 143쪽 전수 점검에서 이런 조각 15개 가운데 14개가 틀렸다(2026-11-16). 스트레이너·벤트처럼
        # 배관 위 부품은 작게 그리므로 설비 분류에만 둔다
        kind, basis = None, None
    if kind is not None:
        return kind, basis
    # 몸체 안에 원이 든 기호(소화전 등)는 끝막음이 아니다. 삼각형 하나뿐인 몸체도 아니다: 범례 1.7-1 1/4의 끝막음은 배관
    # 끝의 괄호·반원이고, 막대에 매단 삼각형은 SPRAY NOZZLE OR SPARGER의 분사구다
    if not text and degree == 1 and not sym.stroke_only and max(_w(sym.bbox), _h(sym.bbox)) <= prm["pipe_cap_max"] \
            and not (len(sym.bodies) >= 2 and any(b.get("curved") for b in sym.bodies)) \
            and not any(_is_triangle(b) for b in sym.bodies) \
            and (any(b.get("curved") for b in sym.bodies) or
                 max(_w(sym.core), _h(sym.core)) >= PIPE_CAP_ASPECT * min(_w(sym.core), _h(sym.core))) \
            and not any(b.get("closed") and not b.get("curved") and not _is_convex(b["pts"]) for b in sym.bodies):
        # 끝막음은 배관 끝을 가로지르는 납작한 막대·괄호·반원이다(범례 1.7-1 1/4). 삼각형이 든 몸체(LT 반쪽 칠한 밸브의
        # 흰 반쪽 + 축소관)와 네모 상자(S 상자, 범례 쪽 X·* 상자, 시료 패널)는 끝막음이 아니다. 143쪽 pipe_cap 표본
        # 40개 가운데 20개가 이런 것이었다(2026-11-16)
        # 나비처럼 꼬인 닫힌 다각형은 밸브 몸통이다. 구동부와 따로 묶인 솔레노이드 파일럿 밸브는 S 상자 선 하나만 닿아도
        # 끝막음이 아니다(APR1400 063쪽 240)
        return "pipe_cap", PIPE_CAP_BASIS
    return None, None


PIPE_CAP_ASPECT = 1.4  # 곧은 변 끝막음 몸체의 긴 변 / 짧은 변 하한(납작한 막대)
WORD_INSIDE_RE = re.compile(r"[A-Z]{2,}")  # 기호 상자 안 낱말(두 글자 이상 대문자)
NAME_EQUIPMENT_MIN = 6.0  # 이름 낱말로 설비 종류를 정하는 기호의 긴 변 하한(pt). 가장 작은 펌프 기호가 10pt 안팎
PATTERN_MAX = 6.0        # 무늬 낱개: 긴 변 상한(pt). 밸브 몸통·S 상자는 5~11pt라 늘어서도 선이 닿는다
PATTERN_RUN = 3          # 격자: 같은 모양이 같은 간격으로 한 방향은 이 수 이상, 다른 방향은 둘 이상 늘어선다
PATTERN_SIZE_TOL = 0.3   # 같은 모양: 너비·높이 차 상한(pt)
PATTERN_PITCH_TOL = 0.15  # 같은 간격: 간격 차 ≤ 간격 × 비율
PATTERN_PITCH_MAX = 3.0  # 무늬 간격 상한 = 낱개 긴 변 × 배수
STRAY_FLAT = 0.05        # 넓이 없는 조각: 짧은 변 상한(pt)
FRAME_MIN = 50.0         # 빈 틀: 짧은 변 하한(pt). 선이 아직 안 붙은 기기 상자(40pt 안팎)보다 크다


HATCH_MIN = 3        # 빗금 칠한 단면: 몸체 안 평행선 수 하한
HATCH_COS = 0.995    # 빗금끼리 평행하다고 보는 방향 코사인(약 6도 안)


def _hatch_block(s):
    """곧은 변 닫힌 몸체 하나와, 그 안에 같은 방향으로 그은 곧은 선 셋 이상으로만 된 기호인가(단면 빗금, APR1400 007쪽 베어링)."""
    if len(s.bodies) != 1 or s.markers or s.dashes or len(s.strokes) < HATCH_MIN or \
            not s.bodies[0].get("closed") or s.bodies[0].get("curved"):
        return False
    dirs = []
    for m in s.strokes:
        if len(m["pts"]) != 2 or m.get("curved") or not _inside(_center(m["bbox"]), s.bodies[0]["bbox"]):
            return False
        (x0, y0), (x1, y1) = m["pts"]
        L = math.hypot(x1 - x0, y1 - y0)
        if not L:
            return False
        dirs.append(((x1 - x0) / L, (y1 - y0) / L))
    return all(abs(d[0] * dirs[0][0] + d[1] * dirs[0][1]) >= HATCH_COS for d in dirs)


SPARGER_BASIS = "triangle_row_on_line"
COUPLER_BASIS = "pipe_end_bracket_open_outward"
COUPLER_MAX = 6.0  # 호스 연결구 괄호 긴 변 상한(pt). APR1400 097쪽 3~4pt
# 등판 길이 ≥ 발 길이 × 비율. 범례 괄호는 약 3배, 097·103·131쪽은 약 2배다. 등판과 발이 같은 1.5pt 'ㅂ'꼴(024쪽 'V'
# 옆 벤트 마개)은 넣지 않는다
COUPLER_BAR_RATIO = 1.5


GOOSENECK_BASIS = "pipe_end_bent_back_180"
GOOSENECK_MAX = 9.0       # 굽이 폭(굽기 시작한 점 ~ 배관 끝) 상한(pt). APR1400 025·097·128쪽 4.4~7.7
GOOSENECK_TICK_MAX = 3.0  # 굽이 끝 막대(WITH SCREEN) 긴 변 상한(pt). 128·097쪽 1.3~1.9
GOOSENECK_RISE = (0.3, 0.7)  # 굽이 높이 / 굽이 폭. 반원이면 0.5
GOOSENECK_BACK = 0.35     # 배관 끝이 굽기 시작한 높이에서 벗어나도 되는 정도(굽이 높이 × 비율)
GOOSENECK_LEG = 0.3       # 굽기 전 곧은 배관 길이 하한 = 굽이 폭 × 비율(025쪽 밸브 바로 위 굽이는 폭 4.4pt에 다리 3pt)
GOOSENECK_LEG_TOL = 0.15  # 곧은 다리 위 점이 다리 방향 직선에서 벗어나도 되는 거리(pt)


def _is_gooseneck(sym, seq, curved_chain, prm):
    """범례 1.7-1 1/4 ATMOSPHERIC VENT (WITH / WITHOUT SCREEN): 배관 끝이 곡선으로 반 바퀴 돌아 처음 방향의 반대로 내려온다.
    seq: 이 기호에 닿은 배관 사슬의 점(기호 쪽이 끝). 굽이는 기호 자체(곡선 하나뿐인 선 기호, 025쪽)이거나, 사슬 안의 곡선이고
    기호는 끝의 작은 막대(128·097쪽)다. 굽이 높이가 폭의 절반 안팎이고 끝이 굽기 시작한 높이로 돌아와야 한다. 90도 꺾임은
    돌아오지 않고, 배관 중간의 U자 트랩은 배관 끝이 아니다."""
    if not sym.stroke_only or sym.bodies or sym.markers or sym.dashes:
        return False
    pts = list(seq)
    if len(sym.strokes) == 1 and sym.strokes[0].get("curved"):
        arc = list(sym.strokes[0].get("fine") or sym.strokes[0]["pts"])
        if math.dist(arc[-1], pts[-1]) < math.dist(arc[0], pts[-1]):
            arc = arc[::-1]
        if math.dist(arc[0], pts[-1]) > prm["end_tol"]:
            return False
        pts += arc[1:]
    elif not curved_chain or any(st.get("curved") for st in sym.strokes) or \
            max(_w(sym.bbox), _h(sym.bbox)) > GOOSENECK_TICK_MAX:
        return False
    end = pts[-1]
    for i in range(len(pts) - 2, 0, -1):
        a = pts[i]
        lat_end = math.dist(a, end)
        if lat_end > GOOSENECK_MAX:
            break
        prev = next((p for p in reversed(pts[:i]) if math.dist(p, a) > 0.3), None)
        if prev is None or lat_end < 1.0:
            continue
        L = math.dist(prev, a)
        u = ((a[0] - prev[0]) / L, (a[1] - prev[1]) / L)
        leg = 0.0  # 굽기 전 곧은 배관 길이. 곡선끼리 이어진 물결 외곽(111쪽 둥근 칸막이)은 곧은 다리가 없다
        for p in reversed(pts[:i]):
            if abs((p[0] - a[0]) * u[1] - (p[1] - a[1]) * u[0]) > GOOSENECK_LEG_TOL:
                break
            leg = max(leg, math.dist(p, a))
        if leg < max(1.0, GOOSENECK_LEG * lat_end):
            continue
        rise = [(p[0] - a[0]) * u[0] + (p[1] - a[1]) * u[1] for p in pts[i:]]
        h = max(rise)
        if h > 0 and GOOSENECK_RISE[0] <= h / lat_end <= GOOSENECK_RISE[1] and abs(rise[-1]) <= GOOSENECK_BACK * h \
                and min(rise) >= -GOOSENECK_BACK * h:
            return True
    return False


def _is_coupler(sym, pt, d, prm):
    """범례 1.7-1 1/4 HOSE CONNECTION (COUPLER) '—[': 배관 끝 pt(바깥 방향 d)가 괄호 등판 가운데에 닿고, 등판 양 끝에서
    두 발이 배관 반대쪽으로 뻗는다. 발이 배관 쪽으로 오면 나사 마개(SCREWED CAP '—]'), 등판과 나란한 둘째 막대가 있으면
    막음 플랜지(BLIND FLANGE '—| |'), 가운데에도 발이 있으면 숨구멍 마개(BREATHER CAP)라 아니다."""
    if not sym.stroke_only or sym.bodies or max(_w(sym.bbox), _h(sym.bbox)) > COUPLER_MAX:
        return False
    tol = prm["end_tol"]
    across, along = [], []
    for st in sym.strokes:
        for a, b in zip(st["pts"], st["pts"][1:]):
            L = math.dist(a, b)
            if L < 0.3:
                continue
            ra = ((a[0] - pt[0]) * d[0] + (a[1] - pt[1]) * d[1], (a[0] - pt[0]) * d[1] - (a[1] - pt[1]) * d[0])
            rb = ((b[0] - pt[0]) * d[0] + (b[1] - pt[1]) * d[1], (b[0] - pt[0]) * d[1] - (b[1] - pt[1]) * d[0])
            if min(ra[0], rb[0]) < -0.3 * tol:
                return False  # 배관 쪽으로 넘어온 선(나사 마개의 발 등)
            cos = abs((b[0] - a[0]) * d[0] + (b[1] - a[1]) * d[1]) / L
            if cos <= 0.2:
                across.append((ra, rb))
            elif cos >= 0.98:
                along.append((ra, rb))
            else:
                return False
    if not across or any(max(ra[0], rb[0]) > tol for ra, rb in across):
        return False  # 등판은 배관 끝 한 줄뿐이다
    lo = min(min(ra[1], rb[1]) for ra, rb in across)
    hi = max(max(ra[1], rb[1]) for ra, rb in across)
    if lo > -0.5 or hi < 0.5 or len(along) != 2:
        return False
    sides = sorted(ra[1] for ra, _ in along)
    reach = [max(ra[0], rb[0]) for ra, rb in along]
    return sides[0] <= 0.7 * lo and sides[1] >= 0.7 * hi and min(reach) >= 0.8 and \
        hi - lo >= COUPLER_BAR_RATIO * max(reach) and all(min(ra[0], rb[0]) <= tol for ra, rb in along)


def _sparger_rows(syms, polys, prm):
    """범례 1.7-1 SPRAY NOZZLE OR SPARGER: 곧은 선 하나에 같은 크기 작은 삼각형 셋 이상이 같은 간격으로 매달린 것은 분사구
    하나다(008쪽 SPARGER 막대, 134쪽 탱크 안 배관 끝). 삼각형마다 따로 노드가 되지 않게 한 기호로 묶고 sparger 표시를 단다.
    줄 길이 안에서 끝나는 선(막대)은 기호에 넣고, 줄 밖으로 이어지는 선(공급 배관)은 그대로 둔다 → 남은 선 목록."""
    tri = {}
    for s in syms:
        if len(s.bodies) == 1 and _is_triangle(s.bodies[0]) and not (s.markers or s.dashes) and s.seed is None:
            size = max(_w(s.bodies[0]["bbox"]), _h(s.bodies[0]["bbox"]))
            if size <= PATTERN_MAX and all(max(_w(m["bbox"]), _h(m["bbox"])) <= size for m in s.strokes):
                tri[id(s)] = s
    used, rest = set(), []
    for p in polys:
        if len(p["pts"]) != 2 or p.get("curved"):
            rest.append(p)
            continue
        (ax, ay), (bx, by) = p["pts"]
        L = math.hypot(bx - ax, by - ay)
        on = [s for k, s in tri.items() if k not in used and L and
              _poly_box_dist(p["pts"], s.bodies[0]["bbox"]) <= prm["touch_tol"]]
        if len(on) < PATTERN_RUN:
            rest.append(p)
            continue
        a = on[0].bodies[0]["bbox"]
        on = [s for s in on if abs(_w(s.bodies[0]["bbox"]) - _w(a)) <= PATTERN_SIZE_TOL
              and abs(_h(s.bodies[0]["bbox"]) - _h(a)) <= PATTERN_SIZE_TOL]
        ux, uy = (bx - ax) / L, (by - ay) / L
        on.sort(key=lambda s: (_center(s.bodies[0]["bbox"])[0] - ax) * ux + (_center(s.bodies[0]["bbox"])[1] - ay) * uy)
        at = [(_center(s.bodies[0]["bbox"])[0] - ax) * ux + (_center(s.bodies[0]["bbox"])[1] - ay) * uy for s in on]
        gaps = [q - r for r, q in zip(at, at[1:])]
        size = max(_w(a), _h(a))
        if len(on) < PATTERN_RUN or not all(0 < g <= PATTERN_PITCH_MAX * size and abs(g - gaps[0]) <= PATTERN_PITCH_TOL * gaps[0]
                                            for g in gaps):
            rest.append(p)
            continue
        row = on[0]
        for s in on[1:]:
            row.merge(s)
        row.sparger = True
        used.update(id(s) for s in on)
        if all(_inside(e, row.bbox, prm["touch_tol"]) for e in p["pts"]):
            row.add([p], "strokes")
        else:
            rest.append(p)
    return [s for s in syms if s.alive], rest


def _straight_stroke(m, prm):
    """꺾이지 않은 선(같은 줄 위 점이 여럿이어도 된다)."""
    a, b = m["pts"][0], m["pts"][-1]
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    return not m.get("curved") and L > 0 and all(
        abs((q[0] - a[0]) * (b[1] - a[1]) - (q[1] - a[1]) * (b[0] - a[0])) / L <= prm["touch_tol"] for q in m["pts"])


def _line_head(strokes, markers, prm, taken=()):
    """선 하나의 끝이 화살촉 밑변 안에 있고 화살촉 가운데가 그 선을 늘인 줄 위 앞쪽에 있으면 그 화살촉. 없으면 None."""
    for st in strokes:
        a, b = st["pts"][0], st["pts"][-1]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        for e, o in ((a, b), (b, a)) if L else ():
            ux, uy = (e[0] - o[0]) / L, (e[1] - o[1]) / L
            for m in markers:
                c = _center(m["bbox"])
                if id(m) not in taken and _is_triangle(m) and _inside(e, m["bbox"], prm["touch_tol"]) and \
                        (c[0] - e[0]) * ux + (c[1] - e[1]) * uy > 0 and \
                        abs((c[0] - e[0]) * uy - (c[1] - e[1]) * ux) <= prm["touch_tol"]:
                    return m
    return None


AIR_BAR_RATIO = 3.0  # 덕트 끝 막대: 길이 ≤ 화살촉 긴 변 × 비율, 몸통 줄에서 앞뒤로 떨어진 거리 ≤ 화살촉 긴 변 × 비율


def _end_bar(strokes, markers, prm):
    """몸통 선 하나의 끝에 화살촉이 달리고, 몸통 줄 위 머리 앞이나 꼬리 뒤에 몸통을 가로지르는 짧은 막대가 있는가
    (범례 1.7-1 2/4 DUCTED AIR FLOW의 덕트 끝 막대). 몸통 줄 양쪽으로 길게 뻗은 선(128쪽 건물 경계 TGB|AB 칸막이)은
    막대가 아니다."""
    for st in strokes:
        head = _line_head([st], markers, prm)
        if head is None:
            continue
        size = max(_w(head["bbox"]), _h(head["bbox"]))
        a, b = st["pts"][0], st["pts"][-1]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        ts = [0.0, L] + [(q[0] - a[0]) * ux + (q[1] - a[1]) * uy for q in head["pts"]]
        lo, hi = min(ts), max(ts)
        for bar in strokes:
            p, q = bar["pts"][0], bar["pts"][-1]
            M = math.hypot(q[0] - p[0], q[1] - p[1])
            if bar is st or not M or M > AIR_BAR_RATIO * size or abs(ux * (q[0] - p[0]) + uy * (q[1] - p[1])) > 0.1 * M:
                continue
            c = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            t = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy
            if abs((c[0] - a[0]) * uy - (c[1] - a[1]) * ux) <= M / 2 and not lo < t < hi and \
                    lo - AIR_BAR_RATIO * size <= t <= hi + AIR_BAR_RATIO * size:
                return True
    return False


def _is_air_arrow(sym, prm):
    """범례 1.7-1(2 of 4) DUCTED/NON-DUCTED AIR FLOW: 곧은 선만으로 된 선 기호(굵은 몸통)의 한 선 끝에 그 선을 늘인 줄 위로
    화살촉 하나가 달리고, 몸통 줄 위에 덕트 끝 막대가 있다(_end_bar). 머리는 _arrow_heads가 붙였거나 기호 묶기에서 이미
    들어왔다(APR1400 072쪽). 막대 없이 선과 화살촉만인 것(012쪽 배기 화살표)이나 칸막이 선 옆 화살표(128쪽 건물 경계)는
    덕트 끝 화살표가 아니다."""
    if not sym.stroke_only or sym.bodies or sym.dashes or len(sym.markers) != 1 or \
            not all(_straight_stroke(m, prm) for m in sym.strokes):
        return False
    return _end_bar(sym.strokes, sym.markers, prm)


def _arrow_heads(syms, markers, prm):
    """덕트 끝 공기 흐름 화살표(_is_air_arrow)의 한 선이 홀로 남은 화살촉 밑변에서 끝나고 화살촉이 그 선을 늘인 줄 위에
    있으면, 화살촉은 그 기호의 머리다(APR1400 072·080쪽 공조 덕트 끝 화살표). 머리가 떨어져 몸통만 노드가 되지 않게 기호에
    넣는다. 배관이 닿은 기호(syms)만 본다. 사슬을 다 이은 뒤라 머리가 선 끝을 빼앗지 않고, 어느 선도 닿지 않은 몸통(008쪽
    안전밸브 배기 화살표)은 넓이 없는 조각으로 그대로 버린다 → 남은 화살촉 목록."""
    taken, seen = set(), set()
    for s in syms:
        if id(s) in seen:
            continue
        seen.add(id(s))
        if s.stroke_only and not (s.bodies or s.markers or s.dashes) and \
                all(_straight_stroke(m, prm) for m in s.strokes):
            m = _line_head(s.strokes, markers, prm, taken)
            if m is not None:
                s.add([m], "markers")
                s.flow_arrow = True
                taken.add(id(m))
    return [m for m in markers if id(m) not in taken]


def _noise_symbols(syms, degree, label_of, prm):
    """노드로 내지 않을 기호 {id(기호): 까닭}.
    - pattern_grid: 작은 닫힌 도형 하나로 된 같은 모양이 같은 간격으로 한 방향 셋 이상, 다른 방향 둘 이상 늘어선 격자. 담는 외곽
      안에 그린 관 다발 점 격자(APR1400 007쪽 베어링 냉각기)는 무늬이지 기호가 아니다. 무늬에 닿은 선 끝은 무늬에 붙이지
      않는다(점 격자 옆을 지나는 선이 점 하나에 닿는다). 한 줄로만 늘어선 것은 무늬로 보지 않는다. 막대에 매단 삼각형
      줄은 분사구(범례 1.7-1 SPRAY NOZZLE OR SPARGER, 008쪽 SPARGER)다.
    - stray_stroke: 어느 선도 닿지 않고 넓이 없는 선 조각이나 크기 없는 경로만 남은 것(089쪽 글자 밑줄, 080쪽 0×0 경로).
    - bare_outline: 어느 선도 닿지 않고 이름도 없이 아무것도 담지 않은 짧은 변 FRAME_MIN 이상 빈 상자(080쪽 그림 틀).
      장비 이름도 배관도 없는 틀이다. 무언가를 담은 외곽(방·탱크)은 이름이 없어도 그대로 둔다.
    - hatch_block: 이름 없이 빗금만 친 닫힌 몸체(_hatch_block). 기계 단면의 빗금이다(007쪽 베어링). 단면에 맞닿은 축 선이
      빗금 칸에 닿아도 연결이 아니라서 무늬처럼 그 선 끝을 붙이지 않는다."""
    # 줄은 모든 기호의 작은 닫힌 몸체로 잰다. 격자 점 몇 개가 옆 기호에 묶여 들어가도 남은 점이 그 격자에 든다
    small = [b["bbox"] for s in syms for b in s.bodies if b.get("closed")
             and max(_w(b["bbox"]), _h(b["bbox"])) <= PATTERN_MAX]
    out = {}
    for s in syms:
        if len(s.bodies) != 1 or s.strokes or s.markers or s.dashes or not s.bodies[0].get("closed") or \
                max(_w(s.bbox), _h(s.bbox)) > PATTERN_MAX:
            continue
        a = s.bbox
        runs = []
        for ax in (0, 1):  # 0: 가로 줄(같은 y), 1: 세로 줄(같은 x)
            row = sorted({_center(b)[ax] for b in small if abs(_w(b) - _w(a)) <= PATTERN_SIZE_TOL
                          and abs(_h(b) - _h(a)) <= PATTERN_SIZE_TOL
                          and abs(_center(b)[1 - ax] - _center(a)[1 - ax]) <= PATTERN_SIZE_TOL})
            gaps = [q - p for p, q in zip(row, row[1:])]
            size, me = max(_w(a), _h(a)), row.index(_center(a)[ax])
            k = 0
            while k < len(gaps):
                j = k
                while j < len(gaps) and 0 < gaps[j] <= PATTERN_PITCH_MAX * size and \
                        abs(gaps[j] - gaps[k]) <= PATTERN_PITCH_TOL * gaps[k]:
                    j += 1
                if k <= me <= j:
                    runs.append(j - k + 1)
                    break
                k = max(j, k + 1)
        if len(runs) == 2 and min(runs) >= 2 and max(runs) >= PATTERN_RUN:
            out[id(s)] = "pattern_grid"
    for i, s in enumerate(syms):
        if id(s) not in out and i not in label_of and _hatch_block(s):
            out[id(s)] = "hatch_block"
        if degree.get(id(s)) or id(s) in out:
            continue
        if min(_w(s.bbox), _h(s.bbox)) <= STRAY_FLAT and (not s.bodies or max(_w(s.bbox), _h(s.bbox)) <= STRAY_FLAT):
            out[id(s)] = "stray_stroke"
        elif i not in label_of and len(s.bodies) == 1 and not (s.strokes or s.markers or s.dashes or s.rings) and \
                s.bodies[0].get("closed") and not s.bodies[0].get("curved") and min(_w(s.bbox), _h(s.bbox)) >= FRAME_MIN:
            out[id(s)] = "bare_outline"
    return out


# ---------------------------------------------------------------- 태그

# 범례가 뜻을 정한 축 끝 글자 상자 → (kind, 속성, kind가 없을 때 말고도 올려도 되는 몸통 kind, 몸통이 밸브여야 하는지).
# 범례 1.7-1 1/4: S = SOLENOID OPERATORS (SPRING RETURN) FOR VALVES(어느 밸브 몸통에나 붙는다. 속성은 사전
# apr1400.solenoid_operator와 같다). P = L1-078 PILOT OPERATED SAFETY RELIEF(P 상자·축·스프링 단 앵글 밸브가 한 기호다.
# 사전 apr1400.angle_relief_valve와 같은 psv). 그 밖의 글자는 종류를 정하지 않는다
LETTER_KIND = {"S": ("solenoid_valve", {"actuator_type": "solenoid", "motive_power": "electric"}, ("manual_valve",), True),
               "P": ("psv", {}, (), False)}
LETTER_BOX_SQUARE_RATIO = 0.2  # 글자 상자: |폭-높이| ≤ 긴 변 × 비율
LETTER_STEM_RATIO = 2.5        # 글자 상자 축 길이 상한 = 상자 긴 변 × 비율(008쪽 P 상자 5.3pt·축 약 9pt)


OPERATOR_PIECE_MAX = 12.0  # 구동부 묶음 조각(복동 실린더 X 상자·반쪽 칠한 상자·솔레노이드 S 상자) 긴 변 상한(pt)
OPERATOR_LINK_MAX = 8.0    # 구동부 조각끼리 잇는 곧은 선 길이 상한(pt). S 상자에서 X 상자까지 빗선 약 5pt
STACK_AIR_TEXT = "IA"      # 계장용 공기(범례 4/4 VALVE OPERATOR CONTROLS의 구동부 옆 글자)
STACK_AIR_GAP = 5.0        # IA 글자와 묶음 조각 사이 거리 상한(pt). 143쪽 묶음에서 0~4.9pt, 그다음은 6pt 넘는 옆 밸브 몫


def _operator_stacks(syms, chains, valve_like, straight_stem_of, shape_of, hits, prm):
    """밸브 축 위에 쌓은 구동부 조각 묶음 → {밸브 기호 id: (밸브, [조각 기호])}.
    씨앗은 꺾이지 않은 축으로 밸브 하나에만 이어진 작은 조각이다. 거기서 맞닿거나 짧은 곧은 선으로 이어진 작은 조각을 모은다.
    조각은 종류를 못 정한 기호(사전 구동부는 넣는다)이고, 두 밸브의 묶음에 함께 들면 둘 다 버린다."""
    piece = set()
    for si, s in enumerate(syms):
        h = hits.get(si)
        if id(s) in valve_like or max(_w(s.bbox), _h(s.bbox)) > OPERATOR_PIECE_MAX or shape_of[si][0] is not None:
            continue
        if h is not None and h.outcome == "matched" and h.entry.role != "actuator":
            continue
        piece.add(id(s))
    order = {id(s): si for si, s in enumerate(syms)}
    links = collections.defaultdict(set)
    for ch in chains:
        if ch.get("dashed") or any(v[0] != "sym" for v, _, _ in ch["ends"]):
            continue
        a, b = ch["ends"][0][0][1], ch["ends"][1][0][1]
        straight = len({(round(q[0], 2), round(q[1], 2)) for q in ch["pts"]}) == 2
        if a is not b and id(a) in piece and id(b) in piece and (ch.get("pneumatic") or (
                straight and math.dist(ch["pts"][0], ch["pts"][-1]) <= OPERATOR_LINK_MAX)):
            links[id(a)].add(id(b))
            links[id(b)].add(id(a))
    ps = sorted(piece, key=order.get)
    for i, a in enumerate(ps):
        for b in ps[i + 1:]:
            if _box_gap(syms[order[a]].bbox, syms[order[b]].bbox) <= prm["touch_tol"]:
                links[a].add(b)
                links[b].add(a)
    owner, stacks = collections.defaultdict(set), {}
    for pid in ps:
        vs = {id(v): v for v in straight_stem_of.get(pid, [])}
        if len(vs) != 1:
            continue
        v = next(iter(vs.values()))
        seen, todo = {pid}, [pid]
        while todo:
            for nb in links[todo.pop()]:
                if nb not in seen:
                    seen.add(nb)
                    todo.append(nb)
        for q in seen:
            owner[q].add(id(v))
        stacks.setdefault(id(v), (v, set()))[1].update(seen)
    return {vid: (v, [syms[order[i]] for i in sorted(members, key=order.get)]) for vid, (v, members) in stacks.items()
            if all(owner[q] == {vid} for q in members)}


class _StackEntry:
    """구동부 묶음 하나로 정한 밸브 kind와 속성(사전 항목 자리에 넣어 _apply_merges가 그대로 쓴다)."""

    def __init__(self, kind, attributes):
        self.kind, self.attributes = kind, attributes
        self.id = "operator_stack:" + attributes["actuator_type"]


def _stack_entry(members, member_hits, blocks, chains):
    """구동부 묶음 → _StackEntry 또는 None(범례가 정하지 않은 묶음).
    - 축 위의 솔레노이드 S 상자 하나뿐이면 전자 밸브다(범례 1/4 SOLENOID OPERATORS (SPRING RETURN) FOR VALVES).
    - 사전에 없는 조각(복동 실린더의 X 상자·반쪽 칠한 상자, 스프링 복귀 구동부의 파일럿 밸브)이 있는 묶음은 다이어프램이
      있거나 계장용 공기(IA) 글자·공압 신호선이 묶음에 닿을 때만 공기구동 밸브다(범례 4/4 VALVE OPERATOR CONTROLS). S 상자는
      그 파일럿이다. 그 밖의 조각(손잡이, 사전에 없는 원 등)만 있는 묶음은 정하지 않는다."""
    types = {h.entry.attributes.get("actuator_type") for h in member_hits if h is not None and h.outcome == "matched"}
    others = sum(1 for h in member_hits if h is None or h.outcome != "matched")
    if not others:
        if len(members) == 1 and types == {"solenoid"}:
            return _StackEntry("solenoid_valve", dict(member_hits[0].entry.attributes))
        return None
    if not types <= {"diaphragm", "solenoid"}:
        return None
    air = "diaphragm" in types or any(
        b["text"].strip() == STACK_AIR_TEXT and min(_box_gap(b["bbox"], m.bbox) for m in members) <= STACK_AIR_GAP
        for b in blocks) or any(ch.get("pneumatic") and any(v[0] == "sym" and any(v[1] is m for m in members)
                                                            for v, _, _ in ch["ends"]) for ch in chains)
    if not air:
        return None
    kind = ("diaphragm" if "diaphragm" in types else "pneumatic") + ("+solenoid_pilot" if "solenoid" in types else "")
    return _StackEntry("air_operated_valve", {"actuator_type": kind, "motive_power": "air"})


def _letter_boxes(syms, chains, blocks, label_of, unclassified, prm):
    """범례 1.7-1 1/4: 밸브 위로 곧게 선 짧은 세로 축 끝의 글자 상자(L1-078 파일럿 작동 안전방출 밸브의 P, 솔레노이드
    구동부의 S)는 밸브 기호의 한 부분이다 → [(상자 기호, 축 반대 끝 기호, 글자)]. 상자는 종류를 못 정한 기호이고,
    안에 대문자 한 글자가 있고, 축 정렬 사각형 하나로 그렸고, 실선이 그 축 하나뿐이어야 한다. 축은 꺾이지 않은 세로선이고
    길이가 상자 크기에 비례한 상한 안이며, 반대 끝이 다른 기호여야 한다(분기점·떠 있는 끝은 아니다). 사선 지시선에
    매달린 상자(062쪽 G)와 원(072쪽 P)은 여기 들지 않는다."""
    solid_at = collections.defaultdict(list)
    for ch in chains:
        if ch.get("dashed"):
            continue
        for k in (0, 1):
            v = ch["ends"][k][0]
            if v[0] == "sym":
                solid_at[id(v[1])].append((ch, ch["ends"][1 - k][0]))
    out = []
    for si in sorted(unclassified):
        s, bi = syms[si], label_of.get(si)
        if bi is None or len(solid_at[id(s)]) != 1 or not re.fullmatch(r"[A-Z]", blocks[bi]["text"].strip()):
            continue
        side = max(_w(s.bbox), _h(s.bbox))
        if not (_inside(_center(blocks[bi]["bbox"]), s.bbox) and len(s.bodies) == 1 and not s.strokes
                and _is_axis_rect(s.bodies[0], prm["axis_rect_tol"]) and min(_w(s.bbox), _h(s.bbox)) >= prm["stroke_symbol_min"]
                and abs(_w(s.bbox) - _h(s.bbox)) <= LETTER_BOX_SQUARE_RATIO * side):
            continue
        ch, far = solid_at[id(s)][0]
        a, b = ch["pts"][0], ch["pts"][-1]
        if (far[0] == "sym" and far[1] is not s and len({(round(q[0], 2), round(q[1], 2)) for q in ch["pts"]}) == 2
                and abs(a[0] - b[0]) <= prm["touch_tol"] and abs(a[1] - b[1]) <= LETTER_STEM_RATIO * side
                and side <= max(_w(far[1].bbox), _h(far[1].bbox))):
            out.append((s, far[1], blocks[bi]["text"].strip()))
    return out


def _merged_line(ch, merge_into, number_ids):
    """합친 기호와 그 밸브 사이 선(축), 번호 원에서 떠 있는 지시선이면 그 이유. 아니면 None."""
    ends = [v[1] for v, _, _ in ch["ends"] if v[0] == "sym"]
    for x in ends:
        target = merge_into.get(id(x))
        if target is None:
            continue
        number = id(x) in number_ids
        if len(ends) == 2 and all(merge_into.get(id(y), y) is target for y in ends):
            return "valve_number_leader" if number else "actuator_stem"
        if len(ends) == 1 and number and not ch.get("dashed"):
            return "valve_number_leader"
    return None


def _apply_merges(syms, node_out, locations, unknowns, dropped, instrument_ids, local_of, chains, acts_on, numbers_on,
                  boxes_on):
    """S5(D6): 계획한 구동부·번호 원을 노드 kind가 정해진 뒤 밸브에 합친다 → {합친 기호 id: 밸브 기호}.
    - 글자 상자(_letter_boxes): 상자 kind가 없고 축 반대 끝 노드가 kind 없음이나 밸브면 합치고 글자를
      evidence.actuator_marks에 남긴다. 상자가 하나뿐이고 사전 구동부가 없으며 범례가 그 글자의 뜻을 정했으면
      (LETTER_KIND) kind를 올린다.
    - 구동부: 밸브 kind가 없거나 수동이면 범례가 정한 kind로 올리고 actuator_type·motive_power를 단다. 이미 구동 밸브면
      속성만 단다(kind가 다르면 합치지 않는다). 그 밖의 kind(체크 밸브, 글자로 정한 펌프 등)나 범례에 없는 조합은
      합치지 않는다(구동부를 노드로 남겨 정보를 잃지 않는다).
    - 번호 원: 밸브(또는 kind 없는 밸브 모양)에 번호가 하나뿐일 때만 evidence.ident_number로 둔다.
    합친 기호의 노드·미확인은 지우고 drawing.ignored_objects에 남긴다. 합친 기호·축·지시선의 PDF 객체는 밸브의
    evidence.merged_objects에 남긴다. analysis의 기호 객체는 호출끼리 함께 쓰므로 고치지 않는다.
    → ({합친 기호 id: 밸브 기호}, 번호 원 id 집합)"""
    by_local = {nd["local_id"]: nd for nd in node_out}
    node_of = {id(sy): by_local[local_of[id(sy)][0]] for sy in syms if local_of[id(sy)][0] in by_local}
    merge_into, number_ids = {}, set()
    for sy in syms:
        nd = node_of.get(id(sy))
        if nd is None:
            continue
        kind, changed = nd["kind"], False
        boxes = [(b, t) for b, t in boxes_on.get(id(sy), []) if node_of.get(id(b)) is not None
                 and node_of[id(b)]["kind"] is None]
        entries = acts_on.get(id(sy), [])
        if boxes and (kind is None or rules.KIND_CATEGORY.get(kind) == "valve"):
            nd["evidence"]["actuator_marks"] = sorted(t for _, t in boxes)
            merge_into.update({id(b): sy for b, _ in boxes})
            rule = LETTER_KIND.get(boxes[0][1]) if len(boxes) == 1 and not entries else None
            if rule and (kind is None or kind in rule[2]) and (nd["category"] == "valve" or not rule[3]):
                nd.update(kind=rule[0], category=rules.KIND_CATEGORY[rule[0]], classification="classified")
                nd["evidence"]["classification_basis"] = "+".join(
                    filter(None, (nd["evidence"]["classification_basis"], "actuator_mark:" + boxes[0][1])))
                nd["attributes"] = dict(nd["attributes"], **rule[1])
        if entries and (kind is None or rules.KIND_CATEGORY.get(kind) == "valve"):
            new_kind, extra = _actuated_kind([e for _, e in entries])
            if new_kind and kind in (None, "manual_valve"):
                nd.update(kind=new_kind, category=rules.KIND_CATEGORY.get(new_kind), classification="classified")
                nd["evidence"]["classification_basis"] = "%s+actuator:%s" % (
                    nd["evidence"]["classification_basis"], "+".join(sorted({e.id for _, e in entries})))
                changed = True
            elif new_kind and (kind == new_kind or kind == "control_valve"):
                changed = True
            if changed:
                nd["attributes"] = dict(nd["attributes"], **{k: v for k, v in extra.items()
                                                             if k in rules.REGISTRY.properties})
                merge_into.update({id(a): sy for a, _ in entries})
        numbers = numbers_on.get(id(sy), [])
        if numbers and len({t for _, t in numbers}) == 1 and (nd["kind"] is None or
                                                              rules.KIND_CATEGORY.get(nd["kind"]) == "valve"):
            nd["evidence"]["ident_number"] = numbers[0][1]
            number_ids.update(id(c) for c, _ in numbers if c is not sy)
            merge_into.update({id(c): sy for c, _ in numbers if c is not sy})  # 몸통과 한 기호로 묶인 원은 합칠 것이 없다
    if not merge_into:
        return merge_into, number_ids
    gone = {local_of[i][0] for i in merge_into}
    for sy in syms:
        nd = node_of.get(id(sy))
        if nd is None or nd["local_id"] in gone or not any(v is sy for v in merge_into.values()):
            continue
        objs = [o for i, v in merge_into.items() if v is sy for x in syms if id(x) == i for o in x.evidence()]
        objs += [o for ch in chains if _merged_line(ch, merge_into, number_ids) and
                 any(v[0] == "sym" and merge_into.get(id(v[1])) is sy for v, _, _ in ch["ends"]) for o in ch["evidence"]]
        nd["evidence"]["merged_objects"] = sorted(set(objs))
        if nd["kind"] is not None:  # kind를 정했으면 보류·종류 없음 미확인은 풀린다
            unknowns[:] = [u for u in unknowns if not (u.get("target") == nd["local_id"] and
                                                      u["check"] in ("actuated_valve_pending", "missing_kind"))]
    for i in merge_into:
        nd = node_of[i]
        g = nd["geometry"]
        dropped.append({"source_object_id": nd["source_object_id"], "label_text": nd["label_text"],
                        "bbox": [g["x"], g["y"], g["width"], g["height"]],
                        "reason": "valve_number_merged" if i in number_ids else "actuator_merged"})
    node_out[:] = [nd for nd in node_out if nd["local_id"] not in gone]
    locations[:] = [lc for lc in locations if lc["local_id"] not in gone]
    unknowns[:] = [u for u in unknowns if u.get("target") not in gone]
    instrument_ids.difference_update(gone)
    return merge_into, number_ids


def _valve_gap(block, sym):
    return -1.0 if _inside(_center(block["bbox"]), sym.bbox) else _box_gap(block["bbox"], sym.bbox)


def _nearest_valve(block, valves, prm):
    """label_gap_max 안에서 문단에 가장 가까운 밸브. 두 번째 밸브가 확실히 멀 때만(number_reach 규칙과 같은 비율)."""
    near = sorted((_valve_gap(block, v), k) for k, v in enumerate(valves))
    near = [(g, k) for g, k in near if g <= prm["label_gap_max"]]
    if near and (len(near) == 1 or near[1][0] > max(2 * near[0][0], near[0][0] + 1.0)):
        return valves[near[0][1]]
    return None


def _valve_labels(syms, blocks, roles, valve_like, plan_into, label_of, taken, marks, drop, prm, circled=()):
    """밸브 라벨 고르기(F1-5). label_of·taken을 고치고 {밸브 기호 id: [(위치 약어, 문단 번호)]}를 돌려준다.
    탐욕 배정(가까운 글자부터)은 그대로 두고 밸브만 손본다. 다른 기호의 라벨은 바꾸지 않는다.
    - 라벨이 없거나 라벨에 밸브 번호 줄이 없는 밸브(위치 약어 NO·LC·'NC,FO', 옆 계기 상자의 경보 글자 'IAH', 배관 행선지
      글자 등)는, 아무 기호의 라벨도 아닌 밸브 번호('V1681', 댐퍼 'Y0029', 돌린 글자 포함)가 label_gap_max 안에 있고 그
      번호에 가장 가까운 밸브가 이 밸브이면 그 번호를 라벨로 삼는다. 가까운 다른 글자가 밸브 번호보다 먼저 라벨을 뺏던
      자리다(008쪽 V2300 옆 'IAH', 063쪽 V2023 옆 'REACTOR DRAIN HEADER').
    - 위치 약어는 태그가 아니라 속성이다. 밸브(또는 그 밸브에 합칠 구동부)의 라벨이었던 약어, 아무 기호의 라벨도 아니고
      가장 가까운 밸브가 하나로 정해지는 약어를 그 밸브의 정상·고장 위치로 둔다.
    - 밸브 번호를 태그로 쓸 밸브(→ 두 번째 돌려주는 값, 기호 번호 집합)는 라벨에 밸브 번호 줄이 있고, 그 라벨 문단에 가장
      가까운 기호가 이 밸브 하나인 것이다. 몸통 안에 구동부 표기(M, E/H) 말고 다른 글자가 든 기호는 밸브 번호를 받지 않는다.
      APR1400의 품질 등급 마름모('BI|CI')가 나비 규칙으로 밸브가 되어, 옆 밸브의 번호를 가져가던 자리다(063쪽 V751).
    - 번호 원(VALVE IDENT. NUMBER)이 합쳐질 밸브(circled, 기호 id)는 그 원이 번호다. 밸브 번호 글자를 받지 않는다(016쪽
      구동 밸브 348이 옆 체크 밸브의 V158을, 025쪽 방출 밸브 1108이 V1110을 가져가던 자리). 가장 가까운 밸브를 셀 때는
      그대로 넣어, 그 글자가 더 먼 다른 밸브로 가지도 않게 한다.
    - 밸브에 그 번호 문단보다 더 가까운 다른 밸브 번호 문단이 있으면 번호를 주지 않는다(미확인 missing_tag로 남는다).
      옆 밸브가 기호로 잡히지 않으면 owner_of가 그 밸브를 보지 못해, 이웃 번호를 받는다(025쪽 V1007~V1010 자리에
      V1001~V1004, 1pt 옆 V1311·V1312 대신 8.7pt 떨어진 V1309·V1310). 틀린 태그보다 빈 태그가 낫다. 거리는 번호 줄로
      잰다. 번호와 위치 약어가 한 문단이면 문단 상자는 약어 때문에 밸브에 붙는다(126쪽 'V1106' 아래 'LC', 밸브 번호는 V1134).
    - 라벨로 붙은 위치 약어도 _nearest_valve와 같은 비율로 다른 밸브보다 확실히 가까울 때만 그 밸브의 것이다. 두 밸브와
      같은 거리의 'LO'를 한 밸브에 단정하지 않는다."""
    lettered = {si for si, ms in marks.items() if any(not ACTUATOR_MARK_RE.fullmatch(" ".join(m.split())) for m in ms)}
    valves = [sy for si, sy in enumerate(syms) if id(sy) in valve_like and si not in lettered]
    index = {id(sy): si for si, sy in enumerate(syms)}
    others = [sy for si, sy in enumerate(syms) if si not in drop]

    def owner_of(bi):
        """문단에 몸체(core)가 가장 가까운 기호(밸브든 아니든). 기호 상자는 지시선·장식선까지 들어가 커지므로(062쪽 V2132
        위의 'DE→WM' 화살표) 몸체로 잰다. 같은 거리의 기호가 둘 이상이면 문단 가운데에서 몸체 가운데까지가 1pt 넘게 가까운
        기호다. 그것도 가리지 못하면 None. 밸브 몸통과 옆에 붙은 축소관은 아랫변이 같아 그 밑 번호까지 거리가 같다(062쪽
        V2130은 밸브 바로 밑 가운데에 찍힘)."""
        box = blocks[bi]["bbox"]
        near = sorted((-1.0 if _inside(_center(box), sy.core) else _box_gap(box, sy.core), k) for k, sy in enumerate(others))
        if not near or near[0][0] > prm["label_gap_max"]:
            return None
        tied = [k for g, k in near if g <= near[0][0] + 0.01]
        if len(tied) > 1:
            by_center = sorted((math.dist(_center(box), _center(others[k].core)), k) for k in tied)
            if by_center[1][0] - by_center[0][0] <= 1.0:
                return None
            return others[by_center[0][1]]
        return others[near[0][1]]

    def text(bi):
        return " ".join(blocks[bi]["text"].split())

    def number_lines(bi):
        """문단 bi의 밸브 번호 줄: [(번호, 줄 상자)]. 번호와 위치 약어가 한 문단('V1106' 아래 'LC')이면 번호 줄만 잰다."""
        lines = [" ".join(l.split()) for l in blocks[bi]["text"].split("\n")]
        boxes = blocks[bi].get("line_boxes") or [blocks[bi]["bbox"]] * len(lines)
        return [(l, box) for l, box in zip(lines, boxes) if NUMBER_PLATE_RE.fullmatch(l)]
    numbered_blocks = [(bj, number_lines(bj)) for bj in range(len(blocks)) if number_lines(bj)]

    def gap_to(box, sy):
        return -1.0 if _inside(_center(box), sy.bbox) else _box_gap(box, sy.bbox)

    def closer_number(bi, sy):
        """이 밸브에 문단 bi의 번호 줄보다 더 가까운 다른 밸브 번호 줄이 있는가."""
        mine = number_lines(bi)
        if not mine:
            return False
        own = min(gap_to(box, sy) for _, box in mine)
        return any(gap_to(box, sy) < own for bj, lines in numbered_blocks if bj != bi
                   for number, box in lines if number not in {n for n, _ in mine})

    def clearly_of(bi, owner, sy):
        """문단 bi가 이 밸브(owner, 또는 owner에 합칠 구동부 sy) 몫으로 분명한가(_nearest_valve의 비율)."""
        own = min(_valve_gap(blocks[bi], owner), _valve_gap(blocks[bi], sy))
        rival = min((_valve_gap(blocks[bi], v) for v in valves if v is not owner and v is not sy), default=None)
        return rival is None or rival > max(2 * own, own + 1.0)
    positions = {}
    for si, bi in label_of.items():
        owner = plan_into.get(id(syms[si]), syms[si])
        if id(owner) in valve_like and POSITION_TEXT_RE.fullmatch(text(bi)) and clearly_of(bi, owner, syms[si]):
            positions.setdefault(id(owner), []).extend((c, bi) for c in POSITION_CODE_RE.findall(blocks[bi]["text"]))
    for bi in range(len(blocks)):
        if bi in roles or bi in taken or not POSITION_TEXT_RE.fullmatch(text(bi)):
            continue
        v = _nearest_valve(blocks[bi], valves, prm)
        if v is not None:
            positions.setdefault(id(v), []).extend((c, bi) for c in POSITION_CODE_RE.findall(blocks[bi]["text"]))

    def stray(bi, sy):
        """기호 sy가 라벨로 잡은 밸브 번호 문단 bi가 다른 밸브의 것인가: 문단에 몸체가 가장 가까운 기호가 따로 있는 밸브다.
        이웃 밸브가 위치 약어('LO')를 먼저 라벨로 잡으면 그 번호는 다음으로 가까운 밸브가 가져간다(016쪽 V255 자리의 V413)."""
        own = owner_of(bi)
        return own is not None and own is not sy and id(own) in valve_like
    open_valves = {id(v) for v in valves if id(v) not in circled and (
                   label_of.get(index[id(v)]) is None or not number_lines(label_of[index[id(v)]])
                   or stray(label_of[index[id(v)]], v))}
    holder = {bi: si for si, bi in label_of.items()}

    def lent(bi):
        """밸브 번호 문단이 번호를 받지 못하는 기호의 라벨로 잡혀 있는가: 밸브가 아닌 기호(배관 부속·미분류 조각), 또는
        몸통 안에 다른 글자가 든 기호(lettered, 품질 등급 마름모 'BI|CI'). 밸브 번호는 밸브 몫이다. 위치 약어('LC')가
        밸브 라벨을 먼저 차지하면 번호는 그다음 가까운 마름모로 가던 자리다(016쪽 V290·V293)."""
        if bi not in holder:
            return False
        hs = holder[bi]
        host = plan_into.get(id(syms[hs]), syms[hs])
        return id(host) not in valve_like or hs in lettered or stray(bi, host)
    pairs = []
    for bi in range(len(blocks)):
        if bi in roles or (bi in taken and not lent(bi)) or not NUMBER_PLATE_RE.fullmatch(text(bi)):
            continue
        v = _nearest_valve(blocks[bi], valves, prm)
        if v is not None and id(v) in open_valves and owner_of(bi) is v and not closer_number(bi, v):
            pairs.append((round(_valve_gap(blocks[bi], v), 6), bi, index[id(v)]))
    moved = set()
    for gap, bi, si in sorted(pairs):
        if si in moved or (bi in taken and not lent(bi)):
            continue
        if lent(bi):
            del label_of[holder.pop(bi)]
            taken.discard(bi)
        old = label_of.get(si)
        if old is not None:
            taken.discard(old)
        label_of[si] = bi
        taken.add(bi)
        moved.add(si)
    numbered = {si for si, bi in label_of.items() if id(syms[si]) in valve_like and si not in lettered
                and id(syms[si]) not in circled
                and any(NUMBER_PLATE_RE.fullmatch(" ".join(l.split())) for l in blocks[bi]["text"].splitlines())
                and owner_of(bi) is syms[si] and not closer_number(bi, syms[si])}
    return positions, numbered


def _apply_positions(syms, node_out, unknowns, local_of, positions, blocks):
    """밸브 옆 위치 약어를 그 밸브 노드의 normal_position·fail_position으로 둔다. 글자는 evidence.position_text에 남긴다.
    기호 모양이 정한 값(검게 칠한 몸통의 NC)이 있으면 evidence.position_from_body에 남긴다. 그 옆 글자가 LC면 같은 닫힘을
    더 자세히 쓴 것이라 LC로 둔다. 그 밖에 이미 있는 값과 다르거나 약어끼리 서로 다르면 그 속성을 비우고 position_conflict
    미확인을 남긴다. 몸통 값과 글자는 근거(position_from_body·position_text)에 둘 다 남는다. 비우지 않으면 몸통 값이 확정
    주장(hazop.kg.claims)으로 넘어가 사람이 볼 일이 없어진다.
    속성은 레지스트리가 그 종류에 두는 것만 둔다(수동 밸브에는 fail_position이 없다). 종류에 없는 속성의 약어('LC,FC' 옆의
    수동 밸브)는 종류가 틀렸을 수 있어 position_kind_mismatch 미확인으로 남긴다. 밸브 분류가 아닌 노드(합쳐지지 않은 구동부
    등)에는 두지 않는다."""
    by_local = {nd["local_id"]: nd for nd in node_out}
    for sy in syms:
        found = positions.get(id(sy))
        nd = by_local.get(local_of[id(sy)][0]) if found else None
        if nd is None or nd["category"] != "valve":
            continue
        nd["evidence"]["position_text"] = [" ".join(blocks[bi]["text"].split()) for bi in sorted({bi for _, bi in found})]
        attrs = dict(nd["attributes"])
        cid = rules.REGISTRY.kind_class.get(nd["kind"]) or nd["category"]
        allowed = rules.REGISTRY.class_properties(cid)
        for field in ("normal_position", "fail_position"):
            codes = sorted({c for c, _ in found if POSITION_FIELD[c] == field})
            if not codes:
                continue
            if field not in allowed:
                _issue(unknowns, "position_kind_mismatch", "%s %s: %s 종류에는 없는 속성(종류를 확인할 것)"
                       % (field, "·".join(codes), nd["kind"] or nd["category"]), nd["source_object_id"], nd["local_id"], "kind")
                continue
            have = attrs.get(field)
            if have is not None:
                nd["evidence"]["position_from_body"] = have
            if len(codes) == 1 and (have in (None, codes[0]) or (have, codes[0]) in POSITION_REFINES):
                attrs[field] = codes[0]
                continue
            why = ("기호 모양은 %s, 글자는 %s" % (have, "·".join(codes)) if have
                   else "옆 글자가 %s로 서로 다름" % "·".join(codes))
            attrs.pop(field, None)
            _issue(unknowns, "position_conflict", "%s: %s(둘 다 근거에 남기고 정하지 않음)" % (field, why),
                   nd["source_object_id"], nd["local_id"], field)
        nd["attributes"] = attrs


# ---------------------------------------------------------------- 조립


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
    _promote_black_symbols(cls, prm)
    _mark_actuator_bodies(cls, prm)
    blocks = _text_blocks(words, prm)
    for p in cls["panels"]:  # 범례 1.7-1 2/4: 코일 판은 HC(가열)·CC(냉각) 글자를 단다. 글자 없는 무늬 판은 여과 판
        p["coil"] = any(_inside(_center(b["bbox"]), p["rect"]["bbox"]) and PANEL_COIL_WORDS & set(b["text"].upper().split())
                        for b in blocks)
    _mark_class_boundaries(cls, blocks, prm)
    _boundary_marks(cls, prm)
    ticks, marked = _line_ticks(cls["polys"], prm, cls["bodies"])
    syms, polys, markers, dashes = _group_symbols(cls, prm)
    syms, polys = _sparger_rows(syms, polys, prm)
    # 빗금은 기호 묶기가 끝난 뒤에 남은 선에서만 뺀다. 기호 장식선으로 흡수된 빗금은 그대로 두어 기호 모양과 번호가
    # 빗금 처리 전과 같게 한다(빗금을 먼저 빼면 안전밸브 규칙이 응축기 몸통에 맞는 등 기호 판정이 바뀜). 외톨이 // 도
    # 같다. 먼저 빼면 143쪽에서 기호 묶음이 달라져 새 안전밸브·끝막음 판정이 생겼다(F1-4 후보 비교)
    cls["ticks"] = [p for p in polys if p["id"] in ticks]
    polys = [p for p in polys if p["id"] not in ticks]
    tees, chains = _build_solid(syms, polys, markers, prm, cls["bridges"], cls["mouths"])
    for ch in chains:
        # 빗금 선으로만 되고 그 사슬 위에 빗금 묶음이 실제로 있는 사슬 = 공압 신호선. 배관과 섞이거나, 원래 경로가
        # 분기점에서 나뉘어 빗금 없는 쪽 토막이면 배관으로 둔다
        if ch["evidence"] and all(e in marked for e in ch["evidence"]) and any(
                _seg_dist(c, a, b)[0] <= prm["tick_host_dist"] for e in ch["evidence"] for c in marked[e]
                for a, b in _segs(ch["pts"])):
            ch["pneumatic"] = True
    chains += _contact_chains(syms, prm) + _housing_chains(syms, cls["cells"], prm)
    dots = _line_dots(dashes, polys, prm)  # 실선 위 점(매설 배관 무늬)은 점선 조각이 아니다
    cls["dots"] = [d for d in dashes if d["id"] in dots]
    # 점선도 검정 견본으로 올린 몸통(seed) 밑을 끊기지 않고 지나갈 수 있다. 몸통 안의 조각을 빼면 사슬이 거기서 끊겨
    # 양쪽 끝이 밸브에 붙는다(실선의 _cut_at_boxes와 같은 일)
    cores = [s.core for s in syms if s.seed is not None]
    chains += _build_dashed(syms, [d for d in dashes if d["id"] not in dots
                                   and not any(_inside(_center(d["bbox"]), c) for c in cores)], markers, prm)
    chains = _dashed_continuations(chains, prm)
    vents, chains = _vent_ends(chains, markers, polys, prm)
    syms += vents
    stubs, chains, tees = _stub_ends(tees, chains)
    syms += stubs
    syms = _merge_appendages(syms, chains, prm)
    for ch in chains:  # 흐름 방향: 사슬 위·끝에 남은 화살촉(pdf_vector_flow)
        if not ch.get("dashed") or ch.get("continues_pipe"):
            ch["flow"] = _chain_flow(ch, markers, prm)
    markers = _arrow_heads([v[1] for ch in chains for v, _, _ in ch["ends"] if v[0] == "sym"], markers, prm)
    return {"params": prm, "classified": cls, "symbols": syms, "tees": tees, "chains": chains,
            "blocks": blocks, "leftover_markers": markers}


def build_extraction(analysis, width, height, page_count, page, file_label, sha):
    """중간 결과 → extraction dict(drawio.extract와 같은 최상위·노드·관계 키)."""
    prm = analysis["params"]
    syms, tees, chains, blocks = analysis["symbols"], analysis["tees"], analysis["chains"], list(analysis["blocks"])
    cls = analysis["classified"]
    blockers, unknowns = [], []
    if not words_or_paths(analysis):
        _issue(blockers, "no_vector_content", "페이지에 글자·벡터 경로가 없음(스캔 PDF 등, 이 어댑터로 읽을 수 없음)")

    # 글자: 표제란·선 라벨·기호 라벨·나머지
    cell_boxes = [c["bbox"] for c in cls["cells"]]
    # 글자 줄과 같은 방향으로 글자 위를 지나는 선만 선 라벨 근거로 본다(가로지르는 선은 우연한 겹침). 돌린 글자는 세로
    # 선이 같은 방향이다. 돌린 밸브 번호를 가로 배관이 가로지르면 선 라벨이 되어 밸브가 번호를 잃던 자리다(128쪽 V1623)
    plain = [(a, b) for ch in chains if not ch.get("dashed") for a, b in _segs(ch["pts"])]
    solid_segments = [(a, b) for a, b in plain if abs(b[1] - a[1]) <= 0.2 * abs(b[0] - a[0])]
    solid_upright = [(a, b) for a, b in plain if abs(b[0] - a[0]) <= 0.2 * abs(b[1] - a[1])]
    shape_of = [_shape_rule(s, prm) for s in syms]
    # 연결 표시 화살표와 겹치는 문단(화살표 안 'SHEET n "X"'까지 한 문단)은 화살표 몫이다. 화살표로 들어가는 배관이
    # 그 문단을 지나도 배관 글자로 보지 않는다
    arrow_boxes = [s.bbox for s, sh in zip(syms, shape_of) if sh[0] == "continuation"]
    roles = {}
    for bi, b in enumerate(blocks):
        c = _center(b["bbox"])
        if any(_inside(c, cb) for cb in cell_boxes):
            roles[bi] = "title_block"
        elif any(_inside(c, m["bbox"]) for m in cls["masks"]) or (
                any(_poly_box_dist([s1, s2], _expand(b["bbox"], -0.5)) == 0.0
                    for s1, s2 in (solid_upright if b.get("rotated") else solid_segments))
                and not (SHEET_WORD_RE.search(b["text"]) and any(_box_gap(b["bbox"], ab) <= 0 for ab in arrow_boxes))):
            roles[bi] = "line_label"
    # 밸브 몸통·구동부 안 글자(M, E/H 등)는 태그가 아니라 기호 표기로 본다
    marks = {}
    for bi, b in enumerate(blocks):
        if bi in roles:
            continue
        for si, s in enumerate(syms):
            if rules.KIND_CATEGORY.get(shape_of[si][0]) == "valve" and _inside(_center(b["bbox"]), s.bbox):
                marks.setdefault(si, []).append(b["text"])
                roles[bi] = "symbol_mark"
                break
    degree, end_at, end_chain = {}, {}, {}
    for ch in chains:
        for k, (v, pt, _) in enumerate(ch["ends"]):
            if v[0] == "sym":
                degree[id(v[1])] = degree.get(id(v[1]), 0) + 1
                if not ch.get("dashed"):
                    end_at[id(v[1])] = ch["pts"] if k == 1 else ch["pts"][::-1]
                    end_chain[id(v[1])] = ch
    curved_ids = {p["id"] for p in cls["polys"] if p.get("curved")}
    couplers, goosenecks = set(), set()
    for s in syms:
        seq = end_at.get(id(s))
        prev = next((p for p in reversed(seq[:-1]) if math.dist(p, seq[-1]) > 0.5), None) if seq else None
        if degree.get(id(s)) == 1 and prev is not None:
            L = math.dist(prev, seq[-1])
            if _is_coupler(s, seq[-1], ((seq[-1][0] - prev[0]) / L, (seq[-1][1] - prev[1]) / L), prm):
                couplers.add(id(s))
            elif not end_chain[id(s)].get("pneumatic") and _is_gooseneck(
                    s, seq, any(e in curved_ids for e in end_chain[id(s)]["evidence"]), prm):
                goosenecks.add(id(s))
    # 구조 규칙이 못 정한 기호는 사전의 격자 견본에 먼저 대 본다. 사전이 연결 표시로 본 기호도 화살표 목록에 넣어야 이웃 화살표의
    # 계통 글자를 가져가지 않는다(_continuation_attributes). 버릴 기호(무늬 점)는 글자를 가져가지 않게 후보에서 뺀다
    hits = {si: _symbol_match(s, blocks) for si, s in enumerate(syms) if shape_of[si][0] in (None, "instrument")}
    drop = {si for si, h in hits.items() if h.outcome == "matched" and h.entry.role == "drop"
            and not degree.get(id(syms[si]))}
    actuators = [syms[si] for si, h in sorted(hits.items()) if h.outcome == "matched" and h.entry.role == "actuator"]
    # 사전에 통째로는 맞지 않지만 몸통만 떼면 수동 밸브이고 축 끝에 손잡이(T)가 있는 기호: 축·벨로스·화살표·글자 원이
    # 몸통과 함께 묶여 사전을 벗어난 수동 밸브다(APR1400 063쪽 V349, 062쪽 V2120, 016쪽 V402·V701)
    hand_valves = {}
    for si, sy in enumerate(syms):
        if shape_of[si][0] is None and not getattr(sy, "plate_valve", None) and not (
                si in hits and hits[si].outcome == "matched"):
            found = _valve_body_part(sy, cls)
            if found and _hand_wheel(found[0], cls, blocks, prm):
                hand_valves[id(sy)] = found
    # 밸브 축: 밸브 가운데(판 밸브는 원판 점, 그 밖은 몸통 상자 가운데)로 들어가는 선. 배관은 몸통 양 끝에 닿는다.
    # 축 반대 끝 기호 = 구동부. 끝막음 규칙(연결 하나)에 넣지 않고, 판 밸브는 수동으로 정하지 않는다
    valve_like = {id(sy) for si, sy in enumerate(syms) if getattr(sy, "plate_valve", None)
                  or rules.KIND_CATEGORY.get(shape_of[si][0]) == "valve" or id(sy) in hand_valves
                  or (si in hits and hits[si].outcome == "matched" and hits[si].entry.role == "symbol"
                      and rules.KIND_CATEGORY.get(hits[si].entry.kind) == "valve")}

    def at_stem(v, pt):
        if getattr(v, "plate_valve", None):
            c, lim = v.plate_center, prm["plate_touch_tol"] + 1.0
        else:
            c, lim = _center(v.core), 0.25 * max(_w(v.core), _h(v.core))
        return math.hypot(pt[0] - c[0], pt[1] - c[1]) <= lim
    # 검정 견본으로 올린 밸브 몸통(검게 칠한 닫힌 밸브)은 묶인 기호 전체가 사전에 없을 수 있다. 축 위 구동부 묶음을 볼 때만
    # 밸브로 넣는다(seed_stem_of). 그 밖의 합치기·끝막음 판정은 그대로 둔다
    seed_valves = {id(sy) for si, sy in enumerate(syms) if sy.seed is not None and id(sy) not in valve_like
                   and rules.KIND_CATEGORY.get(cls["seeds"][sy.seed].entry.kind) == "valve"
                   and not (si in hits and hits[si].outcome == "matched")}
    stem_of, straight_stem_of, seed_stem_of = {}, {}, {}  # 구동부 기호 id → 밸브 기호(합치기는 꺾이지 않은 축만 쓴다)
    for ch in chains:
        if ch.get("dashed") or any(v[0] != "sym" for v, _, _ in ch["ends"]):
            continue
        (va, pa, _), (vb, pb, _) = ch["ends"]
        straight = len({(round(q[0], 2), round(q[1], 2)) for q in ch["pts"]}) == 2
        for (v, pt), (x, _) in (((va[1], pa), (vb[1], pb)), ((vb[1], pb), (va[1], pa))):
            if x is v or id(x) in valve_like or id(x) in seed_valves or not at_stem(v, pt):
                continue
            if id(v) in valve_like:
                stem_of.setdefault(id(x), []).append(v)
                if straight:
                    straight_stem_of.setdefault(id(x), []).append(v)
            elif id(v) in seed_valves and straight:
                seed_stem_of.setdefault(id(x), []).append(v)
    on_valve = set(stem_of)
    # 실선 배관이 몸체 한가운데를 지나가는 작은 기호는 배관 위 부품이지 끝막음이 아니다
    solid = [(_bbox_pts(ch["pts"]), ch) for ch in chains if not ch.get("dashed")]
    for sy in syms:
        if max(_w(sy.bbox), _h(sy.bbox)) <= prm["pipe_cap_max"] and _w(sy.core) > 1 and _h(sy.core) > 1:
            inner = _expand(sy.core, -0.5)
            if any(_box_gap(cb, inner) <= 0 and _poly_box_dist(ch["pts"], inner) == 0.0
                   and all(v[0] != "sym" or v[1] is not sy for v, _, _ in ch["ends"]) for cb, ch in solid):
                on_valve.add(id(sy))
    # 검정 견본으로 올린 몸통(seed)에 맞닿은 기호(밸브에 붙여 그린 축소관 등)는 그 몸통에 이어진 것이지 끝막음이 아니다
    seeded = [sy for sy in syms if sy.seed is not None]
    on_valve |= {id(sy) for sy in syms if sy.seed is None
                 and any(_box_gap(sy.bbox, v.bbox) <= prm["touch_tol"] for v in seeded)}
    stemmed = {id(v) for vs in stem_of.values() for v in vs}
    # S5 계획: 사전 구동부를 꺾이지 않은 축으로 이어진(축이 없으면 닿은) 밸브 하나에 합칠 후보로 둔다(D6). 실제로 합칠지는
    # 노드 kind가 정해진 뒤 정한다(아래 _apply_merges). 밸브가 없거나 둘 이상이면 후보가 아니다
    plan_into, acts_on = {}, {}
    for si, h in sorted(hits.items()):
        if h.outcome != "matched" or h.entry.role != "actuator":
            continue
        a = syms[si]
        cands = {id(v): v for v in straight_stem_of.get(id(a), [])} or {
            id(v): v for v in syms if id(v) in valve_like and _box_gap(a.bbox, v.bbox) <= prm["attach_tol"]}
        if len(cands) == 1:
            v = next(iter(cands.values()))
            plan_into[id(a)] = v
            acts_on.setdefault(id(v), []).append((a, h.entry))
    # 축 위에 쌓은 구동부 묶음(_operator_stacks)이 범례가 정한 구동 방식이면 묶음 조각 전부를 그 밸브에 합칠 후보로 바꿔 둔다
    index = {id(s): si for si, s in enumerate(syms)}
    stack_stems = {k: straight_stem_of.get(k, []) + seed_stem_of.get(k, []) for k in set(straight_stem_of) | set(seed_stem_of)}
    for vid, (v, members) in _operator_stacks(syms, chains, valve_like | seed_valves, stack_stems, shape_of, hits,
                                              prm).items():
        if any(plan_into.get(id(m), v) is not v for m in members):
            continue
        decided = _stack_entry(members, [hits.get(index[id(m)]) for m in members], blocks, chains)
        if decided:
            plan_into.update((id(m), v) for m in members)
            acts_on[vid] = [(m, decided) for m in members]
    cand = []
    is_size = [(parse_label(b["text"]) or ("",))[0] == "size" for b in blocks]
    is_position = [bool(POSITION_TEXT_RE.fullmatch(" ".join(b["text"].split()))) for b in blocks]
    valve_syms = [v for v in syms if id(v) in valve_like]
    valve_piece = {si for si, s in enumerate(syms) if id(plan_into.get(id(s), s)) not in valve_like
                   and any(_box_gap(s.bbox, v.bbox) <= prm["attach_tol"] for v in valve_syms)}
    # 사전으로 맞춘 연결 표시(세로로 세운 순서 문자 깃발 등)는 상자 안의 돌린 글자를 제 글자로 받는다(APR1400 015쪽 깃발 안 'B')
    library_arrow = {si for si, h in hits.items() if h.outcome == "matched" and h.entry.role == "continuation"}
    for bi, b in enumerate(blocks):
        if bi in roles:
            continue
        for si, s in enumerate(syms):
            if si in drop:
                continue
            if b.get("rotated") and shape_of[si][0] not in ("instrument", "continuation") and not (
                    si in library_arrow and _inside(_center(b["bbox"]), s.bbox)):
                continue  # 돌린 글자는 대개 행선지·위치 설명이라 다른 기호의 종류를 정하는 글자로 쓰지 않는다
            inside = _inside(_center(b["bbox"]), s.bbox)
            if not inside and is_size[bi]:
                continue  # 구경 글자('¾"')는 기호 이름이 아니라 배관 속성이다(attach_line_labels가 배관에 붙인다)
            if not inside and is_position[bi] and si in valve_piece:
                continue  # 위치 약어('LC,FC')는 밸브 속성이다. 밸브 몸통에 붙은 미분류 조각이 가져가면 밸브가 잃는다(012쪽 419)
            gap = -1.0 if inside else _box_gap(b["bbox"], s.bbox)
            if gap <= prm["label_gap_max"]:
                # 글자가 여러 기호 상자 안에 들면 가장 작은 기호의 글자다. 건물 경계처럼 큰 상자가 먼저 가져가면 그 안
                # 밸브 번호 원이 제 번호를 잃는다(APR1400 105쪽 주증기 안전밸브 '1304')
                cand.append((round(gap, 6), bi, _w(s.bbox) * _h(s.bbox) if inside else 0.0, si))
    # 큰 기호 상자 안에 제 글자(더 작은 기호 상자에 들지 않은 글자)가 있으면, 안쪽 작은 기호 상자의 글자는 그 큰 기호의
    # 라벨이 되지 않는다. 장비 외곽에 걸쳐 그린 계기 비석의 아랫줄(046쪽 VET 비석의 IAH)이 압축기 이름 'AIR COMPRESSOR 01'을
    # 밀어내던 자리. 제 글자가 없는 큰 기호(076쪽 공조기 칸 상자: 안의 글자는 코일 판의 CC·CW뿐)는 예전대로 둔다. 그렇게
    # 막으면 상자가 바깥 이름 글자를 가져가 안쪽 송풍기의 (틀린) 종류를 넘겨받는다
    smallest = {}
    for gap, bi, area, si in cand:
        if gap < 0:
            smallest[bi] = min(area, smallest.get(bi, area))
    owns = {si for gap, bi, area, si in cand if gap < 0 and area <= smallest[bi]}
    cand = [c for c in cand if c[0] >= 0 or c[2] <= smallest[c[1]] or c[3] not in owns]
    arrows = [s for si, s in enumerate(syms) if shape_of[si][0] == "continuation" or
              (si in hits and hits[si].outcome == "matched" and hits[si].entry.role == "continuation")]
    label_of, taken = {}, set()
    for gap, bi, _, si in sorted(cand):
        if si in label_of or bi in taken:
            continue
        label_of[si] = bi
        taken.add(bi)
    _join_bubble_number(syms, blocks, label_of, taken, roles)
    # S5: 밸브 번호 원(원 안 숫자뿐)은 지시선 하나의 반대 끝이 밸브에 닿거나, 가장 가까운 밸브가 number_reach 안이고
    # 두 번째 밸브가 그 두 배보다 멀 때만 그 밸브에 합친다(기획서/PID-기호사전.md §4.2 4번). 숫자만으로는 계통 접두를
    # 알 수 없어 태그는 만들지 않고 근거(ident_number)로만 남긴다
    leaders = collections.defaultdict(list)
    for ch in chains:
        if ch.get("dashed"):
            continue
        for k in (0, 1):
            v = ch["ends"][k][0]
            if v[0] == "sym":
                leaders[id(v[1])].append((ch, ch["ends"][1 - k]))
    valves = [sy for sy in syms if id(sy) in valve_like]
    numbers_on = {}  # 밸브 id → [(번호 원, 숫자)]
    for si, sy in enumerate(syms):
        bi = label_of.get(si)
        if shape_of[si][0] != "instrument" or bi is None or id(sy) in plan_into or len(leaders[id(sy)]) != 1:
            continue
        if not (VALVE_NUMBER_RE.fullmatch(blocks[bi]["text"].strip()) and _inside(_center(blocks[bi]["bbox"]), sy.bbox)):
            continue
        ch, (far, pt, _) = leaders[id(sy)][0]
        target = None
        if far[0] == "sym":
            hit_sym = plan_into.get(id(far[1]), far[1])  # 지시선이 합칠 구동부에 닿았으면 그 밸브
            target = hit_sym if id(hit_sym) in valve_like else None
        elif far[0] == "free":  # 분기점·통과점에 닿은 선은 지시선이 아니다
            near = sorted((_pt_box_dist(pt, v.bbox), k) for k, v in enumerate(valves))
            if near and near[0][0] <= prm["number_reach"] and (len(near) == 1 or near[1][0] > 2 * near[0][0]):
                target = valves[near[0][1]]
        if target is not None:
            numbers_on.setdefault(id(target), []).append((sy, blocks[bi]["text"].strip()))
    # 번호 원(범례 1.7-1 1/4 VALVE IDENT. NUMBER) 안 숫자가 원이 아니라 밸브의 라벨로 잡힌 자리. 원이 밸브 몸통에 닿아 한
    # 기호로 묶였으면(008쪽 방출 밸브 200~203) 그 원이 이 밸브의 번호다. 원이 따로면(063쪽 302·354·524, 원에 'N' 표가 붙어
    # 계기 원 모양이 아님) 원에서 나온 지시선 하나가 이 밸브에 닿을 때만 이 밸브의 번호다. 이웃 밸브의 번호를 받지 않는다
    for si, sy in enumerate(syms):
        bi = label_of.get(si)
        if bi is None or id(sy) in numbers_on or not VALVE_NUMBER_RE.fullmatch(blocks[bi]["text"].strip()):
            continue
        mid = _center(blocks[bi]["bbox"])
        rings = [(ci, c) for ci, c in enumerate(syms) if ci not in drop and any(
                 _is_circle(b, prm) and _pt_circle_dist(mid, b) == 0 for b in c.bodies)]
        if len(rings) != 1:
            continue
        ci, c = rings[0]
        if c is sy:
            if shape_of[si][0] == "instrument":  # 원 하나뿐인 기호(계기 원·번호 원 자체)는 S5 위 규칙의 몫이다
                continue
        else:
            own = label_of.get(ci)
            if id(c) in plan_into or len(leaders[id(c)]) != 1 or (own is not None and re.search(r"\d", blocks[own]["text"])):
                continue
            far = leaders[id(c)][0][1][0]
            if far[0] != "sym" or plan_into.get(id(far[1]), far[1]) is not sy:
                continue
        numbers_on.setdefault(id(sy), []).append((c, blocks[bi]["text"].strip()))

    letter_boxes = _letter_boxes(syms, chains, blocks, label_of, {si for si, h in hits.items() if shape_of[si][0] is None
                                                                  and h.outcome != "matched"}, prm)
    boxes_on, box_ids = {}, {id(b) for b, _, _ in letter_boxes}
    for box, v, letter in letter_boxes:
        if id(v) not in box_ids and id(v) not in plan_into:
            boxes_on.setdefault(id(v), []).append((box, letter))
    # 검정 견본에 맞은 밸브 몸통은 묶인 기호 전체가 사전에 없어 종류를 못 정해도(벨로스가 붙은 몸통 등) 밸브다. 옆 밸브
    # 번호는 이 몸통 몫이다(APR1400 063쪽 V359·V361·V2081, 062쪽 V2120). 구동부 합치기는 바꾸지 않게 번호 고르기에만 넣는다
    body_valves = {id(sy) for si, sy in enumerate(syms) if sy.seed is not None
                   and rules.KIND_CATEGORY.get(cls["seeds"][sy.seed].entry.kind) == "valve"
                   and not (si in hits and hits[si].outcome == "matched")}
    positions, numbered = _valve_labels(syms, blocks, roles, valve_like | body_valves, plan_into, label_of, taken, marks,
                                        drop, prm, set(numbers_on))
    node_out, locations, local_of, instrument_ids, dropped, label_lines = [], [], {}, set(), [], {}
    noise = _noise_symbols(syms, degree, label_of, prm)
    class_marks = {}
    for n, s in enumerate(syms, 1):
        local_id = "local-node-%03d" % n
        sid = "pdf-p%d-sym-%04d" % (page, n)
        local_of[id(s)] = (local_id, sid)
        if id(s) in noise:
            dropped.append({"source_object_id": sid, "label_text": "", "bbox": _box_out(s.bbox), "reason": noise[id(s)]})
            continue
        bi = label_of.get(n - 1)
        text = blocks[bi]["text"] if bi is not None else ""
        if bi is not None:
            label_lines[local_id] = list(zip(text.split("\n"), blocks[bi]["line_boxes"]))
        kind, basis = _classify(s, text, 0 if id(s) in on_valve else degree.get(id(s), 0), prm, marks.get(n - 1, []))
        if basis == "lines+marker" and any(WORD_INSIDE_RE.search(b["text"]) and _inside(_center(b["bbox"]), s.bbox)
                                           for b in blocks):
            # '선과 표식' 체크밸브 모양 안에 낱말이 들어 있으면 체크밸브가 아니다. 건물 경계 표시('AB ▶|◀ YARD', 128쪽)는
            # 화살촉 둘과 칸막이 선으로 그려 같은 구조로 읽혔다
            kind, basis = None, None
        if id(s) in couplers:  # 괄호 모양이 종류를 정한다. 옆 글자(FILL 등)로 정하지 않는다
            kind, basis = "hose_connection", COUPLER_BASIS
        elif id(s) in goosenecks:
            kind, basis = "vent", GOOSENECK_BASIS
        mark_lines = ["".join(m.partition("\n")[0].split()) for m in marks.get(n - 1, [])]
        class_mark = basis == "valve_body" and any(SAFETY_CLASS_RE.fullmatch(t) for t in mark_lines + ["".join(mark_lines)])
        if class_mark:
            # 안전등급 경계 마름모는 공정 기호가 아니다. 노드로 두지 않고, 닿은 선은 아래에서 경계 표시로 정리한다
            class_marks[id(s)] = "|".join(t for t in mark_lines if t) or "".join(mark_lines)
            dropped.append({"source_object_id": sid, "label_text": class_marks[id(s)], "bbox": _box_out(s.bbox),
                            "reason": SAFETY_CLASS_BASIS})
            continue
        symbol_id, symbol_attrs = None, {}
        valve_body = False  # 몸통이 밸브인 것은 알지만 종류를 정하지 못함
        if getattr(s, "plate_valve", None):
            symbol_attrs = {"valve_type": s.plate_valve}
            if id(s) in stemmed or any(_box_gap(a.bbox, s.bbox) <= prm["attach_tol"] for a in actuators):
                kind, valve_body = None, True  # 사전 몸통과 같이, 구동부가 붙은 몸통은 구동 방식을 정하기 전까지 수동으로 두지 않는다
                _issue(unknowns, "actuated_valve_pending", "구동부 기호가 붙은 밸브 몸통: 구동 방식은 아직 정하지 않음",
                       sid, local_id, "kind")
        if basis == SPRING_BASIS:  # 사전 견본(앵글 방출 밸브 등)이 같은 종류로 맞으면 그 항목을 근거로 둔다
            hit = _symbol_match(s, blocks)
            if hit.outcome == "matched" and hit.entry.role == "symbol" and hit.entry.kind == kind:
                symbol_id, basis = hit.entry.id, "symbol:%s" % hit.entry.id
                symbol_attrs = {k: v for k, v in sorted(hit.attributes.items()) if k in rules.REGISTRY.properties}
        fallback = basis == PIPE_CAP_BASIS  # 끝막음은 형상 규칙이 아니라 뒤처리 규칙: 사전에 후보가 없을 때만 남긴다(§4.2 5번)
        if (kind is None or fallback) and not getattr(s, "plate_valve", None) and not class_mark:  # 구조·글자 규칙이 못 정한 기호만 사전의 격자 견본에 대 본다(기획서/PID-기호사전.md §4.2)
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
                    kind, isa_basis = _instrument_kind(text, min(_w(s.bbox), _h(s.bbox)))
                    basis = "%s+%s" % (basis, isa_basis) if kind else basis
                    instrument_ids.add(local_id)
                elif entry.role in ("symbol", "continuation"):
                    kind = entry.kind
                    symbol_attrs = {k: v for k, v in sorted(hit.attributes.items()) if k in rules.REGISTRY.properties}
                    reach = ACTUATOR_REACH_RATIO * max(_w(s.bbox), _h(s.bbox))
                    # 곧은 축으로 다른 밸브에 이어진 구동부는 그 밸브 것이다(APR1400 128쪽 MOV 009 옆 수동 밸브).
                    # 어느 밸브에도 이어지지 않은 구동부가 몸통의 축 자리(몸통 가운데에서 배관과 수직인 줄)를 벗어나 있으면
                    # 이웃 밸브의 것이다. 축에 무엇이 붙은 몸통(stemmed: 박막 머리 등 사전에 없는 구동부)은 그대로 보류한다
                    if kind == "manual_valve" and any(
                            _box_gap(a.bbox, s.bbox) <= reach and plan_into.get(id(a), s) is s
                            and (id(a) in plan_into or id(s) in stemmed or _on_stem_line(a, s, prm)) for a in actuators):
                        kind, valve_body = None, True  # 몸통만으로는 수동인지 모른다. 구동부를 밸브에 합치는 단계(S5) 전에는 정하지 않는다
                        _issue(unknowns, "actuated_valve_pending", "구동부 기호가 붙은 밸브 몸통: 구동 방식은 아직 정하지 않음",
                               sid, local_id, "kind")
            elif hit.outcome == "ambiguous":
                _issue(unknowns, "ambiguous_symbol", "기호 사전 후보가 둘 이상이라 정하지 않음: %s"
                       % ", ".join(c for c, _ in hit.candidates[:3]), sid, local_id, "kind")
        seed = analysis["classified"].get("seeds", {}).get(s.seed)
        if id(s) in hand_valves and kind is None and symbol_id is None and not class_mark and not any(
                _box_gap(a.bbox, s.bbox) <= ACTUATOR_REACH_RATIO * max(_w(s.core), _h(s.core))
                and plan_into.get(id(a), s) is s and (id(a) in plan_into or _on_stem_line(a, hand_valves[id(s)][0], prm))
                for a in actuators):
            entry = hand_valves[id(s)][1]
            kind, basis = entry.kind, "%s:%s+hand_actuator" % ("black_body" if seed is not None else "valve_body", entry.id)
            symbol_attrs = {k: v for k, v in sorted(entry.attributes.items()) if k in rules.REGISTRY.properties}
            if seed is not None:
                symbol_attrs.update((k, v) for k, v in seed.attributes.items() if k == "normal_position")
        if seed is not None and kind is None and symbol_id is None and not class_mark:
            # 몸통은 검정 견본에 맞았지만 묶인 기호 전체는 사전에 없다(벨로스 같은 다른 선이 몸통에 붙음). 종류는 비워 두고
            # 검게 칠한 몸통이 뜻하는 정상 위치만 남긴다
            symbol_attrs = {k: v for k, v in sorted(seed.attributes.items()) if k == "normal_position"}
            basis, valve_body = "black_body:%s" % seed.entry.id, True
        if rules.KIND_CATEGORY.get(kind) == "instrument" or (kind is None and shape_of[n - 1][0] == "instrument"):
            instrument_ids.add(local_id)  # 측정 연결 판정: 계기로 분류됐거나 원형이고 다른 종류 근거가 없는 기호
        category = rules.KIND_CATEGORY.get(kind)
        classification = "classified" if category else "unclassified"
        if kind is None and valve_body:
            # 종류는 못 정했어도 분류는 밸브다. 경로 분석과 검토구간 나누기는 분류로 밸브를 가리므로, 분류까지 비우면 닫힌
            # 밸브가 있는 길을 정상 유로로 읽는다. 종류 없음 미확인은 그대로 남긴다
            category = "valve"
        if kind is None and not class_mark:
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
    merge_into, number_ids = _apply_merges(syms, node_out, locations, unknowns, dropped, instrument_ids, local_of, chains,
                               acts_on, numbers_on, boxes_on)
    _apply_positions(syms, node_out, unknowns, local_of, positions, blocks)
    _assign_tags(node_out, unknowns, instrument_ids, {local_of[id(syms[si])][0] for si in numbered}, label_lines)
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
        if v[0] == "sym" and (id(v[1]) in noise or id(v[1]) in class_marks):
            return None
        if v[0] == "sym":
            return local_of[id(merge_into.get(id(v[1]), v[1]))]  # 합친 구동부에 닿은 선(신호선 등)은 밸브로
        if v[0] == "tee":
            return tee_ids[v[1]]
        return None

    chains, marked_ends = _class_mark_lines(chains, class_marks, dropped,
                                            [o for o in syms if id(o) not in class_marks and id(o) not in noise])
    by_local_id = {nd["local_id"]: nd for nd in node_out}
    for v, text in marked_ends:  # 지시선이 가리킨 기호·분기점에 등급 경계 글자를 근거로 남긴다
        r = ref(v)
        if r and r[0] in by_local_id:
            marks_here = by_local_id[r[0]]["evidence"].setdefault(SAFETY_CLASS_BASIS, [])
            if text not in marks_here:
                marks_here.append(text)
    ordered = sorted(chains, key=lambda c: (bool(c.get("dashed")), c["evidence"][0]))
    relations, unresolved = [], []
    node_by_local = {nd["local_id"]: nd for nd in node_out}
    for n, ch in enumerate(ordered, 1):
        local_id, sid = "local-edge-%03d" % n, "pdf-p%d-conn-%04d" % (page, n)
        why = _merged_line(ch, merge_into, number_ids)
        if why:
            dropped.append({"source_object_id": sid, "label_text": "", "bbox": _box_out(_bbox_pts(ch["pts"])),
                            "reason": why})
            continue  # 구동부 축·번호 원 지시선: 합친 밸브 안의 선이다(관계 번호는 비워 둔다)
        # 합친 구동부로 들어가던 선은 구동 신호로 본다. 글자 상자로 들어가던 선(P 상자의 파일럿 배관)은 제 선 종류를 지킨다
        moved = any(v[0] == "sym" and id(v[1]) in merge_into and id(v[1]) not in box_ids for v, _, _ in ch["ends"])
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
        if ch.get("dashed") and resolved and not moved and _dashed_pipe(ch, node_by_local, ids, instrument_ids, prm):
            rel_kind, line_type = "physical_connection", "pdf_dashed"
        elif ch.get("dashed"):
            rel_kind, line_type = "signal_connection", "pdf_dashed"
        elif moved:  # 합친 구동부로 들어가던 선은 구동 신호다(배관 분기로 보지 않는다)
            rel_kind, line_type = "signal_connection", "pdf_solid"
        elif ch.get("pneumatic"):
            rel_kind, line_type = "signal_connection", "pdf_pneumatic"
        elif any(i in instrument_ids for i in ids if i):
            rel_kind, line_type = "measurement_connection", "pdf_solid"
        else:
            rel_kind, line_type = "physical_connection", "pdf_solid"
        if ch.get("contact") and line_type == "pdf_solid":
            line_type = "pdf_touching"  # 선 없이 맞닿은 두 기호(_contact_chains)
        flow = None
        sense, flow_basis = ch.get("flow"), "pdf_arrowhead"
        if rel_kind in rules.RELATION_KINDS_WITH_FLOW and resolved and not sense:
            sense, flow_basis = _continuation_sense(ch, ids, node_by_local), "continuation_arrow"
        if rel_kind in rules.RELATION_KINDS_WITH_FLOW and resolved and sense:
            a, b = (ids[0], ids[1]) if sense > 0 else (ids[1], ids[0])
            ends = {ids[0]: "source", ids[1]: "target"}
            flow = {"from": a, "to": b, "from_end": ends[a], "to_end": ends[b], "basis": flow_basis}
        elif rel_kind in rules.RELATION_KINDS_WITH_FLOW:
            _issue(unknowns, "unknown_flow_direction", "PDF 선에서 흐름 방향을 정하지 않음", sid, local_id,
                   "flow_direction")
        record = {
            "local_id": local_id, "source_object_id": sid, "kind": rel_kind, "line_type": line_type,
            "line_no": None, "endpoints": endpoints, "flow_direction": flow,
            "waypoints": [[_num(p[0]), _num(p[1])] for p in ch["pts"][1:-1]] if not ch.get("dashed") else [],
            "label": "", "label_text": "", "label_cells": [], "attributes": {}, "style": None, "parent": None,
            "geometry": None,
            "evidence": {"classification_basis": ("dash_chain" if ch.get("dashed") else
                                                  "touching_bodies" if ch.get("contact") else "solid_path"),
                         "pdf_objects": list(ch["evidence"]),
                         # 선이 지나는 실제 점(양 끝 포함, 점선은 조각 중심). ② 배경 SVG의 관계 경로로 그린다
                         "pdf_path": [[_num(p[0]), _num(p[1])] for p in ch["pts"]]},
        }
        (relations if resolved else unresolved).append(record)
        pts = ch["pts"] + [tuple(e["point"]) for e in endpoints]
        locations.append({"object_id": sid, "local_id": local_id, "coordinate_space": COORDINATE_SPACE,
                          "unit": UNIT, "bbox": _box_out(_bbox_pts(pts)), "approximate": True,
                          "method": "pdf_path_points"})
    # 같은 쪽 순서 문자 깃발 짝은 그려진 선이 없어도 한 배관이다. 깃발 가운데끼리 잇는 물리 관계로 둔다
    for k, (a, b) in enumerate(same_sheet_letter_pairs(node_out, relations + unresolved), len(ordered) + 1):
        local_id, sid = "local-edge-%03d" % k, "pdf-p%d-conn-%04d" % (page, k)
        ends = [(a, "source"), (b, "target")]
        centers = [(g["x"] + g["width"] / 2, g["y"] + g["height"] / 2) for g in (node_by_local[i]["geometry"] for i, _ in ends)]
        relations.append({
            "local_id": local_id, "source_object_id": sid, "kind": "physical_connection",
            "line_type": "pdf_sequence_letter", "line_no": None,
            "endpoints": [{"end": end, "node_local_id": i, "source_object_id": node_by_local[i]["source_object_id"],
                           "constraint": None, "point": [_num(c[0]), _num(c[1])], "point_basis": "sequence_letter_pair",
                           "status": "connected", "port": None} for (i, end), c in zip(ends, centers)],
            "flow_direction": None, "waypoints": [], "label": "", "label_text": "", "label_cells": [], "attributes": {},
            "style": None, "parent": None, "geometry": None,
            "evidence": {"classification_basis": "sequence_letter_pair", "pdf_objects": [],
                         "pdf_path": [[_num(c[0]), _num(c[1])] for c in centers]},
        })
        _issue(unknowns, "unknown_flow_direction", "PDF 선에서 흐름 방향을 정하지 않음", sid, local_id, "flow_direction")
        locations.append({"object_id": sid, "local_id": local_id, "coordinate_space": COORDINATE_SPACE,
                          "unit": UNIT, "bbox": _box_out(_bbox_pts(centers)), "approximate": True,
                          "method": "sequence_letter_pair"})
    # 기호가 그린 방향(공기 흐름 화살표·체크 밸브 경첩)을 먼저 매기고, 흐름 보존으로 넓힌다(2포트 배관 기호·분기점·
    # 공조기 칸·배관이 꿰고 지나가는 미분류 노드). 정한 관계는 방향 미확인에서 뺀다
    before = {r["local_id"] for r in relations if r.get("flow_direction")}
    passes = {local_of[id(s)][0] for s in syms if s.housing} | _inline_unclassified(relations, node_out)
    kind_of = {n["local_id"]: n.get("kind") for n in node_out}
    seeded = _end_symbol_flows(relations, {local_of[id(s)][0]: s for s in syms if id(s) in local_of}, kind_of)
    # 배관이 꿰고 지나가는 계기(유량계 상자)로 가는 측정선은 분기점에서 보면 배관 가지다. 계기 원으로 가는 탭 하나는
    # 흐름이 없으니 가지로 세지 않는다
    meas = [r for r in relations if r["kind"] == "measurement_connection" and r["line_type"] == "pdf_solid"]
    through = _through_instruments(meas, {n["local_id"]: n for n in node_out if n["local_id"] in instrument_ids})
    side = {e["node_local_id"] for r in meas if through & {e["node_local_id"] for e in r["endpoints"]}
            for e in r["endpoints"]}
    if _propagate_flows(relations, kind_of, passes, side) + seeded:
        _revert_contradictions(relations, kind_of, passes, side)
        filled = {r["local_id"] for r in relations if r.get("flow_direction")} - before
        unknowns[:] = [u for u in unknowns if not (u.get("check") == "unknown_flow_direction" and u.get("target") in filled)]
    # 배관 글자(구경·배관 번호)를 가장 가까운 물리 배관 속성으로(pdf_vector_lines). 붙인 글자는 남은 글자 목록에서 뺀다
    taken |= attach_line_labels(blocks, [bi for bi in range(len(blocks)) if bi not in taken
                                         and roles.get(bi) not in ("title_block", "symbol_mark")], relations + unresolved)
    attach_continuation_line_numbers(node_out, relations + unresolved)
    _flow_elements(node_out, relations, unknowns)

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
        for o in cls.get("ticks", [])] + [
        {"source_object_id": o["id"], "label_text": "", "bbox": _box_out(o["bbox"]), "reason": "line_dot"}
        for o in cls.get("dots", [])] + [
        {"source_object_id": o["id"], "label_text": "", "bbox": _box_out(o["bbox"]), "reason": "flange_plate"}
        for o in cls.get("flanges", [])]
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


def _flow_elements(nodes, relations, unknowns):
    """배관 위 요소 가운데 FE 계기 원과 측정선으로 이어진 것을 유량 요소(flow_element)로 정한다(범례 1.7-1 2/4 FE).
    요소는 배관 두 쪽에 물리 연결이 있고 종류가 없거나 오리피스 판으로 읽힌 기호다. FE 원 자체는 계기로 두고(검토구간
    나누기는 원을 계기로 본다), 요소의 태그는 비워 둔다. FE 원이 둘 이상이거나 요소가 이미 다른 종류면 정하지 않는다.
    025쪽 차압 탭이 달린 유량 요소 상자(FE 003·047·049·071), 097쪽 FE 031 아래 오리피스 판."""
    by_id = {n["local_id"]: n for n in nodes}
    pipes, fe = collections.Counter(), collections.defaultdict(set)
    for r in relations:
        ids = [e["node_local_id"] for e in r["endpoints"]]
        if r["kind"] == "physical_connection":
            for i in ids:
                pipes[i] += 1
        elif r["kind"] == "measurement_connection":
            for i, j in (ids, ids[::-1]):
                lines = by_id[j]["label_text"].split()
                if lines and lines[0] == "FE" and by_id[j]["category"] in (None, "instrument"):
                    fe[i].add(j)
    for n in nodes:
        bubbles = fe.get(n["local_id"], ())
        if len(bubbles) != 1 or pipes[n["local_id"]] < 2 or n["kind"] not in (None, "orifice") or \
                n["category"] not in (None, rules.KIND_CATEGORY["orifice"]):
            continue
        bubble = by_id[next(iter(bubbles))]
        n.update(kind="flow_element", category=rules.KIND_CATEGORY["flow_element"], classification="classified")
        n["evidence"]["classification_basis"] = "fe_bubble_measurement+%s" % (n["evidence"]["classification_basis"] or "pipe_element")
        unknowns[:] = [u for u in unknowns if not (u["target"] == n["local_id"] and u["check"] == "missing_kind")]
        # 태그는 식별자라 같은 쪽에서 요소와 FE 원이 같은 값을 갖지 않게 한다. 원 번호는 근거에만 남긴다(총괄 판정 2026-11-16)
        n["evidence"]["fe_bubble"] = bubble["local_id"]
        if bubble.get("tag"):
            n["evidence"]["fe_bubble_tag"] = bubble["tag"]


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
