"""시험 패키지. 잘못 잡힌 인터프리터(LibreOffice 내장 Python 등)로 돌리면 곧바로 멈춘다(2026-11-10 교훈).

우회가 꼭 필요하면 HAZOP_ALLOW_ANY_PYTHON=1.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import devenv  # noqa: E402

_bad = devenv.interpreter_problems()
if _bad:
    raise SystemExit("시험 중단: " + "; ".join(_bad))

try:
    # 새 화면의 주소 체계 hazop-app://는 QApplication보다 먼저 등록해야 한다(hazop/shell/scheme.py). 시험을 한 프로세스에서 돌릴 때(run_ci)
    # 다른 시험이 QApplication을 먼저 만들어도 지켜지도록 시험 패키지를 가져올 때 등록한다. 늦게 등록하면 fetch가 'URL scheme not supported'로 실패한다.
    from PySide6 import QtWebEngineWidgets  # noqa: E402,F401
    from hazop.shell import scheme as _shell_scheme  # noqa: E402

    _shell_scheme.register()
except ImportError:
    pass
