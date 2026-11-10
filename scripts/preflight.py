"""시험·검사 전 환경 점검. 하위 세션은 작업을 시작할 때 한 번 돌린다.

  <시험용 venv python> scripts/preflight.py                 # 인터프리터·필수 패키지·디스크 여유·기준값·임시 폴더
  <시험용 venv python> scripts/preflight.py --profile apr1400 --min-free-gb 10
  <시험용 venv python> scripts/preflight.py --clean-temp     # 남은 hazop_* 임시 폴더를 지움(2시간 넘은 것만)

통과하면 rc=0, 막히는 문제가 있으면 rc=2. 경고는 rc를 바꾸지 않는다. 경고하는 것: 임시 폴더가 큼, 기준값이 HEAD와 다름,
저장소 밖 시험 폴더(저장소 옆 `<저장소 이름>-trials`, 환경변수 HAZOP_TRIALS_ROOT로 바꿈)가 이름 규칙 §4.11과 다름, 병합된 로컬 브랜치,
폴더가 없는 작업트리 기록.
"""

import argparse
import glob
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devenv  # noqa: E402

def dir_gb(path):
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1024 ** 3


def temp_dirs():
    return devenv.stale_temp_dirs(0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="test", choices=sorted(devenv.PROFILES))
    ap.add_argument("--min-free-gb", type=float, default=None)
    ap.add_argument("--temp-budget-gb", type=float, default=2.0, help="hazop 임시 폴더 합계가 이보다 크면 경고")
    ap.add_argument("--clean-temp", action="store_true", help="2시간 넘게 지난 hazop 임시 폴더를 지움")
    args = ap.parse_args(argv)
    sys.path.insert(0, devenv.REPO_ROOT)
    from hazop import paths
    from hazop.console import safe_console
    safe_console()

    print("인터프리터: %s" % sys.executable)
    print("시험용 venv: %s" % devenv.default_venv_python())
    print("작업 루트: %s" % paths.work_root())
    print("임시 폴더: %s" % tempfile.gettempdir())

    blocking = devenv.interpreter_problems()
    miss = devenv.missing_modules(devenv.PROFILES[args.profile])
    if miss:
        blocking.append("필수 패키지 없음(%s): %s" % (args.profile, ", ".join(miss)))
    if args.clean_temp:
        gone = devenv.sweep_stale_temp(2)
        print("지운 hazop 임시 폴더: %d개" % len(gone))
    blocking += devenv.disk_problems(need_gb=args.min_free_gb)

    warn = []
    tmp = [(d, dir_gb(d)) for d in temp_dirs()]
    total = sum(g for _d, g in tmp)
    if total > args.temp_budget_gb:
        big = sorted(tmp, key=lambda x: -x[1])[:5]
        warn.append("hazop 임시 폴더 %d개, 합계 %.1fGB > %.1fGB. 큰 것: %s. --clean-temp로 정리할 것"
                    % (len(tmp), total, args.temp_budget_gb, ", ".join("%s(%.1fGB)" % (os.path.basename(d), g)
                                                                     for d, g in big)))
    for b in sorted(glob.glob(os.path.join(devenv.REPO_ROOT, "tests", "baselines", "*.json"))):
        warn += ["경고: " + x for x in devenv.baseline_update_problems(b)]
    warn += devenv.trials_warnings() + devenv.git_leftover_warnings() + devenv.old_work_root_warnings()

    for line in warn:
        print("주의: %s" % line)
    for line in blocking:
        print("막힘: %s" % line)
    print("환경 점검: %s" % ("통과" if not blocking else "실패"))
    return 2 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
