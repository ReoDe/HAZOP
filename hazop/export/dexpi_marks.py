"""내보낸 DEXPI에 원래 값 표시를 얹는다(HZ-PLN-22 §6.9). 내보내기(dexpi_export)가 부른다."""

import xml.etree.ElementTree as ET

from hazop.export import dexpi_xml
from hazop.extract.adapters import dexpi_import, dexpi_origin as origin, dexpi_read


def marks_of(export, graph):
    """표시 없이 내보낸 결과와 그 그래프 -> {DEXPI id: {칸: 글자}}."""
    model = dexpi_import.extract_bytes(export.xml, "marks.dexpi.xml")[1]
    return marks(model, export.sidecar["entities"], export.sidecar["pipes"], {n["entity_id"]: n for n in graph["nodes"]})


def marks(model, entities, pipes, by_id):
    """되읽은 Model과 곁 파일의 줄(구성요소·배관), {entity_id: 그래프 노드} -> {DEXPI id: {칸: 글자}}. 지문은 되읽은 표준 값에서 셈한다.
    자동 확정이 정해 사람이 보지 않은 칸은 Auto에 적는다."""
    out, controlled = {}, dexpi_import.controlled_valves(model)
    for row in entities:
        n, item = by_id[row["entity_id"]], model.items.get(row["dexpi_id"])
        if item is None:
            continue
        mark = {"Kind": n["kind"] or None, "Text": n["label_text"], "Echo": origin.node_echo(item, dexpi_import.drive_of(controlled, row["dexpi_id"]))}
        if item["group"] == "instrument":
            mark["Tag"] = n["tag"] or ""
        mark["Auto"] = " ".join(x for x in ("kind", "tag") if x in (n.get("auto") or ())) or None
        out[row["dexpi_id"]] = _writable(mark)
    conns = {c["id"]: c for c in model.connections if c["id"]}
    for row in pipes:
        n, conn = by_id[row["entity_id"]], conns.get(row["dexpi_id"])
        if conn is None:
            continue
        mark = {"Text": n["label_text"] or None, "Echo": origin.pipe_echo(conn)}
        fd = n.get("flow_direction")
        if fd:
            mark["Flow"] = origin.OTHER_END[fd["from_end"]] if row["swapped"] else fd["from_end"]
            mark["Basis"] = fd.get("basis")
            if "flow" in (n.get("auto") or ()):  # 고침의 근거 이름은 자동이어도 human이다. 사람이 본 것처럼 싣지 않는다
                mark["Auto"], mark["Basis"] = "flow", "ai_auto"
        out[row["dexpi_id"]] = _writable(mark)
    return out


_CELLS = {"kind": ("Kind",), "tag": ("Tag",), "label_text": ("Text",), "flow_direction": ("Flow", "Basis")}


def write(xml, entities, pipes, by_id):
    """표시 없는 DEXPI 바이트에 표시를 얹어 (바이트, 되읽은 추출 결과). 되읽을 때 쓰이지 않을 칸(사람이 태그를 바꿔 계측 기능의 조각과 어긋난 것
    등)은 싣지 않는다."""
    rows = marks(dexpi_import.extract_bytes(xml, "marks.dexpi.xml")[1], entities, pipes, by_id)
    out = add(xml, rows)
    again = dexpi_import.extract_bytes(out, "marks.dexpi.xml")[0]
    useless = [(u["source_object_id"], u["field"]) for u in again["validation"]["unknowns"] if u["check"] == origin.CHECK]
    if useless:
        for oid, field in useless:
            for cell in _CELLS.get(field, ()):
                rows.get(oid, {}).pop(cell, None)
        out = add(xml, rows)
        again = dexpi_import.extract_bytes(out, "marks.dexpi.xml")[0]
    return out, again


def _writable(mark):
    """XML에 그대로 실리는 글자만. 되읽으면 달라질 글자(XML 밖 글자, 줄바꿈 CR)가 든 칸은 쓰지 않는다."""
    return {k: v for k, v in mark.items() if isinstance(v, str) and "\r" not in v and dexpi_xml.clean_text(v) == v}


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
