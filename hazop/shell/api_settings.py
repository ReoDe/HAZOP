"""새 웹 화면의 AI 연결·모델 설정(INTENT.md §3.5, 화면 설계 docs/design/ai-connection-screens.md §3). Qt를 import하지 않는다.

- **읽기** `aisettings`: 지금 쓰는 경로(구독·API 키·연결 안 됨)와 모델, 방식별 상태, 구독 상세, API 키 목록(이름·끝 네 자리·사용 중·마지막 시험),
  분석 모델·채팅 모델 목록. **키 값은 어떤 답에도 싣지 않는다**(KeyStore.entries의 hint만, 오류 글은 apikey.mask로 가린다).
- **명령**(`aiconn.*`, 프로젝트에 묶이지 않음: 연결 설정은 프로젝트와 상관없다. `UNBOUND_PREFIXES`로 api.py의 기본 묶기에서 뺀다)
  - `check`(방식): 다시 확인. API 키는 연결 시험(GET /v1/models, 토큰·요금 없음)
  - `use`(방식, confirmed): '이 방식으로 사용'. API 키로 바꿀 때는 요금 확인(confirmed 없으면 확인 글만 돌려줌), 구독은 처음 한 번 이용 조건
  - `ack_terms`, `set_model`(방식, 모델), `add_key`(이름·저장 여부), `select_key`, `rename_key`, `remove_key`(confirmed 필수)
  - 분석이 도는 동안에는 방식·모델·사용 키 바꾸기와 키 지우기를 막는다(화면 설계 §3.7). 이름 바꾸기·키 추가·확인은 막지 않는다.
- **키 입력은 웹으로 받지 않는다.** `add_key`는 창이 꽂은 `engine.hooks["ask_api_key"]`(없으면 hazop.shell.key_dialog)로 Qt 입력 창을 열어
  Python 쪽에서만 키를 받는다. 웹·다리(bridge)·채팅·로그에는 키가 지나가지 않는다.
- 엔진 창구 `engine.ai`는 window.py의 AiAdapter이고 그 안의 `conn`(hazop.app.ai_conn.AiConnection)을 쓴다. 이전 화면 설정 창과 같은 저장
  (설정 파일의 ai_method·ai_models, KeyStore api_keys.json)이다. `adapter_status(conn)`는 AiAdapter.status가 지금 고른 방식으로 상태를 내도록
  쓰는 함수다(s-frame에 요청).
- 채팅(d-chat)용 함수: `connection(engine)`(분석 연결 상태 보기), `chat_connection(engine)`(채팅이 실제로 쓰는 방식·모델·쓸 수 있는지),
  `set_model(engine, method, model)`. 키는 채팅으로 받지 않는다.
- **실행 직전 확인**(A8 검토 R1): `run_conn(engine, kind, calls, sections)`는 분석(`analysis`)·AI 검토(`ai_review`)가 실제로 쓸 방식·모델·
  예상 비용과 판(`conn_ver`)을 낸다. 실행 카드는 이 값을 보이고 시작할 때 `conn_ver`를 보내며, 실행 명령은 `same_conn`으로 대조해 다르면
  시작하지 않는다(화면에 보인 방식과 실제 방식이 다르면 다시 묻는다). API는 사용자가 고른 경우에만 쓴다(ai_conn auto_api=False).
"""

import hashlib
import logging

from hazop.study import apikey, claude_http
from hazop.study.ai_settings import NOTICE_NO_SUBSCRIPTION

LOG = logging.getLogger("hazop.shell.api_settings")
TOPICS = ("aisettings",)
PROJECT_PREFIXES = ()
UNBOUND_PREFIXES = ("aiconn.", "aisettings.")
UNBOUND_REASONS = {"aiconn.": "AI 연결·키는 이 PC의 설정이라 프로젝트와 상관없다(A8 검토 3)",
                   "aisettings.": "연결 설정 읽기도 프로젝트와 상관없다(A8 검토 3)"}
