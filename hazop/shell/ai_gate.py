"""엔진 전체의 AI 호출 차례(일괄 작업이 구독 호출을 한 번에 하나만 돌게). Qt를 import하지 않는다.

규격은 docs/specs/extraction.md 'AI 검토 실행(R2)'의 '작업끼리의 차례'.

- 차례를 타는 것: AI 검토 실행, 추출 뒤 자동 AI 검토, AI 분석 실행. 작업 하나가 차례를 잡으면 그 작업의 호출이 모두 끝날 때까지 놓지 않는다.
  뒤에 온 작업은 거절하지 않고 온 순서대로 기다리며, 기다리는 동안 앞 작업 이름을 알린다(on_wait).
- 기다리는 작업도 멈추기가 바로 먹는다: should_stop()을 poll초마다 보고, 참이면 stopped()가 만든 예외를 올린다.
- 채팅은 차례를 타지 않는다. 사람이 답을 기다리는 길이라 일괄 작업 뒤에 묶으면 호출 하나(최대 600초)만큼 기다릴 수 있다.
  채팅은 질문을 한 번에 하나만 받으므로(ChatController) 동시에 도는 구독 호출은 일괄 작업 하나와 채팅 하나, 많아야 둘이다.
"""

import contextlib
import threading

POLL_SECONDS = 0.2


class Gate:
    def __init__(self):
        self._cond = threading.Condition()
        self._queue = []      # [(번호, 이름)] 앞이 지금 차례
        self._seq = 0

    def waiting(self):
        """차례를 잡았거나 기다리는 작업 이름(앞부터)."""
        with self._cond:
            return [label for _n, label in self._queue]

    @contextlib.contextmanager
    def turn(self, label, should_stop, stopped, on_wait=None, poll=POLL_SECONDS):
        with self._cond:
            self._seq += 1
            ticket = (self._seq, label)
            self._queue.append(ticket)
        try:
            told = None
            while True:
                with self._cond:
                    if self._queue[0] is ticket:
                        break
                    ahead = self._queue[0][1]
                if should_stop():
                    raise stopped()
                if on_wait is not None and ahead != told:
                    told = ahead
                    on_wait(ahead)
                with self._cond:
                    if self._queue[0] is not ticket:
                        self._cond.wait(poll)
            yield
        finally:
            with self._cond:
                self._queue.remove(ticket)
                self._cond.notify_all()
