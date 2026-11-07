"""등록 대상 파일의 형식 확인과 표제란 자동 후보 읽기.

근거: 기획서/자료등록.md(MVP 등록 절차 2, 입력과 등록정보, 처리 원칙 1). 등록 형식은 draw.io(.drawio)와
벡터 PDF(.pdf)다(사용자 결정 2026-11-06, 이미지는 제외). PDF는 pdfplumber로 쪽 수를 읽고 표제란 후보를
PDF 어댑터(hazop/extract/adapters/pdf_vector)의 표제란 판독으로 얻는다.
draw.io는 도면 객체를 추출하지 않는다. PDF는 표제란 판독을 위해 첫 쪽을 분석하되 결과는 후보로만 쓴다. 표제란(pidIgnore 셀) 값은 '자동 후보'로만 돌려주며 확정값으로 쓰지 않는다
(사용자 결정 2026-11-04).
"""

import os
import xml.etree.ElementTree as ET

from hazop.extract import drawio, rules

DRAWIO_EXTENSIONS = (".drawio",)
PDF_EXTENSIONS = (".pdf",)
# P&ID 등록 대상 확장자 -> 기대하는 실제 형식(자료 종류별 표는 파일 끝 MATERIAL_FORMATS)
EXPECTED_FORMAT = dict([(e, "drawio") for e in DRAWIO_EXTENSIONS] + [(e, "pdf") for e in PDF_EXTENSIONS])
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
    # XML 여부는 파서로 판정한다(UTF-8·UTF-16 BOM 등 인코딩 감지는 파서에 맡김).
    try:
        root = ET.fromstring(data)
    except Exception:  # ParseError, 알 수 없는 인코딩(LookupError) 등 파서 예외는 모두 읽기 실패로 판정
        head = data.lstrip(b"\xef\xbb\xbf \t\r\n")
        looks_xml = head.startswith(b"<") or data.startswith((b"\xff\xfe", b"\xfe\xff"))
        return "broken_xml" if looks_xml else "unknown"
    return "drawio" if root.tag in ("mxfile", "mxGraphModel") else "xml"


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
            x, y = drawio._to_float(geo.get("x", 0)), drawio._to_float(geo.get("y", 0))
            if x is None or y is None:  # 숫자가 아니거나 NaN·Infinity
                raise ValueError("표제란 셀 %r 좌표를 읽을 수 없음: x=%r y=%r"
                                 % (el.get("id"), geo.get("x"), geo.get("y")))
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


def _inspect_pdf(path, data, info):
    """PDF: 쪽 목록(page-<번호>)과 첫 쪽 표제란 자동 후보. 추출과 같은 읽기(pdf_vector)를 쓰며, 분석 결과는
    pdf_vector.analyze_bytes가 기억해 등록·추출 때 같은 쪽을 다시 분석하지 않는다."""
    try:
        from hazop.extract.adapters import pdf_vector
        sha, page_count, width, height, analysis = pdf_vector.analyze_bytes(data, 0)
        res = pdf_vector.build_extraction(analysis, width, height, page_count, 0, os.path.basename(path), sha)
    except ImportError:
        info["blockers"].append(_problem("unreadable", "PDF를 읽을 pdfplumber가 없음"))
        return
    except Exception as exc:  # 손상·암호화 등 모든 읽기 실패를 사유로 남긴다
        info["blockers"].append(_problem("unreadable", "PDF를 읽을 수 없음: %s" % exc))
        return
    for b in res["validation"]["blockers"]:
        if b["check"] == "no_vector_content":  # 스캔 PDF 등 이미지만 있는 PDF는 등록하지 않는다(이미지 제외 결정)
            info["blockers"].append(_problem("no_vector_content", b["reason"]))
            return
    info["pages"] = [{"page_id": "page-%d" % i, "page_name": None, "compressed": False}
                     for i in range(1, page_count + 1)]
    for key, field in CANDIDATE_FIELDS.items():
        cell = res["drawing"]["title_block"].get(key)
        if cell and cell.get("value"):
            info["auto_candidates"][field] = {"value": cell["value"], "source": "title_block", "page_id": "page-1",
                                              "key_object_id": cell.get("key_object_id"),
                                              "value_object_id": cell.get("value_object_id")}


def _inspect_text_pdf(path, data, info):
    """설계 문서 PDF: 쪽마다 글자를 읽을 수 있는지(hazop.kg.docextract.read_pages, 추출과 같은 읽기)와 쪽 목록.
    벡터 도면 분석(pdf_vector)·표제란 후보는 하지 않는다(글 문서에는 도면이 없음)."""
    from hazop.kg import docextract
    try:
        pages = docextract.read_pages(data)
    except docextract.DocExtractError as exc:
        info["blockers"].append(_problem("unreadable", str(exc)))
        return
    if not any(line.strip() for _, lines in pages for line in lines):
        info["blockers"].append(_problem("no_text_content", "글자가 없는 PDF(스캔 문서)는 지원하지 않음 — OCR 없음"))
        return
    info["pages"] = [{"page_id": "page-%d" % i, "page_name": None, "compressed": False} for i, _ in pages]


def inspect(path, data, material_type="P&ID"):
    """확장자·실제 형식·drawio/PDF 읽기·페이지 목록 확인. 허용 형식과 PDF 읽기는 자료 종류별(MATERIAL_FORMATS).

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
    kind = MATERIAL_FORMATS[material_type]
    expected = kind["formats"].get(ext)
    if expected is None:
        blockers.append(_problem("unsupported_extension", "확장자 %r 는 %s 등록 대상(%s)이 아님"
                                 % (ext, material_type, "·".join(kind["formats"]))))
    if actual not in ("drawio", "pdf"):
        if expected == "drawio" and actual in ("broken_xml", "unknown"):
            blockers.append(_problem("unreadable", "draw.io XML로 읽을 수 없음(손상 또는 알 수 없는 형식: %s)"
                                     % actual))
        elif expected is not None:
            blockers.append(_problem("format_mismatch", "확장자는 %s인데 실제 형식은 %s" % (ext, actual)))
        return info
    if expected != actual:
        blockers.append(_problem("format_mismatch", "실제 형식은 %s인데 확장자가 %r" % (actual, ext)))
        return info
    if actual == "pdf":
        kind["pdf"](path, data, info)
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
    ids = [p["page_id"] for p in info["pages"]]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        # 실제 ID끼리 또는 대체 ID(page-<번호>)와 실제 ID가 겹치면 페이지를 하나로 지목할 수 없다.
        blockers.append(_problem("duplicate_page_id", "페이지 ID 중복(대체 ID page-<번호> 포함): %s" % dup,
                                 "page_ids"))
    info["compressed"] = any(p["compressed"] for p in info["pages"])
    try:
        info["auto_candidates"] = _title_block_candidates(pages)
    except ValueError as exc:
        blockers.append(_problem("invalid_number", str(exc)))
    return info


# 자료 종류 -> 허용 확장자(기대 형식)와 PDF 읽기 함수. registry.MATERIAL_TYPES는 이 표의 키다.
MATERIAL_FORMATS = {
    "P&ID": {"formats": EXPECTED_FORMAT, "pdf": _inspect_pdf},
    "design_document": {"formats": {e: "pdf" for e in PDF_EXTENSIONS}, "pdf": _inspect_text_pdf},
}
