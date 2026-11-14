"""채팅 동작 A11 2차 마무리: 표제란(A3)·도면 고치기(A5)·초기사건 P5(FMEA·MLD)·설계 문서 판 대응을 채팅에 잇는다. Qt를 import하지 않는다.

1차에서 정한 방식을 그대로 따른다(hazop/shell/chat_screens.py 머리말).
- 저장하는 동작은 모두 확인 상자를 거친다. 상자에는 저장될 값 전부(앞값 → 새값, AI가 쓴 사유)를 보이고, 승인 때 지금 상태로 다시 만든
  줄과 글자 그대로 같을 때만 실행한다.
- 화면이 하는 대조를 상자에서 본 값 그대로 엔진에 넘긴다: 표제란은 등록정보 판(ver), 도면 고치기는 세 파일 판(ver)·항목 지문(base)·
  엔진이 물을 확인 글(confirm), FMEA·MLD는 파일 지문(fver·mver)과 행·가지 지문(seen).
- 표제란 확정은 다시 추출을 작업으로 돌린다. 같은 자료가 돌고 있으면 겹쳐 시작하지 않고, 작업 끝(끝남·실패)을 기록에 남긴다.
- 파일을 고르는 일(FMEA 양식 가져오기·MLD 가져오기·FMEA 양식 내보내기)은 채팅으로 하지 않는다(웹은 경로를 보내지 않는다).

내보내는 것: `checks(engine, running)`·`details(engine)`·`executors(engine, running, watcher)`, `RUN_ACTIONS`.
엔진 함수(api_titleblock·hazop.register.titleblock·api_corrections·api_ie·api_docs)는 부르기만 한다.
"""

import logging

from hazop.shell.chat_screens import _guard, _ok, _refused

LOG = logging.getLogger("hazop.shell.chat_edits")
TITLEBLOCK_ACTIONS = ("titleblock.confirm", "titleblock.unconfirm")
DRAWING_ACTIONS = ("drawing.edit", "drawing.undo", "drawing.redo")
P5_ACTIONS = ("ie.fmea_status", "ie.fmea_mark", "ie.mld_link")
LINK_ACTIONS = ("links.pair", "links.unlink", "links.clear")
RUN_ACTIONS = TITLEBLOCK_ACTIONS + DRAWING_ACTIONS + P5_ACTIONS + ("docs.revision",) + LINK_ACTIONS
# 고침마다 엔진에 넘기는 value 열쇠. 그 밖의 열쇠는 걸러 내고 확인 상자에 '넘기지 않은 값'으로 보인다(상자에 없는 값이 저장되지 않게)
VALUE_KEYS = {"set_tag": ("tag",), "set_kind": ("kind",), "set_normal_position": ("value",), "set_fail_position": ("value",),
              "set_flow": ("from", "to", "flip"), "set_endpoint": ("end", "node"), "clear_endpoint": ("end",), "set_path": ("points",),
              "confirm": ("items",), "add_node": ("kind", "tag", "at"), "add_relation": ("kind", "from", "to", "line_no"),
              "delete_node": (), "delete_relation": ()}
CONFIRM_ITEM_KEYS = ("check", "reason")
TAG_ASK = "태그 '%s'가 이미 있습니다: %s. 태그는 프로젝트 전체에서 유일해야 합니다. 그래도 고칠까요?"   # api_corrections.apply_edit과 같은 글


def _show(v):
    from hazop.chat.actions import show_value
    return show_value(v)


def _who(engine):
    return engine.reviewer() or "(검토자 이름 없음)"


# ================================================================ 표제란(A3, api_titleblock · hazop.register.titleblock)

def _tb_row(engine, a):
    """material_id 또는 graph_id(그 자료에서 추출한 쪽) -> 표제란 행, 없으면 None."""
    from hazop.register import titleblock as tb
    pid = engine.project_id()
    if a.get("material_id"):
        return tb.row(pid, a["material_id"])
    gid = a.get("graph_id")
    return next((r for r in tb.view(pid) if any(s.get("graph_id") == gid for s in r.get("sheets") or [])), None) if gid else None


def _tb_fields(item):
    a = item.args
    if item.action == "titleblock.confirm":
        return {k: v for k, v in (a.get("fields") or {}).items() if v is not None}
    return a.get("fields")


def _tb_dry(engine, item, row):
    from hazop.register import titleblock as tb
    pid, mid, by = engine.project_id(), row["material_id"], engine.reviewer()
    if item.action == "titleblock.confirm":
        return tb.confirm(pid, mid, _tb_fields(item), by, row["ver"], item.args.get("reason"), dry=True)
    return tb.unconfirm(pid, mid, _tb_fields(item), by, row["ver"], item.args.get("reason"), dry=True)


def _tb_check(engine, running):
    def check(item, snap):
        a = item.args
        if not a.get("material_id") and not a.get("graph_id"):
            return "material_id 또는 graph_id가 있어야 함"
        if item.action == "titleblock.unconfirm" and a.get("fields") is not None and not isinstance(a["fields"], list):
            return "취소할 항목은 목록(drawing_number·design_revision·title)이어야 함"
        row = _tb_row(engine, a)
        if row is None:
            return "지금 프로젝트에 없는 도면 자료"
        if row["material_id"] in running:
            return "이 자료의 표제란 확정(다시 추출)이 이미 돌고 있음"
        out = _tb_dry(engine, item, row)
        if not out.get("ok"):
            return str((out.get("refused") or [{}])[0].get("reason") or "확정할 수 없음")
        if not out.get("changed"):
            return "바뀌는 값이 없음(이미 그 값으로 확정됨)"
        item.targets = [row["material_id"]]
        item.basis = {"material_id": row["material_id"], "ver": row["ver"], "re_extract": bool(out.get("re_extract"))}
        return None
    return check


