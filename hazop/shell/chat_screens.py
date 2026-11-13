"""채팅 동작 A11 2차: 새 화면 영역(지식그래프 A6·AI 검토 후보 A4·원본 선택)의 실행 함수를 채팅에 잇는다. Qt를 import하지 않는다.

1차 검토(8c74f5f 반려)에서 정한 것을 그대로 지킨다.
- 사람 판단을 저장하는 동작(잠재 후보 판단, AI 후보 수락·거절·되돌리기·묶음 수락, 원본 형식 고르기)은 확인 상자를 거친다.
- 확인 상자에 저장될 값 전부를 보인다(`details`). 이 줄은 승인 표지에 들어가 실행 직전에 지금 상태로 다시 만든 줄과 글자 그대로 같을 때만 실행한다.
- 화면이 하는 대조를 확인 상자에서 본 값 그대로 엔진에 넘긴다: 잠재 후보는 항목 digest·상태·판단 판(ver), AI 후보는 후보 ID와 판(ver).
  묶음 수락은 엔진이 다시 세지 않고 확인 상자에 보인 후보 ID만 수락한다.
- 판단자는 확인 상자를 누른 사람(검토자 이름)이다. 사유·근거 글은 AI가 쓴 것이라고 확인 상자에 적는다.

내보내는 것: `checks(engine)`·`details(engine)`·`executors(engine)`(동작 이름 -> 함수 표), `kg_display(engine, text)`(표시 동작).
엔진 함수(hazop/shell/api_kg.py·api_aireview.py·api_drawings.py·hazop.graph.sources)는 부르기만 한다.
"""

import logging

LOG = logging.getLogger("hazop.shell.chat_screens")
MAX_CANDS = 50                 # 한 번에 수락·거절할 AI 후보 수(확인 상자에 모두 보인다)
KG_JUDGEMENTS = ("confirm", "reject", "absent", "not_applicable", "undo")
SOURCE_FORMATS = ("drawio", "pdf_vector", "dexpi")
AIREVIEW_ACTIONS = ("aireview.accept", "aireview.reject", "aireview.revert", "aireview.accept_bulk")


def _api():
    from hazop.shell import api
    return api


def _ok(message, topics=()):
    return {"ok": True, "refused": [], "batch_id": None, "node_ids": [], "set_rev": None, "message": message, "topics": list(topics)}


def _refused(reason, code="rule", target=""):
    return {"ok": False, "refused": [{"target": target, "code": code, "reason": str(reason)[:300]}], "batch_id": None,
            "node_ids": [], "set_rev": None}


def _guard(fn):
    def run(args, call):
        api = _api()
        try:
            return fn(args, call)
        except api.CommandError as exc:
            return _refused(exc.message, exc.code)
    return run


# ================================================================ 지식그래프: 잠재 후보 판단

def _kg_item(engine, expectation_id):
    """(맥락, 잠재 후보 항목) 또는 (None, 거절 사유)."""
    from hazop.shell import api_kg
    ctx, why = api_kg._context(engine)
    if ctx is None:
        return None, why or "지식그래프를 읽을 수 없음"
    if ctx.get("judge_problem"):
        return None, ctx["judge_problem"]
    item = next((i for i in (ctx.get("expectations") or {}).get("items") or [] if i.get("id") == expectation_id), None)
    if item is None:
        return None, "없는 잠재 후보: %s" % expectation_id
    return ctx, item


def _kg_check(engine):
    def check(item, snap):
        from hazop.kg import expect
        a = item.args
        if a["judgement"] not in KG_JUDGEMENTS:
            return "판단은 %s 가운데 하나" % ", ".join(KG_JUDGEMENTS)
        ctx, found = _kg_item(engine, a["id"])
        if ctx is None:
            return found
        try:
            row = expect.transition(found["state"], action=a["judgement"])
        except expect.ExpectError as exc:
            return str(exc)
        given = {"reason": (a.get("reason") or "").strip(), "evidence": (a.get("evidence") or "").strip()}
        missing = [expect.NEED_LABELS[k] for k in row[4] if not given[k]]
        if missing:
            return "%s에는 %s이 필요함" % (expect.ACTION_LABELS[a["judgement"]], "·".join(missing))
        item.targets = [a["id"]]
        item.basis = {"digest": found["digest"], "state": found["state"], "ver": ctx["ver"]}
        return None
    return check


def _kg_details(engine):
    def details(item, snap):
        from hazop.kg import expect
        from hazop.chat.actions import show_value
        a = item.args
        ctx, found = _kg_item(engine, a["id"])
        if ctx is None:
            return [{"label": "오류", "after": found}]
        to = expect.transition(found["state"], action=a["judgement"])[1]
        return [{"label": "잠재 후보", "after": "%s · 대상 %s" % (found.get("label") or found.get("rule_id"), found.get("target_tag") or found.get("target"))},
                {"label": "판단", "before": expect.STATES.get(found["state"], found["state"]),
                 "after": "%s(%s)" % (expect.STATES.get(to, to), expect.ACTION_LABELS[a["judgement"]])},
                {"label": "사유(AI가 씀)", "after": show_value(a.get("reason"))},
                {"label": "근거(AI가 씀)", "after": show_value(a.get("evidence"))},
                {"label": "항목 지문", "after": "%s · 판 %s" % (str(found["digest"])[:12], str(ctx["ver"]).split("|")[-1][:12])}]
    return details


