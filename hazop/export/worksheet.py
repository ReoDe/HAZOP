"""Excel 워크시트 출력 (기획서/인터페이스.md §6, §5.1 exports, §8 Excel 행; HAZOP기법지침.md §7 〈별표7〉·〈별표9〉).

export_worksheet(run_dir, store_root, out_root, scope, now)
- 시트: 분석 정보 / 전체 편차 후보 / HAZOP 워크시트(〈별표7〉) / 설계보완 후보 / 개선 권고(〈별표9〉) / 자료 요청 메모
- 2–4열은 hazop.review.merge_display(⑤ 화면 재조회와 같은 함수), 5–7열은 사람 확정값(risk_confirmation)만.
  AI 위험도 제안은 추가 열에만 쓰고, 〈별표9〉 위험등급·우선순위는 연결 시나리오의 risk_confirmation에서만 가져온다
  (설계보완 후보의 basis.risk는 쓰지 않음).
- blocked 결과, analysis.json 삭제·해시 불일치(검토 기록 기준)면 출력하지 않는다(ExportError).
- 파일은 <out_root>/<region_id>/<analysis_run_id>/worksheet-<출력 시각>.xlsx에 새로 만들고 덮어쓰지 않는다.
  출력 기록은 <store_root>/reviews/<region_id>/<analysis_run_id>/exports/<출력 시각>.json.
- '=', '+', '-', '@'로 시작하는 문자열은 문자열 셀(data_type 's', quotePrefix)로 쓴다(수식 주입 방지).
"""

import datetime
import hashlib
import io
import json
import os
import re

from hazop import paths
from hazop.analysis.ai import STATUS_LABELS_KO
from hazop import review as rv
from hazop.review import store
from hazop.study import span

SCOPES = {"all": "전체", "accepted_modified": "수용·수정 행만"}
SHEETS = ("분석 정보", "전체 편차 후보", "HAZOP 워크시트", "설계보완 후보", "개선 권고", "자료 요청 메모")
UNCONFIRMED = "미확정"
NOT_MANAGED = "관리 안 함"
NO_SCENARIO = "시나리오 없음"
FORMULA_PREFIX = ("=", "+", "-", "@")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
KST = datetime.timezone(datetime.timedelta(hours=9), "KST")

# 〈별표7〉 1–8열(원문 순서) + 프로젝트 추가 열(§6.2). (키, 4행 머리글, 5행 하위 머리글)
WORKSHEET_COLUMNS = (
    ("deviation", "이탈", None), ("cause", "원인", None), ("consequence", "결과", None),
    ("safeguards", "현재안전조치", None),
    ("frequency", "위험도", "빈도"), ("severity", "위험도", "강도"), ("risk", "위험도", "위험도"),
    ("recommendation", "개선권고사항", None), ("drawings", "도면 번호", None),
    ("candidate_id", "편차 ID", None), ("scenario_id", "시나리오 ID", None), ("origin", "출처", None),
    ("pattern", "적용 패턴", None), ("value_source", "값 출처", None), ("ai_safeguards", "AI 제시 보호수단", None),
    ("ai_risk", "AI 위험도 제안", None), ("risk_source", "위험도 확정 출처", None),
    ("risk_name", "확정 위험도 등급명(〈표6〉)", None), ("decision", "검토 결정", None),
    ("decision_reason", "결정 사유", None), ("decided_by", "검토자", None), ("decided_at", "결정 시각(UTC)", None),
    ("dics", "설계보완 후보", None), ("evidence", "근거 참조", None), ("holds", "보류·미확인", None),
)
HEADER_ROW, SUBHEADER_ROW, FIRST_DATA_ROW = 4, 5, 6
RECOMMENDATION_COLUMNS = ("번호", "우선순위", "위험등급", "개선권고사항", "책임부서", "조치일정", "진행결과", "완료확인", "비고")

DECISION_LABELS = {"accept": "수용", "modify": "수정", "reject": "기각", "defer": "보류",
                   "not_applicable": "해당 없음(시나리오 기각)", "confirm_no_scenario": "시나리오 없음 확인", None: "미검토"}
STATUS_LABELS = {"not_reviewed": "미검토", "reviewing": "검토 중", "deferred": "보류", "confirmed": "확정"}
SELECTION_LABELS = {"selected": "선택", "excluded": "제외", "deferred": "보류"}
ORIGIN_LABELS = {"pattern": "패턴", "ai_additional_hypothesis": "AI 추가 가설"}
TRIGGER_LABELS = {"risk_conditional_or_worse": "제안 위험도가 〈표9〉 조건부 수용 이상",
                  "no_safeguard_found_in_graph": "그래프에서 원인과 독립인 보호수단을 찾지 못함(없음이 아니라 미확인)"}
