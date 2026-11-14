"""스캔 읽기 표본 밖 측정용 합성 쪽: SNP 가상 도면에서 기호 그림만 잘라 새 배치로 놓고, 배관·화살촉·배관 번호·태그·
기기 이름을 새로 그려 쪽 그림과 정답지를 함께 만든다(HZ-PLN-23 §5, scripts/check_scan_quality.py --synthetic).

래스터 문턱과 개선은 SNP 6장을 보며 정했으므로 그 6장으로 잰 값은 표본 안 값이다. 이 쪽들은 기호 모양은 SNP와 같지만
배치·배관 경로·글자·태그 번호가 새로 정해져, 문턱이 그 6장의 배치에 맞춰졌는지 보는 데 쓴다. 기호 모양 자체가 새로운
도면(APR1400 등)에 대한 값은 아니다.

글자 배치는 SNP 관례를 따른다: 밸브 태그는 기호 위 한 줄, 기기(펌프·탱크·열교환기)는 태그와 이름을 기호 아래 두 줄.
정답지 형식은 scripts/check_read_quality.py와 같다(좌표 pt). 연결은 공정 기호끼리 배관으로 이은 쌍, 흐름은 화살촉을 그린
쪽, 배관 번호는 라벨을 그린 배관 위 점, 태그는 그린 태그 글자. 도면 연결 표시(continuation)와 밸브 위치 속성은 넣지 않는다.
씨앗이 같으면 같은 쪽이 나온다. Pillow만 쓴다(시험 venv).
"""

import os
import random

from PIL import Image, ImageDraw, ImageFont

PAGE_PT = (1190.55, 841.89)        # A3 가로
FONT_FILE = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf")
TEXT_PT = 8.0                      # SNP 라벨 글자 크기(대략)
PIPE_PT = 1.44                     # SNP 굵은 배관 두께(300dpi에서 잰 값)
ARROW_PT = (7.0, 6.4)              # 화살촉 길이·폭(SNP 화살촉 7.2×7.4pt 안팎)
USE_KINDS = ("manual_valve", "control_valve", "motor_operated_valve", "check_valve", "pump", "tank",
             "heat_exchanger", "orifice", "transmitter")
CONNECTABLE = set(USE_KINDS) - {"transmitter"}
TAG_PREFIX = {"manual_valve": "V", "control_valve": "V", "motor_operated_valve": "V", "check_valve": "V",
              "pump": "PP", "tank": "TK", "heat_exchanger": "HX", "orifice": "FO"}
NAME_WORDS = {"pump": "PUMP", "tank": "TANK", "heat_exchanger": "HEAT EXCHANGER"}
NAME_FIRST = ("FEED", "CHARGING", "MAKEUP", "DRAIN", "COOLING", "BORIC ACID", "SPRAY", "RECIRCULATION")
SYSTEMS = ("AB", "CD", "EF", "GH", "KL", "MN", "PR", "ST")
MAX_SYMBOL_PT = 150.0


def _font(px):
    return ImageFont.truetype(FONT_FILE, int(round(px)))


def symbol_library(pages):
    """pages: [(정답지, 300dpi 그림 경로, px/pt)] → 종류별 기호 조각 [{kind, img(L), w, h(pt), ports}].
    조각은 정답 상자(+1pt) 안 잉크만 남기고 밖은 흰색으로 지운다. ports: 왼·오른(가로 기호) 또는 위·아래(세로 기호) 가장자리에서
    잉크가 닿은 점(조각 좌표 px, 없으면 가운데)."""
    lib = {}
    for key, png, k in pages:
        with Image.open(png) as im:
            page = im.convert("L")
            for s in key["symbols"]:
                if s["kind"] not in USE_KINDS:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                if max(x1 - x0, y1 - y0) > MAX_SYMBOL_PT:
                    continue
                pad = 1.0
                box = tuple(int(round(v * k)) for v in (x0 - pad, y0 - pad, x1 + pad, y1 + pad))
                crop = page.crop(box)
                lib.setdefault(s["kind"], []).append({"kind": s["kind"], "img": crop, "w": crop.size[0] / k,
                                                      "h": crop.size[1] / k, "label": s.get("tag")})
    for items in lib.values():
        for it in items:
            it["vertical"] = it["kind"] in ("manual_valve", "check_valve", "orifice") and it["h"] > it["w"] * 1.3
            it["ports"] = _ports(it["img"], it["vertical"])
    return lib


