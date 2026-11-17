"""큰 자료를 한꺼번에 읽고 지을 때만 순환 쓰레기 수거(gc)를 잠시 멈춘다.

143쪽 프로젝트는 메모리에 객체가 수백만 개 떠 있다. 그 위에서 도면 그래프 수만 개 노드를 새로 만들면 파이썬이 세대별 수거를
자주 돌리며 살아 있는 객체를 계속 훑는다. 같은 일이 수거를 멈추면 절반 이하로 끝난다(다시 만들기 2.0초 → 1.1초, 측정은
docs/units/2026-11-13-drawing-knowledge/evidence/shell-perf.md). 결과는 같고 수거만 늦춘다. 끝나면 원래대로 돌려 두고,
그동안 쌓인 순환 쓰레기는 다음 수거가 치운다.

- 여러 스레드·겹친 호출에 안전하다: 가장 바깥 호출이 들어갈 때 gc가 켜져 있었으면 끄고, 마지막 호출이 나올 때 다시 켠다.
  처음부터 꺼져 있었으면(시험이나 호출한 쪽이 껐으면) 켜지 않는다.
- 일이 길어질수록 쓰레기가 쌓이므로 한 번에 몇 초 안쪽의 묶음 작업에만 쓴다.
"""

import contextlib
import gc
import threading

_LOCK = threading.Lock()
_DEPTH = 0
_WAS_ENABLED = False


@contextlib.contextmanager
def paused():
    global _DEPTH, _WAS_ENABLED
    with _LOCK:
        if _DEPTH == 0:
            _WAS_ENABLED = gc.isenabled()
            if _WAS_ENABLED:
                gc.disable()
        _DEPTH += 1
    try:
        yield
    finally:
        with _LOCK:
            _DEPTH -= 1
            if _DEPTH == 0 and _WAS_ENABLED:
                gc.enable()
