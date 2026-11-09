r"""실제 데스크톱 점유 잠금. 창을 키보드·마우스로 움직이는 검사·임시 스크립트는 이 잠금 안에서만 돌린다.

  <venv python> scripts/desktop_lease.py status                     # 누가 쥐고 있는지
  <venv python> scripts/desktop_lease.py run --purpose "U5 실측" -- <명령…>   # 잠금을 잡고 명령을 돌린 뒤 푼다

check_user_scenarios.py는 스스로 잠금을 잡는다. 쥔 쪽 이름은 환경변수 HAZOP_OWNER(세션 이름)로 남긴다.
잠금 파일: %USERPROFILE%\.hazop\desktop.lock(Claude 앱 안팎이 같은 파일을 본다).
감싼 명령 안에서 check_user_scenarios.py가 다시 잠금을 잡으려 하면 바깥 잠금을 물려받아 그대로 돈다. 쥔 프로세스가 끝났으면 다음 사람이 자동으로 치운다.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devenv  # noqa: E402


def main(argv=None):
    from hazop.console import safe_console
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("--purpose", required=True)
    r.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if args.cmd == "status":
        held = devenv.desktop_holder()
        print("비어 있음" if not held else "사용 중: %(owner)s · %(purpose)s · %(started)s · pid %(pid)s" % held)
        return 0
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        ap.error("돌릴 명령이 없음")
    try:
        devenv.acquire_desktop(args.purpose)
    except devenv.DesktopBusy as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        return subprocess.call(cmd, env=dict(os.environ, **{devenv.ENV_LEASE_PID: str(os.getpid())}))
    finally:
        devenv.release_desktop()


if __name__ == "__main__":
    sys.exit(main())
