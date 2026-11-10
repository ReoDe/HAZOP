"""이름 이전 도구(HZ-GOV-02 §6.9, §7). 대응표 `docs/2026-11-10-naming-rules/name-map.csv`(열: stage, old, new)를 읽는다.

    python scripts/migrate_names.py --stage 2                  옮길 것과 바뀔 줄을 보여 준다(쓰지 않음)
    python scripts/migrate_names.py --stage 2 --move           대응표대로 `git mv`만 한다(내용 변경 0)
    python scripts/migrate_names.py --stage 2 --rewrite-links --report <csv>
                                                               .md·.html의 상대 링크와 백틱 경로를 새 이름으로 바꾼다

    python scripts/migrate_names.py --stage 3 --stage 3d --rewrite-links --only .claude --only CLAUDE.md
                                                               운영 파일만 골라 고쳐 쓴다(총괄이 한다)

다음 단계는 대응표에 줄을 더하고 `--stage`만 바꿔 돌린다. `--stage`는 여러 번 줄 수 있다.
폴더 이름과 그 안의 파일 이름이 함께 바뀌는 단계는 줄을 둘로 나눈다. 파일 줄은 `3`처럼 숫자 stage에 두고 `--move`로 옮긴다.
폴더 줄은 `3d`에 두고 링크 바꾸기에만 쓴다(`--stage 3 --stage 3d --rewrite-links`). 폴더를 먼저 옮기면 파일 줄의 옛 이름이 없어지기 때문이다.
git이 추적하지 않는 파일·폴더는 `5u`처럼 따로 두고 손으로 옮긴다(이동 기록 `evidence/step5-moves.csv`). 이 줄도 링크 바꾸기에만 쓴다.
링크 바꾸기가 고치는 것은 `.md`·`.html`의 상대 링크(대상과, 대상 이름을 그대로 적은 링크 글자)와 백틱(`<code>`) 안의
경로뿐이다. 본문 문장, 코드 울타리, JSON·CSV·코드는 건드리지 않는다. `HANDS_OFF`의 운영 파일은 바뀔 줄만 기록하고 쓰지 않는다.
기록 문서(`RECORD_DOCS`: 결정로그, 남은작업)는 링크 대상만 고친다. 거기 적힌 옛 이름은 그 시점의 기록이다(§6.9).
다른 문서에서도 옛 이름을 일부러 적은 곳은 두고 간다: 새 이름을 이미 백틱으로 적은 줄(`옛`→`새`처럼 옮긴 일을 말하는 줄)과
백틱을 품은 인용(`` `옛/이름.md` ``).
운영 파일은 `--only`로 그 경로를 짚어 줄 때만 고쳐 쓴다.
두 명령 모두 지금 있는 상태에서 남은 일만 하므로, 중간에 끊겨도 다시 돌리면 같은 결과가 된다.
"""

import argparse
import collections
import csv
import os
import posixpath
import re
import subprocess
import sys
import urllib.parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tests import test_naming_rules as rules  # noqa: E402

MAP_FILE = "docs/2026-11-10-naming-rules/name-map.csv"
# 운영 규칙 파일. 바뀔 줄을 기록만 하고 총괄이 직접 고친다.
HANDS_OFF = ("CLAUDE.md", ".claude/")
# 옛 이름을 일부러 적어 둔 문서. 읽지도 않는다. 둘째는 2026-11-09 정리의 계획이자 기록이다. 그때 정한 `자원/` 배치와 옮긴 순서를
# 적은 문서라 새 이름으로 바꾸면 기록이 틀려진다. 지금 이름은 HZ-GOV-02 §5.5 대응표로 찾는다.
KEEP = (rules.NAMING_DOC, "docs/2026-11-09-data-consolidation/README.md")
# 옛 이름을 일부러 적은 줄: (문서의 지금 경로, 그 줄에 든 글자)
KEEP_LINES = (
    ("docs/2026-11-10-plan/pstack-advice.md", "과거 실제 위반에서 실패함을 보인다"),
    # 단위 NAMING 절에서 '무엇을 어디로 옮기나'와 '데이터에 적힌 옛 출처'를 말하는 줄
    ("docs/2026-11-10-plan/pstack-advice.md", "기준 자료 JSON 안의 출처 문자열은 고치면 안 된다"),
    ("docs/2026-11-10-plan/pstack-advice.md", "그 폴더를 옮기는 단계의 ② 커밋"),
    ("docs/2026-11-10-plan/pstack-advice.md", "단계 0에 규칙 18을 넣고"),
    ("docs/2026-11-10-plan/pstack-advice.md", "단계 3이 옮긴 뒤"),
    ("docs/2026-11-10-plan/pstack-advice.md", "단계 3 끝(`메모리/`"),
    ("docs/2026-11-10-plan/pstack-advice.md", "그래프 판이 바뀌면 바로 걸리는 장치가 이미 있다"),
    # 그때의 폴더 이름에 한글·`&`·공백이 들어 있었다는 말이라 새 이름으로 바꾸면 뜻이 틀어진다
    ("docs/2026-11-10-plan/pstack-advice.md", "한글·`&`·공백이 든 경로("),
)

