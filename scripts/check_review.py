"""단계 ⑤ 검토 확정 기록 검사를 한 번에 실행한다 (QA용). 네트워크·AI 호출 없음.

입력: tests/run_fixture.py가 임시 폴더에 고정 응답으로 새로 만든 실행(scripts/analyze.py 하위 프로세스)을
복사해 쓴다. output/(git 제외 폴더)의 기존 실행에 의존하지 않는다.
검토 기록은 임시 저장 루트에만 쓰고 끝나면 지운다(store/에 쓰지 않음).

1) 정상 흐름: 수정(결과만)·수용·보류·기각 결정 → 저장 v1·v2, 이전 파일 바이트 불변
2) 차단: 사유·검토자 없음, 강도·빈도 없음, 등급 직접 입력, 근거 없는 보호수단, 보호수단 없이 빈도 감소,
   기각+설계보완 수용, 시나리오 있는 편차의 '시나리오 없음 확인', 해시 변경·파일 삭제, blocked 결과
3) review_status 판정·집계, 병합 규칙 값 출처, 이전 검토 가져오기
4) tests/test_review.py
종료 코드 0 = 전부 통과.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402
from hazop import review as rv  # noqa: E402
from tests.run_fixture import fresh_run_dir  # noqa: E402

WHO = "검토자A"


def ok(label, cond, failures):
    print("  [%s] %s" % ("OK" if cond else "FAIL", label))
    if not cond:
        failures.append(label)


def blocked(run, rec, fragment):
    errs = rv.validate_review(run, rec)
    return any(fragment in e for e in errs)


def harness(tmp, src, failures):
    run_dir = os.path.join(tmp, "runs", os.path.basename(src))
    shutil.copytree(src, run_dir)
    store_root = os.path.join(tmp, "store")
    run = rv.open_run(run_dir)
    doc = run["doc"]
    region = doc["region_ref"]["region_id"]
    print("실행: %s (검증 %s)" % (doc["analysis_run_id"], doc["validation"]["status"]))

    def rc(sev=3, f0=2, f=2, credited=()):
        return rv.make_risk_confirmation(run, sev, "강도 근거", f0, f, "빈도 근거", credited)

    print("1) 정상 흐름")
    cid = "deviation-p86-d09"
    sids = [s["scenario_id"] for s in doc["scenarios"] if s["candidate_id"] == cid]
    dids = [d["dic_id"] for d in doc["design_improvement_candidates"] if d["candidate_id"] == cid]
    decs = [rv.scenario_decision(run, sids[0], "modify", "결과 정정", WHO,
                                 revised={"consequence": "가압기 압력 상승(정정)"}, risk_confirmation=rc())]
    decs += [rv.scenario_decision(run, s, "accept", "수용", WHO, risk_confirmation=rc()) for s in sids[1:3]]
    decs += [rv.scenario_decision(run, sids[3], "reject", "도면 범위 밖", WHO),
             rv.scenario_decision(run, sids[4], "defer", "자료 대기", WHO)]
    ddecs = [rv.dic_decision(run, d, "accept", "권고 필요", WHO, recommendation="경보 추가 검토") for d in dids
             if not d.endswith(sids[3])]
    rec = rv.build_review(run, cid, WHO, "편차 검토 요약", decs, ddecs)
    p1, r1 = rv.save_review(store_root, run, rec)
    with open(p1, "rb") as fh:
        b1 = fh.read()
    p2, r2 = rv.save_review(store_root, run, rec)
    with open(p1, "rb") as fh:
        ok("저장마다 새 버전(v1, v2), 이전 파일 바이트 불변", (r1["review_version"], r2["review_version"]) == (1, 2)
           and fh.read() == b1, failures)
    na = [d for d in r1["design_improvement_decisions"] if d["decision"] == "not_applicable"]
    ok("기각 시나리오의 설계보완 후보가 not_applicable·사유 상속",
       len(na) == 1 and na[0]["reason"] == "도면 범위 밖" and na[0]["inherited_from"] == sids[3], failures)
    ok("보류가 있으면 review_status=deferred", r1["review_status"] == "deferred", failures)
    ok("revised에는 바뀐 필드만", r1["scenario_decisions"][0]["revised"] == {"consequence": "가압기 압력 상승(정정)"},
       failures)
    orig = next(s for s in doc["scenarios"] if s["scenario_id"] == sids[0])
    ao = r1["scenario_decisions"][0]["ai_original"]
    ok("ai_original = analysis.json 원안", ao["pattern"]["consequence"] == orig["consequence"]
       and ao["ai_interpretation"] == orig["ai_interpretation"], failures)
    ok("검토자·시각 기록", r1["reviewer_id"] == WHO and r1["reviewed_at"].endswith("Z"), failures)

    print("2) 차단")
    one = "deviation-p86-d12"
    s12 = next(s["scenario_id"] for s in doc["scenarios"] if s["candidate_id"] == one)
    d12 = next(d["dic_id"] for d in doc["design_improvement_candidates"] if d["candidate_id"] == one)

    def rec12(sdec, ddec=None, who=WHO):
        return rv.build_review(run, one, who, "요약", [sdec], ddec or [])

    for dec in rv.SCENARIO_DECISIONS:
        r = rec12(rv.scenario_decision(run, s12, dec, "", WHO,
                                       risk_confirmation=rc() if dec in ("accept", "modify") else None))
        ok("사유 없는 %s 차단" % dec, blocked(run, r, "사유 없음"), failures)
    ok("검토자 없음 차단", blocked(run, rec12(rv.scenario_decision(run, s12, "defer", "대기", WHO), who=""),
                              "검토자 이름"), failures)
    bad = rc()
    bad["severity"] = None
    ok("강도 없음 차단", blocked(run, rec12(rv.scenario_decision(run, s12, "accept", "수용", WHO, risk_confirmation=bad)),
                             "강도"), failures)
    bad = rc()
    bad["risk"] = 5
    ok("등급 직접 입력 차단", blocked(run, rec12(rv.scenario_decision(run, s12, "accept", "수용", WHO,
                                                                 risk_confirmation=bad)), "〈표5〉"), failures)
    ok("보호수단 없이 빈도 감소 차단", blocked(run, rec12(rv.scenario_decision(
        run, s12, "accept", "수용", WHO, risk_confirmation=rc(3, 2, 1))), "보호수단 없이"), failures)
    ok("근거 없는 인정 보호수단 차단", blocked(run, rec12(rv.scenario_decision(
        run, s12, "accept", "수용", WHO, risk_confirmation=rc(3, 2, 1, [{"node_id": "entity-node-014"}]))),
        "확인 근거"), failures)
    ok("기각 + 설계보완 수용 차단", blocked(run, rec12(
        rv.scenario_decision(run, s12, "reject", "기각", WHO),
        [rv.dic_decision(run, d12, "accept", "필요", WHO, recommendation="권고")]), "함께 저장할 수 없음"), failures)
    ok("시나리오 있는 편차의 '시나리오 없음 확인' 차단", blocked(run, rv.build_review(
        run, one, WHO, "요약", no_scenario=rv.no_scenario_confirmation("없음", WHO)), "시나리오 없음 확인"), failures)

    print("3) 판정·병합·가져오기")
    zero = rv.build_review(run, "deviation-p86-d01", WHO, "요약")
    ok("시나리오 0개 편차는 확인 없이 confirmed 아님", zero["review_status"] == "reviewing", failures)
    zero_ok = rv.build_review(run, "deviation-p86-d01", WHO, "요약",
                              no_scenario=rv.no_scenario_confirmation("원인 설비 없음 확인", WHO))
    ok("'시나리오 없음 확인' 후 confirmed", zero_ok["review_status"] == "confirmed", failures)
    rv.save_review(store_root, run, zero_ok)
    summ = rv.review_summary(doc, rv.load_run_reviews(store_root, region, doc["analysis_run_id"]))
    ok("집계: 제외 19는 판정에서 빠짐, 선택 25 판정", len(summ["excluded"]) == 19
       and sum(summ["counts"].values()) == 25, failures)
    m = rv.merge_display(orig, r1["scenario_decisions"][0])
    ok("병합 값 출처: 원인=AI 해석, 결과=사람 수정, 안전조치=그래프",
       rv.value_source_text(m) == "원인=AI 해석 원안, 결과=사람 수정, 현재안전조치=그래프 확인", failures)
    hyp = dict(orig, origin="ai_additional_hypothesis", pattern_ref=None)
    ok("AI 추가 가설: AI 제시 보호수단을 현재안전조치 값에 넣지 않음",
       rv.merge_display(hyp)["safeguards"] == {"value": [], "source": "graph"}, failures)

    new_dir = os.path.join(tmp, "runs", "analysis-29991231T000000Z-check")
    shutil.copytree(src, new_dir)
    with open(os.path.join(new_dir, "analysis.json"), encoding="utf-8") as fh:
        nd = json.load(fh)
    nd["analysis_run_id"] = os.path.basename(new_dir)
    with open(os.path.join(new_dir, "analysis.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(nd, fh, ensure_ascii=False, indent=2)
    new = rv.open_run(new_dir)
    ok("재분석 실행에 자동 승계 없음", rv.load_review(store_root, region, nd["analysis_run_id"], cid) is None, failures)
    prior = rv.find_prior_reviews(store_root, region, nd["analysis_run_id"], cid)[0]
    got = rv.import_scenario_decision(new, sids[1], prior, "재확인", "검토자B")
    ok("가져온 결정: 새 사유·검토자 + imported_from", got["reason"] == "재확인" and got["decided_by"] == "검토자B"
       and got["imported_from"]["scenario_id"] == sids[1], failures)

    print("4) 잠금·blocked")
    with open(run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    ok("analysis.json 해시 변경 시 편집 불가", not rv.check_editable(rv.open_run(run_dir), r2)["editable"], failures)
    os.remove(run["analysis_path"])
    ok("analysis.json 삭제 시 편집 불가", not rv.check_editable(run, r2)["editable"], failures)
    nd["validation"]["status"] = "blocked"
    with open(os.path.join(new_dir, "analysis.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(nd, fh, ensure_ascii=False, indent=2)
    brun = rv.open_run(new_dir)
    ok("blocked 결과 저장 차단", blocked(brun, rv.build_review(
        brun, one, WHO, "요약", [rv.scenario_decision(brun, s12, "defer", "대기", WHO)]), "passed가 아님"), failures)


def main():
    safe_console()
    failures = []
    try:
        src = fresh_run_dir()
    except Exception as e:  # 분석 실행 실패도 실패로 보고
        print("[FAIL] 검사용 분석 실행을 만들지 못함: %r" % e)
        return 1
    tmp = tempfile.mkdtemp(prefix="hazop-check-review-")
    try:
        harness(tmp, src, failures)
    except Exception as e:  # 검사 도중 예외도 실패로 보고
        failures.append("예외: %r" % e)
        print("  [FAIL] 예외: %r" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("5) tests/test_review.py")
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_review")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok("단위 테스트 %d개" % result.testsRun, result.wasSuccessful(), failures)
    print("결과: %s" % ("전부 통과" if not failures else "실패 %d건: %s" % (len(failures), failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
