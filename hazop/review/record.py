"""⑤ 검토 결정 기록 생성·검사·review_status 판정 (기획서/인터페이스.md §3.4, §5.2; HAZOP기법지침.md §6·§8.3).

- 결정값: 시나리오 accept·modify·reject·defer, 설계보완 후보는 여기에 not_applicable(자동 지정만).
- 위험도는 사람이 강도·빈도·근거를 넣고, 등급은 이 모듈이 〈표5〉로 계산한다(직접 입력 불가).
- 저장 전 검사(validate_review)를 하나라도 어기면 save_review가 저장을 막는다.
"""

import re

from hazop.analysis.risk import FREQUENCIES, MATRIX_P86, SEVERITIES
from hazop.review import store
from hazop.review.merge import merge_display
from hazop.review.store import ReviewError, utc_now

SCHEMA_VERSION = "0.1"
SCENARIO_DECISIONS = ("accept", "modify", "reject", "defer")
DIC_DECISIONS = SCENARIO_DECISIONS + ("not_applicable",)
RISK_SOURCES = ("human", "ai_proposal_adopted")
SCENARIO_REVISABLE = ("cause", "consequence", "safeguards")
DIC_REVISABLE = ("trigger_description",)
STATUSES = ("not_reviewed", "reviewing", "deferred", "confirmed")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
# Excel(XML)에 쓸 수 없는 제어문자. openpyxl.cell.cell.ILLEGAL_CHARACTERS_RE와 같은 범위(\t \n \r 제외)
ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


def _text(v):
    return isinstance(v, str) and bool(v.strip())


def _scenario(doc, scenario_id):
    for s in doc["scenarios"]:
        if s["scenario_id"] == scenario_id:
            return s
    raise ReviewError("시나리오 없음: %s" % scenario_id)


def _dic(doc, dic_id):
    for d in doc["design_improvement_candidates"]:
        if d["dic_id"] == dic_id:
            return d
    raise ReviewError("설계보완 후보 없음: %s" % dic_id)


def _candidate(doc, candidate_id):
    for c in doc["candidates"]:
        if c["candidate_id"] == candidate_id:
            return c
    raise ReviewError("편차 후보 없음: %s" % candidate_id)


def scenario_match_key(scenario):
    """이전 검토 대응키(§5.3): 패턴 시나리오는 ("match", pattern_ref.match_id), AI 가설은 ("scenario", scenario_id)."""
    ref = scenario.get("pattern_ref") or {}
    if scenario.get("origin") == "pattern" and ref.get("match_id"):
        return ["match", ref["match_id"]]
    return ["scenario", scenario["scenario_id"]]


# ---------------------------------------------------------------- ai_original
def scenario_ai_original(scenario):
    """시나리오의 AI·패턴 원안 사본(§5.2 ai_original). sha256은 analysis.json 시나리오 객체 전체의 정렬 JSON 해시."""
    interp = scenario.get("ai_interpretation")
    pattern = None
    if scenario.get("origin") == "pattern":
        pattern = {"pattern_ref": scenario.get("pattern_ref"), "cause": scenario.get("cause"),
                   "consequence": scenario.get("consequence")}
    return {"scenario_id": scenario["scenario_id"], "origin": scenario.get("origin"),
            "match_key": scenario_match_key(scenario),
            "pattern": pattern, "ai_interpretation": interp,
            "safeguards": scenario.get("safeguards") or [],
            "ai_safeguards": (interp or {}).get("safeguards") or [],
            "risk_proposal": scenario.get("risk_proposal"),
            "sha256": store.obj_sha256(scenario)}


def dic_ai_original(doc, dic):
    """설계보완 후보 원안 사본: 후보 객체 전체 + 연결 시나리오 대응키 + 해시."""
    out = dict(dic)
    out["scenario_match_key"] = scenario_match_key(_scenario(doc, dic["scenario_id"]))
    out["sha256"] = store.obj_sha256(dic)
    return out


