"""HAZOP 데스크톱 프로그램 실행 (기획서/인터페이스.md). 사용 예: python scripts/run_app.py

AI를 호출하지 않으며(고정 응답 폴더만), 웹뷰의 외부 네트워크 요청을 막는다.
경로: 자원 루트(HAZOP_RESOURCE_ROOT)·작업 루트(HAZOP_WORK_ROOT)·저장 루트(HAZOP_STORE_ROOT)는 hazop/paths.py가 정한다.
옵션 --screenshots <폴더>: 각 화면을 열어 PNG로 저장하고 끝낸다(QWidget.grab()).
설정 파일을 읽을 수 없으면(hazop/app/startup.py) 대화형은 한국어 대화상자(백업 후 기본값으로 시작 / 종료), --screenshots는
stderr 안내와 종료 코드 2.
대화형은 한 작업 루트에 하나만 띄운다. 이미 실행 중이면 안내 후 종료 코드 3(startup.single_instance).
작업 루트가 0.1.x 배치(한글 이름 폴더)면 대화형은 복사해 옮길지 묻고(startup.offer_work_root_move), 옮기지 않으면 종료 코드 4로
끝낸다. --screenshots는 묻지 않고 stderr 안내와 종료 코드 4.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

# 시험 전용(packaging/verify_bundle.py, D18): 1이면 창을 띄우지 않고 시험용 예외를 sys.excepthook에 넘긴 뒤 종료 코드 70.
# 묶인 실행의 미처리 예외 기록(packaging/rthook_applog.py)만 확인한다. PyInstaller 오류 대화상자는 스크립트가 예외로 끝날 때
# 부트로더가 띄우므로, 예외를 잡아 직접 넘기면 뜨지 않는다. 검증용 빌드 표지(sys._hazop_verify_build, 런타임 훅
# packaging/rthook_verify_build.py — 검증용 HAZOP.exe에만 들어감)가 있을 때만 켜진다. 배포용·개발 실행에서는 무시한다.
CHAT_TOOLS_FLAG = "--chat-tools"  # 첫 인자일 때만. HAZOP.exe --chat-tools --project <id> --question-file <파일>
ENV_TEST_EXCEPTHOOK = "HAZOP_TEST_EXCEPTHOOK"
EXIT_TEST_EXCEPTHOOK = 70


def _test_excepthook():
    try:
        raise RuntimeError("시험용 미처리 예외(%s)" % ENV_TEST_EXCEPTHOOK)
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    return EXIT_TEST_EXCEPTHOOK


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == [CHAT_TOOLS_FLAG]:  # 채팅 도구 서버(규격 docs/specs/chat-panel.md §2.4): Qt·창·잠금 없이 서버만 돈다
        from hazop.chat import mcp_server
        return mcp_server.main(argv[1:])
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="시작할 때 열 분석 실행 폴더")
    ap.add_argument("--screenshots", help="화면별 스크린샷을 저장할 폴더(저장 후 종료)")
    ap.add_argument("--settings", help="설정 파일 경로(기본: APPDATA 아래 HAZOP/settings.json)")
    ap.add_argument("--debug", action="store_true", help="상태줄에 Python↔웹 메시지 등 개발자 정보를 표시")
    ap.add_argument("--shell", action="store_true", help="새 웹 화면으로 연다(기본). 설정 ui_shell이 꺼져 있어도 이 창으로 연다")
    ap.add_argument("--classic", action="store_true", help="이전 위젯 화면으로 연다(새 화면이 기본이어도)")
    args = ap.parse_args(argv)
    if os.environ.get(ENV_TEST_EXCEPTHOOK) == "1" and getattr(sys, "_hazop_verify_build", False):
        return _test_excepthook()
    from hazop.app.startup import check_settings, offer_work_root_move, single_instance
    if args.screenshots:  # 비대화형: 설정 파일을 읽을 수 없으면 대화상자 없이 stderr 안내, 종료 코드 2
        rc = check_settings(args.settings, interactive=False) or offer_work_root_move(interactive=False)
        if rc is not None:
            return rc
    from hazop.app import make_application
    app = make_application()
    lock = None
    if not args.screenshots:  # 대화형: 이미 실행 중이면 설정 파일을 건드리기 전에 끝낸다. 그다음 설정 확인, MainWindow 생성 전
        lock, rc = single_instance()
        if rc is not None:
            return rc
        rc = check_settings(args.settings, interactive=True)
        if rc is not None:
            return rc
        rc = offer_work_root_move(interactive=True, locked=lock is not None)
        if rc is not None:
            if lock is not None:
                lock.unlock()
            return rc
    from hazop.app import startup
    if startup.window_kind(args.classic, args.screenshots, args.run, args.shell, startup.shell_setting(args.settings)) == "shell":
        code = startup.run_shell(app, args.settings, args.debug)
        if lock is not None:
            lock.unlock()
        return code
    from hazop.app.main_window import MainWindow
    if args.screenshots:  # 스크린샷의 확정 예시 저장은 임시 저장 루트에만(store/를 건드리지 않음)
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
    win.ai_conn.start()  # 지금 연결 방식만 확인(구독은 작업 스레드에서 check(), API 키는 '확인 안 함' 그대로)
    code = app.exec()
    win.close()
    if lock is not None:
        lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
