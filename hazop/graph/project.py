"""프로젝트 그래프: 프로젝트의 도면 그래프(graph.json)를 도면 연결점(continuation)으로 이어 붙인 하나의 망.

근거: 사용자 요청(2026-11-07) "모든 P&ID 도면을 연결해서 1개의 지식그래프". HAZOP 검토가 여러 도면을 넘나든다.
- 결과는 graph.json과 같은 모양(nodes·edges·graph_id·graph_version·validation)이라 ④ 검토구간(hazop.study.nodes),
  ⑤ AI 맥락(hazop.study.ai_cells), 탐색(hazop.analysis.explore), 경로 질의(hazop.graph.query.GraphQuery)가 그대로 쓴다.
- 노드·관계 ID = "<도면 graph_id>/<도면 안 entity_id>". 노드마다 sheet(출처 도면 graph_id)·sheet_entity_id를 남긴다.
- 도면 연결 매칭: 연결점 A(도면 D, 상대 도면 T, 배관 번호 L)의 짝은 도면 T에서 상대 도면이 D이고 배관 번호가 L인
  연결점이다. 양쪽 모두 짝이 정확히 하나이고 방향(TO·FROM)이 모순되지 않을 때만 잇는다. 이은 짝은 배관 구간 노드
  하나(sheet_link 구간)와 has_endpoint 관계 둘로 넣는다(흐름 방향: TO 쪽 → FROM 쪽).
- 잇지 않은 연결점은 사유와 함께 sheet_links에 남긴다: 상대 도면 미등록, 짝 없음, 짝 여럿, 방향 모순, 사람이 끊음.
- 사람 지정(data/drawing-links/<project_id>.json)이 자동 매칭보다 먼저다. 연결점은 source_object_id로 가리킨다.
- 같은 태그 도면 객체가 여러 도면에 있으면 합치지 않고 duplicate_tags로 남긴다(태그 유일성 규칙 유지, 사람 확인).
- 같은 입력이면 같은 graph_version·같은 결과(도면 graph_id순, 정렬 고정).
"""

import copy
import csv
import functools
import hashlib
import json
import os
import pickle
import re
import threading

from hazop import paths
from hazop.graph import sources
from hazop.graph.build import to_networkx

SCHEMA_VERSION = "0.1"
KIND = "hazop_project_graph"
MANUAL_KIND = "hazop_sheet_links"
SYSTEM_CODES_FILE = "system-codes.csv"  # APR1400 DCD 계통 약어 → 그림 번호(paths.folder("APR1400") 아래)
# 등록 경로 밖 도면(project_id 없음: 샘플 실행 등)을 묶는 프로젝트. 샘플 지식(data/knowledge-graph/SNP-SAMPLE)과 같은 이름.
UNREGISTERED_PROJECT = "SNP-SAMPLE"
LEGACY_PROJECT_DIR = "no-project"  # 이 규칙 이전 저장본 폴더(읽기 대체 경로)
SEP = "/"
PHYSICAL = "has_endpoint"
LINKED = "linked"
UNLINKED = "unlinked"
REASONS = {
    "unregistered_drawing": "상대 도면이 프로젝트에 없음(미등록·미추출)",
    "no_counterpart": "상대 도면에 짝(같은 배관 번호로 이 도면을 가리키는 연결점)이 없음",
    "ambiguous": "짝이 여럿이라 고르지 않음",
    "direction_conflict": "양쪽 방향 표시가 같음(TO·TO 또는 FROM·FROM)",
    "missing_key": "상대 도면 번호나 배관 번호를 읽을 수 없음",
    "other_system": "다른 계통 도면을 가리킴(계통 약어→그림 번호 대응이 없어 상대를 정하지 않음)",
    "description_only": "행선지 설명 글자만 있어 상대 도면을 알 수 없음",
    "system_candidate": "계통 약어 대응표의 추정 행으로 찾은 후보(사람 확인 전이라 잇지 않음)",
    "manual_unlink": "사람이 연결하지 않음으로 지정",
}
_LINE_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*$")
# 'SHEET 5"RC"', 'SHEET 2-A', 'SHEET 3 - X', 'SHEET 2'. 굽은 따옴표('SHEET 2 “D”', 9.5.1-1-S4)도 받는다.
# 'FP SHEET 2 “D”'처럼 두 글자 계통 약어를 같은 줄 앞에 쓴 것은 약어를 따로 쓴 줄('FP\nSHEET 2')과 같게 본다.
# 짝 글자를 둘 쓴 'SHEET 1 "C"/"E"'(10.4.6-1-S2)는 글자 하나로 정할 수 없어 more에 남긴다
_DCD_SHEET = re.compile(r'^(?:(?!(?:TO|FC|FO|FL|LO|LC|LT|NO|NC)\s)(?P<code>[A-Z]{2})\s+)?SHEET\s*(?P<sheet>\d+)\s*'
                        r'(?:["“”]\s*(?P<quoted>[A-Z0-9]+)\s*["“”](?P<more>(?:\s*/\s*["“”][A-Z0-9]+["“”])+)?'
                        r'|-\s*(?P<dashed>[A-Z0-9]+))?$')
