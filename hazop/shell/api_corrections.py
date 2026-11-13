"""새 웹 화면의 도면 고치기(INTENT.md §3.2·§4, 완료 목록 2 A5). Qt를 import하지 않는다.

이전 화면(hazop/app/screens/viewer.py)이 하던 일을 같은 엔진(hazop.extract.corrections)으로 한다. 다른 점은 저장 시점뿐이다:
이전 화면은 작업 중 연산을 모아 '저장'을 눌렀고, 새 화면은 **연산 하나가 곧 저장 하나**이고 되돌리기·다시 하기도 저장으로 남는다.

- **읽기** `edit/<도면 ID>`(판, 연산 목록과 적용 상태, 되돌리기·다시 하기 대상, 종류 고르기 목록), `edit/<도면 ID>/item/<local_id>`
  (그 항목에서 할 수 있는 고침과 지금 값, 고침이 걸리는 것: 쪽 확정, 그 구성요소가 든 검토구간).
- **명령** `edit.apply`(연산 하나), `edit.undo`(연산 하나 빼기), `edit.redo`(마지막으로 뺀 연산 되살리기). 모두 화면이 본 판(`ver`, 세 파일 지문)을
  대조해 어긋나면 stale로 거절하고, 프로젝트 ID는 api.dispatch가 대조한다. 고친 사람은 설정의 검토자 이름, 때는 엔진이 채운다.
- **저장 뒤** 그 도면 그래프와 프로젝트 지식그래프를 다시 만든다(hazop.shell.sheet_refresh, AI 후보와 같은 길). 실패해도 저장은 남았으니
  '저장됨, 그래프 갱신 실패'를 돌려주고 낡은 그래프 표시를 남긴다(다음 동작에서 다시 만든다).
- 채팅(d-chat)이 부를 실행 함수: `view`, `item`, `apply_edit`, `undo`, `redo`. 모두 {"ok", ...} 사전을 돌려주고 예외를 올리지 않는다.
  웹과 채팅 모두 도면 ID·도면 안 local_id만 주고받는다(경로 없음).

웹이 보내는 값(도면 좌표는 화면 좌표 = 추출 좌표 - svg_alignment.offset, 기기·연결은 도면 안 local_id):
  set_tag {tag} · set_kind {kind} · set_normal_position·set_fail_position {value} · set_flow {from, to} 또는 {flip: true} ·
  confirm {items: [{check, reason}]} · set_endpoint {end, node} · clear_endpoint {end} · set_path {points} ·
  add_node {kind, tag, at: [x, y]} · delete_node {} · add_relation {kind, from, to, line_no} · delete_relation {}
"""

import copy
import logging

from hazop import store_io
from hazop.extract import corrections, rules
from hazop.shell import sheet_refresh

LOG = logging.getLogger("hazop.shell.api_corrections")
TOPICS = ("edit",)
PROJECT_PREFIXES = ("edit.",)
NEW_NODE_SIZE = 40                         # 기기 추가: 누른 점을 가운데로 하는 정사각형(이전 화면과 같다)
RELATION_KINDS = (("physical_connection", "공정 배관", "process"), ("signal_connection", "계장 신호", "signal"),
                  ("measurement_connection", "계측 연결", "instrument_tap"))
OP_LABELS = {"set_tag": "태그", "set_kind": "종류", "set_normal_position": "정상 위치", "set_fail_position": "고장 위치",
             "set_flow": "흐름 방향", "set_endpoint": "끝 잇기", "clear_endpoint": "끝 끊기", "set_path": "경로 다시 그리기",
             "confirm": "미확인 확정", "add_node": "기기 추가", "delete_node": "기기 삭제", "add_relation": "연결 추가",
             "delete_relation": "연결 삭제"}
DELETES = ("delete_node", "delete_relation")
STALE_TEXT = "도면 수정 기록이나 AI 후보가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 해 주세요."


class Refused(Exception):
    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail


def _api():
    from hazop.shell import api
    return api


# ---------------------------------------------------------------- 자료 읽기

def _name(engine, graph_id):
    name = engine.graph_names().get(graph_id)
    if not name:
        raise Refused("not_found", "없는 도면")
    return name


