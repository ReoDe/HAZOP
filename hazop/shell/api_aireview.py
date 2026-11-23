"""새 웹 화면의 AI 검토 후보 영역(INTENT.md §3.2, 완료 목록 2 A4). Qt를 import하지 않는다.

- **읽기** `aireview`(도면별 후보 수·마지막 실행), `aireview/<도면 ID>`(한 도면의 후보: 할 일별 묶음, 묶어 수락할 수 있는 묶음, 지금 값),
  `aireview/estimate?cap=N`(도면별 예상 호출 수, `ai_review.estimate_pages`). 읽기는 파일을 쓰지 않는다.
- **명령** `aireview.accept`·`aireview.reject`·`aireview.revert`(낱개), `aireview.accept_bulk`(확신 높은 묶음), `aireview.run`(고른 도면에
  AI 검토 실행). 쓰기는 읽은 판(`ver` = 후보 파일과 사람 수정 기록의 지문)을 대조해 어긋나면 stale로 거절한다. 결정한 사람은 설정의 검토자 이름이다.
- **수락·되돌리기 뒤 그래프를 바로 다시 만든다**(공용 길 hazop/shell/sheet_refresh.py, 도면 고치기와 함께 쓴다). 수락은 사람 수정 기록(hazop.extract.corrections)에 연산으로 들어가므로, 이전 화면처럼 '다시 열면
  반영'이 아니라 그 도면의 그래프(scripts/build_graph.build_one이 기록을 적용)와 프로젝트 지식그래프를 이 자리에서 다시 만든다(hazop.app.data와 같은 길).
- 채팅(d-chat)이 부를 실행 함수: `candidates`, `bulk_ids`(묶음 수락이 고를 ID, 읽기만), `accept`, `accept_bulk`, `reject`, `revert`. 모두 {"ok", ...} 사전을 돌려주고 예외를 올리지 않는다.
  웹 명령은 이 함수들을 감싼 것이다. 웹과 채팅 모두 경로를 주고받지 않고 도면 ID·후보 ID만 쓴다.
"""

import logging

from hazop import store_io
from hazop.extract import ai_review, corrections
from hazop.shell import ai_image_flow
from hazop.shell.sheet_refresh import ensure_graph, lock, refresh, ver_of  # noqa: F401  (ver_of는 채팅·시험도 이 이름으로 부른다)

LOG = logging.getLogger("hazop.shell.api_aireview")
TOPICS = ("aireview",)
PROJECT_PREFIXES = ("aireview.",)
MAX_IDS = 500
FIELD_LABELS = {"kind": "종류", "tag": "태그", "normal_position": "정상 위치", "fail_position": "고장 위치", "connection": "연결",
                "to_system": "연결 계통"}
STATUS_LABELS = {"proposed": "제안", "accepted": "수락", "rejected": "거절"}


def _api():
    from hazop.shell import api
    return api


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ---------------------------------------------------------------- 읽기

def _name(engine, graph_id):
    name = engine.graph_names().get(graph_id)
    if not name:
        raise Refused("not_found", "없는 도면")
    return name


def _original(name):
    from hazop.app import data
    return data.read_json(data.extraction_path(name))


def _current(shown, c):
    if c["field"] == "connection":
        return "끊긴 연결"
    node = shown.get(c["target"])
    if node is None:
        return ""
    if c["field"] in ("kind", "tag"):
        return node.get(c["field"]) or ""
    return (node.get("attributes") or {}).get(c["field"]) or ""


# 그림 입력 AI의 종류 후보에 붙는 match(legend=범례 견본과 모양이 같다고 본 것). 없는 후보(스크립트·글 입력·옛 저장본)는 칩 없이 둔다.
MATCH_LABELS = {"legend": ("높음", "범례 견본과 맞는 후보"), "other": ("보통", "범례에 없는 꼴이라 확인이 필요한 후보")}


def _show(field, value):
    """화면에 쓰는 값: 종류는 한글 종류 이름(영문 내부 이름은 보이지 않는다, 실제 창 확인 2026-11-23). 사전에 없는 종류는 '목록에 없는 종류'."""
    if field in ("kind", "split") and value:
        from hazop.shell.sheet_items import kind_label
        return kind_label(value) or "목록에 없는 종류"
    return value


def by_sid(corrected):
    """{source_object_id: 항목}(기기·연결·열린 끝). 후보의 자리는 저장된 local_id가 아니라 이것으로 다시 찾는다."""
    out = {}
    for key in ("unresolved_connectors", "relations", "nodes"):
        out.update((x["source_object_id"], x) for x in corrected.get(key) or [] if x.get("source_object_id"))
    return out


def local_of(c, shown):
    """후보가 가리키는 기호의 지금 자리 번호. 기준 추출을 다시 지으면 local-node 번호가 밀리므로 저장된 c["local_id"]를 쓰지 않고
    지금 고친 결과에서 그 기호(c["target"], source_object_id)로 찾는다. 지금 없는 기호면 None(엉뚱한 기호에 붙지 않게, 검토 차단 1)."""
    hit = shown.get(c.get("target"))
    return hit.get("local_id") if hit else None


