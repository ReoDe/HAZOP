"""내보낸 DEXPI에 원래 값 표시를 얹는다(HZ-PLN-22 §6.9). 아직 내보내기가 부르지 않는다(쓰기는 꺼져 있다)."""

import xml.etree.ElementTree as ET

from hazop.export import dexpi_xml
from hazop.extract.adapters import dexpi_import, dexpi_origin as origin, dexpi_read


def marks_of(export, graph):
    """내보낸 결과와 그 그래프 -> {DEXPI id: {칸: 글자}}. 지문은 파일을 되읽은 표준 값에서 셈한다."""
    model = dexpi_import.extract_bytes(export.xml, "marks.dexpi.xml")[1]
    by_id = {n["entity_id"]: n for n in graph["nodes"]}
    out = {}
    for row in export.sidecar["entities"]:
        n, item = by_id[row["entity_id"]], model.items.get(row["dexpi_id"])
        if item is None:
            continue
        mark = {"Kind": n["kind"] or None, "Text": n["label_text"], "Echo": origin.node_echo(item)}
        if item["group"] == "instrument":
            mark["Tag"] = n["tag"] or ""
        out[row["dexpi_id"]] = _writable(mark)
    conns = {c["id"]: c for c in model.connections if c["id"]}
    for row in export.sidecar["pipes"]:
        n, conn = by_id[row["entity_id"]], conns.get(row["dexpi_id"])
        if conn is None:
            continue
        mark = {"Text": n["label_text"] or None, "Echo": origin.pipe_echo(conn)}
        fd = n.get("flow_direction")
        if fd:
            mark["Flow"] = origin.OTHER_END[fd["from_end"]] if row["swapped"] else fd["from_end"]
            mark["Basis"] = fd.get("basis")
        out[row["dexpi_id"]] = _writable(mark)
    return out


def _writable(mark):
    """XML에 그대로 실리는 글자만. 되읽으면 달라질 글자(XML 밖 글자, 줄바꿈 CR)가 든 칸은 쓰지 않는다."""
    return {k: v for k, v in mark.items() if isinstance(v, str) and "\r" not in v and dexpi_xml.clean_text(v) == v}


def add(xml, marks):
    """DEXPI 바이트에 표시를 얹은 바이트. 정의는 Import 뒤, 표시는 Object 뒤(Model의 Data 앞)에 둔다."""
    root = dexpi_read.parse_safely(xml)
    tail = next((i for i, c in enumerate(root) if c.tag == "Data"), len(root))
    for oid, mark in marks.items():
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
