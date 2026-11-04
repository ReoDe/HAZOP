"""④ 원인·결과 패턴 적용 (기획서/HAZOP분석.md #patterns).

탐색이 찾은 기기에 기기 종류 × 후보(파라미터·가이드워드) 패턴을 맞춘다. 결과는 모두 가설이다.
- 조건 속성이 그래프에 없으면 condition_unknown: 적용하지 않고 보류 사유로 남긴다(임의 가정 금지).
- 패턴이 하나도 없는 기기 종류는 kinds_without_patterns로 구분한다(AI 가설과 섞지 않기 위함).
- 도달했으나 적용된 원인 패턴이 없는 대상은 connection_only(연결 사실만 있고 인과 근거 없음)로 둔다.
- 보호수단은 패턴이 아니라 편차(후보)별 deviation_safeguards로 찾는다(match_safeguards).
"""

from . import equipment

SIGNAL = "signal_connection"


class _Blank(dict):
    def __missing__(self, key):
        return "미확인"


def chain_scope(exploration):
    """신호 사슬을 따라갈 수 있는 대상 집합. 탐색 설정에 signal_connection이 없으면 None(사슬 조건은 성립하지 않음).
    사슬은 탐색이 도달한 대상(구간·확장 범위 안)만 지나며, 설정 밖으로 원인 설비를 늘리지 않는다."""
    if SIGNAL not in exploration["settings"]["relation_kinds"]:
        return None
    return {exploration["start"]} | {r["entity_id"] for r in exploration["reached"]}


def _signal_chain(query, start, kinds, scope):
    """start에서 signal_connection을 따라 kinds 순서의 기기가 이어지는 첫 사슬(결정적). (노드들, 엣지들) 또는 None."""
    if scope is None:
        return None
    adj = query.adjacency("all")

    def walk(cur, i, seen):
        if i == len(kinds):
            return [], []
        for nb, eid in adj[cur]:
            if query.edges[eid]["kind"] != SIGNAL or nb in seen or nb not in scope or query.nodes[nb]["kind"] != kinds[i]:
                continue
            rest = walk(nb, i + 1, seen | {nb})
            if rest is not None:
                return [nb] + rest[0], [eid] + rest[1]
        return None

    return walk(start, 0, {start})


def _check(query, pattern, node_id, scope):
    """(status, detail, chain) — status: applied / condition_unknown / condition_not_met."""
    node = query.nodes[node_id]
    cond = pattern.get("conditions") or {}
    for attr, allowed in sorted((cond.get("attributes") or {}).items()):
        val = node["attributes"].get(attr)
        if val is None:
            return "condition_unknown", "속성 %s 미확인(그래프에 값 없음)" % attr, None
        if val not in allowed:
            return "condition_not_met", "속성 %s=%s, 조건 %s" % (attr, val, allowed), None
    chain = None
    if cond.get("signal_chain"):
        chain = _signal_chain(query, node_id, cond["signal_chain"], scope)
        if chain is None:
            return "condition_not_met", "신호 연결 사슬 %s 없음(그래프 구조·탐색 범위)" % cond["signal_chain"], None
    return "applied", None, chain


