"""`데이터/`·`참고자료/` 경로 참조 목록과 폴더 현황을 만든다(docs/2026-11-09-data-consolidation).

    python scripts/inventory_data_paths.py [--repo <저장소>] [--out <출력 폴더>]

읽기만 한다. 출력 폴더에 세 파일을 쓴다(같은 저장소 상태면 같은 내용).
- references.csv: 참조마다 파일·행·원본 종류·루트·하위 폴더·대상 분류·접근 방식·행 내용
- folders.csv: 하위 폴더마다 파일 수(git 추적·미추적·ignore), 크기, 배포본 묶음 여부, 분류, 참조 수
- summary.md: 위 두 표의 요약

이전 세션은 이전 전후에 다시 돌려 두 결과를 비교한다. 대상 분류는 FOLDER_CLASS 표 하나로 정한다.
"""

import argparse
import importlib.util
import collections
import csv
import os
import re
import subprocess
import sys

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DEFAULT = os.path.join("docs", "2026-11-09-data-consolidation", "inventory")
ROOTS = ("데이터", "참고자료")

# (루트, 하위 폴더) → (분류, 설명). 분류: 자원(읽기 전용 기준 자료) / 작업(사람·앱이 쓰는 데이터) /
# 표본(저장소에 넣은 작업 데이터 예시) / 참고(문서·샘플 도면) / 대용량참고(git 제외)
FOLDER_CLASS = {
    ("데이터", "이탈후보"): ("자원", "KOSHA 이탈 카탈로그와 구간별 적용 판단"),
    ("데이터", "기준표"): ("자원", "위험도 기준표, 일반 초기사건 범주"),
    ("데이터", "패턴"): ("자원", "기기 유형별 원인·결과 패턴"),
    ("데이터", "평가기준"): ("표본", "구간별 평가 기준 표본"),
    ("데이터", "고정응답"): ("표본", "AI 대신 쓰는 고정 응답(작업 루트에서 읽고 씀)"),
    ("데이터", "구간"): ("작업", "구간 JSON"),
    ("데이터", "지식"): ("작업", "지식그래프 카드 CSV"),
    ("데이터", "검토구간"): ("작업", "프로젝트 검토구간 저장본"),
    ("데이터", "분석결과"): ("작업", "분석 결과 저장본"),
    ("데이터", "분석결과-시험"): ("작업", "고정 응답(시험) 분석 결과, 실제 결과와 따로 둠(AI 연결 D5)"),
    ("데이터", "백업"): ("작업", "앱이 이전 전에 만든 백업"),
    ("데이터", "초기사건"): ("작업", "초기사건 그룹 저장본(P3)"),
    ("데이터", "도면수정"): ("작업", "도면 추출 수정 OPS"),
    ("데이터", "도면연결"): ("작업", "도면 간 수동 연결"),
    ("데이터", "잠재후보"): ("작업", "지식그래프 잠재 후보 판단"),
    ("데이터", "스키마"): ("작업", "프로젝트 지식그래프 스키마 확장(기획)"),
    ("데이터", "참고자료"): ("대용량참고", "APR1400 DCD 원본·추출 도면(git 제외)"),
    ("참고자료", "HAZOP 기법"): ("참고", "KOSHA 지침 원본 PDF(git 제외)"),
    ("참고자료", "P&ID 기호 카탈로그"): ("참고", "P&ID 기호 카탈로그"),
    ("참고자료", "P&ID 도면 샘플"): ("참고", "P&ID 도면 샘플(검사·테스트 입력)"),
    ("참고자료", "참고 사진"): ("참고", "외부 데모 촬영본(git 제외)"),
}

TEXT_EXT = {".py", ".md", ".json", ".csv", ".spec", ".ps1", ".bat", ".cmd", ".txt", ".toml", ".ini", ".cfg",
            ".yml", ".yaml", ".html", ".js"}
EXCLUDE_PREFIX = ("licenses/", ".claude/worktrees/", "docs/2026-11-09-data-consolidation/",
                  "scripts/inventory_data_paths.py")
MAX_BYTES = 2_000_000

# 접근 방식: 행에서 처음 맞는 것(앞쪽이 우선). paths 함수를 거치는지, 저장소 루트를 직접 붙이는지 가른다.
ACCESSORS = (
    ("resource_path", re.compile(r"\bresource_(?:path|root)\b")),
    ("work_path", re.compile(r"\bwork_(?:path|root)\b|\boutput_root\b|\bstore_root\b")),
    ("program_path", re.compile(r"\bprogram_(?:path|root)\b")),
    ("repo_root", re.compile(r"\bREPO(?:_ROOT)?\b|\brepo_root\b|\bROOT\b|__file__")),
)

