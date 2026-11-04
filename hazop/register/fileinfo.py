"""등록 대상 파일의 형식 확인과 표제란 자동 후보 읽기.

근거: 기획서/자료등록.md(MVP 등록 절차 2, 입력과 등록정보, 처리 원칙 1).
도면 객체는 추출하지 않는다. 표제란(pidIgnore 셀) 값은 '자동 후보'로만 돌려주며 확정값으로 쓰지 않는다
(사용자 결정 2026-11-04).
"""

import os
import xml.etree.ElementTree as ET

from hazop.extract import drawio, rules

DRAWIO_EXTENSIONS = (".drawio",)
# 실제 형식 판별용 파일 시작 바이트
MAGIC = [(b"%PDF", "pdf"), (b"\x89PNG", "png"), (b"\xff\xd8\xff", "jpeg"), (b"PK\x03\x04", "zip")]
# 표제란 키 -> 등록정보 필드 (추출 규칙의 표제란 키를 그대로 쓴다)
CANDIDATE_FIELDS = {key: ("design_revision" if field == "revision" else field)
                    for key, field in rules.TITLE_BLOCK_FIELDS.items()
                    if field in ("drawing_number", "revision", "title")}


def _problem(check, reason, field=None):
    return {"check": check, "field": field, "reason": reason}


def detect_format(data):
    """바이트 내용으로 실제 형식을 판별한다: drawio / xml / broken_xml / pdf / png / jpeg / zip / unknown."""
    for magic, name in MAGIC:
        if data.startswith(magic):
            return name
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<"):
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return "broken_xml"
        return "drawio" if root.tag in ("mxfile", "mxGraphModel") else "xml"
    return "unknown"


def _title_block_candidates(pages):
    """각 페이지의 pidIgnore 셀 중 같은 행 2칸(키·값)을 표제란 쌍으로 읽는다(추출 단계와 같은 배치 가정 [추론]).
    레이어 바로 아래 셀만 본다. 필드별로 처음 찾은 값을 후보로 돌려준다."""
    found = {}
    for page_id, _, model, _ in pages:
        root = model.find("root")
        if root is None:
            continue
        elements = list(root)
        parent_of = {}
        for el in elements:
            cell = el if el.tag == "mxCell" else el.find("mxCell")
            parent_of[el.get("id")] = cell.get("parent") if cell is not None else None
        layers = {i for i, p in parent_of.items() if p in (None, "0")}
        rows = {}
        for el in elements:
            cell = el if el.tag == "mxCell" else el.find("mxCell")
            if cell is None or cell.get("vertex") != "1" or cell.get("parent") not in layers:
                continue
            style = drawio.parse_style(cell.get("style"))
            geo = cell.find("mxGeometry")
            if style.get("pidIgnore") != "1" or geo is None:
                continue
            label = el.get("value") if el.tag == "mxCell" else el.get("label")
            text = drawio.label_to_text(label or "", style)
            try:
                x, y = float(geo.get("x", 0)), float(geo.get("y", 0))
            except ValueError:
                continue
            if text:
                rows.setdefault(round(y), []).append((x, el.get("id"), text))
        for _, items in sorted(rows.items()):
            if len(items) != 2:
                continue
            (_, key_id, key), (_, value_id, value) = sorted(items)
            field = CANDIDATE_FIELDS.get(key)
            if field and field not in found:
                found[field] = {"value": value, "source": "title_block", "page_id": page_id,
                                "key_object_id": key_id, "value_object_id": value_id}
    return found


def inspect(path, data):
    """확장자·실제 형식·drawio 읽기·페이지 목록 확인.

    반환: {"format", "extension", "size_bytes", "pages", "compressed", "auto_candidates", "blockers"}
    blockers가 비어 있지 않으면 등록 완료 금지.
    """
    ext = os.path.splitext(path)[1].lower()
    info = {"format": None, "extension": ext, "size_bytes": len(data), "pages": [],
            "compressed": False, "auto_candidates": {}, "blockers": []}
    blockers = info["blockers"]
    if not data:
        blockers.append(_problem("empty_file", "빈 파일(0바이트)"))
        return info
    actual = detect_format(data)
    info["format"] = actual
    if ext not in DRAWIO_EXTENSIONS:
        blockers.append(_problem("unsupported_extension", "확장자 %r 는 MVP 등록 대상(.drawio)이 아님" % ext))
    if actual != "drawio":
        if ext in DRAWIO_EXTENSIONS:
            if actual in ("broken_xml", "unknown"):
                blockers.append(_problem("unreadable", "draw.io XML로 읽을 수 없음(손상 또는 알 수 없는 형식: %s)"
                                         % actual))
            else:
                blockers.append(_problem("format_mismatch", "확장자는 .drawio인데 실제 형식은 %s" % actual))
        return info
    if ext not in DRAWIO_EXTENSIONS:
        blockers.append(_problem("format_mismatch", "실제 형식은 drawio인데 확장자가 %r" % ext))
        return info
    try:
        pages = drawio.load_pages(data)
    except Exception as exc:  # 압축 해제·XML 오류 등 모든 읽기 실패를 사유로 남긴다
        blockers.append(_problem("unreadable", "draw.io 페이지를 읽을 수 없음: %s" % exc))
        return info
    for i, (page_id, name, model, compressed) in enumerate(pages, 1):
        if model.find("root") is None:
            blockers.append(_problem("unreadable", "페이지 %r 에 root가 없음" % (page_id or i)))
        info["pages"].append({"page_id": page_id or "page-%d" % i, "page_name": name, "compressed": compressed})
    info["compressed"] = any(p["compressed"] for p in info["pages"])
    info["auto_candidates"] = _title_block_candidates(pages)
    return info
