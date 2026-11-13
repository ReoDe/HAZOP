"""DEXPI 파일(2.0 이후 DEXPI XML, 1.x Proteus XML)을 안전하게 읽어 같은 중간 형태(Model)로 만든다(HZ-PLN-22 §5).

이 모듈은 읽기만 하고 파일을 쓰거나 네트워크를 열지 않는다. 밖에서 온 XML이므로 §5.1을 지킨다.
- DTD·개체 선언(`<!DOCTYPE`, `<!ENTITY`)이 나오면 거절한다(사유 dexpi_doctype_forbidden). 외부 개체도 가져오지 않는다.
- `Import source=…` 같은 주소는 이름표로만 읽고 열지 않는다.
- 파일 크기·요소 수·깊이 한도를 넘으면 거절한다(dexpi_too_large).
등록의 형식 판별(hazop.register.fileinfo)도 `parse_safely`를 쓴다.

좌표는 모두 mm, 위가 0인 화면 좌표(y가 아래로 커짐)로 맞춘다. 2.0은 원래 그렇고(2.0.1 Reference P&ID의 표제란 글자가 y 291에 있고
칸 글자 A가 y 21에 있어 y 아래쪽 증가로 확인), Proteus는 y가 위로 커서 도면 높이에서 뺀다(같은 도면의 두 판에서 노드 y의 합이 297).
원래 값은 호출한 쪽이 필요하면 `raw_position`으로 되돌린다.
"""

import json
import math
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

from hazop.extract import dexpi_map

MAX_BYTES = 100 * 1024 * 1024
MAX_ELEMENTS = 3_000_000
MAX_DEPTH = 256
XML_FRAGMENT_LIMIT = 4096  # 근거로 남기는 원문 조각의 최대 길이(§5.5)

FMT_DEXPI = "dexpi_xml"
FMT_PROTEUS = "proteus"


class DexpiError(ValueError):
    """읽을 수 없는 파일. code는 사유 코드, reason은 사람이 읽을 문장."""

    def __init__(self, code, reason):
        ValueError.__init__(self, reason)
        self.code = code
        self.reason = reason


# ---------------------------------------------------------------- 안전한 XML 읽기
def parse_safely(data):
    """바이트 -> 뿌리 Element. 규칙은 모듈 머리말. 규칙을 어기거나 XML이 아니면 DexpiError."""
    if not isinstance(data, (bytes, bytearray)):
        raise DexpiError("dexpi_unreadable", "바이트가 아님")
    if len(data) > MAX_BYTES:
        raise DexpiError("dexpi_too_large", "파일이 너무 큼(%d바이트, 한도 %d바이트)" % (len(data), MAX_BYTES))
    parser = expat.ParserCreate()
    parser.buffer_text = True
    state = {"count": 0, "depth": 0, "root": None, "stack": []}

    def forbid(_name=None, *_args):
        raise DexpiError("dexpi_doctype_forbidden", "DTD·개체 선언이 든 파일은 읽지 않음")

    def start(name, attrs):
        state["count"] += 1
        state["depth"] += 1
        if state["count"] > MAX_ELEMENTS:
            raise DexpiError("dexpi_too_large", "요소가 너무 많음(한도 %d개)" % MAX_ELEMENTS)
        if state["depth"] > MAX_DEPTH:
            raise DexpiError("dexpi_too_large", "XML이 너무 깊음(한도 %d단계)" % MAX_DEPTH)
        el = ET.Element(name, attrs)
        if state["stack"]:
            state["stack"][-1].append(el)
        else:
            state["root"] = el
        state["stack"].append(el)

    def end(_name):
        state["depth"] -= 1
        state["stack"].pop()

    def text(chunk):
        if not state["stack"]:
            return
        top = state["stack"][-1]
        if len(top):
            last = top[-1]
            last.tail = (last.tail or "") + chunk
        else:
            top.text = (top.text or "") + chunk

    parser.StartDoctypeDeclHandler = forbid
    parser.EntityDeclHandler = forbid
    parser.ExternalEntityRefHandler = forbid
    parser.UnparsedEntityDeclHandler = forbid
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    try:
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        parser.Parse(bytes(data), True)
    except DexpiError:
        raise
    except expat.ExpatError as exc:
        raise DexpiError("dexpi_unreadable", "XML로 읽을 수 없음: %s" % exc)
    except (LookupError, ValueError) as exc:  # 알 수 없는 인코딩
        raise DexpiError("dexpi_unreadable", "XML로 읽을 수 없음: %s" % exc)
    if state["root"] is None:
        raise DexpiError("dexpi_unreadable", "XML 요소가 없음")
    return state["root"]


def detect(root):
    """뿌리 요소로 형식을 판별한다: (FMT_DEXPI, DEXPI 판) / (FMT_PROTEUS, DEXPI 판 — 없으면 Proteus 스키마 판) / None.
    FMT_*는 등록의 dexpi_flavor 값이다(HZ-PLN-22 §4.1)."""
    if root.tag == "Model":
        for imp in root.findall("Import"):
            m = re.search(r"/models/([0-9][0-9.]*)/", imp.get("source") or "")
            if m and (imp.get("prefix") in ("Plant", "Core") or "Plant" in (imp.get("source") or "")):
                return FMT_DEXPI, m.group(1)
        return None
    if root.tag == "PlantModel" and root.find("PlantInformation") is not None:
        info = root.find("PlantInformation")
        return FMT_PROTEUS, info.get("ApplicationVersion") or info.get("SchemaVersion")
    return None