def _row(c, shown):
    block = ai_review.bulk_block(c)
    match = MATCH_LABELS.get(c.get("match")) if isinstance(c.get("match"), str) else None
    return {"cand_id": c["cand_id"], "task": c["task"], "field": c["field"], "field_label": FIELD_LABELS.get(c["field"], c["field"]),
            "current": _current(shown, c), "values": list(c["values"])[:3], "confidence": round(float(c["confidence"]), 2),
            "reason": (c.get("reason") or "")[:300], "status": c["status"], "status_label": STATUS_LABELS.get(c["status"], c["status"]),
            "local_id": local_of(c, shown), "bulk_ok": block is None, "bulk_block": block if c["status"] == "proposed" else None,
            "decided_by": c.get("decided_by"), "script_value": c.get("script_value"), "match": c.get("match") if match else None,
            "match_label": match[0] if match else None, "match_hint": match[1] if match else None,
            "current_text": _show(c["field"], _current(shown, c)), "values_text": [_show(c["field"], v) for v in list(c["values"])[:3]],
            "script_text": _show(c["field"], c.get("script_value"))}


def _load(name):
    """(후보 문서 또는 None, 원본 추출). 옛 종류 후보에는 near_symbol을 채운다(메모리에서만)."""
    original = _original(name)
    doc = ai_review.load_doc(name)
    if doc is not None:
        ai_review.annotate(doc, original)
    return doc, original


def _reconcile(name):
    """후보 상태를 사람 수정 기록에 맞춘다(ai_review.reconcile, A5 검토 R2의 안전망). 그새 바뀌어 겹치면 다음 읽기에서 맞춘다."""
    try:
        return ai_review.reconcile(name)
    except store_io.Conflict:
        return []


def candidates(engine, graph_id):
    """한 도면의 후보(채팅·웹 공용). → {ok, available, graph_id, drawing_number, ver, counts, groups, bulk, last_run} 또는 {ok: False, code, message}.
    도면별 잠금(sheet_refresh.lock) 안에서 맞추기·다시 만들기·읽기를 해, 보이는 목록과 판(ver)이 같은 때의 것이다."""
    try:
        name = _name(engine, graph_id)
        with lock(name):
            if _reconcile(name):
                engine.changed("sheetconf", None)
            stale, stale_notes, _recheck = ensure_graph(name)
            doc, original = _load(name)
            ver = ver_of(name)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except (OSError, ValueError) as exc:
        return {"ok": False, "code": "failed", "message": "AI 후보를 읽을 수 없습니다(%s)." % str(exc)[:120]}
    from hazop.shell import api_drawings
    base = {"ok": True, "graph_id": graph_id, "drawing_number": api_drawings.display(engine, graph_id),      # 사람용 도면 이름(임시 이름·폴더 이름이 아님)
            "ver": ver, "graph_stale": stale, "graph_notes": stale_notes}
    if doc is None:
        return dict(base, available=False, reason="이 도면에는 AI 후보가 없습니다. AI 검토를 실행하면 생깁니다.", counts={}, groups=[], bulk=[],
                    last_run=None)
    shown = by_sid(corrections.resolve(name, original)["corrected"])      # 기준 추출 위 고친 값(입력 연산 U2), 기호 번호로 찾음
    order = {f: i for i, f in enumerate(FIELD_LABELS)}
    rows = sorted(doc["candidates"], key=lambda c: (c["status"] != "proposed", order.get(c["field"], 99), -c["confidence"], c["cand_id"]))
    groups = []
    for task in ai_review.TASK_ORDER:
        items = [_row(c, shown) for c in rows if c["task"] == task]
        if items:
            groups.append({"task": task, "label": ai_review.TASK_LABELS[task], "items": items,
                           "proposed": sum(1 for x in items if x["status"] == "proposed")})
    bulk = [{"task": t, "label": ai_review.TASK_LABELS[t], "count": len(ids)} for t, ids in ai_review.bulk_groups(doc, by="task").items()]
    counts = {s: sum(1 for c in doc["candidates"] if c["status"] == s) for s in STATUS_LABELS}
    runs = doc.get("runs") or []
    last = runs[-1] if runs else {}
    return dict(base, available=True, counts=counts, groups=groups, bulk=bulk, threshold=ai_review.DEFAULT_THRESHOLD,
                last_run=dict({k: last.get(k) for k in ("at", "calls", "left", "needed_calls", "halted", "stopped", "not_symbol")},
                              legend=_legend_text(last.get("images"))) if last else None)