RISK_SOURCE_LABELS = {"human": "사람 확정(직접 고름)",
                      "ai_proposal_adopted": "사람 확정(AI 제안 가져옴 — 근거 확인 필요)"}


class ExportError(rv.ReviewError):
    """출력 차단(blocked 결과, 해시 불일치, 같은 이름 파일 있음 등). errors에 사유 목록."""


# ---------------------------------------------------------------- 공통
def kst_date(utc_iso):
    """UTC ISO 8601('...Z') → 한국 표준시 날짜 'YYYY-MM-DD'."""
    t = datetime.datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(KST).strftime("%Y-%m-%d")


def _put(ws, row, col, value, bold=False):
    """셀 쓰기. None은 '미확인'으로 쓰고(빈칸으로 바꾸지 않음), 수식처럼 시작하는 문자열은 문자열 셀로 고정한다."""
    from openpyxl.styles import Alignment, Font
    if value is None:
        value = "미확인"
    cell = ws.cell(row=row, column=col)
    cell.value = value
    if isinstance(value, str) and value.startswith(FORMULA_PREFIX):
        cell.data_type = "s"
        cell.quotePrefix = True
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    if bold:
        cell.font = Font(bold=True)
    return cell


def _table(ws, header_row, headers, rows):
    for i, h in enumerate(headers, 1):
        _put(ws, header_row, i, h, bold=True)
    for r, values in enumerate(rows, header_row + 1):
        for c, v in enumerate(values, 1):
            _put(ws, r, c, v)
    return header_row + len(rows)


def _tags(run):
    return {n["entity_id"]: n.get("tag") for n in (run.get("graph") or {}).get("nodes", [])}


def _tagged(nid, tags):
    tag = tags.get(nid)
    return "%s(%s)" % (tag, nid) if tag else nid


# 근거 참조 열의 경로 밸브 문구 (머리말, 판정). 문구·제어밸브 주석은 총괄 결정(권고안, 사용자 위임 2026-11-06)
VALVE_CLOSED = ("정상 닫힘 밸브 경유", "정상 운전 유로 아님")
VALVE_UNKNOWN = ("정상 위치 미확인 밸브 경유", "정상 운전 유로 여부 판단 보류")
VALVE_UNKNOWN_NOT_MATERIAL = ("정상 위치 미확인 밸브 경유", "물질 유로 아님")
CONTROL_VALVE_NOTE = "(제어밸브, 운전 중 개폐 가능 [일반지식])"


def ai_status_label(status):
    """AI 상태 한국어 라벨(정본 hazop.analysis.ai.STATUS_LABELS_KO). 모르는 코드는 그대로, 없으면 '미요청'."""
    return STATUS_LABELS_KO.get(status, status or "미요청")


def _valve_path_text(doc, s):
    """시나리오가 인용한 탐색 경로(ev-path-*) 위의 닫힌·정상 위치 미확인 밸브(④ explore valves_on_path).
    닫힌 밸브 경유 경로도 탐색에서 끊지 않으므로(오조작 원인 검토용) 사람이 보도록 근거 열에 적는다. 없으면 None."""
    cited = set((s.get("graph_evidence") or {}).get("evidence_ids") or [])
    bundle = (doc.get("evidence_bundles") or {}).get(s.get("candidate_id")) or {}
    groups = {}  # (머리말, 판정) -> {밸브 이름: 표시}
    for ev in bundle.get("evidence") or []:
        if ev.get("type") != "exploration_path" or ev.get("evidence_id") not in cited:
            continue
        for v in ev.get("valves_on_path") or []:
            name = v.get("tag") or v.get("entity_id")
            if v.get("state") == "closed":
                label = "%s(%s)" % (name, v.get("normal_position"))
                if v.get("kind") == "control_valve":
                    label += CONTROL_VALVE_NOTE
                groups.setdefault(VALVE_CLOSED, {})[name] = label
            elif v.get("state") == "unknown":
                key = (VALVE_UNKNOWN_NOT_MATERIAL if ev.get("normal_operation_flow") == "not_material_path"
                       else VALVE_UNKNOWN)
                groups.setdefault(key, {})[name] = name
    lines = ["%s: %s — %s" % (key[0], ", ".join(groups[key][k] for k in sorted(groups[key])), key[1])
             for key in (VALVE_CLOSED, VALVE_UNKNOWN, VALVE_UNKNOWN_NOT_MATERIAL) if key in groups]
    return "\n".join(lines) or None


