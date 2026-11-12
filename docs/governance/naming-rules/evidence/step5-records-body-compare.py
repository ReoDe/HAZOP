"""기록 문서(결정로그·남은작업)의 본문이 기준 커밋과 같은지 맞대어 본다.
    python step5-records-body-compare.py <저장소> --base <커밋>

HZ-GOV-02 §6.9: 기록 문서의 본문 문장에 적힌 옛 이름은 그 시점의 기록이라 링크 대상 말고는 고치지 않는다.
기준 커밋의 같은 경로 파일과 지금 파일을 줄마다 맞대고, 링크 대상을 뺀 글이 다르면 그 줄을 찍는다.
`step3-records-body-compare.py`는 폴더 이동·문서 머리·결정 번호 열이 함께 바뀐 단계 3 전용이다. 이 스크립트는 기록 문서가
이미 `records/`에 있는 단계(5, 6)에서 쓴다. 끝나면 '다른 줄 N'을 찍고, 0이 아니면 종료 코드 1이다.
"""
import collections
import os
import subprocess
import sys

repo = os.path.abspath(sys.argv[1])
base = sys.argv[sys.argv.index("--base") + 1]
sys.path.insert(0, repo)
from tests import test_naming_rules as rules  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def without_link_targets(path, text):
    spans = collections.defaultdict(list)
    for ref in rules.doc_refs(path, text):
        if ref.kind == "link":
            spans[ref.line].append((ref.start, ref.end))
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        for s, e in sorted(spans[no], reverse=True):
            line = line[:s] + line[e:]
        out.append(line)
    return out


total = 0
for path in rules.RECORD_DOCS:
    shown = subprocess.run(["git", "-C", repo, "show", "%s:%s" % (base, path)], capture_output=True)
    if shown.returncode != 0:
        sys.exit("git show 실패: %s" % shown.stderr.decode("utf-8", "replace"))
    old = without_link_targets(path, shown.stdout.decode("utf-8"))
    with open(os.path.join(repo, path), encoding="utf-8", newline="") as f:
        raw = f.read()
    new = without_link_targets(path, raw)
    if len(old) != len(new):
        sys.exit("%s: 줄 수가 다르다(기준 %d, 지금 %d). 더한 행을 빼고 맞대야 한다" % (path, len(old), len(new)))
    differ = [(no, a, b) for no, (a, b) in enumerate(zip(old, new), 1) if a != b]
    for no, a, b in differ:
        print("%s:%d\n  기준: %s\n  지금: %s" % (path, no, a.strip()[:400], b.strip()[:400]))
    same_bytes = shown.stdout.replace(b"\r\n", b"\n") == raw.encode("utf-8").replace(b"\r\n", b"\n")
    print("%s: 다른 줄 %d (기준 %s, %d줄%s)" % (path, len(differ), base, len(old), ", 줄 끝 글자를 빼면 바이트도 같음" if same_bytes else ""))
    total += len(differ)
print("다른 줄 %d" % total)
sys.exit(1 if total else 0)
