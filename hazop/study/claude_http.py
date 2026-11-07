"""Claude API HTTP 클라이언트 (4단계 설계 D1·D2·D3, '클라이언트 계약'). Qt 의존 없음.

anthropic SDK 없이 표준 라이브러리(urllib + ssl)로 POST /v1/messages를 부른다. 비스트리밍, 구조화 출력(json_schema),
서버 측 대체 모델(fallbacks "default"). thinking·temperature·prefill·tool_choice는 보내지 않는다.
opener를 주입하면 네트워크 없이 시험할 수 있다. 키 문자열은 결과의 어떤 필드에도 남기지 않는다.
"""

import http.client
import json
import ssl
import urllib.error
import urllib.request

from hazop.analysis import ai
from hazop.study.apikey import mask

API_BASE = "https://api.anthropic.com"
MESSAGES_URL = API_BASE + "/v1/messages"
MODELS_URL = API_BASE + "/v1/models/"
API_VERSION = "2026-10-21"
FALLBACK_BETA = ai.FALLBACK_BETA
DEFAULT_MODEL = "claude-opus-5-5"
TEST_TIMEOUT = 20

# USD / 백만 토큰 (claude-api 스킬 2026-10-06 캐시). cache_write는 5분 TTL(입력 단가의 1.25배).
# fallbacks "default"는 거절 범주에 따라 다른 모델로 넘어갈 수 있어(예: cyber -> Opus 4.8) 그 모델 단가도 둔다.
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
}

STATUSES = ("completed", "refused", "truncated", "api_error", "parse_error", "no_key")
NO_KEY_MESSAGE = "API 키가 설정되지 않음(파일 > API 키 설정)"
BAD_KEY_MESSAGE = "API 키 형식이 올바르지 않음(공백·줄바꿈 확인). 키를 다시 입력하세요."
_ERROR_MESSAGES = {
    "auth": "API 키가 거부됨(HTTP 401, 키 확인 필요)",
    "permission": "이 API 키에 권한이 없음(HTTP 403)",
    "overloaded": "AI 서비스가 과부하 상태임(HTTP 529, 잠시 뒤 재시도)",
    "timeout": "AI 서비스 응답 시간이 초과됨(네트워크 확인 또는 재시도)",
    "bad_response": "AI 서비스 응답을 읽을 수 없음",
}


def cost_usd(usage, model):
    """사용량 -> 추정 비용(USD). 표에 없는 모델은 기본 모델 단가로 추정한다."""
    usage = usage or {}
    p = PRICES.get(model) or PRICES[DEFAULT_MODEL]

    def n(k):
        return usage.get(k) or 0

    total = (n("input_tokens") * p["input"] + n("output_tokens") * p["output"]
             + n("cache_read_input_tokens") * p["cache_read"] + n("cache_creation_input_tokens") * p["cache_write"])
    return total / 1_000_000


