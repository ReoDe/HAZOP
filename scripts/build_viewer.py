"""출력/추출/<도면번호>/extraction.json -> 출력/뷰어/<도면번호>.html + index.html

추출 결과가 없으면 먼저: python scripts/extract_drawio.py --samples
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.viewer import build  # noqa: E402

DEFAULT_EXTRACT = paths.output_root("extract")  # <작업 루트>/출력 (hazop/paths.py)
DEFAULT_OUT = paths.output_root("viewer")
DEFAULT_GRAPH = paths.output_root("graph")


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract-root", default=DEFAULT_EXTRACT)
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    ap.add_argument("--graph-root", default=DEFAULT_GRAPH, help="그래프 결과 루트('none'이면 그래프 없이 빌드)")
    args = ap.parse_args(argv)
    graph_root = None if args.graph_root == "none" else args.graph_root
    root = paths.work_root()
    # SVG 허용 루트: 작업 루트(첫 번째, 상대 경로 기준), 자원 루트(샘플 원본), 저장 루트(등록 파생 SVG). 그 밖은 거부
    entries = build.build_all(args.extract_root, args.out_root, root, graph_root,
                              svg_roots=[paths.resource_root(), paths.store_root()])
    for e in entries:
        print("%s -> %s (graph: %s)" % (e["drawing_number"], paths.plain_rel(os.path.join(args.out_root, e["file"]), root),
                                        "있음" if e["graph"] else "없음"))
    print("index -> %s" % paths.plain_rel(os.path.join(args.out_root, "index.html"), root))
    return 0 if entries else 1


if __name__ == "__main__":
    sys.exit(main())
