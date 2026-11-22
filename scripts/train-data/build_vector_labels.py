"""벡터 PDF 쪽에서 학습용 기호 정답을 반자동으로 만든다((나) 길): 상자는 추출기, 종류는 AI가 그림 조각을 보고.

  python scripts/train-data/build_vector_labels.py <출력 폴더> --pages 12,63 [--model claude-opus-5-5] [--effort medium]
      [--workers 3] [--per-sheet 20] [--no-missed]

1. 추출기(pdf_vector.extract)의 기호 후보(분기점 tee 제외)마다 상자와 둘레를 쪽 그림에서 잘라 빨간 상자를 그린다.
2. 조각 20개를 한 장에 모아(번호 붙임) 구독 AI에 한 번 묻는다: 종류(작성 규칙의 종류 또는 not_symbol), 이름표,
   상자가 기호 하나를 덮는지. 스크립트가 정한 종류는 AI에 알려 주지 않는다(따로 견주려고).
3. 놓친 기호 찾기: 쪽을 3×3 조각으로 나눠, 받아들인 상자를 초록으로 그린 그림을 보이고 상자 없는 기호를 pt 격자로 받는다.
   받은 상자는 그 안의 벡터 원소(선·곡선·사각형) 묶음으로 맞춘다(snap).
4. 결과: <출력>/<쪽>/labels.json(정답지 형식 + 출처 칸), symbols.coco.json, calls.jsonl(호출마다 시간·토큰).

AI 답은 answers/ 아래에 저장하고, 같은 그림 묶음으로 다시 돌리면 다시 묻지 않는다(호출 수를 아끼려고).
정답지(tests/fixtures/read-quality/)는 이 스크립트가 읽지 않는다. 견주기는 compare_vector_labels.py가 따로 한다.
"""

import argparse
import concurrent.futures as cfut
import glob
import hashlib
import json
import math
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import coco_format as cf  # noqa: E402

sys.path.insert(0, os.path.join(cf.REPO_ROOT, "scripts"))

SCALE = 5.0          # 조각을 자를 쪽 그림 배율(px/pt, 360dpi)
CELL = 300           # 조각 칸 크기(px)
COLS = 5
MISSED_GRID = (3, 3)
MISSED_SCALE = 3.4
BORDER = (18.0, 18.0, 1206.0, 774.0)   # APR1400 쪽 테두리 안(1224×792pt)

KIND_GUIDE = """Kinds (choose one; use "unlisted" with kind_text if none fits; "not_symbol" if the red box is not a P&ID symbol):
- Equipment: reactor_vessel, steam_generator, pressurizer, pump, vessel, tank, heat_exchanger, turbine, condenser, filter,
  demineralizer, compressor, fan, accumulator, chiller, electric_heater, silencer
- Valves: manual_valve (gate/globe/ball/butterfly/plug/needle with no actuator), motor_operated_valve (M actuator),
  air_operated_valve (diaphragm/air actuator, not for modulation), control_valve (modulating), solenoid_valve (S actuator),
  check_valve, damper (HVAC), relief_valve (safety/relief valve), rupture_disc, isolation_valve
- Piping parts: orifice, vent, drain, strainer, test_connection, reducer, flow_element, blind_flange, pipe_cap, nozzle, sparger,
  slip_joint, expansion_joint, flexible_hose, hose_connection, sight_glass, flame_arrestor, sample_probe, diaphragm_seal,
  air_flow_arrow, continuation (off-sheet connector arrow/pentagon)
- Instruments (by the function letters in the bubble): transmitter (..T: PT FT LT TT PDT AT), temperature_element (TE, TEW),
  flow_element (FE), level_element (LE), indicator (..I: PI TI FI LI PDI LTI), controller (..C, ..IC), switch (..S, ..SH, ..SL,
  ZS, HS), recorder (..R), alarm (..A), pilot_light
Circles or ovals holding only a number (e.g. 418, 021) and tied to a valve by a short leader line are valve tag bubbles,
not symbols: answer not_symbol for them, and when the red box is that valve, read the bubble number as the valve tag.
If the red box covers only a piece of a symbol (one half of a valve body, the S or M box of an actuator, an actuator top),
give the kind of the whole symbol and set box to part_of_symbol.
Not symbols: tees, elbows, line crossings, flanges, quality-group/safety-class boundary diamonds (e.g. "CI|DII"), same-sheet
connection flags, notes, title-block text, plain text labels, pipe line numbers."""