# ---------------------------------------------------------------- 위험도
def compute_risk(criteria, severity, frequency):
    """〈표5〉 조회로 위험도 계산. 반환 {"risk", "risk_name", "calculation"}. 허용값 밖·기준표 불일치면 ReviewError."""
    if not criteria:
        raise ReviewError("위험도 기준표 없음 — 확정할 수 없음")
    if type(severity) is not int or severity not in SEVERITIES:
        raise ReviewError("강도 허용값(1–4) 아님: %r" % (severity,))
    if type(frequency) is not int or frequency not in FREQUENCIES:
        raise ReviewError("빈도 허용값(1–3) 아님: %r" % (frequency,))
    risk = criteria["matrix"][str(severity)][str(frequency)]
    if risk != MATRIX_P86[severity][frequency]:
        raise ReviewError("기준표 〈표5〉 값이 코드 고정값과 다름: matrix[%d][%d]" % (severity, frequency))
    return {"risk": risk, "risk_name": criteria["risk_levels"][str(risk)]["name"],
            "calculation": "표5 조회: matrix[severity=%d][frequency=%d] = %d" % (severity, frequency, risk)}


def make_risk_confirmation(run, severity, severity_basis, frequency_without_safeguards, frequency,
                           frequency_basis, credited_safeguards=(), source="human"):
    """사람 위험도 확정값 생성. risk·risk_name·calculation·기준표 식별자는 함수가 채운다(등급 직접 입력 불가).
    credited_safeguards: [{"node_id", "basis": {"reference", "description"}}]. 검사는 check_risk_confirmation."""
    criteria = run["criteria"]
    calc = compute_risk(criteria, severity, frequency)
    return {"severity": severity, "severity_basis": severity_basis,
            "frequency_without_safeguards": frequency_without_safeguards, "frequency": frequency,
            "frequency_basis": frequency_basis,
            "credited_safeguards": [dict(x) for x in credited_safeguards],
            "risk": calc["risk"], "risk_name": calc["risk_name"],
            "criteria_id": criteria["criteria_id"], "criteria_version": criteria["criteria_version"],
            "criteria_file_version": criteria.get("criteria_file_version"),
            "calculation": calc["calculation"], "source": source}


def adopt_ai_proposal(run, scenario_id):
    """'AI 제안 가져오기': AI 제안의 severity·frequency_without_safeguards·frequency_used를 입력값으로 돌려준다.
    근거 문장과 credited_safeguards는 비워 둔다(검토자가 입력). source는 ai_proposal_adopted.
    제안이 proposed가 아니면 ReviewError."""
    rp = _scenario(run["doc"], scenario_id).get("risk_proposal") or {}
    if rp.get("status") != "proposed":
        raise ReviewError("가져올 AI 위험도 제안 없음(상태 %s): %s" % (rp.get("status"), scenario_id))
    return {"severity": rp["severity"], "severity_basis": None,
            "frequency_without_safeguards": rp["frequency_without_safeguards"],
            "frequency": rp["frequency_used"], "frequency_basis": None,
            "credited_safeguards": [], "source": "ai_proposal_adopted",
            "note": "AI 값에서 가져옴 — 근거 확인 필요"}


def graph_node_errors(run, node_ids, label):
    """node_ids가 분석 당시 그래프(<실행>/inputs/graph.json)에 있는지 검사. 오류 목록."""
    graph_nodes = {n["entity_id"] for n in (run.get("graph") or {}).get("nodes", [])}
    return ["%s: %s가 분석 당시 그래프에 없음" % (label, n) for n in node_ids
            if run.get("graph") is None or n not in graph_nodes]


