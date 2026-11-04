"""draw.io 샘플 작성 규칙(초안)의 기계 판독용 표.

근거: 기획서/정보추출.md '샘플 작성 규칙 (초안)', 기획서/정보통합관리.md #node-unit.
규칙이 바뀌면 RULES_VERSION을 올린다.
"""

RULES_VERSION = "drawio-rules-draft-2026-11-03"

# kind -> category. 표시 필터(심볼·배관 등)와 미분류 판정에 쓴다.
KIND_CATEGORY = {}
for _k in ("reactor_vessel", "steam_generator", "pressurizer", "pump", "vessel", "tank",
           "heat_exchanger", "turbine", "condenser", "filter", "demineralizer", "orifice", "vent"):
    KIND_CATEGORY[_k] = "equipment"
for _k in ("manual_valve", "motor_operated_valve", "control_valve", "check_valve",
           "isolation_valve", "psv"):
    KIND_CATEGORY[_k] = "valve"
for _k in ("transmitter", "controller", "indicator", "temperature_element"):
    KIND_CATEGORY[_k] = "instrument"
for _k in ("tee", "pipe_cap", "continuation"):
    KIND_CATEGORY[_k] = "piping_element"

# 태그가 없어도 규칙 위반이 아닌 kind (continuation은 tag 없이 to_drawing·to_object 보유)
KINDS_WITHOUT_TAG = {"continuation"}

# normal_position을 기대하는 밸브. check_valve는 정상 위치 개념이 없어 제외 [가정]
KINDS_NEED_NORMAL_POSITION = {"manual_valve", "motor_operated_valve", "control_valve",
                              "isolation_valve", "psv"}
NORMAL_POSITION_VALUES = {"NO", "NC", "LO", "LC"}
# 제어밸브만 fail_position 누락을 미확인으로 본다 ('해당 없으면 비움')
KINDS_NEED_FAIL_POSITION = {"control_valve"}

# line_type -> 관계 종류. 그래프 표현(구간 노드 여부)은 ③에서 정한다.
LINE_TYPE_RELATION = {
    "process": "physical_connection",
    "process_secondary": "physical_connection",
    "signal": "signal_connection",
    "signal_electric": "signal_connection",
    "instrument_tap": "measurement_connection",
}
# 흐름 방향 미확인을 검사하는 관계 종류 (물질 흐름이 있는 배관만)
RELATION_KINDS_WITH_FLOW = {"physical_connection"}
FLOW_DIRECTION_VALUES = {"source_to_target"}

# 표제란 키 -> drawing 메타데이터 필드
TITLE_BLOCK_FIELDS = {"DWG NO.": "drawing_number", "TITLE": "title", "REV.": "revision",
                      "NOTE": "note"}
