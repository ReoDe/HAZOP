"""도면 한 장의 그리기 자료(items)를 추출 결과에서 만든다(`hazop/shell/web/js/canvas/README.md`의 입력 자료). Qt를 import하지 않는다.

좌표는 모두 SVG 사용자 단위다: 추출 좌표(draw.io)에서 `svg_alignment.offset`을 뺀다(svg_x = drawio_x - offset[0]).
- 구성요소(node): `geometry`(x·y·width·height)가 bbox이고, 없으면 글자 위치(`label_location.bbox`)를 쓴다.
- 배관(relation): 끝점(`endpoints[].point`)과 꺾임점(`waypoints`)을 이은 꺾은선이고 bbox는 그 꺾은선을 감싼 상자다.
- 미확인(unknown): 분류가 안 된 기호(classification이 classified가 아니거나 kind가 비어 있음)와 끝이 이어지지 않은 배관이다.
엔진은 자료를 바꾸지 않는다(읽기만).
"""

import re


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _alignment(extraction):
    return ((extraction.get("coordinate_system") or {}).get("svg_alignment")) or {}


def _offset(extraction):
    off = _alignment(extraction).get("offset")
    if isinstance(off, (list, tuple)) and len(off) == 2 and all(_num(x) is not None for x in off):
        return float(off[0]), float(off[1])
    return 0.0, 0.0


def _view_size(extraction):
    vb = _alignment(extraction).get("viewBox")
    if isinstance(vb, str):
        parts = [p for p in re.split(r"[ ,]+", vb.strip()) if p]
        if len(parts) == 4:
            try:
                return float(parts[2]), float(parts[3])
            except ValueError:
                pass
    d = extraction.get("drawing") or {}
    return float(d.get("page_width") or 0), float(d.get("page_height") or 0)


def _box(b, ox, oy):
    """[x, y, w, h] -> [x0, y0, x1, y1](SVG 좌표). 모양이 틀리면 None."""
    if isinstance(b, (list, tuple)) and len(b) == 4 and all(_num(v) is not None for v in b):
        return [b[0] - ox, b[1] - oy, b[0] + b[2] - ox, b[1] + b[3] - oy]
    return None


def _node_bbox(n, ox, oy):
    g = n.get("geometry") or {}
    x, y, w, h = _num(g.get("x")), _num(g.get("y")), _num(g.get("width")), _num(g.get("height"))
    if None not in (x, y, w, h):
        return [x - ox, y - oy, x + w - ox, y + h - oy]
    return _box((n.get("label_location") or {}).get("bbox"), ox, oy)


def _pair(p, ox, oy):
    if isinstance(p, (list, tuple)) and len(p) == 2 and all(_num(v) is not None for v in p):
        return [p[0] - ox, p[1] - oy]
    if isinstance(p, dict) and _num(p.get("x")) is not None and _num(p.get("y")) is not None:
        return [p["x"] - ox, p["y"] - oy]
    return None


def _points(r, ox, oy):
    src, dst = [], []
    for ep in r.get("endpoints") or []:
        if not isinstance(ep, dict):
            continue
        p = _pair(ep.get("point"), ox, oy)
        if p is not None:
            (src if ep.get("end") == "source" else dst).append(p)
    way = [p for p in (_pair(w, ox, oy) for w in r.get("waypoints") or []) if p is not None]
    return src + way + dst


def build_items(extraction):
    """추출 결과 -> {"width","height","items":[…]}. 각 item: id(local_id), kind, category, tag, layer(symbol|pipe), bbox, polyline,
    classification, unknown, label_bbox(구성요소의 글자 자리)."""
    ox, oy = _offset(extraction)
    items = []
    for n in extraction.get("nodes") or []:
        if not isinstance(n, dict) or not isinstance(n.get("local_id"), str):
            continue
        bbox = _node_bbox(n, ox, oy)
        if bbox is None:
            continue
        cls = n.get("classification")
        items.append({"id": n["local_id"], "kind": n.get("kind"), "category": n.get("category"), "tag": n.get("tag"), "layer": "symbol",
                      "bbox": bbox, "polyline": None, "classification": cls, "unknown": cls not in (None, "classified") or not n.get("kind"),
                      "label_bbox": _box((n.get("label_location") or {}).get("bbox"), ox, oy)})
    for r in extraction.get("relations") or []:
        if not isinstance(r, dict) or not isinstance(r.get("local_id"), str):
            continue
        line = _points(r, ox, oy)
        if len(line) < 2:
            continue
        xs, ys = [p[0] for p in line], [p[1] for p in line]
        open_end = any((ep or {}).get("status") != "connected" for ep in r.get("endpoints") or [] if isinstance(ep, dict))
        items.append({"id": r["local_id"], "kind": r.get("kind"), "category": "pipe", "tag": r.get("line_no") or r.get("label_text"),
                      "layer": "pipe", "bbox": [min(xs), min(ys), max(xs), max(ys)], "polyline": line, "classification": "classified",
                      "unknown": open_end, "label_bbox": None})
    w, h = _view_size(extraction)
    return {"width": w, "height": h, "items": items}