def _tb_details(engine):
    def details(item, snap):
        row = _tb_row(engine, item.args)
        if row is None:
            return [{"label": "오류", "after": "자료가 없어짐"}]
        rows = [{"label": "도면 자료", "after": "%s (%s, 등록 v%s)" % (row.get("name") or "", row["material_id"], row.get("version"))}]
        fields = _tb_fields(item)
        for f in row["fields"]:
            if item.action == "titleblock.confirm":
                if f["field"] not in fields:
                    continue
                new = " ".join(str(fields[f["field"]]).split())
                note = " (후보 그대로)" if new == f.get("candidate") else (" (후보 %s와 다름)" % f["candidate"] if f.get("candidate") else "")
                rows.append({"label": f["label"], "before": _show(f["value"]) if f["value"] is not None else "(미확정)", "after": new + note})
            elif fields is None or f["field"] in fields:
                rows.append({"label": f["label"], "before": _show(f["value"]) if f["value"] is not None else "(미확정)",
                             "after": "확정 취소(후보 %s만 남음)" % (f.get("candidate") or "없음")})
        rows.append({"label": "확정한 사람", "after": "%s(확인한 사람)" % _who(engine)})
        if (item.args.get("reason") or "").strip():
            rows.append({"label": "사유(AI가 씀)", "after": _show(item.args["reason"])})
        sheets = row.get("sheets") or []
        if sheets:
            rows.append({"label": "다시 추출", "after": "추출한 쪽 %d개를 새 등록 버전으로 다시 추출합니다(사람 수정은 옮겨 씀, 쪽 확정은 풀림)."
                         % len(sheets)})
        if row.get("review_data"):
            rows.append({"label": "이 도면을 가리키는 검토 자료", "after": "; ".join(row["review_data"])})
        rows.append({"label": "등록정보 판", "after": str(row["ver"])[-12:]})
        return rows
    return details


def _tb_execute(engine, running, watcher):
    def run(args, call):
        from hazop.shell import api_titleblock
        basis = call.basis or {}
        mid = basis.get("material_id")
        if not mid or not basis.get("ver"):
            return _refused("확인 상자에서 본 등록정보 판이 없어 저장하지 않았습니다.", "stale")
        if mid in running:
            return _refused("이 자료의 표제란 확정이 이미 돌고 있습니다.", "busy", mid)
        a = {"material_id": mid, "ver": basis["ver"], "reason": args.get("reason"), "fields": args.get("fields")}
        handler = api_titleblock._h_confirm if call.action == "titleblock.confirm" else api_titleblock._h_unconfirm
        if call.action == "titleblock.unconfirm" and args.get("fields") is None:
            a.pop("fields")
        out = handler(engine, a)
        what = "확정" if call.action == "titleblock.confirm" else "확정 취소"
        if not out.get("changed"):
            return _ok("표제란에서 바뀐 것이 없습니다.")
        job = out.get("job")
        if not job:
            return _ok("표제란 %s을(를) 저장했습니다(%s, 다시 추출할 쪽 없음)." % (what, mid), topics=["titleblock"])
        running.add(mid)
        if watcher is not None:
            watcher.follow(job, call, [mid], lambda: running.discard(mid))
        else:
            running.discard(mid)
        return _ok("표제란 %s을(를) 저장하고 다시 추출을 시작했습니다(%s, 작업 %s)." % (what, mid, job), topics=["titleblock"])
    return run


# ================================================================ 도면 고치기(A5, api_corrections)

def _resolve(engine, a):
    """(graph_id, local_id, value) 또는 사유 글. id(프로젝트 구성요소 ID, 또는 하나로 정해지는 태그)를 주면 도면과 local_id로 바꾸고,
    value의 from·to·node도 같은 도면의 구성요소면 local_id로 바꾼다."""
    from hazop.extract import corrections
    gid, lid, value = a.get("graph_id"), a.get("local_id"), _kept(a.get("op"), a.get("value"))[0]
    find = None
    if a.get("id") or any(isinstance(value.get(k), str) for k in corrections.REF_KEYS):
        find = _finder(engine)
    if a.get("id"):
        hit = find(a["id"])
        if isinstance(hit, str):
            return hit
        if gid and gid != hit[0]:
            return "구성요소 %s는 도면 %s에 있음(graph_id와 다름)" % (a["id"], hit[0])
        gid, lid = hit
    if not gid:
        return "graph_id(또는 구성요소 id)가 있어야 함"
    for k in corrections.REF_KEYS:
        v = value.get(k)
        if isinstance(v, str) and find is not None:
            hit = find(v)
            if not isinstance(hit, str) and hit[0] == gid:
                value[k] = hit[1]
    return gid, lid, value


