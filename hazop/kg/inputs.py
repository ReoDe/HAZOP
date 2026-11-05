"""지식 입력: 사람이 쓴 CSV 2개 -> knowledge.json (정규화한 지식 입력, 계약).

근거: 기획서/그래프활용.md §2.6 입력 형식, §2.4 근거 필드, §3.2 mentions 반영 열.
- CSV는 UTF-8(BOM 허용). 파일 머리의 '#'로 시작하는 줄은 주석(가상 자료 고지 등)으로 건너뛴다.
- 빈 칸은 null(미확인)로 읽고 0이나 "없음"으로 바꾸지 않는다. 값은 쓴 그대로 문자열로 두며 단위·압력 기준을 추정하지 않는다.
- 이 단계는 형식만 바꾼다. 종류·참조·근거 검사는 지식 빌더(hazop.kg.build)가 한다.
- 행 순서는 입력 순서를 그대로 둔다(같은 입력이면 같은 결과).
"""

import csv
import hashlib
import io
import re
import unicodedata

SCHEMA_VERSION = "0.1"

NODE_COLUMNS = ("id", "node_type", "name", "text", "item", "value", "unit", "pressure_basis", "operating_mode",
                "material_id", "registration_version", "document_id", "page", "locator",
                "knowledge_status", "author", "reason")
SOURCE_COLUMNS = ("material_id", "registration_version", "document_id", "page", "locator")
MENTION_COLUMNS = ("candidate_key", "chunk_id", "text_sha256", "graph_version", "target_source_object_id")
LINK_COLUMNS = ("id", "kind", "from", "to", "method", "knowledge_status", "link_status") + SOURCE_COLUMNS + \
               ("author", "reviewed_by", "reviewed_at", "reason") + MENTION_COLUMNS
CANDIDATE_KEY_FIELDS = ("chunk_id", "text_sha256", "material_id", "registration_version", "match_start", "match_end",
                        "target_graph_id", "target_graph_version", "target_ref", "target_source_object_id")
NODE_VALUE_FIELDS = ("name", "text", "item", "value", "unit", "pressure_basis", "operating_mode")
BLANK_REASON = "입력 빈 칸(미확인)"
UNREGISTERED_REASON = "자료 등록 정보 없음(material_id 빈 칸)"


def normalize_text(text):
    """조각 원문 정규화(text_sha256용) [가정]: Unicode NFC, 연속 공백(줄바꿈 포함)을 공백 1개로, 앞뒤 공백 제거."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def text_sha256(text):
    """조각 원문 해시. 원문이 없으면 None."""
    if text is None:
        return None
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _cell(v):
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def read_csv(path, columns):
    """CSV -> 행 dict 목록(빈 칸 None). 열 이름이 규격과 다르면 ValueError(빠진 열·모르는 열)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        lines = fh.read().splitlines(keepends=True)
    start = 0  # 머리글 이전의 '#' 주석 줄과 빈 줄만 건너뛴다(본문 따옴표 셀 안의 '#' 줄은 원문 그대로)
    while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith("#")):
        start += 1
    reader = csv.DictReader(io.StringIO("".join(lines[start:])))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in columns if c not in header]
    extra = [h for h in header if h not in columns]
    if missing or extra or len(set(header)) != len(header):
        raise ValueError("%s: 열 규격 불일치(빠진 열 %s, 모르는 열 %s, 중복 열 %s)"
                         % (path, missing, extra, sorted({h for h in header if header.count(h) > 1})))
    rows = []
    for raw in reader:
        row = {k.strip(): _cell(v) for k, v in raw.items() if k is not None}
        if None in raw and any(_cell(v) for v in raw[None]):
            raise ValueError("%s %d행: 열 수가 머리글보다 많음" % (path, reader.line_num))
        if all(row.get(c) is None for c in columns):
            continue  # 완전히 빈 행
        rows.append({c: row.get(c) for c in columns})
    return rows


