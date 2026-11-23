"""판 이전의 대응표(무엇이 무엇으로)와 id 필드 등록부(어디에 id가 있나). 근거: docs/specs/study-node-segmentation.md §2.6,
docs/units/2026-11-13-drawing-knowledge/evidence/migration-map-design.md.

- 구성요소의 정체성: id_basis가 "source"(drawio·DEXPI 파일 id·사람이 더한 manual-·나누기 split-)면 안정 참조(ref)가 정체성이다.
  "sequence"(벡터 PDF·스캔 순번, DEXPI 가져오기가 지은 id)면 표시(mark: 종류·도면·기호 종류·태그·상자)가 정체성이고 ref는
  표시가 같은 것이 둘 이상일 때 고르는 데만 쓴다. 표시가 같은 다른 기호(태그 없는 같은 종류가 같은 상자)는 구별하지 못한다.
  상자가 없는 순번 구성요소 가운데 끝(has_endpoint)이 있는 것(배관 구간, 도면 연결 구간 xlink)은 겉모습(종류·도면·기호
  종류·태그)과 끝 구성요소들이 정체다. 끝이 모두 이어지고 그 끝들을 가진 같은 겉모습의 새 구성요소가 하나뿐이면 잇는다.
- 판 이전은 대응표(compute) 하나를 먼저 다 계산하고, 등록부(FIELDS)의 모든 id 필드에 같은 함수(apply)로 적용한다.
  옛 판의 모든 구성요소는 새 구성요소 하나나 묘비 하나로 간다(전함수). 새 구성요소 하나로 모이는 옛 구성요소는 모두 묘비다.
- 묘비 id는 `lost:<graph_id>:<잃은 판>:t-<지문>`. 지문(tomb_key)은 graph_id·잃기 전 판·잃은 판·옛 entity_id·옛 참조·표시의
  해시다. 판 문자열은 내용 해시라 (잃기 전 판, 옛 entity_id)가 기호 하나를 정하므로, 같은 id면 같은 잃은 기호이고 다른
  기호면 다른 id다. 집합을 새로 제안하거나 백업에서 되돌려도, 결과가 든 묘비 id를 다른 기호에 다시 쓰지 않는다. 살아 있는
  id(entity-·relation-·xlink-·<graph_id>/·graph-·project-)와 꼴이 겹치지 않는다. 묘비는 지우지 않고, 표시가 맞는 구성요소가
  하나뿐으로 다시 나오면 되찾는다(found). source 구성요소의 묘비는 표시 대신 겉모습(look: 종류·도면·기호 종류·태그)을 지문에
  넣어 두고, 같은 참조의 source 구성요소가 하나뿐으로 다시 나오고 겉모습이 같으면(기록에 태그가 없으면 태그는 보지 않음)
  되찾는다(나누기를 되돌렸다 다시 하면 같은 나눈 id가 돌아온다). 같은 참조가 다른 종류로 돌아오면 다른 기호라 묘비로 둔다.
  되찾기는 기록의 지문이 묘비 id와 맞는 것만 한다(기록에 없는 묘비 id는 풀지 않음).
- 구간(members를 가진 사전)은 members에 지금 판의 살아 있는 id만 두고 잃은 것은 lost(묘비 id)에 둔다. 실행 취소 기록의
  before·after와 조각 기록도 같은 규칙이라 되돌려도 묘비는 묘비다. 사람이 확인하고 버린 묘비는 lost에서 discarded로
  옮긴다(hazop.study.nodes.discard_lost). 지금 구간 어디에도 lost로 남지 않고 버려진 묘비(discarded_tombs)는 되찾지 않는다.
- 시트의 자료가 바뀌면(같은 도면 번호의 다른 파일로 갈아탐, hazop.graph.sources) 파일 id가 같아도 같은 기호라는 증거가 아니다. 판 사진에
  시트별 자료(graph_member_sheets {시트 graph_id: material_id})를 남기고, 옛 사진과 새 그래프의 자료가 다른 시트의 source 구성요소는
  참조로 잇지 않는다(표시로 증명하지 못하면 묘비). 그 칸이 없는 옛 사진은 전처럼 참조로 잇는다.
- 등록되지 않은 자리에서 옛 판 id를 만나면 report["unregistered"]에 경로를 적는다(시험에서는 비어 있어야 한다).
- 경로의 `[]`는 목록의 항목, `{}`는 ID를 열쇠로 쓰는 사전의 값이다. 경로가 `{}`로 끝나면 그 사전의 열쇠를 옮긴다(키 다시
  짓기). 옮긴 열쇠가 다른 항목의 열쇠와 겹치면 뒤 항목은 묘비 열쇠로 둔다(어느 쪽이 맞는지 모르므로 덮지 않음). 값이 자기
  열쇠를 `key`로 들고 있으면 그것도 같이 바꾼다.
- 프로젝트 문서(⑥ 초기사건 IE, FMEA, 잠재 후보 판단 LATENT)도 같은 표로 옮긴다(차례는 hazop.study.follow).
"""

import collections
import copy
import hashlib
import json
import re

from hazop.extract import ids

TOMB_PREFIX = "lost:"
EXP_SEP = "|exp:"
LEGACY_LOST = "~lost"  # cff108c~49033f1 판이 찾지 못한 참조 끝에 붙인 글자. upgrade가 묘비로 바꾼다
LOST_LABEL = "대상 없음(다시 추출 뒤 찾지 못함, 확인 필요)"
DISCARDED_LABEL = "대상 없음(다시 추출 뒤 찾지 못해 사람이 버림)"

MARK_TOL = 1.0  # pt. 같은 기호를 다시 읽으면 상자가 그대로다
MARK_LEN = 8

MEMBERS, EID, REF, EXP = "members", "eid", "ref", "exp"
HEAD, TAIL = "head", "tail"  # "<참조>|<나머지>"(기본사건 열쇠), "<규칙>|<참조>"(잠재 후보 판단 열쇠)
SET, RESULTS = "study_set", "results"
IE, FMEA, LATENT = "ie", "fmea", "latent"
MARKER_FIELDS = ("ref_versions", "ref_migrations")  # 프로젝트 문서의 판 표지와 옮긴 기록(hazop.study.follow)

_PID_ID = re.compile(r"(^|/)(entity|relation)-")
_RELATION_ID = re.compile(r"(^|/)relation-|^xlink-[0-9a-f]+-[ab]$")  # 도면 연결 구간의 두 끝 관계도 순번처럼 바뀐다
_LEGACY_SEQUENCE_ID = re.compile(r"^pdf-p\d+-[a-z]+-\d+$")  # 49033f1 판이 표시를 남긴 id(B꼴 표시의 범위)