def check_risk_confirmation(run, scenario, rc, imported=False):
    """위험도 확정 검사(§5.2 1·3·4·5와 필수 항목). 오류 목록 반환(빈 목록이면 통과).
    imported=True(이전 검토에서 가져온 결정)이면 현재 실행에 AI 제안이 없어도 source=ai_proposal_adopted를 허용한다."""
    sid = scenario["scenario_id"]
    errs = []
    if not isinstance(rc, dict):
        return ["%s: 위험도 확정값 없음(수용·수정은 강도·빈도 필수)" % sid]
    sev, f0, f = rc.get("severity"), rc.get("frequency_without_safeguards"), rc.get("frequency")
    for name, v, allowed in (("강도", sev, SEVERITIES), ("보호수단 미반영 빈도", f0, FREQUENCIES),
                             ("빈도", f, FREQUENCIES)):
        if type(v) is not int or v not in allowed:
            errs.append("%s: %s 허용값 아님 또는 비어 있음: %r" % (sid, name, v))
    for key, label in (("severity_basis", "강도 근거"), ("frequency_basis", "빈도 근거")):
        if not _text(rc.get(key)):
            errs.append("%s: %s 없음" % (sid, label))
    if rc.get("source") not in RISK_SOURCES:
        errs.append("%s: source는 human 또는 ai_proposal_adopted: %r" % (sid, rc.get("source")))
    elif (rc["source"] == "ai_proposal_adopted" and not imported
          and (scenario.get("risk_proposal") or {}).get("status") != "proposed"):
        errs.append("%s: AI 제안이 없는데 source가 ai_proposal_adopted" % sid)
    criteria = run["criteria"]
    if not errs:
        try:
            calc = compute_risk(criteria, sev, f)
        except ReviewError as e:
            errs.extend("%s: %s" % (sid, m) for m in e.errors)
        else:
            for key in ("risk", "risk_name", "calculation"):
                if rc.get(key) != calc[key]:
                    errs.append("%s: %s가 〈표5〉 계산과 다름(%r ≠ %r) — 등급은 직접 입력할 수 없음"
                                % (sid, key, rc.get(key), calc[key]))
    ref = run["doc"]["analysis_run"]["versions"].get("risk_criteria") or {}
    if criteria and (criteria.get("criteria_id") != ref.get("id") or criteria.get("criteria_version") != ref.get("version")):
        errs.append("%s: 실행 폴더 기준표가 analysis_run.versions.risk_criteria와 다름" % sid)
    if (rc.get("criteria_id"), rc.get("criteria_version")) != (ref.get("id"), ref.get("version")):
        errs.append("%s: 기준표 식별자가 분석 실행의 기준표와 다름" % sid)
    if criteria and rc.get("criteria_file_version") != criteria.get("criteria_file_version"):
        errs.append("%s: criteria_file_version이 분석 실행의 기준표와 다름" % sid)
    credited = rc.get("credited_safeguards")
    if not isinstance(credited, list):
        errs.append("%s: credited_safeguards는 목록이어야 함" % sid)
        credited = []
    if type(f) is int and type(f0) is int and f < f0 and not credited:
        errs.append("%s: 보호수단 없이 빈도를 낮춤(credited_safeguards 필요)" % sid)
    for g in credited:
        g = g if isinstance(g, dict) else {}
        basis = g.get("basis") if isinstance(g.get("basis"), dict) else {}
        if not _text(g.get("node_id")):
            errs.append("%s: 인정 보호수단에 node_id 없음" % sid)
        else:
            errs.extend(graph_node_errors(run, [g["node_id"]], "%s: 인정 보호수단" % sid))
        if not _text(basis.get("reference")) or not _text(basis.get("description")):
            errs.append("%s: 인정 보호수단 %s에 확인 근거(basis.reference·description) 없음"
                        % (sid, g.get("node_id")))
    return errs


# ---------------------------------------------------------------- 결정 만들기
def scenario_decision(run, scenario_id, decision, reason, reviewer_id, revised=None,
                      risk_confirmation=None, imported_from=None, now=None):
    """시나리오 결정 항목. revised는 편집한 값(cause·consequence·safeguards)이며 원안과 같은 필드는 빠진다.
    revised는 modify에서만 남는다. 검사는 validate_review에서."""
    sc = _scenario(run["doc"], scenario_id)
    rev = None
    if decision == "modify" and revised:
        base = merge_display(sc)
        rev = {k: v for k, v in revised.items() if k not in base or v != base[k]["value"]} or None
    elif revised and decision != "modify":
        raise ReviewError("%s: revised는 수정(modify)에서만 쓸 수 있음" % scenario_id)
    return {"scenario_id": scenario_id, "decision": decision, "reason": reason,
            "ai_original": scenario_ai_original(sc), "revised": rev,
            "risk_confirmation": risk_confirmation if decision in ("accept", "modify") else None,
            "imported_from": imported_from, "decided_by": reviewer_id, "decided_at": now or utc_now()}


def dic_decision(run, dic_id, decision, reason, reviewer_id, recommendation=None, revised=None,
                 imported_from=None, now=None):
    """설계보완 후보 결정 항목(accept·modify·reject·defer). not_applicable은 build_review가 자동 지정한다.
    수용·수정은 recommendation(개선 권고 문안) 필수, revised는 modify에서 trigger_description만."""
    d = _dic(run["doc"], dic_id)
    if decision == "not_applicable":
        raise ReviewError("%s: not_applicable은 사람이 고를 수 없음(시나리오 기각 시 자동)" % dic_id)
    return {"dic_id": dic_id, "decision": decision, "reason": reason,
            "ai_original": dic_ai_original(run["doc"], d),
            "revised": (revised or None) if decision == "modify" else revised,
            "recommendation": recommendation if decision in ("accept", "modify") else None,
            "inherited_from": None, "imported_from": imported_from,
            "decided_by": reviewer_id, "decided_at": now or utc_now()}


