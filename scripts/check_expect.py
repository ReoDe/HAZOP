"""잠재 후보(기대 패턴) 검사와 측정 (기획서/지식그래프-스키마.md §8.2 M4 완료 기준). 하위 프로세스·네트워크를 쓰지 않는다.

1) 샘플 SNP-SAMPLE 프로젝트 그래프(출력/그래프 6장, 읽기만) + 지식그래프 kg-SNP-SAMPLE(있으면, 읽기만)로 규칙별
   대상·후보 발견·미발견 수 표를 낸다.
2) 임시 폴더에 사람 판단(후보 확인·후보 기각·부재 확정·무관)을 저장하고 다시 계산해 같은 상태인지, 세 번째 계산이 같은지(멱등)
   확인한다. 데이터/·출력/에는 쓰지 않는다.
3) 대상 내용이 바뀐 판에서 확인됨·부재 확정이 재확인 필요로 돌아가는지 확인한다.
4) 잠재 후보가 계산 뷰(V5)와 ③ 알고리즘 결과에 들어가지 않는지 확인한다.
5) tests/test_kg_expect.py
종료 코드 0 = 전부 통과.
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.kg import algo, build, expect, screen  # noqa: E402

PROJECT = project.UNREGISTERED_PROJECT
SAMPLE_GRAPH = "graph-SNP-M-102"


def load_inputs():
    pg = project.load(PROJECT, os.path.join(REPO_ROOT, "출력", "그래프"))
    kg_root = os.path.join(REPO_ROOT, "출력", "지식그래프", "kg-%s" % PROJECT)
    kg = build.load_outputs(kg_root)[1] if os.path.isfile(os.path.join(kg_root, build.POINTER_FILE)) else None
    return pg, kg


def table(res):
    lines = ["| 규칙 | 기대 | 대상 | 후보 발견 | 미발견 |", "| --- | --- | --- | --- | --- |"]
    total = [0, 0, 0]
    for rid, s in res["summary"].items():
        lines.append("| %s | %s | %d | %d | %d |" % (rid, s["label"], s["targets"], s["candidate_found"], s["not_found"]))
        total = [total[0] + s["targets"], total[1] + s["candidate_found"], total[2] + s["not_found"]]
    lines.append("| 계 | | %d | %d | %d |" % tuple(total))
    return "\n".join(lines)


def first(res, rule, state):
    return next((i for i in res["items"] if i["rule_id"] == rule and i["state"] == state), None)


def persistence(pg, kg, failures):
    tmp = tempfile.mkdtemp(prefix="hazop-expect-")
    try:
        path = os.path.join(tmp, *expect.STORE_DIR, "%s.json" % PROJECT)
        res = expect.evaluate(pg, kg)
        plan = [("E01", "candidate_found", "confirm", {}),
                ("E02", "candidate_found", "reject", {}),
                ("E05", "expected", "absent", {"reason": "샘플 도면·문서에 구동원 정보 없음(측정용 판단)",
                                               "evidence": "측정용 가상 근거"}),
                ("E03", "expected", "not_applicable", {"reason": "측정용 판단"})]
        picked = {}
        for rule, state, action, kw in plan:
            it = first(res, rule, state)
            if it is None:
                failures.append("판단할 %s %s 항목이 샘플에 없음" % (rule, state))
                continue
            rec = expect.apply_action(it, action, "측정", at="2026-11-09T00:00:00Z", **kw)
            expect.save_judgement(path, PROJECT, rec)
            picked[it["key"]] = rec["state"] if action != "reject" else "expected"
        j = expect.load_judgements(path, PROJECT)
        again = expect.evaluate(pg, kg, j)
        third = expect.evaluate(pg, kg, expect.load_judgements(path, PROJECT))
        got = {i["key"]: i["state"] for i in again["items"] if i["key"] in picked}
        print("  판단 저장 %d건 → 다시 계산: %s" % (len(picked), ", ".join("%s=%s" % (k.split("|")[0], expect.STATES[v])
                                                                  for k, v in sorted(got.items()))))
        if got != picked:
            failures.append("재실행 후 상태가 다름: %s != %s" % (got, picked))
        if third != again:
            failures.append("세 번째 계산이 두 번째와 다름(멱등 아님)")
        others = [i for i in again["items"] if i["key"] not in picked]
        if [(i["key"], i["state"]) for i in others] != [(i["key"], i["auto_state"]) for i in others]:
            failures.append("판단하지 않은 항목의 상태가 바뀜")
        changed = copy.deepcopy(pg)
        keys = {k for k, v in picked.items() if v in ("confirmed_present", "confirmed_absent")}
        targets = {k.split("|", 1)[1] for k in keys}
        for n in changed["nodes"]:
            ref = "%s#%s" % (n.get("sheet"), n.get("source_object_id"))
            if ref in targets:
                n["attributes"] = dict(n.get("attributes") or {}, size="측정용 변경")
        rev = expect.evaluate(changed, kg, j)
        rech = {i["key"] for i in rev["items"] if i["recheck"]}
        print("  대상 내용 변경 → 재확인 필요 %d건 (확인됨·부재 확정 %d건 중)" % (len(rech & keys), len(keys)))
        if rech != keys:
            failures.append("판 변경 재확인 대상이 다름: %s != %s" % (sorted(rech), sorted(keys)))
        with open(path, encoding="utf-8") as fh:
            print("  판단 파일(임시): %s, %d바이트" % (os.path.relpath(path, tmp), len(fh.read().encode("utf-8"))))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def exclusion(pg, kg, failures):
    if kg is None:
        print("  지식그래프 없음 — V5 제외 확인 건너뜀")
        return
    graphs = screen.load_graphs(os.path.join(REPO_ROOT, "출력", "그래프"))
    hit = next((g for _, g in graphs.values() if g["graph_id"] == SAMPLE_GRAPH), None)
    if hit is None:
        failures.append("%s 그래프 없음" % SAMPLE_GRAPH)
        return
    res = expect.evaluate(pg, kg)
    with_x = screen.screen_data(kg, hit, expectations=res)
    without = screen.screen_data(kg, hit)
    xs = {n["id"] for n in with_x["nodes"] if n["layer"] == screen.EXP_LAYER}
    v5 = algo.view_v5(kg, hit)
    bad = xs & set(v5.nodes) or any(n["v5"] for n in with_x["nodes"] if n["id"] in xs)
    print("  %s 화면 잠재 후보 %d개, V5 노드 %d개, 겹침 %s, 알고리즘 결과 동일 %s" % (
        SAMPLE_GRAPH, len(xs), v5.number_of_nodes(), "있음" if bad else "없음", with_x["algo"] == without["algo"]))
    if bad or with_x["algo"] != without["algo"] or not xs:
        failures.append("잠재 후보가 계산 뷰·알고리즘 결과에 영향을 줌(또는 화면에 없음)")


def main():
    safe_console()
    failures = []
    print("== 1. 샘플 %s 규칙별 집계" % PROJECT)
    pg, kg = load_inputs()
    res = expect.evaluate(pg, kg)
    print("  도면 %d장, 지식그래프 %s, 규칙 판 %s, 잠재 후보 %d개" % (len(pg["sheets"]), (kg or {}).get("kg_version", "없음"),
                                                       res["rules_version"], len(res["items"])))
    print(table(res))
    print("== 2·3. 판단 저장·재실행 유지·판 변경 재확인 (임시 폴더)")
    persistence(pg, kg, failures)
    print("== 4. 계산 뷰 제외")
    exclusion(pg, kg, failures)
    store = paths.work_path(*expect.STORE_DIR)
    print("  실제 판단 폴더(읽지도 쓰지도 않음): %s" % store)
    print("== 5. unittest tests.test_kg_expect")
    outcome = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromName("tests.test_kg_expect"))
    if not outcome.wasSuccessful():
        failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