def _kept(op, value):
    """(넘길 value, 걸러 낸 열쇠 목록). 미확인 확정의 항목도 check·reason만 남긴다."""
    value = dict(value or {})
    keys = VALUE_KEYS.get(op, ())
    kept = {k: v for k, v in value.items() if k in keys}
    dropped = sorted(k for k in value if k not in keys)
    if op == "confirm" and isinstance(kept.get("items"), list):
        items = []
        for x in kept["items"]:
            if isinstance(x, dict):
                dropped += sorted("items." + k for k in x if k not in CONFIRM_ITEM_KEYS)
                items.append({k: x[k] for k in CONFIRM_ITEM_KEYS if k in x})
            else:
                items.append(x)
        kept["items"] = items
    return kept, dropped


def _finder(engine):
    """구성요소 ID 또는 태그 -> (graph_id, local_id), 못 찾거나 하나로 안 정해지면 사유 글."""
    from hazop.app import project_ctx
    from hazop.chat import view as chatview
    try:
        pg = project_ctx.project_graph(engine.project_id())
        fwd, _back = chatview._locals(pg)
    except (OSError, ValueError, KeyError):
        pg, fwd = {}, {}

    def find(ref):
        if ref in fwd:
            return fwd[ref]
        key = ref.strip().casefold()
        hits = [fwd[n["entity_id"]] for n in pg.get("nodes") or [] if n.get("entity_id") in fwd and (n.get("tag") or "").strip().casefold() == key]
        if len(hits) == 1:
            return hits[0]
        return ("태그 %s가 도면 %d곳에 있음(구성요소 ID로 가리킬 것)" % (ref, len(hits))) if hits else "도면에 그릴 수 없는 구성요소: %s" % ref
    return find


def _ask_text(engine, gid, op, lid, value):
    """엔진(apply_edit)이 물을 확인 글, 묻지 않으면 None. 같은 내부 함수로 저장 없이 계산한다."""
    from hazop.shell import api_corrections as ac
    name = ac._name(engine, gid)
    corrected = ac._sources(name)["corrected"]
    if op in ac.DELETES:
        removed = ac._removed_by(corrected, op, lid)
        return ac._confirm_text("지우기", removed, ac._impact(engine, gid, name, removed))
    if op in ("set_tag", "add_node"):
        idx = ac._index(corrected)
        if op == "add_node" or (idx.get(lid) or ("",))[0] == "node":
            tag = (value.get("tag") or "").strip() if op == "add_node" else value.get("tag")
            hits = ac._tag_conflicts(engine, name, corrected, tag, lid)
            if hits:
                return TAG_ASK % (tag, ", ".join("%s(%s)" % (h.get("name"), h.get("local_id")) for h in hits[:5]))
    return None


def _undo_ask(engine, gid, view, op_id):
    from hazop.extract import corrections
    from hazop.shell import api_corrections as ac
    name = ac._name(engine, gid)
    src = ac._sources(name)
    op = next((o for o in src["ops"] if o["op_id"] == op_id), None)
    if op is None or op["op"] not in ("add_node", "add_relation"):
        return None
    kind = "node" if op["op"] == "add_node" else "relation"
    removed = ac._removed_by(src["corrected"], "delete_" + kind, corrections.MANUAL_PREFIX + op_id)
    impact = ac._impact(engine, gid, name, removed)
    if impact["nodes"] or impact.get("sheet") in ("compared", "confirmed"):
        return ac._confirm_text("되돌리기", removed, impact)
    return None


def _undo_target(view, a):
    """되돌릴 연산 ID: op_id를 주면 그것(되돌릴 수 있는 것이어야 함), 없으면 되돌릴 수 있는 마지막 고침."""
    able = view.get("undoable") or []
    if a.get("op_id"):
        return a["op_id"] if a["op_id"] in able else None
    return able[-1] if able else None


def _drawing_check(engine):
    def check(item, snap):
        from hazop.extract import corrections
        from hazop.shell import api_corrections as ac
        a = item.args
        got = _resolve(engine, a)
        if isinstance(got, str):
            return got
        gid, lid, value = got
        view = ac.view(engine, gid)
        if not view.get("ok"):
            return view.get("message") or "도면 수정 기록을 읽지 못함"
        if not engine.reviewer():
            return "검토자 이름을 먼저 설정에서 입력해야 함(고친 사람으로 남음)"
        basis = {"graph_id": gid, "ver": view["ver"]}
        if item.action == "drawing.edit":
            op = a.get("op")
            if op not in corrections.OPS:
                return "모르는 고침: %s(%s 가운데 하나)" % (op, ", ".join(corrections.OPS))
            if corrections.OPS[op].targets and not lid:
                return "고칠 항목(구성요소 id 또는 local_id)이 있어야 함"
            base = None
            if lid:
                row = ac.item(engine, gid, lid)
                if not row.get("ok"):
                    return row.get("message") or "도면에 없는 항목"
                base = row["base"]
            basis.update(local_id=lid, value=value, op=op, base=base, confirm=_ask_text(engine, gid, op, lid, value))
            item.targets = [gid] + ([lid] if lid else [])
        elif item.action == "drawing.undo":
            op_id = _undo_target(view, a)
            if op_id is None:
                return ("되돌릴 수 없는 고침: %s(AI 검토에서 수락한 고침은 AI 검토 패널에서, 뒤 고침이 쓰는 것은 뒤 고침부터)" % a["op_id"]
                        if a.get("op_id") else "되돌릴 고침이 없음")
            basis.update(op_id=op_id, confirm=_undo_ask(engine, gid, view, op_id))
            item.targets = [gid, op_id]
        else:
            if not view.get("redo"):
                return "다시 할 고침이 없음(되돌린 뒤 새로 고쳤으면 다시 하기는 없음)"
            basis.update(op_id=view["redo"]["op_id"])
            item.targets = [gid, view["redo"]["op_id"]]
        item.basis = basis
        return None
    return check