CELL_SYSTEM = """You label symbols on a nuclear plant P&ID (APR1400 DCD, public document) to build training data for a
symbol detector. Each numbered cell shows one candidate region outlined by a RED box, with some surrounding context.
For every cell decide what the red box contains. Read the tag printed next to or inside the symbol (valve number such as
V1143 or 021, instrument function letters + loop number such as "FT 073C", equipment tag such as PP01A); null if none.
""" + KIND_GUIDE + """
box: "ok" if the red box tightly covers exactly one whole symbol; "covers_several" if it covers two or more symbols;
"part_of_symbol" if it covers only a piece of a symbol; "not_a_symbol" if kind is not_symbol.
Answer every cell number exactly once. Be terse in kind_text and note."""

MISSED_SYSTEM = """You check symbol annotations on a nuclear plant P&ID tile (APR1400 DCD, public document). GREEN boxes are
symbols already annotated. A pt grid is drawn: thin lines every 10pt, red lines with numbers every 50pt (x along the top,
y along the left). Find every P&ID symbol in the tile that has NO green box (or only a green box covering a different
symbol) and give its bounding box in page pt [x0, y0, x1, y1] read from the grid, within about 3pt.
""" + KIND_GUIDE + """
Ignore anything already in a green box, title block, notes, text-only labels, line numbers. If nothing is missing return
an empty list."""


