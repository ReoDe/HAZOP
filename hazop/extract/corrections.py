"""② 도면 사람 수정 기록: 원본 추출은 그대로 두고 수정 기록(연산 목록)을 그 위에 적용한다.

기록 파일: <작업 루트>/데이터/도면수정/<safe_name(추출 폴더 이름)>.json. 연산은 OPS 표(이름 → 대상 종류, 값 검사,
적용 함수, 해소하는 미확인)로 적용한다. 대상은 source_object_id(다시 추출해도 안정)로 가리키고, 사람이 추가한 기기·연결의
id는 "manual-" + op_id다. 적용할 수 없는 연산은 사유와 함께 건너뛰고 나머지는 계속 적용한다.
"""

import copy
import json
import math
import os
from dataclasses import dataclass
from typing import Callable

from hazop import paths
from hazop.extract import rules
from hazop.extract.drawio import summarize
from hazop.kg.build import write_json_atomic
from hazop.kg.schema import REGISTRY
from hazop.study.nodes import now_utc

KIND = "hazop_drawing_corrections"
SCHEMA_VERSION = "0.1"
MANUAL_PREFIX = "manual-"
RELATION_KINDS = ("physical_connection", "signal_connection", "measurement_connection")
ENDS = ("source", "target")


class _Skip(Exception):
    """적용 불가(not_applicable) 사유."""


# 문구를 바꾼 미확인 사유: 옛 문구로 저장된 확정 기록이 새 문구의 미확인도 지우게 한다(M2에서 고장 위치 검사를 전동 밸브까지 넓힘).
RENAMED_REASONS = {"제어밸브 실패 위치 미확인": "밸브 고장 위치 미확인"}

def store_path(name):
    return paths.work_path("데이터", "도면수정", paths.safe_name(name) + ".json")


def load(name):
    """수정 기록 문서. 없으면 None, 다른 종류 파일이면 ValueError."""
    path = store_path(name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("도면 수정 기록 파일이 아님: %s" % path)
    return doc


def save(name, ops, by, drawing_number=None, at=None):
    """ops 전체를 저장하고 이전 파일과 비교한 op_id 증감을 log에 덧붙인다. 임시 파일에 쓴 뒤 교체. 쓴 경로를 돌려준다.
    지운 연산은 내용까지 log의 removed_ops에 남긴다(지운 사람 수정도 기록에서 찾을 수 있게)."""
    prev = load(name) or {}
    ops = [dict(o) for o in ops]
    before = [o["op_id"] for o in prev.get("ops") or []]
    after = [o["op_id"] for o in ops]
    removed = [o for o in prev.get("ops") or [] if o["op_id"] not in after]
    doc = {
        "kind": KIND, "schema_version": SCHEMA_VERSION, "extraction_name": name,
        "drawing_number": drawing_number if drawing_number is not None else prev.get("drawing_number"),
        "ops": ops,
        "log": list(prev.get("log") or []) + [{
            "at": at or now_utc(), "by": by, "action": "save",
            "added": [i for i in after if i not in before], "removed": [o["op_id"] for o in removed],
            "removed_ops": removed}],
    }
    path = store_path(name)
    write_json_atomic(path, doc)
    return path


def issued_op_ids(name):
    """저장 기록에 한 번이라도 나온 op_id(지금 연산과 log의 추가·삭제). 새 op_id는 이 번호들과 겹치지 않게 발급한다."""
    doc = load(name) or {}
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


# ---------------------------------------------------------------- 적용 상태

class _State:
    """고치는 중인 extraction 사본과 source_object_id 색인."""

    def __init__(self, doc):
        self.doc = doc
        self.deleted = set()
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
    obj.setdefault("attributes", {})["kind"] = obj["kind"]
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


@dataclass(frozen=True)
class OpSpec:
    targets: tuple  # 빈 튜플이면 대상 없이 새로 만드는 연산
    check: Callable  # value -> None, 형식 오류면 ValueError
    apply: Callable  # (state, 대상 종류, 대상, op) -> human_edit를 붙일 대상 또는 None
    resolves: Callable  # (unknown, 대상 종류, value) -> 이 연산으로 지울 미확인인가


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
}


# ---------------------------------------------------------------- 지문·연산 만들기·적용

def fingerprint(kind, obj, loc=None):
    """base 비교용 대상 지문. 노드 {kind, category, tag, at}, 관계 {kind, ends: 양 끝 노드 source_object_id, at}.
    at = 위치 상자 중심(정수 반올림). PDF 대상 ID는 순번이라 다시 추출하면 같은 ID가 다른 기호를 가리킬 수 있어 위치로 가른다."""
    at = [round(loc["bbox"][0] + loc["bbox"][2] / 2.0), round(loc["bbox"][1] + loc["bbox"][3] / 2.0)] if loc else None
    if kind == "node":
        return {"kind": obj.get("kind"), "category": obj.get("category"), "tag": obj.get("tag"), "at": at}
    return {"kind": obj.get("kind"), "ends": [ep.get("source_object_id") for ep in obj["endpoints"]], "at": at}


