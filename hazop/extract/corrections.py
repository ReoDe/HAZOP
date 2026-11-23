"""② 도면 사람 수정 기록: 원본 추출은 그대로 두고 수정 기록(연산 목록)을 그 위에 적용한다.

기록 파일: <작업 루트>/data/drawing-edits/<safe_name(추출 폴더 이름)>.json. 연산은 OPS 표(이름 → 단계, 대상 종류, 값 검사,
적용 함수, 해소하는 미확인)로 적용한다. 대상은 source_object_id로 가리키고, 사람이 추가한 기기·연결의
id는 "manual-" + op_id다. 적용할 수 없는 연산은 사유와 함께 건너뛰고 나머지는 계속 적용한다.

단계는 둘이다(설계 docs/units/2026-11-13-drawing-knowledge/evidence/fix-input-ops-design.md).
- input(나누기 split, 배관 지정 pipe): 추출의 입력이다. resolve가 원본 PDF를 이 연산들로 다시 추출해 기준 추출(base)을
  만든다(열쇠가 같으면 output/extract/<이름>/extraction.inputs.json을 읽음). 연산은 pdf 개체 id와 그 모양으로 개체를
  가리키고, 모양으로 다시 찾지 못하면 몇 개를 못 찾았는지 사유와 함께 적용 불가다. 나눈 기호는 pdf-p<쪽>-split-<op_id>다.
- overlay(그 밖): 지금처럼 apply가 기준 추출 위에 적용한다. 입력 연산이 없으면 기준 추출은 원본 그대로다.
"""

import collections
import copy
import functools
import hashlib
import importlib.util
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Callable

from hazop import paths, store_io
from hazop.extract import rules
from hazop.extract.drawio import summarize
from hazop.extract.ids import MANUAL_PREFIX
from hazop.kg.schema import REGISTRY
from hazop.study.nodes import now_utc

KIND = "hazop_drawing_corrections"
SCHEMA_VERSION = "0.1"
RELATION_KINDS = ("physical_connection", "signal_connection", "measurement_connection")
ENDS = ("source", "target")


class _Skip(Exception):
    """적용 불가(not_applicable) 사유."""


# 문구를 바꾼 미확인 사유: 옛 문구로 저장된 확정 기록이 새 문구의 미확인도 지우게 한다(M2에서 고장 위치 검사를 전동 밸브까지 넓힘).
RENAMED_REASONS = {"제어밸브 실패 위치 미확인": "밸브 고장 위치 미확인"}

def store_path(name):
    return paths.folder("drawing-edits", paths.safe_name(name) + ".json")


def load(name):
    """수정 기록 문서. 없으면 None, 다른 종류 파일이면 ValueError."""
    return load_fp(name)[0]


def load_fp(name):
    """(수정 기록 문서, 읽은 바이트의 지문). 없으면 (None, None), 다른 종류 파일이면 ValueError."""
    path = store_path(name)
    data, fp = store_io.read_bytes(path)
    if data is None:
        return None, None
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("도면 수정 기록 파일이 아님: %s" % path)
    return doc, fp


def save(name, ops, by, drawing_number=None, at=None, expect=store_io.ANY):
    """save_fp와 같되 쓴 경로만 돌려준다."""
    return save_fp(name, ops, by, drawing_number, at, expect)[0]


# log 한 줄의 action. 새 화면은 연산 하나마다 edit, 되돌리기·다시 하기를 따로 적는다. AI 후보 수락·되돌리기는 ai_accept·ai_revert
SAVE_ACTIONS = ("save", "edit", "undo", "redo", "ai_accept", "ai_revert")


def save_fp(name, ops, by, drawing_number=None, at=None, expect=store_io.ANY, action="save", note=None):
    """ops 전체를 저장하고 이전 파일과 비교한 op_id 증감을 log에 덧붙인다. (쓴 경로, 새 지문)을 돌려준다.
    지운 연산은 내용까지 log의 removed_ops에 남긴다(지운 사람 수정도 기록에서 찾을 수 있게).
    expect(ops를 읽을 때의 load_fp 지문)를 주면 그 뒤 파일이 바뀌었을 때 쓰지 않고 store_io.Conflict를 낸다.
    op_id 하나는 연산 하나만 가리킨다. 저장된 연산이나 지운 연산의 번호를 다른 내용에 쓰면 ValueError다."""
    prev, fp = load_fp(name)
    if expect is not store_io.ANY and fp != expect:
        raise store_io.Conflict("읽은 뒤 저장 파일이 바뀜: %s" % store_path(name))
    prev = prev or {}
    ops = [dict(o) for o in ops]
    saved = {o["op_id"]: o for o in prev.get("ops") or []}
    before = list(saved)
    after = [o["op_id"] for o in ops]
    gone = _issued(prev) - set(before)
    kept = [o for e in prev.get("log") or [] for o in e.get("removed_ops") or []]
    reused = [o["op_id"] for o in ops if o["op_id"] in gone and o not in kept]  # 지운 그대로 되살리는 것(실행 취소)은 된다
    reused += [i for i, o in zip(after, ops) if i in saved and o != saved[i]]
    reused += [i for n, i in enumerate(after) if i in after[:n]]
    if action not in SAVE_ACTIONS:
        raise ValueError("모르는 저장 동작: %r" % (action,))
    if reused:
        raise ValueError("이미 쓴 연산 번호를 다른 연산에 쓸 수 없음: %s (새 연산은 make_op에 name을 넘겨 번호를 받을 것)"
                         % ", ".join(dict.fromkeys(reused)))
    removed = [o for o in prev.get("ops") or [] if o["op_id"] not in after]
    doc = {
        "kind": KIND, "schema_version": SCHEMA_VERSION, "extraction_name": name,
        "drawing_number": drawing_number if drawing_number is not None else prev.get("drawing_number"),
        "ops": ops,
        "log": list(prev.get("log") or []) + [{
            "at": at or now_utc(), "by": by, "action": action,
            "added": [i for i in after if i not in before], "removed": [o["op_id"] for o in removed],
            "removed_ops": removed, **(note or {})}],
    }
    path = store_path(name)
    return path, store_io.write_json(path, doc, expect=fp)


def issued_op_ids(name):
    """저장 기록에 한 번이라도 나온 op_id(지금 연산과 log의 추가·삭제). 새 op_id는 이 번호들과 겹치지 않게 발급한다."""
    return _issued(load(name) or {})


def _issued(doc):
    ids = {o.get("op_id") for o in doc.get("ops") or []}
    for entry in doc.get("log") or []:
        ids.update(entry.get("added") or [])
        ids.update(entry.get("removed") or [])
    ids.discard(None)
    return ids


def unknown_ratio(extraction):
    """미확인 수 / (노드 + 관계 + 미해결 커넥터). scripts/check_adapter.py drawing_metrics와 같은 정의. 대상이 없으면 None."""
    n = len(extraction["nodes"]) + len(extraction["relations"]) + len(extraction["unresolved_connectors"])
    return len(extraction["validation"]["unknowns"]) / n if n else None


# ---------------------------------------------------------------- 값 검사(형식만, 대상 존재는 적용 때 본다)

def _str(value, key, allow_empty=False):
    v = value.get(key)
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        raise ValueError("%s는 비어 있지 않은 문자열이어야 함" % key)
    return v.strip()


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _points(pts, key="points"):
    if not isinstance(pts, list) or len(pts) < 2 or not all(
            isinstance(p, list) and len(p) == 2 and all(_num(c) for c in p) for p in pts):
        raise ValueError("%s는 [x, y] 점 2개 이상이어야 함" % key)


def _kind_category(value):
    kind, cat = _str(value, "kind"), _str(value, "category")
    # M2 이전에 저장한 연산(오리피스·벤트 = equipment, 그때 없던 kind는 분류 자유)도 받는다. 적용할 때 분류는 레지스트리 값으로 맞춘다
    legacy_ok = rules.LEGACY_KIND_CATEGORY.get(kind, cat) == cat
    if kind in rules.KIND_CATEGORY and rules.KIND_CATEGORY[kind] != cat and not legacy_ok:
        raise ValueError("kind %s의 category는 %s여야 함(받은 값 %s)" % (kind, rules.KIND_CATEGORY[kind], cat))


def _category(v):
    return rules.KIND_CATEGORY.get(v["kind"].strip(), v["category"].strip())


def _check_tag(value):
    _str(value, "tag")


def _position_check(prop):
    allowed = REGISTRY.properties[prop]["values"]

    def check(value):
        if value.get("value") not in allowed:
            raise ValueError("%s는 %s 중 하나여야 함" % (REGISTRY.properties[prop]["label_ko"], "/".join(allowed)))
    return check


def _check_flow(value):
    _str(value, "from"), _str(value, "to")
    if value["from"] == value["to"]:
        raise ValueError("from과 to가 같음")


