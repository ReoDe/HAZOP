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
import os
import threading

from hazop.chat import actions as A
from hazop.chat import actions_log

LOG = logging.getLogger("hazop.shell.chat_actions")
NODE_ACTIONS = ("nodes.apply", "nodes.undo", "nodes.confirm", "nodes.unconfirm", "nodes.lock")
# A11 1차: 화면·엔진에 이미 있는 기능을 잇는 실행 동작(엔진 함수는 api_results·api_drawings·data를 부르기만 한다)
RUN_ACTIONS = ("analysis.run", "results.set_status", "results.edit", "export.excel", "export.ie_bundle",
               "register.extract", "register.reextract", "sheet.confirm", "dexpi.export")
DISPLAY_ACTIONS = ("show", "goto", "select", "layer", "fit")
# 동작 표에는 있으나 아직 새 화면이 없는 동작(2차) -> 사람이 할 곳
NOT_YET = {
    "register.exclude": "도면 패널에 '분석에서 빼기'가 생기면 잇는다",
    "extract.suggest": "도면의 AI 후보 목록에서 사람이 한다",
    "kg.algorithm": "지식그래프 화면이 생기면 잇는다",
    "kg.rebuild": "지식그래프 화면이 생기면 잇는다",
    "ie.draft_rules": "⑥ 초기사건 패널의 '규칙 초안'에서 사람이 한다",
    "ie.reset": "⑥ 초기사건 패널에서 사람이 한다",
}
PANELS = {"drawings": "도면", "nodes": "구간", "results": "분석 결과", "ie": "초기사건", "settings": "설정"}
PANEL_ALIASES = {"①": "drawings", "②": "drawings", "도면": "drawings", "register": "drawings", "extract": "drawings",
                 "④": "nodes", "구간": "nodes", "검토구간": "nodes", "⑤": "results", "결과": "results", "분석 결과": "results",
                 "analysis": "results", "⑥": "ie", "초기사건": "ie", "설정": "settings"}
LAYERS = {"symbol": "symbol", "symbols": "symbol", "기호": "symbol", "pipe": "pipe", "pipes": "pipe", "배관": "pipe",
          "tag": "tag", "tags": "tag", "태그": "tag", "글자": "tag"}
