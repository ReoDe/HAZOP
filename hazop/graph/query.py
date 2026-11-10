"""단계 ③ 기본 질의(그래프 검증용). HAZOP 편차 탐색이 아니다(그것은 ④).

- neighbors(ref): 바로 이웃과, 배관 구간 너머의 노드
- path(a, b, mode): mode=physical(has_endpoint만) / all(모든 엣지)의 '방향 무시 경로'와,
  모드와 관계없이 물리 배관(has_endpoint)만 쓰는 '확인된 흐름 방향만 따르는 경로'를 나눠 돌려준다.
  방향을 만들어 내지 않는다. 밸브 정상 위치(NC·LC 등)·제어밸브 실패 위치는 반영하지 않는다(열린 유로로 간주).
- components(): 물리 연결 성분(has_endpoint)

경로 탐색 규칙(뷰어 JS와 동일해야 함. scripts/check_viewer_paths.js가 대조):
  결정적 BFS. 각 노드의 이웃을 (이웃 entity_id, 엣지 entity_id) 오름차순으로 방문하고,
  처음 발견할 때의 이전 노드·엣지를 기록한다. 따라서 홉 수 최단 경로 중 하나가 항상 같게 나온다.
  흐름 판정은 노드가 아니라 has_endpoint 엣지의 end(source/target) 기준이다.
"""

from .build import to_networkx

MODES = ("physical", "all")
VALVE_POSITION_NOTE = "밸브 정상 위치(NC·LC 등)와 실패 위치는 반영하지 않음(모든 밸브를 열린 유로로 간주)"


class QueryError(ValueError):
    pass


