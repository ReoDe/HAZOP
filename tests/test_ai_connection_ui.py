"""AI 연결 화면(디자인/AI연결-화면설계.md §2~§5·§9·§10) 시험: 연결 상태 표, 연결 설정 묶음, 'AI 연결 설정' 창,
상태줄 연결 칩. 실제 구독·API 호출 없음: 구독 확인은 tests/fake_claude/fake_claude.py를 argv_prefix로 주입하고,
API 연결 시험은 가짜 전송 함수를 쓴다. 작업 루트·저장 루트·설정 파일은 임시 폴더다.
실행: python -m pytest -q tests/test_ai_connection_ui.py
"""

import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # 맑은 고딕으로 재야 칩 폭이 실제와 같다

from hazop import paths  # noqa: E402
from hazop.app import conn_view  # noqa: E402
from hazop.study import ai_settings, claude_cli, providers  # noqa: E402
from hazop.study.ai_settings import AiPrefs  # noqa: E402
from hazop.study.apikey import KeyStore  # noqa: E402

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude", "fake_claude.py")
KEY = "sk-ant-api03-TESTTESTTEST-conn-ui-a1b2"
# 기술 설계 §0.2 표의 conn_state 전부
SPEC_STATES = ("checking", "disabled", "not_installed", "cli_too_old", "cli_unsupported", "login_required",
               "login_expired", "not_subscription", "account_blocked", "limit_reached", "overage_risk", "limit_warning",
               "no_key", "key_invalid", "no_permission", "no_credit", "rate_limited", "model_unavailable", "no_folder",
               "network", "error", "unchecked", "ok")
BLOCKED = ("not_installed", "cli_too_old", "cli_unsupported", "login_required", "login_expired", "not_subscription",
           "account_blocked", "limit_reached", "no_key", "key_invalid", "no_permission", "no_credit", "model_unavailable",
           "no_folder", "disabled")


def today_kst(hour, minute):
    now = datetime.datetime.now(claude_cli.KST)
    return int(now.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp())


def sub_status(state, **kw):
    return dict({"via": "subscription", "state": state, "detail": "", "plan": None, "limit": None,
                 "checked_at": "2026-11-09T14:02:00+09:00"}, **kw)


class FakeOpener:
    def __init__(self, status=200, body=b"{}"):
        self.status, self.body, self.calls = status, body, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append(url)
        return self.status, self.body


def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def pump_until(cond, conn=None, secs=20):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if conn is not None:
            conn.tasks.wait(50)
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


