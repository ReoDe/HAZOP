"""④⑤ 상세 패널 HTML(QTextBrowser). AI 산출은 점선·회색 상자와 '제안' 칩, 사람 확정은 흰 바탕 실선 상자."""

from hazop.app import data
from hazop.app.widgets import badge, box, esc, risk_chip

SCENARIO_STATUS = {"draft": "초안", "on_hold": "보류"}
ORIGIN = {"pattern": "패턴", "ai_additional_hypothesis": "AI 추가 가설"}


def tags_of(graph):
    return {n["entity_id"]: n.get("tag") for n in (graph or {}).get("nodes", [])}


def tag_list(ids, tags):
    return ", ".join("%s" % esc(tags.get(i) or i) for i in ids or []) or "<span style='color:#92400e'>미확인</span>"


def safeguard_rows(items, tags):
    if not items:
        return "<span style='color:#92400e'>그래프에서 찾지 못함(없음이 아니라 미확인)</span>"
    rows = []
    for g in items:
        adequacy = "적정성 미확인" if g.get("adequacy") in (None, "unknown") else "적정성 %s" % g.get("adequacy")
        rows.append("<li><b>%s</b> %s — %s · 존재 %s · %s%s</li>" % (
            esc(g.get("tag") or tags.get(g.get("node_id")) or g.get("node_id")), esc(g.get("kind") or ""),
            esc(g.get("description") or ""), esc(g.get("existence") or "미확인"), esc(adequacy),
            "" if g.get("counts_as_found", True) else " · " + badge("미계수", "plain")))
    return "<ul style='margin:2px 0 2px -20px'>%s</ul>" % "".join(rows)


def risk_proposal_html(rp):
    if not rp:
        return "<span style='color:#92400e'>위험도 제안 없음(미확인)</span>"
    if rp.get("status") != "proposed":
        return "%s 상태 %s — 사유: %s · 등급 <b>보류</b>" % (badge("[AI] 제안", "ai"), esc(rp.get("status")),
                                                         esc(rp.get("reason") or rp.get("hold_reason") or rp.get("note")))
    h = "%s 강도 %s · 빈도 %s → %s<br>" % (badge("[AI] 제안", "ai"), esc(rp.get("severity")), esc(rp.get("frequency_used")),
                                          risk_chip(rp.get("risk"), rp.get("risk_name"), proposal=True))
    h += "<small>관리기준: %s<br>계산: %s<br>보호수단 반영: %s — %s<br>강도 근거: %s<br>빈도 근거: %s<br>가정: %s · 불확실성: %s</small>" % (
        esc(rp.get("management")), esc(rp.get("calculation")), "예" if rp.get("safeguard_credit_applied") else "아니오",
        esc(rp.get("safeguard_credit_reason")), esc(rp.get("severity_basis")), esc(rp.get("frequency_basis")),
        esc("; ".join(rp.get("assumptions") or []) or "없음"), esc(rp.get("uncertainty") or "미확인"))
    return h


def scenario_html(doc, s, tags, review_status=None, evidence=None):
    """시나리오 카드(§3.3). 패턴 원안과 AI 해석, 그래프 확인 보호수단과 AI 제시 보호수단을 나눠 보여 준다."""
    h = ["<p><b>%s</b> %s %s %s</p>" % (
        esc(s["scenario_id"]), badge(ORIGIN.get(s.get("origin"), s.get("origin")), "ai" if s.get("origin") != "pattern" else "plain"),
        badge("가설", "plain") if s.get("knowledge_status") == "hypothesis" else "",
        badge(SCENARIO_STATUS.get(s.get("scenario_status"), s.get("scenario_status") or ""), "warn"
              if s.get("scenario_status") == "on_hold" else "plain"))]
    if s.get("status_reason"):
        h.append("<p>상태 사유: %s</p>" % esc(s["status_reason"]))
    if review_status:
        h.append("<p>검토 상태: %s</p>" % esc(data.STATUS_LABELS.get(review_status, review_status)))
    if s.get("origin") == "pattern":
        ref = s.get("pattern_ref") or {}
        h.append(box("<b>패턴 원안</b> <small>(%s v%s)</small><br>원인: %s<br>결과: %s" % (
            esc(ref.get("pattern_id")), esc(ref.get("pattern_version")), esc(s.get("cause")), esc(s.get("consequence"))), "ai"))
    ai = s.get("ai_interpretation")
    if ai:
        h.append(box("%s <b>AI 해석</b><br>원인: %s<br>결과: %s<br><small>%s</small>" % (
            badge("[AI] 제안", "ai"), esc(ai.get("cause")), esc(ai.get("consequence")), esc(ai.get("interpretation"))), "ai"))
    elif s.get("origin") != "pattern":
        h.append(box("%s 원인: %s<br>결과: %s" % (badge("[AI] 추가 가설", "ai"), esc(s.get("cause")), esc(s.get("consequence"))), "ai"))
    h.append("<p>원인 설비: %s<br>전제 설비: %s</p>" % (tag_list(s.get("cause_equipment"), tags),
                                                tag_list(s.get("assumed_equipment"), tags)))
    nc = s.get("narrative_check") or {}
    if nc.get("limit"):
        h.append("<p><small>서술 검사 한계: %s</small></p>" % esc(nc["limit"]))
    pc = s.get("path_context")
    if pc:
        h.append("<p><small>경로 문맥: %s</small></p>" % esc(", ".join("%s=%s" % (k, v) for k, v in pc.items())))
    graph_sg = s.get("safeguards") if s.get("origin") == "pattern" else []
    h.append("<p><b>보호수단 — 그래프에서 확인</b>%s</p>" % safeguard_rows(graph_sg, tags))
    if ai and ai.get("safeguards"):
        h.append("<p><b>보호수단 — AI 제시</b> %s%s</p>" % (badge("[AI] 제안", "ai"), safeguard_rows(ai["safeguards"], tags)))
    h.append("<p><b>위험도 제안</b><br>%s</p>" % risk_proposal_html(s.get("risk_proposal")))
    ge = s.get("graph_evidence") or {}
    h.append("<p><small>근거 ID: %s</small></p>" % esc(", ".join(
        (ge.get("evidence_ids") or []) + (ge.get("node_ids") or []) + (ge.get("relation_ids") or [])) or "없음"))
    if evidence:
        h.append("<p><small>%s</small></p>" % esc(data.evidence_text(evidence)))
    return "".join(h)


