"""DEXPI 그림 쓰기(HZ-PLN-22 §6.7) 시험: hazop/export/dexpi_diagram.py. 되읽기는 tests/test_dexpi_picture.py가 본다.

입력은 가상 도면 SNP 6세트(drawio)와 손으로 만든 작은 DEXPI 파일이다. 되읽은 자리는 곁 파일의 배율로 원래 단위로 되돌려 견준다.
실행: python -m unittest tests.test_dexpi_diagram
"""

import copy
import itertools
import json
import math
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.export import dexpi_diagram as dd  # noqa: E402
from hazop.export import dexpi_export as de  # noqa: E402
from hazop.extract import corrections, dexpi_map, drawio  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_read  # noqa: E402
from hazop.graph import build  # noqa: E402
from tests.test_dexpi_export import SNP, dexpi_pair, export, reimport, snp_pair  # noqa: E402

TOL = 0.5  # 원래 단위(drawio px)


def objects(exp, typ):
    return [o for o in dexpi_read.parse_safely(exp.xml).iter("Object") if o.get("type") == typ]


def back(exp, p):
    s = exp.sidecar["scale"]
    return [(p[0] - s["dx"]) / s["factor"], (p[1] - s["dy"]) / s["factor"]]


def box_of(exp, node):
    g = node["geometry"]
    x0, y0 = back(exp, (g["x"], g["y"]))
    x1, y1 = back(exp, (g["x"] + g["width"], g["y"] + g["height"]))
    return [x0, y0, x1, y1]


def line_of(rel):
    return [rel["endpoints"][0]["point"]] + rel["waypoints"] + [rel["endpoints"][1]["point"]]


def far(a, b):
    return max(abs(x - y) for p, q in zip(a, b) for x, y in zip(p, q)) if len(a) == len(b) else math.inf


def by_id(doc, key="nodes"):
    return {x["source_object_id"]: x for x in doc[key]}


def pair_of(change):
    """SNP-M-101 추출을 고쳐 (추출, 그래프)."""
    ex = copy.deepcopy(snp_pair(SNP[0])[0])
    change(ex)
    return ex, build.build_graph(ex)


def exported(pair):
    exp = export(pair)
    return exp, reimport(exp, with_sidecar=False)


def entity(exp, local_id):
    return next(e for e in exp.sidecar["entities"] if e["local_id"] == local_id)


class RoundtripTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pairs = {os.path.basename(os.path.dirname(p)).split("_")[0]: snp_pair(p) for p in SNP}
        cls.exports = {k: export(v) for k, v in cls.pairs.items()}

    def each(self):
        for key in sorted(self.pairs):
            with self.subTest(drawing=key):
                yield self.pairs[key][0], self.exports[key], reimport(self.exports[key], with_sidecar=False)

    def test_every_exported_symbol_comes_back_in_its_place_and_size(self):
        for ex, exp, again in self.each():
            src, got = {n["local_id"]: n for n in ex["nodes"]}, by_id(again)
            self.assertGreater(len(exp.sidecar["entities"]), 15)
            for e in exp.sidecar["entities"]:
                g = src[e["local_id"]]["geometry"]
                want = [g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"]]
                self.assertLess(max(abs(a - b) for a, b in zip(want, box_of(exp, got[e["dexpi_id"]]))), TOL, e["tag"])

    def test_every_exported_pipe_comes_back_with_its_bends(self):
        bends = 0
        for ex, exp, again in self.each():
            src = {r["local_id"]: r for r in ex["relations"]}
            got = by_id(again, "relations")
            for p in exp.sidecar["pipes"]:
                want = line_of(src[p["local_id"]])
                want = want[::-1] if p["swapped"] else want
                self.assertLess(far(want, [back(exp, q) for q in line_of(got[p["dexpi_id"]])]), TOL, p["entity_id"])
                bends += len(want) - 2
        self.assertEqual(bends, 41)  # 나가는 배관의 꺾임점 전부(6장의 관계 전체는 48, 나머지는 계장선과 빠진 연결)

    def test_signal_lines_come_back_between_their_two_marks(self):
        count = 0
        for ex, exp, again in self.each():
            src = {tuple(sorted(e["source_object_id"] for e in r["endpoints"])): r for r in ex["relations"] if r["kind"] != "physical_connection"}
            entity_of = {e["dexpi_id"]: e["local_id"] for e in exp.sidecar["entities"]}
            sid = {n["local_id"]: n["source_object_id"] for n in ex["nodes"]}
            for r in again["relations"]:
                if r["kind"] == "physical_connection":
                    continue
                ends = tuple(sorted(sid[entity_of[e["source_object_id"]]] for e in r["endpoints"]))
                want, got = line_of(src[ends]), [back(exp, q) for q in line_of(r)]
                self.assertLess(min(far(want, got), far(want[::-1], got)), TOL)
                count += 1
        self.assertGreater(count, 15)

    def test_the_picture_passes_the_checks_and_is_the_same_every_time(self):
        for key, pair in sorted(self.pairs.items()):
            exp = self.exports[key]
            root = dexpi_read.parse_safely(exp.xml)
            self.assertEqual((dexpi_read.check_structure(root), dexpi_read.check_references(root)), ([], []))
            self.assertTrue(all(dexpi_map.type_is_known(o.get("type")) for o in root.iter("Object")))
            self.assertEqual({k: v for k, v in export(copy.deepcopy(pair)).files.items()}, exp.files)

    def test_one_unit_shape_for_each_kind_and_every_usage_points_at_one(self):
        for ex, exp, _ in self.each():
            kinds = {e["kind"] for e in exp.sidecar["entities"]}
            shapes = objects(exp, "Core/Diagram.Shape")
            names = {s.get("id"): next("".join(d.itertext()).strip() for d in s.findall("Data") if d.get("property") == "Name") for s in shapes}
            self.assertEqual(sorted(names.values()), sorted(k.upper() + "_SHAPE" for k in kinds))
            self.assertTrue(all(len(s.findall("Components/Object")) == 1 for s in shapes), "도형 선은 싣지 않고 단위 상자만")
            used = {r.get("objects")[1:] for u in objects(exp, "Core/Diagram.ShapeUsage") for r in u.findall("References")}
            self.assertEqual(used, set(names))
            self.assertEqual(len(objects(exp, "Core/Diagram.ShapeUsage")), exp.stats["picture"]["symbols"])

    def test_the_scale_in_the_sidecar_is_the_whole_number_that_was_used(self):
        for ex, exp, _ in self.each():
            w, h = ex["drawing"]["page_width"], ex["drawing"]["page_height"]
            self.assertEqual(exp.sidecar["scale"]["factor"], min(400.0 / w, 277.0 / h))

    def test_tags_and_line_numbers_are_written_as_text_once(self):
        for ex, exp, _ in self.each():
            texts = [next("".join(d.itertext()).strip() for d in t.findall("Data") if d.get("property") == "Text")
                     for t in objects(exp, "Core/Diagram.Text")]
            for e in exp.sidecar["entities"]:
                if e["tag"] and e["kind"] != "continuation":
                    self.assertIn(e["tag"], texts)
            for no in {p["line_no"] for p in exp.sidecar["pipes"] if p["line_no"]}:
                self.assertEqual(texts.count(no), 1, no)

    def test_the_place_used_to_find_a_target_again_is_the_middle_of_the_symbol_as_before(self):
        """그림이 없던 옛 내보내기는 모든 노드를 구성요소 가운데에 적었다. 새 내보내기로 바꿔 등록해도 사람 수정의 열쇠(at)가 같아야 한다."""
        for ex, exp, again in self.each():
            at = {k: v["at"] for k, v in corrections._fingerprints(again).items()}
            s, middle = exp.sidecar["scale"], {}
            for e in exp.sidecar["entities"]:
                g = next(n["geometry"] for n in ex["nodes"] if n["local_id"] == e["local_id"])
                middle[e["local_id"]] = [(g["x"] + g["width"] / 2) * s["factor"] + s["dx"], (g["y"] + g["height"] / 2) * s["factor"] + s["dy"]]
                self.assertLess(math.dist(at[e["dexpi_id"]], middle[e["local_id"]]), 0.8, e["tag"])
            rels = {r["local_id"]: r for r in ex["relations"]}
            for p in exp.sidecar["pipes"]:
                a, b = (middle[x["node_local_id"]] for x in rels[p["local_id"]]["endpoints"])
                self.assertLess(math.dist(at[p["dexpi_id"]], [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]), 0.8)

    def test_the_sidecar_keeps_its_old_columns_and_version(self):
        for _, exp, _ in self.each():
            self.assertEqual(exp.sidecar["schema"], "hazop_dexpi_sidecar/1")
            self.assertEqual(set(exp.sidecar) - {"picture"}, {
                "schema", "exporter_version", "dexpi_version", "attribution", "dexpi_sha256", "graph_id", "graph_version", "drawing_number",
                "extraction_run_id", "scale", "entities", "pipes", "check_directions", "unknowns"})
            json.loads(exp.files[exp.name + ".hazop.json"].decode("utf-8"))


class EndsTest(unittest.TestCase):
    """가상 도면에 없는 꼴: 거꾸로 적힌 계장선, 흐름이 target에서 시작하는 배관, 한 노즐에 다른 자리로 닿는 두 배관, 부모 도형 안의 기호."""

    @staticmethod
    def backwards(r):
        a, b = r["endpoints"]
        r["endpoints"] = [dict(b, end="source"), dict(a, end="target")]
        r["waypoints"] = r["waypoints"][::-1]

    def test_a_measuring_line_written_the_other_way_starts_at_the_sensing_end(self):
        def change(ex):
            kinds = {n["local_id"]: n["category"] for n in ex["nodes"]}
            rel = next(r for r in ex["relations"] if r["kind"] == "measurement_connection" and kinds[r["endpoints"][0]["node_local_id"]] != "instrument"
                       and kinds[r["endpoints"][0]["node_local_id"]] != "equipment")
            rel["waypoints"] = [[777, 333]]
            self.sense = rel["endpoints"][0]["point"]
            self.backwards(rel)
        exp, again = exported(pair_of(change))
        got = next(r for r in again["relations"] if r["kind"] == "measurement_connection" and r["waypoints"])
        self.assertLess(math.dist(back(exp, got["endpoints"][0]["point"]), self.sense), TOL)
        self.assertEqual([round(v) for v in back(exp, got["waypoints"][0])], [777, 333])
        written = dexpi_read.read(exp.xml).conn_paths[got["source_object_id"]]
        self.assertLess(math.dist(back(exp, written[0]), self.sense), TOL, "파일의 선도 측정 자리에서 시작함")

    def test_a_pipe_whose_flow_starts_at_its_target_is_drawn_along_the_flow(self):
        def change(ex):
            rel = next(r for r in ex["relations"] if r["kind"] == "physical_connection" and r["waypoints"] and r["flow_direction"]
                       and r["flow_direction"]["from_end"] == "source")
            self.local, self.points = rel["local_id"], line_of(rel)
            fd = rel["flow_direction"]
            rel["flow_direction"] = dict(fd, **{"from": fd["to"], "to": fd["from"], "from_end": "target", "to_end": "source"})
        exp, again = exported(pair_of(change))
        row = next(p for p in exp.sidecar["pipes"] if p["local_id"] == self.local)
        self.assertTrue(row["swapped"])
        got = line_of(by_id(again, "relations")[row["dexpi_id"]])
        self.assertLess(far(self.points[::-1], [back(exp, p) for p in got]), TOL)

    def test_a_signal_line_whose_ends_lie_nearer_the_other_symbol_does_not_stop_the_export(self):
        def change(ex):
            rel = next(r for r in ex["relations"] if r["kind"] == "measurement_connection")
            a, b = (e["point"] for e in rel["endpoints"])
            for r in ex["relations"]:
                if r["kind"] == "measurement_connection":
                    r["endpoints"][0]["point"], r["endpoints"][1]["point"] = r["endpoints"][1]["point"], r["endpoints"][0]["point"]
            self.assertNotEqual(a, b)
        exp, _ = exported(pair_of(change))
        self.assertGreater(exp.stats["picture"]["signals"], 0)

    def test_two_pipes_at_one_nozzle_keep_their_own_ends(self):
        def change(ex):
            kinds = {n["local_id"]: n["category"] for n in ex["nodes"]}
            ends = {}
            for r in ex["relations"]:
                for e in r["endpoints"]:
                    if r["kind"] == "physical_connection" and kinds[e["node_local_id"]] == "equipment":
                        ends.setdefault(e["node_local_id"], []).append((r, e))
            self.two = next(v for v in ends.values() if len(v) >= 2 and v[0][1]["point"] != v[1][1]["point"])[:2]
            for _r, e in self.two:
                e["port"] = "N9"
        exp, again = exported(pair_of(change))
        rels = by_id(again, "relations")
        for r, e in self.two:
            row = next(p for p in exp.sidecar["pipes"] if p["local_id"] == r["local_id"])
            got = [back(exp, p) for p in line_of(rels[row["dexpi_id"]])]
            self.assertLess(min(math.dist(got[0], e["point"]), math.dist(got[-1], e["point"])), TOL)
        model = dexpi_read.read(exp.xml)
        first = next(p for p in exp.sidecar["pipes"] if p["local_id"] in [r["local_id"] for r, _e in self.two])
        conn = next(c for c in model.connections if c["id"] == first["dexpi_id"])
        shared = next(n for n in (conn["source_node"], conn["target_node"])
                      if sum(n in (c["source_node"], c["target_node"]) for c in model.connections) == 2)
        point = next(e["point"] for r, e in self.two if r["local_id"] == first["local_id"])
        self.assertLess(math.dist(back(exp, model.node_pos[shared]), point), TOL, "노드의 자리는 먼저 적은 배관의 끝")

    def test_a_piping_node_sits_where_its_pipe_ends_and_not_in_the_middle_of_the_symbol(self):
        exp = export(snp_pair(SNP[0]))
        model = dexpi_read.read(exp.xml)
        for c in model.connections:
            path = model.conn_paths[c["id"]]
            for node, at in ((c["source_node"], path[0]), (c["target_node"], path[-1])):
                self.assertEqual(model.node_pos[node], at)

    def test_a_piping_node_of_a_dexpi_file_keeps_its_place_when_a_person_moves_the_pipe(self):
        ex, _ = dexpi_pair("small-pid-dexpi2.xml")
        pipe = next(r for r in ex["relations"] if r["source_object_id"] == "Pipe1")
        pipe["endpoints"][0]["point"] = [72.0, 125.0]
        exp, again = exported((ex, build.build_graph(ex)))
        self.assertEqual(dexpi_read.read(exp.xml).node_pos["Nd2"], (70.0, 120.0))
        got = line_of(by_id(again, "relations")["Pipe1"])
        self.assertIn([72.0, 125.0], got)

    def test_a_symbol_inside_a_parent_shape_is_drawn_at_its_place_on_the_sheet(self):
        def change(ex):
            v = next(n for n in ex["nodes"] if n["category"] == "valve")
            self.local, self.want = v["local_id"], [v["geometry"][k] for k in ("x", "y", "width", "height")]
            v["geometry"] = dict(v["geometry"], x=3, y=4)  # 부모 기준 좌표. 쪽 기준 자리는 source_locations에 있다
        exp, again = exported(pair_of(change))
        x0, y0, x1, y1 = box_of(exp, by_id(again)[entity(exp, self.local)["dexpi_id"]])
        self.assertLess(max(abs(a - b) for a, b in zip((x0, y0, x1 - x0, y1 - y0), self.want)), TOL)


class OrientationTest(unittest.TestCase):

    def turned(self, style, box=(400.0, 300.0, 60.0, 20.0)):
        """(되읽은 상자, 되읽은 모양) 또는 그리지 않은 까닭."""
        def change(ex):
            v = next(n for n in ex["nodes"] if n["kind"] == "manual_valve" or n["category"] == "valve")
            v["style"] = style
            v["geometry"] = dict(zip(("x", "y", "width", "height"), box))
            next(l for l in ex["source_locations"] if l["local_id"] == v["local_id"])["bbox"] = list(box)
            self.local = v["local_id"]
        exp, again = exported(pair_of(change))
        for row in exp.sidecar["picture"]["not_drawn"]:
            if row["local_id"] == self.local:
                self.assertEqual(row["box"], list(box))
                return None, row["reason"]
        node = by_id(again)[entity(exp, self.local)["dexpi_id"]]
        return [round(v, 1) for v in box_of(exp, node)], node["geometry"]["shape"]

    def test_quarter_turns_keep_the_box_and_the_angle(self):
        for style, rot in (("direction=south;", 90.0), ("direction=west;", 180.0), ("direction=north;", 270.0), ("", 0.0)):
            box, shape = self.turned(style)
            self.assertEqual((box, shape["rotation"], shape["mirrored"]), ([400.0, 300.0, 460.0, 320.0], rot, False), style)

    def test_rotation_turns_the_box_about_its_middle(self):
        for rot, want in ((90, [420.0, 280.0, 440.0, 340.0]), (180, [400.0, 300.0, 460.0, 320.0]), (270, [420.0, 280.0, 440.0, 340.0])):
            box, shape = self.turned("rotation=%d;" % rot)
            self.assertEqual((box, shape["rotation"]), (want, float(rot)))

    def test_mirrors_come_back(self):
        for style, want in (("flipH=1;", (0.0, True)), ("flipV=1;", (180.0, True)), ("flipH=1;flipV=1;", (180.0, False)),
                            ("rotation=270;flipH=1;", (270.0, True))):
            _box, shape = self.turned(style)
            self.assertEqual((shape["rotation"], shape["mirrored"]), want, style)

    def test_every_combination_points_where_the_drawio_reader_says_or_is_not_drawn(self):
        """도형 좌표의 두 축을 drawio 읽기(_symbol_direction)와 놓임이 같은 곳으로 보내는지 288가지 조합으로 맞댄다. 읽기가 모른다고 한 조합은
        그리지 않는다."""
        from hazop.extract import rules
        drawn = skipped = 0
        for combo in itertools.product(("", "east", "south", "west", "north", "up"), ("", "0", "1", "true"), ("", "1"),
                                       ("", "90", "180", "270", "-90", "450")):
            style = "".join("%s=%s;" % kv for kv in zip(("direction", "flipH", "flipV", "rotation"), combo) if kv[1])
            want = []
            for axis in ((1.0, 0.0), (0.0, 1.0)):
                cell = types.SimpleNamespace(cell_id="c", parent="1", style_map=drawio.parse_style("shape=s;valveType=v;" + style))
                with mock.patch.dict(rules.CHECK_VALVE_SYMBOL_DIRECTIONS, {("s", "v"): axis}):
                    want.append(drawio._symbol_direction(cell, {"c": {"bbox": [0, 0, 1, 1], "approximate": False}}, {"1"}))
            node = {"style": style, "geometry": {"x": 0.0, "y": 0.0, "width": 60.0, "height": 20.0}}
            try:
                p = dd.source_placement(node, {"bbox": [0.0, 0.0, 60.0, 20.0]}, "drawio")
            except dd.Undrawable as why:
                self.assertEqual((want, str(why)), ([None, None], "orientation_unknown"), style)
                skipped += 1
                continue
            t = math.radians(p.rotation)
            for (x, y), goal in zip(((-1.0 if p.mirrored else 1.0, 0.0), (0.0, 1.0)), want):
                self.assertIsNotNone(goal, style)
                self.assertLess(math.dist((x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t)), goal), 1e-9, style)
            drawn += 1
        self.assertEqual((drawn, skipped), (108, 180))

    def test_a_turn_the_reader_does_not_know_goes_to_the_sidecar(self):
        for direction in ("south", "west", "north"):
            for flips in ("flipH=1;", "flipV=1;", "flipH=1;flipV=1;"):
                self.assertEqual(self.turned("direction=%s;%s" % (direction, flips)), (None, "orientation_unknown"), direction + flips)

    def test_an_angle_just_short_of_a_full_turn_does_not_stop_the_export(self):
        for rot in ("-1e-9", "-0.0000001", "359.9999999", "719.9999999999", "-1e-17", "360", "-360", "359.9996"):
            box, shape = self.turned("rotation=%s;" % rot)
            self.assertEqual(box, [400.0, 300.0, 460.0, 320.0], rot)
            self.assertTrue(0.0 <= shape["rotation"] < 360.0, (rot, shape["rotation"]))

    def test_a_turned_symbol_of_a_dexpi_file_keeps_its_turn_when_written_again(self):
        ex, _ = dexpi_pair("small-pid-dexpi2.xml")
        ex["nodes"][0]["geometry"] = {"x": 50.0, "y": 110.0, "width": 10.0, "height": 20.0,
                                      "shape": {"name": "X", "width": 20.0, "height": 10.0, "rotation": 270.0, "mirrored": True}}
        exp, again = exported((ex, build.build_graph(ex)))
        g = by_id(again)["Pump1"]["geometry"]
        self.assertEqual([g[k] for k in ("x", "y", "width", "height")], [50.0, 110.0, 10.0, 20.0])
        self.assertEqual((g["shape"]["rotation"], g["shape"]["mirrored"], g["shape"]["width"]), (270.0, True, 20.0))


