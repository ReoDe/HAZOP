"""프로젝트 그래프: 프로젝트의 도면 그래프(graph.json)를 도면 연결점(continuation)으로 이어 붙인 하나의 망.

근거: 사용자 요청(2026-11-07) "모든 P&ID 도면을 연결해서 1개의 지식그래프". HAZOP 검토가 여러 도면을 넘나든다.
- 결과는 graph.json과 같은 모양(nodes·edges·graph_id·graph_version·validation)이라 ④ 검토구간(hazop.study.nodes),
  ⑤ AI 맥락(hazop.study.ai_cells), 탐색(hazop.analysis.explore), 경로 질의(hazop.graph.query.GraphQuery)가 그대로 쓴다.
- 노드·관계 ID = "<도면 graph_id>/<도면 안 entity_id>". 노드마다 sheet(출처 도면 graph_id)·sheet_entity_id를 남긴다.
- 도면 연결 매칭: 연결점 A(도면 D, 상대 도면 T, 배관 번호 L)의 짝은 도면 T에서 상대 도면이 D이고 배관 번호가 L인
  연결점이다. 양쪽 모두 짝이 정확히 하나이고 방향(TO·FROM)이 모순되지 않을 때만 잇는다. 이은 짝은 배관 구간 노드
  하나(sheet_link 구간)와 has_endpoint 관계 둘로 넣는다(흐름 방향: TO 쪽 → FROM 쪽).
- 잇지 않은 연결점은 사유와 함께 sheet_links에 남긴다: 상대 도면 미등록, 짝 없음, 짝 여럿, 방향 모순, 사람이 끊음.
- 사람 지정(데이터/도면연결/<project_id>.json)이 자동 매칭보다 먼저다. 연결점은 source_object_id로 가리킨다.
- 같은 태그 도면 객체가 여러 도면에 있으면 합치지 않고 duplicate_tags로 남긴다(태그 유일성 규칙 유지, 사람 확인).
- 같은 입력이면 같은 graph_version·같은 결과(도면 graph_id순, 정렬 고정).
"""

import copy
import hashlib
import json
import os
import re

import networkx as nx

from hazop import paths
from hazop.graph.build import to_networkx

SCHEMA_VERSION = "0.1"
KIND = "hazop_project_graph"
MANUAL_KIND = "hazop_sheet_links"
# 등록 경로 밖 도면(project_id 없음: 샘플 실행 등)을 묶는 프로젝트. 샘플 지식(데이터/지식/SNP-SAMPLE)과 같은 이름.
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
    "manual_unlink": "사람이 연결하지 않음으로 지정",
}
_LINE_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*$")


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


def _norm(s):
    return re.sub(r"\s+", "", str(s or "")).upper() or None


# ---------------------------------------------------------------- 연결점 읽기

def continuation_key(graph, node):
    """연결점 -> 매칭 키. 속성(to_drawing·line_no)을 먼저 쓰고, 없으면 라벨('TO SNP-M-102\\nRC-L010 ...')에서 읽는다."""
    attrs = node.get("attributes") or {}
    lines = [l.strip() for l in (node.get("label_text") or "").split("\n") if l.strip()]
    head = lines[0].split() if lines else []
    direction = (attrs.get("direction") or (head[0] if head else "")).strip().lower()
    direction = direction if direction in ("to", "from") else None
    to_drawing = attrs.get("to_drawing") or (head[1] if len(head) > 1 else None)
    line_no = attrs.get("line_no")
    if not line_no and len(lines) > 1:
        tok = lines[1].split()[0].upper()
        line_no = tok if _LINE_TOKEN.match(tok) else None
    return {"graph_id": graph["graph_id"], "drawing_number": (graph.get("source") or {}).get("drawing_number"),
            "entity_id": node["entity_id"], "source_object_id": node.get("source_object_id"),
            "direction": direction, "to_drawing": to_drawing, "line_no": line_no,
            "to_object": attrs.get("to_object"), "label_text": node.get("label_text")}


def _ref(end):
    return "%s#%s" % (end["graph_id"], end["source_object_id"] or end["entity_id"])


# ---------------------------------------------------------------- 사람 지정 기록

def manual_path(project_id):
    return paths.work_path("데이터", "도면연결", paths.safe_name(project_id) + ".json")


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

