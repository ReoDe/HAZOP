"""내보낸 DEXPI에 원래 값 표시를 얹는다(HZ-PLN-22 §6.9). 내보내기(dexpi_export)가 부른다."""

import json
import xml.etree.ElementTree as ET

from hazop.export import dexpi_xml
from hazop.extract.adapters import dexpi_import, dexpi_origin as origin, dexpi_read


def marks_of(export, graph):
    """표시 없이 내보낸 결과와 그 그래프 -> {DEXPI id: {칸: 글자}}."""
    model = dexpi_import.extract_bytes(export.xml, "marks.dexpi.xml")[1]
    return marks(model, export.sidecar["entities"], export.sidecar["pipes"], graph)


def _grades(node, unsettled):
    g = origin.grades_out(node)
    return {"Auto": " ".join(g.get("auto", ())) or None, "Edited": " ".join(g.get("edited", ())) or None, "TagBasis": g.get("tag_basis"),
            "Open": " ".join(x for x in origin.OPEN_FIELDS if (node["entity_id"], x) in unsettled) or None}


def marks(model, entities, pipes, graph):
    """되읽은 Model과 곁 파일의 줄(구성요소·배관), 그래프 -> {DEXPI id: {칸: 글자}}. 지문은 되읽은 표준 값에서 셈한다.
    값의 출처 등급(자동 확정이 정함, 사람이 고침, 추정한 태그)도 함께 적어 되읽을 때 등급이 올라가지 않게 한다."""
    out, controlled = {}, dexpi_import.controlled_valves(model)
    by_id = {n["entity_id"]: n for n in graph["nodes"]}
    unsettled = {(u.get("target"), u.get("field")) for u in graph["validation"]["unknowns"] if u.get("check") == origin.CHECK}
    for row in entities:
        n, item = by_id[row["entity_id"]], model.items.get(row["dexpi_id"])
        if item is None:
            continue
        mark = {"Kind": n["kind"] or None, "Text": n["label_text"], "Echo": origin.node_echo(item, dexpi_import.drive_of(controlled, row["dexpi_id"]))}
        if item["group"] == "instrument":
            mark["Tag"] = n["tag"] or ""
        mark.update(_grades(n, unsettled))
        out[row["dexpi_id"]] = _writable(mark)
    conns = {c["id"]: c for c in model.connections if c["id"]}
    for row in pipes:
        n, conn = by_id[row["entity_id"]], conns.get(row["dexpi_id"])
        if conn is None:
            continue
        mark = {"Text": n["label_text"] or None, "Echo": origin.pipe_echo(conn)}
        mark.update(_grades(n, unsettled))
        fd = n.get("flow_direction")
        if fd:
            mark["Flow"] = origin.OTHER_END[fd["from_end"]] if row["swapped"] else fd["from_end"]
            mark["Basis"] = origin.basis_for(fd.get("basis"), origin.grades_out(n))
        out[row["dexpi_id"]] = _writable(mark)
    return out


def write(xml, model, entities, pipes, graph):
    """표시 없는 DEXPI 바이트(와 그것을 되읽은 Model)에 표시를 얹어 (바이트, 되읽은 추출 결과). 표준 값과 어긋나 되읽을 때 쓰이지 않을 칸(사람이
    태그를 바꿔 계측 기능의 조각과 어긋난 것, 흐름을 도면 연결과 반대로 둔 것)도 싣는다. 되읽으면 미확인으로 남아 조용히 바뀌지 않는다."""
    out = add(xml, marks(model, entities, pipes, graph))
    return out, dexpi_import.extract_bytes(out, "marks.dexpi.xml")[0]


def _writable(mark):
    """글자가 있는 칸만. XML에 그대로 실리지 않는 글자(XML 밖 글자, 줄바꿈 CR)가 든 값은 JSON 글자로 적어 잃지 않는다."""
    def text(v):
        plain = "\r" not in v and dexpi_xml.clean_text(v) == v and not v.startswith(origin.PACKED)
        return v if plain else origin.PACKED + json.dumps(v)
    return {k: text(v) for k, v in mark.items() if isinstance(v, str)}


def add(xml, rows):
    """DEXPI 바이트에 표시를 얹은 바이트. 정의는 Import 뒤, 표시는 Object 뒤(Model의 Data 앞)에 둔다."""
    root = dexpi_read.parse_safely(xml)
    tail = next((i for i, c in enumerate(root) if c.tag == "Data"), len(root))
    for oid, mark in rows.items():
        obj = ET.Element("Object", type=origin.TYPE)
        for name in origin.FIELDS:
            if name in mark:
                dexpi_xml.value(obj, name, "String", mark[name])
        dexpi_xml.refs(obj, origin.TARGET, oid)
        root.insert(tail, obj)
        tail += 1
    root.insert(sum(1 for c in root if c.tag == "Import"), _definition())
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8") + b"\n"


def _definition():
    cls = ET.Element("ConcreteClass", name=origin.CLASS)
    for name in origin.FIELDS:
        p = dexpi_xml.el(cls, "DataProperty", name=name, lower="1" if name == "Echo" else "0", upper="1", isOrdered="false", isUnique="true")
        dexpi_xml.el(p, "DataTypeReference", type="Core/DataTypes.String")
    p = dexpi_xml.el(cls, "ReferenceProperty", name=origin.TARGET, lower="1", upper="1", oppositeLower="0", oppositeUpper="1", isOrdered="false",
                     isUnique="true")
    dexpi_xml.el(p, "ClassReference", type="Core/ConceptualObject")
    return cls
