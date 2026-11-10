"""빌드한 HAZOP.exe의 단일 실행 잠금 확인(실제 데스크톱 창을 띄운다). 대화형 실행만 잠금을 거치므로 --screenshots를 쓰지 않는다.

  <venv python> scripts/desktop_lease.py run --purpose "B 단일 실행 잠금" -- \
      <venv python> packaging/lock_probe.py --exe <dist>/HAZOP/HAZOP.exe --out <저장소 밖 결과 폴더>

1) 임시 작업 루트·APPDATA·설정 경로로 첫 실행을 띄우고, 잠금 파일(<작업 루트>/.hazop-app.lock)과 첫 실행의 보이는 창을 기다린다.
2) 같은 환경으로 두 번째 실행을 띄우고, 그 프로세스의 안내 창("HAZOP이 이미 실행 중입니다")을 찾아 PNG로 찍은 뒤 WM_CLOSE로 닫는다.
3) 두 번째 실행의 종료 코드가 3(startup.EXIT_RUNNING)이고, 그동안 첫 실행이 살아 있었는지 본다.
4) 첫 실행을 끝내고 임시 폴더를 지운다. 결과는 <out>/lock_probe.json. 종료 코드 0 = 통과.
네트워크·AI 호출 없음. 자식 환경은 verify_bundle.child_env와 같다(PATH 제한, HAZOP_* 제거).
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTICE_TITLE = "HAZOP이 이미 실행 중입니다"
LOCK_NAME = ".hazop-app.lock"
EXIT_RUNNING = 3
WM_CLOSE = 0x0010
user32 = ctypes.windll.user32


def _verify_bundle():
    spec = importlib.util.spec_from_file_location("hazop_verify_bundle_lock",
                                                  os.path.join(REPO_ROOT, "packaging", "verify_bundle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def windows_of(pid):
    """[(hwnd, 제목)]: pid 프로세스의 보이는 최상위 창."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            found.append((hwnd, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return found


def wait_for(cond, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.25)
    return cond()


def grab(hwnd, path):
    from PIL import ImageGrab
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args(argv)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    vb = _verify_bundle()
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-lock-probe-")
    env = vb.child_env(tmp)
    cmd = [os.path.abspath(args.exe), "--settings", os.path.join(tmp, "settings.json")]
    lock = os.path.join(env["HAZOP_WORK_ROOT"], LOCK_NAME)
    res = {"exe": cmd[0], "work_root": env["HAZOP_WORK_ROOT"], "problems": []}
    first = second = None
    try:
        first = subprocess.Popen(cmd, env=env, cwd=tmp)
        res["first_windows"] = [t for _, t in wait_for(
            lambda: os.path.exists(lock) and windows_of(first.pid), args.timeout) or []]
        res["lock_file"] = os.path.exists(lock)
        if not (res["lock_file"] and res["first_windows"]):
            res["problems"].append("첫 실행이 잠금 파일이나 창을 만들지 않음")
            return finish(res, args.out)
        second = subprocess.Popen(cmd, env=env, cwd=tmp)
        notice = wait_for(lambda: [w for w in windows_of(second.pid) if w[1] == NOTICE_TITLE], args.timeout)
        res["second_windows"] = [t for _, t in windows_of(second.pid)]
        if notice:
            time.sleep(0.5)
            grab(notice[0][0], os.path.join(args.out, "second-instance-notice.png"))
            user32.PostMessageW(notice[0][0], WM_CLOSE, 0, 0)
        else:
            res["problems"].append("두 번째 실행의 안내 창을 찾지 못함")
        try:
            res["second_rc"] = second.wait(args.timeout)
        except subprocess.TimeoutExpired:
            res["second_rc"] = "timeout"
        res["first_alive_after_second"] = first.poll() is None
        if res["second_rc"] != EXIT_RUNNING:
            res["problems"].append("두 번째 실행 종료 코드 %r(기대 %d)" % (res["second_rc"], EXIT_RUNNING))
        if not res["first_alive_after_second"]:
            res["problems"].append("두 번째 실행 동안 첫 실행이 끝남")
        log = os.path.join(env["HAZOP_WORK_ROOT"], "logs", "app.log")
        if os.path.isfile(log):
            with open(log, encoding="utf-8", errors="replace") as fh:
                res["app_log_running_line"] = "이미 실행 중" in fh.read()
        return finish(res, args.out)
    finally:
        for p in (second, first):
            if p is not None and p.poll() is None:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
                p.wait(30)
        shutil.rmtree(tmp, ignore_errors=True)


def finish(res, out):
    res["passed"] = not res["problems"]
    with open(os.path.join(out, "lock_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
