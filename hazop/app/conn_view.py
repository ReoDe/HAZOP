"""AI 연결 상태 표(디자인/AI연결-화면설계.md §2·§5·§9·§10.3, 기획서/AI연결-구독제.md §0.2). Qt 위젯 없음.

연결 칩·칩 상세 창·설정 창 상태 칸·해결 띠·실행 전 안내가 모두 이 표만 읽는다. 상태별 분기를 화면 곳곳에 두지 않는다.
상태 이름은 기술 설계 §0.2(`conn_state`) 그대로다. 같은 상태라도 방식마다 안내가 다르면 (방식, 상태) 줄이 이긴다.
"""

import collections
import datetime
from dataclasses import dataclass, replace

from hazop.study import claude_cli, claude_http

METHOD_NAMES = {"subscription": "Claude 구독", "api": "API 키", "fixed": "고정 응답(시험)"}
METHOD_SHORT = {"subscription": "구독", "api": "API 키", "fixed": "시험"}
METHOD_COST = {"subscription": "건별 요금이 없습니다. 쓴 만큼 구독 사용 한도에서 빠집니다.",
               "api": "호출마다 요금이 나갑니다. Anthropic Console에서 발급한 키가 필요합니다.",
               "fixed": "AI를 부르지 않고 저장해 둔 응답으로 칸을 채웁니다. 화면과 흐름을 시험할 때 씁니다."}

# 바탕·글자·테두리 토큰(화면 설계 §2.2)
TONES = {"plain": ("surface-2", "ink-2", "line"), "plain_strong": ("surface-2", "ink-2", "line-strong"),
         "ok": ("ok-bg", "ok", "ok"), "warn": ("warn-bg", "warn-ink", "warn-line"),
         "err": ("err-bg", "err-ink", "err-line"), "ai": ("ai-hatch-a", "ai-ink", "line-strong")}
# 시작 가능 여부: go 됨 · check_first 시작 직전에 확인 · wait 확인 끝까지 대기 · confirm 확인 받고 시작
# · retry 다시 확인 · block 막음. 실행할 수 없는 상태(retry·block·confirm)는 테두리 1.5px
STARTABLE = ("go", "check_first", "confirm")
THICK = ("retry", "block", "confirm")


@dataclass(frozen=True)
class Look:
    label: str        # 칩 넓은 형식의 상태 글자
    short: str        # 칩 좁은 형식의 상태 글자
    icon: str         # ICONS 이름
    tone: str         # TONES 이름
    start: str        # 시작 가능 여부(위 주석)
    title: str        # 해결 띠 제목
    guide: str        # 해결 띠 안내(무슨 일인지 → 무엇을 하면 되는지). {pct}·{reset}·{detail}·{count} 채움
    actions: tuple = ()   # ACTIONS 이름(해결 동작 단추)
    a11y: str = ""        # accessibleName의 상태 구절(없으면 label)

    @property
    def colors(self):
        return TONES[self.tone]

    @property
    def border(self):
        return 1.5 if self.start in THICK else 1.0

    @property
    def dashed(self):
        return self.tone == "ai"

    @property
    def can_start(self):
        return self.start in STARTABLE