class StateTableTest(unittest.TestCase):
    def test_every_spec_state_and_cli_message_has_a_look(self):
        from hazop.app.conn_widgets import _SVG
        cli_states = {k for k in claude_cli.MESSAGES if k in SPEC_STATES}
        for method in ("subscription", "api", "fixed"):
            for state in set(SPEC_STATES) | cli_states:
                with self.subTest(method=method, state=state):
                    lk = conn_view.look(method, state)
                    self.assertIsNot(lk, conn_view.LOOKS["error"] if state != "error" else None)
                    self.assertTrue(lk.label and lk.short and lk.title)
                    self.assertIn(lk.icon, _SVG)
                    self.assertIn(lk.tone, conn_view.TONES)
                    for a in lk.actions:
                        self.assertIn(a, conn_view.ACTIONS)

    def test_blocked_states_cannot_start_and_have_thick_border(self):
        for state in BLOCKED:
            with self.subTest(state):
                lk = conn_view.look("subscription", state)
                self.assertFalse(lk.can_start)
                self.assertEqual(lk.border, 1.5)
        for state in ("ok", "unchecked", "limit_warning", "checking"):
            self.assertEqual(conn_view.look("subscription", state).border, 1.0, state)
        self.assertTrue(conn_view.can_start("subscription", "ok"))
        self.assertTrue(conn_view.can_start("api", "unchecked"))  # 시작할 때 먼저 확인
        self.assertFalse(conn_view.can_start("subscription", "checking"))

    def test_chip_text_matches_screen_design_table(self):
        limit = {"status": "limit_reached", "window": "five_hour", "resets_at": today_kst(17, 40), "utilization": 1.0}
        warn = dict(limit, status="limit_warning", utilization=0.86)
        rows = [
            ("subscription", sub_status("ok"), "구독 · Opus 5.5 · 연결됨", "구독 · Opus · 연결됨"),
            ("subscription", sub_status("checking"), "구독 · Opus 5.5 · 확인 중", "구독 · Opus · 확인 중"),
            ("subscription", sub_status("limit_warning", limit=warn), "구독 · Opus 5.5 · 한도 가까움 · 17:40 재설정",
             "구독 · Opus · 한도 가까움"),
            ("subscription", sub_status("limit_reached", limit=limit), "구독 · Opus 5.5 · 한도 도달 · 17:40 재설정",
             "구독 · Opus · 한도 · 17:40"),
            ("subscription", sub_status("login_required"), "구독 · Opus 5.5 · 로그인 필요", "구독 · Opus · 로그인 필요"),
            ("subscription", sub_status("login_expired"), "구독 · Opus 5.5 · 다시 로그인 필요", "구독 · Opus · 재로그인"),
            ("subscription", sub_status("not_subscription"), "구독 · Opus 5.5 · 구독 계정 아님", "구독 · Opus · 구독 아님"),
            ("subscription", sub_status("not_installed"), "구독 · Opus 5.5 · 미설치", "구독 · Opus · 미설치"),
            ("subscription", sub_status("cli_too_old"), "구독 · Opus 5.5 · 업데이트 필요", "구독 · Opus · 업데이트"),
            ("subscription", sub_status("network"), "구독 · Opus 5.5 · 연결 못 함", "구독 · Opus · 연결 못 함"),
            ("api", {"state": "ok"}, "API 키 · Opus 5.5 · 연결됨", "API 키 · Opus · 연결됨"),
            ("api", {"state": "unchecked"}, "API 키 · Opus 5.5 · 확인 안 함", "API 키 · Opus · 확인 안 함"),
            ("api", {"state": "no_key"}, "API 키 · Opus 5.5 · 키 없음", "API 키 · Opus · 키 없음"),
            ("api", {"state": "key_invalid"}, "API 키 · Opus 5.5 · 키 거부됨", "API 키 · Opus · 키 거부됨"),
            ("fixed", {"state": "ok"}, "시험 · 고정 응답", "시험 · 고정 응답"),
        ]
        for method, status, wide, narrow in rows:
            with self.subTest(wide):
                self.assertEqual(conn_view.chip_text(method, status, "claude-opus-5-5"), wide)
                self.assertEqual(conn_view.chip_text(method, status, "claude-opus-5-5", narrow=True), narrow)
        self.assertEqual(conn_view.chip_text("api", {"state": "ok"}, "claude-opus-5-5", this_run=True),
                         "API 키 · Opus 5.5 · 이번 실행만")

    def test_accessible_name_is_full_sentence(self):
        limit = {"status": "limit_reached", "window": "five_hour", "resets_at": today_kst(17, 40)}
        self.assertEqual(conn_view.chip_accessible("subscription", sub_status("limit_reached", limit=limit),
                                                   "claude-opus-5-5"),
                         "AI 연결: Claude 구독, 모델 Opus 5.5, 한도 도달, 17시 40분 재설정")
        self.assertEqual(conn_view.list_accessible("subscription", sub_status("ok"), True), "Claude 구독, 연결됨, 사용 중")
        self.assertEqual(conn_view.status_accessible("subscription", sub_status("login_required"))[0],
                         "연결 상태: 로그인 필요")

    def test_usage_lines_follow_limit_rules(self):
        unknown = conn_view.usage_lines(None)
        self.assertEqual(unknown[0][0], "한도 정보가 없습니다. 첫 호출 뒤에 보입니다.")
        seen = datetime.datetime.now(claude_cli.KST).replace(hour=14, minute=2).isoformat()
        ok = {"status": "limit_ok", "window": "five_hour", "utilization": 0.38, "resets_at": today_kst(17, 40),
              "seen_at": seen}
        text, say, warn = conn_view.usage_lines(ok)[0]
        self.assertEqual(text, "5시간 한도 38% 사용 · 17:40 재설정 (14:02 호출 기준)")
        self.assertEqual(say, "5시간 한도 38퍼센트 사용, 17시 40분 재설정, 14시 2분 호출 기준")
        self.assertEqual(warn, "")
        self.assertTrue(conn_view.usage_lines(dict(ok, status="limit_warning", utilization=0.86))[0][2])
        reached = conn_view.usage_lines(dict(ok, status="limit_reached"))[0][0]
        self.assertEqual(reached, "5시간 한도 도달 · 17:40 재설정")
        no_util = conn_view.usage_lines(dict(ok, utilization=None, window="seven_day"))[0][0]
        self.assertNotIn("%", no_util)
        self.assertTrue(no_util.startswith("주간 한도"))
        for lim in (ok, dict(ok, utilization=None), None):
            self.assertNotIn("여유", conn_view.usage_lines(lim)[0][0])

    def test_guide_texts_fill_reset_time(self):
        limit = {"status": "limit_reached", "resets_at": today_kst(17, 40)}
        self.assertIn("17:40에 다시 쓸 수 있습니다",
                      conn_view.guide_text("subscription", sub_status("limit_reached", limit=limit)))
        self.assertIn("재설정 시각은 아직 알 수 없습니다",
                      conn_view.guide_text("subscription", sub_status("limit_reached", limit={"status": "limit_reached"})))
        self.assertIn("86%, 17:40 재설정", conn_view.guide_text("subscription", sub_status(
            "limit_warning", limit={"status": "limit_warning", "utilization": 0.86, "resets_at": today_kst(17, 40)})))

    def test_plan_names(self):
        self.assertEqual(conn_view.plan_name("max_20x"), "Max 20x 요금제")
        self.assertEqual(conn_view.plan_name("pro"), "Pro 요금제")
        self.assertEqual(conn_view.plan_name("team_standard"), "Team 요금제 (team_standard)")
        self.assertEqual(conn_view.plan_name(None), "")

    def test_api_status_from_last_test(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = KeyStore(os.path.join(tmp, "api_keys.json"))
        self.assertEqual(conn_view.api_status(store)["state"], "no_key")
        kid = store.add("시험", KEY, persist=False)
        self.assertEqual(conn_view.api_status(store)["state"], "unchecked")
        for msg, state in (("키가 거부됨(HTTP 401). 키를", "key_invalid"), ("이 키에 권한이 없음(HTTP 403).", "no_permission"),
                           ("크레딧이 부족하거나 결제 문제가 있음(HTTP 400).", "no_credit"),
                           ("사용 한도를 넘음(HTTP 429).", "rate_limited"),
                           ("AI 서비스에 연결하지 못함(네트워크·프록시 확인)", "network")):
            store._entry(kid)["last_test"] = {"at": "2026-11-09T05:02:00Z", "ok": False, "model": store.model,
                                              "message": msg}
            self.assertEqual(conn_view.api_status(store)["state"], state, msg)
        store._entry(kid)["last_test"]["model"] = "claude-haiku-5-5"
        self.assertEqual(conn_view.api_status(store)["state"], "unchecked", "다른 모델로 한 시험은 확인 안 함")


class PrefsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_old_settings_file_reads_defaults_and_keeps_other_fields(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"reviewer_name": "김검토", "recent_runs": []}, fh, ensure_ascii=False)
        settings = paths.load_settings(self.path)
        prefs = AiPrefs(settings, lambda s: paths.save_settings(s, self.path))
        self.assertIsNone(prefs.chosen_method)
        self.assertIsNone(prefs.terms_ack_at)
        self.assertFalse(prefs.allow_overage)
        self.assertEqual(prefs.concurrency, 1)
        self.assertEqual(prefs.model("subscription"), "claude-opus-5-5")
        prefs.choose("api")
        prefs.ack_terms()
        again = paths.load_settings(self.path)
        self.assertEqual(again["reviewer_name"], "김검토")
        self.assertEqual(AiPrefs(again).chosen_method, "api")
        self.assertTrue(AiPrefs(again).terms_ack_at.endswith("+09:00"), "확인 시각은 KST")

    def test_concurrency_is_clamped_to_two(self):
        self.assertEqual(AiPrefs({"ai_concurrency": 5}).concurrency, 2)
        self.assertEqual(AiPrefs({"ai_concurrency": "x"}).concurrency, 1)

    def test_default_method_rules_from_screen_design_table(self):
        dev = ("subscription", "api")
        self.assertEqual(ai_settings.auto_method("ok", False, dev), "subscription")
        self.assertEqual(ai_settings.auto_method("login_required", True, dev), "api")
        self.assertEqual(ai_settings.auto_method("login_required", False, dev), "subscription")
        self.assertEqual(ai_settings.auto_method("ok", True, ("api",)), "api", "배포본은 API")
        # 토스트: 처음 켠 사용자(키 없음)는 알리지 않음, 기존 API 사용자는 바뀌면 알림, 같으면 조용히
        self.assertIsNone(ai_settings.auto_notice(None, "subscription", False))
        self.assertEqual(ai_settings.auto_notice(None, "subscription", True), ai_settings.NOTICE_TO_SUBSCRIPTION)
        self.assertEqual(ai_settings.auto_notice("subscription", "api", True), ai_settings.NOTICE_TO_API)
        self.assertIsNone(ai_settings.auto_notice("subscription", "subscription", True))

    def test_bundle_hides_subscription_and_ignores_saved_choice(self):
        with mock.patch.object(sys, "_MEIPASS", self.tmp, create=True):
            self.assertEqual(providers.available_methods(), ("api",))
            prefs = AiPrefs({"ai_method": "subscription"})
            self.assertIsNone(prefs.chosen_method)
            with self.assertRaises(ValueError):
                prefs.choose("subscription")


class ConnCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "log")
        self.limits = os.path.join(self.tmp, "ai_limits.json")
        self.store = KeyStore(os.path.join(self.tmp, "api_keys.json"))
        self.settings = {}
        self.saved = []

    def prefs(self):
        return AiPrefs(self.settings, lambda s: self.saved.append(dict(s)))

    def factory(self, scenario):
        def make(path, **kw):
            return claude_cli.ClaudeCliClient(argv_prefix=[sys.executable, FAKE, scenario, self.log],
                                              limits_path=self.limits, run_root=os.path.join(self.tmp, "run"), **kw)
        return make

    def conn(self, scenario="ok", debug=False, opener=None):
        from hazop.app.ai_conn import AiConnection
        c = AiConnection(self.prefs(), self.store, debug=debug, cli_factory=self.factory(scenario),
                         opener=opener or FakeOpener())
        self.addCleanup(c.tasks.wait, 20000)
        return c

    def checked(self, conn, method="subscription"):
        conn.check(method)
        self.assertTrue(pump_until(lambda: conn.status(method)["state"] != "checking", conn), "확인이 끝나야 함")
        return conn.status(method)

    def dialog(self, conn):
        from hazop.app.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.store, conn=conn)
        self.addCleanup(dlg.deleteLater)
        return dlg

    def texts(self, widget):
        from PySide6.QtWidgets import QLabel
        return "\n".join(w.text() for w in widget.findChildren(QLabel) if w.isVisibleTo(widget))