KINDS = ("analysis", "ai_review")
# AI 검토 호출 하나의 토큰 어림(도면 조각 그림 + 질문, 실측 전). API 단가표(claude_http.PRICES)로 예상 비용을 낸다
REVIEW_CALL_USAGE = {"input_tokens": 4000, "output_tokens": 800}
NOTE_NEXT_RUN = "%s이(가) 도는 중입니다. 지금 도는 작업은 시작할 때의 연결로 끝까지 가고, 바꾼 설정은 다음 실행부터 씁니다."
METHODS = ("subscription", "api", "fixed")
MAX_NAME = 40
NONE_STATE = {"state": "none", "label": "연결 안 됨", "short": "연결 안 됨", "tone": "err", "title": "AI 연결이 없습니다",
              "guide": "AI 연결이 없어도 도면 등록·추출·구간 나누기는 스크립트로 됩니다. AI 분석을 쓰려면 Claude 구독(Claude Code 로그인)이나 API 키를 연결하세요.",
              "can_start": False}


def _api():
    from hazop.shell import api
    return api


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _conn(engine):
    conn = getattr(engine.ai, "conn", None) if engine.ai is not None else None
    if conn is None:
        raise Refused("failed", "AI 연결 설정을 쓸 수 없습니다.")
    return conn


def _views():
    from hazop.app import conn_view
    return conn_view


def _model_rows():
    return [{"id": m, "label": v["label"], "section_usd": v["section_usd"]} for m, v in claude_http.MODELS.items()]


def _masked(conn, text):
    try:
        key = conn.keys.get()
    except Exception:  # noqa: BLE001 - 키를 못 읽는 상태에서도 글은 내보낸다
        key = None
    return apikey.mask(text or "", key)


def _look(conn, method):
    cv = _views()
    st = conn.status(method)
    lk = cv.look(method, st.get("state"))
    guide = lk.guide.replace("{pct}", "").replace("{reset}", "").replace("{detail}", st.get("detail") or "").replace("{count}", "")
    return st, lk, _masked(conn, guide)


def adapter_status(conn, method=None):
    """AiAdapter.status가 돌려줄 값: 지금 고른 방식(없으면 conn.method)의 상태 + 방식·모델 이름. 키 값은 들어가지 않는다."""
    cv = _views()
    method = method or conn.method
    st, lk, guide = _look(conn, method)
    model = conn.model(method)
    return {"via": method, "method_name": cv.METHOD_NAMES.get(method, method), "method_short": cv.METHOD_SHORT.get(method, method),
            "model": model, "model_name": cv.model_name(model) if model else "", "state": st.get("state"),
            "detail": _masked(conn, st.get("detail") or ""), "plan": st.get("plan"), "limit": st.get("limit"),
            "checked_at": st.get("checked_at"), "label": lk.label, "short": lk.short, "tone": lk.tone, "title": lk.title, "guide": guide,
            "can_start": bool(lk.can_start), "chip": "%s · %s · %s" % (cv.METHOD_SHORT.get(method, method),
                                                                        cv.model_name(model, narrow=True) if model else "-", lk.short)}


def _running(engine):
    run = getattr(engine, "_analysis", None)
    return bool(run is not None and getattr(run, "running", False)) or bool(getattr(_conn(engine), "running", False))


