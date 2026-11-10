"""이름 이전 도구(HZ-GOV-02 §6.9, §7). 대응표 `docs/2026-11-10-naming-rules/name-map.csv`(열: stage, old, new)를 읽는다.

    python scripts/migrate_names.py --stage 2                  옮길 것과 바뀔 줄을 보여 준다(쓰지 않음)
    python scripts/migrate_names.py --stage 2 --move           대응표대로 `git mv`만 한다(내용 변경 0)
    python scripts/migrate_names.py --stage 2 --rewrite-links --report <csv>
                                                               .md·.html의 상대 링크와 백틱 경로를 새 이름으로 바꾼다

다음 단계는 대응표에 줄을 더하고 `--stage`만 바꿔 돌린다. `--stage`는 여러 번 줄 수 있다.
링크 바꾸기가 고치는 것은 `.md`·`.html`의 상대 링크(대상과, 대상 이름을 그대로 적은 링크 글자)와 백틱(`<code>`) 안의
경로뿐이다. 본문 문장, 코드 울타리, JSON·CSV·코드는 건드리지 않는다. `HANDS_OFF`의 운영 파일은 바뀔 줄만 기록하고 쓰지 않는다(총괄이 고친다).
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
# 옛 이름을 일부러 적어 둔 문서. 읽지도 않는다.
KEEP = (rules.NAMING_DOC,)
# 옛 이름을 일부러 적은 줄: (문서의 지금 경로, 그 줄에 든 글자)
KEEP_LINES = (
    ("docs/2026-11-10-plan/pstack-advice.md", "과거 실제 위반에서 실패함을 보인다"),
)

Row = collections.namedtuple("Row", "stage old new")
Change = collections.namedtuple("Change", "file line kind before after applied")
REPORT_HEADER = ["파일", "줄", "종류", "전", "후", "적용"]
TOKEN = re.compile(r"[^\s\"'`<>|,;=]+")
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
    폴더 없이 파일 이름만 적은 것은 그 이름의 새 이름이 하나로 정해질 때만 바꾼다."""
    path = TOKEN_TAIL.sub("", token)
    tail = token[len(path):]
    if not path or "\\" in path:
        return None
    base_before, base_now = posixpath.dirname(doc_before), posixpath.dirname(doc)
    while True:
        hit = _lookup(_forward(rows), posixpath.normpath(posixpath.join(base_before, path)))
        if hit and exists(hit[1]):
            return posixpath.relpath(hit[0], base_now or ".") + tail
        if not base_before or not base_now:
            break
        base_before, base_now = posixpath.dirname(base_before), posixpath.dirname(base_now)
    if "/" not in path and "." in path:
        names = {posixpath.basename(r.new) for r in rows if posixpath.basename(r.old) == path and exists(r.new)}
        if len(names) == 1:
            return names.pop() + tail
    return None


def _link_text_span(line, start):
    """링크 대상 바로 앞 `[글자](`에서 글자의 (시작, 끝)."""
    head = line[:start].rstrip("<")
    open_at = head.rfind("[", 0, len(head) - 2) if head.endswith("](") else -1
    return (open_at + 1, len(head) - 2) if open_at >= 0 else None


def rewrite_text(doc, text, rows, exists, keep_lines=KEEP_LINES):
    """doc은 문서의 지금 경로다. (바뀐 글, [(문서, 줄, 종류, 전, 후)])를 낸다."""
    needles = [needle for path, needle in keep_lines if path == doc]
    back = _lookup(_backward(rows), doc)
    doc_before = back[0] if back else doc
    by_line = collections.defaultdict(list)
    lines = text.splitlines(keepends=True)
    for ref in rules.doc_refs(doc, text):
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
            if span and target and _lookup(_backward(rows), target):
                label = lines[ref.line - 1][span[0]:span[1]]
                new_label = _new_token(doc, doc_before, label, rows, exists)
                if new_label is not None and new_label != label:
                    by_line[ref.line].append(span + ("link-text", label, new_label))
            continue
        for m in TOKEN.finditer(ref.value):
            new = _new_token(doc, doc_before, m.group(), rows, exists)
            if new is not None and new != m.group():
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


def rewrite_links(rows, repo=REPO_ROOT, write=False, report=None):
    paths = rules.tracked_files(repo)
    tracked = set(paths)
    dirs = {p[:i] for p in paths for i, ch in enumerate(p) if ch == "/"}
    changes = []
    for doc in paths:
        if not rules.is_doc(doc) or doc in KEEP:
            continue
        full = os.path.join(repo, doc)
        if not os.path.isfile(full):
            continue
        with open(full, encoding="utf-8", newline="") as f:
            old = f.read()
        new, found = rewrite_text(doc, old, rows, lambda p: p in tracked or p in dirs)
        applied = not doc.startswith(HANDS_OFF)
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
            changes = rewrite_links(rows, args.repo, write=args.rewrite_links, report=args.report)
            for c in changes:
                print("%s:%d [%s%s] %s -> %s" % (c.file, c.line, c.kind, "" if c.applied else ", 쓰지 않음", c.before, c.after))
            print("%s %d곳, 파일 %d개" % ("바꿈" if args.rewrite_links else "바뀔 곳", len(changes), len({c.file for c in changes})))
    except MigrateError as e:
        print("멈춤: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