# ---------------------------------------------------------------- 중간 형태
class Model:
    """두 형식을 같은 모양으로 담는 읽기 결과. 항목(items)은 파일 안 순서."""

    def __init__(self, fmt, version):
        self.fmt = fmt
        self.version = version
        self.application = None
        self.schema_version = None  # Proteus 스키마 판(예 4.1.1)
        self.drawing = {"number": None, "name": None, "width": None, "height": None}
        self.items = {}  # id -> 항목 dict(equipment·piping·offpage·instrument)
        self.nozzles = {}  # id -> {id, cls, parent, port, attrs, nodes, xml}
        self.node_owner = {}  # 노드 id -> (항목 id, 순번)
        self.connections = []  # {id, cls, source, source_node, target, target_node, segment, system}
        self.segments = {}  # id -> {id, system, attrs}
        self.systems = {}  # id -> {id, attrs}
        self.info_flows = []  # {id, cls, source, target}
        self.sensing = {}  # 측정 기능(ProcessSignalGeneratingFunction) id -> {item, pif}
        self.actuating = {}  # 구동 기능 id -> [구동계 id]
        self.act_systems = {}  # 구동계 id -> {id, valves, fail_action, number}
        self.arrows = []  # {segment, position, direction}
        self.node_pos = {}  # 노드 id -> (x, y)
        self.diagram_count = 0
        self.process_objects = 0
        self.issues = []  # {check, target, reason}
        self.duplicate_ids = []
        self.flip_height = None  # Proteus: y를 이 값에서 뺀다

    def issue(self, check, target, reason):
        self.issues.append({"check": check, "target": target, "reason": reason})


def _fragment(el):
    """객체의 원문 조각(그림 쪽 제외, 4KB까지). -> (문자열, 잘렸는가)"""
    clone = _strip_diagram(el)
    text = ET.tostring(clone, encoding="unicode")
    if len(text) > XML_FRAGMENT_LIMIT:
        return text[:XML_FRAGMENT_LIMIT], True
    return text, False


def _strip_diagram(el):
    out = ET.Element(el.tag, {k: v for k, v in el.attrib.items() if not k.startswith("_")})  # 읽기가 단 `_id` 표시는 뺀다
    out.text = el.text
    for child in el:
        if child.tag in ("Presentation", "Position", "Scale", "Extent", "CenterLine", "Label", "Text", "PolyLine",
                         "Circle", "Shape", "TextStringFormatSpecification", "ConnectionPoints"):
            continue
        if child.tag == "Object" and (child.get("type") or "").startswith("Core/Diagram."):
            continue
        out.append(_strip_diagram(child))
    out.tail = None
    return out


def _synthetic_id(parent_id, prop, index):
    """id가 없는 객체의 경로 ID(§5.2). DEXPI XML의 ID 글자 규칙을 지키도록 `/` 대신 `__`를 쓴다."""
    return re.sub(r"[^A-Za-z0-9_]", "_", "%s__%s_%d" % (parent_id or "model", prop or "item", index))


def _float(text):
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- DEXPI XML 2.0
def _data_value(data_el):
    """<Data property=…> 안의 값을 문자열로. 값이 없으면 None. 물리량은 '값 단위'."""
    for child in data_el:
        tag = child.tag
        if tag in ("String", "Double", "Integer", "Boolean", "DateTime"):
            text = (child.text or "").strip()
            return text if text != "" else None
        if tag == "DataReference":
            return child.get("data")
        if tag == "AggregatedDataValue":
            inner = {d.get("property"): _data_value(d) for d in child.findall("Data")}
            if child.get("type", "").endswith("PhysicalQuantity"):
                unit = (inner.get("Unit") or "").replace("/", ".").split(".")
                unit_text = ".".join(unit[-2:]) if len(unit) >= 2 else (inner.get("Unit") or "")
                return ("%s %s" % (inner.get("Value"), unit_text)).strip()
            return json.dumps(inner, ensure_ascii=False, sort_keys=True)
    return None


def _data_attrs(obj):
    attrs = {}
    for d in obj.findall("Data"):
        name = d.get("property")
        if not name:
            continue
        value = _data_value(d)
        if value is not None:
            attrs[name] = value
    return attrs


def _refs(obj, prop):
    out = []
    for r in obj.findall("References"):
        if r.get("property") == prop:
            out += [x.lstrip("#") for x in (r.get("objects") or "").split() if x]
    return out


def _children(obj, prop):
    """Components property=prop 안의 Object들."""
    out = []
    for c in obj.findall("Components"):
        if c.get("property") == prop:
            out += c.findall("Object")
    return out


def _point(data_el):
    """Data(Position)·Point 값 -> (x, y) 또는 None."""
    agg = data_el.find("AggregatedDataValue")
    if agg is None:
        return None
    vals = {d.get("property"): _float(_data_value(d)) for d in agg.findall("Data")}
    if vals.get("X") is None or vals.get("Y") is None:
        return None
    return (vals["X"], vals["Y"])


def _data_point(obj, prop="Position"):
    for d in obj.findall("Data"):
        if d.get("property") == prop:
            return _point(d)
    return None


