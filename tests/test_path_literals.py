"""경로 문자열 금지 검사(docs/units/2026-11-09-data-consolidation §4 '이전 뒤 재발 방지 장치').

`hazop/paths.py`와 이전 도구 밖의 .py에서 문자열 상수가 아래 경로 구성요소를 담으면 실패한다(HZ-GOV-02 §6.4).
① 영어로 옮긴 최상위 폴더 이름(`resources`): 문자열 맨 앞이거나 `/` 바로 뒤에 올 때. ② 옮기기 전 한글 폴더 이름
(`데이터`, `자원`, `작업`, `출력`, `자료저장소`, `기호후보` 등). ③ 옮기기 전 작업 루트 안쪽 이름(`그래프`, `분석`, `구간` 등):
화면 문구와 글자가 같아서 `/`가 붙었거나 os.path.join의 인자로 쓰였을 때만. ④ 지금 작업 루트 배치(`output/graph`,
`data/regions`, `work/output` 등)를 이어 적은 것. 이 이름들은 `paths.FOLDERS`와 `paths.OUTPUT_FOLDERS`에만 적는다.
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
    "tests/test_migrate_names.py",
    "tests/test_record_paths.py",
    "tests/test_work_record_paths.py",
    "tests/test_workroot.py",
    "tests/test_workroot_app.py",
    "tests/test_workroot_review.py",
}
# 사용자 데이터·배치 계약을 그대로 적어야 하는 줄은 끝에 "# 경로문자열-허용: <이유>"를 단다
ALLOW_MARK = "# 경로문자열-허용:"
# ① 영어로 옮긴 최상위 폴더. 개발 작업 루트 `work`는 흔한 낱말이라 ④에서 그 아래 폴더와 이어 적은 것만 막는다.
NEW_TOPS = ("resources",)
# ② 옮기기 전 한글 이름. 한 낱말만 적어도(os.path.join(root, "자원")) 걸린다.
OLD_NAMES = ("데이터", "참고자료", "자원", "작업", "출력", "자료저장소", "기호후보")
# ③ 옮기기 전 작업 루트 안쪽 이름(HZ-GOV-02 §5.6). 화면 문구("그래프", "분석", "구간")와 글자가 같아 한 낱말은 두고,
# `/`가 붙었거나 os.path.join의 인자일 때만 막는다.
OLD_INNER = ("기준", "표본", "그래프", "분석", "추출", "지식그래프", "뷰어", "스크린샷", "사용자검증", "디자인검사", "근거묶음", "워크시트",
             "평가비교", "내보내기", "문서지식", "어댑터", "로그", "초기사건", "_보관", "_외부", "구간", "고정응답", "지식", "검토구간",
             "분석결과", "분석결과-시험", "백업", "도면수정", "도면연결", "잠재후보", "캐시", "평가기준")
# ④ 지금 작업 루트 배치. 표에서 읽어 만든다: <작업 루트 최상위>/<그 아래 폴더>, <개발 작업 루트 이름>/<작업 루트 최상위>
WORK_TOPS = sorted({f.rel[0] for f in paths.FOLDERS.values() if f.root == "work"})
WORK_INNER = sorted({f.rel[1] for f in paths.FOLDERS.values() if f.root == "work" and len(f.rel) > 1}
                    | set(paths.OUTPUT_FOLDERS.values()))
SEP = r"[/\\]"
PATH_PART = re.compile(
    "(?:^|%s)(?:%s)(?:%s|$)" % (SEP, "|".join(NEW_TOPS + OLD_NAMES), SEP)
    + "|(?:^|%s)(?:%s)%s" % (SEP, "|".join(OLD_INNER), SEP)
    + "|%s(?:%s)$" % (SEP, "|".join(OLD_INNER))
    + "|(?:^|%s)(?:%s)%s(?:%s)(?:%s|$)" % (SEP, "|".join(WORK_TOPS), SEP, "|".join(WORK_INNER), SEP)
    + "|(?:^|%s)%s%s(?:%s)(?:%s|$)" % (SEP, os.path.basename(paths.DEV_WORK_ROOT), SEP, "|".join(WORK_TOPS), SEP))
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


def join_args(tree):
    """os.path.join(…)처럼 이름이 join인 호출의 인자로 바로 적힌 문자열 상수의 id."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "join":
            ids.update(id(a) for a in node.args if isinstance(a, ast.Constant))
    return ids


