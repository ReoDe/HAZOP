"""DEXPI 읽기 결과(dexpi_read.Model) -> 추출 결과(extraction.json) (HZ-PLN-22 §3·§5).

그림을 인식하지 않고 파일에 적힌 구조를 옮기는 변환이다. 추출 결과의 공통 계약은 drawio·PDF 추출과 같아서 그래프 변환
(hazop.graph.build)과 사람 수정·미확인 목록이 바뀌지 않는다. `run.read_method`는 'dexpi'다.
- 노즐은 노드로 만들지 않고 배관 끝의 포트(port)로 바꾼다(V-3). 노즐의 원래 목록은 설비 attributes["dexpi:nozzles"]에 둔다.
- 흐름 방향은 연결의 Source->Target으로 정하지 않는다(F13). 흐름 화살표·도면 연결 기호만 declared로 쓴다(§5.4).
- 대응이 없는 클래스는 미분류 노드로 가져오고 원문 조각을 근거에 남긴다(§5.5).
같은 파일은 같은 결과가 나온다(파일 안 순서, 시각 없음).
"""

import hashlib
import json
import math
import re

from hazop.extract import dexpi_map, properties, rules
from hazop.extract.adapters import dexpi_read

SCHEMA_VERSION = "0.1"
SIDECAR_SCHEMA = "hazop_dexpi_sidecar/1"  # hazop.export.dexpi_export와 같은 값
SCRIPT_NAME = "hazop.extract.adapters.dexpi_import"
SCRIPT_VERSION = "0.1.0"
RULES_VERSION = "dexpi-import-2026-11-13"
COORDINATE_SPACE = "dexpi_diagram"
FLOW_COS = 0.7  # 화살표 방향이 연결 방향과 이 값 이상 맞아야 흐름으로 읽는다

_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
TAGGED_CATEGORIES = ("equipment", "valve", "instrument")
UNIT_NAMES = {"Bar": "bar", "MegaPascal": "MPa", "KiloPascal": "kPa", "Pascal": "Pa", "DegreeCelsius": "°C",
              "Kelvin": "K", "DegreeFahrenheit": "°F"}
# 설비 속성 이름 -> (우리 속성, 챔버 안의 이름). 챔버가 하나일 때만 설비 값으로 올린다(§3.5)
CHAMBER_FIELDS = {"design_pressure_max": "UpperLimitDesignPressure", "design_pressure_min": "LowerLimitDesignPressure",
                  "design_temperature_max": "UpperLimitDesignTemperature",
                  "design_temperature_min": "LowerLimitDesignTemperature", "material": "MaterialOfConstructionCode"}
# 태그를 만드는 데 쓰고도 attributes에 남기는 조각: 계기의 구분 문자·번호·기능 문자(태그만으로는 되돌릴 수 없다, §3.5)와 노즐 이름
KEEP_TAG_FIELDS = ("SubTagName", "ProcessInstrumentationFunctionCategory", "ProcessInstrumentationFunctionNumber",
                   "ProcessInstrumentationFunctions")
TAG_FIELDS = ("TagName", "TagNamePrefix", "TagNameSequenceNumber", "TagNameSuffix", "PipingComponentNumber",
              "SubTagName", "PositionNumber", "ProcessInstrumentationFunctionCategory",
              "ProcessInstrumentationFunctionNumber", "ProcessInstrumentationFunctions")


def _issue(lst, check, reason, source_object_id=None, target=None, field=None):
    lst.append({"check": check, "target": target, "source_object_id": source_object_id, "field": field,
                "reason": reason})


def _clean(v):
    return round(v, 3) if isinstance(v, float) else v


def _local_id(source_id, used):
    base = "dx-" + _NAME_CHARS.sub("_", source_id or "item")
    cand, n = base, 1
    while cand in used:
        n += 1
        cand = "%s~%d" % (base, n)
    used.add(cand)
    return cand


def _pretty_quantity(text):
    """'60.0 PressureGaugeUnit.Bar' -> '60.0 bar(g)'. 모르는 단위는 원문 그대로."""
    m = re.fullmatch(r"(\S+) (\w+Unit)\.(\w+)", text or "")
    if not m:
        return text
    unit = UNIT_NAMES.get(m.group(3))
    if unit is None:
        return text
    suffix = "(g)" if m.group(2) == "PressureGaugeUnit" else "(a)" if m.group(2) == "PressureAbsoluteUnit" else ""
    return "%s %s%s" % (m.group(1), unit, suffix)


