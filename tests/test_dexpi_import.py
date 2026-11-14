"""DEXPI 가져오기(HZ-PLN-22 §5, 단위 X1) 시험: hazop/extract/adapters/dexpi_read.py·dexpi_import.py, scripts/extract_dexpi.py,
등록의 형식 판별(hazop/register/fileinfo.py).

손으로 만든 작은 파일(tests/fixtures/dexpi/)만 CI에서 돈다. 공개 예제(2.0.1 Reference P&ID, TrainingTestCases)는
환경변수 HAZOP_DEXPI_SAMPLES가 가리키는 폴더에 있을 때만 돌고 없으면 건너뛴다(저장소에 넣지 않음, 규격 §8.3).
공개 예제는 DEXPI e.V.의 CC BY 4.0 자료다(출처·저작자 표시: licenses/dexpi/NOTICE.md).
실행: python -m unittest tests.test_dexpi_import
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import extract_dexpi  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.app import data  # noqa: E402
from hazop.extract import dexpi_map, rules  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_read  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.register import fileinfo, registry  # noqa: E402

FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi")
SAMPLES = os.environ.get("HAZOP_DEXPI_SAMPLES")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def extract(data_bytes, label="x.xml", **kw):
    return dexpi_import.extract_bytes(data_bytes, label, **kw)[0]


def by_tag(ex):
    return {n["tag"]: n for n in ex["nodes"] if n["tag"]}


def node_of(ex, kind):
    return [n for n in ex["nodes"] if n["kind"] == kind]


def signature(ex):
    """두 형식(2.0·Proteus)이 같은 도면인지 비교하는 서명: 노드(kind, tag), 관계(종류, 끝 태그·포트, 선 번호, 흐름 근거)."""
    label = {n["local_id"]: (n["kind"], n["tag"]) for n in ex["nodes"]}
    nodes = sorted((str(k), str(t)) for k, t in label.values())
    rels = []
    for r in ex["relations"] + ex["unresolved_connectors"]:
        ends = tuple((str(label.get(e["node_local_id"])), e["port"], e["status"]) for e in r["endpoints"])
        flow = r["flow_direction"]
        rels.append((r["kind"], ends, r["attributes"].get("line_no"), flow["basis"] if flow else None,
                     (str(label[flow["from"]]) if flow else None)))
    return nodes, sorted(rels, key=str)


class SmallDrawingTest(unittest.TestCase):
    """손으로 만든 도면 하나를 두 형식으로 읽는다: 펌프 P-101 -> 밸브 V-101 -> 분기 -> 탱크 T-101(+ 도면 연결 기호), 믹서 M-101 -> 탱크."""

    @classmethod
    def setUpClass(cls):
        cls.exs = {"dexpi2": extract(fixture("small-pid-dexpi2.xml")), "proteus": extract(fixture("small-pid-proteus.xml"))}

    def each(self):
        for name, ex in self.exs.items():
            with self.subTest(fmt=name):
                yield name, ex

    def test_formats_are_detected_and_drawing_is_identified(self):
        self.assertEqual(self.exs["dexpi2"]["run"]["dexpi"]["flavor"], "dexpi_xml")
        self.assertEqual(self.exs["dexpi2"]["source"]["dexpi_version"], "2.0.1")
        self.assertEqual(self.exs["proteus"]["run"]["dexpi"]["flavor"], "proteus")
        self.assertEqual(self.exs["proteus"]["source"]["dexpi_version"], "1.3.1")  # DEXPI 판. Proteus 스키마 판은 따로
        self.assertEqual(self.exs["proteus"]["run"]["dexpi"]["schema_version"], "4.1.1")
        for _, ex in self.each():
            self.assertEqual(ex["source"]["format"], "dexpi")  # §4.1: 새 필드(read_method) 없이 기존 source.format에 dexpi
            self.assertNotIn("read_method", ex["run"])
            self.assertEqual(ex["validation"]["status"], "passed")
            self.assertEqual(ex["drawing"]["drawing_number"], "TEST-1")  # 등록 없이 읽을 때는 파일 값(등록 때는 후보)
            self.assertEqual((ex["drawing"]["page_width"], ex["drawing"]["page_height"]), (420, 297))

    def test_nodes_use_the_mapping_table(self):
        for _, ex in self.each():
            tags = by_tag(ex)
            self.assertEqual(tags["P-101"]["kind"], "pump")
            self.assertEqual(tags["P-101"]["category"], "equipment")
            self.assertEqual(tags["P-101"]["attributes"]["dexpi:type"], "CentrifugalPump")
            self.assertEqual(tags["T-101"]["kind"], "tank")
            self.assertEqual(tags["V-101"]["kind"], "control_valve")  # 구동계가 있고 신호 루프에 든 밸브
            self.assertEqual(tags["V-101"]["attributes"]["fail_position"], "FC")
            self.assertEqual(tags["V-101"]["attributes"]["dexpi:type"], "BallValve")
            self.assertEqual(tags["P101"]["category"], "instrument")  # 계측 기능 구분 문자 + 번호
            self.assertEqual(tags["P101"]["kind"], "controller")
            self.assertEqual(len(node_of(ex, "tee")), 1)
            cont = node_of(ex, "continuation")[0]
            self.assertEqual(cont["attributes"]["to_drawing"], "DWG-2")
            self.assertEqual(cont["attributes"]["to_object"], "OC-9")
            self.assertEqual(cont["attributes"]["direction"], "TO")
            self.assertEqual(cont["attributes"]["line_no"], "L-100")

    def test_nozzles_become_ports_not_nodes(self):
        for _, ex in self.each():
            self.assertNotIn("nozzle", [n["kind"] for n in ex["nodes"]])
            label = {n["local_id"]: n["tag"] for n in ex["nodes"]}
            ports = {(label[e["node_local_id"]], e["port"]) for r in ex["relations"] for e in r["endpoints"]
                     if label[e["node_local_id"]] in ("P-101", "T-101", "M-101")}
            self.assertEqual(ports, {("P-101", "N2"), ("T-101", "N1"), ("T-101", "N2"), ("M-101", "N1")})
            nozzles = json.loads(by_tag(ex)["T-101"]["attributes"]["dexpi:nozzles"])
            self.assertEqual([n["port"] for n in nozzles], ["N1", "N2"])

    def test_unknown_class_is_kept_as_unclassified_with_the_original_text(self):
        for _, ex in self.each():
            mixer = by_tag(ex)["M-101"]
            self.assertIsNone(mixer["kind"])
            self.assertEqual(mixer["classification"], "unclassified")
            self.assertEqual(mixer["category"], "equipment")
            self.assertEqual(mixer["attributes"]["dexpi:type"], "Mixer")
            self.assertEqual(mixer["evidence"]["dexpi"]["type"], "Mixer")
            self.assertIn("Mixer", mixer["evidence"]["dexpi"]["xml"])
            checks = [(u["check"], u["target"]) for u in ex["validation"]["unknowns"]]
            self.assertIn(("dexpi_unmapped_class", mixer["local_id"]), checks)

    def test_connections_and_line_attributes(self):
        for _, ex in self.each():
            self.assertEqual(ex["summary"]["relations_by_kind"],
                             {"physical_connection": 5, "measurement_connection": 1, "signal_connection": 1})
            self.assertEqual(ex["unresolved_connectors"], [])
            phys = [r for r in ex["relations"] if r["kind"] == "physical_connection"]
            main = [r for r in phys if r["line_no"] == "L-100"]
            self.assertEqual(len(main), 4)
            for r in main:
                self.assertEqual((r["attributes"]["fluid_code"], r["attributes"]["pipe_class"],
                                  r["attributes"]["nominal_diameter"]), ("W", "A1", "DN 80"))
            self.assertEqual([r["line_no"] for r in phys if r["line_no"] != "L-100"], ["L-200"])

    def test_flow_comes_only_from_arrows_and_off_page_connectors(self):
        """연결의 Source -> Target은 흐름 방향이 아니다(F13). 근거가 있는 두 연결만 declared, 나머지는 미확인으로 남는다."""
        for _, ex in self.each():
            label = {n["local_id"]: n["tag"] or n["kind"] for n in ex["nodes"]}
            flows = {(label[r["flow_direction"]["from"]], label[r["flow_direction"]["to"]]): r["flow_direction"]["basis"]
                     for r in ex["relations"] if r["flow_direction"]}
            self.assertEqual(flows, {("P-101", "V-101"): "dexpi_flow_arrow", ("tee", "continuation"): "dexpi_off_page_connector"})
            no_flow = [u for u in ex["validation"]["unknowns"] if u["check"] == "unknown_flow_direction"]
            self.assertEqual(len(no_flow), 3)

    def test_instrument_and_signal_relations(self):
        for _, ex in self.each():
            label = {n["local_id"]: n["tag"] or n["kind"] for n in ex["nodes"]}
            rels = {r["kind"]: [label[e["node_local_id"]] for e in r["endpoints"]]
                    for r in ex["relations"] if r["kind"] != "physical_connection"}
            self.assertEqual(rels, {"measurement_connection": ["tee", "P101"], "signal_connection": ["P101", "V-101"]})

    def test_both_formats_give_the_same_drawing(self):
        self.assertEqual(signature(self.exs["dexpi2"]), signature(self.exs["proteus"]))

    def test_positions_are_top_left_millimetres(self):
        """Proteus는 y가 위로 커서 도면 높이에서 뺀다. 두 형식에서 같은 노드가 같은 자리에 온다."""
        pos = {}
        for name, ex in self.exs.items():
            loc = {l["local_id"]: l["bbox"] for l in ex["source_locations"]}
            pos[name] = {n["tag"]: loc[n["local_id"]] for n in ex["nodes"] if n["tag"] in ("P-101", "T-101")}
            self.assertEqual(ex["coordinate_system"]["unit"], "mm")
            self.assertEqual(ex["coordinate_system"]["origin"], "top_left")
        self.assertEqual(pos["dexpi2"], pos["proteus"])
        self.assertEqual(pos["dexpi2"]["P-101"][1], 120)  # y = 120(위에서 120mm)
        self.assertEqual(self.exs["proteus"]["coordinate_system"]["source_origin"], "bottom_left")

    def test_quantity_attribute_keeps_value_and_unit(self):
        self.assertEqual(by_tag(self.exs["dexpi2"])["P-101"]["attributes"]["design_pressure_max"], "16.0 bar(g)")


class MappingTableTest(unittest.TestCase):
    """대응표(dexpi_map.py)와 클래스 목록(classes.json), 지식그래프 레지스트리의 dexpi_class가 서로 맞는다(§3.6)."""

    def test_every_mapped_class_exists_and_is_concrete(self):
        table = dexpi_map.classes()
        names = set(dexpi_map.EQUIPMENT_KIND) | set(dexpi_map.PIPING_KIND) | {c for c, _ in dexpi_map.EXPORT_CLASS.values()}
        for name in sorted(names):
            self.assertIn(name, table, name)
            self.assertFalse(table[name]["abstract"] and name != "PipeOffPageConnector", "추상 클래스: %s" % name)

    def test_every_kind_is_either_exported_or_listed_as_not_exported(self):
        covered = set(dexpi_map.EXPORT_CLASS) | set(dexpi_map.EXPORT_NONE) | set(dexpi_map.INSTRUMENT_KINDS) | {"continuation"}
        self.assertEqual(sorted(set(rules.KIND_CATEGORY) - covered), [])

    def test_registry_dexpi_class_agrees_with_the_table(self):
        from hazop.kg.schema import REGISTRY
        for cid, cls in REGISTRY.classes.items():
            name, kind = cls.get("dexpi_class"), cls.get("kind")
            if not name or not kind:
                continue
            expect = {"continuation": "PipeOffPageConnector", "nozzle": "Nozzle"}.get(kind) or dexpi_map.EXPORT_CLASS[kind][0]
            self.assertEqual(name, expect, kind)
        steam = REGISTRY.classes["steam_generator"]
        self.assertNotIn("dexpi_class", steam)  # DEXPI SteamGenerator는 가열로 계열이라 쓰지 않는다(V-7)

    def test_ancestry_picks_the_nearest_mapped_class(self):
        self.assertEqual(dexpi_map.import_kind("CentrifugalPump"), ("pump", "Pump"))
        self.assertEqual(dexpi_map.import_kind("Tank"), ("tank", "Tank"))  # Tank는 Vessel의 하위지만 더 가까운 표 항목이 먼저
        self.assertEqual(dexpi_map.import_kind("PressureVessel"), ("vessel", "PressureVessel"))
        self.assertEqual(dexpi_map.import_kind("AxialBlower"), ("fan", "Blower"))
        self.assertEqual(dexpi_map.import_kind("RuptureDisc"), ("rupture_disc", "RuptureDisc"))
        self.assertEqual(dexpi_map.import_kind("SpringLoadedGlobeSafetyValve"), ("psv", "SafetyValveOrFitting"))
        self.assertEqual(dexpi_map.import_kind("GateValve"), ("manual_valve", "OperatedValve"))
        self.assertEqual(dexpi_map.import_kind("FlowOutPipeOffPageConnector"), ("continuation", "PipeOffPageConnector"))
        self.assertEqual(dexpi_map.import_kind("Mixer"), (None, None))
        self.assertEqual(dexpi_map.import_kind("SteamGenerator"), (None, None))  # 이름이 같아도 증기발생기로 읽지 않는다


class GraphTest(unittest.TestCase):

    def test_graph_builds_and_is_deterministic(self):
        for name in ("small-pid-dexpi2.xml", "small-pid-proteus.xml"):
            with self.subTest(file=name):
                a = build.build_graph(extract(fixture(name)))
                b = build.build_graph(extract(fixture(name)))
                self.assertEqual(a["validation"]["status"], "passed")
                self.assertEqual(a["validation"]["blockers"], [])
                self.assertEqual(a["graph_version"], b["graph_version"])
                self.assertEqual(a, b)
                self.assertEqual(sorted(a["source"]), ["drawing_number", "extraction_file", "extraction_run_id"])  # 그래프 파일 틀은 그대로
                kinds = a["structure"]["node_kinds"]
                self.assertEqual(kinds["pipe_segment"], 5)
                self.assertEqual(a["structure"]["segments_with_endpoint_count_not_2"], [])
                self.assertEqual(a["structure"]["isolated_nodes"], [])
                flows = [n for n in a["nodes"] if n["node_type"] == "pipe_segment" and n.get("flow_direction")]
                self.assertEqual(len(flows), 2)

    def test_existing_extractors_output_is_untouched_by_this_unit(self):
        """§4 5번: 새 필드를 만들지 않아 기존 drawio 추출 결과와 그 그래프 파일 틀이 바뀌지 않는다."""
        from hazop.extract import drawio
        path = sorted(glob.glob(paths.folder("references", "pid-samples", "SNP-M-101*", "*.drawio")))[0]
        ex = drawio.extract(path, repo_root=REPO_ROOT)
        self.assertNotIn("dexpi", json.dumps(ex["run"]) + json.dumps(ex["source"]))
        self.assertNotIn("read_method", json.dumps(build.build_graph(ex)["source"]))


class BrokenInputTest(unittest.TestCase):

    def test_broken_reference_goes_to_unresolved_not_to_a_normal_connection(self):
        text = fixture("small-pid-dexpi2.xml").decode("utf-8")
        text = text.replace('<References objects="#Valve1" property="TargetItem"/>', '<References objects="#Ghost1" property="TargetItem"/>', 1)
        ex = extract(text.encode("utf-8"))
        self.assertEqual(ex["validation"]["status"], "passed")
        self.assertEqual(len(ex["unresolved_connectors"]), 1)
        ends = {e["end"]: e["status"] for e in ex["unresolved_connectors"][0]["endpoints"]}
        self.assertEqual(ends, {"source": "connected", "target": "invalid_reference"})
        self.assertIn("unconnected_endpoint", [u["check"] for u in ex["validation"]["unknowns"]])
        g = build.build_graph(ex)
        self.assertEqual(len(g["unresolved"]), 1)
        self.assertEqual(g["structure"]["node_kinds"]["pipe_segment"], 4)
        # 구조 검사도 참조 문제를 알린다
        problems = dexpi_read.check_references(dexpi_read.parse_safely(text.encode("utf-8")))
        self.assertEqual(problems, ["없는 객체를 가리킴: #Ghost1"])

    def test_missing_end_is_unresolved_unconnected(self):
        text = fixture("small-pid-proteus.xml").decode("utf-8")
        text = text.replace('<Connection FromID="Mixer-N1" FromNode="1" ToID="Tank-N2" ToNode="1"/>',
                            '<Connection ToID="Tank-N2" ToNode="1"/>')
        ex = extract(text.encode("utf-8"))
        self.assertEqual([e["status"] for e in ex["unresolved_connectors"][0]["endpoints"]], ["unconnected", "connected"])

    def test_duplicate_id_is_a_blocker(self):
        text = fixture("small-pid-dexpi2.xml").decode("utf-8")
        text = text.replace('id="NV2"', 'id="NV1"', 1)
        ex = extract(text.encode("utf-8"))
        self.assertEqual(ex["validation"]["status"], "blocked")
        self.assertEqual([b["check"] for b in ex["validation"]["blockers"]], ["duplicate_id"])

    def test_not_a_dexpi_file(self):
        for data_bytes, code in ((b"not xml", "dexpi_unreadable"), (b"<foo/>", "dexpi_unknown_format"),
                                 (b"<Model name='m' uri='u'/>", "dexpi_unknown_format"), (b"", "dexpi_unreadable")):
            with self.subTest(data=data_bytes):
                with self.assertRaises(dexpi_read.DexpiError) as cm:
                    dexpi_read.read(data_bytes)
                self.assertEqual(cm.exception.code, code)


class SecurityTest(unittest.TestCase):
    """HZ-PLN-22 §5.1: DTD·개체 선언 금지, 네트워크 금지, 크기 한도."""

    def refuse(self, payload, code="dexpi_doctype_forbidden"):
        with self.assertRaises(dexpi_read.DexpiError) as cm:
            dexpi_read.parse_safely(payload)
        self.assertEqual(cm.exception.code, code)

    def test_doctype_and_entity_declarations_are_refused(self):
        self.refuse(b'<!DOCTYPE Model><Model name="m" uri="u"/>')
        self.refuse(b'<!DOCTYPE Model [<!ENTITY a "x">]><Model name="m" uri="u"/>')
        self.refuse(b'<?xml version="1.0"?><!DOCTYPE Model [<!ENTITY % p "<!ENTITY a \'x\'>">%p;]><Model name="m" uri="u"/>')

    def test_external_entity_is_never_read(self):
        secret = os.path.join(tempfile.mkdtemp(), "secret.txt")
        self.addCleanup(shutil.rmtree, os.path.dirname(secret), True)
        with open(secret, "w") as fh:
            fh.write("TOP-SECRET")
        payload = ('<!DOCTYPE Model [<!ENTITY xxe SYSTEM "file:///%s">]><Model name="m" uri="u">&xxe;</Model>'
                   % secret.replace("\\", "/")).encode("utf-8")
        with self.assertRaises(dexpi_read.DexpiError) as cm:
            dexpi_read.read(payload)
        self.assertEqual(cm.exception.code, "dexpi_doctype_forbidden")
        self.assertNotIn("TOP-SECRET", cm.exception.reason)

    def test_entity_expansion_bomb_is_refused_quickly(self):
        bomb = (b'<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
                b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]><Model name="m" uri="u">&lol3;</Model>')
        self.refuse(bomb)

    def test_no_network_access_while_reading(self):
        with mock.patch("socket.socket", side_effect=AssertionError("네트워크를 열면 안 됨")), \
                mock.patch("socket.create_connection", side_effect=AssertionError("네트워크를 열면 안 됨")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("네트워크를 열면 안 됨")):
            ex = extract(fixture("small-pid-dexpi2.xml"))  # Import source="https://data.dexpi.org/…"가 들어 있다
        self.assertEqual(ex["run"]["dexpi"]["version"], "2.0.1")

    def test_size_limits(self):
        sample = fixture("small-pid-dexpi2.xml")
        with mock.patch.object(dexpi_read, "MAX_BYTES", 100):
            self.refuse(sample, "dexpi_too_large")
        with mock.patch.object(dexpi_read, "MAX_ELEMENTS", 20):
            self.refuse(sample, "dexpi_too_large")
        with mock.patch.object(dexpi_read, "MAX_DEPTH", 4):
            self.refuse(sample, "dexpi_too_large")
        deep = b"<a>" * 300 + b"</a>" * 300
        self.refuse(deep, "dexpi_too_large")

    def test_registration_blocks_unsafe_and_unreadable_files(self):
        for payload, check in ((b'<!DOCTYPE Model [<!ENTITY a "x">]><Model name="m" uri="u"/>', "dexpi_unsafe_xml"),
                               (b"<Model", "unreadable"), (b"<foo/>", "format_mismatch")):
            with self.subTest(check=check):
                info = fileinfo.inspect("bad.xml", payload)
                self.assertEqual([b["check"] for b in info["blockers"]], [check])


class RegistrationTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = os.path.join(self.tmp, "store")
        self.work = os.path.join(self.tmp, "work")

    def put(self, name):
        path = os.path.join(self.tmp, "in", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(fixture(name))
        return path

    def test_detect_format(self):
        self.assertEqual(fileinfo.detect_format(fixture("small-pid-dexpi2.xml")), "dexpi")
        self.assertEqual(fileinfo.detect_format(fixture("small-pid-proteus.xml")), "dexpi")
        self.assertEqual(fileinfo.detect_format(b'<mxfile><diagram id="a"><mxGraphModel/></diagram></mxfile>'), "drawio")
        self.assertEqual(fileinfo.detect_format(b"<root/>"), "xml")
        self.assertEqual(fileinfo.detect_format(b'<!DOCTYPE a [<!ENTITY b "c">]><a/>'), "unsafe_xml")

    def test_inspect_lists_pages_and_candidates(self):
        for name, fmt in (("small-pid-dexpi2.xml", "dexpi_xml"), ("small-pid-proteus.xml", "proteus")):
            with self.subTest(file=name):
                info = fileinfo.inspect(name, fixture(name))
                self.assertEqual((info["format"], info["dexpi_flavor"], info["blockers"]), ("dexpi", fmt, []))
                self.assertEqual([p["page_id"] for p in info["pages"]], ["page-1"])
                self.assertEqual(info["auto_candidates"]["drawing_number"]["value"], "TEST-1")
                self.assertEqual(info["auto_candidates"]["title"]["value"], "Small test P&ID")

    def test_xml_extension_other_than_dexpi_is_a_mismatch(self):
        info = fileinfo.inspect("a.xml", b"<root/>")
        self.assertEqual([b["check"] for b in info["blockers"]], ["format_mismatch"])
        info = fileinfo.inspect("a.drawio", fixture("small-pid-dexpi2.xml"))
        self.assertEqual([b["check"] for b in info["blockers"]], ["format_mismatch"])

    def test_register_extract_and_graph_for_both_formats(self):
        for name, fmt in (("small-pid-dexpi2.xml", "dexpi_xml"), ("small-pid-proteus.xml", "proteus")):
            with self.subTest(file=name), mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.work + fmt,
                                                                      "HAZOP_STORE_ROOT": self.store}):
                res = registry.register(self.put(name), "proj-1", store_root=self.store, actor="tester",
                                        metadata={"drawing_number": "TEST-1", "title": "Small", "design_revision": "0",
                                                  "by": "tester", "reason": "시험"})
                self.assertEqual(res["outcome"], "registered")
                record = res["record"]
                self.assertEqual((record["format"], record["dexpi_flavor"]), ("dexpi", fmt))
                self.assertNotIn("SVG 없음", json.dumps(record["validation"]["unknowns"], ensure_ascii=False))
                self.assertEqual(record["derived_files"], [])
                out = data.extract_and_graph(res["registration_file"])
                ex = out["extraction"]
                self.assertEqual(ex["project_id"], "proj-1")
                self.assertEqual(ex["source"]["material_id"], record["material_id"])
                self.assertEqual(ex["drawing"]["drawing_number"], "TEST-1")
                self.assertEqual(ex["drawing"]["identification_basis"], "registration_confirmed")
                self.assertEqual(out["graph"]["validation"]["status"], "passed")
                with open(os.path.join(out["extract_dir"], "extraction_run.json"), encoding="utf-8") as fh:
                    run = json.load(fh)
                self.assertEqual(run["extractor"], "dexpi")
                self.assertNotIn("read_method", run)
                self.assertEqual(out["extraction"]["source"]["format"], "dexpi")
                rows = data.list_registrations(self.store)
                self.assertEqual([(r["extracted"], r["graphed"]) for r in rows if r["record"].get("dexpi_flavor") == fmt], [(True, True)])

    def test_registered_run_with_a_changed_file_is_blocked(self):
        res = registry.register(self.put("small-pid-dexpi2.xml"), "proj-1", store_root=self.store, actor="tester")
        record = dict(res["record"], sha256="0" * 64)
        ex = extract(fixture("small-pid-dexpi2.xml"), registration=record)
        self.assertEqual([b["check"] for b in ex["validation"]["blockers"]], ["registration_hash_mismatch"])

    def test_script_refuses_unsafe_file_without_writing(self):
        bad = os.path.join(self.tmp, "bad.xml")
        with open(bad, "wb") as fh:
            fh.write(b'<!DOCTYPE Model [<!ENTITY a "x">]><Model name="m" uri="u"/>')
        out = os.path.join(self.tmp, "out")
        with mock.patch("builtins.print"):
            self.assertEqual(extract_dexpi.main([bad, "--out-root", out]), 1)
        self.assertFalse(os.path.exists(out))

    def test_script_writes_extraction_report_and_run_info(self):
        out = os.path.join(self.tmp, "out")
        with mock.patch("builtins.print"):
            self.assertEqual(extract_dexpi.main([os.path.join(FIXTURES, "small-pid-dexpi2.xml"), "--out-root", out]), 0)
        folder = os.path.join(out, "TEST-1-dexpi")
        self.assertEqual(sorted(os.listdir(folder)), ["extraction.json", "extraction_run.json", "validation_report.md"])
        with open(os.path.join(folder, "extraction.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["source"]["format"], "dexpi")


@unittest.skipUnless(SAMPLES and os.path.isdir(SAMPLES), "HAZOP_DEXPI_SAMPLES(공개 예제 폴더)가 없어 건너뜀")
class PublicSamplesTest(unittest.TestCase):
    """DEXPI 2.0.1 사양 부록 Reference P&ID와 TrainingTestCases C01(CC BY 4.0). 파일은 저장소에 없다."""

    def sample(self, *parts):
        path = os.path.join(SAMPLES, *parts)
        if not os.path.isfile(path):
            self.skipTest("예제 파일 없음: %s" % path)
        with open(path, "rb") as fh:
            return fh.read()

    def test_reference_pid_and_its_proteus_twin_agree(self):
        a = extract(self.sample("dexpi-2.0.1", "reference_pid.xml"))
        b = extract(self.sample("dexpi-1.3", "C01V04-VER.EX01.xml"))
        self.assertEqual((a["validation"]["status"], b["validation"]["status"]), ("passed", "passed"))
        self.assertEqual(a["drawing"]["drawing_number"], "123/A93")
        tags = lambda ex: sorted(n["tag"] or "-" for n in ex["nodes"])  # noqa: E731
        self.assertEqual(tags(a), tags(b))
        kinds = lambda ex: sorted(str(n["kind"]) for n in ex["nodes"])  # noqa: E731
        self.assertEqual(kinds(a), kinds(b))
        self.assertEqual(a["summary"]["nodes"], 30)
        self.assertEqual(len(a["unresolved_connectors"]), len(b["unresolved_connectors"]))
        self.assertEqual(build.build_graph(a)["validation"]["status"], "passed")

    def test_reference_pid_registration_inspect(self):
        info = fileinfo.inspect("reference_pid.xml", self.sample("dexpi-2.0.1", "reference_pid.xml"))
        self.assertEqual((info["format"], info["dexpi_flavor"], info["blockers"]), ("dexpi", "dexpi_xml", []))
        self.assertEqual(dexpi_read.check_structure(dexpi_read.parse_safely(self.sample("dexpi-2.0.1", "reference_pid.xml"))), [])

    def test_c03_unmapped_classes_are_kept(self):
        ex = extract(self.sample("dexpi-1.3", "C03V04-VER.EX02.xml"))
        self.assertEqual(ex["summary"]["nodes_unclassified"], 4)
        self.assertTrue(all(n["evidence"]["dexpi"]["xml"] for n in ex["nodes"]))


if __name__ == "__main__":
    unittest.main()
