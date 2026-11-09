"""개발 환경 점검 도구(2026-11-10 교훈 반영). 시험·검사 스크립트가 시작할 때 부르는 공용 함수 모음.

- interpreter_problems(): LibreOffice 내장 Python처럼 잘못 잡힌 인터프리터를 걸러 낸다.
  저장소 루트에서 `python`은 LibreOffice Python이라, 이것으로 돌리면 '순수 HEAD에서도 실패'하는 거짓 실패가 난다.
- missing_modules(): 필수 패키지가 빠진 venv를 걸러 낸다.
- disk_problems(): 작업 루트·임시 폴더 드라이브의 여유 공간이 기준 아래면 알린다(C 드라이브 가득 참 사고).
- baseline_update_problems(): 회귀 기준값을 --update로 덮기 전에, 다른 세션이 갱신해 놓고 아직 커밋하지 않은
  기준값을 덮어쓰지 않게 막는다(apr1400_score.json을 두 세션이 덮은 사고).
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 시험용 venv(빌드 venv와 같음): %USERPROFILE%\.hazop\venv-py312. 다른 곳으로 옮기면 HAZOP_VENV로 알려 준다.
ENV_VENV = "HAZOP_VENV"
ENV_ALLOW_ANY_PYTHON = "HAZOP_ALLOW_ANY_PYTHON"
ENV_MIN_FREE_GB = "HAZOP_MIN_FREE_GB"
DEFAULT_MIN_FREE_GB = 5.0

PROFILES = {
    # 단위 시험 전체와 대부분의 검사 스크립트
    "test": ("networkx", "PySide6", "pdfplumber", "pypdfium2", "openpyxl"),
    # APR1400 일괄 추출·점수 검사
    "apr1400": ("networkx", "pdfplumber", "pypdfium2"),
    # 래스터 추출(별도 venv-raster-py312)
    "raster": ("networkx", "numpy", "cv2"),
}


def default_venv():
    return os.environ.get(ENV_VENV) or os.path.join(os.path.expanduser("~"), ".hazop", "venv-py312")


def default_venv_python():
    return os.path.join(default_venv(), "Scripts" if os.name == "nt" else "bin",
                        "python.exe" if os.name == "nt" else "python")


def interpreter_problems(executable=None, prefix=None):
    """잘못 잡힌 인터프리터면 이유 목록을 돌려준다. HAZOP_ALLOW_ANY_PYTHON=1이면 검사하지 않는다."""
    if os.environ.get(ENV_ALLOW_ANY_PYTHON) == "1":
        return []
    exe = executable or sys.executable or ""
    pre = prefix if prefix is not None else (getattr(sys, "base_prefix", "") or "")
    if "libreoffice" in exe.lower() or "libreoffice" in pre.lower():
        return ["LibreOffice 내장 Python으로 실행했음(%s). 시험용 venv의 python을 경로로 지정할 것: %s"
                % (exe, default_venv_python())]
    norm = exe.replace("\\", "/").lower()
    if "/appdata/local/hazop/venv" in norm or "/localcache/local/hazop/venv" in norm:
        return ["옛 venv(%s)로 실행했음. pdfplumber가 없어 거짓 실패가 난다. 시험용 venv를 쓸 것: %s"
                % (exe, default_venv_python())]
    return []


def missing_modules(names):
    return [n for n in names if importlib.util.find_spec(n) is None]


def free_gb(path):
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return shutil.disk_usage(probe or os.getcwd()).free / 1024 ** 3


def min_free_gb(default=DEFAULT_MIN_FREE_GB):
    try:
        return float(os.environ.get(ENV_MIN_FREE_GB, default))
    except ValueError:
        return default


def disk_problems(paths=None, need_gb=None):
    """작업 루트·임시 폴더(기본) 드라이브마다 여유가 need_gb보다 적으면 이유 목록을 돌려준다."""
    need = min_free_gb() if need_gb is None else need_gb
    if paths is None:
        sys.path.insert(0, REPO_ROOT)
        from hazop import paths as hp
        paths = [hp.work_root(), tempfile.gettempdir()]
    seen, bad = set(), []
    for p in paths:
        drive = os.path.splitdrive(os.path.abspath(p))[0].upper() or p
        if drive in seen:
            continue
        seen.add(drive)
        gb = free_gb(p)
        if gb < need:
            bad.append("디스크 여유 부족: %s 남은 %.1fGB < 기준 %.1fGB(%s). 시험 폴더·임시 폴더를 먼저 비울 것"
                       % (drive, gb, need, p))
    return bad


def _git(*args):
    return subprocess.run(["git", "-C", REPO_ROOT, "-c", "core.quotepath=false"] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# 점수에 닿는 입력: 코드, 기호 사전(pdf_vector가 폴더를 훑어 읽음), APR1400 정답지
SCORING_PATHS = ("hazop", "scripts", "자원/기준/기호", "tests/fixtures/apr1400")
# 이 아래는 추적 안 한 새 파일도 읽히므로 그것까지 본다
SCORING_UNTRACKED = ("자원/기준/기호",)


def baseline_update_problems(path, force=False, code_paths=SCORING_PATHS, untracked_paths=SCORING_UNTRACKED):
    """회귀 기준값은 커밋된 코드로만 매긴다. 아래면 --update를 막는다.

    - 기준값 파일이 HEAD와 다름: 누군가 갱신하고 아직 커밋하지 않음. 다른 세션의 갱신을 덮을 수 있다.
    - 점수에 닿는 입력(hazop/·scripts/·기호 사전·APR1400 정답지)에 커밋하지 않은 수정이 있음: 자기 것이든 다른 세션 것이든 섞인 코드로
      매긴 값이 기준이 되면, HEAD 코드로 돌린 검사가 실패한다(2026-11-09 apr1400_score.json 사고).
      코드를 먼저 커밋하고 기준값은 따로 갱신·커밋한다. 깨끗한 분리 작업트리에서 돌리는 것이 가장 안전하다.
    추적하지 않는 새 파일은 기호 사전 폴더에서만 본다. --force면 막지 않는다. 저장소 밖 경로나 git이 없으면 막지 않는다."""
    if force:
        return []
    path = os.path.abspath(path)
    try:
        rel = os.path.relpath(path, REPO_ROOT)
    except ValueError:
        return []
    if rel.startswith(".."):
        return []
    rel = rel.replace(os.sep, "/")
    try:
        r = _git("status", "--porcelain", "--untracked-files=no", "--", rel, *code_paths)
    except OSError:
        return []
    if r.returncode != 0:
        return []
    dirty = [line[3:].strip().strip('"') for line in r.stdout.splitlines() if line.strip()]
    if untracked_paths:
        try:
            u = _git("status", "--porcelain", "--untracked-files=all", "--", *untracked_paths)
        except OSError:
            u = None
        if u is not None and u.returncode == 0:
            dirty += [line[3:].strip().strip('"') for line in u.stdout.splitlines()
                      if line.startswith("??") and line[3:].strip().strip('"') not in dirty]
    bad = []
    if rel in dirty:
        bad.append("기준값 %s가 HEAD와 다름(커밋하지 않은 갱신이 있음). 다른 세션의 갱신일 수 있으니 덮지 않음. "
                   "`git diff -- %s`로 누구 것인지 확인할 것" % (rel, rel))
    code = [d for d in dirty if d != rel]
    if code:
        bad.append("점수에 닿는 입력에 커밋하지 않은 수정이 있음(%s%s). 코드를 먼저 커밋하거나, HEAD에서 만든 분리 "
                   "작업트리에서 --update를 돌릴 것" % (", ".join(code[:5]), " 외 %d개" % (len(code) - 5) if len(code) > 5 else ""))
    if bad:
        bad[-1] += ". 섞인 코드가 아님을 확인했으면 --force"
    return bad


TEMP_PATTERNS = ("hazop_*", "hazop-*")
ENV_KEEP_TEMP = "HAZOP_KEEP_TEMP"


def stale_temp_dirs(older_than_hours, base=None):
    import glob
    import time
    base = base or tempfile.gettempdir()
    cut = time.time() - older_than_hours * 3600
    found = set()
    for pat in TEMP_PATTERNS:
        found.update(p for p in glob.glob(os.path.join(base, pat)) if os.path.isdir(p))
    out = []
    for p in sorted(found):
        try:
            if os.path.getmtime(p) < cut:
                out.append(p)
        except OSError:
            pass
    return out


def sweep_stale_temp(older_than_hours=24, base=None):
    """시험이 남긴 hazop 임시 폴더를 지운다. QtWebEngine 등이 파일을 쥐고 있으면 rmtree(ignore_errors)가
    조용히 실패해 하루 1,000개 넘게 쌓였다(2026-11-07~09 약 3,000개). HAZOP_KEEP_TEMP=1이면 지우지 않는다."""
    if os.environ.get(ENV_KEEP_TEMP) == "1":
        return []
    gone = []
    for p in stale_temp_dirs(older_than_hours, base):
        shutil.rmtree(p, ignore_errors=True)
        if not os.path.exists(p):
            gone.append(p)
    return gone


def require_baseline_update(path, force=False):
    bad = baseline_update_problems(path, force)
    if bad:
        for line in bad:
            print("기준값 갱신 막음: %s" % line, file=sys.stderr)
        sys.exit(2)


def require(profile="test", need_gb=None, check_disk=True):
    """시작 점검. 문제가 있으면 이유를 stderr에 쓰고 rc=2로 끝낸다."""
    bad = interpreter_problems()
    if not bad:
        miss = missing_modules(PROFILES[profile])
        if miss:
            bad.append("필수 패키지 없음(%s): %s. 실행 인터프리터 %s, 시험용 venv %s"
                       % (profile, ", ".join(miss), sys.executable, default_venv_python()))
    if check_disk:
        bad += disk_problems(need_gb=need_gb)
    if bad:
        for line in bad:
            print("환경 점검 실패: %s" % line, file=sys.stderr)
        sys.exit(2)


# ---- 실제 데스크톱 점유(2026-11-10 교훈) -------------------------------------------------------------------
# 실제 창을 키보드·마우스로 움직이는 검사는 한 번에 하나만 돈다. 메시지로 '데스크톱 반납'을 주고받던 방식은
# 메시지를 못 본 세션을 막지 못했다. 기계 전체에 하나인 잠금 파일로 막는다.
# %LOCALAPPDATA%는 Claude 앱(MSIX) 안에서 가상화되어 앱 밖 터미널과 갈라지므로, venv처럼 사용자 폴더 아래에 둔다
DESKTOP_LOCK = os.path.join(os.path.expanduser("~"), ".hazop", "desktop.lock")
ENV_LEASE_PID = "HAZOP_DESKTOP_LEASE_PID"  # desktop_lease.py run이 자식에게 물려주는 잠금 주인 pid
ENV_OWNER = "HAZOP_OWNER"


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0)은 Windows에서 프로세스를 끝내므로 쓰지 않는다
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def desktop_holder(lock=None):
    """지금 데스크톱을 쥔 쪽(dict) 또는 None. 쥔 프로세스가 끝났으면 None."""
    import json
    lock = lock or DESKTOP_LOCK
    try:
        with open(lock, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    return info if pid_alive(int(info.get("pid", 0))) else None


class DesktopBusy(RuntimeError):
    pass


def acquire_desktop(purpose, lock=None, pid=None):
    """잠금을 잡는다. 다른 살아 있는 프로세스가 쥐고 있으면 DesktopBusy. 주인이 죽은 잠금은 치운다."""
    import json
    import time
    lock = lock or DESKTOP_LOCK
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    info = {"pid": pid or os.getpid(), "owner": os.environ.get(ENV_OWNER) or "pid %d" % (pid or os.getpid()),
            "purpose": purpose, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "cwd": os.getcwd()}
    inherited = os.environ.get(ENV_LEASE_PID)
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) < 5 and os.path.getsize(lock) == 0:
                    time.sleep(1)  # 다른 쪽이 막 만들고 아직 쓰는 중
            except OSError:
                pass
            held = desktop_holder(lock)
            if held and inherited and str(held.get("pid")) == inherited:
                return held  # 바깥 desktop_lease run이 잡은 잠금 안에서 도는 자식
            if held:
                raise DesktopBusy("데스크톱을 다른 쪽이 쓰는 중: %s(%s, %s부터, pid %s). 끝날 때까지 기다릴 것"
                                  % (held.get("owner"), held.get("purpose"), held.get("started"), held.get("pid")))
            try:
                os.remove(lock)
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False)
        return info
    raise DesktopBusy("데스크톱 잠금을 잡지 못함: %s" % lock)


def release_desktop(lock=None, pid=None):
    import json
    lock = lock or DESKTOP_LOCK
    try:
        with open(lock, encoding="utf-8") as fh:
            if int(json.load(fh).get("pid", 0)) != (pid or os.getpid()):
                return
        os.remove(lock)
    except (OSError, ValueError):
        pass