def _legend_text(info):
    """실행 결과 줄에 작게 보일 글(범례판 출처, 또는 그림을 만들지 못해 글만 보낸 것). 그림 입력이 아니었으면 None."""
    if not isinstance(info, dict):
        return None
    if info.get("failed"):
        return ai_image_flow.FAILED_TEXT
    value = info.get("legend_source")
    if not isinstance(value, str) or not value:
        return None
    return "범례판: " + ai_image_flow.LEGEND_LABELS.get(value, ai_image_flow.UNKNOWN_LEGEND)


# ---------------------------------------------------------------- 도면별 AI 검토 상태(HZ-DSN-06 §3.7)
# 시작한 도면은 aireview.run 작업 안에서 '기다림 → 묻는 중'을 적어 둔다(엔진에만, 파일은 쓰지 않는다). 끝나면 지우고, 오류로 끝나면 failed에 남긴다.
import threading  # noqa: E402

_LIVE_LOCK = threading.Lock()


def _live(engine):
    d = getattr(engine, "_review_live", None)
    if d is None:
        d = engine._review_live = {"seq": 0, "names": {}, "failed": {}, "cancel": set()}
    return d


def _mark_waiting(engine, names):
    with _LIVE_LOCK:
        live = _live(engine)
        live["seq"] += 1
        token = live["seq"]
        for n in names:
            live["names"][n] = {"state": "waiting", "seq": token, "done": None, "total": None}
            live["failed"].pop(n, None)
            live["cancel"].discard(n)
    return token


def _mark_running(engine, token, name, done, total):
    with _LIVE_LOCK:
        names = _live(engine)["names"]
        for n, v in names.items():
            if v["seq"] == token and v["state"] == "running" and n != name:
                v["state"] = "finished"             # 같은 실행에서 앞 도면은 끝났다(자리에서 빼기 전까지 다시 세지 않음)
        if name in names and names[name]["seq"] == token:
            was = names[name]["state"]
            names[name].update(state="running", done=done, total=total)
            return was != "running"
        return False


def _mark_ended(engine, token, names, error=None):
    with _LIVE_LOCK:
        live = _live(engine)
        for n in names:
            if live["names"].get(n, {}).get("seq") == token:
                del live["names"][n]
                live["cancel"].discard(n)
            if error:
                live["failed"][n] = error


def request_stop(engine, graph_id):
    """도면 하나의 AI 검토를 멈추거나(묻는 중) 취소한다(기다리는 중). 다른 도면·다른 작업(등록·분석)은 멈추지 않는다.
    묻는 중이면 지금 호출 하나를 마친 뒤 멈추고(그때까지 받은 후보는 저장, 남은 곳은 '일부만 함'), 기다리는 중이면 차례를 잡기 전에 빠진다.
    → {"graph_id", "was": waiting|running} 또는 None(그 도면은 돌거나 기다리지 않음)."""
    name = engine.graph_names().get(graph_id)
    with _LIVE_LOCK:
        live = _live(engine)
        entry = live["names"].get(name) if name else None
        if not entry or entry["state"] not in ("waiting", "running"):
            return None
        live["cancel"].add(name)
        was = entry["state"]
    engine.changed("aireview", None)
    return {"graph_id": graph_id, "was": was}


def _stopper(engine, token):
    """이 실행이 멈춰야 하는가: 엔진 전체 멈춤, 또는 지금 묻는 도면(차례 전이면 이 실행의 모든 도면)이 멈춤·취소를 받음.
    지금 묻는 도면은 run_pages가 도면을 시작할 때(on_page) 적는다. 한 도면의 멈춤은 그 도면만 그만두고 다음 도면으로 간다(검토 지적 1)."""
    def should_stop():
        if engine.stop_requested():
            return True
        with _LIVE_LOCK:
            live = _live(engine)
            mine = [(n, v) for n, v in live["names"].items() if v["seq"] == token and v["state"] in ("waiting", "running")]
            running = [n for n, v in mine if v["state"] == "running"]
            if running:
                return running[0] in live["cancel"]
            return bool(mine) and all(n in live["cancel"] for n, _v in mine)
    return should_stop


def _skipper(engine, token):
    """취소·멈춤을 받은 도면은 묻지 않고 넘어간다(한 번도 묻지 않음)."""
    def skip(name):
        with _LIVE_LOCK:
            return name in _live(engine)["cancel"]
    return skip


def _after_extract(name, runs):
    """마지막 검토 기록이 지금 추출본보다 앞인가(다시 추출하면 검토 기록이 새 판과 맞지 않는다)."""
    import datetime
    import os
    from hazop.app import data
    try:
        at = datetime.datetime.fromisoformat(str(runs[-1].get("at")).replace("Z", "+00:00")).timestamp()
        return os.path.getmtime(data.extraction_path(name)) <= at + 1
    except (OSError, ValueError, TypeError, AttributeError):
        return True


def _left(engine, name):
    """지금 물을 곳 수와 예상 호출 수(도면당 상한 기준). 못 읽으면 (None, None)."""
    try:
        cap = int(engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP)
        est, _mode = ai_image_flow.estimate_pages([(name, _original(name))], cap, ai_review.RUN_CAP, ai_image_flow.enabled(engine))
        return sum(p["items"] for p in est["pages"]), est["calls"]
    except (OSError, ValueError, TypeError, KeyError):
        return None, None