def _node_fields(base):
    return ((base, MEMBERS), (base + ".absorbed[]", MEMBERS), (base + ".parts[]", MEMBERS),
            (base + ".boundary_hint.from", EID), (base + ".boundary_hint.to", EID))


_REF_FIELDS = (("cause_refs[].ref", REF), ("consequence_refs[].ref", REF), ("safeguards[].refs[].ref", REF),
               ("expectation_refs[]", EXP))


_JUDGEMENT_FIELDS = (("key", TAIL), ("target", REF), ("found[]", REF), ("rejected[]", REF))


def _entry_fields(base):
    return (tuple((base + "." + p, s) for p, s in _REF_FIELDS) + ((base + ".ai_basis.kg_paths[][]", EID),)
            + tuple((base + ".history[].before." + p, s) for p, s in _REF_FIELDS))


FIELDS = {
    SET: (_node_fields("nodes[]") + _node_fields("batches[].ops[].before") + _node_fields("batches[].ops[].after")
          + _node_fields("previous[].nodes[]") + _node_fields("legacy.previous[].nodes[]")
          + _node_fields("legacy.excluded_nodes[]")),
    RESULTS: _entry_fields("cells[].entries[]") + _entry_fields("archived_cells[].cell.entries[]"),
    # 표제 대상·기본사건 참조. 기본사건 열쇠는 앞 참조만 옮기고 '|고장모드'는 그대로. tag·name은 사본이라 옮기지 않는다
    IE: (("headings{}.targets[]", REF), ("basic_events{}.ref", REF), ("basic_events{}.key", HEAD),
         ("history[].before.targets[]", REF)),
    FMEA: (("rows{}.ref", REF), ("rows{}.entity_id", EID), ("history[].before.ref", REF)),  # 행 고침 이력에 entity_id는 없음
    # 열쇠 다시 짓기("judgements{}")는 값의 key를 옮긴 뒤에 한다(_rekey가 옮긴 key로 자기 열쇠를 알아봄)
    LATENT: (tuple(("judgements{}." + p, s) for p, s in _JUDGEMENT_FIELDS)
             + tuple(("judgements{}.history[]." + p, s) for p, s in _JUDGEMENT_FIELDS) + (("judgements{}", TAIL),)),
}
# 일부러 옮기지 않는 자리: 지난 일의 기록(history·version_migrations), 판 이전 끝에 새로 만드는 판 사진, 묘비 기록
IGNORED = {
    SET: ("history", "graph_member_refs", "graph_member_marks", "graph_member_basis", "graph_member_ends",
          "graph_member_looks", "graph_member_sheets", "member_digest", "tombstones", "tomb_seq", "legacy.member_digest", "legacy.member_refs"),
    RESULTS: ("version_migrations", "cells[].entries[].history", "archived_cells[].cell.entries[].history",
              "legacy", "carried_from", "study_nodes_ref"),
    IE: MARKER_FIELDS, FMEA: MARKER_FIELDS, LATENT: MARKER_FIELDS,
}


# ---------------------------------------------------------------- 이름과 표시

def is_tomb(x):
    return isinstance(x, str) and x.startswith(TOMB_PREFIX)


def label(x, names=None, discarded=()):
    """사람이 읽는 이름. 묘비(잠재 후보 묘비 포함)면 LOST_LABEL, 그 가운데 discarded(discarded_tombs)에 든 것은
    DISCARDED_LABEL, names {id: 이름}에 있으면 그 이름, 아니면 x 그대로."""
    if is_tomb(x):
        return DISCARDED_LABEL if x.partition(EXP_SEP)[0] in discarded else LOST_LABEL
    return (names or {}).get(x, x)


def tomb_name(rec):
    """묘비 기록이 가리키던 기호의 이름. 잃기 전 판의 표시(종류·태그), source 구성요소면 잃기 전 참조, 아니면 '이름 없는
    구성요소'. 판 이전 뒤 집합의 판 사진은 새 판이라 옛 id로 찾지 않는다(describe는 판 이전 전에만 맞음)."""
    rec = rec if isinstance(rec, dict) else {}
    mk = rec.get("mark")
    if valid_mark(mk) and mk[2]:
        return " ".join(x for x in (mk[2], mk[3]) if x)
    if rec.get("ref") and rec.get("basis") != ids.SEQUENCE:
        return rec["ref"]
    return "이름 없는 구성요소"


def tomb_handle(tomb):
    """화면에 내는 묘비 손잡이 'L-<해시 12자>'. 묘비 id(lost:…)는 화면에 날것으로 나가지 않는다."""
    return "L-" + hashlib.sha256(tomb.encode("utf-8")).hexdigest()[:12]


def discarded_tombs(node_set):
    """사람이 버렸고 지금 구간 어디에도 lost로 남지 않은 묘비 id 집합. 되찾지 않고 '되찾지 못한 묘비' 수에서 빠진다.
    구간의 discarded와, 버린 묘비를 가진 구간을 지울 때 옮긴 집합 수준 discarded를 함께 본다. 겹친 구간 하나에서만 버린
    묘비는 다른 구간의 lost에 남아 있으면 아직 열린 묘비다."""
    ns = node_set or {}
    rows = [n for n in ns.get("nodes") or [] if isinstance(n, dict)]
    gone = {t for n in rows for t in n.get("discarded") or [] if is_tomb(t)} | {
        t for t in ns.get("discarded") or [] if is_tomb(t)}
    return gone - {t for n in rows for t in n.get("lost") or []}


def describe(node_set, entity_id):
    """옛 판 구성요소를 사람이 읽는 이름으로(표시·겉모습의 종류와 태그, source 구성요소는 안정 참조). 옛 id는 새 판에서
    다른 기호를 가리킬 수 있어 보이지 않는다."""
    look = ((node_set.get("graph_member_marks") or {}).get(entity_id)
            or (node_set.get("graph_member_ends") or {}).get(entity_id))
    if isinstance(look, list) and len(look) >= 4 and look[2]:
        return " ".join(x for x in (look[2], look[3]) if x)
    ref = (node_set.get("graph_member_refs") or {}).get(entity_id)
    if ref and (node_set.get("graph_member_basis") or {}).get(entity_id) == ids.SOURCE:
        return ref
    return "이름 없는 구성요소"


def ref_of(node, graph_id):
    """구성요소의 안정 참조 "<도면 graph_id>#<source_object_id>". 도면 연결 구간은 ID 자체가 양 끝 연결점의 참조로 만든
    해시라 그대로 쓴다. 참조를 만들 수 없으면 None."""
    soid = node.get("source_object_id")
    if soid:
        return "%s#%s" % (node.get("sheet") or graph_id, soid)
    if (node.get("sheet_link") or {}).get("link_id") == node["entity_id"]:
        return node["entity_id"]
    return None


