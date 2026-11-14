"""새 웹 화면의 AI 연결·모델 설정(hazop/shell/api_settings.py). 실행: python -m unittest tests.test_shell_settings

실제 연결 상태 보관(hazop.app.ai_conn.AiConnection)과 키 보관(hazop.study.apikey.KeyStore)을 임시 폴더에서 쓴다. 구독은 가짜 CLI 객체,
API 연결 시험은 가짜 전송 함수(tests.test_ai_connection_ui.FakeOpener)라 네트워크를 쓰지 않는다. 키는 가짜 값이다.
본다: 경로 전환(구독 ↔ API, 요금 확인·이용 조건), 키가 웹·로그·설정 파일·사건에 안 나감, 구독 없는 PC 안내, 모델 선택이 실행 클라이언트에 반영,
분석 중 바꾸기 막음, 키 지우기 확인.
"""

import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop.shell import api, api_settings as S  # noqa: E402
from hazop.study import claude_http  # noqa: E402
from hazop.study.ai_settings import AiPrefs  # noqa: E402
from hazop.study.apikey import KeyStore  # noqa: E402
from tests.test_ai_connection_ui import FakeOpener, pump_until, qapp  # noqa: E402

FAKE_KEY = "sk-ant-api03-FAKEFAKEFAKE-zz9Q"       # 가짜 키(형식만 맞춤)


class FakeCli:
    made = []

    def __init__(self, state, model=None, **kw):
        self.state, self.model = state, model
        FakeCli.made.append(self)

    def check(self):
        return {"via": "subscription", "state": self.state, "detail": "", "plan": "max_20x" if self.state == "ok" else None}


class Adapter:
    """window.py AiAdapter 자리(시험용): 상태는 api_settings.adapter_status로 낸다(s-frame에 요청한 모양)."""

    def __init__(self, conn):
        self.conn = conn

    def status(self):
        return S.adapter_status(self.conn)

    def make_client(self):
        return self.conn.make_client()


class Base(unittest.TestCase):
    cli_state = "ok"

    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def setUp(self):
        from hazop.app.ai_conn import AiConnection
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellset-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(api.COMMANDS)
        p.start()
        self.addCleanup(p.stop)
        if "aiconn.use" not in api.COMMANDS:
            S.register(api.COMMANDS)
        self.events = []
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events.append)
        self.saved = []
        prefs = AiPrefs(self.engine.settings, lambda s: self.saved.append(json.dumps(s, ensure_ascii=False)))
        self.store = KeyStore(os.path.join(self.tmp, "api_keys.json"))
        self.opener = FakeOpener()
        FakeCli.made = []
        # 새 화면과 같게 auto_api=False(window.py가 이렇게 만든다): 사용자가 고르지 않은 과금 경로로 넘어가지 않는다
        self.conn = AiConnection(prefs, self.store, cli_factory=lambda path, **kw: FakeCli(self.cli_state, **kw), opener=self.opener,
                                 auto_api=False)
        self.addCleanup(self.conn.tasks.wait, 20000)
        self.engine.ai = Adapter(self.conn)
        self.engine.hooks["ask_api_key"] = lambda name: ("업무 키", FAKE_KEY, False)
        self.check("subscription")

    def check(self, method):
        self.conn.check(method)
        pump_until(lambda: self.conn.status(method)["state"] != "checking", self.conn)

    def view(self):
        return json.loads(S.read(self.engine, ["aisettings"], {}).body.decode("utf-8"))

    def call(self, cmd, **args):
        return self.engine.dispatch(cmd, args, via_web=True)      # 웹이 보내는 실제 길(프로젝트 ID 없이: 연결 설정은 프로젝트에 묶이지 않는다)

    def add_key(self):
        out = self.call("aiconn.add_key")
        self.assertTrue(out["ok"], out)
        pump_until(lambda: self.conn.status("api")["state"] not in ("checking", "unchecked"), self.conn)
        return out