_BARE_CODE = re.compile(r"^[A-Z]{2}$")  # 쌍점 없이 따로 쓴 계통 약어 줄('CC', 'PS', 범례 예 'MS'). DCD 계통 약어는 두 글자
_FIG_SHEET = re.compile(r"^(.+)-S(\d+)$")                             # 도면번호 '9.3.4-1-S1'


def project_id_of(graph):
    """도면·검토구간·결과의 프로젝트. 등록 경로 밖이면 UNREGISTERED_PROJECT."""
    return graph.get("project_id") or UNREGISTERED_PROJECT


def project_graph_id(project_id):
    return "project-%s" % project_id


def is_project_graph(graph):
    return isinstance(graph, dict) and graph.get("kind") == KIND


def nid(graph_id, entity_id):
    return "%s%s%s" % (graph_id, SEP, entity_id)


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(obj, n=12):
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()[:n]


_WS = re.compile(r"\s+")


@functools.lru_cache(maxsize=65536)
def _norm_text(s):
    return _WS.sub("", s).upper() or None


def _norm(s):
    return _norm_text(str(s or ""))


@functools.lru_cache(maxsize=65536)
def _dn_text(s):
    m = _FIG_SHEET.match(_norm_text(s) or "")
    return "%s-S%d" % (m.group(1), int(m.group(2))) if m else _norm_text(s)


def _dn(s):
    """도면번호 비교 키. '<그림>-S<시트>' 꼴이면 시트 번호 앞 0을 없앤다('9.3.4-1-S01' = '9.3.4-1-S1')."""
    return _dn_text(str(s or ""))


# ---------------------------------------------------------------- 연결점 읽기

def continuation_key(graph, node):
    """연결점 -> 매칭 키. 속성(to_drawing·line_no)을 먼저 쓰고, 없으면 라벨('TO SNP-M-102\\nRC-L010 ...')에서 읽는다."""
    attrs = node.get("attributes") or {}
    lines = [l.strip() for l in (node.get("label_text") or "").split("\n") if l.strip()]
    head = lines[0].split() if lines else []
    direction = (attrs.get("direction") or (head[0] if head else "")).strip().lower()
    direction = direction if direction in ("to", "from") else None
    drawing_number = (graph.get("source") or {}).get("drawing_number")
    # DCD 'SHEET n' 줄이 있으면 DCD식으로 읽는다. 'FROM QUADRANT A\nSUPPLY HEADER\nSHEET 1 "C"'처럼 설명이 FROM·TO로
    # 시작해도 SNP식 상대 도면번호('QUADRANT')로 읽지 않는다(방향 낱말은 방향으로만 쓴다)
    dcd = None if attrs.get("to_drawing") else _dcd_sheet_ref(lines, attrs, drawing_number)
    keyed = direction or attrs.get("to_drawing")
    unkeyed = None
    if dcd is None and not keyed and _FIG_SHEET.match(_norm(drawing_number) or ""):
        # DCD식 도면번호인데 시트 표시가 없다: 계통 약어만 있거나('CV:IRWST RETURN LINE') 설명뿐('SPRAY LINE')
        dcd = (None, None, False, "other_system" if attrs.get("to_system") else "description_only")
    if dcd is not None:
        to_drawing, line_no, sheet_only, unkeyed = dcd
        if attrs.get("line_no"):  # 속성이 라벨보다 먼저다(사람이 고친 값)
            line_no, sheet_only = attrs["line_no"], False
    else:
        to_drawing = attrs.get("to_drawing") or (head[1] if len(head) > 1 else None)
        line_no, sheet_only = attrs.get("line_no"), False
        if not line_no and len(lines) > 1:
            tok = lines[1].split()[0].upper()
            line_no = tok if _LINE_TOKEN.match(tok) else None
    return {"graph_id": graph["graph_id"], "drawing_number": drawing_number,
            "entity_id": node["entity_id"], "source_object_id": node.get("source_object_id"),
            "direction": direction, "to_drawing": to_drawing, "line_no": line_no, "sheet_only": sheet_only,
            "unkeyed": unkeyed, "system_ref": _system_ref(lines, attrs) if unkeyed == "other_system" else None,
            "to_object": attrs.get("to_object"), "label_text": node.get("label_text")}


def _system_ref(lines, attrs):
    """다른 계통 표시의 (계통 약어, 시트 번호, 짝 글자). 'CV:RDT / SHEET 5' → CV·5, 'MS\\nSHEET 2"A"' → MS·2·A.
    약어나 시트 번호가 없으면 None(계통 약어 대응표로도 상대를 찾을 수 없다)."""
    m = next((m for m in (_DCD_SHEET.match(line) for line in lines) if m), None)
    code = attrs.get("to_system") or next((line for line in lines if _BARE_CODE.match(line)), None) or \
        (m and m.group("code"))
    if m is None or not code:
        return None
    return {"code": code, "sheet": int(m.group("sheet")), "letter": _sheet_letter(m)}


