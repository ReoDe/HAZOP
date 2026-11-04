"""④ AI 응답 검증. 검증을 통과하지 못한 응답은 결과에 반영하지 않는다(검증된 근거로 통과 금지).

1) 형식: ai.RESPONSE_SCHEMA의 부분집합(type, enum, anyOf, properties, required, additionalProperties, items)
2) 참조: 인용한 노드·관계·근거·패턴 적용 ID가 그래프와 근거 묶음에 실제 있는지
3) 구분: pattern 시나리오는 적용된 cause 패턴을, 추가 가설은 패턴 없이(null)
4) 위험도: 허용값, 빈도 감소 방향, 인정 보호수단이 시나리오 보호수단에 있는지
5) 도면 설비 한정(사용자 결정 2026-11-04) — 시나리오 단위 거부(rejected, 사유 기록):
   - cause_entity_ids가 비었거나, cause_entity_ids·assumed_equipment에 실제 기기가 아닌 대상(연결 요소·배관 구간,
     다른 도면 연결점 continuation = 도면 밖)이 있으면 거부(허용 종류: hazop.analysis.equipment)
   - AI가 서술 속 그래프 밖 설비명을 자기 신고(outside_graph_equipment)하면 거부
   한계: 문장 속 설비명을 자동 대조하지는 않는다. 구조 검증(ID·종류)과 AI 자기 신고의 2중 확인이며,
   AI가 신고하지 않은 서술 속 설비는 사람이 검토해야 한다(결과의 narrative_check에 표시).
6) 보호수단: 후보의 보호수단 후보 목록(allowed_ids.safeguard_node_ids) 밖이면 인정하지 않고 경고로 남긴다.
"""

from . import equipment

_TYPES = {"object": dict, "array": list, "string": str, "null": type(None)}


def check_schema(value, schema, path="$"):
    errors = []
    if "anyOf" in schema:
        if all(check_schema(value, s, path) for s in schema["anyOf"]):
            errors.append({"type": "schema_error", "path": path, "detail": "anyOf 중 맞는 형식 없음"})
        return errors
    t = schema.get("type")
    if t == "integer":
        ok = type(value) is int
    elif t == "boolean":
        ok = type(value) is bool
    elif t:
        ok = isinstance(value, _TYPES[t])
    else:
        ok = True
    if not ok:
        return [{"type": "schema_error", "path": path, "detail": "형식 %s 아님" % t}]
    if "enum" in schema and value not in schema["enum"]:
        errors.append({"type": "schema_error", "path": path, "detail": "허용값 아님: %r" % (value,)})
    if t == "object":
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errors.append({"type": "schema_error", "path": "%s.%s" % (path, k), "detail": "필수 필드 없음"})
        for k, v in value.items():
            if k in props:
                errors += check_schema(v, props[k], "%s.%s" % (path, k))
            elif schema.get("additionalProperties") is False:
                errors.append({"type": "schema_error", "path": "%s.%s" % (path, k), "detail": "정의되지 않은 필드"})
    if t == "array" and "items" in schema:
        for i, v in enumerate(value):
            errors += check_schema(v, schema["items"], "%s[%d]" % (path, i))
    return errors


def _ref_errors(ids, allowed, graph_ids, kind, path):
    errs = []
    for x in ids:
        if x in allowed:
            continue
        where = "그래프에 없음" if x not in graph_ids else "그래프에는 있으나 근거 묶음 밖"
        errs.append({"type": "reference_error", "path": path, "detail": "%s %r: %s" % (kind, x, where)})
    return errs


