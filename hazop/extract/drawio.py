"""draw.io(.drawio) P&ID 원본 구조 읽기와 추출 결과 생성.

근거: 기획서/정보추출.md(작성 규칙·실행 순서·공통 계약 초안), 기획서/전체기획.md #data-contract,
기획서/정보통합관리.md #node-unit. 표준 라이브러리만 사용한다.
"""

import base64
import hashlib
import html
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from html.parser import HTMLParser

from . import rules

SCHEMA_VERSION = "0.1"
SCRIPT_NAME = "hazop.extract.drawio"
SCRIPT_VERSION = "0.2.0"
COORDINATE_SPACE = "page_local_2d"
UNIT = "canvas_unit"
DEFAULT_FONT_SIZE = 11.0  # draw.io 기본 글자 크기
DEFAULT_SPACING = 2.0  # draw.io 기본 spacing
NUMERIC_STYLE_KEYS = ("rotation", "fontSize", "spacing", "spacingLeft", "spacingRight", "spacingTop",
                      "spacingBottom")


# ---------------------------------------------------------------- 파일 읽기

def _decode_diagram_text(text):
    """압축 저장(deflate raw + base64 + URL 인코딩)된 diagram 본문을 XML 문자열로 푼다."""
    data = base64.b64decode(text.strip())
    xml_text = zlib.decompress(data, -15).decode("utf-8")
    return urllib.parse.unquote(xml_text)


def load_pages(raw_bytes):
    """drawio 파일 바이트에서 페이지 목록 [(page_id, page_name, mxGraphModel 요소, compressed)]."""
    root = ET.fromstring(raw_bytes)
    if root.tag == "mxGraphModel":
        return [(None, None, root, False)]
    if root.tag != "mxfile":
        raise ValueError("drawio 루트 요소가 mxfile/mxGraphModel이 아님: %s" % root.tag)
    pages = []
    for diagram in root.findall("diagram"):
        model = diagram.find("mxGraphModel")
        compressed = False
        if model is None:
            text = (diagram.text or "").strip()
            if not text:
                raise ValueError("diagram %r 본문이 비어 있음" % diagram.get("id"))
            if text.startswith("<"):
                model = ET.fromstring(text)
            else:
                model = ET.fromstring(_decode_diagram_text(text))
                compressed = True
        pages.append((diagram.get("id"), diagram.get("name"), model, compressed))
    if not pages:
        raise ValueError("diagram 요소가 없음")
    return pages


# ---------------------------------------------------------------- 보조 함수

def parse_style(style):
    """'a=1;b=2;text;' -> {'a': '1', 'b': '2', 'text': True}. 같은 키가 반복되면 마지막 값."""
    result = {}
    for token in (style or "").split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = value
        else:
            result[token] = True
    return result


