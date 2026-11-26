"""구성요소 속성 카드의 자료(읽기 토픽 `props`): 그 구성요소 자체의 사양(지름·두께·재질 …)을 종류별 항목 표로 돌려준다. Qt를 import하지 않는다.

이어진 곳·든 구간은 속성이 아니라서 넣지 않는다. 값이 없는 항목도 이름은 그대로 돌려주고(value None) 화면이 '—'로 보인다. 지어내지 않는다.
읽기: props/<graph_id>/<local_id> → {"found", "group", "group_label", "items": [{"label", "value", "source"}]}.
source: {"kind": "drawing"} 또는 {"kind": "document", "name": 문서 이름}.

값의 출처 두 곳(항목 ↔ 칸 대응표는 아래 SPECS가 기준이고 시험이 지킨다):
1. 도면에서 읽은 속성: 고친 추출의 구성요소 attributes(배관은 relation attributes). 이름은 hazop/kg/schema/registry.json의 속성 사전 이름이다.
2. 설계 문서에서 뽑은 지식: 프로젝트 지식그래프의 속성 주장(claims) 가운데 문서가 낸 것(holder가 있음). 사전 속성 이름이 같거나, 속성 칸이 없는 종류라서
   속성 이름이 비어 있으면 문서 항목 이름(item: '설계압력' 등)이 같은 것.
두 곳에 모두 있으면 도면 값을 쓴다(둘이 다른 것은 지식그래프의 충돌 표시가 따로 보여 준다).
"""

import logging
import os

LOG = logging.getLogger("hazop.shell.api_props")

TOPICS = ("props",)

# 항목 하나: (화면 이름, 도면 속성 이름들, 문서 항목 이름들). 속성 이름은 앞에서부터 찾는다. 속성 사전에 아직 없는 이름(wall_thickness 등)도 적어 둔다:
# 추출이 그 이름으로 내기 시작하면 그대로 채워진다.
I_DIAMETER = ("호칭 지름", ("nominal_diameter", "size"), ())
I_MATERIAL = ("재질", ("material",), ("재질",))
I_DESIGN_P = ("설계 압력", ("design_pressure", "design_pressure_max"), ("설계압력",))
I_DESIGN_T = ("설계 온도", ("design_temperature", "design_temperature_max"), ("설계온도",))

SPECS = {
    "pipe": ("배관", (
        I_DIAMETER,
        ("두께(스케줄)", ("schedule", "wall_thickness"), ("두께", "스케줄")),
        I_MATERIAL, I_DESIGN_P, I_DESIGN_T,
        ("유체", ("fluid_code", "fluid"), ("유체",)),
        ("보온", ("insulation",), ("보온",)))),
    "vessel": ("용기·열교환기·탱크", (
        I_MATERIAL, I_DESIGN_P, I_DESIGN_T,
        ("용량", ("capacity", "volume"), ("용량", "용적")),
        ("치수", ("dimensions", "size"), ("치수",)))),
    "rotating": ("펌프·압축기", (
        ("형식", ("pump_type", "equipment_type"), ("형식",)),
        ("정격 유량", ("rated_flow",), ("정격유량", "정격 유량")),
        ("정격 양정(압력)", ("rated_head", "rated_pressure"), ("정격양정", "정격 양정")),
        ("동력", ("rated_power", "driver"), ("동력", "정격동력")),
        I_MATERIAL)),
    "valve": ("밸브", (
        ("형식", ("valve_type",), ("형식",)),
        I_DIAMETER,
        ("압력 등급", ("pressure_class", "rating"), ("압력등급", "압력 등급")),
        I_MATERIAL,
        ("구동 방식", ("actuator_type", "motive_power"), ("구동방식", "구동 방식")),
        ("고장 시 위치", ("fail_position",), ("고장위치", "고장 시 위치")))),
    "relief": ("안전·방출밸브", (      # 안전밸브·방출밸브·파열판: 밸브 항목에 설정 압력을 더한다(도면에서 가장 많이 읽히는 값)
        ("형식", ("valve_type",), ("형식",)),
        I_DIAMETER,
        ("압력 등급", ("pressure_class", "rating"), ("압력등급", "압력 등급")),
        I_MATERIAL,
        ("설정 압력", ("set_pressure",), ("설정압력",)),
        ("고장 시 위치", ("fail_position",), ("고장위치", "고장 시 위치")))),
    "instrument": ("계기", (
        ("측정 변수", ("measured_variable",), ("측정변수",)),
        ("측정 범위", ("range_min", "range_max"), ("측정범위",)),
        ("기능", ("functions",), ("기능",)),
        ("설정값", ("set_pressure", "alarm_setpoint", "trip_setpoint"), ("설정압력", "설정값", "경보설정치", "트립설정치")))),
    "other": ("그 밖", (
        I_MATERIAL,
        ("비고", ("remarks", "note"), ("비고",)))),
}

