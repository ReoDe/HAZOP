"""DEXPI 클래스 <-> 우리 `kind` 대응표(HZ-PLN-22 §3). 가져오기(dexpi_import)와 내보내기(hazop.export.dexpi_export)가 같이 쓴다.

클래스 목록은 resources/library/dexpi-schema/classes-2-0-1.json(2.0.1 사양 원문에서 뽑음, scripts/build_dexpi_library.py)이다.
가져올 때는 클래스의 조상 가운데 표에 있는 가장 가까운 클래스로 정한다(하위 클래스 이름은 호출한 쪽이 `dexpi:type`에 남긴다).
표에 없는 클래스는 kind None(미분류)이고 category만 DEXPI 상위 클래스로 정한다(§5.5).
"""

import json
import os

from hazop import paths

DEXPI_VERSION = "2.0.1"
ATTRIBUTION = "DEXPI Specification 2.0.1, DEXPI e.V., CC BY 4.0"

_CLASSES = {}

# 설비: 가장 가까운 조상 -> kind (§3.2). Blower는 fan으로 가져온다
EQUIPMENT_KIND = {
    "Pump": "pump", "Compressor": "compressor", "Fan": "fan", "Blower": "fan", "Turbine": "turbine",
    "Tank": "tank", "Vessel": "vessel", "PressureVessel": "vessel", "HeatExchanger": "heat_exchanger",
    "Filter": "filter",
}
# 배관 부품 -> kind (§3.4). OperatedValve는 모든 밸브의 부모 클래스라 구동계 유무는 가져오는 쪽이 따로 본다
PIPING_KIND = {
    "OperatedValve": "manual_valve", "CheckValve": "check_valve", "SafetyValveOrFitting": "psv",
    "RuptureDisc": "rupture_disc", "RestrictionOrifice": "orifice", "FlowMeasuringElement": "flow_element",
    "PipeReducer": "reducer", "BlindFlange": "blind_flange", "Strainer": "strainer", "VentLine": "vent",
    "PipeTee": "tee", "PipeOffPageConnector": "continuation",
}
# 설비 안쪽(노드로 만들지 않고 부모 설비의 attributes에 넣는 것, §3.2)
EQUIPMENT_INTERNAL = ("Chamber", "TubeBundle", "Impeller", "Displacer")

# classes.json(배관·설비·계장 묶음)에 없지만 내보낸 파일이 쓰는 2.0.1 구조 클래스. 2.0.1 Reference P&ID에서 확인한 것만 적는다.
STRUCTURAL_TYPES = ("Plant/PlantModel", "Plant/Diagram.PlantMetaData", "Plant/Diagram.PipingNodePosition",
                    "Plant/Diagram.InstrumentationNodePosition")


def type_is_known(type_text):
    """`type` 문자열이 2.0.1 클래스인가. Core/…는 틀 클래스라 이름만 보고 통과, Plant/…는 목록과 구조 클래스 표에서 찾는다."""
    if type_text.startswith("Core/"):
        return True
    return type_text in STRUCTURAL_TYPES or class_of(type_text) in classes()


# 내보내기: kind -> (DEXPI 클래스, 정도). 정도 'approx'는 곁 파일·뺀 목록에 '근사'로 적는다(§3.2·§3.4).
EXPORT_CLASS = {
    "pump": ("Pump", "exact"), "compressor": ("Compressor", "exact"), "fan": ("Fan", "exact"),
    "turbine": ("Turbine", "exact"), "tank": ("Tank", "exact"), "vessel": ("Vessel", "exact"),
    "heat_exchanger": ("HeatExchanger", "exact"), "filter": ("Filter", "exact"),
    # 복수기 클래스가 없다. DEXPI SteamGenerator는 가열로 계열이라 원전 증기발생기와 뜻이 달라 쓰지 않는다(V-7)
    "condenser": ("HeatExchanger", "approx"), "steam_generator": ("HeatExchanger", "approx"),
    "reactor_vessel": ("PressureVessel", "approx"), "pressurizer": ("PressureVessel", "approx"),
    "accumulator": ("PressureVessel", "approx"), "demineralizer": ("PressureVessel", "approx"),
    "manual_valve": ("OperatedValve", "approx"), "isolation_valve": ("OperatedValve", "approx"),
    "motor_operated_valve": ("OperatedValve", "approx"), "air_operated_valve": ("OperatedValve", "approx"),
    "solenoid_valve": ("OperatedValve", "approx"), "control_valve": ("OperatedValve", "approx"),
    "check_valve": ("CheckValve", "exact"), "psv": ("SafetyValveOrFitting", "exact"),
    "relief_valve": ("SafetyValveOrFitting", "exact"), "rupture_disc": ("RuptureDisc", "exact"),
    "orifice": ("RestrictionOrifice", "exact"), "flow_element": ("FlowMeasuringElement", "exact"),
    "reducer": ("PipeReducer", "exact"), "blind_flange": ("BlindFlange", "exact"), "strainer": ("Strainer", "exact"),
    "vent": ("VentLine", "approx"), "tee": ("PipeTee", "exact"),
    "silencer": ("Silencer", "exact"), "flame_arrestor": ("FlameArrestor", "exact"),
    "sight_glass": ("SightGlass", "exact"), "electric_heater": ("ElectricHeater", "exact"),
}
# DEXPI에 맞는 자리가 없는 kind: 내보낼 때 뺀다(§6.2)
EXPORT_NONE = ("damper", "drain", "test_connection", "pipe_cap", "nozzle",
               # APR1400 범례로 들인 종류(registry 0.9.0) 가운데 DEXPI 클래스가 분명하지 않은 것
               "air_flow_arrow", "slip_joint", "sparger", "hose_connection", "flexible_hose", "diaphragm_seal",
               "expansion_joint", "pilot_light", "alarm", "sample_probe", "level_element", "chiller")
