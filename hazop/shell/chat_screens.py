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


# ================================================================ ⑥ 초기사건 편집(A10, api_ie)
# 화면 ⑥의 쓰기 대조를 그대로 쓴다: 읽은 ⑥ 파일 지문(ver)·⑤ 결과 지문(rver)·건드리는 항목의 지문(seen). 확인 상자를 띄울 때 읽은 값을
# 실행 때 그대로 넘겨, 그 사이 바뀌었으면 엔진이 stale로 거절한다. 확정이 풀리는 그룹은 확인 상자에 미리 계산해 보이고, 실행 때 그 목록을
# confirm_groups로 넘긴다(엔진이 지금 목록과 다르면 stale). 상자에 없던 풀림이 생기면 엔진은 저장하지 않고 되묻고, 채팅은 거절로 알린다.
# 지문은 화면과 같이 FMEA·MLD까지 넣은 묶음에서 낸다.

IE_ACTIONS = ("ie.move", "ie.split", "ie.edit_group", "ie.accept_members", "ie.confirm_group", "ie.reopen_group", "ie.set_coverage")
IE_HANDLER = {"ie.move": "_move", "ie.split": "_split", "ie.edit_group": "_edit_group", "ie.accept_members": "_accept_members",
              "ie.confirm_group": "_confirm", "ie.reopen_group": "_reopen", "ie.set_coverage": "_set_coverage"}


def _ie_ctx(engine):
    """(맥락, 맞춘 ⑥ 문서, 항목 지문, 묶음) 또는 (None, 사유, None, None). 화면과 같은 계산: 승인 FMEA 행까지 맞춘 문서(_view_doc)와
    FMEA·MLD를 함께 넣은 묶음(_build)에서 지문을 낸다(빼면 MLD 가지·기본사건 지문이 화면과 달라진다)."""
    from hazop.shell import api_ie
    from hazop.study import nodes
    ctx, why = api_ie._context(engine)
    if ctx is None:
        return None, why, None, None
    pg, ns, doc, ie_doc, _fp = ctx
    base = api_ie._view_doc(ie_doc, doc, ns)
    b = api_ie._build(doc, ns, pg, base, nodes.now_utc())
    return ctx, base, api_ie.item_fps(b), b


def _ie_keys(item, base, b=None):
    from hazop.shell import api_ie
    a = item.args
    if item.action in ("ie.move", "ie.accept_members"):
        return api_ie._member_keys(base, a["iecs"], [a["to"]] if a.get("to") else [], b)
    if item.action == "ie.set_coverage":
        return ["coverage:" + a["code"]]
    return ["group:" + a["group_id"]]


def _ie_new(engine, item, ctx, base):
    """실행하면 저장될 ⑥ 문서(api_ie의 명령과 같은 model 함수, 저장하지 않음). 계산하지 못하면 None."""
    from hazop.ie import model
    from hazop.shell import api_ie
    pg, ns, doc, _ie, _fp = ctx
    a, act = item.args, item.action
    by = engine.reviewer() or ""
    try:
        if act in ("ie.move", "ie.accept_members"):
            d = base
            for i in api_ie._twins_of(base, doc, ns, pg, a["iecs"]):
                if act == "ie.move":
                    d = model.place(d, i, a.get("to") or None)
                elif base["candidates"].get(i, {}).get("group_id"):
                    d = model.accept(d, ("member", i))
            return d
        if act == "ie.split":
            out = model.split(base, a["group_id"], api_ie._twins_of(base, doc, ns, pg, a["moved"]))
            return out[0] if isinstance(out, tuple) else out
        if act == "ie.edit_group":
            return model.edit(base, ("group", a["group_id"]), a["fields"])
        if act == "ie.confirm_group":
            return model.confirm(base, a["group_id"], doc, by, node_set=ns)
        if act == "ie.reopen_group":
            return model.reopen(base, a["group_id"])
        if act == "ie.set_coverage":
            return model.set_coverage(base, a["code"], a.get("disposition") or None, a.get("reason") or "", by)
    except (ValueError, KeyError, TypeError) as exc:
        LOG.info("⑥ 변경 미리 계산 실패: %s", exc)
    return None