# 기록 문서. 옮기기 전 이름으로 돌려도 같게 다룬다.
RECORD_DOCS = frozenset(rules.RECORD_DOCS) | {"메모리/결정로그.md", "메모리/남은작업.md"}

Row = collections.namedtuple("Row", "stage old new")
Change = collections.namedtuple("Change", "file line kind before after applied")
REPORT_HEADER = ["파일", "줄", "종류", "전", "후", "적용"]
TOKEN_CHARS = r"[^\s\"'`<>|,;=]"
TOKEN = re.compile(TOKEN_CHARS + "+")
# 경로 뒤에 붙는 것: 폴더 표시 `/`, 줄 번호 `:25`·`:24-68`, 문장부호
TOKEN_TAIL = re.compile(r"/?(?::\d+(?:-\d+)?)?[.:)\]]*\Z")


class MigrateError(Exception):
    pass


# ---------------------------------------------------------------- 대응표
def load_map(repo=REPO_ROOT):
    with open(os.path.join(repo, MAP_FILE), encoding="utf-8-sig", newline="") as f:
        return [Row(r["stage"].strip(), r["old"].strip().strip("/"), r["new"].strip().strip("/")) for r in csv.DictReader(f)]


def map_problems(rows):
    """한 이름이 두 번 옮겨지거나 두 이름이 한곳으로 모이는 대응표는 다시 돌렸을 때 결과가 달라진다."""
    out = []
    olds = collections.Counter(r.old for r in rows)
    news = collections.Counter(r.new for r in rows)
    out += ["옛 이름이 두 번 나온다: %s" % k for k, n in olds.items() if n > 1]
    out += ["새 이름이 두 번 나온다: %s" % k for k, n in news.items() if n > 1]
    out += ["새 이름이 다른 줄의 옛 이름이다: %s" % r.new for r in rows if r.new in olds]
    return out


def _lookup(pairs, path):
    """path가 대응표의 이름이거나 그 폴더 아래면 (바뀐 경로, 대응된 이름)을 낸다. 긴 이름부터 맞춘다."""
    for src, dst in sorted(pairs, key=lambda p: -len(p[0])):
        if path == src:
            return dst, dst
        if path.startswith(src + "/"):
            return dst + path[len(src):], dst
    return None


def _forward(rows):
    return [(r.old, r.new) for r in rows]


def _backward(rows):
    return [(r.new, r.old) for r in rows]


# ---------------------------------------------------------------- 옮기기
def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off"] + list(args), capture_output=True)


def move(rows, repo=REPO_ROOT):
    """옛 이름만 있으면 `git mv`하고, 새 이름만 있으면 이미 옮긴 것으로 본다. 둘 다 있으면 덮어쓰지 않고 멈춘다."""
    todo = []
    for r in rows:
        old, new = os.path.join(repo, r.old), os.path.join(repo, r.new)
        if os.path.exists(old) and os.path.exists(new):
            raise MigrateError("옛 이름과 새 이름이 둘 다 있다. 덮어쓰지 않는다: %s, %s" % (r.old, r.new))
        if not os.path.exists(old) and not os.path.exists(new):
            raise MigrateError("옛 이름도 새 이름도 없다: %s" % r.old)
        if os.path.exists(old):
            todo.append(r)
    for r in todo:
        os.makedirs(os.path.dirname(os.path.join(repo, r.new)), exist_ok=True)
        done = _git(repo, "mv", r.old, r.new)
        if done.returncode != 0:
            raise MigrateError("git mv 실패: %s -> %s: %s" % (r.old, r.new, done.stderr.decode("utf-8", "replace").strip()))
        parent = os.path.dirname(os.path.join(repo, r.old))
        while parent != repo and os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
            parent = os.path.dirname(parent)
    return todo