def view(engine):
    """설정 패널이 읽는 전부. 연결 창구가 없으면 available False와 안내."""
    try:
        conn = _conn(engine)
    except Refused:
        return {"available": False, "current": dict(NONE_STATE, via=None, method_name="연결 안 됨", model=None, model_name="", chip="연결 안 됨"),
                "reason": "AI 연결 설정을 쓸 수 없습니다."}
    cv = _views()
    methods = []
    for m in conn.methods():
        st, lk, _g = _look(conn, m)
        methods.append({"method": m, "name": cv.METHOD_NAMES.get(m, m), "cost": cv.METHOD_COST.get(m, ""), "state": st.get("state"),
                        "label": lk.label, "tone": lk.tone, "in_use": m == conn.method})
    out = {"available": True, "current": adapter_status(conn), "methods": methods, "chosen": conn.is_chosen(), "running": _running(engine),
           "models": _model_rows(), "chat": {"model": engine.settings.get("chat_model") or "fast",
                                             "models": [{"id": "fast", "label": "빠름(기본)"}, {"id": "normal", "label": "보통"}, {"id": "deep", "label": "깊게"}],
                                             "via": "subscription"}}
    if "subscription" in conn.methods():
        st, lk, guide = _look(conn, "subscription")
        out["subscription"] = {"state": st.get("state"), "label": lk.label, "tone": lk.tone, "title": lk.title, "guide": guide,
                               "can_start": bool(lk.can_start), "plan": cv.plan_name(st.get("plan")), "checked_at": st.get("checked_at"),
                               "detail": _masked(conn, st.get("detail") or ""), "model": conn.model("subscription"),
                               "terms_acked": conn.terms_acked(), "cost": cv.METHOD_COST["subscription"]}
        line, _say, warn = cv.usage_lines(st.get("limit"))[0]          # 5시간·주간 한도와 재설정 시각(받은 창만, 근거 없는 '여유' 말 없음)
        out["subscription"].update(usage=line, usage_warn=warn, can_locate=st.get("state") == "not_installed",
                                   cli_set=bool(conn.prefs.cli_path))
    if "api" in conn.methods():
        st, lk, guide = _look(conn, "api")
        keys = []
        for e in conn.keys.entries():
            t = e.get("last_test") or {}
            keys.append({"id": e["id"], "name": e["name"], "hint": "…" + (e.get("hint") or "")[-4:] if len(e.get("hint") or "") > 4 else "…",
                         "active": bool(e.get("active")), "persisted": bool(e.get("persisted")),
                         "last_test": {"at": t.get("at"), "ok": bool(t.get("ok")), "model": t.get("model")} if t else None})
        model = conn.model("api")
        out["api"] = {"state": st.get("state"), "label": lk.label, "tone": lk.tone, "title": lk.title, "guide": guide,
                      "can_start": bool(lk.can_start), "detail": _masked(conn, st.get("detail") or ""), "keys": keys, "model": model,
                      "section_usd": claude_http.MODELS[model]["section_usd"], "cost": cv.METHOD_COST["api"],
                      "load_error": bool(getattr(conn.keys, "load_error", None)),
                      "load_error_text": _masked(conn, getattr(conn.keys, "load_error", None) or "")[:200]}
    if getattr(conn.prefs, "bad_models", False):
        out["settings_warning"] = "설정 파일의 AI 모델 값을 읽지 못해 기본 모델로 읽었습니다. 모델을 다시 고르면 고쳐 저장합니다."
    if not conn.is_chosen() and not conn.can_start(conn.method) and "api" in conn.methods() and conn.keys.get() is not None:
        out["advice"] = NOTICE_NO_SUBSCRIPTION
    busy = _busy_others(engine)
    if busy:
        out["busy_note"] = NOTE_NEXT_RUN % busy
    return out


def _busy_others(engine):
    """분석 말고 도는 AI 작업(AI 검토, 채팅 답) 이름. 분석은 _running이 막는다."""
    names = []
    try:
        if "ai_review" in engine.running_kinds():
            names.append("AI 검토")
    except AttributeError:
        pass
    chat = getattr(engine, "chat", None)
    try:
        if chat is not None and chat.busy():
            names.append("채팅 답")
    except Exception:  # noqa: BLE001 - 채팅 상태를 못 읽어도 설정은 보인다
        pass
    return "·".join(names)


def _conn_ver(via, model, key_id):
    return hashlib.sha256(("%s|%s|%s" % (via, model, key_id or "-")).encode("utf-8")).hexdigest()[:12]