def _value_rows(engine, row, op, value):
    """도면 고침의 앞값 → 새값 줄."""
    from hazop.shell.sheet_items import kind_label
    r = row or {}
    if op == "set_tag":
        return [{"label": "태그" if r.get("type") == "node" else "배관 번호", "before": _show(r.get("tag")), "after": _show(value.get("tag"))}]
    if op == "set_kind":
        k = value.get("kind")
        return [{"label": "종류", "before": "%s (%s)" % (r.get("kind_label") or "", r.get("kind")),
                 "after": "%s (%s)" % (kind_label(k) or "", k)}]
    if op in ("set_normal_position", "set_fail_position"):
        p = next((x for x in r.get("positions") or [] if x["op"] == op), {})
        return [{"label": p.get("label") or op, "before": _show(p.get("value")), "after": _show(value.get("value"))}]
    if op == "set_flow":
        now = r.get("flow")
        before = "%s → %s" % (now["from"], now["to"]) if now else "(방향 없음)"
        after = "지금 방향을 뒤집음" if value.get("flip") else "%s → %s" % (value.get("from"), value.get("to"))
        return [{"label": "흐름 방향", "before": before, "after": after}]
    if op in ("set_endpoint", "clear_endpoint"):
        end = value.get("end")
        cur = ((r.get("ends") or {}).get(end) or {}).get("node")
        return [{"label": "끝 %s" % end, "before": _show(cur), "after": _show(value.get("node")) if op == "set_endpoint" else "(끊음)"}]
    if op == "set_path":
        return [{"label": "경로 점", "after": "%d개: %s" % (len(value.get("points") or []), _show(value.get("points")))}]
    if op == "confirm":
        return [{"label": "미확인 %s(사유는 AI가 씀)" % x.get("check"), "after": _show(x.get("reason"))} for x in value.get("items") or []] or \
            [{"label": "미확인 확정", "after": "(항목 없음)"}]
    if op == "add_node":
        return [{"label": "새 기기", "after": "%s (%s) · 태그 %s · 자리 %s" % (kind_label(value.get("kind")) or "", value.get("kind"),
                                                                       _show(value.get("tag")), _show(value.get("at")))}]
    if op == "add_relation":
        return [{"label": "새 연결", "after": "%s · %s → %s · 배관 번호 %s" % (value.get("kind") or "physical_connection", value.get("from"),
                                                                       value.get("to"), _show(value.get("line_no")))}]
    if op in ("delete_node", "delete_relation"):
        return [{"label": "지울 것", "before": "%s %s" % (r.get("local_id"), _show(r.get("tag"))), "after": "(지움)"}]
    return [{"label": "값", "after": _show(value)}]


def _drawing_details(engine):
    def details(item, snap):
        from hazop.shell import api_corrections as ac
        a = item.args
        got = _resolve(engine, a)
        if isinstance(got, str):
            return [{"label": "오류", "after": got}]
        gid, lid, value = got
        view = ac.view(engine, gid)
        if not view.get("ok"):
            return [{"label": "오류", "after": view.get("message")}]
        rows = [{"label": "도면", "after": "%s (%s)" % (engine.graph_names().get(gid, gid), gid)}]
        if item.action == "drawing.edit":
            row = ac.item(engine, gid, lid) if lid else None
            if row is not None and not row.get("ok"):
                return [{"label": "오류", "after": row.get("message")}]
            rows.append({"label": "고침", "after": ac.OP_LABELS.get(a["op"], a["op"])})
            if row:
                rows.append({"label": "대상", "after": "%s · %s · %s" % (lid, row.get("kind_label") or row.get("kind") or "", _show(row.get("tag")))})
                impact = row.get("impact") or {}
                if impact.get("nodes"):
                    rows.append({"label": "이 항목이 든 구간", "after": ", ".join("%s(%s)" % (n["node_id"], n["state"]) for n in impact["nodes"])})
                if impact.get("sheet") in ("compared", "confirmed"):
                    rows.append({"label": "쪽 확정", "after": "이 쪽의 %s이 풀릴 수 있습니다." % ("확정" if impact["sheet"] == "confirmed" else "견줌")})
            rows += _value_rows(engine, row, a["op"], value)
            dropped = _kept(a["op"], a.get("value"))[1]
            if dropped:
                rows.append({"label": "넘기지 않은 값", "after": "이 고침에 쓰지 않는 값이라 저장하지 않음: %s" % ", ".join(dropped)})
            ask = _ask_text(engine, gid, a["op"], lid, value)
        else:
            op_id = _undo_target(view, a) if item.action == "drawing.undo" else (view.get("redo") or {}).get("op_id")
            op = next((o for o in view["ops"] if o["op_id"] == op_id), None) if item.action == "drawing.undo" else view.get("redo")
            rows.append({"label": "되돌릴 고침" if item.action == "drawing.undo" else "다시 할 고침",
                         "after": "%s %s%s" % (op_id, (op or {}).get("label") or "",
                                               " · 대상 %s · %s %s" % (op.get("local_id"), op.get("by") or "", op.get("at") or "")
                                               if item.action == "drawing.undo" and op else "")})
            ask = _undo_ask(engine, gid, view, op_id) if item.action == "drawing.undo" and op_id else None
        if ask:
            rows.append({"label": "엔진 확인", "after": ask})
        rows.append({"label": "고친 사람", "after": "%s(확인한 사람)" % _who(engine)})
        rows.append({"label": "저장 뒤", "after": "그 도면 그래프와 지식그래프를 다시 만듭니다(되돌리기로 뺄 수 있음)."})
        rows.append({"label": "도면 판", "after": str(view["ver"])[-12:]})
        return rows
    return details


