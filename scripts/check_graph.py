"""단계 ③ 그래프 검사를 한 번에 실행한다 (QA용). 하위 프로세스를 쓰지 않는다.

1) 샘플 추출 -> 그래프 빌드(output/graph/<도면번호>/)
2) 그래프 파일 검사: 구조 검증 통과, 노드·엣지 수 = 추출 결과에서 독립 계산한 값,
   구간 끝점 2개, 대상 매핑 완전(entity_mapping.json 포함), 확인 안 된 흐름 방향 생성 없음, 재빌드 결과 동일
3) 기본 질의 정답 사례(SNP-M-101)
4) tests/ 아래 unittest 전체
종료 코드 0 = 전부 통과.
"""

import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import build_graph  # noqa: E402
import extract_drawio  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.graph.query import GraphQuery  # noqa: E402


def check_one(name, failures):
    with open(os.path.join(build_graph.DEFAULT_EXTRACT, name, "extraction.json"), encoding="utf-8") as fh:
        ex = json.load(fh)
    gpath = os.path.join(build_graph.DEFAULT_OUT, name, "graph.json")
    if not os.path.isfile(gpath) or not os.path.isfile(os.path.join(build_graph.DEFAULT_OUT, name, "structure_report.md")):
        failures.append("%s: graph.json 또는 structure_report.md 없음" % name)
        return
    with open(gpath, encoding="utf-8") as fh:
        g = json.load(fh)
    f = []
    if g["validation"]["status"] != "passed":
        f.append("구조 검증 %s" % g["validation"]["status"])
    kinds = {}
    for r in ex["relations"]:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    phys = kinds.get("physical_connection", 0)
    want_nodes = len(ex["nodes"]) + phys
    want_edges = 2 * phys + kinds.get("signal_connection", 0) + kinds.get("measurement_connection", 0)
    if (len(g["nodes"]), len(g["edges"])) != (want_nodes, want_edges):
        f.append("노드/엣지 %d/%d != 기대 %d/%d" % (len(g["nodes"]), len(g["edges"]), want_nodes, want_edges))
    if g["structure"]["segments_with_endpoint_count_not_2"]:
        f.append("끝점 2개가 아닌 구간 %s" % g["structure"]["segments_with_endpoint_count_not_2"])
    mapped = {m["local_id"] for m in g["entity_mapping"]}
    want = {n["local_id"] for n in ex["nodes"]} | {r["local_id"] for r in ex["relations"]}
    if mapped != want:
        f.append("대상 매핑 불일치 %s" % sorted(want ^ mapped))
    # 흐름 방향: 추출에서 확인된 구간만 가지며, from/to가 추출 관계의 from/to와 같은 대상이어야 한다
    rel = {r["local_id"]: r for r in ex["relations"]}
    local_of = {n["entity_id"]: n["local_id"] for n in g["nodes"]}
    for n in g["nodes"]:
        if n["node_type"] != "pipe_segment":
            continue
        src = rel[n["local_id"]]["flow_direction"]
        fd = n["flow_direction"]
        if fd and not src:
            f.append("확인 안 된 흐름 방향 생성: %s" % n["entity_id"])
        elif src and not fd:
            f.append("확인된 흐름 방향 누락: %s" % n["entity_id"])
        elif fd and (local_of.get(fd["from"]), local_of.get(fd["to"]), fd["from_end"], fd["to_end"]) != \
                (src["from"], src["to"], src["from_end"], src["to_end"]):
            f.append("흐름 방향 from/to 불일치: %s" % n["entity_id"])
    for e in g["edges"]:
        if e["kind"] != "has_endpoint" and e.get("flow_direction") and not rel[e["local_id"]]["flow_direction"]:
            f.append("신호·계측 엣지에 확인 안 된 방향 생성: %s" % e["entity_id"])
    exp_path = os.path.join(build_graph.DEFAULT_OUT, name, "path_expectations.json")
    if not os.path.isfile(exp_path):
        f.append("path_expectations.json 없음")
    else:
        with open(exp_path, encoding="utf-8") as fh:
            if json.load(fh)["graph_version"] != g["graph_version"]:
                f.append("path_expectations.json의 graph_version이 graph.json과 다름")
    mpath = os.path.join(build_graph.DEFAULT_OUT, name, "entity_mapping.json")
    if not os.path.isfile(mpath):
        f.append("entity_mapping.json 없음")
    else:
        with open(mpath, encoding="utf-8") as fh:
            if json.load(fh) != build.entity_mapping_document(g, ex):
                f.append("entity_mapping.json이 graph.json·추출 결과와 다름")
    if g["input_runs"] != [ex["extraction_run_id"]]:
        f.append("input_runs 불일치")
    rebuilt = build.build_graph(ex, extraction_file=g["source"]["extraction_file"])
    if json.dumps(rebuilt, sort_keys=True) != json.dumps(g, sort_keys=True):
        f.append("같은 입력 재빌드 결과가 다름")
    print("  %s: nodes=%d edges=%d 문제 %d건" % (name, len(g["nodes"]), len(g["edges"]), len(f)))
    failures += ["%s: %s" % (name, x) for x in f]


def check_queries(failures):
    with open(os.path.join(build_graph.DEFAULT_OUT, "SNP-M-101", "graph.json"), encoding="utf-8") as fh:
        q = GraphQuery(json.load(fh))
    cases = [
        ("RC-RV01 -> RC-PP01 물리 경로 존재", q.path("RC-RV01", "RC-PP01")["ignoring_direction"]["found"] is True),
        ("RC-RV01 -> RC-PP01 확인된 흐름 경로 존재", q.path("RC-RV01", "RC-PP01")["confirmed_flow_direction"]["found"] is True),
        ("계기 RC-PT101은 물리 경로에서 제외", q.path("RC-RV01", "RC-PT101")["ignoring_direction"]["found"] is False),
        ("계기 RC-PT101은 all 경로에 포함", q.path("RC-RV01", "RC-PT101", "all")["ignoring_direction"]["found"] is True),
        ("RC-V001 -> RC-PP01 방향 미확인 구간 표시",
         len(q.path("RC-V001", "RC-PP01")["ignoring_direction"]["segments_direction_unknown"]) == 1),
        ("물리 연결 성분 1개", len(q.components()["physical_components"]) == 1),
    ]
    for label, ok in cases:
        print("  [%s] %s" % ("OK" if ok else "FAIL", label))
        if not ok:
            failures.append("질의: %s" % label)


def main():
    safe_console()
    failures = []
    print("== 1. 샘플 추출·그래프 빌드")
    if extract_drawio.main(["--samples"]) != 0:
        failures.append("추출 결과에 blocked 있음")
    if build_graph.main([]) != 0:
        failures.append("그래프 빌드 실패 또는 blocked")
    print("== 2. 그래프 파일 검사")
    names = sorted(d for d in os.listdir(build_graph.DEFAULT_EXTRACT)
                   if os.path.isfile(os.path.join(build_graph.DEFAULT_EXTRACT, d, "extraction.json")))
    if len(names) < 6:
        failures.append("추출 결과 %d개 < 6" % len(names))
    for name in names:
        check_one(name, failures)
    print("== 3. 기본 질의")
    check_queries(failures)
    print("== 4. unittest")
    suite = unittest.defaultTestLoader.discover(os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT)
    outcome = unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():
        failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