# ---------------------------------------------------------------- 링크와 백틱 경로
def _relative(doc, target):
    return posixpath.relpath(target, posixpath.dirname(doc) or ".")


def _new_link(doc, doc_before, value, rows, exists):
    raw = re.split(r"[#?]", value, 1)[0]
    rel = rules.link_path(value)
    if rel is None:
        return None
    here = rules.resolve(doc, rel)
    if here is not None and exists(here):
        return None
    before = rules.resolve(doc_before, rel)
    if before is None:
        return None
    hit = _lookup(_forward(rows), before)
    target = hit[0] if hit else before
    if not exists(hit[1] if hit else before) or (not hit and doc == doc_before):
        return None
    new = _relative(doc, target) + ("/" if rel.endswith("/") else "")
    if "%" in raw:
        new = urllib.parse.quote(new, safe="/")
    return new + value[len(raw):]


def _new_token(doc, doc_before, token, rows, exists):
    """백틱 안의 낱말 하나가 옮긴 경로면 새 경로를 낸다. 경로는 문서 폴더, 그 위 폴더들, 저장소 루트 순서로 풀어 본다.
    새 경로가 실제로 있는 풀이를 먼저 쓴다. 없으면(`records/*.md`, 지워진 파일) 옮긴 폴더 아래로 풀리는 것 중 루트에 가장 가까운
    풀이를 쓴다. 옮긴 폴더 안의 문서가 다른 옮긴 폴더를 적으면(`specs/` 문서의 `디자인/`) 문서 폴더 기준 풀이도 옮긴 폴더 아래로
    풀리기 때문이다.
    `/`가 없는 낱말은 경로로 보지 않는다. 폴더 이름과 같은 낱말(`지식`, `메모리`)이 본문에 흔하다.
    폴더 없이 파일 이름만 적은 것은 그 이름의 새 이름이 하나로 정해질 때만 바꾼다."""
    path = TOKEN_TAIL.sub("", token)
    tail = token[len(path):]
    if not path or "\\" in path:
        return None
    base_before, base_now = posixpath.dirname(doc_before), posixpath.dirname(doc)
    loose = None
    while "/" in token:
        hit = _lookup(_forward(rows), posixpath.normpath(posixpath.join(base_before, path)))
        new = posixpath.relpath(hit[0], base_now or ".") if hit else None
        # 옮긴 폴더 안의 문서에서는 아무 낱말이나 문서 폴더에 붙이면 옮긴 폴더 아래로 풀린다(`https://…`도). 그렇게 풀린 것은
        # 되돌려 적으면 같은 글자이므로, 적힌 경로가 실제로 달라지는 풀이만 받는다.
        if new is not None and posixpath.normpath(new) != posixpath.normpath(path):
            if exists(hit[0]):
                return new + tail
            if exists(hit[1]):
                loose = new + tail
        elif new is not None and exists(hit[0]):
            return None
        if not base_before or not base_now:
            break
        base_before, base_now = posixpath.dirname(base_before), posixpath.dirname(base_now)
    if loose is not None:
        return loose
    if "/" not in path and "." in path:
        names = {posixpath.basename(r.new) for r in rows if posixpath.basename(r.old) == path and exists(r.new)}
        if len(names) == 1:
            return names.pop() + tail
    return None


def _code_tokens(value, rows):
    """백틱 안 글을 경로 후보 낱말로 나눈다. 공백이 든 옛 이름은 한 낱말로 묶는다. 첫 구성요소에 공백이 있으면(`flow chart/…`)
    그 이름부터, 안쪽 구성요소에 있으면(`자원/참고자료/P&ID 도면 샘플/…`) 대응표에 적힌 옛 경로 전체부터 묶는다."""
    spaced = sorted({r.old.split("/")[0] for r in rows if " " in r.old.split("/")[0]} | {r.old for r in rows if " " in r.old},
                    key=len, reverse=True)
    if not spaced:
        return list(TOKEN.finditer(value))
    whole = re.compile(r"(?:%s*/)?(?:%s)(?:/%s*)?" % (TOKEN_CHARS, "|".join(re.escape(s) for s in spaced), TOKEN_CHARS))
    found = list(whole.finditer(value))
    taken = [m.span() for m in found]
    found += [m for m in TOKEN.finditer(value) if not any(s < m.end() and m.start() < e for s, e in taken)]
    return sorted(found, key=lambda m: m.start())


