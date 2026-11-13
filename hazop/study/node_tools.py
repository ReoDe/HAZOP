"""구간을 묶음 하나로 바꾸는 앱 함수(Qt 없음). 근거: docs/specs/study-node-segmentation.md §2.3, §4.4, §6.2.

- apply_nodes: 채팅의 제안 동작(node.create·update·merge·split·remove)과 도면에서 고르기가 부른다. ops 전체를 묶음(B<번호>)
  하나로 적용하거나, 하나라도 규칙에 걸리면 아무것도 바꾸지 않고 ValueError(무엇이 왜인지 목록)를 낸다.
- undo_batch: 묶음 하나를 되돌린다. op마다 '구간 삭제'(add 되돌림)·'편집 복원'(edit 되돌림)·'되살림'(remove 되돌림)을
  구분하고, 그 사이 바뀐 구간·확정 구간·사람 판정이 있는 칸·AI가 사람 묶음을 되돌리는 경우를 막는다. 되돌리기도 새 묶음이다.
- 두 함수 모두 ⑤ 결과를 받는다(병합·삭제의 칸 처리와 되돌리기의 칸 검사). 결과가 없으면 None을 넘긴다(칸이 없는 상태).
- AI가 부르는 읽기 도구(find_major_equipment·make_candidates·outside_components)는 N3에서 이 파일에 더한다.
"""

import copy

from hazop.study import nodes
from hazop.study import results as res
from hazop.study.node_review import TAG_LIKE, drawing_tags

STAGE_LIMITS = {"representative": 5, "rest": 30, None: 5}
OPS = ("add", "edit", "merge", "split", "remove")