def run_conn(engine, kind, calls=0, sections=0, method=None):
    """실행 카드가 보일 '실제로 쓸 연결'(키 값 없음). kind: analysis(고른 방식) | ai_review(구독으로만 돈다).
    method: 이번 실행만 다른 방식(분석의 'API 키로 이어서', 사용자가 그때 고름). 쓸 수 없는 방식이면 Refused. 고정 응답(시험)은 설정에서
    고른 경우에만 쓴다(이번 실행만으로는 고를 수 없다).
    → {kind, via, method_name, model, model_name, can_start, label, guide, paid, usd, cost_text, confirm_text, test, this_run, conn_ver}."""
    cv = _views()
    try:
        conn = _conn(engine)
    except Refused:
        ai = engine.ai
        if ai is not None and hasattr(ai, "status"):   # conn 없는 창구(시험 대역·다른 엔진): 그 창구의 상태를 그대로 보인다
            st = ai.status() or {}
            via, model = st.get("via"), st.get("model")
            return dict(kind=kind, via=via, method_name=st.get("method_name") or via or "AI 연결", model=model, model_name=st.get("model_name") or "",
                        can_start=bool(st.get("can_start")), label=st.get("label") or "", guide=st.get("guide") or "", paid=via == "api", usd=None,
                        cost_text="", conn_ver=_conn_ver(via, model, None))
        return dict(kind=kind, via=None, method_name="연결 안 됨", model=None, model_name="", can_start=False, label=NONE_STATE["label"],
                    guide=NONE_STATE["guide"], paid=False, usd=None, cost_text="AI 연결이 없습니다.", conn_ver=_conn_ver(None, None, None))
    if kind == "ai_review":
        via = "subscription"
    elif method is not None:
        if method not in conn.methods() or method == "fixed" and conn.method != "fixed":
            raise Refused("bad_args", "이번 실행에 쓸 수 없는 연결 방식입니다.")
        via = method
    else:
        via = conn.method
    if via not in conn.methods():
        via = conn.method
    st, lk, guide = _look(conn, via)
    model = conn.model(via)
    paid = via == "api"
    key = conn.keys.active() if paid else None
    usd = None
    if paid and model:
        if kind == "analysis":
            usd = round(max(0, int(sections)) * claude_http.MODELS[model]["section_usd"], 2)
        else:
            usd = round(max(0, int(calls)) * claude_http.cost_usd(REVIEW_CALL_USAGE, model), 2)
    confirm_text = ""
    if paid:
        what = "구간 %d개" % sections if kind == "analysis" else "호출 %d회 어림" % calls
        cost_text = "호출마다 요금, 약 $%.2f(%s)" % (usd or 0, what)      # 앞에 방식 이름(API 키)은 카드가 붙인다
        confirm_text = "API 키(%s)로 호출마다 요금이 나갑니다. 예상 약 $%.2f(%s, %s 기준 어림). 확인하고 시작할까요?" % (
            (key or {}).get("name") or "키", usd or 0, what, cv.model_name(model) if model else "-")
    elif via == "subscription":
        cost_text = "Claude 구독 한도를 씁니다(건별 요금 없음)"
    elif via == "fixed":
        cost_text = "시험용 고정 응답 · AI를 부르지 않습니다. 결과는 시험 파일에 저장해 실제 결과에 섞지 않습니다"
    else:
        cost_text = ""
    if kind == "ai_review" and conn.method == "api":
        cost_text += " · AI 검토는 분석 연결(API 키)과 상관없이 구독으로만 돕니다"
    this_run = via != conn.method
    if this_run:
        cost_text += " · 이번 실행만"
    return {"kind": kind, "via": via, "method_name": cv.METHOD_NAMES.get(via, via), "model": model,
            "model_name": cv.model_name(model) if model else "", "can_start": bool(lk.can_start), "label": lk.label, "guide": guide,
            "paid": paid, "usd": usd, "cost_text": cost_text, "confirm_text": confirm_text, "test": via == "fixed", "this_run": this_run,
            "conn_ver": _conn_ver(via, model, key and key.get("id"))}


