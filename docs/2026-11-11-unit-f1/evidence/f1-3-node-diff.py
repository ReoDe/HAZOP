"""F1-3(검게 칠한 닫힌 밸브) 전후의 APR1400 추출 결과를 노드 단위로 견주는 스크립트.

  python f1-3-node-diff.py dump --repo <코드 폴더> --out <폴더> [--input-dir <쪽별 PDF 폴더>] [--jobs 6]
      <코드 폴더>의 추출기와 기호 사전으로 143쪽을 추출해 <폴더>/<순번>.json(추출 JSON 전체)을 쓴다.
      '전'은 기준 커밋을 꺼낸 분리 작업트리를, '후'는 주 체크아웃을 --repo로 준다.
  python f1-3-node-diff.py compare <전 폴더> <후 폴더> [--csv <노드 변화 목록.csv>]
      같은 자리(상자가 0.5pt 안에서 같음)의 노드를 짝지어 종류·태그·정상 위치가 바뀐 수, 새로 생긴 노드와 없어진
      노드를 종류별로 센다. 미확인 수도 사유별로 견준다.
  python f1-3-node-diff.py carry <전 폴더> <후 폴더>
      '전' 추출의 모든 기호 노드와 관계에 사람 수정(set_tag)을 하나씩 만들고 '후' 추출에 적용해 본다
      (hazop/extract/corrections.py). 적용된 수, 번호가 밀려 자리로 다시 찾은 수, 적용하지 못한 수와 사유를 낸다.
      적용된 수정이 '전'과 다른 자리의 대상에 들어갔는지도 센다(0이어야 한다).

이 스크립트는 저장소 파일을 고치지 않는다. 쪽별 PDF는 저장소에 없다(resources/references/APR1400_DCD/by-drawing).
"""

import argparse
import collections
import csv
import glob
import json
import multiprocessing
import os
import re
import sys


def _extract(job):
    repo, path, dst = job
    sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector
    ex = pdf_vector.extract(path, page=0)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(ex, fh, ensure_ascii=False)
    return os.path.basename(dst)


def dump(args):
    repo = os.path.abspath(args.repo)
    sys.path.insert(0, repo)
    from hazop import paths
    src = args.input_dir or paths.folder("APR1400", "by-drawing")
    files = sorted(glob.glob(os.path.join(src, "*.pdf")))
    if not files:
        sys.exit("쪽별 PDF가 없음: %s" % src)
    os.makedirs(args.out, exist_ok=True)
    jobs = [(repo, f, os.path.join(args.out, os.path.basename(f).split("_")[0] + ".json")) for f in files]
    with multiprocessing.Pool(args.jobs) as pool:
        done = pool.map(_extract, jobs, chunksize=1)
    print("%d쪽 → %s (코드: %s)" % (len(done), args.out, repo))


def _pages(folder):
    out = {}
    for f in sorted(glob.glob(os.path.join(folder, "[0-9]*.json"))):
        with open(f, encoding="utf-8") as fh:
            out[os.path.basename(f)[:-5]] = json.load(fh)
    return out


def _box(n):
    g = n["geometry"]
    return (g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"])


def _symbol_nodes(ex):
    return [n for n in ex["nodes"] if n.get("geometry") and "-sym-" in (n.get("source_object_id") or "")]


def _state(n):
    return (n["kind"], n["tag"], (n.get("attributes") or {}).get("normal_position"))


def compare(args):
    before, after = _pages(args.before), _pages(args.after)
    if sorted(before) != sorted(after):
        sys.exit("쪽 목록이 다름: 전 %d, 후 %d" % (len(before), len(after)))
    kind_change, tag_change, pos_change = collections.Counter(), collections.Counter(), collections.Counter()
    born, gone = collections.Counter(), collections.Counter()
    unknown_b, unknown_a = collections.Counter(), collections.Counter()
    rows, counts = [], collections.Counter()
    for seq in sorted(before):
        b, a = before[seq], after[seq]
        unknown_b.update(u["check"] for u in b["validation"]["unknowns"])
        unknown_a.update(u["check"] for u in a["validation"]["unknowns"])
        counts["nodes_before"] += len(b["nodes"])
        counts["nodes_after"] += len(a["nodes"])
        counts["relations_before"] += len(b["relations"])
        counts["relations_after"] += len(a["relations"])
        index = collections.defaultdict(list)
        for n in _symbol_nodes(a):
            index[tuple(round(v) for v in _box(n))].append(n)
        used = set()
        for n in _symbol_nodes(b):
            box = _box(n)
            near = [m for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    for m in index.get((round(box[0]) + dx, round(box[1]) + dy, round(box[2]) + dx, round(box[3]) + dy), ())
                    if id(m) not in used and max(abs(p - q) for p, q in zip(box, _box(m))) <= 0.5]
            if not near:
                gone[n["kind"]] += 1
                rows.append([seq, "없어짐", n["kind"], "", n["tag"] or "", "", "", ""] + [round(v, 1) for v in box])
                continue
            m = near[0]
            used.add(id(m))
            (k0, t0, p0), (k1, t1, p1) = _state(n), _state(m)
            if k0 != k1:
                kind_change[(k0, k1)] += 1
            if t0 != t1:
                tag_change[(t0 is not None, t1 is not None)] += 1
            if p0 != p1:
                pos_change[(p0, p1)] += 1
            if (k0, t0, p0) != (k1, t1, p1):
                rows.append([seq, "바뀜", k0, k1, t0 or "", t1 or "", p0 or "", p1 or ""] + [round(v, 1) for v in box])
        for m in _symbol_nodes(a):
            if id(m) not in used:
                born[(m["kind"], (m.get("attributes") or {}).get("normal_position"))] += 1
                rows.append([seq, "새로 생김", "", m["kind"], "", m["tag"] or "",
                             "", (m.get("attributes") or {}).get("normal_position") or ""] + [round(v, 1) for v in _box(m)])
    print("쪽 %d · 노드 %d → %d · 관계 %d → %d" % (len(before), counts["nodes_before"], counts["nodes_after"],
                                               counts["relations_before"], counts["relations_after"]))
    print("\n같은 자리 기호의 종류 변화(전 → 후: 수)")
    for (k0, k1), n in sorted(kind_change.items(), key=lambda x: -x[1]):
        print("  %s → %s: %d" % (k0, k1, n))
    print("\n같은 자리 기호의 정상 위치 변화")
    for (p0, p1), n in sorted(pos_change.items(), key=lambda x: -x[1]):
        print("  %s → %s: %d" % (p0, p1, n))
    print("\n같은 자리 기호의 태그 변화(있음 여부 전 → 후)")
    for (t0, t1), n in sorted(tag_change.items(), key=lambda x: -x[1]):
        print("  %s → %s: %d" % ("있음" if t0 else "없음", "있음" if t1 else "없음", n))
    print("\n새로 생긴 기호 노드(종류, 정상 위치): %d" % sum(born.values()))
    for (k, p), n in sorted(born.items(), key=lambda x: -x[1]):
        print("  %s %s: %d" % (k, p or "", n))
    print("\n없어진 기호 노드(종류): %d" % sum(gone.values()))
    for k, n in sorted(gone.items(), key=lambda x: -x[1]):
        print("  %s: %d" % (k, n))
    print("\n미확인 사유별(전 → 후, 차)")
    for check in sorted(set(unknown_b) | set(unknown_a), key=lambda c: -unknown_b[c]):
        print("  %s: %d → %d (%+d)" % (check, unknown_b[check], unknown_a[check], unknown_a[check] - unknown_b[check]))
    print("  합계: %d → %d (%+d)" % (sum(unknown_b.values()), sum(unknown_a.values()),
                                 sum(unknown_a.values()) - sum(unknown_b.values())))
    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["seq", "change", "kind_before", "kind_after", "tag_before", "tag_after", "position_before",
                        "position_after", "x0", "y0", "x1", "y1"])
            w.writerows(rows)
        print("\n노드 변화 목록 %d줄 → %s" % (len(rows), args.csv))


