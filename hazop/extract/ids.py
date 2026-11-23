"""추출 결과의 구성요소 id(source_object_id)가 다시 추출하면 바뀔 수 있는 순번인지를 정한다.

- "sequence": 어댑터가 열거 순서로 매긴 id(벡터 PDF `pdf-p<쪽>-sym-0012`, 스캔·그림 `img-sym-0012`).
  같은 도면을 다시 추출해 기호가 하나 늘거나 줄면 뒤의 번호가 밀려 같은 id가 다른 기호를 가리킬 수 있다.
- "source": 원본 파일이 준 id(drawio 셀 id, 파일에 적힌 DEXPI 개체 id)나 연산에 묶인 id(사람이 더한 `manual-<op>`,
  나누기 `pdf-p0-split-<op>`, 만드는 곳은 pdf_vector.build_extraction). 다시 추출해도 같은 기호를 가리킨다.

판단 근거는 추출 쪽 사실이다. 어댑터가 쓴 source.format, 그리고 DEXPI 가져오기가 '파일에 없어서 어댑터가 지은 id'(Proteus Connection의
`<구간>__Connection_<n>`, 쪼갠 조각 `<id>_<n>`, ID 없는 부품·객체의 경로 id 등. 문서 안 순서에서 나오므로 파일을 고치면 밀린다)를
표시한 것을 읽는다. 형식을 모르면 id를 믿지 않고 sequence로 둔다(위치로 다시 확인하는 쪽이 안전하다).
그래프 노드에 `id_basis`로 적는 값은 추출 결과에서만 유도되므로 graph_version을 바꾸지 않는다.
"""

import json
import os
import re

SEQUENCE = "sequence"
SOURCE = "source"
BASES = (SEQUENCE, SOURCE)

# corrections.py가 사람이 더한 노드·관계에 붙이는 머리(add_node·add_relation의 id = 머리 + op_id)
MANUAL_PREFIX = "manual-"
# 나누기가 만드는 id의 머리 `pdf-p<쪽>-split-<op>`. 스캔 추출은 `pdf-p0-`를 `img-`로 바꾸므로 `img-split-`도 같다.
# 연산 id이므로 형식과 무관하게 고정으로 본다
SPLIT_RE = re.compile(r"^(?:pdf-p\d+|img)-split-")

# 어댑터가 쓰는 source.format. 벡터 PDF와 스캔·그림은 순번 id, drawio·DEXPI는 파일에 있던 id
# (DEXPI는 어댑터가 지은 id가 섞이므로 그것만 basis()의 made로 sequence가 된다)
FIXED_FORMATS = ("drawio", "dexpi")
SEQUENCE_FORMATS = ("pdf_vector", "raster", "raster_png", "raster_jpeg")
# 옛 판의 스캔 추출 결과(hazop/shell/api.py SCAN_FORMATS)
LEGACY_SEQUENCE_FORMATS = ("raster_scan_pdf", "png", "jpeg")

# DEXPI 가져오기가 ID 없는 부품에 경로 id를 지을 때 남기는 미확인 항목(dexpi_read.py). source_object_id가 지은 id다
DEXPI_ITEM_WITHOUT_ID = "dexpi_item_without_id"
# DEXPI 가져오기가 Proteus 파일에 적는 run.dexpi.flavor(dexpi_read.FMT_PROTEUS)
PROTEUS_FLAVOR = "proteus"
# 가져오기가 관계 id를 지었을 때 그 관계 기록에 적는 열쇠(dexpi_import.add_relation)
MADE_KEY = "id_made"


def is_operation_id(soid):
    """사람 수정·나누기 연산이 만든 id인가(어느 형식의 추출 위에서도 연산에 묶여 고정)."""
    s = soid or ""
    return s.startswith(MANUAL_PREFIX) or bool(SPLIT_RE.match(s))


def format_basis(fmt):
    """추출 형식 -> SEQUENCE | SOURCE | None(모르는 형식)."""
    f = str(fmt or "").strip().lower()
    if f in FIXED_FORMATS:
        return SOURCE
    if f in SEQUENCE_FORMATS or f in LEGACY_SEQUENCE_FORMATS or f.startswith("pdf"):
        return SEQUENCE
    return None