def run_lines(conn):
    """확인 상자 줄(채팅의 분석 실행 확인 등, [{label, after}]): 실제로 쓸 방식·모델·비용. 과금이면 요금 확인 글을 한 줄 더한다. 키 값 없음."""
    if not conn:
        return [{"label": "연결", "after": "AI 연결이 없습니다"}]
    rows = [{"label": "연결", "after": "%s · %s · %s" % (conn.get("method_name") or "-", conn.get("model_name") or "-", conn.get("cost_text") or "")}]
    if not conn.get("can_start"):
        rows.append({"label": "연결 상태", "after": "%s. %s" % (conn.get("label") or "쓸 수 없음", conn.get("guide") or "")})
    if conn.get("paid"):
        rows.append({"label": "요금", "after": conn.get("confirm_text") or "호출마다 요금이 나갑니다"})
    return rows


def same_conn(engine, kind, conn_ver, method=None):
    """실행 직전: 화면이 본 판(conn_ver)과 지금 실제 연결이 같은지. 다르면 Refused('conn_changed')."""
    now = run_conn(engine, kind, **({"method": method} if method else {}))
    if not conn_ver or conn_ver != now["conn_ver"]:
        raise Refused("conn_changed", "AI 연결이 화면에 보인 것과 달라졌습니다(지금: %s · %s). 실행하지 않았습니다. 확인 상자를 다시 보고 시작하세요."
                      % (now["method_name"], now["model_name"] or "-"))
    return now


def chat_connection(engine):
    """채팅 창 아래 줄용: 채팅이 실제로 쓰는 방식(구독)·채팅 모델·쓸 수 있는지. 분석 연결 칩과 따로 본다. 키 값 없음."""
    from hazop.shell import chat as chat_mod
    model = engine.settings.get("chat_model") or "fast"
    out = {"via": "subscription", "method_name": "Claude 구독", "model": model, "model_name": chat_mod.MODEL_NAME.get(model, model)}
    try:
        conn = _conn(engine)
        _st, lk, guide = _look(conn, "subscription")
        out.update(label=lk.label, short=lk.short, tone=lk.tone, can_start=bool(lk.can_start), guide=guide)
    except Refused:
        out.update(label=NONE_STATE["label"], short=NONE_STATE["short"], tone="err", can_start=False, guide=NONE_STATE["guide"])
    chat = getattr(engine, "chat", None)
    try:
        avail = chat.snapshot().get("availability") if chat is not None else None
    except Exception:  # noqa: BLE001
        avail = None
    if avail and avail.get("blocked"):
        out.update(can_start=False, tone="warn")
    out["chip"] = "구독 · %s · %s" % (out["model_name"], out["short"])
    return out


def connection(engine):
    """채팅용: 지금 쓰는 경로·모델·상태(키 값 없음). 예외를 올리지 않는다."""
    try:
        return dict(adapter_status(_conn(engine)), ok=True)
    except Refused:
        return dict(NONE_STATE, ok=True, via=None, model=None)


def read(engine, parts, query):
    if len(parts) == 1:
        return _api()._json(view(engine))
    return None


# ---------------------------------------------------------------- 쓰기

def _guard(engine, what):
    if _running(engine):
        raise Refused("busy", "AI 분석이 돌고 있어 %s 바꿀 수 없습니다. 실행이 끝나거나 멈춘 뒤 바꾸세요." % what)


def _done(engine, out=None):
    conn = _conn(engine)
    conn.refresh()
    engine.changed("aisettings", None)
    out = dict(out or {}, view=view(engine))
    if out["view"].get("busy_note"):
        out["note"] = out["view"]["busy_note"]       # AI 검토·채팅이 도는 중에 바꾸면 막지 않고 '다음 실행부터'라고 알린다(A8 검토 R6)
    return out


