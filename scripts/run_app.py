"""HAZOP 데스크톱 프로그램 실행 (기획서/인터페이스.md). 사용 예: python scripts/run_app.py

AI를 호출하지 않으며(고정 응답 폴더만), 웹뷰의 외부 네트워크 요청을 막는다.
경로: 자원 루트(HAZOP_RESOURCE_ROOT)·작업 루트(HAZOP_WORK_ROOT)·저장 루트(HAZOP_STORE_ROOT)는 hazop/paths.py가 정한다.
옵션 --screenshots <폴더>: 각 화면을 열어 PNG로 저장하고 끝낸다(QWidget.grab()).
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="시작할 때 열 분석 실행 폴더")
    ap.add_argument("--screenshots", help="화면별 스크린샷을 저장할 폴더(저장 후 종료)")
    ap.add_argument("--settings", help="설정 파일 경로(기본: APPDATA 아래 HAZOP/settings.json)")
    ap.add_argument("--debug", action="store_true", help="상태줄에 Python↔웹 메시지 등 개발자 정보를 표시")
    args = ap.parse_args(argv)
    from hazop.app import make_application
    app = make_application()
    from hazop.app.main_window import MainWindow
    if args.screenshots:  # 스크린샷의 확정 예시 저장은 임시 저장 루트에만(자료저장소/를 건드리지 않음)
        import tempfile
        os.environ["HAZOP_STORE_ROOT"] = tempfile.mkdtemp(prefix="hazop-screenshot-store-")
    win = MainWindow(settings_path=args.settings, ask_reviewer=not args.screenshots, debug=args.debug)
    win.show()
    if args.run:
        win.open_run(args.run)
    if args.screenshots:
        from hazop.app.screenshots import take_all
        files = take_all(app, win, args.screenshots, args.run)
        for f in files:
            print(f)
        win.close()
        return 0
    code = app.exec()
    win.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