class NotDrawnTest(unittest.TestCase):

    def check(self, change, what, reason):
        """고친 자료를 내보내도 나가고, 그 대상은 XML에 그려지지 않고 곁 파일에 까닭과 함께 있다."""
        local = []

        def apply(ex):
            local.append(change(ex))
        pair = pair_of(apply)
        whole = export(snp_pair(SNP[0]))
        exp, again = exported(pair)
        self.assertEqual(exp.stats["components"], whole.stats["components"])
        self.assertEqual(exp.stats["connections"], whole.stats["connections"])
        rows = [r for r in exp.sidecar["picture"]["not_drawn"] if r["local_id"] == local[0]]
        self.assertEqual([(r["what"], r["reason"]) for r in rows], [(what, reason)])
        json.loads(exp.files[exp.name + ".hazop.json"].decode("utf-8"), parse_constant=lambda c: self.fail("JSON에 없는 수 %s" % c))
        key = "symbols" if what == "symbol" else "lines"
        self.assertEqual(exp.stats["picture"][key], whole.stats["picture"][key] - 1)
        return rows[0], exp, again

    @staticmethod
    def boxed(box):
        def change(ex):
            v = next(n for n in ex["nodes"] if n["category"] == "valve")
            v["geometry"] = dict(zip(("x", "y", "width", "height"), box))
            next(l for l in ex["source_locations"] if l["local_id"] == v["local_id"])["bbox"] = list(box)
            return v["local_id"]
        return change

    def test_a_box_outside_the_sheet_goes_to_the_sidecar(self):
        row, _, _ = self.check(self.boxed([5000.0, 100.0, 20.0, 20.0]), "symbol", "off_sheet")
        self.assertEqual(row["box"], [5000.0, 100.0, 20.0, 20.0])
        self.check(self.boxed([-300.0, 100.0, 20.0, 20.0]), "symbol", "off_sheet")

    def test_a_box_that_crosses_an_edge_of_the_sheet_goes_to_the_sidecar(self):
        for box in ([1600.0, 100.0, 400.0, 20.0], [100.0, 1100.0, 20.0, 400.0], [-300.0, 100.0, 400.0, 20.0], [100.0, -300.0, 20.0, 400.0]):
            self.check(self.boxed(box), "symbol", "off_sheet")

    def test_a_box_that_is_not_a_number_goes_to_the_sidecar(self):
        self.check(self.boxed([math.nan, 100.0, 20.0, 20.0]), "symbol", "bad_number")
        self.check(self.boxed([100.0, math.inf, 20.0, 20.0]), "symbol", "bad_number")

    def test_a_box_without_a_size_goes_to_the_sidecar(self):
        self.check(self.boxed([100.0, 100.0, 0.0, 20.0]), "symbol", "zero_size")
        self.check(self.boxed([100.0, 100.0, 20.0, -3.0]), "symbol", "zero_size")

    def test_a_component_without_a_box_goes_to_the_sidecar(self):
        def change(ex):
            v = next(n for n in ex["nodes"] if n["category"] == "valve")
            v["geometry"] = None
            ex["source_locations"] = [l for l in ex["source_locations"] if l["local_id"] != v["local_id"]]
            return v["local_id"]
        self.check(change, "symbol", "no_box")

    @staticmethod
    def lined(edit):
        def change(ex):
            r = next(r for r in ex["relations"] if r["kind"] == "physical_connection" and r["waypoints"])
            edit(r)
            return r["local_id"]
        return change

    def test_a_line_of_one_point_goes_to_the_sidecar(self):
        def edit(r):
            r["waypoints"] = []
            r["endpoints"][1]["point"] = list(r["endpoints"][0]["point"])
        self.check(self.lined(edit), "line", "one_point")

    def test_a_line_that_shrinks_to_one_point_goes_to_the_sidecar(self):
        def edit(r):
            x, y = r["endpoints"][0]["point"]
            r["waypoints"], r["endpoints"][1]["point"] = [], [x + 1e-4, y]
        self.check(self.lined(edit), "line", "one_point")

    def test_a_line_that_leaves_the_sheet_goes_to_the_sidecar(self):
        for p in ([3000.0, 100.0], [100.0, 3000.0], [-300.0, 100.0], [100.0, -300.0]):
            self.check(self.lined(lambda r: r.update(waypoints=[p])), "line", "off_sheet")

    def test_a_line_whose_end_is_unknown_or_strange_goes_to_the_sidecar(self):
        self.check(self.lined(lambda r: r["endpoints"][0].update(point=None)), "line", "end_unknown")
        self.check(self.lined(lambda r: r["waypoints"].append([math.nan, 3.0])), "line", "bad_number")
        self.check(self.lined(lambda r: r["waypoints"].append([99999.0, 3.0])), "line", "off_sheet")

    def test_the_place_of_a_component_that_is_not_a_number_does_not_stop_the_export(self):
        _, exp, _ = self.check(self.boxed([math.nan, math.nan, math.nan, 20.0]), "symbol", "bad_number")
        self.assertNotIn(b"nan", exp.xml)

    def test_a_connector_whose_direction_is_unknown_is_kept_in_the_sidecar_with_its_place(self):
        def change(ex):
            n = next(n for n in ex["nodes"] if n["kind"] == "continuation")
            n["attributes"].pop("direction", None)
            n["label_text"] = "HDR A\nSNP-M-999"
            self.local, self.geo = n["local_id"], n["geometry"]
        exp, _ = exported(pair_of(change))
        row = next(r for r in exp.sidecar["picture"]["not_drawn"] if r["local_id"] == self.local)
        self.assertEqual((row["what"], row["reason"], row["dexpi_id"], row["lines"]), ("symbol", "direction_unknown", None, ["HDR A", "SNP-M-999"]))
        self.assertEqual(row["box"], [self.geo[k] for k in ("x", "y", "width", "height")])
        self.assertNotIn("SNP-M-999", exp.xml.decode("utf-8"))

    def test_signal_lines_with_good_ends_that_dexpi_cannot_hold_are_kept_in_the_sidecar(self):
        seen = 0
        for path in SNP:
            exp = export(snp_pair(path))
            gone = [c["entity_id"] for c in exp.excluded["excluded_connections"]
                    if c["reason"] in ("sensing_location_not_piping_component", "signal_end_not_instrument_or_actuator")]
            rows = {r["entity_id"]: r for r in exp.sidecar["picture"]["not_drawn"] if r["what"] == "signal"}
            self.assertEqual(sorted(gone), sorted(rows))
            self.assertTrue(all(len(r["points"]) >= 2 for r in rows.values()))
            seen += len(rows)
        self.assertGreater(seen, 0)

    def test_kinds_without_a_class_are_counted_in_the_summary(self):
        def change(ex):
            for n in [n for n in ex["nodes"] if n["category"] == "valve"][:2]:
                n["kind"] = "damper"
        exp, _ = exported(pair_of(change))
        before = export(snp_pair(SNP[0])).stats["excluded_by_reason"]["no_dexpi_class"]
        self.assertEqual(exp.stats["excluded_by_reason"], {"no_dexpi_class": before + 2})
        self.assertEqual(exp.excluded["excluded_by_reason"], exp.stats["excluded_by_reason"])

    def test_a_place_the_reader_called_approximate_is_drawn_but_marked(self):
        def change(ex):
            v = next(n for n in ex["nodes"] if n["category"] == "valve")
            r = next(r for r in ex["relations"] if r["kind"] == "physical_connection")
            for loc in ex["source_locations"]:
                if loc["local_id"] == v["local_id"]:
                    loc["approximate"] = True
                if loc["local_id"] == r["local_id"]:
                    loc["method"] += "; parent_offset_approx"
            self.two = [("line", r["local_id"]), ("symbol", v["local_id"])]
        exp, _ = exported(pair_of(change))
        rows = exp.sidecar["picture"]["approximate"]
        self.assertEqual(sorted((r["what"], r["local_id"]) for r in rows), self.two)
        drawn = {e["dexpi_id"] for e in exp.sidecar["entities"]} | {p["dexpi_id"] for p in exp.sidecar["pipes"]}
        self.assertTrue(all(r["dexpi_id"] in drawn for r in rows))
        self.assertEqual(exp.stats["picture"]["approximate"], 2)
        self.assertEqual(export(snp_pair(SNP[0])).sidecar["picture"]["approximate"], [])

    def test_text_without_an_owner_is_kept_in_the_sidecar_only(self):
        def change(ex):
            ex["texts"].append({"local_id": "t-1", "text": "NOTE 7", "bbox": [10, 10, 30, 8]})
        exp, _ = exported(pair_of(change))
        self.assertIn({"text": "NOTE 7", "bbox": [10, 10, 30, 8]}, exp.sidecar["picture"]["texts"])
        self.assertNotIn("NOTE 7", exp.xml.decode("utf-8"))