def _drawing_execute(engine):
    def run(args, call):
        from hazop.shell import api_corrections as ac
        b = call.basis or {}
        if not b.get("ver") or not b.get("graph_id"):
            return _refused("확인 상자에서 본 도면 판이 없어 저장하지 않았습니다.", "stale")
        gid = b["graph_id"]
        if call.action == "drawing.edit":
            out = ac.apply_edit(engine, gid, b["op"], b.get("local_id"), b.get("value") or {}, b["ver"], confirm=b.get("confirm"),
                                base=b.get("base"), defer=True)
        elif call.action == "drawing.undo":
            out = ac.undo(engine, gid, b["op_id"], b["ver"], confirm=b.get("confirm"), defer=True)
        else:
            now = (ac.view(engine, gid).get("redo") or {}).get("op_id")
            if now != b.get("op_id"):      # 확인한 고침과 지금 다시 할 고침이 다르면 하지 않는다(판 대조와 함께 이중으로 막음)
                return _refused("확인한 뒤 다시 할 고침이 바뀌어(%s → %s) 하지 않았습니다. 다시 요청해 확인 상자를 보세요."
                                % (b.get("op_id"), now or "없음"), "stale", gid)
            out = ac.redo(engine, gid, b["ver"], defer=True)
            if out.get("ok") and out.get("op_id") != b.get("op_id"):
                LOG.error("다시 하기가 확인하지 않은 고침(%s)을 되살림(확인한 것 %s)", out.get("op_id"), b.get("op_id"))
        if not out.get("ok"):
            code = out.get("code") or "failed"
            text = out.get("message") or "저장하지 못했습니다."
            if code == "needs_confirm":
                text = "확인한 뒤 걸리는 것이 바뀌어 저장하지 않았습니다: %s 다시 요청해 확인 상자를 보세요." % text
                code = "stale"
            return _refused(text, code, gid)
        notes = " ".join(out.get("notes") or [])
        verb = {"drawing.edit": "고쳤습니다", "drawing.undo": "되돌렸습니다", "drawing.redo": "다시 했습니다"}[call.action]
        return _ok("도면 %s에서 %s(%s)을(를) %s. %s" % (engine.graph_names().get(gid, gid), out.get("label") or "", out.get("op_id"), verb, notes),
                   topics=["edit", "sheet"])
    return run


# ================================================================ 초기사건 P5: FMEA·MLD(api_ie)

def _p5(engine, item):
    """(지금 읽은 값, 지문 이름, 지문, seen 열쇠 -> 지문) 또는 사유 글."""
    from hazop.shell import api_ie
    a = item.args
    if item.action in ("ie.fmea_status", "ie.fmea_mark"):
        view = api_ie.fmea_view(engine)
        if view is None:
            return "⑥ 초기사건을 열 수 없음(구간·결과가 없음)"
        if item.action == "ie.fmea_status":
            rows = {r["row_id"]: r for r in view["rows"]}
            missing = [r for r in a["row_ids"] if r not in rows]
            if missing:
                return "없는 FMEA 행: %s" % ", ".join(missing[:5])
            return view, "fver", view["fver"], {"fmea:" + r: rows[r]["fp"] for r in a["row_ids"]}
        return view, "fver", view["fver"], None
    view = api_ie.mld_view(engine)
    if view is None or not view.get("loaded"):
        return "주논리도(MLD)를 아직 가져오지 않음(⑥ 패널에서 파일을 고른다)"
    br = {x["id"]: x for x in view["branches"]}
    if a["branch_id"] not in br:
        return "없는 MLD 가지: %s" % a["branch_id"]
    groups = {g["group_id"] for g in view["groups"]}
    bad = [g for g in a.get("group_ids") or [] if g not in groups]
    if bad:
        return "없는 초기사건 그룹: %s" % ", ".join(bad[:5])
    from hazop.ie import mld
    return view, "mver", view["mver"], {"coverage:" + mld.COVER_PREFIX + a["branch_id"]: br[a["branch_id"]]["fp"]}


def _p5_check(engine):
    def check(item, snap):
        from hazop.ie import fmea
        a = item.args
        if not engine.reviewer():
            return "검토자 이름을 먼저 설정에서 입력해야 함"
        if item.action == "ie.fmea_status" and a.get("status") not in fmea.STATUSES:
            return "상태는 %s 가운데 하나" % ", ".join(fmea.STATUSES)
        if item.action == "ie.fmea_mark" and (a.get("mark") or "") not in ("",) + tuple(fmea.MARKS):
            return "표시는 %s 가운데 하나(빈 글자면 지움)" % ", ".join(fmea.MARKS)
        got = _p5(engine, item)
        if isinstance(got, str):
            return got
        view, key, ver, seen = got
        if item.action == "ie.fmea_mark":
            if a["node_id"] not in _node_ids(engine):
                return "없는 구간: %s" % a["node_id"]
        item.targets = list(a.get("row_ids") or []) or [a.get("node_id") or a.get("branch_id")]
        item.basis = {key: ver, "seen": seen}
        return None
    return check


