"""지식그래프 알고리즘 검사 A1~A5·A1′와 성능 기록 P1 (QA용). 하위 프로세스·네트워크를 쓰지 않는다.

근거: 기획서/그래프활용.md §4(뷰·알고리즘), §7.1(샘플·A2 기대값), §7.2(A1~A5, A1′, P1), §7.3(성능 상한).
1) 정상 샘플 지식그래프 빌드(scripts/build_kg.py와 같음) -> 포인터를 따라 읽기
2) A1~A5: 샘플 결과가 정답 파일 tests/fixtures/kg_algo/expected_SNP-SAMPLE.json과 같음
3) A1′: 선택 노드 = 구간 focus_entities[0]일 때 A1 탐색 결과가 ④ 분석 실행(run.load_inputs + run.prepare_doc)의
   탐색 결과와 같음(도달 대상·경로·방향 표시·밸브 위치 표시·절단 기록 포함 전체)
4) 결정성: 같은 입력 두 번 -> 같은 결과 바이트. 결과 JSON·보고서를 출력/지식그래프/ 아래에 씀
5) P1: §7.3 전역 보기 상한(5,000 노드) 규모 합성 그래프에서 계산 시간 기록(합격 기준 아님)
6) tests/test_kg_algo.py
P&ID 그래프가 없으면 먼저: python scripts/extract_drawio.py --samples && python scripts/build_graph.py
종료 코드 0 = 전부 통과. --skip-p1 로 P1 생략.
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import sys
import time
import unittest

import networkx as nx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402

import analyze_kg  # noqa: E402
import build_kg  # noqa: E402
from hazop.analysis import run  # noqa: E402
from hazop.kg import algo, build  # noqa: E402

SAMPLE_PROJECT = "SNP-SAMPLE"
EXPECTED = os.path.join(REPO_ROOT, "tests", "fixtures", "kg_algo", "expected_SNP-SAMPLE.json")
REGION_FILE = paths.folder_in(REPO_ROOT, "표본", "regions", "region-SNP-M-102-pzr.json")
P1_NODES = 5000  # §7.3 전역 보기 노드 수 상한
P1_FILE = "p1_performance.json"


def load_expected():
    with open(EXPECTED, encoding="utf-8") as fh:
        return json.load(fh)


def expected_problems(kg, graph, regions, exp):
    """정답 파일과 다른 점 {검사 ID: [문제]} (빈 목록 = 통과)."""
    doc = algo.analyze(kg, graph, regions, exp["start"], exp["radius"])
    r = {k: v["result"] for k, v in doc["results"].items()}
    out = {k: [] for k in ("A1", "A2", "A3", "A4", "A5")}

    def cmp(key, name, got, want):
        if got != want:
            out[key].append("%s: %s != 기대 %s" % (name, json.dumps(got, ensure_ascii=False),
                                                 json.dumps(want, ensure_ascii=False)))
    a1, e1 = r["A1"], exp["A1"]
    cmp("A1", "active", a1["active"], e1["active"])
    if a1["active"]:
        s, x = a1["summary"], a1["exploration"]
        cmp("A1", "region_id", a1["region_ref"]["region_id"], e1["region_id"])
        for f in ("reached", "by_direction", "not_normal_flow_path", "valve_position_unknown_path", "limits_hit",
                  "unreached_region_members"):
            cmp("A1", f, s[f], e1[f])
        cmp("A1", "truncations", sorted([t["reason"], t["at"]] for t in x["truncations"]), e1["truncation_reasons_at"])
        cmp("A1", "cycle_or_merge_edges", x["cycle_or_merge_edges"], e1["cycle_or_merge_edges"])
    a2, e2 = r["A2"], exp["A2"]
    cmp("A2", "orphans", [o["id"] for o in a2["orphans"]], e2["orphans"])
    cmp("A2", "orphan_link_hints", {o["id"]: [[h["chunk"], h["entity_id"]] for h in o["link_hints"]]
                                    for o in a2["orphans"] if o.get("link_hints")}, e2["orphan_link_hints"])
    cmp("A2", "evidence_gaps", [g["entity_id"] for g in a2["evidence_gaps"]], e2["evidence_gaps"])
    cmp("A2", "no_knowledge_input", [g["entity_id"] for g in a2["no_knowledge_input"]], e2["no_knowledge_input"])
    cmp("A2", "no_knowledge_input_continuations", [g["entity_id"] for g in a2["no_knowledge_input_continuations"]],
        e2["no_knowledge_input_continuations"])
    flagged = {g["entity_id"] for g in a2["evidence_gaps"] + a2["no_knowledge_input"]
               + a2["no_knowledge_input_continuations"]} | {o["id"] for o in a2["orphans"]}
    for n in e2["not_orphan_not_gap"]:
        if n in flagged:
            out["A2"].append("%s는 고아·근거 공백·지식 입력 없음 어디에도 없어야 함" % n)
    for f in ("degree", "degree_segments_folded"):
        cmp("A3", f, {n: v["degree"] for n, v in r["A3"][f].items()}, exp["A3"][f])
    v5 = algo.view_v5(kg, graph)
    for case in exp["A4"]:
        got = algo.a4_ego(v5, case["center"], case["radius"])
        cmp("A4", "%s r%d active" % (case["center"], case["radius"]), got["active"], case["active"])
        if case["active"] and got["active"]:
            cmp("A4", "%s r%d nodes" % (case["center"], case["radius"]), got["nodes"], case["nodes"])
    for v in ("V1", "V5"):
        for f in exp["A5"][v]:
            got = r["A5"][v][f][1:] if f == "components" else r["A5"][v][f]
            cmp("A5", "%s %s" % (v, f), got, exp["A5"][v][f])
    return out, doc


def a1_prime_problems(kg, graph, region_path):
    """A1′. ④ 분석 실행의 탐색(run.load_inputs + run.prepare_doc, AI 단계 전)과 A1을 비교한다."""
    inputs = run.load_inputs(region_path, paths.work_root(), resource_root=paths.resource_root())
    if inputs["blockers"]:
        return ["④ 입력 차단: %s" % " / ".join(inputs["blockers"])]
    region = inputs["region"]
    focus = region["focus_entities"][0]
    ref = run.prepare_doc(inputs, None)["explorations"][0]
    with open(region_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    a1 = algo.a1_propagation(graph, [(region_path, region, sha)], focus)
    if not a1["active"]:
        return ["A1 비활성: %s" % a1["reason"]]
    got = a1["exploration"]
    probs = []
    if a1["region_members"] != sorted(run.ex_mod.region_members(inputs["graph"],
                                                                 [m["entity_id"] for m in region["members"]])):
        probs.append("구간 멤버가 ④와 다름")
    fields = {"도달 대상": lambda e: [r["entity_id"] for r in e["reached"]],
              "경로": lambda e: [(r["path_nodes"], r["path_edges"]) for r in e["reached"]],
              "방향 표시": lambda e: [(r["direction_from_start"], r["segment_flow"]) for r in e["reached"]],
              "밸브 위치 표시": lambda e: [(r["valves_on_path"], r["valve_state"], r["normal_operation_flow"])
                                     for r in e["reached"]],
              "절단 기록": lambda e: (e["truncations"], e["boundary_crossings"], e["limits_hit"])}
    for name, f in fields.items():
        if f(got) != f(ref):
            probs.append("%s가 ④ 탐색과 다름" % name)
    if got != ref:
        probs.append("탐색 결과 전체가 ④와 다름(설정·순환 엣지·미도달 등)")
    return probs


# ---------------------------------------------------------------- P1 합성 그래프
def synthetic(total_nodes=P1_NODES, graph_id="graph-SYN-P1"):
    """§7.3 상한 규모의 결정적 합성 입력 (graph, kg, regions). 노드 수 합 = total_nodes.
    P&ID: 도면 객체 두 줄(사다리, 40개마다 가로 연결) + 계기, 지식: 문서 1 + 조각·요건·설정치·운전조건.
    값은 성능 측정용 가상 구조이며 실제 계통이 아님."""
    n_knowledge = total_nodes * 8 // 25          # 약 32% 지식 노드
    n_inst = total_nodes // 25                   # 계기
    rows = (total_nodes - n_knowledge - n_inst + 1) // 4  # 한 줄 객체 수(객체 2줄 + 배관 구간 약 2줄)
    nodes, edges = [], []

    def obj(i, kind, category, attrs=None):
        nodes.append({"entity_id": "entity-node-%05d" % i, "node_type": "drawing_object", "kind": kind,
                      "category": category, "tag": "SYN-%05d" % i, "attributes": attrs or {}})
    positions = ["NO", "NC", None, "LO", "LC"]
    for i in range(2 * rows):
        if i % 7 == 3:
            obj(i, "manual_valve", "valve", {"normal_position": positions[i % 5]})
        else:
            obj(i, "tank" if i % 11 == 0 else "tee", "equipment" if i % 11 == 0 else "piping_element")
    seg_no, rel_no = [0], [0]

    def seg(a, b, directed=True):
        s = "entity-seg-%05d" % seg_no[0]
        seg_no[0] += 1
        nodes.append({"entity_id": s, "node_type": "pipe_segment", "kind": "pipe_segment", "category": "pipe_segment",
                      "tag": "SYN-L%03d" % (seg_no[0] % 100), "attributes": {},
                      "flow_direction": {"from_end": "source", "to_end": "target"} if directed else None})
        for node, end in ((a, "source"), (b, "target")):
            rel_no[0] += 1
            edges.append({"entity_id": "relation-%06d" % rel_no[0], "kind": "has_endpoint", "nodes": [s, node],
                          "segment": s, "node": node, "end": end})
    for r in (0, rows):
        for i in range(r, r + rows - 1):
            seg("entity-node-%05d" % i, "entity-node-%05d" % (i + 1), directed=i % 9 != 0)
    for i in range(0, rows, 40):
        seg("entity-node-%05d" % i, "entity-node-%05d" % (i + rows))
    base = 2 * rows
    pid_count = 2 * rows + seg_no[0]
    n_inst = total_nodes - n_knowledge - pid_count
    for j in range(n_inst):
        eid = "entity-node-%05d" % (base + j)
        obj(base + j, "transmitter", "instrument")
        rel_no[0] += 1
        edges.append({"entity_id": "relation-%06d" % rel_no[0], "kind": "measurement_connection",
                      "nodes": ["entity-node-%05d" % ((j * 13) % (2 * rows)), eid]})
    graph = {"graph_id": graph_id, "graph_version": "v-synthetic01", "validation": {"status": "passed"},
             "nodes": nodes, "edges": edges}
    objs = ["entity-node-%05d" % i for i in range(2 * rows)]
    kn, kl = [{"id": "doc-001", "node_type": "document", "compute_view": {"v4": True, "excluded_reasons": []}}], []

    def kref(eid):
        return {"layer": "knowledge", "ref": eid}

    def pref(eid):
        return {"layer": "pid", "ref": "%s:%s" % (graph_id, eid), "graph_id": graph_id, "entity_id": eid}

    def link(kind, a, b, ok=True, status="confirmed"):
        kl.append({"id": "krel-%06d" % len(kl), "kind": kind, "link_status": status,
                   "compute_view": {"v4": ok, "excluded_reasons": [] if ok else ["link_status=%s" % status]},
                   "ends": {"from": a, "to": b}})
    def node_ok(j):
        return j % 50 != 7  # 일부는 hypothesis(계산 제외). 끝 노드가 제외되면 관계도 제외(§4.1)
    for j in range(n_knowledge - 1):
        t = ("doc_chunk", "requirement", "setpoint", "condition")[j % 4]
        nid = {"doc_chunk": "chunk-", "requirement": "req-", "setpoint": "setpt-", "condition": "cond-"}[t] + "%05d" % j
        ok = node_ok(j)
        kn.append({"id": nid, "node_type": t,
                   "compute_view": {"v4": ok, "excluded_reasons": [] if ok else ["knowledge_status=hypothesis"]}})
        target = objs[(j * 7) % len(objs)]
        if t == "doc_chunk":
            link("part_of", kref(nid), kref("doc-001"), ok)
            if j % 3:
                link("mentions", kref(nid), pref(target), ok and j % 5 != 0,
                     "confirmed" if j % 5 else "candidate")
        else:
            chunk = "chunk-%05d" % (j - j % 4)
            link("specified_in", kref(nid), kref(chunk), ok and node_ok(j - j % 4))
            if j % 6:
                link(algo.APPLY_KIND_OF[t], pref(target), kref(nid), ok)
    kg = {"kg_id": "kg-SYN-P1", "kg_version": "v-synthetic01", "validation": {"status": "passed"},
          "graph_refs": [{"graph_id": graph_id, "graph_version": graph["graph_version"]}], "nodes": kn, "links": kl}
    region = {"region_id": "region-SYN-P1", "region_version": 1,
              "graph_ref": {"graph_id": graph_id, "graph_version": graph["graph_version"]},
              "members": [{"entity_id": n["entity_id"], "tag": n["tag"]} for n in nodes
                          if n["node_type"] == "drawing_object"],
              "focus_entities": [objs[0]],
              "exploration": {"relation_kinds": ["has_endpoint", "measurement_connection", "signal_connection"],
                              "max_depth": 12, "max_reached": 200, "boundary_extension_depth": 0}}
    return graph, kg, [("synthetic-region", region, hashlib.sha256(build.dump_bytes(region)).hexdigest())]


def p1_measure(total_nodes=P1_NODES, repeat=3):
    """합성 그래프에서 각 단계 시간(초, repeat회 중 최솟값). 합격 기준이 아니라 기록용."""
    graph, kg, regions = synthetic(total_nodes)
    start = regions[0][1]["focus_entities"][0]
    full = [tuple(x) for x in json.loads(json.dumps(regions))]
    full[0][1]["exploration"].update(max_depth=100000, max_reached=100000)

    def timed(fn):
        best, out = None, None
        for _ in range(repeat):
            t = time.perf_counter()
            out = fn()
            dt = time.perf_counter() - t
            best = dt if best is None else min(best, dt)
        return round(best, 4), out
    v5 = algo.view_v5(kg, graph)
    rows = {}
    rows["views_V1_V3_V4_V5"], _ = timed(lambda: (algo.view_v1(graph), algo.view_v3(graph), algo.view_v5(kg, graph)))
    rows["A1_sample_limits(depth12,reached200)"], a1 = timed(lambda: algo.a1_propagation(graph, regions, start))
    rows["A1_unlimited"], a1f = timed(lambda: algo.a1_propagation(graph, full, start))
    rows["A2"], _ = timed(lambda: algo.a2_orphans_gaps(kg, graph))
    rows["A3_with_fold"], _ = timed(lambda: algo.a3_degree(v5, graph))
    rows["A4_radius2"], _ = timed(lambda: algo.a4_ego(v5, start, 2))
    rows["A4_radius3"], _ = timed(lambda: algo.a4_ego(v5, start, 3))
    rows["A5_V1_V5"], _ = timed(lambda: algo.a5_components(algo.view_v1(graph), v5))
    rows["analyze_all(A1~A5)"], _ = timed(lambda: algo.analyze(kg, graph, regions, start, 2))
    kinds = {}
    for n in graph["nodes"]:
        kinds[n["node_type"]] = kinds.get(n["node_type"], 0) + 1
    return {"total_nodes": len(graph["nodes"]) + len(kg["nodes"]), "pid_nodes": kinds,
            "pid_edges": len(graph["edges"]), "knowledge_nodes": len(kg["nodes"]), "knowledge_links": len(kg["links"]),
            "V5": {"nodes": v5.number_of_nodes(), "edges": v5.number_of_edges()},
            "a1_reached": {"sample_limits": len(a1["exploration"]["reached"]),
                           "unlimited": len(a1f["exploration"]["reached"])},
            "seconds_min_of_%d" % repeat: rows,
            "environment": {"python": platform.python_version(), "networkx": nx.__version__,
                            "cpu": platform.processor(), "platform": platform.platform(),
                            "measured_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "note": "합격 기준 아님(그래프활용 §7.2 P1). 결정적 합성 그래프, 단일 프로세스, 같은 PC의 다른 부하에 따라 달라짐"}


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-p1", action="store_true")
    args = ap.parse_args(argv)
    failures = []
    print("== 1. 정상 샘플 지식그래프 (%s)" % SAMPLE_PROJECT)
    exp = load_expected()
    graphs = build_kg.load_graphs(build_kg.DEFAULT_GRAPH_ROOT)
    if exp["graph"]["graph_id"] not in {g["graph_id"] for g in graphs}:
        print("  P&ID 그래프 %s 없음 - 먼저 build_graph.py 실행" % exp["graph"]["graph_id"])
        return 1
    if build_kg.main([SAMPLE_PROJECT]) != 0:
        print("  [FAIL] 샘플 지식그래프가 passed가 아님")
        return 1
    _, kg = build.load_outputs(os.path.join(build_kg.DEFAULT_OUT, "kg-%s" % SAMPLE_PROJECT))
    graph = analyze_kg.pick_graph(kg, graphs)
    if (graph["graph_id"], graph["graph_version"]) != (exp["graph"]["graph_id"], exp["graph"]["graph_version"]):
        failures.append("P&ID 그래프 버전이 정답 파일과 다름: %s" % graph["graph_version"])
    if kg["kg_version"] != exp["kg_version_at_creation"]:
        print("  [주의] kg_version %s != 정답 파일 작성 시 %s (샘플 입력이 바뀜 - 아래 비교로 판정)"
              % (kg["kg_version"], exp["kg_version_at_creation"]))
    regions = analyze_kg.load_regions(analyze_kg.DEFAULT_REGION_DIR)
    print("== 2. A1~A5 정답 파일 대조")
    probs, doc = expected_problems(kg, graph, regions, exp)
    for k, ps in probs.items():
        print("  [%s] %s" % ("OK" if not ps else "FAIL", k))
        for p in ps:
            print("      ", p)
            failures.append("%s: %s" % (k, p))
    print("== 3. A1′ ④ 탐색과 일치")
    ps = a1_prime_problems(kg, graph, REGION_FILE)
    print("  [%s] A1′" % ("OK" if not ps else "FAIL"))
    failures += ["A1′: %s" % p for p in ps]
    for p in ps:
        print("      ", p)
    print("== 4. 결정성·결과 쓰기")
    again = algo.analyze(kg, graph, regions, exp["start"], exp["radius"])
    same = build.dump_bytes(again) == build.dump_bytes(doc)
    path = algo.write_result(build_kg.DEFAULT_OUT, doc)
    with open(path, "rb") as fh:
        same = same and fh.read() == build.dump_bytes(doc)
    print("  [%s] 같은 입력 두 번 -> 같은 바이트, 쓴 파일 = 결과 (%s)" % ("OK" if same else "FAIL", path))
    if not same:
        failures.append("결정성")
    if not args.skip_p1:
        print("== 5. P1 성능 기록 (합격 기준 아님)")
        p1 = p1_measure()
        print("  노드 %d (P&ID %s, 지식 %d), 엣지 P&ID %d·지식 %d, V5 %s"
              % (p1["total_nodes"], p1["pid_nodes"], p1["knowledge_nodes"], p1["pid_edges"], p1["knowledge_links"],
                 p1["V5"]))
        print("  환경:", p1["environment"])
        for k, v in p1["seconds_min_of_3"].items():
            print("  %-40s %8.4f s" % (k, v))
        build.write_json_atomic(os.path.join(build_kg.DEFAULT_OUT, P1_FILE), p1)
    print("== 6. unittest tests.test_kg_algo")
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_kg_algo")
    outcome = unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():
        failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
