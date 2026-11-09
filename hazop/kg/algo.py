"""지식그래프 알고리즘 MVP A1~A5 (기획서/그래프활용.md §4).

- 계산용 뷰(§4.1): V1 물리 무방향(has_endpoint), V3 계장(signal·measurement), V4 지식(compute_view.v4가 true인
  지식 노드·관계만), V5 통합 무방향(V1 + V3 + V4). V2(흐름 방향)와 A6~A11은 후속이라 만들지 않는다.
- A1 상·하류 전파: ④ hazop.analysis.explore.explore()를 그대로 호출한다. 인자는 선택 노드가 속한 검토 구간 JSON의
  멤버로 만든 region_members와 그 구간의 exploration 값(④ run.prepare_doc과 같은 방식). 구간 밖이면 비활성.
- A2 고아·근거 공백: V4만 쓴다. 설비 적용 관계(레지스트리 a2_role apply, 지금 governed_by·has_setpoint·has_condition·
  analyzed_in)만 센다. 기대 층(잠재 후보)은 레지스트리 v4=false라 어느 뷰에도 들어가지 않는다.
- A3 차수(V5, 배관 구간 접기 결과 함께), A4 ego_graph(V5, undirected=True), A5 connected_components(V1·V5).
- 결과는 결정적이다(정렬, 무작위 없음, 시각 기록 없음). 원본 레이어 파일은 읽기만 한다.
- 연결·도달·차수는 계산 참고 자료이며 인과관계나 HAZOP 근거를 확정하지 않는다(§6).
"""

import hashlib
import os
import shutil

from hazop import paths
from hazop.analysis import explore as ex_mod
from hazop.graph.build import to_networkx
from hazop.graph.query import GraphQuery
from hazop.kg import build as kg_build
from hazop.kg.schema import REGISTRY

GENERATOR = "hazop.kg.algo"
GENERATOR_VERSION = "0.1.0"
SCHEMA_VERSION = "0.1"
PHYSICAL_KINDS = REGISTRY.pid_view_kinds("V1")
INSTRUMENT_KINDS = REGISTRY.pid_view_kinds("V3")
# 지식 노드 종류 -> 그 노드를 설비에 적용하는 관계(§2.3 설비 적용 관계, §4.2 A2 판정 규칙). analyzed_in 포함 4종
APPLY_KIND_OF = REGISTRY.apply_kind_of()
APPLY_KINDS = tuple(sorted(APPLY_KIND_OF.values()))
GAP_KINDS = tuple(sorted(REGISTRY.apply_kind_of(evidence_gap=True).values()))  # 근거 공백(b) 판정에 세는 관계(§4.2)
FOLD_LIMIT = ("구간 접기는 구간 노드를 목록에서 빼고 중심성 분모만 바꾼다. 구간 1개가 엣지 1개로 바뀌므로 "
              "설비의 차수 값은 접어도 같다")
RESULT_FILE = "algo_result.json"
REPORT_FILE = "algo_report.md"
NOTE = "계산 참고 자료. 연결·도달은 인과관계를 입증하지 않으며 HAZOP 근거로 쓰려면 사람 확인을 거친다(그래프활용 §6)"


class AlgoError(ValueError):
    pass


# ---------------------------------------------------------------- 입력 확인
def check_inputs(kg, graph):
    """blocked 지식그래프, 지식그래프가 참조하지 않은 도면, 버전이 다른 도면으로는 계산하지 않는다(§7.1, §2.5)."""
    if kg["validation"]["status"] != "passed":
        raise AlgoError("지식그래프가 passed가 아님(%s) - 알고리즘을 실행하지 않음" % kg["validation"]["status"])
    if graph["validation"]["status"] != "passed":
        raise AlgoError("P&ID 그래프 구조 검증이 passed가 아님(%s)" % graph["validation"]["status"])
    ref = {r["graph_id"]: r["graph_version"] for r in kg["graph_refs"]}
    if graph["graph_id"] not in ref:
        raise AlgoError("지식그래프가 참조하지 않은 도면: %s (graph_refs: %s)" % (graph["graph_id"], sorted(ref)))
    if ref[graph["graph_id"]] != graph["graph_version"]:
        raise AlgoError("graph_version 불일치: 지식그래프는 %s/%s, 입력 그래프는 %s - 지식그래프를 다시 빌드해야 함"
                        % (graph["graph_id"], ref[graph["graph_id"]], graph["graph_version"]))


