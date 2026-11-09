"""지식그래프(지식 레이어) 검사 K1~K8을 한 번에 실행한다 (QA용). 하위 프로세스·네트워크를 쓰지 않는다.

근거: 기획서/그래프활용.md §7.1(정상 샘플·차단 픽스처), §7.2(K1~K8).
1) 정상 샘플 빌드: 데이터/지식/SNP-SAMPLE + 출력/그래프 -> 출력/지식그래프/kg-SNP-SAMPLE/<kg_version>/ + current.json
   (passed여야 함. 읽기는 포인터를 따라 sha256 검증)
2) 샘플 결과로 K1~K8 확인
3) 차단 픽스처(tests/fixtures/kg/*/): 각각 blocked와 expected.json의 blockers(rule·check·target)가 정확히 같음
4) tests/test_kg.py
P&ID 그래프가 없으면 먼저: python scripts/extract_drawio.py --samples && python scripts/build_graph.py
종료 코드 0 = 전부 통과.
"""

import copy
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import build_kg  # noqa: E402
from hazop.kg import build, inputs  # noqa: E402

SAMPLE_PROJECT = "SNP-SAMPLE"
SAMPLE_GRAPH = "graph-SNP-M-102"
FIXTURE_ROOT = os.path.join(REPO_ROOT, "tests", "fixtures", "kg")


def load_dir(input_dir, project_id):
    return inputs.load_knowledge(os.path.join(input_dir, build_kg.NODES_CSV),
                                 os.path.join(input_dir, build_kg.LINKS_CSV), project_id)


def blocker_keys(kg):
    return sorted((b["rule"], b["check"], b["target"]) for b in kg["validation"]["blockers"])


def fixture_problems(case_dir, graphs):
    """차단 픽스처 하나를 빌드해 기대와 다른 점 목록을 돌려준다(빈 목록 = 통과)."""
    with open(os.path.join(case_dir, "expected.json"), encoding="utf-8") as fh:
        exp = json.load(fh)
    kg = build.build_kg(load_dir(case_dir, os.path.basename(case_dir)), graphs)
    want = sorted((b["rule"], b["check"], b["target"]) for b in exp["blockers"])
    out = []
    if kg["validation"]["status"] != exp["status"]:
        out.append("status %s != 기대 %s" % (kg["validation"]["status"], exp["status"]))
    if blocker_keys(kg) != want:
        out.append("blockers %s != 기대 %s" % (blocker_keys(kg), want))
    return out


def fixture_dirs():
    return sorted(os.path.join(FIXTURE_ROOT, d) for d in os.listdir(FIXTURE_ROOT)
                  if os.path.isfile(os.path.join(FIXTURE_ROOT, d, "expected.json")))


