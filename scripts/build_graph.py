"""출력/추출/<도면번호>/extraction.json -> 출력/그래프/<도면번호>/graph.json + structure_report.md

추출 결과가 없으면 먼저: python scripts/extract_drawio.py --samples
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.graph.query import GraphQuery  # noqa: E402

DEFAULT_EXTRACT = os.path.join(REPO_ROOT, "출력", "추출")
DEFAULT_OUT = os.path.join(REPO_ROOT, "출력", "그래프")


def build_one(extraction_path, out_root):
    with open(extraction_path, encoding="utf-8") as fh:
        extraction = json.load(fh)
    rel = os.path.relpath(extraction_path, REPO_ROOT).replace("\\", "/")
    graph = build.build_graph(extraction, extraction_file=rel)
    name = paths.safe_name(graph["source"]["drawing_number"] or os.path.basename(os.path.dirname(extraction_path)))
    out_dir = paths.safe_join(out_root, name)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "graph.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(graph, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    with open(os.path.join(out_dir, "structure_report.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build.render_report(graph))
    # 뷰어 JS 경로 함수 대조용 기대값 (scripts/check_viewer_paths.js)
    with open(os.path.join(out_dir, "path_expectations.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(GraphQuery(graph).path_expectations(), fh, ensure_ascii=False, separators=(",", ":"))
    return graph, out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract-root", default=DEFAULT_EXTRACT)
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    blocked = built = 0
    for name in sorted(os.listdir(args.extract_root)):
        path = os.path.join(args.extract_root, name, "extraction.json")
        if not os.path.isfile(path):
            continue
        graph, out_dir = build_one(path, args.out_root)
        s = graph["structure"]
        print("%s: %s nodes=%d edges=%d components_physical=%d unknowns=%d -> %s" % (
            graph["source"]["drawing_number"], graph["validation"]["status"], s["node_count"],
            s["edge_count"], s["components_physical"], len(graph["validation"]["unknowns"]),
            os.path.relpath(out_dir, REPO_ROOT)))
        built += 1
        blocked += graph["validation"]["status"] != "passed"
    return 1 if blocked or not built else 0


if __name__ == "__main__":
    sys.exit(main())
