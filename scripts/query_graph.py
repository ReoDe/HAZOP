"""그래프 기본 질의(검증용). 결과는 JSON으로 출력한다.

사용 예:
  python scripts/query_graph.py SNP-M-101 neighbors RC-PP01
  python scripts/query_graph.py SNP-M-101 path RC-RV01 RC-PP01 --mode physical
  python scripts/query_graph.py SNP-M-101 components
대상은 tag, entity_id, 추출 local_id, 원본 객체 ID 중 하나로 지정한다.
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.graph.query import GraphQuery, QueryError  # noqa: E402

DEFAULT_GRAPH_ROOT = os.path.join(REPO_ROOT, "출력", "그래프")


def load(drawing, graph_root=DEFAULT_GRAPH_ROOT):
    path = os.path.join(paths.safe_join(graph_root, paths.safe_name(drawing)), "graph.json")
    with open(path, encoding="utf-8") as fh:
        return GraphQuery(json.load(fh))


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("drawing", help="도면 번호 (출력/그래프/<도면번호>/graph.json)")
    ap.add_argument("command", choices=["neighbors", "path", "components"])
    ap.add_argument("refs", nargs="*")
    ap.add_argument("--mode", default="physical", choices=["physical", "all"])
    ap.add_argument("--graph-root", default=DEFAULT_GRAPH_ROOT)
    args = ap.parse_args(argv)
    q = load(args.drawing, args.graph_root)
    try:
        if args.command == "neighbors":
            if len(args.refs) != 1:
                ap.error("neighbors는 대상 1개 필요")
            out = q.neighbors(args.refs[0])
        elif args.command == "path":
            if len(args.refs) != 2:
                ap.error("path는 시작·끝 2개 필요")
            out = q.path(args.refs[0], args.refs[1], args.mode)
        else:
            out = q.components()
    except QueryError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
