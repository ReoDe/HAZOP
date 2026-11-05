"""draw.io가 내보낸 SVG와 drawio 좌표의 대응을 측정한다 (② 뷰어 오버레이용).

draw.io SVG 내보내기는 도면 내용의 최소 경계(테두리 포함)를 SVG 원점으로 옮기므로
SVG 좌표 = drawio 좌표 - offset 이다. 각 셀 그룹(data-cell-id)의 첫 <rect>/<ellipse>에
조상 요소들의 transform을 누적 적용해 drawio bbox와 비교하고, 모든 비교 셀에서 offset이 같은지 확인한다.

- 셀 그룹 안의 translate(0.5,0.5)는 선 선명도용 렌더링 보정이므로 제외한다.
- 셀 그룹 바깥(상위)의 translate는 누적 반영한다. 상위에 scale·rotate·matrix 등이 있으면 정렬을 실패로 판정한다.
- 셀 그룹 안의 도형 자체 변환(flip·rotate)은 그 도형에만 적용되므로 해당 셀만 비교에서 제외한다.
"""

import collections
import glob
import os
import re
import xml.etree.ElementTree as ET

SVG_NS = "{http://www.w3.org/2000/svg}"
_TRANSLATE = re.compile(r"^\s*translate\(\s*([-\d.eE+]+)(?:[\s,]+([-\d.eE+]+))?\s*\)\s*$")
RENDER_FIX = (0.5, 0.5)


def _parse_transform(text):
    """translate(a[,b]) -> (a, b). 없으면 (0,0). 지원하지 않는 변환이면 None."""
    if not text or not text.strip():
        return (0.0, 0.0)
    m = _TRANSLATE.match(text)
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2) or 0.0))


def _first_shape(el):
    """셀 그룹 el 안에서(중첩된 다른 셀은 건너뜀) 첫 rect/ellipse와 그 사이 transform 목록."""
    stack = [(child, [child.get("transform")]) for child in reversed(list(el))]
    while stack:
        node, chain = stack.pop()
        if node.get("data-cell-id") is not None:
            continue
        tag = node.tag.replace(SVG_NS, "")
        if tag in ("rect", "ellipse"):
            return node, chain
        if tag == "foreignObject":
            continue
        for child in reversed(list(node)):
            stack.append((child, chain + [child.get("transform")]))
    return None, None


def _safe_page_name(name):
    """페이지 이름(도면 파일 안의 외부 입력)을 파일 이름에 붙여도 되는지. 경로 구분자·'..'·드라이브 문자(':')·제어문자가
    있으면 False(그 규칙을 건너뜀)."""
    if not isinstance(name, str) or not name:
        return False
    if any(c in name for c in ("/", "\\", ":")) or ".." in name:
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in name)


def _inside(folder, path):
    """path가 folder 바로 아래 파일인지(심볼릭 링크 등을 풀어 확인)."""
    return os.path.dirname(os.path.realpath(path)) == os.path.realpath(folder)


def find_svg(drawio_path, page_index=0, page_name=None, page_count=1):
    """draw.io 원본 옆에서 이 페이지의 SVG를 찾는다. 추출(scripts/extract_drawio.py)과 등록(hazop/register)이 같이 쓴다.
    한 페이지 문서: (1) 원본과 같은 이름 <파일명>.svg(예: X.drawio.svg), <stem>.svg(예: X.svg)
                    (2) <NN>_<페이지 이름>.drawio.svg (예: 01_SNP-M-102.drawio.svg)
                    (3) 폴더에 *.drawio.svg가 하나뿐이면 그것(기존 규칙)
    여러 페이지 문서: (2)만. 하나뿐인 SVG를 여러 페이지에 붙이지 않는다.
    페이지 이름이 경로로 해석될 수 있으면(_safe_page_name) (2)를 건너뛴다. 결과는 원본 폴더 안 파일만. 없으면 None."""
    folder = os.path.dirname(drawio_path)
    names = []
    if page_count == 1:
        names += [drawio_path + ".svg", os.path.splitext(drawio_path)[0] + ".svg"]
    if _safe_page_name(page_name):
        names.append(os.path.join(folder, "%02d_%s.drawio.svg" % (page_index + 1, page_name)))
    for path in names:
        if os.path.isfile(path) and _inside(folder, path):
            return path
    if page_count != 1:
        return None
    found = glob.glob(os.path.join(glob.escape(folder), "*.drawio.svg"))
    return found[0] if len(found) == 1 and _inside(folder, found[0]) else None


