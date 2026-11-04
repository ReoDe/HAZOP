"""④ 위험도 제안 계산 (기획서/HAZOP기법지침.md §6, §8.3).

AI는 강도(severity)·발생빈도(frequency)를 제안만 하고, Python이 〈표5〉 조회로 위험도를 계산한다.
- 기준표가 없으면 보류(deferred). 임의 등급을 만들지 않는다.
- 허용값 밖이면 보류.
- 빈도 감소(보호수단 반영)는 인정한 보호수단이 모두 '적정성 확인(confirmed)'일 때만 적용한다.
  그래프에 존재만 확인된 보호수단은 독립성·용량·작동 적정성이 미확인이므로 감소를 반영하지 않는다.
- 결과는 proposed이며 확정값이 아니다(확정은 ⑤).
"""

SEVERITIES = (1, 2, 3, 4)
FREQUENCIES = (1, 2, 3)
# 〈표5〉 위험도 대조표(KOSHA P-86-2017 예시)를 기준표 파일과 독립적으로 코드에 고정한 값. 행: 강도, 열: 발생빈도.
# 기준표 파일의 무결성 검사(integrity.check_criteria)와 결과 검증(run.check_result)이 이 값과 대조한다.
MATRIX_P86 = {4: {3: 5, 2: 5, 1: 3}, 3: {3: 4, 2: 4, 1: 2}, 2: {3: 3, 2: 2, 1: 1}, 1: {3: 2, 2: 1, 1: 1}}


def lookup(criteria, severity, frequency):
    """〈표5〉 조회. 곱셈·덧셈이 아니다."""
    return criteria["matrix"][str(severity)][str(frequency)]


def deferred(reason, criteria=None):
    return {"status": "deferred", "reason": reason,
            "criteria_id": criteria["criteria_id"] if criteria else None,
            "criteria_version": criteria["criteria_version"] if criteria else None,
            "severity": None, "frequency_used": None, "risk": None, "confirmed": False}


def evaluate(criteria, ai_risk, safeguard_status, evidence_ids=None):
    """ai_risk: AI 응답의 risk 객체. safeguard_status: 노드 ID -> {'adequacy': 'confirmed'|'unknown', ...}.
    evidence_ids: 시나리오가 인용한 근거 ID. 비었거나 강도·빈도 근거 문장이 비었으면 제안하지 않고 보류."""
    if not criteria:
        return deferred("위험도 기준표 없음 — 임의 등급을 만들지 않음")
    if not ai_risk:
        return deferred("AI 강도·빈도 제안 없음", criteria)
    if not evidence_ids:
        return deferred("시나리오 근거 ID(evidence_ids) 없음 — 위험도 제안하지 않음", criteria)
    if not str(ai_risk.get("severity_basis") or "").strip() or not str(ai_risk.get("frequency_basis") or "").strip():
        return deferred("강도 또는 빈도 판단 근거 문장 없음 — 위험도 제안하지 않음", criteria)
    sev = ai_risk.get("severity")
    f0 = ai_risk.get("frequency_without_safeguards")
    f1 = ai_risk.get("frequency_with_safeguards")
    if sev is None or f0 is None:
        return dict(deferred("판단 근거 부족으로 AI가 강도 또는 빈도를 제안하지 않음", criteria),
                    ai_basis={"severity_basis": ai_risk.get("severity_basis"),
                              "frequency_basis": ai_risk.get("frequency_basis")})
    def ok(v, allowed):
        return type(v) is int and v in allowed
    if not ok(sev, SEVERITIES) or not ok(f0, FREQUENCIES) or (f1 is not None and not ok(f1, FREQUENCIES)):
        return deferred("허용값 아님(severity %r, frequency %r/%r)" % (sev, f0, f1), criteria)
    credited = list(ai_risk.get("credited_safeguard_node_ids") or [])
    if f1 is None or f1 >= f0:
        used, applied = f0, False
        credit_reason = "보호수단에 의한 빈도 감소 제안 없음"
    elif not credited:
        used, applied = f0, False
        credit_reason = "빈도 감소를 제안했으나 인정한 보호수단 지정 없음 — 감소 미반영"
    else:
        unconfirmed = [n for n in credited if (safeguard_status.get(n) or {}).get("adequacy") != "confirmed"]
        if unconfirmed:
            used, applied = f0, False
            credit_reason = ("보호수단 미확인(%s: 그래프에 존재만 확인, 독립성·용량·작동 적정성 미확인) — "
                             "빈도 감소 미반영(사용자 결정 2026-11-04)" % ", ".join(unconfirmed))
        else:
            used, applied = f1, True
            credit_reason = "인정한 보호수단 모두 적정성 확인됨 — 빈도 감소 반영"
    risk = lookup(criteria, sev, used)
    level = criteria["risk_levels"][str(risk)]
    return {"status": "proposed", "confirmed": False,
            "criteria_id": criteria["criteria_id"], "criteria_version": criteria["criteria_version"],
            "severity": sev, "severity_basis": ai_risk.get("severity_basis"),
            "frequency_without_safeguards": f0, "frequency_with_safeguards_ai": f1,
            "credited_safeguard_node_ids": credited, "safeguard_credit_applied": applied,
            "safeguard_credit_reason": credit_reason, "frequency_used": used,
            "frequency_basis": ai_risk.get("frequency_basis"),
            "risk": risk, "risk_name": level["name"], "management": level["management"],
            "acceptance": level["acceptance"], "acceptance_note": criteria.get("acceptance_note"),
            "calculation": "표5 조회: matrix[severity=%d][frequency=%d] = %d" % (sev, used, risk),
            "assumptions": list(ai_risk.get("assumptions") or []), "uncertainty": ai_risk.get("uncertainty"),
            "note": "AI 제안 + Python 기준표 조회. 확정값 아님(⑤에서 사람이 확정)"}