def _sources(name):
    """(원본 추출, 저장된 연산, 수정 기록 문서, 그 지문, 고친 추출)."""
    from hazop.app import data
    original = data.read_json(data.extraction_path(name))
    doc, fp = corrections.load_fp(name)
    ops = list((doc or {}).get("ops") or [])
    return original, ops, doc, fp, corrections.apply(original, ops)


def _index(corrected):
    """local_id -> ("node" | "relation", 항목). 끝이 열린 연결도 연결로 본다."""
    out = {n["local_id"]: ("node", n) for n in corrected.get("nodes") or []}
    for key in ("relations", "unresolved_connectors"):
        out.update((r["local_id"], ("relation", r)) for r in corrected.get(key) or [])
    return out


def _offset(extraction):
    from hazop.shell import sheet_items
    return sheet_items._offset(extraction)


def _redo_stack(doc):
    """되돌리기로 뺀 연산 가운데 아직 되살리지 않은 것(마지막이 위). 되돌리기·다시 하기가 아닌 저장이 끼면 비운다."""
    stack = []
    for entry in (doc or {}).get("log") or []:
        action = entry.get("action")
        if action == "undo":
            stack += entry.get("removed_ops") or []
        elif action == "redo":
            back = set(entry.get("added") or [])
            stack = [o for o in stack if o.get("op_id") not in back]
        else:
            stack = []
    return stack


def _depends(ops, op_id):
    """이 연산이 만든 기기·연결(manual-<op_id>)을 가리키는 뒤 연산."""
    mine = corrections.MANUAL_PREFIX + op_id
    out = []
    for o in ops:
        v = o.get("value") or {}
        if o.get("target") == mine or any(v.get(k) == mine for k in corrections.REF_KEYS):
            out.append(o["op_id"])
    return out


def _op_row(op, corrected, by_sid):
    c = corrected.get("corrections") or {}
    status = "applied" if op["op_id"] in (c.get("applied") or []) else "not_applicable"
    reason = next((x["reason"] for x in c.get("not_applicable") or [] if x.get("op_id") == op["op_id"]), None)
    target = op.get("target")
    if op["op"] in ("add_node", "add_relation"):
        target = corrections.MANUAL_PREFIX + op["op_id"]
    return {"op_id": op["op_id"], "op": op["op"], "label": OP_LABELS.get(op["op"], op["op"]), "local_id": by_sid.get(target, target),
            "by": op.get("by"), "at": op.get("at"), "status": status, "reason": reason}


def _kinds():
    """기기 종류 고르기 목록: [{kind, label, category}] 사전의 한글 이름 순."""
    from hazop.shell.sheet_items import kind_label
    rows = [{"kind": k, "label": kind_label(k) or k, "category": cat} for k, cat in rules.KIND_CATEGORY.items()]
    return sorted(rows, key=lambda r: (r["category"], r["label"]))


def view(engine, graph_id):
    """도면 한 장의 고치기 머리: {ok, graph_id, ver, ops, undoable, redo, graph_stale, kinds, relation_kinds}."""
    try:
        name = _name(engine, graph_id)
        original, ops, doc, _fp, corrected = _sources(name)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except (OSError, ValueError) as exc:
        return {"ok": False, "code": "failed", "message": "도면 수정 기록을 읽지 못했습니다(%s)." % str(exc)[:160]}
    by_sid = {sid_local[0]: sid_local[1] for sid_local in _sid_local(corrected)}
    rows = [_op_row(o, corrected, by_sid) for o in ops]
    redo = _redo_stack(doc)
    return {"ok": True, "graph_id": graph_id, "ver": sheet_refresh.ver_of(name), "ops": rows,
            "undoable": [r["op_id"] for i, r in enumerate(rows) if not _depends(ops[i + 1:], r["op_id"])][-20:],
            "redo": {"op_id": redo[-1]["op_id"], "label": OP_LABELS.get(redo[-1]["op"], redo[-1]["op"])} if redo else None,
            "graph_stale": sheet_refresh.graph_stale(name), "kinds": _kinds(),
            "relation_kinds": [{"kind": k, "label": label} for k, label, _lt in RELATION_KINDS],
            "unknowns": len(((corrected.get("validation") or {}).get("unknowns")) or [])}


def _sid_local(corrected):
    for n in corrected.get("nodes") or []:
        yield n["source_object_id"], n["local_id"]
    for key in ("relations", "unresolved_connectors"):
        for r in corrected.get(key) or []:
            yield r["source_object_id"], r["local_id"]