def _kg_execute(engine):
    def run(args, call):
        from hazop.shell import api_kg
        from hazop.kg import expect
        basis = call.basis or {}
        if not basis.get("digest"):
            return _refused("확인 상자에서 본 항목 지문이 없어 저장하지 않았습니다.", "stale", args.get("id", ""))
        out = api_kg.judge(engine, args["id"], args["judgement"], basis["digest"], basis["state"], args.get("reason") or "",
                           args.get("evidence") or "", ver=basis["ver"], by=call.confirmed_by)
        return _ok("잠재 후보 %s을(를) '%s'(으)로 판단했습니다(지금 상태: %s)."
                   % (args["id"], expect.ACTION_LABELS[args["judgement"]], out.get("state_label") or out.get("state")), topics=["kg"])
    return run


def kg_display(engine, text, item_id=None):
    """지식그래프 패널을 열고 찾은 노드를 고른다(데이터를 바꾸지 않음) -> 표시 항목."""
    from hazop.shell import api_kg
    hits = [{"id": item_id, "label": item_id}] if item_id else api_kg.find_nodes(engine, text or "", 5)
    if not hits:
        api_kg.open_panel(engine)
        return {"op": "panel", "ok": True, "panel": "kg", "text": "지식그래프에서 찾지 못했습니다: %s. 패널만 열었습니다." % (text or "")[:60]}
    api_kg.open_panel(engine, hits[0]["id"])
    more = " (비슷한 노드 %d개 더 있음)" % (len(hits) - 1) if len(hits) > 1 else ""
    return {"op": "panel", "ok": True, "panel": "kg", "text": "지식그래프에서 %s을(를) 골랐습니다.%s" % (hits[0].get("label") or hits[0]["id"], more)}


# ================================================================ AI 검토 후보

def _aireview_state(engine, graph_id):
    """(이름, 판, {후보 ID: 화면 줄}, 후보 문서) 또는 거절 사유(글)."""
    from hazop.shell import api_aireview
    view = api_aireview.candidates(engine, graph_id)
    if not view.get("ok"):
        return view.get("message") or "AI 후보를 읽을 수 없음"
    if not view.get("available"):
        return view.get("reason") or "이 도면에는 AI 후보가 없음"
    rows = {r["cand_id"]: r for g in view["groups"] for r in g["items"]}
    return view["ver"], rows


def _bulk_ids(engine, graph_id, task):
    """묶음 수락이 고를 후보 ID(api_aireview.bulk_ids, accept_bulk와 같은 규칙. 읽기만 함)."""
    from hazop.shell import api_aireview
    return list(api_aireview.bulk_ids(engine, graph_id, task) or [])


def _aireview_ids(engine, item):
    if item.action == "aireview.accept_bulk":
        return _bulk_ids(engine, item.args["graph_id"], item.args["task"])
    return list(dict.fromkeys(item.args["cand_ids"]))


NEED_STATUS = {"aireview.accept": ("proposed",), "aireview.reject": ("proposed",), "aireview.accept_bulk": ("proposed",),
               "aireview.revert": ("accepted", "rejected")}


def _aireview_check(engine):
    def check(item, snap):
        from hazop.extract import ai_review
        gid = item.args["graph_id"]
        if gid not in (engine.graph_names() or {}):
            return "지금 프로젝트에 없는 도면"
        if item.action == "aireview.accept_bulk" and item.args["task"] not in ai_review.TASK_ORDER:
            return "묶음은 %s 가운데 하나" % ", ".join(ai_review.TASK_ORDER)
        state = _aireview_state(engine, gid)
        if isinstance(state, str):
            return state
        ver, rows = state
        ids = _aireview_ids(engine, item)
        if not ids:
            return "묶어 수락할 후보가 없음" if item.action == "aireview.accept_bulk" else "후보 ID가 없음"
        if len(ids) > MAX_CANDS:
            return "한 번에 %d개까지(확인 상자에 모두 보입니다)" % MAX_CANDS
        missing = [i for i in ids if i not in rows]
        if missing:
            return "없는 후보: %s" % ", ".join(missing[:5])
        bad = [i for i in ids if rows[i]["status"] not in NEED_STATUS[item.action]]
        if bad:
            return "이 동작을 할 수 없는 상태의 후보: %s" % ", ".join("%s(%s)" % (i, rows[i]["status_label"]) for i in bad[:5])
        item.targets = [gid] + ids
        item.basis = {"ver": ver, "ids": ids}
        return None
    return check