class GraphQuery:

    def __init__(self, graph):
        self.graph = graph
        self.nodes = {n["entity_id"]: n for n in graph["nodes"]}
        self.edges = {e["entity_id"]: e for e in graph["edges"]}
        self._adj = {}

    # ------------------------------------------------------------ 식별
    def resolve(self, ref):
        """entity_id, 추출 local_id, 원본 객체 ID, tag(대소문자 무시) 중 하나로 노드를 찾는다."""
        if ref in self.nodes:
            return ref
        hits = [n["entity_id"] for n in self.graph["nodes"]
                if ref in (n.get("local_id"), n.get("source_object_id"))]
        if not hits:
            low = str(ref).lower()
            hits = [n["entity_id"] for n in self.graph["nodes"]
                    if n.get("tag") and n["tag"].lower() == low and n["node_type"] != "pipe_segment"]
            if not hits:  # 라인 번호는 여러 구간이 공유하므로 마지막에 본다
                hits = [n["entity_id"] for n in self.graph["nodes"] if n.get("tag") and n["tag"].lower() == low]
        if not hits:
            raise QueryError("대상을 찾을 수 없음: %r" % ref)
        if len(hits) > 1:
            raise QueryError("대상이 여러 개임(%r): %s" % (ref, hits))
        return hits[0]

    def describe(self, eid):
        n = self.nodes[eid]
        return {"entity_id": eid, "kind": n["kind"], "tag": n.get("tag"), "local_id": n.get("local_id")}

    # ------------------------------------------------------------ 인접(결정적 순서)
    def adjacency(self, kind):
        """kind: 'physical' | 'all' | 'directed'. 노드 -> [(이웃, 엣지 id)] (이웃 id, 엣지 id) 오름차순."""
        if kind in self._adj:
            return self._adj[kind]
        adj = {nid: [] for nid in self.nodes}
        for e in self.graph["edges"]:
            if kind != "all" and e["kind"] != "has_endpoint":
                continue
            a, b = e["nodes"]
            if kind == "directed":
                flow = self.nodes[e["segment"]].get("flow_direction")
                if not flow:
                    continue
                if e["end"] == flow["from_end"]:
                    adj[e["node"]].append((e["segment"], e["entity_id"]))
                elif e["end"] == flow["to_end"]:
                    adj[e["segment"]].append((e["node"], e["entity_id"]))
            else:
                adj[a].append((b, e["entity_id"]))
                if a != b:
                    adj[b].append((a, e["entity_id"]))
        for nid in adj:
            adj[nid].sort()
        self._adj[kind] = adj
        return adj

    @staticmethod
    def bfs(adj, start, goal):
        """결정적 BFS. (노드 목록, 엣지 목록) 또는 None."""
        prev = {start: None}
        queue, head = [start], 0
        while head < len(queue):
            cur = queue[head]
            head += 1
            if cur == goal:
                break
            for nb, eid in adj.get(cur, []):
                if nb not in prev:
                    prev[nb] = (cur, eid)
                    queue.append(nb)
        if goal not in prev:
            return None
        nodes, edges, c = [goal], [], goal
        while prev[c] is not None:
            c, eid = prev[c]
            nodes.insert(0, c)
            edges.insert(0, eid)
        return nodes, edges

    def flow_relation(self, seg, edge_in, edge_out):
        """구간 seg를 has_endpoint edge_in으로 들어와 edge_out으로 나갈 때: with_flow / against_flow / unknown."""
        flow = self.nodes[seg].get("flow_direction")
        if not flow:
            return "unknown"
        ein, eout = self.edges[edge_in]["end"], self.edges[edge_out]["end"]
        if ein == flow["from_end"] and eout == flow["to_end"]:
            return "with_flow"
        if ein == flow["to_end"] and eout == flow["from_end"]:
            return "against_flow"
        return "unknown"

    # ------------------------------------------------------------ 이웃
    def neighbors(self, ref):
        eid = self.resolve(ref)
        adj = self.adjacency("all")
        direct, beyond = [], []
        for nb, edge in adj[eid]:
            direct.append({"edge": edge, "edge_kind": self.edges[edge]["kind"], "neighbor": self.describe(nb)})
            if self.nodes[nb]["node_type"] == "pipe_segment" and self.nodes[eid]["node_type"] != "pipe_segment":
                for far, edge2 in adj[nb]:
                    if edge2 != edge:
                        beyond.append({"via_segment": nb, "node": self.describe(far),
                                       "flow": self.flow_relation(nb, edge, edge2)})
        return {"target": self.describe(eid), "direct": direct, "via_segment": beyond}

    # ------------------------------------------------------------ 경로
    def path(self, a, b, mode="physical"):
        if mode not in MODES:
            raise QueryError("mode는 %s 중 하나: %r" % (list(MODES), mode))
        sa, sb = self.resolve(a), self.resolve(b)
        result = {"from": self.describe(sa), "to": self.describe(sb), "mode": mode, "note": VALVE_POSITION_NOTE}
        found = self.bfs(self.adjacency(mode), sa, sb)
        if found:
            nodes, edges = found
            steps, unknown, against = [], [], []
            for i, nid in enumerate(nodes):
                step = self.describe(nid)
                if self.nodes[nid]["node_type"] == "pipe_segment" and 0 < i < len(nodes) - 1:
                    rel = self.flow_relation(nid, edges[i - 1], edges[i])
                    step["flow"] = rel
                    if rel == "unknown":
                        unknown.append(nid)
                    elif rel == "against_flow":
                        against.append(nid)
                steps.append(step)
            result["ignoring_direction"] = {
                "found": True, "length": len(nodes) - 1, "nodes": steps,
                "edges": [{"entity_id": e, "kind": self.edges[e]["kind"]} for e in edges],
                "segments_direction_unknown": unknown, "segments_against_flow": against}
        else:
            result["ignoring_direction"] = {"found": False}
        found = self.bfs(self.adjacency("directed"), sa, sb)
        if found:
            nodes, edges = found
            result["confirmed_flow_direction"] = {
                "found": True, "length": len(nodes) - 1, "nodes": [self.describe(x) for x in nodes],
                "edges": [{"entity_id": e, "kind": self.edges[e]["kind"]} for e in edges]}
        else:
            result["confirmed_flow_direction"] = {
                "found": False,
                "reason": "확인된 흐름 방향의 물리 배관만으로는 경로 없음(방향 미확인 구간·흐름 반대·계측/신호 연결만 있는 경우 등)"}
        result["confirmed_flow_direction"]["scope"] = "물리 배관(has_endpoint)만, 모드와 무관"
        if mode == "all":
            result["mode_note"] = "all 모드의 방향 무시 경로는 계장 신호·계측 연결을 포함하며 물질 흐름 경로가 아님"
        return result

    def path_signature(self, a, b, mode):
        """뷰어 JS 대조용 요약: [방향 무시 노드열, 확인 흐름 노드열, 방향 미확인 구간, 흐름 반대 구간]."""
        p = self.path(a, b, mode)
        u, d = p["ignoring_direction"], p["confirmed_flow_direction"]
        return [" ".join(n["entity_id"] for n in u["nodes"]) if u["found"] else None,
                " ".join(n["entity_id"] for n in d["nodes"]) if d["found"] else None,
                " ".join(u.get("segments_direction_unknown", [])),
                " ".join(u.get("segments_against_flow", []))]

    SEGMENT_SAMPLE_STEP = 5

    def path_expectations(self):
        """뷰어 JS 대조용 경로 요약(두 모드).
        - 도면 객체 노드끼리: 모든 순서쌍
        - 배관 구간 노드가 한쪽 이상 끝점인 쌍: 결정적 표본(전체 노드 정렬 순번 i, j에 대해 (i*31 + j) % 5 == 0)"""
        everyone = sorted(self.nodes)
        cases, sampled = {}, 0
        for i, a in enumerate(everyone):
            for j, b in enumerate(everyone):
                if a == b:
                    continue
                has_seg = "pipe_segment" in (self.nodes[a]["node_type"], self.nodes[b]["node_type"])
                if has_seg and (i * 31 + j) % self.SEGMENT_SAMPLE_STEP:
                    continue
                sampled += has_seg
                for mode in MODES:
                    cases["%s|%s|%s" % (a, b, mode)] = self.path_signature(a, b, mode)
        return {"graph_id": self.graph["graph_id"], "graph_version": self.graph["graph_version"],
                "segment_pairs_sampled": sampled,
                "rule": "deterministic BFS, neighbors sorted by (entity_id, edge entity_id)",
                "format": "key 'from|to|mode' -> [방향 무시 노드열, 확인 흐름 노드열, 방향 미확인 구간, 흐름 반대 구간]",
                "cases": cases}

    # ------------------------------------------------------------ 성분
    def components(self):
        import networkx as nx
        g = to_networkx(self.graph, kinds={"has_endpoint"})
        comps = []
        for c in nx.connected_components(g):
            if len(c) < 2:
                continue
            members = sorted(c)
            comps.append({"size": len(members),
                          "objects": [self.describe(x) for x in members if self.nodes[x]["node_type"] != "pipe_segment"],
                          "segments": [x for x in members if self.nodes[x]["node_type"] == "pipe_segment"]})
        comps.sort(key=lambda c: (-c["size"], c["segments"]))
        alone = sorted(n for n in g.nodes if g.degree(n) == 0)
        return {"physical_components": comps,
                "not_physically_connected": [self.describe(x) for x in alone]}