def _review_state(engine, name, doc, proposed):
    with _LIVE_LOCK:
        live = _live(engine)
        mine = dict(live["names"].get(name) or {})
        others = [dict(v) for n, v in live["names"].items() if n != name and v["state"] in ("waiting", "running")]
        failed = live["failed"].get(name)
    out = {"review": None, "calls": None, "left": None, "ahead": None, "progress": None, "stoppable": False}
    if mine.get("state") == "running":
        return dict(out, review="running", progress={"done": mine.get("done") or 0, "total": mine.get("total")}, stoppable=True)
    if mine.get("state") == "waiting" or (not mine and name in getattr(engine, "_reviewing", ())):
        # 앞 도면: 먼저 시작한 실행의 도면, 같은 실행에서 지금 묻는 도면
        ahead = sum(1 for v in others if v["seq"] < mine["seq"] or (v["seq"] == mine["seq"] and v["state"] == "running")) if mine else None
        return dict(out, review="waiting", ahead=ahead, stoppable=bool(mine))      # 추출 뒤 자동 검토가 잡은 도면은 aireview.stop이 닿지 않는다(검토 지적 2)
    if proposed:
        last = ((doc or {}).get("runs") or [{}])[-1]
        return dict(out, review="candidates", calls=last.get("calls"), left=last.get("left"))
    if failed:
        return dict(out, review="failed")
    runs = (doc or {}).get("runs") or []
    if runs and _after_extract(name, runs):
        left = int(runs[-1].get("left") or 0)
        return dict(out, review="partial" if left > 0 else "done", calls=runs[-1].get("calls"), left=left)
    items, calls = _left(engine, name)
    return dict(out, review="not_run" if (calls or 0) > 0 else "nothing", calls=calls, left=items)


def overview(engine):
    """도면별 후보 수와 AI 검토 상태(목록, HZ-DSN-06 §3.7). 후보 파일이 없는 도면도 0으로 넣는다.
    review: not_run·nothing·waiting·running·candidates·partial·failed·done. ahead는 waiting일 때 앞 도면 수, progress는 running일 때 {done, total}."""
    from hazop.shell import api_drawings
    lb = api_drawings.labels(engine)
    rows = []
    for gid, name in sorted(engine.graph_names().items(), key=lambda kv: (api_drawings.display(engine, kv[0], lb), kv[0])):
        try:
            doc = ai_review.load_doc(name)
        except (OSError, ValueError):
            doc = None
        cands = (doc or {}).get("candidates") or []
        row = {"graph_id": gid, "drawing_number": api_drawings.display(engine, gid, lb),
               "proposed": sum(1 for c in cands if c["status"] == "proposed"), "total": len(cands),
               "accepted": sum(1 for c in cands if c["status"] == "accepted"), "ran": bool((doc or {}).get("runs"))}
        row.update(_review_state(engine, name, doc, row["proposed"]))
        rows.append(row)
    return {"drawings": rows, "cap": int(engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP), "run_cap": ai_review.RUN_CAP,
            "seconds_per_call": ai_review.SECONDS_PER_CALL, "images": ai_image_flow.enabled(engine)}


def estimate(engine, cap, graph_ids=None):
    """도면별 예상 호출 수(사람이 고친 자리를 뺀 미확인 항목으로 센다). graph_ids가 없으면 프로젝트의 모든 도면."""
    names = engine.graph_names()
    pick = [g for g in (graph_ids or sorted(names, key=lambda g: names[g])) if g in names]
    pages = []
    for gid in pick:
        try:
            pages.append((names[gid], _original(names[gid])))
        except (OSError, ValueError):
            continue
    on = ai_image_flow.enabled(engine)
    est, mode = ai_image_flow.estimate_pages(pages, cap, ai_review.RUN_CAP, on)
    reasons = {n: ai_image_flow.text_reason(ex) for n, ex in pages}
    to_gid = {names[g]: g for g in pick}
    from hazop.shell import api_settings
    return {"cap": cap, "run_cap": ai_review.RUN_CAP, "calls": est["calls"], "seconds": est["seconds"], "capped": est["capped"],
            "conn": api_settings.run_conn(engine, "ai_review", calls=est["calls"]),
            "images": {"on": on, "pages": sum(1 for v in mode.values() if v)},
            "pages": [{"graph_id": to_gid.get(p["name"]), "items": p["items"], "calls": p["calls"], "needed": p["needed"],
                       "image": bool(mode.get(p["name"])), "text_reason": reasons.get(p["name"])} for p in est["pages"]]}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'aireview'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(overview(engine))
    if len(parts) == 2 and parts[1] == "estimate":
        try:
            cap = max(1, min(200, int(query.get("cap") or engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP)))
        except ValueError:
            cap = ai_review.DEFAULT_CAP
        gid = query.get("graph_id") or None            # 도면 하나의 확인 창(§3.7): 실행 상한을 다른 도면과 나누지 않고 센다
        return api._json(estimate(engine, cap, [gid] if gid else None))
    if len(parts) == 3 and parts[2] == "revert":            # 되돌리기 미리 알림: aireview/<도면>/revert?ids=a,b
        ids = [i for i in str(query.get("ids") or "").split(",") if i][:MAX_IDS]
        try:
            return api._json(revert_preview(engine, parts[1], ids))
        except Refused:
            return None
    if len(parts) == 2:
        data = candidates(engine, parts[1])
        if not data["ok"] and data["code"] == "not_found":
            return None
        return api._json(data)
    return None