def no_scenario_confirmation(reason, reviewer_id, imported_from=None, now=None):
    """'시나리오 없음 확인' 결정(시나리오 0개 선택 편차 전용)."""
    return {"decision": "confirm_no_scenario", "reason": reason, "decided_by": reviewer_id,
            "decided_at": now or utc_now(), "imported_from": imported_from}


def memo_record(memo_id, content, reason, reviewer_id, hold_ids=(), now=None):
    """자료 요청 메모 항목. 조치로 자동 전환하지 않는다."""
    return {"memo_id": memo_id, "hold_ids": list(hold_ids), "content": content, "reason": reason,
            "created_by": reviewer_id, "created_at": now or utc_now()}


# ---------------------------------------------------------------- 검토본
def _apply_not_applicable(doc, scenario_decisions, dic_decisions):
    """기각 시나리오에 연결된 설계보완 후보를 not_applicable(사유 상속)로 바꾼다. 수용·수정은 그대로 두어 검사에서 차단."""
    rejected = {d["scenario_id"]: d for d in scenario_decisions if d.get("decision") == "reject"}
    by_id = {d["dic_id"]: d for d in dic_decisions}
    out = []
    for dic in doc["design_improvement_candidates"]:
        cur = by_id.pop(dic["dic_id"], None)
        sd = rejected.get(dic["scenario_id"])
        if sd and (cur is None or cur.get("decision") not in ("accept", "modify")):
            cur = {"dic_id": dic["dic_id"], "decision": "not_applicable", "reason": sd["reason"],
                   "ai_original": dic_ai_original(doc, dic), "revised": None, "recommendation": None,
                   "inherited_from": sd["scenario_id"], "imported_from": None,
                   "decided_by": sd["decided_by"], "decided_at": sd["decided_at"]}
        if cur is not None:
            out.append(cur)
    out.extend(by_id.values())  # 실행에 없는 후보 ID — 검사에서 차단
    return out


def build_review(run, candidate_id, reviewer_id, reason, scenario_decisions=(), dic_decisions=(),
                 no_scenario=None, memo_records=(), review_required=False):
    """편차 검토본(저장 전 초안)을 만든다. not_applicable 자동 지정, review_status·최상위 risk_confirmation·
    action_ids·material_request_memos를 계산한다. review_version·reviewed_at은 save_review가 정한다."""
    doc = run["doc"]
    sds = [dict(d) for d in scenario_decisions]
    dds = _apply_not_applicable(doc, sds, [dict(d) for d in dic_decisions])
    memos = [dict(m) for m in memo_records]
    rec = {"schema_version": SCHEMA_VERSION, "project_id": doc.get("project_id"),
           "review_id": "review-%s" % candidate_id, "review_version": None,
           "analysis_run_id": doc["analysis_run_id"], "candidate_id": candidate_id,
           "review_status": None, "review_required": review_required,
           "risk_confirmation": top_risk_confirmation(sds), "reviewer_id": reviewer_id, "reason": reason,
           "action_ids": ["action-%s" % d["dic_id"] for d in dds if d.get("decision") in ("accept", "modify")],
           "material_request_memos": [m.get("content") for m in memos],
           "previous_review_version": None, "reviewed_at": None,
           "analysis_ref": {"analysis_sha256": run["analysis_sha256"], "region_ref": doc["region_ref"],
                            "graph_ref": doc["graph_ref"]},
           "no_scenario_confirmation": no_scenario,
           "scenario_decisions": sds, "design_improvement_decisions": dds, "memo_records": memos}
    rec["review_status"] = compute_review_status(doc, candidate_id, rec)
    return rec


def top_risk_confirmation(scenario_decisions):
    """편차 대표 위험도: 확정값 중 risk가 가장 높은 것(같으면 앞 순서)을 scenario_id와 함께. 없으면 None."""
    best = None
    for d in scenario_decisions:
        rc = d.get("risk_confirmation")
        if isinstance(rc, dict) and isinstance(rc.get("risk"), int) and (best is None or rc["risk"] > best["risk"]):
            best = {"scenario_id": d["scenario_id"], "severity": rc.get("severity"),
                    "frequency": rc.get("frequency"), "risk": rc["risk"], "source": rc.get("source")}
    return best


