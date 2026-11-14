"""도면 연결(오각형) 짝을 사람이 지정·끊기(완료 목록 3 B1, 규격 docs/design/app-shell-web.md §2.3 '도면 연결 짝').
이전 화면(hazop/app/screens/viewer.py의 짝 지정 대화상자·연결 끊기·오래됨 안내)의 기능을 새 화면의 고치기 카드로 옮긴다. Qt를 import하지 않는다.

- 저장은 프로젝트의 사람 지정 기록(hazop.graph.project.save_manual, `drawing-links/<프로젝트>.json`) 하나다. 도면 그래프(graph.json)는 바꾸지 않고,
  프로젝트 그래프를 지을 때 project.match가 이 기록을 먼저 적용한다(쪽별 캐시는 graph.json만 열쇠로 쓰고 짝 찾기는 매번 다시 하므로 지정이 바로 보인다).
- 쪽 확정(추출 결과·사람 수정 기록·AI 후보의 지문)은 이 기록을 보지 않으므로 짝 지정으로 풀리지 않는다. 지식그래프도 이 기록을 쓰지 않는다.
- A5와 같은 저장 규칙: 프로젝트별 잠금 안에서 읽기 → 대조 → 쓰기. 화면이 본 판(`ver`: 기록 파일 지문 + 프로젝트 그래프 판), 카드에서 본 연결점의
  지문(`base`), 확인 글(`confirm`, 엔진이 지금 다시 만든 글과 같아야 함), 프로젝트 ID(명령 머리 `links.`를 프로젝트에 묶음)를 대조한다.
  쓰기는 읽을 때의 파일 지문을 store_io에 넘겨 다른 프로세스가 그 사이 바꿨으면 쓰지 않는다.
- 확인을 받는 것: 지금 있는 짝이 풀리는 지정·끊기(이 연결점의 짝, 고른 후보의 짝), 확정·잠금 구간에 든 연결점. 저장 뒤에는 구간 재확인 안내를 돌려준다.
- 오래됨: 지정이 가리키는 연결점을 프로젝트 도면에서 찾지 못하면(원본이 바뀜) project.match가 건너뛰고 manual_skipped에 남긴다. 그 도면의 카드가
  사유와 함께 보이고 '지정 지우기'로 뺄 수 있다.

웹 명령: links.pair · links.unlink · links.clear. 읽기: links/<graph_id>/<local_id>[?q=찾을 글]. 채팅은 같은 이름의 함수(view·pair·unlink·clear)를 부른다.
"""

import hashlib
import json
import logging
import uuid

from hazop import store_io
from hazop.graph import project
from hazop.shell import sheet_refresh

LOG = logging.getLogger("hazop.shell.api_links")
CANDIDATE_LIMIT = 60


class Refused(Exception):
    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail


# ---------------------------------------------------------------- 읽기

def _pg(engine):
    from hazop.app import project_ctx
    pid = engine.project_id()
    if not pid:
        raise Refused("bad_args", "프로젝트를 먼저 고르세요.")
    try:
        return pid, project_ctx.project_graph(pid)
    except ValueError as exc:
        raise Refused("not_found", "프로젝트 그래프가 없습니다(%s)." % str(exc)[:120])


def _manual(pid):
    """(지정 기록 ops, 파일 지문). 지문은 읽은 바로 그 바이트의 것이다."""
    data, fp = store_io.read_bytes(project.manual_path(pid))
    if data is None:
        return [], None
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("kind") != project.MANUAL_KIND:
        raise Refused("failed", "도면 연결 지정 파일의 모양이 다릅니다.")
    return list(doc.get("ops") or []), fp


def _ver(fp, pg):
    return hashlib.sha256(("%s|%s" % (fp or "-", pg.get("graph_version"))).encode("utf-8")).hexdigest()[:16]


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _numbers(pg):
    return {s["graph_id"]: s.get("drawing_number") for s in pg.get("sheets") or []}


def _label(n):
    from hazop.app import project_ctx
    return project_ctx.continuation_label(n)


