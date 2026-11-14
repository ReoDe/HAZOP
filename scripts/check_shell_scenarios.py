"""새 화면(hazop/shell/) 사용자 시나리오 N1~N15 점검. 실행:
    %USERPROFILE%\\.hazop\\venv-py312\\Scripts\\python.exe scripts/check_shell_scenarios.py --out <폴더> [--only N1,N3] [--list] [--keep-temp] [--real-ai]

목록과 단계별 확인 기준은 docs/units/2026-11-14-shell-scenarios/README.md에 있다. 이 스크립트는 오프스크린으로 도는 부분이다.
- 새 화면 창(ShellWindow)을 화면 밖(QT_QPA_PLATFORM=offscreen)에 띄우고, 웹이 보내는 것과 같은 명령 길(Engine.dispatch, 웹이 본 프로젝트 ID를 함께
  보냄)로 조작한 뒤, 저장된 파일과 웹 화면(패널 글자)을 함께 확인한다.
- 파일 고르기·저장 대화상자는 창의 갈고리(engine.hooks)에 정해 둔 경로를 넣는다. 대화상자 자체와 키보드·마우스 조작은 실제 창 시나리오(문서의
  '실제 창에서 볼 것')가 맡는다.
- AI는 가짜다: 추출 뒤 AI 검토는 고정 답 클라이언트, 채팅은 정해 둔 답을 내는 세션(경로는 실제 그래프에서 trace_path로 찾은 것), 일괄 분석은
  tests/test_shell_results.fake_run_unit. --real-ai를 주면 일괄 분석(N8)만 실제 구독으로 부르고 호출 수가 20을 넘으면 부르지 않는다.
- 시나리오는 앞 시나리오의 결과에 기대어 차례로 돈다. 앞이 실패하면 기대는 시나리오는 '건너뜀'으로 적는다.
- 작업·저장 루트는 임시 폴더다(사용자의 work·%APPDATA%를 건드리지 않는다). 결과는 --out에 report.md·report.json으로 남긴다.
"""

import argparse
import contextlib
import datetime
import glob
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PROJECT = "SCN"
IMPORT_PROJECT = "SCN-DEXPI"
REVIEWER = "검토자A"
REAL_AI_MAX_CALLS = 20


# ---------------------------------------------------------------- 시나리오 표(docs/units/2026-11-14-shell-scenarios/README.md와 같은 번호)

SCENARIOS = [
    ("N1", "도면 등록(drawio, 파일 고르기)", "offscreen", ()),
    ("N2", "AI 검토 켜고 등록·추출, 후보 처리", "offscreen", ("N1",)),
    ("N3", "표제란 확정(후보 그대로)", "offscreen", ("N2",)),
    ("N4", "도면 고치기(태그 고침·되돌리기·다시 하기)", "offscreen", ("N3",)),
    ("N5", "쪽 확정(원본과 견줌 → 확정)", "offscreen", ("N4",)),
    ("N6", "채팅 질문과 경로 표시", "offscreen", ("N1", "N2")),
    ("N7", "채팅으로 구간 만들기·확정", "offscreen", ("N1", "N2")),
    ("N8", "일괄 분석", "offscreen", ("N7",)),
    ("N9", "결과 판정(승인·보류)", "offscreen", ("N8",)),
    ("N10", "Excel 내보내기", "offscreen", ("N9",)),
    ("N11", "초기사건 편집(초안·그룹 이름)", "offscreen", ("N9",)),
    ("N12", "인계 묶음 내보내기", "offscreen", ("N11",)),
    ("N13", "DEXPI 내보내기", "offscreen", ("N5",)),
    ("N14", "내보낸 DEXPI 가져오기(다른 프로젝트)", "offscreen", ("N13",)),
    ("N15", "지식그래프·설계 문서", "offscreen", ("N1", "N2")),
]


class Skip(Exception):
    pass


class Check:
    """시나리오 하나의 확인 기록."""

    def __init__(self, sid, title):
        self.sid, self.title, self.items, self.error, self.skipped, self.seconds = sid, title, [], None, None, 0.0

    def ok(self, what, cond, detail=""):
        self.items.append({"what": what, "ok": bool(cond), "detail": "" if cond else str(detail)[:600]})
        return bool(cond)

    def need(self, what, cond, detail=""):
        """실패하면 이 시나리오를 더 진행할 수 없는 확인."""
        if not self.ok(what, cond, detail):
            raise AssertionError(what)

    @property
    def passed(self):
        return self.skipped is None and self.error is None and all(i["ok"] for i in self.items)

    def verdict(self):
        if self.skipped:
            return "건너뜀"
        return "통과" if self.passed else "실패"


# ---------------------------------------------------------------- Qt·웹 도우미

def pump(sec):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + sec
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def wait_for(cond, timeout=20.0):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        try:
            if cond():
                return True
        except Exception:  # noqa: BLE001 - 조건을 읽는 중 생긴 오류는 '아직 아님'으로 본다
            pass
        time.sleep(0.02)
    return False


class FakeChat:
    """채팅 세션 대역. 질문을 받으면 queue의 앞 것(도구 사건 목록, 답)을 그 자리에서 낸다. 실제 CLI·모델을 부르지 않는다."""

    def __init__(self, model, cb, owner):
        self.model, self.cb, self.owner, self.n, self.asked = model, cb, owner, 0, []

    def start(self):
        return True

    def ask(self, text, view=None):
        self.n += 1
        qid = "q%d" % self.n
        self.asked.append(text)
        tools, ans = self.owner.queue.pop(0) if self.owner.queue else ([], {"text": "준비한 답이 없습니다."})
        for name, result in tools:
            self.cb["on_tool_event"](qid, name, {}, result)
        self.cb["on_answer"](qid, dict({"general": "", "refs": [], "paths": [], "highlight": [], "warnings": [], "actions": []}, **ans),
                             self.owner.tool_ids)
        return qid

    def stop(self):
        pass

    def close(self):
        pass

    def set_model(self, model):
        self.model = model


