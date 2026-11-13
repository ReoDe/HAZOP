"""DEXPI 내보내기(HZ-PLN-22 §6·§7, 단위 X2) 시험: hazop/export/dexpi_export.py, 되읽기(dexpi_import.apply_sidecar), scripts/export_dexpi.py.

입력은 가상 도면 SNP 6세트(drawio)와 손으로 만든 작은 DEXPI 파일(tests/fixtures/dexpi/)이다. 공개 예제는 HAZOP_DEXPI_SAMPLES가
가리키는 폴더에 있을 때만 돈다(CC BY 4.0, licenses/dexpi/NOTICE.md).
실행: python -m unittest tests.test_dexpi_export
"""

import copy
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import export_dexpi  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.export import dexpi_export as de  # noqa: E402
from hazop.extract import dexpi_map, drawio  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_read  # noqa: E402
from hazop.graph import build  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi")
SAMPLES = os.environ.get("HAZOP_DEXPI_SAMPLES")
SNP = sorted(glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio")))


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def snp_pair(path):
    ex = drawio.extract(path, repo_root=REPO_ROOT)
    return ex, build.build_graph(ex)


def dexpi_pair(name):
    ex = dexpi_import.extract_bytes(fixture(name), name)[0]
    return ex, build.build_graph(ex)


def export(pair):
    ex, g = pair
    return de.export_drawing(g, ex, require_confirmed_number=False)


def reimport(exp, with_sidecar=True):
    return dexpi_import.extract_bytes(exp.xml, exp.name + ".dexpi.xml", sidecar=exp.sidecar if with_sidecar else None)[0]


def tag_pairs(ex):
    """연결을 (종류, 정렬한 끝 태그 쌍, 선 번호)로. 태그 없는 노드는 kind로 대신한다."""
    label = {n["local_id"]: n["tag"] or str(n["kind"]) for n in ex["nodes"]}
    out = []
    for r in ex["relations"]:
        ends = tuple(sorted(label[e["node_local_id"]] for e in r["endpoints"]))
        out.append((r["kind"], ends, r["attributes"].get("line_no")))
    return sorted(out, key=str)


class SnpExportTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pairs = {os.path.basename(os.path.dirname(p)).split("_")[0]: snp_pair(p) for p in SNP}
        cls.exports = {k: export(v) for k, v in cls.pairs.items()}

    def each(self):
        for key in sorted(self.pairs):
            with self.subTest(drawing=key):
                yield key, self.pairs[key], self.exports[key]

    def test_every_sample_passes_the_checks_in_6_5(self):
        self.assertEqual(sorted(self.exports), ["SNP-M-101", "SNP-M-102", "SNP-M-201", "SNP-M-301", "SNP-M-401", "SNP-M-501"])
        for _, (ex, g), exp in self.each():
            root = dexpi_read.parse_safely(exp.xml)
            self.assertEqual(dexpi_read.check_structure(root), [])
            self.assertEqual(dexpi_read.check_references(root), [])
            self.assertTrue(all(dexpi_map.type_is_known(o.get("type")) for o in root.iter("Object")))

    def test_counts_match_an_independent_count_of_the_graph(self):
        for _, (ex, g), exp in self.each():
            nodes = [n for n in g["nodes"] if n["node_type"] == "drawing_object"]
            gone = [n for n in nodes if n["kind"] is None or n["kind"] in dexpi_map.EXPORT_NONE]
            kept = {n["entity_id"] for n in nodes} - {n["entity_id"] for n in gone}
            segs = {}
            for e in g["edges"]:
                if e["kind"] == "has_endpoint":
                    segs.setdefault(e["segment"], []).append(e["node"])
            lost = [s for s, ns in segs.items() if any(x not in kept for x in ns)]
            self.assertEqual(exp.stats["components"], len(kept))
            self.assertEqual(exp.stats["excluded_components"], len(gone))
            self.assertEqual(exp.stats["connections"], len(segs) - len(lost))
            self.assertEqual(sorted(x["entity_id"] for x in exp.excluded["excluded_components"]),
                             sorted(n["entity_id"] for n in gone))
            self.assertEqual(sorted(x["entity_id"] for x in exp.excluded["excluded_connections"] if x["reason"] == "endpoint_excluded"),
                             sorted(lost))

    def test_generated_nozzle_names_are_listed_as_approximations(self):
        """포트가 없는 설비 끝마다 연결 순서대로 N1, N2…를 붙이고 근사 목록에 적는다(§3.3). 센 방법: 그래프에서 따로."""
        for _, (ex, g), exp in self.each():
            nodes = {n["entity_id"]: n for n in g["nodes"] if n["node_type"] == "drawing_object"}
            kept = {e for e, n in nodes.items() if n["kind"] is not None and n["kind"] not in dexpi_map.EXPORT_NONE}
            ends = {}
            for e in g["edges"]:
                if e["kind"] == "has_endpoint":
                    ends.setdefault(e["segment"], []).append(e)
            want = {}
            for seg, pair in ends.items():
                if all(x["node"] in kept for x in pair):
                    for x in pair:
                        if nodes[x["node"]]["category"] == "equipment" and x["port"] is None:
                            want[x["node"]] = want.get(x["node"], 0) + 1
            got = {}
            for a in exp.excluded["approximations"]:
                if a["reason"] == "nozzle_name_generated":
                    got[a["entity_id"]] = got.get(a["entity_id"], 0) + 1
            self.assertEqual(got, want)
            self.assertGreater(len(want), 0)

    def test_unresolved_and_unsupported_items_are_listed_not_guessed(self):
        for _, (ex, g), exp in self.each():
            reasons = {x["reason"] for x in exp.excluded["excluded_connections"]}
            self.assertLessEqual(reasons, {"endpoint_excluded", "sensing_location_not_piping_component", "unresolved_connector",
                                           "signal_end_not_instrument_or_actuator", "bad_endpoint_count"})
            self.assertEqual(len([x for x in exp.excluded["excluded_connections"] if x["reason"] == "unresolved_connector"]),
                             len(g["unresolved"]))

    def test_no_unknown_marker_inside_the_dexpi_file(self):
        """DEXPI 파일 안에는 미확인 표시나 우리 확장 이름이 없다(V-2·V-6). 속성이 없는 자리는 비워 둔다."""
        for _, _, exp in self.each():
            text = exp.xml.decode("utf-8")
            for word in ("unknown", "미확인", "ClassExtension", "HAZOP", "origin", "human_edit"):
                self.assertNotIn(word, text)

    def test_fail_position_becomes_fail_action_and_unknown_one_is_left_out(self):
        for _, (ex, g), exp in self.each():
            valves = [n for n in g["nodes"] if n["kind"] in dexpi_map.ACTUATED_KINDS]
            root = dexpi_read.parse_safely(exp.xml)
            actions = [d for o in root.iter("Object") if o.get("type") == "Plant/Instrumentation.ControlledActuator"
                       for d in o.findall("Data") if d.get("property") == "FailAction"]
            want = [n for n in valves if n["attributes"].get("fail_position") in dexpi_map.FAIL_ACTION_BACK]
            self.assertEqual(len(actions), len(want))
            self.assertLessEqual(len(actions), len(valves))

    def test_same_input_gives_same_bytes(self):
        for key, pair, exp in self.each():
            again = export(snp_pair(SNP[sorted(self.pairs).index(key)]))
            self.assertEqual(again.xml, exp.xml)
            self.assertEqual(again.files, exp.files)

    def test_roundtrip_keeps_components_connections_and_original_kinds(self):
        """§7.3: 내보내고 다시 가져오면 구성요소 수·kind(근사는 곁 파일로)·태그·연결 끝·선 번호·도면 연결 참조가 같다."""
        for _, (ex, g), exp in self.each():
            back = reimport(exp)
            self.assertEqual(back["validation"]["status"], "passed")
            by_entity = {s["entity_id"]: s for s in exp.sidecar["entities"]}
            self.assertEqual(len(back["nodes"]), len(by_entity))
            kept = [n for n in g["nodes"] if n["entity_id"] in by_entity]
            self.assertEqual(sorted(str(n["kind"]) for n in back["nodes"]), sorted(str(n["kind"]) for n in kept))
            self.assertEqual(sorted(n["tag"] or "" for n in back["nodes"] if n["category"] != "instrument" and n["kind"] != "continuation"),
                             sorted(n["tag"] or "" for n in kept if n["category"] != "instrument" and n["kind"] != "continuation"))
            # 연결 끝: 원래 그래프에서 같은 방법으로 센다
            label = {n["entity_id"]: n["tag"] or str(n["kind"]) for n in g["nodes"] if n["node_type"] == "drawing_object"}
            want = []
            ends = {}
            for e in g["edges"]:
                if e["kind"] == "has_endpoint":
                    ends.setdefault(e["segment"], []).append(e["node"])
            segs = {s["entity_id"]: s for s in g["nodes"] if s["node_type"] == "pipe_segment"}
            for sid, ns in ends.items():
                if all(x in by_entity for x in ns):
                    want.append(("physical_connection", tuple(sorted(label[x] for x in ns)), segs[sid].get("line_no")))
            got = [x for x in tag_pairs(back) if x[0] == "physical_connection"]
            self.assertEqual(sorted(got, key=str), sorted(want, key=str))
            for n in back["nodes"]:
                if n["kind"] == "continuation":
                    self.assertTrue(n["attributes"].get("to_drawing") or n["attributes"].get("to_object"))

    def test_roundtrip_restores_flow_and_check_valve_directions_from_the_sidecar(self):
        for _, (ex, g), exp in self.each():
            back = reimport(exp)
            flows_before = sum(1 for n in g["nodes"] if n["node_type"] == "pipe_segment" and n.get("flow_direction")
                               and n["entity_id"] in {p["entity_id"] for p in exp.sidecar["pipes"]})
            flows_after = sum(1 for r in back["relations"] if r["kind"] == "physical_connection" and r["flow_direction"])
            self.assertEqual(flows_after, flows_before)
            self.assertLessEqual(back["run"]["dexpi"]["sidecar"]["restored_flows"], flows_after)
            valves_before = [n for n in g["nodes"] if n["kind"] == "check_valve" and n.get("check_direction")
                             and n["entity_id"] in {e["entity_id"] for e in exp.sidecar["entities"]}]
            valves_after = [n for n in back["nodes"] if n["kind"] == "check_valve" and n.get("check_direction")]
            self.assertEqual(len(valves_after), len(valves_before))

    def test_without_the_sidecar_the_file_stands_alone(self):
        """곁 파일 없이도 DEXPI 파일만으로 온전하다. 근사로 낸 kind는 DEXPI 쪽 이름으로, 흐름 방향은 미확인으로 돌아온다."""
        key = "SNP-M-201"
        ex, g = self.pairs[key]
        back = reimport(self.exports[key], with_sidecar=False)
        self.assertEqual(back["validation"]["status"], "passed")
        # 곁 파일이 없으면 흐름은 파일에 근거가 있는 것(도면 연결 기호)만 남고 나머지는 미확인이다
        self.assertEqual({r["flow_direction"]["basis"] for r in back["relations"] if r["flow_direction"]}, {"dexpi_off_page_connector"})
        self.assertNotIn("demineralizer", [n["kind"] for n in back["nodes"]])  # PressureVessel -> vessel
        self.assertIn("vessel", [n["kind"] for n in back["nodes"]])
        self.assertEqual(len([u for u in back["validation"]["unknowns"] if u["check"] == "unknown_flow_direction"]),
                         len([r for r in back["relations"] if r["kind"] == "physical_connection" and not r["flow_direction"]]))


class ExclusionRulesTest(unittest.TestCase):

    def setUp(self):
        self.ex, self.g = dexpi_pair("small-pid-dexpi2.xml")

    def test_unclassified_component_and_its_connections_are_left_out(self):
        g = copy.deepcopy(self.g)
        mixer = [n for n in g["nodes"] if n["tag"] == "M-101"][0]
        exp = de.export_drawing(g, None, require_confirmed_number=False)  # 원문 조각을 줄 extraction이 없다
        self.assertEqual([(x["tag"], x["reason"]) for x in exp.excluded["excluded_components"]], [("M-101", "unclassified")])
        self.assertEqual(exp.stats["connections"], 4)
        reasons = [x["reason"] for x in exp.excluded["excluded_connections"]]
        self.assertEqual(reasons.count("endpoint_excluded"), 1)
        self.assertNotIn(mixer["entity_id"], [e["entity_id"] for e in exp.sidecar["entities"]])
        text = exp.xml.decode("utf-8")
        self.assertNotIn("Mixer", text)

    def test_imported_unclassified_component_is_restored_from_its_original_text(self):
        """§7.2: 가져올 때 남긴 원문 조각은 사람이 고치지 않았을 때만 그대로 되쓴다. 고쳤으면 원문을 버리고 뺀다."""
        exp = de.export_drawing(self.g, self.ex, require_confirmed_number=False)
        self.assertEqual(exp.stats["excluded_components"], 0)
        self.assertEqual(exp.stats["connections"], 5)
        self.assertIn({"entity_id": [n for n in self.g["nodes"] if n["tag"] == "M-101"][0]["entity_id"],
                       "reason": "restored_from_original_text", "dexpi_class": "Mixer"}, exp.excluded["approximations"])
        types = [o.get("type") for o in dexpi_read.parse_safely(exp.xml).iter("Object")]
        self.assertIn("Plant/ProcessEquipment.Mixer", types)
        back = dexpi_import.extract_bytes(exp.xml, "x.dexpi.xml", sidecar=exp.sidecar)[0]
        mixer = [n for n in back["nodes"] if n["tag"] == "M-101"][0]
        self.assertEqual((mixer["kind"], mixer["attributes"]["dexpi:type"]), (None, "Mixer"))
        self.assertEqual(len([r for r in back["relations"] if r["kind"] == "physical_connection"]), 5)
        g = copy.deepcopy(self.g)  # 사람이 고쳤으면 되쓰지 않는다
        edited = [n for n in g["nodes"] if n["tag"] == "M-101"][0]
        edited.update(origin="human_edit", human_edit={"op_ids": ["op-1"], "ops": [], "by": "tester", "at": "x"})
        exp2 = de.export_drawing(g, self.ex, require_confirmed_number=False)
        self.assertEqual([(x["tag"], x["reason"]) for x in exp2.excluded["excluded_components"]], [("M-101", "unclassified")])
        cut = copy.deepcopy(self.ex)  # 조각이 잘렸으면 되쓰지 않는다
        for n in cut["nodes"]:
            if n["tag"] == "M-101":
                n["evidence"]["dexpi"]["xml_cut"] = True
        exp3 = de.export_drawing(self.g, cut, require_confirmed_number=False)
        self.assertEqual([x["tag"] for x in exp3.excluded["excluded_components"]], ["M-101"])

    def test_attribute_level_unknown_only_drops_that_attribute(self):
        g = copy.deepcopy(self.g)
        pump = [n for n in g["nodes"] if n["tag"] == "P-101"][0]
        pump["tag"] = None
        pump["attributes"].pop("tag", None)
        exp = de.export_drawing(g, self.ex, require_confirmed_number=False)
        self.assertEqual(exp.stats["excluded_components"], 0)  # 믹서는 원문으로 되살아난다
        root = dexpi_read.parse_safely(exp.xml)
        pumps = [o for o in root.iter("Object") if o.get("type") == "Plant/ProcessEquipment.CentrifugalPump"]
        self.assertEqual(len(pumps), 1)
        self.assertEqual([d for d in pumps[0].findall("Data") if d.get("property") == "TagName"], [])  # 추측값을 넣지 않는다

    def test_confirmed_drawing_number_is_required(self):
        with self.assertRaises(de.ExportError) as cm:
            de.export_drawing(self.g, self.ex)
        self.assertIn("확정", cm.exception.reasons[0])
        ex = copy.deepcopy(self.ex)
        ex["drawing"]["identification_basis"] = "registration_confirmed"
        self.assertEqual(de.export_drawing(self.g, ex).sidecar["drawing_number"], "TEST-1")
        g = copy.deepcopy(self.g)
        g["source"]["drawing_number"] = None
        with self.assertRaises(de.ExportError):
            de.export_drawing(g, ex)

    def test_blocked_graph_is_not_exported(self):
        g = copy.deepcopy(self.g)
        g["validation"]["status"] = "blocked"
        g["validation"]["blockers"] = [{"check": "x", "target": None, "reason": "x"}]
        with self.assertRaises(de.ExportError):
            de.export_drawing(g, self.ex, require_confirmed_number=False)

    def test_human_edited_kind_is_exported_as_edited(self):
        g = copy.deepcopy(self.g)
        pump = [n for n in g["nodes"] if n["tag"] == "P-101"][0]
        pump.update(kind="compressor", origin="human_edit", human_edit={"op_ids": ["op-1"], "ops": [], "by": "tester", "at": "x"})
        pump["attributes"]["kind"] = "compressor"
        pump["attributes"].pop("dexpi:type")  # 사람이 종류를 고쳤으니 원래 하위 클래스를 따르지 않는다
        exp = de.export_drawing(g, self.ex, require_confirmed_number=False)
        types = [o.get("type") for o in dexpi_read.parse_safely(exp.xml).iter("Object")]
        self.assertIn("Plant/ProcessEquipment.Compressor", types)
        self.assertNotIn("Plant/ProcessEquipment.CentrifugalPump", types)
        side = [e for e in exp.sidecar["entities"] if e["tag"] == "P-101"][0]
        self.assertEqual((side["origin"], side["human_edit"]["by"]), ("human_edit", "tester"))

    def test_broken_reference_in_the_source_is_listed_as_unresolved(self):
        text = fixture("small-pid-dexpi2.xml").decode("utf-8").replace(
            '<References objects="#Valve1" property="TargetItem"/>', '<References objects="#Ghost1" property="TargetItem"/>', 1)
        ex = dexpi_import.extract_bytes(text.encode("utf-8"), "x.xml")[0]
        exp = de.export_drawing(build.build_graph(ex), ex, require_confirmed_number=False)
        self.assertEqual([x["reason"] for x in exp.excluded["excluded_connections"]], ["unresolved_connector"])
        self.assertEqual(exp.stats["connections"], 4)

    def test_class_outside_the_list_blocks_the_export_and_nothing_is_written(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        broken = dict(dexpi_map.EXPORT_CLASS, pump=("NoSuchPump", "exact"))
        with mock.patch.dict(dexpi_map.EXPORT_CLASS, broken, clear=True):
            g = copy.deepcopy(self.g)
            [n for n in g["nodes"] if n["tag"] == "P-101"][0]["attributes"].pop("dexpi:type")
            with self.assertRaises(de.ExportError) as cm:
                de.export_drawing(g, self.ex, require_confirmed_number=False)
        self.assertIn("클래스 목록", cm.exception.reasons[0])
        self.assertEqual(os.listdir(out), [])


class DexpiRoundtripTest(unittest.TestCase):
    """§7.1: DEXPI -> 우리 -> DEXPI. id·클래스·연결 끝·태그·선 속성·설계 조건·도면 연결 참조·그림 위치가 지켜진다."""

    def roundtrip(self, name):
        ex1, g1 = dexpi_pair(name)
        exp = de.export_drawing(g1, ex1, require_confirmed_number=False)
        ex2 = dexpi_import.extract_bytes(exp.xml, "again.dexpi.xml", sidecar=exp.sidecar)[0]
        return ex1, g1, exp, ex2

    def test_ids_classes_tags_and_connections_survive(self):
        for name in ("small-pid-dexpi2.xml", "small-pid-proteus.xml"):
            with self.subTest(file=name):
                ex1, g1, exp, ex2 = self.roundtrip(name)
                fix = lambda i: i if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", i) else "HZ_" + re.sub(r"[^A-Za-z0-9_]", "_", i)  # noqa: E731
                # 미분류 믹서는 2.0 파일에서 가져왔을 때만 원문 조각으로 되살아난다(Proteus 조각은 2.0 파일에 넣을 수 없다)
                restored = name == "small-pid-dexpi2.xml"
                cut = {fix(n["source_object_id"]): n for n in ex1["nodes"] if n["kind"] is not None or restored}
                back = {n["source_object_id"]: n for n in ex2["nodes"]}
                self.assertEqual(sorted(back), sorted(cut))  # 같은 id
                for oid, n in cut.items():
                    self.assertEqual(back[oid]["attributes"]["dexpi:type"], n["attributes"]["dexpi:type"], oid)
                    self.assertEqual((back[oid]["kind"], back[oid]["tag"]), (n["kind"], n["tag"]), oid)
                self.assertEqual(tag_pairs(ex2), [x for x in tag_pairs(ex1) if restored or "M-101" not in x[1]])
                self.assertEqual(len([r for r in ex2["relations"] if r["kind"] == "physical_connection"]), 5 if restored else 4)

    def test_line_attributes_design_conditions_and_off_page_reference_survive(self):
        ex1, g1, exp, ex2 = self.roundtrip("small-pid-dexpi2.xml")
        rel = [r for r in ex2["relations"] if r["kind"] == "physical_connection"]
        for r in [r for r in rel if r["line_no"] == "L-100"]:
            self.assertEqual((r["attributes"]["line_no"], r["attributes"]["fluid_code"], r["attributes"]["pipe_class"],
                              r["attributes"]["nominal_diameter"]), ("L-100", "W", "A1", "DN 80"))
        self.assertEqual(sorted(r["line_no"] for r in rel), ["L-100"] * 4 + ["L-200"])
        pump = [n for n in ex2["nodes"] if n["tag"] == "P-101"][0]
        self.assertEqual(pump["attributes"]["design_pressure_max"], "16.0 bar(g)")
        cont = [n for n in ex2["nodes"] if n["kind"] == "continuation"][0]
        self.assertEqual((cont["attributes"]["to_drawing"], cont["attributes"]["to_object"]), ("DWG-2", "OC-9"))
        self.assertEqual(cont["attributes"]["direction"], "TO")
        valve = [n for n in ex2["nodes"] if n["tag"] == "V-101"][0]
        self.assertEqual((valve["kind"], valve["attributes"]["fail_position"]), ("control_valve", "FC"))
        ports = {(e["port"]) for r in rel for e in r["endpoints"] if e["port"]}
        self.assertEqual(ports, {"N1", "N2"})

    def test_node_positions_are_kept_within_a_hundredth_of_a_millimetre(self):
        ex1, g1, exp, ex2 = self.roundtrip("small-pid-dexpi2.xml")
        root1 = dexpi_read.read(fixture("small-pid-dexpi2.xml"))
        root2 = dexpi_read.read(exp.xml)
        self.assertEqual(sorted(root1.node_pos), sorted(root2.node_pos))
        for nid, p in root2.node_pos.items():
            self.assertAlmostEqual(p[0], root2.node_pos[nid][0], delta=0.01, msg=nid)
            self.assertAlmostEqual(p[1], root2.node_pos[nid][1], delta=0.01, msg=nid)

    def test_flow_from_arrows_comes_back_through_the_sidecar(self):
        ex1, g1, exp, ex2 = self.roundtrip("small-pid-dexpi2.xml")
        self.assertEqual(len([r for r in ex1["relations"] if r["flow_direction"]]), 2)
        self.assertEqual(len([r for r in ex2["relations"] if r["flow_direction"]]), 2)
        self.assertEqual(exp.excluded["notes"], [{"reason": "flow_direction_has_no_dexpi_slot", "count": 2}])

    def test_instrument_pieces_survive(self):
        ex1, g1, exp, ex2 = self.roundtrip("small-pid-dexpi2.xml")
        pif = [n for n in ex2["nodes"] if n["category"] == "instrument"][0]
        self.assertEqual((pif["tag"], pif["attributes"]["dexpi:ProcessInstrumentationFunctionCategory"],
                          pif["attributes"]["dexpi:ProcessInstrumentationFunctionNumber"]), ("P101", "P", "101"))
        kinds = sorted(r["kind"] for r in ex2["relations"] if r["kind"] != "physical_connection")
        self.assertEqual(kinds, ["measurement_connection", "signal_connection"])

    def test_fail_actions_follow_the_enumeration_and_fl_comes_back_from_the_sidecar(self):
        ex1, g1 = dexpi_pair("small-pid-dexpi2.xml")
        for fp, action, back in (("FO", "FailOpen", "FO"), ("FC", "FailClose", "FC"), ("FAI", "FailRetainPosition", "FAI"),
                                 ("FL", "FailRetainPosition", "FL")):
            g = copy.deepcopy(g1)
            valve = [n for n in g["nodes"] if n["tag"] == "V-101"][0]
            valve["attributes"]["fail_position"] = fp
            exp = de.export_drawing(g, ex1, require_confirmed_number=False)
            self.assertIn("FailActionClassification." + action, exp.xml.decode("utf-8"))
            again = dexpi_import.extract_bytes(exp.xml, "x.dexpi.xml", sidecar=exp.sidecar)[0]
            self.assertEqual([n for n in again["nodes"] if n["tag"] == "V-101"][0]["attributes"]["fail_position"], back, fp)
            self.assertEqual(any(a["reason"] == "fail_action_approximate" for a in exp.excluded["approximations"]), fp == "FL")

    def test_stale_sidecar_is_not_applied(self):
        ex1, g1 = dexpi_pair("small-pid-dexpi2.xml")
        exp = de.export_drawing(g1, ex1, require_confirmed_number=False)
        changed = exp.xml.replace(b"P-101", b"P-102")
        ex2 = dexpi_import.extract_bytes(changed, "x.dexpi.xml", sidecar=exp.sidecar)[0]
        self.assertIn("dexpi_sidecar_stale", [u["check"] for u in ex2["validation"]["unknowns"]])
        self.assertNotIn("sidecar", ex2["run"]["dexpi"])
        self.assertTrue(all("hazop_sidecar" not in n.get("evidence", {}) for n in ex2["nodes"]))


class WriteTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.graph_root, self.extract_root = os.path.join(self.tmp, "graph"), os.path.join(self.tmp, "extract")
        for name, path in (("SNP-M-101", [p for p in SNP if "SNP-M-101" in p][0]), ("SNP-M-102", [p for p in SNP if "SNP-M-102" in p][0])):
            ex, g = snp_pair(path)
            for root, doc, fname in ((self.graph_root, g, "graph.json"), (self.extract_root, ex, "extraction.json")):
                os.makedirs(os.path.join(root, name))
                with open(os.path.join(root, name, fname), "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, ensure_ascii=False)
        self.out = os.path.join(self.tmp, "out")

    def export(self, **kw):
        kw.setdefault("confirmation", "assume")
        kw.setdefault("require_confirmed_number", False)
        return de.export_names(None, self.out, graph_root=self.graph_root, extract_root=self.extract_root, **kw)

    def test_export_names_writes_files_and_a_manifest(self):
        res = self.export(now="2026-11-14T00:00:00+00:00")
        self.assertEqual(sorted(os.listdir(self.out)), ["SNP-M-101.dexpi.xml", "SNP-M-101.excluded.json", "SNP-M-101.hazop.json",
                                                         "SNP-M-102.dexpi.xml", "SNP-M-102.excluded.json", "SNP-M-102.hazop.json",
                                                         "manifest.json"])
        with open(res["manifest"], encoding="utf-8") as fh:
            man = json.load(fh)
        self.assertEqual(man["attribution"], "DEXPI Specification 2.0.1, DEXPI e.V., CC BY 4.0")
        self.assertEqual(man["dexpi_version"], "2.0.1")
        self.assertEqual((man["confirmation"], man["not_exported"]), ("assumed", []))
        self.assertEqual([d["drawing_number"] for d in man["drawings"]], ["SNP-M-101", "SNP-M-102"])
        self.assertTrue(all(d["graph_version"].startswith("v-") for d in man["drawings"]))
        with open(os.path.join(self.out, "SNP-M-101.hazop.json"), encoding="utf-8") as fh:
            side = json.load(fh)
        with open(os.path.join(self.out, "SNP-M-101.dexpi.xml"), "rb") as fh:
            import hashlib
            self.assertEqual(side["dexpi_sha256"], hashlib.sha256(fh.read()).hexdigest())

    def gate(self, states, calls=None):
        def sheet_confirmation(name):
            if calls is not None:
                calls.append(name)
            state = states[name]
            state = state.pop(0) if isinstance(state, list) else state
            return {"state": state, "unconfirmed": [{"reason": "x"}] * (0 if state == "confirmed" else 3), "unplaced": []}
        return sheet_confirmation

    def test_only_confirmed_pages_are_exported_and_the_rest_is_listed(self):
        res = self.export(confirmation=self.gate({"SNP-M-101": "confirmed", "SNP-M-102": "ready"}))
        self.assertEqual([d["name"] for d in res["drawings"]], ["SNP-M-101"])
        self.assertEqual(res["not_exported"], [{"name": "SNP-M-102", "drawing_number": "SNP-M-102", "state": "ready", "unconfirmed": 3}])
        self.assertEqual(sorted(os.listdir(self.out)), ["SNP-M-101.dexpi.xml", "SNP-M-101.excluded.json", "SNP-M-101.hazop.json",
                                                         "manifest.json"])
        with open(res["manifest"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["not_exported"][0]["name"], "SNP-M-102")

    def test_no_confirmed_page_writes_nothing(self):
        with self.assertRaises(de.ExportError) as cm:
            self.export(confirmation=self.gate({"SNP-M-101": "open", "SNP-M-102": "ready"}))
        self.assertIn("확정된 쪽이 하나도 없어", cm.exception.reasons[0])
        self.assertFalse(os.path.exists(self.out))

    def test_the_gate_is_asked_again_just_before_writing(self):
        calls = []
        res = self.export(confirmation=self.gate({"SNP-M-101": "confirmed", "SNP-M-102": ["confirmed", "open"]}, calls))
        self.assertEqual([d["name"] for d in res["drawings"]], ["SNP-M-101"])
        self.assertEqual(res["not_exported"][0]["state"], "open")
        self.assertEqual(calls, ["SNP-M-101", "SNP-M-102", "SNP-M-101", "SNP-M-102"])

    def test_without_the_sheet_confirmation_function_nothing_is_exported(self):
        with mock.patch.dict(sys.modules, {"hazop.extract.confirmation": None}):
            self.assertIsNone(de.default_confirmation())
            with self.assertRaises(de.ExportError) as cm:
                de.export_names(None, self.out, graph_root=self.graph_root, extract_root=self.extract_root, confirmation="auto")
        self.assertIn("V3", cm.exception.reasons[0])
        self.assertFalse(os.path.exists(self.out))

    def test_auto_uses_the_sheet_confirmation_of_the_engine_when_it_exists(self):
        import types
        fake = types.ModuleType("hazop.extract.confirmation")
        fake.sheet_confirmation = self.gate({"SNP-M-101": "confirmed", "SNP-M-102": "open"})
        with mock.patch.dict(sys.modules, {"hazop.extract.confirmation": fake}):
            res = self.export(confirmation="auto")
        self.assertEqual([d["name"] for d in res["drawings"]], ["SNP-M-101"])

    def test_list_exportable_tells_why_a_drawing_cannot_go_out(self):
        gate = self.gate({"SNP-M-101": "confirmed", "SNP-M-102": "open"})
        rows = de.list_exportable(self.graph_root, self.extract_root, confirmation=gate)
        self.assertEqual([(r["name"], r["confirmed"], r["state"], r["unconfirmed"], r["exportable"]) for r in rows],
                         [("SNP-M-101", False, "confirmed", 0, False), ("SNP-M-102", False, "open", 3, False)])
        self.assertEqual(rows[0]["why"], ["도면 번호가 등록에서 확정되지 않음"])
        self.assertIn("쪽이 확정되지 않음(open, 남은 미확인 3)", rows[1]["why"])
        path = os.path.join(self.extract_root, "SNP-M-101", "extraction.json")
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
        ex["drawing"]["identification_basis"] = "registration_confirmed"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ex, fh)
        rows = de.list_exportable(self.graph_root, self.extract_root, confirmation=gate)
        self.assertEqual([(r["name"], r["exportable"]) for r in rows], [("SNP-M-101", True), ("SNP-M-102", False)])
        self.assertEqual(de.list_exportable(os.path.join(self.tmp, "nothing"), self.extract_root), [])
        none = de.list_exportable(self.graph_root, self.extract_root, confirmation=None)
        self.assertIn("쪽 확정 함수(sheet_confirmation, 화면 규격 V3)가 아직 없음", none[0]["why"])

    def test_unconfirmed_drawing_numbers_block_the_whole_export(self):
        with self.assertRaises(de.ExportError) as cm:
            de.export_names(None, self.out, graph_root=self.graph_root, extract_root=self.extract_root, confirmation="assume")
        self.assertEqual(len(cm.exception.reasons), 2)
        self.assertFalse(os.path.exists(self.out))

    def test_one_failing_drawing_writes_nothing_for_the_others(self):
        path = os.path.join(self.graph_root, "SNP-M-102", "graph.json")
        with open(path, encoding="utf-8") as fh:
            g = json.load(fh)
        g["validation"]["status"] = "blocked"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(g, fh)
        with self.assertRaises(de.ExportError) as cm:
            self.export()
        self.assertEqual(len(cm.exception.reasons), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_failed_write_removes_what_was_written(self):
        real = de.store_io.write_bytes
        calls = []

        def flaky(path, data, *a, **k):
            calls.append(path)
            if len(calls) == 5:
                raise PermissionError(13, "denied", path)
            return real(path, data, *a, **k)
        with mock.patch.object(de.store_io, "write_bytes", side_effect=flaky):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual(os.listdir(self.out), [])

    def test_script_runs_and_reports(self):
        with mock.patch("builtins.print") as pr:
            rc = export_dexpi.main(["--graph-root", self.graph_root, "--extract-root", self.extract_root, "--out", self.out,
                                    "--assume-confirmed"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "manifest.json")))
        self.assertTrue(pr.called)
        with mock.patch.dict(sys.modules, {"hazop.extract.confirmation": None}), mock.patch("builtins.print"):
            self.assertEqual(export_dexpi.main(["--graph-root", self.graph_root, "--extract-root", self.extract_root,
                                                "--out", os.path.join(self.tmp, "out2")]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out2")))


class IdAndOrientationTest(unittest.TestCase):

    def test_ids_follow_section_6_6(self):
        ids = de._Ids()
        self.assertEqual(ids.take("Pump1", "Equipment", keep=True), "Pump1")  # DEXPI에서 가져온 id가 글자 규칙에 맞으면 그대로
        self.assertEqual(ids.take("Pump1", "Equipment", keep=True), "HZ_Pump1")  # 겹치면 HZ_가 붙는다
        self.assertEqual(ids.take("Nozzle-4", "Nozzle", keep=True), "HZ_Nozzle_4")  # 규칙 밖 글자는 _로
        self.assertEqual(ids.take("Nozzle_4", "Nozzle"), "HZ_Nozzle_4_2")  # 바뀐 값이 겹치면 _2, _3…
        self.assertEqual(ids.take("Nozzle.4", "Nozzle"), "HZ_Nozzle_4_3")
        self.assertEqual(ids.take("entity-node-003", "Equipment"), "HZ_entity_node_003")
        self.assertEqual(ids.take(None, "Node"), "HZ_Node1")

    def test_exported_ids_are_valid_and_unique_for_every_sample(self):
        for path in SNP:
            ex, g = snp_pair(path)
            exp = de.export_drawing(g, ex, require_confirmed_number=False)
            root = dexpi_read.parse_safely(exp.xml)
            ids = [o.get("id") for o in root.iter("Object") if o.get("id")]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", i) for i in ids))
            self.assertTrue(all(i.startswith("HZ_") or i in ("PlantModel1", "PlantMetaData1") for i in ids), ids[:5])
            by_id = {e["dexpi_id"]: e["entity_id"] for e in exp.sidecar["entities"]}
            self.assertTrue(all(k == "HZ_" + e.replace("-", "_") for k, e in by_id.items()), list(by_id.items())[:3])

    def test_exported_pipes_follow_the_confirmed_flow_and_say_only_single_or_dual(self):
        ex, g = dexpi_pair("small-pid-dexpi2.xml")
        g = copy.deepcopy(g)
        by_tag = {n["tag"]: n["entity_id"] for n in g["nodes"] if n["tag"]}
        seg = [n for n in g["nodes"] if n["source_object_id"] == "Pipe3"][0]
        seg["flow_direction"] = {"from": by_tag["T-101"], "to": by_tag["TE-1"] if "TE-1" in by_tag else [n["entity_id"] for n in g["nodes"] if n["kind"] == "tee"][0],
                                 "from_end": "target", "to_end": "source", "basis": "source_to_target"}
        exp = de.export_drawing(g, ex, require_confirmed_number=False)
        root = dexpi_read.parse_safely(exp.xml)
        pipes = {o.get("id"): {r.get("property"): r.get("objects") for r in o.findall("References")}
                 for o in root.iter("Object") if o.get("type") == "Plant/Piping.Pipe"}
        self.assertEqual(pipes["Pipe3"]["SourceItem"], "#TankN1")  # 흐름 순서(탱크 -> 분기)로 적는다
        self.assertEqual(pipes["Pipe3"]["TargetItem"], "#Tee1")
        self.assertEqual(pipes["Pipe2"]["SourceItem"], "#Valve1")  # 흐름이 없는 연결은 그대로
        segments = [o for o in root.iter("Object") if o.get("type") == "Plant/Piping.PipingNetworkSegment"]
        flagged = [o for o in segments if any(d.get("property") == "FlowDirection" for d in o.findall("Data"))]
        self.assertEqual(len(flagged), 1)
        refs = [d.find("DataReference").get("data") for d in flagged[0].findall("Data") if d.get("property") == "FlowDirection"]
        self.assertEqual(refs, ["Plant/Enumerations.PipingNetworkSegmentFlowClassification.SingleFlowPipingNetworkSegment"])
        in_flagged = sorted(o.get("id") for o in flagged[0].iter("Object") if o.get("type") == "Plant/Piping.Pipe")
        self.assertEqual(in_flagged, ["Pipe1", "Pipe3", "Pipe4"])  # 흐름이 확인된 연결만 한 구간에 모인다
        self.assertIn("flow_direction_has_no_dexpi_slot", [n["reason"] for n in exp.excluded["notes"]])

    def test_dual_flow_class_is_written_back(self):
        ex, g = dexpi_pair("small-pid-dexpi2.xml")
        g = copy.deepcopy(g)
        for n in g["nodes"]:
            if n["node_type"] == "pipe_segment" and n["source_object_id"] == "Pipe2":
                n["attributes"]["flow_class"] = "dual"
        exp = de.export_drawing(g, ex, require_confirmed_number=False)
        text = exp.xml.decode("utf-8")
        self.assertIn("PipingNetworkSegmentFlowClassification.DualFlowPipingNetworkSegment", text)

    def test_check_valve_inlet_pipe_ends_at_the_valve_and_outlet_pipe_starts_there(self):
        key = "SNP-M-201"
        ex, g = snp_pair([p for p in SNP if key in p][0])
        exp = de.export_drawing(g, ex, require_confirmed_number=False)
        root = dexpi_read.parse_safely(exp.xml)
        pipes = {o.get("id"): {r.get("property"): r.get("objects") for r in o.findall("References")}
                 for o in root.iter("Object") if o.get("type") == "Plant/Piping.Pipe"}
        pipe_of = {p["entity_id"]: p["dexpi_id"] for p in exp.sidecar["pipes"]}
        valves = [n for n in g["nodes"] if n["kind"] == "check_valve" and n.get("check_direction")]
        self.assertGreater(len(valves), 0)
        for n in valves:
            vid = [e["dexpi_id"] for e in exp.sidecar["entities"] if e["entity_id"] == n["entity_id"]][0]
            inlet, outlet = pipes[pipe_of[n["check_direction"]["inlet"]]], pipes[pipe_of[n["check_direction"]["outlet"]]]
            self.assertEqual(inlet["TargetItem"], "#" + vid)
            self.assertEqual(outlet["SourceItem"], "#" + vid)
            self.assertIn(vid, exp.sidecar["check_directions"])


class QuantityTest(unittest.TestCase):

    def test_known_units_only(self):
        self.assertEqual(de.quantity_to_dexpi("60.0 PressureGaugeUnit.Bar"), ("60.0", "PressureGaugeUnit.Bar"))
        self.assertEqual(de.quantity_to_dexpi("16.0 bar(g)"), ("16.0", "PressureGaugeUnit.Bar"))
        self.assertEqual(de.quantity_to_dexpi("80 °C"), ("80", "TemperatureUnit.DegreeCelsius"))
        for text in ("17.2 MPa", "abc bar(g)", "17.2", "", None, "16 bar"):  # 모호하거나 처음 보는 단위는 만들어 내지 않는다
            self.assertIsNone(de.quantity_to_dexpi(text), text)


@unittest.skipUnless(SAMPLES and os.path.isdir(SAMPLES), "HAZOP_DEXPI_SAMPLES(공개 예제 폴더)가 없어 건너뜀")
class PublicSamplesTest(unittest.TestCase):

    def test_reference_pid_roundtrip(self):
        path = os.path.join(SAMPLES, "dexpi-2.0.1", "reference_pid.xml")
        if not os.path.isfile(path):
            self.skipTest("예제 파일 없음")
        with open(path, "rb") as fh:
            raw = fh.read()
        ex1 = dexpi_import.extract_bytes(raw, "reference_pid.xml")[0]
        g1 = build.build_graph(ex1)
        exp = de.export_drawing(g1, ex1, require_confirmed_number=False)
        ex2 = dexpi_import.extract_bytes(exp.xml, "back.dexpi.xml", sidecar=exp.sidecar)[0]
        self.assertEqual(ex2["validation"]["status"], "passed")
        classified = {n["source_object_id"]: n for n in ex1["nodes"] if n["kind"] is not None}
        back = {n["source_object_id"]: n for n in ex2["nodes"]}
        self.assertEqual(sorted(back), sorted(classified))
        for oid, n in classified.items():
            self.assertEqual((back[oid]["attributes"]["dexpi:type"], back[oid]["tag"]), (n["attributes"]["dexpi:type"], n["tag"]), oid)
        self.assertEqual(len(ex2["relations"]) + len(ex2["unresolved_connectors"]),
                         len(ex1["relations"]) + len(ex1["unresolved_connectors"]) - len(exp.excluded["excluded_connections"]))
        side_ids = {p["dexpi_id"] for p in exp.sidecar["pipes"]}
        self.assertTrue(side_ids <= {r["source_object_id"] for r in ex2["relations"]})


if __name__ == "__main__":
    unittest.main()
