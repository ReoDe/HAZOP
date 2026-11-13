"""새 웹 화면과 엔진 사이의 길(docs/design/app-shell-web.md §5.2·§5.3). Qt를 import하지 않는다.

- **읽기 API** `ReadApi`: 웹이 `hazop-app://api/<자료>`로 읽어 간다. 저장된 자료를 읽기만 한다(쓰기 없음).
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
    def dispatch(self, name, args):
        """명령 하나를 돌린다 -> 답(dict). 어떤 오류도 오류 답으로 바꾼다(웹에 안쪽 글을 싣지 않는다)."""
        cmd = COMMANDS.get(name) if isinstance(name, str) else None
        if cmd is None:
            return reply_error("unknown_command", "모르는 명령")
        try:
            clean = check_args(cmd.spec, args)
            return reply_ok(cmd.handler(self, clean))
        except CommandError as exc:
            return reply_error(exc.code, exc.message)
        except Exception:  # noqa: BLE001 - 처리 함수의 안쪽 오류 글은 웹에 보내지 않는다
            LOG.exception("명령 처리 오류: %s", name)
            return reply_error("failed", "처리하지 못했습니다. 기록을 확인하세요.")

    # ------------------------------------------------------------ 작업(등록·추출)
    def _thread_jobs(self, job_id, fn):
        t = threading.Thread(target=fn, name="hazop-job-%s" % job_id, daemon=True)
        t.start()
        return t

    def start_job(self, label, fn):
        """작업을 시작하고 작업 ID를 돌려준다. fn(progress)은 작업 스레드에서 돌고, 진행·끝은 job.* 사건으로 간다."""
        with self._lock:
            self._job_seq += 1
            job_id = "j%d" % self._job_seq
            self._jobs[job_id] = {"label": label, "state": "running"}

        def run():
            self.emit("job.progress", {"id": job_id, "label": label, "state": "running"})
            try:
                result = fn(lambda text, done=None, total=None: self.emit(
                    "job.progress", {"id": job_id, "label": label, "state": "running", "text": text, "done": done, "total": total}))
                self._jobs[job_id]["state"] = "done"
                self.emit("job.done", {"id": job_id, "label": label, "result": result})
                self.changed("drawings")
            except Exception as exc:  # noqa: BLE001
                LOG.exception("작업 오류: %s", label)
                self._jobs[job_id]["state"] = "failed"
                self.emit("job.failed", {"id": job_id, "label": label, "message": _one_line(exc)})
        self._run_jobs(job_id, run)
        return job_id


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
    engine.changed("drawings")
    engine.changed("state")
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
    return _h_add_files(engine, {"paths": list(files)[:MAX_FILES]})


def _h_open_classic(engine, a):
    hook = engine.hooks.get("open_classic")
    if hook is None:
        raise CommandError("failed", "이전 화면을 열 수 없음")
    hook()
    return {}


def _h_add_files(engine, a):
    files = []
    for p in a["paths"]:
        full = os.path.abspath(p)
        if os.path.splitext(full)[1].lower() not in REGISTRABLE_EXT or not os.path.isfile(full):
            raise CommandError("bad_args", "등록할 수 없는 파일: %s" % os.path.basename(full))
        files.append(full)
    if not files:
        raise CommandError("bad_args", "파일이 없음")
    from hazop.shell import register_flow
    return {"jobs": [engine.start_job(os.path.basename(f), lambda progress, f=f: register_flow.register_and_extract(engine, f, progress))
                     for f in files]}


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
    "chat.set_model": Command({"model": (v_enum(*CHAT_MODELS), True)}, _h_chat_model, "채팅 모델(빠름·보통·깊게)"),
    "extract.set_ai_review": Command({"enabled": (v_bool(), False), "cap": (v_int(1, 200), False)}, _h_set_ai_review,
                                     "추출 뒤 AI 검토 토글과 도면당 호출 상한"),
    "register.pick": Command({}, _h_pick_files, "파일 고르기 창을 열어 고른 파일을 등록한다"),
    "app.open_classic": Command({}, _h_open_classic, "이전 위젯 화면으로 연다(이 창은 닫힌다)"),
    "register.add_files": Command({"paths": (v_list(v_str(1, MAX_PATH_CHARS), MAX_FILES), True)}, _h_add_files,
                                  "끌어 놓은 파일을 등록하고 추출한다"),
}


# 2단계 구간 명령(hazop/shell/api_nodes.py, s-viewer 몫)을 같은 표에 올린다
from hazop.shell import api_nodes  # noqa: E402
api_nodes.register(COMMANDS)


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
        if topic == "nodes":
            return api_nodes.read(self.engine, parts, query)
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
                "ui_shell": s.get("ui_shell") is True, "debug": bool(os.environ.get("HAZOP_DEBUG"))}

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
