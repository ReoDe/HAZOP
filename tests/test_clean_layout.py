"""정리된 보기의 정돈(hazop/shell/clean_layout.py) 시험. 실행: python -m unittest tests.test_clean_layout

규칙마다 합성 자료로 보고, 가상 도면 SNP 6장에서 정돈 품질(layout_lint)이 모두 0이고 위상(끝의 연결 대상·상태)이 그대로인지 본다.
"""

import copy
import json
import math
import os
import tempfile
import time
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


def pipe(i, pts, a=None, b=None, sa="connected", sb="connected", line_type="process"):
    ends = [{"end": "source", "point": list(pts[0]), "status": sa if a else "open", "node": a if sa == "connected" else None}, {"end": "target", "point": list(pts[-1]), "status": sb if b else "open", "node": b if sb == "connected" else None}]
    return {"id": i, "layer": "pipe", "kind": "physical_connection", "bbox": [0, 0, 0, 0], "polyline": [list(p) for p in pts], "unknown": False}, \
        {"line_type": line_type, "flow": None, "ends": ends, "review": "script"}


def unknown(i, bbox):
    return {"id": i, "layer": "symbol", "kind": None, "category": None, "bbox": list(bbox), "polyline": None, "unknown": True}, {"orient": dict(R0), "review": "script"}


def run(*parts):
    items, extras = [], {}
    for it, ex in parts:
        items.append(it)
        extras[it["id"]] = ex
    return items, extras, cl.tidy(items, extras, SYMBOLS)