def cell_schema():
    return {"type": "object", "additionalProperties": False, "required": ["cells"],
            "properties": {"cells": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["n", "kind", "tag", "box", "confidence"],
                "properties": {"n": {"type": "integer"}, "kind": {"type": "string", "enum": cf.KINDS + ["not_symbol"]},
                               "kind_text": {"type": "string"}, "tag": {"type": ["string", "null"]},
                               "box": {"type": "string", "enum": ["ok", "covers_several", "part_of_symbol", "not_a_symbol"]},
                               "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                               "note": {"type": "string"}}}}}}


def missed_schema():
    return {"type": "object", "additionalProperties": False, "required": ["missing"],
            "properties": {"missing": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["kind", "bbox", "tag"],
                "properties": {"kind": {"type": "string", "enum": cf.KINDS},
                               "kind_text": {"type": "string"},
                               "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                               "tag": {"type": ["string", "null"]}, "note": {"type": "string"}}}}}}


def node_box(n):
    g = n.get("geometry") or {}
    if "x" not in g:
        return None
    x0, y0, w, h = g["x"], g["y"], g.get("width") or 0, g.get("height") or 0
    if w < 3:
        x0, w = x0 + w / 2 - 1.5, 3
    if h < 3:
        y0, h = y0 + h / 2 - 1.5, 3
    return [x0, y0, x0 + w, y0 + h]


def make_sheets(page_img, cands, out_dir, per_sheet):
    from PIL import Image, ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    sheets = []
    for start in range(0, len(cands), per_sheet):
        chunk = cands[start:start + per_sheet]
        rows = math.ceil(len(chunk) / COLS)
        sheet = Image.new("RGB", (COLS * (CELL + 8), rows * (CELL + 28)), "white")
        d = ImageDraw.Draw(sheet)
        for i, c in enumerate(chunk):
            b = c["box"]
            pad = max(14.0, 0.6 * max(b[2] - b[0], b[3] - b[1]))
            box = [max(0, b[0] - pad), max(0, b[1] - pad), b[2] + pad, b[3] + pad]
            crop = page_img.crop(tuple(int(v * SCALE) for v in box)).convert("RGB")
            cd = ImageDraw.Draw(crop)
            cd.rectangle([(b[0] - box[0]) * SCALE - 2, (b[1] - box[1]) * SCALE - 2,
                          (b[2] - box[0]) * SCALE + 2, (b[3] - box[1]) * SCALE + 2], outline=(230, 0, 0), width=3)
            crop.thumbnail((CELL, CELL))
            cx, cy = (i % COLS) * (CELL + 8), (i // COLS) * (CELL + 28)
            d.rectangle([cx, cy, cx + CELL + 6, cy + CELL + 26], outline=(120, 120, 120))
            d.text((cx + 4, cy + 4), "#%d" % (start + i + 1), fill=(0, 0, 200))
            sheet.paste(crop, (cx + 3, cy + 22))
            c["n"] = start + i + 1
        path = os.path.join(out_dir, "sheet-%02d.png" % (len(sheets) + 1))
        sheet.save(path)
        sheets.append((path, chunk))
    return sheets


def missed_tiles(page_img, accepted, out_dir):
    import check_read_quality as crq
    from PIL import ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    x0, y0, x1, y1 = BORDER
    nx, ny = MISSED_GRID
    tw, th = (x1 - x0) / nx + 20, (y1 - y0) / ny + 20
    tiles = []
    for j in range(ny):
        for i in range(nx):
            tx, ty = x0 + i * (x1 - x0) / nx - 10, y0 + j * (y1 - y0) / ny - 10
            area = [max(0, tx), max(0, ty), min(1224, tx + tw), min(792, ty + th)]
            im = page_img.crop(tuple(int(v * SCALE) for v in area)).convert("RGB")
            im = im.resize((int((area[2] - area[0]) * MISSED_SCALE), int((area[3] - area[1]) * MISSED_SCALE)))
            d = ImageDraw.Draw(im)
            crq._grid(im, (area[0], area[1]), MISSED_SCALE)
            for s in accepted:
                b = s["bbox"]
                if b[2] < area[0] or b[0] > area[2] or b[3] < area[1] or b[1] > area[3]:
                    continue
                d.rectangle([(b[0] - area[0]) * MISSED_SCALE - 2, (b[1] - area[1]) * MISSED_SCALE - 2,
                             (b[2] - area[0]) * MISSED_SCALE + 2, (b[3] - area[1]) * MISSED_SCALE + 2],
                            outline=(0, 170, 0), width=3)
            path = os.path.join(out_dir, "tile-%d%d.png" % (j, i))
            im.save(path)
            tiles.append((path, area))
    return tiles


def snap(box, objs):
    """AI가 격자로 읽은 상자를 그 안의 벡터 원소 묶음 상자로 맞춘다. 맞출 원소가 없거나 크기가 크게 어긋나면 그대로."""
    pad = 3.0
    inside = [o for o in objs if o[0] >= box[0] - pad and o[1] >= box[1] - pad and o[2] <= box[2] + pad and o[3] <= box[3] + pad
              and (o[2] - o[0]) < 1.6 * (box[2] - box[0]) + 2 and (o[3] - o[1]) < 1.6 * (box[3] - box[1]) + 2]
    if not inside:
        return box, False
    u = [min(o[0] for o in inside), min(o[1] for o in inside), max(o[2] for o in inside), max(o[3] for o in inside)]
    area = lambda b: max(b[2] - b[0], 1) * max(b[3] - b[1], 1)  # noqa: E731
    if 0.3 <= area(u) / area(box) <= 2.5:
        return [round(v, 1) for v in u], True
    return box, False


def merge_parts(symbols, reach=15.0):
    """추출기가 한 기호를 몸통 반쪽·S 상자·구동부로 쪼개 낸 후보를 합친다. AI가 조각(part_of_symbol)이라 한 후보를
    가운데 거리 reach pt 안에서 AI 종류가 같은 가장 가까운 후보 하나에 붙인다(온전한 상자 'ok' 후보를 먼저 고름). 온전한 후보끼리는
    합치지 않는다. 종류는 묶음에서 온전한 후보의 AI 답(없으면 가장 큰 후보), 태그는 처음 나온 것."""
    def kind(s):
        k = s.get("ai_kind")
        return cf.canonical(k) if k and k != "not_symbol" else s["kind"]

    def center(b):
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    parent = list(range(len(symbols)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(symbols):
        if a.get("ai_box") != "part_of_symbol":
            continue
        near = [(b.get("ai_box") != "ok", math.dist(center(a["bbox"]), center(b["bbox"])), j)
                for j, b in enumerate(symbols) if j != i and kind(b) == kind(a)]
        near = [t for t in near if t[1] <= reach]
        if near:
            parent[find(i)] = find(min(near)[2])
    groups = {}
    for i in range(len(symbols)):
        groups.setdefault(find(i), []).append(symbols[i])
    out = []
    for g in groups.values():
        box = [min(s["bbox"][0] for s in g), min(s["bbox"][1] for s in g),
               max(s["bbox"][2] for s in g), max(s["bbox"][3] for s in g)]
        head = max(g, key=lambda s: (s.get("ai_box") == "ok", (s["bbox"][2] - s["bbox"][0]) * (s["bbox"][3] - s["bbox"][1])))
        out.append(dict(head, id="g%03d" % (len(out) + 1), kind=kind(head), bbox=[round(v, 1) for v in box],
                        tag=next((s["tag"] for s in g if s.get("tag")), None), parts=len(g),
                        candidate=head["candidate"]))
    return out


def vector_objects(pdf):
    import pdfplumber
    with pdfplumber.open(pdf) as doc:
        pg = doc.pages[0]
        objs = []
        for o in pg.curves + pg.rects + pg.lines:
            b = (float(o["x0"]), float(o["top"]), float(o["x1"]), float(o["bottom"]))
            if (b[2] - b[0]) < 80 and (b[3] - b[1]) < 80:   # 긴 배관 선은 기호 상자 맞춤에 쓰지 않는다
                objs.append(b)
    return objs


class Caller:
    def __init__(self, client, log_path, cache_dir):
        self.client, self.log_path, self.cache_dir = client, log_path, cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def __call__(self, label, system, text, pngs, schema):
        h = hashlib.sha256()
        for p in pngs:
            with open(p, "rb") as fh:
                h.update(fh.read())
        h.update((system + text + self.client.model + self.client.effort).encode("utf-8"))
        cache = os.path.join(self.cache_dir, "%s-%s.json" % (label, h.hexdigest()[:12]))
        if os.path.isfile(cache):
            with open(cache, encoding="utf-8") as fh:
                return json.load(fh)["output"]
        res, dt = self.client.ask(system, text, pngs, schema)
        rec = {"label": label, "seconds": round(dt, 1), "status": res["status"], "error": res["error"],
               "usage": res["usage"], "model": res["model"], "billing": res["billing"]}
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if res["status"] != "completed":
            print("  호출 실패 %s: %s" % (label, res["error"]))
            return None
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump({"output": res["output"], "call": rec}, fh, ensure_ascii=False, indent=1)
        return res["output"]


def label_page(pdf, name, out_dir, caller, per_sheet, workers, do_missed):
    import check_read_quality as crq
    from hazop.extract.adapters import pdf_vector
    work = tempfile.mkdtemp(prefix="hazop-train-vec-")
    os.environ["HAZOP_WORK_ROOT"] = work
    t0 = time.time()
    ex = pdf_vector.extract(pdf, page=0, repo_root=work)
    page_img, _ = crq.render_page(pdf, SCALE)
    page_img = page_img.convert("L")
    cands = [{"local_id": n["local_id"], "box": node_box(n), "script_kind": n.get("kind"), "script_tag": n.get("tag")}
             for n in ex["nodes"] if n.get("kind") != "tee" and node_box(n)]
    sheets = make_sheets(page_img, cands, os.path.join(out_dir, "sheets"), per_sheet)
    t_prep = time.time() - t0
    prompt = ("There are %d cells on this sheet, numbered #%d to #%d. Return one entry per cell.")
    with cfut.ThreadPoolExecutor(workers) as pool:
        futs = {pool.submit(caller, "%s-cells-%02d" % (name, i + 1), CELL_SYSTEM,
                            prompt % (len(chunk), chunk[0]["n"], chunk[-1]["n"]), [path], cell_schema()): chunk
                for i, (path, chunk) in enumerate(sheets)}
        for f in cfut.as_completed(futs):
            out = f.result() or {"cells": []}
            by_n = {c["n"]: c for c in out["cells"]}
            for c in futs[f]:
                c["ai"] = by_n.get(c["n"])
    symbols = []
    for c in cands:
        ai = c.get("ai") or {}
        ai_kind = ai.get("kind")
        if c["script_kind"]:
            kind, src = c["script_kind"], "script"
        elif ai_kind and ai_kind != "not_symbol":
            kind, src = ai_kind, "ai"
        else:
            continue
        symbols.append({"id": "s%03d" % (len(symbols) + 1), "kind": cf.canonical(kind), "bbox": [round(v, 1) for v in c["box"]],
                        "tag": c["script_tag"] or ai.get("tag"), "attributes": {}, "source": src,
                        "script_kind": c["script_kind"], "ai_kind": ai_kind, "ai_box": ai.get("box"),
                        "ai_confidence": ai.get("confidence"), "kind_text": ai.get("kind_text"), "candidate": c["local_id"]})
    missed = []
    if do_missed:
        tiles = missed_tiles(page_img, symbols, os.path.join(out_dir, "missed-tiles"))
        objs = vector_objects(pdf)
        with cfut.ThreadPoolExecutor(workers) as pool:
            futs = {pool.submit(caller, "%s-missed-%d" % (name, k), MISSED_SYSTEM,
                                "Tile covers page pt x %.0f..%.0f, y %.0f..%.0f. List symbols without a green box."
                                % tuple(area), [path], missed_schema()): area
                    for k, (path, area) in enumerate(tiles)}
            for f in cfut.as_completed(futs):
                for m in (f.result() or {"missing": []})["missing"]:
                    b = sorted(m["bbox"][::2]) + sorted(m["bbox"][1::2])
                    b = [b[0], b[2], b[1], b[3]]
                    if b[2] - b[0] < 1 or b[3] - b[1] < 1:
                        continue
                    if any(math.dist(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2),
                                     ((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2)) < 6
                           for s in symbols + missed):
                        continue
                    sb, snapped = snap(b, objs)
                    missed.append({"id": "m%03d" % (len(missed) + 1), "kind": cf.canonical(m["kind"]), "bbox": sb,
                                   "ai_bbox": [round(v, 1) for v in b], "snapped": snapped, "tag": m.get("tag"),
                                   "attributes": {}, "source": "ai_missed", "kind_text": m.get("kind_text")})
    doc = {"schema": "hazop_train_labels", "version": 1, "drawing": name, "source_file": os.path.basename(pdf),
           "page_size": [1224.0, 792.0], "method": "벡터 후보 상자 + AI 종류(조각 %d개/장), 놓친 기호 %s" % (
               per_sheet, "3x3 조각" if do_missed else "안 찾음"),
           "candidates": len(cands), "sheets": len(sheets), "prep_seconds": round(t_prep, 1),
           "symbols": symbols, "missed": missed,
           "rejected": [{"candidate": c["local_id"], "bbox": [round(v, 1) for v in c["box"]], "ai": c.get("ai")}
                        for c in cands if not c["script_kind"] and (c.get("ai") or {}).get("kind") in (None, "not_symbol")],
           "script_kept_ai": [{"candidate": c["local_id"], "script_kind": c["script_kind"], "ai": c.get("ai")}
                              for c in cands if c["script_kind"]]}
    cf.save(doc, os.path.join(out_dir, "labels.json"))
    # 학습 자료는 권장 정책(설계 문서 §2.1): 모든 후보에 AI 종류, 조각 합치기, 놓친 기호 찾기 결과는 넣지 않음.
    # 스크립트와 AI가 같은 종류이거나 스크립트 종류 없이 AI 확신이 high면 그대로 받고, 나머지는 사람 확인 표시
    final = merge_parts([dict(s, kind=cf.canonical(s["ai_kind"])) if s.get("ai_kind") else s
                         for s in symbols if s.get("ai_kind") != "not_symbol"])
    ds = cf.dataset("APR1400 %s 벡터 후보 + AI 종류" % name)
    png = "page.png"
    page_img.resize((int(1224 * 200 / 72), int(792 * 200 / 72))).save(os.path.join(out_dir, png))
    iid = cf.add_image(ds, png, int(1224 * 200 / 72), int(792 * 200 / 72), source="apr1400-vector-ai", drawing=name, dpi=200)
    for s in final:
        sk = s.get("script_kind")
        agree = sk is not None and cf.canonical(sk) == s["kind"]
        review = not (agree or (sk is None and s.get("ai_confidence") == "high"))
        cf.add_box(ds, iid, cf.CATEGORY_ID.get(s["kind"], cf.CATEGORY_ID["unlisted"]), s["bbox"], 200 / 72.0,
                   attributes={"tag": s.get("tag"), "label_source": "script+ai" if agree else "ai",
                               "needs_review": review, "parts": s.get("parts", 1)})
    cf.save(ds, os.path.join(out_dir, "symbols.coco.json"))
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--pages", required=True, help="APR1400 순번, 쉼표로(예: 12,63)")
    ap.add_argument("--input", default=cf.paths.folder("APR1400", "by-drawing"))
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--per-sheet", type=int, default=20)
    ap.add_argument("--no-missed", action="store_true")
    ap.add_argument("--missed-from", help="놓친 기호를 다시 묻지 않고 이 폴더(<쪽>/labels.json)의 결과를 씀")
    a = ap.parse_args()
    from vision_client import VisionClient
    client = VisionClient(model=a.model, effort=a.effort, timeout=900)
    caller = Caller(client, os.path.join(a.out, "calls.jsonl"), os.path.join(a.out, "answers"))
    for seq in [int(s) for s in a.pages.split(",")]:
        pdf = glob.glob(os.path.join(a.input, "%03d_*.pdf" % seq))[0]
        name = "apr1400-%03d" % seq
        t0 = time.time()
        doc = label_page(pdf, name, os.path.join(a.out, name), caller, a.per_sheet, a.workers,
                         not (a.no_missed or a.missed_from))
        if a.missed_from:
            with open(os.path.join(a.missed_from, name, "labels.json"), encoding="utf-8") as fh:
                doc["missed"] = json.load(fh)["missed"]
            doc["method"] += ", 놓친 기호는 %s 결과를 씀" % a.missed_from
            cf.save(doc, os.path.join(a.out, name, "labels.json"))
        print("%s: 후보 %d, 조각 장 %d, 기호 %d(스크립트 %d, AI %d), 놓친 기호 %d, %.0f초" % (
            name, doc["candidates"], doc["sheets"], len(doc["symbols"]),
            sum(s["source"] == "script" for s in doc["symbols"]), sum(s["source"] == "ai" for s in doc["symbols"]),
            len(doc["missed"]), time.time() - t0))


if __name__ == "__main__":
    main()
