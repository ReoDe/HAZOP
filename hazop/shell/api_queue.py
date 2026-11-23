"""검토 대기열(규격 HZ-DSN-06 §3.3, 단위 U3). 읽기 토픽 `queue`: `queue/ai`(AI 후보), `queue/lost`(찾지 못한 구성요소).

AI 후보와 찾지 못한 구성요소를 같은 항목 꼴로 한 줄에 세운다. **이 모듈은 명령이 없고 새로 쓰는 것이 없다**(AI 후보 읽기
`api_aireview.candidates`가 원래 하는 상태 맞추기만 그대로 일어난다). 판정은 화면이 지금 있는 명령을 그대로 부른다
(새 저장 길을 만들지 않는다, 총괄 결정 2026-11-23).

| 대기열 | 수락(A) | 거절(R) | 고쳐서 수락(E) | 되돌리기(Z) |
| --- | --- | --- | --- | --- |
| ai | `aireview.accept` | `aireview.reject` | `edit.apply` 뒤 `aireview.reject` | `aireview.revert`(E는 `edit.undo`도) |
| lost | (아직 없음: 고른 후보로 잇는 저장 길은 총괄 승인 뒤) | `nodes.discard_lost` | — | `nodes.undo` |

묶음 수락(Shift+A)은 도면·할 일마다 `aireview.accept_bulk`를 부르고(묶음은 엔진이 다시 센다), 되돌리기는 바뀐 후보를 `aireview.revert`로 돌린다.
그래서 항목마다 그 명령에 실을 판을 함께 낸다: AI 후보는 도면별 `ver`, 찾지 못한 구성요소는 `set_rev`와 구간의 `target`(rev·state).

AI 후보 대기열은 도면별이다(사용자 결정 2026-11-23): `queue/ai?graph_id=…`이면 그 도면의 후보만 담는다(없으면 모든 도면).

꼴: {"kind", "ver", "total", "items": [...], "bulk": [{graph_id, task, count}], "threshold"}
- 항목 `label`은 도면에서 보이는 이름(태그, 없으면 종류)이다. 묘비 id·로컬 id는 화면 글자로 쓰지 않는다(`local_id`는 도면 확대에만 쓴다).
- `state`는 늘 "open"이다. 판정한 것은 다음 읽기에서 빠진다. 수락·거절·건너뜀은 화면이 대기열을 연 동안 들고 있다.
"""

import hashlib
import logging

from hazop.extract import ai_review

LOG = logging.getLogger(__name__)

TOPICS = ("queue",)
KINDS = ("ai", "lost")
EDIT_OPS = {"tag": "set_tag", "normal_position": "set_normal_position", "fail_position": "set_fail_position"}   # E로 고칠 수 있는 필드
CONNECT_TASKS = ("connection",)


def _api():
    from hazop.shell import api
    return api


def _ver(parts):
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- AI 후보
def _kind_text(kind):
    from hazop.shell.sheet_items import kind_label
    return kind_label(kind) or ("목록에 없는 종류" if kind else "")


def _value_text(field, value):
    if field in ("kind", "split"):
        return _kind_text(value)
    return value or ""


def _ai_items(engine, graph_id=None):
    from hazop.extract import corrections
    from hazop.shell import api_aireview
    items, bulk, vers, inputs = [], [], [], {}
    for row in api_aireview.overview(engine)["drawings"]:
        if not row.get("proposed") or (graph_id and row["graph_id"] != graph_id):
            continue
        gid = row["graph_id"]
        view = api_aireview.candidates(engine, gid)
        if not view.get("ok") or not view.get("available"):
            continue
        vers.append("%s=%s" % (gid, view["ver"]))
        name = engine.graph_names().get(gid)
        try:
            original = api_aireview._original(name)
            resolved = corrections.resolve(name, original)
            corrected = resolved["corrected"]
            shown = {x["local_id"]: x for x in api_aireview.by_sid(corrected).values() if x.get("local_id")}
            pend = _inputs_of(name, original, resolved)
            if pend:
                inputs[gid] = pend
        except (OSError, ValueError, TypeError, KeyError):
            shown, corrected = {}, {}
        for g in view["groups"]:
            for c in g["items"]:
                if c["status"] != "proposed":
                    continue
                local = c.get("local_id")                         # 후보 줄(api_aireview._row)이 지금 고친 결과에서 기호 번호로 다시 찾은 자리(검토 차단 1)
                node = shown.get(local) or {}
                label = node.get("tag") or _kind_text(node.get("kind")) or "이름 없는 기호"
                items.append({"qid": "ai|%s|%s" % (gid, c["cand_id"]), "kind": "ai", "graph_id": gid, "sheet": view["drawing_number"],
                              "ver": view["ver"], "cand_id": c["cand_id"], "local_id": local, "label": label,
                              "item_fp": _item_fp(node, corrected) if local else None,
                              "task": g["label"], "field": c["field"], "field_label": c["field_label"],
                              "now": _value_text(c["field"], c["current"]) or "(비어 있음)",
                              "proposal": _value_text(c["field"], (c["values"] or [""])[0]),
                              "confidence": c["confidence"], "why": c["reason"], "match_label": c.get("match_label"),
                              "bulk": bool(c["bulk_ok"]) and c["task"] not in CONNECT_TASKS, "bulk_block": c.get("bulk_block"),
                              "edit_op": EDIT_OPS.get(c["field"]), "state": "open"})
        for b in view.get("bulk") or []:
            if b["task"] not in CONNECT_TASKS:
                bulk.append({"graph_id": gid, "sheet": view["drawing_number"], "task": b["task"], "label": b["label"], "count": b["count"],
                             "ver": view["ver"]})
    return items, bulk, vers, inputs


