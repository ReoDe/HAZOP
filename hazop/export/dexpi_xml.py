"""DEXPI XML 2.0.1의 요소를 짓는 작은 함수들(dexpi_export·dexpi_diagram이 같이 쓴다)."""

import re
import xml.etree.ElementTree as ET

_NOT_XML = re.compile("[^\t\n\r -퟿-�\U00010000-\U0010ffff]")


def el(parent, tag, **attrs):
    e = ET.SubElement(parent, tag)
    for k, v in attrs.items():
        e.set(k, v)
    return e


def refs(parent, prop, target):
    el(parent, "References", objects="#" + target, property=prop)


def components(parent, prop):
    return el(parent, "Components", property=prop)


def obj(parent, typ, oid=None):
    o = el(parent, "Object", type=typ)
    if oid:
        o.set("id", oid)
    return o


def value(parent, prop, kind, text):
    """<Data property=…><kind>text</kind></Data>. kind는 String·Double·Integer·Boolean."""
    el(el(parent, "Data", property=prop), kind).text = text


def number(parent, prop, v):
    value(parent, prop, "Double", repr(float(v)))


def reference(parent, prop, name):
    el(el(parent, "Data", property=prop), "DataReference", data=name)


def points(parent, prop, pts):
    d = el(parent, "Data", property=prop)
    for x, y in pts:
        agg = el(d, "AggregatedDataValue", type="Core/Diagram.Point")
        number(agg, "X", x)
        number(agg, "Y", y)


def color(parent, prop, rgb):
    agg = el(el(parent, "Data", property=prop), "AggregatedDataValue", type="Core/Diagram.Color")
    for name, v in zip("BGR", reversed(rgb)):
        value(agg, name, "Integer", str(v))


def stroke(parent, width, dash="Solid"):
    agg = el(el(parent, "Data", property="Stroke"), "AggregatedDataValue", type="Core/Diagram.Stroke")
    color(agg, "Color", (0, 0, 0))
    reference(agg, "DashStyle", "Core/Diagram.DashStyle." + dash)
    number(agg, "Width", width)


def join_values(root):
    """들여쓴 뒤, 그림 쪽 객체의 값(Data) 하나를 한 줄로 붙인다. 좌표마다 열 줄씩 늘어나는 것을 막는다(뜻은 같다)."""
    for o in root.iter("Object"):
        if "/Diagram." not in (o.get("type") or ""):
            continue
        for d in o.findall("Data"):
            for part in d.iter():
                if len(part):
                    part.text = None
                if part is not d:
                    part.tail = None


def clean_text(text):
    """XML에 쓸 수 없는 글자를 뺀다."""
    return _NOT_XML.sub("", str(text))
