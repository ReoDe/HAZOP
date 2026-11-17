"""AI 연결 방식(via) 표: 구독·API·고정 응답 클라이언트를 한 곳에서 고른다(기획서/AI연결-구독제.md §0·§5.1). Qt 의존 없음.

내부용 배포본(PyInstaller)에서도 구독을 고를 수 있다(U3 2026-11-13 개정, DEC-0306). 기본은 구독 확인이 통과하면 구독이다(U5).
"""

import hashlib
import json
import os
import time

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
    """고정 응답 파일 이름: 요청 전체(프롬프트 system, 답 스키마, 맥락, 지시, 그림이 있으면 그림 이름표·내용) 해시 앞 16자.
    프롬프트나 스키마가 바뀌면 열쇠가 바뀌어, 옛 판으로 받아 둔 응답을 다시 쓰지 않고 새로 묻는다."""
    text = "\n".join((request.get("system") or "", json.dumps(request.get("schema"), ensure_ascii=False, sort_keys=True),
                      request.get("context", ""), request["user"]))
    return _key_hash(text, request)


def legacy_key(request):
    """2026-11-17 전 열쇠(맥락·지시·그림만, system·스키마 없음). 사용자가 예전에 받아 둔 고정 응답 폴더를 읽을 때만 쓴다."""
    return _key_hash(request.get("context", "") + "\n" + request["user"], request)


def _key_hash(text, request):
    for img in request.get("images") or []:
        text += "\n%s:%s" % (img["label"], hashlib.sha256(img["data"].encode("ascii")).hexdigest())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def stored_keys(request):
    """고정 응답 폴더에서 찾을 열쇠, 찾는 순서대로. 새 열쇠 먼저. 글만 보내는 요청(결과 화면 AI 칸 등)은 사용자가 이전 판
    열쇠로 받아 둔 폴더를 잃지 않게 이전 판 열쇠도 받는다. 그림 요청은 프롬프트가 바뀐 옛 답을 쓰지 않게 새 열쇠만.
    저장은 늘 새 열쇠(fixed_key)로 한다."""
    return [fixed_key(request)] if request.get("images") else [fixed_key(request), legacy_key(request)]


def _stored_path(response_dir, request):
    """(있는 파일 경로, 이전 판 열쇠로 찾았나) 또는 (None, False)."""
    for n, key in enumerate(stored_keys(request)):
        path = os.path.join(response_dir, key + ".json")
        if os.path.isfile(path):
            return path, n > 0
    return None, False


class RecordingClient:
    """다른 클라이언트를 감싸 응답을 고정 응답 꼴(<response_dir>/<fixed_key>.json)로 남기고 호출마다 걸린 시간을 적는다.
    같은 요청을 FixedCellsClient(response_dir)로 다시 돌리면 같은 답이 나온다(재현). 연결 방식(describe)은 안쪽 것을 그대로 쓴다.
    폴더에 이미 그 요청의 응답이 있으면 부르지 않고 그것을 쓴다(한도에 걸려 멈춘 실행을 같은 자리에서 이어 감, cached)."""

    def __init__(self, inner, response_dir):
        self.inner = inner
        self.response_dir = response_dir
        self.calls = []  # [{key, seconds, status, error_kind, images, cached}]

    def describe(self):
        return self.inner.describe() if hasattr(self.inner, "describe") else {}

    def check(self):
        return self.inner.check()

    def cancel(self):
        self.inner.cancel()

    def analyze(self, request):
        key = fixed_key(request)
        n_images = len(request.get("images") or [])
        if _stored_path(self.response_dir, request)[0]:
            res = FixedCellsClient(self.response_dir).analyze(request)
            self.calls.append({"key": key, "seconds": 0.0, "status": res.get("status"),
                               "error_kind": res.get("error_kind"), "images": n_images, "cached": True,
                               "legacy_key": bool(res.get("legacy_key"))})
            return res
        started = time.monotonic()
        res = self.inner.analyze(request)
        self.calls.append({"key": key, "seconds": round(time.monotonic() - started, 1), "status": res.get("status"),
                           "error_kind": res.get("error_kind"), "images": n_images, "cached": False, "legacy_key": False})
        if res.get("status") == "completed":
            os.makedirs(self.response_dir, exist_ok=True)
            with open(os.path.join(self.response_dir, key + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"output": res.get("output")}, fh, ensure_ascii=False, indent=1)
        return res


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
        path, legacy = _stored_path(self.response_dir, request)
        if legacy:
            res["legacy_key"] = True  # 이전 판 열쇠로 찾음(프롬프트 판을 확인할 수 없는 옛 저장본)
        try:
            with open(path or os.path.join(self.response_dir, fixed_key(request) + ".json"), encoding="utf-8") as fh:
                doc = json.load(fh)
        except OSError:
            return dict(res, status="api_error", error_kind="not_ready", conn_state="no_folder",
                        error="고정 응답 파일 없음: %s.json" % fixed_key(request))
        except ValueError:
            return dict(res, status="parse_error", error_kind="bad_output", error=ai.user_message("parse_error"))
        stop = doc.get("stop_reason")
        if stop == "refusal":
            return dict(res, status="refused", error_kind="refused", error=ai.user_message("refused"))
        if stop == "max_tokens":
            return dict(res, status="truncated", error_kind="bad_output", error=ai.user_message("truncated"))
        return dict(res, status="completed", output=doc.get("output"))
