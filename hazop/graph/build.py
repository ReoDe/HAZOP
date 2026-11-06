"""단계 ③ 도면 1장의 추출 결과(extraction.json) -> 그래프(graph.json).

근거: 기획서/정보통합관리.md #node-unit(노드 단위), 독립 검증·통과 기준, 기획서/전체기획.md #data-contract(③ -> ④).
- 추출 노드 -> 노드 1개
- physical_connection 관계 1개 -> pipe_segment 노드 1개 + 양 끝 has_endpoint 엣지(end=source|target)
- signal_connection·measurement_connection -> 양 끝 노드를 잇는 엣지 1개
- unresolved_connectors·unknowns는 정상 연결로 넣지 않고 미확인 목록으로 전달
- 흐름 방향은 만들지 않는다. 추출에서 확인된 구간만 flow_direction을 가진다(직접 엣지도 같은 이름).
- 체크밸브 check_direction은 입구·출구 local_id를 구간 엔터티 ID로 바꿔 그대로 전달, 끝점 port는 has_endpoint·unresolved에 전달
  (기획서/정보추출.md #check-valve-direction, #port-rule)
- 관계 대상 제약·자기 루프 등 [가정] 기반 점검은 unknowns가 아니라 review_items로 분리한다.
같은 입력이면 같은 결과(ID·순서)가 나오도록 결정적으로 만든다.
"""

import hashlib
import json
import math

import networkx as nx

SCHEMA_VERSION = "0.1"
BUILDER = "hazop.graph.build"
BUILDER_VERSION = "0.3.0"

PHYSICAL = "physical_connection"
DIRECT_EDGE_KINDS = ("signal_connection", "measurement_connection")
# 관계 양 끝 대상 제약(검토 항목). 정보통합관리.md '관계 대상이 정의와 맞지 않음' 검사용 [가정]
# level: "검토"(확인 필요) / "참고"(오탐 가능성이 커 참고만. 예: 펌프 트립 신호는 펌프에 연결됨)
END_CATEGORY_RULES = {
    "measurement_connection": ("검토", "한쪽 끝은 계기여야 함", lambda cats: "instrument" in cats),
    "signal_connection": ("참고", "양 끝이 계기 또는 밸브가 아님", lambda cats: all(c in ("instrument", "valve") for c in cats)),
}


def _polyline_midpoint(points):
    """폴리라인 길이의 절반 지점."""
    if not points:
        return None
    if len(points) == 1:
        return list(points[0])
    lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    half = sum(lengths) / 2.0
    for i, seg in enumerate(lengths):
        if half <= seg or i == len(lengths) - 1:
            t = 0 if seg == 0 else min(half / seg, 1.0)
            (x0, y0), (x1, y1) = points[i], points[i + 1]
            return [round(x0 + (x1 - x0) * t, 3), round(y0 + (y1 - y0) * t, 3)]
        half -= seg
    return list(points[-1])


def _center(bbox):
    return [round(bbox[0] + bbox[2] / 2.0, 3), round(bbox[1] + bbox[3] / 2.0, 3)]


