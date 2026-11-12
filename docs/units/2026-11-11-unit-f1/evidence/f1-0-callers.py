"""`hazop.extract.adapters.pdf_vector`의 이름을 밖에서 쓰는 곳을 센다(F1-0 나누기 전 호출자 목록).

  python f1-0-callers.py [--out f1-0-callers.csv]

git이 추적하는 .py 파일을 AST로 읽어 다음을 찾는다.
- import: `from … import pdf_vector`, `import ….pdf_vector`, `from ….pdf_vector import 이름`
- attr: `pdf_vector.이름`(별칭 포함) 속성 접근. 값을 읽는 것과 대입(`pdf_vector.이름 = …`)을 나눠 적는다
- patch: `mock.patch.object(pdf_vector, "이름")`
- string: 문자열 안의 'pdf_vector.이름' 또는 'pdf_vector'(mock.patch 대상, 모듈 목록, hidden import)
.py가 아닌 추적 파일(.spec, .json, .toml 등, .md 제외)은 'pdf_vector'가 든 줄을 text로 적는다.
"""

import argparse
import ast
import csv
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TARGET = "hazop/extract/adapters/pdf_vector.py"
MODULE = "pdf_vector"
STRING_RE = re.compile(r"pdf_vector(?:\.([A-Za-z_][A-Za-z_0-9]*))?")


def tracked():
    out = subprocess.run(["git", "-C", REPO_ROOT, "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def scan_py(rel, rows):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
        src = fh.read()
    if MODULE not in src:
        return
    tree = ast.parse(src, rel)
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                if a.name == MODULE:
                    aliases.add(a.asname or a.name)
                    rows.append((rel, node.lineno, "import", ""))
                elif mod.split(".")[-1] == MODULE:
                    rows.append((rel, node.lineno, "import", a.name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[-1] == MODULE:
                    aliases.add(a.asname or a.name)
                    rows.append((rel, node.lineno, "import", ""))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            base = node.value
            dotted = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else None)
            if dotted in aliases or dotted == MODULE:
                kind = "attr-set" if isinstance(node.ctx, (ast.Store, ast.Del)) else "attr"
                rows.append((rel, node.lineno, kind, node.attr))
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "object" and len(node.args) >= 2:
                a0, a1 = node.args[0], node.args[1]
                if isinstance(a0, ast.Name) and a0.id in aliases and isinstance(a1, ast.Constant):
                    rows.append((rel, node.lineno, "patch", str(a1.value)))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and MODULE in node.value:
            if len(node.value) > 200:  # 모듈 설명글
                continue
            for m in STRING_RE.finditer(node.value):
                rows.append((rel, node.lineno, "string", m.group(1) or ""))


def scan_text(rel, rows):
    try:
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if MODULE in line:
                    rows.append((rel, i, "text", line.strip()[:120]))
    except (UnicodeDecodeError, OSError):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "f1-0-callers.csv"))
    args = ap.parse_args(argv)
    rows = []
    for rel in tracked():
        if rel == TARGET or rel.startswith("docs/units/2026-11-11-unit-f1/"):
            continue
        if rel.endswith(".py"):
            scan_py(rel, rows)
        elif not rel.endswith((".md", ".csv", ".pdf", ".png", ".svg", ".drawio", ".html")):
            scan_text(rel, rows)
    rows.sort()
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["file", "line", "kind", "name"])
        w.writerows(rows)
    files = sorted({r[0] for r in rows})
    names = sorted({r[3] for r in rows if r[2] in ("attr", "attr-set", "patch", "import") and r[3]})
    private = [n for n in names if n.startswith("_")]
    print("파일 %d개, 참조 %d곳, 쓰는 이름 %d개(밑줄로 시작 %d개)" % (len(files), len(rows), len(names), len(private)))
    for top in ("hazop", "scripts", "packaging", "tests"):
        sub = [r for r in rows if r[0].startswith(top + "/")]
        print("  %s: 파일 %d, 참조 %d" % (top, len({r[0] for r in sub}), len(sub)))
    for kind in ("attr-set", "patch", "string"):
        sub = [r for r in rows if r[2] == kind]
        print("  %s %d곳: %s" % (kind, len(sub), ", ".join(sorted({"%s:%s" % (os.path.basename(r[0]), r[3]) for r in sub}))))
    print("이름: %s" % ", ".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
