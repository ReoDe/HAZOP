"""④ 원인·전제·보호수단으로 쓸 수 있는 '실제 기기' 종류 (한 곳에서 정의).

근거: 사용자 결정(2026-11-04) '도면에 있는 설비만'. 종류 분류는 ② 작성 규칙(hazop/extract/rules.py KIND_CATEGORY,
타입 레지스트리)을 따른다.
- 허용: 연결 요소가 아닌 분류(설비·밸브·배관 부품·계기 기능)의 kind. 배관 부품(오리피스·벤트 등)은 2026-11-08 설비에서
  나뉘었으나(사전 §2.1, U9) 막힘·누설 원인이 되는 실제 부품이라 그대로 허용한다
- 불가: 연결 요소(tee·pipe_cap·continuation·nozzle = piping_element)와 배관 구간(pipe_segment).
  continuation은 다른 도면으로 이어지는 연결점이므로, 이를 전제하는 것은 도면 밖 설비를 전제하는 것으로 본다.
"""

from hazop.extract.rules import KIND_CATEGORY
from hazop.kg.schema import REGISTRY

CONNECTION_CATEGORIES = ("piping_element", "pipe_segment")
EQUIPMENT_CATEGORIES = tuple(c for c in REGISTRY.pid_categories() if c not in CONNECTION_CATEGORIES + ("unclassified",))
EQUIPMENT_KINDS = frozenset(k for k, c in KIND_CATEGORY.items() if c in EQUIPMENT_CATEGORIES)
CONNECTION_KINDS = frozenset(k for k, c in KIND_CATEGORY.items() if c == "piping_element") | {"pipe_segment"}


def is_equipment(node):
    return node.get("node_type") == "drawing_object" and node.get("kind") in EQUIPMENT_KINDS


def why_not_equipment(node):
    """실제 기기가 아니면 사유 문장, 기기면 None."""
    if node is None:
        return "그래프에 없음"
    if is_equipment(node):
        return None
    if node.get("kind") == "continuation":
        return "다른 도면 연결점(to_drawing %s) — 그 너머 설비는 도면 밖" % (node.get("attributes") or {}).get("to_drawing")
    if node.get("kind") in CONNECTION_KINDS:
        return "연결 요소(%s)는 기기가 아님" % node.get("kind")
    return "허용 기기 종류가 아님(%s)" % node.get("kind")


# 보호수단의 보호 동작 종류 (패턴 라이브러리 deviation_safeguards.protective_action)
#   self_acting: 자력식 보호 기기(안전밸브 등). 묶인 편차(예: 과압)에서만 보호 동작으로 인정
#   detection: 감지기(온도·압력 계기 등). 경보·트립 등 보호 동작이 그래프 속성으로 확인될 때만 인정
PROTECTIVE_ACTIONS = ("self_acting", "detection")
# 자력식 보호 기기 kind 허용 목록. self_acting 선언은 이 kind에만 유효(감지기 등은 선언만으로 인정하지 않음)
SELF_ACTING_KINDS = frozenset({"psv"})
# 감지기의 보호 동작을 확인하는 그래프 속성과 값 형식. 양(+)의 증거만 인정한다.
#   alarm_setpoint, trip_setpoint: 0이 아닌 수(int·float, bool 제외) 또는 숫자를 포함한 비어 있지 않은 문자열(예: "350 C")
#     — 빈 값·공백·"0"·"none"·"n/a"·"-"·"없음"·"미확인" 등은 확인이 아님
#   interlock: True 또는 문자열 "true"·"yes"·"y"(대소문자 무시) — False·빈 값·그 밖의 값은 확인이 아님
# 현재 샘플 도면에는 이 속성이 없으므로 감지기는 '찾음'으로 세지 않는다.
SETPOINT_ATTRIBUTES = ("alarm_setpoint", "trip_setpoint")
INTERLOCK_ATTRIBUTE = "interlock"
ACTION_ATTRIBUTES = SETPOINT_ATTRIBUTES + (INTERLOCK_ATTRIBUTE,)
_NEGATIVE_TEXT = {"", "0", "0.0", "none", "null", "n/a", "na", "-", "없음", "미확인", "false", "no", "unknown"}


def _positive_setpoint(v):
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        t = v.strip()
        return t.lower() not in _NEGATIVE_TEXT and any(ch.isdigit() for ch in t) and             any(ch.isdigit() and ch != "0" for ch in t)
    return False


def _positive_interlock(v):
    if v is True:
        return True
    return isinstance(v, str) and v.strip().lower() in ("true", "yes", "y")


def protective_action_confirmed(node, action):
    """보호 동작 확인 여부. self_acting은 자력식 kind에서만 True. 그 밖의 기기는 동작 속성에 양의 값이 있어야 True."""
    if action == "self_acting" and node.get("kind") in SELF_ACTING_KINDS:
        return True
    attrs = node.get("attributes") or {}
    return any(_positive_setpoint(attrs.get(k)) for k in SETPOINT_ATTRIBUTES) or         _positive_interlock(attrs.get(INTERLOCK_ATTRIBUTE))


def validate_library(lib):
    """패턴 라이브러리의 기기 종류가 모두 실제 기기인지 등 구조 검사. 오류 문장 목록."""
    errs = []
    for p in lib.get("patterns") or []:
        if p.get("equipment_kind") not in EQUIPMENT_KINDS:
            errs.append("패턴 %s: 기기 종류 %r는 실제 기기가 아님" % (p.get("pattern_id"), p.get("equipment_kind")))
        for k in (p.get("conditions") or {}).get("signal_chain") or []:
            if k not in EQUIPMENT_KINDS:
                errs.append("패턴 %s: 신호 사슬 종류 %r는 실제 기기가 아님" % (p.get("pattern_id"), k))
        if p.get("role") != "cause":
            errs.append("패턴 %s: role은 cause만 허용" % p.get("pattern_id"))
    for g in lib.get("deviation_safeguards") or []:
        if g.get("kind") not in EQUIPMENT_KINDS:
            errs.append("보호수단 %s: 기기 종류 %r는 실제 기기가 아님" % (g.get("safeguard_id"), g.get("kind")))
        for k in g.get("signal_chain") or []:
            if k not in EQUIPMENT_KINDS:
                errs.append("보호수단 %s: 신호 사슬 종류 %r는 실제 기기가 아님" % (g.get("safeguard_id"), k))
        if g.get("protective_action") not in PROTECTIVE_ACTIONS:
            errs.append("보호수단 %s: protective_action %r 허용값 아님" % (g.get("safeguard_id"), g.get("protective_action")))
        elif g["protective_action"] == "self_acting" and g.get("kind") not in SELF_ACTING_KINDS:
            errs.append("보호수단 %s: %r는 자력식 기기가 아님 — self_acting 선언 불가(감지기는 동작 속성으로만 확인)"
                        % (g.get("safeguard_id"), g.get("kind")))
    return errs
