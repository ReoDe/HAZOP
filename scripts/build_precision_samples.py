"""노드 목록(inventory_node_kinds.py 출력)에서 무리마다 표본을 뽑아 둘레 그림 한 장과 판정 칸이 빈 표를 만든다.

실행: python scripts/build_precision_samples.py <목록.jsonl> <출력 폴더> [--group word|kind|basis] [--per-group 15]
                                                [--input-dir 폴더]
  --group word : 이름 낱말 규칙(basis 'text_word:…')이 정한 노드를 낱말마다
          kind : 종류가 있는 노드를 종류마다
          basis: 종류가 있는 노드를 '종류 | 근거' 마다
  표본 시드는 무리 이름의 crc32라 같은 목록이면 같은 표본이 나온다.
출력: <출력 폴더>/<무리>.png(빨간 상자가 노드, 칸 위에 표본 번호·쪽·노드·종류·라벨)와
      <출력 폴더>/audit.tsv(칸: group, nodes, sample, page, node, kind, label, verdict. verdict는 비어 있다).
다음 순서: 그림을 보고 틀린 표본 번호를 판정 파일에 적은 뒤 analyze_precision_verdicts.py로 표를 만든다.
그림에는 도면 조각이 들어가므로 저장소 밖 작업 폴더에 둔다.
"""

import argparse
import collections
import glob
import json
import os
import random
import re
import sys
import zlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [REPO_ROOT, os.path.join(REPO_ROOT, "scripts")]

TILE, SCALE, COLS = 240, 5.0, 5


def group_of(row, how):
    if not row["kind"]:
        return None
    if how == "word":
        return row["basis"].split(":", 1)[1] if row["basis"].startswith("text_word:") else None
    if how == "kind":
        return row["kind"]
    return "%s | %s" % (row["kind"], row["basis"] or "-")


def main():
    import check_read_quality as rq
    from PIL import Image, ImageDraw
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inventory")
    ap.add_argument("out")
    ap.add_argument("--group", choices=("word", "kind", "basis"), default="word")
    ap.add_argument("--per-group", type=int, default=15)
    ap.add_argument("--input-dir", default=None)
    a = ap.parse_args()
    folder = a.input_dir or rq.default_input_dir()
    os.makedirs(a.out, exist_ok=True)
    groups = collections.defaultdict(list)
    for line in open(a.inventory, encoding="utf-8"):
        r = json.loads(line)
        g = group_of(r, a.group)
        if g:
            groups[g].append(r)
    pages, tsv = {}, ["group\tnodes\tsample\tpage\tnode\tkind\tlabel\tverdict"]
    for name in sorted(groups):
        pool = sorted(groups[name], key=lambda r: (r["page"], r["id"]))
        random.Random(zlib.crc32(name.encode("utf-8"))).shuffle(pool)
        pick = pool[:a.per_group]
        sheet = Image.new("RGB", (TILE * COLS, (TILE + 28) * ((len(pick) + COLS - 1) // COLS)), "white")
        draw = ImageDraw.Draw(sheet)
        for k, r in enumerate(pick):
            if r["page"] not in pages:
                pages[r["page"]] = rq.render_page(glob.glob(os.path.join(folder, "%s_*.pdf" % r["page"]))[0], SCALE)[0]
            x0, y0, x1, y1 = r["bbox"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            half = max(20, (x1 - x0) / 2 + 6, (y1 - y0) / 2 + 6)
            crop = pages[r["page"]].crop((int((cx - half) * SCALE), int((cy - half) * SCALE),
                                          int((cx + half) * SCALE), int((cy + half) * SCALE))).convert("RGB")
            ImageDraw.Draw(crop).rectangle([(x0 - cx + half) * SCALE, (y0 - cy + half) * SCALE,
                                            (x1 - cx + half) * SCALE, (y1 - cy + half) * SCALE], outline=(255, 0, 0), width=3)
            crop.thumbnail((TILE, TILE))
            x, y = (k % COLS) * TILE, (k // COLS) * (TILE + 28)
            sheet.paste(crop, (x, y + 28))
            draw.text((x + 2, y + 2), "%d %s %s %s" % (k, r["page"], r["id"].split("-")[-1], r["kind"]), fill=(0, 0, 200))
            draw.text((x + 2, y + 14), r["label"].replace("\n", " ")[:38], fill=(0, 0, 0))
            tsv.append("\t".join([name, str(len(pool)), str(k), r["page"], r["id"], r["kind"],
                                  r["label"].replace("\n", " / "), ""]))
        sheet.save(os.path.join(a.out, re.sub(r"[^A-Za-z0-9_+.-]+", "_", name) + ".png"))
        print(name, len(pool), len(pick))
    with open(os.path.join(a.out, "audit.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(tsv) + "\n")


if __name__ == "__main__":
    main()