class SwitchTest(Base):
    def test_subscription_is_the_default_and_always_shown(self):
        v = self.view()
        self.assertEqual((v["current"]["via"], v["current"]["model"]), ("subscription", "claude-opus-5-5"))
        self.assertTrue(v["current"]["can_start"])
        self.assertTrue(v["current"]["chip"].startswith("구독 · Opus"))
        self.assertEqual(v["chat"]["model"], "fast")
        self.assertEqual([m["method"] for m in v["methods"]][:2], ["subscription", "api"])

    def test_switch_to_api_asks_about_cost_first(self):
        out = self.call("aiconn.use", method="api")
        self.assertTrue(out["data"]["need_confirm"])
        self.assertIn("$0.86", out["data"]["text"])
        self.assertEqual(self.conn.method, "subscription")                     # 확인 전에는 바뀌지 않음
        out = self.call("aiconn.use", method="api", confirmed=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.conn.method, "api")
        cur = self.view()["current"]
        self.assertEqual((cur["via"], cur["state"], cur["can_start"]), ("api", "no_key", False))   # 키가 없으면 실행 못 함
        self.assertTrue(self.add_key()["data"]["added"])
        cur = self.view()["current"]
        self.assertEqual((cur["via"], cur["state"], cur["can_start"]), ("api", "ok", True))
        self.assertIn("/v1/models/", self.opener.calls[0])                    # 연결 시험은 모델 조회 GET뿐(요금 없음)

    def test_back_to_subscription_needs_terms_once(self):
        self.call("aiconn.use", method="api", confirmed=True)
        out = self.call("aiconn.use", method="subscription")
        self.assertTrue(out["data"].get("need_terms"), out)
        self.assertEqual(self.conn.method, "api")
        self.call("aiconn.ack_terms")
        out = self.call("aiconn.use", method="subscription")
        self.assertTrue(out["data"]["changed"])
        self.assertEqual(self.conn.method, "subscription")

    def test_changes_are_locked_while_analysis_runs(self):
        self.engine._analysis = mock.Mock(running=True)
        self.assertEqual(self.call("aiconn.use", method="api", confirmed=True)["error"]["code"], "busy")
        self.assertEqual(self.call("aiconn.set_model", method="subscription", model="claude-haiku-5-5")["error"]["code"], "busy")
        self.assertEqual(self.conn.model("subscription"), "claude-opus-5-5")


class ModelTest(Base):
    def test_model_choice_reaches_the_run_client(self):
        self.assertTrue(self.call("aiconn.set_model", method="subscription", model="claude-sonnet-5-5")["ok"])
        self.engine.ai.make_client()
        self.assertEqual(FakeCli.made[-1].model, "claude-sonnet-5-5")          # 분석 실행이 쓰는 구독 클라이언트
        self.add_key()
        self.call("aiconn.use", method="api", confirmed=True)
        self.assertTrue(self.call("aiconn.set_model", method="api", model="claude-haiku-5-5")["ok"])
        client = self.engine.ai.make_client()
        self.assertIsInstance(client, claude_http.ClaudeHttpClient)
        self.assertEqual(client.model, "claude-haiku-5-5")
        self.assertEqual(self.view()["current"]["model"], "claude-haiku-5-5")

    def test_unknown_model_refused_and_chat_function(self):
        self.assertEqual(self.call("aiconn.set_model", method="subscription", model="gpt")["error"]["code"], "bad_args")
        out = S.set_model(self.engine, "subscription", "claude-haiku-5-5")
        self.assertTrue(out["ok"])
        self.assertEqual(S.connection(self.engine)["model"], "claude-haiku-5-5")
        self.assertFalse(S.set_model(self.engine, "fixed", "claude-haiku-5-5")["ok"])