def compute_review_status(doc, candidate_id, record):
    """§5.2 판정 순서: 기록 없음→not_reviewed, 미결정 항목 있음→reviewing, 그 외 defer 있음→deferred, 그 외 confirmed.
    결정 항목: 시나리오 1개 이상이면 각 시나리오·설계보완 후보, 0개면 '시나리오 없음 확인' 하나."""
    if record is None:
        return "not_reviewed"
    sids = [s["scenario_id"] for s in doc["scenarios"] if s["candidate_id"] == candidate_id]
    dics = [d["dic_id"] for d in doc["design_improvement_candidates"] if d["candidate_id"] == candidate_id]
    sdec = {d.get("scenario_id"): d.get("decision") for d in record.get("scenario_decisions") or []}
    ddec = {d.get("dic_id"): d.get("decision") for d in record.get("design_improvement_decisions") or []}
    if sids:
        items = [sdec.get(s) for s in sids] + [ddec.get(d) for d in dics]
        decided = [v in SCENARIO_DECISIONS for v in items[:len(sids)]] + \
                  [v in DIC_DECISIONS for v in items[len(sids):]]
    else:
        nsc = record.get("no_scenario_confirmation")
        items = ["confirm_no_scenario" if nsc else None]
        decided = [bool(nsc)]
    if not items or not all(decided):
        return "reviewing"
    if "defer" in items:
        return "deferred"
    return "confirmed"


def review_summary(doc, records):
    """실행 전체 검토 집계. records: {candidate_id: 최신 검토본}. 판정은 선택 편차만,
    제외·판단 보류 후보는 따로 센다. 반환 {"by_candidate", "counts", "excluded", "selection_deferred"}."""
    by, counts = {}, {s: 0 for s in STATUSES}
    excluded, sel_deferred = [], []
    for c in doc["candidates"]:
        cid = c["candidate_id"]
        if c["selection_status"] == "excluded":
            excluded.append(cid)
        elif c["selection_status"] == "deferred":
            sel_deferred.append(cid)
        else:
            st = compute_review_status(doc, cid, records.get(cid))
            by[cid] = st
            counts[st] += 1
    return {"by_candidate": by, "counts": counts, "excluded": excluded, "selection_deferred": sel_deferred}


def _check_common(prefix, d, errs):
    if not _text(d.get("reason")):
        errs.append("%s: 사유 없음" % prefix)
    if not _text(d.get("decided_by")):
        errs.append("%s: 결정자 없음" % prefix)
    if not isinstance(d.get("decided_at"), str) or not _UTC.match(d["decided_at"]):
        errs.append("%s: 결정 시각이 UTC ISO 형식 아님" % prefix)


def _check_imported(prefix, imp, key, errs):
    if imp is None:
        return
    if not isinstance(imp, dict) or not _text(imp.get("analysis_run_id")) or \
            type(imp.get("review_version")) is not int or (key and not _text(imp.get(key))):
        errs.append("%s: imported_from 형식 오류" % prefix)


