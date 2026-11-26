"""자동 수락을 켜도 되는지의 판정(scripts/check_auto_accept.py judge). 채점된 줄만 보는 순수 함수 시험이고 도면·응답을 열지 않는다.
실행: python -m unittest tests.test_auto_accept_judge
"""

import contextlib
import io
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import check_auto_accept as C  # noqa: E402


def r(n, res="ok", value="pump", truth=None, conf=0.9, field="kind"):
    return [{"field": field, "task": field, "res": res, "value": value, "truth": truth or (value if res == "ok" else None), "conf": conf}
            for _ in range(n)]


GOOD = r(50) + r(20, field="tag", value="V1")
BAND = r(25, conf=0.65)


class JudgeTest(unittest.TestCase):
    def why(self, rows, floor=0.7):
        return C.judge(rows, floor)

    def test_pass(self):
        out = self.why(GOOD)
        self.assertEqual((out["kind"], out["tag"], out["why"]), (True, True, []))

    def test_count_precision_and_wilson(self):
        self.assertIn("count", self.why(r(39))["why"])
        self.assertIn("precision", self.why(r(50) + r(10, "wrong", "tank", "pump"))["why"])
        out = self.why(r(36) + r(4, "wrong", "tank", "pump"))
        self.assertEqual(out["why"], ["wilson"], "40건의 90%는 하한이 80%에 못 미친다")

    def test_flips(self):
        for truth, value in (("check_valve", "damper"), ("isolation_valve", "pump"), ("psv", "manual_valve"), ("relief_valve", "check_valve"),
                             ("motor_operated_valve", "air_operated_valve"), ("manual_valve", "control_valve")):
            self.assertEqual(self.why(r(99) + r(1, "wrong", value, truth))["why"], ["flip"], (truth, value))
        self.assertTrue(self.why(r(99) + r(1, "wrong", "tank", "pump"))["kind"])

    def test_unpaired_components(self):
        self.assertTrue(self.why(r(99) + r(2, "unpaired", "pump"))["kind"])
        self.assertEqual(self.why(r(99) + r(3, "unpaired", "pump"))["why"], ["unpaired"])
        self.assertTrue(self.why(r(99) + r(4, "unpaired", "air_flow_arrow"))["kind"], "설비·밸브·계기가 아닌 종류는 세지 않는다")

    def test_outside_and_moved_are_not_scored(self):
        self.assertTrue(self.why(GOOD + r(90, "outside") + r(90, "moved"))["kind"])

    def test_tags(self):
        self.assertIsNone(self.why(r(50) + r(9, field="tag"))["tag"])
        self.assertFalse(self.why(r(50) + r(18, field="tag") + r(1, "wrong", field="tag"))["tag"])
        self.assertTrue(self.why(r(50) + r(19, field="tag") + r(1, "wrong", field="tag"))["tag"])

    def test_lower_floor_needs_its_own_band(self):
        self.assertTrue(self.why(GOOD + BAND, 0.6)["kind"])
        self.assertIn("band_count", self.why(GOOD + r(19, conf=0.65), 0.6)["why"])
        self.assertIn("band_precision", self.why(GOOD + r(16, conf=0.65) + r(4, "wrong", "tank", "pump", 0.65), 0.6)["why"])
        self.assertIn("band_flip", self.why(GOOD + r(60, conf=0.65) + r(1, "wrong", "damper", "check_valve", 0.65), 0.6)["why"])
        self.assertIn("count", self.why(r(30) + r(30, conf=0.65), 0.6)["why"], "0.70 기준을 못 지나면 0.60도 켜지 않는다")

    def test_report_is_totals_only(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            C.report([dict(x, page="apr1400-999", tag="SECRET") for x in GOOD + BAND], (0.6, 0.7))
        self.assertNotIn("999", out.getvalue())
        self.assertNotIn("SECRET", out.getvalue())
        self.assertIn("0.60", out.getvalue())
        self.assertIn("통과", out.getvalue())

    def test_held_pages_stay_closed(self):
        with self.assertRaises(SystemExit):
            C.main(["--input-dir", "x", "--keys", "x", "--responses", "x", "--pages", "13"])
        with self.assertRaises(SystemExit):
            C.main(["--input-dir", "x", "--keys", "x", "--judge"])


if __name__ == "__main__":
    unittest.main()
