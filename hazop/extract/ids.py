"""추출 결과의 구성요소 id(source_object_id)가 다시 추출하면 바뀔 수 있는 순번인지를 정한다.

- "sequence": 어댑터가 열거 순서로 매긴 id(벡터 PDF `pdf-p<쪽>-sym-0012`, 스캔·그림 `img-sym-0012`).
  같은 도면을 다시 추출해 기호가 하나 늘거나 줄면 뒤의 번호가 밀려 같은 id가 다른 기호를 가리킬 수 있다.
- "source": 원본이 준 id(drawio 셀 id, DEXPI 개체 id)나 연산에 묶인 id(사람이 더한 `manual-<op>`, 나누기 `pdf-p0-split-<op>`).
  다시 추출해도 같은 기호를 가리킨다.

판단 근거는 추출 쪽 사실(어댑터가 쓴 source.format과 어댑터가 id를 만드는 꼴)이다. id 글자 꼴 정규식은
추출 형식을 알 수 없는 옛 그래프의 마지막 단계에서만 쓴다(drawio 셀 id는 어떤 글자 꼴이든 될 수 있어 글자만으로는 정할 수 없다).
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
# 나누기가 만드는 id의 머리 `pdf-p<쪽>-split-<op>`. 스캔 추출은 `pdf-p0-`를 `img-`로 바꾸므로 `img-split-`도 같다
SPLIT_RE = re.compile(r"^(?:pdf-p\d+|img)-split-")

# 어댑터가 쓰는 source.format. 벡터 PDF와 스캔·그림은 순번 id, drawio·DEXPI는 원본 id
FIXED_FORMATS = ("drawio", "dexpi")
SEQUENCE_FORMATS = ("pdf_vector", "raster", "raster_png", "raster_jpeg")
# 옛 판의 스캔 추출 결과(hazop/shell/api.py SCAN_FORMATS)
LEGACY_SEQUENCE_FORMATS = ("raster_scan_pdf", "png", "jpeg")

# 마지막 단계: 추출 형식을 알 수 없는 옛 그래프에서만 id 글자 꼴로 짐작한다
_SEQUENCE_SHAPE = (re.compile(r"^pdf-p\d+-[a-z]+-\d+$"), re.compile(r"^img-[a-z]+-\d+$"))


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


def shape_basis(soid):
    """id 글자 꼴로 짐작(마지막 단계). 순번 꼴이 아니면 SOURCE."""
    s = soid or ""
    return SEQUENCE if any(r.match(s) for r in _SEQUENCE_SHAPE) else SOURCE


def basis(fmt, soid):
    """(추출 source.format, source_object_id) -> "sequence" | "source".
    연산 id(manual-·split-)는 형식과 무관하게 고정. 형식을 모르면 글자 꼴로 짐작한다."""
    if is_operation_id(soid):
        return SOURCE
    by_format = format_basis(fmt)
    return by_format if by_format is not None else shape_basis(soid)


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
    src = (graph or {}).get("source") or {}
    ref = src.get("extraction_file")
    if not isinstance(ref, str) or not ref:
        return None
    from hazop import paths
    try:
        path = paths.resolve_rel(ref, work_root or paths.work_root())
    except (OSError, ValueError, RuntimeError):
        return None
    return _read_format(path) if path else None


def node_basis(node, graph=None, fmt=None):
    """그래프 노드의 id_basis. 노드에 적힌 값이 먼저, 없는 옛 그래프는 추출 형식(fmt, 없으면 graph_format = 추출 파일)에서, 그것도 모르면 글자 꼴로."""
    own = (node or {}).get("id_basis")
    if own in BASES:
        return own
    soid = (node or {}).get("source_object_id")
    return basis(fmt if fmt is not None else graph_format(graph), soid)