def check(engine, method):
    conn = _conn(engine)
    if method not in conn.methods():
        raise Refused("bad_args", "쓸 수 없는 연결 방식입니다.")
    if method == "api" and conn.keys.get() is None:
        raise Refused("failed", "시험할 키가 없습니다. 키를 먼저 추가하세요.")
    conn.check(method, done=lambda _st: engine.changed("aisettings", None))
    return _done(engine, {"checking": True})


def use(engine, method, confirmed=False):
    """'이 방식으로 사용'. API 키는 요금 확인(confirmed), 구독은 처음 한 번 이용 조건(need_terms)."""
    conn = _conn(engine)
    if method not in conn.methods():
        raise Refused("bad_args", "쓸 수 없는 연결 방식입니다.")
    _guard(engine, "연결 방식을")
    if method == conn.method and conn.is_chosen():
        return _done(engine, {"changed": False})
    if method == "api" and not confirmed:
        cv = _views()
        model = conn.model("api")
        return {"need_confirm": True, "text": "API 키로 바꾸면 호출마다 요금이 나갑니다. 지금 모델(%s)로 검토구간 1개를 분석하면 약 $%.2f입니다. 바꿀까요?"
                % (cv.model_name(model), claude_http.MODELS[model]["section_usd"])}
    if method == "subscription" and not conn.terms_acked():
        return {"need_terms": True}
    conn.prefs.choose(method)
    conn.changed.emit()
    conn.check(method, done=lambda _st: engine.changed("aisettings", None))
    return _done(engine, {"changed": True})


def ack_terms(engine):
    _conn(engine).prefs.ack_terms()
    return _done(engine)


def set_model(engine, method, model):
    """분석 모델 바꾸기(구독·API 따로). 채팅에서도 부른다. → {ok, ...} 또는 {ok: False, code, message}."""
    try:
        conn = _conn(engine)
        if method not in ("subscription", "api") or method not in conn.methods():
            raise Refused("bad_args", "모델을 고를 수 없는 연결 방식입니다.")
        if model not in claude_http.MODELS:
            raise Refused("bad_args", "고를 수 없는 모델입니다.")
        _guard(engine, "모델을")
        try:
            conn.set_model(method, model)
        except OSError as exc:
            raise Refused("failed", _masked(conn, "설정 파일에 쓰지 못했습니다(%s)." % exc)[:200])
        return dict(_done(engine, {"model": model}), ok=True)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}


def _ask_key(engine, name):
    hook = engine.hooks.get("ask_api_key")
    if hook is None:
        from hazop.shell import key_dialog
        hook = key_dialog.ask_key
    return hook(name)


def add_key(engine, name=None):
    """창의 키 입력 상자로 키를 받아 추가하고 연결 시험을 건다. → {added, key: {id, name, hint}} (키 값 없음)."""
    conn = _conn(engine)
    got = _ask_key(engine, name or "")
    if not got:
        return {"added": False}
    key_name, key, persist = got
    key = apikey.clean_key(key)
    try:
        kid = conn.keys.add(key_name, key, persist=bool(persist))
    except ValueError as exc:                       # key_problem 글(키 값 없음)
        raise Refused("bad_args", str(exc))
    except OSError as exc:
        raise Refused("failed", apikey.mask("키를 암호화해 저장하지 못했습니다(%s)." % exc, key)[:200])
    finally:
        key = None
    conn.refresh()
    conn.check("api", done=lambda _st: engine.changed("aisettings", None))
    e = next((x for x in conn.keys.entries() if x["id"] == kid), {})
    return _done(engine, {"added": True, "key": {"id": kid, "name": e.get("name"), "hint": "…" + (e.get("hint") or "")[-4:]}})


def _keyop(engine, fn, what=None):
    conn = _conn(engine)
    if what:
        _guard(engine, what)
    try:
        fn(conn.keys)
    except KeyError:
        raise Refused("not_found", "없는 키입니다.")
    except ValueError as exc:
        raise Refused("bad_args", str(exc)[:120])
    except OSError as exc:
        raise Refused("failed", _masked(conn, "설정 파일에 쓰지 못했습니다(%s)." % exc)[:200])
    return _done(engine)


