"""벡터 PDF 한 쪽 → 도면 배경 SVG (② 뷰어용, 기획서/인터페이스.md §3.1 PDF 등록).

PDF 등록 자료에는 draw.io처럼 함께 내보낸 SVG가 없으므로, 추출과 같은 pdfplumber 객체(같은 좌표: 페이지 pt,
원점 왼쪽 위, y 아래쪽 증가)로 선·곡선·사각형·글자를 그대로 SVG로 옮긴다. 좌표가 추출 결과와 같으므로
오버레이 정렬은 offset (0, 0)이다. 이미지·클리핑·패턴 색은 그리지 않는다(벡터 P&ID 범위).
"""

import html
import math
import re

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


def _path_el(obj):
    d = _path_d(obj)
    if not d:
        return None
    fill = (_color(obj.get("non_stroking_color")) or "#000000") if obj.get("fill") else "none"
    attrs = ['d="%s"' % d, 'fill="%s"' % fill]
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


def render_page_svg(path, page=0):
    """PDF 한 쪽 → SVG 문자열(그리기 순서 유지). pdfplumber가 없으면 ImportError."""
    import pdfplumber  # 지연 import(pdf_vector와 같음)

    with pdfplumber.open(path) as pdf:
        if not 0 <= page < len(pdf.pages):
            raise ValueError("페이지 %r 없음(전체 %d쪽)" % (page, len(pdf.pages)))
        pg = pdf.pages[page]
        width, height = float(pg.width), float(pg.height)
        mb_x0, mb_top = float(pg.mediabox[0]), float(pg.mediabox[1])
        body = []
        for obj in pg.iter_layout_objects(pg.layout._objs):
            kind = obj.get("object_type")
            el = _char_el(obj, mb_x0) if kind == "char" else \
                _path_el(obj) if kind in ("line", "rect", "curve") else None
            if el:
                body.append(el)
    return ('<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="%s" height="%s" viewBox="%s %s %s %s">\n'
            '%s\n</svg>\n' % (_num(width), _num(height), _num(mb_x0), _num(mb_top), _num(width), _num(height),
                               "\n".join(body)))
