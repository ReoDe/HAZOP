"""AI 연결 상태 보관(주 창 하나에 하나). 연결 칩·설정 창·⑤ 실행 흐름이 같은 값을 본다.

방식별 마지막 ConnStatus({via, state, detail, plan, limit, checked_at}, 기획서/AI연결-구독제.md §5.1)를 들고,
확인(check())은 작업 스레드에서 돌린다. API 키 상태는 KeyStore의 마지막 연결 시험에서 읽는다(시작할 때는 네트워크 없음).
바뀔 때마다 changed를 낸다. 앱이 정한 기본 방식이 바뀌면 notice(토스트 문구)를 한 번 낸다(화면 설계 §4).

⑤ 실행 흐름이 쓰는 곳: set_status(실행 중 받은 상태), set_running·cancel_handler(설정 창 잠금 띠의 '실행 취소'),
set_run_override('API 키로 이어서'는 이번 실행만, D4), make_client(), can_start().
"""

import os

from PySide6.QtCore import QObject, Signal

from hazop.app import conn_view
from hazop.app.widgets import TaskRunner
from hazop.study import ai_settings, claude_cli, claude_http, providers
from hazop.study.apikey import mask
from hazop.study.nodes import now_utc


NOTICE_NO_SUBSCRIPTION = ai_settings.NOTICE_NO_SUBSCRIPTION


def _status(via, state, detail="", **kw):
    return dict({"via": via, "state": state, "detail": detail, "plan": None, "limit": None,
                 "checked_at": claude_cli.now_kst()}, **kw)