LAYER_NAMES = {"symbol": "기호", "pipe": "배관", "tag": "태그"}
MAX_DISPLAY_IDS = 400
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

    def __init__(self, emit, project_fn, pg_fn, reviewer_fn, changed, model_fn=None, record=actions_log.record, planner_factory=None,
                 engine=None):
        # engine: hazop.shell.api.Engine(분석 실행·내보내기·쪽 확정이 부르는 창구). 창이 넘기지 않으면 project_fn이 엔진의 메서드일 때 그 엔진을 쓴다
        self._engine = engine if engine is not None else _engine_of(project_fn)
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
        return A.ActionPlanner(project, self.read_state, self._executors(), record=self._record, model=self._model_fn(), via="subscription",
                               not_yet=self._not_yet(), extra_checks=self._extra_checks(), detail_fns=self._detail_fns())

    def _extra_checks(self):
        """확인 상자를 띄우기 전에 거절할 것(이 화면의 실행 함수가 못 하는 것)."""
        def analysis(item, snap):
            if len(item.args.get("node_ids") or []) != 1:
                return "한 번에 한 구간씩 분석합니다. 여러 구간은 ⑤ 분석 결과의 '전체 분석'으로 하세요."
            if len(item.args.get("cell_ids") or []) > 1:
                return "칸은 한 번에 하나만 다시 분석합니다."
            return None
        return {"analysis.run": analysis}

    def _detail_fns(self):
        """확인 상자 줄(규격 §4.2): 분석 실행은 호출 수 어림, 다시 추출은 다시 얹을 사람 수정 수와 풀리는 쪽 확정."""
        return {"analysis.run": lambda item, snap: analysis_details(item, snap),
                "register.reextract": lambda item, snap: reextract_details(snap.registrations.get(item.args["registration_id"]) or {})}

    def _not_yet(self):
        """2차 동작과, 엔진이 없어 이을 수 없는 실행 동작 -> 사람이 할 곳."""
        out = dict(NOT_YET)
        if self._engine is None:
            out.update({name: "이 창에서는 채팅으로 실행할 수 없습니다" for name in RUN_ACTIONS})
        return out

    def _executors(self):
        from hazop.study import node_commands

        def make(name):
            def run(args, call):
                return A.node_executors(self._pg_fn(), node_commands.execute)[name](args, call)
            return run
        out = {name: make(name) for name in NODE_ACTIONS}
        if self._engine is not None:
            self.runner = RunExecutors(self._engine, self._pg_fn, lambda: self._registrations(self._project_fn()),
                                       record=self._record_outcome)
            out.update(self.runner.table())
        return out

    def read_state(self):
        """plan·approve 직전마다 새로 읽는 프로젝트 상태(저장본을 읽기만 한다)."""
        from hazop.study import nodes as sn
        from hazop.study import results as res
        pg = self._pg_fn()
        project = self._project_fn()
        regs, sheets = self._registrations(project), _Sheets(self._engine)
        if not pg:
            return A.Snapshot(project, registrations=regs, sheets=sheets)
        ns = sn.read_as_is(pg) or sn.new_set(pg)
        results, fp = None, None
        try:
            results, fp = res.load_fp(ns)
        except (OSError, ValueError):
            results = None
        return A.Snapshot(project, node_set=ns, results=results, graph_ids=frozenset(n["entity_id"] for n in pg.get("nodes") or []),
                          registrations=regs, sheets=sheets, results_fp=fp)

    def _registrations(self, project):
        """등록 자료 ID(material_id)와 그 추출 이름·도면 ID -> {has_result, excluded, path}. 엔진이 없으면 빈 표."""
        if self._engine is None:
            return {}
        try:
            from hazop.app import data
            rows = data.list_registrations()
        except Exception:  # noqa: BLE001 - 등록을 못 읽어도 다른 동작은 판정한다
            LOG.exception("등록 목록을 읽지 못함")
            return {}
        try:
            by_name = {v: k for k, v in self._engine.graph_names().items()}
        except Exception:  # noqa: BLE001
            by_name = {}
        out = {}
        for e in rows:
            rec = e.get("record") or {}
            if rec.get("project_id") != project or rec.get("status") != "registered":
                continue
            names = page_names(rec, e.get("extract_name"))
            entry = {"has_result": bool(e.get("extracted")) or any(_has_output(n) for n in names), "excluded": False,
                     "path": e.get("path"), "names": names}
            for key in (rec.get("material_id"), e.get("extract_name"), by_name.get(e.get("extract_name"))):
                if isinstance(key, str) and key:
                    out.setdefault(key, entry)
        return out

    # ------------------------------------------------------------ 표시 동작(데이터를 바꾸지 않음)
    def show(self, items, answer_id):
        """plan.display를 도면·패널에 보일 항목으로 풀어 웹에 보낸다(chat.display). 기록하지 않는다(표시는 실행 기록 대상이 아님)."""
        if not items:
            return []
        try:
            pg = self._pg_fn() or {"nodes": []}
        except Exception:  # noqa: BLE001
            pg = {"nodes": []}
        names = {}
        if self._engine is not None:
            try:
                names = self._engine.graph_names()
            except Exception:  # noqa: BLE001
                names = {}
        out = []
        for it in items:
            try:
                out.append(display_item(it.action, it.args or {}, pg, names, self._node_ids))
            except Exception:  # noqa: BLE001 - 하나가 깨져도 나머지는 보인다
                LOG.exception("표시 동작을 풀지 못함")
                out.append({"op": "none", "ok": False, "text": "보이지 못했습니다."})
        self._emit("chat.display", {"answer_id": answer_id, "items": out})
        return out

    def _node_ids(self):
        from hazop.study import nodes as sn
        try:
            pg = self._pg_fn()
            ns = (sn.read_as_is(pg) if pg else None) or {}
            return {n.get("node_id") for n in ns.get("nodes") or []}
        except Exception:  # noqa: BLE001
            return set()

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
        topics = []
        try:
            plan = planner.plan(answer_id, actions, turn, request_id, request_text or "")
            self.show(plan.display, answer_id)
            for it in plan.run:
                out = planner.run(it)
                entry, rev = self._run_entry(planner, it, out)
                items.append(entry)
                changed_rev = rev if rev is not None else changed_rev
                if entry["status"] in ("applied", "candidate"):
                    topics += [t for t in out.get("topics") or [] if t not in topics]
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
        if any(e["status"] == "applied" and e["action"] in NODE_ACTIONS for e in items):
            self._changed("nodes", changed_rev)
        for topic in topics:
            self._changed(topic, None)
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
            if entry["status"] == "applied" and entry["action"] in NODE_ACTIONS:
                self._changed("nodes", rev)
            if entry["status"] == "applied":
                for topic in out.get("topics") or []:
                    self._changed(topic, None)
        self._next(shown)
        return {"ok": True, "result": out.get("result"), "item": entry}

    def decline(self, token):
        planner = self._current()
        shown = self._shown.get(token)
        if planner is None or shown is None:
            return {"ok": False, "error": "closed", "message": "대화가 끝나 확인이 만료되었습니다."}
        out = planner.decline(token)
        entry = dict(shown, status="declined", token=None, title="실행하지 않았습니다", text=_clip(shown.get("text")), waiting=False,
                     log_error=_log_error(out))
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
                 targets=targets["items"], targets_total=targets["total"], ops=ops, details=list(getattr(item, "details", None) or []))
        self._items[item.token] = item
        self._shown[item.token] = e
        return e

    def _rejected_entry(self, item):
        e = self._base(item)
        e.update(status="rejected", title=_title(item), text="", reason=_clip(item.reason), where=_clip(item.where) or None)
        e["log_error"] = self._log_error_of(item.keys)
        return e

    def _log_error_of(self, keys):
        """이 동작의 기록 쓰기가 실패했으면 그 까닭(화면에 알린다). 동작 층이 남긴 기록 결과(planner.log)에서 찾는다."""
        planner = self._current()
        for key, _result, rec in list(getattr(planner, "log", None) or []):
            if key in keys and _rec_failed(rec):
                return "실행 기록을 남기지 못했습니다(%s)." % _clip(_rec_error(rec))
        return None

    def _record_outcome(self, call, result, error=None, targets=()):
        """뒤에서 도는 작업(분석·추출)이 끝났을 때의 결과를 같은 동작 열쇠로 한 줄 더 남긴다(result: done | failed)."""
        try:
            key = (call.action_keys or [""])[0]
            answer_id, index = key.rsplit("#", 1)
            klass = "confirm" if call.confirmed_by else "auto"
            prop = {"action": call.action or "", "args": {}, "why": "작업이 끝남"}
            rec = self._record(call.project_id, answer_id=answer_id, index=int(index), request_id=call.request_id or "q-none",
                               request_text="", proposal=prop, klass=klass, result=result, error=error, targets=list(targets),
                               confirmed_by=call.confirmed_by if klass == "confirm" else None,
                               confirmed_at=actions_log.now_kst().isoformat() if klass == "confirm" else None,
                               conversation_id=call.conversation_id, model=call.model, via="subscription")
        except Exception as exc:  # noqa: BLE001 - 끝난 기록을 못 남겨도 작업은 이미 끝났다. 화면에 알린다
            LOG.exception("작업 끝 기록을 남기지 못함")
            rec = {"status": "failed", "error": str(exc)}
        if _rec_failed(rec):
            self._emit("chat.notice", {"text": "작업 끝 기록을 남기지 못했습니다(%s)." % _clip(_rec_error(rec))})
        return rec

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
            e.update(status="applied" if result == "ok" else "candidate", batch_id=out.get("batch_id"),
                     node_ids=list(out.get("targets") or []) if item.action in NODE_ACTIONS else [])
            e["text"] = _clip(out.get("message")) if out.get("message") and item.action not in NODE_ACTIONS else _done_text(item, out)
            e["log_error"] = _log_error(out)
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
        e["log_error"] = _log_error(out)
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
    return TITLES.get(name, name or "동작")