def _carry_page(job):
    repo, seq, before_path, after_path = job
    sys.path.insert(0, repo)
    from hazop.extract import corrections
    with open(before_path, encoding="utf-8") as fh:
        b = json.load(fh)
    with open(after_path, encoding="utf-8") as fh:
        a = json.load(fh)
    fp_b = corrections._fingerprints(b)
    ops = []
    targets = [(n["source_object_id"], "node") for n in b["nodes"] if "-sym-" in (n.get("source_object_id") or "")]
    targets += [(r["source_object_id"], "relation") for r in b["relations"]]
    for k, (sid, kind) in enumerate(targets, 1):
        ops.append({"op_id": "c-%04d" % k, "op": "set_tag", "target": sid, "base": fp_b[sid], "refs": {},
                    "value": {"tag": "X-%04d" % k}, "by": "f1-3-carry", "at": "2026-11-11T00:00:00Z"})
    if not ops:
        return seq, {}
    out = corrections.apply(a, ops)["corrections"]
    fp_a = corrections._fingerprints(a)
    moved = {r["op_id"]: r["to"] for r in out.get("retargeted", [])}
    kind_of = dict(targets)
    stat = collections.Counter()
    for op in ops:
        stat["%s 수정" % kind_of[op["target"]]] += 1
    for op_id in out["applied"]:
        op = ops[int(op_id[2:]) - 1]
        kind = kind_of[op["target"]]
        stat["%s 적용" % kind] += 1
        if op_id in moved:
            stat["%s 적용(번호가 밀려 자리로 다시 찾음)" % kind] += 1
        if (fp_a.get(moved.get(op_id, op["target"])) or {}).get("at") != op["base"]["at"]:
            stat["%s 다른 자리에 적용" % kind] += 1
    for s in out["not_applicable"]:
        op = ops[int(s["op_id"][2:]) - 1]
        why = s["reason"].split(":")[0]
        if why == "대상이 바뀜":  # 무엇이 바뀌었는지(kind, tag, at, ends)까지 센다
            why += "(%s)" % "·".join(sorted(set(re.findall(r"(?:^|, )(kind|tag|at|ends) ", s["reason"].split(": ", 1)[1]))))
        stat["%s 적용 못 함: %s" % (kind_of[op["target"]], why)] += 1
    return seq, dict(stat)


def carry(args):
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    seqs = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(args.before, "[0-9]*.json")))
    jobs = [(repo, s, os.path.join(args.before, s + ".json"), os.path.join(args.after, s + ".json")) for s in seqs]
    total = collections.Counter()
    with multiprocessing.Pool(args.jobs) as pool:
        for _, stat in pool.map(_carry_page, jobs, chunksize=1):
            total.update(stat)
    print("쪽 %d (수정 적용 코드: %s)" % (len(seqs), repo))
    for key in sorted(total):
        print("  %s: %d" % (key, total[key]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--repo", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--input-dir")
    d.add_argument("--jobs", type=int, default=6)
    c = sub.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--csv")
    k = sub.add_parser("carry")
    k.add_argument("before")
    k.add_argument("after")
    k.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()
    {"dump": dump, "compare": compare, "carry": carry}[args.cmd](args)


if __name__ == "__main__":
    main()