def drawing_of(ref):
    gid, sep, _ = (ref or "").partition("#")
    return gid if sep else None


def _box_ok(b):
    return (isinstance(b, (list, tuple)) and len(b) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in b))


def mark_of(node, basis):
    """순번 구성요소의 표시 [node_type, 도면(프로젝트 그래프의 sheet), kind, tag, x0, y0, x1, y1](0.1pt 반올림).
    basis가 sequence가 아니거나 상자가 없으면 None. 좌표는 도면마다 따로라 도면도 같아야 같은 자리다."""
    b = node.get("bbox")
    if basis != ids.SEQUENCE or not _box_ok(b):
        return None
    x, y, w, h = b
    return [node.get("node_type"), node.get("sheet"), node.get("kind"), node.get("tag"),
            round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)]


def valid_mark(m):
    return (isinstance(m, list) and len(m) == MARK_LEN
            and all(v is None or isinstance(v, str) for v in m[:4])
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in m[4:]))


def _same_mark(a, b):
    return a[:4] == b[:4] and all(abs(x - y) <= MARK_TOL for x, y in zip(a[4:], b[4:]))


def bases(graph):
    """{entity_id: id_basis}. 노드에 적힌 값이 먼저, 없는 옛 그래프는 추출 형식, 그것도 모르면 sequence(hazop.extract.ids)."""
    out, fmt = {}, False
    for n in graph.get("nodes", []):
        own = n.get("id_basis")
        if own not in ids.BASES:
            if fmt is False:
                fmt = ids.graph_format(graph)
            own = ids.basis(fmt, n.get("source_object_id"))
        out[n["entity_id"]] = own
    return out


def ends_of(graph):
    """{구간 entity_id: [끝 entity_id](정렬)}. has_endpoint 관계의 첫 노드가 구간(배관 구간·도면 연결 구간)이다."""
    out = {}
    for e in graph.get("edges", []):
        nodes = e.get("nodes") or []
        if e.get("kind") == "has_endpoint" and len(nodes) >= 2:
            out.setdefault(nodes[0], set()).update(nodes[1:])
    return {k: sorted(v) for k, v in out.items()}


def look_of(node):
    """끝으로 잇는 구성요소의 겉모습 [node_type, 도면, kind, tag](표시의 앞 넷과 같음)."""
    return [node.get("node_type"), node.get("sheet"), node.get("kind"), node.get("tag")]


def valid_look(v):
    return isinstance(v, list) and len(v) == 4 and all(x is None or isinstance(x, str) for x in v)


def _same_look(rec, new):
    """source 묘비의 되찾기: 종류·도면·기호 종류가 같고, 기록에 태그가 있으면 태그도 같다."""
    return rec[:3] == new[:3] and (rec[3] is None or rec[3] == new[3])


def valid_ends(v):
    return (isinstance(v, list) and len(v) == 5 and all(x is None or isinstance(x, str) for x in v[:4])
            and isinstance(v[4], list) and all(isinstance(x, str) for x in v[4]))


def sheet_materials(graph):
    """{시트 graph_id: material_id}. 프로젝트 그래프는 sheets[], 도면 그래프는 머리 source. 자료를 모르는 시트는 뺀다."""
    if graph.get("sheets") is not None:
        return {s["graph_id"]: s["material_id"] for s in graph["sheets"] if s.get("material_id")}
    mid = (graph.get("source") or {}).get("material_id")
    return {graph["graph_id"]: mid} if mid and graph.get("graph_id") else {}


def snapshot(graph):
    """집합이 가리키는 판의 사진: 그래프 전체 구성요소의 참조·id 근거와, 상자가 있는 순번 구성요소의 표시, 상자가 없고 끝이
    있는 순번 구성요소의 겉모습과 끝(graph_member_ends {id: [node_type, 도면, kind, tag, [끝 id]]}), source 구성요소의
    겉모습(graph_member_looks {id: [node_type, 도면, kind, tag]}, 묘비를 되찾을 때 같은 기호인지 본다)."""
    gid = graph.get("graph_id")
    basis = bases(graph)
    ends = ends_of(graph)
    refs, marks, linked, looks = {}, {}, {}, {}
    for n in graph.get("nodes", []):
        e = n["entity_id"]
        refs[e] = ref_of(n, gid)
        m = mark_of(n, basis[e])
        if m is not None:
            marks[e] = m
        elif basis[e] == ids.SEQUENCE and ends.get(e):
            linked[e] = look_of(n) + [ends[e]]
        if basis[e] == ids.SOURCE:
            looks[e] = look_of(n)
    return {"graph_member_refs": dict(sorted(refs.items())), "graph_member_marks": dict(sorted(marks.items())),
            "graph_member_basis": dict(sorted(basis.items())), "graph_member_ends": dict(sorted(linked.items())),
            "graph_member_looks": dict(sorted(looks.items())),
            "graph_member_sheets": dict(sorted(sheet_materials(graph).items()))}


OPTIONAL_SNAPSHOT = ("graph_member_looks", "graph_member_sheets")  # 나중에 들인 칸: 없는 옛 사진은 그 칸을 보지 않는다


def has_snapshot(node_set, graph, strict=False):
    """집합의 판 사진이 이 그래프의 것과 같은가. 나중에 들인 칸(OPTIONAL_SNAPSHOT)이 없는 옛 사진은 그 칸을 보지 않는다(같은 판을
    열기만 해서는 집합을 다시 쓰지 않게). strict면 그 칸도 본다: 다시 추출 직전 표지 채우기(hazop.app.data.prepare_reextract)가
    쓴다. 그 밖에는 다음에 집합을 쓸 때(확정·판 이전 등) 채워진다."""
    snap = snapshot(graph)
    return all(node_set.get(k) == v for k, v in snap.items() if strict or k not in OPTIONAL_SNAPSHOT or k in node_set)


def _sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def tomb_id(graph_id, version, key):
    return "%s%s:%s:%s" % (TOMB_PREFIX, graph_id, version or "legacy", key)


def tomb_key(graph_id, frm, to, entity_id, ref, mark, look=None):
    """묘비 지문. look은 f945ff2 판이 지은 묘비 id를 알아볼 때만 넘긴다. 새 묘비는 겉모습을 지문에 넣지 않는다: 겉모습이 없는 옛 사진
    (백업에서 되돌린 집합)으로 다시 셈해도 같은 잃은 기호가 같은 id가 되어 집합과 ⑤ 결과가 한 묘비를 든다. 겉모습은 look_key로 지킨다."""
    row = [graph_id, frm, to, entity_id, ref, mark] + ([look] if look is not None else [])
    canon = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    return "t-" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def look_key(tomb, look):
    """묘비 기록의 겉모습이 그 묘비를 지을 때의 것인지 보는 지문(고쳐 쓴 겉모습으로 되찾지 않게)."""
    return "k-" + _sha8(json.dumps([tomb, look], ensure_ascii=False, separators=(",", ":")))


