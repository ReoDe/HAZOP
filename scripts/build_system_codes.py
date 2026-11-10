"""APR1400 DCD 계통 약어 → 그림 번호 대응표(계통약어.csv)를 만든다. 다른 계통으로 가는 연결 표시('CV:RDT / SHEET 5',
'MS / SHEET 2"A"')를 짝지으려면 약어가 어느 그림인지 알아야 한다.

  python scripts/build_system_codes.py [--input-dir <도면별>] [--catalog <도면목록.csv>] [--out <계통약어.csv>]

근거(출처 열):
- [문서] 도면목록의 계통 이름 괄호 안 약어가 도면에 쓰인 약어와 글자 그대로 같다(예: '계기용 공기계통(IA)' → IA).
- [추론] 계통 이름 약어가 X로 시작하는 그림(CV → CVCS) 중, 그림 A 시트 a의 'X / SHEET b' 화살표에 대해 그 그림 시트 b에
  시트 a를 가리키는 화살표가 있는 짝이 가장 많은 그림. 약어 근거가 없는 약어는 정하지 않는다.
'사람 확인' 열은 처음에 '미확인'. 사람이 확인하면 '확인'으로 바꾼다. 다시 만들 때 이미 '확인'인 행은 그대로 둔다.
짝짓기(hazop.graph.project)는 [문서] 또는 '확인' 행만 확정 연결에 쓰고, 나머지는 후보 연결로만 보인다.
"""

import argparse
import collections
import csv
import multiprocessing
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

FIELDS = ["계통약어", "그림번호", "계통명", "출처", "근거", "사람 확인"]
SHEET_RE = re.compile(r"SHEET\s*(\d+)")
BARE_RE = re.compile(r"^[A-Z]{2}$")


def _work(job):
    path, dwg = job
    from hazop.extract.adapters import pdf_vector
    ex = pdf_vector.extract(path, page=0)
    return dwg, [{"code": (n.get("attributes") or {}).get("to_system"), "label": n.get("label_text") or ""}
                 for n in ex["nodes"] if n.get("kind") == "continuation"]


def arrows_with_codes(input_dir, catalog, jobs):
    rows = list(csv.DictReader(open(catalog, encoding="utf-8-sig")))
    todo = [(os.path.join(input_dir, r["개별파일"]), (r["그림번호"], int(r["시트"]))) for r in rows]
    with multiprocessing.Pool(jobs) as pool:
        done = pool.map(_work, todo, chunksize=1)
    out = []
    for (fig, sheet), arrows in done:
        for a in arrows:
            m = SHEET_RE.search(a["label"])
            bare = next((line.strip() for line in a["label"].splitlines() if BARE_RE.match(line.strip())), None)
            code = a["code"] or bare  # 범례식 'MS / SHEET 2"A"'처럼 라벨에만 있는 두 글자 약어도 센다
            if code and m:
                out.append((fig, sheet, code, int(m.group(1))))
    return rows, out


