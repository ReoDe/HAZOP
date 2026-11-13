"""새 웹 화면의 채팅 조종기. Qt를 import하지 않는다(docs/design/app-shell-web.md §3.2·§5.2, docs/specs/chat-panel.md).

`ChatSession`(hazop/chat/session.py)은 엔진에 남는다. 이 조종기는 이전 Qt 채팅 창(hazop/app/chat_panel.py)이 지키던 규칙을 새 화면에도
그대로 지킨다. 웹은 그리기만 하고, 검사와 막기는 모두 여기서 한다.

- 답 카드는 `hazop.chat.card.build_card`가 검사한 것만 웹으로 간다(경고·출처 구분·근거 확인은 앱이 계산).
- 요금·한도: 세션이 막는 오류(HALT_KINDS)와 연결 상태는 질문 ID가 있든 없든, 답이 정상으로 온 뒤에 이어서 오든 입력을 막는다.
  채팅이 건 막힘은 연결 상태 갱신(`set_availability`)으로 풀지 않고, 사용자가 연결을 다시 확인해 정상이 됐거나(user_check) 한도 재설정
  시각이 지났을 때만 푼다.
- 질문 ID 없는 오류는 진행 중인 질문을 끝내지 않는다. 다른 질문의 오류는 버린다.
- 프로젝트가 바뀌면 대화를 끝낸다. 질문 중에 바뀌었으면 옛 도구 결과를 근거로 인정하지 않는다.
- 대화는 저장하지 않는다.

사건(`emit(name, data)`): chat.state · chat.user · chat.progress · chat.answer · chat.notice · chat.cleared.
세션 콜백은 읽기 스레드에서 오므로 안쪽 상태는 잠근다. emit은 어느 스레드에서 불러도 된다.
"""

import datetime
import logging
import threading
import time

from hazop.chat import card as cardmod
from hazop.chat import view as chatview

LOG = logging.getLogger("hazop.shell.chat")
MODELS = ("fast", "normal", "deep")
MODEL_NAME = {"fast": "빠름", "normal": "보통", "deep": "깊게"}
BLOCKING_STATES = ("limit_reached", "overage", "not_installed", "cli_unsupported", "cli_too_old", "login_required", "login_expired",
                   "disabled", "auth_mismatch", "not_ready", "tool_guard_failed", "not_subscription", "account_blocked")
VIEW_KEYS = ("stage", "sheet", "selected")


def card_to_dict(card, pg=None):
    """검사가 끝난 Card -> 웹으로 보낼 JSON 값. 칩에는 도면 안 local_id를, 경로마다 도면별 그리기 항목(marks)을 붙인다."""
    locals_ = chatview._locals(pg)[0] if pg else {}
    paths_ = []
    for i, p in enumerate(card.paths):
        chips = []
        for c in p.chips:
            hit = locals_.get(c["id"])
            chips.append(dict(c, local_id=hit[1] if hit else None))
        paths_.append({"label": p.label, "chips": chips, "sheets": [[s, n] for s, n in p.sheets], "sheet_labels": dict(p.sheet_labels),
                       "marks": chatview.marks_for_card(pg, card, path_index=i) if pg else {}})
    return {"text": card.text, "general": card.general, "no_evidence": card.no_evidence, "badges": list(card.badges),
            "refs": list(card.refs), "paths": paths_, "path_notes": list(card.path_notes),
            "warnings": [{"reason": w["reason"], "text": w["text"], "scope": w["scope"], "labels": list(w["labels"])} for w in card.warnings],
            "model_warnings": list(card.model_warnings), "dropped": card.dropped, "ungrounded": card.ungrounded,
            "notes": card.footer_notes(), "highlight_marks": chatview.marks_for_card(pg, card, path_index=None) if pg and not card.paths else {}}


class NoEnv(cardmod.CardEnv):
    """프로젝트 자료를 못 읽을 때: 아무것도 확인하지 않는다(모든 항목이 '프로젝트에 없음'으로 빠진다)."""

    def component(self, ref):
        return None

    def exists(self, kind, ident):
        return False

    def describe(self, ident):
        return None

    def reasons(self, ident):
        return set()

    def path_steps(self, path_ref):
        return None


