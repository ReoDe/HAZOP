"""④ HAZOP 분석 실행: 입력 고정 -> 후보 판단 -> 탐색 -> 패턴 -> AI 해석·검증 -> 위험도 -> 설계보완 후보 -> 보류 -> 결과 검증·저장.

근거: 기획서/HAZOP분석.md(MVP 범위, 도면 설비 한정, 설계보완 후보, 정보 부족과 결과 저장, 독립 검증),
기획서/전체기획.md #data-contract(④ -> ⑤).
저장: 출력/분석/<구간 ID>/<실행 ID>/analysis.json + inputs/(입력 원본 사본). execute()는 AI 단계 전에 후보·탐색·패턴
결과를 먼저 저장하고, 후보마다 이어 저장한다. 중단·예외가 나도 그때까지의 결과가 남고 resume()으로 AI 단계부터 재시도한다.
"""

import copy
import datetime
import hashlib
import json
import os

from hazop import paths
from hazop.graph.query import GraphQuery

from . import ai, candidates as cand_mod, equipment, explore as ex_mod, patterns as pat_mod, risk as risk_mod, validate

SCHEMA_VERSION = "0.1"
ANALYZER = "hazop.analysis"
ANALYZER_VERSION = "0.2.0"
INPUT_ROLES = ("region", "graph", "candidate_catalog", "applicability", "patterns", "risk_criteria")
AI_DONE = "validated"
SCENARIO_STATUS = ("draft", "deferred")
ACCEPTED = "위험작업 수용"  # 〈표9〉 비고: 이 값이 아니면 조건부 수용 이상(지침서 §6, [추론] 해석)
SAFEGUARD_NOTE = "그래프에 존재만 확인. 독립성·용량·작동 적정성 미확인"
SIGNAL = "signal_connection"


class InputError(ValueError):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_obj(obj):
    return _sha_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


# ---------------------------------------------------------------- 입력
def _resolve(path, repo_root):
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


def load_inputs(region_path, repo_root, graph_path=None):
    """구간 JSON과 그것이 가리키는 파일을 읽어 prepare()로 검사한다."""
    raw, docs, files = {}, {}, []

    def read(role, path):
        if path is None:
            docs[role] = None
            return
        full = _resolve(path, repo_root)
        if not os.path.isfile(full):
            raise InputError("%s 파일 없음: %s" % (role, path))
        with open(full, encoding="utf-8") as fh:
            raw[role] = fh.read()
        docs[role] = json.loads(raw[role])
        files.append({"role": role, "path": paths.rel_or_abs(full, repo_root),
                      "sha256": _sha_text(raw[role])})

    read("region", region_path)
    region = docs["region"]
    read("graph", graph_path or region["graph_ref"]["graph_file"])
    for role in INPUT_ROLES[2:]:
        read(role, (region.get("inputs") or {}).get(role))
    inputs = prepare(region, docs["graph"], docs["candidate_catalog"], docs["applicability"], docs["patterns"],
                     docs["risk_criteria"], files=files)
    inputs["raw"] = raw
    return inputs


def _member_mismatches(region, graph):
    nodes = {n["entity_id"]: n for n in graph["nodes"]}
    out = []
    for m in region["members"]:
        n = nodes.get(m["entity_id"])
        if n is None:
            out.append("구간 포함 대상이 그래프에 없음: %s" % m["entity_id"])
        elif n.get("tag") != m.get("tag"):
            out.append("구간 포함 대상 태그 불일치: %s 구간 %r, 그래프 %r" % (m["entity_id"], m.get("tag"), n.get("tag")))
    return out


def prepare(region, graph, catalog, applicability, patterns, criteria, files=None):
    """입력 검사. 차단 오류(blockers)가 있으면 분석하지 않는다."""
    blockers = []
    ref = region["graph_ref"]
    if graph["validation"]["status"] != "passed":
        blockers.append("그래프 구조 검증이 passed가 아님(%s) — 정상 입력으로 쓰지 않음" % graph["validation"]["status"])
    if (graph["graph_id"], graph["graph_version"]) != (ref["graph_id"], ref["graph_version"]):
        blockers.append("그래프 버전 불일치: 구간은 %s/%s, 입력은 %s/%s — 최신 버전으로 조용히 바꾸지 않음. "
                        "차이를 확인한 뒤 scripts/analyze.py --rebind-graph 로 구간 JSON을 갱신해야 함"
                        % (ref["graph_id"], ref["graph_version"], graph["graph_id"], graph["graph_version"]))
    nodes = {n["entity_id"]: n for n in graph["nodes"]}
    blockers += _member_mismatches(region, graph)
    member_ids = {m["entity_id"] for m in region["members"]}
    if len(region.get("focus_entities") or []) != 1:
        blockers.append("MVP는 중심 대상(focus_entities) 1개만 지원")
    for f in region.get("focus_entities") or []:
        if f not in member_ids:
            blockers.append("중심 대상이 구간 포함 대상에 없음: %s" % f)
    for b in region.get("boundaries") or []:
        if b["entity_id"] not in member_ids:
            blockers.append("경계 대상이 구간 포함 대상에 없음: %s" % b["entity_id"])
    for c in region.get("normal_operating_conditions") or []:
        if c.get("entity_id") and c["entity_id"] not in nodes:
            blockers.append("운전조건 대상이 그래프에 없음: %s" % c["entity_id"])
    if region.get("operating_mode") != "normal":
        blockers.append("MVP는 정상 운전(normal)만 지원: %r" % region.get("operating_mode"))
    if graph.get("project_id") != region.get("project_id"):
        blockers.append("project_id 불일치: 구간 %r, 그래프 %r" % (region.get("project_id"), graph.get("project_id")))
    if catalog is None or patterns is None:
        blockers.append("이탈 후보 카탈로그와 패턴 라이브러리는 필수")
    if applicability is not None and catalog is not None:
        cref = applicability.get("catalog_ref") or {}
        if (cref.get("catalog_id"), cref.get("catalog_version")) != (catalog["catalog_id"], catalog["catalog_version"]):
            blockers.append("적용 판단 파일의 카탈로그 참조가 카탈로그와 다름")
        if applicability.get("region_id") != region["region_id"]:
            blockers.append("적용 판단 파일의 구간이 다름: %r" % applicability.get("region_id"))
    if files is None:
        files = [{"role": r, "path": None, "sha256": _sha_obj(d)} for r, d in
                 zip(INPUT_ROLES, (region, graph, catalog, applicability, patterns, criteria)) if d is not None]
    return {"region": region, "graph": graph, "catalog": catalog, "applicability": applicability,
            "patterns": patterns, "criteria": criteria, "files": files, "blockers": blockers}