class _TextExtractor(HTMLParser):
    _BREAK_TAGS = {"br", "div", "p", "li", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def label_to_text(label, style_map):
    """라벨 원문을 사람이 읽는 텍스트로. html=1이면 태그를 지우고 <br>은 줄바꿈으로."""
    if not label:
        return ""
    if style_map.get("html") == "1":
        parser = _TextExtractor()
        parser.feed(label)
        parser.close()
        text = "".join(parser.parts)
    else:
        text = html.unescape(label)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _to_float(value):
    """숫자 문자열 -> float. 실패하면 None (0으로 바꾸지 않는다)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _style_num(style_map, key, default):
    """스타일 수치. 없으면 기본값, 잘못된 값이면 None."""
    if key not in style_map:
        return default
    return _to_float(style_map[key])


def _clean_number(value):
    return int(value) if float(value).is_integer() else round(value, 3)


def _bbox(x, y, w, h):
    return [_clean_number(x), _clean_number(y), _clean_number(w), _clean_number(h)]


def estimate_label_bbox(shape_bbox, style_map, text):
    """도형 라벨(태그 텍스트)의 bbox를 근사 계산한다.

    draw.io 규칙: labelPosition(left/center/right)·verticalLabelPosition(top/middle/bottom)으로
    라벨 영역을 도형 옆으로 옮기고, 그 영역 안에서 align·verticalAlign·spacing으로 글자를 놓는다.
    글자 크기는 글꼴 측정 없이 fontSize로 추정하므로 근사값이다
    (폭 = 0.6 x fontSize x 최장 줄 글자 수, 높이 = 1.2 x fontSize x 줄 수).
    """
    if not text or shape_bbox is None:
        return None
    x, y, w, h = shape_bbox
    font = _style_num(style_map, "fontSize", DEFAULT_FONT_SIZE) or DEFAULT_FONT_SIZE
    lines = text.split("\n")
    tw = 0.6 * font * max(len(line) for line in lines)
    th = 1.2 * font * len(lines)
    spacing = _style_num(style_map, "spacing", DEFAULT_SPACING) or 0.0
    sp = {k: spacing + (_style_num(style_map, "spacing" + k, 0.0) or 0.0)
          for k in ("Left", "Right", "Top", "Bottom")}

    label_pos = style_map.get("labelPosition", "center")
    vlabel_pos = style_map.get("verticalLabelPosition", "middle")
    ax = x - w if label_pos == "left" else (x + w if label_pos == "right" else x)
    ay = y - h if vlabel_pos == "top" else (y + h if vlabel_pos == "bottom" else y)

    align = style_map.get("align", "center")
    valign = style_map.get("verticalAlign", "middle")
    if align == "left":
        tx = ax + sp["Left"]
    elif align == "right":
        tx = ax + w - sp["Right"] - tw
    else:
        tx = ax + (w - tw) / 2.0
    if valign == "top":
        ty = ay + sp["Top"]
    elif valign == "bottom":
        ty = ay + h - sp["Bottom"] - th
    else:
        ty = ay + (h - th) / 2.0
    return {
        "bbox": _bbox(tx, ty, tw, th),
        "approximate": True,
        "method": "drawio_label_style_estimate",
        "style": {"labelPosition": label_pos, "verticalLabelPosition": vlabel_pos,
                  "align": align, "verticalAlign": valign, "fontSize": _clean_number(font)},
    }


# ---------------------------------------------------------------- 셀 수집

class _Cell:
    """root 바로 아래의 mxCell 또는 object/UserObject(+내부 mxCell)."""

    def __init__(self, element, order):
        self.order = order
        if element.tag == "mxCell":
            self.cell = element
            self.user_attrs = {}
            self.label = element.get("value") or ""
        else:
            self.cell = element.find("mxCell")
            if self.cell is None:
                self.cell = ET.Element("mxCell")
            self.user_attrs = {k: v for k, v in element.attrib.items()
                               if k not in ("id", "label", "placeholders")}
            self.label = element.get("label") or ""
        self.cell_id = element.get("id")
        self.style = self.cell.get("style") or ""
        self.style_map = parse_style(self.style)
        self.parent = self.cell.get("parent")
        self.is_vertex = self.cell.get("vertex") == "1"
        self.is_edge = self.cell.get("edge") == "1"
        self.source = self.cell.get("source")
        self.target = self.cell.get("target")
        self.text = label_to_text(self.label, self.style_map)
        self._parse_geometry()

    def _parse_geometry(self):
        """수치 파싱. 잘못된 값은 geo_errors에 남기고 0으로 바꾸지 않는다."""
        g = self.cell.find("mxGeometry")
        self.geo = None
        self.geo_errors = []
        self.raw_geo = None
        if g is None:
            return
        geo, raw = {}, {}

        def num(label, value):
            f = _to_float(value)
            if f is None:
                self.geo_errors.append("%s=%r" % (label, value))
                return value
            return f

        for key in ("x", "y", "width", "height"):
            if g.get(key) is not None:
                v = num(key, g.get(key))
                raw[key] = _clean_number(v) if isinstance(v, float) else v
                if isinstance(v, float):
                    geo[key] = v
        geo["relative"] = g.get("relative") == "1"
        if geo["relative"]:
            raw["relative"] = True
        for point in g.findall("mxPoint"):
            role = point.get("as")
            if role in ("sourcePoint", "targetPoint", "offset"):
                px, py = num(role + ".x", point.get("x", "0")), num(role + ".y", point.get("y", "0"))
                raw[role] = [_clean_number(v) if isinstance(v, float) else v for v in (px, py)]
                if isinstance(px, float) and isinstance(py, float):
                    geo[role] = (px, py)
        array = g.find("Array")
        if array is not None:
            pts, raw_pts = [], []
            for i, p in enumerate(array.findall("mxPoint")):
                px, py = num("points[%d].x" % i, p.get("x", "0")), num("points[%d].y" % i, p.get("y", "0"))
                raw_pts.append([_clean_number(v) if isinstance(v, float) else v for v in (px, py)])
                if isinstance(px, float) and isinstance(py, float):
                    pts.append((px, py))
            raw["points"] = raw_pts
            geo["points"] = pts
        self.geo, self.raw_geo = geo, raw

    @property
    def ignored(self):
        return self.style_map.get("pidIgnore") == "1"


def _collect_cells(model):
    root = model.find("root")
    if root is None:
        raise ValueError("mxGraphModel에 root가 없음")
    return [_Cell(el, i) for i, el in enumerate(root)]


# ---------------------------------------------------------------- 추출

def _issue(lst, check, reason, source_object_id=None, target=None, field=None):
    lst.append({"check": check, "target": target, "source_object_id": source_object_id,
                "field": field, "reason": reason})


def _title_block(ignored_cells, boxes):
    """pidIgnore 셀 중 같은 행에 2칸(키·값)인 것을 표제란 쌍으로 읽는다 [추론: 샘플 표제란 배치 기준]."""
    rows = {}
    for c in ignored_cells:
        info = boxes.get(c.cell_id)
        if info is None or not c.text:
            continue
        rows.setdefault(round(info["bbox"][1]), []).append((info["bbox"][0], c))
    block = {}
    for _, items in sorted(rows.items()):
        if len(items) != 2:
            continue
        items.sort(key=lambda t: t[0])
        key, value = items[0][1], items[1][1]
        block[key.text] = {"value": value.text, "key_object_id": key.cell_id,
                           "value_object_id": value.cell_id}
    return block


def extract(path, page=0, repo_root=None, registration=None):
    """drawio 파일 하나(페이지 하나)를 추출 결과 dict로 만든다.

    registration: ① 등록정보(dict). 주면 project_id·material_id·registration_version·document_id를 채우고
    등록 단계의 미확인 항목을 그대로 전달한다. 없으면 등록 미연동(not_registered)으로 미확인 기록.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    pages = load_pages(raw)
    if isinstance(page, str):
        matches = [i for i, p in enumerate(pages) if p[1] == page or p[0] == page]
        if not matches:
            raise ValueError("페이지 %r 없음" % page)
        page = matches[0]
    page_id, page_name, model, compressed = pages[page]
    cells = _collect_cells(model)

    blockers, unknowns = [], []
    by_id = {}
    for c in cells:
        if c.cell_id is None:
            _issue(blockers, "missing_id", "id 속성이 없는 셀")
            continue
        if c.cell_id in by_id:
            _issue(blockers, "duplicate_id", "같은 id가 두 번 이상 나타남", c.cell_id)
            continue
        by_id[c.cell_id] = c
    cells = [c for c in cells if c.cell_id is not None and by_id.get(c.cell_id) is c]

    for c in cells:
        for err in c.geo_errors:
            _issue(blockers, "invalid_number", "좌표 수치를 읽을 수 없음: %s" % err, c.cell_id,
                   field="geometry")
        # 좌표·라벨 계산에 쓰는 스타일 수치. 잘못된 값은 0·기본값으로 조용히 바꾸지 않고 오류로 남긴다(원문 style 보존).
        for key in NUMERIC_STYLE_KEYS:
            if key in c.style_map and _to_float(c.style_map[key]) is None:
                _issue(blockers, "invalid_number", "스타일 수치를 읽을 수 없음: %s=%r" % (key, c.style_map[key]),
                       c.cell_id, field="style." + key)

    # parent 참조·순환 검사
    cyclic = set()
    for c in cells:
        if c.parent is not None and c.parent not in by_id:
            _issue(blockers, "missing_reference", "parent %r 가 존재하지 않음" % c.parent,
                   c.cell_id, field="parent")
        seen, cur = [], c.cell_id
        while cur is not None and cur in by_id:
            if cur in seen:
                cyclic.update(seen[seen.index(cur):])
                break
            seen.append(cur)
            cur = by_id[cur].parent
    for cid in sorted(cyclic):
        _issue(blockers, "parent_cycle", "parent 관계가 자기 자신 또는 순환을 가리킴", cid, field="parent")

    layer_ids = {c.cell_id for c in cells if c.parent in (None, "0") and not c.is_vertex
                 and not c.is_edge and c.cell_id not in cyclic}

    # 절대 좌표. 부모가 레이어면 그대로, 부모가 도형이면 mxGraph 규칙으로 계산하되
    # 상대 좌표(relative=1)나 회전된 부모는 근사로 표시한다. 계산 근거가 없으면 None.
    box_cache = {}

    def origin_of(parent_id):
        """자식 좌표의 기준 원점 (x, y, approximate, reason) 또는 None."""
        if parent_id is None or parent_id in layer_ids:
            return (0.0, 0.0, False, None)
        p = by_id.get(parent_id)
        if p is None or parent_id in cyclic or not p.is_vertex:
            return None
        info = box_of(parent_id)
        if info is None:
            return None
        rot = _style_num(p.style_map, "rotation", 0.0)
        approx = info["approximate"] or rot != 0.0
        reason = info["reason"] or ("부모 도형이 회전됨" if rot != 0.0 else None)
        return (info["bbox"][0], info["bbox"][1], approx, reason)

    def box_of(cid):
        if cid in box_cache:
            return box_cache[cid]
        box_cache[cid] = None  # 재귀 보호
        c = by_id[cid]
        g = c.geo
        if (not c.is_vertex or g is None or c.geo_errors or cid in cyclic):
            return None
        parent = by_id.get(c.parent)
        if parent is not None and parent.is_edge:
            return None  # 커넥터 라벨: 위치는 커넥터 경로에 따라 정해지므로 계산하지 않음
        o = origin_of(c.parent)
        if o is None:
            return None
        ox, oy, approx, reason = o
        x, y = g.get("x", 0.0), g.get("y", 0.0)
        w, h = g.get("width", 0.0), g.get("height", 0.0)
        if g["relative"]:
            if c.parent in layer_ids or c.parent is None:
                return None  # 레이어 기준 상대 좌표는 의미가 없음
            pw, ph = box_cache[c.parent]["bbox"][2], box_cache[c.parent]["bbox"][3]
            off = g.get("offset", (0.0, 0.0))
            x, y = x * pw + off[0], y * ph + off[1]
            approx, reason = True, "relative=1 (부모 크기 비율) 좌표"
        info = {"bbox": [ox + x, oy + y, w, h], "approximate": approx, "reason": reason,
                "basis": "page" if c.parent in layer_ids else "parent_vertex"}
        box_cache[cid] = info
        return info

    boxes = {}
    for c in cells:
        info = box_of(c.cell_id)
        if info is not None:
            boxes[c.cell_id] = info

    # 분류
    ignored, nodes, texts, unclassified, connectors, edge_labels = [], [], [], [], [], []
    for c in cells:
        if c.cell_id in layer_ids:
            continue
        parent = by_id.get(c.parent)
        if c.ignored:
            ignored.append(c)
        elif c.is_edge:
            connectors.append(c)
        elif parent is not None and parent.is_edge:
            edge_labels.append(c)
        elif c.is_vertex:
            kind = c.user_attrs.get("kind")
            if kind is None and c.style_map.get("text") is True:
                texts.append(c)
            else:
                nodes.append(c)
        else:
            unclassified.append(c)

    def add_location_issue(c, local_id):
        info = boxes.get(c.cell_id)
        if info is None:
            _issue(unknowns, "missing_geometry", "도형 좌표를 확정할 수 없음", c.cell_id, local_id, "bbox")
        elif info["approximate"]:
            _issue(unknowns, "approximate_geometry", "좌표 근사: %s" % info["reason"],
                   c.cell_id, local_id, "bbox")

    local_of = {}
    node_out = []
    for i, c in enumerate(nodes, 1):
        local_id = "local-node-%03d" % i
        local_of[c.cell_id] = local_id
        kind = c.user_attrs.get("kind")
        category = rules.KIND_CATEGORY.get(kind)
        if kind is None:
            classification = "unclassified"
            _issue(unknowns, "missing_kind", "도형에 kind 속성이 없음", c.cell_id, local_id, "kind")
        elif category is None:
            classification = "unclassified"
            _issue(unknowns, "unclassified_kind",
                   "작성 규칙에 없는 kind 값 %r (원값 유지)" % kind, c.cell_id, local_id, "kind")
        else:
            classification = "classified"
        tag = c.user_attrs.get("tag") or None
        if tag is None and kind not in rules.KINDS_WITHOUT_TAG:
            _issue(unknowns, "missing_tag", "tag 속성이 없음", c.cell_id, local_id, "tag")
        if kind in rules.KINDS_NEED_NORMAL_POSITION:
            npos = c.user_attrs.get("normal_position")
            if not npos:
                _issue(unknowns, "missing_normal_position", "밸브 정상 위치 미확인",
                       c.cell_id, local_id, "normal_position")
            elif npos not in rules.NORMAL_POSITION_VALUES:
                _issue(unknowns, "invalid_normal_position", "규칙에 없는 값 %r" % npos,
                       c.cell_id, local_id, "normal_position")
        if kind in rules.KINDS_NEED_FAIL_POSITION and not c.user_attrs.get("fail_position"):
            _issue(unknowns, "missing_fail_position", "제어밸브 실패 위치 미확인",
                   c.cell_id, local_id, "fail_position")
        if c.user_attrs.get("flow_direction"):
            # 도형의 방향 값이 어느 커넥터 기준인지 원본에 근거가 없으므로 방향을 만들지 않는다.
            check = ("check_valve_direction_basis_unresolved" if kind == "check_valve"
                     else "node_direction_basis_unresolved")
            _issue(unknowns, check, "도형의 flow_direction %r 의 기준 커넥터를 판정할 근거 없음(값만 보존)"
                   % c.user_attrs["flow_direction"], c.cell_id, local_id, "flow_direction")
        add_location_issue(c, local_id)
        info = boxes.get(c.cell_id)
        node_out.append({
            "local_id": local_id,
            "source_object_id": c.cell_id,
            "classification": classification,
            "category": category,
            "kind": kind,
            "tag": tag,
            "label": c.label,
            "label_text": c.text,
            "label_location": estimate_label_bbox(info["bbox"] if info else None, c.style_map, c.text),
            "attributes": dict(c.user_attrs),
            "style": c.style,
            "parent": c.parent,
            "geometry": c.raw_geo,
        })

    text_out = []
    for i, c in enumerate(texts, 1):
        local_id = "local-text-%03d" % i
        local_of[c.cell_id] = local_id
        add_location_issue(c, local_id)
        text_out.append({"local_id": local_id, "source_object_id": c.cell_id, "label": c.label,
                         "text": c.text, "attributes": dict(c.user_attrs), "style": c.style,
                         "parent": c.parent, "geometry": c.raw_geo,
                         "knowledge_status": "unknown",
                         "note": "소속 대상 미확정(거리로 확정하지 않음)"})

    unclassified_out = []
    for c in unclassified:
        unclassified_out.append({"source_object_id": c.cell_id, "label_text": c.text,
                                 "attributes": dict(c.user_attrs), "style": c.style,
                                 "parent": c.parent, "geometry": c.raw_geo})
        _issue(unknowns, "unclassified_element", "도형·커넥터 어느 쪽도 아닌 셀", c.cell_id)

    labels_of_edge = {}
    for c in edge_labels:
        labels_of_edge.setdefault(c.parent, []).append({
            "source_object_id": c.cell_id, "label": c.label, "text": c.text,
            "attributes": dict(c.user_attrs), "style": c.style, "geometry": c.raw_geo,
            "location": None, "note": "커넥터 라벨. 위치는 커넥터 경로 기준이라 계산하지 않음"})

    relations, unresolved = [], []
    for i, c in enumerate(connectors, 1):
        local_id = "local-edge-%03d" % i
        line_type = c.user_attrs.get("line_type")
        rel_kind = rules.LINE_TYPE_RELATION.get(line_type)
        if line_type is None:
            _issue(unknowns, "missing_line_type", "커넥터에 line_type이 없어 관계 종류 미확인",
                   c.cell_id, local_id, "line_type")
        elif rel_kind is None:
            _issue(unknowns, "unknown_line_type",
                   "작성 규칙에 없는 line_type %r (원값 유지)" % line_type,
                   c.cell_id, local_id, "line_type")
        geom = c.geo or {}
        o = origin_of(c.parent) if c.cell_id not in cyclic else None
        approx_path = o is None or o[2]
        ox, oy = (o[0], o[1]) if o else (0.0, 0.0)
        endpoints, resolved = [], True
        for end, ref, prefix, point_key in (("source", c.source, "exit", "sourcePoint"),
                                            ("target", c.target, "entry", "targetPoint")):
            constraint = None
            if any(prefix + s in c.style_map for s in ("X", "Y")):
                vals = {k: _style_num(c.style_map, prefix + s, 0.0)
                        for k, s in (("x", "X"), ("y", "Y"), ("dx", "Dx"), ("dy", "Dy"))}
                if None in vals.values():
                    _issue(blockers, "invalid_number", "%s 접속 위치 스타일 수치 오류" % prefix,
                           c.cell_id, local_id, "style")
                else:
                    constraint = vals
            ep = {"end": end, "node_local_id": None, "source_object_id": ref,
                  "constraint": constraint, "point": None, "point_basis": None,
                  "status": "connected"}
            if ref is None:
                ep["status"] = "unconnected"
                resolved = False
                _issue(unknowns, "unconnected_endpoint",
                       "%s 끝이 도형에 붙어 있지 않음(미확인 끝점)" % end, c.cell_id, local_id, end)
                if point_key in geom and o is not None:
                    ep["point"] = [_clean_number(ox + geom[point_key][0]),
                                   _clean_number(oy + geom[point_key][1])]
                    ep["point_basis"] = "geometry_point"
            elif ref not in by_id:
                ep["status"] = "invalid_reference"
                resolved = False
                _issue(blockers, "missing_reference", "%s %r 가 존재하지 않음" % (end, ref),
                       c.cell_id, local_id, end)
            elif not local_of.get(ref, "").startswith("local-node-"):
                ep["status"] = "not_a_node"
                resolved = False
                _issue(unknowns, "endpoint_not_node",
                       "%s %r 가 노드가 아님(제외·텍스트·커넥터 등)" % (end, ref),
                       c.cell_id, local_id, end)
            else:
                ep["node_local_id"] = local_of[ref]
            if ep["point"] is None and ref in boxes:
                bx, by, bw, bh = boxes[ref]["bbox"]
                if constraint is not None:
                    ep["point"] = [_clean_number(bx + constraint["x"] * bw + constraint["dx"]),
                                   _clean_number(by + constraint["y"] * bh + constraint["dy"])]
                    ep["point_basis"] = "constraint"
                else:
                    ep["point"] = [_clean_number(bx + bw / 2.0), _clean_number(by + bh / 2.0)]
                    ep["point_basis"] = "terminal_center_approx"
            endpoints.append(ep)

        waypoints = ([[_clean_number(ox + p[0]), _clean_number(oy + p[1])] for p in geom.get("points", [])]
                     if o is not None else [])
        fd_raw = c.user_attrs.get("flow_direction")
        flow = None
        if fd_raw in rules.FLOW_DIRECTION_VALUES:
            flow = {"from": endpoints[0]["node_local_id"], "to": endpoints[1]["node_local_id"],
                    "from_end": "source", "to_end": "target", "basis": fd_raw}
        elif fd_raw:
            _issue(unknowns, "invalid_flow_direction", "규칙에 없는 값 %r" % fd_raw,
                   c.cell_id, local_id, "flow_direction")
        elif rel_kind in rules.RELATION_KINDS_WITH_FLOW:
            _issue(unknowns, "unknown_flow_direction", "원본에 흐름 방향 지정 없음",
                   c.cell_id, local_id, "flow_direction")

        pts = [ep["point"] for ep in endpoints if ep["point"] is not None] + waypoints
        record = {
            "local_id": local_id,
            "source_object_id": c.cell_id,
            "kind": rel_kind,
            "line_type": line_type,
            "line_no": c.user_attrs.get("line_no"),
            "endpoints": endpoints,
            "flow_direction": flow,
            "waypoints": waypoints,
            "label": c.label,
            "label_text": c.text,
            "label_cells": labels_of_edge.pop(c.cell_id, []),
            "attributes": dict(c.user_attrs),
            "style": c.style,
            "parent": c.parent,
            "geometry": c.raw_geo,
            "_pts": pts,
            "_approx_path": approx_path,
        }
        (relations if resolved else unresolved).append(record)

    # 부모 커넥터가 추출 대상이 아닌(제외 등) 커넥터 라벨은 미분류로 남긴다.
    for parent_id, labels in sorted(labels_of_edge.items()):
        for lab in labels:
            unclassified_out.append({"source_object_id": lab["source_object_id"],
                                     "label_text": lab["text"], "attributes": lab["attributes"],
                                     "style": lab["style"], "parent": parent_id,
                                     "geometry": lab["geometry"]})
            _issue(unknowns, "unclassified_element", "추출 대상이 아닌 커넥터 %r 의 라벨" % parent_id,
                   lab["source_object_id"])

    # 원본 좌표 (단계 간 규격의 source_locations)
    source_locations = []
    for rec in node_out + text_out:
        info = boxes.get(rec["source_object_id"])
        if info is not None:
            loc = {"object_id": rec["source_object_id"], "local_id": rec["local_id"],
                   "coordinate_space": COORDINATE_SPACE, "unit": UNIT,
                   "bbox": _bbox(*info["bbox"]), "approximate": info["approximate"]}
            if info["approximate"]:
                loc["method"] = info["reason"]
            source_locations.append(loc)
    for rec in relations + unresolved:
        pts = rec.pop("_pts")
        approx_path = rec.pop("_approx_path")
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            source_locations.append({
                "object_id": rec["source_object_id"], "local_id": rec["local_id"],
                "coordinate_space": COORDINATE_SPACE, "unit": UNIT,
                "bbox": _bbox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)),
                "approximate": True,
                "method": "endpoints_and_waypoints" + ("; parent_offset_approx" if approx_path else "")})

    title_block = _title_block(ignored, boxes)
    drawing = {"page_width": None, "page_height": None, "title_block": title_block}
    for key, field in rules.TITLE_BLOCK_FIELDS.items():
        drawing[field] = title_block[key]["value"] if key in title_block else None
    if drawing["drawing_number"] is None:
        _issue(unknowns, "missing_drawing_number", "표제란에서 DWG NO.를 찾지 못함",
               field="drawing_number")
    for key, field in (("pageWidth", "page_width"), ("pageHeight", "page_height")):
        v = _to_float(model.get(key))
        drawing[field] = _clean_number(v) if v is not None else None
    drawing["ignored_objects"] = [
        {"source_object_id": c.cell_id, "label_text": c.text,
         "bbox": _bbox(*boxes[c.cell_id]["bbox"]) if c.cell_id in boxes else None}
        for c in ignored]

    sha = hashlib.sha256(raw).hexdigest()
    reg = registration or {}
    if registration is None:
        # 등록정보 없이 실행하면 식별 정보가 비어 있음을 미확인으로 남긴다.
        for field in ("project_id", "material_id", "registration_version"):
            _issue(unknowns, "not_registered", "자료 등록 단계 미연동으로 %s 없음" % field, field=field)
    else:
        if reg.get("sha256") != sha:
            _issue(blockers, "registration_hash_mismatch", "입력 파일 해시가 등록정보의 sha256과 다름",
                   field="sha256")
        # 추출한 페이지가 등록정보의 문서·페이지 목록에 있어야 한다(id 없는 페이지는 등록 규칙과 같이 page-<번호>).
        registered_pages = [pid for d in reg.get("documents") or [] for pid in d.get("page_ids") or []]
        if (page_id or "page-%d" % (page + 1)) not in registered_pages:
            _issue(blockers, "registration_page_mismatch", "추출한 페이지 %r 가 등록정보 page_ids %r 에 없음"
                   % (page_id, registered_pages), field="page_id")
        for u in reg.get("validation", {}).get("unknowns", []):
            _issue(unknowns, "registration_unknown", "등록 단계 미확인: %s" % u["reason"], field=u["field"])
    run_id = "extract-%s-p%d-%s-%s" % (drawing["drawing_number"] or page_name or "page", page,
                                       rules.RULES_VERSION, sha[:12])
    if registration is not None:
        run_id += "-%s-r%s" % (reg.get("material_id"), reg.get("registration_version"))
    rel_path = os.path.relpath(path, repo_root).replace("\\", "/") if repo_root else path
    result = {
        "schema_version": SCHEMA_VERSION,
        "project_id": reg.get("project_id"),
        "extraction_run_id": run_id,
        "run": {"script": SCRIPT_NAME, "script_version": SCRIPT_VERSION,
                "rules_version": rules.RULES_VERSION, "scope": "full",
                "settings": {"page_index": page}},
        "source": {"material_id": reg.get("material_id"), "registration_version": reg.get("registration_version"),
                   "format": "drawio",
                   "file": rel_path, "sha256": sha, "compressed": compressed,
                   "page_count": len(pages)},
        "source_context": {"document_id": (reg.get("documents") or [{}])[0].get("document_id"),
                           "page_id": page_id, "page_name": page_name},
        "review_status": "not_reviewed",
        "drawing": drawing,
        "coordinate_system": {"coordinate_space": COORDINATE_SPACE, "unit": UNIT,
                              "origin": "drawio 페이지 원점, x 오른쪽·y 아래쪽 증가",
                              "svg_alignment": None},
        "nodes": node_out,
        "relations": relations,
        "unresolved_connectors": unresolved,
        "texts": text_out,
        "unclassified": unclassified_out,
        "source_locations": source_locations,
        "validation": {"status": "blocked" if blockers else "passed",
                       "blockers": blockers, "unknowns": unknowns},
    }
    result["summary"] = summarize(result)
    return result


def summarize(result):
    counts = {}
    for item in result["validation"]["blockers"] + result["validation"]["unknowns"]:
        counts[item["check"]] = counts.get(item["check"], 0) + 1
    by_kind = {}
    for r in result["relations"]:
        by_kind[str(r["kind"])] = by_kind.get(str(r["kind"]), 0) + 1
    return {
        "nodes": len(result["nodes"]),
        "nodes_unclassified": sum(1 for n in result["nodes"]
                                  if n["classification"] == "unclassified"),
        "relations": len(result["relations"]),
        "relations_by_kind": by_kind,
        "unresolved_connectors": len(result["unresolved_connectors"]),
        "texts": len(result["texts"]),
        "unclassified_elements": len(result["unclassified"]),
        "edge_label_cells": sum(len(r["label_cells"]) for r in
                                result["relations"] + result["unresolved_connectors"]),
        "ignored_objects": len(result["drawing"]["ignored_objects"]),
        "blockers": len(result["validation"]["blockers"]),
        "unknowns": len(result["validation"]["unknowns"]),
        "issue_counts": counts,
    }
