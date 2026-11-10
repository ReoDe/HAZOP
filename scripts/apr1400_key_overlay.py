"""APR1400 독립 정답 만들기·다시 보기 도구. PDF 한 쪽을 렌더해 눈으로 확인한다(텍스트 층 대리 지표와 따로).

  python scripts/apr1400_key_overlay.py candidates <쪽.pdf> <출력 폴더>
      벡터 경로에서 작은 원·비석 모양 곡선(폭 8~30pt) 모두를 번호 붙여 잘라 붙인 접촉 시트와 쪽 전체 격자 타일을 쓴다.
      그림을 보고 계기 원·연결 표기를 골라 정답 JSON을 쓴다(원 안 글자를 텍스트 층이 아닌 그림에서 읽음).
  python scripts/apr1400_key_overlay.py overlay <쪽.pdf> <정답.json> <출력.png>
      정답 상자를 렌더한 그림 위에 겹쳐 그린다(계기 빨강, 연결 표기 파랑). 정답을 다시 확인할 때 쓴다.
좌표는 pdfplumber와 같은 PDF pt(왼쪽 위 원점).
"""

import json
import os
import sys

SCALE = 4.0


def render(pdf_path):
    import pypdfium2
    doc = pypdfium2.PdfDocument(pdf_path)
    img = doc[0].render(scale=SCALE).to_pil().convert("RGB")
    return img


def circles(pdf_path):
    """계기 기호 후보 상자. 점수판(scripts/check_apr1400.symbol_boxes)과 같은 규칙."""
    import pdfplumber
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from check_apr1400 import symbol_boxes
    with pdfplumber.open(pdf_path) as pdf:
        return [tuple(round(v, 1) for v in b) for b in symbol_boxes(pdf.pages[0])]


def arrows(pdf_path):
    """연결 표시 화살표 후보: 점 6개짜리 닫힌 경로(갈매기 모양), 길이 15~90pt·두께 4~12pt(세로로 돌린 것 포함)."""
    import pdfplumber
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for c in pdf.pages[0].curves:
            pts = c.get("pts") or []
            w, h = c["x1"] - c["x0"], c["bottom"] - c["top"]
            closed = len(pts) == 7 and abs(pts[0][0] - pts[-1][0]) < 0.2 and abs(pts[0][1] - pts[-1][1]) < 0.2
            if closed and (15 <= w <= 90 and 4 <= h <= 12 or 15 <= h <= 90 and 4 <= w <= 12):
                box = (round(c["x0"], 1), round(c["top"], 1), round(c["x1"], 1), round(c["bottom"], 1))
                if not any(abs(box[0] - b[0]) < 1 and abs(box[1] - b[1]) < 1 for b in out):
                    out.append(box)
    return out


def contact_sheet(img, boxes, pad, path):
    from PIL import Image, ImageDraw
    cell, cols = 260, 6
    sheet = Image.new("RGB", (cols * cell, max(1, ((len(boxes) + cols - 1) // cols) * (cell + 24))), "white")
    d = ImageDraw.Draw(sheet)
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        crop = img.crop((int((x0 - pad) * SCALE), int((y0 - pad) * SCALE), int((x1 + pad) * SCALE), int((y1 + pad) * SCALE)))
        ImageDraw.Draw(crop).rectangle((pad * SCALE - 3, pad * SCALE - 3, (x1 - x0 + pad) * SCALE + 3,
                                        (y1 - y0 + pad) * SCALE + 3), outline="red", width=3)
        crop.thumbnail((cell, cell))
        cx, cy = (i % cols) * cell, (i // cols) * (cell + 24)
        sheet.paste(crop, (cx, cy + 24))
        d.text((cx + 4, cy + 4), "#%d (%.0f,%.0f)" % (i, x0, y0), fill="red")
    sheet.save(path)


def candidates(pdf_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    img = render(pdf_path)
    cs = circles(pdf_path)
    contact_sheet(img, cs, 14, os.path.join(out_dir, "circles.png"))
    ar = arrows(pdf_path)
    contact_sheet(img, ar, 28, os.path.join(out_dir, "arrows.png"))
    with open(os.path.join(out_dir, "circles.json"), "w", encoding="utf-8") as fh:
        json.dump({"circles": [{"i": i, "bbox": b} for i, b in enumerate(cs)],
                   "arrows": [{"i": i, "bbox": b} for i, b in enumerate(ar)]}, fh, indent=1)
    W, H = img.size
    n = 3
    for r in range(n):
        for c in range(n):
            tile = img.crop((c * W // n, r * H // n, (c + 1) * W // n, (r + 1) * H // n))
            tile.save(os.path.join(out_dir, "tile_r%dc%d.png" % (r, c)))
    print("화살표 %d개 · 원 %d개 · 타일 %d장 · 쪽 크기 %.0fx%.0f pt → %s"
          % (len(ar), len(cs), n * n, W / SCALE, H / SCALE, out_dir))


def overlay(pdf_path, key_path, out_png):
    from PIL import ImageDraw
    img = render(pdf_path)
    d = ImageDraw.Draw(img)
    with open(key_path, encoding="utf-8") as fh:
        key = json.load(fh)
    for color, items in (("red", key["instruments"]), ("blue", key["connectors"])):
        for it in items:
            x0, y0, x1, y1 = (v * SCALE for v in it["bbox"])
            d.rectangle((x0, y0, x1, y1), outline=color, width=3)
            d.text((x0, max(0, y0 - 12)), it.get("tag") or it.get("label", ""), fill=color)
    img.save(out_png)
    print(out_png)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "candidates" and len(sys.argv) == 4:
        candidates(sys.argv[2], sys.argv[3])
    elif cmd == "overlay" and len(sys.argv) == 5:
        overlay(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
        sys.exit(2)