# ---------------------------------------------------------------- 뷰
def _v4_links(kg):
    """V4 관계 [(관계, from 키, to 키)]. 지식 끝 = 지식 ID, P&ID 끝 = (graph_id, entity_id).
    두 끝이 모두 포함될 때만 넣는다(지식 끝은 V4 노드, P&ID 끝은 entity_id로 풀린 것)."""
    v4_ids = {n["id"] for n in kg["nodes"] if n["compute_view"]["v4"]}
    out = []
    for l in kg["links"]:
        if not l["compute_view"]["v4"]:
            continue
        ends = []
        for s in ("from", "to"):
            e = l["ends"][s]
            if e["layer"] == "knowledge":
                ends.append(e["ref"] if e["ref"] in v4_ids else None)
            else:
                ends.append((e.get("graph_id"), e["entity_id"]) if e.get("entity_id") is not None else None)
        if None not in ends:
            out.append((l, ends[0], ends[1]))
    return out


def v4_items(kg, graph):
    """선택 도면 기준 V4: (지식 노드 목록, [(관계, from 노드 ID, to 노드 ID)], 제외 집계).
    P&ID 끝은 선택 도면의 entity_id로 바꾼다. 다른 도면을 가리키는 관계는 이 도면 계산에서 뺀다(집계에 남김)."""
    nodes = [n for n in kg["nodes"] if n["compute_view"]["v4"]]
    links, other_graph = [], 0
    for l, a, b in _v4_links(kg):
        ends = []
        for x in (a, b):
            if isinstance(x, tuple):
                ends.append(x[1] if x[0] == graph["graph_id"] else None)
            else:
                ends.append(x)
        if None in ends:
            other_graph += 1
            continue
        links.append((l, ends[0], ends[1]))

    def by_reason(items):
        out = {}
        for it in items:
            for r in it["compute_view"]["excluded_reasons"]:
                out[r] = out.get(r, 0) + 1
        return dict(sorted(out.items()))
    excl_nodes = [n for n in kg["nodes"] if not n["compute_view"]["v4"]]
    excl_links = [l for l in kg["links"] if not l["compute_view"]["v4"]]
    excluded = {"knowledge_nodes": len(excl_nodes), "knowledge_nodes_by_reason": by_reason(excl_nodes),
                "knowledge_links": len(excl_links), "knowledge_links_by_reason": by_reason(excl_links),
                "kg_candidate_links": sum(1 for l in kg["links"] if l.get("link_status") == "candidate"),
                "links_to_other_graphs": other_graph}
    return nodes, links, excluded


def view_v1(graph):
    return to_networkx(graph, kinds=set(PHYSICAL_KINDS))


def view_v3(graph):
    return to_networkx(graph, kinds=set(INSTRUMENT_KINDS))


def view_v4(kg, graph):
    """지식 노드(V4) + V4 관계가 닿는 P&ID 노드. MultiGraph, 엣지 키 = 관계 ID."""
    import networkx as nx
    nodes, links, _ = v4_items(kg, graph)
    pid = {n["entity_id"]: n for n in graph["nodes"]}
    g = nx.MultiGraph()
    for n in nodes:
        g.add_node(n["id"], layer="knowledge", node_type=n["node_type"])
    for l, a, b in links:  # 두 끝이 모두 포함된 관계만(v4_items). 빠진 노드가 엣지로 다시 들어오지 않음
        for x in (a, b):
            if x in pid and x not in g:
                g.add_node(x, layer="pid", node_type=pid[x]["node_type"])
        if a in g and b in g:
            g.add_edge(a, b, key=l["id"], kind=l["kind"], layer="knowledge")
    return g


