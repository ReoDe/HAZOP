"""시작 전 설정 파일 확인 (패키징 W10, D18). scripts/run_app.py가 MainWindow를 만들기 전에 부른다.

설정 파일(settings.json)을 읽을 수 없으면 기본값으로 조용히 덮어쓰지 않는다(hazop/paths.load_settings 원칙 유지).
- 손상(JSON 문법 오류·JSON 객체 아님·UTF-8 아님): 대화형은 한국어 대화상자로 경로·원인을 보여 주고 "기존 파일을 백업하고
  기본값으로 시작"(settings.json → settings.json.bad-<시각>.json으로 이름 바꿈) 또는 "종료"를 고르게 한다. 대화상자 응답 뒤
  이름을 바꾸기 직전에 파일을 다시 확인해(크기·수정 시각·내용 해시) 그사이 바뀌었으면 백업하지 않고 다시 판정한다.
- 읽기 실패(OSError: 권한·잠금 등): 백업 선택지 없이 안내 후 종료.
비대화형 실행(--screenshots)은 대화상자 없이 stderr에 안내하고 종료 코드 2로 끝낸다.

한 작업 루트에서는 대화형 실행을 하나만 띄운다(single_instance). 두 실행이 같은 저장본을 따로 고치다 덮어쓰지 않게 하려는 것이다.

0.1.x가 쓰던 작업 폴더(한글 이름 배치)를 찾으면 0.2.0 배치로 복사해 옮길지 묻는다(offer_work_root_move, HZ-GOV-02 §6.6).
조용히 옮기지 않는다. 거절하거나 옮기지 못하면 옛 폴더를 그대로 두고, 까닭을 알린 뒤 시작하지 않는다(종료 코드 4). 옛 폴더가
남은 채로 새 이름 폴더에 쓰기 시작하면 뒤에 옮길 때 부딪혀 사람이 한 수정을 잃을 수 있어서다. 다음에 시작할 때 다시 묻는다.
"""

import hashlib
import logging
import os
import sys
import time

from hazop import paths, workroot

BACKUP = "backup"
QUIT = "quit"
CORRUPT = "corrupt"        # 내용 손상: 백업 후 기본값으로 시작할 수 있음
UNREADABLE = "unreadable"  # 읽기 실패(OSError): 종료만
EXIT_SETTINGS = 2  # 설정 파일 때문에 시작하지 않음
EXIT_RUNNING = 3   # 같은 작업 루트에서 이미 실행 중이라 시작하지 않음
LOCK_NAME = ".hazop-app.lock"
EXIT_OLD_LAYOUT = 4  # 0.1.x 작업 폴더를 옮기지 않아 시작하지 않음
MOVE_TITLE = "이전 버전의 작업 폴더"
_log = logging.getLogger("hazop.settings")
_log.addHandler(logging.NullHandler())  # 개발 실행에서 logging 기본 출력(lastResort)이 stderr 안내와 겹치지 않게


def settings_error(path):
    """(종류, 원인 문자열). 읽을 수 있으면(파일 없음 포함) None.
    json.JSONDecodeError·UnicodeDecodeError는 ValueError의 하위 클래스다(CORRUPT). OSError는 UNREADABLE."""
    try:
        paths.load_settings(path)
    except ValueError as e:
        return CORRUPT, "%s: %s" % (type(e).__name__, e)
    except OSError as e:
        return UNREADABLE, "%s: %s" % (type(e).__name__, e)
    return None


def fingerprint(path):
    """(크기, 수정 시각 ns, SHA-256). 파일이 없거나 읽을 수 없으면 None."""
    try:
        st = os.stat(path)
        with open(path, "rb") as fh:
            return st.st_size, st.st_mtime_ns, hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def backup_name(path, now=None):
    return "%s.bad-%s.json" % (path, time.strftime("%Y%m%d-%H%M%S", time.localtime(now)))


def _write(err, text):
    stream = err or sys.stderr
    if stream is not None:  # 창 프로그램에서 로그 연결이 실패하면 stderr가 없을 수 있다
        stream.write(text)
        stream.flush()


def ask_dialog(path, cause):
    """손상 안내 대화상자: BACKUP 또는 QUIT. QApplication이 있어야 한다."""
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Warning, "설정 파일을 읽을 수 없음",
                      "설정 파일의 내용이 손상되어 프로그램을 시작하지 못했습니다.\n\n파일: %s\n원인: %s\n\n"
                      "백업을 고르면 기존 파일은 지우지 않고 이름을 바꿔 남깁니다." % (path, cause))
    backup = box.addButton("기존 파일을 백업하고 기본값으로 시작", QMessageBox.AcceptRole)
    quit_ = box.addButton("종료", QMessageBox.RejectRole)
    box.setDefaultButton(quit_)
    box.exec()
    return BACKUP if box.clickedButton() is backup else QUIT


