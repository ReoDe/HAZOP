"""사람이 이름 붙인 미분류 묶음으로 기호 사전 항목을 만들거나 견본을 더한다(기획서/PID-기호사전.md §6 4번).

  python scripts/symbols/add_symbols.py --set APR1400 --labels <라벨.csv> --meta <항목정보.csv>
         [--candidates <cluster_unclassified 결과 폴더>] [--library <사전 폴더>] [--template-parity odd]
         [--input-dir <도면 폴더>] [--per-entry 8] [--date 2026-11-09]

- 라벨.csv: `순위, id` (cluster_unclassified.py의 묶음.json 순위 → 사전 id). 같은 id에 여러 묶음을 붙여도 된다.
- 항목정보.csv: id, name_en, name_ko, category, role, kind, kind_from, attributes(JSON), text_inside, text_forbid,
  enabled, legend_ref, note. 새 항목을 만들 때만 읽는다. 이미 있는 항목은 사람이 고친 값을 그대로 둔다.
- 견본: 라벨 붙은 묶음 구성원 중 서로 다른 격자를 빈도순으로 --per-entry개. 이미 있는 견본과 같은 격자는 더하지 않는다.
  견본이 바뀐 항목만 revision을 올리고 updated를 --date로 바꾼다. 같은 입력으로 다시 돌리면 아무것도 바뀌지 않는다.
- 예시 그림: 새 항목이면 가장 흔한 격자의 첫 기호를 잘라 <묶음 폴더>/images/<이름>.png(긴 변 160px 이하)로.
"""

import argparse
import collections
import csv
import datetime
import json
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hazop import paths  # noqa: E402
from hazop.extract import symbols  # noqa: E402
import cluster_unclassified as cu  # noqa: E402

COMP_FIELDS = ("closed_curved", "closed_straight", "solid", "strokes", "markers", "dashes")


def comp_from_key(key):
    vals = [int(p[1:]) for p in key.split(".")]
    return {k: v for k, v in zip(COMP_FIELDS, vals) if v}


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def new_entry(meta, date):
    e = {"id": meta["id"], "revision": 0, "added": date, "updated": date,
         "name": {"en": meta["name_en"], "ko": meta["name_ko"]}, "category": meta["category"], "role": meta["role"],
         "kind": meta["kind"] or None}
    if meta.get("kind_from"):
        e["kind_from"] = meta["kind_from"]
    e["attributes"] = json.loads(meta["attributes"]) if meta.get("attributes") else {}
    e["enabled"] = meta.get("enabled", "true").strip().lower() != "false"
    text = {k: meta[f] for k, f in (("inside", "text_inside"), ("forbid_inside", "text_forbid")) if meta.get(f)}
    if text:
        e["text"] = text
    e["match"] = []
    e["sources"] = []
    if meta.get("legend_ref"):
        e["sources"].append({"set": meta.get("source_set", ""), "legend": meta["legend_ref"]})
    if meta.get("note"):
        e["note"] = meta["note"]
    return e