def _graph_version(extraction):
    """입력(추출 결과)과 변환기 버전이 같으면 같은 값, 하나라도 바뀌면 다른 값."""
    canon = json.dumps(extraction, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "v-" + hashlib.sha256((BUILDER_VERSION + "|" + canon).encode("utf-8")).hexdigest()[:12]


def build_graph(extraction, extraction_file=None):
    """extraction dict -> graph dict."""
    locs = {l["local_id"]: l for l in extraction["source_locations"]}
    dwg = extraction["drawing"].get("drawing_number")
    run_id = extraction["extraction_run_id"]
    blockers, unknowns = [], []
    if extraction["validation"]["status"] != "passed":
        blockers.append({"check": "input_blocked", "target": None,
                         "reason": "추출 결과가 구조 검증을 통과하지 못함(차단 오류 %d건)"
                         % len(extraction["validation"]["blockers"])})

    nodes, edges, mapping = [], [], []
    entity_of = {}  # extraction local_id -> entity_id

    for i, n in enumerate(extraction["nodes"], 1):
        eid = "entity-node-%03d" % i
        entity_of[n["local_id"]] = eid
        loc = locs.get(n["local_id"])
        nodes.append({
            "entity_id": eid, "node_type": "drawing_object", "kind": n["kind"], "category": n["category"],
            "classification": n["classification"], "tag": n["tag"], "label_text": n["label_text"],
            "attributes": dict(n["attributes"]), "local_id": n["local_id"],
            "source_object_id": n["source_object_id"],
            "bbox": loc["bbox"] if loc else None,
            "position": _center(loc["bbox"]) if loc else None,
        })
        mapping.append({"extraction_run_id": run_id, "local_id": n["local_id"], "entity_id": eid})

    seg_no = rel_no = 0
    for r in extraction["relations"]:
        ends = r["endpoints"]
        end_entities = [entity_of.get(ep["node_local_id"]) for ep in ends]
        if None in end_entities:
            # 추출이 정상 관계로 넘겼으나 끝 노드를 찾을 수 없으면 정상 연결로 넣지 않는다.
            blockers.append({"check": "missing_reference", "target": r["local_id"],
                             "reason": "관계 끝 노드가 추출 노드에 없음"})
            continue
        flow = None
        if r.get("flow_direction"):
            fd = r["flow_direction"]
            flow = {"from": entity_of.get(fd["from"]), "to": entity_of.get(fd["to"]),
                    "from_end": fd["from_end"], "to_end": fd["to_end"], "basis": fd["basis"]}
        if r["kind"] == PHYSICAL:
            seg_no += 1
            sid = "entity-seg-%03d" % seg_no
            entity_of[r["local_id"]] = sid
            pts = [ep["point"] for ep in ends[:1] if ep["point"]] + r["waypoints"] + \
                  [ep["point"] for ep in ends[1:] if ep["point"]]
            loc = locs.get(r["local_id"])
            nodes.append({
                "entity_id": sid, "node_type": "pipe_segment", "kind": "pipe_segment",
                "category": "pipe_segment", "classification": "classified", "tag": r["line_no"],
                "label_text": r["label_text"], "line_no": r["line_no"], "line_type": r["line_type"],
                "flow_direction": flow, "attributes": dict(r["attributes"]), "local_id": r["local_id"],
                "source_object_id": r["source_object_id"],
                "bbox": loc["bbox"] if loc else None,
                "position": _polyline_midpoint(pts),
            })
            mapping.append({"extraction_run_id": run_id, "local_id": r["local_id"], "entity_id": sid})
            for ep, ne in zip(ends, end_entities):
                rel_no += 1
                edges.append({"entity_id": "relation-%03d" % rel_no, "kind": "has_endpoint",
                              "nodes": [sid, ne], "segment": sid, "node": ne, "end": ep["end"],
                              "constraint": ep["constraint"], "port": ep.get("port"), "local_id": r["local_id"],
                              "source_object_id": r["source_object_id"]})
            if flow is None:
                unknowns.append({"check": "unknown_flow_direction", "target": sid, "field": "flow_direction",
                                 "reason": "흐름 방향 미확인(원본에 지정 없음)"})
        elif r["kind"] in DIRECT_EDGE_KINDS:
            rel_no += 1
            rid = "relation-%03d" % rel_no
            entity_of[r["local_id"]] = rid
            edges.append({"entity_id": rid, "kind": r["kind"], "nodes": end_entities,
                          "ends": [ep["end"] for ep in ends], "line_type": r["line_type"],
                          "line_no": r["line_no"], "flow_direction": flow, "local_id": r["local_id"],
                          "source_object_id": r["source_object_id"]})
            mapping.append({"extraction_run_id": run_id, "local_id": r["local_id"], "entity_id": rid})
        else:
            unknowns.append({"check": "unknown_relation_kind", "target": r["local_id"], "field": "kind",
                             "reason": "관계 종류 미확인(%r) - 그래프 정상 연결에서 제외" % r["kind"]})

    # 체크밸브 허용 방향: 입구·출구 커넥터 local_id -> 엔터티 ID (basis·status는 그대로)
    for n, src in zip(nodes, extraction["nodes"]):
        if "check_direction" in src:
            cd = src["check_direction"]
            n["check_direction"] = None if cd is None else dict(
                cd, inlet=entity_of.get(cd["inlet"]), outlet=entity_of.get(cd["outlet"]), basis=list(cd["basis"]))

    # 관계 양 끝 대상 제약 (검토 항목)
    review_items = []
    cat_of = {n["entity_id"]: n["category"] for n in nodes}
    for e in edges:
        rule = END_CATEGORY_RULES.get(e["kind"])
        cats = [cat_of.get(x) for x in e["nodes"]]
        if rule and not rule[2](cats):
            review_items.append({"check": "relation_target_unexpected", "level": rule[0], "target": e["entity_id"],
                                 "local_id": e["local_id"], "reason": "%s: %s [가정 규칙]" % (rule[1], cats)})
    # 자기 루프: 커넥터 source와 target이 같은 대상
    seg_nodes = {}
    for e in edges:
        if e["kind"] == "has_endpoint":
            seg_nodes.setdefault(e["segment"], []).append(e["node"])
    for sid, ns in sorted(seg_nodes.items()):
        if len(ns) == 2 and ns[0] == ns[1]:
            review_items.append({"check": "self_loop_segment", "level": "검토", "target": sid,
                                 "local_id": next(n["local_id"] for n in nodes if n["entity_id"] == sid),
                                 "reason": "배관 양 끝이 같은 대상(%s)" % ns[0]})

    # 추출 단계의 미확인 항목을 대상 ID를 바꿔 전달 (원래 local_id 유지)
    for u in extraction["validation"]["unknowns"]:
        if u["check"] == "unknown_flow_direction":
            continue  # 위에서 구간 노드 기준으로 다시 기록함
        item = dict(u)
        item["local_id"] = u.get("target")
        item["target"] = entity_of.get(u.get("target"))
        item["origin"] = "extraction"
        unknowns.append(item)

    unresolved = [{"local_id": r["local_id"], "source_object_id": r["source_object_id"], "kind": r["kind"],
                   "line_type": r["line_type"], "line_no": r["line_no"],
                   "endpoints": [{"end": ep["end"], "status": ep["status"],
                                  "node_entity_id": entity_of.get(ep["node_local_id"]),
                                  "source_object_id": ep["source_object_id"], "port": ep.get("port")}
                                 for ep in r["endpoints"]],
                   "reason": "양 끝이 확정되지 않아 정상 연결로 넣지 않음"}
                  for r in extraction["unresolved_connectors"]]

    graph = {
        "schema_version": SCHEMA_VERSION,
        "project_id": extraction.get("project_id"),
        "graph_id": "graph-%s" % (dwg or extraction["source_context"].get("page_name") or "drawing"),
        "graph_version": _graph_version(extraction),
        "input_runs": [run_id],
        "builder": {"name": BUILDER, "version": BUILDER_VERSION, "networkx": nx.__version__},
        "source": {"extraction_file": extraction_file, "drawing_number": dwg,
                   "extraction_run_id": run_id},
        "coordinate_system": {"coordinate_space": extraction["coordinate_system"]["coordinate_space"],
                              "unit": extraction["coordinate_system"]["unit"],
                              "note": "position·bbox는 drawio 도면 좌표. 구간 노드 position은 커넥터 경로 길이의 중점"},
        "entity_mapping": mapping,
        "nodes": nodes,
        "edges": edges,
        "unresolved": unresolved,
        "validation": {"status": "blocked" if blockers else "passed", "blockers": blockers,
                       "unknowns": unknowns},
        "review_items": review_items,
    }
    graph["structure"] = structure_report(graph)
    return graph


def entity_mapping_document(graph, extraction):
    """그래프 버전의 대상 매핑: entity_id <-> (추출 실행, local_id, 원본 객체 ID, 자료 ID, 등록 버전).
    ③ -> ④ 규격의 entity_mapping 항목(extraction_run_id·local_id·entity_id)에 원본 근거를 더한다."""
    src = extraction["source"]
    obj_of = {x["local_id"]: x["source_object_id"] for x in extraction["nodes"] + extraction["relations"]}
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": graph["project_id"],
        "graph_id": graph["graph_id"],
        "graph_version": graph["graph_version"],
        "input_runs": list(graph["input_runs"]),
        "entity_mapping": [dict(m, source_object_id=obj_of.get(m["local_id"]), material_id=src["material_id"],
                                registration_version=src["registration_version"])
                           for m in graph["entity_mapping"]],
    }