def _link_text_span(line, start):
    """링크 대상 바로 앞 `[글자](`에서 글자의 (시작, 끝)."""
    head = line[:start].rstrip("<")
    open_at = head.rfind("[", 0, len(head) - 2) if head.endswith("](") else -1
    return (open_at + 1, len(head) - 2) if open_at >= 0 else None


def _path_of(token):
    return posixpath.normpath(TOKEN_TAIL.sub("", token) or ".")


def rewrite_text(doc, text, rows, exists, keep_lines=KEEP_LINES):
    """doc은 문서의 지금 경로다. (바뀐 글, [(문서, 줄, 종류, 전, 후)])를 낸다."""
    needles = [needle for path, needle in keep_lines if path == doc]
    record = doc in RECORD_DOCS
    back = _lookup(_backward(rows), doc)
    doc_before = back[0] if back else doc
    by_line = collections.defaultdict(list)
    lines = text.splitlines(keepends=True)
    refs = rules.doc_refs(doc, text)
    written = collections.defaultdict(set)
    for ref in refs:
        if ref.kind == "code":
            written[ref.line] |= {_path_of(m.group()) for m in _code_tokens(ref.value, rows)}
    for ref in refs:
        if any(n in lines[ref.line - 1] for n in needles):
            continue
        if ref.kind == "link":
            new = _new_link(doc, doc_before, ref.value, rows, exists)
            if new is not None and new != ref.value:
                by_line[ref.line].append((ref.start, ref.end, "link", ref.value, new))
            # 링크가 옮긴 것을 가리키고 링크 글자가 그 옛 이름을 그대로 적었으면 글자도 바꾼다.
            rel = rules.link_path(new or ref.value)
            target = rules.resolve(doc, rel) if rel else None
            span = _link_text_span(lines[ref.line - 1], ref.start) if not doc.lower().endswith(".html") else None
            if span and target and not record and _lookup(_backward(rows), target):
                label = lines[ref.line - 1][span[0]:span[1]]
                new_label = _new_token(doc, doc_before, label, rows, exists)
                if new_label is not None and new_label != label:
                    by_line[ref.line].append(span + ("link-text", label, new_label))
            continue
        if record or "`" in ref.value:
            continue
        for m in _code_tokens(ref.value, rows):
            new = _new_token(doc, doc_before, m.group(), rows, exists)
            if new is not None and new != m.group() and _path_of(new) not in written[ref.line]:
                by_line[ref.line].append((ref.start + m.start(), ref.start + m.end(), "code", m.group(), new))
    if not by_line:
        return text, []
    changes = []
    for no in sorted(by_line):
        line = lines[no - 1]
        for start, end, kind, before, after in sorted(by_line[no], reverse=True):
            line = line[:start] + after + line[end:]
        lines[no - 1] = line
        changes += [(doc, no, kind, before, after) for _s, _e, kind, before, after in sorted(by_line[no])]
    return "".join(lines), changes


def _merge_report(path, changes):
    """기록 파일에 이번에 바꾼 줄을 더한다. 중간에 끊긴 뒤 다시 돌려도 앞서 바꾼 줄이 기록에 남는다."""
    rows = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = {tuple(r[k] for k in REPORT_HEADER) for r in csv.DictReader(f)}
    rows |= {(c.file, str(c.line), {"link": "링크", "link-text": "링크 글자", "code": "백틱"}[c.kind], c.before, c.after,
              "예" if c.applied else "아니오(총괄 몫)") for c in changes}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(REPORT_HEADER)
        w.writerows(sorted(rows, key=lambda r: (r[0], int(r[1]), r[3])))


