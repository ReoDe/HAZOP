"""비교 입력 뷰 생성 (기획서/평가기준비교.md §3.5, §3.6). 분석 실행 폴더·검토 저장소를 읽기만 한다.

build_view(run_dir, store_root, basis, export_path) -> (view, reasons)
- reasons: 차단 사유(분석 결과 검증 상태가 passed가 아님, 출력 기록 해시 불일치, 그래프 사본 없음,
  reviewed에서 검토 기록이 현재 analysis.json과 다른 해시를 가리킴). 비어 있으면 비교 가능.
- 원인·결과·보호수단 값은 hazop.review.merge_display(Excel 2–4열과 같은 함수)로 만든다.
"""

import json

from hazop import review as rv
from hazop.evaluate.criteria import norm

BASES = ("draft", "reviewed")


def _graph_tags(graph):
    return {n["entity_id"]: n.get("tag") for n in (graph or {}).get("nodes", [])}


def _safeguard_items(items, tags):
    out = []
    for g in items or []:
        tag = g.get("tag") or tags.get(g.get("node_id"))
        out.append({"tag": tag, "description": g.get("description") or ""})
    return out


def _load_export(export_path, run, reasons):
    """출력 기록 → (export_id, {scenario_id: 워크시트 행}). 해시가 다르면 reasons에 넣는다."""
    try:
        with open(export_path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError) as exc:
        reasons.append("출력 기록을 읽을 수 없음: %s" % exc)
        return None, {}
    target = rec.get("target") or {}
    if target.get("analysis_sha256") != run["analysis_sha256"]:
        reasons.append("analysis.json 해시가 출력 기록(%s)의 target.analysis_sha256과 다름"
                       % rec.get("export_id"))
    rows = {}
    for r in (rec.get("rows") or {}).get("worksheet") or []:
        if r.get("scenario_id"):
            rows[r["scenario_id"]] = r.get("row")
    return rec.get("export_id"), rows


def build_view(run_dir, store_root, basis="draft", export_path=None):
    """비교 입력 뷰와 차단 사유. analysis.json이 없으면 hazop.review.ReviewError."""
    if basis not in BASES:
        raise ValueError("basis는 draft 또는 reviewed: %r" % (basis,))
    run = rv.open_run(run_dir)
    doc = run["doc"]
    reasons = list(run["blocked_reasons"])
    if run["graph"] is None:
        reasons.append("실행 사본 inputs/graph.json 없음 — 원인 설비 태그를 만들 수 없음")
    tags = _graph_tags(run["graph"])
    export_id, ws_rows = None, {}
    if export_path:
        export_id, ws_rows = _load_export(export_path, run, reasons)
    region_id, run_id = doc["region_ref"]["region_id"], doc["analysis_run_id"]
    records = rv.load_run_reviews(store_root, region_id, run_id)
    if basis == "reviewed":
        for cid, rec in sorted(records.items()):
            for r in rv.check_editable(run, rec)["reasons"]:
                if r not in run["blocked_reasons"]:
                    reasons.append("검토 기록 %s v%s: %s" % (cid, rec.get("review_version"), r))

    selected = {c["candidate_id"] for c in doc["candidates"] if c["selection_status"] == "selected"}
    scenarios, excluded = [], 0
    for s in doc["scenarios"]:
        cid, sid = s["candidate_id"], s["scenario_id"]
        if cid not in selected:
            continue
        rec = records.get(cid) or {}
        sd = {d["scenario_id"]: d for d in rec.get("scenario_decisions") or []}.get(sid)
        decision = (sd or {}).get("decision")
        recs = []
        if basis == "reviewed":
            if decision == "reject":
                excluded += 1
                continue
            ddecs = {d["dic_id"]: d for d in rec.get("design_improvement_decisions") or []}
            for dic in doc["design_improvement_candidates"]:
                dd = ddecs.get(dic["dic_id"]) or {}
                if dic["scenario_id"] == sid and dd.get("decision") in ("accept", "modify"):
                    recs.append(dd.get("recommendation"))
            merged = rv.merge_display(s, sd)
        else:
            merged = rv.merge_display(s, None)
        cause_tags = []
        for n in s.get("cause_equipment") or []:
            t = tags.get(n)
            if t and t not in cause_tags:
                cause_tags.append(t)
        scenarios.append({
            "scenario_id": sid, "candidate_id": cid, "worksheet_row": ws_rows.get(sid),
            "cause": merged["cause"]["value"], "consequence": merged["consequence"]["value"],
            "cause_equipment_tags": cause_tags,
            "safeguards": _safeguard_items(merged["safeguards"]["value"], tags),
            "recommendations": recs, "decision": decision})
    view = {
        "analysis_run_id": run_id, "analysis_sha256": run["analysis_sha256"],
        "region_ref": doc["region_ref"], "graph_ref": doc["graph_ref"],
        "operating_mode": doc.get("operating_mode"), "basis": basis, "export_id": export_id,
        "reviews": [{"candidate_id": cid, "review_version": r.get("review_version")}
                    for cid, r in sorted(records.items(), key=lambda kv: (kv[0], kv[1].get("review_version") or 0))],
        "excluded_by_review": excluded,
        "graph_tags": sorted({norm(t) for t in tags.values() if t}),
        "deviations": [{"candidate_id": c["candidate_id"], "item_id": c.get("item_id"),
                        "parameter_ko": c.get("parameter_ko"), "guide_word_ko": c.get("guide_word_ko"),
                        "guide_word_en": c.get("guide_word_en"), "selection_status": c["selection_status"]}
                       for c in doc["candidates"]],
        "scenarios": scenarios,
    }
    return view, reasons