# 값이 약속된 글자(enum)인 속성은 한글로 보인다.
ENUM_KO = {
    "valve_type": {"gate": "게이트", "globe": "글로브", "ball": "볼", "butterfly": "버터플라이", "plug": "플러그"},
    "motive_power": {"air": "공기", "electric": "전기", "hydraulic": "유압"},
    "fail_position": {"FO": "열림", "FC": "닫힘", "FL": "잠금", "FAI": "그대로"},
    "driver": {"motor": "전동기", "turbine": "터빈"},
    "actuator_type": {"motor": "전동기", "diaphragm": "다이어프램", "solenoid_pilot": "솔레노이드", "piston": "피스톤", "manual": "수동",
                      "diaphragm+solenoid_pilot": "다이어프램+솔레노이드"},
}
RELIEF_KINDS = ("psv", "relief_valve", "rupture_disc")
ROTATING_CLASSES = ("pump", "compressor", "fan")


def group_of(kind, layer):
    """구성요소 종류(kind)와 그림 층(layer: symbol|pipe) → SPECS의 묶음 열쇠. 종류를 모르면 'other'."""
    if layer == "pipe":
        return "pipe"
    from hazop.kg.schema import REGISTRY
    if kind in RELIEF_KINDS:
        return "relief"
    cid = REGISTRY.kind_class.get(kind)
    if cid is None:
        return "other"
    chain = [cid]
    while REGISTRY.classes[chain[-1]].get("parent"):
        chain.append(REGISTRY.classes[chain[-1]]["parent"])
    if any(c in ROTATING_CLASSES for c in chain):
        return "rotating"
    if "valve" in chain:
        return "valve"
    if "instrument" in chain:
        return "instrument"
    if "equipment" in chain:
        return "vessel"
    return "other"


def _one(name, value):
    if value in (None, ""):
        return None
    return ENUM_KO.get(name, {}).get(str(value), str(value))


def _from_attrs(names, attrs):
    """도면 속성에서 이 항목의 값 한 줄. 이름이 여럿이면 값이 있는 것을 ' · '로 이어 쓰되, 측정 범위(하한~상한)만 '~'로 잇는다."""
    if names == ("range_min", "range_max"):
        lo, hi = _one("range_min", attrs.get("range_min")), _one("range_max", attrs.get("range_max"))
        return (lo + "~" + hi) if lo and hi else (lo or hi)
    if names == ("actuator_type", "motive_power"):
        parts = [_one(n, attrs.get(n)) for n in names]
        return " · ".join(p for p in parts if p) or None
    for n in names:
        v = _one(n, attrs.get(n))
        if v:
            return v
    return None


def _claim_value(c):
    v = c.get("value")
    if v in (None, ""):
        return None
    unit = c.get("unit")
    return str(v) + (" " + unit if unit else "")


