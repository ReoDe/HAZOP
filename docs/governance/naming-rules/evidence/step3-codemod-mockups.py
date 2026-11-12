"""시안 폴더(docs/design/mockups)의 build.py와 HTML에 적힌 옛 이름을 대응표(name-map.csv, stage 3·3d)대로 바꾼다.
    python codemod_mockups.py <저장소> [--apply]

build.py가 이름을 정해 HTML을 찍으므로 둘에 같은 규칙을 쓴다. 바꾸는 것은 세 가지뿐이다.
 1) 저장소 기준 옛 경로 전체(`디자인/시안/완성본/build.py`, `기획서/초기사건-출력설계.md`). 폴더는 뒤에 `/`가 올 때만.
 2) 따옴표로 감싼 완성본 폴더와 그 하위 폴더 이름("완성본", "B-고밀도작업대").
 3) 화면 이름: 숫자로 시작하는 것(`1-자료등록`)은 낱말 경계에서, 그 밖(`대비표`)은 확장자가 붙었을 때만.
화면에 보이는 낱말('초기사건', '시안')은 건드리지 않는다.
"""
import csv
import os
import posixpath
import re
import subprocess
import sys

repo = sys.argv[1]
apply = "--apply" in sys.argv
ROOT = "docs/design/mockups"
EXTS = ("-1366.png", "-1920.png", ".html", ".md")
WORD = "0-9A-Za-z가-힣_"
# 따옴표 안의 폴더 이름은 이 폴더와 그 아래 것만 바꾼다. build.py가 경로 조각으로 쓰는 이름이다.
# 다른 폴더 이름('초기사건', 'AI연결')은 화면 글자로도 따옴표 안에 나온다.
QUOTED_UNDER = "디자인/시안/완성본"

files, dirs, stems, quoted = {}, {}, {}, {}
with open(os.path.join(repo, "docs/governance/naming-rules/name-map.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        old, new = r["old"], r["new"]
        if r["stage"] == "3d":
            dirs[old] = new
            if (old + "/").startswith(QUOTED_UNDER + "/") and posixpath.basename(old) != posixpath.basename(new):
                quoted[posixpath.basename(old)] = posixpath.basename(new)
        elif r["stage"] == "3":
            files[old] = new
            if new.startswith(ROOT + "/"):
                a, b = posixpath.basename(old), posixpath.basename(new)
                for ext in EXTS:
                    if a.endswith(ext):
                        a, b = a[:-len(ext)], b[:-len(ext)]
                        break
                if a != b:
                    assert stems.setdefault(a, b) == b, (a, b)


def alt(names):
    return "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))


numbered = {a: b for a, b in stems.items() if a[0].isdigit()}
plain = {a: b for a, b in stems.items() if not a[0].isdigit()}
RULES = [
    (re.compile(r"(?<![%s/-])(%s)(?![%s-])" % (WORD, alt(files), WORD)), files),
    (re.compile(r"(?<![%s/-])(%s)(?=/)" % (WORD, alt(dirs))), dirs),
    (re.compile(r"(?<=[\"'])(%s)(?=[\"'])" % alt(quoted)), quoted),
    (re.compile(r"(?<![%s-])(%s)(?![%s]|-(?!1366|1920))" % (WORD, alt(numbered), WORD)), numbered),
    (re.compile(r"(?<![%s-])(%s)(?=\.(?:md|html)\b)" % (WORD, alt(plain))), plain),
]

ls = subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off", "ls-files", "-z", "--", ROOT], capture_output=True, check=True)
total = 0
for p in sorted(x for x in ls.stdout.decode("utf-8").split("\0") if x.endswith((".html", "build.py"))):
    full = os.path.join(repo, p)
    with open(full, encoding="utf-8", newline="") as fh:
        text = fh.read()
    count = 0
    for pattern, table in RULES:
        text, n = pattern.subn(lambda m, t=table: t[m.group(1)], text)
        count += n
    if count:
        total += count
        print("%s: %d곳" % (p, count))
        if apply:
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
print("%s %d곳" % ("바꿈" if apply else "바뀔 곳", total))
