"""DEXPI 가져오기의 규칙 시험(HZ-PLN-22 §5.2~§5.7): 구간 안 부품이 길에서 빠지지 않는다, 한 방향·양방향 구분, 위치 없는 것, 틀 검사 표가
참고 자료 XSD와 같다, 경로 ID. 손으로 만든 작은 파일(tests/fixtures/dexpi/)을 바탕으로 문자열을 고쳐 만든다.
실행: python -m unittest tests.test_dexpi_rules
"""

import json
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_read  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def extract(data):
    return dexpi_import.extract_bytes(data, "x.xml")[0]


def pairs(ex):
    label = {n["local_id"]: n["tag"] or str(n["kind"]) for n in ex["nodes"]}
    return sorted((label[r["endpoints"][0]["node_local_id"]], label[r["endpoints"][1]["node_local_id"]])
                  for r in ex["relations"] if r["kind"] == "physical_connection")


PROTEUS_VALVES = """<PipingNetworkSegment ID="Seg-2" ComponentClass="PipingNetworkSegment">
      <PipingComponent ID="Valve-2" ComponentClass="GateValve"><ConnectionPoints NumPoints="2"><Node ID="NW1"/><Node ID="NW2"/></ConnectionPoints>
        <GenericAttributes Set="DexpiAttributes" Number="1"><GenericAttribute Name="PipingComponentNumberAssignmentClass" Format="string" Value="V-102"/></GenericAttributes></PipingComponent>
      <PipingComponent ID="Valve-3" ComponentClass="GlobeValve"><ConnectionPoints NumPoints="2"><Node ID="NX1"/><Node ID="NX2"/></ConnectionPoints>
        <GenericAttributes Set="DexpiAttributes" Number="1"><GenericAttribute Name="PipingComponentNumberAssignmentClass" Format="string" Value="V-103"/></GenericAttributes></PipingComponent>"""

DEXPI2_LOOSE_VALVE = """<Components property="Items">
                  <Object id="Valve9" type="Plant/Piping.GateValve">
                    <Components property="Nodes"><Object id="NV9" type="Plant/Piping.PipingNode"/><Object id="NV10" type="Plant/Piping.PipingNode"/></Components>
                    <Data property="PipingComponentNumber"><String>V-109</String></Data>
                  </Object>"""