def _entity(pg, graph_id, local_id):
    from hazop.chat import view as chatview
    _fwd, back = chatview._locals(pg)
    eid = back.get((graph_id, local_id))
    by_id = {n["entity_id"]: n for n in pg["nodes"]} if eid else {}
    n = by_id.get(eid)
    if n is None:
        raise Refused("not_found", "이 도면에 없는 항목입니다.")
    if n.get("kind") != "continuation":
        raise Refused("bad_args", "도면 연결(오각형)만 짝을 지정할 수 있습니다.")
    return n, by_id


def _link_of(pg, n):
    lid = (n.get("sheet_link") or {}).get("link_id")
    return next((l for l in pg.get("sheet_links") or [] if l["link_id"] == lid), None)


def _end(n, nums):
    """지정 기록의 끝: 도면 번호·원본 번호와 연결점 지문(라벨·배관 번호·상대 도면·방향·자리). 다시 추출로 번호가 밀려도
    project.match가 지문으로 같은 연결점을 찾거나, 못 찾으면 붙이지 않고 '오래된 지정'으로 돌린다(B1 검토 차단)."""
    return project.end_ref({"graph_id": n["sheet"], "source": {"drawing_number": nums.get(n["sheet"])}}, n)


def _name_of(n, nums):
    """알림 글에 쓰는 연결점 이름: '<도면 번호> <라벨>'."""
    return "%s %s" % (nums.get(n["sheet"]) or n["sheet"], _label(n))


def _end_key(end):
    return ((end.get("drawing_number") or "").strip().upper(), end.get("source_object_id"))


def _peer_of(pg, n, by_id):
    """짝이 있으면 그 노드."""
    link = n.get("sheet_link") or {}
    if link.get("status") != project.LINKED or not link.get("peer"):
        return None
    return by_id.get(link["peer"])


def _owners(pg):
    """프로젝트 구성요소 ID → [(구간 ID, 상태)]. 프로젝트 구간 집합이 없거나 옛 모양이면 빈 사전."""
    from hazop.study import nodes as sn
    try:
        ns = sn.read_as_is(pg)
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for node in (ns or {}).get("nodes") or []:
        for m in node.get("members") or []:
            out.setdefault(m, []).append((node["node_id"], sn.node_state(node)))
    return out


def _point(pg, n, by_id, ops):
    nums = _numbers(pg)
    link = _link_of(pg, n) or {}
    key = project.continuation_key({"graph_id": n["sheet"], "source": {"drawing_number": nums.get(n["sheet"])}}, n)
    op = next((o for o in ops if o.get("op_id") and o["op_id"] == link.get("op_id")), None)
    peer = _peer_of(pg, n, by_id)
    out = {"local_id": n.get("local_id"), "label": _label(n), "drawing_number": nums.get(n["sheet"]), "line_no": key["line_no"],
           "to_drawing": key["to_drawing"], "direction": key["direction"], "status": link.get("status") or "unlinked",
           "reason": link.get("reason"), "reason_text": project.REASONS.get(link.get("reason")) if link.get("reason") else None,
           "origin": link.get("origin"), "op": {k: op.get(k) for k in ("op_id", "op", "by", "at", "reason")} if op else None,
           "peer": {"graph_id": peer["sheet"], "local_id": peer.get("local_id"), "drawing_number": nums.get(peer["sheet"]),
                    "label": _label(peer)} if peer else None,
           "check": link.get("check")}         # no_fingerprint: 지문 없이 남은 옛 지정(번호만 보고 붙임, 사람이 확인해야 함)
    out["base"] = _sha([out["status"], (peer or {}).get("entity_id"), out["origin"], link.get("op_id")])
    return out


