"""학습 자료 공통 형식: COCO 검출 JSON(기호·글자)과 연결 그래프 JSON.

좌표는 그림 픽셀(왼쪽 위 원점), COCO bbox는 [x, y, 폭, 높이]다. 도면 pt 좌표는 scale = dpi / 72를 곱해 옮긴다.
종류 목록은 추출기 작성 규칙(hazop/extract/rules.py KIND_CATEGORY)에서 tee를 빼고 unlisted를 더한 것으로 고정한다.
같은 이름표 목록을 세 길(합성·벡터 반자동·AI 전부)이 함께 써야 학습 자료를 합칠 수 있다.
"""

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from hazop.extract.rules import KIND_CATEGORY  # noqa: E402

KINDS = sorted(k for k in KIND_CATEGORY if k != "tee") + ["unlisted"]
CATEGORY_ID = {k: i + 1 for i, k in enumerate(KINDS)}
KIND_SAME = {"psv": "relief_valve"}


def canonical(kind):
    return KIND_SAME.get(kind, kind)


def dataset(description):
    return {"info": {"description": description, "version": "0.1"},
            "licenses": [], "images": [], "annotations": [],
            "categories": [{"id": CATEGORY_ID[k], "name": k, "supercategory": KIND_CATEGORY.get(k, "unlisted")}
                           for k in KINDS]}


def text_dataset(description):
    return {"info": {"description": description, "version": "0.1"}, "licenses": [], "images": [],
            "annotations": [], "categories": [{"id": 1, "name": "text", "supercategory": "text"}]}


def add_image(ds, file_name, width, height, **meta):
    img = dict({"id": len(ds["images"]) + 1, "file_name": file_name, "width": int(width), "height": int(height)}, **meta)
    ds["images"].append(img)
    return img["id"]


def add_box(ds, image_id, category_id, box_pt, scale, **meta):
    """box_pt: [x0, y0, x1, y1] 도면 pt. → 주석 id."""
    x0, y0, x1, y1 = (v * scale for v in box_pt)
    w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    ann = dict({"id": len(ds["annotations"]) + 1, "image_id": image_id, "category_id": category_id,
                "bbox": [round(x0, 1), round(y0, 1), round(w, 1), round(h, 1)], "area": round(w * h, 1),
                "iscrowd": 0}, **meta)
    ds["annotations"].append(ann)
    return ann["id"]


def save(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def render_pdf_page(pdf_path, dpi, out_png):
    import pypdfium2
    doc = pypdfium2.PdfDocument(pdf_path)
    page = doc[0]
    w, h = page.get_size()
    img = page.render(scale=dpi / 72.0, grayscale=True).to_pil()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    img.save(out_png)
    return img.size, (w, h)
