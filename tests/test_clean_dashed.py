"""점선 배관(pdf_dashed, 관계 종류 physical_connection)과 신호 점선(pdf_dashed, signal_connection)을 정리된 보기가 가르는지.
실행: python -m unittest tests.test_clean_dashed

배관 굵기 점선(r3b b8afa78~25bb189)은 물리 연결 관계로 나온다. 정리된 보기는 이것을 배관으로 보고 기호 자리를 잡는 데 쓰고, 신호 점선은 기호 자리를
정하지 않는 신호선으로 둔다. 그리는 쪽(web/js/canvas/clean_view.js)의 점선 획은 web/test/clean_dashed.test.js가 본다.
"""

import unittest

from hazop.shell import clean_items, clean_layout as cl
from tests.test_clean_items import extraction, node, rel
from tests.test_clean_layout import center, pipe, port_gaps, run, sym


class ExtrasTest(unittest.TestCase):
    def kinds(self, line_type, kind):
        r = rel("r", ("a", [40, 20]), ("b", [200, 20]), line_type=line_type)
        r["kind"] = kind
        ex = extraction([node("a", "pump", 0, 0, 40, 40, cat="equipment"), node("b", "tank", 200, 0, 40, 40, cat="equipment")], [r], fmt="pdf")
        return clean_items.build(ex)["items"]["r"]

    def test_a_dashed_relation_carries_its_relation_kind(self):
        self.assertEqual(self.kinds("pdf_dashed", "physical_connection")["rel_kind"], "physical_connection")
        self.assertEqual(self.kinds("pdf_dashed", "signal_connection")["rel_kind"], "signal_connection")

    def test_other_line_types_get_no_new_key(self):
        self.assertNotIn("rel_kind", self.kinds("process", "physical_connection"))
        self.assertNotIn("rel_kind", self.kinds("pdf_solid", "physical_connection"))


class LayoutTest(unittest.TestCase):
    """제어밸브 한 개: 앞뒤 배관과 위의 신호선(RC-PV101 꼴). 배관이 점선이어도 밸브는 배관 위에 서고, 신호 점선은 구동부에 닿는다."""

    def scene(self, pipe_kind):
        valve = sym("v", "control_valve", (311, 134, 361, 196))
        ctl = sym("c", "controller", (312, 33, 360, 81), "instrument")
        p_in = pipe("in", [(241, 181), (311, 181.12)], None, "v", line_type="pdf_dashed")
        p_out = pipe("out", [(361, 181), (431, 181)], "v", None, line_type="pdf_dashed")
        sig = pipe("sig", [(336, 81), (336, 134)], "c", "v", line_type="pdf_dashed")
        p_in[1]["rel_kind"] = p_out[1]["rel_kind"] = pipe_kind
        sig[1]["rel_kind"] = "signal_connection"
        return run(valve, ctl, p_in, p_out, sig)

    def test_a_dashed_physical_pipe_places_the_symbol_like_a_process_pipe(self):
        items, extras, t = self.scene("physical_connection")
        gaps = {pid: g for pid, _n, g in port_gaps(items, extras, t)}
        self.assertLessEqual(gaps["in"], 0.5)
        self.assertLessEqual(gaps["out"], 0.5)
        self.assertLessEqual(abs(center(t["symbols"]["v"])[0] - 336), 0.5)
        end = t["pipes"]["sig"]["polyline"][-1]
        self.assertAlmostEqual(end[0], center(t["symbols"]["v"])[0], places=2)     # 신호 점선은 구동부(몸통 가운데 위)에 닿는다
        self.assertLess(end[1], center(t["symbols"]["v"])[1])

    def test_a_dashed_physical_pipe_is_tidied_exactly_like_the_same_process_pipe(self):
        def scene(line_type, kind):
            valve = sym("v", "control_valve", (311, 150, 361, 212))               # 앞뒤 배관과 어긋나게 둔다(정돈이 움직여야 하는 장면)
            p_in = pipe("in", [(241, 181), (311, 181.12)], None, "v", line_type=line_type)
            p_out = pipe("out", [(361, 190), (431, 190)], "v", None, line_type=line_type)
            if kind:
                p_in[1]["rel_kind"] = p_out[1]["rel_kind"] = kind
            return run(valve, p_in, p_out)[2]
        self.assertEqual(scene("pdf_dashed", "physical_connection"), scene("process", None))

    def test_the_two_dashed_kinds_are_told_apart(self):
        sh = cl._Sheet(*self._sheet_args("physical_connection"))
        self.assertFalse(sh.pipes["in"]["signal"])
        self.assertTrue(sh.pipes["sig"]["signal"])
        sh = cl._Sheet(*self._sheet_args("signal_connection"))
        self.assertTrue(sh.pipes["in"]["signal"])

    def _sheet_args(self, pipe_kind):
        items, extras, _t = self.scene(pipe_kind)
        return items, extras, cl.SYMBOLS if hasattr(cl, "SYMBOLS") else {}


if __name__ == "__main__":
    unittest.main()