@unittest.skipUnless(sys.platform == "win32", "가짜 CLI는 claude_cli의 Windows 프로세스 정리를 쓴다")
class FakeCliScenarioTest(ConnCase):
    def test_scenarios_show_in_status_and_dialog(self):
        future = int(time.time()) + 3600
        cases = (("ok", None, "ok", "연결됨", None),
                 ("logged_out", None, "login_required", "로그인 필요", "로그인이 필요합니다"),
                 ("console", None, "not_subscription", "구독 계정 아님", "구독 계정이 아닙니다"),
                 ("ok", {"status": "limit_reached", "resets_at": future}, "limit_reached", "한도 도달",
                  "구독 사용 한도에 닿았습니다"))
        for scenario, limit, state, label, band in cases:
            with self.subTest(scenario=scenario, limit=bool(limit)):
                if limit:
                    claude_cli.save_limit(self.limits, limit)
                elif os.path.exists(self.limits):
                    os.remove(self.limits)
                conn = self.conn(scenario)
                status = self.checked(conn)
                self.assertEqual(status["state"], state)
                self.assertIn(label, conn_view.chip_text("subscription", status, conn.model("subscription")))
                dlg = self.dialog(conn)
                dlg.select("subscription")
                self.assertEqual(dlg.sub_chip.text(), label)
                self.assertEqual(dlg.sub_band.isVisibleTo(dlg), band is not None)
                if band:
                    self.assertEqual(dlg.sub_band.title.text(), band)
                if state == "ok":
                    self.assertIn("Max 20x 요금제", dlg.account_label.text())
                    self.assertNotIn("someone@example.com", self.texts(dlg))
                if state == "limit_reached":
                    self.assertIn("to_api", dlg.sub_band.btns)

    def test_first_start_for_existing_api_user_switches_and_toasts_once(self):
        self.store.add("기존", KEY, persist=False)
        conn = self.conn("ok")
        notices = []
        conn.notice.connect(notices.append)
        conn.start()
        self.assertTrue(pump_until(lambda: conn.status("subscription")["state"] == "ok", conn))
        self.assertEqual(conn.method, "subscription")
        self.assertEqual(notices, [ai_settings.NOTICE_TO_SUBSCRIPTION])
        again = self.conn("ok")
        again.notice.connect(notices.append)
        again.start()
        self.assertTrue(pump_until(lambda: again.status("subscription")["state"] == "ok", again))
        self.assertEqual(len(notices), 1, "결과가 같으면 다시 알리지 않음")
        broken = self.conn("logged_out")
        broken.notice.connect(notices.append)
        broken.start()
        self.assertTrue(pump_until(lambda: broken.status("subscription")["state"] == "login_required", broken))
        self.assertEqual(broken.method, "api")
        self.assertEqual(notices[-1], ai_settings.NOTICE_TO_API)
        self.assertIsNone(self.settings.get("ai_method"), "앱이 정한 방식은 사용자가 고른 방식으로 저장하지 않음")


    def test_recheck_keeps_method_the_app_chose_at_start(self):
        """앱이 정한 기본 방식은 앱을 켤 때만 다시 정한다(화면 설계 §4). 한도를 본 다시 확인으로 API 키로 넘어가지 않음."""
        self.store.add("기존", KEY, persist=False)
        conn = self.conn("ok")
        notices = []
        conn.notice.connect(notices.append)
        conn.start()
        self.assertTrue(pump_until(lambda: conn.status("subscription")["state"] == "ok", conn))
        claude_cli.save_limit(self.limits, {"status": "limit_reached", "resets_at": int(time.time()) + 3600})
        self.assertEqual(self.checked(conn)["state"], "limit_reached")
        self.assertEqual(conn.method, "subscription")
        self.assertEqual(notices, [ai_settings.NOTICE_TO_SUBSCRIPTION])
        self.assertEqual(self.settings.get("ai_method_auto"), "subscription")
        again = self.conn("ok")
        again.start()
        self.assertTrue(pump_until(lambda: again.status("subscription")["state"] == "limit_reached", again))
        self.assertEqual(again.method, ai_settings.auto_method("limit_reached", True, again.methods()),
                         "다음 시작 때 다시 정함")