def _sheet_letter(m):
    """'SHEET n' 표시의 짝 글자. 없으면 None. 둘 이상('"C"/"E"')이면 'C/E' 그대로 두어 글자 하나뿐인 표시나 글자 없는
    표시와는 잇지 않는다(글자 없는 것으로 지우면 상대의 글자 없는 표시와 잘못 이어진다, Codex 검토 재현)."""
    if m.group("more"):
        return "/".join([m.group("quoted")] + re.findall(r"[A-Z0-9]+", m.group("more")))
    return m.group("quoted") or m.group("dashed")


def _dcd_sheet_ref(lines, attrs, drawing_number):
    """APR1400 DCD식 표시(범례 그림 1.7-1). 같은 그림의 다른 시트로 가면 'SHEET 5"RC"'(시트 번호 + 짝 글자) 또는
    'SHEET 2'만 쓴다. 도면번호가 '<그림 번호>-S<시트>'(예: 9.3.4-1-S1)이면 상대 도면번호는 '<그림 번호>-S5'이고
    짝 글자를 배관 번호 자리(line_no)에 둔다. 짝 글자가 없으면 sheet_only(상대 시트에서 되짚는 화살표가 하나뿐일 때만 잇는다).
    다른 계통으로 가는 표시(to_system 있음, 또는 'CC\nSHEET 4'처럼 계통 약어만 따로 쓴 줄이 있음)와 제 시트 번호를
    가리키는 표시('PS\nSHEET 2')는 계통 약어→그림 번호 대응이 없어 상대를 정하지 않는다. 시트 번호 앞 0은 무시한다.
    DCD식이 아니면 None. → (to_drawing, line_no, sheet_only, 상대를 못 정한 사유 또는 None)"""
    m = next((m for m in (_DCD_SHEET.match(line) for line in lines) if m), None)
    if m is None:
        return None
    fig = _FIG_SHEET.match(drawing_number or "")
    letter = _sheet_letter(m)
    # 두 글자만 있는 줄은 계통 약어다(범례 'MS\nSHEET 2"A"'). 세 글자 이상('RDT')은 같은 계통 기기 이름일 수 있다
    bare_code = any(_BARE_CODE.match(line) for line in lines) or m.group("code")
    if fig is None:
        return None, None, False, None
    if attrs.get("to_system") or bare_code or int(m.group("sheet")) == int(fig.group(2)):
        return None, None, False, "other_system"
    return "%s-S%d" % (fig.group(1), int(m.group("sheet"))), letter, letter is None, None


def _ref(end):
    return "%s#%s" % (end["graph_id"], end["source_object_id"] or end["entity_id"])


# ---------------------------------------------------------------- 사람 지정 기록

def manual_path(project_id):
    return paths.folder("drawing-links", paths.safe_name(project_id) + ".json")


