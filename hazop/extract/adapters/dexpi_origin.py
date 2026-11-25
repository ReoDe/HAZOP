"""이 앱이 낸 DEXPI 파일에 실은 원래 값 표시를 읽고 검사한다(HZ-PLN-22 §6.9). 쓰기는 hazop.export.dexpi_marks.

표시는 파일이 정의한 클래스 `HazopOrigin`의 Object이고 Model 바로 아래에 있다. 대상은 References #id, 값은 글자 칸이다.
비밀 열쇠가 없어 위조를 막지는 못한다. 검사는 표시가 바꿀 수 있는 것을 파일의 표준 값이 허용하는 범위로 묶는다. 어긋난 칸만 버린다.
"""

import collections
import hashlib
import json
import re

from hazop.extract import dexpi_map, isa, rules

OWN_URI = "urn:hazop:dexpi-export:"  # 이 앱이 낸 파일의 Model uri 앞부분(hazop.export.dexpi_export)
CLASS = "HazopOrigin"
TYPE = "/" + CLASS
TARGET = "Target"
FIELDS = ("Kind", "Tag", "Text", "Flow", "Basis", "Auto", "Edited", "TagBasis", "Open", "Line", "Fail", "Echo")
# 출처 등급(§6.9.3): 자동 확정이 정한 칸(Auto)과 이 파일을 낸 프로젝트에서 사람이 고친 칸(Edited)의 이름, 빈칸으로 나눔. 배관의 tag는 배관 번호다
GRADED = ("kind", "tag", "flow", "normal_position", "fail_position", "endpoint", "path", "add_node", "add_relation", "line_no")
EDITED_FLOW = "human_elsewhere"  # 다른 프로젝트에서 사람이 정한 흐름의 근거. 이 프로젝트의 사람이 정한 것(human)이 아니다
ECHO_VERSION = "1"  # 지문 셈이 바뀌면 올린다(옛 표시는 지문이 달라 쓰이지 않는다)
OTHER_END = {"source": "target", "target": "source"}
UNNAMED_BASIS = "dexpi_origin"  # 근거 이름이 없거나 이름 꼴이 아닐 때
STANDARD = ("TagName", "PipingComponentNumber", "ProcessInstrumentationFunctionCategory", "ProcessInstrumentationFunctionNumber",
            "ProcessInstrumentationFunctions")
_BASIS = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_HEADING = re.compile(r"\s*(FROM|TO)\b", re.I)
CHECK = "dexpi_origin_mismatch"

Claim = collections.namedtuple("Claim", "values problems marked")  # 쓸 값 {칸: 값}(파일만 읽은 값과 다른 것만), [(칸, 까닭)], 지문이 맞는 표시인가


def node_echo(item, drive=None):
    """구성요소의 표준 값 지문. drive: 밸브의 구동계(없음 None, 있음 "system", 신호선까지 있음 "loop")."""
    ref = item.get("reference") or {}
    return _hash("node", item["id"], item["cls"], [item["attrs"].get(k) for k in STANDARD], ref.get("drawing"), ref.get("connector"), drive)


def pipe_echo(conn):
    """배관 연결의 표준 값 지문."""
    return _hash("pipe", conn["id"], conn["source"], conn["source_node"], conn["target"], conn["target_node"])