def template_from(group, max_distance, size_ratio):
    r = group[0]
    if r["zero"]:
        return {"shape": "zero_size"}
    shorts = sorted(m["size"][0] for m in group)
    longs = sorted(m["size"][1] for m in group)
    return {"shape": "grid", "composition": comp_from_key(r["key"]),
            "size_pt": [shorts[len(shorts) // 2], longs[len(longs) // 2]], "size_ratio": size_ratio,
            "rotations": "dihedral8", "max_distance": max_distance, "count": len(group), "grid": r["grid"]}


def size_bucket(long_side, ratio):
    """긴 변을 허용 비 단위로 나눈 칸. 같은 격자라도 칸이 다르면 다른 견본이다(6pt와 60pt를 하나로 묶지 않음)."""
    return 0 if long_side <= 0 else int(math.floor(math.log(long_side) / math.log(ratio)))


def canonical(grid):
    """회전·뒤집기 8가지 중 가장 작은 칸 목록. 같은 모양을 놓인 방향과 상관없이 한 묶음으로 센다."""
    cells = symbols.cells_of(grid)
    return min(tuple(sorted(f(r, c) for r, c in cells)) for _, f in symbols.TRANSFORMS)


def same_template(a, b):
    if a.get("shape", "grid") != b.get("shape", "grid"):
        return False
    if a.get("shape") == "zero_size":
        return True
    ratio = max(a.get("size_ratio", 1.25), b.get("size_ratio", 1.25))
    if a["composition"] != b["composition"] or not 1 / ratio <= a["size_pt"][1] / b["size_pt"][1] <= ratio:
        return False
    cells = symbols.cells_of(b["grid"])
    variants = {frozenset(f(r, c) for r, c in cells) for _, f in symbols.TRANSFORMS}
    return symbols.cells_of(a["grid"]) in variants  # 회전·뒤집기만 다른 격자는 같은 견본(회전 근거가 견본마다 달라지지 않게)


def crop(input_dir, r, dst):
    import pdfplumber
    with pdfplumber.open(os.path.join(input_dir, r["file"])) as pdf:
        pg = pdf.pages[0]
        x0, y0, x1, y1 = r["bbox"]
        box = (max(0, x0 - 6), max(0, y0 - 6), min(pg.width, x1 + 6), min(pg.height, y1 + 6))
        im = pg.crop(box).to_image(resolution=300).original.convert("RGB")
    im.thumbnail((160, 160))
    im.save(dst, optimize=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", default="APR1400")
    ap.add_argument("--labels", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--candidates")
    ap.add_argument("--library")
    ap.add_argument("--input-dir")
    ap.add_argument("--template-parity", choices=("all", "odd", "even"), default="all")
    ap.add_argument("--per-entry", type=int, default=8)
    ap.add_argument("--max-distance", type=float, default=0.8)
    ap.add_argument("--size-ratio", type=float, default=1.25)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--source-note", default="", help="sources에 남길 도면 묶음 이름(예: APR1400 DCD Rev.3)")
    a = ap.parse_args()
    cand = a.candidates or paths.folder("기호후보", a.set)
    root = a.library or paths.folder("기호")
    input_dir = a.input_dir or paths.folder("APR1400", "by-drawing")
    rows = {(r["seq"], r["i"]): r for r in cu.load_rows(os.path.join(cand, "쪽"))}
    clusters = {c["rank"]: c for c in read_json(os.path.join(cand, "묶음.json"))}
    meta = {m["id"]: dict(m, source_set=a.source_note) for m in read_csv(a.meta)}

    for eid in meta:
        if not symbols.ID_RE.match(eid):
            sys.exit("항목정보.csv의 id 형식 오류: %r" % eid)
    members = collections.defaultdict(list)
    for lab in read_csv(a.labels):
        if not lab.get("id"):
            continue
        if not symbols.ID_RE.match(lab["id"]):
            sys.exit("라벨 id 형식 오류(영문 소문자·숫자·_ 두 마디): %r" % lab["id"])
        for seq, i in clusters[int(lab["순위"])]["members"]:
            n = int(seq) if seq.isdigit() else 0
            if a.template_parity == "all" or (n % 2 == 1) == (a.template_parity == "odd"):
                members[lab["id"]].append(rows[(seq, i)])

    manifest = os.path.join(root, symbols.BUNDLES_FILE)
    os.makedirs(root, exist_ok=True)
    man = read_json(manifest) if os.path.isfile(manifest) else {"margin": 0.1, "bundles": []}
    changed = []
    for eid in sorted(members):
        prefix, name = eid.split(".", 1)
        bundle = next((b["name"] for b in man["bundles"] if (b.get("prefix") or b["name"].lower()) == prefix), None)
        if bundle is None:
            bundle = a.set if prefix == a.set.lower() else prefix
            man["bundles"].append({"name": bundle, "prefix": prefix, "active": True, "source": a.source_note})
        folder = symbols.bundle_dir(root, bundle, prefix)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name + ".json")
        if os.path.isfile(path):
            entry = read_json(path)
        else:
            if eid not in meta:
                sys.exit("항목정보.csv에 %s가 없음" % eid)
            entry = new_entry(meta[eid], a.date)
        groups = collections.OrderedDict()
        for r in sorted(members[eid], key=lambda r: (r["seq"], r["i"])):
            groups.setdefault((r["key"], canonical(r["grid"]), r["zero"], size_bucket(r["size"][1], a.size_ratio)),
                              []).append(r)
        ranked = sorted(groups.values(), key=lambda g: (-len(g), g[0]["seq"], g[0]["i"]))
        added = 0
        for g in ranked[:a.per_entry]:
            t = template_from(g, a.max_distance, a.size_ratio)
            if not any(same_template(t, old) for old in entry["match"]):
                entry["match"].append(t)
                added += 1
        if added:
            entry["revision"] += 1
            entry["updated"] = a.date
            pages = sorted({r["seq"] for r in members[eid]})
            entry["sources"] = [s for s in entry["sources"] if "pages" not in s] + [
                {"set": a.source_note, "pages": pages, "symbols": len(members[eid]), "template_parity": a.template_parity}]
            img_dir = os.path.join(folder, symbols.IMAGE_DIR)
            img = os.path.join(img_dir, name + ".png")
            if not os.path.isfile(img) and ranked and not ranked[0][0]["zero"]:
                os.makedirs(img_dir, exist_ok=True)
                crop(input_dir, ranked[0][0], img)
            if os.path.isfile(img):
                entry["image"] = "%s/%s.png" % (symbols.IMAGE_DIR, name)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(entry, f, ensure_ascii=False, indent=1)
                f.write("\n")
            changed.append((eid, added, len(entry["match"])))
    with open(manifest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
        f.write("\n")
    for eid, added, total in changed:
        print("%s: 견본 +%d (모두 %d)" % (eid, added, total))
    print("바뀐 항목 %d" % len(changed))


if __name__ == "__main__":
    main()
