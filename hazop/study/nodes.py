"""④ 검토구간 집합(StudyNodeSet): 자동 제안·편집·확정·저장. 근거: 3단계 명세 §B nodes.py.

도면 그래프(graph.json) 하나당 집합 하나. 구성요소 = graph nodes 전부(배관 구간 포함).
프로젝트 그래프(hazop.graph.project)를 넣으면 도면 경계를 넘는 프로젝트 전체 집합이 된다. 도면 연결점(continuation)과
도면 연결 구간은 배관 경로 요소라 경로가 이어진 도면까지 한 구간에 든다. 도면별 저장본은 그대로 따로 읽힌다.
편집 연산은 모두 순수 함수다. 입력을 바꾸지 않고 새 dict를 돌려주며 history에 한 줄 덧붙인다.

저장 규격 0.2(docs/specs/study-node-segmentation.md §2). 확정은 구간마다다(state: applied → confirmed → locked).
구간끼리 겹쳐도 되고, 어느 구간에도 들지 않는 구성요소('구간 밖')가 있어도 확정할 수 있다.
구성요소·이름·basis·설계 의도가 바뀌면 그 구간의 분석 판(rev)이 1 오르고, 확정·잠금 구간은 확정 해제 뒤에만 고친다.
편집 하나가 묶음(batches, B<번호>) 하나이고 묶음마다 op의 before·after를 남긴다(되돌리기는 hazop.study.node_tools).
0.1 파일은 nodes.load_fp가 읽을 때 hazop.study.convert로 바꾼다.
"""

import copy
import json
import os
from dataclasses import dataclass

from hazop import paths, store_io
from hazop.graph.project import LEGACY_PROJECT_DIR, UNREGISTERED_PROJECT
from hazop.graph.project import _norm as drawing_key  # 프로젝트 그래프가 같은 도면으로 보는 규칙(공백 무시·대문자)
from hazop.store_io import ANY, Conflict, fingerprint, now_utc  # noqa: F401  이 모듈 이름으로도 쓴다
from hazop.study import segment

SCHEMA_VERSION = "0.2"
LEGACY_SCHEMA_VERSION = "0.1"
KIND = "hazop_study_nodes"
STATES = ("applied", "confirmed", "locked")
ACTIVE_STATES = ("confirmed", "locked")  # ⑤ 행이 있는 상태
ORIGINS = ("ai", "user", "script")
ANALYSIS_INPUTS = ("members", "name", "basis", "design_intent")  # 바뀌면 rev가 오르는 값(⑤ AI 분석 입력)
BATCH_KEEP = 50
PROPOSER = {"name": "hazop.study.nodes", "version": "0.2.0", "algorithm": segment.ALGORITHM,
            "max_active": segment.MAX_ACTIVE, "budget": segment.BUDGET, "merge_cap": segment.MERGE_CAP}
STATUSES = ("keep", "low", "excluded")
OTHER_NAME = segment.OTHER_NAME


# ---------------------------------------------------------------- 스크리닝 판정 읽기

@dataclass(frozen=True)
class Screen:
    """구간 하나의 스크리닝 판정. 화면·⑤·내보내기는 node["screen"]을 직접 읽지 않고 screens()로 받는다
    (옛 저장본의 기본값 keep을 한 곳에서만 정하려고)."""
    status: str                 # keep · low · excluded
    score: int | None           # None = 편집으로 구성요소가 바뀐 뒤 아직 다시 세지 않음
    grade: str | None           # 주요 · 일반 · 낮음, excluded면 None
    rule: str | None            # R0 · R2 · R3 · R4, 사람이 정했거나 규칙이 없으면 None
    by: str                     # rule · human
    reason: str | None = None


def screens(node_set, graph=None):
    """{node_id: Screen}. screen 필드가 없는 구간(0.1.0 제안기 저장본)은 keep·rule로 본다.
    graph를 주면 점수가 비었거나 옛 구간인 것의 점수·등급을 세어 채운다(문서는 바꾸지 않음)."""
    by_id = {n["entity_id"]: n for n in graph.get("nodes", [])} if graph else None
    out = {}
    for n in node_set["nodes"]:
        sc = n.get("screen") or {}
        status = sc.get("status") or "keep"
        value = sc.get("score")
        if value is None and by_id is not None and status != "excluded":
            value = segment.score(by_id, n["members"])
        out[n["node_id"]] = Screen(status, value, segment.grade(status, value), sc.get("rule"),
                                   sc.get("by") or "rule", sc.get("reason"))
    return out


# ---------------------------------------------------------------- 제안

def _piece_doc(piece, rule):
    return {"from": piece.pid, "members": list(piece.members), "rule": rule}


def _node_doc(seg, node_id):
    if isinstance(seg, segment.Kept):
        basis = seg.head.basis
        r2 = sum(1 for a in seg.absorbed if a.rule == "R2")
        if seg.low:
            basis = "편차원 구간에 닿지만 크기 상한(%d)에 막힌 부속 배관 묶음(R4)" % segment.MERGE_CAP
        elif r2:
            basis += " · 부속 배관 %d조각을 붙임(R2)" % r2
        return {"node_id": node_id, "name": seg.head.name, "origin": "rule", "basis": basis,
                "members": list(seg.members),
                "screen": {"status": seg.status, "score": seg.score, "grade": seg.grade,
                           "rule": "R4" if seg.low else None, "by": "rule"},
                "absorbed": [_piece_doc(a.piece, a.rule) for a in seg.absorbed]}
    if seg.rule == "R0":
        name, basis = "스크리닝 제외(범례 도면) · %s" % seg.drawing, "구간 분석에서 뺀 도면(R0)"
    else:
        name, basis = "스크리닝 제외 · %s" % seg.drawing, "편차원 구간에 닿지 않는 조각 %d개(R3)" % len(seg.parts)
    return {"node_id": node_id, "name": name, "origin": "rule", "basis": basis, "members": list(seg.members),
            "screen": {"status": "excluded", "score": None, "grade": None, "rule": seg.rule, "by": "rule"},
            "parts": [_piece_doc(p, seg.rule) for p in seg.parts]}