def _candidates(pg, n, by_id, q=None):
    """맞은편 후보: 다른 도면의 연결점. 짝 없는 것 → 이 도면을 가리키는 것 → 배관 번호가 같은 것 순(이전 화면과 같음)."""
    nums = _numbers(pg)
    me = project.continuation_key({"graph_id": n["sheet"], "source": {"drawing_number": nums.get(n["sheet"])}}, n)
    my_dn = project._dn(nums.get(n["sheet"]))
    words = [w for w in (q or "").casefold().split() if w]
    out = []
    for c in pg["nodes"]:
        if c.get("kind") != "continuation" or c.get("sheet") in (None, n["sheet"]) or not c.get("local_id"):
            continue
        k = project.continuation_key({"graph_id": c["sheet"], "source": {"drawing_number": nums.get(c["sheet"])}}, c)
        peer = _peer_of(pg, c, by_id)
        row = {"graph_id": c["sheet"], "local_id": c["local_id"], "drawing_number": nums.get(c["sheet"]), "label": _label(c),
               "line_no": k["line_no"], "to_drawing": k["to_drawing"], "linked": peer is not None,
               "peer_drawing": nums.get(peer["sheet"]) if peer else None, "warn": []}
        if project._dn(k["to_drawing"]) != my_dn:
            row["warn"].append("상대 도면이 다름(%s를 가리킴)" % (k["to_drawing"] or "없음"))
        if project._norm(k["line_no"]) != project._norm(me["line_no"]):
            row["warn"].append("배관 번호가 다름(%s ≠ %s)" % (k["line_no"] or "없음", me["line_no"] or "없음"))
        text = " ".join(str(v or "") for v in (row["drawing_number"], row["line_no"], row["label"], row["to_drawing"])).casefold()
        if words and not all(w in text for w in words):
            continue
        row["_key"] = (row["linked"], project._dn(k["to_drawing"]) != my_dn, project._norm(k["line_no"]) != project._norm(me["line_no"]),
                       row["drawing_number"] or "", row["label"] or "")
        out.append(row)
    out.sort(key=lambda r: r["_key"])
    for r in out:
        del r["_key"]
    return out[:CANDIDATE_LIMIT], len(out)


def _stale(pg, ops, drawing_number):
    """이 도면을 가리키는 지정 가운데 project.match가 건너뛴 것(원본이 바뀌어 연결점을 못 찾음 등)."""
    by_op = {o.get("op_id"): o for o in ops}
    dn = project._dn(drawing_number)
    out = []
    for s in pg.get("manual_skipped") or []:
        o = by_op.get(s.get("op_id")) or {}
        if any(project._dn(e.get("drawing_number")) == dn for e in o.get("ends") or []):
            out.append({"op_id": s.get("op_id"), "reason": s.get("reason"), "op": o.get("op"), "by": o.get("by"), "at": o.get("at"),
                        "ends": [{"drawing_number": e.get("drawing_number"), "source_object_id": e.get("source_object_id")} for e in o.get("ends") or []]})
    return out


def _relocated(pg, drawing_number):
    dn = project._dn(drawing_number)
    return [dict(m) for m in pg.get("manual_relocated") or [] if project._dn(m.get("drawing_number")) == dn]


def view(engine, graph_id, local_id, q=None):
    """연결점 카드: {ok, ver, point, candidates, more, stale, relocated}. relocated: 다시 추출로 번호가 밀려 지문으로 옮겨 붙인 지정(이 도면)."""
    try:
        pid, pg = _pg(engine)
        ops, fp = _manual(pid)
        n, by_id = _entity(pg, graph_id, local_id)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except (OSError, ValueError) as exc:
        return {"ok": False, "code": "failed", "message": "도면 연결 지정을 읽지 못했습니다(%s)." % str(exc)[:160]}
    cands, total = _candidates(pg, n, by_id, q)
    point = _point(pg, n, by_id, ops)
    return {"ok": True, "graph_id": graph_id, "ver": _ver(fp, pg), "point": point, "candidates": cands, "more": max(0, total - len(cands)),
            "stale": _stale(pg, ops, point["drawing_number"]), "relocated": _relocated(pg, point["drawing_number"])}


# ---------------------------------------------------------------- 쓰기

def _who(engine, by):
    by = by or engine.reviewer()
    if not by:
        raise Refused("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 지정한 사람으로 남습니다.")
    return by


