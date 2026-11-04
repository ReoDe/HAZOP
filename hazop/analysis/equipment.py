"""④ 원인·전제·보호수단으로 쓸 수 있는 '실제 기기' 종류 (한 곳에서 정의).

근거: 사용자 결정(2026-11-04) '도면에 있는 설비만'. 종류 분류는 ② 작성 규칙(hazop/extract/rules.py KIND_CATEGORY)을 따른다.
- 허용: category가 equipment·valve·instrument인 kind
- 불가: 연결 요소(tee·pipe_cap·continuation = piping_element)와 배관 구간(pipe_segment).
  continuation은 다른 도면으로 이어지는 연결점이므로, 이를 전제하는 것은 도면 밖 설비를 전제하는 것으로 본다.
"""

from hazop.extract.rules import KIND_CATEGORY

EQUIPMENT_CATEGORIES = ("equipment", "valve", "instrument")
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