def dic_html(d, holds_by_id):
    b = d.get("basis") or {}
    trig = "<br>".join(esc(data.TRIGGER_LABELS.get(t, t)) for t in d.get("triggers") or [])
    inner = "<b>%s</b> %s %s<br>발생 조건: %s<br>원인: %s<br>결과: %s<br>근거 위험도: %s<br><small>%s</small>" % (
        esc(d["dic_id"]), badge("원안", "plain"), badge("미확정", "warn"), trig, esc(d.get("cause")), esc(d.get("consequence")),
        risk_chip(b.get("risk"), b.get("risk_name"), proposal=True) if b.get("risk") is not None else "미확인",
        esc(d.get("note")))
    if d.get("hold_ids"):
        inner += "<br>자료 요청: %s" % esc(", ".join("%s(%s)" % (h, (holds_by_id.get(h) or {}).get("item")) for h in d["hold_ids"]))
    return box(inner, "ai")


def holds_html(holds):
    if not holds:
        return "<p style='color:#6b7280'>열린 자료 요청 없음</p>"
    return "".join("<p><b>%s</b> %s · %s<br>사유: %s<br>요청 자료: %s<br><small>출처 %s · 범위 %s</small></p>" % (
        esc(h["hold_id"]), esc(h.get("item")), badge("열림" if h.get("status") == "open" else "닫힘",
                                                      "warn" if h.get("status") == "open" else "plain"),
        esc(h.get("reason")), esc(h.get("request")), esc(h.get("source")), esc(h.get("scope"))) for h in holds)


def ai_runs_html(doc, cand):
    an = cand.get("analysis") or {}
    runs = [r for r in doc.get("ai_runs") or [] if r.get("candidate_id") == cand["candidate_id"]]
    h = ["<p>AI 상태: <b>%s</b></p>" % esc(data.AI_STATUS_LABELS.get(an.get("ai_status"), an.get("ai_status") or "미요청"))]
    for r in runs:
        v = r.get("validation") or {}
        cl = r.get("client") or {}
        h.append("<p><b>%s</b> 시도 %s · 상태 %s<br>응답 출처: %s (%s)<br>검증: %s<br>오류: %s<br>경고: %s</p>" % (
            esc(r.get("ai_run_id")), esc(r.get("attempt")), esc(r.get("status")), esc(cl.get("type")),
            esc(cl.get("response_dir")), esc(v.get("status") if isinstance(v, dict) else v),
            esc("; ".join((v.get("errors") or []) if isinstance(v, dict) else []) or "없음"),
            esc("; ".join(str(w) for w in r.get("warnings") or []) or "없음")))
    for rej in an.get("rejected_ai_scenarios") or []:
        h.append(box("%s 거부된 AI 가설: %s<br>사유: %s" % (badge("[AI] 거부", "err"), esc(rej.get("cause") or rej.get("scenario")),
                                                       esc(rej.get("reason") or rej.get("rejected_reason"))), "ai"))
    return "".join(h)