def to_networkx(graph, kinds=None):
    """graph dict -> nx.MultiGraph (무방향, 엣지 순서는 방향 아님). kinds로 엣지 종류를 제한."""
    g = nx.MultiGraph()
    for n in graph["nodes"]:
        g.add_node(n["entity_id"], **{k: v for k, v in n.items() if k != "entity_id"})
    for e in graph["edges"]:
        if kinds is None or e["kind"] in kinds:
            g.add_edge(e["nodes"][0], e["nodes"][1], key=e["entity_id"], **e)
    return g


def structure_report(graph):
    g_all = to_networkx(graph)
    g_phys = to_networkx(graph, kinds={"has_endpoint"})
    node_kinds, edge_kinds = {}, {}
    for n in graph["nodes"]:
        node_kinds[n["kind"] or "unclassified"] = node_kinds.get(n["kind"] or "unclassified", 0) + 1
    for e in graph["edges"]:
        edge_kinds[e["kind"]] = edge_kinds.get(e["kind"], 0) + 1
    seg_ends = {}
    for e in graph["edges"]:
        if e["kind"] == "has_endpoint":
            seg_ends[e["segment"]] = seg_ends.get(e["segment"], 0) + 1
    bad_segments = sorted(n["entity_id"] for n in graph["nodes"]
                          if n["node_type"] == "pipe_segment" and seg_ends.get(n["entity_id"], 0) != 2)
    phys_members = [c for c in nx.connected_components(g_phys) if len(c) > 1]
    return {
        "node_count": g_all.number_of_nodes(),
        "edge_count": g_all.number_of_edges(),
        "node_kinds": dict(sorted(node_kinds.items())),
        "edge_kinds": dict(sorted(edge_kinds.items())),
        "components_all": nx.number_connected_components(g_all) if g_all.number_of_nodes() else 0,
        "components_physical": len(phys_members),
        "isolated_nodes": sorted(n for n in g_all.nodes if g_all.degree(n) == 0),
        "nodes_without_physical_connection": sorted(n for n in g_phys.nodes
                                                    if g_phys.degree(n) == 0
                                                    and g_phys.nodes[n]["node_type"] != "pipe_segment"),
        "segments_with_endpoint_count_not_2": bad_segments,
        "segments_without_flow": sorted(n["entity_id"] for n in graph["nodes"]
                                        if n["node_type"] == "pipe_segment" and not n.get("flow_direction")),
    }