def match(graphs, manual_ops=()):
    """(sheet_links, manual_skipped). sheet_links 항목:
    {"link_id", "status": linked|unlinked, "reason": None|REASONS 키, "detail", "origin": auto|manual,
     "from": 끝, "to": 끝|None, "candidates": [끝 ref]}. linked면 from = 흐름이 나가는 쪽(TO), to = 들어오는 쪽(FROM).
    방향을 한쪽도 모르거나 사람이 같은 방향끼리 이었으면 flow_known=False(흐름 방향을 만들지 않음)."""
    ends = []
    by_drawing = {}
    for g in graphs:
        by_drawing.setdefault(_norm((g.get("source") or {}).get("drawing_number")), []).append(g["graph_id"])
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

    def peers(e):
        return [x for x in ends if _ref(x) not in manual_used and x is not e
                and _norm(x["drawing_number"]) == _norm(e["to_drawing"])
                and _norm(x["to_drawing"]) == _norm(e["drawing_number"])
                and _norm(x["line_no"]) == _norm(e["line_no"])]

    for e in sorted(ends, key=_ref):
        if _ref(e) in used:
            continue
        if not e["to_drawing"] or not e["line_no"]:
            record(UNLINKED, "missing_key", "auto", e)
            continue
        if _norm(e["to_drawing"]) not in by_drawing:
            record(UNLINKED, "unregistered_drawing", "auto", e)
            continue
        cands = peers(e)
        if not cands:
            record(UNLINKED, "no_counterpart", "auto", e)
            continue
        back = peers(cands[0]) if len(cands) == 1 else []
        if len(cands) > 1 or len(back) != 1:
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

def _copy_sheet(g):
    gid = g["graph_id"]
    nodes, edges = [], []
    for n in sorted(g["nodes"], key=lambda x: x["entity_id"]):
        c = copy.deepcopy(n)
        c.update(entity_id=nid(gid, n["entity_id"]), sheet=gid, sheet_entity_id=n["entity_id"])
        fd = c.get("flow_direction")
        if isinstance(fd, dict):
            fd.update({k: nid(gid, fd[k]) for k in ("from", "to") if fd.get(k)})
        nodes.append(c)
    for e in sorted(g["edges"], key=lambda x: x["entity_id"]):
        c = copy.deepcopy(e)
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


def build(project_id, graphs, manual_ops=()):
    """도면 그래프 목록 -> 프로젝트 그래프 dict. 도면 graph_id가 겹치면 ValueError(auto.project_graphs가 먼저 고른다)."""
    graphs = sorted(graphs, key=lambda g: g["graph_id"])
    gids = [g["graph_id"] for g in graphs]
    if len(set(gids)) != len(gids):
        raise ValueError("같은 graph_id 도면이 여럿: %s" % gids)
    nodes, edges, blockers = [], [], []
    for g in graphs:
        n, e = _copy_sheet(g)
        nodes += n
        edges += e
        if (g.get("validation") or {}).get("status") != "passed":
            blockers.append({"graph_id": g["graph_id"], "reason": "도면 그래프 구조 검증이 passed가 아님(%s)"
                             % (g.get("validation") or {}).get("status")})
    links, skipped = match(graphs, manual_ops)
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
        flow = {"from": a, "to": b, "from_end": "source", "to_end": "target",
                "basis": "도면 연결 표시 TO→FROM"} if l["flow_known"] else None
        nodes.append({"entity_id": l["link_id"], "node_type": "pipe_segment", "kind": "pipe_segment",
                      "category": "pipe_segment", "classification": "classified", "tag": line, "line_no": line,
                      "label_text": "%s → %s" % (l["from"]["drawing_number"], l["to"]["drawing_number"]),
                      "line_type": "process", "flow_direction": flow, "sheet": None, "sheet_entity_id": None,
                      "sheet_link": {"link_id": l["link_id"], "status": LINKED, "origin": l["origin"]},
                      "attributes": {"line_no": line, "sheet_link": l["link_id"]}, "position": None})
        for suffix, node, end in (("a", a, "source"), ("b", b, "target")):
            edges.append({"entity_id": "%s-%s" % (l["link_id"], suffix), "kind": PHYSICAL, "nodes": [l["link_id"], node],
                          "segment": l["link_id"], "node": node, "end": end, "sheet": None,
                          "sheet_link": l["link_id"]})
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
    """출력/그래프의 프로젝트 도면(project_id_of가 같은 것) + 사람 지정 기록으로 프로젝트 그래프를 만든다.
    도면이 없으면 ValueError. 지식그래프 자동 빌드(hazop.kg.auto)의 도면 선택 규칙은 바꾸지 않는다."""
    root = graph_root or paths.output_root("그래프")
    best = {}
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, name, "graph.json")
        try:
            with open(p, encoding="utf-8") as fh:
                g = json.load(fh)
        except (OSError, ValueError):
            continue
        if project_id_of(g) == project_id:
            key = (os.path.getmtime(p), p)  # 같은 graph_id는 가장 최근 것(hazop.kg.auto.project_graphs와 같은 규칙)
            if g.get("graph_id") not in best or key > best[g["graph_id"]][0]:
                best[g["graph_id"]] = (key, g)
    graphs = [best[k][1] for k in sorted(best)]
    if not graphs:
        raise ValueError("프로젝트 %s에 추출한 도면이 없음" % project_id)
    return build(project_id, graphs, (load_manual(project_id) or {}).get("ops") or ())


# ---------------------------------------------------------------- 조회

def components(pg, kinds=(PHYSICAL,)):
    """연결 성분(노드 2개 이상) [[노드 ID]] 큰 것부터. kinds=None이면 모든 관계."""
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