TITLES = {"nodes.undo": "묶음 되돌리기", "nodes.confirm": "구간 확정", "nodes.unconfirm": "구간 확정 해제", "nodes.lock": "분석 마침 · 잠금",
          "analysis.run": "AI 분석 실행", "results.set_status": "결과 판정", "results.edit": "결과 항목 고치기",
          "export.excel": "Excel로 내보내기", "export.ie_bundle": "초기사건 인계 묶음 내보내기", "register.extract": "추출",
          "register.reextract": "다시 추출", "sheet.confirm": "도면 쪽 확정", "dexpi.export": "DEXPI로 내보내기",
          # 아직 잇지 않았거나 채팅으로 하지 않는 동작(거절 줄의 이름)
          "register.exclude": "분석에서 빼기", "extract.suggest": "추출 값 후보", "kg.algorithm": "지식그래프 알고리즘",
          "kg.rebuild": "지식그래프 다시 만들기", "ie.draft_rules": "초기사건 규칙 초안", "ie.reset": "초기사건 새로 시작",
          "kg.judge": "지식그래프 판단", "titleblock.confirm": "표제란 확정", "ie.edit": "초기사건 편집", "drawing.edit": "도면 고치기",
          "extract.accept": "AI 후보 수락", "extract.edit": "추출 편집", "nodes.unlock": "잠금 풀기", "sheet.compare": "원본과 견줌",
          "settings.change": "설정 바꾸기", "settings.api_key": "API 키", "settings.work_root": "작업 루트", "settings.reviewer": "검토자 이름",
          "files.delete": "파일 지우기"}


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


# ================================================================ 등록 쪽·확인 상자 줄·기록 결과

def page_names(record, extract_name=None):
    """등록 하나가 만드는 추출 이름들. PDF는 등록된 쪽마다, 그 밖은 하나."""
    try:
        from hazop.app import data
        if record.get("format") == "pdf":
            xp, ex = data.script_module("extract_pdf"), data.script_module("extract_drawio")
            return [ex.registered_out_name(record, i) for i in xp.registered_pages(record)]
    except Exception:  # noqa: BLE001
        LOG.exception("등록 쪽 이름을 만들지 못함")
    return [extract_name] if extract_name else []