def _recorded_as(t, rec, graph_id):
    """묘비 기록이 그 묘비 id를 지은 기록인가(되찾기 전 확인). B꼴에서 옮긴 묘비는 upgrade의 열쇠로 본다."""
    if rec.get("lost_at") is None:
        key = json.dumps([rec.get("entity_id"), rec.get("ref"), rec.get("lost_from")], sort_keys=True)
        return t == tomb_id(graph_id, "legacy", "b-" + _sha8(key))
    args = (graph_id, rec.get("lost_from"), rec["lost_at"], rec.get("entity_id"), rec.get("ref"), rec.get("mark"))
    if rec.get("look") is not None and t == tomb_id(graph_id, rec["lost_at"], tomb_key(*args, look=rec["look"])):
        return True                     # f945ff2 판이 겉모습을 지문에 넣어 지은 묘비
    if t != tomb_id(graph_id, rec["lost_at"], tomb_key(*args)):
        return False
    return rec.get("look") is None or rec.get("look_key") == look_key(t, rec["look"])


# ---------------------------------------------------------------- 대응표

def _empty_table(graph_id, frm, to, partial):
    return {"graph_id": graph_id, "from": frm, "to": to, "eid": {}, "ref": {}, "found": {}, "new_tombs": {},
            "check": "mark", "partial": partial, "drawings": [], "unnamed": []}


def _registered_ids(doc, kind, spaces):
    """문서의 등록 경로에서 만난 값(공간이 spaces에 드는 것만)."""
    out = set()
    for path, space in FIELDS[kind]:
        if space not in spaces:
            continue
        for holder, key in walk(doc, path):
            v = holder.get(key) if isinstance(holder, dict) else holder[key]
            if space == MEMBERS:
                if isinstance(v, dict):
                    out.update(x for x in v.get("members") or [] if isinstance(x, str))
            elif isinstance(v, str):
                out.add(v)
    return out


def compute(node_set, graph, at=None):
    """옛 판 사진(집합)에서 새 그래프로 가는 대응표. 순수 함수. 집합은 upgrade를 거친 것이어야 한다."""
    gid = graph.get("graph_id")
    frm, to = node_set.get("graph_version"), graph.get("graph_version")
    table = _empty_table(gid, frm, to, False)
    old_refs = node_set.get("graph_member_refs") or {}
    old_marks = {k: v for k, v in (node_set.get("graph_member_marks") or {}).items() if valid_mark(v)}
    old_basis = node_set.get("graph_member_basis")
    old_looks = {k: v for k, v in (node_set.get("graph_member_looks") or {}).items() if valid_look(v)}
    tombs = node_set.get("tombstones") or {}
    gone = discarded_tombs(node_set)
    new_basis = bases(graph)
    now_sheets = sheet_materials(graph)
    old_sheets = node_set.get("graph_member_sheets") or {}
    moved = {s for s, mid in old_sheets.items() if mid and now_sheets.get(s) not in (None, mid)}
    by_id = {n["entity_id"]: n for n in graph.get("nodes", [])}
    new_ref = {e: ref_of(n, gid) for e, n in by_id.items()}
    by_ref = {}
    for e, r in new_ref.items():
        if r is not None:
            by_ref.setdefault(r, []).append(e)
    by_look = {}  # 표시 앞 넷(종류·도면·기호 종류·태그) → [(표시, entity_id)]
    for e, n in by_id.items():
        m = mark_of(n, new_basis[e])
        if m is not None:
            by_look.setdefault(json.dumps(m[:4]), []).append((m, e))

    def mark_hits(mark):
        return [e for m, e in by_look.get(json.dumps(mark[:4]), ()) if _same_mark(mark, m)]

    def old_basis_of(m):
        if old_basis is not None:
            return old_basis.get(m, ids.SEQUENCE)
        if m in old_marks:  # B꼴 표시는 순번 id에만 있었다
            return ids.SEQUENCE
        hits = by_ref.get(old_refs.get(m)) or []
        return ids.SOURCE if hits and all(new_basis[e] == ids.SOURCE for e in hits) else ids.SEQUENCE

    domain = set(old_refs) | {x for x in _registered_ids(node_set, SET, (MEMBERS, EID)) if not is_tomb(x)}
    link = {}
    for m in sorted(domain):
        r = old_refs.get(m)
        hits = []
        if m not in old_refs:
            pass  # 판 사진에 없는 떠돌이 id: 무엇이었는지 모른다
        elif old_basis_of(m) == ids.SOURCE:
            hits = [] if drawing_of(r) in moved else by_ref.get(r) or []   # 다른 파일의 같은 id는 같은 기호가 아니다
        elif m in old_marks:
            # 순번 구성요소는 표시로 잇는다. 표시가 없으면(상자 없음, A꼴, B꼴의 스캔·지은 id) 끝으로 잇거나(_link_by_ends) 묘비다.
            # 구간 지문(md3)이 같아도 위치는 지문에 없어서, 같은 종류·태그의 다른 자리 기호로 이을 수 있다(퍼즈로 확인)
            hits = mark_hits(old_marks[m])
            if len(hits) > 1:  # 표시가 같은 것이 여럿이면 같은 참조인 것만
                hits = [e for e in hits if new_ref[e] == r]
        if len(hits) == 1:
            link[m] = hits[0]
    contested = _drop_contested(link)
    _link_by_ends(node_set, graph, new_basis, by_id, link, contested, old_basis_of, domain)
    for m in sorted(domain - set(link)):
        mk = old_marks.get(m)
        lk = old_looks.get(m) if m in old_refs and old_basis_of(m) == ids.SOURCE else None
        t = tomb_id(gid, to, tomb_key(gid, frm, to, m, old_refs.get(m), mk))
        table["eid"][m] = t
        if t not in tombs:  # 같은 id면 같은 기호라 앞 기록을 그대로 둔다
            table["new_tombs"][t] = {"entity_id": m, "ref": old_refs.get(m), "mark": mk, "basis": (old_basis or {}).get(m),
                                     "lost_from": frm, "lost_at": to, "at": at, "legacy_key": None, "found": None}
            if lk is not None:
                table["new_tombs"][t].update(look=lk, look_key=look_key(t, lk))
                if old_sheets.get(drawing_of(old_refs.get(m))):   # 잃을 때의 시트 자료(다른 파일로 바뀐 뒤 같은 id로 되찾지 않게)
                    table["new_tombs"][t]["material"] = old_sheets[drawing_of(old_refs.get(m))]
    table["eid"].update(link)
    taken = set(link.values())
    claims = {}
    for t, rec in sorted(tombs.items()):
        if not isinstance(rec, dict) or rec.get("found") is not None or t in gone or not _recorded_as(t, rec, gid):
            continue
        if valid_mark(rec.get("mark")):
            hits = mark_hits(rec["mark"])
        elif rec.get("basis") == ids.SOURCE and rec.get("ref") and valid_look(rec.get("look")):
            sheet = drawing_of(rec["ref"])
            lost_in = rec.get("material")       # 잃을 때의 시트 자료. 없는 옛 묘비는 이번에 자료가 바뀌었는지만 본다
            if (sheet in moved) if lost_in is None else now_sheets.get(sheet, lost_in) != lost_in:
                continue                        # 시트 자료가 다르면 같은 파일 id·같은 겉모습도 같은 기호가 아니다
            hits = [e for e in by_ref.get(rec["ref"]) or ()
                    if new_basis[e] == ids.SOURCE and _same_look(rec["look"], look_of(by_id[e]))]
        else:
            continue
        hits = [e for e in hits if e not in taken and e not in contested]
        if len(hits) == 1:
            claims.setdefault(hits[0], []).append(t)
    for e, ts in claims.items():
        if len(ts) == 1:  # 묘비 둘이 한 구성요소를 다투면 둘 다 못 찾는다
            table["found"][ts[0]] = [e, new_ref[e]]
    for m, r in old_refs.items():
        if r is None:
            continue
        v = table["eid"][m]
        if not is_tomb(v) and new_ref[v] is None:  # 이은 새 구성요소에 안정 참조가 없음: 이력 줄(ref_moved None)과 같은 묘비
            table["unnamed"].append(r)
            v = tomb_id(gid, to, "r-" + _sha8(r))
        table["ref"].setdefault(r, v if is_tomb(v) else new_ref[v])
    table["drawings"] = sorted({drawing_of(r) for r in list(old_refs.values()) + list(new_ref.values())} - {None}
                               | ({gid} if gid else set()))
    table["unnamed"] = sorted(set(table["unnamed"]))
    return table