# ---------------------------------------------------------------- 쓰기

STALE_TEXT = "AI 후보나 도면 수정이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요."


NEEDS_CONFIRM_TEXT = "이 수락에 기대 사람이 한 고침 %d건이 함께 빠집니다. 무엇이 빠지는지 확인한 뒤 다시 되돌리세요."


def _op_words(dependents):
    """함께 빠지는 고침 → 사람 말 '태그 고침 2건 · 종류 고침 1건'(연산 이름·op_id를 싣지 않는다)."""
    from hazop.shell import api_corrections
    labels = dict(api_corrections.OP_LABELS, split="나누기", pipe="배관 지정")
    count = {}
    for d in dependents:
        w = labels.get(d.get("op"), "도면")
        count[w] = count.get(w, 0) + 1
    return " · ".join("%s 고침 %d건" % (w, n) for w, n in count.items())


def revert_preview(engine, graph_id, cand_ids):
    """되돌리기 전에 화면이 알릴 값(입력 연산 U2 §11.6). 파일을 쓰지 않는다.
    → {"confirm": [확인받을 사람 고침 op_id], "human": 수, "ai": 함께 제안으로 돌아갈 AI 수락 수, "text": 사람 말}."""
    name = _name(engine, graph_id)
    doc, _original = _load(name)
    if doc is None:
        return {"confirm": [], "human": 0, "ai": 0, "text": ""}
    pv = ai_review.revert_preview(doc, list(cand_ids), name)
    deps = pv.get("dependents") or []
    human = [d for d in deps if not d.get("candidate")]
    ai = [d for d in deps if d.get("candidate")]
    parts = []
    if human:
        parts.append("이 수락에 기대 사람이 한 고침 %d건(%s)이 함께 빠집니다." % (len(human), _op_words(human)))
    if ai:
        parts.append("이 수락에 기댄 다른 AI 후보 수락 %d건도 제안으로 돌아갑니다." % len(ai))
    return {"confirm": [d["op_id"] for d in human], "human": len(human), "ai": len(ai), "text": " ".join(parts)}


def _decide(engine, graph_id, cand_ids, action, ver, by=None, confirm=None):
    """도면별 잠금 안에서 _decide_locked를 부른다(같은 판을 본 두 결정·사람 고침이 서로를 덮지 않게, sheet_refresh.lock)."""
    try:
        name = _name(engine, graph_id)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    with lock(name):
        return _decide_locked(engine, graph_id, cand_ids, action, ver, by, confirm)


