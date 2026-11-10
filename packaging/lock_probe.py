"""빌드한 HAZOP.exe의 단일 실행 잠금 확인(실제 데스크톱 창을 띄운다). 대화형 실행만 잠금을 거치므로 --screenshots를 쓰지 않는다.

  <venv python> scripts/desktop_lease.py run --purpose "B 단일 실행 잠금" -- \
      <venv python> packaging/lock_probe.py --exe <dist>/HAZOP/HAZOP.exe --out <저장소 밖 새 결과 폴더>

desktop_lease.py run 밖에서(HAZOP_DESKTOP_LEASE_PID 없음) 부르면 거부한다(종료 코드 2). --out이 이미 있어도 거부한다.
임시 작업 루트·APPDATA·설정 경로를 쓰고, 단계마다 '정상 기동'을 다음 세 가지로 판정한다.
  - 그 프로세스의 보이는 창이 주 창(제목 MAIN_TITLE)뿐이다. 처음 실행에 뜨는 '검토자 이름' 입력 창은 취소로 닫고 넘어간다.
    그 밖의 창(오류 대화상자 등)이 보이면 실패다.
  - <작업 루트>/logs/app.log에 그 pid의 '시작 pid=' 줄이 있고 '미처리 예외' 줄이 없다.
  - 프로세스가 살아 있다.
1) 첫 실행이 정상 기동하고 잠금 파일(<작업 루트>/.hazop-app.lock)을 만든다.
2) 두 번째 실행이 안내 창("HAZOP이 이미 실행 중입니다")을 띄운다. 창을 찍고 닫으면 종료 코드 3이고, 첫 실행은 살아 있다.
3) 첫 실행을 주 창 닫기(WM_CLOSE)로 끝낸 뒤 다시 실행하면 안내 없이 정상 기동한다(남은 잠금 파일이 막지 않음).
4) 그 실행을 강제로 끝낸 뒤(taskkill /F, 잠금 파일이 남음) 다시 실행해도 안내 없이 정상 기동한다.
결과는 <out>/lock_probe.json과 안내 창 PNG. 끝나면 띄운 프로세스를 모두 끝내고 임시 폴더를 지운다. 종료 코드 0 = 통과.
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
MAIN_TITLE = "HAZOP 분석 도구"  # hazop/app/main_window.APP_NAME (시험이 같은지 본다)
REVIEWER_TITLE = "검토자 이름"
NOTICE_TITLE = "HAZOP이 이미 실행 중입니다"
LOCK_NAME = ".hazop-app.lock"
EXIT_RUNNING = 3
WM_CLOSE = 0x0010
user32 = ctypes.windll.user32


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO_ROOT, *rel.split("/")))
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


def log_text(work):
    p = os.path.join(work, "logs", "app.log")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def started(proc, work, timeout):
    """정상 기동 판정. (통과 여부, 기록). 검토자 이름 창은 닫고(취소) 주 창을 기다린다."""
    def settled():
        if proc.poll() is not None:
            return "exited"
        wins = windows_of(proc.pid)
        for hwnd, title in wins:
            if title == REVIEWER_TITLE:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return None
        titles = [t for _, t in wins]
        if titles and any(t != MAIN_TITLE for t in titles):
            return "other"
        return "main" if titles == [MAIN_TITLE] else None
    state = wait_for(settled, timeout)
    time.sleep(1.0)  # 주 창 뒤에 늦게 뜨는 오류 창도 잡도록 한 번 더 본다
    titles = [t for _, t in windows_of(proc.pid)]
    text = log_text(work)
    rec = {"pid": proc.pid, "state": state, "windows": titles, "alive": proc.poll() is None,
           "log_start_line": ("시작 pid=%d " % proc.pid) in text, "log_unhandled": "미처리 예외" in text}
    ok = (state == "main" and titles == [MAIN_TITLE] and rec["alive"] and rec["log_start_line"]
          and not rec["log_unhandled"])
    return ok, rec


def close_main(proc, timeout):
    """주 창에 WM_CLOSE를 보내고 끝나기를 기다린다. 종료 코드(또는 'timeout')."""
    for hwnd, title in windows_of(proc.pid):
        if title == MAIN_TITLE:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        return proc.wait(timeout)
    except subprocess.TimeoutExpired:
        return "timeout"


def kill(proc):
    if proc is not None and proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        proc.wait(30)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--out", required=True, help="새 결과 폴더(이미 있으면 거부)")
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args(argv)
    vb = _load("packaging/verify_bundle.py", "hazop_verify_bundle_lock")  # 저장소를 sys.path에 넣는다
    devenv = _load("scripts/devenv.py", "hazop_devenv_lock")
    if not os.environ.get(devenv.ENV_LEASE_PID):
        print("중단: desktop_lease.py run 밖에서 실행함(%s 없음). 실제 창을 띄우므로 잠금 안에서만 돌린다"
              % devenv.ENV_LEASE_PID)
        return 2
    if os.path.exists(args.out):
        print("중단: 결과 폴더가 이미 있음(덮어쓰지 않음): %s" % args.out)
        return 2
    os.makedirs(args.out)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    tmp = tempfile.mkdtemp(prefix="hazop-lock-probe-")
    env = vb.child_env(tmp)
    work = env["HAZOP_WORK_ROOT"]
    cmd = [os.path.abspath(args.exe), "--settings", os.path.join(tmp, "settings.json")]
    lock = os.path.join(work, LOCK_NAME)
    res = {"exe": cmd[0], "work_root": work, "lease_pid": os.environ.get(devenv.ENV_LEASE_PID), "problems": []}
    procs = []

    def launch():
        p = subprocess.Popen(cmd, env=env, cwd=tmp)
        procs.append(p)
        return p

    try:
        first = launch()
        ok, res["first"] = started(first, work, args.timeout)
        res["first"]["lock_file"] = os.path.exists(lock)
        if not (ok and res["first"]["lock_file"]):
            res["problems"].append("1) 첫 실행이 정상 기동하지 않았거나 잠금 파일이 없음")
            return finish(res, args.out)

        second = launch()
        notice = wait_for(lambda: [w for w in windows_of(second.pid) if w[1] == NOTICE_TITLE], args.timeout)
        res["second"] = {"pid": second.pid, "windows": [t for _, t in windows_of(second.pid)]}
        if notice:
            time.sleep(0.5)
            grab(notice[0][0], os.path.join(args.out, "second-instance-notice.png"))
            user32.PostMessageW(notice[0][0], WM_CLOSE, 0, 0)
        else:
            res["problems"].append("2) 두 번째 실행의 안내 창을 찾지 못함")
        try:
            res["second"]["rc"] = second.wait(args.timeout)
        except subprocess.TimeoutExpired:
            res["second"]["rc"] = "timeout"
        res["second"]["first_alive"] = first.poll() is None
        res["second"]["log_running_line"] = "이미 실행 중" in log_text(work)
        if res["second"]["rc"] != EXIT_RUNNING:
            res["problems"].append("2) 두 번째 실행 종료 코드 %r(기대 %d)" % (res["second"]["rc"], EXIT_RUNNING))
        if not res["second"]["first_alive"]:
            res["problems"].append("2) 두 번째 실행 동안 첫 실행이 끝남")

        res["first"]["close_rc"] = close_main(first, args.timeout)
        res["first"]["lock_file_after_close"] = os.path.exists(lock)
        if res["first"]["close_rc"] != 0:
            res["problems"].append("3) 첫 실행이 주 창 닫기로 끝나지 않음: %r" % res["first"]["close_rc"])
        third = launch()
        ok, res["after_close"] = started(third, work, args.timeout)
        if not ok:
            res["problems"].append("3) 닫은 뒤 다시 실행이 정상 기동하지 않음")

        kill(third)
        res["after_close"]["lock_file_after_kill"] = os.path.exists(lock)
        fourth = launch()
        ok, res["after_kill"] = started(fourth, work, args.timeout)
        if not ok:
            res["problems"].append("4) 강제 종료 뒤 다시 실행이 정상 기동하지 않음(남은 잠금이 막음?)")
        res["after_kill"]["close_rc"] = close_main(fourth, args.timeout)
        return finish(res, args.out)
    finally:
        for p in reversed(procs):
            kill(p)
        shutil.rmtree(tmp, ignore_errors=True)


def finish(res, out):
    res["passed"] = not res["problems"]
    with open(os.path.join(out, "lock_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
