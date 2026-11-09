"""⑤ AI 분석 실행: 실행 상태 기계(기획서/AI연결-구독제.md §6.4)와 작업자 N개(§6.2, 결정 U8).

작업자는 ai_cells.run_unit(네트워크·파싱·근거 검증)만 부르고 UnitResult를 신호로 보낸다. results dict는 만지지 않는다.
병합(apply_unit)·저장은 신호를 받은 UI 스레드가 한다. 같은 대기열에서 호출 단위를 꺼내므로 동시 수가 달라도 부르는 단위는 같다.
"""

import collections
import threading
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QObject, Signal

from hazop.study import ai_cells, providers

_stamp_lock = threading.Lock()
_last_stamp = [datetime.min.replace(tzinfo=timezone.utc)]

# 실행 상태표(§6.4). 빈 칸(표에 없는 사건)은 무시한다. "호출 끝"에서 idle·closed로 갈 때는 받은 결과를 먼저 반영·저장한다.
TRANSITIONS = {
    "idle": {"start": "preflight", "close_wait": "closed", "close_now": "closed"},
    "preflight": {"check_ok": "calling", "check_fail": "idle", "cancel": "idle", "close_wait": "closed",
                  "close_now": "closed"},
    "calling": {"call_more": "calling", "call_last": "idle", "limit": "idle", "timeout": "killing", "cancel": "draining",
                "close_wait": "close_wait", "close_now": "killing_close"},
    "draining": {"call_more": "idle", "call_last": "idle", "limit": "idle", "timeout": "killing", "cancel": "killing",
                 "close_wait": "close_wait", "close_now": "killing_close"},
    "close_wait": {"call_more": "closed", "call_last": "closed", "limit": "closed", "timeout": "killing_close",
                   "close_now": "killing_close", "wait_expired": "killing_close"},
    "killing": {"close_wait": "killing_close", "close_now": "killing_close", "killed": "idle"},
    "killing_close": {"killed": "closed"},
    # 창이 닫기를 거절하면(저장 안 한 변경에서 '취소') 창은 열려 있으므로 다시 실행을 받는다. §6.4 표에 더한 유일한 전이
    "closed": {"close_refused": "idle"},
}
PROCESS_ALIVE = frozenset({"calling", "draining", "close_wait", "killing", "killing_close"})
# 하위 프로세스가 끝났다는 뜻의 사건. 프로세스가 살아 있는 상태에서 closed로 가는 전이는 이 사건으로만 일어난다
PROCESS_ENDED = frozenset({"call_more", "call_last", "limit", "killed"})


class RunMachine:
    """실행 하나의 수명. fire(사건)는 표대로 옮기고 새 상태를, 표에 없는 사건이면 None을 돌려준다(상태 그대로)."""

    def __init__(self):
        self.state = "idle"

    def fire(self, event):
        nxt = TRANSITIONS[self.state].get(event)
        if nxt is not None:
            self.state = nxt
        return nxt

    @property
    def busy(self):
        """확인 중이거나 호출이 살아 있음(새 실행을 받지 않음)."""
        return self.state not in ("idle", "closed")

    @property
    def alive(self):
        return self.state in PROCESS_ALIVE


def stamp():
    """UTC ISO 8601(마이크로초). 항목 ID에 들어가므로 같은 프로세스 안에서는 늘 앞 값보다 크다."""
    with _stamp_lock:
        t = max(datetime.now(timezone.utc), _last_stamp[0] + timedelta(microseconds=1))
        _last_stamp[0] = t
    return t.isoformat(timespec="microseconds").replace("+00:00", "Z")


class AiRunner(QObject):
    """jobs = [(unit, ctx)] (UI 스레드에서 준비). start() 뒤 unit마다 unit_started(unit)·unit_done(UnitResult)·
    progress(done, total)를 보내고, 작업자가 모두 끝나면 finished(reason)를 한 번 보낸다.

    reason: done(모두 부름) · cancelled(cancel로 남은 호출을 멈춤) · halted(providers.halts가 멈춤) · killed(kill).
    remaining은 끝난 뒤 아직 부르지 않은 호출 단위 목록이다(기술 설계 §11 3번 '남은 칸 이어서 실행'에 씀)."""

    unit_started = Signal(object)
    unit_done = Signal(object)
    progress = Signal(int, int)
    finished = Signal(str)

    def __init__(self, jobs, deviations, client, workers=1):
        super().__init__()
        self.jobs = list(jobs)
        self.deviations = deviations
        self.client = client
        self.workers = max(1, int(workers))
        self.remaining = []
        self.halted_by = None    # 멈춤을 부른 UnitResult
        self._queue = collections.deque(self.jobs)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._cancelled = self._killed = False
        self._kinds = []         # 끝난 순서의 error_kind(성공은 None)
        self._done = 0
        self._live = 0
        self._threads = []

    def start(self):
        total = len(self.jobs)
        self.progress.emit(0, total)
        n = min(self.workers, total)
        if n == 0:
            self.finished.emit("done")
            return
        self._live = n
        for i in range(n):
            # 데몬: '바로 끊고 닫기'에서 끊을 수 없는 클라이언트(API)가 앱 종료를 붙잡지 않게
            t = threading.Thread(target=self._work, name="ai-worker-%d" % i, daemon=True)
            self._threads.append(t)
        for t in self._threads:
            t.start()

    def cancel(self):
        """남은 호출을 부르지 않는다. 진행 중인 호출은 끝까지 받는다."""
        self._cancelled = True
        self._stop.set()

    def kill(self):
        """남은 호출을 멈추고 진행 중인 호출도 바로 끊는다. 클라이언트가 끊을 수 있으면 True."""
        self._killed = True
        self._stop.set()
        cancel = getattr(self.client, "cancel", None)
        if cancel is None:
            return False
        cancel()
        return True

    def is_running(self):
        with self._lock:
            return self._live > 0

    def calls_in_flight(self):
        """지금 부르고 있는 호출 수."""
        with self._lock:
            return len(self.jobs) - len(self._queue) - self._done if self._live > 0 else 0

    def wait(self, msecs=None):
        timeout = None if msecs is None else msecs / 1000.0
        for t in self._threads:
            t.join(timeout)
        return not self.is_running()

    def _next(self):
        with self._lock:
            if self._stop.is_set() or not self._queue:
                return None
            return self._queue.popleft()

    def _work(self):
        try:
            while True:
                job = self._next()
                if job is None:
                    break
                unit, ctx = job
                self.unit_started.emit(unit)
                ur = ai_cells.run_unit(self.client, unit, ctx, self.deviations, stamp())
                with self._lock:
                    self._done += 1
                    done = self._done
                    self._kinds.append(ur.get("error_kind"))
                    if providers.halts(self._kinds) and not self._stop.is_set():
                        self.halted_by = ur
                        self._stop.set()
                self.unit_done.emit(ur)
                self.progress.emit(done, len(self.jobs))
        finally:
            # 결과 신호를 모두 보낸 뒤 finished를 보낸다(UI 스레드가 받는 순서가 보내는 순서와 같다)
            with self._lock:
                self._live -= 1
                last = self._live == 0
                if last:
                    self.remaining = [u for u, _c in self._queue]
            if last:
                reason = ("killed" if self._killed else "halted" if self.halted_by is not None else
                          "cancelled" if self._cancelled and self.remaining else "done")
                self.finished.emit(reason)