def _tag_of(item):
    """(태그 또는 None, 근거 또는 None). 규칙은 §3.5."""
    a = item["attrs"]
    group, cls = item["group"], item["cls"]
    if group == "instrument":
        cat, num = a.get("ProcessInstrumentationFunctionCategory"), a.get("ProcessInstrumentationFunctionNumber")
        if cat and num:
            return cat + num, "계측 기능 구분 문자와 번호"
        return None, None
    if group == "equipment":
        if a.get("TagName"):
            return a["TagName"], "TagName"
        joined = "".join(a.get(k) or "" for k in ("TagNamePrefix", "TagNameSequenceNumber", "TagNameSuffix"))
        return (joined, "조각 결합") if joined else (None, None)
    if a.get("PipingComponentNumber"):
        return a["PipingComponentNumber"], "PipingComponentNumber"
    if a.get("SubTagName"):
        return a["SubTagName"], "SubTagName"
    if a.get("PositionNumber"):
        return a["PositionNumber"], "PositionNumber"
    return None, None


def _node_entry(model, node_id):
    p = model.node_pos.get(node_id)
    return {"id": node_id, "position": [_clean(p[0]), _clean(p[1])] if p is not None else None}


def _bbox(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [_clean(min(xs)), _clean(min(ys)), _clean(max(xs) - min(xs)), _clean(max(ys) - min(ys))]


def _points_of(model, item):
    pts = [model.node_pos[n] for n in item.get("nodes", []) if n in model.node_pos]
    for nz in item.get("nozzles", []):
        pts += [model.node_pos[n] for n in model.nozzles[nz]["nodes"] if n in model.node_pos]
    if item.get("position") is not None:
        pts.append(item["position"])
    return pts


def build(model, source, registration=None, page=0, repo_root=None):
    """Model -> 추출 결과 dict. source: {"file", "sha256", "size_bytes"}. registration: 등록정보(드로이오와 같은 규칙)."""
    unknowns, blockers = [], []
    used = set()
    reg = registration or {}
    local_of = {}  # 항목 id -> local_id
    nodes, source_locations = [], []

    for dup in sorted(set(model.duplicate_ids)):
        _issue(blockers, "duplicate_id", "같은 id가 두 번 이상 나타남(어느 객체인지 정할 수 없음)", dup)
    for iss in model.issues:
        _issue(unknowns, iss["check"], iss["reason"], iss.get("target"))

    # ---- 구동계: 밸브 id -> {fail_action, loop} (구동 기능이 신호 흐름의 끝이면 제어 밸브)
    controlled = {}
    signal_targets = {f["target"] for f in model.info_flows if f["cls"] and "SignalConveyingFunction" in dexpi_map.ancestry(f["cls"])
                      and f["cls"] != "MeasuringLineFunction"}
    for fn_id, systems in model.actuating.items():
        for sid in systems:
            entry = model.act_systems.get(sid)
            if entry is None:
                continue
            for valve in entry["valves"]:
                controlled[valve] = {"fail_action": entry["fail_action"], "in_loop": fn_id in signal_targets,
                                     "number": entry["number"]}
    for sid, entry in model.act_systems.items():  # 구동 기능 없이 구동계만 있는 파일(Proteus 일부)
        for valve in entry["valves"]:
            controlled.setdefault(valve, {"fail_action": entry["fail_action"], "in_loop": False, "number": entry["number"]})

    # ---- 노드
    for item in model.items.values():
        iid, group, cls = item["id"], item["group"], item["cls"]
        local = _local_id(iid, used)
        local_of[iid] = local
        kind, mapped_cls = dexpi_map.import_kind(cls, group) if cls else (None, None)
        attrs = {}
        extra_unknown = []
        if group == "instrument":
            variable = item["attrs"].get("ProcessInstrumentationFunctionCategory")
            kind = dexpi_map.instrument_kind(variable, item["attrs"].get("ProcessInstrumentationFunctions"))
        if kind == "manual_valve" and iid in controlled:
            info = controlled[iid]
            if info["in_loop"]:
                kind = "control_valve"
            else:
                kind = None  # 구동 방식을 지어내지 않는다(§3.4)
                extra_unknown.append(("dexpi_actuator_kind_unknown", "구동계가 있으나 구동 방식을 알 수 없음", "kind"))
        classification = "classified" if kind is not None else "unclassified"
        if kind is not None and rules.KIND_CATEGORY.get(kind):
            category = rules.KIND_CATEGORY[kind]
        else:
            category = "valve" if (kind is None and iid in controlled) else dexpi_map.raw_category(group)
        tag, tag_basis = _tag_of(item)
        if kind is not None:
            attrs["kind"] = kind
        if tag:
            attrs["tag"] = tag
        attrs["dexpi:type"] = cls or ""
        if iid in controlled:
            fa = controlled[iid]["fail_action"]
            if fa and dexpi_map.FAIL_ACTION.get(fa):
                attrs["fail_position"] = dexpi_map.FAIL_ACTION[fa]
            elif fa:
                attrs["dexpi:FailAction"] = fa
            if controlled[iid]["number"]:
                attrs["dexpi:ActuatingSystemNumber"] = controlled[iid]["number"]
        if group == "equipment":
            chambers = item.get("chambers") or []
            if len(chambers) == 1:
                for ours, theirs in CHAMBER_FIELDS.items():
                    if chambers[0].get(theirs):
                        attrs[ours] = _pretty_quantity(chambers[0][theirs])
            elif len(chambers) > 1:
                attrs["dexpi:chambers"] = json.dumps(chambers, ensure_ascii=False, sort_keys=True)
            if item.get("nozzles"):
                attrs["dexpi:nozzles"] = json.dumps(
                    [{"id": n, "class": model.nozzles[n]["cls"], "port": model.nozzles[n]["port"],
                      "attributes": model.nozzles[n]["attrs"],
                      "nodes": [_node_entry(model, nid) for nid in model.nozzles[n]["nodes"]]} for n in item["nozzles"]],
                    ensure_ascii=False, sort_keys=True)
        if item.get("nodes"):  # 노드 id와 그림 위치(내보낼 때 같은 id·위치로 되쓴다, §7.1)
            attrs["dexpi:nodes"] = json.dumps([_node_entry(model, nid) for nid in item["nodes"]], ensure_ascii=False,
                                              sort_keys=True)
        for name, value in item["attrs"].items():
            if name in TAG_FIELDS and name not in KEEP_TAG_FIELDS:
                continue
            if group == "equipment" and name in CHAMBER_FIELDS.values():
                continue
            if name == "FlowDirection":
                continue
            attrs.setdefault("dexpi:" + name, _pretty_quantity(value) if value else value)
        if item.get("segment"):
            attrs["dexpi:segment"] = item["segment"]
        if group == "offpage":  # 도면 연결 기호: 방향은 클래스 이름(FlowIn·FlowOut)에서, 참조는 있을 때만(§3.1)
            ref = item.get("reference") or {}
            if ref.get("drawing"):
                attrs["to_drawing"] = ref["drawing"]
            if ref.get("connector") or ref.get("object"):
                attrs["to_object"] = ref.get("connector") or ref.get("object")
            system = model.systems.get(item.get("system"), {}).get("attrs", {})
            if system.get("LineNumber"):
                attrs["line_no"] = system["LineNumber"]
            if cls and "FlowOut" in cls:
                attrs["direction"] = "TO"
            elif cls and "FlowIn" in cls:
                attrs["direction"] = "FROM"
        evidence = {"dexpi": {"type": cls, "id": iid if item.get("has_id", True) else None,
                              "xml": item["xml"], "xml_cut": bool(item.get("xml_cut"))}}
        if tag_basis and tag_basis != "TagName":
            evidence["tag_basis"] = tag_basis
        node = {"local_id": local, "source_object_id": iid, "classification": classification, "category": category,
                "kind": kind, "tag": tag, "label": tag or "", "label_text": tag or "", "label_location": None,
                "attributes": {k: v for k, v in attrs.items() if v is not None}, "style": "", "parent": None,
                "geometry": None, "evidence": evidence}
        if kind == "check_valve":
            node["check_direction"] = None
            _issue(unknowns, "unknown_check_valve_direction", "DEXPI에 체크밸브 허용 방향이 없음", iid, local, "flow_direction")
        if kind is None:
            _issue(unknowns, "dexpi_unmapped_class", "대응표에 없는 DEXPI 클래스 %s" % cls, iid, local, "kind")
        for check, reason, field in extra_unknown:
            _issue(unknowns, check, reason, iid, local, field)
        if tag is None and (category in TAGGED_CATEGORIES) and group != "offpage":
            _issue(unknowns, "missing_tag", "태그를 읽을 수 없음", iid, local, "tag")
        for check, field, reason in properties.node_issues(kind, {k: v for k, v in node["attributes"].items()
                                                                  if not k.startswith("dexpi:")}):
            _issue(unknowns, check, reason, iid, local, field)
        pts = _points_of(model, item)
        if pts:
            loc = {"object_id": iid, "local_id": local, "coordinate_space": COORDINATE_SPACE, "unit": "mm",
                   "bbox": _bbox(pts), "approximate": True, "method": "dexpi_positions"}
            source_locations.append(loc)
        else:
            _issue(unknowns, "dexpi_no_position", "그림 위치 없음(DEXPI 파일에 그림 정보가 없음)", iid, local, "bbox")
        nodes.append(node)

    # ---- 끝점 풀이: 노즐은 부모 설비로, 포트는 노즐 이름
    def resolve(item_id, node_id):
        """-> (node local_id 또는 None, 포트, 상태, 사유)"""
        if item_id is None:
            return None, None, "unconnected", "끝이 어떤 객체에도 붙어 있지 않음"
        if item_id in model.nozzles:
            noz = model.nozzles[item_id]
            return local_of.get(noz["parent"]), noz["port"], "connected", None
        if item_id in local_of:
            return local_of[item_id], None, "connected", None
        return None, None, "invalid_reference", "참조한 객체 %r 가 파일에 없음" % item_id

    def endpoint_point(item_id, node_id):
        p = dexpi_read._endpoint_position(model, item_id, node_id)
        return [_clean(p[0]), _clean(p[1])] if p is not None else None

    relations, unresolved = [], []
    rel_no = 0

    def line_attrs(seg_id):
        seg = model.segments.get(seg_id, {"attrs": {}, "system": None})
        system = model.systems.get(seg.get("system"), {"attrs": {}})["attrs"]
        merged = dict(system)
        merged.update(seg["attrs"])
        out = {"line_type": "process"}
        pairs = (("line_no", system.get("LineNumber")), ("fluid_code", merged.get("FluidCode")),
                 ("pipe_class", merged.get("PipingClassCode")),
                 ("nominal_diameter", merged.get("NominalDiameterRepresentation")
                  or merged.get("NominalDiameterNumericalValueRepresentation")))
        for k, v in pairs:
            if v:
                out[k] = v
        if seg_id:
            out["dexpi:segment"] = seg_id
        if seg.get("system"):
            out["dexpi:system"] = seg["system"]
        return out

    def add_relation(kind, line_type, c_id, src, dst, extra_attrs, flow=None, waypoints=None):
        nonlocal rel_no
        rel_no += 1
        lid = _local_id(c_id, used)
        ends, ok = [], True
        for end, (item_id, node_id) in (("source", src), ("target", dst)):
            local, port, status, why = resolve(item_id, node_id)
            ep = {"end": end, "node_local_id": local, "source_object_id": item_id, "constraint": None,
                  "point": endpoint_point(item_id, node_id), "point_basis": "dexpi_node" if node_id in model.node_pos
                  else ("dexpi_item_position" if item_id else None), "status": status, "port": port}
            if status != "connected":
                ok = False
                _issue(unknowns, "unconnected_endpoint", "%s %s" % (end, why), c_id, lid, end)
            ends.append(ep)
        attrs = dict(extra_attrs)
        rec = {"local_id": lid, "source_object_id": c_id, "kind": kind, "line_type": line_type,
               "line_no": attrs.get("line_no"), "endpoints": ends, "flow_direction": None if not ok else flow,
               "waypoints": waypoints or [], "label": "", "label_text": "", "label_cells": [], "attributes": attrs,
               "style": "", "parent": None, "geometry": None}
        (relations if ok else unresolved).append(rec)
        pts = [e["point"] for e in ends if e["point"] is not None]
        if pts:
            source_locations.append({"object_id": c_id, "local_id": lid, "coordinate_space": COORDINATE_SPACE,
                                     "unit": "mm", "bbox": _bbox(pts), "approximate": True, "method": "dexpi_endpoints"})
        elif ok:
            _issue(unknowns, "dexpi_no_position", "그림 위치 없음(DEXPI 파일에 그림 정보가 없음)", c_id, lid, "bbox")
        return rec

    # ---- 흐름: 도면 연결 기호와 화살표(§5.4)
    assumed_seen = set()
    arrow_of = _arrow_flows(model)
    for idx, c in enumerate(model.connections):
        c_id = c["id"] or c["synthetic_id"]
        attrs = line_attrs(c["segment"])
        if c.get("order") is not None:
            attrs["dexpi:segment_order"] = str(c["order"])
        for item_id in c.get("assumed_items") or []:
            if (item_id, c["segment"]) not in assumed_seen:
                assumed_seen.add((item_id, c["segment"]))
                _issue(unknowns, "dexpi_item_order_assumed", "어느 연결의 끝에도 없는 부품을 문서 순서로 길에 끼움", item_id,
                       local_of.get(item_id), "kind")
        flow, basis = _flow_of(model, c, arrow_of.get(idx))
        flow_dict = None
        src_local = resolve(c["source"], c["source_node"])[0]
        dst_local = resolve(c["target"], c["target_node"])[0]
        if flow is not None and src_local and dst_local:
            first, last = ("source", "target") if flow == "forward" else ("target", "source")
            a, b = (src_local, dst_local) if flow == "forward" else (dst_local, src_local)
            flow_dict = {"from": a, "to": b, "from_end": first, "to_end": last, "basis": basis}
            attrs["flow_direction"] = "source_to_target" if flow == "forward" else "target_to_source"
        flow_class = _flow_class(model, c["segment"])
        if flow_class:
            attrs["flow_class"] = flow_class
        rec = add_relation("physical_connection", "process", c_id, (c["source"], c["source_node"]),
                           (c["target"], c["target_node"]), attrs, flow_dict)
        for end, key in (("source", "source_node_no"), ("target", "target_node_no")):
            if c.get(key):
                for ep in rec["endpoints"]:
                    if ep["end"] == end:
                        ep["attributes"] = {"dexpi:node": c[key]}
        if flow_dict is None and rec in relations:
            _issue(unknowns, "unknown_flow_direction",
                   "양방향 흐름 구간(DEXPI DualFlow): 한쪽으로 확정하지 않음" if flow_class == "dual"
                   else "DEXPI 연결의 Source·Target은 흐름 방향이 아님(근거 없음)", c_id, rec["local_id"], "flow_direction")

    # ---- 계장 연결: 측정선(센서 위치 -> 계측 기능), 신호선(계측 기능 -> 구동 대상)
    for flow in model.info_flows:
        cls = flow["cls"] or ""
        src, tgt = flow["source"], flow["target"]
        if cls == "MeasuringLineFunction" or "MeasuringLineFunction" in dexpi_map.ancestry(cls):
            sens = model.sensing.get(src, {})
            loc_item = sens.get("item")
            pif = tgt if tgt in model.items else sens.get("pif")
            if loc_item and loc_item in model.segments:
                _issue(unknowns, "unconnected_endpoint", "측정 위치가 배관 구간이라 구성요소에 붙이지 못함", flow["id"], None, "source")
                loc_item = None
            add_relation("measurement_connection", "instrument_tap", flow["id"] or "measuring-line",
                         (loc_item, None), (pif, None), {"line_type": "instrument_tap"})
        else:
            targets = []
            if tgt in model.items:
                targets = [tgt]
            elif tgt in model.actuating:
                for sid in model.actuating[tgt]:
                    targets += model.act_systems.get(sid, {}).get("valves", [])
            if not targets:
                targets = [None]
            for n, t in enumerate(targets):
                cid = flow["id"] if n == 0 else "%s#%d" % (flow["id"], n + 1)
                add_relation("signal_connection", "signal", cid or "signal-line", (src, None), (t, None),
                             {"line_type": "signal"})

    # ---- 도면 정보와 식별
    drawing_number, drawing_name = model.drawing["number"], model.drawing["name"]
    ignored = []
    drawing = {"page_width": _clean(model.drawing["width"]), "page_height": _clean(model.drawing["height"]),
               "title_block": {}, "drawing_number": None, "title": None, "revision": None, "note": None,
               "ignored_objects": ignored}
    if registration is None:
        drawing["drawing_number"], drawing["title"] = drawing_number, drawing_name
        if drawing_number is None:
            _issue(unknowns, "missing_drawing_number", "DEXPI 파일에 도면 번호가 없음", field="drawing_number")
        for field in ("project_id", "material_id", "registration_version"):
            _issue(unknowns, "not_registered", "자료 등록 단계 미연동으로 %s 없음" % field, field=field)
    else:
        drawing["identification_basis"] = "registration_confirmed"
        drawing["title_block_candidates"] = {"drawing_number": drawing_number, "revision": None, "title": drawing_name}
        for field, reg_field in (("drawing_number", "drawing_number"), ("revision", "design_revision"), ("title", "title")):
            drawing[field] = reg.get(reg_field)
        reg_val = reg.get("validation") or {}
        if reg.get("status") != "registered" or reg_val.get("status") != "passed" or reg_val.get("blockers"):
            _issue(blockers, "registration_not_completed", "등록 완료(registered·passed)가 아닌 등록정보: status=%r"
                   % reg.get("status"), field="status")
        if reg.get("sha256") != source["sha256"]:
            _issue(blockers, "registration_hash_mismatch", "입력 파일 해시가 등록정보의 sha256과 다름", field="sha256")
        for u in reg.get("validation", {}).get("unknowns", []):
            _issue(unknowns, "registration_unknown", "등록 단계 미확인: %s" % u["reason"], field=u["field"])
    if model.diagram_count > 1:
        _issue(unknowns, "dexpi_multiple_diagrams", "도면(Diagram)이 %d개인 파일: 첫 도면 기준으로 읽음" % model.diagram_count)
    if model.process_objects:
        _issue(unknowns, "dexpi_process_model_skipped", "공정 모델(Process) 객체 %d개는 가져오지 않음" % model.process_objects)
    if model.diagram_count == 0:
        _issue(unknowns, "dexpi_no_position", "그림(Diagram) 없이 설비 모델만 있는 파일", field="bbox")

    sha = source["sha256"]
    run_id = "extract-%s-p%d-dexpi-%s-%s" % (drawing_number or drawing_name or "page", page, model.version or "x", sha[:12])
    if registration is not None:
        run_id += "-%s-%s-r%s" % (reg.get("project_id"), reg.get("material_id"), reg.get("registration_version"))
    units = (model.application or {}).get("units") or "mm"
    result = {
        "schema_version": SCHEMA_VERSION,
        "project_id": reg.get("project_id"),
        "extraction_run_id": run_id,
        "run": {"script": SCRIPT_NAME, "script_version": SCRIPT_VERSION, "rules_version": RULES_VERSION, "scope": "full",
                "settings": {"page_index": page},
                "dexpi": {"flavor": model.fmt, "version": model.version, "schema_version": model.schema_version,
                          "application": model.application, "diagram_count": model.diagram_count,
                          "process_objects_skipped": model.process_objects}},
        "source": {"material_id": reg.get("material_id"), "registration_version": reg.get("registration_version"),
                   "format": "dexpi", "dexpi_version": model.version, "dexpi_flavor": model.fmt, "file": source["file"],
                   "sha256": sha, "compressed": False,
                   "page_count": max(1, model.diagram_count)},
        "source_context": {"document_id": (reg.get("documents") or [{}])[0].get("document_id"),
                           "page_id": "page-1" if page == 0 else "page-%d" % (page + 1), "page_name": drawing_name},
        "review_status": "not_reviewed",
        "drawing": drawing,
        "coordinate_system": {"coordinate_space": COORDINATE_SPACE, "unit": units, "origin": "top_left",
                              "source_origin": "bottom_left" if model.fmt == dexpi_read.FMT_PROTEUS else "top_left",
                              "svg_alignment": None},
        "nodes": nodes,
        "relations": relations,
        "unresolved_connectors": unresolved,
        "texts": [],
        "unclassified": [],
        "source_locations": source_locations,
        "validation": {"status": "blocked" if blockers else "passed", "blockers": blockers, "unknowns": unknowns},
    }
    result["summary"] = summarize(result)
    return result


def summarize(result):
    counts = {}
    for item in result["validation"]["blockers"] + result["validation"]["unknowns"]:
        counts[item["check"]] = counts.get(item["check"], 0) + 1
    by_kind = {}
    for r in result["relations"]:
        by_kind[str(r["kind"])] = by_kind.get(str(r["kind"]), 0) + 1
    return {"nodes": len(result["nodes"]),
            "nodes_unclassified": sum(1 for n in result["nodes"] if n["classification"] == "unclassified"),
            "relations": len(result["relations"]), "relations_by_kind": by_kind,
            "unresolved_connectors": len(result["unresolved_connectors"]), "texts": 0, "unclassified_elements": 0,
            "edge_label_cells": 0, "ignored_objects": 0, "blockers": len(result["validation"]["blockers"]),
            "unknowns": len(result["validation"]["unknowns"]), "issue_counts": counts}


# ---------------------------------------------------------------- 흐름 방향
def _arrow_flows(model):
    """흐름 화살표 -> {연결 순번: 'forward'|'backward'}. 화살표는 같은 구간에서 가장 가까운 연결 하나에만 붙인다."""
    out = {}
    for arrow in model.arrows:
        best = None
        for idx, c in enumerate(model.connections):
            if c["segment"] != arrow["segment"]:
                continue
            a = dexpi_read._endpoint_position(model, c["source"], c["source_node"])
            b = dexpi_read._endpoint_position(model, c["target"], c["target_node"])
            if a is None or b is None or a == b:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            px, py = arrow["position"]
            t = min(1.0, max(0.0, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy)))
            d = math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))
            cos = (arrow["direction"][0] * dx + arrow["direction"][1] * dy) / math.hypot(dx, dy)
            if best is None or d < best[0]:
                best = (d, idx, cos)
        if best is not None and abs(best[2]) >= FLOW_COS:
            out[best[1]] = "forward" if best[2] > 0 else "backward"
    return out