_NET = "Anthropic 서버에 연결하지 못했습니다. 인터넷 연결이나 회사 프록시 설정을 확인하세요."
LOOKS = {
    "checking": Look("확인 중", "확인 중", "dots", "plain", "wait", "연결을 확인하고 있습니다",
                     "Claude Code 연결을 확인하고 있습니다."),
    "unchecked": Look("확인 안 함", "확인 안 함", "question", "plain", "check_first", "아직 확인하지 않았습니다",
                      "아직 연결을 확인하지 않았습니다. 분석을 시작할 때 먼저 확인합니다.", ("check",)),
    "ok": Look("연결됨", "연결됨", "check", "ok", "go", "연결됐습니다",
               "Claude Code에 구독 계정으로 로그인돼 있습니다. 분석은 구독 사용량에서 빠집니다.", ("check",)),
    "limit_warning": Look("한도 가까움", "한도 가까움", "clock", "warn", "go", "한도가 가까워졌습니다",
                          "구독 사용 한도가 가까워졌습니다({pct}{reset}). 큰 분석은 도중에 멈출 수 있습니다."),
    "overage_risk": Look("초과 사용 주의", "초과 주의", "clock", "warn", "confirm", "초과 사용으로 넘어갈 수 있습니다",
                         "구독 한도가 거의 찼고 초과 사용(유료)이 켜져 있습니다. 이대로 돌리면 한도를 넘은 호출에 요금이 "
                         "붙을 수 있어 분석을 시작하기 전에 한 번 더 묻습니다.", ("to_api", "check")),
    "limit_reached": Look("한도 도달", "한도", "clock", "warn", "block", "구독 사용 한도에 닿았습니다",
                          "{reset_sentence}", ("to_api", "check")),
    "disabled": Look("꺼짐", "꺼짐", "question", "plain_strong", "block", "구독 연결이 꺼져 있습니다",
                     "구독 연결이 꺼져 있습니다. '이 방식으로 사용'을 누르고 이용 조건을 확인하면 켜집니다."),
    "not_installed": Look("미설치", "미설치", "download", "warn", "block", "Claude Code를 찾지 못했습니다",
                          "이 PC에서 Claude Code를 찾지 못했습니다. 설치한 뒤 다시 확인을 누르세요. 다른 곳에 설치했다면 "
                          "위치를 지정하세요.", ("install_help", "locate", "check"), "Claude Code 미설치"),
    "cli_too_old": Look("업데이트 필요", "업데이트", "download", "warn", "block", "업데이트가 필요합니다",
                        "Claude Code 버전이 낮습니다(v2.1.259 이상 필요). 터미널에서 claude update를 실행한 뒤 다시 확인을 "
                        "누르세요.", ("terminal_update", "check"), "Claude Code 업데이트 필요"),
    "cli_unsupported": Look("설치 방식 바꿈 필요", "설치 방식", "download", "warn", "block", "지원하지 않는 설치 방식입니다",
                            "npm으로 설치한 Claude Code는 쓸 수 없습니다. 네이티브 설치본으로 바꾼 뒤 다시 확인을 누르세요.",
                            ("install_help", "check"), "Claude Code 설치 방식 바꿈 필요"),
    "login_required": Look("로그인 필요", "로그인 필요", "warn", "warn", "block", "로그인이 필요합니다",
                           "Claude Code에 로그인돼 있지 않습니다. 터미널에서 claude auth login을 실행해 구독 계정으로 "
                           "로그인한 뒤 다시 확인을 누르세요.", ("terminal_login", "check")),
    "login_expired": Look("다시 로그인 필요", "재로그인", "warn", "warn", "block", "다시 로그인해야 합니다",
                          "Claude Code 로그인 기간이 끝났습니다. 터미널에서 claude auth login으로 다시 로그인한 뒤 다시 "
                          "확인을 누르세요.", ("terminal_login", "check"), "로그인 기간 끝남"),
    "not_subscription": Look("구독 계정 아님", "구독 아님", "warn", "warn", "block", "구독 계정이 아닙니다",
                             "Claude Code가 구독이 아닌 계정(API 키나 Console)으로 로그인돼 있습니다. 이대로 쓰면 건마다 "
                             "요금이 나갑니다. claude auth login으로 구독 계정에 다시 로그인하거나, 요금을 내고 쓰려면 API 키 "
                             "방식을 고르세요.", ("login_help", "to_api", "check"), "구독 계정이 아님, 요금이 나갈 수 있음"),
    "account_blocked": Look("계정 확인 필요", "계정 확인", "warn", "warn", "block", "Claude 계정에 문제가 있습니다",
                            "Claude 계정이 정지됐거나 조직에서 허용하지 않았거나 결제에 문제가 있습니다. claude.ai에서 "
                            "계정 상태를 확인한 뒤 다시 확인을 누르세요.", ("check",)),
    "no_key": Look("키 없음", "키 없음", "question", "plain_strong", "block", "API 키가 없습니다",
                   "아래 새 키 추가에서 키를 넣으세요.", ("add_key",)),
    "key_invalid": Look("키 거부됨", "키 거부됨", "cross", "err", "block", "키가 거부됐습니다",
                        "{detail}", ("test",)),
    "no_permission": Look("권한 없음", "권한 없음", "cross", "err", "block", "키에 권한이 없습니다",
                          "{detail}", ("test",)),
    "no_credit": Look("크레딧 부족", "크레딧 부족", "cross", "err", "block", "크레딧이 부족합니다",
                      "{detail}", ("test",)),
    "rate_limited": Look("요청 제한 · 잠시 뒤 다시", "요청 제한", "clock", "warn", "retry", "요청이 잠시 거절됐습니다",
                         "짧은 시간에 요청이 많아 API가 잠시 거절했습니다. 1분쯤 뒤에 다시 시도하세요.", ("test",),
                         "요청 제한, 잠시 뒤 다시"),
    "model_unavailable": Look("모델 못 씀", "모델 못 씀", "cross", "err", "block", "고른 모델을 쓸 수 없습니다",
                              "이 계정이나 키로는 고른 모델을 쓸 수 없습니다. 다른 모델을 고른 뒤 다시 확인하세요.",
                              ("check",), "고른 모델을 쓸 수 없음"),
    "no_folder": Look("응답 폴더 없음", "폴더 없음", "question", "ai", "block", "응답 폴더가 없습니다",
                      "응답 폴더를 고르세요.", ("browse",)),
    "network": Look("연결 못 함", "연결 못 함", "cross", "err", "retry", "서버에 연결하지 못했습니다", _NET,
                    ("check", "copy_error"), "서버에 연결하지 못함"),
    "error": Look("오류", "오류", "cross", "err", "retry", "확인하다 오류가 났습니다",
                  "Claude Code를 확인하는 중에 오류가 났습니다. 오류 내용을 복사해 담당자에게 보내 주세요.",
                  ("copy_error", "open_logs", "check"), "확인 중 오류"),
}

