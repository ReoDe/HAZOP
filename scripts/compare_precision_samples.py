"""판정을 채운 표본 표의 노드가 다른 실행에서 어떤 종류가 되었는지 센다(같은 표본으로 보는 규칙 전후).

실행: python scripts/compare_precision_samples.py <판정 채운 audit.tsv> <앞 목록.jsonl> <뒤 목록.jsonl>
  audit.tsv는 앞 목록으로 build_precision_samples.py → analyze_precision_verdicts.py를 거친 것이다.
  목록은 inventory_node_kinds.py 출력이다. 같은 쪽에서 상자 가운데가 1pt 안인 노드를 같은 노드로 본다.
출력: 종류가 바뀌거나 없어진 표본을 한 줄씩, 끝에 '앞 판정 · 뒤 상태'별 개수(같음, 미분류, 바뀜:<종류>, 노드 없음).
"""

import argparse
import collections
import json


def center(r):
    x0, y0, x1, y1 = r["bbox"]
    return round((x0 + x1) / 2), round((y0 + y1) / 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("audit")
    ap.add_argument("before")
    ap.add_argument("after")
    a = ap.parse_args()
    with open(a.audit, encoding="utf-8") as fh:
        rows = [ln.split("\t") for ln in fh.read().splitlines()[1:]]
    with open(a.before, encoding="utf-8") as fh:
        before = {(r["page"], r["id"]): r for r in map(json.loads, fh)}
    index = collections.defaultdict(list)
    with open(a.after, encoding="utf-8") as fh:
        for r in map(json.loads, fh):
            index[(r["page"],) + center(r)].append(r)
    count = collections.Counter()
    for group, _, sample, page, node, kind, label, verdict in rows:
        cx, cy = center(before[(page, node)])
        hit = next((r for dx in (-1, 0, 1) for dy in (-1, 0, 1) for r in index.get((page, cx + dx, cy + dy), [])), None)
        new = hit["kind"] if hit else "(노드 없음)"
        state = "같음" if new == kind else "미분류" if new is None else "바뀜:%s" % new
        count[(verdict or "판정 없음", state)] += 1
        if state != "같음":
            print(group, sample, page, node, kind, "->", new, "|", verdict, "|", label[:40])
    print()
    for (verdict, state), n in sorted(count.items()):
        print("앞 %s · 뒤 %s: %d" % (verdict, state, n))


if __name__ == "__main__":
    main()
