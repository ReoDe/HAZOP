"""Claude Code 구독 연결: 로컬 claude.exe를 헤드리스(-p, stream-json)로 부른다(기획서/AI연결-구독제.md §5·§6). Qt 의존 없음.

앱은 로그인 정보를 읽거나 저장하지 않는다. 호출마다 빈 임시 폴더에서, 도구·MCP·설정 출처를 끄고, API 키 환경변수를 지운 채
띄운다. 띄운 프로세스 트리는 Job Object로 묶어 시간 초과·취소·앱 종료에 함께 끝낸다. Job을 못 쓰면 띄운 PID로만
taskkill /T /F를 쓴다. 프로세스 이름으로 찾아 끄지 않는다(사용자의 다른 Claude Code 세션이 죽는다).

CLI 출력은 이 파일의 경계(_parse_line, limit_info, classify, auth_state)에서 한 번만 해석한다. 바깥은 결과 dict만 본다.
"""

import ctypes
import datetime
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from hazop import paths

MIN_VERSION = (2, 1, 259)  # --permission-prompts가 이 버전부터 있다
STDIN_DEADLINE = 3.0  # 띄운 뒤 이 시간 안에 stdin이 없으면 CLI가 끝난다(§2.2 실측)
DEFAULT_TIMEOUT = 600
CHECK_TIMEOUT = 20
STDERR_LIMIT = 64 * 1024
LIMITS_FILE_NAME = "ai_limits.json"
KST = datetime.timezone(datetime.timedelta(hours=9))

SCRUB_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE",
             "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_OAUTH_TOKEN")
QUIET_ENV = {"DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
             "DISABLE_FEEDBACK_COMMAND": "1"}

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
SPAWN_FLAGS = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW if sys.platform == "win32" else 0

MESSAGES = {
    "not_installed": "Claude Code가 이 PC에 없음. 설치하거나 실행 파일 위치를 지정하세요.",
    "cli_unsupported": "npm으로 설치한 claude.cmd는 쓸 수 없음. 네이티브 설치(claude.exe)로 바꾸세요.",
    "cli_too_old": "Claude Code 버전이 낮음(%s). 터미널에서 claude update를 실행하세요.",
    "login_required": "Claude Code에 로그인되어 있지 않음. 터미널에서 claude auth login을 실행하세요.",
    "login_expired": "Claude Code 로그인 기간이 끝남. 다시 로그인하세요.",
    "not_subscription": "구독이 아닌 인증(API 키·Console·외부 제공자)으로 잡혀 요금이 나갈 수 있어 멈춤. "
                        "구독 계정으로 로그인하거나 연결 방식을 API로 바꾸세요.",
    "account_blocked": "Claude 계정에 문제가 있음(정지·조직 불허·결제). claude.ai에서 계정을 확인하세요.",
    "model_unavailable": "고른 모델을 이 계정에서 쓸 수 없음. 다른 모델을 고르세요.",
    "limit_reached": "구독 사용 한도에 도달함. 재설정 시각 뒤 실패한 칸을 다시 실행하세요.",
    "overage": "초과 사용(유료)으로 넘어가 남은 호출을 멈춤. 이 호출 결과는 반영함.",
    "auth_mismatch": "호출 중 인증 출처가 구독이 아님을 확인해 바로 끊음(요금 방지).",
    "transient": "Claude 서비스가 일시적으로 응답하지 못함. 다시 실행하세요.",
    "timeout": "응답 시간(%d초)을 넘겨 호출을 끊음.",
    "cancelled": "사용자가 호출을 취소함.",
    "bad_output": "AI 응답 형식이 맞지 않음.",
    "schema": "응답 스키마가 CLI 규칙에 맞지 않음(개발 결함).",
    "refused": "AI가 응답을 거부함.",
    "truncated": "AI 응답이 길이 제한으로 잘림.",
    "error": "Claude Code 확인 중 오류가 남.",
}


def now_kst():
    return datetime.datetime.now(KST).isoformat(timespec="seconds")


def default_limits_path():
    return os.path.join(os.path.dirname(paths.settings_path()), LIMITS_FILE_NAME)