def _flow_class(model, segment_id):
    """구간의 FlowDirection(한 방향·양방향 구분, §5.4) -> 'single' | 'dual' | None. 향하는 쪽은 정하지 않는다."""
    value = ((model.segments.get(segment_id) or {}).get("attrs") or {}).get("FlowDirection") or ""
    if value.endswith("DualFlowPipingNetworkSegment"):
        return "dual"
    if value.endswith("SingleFlowPipingNetworkSegment"):
        return "single"
    return None


def _flow_of(model, c, arrow_flow):
    """연결 하나의 흐름 -> ('forward'|'backward'|None, basis). 도면 연결 기호와 화살표가 어긋나면 None."""
    connector = None
    for end, other in (("source", "target"), ("target", "source")):
        item = model.items.get(c[end])
        if item is not None and item["group"] == "offpage":
            cls = item["cls"] or ""
            if "FlowIn" in cls:  # 기호에서 흘러 들어옴
                connector = "forward" if end == "source" else "backward"
            elif "FlowOut" in cls:  # 기호로 흘러 나감
                connector = "forward" if end == "target" else "backward"
    if connector and arrow_flow and connector != arrow_flow:
        return None, None
    if connector:
        return connector, "dexpi_off_page_connector"
    if arrow_flow:
        return arrow_flow, "dexpi_flow_arrow"
    return None, None