def load_manual(project_id):
    """사람 지정 기록. 없으면 None. 다른 종류 파일이면 ValueError.
    문서 모양: {"kind": "hazop_sheet_links", "schema_version", "project_id", "ops": [op], "log": [...]}
    op: {"op_id", "op": "link"|"unlink", "ends": [{"drawing_number", "source_object_id"}] (link 2개, unlink 1개),
         "by", "at", "reason"}"""
    path = manual_path(project_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("kind") != MANUAL_KIND:
        raise ValueError("도면 연결 지정 파일이 아님: %s" % path)
    return doc


def save_manual(project_id, ops, by, at):
    """ops 전체를 저장하고 op_id 증감을 log에 덧붙인다. 쓴 경로를 돌려준다."""
    from hazop.kg.build import write_json_atomic
    for o in ops:
        check_op(o)
    prev = load_manual(project_id) or {}
    before = [o["op_id"] for o in prev.get("ops") or []]
    after = [o["op_id"] for o in ops]
    doc = {"kind": MANUAL_KIND, "schema_version": SCHEMA_VERSION, "project_id": project_id, "ops": [dict(o) for o in ops],
           "log": list(prev.get("log") or []) + [{"at": at, "by": by, "action": "save",
                                                   "added": [i for i in after if i not in before],
                                                   "removed": [i for i in before if i not in after]}]}
    path = manual_path(project_id)
    write_json_atomic(path, doc)
    return path


def check_op(op):
    """형식 검사. 틀리면 ValueError."""
    want = {"link": 2, "unlink": 1}.get(op.get("op"))
    if want is None:
        raise ValueError("op는 link·unlink 중 하나: %r" % op.get("op"))
    ends = op.get("ends")
    if not isinstance(ends, list) or len(ends) != want or any(
            not isinstance(e, dict) or not e.get("drawing_number") or not e.get("source_object_id") for e in ends):
        raise ValueError("%s에는 drawing_number·source_object_id가 있는 끝 %d개가 필요" % (op["op"], want))
    if not op.get("op_id") or not (op.get("by") or "").strip():
        raise ValueError("op_id와 by(지정한 사람)가 필요")


# ---------------------------------------------------------------- 매칭

def match(graphs, manual_ops=(), system_codes=None):
    """(sheet_links, manual_skipped). sheet_links 항목:
    {"link_id", "status": linked|unlinked, "reason": None|REASONS 키, "detail", "origin": auto|manual,
     "from": 끝, "to": 끝|None, "candidates": [끝 ref]}. linked면 from = 흐름이 나가는 쪽(TO), to = 들어오는 쪽(FROM).
    방향을 한쪽도 모르거나 사람이 같은 방향끼리 이었으면 flow_known=False(흐름 방향을 만들지 않음)."""
    ends = []
    by_drawing = {}
    for g in graphs:
        by_drawing.setdefault(_dn((g.get("source") or {}).get("drawing_number")), []).append(g["graph_id"])
        for n in g["nodes"]:
            if n.get("kind") == "continuation":
                ends.append(continuation_key(g, n))
    by_soid = {}
    for e in ends:
        by_soid.setdefault((_norm(e["drawing_number"]), e["source_object_id"]), []).append(e)
    used, manual_used, links, skipped = set(), set(), [], []

    def record(status, reason, origin, a, b=None, candidates=(), op_id=None):
        if b is not None and status == LINKED:
            da, db = a["direction"], b["direction"]
            if da == "from" or db == "to":
                a, b = b, a
            known = bool(da or db) and da != db  # 사람이 TO·TO/FROM·FROM을 이으면 흐름 방향은 미확인
        else:
            known = None
        refs = sorted(_ref(x) for x in (a, b) if x is not None)
        links.append({"link_id": "xlink-%s" % _sha(refs, 10), "status": status, "reason": reason,
                      "detail": REASONS.get(reason) if reason else None, "origin": origin, "op_id": op_id,
                      "from": a, "to": b, "flow_known": known, "candidates": sorted(candidates)})
        used.update(_ref(x) for x in (a, b) if x is not None)

    for op in manual_ops:
        try:
            check_op(op)
        except ValueError as exc:
            skipped.append({"op_id": op.get("op_id"), "reason": str(exc)})
            continue
        hits = [by_soid.get((_norm(e["drawing_number"]), e["source_object_id"])) or [] for e in op["ends"]]
        found = [h[0] if len(h) == 1 else None for h in hits]
        if any(len(h) > 1 for h in hits):
            skipped.append({"op_id": op["op_id"], "reason": "가리키는 연결점이 여럿이라 고르지 않음"})
        elif None in found:
            skipped.append({"op_id": op["op_id"], "reason": "가리키는 연결점이 프로젝트 도면에 없음"})
        elif any(_ref(e) in used for e in found):
            skipped.append({"op_id": op["op_id"], "reason": "같은 연결점을 가리키는 앞선 지정이 있음"})
        elif op["op"] == "unlink":
            record(UNLINKED, "manual_unlink", "manual", found[0], op_id=op["op_id"])
        else:
            record(LINKED, None, "manual", found[0], found[1], op_id=op["op_id"])
    manual_used.update(used)
    # 짝 찾기 색인(ends 순서 그대로). 앞의 조건은 사람 지정 뒤로 바뀌지 않는 것만 넣는다
    back_index, system_index = {}, {}
    for x in ends:
        if _ref(x) in manual_used:
            continue
        if x["to_drawing"] and (x["line_no"] or x.get("sheet_only")):  # 키가 없는 끝(missing_key)은 짝이 아니다
            back_index.setdefault((_dn(x["drawing_number"]), _dn(x["to_drawing"])), []).append(x)
        if x.get("system_ref"):
            system_index.setdefault(_dn(x["drawing_number"]), []).append(x)

    def peers(e):
        """e를 되짚는 연결점. 짝 글자 없는 DCD 표시(sheet_only)는 글자와 상관없이 상대 시트에서 이 시트를 가리키는
        모든 화살표를 돌려준다(하나뿐이고 그것도 글자가 없을 때만 잇는다)."""
        back = [x for x in back_index.get((_dn(e["to_drawing"]), _dn(e["drawing_number"])), ()) if x is not e]
        return back if e.get("sheet_only") else [x for x in back if _norm(x["line_no"]) == _norm(e["line_no"])]

    def system_peer(e):
        """다른 계통 표시 e의 상대: 대응표가 e의 약어로 가리키는 그림의 그 시트에서, 약어가 e의 그림을 가리키고 시트 번호가
        e의 시트이며 짝 글자가 같은 표시. → (상대 또는 None, 양쪽 약어가 모두 확정인지)"""
        ref, home = e.get("system_ref"), _FIG_SHEET.match(_dn(e["drawing_number"]) or "")
        row = (system_codes or {}).get((ref or {}).get("code"))
        if not (ref and home and row) or row["figure"] == home.group(1):  # 제 그림을 가리키는 약어로는 잇지 않는다
            return None, False
        target = _dn("%s-S%d" % (row["figure"], ref["sheet"]))
        found = [x for x in system_index.get(target, ()) if x is not e and (system_codes.get(x["system_ref"]["code"]) or {}).get("figure") == home.group(1)
                 and x["system_ref"]["sheet"] == int(home.group(2))
                 and _norm(x["system_ref"]["letter"]) == _norm(ref["letter"])
                 and _norm(x["line_no"]) == _norm(e["line_no"])]  # 사람이 적은 배관 번호가 다르면 짝이 아니다
        if len(found) != 1:
            return None, False
        x = found[0]
        return x, row["confirmed"] and system_codes[x["system_ref"]["code"]]["confirmed"]

    for e in sorted(ends, key=_ref):
        if _ref(e) in used:
            continue
        if e.get("unkeyed") == "other_system" and system_codes:
            x, confirmed = system_peer(e)
            if x is not None and e["direction"] and x["direction"] and e["direction"] == x["direction"]:
                record(UNLINKED, "direction_conflict", "auto", e, candidates=[_ref(x)])
                continue
            if x is not None and confirmed and _ref(x) not in used and system_peer(x)[0] is e:
                record(LINKED, None, "auto", e, x)
                continue
            if x is not None and system_peer(x)[0] is e:  # [추론] 행에 기댄 짝은 확정하지 않고 후보로만(서로 하나뿐일 때)
                record(UNLINKED, "system_candidate", "auto", e, candidates=[_ref(x)])
                continue
        if not e["to_drawing"] or not (e["line_no"] or e.get("sheet_only")):
            record(UNLINKED, e.get("unkeyed") or "missing_key", "auto", e)
            continue
        if _dn(e["to_drawing"]) not in by_drawing:
            record(UNLINKED, "unregistered_drawing", "auto", e)
            continue
        cands = peers(e)
        if not cands:
            record(UNLINKED, "no_counterpart", "auto", e)
            continue
        back = peers(cands[0]) if len(cands) == 1 else []
        if len(cands) > 1 or len(back) != 1 or bool(e.get("sheet_only")) != bool(cands[0].get("sheet_only")):
            record(UNLINKED, "ambiguous", "auto", e, candidates=[_ref(x) for x in cands + back if x is not e])
            continue
        b = cands[0]
        if e["direction"] and b["direction"] and e["direction"] == b["direction"]:
            record(UNLINKED, "direction_conflict", "auto", e, candidates=[_ref(b)])
            continue
        record(LINKED, None, "auto", e, b)
    links.sort(key=lambda l: (l["status"] != LINKED, l["link_id"]))
    return links, skipped


# ---------------------------------------------------------------- 프로젝트 그래프

def _clone(obj):
    """JSON에서 온 값의 깊은 사본. copy.deepcopy와 같은 결과지만 143쪽이면 3초 걸리던 것이 C 구현이라 몇 배 빠르다."""
    return pickle.loads(pickle.dumps(obj, pickle.HIGHEST_PROTOCOL))


def _copy_sheet(g):
    gid = g["graph_id"]
    nodes, edges = [], []
    for n in sorted(g["nodes"], key=lambda x: x["entity_id"]):
        c = _clone(n)
        c.update(entity_id=nid(gid, n["entity_id"]), sheet=gid, sheet_entity_id=n["entity_id"])
        fd = c.get("flow_direction")
        if isinstance(fd, dict):
            fd.update({k: nid(gid, fd[k]) for k in ("from", "to") if fd.get(k)})
        nodes.append(c)
    for e in sorted(g["edges"], key=lambda x: x["entity_id"]):
        c = _clone(e)
        c.update(entity_id=nid(gid, e["entity_id"]), sheet=gid, nodes=[nid(gid, x) for x in e["nodes"]])
        for k in ("segment", "node"):
            if c.get(k):
                c[k] = nid(gid, c[k])
        edges.append(c)
    return nodes, edges


def _duplicate_tags(graphs):
    seen = {}
    for g in graphs:
        for n in g["nodes"]:
            if n.get("tag") and n.get("node_type") == "drawing_object":
                seen.setdefault(_norm(n["tag"]), []).append(nid(g["graph_id"], n["entity_id"]))
    return [{"tag": t, "entity_ids": sorted(ids), "rule": "합치지 않음 — 같은 기기인지 사람이 확인(태그 유일성)"}
            for t, ids in sorted(seen.items()) if len({i.split(SEP)[0] for i in ids}) > 1]


def build(project_id, graphs, manual_ops=(), system_codes=None, copies=None):
    """도면 그래프 목록 -> 프로젝트 그래프 dict. 도면 graph_id가 겹치면 ValueError(auto.project_graphs가 먼저 고른다).
    copies: {도면 graph_id: _copy_sheet(그 도면) 결과(새 객체)}. 주면 그 도면은 다시 복사하지 않는다(load_with_names의 쪽별 캐시)."""
    graphs = sorted(graphs, key=lambda g: g["graph_id"])
    gids = [g["graph_id"] for g in graphs]
    if len(set(gids)) != len(gids):
        raise ValueError("같은 graph_id 도면이 여럿: %s" % gids)
    nodes, edges, blockers = [], [], []
    for g in graphs:
        n, e = (copies or {}).get(g["graph_id"]) or _copy_sheet(g)
        nodes += n
        edges += e
        if (g.get("validation") or {}).get("status") != "passed":
            blockers.append({"graph_id": g["graph_id"], "reason": "도면 그래프 구조 검증이 passed가 아님(%s)"
                             % (g.get("validation") or {}).get("status")})
    links, skipped = match(graphs, manual_ops, system_codes)
    by_id = {n["entity_id"]: n for n in nodes}
    for l in links:
        for side in ("from", "to"):
            end = l[side]
            if end is not None:
                peer = l["to" if side == "from" else "from"]
                by_id[nid(end["graph_id"], end["entity_id"])]["sheet_link"] = {
                    "link_id": l["link_id"], "status": l["status"], "reason": l["reason"],
                    "peer": nid(peer["graph_id"], peer["entity_id"]) if peer else None}
        if l["status"] != LINKED:
            continue
        a, b = nid(l["from"]["graph_id"], l["from"]["entity_id"]), nid(l["to"]["graph_id"], l["to"]["entity_id"])
        line = l["from"]["line_no"] or l["to"]["line_no"]
        origin = "human_edit" if l["origin"] == "manual" else "pid_extract"
        flow = {"from": a, "to": b, "from_end": "source", "to_end": "target",
                "basis": "도면 연결 표시 TO→FROM"} if l["flow_known"] else None
        nodes.append({"entity_id": l["link_id"], "node_type": "pipe_segment", "kind": "pipe_segment",
                      "category": "pipe_segment", "classification": "classified", "tag": line, "line_no": line,
                      "label_text": "%s → %s" % (l["from"]["drawing_number"], l["to"]["drawing_number"]),
                      "line_type": "process", "flow_direction": flow, "sheet": None, "sheet_entity_id": None,
                      "sheet_link": {"link_id": l["link_id"], "status": LINKED, "origin": l["origin"]},
                      "attributes": {"line_no": line, "sheet_link": l["link_id"]}, "position": None, "origin": origin})
        for suffix, node, end in (("a", a, "source"), ("b", b, "target")):
            edges.append({"entity_id": "%s-%s" % (l["link_id"], suffix), "kind": PHYSICAL, "nodes": [l["link_id"], node],
                          "segment": l["link_id"], "node": node, "end": end, "sheet": None,
                          "sheet_link": l["link_id"], "origin": origin})
    sheets = [{"graph_id": g["graph_id"], "graph_version": g["graph_version"],
               "drawing_number": (g.get("source") or {}).get("drawing_number")} for g in graphs]
    version = "pv-" + _sha({"sheets": sheets, "links": [(l["link_id"], l["status"], l["reason"]) for l in links]})
    return {
        "schema_version": SCHEMA_VERSION, "kind": KIND, "project_id": project_id,
        "graph_id": project_graph_id(project_id), "graph_version": version,
        "source": {"drawing_number": None, "drawings": [s["drawing_number"] for s in sheets]},
        "sheets": sheets, "nodes": nodes, "edges": edges, "sheet_links": links, "manual_skipped": skipped,
        "duplicate_tags": _duplicate_tags(graphs),
        "validation": {"status": "blocked" if blockers else "passed", "blockers": blockers, "unknowns": []},
    }


def load(project_id, graph_root=None):
    """output/graph의 프로젝트 도면(project_id_of가 같은 것) + 사람 지정 기록으로 프로젝트 그래프를 만든다.
    도면이 없으면 ValueError. 지식그래프 자동 빌드(hazop.kg.auto)의 도면 선택 규칙은 바꾸지 않는다."""
    return load_with_names(project_id, graph_root)[0]


# ---------------------------------------------------------------- 쪽별 캐시(증분 빌드)
# 도면 하나를 고친 뒤 프로젝트 그래프를 다시 지을 때, 바뀌지 않은 쪽은 graph.json을 다시 파싱하거나 노드를 하나씩 복사하지 않는다.
# 열쇠는 graph.json의 (경로, 바뀐 시각 ns, 크기, inode, 만든 시각 ns): 원자적 쓰기(os.replace)나 다시 쓰기는 이 가운데 하나를 바꾼다.
# 값은 pickle 바이트로 두고 쓸 때마다 새 객체로 푼다(부르는 쪽이 고쳐도 캐시가 오염되지 않는다). 도면 사이 짝 찾기(match)와
# 프로젝트 전체에 걸친 계산(구조·버전·겹친 태그)은 매번 다시 한다. tests/test_graph_rebuild_speed가 캐시 없는 처음부터 짓기와 견준다.
_SHEETS = {}            # 경로 -> {"stamp", "graph": pickle, "copy": pickle 또는 없음}
_SHEETS_LOCK = threading.Lock()


def clear_sheet_cache():
    with _SHEETS_LOCK:
        _SHEETS.clear()


def _stamp(p):
    st = os.stat(p)
    return (st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns)


def _read_graph(p):
    """graph.json -> (새 graph dict, stamp). 읽는 사이에 파일이 바뀌면 캐시에 넣지 않는다."""
    stamp = _stamp(p)
    hit = _SHEETS.get(p)
    if hit is not None and hit["stamp"] == stamp:
        return pickle.loads(hit["graph"]), stamp
    with open(p, encoding="utf-8") as fh:
        g = json.load(fh)
    if _stamp(p) == stamp:
        with _SHEETS_LOCK:
            _SHEETS[p] = {"stamp": stamp, "graph": pickle.dumps(g, pickle.HIGHEST_PROTOCOL)}
    return g, stamp


def _sheet_copy(p, stamp, g):
    """_copy_sheet(g)와 같은 (노드, 엣지) 새 객체. g는 _read_graph(p)가 stamp 때 읽은 것."""
    hit = _SHEETS.get(p)
    if hit is not None and hit["stamp"] == stamp and hit.get("copy") is not None:
        return pickle.loads(hit["copy"])
    out = _copy_sheet(g)
    if hit is not None and hit["stamp"] == stamp:
        with _SHEETS_LOCK:
            hit["copy"] = pickle.dumps(out, pickle.HIGHEST_PROTOCOL)
    return out


def _pick(project_id, graph_root=None):
    """{graph_id: 고른 후보 {"gid", "key", "graph", "name", "path", "stamp"}}."""
    root = graph_root or paths.output_root("graph")
    cands, seen = [], set()
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, name, "graph.json")
        seen.add(p)
        try:
            g, stamp = _read_graph(p)
        except (OSError, ValueError):
            continue
        if project_id_of(g) == project_id:
            cands.append({"gid": g.get("graph_id"), "key": (os.path.getmtime(p), p), "graph": g, "name": name,
                          "path": p, "stamp": stamp})
    with _SHEETS_LOCK:                          # 이 폴더에서 사라진 도면은 캐시에서도 뺀다
        for p in [p for p in _SHEETS if os.path.dirname(os.path.dirname(p)) == root and p not in seen]:
            del _SHEETS[p]
    # 같은 graph_id는 가장 최근 것(hazop.kg.auto.project_graphs와 같은 규칙). 단 같은 도면 번호가 다른 형식으로 섞이면
    # 사람이 고르기 전에는 먼저 있던 형식을 바꾸지 않는다(hazop.graph.sources)
    chosen, _notes = sources.pick(project_id, cands, graph_root=root if graph_root else None)
    return chosen


