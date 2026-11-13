"""정리된 보기의 정돈(hazop/shell/clean_layout.py) 시험. 실행: python -m unittest tests.test_clean_layout

규칙마다 합성 자료로 보고, 가상 도면 SNP 6장에서 정돈 품질(layout_lint)이 모두 0이고 위상(끝의 연결 대상·상태)이 그대로인지 본다.
"""

import copy
import json
import os
import unittest

from hazop.shell import clean_layout as cl
from hazop.shell import clean_items, sheet_items
from tests.test_clean_items import snp_extractions

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO, "hazop", "shell", "web", "js", "canvas", "symbols.json"), encoding="utf-8") as fh:
    SYMBOLS = json.load(fh)["symbols"]
R0 = {"rot": 0, "flip_h": False, "flip_v": False, "basis": "none"}


def sym(i, kind, bbox, cat="valve", rot=0):
    return {"id": i, "layer": "symbol", "kind": kind, "category": cat, "bbox": list(bbox), "polyline": None, "unknown": False}, \
        {"orient": dict(R0, rot=rot), "review": "script"}


def pipe(i, pts, a=None, b=None, sa="connected", sb="connected"):
    ends = [{"end": "source", "point": list(pts[0]), "status": sa if a else "open", "node": a if sa == "connected" else None}, {"end": "target", "point": list(pts[-1]), "status": sb if b else "open", "node": b if sb == "connected" else None}]
    return {"id": i, "layer": "pipe", "kind": "physical_connection", "bbox": [0, 0, 0, 0], "polyline": [list(p) for p in pts], "unknown": False}, \
        {"line_type": "process", "flow": None, "ends": ends, "review": "script"}


def run(*parts):
    items, extras = [], {}
    for it, ex in parts:
        items.append(it)
        extras[it["id"]] = ex
    return items, extras, cl.tidy(items, extras, SYMBOLS)