def extract_bytes(data, file_label, registration=None, page=0, repo_root=None, sidecar=None):
    """바이트 -> (추출 결과, Model). 읽을 수 없으면 dexpi_read.DexpiError. sidecar: 내보낼 때 함께 낸 곁 파일(dict)이면 되붙인다."""
    model = dexpi_read.read(data)
    sha = hashlib.sha256(data).hexdigest()
    result = build(model, {"file": file_label, "sha256": sha, "size_bytes": len(data)}, registration, page, repo_root)
    if sidecar is not None:
        apply_sidecar(result, sidecar, sha)
    return result, model


def apply_sidecar(extraction, sidecar, dexpi_sha256):
    """같은 앱이 내보낸 곁 파일(`<도면>.hazop.json`)로 DEXPI에 자리가 없던 정보를 되붙인다(§6.3·§7.3): 원래 kind(근사 대응),
    DEXPI에 없던 속성, 흐름 방향, 체크밸브 허용 방향, 원래 출처(entity_id·origin·수정 표시). 곁 파일이 이 DEXPI 파일의 것이 아니거나
    그 뒤 파일이 바뀌었으면(SHA-256이 다름) 아무것도 되붙이지 않고 미확인 dexpi_sidecar_stale을 남긴다. 반환: 되붙인 개수 dict."""
    unknowns = extraction["validation"]["unknowns"]
    out = {"restored_kinds": 0, "restored_attributes": 0, "restored_flows": 0, "restored_check_directions": 0}
    if sidecar.get("schema") != SIDECAR_SCHEMA or sidecar.get("dexpi_sha256") != dexpi_sha256:
        _issue(unknowns, "dexpi_sidecar_stale", "곁 파일이 이 DEXPI 파일의 것이 아님(내보낸 뒤 파일이 바뀌었거나 다른 파일): 되붙이지 않음")
        extraction["summary"] = summarize(extraction)
        return out
    node_by_id = {n["source_object_id"]: n for n in extraction["nodes"]}
    rel_by_id = {r["source_object_id"]: r for r in extraction["relations"]}
    local_of_entity, pipe_of_entity = {}, {}
    for ent in sidecar.get("entities", []):
        node = node_by_id.get(ent["dexpi_id"])
        if node is None:
            continue
        local_of_entity[ent["entity_id"]] = node["local_id"]
        kind = ent.get("kind")
        if kind and kind != node["kind"] and rules.KIND_CATEGORY.get(kind):
            node["kind"], node["category"], node["classification"] = kind, rules.KIND_CATEGORY[kind], "classified"
            node["attributes"]["kind"] = kind
            out["restored_kinds"] += 1
        restored = []
        if (ent.get("attributes") or {}).get("fail_position") == "FL" and node["attributes"].get("fail_position") == "FAI":
            node["attributes"]["fail_position"] = "FL"  # DEXPI에는 FL이 없어 FailRetainPosition(FAI)으로 나갔다
            restored.append("fail_position")
        for k, v in (ent.get("attributes") or {}).items():
            if not k.startswith("dexpi:") and k not in node["attributes"] and v not in (None, ""):
                node["attributes"][k] = v
                restored.append(k)
        out["restored_attributes"] += len(restored)
        node.setdefault("evidence", {})["hazop_sidecar"] = {"entity_id": ent["entity_id"], "graph_version": sidecar.get("graph_version"),
                                                           "origin": ent.get("origin"), "human_edit": ent.get("human_edit")}
        gone = set(restored)
        if kind and node["kind"] == kind:
            gone.add("kind")
        unknowns[:] = [u for u in unknowns if not (u.get("target") == node["local_id"] and u.get("field") in gone)]
    for pipe in sidecar.get("pipes", []):
        rel = rel_by_id.get(pipe["dexpi_id"])
        if rel is None:
            continue
        pipe_of_entity[pipe["entity_id"]] = rel["local_id"]
        fd = pipe.get("flow_direction")
        if fd and rel["flow_direction"] is None and fd.get("from") in local_of_entity and fd.get("to") in local_of_entity:
            a, b = local_of_entity[fd["from"]], local_of_entity[fd["to"]]
            ends = [e["node_local_id"] for e in rel["endpoints"]]
            if a in ends and b in ends and a != b:
                rel["flow_direction"] = {"from": a, "to": b, "from_end": "source" if ends[0] == a else "target",
                                         "to_end": "source" if ends[0] == b else "target", "basis": fd.get("basis")}
                unknowns[:] = [u for u in unknowns if not (u["check"] == "unknown_flow_direction" and u.get("target") == rel["local_id"])]
                out["restored_flows"] += 1
    for dexpi_id, cd in (sidecar.get("check_directions") or {}).items():
        node = node_by_id.get(dexpi_id)
        inlet, outlet = pipe_of_entity.get(cd.get("inlet")), pipe_of_entity.get(cd.get("outlet"))
        if node is not None and inlet and outlet:
            node["check_direction"] = {"inlet": inlet, "outlet": outlet, "basis": list(cd.get("basis") or []),
                                       "status": cd.get("status") or "declared"}
            unknowns[:] = [u for u in unknowns if not (u["check"] == "unknown_check_valve_direction" and u.get("target") == node["local_id"])]
            out["restored_check_directions"] += 1
    extraction["run"]["dexpi"]["sidecar"] = dict(out, graph_version=sidecar.get("graph_version"))
    extraction["summary"] = summarize(extraction)
    return out