def sample_checks(kg, knowledge, graphs, out_dir):
    """정상 샘플 결과로 K1~K8 판정. [(K번호, 설명, 통과 여부)]."""
    node = {n["id"]: n for n in kg["nodes"]}
    gmap = {g["graph_id"]: g for g in graphs}
    res = []
    def end_type(e):
        if e["layer"] != "pid":
            return node[e["ref"]]["node_type"]
        g = gmap.get(e.get("graph_id")) or {"nodes": []}
        return build.pid_end_class(next((n for n in g["nodes"] if n["entity_id"] == e.get("entity_id")), None))

    def pair_ok(l):
        return build.pair_allowed(l["kind"], end_type(l["ends"]["from"]), end_type(l["ends"]["to"]))
    res.append(("K1", "노드·관계 종류와 관계 타입 쌍(from·to node_type)이 화이트리스트 안",
                all(n["node_type"] in build.NODE_PREFIX for n in kg["nodes"])
                and all(l["kind"] in build.LINK_TYPES and pair_ok(l) for l in kg["links"])))
    pid_ends = [l["ends"][s] for l in kg["links"] for s in ("from", "to") if l["ends"][s]["layer"] == "pid"]

    def unique_tag(e):
        if e["ref"].startswith(e["graph_id"] + "#"):
            return True
        return sum(1 for n in gmap[e["graph_id"]]["nodes"] if n.get("tag") == e["tag"]) == 1
    res.append(("K2", "P&ID 참조가 모두 하나의 entity_id로 풀리고 동명 태그를 graph_id:tag로 쓰지 않음",
                bool(pid_ends) and all(e["entity_id"] for e in pid_ends) and all(unique_tag(e) for e in pid_ends)))
    ids = [n["id"] for n in kg["nodes"]] + [l["id"] for l in kg["links"]]
    res.append(("K3", "ID 중복·P&ID 접두어 충돌 없음",
                len(ids) == len(set(ids)) and not any(i.startswith(build.RESERVED_PREFIXES) for i in ids)))
    with open(os.path.join(out_dir, build.KG_FILE), "rb") as fh:
        on_disk = fh.read()
    with open(os.path.join(out_dir, build.KNOWLEDGE_FILE), "rb") as fh:
        k_disk = fh.read()
    again = build.build_kg(copy.deepcopy(knowledge), graphs)
    k2 = load_dir(os.path.join(build_kg.DEFAULT_INPUT_ROOT, SAMPLE_PROJECT), SAMPLE_PROJECT)
    res.append(("K4", "같은 입력 재빌드 -> 같은 kg_version·같은 바이트, 노드·관계 수 = 입력 행 수",
                build.dump_bytes(again) == on_disk and build.dump_bytes(k2) == k_disk
                and again["kg_version"] == kg["kg_version"]
                and (len(kg["nodes"]), len(kg["links"])) == (len(knowledge["nodes"]), len(knowledge["links"]))))
    changed = copy.deepcopy(graphs)
    for g in changed:
        if g["graph_id"] == SAMPLE_GRAPH:
            g["graph_version"] = "v-000000000000"
    kg5 = build.build_kg(copy.deepcopy(knowledge), changed)
    res.append(("K5", "참조 graph_version이 바뀌면 kg_version이 바뀜(그리고 mentions 재확인)",
                kg5["kg_version"] != kg["kg_version"]
                and all(l["recheck"] for l in kg5["links"] if l["kind"] == "mentions")))
    res.append(("K6", "confirmed 항목은 모두 출처 있음, 근거 열 없는 depends_on 없음",
                all(x["has_source"] for x in kg["nodes"] + kg["links"] if x["knowledge_status"] == "confirmed")
                and all(build._has_source(l["source"]) for l in kg["links"] if l["kind"] == "depends_on")))
    conf = {tuple(c["members"]) for c in kg["conflicts"]}
    psv = next(n for n in gmap[SAMPLE_GRAPH]["nodes"] if n.get("tag") == "RC-PSV101")
    psv_ref = "%s#%s" % (SAMPLE_GRAPH, psv["source_object_id"])
    res.append(("K7", "설정치 충돌(setpt-001·002)과 도면 설정압력(RC-PSV101 17.2 MPa)≠setpt-003(9) 모두 보존·표시, "
                      "운전압력·설계압력은 충돌 아님",
                conf == {("setpt-001", "setpt-002"), (psv_ref, "setpt-003")}
                and node["setpt-001"]["conflict_with"] == ["setpt-002"]
                and node["setpt-003"]["conflict_with_pid"] == [psv_ref] and node["setpt-003"]["value"] == "9"
                and psv["attributes"].get("set_pressure") == "17.2 MPa"
                and node["setpt-002"]["value"] == "8.5" and not node["cond-001"]["conflict_with"]))
    sp = node["setpt-003"]
    res.append(("K8", "빈 칸은 null·사유로 남고 0으로 바뀌지 않음",
                sp["unit"] is None and sp["pressure_basis"] is None
                and {"unit", "pressure_basis"} <= set(sp["null_reasons"])
                and all(n[f] is None for n in kg["nodes"] for f in n["null_reasons"] if f in n)
                and node["case-001"]["source"]["unregistered_reason"] is not None))
    return res


def main():
    safe_console()
    failures = []
    print("== 1. 정상 샘플 빌드 (%s)" % SAMPLE_PROJECT)
    graphs = build_kg.load_graphs(build_kg.DEFAULT_GRAPH_ROOT)
    if SAMPLE_GRAPH not in {g["graph_id"] for g in graphs}:
        print("  P&ID 그래프 %s 없음 - 먼저 build_graph.py 실행" % SAMPLE_GRAPH)
        return 1
    rc = build_kg.main([SAMPLE_PROJECT])
    if rc != 0:
        failures.append("정상 샘플 빌드 rc=%d (passed 아님)" % rc)
    kg_root = os.path.join(build_kg.DEFAULT_OUT, "kg-%s" % SAMPLE_PROJECT)
    try:
        _, kg = build.load_outputs(kg_root)  # 포인터를 따라 읽고 sha256 확인
    except (OSError, ValueError, KeyError) as e:
        print("  [FAIL] 출력 읽기:", e)
        return 1
    out_dir = build.current_dir(kg_root)
    knowledge = load_dir(os.path.join(build_kg.DEFAULT_INPUT_ROOT, SAMPLE_PROJECT), SAMPLE_PROJECT)
    print("== 2. 샘플 K1~K8")
    for k, label, ok in sample_checks(kg, knowledge, graphs, out_dir):
        print("  [%s] %s %s" % ("OK" if ok else "FAIL", k, label))
        if not ok:
            failures.append("%s: %s" % (k, label))
    print("== 3. 차단 픽스처")
    cases = fixture_dirs()
    if len(cases) < 8:
        failures.append("차단 픽스처 %d개 < 8" % len(cases))
    for d in cases:
        probs = fixture_problems(d, graphs)
        print("  [%s] %s" % ("OK" if not probs else "FAIL", os.path.basename(d)))
        failures += ["%s: %s" % (os.path.basename(d), p) for p in probs]
    print("== 4. unittest tests.test_kg")
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_kg")
    outcome = unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():
        failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