class LogTail:
    """엔진이 웹에 싣지 않는 안쪽 오류(LOG.exception)를 모아 보고서에 붙인다."""

    def __init__(self):
        import logging
        self.records = []
        outer = self

        class H(logging.Handler):
            def emit(self, record):
                text = record.getMessage()
                if record.exc_info:
                    text += " | " + "".join(traceback.format_exception_only(*record.exc_info[:2])).strip()
                outer.records.append(text)
        self.handler = H(level=logging.ERROR)
        logging.getLogger("hazop").addHandler(self.handler)

    def since(self, n):
        return self.records[n:]


class Run:
    """시나리오들이 함께 쓰는 상태: 창, 사건 기록, 앞 시나리오가 남긴 값."""

    def __init__(self, tmp, out, real_ai=False):
        self.tmp, self.out, self.real_ai = tmp, out, real_ai
        self.events, self.queue, self.tool_ids, self.sessions = [], [], {}, []
        self.state = {}
        self.win = None
        self.log = LogTail()

    # -- 창
    def open(self):
        from hazop.app import make_application
        from hazop.shell.window import ShellWindow
        self.qapp = make_application(["check-shell-scenarios"])
        settings = os.path.join(self.tmp, "shell-settings.json")
        with open(settings, "w", encoding="utf-8") as fh:
            json.dump({"reviewer_name": REVIEWER, "project_id": PROJECT}, fh)

        def factory(model, cb):
            s = FakeChat(model, cb, self)
            self.sessions.append(s)
            return s
        self.win = ShellWindow(settings_path=settings, size=(1366, 768), session_factory=factory)
        send = self.win.bridge.send
        lock = threading.Lock()

        def tee(msg):
            with lock:
                self.events.append(msg)
            send(msg)
        # 엔진·채팅·채팅 동작이 웹으로 보내는 사건을 모두 기록한다(채팅은 만들 때 받은 send를 쥐고 있어 따로 바꾼다)
        self.win.bridge.send = tee
        self.win.engine._emit = tee
        self.win.chat._emit = tee
        self.win.show()
        if not wait_for(lambda: self.js("!!window.__hz && document.querySelector('.rail') !== null"), 60):
            raise RuntimeError("새 화면 웹이 뜨지 않음")
        pump(0.5)

    def close(self):
        if self.win is None:
            return
        from PySide6.QtCore import QCoreApplication, QEvent
        from hazop.shell.window import ShellView
        self.win.engine.wait_jobs(60)
        for w in self.qapp.allWidgets():
            if isinstance(w, ShellView):
                w.dispose()
        for w in self.qapp.topLevelWidgets():
            w.close()
            w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()
        self.win = None

    @property
    def engine(self):
        return self.win.engine

    def js(self, code, timeout=10.0):
        out = []
        self.win.view.page().runJavaScript(code, 0, out.append)
        end = time.monotonic() + timeout
        while time.monotonic() < end and not out:
            pump(0.01)
        return out[0] if out else None

    def jsj(self, expr):
        raw = self.js("JSON.stringify(%s)" % expr)
        return json.loads(raw) if raw else None

    def text(self):
        return self.js("document.body.innerText") or ""

    def panel(self, name, expect=None, timeout=20.0):
        """패널 하나를 연다(웹 보기 상태). expect 글자가 화면에 보일 때까지 기다린다 -> 보였는지."""
        self.js("window.__hz.store.set({panel: %s})" % json.dumps(name))
        if expect is None:
            pump(0.5)
            return True
        expects = [expect] if isinstance(expect, str) else list(expect)
        return wait_for(lambda: all(e in self.text() for e in expects), timeout)

    # -- 명령·읽기
    def cmd(self, name, args=None):
        """웹과 같은 길: 프로젝트에 묶인 명령은 웹이 본 프로젝트 ID를 싣는다."""
        from hazop.shell import api
        project = self.engine.project_id() if name.startswith(api.PROJECT_BOUND) else None
        return self.engine.dispatch(name, args or {}, project=project, via_web=project is not None)

    def read(self, *parts, query=None):
        from hazop.shell import api
        r = api.ReadApi(self.engine).read([str(p) for p in parts], query or {})
        return None if r is None else json.loads(r.body.decode("utf-8"))

    def mark(self):
        return len(self.events)

    def events_since(self, mark, name=None):
        evs = [e for e in self.events[mark:] if e.get("t") == "event"]
        return [e["data"] for e in evs if name is None or e.get("name") == name]

    def wait_jobs(self, mark, timeout=300.0):
        """mark 뒤에 시작한 작업이 모두 끝나기를 Qt 사건을 돌리며 기다린다 -> (끝난 결과 목록, 실패 목록)."""
        wait_for(lambda: not self.engine.running_jobs(), timeout)
        pump(0.5)
        return self.events_since(mark, "job.done"), self.events_since(mark, "job.failed")


# ---------------------------------------------------------------- 입력 자료

def sample_drawio(drawing):
    from hazop import paths
    src = [p for p in glob.glob(paths.folder("references", "pid-samples", "*")) if drawing in os.path.basename(p)][0]
    return glob.glob(os.path.join(src, "*.drawio"))[0]


def copy_in(run, src, folder=False):
    """입력을 임시 폴더로 복사한다. folder면 원본 폴더째(drawio 옆의 쪽 SVG가 함께 있어야 도면 위 표시를 만든다)."""
    dst = os.path.join(run.tmp, "inputs", os.path.basename(os.path.dirname(src)) if folder else "")
    if folder:
        shutil.copytree(os.path.dirname(src), dst, dirs_exist_ok=True)
    else:
        os.makedirs(dst, exist_ok=True)
        shutil.copy2(src, dst)
    return os.path.join(dst, os.path.basename(src))


def gid_of(run, number):
    names = run.engine.graph_names()
    hits = [g for g in names if number in g]
    if not hits:
        raise AssertionError("그래프에 %s가 없음: %s" % (number, sorted(names)))
    return hits[0]


# ---------------------------------------------------------------- 시나리오