SEP = r"[/\\]+"
ROOT_RE = re.compile("(데이터|참고자료)")
ARG_RE = re.compile(r"""^["']\s*,\s*["']([^"']+)["']""")
# '데이터'는 일반 낱말이기도 하다. 뒤에 경로 구분자가 없으면 따옴표·백틱으로 감싼 낱말일 때만 경로로 센다.
QUOTED_BEFORE = re.compile(r"""["'`]$""")
QUOTED_AFTER = re.compile(r"""^["'`]""")
DOC_TOPS = ("specs", "design", "records", "docs")


def git_lines(repo, *args):
    out = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=repo, capture_output=True, check=True)
    return [x for x in out.stdout.decode("utf-8").split("\0") if x]


def file_kind(rel):
    if rel in (".gitignore", ".gitattributes"):
        return rel[1:]
    if rel.endswith(".spec"):
        return "spec"
    top = rel.split("/", 1)[0]
    if top in ROOTS:
        return "데이터내부"
    if top == ".claude":
        return ".claude"
    if rel.endswith(".md") or top in DOC_TOPS:
        return "문서"
    return {"hazop": "코드", "tests": "테스트", "scripts": "스크립트", "packaging": "패키징",
            ".claude": ".claude"}.get(top, "기타")


def known_subs(repo):
    subs = {r: set() for r in ROOTS}
    for (root, sub) in FOLDER_CLASS:
        subs[root].add(sub)
    for root in ROOTS:
        top = os.path.join(repo, root)
        if os.path.isdir(top):
            subs[root].update(d for d in os.listdir(top) if os.path.isdir(os.path.join(top, d)))
    return {r: sorted(s, key=len, reverse=True) for r, s in subs.items()}


def parse_refs(line, subs, is_gitignore=False):
    """행 안의 (루트, 하위 폴더 또는 '') 목록. '데이터/참고자료'는 데이터 하위 하나로 센다."""
    refs = []
    pos = 0
    while True:
        m = ROOT_RE.search(line, pos)
        if not m:
            return refs
        root, rest = m.group(1), line[m.end():]
        sub, used = "", 0
        sep = re.match(SEP, rest)
        if sep:
            tail = rest[sep.end():]
            sub = next((s for s in subs[root] if tail.startswith(s) and not re.match(r"[\w&]", tail[len(s):])), "")
            if not sub:
                tok = re.match(r"""\w[^/\\"'\s,)\]`*]+""", tail)
                sub = tok.group(0) if tok else ""
            used = sep.end() + len(sub)
        elif QUOTED_BEFORE.search(line[:m.start()]) and QUOTED_AFTER.match(rest):
            arg = ARG_RE.match(rest)
            if arg and arg.group(1) not in ROOTS:
                sub, used = arg.group(1), arg.end()
        elif not is_gitignore:
            pos = m.end()
            continue
        refs.append((root, sub))
        pos = m.end() + used


def accessor(line):
    return next((name for name, rx in ACCESSORS if rx.search(line)), "literal")


def bundled_dirs(repo):
    """그 저장소의 scripts/build_package.py가 정한 DATA_DIRS·DATA_FILES. 폴더 표에서 계산되므로 불러서 읽는다."""
    path = os.path.join(repo, "scripts", "build_package.py")
    if not os.path.isfile(path):
        return set()
    sys.path.insert(0, repo)
    spec = importlib.util.spec_from_file_location("inventory_build_package", path)
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    return set(bp.DATA_DIRS) | set(bp.DATA_FILES)