def propose(graph, at=None, exclude_sheets=()):
    """그래프에서 검토구간을 제안한다(status=proposed). 모든 구성요소가 정확히 한 구간에 든다.

    분할(C6)과 스크리닝(R0~R4)은 segment.cut이 하고, 여기서는 순서대로 S1…Sn을 붙여 문서로 적는다.
    exclude_sheets는 사람이 '구간 분석에서 뺌'으로 표시한 도면 graph_id(R0)다.
    absorbed·parts의 from(P…)은 한 제안 안의 조각 번호이고, 실제 경계는 거기 적은 구성요소 목록이다.
    """
    segs = segment.cut(graph, exclude_sheets)
    out_nodes = [_node_doc(s, "S%d" % (i + 1)) for i, s in enumerate(segs)]
    count = lambda st: sum(1 for n in out_nodes if n["screen"]["status"] == st)  # noqa: E731
    empty = new_set(graph)
    out = dict(empty, nodes=[dict(n, **_v2_fields("script")) for n in out_nodes])
    out["history"] = [store_io.history_row("propose", {"detail": {
        "nodes": len(out_nodes), "components": len(graph.get("nodes", [])),
        "kept": count("keep"), "low": count("low"), "excluded": count("excluded"),
        "excluded_members": sum(len(n["members"]) for n in out_nodes if n["screen"]["status"] == "excluded")}}, at)]
    return _record_batch(empty, out, "propose", "script", at,
                         tool={"name": "propose", "params": dict(PROPOSER)})


def new_set(graph):
    """구간이 없는 0.2 집합. graph_member_refs는 그래프 전체 구성요소의 안정 참조다(§2.1)."""
    from hazop.study import migrate
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "project_id": graph.get("project_id"),
        "graph_id": graph.get("graph_id"),
        "graph_version": graph.get("graph_version"),
        "drawing_number": (graph.get("source") or {}).get("drawing_number"),
        "set_rev": 0,
        "nodes": [],
        "batches": [],
        "batch_seq": 0,
        "graph_member_refs": migrate.graph_refs(graph),
        "member_digest": {},
        "history": [],
    }


def _v2_fields(origin, by=None):
    """새 구간의 상태 필드. name_by·design_intent.by는 그 값을 마지막으로 쓴 쪽이다."""
    return {"rev": 1, "origin": origin, "state": "applied", "name_by": by or origin, "design_intent": None,
            "confirmed": None, "locked": None}


# ---------------------------------------------------------------- 조회

def coverage(node_set, graph):
    """표시용 '구간 밖' 셈. uncovered는 어느 구간에도 들지 않은 구성요소다. 확정·⑤를 막지 않는다(§3)."""
    ids = {n["entity_id"] for n in graph.get("nodes", [])}
    members = {m for n in node_set["nodes"] for m in n["members"]}
    uncovered = sorted(ids - members)
    total = len(ids)
    covered = total - len(uncovered)
    return {"total": total, "covered": covered, "uncovered": uncovered, "ratio": covered / total if total else 1.0}


def outside(node_set, graph):
    """구간 밖 구성요소 ID 목록."""
    return coverage(node_set, graph)["uncovered"]


def node_state(node):
    """구간 상태. state가 없는 구간은 확정으로 본다(0.2 이전 모양으로 만든 메모리 사본. 0.2 파일은 _check_shape가 state를
    요구하고, 0.1 파일은 convert가 집합 상태대로 적는다)."""
    return node.get("state") or "confirmed"


def is_active(node):
    """확정·잠금 구간(⑤ 행이 있음)."""
    return node_state(node) in ACTIVE_STATES


def active_nodes(node_set):
    return [n for n in (node_set or {}).get("nodes") or [] if is_active(n)]


def all_confirmed(node_set):
    """구간이 있고 모두 확정·잠금이면 True. ④가 집합 단위 단추를 쓰는 동안(N2 전) 옛 '확정본'과 같은 뜻으로 쓴다."""
    ns = (node_set or {}).get("nodes") or []
    return bool(ns) and all(is_active(n) for n in ns)


def intent_text(node):
    return (node.get("design_intent") or {}).get("text")


def analysis_input(node):
    """⑤ AI 분석 입력이 되는 값. 이것이 바뀌면 rev가 오른다(§2.2)."""
    return {"members": sorted(node.get("members") or []), "name": node.get("name"), "basis": node.get("basis"),
            "design_intent": intent_text(node)}


def nodes_of(node_set, entity_id):
    return [n["node_id"] for n in node_set["nodes"] if entity_id in n["members"]]


def is_stale(node_set, graph):
    """저장본을 만든 그래프 판과 현재 그래프 판이 다르면 True(화면이 경고로 보여 준다)."""
    return node_set.get("graph_version") != graph.get("graph_version")


# ---------------------------------------------------------------- 편집(순수 함수)

def _begin(node_set, targets=()):
    """편집 대상 구간이 확정·잠금이면 ValueError. 아니면 깊은 사본."""
    for nid in targets:
        n = _find(node_set, nid)
        if node_state(n) == "locked":
            raise ValueError("%s는 잠긴 구간이라 고칠 수 없음(잠금을 풀고 확정을 해제한 뒤)" % nid)
        if is_active(n):
            raise ValueError("%s는 확정된 구간이라 확정을 해제한 뒤에 고칠 수 있음" % nid)
    return copy.deepcopy(node_set)


def _log(node_set, op, detail, at, before=None, origin="user", request=None, tool=None):
    """history에 한 줄을 남긴다. before(편집 전 집합)를 주면 구간 차이를 묶음 하나로 적고 rev를 올린다."""
    node_set["history"].append(store_io.history_row(op, {"detail": detail}, at))
    if before is not None:
        return _record_batch(before, node_set, op, origin, at, request=request, tool=tool)
    node_set["set_rev"] = (node_set.get("set_rev") or 0) + 1
    return node_set


def next_batch_id(node_set):
    return "B%d" % ((node_set.get("batch_seq") or 0) + 1)


def batch_ops(before, after):
    """[{op, node_id, before, after}] 구간 차이. 순서: after 집합 순서, 이어서 사라진 구간."""
    old = {n["node_id"]: n for n in before["nodes"]}
    new = {n["node_id"]: n for n in after["nodes"]}
    ops = []
    for nid, n in new.items():
        if nid not in old:
            ops.append({"op": "add", "node_id": nid, "before": None, "after": copy.deepcopy(n)})
        elif old[nid] != n:
            ops.append({"op": "edit", "node_id": nid, "before": copy.deepcopy(old[nid]), "after": copy.deepcopy(n)})
    ops += [{"op": "remove", "node_id": nid, "before": copy.deepcopy(n), "after": None, "index": i}
            for i, (nid, n) in enumerate(old.items()) if nid not in new]  # index: 되살릴 때 자리
    return ops


def bump_revs(before, after):
    """after에서 분석 입력이 바뀐 구간의 rev를 before보다 1 올린다(after를 고침)."""
    old = {n["node_id"]: n for n in before["nodes"]}
    for n in after["nodes"]:
        o = old.get(n["node_id"])
        if o is not None:
            n["rev"] = (o.get("rev") or 1) + (analysis_input(o) != analysis_input(n))
        n.setdefault("rev", 1)
    return after


