"""DEXPI 가져오기 검토 1회(총괄 판정 4건 차단)의 재현 시험: ① 화살표를 배관의 실제 경로와 견준다 ② 처리하지 않는 요소를 흔적 없이 버리지 않는다
③ 한도 안 파일에서 읽는 시간이 선형이고 등록에서 한 번만 읽는다 ④ 같은 도면 번호의 다른 형식 원본(→ tests/test_drawing_sources.py).
고치기 전에는 모두 실패하는 시험이다.
실행: python -m unittest tests.test_dexpi_review_fixes
"""

import json
import os
import sys
import time
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.extract.adapters import dexpi_import, dexpi_read  # noqa: E402
from hazop.register import fileinfo  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi")
SAMPLES = os.environ.get("HAZOP_DEXPI_SAMPLES")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read().decode("utf-8")


def extract(text):
    return dexpi_import.extract_bytes(text.encode("utf-8"), "x.xml")[0]


def flows(ex):
    label = {n["local_id"]: n["tag"] or str(n["kind"]) for n in ex["nodes"]}
    return {(label[r["flow_direction"]["from"]], label[r["flow_direction"]["to"]]): r["flow_direction"]["basis"]
            for r in ex["relations"] if r["flow_direction"]}


# 2.0: 펌프 -> 밸브 연결을 위로 올라갔다 내려오는 ㄷ자 경로로 바꾸고(시작 (70,120), 안쪽 (70,40)·(95,40), 끝 (95,120)) 화살표를 끝 쪽 세로 선분에 둔다
U_LINE = """<Object type="Core/Diagram.ConnectorLine">
                    <Data property="InnerPoints">
                      <AggregatedDataValue type="Core/Diagram.Point"><Data property="X"><Double>70.0</Double></Data><Data property="Y"><Double>40.0</Double></Data></AggregatedDataValue>
                      <AggregatedDataValue type="Core/Diagram.Point"><Data property="X"><Double>95.0</Double></Data><Data property="Y"><Double>40.0</Double></Data></AggregatedDataValue>
                    </Data>
                    <References objects="#Pos2" property="Source"/>
                    <References objects="#Pos3" property="Target"/>
                  </Object>"""
PLAIN_LINE = """<Object type="Core/Diagram.ConnectorLine">
                    <References objects="#Pos2" property="Source"/>
                    <References objects="#Pos3" property="Target"/>
                  </Object>"""
ARROW_AT = '<Data property="X"><Double>82.0</Double></Data><Data property="Y"><Double>120.0</Double></Data>'


def with_arrow(x, y, rotation):
    text = fixture("small-pid-dexpi2.xml").replace(PLAIN_LINE, U_LINE, 1)
    text = text.replace(ARROW_AT, '<Data property="X"><Double>%s</Double></Data><Data property="Y"><Double>%s</Double></Data>' % (x, y), 1)
    return text.replace('<Data property="Rotation"><Double>0.0</Double></Data>', '<Data property="Rotation"><Double>%s</Double></Data>' % rotation, 1)