def validate_response(output, bundle, graph, schema):
    """(오류 목록, 경고 목록, 거부 시나리오 목록). 오류가 없어야 통과. 거부 시나리오는 결과에 넣지 않는다."""
    errors, warnings, rejected = check_schema(output, schema), [], []
    if errors:
        return errors, warnings, rejected
    allowed = bundle["allowed_ids"]
    a_nodes, a_rels = set(allowed["node_ids"]), set(allowed["relation_ids"])
    a_ev, a_match = set(allowed["evidence_ids"]), set(allowed["pattern_match_ids"])
    a_safe = set(allowed["safeguard_node_ids"])
    g_nodes = {n["entity_id"]: n for n in graph["nodes"]}
    g_rels = {e["entity_id"] for e in graph["edges"]}
    if output["candidate_id"] != bundle["candidate"]["candidate_id"]:
        errors.append({"type": "reference_error", "path": "$.candidate_id",
                       "detail": "요청 후보와 다름: %r" % output["candidate_id"]})
    for i, f in enumerate(output["facts"]):
        p = "$.facts[%d]" % i
        if not f["evidence_ids"]:
            errors.append({"type": "value_error", "path": p, "detail": "사실에 근거 ID 없음"})
        errors += _ref_errors(f["evidence_ids"], a_ev, a_ev, "근거", p + ".evidence_ids")
        errors += _ref_errors(f["node_ids"], a_nodes, g_nodes, "노드", p + ".node_ids")
        errors += _ref_errors(f["relation_ids"], a_rels, g_rels, "관계", p + ".relation_ids")
    used_matches = set()
    for i, s in enumerate(output["scenarios"]):
        p = "$.scenarios[%d]" % i
        if s["basis"] == "pattern":
            if s["pattern_match_id"] not in a_match:
                errors.append({"type": "reference_error", "path": p + ".pattern_match_id",
                               "detail": "적용된 cause 패턴이 아님: %r" % s["pattern_match_id"]})
            elif s["pattern_match_id"] in used_matches:
                errors.append({"type": "value_error", "path": p + ".pattern_match_id",
                               "detail": "같은 패턴 적용을 두 번 해석함: %r" % s["pattern_match_id"]})
            used_matches.add(s["pattern_match_id"])
        elif s["pattern_match_id"] is not None:
            errors.append({"type": "value_error", "path": p + ".pattern_match_id",
                           "detail": "추가 가설은 패턴 ID를 가질 수 없음"})
        errors += _ref_errors(s["node_ids"], a_nodes, g_nodes, "노드", p + ".node_ids")
        errors += _ref_errors(s["relation_ids"], a_rels, g_rels, "관계", p + ".relation_ids")
        errors += _ref_errors(s["evidence_ids"], a_ev, a_ev, "근거", p + ".evidence_ids")
        safe_ids = [g["node_id"] for g in s["safeguards"]]
        errors += _ref_errors(safe_ids, a_nodes, g_nodes, "보호수단 노드", p + ".safeguards")
        errors += _ref_errors(s["assumed_equipment"], a_nodes, g_nodes, "전제 설비", p + ".assumed_equipment")
        errors += _ref_errors(s["cause_entity_ids"], a_nodes, g_nodes, "원인 설비", p + ".cause_entity_ids")
        for x in safe_ids:
            if x not in a_safe:
                warnings.append({"type": "safeguard_not_recognized", "path": p + ".safeguards", "node_id": x,
                                 "detail": "이 후보의 보호수단 후보 목록 밖 — 인정하지 않음"})
        reasons = []
        if s["outside_graph_equipment"]:
            reasons.append("서술에 도면에 없는 설비(AI 자기 신고: %s)" % ", ".join(s["outside_graph_equipment"]))
        if not s["cause_entity_ids"]:
            reasons.append("원인 설비 entity_id(cause_entity_ids) 없음 — 도면 설비 기반임을 확인할 수 없음")
        for x in s["cause_entity_ids"] + s["assumed_equipment"]:
            if x in g_nodes:
                why = equipment.why_not_equipment(g_nodes[x])
                if why:
                    reasons.append("%s: %s" % (x, why))
        if reasons:
            rejected.append({"index": i, "cause": s["cause"],
                             "reason": "도면에 없는 설비 전제 또는 도면 설비 확인 불가 — " + "; ".join(reasons)
                             + " (사용자 결정 2026-11-04)"})
        r = s["risk"]
        credited = r["credited_safeguard_node_ids"]
        errors += _ref_errors(credited, a_safe & set(safe_ids), g_nodes, "인정 보호수단", p + ".risk.credited_safeguard_node_ids")
        f0, f1 = r["frequency_without_safeguards"], r["frequency_with_safeguards"]
        if f0 is not None and f1 is not None and f1 > f0:
            errors.append({"type": "value_error", "path": p + ".risk",
                           "detail": "보호수단 반영 빈도(%d)가 미반영 빈도(%d)보다 큼" % (f1, f0)})
        if bundle.get("risk_criteria") is None and (r["severity"] is not None or f0 is not None or f1 is not None):
            warnings.append({"type": "risk_without_criteria", "path": p + ".risk",
                             "detail": "기준표 없음인데 강도·빈도 값을 제안함 — 값을 쓰지 않고 위험도 보류"})
    return errors, warnings, rejected
