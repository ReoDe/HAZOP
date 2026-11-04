"""단계 ② 뷰어 검사를 한 번에 실행한다 (QA용).

1) 샘플 추출 재생성  2) 그래프·뷰어 빌드  3) HTML 정적 검사(데이터 id·SVG 대응·viewBox 범위·외부 참조)
4) tests/ 아래 unittest 전체. 종료 코드 0 = 전부 통과. 하위 프로세스를 쓰지 않는다.
"""

import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import build_graph  # noqa: E402
import build_viewer  # noqa: E402
import extract_drawio  # noqa: E402
from hazop.viewer import check  # noqa: E402


def main():
    failures = []
    print("== 1. 샘플 추출")
    if extract_drawio.main(["--samples"]) != 0:
        failures.append("추출 결과에 blocked 있음")
    print("== 2. 그래프 빌드")
    if build_graph.main([]) != 0:
        failures.append("그래프 빌드 실패 또는 blocked")
    print("== 2b. 뷰어 빌드")
    build_viewer.main([])
    print("== 3. HTML 검사")
    out_root, ex_root = build_viewer.DEFAULT_OUT, build_viewer.DEFAULT_EXTRACT
    names = sorted(d for d in os.listdir(ex_root) if os.path.isfile(os.path.join(ex_root, d, "extraction.json")))
    index_path = os.path.join(out_root, "index.html")
    index = ""
    if os.path.isfile(index_path):
        with open(index_path, encoding="utf-8") as fh:
            index = fh.read()
    if not index:
        failures.append("index.html 없음")
    for ref in check.external_refs(index):
        failures.append("index.html 외부 참조 %r" % ref)
    for name in names:
        page = os.path.join(out_root, name + ".html")
        if not os.path.isfile(page):
            failures.append("%s.html 없음" % name)
            continue
        if 'href="%s.html"' % name not in index:
            failures.append("index.html에 %s 링크 없음" % name)
        with open(os.path.join(ex_root, name, "extraction.json"), encoding="utf-8") as fh:
            extraction = json.load(fh)
        graph = build_viewer.build.load_graph(build_viewer.DEFAULT_GRAPH, name)
        if graph is None:
            failures.append("%s: 그래프 없음" % name)
        with open(page, encoding="utf-8") as fh:
            problems = check.check_drawing_html(fh.read(), extraction, graph)
        print("  %s: 문제 %d건" % (name, len(problems)))
        failures += ["%s: %s" % (name, p) for p in problems]
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
