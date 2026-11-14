"""AI 연결 방식(via) 표: 구독·API·고정 응답 클라이언트를 한 곳에서 고른다(기획서/AI연결-구독제.md §0·§5.1). Qt 의존 없음.

내부용 배포본(PyInstaller)에서도 구독을 고를 수 있다(U3 2026-11-13 개정, DEC-0306). 기본은 구독 확인이 통과하면 구독이다(U5).
"""

import hashlib
import json
import os

from hazop import paths
from hazop.analysis import ai
from hazop.study import claude_cli, claude_http

METHODS = ("subscription", "api", "fixed")
BILLING = {"subscription": "plan", "api": "per_call", "fixed": "none"}

# error_kind -> 남은 호출을 멈추는지(설계 §0.3). 같은 종류가 STREAK_LIMIT회 이어져도 멈춘다.
ERROR_KINDS = {"not_ready": True, "auth_mismatch": True, "limit_reached": True, "overage": True,
               "rate_limited": False, "transient": False, "timeout": False, "bad_output": False, "refused": False,
               "cancelled": True, "other": False,
               # 채팅(규격 chat-panel.md §2.4): 도구 검문 실패는 경계가 틀린 것이라 멈추고, 도구 과다는 그 질문만 끊는다
               "tool_guard_failed": True, "tool_limit": False}
STREAK_LIMIT = 3


def available_methods():
    """고를 수 있는 연결 방식. 배포본은 구독·API(U3 2026-11-13 개정, DEC-0306: 내부용 배포본에도 구독 연결을 넣음).
    고정 응답은 시험용이라 배포본에서 숨긴다. 배포본은 CLI를 싣지 않고, 사용자가 설치·로그인한 claude.exe를 찾는다."""
    return ("subscription", "api") if paths.frozen_bundle_dir() else METHODS


def default_method(cli_state):
    """개발자 PC에서 구독 확인이 통과하면 구독, 아니면 API(U5)."""
    ok = cli_state in ("ok", "limit_warning", "overage_risk")
    return "subscription" if "subscription" in available_methods() and ok else "api"


def make_client(method, key_provider=None, model=claude_http.DEFAULT_MODEL, effort="high", response_dir=None,
                cli_path=None, allow_overage=False):
    if method not in available_methods():
        raise ValueError("이 실행본에서는 쓸 수 없는 연결 방식: %r" % method)
    if method == "subscription":
        return claude_cli.ClaudeCliClient(model=model, effort=effort, cli_path=cli_path, allow_overage=allow_overage)
    if method == "api":
        return claude_http.ClaudeHttpClient(key_provider, model=model, effort=effort)
    return FixedCellsClient(response_dir)


def record_via(record):
    """기록의 연결 방식. via가 없는 옛 기록은 api(구독 연결 전에는 API뿐이었다)."""
    return (record or {}).get("via") or "api"


def api_error_kind(resp):
    """via가 없는 클라이언트(claude_http, 시험용 가짜) 결과 -> (error_kind, conn_state). 성공이면 (None, None)."""
    status, et, code = resp.get("status"), resp.get("error_type"), resp.get("status_code")
    if status == "completed":
        return None, None
    if status == "no_key":
        return "not_ready", "no_key"
    if status == "refused":
        return "refused", None
    if status in ("truncated", "parse_error") or et == "bad_response":
        return "bad_output", None
    if et == "bad_key" or code == 401 or et == "auth":
        return "not_ready", "key_invalid"
    if code == 403 or et == "permission":
        return "not_ready", "no_permission"
    if code == 402 or any(w in str(resp.get("error") or "").lower() for w in ("credit", "billing")):
        return "not_ready", "no_credit"
    if code == 404:
        return "not_ready", "model_unavailable"
    if code == 429 or et == "rate_limit":
        return "rate_limited", "rate_limited"
    if et == "timeout":
        return "timeout", None
    if et == "connection":
        return "transient", "network"
    if code == 529 or (isinstance(code, int) and code >= 500) or et == "overloaded":
        return "transient", None
    return "other", None


def halts(error_kinds):
    """지금까지의 error_kind 목록(호출 순서, 성공은 None) -> 남은 호출을 멈춰야 하는지."""
    if not error_kinds:
        return False
    last = error_kinds[-1]
    if last is not None and ERROR_KINDS.get(last, False):
        return True
    tail = error_kinds[-STREAK_LIMIT:]
    return len(tail) == STREAK_LIMIT and last is not None and all(k == last for k in tail)


def fixed_key(request):
    """고정 응답 파일 이름: 요청(맥락+편차) 해시 앞 16자."""
    text = request.get("context", "") + "\n" + request["user"]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class FixedCellsClient:
    """고정 응답(시험·시연): <response_dir>/<fixed_key(request)>.json = {"output": {...}} 또는 {"stop_reason": ...}."""

    def __init__(self, response_dir):
        if not response_dir:
            raise ValueError("고정 응답 폴더가 필요함")
        self.response_dir = response_dir

    def describe(self):
        return {"type": "fixed_cells", "model": None, "via": "fixed", "billing": "none"}

    def check(self):
        ok = os.path.isdir(self.response_dir)
        return {"via": "fixed", "state": "ok" if ok else "no_folder", "detail": "" if ok else "고정 응답 폴더가 없음",
                "plan": None, "limit": None, "checked_at": claude_cli.now_kst()}

    def cancel(self):
        pass

    def analyze(self, request):
        res = {"status": None, "output": None, "usage": None, "model": None, "error_type": None, "status_code": None,
               "error": None, "via": "fixed", "billing": "none", "error_kind": None, "conn_state": None,
               "cost_usd": None, "api_equiv_usd": None, "model_requested": None, "limit": None}
        path = os.path.join(self.response_dir, fixed_key(request) + ".json")
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except OSError:
            return dict(res, status="api_error", error_kind="not_ready", conn_state="no_folder",
                        error="고정 응답 파일 없음: %s" % os.path.basename(path))
        except ValueError:
            return dict(res, status="parse_error", error_kind="bad_output", error=ai.user_message("parse_error"))
        stop = doc.get("stop_reason")
        if stop == "refusal":
            return dict(res, status="refused", error_kind="refused", error=ai.user_message("refused"))
        if stop == "max_tokens":
            return dict(res, status="truncated", error_kind="bad_output", error=ai.user_message("truncated"))
        return dict(res, status="completed", output=doc.get("output"))