def split_layout_args(tree):
    """os.path.join(root, "output", "graph", …)처럼 지금 작업 루트 배치를 인자로 나눠 적은 호출에서, 그 첫 이름 상수의 id.
    이어 적은 글자("output/graph")는 PATH_PART가 잡는다."""
    dev = os.path.basename(paths.DEV_WORK_ROOT)
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "join":
            words = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None for a in node.args]
            for i in range(len(words) - 1):
                if (words[i] in WORK_TOPS and words[i + 1] in WORK_INNER) or (words[i] == dev and words[i + 1] in WORK_TOPS):
                    ids.add(id(node.args[i]))
    return ids


def violations(repo=REPO, pattern=PATH_PART, allow=frozenset(ALLOW), joined=OLD_INNER):
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
        skip, in_join, split = docstring_ids(tree), join_args(tree), split_layout_args(tree)
        lines = open(full, encoding="utf-8").read().splitlines()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                    and (pattern.search(node.value) or (id(node) in in_join and node.value in joined) or id(node) in split)
                    and ALLOW_MARK not in lines[node.lineno - 1]):
                out.append((rel, node.lineno, node.value[:80]))
    return sorted(out)


class PathLiteralTest(unittest.TestCase):
    def test_no_data_path_literals_outside_paths(self):
        found = violations()
        self.assertEqual(found, [], "paths.folder()를 쓰세요:\n" + "\n".join("%s:%d %r" % v for v in found[:50]))

    def test_pattern_catches_new_top_folder_and_old_korean_names(self):
        hits = ("resources", "resources/library", "a/resources/b", "..\\resources", "자원", "자원/기준/기호", "x/참고자료",
                "작업\\출력", "자원/표본", "표본/구간", "기준/기호", "a/표본", "출력/그래프/x/graph.json", "출력/samples",
                "자료저장소/p/originals", "x/자료저장소", "기호후보/a", "분석/region-x", "지식그래프/kg", "_보관/t1", "a\\추출",
                "출력", "자료저장소", "기호후보", "데이터/구간", "구간/region-x.json", "output/graph/x/graph.json", "data/regions",
                "x/output/_archive", "work/output", "work\\store\\p", "data/backup/t1", "output/samples/extract")
        misses = ("resource", "my-resources/x", "resources.json", "표본", "기준", "기준표", "표본검사", "자원 루트", "work",
                  "library/x", "그래프", "분석", "지식그래프", "분석결과", "출력 루트", "추출·그래프 만들기", "구간", "output", "store",
                  "data", "output/x.json", "data/fixtures", "work/tmp", "graph/SNP-M-102", "tests/fixtures/data/a.json")
        self.assertEqual([], [t for t in hits if not PATH_PART.search(t)])
        self.assertEqual([], [t for t in misses if PATH_PART.search(t)])

    def test_old_inner_name_as_join_argument_is_caught(self):
        """os.path.join(root, "분석", …)은 한 낱말이라 패턴에 안 걸리므로 join의 인자인지로 잡는다. 화면 문구로 쓴 것은 둔다."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hazop-pathlit-") as tmp:
            os.makedirs(os.path.join(tmp, "scripts"))
            with open(os.path.join(tmp, "scripts", "x.py"), "w", encoding="utf-8") as fh:
                fh.write('import os\nfrom hazop import paths\nA = os.path.join("w", "분석", "x")\n'
                         'B = os.path.join("w", "구간")\nC = paths.folder("output")\nD = paths.output_root("graph")\n'
                         'E = "분석"\nF = "분석/x"\nG = label("그래프")\n')
            found = violations(tmp)
        self.assertEqual([("scripts/x.py", 3), ("scripts/x.py", 4), ("scripts/x.py", 8)], [v[:2] for v in found])

    def test_layout_split_into_join_arguments_is_caught(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hazop-pathlit-") as tmp:
            os.makedirs(os.path.join(tmp, "scripts"))
            with open(os.path.join(tmp, "scripts", "x.py"), "w", encoding="utf-8") as fh:
                fh.write('import os\nA = os.path.join(root, "output", "graph", "x.json")\nB = os.path.join(root, "data", "regions")\n'
                         'C = os.path.join(repo, "work", "store")\nD = os.path.join(tmp, "output", "x.json")\n'
                         'E = os.path.join(tmp, "work", "tmp")\nF = os.path.join(tmp, "store")\nG = os.path.join(tmp, "graph", "a")\n')
            found = violations(tmp)
        self.assertEqual([("scripts/x.py", 2), ("scripts/x.py", 3), ("scripts/x.py", 4)], [v[:2] for v in found])

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