def infer(rows, arrows, names):
    """→ {약어: (그림, 표 수, 계통 이름 약어)}. 후보 그림은 계통 이름 약어가 그 약어로 시작하는 그림뿐이다
    (CV → CVCS). 시트 번호만으로는 우연히 맞는 짝이 많아(시트 1~4는 흔하다) 약어 근거 없는 추정은 하지 않는다.
    후보 중 서로 가리키는 짝(그 그림의 시트 b에서 이 시트를, 이 그림의 계통 이름 약어로 시작하는 약어로 가리킴)이 가장
    많은 그림을 고르고, 짝이 없거나 동률이면 정하지 않는다."""
    sheets = collections.defaultdict(set)
    for r in rows:
        sheets[r["그림번호"]].add(int(r["시트"]))
    back = collections.defaultdict(set)  # (그림, 시트) → 그 시트의 (가리키는 시트 번호, 약어)
    for fig, sheet, code, to_sheet in arrows:
        back[(fig, sheet)].add((to_sheet, code))
    out = {}
    for code in sorted({c for _, _, c, _ in arrows}):
        cands = {fig: acr for fig, (_, acrs) in names.items() for acr in acrs if acr.startswith(code)}
        votes = collections.Counter()
        for fig, sheet, c, to_sheet in arrows:
            if c != code:
                continue
            mine = names[fig][1]  # 되짚는 화살표의 약어는 이 그림의 계통 이름 약어로 시작해야 진짜 서로 가리키는 짝이다
            for cand in cands:
                if cand != fig and to_sheet in sheets[cand] and any(
                        s == sheet and any(a.startswith(c2) for a in mine) for s, c2 in back[(cand, to_sheet)]):
                    votes[cand] += 1
        ranked = votes.most_common(2) + [(None, 0)]
        if ranked[0][1] and ranked[0][1] > ranked[1][1]:
            out[code] = (ranked[0][0], ranked[0][1], cands[ranked[0][0]])
    return out


def acronyms(rows):
    """그림 번호 → 계통 이름(괄호 안 약어 목록)."""
    out = {}
    for r in rows:
        acr = [a for group in re.findall(r"\(([A-Z/]+)\)", r["계통명"]) for a in group.split("/") if a]  # '(SIS/SCS)'
        out.setdefault(r["그림번호"], (r["계통명"], acr))
    return out


def build(rows, arrows, old):
    names = acronyms(rows)
    owners = collections.defaultdict(set)
    for fig, (_, acr) in names.items():
        for a in acr:
            owners[a].add(fig)
    doc = {a: figs.pop() for a, figs in owners.items() if len(figs) == 1}  # 여러 그림이 같이 쓰는 약어(RCS 등)는 문서 근거가 아니다
    inferred = infer(rows, arrows, names)
    used = sorted({code for _, _, code, _ in arrows} | set(old))
    table = []
    for code in used:
        if (old.get(code, {}).get("사람 확인") or "").strip() == "확인":
            table.append({k: old[code].get(k) or "" for k in FIELDS})
            continue
        if code in doc:
            fig = doc[code]
            table.append({"계통약어": code, "그림번호": fig, "계통명": names[fig][0], "출처": "[문서]",
                          "근거": "도면목록 계통 이름의 약어 (%s)" % code, "사람 확인": "미확인"})
        elif code in inferred:
            fig, n, acr = inferred[code]
            why = "계통 이름 약어 %s가 %s로 시작; 서로 가리키는 짝 %d개" % (acr, code, n)
            table.append({"계통약어": code, "그림번호": fig, "계통명": names[fig][0], "출처": "[추론]", "근거": why,
                          "사람 확인": "미확인"})
    return table


def main(argv=None):
    from hazop import paths
    from hazop.console import safe_console
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", default=paths.folder("APR1400", "도면별"))
    ap.add_argument("--catalog", default=paths.folder("APR1400", "도면목록.csv"))
    ap.add_argument("--out", default=paths.folder("APR1400", "계통약어.csv"))
    ap.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2)))
    args = ap.parse_args(argv)
    old = {}
    if os.path.isfile(args.out):
        from hazop.graph import project
        old = {r["계통약어"]: r for r in project.read_system_code_rows(args.out) or () if r.get("계통약어")}
    rows, arrows = arrows_with_codes(args.input_dir, args.catalog, args.jobs)
    table = build(rows, arrows, old)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        w.writerows(table)
    os.replace(tmp, args.out)  # 쓰다 실패해도 사람이 '확인'한 기존 표는 남는다
    print("약어 %d개 중 대응 %d개([문서] %d, [추론] %d, 확인 %d) → %s" % (
        len({c for _, _, c, _ in arrows}), len(table), sum(t["출처"] == "[문서]" for t in table),
        sum(t["출처"] == "[추론]" for t in table), sum(t["사람 확인"] == "확인" for t in table), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