def scan_files(repo):
    tracked = set(git_lines(repo, "ls-files", "-z"))
    untracked = set(git_lines(repo, "ls-files", "-z", "--others", "--exclude-standard"))
    ignored = set(git_lines(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", *ROOTS))
    files = {".gitignore", ".gitattributes"} | tracked | untracked | ignored
    keep = []
    for rel in files:
        if rel.startswith(EXCLUDE_PREFIX):
            continue
        if rel not in (".gitignore", ".gitattributes") and os.path.splitext(rel)[1].lower() not in TEXT_EXT:
            continue
        full = os.path.join(repo, rel)
        if os.path.isfile(full) and os.path.getsize(full) <= MAX_BYTES:
            keep.append(rel)
    return sorted(keep), tracked, untracked, ignored


def collect_refs(repo, files, subs):
    rows = []
    for rel in files:
        with open(os.path.join(repo, rel), encoding="utf-8", errors="replace") as fh:
            for no, line in enumerate(fh, 1):
                if not ROOT_RE.search(line):
                    continue
                for root, sub in parse_refs(line, subs, rel in (".gitignore", ".gitattributes")):
                    cls = FOLDER_CLASS.get((root, sub), ("루트" if not sub else "미분류", ""))[0]
                    rows.append({"file": rel, "line": no, "kind": file_kind(rel), "root": root, "sub": sub,
                                 "class": cls, "accessor": accessor(line), "text": line.strip()[:200]})
    return rows


def folder_rows(repo, tracked, untracked, ignored, bundled, refs):
    counts = collections.Counter((r["root"], r["sub"]) for r in refs)
    pairs = set(FOLDER_CLASS)
    for root in ROOTS:
        top = os.path.join(repo, root)
        if os.path.isdir(top):
            pairs.update((root, d) for d in os.listdir(top) if os.path.isdir(os.path.join(top, d)))
    rows = []
    for root, sub in sorted(pairs):
        prefix = "%s/%s/" % (root, sub)
        n = {"tracked": 0, "untracked": 0, "ignored": 0}
        size = 0
        top = os.path.join(repo, root, sub)
        for d, _, fs in os.walk(top):
            for f in fs:
                full = os.path.join(d, f)
                rel = os.path.relpath(full, repo).replace("\\", "/")
                size += os.path.getsize(full)
                n["tracked" if rel in tracked else "untracked" if rel in untracked else "ignored"] += 1
        cls, note = FOLDER_CLASS.get((root, sub), ("미분류", ""))
        rows.append({"folder": prefix.rstrip("/"), "class": cls, "exists": os.path.isdir(top),
                     "tracked": n["tracked"], "untracked": n["untracked"], "ignored": n["ignored"],
                     "bytes": size, "bundled": prefix.rstrip("/") in bundled, "refs": counts[(root, sub)],
                     "note": note})
    return rows


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def summary(refs, folders):
    kinds = sorted({r["kind"] for r in refs})
    by_class = collections.defaultdict(collections.Counter)
    for r in refs:
        by_class[r["class"]][r["kind"]] += 1
    cls_rows = [[c] + [by_class[c][k] for k in kinds] + [sum(by_class[c].values())] for c in sorted(by_class)]
    acc = collections.defaultdict(collections.Counter)
    for r in refs:
        if r["kind"] in ("코드", "스크립트", "패키징", "테스트"):
            acc[r["kind"]][r["accessor"]] += 1
    acc_names = sorted({a for c in acc.values() for a in c})
    acc_rows = [[k] + [acc[k][a] for a in acc_names] for k in sorted(acc)]
    files = collections.Counter(r["kind"] for r in {(r["file"], r["kind"]): r for r in refs}.values())
    fold_rows = [[f["folder"], f["class"], "예" if f["exists"] else "없음", f["tracked"], f["untracked"],
                  f["ignored"], "%.1f MB" % (f["bytes"] / 1e6), "예" if f["bundled"] else "", f["refs"]]
                 for f in folders]
    unknown = sorted({"%s/%s" % (r["root"], r["sub"]) for r in refs if r["class"] == "미분류"})
    return "\n\n".join([
        "# 경로 참조 목록 요약",
        "`python scripts/inventory_data_paths.py`가 만든 파일이다. 손으로 고치지 않는다.",
        "참조 %d건, 참조가 있는 파일 %d개(%s)." % (
            len(refs), sum(files.values()), ", ".join("%s %d" % (k, files[k]) for k in sorted(files))),
        "## 하위 폴더 현황",
        table(["폴더", "분류", "있음", "git 추적", "미추적", "ignore", "크기", "배포본", "참조"], fold_rows),
        "## 대상 분류 × 원본 종류",
        table(["분류"] + kinds + ["계"], cls_rows),
        "## 실행 코드의 접근 방식",
        "resource_path·work_path는 paths 함수를 거친 참조, repo_root는 저장소 루트를 직접 붙인 참조, literal은 행만으로는 "
        "알 수 없는 참조(상수 정의, 인자 기본값, 테스트 픽스처 등)다.",
        table(["원본 종류"] + acc_names, acc_rows),
        "## 표에 없는 하위 이름",
        ("FOLDER_CLASS에 없는 하위 이름: " + ", ".join("`%s`" % u for u in unknown)) if unknown else "없음.",
    ]) + "\n"


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--out", default=None, help="출력 폴더(기본: <repo>/%s)" % OUT_DEFAULT.replace("\\", "/"))
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    out = os.path.abspath(args.out or os.path.join(repo, OUT_DEFAULT))
    files, tracked, untracked, ignored = scan_files(repo)
    refs = collect_refs(repo, files, known_subs(repo))
    folders = folder_rows(repo, tracked, untracked, ignored, bundled_dirs(repo), refs)
    os.makedirs(out, exist_ok=True)
    write_csv(os.path.join(out, "references.csv"), refs,
              ["file", "line", "kind", "root", "sub", "class", "accessor", "text"])
    write_csv(os.path.join(out, "folders.csv"), folders,
              ["folder", "class", "exists", "tracked", "untracked", "ignored", "bytes", "bundled", "refs", "note"])
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(summary(refs, folders))
    print("참조 %d건, 파일 %d개 훑음 → %s" % (len(refs), len(files), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