def n1_register(run, c):
    f = copy_in(run, sample_drawio("SNP-M-101"), folder=True)
    run.engine.hooks["pick_files"] = lambda: [f]
    m = run.mark()
    r = run.cmd("register.pick")
    c.need("register.pick이 작업을 시작함", r["ok"] and r["data"].get("jobs"), r)
    done, failed = run.wait_jobs(m)
    c.need("등록·추출 작업이 끝남", done and not failed, failed)
    res = done[-1]["result"]
    c.ok("등록됨(outcome registered)", res.get("outcome") == "registered", res)
    c.ok("AI 검토는 꺼져 있어 돌지 않음", (res.get("ai_review") or {}).get("ran") is False, res.get("ai_review"))
    run.state["m101"] = res.get("material_id")
    gid = gid_of(run, "SNP-M-101")
    name = run.engine.graph_names()[gid]
    from hazop import paths
    c.ok("추출 파일(extraction.json)", os.path.isfile(os.path.join(paths.output_root("extract"), name, "extraction.json")), name)
    c.ok("그래프 파일(graph.json)", os.path.isfile(os.path.join(paths.output_root("graph"), name, "graph.json")), name)
    drawings = run.read("drawings") or {}
    c.ok("도면 목록에 보임(drawings 읽기)", any(gid in json.dumps(d, ensure_ascii=False) for d in drawings.get("drawings", [])),
         json.dumps(drawings, ensure_ascii=False)[:300])
    c.ok("화면: 도면 패널에 도면 이름", run.panel("drawings", "SNP-M-101"), run.text()[-300:])


class StubReview:
    """추출 뒤 AI 검토의 가짜 연결: 물은 항목마다 첫 칸에 고정 값을 답한다(실제 구독 호출 없음)."""

    def __init__(self):
        self.requests = []
        outer = self

        class Client:
            def describe(self):
                return {"via": "subscription", "model": "fixed"}

            def analyze(self, request):
                outer.requests.append(request)
                items = json.loads(request["context"])["items"]
                answers = []
                for it in items:
                    f = it["ask"][0]
                    value = {"tag": "SCN-AI-%s" % it["item_id"][-3:], "kind": "manual_valve", "normal_position": "NO",
                             "fail_position": "FC", "to_system": "CV",
                             "connection": (it.get("partners") or [{"id": "none"}])[0]["id"]}.get(f)
                    if value is not None:
                        answers.append({"item_id": it["item_id"], "field": f, "values": [value], "confidence": 0.9, "reason": "가짜 답"})
                return {"status": "completed", "error_kind": None, "output": {"answers": answers}, "via": "fixed"}

            def cancel(self):
                pass
        self.client = Client()

    def status(self):
        return {"state": "ok", "can_start": True}

    def make_client(self):
        return self.client


def n2_ai_review_extract(run, c):
    r = run.cmd("extract.set_ai_review", {"enabled": True, "cap": 5})
    c.need("AI 검토 켬(extract.set_ai_review)", r["ok"], r)
    stub, real_ai = StubReview(), run.engine.ai
    run.engine.ai = stub
    try:
        f = copy_in(run, sample_drawio("SNP-M-102"), folder=True)
        run.engine.hooks["pick_files"] = lambda: [f]
        m = run.mark()
        r = run.cmd("register.pick")
        c.need("등록 시작", r["ok"], r)
        done, failed = run.wait_jobs(m)
    finally:
        run.engine.ai = real_ai
        run.cmd("extract.set_ai_review", {"enabled": False})
    c.need("등록·추출·AI 검토 작업이 끝남", done and not failed, failed)
    res = done[-1]["result"]
    review = res.get("ai_review") or {}
    run.state["m102"] = res.get("material_id")
    c.ok("AI 검토가 돌았음(ran)", review.get("ran") is True, review)
    c.ok("도면당 상한(5) 안에서 부름", 1 <= len(stub.requests) <= 5, len(stub.requests))
    gid = gid_of(run, "SNP-M-102")
    run.state["g102"] = gid
    name = run.engine.graph_names()[gid]
    from hazop.extract import ai_review
    c.ok("AI 후보 파일 저장", os.path.isfile(ai_review.store_path(name)), ai_review.store_path(name))
    view = run.read("aireview", gid) or {}
    ids = [it["cand_id"] for g in view.get("groups", []) for it in g.get("items", []) if it.get("cand_id")]
    c.ok("aireview 읽기에 제안 후보가 보임", (view.get("counts") or {}).get("proposed", 0) >= 1 and ids, json.dumps(view, ensure_ascii=False)[:400])
    c.ok("화면: AI 검토 패널", run.panel("aireview", "AI 검토"), run.text()[-300:])
    if ids:
        m = run.mark()
        r = run.cmd("aireview.reject", {"graph_id": gid, "ver": view["ver"], "cand_ids": ids})
        c.ok("후보를 사람이 거절(aireview.reject)", r["ok"], r)
        run.wait_jobs(m, 60)
        counts = (run.read("aireview", gid) or {}).get("counts") or {}
        c.ok("거절이 저장됨(제안 0, 거절 %d)" % len(ids), counts.get("proposed") == 0 and counts.get("rejected") == len(ids), counts)
    run.state["ai_review"] = {"calls": len(stub.requests), "candidates": len(ids)}


def n3_titleblock(run, c):
    tb = run.read("titleblock") or {}
    row = next((r for r in tb.get("rows", []) if r.get("material_id") == run.state["m102"]), None)
    c.need("표제란 행(SNP-M-102)", row, json.dumps(tb, ensure_ascii=False)[:400])
    c.ok("화면: 표제란 패널에 후보 번호", run.panel("titleblock", "SNP-M-102"), run.text()[-300:])
    fields = {f["field"]: f["candidate"] for f in row["fields"] if f.get("candidate")}
    c.need("세 칸 모두 후보가 있음", len(fields) == 3, fields)
    m = run.mark()
    r = run.cmd("titleblock.confirm", {"material_id": row["material_id"], "ver": row["ver"], "fields": fields})
    c.need("titleblock.confirm", r["ok"], r)
    done, failed = run.wait_jobs(m)
    c.ok("다시 추출 작업 실패 없음", not failed, failed)
    row2 = next(r for r in (run.read("titleblock") or {})["rows"] if r["material_id"] == run.state["m102"])
    c.ok("세 칸 확정(state confirmed)", row2.get("state") == "confirmed" and all(f.get("value") for f in row2["fields"]), row2)
    c.ok("등록 버전이 올라감", row2.get("version", 0) > row.get("version", 0), (row.get("version"), row2.get("version")))
    gid = gid_of(run, "SNP-M-102")
    run.state["g102"] = gid
    from hazop import paths
    name = run.engine.graph_names()[gid]
    with open(os.path.join(paths.output_root("graph"), name, "graph.json"), encoding="utf-8") as fh:
        g = json.load(fh)
    c.ok("그래프 source.drawing_number가 확정값", (g.get("source") or {}).get("drawing_number") == fields["drawing_number"], g.get("source"))
    sc = run.read("sheetconf", gid) or {}
    c.ok("쪽 확정의 '등록 단계 미확인'이 사라짐", not [u for u in sc.get("unconfirmed", []) if u.get("reason") == "registration_unknown"],
         sc.get("unconfirmed"))


