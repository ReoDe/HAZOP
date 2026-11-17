"""AI 검토에 싣는 그림: 노드 조각과 범례판(docs/specs/extraction.md 'AI 검토', 계획 aiplan 2026-11-17).

조각: 노드 상자 둘레에 PAD pt를 더해 SCALE배로 그린 PNG. 상자 테두리를 빨갛게 그어 어느 기호를 묻는지 보인다.
범례판: 종류(kind)마다 견본 조각 하나에 kind 이름을 적은 칸을 모아 범주별로 한 장씩 만든다. 견본은 스크립트가 종류를
정한 노드에서 고른다. APR1400은 범례 쪽(1.7-1 1/4~4/4)의 추출 결과, SNP는 SNP 도면들의 추출 결과를 쓴다.
보낼 그림이 어느 도면 묶음에서 왔는지는 부르는 쪽이 정한다(이 모듈은 보내지 않는다).
"""

import base64
import io
import json

from hazop import paths
from hazop.extract import rules

SCALE = 2.0
PAD = 25.0
SAMPLE_PAD = 6.0
CELL = (200, 150)      # 범례판 칸 크기(px). 아래 18px는 이름 글자
BOARD_COLS = 5
BOARD_CELLS = 20       # 범례판 한 장의 칸 수 상한
OUTLINE = (230, 0, 0)


def viewer_kinds():
    """보기가 그림을 가진 종류(resources/library/drawing-symbols/manifest.json) 가운데 레지스트리에 있는 것.
    그림 없이 점으로 그리는 이음점(junction, tee)은 기호가 아니라 뺀다."""
    with open(paths.folder("drawing-symbols", "manifest.json"), encoding="utf-8") as fh:
        rows = json.load(fh)["symbols"]
    return sorted({r["kind"] for r in rows if not r.get("junction")} & set(rules.KIND_CATEGORY))


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def block(label, png):
    """analyze 요청의 images 칸 하나."""
    return {"label": label, "media_type": "image/png", "data": base64.b64encode(png).decode("ascii")}


class PageImages:
    """PDF 한 쪽의 그림. 처음 자를 때 한 번만 그린다."""

    def __init__(self, pdf_path, page=0, scale=SCALE):
        self.pdf_path, self.page, self.scale = pdf_path, page, scale
        self._img = None

    def image(self):
        if self._img is None:
            import pypdfium2
            doc = pypdfium2.PdfDocument(self.pdf_path)
            try:
                self._img = doc[self.page].render(scale=self.scale).to_pil().convert("RGB")
            finally:
                doc.close()
        return self._img

    def crop(self, bbox, pad=PAD, outline=True):
        """bbox(pt) 둘레 조각(PIL). outline이면 상자 테두리를 긋는다."""
        from PIL import ImageDraw
        img, s = self.image(), self.scale
        box = [max(0.0, bbox[0] - pad), max(0.0, bbox[1] - pad),
               min(img.width / s, bbox[2] + pad), min(img.height / s, bbox[3] + pad)]
        out = img.crop(tuple(int(round(v * s)) for v in box)).copy()
        if outline:
            ImageDraw.Draw(out).rectangle([(bbox[0] - box[0]) * s - 2, (bbox[1] - box[1]) * s - 2,
                                           (bbox[2] - box[0]) * s + 2, (bbox[3] - box[1]) * s + 2],
                                          outline=OUTLINE, width=2)
        return out

    def crop_png(self, bbox):
        return _png(self.crop(bbox))


def _box(n):
    g = n.get("geometry") or {}
    if "x" not in g:
        return None
    return [g["x"], g["y"], g["x"] + (g.get("width") or 0), g["y"] + (g.get("height") or 0)]


def pick_samples(sources, kinds):
    """sources [(PageImages, extraction)] -> {kind: (PageImages, bbox)}. 종류마다 그 종류가 처음 나오는 쪽(앞 쪽 우선:
    범례 쪽을 먼저 주면 범례 견본을 쓴다)에서 상자가 가장 큰 노드 하나(작은 조각보다 기호 전체가 보이는 것)."""
    best = {}
    for pi, (page, ex) in enumerate(sources):
        for n in sorted(ex.get("nodes") or [], key=lambda n: str(n.get("source_object_id"))):
            k, b = n.get("kind"), _box(n)
            if k not in kinds or b is None:
                continue
            area = (b[2] - b[0]) * (b[3] - b[1])
            if k not in best or (best[k][1] == pi and area > best[k][0]):
                best[k] = (area, pi, page, b)
    return {k: (v[2], v[3]) for k, v in best.items()}


def board(cells):
    """cells [(이름, PIL 조각)] -> 범례판 PNG 바이트."""
    from PIL import Image, ImageDraw
    w, h = CELL
    rows = (len(cells) + BOARD_COLS - 1) // BOARD_COLS
    out = Image.new("RGB", (w * BOARD_COLS, h * rows), "white")
    d = ImageDraw.Draw(out)
    for i, (name, img) in enumerate(cells):
        x, y = (i % BOARD_COLS) * w, (i // BOARD_COLS) * h
        r = min((w - 10) / img.width, (h - 26) / img.height, 4.0)  # 작은 기호는 4배까지 키워 모양이 보이게
        fit = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
        out.paste(fit, (x + (w - fit.width) // 2, y + 4 + (h - 26 - fit.height) // 2))
        d.rectangle([x, y, x + w - 1, y + h - 1], outline=(170, 170, 170))
        d.text((x + 5, y + h - 18), name, fill=(0, 0, 160))
    return _png(out)


def legend_boards(sources, kinds=None):
    """범례판 PNG 바이트 목록(범주 순, 한 장 BOARD_CELLS칸까지)과 견본이 있는 종류 목록."""
    kinds = set(kinds or viewer_kinds())
    picked = pick_samples(sources, kinds)
    order = sorted(picked, key=lambda k: (rules.KIND_CATEGORY.get(k) or "", k))
    cells = [(k, picked[k][0].crop(picked[k][1], pad=SAMPLE_PAD, outline=False)) for k in order]
    boards = [board(cells[i:i + BOARD_CELLS]) for i in range(0, len(cells), BOARD_CELLS)]
    return boards, order


class ImageInput:
    """AI 검토 한 쪽에 실을 그림: 그 쪽 조각(page)과 범례판(legend, PNG 바이트 목록), 답으로 받을 종류(kinds)."""

    def __init__(self, page, legend=(), kinds=None):
        self.page = page
        self.legend = list(legend)
        self.kinds = sorted(kinds or viewer_kinds())