def _safeguards_text(items, source, tags):
    if not items:
        if source == "revised":
            return "보호수단 없음(검토자 수정)"
        if source == "ai":
            return "AI 제시 없음"
        return "미확인 — 도면에서 확인된 보호수단을 찾지 못함(없음이 아님)"
    lines = []
    for g in items:
        name = g.get("tag") or tags.get(g.get("node_id")) or g.get("node_id")
        line = name + (": %s" % g["description"] if g.get("description") else "")
        if g.get("adequacy") in (None, "unknown"):
            line += " [적정성 미확인]"
        lines.append(line)
    return "\n".join(lines)


def _recommendation_text(recs, pending, dics):
    """8열: 수용·수정 권고 문안. 연결 설계보완 후보가 미검토·보류면 '미확정'(남은 후보 수 표시).
    '해당 없음'은 연결 후보가 아예 없을 때만 쓴다."""
    if recs:
        text = "\n".join(recs)
        return text + ("\n(미확정 설계보완 후보 %d건 남음)" % len(pending) if pending else "")
    if pending:
        return "%s(설계보완 후보 %d건 미검토·보류)" % (UNCONFIRMED, len(pending))
    if dics:
        return "개선 권고 없음(설계보완 후보 기각·해당 없음 결정)"
    return "해당 없음(연결된 설계보완 후보 없음)"


def _ai_risk_text(rp):
    if not rp:
        return "AI 제안 없음"
    if rp.get("status") == "proposed":
        return "제안(확정 아님): 강도 %s·빈도 %s·위험도 %s(%s)" % (rp.get("severity"), rp.get("frequency_used"),
                                                       rp.get("risk"), rp.get("risk_name"))
    return "%s: %s" % ("보류" if rp.get("status") == "deferred" else rp.get("status"), rp.get("reason") or "사유 없음")


def _check_exportable(run, records):
    """출력 차단 사유 목록: blocked 결과, 검토 기록별 잠금(analysis.json 삭제·해시 불일치)."""
    reasons = list(run["blocked_reasons"])
    for cid, rec in sorted(records.items()):
        for r in rv.check_editable(run, rec)["reasons"]:
            if r not in run["blocked_reasons"]:
                reasons.append("%s v%s: %s" % (cid, rec.get("review_version"), r))
    return reasons


# ---------------------------------------------------------------- 행 만들기
def _decisions(rec):
    rec = rec or {}
    return ({d["scenario_id"]: d for d in rec.get("scenario_decisions") or []},
            {d["dic_id"]: d for d in rec.get("design_improvement_decisions") or []})


def drawing_numbers(run, node=None):
    """'도면 번호' 열 값. node(span.annotate를 거친 검토구간)를 주면 그 구간이 지나는 모든 도면(흐름 순서),
    없으면 분석 실행의 도면(구간 JSON은 도면 하나 기준)."""
    if node is not None:
        return span.drawing_column(node)
    return (run["doc"]["analysis_run"]["versions"].get("graph_source") or {}).get("drawing_number")