def n4_edit(run, c):
    gid = run.state["g102"]
    from hazop import paths
    name = run.engine.graph_names()[gid]
    with open(os.path.join(paths.output_root("graph"), name, "graph.json"), encoding="utf-8") as fh:
        g = json.load(fh)
    target = next(n for n in g["nodes"] if n.get("kind") == "manual_valve" and n.get("tag"))
    lid, old = target["local_id"], target["tag"]
    item = run.read("edit", gid, "item", lid)
    c.need("고칠 항목 읽기(edit/<gid>/item)", item and item.get("ok"), item)
    new = old + "A"
    m = run.mark()
    r = run.cmd("edit.apply", {"graph_id": gid, "ver": item["ver"], "op": "set_tag", "local_id": lid,
                               "value": {"tag": new}, "base": item["base"]})
    c.need("edit.apply set_tag", r["ok"], r)
    run.wait_jobs(m)

    def tag_now():
        name_ = run.engine.graph_names()[gid]
        with open(os.path.join(paths.output_root("graph"), name_, "graph.json"), encoding="utf-8") as fh_:
            return next(n for n in json.load(fh_)["nodes"] if n["local_id"] == lid).get("tag")
    c.ok("그래프에 고친 태그", tag_now() == new, tag_now())
    from hazop.extract import corrections
    c.ok("사람 수정 기록 저장", os.path.isfile(corrections.store_path(name)), corrections.store_path(name))
    ed = run.read("edit", gid)
    c.ok("화면: 도면 화면 열림(도면 고치기 단추)", run.cmd("sheet.open", {"graph_id": gid})["ok"])
    last = (ed.get("undoable") or [None])[-1] if ed else None
    op_id = last.get("op_id") if isinstance(last, dict) else last
    c.need("되돌릴 고침이 있음", op_id, ed and ed.get("undoable"))
    m = run.mark()
    r = run.cmd("edit.undo", {"graph_id": gid, "ver": ed["ver"], "op_id": op_id})
    c.ok("edit.undo", r["ok"], r)
    run.wait_jobs(m)
    c.ok("되돌린 뒤 원래 태그", tag_now() == old, tag_now())
    ed = run.read("edit", gid)
    m = run.mark()
    r = run.cmd("edit.redo", {"graph_id": gid, "ver": ed["ver"]})
    c.ok("edit.redo", r["ok"], r)
    run.wait_jobs(m)
    c.ok("다시 하기 뒤 고친 태그", tag_now() == new, tag_now())
    run.state["edited"] = {"local_id": lid, "tag": new}


def n5_sheet_confirm(run, c):
    gid = run.state["g102"]
    sc = run.read("sheetconf", gid) or {}
    c.need("확정 조건: 미확인 0", sc.get("unconfirmed_total") == 0, sc.get("unconfirmed"))
    c.need("확정 조건: 위치 없음 0", sc.get("unplaced_total") == 0, sc.get("unplaced"))
    r = run.cmd("sheet.compare", {"graph_id": gid, "ver": sc["ver"], "rev": sc["rev"]})
    c.need("sheet.compare(원본과 견줌)", r["ok"], r)
    sc = run.read("sheetconf", gid)
    r = run.cmd("sheet.confirm", {"graph_id": gid, "ver": sc["ver"], "rev": sc["rev"]})
    c.need("sheet.confirm", r["ok"], r)
    sc = run.read("sheetconf", gid)
    c.ok("쪽 상태 confirmed", sc.get("state") == "confirmed", sc.get("state"))
    from hazop.extract import confirmation
    name = run.engine.graph_names()[gid]
    path = confirmation.store_path(name)
    c.ok("쪽 확정 기록 파일", os.path.isfile(path), path)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            c.ok("확정자는 검토자 이름", REVIEWER in fh.read())
    c.ok("화면: 도면 패널에 확정 표시", run.panel("drawings", "확정"), run.text()[-300:])


def n6_chat_path(run, c):
    from hazop.chat import context, tools
    ctx = context.load_context(run.engine.project_id())
    start, end = "RC-PZ01", run.state.get("edited", {}).get("tag") or "RC-V111"
    result = tools.trace_path(ctx, start=start, end=end)
    data = result.get("data") if isinstance(result, dict) else None
    c.need("실제 그래프에서 경로를 찾음(trace_path)", data and data.get("path", {}).get("found"), json.dumps(result, ensure_ascii=False)[:400])
    ref = data["path"]["path_ref"]
    ids = [s["id"] for s in data["path"]["steps"]]
    run.tool_ids = {"component": set(ids)}
    run.queue.append(([("trace_path", result)], {"text": "%s에서 %s까지 경로입니다." % (start, end),
                                                   "paths": [{"label": "%s → %s" % (start, end), "path_ref": ref}]}))
    m = run.mark()
    r = run.cmd("chat.ask", {"text": "%s에서 %s까지 경로 보여줘" % (start, end)})
    c.need("chat.ask", r["ok"], r)
    c.ok("채팅 세션이 질문을 받음", wait_for(lambda: run.sessions and run.sessions[-1].asked, 10))
    wait_for(lambda: run.events_since(m, "chat.answer"), 15)
    answers = run.events_since(m, "chat.answer")
    c.need("답 카드(chat.answer)", answers, [e.get("name") for e in run.events[m:] if e.get("t") == "event"])
    card = answers[-1].get("card") or {}
    paths_ = card.get("paths") or []
    c.ok("카드에 경로 하나", len(paths_) == 1, card)
    c.ok("경로 표시(marks)가 도면 위 자리를 가리킴", paths_ and paths_[0].get("marks"), paths_)
    c.ok("화면: 채팅 답 글", wait_for(lambda: "경로입니다" in run.text(), 10), run.text()[-300:])
    run.state["chat_path_steps"] = len(ids)