def _ie_lost(engine, item, ctx, base):
    """실행하면 확정이 풀릴 그룹(확정 풀기 자체는 빼고). 엔진이 되묻는 목록과 같은 계산(api_ie.lost_confirmations)."""
    from hazop.shell import api_ie
    if item.action == "ie.reopen_group":
        return []
    new = _ie_new(engine, item, ctx, base)
    return api_ie.lost_confirmations(base, new) if isinstance(new, dict) else []


def _ie_check(engine):
    def check(item, snap):
        from hazop.ie import model
        from hazop.shell import api_ie
        a = item.args
        ctx, base, fps, b = _ie_ctx(engine)
        if ctx is None:
            return base
        if "group_id" in a and a["group_id"] not in base["groups"]:
            return "없는 그룹: %s" % a["group_id"]
        if a.get("to") and a["to"] not in base["groups"]:
            return "없는 그룹: %s" % a["to"]
        missing = [i for i in (a.get("iecs") or []) + (a.get("moved") or []) if i not in base["candidates"]]
        if missing:
            return "없는 후보: %s" % ", ".join(missing[:5])
        if item.action == "ie.edit_group":
            try:
                api_ie.v_fields("group")(a["fields"])
            except ValueError as exc:
                return str(exc)
        if item.action == "ie.set_coverage":
            if (a.get("disposition") or "") not in ("",) + tuple(model.COVERAGE):
                return "처리는 %s 가운데 하나(빈 글자면 지움)" % ", ".join(model.COVERAGE)
            if a.get("disposition") and not (a.get("reason") or "").strip():
                return "판정에는 사유가 있어야 함"
        keys = _ie_keys(item, base, b)
        absent = [k for k in keys if k not in fps]
        if absent:
            return "지금 ⑥ 문서에 없는 항목: %s" % ", ".join(k.split(":", 1)[1] for k in absent[:5])
        item.targets = [k.split(":", 1)[1] for k in keys]
        item.basis = {"ver": api_ie._ver(ctx[4]), "rver": api_ie._rver(ctx), "seen": {k: fps[k] for k in keys},
                      "confirm_groups": _ie_lost(engine, item, ctx, base)}
        return None
    return check


def _group_label(base, gid):
    g = base["groups"].get(gid) or {}
    return "%s %s%s" % (gid, g.get("name") or "", " · 확정" if g.get("status") == "confirmed" else "")


def _ie_details(engine):
    def details(item, snap):
        from hazop.ie import model
        from hazop.chat.actions import show_value
        a = item.args
        ctx, base, fps, b = _ie_ctx(engine)
        if ctx is None:
            return [{"label": "오류", "after": base}]
        rows = []
        if item.action == "ie.move":
            for i in a["iecs"]:
                old = (base["candidates"].get(i) or {}).get("group_id")
                rows.append({"label": "후보 %s" % i, "before": _group_label(base, old) if old else "(묶이지 않음)",
                             "after": _group_label(base, a["to"]) if a.get("to") else "(그룹에서 뺌)"})
        elif item.action == "ie.split":
            rows.append({"label": "나눌 그룹", "after": _group_label(base, a["group_id"])})
            rows.append({"label": "새 그룹으로 옮길 후보", "after": ", ".join(a["moved"])})
        elif item.action == "ie.edit_group":
            g = base["groups"].get(a["group_id"]) or {}
            rows.append({"label": "그룹", "after": _group_label(base, a["group_id"])})
            rows += [{"label": "%s(AI가 씀)" % k, "before": show_value(g.get(k)), "after": show_value(v)} for k, v in sorted(a["fields"].items())]
        elif item.action == "ie.accept_members":
            rows += [{"label": "후보 %s" % i, "after": "소속 확인: %s" % _group_label(base, (base["candidates"].get(i) or {}).get("group_id"))}
                     for i in a["iecs"]]
        elif item.action in ("ie.confirm_group", "ie.reopen_group"):
            g = base["groups"].get(a["group_id"]) or {}
            rows.append({"label": "그룹", "before": g.get("status") or "draft",
                         "after": ("확정(확정자: 확인한 사람)" if item.action == "ie.confirm_group" else "초안으로 되돌림") + " · " + _group_label(base, a["group_id"])})
            if item.action == "ie.confirm_group":
                problems = model.confirm_problems(base, a["group_id"], ctx[2], node_set=ctx[1])
                rows.append({"label": "확정 조건", "after": "; ".join(problems[:5]) if problems else "모두 채움"})
        elif item.action == "ie.set_coverage":
            old = base["coverage"].get(a["code"]) or {}
            rows.append({"label": "범주 %s" % a["code"], "before": model.COVERAGE.get(old.get("disposition"), "(판정 없음)"),
                         "after": model.COVERAGE.get(a.get("disposition") or "", "(판정 지움)")})
            rows.append({"label": "사유(AI가 씀)", "after": show_value(a.get("reason"))})
        lost = _ie_lost(engine, item, ctx, base)
        if lost:
            rows.append({"label": "확정이 풀리는 그룹", "after": ", ".join(_group_label(base, g) for g in lost) + ". 바꾼 뒤 다시 확정해야 합니다."})
        rows.append({"label": "항목 지문", "after": " · ".join("%s %s" % (k.split(":", 1)[1], str(v)[-8:])
                                                           for k, v in sorted({k: fps.get(k) for k in _ie_keys(item, base, b)}.items()))})
        return rows
    return details