# 방식마다 안내·동작이 다른 상태(화면 설계 §9.2·§9.3)
_API_TEST = ("test",)
METHOD_LOOKS = {
    ("api", "unchecked"): replace(LOOKS["unchecked"], guide="아직 연결 시험을 하지 않았습니다. 연결 시험을 누르세요(토큰 비용 없음).",
                                  actions=_API_TEST),
    ("api", "ok"): replace(LOOKS["ok"], guide="API 키로 연결됐습니다. 호출마다 요금이 나갑니다.", actions=_API_TEST),
    ("api", "checking"): replace(LOOKS["checking"], guide="API 연결을 시험하고 있습니다."),
    ("api", "network"): replace(LOOKS["network"], guide=_NET, actions=_API_TEST),
    ("api", "error"): replace(LOOKS["error"], title="연결 시험에서 오류가 났습니다", guide="{detail}", actions=_API_TEST),
    ("api", "model_unavailable"): replace(LOOKS["model_unavailable"], actions=_API_TEST),
    ("fixed", "ok"): Look("준비됨", "준비됨", "flask", "ai", "go", "준비됨", "응답 {count}개를 찾았습니다.", ("browse",),
                          "준비됨"),
    ("fixed", "checking"): replace(LOOKS["checking"], tone="ai", guide="응답 폴더를 확인하고 있습니다."),
    ("fixed", "unchecked"): replace(LOOKS["unchecked"], tone="ai", guide="응답 폴더를 아직 확인하지 않았습니다.",
                                    actions=("browse",)),
    ("fixed", "error"): replace(LOOKS["error"], tone="ai", guide="{detail}", actions=("browse",)),
}

ACTIONS = {  # 해결 동작 단추 글자. '터미널에서 로그인·업데이트'는 claude_cli에 고정 명령 실행 함수가 생기기 전까지 방법 보기
    "check": "다시 확인(&R)", "test": "연결 시험(&T)", "install_help": "설치 방법 보기", "locate": "위치 지정…",
    "terminal_login": "로그인 방법 보기(&L)", "terminal_update": "업데이트 방법 보기", "login_help": "로그인 방법 보기",
    "to_api": "API 키로 바꾸기…", "copy_error": "오류 내용 복사", "open_logs": "로그 폴더 열기", "browse": "찾아보기…",
    "add_key": "새 키 추가",
}

PLAN_NAMES = {"max_20x": "Max 20x 요금제", "max_5x": "Max 5x 요금제", "pro": "Pro 요금제"}
WINDOW_NAMES = {"five_hour": "5시간 한도", "seven_day": "주간 한도", "seven_day_opus": "주간 Opus 한도",
                "seven_day_sonnet": "주간 Sonnet 한도"}
SUB_MODEL_COST = {"claude-opus-5-5": "한도 소모 큼", "claude-sonnet-5-5": "보통", "claude-haiku-5-5": "작음"}
CHIP_HINT = "Enter를 누르면 연결 정보와 바꾸기 단추가 열립니다"


def look(method, state):
    """(방식, 상태) -> Look. 모르는 상태는 error로 본다(화면이 깨지지 않게)."""
    return METHOD_LOOKS.get((method, state)) or LOOKS.get(state) or LOOKS["error"]


def can_start(method, state):
    return look(method, state).can_start


def model_name(model, narrow=False):
    """'claude-opus-5-5' -> 'Opus 5.5'(좁으면 'Opus'). 표에 없으면 받은 값 그대로."""
    m = claude_http.MODELS.get(model or "")
    if not m:
        return model or ""
    full = m["label"].split(" (")[0]
    return full.split()[0] if narrow else full


