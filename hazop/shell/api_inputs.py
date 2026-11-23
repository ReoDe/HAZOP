"""수락한 입력 연산(나누기·배관 지정)을 도면에 반영하는 짓기 작업과 그 차례(입력 연산 U2 셸 몫, 설계 fix-input-ops-design.md §11.3·§11.5).

읽기 토픽 `inputs`, 명령 `inputs.hold`(대기열이 열려 있는 동안 짓기를 미룸)·`inputs.build`(지금 짓기).

- AI 후보 수락·되돌리기(api_aireview._decide_locked)는 그래프를 그 자리에서 다시 만들지 않고 `note(engine, name)`만 부른다. 그 도면은
  '반영 대기'가 되고(sheet_refresh.defer: 다음 수락·읽기가 그 자리에서 다시 만들지 않음) 마지막 수락 뒤 QUIET초 조용하거나 대기열을 닫으면
  도면마다 짓기 작업 하나가 돈다.
- 짓기 작업: 기준 추출(corrections.ensure_base)은 도면 잠금 밖에서, 그래프·지식그래프 다시 만들기(sheet_refresh.refresh)만 잠금 안에서.
  짓는 중 그 도면에 수락이 오면 should_stop으로 멈추고(지은 것은 쓰지 않음) 다시 조용해지면 처음부터 짓는다.
- 상태는 메모리에만 둔다(새 저장 꼴 없음). 앱을 닫을 때 남은 것은 열 때 `scan_on_open`이 수정 기록에서 다시 찾아 '다음에 할 일'에 올린다
  (짓지 않은 입력 연산이 있는 도면). 그때는 저절로 짓지 않고 사람이 '다시 읽기'를 누른다.
"""

import logging
import threading
import time

LOG = logging.getLogger(__name__)

TOPICS = ("inputs",)
QUIET = 10.0          # 마지막 수락 뒤 이만큼 조용하면 짓는다(초, 총괄 결정)
JOB_LABEL = "도면 다시 읽기"


def _api():
    from hazop.shell import api
    return api


class Builds:
    def __init__(self, engine, quiet=QUIET):
        self.engine = engine
        self.quiet = quiet
        self.lock = threading.Lock()
        self.due = {}          # 이름 → 마지막 수락 시각(monotonic)
        self.running = {}      # 이름 → 멈춤 신호(threading.Event)
        self.left = set()      # 열 때 찾은, 짓지 않은 입력 연산이 남은 도면(사람이 누를 때까지 짓지 않음)
        self.hold = False
        self.timer = None

    # ------------------------------------------------------------ 알림
    def note(self, name):
        """수락·되돌리기로 이 도면의 수정 기록이 바뀌었다. 짓는 중이면 멈추고, 조용해지면 다시 짓는다."""
        from hazop.shell import sheet_refresh
        sheet_refresh.defer(name)
        with self.lock:
            self.due[name] = time.monotonic()
            self.left.discard(name)
            ev = self.running.get(name)
        if ev is not None:
            ev.set()
        self._arm()

    def set_hold(self, on):
        with self.lock:
            self.hold = bool(on)
        if not on:
            self.flush()

    def flush(self, names=None):
        """기다리는 도면(names를 주면 그것만)을 지금 짓는다. 열 때 찾은 도면도 names로 주거나 names=None이면 함께."""
        with self.lock:
            pick = [n for n in (names if names is not None else list(self.due) + sorted(self.left)) if n not in self.running]
            for n in pick:
                self.due.pop(n, None)
                self.left.discard(n)
                self.running[n] = threading.Event()
        for n in pick:
            self._start(n)
        return pick

    def waiting(self):
        """짓기를 기다리는 도면 이름(돌고 있는 것은 빼고)."""
        with self.lock:
            return sorted((set(self.due) | self.left) - set(self.running))

    def busy(self, name):
        with self.lock:
            return name in self.running or name in self.due

    # ------------------------------------------------------------ 차례
    def _arm(self):
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
            self.timer = threading.Timer(self.quiet, self._tick)
            self.timer.daemon = True
            self.timer.start()

    def _tick(self):
        now = time.monotonic()
        with self.lock:
            if self.hold:
                return                                   # 대기열을 닫으면 set_hold(False)가 짓는다
            ripe = [n for n, t in self.due.items() if now - t >= self.quiet - 0.05 and n not in self.running]
            rest = any(n not in ripe for n in self.due)
        if ripe:
            self.flush(ripe)
        if rest:
            self._arm()

    def _start(self, name):
        engine = self.engine
        ev = self.running[name]

        def work(progress):
            from hazop.extract import corrections
            from hazop.shell import sheet_refresh
            gid = next((g for g, n in engine.graph_names().items() if n == name), None)
            shown = _shown(engine, gid) if gid else "도면"
            stop = lambda: ev.is_set() or engine.stop_requested()      # noqa: E731
            again, ended = False, False
            try:
                progress("%s 도면 다시 읽는 중" % shown)
                state = corrections.ensure_base(name, should_stop=stop)     # 도면 잠금 밖(큰 쪽은 수십 초)
                if ev.is_set():
                    again = True
                    return {"graph_id": gid, "state": "stopped"}
                with sheet_refresh.lock(name):                              # 그래프·지식그래프 다시 만들기만 잠금 안에서
                    if ev.is_set():
                        again = True
                        return {"graph_id": gid, "state": "stopped"}
                    sheet_refresh.undefer(name)
                    stale, notes, recheck = sheet_refresh.refresh(name)
                for text in list(notes) + list(recheck):           # 다시 만들기 실패(낡은 표시가 남아 다음 동작에서 다시 만듦)·구간 재확인 안내
                    engine.emit("app.notice", {"text": text})
                ended = True
                return {"graph_id": gid, "state": state, "graph_stale": stale, "notes": notes, "recheck": recheck}
            finally:
                if not ended and not again:
                    sheet_refresh.undefer(name)              # 짓기가 오류로 끝남: 낡은 그래프 표시를 보통처럼 다음 동작·열기에서 다시 만든다
                with self.lock:
                    self.running.pop(name, None)
                    if again or name in self.due:
                        self.due.setdefault(name, time.monotonic())
                        again = True
                if again:
                    self._arm()
                for t in ("aireview", "drawings", "sheetconf", "kg", "inputs"):
                    engine.changed(t, None)
                if gid:
                    engine.changed("sheet", gid)
        try:
            engine.start_job(JOB_LABEL, work, kind="graph_refresh")
        except Exception:  # noqa: BLE001 - 작업을 띄우지 못하면 다음 알림·다음 열기에서 다시 본다
            LOG.exception("도면 다시 읽기 작업을 띄우지 못함: %s", name)
            with self.lock:
                self.running.pop(name, None)
                self.due[name] = time.monotonic()