def _node_ids(engine):
    from hazop.shell import api_ie
    ctx, _why = api_ie._context(engine)
    return {n["node_id"] for n in ctx[1]["nodes"]} if ctx else set()


def _p5_details(engine):
    def details(item, snap):
        from hazop.ie import fmea
        a = item.args
        got = _p5(engine, item)
        if isinstance(got, str):
            return [{"label": "오류", "after": got}]
        view, key, ver, seen = got
        rows = []
        if item.action == "ie.fmea_status":
            by = {r["row_id"]: r for r in view["rows"]}
            for rid in a["row_ids"]:
                r = by[rid]
                what = " · ".join(str(x) for x in (r.get("tag"), r.get("failure_mode"), r.get("effect")) if x)
                rows.append({"label": "FMEA %s" % rid, "before": r.get("status"), "after": "%s · %s" % (a["status"], _show(what))})
        elif item.action == "ie.fmea_mark":
            cur = next((n for n in view["ec_nodes"] if n["node_id"] == a["node_id"]), {})
            rows.append({"label": "구간 %s 전기·제어 표시" % a["node_id"], "before": _show(cur.get("mark")) if cur.get("mark") else "(표시 없음)",
                         "after": a.get("mark") or "(표시 지움)"})
            if cur:
                rows.append({"label": "규칙 판정", "after": "전기·제어 구간 규칙에 %s" % ("걸림" if cur.get("rule") else "안 걸림")})
        else:
            br = next(x for x in view["branches"] if x["id"] == a["branch_id"])
            names = {g["group_id"]: g["name"] for g in view["groups"]}
            rows.append({"label": "MLD 가지 %s" % a["branch_id"], "before": ", ".join(br.get("group_ids") or []) or "(이은 그룹 없음)",
                         "after": ", ".join("%s %s" % (g, names.get(g, "")) for g in a["group_ids"]) or "(잇기 지움)"})
        rows.append({"label": "판정자", "after": "%s(확인한 사람)" % _who(engine)})
        rows.append({"label": "파일 판", "after": str(ver)[-12:] + ((" · 항목 지문 " + " · ".join(str(v)[-8:] for _k, v in sorted(seen.items())))
                                                                    if seen else "")})
        return rows
    return details


def _p5_execute(engine):
    def run(args, call):
        from hazop.shell import api_ie
        b = call.basis or {}
        if call.action == "ie.fmea_status":
            out = api_ie.set_fmea_status(engine, {"row_ids": list(args["row_ids"]), "status": args["status"], "fver": b.get("fver"),
                                                  "seen": b.get("seen")})
        elif call.action == "ie.fmea_mark":
            out = api_ie.mark_ec_node(engine, {"node_id": args["node_id"], "mark": args.get("mark") or "", "fver": b.get("fver")})
        else:
            out = api_ie.link_mld_branch(engine, {"branch_id": args["branch_id"], "group_ids": list(args.get("group_ids") or []),
                                                  "mver": b.get("mver"), "seen": b.get("seen")})
        if not out.get("changed"):
            return _ok("바뀐 것이 없습니다.")
        return _ok({"ie.fmea_status": "FMEA 행 상태를 바꿨습니다.", "ie.fmea_mark": "전기·제어 구간 표시를 바꿨습니다.",
                    "ie.mld_link": "MLD 가지에 초기사건 그룹을 이었습니다."}[call.action], topics=["ie"])
    return run


# ================================================================ 설계 문서 판 대응(api_docs docs.revision)

def _rev_ctx(engine, a):
    from hazop.shell import api_docs
    docs = {r["material_id"]: r for r in api_docs.list_documents(engine)}
    row = docs.get(a["material_id"])
    if row is None:
        return "지금 프로젝트에 없는 설계 문서: %s" % a["material_id"]
    if a["answer"] not in ("replace", "separate"):
        return "답은 replace(옛 판을 대신) 또는 separate(다른 문서)"
    asked = [x["material_id"] for x in row.get("ask_revision") or []]
    if not asked:
        return "이 문서에는 판 대응 물음이 없음"
    if a["answer"] == "replace" and a.get("old") not in asked:
        return "old는 물음에 나온 옛 판 가운데 하나: %s" % ", ".join(asked)
    return row, docs


def _rev_check(engine):
    def check(item, snap):
        got = _rev_ctx(engine, item.args)
        if isinstance(got, str):
            return got
        item.targets = [item.args["material_id"]] + ([item.args["old"]] if item.args.get("old") else [])
        return None
    return check


def _rev_details(engine):
    def details(item, snap):
        got = _rev_ctx(engine, item.args)
        if isinstance(got, str):
            return [{"label": "오류", "after": got}]
        row, docs = got
        a = item.args
        rows = [{"label": "새 문서", "after": "%s (%s)" % (row.get("title") or "", row["material_id"])}]
        if a["answer"] == "replace":
            old = docs.get(a["old"]) or {}
            rows.append({"label": "대신할 옛 판", "after": "%s (%s). 옛 판은 지식그래프에서 빠집니다." % (old.get("title") or "", a["old"])})
        else:
            rows.append({"label": "답", "after": "다른 문서로 둡니다(옛 판도 그대로 씀)."})
        rows.append({"label": "정한 사람", "after": "%s(확인한 사람)" % _who(engine)})
        rows.append({"label": "저장 뒤", "after": "프로젝트 지식그래프를 다시 만듭니다."})
        return rows
    return details