class ChatController:
    """session_factory(model, callbacks) -> 세션. env_provider() -> (CardEnv, 프로젝트 그래프) 또는 None. project_fn() -> 프로젝트 ID."""

    def __init__(self, emit, session_factory, env_provider=None, project_fn=None, model="fast", clock=time.monotonic, now=time.time):
        self._emit = emit
        self._factory = session_factory
        self._env_provider = env_provider
        self._project_fn = project_fn
        self._clock, self._now = clock, now
        self.model = model if model in MODELS else "fast"
        self._lock = threading.RLock()
        self._session = None
        self._session_project = None
        self._log = chatview.QuestionLog()
        self._busy = False
        self._qid = None
        self._last_qid = None
        self._started = 0.0
        self._halt = None
        self._avail = chatview.availability(None)
        self._prewarmed = False
        self._view = {}
        self._seq = 0

    # ------------------------------------------------------------ 보기
    def emit(self, name, data=None):
        self._emit({"t": "event", "name": name, "data": data})

    def snapshot(self):
        return {"busy": self._busy, "model": self.model, "availability": dict(self._avail)}

    def _push_state(self):
        self.emit("chat.state", self.snapshot())

    def note_view(self, **view):
        """지금 화면 문맥(단계·도면·고른 것). 질문과 함께 세션에 간다."""
        with self._lock:
            self._view.update({k: v for k, v in view.items() if k in VIEW_KEYS})

    def busy(self):
        return self._busy

    # ------------------------------------------------------------ 연결 상태(안내·막기)
    def set_availability(self, conn_state, message="", reset_text=None, user_check=False):
        """§8: 연결 상태에 따라 입력을 막고 안내만 보인다. 채팅이 건 막힘은 user_check나 재설정 시각으로만 푼다."""
        with self._lock:
            a = chatview.availability(conn_state, message, reset_text)
            if self._halt is not None:
                if a["blocked"]:
                    self._halt = None
                elif user_check or self._halt_expired():
                    self._halt = None
                else:
                    return
            self._avail = a
        self._push_state()

    def _halt_expired(self):
        at = (self._halt or {}).get("resets_at")
        return bool(at) and self._now() >= at

    def _block(self, state, message, limit):
        limit = limit or {}
        at = limit.get("resets_at")
        self._halt = {"state": state, "resets_at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else None}
        reset = limit.get("resets_at_text") or limit.get("reset_text")
        if not reset and self._halt["resets_at"]:
            reset = datetime.datetime.fromtimestamp(self._halt["resets_at"]).strftime("%m-%d %H:%M")
        self._avail = chatview.availability(state, message, reset)

    # ------------------------------------------------------------ 세션
    def _ensure_session(self):
        if self._session is None:
            cb = {"on_tool_event": self._cb_tool, "on_answer": self._cb_answer, "on_error": self._cb_error, "on_state": self._cb_state}
            try:
                self._session = self._factory(self.model, cb)
                self._session_project = self._project_fn() if self._project_fn else None
            except Exception as exc:  # noqa: BLE001 - 프로젝트가 없거나 채팅 부품이 없을 때: 앱은 계속 돈다
                self.emit("chat.notice", {"text": str(exc) or "채팅을 시작하지 못했습니다."})
                self._session = None
        return self._session

    def prewarm(self):
        """채팅 입력에 글자가 들어가기 시작할 때 프로세스를 미리 띄운다(첫 질문의 시작 비용을 숨김). 막힌 상태에서는 하지 않는다."""
        with self._lock:
            if self._avail["blocked"] or self._prewarmed:
                return
            self._prewarmed = True
            session = self._ensure_session()
        if session is not None:
            threading.Thread(target=session.start, daemon=True).start()

    def _project_changed(self):
        if self._project_fn is None or self._session is None:
            return False
        try:
            return self._project_fn() != self._session_project
        except Exception:  # noqa: BLE001 - 프로젝트를 못 알아내면 바뀌었다고 보지 않는다
            return False

    def check_project(self):
        """프로젝트가 바뀌었으면 대화를 끝낸다(세션은 만들 때의 프로젝트에 묶여 있다)."""
        with self._lock:
            if not self._project_changed():
                return False
            old, self._session = self._session, None
            self._prewarmed = False
        if old is not None:
            old.close()
        self.new_conversation()
        self.emit("chat.notice", {"text": "프로젝트가 바뀌어 대화를 새로 시작했습니다. 지금까지의 대화는 지워졌습니다."})
        return True

    # ------------------------------------------------------------ 묻기
    def ask(self, text, view=None):
        text = (text or "").strip()
        with self._lock:
            if self._halt is not None and self._halt_expired():
                self._halt = None
                self._avail = chatview.availability("ok")
            if not text or self._busy or self._avail["blocked"]:
                return False
        self.check_project()
        with self._lock:
            session = self._ensure_session()
            if session is None:
                return False
            self._busy, self._qid = True, None
            self._started = self._clock()
            self._seq += 1
            mine = self._seq
            merged = dict(self._view)
            merged.update({k: v for k, v in (view or {}).items() if k in VIEW_KEYS})
        self.emit("chat.user", {"id": mine, "text": text})
        self._push_state()
        qid = session.ask(text, merged)
        with self._lock:
            self._qid = qid
        return True

    def stop(self):
        with self._lock:
            qid = self._qid
            session = self._session
            if session is None:
                return
            self._busy, self._qid = False, None   # 세션이 보내는 cancelled 오류는 무시하되, 멈춘 질문 뒤에 오는 한도·초과 오류는 받아 입력을 막는다
            self._last_qid = qid
        session.stop()
        if qid:
            self._log.forget(qid)
        self.emit("chat.notice", {"text": "질문을 멈췄습니다. 지금까지의 대화는 지워지고 다음 질문은 새 대화로 시작합니다."})
        self._push_state()

    def new_conversation(self):
        """대화를 지우고 새로 시작한다. 세션은 다음 질문에서 새 프로세스로 뜬다."""
        with self._lock:
            session = self._session
            self._busy, self._qid = False, None
        if session is not None:
            session.stop()
        self.emit("chat.cleared")
        self._push_state()

    def set_model(self, model):
        if model not in MODELS:
            return
        with self._lock:
            self.model = model
            session = self._session
        if session is not None:
            session.set_model(model)
        self._push_state()

    def shutdown(self):
        """창·앱을 닫을 때. 진행 중 질문도 묻지 않고 끊는다."""
        with self._lock:
            session, self._session = self._session, None
        if session is not None:
            session.close()

    # ------------------------------------------------------------ 세션 콜백(읽기 스레드)
    def _mine(self, qid):
        return self._busy and (self._qid is None or not qid or qid == self._qid)

    def _cb_tool(self, qid, name, args, result):
        self._log.tool_event(qid, name, args, result)
        with self._lock:
            ok = self._mine(qid)
        if ok:
            self.emit("chat.progress", {"tools": self._log.tool_count(qid), "name": name})

    def _cb_state(self, state, message):
        if state == "renewed" and message:
            self.emit("chat.notice", {"text": message})

    def _cb_answer(self, qid, answer, tool_ids):
        with self._lock:
            if not self._mine(qid):
                return
            seconds = self._clock() - self._started
            self._busy, self._qid = False, None
            self._last_qid = qid
            stale = self._project_changed()
        try:
            env, pg = (self._env_provider() if self._env_provider else None) or (NoEnv(), {"nodes": []})
        except Exception:  # noqa: BLE001 - 자료를 못 읽어도 답 글은 보여 준다
            LOG.exception("카드 검사 자료를 읽지 못함")
            env, pg = NoEnv(), {"nodes": []}
        if stale:
            card = cardmod.build_card(answer, {}, env)
            self.emit("chat.notice", {"text": "질문하는 동안 프로젝트가 바뀌어 이 답의 근거는 확인하지 않았습니다."})
        else:
            card = cardmod.build_card(answer, tool_ids, env, path_refs=self._log.path_refs(qid), tool_names=self._log.tool_names(qid),
                                      source_kinds=self._log.source_kinds(qid))
        footer = {"tools": self._log.tool_count(qid), "model": MODEL_NAME[self.model], "seconds": round(seconds, 1),
                  "calls": [[n, a] for n, a in self._log.tool_calls(qid)][:20]}
        self._log.forget(qid)
        self.emit("chat.answer", {"id": qid, "card": card_to_dict(card, pg), "footer": footer})
        self._push_state()

    def _cb_error(self, qid, error):
        qid = qid or ""
        with self._lock:
            mine = bool(qid) and self._mine(qid)
            late = bool(qid) and not mine and qid == self._last_qid   # 답이 정상으로 온 뒤 이어지는 한도·초과 사용 오류
            if qid and not (mine or late):
                return                                                # 다른 질문의 오류
            if mine:
                self._busy, self._qid = False, None
            error = error or {}
            message = error.get("message") or "오류가 났습니다."
            state = error.get("conn_state") or error.get("error_kind")
            blocking = state in BLOCKING_STATES
            if blocking:
                self._block(state, message, error.get("limit"))
        if not blocking and not (late and error.get("error_kind") == "cancelled"):
            self.emit("chat.notice", {"text": message})   # 질문 ID가 없는 세션 오류는 진행 중인 질문을 끝내지 않는다
        self._push_state()