class KeyTest(Base):
    def test_key_never_leaves_python(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("hazop").debug("시험 표지")
            self.add_key()
            self.call("aiconn.use", method="api", confirmed=True)
            self.check("api")
            v = self.view()
        body = json.dumps([v, self.events, S.connection(self.engine)], ensure_ascii=False)
        tail = FAKE_KEY[-4:]
        self.assertNotIn(FAKE_KEY, body)
        self.assertNotIn(FAKE_KEY[:20], body)
        self.assertEqual(v["api"]["keys"][0]["hint"], "…" + tail)              # 끝 네 자리만
        self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
        self.assertNotIn(FAKE_KEY, "\n".join(self.saved))                       # 설정 파일(ai_method 등)에 키 없음
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "api_keys.json")))   # '이 PC에 저장' 안 함 → 파일도 없음

    def test_web_cannot_send_a_key(self):
        out = self.call("aiconn.add_key", key=FAKE_KEY)
        self.assertEqual(out["error"]["code"], "bad_args")                      # 명령 표에 키 칸이 없다
        self.assertNotIn(FAKE_KEY, json.dumps(out, ensure_ascii=False))
        self.assertEqual(self.store.entries(), [])

    def test_saved_key_is_encrypted_on_disk(self):
        self.engine.hooks["ask_api_key"] = lambda name: ("저장 키", FAKE_KEY, True)
        self.add_key()
        with open(os.path.join(self.tmp, "api_keys.json"), encoding="utf-8") as fh:
            self.assertNotIn(FAKE_KEY, fh.read())

    def test_bad_key_and_write_error_are_masked(self):
        self.engine.hooks["ask_api_key"] = lambda name: ("나쁜 키", "sk-ant 띄어쓴 키", False)
        out = self.call("aiconn.add_key")
        self.assertEqual(out["error"]["code"], "bad_args")
        self.engine.hooks["ask_api_key"] = lambda name: ("저장 키", FAKE_KEY, True)
        with mock.patch.object(KeyStore, "_write", side_effect=OSError("쓰기 실패 %s" % FAKE_KEY)):
            out = self.call("aiconn.add_key")
        self.assertEqual(out["error"]["code"], "failed")
        self.assertNotIn(FAKE_KEY, out["error"]["message"])
        self.assertIn("***", out["error"]["message"])

    def test_cancel_adds_nothing(self):
        self.engine.hooks["ask_api_key"] = lambda name: None
        self.assertFalse(self.call("aiconn.add_key")["data"]["added"])
        self.assertEqual(self.store.entries(), [])

    def test_remove_needs_confirmation(self):
        self.add_key()
        kid = self.view()["api"]["keys"][0]["id"]
        self.assertEqual(self.call("aiconn.remove_key", key_id=kid, confirmed=False)["error"]["code"], "bad_args")
        self.assertEqual(len(self.store.entries()), 1)
        self.assertTrue(self.call("aiconn.remove_key", key_id=kid, confirmed=True)["ok"])
        self.assertEqual(self.store.entries(), [])
        self.assertEqual(self.call("aiconn.select_key", key_id=kid)["error"]["code"], "not_found")

    def test_rename_and_select(self):
        self.add_key()
        self.engine.hooks["ask_api_key"] = lambda name: ("둘째 키", FAKE_KEY[:-4] + "AAAA", False)
        self.add_key()
        keys = self.view()["api"]["keys"]
        self.assertEqual([k["active"] for k in keys], [False, True])
        self.assertTrue(self.call("aiconn.select_key", key_id=keys[0]["id"])["ok"])
        self.assertTrue(self.call("aiconn.rename_key", key_id=keys[0]["id"], name="본 키")["ok"])
        keys = self.view()["api"]["keys"]
        self.assertEqual((keys[0]["name"], keys[0]["active"]), ("본 키", True))


class NoSubscriptionTest(Base):
    cli_state = "not_installed"

    def test_guide_only_and_scripts_still_work(self):
        v = self.view()
        cur = v["current"]
        self.assertEqual((cur["via"], cur["state"], cur["can_start"]), ("subscription", "not_installed", False))
        self.assertTrue(cur["guide"])
        self.assertEqual(v["subscription"]["state"], "not_installed")
        self.assertTrue(S.connection(self.engine)["ok"])

    def test_no_ai_at_all(self):
        self.engine.ai = None
        v = self.view()
        self.assertFalse(v["available"])
        self.assertEqual(v["current"]["label"], "연결 안 됨")
        self.assertIn("스크립트", v["current"]["guide"])
        self.assertEqual(self.call("aiconn.use", method="api", confirmed=True)["error"]["code"], "failed")