def align(svg_path, result):
    tree = ET.parse(svg_path)
    root = tree.getroot()
    vb = root.get("viewBox")
    boxes = {loc["object_id"]: loc["bbox"] for loc in result["source_locations"]
             if not loc.get("approximate")}
    for obj in result["drawing"]["ignored_objects"]:
        if obj["bbox"] is not None:
            boxes[obj["source_object_id"]] = obj["bbox"]

    offsets = collections.Counter()
    unsupported = []  # 상위 변환 미지원 -> 정렬 실패
    local_excluded = []  # 셀 내부 flip·rotate -> 비교 제외
    svg_ids = set()

    def visit(el, acc, ok):
        t = _parse_transform(el.get("transform"))
        if t is None:
            ok = False
        else:
            acc = (acc[0] + t[0], acc[1] + t[1])
        cid = el.get("data-cell-id")
        if cid is not None:
            svg_ids.add(cid)
            if cid in boxes:
                compare(cid, el, acc, ok)
        for child in el:
            visit(child, acc, ok)

    def compare(cid, el, acc, ok):
        shape, chain = _first_shape(el)
        if shape is None:
            return
        if not ok:
            unsupported.append(cid)
            return
        ax, ay = acc
        for t_text in chain:
            t = _parse_transform(t_text)
            if t is None:
                local_excluded.append(cid)
                return
            if t != RENDER_FIX:
                ax, ay = ax + t[0], ay + t[1]
        a = shape.attrib
        try:
            if shape.tag.endswith("rect"):
                sx, sy, sw, sh = (float(a["x"]), float(a["y"]), float(a["width"]), float(a["height"]))
            else:
                rx, ry = float(a["rx"]), float(a["ry"])
                sx, sy, sw, sh = float(a["cx"]) - rx, float(a["cy"]) - ry, 2 * rx, 2 * ry
        except (KeyError, ValueError):
            return
        box = boxes[cid]
        if abs(sw - box[2]) > 0.01 or abs(sh - box[3]) > 0.01:
            return  # 모양 내부 요소라 bbox와 크기가 다르면 비교에서 제외
        offsets[(round(box[0] - (sx + ax), 3), round(box[1] - (sy + ay), 3))] += 1

    visit(root, (0.0, 0.0), True)

    expected = {n["source_object_id"] for n in result["nodes"]}
    expected |= {r["source_object_id"] for r in result["relations"] + result["unresolved_connectors"]}
    expected |= {t["source_object_id"] for t in result["texts"]}
    out = {
        "svg_file": None,
        "viewBox": vb,
        "width": root.get("width"),
        "height": root.get("height"),
        "status": "failed",
        "reasons": [],
        "offset": None,
        "transform": "svg_x = drawio_x - offset[0], svg_y = drawio_y - offset[1]",
        "compared_cells": sum(offsets.values()),
        "consistent_cells": 0,
        "inconsistent_offsets": [],
        "unsupported_transform_cells": sorted(unsupported),
        "excluded_local_transform_cells": sorted(local_excluded),
        "cells_missing_in_svg": sorted(expected - svg_ids),
        "note": "셀 그룹 안의 translate(0.5,0.5)는 선 선명도용 렌더링 보정이므로 변환에서 제외했다.",
    }
    if offsets:
        (best, count), = offsets.most_common(1)
        out["offset"] = [best[0], best[1]]
        out["consistent_cells"] = count
        out["inconsistent_offsets"] = [{"offset": list(k), "cells": v}
                                       for k, v in offsets.items() if k != best]
    if not offsets:
        out["reasons"].append("비교 가능한 셀 없음")
    if out["inconsistent_offsets"]:
        out["reasons"].append("셀마다 offset이 다름")
    if unsupported:
        out["reasons"].append("상위 요소에 지원하지 않는 transform(scale·rotate·matrix 등) 있음")
    if out["cells_missing_in_svg"]:
        out["reasons"].append("SVG에 없는 추출 객체 있음")
    if not out["reasons"]:
        out["status"] = "verified"
    return out