class ArrowAgainstTheRealPathTest(unittest.TestCase):

    def test_arrow_on_the_last_leg_pointing_down_is_forward_along_the_path(self):
        """경로는 펌프에서 위로 올라갔다 밸브로 내려온다. 끝 쪽 세로 선분의 아래 화살표는 경로를 따라 가는 흐름(펌프 -> 밸브)이다.
        양 끝을 잇는 직선(가로)으로는 방향을 정할 수 없다."""
        ex = extract(with_arrow(95.0, 80.0, 90.0))
        self.assertEqual(flows(ex).get(("P-101", "V-101")), "dexpi_flow_arrow")

    def test_arrow_pointing_up_on_the_last_leg_is_backward_along_the_path(self):
        ex = extract(with_arrow(95.0, 80.0, 270.0))
        self.assertEqual(flows(ex).get(("V-101", "P-101")), "dexpi_flow_arrow")
        self.assertNotIn(("P-101", "V-101"), flows(ex))

    def test_arrow_far_from_every_path_is_not_attached(self):
        ex = extract(with_arrow(82.0, 60.0, 0.0))
        self.assertNotIn(("P-101", "V-101"), flows(ex))
        self.assertNotIn(("V-101", "P-101"), flows(ex))
        self.assertIn("dexpi_flow_arrow_unplaced", [u["check"] for u in ex["validation"]["unknowns"]])

    def test_arrow_across_the_leg_is_not_attached(self):
        ex = extract(with_arrow(95.0, 80.0, 0.0))  # 오른쪽을 가리키는 화살표가 세로 선분 위에 있다: 방향이 맞지 않음
        self.assertFalse([k for k in flows(ex) if "P-101" in k and "V-101" in k])

    def test_arrow_equally_near_two_paths_is_not_attached(self):
        arrow = {"position": (0.0, 0.0), "direction": (1.0, 0.0)}
        up, down = [(-5.0, 1.0), (5.0, 1.0)], [(5.0, -1.0), (-5.0, -1.0)]
        self.assertIsNone(dexpi_import.match_arrow(arrow, [(up, [0]), (down, [1])]))
        self.assertEqual(dexpi_import.match_arrow(arrow, [(up, [0]), ([(-5.0, 9.0), (5.0, 9.0)], [1])]), ("forward", [0]))
        self.assertIsNone(dexpi_import.match_arrow({"position": (0.0, 3.0), "direction": (1.0, 0.0)}, [(up, [0])]))  # 거리 한도(1.5mm)

    def test_proteus_arrow_follows_the_segment_center_line(self):
        text = fixture("small-pid-proteus.xml").replace(
            '<Coordinate X="70" Y="177"/><Coordinate X="95" Y="177"/>',
            '<Coordinate X="70" Y="177"/><Coordinate X="70" Y="257"/><Coordinate X="95" Y="257"/><Coordinate X="95" Y="177"/>', 1)
        text = text.replace('<Location X="82" Y="177" Z="0"/><Axis X="0" Y="0" Z="1"/><Reference X="1" Y="0" Z="0"/>',
                            '<Location X="95" Y="217" Z="0"/><Axis X="0" Y="0" Z="1"/><Reference X="0" Y="1" Z="0"/>', 1)
        ex = extract(text)  # Proteus는 y가 위로 커서 (0, 1)은 화면에서 위쪽: 끝 쪽 선분(아래로 내려옴)과 반대
        self.assertEqual(flows(ex).get(("V-101", "P-101")), "dexpi_flow_arrow")

    @unittest.skipUnless(SAMPLES and os.path.isdir(SAMPLES), "HAZOP_DEXPI_SAMPLES가 없어 건너뜀")
    def test_public_example_segment_3_flows_from_the_valve_to_the_tank(self):
        for path, valve, tank in ((("dexpi-2.0.1", "reference_pid.xml"), "GlobeValve2", "Tank1"),
                                  (("dexpi-1.3", "C01V04-VER.EX01.xml"), "GlobeValve-2", "Tank-1")):
            with open(os.path.join(SAMPLES, *path), "rb") as fh:
                ex = dexpi_import.extract_bytes(fh.read(), "x.xml")[0]
            pairs = {(r["flow_direction"]["from"], r["flow_direction"]["to"]) for r in ex["relations"] if r["flow_direction"]}
            self.assertIn(("dx-" + valve, "dx-" + tank), pairs, path)
            self.assertNotIn(("dx-" + tank, "dx-" + valve), pairs, path)


PROTEUS = fixture("small-pid-proteus.xml")
D2 = fixture("small-pid-dexpi2.xml")


