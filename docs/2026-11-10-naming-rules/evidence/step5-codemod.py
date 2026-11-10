"""단계 5(`자원/` → `resources/`) 코드 고치기. paths.folder(...)에 넘기는 하위 폴더·파일 이름을 대응표(HZ-GOV-02 §5.5)의 새 이름으로 바꾼다.

    python step5-codemod.py <저장소>            바뀔 줄만 보여 준다
    python step5-codemod.py <저장소> --apply    고쳐 쓴다

보는 것은 git이 추적하는 .py이고, `paths.folder("참고"|"표본"|"APR1400", "<옛 이름>", …)` 꼴만 바꾼다. 같은 글자가 다른 뜻으로
쓰인 곳(작업 루트 폴더 이름 "구간", 화면 문구, 기록 경로 문자열)은 건드리지 않는다. 다시 돌리면 바뀔 줄이 0이다.
"""
import re
import subprocess
import sys

repo = sys.argv[1]
apply = "--apply" in sys.argv
INSIDE = {
    "참고": {"P&ID 도면 샘플": "pid-samples", "P&ID 기호 카탈로그": "pid-symbol-catalog"},
    "표본": {"구간": "regions", "고정응답": "fixed-responses", "지식": "knowledge-graph", "평가기준": "evaluation-criteria"},
    "APR1400": {"도면별": "by-drawing", "원본": "source", "계통약어.csv": "system-codes.csv", "도면목록.csv": "drawing-list.csv"},
}
SKIP = ("hazop/paths.py", "scripts/migrate_data_layout.py", "scripts/inventory_data_paths.py", "scripts/codemod_data_paths.py",
        "scripts/migrate_names.py", "tests/test_migrate_names.py", "tests/test_naming_rules.py", "tests/test_path_literals.py")
CALL = re.compile(r'(folder(?:_in)?\((?:[^()\n"]|"[^"\n]*")*?"(%s)",\s*)"([^"\n]+)"' % "|".join(INSIDE))


def fix(m):
    new = INSIDE[m.group(2)].get(m.group(3))
    return m.group(1) + '"%s"' % new if new else m.group(0)


files = subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off", "ls-files", "-z", "--", "*.py"],
                       capture_output=True).stdout.decode("utf-8").split("\0")
total = 0
for rel in sorted(f for f in files if f and f not in SKIP):
    path = repo + "/" + rel
    with open(path, encoding="utf-8", newline="") as fh:
        old = fh.read()
    new = CALL.sub(fix, old)
    if new == old:
        continue
    for no, (a, b) in enumerate(zip(old.splitlines(), new.splitlines()), 1):
        if a != b:
            total += 1
            print("%s:%d\n  - %s\n  + %s" % (rel, no, a.strip(), b.strip()))
    if apply:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
print("%s %d줄" % ("바꿈" if apply else "바뀔 줄", total))
