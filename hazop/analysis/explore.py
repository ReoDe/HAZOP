"""④ 그래프 탐색: 관계 종류·깊이·도달 수를 제한한 결정적 BFS (기획서/HAZOP분석.md '그래프 알고리즘의 역할').

- 이웃 순서와 흐름 판정은 hazop.graph.query.GraphQuery(adjacency, flow_relation)를 그대로 쓴다.
- 방향을 이유로 경로를 버리지 않는다. 각 경로에 확인된 흐름 기준 방향(하류/상류/혼합/미확인)을 표시만 한다.
- 밸브 정상 위치: 경로 중간의 밸브가 NC·LC면 정상 운전 유로가 아님, NO·LO면 열림, 값이 없으면 미확인.
  미확인을 열림·닫힘으로 가정하지 않는다.
- 순환은 방문 상태로 종료하고, 이미 방문한 대상으로 이어지는 엣지를 기록한다.
- 깊이·도달 수 한계, 구간 경계, 다른 도면 연결점에서 멈춘 사실을 truncations에 남긴다.
- 연결상 도달 가능하다는 사실은 인과관계를 입증하지 않는다(경로 근거에 note로 표시).
"""

PHYSICAL = "has_endpoint"
OPEN_POSITIONS = ("NO", "LO")
CLOSED_POSITIONS = ("NC", "LC")
PATH_NOTE = "연결 사실(도달 가능)이며 인과관계를 입증하지 않음"


def region_members(graph, member_ids):
    """도면 객체 member_ids + 양 끝이 모두 구간에 있는 배관 구간 노드."""
    members = set(member_ids)
    ends = {}
    for e in graph["edges"]:
        if e["kind"] == PHYSICAL:
            ends.setdefault(e["segment"], []).append(e["node"])
    for seg, ns in ends.items():
        if ns and all(n in members for n in ns):
            members.add(seg)
    return members


def explore(query, start, members, relation_kinds, max_depth, max_reached, boundary_extension_depth=0):
    """물리 배관 우선 BFS. 1단계: 물리 배관(has_endpoint)만으로 탐색. 2단계: 1단계 방문 대상(BFS 순서)에서
    나머지 관계 종류(계측·신호)까지 넓혀 계속 탐색. 따라서 물리 경로가 있으면 그 경로가 기록된다."""
    kinds = set(relation_kinds)
    adj = query.adjacency("all")
    info = {start: {"depth": 0, "prev": None, "outside": 0}}
    queue = [start]
    truncations, crossings, cycle_edges, seen_trunc = [], [], set(), set()

    def trunc(key, item):
        if key not in seen_trunc:
            seen_trunc.add(key)
            truncations.append(item)

    def run(phase_kinds, head):
        while head < len(queue):
            cur = queue[head]
            head += 1
            depth = info[cur]["depth"]
            if query.nodes[cur]["kind"] == "continuation" and cur != start:
                a = query.nodes[cur]["attributes"]
                trunc(("external_drawing", cur), {
                    "reason": "external_drawing", "at": cur, "to_drawing": a.get("to_drawing"),
                    "to_object": a.get("to_object"), "note": "다른 도면으로 이어짐(이 그래프 밖). 이 실행에서 탐색하지 않음"})
            nbrs = [(nb, eid) for nb, eid in adj[cur] if query.edges[eid]["kind"] in phase_kinds]
            if depth >= max_depth:
                pending = [nb for nb, _ in nbrs if nb not in info]
                if pending:
                    trunc(("max_depth", cur), {"reason": "max_depth", "at": cur, "depth": depth, "not_expanded": pending})
                continue
            for nb, eid in nbrs:
                if nb in info:
                    if info[cur]["prev"] is None or info[cur]["prev"][1] != eid:
                        if not (info[nb]["prev"] and info[nb]["prev"][1] == eid):
                            cycle_edges.add(eid)
                    continue
                outside = 0 if nb in members else info[cur]["outside"] + 1
                if outside > boundary_extension_depth:
                    if not any(c["edge"] == eid for c in crossings):
                        crossings.append({"from": cur, "edge": eid, "outside_node": nb, "action": "not_expanded",
                                          "reason": "구간 경계 밖(확장 깊이 %d)" % boundary_extension_depth})
                    continue
                if len(info) - 1 >= max_reached:
                    trunc(("max_reached", cur, eid), {"reason": "max_reached", "at": cur, "edge": eid, "node": nb})
                    continue
                info[nb] = {"depth": depth + 1, "prev": (cur, eid), "outside": outside}
                queue.append(nb)

    run(kinds & {PHYSICAL}, 0)
    if kinds - {PHYSICAL}:
        run(kinds, 0)

    reached = [_describe_path(query, start, nid, info) for nid in queue[1:]]
    object_members = sorted(m for m in members if query.nodes[m]["node_type"] != "pipe_segment")
    return {
        "exploration_id": "explore-%s" % start,
        "start": start,
        "settings": {"relation_kinds": sorted(kinds), "max_depth": max_depth, "max_reached": max_reached,
                     "boundary_extension_depth": boundary_extension_depth,
                     "algorithm": "physical-first deterministic BFS (1단계 has_endpoint만, 2단계 전체 관계), "
                                  "neighbors sorted by (entity_id, edge entity_id) (hazop.graph.query.GraphQuery.adjacency)"},
        "terminated": True,
        "reached": reached,
        "truncations": truncations,
        "boundary_crossings": crossings,
        "cycle_or_merge_edges": sorted(cycle_edges),
        "unreached_region_members": [m for m in object_members if m not in info],
        "limits_hit": sorted({t["reason"] for t in truncations if t["reason"] in ("max_depth", "max_reached")}),
    }


