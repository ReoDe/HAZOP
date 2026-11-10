"""④ 검토구간 집합(StudyNodeSet): 자동 제안·편집·확정·저장. 근거: 3단계 명세 §B nodes.py.

도면 그래프(graph.json) 하나당 집합 하나. 구성요소 = graph nodes 전부(배관 구간 포함).
프로젝트 그래프(hazop.graph.project)를 넣으면 도면 경계를 넘는 프로젝트 전체 집합이 된다. 도면 연결점(continuation)과
도면 연결 구간은 배관 경로 요소라 경로가 이어진 도면까지 한 구간에 든다. 도면별 저장본은 그대로 따로 읽힌다.
편집 연산은 모두 순수 함수다. 입력을 바꾸지 않고 새 dict를 돌려주며 history에 한 줄 덧붙인다.
확정된 집합은 reopen 뒤에만 고칠 수 있다.
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

SCHEMA_VERSION = "0.1"  # 필드를 더하기만 하고 옛 파일은 screen이 없으면 keep으로 읽으므로 올리지 않는다
KIND = "hazop_study_nodes"
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
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "project_id": graph.get("project_id"),
        "graph_id": graph.get("graph_id"),
        "graph_version": graph.get("graph_version"),
        "drawing_number": (graph.get("source") or {}).get("drawing_number"),
        "status": "proposed",
        "proposer": dict(PROPOSER),
        "nodes": out_nodes,
        "confirmed_at": None,
        "confirmed_by": None,
        "history": [store_io.history_row("propose", {"detail": {
            "nodes": len(out_nodes), "components": len(graph.get("nodes", [])),
            "kept": count("keep"), "low": count("low"), "excluded": count("excluded"),
            "excluded_members": sum(len(n["members"]) for n in out_nodes if n["screen"]["status"] == "excluded")}}, at)],
    }


# ---------------------------------------------------------------- 조회

def coverage(node_set, graph):
    ids = {n["entity_id"] for n in graph.get("nodes", [])}
    members = {m for n in node_set["nodes"] for m in n["members"]}
    uncovered = sorted(ids - members)
    total = len(ids)
    covered = total - len(uncovered)
    return {"total": total, "covered": covered, "uncovered": uncovered, "ratio": covered / total if total else 1.0}


def nodes_of(node_set, entity_id):
    return [n["node_id"] for n in node_set["nodes"] if entity_id in n["members"]]


def is_stale(node_set, graph):
    """저장본을 만든 그래프 판과 현재 그래프 판이 다르면 True(화면이 경고로 보여 준다)."""
    return node_set.get("graph_version") != graph.get("graph_version")


# ---------------------------------------------------------------- 편집(순수 함수)

def _begin(node_set):
    if node_set.get("status") == "confirmed":
        raise ValueError("확정된 검토구간은 reopen 뒤에 고칠 수 있음")
    return copy.deepcopy(node_set)


def _log(node_set, op, detail, at):
    node_set["history"].append(store_io.history_row(op, {"detail": detail}, at))
    return node_set


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
    return ids


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
    for p in out.get("previous") or []:
        for n in p["nodes"]:
            n["members"] = sorted(rename.get(m, m) for m in n["members"])
    return out


def merge(node_set, node_ids, at=None):
    """여러 구간을 하나로 합친다. 집합 안 순서로 첫 구간의 node_id를 남긴다."""
    out = _begin(node_set)
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
        "origin": "merged",
        "basis": "%s 병합" % "·".join(n["node_id"] for n in picked),
        "members": sorted({m for n in picked for m in n["members"]}),
    })
    _settle(keep)
    out["nodes"] = [n for n in out["nodes"] if n is keep or n["node_id"] not in wanted]
    return _log(out, "merge", {"node_ids": [n["node_id"] for n in picked], "into": keep["node_id"]}, at)


def split(node_set, node_id, members_for_new, name=None, at=None):
    """구간 node_id에서 members_for_new를 떼어 새 구간(바로 뒤)으로 만든다."""
    out = _begin(node_set)
    src = _find(out, node_id)
    moved = sorted(set(members_for_new))
    if not moved:
        raise ValueError("새 구간에 넣을 구성요소가 없음")
    if not set(moved) < set(src["members"]):
        raise ValueError("떼어 낼 구성요소는 %s 구성요소의 일부(전부 아님)여야 함" % node_id)
    new = {"node_id": _next_id(out), "name": name or src["name"] + " 분할", "origin": "split",
           "basis": "%s에서 나눔" % node_id, "members": moved}
    for key in ("screen", "absorbed", "parts"):
        if key in src:
            new[key] = copy.deepcopy(src[key])  # 새 구간은 원래 구간의 판정·조각 기록을 물려받고 _settle이 나눈다
    src["members"] = sorted(set(src["members"]) - set(moved))
    _settle(src)
    _settle(new)
    out["nodes"].insert(out["nodes"].index(src) + 1, new)
    return _log(out, "split", {"node_id": node_id, "new_node_id": new["node_id"], "members": moved}, at)


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
    out = _begin(node_set)
    node = _find(out, node_id)
    node["screen"] = {"status": status, "score": None, "grade": None, "rule": None, "by": "human",
                      "reason": reason or None}
    return _log(out, "screen_override", {"node_id": node_id, "from": old, "to": status, "reason": reason or None}, at)


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
    return _human_keep(out, out["history"][-1]["detail"]["new_node_id"], reason, at)


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
    out = _begin(node_set)
    node = _find(out, node_id)
    old, node["name"] = node["name"], name
    return _log(out, "rename", {"node_id": node_id, "from": old, "to": name}, at)


def add_member(node_set, node_id, entity_id, at=None):
    out = _begin(node_set)
    node = _find(out, node_id)
    if entity_id in node["members"]:
        raise ValueError("%s는 이미 %s에 있음" % (entity_id, node_id))
    node["members"] = sorted(node["members"] + [entity_id])
    _settle(node)
    return _log(out, "add", {"node_id": node_id, "entity_id": entity_id}, at)


def remove_member(node_set, node_id, entity_id, at=None):
    out = _begin(node_set)
    node = _find(out, node_id)
    if entity_id not in node["members"]:
        raise ValueError("%s는 %s에 없음" % (entity_id, node_id))
    node["members"] = [m for m in node["members"] if m != entity_id]
    _settle(node)
    return _log(out, "remove", {"node_id": node_id, "entity_id": entity_id}, at)


def confirm(node_set, graph, reviewer, at=None):
    """확정. 그래프 판이 다르거나, 구간이 없거나, 빈 구간·그래프에 없는 구성요소·미포함 구성요소가 있으면 ValueError."""
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("검토자 이름 필요")
    out = _begin(node_set)
    if is_stale(out, graph):
        raise ValueError("그래프 판이 바뀜(%s -> %s): 검토구간을 다시 확인해야 함"
                         % (out.get("graph_version"), graph.get("graph_version")))
    if not out["nodes"]:
        raise ValueError("검토구간이 없음")
    empty = [n["node_id"] for n in out["nodes"] if not n["members"]]
    if empty:
        raise ValueError("빈 구간: %s" % ", ".join(empty))
    ids = {n["entity_id"] for n in graph.get("nodes", [])}
    unknown = sorted({m for n in out["nodes"] for m in n["members"]} - ids)
    if unknown:
        raise ValueError("그래프에 없는 구성요소 %d개: %s" % (len(unknown), ", ".join(unknown[:5])))
    by_id = {n["entity_id"]: n for n in graph.get("nodes", [])}
    leaked = [n["node_id"] for n in out["nodes"] if (n.get("screen") or {}).get("status") == "excluded"
              and (n.get("screen") or {}).get("by", "rule") == "rule" and any(segment.is_source(by_id[m]) for m in n["members"])
              and (n["screen"].get("rule") != "R0")]
    if leaked:
        raise ValueError("규칙이 만든 스크리닝 제외 구간에 편차원이 있음: %s" % ", ".join(leaked))
    cov = coverage(out, graph)
    if cov["uncovered"]:
        raise ValueError("어느 구간에도 없는 구성요소 %d개: %s"
                         % (len(cov["uncovered"]), ", ".join(cov["uncovered"][:5])))
    out.update({"status": "confirmed", "confirmed_at": at or now_utc(), "confirmed_by": reviewer})
    from hazop.study import migrate
    out.update(member_refs=migrate.member_refs(out, graph), member_digest=migrate.member_digest(graph))
    return _log(out, "confirm", {"reviewer": reviewer, "nodes": len(out["nodes"])}, out["confirmed_at"])


def reopen(node_set, at=None):
    if node_set.get("status") != "confirmed":
        raise ValueError("확정되지 않은 검토구간")
    out = copy.deepcopy(node_set)
    detail = {"confirmed_at": out["confirmed_at"], "confirmed_by": out["confirmed_by"]}
    from hazop.study import remap
    out["previous"] = remap.remember(node_set, node_set["confirmed_at"])  # 다시 확정할 때 ⑤ 결과를 잇는 열쇠
    out.update({"status": "proposed", "confirmed_at": None, "confirmed_by": None})
    return _log(out, "reopen", detail, at)


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
    확정본은 읽을 때 판 이전(hazop.study.migrate)을 적용한다. 그래프는 등록·수정·화면 열기 등 여러 길에서 다시 만들어지고
    모두 이 함수로 저장본을 읽으므로, 여기서 한 번 적용하면 어느 길로 판이 바뀌어도 확정 작업이 같은 규칙으로 이어진다.
    판 이전이 파일을 다시 썼으면 지문은 다시 쓴 파일의 것이다."""
    path = _readable_path(graph.get("project_id"), graph.get("graph_id"))
    data, fp = store_io.read_bytes(path)
    if data is None:
        return None, None
    doc = json.loads(data.decode("utf-8-sig"))  # 메모장 등이 붙인 BOM도 읽는다
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("검토구간 파일이 아님: %s" % path)
    _check_shape(doc, path)
    from hazop.study import migrate
    return migrate.on_load(doc, graph, path, fp)