def view_v5(kg, graph):
    """V1 + V3 + V4 통합 무방향 MultiGraph. P&ID 노드는 entity_id, 지식 노드는 지식 ID(접두어가 겹치지 않음, K3)."""
    import networkx as nx
    g = nx.MultiGraph()
    for n in graph["nodes"]:
        g.add_node(n["entity_id"], layer="pid", node_type=n["node_type"])
    for e in graph["edges"]:
        if e["kind"] in PHYSICAL_KINDS or e["kind"] in INSTRUMENT_KINDS:
            g.add_edge(e["nodes"][0], e["nodes"][1], key=e["entity_id"], kind=e["kind"], layer="pid")
    v4 = view_v4(kg, graph)
    for n, d in v4.nodes(data=True):
        if n not in g:
            g.add_node(n, **d)
    for a, b, k, d in v4.edges(keys=True, data=True):
        g.add_edge(a, b, key=k, **d)
    return g


def _view_stats(g):
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges()}


# ---------------------------------------------------------------- A1
def regions_containing(graph, regions, start):
    """regions: [(라벨, 구간 dict, 구간 파일 sha256)]. start가 멤버(배관 구간 자동 포함)인 구간
    [(라벨, 구간, sha256, region_members)]. graph_id가 같은 구간만."""
    out = []
    for label, region, sha in regions:
        if (region.get("graph_ref") or {}).get("graph_id") != graph["graph_id"]:
            continue
        members = ex_mod.region_members(graph, [m["entity_id"] for m in region.get("members") or []])
        if start in members:
            out.append((label, region, sha, members))
    return sorted(out, key=lambda x: x[0])


def _region_problems(region, graph):
    """④ run.prepare가 차단하는 항목 중 탐색 인자에 직결되는 것: 그래프 버전, 멤버 존재·태그."""
    probs = []
    ref = region["graph_ref"]
    if ref.get("graph_version") != graph["graph_version"]:
        probs.append("구간 그래프 버전 불일치: 구간 %s, 그래프 %s" % (ref.get("graph_version"), graph["graph_version"]))
    nodes = {n["entity_id"]: n for n in graph["nodes"]}
    for m in region.get("members") or []:
        n = nodes.get(m["entity_id"])
        if n is None:
            probs.append("구간 포함 대상이 그래프에 없음: %s" % m["entity_id"])
        elif n.get("tag") != m.get("tag"):
            probs.append("구간 포함 대상 태그 불일치: %s" % m["entity_id"])
    return probs


def _inactive(reason, **kw):
    out = {"active": False, "reason": reason}
    out.update(kw)
    return out


def a1_propagation(graph, regions, start):
    """A1. regions: [(라벨, 구간 dict, 구간 파일 sha256)]. 구간을 하나로 정할 수 없으면 비활성(임의 기본값으로 탐색하지 않음)."""
    q = GraphQuery(graph)
    if start not in q.nodes:
        return _inactive("P&ID 노드가 아님(A1은 P&ID 레이어만 탐색)")
    hits = regions_containing(graph, regions, start)
    if not hits:
        return _inactive("검토 구간 미지정")
    if len(hits) > 1:
        return _inactive("여러 검토 구간에 속함 - 구간을 골라야 함",
                         regions=[{"file": h[0], "region_id": h[1].get("region_id"), "sha256": h[2]} for h in hits])
    label, region, sha, members = hits[0]
    region_ref = {"region_id": region.get("region_id"), "region_version": region.get("region_version"),
                  "file": label, "sha256": sha}
    probs = _region_problems(region, graph)
    if probs:
        return _inactive("검토 구간 입력 오류", region_ref=region_ref, problems=probs)
    xs = region["exploration"]
    # ④ run.prepare_doc과 같은 인자(boundary_extension_depth 없음 = 0도 ④와 같게 처리)
    exploration = ex_mod.explore(q, start, members, xs["relation_kinds"], xs["max_depth"], xs["max_reached"],
                                 xs.get("boundary_extension_depth", 0))
    groups = {}
    for r in exploration["reached"]:
        groups.setdefault(r["direction_from_start"], []).append(r["entity_id"])
    return {
        "active": True,
        "region_ref": region_ref,
        "region_members": sorted(members),
        "summary": {
            "reached": len(exploration["reached"]),
            "by_direction": {k: sorted(v) for k, v in sorted(groups.items())},
            "not_normal_flow_path": sorted(r["entity_id"] for r in exploration["reached"]
                                           if r["normal_operation_flow"] is False),
            "valve_position_unknown_path": sorted(r["entity_id"] for r in exploration["reached"]
                                                  if r["valve_state"] == "position_unknown_on_path"),
            "limits_hit": exploration["limits_hit"],
            "unreached_region_members": exploration["unreached_region_members"],
        },
        "exploration": exploration,
    }