def n7_chat_nodes(run, c):
    from hazop.app import project_ctx
    from hazop.study import node_tools, nodes
    pid = run.engine.project_id()
    pg = project_ctx.project_graph(pid)
    ns = nodes.load(pg) or nodes.new_set(pg)
    cands = node_tools.make_candidates(pg, ns, granularity="normal", limit=30)["candidates"][:2]
    c.need("구간 후보가 있음", cands, "후보 0")
    run.queue.append(([], {"text": "대표 구간 둘을 만들었습니다.", "actions": [
        {"action": "nodes.apply", "args": {"set_rev": ns.get("set_rev", 0),
                                           "ops": [{"op": "add", "cand_id": x["cand_id"], "name": "시나리오 구간 %d" % (i + 1)}
                                                   for i, x in enumerate(cands)]}, "why": "대표 구간"}]}))
    m = run.mark()
    r = run.cmd("chat.ask", {"text": "대표 구간 둘 만들어 줘"})
    c.need("chat.ask", r["ok"], r)
    wait_for(lambda: run.events_since(m, "chat.actions"), 15)
    view = run.read("nodes") or {}
    made = [n for n in view.get("nodes", []) if str(n.get("name", "")).startswith("시나리오 구간")]
    c.need("채팅 동작으로 구간 둘이 생김", len(made) == 2, json.dumps(view, ensure_ascii=False)[:400])
    ids = [n["node_id"] for n in made]
    run.queue.append(([], {"text": "두 구간을 확정할까요?", "actions": [
        {"action": "nodes.confirm", "args": {"node_ids": ids}, "why": "확정"}]}))
    m = run.mark()
    run.cmd("chat.ask", {"text": "두 구간 확정해 줘"})
    wait_for(lambda: run.events_since(m, "chat.actions"), 15)
    items = [i for e in run.events_since(m, "chat.actions") for i in e.get("items", [])]
    tokens = [i["token"] for i in items if i.get("token")]
    c.need("확정은 확인 상자(토큰)로 묻는다", tokens, items or [(e.get("name"), e.get("data")) for e in run.events[m:] if e.get("t") == "event"])
    c.ok("화면: 채팅에 확인 상자", wait_for(lambda: "실행" in run.text(), 10), run.text()[-300:])
    r = run.cmd("chat.action.approve", {"token": tokens[0]})
    c.need("chat.action.approve", r["ok"], r)
    view = run.read("nodes") or {}
    states = {n["node_id"]: n.get("state") for n in view.get("nodes", []) if n["node_id"] in ids}
    c.ok("두 구간 확정", set(states.values()) == {"confirmed"}, states)
    path = nodes.store_path(pid, pg.get("graph_id") or "project-%s" % pid) if hasattr(nodes, "store_path") else None
    c.ok("구간 파일 저장", path is None or os.path.isfile(path) or glob.glob(os.path.join(nodes.store_dir(), "*", "*.json")), path)
    c.ok("화면: 구간 패널에 이름", run.panel("nodes", "시나리오 구간 1"), run.text()[-300:])
    run.state["node_ids"] = ids


@contextlib.contextmanager
def fake_analysis(run):
    from unittest import mock
    from tests.test_shell_results import FakeAi, fake_run_unit
    base = fake_run_unit()

    def unit(client, u, ctx, devs, at):
        out = base(client, u, ctx, devs, at)   # 항목 ID는 프로젝트 안에서 겹치면 안 된다(겹치면 칸이 격리됨): 구간 번호를 넣는다
        for cell in (out.get("cells") or {}).values():
            for e in cell.get("entries") or []:
                e["entry_id"] = "%s-%s" % (e["entry_id"], u["node_id"])
        return out
    real = run.engine.ai
    run.engine.ai = FakeAi()
    try:
        with mock.patch("hazop.study.ai_cells.run_unit", unit):
            yield
    finally:
        run.engine.ai = real


def n8_analysis(run, c):
    # 실제 구독이면 구간 하나만(호출 수를 줄인다). 가짜면 전체
    scope = {"scope": "node", "node_id": run.state["node_ids"][0]} if run.real_ai else {"scope": "all"}
    if run.real_ai:   # 임시 설정에만 남는 구독 이용 안내 확인(사용자 설정은 건드리지 않는다)
        run.cmd("results.ack_terms")
        wait_for(lambda: (run.engine.ai.status() or {}).get("can_start"), 60)
    plan = run.cmd("results.run_plan", scope)
    c.need("results.run_plan", plan["ok"], plan)
    calls = (plan["data"] or {}).get("calls")
    c.ok("호출 수를 미리 보여 줌", isinstance(calls, int) and calls > 0, plan["data"])
    if run.real_ai and isinstance(calls, int) and calls > REAL_AI_MAX_CALLS:
        raise Skip("실제 구독 호출이 %d회로 상한 %d를 넘음" % (calls, REAL_AI_MAX_CALLS))
    m = run.mark()
    with (contextlib.nullcontext() if run.real_ai else fake_analysis(run)):
        r = run.cmd("results.run", scope)
        c.need("results.run", r["ok"], r)
        done, failed = run.wait_jobs(m, 1800 if run.real_ai else 120)
    c.need("분석 작업이 끝남", done and not failed, failed)
    view = run.read("results") or {}
    filled = [x for x in view.get("cells", view.get("matrix", [])) if isinstance(x, dict) and (x.get("entries") or x.get("count"))]
    c.ok("칸이 채워짐(results 읽기)", filled or "entries" in json.dumps(view, ensure_ascii=False), json.dumps(view, ensure_ascii=False)[:400])
    from hazop.study import results
    files = glob.glob(os.path.join(os.path.dirname(results.store_path(run.engine.project_id(), "x")), "*.json"))
    c.ok("분석 결과 파일 저장", files, os.path.dirname(results.store_path(run.engine.project_id(), "x")))
    c.ok("화면: 분석 결과 행렬", run.panel("results") and wait_for(lambda: (run.js("document.querySelectorAll('.res-matrix .vg-cell').length") or 0) > 0, 20),
         run.text()[-300:])
    run.state["analysis"] = {"calls": calls, "real": run.real_ai, "summary": done[-1].get("result")}


