"""시트 정체(sheet identity): 도면 한 장(시트)의 graph_id를 정하는 규칙 한 곳.
근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md.

- 시트의 정체는 사람이 확정한 도면 번호가 있으면 그 번호, 없으면 (자료, 쪽)이다.
  - 자연 이름 natural: 쓸 수 있는 번호가 있으면 `graph-<번호>`, 등록 경로인데 번호가 없으면 `graph-<material_id>-p<쪽, 0부터>`,
    등록을 거치지 않은 추출(표본 실행·검사 스크립트)은 지금처럼 `graph-<쪽 이름|drawing>`.
  - 쓸 수 있는 번호: 사람이 확정한 번호이고 자료가 한 쪽일 때만. 여러 쪽 자료의 자료 단위 번호는 쪽 번호가 아니라서 이름에 쓰지 않는다
    (쪽들이 한 이름으로 겹치므로). 그 사유 코드가 NUMBER_HELD다.
- 자리(seat): 이 규칙 전에 쓰던 이름(graph-drawing, graph-<쪽 이름>, 여러 쪽 자료의 graph-<번호>)을 지금 쓰는 시트가 지키도록
  프로젝트마다 한 번 적는 표(hazop.graph.sources.settle). 번호를 쓸 수 없는 (자료, 쪽)이 legacy 자리를 가지면 그 이름을 쓴다.
- 등록 판(r1, r2)은 이름에 넣지 않는다. 표제란 확정이 새 판을 만들어도 같은 시트로 남는다.
- 정착 전의 프로젝트는 legacy_name(이 규칙 전의 이름) 그대로다.
순수 함수만 둔다(파일을 읽거나 쓰지 않음).
"""

import os
import re

PREFIX = "graph-"
LEGACY, IN_USE, CHOSEN = "legacy", "in_use", "chosen"
SEAT_KINDS = (LEGACY, IN_USE, CHOSEN)
# 사람이 도면 번호로 확정하면 임시 이름과 겹치는 꼴(등록·표제란 입력 검사가 막는다)
RESERVED_NUMBER = re.compile(r"^material-[0-9a-f]{12}-p\d+$", re.IGNORECASE)
_TEMP_NAME = re.compile(r"^graph-material-[0-9a-f]{12}-p\d+$")
UNNUMBERED = "번호 미확정 도면"
_OUT_NAME = re.compile(r"__(material-[0-9a-f]{12})-r(\d+)-p(\d+)$")   # scripts/extract_drawio.registered_out_name 꼬리

NUMBER_HELD = "multi_page_number"
NUMBER_RESERVED = "reserved_number"
CONFIRM_FIRST = "confirm_title_block_first"
TEXTS = {
    NUMBER_HELD: "여러 쪽 자료(%(pages)d쪽)에 자료 하나의 도면 번호 %(number)s가 붙어 있어 쪽 이름에 쓰지 않았습니다. "
                 "쪽을 파일로 나눠 등록하면 쪽마다 번호를 확정할 수 있습니다.",
    NUMBER_RESERVED: "도면 번호 %(number)s는 번호 미확정 도면의 임시 이름(material-…-p쪽)과 같은 꼴이라 쓸 수 없습니다.",
    CONFIRM_FIRST: "도면 번호가 확정되지 않았습니다. 구간을 만들기 전에 표제란을 확정하면 나중에 도면 연결·DEXPI 내보내기·"
                   "개정판 이어 받기를 쓸 수 있습니다.",
}


def facts(extraction):
    """추출 결과 -> 이름을 정하는 데 쓰는 값 {material_id, page_index, page_count, number, page_name, file}.
    등록을 거치지 않은 추출은 material_id가 None이다."""
    src = extraction.get("source") or {}
    ctx = extraction.get("source_context") or {}
    page = ((extraction.get("run") or {}).get("settings") or {}).get("page_index")
    return {"material_id": src.get("material_id"), "page_index": page if isinstance(page, int) else 0,
            "page_count": src.get("page_count") if isinstance(src.get("page_count"), int) else 1,
            "number": (extraction.get("drawing") or {}).get("drawing_number"),
            "page_name": ctx.get("page_name"), "file": os.path.basename(src.get("file") or "") or None}


def from_graph(graph):
    """graph.json -> facts와 같은 꼴. 이 규칙 전에 만든 graph.json은 material_id·page_index·page_count가 없어 None이다
    (sources가 폴더 이름·추출 결과로 채운다)."""
    src = graph.get("source") or {}
    return {"material_id": src.get("material_id"), "page_index": src.get("page_index"), "page_count": src.get("page_count"),
            "number": src["number"] if "number" in src else src.get("drawing_number"), "page_name": src.get("page_name"),
            "file": src.get("file")}