def _ie_execute(engine, action):
    def run(args, call):
        from hazop.shell import api, api_ie
        basis = call.basis or {}
        if not basis.get("seen"):
            return _refused("확인 상자에서 본 항목 지문이 없어 저장하지 않았습니다.", "stale")
        a = dict(args, ver=basis["ver"], rver=basis["rver"], seen=basis["seen"])
        if basis.get("confirm_groups"):          # 확인 상자에 보인 '확정이 풀리는 그룹' 그대로. 엔진이 지금 목록과 다르면 stale로 거절한다
            a.update(confirmed=True, confirm_groups=list(basis["confirm_groups"]))
        if action == "ie.move":
            a["to"] = args.get("to") or ""
        if action == "ie.split":
            a["moved"] = list(args["moved"])
        if action == "ie.set_coverage":
            a["disposition"] = args.get("disposition") or ""
        try:
            out = getattr(api_ie, IE_HANDLER[action])(engine, a)
        except api.CommandError as exc:
            if exc.code == "confirm":
                return _refused("%s 이 변경은 ⑥ 초기사건 패널에서 직접 하세요." % exc.message, "confirm")
            raise
        if out.get("ask"):                       # 확인 상자에 없던 '확정 풀림'이 생겼다: 저장하지 않았다
            return _refused("확인한 뒤 확정이 풀릴 그룹이 생겨 저장하지 않았습니다(%s). 다시 요청해 확인 상자를 보세요."
                            % ", ".join(out["ask"].get("groups") or []), "stale")
        if not out.get("changed"):
            return _ok("바뀐 것이 없습니다.")
        extra = ""
        if out.get("groups"):
            extra = " 새 그룹: %s." % ", ".join(str(g) for g in out["groups"] if g)
        return _ok("⑥ 초기사건을 고쳤습니다(%s).%s" % (TITLES_IE.get(action, action), extra), topics=["ie"])
    return run


TITLES_IE = {"ie.move": "후보 옮기기", "ie.split": "그룹 나누기", "ie.edit_group": "그룹 고치기", "ie.accept_members": "소속 확인",
             "ie.confirm_group": "그룹 확정", "ie.reopen_group": "그룹 확정 풀기", "ie.set_coverage": "범주 대조 판정"}


def _ie_draft(engine):
    def run(args, call):
        from hazop.shell import api_ie
        out = api_ie._suggest(engine, {})
        return _ok("초기사건 규칙 초안을 만들었습니다." if out.get("changed") else "규칙 초안에 더할 것이 없습니다.", topics=["ie"])
    return run