def pick_graphs(project_id, graph_root=None):
    """{graph_id: ((바뀐 시각, 경로), graph, 폴더 이름)} 이 프로젝트의 도면. 같은 graph_id는 가장 최근 것
    (hazop.kg.auto.project_graphs와 같은 규칙). load와 ② 도면 이름표(project_ctx.graph_names)가 함께 쓴다."""
    return {gid: (c["key"], c["graph"], c["name"]) for gid, c in _pick(project_id, graph_root).items()}


def load_with_names(project_id, graph_root=None):
    """(load와 같은 프로젝트 그래프, {도면 graph_id: 고른 output/graph 폴더 이름}). 도면 파일을 한 번만 읽으려고 둔다."""
    best = _pick(project_id, graph_root)
    graphs = [best[k]["graph"] for k in sorted(best)]
    if not graphs:
        raise ValueError("프로젝트 %s에 추출한 도면이 없음" % project_id)
    copies = {c["graph"]["graph_id"]: _sheet_copy(c["path"], c["stamp"], c["graph"]) for c in best.values()}
    pg = build(project_id, graphs, (load_manual(project_id) or {}).get("ops") or (),
               load_system_codes(paths.folder("APR1400", SYSTEM_CODES_FILE)), copies=copies)
    return pg, {gid: c["name"] for gid, c in best.items() if gid}


