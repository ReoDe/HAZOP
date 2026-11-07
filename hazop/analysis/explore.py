"""④ 그래프 탐색: 관계 종류·깊이·도달 수를 제한한 결정적 BFS (기획서/HAZOP분석.md '그래프 알고리즘의 역할').

- 이웃 순서와 흐름 판정은 hazop.graph.query.GraphQuery(adjacency, flow_relation)를 그대로 쓴다.
- 방향을 이유로 경로를 버리지 않는다. 각 경로에 확인된 흐름 기준 방향(하류/상류/혼합/미확인)을 표시만 한다.
- 밸브 정상 위치: 경로 중간의 밸브가 NC·LC면 정상 운전 유로가 아님, NO·LO면 열림, 값이 없으면 미확인.
  미확인을 열림·닫힘으로 가정하지 않는다.
- 순환은 방문 상태로 종료하고, 이미 방문한 대상으로 이어지는 엣지를 기록한다.
- 깊이·도달 수 한계, 구간 경계, 다른 도면 연결점에서 멈춘 사실을 truncations에 남긴다. 프로젝트 그래프
  (hazop.graph.project)에서 상대 도면과 이어진 연결점은 멈추지 않고 넘어간다.
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


def _bfs(query, start, members, kinds, max_depth, max_reached, ext):
    """결정적 BFS 1회. 상태 = (대상, 깊이, 경계 밖 누적 깊이, 이전 상태).
    - 대상의 첫 상태가 최단 깊이이며, 그 상태의 경로를 기록한다(경로 길이 = 깊이).
    - 이미 방문한 대상이라도 경계 밖 깊이가 더 작은(확장 여유가 큰) 상태로 닿으면 그 상태를 추가로 펼친다.
      이 상태는 기록 경로·최단 깊이를 바꾸지 않고, 그 너머 대상을 찾는 데만 쓴다. 경계 밖 깊이는 줄어들기만 하므로 끝난다.
    반환: (경로 {대상: (노드들, 엣지들, 경계 밖 깊이)}, 발견 순서, 절단, 경계 이탈, 순환 엣지)"""
    adj = query.adjacency("all")
    states = [(start, 0, 0, None, None)]  # (node, depth, outside, prev_state, edge)
    first = {start: 0}
    best_out = {start: 0}
    order = [start]
    head = 0
    truncations, crossings, cycle_edges, seen_trunc = [], [], set(), set()

    def trunc(key, item):
        if key not in seen_trunc:
            seen_trunc.add(key)
            truncations.append(item)

    while head < len(states):
        sid = head
        cur, depth, out_cur, prev_sid, in_edge = states[head]
        head += 1
        linked = (query.nodes[cur].get("sheet_link") or {}).get("status") == "linked"  # 프로젝트 그래프에서 이어진 연결점
        if query.nodes[cur]["kind"] == "continuation" and cur != start and not linked:  # 최대 깊이에 걸려도 기록
            a = query.nodes[cur]["attributes"]
            trunc(("external_drawing", cur), {
                "reason": "external_drawing", "at": cur, "to_drawing": a.get("to_drawing"),
                "to_object": a.get("to_object"), "note": "다른 도면으로 이어짐(이 그래프 밖). 이 실행에서 탐색하지 않음"})
        nbrs = [(nb, eid) for nb, eid in adj[cur] if query.edges[eid]["kind"] in kinds]
        if depth >= max_depth:
            pending = [nb for nb, _ in nbrs if nb not in first]
            if pending:
                trunc(("max_depth", cur), {"reason": "max_depth", "at": cur, "depth": depth, "not_expanded": pending})
            continue
        for nb, eid in nbrs:
            if eid == in_edge:
                continue
            outside = 0 if nb in members else out_cur + 1
            if nb in first:
                if outside < best_out[nb]:  # 확장 여유가 더 큰 상태로 추가 탐색
                    best_out[nb] = outside
                    states.append((nb, depth + 1, outside, sid, eid))
                elif states[first[nb]][4] != eid:
                    cycle_edges.add(eid)
                continue
            if outside > ext:
                if not any(c["edge"] == eid for c in crossings):
                    crossings.append({"from": cur, "edge": eid, "outside_node": nb, "action": "not_expanded",
                                      "reason": "구간 경계 밖(확장 깊이 %d)" % ext})
                continue
            if len(first) - 1 >= max_reached:
                trunc(("max_reached", cur, eid), {"reason": "max_reached", "at": cur, "edge": eid, "node": nb})
                continue
            first[nb] = len(states)
            best_out[nb] = outside
            order.append(nb)
            states.append((nb, depth + 1, outside, sid, eid))
    paths = {}
    for node, sid in first.items():
        nodes, edges, k = [], [], sid
        out = states[sid][2]
        while k is not None:
            n, _, _, prev, e = states[k]
            nodes.insert(0, n)
            if e is not None:
                edges.insert(0, e)
            k = prev
        paths[node] = (nodes, edges, out)
    return paths, order, truncations, crossings, cycle_edges


def explore(query, start, members, relation_kinds, max_depth, max_reached, boundary_extension_depth=0):
    """도달 여부·깊이 한계는 지정한 관계 종류 전체의 최단 깊이로 판정한다(관계 종류 때문에 대상을 놓치지 않음).
    기록하는 경로는 물리 배관(has_endpoint)만으로 도달할 수 있으면 그 경로를, 아니면 전체 관계의 최단 경로를 쓴다.
    depth = 기록 경로의 길이, shortest_depth = 전체 관계 기준 최단 깊이."""
    kinds = set(relation_kinds)
    paths, order, truncations, crossings, cycle_edges = _bfs(query, start, members, kinds, max_depth, max_reached,
                                                             boundary_extension_depth)
    phys = None
    if PHYSICAL in kinds and kinds - {PHYSICAL}:
        phys = _bfs(query, start, members, {PHYSICAL}, max_depth, max_reached, boundary_extension_depth)[0]
    reached = []
    for nid in order[1:]:
        use = phys if phys and nid in phys else paths
        nodes, edges, out = use[nid]
        r = _describe_path(query, nodes, edges, out)
        r["shortest_depth"] = len(paths[nid][1])
        r["path_basis"] = "physical_preferred" if use is phys else "shortest_all_kinds"
        reached.append(r)
    object_members = sorted(m for m in members if query.nodes[m]["node_type"] != "pipe_segment")
    return {
        "exploration_id": "explore-%s" % start,
        "start": start,
        "settings": {"relation_kinds": sorted(kinds), "max_depth": max_depth, "max_reached": max_reached,
                     "boundary_extension_depth": boundary_extension_depth,
                     "algorithm": "deterministic BFS over all relation kinds (shortest depth); recorded path prefers "
                                  "has_endpoint-only path when one exists within limits; boundary extension revisits a "
                                  "node only with a smaller outside depth; neighbors sorted by (entity_id, edge entity_id) "
                                  "(hazop.graph.query.GraphQuery.adjacency)"},
        "terminated": True,
        "reached": reached,
        "truncations": truncations,
        "boundary_crossings": crossings,
        "cycle_or_merge_edges": sorted(cycle_edges),
        "unreached_region_members": [m for m in object_members if m not in paths],
        "limits_hit": sorted({t["reason"] for t in truncations if t["reason"] in ("max_depth", "max_reached")}),
    }


def _describe_path(query, nodes, edges, outside):
    goal = nodes[-1]
    edge_kinds = [query.edges[e]["kind"] for e in edges]
    material = all(k == PHYSICAL for k in edge_kinds)
    seg_flow = []
    for i in range(1, len(nodes) - 1):
        if query.nodes[nodes[i]]["node_type"] == "pipe_segment":
            seg_flow.append({"segment": nodes[i], "flow": query.flow_relation(nodes[i], edges[i - 1], edges[i])})
    valves = []
    for i in range(0, len(nodes) - 1):
        n = query.nodes[nodes[i]]
        # 밸브 통과 판정은 물리 배관으로 들어오고 나간 경우만. 시작 대상이 밸브면 거기서 나가는 경로도 그 밸브를 거침
        through = edge_kinds[i] == PHYSICAL and (i == 0 or edge_kinds[i - 1] == PHYSICAL)
        if n["category"] == "valve" and through:
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
            "category": n["category"], "depth": len(edges), "outside_region": outside > 0,
            "path_nodes": nodes, "path_edges": edges, "path_edge_kinds": edge_kinds,
            "material_flow_path": material, "segment_flow": seg_flow, "direction_from_start": direction,
            "valves_on_path": valves, "valve_state": valve_state, "normal_operation_flow": normal_flow,
            "note": PATH_NOTE}