def _drop_contested(link):
    """옛 구성요소 둘이 새 구성요소 하나로 모이면 어느 쪽인지 모르므로 둘 다 뺀다. 모인 새 구성요소 집합을 돌려준다."""
    into = {}
    for m, e in link.items():
        into.setdefault(e, []).append(m)
    contested = {e for e, ms in into.items() if len(ms) > 1}
    for e in contested:
        for m in into[e]:
            del link[m]
    return contested


def _link_by_ends(node_set, graph, new_basis, by_id, link, contested, old_basis_of, domain):
    """상자가 없고 끝이 둘 이상인 순번 구성요소(배관 구간·도면 연결 구간)를 겉모습과 끝으로 잇는다(link를 고침). 끝이 모두
    이어졌고, 같은 겉모습으로 그 끝들을 가진 것이 옛 판에 하나·새 판에 하나뿐이며, 끝마다 닿는 같은 겉모습 구성요소 수가
    옛 판과 새 판에서 같을 때만 잇는다(나뉘며 생긴 같은 두 끝 우회선, 끊긴 끝으로 잇지 않음). 한쪽 끝만 있으면 잇지 않는다.
    끝이 끝으로 이은 구성요소일 수도 있어 더 이을 것이 없을 때까지 되풀이한다."""
    every = {m: v for m, v in (node_set.get("graph_member_ends") or {}).items() if valid_ends(v)}
    old = {m: v for m, v in every.items() if m in domain and old_basis_of(m) == ids.SEQUENCE and len(set(v[4])) >= 2}
    if not old:
        return
    new_ends = ends_of(graph)
    count = collections.Counter
    by_key, new_touch, old_key, old_touch = {}, count(), count(), count()
    for e, n in by_id.items():
        if new_basis[e] == ids.SEQUENCE and mark_of(n, ids.SEQUENCE) is None and new_ends.get(e):
            by_key.setdefault(json.dumps(look_of(n) + [new_ends[e]]), []).append(e)
            new_touch.update(json.dumps(look_of(n) + [x]) for x in new_ends[e])
    for v in every.values():
        old_key[json.dumps(v[:4] + [sorted(set(v[4]))])] += 1
        old_touch.update(json.dumps(v[:4] + [x]) for x in set(v[4]))
    while True:
        taken = set(link.values()) | contested
        found = {}
        for m, v in old.items():
            if m in link:
                continue
            ends = sorted(set(v[4]))
            images = [link.get(x) for x in ends]
            # old_key 검사는 판 사진(snapshot)에서는 뜻이 같다: 같은 열쇠의 쌍둥이도 old에 있어 같은 새 구간을 골라 _drop_contested가 둘 다 뺀다(test_two_parallel_pipes_meeting_one_new_pipe_are_both_lost). 손댄 집합을 막으려 둔다
            if None in images or old_key[json.dumps(v[:4] + [ends])] != 1:
                continue
            if any(old_touch[json.dumps(v[:4] + [x])] != new_touch[json.dumps(v[:4] + [y])] for x, y in zip(ends, images)):
                continue
            hits = by_key.get(json.dumps(v[:4] + [sorted(images)])) or []
            if len(hits) == 1 and hits[0] not in taken:
                found[m] = hits[0]
        if not found:
            return
        contested |= _drop_contested(found)
        if not found:
            return
        link.update(found)


def record(table):
    """이력 detail에 남길 표(이름 renamed는 U1 R2 시험이 읽는다). 바뀐 것과 함께 그대로 이어진 것(kept_eids·kept_refs)과
    도면(drawings)을 적어, 늦게 따라오는 문서도 from_record로 같은 표를 만든다(옛 판 사진에 없는 이 도면의 참조는 묘비)."""
    eid = table["eid"]
    return {"renamed": {a: b for a, b in sorted(eid.items()) if not is_tomb(b) and a != b},
            "lost": {a: b for a, b in sorted(eid.items()) if is_tomb(b)},
            "ref_moved": {a: b for a, b in sorted(table["ref"].items()) if a != b},
            "found": {t: v[0] for t, v in sorted(table["found"].items())},
            "found_refs": {t: v[1] for t, v in sorted(table["found"].items())},
            "kept_eids": sorted(a for a, b in eid.items() if a == b),
            "kept_refs": sorted(a for a, b in table["ref"].items() if a == b),
            "unnamed_refs": list(table.get("unnamed") or []),
            "drawings": list(table["drawings"]),
            "check": table["check"]}