def _check_endpoint(value):
    if value.get("end") not in ENDS:
        raise ValueError("end는 source 또는 target이어야 함")
    _str(value, "node")


def _check_clear_endpoint(value):
    if value.get("end") not in ENDS:
        raise ValueError("end는 source 또는 target이어야 함")
    if set(value) - {"end"}:
        raise ValueError("값은 end 하나뿐이어야 함")


def _check_path(value):
    _points(value.get("points"))


def _check_confirm(value):
    # 확정은 사람이 본 미확인 하나하나(check + reason)만 지운다. '전부' 확정은 다시 추출 때 새로 생긴 미확인까지 지우므로 두지 않는다
    items = value.get("items")
    if not isinstance(items, list) or not items or not all(
            isinstance(i, dict) and isinstance(i.get("check"), str) and i["check"] and isinstance(i.get("reason"), str)
            for i in items):
        raise ValueError("items는 {check, reason} 미확인 1개 이상이어야 함")


def _check_add_node(value):
    _kind_category(value)
    if value.get("tag") is not None:
        _str(value, "tag", allow_empty=True)
    box = value.get("bbox")
    if not (isinstance(box, list) and len(box) == 4 and all(_num(v) for v in box) and box[2] > 0 and box[3] > 0):
        raise ValueError("bbox는 [x, y, 너비, 높이](너비·높이 > 0)여야 함")


def _check_add_relation(value):
    if value.get("kind") not in RELATION_KINDS:
        raise ValueError("kind는 %s 중 하나여야 함" % ", ".join(RELATION_KINDS))
    line_type = _str(value, "line_type")
    if line_type in rules.LINE_TYPE_RELATION and rules.LINE_TYPE_RELATION[line_type] != value["kind"]:
        raise ValueError("line_type %s는 %s 관계임" % (line_type, rules.LINE_TYPE_RELATION[line_type]))
    if value.get("line_no") is not None:
        _str(value, "line_no", allow_empty=True)
    _check_flow(value)
    if value.get("points") is not None:
        _points(value["points"])


def _check_empty(value):
    if value:
        raise ValueError("값이 비어 있어야 함")


def _check_pdf_objects(value):
    """입력 연산 공통: {"pdf": {sha256, page, reader}, "objects": [pdf-path id], "shapes": {id: [x0, y0, x1, y1, 점 수, 닫힘]}}."""
    pdf = value.get("pdf")
    if not (isinstance(pdf, dict) and isinstance(pdf.get("sha256"), str) and len(pdf["sha256"]) == 64
            and type(pdf.get("page")) is int and pdf["page"] >= 0 and isinstance(pdf.get("reader"), str)):
        raise ValueError("pdf는 {sha256, page, reader}여야 함(벡터 PDF 도면만)")
    objs = value.get("objects")
    if not (isinstance(objs, list) and objs and all(isinstance(o, str) and o.startswith("pdf-path-") for o in objs)
            and len(set(objs)) == len(objs)):
        raise ValueError("objects는 겹치지 않는 pdf 개체 id(pdf-path-…) 1개 이상이어야 함")
    shapes = value.get("shapes")
    if not (isinstance(shapes, dict) and set(shapes) == set(objs) and all(
            isinstance(v, list) and len(v) == 6 and all(_num(c) for c in v[:4]) and type(v[4]) is int
            and isinstance(v[5], bool) for v in shapes.values())):
        raise ValueError("shapes는 objects마다 [x0, y0, x1, y1, 점 수, 닫힘]이어야 함")


def _check_split(value):
    _check_pdf_objects(value)
    if value.get("kind") is not None and value["kind"] not in rules.KIND_CATEGORY:
        raise ValueError("kind %r는 사전에 없는 종류" % (value["kind"],))
    if set(value) - {"pdf", "objects", "shapes", "kind"}:
        raise ValueError("모르는 키: %s" % ", ".join(sorted(set(value) - {"pdf", "objects", "shapes", "kind"})))


def _check_pipe(value):
    _check_pdf_objects(value)
    if not isinstance(value.get("ring"), bool):
        raise ValueError("ring은 true/false여야 함")
    line_type = _str(value, "line_type")
    if rules.LINE_TYPE_RELATION.get(line_type, "physical_connection") != "physical_connection":
        raise ValueError("배관 지정의 line_type %s는 배관이 아님" % line_type)


# ---------------------------------------------------------------- 적용 상태

class _State:
    """고치는 중인 extraction 사본과 source_object_id 색인."""

    def __init__(self, doc):
        self.doc = doc
        self.deleted = set()
        self.lumps = {}  # 나누기 대상 덩어리 id → 첫 나누기 op_id(덩어리가 없어진 사유)
        self.resolved = 0
        self.index = {}
        for n in doc["nodes"]:
            self.index[n["source_object_id"]] = ("node", n)
        for key in ("relations", "unresolved_connectors"):
            for r in doc[key]:
                self.index[r["source_object_id"]] = ("relation", r)

    def node(self, sid):
        kind, obj = self.index.get(sid, (None, None))
        if kind != "node":
            raise _Skip("삭제된 노드: %s" % sid if sid in self.deleted else "노드 없음: %s" % sid)
        return obj

    def location(self, local_id):
        return next((loc for loc in self.doc["source_locations"] if loc["local_id"] == local_id), None)

    def center(self, node):
        loc = self.location(node["local_id"])
        if loc is not None:
            x, y, w, h = loc["bbox"]
        else:
            g = node.get("geometry") or {}
            if not all(_num(g.get(k)) for k in ("x", "y", "width", "height")):
                raise _Skip("노드 좌표 없음: %s" % node["source_object_id"])
            x, y, w, h = g["x"], g["y"], g["width"], g["height"]
        return [round(x + w / 2.0, 3), round(y + h / 2.0, 3)]

    def set_location(self, local_id, sid, pts):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
        loc = self.location(local_id)
        if loc is None:
            cs = self.doc["coordinate_system"]
            self.doc["source_locations"].append({"object_id": sid, "local_id": local_id,
                                                 "coordinate_space": cs["coordinate_space"], "unit": cs["unit"],
                                                 "bbox": box, "approximate": False})
        else:
            loc.update(bbox=box, approximate=False)
            loc.pop("method", None)

    def drop_unknowns(self, local_id, pred=lambda u: True):
        v = self.doc["validation"]
        keep = [u for u in v["unknowns"] if not (u.get("target") == local_id and pred(u))]
        self.resolved += len(v["unknowns"]) - len(keep)
        v["unknowns"] = keep

    def remove(self, kind, obj):
        local = obj["local_id"]
        for key in (("nodes",) if kind == "node" else ("relations", "unresolved_connectors")):
            self.doc[key] = [x for x in self.doc[key] if x is not obj]
        self.doc["source_locations"] = [loc for loc in self.doc["source_locations"] if loc["local_id"] != local]
        self.drop_unknowns(local)
        del self.index[obj["source_object_id"]]
        self.deleted.add(obj["source_object_id"])


def _end(rel, name):
    return next(ep for ep in rel["endpoints"] if ep["end"] == name)


def _flow(rel, from_node, to_node):
    ends = {}
    for node, role in ((from_node, "from"), (to_node, "to")):
        hit = [ep["end"] for ep in rel["endpoints"] if ep["node_local_id"] == node["local_id"]]
        if len(hit) != 1:
            raise _Skip("흐름 방향의 %s 노드 %s가 이 관계의 한쪽 끝이 아님" % (role, node["source_object_id"]))
        ends[role] = hit[0]
    return {"from": from_node["local_id"], "to": to_node["local_id"], "from_end": ends["from"],
            "to_end": ends["to"], "basis": "human"}


# ---------------------------------------------------------------- 적용 함수 (st, kind, obj, op) -> 표시할 대상 또는 None

def _apply_set_tag(st, kind, obj, op):
    tag = op["value"]["tag"].strip()
    if kind == "node":
        obj["tag"] = tag
        obj.setdefault("attributes", {})["tag"] = tag
        if isinstance(obj.get("evidence"), dict) and "tag_basis" in obj["evidence"]:
            obj["evidence"]["tag_basis"] = "human"  # ③ 자동 연결이 추정 태그로 다루지 않게
    else:
        obj["line_no"] = tag
        obj.setdefault("attributes", {})["line_no"] = tag
    return obj


def _apply_set_kind(st, kind, obj, op):
    v = op["value"]
    obj.update(kind=v["kind"].strip(), category=_category(v), classification="classified")
    attrs = obj.setdefault("attributes", {})
    cid = REGISTRY.kind_class.get(obj["kind"])
    allowed = REGISTRY.class_properties(cid) if cid else ()
    for prop in [k for k in attrs if k in REGISTRY.properties and k not in allowed]:
        del attrs[prop]  # 새 종류에 없는 속성(예: 사전이 붙인 valve_type)은 남기지 않는다
    attrs["kind"] = obj["kind"]
    return obj