INSTRUMENT_KINDS = ("transmitter", "controller", "indicator", "recorder", "switch", "temperature_element")
# 구동계(ActuatingSystem)를 같이 내는 밸브 kind
ACTUATED_KINDS = ("motor_operated_valve", "air_operated_valve", "solenoid_valve", "control_valve")

# FailAction 열거 값(2.0.1, F17) <-> 우리 fail_position(§3.4). `FL`(고장 시 잠김)은 DEXPI에 따로 없어 FailRetainPosition으로 내고
# 곁 파일에 FL을 남긴다. 가져올 때 FailRetainPosition은 FAI다.
FAIL_ACTION = {"FailOpen": "FO", "FailClose": "FC", "FailRetainPosition": "FAI"}
FAIL_ACTION_BACK = {"FO": "FailOpen", "FC": "FailClose", "FAI": "FailRetainPosition", "FL": "FailRetainPosition"}


def classes():
    """{클래스 이름: {package, abstract, supers}}. 파일이 없으면 FileNotFoundError."""
    if not _CLASSES:
        with open(paths.folder("dexpi-schema", "classes-2-0-1.json"), encoding="utf-8") as fh:
            _CLASSES.update(json.load(fh)["classes"])
    return _CLASSES


def is_known(cls):
    return cls in classes()


def ancestry(cls):
    """cls 자신과 모든 조상(가까운 것부터, 중복 없음)."""
    table, out, queue = classes(), [], [cls]
    while queue:
        c = queue.pop(0)
        if c in out:
            continue
        out.append(c)
        queue.extend(table.get(c, {}).get("supers", []))
    return out


def derives_from(cls, ancestor):
    return ancestor in ancestry(cls)


def class_of(type_text):
    """`Plant/Piping.PipeTee` -> `PipeTee`. 점이나 슬래시가 없으면 그대로."""
    return (type_text or "").replace("/", ".").rsplit(".", 1)[-1]


def package_of(type_text):
    """`Plant/Piping.PipeTee` -> `Piping`, `Core/Diagram.Text` -> `Diagram`, 점이 없으면 ''."""
    text = (type_text or "").replace("/", ".")
    return text.rsplit(".", 2)[-2] if text.count(".") >= 1 else ""


def group_of(cls):
    """클래스의 쓰임: equipment | nozzle | piping | offpage | instrument | None(그 밖). 조상으로 정한다."""
    anc = ancestry(cls)
    if "Nozzle" in anc:
        return "nozzle"
    if "ProcessEquipment" in anc:
        return "equipment"
    if "PipeOffPageConnector" in anc:
        return "offpage"
    if "PipingComponent" in anc:
        return "piping"
    if "ProcessInstrumentationFunction" in anc:
        return "instrument"
    return None


def import_kind(cls, group=None):
    """(kind 또는 None, 대응 클래스 이름 또는 None). 조상 중 표에 있는 가장 가까운 클래스를 쓴다."""
    group = group or group_of(cls)
    table = EQUIPMENT_KIND if group == "equipment" else PIPING_KIND if group in ("piping", "offpage") else {}
    for c in ancestry(cls):
        if c in table:
            return table[c], c
    return None, None


def raw_category(group):
    """미분류 노드의 category(§5.5): 설비 하위 -> equipment, 배관 부품 -> inline_component, 계장 -> instrument."""
    return {"equipment": "equipment", "piping": "inline_component", "offpage": "piping_element",
            "instrument": "instrument"}.get(group)


def instrument_kind(variable, functions):
    """계측 기능 문자(변수 문자, 기능 문자)로 계기 kind를 정한다. 모르면 None. ISA-5.1 관례 [추론]."""
    letters = (functions or "").upper()
    if "T" in letters:
        return "transmitter"
    if "C" in letters:
        return "controller"
    if "R" in letters:
        return "recorder"
    if "I" in letters:
        return "indicator"
    if "S" in letters or "A" in letters:
        return "switch"
    if "E" in letters and (variable or "").upper() == "T":
        return "temperature_element"
    return None


def library_ready():
    return os.path.isfile(paths.folder("dexpi-schema", "classes-2-0-1.json"))
