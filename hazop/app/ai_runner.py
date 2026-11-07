"""⑤ AI 분석 작업 스레드 (4단계 설계 D7).

작업 스레드는 ai_cells.run_unit(네트워크·파싱·근거 검증)만 부르고 UnitResult를 신호로 보낸다. results dict는 만지지 않는다.
병합(apply_unit)·저장은 신호를 받은 UI 스레드가 한다. 취소는 다음 unit 시작 전에 멈춘다(진행 중 호출은 끝까지 받아 보낸다).
"""

import threading
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from hazop.study import ai_cells

_stamp_lock = threading.Lock()
_last_stamp = [datetime.min.replace(tzinfo=timezone.utc)]


def stamp():
    """UTC ISO 8601(마이크로초). 항목 ID에 들어가므로 같은 프로세스 안에서는 늘 앞 값보다 크다."""
    with _stamp_lock:
        t = max(datetime.now(timezone.utc), _last_stamp[0] + timedelta(microseconds=1))
        _last_stamp[0] = t
    return t.isoformat(timespec="microseconds").replace("+00:00", "Z")


class AiRunner(QObject):
    """jobs = [(unit, ctx)] (UI 스레드에서 준비). start() 뒤 unit마다 unit_started(unit)·unit_done(UnitResult)·progress(done, total),
    끝에 finished(cancelled)를 보낸다. cancelled는 남은 unit을 부르지 않고 멈췄을 때 True."""

    unit_started = Signal(object)
    unit_done = Signal(object)
    progress = Signal(int, int)
    finished = Signal(bool)

    def __init__(self, jobs, deviations, client):
        super().__init__()
        self.jobs = list(jobs)
        self.deviations = deviations
        self.client = client
        self._cancel = threading.Event()
        self.thread = QThread()
        self.moveToThread(self.thread)
        self.thread.started.connect(self._run)
        self.finished.connect(self.thread.quit, Qt.DirectConnection)  # UI 스레드가 wait()로 막혀 있어도 스레드가 끝나게

    def start(self):
        self.thread.start()

    def cancel(self):
        self._cancel.set()

    def is_running(self):
        return self.thread.isRunning()

    def wait(self, msecs=None):
        return self.thread.wait() if msecs is None else self.thread.wait(msecs)

    @Slot()
    def _run(self):
        total, done = len(self.jobs), 0
        try:
            self.progress.emit(0, total)
            for unit, ctx in self.jobs:
                if self._cancel.is_set():
                    break
                self.unit_started.emit(unit)
                self.unit_done.emit(ai_cells.run_unit(self.client, unit, ctx, self.deviations, stamp()))
                done += 1
                self.progress.emit(done, total)
        finally:
            # 예상 밖 예외에도 finished를 보내야 화면이 '실행 중'에 멈추지 않고 창 닫기의 wait()도 끝난다
            self.finished.emit(done < total)