# ---------------------------------------------------------------- A2
def a2_orphans_gaps(kg, graph):
    """A2 (§4.2 판정 규칙, V4만). 설비 적용 관계가 없는 종류(문서 등)는 판정하지 않는다.
    - 고아: 지식그래프 전체 V4로 판정(다른 도면 P&ID 노드에 적용·언급된 것도 고아가 아님).
    - 근거 공백·지식 입력 없음: 선택 도면의 도면 객체 기준. 도면 연결점(continuation)은 따로 센다."""
    nodes = [n for n in kg["nodes"] if n["compute_view"]["v4"]]
    gid = graph["graph_id"]
    pid = {n["entity_id"]: n for n in graph["nodes"]}
    applied_to = {}      # 지식 노드 -> 적용된 P&ID 노드 키 (해당 종류의 적용 관계만)
    mentions_of = {}     # 조각 -> 언급한 P&ID 노드 키
    mentioned = {}       # 선택 도면 P&ID 노드 -> 언급한 조각
    apply_kinds_of = {}  # 선택 도면 P&ID 노드 -> 적용 관계 종류
    chunks_of = {}       # 요건·설정치·운전조건 -> specified_in 조각
    kind_of = {n["id"]: n["node_type"] for n in nodes}
    for l, a, b in _v4_links(kg):  # P&ID 끝 = (graph_id, entity_id)
        k = l["kind"]
        if k == "mentions":
            mentions_of.setdefault(a, set()).add(b)
            if b[0] == gid:
                mentioned.setdefault(b[1], set()).add(a)
        elif k in APPLY_KINDS:
            if APPLY_KIND_OF.get(kind_of.get(b)) == k:
                applied_to.setdefault(b, set()).add(a)
            if a[0] == gid:
                apply_kinds_of.setdefault(a[1], set()).add(k)
        elif k == "specified_in":
            chunks_of.setdefault(a, set()).add(b)

    def tag(key):
        return pid[key[1]].get("tag") if key[0] == gid and key[1] in pid else None
    orphans, judged = [], 0
    for n in sorted(nodes, key=lambda x: x["id"]):
        t = n["node_type"]
        rel = APPLY_KIND_OF.get(t)
        # 설비 적용 관계가 없는 종류(문서, 앞으로 더할 클래스)는 고아 판정 대상이 아니다
        if t != "doc_chunk" and rel is None:
            continue
        judged += 1
        if t == "doc_chunk":
            if not mentions_of.get(n["id"]):
                orphans.append({"id": n["id"], "node_type": t, "reason": "확인된 mentions 없음"})
            continue
        if applied_to.get(n["id"]):
            continue
        hints = [{"chunk": c, "graph_id": e[0], "entity_id": e[1], "tag": tag(e)}
                 for c in sorted(chunks_of.get(n["id"], ())) for e in sorted(mentions_of.get(c, ()))]
        orphans.append({"id": n["id"], "node_type": t, "reason": "%s 없음" % rel, "link_hints": hints})
    gaps, no_input, no_input_cont = [], [], []
    objects = sorted(e for e, n in pid.items() if n["node_type"] == "drawing_object")
    for e in objects:
        kinds = apply_kinds_of.get(e, set())
        if mentioned.get(e) and not kinds & set(GAP_KINDS):
            gaps.append({"entity_id": e, "tag": pid[e].get("tag"), "mentioned_by": sorted(mentioned[e])})
        elif not mentioned.get(e) and not kinds:
            item = {"entity_id": e, "tag": pid[e].get("tag")}
            (no_input_cont if pid[e]["kind"] == "continuation" else no_input).append(item)
    return {
        "orphans": orphans,
        "orphan_count": len(orphans),
        "orphan_scope": "지식그래프 전체 V4(모든 참조 도면)",
        "knowledge_nodes_judged": judged,
        "evidence_gaps": gaps,
        "evidence_gap_note": "자료 요청 메모 후보일 뿐. 메모 생성은 사람이 함(그래프활용 §6.2)",
        "no_knowledge_input": no_input,
        "no_knowledge_input_continuations": no_input_cont,
        "no_knowledge_input_note": "연결 없음은 '해당 없음'이 아니라 '지식 입력 미확인'. 도면 연결점(continuation)은 "
                                   "설비가 아니므로 따로 표시",
        "drawing_objects_judged": len(objects),
        "gap_scope": "선택 도면 %s" % gid,
    }


