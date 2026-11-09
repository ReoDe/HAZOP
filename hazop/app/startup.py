"""시작 전 설정 파일 확인 (패키징 W10, D18). scripts/run_app.py가 MainWindow를 만들기 전에 부른다.

설정 파일(settings.json)을 읽을 수 없으면 기본값으로 조용히 덮어쓰지 않는다(hazop/paths.load_settings 원칙 유지).
- 손상(JSON 문법 오류·JSON 객체 아님·UTF-8 아님): 대화형은 한국어 대화상자로 경로·원인을 보여 주고 "기존 파일을 백업하고
  기본값으로 시작"(settings.json → settings.json.bad-<시각>.json으로 이름 바꿈) 또는 "종료"를 고르게 한다. 대화상자 응답 뒤
  이름을 바꾸기 직전에 파일을 다시 확인해(크기·수정 시각·내용 해시) 그사이 바뀌었으면 백업하지 않고 다시 판정한다.
- 읽기 실패(OSError: 권한·잠금 등): 백업 선택지 없이 안내 후 종료.
비대화형 실행(--screenshots)은 대화상자 없이 stderr에 안내하고 종료 코드 2로 끝낸다.

한 작업 루트에서는 대화형 실행을 하나만 띄운다(single_instance). 두 실행이 같은 저장본을 따로 고치다 덮어쓰지 않게 하려는 것이다.
"""

import hashlib
import logging
import os
import sys
import time

from hazop import paths

BACKUP = "backup"
QUIT = "quit"
CORRUPT = "corrupt"        # 내용 손상: 백업 후 기본값으로 시작할 수 있음
UNREADABLE = "unreadable"  # 읽기 실패(OSError): 종료만
EXIT_SETTINGS = 2  # 설정 파일 때문에 시작하지 않음
EXIT_RUNNING = 3   # 같은 작업 루트에서 이미 실행 중이라 시작하지 않음
LOCK_NAME = ".hazop-app.lock"
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
    path = paths.work_path(LOCK_NAME)
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