def match_patterns(library, item_id, focus, exploration, query):
    """후보 item_id에 대한 패턴 적용 결과."""
    targets = [(focus, "focus")] + [(r["entity_id"], "reached") for r in exploration["reached"]
                                    if r["node_type"] != "pipe_segment"]
    kinds_with_any = {p["equipment_kind"] for p in library["patterns"]}
    reach = chain_scope(exploration)
    applied, not_applied, kinds_without = [], [], set()
    for node_id, scope in targets:
        node = query.nodes[node_id]
        if node["kind"] not in kinds_with_any:
            kinds_without.add(node["kind"])
        for p in library["patterns"]:
            if p["equipment_kind"] != node["kind"] or p["scope"] != scope or item_id not in p["candidate_items"]:
                continue
            status, detail, chain = _check(query, p, node_id, reach)
            if status != "applied":
                not_applied.append({"pattern_id": p["pattern_id"], "pattern_version": p["pattern_version"],
                                    "target": node_id, "tag": node.get("tag"), "status": status, "detail": detail})
                continue
            chain_nodes, chain_edges = chain or ([], [])
            fmt = _Blank(tag=node.get("tag") or node_id,
                         chain_tags=", ".join(query.nodes[c].get("tag") or c for c in chain_nodes))
            fmt.update({"attr_" + k: v for k, v in node["attributes"].items()})
            m = {"match_id": "m-%s-%s" % (p["pattern_id"], node_id), "pattern_id": p["pattern_id"],
                 "pattern_version": p["pattern_version"], "source": p["source"], "role": p["role"],
                 "target": node_id, "tag": node.get("tag"), "kind": node["kind"],
                 "condition": p.get("conditions") or {}, "knowledge_status": "hypothesis",
                 "node_ids": [node_id] + chain_nodes, "relation_ids": chain_edges}
            m["cause"] = p["cause_template"].format_map(fmt)
            m["consequence"] = p["consequence_template"].format_map(fmt)
            applied.append(m)
    cause_targets = {m["target"] for m in applied if m["role"] == "cause"}
    safeguards, sg_not_applied = match_safeguards(library, item_id, exploration, query)
    not_applied += sg_not_applied
    safeguard_targets = {g["node_id"] for g in safeguards}
    connection_only = [{"entity_id": r["entity_id"], "tag": r["tag"], "kind": r["kind"],
                        "evidence_id": "ev-path-%s" % r["entity_id"],
                        "note": "도달 가능한 연결만 있고 이 후보에 대한 원인 패턴·보호수단 조건 없음 — 원인으로 단정하지 않음"}
                       for r in exploration["reached"]
                       if r["node_type"] != "pipe_segment" and r["entity_id"] not in cause_targets
                       and r["entity_id"] not in safeguard_targets]
    return {"item_id": item_id, "library_id": library["library_id"], "library_version": library["library_version"],
            "applied": applied, "not_applied": not_applied, "safeguards": safeguards,
            "connection_only": connection_only, "kinds_without_patterns": sorted(kinds_without)}


def match_safeguards(library, item_id, exploration, query):
    """편차(후보)별 보호수단 후보: 도달한 기기 중 kind·구조·속성 조건을 만족하는 것.
    속성이 없으면(미확인) 올리지 않고 condition_unknown으로 돌려준다. (보호수단 목록, 미적용 목록)"""
    out, seen, not_applied = [], set(), []
    scope = chain_scope(exploration)
    for spec in library.get("deviation_safeguards") or []:
        if item_id not in spec["candidate_items"]:
            continue
        for r in exploration["reached"]:
            nid = r["entity_id"]
            if r["kind"] != spec["kind"] or nid in seen:
                continue
            node = query.nodes[nid]
            attrs = spec.get("attributes") or {}
            missing = sorted(k for k in attrs if node["attributes"].get(k) is None)
            if missing:
                not_applied.append({"pattern_id": spec["safeguard_id"], "pattern_version": spec["version"],
                                    "target": nid, "tag": node.get("tag"), "status": "condition_unknown",
                                    "detail": "보호수단 조건 속성 %s 미확인(그래프에 값 없음)" % ", ".join(missing)})
                continue
            if any(node["attributes"].get(k) not in allowed for k, allowed in attrs.items()):
                continue
            chain = _signal_chain(query, nid, spec["signal_chain"], scope) if spec.get("signal_chain") else None
            if spec.get("signal_chain") and chain is None:
                continue
            seen.add(nid)
            fmt = _Blank(tag=node.get("tag") or nid)
            fmt.update({"attr_" + k: v for k, v in node["attributes"].items()})
            out.append({"node_id": nid, "tag": node.get("tag"), "kind": node["kind"],
                        "protective_action": spec["protective_action"],
                        "action_confirmed": equipment.protective_action_confirmed(node, spec["protective_action"]),
                        "source": "deviation_safeguard:%s@v%s" % (spec["safeguard_id"], spec["version"]),
                        "description": spec["description_template"].format_map(fmt),
                        "chain_node_ids": chain[0] if chain else [], "chain_relation_ids": chain[1] if chain else []})
    return out, not_applied