def read_dexpi_xml(root, version):
    m = Model(FMT_DEXPI, version)  # Import의 주소는 열지 않는다. 판 번호는 detect가 이미 뽑았다
    objects = {}  # id -> Element

    def collect(obj, parent_id, prop, index, owner_path):
        oid = obj.get("id") or _synthetic_id(owner_path, prop, index)
        obj.set("_id", oid)
        if obj.get("id"):
            if oid in objects:
                m.duplicate_ids.append(oid)
            objects[oid] = obj
        for comp in obj.findall("Components"):
            for i, child in enumerate(comp.findall("Object")):
                collect(child, oid, comp.get("property"), i, oid)

    for i, top in enumerate(root.findall("Object")):
        collect(top, None, "Object", i, "model")

    for obj in _iter_objects(root):
        t = obj.get("type") or ""
        if t == "Core/Diagram.Diagram":
            m.diagram_count += 1
        elif t.startswith("Process/"):  # 공정 모델(Process)은 이번 범위 밖: 개수만 센다(§5.5)
            m.process_objects += 1

    # PlantModel 아래 구조
    for plant in _iter_objects(root):
        if (plant.get("type") or "") != "Plant/PlantModel":
            continue
        for comp in plant.findall("Components"):
            prop = comp.get("property")
            for obj in comp.findall("Object"):
                cls = dexpi_map.class_of(obj.get("type"))
                group = dexpi_map.group_of(cls) if dexpi_map.library_ready() else None
                if prop == "PipingNetworkSystems":
                    _read_system(m, obj)
                elif group == "equipment":
                    _read_equipment(m, obj)
                elif cls == "PlantMetaData" or prop == "MetaData":
                    a = _data_attrs(obj)
                    m.drawing["number"] = a.get("DrawingNumber")
                    m.drawing["name"] = a.get("DrawingName")
                elif group == "instrument" or prop == "ProcessInstrumentationFunctions":
                    _read_pif(m, obj)
                elif prop == "ActuatingSystems":
                    _read_act_system(m, obj)
    # ActuatingFunction과 정보 흐름은 어디에 있든 클래스로 모은다
    for obj in _iter_objects(root):
        cls = dexpi_map.class_of(obj.get("type"))
        if not (obj.get("type") or "").startswith("Plant/Instrumentation."):
            continue
        anc = dexpi_map.ancestry(cls)
        if "ActuatingFunction" in anc:
            m.actuating[obj.get("_id")] = _refs(obj, "Systems")
        if "SignalConveyingFunction" in anc:
            src = _refs(obj, "Source")
            tgt = _refs(obj, "Target")
            m.info_flows.append({"id": obj.get("_id"), "cls": cls, "source": src[0] if src else None,
                                 "target": tgt[0] if tgt else None})
        if "ProcessSignalGeneratingFunction" in anc:
            loc = _refs(obj, "SensingLocation")
            m.sensing[obj.get("_id")] = {"item": loc[0] if loc else None}
    _read_diagram(m, root, objects)
    return m


def _iter_objects(root):
    for el in root.iter("Object"):
        yield el


def _node_ids(obj):
    return [n.get("_id") for n in _children(obj, "Nodes")]


def _register_nodes(m, item_id, obj):
    ids = _node_ids(obj)
    for i, nid in enumerate(ids):
        m.node_owner[nid] = (item_id, i)
    return ids


def _read_equipment(m, obj):
    oid = obj.get("_id")
    cls = dexpi_map.class_of(obj.get("type"))
    frag, cut = _fragment(obj)
    attrs = _data_attrs(obj)
    chambers = [_data_attrs(c) for c in _children(obj, "Chambers")]
    item = {"id": oid, "cls": cls, "group": "equipment", "attrs": attrs, "nodes": [], "chambers": chambers,
            "nozzles": [], "xml": frag, "xml_cut": cut, "position": None, "has_id": bool(obj.get("id"))}
    m.items[oid] = item
    for noz in _children(obj, "Nozzles"):
        nid = noz.get("_id")
        nattrs = _data_attrs(noz)
        ncls = dexpi_map.class_of(noz.get("type"))
        nodes = _register_nodes(m, nid, noz)
        m.nozzles[nid] = {"id": nid, "cls": ncls, "parent": oid, "port": nattrs.get("SubTagName") or nid,
                          "attrs": nattrs, "nodes": nodes}
        item["nozzles"].append(nid)


def _read_system(m, obj):
    sid = obj.get("_id")
    sattrs = _data_attrs(obj)
    m.systems[sid] = {"id": sid, "attrs": sattrs}
    for seg in _children(obj, "Segments"):
        gid = seg.get("_id")
        m.segments[gid] = {"id": gid, "system": sid, "attrs": _data_attrs(seg)}
        for it in _children(seg, "Items"):
            iid = it.get("_id")
            cls = dexpi_map.class_of(it.get("type"))
            group = dexpi_map.group_of(cls)
            frag, cut = _fragment(it)
            nodes = _register_nodes(m, iid, it)
            item = {"id": iid, "cls": cls, "group": group or "piping", "attrs": _data_attrs(it), "nodes": nodes,
                    "segment": gid, "system": sid, "xml": frag, "xml_cut": cut, "position": None,
                    "has_id": bool(it.get("id")), "reference": _offpage_reference(it)}
            if iid in m.items:
                m.duplicate_ids.append(iid)
            m.items[iid] = item
        conns = []
        for idx, conn in enumerate(_children(seg, "Connections")):
            src, tgt = _refs(conn, "SourceItem"), _refs(conn, "TargetItem")
            sn, tn = _refs(conn, "SourceNode"), _refs(conn, "TargetNode")
            conns.append({"id": conn.get("id") or None, "synthetic_id": conn.get("_id"),
                          "cls": dexpi_map.class_of(conn.get("type")),
                          "source": src[0] if src else None, "source_node": sn[0] if sn else None,
                          "target": tgt[0] if tgt else None, "target_node": tn[0] if tn else None,
                          "segment": gid, "system": sid, "index": idx})
        items = [(i, it.get("_id")) for i, it in enumerate(_children(seg, "Items"))
                ]
        # 2.0은 구간 안 부품마다 연결이 따로 있다. 어느 연결의 끝에도 없는 부품만 Items 순서로 길에 끼운다(§5.7)
        m.connections.extend(_segment_paths(conns, items, explode=False))