class AiConnection(QObject):
    changed = Signal()
    notice = Signal(str)

    def __init__(self, prefs, keys, debug=False, cli_factory=None, opener=None, parent=None, auto_api=True):
        """cli_factory(cli_path, **설정) -> 구독 클라이언트(check·analyze·cancel). 확인과 실행이 같은 것을 쓴다.
        시험과 사용자 시나리오 검사(--_app)는 가짜 CLI를 주입한다(설정 파일·화면에서는 바꿀 수 없음).
        opener: API 연결 시험의 전송 함수(claude_http, 시험용 대역).
        auto_api: 사용자가 방식을 고른 적이 없을 때 구독을 쓸 수 없으면 앱이 API 키로 넘어가는지(이전 화면 동작).
        새 화면은 False로 만든다: 과금 경로는 사용자가 고른 경우에만 쓰고, 구독을 쓸 수 없으면 '연결 안 됨'으로 두고 알린다(INTENT §3.5)."""
        super().__init__(parent)
        self.auto_api = bool(auto_api)
        self.opener = opener
        self.prefs = prefs
        self.keys = keys
        self.debug = debug
        self.cli_factory = cli_factory or (lambda path, **kw: claude_cli.ClaudeCliClient(cli_path=path, **kw))
        self.tasks = TaskRunner(self)
        self._status = {m: _status(m, "unchecked", checked_at=None) for m in self.methods()}
        self._api_override = None  # 실행 중 받은 API 상태. 키·모델·시험 결과가 바뀌면 버린다
        self._limits = {}          # 구독 한도 창별 마지막 값(five_hour·seven_day 등). 받은 창만 있다
        self._auto = self.prefs.auto_method or ("subscription" if "subscription" in self.methods() else "api")
        self.running = False
        self.progress = ""
        self.cancel_handler = None
        self.run_override = None
        self.fixed_match = None  # () -> (맞는 칸, 전체 칸) 또는 None. ⑤ 화면이 지금 검토구간으로 센다

    # ------------------------------------------------------------ 방식
    def methods(self):
        """목록에 보일 방식. 배포본은 API만, 고정 응답은 디버그 실행에서만."""
        return tuple(m for m in providers.available_methods() if m != "fixed" or self.debug)

    @property
    def method(self):
        """지금 쓰는 방식: 사용자가 고른 것, 없으면 앱이 정한 것."""
        chosen = self.prefs.chosen_method
        if chosen in self.methods():
            return chosen
        if not self.auto_api and "subscription" in self.methods():
            return "subscription"          # 이전 화면이 기억해 둔 앱 기본값(api)도 따르지 않는다. 과금은 사용자가 고른 경우에만
        return self._auto if self._auto in self.methods() else self.methods()[0]

    def is_chosen(self):
        return self.prefs.chosen_method in self.methods()

    def use(self, method):
        """'이 방식으로 사용'. 고른 값을 저장하고 바로 다시 확인한다."""
        self.prefs.choose(method)
        self.changed.emit()
        self.check(method)

    def model(self, method=None):
        method = method or self.method
        if method == "api":
            return self.keys.model
        return self.prefs.model(method)

    def set_model(self, method, model):
        if method == "api":
            self.keys.set_model(model)
        else:
            self.prefs.set_model(method, model)
        self.changed.emit()

    # ------------------------------------------------------------ 상태
    def status(self, method=None):
        method = method or self.method
        if method == "api":
            derived = conn_view.api_status(self.keys)
            o = self._api_override
            if o and o[0] == self._api_key():
                return o[1]
            return derived
        return self._status.get(method) or _status(method, "unchecked", checked_at=None)

    def _api_key(self):
        e = self.keys.active()
        return (e and e["id"], self.keys.model, e and repr(e.get("last_test")))

    def set_status(self, status):
        """실행 흐름이 받은 상태를 반영한다(예: 호출 중 로그인이 풀림 → login_required)."""
        via = status.get("via") or self.method
        status = dict(_status(via, "unchecked"), **status)
        self._keep_limit(status)
        if via == "api":
            self._api_override = (self._api_key(), status)
        else:
            self._status[via] = status
        self.changed.emit()

    def _keep_limit(self, status):
        limit = status.get("limit")
        if status.get("via") == "subscription" and isinstance(limit, dict) and limit.get("window"):
            self._limits[limit["window"]] = dict(limit)

    def limits(self):
        """구독 한도 창별 마지막 값 {창: limit}(받은 창만)."""
        return dict(self._limits)

    def refresh(self):
        """설정 창이 키·모델을 바꾼 뒤: 실행 중 받은 API 상태를 버리고 다시 그리게 한다."""
        self._api_override = None
        self.changed.emit()

    def look(self, method=None):
        method = method or self.method
        return conn_view.look(method, self.status(method)["state"])

    def can_start(self, method=None):
        return self.look(method).can_start

    # ------------------------------------------------------------ 확인
    def _check_fn(self, method):
        if method == "subscription":
            client = self.cli_factory(self.prefs.cli_path)
            return client.check
        if method == "fixed":
            folder = self.prefs.fixed_dir
            if not folder:
                return lambda: _status("fixed", "no_folder", claude_cli.MESSAGES.get("no_folder", ""))
            return providers.FixedCellsClient(folder).check
        raise ValueError(method)

    def _test_api(self, done):
        """API 키 연결 시험(GET /v1/models, 토큰 비용 없음). 키가 없으면 다시 읽기만 한다."""
        e, key, model = self.keys.active(), self.keys.get(), self.keys.model
        if not key:
            self.refresh()
            if done:
                done(self.status("api"))
            return
        client = claude_http.ClaudeHttpClient(lambda: key, model=model, opener=self.opener)
        self._api_override = (self._api_key(), _status("api", "checking"))
        self.changed.emit()

        def finish(ok, message):
            if e["id"] in {x["id"] for x in self.keys.entries()}:
                try:
                    self.keys.record_test(e["id"], ok, message, now_utc(), model)
                except OSError:
                    pass  # 기록 실패는 표시만 못 남길 뿐 키에는 영향 없음
            self.refresh()
            if done:
                done(self.status("api"))

        self.tasks.run("API 연결 시험", client.test_connection, lambda r: finish(r["ok"], r["message"]),
                       lambda err: finish(False, mask("연결 시험 중 오류: %s" % err, key)))

    def check(self, method=None, done=None):
        """method의 연결을 다시 확인한다. API 키는 연결 시험(GET, 토큰·요금 없음)을 한다.
        done(status)는 확인이 끝난 뒤 UI 스레드에서 부른다."""
        method = method or self.method
        if method == "api":
            self._test_api(done)
            return
        fn = self._check_fn(method)
        prev = self._status.get(method) or {}
        self._status[method] = dict(_status(method, "checking"), plan=prev.get("plan"), limit=prev.get("limit"))
        self.changed.emit()

        def finish(status):
            if not isinstance(status, dict) or "state" not in status:
                status = _status(method, "error", "확인 결과를 읽지 못함")
            self._status[method] = dict(_status(method, "unchecked"), **status)
            self._keep_limit(self._status[method])
            self.changed.emit()
            if done:
                done(self._status[method])

        self.tasks.run("AI 연결 확인", fn, finish, lambda err: finish(_status(method, "error", err)))

    def start(self):
        """앱 시작: 지금 방식만 확인한다(구독은 check(), API 키는 '확인 안 함' 그대로, 화면 설계 §2.4).
        고른 방식이 없는 개발자 PC는 구독을 확인해 기본 방식을 정한다."""
        if not self.is_chosen() and "subscription" in self.methods():
            # 앱이 정하는 기본 방식은 여기서만 다시 정한다. 실행 전 확인·띠의 다시 확인에서 정하면 한도 한 번에 API 키로 넘어간다
            self.check("subscription", done=lambda _s: self.is_chosen() or self._decide_auto())
        elif self.method != "api":
            self.check(self.method)
        else:
            self.changed.emit()

    def _decide_auto(self):
        has_key = self.keys.get() is not None
        if not self.auto_api:
            self.changed.emit()
            if has_key and not self.can_start("subscription"):
                self.notice.emit(NOTICE_NO_SUBSCRIPTION)
            return
        new = ai_settings.auto_method(self._status["subscription"]["state"], has_key, self.methods())
        text = ai_settings.auto_notice(self.prefs.auto_method, new, has_key)
        self._auto = new
        self.prefs.remember_auto(new)
        self.changed.emit()
        if text:
            self.notice.emit(text)

    def terms_acked(self):
        return bool(self.prefs.terms_ack_at)

    # ------------------------------------------------------------ 실행 흐름 연결
    def set_running(self, running, progress=""):
        self.running = bool(running)
        self.progress = progress if running else ""
        self.changed.emit()

    def cancel_run(self):
        if self.cancel_handler is not None:
            self.cancel_handler()

    def set_run_override(self, method):
        """'API 키로 이어서'를 돌리는 동안 칩에 '이번 실행만'을 보인다. None이면 되돌림."""
        self.run_override = method
        self.changed.emit()

    def make_client(self, method=None):
        method = method or self.method
        if method == "subscription":
            if method not in self.methods():
                raise ValueError("이 실행본에서는 쓸 수 없는 연결 방식: %r" % method)
            return self.cli_factory(self.prefs.cli_path, model=self.model(method), allow_overage=self.prefs.allow_overage)
        if method == "api":
            key = self.keys.get()  # 실행 중에 키를 추가해 사용 키가 바뀌어도 이번 실행은 시작할 때의 키로 부른다(§3.7)
            return providers.make_client(method, key_provider=lambda: key, model=self.model(method))
        return providers.make_client(method, response_dir=self.prefs.fixed_dir)

    def fixed_count(self):
        folder = self.prefs.fixed_dir
        try:
            return sum(1 for n in os.listdir(folder) if n.endswith(".json")) if folder else 0
        except OSError:
            return 0