class SegmentPathTest(unittest.TestCase):
    """§5.7: Proteus는 `FromID → 구간 안 부품(문서 순서) → ToID`, 2.0은 연결 하나 = 관계 하나."""

    def test_proteus_segment_with_one_connection_walks_the_items_in_document_order(self):
        text = fixture("small-pid-proteus.xml").decode("utf-8")
        text = text.replace('<PipingNetworkSegment ID="Seg-2" ComponentClass="PipingNetworkSegment">', PROTEUS_VALVES, 1)
        ex = extract(text.encode("utf-8"))
        got = pairs(ex)
        self.assertIn(("M-101", "V-102"), got)
        self.assertIn(("V-102", "V-103"), got)
        self.assertIn(("V-103", "T-101"), got)
        self.assertNotIn(("M-101", "T-101"), got)  # 구간 안 부품을 건너뛴 연결은 없다
        self.assertEqual([u for u in ex["validation"]["unknowns"] if u["check"] == "dexpi_item_order_assumed"], [])
        seg2 = [r for r in ex["relations"] if r["attributes"].get("dexpi:segment") == "Seg-2"]
        self.assertEqual(sorted(r["attributes"]["dexpi:segment_order"] for r in seg2), ["0", "1", "2"])
        self.assertEqual({r["line_no"] for r in seg2}, {"L-200"})  # 길 안 모든 관계가 구간의 선 속성을 복사
        first = [r for r in seg2 if r["attributes"]["dexpi:segment_order"] == "0"][0]
        self.assertEqual(first["endpoints"][0]["attributes"], {"dexpi:node": "1"})  # FromNode는 끝점에 남긴다

    def test_proteus_loose_item_in_a_multi_connection_segment_is_assumed_and_flagged(self):
        text = fixture("small-pid-proteus.xml").decode("utf-8")
        text = text.replace('<Connection FromID="Valve-1" FromNode="2" ToID="Tee-1" ToNode="1"/>\n      ', "")
        ex = extract(text.encode("utf-8"))
        got = pairs(ex)
        self.assertIn(("tee", "V-101"), got)  # 연결 끝에 없는 밸브는 문서 순서로 가장 가까운 연결 위에 끼운다
        self.assertIn(("V-101", "T-101"), got)
        flagged = [u for u in ex["validation"]["unknowns"] if u["check"] == "dexpi_item_order_assumed"]
        self.assertEqual([(u["source_object_id"], u["field"]) for u in flagged], [("Valve-1", "kind")])

    def test_dexpi2_item_without_a_connection_is_inserted_in_items_order_and_flagged(self):
        text = fixture("small-pid-dexpi2.xml").decode("utf-8").replace('<Components property="Items">', DEXPI2_LOOSE_VALVE, 1)
        ex = extract(text.encode("utf-8"))
        flagged = [u["source_object_id"] for u in ex["validation"]["unknowns"] if u["check"] == "dexpi_item_order_assumed"]
        self.assertEqual(flagged, ["Valve9"])
        self.assertTrue(any("V-109" in pair for pair in pairs(ex)))

    def test_dexpi2_explicit_connections_are_not_split(self):
        ex = extract(fixture("small-pid-dexpi2.xml"))
        self.assertEqual([u for u in ex["validation"]["unknowns"] if u["check"] == "dexpi_item_order_assumed"], [])
        self.assertEqual(len([r for r in ex["relations"] if r["kind"] == "physical_connection"]), 5)

    def test_open_end_goes_to_unresolved(self):
        text = fixture("small-pid-proteus.xml").decode("utf-8")
        text = text.replace('<Connection FromID="Mixer-N1" FromNode="1" ToID="Tank-N2" ToNode="1"/>', '<Connection ToID="Tank-N2" ToNode="1"/>')
        self.assertEqual(len(extract(text.encode("utf-8"))["unresolved_connectors"]), 1)


class FlowClassAndPositionTest(unittest.TestCase):

    def test_flow_direction_class_is_kept_but_no_direction_is_made_up(self):
        text = fixture("small-pid-dexpi2.xml").decode("utf-8").replace(
            '<Data property="NominalDiameterRepresentation"><String>DN 80</String></Data>',
            '<Data property="NominalDiameterRepresentation"><String>DN 80</String></Data>\n'
            '<Data property="FlowDirection"><DataReference data="Plant/Enumerations.PipingNetworkSegmentFlowClassification.'
            'DualFlowPipingNetworkSegment"/></Data>', 1)
        ex = extract(text.encode("utf-8"))
        main = [r for r in ex["relations"] if r["line_no"] == "L-100"]
        self.assertEqual({r["attributes"]["flow_class"] for r in main}, {"dual"})
        self.assertNotIn("dexpi:FlowDirection", main[0]["attributes"])
        dual = [u for u in ex["validation"]["unknowns"] if u["check"] == "unknown_flow_direction" and "양방향" in u["reason"]]
        self.assertGreaterEqual(len(dual), 1)
        single = extract(text.replace("DualFlowPipingNetworkSegment", "SingleFlowPipingNetworkSegment").encode("utf-8"))
        self.assertEqual({r["attributes"]["flow_class"] for r in single["relations"] if r["line_no"] == "L-100"}, {"single"})

    def test_objects_without_a_position_are_kept_and_flagged(self):
        text = fixture("small-pid-dexpi2.xml").decode("utf-8")
        a, b = text.index('<Components property="Diagram">'), text.index('<Components property="ShapeCatalogues">')
        ex = extract((text[:a] + text[b:]).encode("utf-8"))
        flagged = [u for u in ex["validation"]["unknowns"] if u["check"] == "dexpi_no_position"]
        self.assertEqual({u["field"] for u in flagged}, {"bbox"})
        self.assertEqual(len(flagged), len(ex["nodes"]) + len(ex["relations"]) + 1)  # 구성요소·관계마다 하나, 그림이 없다는 안내 하나
        self.assertEqual(ex["source_locations"], [])
        self.assertEqual(len(ex["nodes"]), 7)  # 버리지 않는다


