"""구간 명령: 새 화면(웹 shell)과 채팅이 부르는 얇은 진입점. 근거: docs/specs/study-node-segmentation.md §2.2·§2.3·§5·§6.2,
명령 표 docs/units/2026-11-13-drawing-knowledge/evidence/node-commands.md.

execute(pg, name, args, by, set_rev)는 저장본(nodes.load_fp, results.load_fp)을 읽어 명령 하나를 실행하고, 바뀐 ⑤ 결과 → 집합
순서로 지문을 대조해 저장한다(읽은 뒤 파일이 바뀌었으면 쓰지 않음). 규칙은 모두 아래 함수(apply_nodes·undo_batch·confirm_nodes…)가
정하고 여기서는 인자를 옮기고 거절을 같은 모양으로 돌려줄 뿐이다.
돌려주는 값: {"ok", "command", "set_rev", "batch_id", "node_ids", "refused": [{"target", "reason"}]}.
"""

from hazop import store_io
from hazop.study import node_tools as nt
from hazop.study import nodes
from hazop.study import results as res


def _edit(ns, doc, pg, ops, by, origin, request):
    new, new_doc, bid = nt.apply_nodes(ns, doc, pg, ops, dict(request or {}), origin, ns["set_rev"], by=by)
    return new, new_doc, bid


def _create(ns, doc, pg, a, by, origin, request):
    ops = [dict({"op": "add"}, **{k: v for k, v in item.items() if k in ("cand_id", "members", "name", "design_intent",
                                                                          "basis", "params")})
           for item in a.get("items") or []]
    return _edit(ns, doc, pg, ops, by, origin, request)


def _one(op):
    return lambda ns, doc, pg, a, by, origin, request: _edit(ns, doc, pg, [op(a)], by, origin, request)


def _state(fn):
    def run(ns, doc, pg, a, by, origin, request):
        if origin != "user":
            raise nt.Refused([("origin", "확정·확정 해제·잠금·잠금 풀기는 사람만 함(채팅 규격 §4.2)")])
        return fn(ns, doc, pg, a, by), doc, None
    return run


def _undo(ns, doc, pg, a, by, origin, request):
    new, new_doc = nt.undo_batch(ns, doc, a.get("batch_id"), ns["set_rev"], by, origin)
    return new, new_doc, new["batches"][-1]["batch_id"] if new.get("batches") else None


COMMANDS = {
    "create": _create,
    "add_members": _one(lambda a: {"op": "edit", "node_id": a.get("node_id"), "add": list(a.get("members") or [])}),
    "remove_members": _one(lambda a: {"op": "edit", "node_id": a.get("node_id"), "remove": list(a.get("members") or [])}),
    "rename": _one(lambda a: {"op": "edit", "node_id": a.get("node_id"), "name": a.get("name") or ""}),
    "set_design_intent": _one(lambda a: {"op": "edit", "node_id": a.get("node_id"), "design_intent": a.get("text") or ""}),
    "merge": _one(lambda a: {"op": "merge", "node_ids": list(a.get("node_ids") or [])}),
    "split": _one(lambda a: {"op": "split", "node_id": a.get("node_id"), "members": list(a.get("members") or []),
                             "name": a.get("name")}),
    "remove": _one(lambda a: {"op": "remove", "node_id": a.get("node_id"), "archive": bool(a.get("archive"))}),
    "confirm": _state(lambda ns, doc, pg, a, by: nodes.confirm_nodes(ns, pg, list(a.get("node_ids") or []), by)),
    "unconfirm": _state(lambda ns, doc, pg, a, by: nodes.reopen_node(ns, a.get("node_id"), by=by)),
    "lock": _state(lambda ns, doc, pg, a, by: nodes.lock_node(ns, a.get("node_id"), by, doc)),
    "unlock": _state(lambda ns, doc, pg, a, by: nodes.unlock_node(ns, a.get("node_id"), by, a.get("reason"))),
    "undo": _undo,
}


def _refused(name, reasons, set_rev=None):
    return {"ok": False, "command": name, "set_rev": set_rev, "batch_id": None, "node_ids": [],
            "refused": [{"target": str(t), "reason": str(r)} for t, r in reasons]}


def execute(pg, name, args, by, set_rev, origin="user", request=None):
    """명령 name을 실행하고 저장한다. set_rev(화면·채팅이 읽은 판)가 저장본과 다르면 거절한다(None이면 대조하지 않음).
    by는 사람 이름(검토자). origin은 "user"(화면·확인 상자) 또는 "ai"(채팅의 바로 동작)."""
    fn = COMMANDS.get(name)
    if fn is None:
        return _refused(name, [("command", "모르는 명령(%s 가운데 하나)" % ", ".join(sorted(COMMANDS)))])
    by = (by or "").strip()
    if not by:
        return _refused(name, [("by", "사람 이름(검토자) 필요")])
    try:
        ns, fp = nodes.load_fp(pg)
    except (OSError, ValueError) as exc:
        return _refused(name, [("node_set", "검토구간 파일을 읽을 수 없음(%s)" % exc)])
    if ns is None:
        ns = nodes.new_set(pg)
    if ns.get("read_only"):
        return _refused(name, [("node_set", "읽기 전용: %s" % ns["read_only"])], ns.get("set_rev"))
    if set_rev is not None and set_rev != ns.get("set_rev"):
        return _refused(name, [("set_rev", "구간이 그 사이 바뀜(읽은 판 %s, 지금 %s)" % (set_rev, ns.get("set_rev")))],
                        ns.get("set_rev"))
    try:
        doc, rfp = res.load_fp(ns)
    except (OSError, ValueError) as exc:
        return _refused(name, [("results", "⑤ 결과 파일을 읽을 수 없음(%s)" % exc)], ns.get("set_rev"))
    base = doc if doc is not None else res.empty_results(ns, res.load_deviations())
    try:
        new, new_doc, bid = fn(ns, base, pg, dict(args or {}), by, origin, request)
    except nt.Refused as exc:
        return _refused(name, exc.reasons, ns.get("set_rev"))
    except ValueError as exc:
        return _refused(name, [(name, exc)], ns.get("set_rev"))
    try:
        if new_doc is not base and (doc is not None or any(c.get("entries") for c in new_doc.get("cells") or [])):
            res.save_fp(new_doc, ns.get("project_id"), expect=rfp)
        nodes.save_fp(new, expect=fp)
    except store_io.Conflict as exc:
        return _refused(name, [("file", "읽은 뒤 파일이 바뀌어 저장하지 않음(%s)" % exc)], ns.get("set_rev"))
    except OSError as exc:
        return _refused(name, [("file", "저장 실패(%s)" % exc)], ns.get("set_rev"))
    before = {n["node_id"] for n in ns["nodes"]}
    made = [n["node_id"] for n in new["nodes"] if n["node_id"] not in before]
    touched = made or [x for x in (args or {}).get("node_ids") or [(args or {}).get("node_id")] if x]
    return {"ok": True, "command": name, "set_rev": new["set_rev"], "batch_id": bid, "node_ids": touched, "refused": []}