def _offpage_reference(it):
    for ref in _children(it, "ConnectorReference"):
        a = _data_attrs(ref)
        return {"drawing": a.get("ReferencedDrawingNumber"), "connector": a.get("ReferencedConnectorNumber"),
                "object": (_refs(ref, "ReferencedObject") or [None])[0]}
    return None


def _read_pif(m, obj):
    oid = obj.get("_id")
    cls = dexpi_map.class_of(obj.get("type"))
    frag, cut = _fragment(obj)
    attrs = _data_attrs(obj)
    m.items[oid] = {"id": oid, "cls": cls, "group": "instrument", "attrs": attrs, "nodes": [], "xml": frag,
                    "xml_cut": cut, "position": None, "has_id": bool(obj.get("id"))}
    for psgf in _children(obj, "ProcessSignalGeneratingFunctions"):
        m.sensing.setdefault(psgf.get("_id"), {"item": None})["pif"] = oid
    # 안쪽에 둔 신호·측정선은 아래 클래스 훑기가 모은다


def _read_act_system(m, obj):
    sid = obj.get("_id")
    entry = {"id": sid, "valves": [], "fail_action": None, "number": _data_attrs(obj).get("ActuatingSystemNumber")}
    for ca in _children(obj, "ControlledActuator"):
        fa = _data_attrs(ca).get("FailAction")
        entry["fail_action"] = fa.rsplit(".", 1)[-1] if fa else None
    for ref in _children(obj, "OperatedValveReference"):
        entry["valves"] += _refs(ref, "Valve")
    m.act_systems[sid] = entry


def _arrow_direction(shape, rotation, mirrored):
    """흐름 화살표 모양(이등변 삼각형 윤곽)의 끝 방향 벡터(위가 0인 좌표). 모양을 알 수 없으면 None."""
    pts = None
    for el in shape.iter("Object"):
        if (el.get("type") or "") == "Core/Diagram.PolyLine":
            pts = [tuple(_float(_data_value(d)) for d in sorted(a.findall("Data"), key=lambda x: x.get("property")))
                   for a in next(d for d in el.findall("Data") if d.get("property") == "Points")
                   .findall("AggregatedDataValue")]
            break
    if not pts or len(pts) != 3 or any(None in p for p in pts):
        return None
    lens = [math.dist(pts[i], pts[(i + 1) % 3]) for i in range(3)]
    for apex in range(3):
        a, b = lens[apex - 1], lens[apex]  # 꼭짓점에 붙은 두 변
        if a > 1e-9 and abs(a - b) <= 1e-6 * max(a, b):
            others = [pts[(apex + 1) % 3], pts[(apex + 2) % 3]]
            mid = ((others[0][0] + others[1][0]) / 2.0, (others[0][1] + others[1][1]) / 2.0)
            vx, vy = pts[apex][0] - mid[0], pts[apex][1] - mid[1]
            n = math.hypot(vx, vy)
            if n < 1e-9:
                return None
            vx, vy = vx / n, vy / n
            if mirrored:
                vx = -vx
            th = math.radians(rotation or 0.0)
            return (vx * math.cos(th) - vy * math.sin(th), vx * math.sin(th) + vy * math.cos(th))
    return None


def _read_diagram(m, root, objects):
    """그림 쪽: 노드·설비 위치, 도면 크기, 흐름 화살표."""
    for obj in _iter_objects(root):
        t = obj.get("type") or ""
        if t == "Plant/Diagram.PipingNodePosition" or t == "Plant/Diagram.InstrumentationNodePosition":
            p = _data_point(obj)
            for nid in _refs(obj, "Node"):
                if p is not None:
                    m.node_pos[nid] = p
    for diag in _iter_objects(root):
        if (diag.get("type") or "") != "Core/Diagram.Diagram":
            continue
        _walk_groups(m, diag, objects, None)
        border = [o for o in diag.iter("Object") if (o.get("type") or "") == "Core/Diagram.Border"]
        if border:
            xs, ys = [], []
            for pl in border[0].iter("Object"):
                if (pl.get("type") or "") == "Core/Diagram.PolyLine":
                    for d in pl.findall("Data"):
                        if d.get("property") == "Points":
                            for a in d.findall("AggregatedDataValue"):
                                v = {x.get("property"): _float(_data_value(x)) for x in a.findall("Data")}
                                if v.get("X") is not None and v.get("Y") is not None:
                                    xs.append(v["X"])
                                    ys.append(v["Y"])
            if xs:
                m.drawing["width"], m.drawing["height"] = round(max(xs) + min(xs), 3), round(max(ys) + min(ys), 3)
        break
    # 항목 위치: 표현 묶음의 모양 위치 > 노드 위치 평균
    for iid, item in m.items.items():
        if item["position"] is None:
            pts = [m.node_pos[n] for n in item.get("nodes", []) if n in m.node_pos]
            for nz in item.get("nozzles", []):
                pts += [m.node_pos[n] for n in m.nozzles[nz]["nodes"] if n in m.node_pos]
            if pts:
                item["position"] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _walk_groups(m, group, objects, represents):
    """표현 묶음(RepresentationGroup)을 따라 내려가며 Represents 대상의 모양 위치와 화살표를 모은다."""
    rep = _refs(group, "Represents")
    current = rep[0] if rep else represents
    for el in group.findall("Components"):
        for child in el.findall("Object"):
            t = child.get("type") or ""
            if t == "Core/Diagram.ShapeUsage" and current in m.items and m.items[current]["position"] is None:
                m.items[current]["position"] = _data_point(child)
            if t == "Core/Diagram.PipeFlowArrow" and current in m.segments:
                for su in child.iter("Object"):
                    if (su.get("type") or "") == "Core/Diagram.ShapeUsage":
                        shape_id = (_refs(su, "Shape") or [None])[0]
                        shape = objects.get(shape_id)
                        rot = _float(next((_data_value(d) for d in su.findall("Data") if d.get("property") == "Rotation"), None))
                        mirrored = (next((_data_value(d) for d in su.findall("Data") if d.get("property") == "IsMirrored"), "false")
                                    or "false").lower() == "true"
                        pos = _data_point(su)
                        direction = _arrow_direction(shape, rot, mirrored) if shape is not None else None
                        if pos is not None and direction is not None:
                            m.arrows.append({"segment": current, "position": pos, "direction": direction})
                        break
            _walk_groups(m, child, objects, current)