def _record_batch(before, after, op, origin, at, request=None, tool=None, model=None):
    """after에 before와의 차이를 묶음 하나로 적는다(바뀐 것이 없으면 묶음을 만들지 않음). set_rev를 1 올린다."""
    bump_revs(before, after)
    ops = batch_ops(before, after)
    after["set_rev"] = (after.get("set_rev") or 0) + 1
    if not ops:
        return after
    bid = next_batch_id(after)
    req = request or {}
    after["batch_seq"] = int(bid[1:])
    for o in ops:
        if o["after"] is not None:
            o["after"]["batch_id"] = bid
    for n in after["nodes"]:
        if any(o["node_id"] == n["node_id"] and o["after"] is not None for o in ops):
            n["batch_id"] = bid
    digests = after.get("member_digest") or {}
    for o in ops:  # 구성요소가 바뀐 구간의 내용 지문은 옛 것이라 지운다(확정할 때 다시 셈)
        if o["after"] is None or (o["before"] or {}).get("members") != o["after"].get("members"):
            digests.pop(o["node_id"], None)
    after.setdefault("batches", []).append({
        "batch_id": bid, "origin": origin, "at": at or now_utc(), "kind": op,
        "request_id": req.get("request_id"), "request_text": (req.get("request_text") or "")[:500] or None,
        "stage": req.get("stage"), "tool": tool, "model": model, "ops": ops, "undone": None})
    while len(after["batches"]) > BATCH_KEEP:
        old = after["batches"].pop(0)
        after["history"].append(store_io.history_row("batch_summarized", {"detail": {
            "batch_id": old["batch_id"], "origin": old["origin"], "kind": old.get("kind"), "at": old["at"],
            "node_ids": sorted({o["node_id"] for o in old["ops"]}, key=lambda x: (len(x), x))}}, at))
    return after


def _find(node_set, node_id):
    for n in node_set["nodes"]:
        if n["node_id"] == node_id:
            return n
    raise ValueError("없는 검토구간: %s" % node_id)


def _settle(node):
    """조각 기록(absorbed·parts)은 구간 구성요소 안의 것만 남기고, 구성요소가 바뀌었으니 점수·등급은 비운다
    (그래프 없이는 다시 셀 수 없음. screens(node_set, graph)가 센다)."""
    keep = set(node["members"])
    for key in ("absorbed", "parts"):
        if key in node:
            node[key] = [dict(p, members=[m for m in p["members"] if m in keep]) for p in node[key]]
            node[key] = [p for p in node[key] if p["members"]]
    if node.get("screen"):  # 사람이 구성요소를 바꾼 구간의 판정은 규칙이 보장하지 않으므로 사람 판정으로 바꾼다
        node["screen"] = dict(node["screen"], score=None, grade=None, rule=None, by="human")
    return node


def _status(node):
    return (node.get("screen") or {}).get("status") or "keep"


def issued_node_ids(node_set):
    """이 집합에서 한 번이라도 쓴 구간 ID: 지금 구간과 이력(제안·분할·병합 등)에 나온 구간.
    다시 제안하면 이력과 함께 S1부터 새로 매긴다."""
    ids = {n["node_id"] for n in node_set["nodes"]}
    for h in node_set.get("history") or []:
        d = h.get("detail") if isinstance(h, dict) else None
        if not isinstance(d, dict):
            continue
        ids.update(d[k] for k in ("node_id", "new_node_id", "into") if isinstance(d.get(k), str))
        if isinstance(d.get("node_ids"), list):
            ids.update(x for x in d["node_ids"] if isinstance(x, str))
        if h.get("op") == "propose" and type(d.get("nodes")) is int:
            ids.add("S%d" % d["nodes"])
    for b in node_set.get("batches") or []:
        ids.update(o["node_id"] for o in b.get("ops") or [] if isinstance(o.get("node_id"), str))
    for n in (node_set.get("legacy") or {}).get("excluded_nodes") or []:
        if isinstance(n, dict) and isinstance(n.get("node_id"), str):
            ids.add(n["node_id"])
    if node_set.get("issued_upto"):
        ids.add("S%d" % node_set["issued_upto"])
    return ids


def _top(node_set):
    return int(store_io.next_id("S%d", issued_node_ids(node_set))[1:]) - 1


def keep_issued(restored, current):
    """실행 취소로 current를 버리고 restored로 되돌릴 때 쓴다. current가 낸 번호가 restored의 이력에 없으면
    그 가장 큰 번호를 issued_upto에 적은 사본을 돌려준다(되돌린 분할의 번호를 다른 구성요소에 다시 주지 않게).
    current가 restored에서 이어 고친 집합이 아니면(다시 제안은 S1부터 새로 매김) 적지 않는다.
    적을 것이 없으면 restored 그대로."""
    old = restored.get("history") or []
    top = _top(current)
    if (current.get("history") or [])[:len(old)] != old or top <= _top(restored):
        return restored
    return dict(restored, issued_upto=top)


def _next_id(node_set):
    """병합으로 없어진 구간의 번호도 다시 내지 않는다(이력의 'S5'가 두 구간을 가리키지 않게)."""
    return store_io.next_id("S%d", issued_node_ids(node_set))


def map_members(node_set, rename):
    """구성요소 ID를 rename({옛 ID: 새 ID})으로 바꾼 사본. members와 조각 기록(absorbed·parts)을 함께 바꾼다
    (판 이전이 members만 바꾸면 조각 기록이 옛 ID로 남아 되돌리기 근거를 잃는다)."""
    out = copy.deepcopy(node_set)
    for n in out["nodes"]:
        n["members"] = sorted(rename.get(m, m) for m in n["members"])
        for key in ("absorbed", "parts"):
            for p in n.get(key, []):
                p["members"] = sorted(rename.get(m, m) for m in p["members"])
    for p in out.get("previous") or (out.get("legacy") or {}).get("previous") or []:
        for n in p["nodes"]:
            n["members"] = sorted(rename.get(m, m) for m in n["members"])
    for b in out.get("batches") or []:  # 되돌리기의 after 비교가 새 ID로 맞게
        for o in b.get("ops") or []:
            for side in ("before", "after"):
                if isinstance(o.get(side), dict):
                    o[side]["members"] = sorted(rename.get(m, m) for m in o[side].get("members") or [])
                    for key in ("absorbed", "parts"):
                        for p in o[side].get(key, []):
                            p["members"] = sorted(rename.get(m, m) for m in p["members"])
    if out.get("graph_member_refs"):
        out["graph_member_refs"] = dict(sorted((rename.get(m, m), r) for m, r in out["graph_member_refs"].items()))
    return out