def worksheet_rows(run, records, scope, node=None):
    """HAZOP 워크시트 행 목록(dict, 키는 WORKSHEET_COLUMNS). 선택 편차의 시나리오마다 한 행,
    시나리오 없는 선택 편차는 '시나리오 없음' 한 행(전체 범위에서만). node는 drawing_numbers 참고."""
    doc, tags = run["doc"], _tags(run)
    drawings = drawing_numbers(run, node)
    holds_by_scope = {}
    for h in doc["holds"]:
        holds_by_scope.setdefault(h.get("scope"), []).append(h)
    rows = []
    for c in doc["candidates"]:
        if c["selection_status"] != "selected":
            continue
        cid = c["candidate_id"]
        rec = records.get(cid)
        sdecs, ddecs = _decisions(rec)
        scens = [s for s in doc["scenarios"] if s["candidate_id"] == cid]
        if not scens:
            if scope != "all":
                continue
            nsc = (rec or {}).get("no_scenario_confirmation")
            holds = [h for h in doc["holds"] if h.get("candidate_id") == cid]
            rows.append({
                "deviation": c["deviation"], "cause": NO_SCENARIO, "consequence": NO_SCENARIO,
                "safeguards": NO_SCENARIO, "frequency": UNCONFIRMED, "severity": UNCONFIRMED, "risk": UNCONFIRMED,
                "recommendation": "해당 없음(시나리오 없음)", "drawings": drawings, "candidate_id": cid, "scenario_id": NO_SCENARIO,
                "origin": "해당 없음", "pattern": "해당 없음", "value_source": "해당 없음", "ai_safeguards": "해당 없음",
                "ai_risk": "해당 없음", "risk_source": "미확정 — 시나리오 없음", "risk_name": UNCONFIRMED,
                "decision": DECISION_LABELS["confirm_no_scenario" if nsc else None],
                "decision_reason": (nsc or {}).get("reason") or "미검토",
                "decided_by": (nsc or {}).get("decided_by") or "미검토",
                "decided_at": (nsc or {}).get("decided_at") or "미검토",
                "dics": "해당 없음(설계보완 후보 없음)", "evidence": "해당 없음",
                "holds": "\n".join(["AI 상태: %s" % ai_status_label((c.get("analysis") or {}).get("ai_status"))] +
                                   ["%s %s" % (h["hold_id"], h["item"]) for h in holds]),
                "_decision": "confirm_no_scenario" if nsc else None})
            continue
        for s in scens:
            sid = s["scenario_id"]
            sd = sdecs.get(sid)
            dec = (sd or {}).get("decision")
            if scope == "accepted_modified" and dec not in ("accept", "modify"):
                continue
            merged = rv.merge_display(s, sd)
            rc = (sd or {}).get("risk_confirmation") if dec in ("accept", "modify") else None
            if isinstance(rc, dict) and isinstance(rc.get("risk"), int):
                risk = {"frequency": rc["frequency"], "severity": rc["severity"], "risk": rc["risk"],
                        "risk_source": RISK_SOURCE_LABELS.get(rc.get("source"), rc.get("source")),
                        "risk_name": rc.get("risk_name")}
            else:
                why = {None: "미검토", "defer": "보류 결정(위험도 비움)", "reject": "기각 결정"}.get(dec, "확정값 없음")
                risk = {"frequency": UNCONFIRMED, "severity": UNCONFIRMED, "risk": UNCONFIRMED,
                        "risk_source": "미확정 — %s" % why, "risk_name": UNCONFIRMED}
            dics = [d for d in doc["design_improvement_candidates"] if d["scenario_id"] == sid]
            recs = [ddecs[d["dic_id"]]["recommendation"] for d in dics
                    if (ddecs.get(d["dic_id"]) or {}).get("decision") in ("accept", "modify")]
            pending = [d for d in dics if (ddecs.get(d["dic_id"]) or {}).get("decision") in (None, "defer")]
            dic_lines = ["%s [%s]: %s" % (d["dic_id"],
                                         DECISION_LABELS[(ddecs.get(d["dic_id"]) or {}).get("decision")]
                                         if d["dic_id"] in ddecs else "미확정(미검토)",
                                         "; ".join(TRIGGER_LABELS.get(t, t) for t in d.get("triggers") or []))
                         for d in dics]
            ref = s.get("pattern_ref") or {}
            interp = s.get("ai_interpretation") or {}
            ev = s.get("graph_evidence") or {}
            hold_lines = ["%s %s" % (h["hold_id"], h["item"]) for h in holds_by_scope.get(sid, [])]
            if s.get("status_reason"):
                hold_lines.insert(0, "시나리오 상태 %s: %s" % (s.get("scenario_status"), s["status_reason"]))
            rows.append(dict(risk, **{
                "deviation": c["deviation"], "cause": merged["cause"]["value"],
                "consequence": merged["consequence"]["value"],
                "safeguards": _safeguards_text(merged["safeguards"]["value"], merged["safeguards"]["source"], tags),
                "recommendation": _recommendation_text(recs, pending, dics), "drawings": drawings,
                "candidate_id": cid, "scenario_id": sid, "origin": ORIGIN_LABELS.get(s.get("origin"), s.get("origin")),
                "pattern": "%s v%s" % (ref["pattern_id"], ref.get("pattern_version")) if ref.get("pattern_id")
                else "해당 없음",
                "value_source": rv.value_source_text(merged),
                "ai_safeguards": _safeguards_text(interp.get("safeguards") or [], "ai", tags) if interp
                else "AI 해석 없음",
                "ai_risk": _ai_risk_text(s.get("risk_proposal")),
                "decision": DECISION_LABELS[dec] if dec in DECISION_LABELS else str(dec),
                "decision_reason": (sd or {}).get("reason") or "미검토",
                "decided_by": (sd or {}).get("decided_by") or "미검토",
                "decided_at": (sd or {}).get("decided_at") or "미검토",
                "dics": "\n".join(dic_lines) if dic_lines else "해당 없음(설계보완 후보 없음)",
                "evidence": "\n".join(x for x in ("원인 설비: %s\n근거 ID: %s" % (
                    ", ".join(_tagged(n, tags) for n in s.get("cause_equipment") or []) or "없음",
                    ", ".join(ev.get("evidence_ids") or []) or "없음"), _valve_path_text(doc, s)) if x),
                "holds": "\n".join(hold_lines) if hold_lines else "열린 보류 없음",
                "_decision": dec}))
    return rows