# ---------------------------------------------------------------- A3
def fold_segments(v5, graph):
    """배관 구간 접기: V5에서 has_endpoint 외 연결이 없고 끝점이 정확히 2개인 배관 구간 노드를 지우고 양 끝 노드를
    엣지 하나(키 = 구간 ID)로 잇는다. 지식·계장 연결이 있거나 끝점이 2개가 아닌 구간은 정보를 잃지 않도록 접지 않는다.
    (접은 그래프, [{segment, reason}] 접지 않은 구간)"""
    ends = {}
    for e in graph["edges"]:
        if e["kind"] in PHYSICAL_KINDS and e.get("segment"):
            ends.setdefault(e["segment"], []).append(e["node"])
    g = v5.copy()
    kept = []
    for n in sorted(v5.nodes):
        if v5.nodes[n].get("node_type") != "pipe_segment":
            continue
        if any(d.get("kind") not in PHYSICAL_KINDS for _, _, d in v5.edges(n, data=True)):
            kept.append({"segment": n, "reason": "지식·계장 연결 있음"})
            continue
        ns = ends.get(n, [])
        if len(ns) != 2:
            kept.append({"segment": n, "reason": "끝점 %d개(2개 아님)" % len(ns)})
            continue
        g.remove_node(n)
        g.add_edge(ns[0], ns[1], key=n, kind="folded_segment", layer="pid")
    return g, kept


def _degrees(g):
    import networkx as nx
    cent = nx.degree_centrality(g) if g.number_of_nodes() > 1 else {n: 0.0 for n in g}
    return {n: {"degree": g.degree(n), "centrality": round(cent[n], 6)} for n in sorted(g.nodes)}


def a3_degree(v5, graph):
    folded, kept = fold_segments(v5, graph)
    return {"degree": _degrees(v5), "degree_segments_folded": _degrees(folded), "segments_not_folded": kept,
            "fold_rule": "has_endpoint만 있고 끝점이 2개인 배관 구간 노드를 양 끝 노드 사이 엣지 하나로 접음(크기 산정용). "
                         "지식·계장 연결이 있거나 끝점이 2개가 아닌 구간은 접지 않음",
            "fold_limit": FOLD_LIMIT}


# ---------------------------------------------------------------- A4
def a4_ego(v5, start, radius):
    import networkx as nx
    if start not in v5:
        return {"active": False, "reason": "V5에 없음(계산 제외 노드이거나 없는 ID)"}
    ego = nx.ego_graph(v5, start, radius=radius, undirected=True)
    hops = nx.single_source_shortest_path_length(v5, start, cutoff=radius)
    return {"active": True, "center": start, "radius": radius,
            "nodes": sorted(ego.nodes), "edges": sorted(k for _, _, k in ego.edges(keys=True)),
            "hops": {n: hops[n] for n in sorted(hops)},
            "pipe_segments_in_result": sum(1 for n in ego if v5.nodes[n].get("node_type") == "pipe_segment"),
            "hop_note": "radius·hops는 실제 홉 수(배관 구간 노드 포함). 설비 간 거리는 구간 노드 때문에 2배로 셈"}


# ---------------------------------------------------------------- A5
def _components(g):
    import networkx as nx
    comps = sorted((sorted(c) for c in nx.connected_components(g)), key=lambda c: (-len(c), c[0]))
    return {"count": len(comps), "singletons": sum(1 for c in comps if len(c) == 1),
            "sizes": [len(c) for c in comps], "components": comps}


def a5_components(v1, v5):
    return {"V1": _components(v1), "V5": _components(v5),
            "note": "도면 1장 단위에서는 도면 연결점 너머가 끊긴 것으로 보임"}


