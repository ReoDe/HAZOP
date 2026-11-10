"""이름 규칙 검사 N1~N11 (docs/2026-11-10-naming-rules/README.md, HZ-GOV-02 §4와 §8.1).

git이 추적하는 파일만 본다. 규칙을 들이기 전부터 있던 위반은 `EXEMPT` 표에 이전 단계별로 적어 두었다.
단계를 마치면 그 단계의 줄을 지운다. 위반이 사라졌는데 줄이 남아 있으면 `test_exempt_rows_still_match`가 실패한다.

    python tests/test_naming_rules.py --report    지금의 위반과 예외 처리 여부
    python -m unittest tests.test_naming_rules     시험
"""

import collections
import fnmatch
import os
import posixpath
import re
import subprocess
import sys
import unittest
import urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMING_DOC = "docs/2026-11-10-naming-rules/README.md"

# N10은 이 커밋 뒤의 커밋만 본다(§4.10 '단계 0의 커밋부터 적용').
COMMIT_BASE = "d0a0370"

Violation = collections.namedtuple("Violation", "rule subject detail")
Ref = collections.namedtuple("Ref", "line kind start end value")

# 단계 번호 -> [(규칙, 대상 패턴, 이유)]. 패턴은 fnmatch이고 `*`는 `/`도 넘는다.
EXEMPT = {
    "상시": [
        ("N1", "licenses/*", "제3자 고지 원문의 파일 이름을 그대로 둔다"),
        ("N1", "hazop/kg/vendor/*", "가져온 제3자 파일(SHA-256 고정)"),
        ("N1", "tests/fixtures/apr1400/*", "DCD 원본 파일 이름이 기준값의 키다"),
        ("N8", "* @ " + NAMING_DOC, "대응표가 옛 이름을 일부러 적는다"),
        ("N9", "docs/2026-11-05-packaging/evidence/w5-* -> HAZOP기법지침.md", "기획서 문장을 인용한 줄 안의 링크"),
    ],
    2: [
        ("N1", "docs/2026-11-05-*/evidence/*", "§5.4 근거 문서"),
        ("N1", "docs/2026-11-09-symbol-library/*", "§5.4 CSV 5개와 그림 폴더"),
        ("N1", "docs/2026-11-10-lessons/*", "§5.4"),
        ("N1", "docs/2026-11-10-plan/*", "§5.4"),
        ("N3", "docs/screenshots-pdf", "날짜 없는 작업 공간"),
        ("N3", "docs/2026-11-07-drawing-edit", "README 없음"),
        ("N3", "docs/2026-11-09-dev-framework", "README 없음"),
        ("N3", "docs/2026-11-10-plan", "README 없음"),
    ],
    3: [
        ("N1", "기획서/*", "specs/로 옮긴다"),
        ("N1", "flow chart/*", "specs/flows/로 옮긴다"),
        ("N1", "디자인/*", "design/으로 옮긴다"),
        ("N1", "지식/*", "methodology/로 옮긴다"),
        ("N1", "메모리/*", "records/로 옮긴다"),
        ("N1", "packaging/다른PC-점검표.md", "other-pc-checklist.md"),
        ("N2", "기획서", ""), ("N2", "flow chart", ""), ("N2", "디자인", ""), ("N2", "지식", ""), ("N2", "메모리", ""),
        ("N6", "INTENT.md", "문서 머리는 단계 3에서 단다"),
        ("N8", "기획서/ @ *", ""), ("N8", "flow chart/ @ *", ""), ("N8", "디자인/ @ *", ""),
        ("N8", "지식/ @ *", ""), ("N8", "메모리/ @ *", ""),
    ],
    4: [
        ("N1", "tests/fixtures/docextract/SNP-DOC-102_*", "시험 입력 PDF"),
    ],
    5: [
        ("N1", "자원/*", "resources/로 옮긴다"),
        ("N2", "자원", ""),
        ("N8", "자원/ @ *", ""),
    ],
    6: [
        ("N8", "작업/ @ *", ""),
    ],
}