def default_run_root():
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "HAZOP", "cli-run")


def clean_env(base=None):
    env = {k: v for k, v in (os.environ if base is None else base).items() if k.upper() not in SCRUB_ENV}
    env.update(QUIET_ENV)
    return env


# ---------------------------------------------------------------- 실행 파일 찾기 (§6.5)

def find_cli(configured=None, which=shutil.which, home=None):
    """-> (경로|None, conn_state). .exe인 첫 후보만 쓴다. .cmd 따위만 있으면 cli_unsupported."""
    home = home or os.path.expanduser("~")
    seen_other = False
    for cand in (configured, which("claude"), os.path.join(home, ".local", "bin", "claude.exe")):
        if not cand or not os.path.isfile(cand):
            continue
        if cand.lower().endswith(".exe"):
            return cand, "ok"
        seen_other = True
    return None, "cli_unsupported" if seen_other else "not_installed"


# ---------------------------------------------------------------- 프로세스 트리 (§6.4)

class _BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


_JOB_EXTENDED_LIMIT_INFO = 9
_KILL_ON_JOB_CLOSE = 0x2000


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def create_job(proc):
    """proc를 KILL_ON_JOB_CLOSE Job에 넣고 Job 핸들을 돌려준다. 실패하면 None(호출자가 taskkill로 대신)."""
    if sys.platform != "win32":
        return None
    try:
        k = _kernel32()
        job = k.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not (k.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info))
                and k.AssignProcessToJobObject(job, int(proc._handle))):
            k.CloseHandle(job)
            return None
        return job
    except (OSError, AttributeError):
        return None


class ProcessTree:
    """띄운 프로세스 하나와 그 자손. kill()은 Job이 있으면 TerminateJobObject, 없으면 taskkill /T /F /PID."""

    def __init__(self, argv, cwd, env, stdin, job_factory=create_job):
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, creationflags=SPAWN_FLAGS)
        self.job = job_factory(self.proc)
        self.cancelled = False
        self._lock = threading.Lock()

    def kill(self):
        with self._lock:
            if self.job:
                _kernel32().TerminateJobObject(self.job, 1)
            else:
                try:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, check=False, timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def close(self):
        """끝난 뒤 정리. Job이 있으면 남은 자손까지 끝낸다."""
        with self._lock:
            if self.job:
                k = _kernel32()
                k.TerminateJobObject(self.job, 1)
                k.CloseHandle(self.job)
                self.job = None
        # stdout·stderr는 읽기 스레드가 끝날 때 닫는다. 자손이 파이프를 물고 있으면 여기서 닫다가 멈춘다.


def _run_dir(root):
    d = os.path.join(root, uuid.uuid4().hex)
    os.makedirs(d)
    return d


def cleanup_run_dirs(root=None):
    """앱 시작 때 이전 실행이 남긴 임시 작업 폴더를 지운다."""
    root = root or default_run_root()
    if os.path.isdir(root):
        for name in os.listdir(root):
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)


# ---------------------------------------------------------------- 출력 해석 (경계)

def _parse_line(raw):
    try:
        ev = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return ev if isinstance(ev, dict) else None


_LIMIT_STATUS = {"allowed": "limit_ok", "allowed_warning": "limit_warning", "rejected": "limit_reached"}


def limit_info(raw, seen_at=None):
    """rate_limit_event.rate_limit_info(낙타 표기, resetsAt 초) -> LimitInfo."""
    raw = raw if isinstance(raw, dict) else {}
    window = raw.get("rateLimitType")
    win = ((raw.get("unifiedWindows") or {}).get(window) or {}) if window else {}
    util = win.get("utilization")
    if raw.get("isUsingOverage") is True:
        overage = "in_use"
    elif raw.get("overageStatus") == "rejected":
        overage = "off"
    elif raw.get("overageStatus") in ("allowed", "allowed_warning"):
        overage = "on"
    else:
        overage = None
    resets = raw.get("resetsAt")
    return {"status": _LIMIT_STATUS.get(raw.get("status"), "limit_unknown"), "window": window,
            "resets_at": int(resets) if isinstance(resets, (int, float)) and not isinstance(resets, bool) else None,
            "utilization": float(util) if isinstance(util, (int, float)) and not isinstance(util, bool) else None,
            "overage": overage, "seen_at": seen_at or now_kst()}