def _cells(run):
    from hazop.study import nodes, results
    from hazop.app import project_ctx
    pg = project_ctx.project_graph(run.engine.project_id())
    ns = nodes.load(pg)
    doc, _fp = results.load_fp(ns)
    return ns, [x for x in (doc or {}).get("cells", []) if x.get("entries")]


def n9_judge(run, c):
    ns, all_cells = _cells(run)
    cells = []
    for cell in all_cells:      # 화면이 여는 칸만(results/cell 읽기가 되는 칸). 격리된 칸(quarantined)은 판정 대상이 아니다
        view = run.read("results", "cell", cell["node_id"], cell["deviation_id"])
        if view and view.get("ver") and view.get("editable"):
            cells.append(cell)
        elif view and view.get("ver"):
            run.state.setdefault("not_editable_cells", []).append({"cell": "%s/%s" % (cell["node_id"], cell["deviation_id"]),
                                                                   "why": view.get("not_editable_reason") or (view.get("cell") or {}).get("not_editable_reason")})
    run.state["cells"] = {"with_entries": len(all_cells), "editable": len(cells)}
    c.need("판정할 칸이 있음(화면이 여는 칸)", len(cells) >= 2, run.state["cells"])
    done = 0
    for cell in cells[:3]:
        view = run.read("results", "cell", cell["node_id"], cell["deviation_id"])
        for e in cell["entries"]:
            r = run.cmd("results.set_status", {"node_id": cell["node_id"], "deviation_id": cell["deviation_id"], "entry_id": e["entry_id"],
                                               "status": "approved", "reason": "", "ver": view["ver"], "set_rev": ns["set_rev"]})
            c.ok("승인 %s/%s" % (cell["node_id"], cell["deviation_id"]), r["ok"], r)
            if r["ok"]:
                view["ver"], done = r["data"]["ver"], done + 1
    cell = cells[-1]
    view = run.read("results", "cell", cell["node_id"], cell["deviation_id"])
    e = cell["entries"][0]
    r = run.cmd("results.set_status", {"node_id": cell["node_id"], "deviation_id": cell["deviation_id"], "entry_id": e["entry_id"],
                                       "status": "on_hold", "reason": "", "ver": view["ver"], "set_rev": ns["set_rev"]})
    c.ok("사유 없는 보류는 거절", not r["ok"], r)
    r = run.cmd("results.set_status", {"node_id": cell["node_id"], "deviation_id": cell["deviation_id"], "entry_id": e["entry_id"],
                                       "status": "on_hold", "reason": "현장 확인 필요", "ver": view["ver"], "set_rev": ns["set_rev"]})
    c.ok("사유 있는 보류", r["ok"], r)
    _ns, after = _cells(run)
    statuses = [x.get("status") for cl in after for x in cl["entries"]]
    c.ok("파일에 승인이 저장됨", statuses.count("approved") >= 1, statuses)
    c.ok("파일에 보류가 저장됨", "on_hold" in statuses, statuses)
    c.ok("화면: 머리 수치 '승인 %d'" % done, run.panel("results", "승인 %d" % done), run.text()[-300:])
    run.state["approved"] = done


def n10_excel(run, c):
    out = os.path.join(run.out, "exports", "results.xlsx")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    run.engine.hooks["save_path"] = lambda kind, name: out
    n_log = len(run.log.records)
    r = run.cmd("results.export_excel", {"scope": "all"})
    if not c.ok("표제란을 확정하지 않은 도면(SNP-M-101)이 있어도 내보냄", r["ok"], (r, run.log.since(n_log))):
        # 알려진 결함(보고서에 남김): 확정 번호가 없는 도면이 있으면 표지의 도면 목록에서 멈춘다. 그 도면도 확정한 뒤 다시 낸다
        tb = run.read("titleblock") or {}
        row = next(x for x in tb["rows"] if x["material_id"] == run.state["m101"])
        m = run.mark()
        r = run.cmd("titleblock.confirm", {"material_id": row["material_id"], "ver": row["ver"],
                                           "fields": {f["field"]: f["candidate"] for f in row["fields"] if f.get("candidate")}})
        c.ok("SNP-M-101 표제란도 확정", r["ok"], r)
        run.wait_jobs(m)
        r = run.cmd("results.export_excel", {"scope": "all"})
    c.need("results.export_excel", r["ok"] and not r["data"].get("cancelled"), r)
    c.ok("파일이 생김", os.path.isfile(out), out)
    c.ok("행 수가 1 이상", (r["data"].get("rows") or 0) >= 1, r["data"])
    try:
        import openpyxl
        wb = openpyxl.load_workbook(out, read_only=True)
        text = " ".join(str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v is not None)
        c.ok("Excel에 구간 이름", "시나리오 구간" in text, text[:300])
        c.ok("Excel에 판정(승인)", "승인" in text, text[:300])
    except ImportError:
        c.ok("openpyxl로 열기", False, "openpyxl 없음")


def n11_ie(run, c):
    ie = run.read("ie") or {}
    c.need("초기사건 읽기 가능", ie.get("available", True) is not False, json.dumps(ie, ensure_ascii=False)[:400])
    r = run.cmd("ie.suggest", {"ver": ie.get("ver", "none"), "rver": ie.get("rver"), "seen": {}})
    c.need("ie.suggest(규칙 초안)", r["ok"], r)
    ie = run.read("ie") or {}
    groups = ie.get("groups") or []
    c.ok("초안 그룹이 생김", groups or ie.get("unassigned"), json.dumps(ie, ensure_ascii=False)[:400])
    if not groups:
        first = ie.get("unassigned", [])[:1]
        members = [u["candidate_id"] for u in first]
        seen = {"member:%s" % u["candidate_id"]: u.get("fp") for u in first}
        r = run.cmd("ie.create_group", {"ver": ie["ver"], "rver": ie.get("rver"), "seen": seen, "name": "시나리오 그룹", "iecs": members})
        c.need("ie.create_group", r["ok"], r)
        ie = run.read("ie")
        groups = ie.get("groups") or []
    g = groups[0]
    seen = {"group:%s" % g["group_id"]: g["fp"]}
    r = run.cmd("ie.edit_group", {"ver": ie["ver"], "rver": ie.get("rver"), "seen": seen, "group_id": g["group_id"],
                                  "fields": {"name": "시나리오 그룹(고침)"}})
    if r["ok"] and isinstance(r.get("data"), dict) and r["data"].get("ask"):
        r = run.cmd("ie.edit_group", {"ver": ie["ver"], "rver": ie.get("rver"), "seen": seen, "group_id": g["group_id"],
                                      "fields": {"name": "시나리오 그룹(고침)"}, "confirmed": True, "confirm_groups": [g["group_id"]]})
    c.need("ie.edit_group(이름 고침)", r["ok"], r)
    from hazop.ie import store as ie_store
    path = ie_store.store_path(run.engine.project_id())
    c.ok("초기사건 파일에 고친 이름", os.path.isfile(path) and "시나리오 그룹(고침)" in open(path, encoding="utf-8").read(), path)
    c.ok("화면: 초기사건 패널에 그룹 이름", run.panel("ie", "시나리오 그룹(고침)"), run.text()[-300:])