def merge(node_set, node_ids, at=None):
    """여러 구간을 하나로 합친다. 집합 안 순서로 첫 구간의 node_id를 남긴다."""
    out = _begin(node_set, [nid for nid in dict.fromkeys(node_ids)])
    wanted = set(node_ids)
    if len(wanted) < 2:
        raise ValueError("병합에는 서로 다른 구간 2개 이상 필요")
    for nid in wanted:
        _find(out, nid)
    picked = [n for n in out["nodes"] if n["node_id"] in wanted]
    statuses = {_status(n) for n in picked}
    if "excluded" in statuses and len(statuses) > 1:
        raise ValueError("스크리닝 제외 구간은 먼저 꺼낸 뒤 다른 구간과 합칠 수 있음")
    keep = picked[0]
    screened = [n for n in picked if n.get("screen")]
    if screened:
        status = "excluded" if statuses == {"excluded"} else "keep" if "keep" in statuses else "low"
        same = len({(_status(n), (n.get("screen") or {}).get("rule")) for n in picked}) == 1
        keep["screen"] = dict(keep.get("screen") or {"by": "rule"}, status=status,
                              rule=(keep.get("screen") or {}).get("rule") if same else None,
                              by=(keep.get("screen") or {}).get("by", "rule") if same else "human")
        for key in ("absorbed", "parts"):
            if any(key in n for n in picked):
                keep[key] = [p for n in picked for p in n.get(key, [])]
    keep.update({
        "name": "%s 외 %d" % (keep["name"], len(picked) - 1),
        "name_by": "user",
        "basis": "%s 병합" % "·".join(n["node_id"] for n in picked),
        "members": sorted({m for n in picked for m in n["members"]}),
    })
    _settle(keep)
    out["nodes"] = [n for n in out["nodes"] if n is keep or n["node_id"] not in wanted]
    return _log(out, "merge", {"node_ids": [n["node_id"] for n in picked], "into": keep["node_id"]}, at, before=node_set)


def split(node_set, node_id, members_for_new, name=None, at=None):
    """구간 node_id에서 members_for_new를 떼어 새 구간(바로 뒤)으로 만든다."""
    out = _begin(node_set, [node_id])
    src = _find(out, node_id)
    moved = sorted(set(members_for_new))
    if not moved:
        raise ValueError("새 구간에 넣을 구성요소가 없음")
    if not set(moved) < set(src["members"]):
        raise ValueError("떼어 낼 구성요소는 %s 구성요소의 일부(전부 아님)여야 함" % node_id)
    new = dict({"node_id": _next_id(out), "name": name or src["name"] + " 분할",
                "basis": "%s에서 나눔" % node_id, "members": moved}, **_v2_fields("user"))
    for key in ("screen", "absorbed", "parts"):
        if key in src:
            new[key] = copy.deepcopy(src[key])  # 새 구간은 원래 구간의 판정·조각 기록을 물려받고 _settle이 나눈다
    src["members"] = sorted(set(src["members"]) - set(moved))
    _settle(src)
    _settle(new)
    out["nodes"].insert(out["nodes"].index(src) + 1, new)
    return _log(out, "split", {"node_id": node_id, "new_node_id": new["node_id"], "members": moved}, at, before=node_set)


def screen_override(node_set, node_id, status, reason=None, at=None):
    """구간의 스크리닝 판정만 사람 판정으로 바꾼다(구성요소는 그대로). 제외로 옮길 때는 이유가 꼭 있어야 한다.
    같은 판정이면 입력 그대로 돌려준다(기록도 늘지 않음)."""
    if status not in STATUSES:
        raise ValueError("판정 값은 %s 중 하나" % "·".join(STATUSES))
    reason = (reason or "").strip()
    if status == "excluded" and not reason:
        raise ValueError("스크리닝 제외로 옮기는 이유 필요")
    node = _find(node_set, node_id)
    old = (node.get("screen") or {}).get("status") or "keep"
    if old == status:
        return node_set
    out = _begin(node_set, [node_id])
    node = _find(out, node_id)
    node["screen"] = {"status": status, "score": None, "grade": None, "rule": None, "by": "human",
                      "reason": reason or None}
    return _log(out, "screen_override", {"node_id": node_id, "from": old, "to": status, "reason": reason or None}, at,
                before=node_set)


def _piece_with(records, members):
    """members를 모두 품은 조각 기록 하나(구성요소로 찾는다. 나누고 다시 합치면 from이 겹칠 수 있어 from으로 찾지 않음)."""
    want = set(members or ())
    hits = [p for p in records or [] if want and want <= set(p["members"])]
    return hits[0] if len(hits) == 1 else None


def _split_piece(node_set, node_id, members, name, reason, at):
    """조각을 새 구간으로 떼고 새 구간만 사람 판정 keep으로 둔다. 원래 구간은 사람이 판정을 바꾼 것이 아니므로
    그 판정(규칙·이유)을 그대로 둔다(split의 _settle이 사람 판정으로 바꾼 것을 되돌림)."""
    before = copy.deepcopy(_find(node_set, node_id).get("screen"))
    out = split(node_set, node_id, members, name=name, at=at)
    if before is not None:
        _find(out, node_id)["screen"] = dict(before, score=None, grade=None)
    out = _human_keep(out, out["history"][-1]["detail"]["new_node_id"], reason, at)
    for o in out["batches"][-1]["ops"]:  # 판정을 고친 뒤의 구간을 묶음의 after로(되돌리기 비교가 맞게)
        if o["after"] is not None:
            o["after"] = copy.deepcopy(_find(out, o["node_id"]))
    return out


def _human_keep(out, node_id, reason, at):
    node = _find(out, node_id)
    old = (node.get("screen") or {}).get("status") or "keep"
    node["screen"] = {"status": "keep", "score": None, "grade": None, "rule": None, "by": "human", "reason": reason}
    return _log(out, "screen_override", {"node_id": node_id, "from": old, "to": "keep", "reason": reason}, at)