# ---------------------------------------------------------------- 전체 실행
def _region_key(a1):
    """출력 경로의 구간 식별자. 구간 파일 내용(sha256)이 다르면 경로도 다르다."""
    if a1.get("region_ref"):
        ref = a1["region_ref"]
        return "%s-%s" % (ref["region_id"], (ref["sha256"] or "nosha")[:12])
    if a1.get("regions"):
        joined = "|".join(sorted(r["sha256"] or "" for r in a1["regions"]))
        return "ambiguous-" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    return "no-region"


def analyze(kg, graph, regions, start, radius=2, candidate_file=None):
    """A1~A5를 한 번에 계산해 결과 문서(dict)를 돌려준다. 같은 입력이면 같은 결과.
    regions: [(라벨, 구간 dict, 구간 파일 sha256)]. candidate_file: 후보 CSV 집계
    {"file", "sha256", "unconfirmed_candidates"} 또는 None(파일 없음)."""
    import networkx as nx
    check_inputs(kg, graph)
    if not isinstance(radius, int) or radius < 0:
        raise AlgoError("radius는 0 이상 정수: %r" % radius)
    v1, v3, v5 = view_v1(graph), view_v3(graph), view_v5(kg, graph)
    v4 = view_v4(kg, graph)
    _, _, excluded = v4_items(kg, graph)
    excluded["candidate_csv"] = candidate_file
    a1 = a1_propagation(graph, regions, start)
    a3 = a3_degree(v5, graph)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": GENERATOR, "version": GENERATOR_VERSION, "networkx": nx.__version__},
        "inputs": {"kg_id": kg["kg_id"], "kg_version": kg["kg_version"],
                   "graph_refs": [{"graph_id": graph["graph_id"], "graph_version": graph["graph_version"]}],
                   "region_ref": a1.get("region_ref"), "region_key": _region_key(a1),
                   "start": start, "radius": radius},
        "views": {"V1": dict(_view_stats(v1), kinds=list(PHYSICAL_KINDS)),
                  "V3": dict(_view_stats(v3), kinds=list(INSTRUMENT_KINDS)),
                  "V4": dict(_view_stats(v4), rule="compute_view.v4 = true인 지식 노드·관계만(그래프활용 §4.1)"),
                  "V5": dict(_view_stats(v5), rule="V1 + V3 + V4, 무방향 MultiGraph")},
        "results": {
            "A1": {"view": "P&ID 레이어(adjacency all, 구간 exploration.relation_kinds)",
                   "function": "hazop.analysis.explore.explore", "parameters": {"start": start}, "result": a1},
            "A2": {"view": "V4 + P&ID 노드", "function": "관계 종류별 인접 조회", "parameters": {},
                   "result": a2_orphans_gaps(kg, graph)},
            "A3": {"view": "V5", "function": "networkx.degree_centrality / degree",
                   "parameters": {"fold_segments": [False, True]}, "result": a3},
            "A4": {"view": "V5", "function": "networkx.ego_graph(undirected=True)",
                   "parameters": {"center": start, "radius": radius}, "result": a4_ego(v5, start, radius)},
            "A5": {"view": "V1, V5", "function": "networkx.connected_components", "parameters": {},
                   "result": a5_components(v1, v5)},
        },
        "limits": {
            "excluded_from_computation": excluded,
            "a1_truncations": a1["exploration"]["truncations"] if a1["active"] else [],
            "a3_segments_not_folded": a3["segments_not_folded"],
            "a3_fold_limit": FOLD_LIMIT,
            "direction_unknown_segments_excluded": "해당 없음(MVP는 방향 뷰 V2를 쓰지 않음)",
        },
        "note": NOTE,
    }
    return doc