def n12_handover(run, c):
    out = os.path.join(run.out, "exports", "IE-%s.xlsx" % PROJECT)
    run.engine.hooks["save_path"] = lambda kind, name: out
    run.engine.hooks["confirm_overwrite_files"] = lambda names: True
    ie = run.read("ie") or {}
    r = run.cmd("ie.export", {"ver": ie.get("ver", "none"), "rver": ie.get("rver")})
    c.need("ie.export(인계 묶음)", r["ok"] and not r["data"].get("cancelled"), r)
    c.ok("Excel 파일", os.path.isfile(out), out)
    js = os.path.splitext(out)[0] + ".json"
    c.ok("JSON 파일(같은 이름)", os.path.isfile(js), js)
    if os.path.isfile(js):
        with open(js, encoding="utf-8") as fh:
            doc = json.load(fh)
        c.ok("JSON에 그룹", "시나리오 그룹(고침)" in json.dumps(doc, ensure_ascii=False), str(list(doc))[:200])


def n13_dexpi_export(run, c):
    gid = run.state["g102"]
    view = run.read("dexpi") or {}
    c.ok("dexpi 읽기에서 내보낼 수 있음", gid in json.dumps(view, ensure_ascii=False), json.dumps(view, ensure_ascii=False)[:400])
    out = os.path.join(run.out, "exports", "dexpi")
    os.makedirs(out, exist_ok=True)
    run.engine.hooks["save_dir"] = lambda kind: out
    run.engine.hooks["confirm_overwrite_files"] = lambda names: True
    m = run.mark()
    r = run.cmd("dexpi.export", {"graph_ids": [gid]})
    c.need("dexpi.export", r["ok"], r)
    done, failed = run.wait_jobs(m)
    c.need("내보내기 작업이 끝남", done and not failed, failed)
    xml = glob.glob(os.path.join(out, "*.dexpi.xml"))
    c.need("DEXPI XML 파일", xml, os.listdir(out))
    with open(xml[0], encoding="utf-8") as fh:
        text = fh.read()
    c.ok("XML에 확정 도면 번호", "SNP-M-102" in text)
    c.ok("XML에 고친 태그", run.state.get("edited", {}).get("tag", "?") in text, run.state.get("edited"))
    c.ok("manifest.json", os.path.isfile(os.path.join(out, "manifest.json")), os.listdir(out))
    run.state["dexpi_xml"] = xml[0]


def n14_dexpi_import(run, c):
    r = run.cmd("project.set", {"project_id": IMPORT_PROJECT})
    c.need("다른 프로젝트로 바꿈", r["ok"], r)
    wait_for(lambda: run.js("window.__hz.store.get().app.project_id") == IMPORT_PROJECT, 15)
    try:
        f = copy_in(run, run.state["dexpi_xml"])
        run.engine.hooks["pick_files"] = lambda: [f]
        m = run.mark()
        r = run.cmd("register.pick")
        c.need("XML 등록 시작", r["ok"], r)
        done, failed = run.wait_jobs(m)
        c.need("가져오기 작업이 끝남", done and not failed, failed)
        c.ok("가져온 그래프가 생김", run.engine.graph_names(), run.engine.graph_names())
        mid = done[-1]["result"].get("material_id")
        tb = run.read("titleblock") or {}
        row = next((r for r in tb.get("rows", []) if r.get("material_id") == mid), None)
        cands = {f["field"]: f.get("candidate") for f in (row or {}).get("fields", [])}
        c.need("표제란 후보에 내보낸 도면 번호(DrawingNumber)", cands.get("drawing_number") == "SNP-M-102", cands)
        m = run.mark()
        r = run.cmd("titleblock.confirm", {"material_id": mid, "ver": row["ver"], "fields": {k: v for k, v in cands.items() if v}})
        c.need("가져온 도면의 표제란 확정", r["ok"], r)
        run.wait_jobs(m)
        names = run.engine.graph_names()
        gid = next((g for g in names if g == "graph-SNP-M-102"), None)
        c.ok("표제란 확정 뒤 그래프 ID가 graph-SNP-M-102", gid, names)
        if gid:
            from hazop import paths
            with open(os.path.join(paths.output_root("graph"), names[gid], "graph.json"), encoding="utf-8") as fh:
                g = json.load(fh)
            tags = {n.get("tag") for n in g["nodes"]}
            c.ok("가져온 그래프에 고친 태그", run.state["edited"]["tag"] in tags, sorted(t for t in tags if t)[:20])
        c.ok("화면: 도면 패널에 가져온 도면", run.panel("drawings", "SNP-M-102"), run.text()[-300:])
    finally:
        run.cmd("project.set", {"project_id": PROJECT})
        wait_for(lambda: run.js("window.__hz.store.get().app.project_id") == PROJECT, 15)