def _apply_position(prop):
    def apply(st, kind, obj, op):
        cid = REGISTRY.kind_class.get(obj.get("kind"))
        if cid is None or prop not in REGISTRY.class_properties(cid):
            raise _Skip("%s에는 %s를 두지 않음(종류 %s)" % (REGISTRY.label(cid, "이 항목"),
                                                    REGISTRY.properties[prop]["label_ko"], obj.get("kind")))
        obj.setdefault("attributes", {})[prop] = op["value"]["value"]
        return obj
    return apply


def _apply_set_flow(st, kind, obj, op):
    if obj["kind"] not in rules.RELATION_KINDS_WITH_FLOW:
        raise _Skip("흐름 방향은 물리 배관에만 지정함(%s)" % obj["kind"])
    obj["flow_direction"] = _flow(obj, st.node(op["value"]["from"]), st.node(op["value"]["to"]))
    return obj


def _apply_set_endpoint(st, kind, obj, op):
    v = op["value"]
    node = st.node(v["node"])
    point = st.center(node)
    ep = _end(obj, v["end"])
    ep.update(node_local_id=node["local_id"], source_object_id=node["source_object_id"], status="connected",
              point=point, point_basis="human", constraint=None)
    fd = obj.get("flow_direction")
    if fd:
        for role in ("from", "to"):
            if fd[role + "_end"] == v["end"]:
                fd[role] = node["local_id"]
    unresolved = st.doc["unresolved_connectors"]
    if any(x is obj for x in unresolved) and all(e["node_local_id"] and e["status"] == "connected"
                                                 for e in obj["endpoints"]):
        st.doc["unresolved_connectors"] = [x for x in unresolved if x is not obj]
        st.doc["relations"].append(obj)  # 양 끝이 정해졌으니 ③에서 정상 연결로 쓴다
    return obj


def _apply_clear_endpoint(st, kind, obj, op):
    """연결 끊기: 그 끝을 기기에서 떼어 열린 끝으로 둔다(점은 그 자리에 남는다). 흐름 방향은 양 끝이 기기여야 하므로 지운다."""
    ep = _end(obj, op["value"]["end"])
    if not ep.get("node_local_id"):
        raise _Skip("이미 열린 끝")
    end = op["value"]["end"]
    ep.update(node_local_id=None, source_object_id=None, status="unconnected", point_basis="human", constraint=None)
    obj["flow_direction"] = None
    st.doc["validation"]["unknowns"].append({"check": "unconnected_endpoint", "reason": "%s 끝이 도형에 붙어 있지 않음(사람이 끊음)" % end,
                                             "source_object_id": obj["source_object_id"], "target": obj["local_id"], "field": end})
    if any(x is obj for x in st.doc["relations"]):
        st.doc["relations"] = [x for x in st.doc["relations"] if x is not obj]
        st.doc["unresolved_connectors"].append(obj)     # 끝이 열린 연결은 ③에서 정상 연결로 쓰지 않는다
    return obj


def _apply_set_path(st, kind, obj, op):
    pts = [list(p) for p in op["value"]["points"]]
    _end(obj, "source")["point"], _end(obj, "target")["point"] = pts[0], pts[-1]
    obj["waypoints"] = pts[1:-1]
    obj["geometry_source"] = "human"
    st.set_location(obj["local_id"], obj["source_object_id"], pts)
    return obj


def _apply_confirm(st, kind, obj, op):
    return obj


def _apply_add_node(st, kind, obj, op):
    v, new_id = op["value"], MANUAL_PREFIX + op["op_id"]
    if new_id in st.index or new_id in st.deleted:
        raise _Skip("이미 있는 id: %s" % new_id)
    tag = (v.get("tag") or "").strip() or None
    x, y, w, h = v["bbox"]
    node = {"local_id": new_id, "source_object_id": new_id, "classification": "classified",
            "category": _category(v), "kind": v["kind"].strip(), "tag": tag, "label": tag or "",
            "label_text": tag or "", "label_location": None,
            "attributes": {"kind": v["kind"].strip(), **({"tag": tag} if tag else {})},
            "style": None, "parent": None, "geometry": {"x": x, "y": y, "width": w, "height": h}}
    st.doc["nodes"].append(node)
    st.index[new_id] = ("node", node)
    st.set_location(new_id, new_id, [[x, y], [x + w, y + h]])
    return node


def _apply_delete_node(st, kind, obj, op):
    local = obj["local_id"]
    for r in [r for key in ("relations", "unresolved_connectors") for r in st.doc[key]
              if any(ep["node_local_id"] == local for ep in r["endpoints"])]:
        st.remove("relation", r)
    st.remove("node", obj)
    return None


def _apply_add_relation(st, kind, obj, op):
    v, new_id = op["value"], MANUAL_PREFIX + op["op_id"]
    if new_id in st.index or new_id in st.deleted:
        raise _Skip("이미 있는 id: %s" % new_id)
    a, b = st.node(v["from"]), st.node(v["to"])
    pts = [list(p) for p in v["points"]] if v.get("points") else [st.center(a), st.center(b)]
    line_no = (v.get("line_no") or "").strip() or None
    rel = {"local_id": new_id, "source_object_id": new_id, "kind": v["kind"], "line_type": v["line_type"].strip(),
           "line_no": line_no,
           "endpoints": [{"end": end, "node_local_id": n["local_id"], "source_object_id": n["source_object_id"],
                          "constraint": None, "point": p, "point_basis": "human", "status": "connected", "port": None}
                         for end, n, p in (("source", a, pts[0]), ("target", b, pts[-1]))],
           "flow_direction": None, "waypoints": pts[1:-1], "label": line_no or "", "label_text": line_no or "",
           "label_cells": [], "attributes": {"line_type": v["line_type"].strip(), **({"line_no": line_no} if line_no else {})},
           "style": None, "parent": None, "geometry": None, "geometry_source": "human"}
    if v["kind"] in rules.RELATION_KINDS_WITH_FLOW:
        rel["flow_direction"] = _flow(rel, a, b)
    st.doc["relations"].append(rel)
    st.index[new_id] = ("relation", rel)
    st.set_location(new_id, new_id, pts)
    return rel


def _apply_delete_relation(st, kind, obj, op):
    st.remove("relation", obj)
    return None


def _apply_input(st, kind, obj, op):
    raise AssertionError("입력 연산은 기준 추출을 만들 때 쓴다(resolve)")


@dataclass(frozen=True)
class OpSpec:
    targets: tuple  # 빈 튜플이면 대상 없이 새로 만드는 연산
    check: Callable  # value -> None, 형식 오류면 ValueError
    apply: Callable  # (state, 대상 종류, 대상, op) -> human_edit를 붙일 대상 또는 None
    resolves: Callable  # (unknown, 대상 종류, value) -> 이 연산으로 지울 미확인인가
    stage: str = "overlay"  # input: 추출의 입력(resolve가 다시 추출로 적용), overlay: apply가 그 위에 적용


OPS = {
    "set_tag": OpSpec(("node", "relation"), _check_tag, _apply_set_tag,
                      lambda u, k, v: u.get("field") == ("tag" if k == "node" else "line_no")),
    "set_kind": OpSpec(("node",), _kind_category, _apply_set_kind,
                       lambda u, k, v: u.get("field") == "kind" and u["check"] in ("missing_kind", "unclassified_kind")),
    # 정상 위치·고장 위치(기획서/지식그래프-스키마-입력.md §3.2). 같은 속성의 누락·허용값 미확인을 지운다
    "set_normal_position": OpSpec(("node",), _position_check("normal_position"), _apply_position("normal_position"),
                                  lambda u, k, v: u.get("field") == "normal_position"),
    "set_fail_position": OpSpec(("node",), _position_check("fail_position"), _apply_position("fail_position"),
                                lambda u, k, v: u.get("field") == "fail_position"),
    "set_flow": OpSpec(("relation",), _check_flow, _apply_set_flow,
                       lambda u, k, v: u.get("field") == "flow_direction"),
    "set_endpoint": OpSpec(("relation",), _check_endpoint, _apply_set_endpoint,
                           lambda u, k, v: u["check"] in ("unconnected_endpoint", "endpoint_not_node")
                           and (u.get("reason") or "").startswith(v["end"])),
    "clear_endpoint": OpSpec(("relation",), _check_clear_endpoint, _apply_clear_endpoint, lambda u, k, v: False),
    "set_path": OpSpec(("relation",), _check_path, _apply_set_path,
                       lambda u, k, v: u.get("field") in ("bbox", "geometry")),
    "confirm": OpSpec(("node", "relation"), _check_confirm, _apply_confirm,
                      lambda u, k, v: any(u["check"] == i["check"]
                                          and (u.get("reason") or "") == RENAMED_REASONS.get(i["reason"], i["reason"])
                                          for i in v["items"])),
    "add_node": OpSpec((), _check_add_node, _apply_add_node, lambda u, k, v: False),
    "delete_node": OpSpec(("node",), _check_empty, _apply_delete_node, lambda u, k, v: True),
    "add_relation": OpSpec((), _check_add_relation, _apply_add_relation, lambda u, k, v: False),
    "delete_relation": OpSpec(("relation",), _check_empty, _apply_delete_relation, lambda u, k, v: True),
    # 덩어리에서 기호 하나 떼어 내기(대상 = 덩어리 노드). 나눈 기호는 pdf-p<쪽>-split-<op_id>
    "split": OpSpec(("node",), _check_split, _apply_input, lambda u, k, v: False, stage="input"),
    # 이 도형들은 배관(대상 없음). 다시 추출에 넣는 일은 아직 없다(적용 불가 PIPE_PENDING)
    "pipe": OpSpec((), _check_pipe, _apply_input, lambda u, k, v: False, stage="input"),
}
INPUT_NAME = re.compile(r"^pdf-p\d+-(split|ring)-(.+)$")  # 입력 연산이 만든 노드 id → 그 op_id
PIPE_PENDING = "배관 지정은 아직 다시 읽기에 넣지 않음"