class SettingsDialogFlowTest(ConnCase):
    def test_use_api_asks_cost_once_and_cancel_keeps_method(self):
        self.store.add("회사", KEY, persist=False)
        conn = self.conn()
        dlg = self.dialog(conn)
        self.assertEqual(conn.method, "subscription")
        dlg.select("api")
        self.assertEqual(conn.method, "subscription", "목록에서 고르기만 하면 방식은 그대로")
        self.assertTrue(dlg.use_btn.isEnabled())
        asked = []
        dlg._ask_api_switch = lambda: asked.append(1) or False
        self.assertFalse(dlg.use_viewed())
        self.assertEqual((asked, conn.method), ([1], "subscription"))
        dlg._ask_api_switch = lambda: asked.append(1) or True
        self.assertTrue(dlg.use_viewed())
        pump_until(lambda: conn.status("api")["state"] != "checking", conn)
        self.assertEqual(conn.method, "api")
        self.assertEqual(self.settings["ai_method"], "api")
        self.assertEqual(dlg.use_btn.text(), "사용 중")
        self.assertFalse(dlg.use_btn.isEnabled())

    def test_subscription_terms_shown_only_first_time(self):
        from hazop.app import settings_dialog
        self.settings["ai_method"] = "api"
        conn = self.conn()
        dlg = self.dialog(conn)
        shown = []

        class Stub:
            def __init__(self, choice):
                self.choice = choice

            def exec(self):
                shown.append(self.choice)

        dlg._ask_api_switch = lambda: True
        dlg.select("subscription")
        dlg._terms_dialog = lambda: Stub(None)
        self.assertFalse(dlg.use_viewed())
        self.assertEqual(conn.method, "api", "취소하면 바꾸지 않음")
        dlg._terms_dialog = lambda: Stub("api")
        self.assertFalse(dlg.use_viewed())
        self.assertEqual(dlg.viewed, "api", "'API 키로 분석…'은 API 키 상세로")
        dlg.select("subscription")
        dlg._terms_dialog = lambda: Stub("ok")
        self.assertTrue(dlg.use_viewed())
        self.assertEqual(conn.method, "subscription")
        self.assertTrue(self.settings["subscription_terms_ack_at"])
        pump_until(lambda: conn.status("subscription")["state"] != "checking", conn)
        dlg._ask_api_switch = lambda: True
        dlg.select("api")
        dlg.use_viewed()
        pump_until(lambda: conn.status("api")["state"] != "checking", conn)
        dlg.select("subscription")
        dlg.use_viewed()
        self.assertEqual(len(shown), 3, "확인한 뒤로는 이용 조건 창을 띄우지 않음")
        self.assertEqual(settings_dialog.ask_terms(None, conn.prefs), "ok")

    def test_terms_dialog_continue_needs_checkbox(self):
        from hazop.app.settings_dialog import TermsDialog
        dlg = TermsDialog()
        self.addCleanup(dlg.deleteLater)
        self.assertEqual((dlg.width(), dlg.height()), (520, 380))
        self.assertFalse(dlg.ok_btn.isEnabled())
        dlg.ok_btn.click()
        self.assertIsNone(dlg.choice)
        dlg.agree.setChecked(True)
        self.assertTrue(dlg.ok_btn.isEnabled())
        dlg.ok_btn.click()
        self.assertEqual(dlg.choice, "ok")

    def test_running_locks_method_model_and_key_choice(self):
        self.store.add("회사", KEY, persist=False)
        conn = self.conn()
        dlg = self.dialog(conn)
        dlg.select("api")
        cancelled = []
        conn.cancel_handler = lambda: cancelled.append(1)
        conn.set_running(True, "AI 분석 실행 중 · 4/10 호출")
        self.assertTrue(dlg.lock_band.isVisibleTo(dlg))
        for w in (dlg.use_btn, dlg.model_combo, dlg.key_combo, dlg.delete_btn, dlg.sub_model):
            self.assertFalse(w.isEnabled(), w)
        for w in (dlg.rename_btn, dlg.add_btn, dlg.test_btn):
            self.assertTrue(w.isEnabled(), w)
        dlg.cancel_run_btn.click()
        self.assertEqual(cancelled, [1])
        conn.set_running(False)
        self.assertFalse(dlg.lock_band.isVisibleTo(dlg))
        self.assertTrue(dlg.model_combo.isEnabled())

    def test_key_added_during_run_keeps_the_run_key(self):
        """실행 중 '새 키 추가'는 되지만(§3.7) 진행 중 실행의 남은 호출은 시작할 때의 키로 나간다."""
        self.store.add("원래 키", KEY, persist=False)
        conn = self.conn("ok", opener=FakeOpener())
        client = conn.make_client("api")
        conn.set_running(True, "AI 분석 실행 중 · 1/9 호출")
        dlg = self.dialog(conn)
        dlg.select("api")
        dlg.add_toggle.setChecked(True)
        dlg.name_edit.setText("새 키")
        dlg.key_edit.setText("sk-ant-api03-SECONDKEYSECOND-conn-ui-zzzz")
        dlg.add_key()
        pump_until(lambda: conn.status("api")["state"] != "checking", conn)
        self.assertEqual(self.store.active()["name"], "새 키")
        self.assertEqual(client.key_provider(), KEY)

    def test_size_list_and_shortcuts(self):
        conn = self.conn(debug=True)
        dlg = self.dialog(conn)
        self.assertEqual((dlg.width(), dlg.height()), (760, 560))
        self.assertEqual((dlg.minimumWidth(), dlg.minimumHeight()), (720, 520))
        self.assertEqual(dlg.method_list.parentWidget().width(), 220)
        self.assertEqual(dlg.methods, ("subscription", "api", "fixed"), "디버그 실행에서만 고정 응답")
        self.assertEqual(self.dialog(self.conn()).methods, ("subscription", "api"))
        dlg.method_list.setCurrentRow(1)
        self.assertEqual(dlg.stack.currentWidget(), dlg.pages["api"])
        self.assertEqual(conn.method, "subscription")
        self.assertEqual(dlg.use_btn.text(), "이 방식으로 사용(&U)")

    def test_bundle_shows_api_only_without_subscription_words(self):
        with mock.patch.object(sys, "_MEIPASS", self.tmp, create=True):
            self.settings["ai_method"] = "subscription"
            conn = self.conn(debug=True)
            self.assertEqual(conn.methods(), ("api",))
            self.assertEqual(conn.method, "api")
            dlg = self.dialog(conn)
            self.assertEqual(dlg.width(), 600)
            self.assertFalse(hasattr(dlg, "method_list"))
            self.assertFalse(dlg.use_btn.isVisibleTo(dlg))
            text = self.texts(dlg)
            self.assertIn("이 배포본은 API 키로만 AI에 연결합니다.", text)
            self.assertNotIn("구독", text)
            chip = conn_view.chip_text(conn.method, conn.status(), conn.model())
            self.assertTrue(chip.startswith("API 키 · "), chip)


