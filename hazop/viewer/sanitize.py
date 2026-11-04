"""draw.io SVG 정화: XML로 파싱해 허용 목록(요소·속성·URL)에 있는 것만 다시 직렬화한다.

정규식 치환이 아니라 파서가 해석한 트리를 기준으로 하므로, 엔티티(&#58; 등)·공백 문자로 숨긴
javascript: URL도 파서가 디코드한 값으로 검사된다. XML로 읽을 수 없는 입력은 거부한다.
check.py도 같은 규칙(violations)으로 결과를 검사한다.
"""

import html
import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XHTML_NS = "http://www.w3.org/1999/xhtml"
XLINK_NS = "http://www.w3.org/1999/xlink"

# 허용 요소 (그 밖의 요소는 내용과 함께 버린다. a는 내용만 남긴다)
SVG_ELEMENTS = {"svg", "g", "defs", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
                "text", "tspan", "switch", "foreignObject", "clipPath", "linearGradient", "radialGradient",
                "stop", "pattern", "mask", "marker", "title", "desc", "symbol", "use", "image"}
XHTML_ELEMENTS = {"div", "span", "br", "b", "i", "u", "s", "strong", "em", "font", "p", "sub", "sup",
                  "ul", "ol", "li", "table", "tbody", "thead", "tr", "td", "th", "hr", "pre", "code", "h1",
                  "h2", "h3", "h4", "h5", "h6", "blockquote", "strike"}
UNWRAP_ELEMENTS = {"a"}
XHTML_VOID = {"br", "hr"}

SVG_ATTRS = {
    "id", "class", "style", "transform", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "width", "height", "d", "points", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
    "stroke-dasharray", "stroke-dashoffset", "stroke-miterlimit", "stroke-linecap", "stroke-linejoin",
    "stroke-opacity", "opacity", "font-family", "font-size", "font-weight", "font-style", "text-anchor",
    "dominant-baseline", "text-decoration", "viewBox", "version", "pointer-events", "visibility", "display",
    "clip-path", "clip-rule", "mask", "marker-start", "marker-mid", "marker-end", "offset", "stop-color",
    "stop-opacity", "gradientUnits", "gradientTransform", "patternUnits", "preserveAspectRatio",
    "requiredFeatures", "data-cell-id", "dx", "dy", "markerWidth", "markerHeight", "refX", "refY", "orient",
    "overflow", "xml:space", "href",
}
XHTML_ATTRS = {"style", "class", "dir", "align", "color", "face", "size", "colspan", "rowspan"}
URL_ATTRS = {"href"}  # xlink:href 포함 (이름 정규화 후 href)
SAFE_DATA_IMAGE = re.compile(r"^data:image/(?:png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]*$", re.I)
_CTRL = re.compile(r"[\x00-\x20\x7f]+")
_BAD_CSS = re.compile(r"url\((?!\s*['\"]?#)|expression\(|javascript:|vbscript:|@import|behavior\s*:|-moz-binding", re.I)