def urllib_opener(url, headers, body, timeout):
    """기본 전송. HTTP 오류 응답도 (상태 코드, 본문)으로 돌려준다. 연결 실패·시간 초과는 예외로 올린다."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            data = exc.read()
        except OSError:
            data = b""
        return exc.code, data


def _error_type(code):
    if code == 401:
        return "auth"
    if code == 403:
        return "permission"
    if code == 429:
        return "rate_limit"
    if code == 529:
        return "overloaded"
    return "api_status"


def _exc_type(exc):
    if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
        return "timeout"
    return "connection"


def _message(error_type, status_code=None):
    if error_type in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[error_type]
    return ai.user_message("api_error", {"error_type": error_type, "status_code": status_code})


def _api_detail(raw, key):
    """API 오류 본문의 error.type·message(키는 가림, 200자 제한). 읽지 못하면 빈 문자열."""
    try:
        err = json.loads(raw.decode("utf-8")).get("error") or {}
        text = "%s: %s" % (err.get("type", ""), err.get("message", ""))
    except (AttributeError, UnicodeDecodeError, ValueError):
        return ""
    return mask(text, key)[:200] if err else ""


def _scrub(obj, key):
    if isinstance(obj, str):
        return mask(obj, key)
    if isinstance(obj, dict):
        return {k: _scrub(v, key) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, key) for v in obj]
    return obj


class ClaudeHttpClient:
    def __init__(self, key_provider, model=DEFAULT_MODEL, effort="high", max_tokens=16000, timeout=600, opener=None):
        self.key_provider = key_provider
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.opener = opener or urllib_opener

    def __repr__(self):
        return "ClaudeHttpClient(model=%r, effort=%r)" % (self.model, self.effort)

    def describe(self):
        return {"type": "anthropic_http", "model": self.model, "effort": self.effort, "max_tokens": self.max_tokens}

    def _headers(self, key):
        return {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"}

    def build_body(self, request):
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": request["system"],
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": request["context"], "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": request["user"]},
            ]}],
            "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": request["schema"]}},
            "fallbacks": "default",
        }

    def analyze(self, request):
        """request = {"system", "context", "user", "schema"} -> 결과 dict(계약의 7개 필드).
        네트워크·HTTP·응답 형식 오류는 예외 대신 status로 돌려준다."""
        res = {"status": None, "output": None, "usage": None, "model": self.model, "error_type": None,
               "status_code": None, "error": None}
        key = self.key_provider()
        if not key:
            return dict(res, status="no_key", error=NO_KEY_MESSAGE)
        body = json.dumps(self.build_body(request), ensure_ascii=False).encode("utf-8")
        headers = dict(self._headers(key), **{"anthropic-beta": FALLBACK_BETA})
        return _scrub(self._call(res, headers, body), key)

    def _call(self, res, headers, body):
        try:
            code, raw = self.opener(MESSAGES_URL, headers, body, self.timeout)
        except ValueError:  # http.client의 잘못된 헤더 값 오류. 문구에 키가 들어 있어 쓰지 않는다
            return dict(res, status="api_error", error_type="bad_key", error=BAD_KEY_MESSAGE)
        except (OSError, http.client.HTTPException) as exc:
            et = _exc_type(exc)
            return dict(res, status="api_error", error_type=et, error=_message(et))
        res["status_code"] = code
        if code != 200:
            et = _error_type(code)
            detail = _api_detail(raw, headers.get("x-api-key"))
            return dict(res, status="api_error", error_type=et,
                        error=_message(et, code) + (" - " + detail if detail else ""))
        try:
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("응답이 객체가 아님")
        except (UnicodeDecodeError, ValueError):
            return dict(res, status="api_error", error_type="bad_response", error=_message("bad_response"))
        res["usage"] = doc.get("usage")
        res["model"] = doc.get("model") or self.model
        stop = doc.get("stop_reason")
        if stop == "refusal":
            return dict(res, status="refused", error=ai.user_message("refused"))
        if stop == "max_tokens":
            return dict(res, status="truncated", error=ai.user_message("truncated"))
        text = next((b.get("text") for b in doc.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"),
                    None)
        if text is None:
            return dict(res, status="parse_error", error=ai.user_message("parse_error"))
        out, err = ai._parse_text(text)
        if err is not None:
            return dict(res, status="parse_error", error=ai.user_message("parse_error"))
        return dict(res, status="completed", output=out)

    def test_connection(self):
        """GET /v1/models/<model>(토큰 비용 없음) -> {"ok", "message"} 한국어 문구."""
        key = self.key_provider()
        if not key:
            return {"ok": False, "message": "API 키가 없음. 키를 입력하세요."}
        try:
            code, raw = self.opener(MODELS_URL + self.model, self._headers(key), None, min(self.timeout, TEST_TIMEOUT))
        except ValueError:
            return {"ok": False, "message": BAD_KEY_MESSAGE}
        except (OSError, http.client.HTTPException) as exc:
            if _exc_type(exc) == "timeout":
                return {"ok": False, "message": "연결 시간이 초과됨(네트워크·프록시 확인)"}
            return {"ok": False, "message": "AI 서비스에 연결하지 못함(네트워크·프록시 확인)"}
        if code == 200:
            return {"ok": True, "message": "연결됨. 모델 %s 사용 가능" % self.model}
        if code == 401:
            return {"ok": False, "message": "키가 거부됨(HTTP 401). 키를 다시 확인하세요."}
        if code == 403:
            return {"ok": False, "message": "이 키에 권한이 없음(HTTP 403)"}
        if code == 404:
            return {"ok": False, "message": "모델 %s을 찾을 수 없음(HTTP 404)" % self.model}
        detail = _api_detail(raw, key)
        msg = _message(_error_type(code), code)
        return {"ok": False, "message": msg + (" - " + detail if detail else "")}