# ---------------------------------------------------------------- Proteus XML 1.x
_SUFFIXES = ("AssignmentClass", "Specialization")


def _ga_name(name):
    for s in _SUFFIXES:
        if name.endswith(s) and len(name) > len(s):
            return name[:-len(s)]
    return name


def _ga(el):
    attrs = {}
    for ga_set in el.findall("GenericAttributes"):
        for g in ga_set.findall("GenericAttribute"):
            name, value = g.get("Name"), g.get("Value")
            if name and value not in (None, ""):
                attrs.setdefault(_ga_name(name), value)
    return attrs


def _location(el):
    pos = el.find("Position")
    loc = pos.find("Location") if pos is not None else None
    if loc is None:
        return None
    x, y = _float(loc.get("X")), _float(loc.get("Y"))
    return (x, y) if x is not None and y is not None else None


def _assoc(el, kind):
    return [a.get("ItemID") for a in el.findall("Association") if a.get("Type") == kind and a.get("ItemID")]


def read_proteus(root, version):
    m = Model(FMT_PROTEUS, version)
    info = root.find("PlantInformation")
    m.application = {"application": info.get("Application"), "version": info.get("ApplicationVersion"),
                     "units": info.get("Units")} if info is not None else None
    m.schema_version = info.get("SchemaVersion") if info is not None else None
    ext = root.find("./Drawing/Extent")
    if ext is not None and ext.find("Max") is not None:
        m.drawing["width"] = _float(ext.find("Max").get("X"))
        m.drawing["height"] = _float(ext.find("Max").get("Y"))
    m.flip_height = m.drawing["height"]
    md = root.find("MetaData")
    if md is not None:
        a = _ga(md)
        m.drawing["number"], m.drawing["name"] = a.get("DrawingNumber"), a.get("DrawingName")

    def flip(p):
        if p is None:
            return None
        return (p[0], (m.flip_height - p[1]) if m.flip_height is not None else p[1])

    def register(el, item_id):
        pts = el.find("ConnectionPoints")
        ids = []
        if pts is not None:
            for i, n in enumerate(pts.findall("Node")):
                nid = n.get("ID") or "%s__node_%d" % (item_id, i + 1)
                ids.append(nid)
                m.node_owner[nid] = (item_id, i)
                p = flip(_location(n))
                if p is not None:
                    m.node_pos[nid] = p
        return ids

    def dup(item_id):
        if item_id in m.items or item_id in m.nozzles:
            m.duplicate_ids.append(item_id)

    for child in root:
        if child.tag == "Equipment" and child.get("ID"):
            eid = child.get("ID")
            dup(eid)
            frag, cut = _fragment(child)
            item = {"id": eid, "cls": child.get("ComponentClass"), "group": "equipment", "attrs": _ga(child),
                    "nodes": [], "chambers": [], "nozzles": [], "xml": frag, "xml_cut": cut,
                    "position": flip(_location(child)), "has_id": True}
            m.items[eid] = item
            for sub in child.iter():
                if sub is child:
                    continue
                if sub.tag == "Equipment" and sub.get("ComponentClass") == "Chamber":
                    item["chambers"].append(_ga(sub))
                elif sub.tag == "Nozzle" and sub.get("ID"):
                    nid = sub.get("ID")
                    dup(nid)
                    nattrs = _ga(sub)
                    nodes = register(sub, nid)
                    m.nozzles[nid] = {"id": nid, "cls": sub.get("ComponentClass") or "Nozzle", "parent": eid,
                                      "port": nattrs.get("SubTagName") or nid, "attrs": nattrs, "nodes": nodes}
                    item["nozzles"].append(nid)
        elif child.tag == "PipingNetworkSystem":
            sid = child.get("ID")
            m.systems[sid] = {"id": sid, "attrs": _ga(child)}
            for seg in child.findall("PipingNetworkSegment"):
                gid = seg.get("ID")
                m.segments[gid] = {"id": gid, "system": sid, "attrs": _ga(seg)}
                seg_items, seg_conns = [], []
                for doc_index, it in enumerate(seg):
                    if it.tag in ("PipingComponent", "PipeOffPageConnector") and it.get("ID"):
                        seg_items.append((doc_index, it.get("ID")))
                        iid = it.get("ID")
                        dup(iid)
                        cls = it.get("ComponentClass") or ("PipeOffPageConnector" if it.tag == "PipeOffPageConnector" else None)
                        frag, cut = _fragment(it)
                        nodes = register(it, iid)
                        group = dexpi_map.group_of(cls) if cls and dexpi_map.library_ready() else None
                        if it.tag == "PipeOffPageConnector":
                            group = "offpage"
                        a = _ga(it)
                        ref = {"drawing": a.get("ReferencedDrawingNumber"), "connector": a.get("ReferencedConnectorNumber"),
                               "object": None} if it.tag == "PipeOffPageConnector" else None
                        m.items[iid] = {"id": iid, "cls": cls, "group": group or "piping", "attrs": a, "nodes": nodes,
                                        "segment": gid, "system": sid, "xml": frag, "xml_cut": cut,
                                        "position": flip(_location(it)), "has_id": True, "reference": ref}
                    elif it.tag == "Connection":
                        seg_conns.append({"id": None, "synthetic_id": "%s__Connection_%d" % (re.sub(r"[^A-Za-z0-9_]", "_", gid), len(seg_conns) + 1),
                                          "cls": "PipingConnection", "source": it.get("FromID"),
                                          "source_node": _proteus_node(m, it.get("FromID"), it.get("FromNode")),
                                          "source_node_no": it.get("FromNode"),
                                          "target": it.get("ToID"),
                                          "target_node": _proteus_node(m, it.get("ToID"), it.get("ToNode")),
                                          "target_node_no": it.get("ToNode"),
                                          "segment": gid, "system": sid, "index": doc_index})
                    elif it.tag == "PipeFlowArrow" and "DIRECTION_OF_FLOW" in (it.get("ComponentName") or ""):
                        pos = it.find("Position")
                        loc, ref = _location(it), (pos.find("Reference") if pos is not None else None)
                        rx, ry = _float(ref.get("X")) if ref is not None else None, _float(ref.get("Y")) if ref is not None else None
                        if loc is not None and rx is not None and ry is not None and (rx or ry):
                            n = math.hypot(rx, ry)
                            m.arrows.append({"segment": gid, "position": flip(loc), "direction": (rx / n, -ry / n)})
                # 구간의 Connection은 처음(FromID)과 끝(ToID)만 가리키는 경우가 많다. 구간 안 부품은 문서 순서가 길 순서다(§5.7)
                m.connections.extend(_segment_paths(seg_conns, seg_items, explode=True))
        elif child.tag == "ProcessInstrumentationFunction" and child.get("ID") and child.get("ComponentClass"):
            iid = child.get("ID")
            dup(iid)
            frag, cut = _fragment(child)
            nodes = register(child, iid)
            m.items[iid] = {"id": iid, "cls": child.get("ComponentClass"), "group": "instrument", "attrs": _ga(child),
                            "nodes": nodes, "xml": frag, "xml_cut": cut, "position": flip(_location(child)),
                            "has_id": True}
            for sub in child:
                if sub.tag == "ProcessSignalGeneratingFunction" and sub.get("ID"):
                    loc = _assoc(sub, "is located in")
                    m.sensing[sub.get("ID")] = {"item": loc[0] if loc else None, "pif": iid}
                if sub.tag == "InformationFlow" and sub.get("ID"):
                    _proteus_flow(m, sub)
        elif child.tag == "ActuatingSystem":
            sid = child.get("ID")
            entry = {"id": sid, "valves": [], "fail_action": None, "number": _ga(child).get("ActuatingSystemNumber")}
            for comp in child.findall("ActuatingSystemComponent"):
                cc = comp.get("ComponentClass")
                if cc == "ControlledActuator":
                    fa = _ga(comp).get("FailAction")
                    entry["fail_action"] = fa
                elif cc == "OperatedValveReference":
                    entry["valves"] += _assoc(comp, "refers to")
            for fn in child.findall("ActuatingFunction"):
                m.actuating[fn.get("ID")] = [sid]
            m.act_systems[sid] = entry
    # 정보 흐름·측정 기능은 어느 층에 있든 모은다
    seen_flows = {f["id"] for f in m.info_flows}
    for el in root.iter("InformationFlow"):
        if el.get("ID") and el.get("ID") not in seen_flows:
            _proteus_flow(m, el)
    for el in root.iter("ProcessSignalGeneratingFunction"):
        if el.get("ID") and el.get("ID") not in m.sensing:
            loc = _assoc(el, "is located in")
            m.sensing[el.get("ID")] = {"item": loc[0] if loc else None, "pif": None}
    for el in root.iter("ActuatingFunction"):
        if el.get("ID") and el.get("ID") not in m.actuating:
            fulfilled = _assoc(el, "is fulfilled by")
            m.actuating[el.get("ID")] = fulfilled
    m.diagram_count = len(root.findall("Drawing"))
    return m