def n15_kg_docs(run, c):
    kg = run.read("kg") or {}
    c.ok("지식그래프 읽기", kg, kg)
    c.ok("화면: 지식그래프 패널", run.panel("kg", "지식그래프"), run.text()[-300:])
    pdf = glob.glob(os.path.join(REPO, "tests", "fixtures", "docextract", "SNP-DOC-102*.pdf"))
    c.need("설계 문서 표본", pdf, "tests/fixtures/docextract")
    f = copy_in(run, pdf[0])
    run.engine.hooks["pick_doc"] = lambda: [f]
    m = run.mark()
    r = run.cmd("docs.add")
    c.need("docs.add", r["ok"], r)
    done, failed = run.wait_jobs(m)
    c.need("문서 등록·지식 추출이 끝남", done and not failed, failed)
    docs = run.read("docs") or {}
    c.ok("설계 문서 목록에 보임", "SNP-DOC-102" in json.dumps(docs, ensure_ascii=False), json.dumps(docs, ensure_ascii=False)[:300])
    c.ok("화면: 설계 문서 패널", run.panel("docs", "SNP-DOC-102"), run.text()[-300:])
    kg = run.read("kg", "graph", query={"expand": "all"}) or {}
    c.ok("지식그래프에 노드", kg.get("nodes"), json.dumps(kg, ensure_ascii=False)[:300])
    probe = next((n.get("label") or n.get("name") for n in kg.get("nodes", []) if n.get("label") or n.get("name")), "RC-PZ01")
    found = run.read("kg", "search", query={"q": probe}) or {}
    c.ok("지식그래프 찾기(%s)" % probe, found.get("hits"), json.dumps(found, ensure_ascii=False)[:300])


FUNCS = {"N1": n1_register, "N2": n2_ai_review_extract, "N3": n3_titleblock, "N4": n4_edit, "N5": n5_sheet_confirm,
         "N6": n6_chat_path, "N7": n7_chat_nodes, "N8": n8_analysis, "N9": n9_judge, "N10": n10_excel, "N11": n11_ie,
         "N12": n12_handover, "N13": n13_dexpi_export, "N14": n14_dexpi_import, "N15": n15_kg_docs}


# ---------------------------------------------------------------- 실행·보고

def render(checks, meta):
    lines = ["# 새 화면 시나리오 점검", "",
             "- 커밋: %s" % meta["commit"], "- 시각: %s" % meta["started"], "- 인터프리터: `%s`" % meta["python"],
             "- 방식: 오프스크린(QT_QPA_PLATFORM=%s), AI %s" % (meta["qpa"], "실제 구독(N8)" if meta["real_ai"] else "가짜"), "",
             "| 번호 | 시나리오 | 판정 | 확인 | 초 |", "| --- | --- | --- | --- | --- |"]
    for c in checks:
        n_ok = sum(1 for i in c.items if i["ok"])
        lines.append("| %s | %s | %s | %d/%d | %.1f |" % (c.sid, c.title, c.verdict(), n_ok, len(c.items), c.seconds))
    lines.append("")
    for c in checks:
        lines.append("## %s %s: %s" % (c.sid, c.title, c.verdict()))
        if c.skipped:
            lines.append("- 건너뜀: %s" % c.skipped)
        for i in c.items:
            lines.append("- [%s] %s%s" % ("x" if i["ok"] else " ", i["what"], "" if i["ok"] else " — %s" % i["detail"].replace("\n", " ")))
        if c.error:
            lines += ["", "```", c.error.strip()[-1500:], "```"]
        lines.append("")
    return "\n".join(lines)


def run_all(out, only=None, keep_temp=False, real_ai=False):
    import subprocess
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shell-scn-")
    env_keys = ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT", "HAZOP_DEBUG")
    saved = {k: os.environ.get(k) for k in env_keys}
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    os.environ["HAZOP_DEBUG"] = "1"
    os.makedirs(os.environ["HAZOP_WORK_ROOT"])
    meta = {"started": datetime.datetime.now().isoformat(timespec="seconds"), "python": sys.executable,
            "qpa": os.environ.get("QT_QPA_PLATFORM"), "real_ai": real_ai,
            "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()}
    run = Run(tmp, out, real_ai=real_ai)
    checks, wanted = [], set(only or FUNCS)
    try:
        run.open()
        for sid, title, _mode, deps in SCENARIOS:
            c = Check(sid, title)
            checks.append(c)
            if sid not in wanted:
                c.skipped = "--only에 없음"
                continue
            failed_dep = [d for d in deps if not next(x for x in checks if x.sid == d).passed]
            if failed_dep:
                c.skipped = "앞 시나리오(%s)가 통과하지 않음" % ",".join(failed_dep)
                continue
            t0 = time.monotonic()
            try:
                FUNCS[sid](run, c)
            except Skip as exc:
                c.skipped = str(exc)
            except AssertionError:
                pass
            except Exception:  # noqa: BLE001 - 시나리오 하나의 오류는 기록하고 다음으로 간다
                c.error = traceback.format_exc()
            c.seconds = time.monotonic() - t0
            print("%s %s: %s" % (sid, title, c.verdict()), flush=True)
    finally:
        try:
            run.close()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            if keep_temp:
                print("임시 폴더를 남김: %s" % tmp)
            else:
                shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(render(checks, meta))
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "state": run.state, "scenarios": [{"id": c.sid, "title": c.title, "verdict": c.verdict(), "seconds": round(c.seconds, 1),
                                                                    "checks": c.items, "skipped": c.skipped, "error": c.error} for c in checks]},
                  fh, ensure_ascii=False, indent=1, default=str)
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="보고서 폴더(report.md·report.json·내보낸 파일)")
    ap.add_argument("--only", help="쉼표로 이은 번호(예: N1,N2). 기대는 앞 시나리오도 함께 넣어야 한다")
    ap.add_argument("--list", action="store_true", help="시나리오 목록만 출력")
    ap.add_argument("--keep-temp", action="store_true", help="임시 작업 루트를 지우지 않음")
    ap.add_argument("--real-ai", action="store_true", help="N8 일괄 분석만 실제 구독으로 부름(호출 %d회까지)" % REAL_AI_MAX_CALLS)
    a = ap.parse_args(argv)
    if a.list:
        for sid, title, mode, deps in SCENARIOS:
            print("%-4s %-10s %s%s" % (sid, mode, title, " (앞: %s)" % ",".join(deps) if deps else ""))
        return 0
    if not a.out:
        ap.error("--out이 필요함")
    only = [s.strip().upper() for s in a.only.split(",")] if a.only else None
    checks = run_all(os.path.abspath(a.out), only, a.keep_temp, a.real_ai)
    bad = [c for c in checks if c.verdict() == "실패"]
    print("보고서: %s" % os.path.join(os.path.abspath(a.out), "report.md"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
