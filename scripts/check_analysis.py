"""단계 ④ HAZOP 분석 검사를 한 번에 실행한다 (QA용). 하위 프로세스·실제 API 호출을 쓰지 않는다.
모든 생성물은 임시 폴더에 만들고 끝나면 지운다(출력/ 폴더를 덮어쓰거나 누적하지 않음).

1) 샘플 추출 -> 그래프 빌드(임시 폴더)
2) 이탈 후보 카탈로그·적용 판단 = 지침서 §5.3 표, 위험도 기준표 = 지침서 §6 〈표5〉~〈표9〉
3) 고정 응답으로 SNP-M-102 가압기 구간 분석·저장(execute: AI 전 저장 + 후보별 이어 저장)·재읽기
4) 결과 검사: 44개 후보 판단, 적용 불가 19건 사유, 고정 응답 검증, 참조 유효, 위험도 = 〈표5〉 조회,
   보호수단 미확인 시 빈도 감소 미반영, 탐색 종료·NC 경로 구분, 보류 기록, 도면 설비 한정, 설계보완 후보
5) 나쁜 응답 검출, 기준표 없음 보류, 다른 AI 모드 재시도 거부
6) tests/test_analysis.py
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
from hazop import paths  # noqa: E402
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import analyze  # noqa: E402
import build_graph  # noqa: E402
import extract_drawio  # noqa: E402
from hazop.analysis import ai, catalog_md, equipment, integrity, risk, run  # noqa: E402

BAD_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "analysis", "bad")
GUIDE = paths.file_in(REPO_ROOT, "guide")
FIXED_ITEMS = ("p86-d09", "p86-d10", "p86-d12", "p86-d43", "p86-d44")


def ok(label, cond, failures):
    print("  [%s] %s" % ("OK" if cond else "FAIL", label))
    if not cond:
        failures.append(label)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check_doc(doc, graph, criteria, failures):
    cands = {c["item_id"]: c for c in doc["candidates"]}
    ok("후보 44개 전부 판단 상태·이유 있음", len(doc["candidates"]) == 44 and all(
        c["selection_status"] in ("selected", "excluded", "deferred") and c["reason"] and c["judgments"]
        for c in doc["candidates"]), failures)
    ex = [c for c in doc["candidates"] if c["selection_status"] == "excluded"]
    ok("적용 불가 19건 제외(R1)·사유·위험도 not_applicable", len(ex) == 19 and all(
        c["judgments"][0]["decided_by"] == "rule:R1" and c["reason"]
        and c["risk_proposal"]["status"] == "not_applicable" for c in ex), failures)
    ok("적용 25건 선택", sum(c["selection_status"] == "selected" for c in doc["candidates"]) == 25, failures)
    ok("고정 응답 5건 검증 통과", all(cands[i]["analysis"]["ai_status"] == "validated" for i in FIXED_ITEMS), failures)
    nodes = {n["entity_id"]: n for n in graph["nodes"]}
    g_rels = {e["entity_id"] for e in graph["edges"]}
    ok("시나리오 노드·관계 참조가 모두 그래프에 있음", all(
        set(s["graph_evidence"]["node_ids"]) <= set(nodes) and set(s["graph_evidence"]["relation_ids"]) <= g_rels
        for s in doc["scenarios"]), failures)
    ok("모든 시나리오가 도면 설비(cause_equipment) 기반", all(
        s["cause_equipment"] and all(equipment.is_equipment(nodes[e]) for e in s["cause_equipment"])
        for s in doc["scenarios"]), failures)
    rejected = [r for c in doc["candidates"] for r in c["analysis"]["rejected_ai_scenarios"]]
    ok("도면에 없는 설비 가정 시나리오 거부·사유 기록(%d건)" % len(rejected),
       len(rejected) == 2 and all("도면에 없는 설비" in r["reason"] for r in rejected)
       and not any("전열기" in s["cause"] for s in doc["scenarios"]), failures)
    ok("패턴 문구에 '가열'(도면에 없는 전열기 암시) 없음", not any(
        "가열" in s["cause"] + s["consequence"] for s in doc["scenarios"] if s["origin"] == "pattern"), failures)
    proposed = [s["risk_proposal"] for s in doc["scenarios"] if s["risk_proposal"]["status"] == "proposed"]
    ok("위험도 제안 = 표5 조회값 (%d건)" % len(proposed), proposed and all(
        p["risk"] == risk.MATRIX_P86[p["severity"]][p["frequency_used"]] for p in proposed), failures)
    ok("감지기 보호수단은 보호 동작 미확인이면 '찾음' 아님", all(
        not g["counts_as_found"] for s in doc["scenarios"] for g in s["safeguards"]
        if g["protective_action"] == "detection" and not g["action_confirmed"]), failures)
    ok("보호수단 미확인 -> 빈도 감소 미반영", all(
        not p["safeguard_credit_applied"] and p["frequency_used"] == p["frequency_without_safeguards"] for p in proposed)
        and any((p["frequency_with_safeguards_ai"] or 9) < p["frequency_without_safeguards"] for p in proposed), failures)
    ok("위험도는 제안(확정 아님)", all(not p["confirmed"] for p in proposed), failures)
    dics = doc["design_improvement_candidates"]
    from hazop.graph.query import GraphQuery
    q = GraphQuery(graph)
    want = set()
    for s in doc["scenarios"]:
        rp = s["risk_proposal"]
        if rp["status"] == "proposed" and rp["risk"] >= 3:  # 보류 시나리오도 포함
            want.add(s["scenario_id"])
        if s["scenario_status"] == "draft" and not run._safeguard_verdict(s, q)[0]:
            want.add(s["scenario_id"])
    ok("PSV 보호수단은 압력 증가 후보에만", all(g["kind"] != "psv" for cid, b in doc["evidence_bundles"].items()
                                     if cid != "deviation-p86-d09" for g in b["candidate_safeguards"]), failures)
    ok("설계보완 후보 %d건 = 위험도 3 이상·독립 보호수단 미발견 시나리오, 미확정" % len(dics),
       dics and {d["scenario_id"] for d in dics} == want
       and all(d["status"] == "candidate" and d["confirmed"] is False for d in dics), failures)
    ex0 = doc["explorations"][0]
    v111 = next(r for r in ex0["reached"] if r["tag"] == "RC-V111")
    ok("탐색 종료·순환 기록·다른 도면 연결 기록", ex0["terminated"] and ex0["cycle_or_merge_edges"]
       and sum(t["reason"] == "external_drawing" for t in ex0["truncations"]) == 3, failures)
    ok("NC 밸브(RC-PV101) 뒤 경로는 정상 운전 유로 아님", v111["normal_operation_flow"] is False
       and v111["valves_on_path"][0]["normal_position"] == "NC", failures)
    ok("운전조건 미확인 보류 기록", any(h["item"] == "가압기 정상 운전압력" for h in doc["holds"]), failures)
    ok("결과 검증 passed", doc["validation"]["status"] == "passed", failures)


def main():
    safe_console()
    failures = []
    tmp = tempfile.mkdtemp(prefix="check_analysis_")
    try:
        ext, gr, out = (os.path.join(tmp, d) for d in ("추출", "그래프", "분석"))
        print("== 1. 샘플 추출·그래프 빌드 (임시 폴더)")
        if extract_drawio.main(["--samples", "--out-root", ext]) != 0 or \
                build_graph.main(["--extract-root", ext, "--out-root", gr]) != 0:
            failures.append("추출·그래프 빌드 실패")
        print("== 2. 데이터 파일 = 지침서")
        cat, app = catalog_md.rows_to_files(catalog_md.parse_guide_table(GUIDE))
        region = _load(analyze.DEFAULT_REGION)
        on_disk = [_load(paths.resolve_rel(region["inputs"][k], REPO_ROOT)) for k in ("candidate_catalog", "applicability")]
        ok("카탈로그 44개·적용 판단 파일이 지침서 §5.3 표와 같음", [cat, app] == on_disk and len(cat["items"]) == 44, failures)
        crit = _load(paths.resolve_rel(region["inputs"]["risk_criteria"], REPO_ROOT))
        tables = catalog_md.parse_risk_tables(GUIDE)
        ok("위험도 기준표가 지침서 표5~표9와 같음", all(tables[k] == crit[k] for k in tables), failures)
        integ = integrity.check_catalog(on_disk[0], on_disk[1]) + integrity.check_criteria(crit)
        ok("기준 데이터 고정 해시·지침서·코드 상수 대조 %s" % integ, not integ, failures)
        print("== 3. 고정 응답으로 분석·저장")
        inputs = run.load_inputs(analyze.DEFAULT_REGION, REPO_ROOT, graph_path=os.path.join(gr, "SNP-M-102", "graph.json"))
        ok("입력 차단 오류 없음 %s" % inputs["blockers"], not inputs["blockers"], failures)
        if inputs["blockers"]:
            return 1
        fixed = ai.FixedResponseClient(analyze.DEFAULT_FIXED, repo_root=REPO_ROOT)
        doc, run_dir = run.execute(inputs, fixed, out)
        analyze.summary(doc, run_dir)
        saved = _load(os.path.join(run_dir, "analysis.json"))
        ok("저장 결과 재읽기 동일", saved == json.loads(json.dumps(doc)), failures)
        ok("입력 사본 저장", sorted(os.listdir(os.path.join(run_dir, "inputs"))) ==
           sorted(r + ".json" for r in run.INPUT_ROLES), failures)
        print("== 4. 결과 검사")
        check_doc(saved, inputs["graph"], inputs["criteria"], failures)
        print("== 5. 나쁜 응답·기준표 없음·AI 모드")
        bad = run.analyze(inputs, ai.FixedResponseClient(BAD_DIR), run_id="analysis-check-bad")
        d09 = next(c for c in bad["candidates"] if c["item_id"] == "p86-d09")
        rec = next(r for r in bad["ai_runs"] if r["candidate_id"] == d09["candidate_id"])
        ok("없는 노드 인용 -> 참조 오류, 통과 금지", d09["analysis"]["ai_status"] == "validation_failed"
           and any(e["type"] == "reference_error" for e in rec["validation"]["errors"])
           and not any(s["ai_interpretation"] for s in bad["scenarios"] if s["candidate_id"] == d09["candidate_id"]),
           failures)
        nc = run.analyze(dict(inputs, criteria=None), ai.FixedResponseClient(analyze.DEFAULT_FIXED, verify_bundle=False),
                         run_id="analysis-check-nocrit")
        ok("기준표 없음 -> 위험도 전부 보류, 등급 없음", all(
            s["risk_proposal"]["status"] == "deferred" and s["risk_proposal"]["risk"] is None for s in nc["scenarios"]),
            failures)
        try:
            run.resume(run_dir, ai.FixedResponseClient(BAD_DIR, repo_root=REPO_ROOT))
            refused = False
        except run.InputError:
            refused = True
        ok("다른 AI 모드(고정 응답 폴더)로 재시도 거부", refused, failures)
        print("== 6. unittest (tests/test_analysis.py)")
        suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_analysis")
        outcome = unittest.TextTestRunner(verbosity=1).run(suite)
        if not outcome.wasSuccessful():
            failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