def _describe_path(query, start, goal, info):
    nodes, edges, c = [goal], [], goal
    while info[c]["prev"] is not None:
        c, eid = info[c]["prev"]
        nodes.insert(0, c)
        edges.insert(0, eid)
    edge_kinds = [query.edges[e]["kind"] for e in edges]
    material = all(k == PHYSICAL for k in edge_kinds)
    seg_flow = []
    for i in range(1, len(nodes) - 1):
        if query.nodes[nodes[i]]["node_type"] == "pipe_segment":
            seg_flow.append({"segment": nodes[i], "flow": query.flow_relation(nodes[i], edges[i - 1], edges[i])})
    valves = []
    for i in range(1, len(nodes) - 1):
        n = query.nodes[nodes[i]]
        # 밸브 통과 판정은 물리 배관으로 들어오고 나간 경우만
        if n["category"] == "valve" and edge_kinds[i - 1] == PHYSICAL and edge_kinds[i] == PHYSICAL:
            pos = n["attributes"].get("normal_position")
            valves.append({"entity_id": nodes[i], "tag": n.get("tag"), "kind": n["kind"],
                           "normal_position": pos, "fail_position": n["attributes"].get("fail_position"),
                           "state": "closed" if pos in CLOSED_POSITIONS else
                           "open" if pos in OPEN_POSITIONS else "unknown"})
    states = {v["state"] for v in valves}
    if not valves:
        valve_state = "no_valves"
    elif "closed" in states:
        valve_state = "closed_valve_on_path"
    elif "unknown" in states:
        valve_state = "position_unknown_on_path"
    else:
        valve_state = "all_open"
    if not material:
        normal_flow = "not_material_path"
    elif valve_state == "closed_valve_on_path":
        normal_flow = False
    elif valve_state == "position_unknown_on_path":
        normal_flow = None
    else:
        normal_flow = True
    flows = {s["flow"] for s in seg_flow}
    if not material or not seg_flow:
        direction = "not_applicable" if not material else "adjacent"
    elif "unknown" in flows:
        direction = "direction_unknown"
    elif flows == {"with_flow"}:
        direction = "downstream"
    elif flows == {"against_flow"}:
        direction = "upstream"
    else:
        direction = "mixed"
    n = query.nodes[goal]
    return {"entity_id": goal, "tag": n.get("tag"), "kind": n["kind"], "node_type": n["node_type"],
            "category": n["category"], "depth": info[goal]["depth"], "outside_region": info[goal]["outside"] > 0,
            "path_nodes": nodes, "path_edges": edges, "path_edge_kinds": edge_kinds,
            "material_flow_path": material, "segment_flow": seg_flow, "direction_from_start": direction,
            "valves_on_path": valves, "valve_state": valve_state, "normal_operation_flow": normal_flow,
            "note": PATH_NOTE}