def _impact(engine, graph_id, name, local_ids):
    """고침이 걸리는 것: 쪽 확정 상태, 그 구성요소가 든 검토구간(확정·잠금 여부)."""
    from hazop.app import project_ctx
    from hazop.chat import view as chatview
    from hazop.extract import confirmation
    from hazop.study import nodes as study_nodes
    out = {"sheet": None, "nodes": []}
    try:
        out["sheet"] = (confirmation.sheet_confirmation(name) or {}).get("status")
    except (OSError, ValueError):
        out["sheet"] = None
    try:
        pg = project_ctx.project_graph(engine.project_id())
        ns = study_nodes.read_as_is(pg)
    except (OSError, ValueError, KeyError):
        return out
    if not ns or (ns.get("schema_version") or study_nodes.LEGACY_SCHEMA_VERSION) == study_nodes.LEGACY_SCHEMA_VERSION:
        return out
    _fwd, back = chatview._locals(pg)
    ents = {back.get((graph_id, lid)) for lid in local_ids} - {None}
    for n in ns.get("nodes") or []:
        if ents & set(n.get("members") or []):
            out["nodes"].append({"node_id": n["node_id"], "name": n.get("name"), "state": study_nodes.node_state(n)})
    return out


def item(engine, graph_id, local_id):
    """항목 하나의 고치기 카드 자료."""
    try:
        name = _name(engine, graph_id)
        original, ops, _doc, _fp, corrected = _sources(name)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except (OSError, ValueError) as exc:
        return {"ok": False, "code": "failed", "message": "도면 수정 기록을 읽지 못했습니다(%s)." % str(exc)[:160]}
    idx = _index(corrected)
    hit = idx.get(local_id)
    if not hit:
        return {"ok": False, "code": "not_found", "message": "도면에 없는 항목입니다."}
    kind, obj = hit
    from hazop.kg.schema import REGISTRY
    from hazop.shell.sheet_items import kind_label
    unknowns = [{"check": u["check"], "reason": u.get("reason") or ""} for u in (corrected.get("validation") or {}).get("unknowns") or []
                if u.get("target") == local_id]
    row = {"ok": True, "graph_id": graph_id, "local_id": local_id, "type": kind, "kind": obj.get("kind"), "kind_label": kind_label(obj.get("kind")),
           "tag": obj.get("tag") if kind == "node" else obj.get("line_no"), "manual": str(obj.get("source_object_id") or "").startswith(corrections.MANUAL_PREFIX),
           "human_edit": (obj.get("human_edit") or {}).get("ops") or [], "unknowns": unknowns, "ver": sheet_refresh.ver_of(name),
           "impact": _impact(engine, graph_id, name, [local_id])}
    if kind == "node":
        cid = REGISTRY.kind_class.get(obj.get("kind"))
        have = REGISTRY.class_properties(cid) if cid else []
        row["positions"] = [{"op": op, "prop": prop, "label": REGISTRY.properties[prop]["label_ko"], "values": list(REGISTRY.properties[prop]["values"]),
                             "value": (obj.get("attributes") or {}).get(prop)}
                            for op, prop in (("set_normal_position", "normal_position"), ("set_fail_position", "fail_position")) if prop in have]
    else:
        ends = {ep["end"]: ep for ep in obj.get("endpoints") or []}
        fd = obj.get("flow_direction") or None
        row.update(relation_kind=obj.get("kind"), line_type=obj.get("line_type"),
                   ends={e: {"node": (ends.get(e) or {}).get("node_local_id"), "status": (ends.get(e) or {}).get("status")} for e in corrections.ENDS},
                   flow={"from": fd.get("from"), "to": fd.get("to"), "basis": fd.get("basis")} if fd else None,
                   flow_allowed=obj.get("kind") in rules.RELATION_KINDS_WITH_FLOW)
    return row


# ---------------------------------------------------------------- 웹 값 → 엔진 연산

def _sid_of(idx, local_id, want=None):
    hit = idx.get(local_id) if isinstance(local_id, str) else None
    if not hit or (want and hit[0] != want):
        raise Refused("bad_args", "도면에 없는 %s입니다: %s" % ("기기" if want == "node" else "항목", local_id))
    return hit[1]["source_object_id"]


