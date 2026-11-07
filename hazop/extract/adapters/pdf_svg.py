"""벡터 PDF 한 쪽 → 도면 배경 SVG (② 뷰어용, 기획서/인터페이스.md §3.1 PDF 등록).

PDF 등록 자료에는 draw.io처럼 함께 내보낸 SVG가 없으므로, 추출과 같은 pdfplumber 객체(같은 좌표: 페이지 pt,
원점 왼쪽 위, y 아래쪽 증가)로 선·곡선·사각형·글자를 그대로 SVG로 옮긴다. 좌표가 추출 결과와 같으므로
오버레이 정렬은 offset (0, 0)이다. 이미지·클리핑·패턴 색은 그리지 않는다(벡터 P&ID 범위).

추출 결과를 주면 ② 뷰어가 쓰는 data-cell-id를 붙인다: 기호 노드가 가진 PDF 요소에는 노드 ID를, 도면 뒤에는 관계·미해결
커넥터마다 실제 선 경로(evidence.pdf_path)를 보이지 않는 경로로, PDF 요소가 없는 노드(분기점)마다 보이지 않는 점 표식을
덧붙인다. 그리기 순서는 바꾸지 않는다. measure_alignment는 이 SVG와 추출 결과의 기호 bbox를 대조한다.
"""

import html
import math
import re
import xml.etree.ElementTree as ET

_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")  # XML 1.0에 쓸 수 없는 글자
HAIRLINE = 0.6  # PDF 선 두께 0(가장 가는 선)을 SVG에서 보이게 그릴 두께(pt) [제안]


def _num(v):
    return ("%.3f" % v).rstrip("0").rstrip(".") or "0"