def _endpoint_position(m, item_id, node_id):
    if node_id in m.node_pos:
        return m.node_pos[node_id]
    item = m.items.get(item_id)
    if item is not None and item.get("position") is not None:
        return item["position"]
    noz = m.nozzles.get(item_id)
    if noz is not None:
        pts = [m.node_pos[n] for n in noz["nodes"] if n in m.node_pos]
        if pts:
            return pts[0]
    return None


def _segment_paths(conns, items, explode):
    """구간 하나의 연결 목록과 부품 목록(문서·목록 순서)에서 이웃한 두 점마다 연결 하나를 만든다(HZ-PLN-22 §5.7).
    conns: [{source, target, index, …}], items: [(순서, 부품 id)]. explode=True(Proteus)는 연결 하나가 구간 전체의 처음과 끝만
    가리키므로 연결의 끝이 아닌 부품을 문서 순서로 `FromID → 부품… → ToID`로 풀고, 연결이 둘 이상이면 어느 연결에도 들지 못한
    부품을 순서 거리가 가장 가까운 연결에 끼운다(추정이라 assumed 표시). explode=False(2.0)는 연결을 그대로 두고 어느 연결의
    끝에도 없는 부품만 같은 방식으로 끼운다(assumed)."""
    if not conns:
        return []
    ends = {x for c in conns for x in (c["source"], c["target"]) if x}
    inner = {id(c): [] for c in conns}
    assumed = {}
    for index, item in items:
        if item in ends:
            continue
        if len(conns) == 1:
            target = conns[0]
            if not explode:
                assumed[item] = True
        else:
            target = min(conns, key=lambda c: abs(c["index"] - index))
            assumed[item] = True
        inner[id(target)].append((index, item))
    out = []
    for c in conns:
        mids = [x for _, x in sorted(inner[id(c)])]
        if not mids:
            out.append(dict(c, order=0, assumed_items=[]))
            continue
        chain = [(c["source"], c.get("source_node"))] + [(x, None) for x in mids] + [(c["target"], c.get("target_node"))]
        for n, (left, right) in enumerate(zip(chain, chain[1:])):
            part = dict(c, order=n, source=left[0], source_node=left[1], target=right[0], target_node=right[1],
                        id=c["id"] if n == 0 and c["id"] else None,
                        synthetic_id=c["synthetic_id"] if n == 0 else "%s_%d" % (c["synthetic_id"], n + 1),
                        assumed_items=[x for x in mids if assumed.get(x) and x in (left[0], right[0])])
            if n > 0:
                part.pop("source_node_no", None)
            if n < len(chain) - 2:
                part.pop("target_node_no", None)
            out.append(part)
    return out