def _aireview_details(engine):
    def details(item, snap):
        state = _aireview_state(engine, item.args["graph_id"])
        if isinstance(state, str):
            return [{"label": "오류", "after": state}]
        ver, rows = state
        out = []
        for cid in _aireview_ids(engine, item):
            r = rows.get(cid)
            if r is None:
                out.append({"label": "후보 %s" % cid, "after": "(없음)"})
                continue
            value = r["values"][0] if r["values"] else ""
            after = {"aireview.reject": "거절(값은 바꾸지 않음)", "aireview.revert": "되돌림(%s 이전으로)" % r["status_label"]}.get(item.action, value)
            out.append({"label": "%s %s · %s" % (r["field_label"], cid, r.get("local_id") or ""), "before": r["current"] or "(비어 있음)",
                        "after": "%s · 확신도 %.2f · AI 근거: %s" % (after, r["confidence"], r["reason"] or "없음")})
        out.append({"label": "후보 판", "after": str(ver)})
        return out
    return details


def _aireview_execute(engine, action):
    def run(args, call):
        from hazop.shell import api_aireview
        basis = call.basis or {}
        ids = list(basis.get("ids") or [])
        if not ids or not basis.get("ver"):
            return _refused("확인 상자에서 본 후보·판이 없어 저장하지 않았습니다.", "stale", args.get("graph_id", ""))
        fn = {"aireview.accept": api_aireview.accept, "aireview.accept_bulk": api_aireview.accept,
              "aireview.reject": api_aireview.reject, "aireview.revert": api_aireview.revert}[action]
        out = fn(engine, args["graph_id"], ids, ver=basis["ver"], by=call.confirmed_by)
        if not out.get("ok"):
            return _refused(out.get("message") or "저장하지 못했습니다.", out.get("code") or "failed", args["graph_id"])
        verb = {"aireview.reject": "거절", "aireview.revert": "되돌림"}.get(action, "수락")
        text = "AI 후보 %d건을 %s했습니다." % (len(out.get("changed") or []), verb)
        if out.get("failed"):
            text += " 하지 못한 것 %d건: %s." % (len(out["failed"]), "; ".join("%s %s" % (f["cand_id"], f["reason"]) for f in out["failed"][:3]))
        if out.get("notes"):
            text += " " + " ".join(out["notes"][:2])
        if out.get("graph_stale") and not out.get("notes"):     # 저장은 됐다(ok). 그래프만 고치기 전 상태
            text += " 저장했지만 그래프를 다시 만들지 못해 도면·그래프는 아직 고치기 전 상태입니다."
        if out.get("recheck"):
            text += " " + " ".join(str(r) for r in out["recheck"][:3])
        return _ok(text, topics=[])
    return run


# ================================================================ 같은 번호 원본 고르기

def _conflict(engine, drawing_number):
    from hazop.graph import sources
    return next((c for c in sources.conflicts(engine.project_id()) if c["drawing_number"] == drawing_number), None)


def _sources_check(engine):
    def check(item, snap):
        a = item.args
        if a["format"] not in SOURCE_FORMATS:
            return "형식은 %s 가운데 하나" % ", ".join(SOURCE_FORMATS)
        found = _conflict(engine, a["drawing_number"])
        if found is None:
            return "도면 번호 %s에는 형식이 다른 원본이 겹치지 않음(고를 것이 없음)" % a["drawing_number"]
        if a["format"] not in found["formats"]:
            return "도면 번호 %s에 %s 원본이 없음(있는 형식: %s)" % (a["drawing_number"], a["format"], ", ".join(found["formats"]))
        item.targets = [a["drawing_number"]]
        return None
    return check


def _sources_details(engine):
    def details(item, snap):
        a = item.args
        found = _conflict(engine, a["drawing_number"])
        if found is None:
            return [{"label": "오류", "after": "겹치는 원본이 없어짐"}]
        return [{"label": "도면 번호", "after": a["drawing_number"]},
                {"label": "쓸 원본 형식", "before": "%s%s" % (found.get("in_use_format") or "(없음)", " · 사람이 고름" if found.get("chosen") else ""),
                 "after": a["format"]},
                {"label": "있는 형식", "after": ", ".join(found["formats"])}]
    return details


def _sources_execute(engine):
    def run(args, call):
        from hazop.shell import api_drawings
        out = api_drawings._choose_source(engine, {"drawing_number": args["drawing_number"], "format": args["format"]})
        return _ok("도면 %s에 %s 원본을 쓰도록 골랐습니다." % (args["drawing_number"], (out.get("chosen") or {}).get("format") or args["format"]))
    return run


# ================================================================ 표

def checks(engine):
    out = {"kg.judge": _kg_check(engine), "sources.choose": _sources_check(engine)}
    out.update({name: _aireview_check(engine) for name in AIREVIEW_ACTIONS})
    return out


def details(engine):
    out = {"kg.judge": _kg_details(engine), "sources.choose": _sources_details(engine)}
    out.update({name: _aireview_details(engine) for name in AIREVIEW_ACTIONS})
    return out


def executors(engine):
    out = {"kg.judge": _guard(_kg_execute(engine)), "sources.choose": _guard(_sources_execute(engine))}
    out.update({name: _guard(_aireview_execute(engine, name)) for name in AIREVIEW_ACTIONS})
    return out


RUN_ACTIONS = ("kg.judge", "sources.choose") + AIREVIEW_ACTIONS