def _request(op, local_id, value, corrected, original):
    """웹이 보낸 (연산, local_id, 값) → (엔진 target, 엔진 value)."""
    if op not in corrections.OPS:
        raise Refused("bad_args", "모르는 고침입니다: %s" % op)
    idx = _index(corrected)
    spec = corrections.OPS[op]
    target = None
    if spec.targets:
        hit = idx.get(local_id)
        if not hit:
            raise Refused("not_found", "도면에 없는 항목입니다.")
        if hit[0] not in spec.targets:
            raise Refused("bad_args", "%s은(는) %s에 쓸 수 없습니다." % (OP_LABELS.get(op, op), "기기" if hit[0] == "node" else "연결"))
        target = hit[1]["source_object_id"]
    v = dict(value or {})
    ox, oy = _offset(original)
    if op == "set_kind":
        kind = str(v.get("kind") or "")
        if kind not in rules.KIND_CATEGORY:
            raise Refused("bad_args", "사전에 없는 종류입니다: %s" % kind)
        v = {"kind": kind, "category": rules.KIND_CATEGORY[kind]}
    elif op == "set_flow":
        rel = idx[local_id][1]
        if v.get("flip"):
            ends = {ep.get("end"): ep.get("node_local_id") for ep in rel.get("endpoints") or []}
            fd = rel.get("flow_direction")
            a, b = (fd["to"], fd["from"]) if fd and fd.get("from") in idx and fd.get("to") in idx else (ends.get("target"), ends.get("source"))
            if a not in idx or b not in idx:
                raise Refused("bad_args", "양 끝이 모두 기기에 이어져야 흐름 방향을 정할 수 있습니다(끝 잇기 먼저).")
            v = {"from": a, "to": b}
        v = {"from": _sid_of(idx, v.get("from"), "node"), "to": _sid_of(idx, v.get("to"), "node")}
    elif op == "set_endpoint":
        v = {"end": v.get("end"), "node": _sid_of(idx, v.get("node"), "node")}
    elif op == "add_relation":
        kind = v.get("kind") or "physical_connection"
        lt = next((lt for k, _l, lt in RELATION_KINDS if k == kind), None)
        if lt is None:
            raise Refused("bad_args", "모르는 연결 종류입니다: %s" % kind)
        v = {"kind": kind, "line_type": lt, "line_no": (v.get("line_no") or None),
             "from": _sid_of(idx, v.get("from"), "node"), "to": _sid_of(idx, v.get("to"), "node")}
    elif op == "add_node":
        kind = str(v.get("kind") or "")
        if kind not in rules.KIND_CATEGORY:
            raise Refused("bad_args", "사전에 없는 종류입니다: %s" % kind)
        at = v.get("at")
        if not (isinstance(at, list) and len(at) == 2 and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in at)):
            raise Refused("bad_args", "기기를 놓을 자리(at)가 없습니다.")
        h = NEW_NODE_SIZE
        v = {"kind": kind, "category": rules.KIND_CATEGORY[kind], "tag": (v.get("tag") or "").strip(),
             "bbox": [at[0] + ox - h / 2, at[1] + oy - h / 2, h, h]}
    elif op == "set_path":
        pts = v.get("points")
        if not isinstance(pts, list):
            raise Refused("bad_args", "경로 점이 없습니다.")
        v = {"points": [[p[0] + ox, p[1] + oy] for p in pts if isinstance(p, list) and len(p) == 2]}
    return target, v


def _tag_conflicts(engine, name, corrected, tag, exclude_local):
    from hazop.app import data
    key = (tag or "").strip().casefold()
    if not key:
        return []
    hits = [h for h in data.tag_conflicts(tag, corrected.get("project_id")) if h.get("name") != name]
    hits += [{"name": name, "local_id": n["local_id"]} for n in corrected.get("nodes") or []
             if n["local_id"] != exclude_local and (n.get("tag") or "").strip().casefold() == key]
    return hits


# ---------------------------------------------------------------- 쓰기