def _color(value):
    """pdfplumber 색(회색 1개·RGB 3개·CMYK 4개) → '#rrggbb'. 읽을 수 없으면 None(검정으로 그림)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = (value,)
    try:
        vals = [min(1.0, max(0.0, float(v))) for v in value]
    except (TypeError, ValueError):
        return None
    if len(vals) == 1:
        rgb = vals * 3
    elif len(vals) == 3:
        rgb = vals
    elif len(vals) == 4:
        c, m, y, k = vals
        rgb = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    else:
        return None
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in rgb)


def _path_d(obj):
    path = obj.get("path")
    out = []
    if path:
        for cmd in path:
            op = cmd[0]
            if op in ("m", "l"):
                out.append("%s%s %s" % (op.upper(), _num(cmd[1][0]), _num(cmd[1][1])))
            elif op == "c":
                out.append("C" + " ".join("%s %s" % (_num(p[0]), _num(p[1])) for p in cmd[1:]))
            elif op == "h":
                out.append("Z")
    else:
        pts = obj.get("pts") or []
        for i, p in enumerate(pts):
            out.append("%s%s %s" % ("M" if i == 0 else "L", _num(p[0]), _num(p[1])))
        if pts and obj.get("object_type") == "rect":
            out.append("Z")
    return " ".join(out)


def _path_el(obj, cell_id=None):
    d = _path_d(obj)
    if not d:
        return None
    fill = (_color(obj.get("non_stroking_color")) or "#000000") if obj.get("fill") else "none"
    attrs = ['d="%s"' % d, 'fill="%s"' % fill]
    if cell_id:
        attrs.append('data-cell-id="%s"' % html.escape(cell_id, quote=True))
    if obj.get("fill") and obj.get("evenodd"):
        attrs.append('fill-rule="evenodd"')
    if obj.get("stroke"):
        lw = obj.get("linewidth") or 0
        attrs.append('stroke="%s"' % (_color(obj.get("stroking_color")) or "#000000"))
        attrs.append('stroke-width="%s"' % _num(lw if lw > 0 else HAIRLINE))
        dash = obj.get("dash")
        try:
            arr = [float(v) for v in (dash[0] or [])] if dash else []
        except (TypeError, ValueError, IndexError):
            arr = []
        if arr and all(math.isfinite(v) and v >= 0 for v in arr) and any(v > 0 for v in arr):
            attrs.append('stroke-dasharray="%s"' % " ".join(_num(v) for v in arr))
            try:
                attrs.append('stroke-dashoffset="%s"' % _num(float(dash[1] or 0)))
            except (TypeError, ValueError, IndexError):
                pass
    else:
        attrs.append('stroke="none"')
    return "<path %s/>" % " ".join(attrs)


def _char_el(ch, mb_x0):
    text = _XML_INVALID.sub("", ch.get("text") or "")
    if not text.strip():
        return None
    a, b, c, d, e, f = (float(v) for v in ch["matrix"])
    ka, kd = math.hypot(a, b), math.hypot(c, d)
    if not ka or not kd:
        return None
    # pdfminer 좌표는 MediaBox 원점 기준이고 pdfplumber는 x에 MediaBox x0를 다시 더한다(Page.process_object).
    # 기준선 y는 pdfplumber의 top = 높이 - y1 + MediaBox top과 같은 변환이다.
    e += mb_x0
    base = ch["top"] + ch["y1"] - f
    font = ch.get("fontname") or ""
    weight = ' font-weight="bold"' if "bold" in font.lower() else ""
    family = "Times New Roman, serif" if "times" in font.lower() else "Arial, Helvetica, sans-serif"
    return ('<text transform="matrix(%s %s %s %s %s %s)" font-size="%s" font-family="%s"%s fill="%s">%s</text>'
            % (_num(a / ka), _num(-b / ka), _num(-c / kd), _num(d / kd), _num(e), _num(base),
               _num(_char_size(ch, a, b)), family, weight,
               _color(ch.get("non_stroking_color")) or "#000000", html.escape(text)))


def _char_size(ch, a, b):
    """글자 높이. pdfplumber size는 글자 상자의 세로 길이라 세로로 쓴 글자(90°·270°)는 가로 길이를 쓴다."""
    if ch.get("upright", True) or abs(a) >= abs(b):
        return float(ch.get("size") or ch["height"])
    return float(ch["width"])


_PRIM_ID = re.compile(r"pdf-path-(\d+)")


def _owners(extraction):
    """원시 요소 번호(pdf_vector.load_page의 선·사각형·곡선 순서, 'pdf-path-NNNN') → 그 요소를 가진 기호 노드 ID."""
    out = {}
    for n in extraction["nodes"]:
        for oid in n["evidence"].get("pdf_objects") or []:
            m = _PRIM_ID.match(oid)
            if m:
                out.setdefault(int(m.group(1)), n["source_object_id"])
    return out


def _hidden(cell_id, pts):
    d = " ".join("%s%s %s" % ("M" if i == 0 else "L", _num(p[0]), _num(p[1])) for i, p in enumerate(pts))
    return '<g data-cell-id="%s"><path d="%s" fill="none" stroke="none"/></g>' % (html.escape(cell_id, quote=True), d)


def _cell_marks(extraction):
    """관계·미해결 커넥터의 실제 경로(점 2개 이상)와 PDF 요소가 없는 노드(분기점)의 점 표식."""
    out = []
    for r in extraction["relations"] + extraction["unresolved_connectors"]:
        pts = r["evidence"].get("pdf_path") or []
        if len(pts) >= 2:
            out.append(_hidden(r["source_object_id"], pts))
    for n in extraction["nodes"]:
        if not n["evidence"].get("pdf_objects"):
            g = n["geometry"]
            c = (g["x"] + g["width"] / 2, g["y"] + g["height"] / 2)
            out.append(_hidden(n["source_object_id"], [c, c]))
    return out


def render_page_svg(path, page=0, extraction=None):
    """PDF 한 쪽 → SVG 문자열(그리기 순서 유지). pdfplumber가 없으면 ImportError.
    extraction: 같은 쪽의 pdf_vector 추출 결과. 주면 data-cell-id를 붙인다(모듈 설명)."""
    import pdfplumber  # 지연 import(pdf_vector와 같음)

    with pdfplumber.open(path) as pdf:
        if not 0 <= page < len(pdf.pages):
            raise ValueError("페이지 %r 없음(전체 %d쪽)" % (page, len(pdf.pages)))
        pg = pdf.pages[page]
        width, height = float(pg.width), float(pg.height)
        mb_x0, mb_top = float(pg.mediabox[0]), float(pg.mediabox[1])
        owners = _owners(extraction) if extraction else {}
        # pg.lines·rects·curves는 그리기 순서대로 종류별로 나눈 목록이라, 종류별 순번으로 load_page의 요소 번호를 되짚는다
        nxt = {"line": 0, "rect": len(pg.lines), "curve": len(pg.lines) + len(pg.rects)}
        body = []
        for obj in pg.iter_layout_objects(pg.layout._objs):
            kind = obj.get("object_type")
            if kind in nxt:
                el = _path_el(obj, owners.get(nxt[kind]))
                nxt[kind] += 1
            else:
                el = _char_el(obj, mb_x0) if kind == "char" else None
            if el:
                body.append(el)
        if extraction:
            body += _cell_marks(extraction)
    return ('<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="%s" height="%s" viewBox="%s %s %s %s">\n'
            '%s\n</svg>\n' % (_num(width), _num(height), _num(mb_x0), _num(mb_top), _num(width), _num(height),
                               "\n".join(body)))


def _d_bbox(d):
    """이 모듈이 쓴 절대 좌표 경로(M·L·C·Z)의 bbox. 곡선은 조정점까지 넣는다(pdf_vector 기호 bbox와 같은 기준)."""
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
    xs, ys = nums[0::2], nums[1::2]
    return (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None


def measure_alignment(svg_text, extraction, tol=0.5):
    """기호 노드마다 SVG에서 그 노드 ID를 단 요소들의 bbox와 추출 결과의 노드 bbox를 대조한다(허용 오차 tol pt).
    반환은 svg_align.align과 같은 키에 max_residual·tolerance를 더한 것. 그림과 추출 모두 같은 PDF를 읽은 결과라
    독립 정답 대비 검증은 아니다(note에 남김)."""
    boxes = {}
    for el in ET.fromstring(svg_text).iter("{http://www.w3.org/2000/svg}path"):
        cid = el.get("data-cell-id")
        b = _d_bbox(el.get("d") or "") if cid else None
        if b:
            o = boxes.get(cid)
            boxes[cid] = b if o is None else (min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3]))
    missing, bad, residuals = [], [], []
    for n in extraction["nodes"]:
        if not n["evidence"].get("pdf_objects"):
            continue  # 분기점: 그린 요소가 없다
        sid, g = n["source_object_id"], n["geometry"]
        b = boxes.get(sid)
        if b is None:
            missing.append(sid)
            continue
        r = max(abs(b[0] - g["x"]), abs(b[1] - g["y"]), abs(b[2] - g["x"] - g["width"]),
                abs(b[3] - g["y"] - g["height"]))
        residuals.append(r)
        if r > tol:
            bad.append({"cell": sid, "residual": round(r, 3)})
    reasons = (["비교 가능한 기호 없음"] if not residuals else []) + \
        (["SVG 요소 bbox와 노드 bbox 차가 허용 오차보다 큰 기호 있음"] if bad else []) + \
        (["SVG에 없는 기호 노드 있음"] if missing else [])
    return {"status": "failed" if reasons else "verified", "reasons": reasons, "offset": [0, 0],
            "transform": "svg_x = pdf_x, svg_y = pdf_y (같은 pdfplumber 좌표로 그림)",
            "compared_cells": len(residuals), "consistent_cells": len(residuals) - len(bad), "inconsistent_offsets": bad,
            "unsupported_transform_cells": [], "excluded_local_transform_cells": [], "cells_missing_in_svg": missing,
            "max_residual": round(max(residuals), 3) if residuals else None, "tolerance": tol,
            "note": "기호 노드마다 SVG 요소(data-cell-id) bbox와 추출 bbox를 허용 오차 %s pt로 대조함. 그림·추출 모두 같은 PDF를 "
                    "pdfplumber로 읽은 결과라 독립 정답 대비 검증은 아님. 이미지·클리핑은 그리지 않음" % tol}