def take_out(node_set, node_id, members=None, at=None):
    """'스크리닝 제외' 구간에서 members가 든 조각 하나를 남긴 구간으로 꺼낸다. members가 없거나 조각이 구간 전체면
    구간 전체를 남긴 구간으로 바꾼다. members가 한 조각 안에 다 들지 않으면 ValueError. 꺼낸 구간은 사람 판정 keep."""
    node = _find(node_set, node_id)
    if (node.get("screen") or {}).get("status") != "excluded":
        raise ValueError("%s는 스크리닝 제외 구간이 아님" % node_id)
    reason = "스크리닝 제외에서 꺼냄"
    if not members:
        return screen_override(node_set, node_id, "keep", reason, at=at)
    part = _piece_with(node.get("parts"), members)
    if part is None:
        raise ValueError("고른 구성요소가 한 조각 안에 있지 않음(조각 하나의 구성요소만 고르거나 아무것도 고르지 마세요)")
    if set(part["members"]) >= set(node["members"]):
        return screen_override(node_set, node_id, "keep", reason, at=at)
    return _split_piece(node_set, node_id, part["members"], "꺼낸 조각 %s" % part["from"], reason, at)


def detach(node_set, node_id, members, at=None):
    """규칙이 붙인 조각 중 members가 든 것을 떼어 바로 뒤에 새 구간으로 둔다(사람 판정 keep, 기록 screen_override)."""
    node = _find(node_set, node_id)
    piece = _piece_with(node.get("absorbed"), members)
    if piece is None:
        raise ValueError("%s에서 고른 구성요소가 든 붙인 조각을 하나로 찾지 못함" % node_id)
    return _split_piece(node_set, node_id, piece["members"], "떼어 낸 조각 %s" % piece["from"], "규칙이 붙인 조각을 뗌", at)


def reapply(old_set, new_set):
    """다시 제안할 때 사람이 내린 스크리닝 판정(이유가 있는 by human)을 구성요소 기준으로 새 제안에 다시 얹는다.
    (새 집합, 얹지 못한 옛 구간 ID). 병합·분할 같은 구성 편집은 판정이 아니므로 세지 않는다.
    - 꺼낸·뗀 구간(keep): 그 구성요소가 새 제안의 제외 구간 한 조각 안에 있으면 같은 조각을 꺼낸다. 이미 남긴 구간에 있으면 할 일 없음.
    - 제외로 옮긴 구간: 구성요소가 똑같은 새 구간을 제외로 옮긴다.
    구성요소가 사라졌거나 위처럼 맞출 곳이 없으면 얹지 못한 것으로 알린다."""
    out = copy.deepcopy(new_set)
    dropped = []
    for n in (old_set or {}).get("nodes") or []:
        sc = n.get("screen") or {}
        if sc.get("by") != "human" or not sc.get("reason"):
            continue
        members = set(n["members"])
        owners = {o["node_id"]: o for o in out["nodes"] if members & set(o["members"])}
        try:
            if sc.get("status") == "excluded":
                same = next((o for o in owners.values() if set(o["members"]) == members), None)
                if same is None:
                    raise ValueError("구성요소가 같은 새 구간 없음")
                out = screen_override(out, same["node_id"], "excluded", sc["reason"])
            else:
                if len(owners) != 1:
                    raise ValueError("구성요소가 새 구간 하나에 있지 않음")
                (owner,) = owners.values()
                if (owner.get("screen") or {}).get("status") == "excluded":
                    out = take_out(out, owner["node_id"], sorted(members))
        except ValueError:
            dropped.append(n["node_id"])
    return out, dropped