def _write(engine, graph_id, name, ops, by, doc, fp, action, original):
    """연산 목록을 저장하고 그래프를 다시 만든다. 저장 전 쪽 확정 상태를 보아 풀리면 알린다. → 답의 공통 부분."""
    from hazop.extract import confirmation
    try:
        before = (confirmation.sheet_confirmation(name) or {}).get("status")
    except (OSError, ValueError):
        before = None
    corrections.save_fp(name, ops, by, drawing_number=(original.get("drawing") or {}).get("drawing_number"), expect=fp, action=action)
    # 여기부터는 저장이 끝났다. 어떤 예외도 '저장 안 됨'으로 알리지 않는다
    try:
        stale, notes, recheck = sheet_refresh.refresh(name)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("그래프 다시 만들기 실패")
        stale, notes, recheck = True, ["저장했지만 그래프를 다시 만들지 못했습니다(%s)." % type(exc).__name__], []
    try:
        after = (confirmation.sheet_confirmation(name) or {}).get("status")
    except (OSError, ValueError):
        after = None
    released = before in ("compared", "confirmed") and after not in ("compared", "confirmed")
    if released:
        notes = notes + ["이 쪽의 %s이 풀렸습니다. 다시 견주고 확정하세요." % ("확정" if before == "confirmed" else "견줌")]
    for topic, rev in (("edit", graph_id), ("sheet", graph_id), ("drawings", None), ("sheetconf", None), ("aireview", None), ("kg", None), ("nodes", None)):
        engine.changed(topic, rev)
    return {"ok": True, "graph_id": graph_id, "ver": sheet_refresh.ver_of(name), "graph_stale": stale, "notes": notes, "recheck": recheck,
            "released": released}


def _guard(engine, graph_id, ver, by):
    name = _name(engine, graph_id)
    by = by or engine.reviewer()
    if not by:
        raise Refused("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 고친 사람으로 남습니다.")
    if not ver or ver != sheet_refresh.ver_of(name):
        raise Refused("stale", STALE_TEXT if ver else "읽은 판(ver)이 없어 저장하지 않았습니다. 도면을 다시 읽으세요.")
    return name, by


def _run(fn):
    try:
        return fn()
    except Refused as exc:
        out = {"ok": False, "code": exc.code, "message": exc.message}
        if exc.detail is not None:
            out["detail"] = exc.detail
        return out
    except store_io.Conflict:
        return {"ok": False, "code": "stale", "message": STALE_TEXT}
    except (OSError, ValueError) as exc:
        LOG.exception("도면 고치기 실패")
        return {"ok": False, "code": "failed", "message": "저장하지 못했습니다(%s)." % str(exc)[:160]}


def apply_edit(engine, graph_id, op, local_id, value, ver, confirm=False, by=None):
    """고침 하나를 저장한다. 지우기와 태그 겹침은 confirm=True여야 한다(아니면 needs_confirm과 걸리는 것을 돌려준다)."""
    def go():
        name, who = _guard(engine, graph_id, ver, by)
        sheet_refresh.ensure_graph(name)
        original, ops, doc, fp, corrected = _sources(name)
        target, v = _request(op, local_id, value, corrected, original)
        if op in DELETES and not confirm:
            impact = _impact(engine, graph_id, name, [local_id])
            held = [n for n in impact["nodes"] if n["state"] != "applied"]
            msg = "%s을(를) 지웁니다. 되돌리기로 살릴 수 있습니다." % (local_id,)
            if held:
                msg += " 확정·잠금 구간 %s에 든 구성요소입니다. 지우면 그 구간을 재확인해야 합니다." % ", ".join(n["node_id"] for n in held)
            raise Refused("needs_confirm", msg, {"impact": impact})
        if op in ("set_tag", "add_node") and not confirm:
            node_tag = op == "add_node" or _index(corrected)[local_id][0] == "node"
            hits = _tag_conflicts(engine, name, corrected, v.get("tag"), local_id) if node_tag else []
            if hits:
                where = ", ".join("%s(%s)" % (h.get("name"), h.get("local_id")) for h in hits[:5])
                raise Refused("needs_confirm", "태그 '%s'가 이미 있습니다: %s. 태그는 프로젝트 전체에서 유일해야 합니다. 그래도 고칠까요?" % (v.get("tag"), where),
                              {"conflicts": hits[:20]})
        try:
            new = corrections.make_op(original, op, target, v, who, existing_ops=ops, name=name)
        except ValueError as exc:
            raise Refused("bad_args", str(exc))
        out = _write(engine, graph_id, name, ops + [new], who, doc, fp, "edit", original)
        made = corrections.MANUAL_PREFIX + new["op_id"] if op in ("add_node", "add_relation") else None
        return dict(out, op_id=new["op_id"], label=OP_LABELS.get(op, op), created=made)
    return _run(go)