def _follow_moves(pg, ops):
    """project.match가 지문으로 옮겨 붙인 끝을 기록에도 옮긴다(다음 저장 때 이력 note에 남김). → (새 ops, 옮긴 목록)."""
    moves = {(m["op_id"], project._dn(m["drawing_number"]), m["from"]): m["to"] for m in pg.get("manual_relocated") or []}
    if not moves:
        return ops, []
    out, done = [], []
    for o in ops:
        ends = []
        for e in o.get("ends") or []:
            to = moves.get((o.get("op_id"), project._dn(e.get("drawing_number")), e.get("source_object_id")))
            if to:
                done.append({"op_id": o["op_id"], "drawing_number": e.get("drawing_number"), "from": e.get("source_object_id"), "to": to})
                e = dict(e, source_object_id=to)
            ends.append(e)
        out.append(dict(o, ends=ends))
    return out, done


def _without(ops, keys):
    """keys(연결점)를 건드리는 앞선 지정을 뺀다(project.match는 같은 연결점의 앞 지정만 쓰므로, 남기면 새 지정이 무시된다)."""
    return [o for o in ops if not keys & {_end_key(e) for e in o.get("ends") or []}]


def _impact_text(pg, by_id, touched, breaking):
    """확인 글. touched: 짝이 바뀌는 연결점 노드들, breaking: 풀리는 짝 [(노드, 맞은편 노드)]. 걸리는 것이 없으면 None."""
    nums = _numbers(pg)
    parts = []
    for a, b in breaking:
        parts.append("%s %s ↔ %s %s 짝이 풀립니다" % (nums.get(a["sheet"]), _label(a), nums.get(b["sheet"]), _label(b)))
    owners = _owners(pg)
    held = sorted({nid for x in touched for nid, state in owners.get(x["entity_id"], []) if state != "applied"})
    if held:
        parts.append("확정·잠금 구간 %s에 든 연결점입니다. 바꾸면 그 구간을 재확인해야 합니다" % ", ".join(held))
    return ". ".join(parts) + "." if parts else None


def _save(engine, graph_id, local_id, ver, base, confirm, by, plan, done, dry=False):
    """plan(pg, n, by_id, ops, nums) → (새 ops, 짝이 바뀌는 노드들, 풀리는 짝, log 설명). done(설명) → 알림 글.
    dry=True: 같은 검사를 하고 저장하지 않는다 → {ok, dry, confirm(물을 확인 글 또는 None), notes(저장하면 낼 알림)}(채팅 확인 상자가 미리 보인다)."""
    who = _who(engine, by)
    if not ver or not base:          # 채팅 길도 같다: 먼저 view로 읽고 그 판·지문을 함께 보낸다
        raise Refused("bad_args", "읽은 판(ver)과 연결점 지문(base)을 함께 보내야 합니다. 먼저 연결점을 읽으세요.")
    pid = engine.project_id()
    with sheet_refresh.lock("drawing-links:" + str(pid)):
        pid, pg = _pg(engine)
        ops, fp = _manual(pid)
        if not ver or ver != _ver(fp, pg):
            raise Refused("stale", "화면을 연 뒤 도면 연결이나 도면이 바뀌었습니다. 카드를 다시 열었으니 확인하고 다시 하세요.")
        n, by_id = _entity(pg, graph_id, local_id)
        if base != _point(pg, n, by_id, ops)["base"]:
            raise Refused("stale", "이 연결점의 짝이 그 사이 바뀌었습니다. 카드를 다시 열었으니 확인하고 다시 하세요.")
        nums = _numbers(pg)
        ops, moved = _follow_moves(pg, ops)
        new_ops, touched, breaking, note = plan(pg, n, by_id, ops, nums)
        if moved:
            note = dict(note, relocated=moved)
        text = _impact_text(pg, by_id, touched, breaking)
        if dry:
            return {"ok": True, "dry": True, "confirm": text, "notes": [done(note)]}
        if text and confirm != text:
            raise Refused("needs_confirm", text)
        at = store_io.now_utc()
        try:
            project.save_manual(pid, new_ops, who, at, expect=fp, note=note)
        except store_io.Conflict:
            raise Refused("stale", "다른 곳에서 도면 연결 지정이 바뀌었습니다. 카드를 다시 열었으니 확인하고 다시 하세요.")
    for topic in ("links", "nodes", "drawings"):
        engine.changed(topic, None)
    recheck = sheet_refresh.project_recheck(pid)
    return {"ok": True, "notes": [done(note)], "recheck": recheck}