def from_record(detail, graph_id):
    """이력 한 줄 → 표. kept_eids·kept_refs가 있는 줄은 compute가 만든 표와 같은 온전한 표이고, 없는 옛 줄(cff108c~M2)은
    바뀐 것만 담은 partial 표다. 49033f1 판의 줄(unmapped·ref_moved의 None·`~lost` 열쇠)도 읽는다."""
    to = detail.get("to")
    whole = isinstance(detail.get("kept_eids"), list) and isinstance(detail.get("kept_refs"), list)
    t = _empty_table(graph_id, detail.get("from"), to, not whole)
    if whole:
        t["eid"].update((a, a) for a in detail["kept_eids"])
        t["ref"].update((a, a) for a in detail["kept_refs"])
        t["drawings"] = list(detail.get("drawings") or [])
    for a, b in (detail.get("renamed") or {}).items():
        if not str(a).endswith(LEGACY_LOST):  # 옛 판의 되찾기 열쇠는 따르지 않는다(못 찾은 것으로 둠)
            t["eid"][a] = b
    t["eid"].update(detail.get("lost") or {})
    for a in detail.get("unmapped") or []:
        t["eid"].setdefault(a, tomb_id(graph_id, to, "e-" + _sha8(a)))
    for a, b in (detail.get("ref_moved") or {}).items():
        if str(a).endswith(LEGACY_LOST):
            continue
        t["ref"][a] = b if b is not None else tomb_id(graph_id, to, "r-" + _sha8(a))
        if b is None:
            t["unnamed"].append(a)
    found, refs = detail.get("found"), detail.get("found_refs") or {}
    if isinstance(found, dict):
        t["found"] = {k: [v, refs.get(k)] for k, v in found.items() if is_tomb(k)}
    t["unnamed"] = sorted(set(t["unnamed"]) | set(detail.get("unnamed_refs") or []))
    t["check"] = detail.get("check") or ("mark" if detail.get("marked") else "ref")
    return t


# ---------------------------------------------------------------- 적용

_STEPS = re.compile(r"\[\]|\{\}")


def walk(doc, path):
    """경로(a.b[].c{}.d)가 가리키는 자리마다 (담은 것, 열쇠 또는 번호). `[]`는 목록 항목, `{}`는 사전 값."""
    parts = path.split(".")
    out = []

    def go(node, i):
        part = parts[i]
        name = _STEPS.sub("", part)
        last = i == len(parts) - 1
        if not isinstance(node, dict) or name not in node:
            return
        holders = [(node, name)]
        for step in _STEPS.findall(part):
            nxt = []
            for h, k in holders:
                v = h[k]
                if step == "[]" and isinstance(v, list):
                    nxt += [(v, j) for j in range(len(v))]
                elif step == "{}" and isinstance(v, dict):
                    nxt += [(v, j) for j in list(v)]
            holders = nxt
        for h, k in holders:
            if last:
                out.append((h, k))
            else:
                go(h[k], i + 1)
    go(doc, 0)
    return out


class _Ctx:
    """표 하나를 공간별 번역 함수로. 함수는 값만 돌려주고, 센 것은 apply가 report에 모은다."""

    def __init__(self, table):
        self.t = table
        self.found_eid = {k: v[0] for k, v in table["found"].items()}
        self.found_ref = {k: v[1] for k, v in table["found"].items() if v[1]}
        self.drawings = set(table.get("drawings") or ())
        self.exp_index = {}

    def eid(self, x, paths=False):
        if not isinstance(x, str):
            return x
        if is_tomb(x):
            return self.found_eid.get(x, x)
        if x in self.t["eid"]:
            return self.t["eid"][x]
        if paths and (_RELATION_ID.search(x) or not self.t["partial"] and _PID_ID.search(x)):
            # 근거 경로의 관계 id(판 사진에 없고 build가 순번으로 매김)와 옛 판 사진에 없는 구성요소 id는 다른 것을 가리킬 수 있다
            return tomb_id(self.t["graph_id"], self.t["to"], "e-" + _sha8(x))
        return x

    def ref(self, x):
        if not isinstance(x, str):
            return x
        if is_tomb(x):
            return self.found_ref.get(x, x)
        if x in self.t["ref"]:
            return self.t["ref"][x]
        if not self.t["partial"] and drawing_of(x) in self.drawings:  # 옛 판 사진에 없는 이 도면의 참조
            return tomb_id(self.t["graph_id"], self.t["to"], "r-" + _sha8(x))
        return x

    def head(self, x):
        if not isinstance(x, str) or "|" not in x:
            return x
        r, sep, rest = x.partition("|")
        return self.ref(r) + sep + rest

    def tail(self, x):
        if not isinstance(x, str) or "|" not in x:
            return x
        rest, sep, r = x.partition("|")
        return rest + sep + self.ref(r)

    def exp(self, x):
        from hazop.kg import expect
        if not isinstance(x, str):
            return x
        if is_tomb(x):
            tomb, sep, rule = x.partition(EXP_SEP)
            return expect.expectation_id(rule, self.found_ref[tomb]) if sep and tomb in self.found_ref else x
        if not x.startswith(expect.ID_PREFIX):
            return x
        rule = x[len(expect.ID_PREFIX):].rsplit("-", 1)[0]
        idx = self.exp_index.get(rule)
        if idx is None:
            idx = self.exp_index[rule] = {expect.expectation_id(rule, r): r for r in self.t["ref"]}
        r = idx.get(x)
        if r is None:  # 대상을 모르는 잠재 후보: 이어진 것을 증명하지 못한 결과면 묘비
            return "%s%s%s" % (tomb_id(self.t["graph_id"], self.t["to"], "x-" + _sha8(x)), EXP_SEP, rule) if self.t.get(
                "unproven") else x
        to = self.ref(r)
        if to == r:
            return x
        return "%s%s%s" % (to, EXP_SEP, rule) if is_tomb(to) else expect.expectation_id(rule, to)

    def members(self, d):
        """[(옛 값, 새 값)]. members의 묘비는 lost로, lost의 되찾은 묘비는 members로."""
        if not isinstance(d, dict) or not isinstance(d.get("members"), list):
            return []
        pairs = []
        live, lost = [], [x for x in d.get("lost") or [] if isinstance(x, str)]
        for m in d["members"]:
            v = self.eid(m)
            pairs.append((m, v))
            (lost if is_tomb(v) else live).append(v)
        for x in lost:
            if x in self.found_eid:
                pairs.append((x, self.found_eid[x]))
                live.append(self.found_eid[x])
        lost = sorted(set(x for x in lost if x not in self.found_eid))
        d["members"] = sorted(set(live))
        if lost:
            d["lost"] = lost
        else:
            d.pop("lost", None)
        return pairs