def plan_name(plan):
    """planTier(또는 subscriptionType) -> 화면 이름(기술 설계 §11 8번). 없으면 빈 글자."""
    if not plan:
        return ""
    if plan in PLAN_NAMES:
        return PLAN_NAMES[plan]
    return "%s 요금제 (%s)" % (plan.split("_")[0].capitalize(), plan)


# ---------------------------------------------------------------- 시각

def _kst(epoch):
    return datetime.datetime.fromtimestamp(epoch, claude_cli.KST)


def _now():
    return datetime.datetime.now(claude_cli.KST)


def _hhmm(dt, now=None):
    now = now or _now()
    return dt.strftime("%H:%M") if dt.date() == now.date() else dt.strftime("%m-%d %H:%M")


def _spoken(dt, now=None):
    now = now or _now()
    day = "" if dt.date() == now.date() else "%d월 %d일 " % (dt.month, dt.day)
    return "%s%d시 %d분" % (day, dt.hour, dt.minute)


def _parse_kst(iso):
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(claude_cli.KST)


def reset_hhmm(limit, now=None):
    """재설정 시각 'HH:MM'(오늘이 아니면 'MM-DD HH:MM'). 모르면 빈 글자."""
    if not limit or not limit.get("resets_at"):
        return ""
    return _hhmm(_kst(limit["resets_at"]), now)


def checked_text(status, now=None):
    """'14:02 확인'. 확인 시각이 없으면 빈 글자."""
    t = _parse_kst((status or {}).get("checked_at"))
    return "%s 확인" % _hhmm(t, now) if t else ""


# ---------------------------------------------------------------- 한도 줄(§2.3)

def usage_lines(limit, now=None):
    """LimitInfo -> [(줄 글자, 소리 내어 읽을 글자, 경고 줄 또는 '')]. 정보가 없으면 안내 한 줄.
    받은 창(rateLimitType)의 줄만 만든다. '여유 있음'처럼 근거 없는 말은 쓰지 않는다."""
    if not limit or limit.get("status") in (None, "limit_unknown"):
        text = "한도 정보가 없습니다. 첫 호출 뒤에 보입니다."
        return [(text, text, "")]
    name = WINDOW_NAMES.get(limit.get("window"), "구독 한도")
    util = limit.get("utilization")
    reset = reset_hhmm(limit, now)
    reset_say = _spoken(_kst(limit["resets_at"]), now) if limit.get("resets_at") else ""
    seen = _parse_kst(limit.get("seen_at"))
    seen_txt = " (%s 호출 기준)" % _hhmm(seen, now) if seen else ""
    seen_say = ", %s 호출 기준" % _spoken(seen, now) if seen else ""
    status = limit["status"]
    if status == "limit_reached":
        text = "%s 도달%s" % (name, " · %s 재설정" % reset if reset else "")
        say = "%s 도달%s" % (name, ", %s 재설정" % reset_say if reset_say else "")
        return [(text, say, "")]
    pct = " %d%% 사용" % round(util * 100) if util is not None else (" 가까움" if status == "limit_warning" else "")
    pct_say = " %d퍼센트 사용" % round(util * 100) if util is not None else pct
    text = "%s%s%s%s" % (name, pct, " · %s 재설정" % reset if reset else "", seen_txt)
    say = "%s%s%s%s" % (name, pct_say, ", %s 재설정" % reset_say if reset_say else "", seen_say)
    warn = "한도가 가까워 도중에 멈출 수 있습니다." if status == "limit_warning" else ""
    return [(text, say, warn)]


# ---------------------------------------------------------------- 칩·띠 글자

def chip_text(method, status, model, narrow=False, this_run=False, now=None):
    """칩 글자(아이콘 제외): '방식 · 모델 · 상태[ · 덧붙임]'. 시험 방식은 모델 칸이 없다."""
    state = (status or {}).get("state") or "unchecked"
    lk = look(method, state)
    if method == "fixed":
        return "시험 · 고정 응답" if lk.can_start or state in ("checking", "unchecked") else "시험 · %s" % lk.short
    head = "%s · %s" % (METHOD_SHORT[method], model_name(model, narrow))
    if this_run:
        return "%s · 이번 실행만" % head
    reset = reset_hhmm((status or {}).get("limit"), now) if state in ("limit_warning", "limit_reached") else ""
    if narrow:
        tail = "%s · %s" % (lk.short, reset) if state == "limit_reached" and reset else (
            lk.label if state == "limit_reached" else lk.short)
    else:
        tail = lk.label + (" · %s 재설정" % reset if reset else "")
    return "%s · %s" % (head, tail)


def chip_look(method, status, this_run=False):
    return LOOKS["ok"] if this_run else look(method, (status or {}).get("state") or "unchecked")


