"""F1-0: `hazop/extract/adapters/pdf_vector.py`를 동작 그대로 나누는 스크립트와 그 검사.

  python f1-0-split.py apply     # 기준 커밋의 pdf_vector.py를 읽어 다섯 파일을 다시 쓴다(몇 번 돌려도 결과가 같다)
  python f1-0-split.py check     # 작업 폴더의 다섯 파일이 기준 커밋의 최상위 문장을 글자 그대로 한 번씩 담고 있는지 본다

나누는 단위는 최상위 문장(함수·클래스·대입)이다. 문장 바로 위에 붙은 주석 줄은 그 문장과 함께 옮긴다.
문장 원문은 손대지 않고 그대로 옮긴다. 새로 쓰는 것은 모듈 설명글, import 줄, 구획 주석(`# ----…`)뿐이다.
check는 여기에 더해 pdf_vector 모듈에서 예전 이름이 모두 보이는지(import로 들어와 `pdf_vector.이름`으로 보이던 것 포함),
옮긴 이름이 새 모듈의 것과 같은 객체인지, 다섯 모듈의 함수가 읽는 전역 이름이 모두 정의돼 있는지(빠뜨린 import) 본다.
"""

import argparse
import ast
import builtins
import importlib
import os
import subprocess
import symtable
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BASE_COMMIT = "072d5c0"
PKG_DIR = "hazop/extract/adapters"
SOURCE = PKG_DIR + "/pdf_vector.py"
ABSOLUTE = (("TAG_RE", "from hazop.kg.docextract import TAG_RE"),)
STDLIB = ("collections", "hashlib", "io", "math", "os", "re", "threading")

COMMON = "pdf_vector_common"
GROUPING = "pdf_vector_grouping"
CONNECTORS = "pdf_vector_connectors"
LABELS = "pdf_vector_labels"

MOVES = {
    COMMON: ["_num", "_bbox_pts", "_union", "_expand", "_inside", "_pt_box_dist", "_box_gap", "_depth", "_w", "_h",
             "_seg_dist", "_segs", "_poly_dist", "_seg_cross", "_poly_box_dist", "_uf_groups", "_center",
             "_is_circle", "_is_tombstone", "_is_chevron", "_is_triangle", "_issue"],
    GROUPING: ["_Sym", "_cluster_bodies", "_nearest_sym", "_end_status", "_plate_assemblies", "_group_symbols",
               "_merge_appendages"],
    CONNECTORS: ["SHEET_WORD_RE", "CONTINUATION_RE", "SYSTEM_LABEL_RE", "BARE_SYSTEM_RE", "_continuation_attributes"],
    LABELS: ["ISA_LABEL_RE", "PAREN_TOKEN_RE", "_text_blocks", "_upright_blocks", "_bubble_like", "_assign_tags"],
}

DOCSTRINGS = {
    COMMON: '''"""벡터 PDF 어댑터(pdf_vector)의 여러 단계가 함께 쓰는 보조 함수.

상자·선분 기하(_bbox_pts, _seg_dist, _poly_dist 등), 몸체 모양 판별(_is_circle, _is_chevron 등), 묶음 찾기(_uf_groups),
미확인·차단 기록 한 줄(_issue). pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""''',
    GROUPING: '''"""벡터 PDF 어댑터의 기호 묶기(pdf_vector 설명글 2번).

분류된 원시 요소(몸체·열린 선·표식·점선 조각)를 기호(_Sym)로 묶는다. 겹치는 몸체, 몸체 안 선, 구동부 축,
끝이 뜬 장식선, 플랜지 판 조립(_plate_assemblies), 관계에 닿지 않은 부속 기호 합치기(_merge_appendages)를 다룬다.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""''',
    CONNECTORS: '''"""벡터 PDF 어댑터의 연결 표시(다른 도면·시트로 이어지는 화살표) 글자 읽기.

연결 표시 옆 글자에서 계통 약어와 시트 표기를 읽는 정규식과 _continuation_attributes.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""''',
    LABELS: '''"""벡터 PDF 어댑터의 라벨 고르기(pdf_vector 설명글 5번·7번).

낱말을 줄·문단으로 묶고(_text_blocks), 보이는 글자로 노드 태그를 정한다(_assign_tags).
글자를 어느 기호에 붙일지는 pdf_vector.build_extraction 안에 남아 있다.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""''',
}

HEADERS = {  # 새 모듈의 구획 주석: 이 이름 앞에 넣는다
    COMMON: {"_num": "기하 보조", "_uf_groups": "묶음 찾기", "_center": "몸체 모양", "_issue": "미확인·차단 기록"},
    GROUPING: {}, CONNECTORS: {}, LABELS: {"_bubble_like": "태그"},
}
DROP_HEADERS = ("기하 보조", "5. 글자")  # 딸린 문장이 모두 옮겨져 pdf_vector.py에서 빼는 구획 주석
RENAME_HEADERS = {"2. 기호 묶기": "2. 선 위 빗금·점 (기호 묶기는 pdf_vector_grouping)"}
RULE = "# " + "-" * 64 + " "
REEXPORT_NOTE = "# 나눈 모듈(F1-0). 옮긴 이름을 예전 경로(pdf_vector.이름)로도 쓸 수 있게 모두 다시 내보낸다"


