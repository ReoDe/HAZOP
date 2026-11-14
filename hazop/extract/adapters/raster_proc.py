"""스캔 읽기 하위 프로세스: 래스터 venv의 Python으로 scripts/extract_raster.py를 부르는 곳은 여기 하나다(HZ-PLN-23 §4).

앱의 하위 프로세스는 원래 hazop/study/claude_cli.py 한 곳에만 두는 경계가 있다(tests/test_app.py
test_subprocess_only_in_claude_cli). OpenCV·OCR은 배포본에 넣지 않고 별도 venv에 두므로(결정 D7) 스캔 읽기만 이 모듈을
둘째 예외로 둔다. 경계를 좁게 지키려고:
- 인터프리터는 정해진 래스터 venv의 python(.exe)이다. 개발용 HAZOP_RASTER_PYTHON은 절대 경로이고 파일 이름이
  python·python.exe인 실제 파일일 때만 받는다.
- 스크립트는 저장소의 scripts/extract_raster.py 하나로 고정한다.
- 명령은 목록 인자로 넘기고 셸을 거치지 않는다. 사용자 파일 이름·경로는 명령 줄에 넣지 않는다. 부르는 쪽은 그림을
  자기가 만든 임시 폴더에 page.png·page.jpg로 옮겨 넘기고, 결과 파일 이름은 extraction.json으로 고정한다.
- 시간 한도(TIMEOUT_S)를 두고, 넘으면 하위 프로세스를 끝내고 ScanTimeout을 낸다.
"""

import os
import re
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "extract_raster.py")
RASTER_VENV = os.path.join(os.path.expanduser("~"), ".hazop", "venv-raster-py312")
TIMEOUT_S = 180                    # 쪽 하나 상한. 300dpi A3 쪽이 23~58초(2026-11-14 측정)라 세 배 넘게 둔다
IMAGE_NAME = re.compile(r"^page\.(png|jpg)$")
RESULT_NAME = "extraction.json"
_PY_NAMES = ("python.exe", "python")


class ScanTimeout(RuntimeError):
    """하위 프로세스가 시간 한도를 넘었다(프로세스는 끝냈다)."""


def interpreter():
    """래스터 venv Python 경로. 없으면 None."""
    env = os.environ.get("HAZOP_RASTER_PYTHON")
    if env:
        ok = os.path.isabs(env) and os.path.basename(env).lower() in _PY_NAMES and os.path.isfile(env)
        return env if ok else None
    cands = [os.path.join(RASTER_VENV, "Scripts", "python.exe"), os.path.join(RASTER_VENV, "bin", "python")]
    return next((c for c in cands if os.path.isfile(c)), None)


def command(py, image, out, px_per_pt=None, use_ocr=True):
    """하위 프로세스 명령 목록. image·out은 같은 임시 폴더의 page.png|page.jpg와 extraction.json이어야 한다."""
    if not IMAGE_NAME.match(os.path.basename(image)) or os.path.basename(out) != RESULT_NAME \
            or os.path.dirname(os.path.abspath(image)) != os.path.dirname(os.path.abspath(out)):
        raise ValueError("스캔 읽기 하위 프로세스에는 임시 폴더의 page.png|page.jpg와 extraction.json만 넘긴다")
    cmd = [py, SCRIPT, os.path.abspath(image), "--json-out", os.path.abspath(out)]
    if px_per_pt:
        cmd += ["--px-per-pt", repr(float(px_per_pt))]
    if not use_ocr:
        cmd.append("--no-ocr")
    return cmd


def run(image, out, px_per_pt=None, use_ocr=True, timeout=TIMEOUT_S):
    """래스터 venv로 그림 한 장을 읽어 out에 결과 JSON을 쓴다. → (종료 코드, 출력 끝 500자).
    인터프리터가 없으면 FileNotFoundError, 시간 한도를 넘으면 ScanTimeout."""
    py = interpreter()
    if py is None:
        raise FileNotFoundError("래스터 venv Python 없음")
    cmd = command(py, image, out, px_per_pt, use_ocr)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:  # subprocess.run이 하위 프로세스를 끝낸 뒤 이 예외를 낸다
        raise ScanTimeout("시간 한도(%d초)를 넘어 읽지 못함" % timeout)
    return proc.returncode, (proc.stdout + proc.stderr).strip()[-500:]