# ---------------------------------------------------------------- N1, N2
CONVENTION_FILES = {"README.md", "CLAUDE.md", "AGENTS.md", "INTENT.md", "PROGRESS.md", "ROADMAP.md", "SKILL.md"}
# 대문자를 써도 되는 고유명사와 도면번호(§4.1)
PROPER_NOUNS = re.compile(r"APR1400|SNP-[A-Z]+(?:-\d+)?|[LD]\d+-\d+")
SAFE_CHARS = re.compile(r"[A-Za-z0-9._-]*\Z")
TOP_LEVEL = {
    "hazop", "scripts", "tests", "packaging", "licenses", "specs", "design", "methodology", "records", "resources",
    "work", "docs", "CLAUDE.md", "INTENT.md", "README.md", ".claude", ".github", ".gitignore", ".gitattributes",
}


def component_problem(name):
    if not SAFE_CHARS.match(name):
        return "한글·공백·특수문자"
    if name not in CONVENTION_FILES and re.search(r"[A-Z]", PROPER_NOUNS.sub("", name)):
        return "대문자"
    return None


def n1_path_chars(paths):
    out = []
    for p in paths:
        bad = ["%s(%s)" % (c, why) for c in p.split("/") for why in [component_problem(c)] if why]
        if bad:
            out.append(Violation("N1", p, ", ".join(bad)))
    return out


def n2_top_level(paths):
    tops = sorted({p.split("/")[0] for p in paths})
    return [Violation("N2", t, "§4.2 목록에 없는 최상위 이름") for t in tops if t not in TOP_LEVEL]


# ---------------------------------------------------------------- N3, N4, N5, N7
WORKSPACE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*\Z")
SCRIPT_VERBS = {
    "check", "build", "extract", "export", "shoot", "run", "analyze", "migrate", "seed", "register", "clean", "query",
    "link", "compare", "bench", "refresh", "inventory",
}
SCRIPTS_WITHOUT_VERB = {
    "devenv", "preflight", "desktop_lease", "codemod_data_paths", "unknowns_breakdown", "apr1400_key_overlay",
    "degrade_raster",
}
HAND_VERSION = re.compile(r"(_v\d+|_draft|_final|-new)(?=[._-]|\Z)|복사본")
TEST_CASE = re.compile(r"^class\s+\w+\(.*TestCase.*\):", re.MULTILINE)


def n3_docs_workspaces(paths):
    spaces = sorted({p.split("/")[1] for p in paths if p.startswith("docs/") and p.count("/") >= 2})
    out = []
    for name in spaces:
        if not WORKSPACE.match(name):
            out.append(Violation("N3", "docs/" + name, "이름이 YYYY-MM-DD-<slug>가 아니다"))
        if "docs/%s/README.md" % name not in paths:
            out.append(Violation("N3", "docs/" + name, "README.md가 없다"))
    return out


def n4_script_verbs(paths):
    out = []
    for p in paths:
        m = re.match(r"scripts/([^/]+)\.py\Z", p)
        if m and m.group(1) not in SCRIPTS_WITHOUT_VERB and m.group(1).split("_")[0] not in SCRIPT_VERBS:
            out.append(Violation("N4", p, "접두가 §4.4 동사 목록에 없다"))
    return out


def n5_test_files(py_sources):
    """시험 클래스가 든 파일 이름이 test_*.py가 아니면 unittest discover가 조용히 건너뛴다."""
    return [Violation("N5", p, "TestCase가 있는데 이름이 test_*.py가 아니다")
            for p, text in sorted(py_sources.items())
            if p.startswith("tests/") and not posixpath.basename(p).startswith("test_") and TEST_CASE.search(text)]


def n7_hand_versions(paths):
    out = []
    for p in paths:
        bad = [c for c in p.split("/") if HAND_VERSION.search(c)]
        if bad:
            out.append(Violation("N7", p, "손 버전 이름: " + ", ".join(bad)))
    return out


# ---------------------------------------------------------------- N6
HEADER_TARGETS = (
    "specs/*.md", "specs/flows/*.md", "design/*.md", "methodology/*.md", "records/*.md", "INTENT.md", NAMING_DOC,
    "packaging/other-pc-checklist.md",
)
HEADER_KEYS = ("doc_id", "rev", "status", "author", "reviewed", "approved")
DOC_ID = re.compile(r"HZ-(PLN|FLW|DSN|MTH|REC|GOV|CHK)-\d{2}\Z")
STATUSES = {"draft", "review", "approved", "obsolete"}