def is_input(op):
    spec = OPS.get(op.get("op"))
    return spec is not None and spec.stage == "input"


# ---------------------------------------------------------------- 지문·연산 만들기·적용

def objs_digest(obj, pdf_sha=None):
    """대상의 pdf 개체 집합 지문("o-" + sha1 앞 6자리). pdf 개체가 없으면(drawio·분기점·사람이 더한 것) None.
    pdf-path 순번은 그 PDF 안에서만 같은 도형을 가리키므로 원본 PDF의 sha256(pdf_sha)을 함께 넣는다. PDF가 바뀌면 지문이 달라
    _rematch가 순번만 같은 다른 도형으로 대상을 옮기지 않는다."""
    objs = sorted((obj.get("evidence") or {}).get("pdf_objects") or []) if isinstance(obj.get("evidence"), dict) else []
    return "o-" + hashlib.sha1(("%s|" % (pdf_sha or "") + ",".join(objs)).encode("utf-8")).hexdigest()[:6] if objs else None


def fingerprint(kind, obj, loc=None, pdf_sha=None):
    """base 비교용 대상 지문. 노드 {kind, category, tag, at}, 관계 {kind, ends: 양 끝 노드 source_object_id, at}.
    at = 위치 상자 중심(정수 반올림). PDF 대상 ID는 순번이라 다시 추출하면 같은 ID가 다른 기호를 가리킬 수 있어 위치로 가른다.
    PDF 대상이면 objs(pdf 개체 집합 지문)도 넣는다. 같은 대상인지는 보지 않고(조각 하나가 더 붙어도 같은 기호다),
    번호가 밀린 대상을 다시 찾을 때 먼저 쓴다."""
    at = [round(loc["bbox"][0] + loc["bbox"][2] / 2.0), round(loc["bbox"][1] + loc["bbox"][3] / 2.0)] if loc else None
    if kind == "node":
        out = {"kind": obj.get("kind"), "category": obj.get("category"), "tag": obj.get("tag"), "at": at}
    else:
        out = {"kind": obj.get("kind"), "ends": [ep.get("source_object_id") for ep in obj["endpoints"]], "at": at}
    objs = objs_digest(obj, pdf_sha)
    if objs:
        out["objs"] = objs
    return out


def _fingerprints(extraction):
    locs = {loc["local_id"]: loc for loc in extraction["source_locations"]}
    sha = (extraction.get("source") or {}).get("sha256")
    out = {n["source_object_id"]: fingerprint("node", n, locs.get(n["local_id"]), sha) for n in extraction["nodes"]}
    for key in ("relations", "unresolved_connectors"):
        out.update((r["source_object_id"], fingerprint("relation", r, locs.get(r["local_id"]), sha)) for r in extraction[key])
    return out


REF_KEYS = ("from", "to", "node")  # value 안에서 노드를 가리키는 키


def _same(base, cur):
    """지문 비교. 분류(category)는 kind에서 레지스트리로 정해지므로 보지 않는다(레지스트리 분류 이동만으로 옛 연산이
    '대상이 바뀜'이 되지 않게, M2 U9)."""
    if base is None or cur is None:
        return base is cur
    base = {k: v for k, v in base.items() if k not in ("category", "objs")}
    cur = {k: v for k, v in cur.items() if k not in ("category", "objs")}
    if base.get("at") is not None:  # 같은 자리에서 지식이 늘어난 것은 대상이 바뀐 것이 아니다(기호 사전, 기획서/PID-기호사전.md D14)
        for k in ("kind", "tag"):  # 없던 값이 새로 채워지거나, 틀린 값이 지워짐(같은 자리의 같은 대상)
            if (base.get(k) is None) != (cur.get(k) is None):
                base[k] = cur.get(k)
        if (base.get("kind"), cur.get("kind")) == ("physical_connection", "measurement_connection"):
            base["kind"] = cur["kind"]  # 끝 기호가 계기로 밝혀져 같은 선이 측정 연결이 됨
    return base == cur


def _refs(value):
    return sorted({value[k] for k in REF_KEYS if isinstance(value.get(k), str) and not value[k].startswith(MANUAL_PREFIX)})


def _apply_one(st, original_fp, op):
    spec = OPS.get(op.get("op"))
    if spec is None:
        raise _Skip("형식 오류: 알 수 없는 연산 %r" % op.get("op"))
    value = op.get("value")
    if not isinstance(value, dict):
        raise _Skip("형식 오류: value가 객체가 아님")
    try:
        spec.check(value)
    except ValueError as exc:
        raise _Skip("형식 오류: %s" % exc)
    target, kind, obj = op.get("target"), None, None
    if not spec.targets:
        if target is not None:
            raise _Skip("형식 오류: %s에는 대상을 주지 않음" % op["op"])
    else:
        if target in st.deleted:
            raise _Skip("삭제된 대상")
        if target not in st.index:
            m = INPUT_NAME.match(str(target))
            if m:  # 대상이 나누기로 생긴 기호인데 그 나누기가 없어짐(되돌림)
                raise _Skip("나누기 %s이(가) 되돌려져 대상이 없음" % m.group(2))
            raise _Skip("대상 없음")
        kind, obj = st.index[target]
        if kind not in spec.targets:
            raise _Skip("형식 오류: %s는 %s 대상에 쓸 수 없음" % (op["op"], kind))
        if not str(target).startswith(MANUAL_PREFIX) and not _same(op.get("base"), original_fp.get(target)):
            cur, base = original_fp.get(target) or {}, op.get("base") or {}
            diff = ["%s %r→%r" % (k, base.get(k), cur.get(k)) for k in sorted(set(cur) | set(base))
                    if base.get(k) != cur.get(k) and k not in ("category", "objs")]
            raise _Skip("대상이 바뀜: %s" % ", ".join(diff))
    refs = op.get("refs") or {}
    for sid in _refs(value):
        if refs.get(sid) is None or not _same(refs[sid], original_fp.get(sid)):
            raise _Skip("연결 대상 기기가 바뀌었거나 없음: %s" % sid)
    edited = spec.apply(st, kind, obj, op)
    if obj is not None:
        st.drop_unknowns(obj["local_id"], lambda u: spec.resolves(u, kind, value))
    if edited is not None:
        mark = edited.setdefault("human_edit", {"op_ids": []})
        mark["op_ids"].append(op["op_id"])
        ops = mark.setdefault("ops", [])
        if op["op"] not in ops:
            ops.append(op["op"])
        mark.update(by=op.get("by"), at=op.get("at"))


def _rematch(fp, original_fp):
    """번호가 밀린 대상을 지문으로 다시 찾는다(기획서/PID-기호사전.md D14). 같은 PDF에서 pdf 개체 집합(objs)이 같고
    종류도 같은 대상이 정확히 하나면 그것(같은 도형이다, objs_digest). 아니면 같은 위치(at)·같은 종류의 대상이 정확히
    하나일 때만 그 id. 관계의 양 끝(ends)은 노드 번호가 같이 밀리므로 보지 않는다. 둘 이상이거나 없으면 None."""
    if not fp:
        return None
    is_rel = "ends" in fp
    if fp.get("objs"):
        same = [sid for sid, cur in sorted(original_fp.items())
                if cur and cur.get("objs") == fp["objs"] and ("ends" in cur) == is_rel and cur.get("kind") == fp.get("kind")]
        if len(same) == 1:
            return same[0]
    if fp.get("at") is None:
        return None
    strip = {k: v for k, v in fp.items() if k != "ends"}
    hits = [sid for sid, cur in sorted(original_fp.items())
            if cur and cur.get("at") == fp["at"] and ("ends" in cur) == is_rel
            and _same(strip, {k: v for k, v in cur.items() if k != "ends"})]
    return hits[0] if len(hits) == 1 else None


