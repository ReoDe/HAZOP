"""출력/추출/<도면번호>/extraction.json -> 출력/뷰어/<도면번호>.html + index.html

추출 결과가 없으면 먼저: python scripts/extract_drawio.py --samples
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.viewer import build  # noqa: E402

DEFAULT_EXTRACT = os.path.join(REPO_ROOT, "출력", "추출")
DEFAULT_OUT = os.path.join(REPO_ROOT, "출력", "뷰어")
DEFAULT_GRAPH = os.path.join(REPO_ROOT, "출력", "그래프")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract-root", default=DEFAULT_EXTRACT)
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    ap.add_argument("--graph-root", default=DEFAULT_GRAPH, help="그래프 결과 루트('none'이면 그래프 없이 빌드)")
    args = ap.parse_args(argv)
    graph_root = None if args.graph_root == "none" else args.graph_root
    entries = build.build_all(args.extract_root, args.out_root, REPO_ROOT, graph_root)
    for e in entries:
        print("%s -> %s (graph: %s)" % (e["drawing_number"], os.path.relpath(os.path.join(args.out_root, e["file"]), REPO_ROOT),
                                        "있음" if e["graph"] else "없음"))
    print("index -> %s" % os.path.relpath(os.path.join(args.out_root, "index.html"), REPO_ROOT))
    return 0 if entries else 1


if __name__ == "__main__":
    sys.exit(main())