def rewrite_links(rows, repo=REPO_ROOT, write=False, report=None, only=None):
    """only를 주면 그 경로(폴더는 그 아래 전부)의 문서만 본다. 운영 파일은 only로 짚었을 때만 고쳐 쓴다."""
    paths = rules.tracked_files(repo)
    tracked = set(paths)
    dirs = {p[:i] for p in paths for i, ch in enumerate(p) if ch == "/"}
    changes = []

    def on_disk(p):
        # 추적하지 않는 것(대응표 stage 5u: APR1400 원본·쪽별 PDF 등)은 이 PC에 옮겨져 있을 때만 새 이름으로 적는다
        return p in tracked or p in dirs or os.path.exists(os.path.join(repo, p))

    for doc in paths:
        if not rules.is_doc(doc) or doc in KEEP:
            continue
        if only and not any(doc == o or doc.startswith(o.rstrip("/") + "/") for o in only):
            continue
        full = os.path.join(repo, doc)
        if not os.path.isfile(full):
            continue
        with open(full, encoding="utf-8", newline="") as f:
            old = f.read()
        new, found = rewrite_text(doc, old, rows, on_disk)
        applied = bool(only) or not doc.startswith(HANDS_OFF)
        changes += [Change(*c, applied=applied) for c in found]
        if write and applied and new != old:
            with open(full, "w", encoding="utf-8", newline="") as f:
                f.write(new)
    if write and report and changes:
        _merge_report(report, changes)
    return changes


def leftovers(rows, repo=REPO_ROOT):
    """옮긴 이름이 문서에 글자 그대로 남은 줄. 본문 문장이나 코드 울타리에 적힌 것이라 사람이 판단한다."""
    names = sorted({r.old for r in rows} | {posixpath.basename(r.old) for r in rows if "." in posixpath.basename(r.old)},
                   key=len, reverse=True)
    out = []
    for doc, text in sorted(rules.read_texts([p for p in rules.tracked_files(repo) if rules.is_doc(p)], repo).items()):
        if doc in KEEP:
            continue
        for no, line in enumerate(text.splitlines(), 1):
            hit = next((n for n in names if n in line), None)
            if hit:
                out.append((doc, no, hit))
    return out


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", action="append", required=True, help="대응표의 stage 값. 여러 번 줄 수 있다")
    ap.add_argument("--move", action="store_true", help="git mv를 한다")
    ap.add_argument("--rewrite-links", action="store_true", help="링크와 백틱 경로를 바꿔 쓴다")
    ap.add_argument("--report", help="바꾼 줄 목록을 더해 적을 CSV")
    ap.add_argument("--only", action="append", help="이 경로의 문서만 본다. 운영 파일(CLAUDE.md, .claude/)은 여기 적어야 고쳐 쓴다")
    ap.add_argument("--leftovers", action="store_true", help="옛 이름이 글자 그대로 남은 줄을 보여 준다")
    ap.add_argument("--repo", default=REPO_ROOT)
    args = ap.parse_args(argv)
    try:
        table = load_map(args.repo)
        problems = map_problems(table)
        if problems:
            raise MigrateError("대응표 오류:\n" + "\n".join(problems))
        rows = [r for r in table if r.stage in args.stage]
        if not rows:
            raise MigrateError("대응표에 stage %s 줄이 없다" % ", ".join(args.stage))
        if args.move:
            moved = move(rows, args.repo)
            print("git mv %d건 (대응표 %d줄)" % (len(moved), len(rows)))
        elif not args.rewrite_links and not args.leftovers:
            for r in rows:
                state = "옮길 것" if os.path.exists(os.path.join(args.repo, r.old)) else "옮김"
                print("%s: %s -> %s" % (state, r.old, r.new))
        if args.leftovers:
            for doc, no, name in leftovers(rows, args.repo):
                print("%s:%d %s" % (doc, no, name))
            return 0
        if not args.move:
            changes = rewrite_links(rows, args.repo, write=args.rewrite_links, report=args.report, only=args.only)
            for c in changes:
                print("%s:%d [%s%s] %s -> %s" % (c.file, c.line, c.kind, "" if c.applied else ", 쓰지 않음", c.before, c.after))
            print("%s %d곳, 파일 %d개" % ("바꿈" if args.rewrite_links else "바뀔 곳", len(changes), len({c.file for c in changes})))
    except MigrateError as e:
        print("멈춤: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