def recommendation_rows(run, records):
    """〈별표9〉 행: 수용·수정한 설계보완 후보만. 위험등급·우선순위는 연결 시나리오의 사람 확정값에서만."""
    doc = run["doc"]
    out = []
    for d in doc["design_improvement_candidates"]:
        rec = records.get(d["candidate_id"])
        sdecs, ddecs = _decisions(rec)
        dd = ddecs.get(d["dic_id"])
        if (dd or {}).get("decision") not in ("accept", "modify"):
            continue
        sd = sdecs.get(d["scenario_id"]) or {}
        rc = sd.get("risk_confirmation") if sd.get("decision") in ("accept", "modify") else None
        risk = rc["risk"] if isinstance(rc, dict) and isinstance(rc.get("risk"), int) else None
        out.append({"dic_id": d["dic_id"], "scenario_id": d["scenario_id"], "candidate_id": d["candidate_id"],
                    "recommendation": dd["recommendation"], "risk": risk,
                    "risk_name": rc.get("risk_name") if risk is not None else None})
    levels = sorted({r["risk"] for r in out if r["risk"] is not None}, reverse=True)
    for r in out:  # 우선순위 = 확정 위험도의 내림차순 순위(같은 위험도는 같은 순위)
        r["priority"] = levels.index(r["risk"]) + 1 if r["risk"] is not None else None
    return out


# ---------------------------------------------------------------- 시트
def _sheet_info(ws, run, records, scope, now, xlsx_rel):
    doc, ar = run["doc"], run["doc"]["analysis_run"]
    v, reg = ar["versions"], ar.get("region") or {}
    crit = v.get("risk_criteria") or {}
    pat = v.get("patterns") or {}
    gs = v.get("graph_source") or {}
    client = ar.get("ai_client") or {}
    val = doc["validation"]
    reviewers = sorted({r.get("reviewer_id") for r in records.values() if r.get("reviewer_id")})
    rows = [
        ("프로젝트 ID", doc.get("project_id") or "미확인(project_id 없음)"),
        ("구간 ID", doc["region_ref"]["region_id"]), ("구간 이름", reg.get("name")),
        ("구간 버전", doc["region_ref"]["region_version"]), ("분석 실행 ID", doc["analysis_run_id"]),
        ("분석 실행 시각(UTC)", ar.get("created_at")),
        ("그래프 ID", doc["graph_ref"]["graph_id"]), ("그래프 버전", doc["graph_ref"]["graph_version"]),
        ("도면번호", gs.get("drawing_number")), ("운전모드", doc.get("operating_mode")),
    ]
    rows += [("입력 파일 해시: %s" % f.get("role"), "%s  sha256=%s" % (f.get("path"), f.get("sha256")))
             for f in ar.get("input_files") or []]
    rows += [
        ("이탈 후보 카탈로그", "%s v%s" % ((v.get("candidate_catalog") or {}).get("id"),
                                       (v.get("candidate_catalog") or {}).get("version"))),
        ("적용 판단", "%s v%s" % ((v.get("applicability") or {}).get("id"), (v.get("applicability") or {}).get("version"))),
        ("원인·결과 패턴", "%s v%s (%s)" % (pat.get("id"), pat.get("version"), pat.get("source"))),
        ("위험도 기준표", "%s / %s" % (crit.get("id"), crit.get("version"))),
        ("AI 응답 출처", "%s %s — %s" % (client.get("type"), client.get("response_dir") or "", client.get("note") or "")),
        ("결과 검증 상태", "%s — %s" % (val.get("status"), val.get("note"))),
        ("analysis.json SHA-256", run["analysis_sha256"]),
        ("출력 시각", "%s (KST 날짜 %s)" % (now, kst_date(now))), ("출력 범위", SCOPES[scope]),
        ("필터", "없음(출력 범위만 적용)"), ("출력 파일", xlsx_rel),
        ("검토자", ", ".join(reviewers) if reviewers else "검토 기록 없음"),
        ("검토 기록", "편차 %d건(최신 버전 기준)" % len(records)),
        ("위험도 열 규칙", "〈별표7〉 5–7열은 사람 확정값만. AI 제안은 'AI 위험도 제안' 열에만 표시"),
    ]
    _table(ws, 1, ("항목", "값"), rows)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 100