def _retarget(op, original_fp):
    """대상·참조 노드가 다시 추출로 번호만 바뀌었으면 새 번호로 바꾼 연산 사본과 바뀐 (옛, 새) 목록."""
    moved, target, base = [], op.get("target"), op.get("base")
    bound = lambda sid: str(sid).startswith(MANUAL_PREFIX) or INPUT_NAME.match(str(sid))  # noqa: E731  연산에 묶인 id
    if target and not bound(target) and base and not _same(base, original_fp.get(target)):
        alt = _rematch(base, original_fp)
        if alt:  # 같은 자리·같은 종류가 하나뿐: 번호(대상 id나 끝 노드 id)만 바뀐 같은 대상이다
            op = dict(op, target=alt, base=original_fp[alt])
            moved.append((target, alt))
    value, refs = op.get("value"), op.get("refs") or {}
    if isinstance(value, dict):
        repl = {}
        for sid in _refs(value):
            if refs.get(sid) is not None and not bound(sid) and not _same(refs[sid], original_fp.get(sid)):
                alt = _rematch(refs[sid], original_fp)
                if alt and alt != sid:
                    repl[sid] = alt
        if repl:
            value = {k: (repl.get(v, v) if k in REF_KEYS and isinstance(v, str) else v) for k, v in value.items()}
            op = dict(op, value=value, refs={repl.get(k, k): v for k, v in refs.items()})
            moved += sorted(repl.items())
    return op, moved


def apply(extraction, ops):
    """원본(또는 기준) extraction에 덧바르는(overlay) ops를 순서대로 적용한 깊은 사본. 입력은 바꾸지 않는다.
    ops가 비면 같은 내용의 사본("corrections" 키 없음, graph_version 그대로). 입력 연산(split·pipe)은 적용하지 않고
    corrections.input_ops에 적는다(기준 추출에서 적용함, resolve)."""
    doc = copy.deepcopy(extraction)
    if not ops:
        return doc
    st, original_fp = _State(doc), _fingerprints(extraction)
    for op in ops:
        if op.get("op") == "split":
            st.lumps.setdefault(op.get("target"), op.get("op_id"))
    applied, skipped, retargeted, inputs = [], [], [], []
    for op in ops:
        if is_input(op):
            inputs.append(op.get("op_id"))
            continue
        try:
            ids = [op.get("target")] + (_refs(op["value"]) if isinstance(op.get("value"), dict) else [])
            gone = next((i for i in ids if i in st.lumps and i not in st.index), None)
            if gone:  # 나누기로 없어진 덩어리: 같은 자리의 나눈 기호로 옮겨 붙이지 않는다
                raise _Skip("나누기 %s로 덩어리가 나뉘어 대상이 없음" % st.lumps[gone])
            op, moved = _retarget(op, original_fp)
            _apply_one(st, original_fp, op)
        except _Skip as exc:
            skipped.append({"op_id": op.get("op_id"), "reason": str(exc)})
        else:
            applied.append(op["op_id"])
            retargeted += [{"op_id": op["op_id"], "from": a, "to": b} for a, b in moved]
    doc["corrections"] = {"ops": len(ops), "applied": applied, "not_applicable": skipped,
                          "resolved_unknowns": st.resolved}
    if inputs:
        doc["corrections"]["input_ops"] = inputs
    if retargeted:
        doc["corrections"]["retargeted"] = retargeted  # 다시 추출로 번호만 바뀐 대상(지문 위치로 다시 찾음)
    doc["summary"] = summarize(doc)
    return doc


def apply_saved(extraction, name):
    """저장된 수정 기록을 적용한다. 기록이 없으면 같은 내용의 사본."""
    doc = load(name)
    return apply(extraction, doc["ops"] if doc else [])


def _next_op_id(existing_ops, used_ids=()):
    return store_io.next_id("c-%04d", [o.get("op_id") for o in existing_ops] + list(used_ids))


def _via(extraction, ids, existing_ops):
    """ids(대상·참조 노드)가 기댄 입력 연산 op_id 목록. 입력 연산이 만든 노드(pdf-p0-split-<op_id>)이거나, 배관 지정한
    pdf 개체를 근거로 가진 대상이면 그 연산이다."""
    out = []
    objs_of = {}
    for key in ("nodes", "relations", "unresolved_connectors"):
        for o in extraction.get(key) or []:
            objs_of[o["source_object_id"]] = set((o.get("evidence") or {}).get("pdf_objects") or [])
    pipes = [(o["op_id"], set(o["value"]["objects"])) for o in existing_ops
             if o.get("op") == "pipe" and isinstance(o.get("value"), dict) and isinstance(o["value"].get("objects"), list)]
    for sid in ids:
        m = INPUT_NAME.match(str(sid))
        if m:
            out.append(m.group(2))
        out += [oid for oid, objs in pipes if objs & objs_of.get(sid, set())]
    return list(dict.fromkeys(out))


def make_op(original_extraction, op, target, value, by, at=None, op_id=None, existing_ops=(), used_ids=(), name=None):
    """검사를 마친 Op dict. base는 기준 추출(입력 연산을 넣어 다시 추출한 것, 없으면 원본)에서 계산하고 manual 대상이면
    None. 대상이나 참조가 입력 연산이 만든 것에 기대면 via에 그 op_id를 적는다(되돌리기·적용 불가 사유가 쓴다).
    새 op_id는 existing_ops, used_ids, name(추출 이름)의 저장 기록에 나온 번호(issued_op_ids)보다 크게 발급한다.
    지운 연산의 번호를 다시 쓰면 manual- ID가 다른 기기를 가리키게 되기 때문이다. 저장할 기록이 있는 호출은 name을 넘긴다
    (넘기지 않아 겹친 번호는 save가 거절한다).
    existing_ops 뒤에 붙여 적용해 볼 때 적용 불가면 ValueError(사유)."""
    if op not in OPS:
        raise ValueError("알 수 없는 수정 연산: %r" % (op,))
    if OPS[op].stage == "input" and (original_extraction.get("source") or {}).get("format") != "pdf_vector":
        raise ValueError("나누기·배관 지정은 벡터 PDF 도면만 할 수 있음")
    existing_ops = list(existing_ops)
    if name:
        used_ids = set(used_ids) | issued_op_ids(name)
    base, fp = None, _fingerprints(original_extraction)
    if target is not None and not str(target).startswith(MANUAL_PREFIX):
        if target not in fp:
            raise ValueError("원본 추출에 없는 대상: %s" % target)
        base = fp[target]
    refs = {sid: fp.get(sid) for sid in _refs(value)} if isinstance(value, dict) else {}
    new = {"op_id": op_id or _next_op_id(existing_ops, used_ids), "op": op, "target": target, "base": base, "refs": refs,
           "value": copy.deepcopy(value), "by": by, "at": at or now_utc()}
    via = _via(original_extraction, ([target] if target else []) + sorted(refs), existing_ops)
    if via:
        new["via"] = via
    if any(o.get("op_id") == new["op_id"] for o in existing_ops):
        raise ValueError("이미 있는 op_id: %s" % new["op_id"])
    trial = apply(original_extraction, existing_ops + [new])["corrections"]
    for s in trial["not_applicable"]:
        if s["op_id"] == new["op_id"]:
            raise ValueError("수정을 적용할 수 없음: %s" % s["reason"])
    return new


# ---------------------------------------------------------------- 입력 연산: 값 만들기·기준 추출

def dependents(ops, op_id):
    """op_id를 지우면 함께 빠져야 하는 연산 op_id 목록(그 연산이 만든 manual-·split- 대상을 가리키거나 via에 적은 것, 이어서)."""
    out, todo = [], [op_id]
    while todo:
        cur = todo.pop()
        made = {MANUAL_PREFIX + cur}
        for o in ops:
            oid = o.get("op_id")
            if oid == op_id or oid in out:
                continue
            value = o.get("value") if isinstance(o.get("value"), dict) else {}
            ids = [o.get("target")] + [value.get(k) for k in REF_KEYS]
            hit = cur in (o.get("via") or []) or any(
                isinstance(i, str) and (i in made or (INPUT_NAME.match(i) and INPUT_NAME.match(i).group(2) == cur))
                for i in ids)
            if hit:
                out.append(oid)
                todo.append(oid)
    return out


def pdf_source(extraction):
    """(원본 PDF 경로, 쪽) 또는 (None, 사유). 입력 연산은 벡터 PDF 도면에만 쓴다."""
    src = extraction.get("source") or {}
    if src.get("format") != "pdf_vector":
        return None, "벡터 PDF 도면만"
    path = paths.resolve_rel(src.get("file") or "", paths.work_root()) if src.get("file") else None
    if not path or not os.path.isfile(path):
        return None, "원본 PDF 없음"
    try:
        page = int(((extraction.get("run") or {}).get("settings") or {}).get("page_index") or 0)
    except (TypeError, ValueError):
        page = 0
    return (path, max(0, page)), None


