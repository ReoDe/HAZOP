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
        self.path = os.path.join(self.tmp, "api_key.dpapi")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class KeyStoreTest(TempDirTest):
    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_dpapi_round_trip(self):
        data = KEY.encode("utf-8")
        enc = apikey.protect(data)
        self.assertNotEqual(enc, data)
        self.assertEqual(apikey.unprotect(enc), data)

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_persisted_file_has_no_plaintext_and_reloads(self):
        KeyStore(self.path).set(KEY, persist=True)
        with open(self.path, "rb") as fh:
            raw = fh.read()
        self.assertNotIn(KEY.encode("utf-8"), raw)
        self.assertNotIn(KEY.encode("utf-16-le"), raw)
        again = KeyStore(self.path)
        self.assertTrue(again.is_persisted())
        self.assertEqual(again.get(), KEY)

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_clear_deletes_file(self):
        store = KeyStore(self.path)
        store.set(KEY, persist=True)
        store.clear()
        self.assertFalse(os.path.exists(self.path))
        self.assertIsNone(store.get())
        self.assertIsNone(KeyStore(self.path).get())

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_session_only_set_removes_old_persisted_key(self):
        store = KeyStore(self.path)
        store.set("old-key-value", persist=True)
        store.set(KEY, persist=False)
        self.assertFalse(store.is_persisted())
        self.assertEqual(store.get(), KEY)
        self.assertIsNone(KeyStore(self.path).get())

    def test_session_only_writes_nothing(self):
        store = KeyStore(self.path)
        store.set(KEY, persist=False)
        self.assertEqual(store.get(), KEY)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_corrupt_file_reads_as_no_key(self):
        with open(self.path, "wb") as fh:
            fh.write(b"not dpapi")
        store = KeyStore(self.path)
        self.assertIsNone(store.get())
        self.assertTrue(store.load_error)

    def test_repr_masks_key(self):
        store = KeyStore(self.path)
        store.set(KEY, persist=False)
        self.assertNotIn(KEY, repr(store))
        self.assertNotIn(KEY, str(store))

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            KeyStore(self.path).set("  ", persist=False)

    def test_key_with_inner_newline_or_space_rejected(self):
        for bad in ("sk-ant-AAA\nBBB", "sk-ant-AAA BBB", "sk-ant-AAA\tBBB", "sk-ant-키"):
            with self.assertRaises(ValueError) as cm:
                KeyStore(self.path).set(bad, persist=False)
            self.assertNotIn("AAA", str(cm.exception))
        self.assertFalse(os.path.exists(self.path))

    def test_mask(self):
        self.assertEqual(mask("a %s b %s" % (KEY, KEY), KEY), "a *** b ***")
        self.assertEqual(mask("plain", KEY), "plain")
        self.assertEqual(mask("plain", None), "plain")
        self.assertIsNone(mask(None, KEY))

    def test_default_path_next_to_settings(self):
        from hazop import paths
        self.assertEqual(os.path.dirname(apikey.default_key_path()), os.path.dirname(paths.settings_path()))
        self.assertEqual(os.path.basename(apikey.default_key_path()), "api_key.dpapi")


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
        return SettingsDialog(self.store, opener=opener)

    def test_session_only_save(self):
        from PySide6.QtWidgets import QLineEdit
        dlg = self.dialog()
        self.assertEqual(dlg.status_label.text(), "없음")
        self.assertEqual(dlg.key_edit.echoMode(), QLineEdit.Password)
        dlg.key_edit.setText(KEY)
        dlg.persist_box.setChecked(False)
        dlg.save()
        self.assertEqual(self.store.get(), KEY)
        self.assertEqual(os.listdir(self.tmp), [])
        self.assertEqual(dlg.status_label.text(), "이번 실행만")
        self.assertEqual(dlg.key_edit.text(), "")
        for label in (dlg.status_label, dlg.message_label):
            self.assertNotIn(KEY, label.text())
        dlg.clear_key()
        self.assertEqual(dlg.status_label.text(), "없음")
        self.assertIsNone(self.store.get())

    @unittest.skipUnless(WIN, "Windows DPAPI 전용")
    def test_persisted_save_label(self):
        dlg = self.dialog()
        dlg.key_edit.setText(KEY)
        dlg.persist_box.setChecked(True)
        dlg.save()
        self.assertEqual(dlg.status_label.text(), "저장됨(암호화)")
        self.assertTrue(os.path.isfile(self.path))

    def test_connection_runs_off_ui_thread(self):
        from PySide6.QtCore import QCoreApplication
        op = FakeOpener(status=401)
        dlg = self.dialog(opener=op)
        dlg.key_edit.setText(KEY)
        dlg.test_connection()
        self.assertFalse(dlg.test_btn.isEnabled())
        dlg.tasks.wait(10000)
        end = time.monotonic() + 5
        while not dlg.test_btn.isEnabled() and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        self.assertTrue(dlg.test_btn.isEnabled())
        self.assertIn("401", dlg.message_label.text())
        self.assertNotIn(KEY, dlg.message_label.text())
        self.assertEqual(op.calls[0]["headers"]["x-api-key"], KEY)
        self.assertIsNone(self.store.get())


if __name__ == "__main__":
    unittest.main()
