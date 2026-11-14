"""구간 명령: 새 화면(웹 shell)과 채팅이 부르는 얇은 진입점. 근거: docs/specs/study-node-segmentation.md §2.2·§2.3·§5·§6.2,
채팅 규격 §4.3·§4.5, 명령 표 docs/units/2026-11-13-drawing-knowledge/evidence/node-commands.md.

execute(pg, name, args, author=…, confirmed_by=…, set_rev=…)는 저장본을 읽어 명령 하나를 실행하고 저장한다.
- author(누가 썼나, 기본값 없음): "user"는 사람이 화면에서 한 일, "ai"는 채팅에서 AI가 낸 동작이다. AI가 쓴 동작은 사람이
  확인 상자를 눌러도 origin ai·name_by ai로 저장하고 AI 누적 상한에 센다.
- confirmed_by(누가 눌렀나): 사람 이름. 사람이 한 일(author user)과 확정·확정 해제·잠금·풀기에는 꼭 있어야 하고, AI 동작에서는
  사람이 확인 상자를 눌렀을 때만 넣는다(그때 AI가 사람 구간을 고치는 동작과 '나머지' 단계가 열림).
- 시각(at)은 엔진이 채운다(부르는 쪽이 넘기지 않음).
- 저장 순서(두 파일이 어긋나지 않게): 바뀐 ⑤ 결과를 먼저 옆 파일(<결과>.pending.json)에 '이 집합 판(지문)을 위한 것'으로
  적고, 집합을 지문 대조로 쓰고, 그다음 결과를 지문 대조로 쓴다. 집합 쓰기가 막히면 결과는 바뀌지 않는다. 집합을 쓴 뒤
  결과를 쓰기 전에 꺼지면, 다음 명령이나 recover(pg)가 옆 파일을 보고(집합 지문과 옛 결과 지문이 모두 맞을 때만) 결과를 마저 쓴다.
돌려주는 값: {"ok", "command", "changed", "set_rev", "batch_id", "node_ids", "refused": [{"target", "code", "reason"}]}.
"""

import json
import os

from hazop import store_io
from hazop.study import node_tools as nt
from hazop.study import nodes
from hazop.study import results as res

AUTHORS = ("user", "ai")
PENDING_KIND = "hazop_results_pending"
STATE_COMMANDS = ("confirm", "unconfirm", "lock", "unlock")
PERSON_COMMANDS = STATE_COMMANDS + ("screen",)   # 누른 사람 이름(confirmed_by)이 꼭 있어야 하는 명령. screen은 AI 동작도 되지만 사람이 확인 상자를 눌러야 한다
# 거절 사유 코드: 부르는 쪽(채팅 동작 층·웹 화면)이 문구 대신 이 값으로 갈래를 나눈다. confirm은 '사람에게 물을 글(needs_confirm)을 보이고
# 그 글을 confirm 인자로 다시 보내라'는 뜻이다
CODES = ("unknown_command", "bad_actor", "stale", "conflict", "unreadable", "read_only", "rule", "confirm")


class NeedsConfirm(Exception):
    def __init__(self, target, text):
        super().__init__(text)
        self.target, self.text = target, text


def _edit(ns, doc, pg, ops, ctx):
    return nt.apply_nodes(ns, doc, pg, ops, ctx["request"], ctx["author"], ns["set_rev"], by=ctx["by"])


def _create(ns, doc, pg, a, ctx):
    ops = [dict({"op": "add"}, **{k: v for k, v in item.items() if k in ("cand_id", "members", "name", "design_intent",
                                                                          "basis", "params")})
           for item in a.get("items") or []]
    return _edit(ns, doc, pg, ops, ctx)


def _one(op):
    return lambda ns, doc, pg, a, ctx: _edit(ns, doc, pg, [op(a)], ctx)


def _each(fn):
    """node_ids 목록의 구간마다 fn을 차례로(하나라도 막히면 아무것도 저장하지 않음)."""
    def run(ns, doc, pg, a, ctx):
        ids = list(a.get("node_ids") or [])
        if not ids:
            raise ValueError("node_ids가 비었음")
        out = ns
        for nid in ids:
            out = fn(out, doc, pg, nid, a, ctx["by"])
        return out, doc, None
    return run