def load_system_codes(path):
    """계통 약어 → {"figure", "confirmed"} 대응표(scripts/build_system_codes.py가 만드는 system-codes.csv). 파일이 없으면 None.
    confirmed: 출처가 [문서]이거나 사람이 '확인'한 행. 나머지([추론])는 후보 연결에만 쓴다.
    같은 약어가 여러 행이면 그림 번호가 모두 같고 모든 행이 확정일 때만 확정이다(그림이 다르면 그 약어는 쓰지 않는다)."""
    rows = read_system_code_rows(path)
    if rows is None:
        return None
    out = {}
    for r in rows:
        code, fig = (r.get("계통약어") or "").strip(), (r.get("그림번호") or "").strip()
        if not code or not fig:
            continue
        ok = (r.get("출처") or "").strip() == "[문서]" or (r.get("사람 확인") or "").strip() == "확인"
        if code in out:
            out[code] = None if out[code] is None or out[code]["figure"] != fig else \
                {"figure": fig, "confirmed": out[code]["confirmed"] and ok}
        else:
            out[code] = {"figure": fig, "confirmed": ok}
    return {k: v for k, v in out.items() if v is not None}


def read_system_code_rows(path):
    """system-codes.csv의 행 목록. 엑셀로 고쳐 저장하면 cp949가 되므로 그것도 읽는다. 읽을 수 없으면 None."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=enc) as fh:
                return list(csv.DictReader(fh))
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
    return None


# ---------------------------------------------------------------- 조회

def components(pg, kinds=(PHYSICAL,)):
    """연결 성분(노드 2개 이상) [[노드 ID]] 큰 것부터. kinds=None이면 모든 관계."""
    import networkx as nx
    g = to_networkx(pg, kinds=set(kinds) if kinds else None)
    comps = [sorted(c) for c in nx.connected_components(g) if len(c) > 1]
    return sorted(comps, key=lambda c: (-len(c), c[0]))


def sheets_of(pg, ids):
    """노드 ID 목록이 걸친 도면 graph_id(정렬). 도면 연결 구간(sheet 없음)은 세지 않는다."""
    by_id = {n["entity_id"]: n for n in pg["nodes"]}
    return sorted({by_id[i]["sheet"] for i in ids if i in by_id and by_id[i].get("sheet")})


def sheet_view(node_set, pg, graph_id):
    """검토구간 집합의 도면별 보기: 이 도면에 구성요소가 있는 구간만, 구성요소는 이 도면 것만(도면 안 entity_id).
    [{"node_id", "name", "members", "other_sheets"}]."""
    by_id = {n["entity_id"]: n for n in pg["nodes"]}
    out = []
    for n in node_set["nodes"]:
        mine = [by_id[m]["sheet_entity_id"] for m in n["members"] if (by_id.get(m) or {}).get("sheet") == graph_id]
        if mine:
            out.append({"node_id": n["node_id"], "name": n["name"], "members": sorted(mine),
                        "other_sheets": [s for s in sheets_of(pg, n["members"]) if s != graph_id]})
    return out


def lift_ids(graph_id, entity_ids):
    """도면 안 entity_id -> 프로젝트 그래프 ID(도면별 저장본을 프로젝트 그래프에서 볼 때)."""
    return [nid(graph_id, e) for e in entity_ids]


def kg_view(kg, pg):
    """프로젝트 지식그래프를 프로젝트 그래프 ID로 옮긴 사본(원본은 바꾸지 않음). P&ID 끝 (graph_id, entity_id)는
    (프로젝트 graph_id, "<graph_id>/<entity_id>")가 된다. 지식그래프가 참조한 도면 판이 프로젝트 그래프와 하나라도
    다르면 graph_refs 판을 "mismatch:..."로 두어 hazop.kg.context.content_blockers가 막게 한다."""
    view = copy.deepcopy(kg)
    pgid = pg["graph_id"]
    for l in view.get("links") or []:
        for side in ("from", "to"):
            e = (l.get("ends") or {}).get(side)
            if isinstance(e, dict) and e.get("layer") == "pid" and e.get("graph_id"):
                if e.get("entity_id") is not None:
                    e["entity_id"] = nid(e["graph_id"], e["entity_id"])
                e["graph_id"] = pgid
    have = {s["graph_id"]: s["graph_version"] for s in pg["sheets"]}
    bad = sorted(r["graph_id"] for r in kg.get("graph_refs") or [] if have.get(r["graph_id"]) != r.get("graph_version"))
    view["graph_refs"] = [{"graph_id": pgid,
                           "graph_version": "mismatch:%s" % ",".join(bad) if bad else pg["graph_version"]}]
    return view


def summary(pg):
    """측정 요약: 도면 수, 연결 매칭 결과, 연결 성분 수(물리·전체), 도면을 넘는 성분 수."""
    by_reason = {}
    for l in pg["sheet_links"]:
        if l["status"] != LINKED:
            by_reason[l["reason"]] = by_reason.get(l["reason"], 0) + 1
    phys, every = components(pg), components(pg, kinds=None)
    return {"project_id": pg["project_id"], "graph_version": pg["graph_version"], "sheets": len(pg["sheets"]),
            "continuations": sum(1 for n in pg["nodes"] if n.get("kind") == "continuation"),
            "linked": sum(1 for l in pg["sheet_links"] if l["status"] == LINKED),
            "unlinked": dict(sorted(by_reason.items())),
            "direction_conflicts": by_reason.get("direction_conflict", 0),
            "physical_components": len(phys), "all_components": len(every),
            "cross_sheet_components": sum(1 for c in every if len(sheets_of(pg, c)) > 1),
            "isolated_nodes": len(pg["nodes"]) - sum(len(c) for c in every),
            "duplicate_tags": len(pg["duplicate_tags"]), "manual_skipped": len(pg["manual_skipped"])}