def chip_icon(method, status, this_run=False):
    return chip_look(method, status, this_run).icon


def chip_accessible(method, status, model, this_run=False, now=None):
    """칩 accessibleName(§10.3): 좁은 형식이어도 늘 전체 문장."""
    state = (status or {}).get("state") or "unchecked"
    if method == "fixed":
        lk = look(method, state)
        return "AI 연결: 고정 응답 시험 방식, AI를 호출하지 않음%s" % ("" if lk.can_start else ", " + (lk.a11y or lk.label))
    head = "AI 연결: %s, 모델 %s" % (METHOD_NAMES[method], model_name(model))
    if this_run:
        return head + ", 이번 실행만"
    lk = look(method, state)
    out = "%s, %s" % (head, lk.a11y or lk.label)
    limit = (status or {}).get("limit")
    if state in ("limit_warning", "limit_reached") and limit and limit.get("resets_at"):
        out += ", %s 재설정" % _spoken(_kst(limit["resets_at"]), now)
    return out


def guide_text(method, status, count=None, now=None):
    """해결 띠 안내 문구. 상태별 자리 채움은 여기서만 한다."""
    status = status or {}
    state = status.get("state") or "unchecked"
    lk = look(method, state)
    limit = status.get("limit") or {}
    reset = reset_hhmm(limit, now)
    util = limit.get("utilization")
    pct = "%d%%" % round(util * 100) if util is not None else ""
    reset_part = ("%s%s 재설정" % (", " if pct else "", reset)) if reset else ""
    reset_sentence = ("%s에 다시 쓸 수 있습니다." % reset) if reset else "재설정 시각은 아직 알 수 없습니다."
    if state == "limit_reached":
        reset_sentence = "구독 사용 한도에 닿았습니다. " + reset_sentence
    detail = status.get("detail") or lk.title + "."
    text = lk.guide.format(pct=pct, reset=reset_part, reset_sentence=reset_sentence, detail=detail,
                           count=count if count is not None else 0)
    if state == "limit_warning" and not (pct or reset_part):
        text = text.replace("()", "")
    return text


def status_accessible(method, status):
    """설정 창 상태 칩 (accessibleName, accessibleDescription)."""
    lk = look(method, (status or {}).get("state") or "unchecked")
    desc = "" if lk.can_start else "아래 안내를 따른 뒤 다시 확인을 누르세요"
    return "연결 상태: %s" % (lk.a11y or lk.label), desc


def list_accessible(method, status, in_use):
    lk = look(method, (status or {}).get("state") or "unchecked")
    return "%s, %s%s" % (METHOD_NAMES[method], lk.label, ", 사용 중" if in_use else "")


def ai_call_line(method):
    """도움말 › 정보의 'AI 호출' 줄(§5.3)."""
    if method == "subscription":
        return ("AI 호출: ⑤ AI 분석 실행 때만. Claude 구독(이 PC의 claude 프로그램)을 거쳐 Anthropic으로 보냄, "
                "웹뷰 외부 네트워크 차단")
    if method == "fixed":
        return "AI 호출: 없음(고정 응답 시험). 웹뷰 외부 네트워크 차단"
    return "AI 호출: ⑤ AI 분석 실행 때만. API 키로 Claude API(api.anthropic.com)에 보냄, 웹뷰 외부 네트워크 차단"


def run_tooltip(method, model):
    """⑤ 'AI 분석 실행' 단추 도구 설명(§5.3)."""
    if method == "fixed":
        return "고정 응답(시험)으로 실행합니다. AI를 호출하지 않습니다"
    return "%s · %s로 실행합니다" % (METHOD_NAMES[method], model_name(model))


# ---------------------------------------------------------------- API 키 상태(KeyStore에서 읽음, 네트워크 없음)

_API_FAIL = (("HTTP 401", "key_invalid"), ("HTTP 400", "key_invalid"), ("HTTP 403", "no_permission"),
             ("HTTP 402", "no_credit"), ("크레딧", "no_credit"), ("HTTP 404", "model_unavailable"),
             ("HTTP 429", "rate_limited"), ("네트워크", "network"), ("형식", "key_invalid"))