def apply(doc, kind, table):
    """(사본, 보고 {changed, lost, found, spaces{공간: {changed, lost, found}}, unregistered[경로]}).
    문서의 등록된 id 필드 전부에 표를 적용한다. 순수 함수."""
    out = copy.deepcopy(doc)
    ctx = _Ctx(table)
    report = {"changed": 0, "lost": 0, "found": 0, "spaces": {}}

    def count(space, a, b):
        if a == b:
            return
        row = report["spaces"].setdefault(space, {"changed": 0, "lost": 0, "found": 0})
        for target in (report, row):
            target["changed"] += 1
            target["lost"] += is_tomb(b) and not is_tomb(a)
            target["found"] += is_tomb(a) and not is_tomb(b)
    fn = {REF: ctx.ref, HEAD: ctx.head, TAIL: ctx.tail, EXP: ctx.exp}
    for path, space in FIELDS[kind]:
        if path.endswith("{}"):
            for holder, key in walk(out, path[:-2]):
                if isinstance(holder[key], dict):
                    holder[key] = _rekey(holder[key], fn[space], table, count, space)
            continue
        for holder, key in walk(out, path):
            v = holder[key]
            if space == MEMBERS:
                for a, b in ctx.members(v):
                    count(space, a, b)
                continue
            if space == EID:
                w = ctx.eid(v, paths=path.endswith("kg_paths[][]"))
            else:
                w = fn[space](v)
            count(space, v, w)
            holder[key] = w
    report["unregistered"] = _unregistered(out, kind, table)
    return out, report


def _rekey(d, fn, table, count, space):
    """ID를 열쇠로 쓰는 사전 d의 열쇠를 fn으로 옮긴 새 사전(차례 그대로). 옮긴 열쇠가 앞 항목과 겹치면 뒤 항목은 그 옛 열쇠의
    지문으로 지은 묘비 열쇠로 둔다. 값의 key가 (이미 옮긴) 자기 열쇠면 같이 바꾼다."""
    out = {}
    for k, v in d.items():
        nk = fn(k)
        if nk in out:
            rest, sep, _r = k.partition("|") if space == TAIL else ("", "", k)
            nk = rest + sep + tomb_id(table["graph_id"], table["to"], "k-" + _sha8(k))
            if isinstance(v, dict) and v.get("key") == fn(k):
                v["key"] = nk
        count(space, k, nk)
        out[nk] = v
    return out


def _unregistered(doc, kind, table):
    """등록되지 않았고 IGNORED도 아닌 자리의 문자열 잎 가운데 옛 판 id(대응표의 eid·ref 열쇠)인 것의 경로."""
    old = set(table["eid"]) | set(table["ref"])
    if not old:
        return []
    leaves = set()
    for path, space in FIELDS[kind]:
        if space == MEMBERS:
            leaves.update((path + ".members[]", path + ".lost[]"))
        else:
            leaves.add(path)
    ignored = set(IGNORED[kind])
    # ID를 열쇠로 쓰는 사전(경로에 {}로 적은 것). 그 아래는 열쇠 대신 {}로 맞춘다
    maps = {p[:m.start()] for p, _s in FIELDS[kind] for m in _STEPS.finditer(p) if m.group() == "{}"}
    hits = []

    def go(v, pat, where):
        if pat in ignored:
            return
        if isinstance(v, dict):
            for k, x in v.items():
                if k in old and pat not in maps:  # 옛 id를 열쇠로 쓰는 등록되지 않은 사전
                    hits.append(".".join(where).replace(".[", "[") + "{%s}" % k)
                go(x, pat + "{}" if pat in maps else "%s.%s" % (pat, k) if pat else str(k), where + (str(k),))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                go(x, pat + "[]", where + ("[%d]" % i,))
        elif isinstance(v, str) and v in old and pat not in leaves:
            hits.append(".".join(where).replace(".[", "["))
    go(doc, "", ())
    return sorted(set(hits))


# ---------------------------------------------------------------- 옛 꼴 읽기(A꼴: 표시 없음, B꼴: lost_members·~lost)

def upgrade(node_set):
    """(집합, 보고). B꼴(49033f1 판)의 nodes[].lost_members·실행 취소 기록의 lost_members를 묘비(tombstones, lost)로 옮긴다.
    A꼴은 바꿀 것이 없다(판이 같으면 판 사진을 채우고, 판이 다르면 표시가 없는 순번 구성요소는 묘비가 된다). 할 일이 없으면 입력 그대로.
    B꼴 표시(graph_member_marks)는 순번 정규식에 걸린 것에만 있으므로 graph_member_basis를 만들지 않는다."""
    holders = [h[k] for path, space in FIELDS[SET] if space == MEMBERS for h, k in walk(node_set, path)]
    if not any(isinstance(d, dict) and "lost_members" in d for d in holders):
        return node_set, {"tombs": 0, "broken": 0}
    out = copy.deepcopy(node_set)
    gid = out.get("graph_id")
    tombs = dict(out.get("tombstones") or {})
    by_rec = {}
    broken = 0
    for path, space in FIELDS[SET]:
        if space != MEMBERS:
            continue
        for h, k in walk(out, path):
            d = h[k]
            if not isinstance(d, dict) or "lost_members" not in d:
                continue
            recs = d.pop("lost_members")
            got = list(d.get("lost") or [])
            for x in recs if isinstance(recs, list) else ():
                if not isinstance(x, dict) or not isinstance(x.get("entity_id"), str):
                    broken += 1
                    continue
                key = json.dumps([x.get("entity_id"), x.get("ref"), x.get("from")], sort_keys=True)
                t = by_rec.get(key)
                if t is None:
                    t = tomb_id(gid, "legacy", "b-" + _sha8(key))
                    mk = x.get("mark") if valid_mark(x.get("mark")) else None
                    tombs.setdefault(t, {"entity_id": x["entity_id"], "ref": x.get("ref") if isinstance(x.get("ref"), str)
                                         else None, "mark": mk, "basis": None, "lost_from": x.get("from"),
                                         "lost_at": None, "at": None,
                                         "legacy_key": x["ref"] + LEGACY_LOST if isinstance(x.get("ref"), str) else None,
                                         "found": None})
                    by_rec[key] = t
                got.append(t)
            if got:
                d["lost"] = sorted(set(got))
    out["tombstones"] = dict(sorted(tombs.items()))
    return out, {"tombs": len(by_rec), "broken": broken}