def _hash(*parts):
    return hashlib.sha256(json.dumps((ECHO_VERSION,) + parts, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 파일에서 모으기
def collect(root, model):
    """뿌리 -> {대상 id: {칸: 글자}}. 이 앱이 낸 파일(uri)이 아니면 빈 것. 쓸 수 없는 표시는 model.issues에 남긴다."""
    if not (model.uri or "").startswith(OWN_URI):
        return {}
    ids = collections.Counter(o.get("id") for o in root.iter("Object") if o.get("id"))
    found, lost = {}, 0
    for obj in root.findall("Object"):
        if obj.get("type") != TYPE:
            continue
        refs = [x for r in obj.findall("References") if r.get("property") == TARGET for x in (r.get("objects") or "").split()]
        target = refs[0][1:] if len(refs) == 1 and refs[0].startswith("#") else None
        if target is None or not ids[target]:
            lost += 1
        else:
            found.setdefault(target, []).append(_fields(obj))
    if lost:
        model.issue(CHECK, None, "대상을 찾을 수 없는 원래 값 표시 %d개를 쓰지 않음" % lost)
    out = {}
    for target, marks in found.items():
        if len(marks) == 1 and ids[target] == 1:
            out[target] = marks[0]
        else:
            model.issue(CHECK, target, "대상 하나에 원래 값 표시가 %d개, 같은 id가 %d개라 쓰지 않음" % (len(marks), ids[target]))
    return out


def _fields(obj):
    """표시 하나의 칸. 같은 칸이 둘이거나 글자 하나가 아니면 그 칸은 없는 것으로 본다."""
    out, twice = {}, set()
    for d in obj.findall("Data"):
        name = d.get("property")
        if name in out or name not in FIELDS or len(d) != 1 or d[0].tag != "String":
            twice.add(name)
        else:
            out[name] = unpack(d[0].text or "")
    return {k: v for k, v in out.items() if k not in twice}


PACKED = "json:"  # XML에 그대로 실리지 않는 글자가 든 값은 이 머리 뒤에 JSON 글자로 적는다


def unpack(text):
    if not text.startswith(PACKED):
        return text
    try:
        value = json.loads(text[len(PACKED):])
    except ValueError:
        return text
    return value if isinstance(value, str) else text


OPEN_FIELDS = ("kind", "tag", "label_text", "flow_direction", "line_no")


def open_of(mark):
    """파일을 낸 프로젝트에서 이미 표시와 표준 값이 어긋나 풀리지 않은 칸(Open)."""
    return [x for x in OPEN_FIELDS if x in (mark.get("Open") or "").split()]


WAS_OPEN = "이 파일을 낸 곳에서 원래 값 표시와 표준 값이 어긋나 풀리지 않은 칸"


# ---------------------------------------------------------------- 검사
def claim_node(mark, item, plain, drive):
    """구성요소의 표시와 파일만 읽은 값 plain {"kind", "tag", "label_text"}, 구동계(node_echo의 drive) -> Claim."""
    want = {"kind": mark.get("Kind") or None, "label_text": mark.get("Text")}
    want = {k: v for k, v in want.items() if v is not None}
    if "Tag" in mark:
        want["tag"] = mark["Tag"] or None
    values, problems = {}, []
    stale = mark.get("Echo") != node_echo(item, drive)
    for field, value in want.items():
        if value == plain[field]:
            continue
        why = "표시를 쓴 뒤 파일의 표준 값이 바뀜" if stale else _WHY[field](value, item, drive)
        if why is None:
            values[field] = value
        else:
            problems.append((field, why))
    if "tag" in values and "label_text" not in want:
        values["label_text"] = values["tag"] or ""
    return Claim(values, problems, not stale)


def grades_of(mark):
    """표시가 적은 등급 {"auto"|"edited": [칸 이름]}(빈 것은 없음). 자동이 사람보다 낮은 등급이라 둘 다면 자동이다."""
    auto = [x for x in GRADED if x in (mark.get("Auto") or "").split()]
    edited = [x for x in GRADED if x in (mark.get("Edited") or "").split() and x not in auto]
    return {k: v for k, v in (("auto", auto), ("edited", edited)) if v}


def line_grades(model):
    """{배관망 계통 id: 배관 번호의 등급}. 도면 연결 기호는 배관 번호를 계통에서 읽으므로 그 배관의 등급을 따른다."""
    out = {}
    for conn in model.connections:
        for key, names in grades_of(model.origins.get(conn["id"], {})).items():
            if "tag" in names and out.get(conn["system"]) != "auto":
                out[conn["system"]] = key
    return out


def why_line(mark, line_no):
    """도면 연결 기호의 원래 배관 번호(Line)와 계통에서 읽은 번호가 다르면 그 까닭."""
    return "적힌 배관 번호가 계통의 배관 번호와 다름" if mark.get("Line") and line_no and mark["Line"] != line_no else None


def without(grades, names):
    out = {k: [x for x in v if x not in names] for k, v in grades.items()}
    return {k: v for k, v in out.items() if v}


def basis_for(basis, grades):
    """파일에 싣거나 파일에서 되살리는 흐름의 근거. 자동으로 정한 것과 다른 프로젝트의 사람이 정한 것은 이 프로젝트의 사람(human)이 아니다."""
    if "flow" in grades.get("auto", ()) or basis == "ai_auto":
        return "ai_auto"
    return EDITED_FLOW if "flow" in grades.get("edited", ()) else basis


def _names(item):
    """이 프로젝트에서 사람이나 자동 확정이 정한 칸의 이름(연산 이름에서 set_를 뺀 것)."""
    return {o[len("set_"):] if o.startswith("set_") else o for o in (item.get("human_edit") or {}).get("ops") or ()}


def grades_out(node):
    """그래프 노드(구성요소·배관)의 등급 {"auto"|"edited": [칸 이름]}과, 추정한 태그면 "tag_basis". 파일에 싣는 값이다."""
    ops = _names(node)
    auto = set(node.get("auto") or ())
    edited = (ops | set(node.get("edited_elsewhere") or ())) - auto
    basis = node.get("tag_basis") or ""
    if basis == "human":
        edited.add("tag")
    flow = (node.get("flow_direction") or {}).get("basis")
    auto |= {"flow"} if flow == "ai_auto" else set()
    edited |= {"flow"} if flow in ("human", EDITED_FLOW) and "flow" not in auto else set()
    out = {k: [x for x in GRADED if x in v] for k, v in (("auto", auto), ("edited", edited))}
    out = {k: v for k, v in out.items() if v}
    return dict(out, tag_basis=basis) if INFERRED in basis else out


def grades_in(item):
    """추출 노드·관계 -> 그래프 노드에 둘 {"auto", "edited_elsewhere"}. 들여온 뒤 여기서 다시 정한 칸은 뺀다."""
    grades = without((item.get("evidence") or {}).get("dexpi_origin") or {}, _names(item))
    return {k: v for k, v in (("auto", grades.get("auto")), ("edited_elsewhere", grades.get("edited"))) if v}


INFERRED = "[추론]"


def tag_basis_of(mark):
    """표시가 추정했거나 자동으로 정한 태그라고 적었으면 그 근거, 아니면 None. 확정이라고 적은 것은 보지 않는다."""
    basis = mark.get("TagBasis") or ""
    if basis.startswith("ai_auto"):
        return "ai_auto"
    return None if INFERRED not in basis else basis if len(basis) <= 200 else INFERRED


def _why_kind(kind, item, drive):
    group = item["group"]
    if group == "instrument":
        fits = kind in dexpi_map.INSTRUMENT_KINDS
    elif group == "offpage":
        fits = kind == "continuation"
    else:
        fits = kind in dexpi_map.EXPORT_CLASS and dexpi_map.derives_from(item["cls"], dexpi_map.EXPORT_CLASS[kind][0])
        fits = fits and (drive or kind not in dexpi_map.ACTUATED_KINDS)
    return None if fits and rules.KIND_CATEGORY.get(kind) else "적힌 종류가 DEXPI 클래스와 맞지 않음"


def _why_tag(tag, item, _drive):
    if item["group"] != "instrument":
        return "계기가 아닌 것의 태그는 표준 값이 먼저임"
    category, number, functions = (item["attrs"].get(k) for k in STANDARD[2:])
    parsed = isa.parse_tag(tag)
    if parsed:
        fits = (category, number, functions) == (parsed["measured_variable"], parsed["loop_no"] + (parsed["suffix"] or ""), parsed["functions"] or None)
    else:
        fits = category is None and bool(tag) and number == tag
    return None if fits else "적힌 태그가 계측 기능의 문자·번호와 맞지 않음"


def _why_text(text, item, _drive):
    head = _HEADING.match(text)
    side = {"FlowIn": "FROM", "FlowOut": "TO"}
    if item["group"] == "offpage" and head and any(k in (item["cls"] or "") and head.group(1).upper() != v for k, v in side.items()):
        return "적힌 글자의 방향이 DEXPI 클래스와 맞지 않음"
    return None


_WHY = {"kind": _why_kind, "tag": _why_tag, "label_text": _why_text}


def claim_pipe(mark, conn, flow, disputed):
    """배관의 표시 -> Claim. 값은 label_text와 flow (방향 forward|backward, 근거). flow: 표준 근거로 읽은 방향(없으면 None).
    disputed: 표준 근거끼리 어긋나거나 양방향 구간이라 방향을 정할 수 없음."""
    values, problems = {}, []
    stale = mark.get("Echo") != pipe_echo(conn)
    if mark.get("Text"):
        if stale:
            problems.append(("label_text", "표시를 쓴 뒤 파일의 연결이 바뀜"))
        else:
            values["label_text"] = mark["Text"]
    if "Flow" in mark:
        want = {"source": "forward", "target": "backward"}.get(mark["Flow"])
        why = ("적힌 흐름이 source·target이 아님" if want is None else "표시를 쓴 뒤 파일의 연결이 바뀜" if stale
               else "적힌 흐름이 파일의 흐름 근거와 맞지 않음" if disputed or flow not in (None, want) else None)
        if why is None:
            values["flow"] = (want, mark["Basis"] if _BASIS.fullmatch(mark.get("Basis", "")) else UNNAMED_BASIS)
        elif flow is None or flow != want:
            problems.append(("flow_direction", why))
    return Claim(values, problems, not stale)


# ---------------------------------------------------------------- 표시를 빼고 읽은 값
PLAIN = "read_as"  # 표시를 받아들인 노드에만 있는 칸: 파일의 표준 값만으로 읽은 {"kind", "tag", "label_text"}. 배관은 표시가 흐름을 채웠을 때만


def plain_view(extraction):
    """추출 결과에서 표시가 바꾼 값을 표준 값만으로 읽은 값으로 되돌린 것. 받아들인 표시가 없으면 받은 것 그대로."""
    nodes = extraction["nodes"]
    if not any(PLAIN in n for n in nodes):
        return extraction
    return dict(extraction, nodes=[{k: v for k, v in dict(n, **n.get(PLAIN, {})).items() if k != PLAIN} for n in nodes])