def _ports(img, vertical):
    w, h = img.size
    px = img.load()

    def ink(x, y):
        return px[x, y] < 128
    if vertical:
        cols = range(w)
        top = min((x for x in cols if any(ink(x, y) for y in range(0, max(1, h // 8)))), key=lambda x: abs(x - w / 2),
                  default=w // 2)
        bot = min((x for x in cols if any(ink(x, y) for y in range(h - max(1, h // 8), h))),
                  key=lambda x: abs(x - w / 2), default=w // 2)
        return {"in": (top, 0), "out": (bot, h - 1)}
    rows = range(h)
    left = min((y for y in rows if any(ink(x, y) for x in range(0, max(1, w // 8)))), key=lambda y: abs(y - h / 2),
               default=h // 2)
    right = min((y for y in rows if any(ink(x, y) for x in range(w - max(1, w // 8), w))),
                key=lambda y: abs(y - h / 2), default=h // 2)
    return {"in": (0, left), "out": (w - 1, right)}


def make_page(lib, seed, k, out_png):
    """합성 쪽 하나를 그려 out_png에 쓰고 정답지를 돌려준다. k: px/pt(300dpi면 300/72)."""
    rng = random.Random(seed)
    W, H = int(round(PAGE_PT[0] * k)), int(round(PAGE_PT[1] * k))
    im = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(im)
    font = _font(TEXT_PT * k)
    sysc = rng.choice(SYSTEMS)
    symbols, connections, lines, used_text, labels = [], [], [], [], []
    counters = {}
    rows = 3
    row_h = (PAGE_PT[1] - 160) / rows

    def text_box(x, y, text, anchor="mm"):
        bb = dr.textbbox((x * k, y * k), text, font=font, anchor=anchor)
        return [v / k for v in bb]

    def put_text(x, y, text, anchor="mm", white=False):
        bb = dr.textbbox((x * k, y * k), text, font=font, anchor=anchor)
        if white:
            dr.rectangle([bb[0] - 3, bb[1] - 3, bb[2] + 3, bb[3] + 3], fill=255)
        dr.text((x * k, y * k), text, fill=0, font=font, anchor=anchor)
        used_text.append([v / k for v in bb])

    def pipe(points):
        t = max(1, int(round(PIPE_PT * k)))
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            dr.line([ax * k, ay * k, bx * k, by * k], fill=0, width=t)
            # 꺾임을 메운다
            dr.rectangle([bx * k - t / 2, by * k - t / 2, bx * k + t / 2, by * k + t / 2], fill=0)

    def arrow(tip, direction):
        L, Wd = ARROW_PT
        dx, dy = direction
        bx, by = tip[0] - dx * L, tip[1] - dy * L
        px_, py_ = -dy * Wd / 2, dx * Wd / 2
        dr.polygon([(tip[0] * k, tip[1] * k), ((bx + px_) * k, (by + py_) * k), ((bx - px_) * k, (by - py_) * k)], fill=0)

    for r in range(rows):
        y_mid = 110 + row_h * (r + 0.5)
        n = rng.randint(3, 5)
        xs = [90 + (PAGE_PT[0] - 200) * (i + 0.5) / n + rng.uniform(-25, 25) for i in range(n)]
        prev = None
        for i in range(n):
            kind = rng.choice([kd for kd in USE_KINDS if kd in lib and kd != "transmitter"])
            it = rng.choice(lib[kind])
            x0 = xs[i] - it["w"] / 2
            y0 = y_mid - it["h"] / 2 + rng.uniform(-15, 15)
            ox, oy = int(round(x0 * k)), int(round(y0 * k))
            im.paste(it["img"], (ox, oy), it["img"].point(lambda v: 255 if v < 200 else 0))  # 잉크만 얹는다
            sid = "s%03d" % (len(symbols) + 1)
            bbox = [round(x0 + 1.0, 1), round(y0 + 1.0, 1), round(x0 + it["w"] - 1.0, 1), round(y0 + it["h"] - 1.0, 1)]
            tag = None
            if kind in TAG_PREFIX:
                counters[kind] = counters.get(kind, 0) + 1
                tag = "%s-%s%03d" % (sysc, TAG_PREFIX[kind], rng.randint(1, 899)) if kind not in ("pump", "tank") \
                    else "%s-%s%02d" % (sysc, TAG_PREFIX[kind], rng.randint(1, 49))
                if kind in NAME_WORDS:  # 기기: SNP처럼 태그와 이름을 기호 아래 두 줄로
                    put_text((bbox[0] + bbox[2]) / 2, bbox[3] + 9, tag)
                    put_text((bbox[0] + bbox[2]) / 2, bbox[3] + 9 + TEXT_PT * 1.25,
                             "%s %s" % (rng.choice(NAME_FIRST), NAME_WORDS[kind]))
                else:  # 밸브·오리피스: 기호 위 한 줄
                    put_text((bbox[0] + bbox[2]) / 2, bbox[1] - 9, tag)
            sym = {"id": sid, "kind": kind, "bbox": bbox, "tag": tag, "attributes": {}, "_it": it, "_xy": (x0, y0)}
            symbols.append(sym)
            if prev is not None:
                a, b = prev, sym
                pa = (a["_xy"][0] + a["_it"]["ports"]["out"][0] / k, a["_xy"][1] + a["_it"]["ports"]["out"][1] / k)
                pb = (b["_xy"][0] + b["_it"]["ports"]["in"][0] / k, b["_xy"][1] + b["_it"]["ports"]["in"][1] / k)
                pts = _route(pa, pb, a["_it"]["vertical"], b["_it"]["vertical"])
                flow = rng.random() < 0.7
                if flow:
                    last_a, last_b = pts[-2], pts[-1]
                    d = (last_b[0] - last_a[0], last_b[1] - last_a[1])
                    L = max(1e-6, (d[0] ** 2 + d[1] ** 2) ** 0.5)
                    if L > ARROW_PT[0] + 2:
                        pipe(pts)
                        arrow(last_b, (d[0] / L, d[1] / L))
                    else:
                        flow = False
                        pipe(pts)
                else:
                    pipe(pts)
                connections.append({"a": a["id"], "b": b["id"], "flow": "a_to_b" if flow else None})
                seg = max(zip(pts, pts[1:]), key=lambda s: abs(s[1][0] - s[0][0]))
                seg_len = abs(seg[1][0] - seg[0][0])
                if rng.random() < 0.7 and seg_len > 70 and abs(seg[0][1] - seg[1][1]) < 0.5:
                    no = "%s-L%03d" % (sysc, rng.randint(1, 299))
                    cx = (seg[0][0] + seg[1][0]) / 2 + rng.uniform(-seg_len / 6, seg_len / 6)
                    cy = seg[0][1]
                    labels.append((cx, cy, no))  # 배관 번호는 모든 배관을 그린 뒤 흰 바탕과 함께 얹는다
                    lines.append({"id": "l%03d" % (len(lines) + 1), "at": [round(cx, 1), round(cy, 1)], "line_no": no})
            prev = sym
        # 줄 끝에 계기 하나(연결하지 않음)
        if "transmitter" in lib and rng.random() < 0.8:
            it = rng.choice(lib["transmitter"])
            x0, y0 = PAGE_PT[0] - 70, y_mid - 60
            ox, oy = int(round(x0 * k)), int(round(y0 * k))
            im.paste(it["img"], (ox, oy))
            symbols.append({"id": "s%03d" % (len(symbols) + 1), "kind": "transmitter",
                            "bbox": [round(x0 + 1, 1), round(y0 + 1, 1), round(x0 + it["w"] - 1, 1),
                                     round(y0 + it["h"] - 1, 1)], "tag": it["label"], "attributes": {}})
    # 배관 번호 라벨은 마지막에: 뒤에 그린 배관이 앞 라벨의 흰 바탕을 지나가 글자 위에 선이 겹치지 않게(SNP처럼)
    for cx, cy, no in labels:
        put_text(cx, cy, no, white=True)
    im.save(out_png)
    for s in symbols:
        s.pop("_it", None)
        s.pop("_xy", None)
    return {"schema": "hazop_read_quality_key", "version": 1, "drawing": "synthetic-%d" % seed,
            "page_size": list(PAGE_PT), "regions": [[0, 0, PAGE_PT[0], PAGE_PT[1]]],
            "method": "scripts/build_scan_synthetic.py 씨앗 %d: SNP 기호 조각을 새 배치로 놓고 배관·글자를 새로 그림" % seed,
            "symbols": symbols, "lines": lines, "connections": connections, "continuations": []}


def _route(pa, pb, va, vb):
    """두 포트 사이 직각 경로(점 목록). 세로 기호는 아래로 나가고 위로 들어온다."""
    if va:
        pa2 = (pa[0], pa[1] + 15)
        start = [pa, pa2]
    else:
        start = [pa]
    if vb:
        pb2 = (pb[0], pb[1] - 15)
        end = [pb2, pb]
    else:
        end = [pb]
    s, e = start[-1], end[0]
    if vb:  # 세로로 들어간다: 가로로 간 뒤 내려간다
        mid = [(e[0], s[1])]
    elif abs(s[1] - e[1]) < 0.5:
        mid = []
    else:
        mx = (s[0] + e[0]) / 2
        mid = [(mx, s[1]), (mx, e[1])]
    pts = start + mid + end
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out