class NothingIsDroppedTest(unittest.TestCase):

    def test_top_level_unknown_equipment_class_becomes_an_unclassified_node(self):
        text = D2.replace('<Components property="MetaData">', '<Components property="TaggedPlantItems"><Object id="Reactor9" type="Plant/ProcessEquipment.NuclearReactor">'
                          '<Data property="TagName"><String>RV-1</String></Data></Object></Components><Components property="MetaData">', 1)
        ex = extract(text)
        node = [n for n in ex["nodes"] if n["source_object_id"] == "Reactor9"][0]
        self.assertEqual((node["kind"], node["classification"], node["tag"]), (None, "unclassified", "RV-1"))
        self.assertIn("dexpi_unmapped_class", [u["check"] for u in ex["validation"]["unknowns"] if u["source_object_id"] == "Reactor9"])

    def test_objects_without_a_place_in_the_graph_are_counted_by_kind(self):
        text = D2.replace('<Components property="MetaData">', '<Components property="InstrumentationLoopFunctions">'
                          '<Object id="Loop9" type="Plant/Instrumentation.InstrumentationLoopFunction"/><Object id="Loop8" type="Plant/Instrumentation.InstrumentationLoopFunction"/>'
                          '</Components><Components property="MetaData">', 1)
        ex = extract(text)
        self.assertEqual(ex["run"]["dexpi"]["not_imported"], {"Plant/Instrumentation.InstrumentationLoopFunction": 2})
        left = [u for u in ex["validation"]["unknowns"] if u["check"] == "dexpi_not_imported"]
        self.assertEqual(len(left), 1)
        self.assertIn("InstrumentationLoopFunction 2개", left[0]["reason"])

    def test_proteus_top_level_unknown_element_is_counted(self):
        text = PROTEUS.replace('<Equipment ID="Tank-1"', '<InstrumentComponent ID="Inst-9" ComponentClass="Transmitter"/><Equipment ID="Tank-1"', 1)
        ex = extract(text)
        self.assertEqual(ex["run"]["dexpi"]["not_imported"], {"Transmitter": 1})

    def test_proteus_inline_element_stays_on_the_path_and_the_neighbours_are_not_joined(self):
        text = PROTEUS.replace('<Connection FromID="Mixer-N1"', '<ProcessInstrument ID="FE-9" ComponentClass="FlowMeasuringElement">'
                               '<ConnectionPoints NumPoints="2"><Node ID="Q1"/><Node ID="Q2"/></ConnectionPoints></ProcessInstrument>'
                               '<Connection FromID="Mixer-N1"', 1)
        ex = extract(text)
        label = {n["local_id"]: n["tag"] or n["source_object_id"] for n in ex["nodes"]}
        pairs = sorted((label[r["endpoints"][0]["node_local_id"]], label[r["endpoints"][1]["node_local_id"]])
                       for r in ex["relations"] if r["kind"] == "physical_connection")
        self.assertIn(("M-101", "FE-9"), pairs)
        self.assertIn(("FE-9", "T-101"), pairs)
        self.assertNotIn(("M-101", "T-101"), pairs)
        node = [n for n in ex["nodes"] if n["source_object_id"] == "FE-9"][0]
        self.assertEqual(node["classification"], "unclassified")

    def test_proteus_inline_component_without_an_id_gets_a_path_id(self):
        text = PROTEUS.replace('<Connection FromID="Mixer-N1"', '<PipingComponent ComponentClass="GateValve"><ConnectionPoints NumPoints="2"><Node/><Node/></ConnectionPoints></PipingComponent>'
                               '<Connection FromID="Mixer-N1"', 1)
        ex = extract(text)
        made = [n for n in ex["nodes"] if "__item_" in n["source_object_id"]]
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["kind"], "manual_valve")
        self.assertIn("dexpi_item_without_id", [u["check"] for u in ex["validation"]["unknowns"]])
        self.assertEqual(len([r for r in ex["relations"] if r["attributes"].get("dexpi:segment") == "Seg-2"]), 2)


