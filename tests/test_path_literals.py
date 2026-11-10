"""경로 문자열 금지 검사(docs/2026-11-09-data-consolidation §4 '이전 뒤 재발 방지 장치').

`hazop/paths.py`와 이전 도구 밖의 .py에서 문자열 상수가 `데이터`·`참고자료`·`자원`·`작업` 경로 구성요소면 실패한다.
모듈·클래스·함수 docstring과 "# 경로문자열-허용: <이유>"를 단 줄은 보지 않는다. f-string 안의 고정 부분도 문자열 상수라 함께 걸린다.

    python tests/test_path_literals.py --report   위반 목록
    python -m unittest tests.test_path_literals    테스트
"""

import ast
import os
import re
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop import paths  # noqa: E402

SCAN = ("hazop", "scripts", "packaging", "tests")
ALLOW = {
    "hazop/paths.py",
    "scripts/inventory_data_paths.py",
    "scripts/migrate_data_layout.py",
    "scripts/codemod_data_paths.py",
    "scripts/seed_samples.py",
    "tests/test_path_literals.py",
    "tests/test_naming_rules.py",
}
# 사용자 데이터·배치 계약을 그대로 적어야 하는 줄은 끝에 "# 경로문자열-허용: <이유>"를 단다
ALLOW_MARK = "# 경로문자열-허용:"
PATH_PART = re.compile(r"(?:^|[/\\])(데이터|참고자료|자원|작업)(?:[/\\]|$)")
GUIDE_NAME = re.compile(re.escape(paths.FILES["guide"].rel[-1]))


def docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def python_files(repo=REPO, tops=SCAN):
    """git이 추적하는(스테이징 포함) .py만 본다. 같은 체크아웃에서 다른 세션이 둔 추적 안 한 임시 파일 때문에
    모두의 시험이 깨지던 일을 막는다(2026-11-10 교훈). 새 파일은 git add 뒤에 검사된다. git이 없으면 폴더를 훑는다."""
    try:
        r = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--"] + list(tops), capture_output=True)
        if r.returncode == 0:
            rels = r.stdout.decode("utf-8").split("\0")
            return sorted(p for p in rels if p.endswith(".py") and os.path.isfile(os.path.join(repo, p)))
    except OSError:
        pass
    out = []
    for top in tops:
        for d, dirs, files in os.walk(os.path.join(repo, top)):
            dirs[:] = [x for x in dirs if x != "__pycache__" and not x.startswith(".")]
            out += [os.path.relpath(os.path.join(d, f), repo).replace("\\", "/") for f in files if f.endswith(".py")]
    return sorted(out)


def violations(repo=REPO, pattern=PATH_PART, allow=frozenset(ALLOW)):
    out = []
    for rel in python_files(repo):
        if rel in allow or "/fake_claude/" in rel:
            continue
        full = os.path.join(repo, rel)
        try:
            tree = ast.parse(open(full, encoding="utf-8").read(), rel)
        except SyntaxError as e:
            out.append((rel, e.lineno or 0, "구문 오류"))
            continue
        skip = docstring_ids(tree)
        lines = open(full, encoding="utf-8").read().splitlines()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                    and pattern.search(node.value) and ALLOW_MARK not in lines[node.lineno - 1]):
                out.append((rel, node.lineno, node.value[:80]))
    return sorted(out)


class PathLiteralTest(unittest.TestCase):
    def test_no_data_path_literals_outside_paths(self):
        found = violations()
        self.assertEqual(found, [], "paths.folder()를 쓰세요:\n" + "\n".join("%s:%d %r" % v for v in found[:50]))

    def test_guide_location_is_written_once(self):
        """지침서 위치는 paths.FILES["guide"]에만 적는다. 한 곳이라도 따로 적으면 폴더를 옮길 때 그곳만 빠져
        배포본에서만 지침서를 못 찾는다(HZ-GOV-02 §6.5). migrate_doc_headers.py의 같은 글자는 문서번호 표의 열쇠라 위치를 읽지 않는다."""
        found = violations(pattern=GUIDE_NAME, allow=ALLOW | {"scripts/migrate_doc_headers.py"})
        self.assertEqual(found, [], 'paths.file_rel("guide")를 쓰세요:\n' + "\n".join("%s:%d %r" % v for v in found))

    def test_guide_literal_is_caught(self):
        import tempfile
        name = paths.FILES["guide"].rel[-1]
        with tempfile.TemporaryDirectory(prefix="hazop-pathlit-") as tmp:
            os.makedirs(os.path.join(tmp, "scripts"))
            with open(os.path.join(tmp, "scripts", "x.py"), "w", encoding="utf-8") as fh:
                fh.write('"""문서 %s는 설명글이라 보지 않는다."""\nGUIDE = "a/%s"\n' % (name, name))
            found = violations(tmp, GUIDE_NAME)
        self.assertEqual([("scripts/x.py", 2)], [v[:2] for v in found])


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
