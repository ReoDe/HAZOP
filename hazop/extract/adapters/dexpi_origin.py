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
FIELDS = ("Kind", "Tag", "Text", "Flow", "Basis", "Echo")
ECHO_VERSION = "1"  # 지문 셈이 바뀌면 올린다(옛 표시는 지문이 달라 쓰이지 않는다)
OTHER_END = {"source": "target", "target": "source"}
UNNAMED_BASIS = "dexpi_origin"  # 근거 이름이 없거나 이름 꼴이 아닐 때
STANDARD = ("TagName", "PipingComponentNumber", "ProcessInstrumentationFunctionCategory", "ProcessInstrumentationFunctionNumber",
            "ProcessInstrumentationFunctions")
_BASIS = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_HEADING = re.compile(r"\s*(FROM|TO)\b", re.I)
CHECK = "dexpi_origin_mismatch"

Claim = collections.namedtuple("Claim", "values problems")  # 쓸 값 {칸: 값}(파일만 읽은 값과 다른 것만), [(칸, 까닭)]


def node_echo(item):
    """구성요소의 표준 값 지문."""
    ref = item.get("reference") or {}
    return _hash("node", item["id"], item["cls"], [item["attrs"].get(k) for k in STANDARD], ref.get("drawing"), ref.get("connector"))


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
            out[name] = d[0].text or ""
    return {k: v for k, v in out.items() if k not in twice}


# ---------------------------------------------------------------- 검사
def claim_node(mark, item, plain, actuated):
    """구성요소의 표시와 파일만 읽은 값 plain {"kind", "tag", "label_text"} -> Claim."""
    want = {"kind": mark.get("Kind") or None, "label_text": mark.get("Text")}
    want = {k: v for k, v in want.items() if v is not None}
    if "Tag" in mark:
        want["tag"] = mark["Tag"] or None
    values, problems = {}, []
    stale = mark.get("Echo") != node_echo(item)
    for field, value in want.items():
        if value == plain[field]:
            continue
        why = "표시를 쓴 뒤 파일의 표준 값이 바뀜" if stale else _WHY[field](value, item, actuated)
        if why is None:
            values[field] = value
        else:
            problems.append((field, why))
    if "tag" in values and "label_text" not in want:
        values["label_text"] = values["tag"] or ""
    return Claim(values, problems)


def _why_kind(kind, item, actuated):
    group = item["group"]
    if group == "instrument":
        fits = kind in dexpi_map.INSTRUMENT_KINDS
    elif group == "offpage":
        fits = kind == "continuation"
    else:
        fits = kind in dexpi_map.EXPORT_CLASS and dexpi_map.derives_from(item["cls"], dexpi_map.EXPORT_CLASS[kind][0])
        fits = fits and (actuated or kind not in dexpi_map.ACTUATED_KINDS)
    return None if fits and rules.KIND_CATEGORY.get(kind) else "적힌 종류가 DEXPI 클래스와 맞지 않음"


def _why_tag(tag, item, _actuated):
    if item["group"] != "instrument":
        return "계기가 아닌 것의 태그는 표준 값이 먼저임"
    category, number, functions = (item["attrs"].get(k) for k in STANDARD[2:])
    parsed = isa.parse_tag(tag)
    if parsed:
        fits = (category, number, functions) == (parsed["measured_variable"], parsed["loop_no"] + (parsed["suffix"] or ""), parsed["functions"] or None)
    else:
        fits = category is None and bool(tag) and number == tag
    return None if fits else "적힌 태그가 계측 기능의 문자·번호와 맞지 않음"


def _why_text(text, item, _actuated):
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
    return Claim(values, problems)


# ---------------------------------------------------------------- 표시를 빼고 읽은 값
PLAIN = "read_as"  # 표시가 값을 바꾼 노드에만 있는 칸: 파일의 표준 값만으로 읽은 {"kind", "tag", "label_text"}


def plain_view(extraction):
    """추출 결과에서 표시가 바꾼 값을 표준 값만으로 읽은 값으로 되돌린 것. 표시가 바꾼 것이 없으면 받은 것 그대로."""
    nodes = extraction["nodes"]
    if not any(PLAIN in n for n in nodes):
        return extraction
    return dict(extraction, nodes=[{k: v for k, v in dict(n, **n.get(PLAIN, {})).items() if k != PLAIN} for n in nodes])
