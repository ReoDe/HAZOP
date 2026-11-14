"""기호 사전 그림(resources/library/drawing-symbols)으로 가상 P&ID 쪽을 무작위로 그리고 정답을 함께 쓴다.

  python scripts/train-data/build_synthetic_pages.py <출력 폴더> [--pages 20] [--seed 20261114] [--dpi 200]

쪽 하나 = 가로 배관 몇 줄 + 줄 위의 2포트 기호 + 세로 가지(끝 부속·도면 밖 연결) + 신호선으로 붙은 계기 원 + 이름표·배관 글자
+ 표제란. 정답(기호 상자·종류·태그, 글자 상자, 기호 쌍 연결)은 그리면서 함께 적으므로 100% 맞다. 모양은 실제 도면과 다르다
(선 굵기·글꼴·기호 그림이 한 벌뿐). 쪽의 절반은 흐림과 잡음을 더해 스캔처럼 만든다.
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import coco_format as cf  # noqa: E402

PAGE_W, PAGE_H = 1224.0, 792.0
SYMBOL_DIR = cf.paths.folder("drawing-symbols")
INLINE = ["manual_valve", "manual_valve", "manual_valve", "isolation_valve", "check_valve", "check_valve",
          "reducer", "orifice", "control_valve", "motor_operated_valve", "motor_operated_valve", "damper"]
TERMINAL = ["vent", "drain", "test_connection", "pipe_cap", "continuation", "psv"]
EQUIPMENT = ["tank", "heat_exchanger", "filter", "demineralizer", "pump", "pump"]
INSTRUMENT = {"transmitter": ["PT", "FT", "LT", "TT", "PDT"], "indicator": ["PI", "TI", "FI", "LI"],
              "controller": ["PIC", "FIC", "LIC"], "temperature_element": ["TE", "TEW"]}
SYSTEMS = ["CV", "SI", "CC", "RC", "AF", "MS", "FW", "WD", "SC", "EW"]


def load_symbols():
    with open(os.path.join(SYMBOL_DIR, "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    out = {}
    for s in man["symbols"]:
        if not s.get("file"):
            continue
        path = os.path.join(SYMBOL_DIR, s["file"])
        with open(path, encoding="utf-8") as fh:
            vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', fh.read()).group(1).split()]
        out[s["kind"]] = dict(s, path=path, vw=vb[2], vh=vb[3])
    return out


class Page:
    """한 쪽의 정답. 좌표는 모두 도면 pt."""

    def __init__(self):
        self.symbols = []      # {"id", "kind", "box", "tag"}
        self.texts = []        # {"box", "text"}
        self.edges = []        # (노드 a, 노드 b) 배관으로 바로 이어진 두 노드(기호 id 또는 "t<n>" 분기점)
        self.pipes = []        # [(x, y), ...]
        self.signals = []
        self.busy = []

    def free(self, box, pad=3.0):
        return all(box[2] + pad < b[0] or b[2] + pad < box[0] or box[3] + pad < b[1] or b[3] + pad < box[1]
                   for b in self.busy) and 30 < box[0] and box[2] < PAGE_W - 30 and 30 < box[1] and box[3] < PAGE_H - 30

    def symbol_pairs(self):
        """분기점을 지나 사이에 다른 기호 없이 닿는 기호 쌍(정답지 규칙과 같음)."""
        adj = {}
        for a, b in self.edges:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        pairs = set()
        for s in self.symbols:
            seen, stack = {s["id"]}, [s["id"]]
            while stack:
                for n in adj.get(stack.pop(), ()):
                    if n in seen:
                        continue
                    seen.add(n)
                    if n.startswith("t"):
                        stack.append(n)
                    else:
                        pairs.add(tuple(sorted((s["id"], n))))
        return sorted(pairs)


def layout(rng, lib):
    """무작위 배치. → Page(그리기 명령은 Page 안의 symbols·texts·pipes·signals로 충분하다)."""
    pg = Page()
    title = [880.0, 690.0, 1190.0, 770.0]
    pg.busy.append(title)
    for i, (k, v) in enumerate((("TITLE", "SYNTHETIC P&ID %04d" % rng.randint(0, 9999)), ("DWG NO.", "SYN-%03d" % rng.randint(1, 999)),
                                ("REV.", str(rng.randint(0, 3))))):
        pg.texts.append({"text": k, "at": (title[0] + 6, title[1] + 8 + 22 * i), "size": 7.0, "frame": title})
        pg.texts.append({"text": v, "at": (title[0] + 80, title[1] + 8 + 22 * i), "size": 7.0})
    sys_code = rng.choice(SYSTEMS)
    n_tee = [0]
    vsize = rng.uniform(0.8, 1.6)  # 쪽마다 기호 크기 배율(실제 도면은 쪽마다 기호 크기가 다르다)

    def add_symbol(kind, cx, cy, w, h, rot=0, tag=None):
        box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2] if rot % 180 == 0 else [cx - h / 2, cy - w / 2, cx + h / 2, cy + w / 2]
        if not pg.free(box):
            return None
        sid = "s%03d" % (len(pg.symbols) + 1)
        pg.symbols.append({"id": sid, "kind": kind, "box": box, "rot": rot, "tag": tag, "w": w, "h": h, "c": (cx, cy)})
        pg.busy.append(box)
        return sid

    def add_text(text, x, y, size, anchor="lt", check=False):
        w = 0.62 * size * len(text)
        box = [x - w / 2, y - size / 2, x + w / 2, y + size / 2] if anchor == "c" else [x, y, x + w, y + size]
        if check and not pg.free(box, pad=1.0):
            return False
        pg.texts.append({"text": text, "at": (x, y), "size": size, "anchor": anchor})
        if anchor != "c":
            pg.busy.append(box)
        return True

    def tee():
        n_tee[0] += 1
        return "t%d" % n_tee[0]

    rows = sorted(rng.sample(range(110, 640, 45), rng.randint(3, 6)))
    for y in rows:
        x0, x1 = rng.uniform(60, 240), rng.uniform(640, 860)
        # 왼쪽 끝: 설비 또는 도면 밖 연결
        chain = []
        left_kind = rng.choice(EQUIPMENT + ["continuation", "continuation"])
        if left_kind == "continuation":
            w, h = 52 * vsize, 16 * vsize
            sid = add_symbol("continuation", x0 - w / 2, y, w, h)
            if sid:
                add_text("FROM %s-%d" % (rng.choice(SYSTEMS), rng.randint(100, 999)), x0 - w + 3, y - 3, 4.5 * vsize)
        else:
            w = (rng.uniform(22, 30) if left_kind == "pump" else rng.uniform(40, 80)) * vsize
            h = w if left_kind == "pump" else w * rng.uniform(0.6, 1.4)
            sid = add_symbol(left_kind, x0 - w / 2, y, w, h)
            if sid:
                tag = "%s%02d%s" % ({"tank": "TK", "pump": "PP", "heat_exchanger": "HE", "filter": "FT", "demineralizer": "IX"}[left_kind],
                                     rng.randint(1, 9), rng.choice(["", "A", "B"]))
                pg.symbols[-1]["tag"] = tag
                add_text(tag, x0 - w / 2 - 10, y + h / 2 + 4, 5.5 * vsize)
        if sid:
            chain.append((sid, x0))
        x = x0 + rng.uniform(25, 50)
        while x < x1 - 40:
            r = rng.random()
            if r < 0.55:
                kind = rng.choice(INLINE)
                spec = lib[kind]
                w = rng.uniform(11, 16) * vsize
                h = w * spec["vh"] / spec["vw"]
                port_y = spec["ports"][0]["y"] / spec["vh"] * h
                cy = y - port_y + h / 2
                tag = "V%d" % rng.randint(100, 9999) if "valve" in kind else None
                sid = add_symbol(kind, x + w / 2, cy, w, h, tag=tag)
                if sid:
                    chain.append((sid, x))
                    if tag:
                        add_text(tag, x - 2, cy + h / 2 + 2, 4.5 * vsize)
                    if "valve" in kind and rng.random() < 0.3:
                        add_text(rng.choice(["LO", "LC", "NO", "NC"]), x + w + 2, cy - h / 2 - 6, 4.0 * vsize)
                x += w + rng.uniform(25, 70)
            elif r < 0.8:
                # 아래위로 가지: 분기점 + (가운데 2포트 기호) + 끝 부속. 가지 선이 남의 기호를 지나거나 끝 부속을
                # 놓지 못하면 가지 전체를 되돌린다(끝이 빈 배관이 정답에 없는 모양으로 남지 않게)
                sign = rng.choice([-1, 1])
                room = min([abs(r - y) for r in rows if (r - y) * sign > 0] + [y - 40 if sign < 0 else 680 - y]) - 22
                if room < 25:
                    x += rng.uniform(15, 30)
                    continue
                L = rng.uniform(25, min(110, room))
                end_y = y + sign * L
                lane = [x - 2, min(y, end_y) + (4 if sign < 0 else 4), x + 2, max(y, end_y)]
                if not pg.free(lane, pad=1.0):
                    x += rng.uniform(15, 30)
                    continue
                mark = (len(pg.symbols), len(pg.busy), len(pg.texts), len(pg.edges))
                t = tee()
                prev = t
                pts = [(x, y)]
                if rng.random() < 0.5:
                    kind = rng.choice(["manual_valve", "manual_valve", "check_valve", "orifice"])
                    spec = lib[kind]
                    w = rng.uniform(10, 14) * vsize
                    h = w * spec["vh"] / spec["vw"]
                    cy = y + sign * L / 2
                    tag = "V%d" % rng.randint(100, 9999) if "valve" in kind else None
                    sid = add_symbol(kind, x, cy, w, h, rot=90, tag=tag)
                    if sid:
                        pg.edges.append((prev, sid))
                        prev = sid
                        if tag:
                            add_text(tag, x + h / 2 + 3, cy - 2, 4.5 * vsize)
                kind = rng.choice(TERMINAL if sign < 0 else [k for k in TERMINAL if k != "psv"])
                spec = lib[kind]
                if kind == "continuation":
                    w, h = 46 * vsize, 14 * vsize
                    sid = add_symbol(kind, x, end_y + sign * w / 2, w, h, rot=90)
                elif kind == "psv":
                    w = h = rng.uniform(14, 20) * vsize
                    sid = add_symbol(kind, x + w * 0.0, end_y + sign * h / 2, w, h, tag="V%d" % rng.randint(100, 9999))
                    if sid:
                        add_text(pg.symbols[-1]["tag"], x + w / 2 + 3, end_y + sign * h / 2, 4.5 * vsize)
                else:
                    w = rng.uniform(9, 13) * vsize
                    h = w * spec["vh"] / spec["vw"]
                    sid = add_symbol(kind, x, end_y + sign * w / 2, w, h, rot=90 if sign > 0 else 270)
                if sid:
                    pg.edges.append((prev, sid))
                    chain.append((t, x))
                    pts.append((x, end_y))
                    pg.pipes.append(pts)
                    pg.busy.append(lane)
                else:
                    del pg.symbols[mark[0]:], pg.busy[mark[1]:], pg.texts[mark[2]:], pg.edges[mark[3]:]
                x += rng.uniform(30, 60)
            else:
                # 계기 원: 배관 위아래에 두고 점선 신호선으로 잇는다(배관 연결이 아님)
                kind = rng.choice(list(INSTRUMENT))
                d = rng.uniform(13, 18) * vsize
                sign = rng.choice([-1, 1])
                cy = y + sign * rng.uniform(28, 45)
                letters = rng.choice(INSTRUMENT[kind])
                num = "%d%s" % (rng.randint(100, 999), rng.choice(["", "", "A", "B"]))
                sid = add_symbol(kind, x, cy, d, d, tag="%s %s" % (letters, num))
                if sid:
                    pg.signals.append([(x, y), (x, cy - sign * d / 2)])
                    add_text(letters, x, cy - d * 0.18, 3.6 * vsize, anchor="c")
                    add_text(num, x, cy + d * 0.18, 3.6 * vsize, anchor="c")
                x += rng.uniform(25, 50)
        right_kind = rng.choice(EQUIPMENT + ["continuation", "continuation", "continuation"])
        end = max(x, x1)
        if right_kind == "continuation":
            w, h = 52 * vsize, 16 * vsize
            sid = add_symbol("continuation", end + w / 2, y, w, h)
            if sid:
                add_text("TO %s-%d" % (rng.choice(SYSTEMS), rng.randint(100, 999)), end + 3, y - 3, 4.5 * vsize)
        else:
            w = (rng.uniform(22, 30) if right_kind == "pump" else rng.uniform(40, 80)) * vsize
            h = w if right_kind == "pump" else w * rng.uniform(0.6, 1.4)
            sid = add_symbol(right_kind, end + w / 2, y, w, h)
        if sid:
            chain.append((sid, end))
        for (a, _), (b, _) in zip(chain, chain[1:]):
            pg.edges.append((a, b))
        if chain:
            pg.pipes.append([(chain[0][1], y), (chain[-1][1], y)])
            if rng.random() < 0.7:
                lx = rng.uniform(chain[0][1] + 10, max(chain[0][1] + 11, chain[-1][1] - 60))
                add_text('%s"-%s-%03d' % (rng.choice(["3/4", "1", "2", "3", "4", "6", "8"]), sys_code, rng.randint(1, 999)),
                         lx, y - 9, 4.5 * vsize, check=True)
    add_text("NOTES", 60, 700, 6.0)
    add_text("1. SYNTHETIC DRAWING FOR TRAINING. NOT A REAL DESIGN.", 60, 712, 5.0)
    return pg


def render(pg, lib, dpi, rng, degrade):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
    from PySide6.QtSvg import QSvgRenderer
    S = dpi / 72.0
    img = QImage(int(PAGE_W * S), int(PAGE_H * S), QImage.Format_Grayscale8)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pipe_w = rng.uniform(0.5, 1.2) * S
    p.setPen(QPen(Qt.black, pipe_w))
    for pts in pg.pipes:
        for a, b in zip(pts, pts[1:]):
            p.drawLine(QPointF(a[0] * S, a[1] * S), QPointF(b[0] * S, b[1] * S))
    p.setPen(QPen(Qt.black, 0.5 * S, Qt.DashLine))
    for a, b in pg.signals:
        p.drawLine(QPointF(a[0] * S, a[1] * S), QPointF(b[0] * S, b[1] * S))
    renderers = {}
    for s in pg.symbols:
        spec = lib[s["kind"]]
        r = renderers.setdefault(s["kind"], QSvgRenderer(spec["path"]))
        b = s["box"]
        p.fillRect(QRectF(b[0] * S, b[1] * S, (b[2] - b[0]) * S, (b[3] - b[1]) * S), Qt.white)
        p.save()
        p.translate(s["c"][0] * S, s["c"][1] * S)
        p.rotate(s["rot"])
        r.render(p, QRectF(-s["w"] / 2 * S, -s["h"] / 2 * S, s["w"] * S, s["h"] * S))
        p.restore()
    p.setPen(QPen(Qt.black, 0.8 * S))
    texts = []
    for t in pg.texts:
        if t.get("frame"):
            f = t["frame"]
            p.drawRect(QRectF(f[0] * S, f[1] * S, (f[2] - f[0]) * S, (f[3] - f[1]) * S))
        font = QFont(rng.choice(["Arial", "Arial Narrow", "Consolas"]) if t.get("size", 0) < 7 else "Arial")
        font.setPixelSize(max(4, round(t["size"] * S)))
        p.setFont(font)
        fm = QFontMetricsF(font)
        br = fm.tightBoundingRect(t["text"])
        x, y = t["at"][0] * S, t["at"][1] * S
        if t.get("anchor") == "c":
            x -= br.width() / 2
            y += fm.ascent() / 2 - fm.descent() / 2
        else:
            y += fm.ascent()
        p.drawText(QPointF(x, y), t["text"])
        texts.append({"text": t["text"], "box": [(x + br.left()) / S, (y + br.top()) / S, (x + br.right()) / S, (y + br.bottom()) / S]})
    p.end()
    from PIL import Image, ImageFilter
    pil = Image.frombuffer("L", (img.width(), img.height()), bytes(img.constBits()), "raw", "L", img.bytesPerLine(), 1)
    if degrade:
        pil = pil.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
        noise = Image.effect_noise(pil.size, rng.uniform(10, 25))
        pil = Image.blend(pil, noise, 0.06)
    return pil, texts


def build(out_dir, pages, seed, dpi):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 글꼴을 쓰려면 앱이 있어야 한다
    from PySide6.QtGui import QFontDatabase
    for f in ("arial.ttf", "arialn.ttf", "consola.ttf"):  # offscreen 플랫폼은 시스템 글꼴을 모르므로 직접 올린다
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f)
        if os.path.isfile(path):
            QFontDatabase.addApplicationFont(path)
    lib = load_symbols()
    rng = random.Random(seed)
    sym = cf.dataset("가상 P&ID 무작위 생성(기호 사전 그림, 씨앗 %d)" % seed)
    txt = cf.text_dataset("가상 P&ID 무작위 생성 글자")
    graphs = []
    S = dpi / 72.0
    for i in range(pages):
        pg = layout(rng, lib)
        degrade = i % 2 == 1
        pil, texts = render(pg, lib, dpi, rng, degrade)
        name = "syn-%04d" % (i + 1)
        png = "images/%s.png" % name
        os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
        pil.save(os.path.join(out_dir, png))
        meta = {"source": "synthetic", "drawing": name, "group": name, "dpi": dpi, "degraded": degrade, "seed": seed}
        iid = cf.add_image(sym, png, pil.width, pil.height, **meta)
        tid = cf.add_image(txt, png, pil.width, pil.height, **meta)
        ann = {}
        for s in pg.symbols:
            ann[s["id"]] = cf.add_box(sym, iid, cf.CATEGORY_ID[cf.canonical(s["kind"])], s["box"], S,
                                      attributes={"tag": s["tag"], "label_source": "generator"})
        for t in texts:
            cf.add_box(txt, tid, 1, t["box"], S, attributes={"text": t["text"]})
        graphs.append({"image": png, "nodes": list(ann.values()),
                       "edges": [{"a": ann[a], "b": ann[b], "flow": None} for a, b in pg.symbol_pairs()],
                       "pipes_px": [[[round(x * S, 1), round(y * S, 1)] for x, y in pts] for pts in pg.pipes]})
    cf.save(sym, os.path.join(out_dir, "symbols.coco.json"))
    cf.save(txt, os.path.join(out_dir, "text.coco.json"))
    cf.save({"schema": "hazop_train_graph", "version": 1, "pages": graphs}, os.path.join(out_dir, "graph.json"))
    return sym, txt, graphs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--pages", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args()
    t0 = time.time()
    sym, txt, graphs = build(a.out, a.pages, a.seed, a.dpi)
    from collections import Counter
    cats = {c["id"]: c["name"] for c in sym["categories"]}
    print("쪽 %d, 기호 %d, 글자 %d, 연결 %d, %.1f초" % (len(sym["images"]), len(sym["annotations"]), len(txt["annotations"]),
                                                  sum(len(g["edges"]) for g in graphs), time.time() - t0))
    print("종류별:", dict(Counter(cats[x["category_id"]] for x in sym["annotations"]).most_common()))


if __name__ == "__main__":
    main()