def _rev_execute(engine, watcher):
    def run(args, call):
        from hazop.shell import api_docs
        out = api_docs._h_revision(engine, {"material_id": args["material_id"], "answer": args["answer"], "old": args.get("old")})
        job = out.get("job")
        if watcher is not None and job:
            watcher.follow(job, call, [args["material_id"]])
        return _ok("설계 문서 판 대응을 적용하고 있습니다(작업 %s)." % job, topics=["docs"])
    return run


# ================================================================ 도면 연결 짝(B1, api_links)
# 화면의 고치기 카드와 같은 대조: 카드(=확인 상자)가 본 판(ver)·연결점 지문(base)·엔진이 물을 확인 글(confirm)을 그대로 넘긴다.
# 확인 글은 엔진의 마른 실행(dry=True, e028ffa)으로 저장 없이 얻는다(엔진 검사에 막히면 상자를 띄우기 전에 거절).

def _link_point(engine, a, prefix=""):
    """(graph_id, local_id) 또는 사유 글. id(구성요소 ID) 또는 graph_id+local_id. prefix='peer_'면 맞은편."""
    if a.get(prefix + "id"):
        hit = _finder(engine)(a[prefix + "id"])
        return hit if not isinstance(hit, str) else hit
    if a.get(prefix + "graph_id") and a.get(prefix + "local_id"):
        return a[prefix + "graph_id"], a[prefix + "local_id"]
    return "%s연결점(id 또는 graph_id+local_id)이 있어야 함" % ("맞은편 " if prefix else "")


def _link_ctx(engine, item):
    """(view, 이 연결점, 맞은편 또는 None, 뺄 지정 ID 또는 None) 또는 사유 글."""
    from hazop.shell import api_links
    a = item.args
    me = _link_point(engine, a)
    if isinstance(me, str):
        return me
    view = api_links.view(engine, me[0], me[1])
    if not view.get("ok"):
        return view.get("message") or "도면 연결점을 읽지 못함"
    peer = op_id = None
    if item.action == "links.pair":
        peer = _link_point(engine, a, "peer_")
        if isinstance(peer, str):
            return peer
        if peer[0] == me[0]:
            return "같은 도면의 연결점끼리는 짝을 지정하지 않음"
    if item.action == "links.clear":
        op_id = a.get("op_id") or ((view["point"].get("op") or {}).get("op_id"))
        if not op_id:
            return "뺄 지정이 없음(사람이 지정한 짝이나 끊기가 있는 연결점만)"
    return view, me, peer, op_id