def _shown(engine, gid):
    from hazop.shell import api_drawings
    try:
        return api_drawings.display(engine, gid)
    except Exception:  # noqa: BLE001 - 진행 글의 이름 한 칸
        return "도면"


def of(engine):
    b = getattr(engine, "_input_builds", None)
    if b is None:
        b = engine._input_builds = Builds(engine)
    return b


def note(engine, name):
    of(engine).note(name)


def scan_on_open(engine):
    """열 때 한 번: 짓지 않은 입력 연산이 남은 도면을 찾아 '다음에 할 일'에 올린다(저절로 짓지 않음). → 찾은 이름 목록."""
    from hazop.extract import corrections
    found = []
    for name in sorted(set(engine.graph_names().values())):
        try:
            ops = (corrections.load(name) or {}).get("ops") or []
            if not any(corrections.is_input(o) for o in ops):
                continue
            if corrections.resolve(name)["inputs"]["waiting"]:
                found.append(name)
        except (OSError, ValueError, KeyError, TypeError):
            LOG.warning("입력 연산 확인 실패: %s", name, exc_info=True)
    b = of(engine)
    with b.lock:
        b.left = {n for n in found if n not in b.running}
    if found:
        engine.changed("inputs", None)
    return found


# ---------------------------------------------------------------- 읽기·명령
def summary(engine):
    b = of(engine)
    names = {n: g for g, n in engine.graph_names().items()}
    with b.lock:
        running = sorted(b.running)
        hold = b.hold
        left = sorted(b.left - set(b.running))
    waiting = b.waiting()
    row = lambda n: {"graph_id": names.get(n), "drawing_number": _shown(engine, names[n]) if names.get(n) else "도면"}    # noqa: E731
    return {"waiting": [row(n) for n in waiting if n in names], "running": [row(n) for n in running if n in names], "hold": hold,
            "left": [row(n) for n in left if n in names]}


def read(engine, parts, query):
    if parts == ["inputs"]:
        return _api()._json(summary(engine))
    return None


def _h_hold(engine, a):
    of(engine).set_hold(a["on"])
    return {"hold": bool(a["on"])}


def _h_build(engine, a):
    names = engine.graph_names()
    gid = a.get("graph_id")
    if gid and gid not in names:
        raise _api().CommandError("not_found", "없는 도면")
    started = of(engine).flush([names[gid]] if gid else None)
    engine.changed("inputs", None)
    return {"started": [g for g, n in names.items() if n in started]}


def register(commands):
    api = _api()
    if "inputs.hold" in commands:
        raise ValueError("명령 이름이 겹침: inputs.hold")
    commands["inputs.hold"] = api.Command({"on": (api.v_bool(), True)}, _h_hold,
                                          "대기열이 열려 있는 동안 도면 다시 읽기를 미룬다(닫으면 기다리던 도면을 바로 읽는다)")
    commands["inputs.build"] = api.Command({"graph_id": (api.v_str(1, 200), False)}, _h_build,
                                           "반영하지 않은 수락이 있는 도면을 지금 다시 읽는다(graph_id가 없으면 모두)")