def notify_dialog(title, text):
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Critical, title, text)
    box.addButton("종료", QMessageBox.RejectRole)
    box.exec()


def check_settings(path, interactive, ask=None, notify=None, err=None, now=None):
    """None = 계속 시작, 정수 = 종료 코드(EXIT_SETTINGS). ask(path, cause) -> BACKUP|QUIT, notify(title, text)."""
    path = path or paths.settings_path()
    notify = notify or notify_dialog
    while True:
        before = fingerprint(path)
        problem = settings_error(path)
        if problem is None:
            return None
        kind, cause = problem
        _log.warning("설정 파일을 읽을 수 없음: %s (%s)", path, cause)
        if not interactive:
            _write(err, "설정 파일을 읽을 수 없어 종료합니다: %s\n원인: %s\n%s\n" % (path, cause, (
                "파일을 고치거나 지운 뒤 다시 실행하세요(대화형 실행에서는 백업 후 기본값으로 시작할 수 있음)."
                if kind == CORRUPT else "파일 권한·잠금을 확인한 뒤 다시 실행하세요.")))
            return EXIT_SETTINGS
        if kind == UNREADABLE:
            notify("설정 파일을 읽을 수 없음", "설정 파일을 읽을 수 없어 종료합니다.\n\n파일: %s\n원인: %s\n\n"
                   "파일 권한·잠금(다른 프로그램이 열고 있는지)을 확인한 뒤 다시 실행하세요." % (path, cause))
            return EXIT_SETTINGS
        if (ask or ask_dialog)(path, cause) != BACKUP:
            _log.warning("사용자가 종료를 선택함")
            return EXIT_SETTINGS
        if fingerprint(path) != before:  # 대화상자를 띄운 사이 파일이 바뀌거나 없어졌으면 백업하지 않고 다시 판정
            _log.warning("설정 파일이 확인 중에 바뀜: 다시 판정함 %s", path)
            continue
        dest = backup_name(path, now)
        try:
            os.rename(path, dest)  # 같은 이름이 있으면 Windows에서 실패한다(덮어쓰지 않음)
        except OSError as e:
            _log.warning("설정 파일 백업 실패: %s -> %s (%s)", path, dest, e)
            notify("설정 파일 백업 실패", "이름을 바꾸지 못해 종료합니다.\n\n파일: %s\n새 이름: %s\n원인: %s" % (path, dest, e))
            return EXIT_SETTINGS
        _log.warning("설정 파일 백업: %s -> %s, 기본값으로 시작", path, dest)
        return None


def move_question(plan):
    names = ", ".join(old for old, _now in plan.tops)
    return ("이전 버전(0.1)에서 쓰던 작업 폴더가 있습니다.\n\n위치: %s\n폴더: %s\n\n"
            "이 버전은 폴더 이름이 달라서, 새 이름으로 복사해야 등록한 자료와 분석 결과가 보입니다. "
            "복사할 양은 파일 %d개, %.1f MB입니다.\n"
            "옛 폴더는 지우지 않고 '%s' 폴더로 옮겨 둡니다.\n\n지금 복사할까요?"
            % (plan.root, names, len(plan.files), plan.size / 1e6, workroot.KEEP_DIR))


def ask_move_dialog(plan):
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Question, MOVE_TITLE, move_question(plan))
    yes = box.addButton("복사해서 옮기기", QMessageBox.AcceptRole)
    box.addButton("옮기지 않고 끝내기", QMessageBox.RejectRole)
    box.setDefaultButton(yes)
    box.exec()
    return box.clickedButton() is yes


