"""④ 후보 판단 변경(기획서/인터페이스.md §3.3 '후보 판단 변경').

구간 JSON의 candidate_decisions에 항목을 덧붙이기만 하고(이전 항목은 고치거나 지우지 않음), region_version을 1 올려
구간 JSON 전체를 다시 쓴다(run.write_region: 임시 파일에 쓴 뒤 교체). 열려 있는 analysis.json과 실행 폴더는 건드리지 않는다.
항목 형식은 hazop/analysis/candidates.py가 읽는 candidate_id·selection_status·decided_by·reason·decided_at.
저장 전에 candidates.build_candidates로 같은 규칙을 적용해 재분석 때 읽히는 항목인지 확인한다.
"""

import copy
import json
import os

from hazop import paths

from . import candidates as cand_mod, run

REANALYZE_NOTICE = "변경을 반영하려면 재분석이 필요합니다"


class DecisionError(ValueError):
    pass


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _reference_inputs(region, resource_root):
    """후보 목록을 다시 만들 카탈로그·적용 판단(자원 루트 기준)."""
    docs = {}
    for role in ("candidate_catalog", "applicability"):
        rel = (region.get("inputs") or {}).get(role)
        if rel is None:
            docs[role] = None
            continue
        full = rel if os.path.isabs(rel) else os.path.join(resource_root, rel)
        if not os.path.isfile(full):
            raise run.InputError("%s 파일 없음: %s" % (role, rel))
        docs[role] = _load(full)
    if docs["candidate_catalog"] is None:
        raise run.InputError("구간 JSON에 이탈 후보 카탈로그(inputs.candidate_catalog)가 없음")
    return docs["candidate_catalog"], docs["applicability"]


def _status_of(cands, candidate_id):
    return next(c["selection_status"] for c in cands if c["candidate_id"] == candidate_id)


def change_candidate_decision(region_path, candidate_id, selection_status, decided_by, reason, now=run.utc_now,
                              resource_root=None):
    """후보 하나의 판단(selected·excluded·deferred)을 바꾼다.

    사유·변경자가 비었거나, 판단 값이 허용값이 아니거나, 후보가 없으면 DecisionError(파일 변경 없음).
    반환: {"region_file", "region_version", "decision", "previous_status", "notice"}
    """
    if not isinstance(reason, str) or not reason.strip():
        raise DecisionError("사유는 필수임")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise DecisionError("변경자는 필수임")
    if selection_status not in cand_mod.SELECTION:
        raise DecisionError("판단 값은 %s 중 하나: %r" % ("·".join(cand_mod.SELECTION), selection_status))
    region = _load(region_path)
    catalog, applicability = _reference_inputs(region, resource_root or paths.resource_root())
    at = now()
    entry = {"candidate_id": candidate_id, "selection_status": selection_status, "decided_by": decided_by.strip(),
             "reason": reason.strip(), "decided_at": at}
    try:
        before = cand_mod.build_candidates(catalog, applicability, region, {}, at)
    except cand_mod.CandidateInputError as exc:
        raise DecisionError("현재 구간 JSON의 후보 판단 기록을 읽을 수 없음: %s" % exc)
    if candidate_id not in {c["candidate_id"] for c in before}:
        raise DecisionError("후보 없음: %r" % candidate_id)
    new = copy.deepcopy(region)
    new.setdefault("candidate_decisions", []).append(entry)
    try:
        cand_mod.build_candidates(catalog, applicability, new, {}, at)  # 재분석 때와 같은 규칙으로 읽히는지 확인
    except cand_mod.CandidateInputError as exc:
        raise DecisionError(str(exc))
    new["region_version"] = region["region_version"] + 1
    run.write_region(region_path, new)
    return {"region_file": region_path, "region_version": new["region_version"], "decision": entry,
            "previous_status": _status_of(before, candidate_id), "notice": REANALYZE_NOTICE}