def input_value(extraction, objects, **extra):
    """split·pipe 연산의 value: 원본 PDF의 sha256·쪽·pdfplumber 판과 개체 모양을 붙인다. 벡터 PDF가 아니면 ValueError."""
    from hazop.extract.adapters import pdf_vector
    where, why = pdf_source(extraction)
    if where is None:
        raise ValueError("나누기·배관 지정을 할 수 없음: %s" % why)
    shapes = pdf_vector.object_shapes(*where)
    missing = [o for o in objects if o not in shapes]
    if missing:
        raise ValueError("쪽에 없는 pdf 개체: %s" % ", ".join(missing[:5]))
    sha = file_sha256(where[0])
    return dict({"pdf": {"sha256": sha, "page": where[1], "reader": pdf_vector.reader_version()},
                 "objects": list(objects), "shapes": {o: list(shapes[o]) for o in objects}}, **extra)


SHAPE_TOL = 0.2  # pt. 모양으로 다시 찾을 때 상자 허용 차


def _locate(op, shapes, sha, reader):
    """입력 연산의 개체를 지금 쪽에서 찾는다. (지금 id 목록, [(옛 id, 새 id)]). 못 찾으면 _Skip."""
    v = op["value"]
    if v["pdf"]["sha256"] == sha and v["pdf"]["reader"] == reader and all(
            shapes.get(o) == v["shapes"][o] for o in v["objects"]):
        return list(v["objects"]), []
    found, moved, lost = [], [], 0
    for o in v["objects"]:
        want = v["shapes"][o]
        if shapes.get(o) == want:
            found.append(o)
            continue
        hits = [k for k, s in shapes.items() if s[4:] == want[4:] and all(abs(a - b) <= SHAPE_TOL for a, b in zip(s, want[:4]))]
        if len(hits) == 1:
            found.append(hits[0])
            moved.append((o, hits[0]))
        else:
            lost += 1
    what = "나눌" if op["op"] == "split" else "배관"
    if lost:
        raise _Skip("도면이 바뀌어 %s 개체를 찾지 못함(%d개 중 %d개)" % (what, len(v["objects"]), lost))
    twice = sorted(k for k, n in collections.Counter(found).items() if n > 1)
    if twice:
        raise _Skip("도면이 바뀌어 %s 개체 둘 이상이 같은 개체로 짝지어짐(%s)" % (what, ", ".join(twice[:5])))
    return found, moved


_SHA_CACHE = {}


def file_sha256(path):
    """파일 내용의 sha256. (경로, 수정 시각, 크기)가 같으면 다시 읽지 않는다(큰 PDF를 수락마다 읽지 않게)."""
    st = os.stat(path)
    key = (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)
    if key not in _SHA_CACHE:
        with open(path, "rb") as fh:
            _SHA_CACHE[key] = hashlib.sha256(fh.read()).hexdigest()
    return _SHA_CACHE[key]


def _library_version():
    """기호 사전 판: 사전 JSON 파일 내용의 해시(사전이 바뀌면 같은 입력이라도 다시 추출한다). 프로세스에서 한 번 계산한다.
    추출이 쓰는 사전도 프로세스마다 한 번 읽으므로(pdf_vector.symbol_library) 뜻이 같다. 매번 파일 수십 개를 열면 다른
    스레드가 기준 추출을 짓는 동안 수락 한 번이 GIL을 기다려 초 단위로 늘었다."""
    return _library_digest(paths.folder("symbols"))


@functools.lru_cache(maxsize=None)
def _library_digest(root):
    h = hashlib.sha256()
    for dirpath, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for f in sorted(files):
            if f.endswith(".json"):
                with open(os.path.join(dirpath, f), "rb") as fh:
                    h.update(f.encode("utf-8") + b"\0" + fh.read())
    return h.hexdigest()[:16]


# 기준 추출 결과에 닿는 코드: build_base가 부르는 pdf_vector 묶음과 그 모듈 수준 import(hazop 안), 그리고 이 모듈(build_base·
# 종류 고치기). 목록은 pdf_vector의 import 닫힘에서 껍데기(패키지 __init__·paths·store_io)를 뺀 것이다.
# tests/test_corrections_inputs.py가 import 그래프로 이 목록이 닫힘을 덮는지 확인한다.
FINGERPRINT_MODULES = (
    "hazop.extract.corrections",
    "hazop.extract.adapters.pdf_vector",
    "hazop.extract.adapters.pdf_vector_common",
    "hazop.extract.adapters.pdf_vector_connectors",
    "hazop.extract.adapters.pdf_vector_flow",
    "hazop.extract.adapters.pdf_vector_grouping",
    "hazop.extract.adapters.pdf_vector_labels",
    "hazop.extract.adapters.pdf_vector_lines",
    "hazop.extract.drawio",
    "hazop.extract.properties",
    "hazop.extract.rules",
    "hazop.extract.symbols",
    "hazop.kg.docextract",
    "hazop.kg.schema",
)
FINGERPRINT_DATA = (("hazop.kg.schema", "registry.json"),)  # 노드 종류 레지스트리: 모듈 옆 파일(묶음에서도 같은 상대 위치)
_SEP = b"|"


def _code_digest(code, h):
    """코드 개체를 해시에 넣는다. marshal은 참조 수에 따라 바이트가 달라질 수 있어 쓰지 않고, 바이트코드·이름·상수를 직접 넣는다."""
    h.update(code.co_name.encode("utf-8") + _SEP)
    h.update(code.co_code)
    h.update(repr((code.co_argcount, code.co_kwonlyargcount, code.co_flags, code.co_names, code.co_varnames,
                   code.co_freevars, code.co_cellvars)).encode("utf-8"))
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            _code_digest(c, h)
        elif isinstance(c, (frozenset, set)):
            h.update(repr(sorted(map(repr, c))).encode("utf-8"))
        else:
            h.update(repr(c).encode("utf-8"))


def _module_digest(name):
    """모듈 하나의 내용 해시. 소스 .py가 디스크에 있으면 줄끝을 LF로 맞춘 소스, 없으면(PyInstaller 묶음은 코드를 PYZ 안
    바이트코드로만 갖는다) 로더가 주는 코드 개체. 둘 다 못 얻으면 표지만(그 모듈은 규칙 판만으로 갈음)."""
    h = hashlib.sha256()
    spec = importlib.util.find_spec(name)
    origin = getattr(spec, "origin", None)
    if origin and origin.endswith(".py") and os.path.isfile(origin):
        with open(origin, "rb") as fh:
            h.update(b"src" + _SEP + fh.read().replace(b"\r\n", b"\n"))
        return h.hexdigest()
    get_code = getattr(getattr(spec, "loader", None), "get_code", None)
    try:
        code = get_code(name) if get_code is not None else None
    except (ImportError, OSError):
        code = None
    if code is None:
        h.update(b"none")
    else:
        h.update(b"code" + _SEP)
        _code_digest(code, h)
    return h.hexdigest()


def _compute_code_fingerprint(modules=FINGERPRINT_MODULES, data=FINGERPRINT_DATA):
    h = hashlib.sha256()
    for name in modules:
        h.update(name.encode("utf-8") + _SEP + _module_digest(name).encode("ascii") + b"\n")
    for name, fname in data:
        spec = importlib.util.find_spec(name)
        try:
            with open(os.path.join(os.path.dirname(spec.origin), fname), "rb") as fh:
                body = fh.read().replace(b"\r\n", b"\n")
        except (OSError, TypeError, AttributeError):
            body = b"missing"
        h.update(name.encode("utf-8") + b"/" + fname.encode("utf-8") + _SEP + body + b"\n")
    return h.hexdigest()[:16]


@functools.lru_cache(maxsize=None)
def code_fingerprint():
    """추출 코드 지문: FINGERPRINT_MODULES·FINGERPRINT_DATA의 내용 해시(프로세스에서 한 번 계산). 규칙 판(RULES_VERSION)을
    올리지 않고 추출 코드를 고쳐도 옛 기준 추출을 쓰지 않게 한다."""
    return _compute_code_fingerprint()


def _params(original):
    """원본 추출의 설정(run.settings.params). 없으면(옛 추출) None = 기본 설정."""
    return ((original.get("run") or {}).get("settings") or {}).get("params")


def _pdf_now(original):
    """(지금 원본 PDF 경로, 쪽, 파일 sha256, 읽기 엔진 판) 또는 (None, 사유)."""
    from hazop.extract.adapters import pdf_vector
    where, why = pdf_source(original)
    if where is None:
        return None, why
    return (where[0], where[1], file_sha256(where[0]), pdf_vector.reader_version()), None