def values_for(group, attrs, doc_claims):
    """묶음 열쇠·도면 속성·문서 주장 목록 → 항목 목록. doc_claims: [{"property", "item", "value", "unit", "name"}]."""
    label, specs = SPECS[group]
    items = []
    for name, attr_names, doc_items in specs:
        value = _from_attrs(attr_names, attrs or {})
        source = {"kind": "drawing"} if value else None
        if not value:
            for c in doc_claims:
                if (c.get("property") in attr_names) or (c.get("property") is None and c.get("item") in doc_items):
                    v = _claim_value(c)
                    if v:
                        value, source = v, {"kind": "document", "name": c.get("name")}
                        break
        items.append({"label": name, "value": value, "source": source})
    return {"group": group, "group_label": label, "items": items}


# ---------------------------------------------------------------- 자료 모으기

_KG_CACHE = {}


def _kg(engine):
    """프로젝트 지식그래프(없거나 깨졌으면 None). 포인터 파일이 그대로면 다시 읽지 않는다."""
    from hazop import paths
    from hazop.kg import build
    pid = engine.project_id()
    root = os.path.join(paths.output_root("knowledge-graph"), paths.safe_name("kg-%s" % pid))
    ptr = os.path.join(root, build.POINTER_FILE)
    try:
        st = os.stat(ptr)
    except OSError:
        return None
    key = (root, st.st_mtime_ns, st.st_size)
    hit = _KG_CACHE.get("key") == key
    if not hit:
        try:
            _KG_CACHE.clear()
            _KG_CACHE.update(key=key, kg=build.load_outputs(root)[1])
        except (OSError, ValueError, KeyError):
            LOG.warning("지식그래프를 읽지 못해 속성 카드에 문서 값을 넣지 않음", exc_info=True)
            return None
    return _KG_CACHE.get("kg")


def _doc_claims(engine, graph_id, source_object_id):
    """이 구성요소(도면·source_object_id)를 가리키는 문서 속성 주장 → values_for가 쓰는 꼴."""
    if not source_object_id:
        return []
    from hazop.kg import claims as kgclaims
    kg = _kg(engine)
    if not kg:
        return []
    target = kgclaims.stable_ref(graph_id, source_object_id)
    mine = [c for c in kg.get("claims") or [] if c.get("target") == target and c.get("holder")]
    if not mine:
        return []
    names = {}
    try:
        from hazop.shell import api_docs
        names = {e["record"].get("material_id"): api_docs._name(e["record"]) for e in api_docs._entries(engine.project_id())}
    except (OSError, ValueError, KeyError):
        pass
    out = []
    for c in mine:
        mid = (c.get("source") or {}).get("material_id")
        out.append({"property": c.get("property"), "item": c.get("item"), "value": c.get("value"), "unit": c.get("unit"), "name": names.get(mid) or mid})
    return out


def props(engine, graph_id, local_id):
    """속성 카드 자료. 도면이나 구성요소를 모르면 None."""
    from hazop.app import data
    name = engine.graph_names().get(graph_id)
    if not name:
        return None
    _original, corrected = data.load_extraction(name)
    rec, layer = None, "symbol"
    for n in corrected.get("nodes") or []:
        if isinstance(n, dict) and n.get("local_id") == local_id:
            rec = n
            break
    if rec is None:
        for r in corrected.get("relations") or []:
            if isinstance(r, dict) and r.get("local_id") == local_id:
                rec, layer = r, "pipe"
                break
    if rec is None:
        return None
    group = group_of(rec.get("kind"), layer)
    attrs = dict(rec.get("attributes") or {})
    if layer == "pipe" and rec.get("line_no") and not attrs.get("line_no"):
        attrs["line_no"] = rec["line_no"]
    out = values_for(group, attrs, _doc_claims(engine, graph_id, rec.get("source_object_id")))
    out["found"] = True
    return out


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts == ['props', graph_id, local_id]."""
    from hazop.shell import api
    if len(parts) != 3:
        return None
    data = props(engine, parts[1][:200], parts[2][:200])
    return api._json(data) if data is not None else None