def reset_text(limit):
    if not limit or not limit.get("resets_at"):
        return ""
    t = datetime.datetime.fromtimestamp(limit["resets_at"], KST)
    return " (재설정 %s KST)" % t.strftime("%m-%d %H:%M")


_NOT_READY = {"authentication_failed": "login_required", "account_on_hold": "account_blocked",
              "oauth_org_not_allowed": "account_blocked", "billing_error": "account_blocked",
              "model_not_found": "model_unavailable"}
_TRANSIENT = ("overloaded", "server_error", "connection", "api_connection")


def _usage(result):
    u = (result or {}).get("usage") or {}
    return {k: u.get(k) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                       "cache_creation_input_tokens")}


def classify(result, returncode, stderr_text, retry_errors, limit):
    """마지막 result 이벤트 등 관찰 -> (status, error_kind, conn_state, error 문구). 표: 설계 §5.3."""
    def fail(kind, msg, conn=None, status="api_error"):
        return status, kind, conn, msg

    if limit and limit["status"] == "limit_reached" and not (result and result.get("is_error") is False):
        return fail("limit_reached", MESSAGES["limit_reached"] + reset_text(limit))
    if result is None:
        if any(e in _TRANSIENT for e in retry_errors):
            return fail("transient", MESSAGES["transient"])
        if returncode not in (0, None):
            detail = stderr_text.strip()[:200]
            return fail("other", "Claude Code가 비정상 종료함(코드 %s)%s" % (returncode, ": " + detail if detail else ""))
        return fail("bad_output", MESSAGES["bad_output"], status="parse_error")
    text = str(result.get("result") or "")
    low = text.lower()
    for err in retry_errors:
        if err in _NOT_READY:
            conn = _NOT_READY[err]
            return fail("not_ready", MESSAGES[conn], conn)
    if "not logged in" in low:
        return fail("not_ready", MESSAGES["login_required"], "login_required")
    if "login expired" in low or "oauth token has expired" in low:
        return fail("not_ready", MESSAGES["login_expired"], "login_expired")
    if result.get("subtype") == "error_max_structured_output_retries":
        return fail("bad_output", MESSAGES["bad_output"], status="parse_error")
    if result.get("api_error_status") == 400 and "input_schema" in text:
        return fail("bad_output", MESSAGES["schema"], status="parse_error")
    if result.get("stop_reason") == "refusal":
        return fail("refused", MESSAGES["refused"], status="refused")
    if result.get("stop_reason") == "max_tokens" or "max_output_tokens" in retry_errors:
        return fail("bad_output", MESSAGES["truncated"], status="truncated")
    if result.get("is_error") is not False or result.get("subtype") != "success" or returncode not in (0, None):
        if any(e in _TRANSIENT for e in retry_errors):
            return fail("transient", MESSAGES["transient"])
        return fail("other", "Claude Code 호출 실패: %s" % (text[:200] or result.get("subtype") or "원인 모름"))
    if not isinstance(result.get("structured_output"), dict):
        return fail("bad_output", MESSAGES["bad_output"], status="parse_error")
    return "completed", None, None, None


# ---------------------------------------------------------------- 한도 저장

NO_RESET_HOLD = 5 * 3600  # 재설정 시각 없이 한도 도달을 받으면 가장 짧은 창(5시간) 동안 막아 둔다
_save_lock = threading.Lock()


def load_limit(path, now=None):
    """저장된 LimitInfo. 없거나 읽지 못하거나 지난 정보면 None."""
    now = time.time() if now is None else now
    try:
        with open(path, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    if info.get("resets_at"):
        return info if info["resets_at"] > now else None
    seen = info.get("seen_epoch") or 0
    return info if info.get("status") == "limit_reached" and now - seen < NO_RESET_HOLD else None


def save_limit(path, info):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _save_lock:
        tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dict(info, seen_epoch=info.get("seen_epoch") or time.time()), fh, ensure_ascii=False)
        os.replace(tmp, path)