def select_key(engine, kid):
    return _keyop(engine, lambda ks: ks.select(kid), "사용할 키를")


def rename_key(engine, kid, name):
    return _keyop(engine, lambda ks: ks.rename(kid, name))


def remove_key(engine, kid, confirmed=False):
    if not confirmed:
        raise Refused("bad_args", "키를 지우려면 확인이 필요합니다.")
    return _keyop(engine, lambda ks: ks.remove(kid), "키를")


CLI_NAMES = ("claude.exe", "claude.cmd", "claude")


def _pick_cli(engine):
    hook = engine.hooks.get("pick_cli")
    if hook is None:
        from hazop.shell import key_dialog
        hook = key_dialog.pick_cli
    return hook()


def locate_cli(engine):
    """Claude Code 프로그램 위치 지정('찾지 못했을 때만' 보이는 줄). 경로는 창의 파일 상자로 Python 쪽에서만 받고 웹에는 보내지 않는다."""
    import os
    conn = _conn(engine)
    path = _pick_cli(engine)
    if not path:
        return {"set": False}
    if not os.path.isfile(path) or os.path.basename(path).lower() not in CLI_NAMES:
        raise Refused("bad_args", "Claude Code 프로그램(claude.exe)을 고르세요.")
    try:
        conn.prefs.set_cli_path(path)
    except OSError as exc:
        raise Refused("failed", "설정 파일에 쓰지 못했습니다(%s)." % str(exc)[:120])
    conn.check("subscription", done=lambda _st: engine.changed("aisettings", None))
    return _done(engine, {"set": True})


def _wrap(fn):
    def handler(engine, a):
        try:
            return fn(engine, a)
        except Refused as exc:
            raise _api().CommandError(exc.code, exc.message)
    return handler


def _h_set_model(engine, a):
    out = set_model(engine, a["method"], a["model"])
    if not out.pop("ok"):
        raise Refused(out["code"], out["message"])
    return out


def register(commands):
    api = _api()
    C, v_str, v_enum, v_bool = api.Command, api.v_str, api.v_enum, api.v_bool
    method = (v_enum(*METHODS), True)
    kid = (v_str(1, 40), True)

    def put(name, spec_, fn, doc):
        key = "aiconn." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, _wrap(fn), doc)

    put("check", {"method": method}, lambda e, a: check(e, a["method"]), "연결 다시 확인(API 키는 연결 시험, 요금 없음)")
    put("use", {"method": method, "confirmed": (v_bool(), False)}, lambda e, a: use(e, a["method"], a.get("confirmed", False)),
        "이 방식으로 사용(API 키는 요금 확인, 구독은 처음 한 번 이용 조건)")
    put("ack_terms", {}, lambda e, a: ack_terms(e), "구독 이용 조건 확인을 기록")
    put("set_model", {"method": (v_enum("subscription", "api"), True), "model": (v_enum(*claude_http.MODELS), True)}, _h_set_model, "분석 모델")
    put("add_key", {"name": (v_str(0, MAX_NAME), False)}, lambda e, a: add_key(e, a.get("name")),
        "API 키 추가(키는 창의 입력 상자로 받는다. 웹은 키를 보내지 않는다)")
    put("locate_cli", {}, lambda e, a: locate_cli(e), "Claude Code 프로그램 위치 지정(창의 파일 상자, 경로는 웹에 보내지 않음)")
    put("select_key", {"key_id": kid}, lambda e, a: select_key(e, a["key_id"]), "사용할 키")
    put("rename_key", {"key_id": kid, "name": (v_str(1, MAX_NAME), True)}, lambda e, a: rename_key(e, a["key_id"], a["name"]), "키 이름 바꾸기")
    put("remove_key", {"key_id": kid, "confirmed": (v_bool(), True)}, lambda e, a: remove_key(e, a["key_id"], a["confirmed"]),
        "키 지우기(확인 필수, 이 PC에 저장한 암호화 사본도 지움)")