def center(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


class RuleTest(unittest.TestCase):
    def test_1_nearly_equal_axes_become_one_value(self):
        parts = [sym("a", "transmitter", (100, 97, 130, 127), "instrument"), sym("b", "transmitter", (200, 101.5, 230, 131.5), "instrument"), sym("c", "transmitter", (300, 99, 330, 129), "instrument")]
        _i, _e, t = run(*parts)
        ys = {round(center(b)[1], 3) for b in t["symbols"].values()}
        self.assertEqual(len(ys), 1)
        self.assertEqual(t["lint"]["off_axis"], 0)

    def test_2_nearly_horizontal_and_vertical_lines_become_exact(self):
        _i, _e, t = run(pipe("h", [(0, 100), (100, 102.5)]), pipe("v", [(300, 0), (302, 100)]))
        h, v = t["pipes"]["h"]["polyline"], t["pipes"]["v"]["polyline"]
        self.assertEqual(h[0][1], h[1][1])
        self.assertEqual(v[0][0], v[1][0])
        self.assertEqual(t["lint"]["non_orthogonal"], 0)

    def test_3_valve_sits_on_the_pipe_axis_and_ports_touch_exactly(self):
        # 밸브(가로 흐름) 중심이 배관 축(y=100)에서 4 어긋나 있고, 배관 끝이 연결점에서 3 떨어져 있다
        valve = sym("v", "manual_valve", (100, 89, 150, 119))
        p1 = pipe("p1", [(0, 100), (97, 100)], None, "v")
        p2 = pipe("p2", [(153, 100), (300, 100)], "v", None)
        _i, _e, t = run(valve, p1, p2)
        b = t["symbols"]["v"]
        self.assertAlmostEqual(center(b)[1], 100, places=3)
        ports = cl._ports(SYMBOLS["manual_valve"], b, R0)
        self.assertEqual([round(x, 3) for x in t["pipes"]["p1"]["polyline"][-1]], [round(x, 3) for x in min(ports)])
        self.assertEqual([round(x, 3) for x in t["pipes"]["p2"]["polyline"][0]], [round(x, 3) for x in max(ports)])
        self.assertEqual(t["lint"]["loose_ends"], 0)
        self.assertEqual(t["lint"]["off_axis"], 0)

    def test_3_vertical_valve_centers_on_a_vertical_pipe(self):
        valve = sym("v", "manual_valve", (95, 100, 125, 150), rot=90)          # 세로 밸브(direction=south), 중심 x=110
        p1 = pipe("p1", [(108, 0), (108, 97)], None, "v")
        p2 = pipe("p2", [(108, 153), (108, 300)], "v", None)
        _i, _e, t = run(valve, p1, p2)
        self.assertAlmostEqual(center(t["symbols"]["v"])[0], 108, places=2)
        self.assertEqual(t["lint"]["loose_ends"], 0)

    def test_3_tee_sits_exactly_on_the_crossing_of_its_pipes(self):
        tee = sym("t", "tee", (198, 98, 200, 100), "piping_element")
        h = pipe("h", [(0, 99), (199, 99)], None, "t")
        v = pipe("v", [(199.8, 0), (199.8, 99)], None, "t")
        _i, _e, t = run(tee, h, v)
        c = center(t["symbols"]["t"])
        self.assertEqual([round(x, 2) for x in t["pipes"]["h"]["polyline"][-1]], [round(c[0], 2), round(c[1], 2)])
        self.assertEqual([round(x, 2) for x in t["pipes"]["v"]["polyline"][-1]], [round(c[0], 2), round(c[1], 2)])

    def test_4_pipe_ends_touch_the_edge_of_equipment(self):
        vessel = sym("e", "tank", (200, 100, 260, 200), "equipment")
        p = pipe("p", [(100, 150), (203, 150)], None, "e")                    # 끝이 설비 안으로 3 들어가 있다
        _i, _e, t = run(vessel, p)
        self.assertEqual(t["pipes"]["p"]["polyline"][-1], [200.0, 150.0])
        self.assertEqual(t["lint"]["loose_ends"], 0)

    def test_4_open_ends_are_not_connected_by_tidying(self):
        valve = sym("v", "manual_valve", (100, 85, 150, 115))
        p = pipe("p", [(0, 100), (80, 100)], None, "v", sb="open")             # 연결이 없는 끝: 열린 끝으로 남는다
        i, e, t = run(valve, p)
        self.assertEqual(t["pipes"]["p"]["ends"][1]["status"], "open")
        self.assertIsNone(t["pipes"]["p"]["ends"][1]["node"])
        self.assertEqual(t["pipes"]["p"]["polyline"][-1], [80, 100])

    def test_5_same_kind_gets_the_same_size_and_equipment_snaps_to_a_grid(self):
        parts = [sym("a", "manual_valve", (100, 100, 130, 150)), sym("b", "manual_valve", (300, 100, 332, 148)), sym("c", "manual_valve", (500, 100, 331, 149)),
                 sym("t1", "tank", (600, 100, 657, 203), "equipment")]
        _i, _e, t = run(*parts)
        sizes = {(round(b[2] - b[0], 2), round(b[3] - b[1], 2)) for k, b in t["symbols"].items() if k != "t1"}
        self.assertEqual(len(sizes), 1)
        w = t["symbols"]["t1"][2] - t["symbols"]["t1"][0]
        h = t["symbols"]["t1"][3] - t["symbols"]["t1"][1]
        self.assertEqual((w % 10, h % 10), (0, 0))
        self.assertEqual(t["lint"]["size_mismatch"], 0)

    def test_6_overlapping_symbols_are_pushed_apart_within_the_allowed_distance(self):
        parts = [sym("a", "manual_valve", (100, 100, 150, 130)), sym("b", "manual_valve", (144, 100, 194, 130))]
        i, e, t = run(*parts)
        self.assertEqual(t["lint"]["overlap_symbols"], 0)
        self.assertLessEqual(t["moved"], cl.MAX_SHIFT)

    def test_6_unsolvable_overlap_is_counted_not_hidden(self):
        parts = [sym("a", "manual_valve", (100, 100, 150, 130)), sym("b", "manual_valve", (110, 100, 160, 130))]      # 40 겹침: 허용 범위 안에서 못 푼다
        _i, _e, t = run(*parts)
        self.assertGreaterEqual(t["lint"]["overlap_symbols"], 1)

    def test_6_pipe_through_a_symbol_it_is_not_connected_to_is_counted(self):
        parts = [sym("v", "manual_valve", (100, 85, 150, 115)), pipe("p", [(0, 100), (300, 100)])]
        _i, _e, t = run(*parts)
        self.assertEqual(t["lint"]["overlap_pipe_symbol"], 1)

    def test_9_unconnected_crossing_pipes_get_a_hop_but_connected_ones_do_not(self):
        _i, _e, t = run(pipe("h", [(0, 100), (200, 100)]), pipe("v", [(100, 0), (100, 200)]))
        self.assertEqual(t["hops"], [{"id": "h", "x": 100.0, "y": 100.0}])
        tee = sym("t", "tee", (98, 98, 102, 102), "piping_element")
        _i, _e, t = run(tee, pipe("h", [(0, 100), (100, 100)], None, "t"), pipe("v", [(100, 0), (100, 100)], None, "t"), pipe("h2", [(100, 100), (200, 100)], "t", None))
        self.assertEqual(t["hops"], [])

    def test_lint_flags_a_bad_layout(self):
        items, extras, t = run(sym("v", "manual_valve", (100, 85, 150, 115)), pipe("p", [(0, 100), (90, 100)], None, "v"))
        bad = copy.deepcopy(t)
        bad["pipes"]["p"]["polyline"][-1] = [80, 100]          # 연결점에서 떨어진 끝
        self.assertEqual(cl.layout_lint(items, extras, SYMBOLS, bad)["loose_ends"], 1)
        bad2 = copy.deepcopy(t)
        bad2["pipes"]["p"]["polyline"] = [[0, 100], [90, 104]]
        self.assertGreaterEqual(cl.layout_lint(items, extras, SYMBOLS, bad2)["non_orthogonal"], 1)


class SnpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ex = snp_extractions()

    def test_lint_is_all_zero_and_moves_stay_within_the_allowed_distance_on_every_sheet(self):
        for d, e in self.ex.items():
            items = sheet_items.build_items(e)["items"]
            extras = clean_items.build(e)["items"]
            t = cl.tidy(items, extras, SYMBOLS)
            lint = dict(t["lint"])
            moved = lint.pop("moved")
            self.assertEqual({k: v for k, v in lint.items() if v}, {}, d)
            self.assertLessEqual(moved, cl.CENTER_SHIFT, d)

    def test_topology_is_unchanged_on_every_sheet(self):
        """끝의 연결 대상(node)·상태(status)·끝 개수·배관 수가 정돈 전과 같다. 이어진 것을 끊거나 안 이어진 것을 잇지 않는다."""
        for d, e in self.ex.items():
            items = sheet_items.build_items(e)["items"]
            extras = clean_items.build(e)["items"]
            t = cl.tidy(items, extras, SYMBOLS)
            for it in items:
                if it["layer"] != "pipe" or not it.get("polyline"):
                    continue
                before = [(x.get("end"), x.get("node"), x.get("status")) for x in extras[it["id"]]["ends"]]
                after = [(x.get("end"), x.get("node"), x.get("status")) for x in t["pipes"][it["id"]]["ends"]]
                self.assertEqual(before, after, "%s %s" % (d, it["id"]))
            self.assertEqual(len(t["pipes"]), len([i for i in items if i["layer"] == "pipe" and i.get("polyline")]), d)

    def test_tidy_does_not_change_its_inputs(self):
        e = self.ex["SNP-M-101"]
        items = sheet_items.build_items(e)["items"]
        extras = clean_items.build(e)["items"]
        before = copy.deepcopy((items, extras))
        cl.tidy(items, extras, SYMBOLS)
        self.assertEqual((items, extras), before)


if __name__ == "__main__":
    unittest.main()