def _has_output(name):
    """추출 폴더에 결과(extraction.json)나 건너뛴 표시(not_extracted.json)가 있는지."""
    from hazop import paths
    d = os.path.join(paths.output_root("extract"), name)
    return os.path.isfile(os.path.join(d, "extraction.json")) or os.path.isfile(os.path.join(d, "not_extracted.json"))


def reextract_details(reg):
    """다시 추출 확인 상자 줄: 다시 얹을 사람 수정 수, 풀리는 쪽 확정 수(규격 §4.2)."""
    from hazop.extract import confirmation, corrections
    names = list(reg.get("names") or [])
    edits, confirmed = 0, []
    for name in names:
        try:
            doc = corrections.load(name) or {}
            edits += len([o for o in doc.get("ops") or [] if isinstance(o, dict)])
        except (OSError, ValueError):
            pass
        try:
            if confirmation.sheet_confirmation(name).get("state") == "confirmed":
                confirmed.append(name)
        except (OSError, ValueError):
            pass
    rows = [{"label": "다시 추출할 쪽", "after": "%d쪽" % len(names)},
            {"label": "사람 수정", "after": "%d건을 새 결과 위에 다시 얹습니다. 대상이 사라진 수정은 얹지 못하며, 끝난 뒤 그 목록을 보입니다." % edits}]
    if confirmed:
        rows.append({"label": "쪽 확정", "after": "확정한 %d쪽(%s)의 확정이 풀립니다. 다시 견주고 확정해야 DEXPI로 내보낼 수 있습니다."
                     % (len(confirmed), ", ".join(confirmed[:5]) + (" 외" if len(confirmed) > 5 else ""))})
    return rows


def analysis_details(item, snap):
    """분석 실행 확인 상자 줄: 호출 수 어림(규격 §4.2·§2.6). 확정 구간만 분석한다."""
    from hazop.shell import analysis_run
    ns = snap.node_set or {}
    ids = item.args.get("node_ids") or []
    cells = item.args.get("cell_ids") or []
    if not ns or len(ids) != 1:
        return []
    try:
        from hazop.shell import api_results
        doc = snap.results
        scope = "cell" if len(cells) == 1 else "node"
        units = analysis_run.plan(api_results.scope_set(ns), doc or {"cells": []}, scope, ids[0],
                                  cells[0].split("/")[-1] if cells else None)
        n = len(units)
    except Exception:  # noqa: BLE001
        LOG.exception("호출 수 어림을 만들지 못함")
        return [{"label": "호출 수 어림", "after": "셀 수 없음"}]
    if not n:
        return [{"label": "호출 수 어림", "after": "0회(분석할 칸이 없음: 확정한 구간만 분석합니다)"}]
    return [{"label": "호출 수 어림", "after": "약 %d회(구독 한도를 씁니다)" % n}]


def _rec_failed(rec):
    if isinstance(rec, list):
        return any(_rec_failed(r) for r in rec)
    status = getattr(rec, "status", None) if not isinstance(rec, dict) else rec.get("status")
    return status == "failed"


def _rec_error(rec):
    if isinstance(rec, list):
        return next((_rec_error(r) for r in rec if _rec_failed(r)), "")
    return (getattr(rec, "error", None) if not isinstance(rec, dict) else rec.get("error")) or "까닭 모름"


def _log_error(out):
    rec = (out or {}).get("record")
    return "실행 기록을 남기지 못했습니다(%s)." % _clip(_rec_error(rec)) if rec is not None and _rec_failed(rec) else None


# ================================================================ 엔진 창구·쪽 상태

def _engine_of(fn):
    """창이 엔진을 따로 넘기지 않았을 때: project_fn이 엔진의 메서드(engine.project_id)면 그 엔진."""
    eng = getattr(fn, "__self__", None)
    return eng if eng is not None and hasattr(eng, "dispatch") and hasattr(eng, "hooks") else None