def _decide_locked(engine, graph_id, cand_ids, action, ver, by=None, confirm=None):
    """낱개 결정의 공통 길. ver(읽은 판)는 꼭 있어야 한다(채팅도 같다, 검토 5).
    → {ok, changed, failed, ver, notes, recheck, graph_stale} 또는 {ok: False, code, message}.
    저장한 뒤의 실패(그래프 다시 만들기)는 오류가 아니라 '저장됨, 그래프 갱신 실패'로 돌려주고 낡은 그래프 표시를 남긴다(검토 3·4)."""
    stale_before, notes, recheck = False, [], []
    try:
        name = _name(engine, graph_id)
        stale_before, notes, recheck = ensure_graph(name)          # 앞에서 실패한 다시 만들기를 이번 동작에서 다시 해 본다
        by = by or engine.reviewer()
        if not by:
            raise Refused("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 수락·거절한 사람으로 남습니다.")
        if not ver or ver != ver_of(name):
            raise Refused("stale", STALE_TEXT if ver else "화면에서 본 후보 목록을 함께 보내지 않아 저장하지 않았습니다. 후보 목록을 다시 열어 주세요.")
        doc, original = _load(name)
        if doc is None:
            raise Refused("not_found", "이 도면에는 AI 후보가 없습니다.")
        have = {c["cand_id"]: c for c in doc["candidates"]}
        ids = [i for i in dict.fromkeys(cand_ids) if i in have]
        missing = [i for i in cand_ids if i not in have]
        if not ids:
            raise Refused("not_found", "없는 후보입니다.")
        before = {i: have[i]["status"] for i in ids}
        failed = [{"cand_id": i, "reason": "없는 후보"} for i in missing]
        if action == "accept":
            failed += [{"cand_id": c, "reason": r} for c, r in ai_review.accept(doc, ids, original, name, by=by)]
        elif action == "reject":
            ai_review.reject(doc, ids, by=by)
        else:
            ai_review.revert(doc, ids, name, by=by, confirm=confirm)
    except ai_review.RevertNeedsConfirm as exc:                  # 기댄 사람 고침을 확인받지 않음: 아무것도 지우지 않았다
        return {"ok": False, "code": "needs_confirm", "message": NEEDS_CONFIRM_TEXT % len(exc.dependents)}
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except store_io.Conflict:
        return {"ok": False, "code": "stale", "message": STALE_TEXT}
    except (OSError, ValueError) as exc:
        LOG.exception("AI 후보 %s 실패", action)
        return {"ok": False, "code": "failed", "message": "저장하지 못했습니다(%s)." % str(exc)[:160]}
    # 여기부터는 저장이 끝났다. 어떤 예외도 '저장 안 됨'으로 알리지 않는다
    after = {c["cand_id"]: c["status"] for c in doc["candidates"]}
    changed = [i for i in ids if after.get(i) != before[i]]
    stale = stale_before
    if changed and action in ("accept", "revert"):
        # 그래프·지식그래프 다시 만들기(나누기는 기준 추출 짓기까지)는 짓기 작업으로 미룬다: 수락이 이어지는 동안 잠금을 오래 쥐지 않게
        # 마지막 수락 뒤 조용해지거나 대기열을 닫으면 도면마다 한 번 돈다(api_inputs, 입력 연산 U2 §11.3·§11.5). 도면 그림은 수정 기록을 바로 보인다
        from hazop.shell import api_inputs
        api_inputs.note(engine, name)
    if changed or stale_before != stale:
        engine.changed("aireview", None)
        engine.changed("drawings", None)
        engine.changed("sheetconf", None)                         # 쪽 확정 카드의 AI 후보 수(검토 6)
        if action in ("accept", "revert") or stale_before != stale:
            engine.changed("sheet", graph_id)
            engine.changed("inputs", None)
    return {"ok": True, "graph_id": graph_id, "changed": changed, "failed": failed, "ver": ver_of(name), "notes": notes,
            "recheck": recheck, "graph_stale": stale}


def accept(engine, graph_id, cand_ids, ver, by=None):
    return _decide(engine, graph_id, cand_ids, "accept", ver, by)


def reject(engine, graph_id, cand_ids, ver, by=None):
    return _decide(engine, graph_id, cand_ids, "reject", ver, by)


def revert(engine, graph_id, cand_ids, ver, by=None, confirm=None):
    """confirm: 미리 알림(revert_preview)의 confirm 목록. 기댄 사람 고침이 있는데 빠졌으면 needs_confirm으로 거절하고 아무것도 지우지 않는다."""
    return _decide(engine, graph_id, cand_ids, "revert", ver, by, confirm)


def _bulk(doc, task):
    return list(ai_review.bulk_groups(doc, by="task").get(task) or []) if doc else []


def bulk_ids(engine, graph_id, task):
    """묶음 수락이 고를 후보 ID(accept_bulk와 같은 규칙, 파일을 쓰지 않음). 채팅 확인 상자에 보일 목록. 없는 도면·후보면 []."""
    try:
        doc, _original_ex = _load(_name(engine, graph_id))
    except (Refused, OSError, ValueError):
        return []
    return _bulk(doc, task)


def accept_bulk(engine, graph_id, task, ver, by=None):
    """확신 높은 묶음(ai_review.bulk_groups, 할 일별)을 한 번에 수락한다. 묶음은 엔진이 다시 세므로 웹이 고른 ID를 믿지 않는다."""
    try:
        name = _name(engine, graph_id)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    with lock(name):                                     # 묶음을 센 판과 수락하는 판이 같게(잠금은 다시 잡아도 되는 RLock)
        try:
            doc, _original_ex = _load(name)
        except (OSError, ValueError) as exc:
            return {"ok": False, "code": "failed", "message": "AI 후보를 읽을 수 없습니다(%s)." % str(exc)[:120]}
        if not ver or ver != ver_of(name):
            return {"ok": False, "code": "stale", "message": STALE_TEXT if ver else "화면에서 본 후보 목록을 함께 보내지 않아 저장하지 않았습니다. 후보 목록을 다시 열어 주세요."}
        ids = _bulk(doc, task)
        if not ids:
            return {"ok": False, "code": "not_found", "message": "묶어 수락할 후보가 없습니다."}
        return _decide_locked(engine, graph_id, ids, "accept", ver, by)


