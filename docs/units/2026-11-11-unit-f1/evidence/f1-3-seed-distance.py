"""F1-3: 검은 채움 묶음마다 사전의 검정 견본까지 거리를 재서, 밸브로 올릴 문턱(pdf_vector.BLACK_SEED_DISTANCE)의 여유를 본다.

  python f1-3-seed-distance.py <cluster_unclassified.py --black-fills --no-library 결과 폴더> <라벨.csv>

라벨.csv(순위, id)는 사람이 그림을 보고 게이트·글로브라고 정한 묶음이다. 그 묶음의 구성원과 나머지 묶음의 구성원을 나눠,
검정 견본(set_attributes가 있는 견본)까지의 가장 가까운 거리를 낸다. 견본의 max_distance는 무시하고 잰다(거리만 본다).
라벨 붙인 쪽의 최댓값과 나머지 쪽의 최솟값 사이에 문턱이 있어야 한다. 저장소 파일은 고치지 않는다.
"""

import collections
import csv
import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "symbols"))

from hazop import paths  # noqa: E402
from hazop.extract import symbols  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
import cluster_unclassified as cu  # noqa: E402


def loose_library(tmp):
    """저장소 사전의 사본에서 검정 견본의 max_distance만 0.8로 올린 것(문턱 밖 거리도 재려고)."""
    root = os.path.join(tmp, "symbols")
    shutil.copytree(paths.folder("symbols"), root)
    for folder, _, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".json") or fn == symbols.BUNDLES_FILE:
                continue
            path = os.path.join(folder, fn)
            with open(path, encoding="utf-8") as fh:
                entry = json.load(fh)
            black = [t for t in entry["match"] if t.get("set_attributes", {}).get("normal_position") == "NC"
                     and t.get("composition", {}).get("solid")]
            if black:
                for t in black:
                    t["max_distance"] = 0.8
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(entry, fh, ensure_ascii=False)
    return symbols.Library.load(root)


def main():
    cand, labels = sys.argv[1], sys.argv[2]
    with open(labels, encoding="utf-8-sig") as fh:
        labeled = {int(r["순위"]): r["id"] for r in csv.DictReader(fh) if r.get("id")}
    with open(os.path.join(cand, "묶음.json"), encoding="utf-8") as fh:
        rank_of = {(seq, i): c["rank"] for c in json.load(fh) for seq, i in c["members"]}
    tmp = tempfile.mkdtemp(prefix="hazop-f1-3-")
    try:
        lib = loose_library(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    inside, outside = [], []
    for r in cu.load_rows(os.path.join(cand, "쪽")):
        m = lib.match(cu.as_signature(r), r["inside"])
        if not m.candidates:
            continue
        rank = rank_of[(r["seq"], r["i"])]
        row = (m.candidates[0][1], rank, r["seq"], r["key"], r["size"])
        (inside if rank in labeled else outside).append(row)
    inside.sort()
    outside.sort()
    limit = pdf_vector.BLACK_SEED_DISTANCE
    print("문턱 %.2f칸. 사전 판 %s" % (limit, symbols.Library.load().versions))
    print("라벨 붙인 묶음(%d개 묶음)의 구성원 %d개: 거리 최대 %.3f, 문턱을 넘는 것 %d개"
          % (len(labeled), len(inside), inside[-1][0], sum(1 for x in inside if x[0] > limit)))
    hist = collections.Counter(min(int(x[0] / 0.05), 16) for x in outside)
    print("그 밖 묶음의 구성원 중 같은 구성·크기의 검정 견본이 있는 것 %d개: 거리 구간별 수" % len(outside))
    for k in sorted(hist):
        print("  [%.2f, %.2f): %d" % (k * 0.05, (k + 1) * 0.05, hist[k]))
    print("그 밖 묶음에서 가까운 순 15개(거리, 묶음 순위, 쪽, 구성 키, 크기)")
    for x in outside[:15]:
        print("  %.3f  %d  %s  %s  %s" % x)


if __name__ == "__main__":
    main()