def _ie_export(engine):
    def run(args, call):
        from hazop import paths
        from hazop.shell import api_ie
        from hazop.shell.chat_actions import _AutoSave
        proxy = _AutoSave(engine, paths.output_root("exports"))
        out = api_ie._export(proxy, {})
        if out.get("cancelled"):
            return _refused("덮어쓸 파일이 있어 내보내지 않았습니다." if out.get("overwrite_refused") else "내보내지 못했습니다.")
        return _ok("초기사건 인계 묶음을 내보냈습니다: %s (작업 루트의 output/exports)." % (out.get("path") or out.get("xlsx") or ""))
    return run


# ================================================================ 설계 문서(A7, api_docs)

def _doc_row(engine, material_id):
    from hazop.shell import api_docs
    return next((r for r in api_docs.list_documents(engine) if r.get("material_id") == material_id), None)


def _docs_check(engine, running):
    def check(item, snap):
        row = _doc_row(engine, item.args["material_id"])
        if row is None:
            return "지금 프로젝트에 없는 설계 문서: %s" % item.args["material_id"]
        if item.args["material_id"] in running:
            return "이 문서의 지식 추출이 이미 돌고 있음"
        item.targets = [item.args["material_id"]]
        return None
    return check


def _docs_details(engine):
    def details(item, snap):
        row = _doc_row(engine, item.args["material_id"])
        if row is None:
            return [{"label": "오류", "after": "문서가 없어짐"}]
        counts = ", ".join("%s %s" % (k, v) for k, v in sorted((row.get("counts") or {}).items()) if v)
        return [{"label": "문서", "after": "%s (%s)" % (row.get("title") or row.get("name") or row["material_id"], row["material_id"])},
                {"label": "지금 뽑힌 항목", "after": counts or "(없음)"},
                {"label": "다시 추출", "after": "뽑힌 항목을 새로 쓰고 프로젝트 지식그래프를 다시 만듭니다. 사람 확인 전 상태로 돌아갑니다."}]
    return details


def _docs_execute(engine, running, record):
    def run(args, call):
        from hazop.shell import api_docs
        mid = args["material_id"]
        if mid in running:
            return _refused("이 문서의 지식 추출이 이미 돌고 있습니다.", "busy", mid)
        out = api_docs.run_extraction(engine, mid)
        job = out.get("job")
        running.add(mid)
        if record is not None and job:
            record.follow(job, call, [mid], lambda: running.discard(mid))
        else:
            running.discard(mid)
        return _ok("설계 문서 %s의 지식 추출을 시작했습니다(작업 %s)." % (mid, job))
    return run


def docs_display(engine):
    from hazop.shell import api_docs
    api_docs.open_panel(engine)
    return {"op": "panel", "ok": True, "panel": "docs", "text": "설계 문서 패널을 열었습니다."}


# ================================================================ 표

def checks(engine, docs_running=None):
    out = {"kg.judge": _kg_check(engine), "sources.choose": _sources_check(engine),
           "docs.extract": _docs_check(engine, docs_running if docs_running is not None else set())}
    out.update({name: _aireview_check(engine) for name in AIREVIEW_ACTIONS})
    out.update({name: _ie_check(engine) for name in IE_ACTIONS})
    return out


def details(engine):
    out = {"kg.judge": _kg_details(engine), "sources.choose": _sources_details(engine), "docs.extract": _docs_details(engine)}
    out.update({name: _aireview_details(engine) for name in AIREVIEW_ACTIONS})
    out.update({name: _ie_details(engine) for name in IE_ACTIONS})
    return out


def executors(engine, docs_running=None, watcher=None):
    out = {"kg.judge": _guard(_kg_execute(engine)), "sources.choose": _guard(_sources_execute(engine)),
           "ie.draft_rules": _guard(_ie_draft(engine)), "ie.export": _guard(_ie_export(engine)),
           "docs.extract": _guard(_docs_execute(engine, docs_running if docs_running is not None else set(), watcher))}
    out.update({name: _guard(_aireview_execute(engine, name)) for name in AIREVIEW_ACTIONS})
    out.update({name: _guard(_ie_execute(engine, name)) for name in IE_ACTIONS})
    return out


RUN_ACTIONS = ("kg.judge", "sources.choose", "ie.draft_rules", "ie.export", "docs.extract") + AIREVIEW_ACTIONS + IE_ACTIONS