def sheet_state(name):
    """추출 이름 하나의 쪽 확정 상태(파일을 쓰지 않음). 채팅으로 확정할 수 있는 것은 'ready'이고 지금 지문으로 원본과 견준 쪽뿐이다."""
    from hazop.extract import confirmation
    try:
        st = confirmation.sheet_confirmation(name)
    except FileNotFoundError:
        return {"state": "open", "fingerprint": None, "rev": 0, "reason": "추출 결과가 없음"}
    except (OSError, ValueError):
        return {"state": "open", "fingerprint": None, "rev": 0, "reason": "쪽 자료를 읽을 수 없음"}
    fp = st.get("fingerprint")
    counts = st.get("counts") or {}
    compared = st.get("compared") or {}
    state = st.get("state")
    reasons = []
    if counts.get("total"):
        reasons.append("미확인 %d곳" % counts["total"])
    if counts.get("unplaced"):
        reasons.append("위치 없는 것 %d개" % counts["unplaced"])
    if st.get("leftovers") is None and state != "confirmed":
        reasons.append("원본에 남은 것을 셀 수 없는 읽기 방식")
    if state == "ready" and compared.get("fingerprint") != fp:
        state = "open"
        reasons.append("원본과 견주지 않음")
    return {"state": state, "fingerprint": fp, "rev": st.get("rev") or 0, "reason": ", ".join(reasons) or None}


class _Sheets:
    """graph_id -> 쪽 확정 상태. 도면이 수백 장이어도 판정마다 모두 읽지 않게, 물을 때만 읽는다(Snapshot.sheets 자리)."""

    def __init__(self, engine):
        self._engine = engine
        self._names = None
        self._cache = {}

    def _all(self):
        if self._names is None:
            try:
                self._names = dict(self._engine.graph_names()) if self._engine is not None else {}
            except Exception:  # noqa: BLE001
                self._names = {}
        return self._names

    def __contains__(self, gid):
        return isinstance(gid, str) and gid in self._all()

    def get(self, gid, default=None):
        if gid not in self:
            return default
        if gid not in self._cache:
            self._cache[gid] = sheet_state(self._all()[gid])
        return self._cache[gid]

    def __getitem__(self, gid):
        found = self.get(gid)
        if found is None:
            raise KeyError(gid)
        return found


# ================================================================ 실행 동작(A11 1차)

def _ok(message, topics=(), **extra):
    return dict({"ok": True, "refused": [], "batch_id": None, "node_ids": [], "set_rev": None, "message": message,
                 "topics": list(topics)}, **extra)


def _refused(reason, code="rule", target=""):
    return {"ok": False, "refused": [{"target": target, "code": code, "reason": str(reason)[:300]}], "batch_id": None,
            "node_ids": [], "set_rev": None}


def _unique(folder, name):
    """folder 안에서 아직 없는 이름(이미 있으면 '-2', '-3'…을 붙인다). 내보내기가 남의 파일을 덮어쓰지 않게 한다."""
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(folder, candidate)):
        n += 1
        candidate = "%s-%d%s" % (stem, n, ext)
    return os.path.join(folder, candidate)


class _AutoSave:
    """엔진을 감싸 저장 위치 묻기(대화상자)를 정해 둔 곳으로 바꾼다. 채팅 내보내기는 작업 루트 output/exports에 시각을 붙인 새 이름으로 쓰고
    덮어쓰지 않는다(이미 있으면 번호를 붙이고, 그래도 겹치면 덮어쓰기를 거절한다). 나머지 속성은 엔진 것을 그대로 쓴다."""

    def __init__(self, engine, folder):
        self._engine = engine
        self.folder = folder
        self.saved = None
        self.hooks = dict(engine.hooks, save_path=self._save_path, save_dir=self._save_dir,
                          confirm_overwrite_files=lambda names: False)

    def __getattr__(self, name):
        return getattr(self._engine, name)

    def _save_path(self, kind, default_name):
        os.makedirs(self.folder, exist_ok=True)
        self.saved = _unique(self.folder, default_name)
        return self.saved

    def _save_dir(self, kind):
        stamp = actions_log.now_kst().strftime("%Y%m%d-%H%M")
        self.saved = _unique(self.folder, "DEXPI-%s-%s" % (self._engine.project_id(), stamp))
        os.makedirs(self.saved)
        return self.saved