def api_status(store):
    """KeyStore -> ConnStatus. 마지막 연결 시험(지금 모델로 한 것)만 본다. 시험 문구는 claude_http._test_message가
    만든 것이라 HTTP 코드가 들어 있다. 앞에서부터 처음 맞는 줄이 이긴다(크레딧 문구에는 400이 같이 올 수 있어 402·크레딧이 먼저)."""
    e = store.active()
    base = {"via": "api", "state": "no_key", "detail": "", "plan": None, "limit": None, "checked_at": None}
    if e is None:
        return base
    t = e.get("last_test")
    if not t or t.get("model") != store.model:
        return dict(base, state="unchecked")
    at = _parse_kst(t.get("at"))
    base["checked_at"] = at.isoformat(timespec="seconds") if at else None
    if t.get("ok"):
        return dict(base, state="ok")
    msg = t.get("message") or ""
    order = sorted(_API_FAIL, key=lambda p: p[1] != "no_credit")
    state = next((s for word, s in order if word in msg), "error")
    return dict(base, state=state, detail=msg)


# ---------------------------------------------------------------- 실행 확인(§6)

def _clock_min(seconds):
    return "약 %d분" % max(1, round(seconds / 60.0))


def confirm_rows(method, calls, cells, link, seconds=0, usd=None, usd_basis="", limit=None, missing=0, store="",
                 now=None, resume=False):
    """실행 확인 대화상자의 첫 줄과 칸 [(칸 이름, 값, accessibleName)]. 구독에서는 어디에도 $가 없다.
    link: 연결 칸 글자, usd·usd_basis: API 키 예상 비용과 근거, missing: 고정 응답이 없어 '분석 전'으로 남는 칸 수,
    resume: 멈춘 실행의 남은 칸을 이어서 돌림."""
    if method == "fixed":
        lead = "AI를 호출하지 않습니다. 저장된 응답으로 %d칸을 채웁니다." % cells
        match = "%d칸 중 %d칸." % (cells + missing, cells)
        if missing:
            match += " 응답이 없는 %d칸은 '분석 전'으로 둡니다." % missing
        rows = [("연결", link), ("예상 시간", "1분 안쪽"), ("비용", "없음"), ("맞는 응답", match)]
    else:
        lead = "AI를 %d회 호출해 %s%d칸을 채웁니다." % (calls, "남은 " if resume else "", cells)
        rows = [("연결", link), ("예상 시간", "%s (호출 하나 15~60초)" % _clock_min(seconds))]
        if method == "api":
            rows.append(("비용", "예상 비용 약 $%.2f · %s" % (usd or 0.0, usd_basis)))
        else:
            rows.append(("비용", "건별 요금 없음. 구독 사용량에서 차감"))
            for text, _say, warn in usage_lines(limit, now):
                rows.append(("사용량", text + ("\n" + warn if warn else "")))
            rows.append(("멈출 때", "한도에 닿으면 남은 호출을 멈추고 받은 칸은 저장합니다. 남은 칸은 재설정 뒤에 이어서 "
                                   "돌리거나 API 키로 돌릴 수 있습니다."))
    rows.append(("저장 위치", store))
    out = []
    for name, value in rows:
        say = "%s: %s" % (name, value.replace(" · ", ", ").replace(". ", ", ").replace("\n", ", ").rstrip("."))
        out.append((name, value, say))
    return lead, out


def cost_basis(avg_usd, from_log):
    """API 키 예상 비용의 근거 문구."""
    if from_log:
        return "이 모델 지난 호출 평균 $%.2f" % avg_usd
    return "기록이 없어 기본 어림값 호출당 $%.2f" % avg_usd


# ---------------------------------------------------------------- 진행 줄(§7.1)

def _k(n):
    return "%dk" % round(n / 1000.0) if n >= 1000 else str(n)


def progress_tail(method, spent, limit=None):
    """막대 옆 줄의 마지막 칸: API 키는 이번 실행 비용, 구독은 '구독 사용량 차감'(한도 가까움이면 사용률)."""
    if method == "api":
        return "$%.2f" % ((spent or {}).get("cost_usd") or 0.0)
    if limit and limit.get("status") == "limit_warning":
        util = limit.get("utilization")
        return "한도 가까움(%d%%)" % round(util * 100) if util is not None else "한도 가까움"
    return "구독 사용량 차감"