def _screen(ns, doc, pg, a, ctx):
    """분석에서 제외(excluded)·다시 넣기(keep). 확정·잠긴 구간이나 결과가 있는 구간을 뺄 때는 엔진이 쓴 확인 글이 confirm으로 와야 한다."""
    nid, status = a.get("node_id"), a.get("status")
    ask = nodes.screen_confirm_text(ns, doc, nid, status)
    if ask and (a.get("confirm") or "") != ask:
        raise NeedsConfirm(nid, ask)
    return nodes.set_screen(ns, nid, status, a.get("reason"), ctx["by"]), doc, None


def _undo(ns, doc, pg, a, ctx):
    new, new_doc = nt.undo_batch(ns, doc, a.get("batch_id"), ns["set_rev"], ctx["by"], ctx["author"])
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
    "confirm": lambda ns, doc, pg, a, ctx: (nodes.confirm_nodes(ns, pg, list(a.get("node_ids") or []), ctx["by"]), doc,
                                            None),
    "unconfirm": _each(lambda ns, doc, pg, nid, a, by: nodes.reopen_node(ns, nid, by=by)),
    "lock": _each(lambda ns, doc, pg, nid, a, by: nodes.lock_node(ns, nid, by, doc)),
    "unlock": _each(lambda ns, doc, pg, nid, a, by: nodes.unlock_node(ns, nid, by, a.get("reason"))),
    "screen": _screen,
    "undo": _undo,
}


def _refused(name, reasons, set_rev=None, code="rule"):
    return {"ok": False, "command": name, "set_rev": set_rev, "batch_id": None, "node_ids": [],
            "refused": [{"target": str(t), "code": code, "reason": str(r)} for t, r in reasons]}


def _pending_path(ns):
    path = res.store_path(ns.get("project_id"), ns["graph_id"])
    return path[:-5] + ".pending.json"


def _set_fp(ns):
    return store_io.fingerprint_of(store_io.dump_bytes(ns, sort_keys=False))