def _local(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def _ns(tag):
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _attr_name(key):
    """'{xlink}href' -> 'href', '{xml}space' -> 'xml:space'."""
    if key.startswith("{http://www.w3.org/XML/1998/namespace}"):
        return "xml:" + _local(key)
    return _local(key)


def _url_ok(elem_name, value):
    v = _CTRL.sub("", value).lower()
    if v.startswith("#"):
        return elem_name == "use"
    if elem_name == "image" and SAFE_DATA_IMAGE.match(value.strip()):
        return True
    return False


def _attr_ok(elem_ns, elem_name, name, value):
    if name.lower().startswith("on"):
        return False
    allowed = XHTML_ATTRS if elem_ns == XHTML_NS else SVG_ATTRS
    if name not in allowed:
        return False
    if name in URL_ATTRS:
        return _url_ok(elem_name, value)
    if name == "style" and _BAD_CSS.search(_CTRL.sub("", value)):
        return False
    if re.search(r"(?:javascript|vbscript|data):", _CTRL.sub("", value), re.I) and name != "href":
        return False
    return True


def _elem_ok(elem):
    ns, name = _ns(elem.tag), _local(elem.tag)
    if ns == XHTML_NS:
        return name in XHTML_ELEMENTS
    if ns in (SVG_NS, ""):
        return name in SVG_ELEMENTS
    return False


def parse(svg_text):
    try:
        return ET.fromstring(svg_text.encode("utf-8") if isinstance(svg_text, str) else svg_text)
    except ET.ParseError as exc:
        raise ValueError("SVG를 XML로 읽을 수 없음(거부): %s" % exc)


def violations(root):
    """허용 목록 위반 목록. 정화 결과 검사(check.py)에 쓴다."""
    found = []
    for elem in root.iter():
        name = _local(elem.tag)
        if not _elem_ok(elem):
            found.append("허용되지 않은 요소 <%s>" % name)
            continue
        for key, value in elem.attrib.items():
            an = _attr_name(key)
            if not _attr_ok(_ns(elem.tag), name, an, value):
                found.append("허용되지 않은 속성 <%s %s=%r>" % (name, an, value[:60]))
    return found


# SVG 안의 id는 모두 이 접두어를 붙여 뷰어 템플릿의 id(getElementById 대상)와 겹치지 않게 한다.
# 같은 SVG 안의 참조(url(#id), href="#id")도 함께 바꾼다.
ID_PREFIX = "svg-"
_URL_REF = re.compile(r"url\(\s*(['\"]?)#")


def _prefix_refs(name, value):
    if name == "id":
        return ID_PREFIX + value
    if name == "href" and value.strip().startswith("#"):
        return "#" + ID_PREFIX + value.strip()[1:]
    return _URL_REF.sub(lambda m: "url(%s#%s" % (m.group(1), ID_PREFIX), value)


def _serialize(elem, out, in_xhtml):
    ns, name = _ns(elem.tag), _local(elem.tag)
    attrs = []
    for key, value in elem.attrib.items():
        an = _attr_name(key)
        if _attr_ok(ns, name, an, value):
            attrs.append(' %s="%s"' % (an, html.escape(_prefix_refs(an, value), quote=True)))
    if ns == XHTML_NS and not in_xhtml:
        attrs.insert(0, ' xmlns="%s"' % XHTML_NS)
    open_tag = "<%s%s" % (name, "".join(attrs))
    children = [c for c in elem if _elem_ok(c) or _local(c.tag) in UNWRAP_ELEMENTS]
    text = html.escape(elem.text or "", quote=False)
    if ns == XHTML_NS and name in XHTML_VOID:
        out.append(open_tag + "/>")
    elif not children and not text:
        out.append(open_tag + ("></%s>" % name if ns == XHTML_NS else "/>"))
    else:
        out.append(open_tag + ">" + text)
        for c in children:
            _emit(c, out, in_xhtml or ns == XHTML_NS)
        out.append("</%s>" % name)
    # tail은 _emit에서 처리


def _emit(elem, out, in_xhtml):
    name = _local(elem.tag)
    if name in UNWRAP_ELEMENTS:  # <a>: 링크는 버리고 내용만 남긴다
        out.append(html.escape(elem.text or "", quote=False))
        for c in elem:
            if _elem_ok(c) or _local(c.tag) in UNWRAP_ELEMENTS:
                _emit(c, out, in_xhtml)
    elif _elem_ok(elem):
        _serialize(elem, out, in_xhtml)
    out.append(html.escape(elem.tail or "", quote=False))


def sanitize_svg(svg_text, root_overrides=None):
    """SVG 문자열 -> 정화된 SVG 문자열(well-formed XML, HTML 인라인 가능)."""
    root = parse(svg_text)
    if _local(root.tag) != "svg" or _ns(root.tag) not in (SVG_NS, ""):
        raise ValueError("루트 요소가 svg가 아님")
    for key in [k for k in root.attrib if _attr_name(k) not in ("width", "height", "viewBox", "version")]:
        del root.attrib[key]
    for k, v in (root_overrides or {}).items():
        root.set(k, v)
    out = []
    _serialize(root, out, False)
    s = "".join(out)
    return s.replace("<svg", '<svg xmlns="%s"' % SVG_NS, 1)
