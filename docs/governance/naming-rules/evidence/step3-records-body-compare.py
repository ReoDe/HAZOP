"""기록 문서(결정로그·남은작업)의 본문이 이름 이전 전과 같은지 맞대어 본다. 다르면 옛 본문으로 되돌린다.
    python step3-records-body-compare.py <저장소> [--base <커밋>] [--restore]

HZ-GOV-02 §6.9: 기록 문서의 본문 문장에 적힌 옛 이름은 그 시점의 기록이라 링크 대상 말고는 고치지 않는다.
옛 판(`--base`, 기본 d0a0370 = 단계 2 직전)과 지금 파일에서 링크 대상, 결정 번호 열, 문서 머리를 지운 글이 같아야 한다.
줄 수가 다르면(기준 뒤에 행을 더했으면) 멈춘다. 그때는 더한 행을 빼고 맞댈 수 있게 이 스크립트를 고친다.
`--restore`는 다른 줄을 옛 줄로 되돌리되 링크 대상과 결정 번호는 지금 것을 둔다.
끝나면 '다른 줄 N'을 찍고, 0이 아니면 종료 코드 1이다.
"""
import collections
import os
import re
import subprocess
import sys

repo = os.path.abspath(sys.argv[1])
base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "d0a0370"
restore = "--restore" in sys.argv
sys.path.insert(0, repo)
from tests import test_naming_rules as rules  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAIRS = (("메모리/결정로그.md", "docs/records/decision-log.md"), ("메모리/남은작업.md", "docs/records/backlog.md"))
NUMBER_CELL = re.compile(r"\| (?:DEC-\d{4}|번호|---) (?=\|)")


def old_text(path):
    r = subprocess.run(["git", "-C", repo, "show", "%s:%s" % (base, path)], capture_output=True)
    if r.returncode != 0:
        sys.exit("git show 실패: %s" % r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8")


def head_length(lines):
    """문서 머리와 그 뒤 빈 줄 하나의 줄 수."""
    if not lines or lines[0].strip() != "---":
        return 0
    end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    return end + 2 if lines[end + 1].strip() == "" else end + 1


def link_spans(path, text):
    spans = collections.defaultdict(list)
    for ref in rules.doc_refs(path, text):
        if ref.kind == "link":
            spans[ref.line].append((ref.start, ref.end))
    return spans


def pieces(line, spans):
    """줄을 (링크 대상이 아닌 조각들, 링크 대상들)로 나눈다. 줄 끝 글자(체크아웃마다 CRLF·LF가 다르다)는 뺀다."""
    line = line.rstrip("\r\n")
    rest, targets, at = [], [], 0
    for s, e in sorted(spans):
        rest.append(line[at:s])
        targets.append(line[s:e])
        at = e
    rest.append(line[at:])
    return rest, targets


def number_cell(line):
    m = NUMBER_CELL.match(line)
    return m.group() if m else ""


total = 0
for old_path, new_path in PAIRS:
    old_lines = old_text(old_path).splitlines(keepends=True)
    with open(os.path.join(repo, new_path), encoding="utf-8", newline="") as f:
        new_all = f.read().splitlines(keepends=True)
    skip = head_length(new_all)
    new_lines = new_all[skip:]
    if len(old_lines) != len(new_lines):
        sys.exit("%s: 줄 수가 다르다(옛 %d, 새 %d). 더한 행을 빼고 맞대야 한다" % (new_path, len(old_lines), len(new_lines)))
    old_spans = link_spans(old_path, "".join(old_lines))
    new_spans = link_spans(new_path, "".join(new_lines))
    differ = 0
    for i, (old, new) in enumerate(zip(old_lines, new_lines), 1):
        cell = number_cell(new) if new_path == "docs/records/decision-log.md" else ""
        old_rest, old_targets = pieces(old, old_spans[i])
        new_rest, new_targets = pieces(new[len(cell):], [(s - len(cell), e - len(cell)) for s, e in new_spans[i]])
        if old_rest == new_rest:
            continue
        differ += 1
        print("%s:%d (%s %s:%d)\n  옛: %s\n  새: %s" % (new_path, skip + i, base, old_path, i,
                                                    "".join(old_rest).strip()[:400], "".join(new_rest).strip()[:400]))
        if restore:
            if len(old_targets) != len(new_targets):
                sys.exit("%s:%d 링크 수가 달라 되돌릴 수 없다" % (new_path, skip + i))
            back = "".join(a + b for a, b in zip(old_rest, new_targets + [""]))
            new_all[skip + i - 1] = cell + back + new[len(new.rstrip("\r\n")):]
    print("%s: 다른 줄 %d (기준 %s:%s, %d줄)" % (new_path, differ, base, old_path, len(old_lines)))
    total += differ
    if restore and differ:
        with open(os.path.join(repo, new_path), "w", encoding="utf-8", newline="") as f:
            f.write("".join(new_all))
print("다른 줄 %d%s" % (total, " (되돌림)" if restore and total else ""))
sys.exit(1 if total and not restore else 0)
