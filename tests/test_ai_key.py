"""4단계 API 키 보관(hazop/study/apikey.py)·HTTP 클라이언트(hazop/study/claude_http.py)·API 키 설정 창 테스트.

네트워크 사용 없음: 모든 호출은 주입한 opener로 대신한다. 키 파일은 임시 폴더에 쓴다.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.study import apikey, claude_http  # noqa: E402
from hazop.study.apikey import KeyStore, mask  # noqa: E402
from hazop.study.claude_http import ClaudeHttpClient, cost_usd  # noqa: E402

KEY = "sk-ant-test-0123456789abcdefSECRET"
KEY2 = "sk-ant-test-second-key-zyxwvuTWO2"
REQUEST = {"system": "시스템", "context": "구간 맥락", "user": "편차 묶음", "schema": {"type": "object"}}
WIN = sys.platform == "win32"


class FakeOpener:
    def __init__(self, status=200, body=b"{}", exc=None):
        self.status, self.body, self.exc = status, body, exc
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.status, self.body


def message(text='{"deviations": []}', stop="end_turn", model="claude-opus-5-5"):
    return json.dumps({"model": model, "stop_reason": stop,
                       "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
                       "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 0,
                                 "cache_creation_input_tokens": 5}}).encode("utf-8")


def client(opener):
    return ClaudeHttpClient(lambda: KEY, opener=opener)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "api_keys.json")
        self.legacy = os.path.join(self.tmp, "api_key.dpapi")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def files_have_no_key(self, *keys):
        for name in os.listdir(self.tmp):
            path = os.path.join(self.tmp, name)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                raw = fh.read()
            for k in keys:
                self.assertNotIn(k.encode("utf-8"), raw, name)
                self.assertNotIn(k.encode("utf-16-le"), raw, name)


class KeyStoreTest(TempDirTest):
    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_dpapi_round_trip(self):
        data = KEY.encode("utf-8")
        enc = apikey.protect(data)
        self.assertNotEqual(enc, data)
        self.assertEqual(apikey.unprotect(enc), data)

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_several_keys_persist_switch_and_reload(self):
        store = KeyStore(self.path)
        a = store.add("회사 워크스페이스", KEY, persist=True)
        b = store.add("개인 시험용", KEY2, persist=True)
        self.assertEqual(store.get(), KEY2)
        store.select(a)
        self.assertEqual(store.get(), KEY)
        self.files_have_no_key(KEY, KEY2)
        again = KeyStore(self.path)
        self.assertEqual([e["name"] for e in again.entries()], ["회사 워크스페이스", "개인 시험용"])
        self.assertEqual(again.get(), KEY)
        again.select(b)
        self.assertEqual(KeyStore(self.path).get(), KEY2)

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_rename_and_remove(self):
        store = KeyStore(self.path)
        a = store.add("A", KEY, persist=True)
        b = store.add("B", KEY2, persist=True)
        store.rename(a, "  회사  ")
        with self.assertRaises(ValueError):
            store.rename(a, " ")
        store.remove(b)
        self.assertEqual(store.get(), KEY)
        again = KeyStore(self.path)
        self.assertEqual([e["name"] for e in again.entries()], ["회사"])
        again.clear()
        self.assertIsNone(again.get())
        self.assertEqual(KeyStore(self.path).entries(), [])
        self.files_have_no_key(KEY, KEY2)

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_session_only_key_stays_out_of_file(self):
        store = KeyStore(self.path)
        store.add("저장", KEY, persist=True)
        store.add("임시", KEY2, persist=False)
        self.assertFalse(store.is_persisted())
        store.select(store.entries()[0]["id"])
        self.files_have_no_key(KEY, KEY2)
        again = KeyStore(self.path)
        self.assertEqual([e["name"] for e in again.entries()], ["저장"])
        self.assertEqual(again.get(), KEY)

    def test_session_only_writes_nothing(self):
        store = KeyStore(self.path)
        store.set(KEY, persist=False)
        self.assertEqual(store.get(), KEY)
        self.assertEqual(os.listdir(self.tmp), [])

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_legacy_single_key_migrates(self):
        with open(self.legacy, "wb") as fh:
            fh.write(apikey.protect(KEY.encode("utf-8")))
        store = KeyStore(self.path)
        self.assertEqual(store.get(), KEY)
        self.assertEqual(store.active()["name"], apikey.LEGACY_NAME)
        self.assertTrue(store.is_persisted())
        self.assertFalse(os.path.exists(self.legacy))
        self.assertEqual(KeyStore(self.path).get(), KEY)
        self.files_have_no_key(KEY)

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_legacy_kept_when_migration_write_fails(self):
        with open(self.legacy, "wb") as fh:
            fh.write(apikey.protect(KEY.encode("utf-8")))
        os.mkdir(self.path)  # 새 파일 자리를 폴더로 막아 쓰기 실패
        store = KeyStore(self.path)
        self.assertEqual(store.get(), KEY)
        self.assertTrue(store.load_error)
        with open(self.legacy, "rb") as fh:
            self.assertEqual(apikey.unprotect(fh.read()).decode("utf-8"), KEY)

    def test_unreadable_legacy_is_left_alone(self):
        with open(self.legacy, "wb") as fh:
            fh.write(b"not dpapi")
        store = KeyStore(self.path)
        self.assertIsNone(store.get())
        self.assertTrue(store.load_error)
        with open(self.legacy, "rb") as fh:
            self.assertEqual(fh.read(), b"not dpapi")
        self.assertFalse(os.path.exists(self.path))

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_unreadable_key_survives_next_save(self):
        store = KeyStore(self.path)
        store.add("좋은 키", KEY, persist=True)
        with open(self.path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["keys"].append({"id": "broken", "name": "읽지 못함", "blob": "bm90LWRwYXBp", "last_test": None})
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        again = KeyStore(self.path)
        self.assertEqual(len(again.entries()), 1)
        self.assertTrue(again.load_error)
        again.set_model("claude-sonnet-5-5")
        with open(self.path, encoding="utf-8") as fh:
            self.assertIn("broken", [k["id"] for k in json.load(fh)["keys"]])

    def test_corrupt_store_reads_as_no_key(self):
        with open(self.path, "wb") as fh:
            fh.write(b"{not json")
        store = KeyStore(self.path)
        self.assertIsNone(store.get())
        self.assertTrue(store.load_error)

    def test_repr_entries_and_hint_hide_key(self):
        store = KeyStore(self.path)
        store.set(KEY, persist=False)
        self.assertNotIn(KEY, repr(store))
        text = json.dumps(store.entries(), ensure_ascii=False)
        self.assertNotIn(KEY, text)
        self.assertNotIn("0123456789abcdef", text)
        self.assertEqual(store.active()["hint"], "sk-ant-…CRET")

    def test_pasted_whitespace_cleaned(self):
        store = KeyStore(self.path)
        store.add("붙여넣기", "  sk-ant-AAA\nBBB \t", persist=False)
        self.assertEqual(store.get(), "sk-ant-AAABBB")

    def test_bad_key_rejected(self):
        for bad in ("  ", "sk-ant-키", "sk-ant-\x00x"):
            with self.assertRaises(ValueError) as cm:
                KeyStore(self.path).add("x", bad, persist=False)
            self.assertNotIn("sk-ant", str(cm.exception))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_model_choice(self):
        store = KeyStore(self.path)
        self.assertEqual(store.model, "claude-opus-5-5")
        with self.assertRaises(ValueError):
            store.set_model("gpt-x")
        if WIN:
            store.set_model("claude-haiku-5-5")
            self.assertEqual(KeyStore(self.path).model, "claude-haiku-5-5")

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_record_test_masks_key(self):
        store = KeyStore(self.path)
        kid = store.add("저장", KEY, persist=True)
        store.record_test(kid, False, "거부 %s" % KEY, "2026-11-07T05:00:00Z", "claude-opus-5-5")
        self.assertNotIn(KEY, store.active()["last_test"]["message"])
        self.assertFalse(KeyStore(self.path).active()["last_test"]["ok"])
        self.files_have_no_key(KEY)

    def test_mask(self):
        self.assertEqual(mask("a %s b %s" % (KEY, KEY), KEY), "a *** b ***")
        self.assertEqual(mask("plain", KEY), "plain")
        self.assertEqual(mask("plain", None), "plain")
        self.assertIsNone(mask(None, KEY))

    def test_default_path_next_to_settings(self):
        from hazop import paths
        self.assertEqual(os.path.dirname(apikey.default_store_path()), os.path.dirname(paths.settings_path()))
        self.assertEqual(os.path.basename(apikey.default_store_path()), "api_keys.json")


class ModelChoiceTest(unittest.TestCase):
    def test_models_have_prices_and_fallback_rule(self):
        for mid in claude_http.MODELS:
            self.assertIn(mid, claude_http.PRICES)
        self.assertEqual(claude_http.PRICES["claude-sonnet-5-5"]["input"], 2.00)
        self.assertEqual(claude_http.PRICES["claude-haiku-5-5"]["output"], 0.50)

    def test_haiku_request_has_no_fallback(self):
        op = FakeOpener(body=message(model="claude-haiku-5-5"))
        ClaudeHttpClient(lambda: KEY, model="claude-haiku-5-5", opener=op).analyze(REQUEST)
        body = json.loads(op.calls[0]["body"])
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertNotIn("fallbacks", body)
        self.assertNotIn("anthropic-beta", op.calls[0]["headers"])
        self.assertEqual(body["output_config"]["effort"], "high")

    def test_sonnet_request_keeps_fallback(self):
        op = FakeOpener(body=message(model="claude-sonnet-5-5"))
        ClaudeHttpClient(lambda: KEY, model="claude-sonnet-5-5", opener=op).analyze(REQUEST)
        self.assertEqual(json.loads(op.calls[0]["body"])["fallbacks"], "default")

    def test_connection_messages_name_next_step(self):
        def detail(text):
            return json.dumps({"error": {"type": "invalid_request_error", "message": text}}).encode()
        cases = ((400, detail("bad"), "워크스페이스"), (400, detail("Your credit balance is too low"), "Billing"),
                 (402, b"{}", "Billing"), (401, b"{}", "Console"), (404, b"{}", "다른 모델"))
        for code, body, word in cases:
            res = client(FakeOpener(status=code, body=body)).test_connection()
            self.assertFalse(res["ok"])
            self.assertIn(word, res["message"], code)


class RequestShapeTest(unittest.TestCase):
    def test_headers_and_body(self):
        op = FakeOpener(body=message())
        client(op).analyze(REQUEST)
        call = op.calls[0]
        self.assertEqual(call["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(call["timeout"], 600)
        h = call["headers"]
        self.assertEqual(h["x-api-key"], KEY)
        self.assertEqual(h["anthropic-version"], "2026-10-21")
        self.assertEqual(h["content-type"], "application/json")
        self.assertEqual(h["anthropic-beta"], "server-side-fallback-2026-07-01")
        body = json.loads(call["body"].decode("utf-8"))
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["max_tokens"], 16000)
        self.assertEqual(body["system"], "시스템")
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(body["output_config"], {"effort": "high",
                                                 "format": {"type": "json_schema", "schema": {"type": "object"}}})
        self.assertEqual(body["messages"], [{"role": "user", "content": [
            {"type": "text", "text": "구간 맥락", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "편차 묶음"}]}])
        for banned in ("thinking", "temperature", "top_p", "top_k", "tool_choice", "stream"):
            self.assertNotIn(banned, body)
        self.assertNotIn(KEY, call["body"].decode("utf-8"))

    def test_describe_has_no_key(self):
        d = client(FakeOpener()).describe()
        self.assertEqual(d, {"type": "anthropic_http", "model": "claude-opus-5-5", "effort": "high",
                             "max_tokens": 16000})
        self.assertNotIn(KEY, repr(client(FakeOpener())))


class StatusMappingTest(unittest.TestCase):
    FIELDS = {"status", "output", "usage", "model", "error_type", "status_code", "error"}

    def run_case(self, **kw):
        res = client(FakeOpener(**kw)).analyze(REQUEST)
        self.assertEqual(set(res), self.FIELDS)
        self.assertNotIn(KEY, json.dumps(res, ensure_ascii=False))
        return res

    def test_completed(self):
        res = self.run_case(body=message())
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["output"], {"deviations": []})
        self.assertEqual(res["usage"]["output_tokens"], 20)
        self.assertEqual(res["status_code"], 200)
        self.assertIsNone(res["error"])

    def test_fallback_model_reported(self):
        self.assertEqual(self.run_case(body=message(model="claude-opus-4-8"))["model"], "claude-opus-4-8")

    def test_refusal(self):
        res = self.run_case(body=message(stop="refusal"))
        self.assertEqual(res["status"], "refused")
        self.assertIsNone(res["output"])

    def test_max_tokens(self):
        self.assertEqual(self.run_case(body=message(stop="max_tokens"))["status"], "truncated")

    def test_model_text_not_json(self):
        res = self.run_case(body=message(text="이건 JSON이 아님"))
        self.assertEqual(res["status"], "parse_error")
        self.assertTrue(res["error"])

    def test_no_text_block(self):
        body = json.dumps({"stop_reason": "end_turn", "content": []}).encode()
        self.assertEqual(self.run_case(body=body)["status"], "parse_error")

    def test_http_body_not_json(self):
        res = self.run_case(body=b"<html>gateway</html>")
        self.assertEqual((res["status"], res["error_type"]), ("api_error", "bad_response"))

    def test_http_errors(self):
        cases = {401: "auth", 403: "permission", 429: "rate_limit", 500: "api_status", 503: "api_status",
                 529: "overloaded", 400: "api_status"}
        for code, et in cases.items():
            body = json.dumps({"type": "error", "error": {"type": "x", "message": "bad key %s" % KEY}}).encode()
            res = self.run_case(status=code, body=body)
            self.assertEqual((res["status"], res["error_type"], res["status_code"]), ("api_error", et, code), code)
            self.assertTrue(res["error"])
        self.assertIn("HTTP 500", self.run_case(status=500, body=b"")["error"])

    def test_timeout_and_connection(self):
        self.assertEqual(self.run_case(exc=TimeoutError("timed out"))["error_type"], "timeout")
        self.assertEqual(self.run_case(exc=urllib.error.URLError(TimeoutError()))["error_type"], "timeout")
        res = self.run_case(exc=urllib.error.URLError("getaddrinfo failed %s" % KEY))
        self.assertEqual((res["status"], res["error_type"], res["status_code"]), ("api_error", "connection", None))
        self.assertEqual(self.run_case(exc=ConnectionResetError())["error_type"], "connection")

    def test_invalid_header_error_does_not_leak_key(self):
        res = self.run_case(exc=ValueError("Invalid header value b'%s\\nX'" % KEY))
        self.assertEqual((res["status"], res["error_type"]), ("api_error", "bad_key"))
        op = FakeOpener(exc=ValueError("Invalid header value b'%s'" % KEY))
        msg = client(op).test_connection()
        self.assertFalse(msg["ok"])
        self.assertNotIn(KEY, msg["message"])

    def test_key_echoed_in_output_is_masked(self):
        res = self.run_case(body=message(text=json.dumps({"note": "key %s" % KEY})))
        self.assertEqual(res["output"], {"note": "key ***"})

    def test_no_key(self):
        op = FakeOpener()
        res = ClaudeHttpClient(lambda: None, opener=op).analyze(REQUEST)
        self.assertEqual(res["status"], "no_key")
        self.assertTrue(res["error"])
        self.assertEqual(op.calls, [])


class CostTest(unittest.TestCase):
    def test_cost_usd(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
                 "cache_creation_input_tokens": 1_000_000}
        self.assertAlmostEqual(cost_usd(usage, "claude-opus-5-5"), 4.00 + 20.00 + 0.20 + 5.00)
        self.assertAlmostEqual(cost_usd({"input_tokens": 500_000, "output_tokens": None}, "claude-opus-5-5"), 2.00)
        self.assertEqual(cost_usd(None, "claude-opus-5-5"), 0.0)
        self.assertAlmostEqual(cost_usd({"output_tokens": 1_000_000}, "claude-opus-4-8"), 25.00)
        self.assertAlmostEqual(cost_usd({"output_tokens": 1_000_000}, "unknown-model"), 20.00)


class TestConnectionTest(unittest.TestCase):
    def test_request(self):
        op = FakeOpener()
        res = client(op).test_connection()
        self.assertTrue(res["ok"])
        call = op.calls[0]
        self.assertEqual(call["url"], "https://api.anthropic.com/v1/models/claude-opus-5-5")
        self.assertIsNone(call["body"])
        self.assertEqual(call["headers"]["x-api-key"], KEY)
        self.assertLessEqual(call["timeout"], claude_http.TEST_TIMEOUT)

    def test_mapping(self):
        for kw, word in (({"status": 401}, "401"), ({"status": 403}, "권한"), ({"status": 404}, "404"),
                         ({"status": 429}, "한도"), ({"exc": urllib.error.URLError("dns")}, "네트워크"),
                         ({"exc": TimeoutError()}, "시간")):
            res = client(FakeOpener(**kw)).test_connection()
            self.assertFalse(res["ok"], kw)
            self.assertIn(word, res["message"], kw)
            self.assertNotIn(KEY, res["message"])

    def test_no_key(self):
        op = FakeOpener()
        self.assertFalse(ClaudeHttpClient(lambda: "", opener=op).test_connection()["ok"])
        self.assertEqual(op.calls, [])


class SettingsDialogTest(TempDirTest):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, opener=None):
        from hazop.app.settings_dialog import SettingsDialog
        self.store = KeyStore(self.path)
        return SettingsDialog(self.store, opener=opener or FakeOpener())

    def wait(self, dlg):
        from PySide6.QtCore import QCoreApplication
        dlg.tasks.wait(10000)
        end = time.monotonic() + 5
        while not dlg.test_btn.isEnabled() and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        QCoreApplication.processEvents()

    def screen_text(self, dlg):
        from PySide6.QtWidgets import QComboBox, QLabel
        parts = [w.text() for w in dlg.findChildren(QLabel)]
        for combo in dlg.findChildren(QComboBox):
            parts += [combo.itemText(i) for i in range(combo.count())]
        return "\n".join(parts)

    def test_add_session_key_tests_and_shows_connected(self):
        from PySide6.QtWidgets import QLineEdit
        from hazop.app.settings_dialog import connection_state, status_bar_html
        op = FakeOpener()
        dlg = self.dialog(op)
        self.assertIn("키 없음", dlg.state_chip.text())
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.Password)
        dlg.show_btn.setChecked(True)
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.Normal)
        dlg.name_edit.setText("개인 시험용")
        dlg.key_edit.setText(" " + KEY + "\n")
        dlg.persist_box.setChecked(False)
        dlg.add_key()
        self.wait(dlg)
        self.assertEqual(self.store.get(), KEY)
        self.assertEqual(os.listdir(self.tmp), [])
        self.assertEqual(dlg.key_edit.text(), "")
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.Password)
        self.assertEqual(op.calls[0]["url"], "https://api.anthropic.com/v1/models/claude-opus-5-5")
        self.assertIn("연결됨", dlg.state_chip.text())
        text = self.screen_text(dlg)
        for word in ("api.anthropic.com", "claude-opus-5-5", claude_http.API_VERSION, "개인 시험용", "sk-ant-…CRET",
                     "이번 실행만"):
            self.assertIn(word, text)
        self.assertNotIn(KEY, text)
        self.assertEqual(connection_state(self.store)[0], "ok")
        self.assertIn("AI 연결됨 · 개인 시험용", status_bar_html(self.store))

    def test_error_message_guides_next_step_and_hides_key(self):
        body = json.dumps({"error": {"type": "invalid_request_error",
                                     "message": "Your credit balance is too low %s" % KEY}}).encode()
        dlg = self.dialog(FakeOpener(status=400, body=body))
        dlg.key_edit.setText(KEY)
        dlg.persist_box.setChecked(False)
        dlg.add_key()
        self.wait(dlg)
        self.assertIn("연결 안 됨", dlg.state_chip.text())
        self.assertIn("Billing", dlg.detail_label.text())
        self.assertNotIn(KEY, self.screen_text(dlg))

    def test_model_change_resets_state_and_uses_model(self):
        op = FakeOpener()
        dlg = self.dialog(op)
        dlg.key_edit.setText(KEY)
        dlg.persist_box.setChecked(False)
        dlg.add_key()
        self.wait(dlg)
        self.store._model = "claude-sonnet-5-5"  # 파일 쓰기 없이 모델만 바꿈(메모리 키)
        dlg.refresh()
        self.assertIn("확인 안 함", dlg.state_chip.text())
        self.assertIn("$2.00", dlg.price_label.text())
        dlg.test_connection()
        self.wait(dlg)
        self.assertTrue(op.calls[-1]["url"].endswith("/claude-sonnet-5-5"))
        self.assertIn("연결됨", dlg.state_chip.text())

    def test_switch_rename_and_delete_with_confirmation(self):
        dlg = self.dialog()
        a = self.store.add("회사", KEY, persist=False)
        self.store.add("개인", KEY2, persist=False)
        dlg.refresh()
        self.assertEqual(dlg.key_combo.count(), 2)
        dlg._select_key(0)
        self.assertEqual(self.store.get(), KEY)
        dlg._ask_delete = lambda e: False
        dlg.delete_key()
        self.assertEqual(len(self.store.entries()), 2)
        dlg._ask_delete = lambda e: True
        dlg.delete_key()
        self.assertNotIn(a, [e["id"] for e in self.store.entries()])
        self.assertEqual(self.store.get(), KEY2)
        dlg._ask_name = lambda cur: "새 이름"
        dlg.rename_key()
        self.assertEqual(self.store.active()["name"], "새 이름")

    def test_close_warns_about_unadded_key(self):
        dlg = self.dialog()
        asked = []
        dlg._ask_discard = lambda: asked.append(1) or False
        dlg.key_edit.setText(KEY)
        dlg.show()
        dlg.reject()
        self.assertEqual(asked, [1])
        self.assertTrue(dlg.isVisible())
        dlg._ask_discard = lambda: True
        dlg.reject()
        self.assertFalse(dlg.isVisible())
        self.assertEqual(dlg.key_edit.text(), "")

    def test_connection_runs_off_ui_thread(self):
        op = FakeOpener(status=401)
        dlg = self.dialog(op)
        self.store.add("x", KEY, persist=False)
        dlg.refresh()
        dlg.test_connection()
        self.assertFalse(dlg.test_btn.isEnabled())
        self.wait(dlg)
        self.assertTrue(dlg.test_btn.isEnabled())
        self.assertIn("401", dlg.detail_label.text())
        self.assertNotIn(KEY, self.screen_text(dlg))
        self.assertEqual(op.calls[0]["headers"]["x-api-key"], KEY)


if __name__ == "__main__":
    unittest.main()