def limit_state(limit):
    """저장된 LimitInfo -> conn_state 일부(limit_reached·overage_risk·limit_warning) 또는 None.
    초과 사용 여부를 모르면(필드 없음) 켜진 것으로 본다(요금 방지)."""
    if not limit:
        return None
    if limit.get("status") == "limit_reached":
        return "limit_reached"
    if limit.get("overage") == "in_use":
        return "overage_risk"
    near = limit.get("status") == "limit_warning" or (limit.get("utilization") or 0) >= 0.9
    if near and limit.get("overage") != "off":
        return "overage_risk"
    if near:
        return "limit_warning"
    return None


# ---------------------------------------------------------------- 연결 확인 (§5.2)

def parse_version(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _expired(value, now):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (value / 1000 if value > 1e12 else value) <= now
    if isinstance(value, str) and value:
        try:
            t = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        return t.timestamp() <= now
    return False


def auth_state(doc, now=None):
    """claude auth status --json -> (conn_state, plan). 이메일·조직 ID는 돌려주지 않는다."""
    if not isinstance(doc, dict):
        return "error", None
    if not doc.get("loggedIn"):
        return "login_required", None
    if _expired(doc.get("loginExpiresAt"), time.time() if now is None else now):
        return "login_expired", None
    if doc.get("authMethod") != "claude.ai" or doc.get("apiProvider") != "firstParty":
        return "not_subscription", None
    return "ok", doc.get("planTier") or doc.get("subscriptionType")


# ---------------------------------------------------------------- 클라이언트

class ClaudeCliClient:
    """analyze(request) 계약(ai_cells.run_unit)을 지키는 구독 클라이언트.

    argv_prefix: 시험 전용 주입(예: [sys.executable, "tests/fake_claude/fake_claude.py", ...]). 설정 파일·화면에서
    바꿀 수 없다. 주입하면 실행 파일 찾기와 .exe 검사를 건너뛴다.
    """

    def __init__(self, model="claude-opus-5-5", effort="high", timeout=DEFAULT_TIMEOUT, cli_path=None,
                 allow_overage=False, limits_path=None, run_root=None, argv_prefix=None, job_factory=create_job):
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.cli_path = cli_path
        self.allow_overage = allow_overage
        self.limits_path = limits_path or default_limits_path()
        self.run_root = run_root or default_run_root()
        self._argv_prefix = list(argv_prefix) if argv_prefix else None
        self._job_factory = job_factory
        self._active = set()
        self._lock = threading.Lock()
        self._cancel_gen = 0

    def __repr__(self):
        return "ClaudeCliClient(model=%r, effort=%r)" % (self.model, self.effort)

    def describe(self):
        return {"type": "claude_cli", "model": self.model, "effort": self.effort, "via": "subscription",
                "billing": "plan"}

    def _exe(self):
        if self._argv_prefix:
            return list(self._argv_prefix), "ok"
        path, state = find_cli(self.cli_path)
        return ([path] if path else None), state

    def _spawn(self, argv, cwd, stdin, gen=None):
        """gen: 호출을 시작할 때의 취소 세대. 띄우는 사이에 cancel()이 오면 바로 끊는다."""
        tree = ProcessTree(argv, cwd, clean_env(), stdin, self._job_factory)
        with self._lock:
            self._active.add(tree)
            late = gen is not None and gen != self._cancel_gen
        if late:
            tree.cancelled = True
            tree.kill()
        return tree

    def _forget(self, tree):
        with self._lock:
            self._active.discard(tree)
        tree.close()

    def cancel(self):
        """진행 중인 호출을 모두 바로 끊는다(스레드 안전). 끊긴 호출은 error_kind cancelled로 돌아온다."""
        with self._lock:
            self._cancel_gen += 1
            trees = list(self._active)
        for t in trees:
            t.cancelled = True
            t.kill()

    # ---- 확인

    def _short(self, base, args):
        """짧은 명령(--version, auth status) -> (종료 코드, stdout 문자열) 또는 (None, 사유)."""
        run_dir = _run_dir(self.run_root)
        try:
            tree = self._spawn(base + args, run_dir, subprocess.DEVNULL)
            try:
                out, _err = tree.proc.communicate(timeout=CHECK_TIMEOUT)
            except subprocess.TimeoutExpired:
                tree.kill()
                return None, "응답 없음"
            finally:
                self._forget(tree)
            return tree.proc.returncode, out.decode("utf-8", "replace")
        except OSError as exc:
            return None, type(exc).__name__
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def check(self):
        """토큰·한도를 쓰지 않는 연결 확인 -> ConnStatus {via, state, detail, plan, limit, checked_at}."""
        status = {"via": "subscription", "state": "ok", "detail": "", "plan": None, "limit": None,
                  "checked_at": now_kst()}

        def done(state, detail=None):
            return dict(status, state=state, detail=detail if detail is not None else MESSAGES.get(state, ""))

        base, state = self._exe()
        if base is None:
            return done(state)
        code, out = self._short(base, ["--version"])
        if code is None:
            return done("error", "%s: %s" % (MESSAGES["error"], out))
        version = parse_version(out)
        if version is None:
            return done("error", "%s: 버전을 읽지 못함" % MESSAGES["error"])
        if version < MIN_VERSION:
            return done("cli_too_old", MESSAGES["cli_too_old"] % ".".join(map(str, version)))
        code, out = self._short(base, ["auth", "status", "--json"])
        if code is None:
            return done("error", "%s: %s" % (MESSAGES["error"], out))
        try:
            doc = json.loads(out)
        except ValueError:
            doc = None
        state, plan = auth_state(doc)
        status["plan"] = plan
        if state != "ok":
            return done(state, MESSAGES["error"] + ": 로그인 상태를 읽지 못함" if state == "error" else None)
        limit = load_limit(self.limits_path)
        status["limit"] = limit
        lstate = limit_state(limit)
        if lstate == "limit_reached":
            return done(lstate, MESSAGES["limit_reached"] + reset_text(limit))
        if lstate:
            return done(lstate, "")
        return done("ok", "")

    # ---- 호출

    def command(self, request, system_file):
        return ["-p", "--output-format", "stream-json", "--verbose",
                "--json-schema", json.dumps(request["schema"], ensure_ascii=False, separators=(",", ":")),
                "--system-prompt-file", system_file,
                "--model", self.model, "--effort", self.effort,
                "--tools", "", "--disallowedTools", "mcp__*",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "",
                "--disable-slash-commands",
                "--permission-mode", "dontAsk", "--permission-prompts", "none",
                "--max-turns", "3", "--no-session-persistence"]

    def analyze(self, request):
        res = {"status": None, "output": None, "usage": None, "model": self.model, "error_type": None,
               "status_code": None, "error": None, "via": "subscription", "billing": "plan", "error_kind": None,
               "conn_state": None, "cost_usd": None, "api_equiv_usd": None, "model_requested": self.model,
               "limit": None}

        def fail(kind, msg, conn=None, status="api_error"):
            return dict(res, status=status, error_type=kind, error_kind=kind, conn_state=conn, error=msg)

        with self._lock:
            gen = self._cancel_gen
        base, state = self._exe()
        if base is None:
            return fail("not_ready", MESSAGES[state], state)
        run_dir = _run_dir(self.run_root)
        try:
            system_file = os.path.join(run_dir, "system.txt")
            with open(system_file, "w", encoding="utf-8") as fh:
                fh.write(request["system"])
            work = os.path.join(run_dir, "cwd")
            os.makedirs(work)
            stdin = (request.get("context", "") + "\n\n" + request["user"]).encode("utf-8")
            try:
                tree = self._spawn(base + self.command(request, system_file), work, subprocess.PIPE, gen)
            except OSError as exc:
                return fail("not_ready", "%s (%s)" % (MESSAGES["not_installed"], type(exc).__name__), "not_installed")
            try:
                return self._drive(tree, stdin, res, fail)
            finally:
                self._forget(tree)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def _drive(self, tree, stdin, res, fail):
        started = time.monotonic()
        events = queue.Queue()
        stderr = bytearray()
        threading.Thread(target=_write_stdin, args=(tree.proc.stdin, stdin), daemon=True).start()
        threading.Thread(target=_read_lines, args=(tree.proc.stdout, events), daemon=True).start()
        err_thread = threading.Thread(target=_read_all, args=(tree.proc.stderr, stderr), daemon=True)
        err_thread.start()
        init = result = limit = None
        retry_errors, overage = [], False
        exited_at = None
        while True:
            left = started + self.timeout - time.monotonic()
            if left <= 0:
                tree.kill()
                return fail("timeout", MESSAGES["timeout"] % self.timeout)
            try:
                ev = events.get(timeout=min(0.2, left))
            except queue.Empty:
                # 자손이 stdout을 물고 있으면 EOF가 오지 않는다. 띄운 프로세스가 끝나면 잠시 더 읽고 멈춘다.
                if tree.proc.poll() is not None:
                    exited_at = exited_at or time.monotonic()
                    if result is not None or time.monotonic() - exited_at > 1.0:
                        break
                continue
            if ev is None:
                break
            if tree.cancelled:
                continue
            kind, sub = ev.get("type"), ev.get("subtype")
            if kind == "system" and sub == "init":
                init = ev
                if ev.get("apiKeySource") != "none":
                    tree.kill()
                    return fail("auth_mismatch", MESSAGES["auth_mismatch"], "not_subscription")
            elif kind == "system" and sub == "api_retry":
                retry_errors.append(str(ev.get("error") or ""))
            elif kind == "rate_limit_event":
                limit = limit_info(ev.get("rate_limit_info"))
                overage = overage or limit["overage"] == "in_use"
                self._remember(limit)
            elif kind == "result":
                result = ev
        if tree.cancelled:
            return fail("cancelled", MESSAGES["cancelled"])
        try:
            tree.proc.wait(max(1.0, started + self.timeout - time.monotonic()))
        except subprocess.TimeoutExpired:
            tree.kill()
            return fail("timeout", MESSAGES["timeout"] % self.timeout)
        err_thread.join(2)
        if result is not None and init is None:
            return fail("auth_mismatch", MESSAGES["auth_mismatch"], "not_subscription")
        res.update(limit=limit, usage=_usage(result) if result else None,
                   api_equiv_usd=(result or {}).get("total_cost_usd"),
                   model=(init or {}).get("model") or next(iter((result or {}).get("modelUsage") or {}), self.model))
        status, kind, conn, msg = classify(result, tree.proc.returncode, stderr.decode("utf-8", "replace"),
                                           retry_errors, limit)
        if overage:
            res["billing"] = "overage"
        if status != "completed":
            if overage and not self.allow_overage and kind not in ("not_ready", "auth_mismatch", "limit_reached"):
                kind, msg = "overage", MESSAGES["overage"] + " 이 호출은 실패함: " + msg
            return fail(kind, msg, conn, status)
        res.update(status="completed", output=result["structured_output"])
        if limit and limit["status"] == "limit_reached":
            res.update(error_kind="limit_reached", error=MESSAGES["limit_reached"] + reset_text(limit))
        elif overage and not self.allow_overage:
            res.update(error_kind="overage", error=MESSAGES["overage"])
        return res

    def _remember(self, limit):
        if limit.get("resets_at") or limit.get("status") == "limit_reached":
            try:
                save_limit(self.limits_path, limit)
            except OSError:
                pass


def _write_stdin(pipe, data):
    try:
        pipe.write(data)
        pipe.close()
    except OSError:
        pass


def _read_lines(pipe, events):
    try:
        for raw in pipe:
            ev = _parse_line(raw.strip())
            if ev is not None:
                events.put(ev)
    except (OSError, ValueError):
        pass
    finally:
        _close(pipe)
    events.put(None)


def _read_all(pipe, buf):
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            if len(buf) < STDERR_LIMIT:
                buf.extend(chunk[:STDERR_LIMIT - len(buf)])
    except (OSError, ValueError):
        pass
    finally:
        _close(pipe)


def _close(pipe):
    try:
        pipe.close()
    except OSError:
        pass