def is_header_target(path):
    return any(fnmatch.fnmatchcase(path, g) and path.count("/") == g.count("/") for g in HEADER_TARGETS)


def front_matter(text):
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    head = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return head
        key, sep, value = line.partition(":")
        if sep:
            head[key.strip()] = re.sub(r"\s+#.*", "", value).strip()
    return None


def n6_doc_headers(docs):
    out, seen = [], {}
    for path, text in sorted(docs.items()):
        head = front_matter(text)
        if head is None:
            out.append(Violation("N6", path, "문서 머리가 없다"))
            continue
        problems = ["%s 없음" % k for k in HEADER_KEYS if not head.get(k)]
        doc_id = head.get("doc_id", "")
        if doc_id and not DOC_ID.match(doc_id):
            problems.append("doc_id 형식: %s" % doc_id)
        if doc_id in seen:
            problems.append("doc_id %s가 %s와 겹친다" % (doc_id, seen[doc_id]))
        seen.setdefault(doc_id, path)
        if head.get("status") and head["status"] not in STATUSES:
            problems.append("status: %s" % head["status"])
        if head.get("status") == "approved" and head.get("approved") in ("—", "-"):
            problems.append("status가 approved인데 approved가 비었다")
        if problems:
            out.append(Violation("N6", path, ", ".join(problems)))
    return out