def report_text(doc):
    """사람이 읽는 짧은 보고서(마크다운)."""
    i, r = doc["inputs"], doc["results"]
    a1, a2, a3, a4, a5 = (r[k]["result"] for k in ("A1", "A2", "A3", "A4", "A5"))
    ex = doc["limits"]["excluded_from_computation"]
    csv_c = ex["candidate_csv"]
    lines = ["# 지식그래프 알고리즘 결과 (A1~A5)", "",
             "- 지식그래프: %s %s" % (i["kg_id"], i["kg_version"]),
             "- P&ID: %s" % ", ".join("%s %s" % (g["graph_id"], g["graph_version"]) for g in i["graph_refs"]),
             "- 검토 구간: %s" % (("%s (sha256 %s)" % (i["region_ref"]["region_id"], i["region_ref"]["sha256"]))
                              if i["region_ref"] else i["region_key"]),
             "- 선택 노드: %s, ego 깊이 %d" % (i["start"], i["radius"]),
             "- 뷰: " + ", ".join("%s %d노드/%d엣지" % (k, v["nodes"], v["edges"]) for k, v in doc["views"].items()),
             "- 계산 제외: 지식 노드 %d, 지식 관계 %d, 다른 도면 관계 %d"
             % (ex["knowledge_nodes"], ex["knowledge_links"], ex["links_to_other_graphs"]),
             "- kg 내 candidate 관계: %d" % ex["kg_candidate_links"],
             "- 후보 CSV의 미확인 후보: %s" % ("파일 없음" if csv_c is None else "%d (%s)" % (
                 csv_c["unconfirmed_candidates"], csv_c["file"])),
             "", "## A1 상·하류 전파"]
    if a1["active"]:
        s = a1["summary"]
        lines.append("- 구간 %s, 도달 %d" % (a1["region_ref"]["region_id"], s["reached"]))
        for k, v in s["by_direction"].items():
            lines.append("- %s: %s" % (k, ", ".join(v)))
        lines.append("- 정상 유로 아님(NC·LC 경유): %s" % (", ".join(s["not_normal_flow_path"]) or "없음"))
        lines.append("- 밸브 위치 미확인 경유: %s" % (", ".join(s["valve_position_unknown_path"]) or "없음"))
        lines.append("- 한계 도달: %s" % (", ".join(s["limits_hit"]) or "없음"))
    else:
        lines.append("- 비활성: %s" % a1["reason"])
    lines += ["", "## A2 고아·근거 공백 (V4)",
              "- 고아(지식그래프 전체 V4 기준) %d / 판정 %d: %s" % (
                  a2["orphan_count"], a2["knowledge_nodes_judged"], ", ".join(o["id"] for o in a2["orphans"]) or "없음")]
    for o in a2["orphans"]:
        if o.get("link_hints"):
            lines.append("  - %s 연결 힌트: %s" % (o["id"], ", ".join("%s->%s" % (h["chunk"], h["tag"] or h["entity_id"])
                                                                   for h in o["link_hints"])))
    lines.append("- 근거 공백(선택 도면, 자료 요청 메모 후보): %s" % (", ".join(
        "%s(%s)" % (g["tag"], g["entity_id"]) for g in a2["evidence_gaps"]) or "없음"))
    lines.append("- 지식 입력 없음: 설비 %d, 도면 연결점 %d / 도면 객체 %d" % (
        len(a2["no_knowledge_input"]), len(a2["no_knowledge_input_continuations"]), a2["drawing_objects_judged"]))
    top = sorted(a3["degree_segments_folded"].items(), key=lambda kv: (-kv[1]["degree"], kv[0]))[:5]
    lines += ["", "## A3 차수 (V5, 배관 구간 접기)", "- 상위 5: " + ", ".join("%s=%d" % (n, d["degree"]) for n, d in top),
              "- 접지 않은 구간: %d" % len(a3["segments_not_folded"]),
              "- 한계: " + FOLD_LIMIT]
    lines += ["", "## A4 ego graph (V5)"]
    lines.append("- %s" % ("노드 %d, 엣지 %d (배관 구간 %d)" % (len(a4["nodes"]), len(a4["edges"]),
                                                          a4["pipe_segments_in_result"])
                           if a4["active"] else "비활성: " + a4["reason"]))
    lines += ["", "## A5 연결 요소",
              "- V1: %d개(단독 %d), V5: %d개(단독 %d)" % (a5["V1"]["count"], a5["V1"]["singletons"],
                                                    a5["V5"]["count"], a5["V5"]["singletons"]),
              "", "> " + doc["note"], ""]
    return "\n".join(lines)