def render_report(graph):
    s = graph["structure"]
    v = graph["validation"]
    tag = {n["entity_id"]: (n.get("tag") or n["kind"] or n["entity_id"]) for n in graph["nodes"]}

    def names(ids):
        return ", ".join("%s(%s)" % (tag.get(i, i), i) for i in ids) or "없음"

    lines = [
        "# 그래프 구조 검증 보고서: %s" % (graph["source"]["drawing_number"] or graph["graph_id"]),
        "",
        "| 항목 | 값 |", "| --- | --- |",
        "| graph_id / version | `%s` / `%s` |" % (graph["graph_id"], graph["graph_version"]),
        "| 입력 추출 실행 | `%s` |" % ", ".join(graph["input_runs"]),
        "| 구조 검증 | **%s** |" % v["status"],
        "| 노드 / 엣지 | %d / %d |" % (s["node_count"], s["edge_count"]),
        "| 연결 성분(전체 엣지) | %d |" % s["components_all"],
        "| 물리 연결 성분(has_endpoint, 2개 이상 노드) | %d |" % s["components_physical"],
        "",
        "## 종류별 개수", "",
        "| 노드 종류 | 개수 |", "| --- | --- |",
    ]
    lines += ["| %s | %d |" % kv for kv in s["node_kinds"].items()]
    lines += ["", "| 엣지 종류 | 개수 |", "| --- | --- |"]
    lines += ["| %s | %d |" % kv for kv in s["edge_kinds"].items()]
    lines += [
        "", "## 구조 점검", "",
        "- 고립 노드(엣지 없음): %s" % names(s["isolated_nodes"]),
        "- 물리 연결 없는 노드(계측·신호로만 연결 등): %s" % names(s["nodes_without_physical_connection"]),
        "- 끝점 수가 2가 아닌 구간: %s" % names(s["segments_with_endpoint_count_not_2"]),
        "- 흐름 방향 미확인 구간: %s" % names(s["segments_without_flow"]),
        "- 미해결 커넥터(정상 연결 제외): %d건" % len(graph["unresolved"]),
        "", "## 차단 오류 (%d)" % len(v["blockers"]), "",
    ]
    lines += ["- %s %s: %s" % (b["check"], b.get("target") or "", b["reason"]) for b in v["blockers"]] or ["없음"]
    lines += ["", "## 미확인 항목 (%d)" % len(v["unknowns"]), "",
              "| 검사 | 대상 entity_id | 추출 local_id | 사유 |", "| --- | --- | --- | --- |"]
    lines += ["| %s | %s | %s | %s |" % (u["check"], u.get("target") or "-", u.get("local_id") or "-",
                                       str(u["reason"]).replace("|", "\\|")) for u in v["unknowns"]]
    items = graph.get("review_items", [])
    lines += ["", "## 검토·참고 항목 (%d) — [가정] 규칙 기반, 차단하지 않음" % len(items), ""]
    lines += ["- [%s] %s %s: %s" % (r["level"], r["check"], r["target"], r["reason"]) for r in items] or ["없음"]
    lines.append("")
    return "\n".join(lines)