def run_usage_line(method, spent):
    """진행 줄 도구 설명의 '이번 실행' 줄."""
    if method == "fixed":
        return "AI 호출 없음"
    spent = spent or {}
    inp = sum(spent.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    tokens = "입력 %s · 출력 %s 토큰" % (_k(inp), _k(spent.get("output_tokens") or 0))
    if method == "api":
        return "%s · 추정 $%.2f" % (tokens, spent.get("cost_usd") or 0.0)
    return "%s, 구독 사용량에서 차감" % tokens


# ---------------------------------------------------------------- 결과 기록(§8)

def _at_text(at):
    t = _parse_kst(at)
    return t.strftime("%m-%d %H:%M") if t else ""


def record_via(record):
    """기록의 연결 방식. via가 없는 옛 기록은 api(providers.record_via와 같은 규칙)."""
    return (record or {}).get("via") or "api"


def model_pair(record):
    """'Opus 5.5', 요청과 실제가 다르면 'Sonnet 5.5(요청 Opus 5.5)'."""
    got, asked = record.get("model"), record.get("model_requested")
    if asked and got and asked != got:
        return "%s(요청 %s)" % (model_name(got), model_name(asked))
    return model_name(got or asked)


def provenance(run, excel=False):
    """칸 상세 출처 줄(§8.1) 'AI 초안 · Opus 5.5 · Claude 구독 · 11-09 14:20 KST',
    Excel 'AI 초안 생성' 열(§8.2) 'Opus 5.5 · 구독 · 11-09 14:20'. AI 실행 기록이 없으면 빈 글자."""
    if not run or not run.get("at"):
        return ""
    via = record_via(run)
    at = _at_text(run["at"])
    if via == "fixed":
        return "고정 응답(시험) · %s" % at if excel else "시험 · 고정 응답 · %s KST" % at
    if excel:
        return "%s · %s · %s" % (model_pair(run), METHOD_SHORT.get(via, via), at)
    return "AI 초안 · %s · %s · %s KST" % (model_pair(run), METHOD_NAMES.get(via, via), at)


def usage_summary(ai_log):
    """도구줄 사용량 도구 설명(§8.1): 방식별 호출 수와 모델, 요금은 API 키 호출분만, 토큰 합계."""
    log = ai_log or []
    if not log:
        return "이 결과의 AI 호출: 없음"
    parts = []
    for via in ("subscription", "api", "fixed"):
        rows = [r for r in log if record_via(r) == via]
        if not rows:
            continue
        if via == "fixed":
            parts.append("시험 %d회(고정 응답)" % len(rows))
            continue
        models = []
        for r in rows:
            m = model_name(r.get("model") or r.get("model_requested"))
            if m and m not in models:
                models.append(m)
        part = "%s %d회(%s)" % (METHOD_SHORT[via], len(rows), ", ".join(models) or "-")
        if via == "api":
            part += " $%.2f" % api_cost(rows)
        parts.append(part)
    inp = sum((r.get("usage") or {}).get(k) or 0 for r in log
              for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    out = sum((r.get("usage") or {}).get("output_tokens") or 0 for r in log)
    return "이 결과의 AI 호출: %s · 토큰 입력 {:,} · 출력 {:,}".format(inp, out) % " · ".join(parts)


def api_cost(ai_log):
    """API 키 호출분 요금 합계(구독·고정 응답은 넣지 않음)."""
    return sum(r["cost_usd"] for r in ai_log or [] if record_via(r) == "api"
               and isinstance(r.get("cost_usd"), (int, float)) and not isinstance(r.get("cost_usd"), bool))


def drafted_cells(cells):
    """Excel 표지 'AI 초안 생성' 값: 'Opus 5.5 · 구독 39칸, Sonnet 5.5 · API 키 12칸'(AI가 채운 칸만)."""
    count = collections.OrderedDict()
    for c in cells:
        run = c.get("ai_run") or {}
        if run.get("status") != "ok":
            continue
        via = record_via(run)
        key = "고정 응답(시험)" if via == "fixed" else "%s · %s" % (model_pair(run), METHOD_SHORT.get(via, via))
        count[key] = count.get(key, 0) + 1
    return ", ".join("%s %d칸" % kv for kv in count.items()) or "없음"


# ---------------------------------------------------------------- ⑤ 안내 띠(§7.3·§7.4·§8.1)

@dataclass(frozen=True)
class Band:
    tone: str          # TONES 이름
    icon: str
    title: str         # 굵게 보이는 첫 문장(accessibleName '알림: …'에도 씀)
    actions: tuple     # BAND_ACTIONS 이름. 첫 단추가 F6으로 닿는 단추
    a11y: str = ""     # accessibleName '알림: …'의 구절(없으면 title)


BANDS = {
    "limit_reached": Band("warn", "clock", "구독 사용 한도에 닿아 AI 분석을 멈췄습니다.", ("resume", "resume_api", "close"),
                          "구독 사용 한도에 닿아 AI 분석을 멈춤"),
    "overage": Band("warn", "clock", "초과 사용(유료)으로 넘어가 AI 분석을 멈췄습니다.", ("resume", "resume_api", "close"),
                    "초과 사용으로 넘어가 AI 분석을 멈춤"),
    "login": Band("err", "warn", "Claude Code 로그인이 풀려 AI 분석을 멈췄습니다.", ("login_help", "recheck", "close"),
                  "로그인이 풀려 AI 분석을 멈춤"),
    "not_subscription": Band("warn", "warn", "Claude Code가 구독이 아닌 계정으로 로그인돼 있어 AI 분석을 멈췄습니다.",
                             ("login_help", "recheck", "close"), "구독 계정이 아니어서 AI 분석을 멈춤"),
    "streak": Band("err", "cross", "같은 오류가 3번 이어져 AI 분석을 멈췄습니다.", ("recheck", "copy_error", "close"),
                   "같은 오류가 이어져 AI 분석을 멈춤"),
    "not_ready": Band("err", "warn", "AI 연결에 문제가 생겨 AI 분석을 멈췄습니다.", ("recheck", "settings", "close"),
                      "AI 연결 문제로 AI 분석을 멈춤"),
    "fixed_view": Band("ai", "flask", "시험 결과를 보는 중입니다.", ("to_real",), "시험 결과를 보는 중"),
}
BAND_ACTIONS = {"resume": "남은 칸 이어서 실행(&C)", "resume_api": "API 키로 이어서 실행…", "close": "닫기",
                "login_help": "로그인 방법 보기(&L)", "recheck": "다시 확인", "copy_error": "오류 내용 복사",
                "settings": "AI 연결 설정…", "to_real": "실제 결과로 돌아가기"}
FIXED_VIEW_TEXT = "고정 응답으로 채운 칸이며 실제 분석 결과가 아닙니다."


def band_kind(method, halted):
    """멈춤을 부른 UnitResult -> BANDS 이름(띠 없음은 None). API 키·배포본 실행은 구독 문구를 쓰지 않는다."""
    if not halted:
        return None
    kind, conn = halted.get("error_kind"), halted.get("conn_state")
    if kind == "cancelled":
        return None
    if method == "subscription":
        if kind == "limit_reached":
            return "limit_reached"
        if kind == "overage":
            return "overage"
        if kind == "auth_mismatch" or conn == "not_subscription":
            return "not_subscription"
        if conn in ("login_required", "login_expired"):
            return "login"
    if kind in ("transient", "timeout", "bad_output", "other"):
        return "streak"
    return "not_ready"


def band_text(kind, calls_total=0, calls_ok=0, cells_ok=0, calls_left=0, cells_left=0, limit=None, guide="", now=None):
    """띠 본문(굵은 첫 문장 뒤). 문구는 화면 설계 §7.3·§7.4 그대로."""
    if kind == "limit_reached":
        reset = reset_hhmm(limit, now)
        tail = ("%s 재설정 뒤에 이어서 돌리거나 API 키로 돌릴 수 있습니다." % reset if reset else
                "재설정 뒤에 이어서 돌리거나 API 키로 돌릴 수 있습니다. 재설정 시각은 아직 알 수 없습니다.")
        return "호출 %d회 중 %d회의 결과(%d칸)는 저장했습니다. 남은 %d회(%d칸)는 %s" % (
            calls_total, calls_ok, cells_ok, calls_left, cells_left, tail)
    if kind == "overage":
        return ("받은 칸은 저장했습니다. 초과 사용을 허용하지 않아 남은 %d회(%d칸)는 호출하지 않았습니다. 한도가 재설정된 뒤 "
                "이어서 돌리거나 API 키로 돌릴 수 있습니다." % (calls_left, cells_left))
    if kind == "login":
        return "받은 칸은 저장했습니다. 다시 로그인한 뒤 이어서 실행하세요."
    if kind == "not_subscription":
        return "이대로 쓰면 건마다 요금이 나갑니다."
    if kind == "streak":
        return "연결 상태를 확인하세요."
    if kind == "fixed_view":
        return FIXED_VIEW_TEXT
    return ("받은 칸은 저장했습니다. " + guide).strip()


def reset_toast(cells_left):
    return "구독 한도가 재설정됐습니다. 남은 %d칸을 이어서 실행할 수 있습니다." % cells_left


# ---------------------------------------------------------------- 창 닫기(기술 설계 §6.3·§11 10번)

CLOSE_TITLE = "AI 분석 중에 닫기"
CLOSE_TEXT = ("AI 호출 %d건이 아직 진행 중입니다. 기다렸다 닫으면 최대 2분 동안 결과를 받아 저장한 뒤 닫습니다. "
              "바로 끊으면 그 호출의 결과는 받지 않습니다. 이미 받은 칸은 어느 쪽이든 저장합니다.")
CLOSE_WAIT = "기다렸다 닫기(최대 2분)"
CLOSE_NOW = "바로 끊고 닫기"
CLOSE_WAITING = "진행 중인 호출을 기다리고 있습니다. %s 뒤에는 끊고 닫습니다."