def made_ids(extraction):
    """DEXPI 추출에서 어댑터가 지은 id를 추출 결과에서 읽어 낸 집합.
    - 파일에 ID가 없는 부품의 경로 id: 미확인 항목 dexpi_item_without_id의 source_object_id.
    - Proteus 파일의 물리 연결(Connection): Proteus Connection에는 ID가 없어 id가 전부 지은 것이다(`<구간>__Connection_<n>`, 쪼갠 조각 `<..>_<n>`).
      추출 결과를 더하지 않으려고 run.dexpi.flavor로 읽는다(graph_version이 그대로다).
    그 밖의 지은 id(DEXPI 2.0의 ID 없는 연결·쪼갠 조각·측정선·신호선)는 가져오기가 관계 기록에 id_made를 적는다. 노드는 evidence.dexpi.id가 None."""
    ext = extraction if isinstance(extraction, dict) else {}
    unknowns = (ext.get("validation") or {}).get("unknowns")
    out = {u.get("source_object_id") for u in unknowns or ()
           if isinstance(u, dict) and u.get("check") == DEXPI_ITEM_WITHOUT_ID and u.get("source_object_id")}
    flavor = ((ext.get("run") or {}).get("dexpi") or {}).get("flavor")
    if flavor == PROTEUS_FLAVOR:
        for r in list(ext.get("relations") or ()) + list(ext.get("unresolved_connectors") or ()):
            if isinstance(r, dict) and r.get("kind") == "physical_connection" and r.get("source_object_id"):
                out.add(r["source_object_id"])
    return out


def is_made(rec, made=()):
    """추출 노드·관계의 source_object_id를 어댑터가 지었는가(파일에 있던 id가 아닌가). 가져오기 코드가 이미 가진 사실만 읽는다.
    노드: evidence.dexpi.id가 None(파일에 id 없음) 또는 made 집합에 있음. 관계: 가져오기가 적은 id_made."""
    if not isinstance(rec, dict):
        return False
    if rec.get(MADE_KEY) is True:
        return True
    dexpi = (rec.get("evidence") or {}).get("dexpi") if isinstance(rec.get("evidence"), dict) else None
    if isinstance(dexpi, dict) and "id" in dexpi and dexpi["id"] is None:
        return True
    return rec.get("source_object_id") in made


def basis(fmt, soid, made=False):
    """(추출 source.format, source_object_id, 어댑터가 지은 id인가) -> "sequence" | "source".
    연산 id(manual-·split-)는 형식과 무관하게 고정. 어댑터가 지은 id는 형식과 무관하게 순번. 형식을 모르면 순번(안전한 쪽)."""
    if is_operation_id(soid):
        return SOURCE
    if made:
        return SEQUENCE
    by_format = format_basis(fmt)
    return by_format if by_format is not None else SEQUENCE


_FORMAT_CACHE = {}


def _read_format(path):
    """추출 결과 파일의 source.format. 읽을 수 없으면 None. (시각, 크기)가 같으면 다시 읽지 않는다."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _FORMAT_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            fmt = (json.load(fh).get("source") or {}).get("format")
    except (OSError, ValueError, AttributeError):
        return None
    _FORMAT_CACHE[path] = (key, fmt)
    return fmt


def graph_format(graph, work_root=None):
    """그래프를 만든 추출의 source.format. 그래프 머리 source.extraction_file이 가리키는 추출 파일에서 읽고, 못 읽으면 None."""
    src = graph.get("source") if isinstance(graph, dict) else None
    ref = src.get("extraction_file") if isinstance(src, dict) else None
    if not isinstance(ref, str) or not ref:
        return None
    from hazop import paths
    try:
        path = paths.resolve_rel(ref, work_root or paths.work_root())
    except (OSError, ValueError, RuntimeError):
        return None
    return _read_format(path) if path else None


def node_basis(node, graph=None, fmt=None):
    """그래프 노드의 id_basis. 노드에 적힌 값이 먼저, 없는 옛 그래프는 추출 형식(fmt, 없으면 graph_format = 추출 파일)에서,
    그것도 모르면 sequence. graph는 그 노드가 나온 도면(시트) 그래프여야 한다(프로젝트 그래프 머리에는 추출 파일이 없다)."""
    node = node if isinstance(node, dict) else {}
    own = node.get("id_basis")
    if own in BASES:
        return own
    return basis(fmt if fmt is not None else graph_format(graph), node.get("source_object_id"))