def _new_op(op, ends, by, reason):
    return {"op_id": "sl-%s" % uuid.uuid4().hex[:12], "op": op, "ends": ends, "by": by, "at": store_io.now_utc(), "reason": (reason or "").strip()[:300]}


def _guard(fn):
    try:
        return fn()
    except Refused as exc:
        out = {"ok": False, "code": exc.code, "message": exc.message}
        if exc.detail is not None:
            out["detail"] = exc.detail
        return out
    except (OSError, ValueError) as exc:
        LOG.exception("도면 연결 지정 실패")
        return {"ok": False, "code": "failed", "message": "도면 연결 지정을 저장하지 못했습니다(%s)." % str(exc)[:160]}


def pair(engine, graph_id, local_id, peer_graph_id, peer_local_id, ver, reason="", base=None, confirm=None, by=None, dry=False):
    """이 연결점과 다른 도면의 연결점 하나를 짝으로 지정한다."""
    def plan(pg, n, by_id, ops, nums):
        if peer_graph_id == graph_id:
            raise Refused("bad_args", "같은 도면의 연결점끼리는 짝을 지정하지 않습니다.")
        try:
            b, _ = _entity(pg, peer_graph_id, peer_local_id)
        except Refused:
            raise Refused("bad_args", "고른 맞은편 연결점을 찾을 수 없습니다(도면이 바뀌었을 수 있음).")
        b = by_id[b["entity_id"]]
        mine, theirs = _peer_of(pg, n, by_id), _peer_of(pg, b, by_id)
        if mine is not None and mine["entity_id"] == b["entity_id"] and (n.get("sheet_link") or {}).get("status") == project.LINKED:
            link = _link_of(pg, n) or {}
            if link.get("origin") == "manual":
                raise Refused("bad_args", "이미 사람이 지정한 짝입니다.")
        ends = [_end(n, nums), _end(b, nums)]
        who = by or engine.reviewer()
        new = _new_op("link", ends, who, reason)
        breaking = [(x, y) for x, y in ((n, mine), (b, theirs)) if y is not None and y["entity_id"] not in (n["entity_id"], b["entity_id"])]
        note = {"op": "link", "ends": ends, "reason": new["reason"], "labels": [_name_of(n, nums), _name_of(b, nums)]}
        return _without(ops, {_end_key(e) for e in ends}) + [new], [n, b], breaking, note

    def done(note):
        return "%s ↔ %s 짝을 지정했습니다." % tuple(note["labels"])
    return _guard(lambda: _save(engine, graph_id, local_id, ver, base, confirm, by, plan, done, dry=dry))


def unlink(engine, graph_id, local_id, ver, reason="", base=None, confirm=None, by=None, dry=False):
    """이 연결점을 '연결하지 않음'으로 지정한다(자동으로 이은 짝도 끊는다). 지금 짝이 있으면 확인을 받는다."""
    def plan(pg, n, by_id, ops, nums):
        if (n.get("sheet_link") or {}).get("status") != project.LINKED:
            link = _link_of(pg, n) or {}
            if link.get("reason") == "manual_unlink":
                raise Refused("bad_args", "이미 끊은 연결점입니다.")
        mine = _peer_of(pg, n, by_id)
        ends = [_end(n, nums)]
        new = _new_op("unlink", ends, by or engine.reviewer(), reason)
        note = {"op": "unlink", "ends": ends, "reason": new["reason"], "labels": [_name_of(n, nums)]}
        keys = {_end_key(e) for e in ends}
        if mine is not None:                 # 사람이 지정한 짝이면 그 지정도 뺀다(맞은편은 자동 판정으로 돌아간다)
            keys.add(_end_key(_end(mine, nums)))
        return _without(ops, keys) + [new], [n] + ([mine] if mine else []), [(n, mine)] if mine else [], note

    def done(note):
        return "%s 연결을 끊었습니다." % note["labels"][0]
    return _guard(lambda: _save(engine, graph_id, local_id, ver, base, confirm, by, plan, done, dry=dry))