def validate_review(run, record):
    """저장 전 검사. 오류 목록 반환(빈 목록이면 저장 가능). 잠금(해시)·blocked 결과도 여기서 막는다."""
    doc = run["doc"]
    errs = list(store.check_editable(run, record)["reasons"])
    errs.extend(control_char_errors(record))
    if not _text(record.get("reviewer_id")):
        errs.append("검토자 이름(reviewer_id) 없음 — 저장 전에 입력 필요")
    if not _text(record.get("reason")):
        errs.append("검토본 요약 사유 없음")
    cid = record.get("candidate_id")
    try:
        cand = _candidate(doc, cid)
    except ReviewError as e:
        return errs + e.errors
    if cand["selection_status"] != "selected":
        errs.append("선택(selected) 편차만 검토 확정 대상: %s(%s)" % (cid, cand["selection_status"]))
    if record.get("analysis_run_id") != doc["analysis_run_id"]:
        errs.append("analysis_run_id가 열린 실행과 다름")
    scen = {s["scenario_id"]: s for s in doc["scenarios"] if s["candidate_id"] == cid}
    dics = {d["dic_id"]: d for d in doc["design_improvement_candidates"] if d["candidate_id"] == cid}
    sdecs, seen = {}, set()
    for d in record.get("scenario_decisions") or []:
        sid = d.get("scenario_id")
        p = "시나리오 %s" % sid
        if sid not in scen:
            errs.append("%s: 이 편차의 시나리오가 아님" % p)
            continue
        if sid in seen:
            errs.append("%s: 결정 중복" % p)
        seen.add(sid)
        sdecs[sid] = d
        if d.get("decision") not in SCENARIO_DECISIONS:
            errs.append("%s: 결정값 오류 %r" % (p, d.get("decision")))
        _check_common(p, d, errs)
        _check_imported(p, d.get("imported_from"), "scenario_id", errs)
        if d.get("ai_original") != scenario_ai_original(scen[sid]):
            errs.append("%s: ai_original이 analysis.json 원안과 다름" % p)
        rev = d.get("revised")
        if rev is not None:
            if d.get("decision") != "modify":
                errs.append("%s: revised는 수정(modify)에서만" % p)
            base = merge_display(scen[sid])
            for k, v in (rev.items() if isinstance(rev, dict) else [("?", None)]):
                if k not in SCENARIO_REVISABLE:
                    errs.append("%s: 수정할 수 없는 필드 %s" % (p, k))
                elif v == base[k]["value"]:
                    errs.append("%s: revised에 바뀌지 않은 필드 %s" % (p, k))
                elif k == "safeguards" and (not isinstance(v, list) or
                                            any(not isinstance(g, dict) or not _text(g.get("node_id")) for g in v)):
                    errs.append("%s: 수정 보호수단은 node_id가 있는 항목 목록이어야 함" % p)
                elif k == "safeguards":
                    errs.extend(graph_node_errors(run, [g["node_id"] for g in v], "%s: 수정 보호수단" % p))
                elif k != "safeguards" and not _text(v):
                    errs.append("%s: 수정한 %s가 비어 있음" % (p, k))
        if d.get("decision") == "modify" and not rev:
            errs.append("%s: 수정(modify)인데 바뀐 내용이 없음 — 바뀐 내용이 없으면 수용으로" % p)
        if d.get("decision") in ("accept", "modify"):
            errs.extend(check_risk_confirmation(run, scen[sid], d.get("risk_confirmation"),
                                                imported=d.get("imported_from") is not None))
        elif d.get("risk_confirmation") is not None:
            errs.append("%s: 기각·보류는 risk_confirmation이 null이어야 함" % p)
    seen = set()
    for d in record.get("design_improvement_decisions") or []:
        did = d.get("dic_id")
        p = "설계보완 후보 %s" % did
        if did not in dics:
            errs.append("%s: 이 편차의 설계보완 후보가 아님" % p)
            continue
        if did in seen:
            errs.append("%s: 결정 중복" % p)
        seen.add(did)
        dec = d.get("decision")
        if dec not in DIC_DECISIONS:
            errs.append("%s: 결정값 오류 %r" % (p, dec))
        _check_common(p, d, errs)
        _check_imported(p, d.get("imported_from"), "dic_id", errs)
        if d.get("ai_original") != dic_ai_original(doc, dics[did]):
            errs.append("%s: ai_original이 analysis.json 원안과 다름" % p)
        linked = sdecs.get(dics[did]["scenario_id"]) or {}
        if linked.get("decision") == "reject":
            if dec in ("accept", "modify"):
                errs.append("%s: 연결 시나리오 기각과 수용·수정을 함께 저장할 수 없음" % p)
            elif dec != "not_applicable":
                errs.append("%s: 연결 시나리오가 기각이면 not_applicable이어야 함" % p)
        if dec == "not_applicable":
            if linked.get("decision") != "reject" or d.get("inherited_from") != dics[did]["scenario_id"]:
                errs.append("%s: not_applicable은 연결 시나리오 기각 시 자동 지정만 가능" % p)
            elif d.get("reason") != linked.get("reason"):
                errs.append("%s: not_applicable 사유가 시나리오 기각 사유와 다름" % p)
        elif d.get("inherited_from") is not None:
            errs.append("%s: inherited_from은 not_applicable에서만" % p)
        if dec in ("accept", "modify") and not _text(d.get("recommendation")):
            errs.append("%s: 수용·수정은 개선 권고 문안 필수" % p)
        rev = d.get("revised")
        if rev is not None and (dec != "modify" or not isinstance(rev, dict) or
                                any(k not in DIC_REVISABLE or not _text(v) for k, v in rev.items())):
            errs.append("%s: revised는 수정에서 trigger_description만" % p)
    nsc = record.get("no_scenario_confirmation")
    if nsc is not None:
        if scen:
            errs.append("시나리오가 있는 편차에는 '시나리오 없음 확인'을 쓸 수 없음")
        if not isinstance(nsc, dict) or nsc.get("decision") != "confirm_no_scenario":
            errs.append("'시나리오 없음 확인' 결정값 오류")
        else:
            _check_common("시나리오 없음 확인", nsc, errs)
            _check_imported("시나리오 없음 확인", nsc.get("imported_from"), None, errs)
    holds = {h["hold_id"] for h in doc["holds"]}
    memos = record.get("memo_records") or []
    for m in memos:
        if not _text(m.get("memo_id")) or not _text(m.get("content")) or not _text(m.get("created_by")):
            errs.append("메모 %s: memo_id·내용·작성자 필요" % m.get("memo_id"))
        bad = [h for h in m.get("hold_ids") or [] if h not in holds]
        if bad:
            errs.append("메모 %s: 없는 보류 ID %s" % (m.get("memo_id"), bad))
    if len({m.get("memo_id") for m in memos}) != len(memos):
        errs.append("메모 ID 중복")
    if record.get("material_request_memos") != [m.get("content") for m in memos]:
        errs.append("material_request_memos가 memo_records 내용과 다름")
    if record.get("review_status") != compute_review_status(doc, cid, record):
        errs.append("review_status가 판정 규칙 결과와 다름")
    if record.get("risk_confirmation") != top_risk_confirmation(record.get("scenario_decisions") or []):
        errs.append("최상위 risk_confirmation이 시나리오 확정값 최댓값과 다름")
    want_actions = ["action-%s" % d.get("dic_id") for d in record.get("design_improvement_decisions") or []
                    if d.get("decision") in ("accept", "modify")]
    if record.get("action_ids") != want_actions:
        errs.append("action_ids가 수용·수정한 설계보완 후보와 다름")
    ref = record.get("analysis_ref") or {}
    if ref.get("region_ref") != doc["region_ref"] or ref.get("graph_ref") != doc["graph_ref"]:
        errs.append("analysis_ref의 구간·그래프 참조가 실행과 다름")
    return errs