class TextTest(unittest.TestCase):

    def test_an_off_page_connector_shows_its_two_lines(self):
        def change(ex):
            n = next(n for n in ex["nodes"] if n["kind"] == "continuation")
            n["attributes"]["direction"], n["label_text"] = "TO", "TO AUX FEEDWATER\nSNP-M-777\nthird"
        exp, _ = exported(pair_of(change))
        texts = [next("".join(d.itertext()).strip() for d in t.findall("Data") if d.get("property") == "Text") for t in objects(exp, "Core/Diagram.Text")]
        self.assertIn("TO AUX FEEDWATER", texts)
        self.assertIn("SNP-M-777", texts)
        self.assertNotIn("third", texts)

    def test_characters_xml_cannot_hold_are_dropped_from_the_picture_text(self):
        def change(ex):
            n = next(n for n in ex["nodes"] if n["kind"] == "continuation")
            n["attributes"]["direction"], n["label_text"] = "TO", "AB\x0cC\x00D E"
        exp, _ = exported(pair_of(change))
        self.assertIn("ABCD E", exp.xml.decode("utf-8"))


class SheetTest(unittest.TestCase):

    def test_a_dexpi_drawing_keeps_its_own_sheet_size(self):
        ex, _ = dexpi_pair("small-pid-dexpi2.xml")
        ex["drawing"].update(page_width=1189.0, page_height=841.0)
        exp, again = exported((ex, build.build_graph(ex)))
        self.assertEqual((again["drawing"]["page_width"], again["drawing"]["page_height"]), (1189.0, 841.0))
        self.assertEqual(exp.sidecar["picture"]["sheet"], [1189.0, 841.0])

    def test_without_the_extraction_the_export_still_goes_out_without_symbols(self):
        _ex, g = snp_pair(SNP[0])
        exp = de.export_drawing(g, None, require_confirmed_number=False)
        self.assertEqual(exp.stats["picture"]["symbols"], 0)

    def test_an_extraction_that_is_not_the_one_the_graph_was_built_from_is_not_drawn(self):
        """나누기로 번호가 밀린 그래프에 나누기 전 추출 결과를 넘기면 남의 자리에 그리지 않는다."""
        ex, g = snp_pair(SNP[0])
        shifted = copy.deepcopy(ex)
        ids = [n["source_object_id"] for n in shifted["nodes"]]
        for n, sid in zip(shifted["nodes"], ids[1:] + ids[:1]):
            n["source_object_id"] = sid
        exp = export((shifted, g))
        self.assertEqual(exp.stats["picture"]["symbols"], 0)
        self.assertEqual(exp.stats["components"], export((ex, g)).stats["components"])

    def test_a_picture_that_does_not_come_back_is_caught_before_writing(self):
        real = dd.dx.points
        for prop, shift in (("Position", 0.5), ("InnerPoints", 0.5)):
            def moved(parent, name, pts):
                real(parent, name, [(x + shift, y) for x, y in pts] if name == prop else pts)
            with self.subTest(prop), mock.patch.object(dd.dx, "points", moved), self.assertRaises(de.ExportError) as caught:
                export(snp_pair(SNP[0]))
            self.assertIn("그림", str(caught.exception))

    def test_a_wrong_turn_or_mirror_in_the_file_is_caught_before_writing(self):
        number, value = dd.dx.number, dd.dx.value
        for name, wrong in (("number", lambda parent, prop, v: number(parent, prop, v + 180.0 if prop == "Rotation" else v)),
                            ("value", lambda parent, prop, kind, text: value(parent, prop, kind, {"false": "true"}.get(text, text)
                                                                             if prop == "IsMirrored" else text))):
            with self.subTest(name), mock.patch.object(dd.dx, name, wrong), self.assertRaises(de.ExportError) as caught:
                export(snp_pair(SNP[0]))
            self.assertIn("자리나 방향이 다름", str(caught.exception))


