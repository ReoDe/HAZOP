"""데이터/지식/<project_id>/knowledge_*.csv + 출력/그래프/*/graph.json
-> 출력/지식그래프/kg-<project_id>/<kg_version>/knowledge.json + knowledge_graph.json, 그 다음 kg-<project_id>/current.json 교체

근거: 기획서/그래프활용.md §2.6 (CSV -> knowledge.json -> knowledge_graph.json). P&ID 그래프는 읽기만 한다.
그래프가 없으면 먼저: python scripts/build_graph.py
종료 코드: 0 = passed, 1 = blocked, 2 = 입력 오류(CSV 열 규격 등).
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.kg import build, inputs  # noqa: E402

DEFAULT_INPUT_ROOT = paths.folder("knowledge-graph")
DEFAULT_GRAPH_ROOT = paths.output_root("graph")
DEFAULT_OUT = paths.output_root("knowledge-graph")
NODES_CSV = "knowledge_nodes.csv"
LINKS_CSV = "knowledge_links.csv"


def load_graphs(graph_root):
    graphs = []
    for name in sorted(os.listdir(graph_root)) if os.path.isdir(graph_root) else []:
        p = os.path.join(graph_root, name, "graph.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                graphs.append(json.load(fh))
    return graphs


def build_dir(input_dir, project_id, graphs, out_root):
    """입력 폴더 하나를 빌드해 버전 폴더에 두 파일을 쓰고 포인터를 교체한다. (kg, 버전 폴더) 반환."""
    nodes_csv, links_csv = os.path.join(input_dir, NODES_CSV), os.path.join(input_dir, LINKS_CSV)
    knowledge = inputs.load_knowledge(nodes_csv, links_csv, project_id)
    kg = build.build_kg(knowledge, graphs)
    kg_root = paths.safe_join(out_root, paths.safe_name(knowledge["kg_id"]))
    return kg, build.write_outputs(kg_root, knowledge, kg)


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_id", help="%s/ 아래 프로젝트 폴더 이름" % paths.folder_rel("knowledge-graph"))
    ap.add_argument("--input-root", default=DEFAULT_INPUT_ROOT)
    ap.add_argument("--graph-root", default=DEFAULT_GRAPH_ROOT)
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        kg, out_dir = build_dir(paths.safe_join(args.input_root, args.project_id), args.project_id,
                                load_graphs(args.graph_root), args.out_root)
    except (OSError, ValueError) as e:
        print("입력 오류:", e)
        return 2
    s, v = kg["summary"], kg["validation"]
    print("%s %s: %s nodes=%d links=%d V4 nodes=%d links=%d conflicts=%d unknowns=%d blockers=%d -> %s"
          % (kg["kg_id"], kg["kg_version"], v["status"], s["node_count"], s["link_count"], s["v4_nodes"],
             s["v4_links"], s["conflicts"], s["unknowns"], s["blockers"], out_dir))
    for b in v["blockers"]:
        print("  [%s] %s %s: %s" % (b["rule"], b["check"], b["target"], b["reason"]))
    return 0 if v["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
