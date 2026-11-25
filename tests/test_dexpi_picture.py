"""DEXPI 그림 자리(HZ-PLN-22 §5.3·§6.7) 시험: 되읽기(상자·방향·선 점).

손으로 만든 작은 DEXPI 파일의 그림 쪽을 바꿔 가며 본다. 공개 예제는 HAZOP_DEXPI_SAMPLES가 가리키는 폴더에 있을 때만 돈다.
실행: python -m unittest tests.test_dexpi_picture
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.extract import corrections  # noqa: E402
from hazop.extract.adapters import dexpi_import  # noqa: E402
from hazop.shell import clean_items, sheet_items  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi")
SAMPLES = os.environ.get("HAZOP_DEXPI_SAMPLES")
PUMP_SHAPE = """<Object type="Core/Diagram.ShapeUsage">
                    <Data property="Position">
                      <AggregatedDataValue type="Core/Diagram.Point"><Data property="X"><Double>60.0</Double></Data><Data property="Y"><Double>120.0</Double></Data></AggregatedDataValue>
                    </Data>
                    <References objects="#ShapeArrow1" property="Shape"/>
                  </Object>"""
PIPE1_LINE = """<References objects="#Pos2" property="Source"/>
                    <References objects="#Pos3" property="Target"/>"""


def fixture():
    with open(os.path.join(FIXTURES, "small-pid-dexpi2.xml"), encoding="utf-8") as fh:
        return fh.read()


def extract(text):
    return dexpi_import.extract_bytes(text.encode("utf-8"), "x.xml")[0]


def swap(old, new, text=None):
    text = text or fixture()
    assert old in text, old
    return text.replace(old, new, 1)


def points(prop, *pts):
    return '<Data property="%s">%s</Data>' % (prop, "".join(
        '<AggregatedDataValue type="Core/Diagram.Point"><Data property="X"><Double>%s</Double></Data><Data property="Y">'
        '<Double>%s</Double></Data></AggregatedDataValue>' % p for p in pts))


def usage(x=60.0, y=120.0, sx=1.0, sy=1.0, rot=0.0, mirrored="false", shape="ShapeBox"):
    return ('<Object type="Core/Diagram.ShapeUsage"><Data property="IsMirrored"><Boolean>%s</Boolean></Data>%s'
            '<Data property="Rotation"><Double>%s</Double></Data><Data property="ScaleX"><Double>%s</Double></Data>'
            '<Data property="ScaleY"><Double>%s</Double></Data><References objects="#%s" property="Shape"/></Object>'
            % (mirrored, points("Position", (x, y)), rot, sx, sy, shape))


def polyline(*pts, stroke=None):
    width = ('<Data property="Stroke"><AggregatedDataValue type="Core/Diagram.Stroke"><Data property="Width"><Double>%s</Double></Data>'
             '</AggregatedDataValue></Data>' % stroke) if stroke else ""
    return '<Object type="Core/Diagram.PolyLine">%s%s</Object>' % (points("Points", *pts), width)


def ellipse(cx, cy, a, b):
    return ('<Object type="Core/Diagram.Ellipse">%s<Data property="HorizontalSemiAxis"><Double>%s</Double></Data>'
            '<Data property="VerticalSemiAxis"><Double>%s</Double></Data></Object>' % (points("Center", (cx, cy)), a, b))


def with_pump(used, primitives=None):
    """펌프 기호를 used로, 새 모양 ShapeBox(기본은 x -4..1, y -1..2인 비대칭 상자)를 목록에 더한 파일."""
    shape = ('<Object id="ShapeBox" type="Core/Diagram.Shape"><Data property="Name"><String>BOX_SHAPE</String></Data>'
             '<Components property="Primitives">%s</Components></Object>' % (primitives or polyline((-4, -1), (1, -1), (1, 2), (-4, 2))))
    return swap('<Components property="Shapes">', '<Components property="Shapes">' + shape, swap(PUMP_SHAPE, used))


def pump(text):
    return next(n for n in extract(text)["nodes"] if n["source_object_id"] == "Pump1")


def box(node):
    g = node["geometry"]
    return None if g is None else [g["x"], g["y"], g["width"], g["height"]]


def line(ex, sid):
    rel = next(r for r in ex["relations"] + ex["unresolved_connectors"] if r["source_object_id"] == sid)
    return [rel["endpoints"][0]["point"]] + rel["waypoints"] + [rel["endpoints"][1]["point"]]


class ReadBoxTest(unittest.TestCase):

    def test_size_and_place_come_from_the_shape_and_its_scales(self):
        node = pump(with_pump(usage(sx=2.0, sy=0.5)))
        self.assertEqual(box(node), [52.0, 119.5, 10.0, 1.5])
        self.assertEqual(node["geometry"]["shape"], {"name": "BOX_SHAPE", "width": 10.0, "height": 1.5, "rotation": 0.0, "mirrored": False})

    def test_right_angles_turn_the_box_clockwise_on_the_sheet(self):
        for rot, want in ((90.0, [58.0, 116.0, 3.0, 5.0]), (180.0, [59.0, 118.0, 5.0, 3.0]), (270.0, [59.0, 119.0, 3.0, 5.0]),
                          (-90.0, [59.0, 119.0, 3.0, 5.0]), (450.0, [58.0, 116.0, 3.0, 5.0])):
            node = pump(with_pump(usage(rot=rot)))
            self.assertEqual(box(node), want, rot)
            self.assertEqual((node["geometry"]["shape"]["rotation"], node["geometry"]["shape"]["width"]), (rot % 360, 5.0))

    def test_mirror_swaps_left_and_right_before_turning(self):
        self.assertEqual(box(pump(with_pump(usage(mirrored="true")))), [59.0, 119.0, 5.0, 3.0])
        node = pump(with_pump(usage(mirrored="true", rot=90.0)))
        self.assertEqual(box(node), [58.0, 119.0, 3.0, 5.0])
        self.assertTrue(node["geometry"]["shape"]["mirrored"])

    def test_other_angles_give_the_box_around_the_turned_shape(self):
        x, _y, w, h = box(pump(with_pump(usage(rot=45.0), polyline((-1, -1), (1, -1), (1, 1), (-1, 1)))))
        self.assertAlmostEqual(w, 2.828, 3)
        self.assertAlmostEqual(h, 2.828, 3)
        self.assertAlmostEqual(x + w / 2, 60.0, 2)

    def test_round_shapes_count_their_radius(self):
        self.assertEqual(box(pump(with_pump(usage(), ellipse(1, 0, 7.5, 2.5)))), [53.5, 117.5, 15.0, 5.0])

    def test_an_arc_counts_only_the_part_that_is_drawn(self):
        arc = ellipse(0, 0, 4, 4).replace("Ellipse", "EllipseArc").replace(
            "</Object>", '<Data property="StartAngle"><Double>270.0</Double></Data><Data property="EndAngle"><Double>90.0</Double></Data></Object>')
        self.assertEqual(box(pump(with_pump(usage(), arc))), [60.0, 116.0, 4.0, 8.0])

    def test_a_symbol_drawn_as_one_stroke_is_as_thick_as_the_stroke(self):
        self.assertEqual(box(pump(with_pump(usage(rot=270.0), polyline((0, -2), (0, 2), stroke=0.4)))), [58.0, 119.8, 4.0, 0.4])

    def test_a_shape_that_cannot_be_measured_leaves_only_the_position(self):
        for text in (with_pump(usage(sx=0.0)), with_pump(usage(sx="nan")), with_pump(usage(sy=-1.0)), with_pump(usage(rot="x")),
                     with_pump(usage(sx=1e308, sy=1e308)), with_pump(usage(shape="ShapeGone")),
                     with_pump(usage(), '<Object type="Core/Diagram.Text"/>'), with_pump(usage(), polyline((1, 1)))):
            ex = extract(text)
            node = next(n for n in ex["nodes"] if n["source_object_id"] == "Pump1")
            self.assertIsNone(node["geometry"])
            self.assertIn(node["local_id"], [x["local_id"] for x in ex["source_locations"]])

    def test_labels_arrows_and_nozzles_are_not_the_symbol(self):
        label = '<Object type="Core/Diagram.Label"><Components property="Elements">%s</Components></Object>' % usage(x=300.0)
        nozzle = ('<Object type="Core/Diagram.RepresentationGroup"><Components property="Groups"><Object type="Core/Diagram.Static">'
                  '<Components property="Elements">%s</Components></Object></Components><References objects="#PumpN1" property="Represents"/>'
                  '</Object>' % usage(x=200.0))
        text = swap('<References objects="#Pump1" property="Represents"/>',
                    '<Components property="Groups">%s</Components><References objects="#Pump1" property="Represents"/>' % (label + nozzle),
                    with_pump(usage()))
        self.assertEqual(box(pump(text)), [56.0, 119.0, 5.0, 3.0])

    def test_two_shapes_of_one_component_share_one_box(self):
        self.assertEqual(box(pump(with_pump(usage() + usage(x=70.0)))), [56.0, 119.0, 15.0, 3.0])

    def test_two_shapes_too_far_apart_to_measure_leave_no_box(self):
        self.assertIsNone(box(pump(with_pump(usage(x=-1.5e308) + usage(x=1.5e308)))))

    def test_a_component_without_a_shape_keeps_no_box(self):
        tank = next(n for n in extract(fixture())["nodes"] if n["source_object_id"] == "Tank1")
        self.assertIsNone(tank["geometry"])

    def test_the_box_is_drawn_in_the_clean_view(self):
        ex = extract(with_pump(usage()))
        shown = [i["tag"] for i in sheet_items.build_items(ex)["items"] if i["layer"] == "symbol"]
        self.assertEqual(shown, ["P-101"])
        self.assertNotIn("dx-Pump1", [u["id"] for u in clean_items.build(ex)["unplaced"]])


class ReadLineTest(unittest.TestCase):

    def test_inner_points_become_the_points_of_the_pipe(self):
        ex = extract(swap(PIPE1_LINE, points("InnerPoints", (70.0, 90.0), (95.0, 90.0)) + PIPE1_LINE))
        self.assertEqual(line(ex, "Pipe1"), [[70.0, 120.0], [70.0, 90.0], [95.0, 90.0], [95.0, 120.0]])

    def test_a_line_drawn_the_other_way_follows_the_connection(self):
        back = points("InnerPoints", (95.0, 90.0), (70.0, 90.0)) + PIPE1_LINE.replace('"Source"', '"S"').replace(
            '"Target"', '"Source"').replace('"S"', '"Target"')
        self.assertEqual(line(extract(swap(PIPE1_LINE, back)), "Pipe1"), [[70.0, 120.0], [70.0, 90.0], [95.0, 90.0], [95.0, 120.0]])

    def test_an_open_end_is_where_the_line_stops(self):
        text = swap(PIPE1_LINE, PIPE1_LINE.replace("#Pos3", "#PosOpen"))
        text = swap('<Object id="Pos1"', '<Object id="PosOpen" type="Plant/Diagram.PipingNodePosition">%s</Object><Object id="Pos1"'
                    % points("Position", (88.0, 120.0)), text)
        text = swap('<References objects="#Valve1" property="TargetItem"/>', "", text)
        text = swap('<References objects="#NV1" property="TargetNode"/>', "", text)
        ex = extract(text)
        self.assertIn("Pipe1", [r["source_object_id"] for r in ex["unresolved_connectors"]])
        self.assertEqual(line(ex, "Pipe1"), [[70.0, 120.0], [88.0, 120.0]])

    def test_a_pipe_cut_by_an_item_the_file_did_not_connect_has_no_borrowed_points(self):
        """길 하나로 그린 선을 부품 앞뒤로 나눌 수 없으면 꺾임점을 어느 쪽에도 주지 않는다."""
        loose = ('<Object id="Valve9" type="Plant/Piping.GateValve"><Components property="Nodes"><Object id="NV9" type='
                 '"Plant/Piping.PipingNode"/><Object id="NV10" type="Plant/Piping.PipingNode"/></Components></Object>')
        text = swap(PIPE1_LINE, points("InnerPoints", (70.0, 90.0)) + PIPE1_LINE, swap('<Object id="Valve1"', loose + '<Object id="Valve1"'))
        ex = extract(text)
        cut = [r for r in ex["relations"] if any(e["source_object_id"] == "Valve9" for e in r["endpoints"])]
        self.assertEqual(len(cut), 2)
        self.assertEqual([r["waypoints"] for r in cut], [[], []])

    def test_a_signal_line_is_read_between_its_two_marks(self):
        marks = "".join('<Object id="%s" type="Plant/Diagram.InstrumentationNodePosition">%s</Object>' % (i, points("Position", p))
                        for i, p in (("Ins1", (100.0, 60.0)), ("Ins2", (100.0, 115.0))))
        group = ('<Object type="Core/Diagram.RepresentationGroup"><Components property="Groups"><Object type="Core/Diagram.Static">'
                 '<Components property="Elements"><Object type="Core/Diagram.ConnectorLine">%s<References objects="#Ins1" property="Source"/>'
                 '<References objects="#Ins2" property="Target"/></Object></Components></Object></Components>'
                 '<References objects="#SC1" property="Represents"/></Object>' % points("InnerPoints", (110.0, 60.0)))
        ex = extract(swap('<Object id="Pos1"', marks + '<Object id="Pos1"', swap(
            '<Object type="Core/Diagram.RepresentationGroup">', group + '<Object type="Core/Diagram.RepresentationGroup">')))
        self.assertEqual(line(ex, "SC1"), [[100.0, 60.0], [110.0, 60.0], [100.0, 115.0]])


class PlaceKeyTest(unittest.TestCase):
    """사람 수정의 지문(at)과 판 이전의 표시가 쓰는 자리(source_locations)는 그림을 읽기 전과 같아야 한다."""

    def test_the_place_used_to_find_a_target_again_does_not_move(self):
        text = swap(PIPE1_LINE, points("InnerPoints", (70.0, 90.0)) + PIPE1_LINE, with_pump(usage(sx=3.0, sy=3.0, rot=90.0)))
        at = {k: v["at"] for k, v in corrections._fingerprints(extract(text)).items()}
        self.assertEqual((at["Pump1"], at["Valve1"], at["Tank1"], at["Pipe1"], at["Pipe2"]),
                         ([60, 120], [100, 120], [190, 120], [82, 120], [120, 120]))


@unittest.skipUnless(SAMPLES and os.path.isdir(SAMPLES), "HAZOP_DEXPI_SAMPLES(공개 예제 폴더)가 없어 건너뜀")
class PublicPictureTest(unittest.TestCase):

    def test_every_symbol_of_the_reference_drawing_has_a_box_and_is_drawn(self):
        with open(os.path.join(SAMPLES, "dexpi-2.0.1", "reference_pid.xml"), "rb") as fh:
            ex = dexpi_import.extract_bytes(fh.read(), "reference_pid.xml")[0]
        self.assertEqual((len(ex["nodes"]), sum(1 for n in ex["nodes"] if n["geometry"])), (30, 30))
        tank = next(n for n in ex["nodes"] if n["source_object_id"] == "Tank1")
        self.assertEqual(box(tank), [179.0, 73.5, 30.0, 51.0])  # 접시형 머리의 호까지
        psv = next(n for n in ex["nodes"] if n["kind"] == "psv")
        self.assertEqual(box(psv), [267.0, 89.0, 3.0, 7.0])  # 뒤집힌 각형 안전밸브: 출구가 왼쪽
        self.assertEqual(len([i for i in sheet_items.build_items(ex)["items"] if i["layer"] == "symbol"]), 30)
        clean = clean_items.build(ex)
        self.assertEqual([u for u in clean["unplaced"] if u["kind"] == "node"], [])
        bent = [r for r in ex["relations"] + ex["unresolved_connectors"] if r["waypoints"]]
        self.assertEqual(len(bent), 10)


if __name__ == "__main__":
    unittest.main()
