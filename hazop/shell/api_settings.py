"""새 웹 화면의 AI 연결·모델 설정(INTENT.md §3.5, 화면 설계 docs/design/ai-connection-screens.md §3). Qt를 import하지 않는다.

- **읽기** `aisettings`: 지금 쓰는 경로(구독·API 키·연결 안 됨)와 모델, 방식별 상태, 구독 상세, API 키 목록(이름·끝 네 자리·사용 중·마지막 시험),
  분석 모델·채팅 모델 목록. **키 값은 어떤 답에도 싣지 않는다**(KeyStore.entries의 hint만, 오류 글은 apikey.mask로 가린다).
- **명령**(`aiconn.*`, 프로젝트에 묶이지 않음)
  - `check`(방식): 다시 확인. API 키는 연결 시험(GET /v1/models, 토큰·요금 없음)
  - `use`(방식, confirmed): '이 방식으로 사용'. API 키로 바꿀 때는 요금 확인(confirmed 없으면 확인 글만 돌려줌), 구독은 처음 한 번 이용 조건
  - `ack_terms`, `set_model`(방식, 모델), `add_key`(이름·저장 여부), `select_key`, `rename_key`, `remove_key`(confirmed 필수)
  - 분석이 도는 동안에는 방식·모델·사용 키 바꾸기와 키 지우기를 막는다(화면 설계 §3.7). 이름 바꾸기·키 추가·확인은 막지 않는다.
- **키 입력은 웹으로 받지 않는다.** `add_key`는 창이 꽂은 `engine.hooks["ask_api_key"]`(없으면 hazop.shell.key_dialog)로 Qt 입력 창을 열어
  Python 쪽에서만 키를 받는다. 웹·다리(bridge)·채팅·로그에는 키가 지나가지 않는다.
- 엔진 창구 `engine.ai`는 window.py의 AiAdapter이고 그 안의 `conn`(hazop.app.ai_conn.AiConnection)을 쓴다. 이전 화면 설정 창과 같은 저장
  (설정 파일의 ai_method·ai_models, KeyStore api_keys.json)이다. `adapter_status(conn)`는 AiAdapter.status가 지금 고른 방식으로 상태를 내도록
  쓰는 함수다(s-frame에 요청).
- 채팅(d-chat)용 함수: `connection(engine)`(연결 상태 보기), `set_model(engine, method, model)`. 키는 채팅으로 받지 않는다.
"""

import logging

from hazop.study import apikey, claude_http

LOG = logging.getLogger("hazop.shell.api_settings")
TOPICS = ("aisettings",)
PROJECT_PREFIXES = ()
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
                      "load_error": bool(getattr(conn.keys, "load_error", None))}
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
    return dict(out or {}, view=view(engine))


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
    put("select_key", {"key_id": kid}, lambda e, a: select_key(e, a["key_id"]), "사용할 키")
    put("rename_key", {"key_id": kid, "name": (v_str(1, MAX_NAME), True)}, lambda e, a: rename_key(e, a["key_id"], a["name"]), "키 이름 바꾸기")
    put("remove_key", {"key_id": kid, "confirmed": (v_bool(), True)}, lambda e, a: remove_key(e, a["key_id"], a["confirmed"]),
        "키 지우기(확인 필수, 이 PC에 저장한 암호화 사본도 지움)")