def clear(engine, graph_id, local_id, ver, op_id, base=None, confirm=None, by=None, dry=False):
    """지정 하나를 뺀다(그 연결점은 자동 판정으로 돌아간다). 오래된(연결점을 못 찾는) 지정도 이것으로 뺀다."""
    def plan(pg, n, by_id, ops, nums):
        op = next((o for o in ops if o.get("op_id") == op_id), None)
        if op is None:
            raise Refused("not_found", "그 지정이 기록에 없습니다(이미 빠졌을 수 있음).")
        touched = []
        for e in op.get("ends") or []:
            hit = next((x for x in pg["nodes"] if x.get("kind") == "continuation" and x.get("sheet")
                        and _end_key(_end(x, nums)) == _end_key(e)), None)
            if hit is not None:
                touched.append(hit)
        breaking = []
        if op["op"] == "link" and len(touched) == 2 and (_peer_of(pg, touched[0], by_id) or {}).get("entity_id") == touched[1]["entity_id"]:
            breaking = [(touched[0], touched[1])]
        note = {"op": "clear", "op_id": op_id, "ends": op.get("ends") or []}
        return [o for o in ops if o.get("op_id") != op_id], touched, breaking, note

    def done(note):
        return "도면 연결 지정 %s를 뺐습니다. 자동 판정으로 돌아갑니다." % note["op_id"]
    return _guard(lambda: _save(engine, graph_id, local_id, ver, base, confirm, by, plan, done, dry=dry))


# ---------------------------------------------------------------- 읽기·명령 등록(api_corrections가 부른다)

def read(engine, parts, query):
    from hazop.shell import api
    if len(parts) != 3:
        return None
    q = (query or {}).get("q")
    if isinstance(q, list):
        q = q[0] if q else None
    data = view(engine, parts[1], parts[2], q=(q or "")[:80])
    if not data["ok"] and data.get("code") == "not_found":
        return None
    return api._json(data)


def _unwrap(res):
    from hazop.shell import api
    if res.get("ok"):
        return {k: v for k, v in res.items() if k != "ok"}
    err = api.CommandError(res["code"], res["message"])
    if res.get("detail") is not None:
        err.detail = res["detail"]
    raise err


def register(commands):
    from hazop.shell import api
    C, v_str = api.Command, api.v_str
    base = {"graph_id": (v_str(1, 200), True), "local_id": (v_str(1, 200), True), "ver": (v_str(1, 40), True),
            "base": (v_str(0, 64), False), "confirm": (v_str(0, 4000), False)}

    def put(name, spec_, handler, doc):
        key = "links." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("pair", dict(base, peer_graph_id=(v_str(1, 200), True), peer_local_id=(v_str(1, 200), True), reason=(v_str(0, 300), False)),
        lambda engine, a: _unwrap(pair(engine, a["graph_id"], a["local_id"], a["peer_graph_id"], a["peer_local_id"], a["ver"],
                                       a.get("reason") or "", base=a.get("base"), confirm=a.get("confirm"))),
        "도면 연결(오각형) 하나와 다른 도면의 연결점을 짝으로 지정한다(풀리는 짝·확정 구간은 엔진이 물은 확인 글을 confirm으로)")
    put("unlink", dict(base, reason=(v_str(0, 300), False)),
        lambda engine, a: _unwrap(unlink(engine, a["graph_id"], a["local_id"], a["ver"], a.get("reason") or "", base=a.get("base"),
                                         confirm=a.get("confirm"))),
        "도면 연결 하나를 '연결하지 않음'으로 지정한다")
    put("clear", dict(base, op_id=(v_str(1, 40), True)),
        lambda engine, a: _unwrap(clear(engine, a["graph_id"], a["local_id"], a["ver"], a["op_id"], base=a.get("base"),
                                        confirm=a.get("confirm"))),
        "사람이 한 도면 연결 지정 하나를 뺀다(자동 판정으로 돌아감. 오래된 지정도)")
