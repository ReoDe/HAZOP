"""표시용 병합 (기획서/인터페이스.md §6.2 '2–4열 병합 규칙'). ⑤ 화면 재조회와 Excel 2–4열이 같은 함수를 쓴다.

필드마다 따로 적용한다.
- cause, consequence: revised의 같은 필드 → ai_interpretation의 같은 필드(있으면) → 패턴 원안(scenarios[].cause·consequence)
- safeguards: revised.safeguards(키가 있으면) → 그래프 확인 보호수단
  그래프 확인 보호수단은 패턴 시나리오(origin: pattern)의 scenarios[].safeguards뿐이다. AI 추가 가설
  (ai_additional_hypothesis)의 scenarios[].safeguards는 AI가 제시한 보호수단이므로 넣지 않고 빈 목록으로 둔다
  (§6.2, 총괄 판정 2026-11-04). AI 제시 보호수단(ai_interpretation.safeguards)은 safeguards 값에 넣지 않는다
  (Excel 'AI 제시 보호수단' 열 몫).
"""

SOURCE_REVISED = "revised"            # 사람 수정
SOURCE_AI = "ai_interpretation"       # AI 해석 원안
SOURCE_PATTERN = "pattern"            # 패턴 원안
SOURCE_GRAPH = "graph"                # 그래프 확인 보호수단
SOURCE_LABELS = {SOURCE_REVISED: "사람 수정", SOURCE_AI: "AI 해석 원안", SOURCE_PATTERN: "패턴 원안",
                 SOURCE_GRAPH: "그래프 확인"}


def _present(v):
    return v is not None and not (isinstance(v, str) and not v.strip())


def merge_display(scenario, scenario_decision=None):
    """시나리오 표시값과 필드별 값 출처. scenario: analysis.json의 scenarios[] 항목,
    scenario_decision: 검토본의 scenario_decisions[] 항목(없으면 None).
    반환 {"cause": {"value", "source"}, "consequence": {...}, "safeguards": {...}}.
    source는 revised·ai_interpretation·pattern·graph 중 하나(SOURCE_LABELS로 한국어 표시)."""
    revised = (scenario_decision or {}).get("revised") or {}
    interp = scenario.get("ai_interpretation") or {}
    out = {}
    for key in ("cause", "consequence"):
        if key in revised:
            out[key] = {"value": revised[key], "source": SOURCE_REVISED}
        elif _present(interp.get(key)):
            out[key] = {"value": interp[key], "source": SOURCE_AI}
        else:
            out[key] = {"value": scenario.get(key), "source": SOURCE_PATTERN}
    if "safeguards" in revised:
        out["safeguards"] = {"value": revised["safeguards"], "source": SOURCE_REVISED}
    else:
        pattern = scenario.get("origin") == "pattern"  # 패턴 시나리오만 그래프 확인 보호수단이 있음
        out["safeguards"] = {"value": (scenario.get("safeguards") or []) if pattern else [], "source": SOURCE_GRAPH}
    return out


def value_source_text(merged):
    """값 출처 한 줄 표시. 예: "원인=AI 해석 원안, 결과=사람 수정, 현재안전조치=그래프 확인"."""
    names = (("cause", "원인"), ("consequence", "결과"), ("safeguards", "현재안전조치"))
    return ", ".join("%s=%s" % (label, SOURCE_LABELS[merged[k]["source"]]) for k, label in names)