def run_review(engine, graph_ids, cap, progress, token=None):
    """고른 도면에 AI 검토를 돌린다(작업 스레드). 도면당 cap, 한 번 실행은 RUN_CAP까지. 사람이 고친 자리는 묻지 않는다.
    → {"drawings": [{graph_id, candidates, calls, left, halted}], "calls", "capped"}."""
    from hazop.shell import api_settings
    ai = engine.ai
    plan = api_settings.run_conn(engine, "ai_review")
    if ai is None or not plan["can_start"]:
        raise RuntimeError("AI 연결이 준비되지 않았습니다")
    client, reason = ai_image_flow.subscription_client(engine)   # 분석 연결이 API 키여도 AI 검토는 구독으로만 돈다
    if reason:
        raise RuntimeError(reason)
    stop = _stopper(engine, token) if token is not None else engine.stop_requested
    with engine.ai_turn("AI 검토", progress, should_stop=stop):    # 다른 일괄 AI 작업이 돌면 끝날 때까지 기다린다(구독 호출은 한 번에 하나). 기다리는 중 취소하면 빠진다
        names = engine.graph_names()                             # 도면은 차례를 잡은 뒤 읽는다: 기다리는 동안 다시 추출됐으면 새 판으로 묻는다
        with _LIVE_LOCK:
            cancelled = set(_live(engine)["cancel"]) if token is not None else set()
        pages = [(names[g], _original(names[g])) for g in graph_ids if g in names and names[g] not in cancelled]
        # 다시 묻기는 수락한 나누기가 도면에 든 뒤(inputs.state ready·none)만: 반영 전에 물으면 같은 덩어리를 다시 제안한다(입력 연산 U2 §11.3 4)
        waiting = [n for n, ex in pages if _inputs_waiting(n, ex)]
        pages = [(n, ex) for n, ex in pages if n not in waiting]
        if waiting:
            from hazop.shell import api_inputs
            for n in waiting:
                api_inputs.note(engine, n)                                  # 짓기 차례에 넣는다(조용해지면 다시 읽음)
        est, _mode = ai_image_flow.estimate_pages(pages, cap, ai_review.RUN_CAP, ai_image_flow.enabled(engine))
        if pages and token is not None and _mark_running(engine, token, pages[0][0], 0, est["pages"][0]["calls"] if est["pages"] else None):
            engine.changed("aireview", None)                     # 차례를 잡았다: 첫 도면은 이제 묻는 중
        progress("AI 검토 준비 중(호출 %d회 안팎)" % est["calls"], 0, est["calls"] or None)
        to_gid = {v: k for k, v in names.items()}
        done, images = ai_image_flow.run_pages(engine, pages, client, cap, ai_review.RUN_CAP,
                                               lambda name, d, t, left: _progress(engine, token, progress, name, d, t), stop,
                                               skip=_skipper(engine, token) if token is not None else None,
                                               on_page=(lambda name: _page_started(engine, token, name)) if token is not None else None)
    for n in waiting:
        engine.emit("app.notice", {"text": "%s는 수락한 나누기를 도면에 반영한 뒤 AI에 다시 물을 수 있습니다. 도면을 다시 읽은 뒤 다시 실행하세요." % _number(engine, n)})
    used = images.used if images is not None else {}
    failed = list(images.failed) if images is not None else []
    engine.changed("aireview", None)
    return {"drawings": [{"graph_id": to_gid.get(n), "candidates": count, "calls": st.get("calls", 0), "left": st.get("left", 0),
                          "halted": bool(st.get("halted")), "images": n in used, "legend_source": used.get(n)} for n, count, st in done],
            "waiting_inputs": [to_gid.get(n) for n in waiting],
            "calls": sum(st.get("calls", 0) for _n, _c, st in done), "estimate": est["calls"], "capped": est["capped"],
            "image_failed": failed}


def _inputs_waiting(name, ex):
    """수락한 입력 연산 가운데 아직 기준 추출에 들지 않은 것이 있는가(corrections.resolve의 inputs.state가 pending·partial)."""
    try:
        return corrections.resolve(name, ex)["inputs"]["state"] in ("pending", "partial")
    except (OSError, ValueError, KeyError):
        return False


def _progress(engine, token, progress, name, done, total):
    """실행 진행: 작업 진행 줄과 도면별 상태(묻는 중, 호출 n/m회). 도면이 묻는 중으로 바뀔 때 목록을 다시 읽게 알린다."""
    started = token is not None and _mark_running(engine, token, name, done, total)
    progress("%s AI 검토 중 · 호출 %s/%s회" % (_number(engine, name), done or 0, total or "?") if total else "AI 검토 %s" % name, done, total)
    if started:
        engine.changed("aireview", None)


def _page_started(engine, token, name):
    """run_pages가 도면 하나를 묻기 시작함: 그 도면을 '묻는 중'으로(앞 도면은 끝남). 진행 알림이 오기 전의 첫 호출부터 그 도면의 멈춤을 본다."""
    if _mark_running(engine, token, name, 0, None):
        engine.changed("aireview", None)


def _number(engine, name):
    """진행 줄의 도면 이름(사람용 이름, hazop.shell.api_drawings.display)."""
    from hazop.shell import api_drawings
    gid = next((g for g, n in engine.graph_names().items() if n == name), None)
    return api_drawings.display(engine, gid) if gid else "도면"