def _source(row):
    """근거 열 -> source. 자료 등록 정보(material_id)가 비면 unregistered_reason에 사유를 남긴다(§2.4)."""
    src = {c: row[c] for c in SOURCE_COLUMNS}
    src["unregistered_reason"] = None if row["material_id"] is not None else UNREGISTERED_REASON
    return src


def _null_reasons(row, fields):
    return {f: BLANK_REASON for f in fields if row.get(f) is None}


def node_record(row):
    rec = {"id": row["id"], "node_type": row["node_type"]}
    rec.update({f: row[f] for f in NODE_VALUE_FIELDS})
    rec["source"] = _source(row)
    rec.update({"method": "manual", "extractor": None, "confidence": None,
                "knowledge_status": row["knowledge_status"], "author": row["author"], "reason": row["reason"]})
    rec["null_reasons"] = _null_reasons(row, NODE_VALUE_FIELDS + SOURCE_COLUMNS)
    return rec


def candidate_fields(candidate_key):
    """candidate_key -> {필드: 문자열}. 형식이 맞지 않으면 None.
    키 직렬화 [가정]: §3.2 후보 키 10개 값을 '|'로 이음(chunk_id|text_sha256|material_id|registration_version|
    match_start|match_end|target_graph_id|target_graph_version|target_ref|target_source_object_id)."""
    parts = (candidate_key or "").split("|")
    if len(parts) != len(CANDIDATE_KEY_FIELDS):
        return None
    return dict(zip(CANDIDATE_KEY_FIELDS, parts))


def candidate_match(candidate_key):
    """candidate_key -> (match_start, match_end) 정수. 형식이 맞지 않거나 0 <= start < end가 아니면 (None, None).
    위치는 normalize_text(조각 원문) 기준의 문자(코드 포인트) 오프셋이다(text_sha256과 같은 정규화). 원문 길이 대조는 빌더가 한다."""
    f = candidate_fields(candidate_key)
    if f is None:
        return None, None
    try:
        start, end = int(f["match_start"]), int(f["match_end"])
    except ValueError:
        return None, None
    return (start, end) if 0 <= start < end else (None, None)


def normalize_tag(s):
    """태그 비교용 정규화(§3.1 2단계): normalize_text 후 하이픈 변형(‐ ‑ ‒ – — ―)을 '-'로, 대소문자 무시."""
    return re.sub("[\u2010-\u2015]", "-", normalize_text(s)).casefold()


def mention_record(row):
    rec = {c: row[c] for c in ("candidate_key", "chunk_id", "text_sha256", "material_id", "registration_version",
                               "graph_version", "target_source_object_id")}
    rec["match_start"], rec["match_end"] = candidate_match(row["candidate_key"])
    return rec


def link_record(row):
    rec = {"id": row["id"], "kind": row["kind"], "from": row["from"], "to": row["to"],
           "method": row["method"], "extractor": None, "confidence": None,
           "knowledge_status": row["knowledge_status"], "link_status": row["link_status"],
           "source": _source(row),
           "author": row["author"], "reviewed_by": row["reviewed_by"], "reviewed_at": row["reviewed_at"],
           "reason": row["reason"],
           "mention": mention_record(row) if row["kind"] == "mentions" else None}
    if row["kind"] != "mentions":
        rec["unused_mention_columns"] = [c for c in MENTION_COLUMNS if row[c] is not None]
    return rec


def file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_knowledge(nodes_csv, links_csv, project_id):
    """CSV 2개 -> knowledge dict. 입력 경로는 기록하지 않고 파일 바이트의 sha256만 남긴다
    (같은 CSV를 다른 위치에서 읽어도 같은 결과·같은 kg_version)."""
    nodes = [node_record(r) for r in read_csv(nodes_csv, NODE_COLUMNS)]
    links = [link_record(r) for r in read_csv(links_csv, LINK_COLUMNS)]
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "kg_id": "kg-%s" % project_id,
        "inputs": {"knowledge_nodes_sha256": file_sha256(nodes_csv), "knowledge_links_sha256": file_sha256(links_csv)},
        "nodes": nodes,
        "links": links,
    }
