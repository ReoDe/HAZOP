"""시작 전 설정 파일 확인·정보 창 고지 위치 테스트 (패키징 W10, D18). 실행: python -m unittest tests.test_app_startup

QT_QPA_PLATFORM=offscreen. 설정 파일은 임시 폴더에만 만든다. 대화상자·탐색기는 대역으로 바꿔 실제로 띄우지 않는다.
"""

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.app import startup  # noqa: E402

BROKEN = {"syntax": (b"{ not json", "JSONDecodeError"), "array": (b"[]", "ValueError: 설정 파일이 JSON 객체가 아님"),
          "encoding": (b'{"reviewer_name": "\xff"}', "UnicodeDecodeError")}


def _run_app():
    spec = importlib.util.spec_from_file_location("hazop_run_app_t", os.path.join(REPO_ROOT, "scripts", "run_app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SettingsCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-settings-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "settings.json")

    def write(self, data):
        with open(self.path, "wb") as fh:
            fh.write(data)

    def read(self):
        with open(self.path, "rb") as fh:
            return fh.read()

    def test_settings_error(self):
        self.assertIsNone(startup.settings_error(self.path))  # 파일 없음 = 기본값
        self.write(b'{"reviewer_name": "kim"}')
        self.assertIsNone(startup.settings_error(self.path))
        for data, cause in BROKEN.values():
            self.write(data)
            kind, text = startup.settings_error(self.path)
            self.assertEqual(kind, startup.CORRUPT)
            self.assertIn(cause, text)
        self.write(b'\xef\xbb\xbf{"reviewer_name": "kim"}')  # UTF-8 BOM(메모장 저장)은 손상이 아님
        self.assertIsNone(startup.settings_error(self.path))
        self.assertEqual(paths.load_settings(self.path)["reviewer_name"], "kim")
        with mock.patch.object(paths, "load_settings", side_effect=PermissionError(13, "거부")):
            self.assertEqual(startup.settings_error(self.path)[0], startup.UNREADABLE)

    def test_stat_permission_error_is_unreadable_not_missing(self):
        """존재 확인 단계의 권한 오류를 '설정 없음'(기본값으로 시작)으로 삼키지 않는다(Codex 재검토, 총괄 수정)."""
        self.write(b'{"reviewer_name": "kim"}')
        real_stat = os.stat

        def stat(p, *a, **k):
            if os.path.normcase(os.fspath(p)) == os.path.normcase(self.path):
                raise PermissionError(13, "거부")
            return real_stat(p, *a, **k)
        with mock.patch.object(paths.os, "stat", side_effect=stat):
            with self.assertRaises(PermissionError):
                paths.load_settings(self.path)
            self.assertEqual(startup.settings_error(self.path)[0], startup.UNREADABLE)
        os.remove(self.path)
        self.assertEqual(paths.load_settings(self.path), paths.DEFAULT_SETTINGS)  # 정말 없으면 기본값
        os.mkdir(self.path)
        self.assertEqual(startup.settings_error(self.path)[0], startup.UNREADABLE)  # 폴더면 읽기 실패

    def test_unreadable_quits_without_backup_choice(self):
        """OSError(권한·잠금): 대화형은 백업 선택지 없이 안내 후 종료, 비대화형은 stderr·rc 2. 파일은 그대로."""
        self.write(b'{"reviewer_name": "kim"}')
        with mock.patch.object(paths, "load_settings", side_effect=PermissionError(13, "거부")):
            ask, notify = mock.Mock(), mock.Mock()
            self.assertEqual(startup.check_settings(self.path, True, ask=ask, notify=notify), 2)
            ask.assert_not_called()
            notify.assert_called_once()
            self.assertIn("PermissionError", notify.call_args[0][1])
            err = io.StringIO()
            self.assertEqual(startup.check_settings(self.path, False, ask=ask, err=err), 2)
            self.assertIn("권한·잠금", err.getvalue())
        self.assertEqual(os.listdir(self.tmp), ["settings.json"])

    def test_failures_logged_as_warning(self):
        self.write(b"[]")
        with self.assertLogs("hazop.settings", "WARNING") as cm:
            startup.check_settings(self.path, False, err=io.StringIO())
        self.assertIn("설정 파일을 읽을 수 없음", cm.output[0])

    def test_file_changed_during_dialog_is_rejudged(self):
        """대화상자 응답과 이름 바꾸기 사이에 파일이 바뀌면 백업하지 않고 다시 판정한다."""
        self.write(b"[]")

        def fix(path, cause):  # 사용자가 대화상자를 띄운 채 파일을 고침
            self.write(b'{"reviewer_name": "kim"}')
            return startup.BACKUP
        self.assertIsNone(startup.check_settings(self.path, True, ask=fix))
        self.assertEqual(os.listdir(self.tmp), ["settings.json"])  # 백업 없음, 고친 파일 그대로
        self.write(b"[]")
        answers = []

        def other_damage(path, cause):  # 첫 응답 사이 다른 손상으로 바뀜 -> 다시 묻고, 두 번째는 종료
            answers.append(cause)
            if len(answers) == 1:
                self.write(b"{ not json")
                return startup.BACKUP
            return startup.QUIT
        self.assertEqual(startup.check_settings(self.path, True, ask=other_damage), 2)
        self.assertEqual(len(answers), 2)
        self.assertIn("JSONDecodeError", answers[1])
        self.assertEqual(self.read(), b"{ not json")
        self.assertEqual(os.listdir(self.tmp), ["settings.json"])

    def test_ok_settings_never_asks(self):
        ask = mock.Mock()
        self.assertIsNone(startup.check_settings(self.path, True, ask=ask))
        ask.assert_not_called()

    def test_non_interactive_rc2_no_dialog(self):
        for data, cause in BROKEN.values():
            self.write(data)
            ask, err = mock.Mock(), io.StringIO()
            self.assertEqual(startup.check_settings(self.path, False, ask=ask, err=err), 2)
            ask.assert_not_called()
            self.assertIn("설정 파일을 읽을 수 없어 종료합니다: %s" % self.path, err.getvalue())
            self.assertIn(cause, err.getvalue())
            self.assertEqual(self.read(), data)  # 덮어쓰지 않음
            self.assertEqual(os.listdir(self.tmp), ["settings.json"])
        with mock.patch.object(sys, "stderr", None):  # stderr가 없는 창 프로그램에서도 종료 코드만 돌려준다
            self.assertEqual(startup.check_settings(self.path, False), 2)

    def test_quit_keeps_file(self):
        self.write(b"[]")
        ask = mock.Mock(return_value=startup.QUIT)
        self.assertEqual(startup.check_settings(self.path, True, ask=ask), 2)
        ask.assert_called_once()
        self.assertEqual(ask.call_args[0][0], self.path)
        self.assertIn("JSON 객체가 아님", ask.call_args[0][1])
        self.assertEqual(self.read(), b"[]")

    def test_backup_renames_and_starts_with_defaults(self):
        self.write(b"{ not json")
        now = 1793232000.0  # 고정 시각
        dest = startup.backup_name(self.path, now)
        self.assertRegex(os.path.basename(dest), r"^settings\.json\.bad-\d{8}-\d{6}\.json$")
        self.assertIsNone(startup.check_settings(self.path, True, ask=lambda p, c: startup.BACKUP, now=now))
        self.assertFalse(os.path.exists(self.path))
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"{ not json")
        self.assertEqual(paths.load_settings(self.path), paths.DEFAULT_SETTINGS)

    def test_backup_failure_quits(self):
        self.write(b"[]")
        now = 1793232000.0
        with open(startup.backup_name(self.path, now), "wb") as fh:  # 같은 이름이 있으면 덮어쓰지 않고 실패
            fh.write(b"old")
        notify = mock.Mock()
        self.assertEqual(startup.check_settings(self.path, True, ask=lambda p, c: startup.BACKUP, notify=notify,
                                                now=now), 2)
        notify.assert_called_once()
        self.assertEqual(self.read(), b"[]")
        with open(startup.backup_name(self.path, now), "rb") as fh:
            self.assertEqual(fh.read(), b"old")


class RunAppStartupTest(unittest.TestCase):
    """scripts/run_app.main: MainWindow를 만들기 전에 설정 파일을 확인한다."""

    @classmethod
    def setUpClass(cls):
        cls.ra = _run_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-runapp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: os.path.join(self.tmp, "work")})
        env.start()
        self.addCleanup(env.stop)
        self.path = os.path.join(self.tmp, "settings.json")
        with open(self.path, "wb") as fh:
            fh.write(b"{ not json")

    def test_screenshots_rc2_before_window(self):
        png = os.path.join(self.tmp, "png")
        err = io.StringIO()
        with mock.patch("hazop.app.make_application") as make_app, mock.patch.object(sys, "stderr", err), \
                mock.patch.object(startup, "ask_dialog") as ask:
            self.assertEqual(self.ra.main(["--screenshots", png, "--settings", self.path]), 2)
        make_app.assert_not_called()  # QApplication·창을 만들지 않음
        ask.assert_not_called()
        self.assertIn("JSONDecodeError", err.getvalue())
        self.assertFalse(os.path.exists(png))

    def test_interactive_quit_before_window(self):
        with mock.patch.object(startup, "ask_dialog", return_value=startup.QUIT) as ask, \
                mock.patch("hazop.app.main_window.MainWindow") as win:
            self.assertEqual(self.ra.main(["--settings", self.path]), 2)
        ask.assert_called_once()
        win.assert_not_called()

    def test_test_excepthook_trigger_only_in_verify_build(self):
        """시험 트리거는 검증용 빌드 표지(sys._hazop_verify_build)가 있을 때만 켜진다(배포용·개발 실행은 무시)."""
        png = os.path.join(self.tmp, "png")
        for marker, want in ((True, 70), (False, 2)):
            calls = []
            with mock.patch.dict(os.environ, {self.ra.ENV_TEST_EXCEPTHOOK: "1"}), \
                    mock.patch.object(sys, "_hazop_verify_build", marker, create=True), \
                    mock.patch.object(sys, "excepthook", lambda *a: calls.append(a)), \
                    mock.patch.object(sys, "stderr", io.StringIO()), \
                    mock.patch("hazop.app.make_application") as make_app:
                self.assertEqual(self.ra.main(["--screenshots", png, "--settings", self.path]), want)
            make_app.assert_not_called()
            self.assertEqual(len(calls), 1 if marker else 0)
            if marker:
                self.assertIs(calls[0][0], RuntimeError)
                self.assertIn("HAZOP_TEST_EXCEPTHOOK", str(calls[0][1]))

    def test_interactive_backup_then_window_with_defaults(self):
        """대화형 "백업" 선택 -> 이름 바꾼 뒤 기본값 설정으로 MainWindow를 만든다(창·이벤트 루프는 대역)."""
        seen = {}

        def make_win(settings_path=None, ask_reviewer=True, debug=False):
            seen.update(path=settings_path, ask=ask_reviewer, settings=paths.load_settings(settings_path))
            return mock.Mock()
        app = mock.Mock()
        app.exec.return_value = 0
        with mock.patch.object(startup, "ask_dialog", return_value=startup.BACKUP), \
                mock.patch("hazop.app.make_application", return_value=app), \
                mock.patch("hazop.app.main_window.MainWindow", side_effect=make_win):
            self.assertEqual(self.ra.main(["--settings", self.path]), 0)   # 3단계가 끝날 때까지 이전 화면이 기본
        self.assertEqual(seen["path"], self.path)
        self.assertTrue(seen["ask"])  # 처음 실행처럼 검토자 이름을 묻는다
        self.assertEqual(seen["settings"], paths.DEFAULT_SETTINGS)
        backups = [n for n in os.listdir(self.tmp) if n.startswith("settings.json.bad-")]
        self.assertEqual(len(backups), 1)


    def test_default_start_opens_the_classic_window_until_stage3(self):
        app = mock.Mock()
        app.exec.return_value = 0
        with mock.patch.object(startup, "ask_dialog", return_value=startup.BACKUP), \
                mock.patch("hazop.app.make_application", return_value=app), \
                mock.patch("hazop.shell.window.ShellWindow") as shell, \
                mock.patch("hazop.app.main_window.MainWindow", return_value=mock.Mock()) as classic:
            self.assertEqual(self.ra.main(["--settings", self.path]), 0)
        shell.assert_not_called()
        classic.assert_called_once()

    def test_shell_flag_or_setting_opens_the_new_web_window(self):
        seen = {}

        def make_shell(settings_path=None, debug=False, **kw):
            seen.update(path=settings_path, debug=debug)
            win = mock.Mock()
            win.classic_requested = False
            return win
        app = mock.Mock()
        app.exec.return_value = 0
        with mock.patch.object(startup, "ask_dialog", return_value=startup.BACKUP),                 mock.patch("hazop.app.make_application", return_value=app),                 mock.patch("hazop.shell.window.ShellWindow", side_effect=make_shell),                 mock.patch("hazop.app.main_window.MainWindow") as classic:
            self.assertEqual(self.ra.main(["--shell", "--settings", self.path]), 0)
        self.assertEqual(seen["path"], self.path)
        classic.assert_not_called()

    def test_classic_switch_from_settings_opens_the_old_window_after_the_new_one_closes(self):
        calls = []
        shell = mock.Mock()
        shell.classic_requested = True
        app = mock.Mock()
        app.exec.return_value = 0
        with mock.patch.object(startup, "ask_dialog", return_value=startup.BACKUP),                 mock.patch("hazop.app.make_application", return_value=app),                 mock.patch("hazop.shell.window.ShellWindow", return_value=shell),                 mock.patch("hazop.app.main_window.MainWindow", side_effect=lambda **kw: calls.append(kw) or mock.Mock()):
            self.assertEqual(self.ra.main(["--shell", "--settings", self.path]), 0)
        self.assertEqual(len(calls), 1, "두 창을 함께 열지 않고 새 창이 닫힌 뒤 이전 창을 연다")
        self.assertEqual(app.exec.call_count, 2)

    def test_window_kind_choice(self):
        self.assertEqual(startup.window_kind(), "classic")
        self.assertEqual(startup.window_kind(shell=True), "shell")
        self.assertEqual(startup.window_kind(setting=True), "shell")
        self.assertEqual(startup.window_kind(shell=True, classic=True), "classic")
        self.assertEqual(startup.window_kind(setting=True, classic=True), "classic")
        self.assertEqual(startup.window_kind(shell=True, screenshots="x"), "classic")
        self.assertEqual(startup.window_kind(shell=True, run="r"), "classic")

    def test_ui_shell_setting_opens_the_new_window(self):
        import json as _json
        with open(self.path, "w", encoding="utf-8") as fh:
            _json.dump({"ui_shell": True}, fh)
        self.assertTrue(startup.shell_setting(self.path))
        with open(self.path, "w", encoding="utf-8") as fh:
            _json.dump({"ui_shell": "yes"}, fh)
        self.assertFalse(startup.shell_setting(self.path))
        self.assertFalse(startup.shell_setting(os.path.join(self.tmp, "none.json")))

    def test_second_instance_quits_before_window(self):
        """다른 실행이 잠금을 쥐고 있으면 대화형 실행은 안내 후 창을 만들지 않고 끝낸다. --screenshots는 잠금을 보지 않는다."""
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{")
        held, rc = startup.single_instance(notify=mock.Mock())
        self.assertIsNone(rc)
        self.addCleanup(held.unlock)
        with mock.patch.object(startup, "notify_running") as notify, \
                mock.patch.object(startup, "ask_dialog") as ask, \
                mock.patch("hazop.app.main_window.MainWindow") as win:
            self.assertEqual(self.ra.main(["--settings", self.path]), startup.EXIT_RUNNING)
        notify.assert_called_once()
        ask.assert_not_called()
        win.assert_not_called()
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{", "실행 중인 프로그램의 설정 파일은 두 번째 실행이 건드리지 않음")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with mock.patch("hazop.app.main_window.MainWindow") as win, \
                mock.patch("hazop.app.screenshots.take_all", return_value=[]), \
                mock.patch.object(startup, "notify_running") as notify:
            self.assertEqual(self.ra.main(["--screenshots", os.path.join(self.tmp, "png"), "--settings", self.path]), 0)
        notify.assert_not_called()
        win.assert_called_once()


class SingleInstanceTest(unittest.TestCase):
    """한 작업 루트에서는 프로그램을 하나만 띄운다(두 창이 같은 저장본을 덮어쓰지 않게)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-lock-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: os.path.join(self.tmp, "work")})
        env.start()
        self.addCleanup(env.stop)

    def test_second_acquisition_is_refused_until_first_exits(self):
        notify = mock.Mock()
        first, rc = startup.single_instance(notify=notify)
        self.assertIsNone(rc)
        self.assertTrue(first.isLocked())
        second, rc = startup.single_instance(notify=notify)
        self.assertIsNone(second)
        self.assertEqual(rc, startup.EXIT_RUNNING)
        notify.assert_called_once()
        self.assertIn("이미 실행 중", notify.call_args[0][1])
        first.unlock()
        third, rc = startup.single_instance(notify=notify)
        self.assertIsNone(rc, "먼저 띄운 실행이 끝나면 다시 띄울 수 있음")
        third.unlock()

    def test_lock_that_cannot_be_created_does_not_block(self):
        err = io.StringIO()
        with mock.patch("hazop.app.startup.os.makedirs", side_effect=PermissionError(13, "거부")):
            lock, rc = startup.single_instance(notify=mock.Mock(), err=err)
        self.assertIsNone(rc)
        self.assertIn("잠금", err.getvalue())

class AboutLicensesTest(unittest.TestCase):
    """도움말 > 버전·데이터 위치: 고지 폴더 위치(개발 = 저장소 licenses/, 묶인 실행 = 실행 파일 옆), 열기 버튼 동작."""

    def test_licenses_dir_dev_and_frozen(self):
        with mock.patch.object(sys, "_MEIPASS", None, create=True):
            self.assertEqual(paths.licenses_dir(), os.path.join(REPO_ROOT, "licenses"))
        exe = os.path.join(tempfile.gettempdir(), "한글 폴더", "HAZOP", "HAZOP.exe")
        with mock.patch.object(sys, "_MEIPASS", os.path.join(os.path.dirname(exe), "_internal"), create=True), \
                mock.patch.object(sys, "executable", exe):
            self.assertEqual(paths.licenses_dir(), os.path.join(os.path.dirname(exe), "licenses"))

    def test_about_text_and_open(self):
        from hazop.app import make_application, main_window
        make_application(["test"])
        stub = types.SimpleNamespace(settings_path=os.path.join(tempfile.gettempdir(), "s.json"))
        text = main_window.MainWindow.about_text(stub)
        self.assertIn("제3자 라이선스 고지: %s" % paths.licenses_dir(), text)
        self.assertIn(main_window.LICENSE_NOTE, text)
        self.assertIn("법무 검토 전", main_window.LICENSE_NOTE)
        with mock.patch.object(main_window.QDesktopServices, "openUrl", return_value=True) as open_url:
            self.assertTrue(main_window.MainWindow.open_licenses(None))
        self.assertEqual(os.path.normcase(open_url.call_args[0][0].toLocalFile()),
                         os.path.normcase(paths.licenses_dir().replace("\\", "/")))
        with mock.patch.object(main_window.QDesktopServices, "openUrl", return_value=False), \
                mock.patch.object(main_window.QMessageBox, "information") as info:
            self.assertFalse(main_window.MainWindow.open_licenses(None))
        self.assertIn(paths.licenses_dir(), info.call_args[0][2])  # 열지 못하면 경로를 보여 줌
        buttons = []

        def fake_exec(box):
            buttons.extend(b.text() for b in box.buttons())
            return 0
        from PySide6.QtWidgets import QWidget
        parent = QWidget()  # _about의 부모 창 대역
        self.addCleanup(parent.deleteLater)
        parent.about_text = lambda: main_window.MainWindow.about_text(stub)
        parent.open_licenses = mock.Mock()
        with mock.patch.object(main_window.QMessageBox, "exec", fake_exec):
            main_window.MainWindow._about(parent)
        self.assertEqual(sorted(buttons), sorted(["라이선스 고지 열기", "닫기"]))
        parent.open_licenses.assert_not_called()  # 닫기(누른 버튼 없음)면 열지 않음
        missing = os.path.join(tempfile.gettempdir(), "hazop-no-such-licenses")
        with mock.patch.object(paths, "licenses_dir", return_value=missing), \
                mock.patch.object(main_window.QMessageBox, "warning") as warn, \
                mock.patch.object(main_window.QDesktopServices, "openUrl") as open_url:
            self.assertFalse(main_window.MainWindow.open_licenses(None))
        warn.assert_called_once()
        open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
