"""도면 그래프(graph.json) -> DEXPI XML 2.0.1 파일 + 뺀 목록 + 곁 파일 (HZ-PLN-22 §6, 단위 X2).

원칙(권장안 V-2·V-6):
- 구성요소 자체가 불확실한 것(분류 못 함, 끝이 미확정인 연결, 제안 상태 AI 후보)은 뺀다. AI 후보는 사람이 수락해 사람 수정 기록에 들어간 것만
  그래프에 있으므로(hazop.extract.ai_review) 이 모듈은 그래프에 있는 것만 낸다.
- 구성요소는 확실하고 속성만 미확인이거나 DEXPI에 자리가 없는 속성은 그 속성만 뺀다. 추측값을 넣지 않는다.
- DEXPI 파일 안에 미확인 표시를 넣지 않는다. 뺀 것과 자리가 없는 정보는 `<이름>.excluded.json`·`<이름>.hazop.json`(곁 파일)에 적는다.
- 파일을 쓰기 전에 §6.5 검사(스키마 규칙·클래스 목록·참조·되읽기)를 통과해야 한다. 하나라도 걸리면 아무 파일도 쓰지 않는다.
같은 입력이면 같은 바이트가 나온다(시각은 묶음 목록에만 둔다).
"""

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from hazop import paths, store_io
from hazop.extract import dexpi_map
from hazop.extract.adapters import dexpi_import, dexpi_read

SIDECAR_SCHEMA = "hazop_dexpi_sidecar/1"
EXCLUDED_SCHEMA = "hazop_dexpi_excluded/1"
MANIFEST_SCHEMA = "hazop_dexpi_manifest/1"
EXPORTER_VERSION = "0.1.0"
MODEL_SOURCE = {"Core": "https://data.dexpi.org/models/2.0.1/Core.xml", "Plant": "https://data.dexpi.org/models/2.0.1/Plant.xml"}
A3 = (420.0, 297.0)
MARGIN = 10.0
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_QUANTITY = re.compile(r"(\S+) ((?:Pressure\w+|Temperature|Length|VolumeFlowRate|\w+)Unit)\.(\w+)\Z")
_DATA_REF = re.compile(r"(?:Core|Plant)/[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)+\Z")
_PRETTY_BACK = {"(g)": "PressureGaugeUnit", "(a)": "PressureAbsoluteUnit"}
_UNIT_BACK = {v: k for k, v in dexpi_import.UNIT_NAMES.items()}
_TEMPERATURE = {"°C": "TemperatureUnit.DegreeCelsius", "K": "TemperatureUnit.Kelvin", "°F": "TemperatureUnit.DegreeFahrenheit"}
# DEXPI 속성으로 옮기지 않고 따로 처리하거나 곁 파일에만 두는 우리 속성
HANDLED_ATTRS = {"kind", "tag", "dexpi:type", "dexpi:nozzles", "dexpi:chambers", "dexpi:nodes", "dexpi:segment", "dexpi:system",
                 "dexpi:ActuatingSystemNumber", "dexpi:FailAction", "fail_position", "symbol_id", "flow_direction",
                 "to_drawing", "to_object", "direction", "line_no", "line_type"}
CHAMBER_ATTRS = dexpi_import.CHAMBER_FIELDS
VALVE_KINDS = ("manual_valve", "isolation_valve", "motor_operated_valve", "air_operated_valve", "solenoid_valve", "control_valve",
               "check_valve", "psv", "relief_valve", "rupture_disc", "damper")


class ExportError(ValueError):
    """내보내지 못함. reasons는 사람이 읽을 문장 목록(§6.5 검사 실패, 도면 번호 미확정 등)."""

    def __init__(self, reasons):
        reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        ValueError.__init__(self, "; ".join(reasons))
        self.reasons = reasons


class Export:
    """한 도면의 내보내기 결과."""

    def __init__(self, name, xml, excluded, sidecar, stats):
        self.name, self.xml, self.excluded, self.sidecar, self.stats = name, xml, excluded, sidecar, stats

    @property
    def files(self):
        """쓸 파일 {파일 이름: 바이트}."""
        return {self.name + ".dexpi.xml": self.xml,
                self.name + ".excluded.json": _json_bytes(self.excluded),
                self.name + ".hazop.json": _json_bytes(self.sidecar)}