def _proteus_node(m, item_id, node_no):
    """Connection의 FromNode·ToNode(1부터 센 순번)를 그 항목의 노드 ID로."""
    try:
        idx = int(node_no) - 1
    except (TypeError, ValueError):
        return None
    for nid, (owner, i) in m.node_owner.items():
        if owner == item_id and i == idx:
            return nid
    return None


def _proteus_flow(m, el):
    start, end = _assoc(el, "has logical start"), _assoc(el, "has logical end")
    m.info_flows.append({"id": el.get("ID"), "cls": el.get("ComponentClass"), "source": start[0] if start else None,
                         "target": end[0] if end else None})


def read(data):
    """바이트 -> Model. 형식을 판별하지 못하면 DexpiError(dexpi_unknown_format)."""
    root = parse_safely(data)
    found = detect(root)
    if found is None:
        raise DexpiError("dexpi_unknown_format", "DEXPI 파일(Model/Import 또는 PlantModel/PlantInformation)이 아님")
    fmt, version = found
    if not dexpi_map.library_ready():
        raise DexpiError("dexpi_library_missing", "DEXPI 클래스 목록(resources/library/dexpi)이 없음")
    return read_dexpi_xml(root, version) if fmt == FMT_DEXPI else read_proteus(root, version)


# ---------------------------------------------------------------- 구조 검사 (DEXPI XML 2.0.1 스키마의 인스턴스 규칙)
# XSD를 실행 중에 읽지 않는다. XSD 파일 자체가 DOCTYPE·개체 선언을 담아 안전한 읽기(parse_safely)로는 읽을 수 없고,
# 파일 단위 이용 조건도 확인하지 못했다(HZ-PLN-22 F7, §5.6). 대신 XSD가 정한 요소·속성·글자 규칙을 아래 표로 옮겨 검사한다.
# 이 표가 참고 자료 XSD(resources/references/dexpi-schema/)와 같은지는 tests/test_dexpi_import.py가 확인한다.
_ID_RE = r"[A-Za-z_][A-Za-z_0-9]*"
_NAME = re.compile(_ID_RE)
_NAME_REF = re.compile(r"(?:%s)?/%s(?:\.%s)*" % (_ID_RE, _ID_RE, _ID_RE))
_NAME_OR_REF = re.compile(r"(?:%s)|(?:%s)" % (_ID_RE, _NAME_REF.pattern))
_ID_REF = re.compile(r"#%s" % _ID_RE)
_NAME_OR_ID_REF = re.compile(r"(?:%s)|(?:%s)" % (_NAME_REF.pattern, _ID_REF.pattern))
_DATA_VALUES = ("AggregatedDataValue", "DataReference", "Boolean", "DateTime", "Double", "Integer", "String", "Undefined")
_MODEL_DEFINITIONS = ("Package", "AbstractClass", "ConcreteClass", "ClassExtension", "AbstractDataType", "AggregatedDataType",
                      "Enumeration", "BooleanType", "DateTimeType", "DoubleType", "IntegerType", "StringType", "UndefinedType")
