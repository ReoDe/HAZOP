"""draw.io 샘플 작성 규칙(초안)의 기계 판독용 표.

근거: 기획서/정보추출.md '샘플 작성 규칙 (초안)', 기획서/정보통합관리.md #node-unit.
규칙이 바뀌면 RULES_VERSION을 올린다.
"""

from hazop.kg.schema import REGISTRY

# 2026-11-08 M2(배관 부품 분류·속성 사전 검사)에는 올리지 않았다. 이 값은 실행 ID에 들어가 결과 내용이 같은 도면까지
# graph_version을 바꾸고, 그러면 data/regions 판 고정·고정 AI 응답·mentions 기록이 모두 재확인으로 간다.
# 결과 내용이 바뀐 도면은 올리지 않아도 graph_version이 바뀐다.
RULES_VERSION = "drawio-rules-draft-2026-11-06"

# kind -> category. 표시 필터(심볼·배관 등)와 미분류 판정에 쓴다. 목록은 타입 레지스트리(hazop/kg/schema/registry.json)
KIND_CATEGORY = REGISTRY.kind_category()

# 태그가 없어도 규칙 위반이 아닌 kind (continuation은 tag 없이 to_drawing·to_object 보유)
KINDS_WITHOUT_TAG = {"continuation"}

# 정상 위치·고장 위치를 기대하는 kind와 허용값은 레지스트리 클래스 required·속성 사전(기획서/지식그래프-스키마-사전.md §2.1).
# check_valve는 정상 위치 누락 검사에서 제외(정상 위치가 있는 체크밸브도 있을 수 있음). 검사는 hazop.extract.properties
KINDS_NEED_NORMAL_POSITION = REGISTRY.kinds_requiring("normal_position")
NORMAL_POSITION_VALUES = set(REGISTRY.properties["normal_position"]["values"])
KINDS_NEED_FAIL_POSITION = REGISTRY.kinds_requiring("fail_position")

# M2(2026-11-08, 레지스트리 0.2.0) 이전의 kind → 분류. 그때 저장한 수정 연산·판 이전 기록을 읽을 때만 쓴다.
# 표에 없는 kind는 그때 미분류였다(분류 자유).
LEGACY_KIND_CATEGORY = dict(
    [(k, "equipment") for k in ("reactor_vessel", "steam_generator", "pressurizer", "pump", "vessel", "tank",
                                "heat_exchanger", "turbine", "condenser", "filter", "demineralizer", "orifice", "vent")]
    + [(k, "valve") for k in ("manual_valve", "motor_operated_valve", "control_valve", "check_valve",
                              "isolation_valve", "psv")]
    + [(k, "instrument") for k in ("transmitter", "controller", "indicator", "temperature_element")]
    + [(k, "piping_element") for k in ("tee", "pipe_cap", "continuation")])

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

# 체크밸브 허용 방향(기획서/정보추출.md #check-valve-direction)
# ① 도형 속성 flow_direction의 허용값(정확히 이 값 하나)
CHECK_VALVE_FLOW_DIRECTION_VALUES = {"source_to_target"}
# ② 기호 기본 방향 등록표: (shape, valveType) -> 기본 방향 d0 (도면 좌표, x 오른쪽·y 아래쪽).
# 사람이 샘플 SVG로 확인하고 decisions.md에 승인을 기록하기 전에는 비워 둔다(테스트는 주입해 실행).
CHECK_VALVE_SYMBOL_DIRECTIONS = {}
# ② 판정 임계값(cos). 경계값은 판정 가능 쪽에 포함 [가정, 샘플로 조정]
CHECK_VALVE_COS_THRESHOLD = 0.2

# 포트(기획서/정보추출.md #port-rule): 물리 배관 끝에 포트 구분을 요구하는 kind [추론: 분리된 내부 유로]
KINDS_NEED_PORT = {"heat_exchanger", "steam_generator"}

# 표제란 키 -> drawing 메타데이터 필드
TITLE_BLOCK_FIELDS = {"DWG NO.": "drawing_number", "TITLE": "title", "REV.": "revision",
                      "NOTE": "note"}
