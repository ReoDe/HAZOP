"""새 웹 화면과 엔진 사이의 길(docs/design/app-shell-web.md §5.2·§5.3). Qt를 import하지 않는다.

- **읽기 API** `ReadApi`: 웹이 `hazop-app://shell/api/<자료>`로 읽어 간다. 저장된 자료를 읽기만 한다(쓰기 없음).
    state · drawings · sheet/<graph_id> · sheet/<graph_id>.svg · connection
- **명령 길** `COMMANDS` 표 + `Engine.dispatch(name, args)`: 웹이 보내는 `{"t":"cmd","id","name","args"}`가 이 표에 있는 이름만 받고
  인자 형·길이를 검사한다. 잘못되면 처리 함수를 부르지 않고 `{"ok":false,"error":{"code","message"}}`를 돌려준다.
- 저장하는 자료는 엔진만 쓴다. 웹은 보기 상태(열린 패널, 확대, 고른 것)만 가지며 `ui.save`로 한 쪽짜리 상태만 맡긴다(§5.3).
- 오래 걸리는 일(등록·추출)은 작업 스레드에서 돌고 진행은 `emit(event)`로 보낸다(`emit`은 어느 스레드에서 불러도 된다).

처리 함수는 지금 이전 화면이 부르는 엔진 함수를 그대로 부른다(`hazop.register.registry`, `hazop.app.data`, `hazop.app.project_ctx`).
"""

import hashlib
import json
import logging
import os
import threading

from hazop import paths, store_io
from hazop.extract import ai_review
from hazop.shell import scheme

LOG = logging.getLogger("hazop.shell.api")
MAX_UI_STATE_CHARS = 4096
MAX_FILES = 50
MAX_PATH_CHARS = 520
REGISTRABLE_EXT = (".drawio", ".pdf")   # SVG는 같은 이름 drawio와 함께 등록되는 파생 자료라 따로 받지 않는다
CHAT_MODELS = ("fast", "normal", "deep")
DEFAULT_PROJECT = "sample-project"   # 이전 화면 ①의 프로젝트 ID 입력칸 기본값과 같다


class CommandError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def reply_ok(data=None):
    return {"ok": True, "data": data}


def reply_error(code, message):
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------- 인자 검사(작은 검사기들)

def v_str(lo=0, hi=200):
    def check(v):
        if not isinstance(v, str) or not lo <= len(v) <= hi or "\x00" in v:
            raise ValueError("글자 %d~%d자가 와야 함" % (lo, hi))
        return v
    return check


def v_enum(*values):
    def check(v):
        if v not in values:
            raise ValueError("%s 중 하나여야 함" % "·".join(map(str, values)))
        return v
    return check


def v_bool():
    def check(v):
        if not isinstance(v, bool):
            raise ValueError("참·거짓이어야 함")
        return v
    return check


def v_int(lo, hi):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError("정수 %d~%d가 와야 함" % (lo, hi))
        return v
    return check


def v_list(item, hi):
    def check(v):
        if not isinstance(v, list) or len(v) > hi:
            raise ValueError("목록(최대 %d개)이어야 함" % hi)
        return [item(x) for x in v]
    return check