class NoPaidFallbackTest(Base):
    """A8 검토 R1(차단): 사용자가 고른 적이 없으면 구독을 못 써도 API(과금)로 넘어가지 않는다."""
    cli_state = "login_required"

    def test_start_with_key_stays_on_subscription_and_says_so(self):
        self.store.add("k", FAKE_KEY, persist=False)
        notes = []
        self.conn.notice.connect(notes.append)
        self.conn.prefs.remember_auto("api")                  # 이전 화면이 기억해 둔 앱 기본값(api)도 따르지 않는다
        self.conn.start()
        pump_until(lambda: self.conn.status("subscription")["state"] != "checking", self.conn)
        pump_until(lambda: bool(notes), self.conn, secs=2)
        self.assertEqual((self.conn.method, self.conn.is_chosen()), ("subscription", False))
        cur = self.view()["current"]
        self.assertEqual((cur["via"], cur["can_start"]), ("subscription", False))
        self.assertNotIsInstance(self.engine.ai.make_client(), claude_http.ClaudeHttpClient)
        self.assertEqual(notes, [S.NOTICE_NO_SUBSCRIPTION])
        self.assertEqual(self.view()["advice"], S.NOTICE_NO_SUBSCRIPTION)
        plan = S.run_conn(self.engine, "analysis", calls=3, sections=2)
        self.assertEqual((plan["via"], plan["paid"], plan["can_start"]), ("subscription", False, False))

    def test_api_only_when_chosen_and_run_shows_cost(self):
        self.store.add("k", FAKE_KEY, persist=False)
        self.assertTrue(self.call("aiconn.use", method="api", confirmed=True)["ok"])
        self.check("api")
        plan = S.run_conn(self.engine, "analysis", calls=4, sections=2)
        self.assertEqual((plan["via"], plan["paid"], plan["usd"]), ("api", True, 1.72))     # 구간 2개 × $0.86
        self.assertIn("$1.72", plan["cost_text"])
        self.assertNotIn(FAKE_KEY[-12:], json.dumps(plan, ensure_ascii=False))
        rv = S.run_conn(self.engine, "ai_review", calls=10)
        self.assertEqual((rv["via"], rv["paid"]), ("subscription", False))      # AI 검토는 구독으로만 돈다

    def test_run_refused_when_connection_changed_after_view(self):
        self.store.add("k", FAKE_KEY, persist=False)
        seen = S.run_conn(self.engine, "analysis", sections=1)["conn_ver"]
        self.call("aiconn.use", method="api", confirmed=True)
        with self.assertRaises(S.Refused) as cm:
            S.same_conn(self.engine, "analysis", seen)
        self.assertEqual(cm.exception.code, "conn_changed")
        now = S.run_conn(self.engine, "analysis")["conn_ver"]
        self.assertEqual(S.same_conn(self.engine, "analysis", now)["via"], "api")
        self.call("aiconn.set_model", method="api", model="claude-haiku-5-5")
        with self.assertRaises(S.Refused):
            S.same_conn(self.engine, "analysis", now)                          # 모델이 바뀌어도 다시 묻는다


