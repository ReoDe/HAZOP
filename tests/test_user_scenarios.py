"""scripts/check_user_scenarios.py의 창 없이 도는 부분: KLM 계산, UIA 점검, WebSocket 프레임, 키 해석, 결과 표."""

import html
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import check_user_scenarios as cus  # noqa: E402


def result(**kw):
    r = {"id": "S9", "title": "시험", "passed": True, "clicks": 0, "keys": 0, "screens": 0, "ops": [], "latencies": [],
         "focus_lost": [], "defects": [], "shots": [], "steps": [], "elapsed": 1.0}
    r.update(kw)
    return r


class KlmTest(unittest.TestCase):
    def test_ctrl_p_then_click_counts_homing_once_each_way(self):
        ops, hand = [], "keyboard"
        for kind, n in (("think", 1), ("key", 2), ("click", 1), ("click", 1), ("type", 3)):
            o, hand = cus.klm_ops_for(kind, n, hand)
            ops += o
        self.assertEqual(ops, ["M", "K", "K", "H", "P", "B", "B", "P", "B", "B", "H", "K", "K", "K"])
        self.assertAlmostEqual(cus.klm_seconds(ops), 1.35 + 5 * 0.28 + 2 * 0.4 + 2 * 1.1 + 4 * 0.1, places=2)

    def test_unknown_operator_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            cus.klm_ops_for("drag")


class UiaAuditTest(unittest.TestCase):
    ITEMS = [{"type": "Edit", "name": "", "rect": [0, 0, 10, 10], "offscreen": False, "aid": "a"},
             {"type": "Edit", "name": "도면번호", "rect": [0, 0, 10, 10], "offscreen": False, "aid": "b"},
             {"type": "Button", "name": " ", "rect": [0, 0, 10, 10], "offscreen": True, "aid": "c"},
             {"type": "Text", "name": "", "rect": [0, 0, 10, 10], "offscreen": False, "aid": "d"},
             {"type": "Button", "name": "등록", "rect": [90, 90, 20, 20], "offscreen": False, "aid": "e"}]

    def test_unnamed_controls_skip_text_offscreen_and_named(self):
        self.assertEqual([e["aid"] for e in cus.unnamed_controls(self.ITEMS)], ["a"])

    def test_outside_window_flags_only_named_overflowing_elements(self):
        self.assertEqual([e["aid"] for e in cus.outside_window(self.ITEMS, [0, 0, 100, 100])], ["e"])
        self.assertEqual(cus.outside_window(self.ITEMS, None), [])


class WebSocketTest(unittest.TestCase):
    def test_masked_client_frame_round_trips_long_korean_text(self):
        text = "승인" * 100
        frame = cus.ws_frame(text, b"\x01\x02\x03\x04")
        fin, op, payload, used = cus.ws_parse(frame)
        self.assertEqual((fin, op, payload.decode("utf-8"), used), (1, 1, text, len(frame)))

    def test_unmasked_server_frame_and_partial_buffer(self):
        body = b'{"id":1}'
        frame = bytes([0x81, len(body)]) + body
        self.assertIsNone(cus.ws_parse(frame[:-1]))
        self.assertEqual(cus.ws_parse(frame + b"rest")[:3], (1, 1, body))

    def test_64bit_length_frame(self):
        body = b"x" * 70000
        frame = bytes([0x81, 127]) + struct.pack(">Q", len(body)) + body
        self.assertEqual(len(cus.ws_parse(frame)[2]), 70000)


class ProgressTextTest(unittest.TestCase):
    def test_running_only_while_calls_remain(self):
        self.assertTrue(cus.running_text(["AI 3/10 호출 · 실패 7"]))
        self.assertFalse(cus.running_text(["AI 분석 끝남: 10/10 호출", "AI 10/10 호출 · 실패 5"]))
        self.assertFalse(cus.running_text(["칸 숫자 = 최고 위험도"]))


class ChordTest(unittest.TestCase):
    def test_chords(self):
        self.assertEqual(cus.parse_chord("ctrl+shift+e"), [0x11, 0x10, ord("E")])
        self.assertEqual(cus.parse_chord("Ctrl+5"), [0x11, ord("5")])
        self.assertEqual(cus.parse_chord("hangul"), [0x15])
        with self.assertRaises(ValueError):
            cus.parse_chord("ctrl+?")


class ReportTest(unittest.TestCase):
    def test_report_lists_scenarios_and_sorts_defects_by_severity(self):
        rs = [result(id="S1", keys=4, ops=["M", "K"], latencies=[{"what": "x", "seconds": 0.5}],
                     defects=[{"severity": "하", "title": "이름 없음", "steps": ["Ctrl+1"], "shot": "shots/S1-01.png"}]),
              result(id="S2", passed=False, clicks=1, ops=["P", "B", "B"],
                     defects=[{"severity": "상", "title": "<저장 안 됨>", "steps": []}])]
        page = cus.render_report(rs, [{"where": "① 자료 등록", "kind": "UIA 이름 없음", "detail": "Edit"}], "메타")
        self.assertIn("결함 (2)", page)
        self.assertLess(page.index("&lt;저장 안 됨&gt;"), page.index("이름 없음"))
        self.assertIn("shots/S1-01.png", page)
        self.assertIn(html.escape(cus.KLM_SOURCE), page)

    def test_inconclusive_scenario_is_not_counted_as_failure(self):
        r = result(inconclusive="한글 입력 상태를 만들지 못함")
        self.assertEqual(cus.verdict(r), "판정 불가")
        self.assertEqual(cus.verdict(result(passed=False, inconclusive="x")), "실패")
        self.assertIn("판정 불가", cus.render_report([r], [], ""))

    def test_summary_keyboard_only_and_latency(self):
        s = cus.summarize(result(clicks=0, ops=["K", "K"], latencies=[{"what": "a", "seconds": 0.2},
                                                                      {"what": "b", "seconds": 0.6}]))
        self.assertTrue(s["keyboard_only"])
        self.assertEqual((s["lat_median"], s["lat_max"], s["klm"]), (0.4, 0.6, 0.56))
        self.assertFalse(cus.summarize(result(clicks=1))["keyboard_only"])


class PackagingTest(unittest.TestCase):
    def test_checker_is_not_bundled(self):
        import build_package
        self.assertNotIn("check_user_scenarios", build_package.SCRIPT_MODULES)


if __name__ == "__main__":
    unittest.main()
