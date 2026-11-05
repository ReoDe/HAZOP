"""지식그래프 알고리즘 A1~A5 실행 (기획서/그래프활용.md §4).

입력: 출력/지식그래프/kg-<project_id>/current.json이 가리키는 knowledge_graph.json(scripts/build_kg.py로 생성),
      출력/그래프/*/graph.json 중 지식그래프가 참조한 도면, 데이터/구간/*.json(A1 검토 구간).
출력: 출력/지식그래프/kg-<project_id>/algo/<kg_version>/<graph_id>@<graph_version>/<구간 식별자>/<start>-r<radius>/
      algo_result.json + algo_report.md (두 파일을 한 묶음으로 교체)
후보 집계: 데이터/지식/<project_id>/link_candidates.csv가 있으면 미확인 후보 행 수를 함께 기록
예: python scripts/analyze_kg.py SNP-SAMPLE --start entity-node-001 --radius 2
종료 코드: 0 = 계산함, 2 = 입력 오류(blocked 지식그래프, 버전 불일치, 파일 없음 등).
"""

import argparse
import csv
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import build_kg  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.kg import algo, build  # noqa: E402

DEFAULT_REGION_DIR = paths.work_path("데이터", "구간")
CANDIDATES_CSV = "link_candidates.csv"


def load_regions(region_dir, only=None):
    """[(라벨, 구간 dict, 파일 sha256)]. only가 있으면 그 파일 하나만(여러 구간에 속할 때 사용자가 고른 구간)."""
    files = [only] if only else [os.path.join(region_dir, f) for f in sorted(os.listdir(region_dir))
                                  if f.endswith(".json")] if os.path.isdir(region_dir) else []
    out = []
    for p in files:
        with open(p, "rb") as fh:
            raw = fh.read()
        out.append((paths.rel_or_abs(p, paths.work_root()), json.loads(raw.decode("utf-8")),
                     hashlib.sha256(raw).hexdigest()))
    return out


def count_candidates(path):
    """후보 CSV(W4 link_candidates.csv)의 미확인(link_status=candidate) 행 수. 파일이 없으면 None.
    '#'로 시작하는 머리 주석 줄은 건너뛴다."""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        raw = fh.read()
    lines = [l for l in raw.decode("utf-8-sig").splitlines() if not l.startswith("#")]
    rows = list(csv.DictReader(lines))
    if rows and "link_status" not in rows[0]:
        raise ValueError("후보 CSV에 link_status 열이 없음: %s" % path)
    return {"file": paths.rel_or_abs(path, paths.work_root()), "sha256": hashlib.sha256(raw).hexdigest(),
            "unconfirmed_candidates": sum(1 for r in rows if (r.get("link_status") or "").strip() == "candidate")}


def pick_graph(kg, graphs, graph_id=None):
    ids = [r["graph_id"] for r in kg["graph_refs"]]
    if graph_id is None:
        if len(ids) != 1:
            raise algo.AlgoError("지식그래프가 참조한 도면이 %d개 - --graph-id로 고르세요: %s" % (len(ids), ids))
        graph_id = ids[0]
    hits = [g for g in graphs if g["graph_id"] == graph_id]
    if len(hits) != 1:
        raise algo.AlgoError("P&ID 그래프 %s를 하나로 찾지 못함(%d개)" % (graph_id, len(hits)))
    algo.check_inputs(kg, hits[0])  # 참조하지 않은 도면·버전 불일치는 오류
    return hits[0]


def run(project_id, start, radius=2, region=None, graph_id=None, kg_root=None, graph_root=None,
        region_dir=None, out_root=None, input_root=None):
    out_root = out_root or build_kg.DEFAULT_OUT
    kg_root = kg_root or paths.safe_join(out_root, paths.safe_name("kg-%s" % project_id))
    _, kg = build.load_outputs(kg_root)
    graph = pick_graph(kg, build_kg.load_graphs(graph_root or build_kg.DEFAULT_GRAPH_ROOT), graph_id)
    cands = count_candidates(os.path.join(paths.safe_join(input_root or build_kg.DEFAULT_INPUT_ROOT, project_id),
                                          CANDIDATES_CSV))
    doc = algo.analyze(kg, graph, load_regions(region_dir or DEFAULT_REGION_DIR, region), start, radius, cands)
    path = algo.write_result(out_root, doc)
    return doc, path


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_id", help="데이터/지식/ 아래 프로젝트 폴더 이름(지식그래프 kg-<project_id>)")
    ap.add_argument("--start", required=True, help="선택 노드: P&ID entity_id 또는 지식 노드 ID")
    ap.add_argument("--radius", type=int, default=2, help="A4 ego graph 깊이(실제 홉 수, 기본 2)")
    ap.add_argument("--region", help="A1 검토 구간 JSON(여러 구간에 속할 때 고름)")
    ap.add_argument("--graph-id", help="지식그래프가 여러 도면을 참조할 때 계산할 도면")
    ap.add_argument("--out-root", default=build_kg.DEFAULT_OUT)
    ap.add_argument("--graph-root", default=build_kg.DEFAULT_GRAPH_ROOT)
    ap.add_argument("--region-dir", default=DEFAULT_REGION_DIR)
    ap.add_argument("--input-root", default=build_kg.DEFAULT_INPUT_ROOT, help="후보 CSV를 찾을 지식 입력 루트")
    args = ap.parse_args(argv)
    try:
        doc, path = run(args.project_id, args.start, args.radius, args.region, args.graph_id,
                        graph_root=args.graph_root, region_dir=args.region_dir, out_root=args.out_root,
                        input_root=args.input_root)
    except (OSError, ValueError, KeyError) as e:
        print("입력 오류:", e)
        return 2
    print(algo.report_text(doc))
    print("->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
