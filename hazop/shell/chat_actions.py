"""채팅이 제안한 쓰기 동작의 새 화면 연결부(채팅 규격 §4, 앱 틀 규격 §2.1·§5.2). Qt를 import하지 않는다.

모델은 답 카드의 `actions`에 `{action, args, why}`만 적는다. 이 연결부는 동작 층(`hazop.chat.actions.ActionPlanner`)에 판정을 맡기고
- 바로·후보 동작은 판정 직후 실행하고(구간 만들기는 대표 3~5개까지),
- 확인 동작은 앱이 만든 확인 항목(token)으로 웹에 내보내 사람이 누르면 `approve`·`decline`을 부르고,
- 거절은 이유와 사람이 할 곳을 웹에 보낸다.
웹은 이 값을 그리기만 한다. `by`·`at`·확인자는 여기서(검토자 이름) 채우고 웹 인자로 받지 않는다. 대화가 끝나면 남은 확인 표지를 버린다.

사건: `chat.actions`(한 답의 항목들) · `chat.action.result`(확인을 누른 뒤 한 항목의 결과). 구간이 바뀌면 `changed("nodes", set_rev)`.
항목: {key, action, status, title, text, token, batch_id, node_ids, reason, where, waiting}
status: applied(적용함) · candidate(후보 목록에 넣음) · confirm(확인 대기) · rejected(앱이 거절) · failed · stale · declined · duplicate
"""

import logging
import threading

from hazop.chat import actions as A
from hazop.chat import actions_log

LOG = logging.getLogger("hazop.shell.chat_actions")
NODE_ACTIONS = ("nodes.apply", "nodes.undo", "nodes.confirm", "nodes.unconfirm", "nodes.lock")
MAX_TEXT = 300
MAX_CONFIRM_TEXT = 1500      # 확인 상자 글(앱이 틀에 검사한 값을 채운 글)의 한도. 넘으면 잘렸다고 표시한다
MAX_TARGETS = 200            # 한 상자에 보내는 대상 수 한도. 넘으면 전체 개수와 함께 잘렸다고 표시한다
NAME_CHARS = 60


def _clip(text):
    text = " ".join(str(text or "").split())
    return text[:MAX_TEXT]


