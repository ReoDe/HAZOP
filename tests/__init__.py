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