def from_out_name(name):
    """등록 경로 출력 폴더 이름 -> (material_id, 등록 판, 쪽) 또는 None."""
    m = _OUT_NAME.search(name or "")
    return (m.group(1), int(m.group(2)), int(m.group(3))) if m else None


def key(f):
    """시트 정체 (material_id, 쪽). 등록을 거치지 않은 것은 None."""
    return (f["material_id"], f["page_index"] or 0) if f.get("material_id") else None


def usable_number(f):
    """이름에 쓸 수 있는 도면 번호(사람이 확정, 한 쪽 자료) 또는 None."""
    if not f.get("number"):
        return None
    if f.get("material_id") and (f.get("page_count") or 1) > 1:
        return None
    return f["number"]


def number_problem(number, page_count):
    """등록·표제란 확정이 도면 번호를 받기 전에 묻는다. -> None 또는 {"code", "text"}(사용자에게 보이는 사유)."""
    if not number:
        return None
    if RESERVED_NUMBER.match(number):
        return {"code": NUMBER_RESERVED, "text": TEXTS[NUMBER_RESERVED] % {"number": number}}
    if (page_count or 1) > 1:
        return {"code": NUMBER_HELD, "text": TEXTS[NUMBER_HELD] % {"number": number, "pages": page_count}}
    return None


def legacy_name(f):
    """이 규칙 전의 이름(정착하지 않은 프로젝트가 그대로 쓴다)."""
    return PREFIX + (f.get("number") or f.get("page_name") or "drawing")


def natural(f):
    """자리 표를 보지 않은 이름."""
    number = usable_number(f)
    if number:
        return PREFIX + number
    if f.get("material_id"):
        return "%s%s-p%d" % (PREFIX, f["material_id"], f["page_index"] or 0)
    return legacy_name(f)


def sheet_id(f, seats):
    """자리 표(seats {graph_id: {material_id, page, why, …}})를 본 이름. 쓸 수 있는 번호가 없고 이 (자료, 쪽)이 legacy 자리를
    가지면 그 자리 이름, 아니면 natural."""
    k = key(f)
    if k is not None and not usable_number(f):
        for gid, seat in sorted((seats or {}).items()):
            if seat.get("why") == LEGACY and (seat.get("material_id"), seat.get("page") or 0) == k:
                return gid
    return natural(f)


def label(f):
    """사람용 도면 이름: 쓸 수 있는 번호, 없으면 '<원본 파일 이름> · <쪽>쪽'(쪽은 1부터), 등록 밖이면 쪽 이름."""
    number = usable_number(f)
    if number:
        return number
    if f.get("material_id"):
        return "%s · %d쪽" % (f.get("file") or f["material_id"], (f.get("page_index") or 0) + 1)
    return f.get("number") or f.get("page_name") or "drawing"


def is_temp_name(graph_id):
    """번호가 없는 등록 시트의 임시 이름(graph-<material_id>-p<쪽>)인가. 사람에게 보이는 글에 그대로 내지 않는다."""
    return bool(_TEMP_NAME.match(graph_id or ""))


def display_name(sheet):
    """사람용 도면 이름 한 곳. sheet는 프로젝트 그래프 sheets[]의 한 줄({graph_id, drawing_number, label}) 또는 같은 꼴.
    번호, 없으면 label('파일 · n쪽'), 그것도 없으면 graph-를 뗀 이름(임시 이름은 '번호 미확정 도면')."""
    if sheet.get("drawing_number"):
        return sheet["drawing_number"]
    if sheet.get("label"):
        return sheet["label"]
    gid = sheet.get("graph_id") or ""
    if is_temp_name(gid):
        return UNNUMBERED
    return gid[len(PREFIX):] if gid.startswith(PREFIX) else gid or "-"


def describe(f, graph_id=None):
    """도면 목록 한 줄에 쓸 엔진 값 {graph_id, label, drawing_number, number_state, notice}.
    number_state: confirmed(이름에 쓰는 번호), held(번호가 있지만 여러 쪽이라 쓰지 않음), unconfirmed(번호 없음).
    notice: None 또는 {"code", "text"}. 등록 밖 추출은 번호가 없어도 알리지 않는다."""
    number = usable_number(f)
    out = {"graph_id": graph_id, "label": label(f), "drawing_number": number}
    if number:
        return dict(out, number_state="confirmed", notice=None)
    if f.get("number") and f.get("material_id"):
        return dict(out, number_state="held", notice=number_problem(f["number"], f.get("page_count")))
    if f.get("material_id"):
        return dict(out, number_state="unconfirmed", notice={"code": CONFIRM_FIRST, "text": TEXTS[CONFIRM_FIRST]})
    return dict(out, number_state="unconfirmed" if not f.get("number") else "confirmed", notice=None,
                drawing_number=f.get("number"))