def _fingerprints(extraction):
    locs = {loc["local_id"]: loc for loc in extraction["source_locations"]}
    out = {n["source_object_id"]: fingerprint("node", n, locs.get(n["local_id"])) for n in extraction["nodes"]}
    for key in ("relations", "unresolved_connectors"):
        out.update((r["source_object_id"], fingerprint("relation", r, locs.get(r["local_id"]))) for r in extraction[key])
    return out


REF_KEYS = ("from", "to", "node")  # value 안에서 노드를 가리키는 키


def _same(base, cur):
    """지문 비교. 분류(category)는 kind에서 레지스트리로 정해지므로 보지 않는다(레지스트리 분류 이동만으로 옛 연산이
    '대상이 바뀜'이 되지 않게, M2 U9)."""
    if base is None or cur is None:
        return base is cur
    return {k: v for k, v in base.items() if k != "category"} == {k: v for k, v in cur.items() if k != "category"}


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
            raise _Skip("대상 없음")
        kind, obj = st.index[target]
        if kind not in spec.targets:
            raise _Skip("형식 오류: %s는 %s 대상에 쓸 수 없음" % (op["op"], kind))
        if not str(target).startswith(MANUAL_PREFIX) and not _same(op.get("base"), original_fp.get(target)):
            cur, base = original_fp.get(target) or {}, op.get("base") or {}
            diff = ["%s %r→%r" % (k, base.get(k), cur.get(k)) for k in sorted(set(cur) | set(base))
                    if base.get(k) != cur.get(k) and k != "category"]
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


def apply(extraction, ops):
    """원본 extraction에 ops를 순서대로 적용한 깊은 사본. 입력은 바꾸지 않는다.
    ops가 비면 같은 내용의 사본("corrections" 키 없음, graph_version 그대로)."""
    doc = copy.deepcopy(extraction)
    if not ops:
        return doc
    st, original_fp = _State(doc), _fingerprints(extraction)
    applied, skipped = [], []
    for op in ops:
        try:
            _apply_one(st, original_fp, op)
        except _Skip as exc:
            skipped.append({"op_id": op.get("op_id"), "reason": str(exc)})
        else:
            applied.append(op["op_id"])
    doc["corrections"] = {"ops": len(ops), "applied": applied, "not_applicable": skipped,
                          "resolved_unknowns": st.resolved}
    doc["summary"] = summarize(doc)
    return doc


def apply_saved(extraction, name):
    """저장된 수정 기록을 적용한다. 기록이 없으면 같은 내용의 사본."""
    doc = load(name)
    return apply(extraction, doc["ops"] if doc else [])


def _next_op_id(existing_ops, used_ids=()):
    ids = [str(o.get("op_id", "")) for o in existing_ops] + [str(i) for i in used_ids]
    nums = [int(i[2:]) for i in ids if i.startswith("c-") and i[2:].isdigit()]
    return "c-%04d" % (max(nums, default=0) + 1)


def make_op(original_extraction, op, target, value, by, at=None, op_id=None, existing_ops=(), used_ids=()):
    """검사를 마친 Op dict. base는 원본 추출(수정 전)에서 계산하고 manual 대상이면 None.
    새 op_id는 existing_ops와 used_ids(issued_op_ids: 저장 기록에 나온 번호)보다 크게 발급한다.
    지운 연산의 번호를 다시 쓰면 manual- ID가 다른 기기를 가리키게 되기 때문이다.
    existing_ops 뒤에 붙여 적용해 볼 때 적용 불가면 ValueError(사유)."""
    if op not in OPS:
        raise ValueError("알 수 없는 수정 연산: %r" % (op,))
    existing_ops = list(existing_ops)
    base, fp = None, _fingerprints(original_extraction)
    if target is not None and not str(target).startswith(MANUAL_PREFIX):
        if target not in fp:
            raise ValueError("원본 추출에 없는 대상: %s" % target)
        base = fp[target]
    refs = {sid: fp.get(sid) for sid in _refs(value)} if isinstance(value, dict) else {}
    new = {"op_id": op_id or _next_op_id(existing_ops, used_ids), "op": op, "target": target, "base": base, "refs": refs,
           "value": copy.deepcopy(value), "by": by, "at": at or now_utc()}
    if any(o.get("op_id") == new["op_id"] for o in existing_ops):
        raise ValueError("이미 있는 op_id: %s" % new["op_id"])
    trial = apply(original_extraction, existing_ops + [new])["corrections"]
    for s in trial["not_applicable"]:
        if s["op_id"] == new["op_id"]:
            raise ValueError("수정을 적용할 수 없음: %s" % s["reason"])
    return new