def _json_bytes(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def valid_name(text):
    return bool(text) and _NAME.match(text) is not None


def _safe_name(text, default="drawing"):
    out = re.sub(r"[^A-Za-z0-9_]", "_", str(text or default)).strip("_") or default
    return out if re.match(r"[A-Za-z_]", out) else "D_" + out


def quantity_to_dexpi(text):
    """'60.0 PressureGaugeUnit.Bar' / '16.0 bar(g)' / '80 °C' -> (값 문자열, 'PressureGaugeUnit.Bar') 또는 None.
    확인한 열거 이름만 쓴다. 단위가 모호하거나 처음 보는 이름이면 None(곁 파일에 남김)."""
    text = (text or "").strip()
    m = _QUANTITY.match(text)
    if m:
        return m.group(1), "%s.%s" % (m.group(2), m.group(3))
    parts = text.split(None, 1)
    if len(parts) != 2 or _num(parts[0]) is None:
        return None
    value, unit = parts
    if unit in _TEMPERATURE:
        return value, _TEMPERATURE[unit]
    for suffix, group in _PRETTY_BACK.items():
        if unit.endswith(suffix) and unit[:-len(suffix)] in _UNIT_BACK:
            return value, "%s.%s" % (group, _UNIT_BACK[unit[:-len(suffix)]])
    return None


def _num(text):
    try:
        float(text)
        return text
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- XML 조립
def _el(parent, tag, **attrs):
    e = ET.SubElement(parent, tag)
    for k, v in attrs.items():
        e.set(k, v)
    return e


def _data(parent, prop, value):
    """Data 요소 하나. value: 문자열(수량·열거 참조는 알맞은 요소로), bool·숫자 아님(DEXPI가 문자열로 받는 속성만 옮긴다)."""
    d = _el(parent, "Data", property=prop)
    q = quantity_to_dexpi(value) if isinstance(value, str) else None
    if q:
        agg = _el(d, "AggregatedDataValue", type="Core/PhysicalQuantities.PhysicalQuantity")
        u = _el(agg, "Data", property="Unit")
        _el(u, "DataReference", data="Core/PhysicalQuantities.%s" % q[1])
        v = _el(agg, "Data", property="Value")
        _el(v, "Double").text = q[0]
    elif isinstance(value, str) and _DATA_REF.match(value):
        _el(d, "DataReference", data=value)
    else:
        _el(d, "String").text = value
    return d


def _refs(parent, prop, target):
    _el(parent, "References", objects="#" + target, property=prop)


def _components(parent, prop):
    return _el(parent, "Components", property=prop)


def _obj(parent, typ, oid=None):
    o = _el(parent, "Object", type=typ)
    if oid:
        o.set("id", oid)
    return o


class _Ids:
    """파일 안에서 겹치지 않는 id(§6.6). DEXPI에서 가져온 객체의 id가 글자 규칙에 맞으면 그대로(keep=True), 그 밖에는
    `HZ_` + 원래 ID의 규칙 밖 글자를 `_`로 바꾼 값. 겹치면 `_2`, `_3`…을 붙인다. 순서는 부르는 순서(엔터티 ID 순)라 결정적이다."""

    def __init__(self):
        self.used = set()
        self.counter = {}

    def take(self, preferred, prefix, keep=False):
        if keep and valid_name(preferred) and preferred not in self.used:
            self.used.add(preferred)
            return preferred
        if preferred:
            base = "HZ_" + re.sub(r"[^A-Za-z0-9_]", "_", str(preferred))
        else:
            n = self.counter.get(prefix, 0) + 1
            while "HZ_%s%d" % (prefix, n) in self.used:
                n += 1
            self.counter[prefix] = n
            base = "HZ_%s%d" % (prefix, n)
        cand, k = base, 1
        while cand in self.used:
            k += 1
            cand = "%s_%d" % (base, k)
        self.used.add(cand)
        return cand


# ---------------------------------------------------------------- 본체
def export_drawing(graph, extraction=None, require_confirmed_number=True, name=None):
    """그래프 하나 -> Export. graph는 build_graph 결과(사람 수정·수락한 AI 후보가 이미 반영됨). extraction은 있으면 도면 크기·번호
    확정 여부·가져온 원문 조각을 읽는 데 쓴다. 내보낼 수 없으면 ExportError."""
    dwg = graph["source"].get("drawing_number")
    reasons = []
    if graph["validation"]["status"] != "passed":
        reasons.append("그래프가 구조 검증을 통과하지 못함(차단 오류 %d건)" % len(graph["validation"]["blockers"]))
    if not dwg:
        reasons.append("도면 번호가 없어 도면 사이 참조를 쓸 수 없음")
    elif require_confirmed_number and (extraction is None
                                       or (extraction.get("drawing") or {}).get("identification_basis") != "registration_confirmed"):
        reasons.append("도면 번호 %s 가 등록에서 사람이 확정한 값이 아님(표제란 후보만 있음)" % dwg)
    if reasons:
        raise ExportError(reasons)
    return _Builder(graph, extraction, name or paths.safe_name(dwg)).run()


class _Builder:

    def __init__(self, graph, extraction, name):
        self.g, self.ex, self.name = graph, extraction, name
        self.ids = _Ids()
        self.excl_nodes, self.excl_conn, self.excl_attrs, self.approx = [], [], [], []
        self.check_dirs = {}
        self.evidence = {n["local_id"]: n.get("evidence") for n in (extraction or {}).get("nodes", [])}
        self.nodes = {n["entity_id"]: n for n in graph["nodes"] if n["node_type"] == "drawing_object"}
        self.segs = {n["entity_id"]: n for n in graph["nodes"] if n["node_type"] == "pipe_segment"}
        self.plan = {}  # entity_id -> {"cls", "group", "id", ...}
        self.node_ids = {}  # entity_id -> [PipingNode id] (항목 노드)
        self.noz = {}  # entity_id -> {port: (nozzle id, node id)}
        self.positions = {}  # PipingNode id -> (x, y) mm
        self.pending_conn = []
        self.sc = self._scale()

    # ----- 좌표
    def _scale(self):
        if (self.g.get("coordinate_system") or {}).get("coordinate_space") == "dexpi_diagram":
            return {"factor": 1.0, "dx": 0.0, "dy": 0.0}
        w = h = None
        if self.ex:
            w, h = self.ex["drawing"].get("page_width"), self.ex["drawing"].get("page_height")
        if not w or not h:
            xs = [n["position"][0] for n in self.nodes.values() if n.get("position")] or [1.0]
            ys = [n["position"][1] for n in self.nodes.values() if n.get("position")] or [1.0]
            w, h = max(xs) * 1.05 or 1.0, max(ys) * 1.05 or 1.0
        factor = round(min((A3[0] - 2 * MARGIN) / w, (A3[1] - 2 * MARGIN) / h), 6)
        return {"factor": factor, "dx": MARGIN, "dy": MARGIN}

    def _xy(self, p):
        return (round(p[0] * self.sc["factor"] + self.sc["dx"], 3), round(p[1] * self.sc["factor"] + self.sc["dy"], 3))

    # ----- 1. 구성요소 계획
    def _decide_nodes(self):
        for eid, n in self.nodes.items():
            kind, attrs = n["kind"], n["attributes"]
            cls, why = None, None
            if kind is None or n["classification"] == "unclassified":
                why = "unclassified"
            elif kind in dexpi_map.EXPORT_NONE:
                why = "no_dexpi_class"
            elif kind in dexpi_map.INSTRUMENT_KINDS:
                cls = "ProcessInstrumentationFunction"
            elif kind == "continuation":
                direction = self._direction(n)
                if direction is None:
                    why = "direction_unknown"
                else:
                    cls = "FlowInPipeOffPageConnector" if direction == "FROM" else "FlowOutPipeOffPageConnector"
            elif kind not in dexpi_map.EXPORT_CLASS:
                why = "no_dexpi_class"  # 대응표에 없는 새 kind는 지어내지 않고 뺀다
            else:
                base = dexpi_map.EXPORT_CLASS[kind][0]
                cls = base
                orig = attrs.get("dexpi:type")
                if orig and dexpi_map.is_known(orig) and dexpi_map.derives_from(orig, base):
                    cls = orig  # 가져온 파일의 하위 클래스를 그대로 되쓴다(§7.1)
                if dexpi_map.EXPORT_CLASS[kind][1] == "approx" and kind not in ("manual_valve", "isolation_valve"):
                    self.approx.append({"entity_id": eid, "kind": kind, "dexpi_class": cls, "reason": "approximate_class"})
            raw = self._raw_object(n) if why == "unclassified" else None
            if raw is not None:  # 가져온 미분류 객체: 사람이 고치지 않았으면 원문 조각 그대로 되쓴다(§7.2)
                cls = dexpi_map.class_of(raw.get("type"))
                group = dexpi_map.group_of(cls)
                self.plan[eid] = {"cls": cls, "group": group, "id": raw.get("id"), "raw": raw}
                for el in raw.iter("Object"):
                    if el.get("id"):
                        self.ids.used.add(el.get("id"))
                self.approx.append({"entity_id": eid, "reason": "restored_from_original_text", "dexpi_class": cls})
                continue
            if why:
                self.excl_nodes.append({"entity_id": eid, "kind": kind, "tag": n["tag"], "reason": why})
                continue
            group = dexpi_map.group_of(cls)
            self.plan[eid] = {"cls": cls, "group": group,
                              "id": self.ids.take(self._origin_id(n), _PREFIX.get(group, "Item"), keep=self._from_dexpi(n))}

    @staticmethod
    def _from_dexpi(n):
        """DEXPI 파일에서 가져온 노드인가(가져올 때 `dexpi:type`을 남긴다)."""
        return "dexpi:type" in n["attributes"]

    def _origin_id(self, n):
        """내보낼 id의 바탕: DEXPI에서 가져왔으면 파일의 id, 아니면 엔터티 ID(§6.6)."""
        return n["source_object_id"] if self._from_dexpi(n) else n["entity_id"]

    def _raw_object(self, n):
        """미분류 노드의 DEXPI 원문 조각(2.0 파일에서 가져왔고 잘리지 않았고 사람이 고치지 않은 것만)을 읽어 돌려준다. 없으면 None."""
        if not self.ex or (self.ex.get("source") or {}).get("dexpi_flavor") != dexpi_read.FMT_DEXPI or n.get("origin") != "pid_extract":
            return None
        ev = ((self.evidence.get(n["local_id"]) or {}).get("dexpi")) or {}
        if not ev.get("xml") or ev.get("xml_cut") or not ev.get("id") or not valid_name(ev["id"]) or ev["id"] in self.ids.used:
            return None
        try:
            raw = dexpi_read.parse_safely(ev["xml"].encode("utf-8"))
        except dexpi_read.DexpiError:
            return None
        if any(not valid_name(o.get("id")) for o in raw.iter("Object") if o.get("id") is not None) or \
                dexpi_read.check_references(raw):  # 원문 조각 안의 id·참조가 §6.6 규칙에 안 맞으면 되살리지 않는다
            return None
        group = dexpi_map.group_of(dexpi_map.class_of(raw.get("type"))) if raw.tag == "Object" and raw.get("type") else None
        return raw if group in ("equipment", "piping", "offpage") else None

    @staticmethod
    def _direction(n):
        d = n["attributes"].get("direction")
        if d in ("FROM", "TO"):
            return d
        m = re.match(r"\s*(FROM|TO)\b", n.get("label_text") or "", re.I)
        return m.group(1).upper() if m else None

    # ----- 2. 연결 계획
    def _decide_connections(self):
        ends = {}
        for e in self.g["edges"]:
            if e["kind"] == "has_endpoint":
                ends.setdefault(e["segment"], {})[e["end"]] = e
        for sid, seg in self.segs.items():
            pair = ends.get(sid, {})
            if set(pair) != {"source", "target"}:
                self.excl_conn.append({"entity_id": sid, "tag": seg["tag"], "reason": "bad_endpoint_count"})
                continue
            src, dst = pair["source"], pair["target"]
            gone = [x["node"] for x in (src, dst) if x["node"] not in self.plan]
            if gone:
                self.excl_conn.append({"entity_id": sid, "tag": seg["tag"], "reason": "endpoint_excluded",
                                       "excluded_ends": gone})
                continue
            fd = seg.get("flow_direction")  # 확인된 흐름이 있으면 연결을 흐름 순서로 적는다(§7.3)
            self.pending_conn.append({"seg": seg, "src": src, "dst": dst, "swap": bool(fd and fd.get("from_end") == "target")})
        for u in self.g.get("unresolved", []):
            self.excl_conn.append({"entity_id": u.get("local_id"), "tag": u.get("line_no"), "reason": "unresolved_connector",
                                   "kind": u.get("kind")})
        self._orient_check_valves()

    def _orient_check_valves(self):
        """체크밸브의 입구 구간은 밸브 쪽이 Target, 출구 구간은 Source가 되게 맞춘다(DEXPI에 허용 방향이 없어 순서로 적는다, §3.1)."""
        by_seg = {c["seg"]["entity_id"]: c for c in self.pending_conn}
        for eid, n in self.nodes.items():
            cd = n.get("check_direction")
            if eid not in self.plan or not cd:
                continue
            for role in ("inlet", "outlet"):
                c = by_seg.get(cd.get(role))
                if c is None:
                    continue
                here = c["src"] if c["src"]["node"] == eid else c["dst"] if c["dst"]["node"] == eid else None
                if here is None:
                    continue
                # 입구 구간은 밸브 쪽이 Target, 출구 구간은 Source. 흐름 순서보다 체크밸브 입구·출구가 먼저다
                c["swap"] = (here is c["src"]) if role == "inlet" else (here is c["dst"])
            self.check_dirs[self.plan[eid]["id"]] = {"inlet": cd.get("inlet"), "outlet": cd.get("outlet"),
                                                     "basis": cd.get("basis"), "status": cd.get("status")}

    # ----- 3. 노드·노즐 배정
    def _allocate(self):
        for eid, p in self.plan.items():
            n = self.nodes[eid]
            if p.get("raw") is not None:
                self._allocate_raw(eid, p)
                continue
            self.node_ids[eid] = []
            for x in _loads(n["attributes"].get("dexpi:nodes")):
                nid = self.ids.take(x.get("id"), "Node", keep=True)
                self.node_ids[eid].append(nid)
                if x.get("position"):
                    self.positions[nid] = tuple(x["position"])
            if p["group"] == "equipment":
                self.noz[eid] = {}
                for z in _loads(n["attributes"].get("dexpi:nozzles")):
                    nz = self.ids.take(z.get("id"), "Nozzle", keep=True)
                    nodes = z.get("nodes") or []
                    nd = self.ids.take(nodes[0].get("id") if nodes else None, "Node", keep=True)
                    if nodes and nodes[0].get("position"):
                        self.positions[nd] = tuple(nodes[0]["position"])
                    self.noz[eid][z.get("port")] = {"id": nz, "node": nd, "cls": z.get("class") or "ProcessNozzle",
                                                    "attrs": z.get("attributes") or {}, "port": z.get("port")}

    def _allocate_raw(self, eid, p):
        raw = p["raw"]
        if p["group"] == "equipment":
            self.noz[eid] = {}
            for comp in raw.findall("Components"):
                if comp.get("property") == "Nozzles":
                    for z in comp.findall("Object"):
                        port, node = z.get("id"), None
                        for d in z.findall("Data"):
                            if d.get("property") == "SubTagName":
                                port = "".join(d.itertext()).strip() or port
                        for c in z.findall("Components"):
                            if c.get("property") == "Nodes" and c.find("Object") is not None:
                                node = c.find("Object").get("id")
                        if node:
                            self.noz[eid][port] = {"id": z.get("id"), "node": node, "cls": "ProcessNozzle", "attrs": {}, "port": port,
                                                   "raw": True}
        else:
            self.node_ids[eid] = [o.get("id") for c in raw.findall("Components") if c.get("property") == "Nodes"
                                  for o in c.findall("Object") if o.get("id")]

    def _end(self, eid, port, used):
        """연결 끝 하나 -> (item id, node id). 설비는 포트 이름의 노즐, 그 밖은 쓰는 순서대로 노드."""
        p = self.plan[eid]
        if p["group"] == "equipment":
            table = self.noz[eid]
            if port is None:
                k = 1
                while ("N%d" % k) in table:
                    k += 1
                port = "N%d" % k
                self.approx.append({"entity_id": eid, "reason": "nozzle_name_generated", "name": port})
            z = table.get(port)
            if z is None:  # 새로 만드는 노즐: HZ_ + 부모 id + _N + 번호(§6.6 5)
                nz = self.ids.take("%s_N%d" % (p["id"], len(table) + 1), "Nozzle")
                nd = self.ids.take("%s_Node%d" % (nz, 1), "Node")
                z = table[port] = {"id": nz, "node": nd, "cls": "ProcessNozzle", "attrs": {"SubTagName": port}, "port": port}
            return z["id"], z["node"]
        k = used.get(eid, 0)
        used[eid] = k + 1
        ids = self.node_ids.setdefault(eid, [])
        while len(ids) <= k:
            ids.append(self.ids.take("%s_Node%d" % (p["id"], len(ids) + 1), "Node"))
        return p["id"], ids[k]

    # ----- 4. 쓰기
    def run(self):
        self._decide_nodes()
        self._decide_connections()
        self._allocate()
        self.excl_attrs = []
        root = ET.Element("Model", name=_safe_name(self.g["source"]["drawing_number"]),
                          uri="urn:hazop:dexpi-export:" + _safe_name(self.g["source"]["drawing_number"]))
        for prefix in ("Core", "Plant"):
            _el(root, "Import", prefix=prefix, source=MODEL_SOURCE[prefix])
        em = _obj(root, "Core/EngineeringModel")
        pm = _obj(_components(em, "ConceptualModel"), "Plant/PlantModel", self.ids.take("PlantModel1", "PlantModel", keep=True))
        meta = _obj(_components(pm, "MetaData"), "Plant/Diagram.PlantMetaData", self.ids.take("PlantMetaData1", "PlantMetaData", keep=True))
        title = (self.ex or {}).get("drawing", {}).get("title") if self.ex else None
        if title:
            _data(meta, "DrawingName", title)
        _data(meta, "DrawingNumber", self.g["source"]["drawing_number"])

        equip = [eid for eid, p in self.plan.items() if p["group"] == "equipment"]
        if equip:
            tagged = _components(pm, "TaggedPlantItems")
        pipes = self._connections()  # 노드·노즐 배정을 끝낸 뒤 설비를 쓴다
        for eid in equip:
            self._equipment(tagged, eid)
        self._piping(pm, pipes)
        instr = self._instrumentation(pm)
        self._diagram(em, pm)
        ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode")
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n").encode("utf-8")
        return self._finish(xml, pipes, instr)

    def _connections(self):
        used, out = {}, []
        for c in self.pending_conn:
            a, b = (c["dst"], c["src"]) if c["swap"] else (c["src"], c["dst"])
            si, sn = self._end(a["node"], a.get("port"), used)
            ti, tn = self._end(b["node"], b.get("port"), used)
            seg = c["seg"]
            dexpi_seg = "dexpi:segment" in seg["attributes"]
            out.append({"id": self.ids.take(seg["source_object_id"] if dexpi_seg else seg["entity_id"], "Pipe", keep=dexpi_seg),
                        "seg": seg, "src": (si, sn), "dst": (ti, tn),
                        "src_e": a["node"], "dst_e": b["node"], "swapped": c["swap"]})
        return out

    def _equipment(self, parent, eid):
        n, p = self.nodes[eid], self.plan[eid]
        if p.get("raw") is not None:
            parent.append(copy.deepcopy(p["raw"]))
            return
        o = _obj(parent, "Plant/ProcessEquipment." + p["cls"], p["id"])
        attrs = n["attributes"]
        chambers = _loads(attrs.get("dexpi:chambers"))
        if not chambers:
            one = {}
            for ours, theirs in CHAMBER_ATTRS.items():
                if attrs.get(ours):
                    one[theirs] = attrs[ours]
            chambers = [one] if one else []
        if chambers:
            comp = _components(o, "Chambers")
            for ch in chambers:
                co = _obj(comp, "Plant/ProcessEquipment.Chamber", self.ids.take(None, "Chamber"))
                for k, v in sorted(ch.items()):
                    self._attribute(co, n, k, v)
        table = self.noz.get(eid) or {}
        if table:
            comp = _components(o, "Nozzles")
            for port, z in table.items():
                no = _obj(comp, "Plant/ProcessEquipment." + (z["cls"] if dexpi_map.is_known(z["cls"]) else "ProcessNozzle"), z["id"])
                _data(no, "SubTagName", z["port"])
                for k, v in sorted(z["attrs"].items()):
                    if k != "SubTagName":
                        self._attribute(no, n, k, v)
                nodes = _components(no, "Nodes")
                _obj(nodes, "Plant/Piping.PipingNode", z["node"])
        if n["tag"]:
            _data(o, "TagName", n["tag"])
        self._extra_attributes(o, n, skip=set(CHAMBER_ATTRS))

    def _attribute(self, parent, node, name, value):
        if not valid_name(name) or value in (None, ""):
            return
        if isinstance(value, str) and value.startswith("{"):
            self.excl_attrs.append({"entity_id": node["entity_id"], "attribute": "dexpi:" + name, "reason": "no_dexpi_slot"})
            return
        _data(parent, name, str(value))

    def _extra_attributes(self, o, n, skip=()):
        """우리 속성 가운데 DEXPI 속성으로 되돌릴 수 있는 것은 쓰고, 나머지는 뺀 속성으로 적는다(곁 파일에는 전부 있다)."""
        for k, v in sorted(n["attributes"].items()):
            if k in HANDLED_ATTRS or k in skip:
                continue
            if k.startswith("dexpi:"):
                self._attribute(o, n, k[6:], v)
            elif k == "set_pressure" and self.plan[n["entity_id"]]["cls"] in ("SafetyValveOrFitting",) and quantity_to_dexpi(str(v)):
                self._attribute(o, n, "SetPressureHigh", v)
            elif v not in (None, ""):
                self.excl_attrs.append({"entity_id": n["entity_id"], "attribute": k, "reason": "no_dexpi_slot"})

    # ----- 배관
    def _piping(self, pm, pipes):
        in_seg = {}  # 항목 -> 처음 닿는 연결의 구간 키
        groups = {}
        for pipe in pipes:
            seg = pipe["seg"]
            key = self._segment_key(seg)
            groups.setdefault(key, []).append(pipe)
            for e in (pipe["src_e"], pipe["dst_e"]):
                if self.plan[e]["group"] != "equipment":
                    in_seg.setdefault(e, key)
        loose = [e for e, p in self.plan.items() if p["group"] in ("piping", "offpage") and e not in in_seg]
        systems = {}
        order = []
        for key in groups:
            systems.setdefault(key[0], []).append(key)
        if loose:
            systems.setdefault("", []).append(("", "orphans", "", "", "", ""))
            groups[("", "orphans", "", "", "", "")] = []
            for e in loose:
                in_seg[e] = ("", "orphans", "", "", "", "")
        if not groups:
            return
        comp = _components(pm, "PipingNetworkSystems")
        seg_no = 0
        for sysk, keys in systems.items():
            so = _obj(comp, "Plant/Piping.PipingNetworkSystem", self.ids.take(None, "System"))
            first = keys[0]
            if sysk:
                _data(so, "LineNumber", sysk)
            fluid, klass = first[2], first[3]
            if fluid and all(k[2] == fluid for k in keys):
                _data(so, "FluidCode", fluid)
            if klass and all(k[3] == klass for k in keys):
                _data(so, "PipingClassCode", klass)
            segs = _components(so, "Segments")
            for key in keys:
                seg_no += 1
                go = _obj(segs, "Plant/Piping.PipingNetworkSegment", self.ids.take(None, "Segment"))
                if key[2]:
                    _data(go, "FluidCode", key[2])
                if key[3]:
                    _data(go, "PipingClassCode", key[3])
                if key[4]:
                    _data(go, "NominalDiameterRepresentation", key[4])
                if key[5]:  # 한 방향·양방향 구분만 있다. 향하는 쪽은 DEXPI에 자리가 없다(§5.4)
                    flow = _el(go, "Data", property="FlowDirection")
                    _el(flow, "DataReference", data="Plant/Enumerations.PipingNetworkSegmentFlowClassification.%s"
                        % ("DualFlowPipingNetworkSegment" if key[5] == "dual" else "SingleFlowPipingNetworkSegment"))
                _data(go, "SegmentNumber", "S%d" % seg_no)
                items = [e for e, k in in_seg.items() if k == key]
                if items:
                    ic = _components(go, "Items")
                    for e in items:
                        self._piping_item(ic, e)
                conns = groups[key]
                if conns:
                    cc = _components(go, "Connections")
                    for pipe in conns:
                        po = _obj(cc, "Plant/Piping.Pipe", pipe["id"])
                        _refs(po, "SourceItem", pipe["src"][0])
                        _refs(po, "SourceNode", pipe["src"][1])
                        _refs(po, "TargetItem", pipe["dst"][0])
                        _refs(po, "TargetNode", pipe["dst"][1])

    def _segment_key(self, seg):
        a = seg["attributes"]
        flow = "dual" if a.get("flow_class") == "dual" else "single" if (seg.get("flow_direction") or a.get("flow_class") == "single") else ""
        return (seg.get("line_no") or "", a.get("dexpi:segment") or "", a.get("fluid_code") or "", a.get("pipe_class") or "",
                a.get("nominal_diameter") or "", flow)

    def _piping_item(self, parent, eid):
        n, p = self.nodes[eid], self.plan[eid]
        if p.get("raw") is not None:
            parent.append(copy.deepcopy(p["raw"]))
            return
        o = _obj(parent, "Plant/Piping." + p["cls"], p["id"])
        count = 3 if p["cls"] == "PipeTee" else 1 if p["group"] == "offpage" else 2
        ids = self.node_ids.setdefault(eid, [])
        while len(ids) < count:
            ids.append(self.ids.take("%s_Node%d" % (p["id"], len(ids) + 1), "Node"))
        nodes = _components(o, "Nodes")
        for nid in ids:
            _obj(nodes, "Plant/Piping.PipingNode", nid)
        if p["group"] == "offpage":
            ref = _components(o, "ConnectorReference")
            ro = _obj(ref, "Plant/Piping.PipeOffPageConnectorReferenceByNumber")
            a = n["attributes"]
            if a.get("to_object"):
                _data(ro, "ReferencedConnectorNumber", a["to_object"])
            if a.get("to_drawing"):
                _data(ro, "ReferencedDrawingNumber", a["to_drawing"])
        elif n["tag"]:
            _data(o, "PipingComponentNumber", n["tag"])
        self._extra_attributes(o, n)

    # ----- 계장
    def _instrumentation(self, pm):
        pifs = [eid for eid, p in self.plan.items() if p["group"] == "instrument"]
        valves = {}
        flows = []
        for e in self.g["edges"]:
            if e["kind"] in ("measurement_connection", "signal_connection"):
                a, b = e["nodes"]
                ok = a in self.plan and b in self.plan
                if not ok:
                    self.excl_conn.append({"entity_id": e["entity_id"], "reason": "endpoint_excluded", "kind": e["kind"]})
                    continue
                flows.append((e, a, b))
        sens, scf = {}, []
        self.psgf_of = {}
        for e, a, b in flows:
            if e["kind"] == "measurement_connection":
                inst, loc = (b, a) if b in pifs else (a, b) if a in pifs else (None, None)
                if inst is None or self.plan[loc]["group"] not in ("piping", "offpage"):
                    self.excl_conn.append({"entity_id": e["entity_id"], "reason": "sensing_location_not_piping_component", "kind": e["kind"]})
                    continue
                sens.setdefault(inst, []).append((e, loc))
            else:
                src, dst = a, b
                if src not in pifs:
                    self.excl_conn.append({"entity_id": e["entity_id"], "reason": "signal_end_not_instrument_or_actuator", "kind": e["kind"]})
                    continue
                if dst in pifs:
                    scf.append((e, src, dst, None))
                elif self.nodes[dst]["kind"] in VALVE_KINDS:
                    valves[dst] = valves.get(dst) or self.ids.take(None, "ActuatingSystem")
                    scf.append((e, src, dst, valves[dst]))
                else:
                    self.excl_conn.append({"entity_id": e["entity_id"], "reason": "signal_end_not_instrument_or_actuator", "kind": e["kind"]})
        for eid, n in self.nodes.items():  # 구동계는 구동 밸브마다 낸다
            if eid in self.plan and n["kind"] in dexpi_map.ACTUATED_KINDS and eid not in valves:
                valves[eid] = self.ids.take(None, "ActuatingSystem")
        if pifs:
            comp = _components(pm, "ProcessInstrumentationFunctions")
            for eid in pifs:
                self._pif(comp, eid, sens.get(eid, []), [x for x in scf if x[1] == eid])
        if valves:
            comp = _components(pm, "ActuatingSystems")
            for eid, asid in valves.items():
                self._actuating_system(comp, eid, asid)
            fcomp = _components(pm, "ActuatingFunctions")
            for eid, asid in valves.items():
                fo = _obj(fcomp, "Plant/Instrumentation.ActuatingFunction", self._af(asid))
                _refs(fo, "Systems", asid)
        return {"pifs": pifs, "valves": valves}

    @staticmethod
    def _af_id(asid):
        return "HZ_AF_" + (asid[3:] if asid.startswith("HZ_") else asid)

    def _af(self, asid):
        af = self._af_id(asid)
        self.ids.used.add(af)
        return af

    def _pif(self, parent, eid, sensing, signals):
        n, p = self.nodes[eid], self.plan[eid]
        o = _obj(parent, "Plant/Instrumentation.ProcessInstrumentationFunction", p["id"])
        a, isa = n["attributes"], n.get("isa") or {}
        cat = a.get("dexpi:ProcessInstrumentationFunctionCategory") or isa.get("measured_variable")
        num = a.get("dexpi:ProcessInstrumentationFunctionNumber") or (
            (isa.get("loop_no") or "") + (isa.get("suffix") or "") if isa.get("loop_no") else None)
        fn = a.get("dexpi:ProcessInstrumentationFunctions") or isa.get("functions")
        if cat:
            _data(o, "ProcessInstrumentationFunctionCategory", cat)
        if num:
            _data(o, "ProcessInstrumentationFunctionNumber", num)
        if fn:
            _data(o, "ProcessInstrumentationFunctions", fn)
        if not (cat and num):
            self.excl_attrs.append({"entity_id": eid, "attribute": "tag", "reason": "tag_not_isa_form"})
            self.approx.append({"entity_id": eid, "reason": "instrument_tag_not_isa_form", "tag": n["tag"]})
            if n["tag"]:
                _data(o, "ProcessInstrumentationFunctionNumber", n["tag"])
        if sensing:
            comp = _components(o, "ProcessSignalGeneratingFunctions")
            for e, loc in sensing:
                po = _obj(comp, "Plant/Instrumentation.ProcessSignalGeneratingFunction", self.ids.take(None, "SignalGenerating"))
                _refs(po, "SensingLocation", self.plan[loc]["id"])
                self.psgf_of[e["entity_id"]] = po.get("id")
        flows = _components(o, "SignalConveyingFunctions") if (sensing or signals) else None
        for e, loc in sensing:
            mo = _obj(flows, "Plant/Instrumentation.MeasuringLineFunction", self.ids.take(e.get("source_object_id"), "MeasuringLine"))
            _refs(mo, "Source", self.psgf_of[e["entity_id"]])
            _refs(mo, "Target", p["id"])
        for e, src, dst, asid in signals:
            so = _obj(flows, "Plant/Instrumentation.SignalConveyingFunction", self.ids.take(e.get("source_object_id"), "SignalLine"))
            _refs(so, "Source", p["id"])
            _refs(so, "Target", self.plan[dst]["id"] if asid is None else self._af_id(asid))
        self._extra_attributes(o, n, skip={"set_pressure"})

    def _actuating_system(self, parent, eid, asid):
        n, p = self.nodes[eid], self.plan[eid]
        o = _obj(parent, "Plant/Instrumentation.ActuatingSystem", asid)
        num = n["attributes"].get("dexpi:ActuatingSystemNumber")
        if num:
            _data(o, "ActuatingSystemNumber", num)
        fp = n["attributes"].get("fail_position")
        ca = _obj(_components(o, "ControlledActuator"), "Plant/Instrumentation.ControlledActuator", self.ids.take(None, "ControlledActuator"))
        if fp in dexpi_map.FAIL_ACTION_BACK:
            d = _el(ca, "Data", property="FailAction")
            _el(d, "DataReference", data="Plant/Enumerations.FailActionClassification." + dexpi_map.FAIL_ACTION_BACK[fp])
        elif fp:
            self.excl_attrs.append({"entity_id": eid, "attribute": "fail_position", "reason": "no_dexpi_value", "value": fp})
        if fp == "FL":
            self.approx.append({"entity_id": eid, "reason": "fail_action_approximate", "value": "FL", "dexpi_value": "FailRetainPosition"})
        if n["kind"] not in dexpi_map.ACTUATED_KINDS:
            self.approx.append({"entity_id": eid, "reason": "actuating_system_added_for_signal_line", "kind": n["kind"]})
        ref = _obj(_components(o, "OperatedValveReference"), "Plant/Instrumentation.OperatedValveReference")
        _refs(ref, "Valve", p["id"])

    # ----- 그림 위치
    def _diagram(self, em, pm):
        for eid, n in self.nodes.items():
            if eid not in self.plan or not n.get("position"):
                continue
            ids = [z["node"] for z in (self.noz.get(eid) or {}).values()] + self.node_ids.get(eid, [])
            for nid in ids:
                self.positions.setdefault(nid, self._xy(n["position"]))
        if not self.positions:
            return
        diag = _obj(_components(em, "Diagram"), "Core/Diagram.Diagram")
        groups = _components(diag, "Groups")
        border = _obj(groups, "Core/Diagram.Border")
        elements = _components(border, "Elements")
        line = _obj(elements, "Core/Diagram.PolyLine")
        pts = _el(line, "Data", property="Points")
        for x, y in ((1.0, 1.0), (A3[0] - 1.0, A3[1] - 1.0)):
            agg = _el(pts, "AggregatedDataValue", type="Core/Diagram.Point")
            for prop, v in (("X", x), ("Y", y)):
                _el(_el(agg, "Data", property=prop), "Double").text = repr(v)
        group = _obj(groups, "Core/Diagram.RepresentationGroup")
        node_pos = _components(group, "NodePositions")
        for nid in sorted(self.positions, key=lambda x: (len(x), x)):
            po = _obj(node_pos, "Plant/Diagram.PipingNodePosition", self.ids.take("Pos_" + (nid[3:] if nid.startswith("HZ_") else nid), "NodePosition"))
            _refs(po, "Node", nid)
            d = _el(po, "Data", property="Position")
            agg = _el(d, "AggregatedDataValue", type="Core/Diagram.Point")
            for prop, v in (("X", self.positions[nid][0]), ("Y", self.positions[nid][1])):
                _el(_el(agg, "Data", property=prop), "Double").text = repr(float(v))
        _refs(group, "Represents", pm.get("id"))
        _refs(diag, "Represents", pm.get("id"))

    # ----- 5. 검사·곁 파일
    def _finish(self, xml, pipes, instr):
        root = dexpi_read.parse_safely(xml)
        problems = [("스키마 규칙", x) for x in dexpi_read.check_structure(root)]
        for o in root.iter("Object"):
            if not dexpi_map.type_is_known(o.get("type", "")):
                problems.append(("클래스 목록", "2.0.1 클래스 목록에 없음: %s" % o.get("type")))
        problems += [("참조", x) for x in dexpi_read.check_references(root)]
        exported = [e for e, p in self.plan.items()]
        try:
            re_ex, _ = dexpi_import.extract_bytes(xml, self.name + ".dexpi.xml")
        except dexpi_read.DexpiError as exc:
            problems.append(("되읽기", exc.reason))
            re_ex = None
        if re_ex is not None:
            want_tags = sorted(self.nodes[e]["tag"] or "" for e in exported if self.nodes[e]["kind"] not in dexpi_map.INSTRUMENT_KINDS
                               and self.plan[e]["group"] != "offpage")
            got_tags = sorted(n["tag"] or "" for n in re_ex["nodes"] if n["category"] != "instrument"
                              and not (n["kind"] == "continuation"))
            if len(re_ex["nodes"]) != len(exported):
                problems.append(("되읽기", "구성요소 수 %d != 내보낸 %d" % (len(re_ex["nodes"]), len(exported))))
            n_phys = sum(1 for r in re_ex["relations"] + re_ex["unresolved_connectors"] if r["kind"] == "physical_connection")
            if n_phys != len(pipes):
                problems.append(("되읽기", "배관 연결 수 %d != 내보낸 %d" % (n_phys, len(pipes))))
            if want_tags != got_tags:
                problems.append(("되읽기", "태그 목록이 다름"))
        if problems:
            raise ExportError(["%s: %s" % p for p in problems[:20]])
        sha = hashlib.sha256(xml).hexdigest()
        entities = []
        for eid, p in self.plan.items():
            n = self.nodes[eid]
            entities.append({"dexpi_id": p["id"], "dexpi_class": p["cls"], "entity_id": eid, "local_id": n["local_id"],
                             "kind": n["kind"], "tag": n["tag"], "origin": n["origin"], "human_edit": n.get("human_edit"),
                             "attributes": n["attributes"]})
        flows = []
        for pipe in pipes:
            seg = pipe["seg"]
            flows.append({"dexpi_id": pipe["id"], "entity_id": seg["entity_id"], "local_id": seg["local_id"],
                          "line_no": seg.get("line_no"), "swapped": pipe["swapped"], "flow_direction": seg.get("flow_direction"),
                          "attributes": seg.get("attributes")})
        sidecar = {"schema": SIDECAR_SCHEMA, "exporter_version": EXPORTER_VERSION, "dexpi_version": dexpi_map.DEXPI_VERSION,
                   "attribution": dexpi_map.ATTRIBUTION, "dexpi_sha256": sha, "graph_id": self.g["graph_id"],
                   "graph_version": self.g["graph_version"], "drawing_number": self.g["source"]["drawing_number"],
                   "extraction_run_id": self.g["source"].get("extraction_run_id"), "scale": self.sc,
                   "entities": entities, "pipes": flows, "check_directions": self.check_dirs,
                   "unknowns": self.g["validation"]["unknowns"]}
        flow_n = sum(1 for f in flows if f["flow_direction"])
        # '이대로 확인'으로 확정한 미분류 기호처럼 뺀 구성요소 때문에 끊긴 배관·계장선(INTENT §3.2: 빼고 내보내며 수를 적는다)
        cut = {"pipes": sum(1 for c in self.excl_conn if c["reason"] == "endpoint_excluded" and "excluded_ends" in c),
               "signal_lines": sum(1 for c in self.excl_conn if c["reason"] == "endpoint_excluded" and "excluded_ends" not in c)}
        excluded = {"schema": EXCLUDED_SCHEMA, "drawing_number": self.g["source"]["drawing_number"],
                    "graph_version": self.g["graph_version"], "dexpi_version": dexpi_map.DEXPI_VERSION,
                    "excluded_components": self.excl_nodes, "excluded_connections": self.excl_conn,
                    "excluded_attributes": self.excl_attrs, "approximations": self.approx, "cut_by_excluded": cut,
                    "notes": ([{"reason": "flow_direction_has_no_dexpi_slot", "count": flow_n}] if flow_n else [])}
        stats = {"components": len(exported), "connections": len(pipes), "excluded_components": len(self.excl_nodes),
                 "excluded_connections": len(self.excl_conn), "excluded_attributes": len(self.excl_attrs),
                 "approximations": len(self.approx), "cut_pipes": cut["pipes"], "cut_signal_lines": cut["signal_lines"],
                 "bytes": len(xml), "dexpi_sha256": sha}
        return Export(self.name, xml, excluded, sidecar, stats)


_PREFIX = {"equipment": "Equipment", "piping": "Piping", "offpage": "OffPage", "instrument": "ProcessInstrumentationFunction"}


def _loads(text):
    if not text:
        return []
    try:
        v = json.loads(text)
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


# ---------------------------------------------------------------- 파일 쓰기와 묶음
def write_drawing(export, out_dir):
    """한 도면의 파일 셋을 out_dir에 바로 쓴다. 쓰다가 실패하면 이미 쓴 것을 지운다. 반환 {종류: 경로}.
    export_names는 이것으로 임시 폴더에 쓴 뒤 바꿔 넣는다(앞 내보내기를 잃지 않게)."""
    os.makedirs(out_dir, exist_ok=True)
    written = {}
    try:
        for fname, data in sorted(export.files.items()):
            path = os.path.join(out_dir, fname)
            store_io.write_bytes(path, data)
            written[fname.split(".", 1)[1]] = path
    except OSError:
        for path in written.values():
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return written


def default_confirmation():
    """내보내기가 쓰는 '쪽 확정' 함수 `sheet_confirmation(name) -> {"state": "open"|"ready"|"confirmed", "unconfirmed": [...],
    "unplaced": [...], …}`(화면 규격 §10.7, 단위 V3, `hazop/extract/confirmation.py`). 아직 없으면 None."""
    try:
        from hazop.extract import confirmation
    except ImportError:
        return None
    return getattr(confirmation, "sheet_confirmation", None)


def _gate(confirmation):
    """confirmation 인자 -> (함수 또는 None, 이름). 'auto'는 V3의 함수, 'assume'은 개발·시험용으로 모두 확정으로 본다."""
    if confirmation == "assume":
        return (lambda name: {"state": "confirmed", "unconfirmed": [], "unplaced": []}), "assumed"
    if confirmation == "auto":
        return default_confirmation(), "sheet_confirmation"
    return confirmation, "injected"


def _engine(gate):
    """gate가 엔진의 sheet_confirmation이면 그 모듈(hazop.extract.confirmation), 아니면 None(주입한 함수·assume)."""
    try:
        from hazop.extract import confirmation
    except ImportError:
        return None
    return confirmation if gate is not None and gate is getattr(confirmation, "sheet_confirmation", None) else None


def _state(gate, name):
    """쪽 확정 상태와 남은 미확인 수. 추출 결과가 없거나 깨진 파일이면 상태 'error'(내보내지 않음)."""
    try:
        res = gate(name) or {}
    except (OSError, ValueError):  # sheet_confirmation: 추출 결과 없음(FileNotFoundError)·깨진 파일(ValueError)
        return "error", 0
    return res.get("state"), len(res.get("unconfirmed") or []) + len(res.get("unplaced") or [])


def _confirmed_graph(cf, name, disk_graph):
    """엔진의 쪽 확정으로 내보낼 때: 확정을 판정한 바로 그 세 파일 바이트(추출 결과·사람 수정·AI 후보)로 그래프를 만든다.
    디스크의 graph.json은 AI 후보 수락처럼 그래프를 다시 만들지 않는 저장 뒤에 낡을 수 있어 내용으로 쓰지 않는다.
    반환 (상태, 남은 미확인 수, 그래프 또는 None, 원본 추출 결과, 지문, 사유, 디스크 graph.json과 달라 다시 만들었는가).
    그래프를 만들 수 없으면 상태 'graph_error'."""
    from hazop.graph import build
    try:
        st, original, corrected = cf.load_sheet(name)
    except (OSError, ValueError):
        return "error", 0, None, None, None, None, False
    left = len(st.get("unconfirmed") or []) + len(st.get("unplaced") or [])
    if st["state"] != "confirmed":
        return st["state"], left, None, None, None, None, False
    try:
        graph = build.build_graph(corrected, extraction_file=paths.rel_or_abs(cf.extraction_path(name), paths.work_root()))
    except Exception as exc:  # noqa: BLE001 - 어떤 이유로든 다시 만들 수 없으면 그 쪽만 내보내지 않고 사유를 적는다
        return "graph_error", left, None, None, st["fingerprint"], "확정한 자료로 그래프를 다시 만들 수 없음(%s)" % exc, False
    rebuilt = disk_graph is None or disk_graph.get("graph_version") != graph.get("graph_version")
    return "confirmed", left, graph, original, st["fingerprint"], None, rebuilt


def list_exportable(graph_root=None, extract_root=None, confirmation="auto"):
    """화면의 내보내기 대상 목록. output/graph 아래 도면마다 {name, drawing_number, confirmed(도면 번호를 등록에서 사람이 확정했는가),
    graph_ok(그래프 구조 검증 통과), state(쪽 확정 상태 open·ready·confirmed, 함수가 없으면 None), unconfirmed(남은 미확인 수),
    exportable(셋 다 통과), why(내보낼 수 없는 사유 목록)}. 파일을 쓰지 않는다."""
    graph_root = graph_root or paths.output_root("graph")
    extract_root = extract_root or paths.output_root("extract")
    gate, _ = _gate(confirmation)
    rows = []
    if not os.path.isdir(graph_root):
        return rows
    for name in sorted(os.listdir(graph_root)):
        gp = os.path.join(graph_root, name, "graph.json")
        if not os.path.isfile(gp):
            continue
        try:
            graph = _read_json(gp)
            ep = os.path.join(extract_root, name, "extraction.json")
            extraction = _read_json(ep) if os.path.isfile(ep) else None
        except (OSError, ValueError) as exc:
            rows.append({"name": name, "drawing_number": None, "confirmed": False, "graph_ok": False, "state": None,
                         "unconfirmed": 0, "exportable": False, "why": ["그래프를 읽을 수 없음: %s" % exc]})
            continue
        dwg = graph.get("source", {}).get("drawing_number")
        confirmed = bool(extraction) and (extraction.get("drawing") or {}).get("identification_basis") == "registration_confirmed"
        graph_ok = graph.get("validation", {}).get("status") == "passed"
        why = []
        state, left = (None, 0)
        if gate is None:
            why.append("쪽 확정 함수(sheet_confirmation, 화면 규격 V3)가 아직 없음")
        else:
            state, left = _state(gate, name)
            if state != "confirmed":
                why.append("쪽이 확정되지 않음(%s, 남은 미확인 %d)" % (state, left))
        if not graph_ok:
            why.append("그래프가 구조 검증을 통과하지 못함")
        if not dwg:
            why.append("도면 번호가 없음")
        elif not confirmed:
            why.append("도면 번호가 등록에서 확정되지 않음")
        rows.append({"name": name, "drawing_number": dwg, "confirmed": confirmed, "graph_ok": graph_ok, "state": state,
                     "unconfirmed": left, "exportable": not why, "why": why})
    return rows


def export_names(names, out_dir, graph_root=None, extract_root=None, require_confirmed_number=True, now=None,
                 confirmation="auto", overwrite=False):
    """화면이 부를 진입 함수. output/graph 아래 도면 이름들 가운데 **쪽 확정이 `confirmed`인 것만** 내보내 out_dir에 쓴다
    (HZ-PLN-22 §6.1). 확정 전 쪽은 쓰지 않고 `manifest.json`의 `not_exported`에 상태와 남은 미확인 수를 적는다. 확정된 쪽이 하나도
    없거나, 확정된 쪽 하나라도 검사(§6.5)에 걸리면 아무 파일도 쓰지 않고 ExportError(reasons에 도면별 사유)를 던진다.
    names가 None이면 graph_root 아래 graph.json이 있는 모든 도면. confirmation: 'auto'(V3의 sheet_confirmation, 없으면 ExportError),
    'assume'(개발·시험용으로 모두 확정으로 봄), 또는 함수(name) -> {"state", "unconfirmed", "unplaced"}.
    'auto'(엔진의 쪽 확정)이면 내보내는 그래프는 디스크의 graph.json이 아니라 확정을 판정한 세 파일로 그 자리에서 만든 것이고,
    쓰기 직전에 세 파일 지문이 그대로인지 다시 본다(바뀌었으면 그 쪽은 not_exported).
    쓸 파일이 out_dir에 이미 있으면 overwrite가 참일 때만 덮는다(아니면 쓰지 않고 status 'exists'와 그 파일 목록을 돌려줌).
    파일은 out_dir 안 임시 폴더에 모두 쓴 뒤 바꿔 넣는다. 쓰기·바꿔 넣기가 실패하면 앞 내보내기 파일을 되돌려 두고 OSError.
    반환: {"status": "written"|"exists", "manifest": 경로 또는 None, "existing": [파일 이름], "drawings": [{name, drawing_number,
    files, graph_version, graph_rebuilt, source_fingerprint, stats}], "not_exported": [{name, drawing_number, state, unconfirmed,
    reason?}]}."""
    graph_root = graph_root or paths.output_root("graph")
    extract_root = extract_root or paths.output_root("extract")
    gate, gate_name = _gate(confirmation)
    if gate is None:
        raise ExportError(["쪽 확정 함수(sheet_confirmation, 화면 규격 V3)가 아직 없어 내보내지 못함"])
    cf = _engine(gate)
    if names is None:
        names = sorted(d for d in os.listdir(graph_root) if os.path.isfile(os.path.join(graph_root, d, "graph.json")))
    exports, errors, not_exported, sources = [], [], [], {}
    for name in names:
        gp = os.path.join(graph_root, name, "graph.json")
        disk = _read_json(gp) if os.path.isfile(gp) or cf is None else None
        dwg = (disk or {}).get("source", {}).get("drawing_number")
        if cf is not None:
            state, left, graph, extraction, fp, why, rebuilt = _confirmed_graph(cf, name, disk)
        else:
            (state, left), graph, fp, why, rebuilt = _state(gate, name), disk, None, None, False
            ex_path = os.path.join(extract_root, name, "extraction.json")
            extraction = _read_json(ex_path) if state == "confirmed" and os.path.isfile(ex_path) else None
        if state != "confirmed":
            row = {"name": name, "drawing_number": dwg, "state": state, "unconfirmed": left}
            if why:
                row["reason"] = why
            not_exported.append(row)
            continue
        try:
            ex = export_drawing(graph, extraction, require_confirmed_number=require_confirmed_number)
        except ExportError as exc:
            errors.append("%s: %s" % (name, "; ".join(exc.reasons)))
            continue
        exports.append((name, ex))
        sources[name] = (fp, rebuilt)
    if errors:
        raise ExportError(errors)
    if not exports:
        raise ExportError(["확정된 쪽이 하나도 없어 내보낼 것이 없음: " + ", ".join(
            "%s(%s, 남은 미확인 %d)" % (x["name"], x["state"], x["unconfirmed"]) for x in not_exported)])
    for name, ex in list(exports):  # 쓰기 직전에 다시 확인한다(그 사이 세 파일이 바뀌면 확정이 풀린다)
        if cf is not None:
            try:
                st = cf.sheet_confirmation(name)
                state, left = st["state"], len(st.get("unconfirmed") or []) + len(st.get("unplaced") or [])
                if state == "confirmed" and st["fingerprint"] != sources[name][0]:
                    state = "changed"
            except (OSError, ValueError):
                state, left = "error", 0
        else:
            state, left = _state(gate, name)
        if state != "confirmed":
            exports.remove((name, ex))
            not_exported.append({"name": name, "drawing_number": ex.sidecar["drawing_number"], "state": state, "unconfirmed": left})
    if not exports:
        raise ExportError(["내보내기 직전에 쪽 확정이 모두 풀려 내보낼 것이 없음"])
    used = {}
    for name, ex in exports:  # 도면 번호가 같은 이름이 되면 파일이 겹친다. Windows 파일 이름은 대소문자를 가리지 않는다
        key = ex.name.casefold()
        if key in used:
            raise ExportError(["파일 이름이 겹침: %s(%s)와 %s(%s)" % (used[key][1], used[key][0], ex.name, name)])
        used[key] = (name, ex.name)
    fnames = [f for _, ex in exports for f in sorted(ex.files)] + ["manifest.json"]
    existing = [f for f in fnames if os.path.lexists(os.path.join(out_dir, f))]
    if existing and not overwrite:
        return {"status": "exists", "manifest": None, "existing": existing, "drawings": [], "not_exported": not_exported}
    drawings = []
    for name, ex in exports:
        fp, rebuilt = sources[name]
        drawings.append({"name": name, "drawing_number": ex.sidecar["drawing_number"], "files": sorted(ex.files),
                         "graph_version": ex.sidecar["graph_version"], "graph_rebuilt": rebuilt, "source_fingerprint": fp,
                         "stats": ex.stats})
    manifest = {"schema": MANIFEST_SCHEMA, "exporter_version": EXPORTER_VERSION, "dexpi_version": dexpi_map.DEXPI_VERSION,
                "attribution": dexpi_map.ATTRIBUTION, "exported_at": now or store_io.now_utc(), "confirmation": gate_name,
                "drawings": drawings, "not_exported": not_exported}
    os.makedirs(out_dir, exist_ok=True)
    stage = tempfile.mkdtemp(prefix=".hazop-dexpi-new-", dir=out_dir)
    try:
        for _name, ex in exports:
            write_drawing(ex, stage)
        store_io.write_json(os.path.join(stage, "manifest.json"), manifest)
        _swap_in(stage, out_dir, fnames)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {"status": "written", "manifest": os.path.join(out_dir, "manifest.json"), "existing": existing,
            "drawings": drawings, "not_exported": not_exported}


def _swap_in(stage, out_dir, fnames):
    """stage에 다 쓴 파일들을 out_dir로 옮긴다. 있던 파일은 먼저 옆 임시 폴더로 비켜 두고, 하나라도 옮기지 못하면 새 파일을 지우고
    비켜 둔 파일을 제자리로 돌린 뒤 OSError를 올린다(앞 내보내기를 잃지 않음)."""
    old = tempfile.mkdtemp(prefix=".hazop-dexpi-old-", dir=out_dir)
    moved_old, moved_new = [], []
    restored = True
    try:
        for f in fnames:
            if os.path.lexists(os.path.join(out_dir, f)):
                os.replace(os.path.join(out_dir, f), os.path.join(old, f))
                moved_old.append(f)
        for f in fnames:
            os.replace(os.path.join(stage, f), os.path.join(out_dir, f))
            moved_new.append(f)
    except OSError:
        for f in moved_new:
            try:
                os.remove(os.path.join(out_dir, f))
            except OSError:
                pass
        for f in moved_old:
            try:
                os.replace(os.path.join(old, f), os.path.join(out_dir, f))
            except OSError:
                restored = False
        raise
    finally:
        if restored:
            shutil.rmtree(old, ignore_errors=True)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
