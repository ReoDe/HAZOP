"""이름 규칙 검사 N1~N12 (이름 규칙 문서 README.md, HZ-GOV-02 §4와 §8.1. 자리는 `NAMING_DIRS`).

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
# 이름 규칙 문서 폴더. 단계 7이 옛 자리를 새 자리로 옮긴다. 옮기기 전과 뒤에 모두 읽도록 두 자리를 새 자리 먼저 적고,
# 이전 도구(scripts/migrate_names.py)와 다른 시험도 경로를 직접 적지 않고 여기서 얻는다.
NAMING_DIRS = ("docs/governance/naming-rules", "docs/2026-11-10-naming-rules")


def naming_dir(repo=REPO):
    for d in NAMING_DIRS:
        if os.path.isfile(os.path.join(repo, *d.split("/"), "README.md")):
            return d
    return NAMING_DIRS[0]


def naming_path(name, repo=REPO):
    return naming_dir(repo) + "/" + name


NAMING_DOC = naming_path("README.md")

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
        ("N8", "* @ *naming-rules/README.md", "대응표가 옛 이름을 일부러 적는다(옮기기 전 docs/2026-11-10-naming-rules/, 뒤 docs/governance/naming-rules/)"),
        ("N9", "docs/units/2026-11-05-packaging/evidence/w5-* -> HAZOP기법지침.md", "기획서 문장을 인용한 줄 안의 링크"),
        ("N8", "* @ docs/units/2026-11-10-plan/pstack-advice.md", "단위 NAMING 절이 옮길 이름과 데이터에 남는 옛 출처를 일부러 적는다"),
        ("N1", "resources/references/pid-samples/*", "샘플 도면 폴더 이름은 기준값의 키다(§5.5)"),
        ("N1", "resources/references/pid-symbol-catalog/*", "받은 기호 카탈로그의 파일 이름을 그대로 둔다"),
        ("N1", "resources/references/APR1400_DCD/*", "받은 이름을 그대로 둔다(§5.5)"),
        ("N8", "자원/ @ docs/units/2026-11-09-data-consolidation/README.md", "2026-11-09 정리의 계획이자 기록. 그때 정한 배치를 적었다"),
        ("N8", "작업/ @ docs/units/2026-11-09-data-consolidation/README.md", "같은 문서. 그때의 개발 작업 루트 이름이다"),
        ("N8", "작업/ @ docs/units/2026-11-10-ci-review/README.md", "2026-11-10 CI 검토 기록. 그때의 작업 루트 이름을 적었다"),
        ("N8", "작업/ @ docs/units/2026-11-10-lessons/d-drive-move.md", "D 드라이브 이전 기록. 그때 옮긴 폴더 이름이다"),
        ("N8", "specs/ @ docs/units/2026-11-09-data-consolidation/README.md", "2026-11-09 정리 계획. 그때 정한 문서 폴더 이름을 적었다"),
        ("N8", "methodology/ @ docs/units/2026-11-09-data-consolidation/README.md", "같은 문서"),
        ("N8", "specs/ @ docs/units/2026-11-12-folder-standard/README.md", "이 이전의 완료 목록. 옮긴 일을 옛 이름으로 말한다"),
        ("N8", "design/ @ docs/units/2026-11-12-folder-standard/README.md", "이 이전의 완료 목록. 옮긴 일을 옛 이름으로 말한다"),
        ("N8", "methodology/ @ docs/units/2026-11-12-folder-standard/README.md", "이 이전의 완료 목록. 옮긴 일을 옛 이름으로 말한다"),
        ("N8", "records/ @ docs/units/2026-11-12-folder-standard/README.md", "이 이전의 완료 목록. 옮긴 일을 옛 이름으로 말한다"),
        ("N8", "작업/ @ docs/design/mockups/README.md", "시안에 넣은 자료를 가져온 그때의 경로다"),
    ],
    # 단계 7(2026-11-12): 문서 폴더를 docs/ 아래로 모았다(N2·N3 줄은 옮긴 날 지웠다). N12 줄은 3단계(규칙서 쓰기)에서 지운다.
    "7": [
        ("N12", "docs", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/design", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/governance", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/governance/naming-rules", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/methodology", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/records", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/specs", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/specs/flows", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "docs/units", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/analysis", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/app", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/contract", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/evaluate", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/export", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/extract", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/graph", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/ie", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/kg", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/register", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/review", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/study", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "hazop/viewer", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "licenses", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "packaging", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "resources", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "resources/library", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "resources/references", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "resources/samples", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "scripts", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "scripts/symbols", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "tests", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "tests/baselines", "폴더 규칙서를 3단계에서 쓴다"),
        ("N12", "tests/fake_claude", "폴더 규칙서를 3단계에서 쓴다"),
    ],
}


# ---------------------------------------------------------------- N1, N2
CONVENTION_FILES = {"README.md", "CLAUDE.md", "AGENTS.md", "INTENT.md", "PROGRESS.md", "ROADMAP.md", "SKILL.md"}
# 대문자를 써도 되는 고유명사와 도면번호(§4.1)
PROPER_NOUNS = re.compile(r"APR1400|SNP-[A-Z]+(?:-\d+)?|[LD]\d+-\d+")
SAFE_CHARS = re.compile(r"[A-Za-z0-9._-]*\Z")
TOP_LEVEL = {
    "hazop", "scripts", "tests", "packaging", "licenses", "resources", "work", "docs",
    "CLAUDE.md", "INTENT.md", "README.md", ".claude", ".github", ".gitignore", ".gitattributes",
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


DOCS_CHILDREN = ("specs", "design", "methodology", "records", "units", "governance")


def n3_docs_workspaces(paths):
    """docs/ 바로 아래는 여섯 폴더뿐이고, 작업 단위 기록은 docs/units/<YYYY-MM-DD-slug>/(README.md 필수)에 둔다."""
    out = []
    for name in sorted({p.split("/")[1] for p in paths if p.startswith("docs/") and p.count("/") >= 2}):
        if name not in DOCS_CHILDREN:
            out.append(Violation("N3", "docs/" + name, "docs/ 바로 아래가 %s가 아니다" % "·".join(DOCS_CHILDREN)))
    out += [Violation("N3", p, "docs/units/ 바로 아래에는 README.md와 날짜 폴더만 둔다")
            for p in sorted(paths) if p.startswith("docs/units/") and p.count("/") == 2 and p != "docs/units/README.md"]
    for name in sorted({p.split("/")[2] for p in paths if p.startswith("docs/units/") and p.count("/") >= 3}):
        if not WORKSPACE.match(name):
            out.append(Violation("N3", "docs/units/" + name, "이름이 YYYY-MM-DD-<slug>가 아니다"))
        if "docs/units/%s/README.md" % name not in paths:
            out.append(Violation("N3", "docs/units/" + name, "README.md가 없다"))
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
# 옮기기 전(`specs/…`)과 옮긴 뒤(`docs/specs/…`)의 자리를 모두 적는다. 폴더 규칙서(README.md)는 N12 양식이라 머리를 달지 않는다.
HEADER_TARGETS = (
    "specs/*.md", "specs/flows/*.md", "design/*.md", "methodology/*.md", "records/*.md",
    "docs/specs/*.md", "docs/specs/flows/*.md", "docs/design/*.md", "docs/methodology/*.md", "docs/records/*.md",
    "INTENT.md", "docs/2026-11-10-naming-rules/README.md", "docs/governance/naming-rules/README.md",
    "packaging/other-pc-checklist.md",
)
# `records/README.md`는 지금도 HZ-REC-01이라 옮긴 뒤에도 머리 대상으로 둔다.
NO_HEADER = ("docs/specs/README.md", "docs/design/README.md", "docs/methodology/README.md", "docs/specs/flows/README.md")
HEADER_KEYS = ("doc_id", "rev", "status", "author", "reviewed", "approved")
DOC_ID = re.compile(r"HZ-(PLN|FLW|DSN|MTH|REC|GOV|CHK)-\d{2}\Z")
STATUSES = {"draft", "review", "approved", "obsolete"}


def is_header_target(path):
    if path in NO_HEADER:
        return False
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


# ---------------------------------------------------------------- N12
FOLDER_README_HEADINGS = ("무엇을 넣는가", "넣지 않는 것", "이름 형식", "주인", "폐기 기준")
UNIT_FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}-")


def readme_required(folder):
    """폴더 규칙서(README.md)를 두어야 하는 폴더인가. 최상위 폴더와 그 바로 아래 한 층, docs/ 아래는 두 층까지다.
    깊이를 정한 이유: 규칙서가 필요한 것은 사람이 '여기 뭘 넣지?'를 묻는 자리(분류가 갈리는 층)이고, 그보다 깊은 폴더는 윗층 규칙서가
    이름 형식으로 이미 설명한다. 빼는 것: 점으로 시작하는 도구 폴더, 작업 단위 기록(docs/units/<날짜-slug>/, 옛 자리 docs/<날짜-slug>/ 포함,
    각자 작업 공간 README가 있다), 시안(mockups, 만든 그림과 자체 README), 시험 입력(tests/fixtures, 폴더를 전부 훑는 시험이 있다),
    제3자 고지 원문(licenses/<이름>/, 바이트가 해시로 고정돼 있다)."""
    parts = folder.split("/")
    if parts[0].startswith(".") or "mockups" in parts or parts[:2] == ["tests", "fixtures"]:
        return False
    if parts[0] == "docs":
        if len(parts) > 1 and (UNIT_FOLDER.match(parts[1]) or (parts[1] == "units" and len(parts) > 2)):
            return False
        return len(parts) <= 3
    if parts[0] == "licenses":
        return len(parts) == 1
    return len(parts) <= 2


def n12_folder_readmes(paths, texts):
    """texts는 {README 경로: 글}. 필수 폴더에 README.md가 있고 `##` 제목 다섯 개가 양식 순서대로 한 번씩 있는지 본다."""
    tracked = set(paths)
    folders = sorted({p[:i] for p in paths for i, ch in enumerate(p) if ch == "/"})
    out = []
    for folder in folders:
        if not readme_required(folder):
            continue
        readme = folder + "/README.md"
        if readme not in tracked:
            out.append(Violation("N12", folder, "README.md가 없다"))
            continue
        heads, fenced = [], False
        for line in texts.get(readme, "").splitlines():
            if FENCE.match(line):
                fenced = not fenced
            elif not fenced and line.startswith("## "):
                heads.append(line[3:].strip())
        if [h for h in heads if h in FOLDER_README_HEADINGS] != list(FOLDER_README_HEADINGS):
            wrong = [h for h in FOLDER_README_HEADINGS if heads.count(h) != 1]
            out.append(Violation("N12", folder, "README.md 제목이 양식(%s)과 다르다: %s" % (
                " / ".join(FOLDER_README_HEADINGS), (", ".join(wrong) + " 확인") if wrong else "순서")))
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
# 고지 원문과 가져온 파일은 바이트가 SHA-256으로 고정돼 있다(licenses/README.md의 표, .gitattributes). 읽지도 고치지도 않는다.
THIRD_PARTY = ("licenses/", "hazop/kg/vendor/")
# 기록 문서. 본문에 백틱으로 적힌 옛 이름은 그 시점의 기록이라 N8이 보지 않고 이전 도구도 고치지 않는다(§6.9). 링크는 본다.
RECORD_DOCS = ("records/decision-log.md", "records/backlog.md", "docs/records/decision-log.md", "docs/records/backlog.md")


def is_doc(path):
    return path.lower().endswith((".md", ".html")) and not path.startswith(THIRD_PARTY)


# 단계 7로 최상위에서 docs/ 아래로 들어간 폴더. `../specs/…`처럼 문서 폴더 기준으로 적은 상대 경로는 맞으므로 접두를 받지 않는다.
MOVED_TOPS = ("specs", "design", "methodology", "records")
MOVED_TOP_IN_CODE = re.compile(r"^(?:\./|[A-Za-z]:[\\/]HAZOP[\\/])?(%s)[\\/]" % "|".join(MOVED_TOPS))


def n8_old_korean_paths(docs):
    out = []
    for path, text in sorted(docs.items()):
        hits = collections.defaultdict(list)
        for ref in doc_refs(path, text):
            if ref.kind == "code" and path in RECORD_DOCS:
                continue
            if ref.kind == "code":
                m = OLD_TOP_IN_CODE.match(ref.value.strip()) or MOVED_TOP_IN_CODE.match(ref.value.strip())
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
COMMIT_SUBJECT = re.compile(r"(feat|fix|docs|test|refactor|perf|build|ci|chore|baseline)(\([a-z0-9-]+\))?!?: \S")
# git과 GitHub가 스스로 붙이는 제목은 검사하지 않는다: `git revert` 기본 제목, 병합 제목, 그리고 GitHub가 브랜치 이름으로 지은
# PR 제목에 번호를 붙인 스쿼시 제목(`feat/next-units` -> `Feat/next units (#15)`). 사람이 쓴 PR 제목은 ` (#15)`가 붙어도 검사한다.
GENERATED_SUBJECT = re.compile(r'Revert "|Merge pull request #\d+|Merge (remote-tracking )?branch '
                               r"|(Feat|Fix|Docs|Chore|Refactor|Test)/[a-z0-9]+( [a-z0-9]+){0,3} \(#\d+\)\Z")
HANGUL = re.compile(r"[가-힣]")
BRANCH = re.compile(r"(feat|fix|docs|chore|refactor|test)/[a-z0-9]+(-[a-z0-9]+){0,3}\Z")


def n10_commit_subjects(subjects):
    out = []
    for s in subjects:
        if GENERATED_SUBJECT.match(s):
            continue
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
    readmes = read_texts([p for p in paths if p.endswith("/README.md") and readme_required(posixpath.dirname(p))], repo)
    return (n1_path_chars(paths) + n2_top_level(paths) + n3_docs_workspaces(tracked) + n4_script_verbs(paths)
            + n5_test_files(tests_py) + n6_doc_headers({p: t for p, t in docs.items() if is_header_target(p)})
            + n7_hand_versions(paths) + n8_old_korean_paths(docs)
            + n9_broken_links(docs, lambda t: t in tracked or t in dirs) + n12_folder_readmes(paths, readmes))


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
        """기준 커밋이 이력에 없으면(얕은 체크아웃) 실패가 아니라 건너뜀이다. 그때 N10은 아무것도 지키지 않는다."""
        subjects = commit_subjects_since()
        if subjects is None:
            self.skipTest("기준 커밋 %s이 이 체크아웃의 이력에 없다" % COMMIT_BASE)
        self.assertEqual([], n10_commit_subjects(subjects))

    def test_scripts_under_docs_find_the_repo_root(self):
        """docs/ 아래 .py가 자기 위치에서 저장소 루트를 세는 방식(dirname 겹침, `..` 단계, parents[n])이 폴더가 한 층 깊어져도 맞는지 본다."""
        nested = re.compile(r"((?:os\.path\.dirname\()+)os\.path\.abspath\(__file__\)")
        dots = re.compile(r"os\.path\.join\((?:HERE|os\.path\.dirname\(os\.path\.abspath\(__file__\)\)), ((?:\"\.\.\"(?:, )?)+)\)")
        parents = re.compile(r"ROOT\.parents\[(\d)\]")
        checked = 0
        for path in tracked_files():
            if not (path.startswith("docs/") and path.endswith(".py")):
                continue
            text = read_texts([path])[path]
            here = os.path.dirname(os.path.join(REPO, *path.split("/")))
            found = []
            for m in nested.finditer(text):
                up = m.group(1).count("dirname(") - 1
                if up < 2:  # 같은 폴더의 파일을 가리키는 한두 겹은 저장소 루트를 세는 것이 아니다
                    continue
                found.append(os.path.normpath(os.path.join(here, *[".."] * up)))
            for m in dots.finditer(text):
                found.append(os.path.normpath(os.path.join(here, *[".."] * m.group(1).count(".."))))
            for m in parents.finditer(text):
                found.append(os.path.normpath(os.path.join(here, *[".."] * (int(m.group(1)) + 1))))
            for root in found:
                checked += 1
                self.assertEqual(os.path.normcase(os.path.normpath(REPO)), os.path.normcase(root), path)
        self.assertGreater(checked, 8, "찾는 방식이 바뀌었는지 확인한다")

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
        self.assertEqual([], n2_top_level(["docs/specs/a.md", "work/x", "resources/y", "README.md", ".claude/a.md"]))
        # 개정 2: 문서 폴더 네 개는 docs/ 아래로 들어갔으므로 최상위에 있으면 걸린다
        self.assertEqual(["design", "methodology", "records", "specs"],
                         [v.subject for v in n2_top_level(["specs/a.md", "design/b.md", "methodology/c.md", "records/d.md"])])

    def test_n3_docs_children_and_unit_folders(self):
        paths = {"docs/units/2026-11-10-plan/pstack-advice.md", "docs/units/2026-11-10-lessons/README.md",
                 "docs/units/screenshots-pdf/README.md", "docs/specs/a.md", "docs/governance/naming-rules/README.md",
                 "docs/2026-11-12-old-place/README.md", "docs/README.md"}
        self.assertEqual([("docs/2026-11-12-old-place", "docs/ 바로 아래가 specs·design·methodology·records·units·governance가 아니다"),
                          ("docs/units/2026-11-10-plan", "README.md가 없다"),
                          ("docs/units/screenshots-pdf", "이름이 YYYY-MM-DD-<slug>가 아니다")],
                         [(v.subject, v.detail) for v in n3_docs_workspaces(paths)])

    def test_n3_loose_files_directly_under_docs_units(self):
        found = n3_docs_workspaces({"docs/units/README.md", "docs/units/loose.md", "docs/units/2026-11-10-plan/README.md"})
        self.assertEqual([("docs/units/loose.md", "docs/units/ 바로 아래에는 README.md와 날짜 폴더만 둔다")],
                         [(v.subject, v.detail) for v in found])

    def test_n3_date_folder_directly_under_docs_is_live_after_the_move(self):
        found = n3_docs_workspaces({"docs/2026-11-05-packaging/README.md"})
        self.assertEqual(["docs/2026-11-05-packaging"], [v.subject for v in found])
        self.assertIsNone(exempt_row(found[0]))

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
        # 옮긴 뒤의 자리도 같은 대상이다
        for moved in ("docs/specs/overview.md", "docs/specs/flows/00-overview.md", "docs/design/screen-spec.md",
                      "docs/methodology/combined-risk-methods.md", "docs/records/backlog.md",
                      "docs/governance/naming-rules/README.md"):
            self.assertTrue(is_header_target(moved), moved)
        for other in ("docs/design/mockups/README.md", "docs/units/2026-11-10-plan/README.md"):
            self.assertFalse(is_header_target(other), other)

    def test_naming_dir_is_found_before_and_after_the_move(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hazop-naming-dir-") as repo:
            self.assertEqual(NAMING_DIRS[0], naming_dir(repo))
            old = os.path.join(repo, *NAMING_DIRS[1].split("/"))
            os.makedirs(old)
            open(os.path.join(old, "README.md"), "w").close()
            self.assertEqual(NAMING_DIRS[1], naming_dir(repo))
            self.assertEqual(NAMING_DIRS[1] + "/name-map.csv", naming_path("name-map.csv", repo))
            new = os.path.join(repo, *NAMING_DIRS[0].split("/"))
            os.makedirs(new)
            open(os.path.join(new, "README.md"), "w").close()
            self.assertEqual(NAMING_DIRS[0], naming_dir(repo))
        self.assertEqual(naming_dir() + "/README.md", NAMING_DOC)
        self.assertTrue(os.path.isfile(os.path.join(REPO, NAMING_DOC)))

    def test_n12_folder_readme_form(self):
        good = "# 이름\n\n## 무엇을 넣는가\n가\n## 넣지 않는 것\n나\n## 이름 형식\n다\n## 주인\n라\n## 폐기 기준\n마\n"
        paths = ["hazop/a.py", "hazop/app/b.py", "hazop/app/deep/c.py", "hazop/README.md", "hazop/app/README.md",
                 "tests/fixtures/x/y.json", "licenses/pkg/LICENSE", "docs/units/2026-11-10-plan/evidence/e.md",
                 "docs/design/mockups/final/a.png", "docs/design/b.md", "docs/specs/flows/00.md", "docs/README.md",
                 "docs/design/README.md", "docs/specs/README.md", "docs/specs/flows/README.md",
                 ".claude/agents/a.md", "scripts/x.py"]
        texts = {"hazop/README.md": good, "hazop/app/README.md": good.replace("## 주인", "## 담당"),
                 "docs/README.md": good, "docs/design/README.md": good, "docs/specs/README.md": good,
                 "docs/specs/flows/README.md": good + "## 덧붙임\n"}
        found = {v.subject: v.detail for v in n12_folder_readmes(paths, texts)}
        self.assertEqual({"hazop/app", "scripts", "tests", "licenses", "docs/units"}, set(found))
        self.assertIn("없다", found["scripts"])
        self.assertIn("주인", found["hazop/app"])

    def test_n12_depth_and_exclusions(self):
        self.assertTrue(readme_required("hazop"))
        self.assertTrue(readme_required("hazop/app"))
        self.assertFalse(readme_required("hazop/app/widgets"))
        self.assertTrue(readme_required("docs"))
        self.assertTrue(readme_required("docs/specs"))
        self.assertTrue(readme_required("docs/specs/flows"))
        self.assertFalse(readme_required("docs/specs/flows/deep"))
        self.assertTrue(readme_required("docs/units"))
        self.assertFalse(readme_required("docs/units/2026-11-10-plan"))
        self.assertFalse(readme_required("docs/2026-11-10-plan"))
        self.assertFalse(readme_required("docs/2026-11-10-plan/evidence"))
        self.assertFalse(readme_required("docs/design/mockups"))
        self.assertFalse(readme_required("design/mockups/final"))
        self.assertFalse(readme_required("tests/fixtures"))
        self.assertFalse(readme_required("tests/fixtures/kg"))
        self.assertTrue(readme_required("tests/baselines"))
        self.assertTrue(readme_required("licenses"))
        self.assertFalse(readme_required("licenses/pkg"))
        self.assertFalse(readme_required(".claude"))
        self.assertFalse(readme_required(".github/workflows"))

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
            "records/decision-log.md": "기획서/전체기획.md를 고쳤다. `기획서/`를 `specs/`로 옮겼다. 작업 루트의 `데이터/지식/`을 본다.\n",
            "records/backlog.md": "`메모리/남은작업.md`에 적었다. [인터페이스](../기획서/인터페이스.md)\n",
            "x.html": '<a href="flow chart/00-overview.md">흐름</a> <code>자원/기준/</code>\n',
        }
        self.assertEqual(
            ["기획서/ @ .claude/agents/hazop-planner.md", "기획서/ @ README.md", "작업/ @ README.md",
             "메모리/ @ docs/2026-11-10-plan/a.md", "기획서/ @ records/backlog.md", "flow chart/ @ x.html", "자원/ @ x.html"],
            [v.subject for v in n8_old_korean_paths(docs)])

    def test_n8_moved_document_folders_are_live_after_stage_7(self):
        """단계 7 뒤로 `specs/`·`design/`·`methodology/`·`records/`는 최상위가 아니다. 백틱 경로로 새로 적으면 걸린다.
        문서 폴더 기준 상대 경로(`../specs/…`)와 `docs/` 아래 경로는 괜찮다. 기록 문서 본문은 보지 않는다."""
        docs = {"README.md": "`specs/overview.md`와 `docs/specs/overview.md`, `design/mockups/`, `./records/backlog.md`\n",
                "docs/design/a.md": "`../specs/interface.md`, `mockups/README.md`, `methodology/combined-risk-methods.md`\n",
                "docs/records/backlog.md": "`specs/overview.md` 본문\n"}
        self.assertEqual(["design/ @ README.md", "records/ @ README.md", "specs/ @ README.md",
                          "methodology/ @ docs/design/a.md"],
                         [v.subject for v in n8_old_korean_paths(docs)])

    def test_n8_is_live_for_folders_moved_in_stage_3(self):
        """단계 3의 넓은 예외(`기획서/ @ *` 등)를 지운 뒤로는, 옮긴 폴더의 옛 경로를 문서에 새로 적으면 예외 없이 걸린다."""
        docs = {"docs/2026-11-10-lessons/new.md":
                "`기획서/인터페이스.md`와 `디자인/시안/`, `메모리/결정로그.md`, `지식/a.md`, [흐름](<../../flow chart/00-overview.md>)\n"}
        where = " @ docs/2026-11-10-lessons/new.md"
        self.assertEqual([top + where for top in ("flow chart/", "기획서/", "디자인/", "메모리/", "지식/")],
                         [v.subject for v in unexempted(n8_old_korean_paths(docs))])

    def test_n8_is_live_for_the_folder_moved_in_stage_5(self):
        """단계 5의 넓은 예외(`자원/ @ *`)를 지운 뒤로는 `자원/…`을 백틱이나 링크로 새로 적으면 걸린다. 기록 경로는 걸리지 않는다."""
        docs = {"docs/2026-11-10-lessons/new.md":
                "기준 자료는 `자원/기준/기호/묶음.json`에 있다. [샘플](<../../자원/참고자료/P&ID 도면 샘플/>)\n"
                "기록 경로 `참고자료/P&ID 도면 샘플/a.drawio`와 새 이름 `resources/library/symbols/bundles.json`은 괜찮다.\n"}
        self.assertEqual(["자원/ @ docs/2026-11-10-lessons/new.md"], [v.subject for v in unexempted(n8_old_korean_paths(docs))])
        self.assertEqual("줄 1", n8_old_korean_paths(docs)[0].detail)

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
        bad = ["Add the core of the P&ID graph", "단위 B 검토 지적을 고친다", "docs: fix typos", "feat:요약을 붙여 쓴다", "Feat(Study): 대문자 종류"]
        self.assertEqual(bad, [v.subject for v in n10_commit_subjects(bad)])
        good = ["docs(naming): 이름 규칙 확정본과 이전 계획을 남긴다", "refactor(paths)!: 작업 루트 폴더 이름을 영어로 바꾼다",
                "test: 이름 규칙 검사를 넣는다", "ci: 워크플로의 YAML 문법 오류를 고친다"]
        self.assertEqual([], n10_commit_subjects(good))

    def test_n10_generated_subjects_are_skipped(self):
        generated = ['Revert "docs(naming): 옮긴 docs 이름에 맞춰 링크와 백틱 경로를 고친다"',
                     "Merge pull request #15 from ReoDe/feat/next-units", "Merge branch 'main' into feat/next-units",
                     "Merge remote-tracking branch 'origin/main' into feat/next-units", "Feat/next units (#15)"]
        self.assertEqual([], n10_commit_subjects(generated))
        self.assertEqual([], n10_commit_subjects(["docs(naming): 이름 규칙 확정본을 남긴다 (#16)"]))
        still_bad = ["Reverted something", "Merge things by hand", "Add a thing (#15) and more", "Add a thing (#15)",
                     "이름 이전 단계 3 (#16)", "feat/next-units (#15)", "Wip/next units (#15)"]
        self.assertEqual(still_bad, [v.subject for v in n10_commit_subjects(still_bad)])

    def test_naming_doc_lists_ci_and_points_to_trial_folder_moves(self):
        with open(os.path.join(REPO, NAMING_DOC), encoding="utf-8") as f:
            doc = f.read()
        self.assertIn("`ci`(CI 설정)", doc)
        self.assertIn(r"build\|ci\|chore", doc)
        self.assertIn("evidence/step1-moves.csv", doc)
        self.assertIn(naming_path("evidence/step1-moves.csv"), tracked_files())

    def test_n11_branch(self):
        for name in ("worktree-agent-a1c5c7a98a4e905b2", "claude/pdf-extract-fix-b525b8", "my-branch",
                     "feat/a-b-c-d-e", "Feat/x"):
            self.assertEqual(["N11"], self.rules(n11_branch(name)), name)
        for name in ("main", "feat/next-units", "chore/naming-migration"):
            self.assertEqual([], n11_branch(name), name)

    def test_exempt_row_is_per_rule(self):
        self.assertIsNotNone(exempt_row(Violation("N1", "resources/references/pid-samples/SNP-M-201_CVCS/SNP-M-201_CVCS.drawio", "")))
        self.assertIsNone(exempt_row(Violation("N7", "resources/references/APR1400_DCD/system-codes_v2.csv", "")))
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