def base_source():
    out = subprocess.run(["git", "-C", REPO_ROOT, "show", "%s:%s" % (BASE_COMMIT, SOURCE)],
                         capture_output=True, check=True).stdout
    return out.decode("utf-8")


def segments(src):
    """→ (머리 줄 목록, [(이름들, 원문, 종류, 앞 빈 줄 수)]). 종류: stmt, header."""
    lines = src.split("\n")
    tree = ast.parse(src)
    body = tree.body
    first = next(i for i, n in enumerate(body) if not isinstance(n, (ast.Import, ast.ImportFrom))
                 and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)))
    head = lines[:body[first - 1].end_lineno]
    segs = []
    prev_end = body[first - 1].end_lineno  # 1부터 세는 줄 번호
    for n in body[first:]:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            names = [n.name]
        elif isinstance(n, ast.Assign):
            names = [t.id for t in n.targets]
        else:
            raise SystemExit("모르는 최상위 문장: 줄 %d" % n.lineno)
        between = lines[prev_end:n.lineno - 1]
        start = n.lineno - 1
        lead = []
        while between and between[-1].startswith("#") and not between[-1].startswith(RULE):
            lead.insert(0, between.pop())
            start -= 1
        blanks = 0
        for ln in between:
            if ln.startswith(RULE):
                segs.append(([], ln, "header", blanks))
                blanks = 0
            elif ln.strip() == "":
                blanks += 1
            else:
                raise SystemExit("문장 사이에 모르는 줄: %r" % ln)
        segs.append((names, "\n".join(lead + lines[n.lineno - 1:n.end_lineno]), "stmt", blanks))
        prev_end = n.end_lineno
    return head, segs


def owner_of(names):
    owners = {m for m, ns in MOVES.items() for nm in names if nm in ns}
    if len(owners) > 1:
        raise SystemExit("한 문장이 두 모듈에 걸림: %s" % names)
    return owners.pop() if owners else None


def used_names(text):
    tree = ast.parse(text)
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def emit(parts):
    """[(원문, 앞 빈 줄 수)] → 본문. 원래 붙어 있던 문장은 원래 간격, 나머지는 두 줄."""
    out = []
    for i, (text, blanks) in enumerate(parts):
        if i:
            out.append("\n" * (blanks + 1))
        out.append(text)
    return "".join(out)


def build(src):
    head, segs = segments(src)
    all_moved = {nm: m for m, ns in MOVES.items() for nm in ns}
    seen = {nm for names, _, kind, _ in segs if kind == "stmt" for nm in names}
    missing = sorted(set(all_moved) - seen)
    if missing:
        raise SystemExit("기준 파일에 없는 이름: %s" % missing)
    per = {m: [] for m in MOVES}
    main = []
    last_owner = "start"
    for names, text, kind, blanks in segs:
        if kind == "header":
            title = text[len(RULE):]
            if title in DROP_HEADERS:
                continue
            main.append((RULE + RENAME_HEADERS.get(title, title), 2, None))
            last_owner = "header"
            continue
        owner = owner_of(names)
        if owner:
            hdr = next((HEADERS[owner][nm] for nm in names if nm in HEADERS[owner]), None)
            if hdr:
                per[owner].append((RULE + hdr, 2))
                per[owner].append((text, 1))
            else:
                per[owner].append((text, blanks if last_owner == owner else 2))
        else:
            gap = blanks if last_owner in (None, "header") else 2
            main.append((text, gap, names))
        last_owner = owner
    files = {}
    order = [COMMON, GROUPING, CONNECTORS, LABELS]
    for m in order:
        body = emit(per[m])
        used = used_names(body)
        imports = ["import %s" % s for s in STDLIB if s in used]
        absolute = [line for name, line in ABSOLUTE if name in used]
        local = []
        if "rules" in used:
            local.append("from .. import rules")
        for dep in order[:order.index(m)]:
            need = [nm for nm in MOVES[dep] if nm in used]
            if need:
                local.append(import_block(dep, need))
        top = [DOCSTRINGS[m], ""]
        if imports:
            top += imports + [""]
        if absolute:
            top += absolute + [""]
        if local:
            top += local + [""]
        if body.startswith(("def ", "class ")):
            top.append("")
        files["%s/%s.py" % (PKG_DIR, m)] = "\n".join(top) + "\n" + body + "\n"
    main_body = emit([(t, b) for t, b, _ in main])
    used = used_names(main_body)
    new_head = []
    for ln in head:  # 쓰지 않게 된 `from … import TAG_RE`는 남긴다. 밖에서 pdf_vector.TAG_RE로 보이던 이름이다
        if ln.startswith("import ") and ln.split()[1] in STDLIB and ln.split()[1] not in used:
            continue
        new_head.append(ln)
    reexport = [REEXPORT_NOTE] + [import_block(m, MOVES[m]) for m in order]
    files[SOURCE] = "\n".join(new_head + [""] + reexport) + "\n\n" + main_body + "\n"
    return files