class MainWindowChipTest(ConnCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = tempfile.mkdtemp()
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.root, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.root, "store")

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.root, ignore_errors=True)

    def window(self, width=1920):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=os.path.join(self.tmp, "settings.json"), ask_reviewer=False)
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(width, 860)
        win.show()
        pump_until(lambda: True)
        return win

    def test_chip_is_focusable_button_with_full_accessible_name(self):
        from PySide6.QtWidgets import QToolButton
        win = self.window()
        chip = win.conn_chip
        self.assertIsInstance(chip, QToolButton)
        self.assertEqual(chip.focusPolicy() & 0x1, 0x1, "Tab으로 닿음")
        win.set_conn_status(sub_status("login_required"))
        self.assertEqual(chip.accessibleName(), "AI 연결: Claude 구독, 모델 Opus 5.5, 로그인 필요")
        self.assertEqual(chip.accessibleDescription(), conn_view.CHIP_HINT)
        self.assertIn("로그인이 필요합니다", win.msg_label.text(), "실행할 수 없게 되면 상태줄에도 알림")
        win.status_message("")
        win.set_conn_status(sub_status("login_required"))
        self.assertEqual(win.msg_label.text(), "", "같은 상태를 다시 받으면 다시 알리지 않음")
        win.set_run_override("api")
        self.assertTrue(chip.text().endswith("이번 실행만"))
        win.set_run_override(None)
        self.assertIn("로그인 필요", chip.text())

    def test_wide_form_when_it_fits_and_narrow_otherwise(self):
        win = self.window(1920)
        win.set_conn_status(sub_status("limit_reached", limit={"status": "limit_reached",
                                                                "resets_at": today_kst(17, 40)}))
        pump_until(lambda: True)
        wide = "구독 · Opus 5.5 · 한도 도달 · 17:40 재설정"
        if win.conn_chip.width_for(wide) > 340:
            self.skipTest("이 글꼴에서는 넓은 형식이 최대 폭(340px)을 넘음")
        self.assertEqual(win.conn_chip.text(), wide)
        win.resize(1366, 768)
        win.status_message("AI 분석 멈춤(한도 도달): 4/10 호출 · 2:41 걸림 · 저장: C:\\아주\\긴\\경로\\결과\\SNP-M-102.json")
        for lab, text in ((win.saved_label, "● 저장됨 14:20"), (win.drawing_label, "SNP-M-102"),
                          (win.count_label, "구간 5   미검토 12   실패 2"), (win.task_label, "진행 중: AI 분석 실행")):
            lab.setText(text)
            lab.show()
        win._fit_conn_chip()
        pump_until(lambda: True)
        self.assertEqual(win.conn_chip.text(), "구독 · Opus · 한도 · 17:40")
        self.assertIn("17시 40분 재설정", win.conn_chip.accessibleName(), "좁은 형식이어도 이름은 전체 문장")
        self.assertGreaterEqual(win.conn_chip.width(), win.conn_chip.width_for(win.conn_chip.text()), "칩은 줄이지 않음")

    def test_enter_opens_detail_and_escape_closes_it(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        win = self.window()
        QTest.keyClick(win.conn_chip, Qt.Key_Return)
        pop = win._conn_popup
        self.assertIsNotNone(pop)
        self.assertTrue(pop.isVisible(), "Enter로 상세 창")
        QTest.keyClick(pop, Qt.Key_Escape)
        self.assertFalse(pop.isVisible(), "Esc로 닫힘")
        QTest.keyClick(win.conn_chip, Qt.Key_Space)
        self.assertTrue(pop.isVisible(), "Space로도 열림")
        pop.close()

    def test_popup_buttons_and_menu_palette_entries(self):
        win = self.window()
        win.set_conn_status(sub_status("limit_reached", limit={"status": "limit_reached"}))
        pop = win.open_conn_popup()
        self.addCleanup(pop.close)
        self.assertEqual(pop.width(), 340)
        for name in ("check", "settings", "to_api"):
            self.assertIn(name, pop.btns)
        self.assertEqual(pop.btns["check"].text(), "다시 확인(&R)")
        self.assertEqual(pop.btns["settings"].text(), "연결 설정…(&S)")
        opened = []
        win.open_ai_settings = lambda method=None: opened.append(method)
        pop.btns["to_api"].click()
        self.assertEqual(opened, ["api"], "API 키 상세로 엶(요금 확인은 설정 창에서)")
        labels = [it.label for it in win.palette_items() if it.kind == "command"]
        self.assertIn("AI 연결 설정", labels)
        self.assertIn("AI 연결 다시 확인", labels)
        menu = [a.text() for a in win.menu_bar.actions()[0].menu().actions()]
        self.assertIn("AI 연결 설정…", menu)
        self.assertNotIn("API 키 설정…", menu)
        self.assertIn("Claude 구독(이 PC의 claude 프로그램)", win.about_text())


if __name__ == "__main__":
    unittest.main()