# ---------------------------------------------------------------- 문서 안의 링크와 백틱 경로 (N8, N9, 이전 도구가 함께 쓴다)
FENCE = re.compile(r"\s*(```|~~~)")
CODE_SPAN = re.compile(r"(`+)(.+?)\1")
MD_LINK = re.compile(r"\]\(\s*(<[^>]*>|(?:[^()\s]|\([^()]*\))+(?: (?![\"'])(?:[^()\s]|\([^()]*\))+)*)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
# 꺾쇠 없이 공백이 든 대상은 경로처럼 생겼을 때만 링크로 본다. '[사실](같은 출처)' 같은 본문 괄호를 거른다.
PATH_LIKE = re.compile(r"/|\.[A-Za-z0-9]{1,5}(?:#|\Z)")
HTML_ATTR = re.compile(r"""\b(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
HTML_CODE = re.compile(r"<code[^>]*>(.*?)</code>", re.IGNORECASE)


def doc_refs(path, text):
    """문서에서 링크 대상(kind='link')과 백틱·<code> 안의 글(kind='code')을 줄 번호, 줄 안 위치와 함께 낸다.
    마크다운의 코드 울타리 안은 보지 않는다."""
    refs, fenced = [], False
    is_html = path.lower().endswith(".html")
    for no, line in enumerate(text.splitlines(), 1):
        if is_html:
            for m in HTML_ATTR.finditer(line):
                g = 1 if m.group(1) is not None else 2
                refs.append(Ref(no, "link", m.start(g), m.end(g), m.group(g)))
            for m in HTML_CODE.finditer(line):
                refs.append(Ref(no, "code", m.start(1), m.end(1), m.group(1)))
            continue
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        spans = [(m.start(2), m.end(2)) for m in CODE_SPAN.finditer(line)]
        refs += [Ref(no, "code", s, e, line[s:e]) for s, e in spans]
        for m in MD_LINK.finditer(line):
            if any(s <= m.start() < e for s, e in spans):
                continue
            s, e = m.span(1)
            if line[s] == "<":
                s, e = s + 1, e - 1
            elif " " in line[s:e] and not PATH_LIKE.search(line[s:e]):
                continue
            refs.append(Ref(no, "link", s, e, line[s:e]))
    return refs


def link_path(target):
    """링크 대상에서 저장소 안 경로 부분만 낸다. 바깥 주소나 문서 안 닻이면 None."""
    target = target.strip()
    if not target or target.startswith(("#", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    return urllib.parse.unquote(re.split(r"[#?]", target, 1)[0]) or None


def resolve(doc_path, rel):
    """문서 기준 상대 경로를 저장소 기준으로 바꾼다. 저장소 밖으로 나가면 None."""
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), rel.replace("\\", "/")))
    return None if joined.startswith("..") or joined.startswith("/") else joined


# ---------------------------------------------------------------- N8, N9
OLD_TOPS = ("기획서", "디자인", "메모리", "지식", "자원", "작업", "flow chart")
OLD_TOP_IN_CODE = re.compile(r"^(?:\./|(?:\.\./)+|[A-Za-z]:[\\/]HAZOP[\\/])?(%s)[\\/]" % "|".join(OLD_TOPS))
THIRD_PARTY = ("licenses/", "hazop/kg/vendor/")


def is_doc(path):
    return path.lower().endswith((".md", ".html")) and not path.startswith(THIRD_PARTY)


def n8_old_korean_paths(docs):
    out = []
    for path, text in sorted(docs.items()):
        hits = collections.defaultdict(list)
        for ref in doc_refs(path, text):
            if ref.kind == "code":
                m = OLD_TOP_IN_CODE.match(ref.value.strip())
                top = m.group(1) if m else None
            else:
                target = resolve(path, link_path(ref.value) or "") if link_path(ref.value) else None
                top = target.split("/")[0] if target and target.split("/")[0] in OLD_TOPS and "/" in target else None
            if top:
                hits[top].append(ref.line)
        for top, lines in sorted(hits.items()):
            out.append(Violation("N8", "%s/ @ %s" % (top, path), "줄 " + ", ".join(map(str, sorted(set(lines))[:8]))))
    return out


def n9_broken_links(docs, exists):
    out = []
    for path, text in sorted(docs.items()):
        if not path.lower().endswith(".md"):
            continue
        for ref in doc_refs(path, text):
            rel = link_path(ref.value) if ref.kind == "link" else None
            if rel is None:
                continue
            target = resolve(path, rel)
            if target is None or not exists(target):
                out.append(Violation("N9", "%s -> %s" % (path, ref.value), "줄 %d: 링크 대상이 없다" % ref.line))
    return out


# ---------------------------------------------------------------- N10, N11
COMMIT_SUBJECT = re.compile(r"(feat|fix|docs|test|refactor|perf|build|chore|baseline)(\([a-z0-9-]+\))?!?: \S")
HANGUL = re.compile(r"[가-힣]")
BRANCH = re.compile(r"(feat|fix|docs|chore|refactor|test)/[a-z0-9]+(-[a-z0-9]+){0,3}\Z")


def n10_commit_subjects(subjects):
    out = []
    for s in subjects:
        if not COMMIT_SUBJECT.match(s):
            out.append(Violation("N10", s, "제목이 '<종류>(<범위>): <요약>' 꼴이 아니다(§4.10)"))
        elif not HANGUL.search(s.split(": ", 1)[1]):
            out.append(Violation("N10", s, "요약에 한글이 없다(§4.10)"))
    return out


def n11_branch(name):
    if name == "main" or BRANCH.match(name):
        return []
    return [Violation("N11", name, "브랜치 이름이 '<종류>/<slug>'가 아니다(§4.9)")]


# ---------------------------------------------------------------- 저장소 읽기
def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off"] + list(args), capture_output=True)


def tracked_files(repo=REPO):
    r = _git(repo, "ls-files", "-z")
    if r.returncode != 0:
        raise RuntimeError("git ls-files 실패: %s" % r.stderr.decode("utf-8", "replace"))
    return sorted(p for p in r.stdout.decode("utf-8").split("\0") if p)


def read_texts(paths, repo=REPO):
    out = {}
    for p in paths:
        full = os.path.join(repo, p)
        if os.path.isfile(full):
            with open(full, encoding="utf-8", errors="replace") as f:
                out[p] = f.read()
    return out


def commit_subjects_since(base=COMMIT_BASE, repo=REPO):
    """기준 커밋 뒤의 커밋 제목(병합 커밋 제외). 얕은 체크아웃처럼 기준 커밋이 이력에 없으면 None."""
    if _git(repo, "merge-base", "--is-ancestor", base, "HEAD").returncode != 0:
        return None
    r = _git(repo, "log", "--no-merges", "--format=%s", "%s..HEAD" % base)
    return r.stdout.decode("utf-8").splitlines() if r.returncode == 0 else None


def current_branch(repo=REPO, env=None):
    """현재 브랜치 이름. GitHub Actions의 PR 실행은 분리된 HEAD라서 GITHUB_HEAD_REF를 먼저 본다. 알 수 없으면 None."""
    env = os.environ if env is None else env
    if env.get("GITHUB_HEAD_REF"):
        return env["GITHUB_HEAD_REF"]
    r = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    return r.stdout.decode("utf-8").strip() or None if r.returncode == 0 else None


def file_violations(repo=REPO):
    paths = tracked_files(repo)
    tracked = set(paths)
    dirs = {p[:i] for p in paths for i, ch in enumerate(p) if ch == "/"}
    docs = read_texts([p for p in paths if is_doc(p)], repo)
    tests_py = read_texts([p for p in paths if p.startswith("tests/") and p.endswith(".py")], repo)
    return (n1_path_chars(paths) + n2_top_level(paths) + n3_docs_workspaces(tracked) + n4_script_verbs(paths)
            + n5_test_files(tests_py) + n6_doc_headers({p: t for p, t in docs.items() if is_header_target(p)})
            + n7_hand_versions(paths) + n8_old_korean_paths(docs)
            + n9_broken_links(docs, lambda t: t in tracked or t in dirs))


def exempt_row(violation):
    for stage, rows in EXEMPT.items():
        for rule, pattern, _why in rows:
            if rule == violation.rule and fnmatch.fnmatchcase(violation.subject, pattern):
                return stage, rule, pattern
    return None


def unexempted(violations):
    return [v for v in violations if exempt_row(v) is None]


def _lines(violations, limit=40):
    return "\n".join("%s %s: %s" % v for v in violations[:limit])


# ---------------------------------------------------------------- 시험
class RepoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = file_violations()

    def test_tracked_files_follow_rules(self):
        left = unexempted(self.found)
        self.assertEqual([], left, "이름 규칙(%s §4) 위반 %d건:\n%s" % (NAMING_DOC, len(left), _lines(left)))

    def test_exempt_rows_still_match(self):
        used = {exempt_row(v) for v in self.found}
        stale = [(stage, rule, pattern) for stage, rows in EXEMPT.items() for rule, pattern, _w in rows
                 if (stage, rule, pattern) not in used]
        self.assertEqual([], stale, "위반이 없어진 예외 줄은 EXEMPT에서 지운다")

    def test_commit_subjects(self):
        subjects = commit_subjects_since()
        if subjects is None:
            self.skipTest("기준 커밋 %s이 이 체크아웃의 이력에 없다" % COMMIT_BASE)
        self.assertEqual([], n10_commit_subjects(subjects))

    def test_branch_name(self):
        name = current_branch()
        if name is None:
            self.skipTest("분리된 HEAD라 브랜치 이름을 알 수 없다")
        self.assertEqual([], n11_branch(name))


class PastViolationTest(unittest.TestCase):
    """검사마다 이 저장소에서 실제로 있었던 위반을 넣어 실패하는지 본다."""

    def rules(self, violations):
        return [v.rule for v in violations]

    def test_n1_korean_space_ampersand_uppercase(self):
        bad = ["기획서/전체기획.md", "자원/참고자료/P&ID 도면 샘플/SNP-M-101_RCS-main-loop/a.drawio",
               "tests/fixtures/docextract/SNP-DOC-102_가압기압력제어_설계설명서(가상).pdf", "docs/2026-11-10-plan/Notes.md"]
        self.assertEqual(bad, [v.subject for v in n1_path_chars(bad)])
        good = ["specs/overview.md", "docs/2026-11-05-packaging/PROGRESS.md", "scripts/check_apr1400.py",
                "tests/fixtures/kg_algo/expected_SNP-SAMPLE.json", "docs/2026-11-09-symbol-library/figures/legend/L1-001.png",
                "tests/fixtures/docextract/SNP-DOC-102-pzr-pressure-control-design-description-fictional.pdf"]
        self.assertEqual([], n1_path_chars(good))

    def test_n2_top_level(self):
        self.assertEqual(["notes", "데이터"], [v.subject for v in n2_top_level(["notes/a.md", "데이터/기준표/x.json", "hazop/a.py"])])

    def test_n3_workspace_name_and_readme(self):
        paths = {"docs/screenshots-pdf/README.md", "docs/2026-11-10-plan/pstack-advice.md",
                 "docs/2026-11-10-lessons/README.md"}
        self.assertEqual([("docs/2026-11-10-plan", "README.md가 없다"), ("docs/screenshots-pdf", "이름이 YYYY-MM-DD-<slug>가 아니다")],
                         [(v.subject, v.detail) for v in n3_docs_workspaces(paths)])

    def test_n4_script_verb(self):
        found = n4_script_verbs(["scripts/helper.py", "scripts/check_naming.py", "scripts/devenv.py", "scripts/sub/x.py"])
        self.assertEqual(["scripts/helper.py"], [v.subject for v in found])

    def test_n5_test_class_outside_test_file(self):
        sources = {"tests/check_x.py": "import unittest\nclass XTest(unittest.TestCase):\n    pass\n",
                   "tests/run_fixture.py": "def main():\n    pass\n",
                   "tests/test_y.py": "import unittest\nclass YTest(unittest.TestCase):\n    pass\n"}
        self.assertEqual(["tests/check_x.py"], [v.subject for v in n5_test_files(sources)])

    def test_n6_header(self):
        head = "---\ndoc_id: %s\nrev: 1\nstatus: %s\nauthor: a\nreviewed: —\napproved: %s\n---\n# 제목\n"
        docs = {
            "specs/a.md": head % ("HZ-PLN-01", "review", "—"),
            "specs/b.md": head % ("HZ-PLN-01", "review", "—"),
            "specs/c.md": head % ("HZ-PLN-3", "done", "—"),
            "specs/d.md": head % ("HZ-PLN-04", "approved", "—"),
            "specs/e.md": "# 머리 없는 문서\n",
            "specs/f.md": head % ("HZ-PLN-06", "approved  # 주석", "director 2026-11-10"),
        }
        found = {v.subject: v.detail for v in n6_doc_headers(docs)}
        self.assertEqual({"specs/b.md", "specs/c.md", "specs/d.md", "specs/e.md"}, set(found))
        self.assertIn("겹친다", found["specs/b.md"])
        self.assertIn("doc_id 형식", found["specs/c.md"])
        self.assertIn("status: done", found["specs/c.md"])
        self.assertIn("approved가 비었다", found["specs/d.md"])

    def test_n6_targets(self):
        self.assertTrue(is_header_target("specs/overview.md"))
        self.assertTrue(is_header_target("INTENT.md"))
        self.assertFalse(is_header_target("design/mockups/README.md"))
        self.assertFalse(is_header_target("docs/2026-11-05-packaging/README.md"))

    def test_n7_hand_versions(self):
        bad = ["자원/참고자료/APR1400_DCD/계통약어_v2.csv", "x/계통약어_draft.csv", "x/u1_final.tar", "x/plan-new.md",
               "x/보고서 복사본.md"]
        self.assertEqual(bad, [v.subject for v in n7_hand_versions(bad)])
        self.assertEqual([], n7_hand_versions(["scripts/check_version_migration.py", "x/w11-final-build.md",
                                               "x/newline-check.md", "x/dev-news.md"]))

    def test_n8_old_korean_top_level(self):
        docs = {
            ".claude/agents/hazop-planner.md": "기획서는 `기획서/` 아래에 쓴다.\n",
            "README.md": "[인터페이스](기획서/인터페이스.md)와 `D:\\HAZOP\\작업\\출력`\n",
            "docs/2026-11-10-plan/a.md": "[결정로그](../../메모리/결정로그.md)\n",
            "records/decision-log.md": "기획서/전체기획.md를 고쳤다. 작업 루트의 `데이터/지식/`을 본다.\n",
            "x.html": '<a href="flow chart/00-overview.md">흐름</a> <code>자원/기준/</code>\n',
        }
        self.assertEqual(
            ["기획서/ @ .claude/agents/hazop-planner.md", "기획서/ @ README.md", "작업/ @ README.md",
             "메모리/ @ docs/2026-11-10-plan/a.md", "flow chart/ @ x.html", "자원/ @ x.html"],
            [v.subject for v in n8_old_korean_paths(docs)])

    def test_n9_broken_relative_link(self):
        docs = {"README.md": "[인터페이스](기획서/인터페이스.md) [규격](specs/interface.md#화면) [밖](https://example.com) [닻](#a)\n"
                             "`[코드](없음.md)`\n```\n[울타리](없음.md)\n```\n[폴더](docs/) [위](../밖.md)\n"}
        found = n9_broken_links(docs, {"specs/interface.md", "docs"}.__contains__)
        self.assertEqual(["README.md -> 기획서/인터페이스.md", "README.md -> ../밖.md"], [v.subject for v in found])

    def test_n9_link_forms(self):
        text = "[공백](<flow chart/00-overview.md>) [꺾쇠 없음](flow chart/01.md) [사실: 시험](같은 출처) [괄호](a/설명서(가상).pdf) [제목](b.md \"제목\") [인코딩](c%20d.md)\n"
        self.assertEqual(["flow chart/00-overview.md", "flow chart/01.md", "a/설명서(가상).pdf", "b.md", "c%20d.md"],
                         [r.value for r in doc_refs("x.md", text) if r.kind == "link"])
        self.assertEqual("c d.md", link_path("c%20d.md#절"))

    def test_n10_commit_subject(self):
        bad = ["Add the core of the P&ID graph", "단위 B 검토 지적을 고친다", "ci: 워크플로의 YAML 문법 오류를 고친다",
               "docs: fix typos", "feat:요약을 붙여 쓴다", "Feat(Study): 대문자 종류"]
        self.assertEqual(bad, [v.subject for v in n10_commit_subjects(bad)])
        good = ["docs(naming): 이름 규칙 확정본과 이전 계획을 남긴다", "refactor(paths)!: 작업 루트 폴더 이름을 영어로 바꾼다",
                "test: 이름 규칙 검사를 넣는다"]
        self.assertEqual([], n10_commit_subjects(good))

    def test_n11_branch(self):
        for name in ("worktree-agent-a1c5c7a98a4e905b2", "claude/pdf-extract-fix-b525b8", "my-branch",
                     "feat/a-b-c-d-e", "Feat/x"):
            self.assertEqual(["N11"], self.rules(n11_branch(name)), name)
        for name in ("main", "feat/next-units", "chore/naming-migration"):
            self.assertEqual([], n11_branch(name), name)

    def test_exempt_row_is_per_rule(self):
        self.assertIsNotNone(exempt_row(Violation("N1", "자원/기준/기호/묶음.json", "")))
        self.assertIsNone(exempt_row(Violation("N7", "자원/참고자료/APR1400_DCD/계통약어_v2.csv", "")))
        self.assertIsNone(exempt_row(Violation("N1", "notes/새문서.md", "")))


class CheckoutShapeTest(unittest.TestCase):
    """GitHub Actions의 얕은 체크아웃과 분리된 HEAD에서 N10·N11이 실패가 아니라 건너뜀이 되는지 본다."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(prefix="hazop-naming-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        self.git("init", "-q", "-b", "feat/sample")
        self.git("commit", "-q", "--allow-empty", "-m", "docs: 첫 커밋")

    def git(self, *args):
        r = subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "-c", "commit.gpgsign=false"] + list(args), capture_output=True)
        self.assertEqual(0, r.returncode, r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode("utf-8").strip()

    def test_base_commit_missing_is_none(self):
        self.assertIsNone(commit_subjects_since(COMMIT_BASE, self.repo))

    def test_subjects_after_base(self):
        base = self.git("rev-parse", "HEAD")
        self.git("commit", "-q", "--allow-empty", "-m", "Add something")
        self.assertEqual(["Add something"], commit_subjects_since(base, self.repo))

    def test_branch_and_detached_head(self):
        self.assertEqual("feat/sample", current_branch(self.repo, {}))
        self.git("checkout", "-q", "--detach")
        self.assertIsNone(current_branch(self.repo, {}))
        self.assertEqual("feat/from-pr", current_branch(self.repo, {"GITHUB_HEAD_REF": "feat/from-pr"}))


if __name__ == "__main__":
    if "--report" in sys.argv:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        found = file_violations()
        counts = collections.Counter((str(exempt_row(v)[0]) if exempt_row(v) else "예외 없음", v.rule) for v in found)
        for v in unexempted(found):
            print("%s %s: %s" % v)
        for (stage, rule), n in sorted(counts.items()):
            print("단계 %s %s: %d건" % (stage, rule, n))
        sys.exit(1 if unexempted(found) else 0)
    unittest.main()