class RunExecutors:
    """실행 동작의 실행 함수 표. 엔진 함수(api_results·api_drawings·data)를 부르기만 하고, 그 함수가 내는 CommandError는 엔진 거절로 바꾼다.
    돌려주는 꼴은 actions.EXECUTOR_RESULT(성공 글 message와 바뀐 자료 changed 포함)."""

    def __init__(self, engine, pg_fn, regs_fn=None, record=None, watch=True):
        self.engine = engine
        self.pg_fn = pg_fn
        self.regs_fn = regs_fn
        self.record = record          # 뒤 작업이 끝났을 때 결과를 남기는 함수(call, result, error, targets)
        self.watch = watch            # 분석 작업의 끝을 지켜볼 스레드를 띄울지(시험은 끄고 watch_job을 직접 부른다)
        self._lock = threading.Lock()
        self._extracting = set()      # 지금 추출 작업이 도는 등록 자료(같은 자료를 겹쳐 추출하지 않는다)
        self.watchers = []

    def table(self):
        g = self._guard
        return {"analysis.run": g(self.analysis), "results.set_status": g(self.result("set_status")),
                "results.edit": g(self.result("edit_entry")), "export.excel": g(self.excel), "export.ie_bundle": g(self.ie_bundle),
                "register.extract": g(self.extract), "register.reextract": g(self.extract), "sheet.confirm": g(self.sheet_confirm),
                "dexpi.export": g(self.dexpi)}

    def _guard(self, fn):
        def run(args, call):
            from hazop.shell import api
            try:
                return fn(args, call)
            except api.CommandError as exc:
                return _refused(exc.message, exc.code)
        return run

    def _exports(self):
        from hazop import paths
        return paths.output_root("exports")

    # ---- ⑤
    def analysis(self, args, call):
        from hazop.shell import api_results
        ids = list(args.get("node_ids") or [])
        if len(ids) != 1:
            return _refused("한 번에 한 구간씩 분석합니다. 여러 구간은 ⑤ 분석 결과의 '전체 분석'으로 하세요.")
        a = {"scope": "node", "node_id": ids[0]}
        cells = [c for c in args.get("cell_ids") or [] if isinstance(c, str)]
        if len(cells) == 1:
            a = {"scope": "cell", "node_id": ids[0], "deviation_id": cells[0].split("/")[-1]}
        out = api_results._run(self.engine, a)
        job = out.get("job")
        if job and self.record is not None:
            if self.watch:
                t = threading.Thread(target=self.watch_job, args=(job, call, ids), daemon=True)
                self.watchers.append(t)
                t.start()
        return _ok("구간 %s의 AI 분석을 시작했습니다(호출 %d회). 진행은 ⑤ 분석 결과에 보입니다." % (ids[0], out.get("calls") or 0),
                   topics=["results.run"])

    def watch_job(self, job, call, targets, poll=1.0, timeout=6 * 3600):
        """엔진 작업 하나가 끝나기를 기다려 끝난 결과를 기록에 남긴다(done | failed). 엔진이 모르는 작업이면 남기지 않는다."""
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            state = ((getattr(self.engine, "_jobs", None) or {}).get(job) or {}).get("state")
            if state is None:
                return None
            if state != "running":
                last = (getattr(getattr(self.engine, "analysis", None), "last", None) or {}) if call.action == "analysis.run" else {}
                failed = state != "done" or bool(isinstance(last, dict) and (last.get("failed") or last.get("halted")))
                error = None
                if failed:
                    error = "작업이 %s(으)로 끝남" % {"stopped": "중지", "failed": "실패"}.get(state, state)
                    if isinstance(last, dict) and last.get("failed"):
                        error += " · 실패 칸 %s" % last.get("failed")
                return self.record(call, "failed" if failed else "done", error, targets)
            time.sleep(poll)
        return None

    def result(self, cmd):
        def fn(args, call):
            from hazop.study import result_commands
            out = A.result_executors(self.pg_fn(), result_commands.execute)["results." + ("edit" if cmd == "edit_entry" else cmd)](args, call)
            if not (isinstance(out, dict) and out.get("ok") is True):
                return out
            where = "구간 %s 편차 %s 항목 %s" % (args.get("node_id"), args.get("deviation_id"), args.get("entry_id"))
            if cmd == "set_status":
                text = "%s을(를) %s(으)로 판정했습니다." % (where, A.STATUS_LABELS.get(args.get("status"), args.get("status")))
            else:
                text = "%s의 내용을 고쳤습니다(판정 '수정')." % where
            return dict(out, message=text, topics=["results"])
        return fn

    def excel(self, args, call):
        from hazop.shell import api_results
        proxy = _AutoSave(self.engine, self._exports())
        out = api_results._export_excel(proxy, {})
        if out.get("cancelled"):
            return _refused("저장하지 못했습니다.")
        rows = out.get("rows")
        count = " · 행 %d개" % rows if isinstance(rows, int) else ""
        return _ok("Excel로 내보냈습니다: %s%s (작업 루트의 output/exports)." % (out.get("path"), count))

    def ie_bundle(self, args, call):
        from hazop.shell import api_results
        proxy = _AutoSave(self.engine, self._exports())
        out = api_results._export_ie(proxy, {})
        if out.get("cancelled"):
            return _refused("저장하지 못했습니다.")
        cands = out.get("candidates")
        count = " · 후보 %d건" % (len(cands) if isinstance(cands, list) else cands) if isinstance(cands, (int, list)) else ""
        return _ok("초기사건 인계 묶음을 내보냈습니다: %s%s (작업 루트의 output/exports)." % (out.get("path"), count))

    # ---- ①·②
    def extract(self, args, call):
        rid = args.get("registration_id")
        reg = (self.regs_fn() if self.regs_fn else {}).get(rid) or {}
        path = reg.get("path")
        if not path:
            return _refused("지금 프로젝트에 없는 등록 자료", target=str(rid))
        again = call.action == "register.reextract"
        if not again and reg.get("has_result"):         # 계획 뒤에 결과가 생겼으면 확인 없이 덮지 않는다
            return _refused("이미 추출 결과가 있는 자료입니다(다시 추출은 확인을 받습니다).", target=str(rid))
        with self._lock:
            if path in self._extracting:
                return _refused("이 자료의 추출 작업이 이미 돌고 있습니다.", "busy", str(rid))
            self._extracting.add(path)
        record = self.record

        def work(progress):
            from hazop.app import data
            try:
                progress("추출·그래프", 1, 1)
                out = data.extract_and_graph(path)
                result = {"pages": len(out.get("pages") or [out])}
            except Exception as exc:
                if record is not None:
                    record(call, "failed", "%s: %s" % (type(exc).__name__, str(exc)[:200]), [rid])
                raise
            finally:
                with self._lock:
                    self._extracting.discard(path)
            if record is not None:
                record(call, "done", None, [rid])
            return result
        try:
            job = self.engine.start_job(("다시 추출: %s" if again else "추출: %s") % rid, work, kind="register")
        except Exception:
            with self._lock:
                self._extracting.discard(path)
            raise
        return _ok("%s %s을 시작했습니다(작업 %s). 끝나면 도면 목록이 새로 고쳐집니다." % (rid, "다시 추출" if again else "추출", job))

    def sheet_confirm(self, args, call):
        from hazop.shell import api_drawings
        gid = args.get("graph_id")
        basis = call.basis or {}
        if not basis.get("fingerprint"):
            return _refused("확인 상자에서 본 쪽의 지문이 없어 확정하지 않았습니다.", "stale", str(gid))
        # 계획 때(사람이 확인 상자에서 본) 지문과 판을 그대로 넘긴다. 그 사이 쪽이 바뀌었으면 엔진이 stale로 거절한다
        out = api_drawings._sheet_command("confirm")(self.engine, {"graph_id": gid, "ver": basis["fingerprint"], "rev": basis.get("rev") or 0})
        name = self.engine.graph_names().get(gid) or gid
        return _ok("도면 %s 쪽을 확정했습니다." % name if out.get("changed") else "도면 %s은(는) 이미 확정한 쪽입니다." % name)

    def dexpi(self, args, call):
        from hazop.shell import api_drawings
        proxy = _AutoSave(self.engine, self._exports())
        out = api_drawings._export(proxy, {"graph_ids": list(args.get("graph_ids") or [])})
        if out.get("cancelled"):
            return _refused("덮어쓸 파일이 있어 내보내지 않았습니다." if out.get("overwrite_refused") else "내보내지 못했습니다.")
        done, skipped = out.get("drawings") or [], out.get("not_exported") or []
        tail = " · 확정 안 된 쪽 %d장은 뺐습니다" % len(skipped) if skipped else ""
        return _ok("DEXPI로 내보냈습니다: 도면 %d장, 폴더 %s (작업 루트의 output/exports)%s." % (len(done), out.get("folder"), tail))