# 요소 이름 -> 허용 자식 요소, 필수 속성, 허용 속성(XSD complexType과 같다). 정의 쪽(Package·ConcreteClass 등)은 이 앱이 읽지 않아
# 이름만 허용하고 안쪽은 보지 않는다.
STRUCTURE = {
    "Model": {"children": ("Import",) + _MODEL_DEFINITIONS + ("Object", "Data"), "required": ("name", "uri"),
              "attributes": ("name", "uri")},
    "Import": {"children": (), "required": ("source", "prefix"), "attributes": ("source", "prefix")},
    "Object": {"children": ("Components", "Data", "References"), "required": ("type",), "attributes": ("name", "id", "type")},
    "Components": {"children": ("Object", "ObjectReference"), "required": ("property",), "attributes": ("property",)},
    "ObjectReference": {"children": (), "required": ("object",), "attributes": ("object",)},
    "References": {"children": (), "required": ("property", "objects"), "attributes": ("property", "objects")},
    "Data": {"children": _DATA_VALUES, "required": ("property",), "attributes": ("property",)},
    "DataReference": {"children": (), "required": ("data",), "attributes": ("data",)},
    "AggregatedDataValue": {"children": ("Data",), "required": ("type",), "attributes": ("type",)},
}
# 속성 이름 -> 글자 규칙(XSD simpleType). 여러 값은 공백으로 나눠 하나씩 본다
_PATTERNS = {("Model", "name"): _NAME, ("Import", "prefix"): _NAME, ("Object", "type"): _NAME_REF, ("Object", "id"): _NAME,
             ("Object", "name"): _NAME, ("Components", "property"): _NAME_OR_REF, ("ObjectReference", "object"): _NAME_OR_ID_REF,
             ("References", "property"): _NAME_OR_REF, ("References", "objects"): _NAME_OR_ID_REF,
             ("Data", "property"): _NAME_OR_REF, ("DataReference", "data"): _NAME_OR_ID_REF,
             ("AggregatedDataValue", "type"): _NAME_REF}
_MULTI = {("References", "objects")}
_MIN_ONE_CHILD = ("Components", "Data")  # XSD minOccurs=1


def check_structure(root, limit=50):
    """DEXPI XML 2.0 뿌리(Model)가 스키마의 인스턴스 규칙을 지키는지 본다. 어긋난 곳의 문장 목록(최대 limit개). 비면 통과."""
    problems = []

    def bad(msg):
        if len(problems) < limit:
            problems.append(msg)

    if root.tag != "Model":
        return ["뿌리가 Model이 아님: %s" % root.tag]
    seen_definition = seen_data = False
    for child in root:
        if child.tag == "Import" and (seen_definition or seen_data):
            bad("Import는 Object 앞에 와야 함")
        elif child.tag == "Data":
            seen_data = True
        elif child.tag != "Import":
            if seen_data:
                bad("Data는 Object 뒤에 와야 함")
            seen_definition = True
    _check_element(root, bad, "")
    return problems


def _check_element(el, bad, where):
    rule = STRUCTURE.get(el.tag)
    if rule is None:
        return
    label = "%s %s" % (el.tag, el.get("id") or el.get("property") or el.get("type") or "")
    for name in rule["required"]:
        if el.get(name) is None:
            bad("%s: 필수 속성 %s 없음" % (label.strip(), name))
    for name, value in el.attrib.items():
        if name.startswith("_"):
            continue
        if name not in rule["attributes"]:
            bad("%s: 허용하지 않은 속성 %s" % (label.strip(), name))
            continue
        rx = _PATTERNS.get((el.tag, name))
        parts = value.split() if (el.tag, name) in _MULTI else [value]
        if rx is not None and (not parts or any(rx.fullmatch(x) is None for x in parts)):
            bad("%s: 속성 %s 값 형식이 아님: %r" % (label.strip(), name, value))
    if el.tag in _MIN_ONE_CHILD and len(el) == 0:
        bad("%s가 비어 있음" % label.strip())
    for child in el:
        if child.tag not in rule["children"]:
            bad("%s 아래에 올 수 없는 요소: %s" % (el.tag, child.tag))
            continue
        if child.tag in STRUCTURE:
            _check_element(child, bad, where)
        elif el.tag == "Data":
            _check_value(child, el, bad)
    if el.tag == "Data":
        for v in el:
            if v.tag == "Undefined" and (len(v) or (v.text or "").strip()):
                bad("Undefined에 내용이 있음 (%s)" % el.get("property"))


def _check_value(v, data, bad):
    if v.tag == "Double" and _float(v.text) is None:
        bad("Double 값이 숫자가 아님: %r (%s)" % (v.text, data.get("property")))
    elif v.tag == "Integer" and not re.fullmatch(r"[+-]?\d+", (v.text or "").strip()):
        bad("Integer 값이 정수가 아님: %r (%s)" % (v.text, data.get("property")))
    elif v.tag == "Boolean" and (v.text or "").strip() not in ("true", "false", "1", "0"):
        bad("Boolean 값이 아님: %r (%s)" % (v.text, data.get("property")))


def check_references(root, limit=50):
    """`#ID` 참조가 파일 안 id를 가리키는지, id가 겹치지 않는지 본다(§5.6-4·§6.5-3). 문장 목록, 비면 통과."""
    ids, dup, problems = set(), set(), []
    for el in root.iter("Object"):
        oid = el.get("id")
        if oid:
            (dup if oid in ids else ids).add(oid)
    for oid in sorted(dup):
        problems.append("id가 겹침: %s" % oid)
    for el in root.iter():
        attr = {"References": "objects", "ObjectReference": "object", "DataReference": "data"}.get(el.tag)
        if attr is None:
            continue
        for t in (el.get(attr) or "").split():
            if t.startswith("#") and t[1:] not in ids and len(problems) < limit:
                problems.append("없는 객체를 가리킴: %s" % t)
    return problems[:limit]