BUSY_TEXT = "이 도면은 AI 검토가 이미 돌고 있거나 차례를 기다리고 있습니다. 끝난 뒤 다시 실행하세요."


def _unwrap(out):
    if not out.get("ok"):
        raise _api().CommandError(out.get("code") or "failed", out.get("message") or "처리하지 못했습니다.")
    return out


def _h_decide(fn):
    return lambda engine, a: _unwrap(fn(engine, a["graph_id"], a["cand_ids"], a["ver"]))


def _h_bulk(engine, a):
    return _unwrap(accept_bulk(engine, a["graph_id"], a["task"], a["ver"]))


def _h_stop(engine, a):
    out = request_stop(engine, a["graph_id"])
    if out is None:
        raise _api().CommandError("not_found", "이 도면은 AI 검토가 돌거나 기다리고 있지 않습니다.")
    return out


def _h_run(engine, a):
    api = _api()
    names = engine.graph_names()
    gids = [g for g in a["graph_ids"] if g in names]
    if not gids:
        raise api.CommandError("not_found", "없는 도면")
    from hazop.shell import api_settings
    try:
        plan = api_settings.same_conn(engine, "ai_review", a["conn_ver"])     # 화면에 보인 방식·모델과 지금이 다르면 시작하지 않는다
    except api_settings.Refused as exc:
        raise api.CommandError(exc.code, exc.message)
    if not plan["can_start"]:
        raise api.CommandError("failed", plan["guide"] or "AI 연결이 준비되지 않았습니다. 설정에서 연결을 확인하세요.")
    cap = a.get("cap") or int(engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP)
    if engine.settings.get(ai_image_flow.KEY) is None:          # 실행을 누르는 것은 화면의 안내와 스위치를 본 뒤다: 그때의 값을 적어 둔다(그 뒤부터 추출 뒤 자동 검토도 이 값을 따른다)
        engine.settings[ai_image_flow.KEY] = ai_image_flow.enabled(engine)
        engine.save_settings()
        engine.changed("state")
    held = engine.reserve_review([names[g] for g in gids])
    if not held:
        raise api.CommandError("busy", BUSY_TEXT)

    token = _mark_waiting(engine, held)
    engine.changed("aireview", None)

    def work(progress):
        error = None
        try:
            return run_review(engine, gids, cap, progress, token)
        except api.JobStopped:
            raise
        except Exception as exc:  # noqa: BLE001 - 도면별 상태에 '마치지 못함'을 남기고 작업 오류로 그대로 올린다
            error = str(exc)[:200] or "오류"
            raise
        finally:
            _mark_ended(engine, token, held, error)
            engine.release_review(held)
            engine.changed("aireview", None)
    try:
        job = engine.start_job("AI 검토", work, kind="ai_review")
    except Exception:
        engine.release_review(held)
        raise
    return {"job": job}


def register(commands):
    api = _api()
    C, v_str, v_int, v_list, v_enum = api.Command, api.v_str, api.v_int, api.v_list, api.v_enum
    base = {"graph_id": (v_str(1, 200), True), "ver": (v_str(1, 40), True)}
    ids = (v_list(v_str(1, 120), MAX_IDS), True)

    def put(name, spec_, handler, doc):
        key = "aireview." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("accept", dict(base, cand_ids=ids), _h_decide(accept), "후보 수락(사람 수정 기록에 연산으로 들어가고 그래프를 다시 만든다)")
    put("reject", dict(base, cand_ids=ids), _h_decide(reject), "후보 거절")
    put("revert", dict(base, cand_ids=ids, confirm=(v_list(v_str(1, 120), 500), False)),
        lambda engine, a: _unwrap(revert(engine, a["graph_id"], a["cand_ids"], a["ver"], confirm=a.get("confirm"))),
        "수락·거절 되돌리기(수락한 연산은 수정 기록에서 빠지고 그래프를 다시 만든다). 기댄 사람 고침이 있으면 confirm에 미리 알림의 목록")
    put("accept_bulk", dict(base, task=(v_enum(*ai_review.TASK_ORDER), True)), _h_bulk,
        "확신 높은 묶음 수락(묶음은 엔진이 센다. 기호 종류는 확신 0.95 이상이고 이웃 기호에 붙지 않은 것만)")
    put("stop", {"graph_id": (v_str(1, 200), True)}, _h_stop,
        "도면 하나의 AI 검토를 멈춘다(묻는 중이면 지금 호출 뒤) 또는 취소한다(차례를 기다리는 중). 다른 도면·작업은 그대로")
    put("run", {"graph_ids": (v_list(v_str(1, 200), 200), True), "cap": (v_int(1, 200), False), "conn_ver": (v_str(1, 40), True)}, _h_run,
        "고른 도면에 AI 검토 실행(도면당 상한 cap, 한 번 실행 300회까지). conn_ver는 estimate가 보인 연결의 판")