def recover(pg):
    """집합은 썼는데 ⑤ 결과를 쓰기 전에 끊긴 명령을 마저 쓴다. 옆 파일의 집합 지문이 지금 집합 파일과 같고, 결과 파일이
    옆 파일이 기억한 옛 지문 그대로일 때만 쓴다. 마저 썼으면 True."""
    path = nodes.store_path(pg.get("project_id"), pg.get("graph_id"))
    set_fp = store_io.fingerprint(path) if os.path.isfile(path) else None
    probe = {"project_id": pg.get("project_id"), "graph_id": pg.get("graph_id")}
    side = _pending_path(probe)
    try:
        with open(side, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(rec, dict) or rec.get("kind") != PENDING_KIND or rec.get("set_fp_after") != set_fp:
        return False
    rpath = res.store_path(pg.get("project_id"), pg.get("graph_id"))
    now = store_io.fingerprint(rpath) if os.path.isfile(rpath) else None
    if now != rec.get("results_fp_before"):
        return False  # 이미 썼거나(지문이 새 것) 그 뒤 다른 쓰기가 있었음
    try:
        res.write(rpath, rec["results"], expect=now)
    except (OSError, store_io.Conflict):
        return False
    return True


def execute(pg, name, args, *, author, confirmed_by=None, set_rev=None, request=None):
    """명령 name을 실행하고 저장한다. set_rev(읽은 판)가 저장본과 다르면 거절한다(None이면 대조하지 않음, 시험용).
    author("user"|"ai")는 꼭 넘긴다. request(AI 동작): {request_id, request_text, user_turn, confirmed_rest}."""
    fn = COMMANDS.get(name)
    if fn is None:
        return _refused(name, [("command", "모르는 명령(%s 가운데 하나)" % ", ".join(sorted(COMMANDS)))],
                        code="unknown_command")
    confirmed_by = (confirmed_by or "").strip() or None
    if author not in AUTHORS:
        return _refused(name, [("author", "누가 썼는지(author: user 또는 ai)를 넘겨야 함")], code="bad_actor")
    if (author == "user" or name in PERSON_COMMANDS) and not confirmed_by:
        return _refused(name, [("confirmed_by", "사람이 한 일·확정·잠금에는 누른 사람 이름이 있어야 함")], code="bad_actor")
    if name in STATE_COMMANDS and author != "user":
        return _refused(name, [("author", "확정·확정 해제·잠금·풀기는 사람만 함(채팅 규격 §4.2)")], code="bad_actor")
    recover(pg)
    try:
        ns, fp = nodes.load_fp(pg)
    except (OSError, ValueError) as exc:
        return _refused(name, [("node_set", "검토구간 파일을 읽을 수 없음(%s)" % exc)], code="unreadable")
    if ns is None:
        ns = nodes.new_set(pg)
    if ns.get("read_only"):
        return _refused(name, [("node_set", "읽기 전용: %s" % ns["read_only"])], ns.get("set_rev"), "read_only")
    if set_rev is not None and set_rev != ns.get("set_rev"):
        return _refused(name, [("set_rev", "구간이 그 사이 바뀜(읽은 판 %s, 지금 %s)" % (set_rev, ns.get("set_rev")))],
                        ns.get("set_rev"), "stale")
    try:
        doc, rfp = res.load_fp(ns)
    except (OSError, ValueError) as exc:
        return _refused(name, [("results", "⑤ 결과 파일을 읽을 수 없음(%s)" % exc)], ns.get("set_rev"), "unreadable")
    base = doc if doc is not None else res.empty_results(ns, res.load_deviations())
    req = dict(request or {}) if author == "ai" else {}
    req["confirmed_by"] = confirmed_by
    ctx = {"author": author, "by": confirmed_by or "AI", "request": req}
    try:
        new, new_doc, bid = fn(ns, base, pg, dict(args or {}), ctx)
    except nt.Refused as exc:
        return _refused(name, exc.reasons, ns.get("set_rev"))
    except NeedsConfirm as exc:
        return dict(_refused(name, [(exc.target, exc.text)], ns.get("set_rev"), "confirm"), needs_confirm=exc.text,
                    node_ids=[exc.target])
    except ValueError as exc:
        return _refused(name, [(name, exc)], ns.get("set_rev"))
    if new is ns and new_doc is base:  # 바뀐 것 없음: 아무것도 쓰지 않음
        return {"ok": True, "command": name, "changed": False, "set_rev": ns["set_rev"], "batch_id": None,
                "node_ids": [], "refused": []}
    write_results = new_doc is not base and (doc is not None or any(c.get("entries") for c in new_doc.get("cells") or []))
    try:
        if write_results:
            store_io.write_json(_pending_path(ns), {"kind": PENDING_KIND, "set_fp_after": _set_fp(new),
                                                   "results_fp_before": rfp, "results": res.disk_form(new_doc)})
        nodes.save_fp(new, expect=fp)
        if write_results:
            res.save_fp(new_doc, ns.get("project_id"), expect=rfp)
    except store_io.Conflict as exc:
        return _refused(name, [("file", "읽은 뒤 파일이 바뀌어 저장하지 않음(%s)" % exc)], ns.get("set_rev"), "conflict")
    except OSError as exc:
        return _refused(name, [("file", "저장 실패(%s)" % exc)], ns.get("set_rev"), "conflict")
    before = {n["node_id"] for n in ns["nodes"]}
    made = [n["node_id"] for n in new["nodes"] if n["node_id"] not in before]
    a = args or {}
    touched = made or [x for x in a.get("node_ids") or [a.get("node_id")] if x]
    return {"ok": True, "command": name, "changed": True, "set_rev": new["set_rev"], "batch_id": bid, "node_ids": touched,
            "refused": []}


# ---------------------------------------------------------------- 도면을 구간 분석에서 빼기(범례·기호표)

def _sheet(pg, graph_id):
    sheets = pg.get("sheets") or [{"graph_id": pg.get("graph_id"), "drawing_number": (pg.get("source") or {}).get("drawing_number")}]
    return next((s for s in sheets if s.get("graph_id") == graph_id), None)


def drawing_nodes(pg, ns, graph_id):
    """그 도면의 구성요소를 품은 구간 [{node_id, name, count}] (구간 집합 순서)."""
    on_sheet = {x["entity_id"] for x in pg.get("nodes") or [] if x.get("sheet") == graph_id}
    out = []
    for n in (ns or {}).get("nodes") or []:
        k = sum(1 for m in n.get("members") or [] if m in on_sheet)
        if k:
            out.append({"node_id": n["node_id"], "name": n.get("name"), "count": k})
    return out


def excluded_ver(project_id):
    """도면 빼기 표시 파일의 판(화면이 읽은 판과 대조한다). 파일이 없으면 'none'."""
    path = nodes.excluded_path(project_id)
    return store_io.fingerprint(path) if os.path.isfile(path) else "none"


HELD_SHOWN = 20   # 확인 글에 이름을 적는 구간 수(글이 확인 인자 한도를 넘지 않게)


def drawing_confirm_text(graph_id, number, held):
    return ("%s 도면의 구성요소가 구간 %s에 들어 있습니다. 도면을 빼면 새 구간 제안에서만 빠지고, 이 구간들은 그대로 분석됩니다. "
            "구간까지 빼려면 구간 카드에서 '분석에서 제외'를 누르세요."
            % (number or graph_id, ", ".join("%s(%d개)" % (h["node_id"], h["count"]) for h in held[:HELD_SHOWN])
               + (" 외 %d곳" % (len(held) - HELD_SHOWN) if len(held) > HELD_SHOWN else "")))


def exclude_drawing(pg, graph_id, excluded, *, by, reason=None, ver=None, confirm=None):
    """도면 한 장을 구간 분석(구간 제안·후보)에서 빼거나 다시 넣는다. 채팅도 이 길로 부른다(사람이 확인 상자를 누른 뒤).
    ver: 화면이 읽은 표시 파일의 판(excluded_ver). 다르면 stale로 거절한다(None이면 대조하지 않음, 시험용).
    그 도면의 구성요소를 품은 구간이 있으면, 뺄 때 drawing_confirm_text 글이 confirm으로 와야 저장한다.
    돌려주는 값: {"ok", "changed", "ver", "needs_confirm"?, "refused"}."""
    project_id = pg.get("project_id")
    by = (by or "").strip()
    if not by:
        return _refused("exclude_drawing", [("by", "누른 사람 이름 필요")], code="bad_actor")
    sheet = _sheet(pg, graph_id)
    if sheet is None:
        return _refused("exclude_drawing", [(graph_id, "프로젝트 그래프에 없는 도면")])
    number = (sheet.get("drawing_number") or "").strip()
    if not number:
        return _refused("exclude_drawing", [(graph_id, "도면 번호가 확정되지 않은 도면은 뺄 수 없음(표제란에서 도면 번호를 먼저 확정)")])
    try:
        marked = nodes.excluded_mark(project_id, number) is not None
    except (OSError, ValueError) as exc:
        return _refused("exclude_drawing", [("file", "도면 빼기 표시를 읽지 못함(%s)" % exc)], code="unreadable")
    now = excluded_ver(project_id)
    if ver is not None and ver != now:
        return _refused("exclude_drawing", [("ver", "도면 빼기 표시가 그 사이 바뀜")], code="stale")
    if marked == bool(excluded):
        return {"ok": True, "command": "exclude_drawing", "changed": False, "ver": now, "refused": []}
    if excluded:
        try:
            ns = nodes.read_as_is(pg)
        except (OSError, ValueError):
            ns = None
        held = drawing_nodes(pg, ns, graph_id)
        ask = drawing_confirm_text(graph_id, number, held) if held else None
        if ask and (confirm or "") != ask:
            return dict(_refused("exclude_drawing", [(graph_id, ask)], code="confirm"), needs_confirm=ask)
    try:
        nodes.set_excluded(project_id, number, bool(excluded), by, reason)
    except ValueError as exc:
        return _refused("exclude_drawing", [(graph_id, exc)])
    except OSError as exc:
        return _refused("exclude_drawing", [("file", "저장 실패(%s)" % exc)], code="conflict")
    return {"ok": True, "command": "exclude_drawing", "changed": True, "ver": excluded_ver(project_id), "refused": []}