class ReviewFixTest(Base):
    def test_r4_bad_settings_shapes_read_as_default_and_fixable(self):
        for bad in ("claude-opus-5-5", ["x"], {"subscription": "--x"}):
            self.engine.settings["ai_models"] = bad
            v = self.view()
            self.assertEqual(v["current"]["model"], claude_http.DEFAULT_MODEL)
            self.assertIn("기본 모델", v["settings_warning"])
            self.assertTrue(self.call("aiconn.set_model", method="subscription", model="claude-haiku-5-5")["ok"])
            self.assertEqual(self.engine.settings["ai_models"], {"subscription": "claude-haiku-5-5"})
            self.assertNotIn("settings_warning", self.view())
        self.engine.settings["ai_method"] = 3
        self.assertEqual(self.view()["current"]["via"], "subscription")

    def test_r6_switch_during_ai_review_job_says_next_run(self):
        import threading
        self.store.add("k", FAKE_KEY, persist=False)
        ev = threading.Event()
        self.addCleanup(ev.set)
        self.engine.start_job("AI 검토", lambda progress: ev.wait(5), kind="ai_review")
        out = self.call("aiconn.use", method="api", confirmed=True)
        self.assertTrue(out["ok"], out)
        self.assertIn("다음 실행부터", out["data"]["note"])
        self.assertIn("AI 검토", self.view()["busy_note"])
        ev.set()

    def test_r7_guide_follows_the_state(self):
        from hazop.app import conn_view
        guides = {}
        for state in ("not_installed", "limit_reached", "network", "not_subscription", "login_required"):
            self.conn.set_status({"via": "subscription", "state": state})
            s = self.view()["subscription"]
            self.assertFalse(s["can_start"])
            guides[state] = s["guide"]
        self.assertEqual(len(set(guides.values())), len(guides), guides)      # 상태마다 다른 안내(설치 안내 하나로 덮지 않음)
        self.assertNotIn("설치", guides["limit_reached"])
        self.assertEqual(guides["network"], conn_view.look("subscription", "network").guide.replace("{detail}", "").replace("{pct}", "")
                         .replace("{reset}", "").replace("{count}", ""))

    def test_key_load_error_reason_is_shown(self):
        with open(os.path.join(self.tmp, "api_keys.json"), "w", encoding="utf-8") as fh:
            fh.write("{깨진 파일")
        self.conn.keys = KeyStore(os.path.join(self.tmp, "api_keys.json"))
        a = self.view()["api"]
        self.assertTrue(a["load_error"])
        self.assertIn("읽지 못함", a["load_error_text"])

    def test_aiconn_not_bound_to_project_on_web_path(self):
        self.assertFalse(any(p.startswith(("aiconn", "aisettings")) for p in api.PROJECT_BOUND))
        self.assertTrue(self.engine.dispatch("aiconn.check", {"method": "subscription"}, via_web=True)["ok"])
        self.assertTrue(self.engine.dispatch("aiconn.check", {"method": "subscription"}, project="other", via_web=True)["ok"])

    def test_chat_connection_is_the_chat_path_not_analysis(self):
        self.store.add("k", FAKE_KEY, persist=False)
        self.call("aiconn.use", method="api", confirmed=True)
        self.engine.settings["chat_model"] = "deep"
        c = S.chat_connection(self.engine)
        self.assertEqual((c["via"], c["model_name"], c["can_start"]), ("subscription", "깊게", True))
        self.assertTrue(c["chip"].startswith("구독 · 깊게"))
        self.assertNotIn(FAKE_KEY[-12:], json.dumps(c, ensure_ascii=False))


class KeyDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def dialog(self):
        from hazop.shell.key_dialog import KeyDialog
        from PySide6.QtWidgets import QLineEdit
        dlg = KeyDialog("이름")
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.Password)            # 가려 보임
        return dlg

    def test_bad_key_stays_open_with_reason(self):
        dlg = self.dialog()
        dlg.key_edit.setText("")
        dlg.accept()
        self.assertIsNone(dlg.result_value)
        self.assertIn("붙여 넣", dlg.msg.text())

    def test_good_key_is_cleaned_and_field_cleared(self):
        dlg = self.dialog()
        dlg.key_edit.setText("  %s	" % FAKE_KEY)
        dlg.accept()
        self.assertEqual(dlg.result_value, ("이름", FAKE_KEY, True))
        self.assertEqual(dlg.key_edit.text(), "")
        self.assertNotIn(FAKE_KEY, dlg.msg.text())

    def test_closing_with_typed_key_asks(self):
        dlg = self.dialog()
        dlg.key_edit.setText(FAKE_KEY)
        dlg.ask_discard = lambda: False
        dlg.reject()
        self.assertEqual(dlg.key_edit.text(), FAKE_KEY)                          # 버리지 않음 → 열린 채
        dlg.ask_discard = lambda: True
        dlg.reject()
        self.assertEqual(dlg.key_edit.text(), "")


if __name__ == "__main__":
    unittest.main()