def control_char_errors(record, path=""):
    """사람이 입력한 문자열(ai_original 제외)에 Excel에 쓸 수 없는 제어문자가 있으면 필드 경로와 함께 오류."""
    errs = []
    if isinstance(record, dict):
        for k, v in record.items():
            if k != "ai_original":
                errs.extend(control_char_errors(v, "%s.%s" % (path, k) if path else k))
    elif isinstance(record, list):
        for i, v in enumerate(record):
            errs.extend(control_char_errors(v, "%s[%d]" % (path, i)))
    elif isinstance(record, str) and ILLEGAL_CHARACTERS_RE.search(record):
        errs.append("%s: 쓸 수 없는 제어문자가 있음(\\t \\n \\r 외)" % path)
    return errs


def save_review(store_root, run, record, now=None):
    """검사 후 새 버전 파일로 저장한다. review_version = 최신+1, previous_review_version, reviewed_at을 채운다.
    이전 버전 검토본이 다른 analysis_sha256을 가리키면(잠금) 저장 거부. 실패 시 ReviewError(파일을 만들지 않음).
    반환 (경로, 저장한 레코드)."""
    rec = dict(record)
    region_id = rec["analysis_ref"]["region_ref"]["region_id"]
    versions = store.list_versions(store_root, region_id, rec["analysis_run_id"], rec["candidate_id"])
    errs = []
    if versions:
        prev = store.load_review(store_root, region_id, rec["analysis_run_id"], rec["candidate_id"], versions[-1])
        base = store.check_editable(run, None)["reasons"]
        errs.extend("이전 검토본: %s" % m for m in store.check_editable(run, prev)["reasons"] if m not in base)
    errs.extend(validate_review(run, rec))
    if errs:
        raise ReviewError(errs)
    rec["review_version"] = (versions[-1] + 1) if versions else 1
    rec["previous_review_version"] = versions[-1] if versions else None
    rec["reviewed_at"] = now or utc_now()
    return store.write_new_version(store_root, rec), rec