def import_block(module, names):
    one = "from .%s import %s" % (module, ", ".join(names))
    if len(one) <= 120:
        return one
    lines, cur = [], "    "
    for nm in names:
        piece = nm + ", "
        if len(cur) + len(piece) > 118:
            lines.append(cur.rstrip())
            cur = "    "
        cur += piece
    lines.append(cur.rstrip().rstrip(","))
    return "from .%s import (\n%s,\n)" % (module, "\n".join(lines))


def apply():
    files = build(base_source())
    for rel, text in files.items():
        with open(os.path.join(REPO_ROOT, rel), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("%5d줄 %s" % (text.count("\n"), rel))
    return 0


def check():
    src = base_source()
    _, segs = segments(src)
    base = {tuple(names): text for names, text, kind, _ in segs if kind == "stmt"}
    found = {}
    bad = []
    for rel in [SOURCE] + ["%s/%s.py" % (PKG_DIR, m) for m in MOVES]:
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
            _, here = segments(fh.read())
        for names, text, kind, _ in here:
            if kind != "stmt":
                continue
            key = tuple(names)
            if key in found:
                bad.append("두 번 나옴: %s (%s, %s)" % (names, found[key], rel))
            found[key] = rel
            if key not in base:
                bad.append("기준에 없는 문장: %s (%s)" % (names, rel))
            elif base[key] != text:
                bad.append("원문이 다름: %s (%s)" % (names, rel))
            want = owner_of(names)
            if rel != ("%s/%s.py" % (PKG_DIR, want) if want else SOURCE):
                bad.append("자리가 다름: %s (%s)" % (names, rel))
    bad += ["빠진 문장: %s" % list(k) for k in base if k not in found]
    print("최상위 문장 %d개 중 글자 그대로 옮겨진 것 %d개" % (len(base), sum(1 for k in base if found.get(k) and not any(
        str(list(k)) in b for b in bad))))
    sys.path.insert(0, REPO_ROOT)
    pv = importlib.import_module("hazop.extract.adapters.pdf_vector")
    old_names = {nm for k in base for nm in k}
    gone = sorted(nm for nm in old_names if not hasattr(pv, nm))
    bad += ["pdf_vector에서 안 보이는 이름: %s" % nm for nm in gone]
    visible = module_names(src)
    lost = sorted(visible - old_names - {nm for nm in visible if hasattr(pv, nm)})
    bad += ["pdf_vector에서 안 보이는 이름(import로 들어왔던 것): %s" % nm for nm in lost]
    same = 0
    for m, names in MOVES.items():
        mod = importlib.import_module("hazop.extract.adapters." + m)
        for nm in names:
            if getattr(pv, nm, None) is getattr(mod, nm):
                same += 1
            else:
                bad.append("다른 객체: pdf_vector.%s / %s.%s" % (nm, m, nm))
    print("pdf_vector에서 보이는 예전 이름 %d/%d, 옮긴 이름 %d개 중 같은 객체 %d개"
          % (len(old_names) - len(gone), len(old_names), sum(len(v) for v in MOVES.values()), same))
    print("기준 커밋에서 모듈 수준으로 보이던 이름(import 포함) %d개 중 지금도 보이는 것 %d개"
          % (len(visible), len(visible) - len(lost) - len(gone)))
    for m in ["pdf_vector"] + list(MOVES):
        mod = importlib.import_module("hazop.extract.adapters." + m)
        with open(mod.__file__, encoding="utf-8") as fh:
            table = symtable.symtable(fh.read(), m, "exec")
        bad += ["정의되지 않은 전역 이름: %s.%s" % (m, nm) for nm in sorted(undefined_globals(table, mod))]
    for line in bad:
        print("문제: %s" % line)
    print("결과: %s" % ("문제 %d건" % len(bad) if bad else "통과"))
    return 1 if bad else 0


def module_names(src):
    """모듈 수준에서 묶이는 이름 전부. 최상위 문장이 정의한 것에 import로 들어온 이름(`pdf_vector.TAG_RE` 등)을 더한다."""
    out = set()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    return out


def undefined_globals(table, mod):
    """함수 안에서 전역으로 읽는 이름 가운데 모듈에도 내장에도 없는 것(옮기면서 빠뜨린 import)."""
    out = set()
    for sym in table.get_symbols():
        name = sym.get_name()
        if (sym.is_global() or table.get_type() == "module") and sym.is_referenced()                 and not hasattr(mod, name) and not hasattr(builtins, name):
            out.add(name)
    for child in table.get_children():
        out |= undefined_globals(child, mod)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("apply", "check"))
    args = ap.parse_args(argv)
    return apply() if args.cmd == "apply" else check()


if __name__ == "__main__":
    sys.exit(main())
