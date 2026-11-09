"""경로 문자열 금지 검사(docs/2026-11-09-data-consolidation §4 '이전 뒤 재발 방지 장치').

`hazop/paths.py`와 이전 도구 밖의 .py에서 문자열 상수가 `데이터`·`참고자료`·`자원`·`작업` 경로 구성요소면 실패한다.
모듈·클래스·함수 docstring과 "# 경로문자열-허용: <이유>"를 단 줄은 보지 않는다. f-string 안의 고정 부분도 문자열 상수라 함께 걸린다.

    python tests/test_path_literals.py --report   위반 목록
    python -m unittest tests.test_path_literals    테스트
"""

import ast
import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("hazop", "scripts", "packaging", "tests")
ALLOW = {
    "hazop/paths.py",
    "scripts/inventory_data_paths.py",
    "scripts/migrate_data_layout.py",
    "scripts/codemod_data_paths.py",
    "scripts/seed_samples.py",
    "tests/test_path_literals.py",
}
# 사용자 데이터·배치 계약을 그대로 적어야 하는 줄은 끝에 "# 경로문자열-허용: <이유>"를 단다
ALLOW_MARK = "# 경로문자열-허용:"
PATH_PART = re.compile(r"(?:^|[/\\])(데이터|참고자료|자원|작업)(?:[/\\]|$)")


def docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def violations(repo=REPO):
    out = []
    for top in SCAN:
        for d, dirs, files in os.walk(os.path.join(repo, top)):
            dirs[:] = sorted(x for x in dirs if x not in ("__pycache__", "fake_claude") and not x.startswith("."))
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                full = os.path.join(d, f)
                rel = os.path.relpath(full, repo).replace("\\", "/")
                if rel in ALLOW:
                    continue
                try:
                    tree = ast.parse(open(full, encoding="utf-8").read(), rel)
                except SyntaxError as e:
                    out.append((rel, e.lineno or 0, "구문 오류"))
                    continue
                skip = docstring_ids(tree)
                lines = open(full, encoding="utf-8").read().splitlines()
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                            and PATH_PART.search(node.value) and ALLOW_MARK not in lines[node.lineno - 1]):
                        out.append((rel, node.lineno, node.value[:80]))
    return sorted(out)


class PathLiteralTest(unittest.TestCase):
    def test_no_data_path_literals_outside_paths(self):
        found = violations()
        self.assertEqual(found, [], "paths.folder()를 쓰세요:\n" + "\n".join("%s:%d %r" % v for v in found[:50]))


if __name__ == "__main__":
    if "--report" in sys.argv:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        found = violations()
        for v in found:
            print("%s:%d %r" % v)
        files = sorted({v[0] for v in found})
        print("위반 %d건, 파일 %d개" % (len(found), len(files)))
        sys.exit(1 if found else 0)
    unittest.main()