class Refused(ValueError):
    """규칙에 걸린 요청. reasons는 [(대상, 이유)]."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join("%s: %s" % r for r in self.reasons))


def _node(ns, nid):
    return next((n for n in ns["nodes"] if n["node_id"] == nid), None)


def _cells_of(results, nid):
    return [c for c in (results or {}).get("cells") or [] if c.get("node_id") == nid]


def _has_entries(results, nid):
    return any(c.get("entries") for c in _cells_of(results, nid))


def _has_human(results, nid):
    return any(e.get("status") in res.HUMAN_STATUSES for c in _cells_of(results, nid) for e in c.get("entries") or [])


def _move_cells(results, src, dst, at):
    """src 구간 칸의 항목을 dst 구간의 같은 item_id 칸으로 옮기고 '범위 바뀜'을 붙인다(§4.4 병합). src 칸은 지운다.
    dst 칸이 없으면 src 칸 모양으로 만든다. 옮긴 칸의 원래 상태는 dst 칸의 legacy_cells에 남긴다."""
    out = copy.deepcopy(results)
    dst_cells = {c.get("item_id"): c for c in out["cells"] if c.get("node_id") == dst["node_id"]}
    keep = []
    for c in out["cells"]:
        if c.get("node_id") != src["node_id"]:
            keep.append(c)
            continue
        target = dst_cells.get(c.get("item_id"))
        if target is None:
            target = dict(c, node_id=dst["node_id"], entries=[], state="not_analyzed", node_rev=dst.get("rev") or 1)
            target.pop("ai_run", None)
            keep.append(target)
            dst_cells[c.get("item_id")] = target
        if not c.get("entries") and c.get("state") == "not_analyzed":
            continue
        target.setdefault("legacy_cells", []).append({"from": src["node_id"], "deviation_id": c.get("deviation_id"),
                                                      "state": c.get("state"), "ai_run": c.get("ai_run")})
        for e in c.get("entries") or []:
            target["entries"].append(dict(copy.deepcopy(e), scope_changed={
                "from_rev": c.get("node_rev") or 1, "to_rev": dst.get("rev") or 1, "at": at, "merged_from": src["node_id"]}))
        if target["entries"]:
            target["state"] = "analyzed"
    out["cells"] = keep
    return out


def _archive_cells(results, nid, reason, by, at):
    out = copy.deepcopy(results)
    moved = [c for c in out["cells"] if c.get("node_id") == nid]
    out["cells"] = [c for c in out["cells"] if c.get("node_id") != nid]
    out.setdefault("archived_cells", [])
    out["archived_cells"] += [{"cell": c, "reason": reason, "at": at, "by": by}
                              for c in moved if c.get("entries") or c.get("state") != "not_analyzed"]
    return out


def _tag_problems(texts, tags):
    missing = sorted({t for text in texts if text for t in TAG_LIKE.findall(text) if t not in tags})
    return "도면에 없는 태그: %s" % ", ".join(missing[:5]) if missing else None


def apply_nodes(node_set, results, pg, ops, request, origin, set_rev, at=None, by=None):
    """(새 집합, 새 결과, batch_id). ops 형식은 §6.2. request: {request_id, request_text, stage}. origin: "ai"|"user".
    거절하면 Refused(ValueError). 결과(results)는 바꾸지 않으면 받은 것 그대로 돌려준다."""
    if origin not in ("ai", "user"):
        raise Refused([("origin", "ai 또는 user")])
    if set_rev != node_set.get("set_rev"):
        raise Refused([("set_rev", "구간이 그 사이 바뀜(읽은 판 %s, 지금 %s)" % (set_rev, node_set.get("set_rev")))])
    if not ops:
        raise Refused([("ops", "할 일이 없음")])
    at = at or nodes.now_utc()
    request = dict(request or {})
    ai = origin == "ai"
    graph_ids = {n["entity_id"] for n in pg.get("nodes", [])}
    tags = drawing_tags(pg) if ai else None
    out = copy.deepcopy(node_set)
    out_res = results
    why = []
    adds = 0

    def changeable(nid, kind, target_label=None):
        n = _node(out, nid)
        label = target_label or nid
        if n is None:
            why.append((label, "없는 구간"))
            return None
        if nodes.node_state(n) == "locked":
            why.append((label, "잠긴 구간은 %s할 수 없음" % kind))
            return None
        if nodes.is_active(n):
            why.append((label, "확정 구간은 %s할 수 없음(사람이 확정을 해제한 뒤)" % kind))
            return None
        if ai and n.get("origin") != "ai":
            why.append((label, "AI는 AI가 만든 적용됨 구간만 %s함(사람·옛 규칙 구간은 node_review 제안으로)" % kind))
            return None
        return n

    def members_ok(label, members):
        if not members:
            why.append((label, "빈 구간"))
            return False
        unknown = sorted(set(members) - graph_ids)
        if unknown:
            why.append((label, "그래프에 없는 구성요소 %d개(%s)" % (len(unknown), ", ".join(unknown[:3]))))
            return False
        return True

    for i, op in enumerate(ops):
        kind = op.get("op")
        label = "%d번째 %s" % (i + 1, kind)
        if kind not in OPS:
            why.append((label, "모르는 동작"))
            continue
        if kind in ("merge", "split", "remove") and out_res is None:
            why.append((label, "⑤ 결과 없이 병합·분할·삭제할 수 없음(칸 검사가 필요함. 결과가 없으면 빈 결과를 넘길 것)"))
            continue
        if ai:
            bad = _tag_problems([op.get("name"), op.get("design_intent"), op.get("basis")], tags)
            if bad:
                why.append((label, bad))
                continue
        if kind == "add":
            if op.get("cand_id"):
                why.append((label, "후보 ID(cand_id)로 적용하는 길은 아직 없음(N3 도구 뒤). members로 적용"))
                continue
            members = sorted(set(op.get("members") or []))
            if not members_ok(label, members):
                continue
            name = (op.get("name") or "").strip()
            if not name:
                why.append((label, "이름 없음"))
                continue
            node = dict({"node_id": nodes._next_id(out), "name": name, "basis": op.get("basis"), "members": members},
                        **nodes._v2_fields(origin))
            if (op.get("design_intent") or "").strip():
                node["design_intent"] = {"text": op["design_intent"].strip(), "by": origin}
            out["nodes"].append(node)
            adds += 1
        elif kind == "edit":
            n = changeable(op.get("node_id"), "편집", label)
            if n is None:
                continue
            if op.get("name") is not None:
                if not op["name"].strip():
                    why.append((label, "빈 이름"))
                    continue
                if ai and n.get("name_by") == "user":
                    why.append((label, "사람이 쓴 이름은 AI가 바꾸지 못함"))
                    continue
                n["name"], n["name_by"] = op["name"].strip(), origin
            if op.get("design_intent") is not None:
                if ai and (n.get("design_intent") or {}).get("by") == "user":
                    why.append((label, "사람이 쓴 설계 의도는 AI가 바꾸지 못함"))
                    continue
                text = op["design_intent"].strip()
                n["design_intent"] = {"text": text, "by": origin} if text else None
            members = sorted((set(n["members"]) | set(op.get("add") or [])) - set(op.get("remove") or []))
            if not members_ok(label, members):
                continue
            n["members"] = members
        elif kind == "merge":
            ids = list(dict.fromkeys(op.get("node_ids") or []))
            if len(ids) < 2:
                why.append((label, "병합에는 서로 다른 구간 2개 이상 필요"))
                continue
            picked = [changeable(nid, "병합", "%s(%s)" % (label, nid)) for nid in ids]
            if None in picked:
                continue
            if ai and any(_has_entries(out_res, nid) for nid in ids):
                why.append((label, "칸에 항목이 있는 구간의 병합은 사람만 함(§4.4)"))
                continue
            keep = picked[0]
            keep["members"] = sorted({m for n in picked for m in n["members"]})
            keep["name_by"] = keep.get("name_by") or origin
            for n in picked[1:]:
                if out_res is not None:
                    out_res = _move_cells(out_res, n, keep, at)
            out["nodes"] = [n for n in out["nodes"] if n is keep or n["node_id"] not in ids]
        elif kind == "split":
            n = changeable(op.get("node_id"), "분할", label)
            if n is None:
                continue
            moved = sorted(set(op.get("members") or []))
            if not moved or not set(moved) < set(n["members"]):
                why.append((label, "떼어 낼 구성요소는 그 구간 구성요소의 일부(전부 아님)여야 함"))
                continue
            if ai and _has_entries(out_res, n["node_id"]):
                why.append((label, "칸에 항목이 있는 구간의 분할은 사람만 함(§4.4)"))
                continue
            new = dict({"node_id": nodes._next_id(out), "name": (op.get("name") or n["name"] + " 분할").strip(),
                        "basis": "%s에서 나눔" % n["node_id"], "members": moved}, **nodes._v2_fields(origin))
            n["members"] = sorted(set(n["members"]) - set(moved))
            out["nodes"].insert(out["nodes"].index(n) + 1, new)
        elif kind == "remove":
            n = changeable(op.get("node_id"), "삭제", label)
            if n is None:
                continue
            if judged(out_res, n["node_id"]):
                if ai or not op.get("archive"):
                    why.append((label, "칸에 판정이 있는 구간은 지울 수 없음(옮길 구간을 고르거나 '보관'을 고를 것, 사람만)"))
                    continue
                out_res = _archive_cells(out_res, n["node_id"], "node_removed", by, at)
            elif out_res is not None and _cells_of(out_res, n["node_id"]):
                out_res = dict(out_res, cells=[c for c in out_res["cells"] if c.get("node_id") != n["node_id"]])
            out["nodes"] = [x for x in out["nodes"] if x is not n]
    limit = STAGE_LIMITS.get(request.get("stage"), STAGE_LIMITS[None])
    adds = len({n["node_id"] for n in out["nodes"]} - {n["node_id"] for n in node_set["nodes"]})  # 분할로 생긴 구간도 셈
    if ai and adds > limit:
        why.append(("요청", "한 요청에서 만들 수 있는 구간은 %d개(%s 단계), 요청은 %d개" % (limit, request.get("stage")
                                                                         or "대표", adds)))
    seen = {}
    for n in out["nodes"]:
        key = frozenset(n["members"])
        if key in seen:
            why.append((n["node_id"], "구성요소가 같은 구간 %s가 이미 있음" % seen[key]))
        seen.setdefault(key, n["node_id"])
    if why:
        raise Refused(why)
    out = nodes._record_batch(node_set, out, "apply", origin, at, request=request,
                              tool=request.get("tool"), model=request.get("model"))
    out["history"].append(nodes.store_io.history_row("apply", {"detail": {
        "batch_id": out["batches"][-1]["batch_id"], "origin": origin, "ops": len(ops)}}, at))
    return out, out_res, out["batches"][-1]["batch_id"]


def judged(results, nid):
    """그 구간 칸 가운데 사람·AI 판정이 남은 것이 있는지(항목이 있거나 칸 상태가 분석 전이 아님)."""
    return any(c.get("entries") or c.get("state") not in (None, "not_analyzed") for c in _cells_of(results, nid))


def judged_nodes(results):
    """⑤ 결과에서 판정이 남은 칸이 있는 구간 ID(정렬). 다시 제안(S1부터 새로 매김)을 막을지 정할 때 쓴다: 판정은 구간 ID로
    붙어 있어, ID를 새로 매기면 '해당 없음' 같은 판정이 구성요소가 다른 새 구간에 붙는다(총괄 검토 R7)."""
    return sorted({c.get("node_id") for c in (results or {}).get("cells") or []
                   if isinstance(c, dict) and (c.get("entries") or c.get("state") not in (None, "not_analyzed"))},
                  key=lambda x: (len(str(x)), str(x)))


def dropped_problems(before, after, results):
    """편집(before → after)으로 사라진 구간 가운데 ⑤ 칸에 판정이 있는 것 [(구간, 이유)]. 결과를 옮기지 않는 편집 경로
    (④의 nodes.merge·remove_member·remove_empty, AI 제안 받아들이기, 다시 제안)가 저장 전에 부른다(규격 §4.4).
    results가 None이면 확인할 수 없으므로 사라진 구간마다 문제로 본다."""
    gone = [n["node_id"] for n in before["nodes"] if n["node_id"] not in {x["node_id"] for x in after["nodes"]}]
    if results is None:
        return [(nid, "⑤ 결과를 읽지 못해 칸을 확인할 수 없음") for nid in gone]
    return [(nid, "⑤ 칸에 판정이 있음(병합은 결과를 옮기는 길로, 삭제는 보관을 골라야 함)") for nid in gone if judged(results, nid)]


def undo_problems(node_set, results, batch_id, requested_by):
    """묶음을 되돌릴 수 없는 이유 [(구간, 이유)] (§2.3). 빈 목록이면 되돌릴 수 있다."""
    b = next((x for x in node_set.get("batches") or [] if x["batch_id"] == batch_id), None)
    if b is None:
        return [(batch_id, "없는 묶음(되돌릴 수 있는 최근 %d개 밖)" % nodes.BATCH_KEEP)]
    if b.get("undone"):
        return [(batch_id, "이미 되돌린 묶음")]
    out = []
    if requested_by == "ai" and b.get("origin") != "ai":
        out.append((batch_id, "AI는 AI가 만든 묶음만 되돌림"))
    for o in b["ops"]:
        nid = o["node_id"]
        cur = _node(node_set, nid)
        expect = o["after"]
        if cur is not None and nodes.is_active(cur):
            out.append((nid, "확정·잠금 구간(사람이 확정을 먼저 해제해야 함)"))
            continue
        if (cur is None) != (expect is None) or (cur is not None and cur != expect):
            out.append((nid, "그 사이 바뀜(뒤 묶음이나 사람이 고침. 뒤 묶음부터 되돌릴 것)"))
            continue
        if o["op"] == "add" and judged(results, nid):
            out.append((nid, "구간 삭제인데 칸에 판정이 있음(옮길 곳 또는 보관을 사람이 고를 것)"))
        elif o["op"] == "edit" and nodes.analysis_input(o["before"]) != nodes.analysis_input(cur) \
                and _has_human(results, nid):
            out.append((nid, "편집 복원으로 분석 판이 바뀌는데 칸에 사람 판정 항목이 있음"))
        elif o["op"] == "remove" and _node(node_set, nid) is not None:
            out.append((nid, "같은 ID의 구간이 이미 있음"))
    return out


def undo_batch(node_set, results, batch_id, set_rev, by, requested_by, at=None):
    """(새 집합, 새 결과). results가 None이면 칸 검사를 할 수 없어 거절한다(§2.3). 막으면 Refused."""
    if results is None:
        raise Refused([(batch_id, "⑤ 결과 없이 되돌릴 수 없음(칸 검사가 필요함. 결과가 없으면 빈 결과를 넘길 것)")])
    if requested_by not in ("ai", "user"):
        raise Refused([("requested_by", "ai 또는 user")])
    if set_rev != node_set.get("set_rev"):
        raise Refused([("set_rev", "구간이 그 사이 바뀜(읽은 판 %s, 지금 %s)" % (set_rev, node_set.get("set_rev")))])
    why = undo_problems(node_set, results, batch_id, requested_by)
    if why:
        raise Refused(why)
    at = at or nodes.now_utc()
    b = next(x for x in node_set["batches"] if x["batch_id"] == batch_id)
    out = copy.deepcopy(node_set)
    out_res = results
    for o in reversed(b["ops"]):
        nid = o["node_id"]
        if o["op"] == "add":
            out["nodes"] = [n for n in out["nodes"] if n["node_id"] != nid]
            if _cells_of(out_res, nid):
                out_res = dict(out_res, cells=[c for c in out_res["cells"] if c.get("node_id") != nid])
        elif o["op"] == "edit":
            restored = copy.deepcopy(o["before"])
            restored["state"], restored["confirmed"] = "applied", None
            out["nodes"] = [restored if n["node_id"] == nid else n for n in out["nodes"]]
        else:
            restored = copy.deepcopy(o["before"])
            restored["state"], restored["confirmed"], restored["locked"] = "applied", None, None
            out["nodes"].insert(min(o.get("index", len(out["nodes"])), len(out["nodes"])), restored)
    bid_before = node_set
    out = nodes._record_batch(bid_before, out, "undo", requested_by, at, request={"request_text": None})
    new_bid = out["batches"][-1]["batch_id"] if out["batches"] and out["batches"][-1]["kind"] == "undo" else None
    for x in out["batches"]:
        if x["batch_id"] == batch_id:
            x["undone"] = {"at": at, "by": by, "batch_id": new_bid}
    out["history"].append(nodes.store_io.history_row("undo_batch", {"detail": {
        "batch_id": batch_id, "undo_batch_id": new_bid, "by": by, "requested_by": requested_by}}, at))
    return out, out_res