def _inside(root, path):
    """path를 realpath로 풀어 출력 루트(root의 realpath) 아래인지 확인한다. 중간 디렉터리가 junction·심볼릭 링크로
    루트 밖을 가리키면 AlgoError. 비교 기준은 항상 처음 받은 루트다."""
    root_real = os.path.realpath(root)
    real = os.path.realpath(path)
    if real == root_real or os.path.commonpath([root_real, real]) != root_real:
        raise AlgoError("출력 경로가 출력 루트 밖으로 풀림: %s -> %s" % (path, real))
    return real


def _content_id(doc):
    """결과 JSON과 보고서 바이트의 sha256 앞 12자."""
    h = hashlib.sha256(kg_build.dump_bytes(doc))
    h.update(b"\0")
    h.update(report_text(doc).encode("utf-8"))
    return h.hexdigest()[:12]


def output_dir(out_root, doc):
    """<out_root>/<kg_id>/algo/<kg_version>/<graph_id>@<graph_version>/<구간 식별자>/<start>-r<radius>-<후보 CSV>-h<내용>/
    후보 CSV 식별자 = 'c' + 파일 sha256 앞 12자, 파일이 없으면 'c-none'. 내용 식별자 = 결과 JSON·보고서 바이트의
    sha256 앞 12자. 파일 라벨·생성기·networkx 버전처럼 앞 칸에 없는 값이 바뀌어도 경로가 달라지므로
    같은 경로 = 같은 결과 바이트가 항상 성립한다(W5 Claude 최종 검토 지적, 총괄 수정)."""
    i = doc["inputs"]
    g = i["graph_refs"][0]
    cand = doc["limits"]["excluded_from_computation"]["candidate_csv"]
    parts = [paths.safe_name(i["kg_id"]), "algo", paths.safe_name(i["kg_version"]),
             paths.safe_name(g["graph_id"]) + "@" + paths.safe_name(g["graph_version"]), paths.safe_name(i["region_key"]),
             paths.safe_name("%s-r%d-c%s" % (i["start"], i["radius"], cand["sha256"][:12] if cand else "-none"))[:100]
             + "-h" + _content_id(doc)]  # 해시 접미사는 safe_name 길이 자르기 뒤에 붙여 항상 남김(Codex 5차)
    return _inside(out_root, os.path.join(os.path.realpath(out_root), *parts))


def write_result(out_root, doc):
    """결과 JSON(키 정렬·LF)과 보고서를 한 묶음으로 쓴다. 결과 폴더는 한 번 쓰면 바꾸지 않는다(W3 write_outputs와 같음).
    - 폴더가 없으면 <dir>.partial에 두 파일을 모두 쓴 뒤 os.rename 한 번으로 만든다. 남은 .partial은 지우고 다시 쓴다.
    - 폴더가 있으면 두 파일 sha256이 새 내용과 같을 때 그대로 둔다(쓰지 않음). 다르면 AlgoError, 기존 폴더는 건드리지 않음.
    결과 JSON 경로를 돌려준다."""
    out_dir = output_dir(out_root, doc)
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)
    _inside(out_root, out_dir)  # 부모를 만든 뒤 다시 확인
    files = ((RESULT_FILE, kg_build.dump_bytes(doc)), (REPORT_FILE, report_text(doc).encode("utf-8")))
    if os.path.exists(out_dir):
        for name, data in files:
            path = os.path.join(out_dir, name)
            old = None
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    old = hashlib.sha256(fh.read()).hexdigest()
            if old != hashlib.sha256(data).hexdigest():
                raise AlgoError("%s: 같은 입력 경로에 다른 내용이 있음 - 덮어쓰지 않음(손상 또는 생성기 변경)" % path)
        return os.path.join(out_dir, RESULT_FILE)
    tmp = _inside(out_root, out_dir + ".partial")
    if os.path.exists(tmp):
        shutil.rmtree(tmp)  # 이전 실패로 남은 임시 폴더(정식 경로가 된 적 없음)
    os.makedirs(tmp)
    for name, data in files:
        with open(os.path.join(tmp, name), "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    os.rename(tmp, out_dir)
    return os.path.join(out_dir, RESULT_FILE)