class ConfirmedPictureTest(unittest.TestCase):
    """쪽 확정에서 내보내기까지: 사람이 더하고 옮긴 것이 그림에 들어간다."""

    def setUp(self):
        from scripts.check_edit_screen import install_sample
        from tests.test_sheet_confirmation import make_clean
        from hazop.extract import confirmation as cf
        self.tmp = tempfile.mkdtemp(prefix="hazop-dexpi-pic-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        env.start()
        self.addCleanup(env.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.cf, self.name = cf, install_sample(os.environ["HAZOP_WORK_ROOT"], "SNP-M-101")
        with open(cf.extraction_path(self.name), encoding="utf-8") as fh:
            self.ex = make_clean(json.load(fh))
        self.ex["drawing"]["identification_basis"] = "registration_confirmed"
        import build_graph
        with open(cf.extraction_path(self.name), "w", encoding="utf-8") as fh:
            json.dump(self.ex, fh, ensure_ascii=False)
        build_graph.build_one(cf.extraction_path(self.name), paths.output_root("graph"))

    def test_a_valve_added_and_a_pipe_moved_by_a_person_are_drawn_where_the_person_put_them(self):
        from hazop.extract import corrections
        pipe = next(r for r in self.ex["relations"] if r["kind"] == "physical_connection")
        ops = []
        for op, target, value in (("add_node", None, {"kind": "manual_valve", "category": "valve", "tag": "V-NEW-1", "bbox": [600, 200, 30, 20]}),
                                  ("set_path", pipe["source_object_id"], {"points": [[400, 400], [450, 420], [500, 400]]})):
            ops.append(corrections.make_op(self.ex, op, target, value, "검토자", existing_ops=ops, name=self.name))
        corrections.save_fp(self.name, ops, "검토자")
        self.assertTrue(self.cf.execute(self.name, "compare", {"mode": "side_by_side"}, by="검토자")["ok"])
        self.assertTrue(self.cf.execute(self.name, "confirm", by="검토자")["ok"])
        out = os.path.join(self.tmp, "out")
        de.export_names([self.name], out, confirmation="auto")
        with open(os.path.join(out, self.name + ".dexpi.xml"), "rb") as fh:
            data = fh.read()
        with open(os.path.join(out, self.name + ".hazop.json"), encoding="utf-8") as fh:
            side = json.load(fh)
        again, exp = dexpi_import.extract_bytes(data, "x.xml", sidecar=side)[0], mock.Mock(sidecar=side)
        node = next(n for n in again["nodes"] if n["tag"] == "V-NEW-1")
        self.assertEqual([round(v, 1) for v in box_of(exp, node)], [600.0, 200.0, 630.0, 220.0])
        row = next(p for p in side["pipes"] if p["local_id"] == pipe["local_id"])
        got = [back(exp, p) for p in line_of(by_id(again, "relations")[row["dexpi_id"]])]
        self.assertLess(min(far(got, w) for w in ([[400, 400], [450, 420], [500, 400]], [[500, 400], [450, 420], [400, 400]])), TOL)


if __name__ == "__main__":
    unittest.main()