def _env(original):
    """기준 추출이 입력 연산 말고 기대는 것: 원본 추출(sha256·쪽·설정·실행 id)·지금 원본 PDF 파일의 sha256·읽기 엔진 판·
    규칙 판·추출 코드 지문·기호 사전 판."""
    from hazop.extract.adapters import pdf_vector
    src, run = original.get("source") or {}, original.get("run") or {}
    now, _ = _pdf_now(original)
    return [src.get("sha256"), (run.get("settings") or {}).get("page_index"), _params(original),
            original.get("extraction_run_id"), now and now[2], now and now[3],
            pdf_vector.RULES_VERSION, code_fingerprint(), _library_version()]


def _sig(op):
    """입력 연산이 기준 추출에 주는 몫(op_id·종류·대상·값). 같으면 같은 기준 추출이다."""
    return [op.get("op_id"), op.get("op"), op.get("target"), op.get("value")]


def _hash(prefix, value):
    canon = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return prefix + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]


def inputs_key(original, inputs, env=None):
    """기준 추출의 열쇠: _env와 입력 연산(_sig). 기준 추출 파일에 함께 둔 입력 상태(개체 다시 찾기 결과)도 이 열쇠에만
    기대므로, 열쇠가 맞으면 다시 찾지 않고 그대로 쓴다."""
    return _hash("in-", (env or _env(original)) + [[_sig(o) for o in inputs]])


def base_env_key(original, env=None):
    """inputs_key에서 입력 연산을 뺀 몫. 기준 추출 파일에 적어 두고, 입력이 늘었을 때 앞서 지은 파일을 쓸 수 있는지(partial) 본다."""
    return _hash("env-", env or _env(original))


BASE_KIND = "hazop_input_extraction"
CONTENT_KEYS = ("nodes", "relations", "unresolved_connectors", "texts", "unclassified", "source_locations", "validation")


def base_path(name):
    return os.path.join(paths.output_root("extract"), name, "extraction.inputs.json")


PDF_CHANGED = "원본 PDF가 추출한 뒤 바뀜(도면을 다시 추출해야 나누기를 적용함)"


def build_base(original, inputs):
    """입력 연산으로 원본 PDF를 원래 추출 설정으로 다시 추출한 기준 추출과 입력 상태 {"applied", "not_applicable",
    "retargeted"}. 식별 칸(drawing·source·run 등)은 원본 그대로 두고 내용 칸만 바꾸며, ① 등록정보 검사 결과는 원본에서
    옮긴다. 나누기는 요청한 개체를 모두 새 기호로 떼어 냈을 때만 적용된 것이고, 아니면 적용 불가로 빼고 다시 추출한다
    (적용 불가 연산은 결과에 흔적이 없다). 같은 입력이면 같은 결과다."""
    from hazop.extract.adapters import pdf_vector
    status = {"applied": [], "not_applicable": [], "retargeted": []}
    now, why = _pdf_now(original)
    if now is None or now[2] != (original.get("source") or {}).get("sha256"):
        status["not_applicable"] = [{"op_id": o["op_id"], "reason": why or PDF_CHANGED} for o in inputs]
        return copy.deepcopy(original), status
    path, page, sha, reader = now
    shapes = pdf_vector.object_shapes(path, page)
    todo, claimed, moved_of = [], {}, {}
    for op in inputs:
        try:
            OPS[op["op"]].check(op.get("value") if isinstance(op.get("value"), dict) else {})
            if op["op"] == "pipe":
                raise _Skip(PIPE_PENDING)
            objs, moved = _locate(op, shapes, sha, reader)
            hit = next((o for o in objs if o in claimed), None)
            if hit:
                raise _Skip("나누기 %s와 개체가 겹침(%s)" % (claimed[hit], hit))
        except ValueError as exc:
            status["not_applicable"].append({"op_id": op.get("op_id"), "reason": "형식 오류: %s" % exc})
            continue
        except _Skip as exc:
            status["not_applicable"].append({"op_id": op.get("op_id"), "reason": str(exc)})
            continue
        claimed.update((o, op["op_id"]) for o in objs)
        moved_of[op["op_id"]] = moved
        todo.append((op, objs))
    while todo:
        groups = {}
        for op, objs in todo:
            groups.setdefault(op.get("target"), []).append({"name": "split-" + op["op_id"], "objects": objs})
        fresh = pdf_vector.extract(path, page=page, params=_params(original),
                                   splits=[{"node": None, "groups": g} for g in groups.values()])
        by_sid = {n["source_object_id"]: n for n in fresh["nodes"]}
        failed = []
        for op, objs in todo:
            node = by_sid.get("pdf-p%d-split-%s" % (page, op["op_id"]))
            if node is None:
                failed.append((op, "나눈 개체가 기호가 되지 못함(몸체·선이 없거나 다른 기호에 합쳐짐)"))
                continue
            got = set((node.get("evidence") or {}).get("pdf_objects") or ())
            missing = [o for o in objs if o not in got]
            if missing:
                failed.append((op, "나눌 개체 %d개 가운데 %d개를 나누지 못함(%s)" % (len(objs), len(missing), ", ".join(missing[:5]))))
        if not failed:
            break
        status["not_applicable"] += [{"op_id": op["op_id"], "reason": reason} for op, reason in failed]
        gone = {op["op_id"] for op, _ in failed}
        todo = [(op, objs) for op, objs in todo if op["op_id"] not in gone]
    order = {o.get("op_id"): k for k, o in enumerate(inputs)}
    status["not_applicable"].sort(key=lambda x: order.get(x["op_id"], len(order)))
    if not todo:
        return copy.deepcopy(original), status
    doc = copy.deepcopy(original)
    for key in CONTENT_KEYS:
        doc[key] = fresh[key]
    if (original.get("drawing") or {}).get("identification_basis") == "registration_confirmed":
        doc["validation"] = pdf_vector.carry_registration(fresh["validation"], original["validation"])
    doc["drawing"] = dict(doc.get("drawing") or {}, ignored_objects=(fresh.get("drawing") or {}).get("ignored_objects"))
    by_sid = {n["source_object_id"]: n for n in doc["nodes"]}
    for op, _ in todo:
        kind = op["value"].get("kind")
        if kind:
            _apply_set_kind(None, "node", by_sid["pdf-p%d-split-%s" % (page, op["op_id"])],
                            {"value": {"kind": kind, "category": rules.KIND_CATEGORY[kind]}})
        status["applied"].append(op["op_id"])
        status["retargeted"] += [{"op_id": op["op_id"], "from": a, "to": b} for a, b in moved_of[op["op_id"]]]
    doc["summary"] = summarize(doc)
    return doc, status