def v_json_text(hi):
    """JSON으로 적을 수 있는 값. 적은 글자 수가 hi를 넘으면 거절."""
    def check(v):
        try:
            text = json.dumps(v, ensure_ascii=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("JSON 값이어야 함") from exc
        if len(text) > hi:
            raise ValueError("너무 큼(%d자 초과)" % hi)
        return v
    return check


def v_obj(**fields):
    """키가 정해진 객체. 모르는 키는 거절. 값이 None이면 있어도 없는 것으로 본다."""
    def check(v):
        if not isinstance(v, dict):
            raise ValueError("객체여야 함")
        extra = sorted(set(v) - set(fields))
        if extra:
            raise ValueError("모르는 키: %s" % ", ".join(map(str, extra[:3])))
        out = {}
        for k, fn in fields.items():
            if k in v and v[k] is not None:
                out[k] = fn(v[k])
        return out
    return check


def check_args(spec, args):
    """spec: {이름: (검사기, 필수 여부)}. 알 수 없는 키·빠진 필수 값·형 오류는 CommandError('bad_args')."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise CommandError("bad_args", "인자는 객체여야 함")
    extra = sorted(set(args) - set(spec))
    if extra:
        raise CommandError("bad_args", "모르는 인자: %s" % ", ".join(map(str, extra[:3])))
    out = {}
    for key, (fn, required) in spec.items():
        if key not in args or args[key] is None:
            if required:
                raise CommandError("bad_args", "빠진 인자: %s" % key)
            continue
        try:
            out[key] = fn(args[key])
        except ValueError as exc:
            raise CommandError("bad_args", "%s: %s" % (key, exc)) from exc
    return out


# ---------------------------------------------------------------- 엔진

class Engine:
    """웹 화면이 쓰는 엔진 창구. 화면 쪽 부품(AI 연결, 채팅)은 주입받는다(시험은 가짜를 넣는다).

    emit(event)  — 웹으로 사건을 보낸다(어느 스레드에서든)
    ai           — status() -> dict, check(), make_client()를 가진 것(없으면 연결 없음)
    chat         — ChatController(hazop.shell.chat) 또는 None
    """

    def __init__(self, settings_path=None, emit=None, ai=None, chat=None, run_jobs=None):
        self.settings_path = settings_path
        self.settings = paths.load_settings(settings_path)
        self._emit = emit or (lambda event: None)
        self.ai = ai
        self.chat = chat
        self.current_sheet = None
        self.hooks = {}          # 창이 꽂아 주는 일(파일 고르기·이전 화면 열기). 시험은 가짜를 꽂는다
        self._run_jobs = run_jobs or self._thread_jobs
        self._jobs = {}
        self._job_seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()   # 창을 닫거나 화면을 바꾸려고 작업을 멈추라고 할 때
        self._threads = []
        self._analysis = None

    # ------------------------------------------------------------ 보내기
    def emit(self, name, data=None):
        self._emit({"t": "event", "name": name, "data": data})

    def changed(self, topic, rev=None):
        self._emit({"t": "changed", "topic": topic, "rev": rev})

    # ------------------------------------------------------------ 설정·상태
    def save_settings(self):
        paths.save_settings(self.settings, self.settings_path)

    def reviewer(self):
        return (self.settings.get("reviewer_name") or "").strip() or None

    def project_id(self):
        """지금 프로젝트: 설정에 적힌 값, 없으면 등록된 자료의 프로젝트, 없으면 기본값."""
        pid = self.settings.get("project_id")
        if isinstance(pid, str) and pid.strip():
            return pid.strip()
        from hazop.app import data
        for e in data.list_registrations():
            if e["record"].get("project_id"):
                return e["record"]["project_id"]
        from hazop.app import project_ctx
        from hazop.graph import project
        try:
            if project_ctx.graph_names(project.UNREGISTERED_PROJECT):   # 등록 없이 추출한 도면(샘플 실행 등)만 있을 때
                return project.UNREGISTERED_PROJECT
        except (OSError, ValueError):
            pass
        return DEFAULT_PROJECT

    def graph_names(self):
        """{graph_id: 도면(추출) 이름}. 프로젝트 그래프가 아직 없으면 빈 사전."""
        from hazop.app import project_ctx
        from hazop.graph import project
        pids = [self.project_id(), project.UNREGISTERED_PROJECT]
        for pid in dict.fromkeys(pids):
            try:
                names = project_ctx.graph_names(pid)
            except (OSError, ValueError):
                names = {}
            if names:
                return dict(names)
        return {}

    def ui_state_path(self):
        return os.path.join(paths.work_root(), "data", "ui-state.json")

    def ui_state(self):
        try:
            with open(self.ui_state_path(), encoding="utf-8") as fh:
                state = json.load(fh)
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    # ------------------------------------------------------------ 명령
    def dispatch(self, name, args, project=None, via_web=False):
        """명령 하나를 돌린다 -> 답(dict). 어떤 오류도 오류 답으로 바꾼다(웹에 안쪽 글을 싣지 않는다).
        via_web: 웹이 보낸 명령. 프로젝트에 묶인 명령(구간·결과·초기사건·채팅 동작)은 웹이 본 프로젝트 ID(project)를 함께 보내야 하고, 지금 프로젝트와 다르면
        아무것도 하지 않고 거절한다(프로젝트를 바꾼 뒤 낡은 목록으로 다른 프로젝트의 구간을 고치지 않게). 영역 파일은 이 한 곳의 검사를 따른다."""
        cmd = COMMANDS.get(name) if isinstance(name, str) else None
        if cmd is None:
            return reply_error("unknown_command", "모르는 명령")
        if name.startswith(PROJECT_BOUND) and (via_web or project is not None):
            if not isinstance(project, str) or not project:
                return reply_error("bad_args", "프로젝트 ID가 없는 명령은 받지 않습니다")
            if project != self.project_id():
                return reply_error("wrong_project", "프로젝트가 바뀌어 저장하지 않았습니다. 화면을 다시 읽었으니 한 번 더 해 주세요.")
        try:
            clean = check_args(cmd.spec, args)
            return reply_ok(cmd.handler(self, clean))
        except CommandError as exc:
            return reply_error(exc.code, exc.message)
        except Exception:  # noqa: BLE001 - 처리 함수의 안쪽 오류 글은 웹에 보내지 않는다
            LOG.exception("명령 처리 오류: %s", name)
            return reply_error("failed", "처리하지 못했습니다. 기록을 확인하세요.")

    # ------------------------------------------------------------ 작업(등록·추출)
    def add_files(self, files):
        """등록할 파일 경로를 받아 등록·추출 작업을 시작한다 -> {"jobs": [작업 ID]}. **웹이 보낸 경로를 받지 않는다**(규격 §5.2): 끌어 놓기 이벤트와 파일
        대화상자처럼 Python 쪽이 사용자 조작으로 얻은 경로만 부른다. 명령 표에는 경로를 받는 명령이 없다. 등록할 수 없는 파일이면 CommandError."""
        checked = []
        for p in files:
            if not isinstance(p, str) or not p or len(p) > MAX_PATH_CHARS or "\x00" in p:
                raise CommandError("bad_args", "등록할 수 없는 파일 경로")
            full = os.path.abspath(p)
            if os.path.splitext(full)[1].lower() not in REGISTRABLE_EXT or not os.path.isfile(full):
                raise CommandError("bad_args", "등록할 수 없는 파일: %s" % os.path.basename(full))
            checked.append(full)
        if not checked:
            raise CommandError("bad_args", "파일이 없음")
        from hazop.shell import register_flow
        return {"jobs": [self.start_job(os.path.basename(f), lambda progress, f=f: register_flow.register_and_extract(self, f, progress))
                         for f in checked]}

    def _thread_jobs(self, job_id, fn):
        t = threading.Thread(target=fn, name="hazop-job-%s" % job_id, daemon=True)
        self._threads.append(t)
        t.start()
        return t

    @property
    def analysis(self):
        """⑤ 분석 실행 하나의 상태(hazop/shell/api_results.py)."""
        if self._analysis is None:
            from hazop.shell import api_results
            self._analysis = api_results.AnalysisRun()
        return self._analysis

    # ------------------------------------------------------------ 진행 중인 작업(창 닫기·화면 바꾸기 전에 묻는다)
    def running_jobs(self):
        """아직 도는 작업의 ID 목록."""
        with self._lock:
            return [j for j, v in self._jobs.items() if v["state"] == "running"]

    def running_kinds(self):
        """도는 작업의 종류 목록(running_jobs와 같은 순서)."""
        with self._lock:
            return [v.get("kind") or "register" for v in self._jobs.values() if v["state"] == "running"]

    def stop_jobs(self):
        """돌고 있는 작업에 멈추라고 알린다. 작업은 진행을 알리는 자리(등록 -> 추출 -> AI 검토 사이, AI 검토는 도면마다)에서 멈춘다.
        단계 한가운데(추출 호출 하나)는 끊지 않는다: 반쯤 쓰인 자료를 남기지 않으려는 것이다."""
        self._stop.set()

    def stop_requested(self):
        return self._stop.is_set()

    def wait_jobs(self, timeout):
        """도는 작업 스레드가 끝나기를 기다린다 -> 모두 끝났으면 True."""
        import time
        end = time.monotonic() + timeout
        for t in list(self._threads):
            t.join(max(0.0, end - time.monotonic()))
        self._threads = [t for t in self._threads if t.is_alive()]
        return not self.running_jobs()

    def _job_ended(self):
        if not self.running_jobs():
            self._stop.clear()
            hook = self.hooks.get("jobs_idle")
            if hook is not None:
                hook()

    def start_job(self, label, fn, kind="register"):
        """작업을 시작하고 작업 ID를 돌려준다. fn(progress)은 작업 스레드에서 돌고, 진행·끝은 job.* 사건으로 간다.
        kind: 창을 닫을 때 묻는 글에 쓴다(register 도면 등록·추출 · analysis AI 분석)."""
        with self._lock:
            self._job_seq += 1
            job_id = "j%d" % self._job_seq
            self._jobs[job_id] = {"label": label, "state": "running", "kind": kind}

        def run():
            self.emit("job.progress", {"id": job_id, "label": label, "state": "running"})
            def progress(text, done=None, total=None):
                if self._stop.is_set():
                    raise JobStopped("중지했습니다")
                self.emit("job.progress", {"id": job_id, "label": label, "state": "running", "text": text, "done": done, "total": total})
            try:
                result = fn(progress)
                self._jobs[job_id]["state"] = "done"
                self.emit("job.done", {"id": job_id, "label": label, "result": result})
                self.changed("drawings")
            except JobStopped as exc:
                self._jobs[job_id]["state"] = "stopped"
                self.emit("job.failed", {"id": job_id, "label": label, "message": _one_line(exc), "stopped": True})
                self.changed("drawings")   # 등록까지 된 도면은 목록에 보여야 한다
            except Exception as exc:  # noqa: BLE001
                LOG.exception("작업 오류: %s", label)
                self._jobs[job_id]["state"] = "failed"
                self.emit("job.failed", {"id": job_id, "label": label, "message": _one_line(exc)})
            finally:
                self._job_ended()
        self._run_jobs(job_id, run)
        return job_id


class JobStopped(Exception):
    """창을 닫거나 화면을 바꾸려고 작업을 멈추라고 했을 때 진행 알림 자리에서 올리는 신호."""


def _one_line(exc):
    text = " ".join(str(exc).split())
    return text[:200] or type(exc).__name__


# ---------------------------------------------------------------- 명령 표

class Command:
    def __init__(self, spec, handler, doc=""):
        self.spec, self.handler, self.doc = spec, handler, doc


def _h_ui_save(engine, a):
    path = engine.ui_state_path()
    store_io.write_json(path, a["state"])
    return {}


def _h_open_sheet(engine, a):
    if a["graph_id"] not in engine.graph_names():
        raise CommandError("not_found", "없는 도면")
    engine.current_sheet = a["graph_id"]
    if engine.chat is not None:
        engine.chat.note_view(sheet=a["graph_id"])
    return {"graph_id": a["graph_id"]}


def _h_set_reviewer(engine, a):
    engine.settings["reviewer_name"] = a["name"].strip()
    engine.save_settings()
    engine.changed("state")
    return {}


def _h_set_project(engine, a):
    pid = a["project_id"].strip()
    if not pid or paths.safe_name(pid) != pid:
        raise CommandError("bad_args", "프로젝트 ID는 글자·숫자·'.'·'-'·'_'만 쓸 수 있음")
    engine.settings["project_id"] = pid
    engine.save_settings()
    if engine.chat is not None:
        engine.chat.check_project()      # 프로젝트가 바뀌면 대화를 끝낸다
    engine.current_sheet = None
    engine.emit("project.changed", {"project_id": pid})      # 웹이 구간·결과·초기사건 상태를 모두 비우고 다시 읽는다
    for topic in ("drawings", "state", "nodes", "results", "ie"):
        engine.changed(topic)
    return {"project_id": pid}


def _h_set_default_shell(engine, a):
    engine.settings["ui_shell"] = a["enabled"]
    engine.save_settings()
    return {"enabled": a["enabled"]}


def _h_conn_check(engine, a):
    if engine.ai is None:
        raise CommandError("failed", "AI 연결 정보를 쓸 수 없음")
    engine.ai.check()
    return {}


def _need_chat(engine):
    if engine.chat is None:
        raise CommandError("failed", "채팅을 쓸 수 없음")
    return engine.chat


def _h_chat_ask(engine, a):
    ok = _need_chat(engine).ask(a["text"], a.get("view") or {})
    return {"accepted": bool(ok)}


def _h_chat_prewarm(engine, a):
    _need_chat(engine).prewarm()
    return {}


def _h_conn_guide(engine, a):
    hook = engine.hooks.get("conn_guide")
    if hook is None:
        raise CommandError("failed", "안내를 열 수 없음")
    hook(a["name"])
    return {}


def _h_chat_stop(engine, a):
    _need_chat(engine).stop()
    return {}


def _h_chat_new(engine, a):
    _need_chat(engine).new_conversation()
    return {}


def _h_action_approve(engine, a):
    """확인 상자에서 사람이 '실행'을 눌렀다. 인자는 앱이 낸 표(token)뿐이고 인자·대상은 동작 층 메모리의 것을 쓴다."""
    out = _need_actions(engine).approve(a["token"])
    if not out.get("ok"):
        raise CommandError(out.get("error") or "failed", out.get("message") or "실행하지 못했습니다.")
    return {"result": out.get("result")}


def _h_action_decline(engine, a):
    out = _need_actions(engine).decline(a["token"])
    if not out.get("ok"):
        raise CommandError(out.get("error") or "failed", out.get("message") or "처리하지 못했습니다.")
    return {"result": out.get("result")}


def _need_actions(engine):
    chat = _need_chat(engine)
    actions = getattr(chat, "_actions", None)
    if actions is None:
        raise CommandError("failed", "채팅 동작을 쓸 수 없습니다.")
    return actions


def _h_chat_model(engine, a):
    _need_chat(engine).set_model(a["model"])
    engine.settings["chat_model"] = a["model"]
    engine.save_settings()
    return {}


def _h_set_ai_review(engine, a):
    if "enabled" in a:
        engine.settings["extract_ai_review"] = a["enabled"]
    if "cap" in a:
        engine.settings["extract_ai_cap"] = a["cap"]
    engine.save_settings()
    return {"enabled": bool(engine.settings.get("extract_ai_review")), "cap": engine.settings.get("extract_ai_cap")}


def _h_pick_files(engine, a):
    pick = engine.hooks.get("pick_files")
    if pick is None:
        raise CommandError("failed", "파일 고르기를 쓸 수 없음")
    files = pick() or []
    if not files:
        return {"jobs": []}
    return engine.add_files(list(files)[:MAX_FILES])


def _h_open_classic(engine, a):
    hook = engine.hooks.get("open_classic")
    if hook is None:
        raise CommandError("failed", "이전 화면을 열 수 없음")
    return {"switched": bool(hook())}   # 작업이 도는 중이면 창이 묻는다: 닫히지 않으면 False


# 프로젝트에 묶인 명령의 이름 머리(웹이 보낼 때 프로젝트 ID를 실어야 하는 것)
PROJECT_BOUND = ("nodes.", "results.", "ie.", "chat.action.")

COMMANDS = {
    "ui.save": Command({"state": (v_json_text(MAX_UI_STATE_CHARS), True)}, _h_ui_save, "웹의 보기 상태(마지막 도면·채팅 접힘 등)를 맡긴다"),
    "sheet.open": Command({"graph_id": (v_str(1, 200), True)}, _h_open_sheet, "보는 도면이 바뀌었음을 알린다(채팅의 지금 화면 문맥)"),
    "project.set": Command({"project_id": (v_str(1, 60), True)}, _h_set_project, "프로젝트를 정하거나 바꾼다(끌어 놓아 등록할 때 쓰는 프로젝트 ID)"),
    "settings.set_default_shell": Command({"enabled": (v_bool(), True)}, _h_set_default_shell, "시작할 때 새 화면을 쓸지(설정 ui_shell)"),
    "settings.set_reviewer": Command({"name": (v_str(1, 60), True)}, _h_set_reviewer, "검토자 이름"),
    "conn.check": Command({}, _h_conn_check, "AI 연결을 다시 확인한다"),
    "chat.ask": Command({"text": (v_str(1, 4000), True),
                         "view": (v_obj(stage=v_str(0, 40), sheet=v_str(0, 200), selected=v_list(v_str(1, 200), 20)), False)},
                        _h_chat_ask, "채팅에 묻는다"),
    "chat.prewarm": Command({}, _h_chat_prewarm, "글자를 치기 시작할 때 채팅 프로세스를 미리 띄운다"),
    "conn.guide": Command({"name": (v_enum("install", "login"), True)}, _h_conn_guide, "연결 안내(설치 방법·로그인)를 연다"),
    "chat.stop": Command({}, _h_chat_stop, "진행 중인 질문을 멈춘다"),
    "chat.new": Command({}, _h_chat_new, "대화를 지우고 새로 시작한다"),
    "chat.action.approve": Command({"token": (v_str(1, 80), True)}, _h_action_approve, "채팅이 제안한 동작의 확인 상자에서 '실행'"),
    "chat.action.decline": Command({"token": (v_str(1, 80), True)}, _h_action_decline, "채팅이 제안한 동작의 확인 상자에서 '하지 않음'"),
    "chat.set_model": Command({"model": (v_enum(*CHAT_MODELS), True)}, _h_chat_model, "채팅 모델(빠름·보통·깊게)"),
    "extract.set_ai_review": Command({"enabled": (v_bool(), False), "cap": (v_int(1, 200), False)}, _h_set_ai_review,
                                     "추출 뒤 AI 검토 토글과 도면당 호출 상한"),
    "register.pick": Command({}, _h_pick_files, "파일 고르기 창을 열어 고른 파일을 등록한다"),
    "app.open_classic": Command({}, _h_open_classic, "이전 위젯 화면으로 연다(이 창은 닫힌다)"),
}


# 영역별 명령 모듈을 같은 표에 올린다. 한 모듈이 없거나 깨져도 새 화면은 뜨고 그 메뉴만 꺼진다(이름이 겹치면 ValueError로 바로 알린다).
try:
    from hazop.shell import api_nodes  # noqa: E402  (2단계 구간, s-viewer 몫)
    api_nodes.register(COMMANDS)
except ImportError:
    LOG.exception("구간 명령 모듈을 읽지 못함: 구간 메뉴가 꺼진다")
    api_nodes = None
try:
    from hazop.shell import api_results  # noqa: E402  (3단계 ⑤ 분석 결과)
    api_results.register(COMMANDS)
except ImportError:
    LOG.exception("분석 결과 명령 모듈을 읽지 못함: 분석 결과 메뉴가 꺼진다")
    api_results = None
try:
    from hazop.shell import api_ie  # noqa: E402  (3단계 ⑥ 초기사건)
    api_ie.register(COMMANDS)
except ImportError:
    LOG.exception("초기사건 명령 모듈을 읽지 못함: 초기사건 메뉴가 꺼진다")
    api_ie = None


# ---------------------------------------------------------------- 읽기 API

def _json(data, status=200):
    return scheme.Response(status, "application/json", json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _fingerprint(*paths_):
    parts = []
    for p in paths_:
        try:
            st = os.stat(p)
            parts.append((os.path.basename(os.path.dirname(p)), st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append((p and os.path.basename(p), None, None))
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()[:12]


_ICON_CACHE = {}


def icon_shapes():
    """{이름: [[태그, 속성], …]}. 웹이 SVG를 요소로 그린다(HTML 문자열로 넣지 않는다). 투명 바탕 경로는 뺀다."""
    if not _ICON_CACHE:
        import xml.etree.ElementTree as ET
        from hazop.app import icons
        for name in icons.names():
            src = icons.icon_path(name)
            try:
                root = ET.parse(src).getroot()
            except (OSError, ET.ParseError):
                continue
            kids = []
            for el in root:
                tag = el.tag.split("}")[-1]
                attrs = dict(el.attrib)
                if tag == "path" and attrs.get("stroke") == "none" and attrs.get("fill") == "none":
                    continue
                kids.append([tag, attrs])
            _ICON_CACHE[name] = kids
    return {"names": dict(_ICON_CACHE)}


class ReadApi:
    def __init__(self, engine):
        self.engine = engine

    def read(self, parts, query):
        topic = parts[0]
        if topic == "state" and len(parts) == 1:
            return _json(self.state())
        if topic == "drawings" and len(parts) == 1:
            return _json(self.drawings())
        if topic == "connection" and len(parts) == 1:
            return _json(self.connection())
        if topic == "chat" and len(parts) == 1:
            chat = self.engine.chat
            return _json(chat.snapshot() if chat is not None else {"busy": False, "model": "fast", "availability": {"blocked": True, "text": "채팅을 쓸 수 없습니다.", "button": None}})
        if topic == "nodes" and api_nodes is not None:
            return api_nodes.read(self.engine, parts, query)
        if topic == "results" and api_results is not None:
            return api_results.read(self.engine, parts, query)
        if topic == "ie" and api_ie is not None:
            return api_ie.read(self.engine, parts, query)
        if topic == "icons" and len(parts) == 1:
            return _json(icon_shapes())
        if topic == "examples" and len(parts) == 1:
            return _json(self.examples())
        if topic == "sheet" and len(parts) == 2:
            if parts[1].endswith(".svg"):
                return self.sheet_svg(parts[1][:-4])
            return self.sheet(parts[1])
        return None

    # ------------------------------------------------------------ 자료
    def state(self):
        try:
            from hazop.app.main_window import APP_VERSION
        except Exception:  # noqa: BLE001
            APP_VERSION = "0.2.0"
        e = self.engine
        s = e.settings
        return {"version": APP_VERSION, "reviewer": e.reviewer(), "project_id": e.project_id(), "current_sheet": e.current_sheet,
                "ui": e.ui_state(), "chat_model": s.get("chat_model") or "fast", "ai_review": bool(s.get("extract_ai_review")),
                "ai_review_cap": s.get("extract_ai_cap") or ai_review.DEFAULT_CAP, "ai_review_run_cap": ai_review.RUN_CAP,
                "ui_shell": s.get("ui_shell") is not False, "debug": bool(os.environ.get("HAZOP_DEBUG"))}

    def examples(self):
        """채팅 예시 질문(종류별). 태그는 지금 프로젝트에서 채운다. 프로젝트 그래프가 없으면 태그 없는 질문."""
        from hazop.app import project_ctx
        from hazop.chat import view as chatview
        try:
            pg = project_ctx.project_graph(self.engine.project_id())
        except (OSError, ValueError, KeyError):
            pg = None
        return {"groups": [[g, qs] for g, qs in chatview.examples(pg)]}

    def connection(self):
        ai = self.engine.ai
        return (ai.status() if ai is not None else {"state": "unchecked", "detail": ""})

    def drawings(self):
        from hazop.app import data
        e = self.engine
        names = e.graph_names()
        rows = []
        for graph_id, name in sorted(names.items(), key=lambda kv: kv[1]):
            brief = data.extraction_brief(data.extraction_path(name)) or {}
            rows.append({"graph_id": graph_id, "name": name, "drawing_number": brief.get("drawing_number"), "title": brief.get("title"),
                         "nodes": brief.get("nodes"), "relations": brief.get("relations"), "unknowns": brief.get("unknowns"),
                         "origin": brief.get("origin")})
        docs = []
        for r in data.list_registrations():
            rec = r["record"]
            docs.append({"material_id": rec.get("material_id"), "name": rec.get("original_name"), "type": rec.get("material_type"),
                         "status": rec.get("status"), "drawing_number": rec.get("drawing_number"), "title": rec.get("title"),
                         "version": rec.get("registration_version"), "extracted": r.get("extracted"), "graphed": r.get("graphed"),
                         "extract_name": r.get("extract_name")})
        return {"project_id": e.project_id(), "drawings": rows, "documents": docs,
                "rev": hashlib.sha256(json.dumps([rows, docs], sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]}

    def _sheet_name(self, graph_id):
        name = self.engine.graph_names().get(graph_id)
        if not name:
            return None
        return name

    def sheet(self, graph_id):
        """도면 한 장의 그리기 자료: 고친 추출에서 만든 구성요소·배관 목록(items, SVG 좌표)과 도면 SVG 주소(canvas/README.md)."""
        from hazop.app import data
        name = self._sheet_name(graph_id)
        if not name:
            return None
        from hazop.shell import sheet_items
        _original, corrected = data.load_extraction(name)
        graph = data.viewer_build.load_graph(paths.output_root("graph"), name)
        built = sheet_items.build_items(corrected)
        svg_ok = bool(((corrected.get("coordinate_system") or {}).get("svg_alignment") or {}).get("svg_file"))
        rev = _fingerprint(data.extraction_path(name), os.path.join(paths.output_root("graph"), name, "graph.json"))
        return _json({"graph_id": graph_id, "name": name, "rev": rev, "svg": "/api/sheet/%s.svg" % graph_id if svg_ok else None,
                      "width": built["width"], "height": built["height"], "items": built["items"],
                      "unknowns": (corrected.get("summary") or {}).get("unknowns"), "has_graph": graph is not None})

    def sheet_svg(self, graph_id):
        from hazop.app import data
        from hazop.viewer import build as viewer_build
        name = self._sheet_name(graph_id)
        if not name:
            return None
        _original, corrected = data.load_extraction(name)
        al = (corrected.get("coordinate_system") or {}).get("svg_alignment") or {}
        if not al.get("svg_file"):
            return None
        try:
            svg_path = viewer_build._svg_path(al["svg_file"], [paths.work_root(), paths.store_root()])
            with open(svg_path, encoding="utf-8") as fh:
                text = viewer_build.prepare_svg(fh.read())
        except (OSError, ValueError):
            return None
        return scheme.Response(200, "image/svg+xml", text.encode("utf-8"))