def _item_fp(node, corrected):
    """고쳐서 수락(E)이 보낼 대상 지문(api_corrections.item_fp): 그새 그 자리의 기호가 바뀌었으면 엔진이 거절한다."""
    from hazop.shell import api_corrections
    kind = "node" if node in (corrected.get("nodes") or []) else "relation"
    return api_corrections.item_fp(kind, node, corrected)


def _inputs_of(name, original, resolved):
    """반영 전 수락(입력 연산 U2 §11.3 6): {"waiting": 기다리는 수, "lines": [{state, code, text}](사람 말), "boxes": [{op_id, rect, kind_label}]}.
    rect는 도면 그림 좌표 [x0, y0, x1, y1](sheet_items와 같은 원점). 입력 연산이 없으면 None."""
    from hazop.extract import corrections
    from hazop.shell import sheet_items
    st = resolved["inputs"]
    if st["state"] == "none" and not st.get("not_applicable"):
        return None
    lines = [{"state": x["state"], "code": x["code"], "text": x["text"], "candidate": x.get("candidate")} for x in corrections.input_items(resolved)]
    ox, oy = sheet_items._offset(original)
    boxes = []
    for b in corrections.pending_inputs(name, original, resolved["ops"]):
        x, y, w, h = b["bbox"]
        boxes.append({"op_id": b["op_id"], "rect": [x - ox, y - oy, x + w - ox, y + h - oy], "kind_label": _kind_text(b.get("kind")) or "기호"})
    if not lines and not boxes:
        return None
    return {"waiting": len(st.get("waiting") or []), "lines": lines, "boxes": boxes}


# ---------------------------------------------------------------- 찾지 못한 구성요소
def _lost_items(engine):
    from hazop.shell import api_nodes
    from hazop.study import idmap, nodes
    pg = api_nodes._pg(engine, strict=False)
    if pg is None:
        return [], None, []
    ns, legacy = api_nodes._peek(pg)
    if legacy:
        return [], None, []
    from hazop.shell import api_drawings
    names = engine.graph_names()
    lb = api_drawings.labels(engine)
    tombs = ns.get("tombstones") or {}
    set_rev = ns.get("set_rev") or 0
    items = []
    for node in ns.get("nodes") or []:
        lost = node.get("lost") or []
        if not lost:
            continue
        nid = node["node_id"]
        target = {"node_id": nid, "rev": node.get("rev") or 1, "state": nodes.node_state(node)}
        for t in lost:
            rec = tombs.get(t) if isinstance(tombs.get(t), dict) else {}
            mk = rec.get("mark")
            gid = mk[1] if idmap.valid_mark(mk) and mk[1] in names else idmap.drawing_of(rec.get("ref"))
            key = idmap.tomb_handle(t)
            items.append({"qid": "lost|%s|%s" % (nid, key), "kind": "lost", "node_id": nid, "node_name": node.get("name") or nid,
                          "key": key, "label": api_nodes.lost_name(idmap.tomb_name(rec), rec.get("ref"), lambda g: api_drawings.display(engine, g, lb)),
                          "graph_id": gid if gid in names else None, "sheet": api_drawings.display(engine, gid, lb) if gid in names else None, "where": [{"node": nid}],
                          "target": target, "held": target["state"] != "applied", "cands": [], "state": "open"})
    return items, set_rev, ["rev=%s" % set_rev]


# ---------------------------------------------------------------- 읽기
def summary(engine, kind, graph_id=None):
    if kind == "ai":
        items, bulk, vers, inputs = _ai_items(engine, graph_id)
        out = {"kind": "ai", "graph_id": graph_id, "items": items, "bulk": bulk, "threshold": ai_review.DEFAULT_THRESHOLD, "inputs": inputs}
        vers += ["%s:%s" % (g, v["waiting"]) for g, v in sorted(inputs.items())]
    else:
        items, set_rev, vers = _lost_items(engine)
        out = {"kind": "lost", "items": items, "bulk": [], "set_rev": set_rev, "project_id": engine.project_id()}
    out["total"] = len(items)
    out["ver"] = _ver([kind] + vers + [i["qid"] for i in items])
    return out


def read(engine, parts, query):
    if len(parts) == 2 and parts[0] == "queue" and parts[1] in KINDS:
        return _api()._json(summary(engine, parts[1], (query or {}).get("graph_id") or None))
    return None
