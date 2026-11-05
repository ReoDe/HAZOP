"""이전 실행 검토 대응·가져오기 (기획서/인터페이스.md §5.3).

- 새 실행에는 이전 확정 결과를 자동으로 넘기지 않는다. 사람이 항목별로 '가져오기'를 눌러야 한다.
- 대응키: 패턴 시나리오 pattern_ref.match_id, AI 추가 가설 scenario_id. cause_group은 쓰지 않는다.
  설계보완 후보는 연결 시나리오의 대응키, '시나리오 없음 확인'은 candidate_id로 대응한다.
- 대응 0개=대응 없음(가져오기 없음), 1개=가져오기 가능, 2개 이상=대상을 고르지 않으면 차단.
- 가져온 결정도 사유·검토자·시각을 새로 기록하고 imported_from을 남긴다.
"""

import os

from hazop import paths
from hazop.review import store
from hazop.review.record import (_dic, _scenario, dic_decision, no_scenario_confirmation, scenario_decision,
                                 scenario_match_key)
from hazop.review.store import ReviewError


def find_prior_reviews(store_root, region_id, current_run_id, candidate_id):
    """같은 구간의 다른 실행에서 같은 candidate_id의 최신 검토본 목록.
    최신 검토본의 reviewed_at이 늦은 순(같으면 실행 ID 역순). 첫 항목이 기본 표시 대상.
    반환 [{"analysis_run_id", "review_version", "record"}]."""
    region_dir = paths.safe_join(paths.safe_join(store_root, store.REVIEWS_DIR), store.path_component(region_id, "region_id"))
    if not os.path.isdir(region_dir):
        return []
    out = []
    for run_id in os.listdir(region_dir):
        if run_id == current_run_id or not os.path.isdir(os.path.join(region_dir, run_id)):
            continue
        rec = store.load_review(store_root, region_id, run_id, candidate_id)
        if rec is not None:
            out.append({"analysis_run_id": run_id, "review_version": rec["review_version"], "record": rec})
    out.sort(key=lambda x: (x["record"].get("reviewed_at") or "", x["analysis_run_id"]), reverse=True)
    return out


def match_scenario(prior_record, scenario):
    """현재 시나리오에 대응하는 이전 시나리오 결정 목록(0·1·2개 이상)."""
    key = scenario_match_key(scenario)
    return [d for d in prior_record.get("scenario_decisions") or []
            if (d.get("ai_original") or {}).get("match_key") == key]


def match_dic(prior_record, doc, dic):
    """현재 설계보완 후보에 대응하는 이전 결정 목록(연결 시나리오 대응키 기준). not_applicable은 자동값이라 제외."""
    key = scenario_match_key(_scenario(doc, dic["scenario_id"]))
    return [d for d in prior_record.get("design_improvement_decisions") or []
            if (d.get("ai_original") or {}).get("scenario_match_key") == key and d.get("decision") != "not_applicable"]


def match_status(matches):
    """대응 수에 따른 표시: none(대응 없음)·single(가져오기 가능)·multiple(대상 선택 필요)."""
    return "none" if not matches else ("single" if len(matches) == 1 else "multiple")


def _pick(matches, choice, id_key, label):
    if not matches:
        raise ReviewError("%s: 이전 검토에 대응 없음 — 가져오기 없음" % label)
    if len(matches) > 1:
        if choice is None:
            raise ReviewError("%s: 이전 검토 대응이 %d개 — 가져올 대상을 골라야 함" % (label, len(matches)))
        picked = [m for m in matches if m.get(id_key) == choice]
        if len(picked) != 1:
            raise ReviewError("%s: 고른 대상 %r가 대응 목록에 없음" % (label, choice))
        return picked[0]
    if choice is not None and matches[0].get(id_key) != choice:
        raise ReviewError("%s: 고른 대상 %r가 대응 목록에 없음" % (label, choice))
    return matches[0]


def _imported(prior, key, value):
    return {"analysis_run_id": prior["analysis_run_id"], "review_version": prior["review_version"], key: value}


def import_scenario_decision(run, scenario_id, prior, reason, reviewer_id, choice=None, now=None):
    """이전 시나리오 결정을 현재 실행 결정으로 가져온다. choice: 대응이 2개 이상일 때 고른 이전 scenario_id.
    결정·revised·위험도 입력값은 복사하고 ai_original·사유·검토자·시각은 새로 만든다(위험도는 현재 기준표로 재검사)."""
    sc = _scenario(run["doc"], scenario_id)
    src = _pick(match_scenario(prior["record"], sc), choice, "scenario_id", scenario_id)
    return scenario_decision(run, scenario_id, src["decision"], reason, reviewer_id, revised=src.get("revised"),
                             risk_confirmation=src.get("risk_confirmation"),
                             imported_from=_imported(prior, "scenario_id", src["scenario_id"]), now=now)


def import_dic_decision(run, dic_id, prior, reason, reviewer_id, choice=None, now=None):
    """이전 설계보완 후보 결정을 가져온다. choice: 대응이 2개 이상일 때 고른 이전 dic_id."""
    dic = _dic(run["doc"], dic_id)
    src = _pick(match_dic(prior["record"], run["doc"], dic), choice, "dic_id", dic_id)
    return dic_decision(run, dic_id, src["decision"], reason, reviewer_id, recommendation=src.get("recommendation"),
                        revised=src.get("revised"), imported_from=_imported(prior, "dic_id", src["dic_id"]), now=now)


def import_no_scenario_confirmation(prior, reason, reviewer_id, now=None):
    """이전 '시나리오 없음 확인'을 가져온다(candidate_id 대응). 이전 기록에 없으면 ReviewError."""
    if not (prior["record"].get("no_scenario_confirmation")):
        raise ReviewError("이전 검토에 '시나리오 없음 확인' 없음 — 가져오기 없음")
    return no_scenario_confirmation(reason, reviewer_id, now=now,
                                    imported_from={"analysis_run_id": prior["analysis_run_id"],
                                                   "review_version": prior["review_version"]})