def run_move_dialog(root):
    """진행 표시를 띄우고 옮긴다. 도중에 멈추는 단추는 두지 않는다(끊겨도 다음에 이어서 한다)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QProgressDialog
    box = QProgressDialog("작업 폴더를 새 이름으로 복사하는 중입니다…", None, 0, 1000)
    box.setWindowTitle(MOVE_TITLE)
    box.setWindowModality(Qt.ApplicationModal)
    box.setMinimumDuration(0)
    box.setValue(0)

    def progress(done, total):
        box.setValue(int(1000 * done / total) if total else 1000)
        QApplication.processEvents()

    try:
        return workroot.apply(root, progress=progress)
    finally:
        box.close()


def offer_work_root_move(interactive, ask=None, notify=None, run=None, err=None, locked=True):
    """작업 루트가 0.1.x 배치면 0.2.0 배치로 복사해 옮길지 묻는다. None = 계속 시작(옮길 것이 없거나 옮겼다),
    EXIT_OLD_LAYOUT = 시작하지 않음(거절, 새 이름 폴더에 이미 파일이 있음, 옮기다 실패). 옮기기 전에는 작업 루트에서
    아무것도 읽거나 쓰지 않는다. ask(plan) -> bool, notify(제목, 글), run(작업 루트). 비대화형 실행은 묻지 않고 끝낸다.
    배치를 확인하지 못해도(권한 등) 시작하지 않는다. locked가 거짓이면(작업 루트 잠금을 잡지 못함) 옮기지 않는다:
    다른 실행이 같은 폴더를 쓰고 있을 수 있다."""
    root = paths.raw_work_root()
    notify = notify or notify_running

    def stop(text):
        _log.warning("작업 폴더 때문에 시작하지 않음: %s", text.replace("\n", " "))
        if interactive:
            notify(MOVE_TITLE, text)
        else:
            _write(err, text + "\n")
        return EXIT_OLD_LAYOUT

    try:
        plan = workroot.make_plan(root)
    except (OSError, workroot.MigrationError) as e:
        return stop("작업 폴더의 배치를 확인하지 못해 프로그램을 시작하지 않습니다.\n\n위치: %s\n원인: %s\n\n"
                    "폴더 권한을 확인한 뒤 다시 실행하세요." % (root, e))
    if plan.state in ("none", "done"):
        try:
            paths.require_current_layout(root)
        except paths.OldLayoutError as e:
            return stop("%s\n\n옮긴 뒤 다시 실행하세요." % e)
        return None
    if plan.state == "undoing":
        return stop("작업 폴더를 되돌리다 끊긴 상태라 프로그램을 시작하지 않습니다.\n\n위치: %s\n\n"
                    "scripts/migrate_names.py --work-root <작업 루트> --undo 를 다시 돌려 끝낸 뒤 실행하세요." % root)
    names = ", ".join(old for old, _now in plan.tops) or workroot.KEEP_DIR
    stays = "이전 버전에서 만든 자료는 옛 폴더(%s)에 그대로 있습니다.\n위치: %s" % (names, root)
    if not interactive:
        _write(err, "이전 버전(0.1)의 작업 폴더를 아직 옮기지 않아 종료합니다. %s\n프로그램을 창으로 켜서 안내를 따르거나 "
               "scripts/migrate_names.py --work-root로 옮긴 뒤 다시 실행하세요.\n" % stays)
        return EXIT_OLD_LAYOUT
    if plan.state == "conflict":
        _log.warning("옛 작업 폴더를 옮기지 않음: %s", " ".join(plan.conflicts))
        notify(MOVE_TITLE, "이전 버전(0.1)의 작업 폴더를 옮길 수 없어 프로그램을 시작하지 않습니다.\n\n%s\n\n%s\n\n"
               "위 까닭을 정리한 뒤 다시 시작하면 옮길지 묻습니다." % ("\n".join(plan.conflicts), stays))
        return EXIT_OLD_LAYOUT
    if not locked:
        return stop("작업 폴더의 잠금을 잡지 못해 이전 버전(0.1)의 폴더를 옮기지 않았습니다. 프로그램을 시작하지 않습니다.\n\n%s\n\n"
                    "다른 HAZOP 창이 열려 있는지, 폴더에 쓸 수 있는지 확인한 뒤 다시 실행하세요." % stays)
    if not (ask or ask_move_dialog)(plan):
        _log.warning("사용자가 옛 작업 폴더를 옮기지 않기로 함: %s", root)
        notify(MOVE_TITLE, "옮기지 않았습니다. 옛 폴더를 옮겨야 이 버전을 쓸 수 있어 프로그램을 시작하지 않습니다.\n\n%s\n\n"
               "다음에 시작할 때 다시 묻습니다." % stays)
        return EXIT_OLD_LAYOUT
    try:
        (run or run_move_dialog)(root)
    except (workroot.MigrationError, OSError) as e:
        _log.warning("옛 작업 폴더를 옮기지 못함: %s (%s)", root, e)
        notify(MOVE_TITLE, "작업 폴더를 옮기지 못해 프로그램을 시작하지 않습니다.\n\n원인: %s\n\n%s\n\n"
               "옛 폴더의 파일은 지워지지 않았습니다. 다음에 시작할 때 남은 일을 이어서 합니다." % (e, stays))
        return EXIT_OLD_LAYOUT
    try:  # 옮겼다고 알리기 전에 정말 열 수 있는 배치가 됐는지 본다
        paths.require_current_layout(root)
    except paths.OldLayoutError as e:
        return stop("작업 폴더를 옮기지 못해 프로그램을 시작하지 않습니다.\n\n%s" % e)
    _log.warning("옛 작업 폴더를 0.2.0 배치로 옮김: %s", root)
    notify(MOVE_TITLE, "작업 폴더를 새 이름으로 옮겼습니다.\n\n옛 폴더는 지우지 않고 '%s' 폴더에 두었습니다.\n위치: %s\n\n"
           "자료가 모두 보이는지 확인한 뒤에 지우면 됩니다." % (workroot.KEEP_DIR, os.path.join(root, workroot.KEEP_DIR)))
    return None


def notify_running(title, text):
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Information, title, text)
    box.addButton("확인", QMessageBox.AcceptRole)
    box.exec()


def single_instance(notify=None, err=None):
    """(잠금, None) 또는 (None, EXIT_RUNNING). 작업 루트의 잠금 파일(QLockFile)을 잡는다.
    다른 실행이 쥐고 있으면 안내하고 종료 코드를 돌려준다. 잠금 파일을 만들 수 없으면(권한 등) 막지 않고 시작한다.
    잠금은 돌려받은 객체가 살아 있는 동안 유지되므로 호출한 쪽이 종료할 때까지 들고 있어야 한다."""
    from PySide6.QtCore import QLockFile
    path = os.path.join(paths.raw_work_root(), LOCK_NAME)  # 잠금은 옛 작업 폴더를 옮기기 전에도 잡는다
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError as e:
        problem = e
    else:
        lock = QLockFile(path)
        lock.setStaleLockTime(0)  # 시간으로는 버리지 않는다. 쥔 프로세스가 없어진 잠금만 버린다
        if lock.tryLock(0):
            return lock, None
        if lock.error() == QLockFile.LockFailedError:
            _log.warning("이미 실행 중: %s", path)
            (notify or notify_running)(
                "HAZOP이 이미 실행 중입니다",
                "HAZOP이 이미 실행 중입니다. 열려 있는 창으로 가서 작업하세요.\n\n"
                "저장한 작업을 서로 덮어쓰지 않도록 한 번에 하나만 실행할 수 있습니다.")
            return None, EXIT_RUNNING
        problem = lock.error()
    _log.warning("실행 잠금 파일을 만들 수 없음: %s (%s)", path, problem)
    _write(err, "실행 잠금 파일을 만들 수 없어 잠금 없이 시작합니다: %s (%s)\n" % (path, problem))
    return None, None


# ---------------------------------------------------------------- 새 웹 화면으로 시작(docs/design/app-shell-web.md §6)

def window_kind(classic=False, screenshots=None, run=None):
    """어느 창으로 시작할지: 새 웹 화면("shell") 또는 이전 위젯 화면("classic"). 이전 화면은 `--classic`, 스크린샷 찍기(`--screenshots`),
    분석 실행 폴더 열기(`--run`, 이전 화면만 아는 기능)일 때만 쓴다. 두 창을 함께 열지 않는다(같은 파일을 두 창이 쓰지 않게)."""
    return "classic" if classic or screenshots or run else "shell"


def run_shell(app, settings_path=None, debug=False):
    """새 틀 창을 열고 이벤트 루프를 돈다. 설정의 '이전 화면 열기'로 닫히면 같은 설정으로 이전 화면을 이어서 연다. 종료 코드를 돌려준다."""
    from hazop.shell.window import ShellWindow
    win = ShellWindow(settings_path=settings_path, debug=debug)
    win.show()
    win.ai_conn.start()   # 지금 연결 방식만 확인(구독은 작업 스레드에서 check())
    code = app.exec()
    switch = win.classic_requested
    win.close()
    if switch:
        from hazop.app.main_window import MainWindow
        classic = MainWindow(settings_path=settings_path, ask_reviewer=True, debug=debug)
        classic.show()
        classic.ai_conn.start()
        code = app.exec()
        classic.close()
    return code