# ================================================================ 표시 동작 풀기

def _sheet_id(raw, names):
    """모델이 적은 도면(graph_id, 추출 이름, 도면 번호 일부) -> graph_id 또는 None. 여럿이 맞으면 None(넘겨짚지 않는다)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    if raw in names:
        return raw
    low = raw.lower()
    exact = [g for g, n in names.items() if str(n).lower() == low]
    if len(exact) == 1:
        return exact[0]
    part = [g for g, n in names.items() if low in str(n).lower() or low in g.lower()]
    return part[0] if len(part) == 1 else None


def _resolve(pg, ids):
    """구성요소 ID 또는 태그(대소문자 무시) -> (프로젝트 ID 목록, 못 찾은 것 목록)."""
    by_id = {n.get("entity_id"): n for n in pg.get("nodes") or [] if n.get("entity_id")}
    by_tag = {}
    for eid, n in by_id.items():
        tag = str(n.get("tag") or "").strip().lower()
        if tag:
            by_tag.setdefault(tag, []).append(eid)
    found, missing = [], []
    for raw in ids or []:
        if not isinstance(raw, str):
            continue
        hits = [raw] if raw in by_id else by_tag.get(raw.strip().lower()) or []
        if hits:
            found += [h for h in hits if h not in found]
        else:
            missing.append(raw)
    labels = [str(by_id[i].get("tag") or i) for i in found]
    return found, missing, labels


def _names_text(labels, n=5):
    labels = list(dict.fromkeys(labels))
    return ", ".join(labels[:n]) + (" 외 %d개" % (len(labels) - n) if len(labels) > n else "")


def display_item(action, args, pg, names, node_ids_fn=lambda: set()):
    """표시 동작 하나 -> 웹이 그대로 따를 항목 {op, ok, text, sheet?, ids?(도면 안 local_id), marks?, panel?, node_id?, cell?, layer?, on?}.
    op: show(도면 열고 표시·확대) · open(도면만 열기) · fit · panel · layer · none(보일 수 없음, text에 까닭)."""
    from hazop.chat import card as cardmod
    from hazop.chat import view as chatview
    if action in ("show", "select"):
        sheet = _sheet_id(args.get("sheet"), names) if args.get("sheet") else None
        if args.get("sheet") and sheet is None:
            return {"op": "none", "ok": False, "text": "도면을 찾지 못했습니다: %s" % _short(args.get("sheet"))}
        ids = args.get("ids") or []
        if not ids:
            if sheet:
                return {"op": "open", "ok": True, "sheet": sheet, "text": "도면 %s을(를) 열었습니다." % names.get(sheet, sheet)}
            return {"op": "none", "ok": False, "text": "보일 대상이 없습니다."}
        found, missing, labels = _resolve(pg, ids)
        groups = chatview.split_by_sheet(pg, found)
        if not groups:
            return {"op": "none", "ok": False, "text": "도면에서 찾지 못했습니다: %s" % _names_text(missing or ids)}
        target = sheet if sheet in groups else next(iter(groups))
        style = args.get("style") if args.get("style") in cardmod.STYLES else "focus"
        marks = {g: [{"op": "mark", "groups": [{"ids": l[:MAX_DISPLAY_IDS], "style": style, "label": None}],
                      "dim_others": action == "show", "center": False}] for g, l in groups.items()}
        verb = "골랐습니다" if action == "select" else "보였습니다"
        text = "도면 %s에서 %s을(를) %s." % (names.get(target, target), _names_text(labels), verb)
        if len(groups) > 1:
            text += " 다른 도면 %d장에도 있습니다." % (len(groups) - 1)
        if missing:
            text += " 찾지 못한 것: %s." % _names_text(missing)
        return {"op": "show", "ok": True, "sheet": target, "ids": groups[target][:MAX_DISPLAY_IDS], "marks": marks, "text": text}
    if action == "fit":
        sheet = _sheet_id(args.get("sheet"), names) if args.get("sheet") else None
        if args.get("sheet") and sheet is None:
            return {"op": "none", "ok": False, "text": "도면을 찾지 못했습니다: %s" % _short(args.get("sheet"))}
        return {"op": "fit", "ok": True, "sheet": sheet, "text": "도면 전체가 보이게 맞췄습니다."}
    if action == "layer":
        layer = LAYERS.get(str(args.get("name") or "").strip().lower())
        if layer is None:
            return {"op": "none", "ok": False, "text": "모르는 층입니다(기호·배관·태그 가운데 하나)."}
        on = args.get("on") if isinstance(args.get("on"), bool) else True
        return {"op": "layer", "ok": True, "layer": layer, "on": on,
                "text": "%s 층을 %s." % (LAYER_NAMES[layer], "켰습니다" if on else "껐습니다")}
    if action == "goto":
        raw = str(args.get("target") or "").strip()
        if raw.lower() in ("③", "kg", "knowledge_graph", "지식그래프"):
            return {"op": "none", "ok": False, "text": "지식그래프 화면은 아직 없습니다."}
        panel = raw.lower() if raw.lower() in PANELS else PANEL_ALIASES.get(raw)
        if panel is None:
            return {"op": "none", "ok": False, "text": "갈 곳을 알 수 없습니다: %s" % _short(raw)}
        ident = args.get("id")
        if panel == "drawings" and ident:
            sheet = _sheet_id(ident, names)
            if sheet is None:
                return {"op": "none", "ok": False, "text": "도면을 찾지 못했습니다: %s" % _short(ident)}
            return {"op": "open", "ok": True, "sheet": sheet, "text": "도면 %s을(를) 열었습니다." % names.get(sheet, sheet)}
        if panel == "nodes" and ident:
            if ident not in node_ids_fn():
                return {"op": "none", "ok": False, "text": "구간을 찾지 못했습니다: %s" % _short(ident)}
            return {"op": "panel", "ok": True, "panel": "nodes", "node_id": ident, "text": "구간 %s을(를) 열었습니다." % ident}
        if panel == "results" and ident and "/" in ident:
            node_id, dev = ident.split("/")[:2]
            return {"op": "panel", "ok": True, "panel": "results", "cell": [node_id, dev],
                    "text": "분석 결과에서 구간 %s 편차 %s 칸을 열었습니다." % (node_id, dev)}
        return {"op": "panel", "ok": True, "panel": panel, "text": "%s 패널을 열었습니다." % PANELS[panel]}
    return {"op": "none", "ok": False, "text": "보일 수 없는 동작입니다."}