def _read_base_file(name):
    try:
        with open(base_path(name), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("kind") == BASE_KIND else None


def _read_base(name, key):
    doc = _read_base_file(name)
    return doc if doc is not None and doc.get("key") == key else None


def _write_base(name, original, inputs, base, status, env=None):
    env = env or _env(original)
    store_io.write_json(base_path(name), {"kind": BASE_KIND, "key": inputs_key(original, inputs, env),
                                          "env": base_env_key(original, env), "built": [_sig(o) for o in inputs],
                                          "inputs": status, "extraction": base})


def _find_base(name, original, inputs):
    """(쓸 기준 추출 파일 또는 None, 그 파일에 든 입력 op_id 집합, 열쇠). 열쇠가 같으면 그 파일. 아니면 같은 환경(base_env_key)에서
    지금 입력의 일부만으로 지은 파일이면 그것(partial: 뒤에 수락한 것만 아직 안 들었다). 지운 입력이 든 파일은 쓰지 않는다."""
    env = _env(original)
    key = inputs_key(original, inputs, env)
    doc = _read_base_file(name)
    if doc is None:
        return None, set(), key
    if doc.get("key") == key:
        return doc, {o.get("op_id") for o in inputs}, key
    now = [_sig(o) for o in inputs]
    built = doc.get("built")
    if doc.get("env") == base_env_key(original, env) and isinstance(built, list) and built and all(b in now for b in built):
        return doc, {b[0] for b in built}, key
    return None, set(), key


def ensure_base(name, original=None, *, should_stop=None):
    """기준 추출 파일을 지금 수정 기록에 맞게 만든다(잠금 없이 작업에서 부른다. 큰 쪽은 수십 초). 상태 문자열을 돌려준다.
    입력 연산 전부를 한 번에 짓는다. 다 만든 뒤 수정 기록이 그새 바뀌었으면 세 번까지 따라잡는다.
    should_stop()이 참이면(더 새 판으로 다시 지을 차례) 지은 것을 쓰지 않고 pending을 돌려준다."""
    stop = should_stop or (lambda: False)
    if original is None:
        with open(os.path.join(paths.output_root("extract"), name, "extraction.json"), encoding="utf-8") as fh:
            original = json.load(fh)
    for _ in range(3):
        if stop():
            return "pending"
        inputs = [o for o in (load(name) or {}).get("ops") or [] if is_input(o)]
        if not inputs:
            return "none"
        key = inputs_key(original, inputs)
        if _read_base(name, key) is not None:
            return "ready"
        base, status = build_base(original, inputs)
        if stop():
            return "pending"
        _write_base(name, original, inputs, base, status)
        again = [o for o in (load(name) or {}).get("ops") or [] if is_input(o)]
        if inputs_key(original, again) == key:
            return "ready"
    return "pending"


def _waiting_on(ops, waiting, skipped):
    """적용 불가로 나온 덮는 연산 가운데 대기 중 입력 연산에 기댄 것 {op_id: [입력 op_id]}(corrections.dependents, 이어서)."""
    out = {}
    for w in waiting:
        for d in dependents(ops, w):
            if d in skipped:
                out.setdefault(d, []).append(w)
    return out


def resolve(name, original=None, ops=None, *, allow_extract=False):
    """수정 기록을 적용한 결과 {"original", "base", "corrected", "ops", "inputs"}.
    inputs: {"key", "state", "applied", "not_applicable", "retargeted", "waiting", "waiting_on"}.
    - state none: 입력 연산 없음, base = 원본. ready: 기준 추출 사용. partial: 앞서 지은 기준 추출(지금 입력의 일부)을 쓰고
      나머지 입력은 대기. pending: 쓸 기준 추출이 없어 원본 위에 덮는 연산만 적용하고 입력 연산은 모두 대기.
    - waiting: 아직 기준 추출에 들지 않은 입력 연산 op_id(기록 차례). applied·not_applicable·retargeted는 든 입력의 결과다.
    - waiting_on: 대기 중 입력에 기댄 덮는 연산 {op_id: [입력 op_id]}. 이것들은 corrected의 not_applicable에서 빼고
      corrections.waiting_on에 적는다(적용 불가가 아니라 대기다).
    allow_extract면 쓸 파일이 없거나 일부만 든 파일일 때 그 자리에서 짓는다. ops를 주면 저장된 기록 대신 쓴다(작업 중 연산)."""
    if original is None:
        with open(os.path.join(paths.output_root("extract"), name, "extraction.json"), encoding="utf-8") as fh:
            original = json.load(fh)
    if ops is None:
        ops = ((load(name) or {}).get("ops") or [])
    inputs = [o for o in ops if is_input(o)]
    state = {"key": None, "state": "none", "applied": [], "not_applicable": [], "retargeted": [], "waiting": [],
             "waiting_on": {}}
    base = original
    if inputs:
        found, built, key = _find_base(name, original, inputs)
        if allow_extract and len(built) < len(inputs):
            extraction, status = build_base(original, inputs)
            _write_base(name, original, inputs, extraction, status)
            found, built = {"inputs": status, "extraction": extraction}, {o.get("op_id") for o in inputs}
        state["key"] = key
        state["waiting"] = [o.get("op_id") for o in inputs if o.get("op_id") not in built]
        if found is None:
            state["state"] = "pending"
        else:
            base = found["extraction"]
            state.update({k: found["inputs"][k] for k in ("applied", "not_applicable", "retargeted")},
                         state="partial" if state["waiting"] else "ready")
    corrected = apply(base, ops)
    if inputs:
        c = corrected.setdefault("corrections", {})
        skipped = {x["op_id"] for x in c.get("not_applicable") or []}
        state["waiting_on"] = _waiting_on(ops, state["waiting"], skipped)
        if state["waiting_on"]:
            c["not_applicable"] = [x for x in c["not_applicable"] if x["op_id"] not in state["waiting_on"]]
            c["waiting_on"] = [{"op_id": k, "inputs": v} for k, v in state["waiting_on"].items()]
        c["inputs"] = {k: state[k] for k in ("state", "applied", "not_applicable")}
        if state["waiting"]:
            c["inputs"]["waiting"] = state["waiting"]
    return {"original": original, "base": base, "corrected": corrected, "ops": ops, "inputs": state}


def pending_inputs(name, original=None, ops=None):
    """대기 중 입력 연산의 자리(화면이 덩어리 안에 흐린 상자로 덧그림). 연산 값의 개체 모양만으로 계산하고 PDF를 읽지 않는다.
    → [{"op_id", "op", "target", "kind", "bbox": [x, y, 너비, 높이](source_locations와 같은 꼴), "objects", "candidate", "by", "at"}]."""
    if original is None:
        with open(os.path.join(paths.output_root("extract"), name, "extraction.json"), encoding="utf-8") as fh:
            original = json.load(fh)
    if ops is None:
        ops = ((load(name) or {}).get("ops") or [])
    inputs = [o for o in ops if is_input(o)]
    if not inputs:
        return []
    _, built, _ = _find_base(name, original, inputs)
    out = []
    for o in inputs:
        if o.get("op_id") in built:
            continue
        boxes = list(((o.get("value") or {}).get("shapes") or {}).values())
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        out.append({"op_id": o.get("op_id"), "op": o.get("op"), "target": o.get("target"), "kind": o["value"].get("kind"),
                    "bbox": [x0, y0, round(x1 - x0, 1), round(y1 - y0, 1)], "objects": len(boxes),
                    "candidate": o.get("ai_candidate"), "by": o.get("by"), "at": o.get("at")})
    return out


# 입력 연산 사유 → 검토 대기열 항목의 (코드, 사람용 글). 왼쪽은 build_base·resolve가 쓰는 사유의 머리다(같은 모듈이 만든 글).
INPUT_REASONS = (
    ("나눈 개체가 기호가 되지 못함", "not_symbol", "고른 부분이 기호 하나로 읽히지 않아 나누지 못했습니다."),
    ("나눌 개체 ", "partly", "고른 부분 가운데 일부를 떼어 내지 못해 나누지 않았습니다."),
    ("나누기 ", "overlap", "다른 나누기와 같은 부분을 골라 나누지 않았습니다."),
    ("도면이 바뀌어 나눌 개체를 찾지 못함", "objects_lost", "도면 파일이 바뀌어 고른 부분을 찾지 못했습니다."),
    ("도면이 바뀌어 배관 개체를 찾지 못함", "objects_lost", "도면 파일이 바뀌어 고른 선을 찾지 못했습니다."),
    ("도면이 바뀌어", "objects_ambiguous", "도면 파일이 바뀌어 고른 부분이 어디인지 하나로 정하지 못했습니다."),
    (PDF_CHANGED, "pdf_changed", "도면 파일이 읽은 뒤 바뀌었습니다. 도면을 다시 읽어야 나누기를 반영합니다."),
    ("원본 PDF 없음", "no_pdf", "원본 도면 파일이 없어 나누기를 반영하지 못했습니다."),
    ("벡터 PDF 도면만", "no_pdf", "이 도면 파일로는 나누기를 할 수 없습니다."),
    ("형식 오류", "format", "저장된 나누기 내용이 올바르지 않아 반영하지 못했습니다."),
    (PIPE_PENDING, "pipe_pending", "배관 지정은 아직 도면 다시 읽기에 넣지 않습니다."),
)
WAITING_TEXT = {"waiting": "아직 도면에 반영하기 전인 나누기입니다. 다시 읽기가 끝나면 반영됩니다.",
                "waiting_on": "반영하기 전인 나누기에 기댄 고침입니다. 나누기가 반영되면 함께 적용됩니다."}
OTHER_TEXT = "나누기를 반영하지 못했습니다."


def input_reason(reason):
    """입력 연산의 적용 불가 사유 글 → (코드, 사람용 글)."""
    for head, code, text in INPUT_REASONS:
        if reason.startswith(head):
            return code, text
    return "other", OTHER_TEXT


def input_items(resolved):
    """resolve 결과 → 검토 대기열 항목 [{"op_id", "op", "target", "candidate", "state": "waiting"|"not_applicable",
    "code", "text", "inputs"}]. 대기 중 입력(waiting), 대기 중 입력에 기댄 고침(waiting_on, state도 waiting),
    든 입력 가운데 적용 불가(사유 코드와 글). inputs는 waiting_on 항목이 기댄 입력 op_id. 기록 차례."""
    st, by_id = resolved["inputs"], {o.get("op_id"): o for o in resolved["ops"]}
    na = {x["op_id"]: x["reason"] for x in st["not_applicable"]}
    out = []
    for oid, o in by_id.items():
        if oid in st["waiting"]:
            row = ("waiting", "waiting", WAITING_TEXT["waiting"], [])
        elif oid in st["waiting_on"]:
            row = ("waiting", "waiting_on", WAITING_TEXT["waiting_on"], st["waiting_on"][oid])
        elif oid in na:
            row = ("not_applicable",) + input_reason(na[oid]) + ([],)
        else:
            continue
        out.append({"op_id": oid, "op": o.get("op"), "target": o.get("target"), "candidate": o.get("ai_candidate"),
                    "state": row[0], "code": row[1], "text": row[2], "inputs": row[3]})
    return out