class VersionAndTagTest(unittest.TestCase):
    """경미 지적: 판 판별(섞인 판·모르는 판·Proteus에서 CAD 버전), 같은 태그."""

    def checks(self, ex):
        return [u["check"] for u in ex["validation"]["unknowns"]]

    def test_mixed_core_and_plant_versions_are_reported(self):
        text = D2.replace("models/2.0.1/Core.xml", "models/2.0.0/Core.xml", 1)
        ex = extract(text)
        self.assertIn("dexpi_version_mixed", self.checks(ex))
        self.assertEqual(ex["source"]["dexpi_version"], "2.0.1")  # Plant 판을 DEXPI 판으로 본다

    def test_unknown_version_is_read_with_the_known_class_list_and_flagged(self):
        ex = extract(D2.replace("models/2.0.1/Plant.xml", "models/9.9/Plant.xml", 1).replace("models/2.0.1/Core.xml", "models/9.9/Core.xml", 1))
        self.assertEqual(ex["source"]["dexpi_version"], "9.9")
        self.assertIn("dexpi_version_unknown", self.checks(ex))

    def test_a_foreign_import_address_is_not_a_dexpi_version(self):
        text = D2.replace("https://data.dexpi.org/models/2.0.1/Plant.xml", "https://evil.example/models/2.0.1/Plant.xml", 1) \
                 .replace("https://data.dexpi.org/models/2.0.1/Core.xml", "https://evil.example/models/2.0.1/Core.xml", 1)
        with self.assertRaises(dexpi_read.DexpiError) as cm:
            dexpi_read.read(text.encode("utf-8"))
        self.assertEqual(cm.exception.code, "dexpi_unknown_format")

    def test_proteus_cad_version_is_not_the_dexpi_version(self):
        text = PROTEUS.replace('Application="Dexpi" ApplicationVersion="1.3.1"', 'Application="SmartPlant P&amp;ID" ApplicationVersion="09.00.12"', 1)
        ex = extract(text)
        self.assertIsNone(ex["source"]["dexpi_version"])
        self.assertEqual(ex["run"]["dexpi"]["application"]["version"], "09.00.12")
        self.assertIn("dexpi_version_unknown", self.checks(ex))

    def test_duplicate_tags_are_kept_apart_and_flagged(self):
        ex = extract(PROTEUS.replace('Value="M-101"', 'Value="P-101"', 1))
        dup = [u for u in ex["validation"]["unknowns"] if u["check"] == "dexpi_tag_not_unique"]
        self.assertEqual(sorted(u["source_object_id"] for u in dup), ["Mixer-1", "Pump-1"])
        self.assertEqual(len([n for n in ex["nodes"] if n["tag"] == "P-101"]), 2)  # 합치지 않는다


def chain(n):
    parts = [b'<PlantModel><PlantInformation Application="Dexpi" ApplicationVersion="1.3.1" SchemaVersion="4.1.1" Units="mm"/>',
             b'<PipingNetworkSystem ID="S"><PipingNetworkSegment ID="G">']
    for i in range(n):
        parts.append(b'<PipingComponent ID="V%d" ComponentClass="GateValve"><ConnectionPoints NumPoints="2"><Node ID="A%d"/><Node ID="B%d"/></ConnectionPoints></PipingComponent>' % (i, i, i))
    for i in range(n - 1):
        parts.append(b'<Connection FromID="V%d" FromNode="2" ToID="V%d" ToNode="1"/>' % (i, i + 1))
    parts.append(b'</PipingNetworkSegment></PipingNetworkSystem></PlantModel>')
    return b"".join(parts)


class LinearTimeTest(unittest.TestCase):

    def run_time(self, n):
        data = chain(n)
        start = time.perf_counter()
        model = dexpi_read.read(data)
        ex = dexpi_import.build(model, {"file": "x", "sha256": "0" * 64})
        elapsed = time.perf_counter() - start
        self.assertEqual(ex["summary"]["relations"], n - 1)
        return elapsed

    def test_read_and_build_grow_linearly(self):
        small, big = min(self.run_time(3000) for _ in range(2)), min(self.run_time(12000) for _ in range(2))
        self.assertLess(big / max(small, 0.02), 7.0, "읽기·변환 시간이 N^2로 늘어남(3000개 %.2fs, 12000개 %.2fs)" % (small, big))
        self.assertLess(big, 8.0)

    def test_registration_parses_the_file_once(self):
        data = chain(50)
        with mock.patch.object(dexpi_read, "parse_safely", wraps=dexpi_read.parse_safely) as parse:
            info = fileinfo.inspect("a.xml", data)
        self.assertEqual(info["blockers"], [])
        self.assertEqual(parse.call_count, 1)
        data2 = D2.encode("utf-8")
        with mock.patch.object(dexpi_read, "parse_safely", wraps=dexpi_read.parse_safely) as parse:
            info = fileinfo.inspect("a.xml", data2)
        self.assertEqual((info["blockers"], info["dexpi_flavor"]), ([], "dexpi_xml"))
        self.assertEqual(parse.call_count, 1)


if __name__ == "__main__":
    unittest.main()