class LinkRefused(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _link_ask(engine, item, me, peer, op_id, reason=""):
    """api_links가 저장 전에 물을 확인 글(없으면 None). 엔진의 마른 실행(dry=True: 같은 검사, 저장 안 함)으로 얻는다.
    엔진이 거절하면(stale·bad_args 등) LinkRefused(사유)."""
    from hazop.shell import api_links
    view = api_links.view(engine, me[0], me[1])
    if not view.get("ok"):
        raise LinkRefused(view.get("message") or "도면 연결점을 읽지 못함")
    ver, base = view["ver"], view["point"]["base"]
    if item.action == "links.pair":
        out = api_links.pair(engine, me[0], me[1], peer[0], peer[1], ver, reason, base=base, dry=True)
    elif item.action == "links.unlink":
        out = api_links.unlink(engine, me[0], me[1], ver, reason, base=base, dry=True)
    else:
        out = api_links.clear(engine, me[0], me[1], ver, op_id, base=base, dry=True)
    if not out.get("ok"):
        raise LinkRefused(out.get("message") or "도면 연결 지정을 할 수 없음")
    return out.get("confirm") or None


def _links_check(engine):
    def check(item, snap):
        if not engine.reviewer():
            return "검토자 이름을 먼저 설정에서 입력해야 함(지정한 사람으로 남음)"
        got = _link_ctx(engine, item)
        if isinstance(got, str):
            return got
        view, me, peer, op_id = got
        try:
            ask = _link_ask(engine, item, me, peer, op_id, item.args.get("reason") or "")
        except Exception as exc:  # noqa: BLE001 - 엔진 글을 못 만들면(마른 실행이 거절하면) 상자를 띄우지 않는다
            return getattr(exc, "message", None) or "확인 글을 만들지 못함"
        item.targets = [me[0], me[1]] + (list(peer) if peer else []) + ([op_id] if op_id else [])
        item.basis = {"graph_id": me[0], "local_id": me[1], "ver": view["ver"], "base": view["point"]["base"], "confirm": ask,
                      "peer": list(peer) if peer else None, "op_id": op_id}
        return None
    return check


def _point_text(p):
    if not p:
        return "-"
    return "%s %s(배관 %s, %s 쪽)" % (p.get("drawing_number") or "", p.get("label") or "", p.get("line_no") or "없음", p.get("to_drawing") or "상대 도면 없음")


def _links_details(engine):
    def details(item, snap):
        got = _link_ctx(engine, item)
        if isinstance(got, str):
            return [{"label": "오류", "after": got}]
        view, me, peer, op_id = got
        pt = view["point"]
        now = pt.get("peer")
        now_text = "%s %s" % (now.get("drawing_number") or "", now.get("label") or "") if now else "(짝 없음)"
        rows = [{"label": "연결점", "after": _point_text(pt)}]
        if item.action == "links.pair":
            cand = next((c for c in view["candidates"] if (c["graph_id"], c["local_id"]) == tuple(peer)), None)
            if cand is None:
                from hazop.shell import api_links
                other = api_links.view(engine, peer[0], peer[1])
                cand = dict(other["point"], warn=[]) if other.get("ok") else {"drawing_number": peer[0], "label": peer[1], "warn": []}
            rows.append({"label": "짝", "before": now_text, "after": _point_text(cand)})
            if cand.get("warn"):
                rows.append({"label": "주의", "after": "; ".join(cand["warn"])})
        elif item.action == "links.unlink":
            rows.append({"label": "짝", "before": now_text, "after": "연결하지 않음(사람이 끊음)"})
        else:
            op = pt.get("op") or {}
            what = "%s %s · %s %s" % (op_id, op.get("op") or "", op.get("by") or "", op.get("at") or "") if op.get("op_id") == op_id else op_id
            rows.append({"label": "뺄 지정", "before": what, "after": "(지정 빼기: 자동 판정으로 돌아감)"})
        if (item.args.get("reason") or "").strip():
            rows.append({"label": "사유(AI가 씀)", "after": _show(item.args["reason"])})
        try:
            ask = _link_ask(engine, item, me, peer, op_id, item.args.get("reason") or "")
        except Exception as exc:  # noqa: BLE001
            return [{"label": "오류", "after": getattr(exc, "message", None) or "확인 글을 만들지 못함"}]
        if ask:
            rows.append({"label": "엔진 확인", "after": ask})
        rows.append({"label": "지정한 사람", "after": "%s(확인한 사람)" % _who(engine)})
        rows.append({"label": "저장 뒤", "after": "프로젝트 그래프가 이 지정을 먼저 적용합니다. 도면·쪽 확정은 바뀌지 않습니다."})
        rows.append({"label": "판", "after": "%s · 연결점 지문 %s" % (str(view["ver"])[-8:], pt["base"][-8:])})
        return rows
    return details


def _links_execute(engine):
    def run(args, call):
        from hazop.shell import api_links
        b = call.basis or {}
        if not b.get("ver") or not b.get("base"):
            return _refused("확인 상자에서 본 판·연결점 지문이 없어 저장하지 않았습니다.", "stale")
        reason = args.get("reason") or ""
        if call.action == "links.pair":
            out = api_links.pair(engine, b["graph_id"], b["local_id"], b["peer"][0], b["peer"][1], b["ver"], reason, base=b["base"],
                                 confirm=b.get("confirm"))
        elif call.action == "links.unlink":
            out = api_links.unlink(engine, b["graph_id"], b["local_id"], b["ver"], reason, base=b["base"], confirm=b.get("confirm"))
        else:
            out = api_links.clear(engine, b["graph_id"], b["local_id"], b["ver"], b["op_id"], base=b["base"], confirm=b.get("confirm"))
        if not out.get("ok"):
            code, text = out.get("code") or "failed", out.get("message") or "저장하지 못했습니다."
            if code == "needs_confirm":
                text, code = "확인한 뒤 걸리는 것이 바뀌어 저장하지 않았습니다: %s 다시 요청해 확인 상자를 보세요." % text, "stale"
            return _refused(text, code, b["graph_id"])
        more = " 재확인할 구간: %s." % ", ".join(str(x) for x in out["recheck"]) if out.get("recheck") else ""
        return _ok(" ".join(out.get("notes") or ["도면 연결 지정을 저장했습니다."]) + more, topics=["links", "nodes"])
    return run


# ================================================================ 표

def checks(engine, running):
    out = {name: _tb_check(engine, running) for name in TITLEBLOCK_ACTIONS}
    out.update({name: _drawing_check(engine) for name in DRAWING_ACTIONS})
    out.update({name: _p5_check(engine) for name in P5_ACTIONS})
    out["docs.revision"] = _rev_check(engine)
    out.update({name: _links_check(engine) for name in LINK_ACTIONS})
    return out


def details(engine):
    out = {name: _tb_details(engine) for name in TITLEBLOCK_ACTIONS}
    out.update({name: _drawing_details(engine) for name in DRAWING_ACTIONS})
    out.update({name: _p5_details(engine) for name in P5_ACTIONS})
    out["docs.revision"] = _rev_details(engine)
    out.update({name: _links_details(engine) for name in LINK_ACTIONS})
    return out


def executors(engine, running, watcher=None):
    out = {name: _guard(_tb_execute(engine, running, watcher)) for name in TITLEBLOCK_ACTIONS}
    out.update({name: _guard(_drawing_execute(engine)) for name in DRAWING_ACTIONS})
    out.update({name: _guard(_p5_execute(engine)) for name in P5_ACTIONS})
    out["docs.revision"] = _guard(_rev_execute(engine, watcher))
    out.update({name: _guard(_links_execute(engine)) for name in LINK_ACTIONS})
    return out