def center(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


# ---------------------------------------------------------------- 정돈 전후를 그림으로 견주는 도구(구현과 따로 센다)

def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def _line_dist(p, line):
    return min(_seg_dist(p, line[i], line[i + 1]) for i in range(len(line) - 1))


def _inside(p, b, m=1.0):
    return b[0] + m < p[0] < b[2] - m and b[1] + m < p[1] < b[3] - m


def _boxes_overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


def _collinear(l1, l2):
    tot = 0.0
    for i in range(len(l1) - 1):
        a, b = l1[i], l1[i + 1]
        for j in range(len(l2) - 1):
            c, d = l2[j], l2[j + 1]
            if abs(a[1] - b[1]) < .5 and abs(c[1] - d[1]) < .5 and abs(a[1] - c[1]) < .5:
                tot += max(0, min(max(a[0], b[0]), max(c[0], d[0])) - max(min(a[0], b[0]), min(c[0], d[0])))
            elif abs(a[0] - b[0]) < .5 and abs(c[0] - d[0]) < .5 and abs(a[0] - c[0]) < .5:
                tot += max(0, min(max(a[1], b[1]), max(c[1], d[1])) - max(min(a[1], b[1]), min(c[1], d[1])))
    return tot


def picture_changes(items, extras, t):
    """정돈이 그림에서 새로 만든 접촉: 배관 끝이 전에 안 닿던 다른 배관·기호에 닿음, 전에 없던 기호 겹침, 같은 줄 겹침."""
    syms = {i["id"]: i for i in items if i["layer"] == "symbol"}
    pipes = {i["id"]: i for i in items if i["layer"] == "pipe" and i.get("polyline") and len(i["polyline"]) >= 2}
    before = {pid: p["polyline"] for pid, p in pipes.items()}
    after = {pid: t["pipes"][pid]["polyline"] for pid in pipes}
    nodes = {pid: {e.get("node") for e in extras[pid]["ends"] if e.get("node")} for pid in pipes}
    bb_b = {k: v["bbox"] for k, v in syms.items()}
    bb_a = dict(bb_b)
    bb_a.update(t["symbols"])
    out = []
    ids = sorted(pipes)
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            if nodes[a] & nodes[b]:
                continue
            for x, y in ((a, b), (b, a)):
                for idx in (0, -1):
                    if _line_dist(after[x][idx], after[y]) < 0.75 <= _line_dist(before[x][idx], before[y]):
                        out.append(("end_on_other_pipe", x, y))
            if _collinear(after[a], after[b]) > _collinear(before[a], before[b]) + 2:
                out.append(("collinear_overlap", a, b))
    for pid in pipes:
        for e in extras[pid]["ends"]:
            idx = 0 if e.get("end") == "source" else -1
            for sid in syms:
                if sid != e.get("node") and _inside(after[pid][idx], bb_a[sid]) and not _inside(before[pid][idx], bb_b[sid]):
                    out.append(("end_into_symbol", pid, sid))
    sids = sorted(syms)
    for n, a in enumerate(sids):
        for b in sids[n + 1:]:
            if _boxes_overlap(bb_a[a], bb_a[b]) and not _boxes_overlap(bb_b[a], bb_b[b]):
                out.append(("symbol_overlap", a, b))
    return out


def port_gaps(items, extras, t):
    """그래프에서 기호(연결점 정의가 있는 것)에 이어진 배관 끝과 그 기호의 가장 가까운 연결점 사이 거리 목록."""
    kinds = {i["id"]: i for i in items if i["layer"] == "symbol"}
    out = []
    for pid, p in t["pipes"].items():
        for e in p["ends"]:
            nid = e.get("node")
            if e.get("status") != "connected" or nid not in t["symbols"]:
                continue
            d = SYMBOLS.get(kinds[nid]["kind"]) or {}
            if not d.get("ports") or d.get("fit") == "stretch":
                continue
            q = p["polyline"][0 if e["end"] == "source" else -1]
            ports = cl._ports(d, t["symbols"][nid], (extras.get(nid) or {}).get("orient") or R0)
            out.append((pid, nid, round(min(math.hypot(w[0] - q[0], w[1] - q[1]) for w in ports), 2)))
    return out


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
        self.assertEqual([round(v, 2) for v in t["pipes"]["p"]["polyline"][-1]], [202.4, 150.0])      # 그려진 겉모양(상자보다 4% 안쪽)에 닿는다
        self.assertEqual(t["lint"]["loose_ends"], 0)

    def test_4_pipe_ends_touch_the_drawn_outline_of_a_shaped_vessel_not_its_box(self):
        # 증기발생기: 아래는 좁은 목이라 상자 아래 가장자리와 그려진 테두리가 다르다. 끝은 상자가 아니라 테두리에 닿아야 한다
        sg = sym("g", "steam_generator", (200, 100, 300, 300), "equipment")
        p = pipe("p", [(250, 400), (250, 305)], None, "g")
        i, e, t = run(sg, p)
        end = t["pipes"]["p"]["polyline"][-1]
        self.assertAlmostEqual(end[0], 250.0, places=2)
        self.assertAlmostEqual(end[1], 294.0, places=1)           # 그림 좌표 y=97 → 100 + 0.97·200
        self.assertEqual(t["lint"]["loose_ends"], 0)
        bad = copy.deepcopy(t)
        bad["pipes"]["p"]["polyline"][-1] = [250, 299.5]            # 상자 아래 가장자리에는 닿지만 테두리에서는 뜬 끝
        self.assertEqual(cl.layout_lint(i, e, SYMBOLS, bad)["loose_ends"], 1)

    def test_5_continuation_pentagons_all_get_the_same_size_around_their_centers(self):
        parts = [sym("a", "continuation", (100, 100, 220, 134), "piping_element"), sym("b", "continuation", (300, 200, 440, 240), "piping_element")]
        _i, _e, t = run(*parts)
        sizes = {(round(b[2] - b[0], 2), round(b[3] - b[1], 2)) for b in t["symbols"].values()}
        self.assertEqual(sizes, {cl.CONT_SIZE})
        self.assertEqual(center(t["symbols"]["a"]), (160.0, 117.0))

    def test_5_small_instrument_circles_grow_to_the_standard_size(self):
        parts = [sym("a", "indicator", (100, 100, 128, 128), "instrument"), sym("b", "indicator", (300, 100, 330, 130), "instrument")]
        _i, _e, t = run(*parts)
        for b in t["symbols"].values():
            self.assertGreaterEqual(b[2] - b[0], cl.INSTR_MIN)
            self.assertGreaterEqual(b[3] - b[1], cl.INSTR_MIN)

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


class ReviewDefectTest(unittest.TestCase):
    """2026-11-14 검토 반려(재현 D:/HAZOP-trials/2026-11-14-review-clean-view)의 결함을 실제 추출 결과 꼴로 다시 만든다."""

    def test_control_valve_stays_on_its_process_pipe_and_the_signal_line_meets_the_actuator(self):
        # SNP-M-102 RC-PV101(local-node-008)의 좌표: 구동부 신호선이 몸통 가운데 위에서 내려온다
        valve = sym("v", "control_valve", (311, 134, 361, 196))
        ctl = sym("c", "controller", (312, 33, 360, 81), "instrument")
        p_in = pipe("in", [(241, 181), (311, 181.12)], None, "v", line_type="process_secondary")
        p_out = pipe("out", [(361, 181), (431, 181)], "v", None, line_type="process_secondary")
        sig = pipe("sig", [(336, 81), (336, 134)], "c", "v", line_type="signal_electric")
        items, extras, t = run(valve, ctl, p_in, p_out, sig)
        gaps = {pid: g for pid, _n, g in port_gaps(items, extras, t)}
        self.assertLessEqual(gaps["in"], 0.5)
        self.assertLessEqual(gaps["out"], 0.5)
        self.assertLessEqual(abs(center(t["symbols"]["v"])[0] - 336), 0.5)       # 몸통은 옆으로 비켜나지 않는다
        end = t["pipes"]["sig"]["polyline"][-1]
        self.assertAlmostEqual(end[0], center(t["symbols"]["v"])[0], places=2)    # 신호선은 구동부(몸통 가운데 위)에 닿는다
        self.assertLess(end[1], center(t["symbols"]["v"])[1])

    def test_a_graph_connected_end_far_from_its_port_is_counted_however_far_it_is(self):
        items, extras, t = run(sym("v", "manual_valve", (100, 85, 150, 115)), pipe("p", [(0, 100), (90, 100)], None, "v"))
        for far in (30, 80, 300):
            bad = copy.deepcopy(t)
            bad["pipes"]["p"]["polyline"][-1] = [100 - far, 100]
            self.assertEqual(cl.layout_lint(items, extras, SYMBOLS, bad)["port_miss"], 1, far)

    def test_open_ends_and_ends_on_unknown_symbols_never_move(self):
        a = pipe("a", [(100, 0), (100, 100)])                                     # 두 끝 모두 열림
        b = pipe("b", [(104, 0), (104, 300)])
        u = unknown("u", (190, 290, 210, 310))
        c = pipe("c", [(103, 200), (196, 297)], None, "u")                        # 미확인 기호에 붙은 끝
        items, extras, t = run(a, b, u, c)
        self.assertEqual(t["pipes"]["a"]["polyline"], [[100, 0], [100, 100]])
        self.assertEqual(t["pipes"]["c"]["polyline"][-1], [196, 297])

    def test_axis_groups_do_not_chain_past_the_allowed_distance(self):
        parts = [sym("t%d" % k, "transmitter", (100 + 5 * k - 24, 100 * k, 100 + 5 * k + 24, 100 * k + 48), "instrument") for k in range(6)]
        _i, _e, t = run(*parts)
        for k in range(6):
            self.assertLessEqual(abs(center(t["symbols"]["t%d" % k])[0] - (100 + 5 * k)), cl.AXIS_TOL + 1e-6, k)

    def test_an_end_keeps_the_port_the_graph_gave_it_when_the_symbol_is_pushed_past_it(self):
        # 작은 밸브가 설비와 겹쳐 오른쪽으로 밀린다. 오른쪽에서 오는 배관은 계속 오른쪽 연결점에 붙어야 한다(반대편 연결점으로 넘어가 몸통을 가로지르면 안 된다)
        tank = sym("e", "tank", (0, 0, 100, 100), "equipment")
        valve = sym("v", "manual_valve", (92, 40, 104, 60))
        p = pipe("p", [(104, 50), (200, 50)], "v", None)
        items, extras, t = run(tank, valve, p)
        ports = cl._ports(SYMBOLS["manual_valve"], t["symbols"]["v"], R0)
        self.assertAlmostEqual(t["pipes"]["p"]["polyline"][0][0], max(w[0] for w in ports), places=2)

    def test_tidying_never_adds_a_contact_or_an_overlap_it_cannot_explain(self):
        # 가까이 지나가는 두 배관과 미확인 기호 곁의 밸브: 축 맞춤·밀어내기가 새 접촉·겹침을 만들면 정돈을 버린다
        parts = [sym("v", "manual_valve", (100, 90, 130, 110)), unknown("u", (131, 90, 151, 110)), pipe("p1", [(0, 100), (100, 100)], None, "v"),
                 pipe("p2", [(20, 104), (300, 104)]), pipe("p3", [(60, 0), (60, 97)])]
        items, extras, t = run(*parts)
        self.assertEqual(picture_changes(items, extras, t), [])
        self.assertEqual(t["lint"]["topology_changed"], 0)

    def test_tidy_scales_close_to_linearly(self):
        e = snp_extractions()["SNP-M-101"]
        items0 = sheet_items.build_items(e)["items"]
        extras0 = clean_items.build(e)["items"]
        items, extras = [], {}
        n = 11                                                                    # 11x11 = 121장, 기호 4천여 개
        for gx in range(n):
            for gy in range(n):
                dx, dy, suf = gx * 2000, gy * 1500, "@%d_%d" % (gx, gy)
                for it in items0:
                    c = copy.deepcopy(it)
                    c["id"] += suf
                    if c.get("bbox"):
                        c["bbox"] = [c["bbox"][0] + dx, c["bbox"][1] + dy, c["bbox"][2] + dx, c["bbox"][3] + dy]
                    if c.get("polyline"):
                        c["polyline"] = [[q[0] + dx, q[1] + dy] for q in c["polyline"]]
                    items.append(c)
                for k, v in extras0.items():
                    c = copy.deepcopy(v)
                    for x in c.get("ends") or []:
                        x["point"] = [x["point"][0] + dx, x["point"][1] + dy] if x.get("point") else x.get("point")
                        x["node"] = x["node"] + suf if x.get("node") else x.get("node")
                    extras[k + suf] = c
        t0 = time.perf_counter()
        t = cl.tidy(items, extras, SYMBOLS)
        took = time.perf_counter() - t0
        self.assertGreater(sum(1 for i in items if i["layer"] == "symbol"), 4000)
        self.assertLess(took, 10.0, "기호 4천여 개 정돈 %.1f초" % took)
        self.assertEqual(t["lint"]["topology_changed"], 0)


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

    def test_every_connected_end_touches_its_port_and_the_picture_gains_no_contact(self):
        for d, e in self.ex.items():
            items = sheet_items.build_items(e)["items"]
            extras = clean_items.build(e)["items"]
            t = cl.tidy(items, extras, SYMBOLS)
            self.assertEqual([g for g in port_gaps(items, extras, t) if g[2] > 0.5], [], d)
            self.assertEqual(picture_changes(items, extras, t), [], d)

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


_APR = {}


def apr_extractions():
    """APR1400 표본(tests/fixtures/apr1400/pdf)을 PDF 어댑터로 읽은 결과. 한 번만 읽는다."""
    if not _APR:
        from hazop.extract.adapters import pdf_vector
        d = os.path.join(REPO, "tests", "fixtures", "apr1400", "pdf")
        old = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = tempfile.mkdtemp(prefix="hazop-apr-")
        try:
            for f in sorted(os.listdir(d)):
                _APR[f[:12]] = pdf_vector.extract(os.path.join(d, f), page=0, repo_root=REPO)
        finally:
            if old is None:
                os.environ.pop("HAZOP_WORK_ROOT", None)
            else:
                os.environ["HAZOP_WORK_ROOT"] = old
    return copy.deepcopy(_APR)


class AprTest(unittest.TestCase):
    """PDF로 읽은 쪽: 정돈은 어긋나도 되지만(기준값), 그림의 이어짐과 겹침을 정돈 전보다 나쁘게 만들면 안 된다."""

    @classmethod
    def setUpClass(cls):
        cls.ex = apr_extractions()

    def test_tidying_a_pdf_page_never_changes_contacts_or_adds_overlaps(self):
        for d, e in self.ex.items():
            items = sheet_items.build_items(e)["items"]
            extras = clean_items.build(e)["items"]
            t = cl.tidy(items, extras, SYMBOLS)
            self.assertEqual(picture_changes(items, extras, t), [], d)
            self.assertEqual(t["lint"]["topology_changed"], 0, d)


if __name__ == "__main__":
    unittest.main()