def _check_shape(doc, path):
    """판 이전·화면이 가리지 않고 꺼내 쓰는 값이 제 모양인지 본다. 아니면 ValueError(화면은 경고와 함께 새로 제안한다)."""
    ids_ok = lambda v: isinstance(v, list) and all(isinstance(m, str) for m in v)  # noqa: E731
    ok = (isinstance(doc.get("graph_id"), str) and isinstance(doc.get("status"), str)
          and isinstance(doc.get("history"), list) and isinstance(doc.get("nodes"), list)
          and all(isinstance(n, dict) and isinstance(n.get("node_id"), str) and isinstance(n.get("name"), str)
                  and ids_ok(n.get("members")) for n in doc["nodes"]))
    pieces_ok = lambda v: isinstance(v, list) and all(  # noqa: E731
        isinstance(p, dict) and ids_ok(p.get("members")) for p in v)
    snap_ok = lambda p: (isinstance(p, dict) and isinstance(p.get("study_nodes_ref"), dict)  # noqa: E731
                         and isinstance(p.get("nodes"), list) and all(
                             isinstance(n, dict) and isinstance(n.get("node_id"), str) and ids_ok(n.get("members"))
                             for n in p["nodes"]))
    prev = doc.get("previous")
    ok = ok and (prev is None or (isinstance(prev, list) and all(snap_ok(p) for p in prev)))
    opt = lambda v, t: v is None or (isinstance(v, t) and not isinstance(v, bool))  # noqa: E731
    screen_ok = lambda sc: sc is None or (  # noqa: E731
        isinstance(sc, dict) and sc.get("status") in STATUSES and opt(sc.get("score"), int)
        and opt(sc.get("grade"), str) and opt(sc.get("rule"), str) and opt(sc.get("reason"), str)
        and sc.get("by", "rule") in ("rule", "human"))
    ok = ok and all(screen_ok(n.get("screen")) and all(k not in n or pieces_ok(n[k]) for k in ("absorbed", "parts"))
                    for n in doc["nodes"])
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
            if isinstance(doc, dict) and doc.get("kind") == KIND and doc.get("status") == "confirmed":
                return True
    return False