def rename(node_set, node_id, name, at=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("빈 이름")
    out = _begin(node_set, [node_id])
    node = _find(out, node_id)
    old, node["name"], node["name_by"] = node["name"], name, "user"
    return _log(out, "rename", {"node_id": node_id, "from": old, "to": name}, at, before=node_set)


def set_design_intent(node_set, node_id, text, by="user", at=None):
    """설계 의도를 고친다. 분석 입력이라 rev가 오른다. 사람이 쓴 값은 AI가 바꾸지 못한다(apply_nodes가 막음)."""
    text = (text or "").strip()
    out = _begin(node_set, [node_id])
    node = _find(out, node_id)
    node["design_intent"] = {"text": text, "by": by} if text else None
    return _log(out, "design_intent", {"node_id": node_id}, at, before=node_set, origin=by)


def add_member(node_set, node_id, entity_id, at=None):
    out = _begin(node_set, [node_id])
    node = _find(out, node_id)
    if entity_id in node["members"]:
        raise ValueError("%s는 이미 %s에 있음" % (entity_id, node_id))
    node["members"] = sorted(node["members"] + [entity_id])
    _settle(node)
    return _log(out, "add", {"node_id": node_id, "entity_id": entity_id}, at, before=node_set)


def remove_member(node_set, node_id, entity_id, at=None):
    """구간에서 구성요소 하나를 뺀다(뺀 구성요소는 미포함으로 남는다). 마지막 구성요소를 빼면 구간도 없앤다
    (구성요소 없는 구간은 두지 않는다. 기록에 node_removed와 그 구간의 스크리닝 판정·이유를 적고, 번호는 다시 내지 않는다)."""
    out = _begin(node_set, [node_id])
    node = _find(out, node_id)
    if entity_id not in node["members"]:
        raise ValueError("%s는 %s에 없음" % (entity_id, node_id))
    node["members"] = [m for m in node["members"] if m != entity_id]
    detail = {"node_id": node_id, "entity_id": entity_id}
    if node["members"]:
        _settle(node)
    else:
        out["nodes"] = [n for n in out["nodes"] if n is not node]
        detail.update(node_removed=True, **_screen_note(node))
    return _log(out, "remove", detail, at, before=node_set)


def _screen_note(node):
    """없애는 구간의 스크리닝 판정을 이력에 남길 모양({"screen": {status, by, reason}}). 판정이 없던 구간이면 빈 dict.
    사람이 이유를 적어 내린 판정이 구간과 함께 사라져도 되짚을 수 있게 한다."""
    sc = node.get("screen")
    return {"screen": {k: sc.get(k) for k in ("status", "by", "reason")}} if sc else {}


def remove_empty(node_set, node_id, at=None):
    """구성요소가 하나도 없는 구간을 없앤다(remove_member가 구간을 없애기 전 판이 저장한 빈 구간을 치우는 길).
    구성요소가 있는 구간이면 ValueError."""
    out = _begin(node_set, [node_id])
    node = _find(out, node_id)
    if node["members"]:
        raise ValueError("%s는 구성요소가 있어 지울 수 없음(구성요소를 먼저 빼거나 다른 구간에 병합)" % node_id)
    out["nodes"] = [n for n in out["nodes"] if n is not node]
    return _log(out, "remove_empty", dict({"node_id": node_id}, **_screen_note(node)), at, before=node_set)


def confirm_nodes(node_set, graph, node_ids, reviewer, at=None):
    """고른 적용됨 구간을 확정한다(§2.2). 구간 밖 구성요소는 막지 않는다. 그래프 판이 다르거나, 고른 구간이 없거나,
    적용됨이 아니거나, 빈 구간·그래프에 없는 구성요소가 있으면 ValueError."""
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("검토자 이름 필요")
    if is_stale(node_set, graph):
        raise ValueError("그래프 판이 바뀜(%s -> %s): 검토구간을 다시 확인해야 함"
                         % (node_set.get("graph_version"), graph.get("graph_version")))
    wanted = list(dict.fromkeys(node_ids))
    if not wanted:
        raise ValueError("확정할 구간이 없음")
    out = copy.deepcopy(node_set)
    picked = [_find(out, nid) for nid in wanted]
    done = [n["node_id"] for n in picked if node_state(n) != "applied"]
    if done:
        raise ValueError("이미 확정·잠금된 구간: %s" % ", ".join(done))
    empty = [n["node_id"] for n in picked if not n["members"]]
    if empty:
        raise ValueError("빈 구간: %s" % ", ".join(empty))
    ids = {n["entity_id"] for n in graph.get("nodes", [])}
    unknown = sorted({m for n in picked for m in n["members"]} - ids)
    if unknown:
        raise ValueError("그래프에 없는 구성요소 %d개: %s" % (len(unknown), ", ".join(unknown[:5])))
    at = at or now_utc()
    from hazop.study import migrate
    for n in picked:
        n["state"] = "confirmed"
        n["confirmed"] = {"at": at, "by": reviewer, "rev": n.get("rev") or 1}
    out["graph_member_refs"] = migrate.graph_refs(graph)
    out["member_digest"] = dict(out.get("member_digest") or {},
                                **{n["node_id"]: migrate.node_digest(graph, n["members"]) for n in picked})
    return _log(out, "confirm", {"reviewer": reviewer, "node_ids": wanted, "nodes": len(wanted)}, at)


def confirm(node_set, graph, reviewer, at=None):
    """적용됨 구간을 모두 확정한다(④의 집합 단위 단추, N2 전까지). 적용됨 구간이 없으면 ValueError."""
    if not node_set["nodes"]:
        raise ValueError("검토구간이 없음")
    todo = [n["node_id"] for n in node_set["nodes"] if node_state(n) == "applied"]
    if not todo:
        raise ValueError("확정할 적용됨 구간이 없음(모두 확정·잠금)")
    return confirm_nodes(node_set, graph, todo, reviewer, at)


def reopen_node(node_set, node_id, at=None, by=None):
    """확정 해제: confirmed → applied. ⑤ 칸은 지우지 않고 보관(hold)으로 남는다(results.reconcile). 잠긴 구간은 잠금 풀기가 먼저."""
    n = _find(node_set, node_id)
    if node_state(n) == "locked":
        raise ValueError("%s는 잠긴 구간이라 잠금을 먼저 풀어야 함" % node_id)
    if node_state(n) != "confirmed":
        raise ValueError("%s는 확정된 구간이 아님" % node_id)
    out = copy.deepcopy(node_set)
    n = _find(out, node_id)
    detail = {"node_id": node_id, "confirmed": n.get("confirmed"), "by": by}
    n["state"], n["confirmed"] = "applied", None
    return _log(out, "reopen", detail, at)


def reopen(node_set, at=None):
    """확정된 구간을 모두 확정 해제한다(④의 집합 단위 단추). 잠긴 구간이 있으면 ValueError(잠금 풀기가 먼저)."""
    locked = [n["node_id"] for n in node_set["nodes"] if node_state(n) == "locked"]
    if locked:
        raise ValueError("잠긴 구간이 있어 확정을 해제할 수 없음(잠금을 먼저 풀 것): %s" % ", ".join(locked))
    todo = [n["node_id"] for n in node_set["nodes"] if node_state(n) == "confirmed"]
    if not todo:
        raise ValueError("확정되지 않은 검토구간")
    out = node_set
    for nid in todo:
        out = reopen_node(out, nid, at)
    return out


def lock_problems(node_set, node_id, results):
    """잠글 수 없는 이유(빈 목록이면 잠글 수 있음, §5.1 V-1). 확정 구간이고, 그 구간의 모든 칸이 analyzed·excluded이며
    제안(proposed) 항목이 없어야 한다."""
    n = _find(node_set, node_id)
    if node_state(n) != "confirmed":
        return ["%s는 확정 구간이 아님" % node_id]
    if results is None:
        return ["⑤ 결과가 없음"]
    cells = [c for c in results.get("cells") or [] if c.get("node_id") == node_id]
    out = [] if cells else ["⑤ 칸이 없음"]
    left = [c["deviation_id"] for c in cells if c.get("state") not in ("analyzed", "excluded")]
    if left:
        out.append("분석하지 않은 칸 %d개(%s)" % (len(left), ", ".join(left[:5])))
    drafts = sum(1 for c in cells for e in c.get("entries") or [] if e.get("status") == "proposed")
    if drafts:
        out.append("사람이 보지 않은 AI 초안 항목 %d개" % drafts)
    return out


def lock_node(node_set, node_id, by, results, at=None):
    by = (by or "").strip()
    if not by:
        raise ValueError("잠그는 사람 이름 필요")
    bad = lock_problems(node_set, node_id, results)
    if bad:
        raise ValueError("%s를 잠글 수 없음: %s" % (node_id, "; ".join(bad)))
    out = copy.deepcopy(node_set)
    at = at or now_utc()
    _find(out, node_id)["state"] = "locked"
    _find(out, node_id)["locked"] = {"at": at, "by": by, "reason": None}
    return _log(out, "lock", {"node_id": node_id, "by": by}, at)


def unlock_node(node_set, node_id, by, reason, at=None):
    """잠금 풀기: locked → confirmed. 사람 이름과 이유가 있어야 한다(§5.3)."""
    by, reason = (by or "").strip(), (reason or "").strip()
    if not by or not reason:
        raise ValueError("잠금을 푸는 사람 이름과 이유 필요")
    n = _find(node_set, node_id)
    if node_state(n) != "locked":
        raise ValueError("%s는 잠긴 구간이 아님" % node_id)
    out = copy.deepcopy(node_set)
    n = _find(out, node_id)
    detail = {"node_id": node_id, "by": by, "reason": reason, "locked": n.get("locked")}
    n["state"], n["locked"] = "confirmed", None
    if n.pop("version_changed", None):  # 잠근 동안 그래프 내용이 바뀌었음: 풀면 분석 판을 올려 항목을 다시 보게 함
        n["rev"] = (n.get("rev") or 1) + 1
        detail["version_changed"] = True
    return _log(out, "unlock", detail, at)


# ---------------------------------------------------------------- 저장

def store_dir():
    return paths.folder("study-nodes")


def store_path(project_id, graph_id):
    return os.path.join(store_dir(), paths.safe_name(project_id or UNREGISTERED_PROJECT),
                        paths.safe_name(graph_id) + ".json")


def _readable_path(project_id, graph_id):
    """저장 경로. 없고 project_id가 없으면 이 규칙 이전 폴더(no-project)의 저장본을 그대로 읽는다(옮기지 않음)."""
    path = store_path(project_id, graph_id)
    legacy = os.path.join(store_dir(), LEGACY_PROJECT_DIR, paths.safe_name(graph_id) + ".json")
    return legacy if not project_id and not os.path.isfile(path) and os.path.isfile(legacy) else path


def save(node_set, expect=ANY):
    """store_io.write_json으로 쓰고 쓴 경로를 돌려준다.
    expect(읽을 때 지문)를 주면 지금 파일이 그 값과 다를 때 쓰지 않고 Conflict를 낸다."""
    return save_fp(node_set, expect)[0]


def save_fp(node_set, expect=ANY):
    """save와 같되 (쓴 경로, 새 지문)을 돌려준다. 이어서 저장할 쪽은 이 지문을 다음 expect로 쓴다."""
    if node_set.get("read_only"):
        raise store_io.Conflict("읽기 전용으로 연 검토구간이라 저장하지 않음: %s" % node_set["read_only"])
    path = store_path(node_set.get("project_id"), node_set["graph_id"])
    return path, store_io.write_json(path, node_set, expect, sort_keys=False)


def write(path, node_set):
    store_io.write_json(path, node_set, sort_keys=False)
    return path


def load(graph):
    """graph의 저장본. 없으면 None. 판 비교는 is_stale로 한다."""
    return load_fp(graph)[0]


def load_fp(graph):
    """(graph의 저장본, 그 파일의 지문). 없으면 (None, None). 지문은 읽은 바이트에서 구한다.
    0.1 파일은 hazop.study.convert가 0.2로 바꾼다(⑤ 결과를 먼저 잇고, 백업을 먼저 쓴 뒤 결과 → 집합 순서로 씀, §2.5).
    바꾸지 못하면 메모리에서 바꾼 집합에 read_only(이유)를 붙이고 지문 None을 돌려준다(저장하면 Conflict).
    0.2 집합은 판 이전(hazop.study.migrate)을 적용한다. 판 이전이 파일을 다시 썼으면 지문은 다시 쓴 파일의 것이다.
    0.2보다 새 판은 ValueError(읽지 않음)."""
    path = _readable_path(graph.get("project_id"), graph.get("graph_id"))
    data, fp = store_io.read_bytes(path)
    if data is None:
        return None, None
    doc = json.loads(data.decode("utf-8-sig"))  # 메모장 등이 붙인 BOM도 읽는다
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("검토구간 파일이 아님: %s" % path)
    version = doc.get("schema_version") or LEGACY_SCHEMA_VERSION
    if version == LEGACY_SCHEMA_VERSION:
        check_legacy_shape(doc, path)
        from hazop.study import convert
        doc, fp = convert.on_load(doc, data, graph, path, fp)
        if doc.get("read_only"):
            return doc, None
    elif version != SCHEMA_VERSION:
        raise ValueError("이 앱보다 새 검토구간 파일(%s)이라 읽지 않음: %s" % (version, path))
    _check_shape(doc, path)
    from hazop.study import migrate
    doc, fp = migrate.on_load(doc, graph, path, fp)
    # 옛 자리(no-project)에서 읽었으면 저장할 자리에는 아직 파일이 없다. 지문은 저장할 자리의 것으로 돌려준다
    return doc, fp if path == store_path(graph.get("project_id"), graph.get("graph_id")) else None


def read_as_is(graph):
    """저장본을 바꾸지 않고 그대로 읽는다(0.1이면 0.1 모양, 변환·판 이전 없음). 없으면 None. 옛 도면별 집합을 프로젝트
    집합으로 옮길 때 쓴다(옛 파일은 손대지 않음)."""
    path = _readable_path(graph.get("project_id"), graph.get("graph_id"))
    data, _fp = store_io.read_bytes(path)
    if data is None:
        return None
    doc = json.loads(data.decode("utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("검토구간 파일이 아님: %s" % path)
    (check_legacy_shape if (doc.get("schema_version") or LEGACY_SCHEMA_VERSION) == LEGACY_SCHEMA_VERSION
     else _check_shape)(doc, path)
    return doc


def _ids_ok(v):
    return isinstance(v, list) and all(isinstance(m, str) for m in v)


def _nodes_ok(doc):
    pieces_ok = lambda v: isinstance(v, list) and all(  # noqa: E731
        isinstance(p, dict) and _ids_ok(p.get("members")) for p in v)
    opt = lambda v, t: v is None or (isinstance(v, t) and not isinstance(v, bool))  # noqa: E731
    screen_ok = lambda sc: sc is None or (  # noqa: E731
        isinstance(sc, dict) and sc.get("status") in STATUSES and opt(sc.get("score"), int)
        and opt(sc.get("grade"), str) and opt(sc.get("rule"), str) and opt(sc.get("reason"), str)
        and sc.get("by", "rule") in ("rule", "human"))
    return (isinstance(doc.get("graph_id"), str) and isinstance(doc.get("history"), list)
            and isinstance(doc.get("nodes"), list)
            and all(isinstance(n, dict) and isinstance(n.get("node_id"), str) and isinstance(n.get("name"), str)
                    and _ids_ok(n.get("members")) and screen_ok(n.get("screen"))
                    and all(k not in n or pieces_ok(n[k]) for k in ("absorbed", "parts")) for n in doc["nodes"]))


def check_legacy_shape(doc, path):
    """0.1 파일 형식 검사(옛 앱의 검사와 같음: 집합 status가 문자열이어야 함). 아니면 ValueError."""
    snap_ok = lambda p: (isinstance(p, dict) and isinstance(p.get("study_nodes_ref"), dict)  # noqa: E731
                         and isinstance(p.get("nodes"), list) and all(
                             isinstance(n, dict) and isinstance(n.get("node_id"), str) and _ids_ok(n.get("members"))
                             for n in p["nodes"]))
    upto = doc.get("issued_upto")
    prev = doc.get("previous")
    ok = (_nodes_ok(doc) and isinstance(doc.get("status"), str)
          and (upto is None or (type(upto) is int and upto > 0))
          and (prev is None or (isinstance(prev, list) and all(snap_ok(p) for p in prev))))
    if not ok:
        raise ValueError("검토구간 파일 형식이 맞지 않음: %s" % path)


def _check_shape(doc, path):
    """0.2 파일에서 판 이전·화면이 가리지 않고 꺼내 쓰는 값이 제 모양인지 본다. 아니면 ValueError."""
    when_ok = lambda v, keys: v is None or (isinstance(v, dict) and all(isinstance(v.get(k), str) for k in keys))  # noqa: E731
    ok = (_nodes_ok(doc) and type(doc.get("set_rev")) is int and isinstance(doc.get("batches"), list)
          and all(n.get("state") in STATES and n.get("origin") in ORIGINS and type(n.get("rev")) is int and n["rev"] >= 1
                  and when_ok(n.get("confirmed"), ("at", "by")) and when_ok(n.get("locked"), ("at", "by"))
                  and (n.get("design_intent") is None or isinstance((n.get("design_intent") or {}).get("text"), str))
                  for n in doc["nodes"])
          and all(isinstance(b, dict) and isinstance(b.get("batch_id"), str) and isinstance(b.get("ops"), list)
                  for b in doc["batches"])
          and isinstance(doc.get("graph_member_refs") or {}, dict) and isinstance(doc.get("member_digest") or {}, dict)
          and (doc.get("issued_upto") is None or (type(doc["issued_upto"]) is int and doc["issued_upto"] > 0)))
    if not ok:
        raise ValueError("검토구간 파일 형식이 맞지 않음: %s" % path)


# ---------------------------------------------------------------- 구간 분석에서 뺀 도면(R0)
#
# 범례·기호표처럼 공정 흐름이 없는 도면을 사람이 표시한다. 등록 정보는 판(registration_version)마다 고정된
# 기록이라 여기 두지 않고, 프로젝트마다 파일 하나에 도면번호로 적는다(다시 추출해도 그대로 이어짐).
# 표시를 바꿔도 저장된 검토구간은 그대로이고, ④에서 다시 제안할 때 반영된다.

EXCLUDED_KIND = "hazop_study_excluded_drawings"
LEGEND_WORDS = ("legend", "symbol", "범례", "기호표", "기호 및")


def excluded_path(project_id):
    return os.path.join(store_dir(), paths.safe_name(project_id or UNREGISTERED_PROJECT), "구간제외도면.json")


def load_excluded(project_id):
    """{도면번호: {by, reason, at}}. 파일이 없으면 빈 dict. 형식이 틀리면 ValueError."""
    path = excluded_path(project_id)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except RecursionError as exc:  # 지나치게 겹친 JSON도 형식 오류로 다룬다
        raise ValueError("구간 제외 도면 파일 형식이 맞지 않음: %s" % path) from exc
    drawings = doc.get("drawings") if isinstance(doc, dict) and doc.get("kind") == EXCLUDED_KIND else None
    if not isinstance(drawings, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in drawings.items()):
        raise ValueError("구간 제외 도면 파일 형식이 맞지 않음: %s" % path)
    return drawings


def excluded_mark(project_id, drawing_number):
    """그 도면의 표시 기록 {by, reason, at} 또는 None. 도면번호는 프로젝트 그래프와 같은 규칙으로 맞춘다."""
    key = drawing_key(drawing_number)
    return next((v for k, v in load_excluded(project_id).items() if key and drawing_key(k) == key), None)


def set_excluded(project_id, drawing_number, excluded, by, reason=None, at=None):
    """도면 하나를 구간 분석에서 빼거나(excluded=True) 다시 넣는다. 같은 상태면 파일을 바꾸지 않는다. 쓴 경로."""
    drawing_number = (drawing_number or "").strip()
    by = (by or "").strip()
    if not drawing_number:
        raise ValueError("도면번호가 없는 도면은 표시할 수 없음(먼저 도면번호를 확정)")
    if not by:
        raise ValueError("표시한 사람 이름 필요")
    drawings = dict(load_excluded(project_id))
    same = [k for k in drawings if drawing_key(k) == drawing_key(drawing_number)]
    if bool(excluded) == bool(same):
        return excluded_path(project_id)
    if excluded:
        drawings[drawing_number] = {"by": by, "reason": (reason or "").strip() or "범례·기호표 도면", "at": at or now_utc()}
    else:
        for k in same:
            drawings.pop(k)
    return write(excluded_path(project_id), {"schema_version": SCHEMA_VERSION, "kind": EXCLUDED_KIND,
                                             "project_id": project_id, "drawings": dict(sorted(drawings.items()))})


def exclusion_for(pg):
    """(구간 분석에서 뺀 도면의 graph_id 집합, 문제 글 또는 None). 집합은 propose의 exclude_sheets로 넘긴다.
    표시 파일을 읽지 못하면 빈 집합과 문제 글을 돌려준다. 부르는 쪽은 문제 글을 꼭 보여야 한다(뺀 도면이 말없이
    다시 분석에 들어가지 않게)."""
    try:
        marked = load_excluded(pg.get("project_id"))
    except (OSError, ValueError) as exc:
        return frozenset(), "구간 분석에서 뺀 도면 표시를 읽지 못해 모든 도면으로 제안합니다(%s)" % exc
    sheets = pg.get("sheets") or [{"graph_id": pg.get("graph_id"),
                                   "drawing_number": (pg.get("source") or {}).get("drawing_number")}]
    keys = {drawing_key(k) for k in marked}
    return frozenset(s["graph_id"] for s in sheets if drawing_key(s.get("drawing_number")) in keys - {None}), None


def looks_like_legend(*texts):
    """파일 이름·표제에 범례·기호표 낱말이 있으면 True. 표시를 제안할 때만 쓰고 스스로 빼지는 않는다."""
    low = " ".join(t for t in texts if t).lower()
    return any(w in low for w in LEGEND_WORDS)


def any_confirmed(project_only=False):
    """작업 루트 아래 확정된 집합이 하나라도 있으면 True(레일 ✓ 표시용). 읽을 수 없는 파일은 확정이 아닌 것으로 본다.
    project_only면 프로젝트 전체 집합(graph_id "project-…")만 센다(옛 도면별 확정본은 화면이 쓰지 않음)."""
    root = store_dir()
    if not os.path.isdir(root):
        return False
    for project in sorted(os.listdir(root)):
        folder = os.path.join(root, project)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8-sig") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError, RecursionError):
                continue
            if not isinstance(doc, dict):
                continue
            if project_only and not str(doc.get("graph_id") or "").startswith("project-"):
                continue
            if isinstance(doc, dict) and doc.get("kind") == KIND and (
                    doc.get("status") == "confirmed"
                    or any(isinstance(n, dict) and is_active(n) for n in doc.get("nodes") or [])):
                return True
    return False