# ---------------------------------------------------------------- 구간 그래프 버전 재고정
def graph_source_of(graph):
    """그래프가 어떤 경로로 만들어졌는지. 등록 경로(run_samples.py)는 project_id가 있다."""
    return "registration" if graph.get("project_id") else "samples"


HOW_TO_BUILD = {
    "samples": "python scripts/extract_drawio.py --samples && python scripts/build_graph.py",
    "registration": "python scripts/run_samples.py (등록 -> 추출 -> 그래프)",
}


def rebind_graph(region_path, graph_path, repo_root, by, reason, confirm, now=utc_now):
    """구간 JSON의 graph_ref를 새 그래프 버전으로 바꾼다. confirm=False면 차이만 보여 준다.
    (보고 문장 목록, 변경 여부). 포함 대상 태그가 맞지 않거나 graph_id가 다르면 바꾸지 않는다."""
    with open(region_path, encoding="utf-8") as fh:
        region = json.load(fh)
    ref = region["graph_ref"]
    gpath = _resolve(graph_path or ref["graph_file"], repo_root)
    with open(gpath, encoding="utf-8") as fh:
        graph = json.load(fh)
    src = graph_source_of(graph)
    lines = ["구간 %s v%s" % (region["region_id"], region["region_version"]),
             "  graph_id: %s -> %s" % (ref["graph_id"], graph["graph_id"]),
             "  graph_version: %s -> %s" % (ref["graph_version"], graph["graph_version"]),
             "  graph_source: %s -> %s" % (ref.get("graph_source"), src),
             "  project_id: %r -> %r" % (region.get("project_id"), graph.get("project_id")),
             "  그래프 구조 검증: %s, 추출 실행: %s" % (graph["validation"]["status"], graph["source"].get("extraction_run_id"))]
    problems = _member_mismatches(region, graph)
    if graph["graph_id"] != ref["graph_id"]:
        problems.append("graph_id가 다름 — 다른 도면의 그래프로 바꾸지 않음")
    if graph["validation"]["status"] != "passed":
        problems.append("그래프 구조 검증이 passed가 아님")
    lines += ["  문제: " + p for p in problems] or ["  포함 대상 %d개 태그 일치" % len(region["members"])]
    if problems:
        return lines + ["변경하지 않음(문제 해결 후 다시 실행)"], False
    if graph["graph_version"] == ref["graph_version"] and graph.get("project_id") == region.get("project_id"):
        return lines + ["이미 같은 버전 — 변경 없음"], False
    if not confirm:
        return lines + ["확인 후 --confirm --by <이름> --reason <사유> 로 다시 실행하면 갱신함"], False
    if not by or not reason:
        return lines + ["--by와 --reason이 필요함 — 변경하지 않음"], False
    region.setdefault("graph_ref_history", []).append({
        "changed_at": now(), "changed_by": by, "reason": reason,
        "from": {"graph_version": ref["graph_version"], "graph_source": ref.get("graph_source"),
                 "project_id": region.get("project_id"), "region_version": region["region_version"]},
        "to": {"graph_version": graph["graph_version"], "graph_source": src, "project_id": graph.get("project_id"),
               "region_version": region["region_version"] + 1}})
    ref.update(graph_version=graph["graph_version"], graph_source=src, how_to_build=HOW_TO_BUILD[src],
               graph_file=paths.rel_or_abs(gpath, repo_root))
    region["project_id"] = graph.get("project_id")
    region["region_version"] += 1
    with open(region_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(region, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return lines + ["갱신함: region_version %d, 이력 기록" % region["region_version"]], True


# ---------------------------------------------------------------- 보류·자료 요청
class Holds:
    def __init__(self, items=None):
        self.items = items if items is not None else []

    def add(self, candidate_id, scope, item, reason, request, source, now):
        h = {"hold_id": "hold-%03d" % (len(self.items) + 1), "candidate_id": candidate_id, "scope": scope,
             "item": item, "reason": reason, "request": request, "source": source, "status": "open",
             "created_at": now}
        self.items.append(h)
        return h["hold_id"]

    def close(self, candidate_id, source, by, now):
        for h in self.items:
            if h["candidate_id"] == candidate_id and h["source"] == source and h["status"] == "open":
                h.update(status="closed", closed_by=by, closed_at=now)


# ---------------------------------------------------------------- 근거 묶음·보호수단
def _source_of(graph, obj):
    return {"graph_id": graph["graph_id"], "graph_version": graph["graph_version"],
            "drawing_number": graph["source"].get("drawing_number"),
            "extraction_run_id": graph["source"].get("extraction_run_id"),
            "local_id": obj.get("local_id"), "source_object_id": obj.get("source_object_id"),
            "bbox": obj.get("bbox")}


def _node_evidence(graph, n):
    return {"evidence_id": "ev-node-%s" % n["entity_id"], "type": "graph_node", "node_id": n["entity_id"],
            "node_type": n["node_type"], "kind": n["kind"], "category": n["category"], "tag": n.get("tag"),
            "label_text": n.get("label_text"), "attributes": n.get("attributes"),
            "flow_direction": n.get("flow_direction"), "knowledge_status": "confirmed",
            "source": _source_of(graph, n)}


def _relation_evidence(graph, e):
    return {"evidence_id": "ev-rel-%s" % e["entity_id"], "type": "graph_relation", "relation_id": e["entity_id"],
            "kind": e["kind"], "nodes": e["nodes"], "end": e.get("end"), "knowledge_status": "confirmed",
            "source": _source_of(graph, e)}


def signal_loop(q, node_ids):
    """node_ids와 signal_connection으로 이어진 대상 전체(제어루프 근사). 방향은 보지 않는다."""
    adj = q.adjacency("all")
    seen, stack = set(node_ids), list(node_ids)
    while stack:
        cur = stack.pop()
        for nb, eid in adj.get(cur, []):
            if q.edges[eid]["kind"] == SIGNAL and nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return seen


def _independence(nid, loop):
    if nid in loop:
        return "same_control_loop_as_cause", "원인과 같은 신호 연결(제어루프)에 속함 — 독립성 미확인, 보호수단 찾음으로 세지 않음"
    return "unknown", "독립성 미확인"


def scenario_safeguards(candidate_safeguards, cause_node_ids, q):
    """후보(편차)별 보호수단 후보에 시나리오 기준 독립성을 붙인다. 원인과 같은 제어루프 요소는 counts_as_found=False."""
    loop = signal_loop(q, cause_node_ids)
    out = []
    for g in candidate_safeguards:
        ind, note = _independence(g["node_id"], loop)
        out.append(dict(g, existence="confirmed_in_graph", adequacy="unknown", independence=ind,
                        counts_as_found=ind != "same_control_loop_as_cause", knowledge_status="unknown",
                        evidence_id="ev-path-%s" % g["node_id"], note="%s; %s" % (SAFEGUARD_NOTE, note)))
    return out


def build_bundle(cand, region, graph, exploration, matches, criteria, missing, q):
    query_nodes = {n["entity_id"]: n for n in graph["nodes"]}
    edges = {e["entity_id"]: e for e in graph["edges"]}
    node_ids = [exploration["start"]] + [r["entity_id"] for r in exploration["reached"]]
    rel_ids = set(exploration["cycle_or_merge_edges"])
    for r in exploration["reached"]:
        rel_ids.update(r["path_edges"])
    for m in matches["applied"]:
        rel_ids.update(m["relation_ids"])
    for g in matches["safeguards"]:
        rel_ids.update(g["chain_relation_ids"])
    evidence = [_node_evidence(graph, query_nodes[n]) for n in node_ids]
    evidence += [_relation_evidence(graph, edges[e]) for e in sorted(rel_ids)]
    for r in exploration["reached"]:
        evidence.append({"evidence_id": "ev-path-%s" % r["entity_id"], "type": "exploration_path",
                         "from": exploration["start"], "to": r["entity_id"], "node_ids": r["path_nodes"],
                         "relation_ids": r["path_edges"], "relation_kinds": r["path_edge_kinds"],
                         "direction_from_start": r["direction_from_start"], "segment_flow": r["segment_flow"],
                         "valves_on_path": r["valves_on_path"], "valve_state": r["valve_state"],
                         "normal_operation_flow": r["normal_operation_flow"], "outside_region": r["outside_region"],
                         "knowledge_status": "confirmed", "note": r["note"]})
    evidence.append({"evidence_id": "ev-design-intent", "type": "design_intent", "text": region["design_intent"]["text"],
                     "knowledge_status": region["design_intent"].get("knowledge_status"),
                     "basis": region["design_intent"].get("basis")})
    for i, c in enumerate(region.get("normal_operating_conditions") or [], 1):
        evidence.append(dict(c, evidence_id="ev-cond-%02d" % i, type="operating_condition"))
    cause_matches = [m for m in matches["applied"] if m["role"] == "cause"]
    equip = [n for n in node_ids if equipment.is_equipment(query_nodes[n])]
    return {
        "bundle_id": "bundle-%s" % cand["candidate_id"],
        "candidate": {k: cand.get(k) for k in ("candidate_id", "item_id", "parameter_ko", "guide_word_ko",
                                                "guide_word_en", "deviation", "deviation_en", "origin")},
        "region": {"region_id": region["region_id"], "region_version": region["region_version"],
                   "name": region.get("name"), "operating_mode": region["operating_mode"],
                   "focus_entities": region["focus_entities"], "boundaries": region.get("boundaries")},
        "exploration": {k: exploration[k] for k in ("exploration_id", "start", "settings", "truncations",
                                                     "boundary_crossings", "cycle_or_merge_edges",
                                                     "unreached_region_members", "limits_hit")},
        "evidence": evidence,
        "pattern_matches": {"library_id": matches["library_id"], "library_version": matches["library_version"],
                            "applied": matches["applied"], "not_applied": matches["not_applied"]},
        "candidate_safeguards": matches["safeguards"],
        "connection_only": matches["connection_only"],
        "kinds_without_patterns": matches["kinds_without_patterns"],
        "missing_information": missing,
        "risk_criteria": None if not criteria else {
            "criteria_id": criteria["criteria_id"], "criteria_version": criteria["criteria_version"],
            "severity_levels": criteria["severity_levels"], "frequency_levels": criteria["frequency_levels"]},
        "allowed_ids": {"node_ids": node_ids, "relation_ids": sorted(rel_ids),
                        "evidence_ids": [e["evidence_id"] for e in evidence],
                        "pattern_match_ids": [m["match_id"] for m in cause_matches],
                        "safeguard_node_ids": sorted(g["node_id"] for g in matches["safeguards"]),
                        "equipment_node_ids": equip},
    }


# ---------------------------------------------------------------- 실행
def prepare_doc(inputs, client, run_id=None, now=utc_now):
    """AI 단계 전까지: 후보 판단·탐색·패턴·근거 묶음·패턴 시나리오·보류."""
    if inputs["blockers"]:
        raise InputError("입력 차단 오류: " + " / ".join(inputs["blockers"]))
    t0 = now()
    region, graph, criteria = inputs["region"], inputs["graph"], inputs["criteria"]
    files_sha = _sha_text("|".join(f["sha256"] for f in inputs["files"]))
    run_id = run_id or "analysis-%s-%s" % (t0.replace("-", "").replace(":", ""), files_sha[:6])
    q = GraphQuery(graph)
    members = ex_mod.region_members(graph, [m["entity_id"] for m in region["members"]])
    run_ref = {"analysis_run_id": run_id,
               "graph_ref": {"graph_id": graph["graph_id"], "graph_version": graph["graph_version"]},
               "region_ref": {"region_id": region["region_id"], "region_version": region["region_version"]},
               "operating_mode": region["operating_mode"]}
    cands = cand_mod.build_candidates(inputs["catalog"], inputs["applicability"], region, run_ref, t0)
    focus = region["focus_entities"][0]
    xs = region["exploration"]
    exploration = ex_mod.explore(q, focus, members, xs["relation_kinds"], xs["max_depth"], xs["max_reached"],
                                 xs.get("boundary_extension_depth", 0))
    holds = Holds()
    run_missing = _run_level_holds(holds, region, graph, q, members, exploration, t0)
    empty_lib = {"library_id": inputs["patterns"]["library_id"], "library_version": inputs["patterns"]["library_version"],
                 "patterns": []}

    bundles, scenarios = {}, []
    for c in cands:
        c["analysis"] = {"ai_status": "not_requested", "ai_run_ids": [], "scenario_ids": [], "ai_facts": [],
                         "rejected_ai_scenarios": [], "warnings": []}
        if c["selection_status"] == "deferred":
            holds.add(c["candidate_id"], "후보 판단", "후보 판단 보류", c["reason"],
                      "근거 확인 후 선택·제외 판단(구간 JSON candidate_decisions)", "candidate", t0)
        if c["selection_status"] != "selected":
            continue
        matches = pat_mod.match_patterns(inputs["patterns"] if c["item_id"] else empty_lib, c["item_id"] or "",
                                         focus, exploration, q)
        missing = list(run_missing)
        for na in matches["not_applied"]:
            if na["status"] == "condition_unknown":
                missing.append({"item": "패턴 %s 적용 조건" % na["pattern_id"], "target": na["target"], "reason": na["detail"]})
                holds.add(c["candidate_id"], "패턴 %s @ %s" % (na["pattern_id"], na["tag"] or na["target"]),
                          "원인 패턴 적용 보류", na["detail"] + " — 값을 임의로 가정하지 않음",
                          "해당 속성(정상 위치·측정 변수 등)을 도면·자료에서 확인", "pattern", t0)
        bundle = build_bundle(c, region, graph, exploration, matches, criteria, missing, q)
        bundles[c["candidate_id"]] = bundle
        c["analysis"].update(exploration_id=exploration["exploration_id"], bundle_id=bundle["bundle_id"],
                             bundle_sha256=ai.bundle_sha256(bundle),
                             pattern_summary={"applied": len(matches["applied"]),
                                              "not_applied": len(matches["not_applied"]),
                                              "connection_only": len(matches["connection_only"]),
                                              "kinds_without_patterns": matches["kinds_without_patterns"]})
        reached_by_id = {r["entity_id"]: r for r in exploration["reached"] if r["node_type"] != "pipe_segment"}
        for m in matches["applied"]:
            if m["role"] == "cause":
                scenarios.append(_pattern_scenario(c, m, matches, reached_by_id, graph, q,
                                                   len(c["analysis"]["scenario_ids"]) + 1))
                c["analysis"]["scenario_ids"].append(scenarios[-1]["scenario_id"])

    return {
        "schema_version": SCHEMA_VERSION, "project_id": region.get("project_id"), "analysis_run_id": run_id,
        "graph_ref": run_ref["graph_ref"], "region_ref": run_ref["region_ref"],
        "operating_mode": region["operating_mode"],
        "analysis_run": {
            "analysis_run_id": run_id, "created_at": t0, "analyzer": {"name": ANALYZER, "version": ANALYZER_VERSION},
            "region": {k: region.get(k) for k in ("region_id", "region_version", "name", "operating_mode",
                                                  "design_intent", "focus_entities", "boundaries",
                                                  "normal_operating_conditions", "note")},
            "graph_source": region["graph_ref"].get("graph_source"),
            "region_members": sorted(members),
            "versions": {
                "candidate_catalog": {"id": inputs["catalog"]["catalog_id"], "version": inputs["catalog"]["catalog_version"]},
                "applicability": None if not inputs["applicability"] else {
                    "id": inputs["applicability"]["applicability_id"], "version": inputs["applicability"]["applicability_version"]},
                "patterns": {"id": inputs["patterns"]["library_id"], "version": inputs["patterns"]["library_version"],
                             "source": inputs["patterns"].get("source")},
                "risk_criteria": None if not criteria else {"id": criteria["criteria_id"],
                                                            "version": criteria["criteria_version"]},
                "judgment_rules": "HAZOP기법지침 §8.2 R1~R5",
                "design_improvement_rule": "도면 설비 시나리오의 제안 위험도가 표9 조건부 수용 이상, 또는 그래프에서 보호수단 미발견 "
                                           "(사용자 결정 2026-11-04)",
                "prompt_template": ai.template_info(),
                "graph_source": graph.get("source"), "graph_builder": graph.get("builder"),
            },
            "input_files": inputs["files"],
            "exploration_settings": exploration["settings"],
            "steps": {"input_check": "completed", "candidates": "completed", "exploration": "completed",
                      "patterns": "completed", "ai": "pending", "risk": "pending"},
            "ai_client": client.describe() if client else None,
        },
        "candidates": cands,
        "explorations": [exploration],
        "evidence_bundles": bundles,
        "scenarios": scenarios,
        "design_improvement_candidates": [],
        "holds": holds.items,
        "ai_runs": [],
    }


def analyze(inputs, client, run_id=None, now=utc_now, only=None):
    """저장 없이 전체 실행(테스트용). 저장하며 실행하려면 execute()."""
    doc = prepare_doc(inputs, client, run_id, now)
    try:
        run_ai_step(doc, inputs["graph"], inputs["criteria"], client, now=now, only=only)
    finally:
        finalize(doc, inputs["graph"], inputs["criteria"], now)
    return doc


def execute(inputs, client, out_root, run_id=None, now=utc_now, only=None):
    """AI 단계 전 결과를 먼저 저장하고, 후보마다 이어 저장한다. 예외·중단 시에도 그때까지의 결과를 남긴다."""
    doc = prepare_doc(inputs, client, run_id, now)
    finalize(doc, inputs["graph"], inputs["criteria"], now)
    run_dir = save(doc, inputs, out_root)
    path = os.path.join(run_dir, "analysis.json")
    try:
        run_ai_step(doc, inputs["graph"], inputs["criteria"], client, now=now, only=only,
                    progress=lambda: _write(path, doc))
    finally:
        finalize(doc, inputs["graph"], inputs["criteria"], now)
        _write(path, doc)
    return doc, run_dir


def _run_level_holds(holds, region, graph, q, members, exploration, now):
    """구간·그래프·탐색 수준의 미확인을 보류로 기록하고, 근거 묶음용 누락 정보 목록을 돌려준다."""
    missing = []

    def add(scope, item, reason, request, source):
        holds.add(None, scope, item, reason, request, source, now)
        missing.append({"item": item, "target": scope, "reason": reason})

    if region["design_intent"].get("knowledge_status") != "confirmed":
        add("구간 설계 의도", "설계 의도 미확정", region["design_intent"].get("basis") or "확인 상태 미확정",
            "사용자가 설계 의도를 확인·확정", "input")
    for c in region.get("normal_operating_conditions") or []:
        if c.get("knowledge_status") != "confirmed":
            add("운전조건", c["item"], c.get("reason") or "미확인", "운전조건·설계 사양 자료 등록", "input")
    for u in graph["validation"]["unknowns"]:
        if u.get("target") is None or u["target"] in members:
            add(u.get("target") or "그래프 전체", "%s 미확인" % u.get("field"), u["reason"],
                "① 자료 등록 연동 후 추출·그래프 재생성" if u.get("check") == "not_registered" else "원본·추출 확인", "graph")
    for nid in sorted(members):
        n = q.nodes[nid]
        if n["category"] == "valve" and n["attributes"].get("normal_position") is None:
            add(nid, "%s 정상 위치 미확인" % (n.get("tag") or nid),
                "밸브 정상 위치 없음 — 이 밸브를 지나는 경로는 정상 운전 유로 여부를 판단하지 않음(열림·닫힘 가정 금지)",
                "도면에서 정상 위치(NO·NC·LO·LC) 확인", "graph")
    for m in exploration["unreached_region_members"]:
        n = q.nodes[m]
        add(m, "%s 탐색 미도달" % (n.get("tag") or m), "구간에 포함되지만 중심 대상에서 지정 관계로 연결되지 않음",
            "도면 연결·추출 결과 확인(물리 연결 누락 여부)", "exploration")
    for t in exploration["truncations"]:
        if t["reason"] in ("max_depth", "max_reached"):
            add(t["at"], "탐색 한계 도달(%s)" % t["reason"], "탐색이 잘림 — 일부 대상 미탐색", "탐색 한계값 검토", "exploration")
    return missing


def _pattern_scenario(c, m, matches, reached_by_id, graph, q, seq):
    path = reached_by_id.get(m["target"])
    ev = ["ev-node-%s" % n for n in m["node_ids"]] + (["ev-path-%s" % m["target"]] if path else [])
    status, reason = "draft", None
    if path and path["valve_state"] == "position_unknown_on_path":
        status, reason = "deferred", "경로상 밸브 정상 위치 미확인 — 정상 운전 유로 여부 판단 보류"
    nodes = {n["entity_id"]: n for n in graph["nodes"]}
    return {
        "scenario_id": "scenario-%s-%02d" % (c["item_id"] or c["candidate_id"], seq),
        "candidate_id": c["candidate_id"], "origin": "pattern", "statement_type": "pattern_hypothesis",
        "scenario_status": status, "status_reason": reason, "knowledge_status": "hypothesis",
        "pattern_ref": {"pattern_id": m["pattern_id"], "pattern_version": m["pattern_version"],
                        "match_id": m["match_id"], "source": m["source"]},
        "cause": m["cause"], "consequence": m["consequence"],
        "cause_equipment": [m["target"]],
        "assumed_equipment": [n for n in m["node_ids"] if equipment.is_equipment(nodes[n])],
        "graph_evidence": {"node_ids": sorted(set(m["node_ids"] + (path["path_nodes"] if path else []))),
                           "relation_ids": sorted(set(m["relation_ids"] + (path["path_edges"] if path else []))),
                           "evidence_ids": ev},
        "path_context": None if not path else {k: path[k] for k in ("direction_from_start", "valve_state",
                                                                    "valves_on_path", "normal_operation_flow",
                                                                    "material_flow_path")},
        "source_locations": [_source_of(graph, nodes[n]) for n in m["node_ids"]],
        "safeguards": scenario_safeguards(matches["safeguards"], m["node_ids"], q),
        "ai_interpretation": None,
        "risk_proposal": risk_mod.deferred("AI 강도·빈도 제안 없음"),
        "review_status": "not_reviewed",
    }


def run_ai_step(doc, graph, criteria, client, now=utc_now, only=None, progress=None):
    """선택 후보 중 AI 검증을 통과하지 못한 것만 (다시) 실행한다. 이전 시도는 ai_runs에 남긴다.
    progress가 있으면 후보 하나를 마칠 때마다 호출한다(이어 저장)."""
    holds = Holds(doc["holds"])
    tinfo = ai.template_info()
    q = GraphQuery(graph)
    doc["analysis_run"]["steps"]["ai"] = "running"
    for c in doc["candidates"]:
        if c["selection_status"] != "selected" or c["analysis"]["ai_status"] == AI_DONE:
            continue
        if only and c["candidate_id"] not in only and c.get("item_id") not in only:
            if not c["analysis"]["ai_run_ids"] and not any(h["candidate_id"] == c["candidate_id"] and h["source"] == "ai"
                                                           for h in holds.items):
                holds.add(c["candidate_id"], "AI 해석", "AI 해석 미요청", "이번 실행에서 AI 대상(--only)에 포함되지 않음",
                          "AI 단계 재실행(resume)", "ai", now())
            continue
        if client is None:
            continue
        bundle = doc["evidence_bundles"][c["candidate_id"]]
        request = ai.build_request(bundle)
        attempt = len(c["analysis"]["ai_run_ids"]) + 1
        started = now()
        try:
            res = client.infer(request)
        except Exception as exc:  # SDK·파일 등 예상 밖 예외: 이 후보만 실패로 기록하고 계속
            res = {"status": "client_error", "error_type": type(exc).__name__, "error": str(exc)}
        finished = now()
        record = {"ai_run_id": "airun-%s-%02d" % (c["candidate_id"], attempt), "candidate_id": c["candidate_id"],
                  "attempt": attempt, "started_at": started, "finished_at": finished, "client": client.describe(),
                  "template": tinfo, "bundle_id": bundle["bundle_id"], "bundle_sha256": request["bundle_sha256"],
                  "request": {"user_sha256": request["user_sha256"], "params": _request_params(client, request)},
                  "result": {k: v for k, v in res.items() if k != "output"},
                  "response": res.get("output"),
                  "validation": None}
        status = res["status"]
        rejected = []
        if status == "completed":
            errors, warnings, rejected = validate.validate_response(res["output"], bundle, graph, ai.RESPONSE_SCHEMA)
            status = AI_DONE if not errors else "validation_failed"
            record["validation"] = {"status": "passed" if not errors else "failed", "errors": errors,
                                    "warnings": warnings, "rejected_scenarios": rejected}
        requested, resp_model = (client.describe() or {}).get("model"), res.get("response_model")
        record["requested_model"], record["response_model"] = requested, resp_model
        record["model_mismatch"] = bool(requested and resp_model and resp_model != requested)
        c["analysis"].setdefault("warnings", [])
        if record["model_mismatch"]:
            c["analysis"]["warnings"].append({
                "type": "model_mismatch", "ai_run_id": record["ai_run_id"], "requested_model": requested,
                "response_model": resp_model, "detail": "요청 모델과 다름(서버측 fallback 등) — 결과 해석 시 확인 필요"})
        if status == AI_DONE:
            snapshot = copy.deepcopy({"scenarios": doc["scenarios"], "holds": doc["holds"], "analysis": c["analysis"]})
            try:
                _merge_ai(doc, c, res["output"], bundle, criteria, record, holds, finished, q,
                          {r["index"] for r in rejected})
                c["analysis"]["rejected_ai_scenarios"] = [dict(r, ai_run_id=record["ai_run_id"]) for r in rejected]
            except Exception as exc:  # 병합 실패: 병합 전 상태로 되돌리고 검증 통과로 기록하지 않음
                doc["scenarios"][:] = snapshot["scenarios"]
                doc["holds"][:] = snapshot["holds"]
                c["analysis"] = snapshot["analysis"]
                status = "merge_error"
                record["merge_error"] = "%s: %s" % (type(exc).__name__, exc)
        record["status"] = status
        doc["ai_runs"].append(record)
        c["analysis"]["ai_run_ids"].append(record["ai_run_id"])
        c["analysis"]["ai_status"] = status
        holds.close(c["candidate_id"], "ai", record["ai_run_id"], finished)
        if status != AI_DONE:
            detail = record.get("merge_error") or res.get("error") or ""
            if record["validation"] and record["validation"]["errors"]:
                detail = "; ".join("%s %s: %s" % (e["type"], e["path"], e["detail"]) for e in record["validation"]["errors"][:5])
            holds.add(c["candidate_id"], "AI 해석", "AI 해석 없음(%s)" % status,
                      "%s — 패턴 기반 초안·탐색 결과는 보존, 위험도 미제안" % detail,
                      "AI 단계 재시도(resume) 또는 고정 응답 보완", "ai", finished)
        if progress:
            progress()
    statuses = [c["analysis"]["ai_status"] for c in doc["candidates"] if c["selection_status"] == "selected"]
    doc["analysis_run"]["steps"]["ai"] = ("completed" if statuses and all(s == AI_DONE for s in statuses)
                                         else "partial" if any(s == AI_DONE for s in statuses) else "not_completed")


def _request_params(client, request):
    if hasattr(client, "build_params"):
        p = copy.deepcopy(client.build_params(request))
        p["system"] = {"sha256": _sha_text(p["system"]), "template_id": ai.TEMPLATE_ID}
        p["messages"] = [{"role": m["role"], "content_sha256": _sha_text(m["content"])} for m in p["messages"]]
        p["output_config"]["format"]["schema"] = {"sha256": _sha_obj(request["schema"]), "ref": "hazop.analysis.ai.RESPONSE_SCHEMA"}
        return p
    return {"note": "고정 응답 클라이언트 — API 요청 없음", "user_sha256": request["user_sha256"]}


NARRATIVE_CHECK = {"method": "구조 검증(ID·기기 종류) + AI 자기 신고(outside_graph_equipment)",
                   "limit": "서술 문장 속 설비명은 자동 대조하지 않음 — AI가 신고하지 않은 도면 밖 설비 서술은 사람이 검토"}


def _merge_ai(doc, c, out, bundle, criteria, record, holds, now, q, rejected_idx):
    ai_run_id = record["ai_run_id"]
    c["analysis"]["ai_facts"] = [dict(f, statement_type="fact", references_verified=True, content_verified=False,
                                      ai_run_id=ai_run_id) for f in out["facts"]]
    by_match = {s["pattern_ref"]["match_id"]: s for s in doc["scenarios"]
                if s["candidate_id"] == c["candidate_id"] and s["pattern_ref"]}
    cand_safe = {g["node_id"]: g for g in bundle["candidate_safeguards"]}
    safeguard_status = {n: {"adequacy": "unknown", "existence": "confirmed_in_graph"} for n in cand_safe}
    interpreted = set()
    for i, s in enumerate(out["scenarios"]):
        if i in rejected_idx:
            continue
        premise = list(dict.fromkeys(s["cause_entity_ids"] + s["assumed_equipment"]))
        recognized = [dict(cand_safe[g["node_id"]], description=g["description"])
                      for g in s["safeguards"] if g["node_id"] in cand_safe]
        excluded = [dict(g, reason="이 후보의 보호수단 후보 목록 밖 — 인정하지 않음")
                    for g in s["safeguards"] if g["node_id"] not in cand_safe]
        ai_safeguards = scenario_safeguards(recognized, premise, q)
        interp = {"cause": s["cause"], "consequence": s["consequence"], "interpretation": s["interpretation"],
                  "cause_entity_ids": s["cause_entity_ids"], "assumed_equipment": s["assumed_equipment"],
                  "node_ids": s["node_ids"], "relation_ids": s["relation_ids"], "evidence_ids": s["evidence_ids"],
                  "safeguards": ai_safeguards, "excluded_safeguards": excluded, "ai_risk_input": s["risk"],
                  "ai_run_id": ai_run_id, "response_model": record.get("response_model"),
                  "statement_type": "interpretation" if s["basis"] == "pattern" else "additional_hypothesis",
                  "references_verified": True, "narrative_check": NARRATIVE_CHECK}
        proposal = risk_mod.evaluate(criteria, s["risk"], safeguard_status)
        if s["basis"] == "pattern":
            sc = by_match[s["pattern_match_id"]]
            sc["ai_interpretation"] = interp
            interpreted.add(s["pattern_match_id"])
        else:
            seq = len(c["analysis"]["scenario_ids"]) + 1
            sc = {"scenario_id": "scenario-%s-%02d" % (c["item_id"] or c["candidate_id"], seq),
                  "candidate_id": c["candidate_id"], "origin": "ai_additional_hypothesis",
                  "statement_type": "additional_hypothesis", "scenario_status": "draft", "status_reason": None,
                  "knowledge_status": "hypothesis", "pattern_ref": None,
                  "cause": s["cause"], "consequence": s["consequence"], "cause_equipment": s["cause_entity_ids"],
                  "assumed_equipment": s["assumed_equipment"],
                  "graph_evidence": {"node_ids": sorted(set(s["node_ids"] + premise)),
                                     "relation_ids": s["relation_ids"], "evidence_ids": s["evidence_ids"]},
                  "path_context": None, "source_locations": [],
                  "safeguards": ai_safeguards, "ai_interpretation": interp, "registered_as_graph_fact": False,
                  "review_status": "not_reviewed"}
            doc["scenarios"].append(sc)
            c["analysis"]["scenario_ids"].append(sc["scenario_id"])
        sc["risk_proposal"] = proposal
        if proposal["status"] == "deferred":
            holds.add(c["candidate_id"], sc["scenario_id"], "위험도 제안 보류", proposal["reason"],
                      "강도·빈도 판단 근거(운전조건·결과 범위·기준표) 확인", "risk", now)
    for match_id, sc in sorted(by_match.items()):
        if match_id not in interpreted:
            holds.add(c["candidate_id"], sc["scenario_id"], "위험도 제안 보류", "AI가 이 패턴 시나리오를 해석하지 않음",
                      "AI 재해석 또는 사람 검토", "risk", now)
    for m in out["missing_information"]:
        holds.add(c["candidate_id"], m["item"], "AI 자료 요청: %s" % m["item"], m["reason"], m["request"], "ai_request", now)


def doc_graph_nodes(bundle):
    return [{"entity_id": e["node_id"], "tag": e.get("tag")} for e in bundle["evidence"] if e["type"] == "graph_node"]


# ---------------------------------------------------------------- 설계보완 후보
def design_improvement_candidates(doc, criteria, holds, now):
    """도면 설비 기반 시나리오(scenario_status=draft)에서 (1) 제안 위험도가 표9 조건부 수용 이상이거나
    (2) 그래프에서 (원인과 독립일 수 있는) 보호수단을 하나도 찾지 못한 경우 후보로 만든다.
    원인과 같은 제어루프 요소는 '찾음'으로 세지 않는다. 상태는 candidate(⑤에서 사람이 확정).
    (2)는 보호수단이 '없다'고 단정하지 않으며 같은 시나리오에 보호수단 존재 확인 자료 요청을 남긴다.
    ID는 시나리오 ID 기반(dic-<scenario_id>)이라 재실행·resume에도 같다."""
    out = []
    for s in doc["scenarios"]:
        if s["scenario_status"] != "draft":
            continue
        triggers, basis = [], {}
        rp = s["risk_proposal"]
        if rp["status"] == "proposed" and criteria:
            level = criteria["risk_levels"][str(rp["risk"])]
            if level["acceptance"] != ACCEPTED:
                triggers.append("risk_conditional_or_worse")
                basis.update(risk=rp["risk"], risk_name=level["name"], acceptance=level["acceptance"],
                             criteria_id=criteria["criteria_id"], criteria_version=criteria["criteria_version"],
                             calculation=rp["calculation"])
        allg = s["safeguards"] + ((s.get("ai_interpretation") or {}).get("safeguards") or [])
        found = sorted({g["node_id"] for g in allg if g.get("counts_as_found", True)})
        same_loop = sorted({g["node_id"] for g in allg if not g.get("counts_as_found", True)})
        hold_ids = []
        if not found:
            triggers.append("no_safeguard_found_in_graph")
            basis.update(safeguards_found_in_graph=0, same_control_loop_not_counted=same_loop,
                         safeguard_note="그래프(도면)에서 원인과 독립일 수 있는 보호수단을 찾지 못함 — "
                                        "보호수단이 없다고 단정하지 않음(미확인)")
            existing = [h["hold_id"] for h in holds.items if h["source"] == "design_improvement"
                        and h["scope"] == s["scenario_id"] and h["status"] == "open"]
            hold_ids = existing or [holds.add(s["candidate_id"], s["scenario_id"], "보호수단 존재 확인",
                                              "그래프에서 이 시나리오의 보호수단을 찾지 못함(없음인지 미확인인지 판단 불가)",
                                              "경보·인터록·안전밸브 등 보호수단 자료와 도면 확인", "design_improvement", now)]
        if not triggers:
            continue
        out.append({"dic_id": "dic-%s" % s["scenario_id"], "scenario_id": s["scenario_id"],
                    "candidate_id": s["candidate_id"], "triggers": triggers, "basis": basis,
                    "cause": s["cause"], "consequence": s["consequence"], "equipment": s.get("cause_equipment") or [],
                    "rule": doc["analysis_run"]["versions"]["design_improvement_rule"],
                    "status": "candidate", "confirmed": False, "hold_ids": hold_ids,
                    "note": "설계보완 후보(미확정). ⑤에서 사람이 확정하며 자동 확정하지 않음"})
    return out


def _close_resolved_holds(doc, now):
    """조건이 해소된 보류를 닫는다: 보호수단을 찾게 된 시나리오의 존재 확인 요청, 위험도가 제안된 시나리오의 위험도 보류."""
    no_safe = {d["scenario_id"] for d in doc["design_improvement_candidates"]
               if "no_safeguard_found_in_graph" in d["triggers"]}
    proposed = {s["scenario_id"] for s in doc["scenarios"] if s["risk_proposal"]["status"] == "proposed"}
    for h in doc["holds"]:
        if h["status"] != "open":
            continue
        resolved = (h["source"] == "design_improvement" and h["scope"] not in no_safe) or \
            (h["source"] == "risk" and h["scope"] in proposed)
        if resolved:
            h.update(status="closed", closed_by="condition_resolved", closed_at=now)


def finalize(doc, graph, criteria, now=utc_now):
    t = now()
    if doc["analysis_run"]["steps"]["ai"] == "running":
        doc["analysis_run"]["steps"]["ai"] = "interrupted"
    doc["analysis_run"]["steps"]["risk"] = "completed" if criteria else "deferred_no_criteria"
    doc["analysis_run"]["drawing_only_check"] = NARRATIVE_CHECK
    doc["design_improvement_candidates"] = design_improvement_candidates(doc, criteria, Holds(doc["holds"]), t)
    _close_resolved_holds(doc, t)
    doc["validation"] = check_result(doc, graph, criteria)


# ---------------------------------------------------------------- 결과 검증
def check_result(doc, graph, criteria):
    errors = []
    g_nodes = {n["entity_id"]: n for n in graph["nodes"]}
    g_rels = {e["entity_id"] for e in graph["edges"]}
    for c in doc["candidates"]:
        if c["selection_status"] not in cand_mod.SELECTION or not c["judgments"] or not c.get("reason"):
            errors.append("후보 판단 상태·이유 없음: %s" % c["candidate_id"])
        if c["selection_status"] == "excluded" and (c.get("risk_proposal") or {}).get("status") != "not_applicable":
            errors.append("제외 후보의 위험도 not_applicable·사유 없음: %s" % c["candidate_id"])
    for s in doc["scenarios"]:
        ge = s["graph_evidence"]
        bad = [n for n in ge["node_ids"] if n not in g_nodes] + [r for r in ge["relation_ids"] if r not in g_rels]
        if bad:
            errors.append("시나리오 참조 오류 %s: %s" % (s["scenario_id"], bad))
        if s["scenario_status"] not in SCENARIO_STATUS:
            errors.append("scenario_status 값 오류: %s" % s["scenario_id"])
        eq = s.get("cause_equipment") or []
        if not eq or any(not equipment.is_equipment(g_nodes.get(n, {})) for n in eq):
            errors.append("도면 설비 기반이 아닌 시나리오: %s" % s["scenario_id"])
        ev = set(doc["evidence_bundles"][s["candidate_id"]]["allowed_ids"]["evidence_ids"])
        if any(e not in ev for e in ge["evidence_ids"]):
            errors.append("시나리오 근거 ID 오류: %s" % s["scenario_id"])
        rp = s["risk_proposal"]
        if rp["status"] == "proposed":
            if not criteria or rp["risk"] != risk_mod.lookup(criteria, rp["severity"], rp["frequency_used"]):
                errors.append("위험도 계산 불일치: %s" % s["scenario_id"])
            if rp["safeguard_credit_applied"]:
                errors.append("확인되지 않은 보호수단으로 빈도 감소 반영: %s" % s["scenario_id"])
        elif rp.get("risk") is not None:
            errors.append("보류된 위험도에 등급 값 있음: %s" % s["scenario_id"])
    for d in doc["design_improvement_candidates"]:
        if d["status"] != "candidate" or d["confirmed"] is not False:
            errors.append("설계보완 후보가 자동 확정됨: %s" % d["dic_id"])
        if "no_safeguard_found_in_graph" in d["triggers"] and not d["hold_ids"]:
            errors.append("보호수단 미발견 설계보완 후보에 자료 요청 없음: %s" % d["dic_id"])
    for h in doc["holds"]:
        if not h.get("reason") or not h.get("request"):
            errors.append("보류 사유·요청 없음: %s" % h["hold_id"])
    counts = {"candidates": len(doc["candidates"])}
    for st in cand_mod.SELECTION:
        counts[st] = sum(c["selection_status"] == st for c in doc["candidates"])
    counts.update(scenarios=len(doc["scenarios"]),
                  risk_proposed=sum(s["risk_proposal"]["status"] == "proposed" for s in doc["scenarios"]),
                  design_improvement_candidates=len(doc["design_improvement_candidates"]),
                  ai_rejected_scenarios=sum(len(c["analysis"]["rejected_ai_scenarios"]) for c in doc["candidates"]),
                  holds_open=sum(h["status"] == "open" for h in doc["holds"]),
                  ai_validated=sum(c["analysis"]["ai_status"] == AI_DONE for c in doc["candidates"]),
                  ai_failed=sum(c["analysis"]["ai_status"] not in (AI_DONE, "not_requested")
                                for c in doc["candidates"]))
    return {"status": "passed" if not errors else "blocked", "errors": errors, "counts": counts,
            "note": "passed는 형식·참조 검증 통과이며 보류 항목이 없다는 뜻이 아님"}


# ---------------------------------------------------------------- 저장·재시도
def save(doc, inputs, out_root):
    run_dir = paths.safe_join(paths.safe_join(out_root, paths.safe_name(doc["region_ref"]["region_id"])),
                              paths.safe_name(doc["analysis_run_id"]))
    if os.path.exists(os.path.join(run_dir, "analysis.json")):
        raise InputError("같은 실행 ID의 결과가 이미 있음(덮어쓰지 않음): %s" % run_dir)
    os.makedirs(os.path.join(run_dir, "inputs"), exist_ok=True)
    for role, text in (inputs.get("raw") or {}).items():
        with open(os.path.join(run_dir, "inputs", role + ".json"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    _write(os.path.join(run_dir, "analysis.json"), doc)
    return run_dir


def _write(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def recorded_ai_mode(run_dir):
    with open(os.path.join(run_dir, "analysis.json"), encoding="utf-8") as fh:
        return json.load(fh)["analysis_run"].get("ai_client") or {}


def check_same_mode(recorded, current):
    """resume는 원래 실행의 AI 모드(고정 응답/실제 API)와 같아야 한다."""
    keys = ("type", "response_dir", "verify_bundle") if recorded.get("type") == "fixed_response" else ("type", "model")
    diff = ["%s: 기록 %r, 이번 %r" % (k, recorded.get(k), current.get(k)) for k in keys if recorded.get(k) != current.get(k)]
    if diff:
        raise InputError("원래 실행과 AI 모드가 다름 — 재시도 거부: " + "; ".join(diff))


def resume(run_dir, client, now=utc_now, only=None):
    """저장된 실행의 AI 단계부터 다시 실행한다. 입력 사본 해시와 AI 모드가 기록과 같아야 한다.
    이전 analysis.json은 history/에 보관하고, 후보마다 이어 저장한다."""
    path = os.path.join(run_dir, "analysis.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    check_same_mode(doc["analysis_run"].get("ai_client") or {}, client.describe())
    docs = {}
    for f in doc["analysis_run"]["input_files"]:
        p = os.path.join(run_dir, "inputs", f["role"] + ".json")
        if not os.path.isfile(p):
            raise InputError("입력 사본 없음(%s) — 재시도 불가" % f["role"])
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        if _sha_text(text) != f["sha256"]:
            raise InputError("입력 사본 해시 불일치(%s) — 재시도 불가" % f["role"])
        docs[f["role"]] = json.loads(text)
    hist = os.path.join(run_dir, "history")
    os.makedirs(hist, exist_ok=True)
    n = len([x for x in os.listdir(hist) if x.endswith(".json")]) + 1
    _write(os.path.join(hist, "analysis-%03d.json" % n), doc)
    doc["analysis_run"].setdefault("resumed_at", []).append(now())
    try:
        run_ai_step(doc, docs["graph"], docs.get("risk_criteria"), client, now=now, only=only,
                    progress=lambda: _write(path, doc))
    finally:
        finalize(doc, docs["graph"], docs.get("risk_criteria"), now)
        _write(path, doc)
    return doc