class StructureTableTest(unittest.TestCase):
    """틀 검사 표(dexpi_read.STRUCTURE)가 참고 자료 XSD의 요소·속성과 같다(§5.6, §8.1 X1)."""

    XSD = paths.folder("references", "dexpi-schema", "dexpi-xml-schema-2-0-1.xsd")
    NS = "{http://www.w3.org/2001/XMLSchema}"

    def load(self):
        # 참고 자료 XSD는 이름 패턴을 내부 개체로 정의한다. 저장소 안 파일이므로 내부 개체만 푸는 기본 파서로 연다(외부 개체·네트워크 없음).
        # 앱의 안전한 읽기(parse_safely)는 이런 파일을 거절하는 것이 맞다.
        with open(self.XSD, "rb") as fh:
            data = fh.read()
        with self.assertRaises(dexpi_read.DexpiError):
            dexpi_read.parse_safely(data)
        return ET.fromstring(data)

    def test_table_matches_the_xsd(self):
        types = {t.get("name"): t for t in self.load().findall(self.NS + "complexType")}
        for name, rule in dexpi_read.STRUCTURE.items():
            t = types[name]
            self.assertEqual(sorted(e.get("name") for e in t.iter(self.NS + "element")), sorted(rule["children"]), name)
            attrs = t.findall(self.NS + "attribute")
            self.assertEqual(sorted(a.get("name") for a in attrs), sorted(rule["attributes"]), name)
            self.assertEqual(sorted(a.get("name") for a in attrs if a.get("use") == "required"), sorted(rule["required"]), name)

    def test_id_pattern_is_the_one_in_the_xsd(self):
        with open(self.XSD, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('<!ENTITY leading-identifier-char "[A-Za-z_]">', text)
        self.assertIn('<!ENTITY following-identifier-char "[A-Za-z_0-9]">', text)

    def test_checker_flags_breaks(self):
        good = dexpi_read.parse_safely(fixture("small-pid-dexpi2.xml"))
        self.assertEqual(dexpi_read.check_structure(good), [])
        for old, new, word in (('<Object type="Core/EngineeringModel">', "<Object>", "type"),
                               ('<Import prefix="Core"', '<Import prefix="Co-re"', "prefix"),
                               ('id="Pump1"', 'id="Pump-1"', "id"), ("<Double>16.0</Double>", "<Double>abc</Double>", "Double"),
                               ('<References objects="#Valve1" property="TargetItem"/>',
                                '<References objects="Valve1" property="TargetItem"/>', "objects"),
                               ("</Model>", "<Bogus/></Model>", "Bogus")):
            text = fixture("small-pid-dexpi2.xml").decode("utf-8").replace(old, new, 1)
            problems = dexpi_read.check_structure(dexpi_read.parse_safely(text.encode("utf-8")))
            self.assertTrue(any(word in x for x in problems), (word, problems))


class IdTest(unittest.TestCase):

    def test_objects_without_an_id_get_double_underscore_path_ids(self):
        text = fixture("small-pid-dexpi2.xml").decode("utf-8").replace('<Object id="PIF1" type=', "<Object type=", 1).replace("#PIF1", "#Gone")
        model = dexpi_read.read(text.encode("utf-8"))
        self.assertEqual([i for i in model.items if "__" in i], ["PlantModel1__ProcessInstrumentationFunctions_0"])
        self.assertTrue(all(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", i) for i in model.items))
        again = dexpi_read.read(text.encode("utf-8"))
        self.assertEqual(list(model.items), list(again.items))  # 같은 파일이면 늘 같은 값


if __name__ == "__main__":
    unittest.main()