def _clip_long(text, limit=MAX_CONFIRM_TEXT):
    """글을 자르되 잘렸으면 눈에 보이게 표시한다(잘린 줄 모르고 확인하지 않게)."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + " …(이하 생략)"


def _short(text, n=NAME_CHARS):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n] + "…"


class ChatActions:
    """project_fn() -> 프로젝트 ID. pg_fn() -> 프로젝트 그래프. reviewer_fn() -> 검토자 이름 또는 None.
    changed(topic, rev) -> 웹에 '이 자료가 바뀜'을 알린다. model_fn() -> 모델 이름(기록용)."""

    def __init__(self, emit, project_fn, pg_fn, reviewer_fn, changed, model_fn=None, record=actions_log.record, planner_factory=None):
        self._emit = emit
        self._project_fn = project_fn
        self._pg_fn = pg_fn
        self._reviewer_fn = reviewer_fn
        self._changed = changed
        self._model_fn = model_fn or (lambda: None)
        self._record = record
        self._planner_factory = planner_factory
        self._lock = threading.RLock()
        self._planner = None
        self._planner_project = None
        self._queue = {}          # answer_id -> 아직 띄우지 않은 확인 항목(token) 목록
        self._shown = {}          # token -> 화면에 보낸 항목
        self._items = {}          # token -> 동작 층이 판정한 Item(결과 글을 만들 때 인자를 본다)

    # ------------------------------------------------------------ 대화 수명
    def end_conversation(self):
        """대화가 끝남(새 대화·프로젝트 바뀜·창 닫음): 남은 확인 표지를 버린다."""
        with self._lock:
            planner, self._planner = self._planner, None
            self._queue.clear()
            self._shown.clear()
            self._items.clear()
        if planner is not None:
            planner.end_conversation()

    def _get(self):
        project = self._project_fn()
        with self._lock:
            if self._planner is not None and self._planner_project != project:
                old, self._planner = self._planner, None
                old.end_conversation()
            if self._planner is None:
                self._planner = self._make(project)
                self._planner_project = project
            return self._planner

    def _make(self, project):
        if self._planner_factory is not None:
            return self._planner_factory(project, self.read_state, self._executors())
        return A.ActionPlanner(project, self.read_state, self._executors(), record=self._record, model=self._model_fn(), via="subscription")

    def _executors(self):
        from hazop.study import node_commands

        def make(name):
            def run(args, call):
                return A.node_executors(self._pg_fn(), node_commands.execute)[name](args, call)
            return run
        return {name: make(name) for name in NODE_ACTIONS}

    def read_state(self):
        """plan·approve 직전마다 새로 읽는 프로젝트 상태(저장본을 읽기만 한다)."""
        from hazop.study import nodes as sn
        from hazop.study import results as res
        pg = self._pg_fn()
        project = self._project_fn()
        if not pg:
            return A.Snapshot(project)
        ns = sn.read_as_is(pg) or sn.new_set(pg)
        results = None
        try:
            results, _fp = res.load_fp(ns)
        except (OSError, ValueError):
            results = None
        return A.Snapshot(project, node_set=ns, results=results, graph_ids=frozenset(n["entity_id"] for n in pg.get("nodes") or []))

    # ------------------------------------------------------------ 답 하나
    def handle(self, actions, turn, request_text):
        """답 카드의 actions를 판정·실행해 웹에 보낸다 -> 항목 목록. 동작이 없으면 아무것도 하지 않는다."""
        if not isinstance(actions, list) or not actions:
            return []
        try:
            planner = self._get()
        except Exception:  # noqa: BLE001 - 프로젝트를 읽지 못해도 답 글은 이미 보였다
            LOG.exception("동작 층을 만들지 못함")
            return []
        answer_id = actions_log.new_id("a")
        request_id = actions_log.new_id("q")
        items = []
        changed_rev = None
        try:
            plan = planner.plan(answer_id, actions, turn, request_id, request_text or "")
            for it in plan.run:
                out = planner.run(it)
                entry, rev = self._run_entry(planner, it, out)
                items.append(entry)
                changed_rev = rev if rev is not None else changed_rev
            confirms = list(plan.confirm)
            shown_confirms = 0
            for it in confirms:
                entry = self._confirm_entry(it, waiting=shown_confirms > 0)
                items.append(entry)
                if entry["status"] == "confirm":
                    if shown_confirms > 0:
                        self._queue.setdefault(answer_id, []).append(it.token)
                    shown_confirms += 1
            for it in plan.rejected:
                items.append(self._rejected_entry(it))
        except Exception:  # noqa: BLE001 - 동작 층 오류가 대화를 깨지 않게 한다
            LOG.exception("채팅 동작 처리 오류")
            items.append({"key": answer_id + "#0", "action": "", "status": "failed", "title": "동작을 처리하지 못했습니다",
                          "text": "", "token": None, "batch_id": None, "node_ids": [], "reason": "internal", "where": None, "waiting": False})
        if items:
            self._emit("chat.actions", {"answer_id": answer_id, "items": items})
        if any(e["status"] == "applied" for e in items):
            self._changed("nodes", changed_rev)
        return items

    # ------------------------------------------------------------ 확인 상자
    def approve(self, token):
        """확인 상자에서 사람이 '실행'을 눌렀다 -> 결과 항목. 검토자 이름이 없으면 실행하지 않는다."""
        reviewer = (self._reviewer_fn() or "").strip()
        if not reviewer:
            return {"ok": False, "error": "no_reviewer", "message": "검토자 이름이 있어야 실행할 수 있습니다. 설정에서 이름을 입력하세요."}
        planner = self._current()
        if planner is None:
            return {"ok": False, "error": "closed", "message": "대화가 끝나 확인이 만료되었습니다."}
        shown, item = self._shown.get(token), self._items.get(token)
        out = planner.approve(token, reviewer)
        entry, rev = self._run_entry(planner, item, out) if item is not None else (None, None)
        if entry is not None:
            self._emit("chat.action.result", {"token": token, "item": entry})
            if entry["status"] == "applied":
                self._changed("nodes", rev)
        self._next(shown)
        return {"ok": True, "result": out.get("result"), "item": entry}

    def decline(self, token):
        planner = self._current()
        shown = self._shown.get(token)
        if planner is None or shown is None:
            return {"ok": False, "error": "closed", "message": "대화가 끝나 확인이 만료되었습니다."}
        out = planner.decline(token)
        entry = dict(shown, status="declined", token=None, title="실행하지 않았습니다", text=_clip(shown.get("text")), waiting=False)
        self._emit("chat.action.result", {"token": token, "item": entry})
        self._next(shown)
        return {"ok": True, "result": out.get("result"), "item": entry}

    def _current(self):
        with self._lock:
            return self._planner

    def _next(self, shown):
        """같은 답의 다음 확인 동작을 띄운다(한 번에 하나). 지금 상태로 다시 검사해 새 표지를 단다."""
        if shown is None:
            return
        answer_id = (shown.get("key") or "").rsplit("#", 1)[0]
        with self._lock:
            queue = self._queue.get(answer_id) or []
            token = queue.pop(0) if queue else None
        planner = self._current()
        if token is None or planner is None:
            return
        fresh = planner.reissue(token)
        if fresh is None:
            return
        if fresh.klass == "rejected":
            entry = self._rejected_entry(fresh)
        else:
            entry = self._confirm_entry(fresh, waiting=False)
        old = self._shown.get(token)
        self._emit("chat.action.result", {"token": token, "item": entry, "replaces": old["key"] if old else None})

    # ------------------------------------------------------------ 항목 만들기
    def _base(self, item):
        return {"key": item.key, "action": item.action, "status": None, "title": "", "text": "", "token": None, "batch_id": None,
                "node_ids": [], "reason": None, "where": None, "waiting": False, "targets": [], "targets_total": 0, "ops": []}

    def _names(self):
        """구간 ID -> 이름(지금 저장본). 못 읽으면 빈 표."""
        try:
            snap = self.read_state()
            return {n.get("node_id"): n.get("name") or "" for n in ((snap.node_set or {}).get("nodes") or [])}
        except Exception:  # noqa: BLE001
            return {}

    def _confirm_entry(self, item, waiting):
        """확인 상자 항목. 상자의 대상 목록과 변경 줄은 모델이 쓴 글이 아니라 앱이 검사한 실제 인자(item.args·item.targets)에서 만든다.
        보여 줄 대상이 하나도 없는 동작은 확인을 받지 않고 거절로 돌린다(보지 못한 것을 승인하게 하지 않는다)."""
        names = self._names()
        targets = _targets_of(item, names)
        ops = _op_lines(item, names)
        if not targets["items"] and not ops:
            e = self._rejected_entry(item)
            e["reason"] = "실행할 대상을 확인할 수 없어 실행하지 않습니다."
            return e
        e = self._base(item)
        e.update(status="confirm", title=_title(item), text=_clip_long(item.confirm_text), token=item.token, waiting=waiting,
                 targets=targets["items"], targets_total=targets["total"], ops=ops)
        self._items[item.token] = item
        self._shown[item.token] = e
        return e

    def _rejected_entry(self, item):
        e = self._base(item)
        e.update(status="rejected", title=_title(item), text="", reason=_clip(item.reason), where=_clip(item.where) or None)
        return e

    def _run_entry(self, planner, item, out):
        """실행 결과(out)를 항목으로. -> (항목, 구간 판 번호 또는 None)."""
        e = self._base(item)
        result = out.get("result")
        e["title"] = _title(item)
        if result == "needs_confirm":                       # 그 사이 상태가 바뀌어 확인이 필요해짐
            fresh = planner.reissue(out.get("item")) if out.get("item") is not None else None   # 지금 상태로 다시 검사해 승인 표지를 단다
            if fresh is None:
                e.update(status="rejected", reason="확인 상자를 만들 수 없어 실행하지 않습니다.")
                return e, None
            if fresh.klass == "rejected":
                return self._rejected_entry(fresh), None
            return self._confirm_entry(fresh, waiting=False), None     # 새 표지를 등록해 눌렀을 때 실행·결과 사건·바뀜 알림이 나가게 한다
        if result in ("ok", "candidate"):
            e.update(status="applied" if result == "ok" else "candidate", batch_id=out.get("batch_id"), node_ids=list(out.get("targets") or []))
            e["text"] = _done_text(item, out)
            return e, out.get("set_rev")
        if result == "duplicate":
            e.update(status="duplicate", text="이미 처리한 동작입니다.")
            return e, None
        reason = out.get("error") or ""
        refused = out.get("refused") or []
        if refused and not reason:
            reason = "; ".join(str(r.get("reason") or "") for r in refused if isinstance(r, dict))
        e.update(status={"stale": "stale", "failed": "failed"}.get(result, "rejected"), reason=_clip(reason),
                 text=_clip(reason))
        return e, None


def _title(item):
    name = getattr(item, "action", "") or ""
    ops = (getattr(item, "args", None) or {}).get("ops") or []
    if name == "nodes.apply":
        kinds = {o.get("op") for o in ops if isinstance(o, dict)}
        if kinds == {"add"}:
            return "구간 %d개 만들기" % len(ops)
        if kinds == {"remove"}:
            return "구간 %d개 지우기" % len(ops)
        return "구간 고치기"
    return {"nodes.undo": "묶음 되돌리기", "nodes.confirm": "구간 확정", "nodes.unconfirm": "구간 확정 해제",
            "nodes.lock": "분석 마침 · 잠금"}.get(name, name or "동작")


def _done_text(item, out):
    name = item.action
    batch = out.get("batch_id")
    targets = list(out.get("targets") or [])
    if name == "nodes.undo":
        return "묶음 %s을(를) 되돌렸습니다." % ((getattr(item, "args", None) or {}).get("batch_id_to_undo") or batch or "")
    if name == "nodes.apply":
        ops = (getattr(item, "args", None) or {}).get("ops") or []
        names = [o.get("name") for o in ops if isinstance(o, dict) and o.get("name")]
        kinds = {o.get("op") for o in ops if isinstance(o, dict)}
        verb = "만들었습니다" if kinds == {"add"} else "지웠습니다" if kinds == {"remove"} else "고쳤습니다"
        head = "구간 %s개를 %s" % (len(targets) or len(ops), verb)
        tail = (" · 묶음 " + batch) if batch else ""
        label = (": " + ", ".join(str(n) for n in names[:6]) + (" …" if len(names) > 6 else "")) if names and kinds == {"add"} else ""
        return _clip(head + label + tail + ".")
    return {"nodes.confirm": "확정했습니다.", "nodes.unconfirm": "확정을 풀었습니다.", "nodes.lock": "잠갔습니다."}.get(name, "처리했습니다.")


def _label(node_id, names):
    name = names.get(node_id)
    return {"id": node_id, "label": "%s %s" % (node_id, _short(name)) if name else node_id}


def _targets_of(item, names):
    """확인 상자에 보일 실제 대상: 동작 층이 판정한 item.targets(구간 ID·칸·파일 열쇠)와, 구간 동작의 인자에 든 구간 ID. 많으면 MAX_TARGETS까지만 보내고 전체 수를 함께 준다."""
    seen, out = set(), []
    args = getattr(item, "args", None) or {}
    ids = list(getattr(item, "targets", None) or [])
    ids += [x for x in (args.get("node_ids") or []) if isinstance(x, str)]
    for op in args.get("ops") or []:
        if isinstance(op, dict):
            ids += [x for x in ([op.get("node_id")] + list(op.get("node_ids") or [])) if isinstance(x, str)]
    for x in ids:
        if isinstance(x, str) and x not in seen:
            seen.add(x)
            out.append(_label(x, names))
    return {"items": out[:MAX_TARGETS], "total": len(out)}


def _op_lines(item, names):
    """nodes.apply의 변경 줄: 무엇을 어느 구간에 하는지(앱이 검사한 인자에서 만든다). 새 구간은 이름만(모델 글이라 짧게 자르고 텍스트로만 보인다)."""
    out = []
    for op in (getattr(item, "args", None) or {}).get("ops") or []:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        if kind == "add":
            out.append("새 구간 만들기: %s" % (_short(op.get("name")) or "(이름 없음)"))
        elif kind == "remove":
            out.append("지우기: %s" % _label(op.get("node_id"), names)["label"])
        elif kind == "edit":
            what = [w for w, k in (("이름", "name"), ("설계 의도", "design_intent"), ("구성요소", "members")) if k in op]
            out.append("고치기: %s (%s)" % (_label(op.get("node_id"), names)["label"], "·".join(what) or "내용"))
        elif kind == "merge":
            out.append("합치기: %s" % ", ".join(_label(i, names)["label"] for i in (op.get("node_ids") or [])))
        elif kind == "split":
            out.append("나누기: %s" % _label(op.get("node_id"), names)["label"])
    return out[:MAX_TARGETS]