def undo(engine, graph_id, op_id, ver, by=None):
    """연산 하나를 뺀다(그 연산이 만든 기기·연결을 뒤 연산이 쓰면 빼지 않는다). 뺀 연산은 다시 하기로 되살릴 수 있다."""
    def go():
        name, who = _guard(engine, graph_id, ver, by)
        original, ops, doc, fp, _corrected = _sources(name)
        pos = next((i for i, o in enumerate(ops) if o["op_id"] == op_id), None)
        if pos is None:
            raise Refused("not_found", "없는 고침입니다(이미 되돌렸을 수 있습니다).")
        later = _depends(ops[pos + 1:], op_id)
        if later:
            raise Refused("bad_args", "이 고침이 만든 것을 뒤 고침(%s)이 씁니다. 뒤 고침부터 되돌리세요." % ", ".join(later[:5]))
        out = _write(engine, graph_id, name, ops[:pos] + ops[pos + 1:], who, doc, fp, "undo", original)
        return dict(out, op_id=op_id, label=OP_LABELS.get(ops[pos]["op"], ops[pos]["op"]))
    return _run(go)


def redo(engine, graph_id, ver, by=None):
    """마지막으로 되돌린 연산을 그대로 되살린다(번호·내용이 같다)."""
    def go():
        name, who = _guard(engine, graph_id, ver, by)
        original, ops, doc, fp, _corrected = _sources(name)
        stack = _redo_stack(doc)
        if not stack:
            raise Refused("not_found", "다시 할 고침이 없습니다.")
        op = copy.deepcopy(stack[-1])
        trial = corrections.apply(original, ops + [op])["corrections"]
        why = next((x["reason"] for x in trial["not_applicable"] if x["op_id"] == op["op_id"]), None)
        if why:
            raise Refused("bad_args", "다시 할 수 없습니다: %s" % why)
        out = _write(engine, graph_id, name, ops + [op], who, doc, fp, "redo", original)
        return dict(out, op_id=op["op_id"], label=OP_LABELS.get(op["op"], op["op"]))
    return _run(go)


# ---------------------------------------------------------------- 읽기·명령 등록

def read(engine, parts, query):
    api = _api()
    if len(parts) == 2:
        data = view(engine, parts[1])
    elif len(parts) == 4 and parts[2] == "item":
        data = item(engine, parts[1], parts[3])
    else:
        return None
    if not data["ok"] and data.get("code") == "not_found":
        return None
    return api._json(data)


def _unwrap(res):
    if res.get("ok"):
        return {k: v for k, v in res.items() if k != "ok"}
    err = _api().CommandError(res["code"], res["message"])
    if res.get("detail") is not None:
        err.detail = res["detail"]
    raise err


def register(commands):
    api = _api()
    C, v_str, v_bool, v_enum, v_json = api.Command, api.v_str, api.v_bool, api.v_enum, api.v_json_text
    base = {"graph_id": (v_str(1, 200), True), "ver": (v_str(1, 40), True)}

    def put(name, spec_, handler, doc):
        key = "edit." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("apply", dict(base, op=(v_enum(*corrections.OPS), True), local_id=(v_str(1, 200), False), value=(v_json(20000), False),
                      confirm=(v_bool(), False)),
        lambda engine, a: _unwrap(apply_edit(engine, a["graph_id"], a["op"], a.get("local_id"), a.get("value") or {}, a["ver"], bool(a.get("confirm")))),
        "도면 고침 하나를 저장하고 그래프를 다시 만든다(지우기·태그 겹침은 confirm)")
    put("undo", dict(base, op_id=(v_str(1, 40), True)), lambda engine, a: _unwrap(undo(engine, a["graph_id"], a["op_id"], a["ver"])),
        "도면 고침 하나를 뺀다(다시 하기로 되살릴 수 있다)")
    put("redo", dict(base), lambda engine, a: _unwrap(redo(engine, a["graph_id"], a["ver"])), "마지막으로 뺀 도면 고침을 되살린다")