def _sheet_candidates(ws, run, records):
    doc = run["doc"]
    summ = rv.review_summary(doc, records)
    rows = []
    for c in doc["candidates"]:
        cid = c["candidate_id"]
        if cid in summ["by_candidate"]:
            st = "%s (%s)" % (STATUS_LABELS[summ["by_candidate"][cid]], summ["by_candidate"][cid])
        elif c["selection_status"] == "excluded":
            st = "판정 제외(제외 후보)"
        else:
            st = "판정 제외(판단 보류 후보)"
        gw = c.get("guide_word_ko") + (" (%s)" % c["guide_word_en"] if c.get("guide_word_en") else "")
        rows.append((cid, c.get("item_id"), c.get("parameter_ko"), gw, c.get("deviation"),
                     SELECTION_LABELS.get(c["selection_status"], c["selection_status"]), c.get("reason"), st))
    _table(ws, 1, ("편차 ID", "항목 ID", "파라미터", "가이드워드", "편차", "판단", "판단 사유", "검토 상태"), rows)
    for col, w in zip("ABCDEFGH", (22, 10, 10, 14, 18, 8, 50, 22)):
        ws.column_dimensions[col].width = w


def _sheet_worksheet(ws, run, records, rows):
    doc = run["doc"]
    reg = doc["analysis_run"].get("region") or {}
    dates = [r["reviewed_at"] for r in records.values() if r.get("reviewed_at")]
    _put(ws, 1, 1, "위험성평가 결과 기록지 (KOSHA GUIDE P-86-2017 〈별표7〉 기준)", bold=True)
    head = (("공정", reg.get("name")),
            ("검토일", kst_date(max(dates)) if dates else "미검토(검토 기록 없음)"),
            ("도면", (doc["analysis_run"]["versions"].get("graph_source") or {}).get("drawing_number")),
            ("쪽", "인쇄 머리글에 표시(쪽 번호/전체)"), ("검토구간", doc["region_ref"]["region_id"]))
    for i, (k, v) in enumerate(head):
        _put(ws, 2, 2 * i + 1, k, bold=True)
        _put(ws, 2, 2 * i + 2, v)
    _put(ws, 3, 1, "위험도(5–7열)는 사람 확정값만 씀. AI 제안은 'AI 위험도 제안' 열. 2–4열의 값 출처는 '값 출처' 열, "
                   "미검토·보류·기각 행의 2–4열은 사람이 확인하지 않은 원안임")
    for i, (key, h, sub) in enumerate(WORKSHEET_COLUMNS, 1):
        if sub is None:
            _put(ws, HEADER_ROW, i, h, bold=True)
            ws.merge_cells(start_row=HEADER_ROW, start_column=i, end_row=SUBHEADER_ROW, end_column=i)
        else:
            _put(ws, SUBHEADER_ROW, i, sub, bold=True)
    risk_cols = [i for i, c in enumerate(WORKSHEET_COLUMNS, 1) if c[2]]
    _put(ws, HEADER_ROW, risk_cols[0], "위험도", bold=True)
    ws.merge_cells(start_row=HEADER_ROW, start_column=risk_cols[0], end_row=HEADER_ROW, end_column=risk_cols[-1])
    for r, row in enumerate(rows, FIRST_DATA_ROW):
        for c, (key, _h, _s) in enumerate(WORKSHEET_COLUMNS, 1):
            _put(ws, r, c, row[key])
    widths = {"deviation": 14, "cause": 36, "consequence": 36, "safeguards": 40, "frequency": 8, "severity": 8,
              "risk": 8, "recommendation": 30, "drawings": 16}
    for i, (key, _h, _s) in enumerate(WORKSHEET_COLUMNS, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = widths.get(key, 24)
    ws.print_title_rows = "%d:%d" % (HEADER_ROW, SUBHEADER_ROW)
    ws.page_setup.orientation = "landscape"
    ws.oddHeader.right.text = "&P/&N"
    ws.freeze_panes = ws.cell(row=FIRST_DATA_ROW, column=2)


def _sheet_dics(ws, run, records):
    doc = run["doc"]
    rows = []
    for d in doc["design_improvement_candidates"]:
        _s, ddecs = _decisions(records.get(d["candidate_id"]))
        dd = ddecs.get(d["dic_id"])
        trig = "; ".join(TRIGGER_LABELS.get(t, t) for t in d.get("triggers") or [])
        desc = ((dd or {}).get("revised") or {}).get("trigger_description")
        if desc:
            trig += "\n[검토자 수정] %s" % desc
        rows.append((d["dic_id"], d["scenario_id"], d["candidate_id"], trig, d.get("cause"), d.get("consequence"),
                     DECISION_LABELS.get((dd or {}).get("decision"), (dd or {}).get("decision")) if dd
                     else "미확정(미검토)",
                     (dd or {}).get("reason") or "미검토", (dd or {}).get("decided_by") or "미검토",
                     (dd or {}).get("decided_at") or "미검토"))
    _table(ws, 1, ("설계보완 후보 ID", "시나리오 ID", "편차 ID", "발생 조건", "원인", "결과", "결정", "사유",
                   "검토자", "결정 시각(UTC)"), rows)
    for col, w in zip("ABCDEFGHIJ", (28, 22, 20, 40, 36, 36, 18, 30, 12, 22)):
        ws.column_dimensions[col].width = w


def _sheet_recommendations(ws, rec_rows):
    rows = []
    for n, r in enumerate(rec_rows, 1):
        note = "설계보완 후보 %s · 시나리오 %s · 편차 %s · 조치 action-%s" % (
            r["dic_id"], r["scenario_id"], r["candidate_id"], r["dic_id"])
        if r["risk"] is not None:
            note += " · 위험등급명 %s(사람 확정)" % r["risk_name"]
        else:
            note += " · 연결 시나리오의 사람 확정 위험도 없음"
        rows.append((n, r["priority"] if r["priority"] is not None else UNCONFIRMED,
                     r["risk"] if r["risk"] is not None else UNCONFIRMED, r["recommendation"],
                     NOT_MANAGED, NOT_MANAGED, NOT_MANAGED, NOT_MANAGED, note))
    _table(ws, 1, RECOMMENDATION_COLUMNS, rows)
    for col, w in zip("ABCDEFGHI", (6, 10, 10, 50, 12, 12, 12, 12, 60)):
        ws.column_dimensions[col].width = w
    ws.page_setup.orientation = "landscape"
    ws.oddHeader.right.text = "&P/&N"


def _sheet_memos(ws, run, records):
    memos = []
    for cid, rec in sorted(records.items()):
        for m in rec.get("memo_records") or []:
            memos.append((m.get("memo_id"), cid, ", ".join(m.get("hold_ids") or []) or "없음", m.get("content"),
                          m.get("reason"), m.get("created_by"), m.get("created_at")))
    last = _table(ws, 1, ("메모 ID", "관련 편차 ID", "관련 보류 ID", "요청 내용", "사유", "작성자", "작성 시각(UTC)"),
                  memos)
    holds = [(h["hold_id"], h.get("candidate_id") or "구간 전체", h.get("scope"), h.get("item"), h.get("reason"),
              h.get("request"), h.get("source"), h.get("status"))
             for h in run["doc"]["holds"] if h.get("status") == "open"]
    _put(ws, last + 2, 1, "분석의 열린 보류 (analysis.json holds)", bold=True)
    _table(ws, last + 3, ("보류 ID", "편차 ID", "범위", "항목", "사유", "요청 자료", "출처", "상태"), holds)
    for col, w in zip("ABCDEFGH", (14, 22, 22, 30, 40, 40, 16, 10)):
        ws.column_dimensions[col].width = w


# ---------------------------------------------------------------- 공개 API
def export_worksheet(run_dir, store_root, out_root, scope="all", now=None, node=None):
    """분석 실행과 그 검토 기록으로 Excel 워크시트를 새로 만든다.

    run_dir: 분석 실행 폴더(analysis.json). store_root: 검토 기록 저장 루트(<store_root>/reviews/...).
    out_root: 워크시트 출력 루트(기본 사용처는 <작업 루트>/출력/워크시트). scope: "all"(기본) 또는 "accepted_modified".
    now: 출력 시각(UTC ISO 'YYYY-MM-DDTHH:MM:SSZ', 기본 현재). 파일 이름과 출력 기록 이름에 쓴다.
    node: '도면 번호' 열에 쓸 검토구간(span.annotate 사본, 여러 도면에 걸친 구간). 없으면 분석 실행의 도면.
    반환 {"path", "export_record_path", "record"}. 차단·같은 이름 파일 있음이면 ExportError(아무 파일도 만들지 않음),
    analysis.json이 없으면 ReviewError."""
    from openpyxl import Workbook
    from openpyxl.utils.exceptions import IllegalCharacterError
    if scope not in SCOPES:
        raise ExportError("출력 범위는 %s 중 하나: %r" % (", ".join(SCOPES), scope))
    now = now or rv.utc_now()
    if not isinstance(now, str) or not _UTC.match(now):
        raise ExportError("출력 시각이 UTC ISO 형식 아님: %r" % (now,))
    run = rv.open_run(run_dir)
    doc = run["doc"]
    region_id, run_id = doc["region_ref"]["region_id"], doc["analysis_run_id"]
    records = rv.load_run_reviews(store_root, region_id, run_id)
    reasons = _check_exportable(run, records)
    if reasons:
        raise ExportError(["출력 차단: %s" % r for r in reasons])

    stamp = now.replace("-", "").replace(":", "")
    out_dir = paths.safe_join(paths.safe_join(out_root, store.path_component(region_id, "region_id")),
                              store.path_component(run_id, "analysis_run_id"))
    xlsx_path = os.path.join(out_dir, "worksheet-%s.xlsx" % stamp)
    exp_dir = rv.review_dir(store_root, region_id, run_id, "exports")
    exp_path = os.path.join(exp_dir, "%s.json" % stamp)
    for p in (xlsx_path, exp_path):
        if os.path.exists(p):
            raise ExportError("같은 이름의 파일이 이미 있음(덮어쓰지 않음): %s" % p)
    xlsx_rel = paths.rel_or_abs(xlsx_path, paths.work_root())

    ws_rows = worksheet_rows(run, records, scope, node)
    rec_rows = recommendation_rows(run, records)
    wb = Workbook()
    sheets = [wb.active] + [wb.create_sheet() for _ in SHEETS[1:]]
    for ws, title in zip(sheets, SHEETS):
        ws.title = title
    try:
        _sheet_info(sheets[0], run, records, scope, now, paths.plain_rel(xlsx_path, paths.work_root()))
        _sheet_candidates(sheets[1], run, records)
        _sheet_worksheet(sheets[2], run, records, ws_rows)
        _sheet_dics(sheets[3], run, records)
        _sheet_recommendations(sheets[4], rec_rows)
        _sheet_memos(sheets[5], run, records)
    except IllegalCharacterError as exc:
        raise ExportError("출력 차단: Excel에 쓸 수 없는 제어문자가 있는 값(%s) — 원본 값을 확인해야 함" % exc)
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()

    if rv.file_sha256(run["analysis_path"]) != run["analysis_sha256"]:
        raise ExportError("출력 차단: analysis.json이 연 뒤에 바뀜 — 다시 열어야 함")
    record = {
        "schema_version": "0.1", "export_id": "export-%s" % stamp, "exported_at": now,
        "scope": scope, "scope_label": SCOPES[scope], "filter": None,
        "file": xlsx_rel, "file_sha256": hashlib.sha256(data).hexdigest(),
        "target": {"analysis_run_id": run_id, "analysis_sha256": run["analysis_sha256"],
                   "region_ref": doc["region_ref"], "graph_ref": doc["graph_ref"],
                   "reviews": [{"candidate_id": cid, "review_version": r.get("review_version"),
                                "review_status": r.get("review_status")} for cid, r in sorted(records.items())]},
        "rows": {
            "worksheet": [{"row": FIRST_DATA_ROW + i, "candidate_id": r["candidate_id"],
                           "scenario_id": None if r["scenario_id"] == NO_SCENARIO else r["scenario_id"],
                           "decision": r["_decision"]} for i, r in enumerate(ws_rows)],
            "recommendations": [{"no": n, "dic_id": r["dic_id"], "scenario_id": r["scenario_id"],
                                 "candidate_id": r["candidate_id"]} for n, r in enumerate(rec_rows, 1)],
        },
    }
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(exp_dir, exist_ok=True)
    try:  # 같은 폴더 임시 파일에 다 쓴 뒤 최종 이름을 배타적으로 만든다(덮어쓰지 않음)
        store.write_exclusive(xlsx_path, data)
    except rv.ReviewError as exc:
        raise ExportError(exc.errors)
    except OSError as exc:
        raise ExportError("워크시트 파일 쓰기 실패: %s" % exc)
    try:
        store.write_exclusive(exp_path, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (rv.ReviewError, OSError) as exc:
        os.remove(xlsx_path)  # 출력 기록이 없는 워크시트를 남기지 않음 — 같은 시각으로 다시 출력할 수 있음
        raise ExportError("출력 기록 쓰기 실패 — 워크시트 파일을 지움: %s" % exc)
    return {"path": xlsx_path, "export_record_path": exp_path, "record": record}
