"""④ 편차 후보와 판단 이력 (기획서/HAZOP분석.md '편차 후보와 검토 기록', HAZOP기법지침.md §8.2 R1~R5).

카탈로그 44개 전부를 후보로 두고 규칙으로 첫 판단을 기록한다. 사람의 판단(구간 JSON candidate_decisions)과
수동 추가 후보(manual_candidates)는 별도 판단 이력으로 덧붙인다. 이전 판단은 지우지 않는다.
"""

SELECTION = ("selected", "excluded", "deferred")
PROCEDURE_MODES = ("startup", "shutdown", "maintenance")


class CandidateInputError(ValueError):
    pass


def rule_judgment(item, app, mode):
    """(rule, selection_status, reason, basis). app이 None이면 판단 근거 없음."""
    if item.get("batch_specific") and mode in PROCEDURE_MODES:
        return "R2", "deferred", "절차 기반 모드에서 시간·시퀀스 재검토 필요", "HAZOP기법지침 §8.2 R2"
    if app is None or not app.get("applicability"):
        return "R5", "deferred", "적용 판단 근거 없음 — 제외하지 않고 보류", "HAZOP기법지침 §8.2 R5"
    a = app["applicability"]
    if a == "not_applicable":
        if app.get("applicability_knowledge_status") not in ("confirmed", "hypothesis"):
            return "R5", "deferred", "적용 불가 판단의 확인 상태가 미확인(%r) — 사유가 있어도 제외하지 않고 보류"                 % app.get("applicability_knowledge_status"), "HAZOP기법지침 §8.2 R5"
        if mode != "normal" or not app.get("applicability_reason") or not app.get("applicability_basis"):
            return "R5", "deferred", "적용 불가 사유·근거 또는 운전모드 조건 불충분 — 보류", "HAZOP기법지침 §8.2 R5"
        return "R1", "excluded", app["applicability_reason"], app["applicability_basis"]
    if a == "needs_review":
        return "R3", "deferred", "검토 필요 — 사람이 근거 확인 후 판단", "HAZOP기법지침 §8.2 R3"
    if a == "applicable":
        return "R4", "selected", "적용 후보(기본 선택)", app.get("applicability_basis") or "HAZOP기법지침 §8.2 R4"
    return "R5", "deferred", "알 수 없는 applicability 값 %r — 보류" % a, "HAZOP기법지침 §8.2 R5"


def build_candidates(catalog, applicability, region, run_ref, now):
    mode = region["operating_mode"]
    app_by_id = {}
    if applicability and applicability.get("region_id") == region["region_id"]:
        app_by_id = {a["item_id"]: a for a in applicability["items"]}
    out = []
    for item in catalog["items"]:
        app = app_by_id.get(item["item_id"])
        rule, status, reason, basis = rule_judgment(item, app, mode)
        cand = {
            "candidate_id": "deviation-%s" % item["item_id"], "item_id": item["item_id"],
            "region_id": region["region_id"], "origin": "catalog",
            "parameter_ko": item["parameter_ko"], "guide_word_ko": item["guide_word_ko"],
            "guide_word_en": item["guide_word_en"], "deviation": item["deviation_ko"],
            "deviation_en": item["deviation_en"], "batch_specific": item["batch_specific"],
            "generation_basis": {"catalog_id": catalog["catalog_id"], "catalog_version": catalog["catalog_version"],
                                 "applicability_id": applicability.get("applicability_id") if applicability else None,
                                 "applicability_version": applicability.get("applicability_version") if applicability else None,
                                 "applicability": app.get("applicability") if app else None,
                                 "applicability_knowledge_status": app.get("applicability_knowledge_status") if app else None,
                                 "generated": "auto"},
            "applied_versions": run_ref,
            "judgments": [{"seq": 1, "selection_status": status, "decided_by": "rule:%s" % rule,
                           "decided_at": now, "reason": reason, "basis": basis}],
        }
        out.append(cand)
    for i, m in enumerate(region.get("manual_candidates") or [], 1):
        for k in ("parameter_ko", "guide_word_ko", "deviation", "added_by", "reason"):
            if not m.get(k):
                raise CandidateInputError("manual_candidates[%d]: %s 필요" % (i - 1, k))
        status = m.get("selection_status")
        if status is None:
            status, reason = "deferred", "판단 미입력 — 보류(R5)"
        elif status not in SELECTION:
            raise CandidateInputError("manual_candidates[%d]: selection_status 값 %r" % (i - 1, status))
        else:
            reason = m["reason"]
        out.append({
            "candidate_id": "deviation-manual-%03d" % i, "item_id": None, "region_id": region["region_id"],
            "origin": "manual", "parameter_ko": m["parameter_ko"], "guide_word_ko": m["guide_word_ko"],
            "guide_word_en": m.get("guide_word_en"), "deviation": m["deviation"], "deviation_en": None,
            "batch_specific": None, "description": m.get("description"),
            "generation_basis": {"generated": "manual", "added_by": m["added_by"], "added_at": m.get("added_at"),
                                 "reason": m["reason"]},
            "applied_versions": run_ref,
            "judgments": [{"seq": 1, "selection_status": status, "decided_by": m["added_by"],
                           "decided_at": m.get("added_at") or now, "reason": reason, "basis": "수동 추가"}],
        })
    by_id = {c["candidate_id"]: c for c in out}
    for i, d in enumerate(region.get("candidate_decisions") or []):
        cid = d.get("candidate_id") or ("deviation-%s" % d["item_id"] if d.get("item_id") else None)
        if cid not in by_id:
            raise CandidateInputError("candidate_decisions[%d]: 후보 없음 %r" % (i, cid))
        if d.get("selection_status") not in SELECTION or not d.get("decided_by") or not d.get("reason"):
            raise CandidateInputError("candidate_decisions[%d]: selection_status·decided_by·reason 필요" % i)
        js = by_id[cid]["judgments"]
        js.append({"seq": len(js) + 1, "selection_status": d["selection_status"], "decided_by": d["decided_by"],
                   "decided_at": d.get("decided_at") or now, "reason": d["reason"], "basis": "사람 판단(구간 JSON)",
                   "previous": js[-1]["selection_status"]})
    for c in out:
        c["selection_status"] = c["judgments"][-1]["selection_status"]
        c["reason"] = c["judgments"][-1]["reason"]
        if c["selection_status"] == "excluded":
            c["risk_proposal"] = {"status": "not_applicable", "reason": c["reason"]}
    return out