def upgrade_results(results, node_set):
    """(결과, 바꾼 수). 49033f1 판이 붙인 `X~lost`(원인·영향·보호수단 참조, 잠재 후보 ID, 근거 경로 id)를 묘비 id로 바꾼다.
    같은 옛 열쇠를 가진 묘비가 하나면 그 묘비로, 둘 이상(서로 다른 두 기호가 같은 순번으로 차례로 잃힘)이거나 없으면
    되찾지 않는 묘비로 바꾼다. 할 일이 없으면 입력 그대로."""
    from hazop.kg import expect
    gid = (node_set or {}).get("graph_id") or results.get("graph_id")
    tombs = (node_set or {}).get("tombstones") or {}
    by_key, by_eid = {}, {}
    for t, rec in tombs.items():
        if isinstance(rec, dict):
            if rec.get("legacy_key"):
                by_key.setdefault(rec["legacy_key"], []).append(t)
            if rec.get("entity_id"):
                by_eid.setdefault(rec["entity_id"] + LEGACY_LOST, []).append(t)

    def one(key, pool):
        hit = pool.get(key) or []
        return hit[0] if len(hit) == 1 else tomb_id(gid, "legacy", "r-" + _sha8(key))

    def ref(x):
        return one(x, by_key) if isinstance(x, str) and x.endswith(LEGACY_LOST) else x

    def eid(x):
        return one(x, by_eid) if isinstance(x, str) and x.endswith(LEGACY_LOST) else x

    def exp(x):
        if not (isinstance(x, str) and x.endswith(LEGACY_LOST) and x.startswith(expect.ID_PREFIX)):
            return x
        bare = x[:-len(LEGACY_LOST)]
        rule = bare[len(expect.ID_PREFIX):].rsplit("-", 1)[0]
        hits = [k for k in by_key if expect.expectation_id(rule, k[:-len(LEGACY_LOST)]) == bare]
        t = one(hits[0], by_key) if len(hits) == 1 else tomb_id(gid, "legacy", "r-" + _sha8(x))
        return "%s%s%s" % (t, EXP_SEP, rule)
    fn = {REF: ref, EID: eid, EXP: exp}
    found = [(p, s) for p, s in FIELDS[RESULTS]
             if any(isinstance(h[k], str) and h[k].endswith(LEGACY_LOST) for h, k in walk(results, p))]
    if not found:
        return results, 0
    out = copy.deepcopy(results)
    n = 0
    for path, space in found:
        for h, k in walk(out, path):
            v = fn[space](h[k])
            n += v != h[k]
            h[k] = v
    return out, n


def legacy_marks_only(node_set):
    """B꼴 판 사진인가(표시는 있으나 id 근거가 없음): 표시는 순번 정규식에 걸린 것에만 있었다."""
    return node_set.get("graph_member_basis") is None and isinstance(node_set.get("graph_member_marks"), dict)


def legacy_marks(graph):
    """49033f1 판이 남겼을 표시(시험·측정용): 순번 정규식에 걸리고 상자가 있는 구성요소만."""
    return {n["entity_id"]: mark_of(n, ids.SEQUENCE) for n in graph.get("nodes", [])
            if _LEGACY_SEQUENCE_ID.match(str(n.get("source_object_id") or "")) and _box_ok(n.get("bbox"))}


# ---------------------------------------------------------------- 확인 필요 요약

def needs_check(node_set, results=None):
    """'참조 확인 필요' 요약(화면이 띄울 근거). {"needs_check": bool, "lost_members": {node_id: 묘비 수},
    "lost_refs": {node_id: 묘비가 된 ⑤ 대상 참조(원인·영향·보호수단·잠재 후보) 수}, "tombstones": 되찾지 못한 묘비 수(사람이
    버린 것은 빼고), "discarded": {node_id: 사람이 버렸고 되찾지 않은 묘비 수}, "discarded_refs": {node_id: lost_refs 가운데 사람이 버린 묘비를
    가리키는 수. ⑤ 항목의 대상은 사람이 고칠 몫이라 lost_refs에서 빼지 않는다},
    "unverified": 표시 없이 참조만 믿고 이은 옛 판 이전(cff108c 전 이력 줄)이 결과에 끼었는가, "unregistered": 등록되지 않은 자리 경로,
    "unproven": 이어진 것을 증명하지 못해 순번 참조를 묘비로 한 까닭들, "refs_unnamed": 새 판 구성요소에 안정 참조가 없어 묘비가 된 참조 수}."""
    ns = node_set or {}
    lost_members = {n["node_id"]: len(n["lost"]) for n in ns.get("nodes") or [] if isinstance(n, dict) and n.get("lost")}
    gone = discarded_tombs(ns)
    tombs = ns.get("tombstones") or {}
    shut = {t for t in gone if (tombs.get(t) or {}).get("found") is None}  # 겹친 다른 구간에서 되찾은 것은 뺌
    discarded = {n["node_id"]: k for n in ns.get("nodes") or [] if isinstance(n, dict)
                 for k in [sum(1 for t in n.get("discarded") or [] if t in shut)] if k}
    lost_refs, discarded_refs = {}, {}
    for cell in (results or {}).get("cells") or []:
        hits = []
        for path, space in FIELDS[RESULTS]:  # 대상 참조만 센다(근거 경로는 AI가 남긴 기록이라 세지 않음)
            if space not in (REF, EXP) or not path.startswith("cells[].entries[]") or ".history[]" in path:
                continue
            hits += [h[key] for h, key in walk({"cells": [cell]}, path) if is_tomb(h[key])]
        nid = cell.get("node_id")
        if hits:
            lost_refs[nid] = lost_refs.get(nid, 0) + len(hits)
        k = sum(1 for x in hits if x.partition(EXP_SEP)[0] in gone)
        if k:
            discarded_refs[nid] = discarded_refs.get(nid, 0) + k
    rows = [h.get("detail") or {} for h in ns.get("history") or [] if isinstance(h, dict) and h.get("op") == "migrate_version"]
    rows += [m for m in (results or {}).get("version_migrations") or [] if isinstance(m, dict)]
    unverified = any(r.get("check") == "ref" or r.get("refs_unverified") is True for r in rows)  # refs_unverified: 49033f1 판 줄
    unregistered = sorted({p for r in rows for p in r.get("unregistered") or []})
    unproven = sorted({r["unproven"] for r in rows if isinstance(r.get("unproven"), str)})
    unnamed = sum(r["refs_unnamed"] for r in rows if type(r.get("refs_unnamed")) is int)
    open_tombs = sum(1 for t, r in (ns.get("tombstones") or {}).items()
                     if isinstance(r, dict) and r.get("found") is None and t not in gone)
    return {"needs_check": bool(lost_members or lost_refs or unverified or unregistered or unproven or unnamed),
            "lost_members": lost_members, "lost_refs": lost_refs, "tombstones": open_tombs,
            "discarded": discarded, "discarded_refs": discarded_refs,
            "unverified": unverified, "unregistered": unregistered, "unproven": unproven, "refs_unnamed": unnamed}
