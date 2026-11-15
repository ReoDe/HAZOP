"""표본 표(build_precision_samples.py의 audit.tsv)에 판정을 채우고 무리마다 맞은 비율 표를 낸다.

실행: python scripts/analyze_precision_verdicts.py <표본 폴더> <판정.json>
판정 파일: {"<무리 이름>": [틀린 표본 번호, ...], ...}. 적지 않은 무리와 번호는 모두 맞음으로 본다. 표본 번호는 그림 칸 왼쪽
위 숫자(audit.tsv의 sample)다. 무리 이름은 audit.tsv의 group 그대로다(예: "PUMP", "check_valve | symbol:…").
출력: audit.tsv의 verdict 칸(맞음/틀림)을 채우고, 표준 출력에 Markdown 표(무리, 노드, 표본, 맞음, 틀린 비율)를 쓴다.
앞 단계: build_precision_samples.py. 뒤 단계: 규칙을 고친 뒤 compare_precision_samples.py로 같은 표본의 전후를 본다.
"""

import argparse
import collections
import json
import os


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    ap.add_argument("verdicts")
    a = ap.parse_args()
    with open(a.verdicts, encoding="utf-8") as fh:
        wrong = json.load(fh)
    path = os.path.join(a.folder, "audit.tsv")
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    unknown = set(wrong) - {ln.split("\t")[0] for ln in lines[1:]}
    if unknown:
        raise SystemExit("표에 없는 무리: %s" % ", ".join(sorted(unknown)))
    out, stat = [lines[0]], collections.OrderedDict()
    for ln in lines[1:]:
        c = ln.split("\t")
        bad = int(c[2]) in wrong.get(c[0], [])
        c[7] = "틀림" if bad else "맞음"
        out.append("\t".join(c))
        s = stat.setdefault(c[0], [int(c[1]), 0, 0])
        s[1] += 1
        s[2] += 0 if bad else 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("| 무리 | 노드 | 표본 | 맞음 | 틀린 비율 |")
    print("|---|---:|---:|---:|---:|")
    total = [0, 0, 0]
    for name, (nodes, picked, ok) in stat.items():
        print("| %s | %d | %d | %d | %.0f%% |" % (name, nodes, picked, ok, 100.0 * (picked - ok) / picked))
        total = [total[0] + nodes, total[1] + picked, total[2] + ok]
    if total[1]:
        print("| 합계 | %d | %d | %d | %.0f%% |" % (total[0], total[1], total[2], 100.0 * (total[1] - total[2]) / total[1]))
        # 표본 합계는 표본마다 같은 무게라 노드가 많은 무리가 덜 반영된다. 무리별 노드 수로 가중한 추정 오답 비율을 함께 낸다
        weighted = sum(nodes * (picked - ok) / picked for nodes, picked, ok in stat.values()) / total[0]
        print()
        print("노드 수로 가중한 추정 오답 비율: %.1f%% (Σ 노드×틀린 비율 / Σ 노드, 노드 %d)" % (100.0 * weighted, total[0]))


if __name__ == "__main__":
    main()
