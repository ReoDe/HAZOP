"""단계 ① drawio 추출 테스트. 실행: python -m unittest discover -s tests -t ."""

import base64
import glob
import os
import re
import shutil
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock
import xml.etree.ElementTree as ET
import zlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import extract_drawio  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.extract import drawio, rules, svg_align  # noqa: E402

SAMPLES = sorted(glob.glob(paths.folder("참고", "P&ID 도면 샘플", "*", "*.drawio")))
SAMPLE_101 = [p for p in SAMPLES if "SNP-M-101" in p][0]


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write_temp(test, text, name="t.drawio"):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d, True)
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def independent_counts(path):
    """정규식으로 원본 XML에서 직접 센다 (추출 코드와 독립)."""
    xml = read_text(path)
    cells = re.findall(r"<mxCell\b[^>]*>", xml)
    vertices = [c for c in cells if 'vertex="1"' in c and "pidIgnore=1" not in c]
    edges = [c for c in cells if 'edge="1"' in c]
    ignored = [c for c in cells if "pidIgnore=1" in c]
    return len(vertices), len(edges), len(ignored)


def compress(text):
    """draw.io 압축 저장 형식으로 변환: diagram 본문 = base64(deflate_raw(urlencode(xml)))."""
    model = re.search(r"<mxGraphModel\b.*</mxGraphModel>", text, re.S).group(0)
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = co.compress(urllib.parse.quote(model, safe="").encode("utf-8")) + co.flush()
    return text.replace(model, base64.b64encode(data).decode("ascii"))


def all_issue_checks(result):
    v = result["validation"]
    return [i["check"] for i in v["blockers"] + v["unknowns"]]


class SampleExtractionTest(unittest.TestCase):

    def test_six_samples_exist(self):
        self.assertEqual(len(SAMPLES), 6)

    def test_all_samples_extract_and_counts_match(self):
        for path in SAMPLES:
            with self.subTest(sample=os.path.basename(path)):
                r = drawio.extract(path)
                self.assertEqual(r["validation"]["status"], "passed")
                self.assertEqual(r["validation"]["blockers"], [])
                n_vertex, n_edge, n_ignored = independent_counts(path)
                self.assertEqual(len(r["nodes"]) + len(r["texts"]) + len(r["unclassified"])
                                 + r["summary"]["edge_label_cells"], n_vertex)
                self.assertEqual(r["coordinate_system"]["svg_alignment"], None)
                self.assertEqual(len(r["relations"]) + len(r["unresolved_connectors"]), n_edge)
                self.assertEqual(len(r["drawing"]["ignored_objects"]), n_ignored)
                # 샘플은 모두 규칙을 따르므로 미분류 0, 모든 노드·관계에 bbox
                self.assertEqual(r["summary"]["nodes_unclassified"], 0)
                located = {loc["object_id"] for loc in r["source_locations"]}
                for item in r["nodes"] + r["relations"]:
                    self.assertIn(item["source_object_id"], located)

    def test_attributes_preserved(self):
        r = drawio.extract(SAMPLE_101)
        root = ET.parse(SAMPLE_101).getroot()
        objs = {o.get("id"): o for o in root.iter("object")}
        for n in r["nodes"]:
            o = objs[n["source_object_id"]]
            expected = {k: v for k, v in o.attrib.items() if k not in ("id", "label")}
            self.assertEqual(n["attributes"], expected)
            self.assertEqual(n["label"], o.get("label"))
            self.assertNotIn("<", n["label_text"])
        n1 = [n for n in r["nodes"] if n["source_object_id"] == "n1"][0]
        self.assertEqual(n1["label_text"], "RC-RV01\nREACTOR VESSEL")
        self.assertEqual(n1["kind"], "reactor_vessel")
        self.assertEqual(n1["tag"], "RC-RV01")

    def test_title_block_excluded_and_kept_as_metadata(self):
        r = drawio.extract(SAMPLE_101)
        ids = {n["source_object_id"] for n in r["nodes"] + r["texts"]}
        for ignored in ("frame", "tb00", "tb11", "t71"):
            self.assertNotIn(ignored, ids)
        self.assertEqual(r["drawing"]["drawing_number"], "SNP-M-101")
        self.assertEqual(r["drawing"]["title"], "REACTOR COOLANT SYSTEM - MAIN LOOP")
        self.assertEqual(r["drawing"]["revision"], "0")

    def test_relation_kinds_and_flow_direction(self):
        r = drawio.extract(SAMPLE_101)
        kinds = {rel["kind"] for rel in r["relations"]}
        self.assertEqual(kinds, {"physical_connection", "signal_connection", "measurement_connection"})
        for k in kinds:
            self.assertRegex(k, r"^[a-z][a-z0-9_]*$")
        e7 = [x for x in r["relations"] if x["source_object_id"] == "e7"][0]
        self.assertEqual(e7["line_type"], "process")
        self.assertEqual([ep["end"] for ep in e7["endpoints"]], ["source", "target"])
        self.assertEqual(e7["endpoints"][0]["constraint"], {"x": 1.0, "y": 0.25, "dx": 0.0, "dy": 0.0})
        self.assertEqual(e7["flow_direction"]["from"], e7["endpoints"][0]["node_local_id"])
        # 방향 속성이 없는 공정 배관은 미확인으로 남고 값을 만들지 않는다
        no_dir = [x for x in r["relations"] if x["kind"] == "physical_connection"
                  and "flow_direction" not in x["attributes"]]
        self.assertTrue(no_dir)
        for x in no_dir:
            self.assertIsNone(x["flow_direction"])
        self.assertEqual(r["summary"]["issue_counts"].get("unknown_flow_direction"), len(no_dir))

    def test_waypoints_kept(self):
        r = drawio.extract(SAMPLE_101)
        e12 = [x for x in r["relations"] if x["source_object_id"] == "e12"][0]
        self.assertEqual(e12["waypoints"], [[857, 560], [780, 560]])

    def test_label_location_reflects_label_style(self):
        r = drawio.extract(SAMPLE_101)
        n1 = [n for n in r["nodes"] if n["source_object_id"] == "n1"][0]
        loc = n1["label_location"]
        self.assertTrue(loc["approximate"])
        # labelPosition=left, align=right: 라벨은 도형(x=260) 왼쪽에 오른쪽 끝을 맞춘다
        x, y, w, h = loc["bbox"]
        self.assertLessEqual(x + w, 260)
        self.assertAlmostEqual(y + h / 2.0, 430 + 280 / 2.0, delta=1)
        # 빈 라벨(tee 등)은 라벨 위치를 만들지 않는다
        tee = [n for n in r["nodes"] if n["kind"] == "tee"][0]
        self.assertIsNone(tee["label_location"])


class CompressedFormatTest(unittest.TestCase):

    def test_compressed_gives_same_result(self):
        text = read_text(SAMPLE_101)
        path = write_temp(self, compress(text))
        self.assertNotIn("<mxGraphModel", read_text(path))
        a = drawio.extract(SAMPLE_101)
        b = drawio.extract(path)
        self.assertTrue(b["source"]["compressed"])
        for key in ("nodes", "relations", "unresolved_connectors", "texts", "source_locations",
                    "validation", "drawing", "summary"):
            self.assertEqual(a[key], b[key], key)


class EditedSampleTest(unittest.TestCase):
    """샘플을 고쳐 규칙 위반 사례를 만든다."""

    def extract_edited(self, old, new, count=1):
        text = read_text(SAMPLE_101)
        self.assertIn(old, text)
        return drawio.extract(write_temp(self, text.replace(old, new, count)))

    def test_floating_line_is_unresolved(self):
        extra = ('<object id="f1" label="" line_type="process">'
                 '<mxCell style="endArrow=none;" edge="1" parent="1" source="n1">'
                 '<mxGeometry relative="1" as="geometry">'
                 '<mxPoint x="900" y="900" as="targetPoint"/></mxGeometry></mxCell></object>'
                 '<mxCell id="f2" style="endArrow=none;" edge="1" parent="1">'
                 '<mxGeometry relative="1" as="geometry"><mxPoint x="10" y="10" as="sourcePoint"/>'
                 '<mxPoint x="50" y="10" as="targetPoint"/></mxGeometry></mxCell></root>')
        r = self.extract_edited("</root>", extra)
        self.assertEqual(r["validation"]["status"], "passed")
        self.assertNotIn("f1", {x["source_object_id"] for x in r["relations"]})
        un = {x["source_object_id"]: x for x in r["unresolved_connectors"]}
        self.assertEqual(set(un), {"f1", "f2"})
        f1 = un["f1"]
        self.assertEqual(f1["endpoints"][0]["status"], "connected")
        self.assertEqual(f1["endpoints"][1]["status"], "unconnected")
        self.assertEqual(f1["endpoints"][1]["point"], [900, 900])
        self.assertIsNone(f1["endpoints"][1]["node_local_id"])
        self.assertIsNone(un["f2"]["kind"])  # line_type 없음 -> 관계 종류 미확인
        checks = all_issue_checks(r)
        self.assertEqual(checks.count("unconnected_endpoint"), 3)
        self.assertIn("missing_line_type", checks)

    def test_unknown_kind_kept_and_listed(self):
        r = self.extract_edited('kind="pump"', 'kind="mystery_pump"')
        node = [n for n in r["nodes"] if n["kind"] == "mystery_pump"][0]
        self.assertEqual(node["classification"], "unclassified")
        self.assertIsNone(node["category"])
        listed = [u for u in r["validation"]["unknowns"] if u["check"] == "unclassified_kind"]
        self.assertEqual([u["source_object_id"] for u in listed], [node["source_object_id"]])
        self.assertEqual(r["validation"]["status"], "passed")

    def test_vertex_without_kind_is_unclassified_node(self):
        extra = ('<mxCell id="x1" value="?" style="ellipse;" vertex="1" parent="1">'
                 '<mxGeometry x="5" y="5" width="10" height="10" as="geometry"/></mxCell></root>')
        r = self.extract_edited("</root>", extra)
        node = [n for n in r["nodes"] if n["source_object_id"] == "x1"][0]
        self.assertEqual(node["classification"], "unclassified")
        self.assertIn("missing_kind", all_issue_checks(r))

    def test_independent_text(self):
        extra = ('<mxCell id="tx1" value="FREE TEXT" style="text;html=1;" vertex="1" parent="1">'
                 '<mxGeometry x="5" y="5" width="50" height="20" as="geometry"/></mxCell></root>')
        r = self.extract_edited("</root>", extra)
        self.assertEqual([t["text"] for t in r["texts"]], ["FREE TEXT"])
        self.assertNotIn("tx1", {n["source_object_id"] for n in r["nodes"]})

    def test_missing_reference_blocks(self):
        r = self.extract_edited('source="n1" target="j4"', 'source="n1" target="nope"')
        self.assertEqual(r["validation"]["status"], "blocked")
        self.assertIn("missing_reference", [b["check"] for b in r["validation"]["blockers"]])
        e7 = [x for x in r["unresolved_connectors"] if x["source_object_id"] == "e7"][0]
        self.assertEqual(e7["endpoints"][1]["status"], "invalid_reference")

    def test_endpoint_on_ignored_object_is_not_node(self):
        r = self.extract_edited('source="n1" target="j4"', 'source="n1" target="tb00"')
        self.assertIn("endpoint_not_node", all_issue_checks(r))
        self.assertIn("e7", {x["source_object_id"] for x in r["unresolved_connectors"]})

    def test_duplicate_id_blocks(self):
        r = self.extract_edited('<object id="n2"', '<object id="n1"')
        self.assertEqual(r["validation"]["status"], "blocked")
        self.assertIn("duplicate_id", [b["check"] for b in r["validation"]["blockers"]])

    def test_missing_valve_position_is_unknown(self):
        text = read_text(SAMPLE_101)
        m = re.search(r'(<object [^>]*kind="manual_valve"[^>]*?) normal_position="\w+"', text)
        r = self.extract_edited(m.group(0), m.group(1))
        self.assertIn("missing_normal_position", all_issue_checks(r))


    def test_check_valve_direction_declared_from_attribute(self):
        # 기획서/정보추출.md #check-valve-direction: 기호 미등록 상태에서 ①(도형 속성)로 선언 기반 확정
        r = drawio.extract(SAMPLE_101)
        src = {x["local_id"]: x["source_object_id"] for x in r["nodes"] + r["relations"]}
        cvs = {n["source_object_id"]: n for n in r["nodes"] if n["kind"] == "check_valve"}
        self.assertEqual(set(cvs), {"n38", "n42"})
        self.assertEqual({k: (src[n["check_direction"]["inlet"]], src[n["check_direction"]["outlet"]])
                          for k, n in cvs.items()}, {"n38": ("e39", "e40"), "n42": ("e43", "e44")})
        for n in cvs.values():
            self.assertEqual(n["attributes"]["flow_direction"], "source_to_target")  # 값 보존
            self.assertEqual((n["check_direction"]["basis"], n["check_direction"]["status"]),
                             (["attribute"], "declared"))
        self.assertFalse({u["check"] for u in r["validation"]["unknowns"]
                          if u["source_object_id"] in cvs})

    def test_registration_meta_and_run_id(self):
        r = drawio.extract(SAMPLE_101)
        self.assertEqual(r["review_status"], "not_reviewed")
        nr = [u["field"] for u in r["validation"]["unknowns"] if u["check"] == "not_registered"]
        self.assertEqual(sorted(nr), ["material_id", "project_id", "registration_version"])
        self.assertIn("-p0-", r["extraction_run_id"])
        self.assertIn(r["run"]["rules_version"], r["extraction_run_id"])


class GeometryEdgeCaseTest(unittest.TestCase):
    """좌표 파싱·상대 좌표·parent 순환."""

    def extract_with(self, extra):
        text = read_text(SAMPLE_101).replace("</root>", extra + "</root>", 1)
        return drawio.extract(write_temp(self, text))

    def node(self, r, cid):
        return [n for n in r["nodes"] if n["source_object_id"] == cid][0]

    def loc(self, r, cid):
        found = [l for l in r["source_locations"] if l["object_id"] == cid]
        return found[0] if found else None

    def test_bad_number_is_error_not_zero(self):
        r = self.extract_with('<object id="b1" kind="pump" tag="P-X"><mxCell style="" vertex="1" parent="1">'
                              '<mxGeometry x="10" y="10" width="bad" height="20" as="geometry"/></mxCell></object>')
        self.assertEqual(r["validation"]["status"], "blocked")
        self.assertIn("invalid_number", [b["check"] for b in r["validation"]["blockers"]])
        self.assertIsNone(self.loc(r, "b1"))
        self.assertEqual(self.node(r, "b1")["geometry"]["width"], "bad")  # 원문 보존, 0으로 바꾸지 않음

    def test_bad_style_numbers_are_errors(self):
        r = self.extract_with('<object id="b2" kind="pump" tag="P-Y" label="P-Y"><mxCell style="rotation=abc;fontSize=big;" '
                              'vertex="1" parent="1"><mxGeometry x="10" y="10" width="20" height="20" as="geometry"/>'
                              '</mxCell></object>')
        bad = {b["field"] for b in r["validation"]["blockers"]
               if b["check"] == "invalid_number" and b["source_object_id"] == "b2"}
        self.assertEqual(bad, {"style.rotation", "style.fontSize"})
        self.assertEqual(r["validation"]["status"], "blocked")
        self.assertIn("rotation=abc", self.node(r, "b2")["style"])  # 원문 보존

    def test_self_and_cyclic_parent_block(self):
        r = self.extract_with('<mxCell id="s1" style="" vertex="1" parent="s1"><mxGeometry x="1" y="1" width="5" height="5" as="geometry"/></mxCell>'
                              '<mxCell id="c1" style="" vertex="1" parent="c2"><mxGeometry x="1" y="1" width="5" height="5" as="geometry"/></mxCell>'
                              '<mxCell id="c2" style="" vertex="1" parent="c1"><mxGeometry x="1" y="1" width="5" height="5" as="geometry"/></mxCell>')
        cyc = {b["source_object_id"] for b in r["validation"]["blockers"] if b["check"] == "parent_cycle"}
        self.assertEqual(cyc, {"s1", "c1", "c2"})
        for cid in ("s1", "c1", "c2"):
            self.assertIsNone(self.loc(r, cid))

    def test_child_of_vertex_absolute_offset(self):
        # n1: x=260 y=430 w=110 h=280. 일반 자식 좌표는 부모 원점 기준(mxGraph 규칙)으로 정확히 계산
        r = self.extract_with('<object id="k1" kind="pump" tag="P-K"><mxCell style="" vertex="1" parent="n1">'
                              '<mxGeometry x="10" y="20" width="5" height="6" as="geometry"/></mxCell></object>')
        loc = self.loc(r, "k1")
        self.assertEqual(loc["bbox"], [270, 450, 5, 6])
        self.assertFalse(loc["approximate"])

    def test_relative_child_is_approximate(self):
        r = self.extract_with('<object id="k2" kind="pump" tag="P-K2"><mxCell style="" vertex="1" parent="n1">'
                              '<mxGeometry x="0.5" y="0.5" width="10" height="10" relative="1" as="geometry">'
                              '<mxPoint x="-5" y="-5" as="offset"/></mxGeometry></mxCell></object>')
        loc = self.loc(r, "k2")
        self.assertEqual(loc["bbox"], [260 + 55 - 5, 430 + 140 - 5, 10, 10])
        self.assertTrue(loc["approximate"])
        self.assertIn("approximate_geometry", all_issue_checks(r))

    def test_relative_child_of_layer_has_no_bbox(self):
        r = self.extract_with('<object id="k3" kind="pump" tag="P-K3"><mxCell style="" vertex="1" parent="1">'
                              '<mxGeometry x="0.5" y="0.5" width="10" height="10" relative="1" as="geometry"/></mxCell></object>')
        self.assertIsNone(self.loc(r, "k3"))
        self.assertIn("missing_geometry", all_issue_checks(r))

    def test_edge_label_cell_is_relation_label_not_node(self):
        r = self.extract_with('<mxCell id="lb1" value="LINE LABEL" style="edgeLabel;html=1;" vertex="1" connectable="0" parent="e7">'
                              '<mxGeometry x="-0.2" relative="1" as="geometry"><mxPoint as="offset"/></mxGeometry></mxCell>')
        self.assertNotIn("lb1", {n["source_object_id"] for n in r["nodes"] + r["texts"]})
        e7 = [x for x in r["relations"] if x["source_object_id"] == "e7"][0]
        self.assertEqual([lc["text"] for lc in e7["label_cells"]], ["LINE LABEL"])
        self.assertEqual(r["summary"]["edge_label_cells"], 1)
        self.assertEqual(r["validation"]["status"], "passed")


class RelationCrossCheckTest(unittest.TestCase):
    """모든 샘플의 커넥터 전체를 원본 XML과 대조: 양 끝 대상, line_no, line_type, 방향."""

    def test_all_connectors_match_xml(self):
        for path in SAMPLES:
            with self.subTest(sample=os.path.basename(path)):
                r = drawio.extract(path)
                rels = {x["source_object_id"]: x for x in r["relations"] + r["unresolved_connectors"]}
                node_src = {n["local_id"]: n["source_object_id"] for n in r["nodes"]}
                edges = [o for o in ET.parse(path).getroot().iter("object")
                         if o.find("mxCell").get("edge") == "1"]
                self.assertEqual(len(edges), len(rels))
                for o in edges:
                    cell, rel = o.find("mxCell"), rels[o.get("id")]
                    src, tgt = rel["endpoints"]
                    self.assertEqual((src["end"], tgt["end"]), ("source", "target"))
                    self.assertEqual(src["source_object_id"], cell.get("source"))
                    self.assertEqual(tgt["source_object_id"], cell.get("target"))
                    self.assertEqual(node_src[src["node_local_id"]], cell.get("source"))
                    self.assertEqual(node_src[tgt["node_local_id"]], cell.get("target"))
                    self.assertEqual(rel["line_no"], o.get("line_no"))
                    self.assertEqual(rel["line_type"], o.get("line_type"))
                    if o.get("flow_direction") == "source_to_target":
                        self.assertEqual((rel["flow_direction"]["from"], rel["flow_direction"]["to"]),
                                         (src["node_local_id"], tgt["node_local_id"]))
                    else:
                        self.assertIsNone(rel["flow_direction"])


SAMPLE_BY_KEY = {os.path.basename(p).split("_")[0]: p for p in SAMPLES}
SYMBOL_KEY = ("mxgraph.pid2valves.valve", "check")
CV_CODES = {"invalid_flow_direction", "unknown_check_valve_direction", "check_valve_direction_ambiguous",
            "check_valve_direction_conflict"}
# 기획서/정보추출.md 샘플 표 8건: (도면, 밸브) -> (입구, 출구)
CV_SAMPLE_TABLE = {("SNP-M-301", "n14"): ("e16", "e17"), ("SNP-M-301", "n22"): ("e24", "e25"),
                   ("SNP-M-101", "n38"): ("e39", "e40"), ("SNP-M-101", "n42"): ("e43", "e44"),
                   ("SNP-M-201", "n32"): ("e36", "e37"), ("SNP-M-401", "n12"): ("e14", "e17"),
                   ("SNP-M-401", "n13"): ("e15", "e18"), ("SNP-M-501", "n32"): ("e33", "e35")}


def extract_sample(test, key, edits=()):
    """샘플 key를 (old, new) 치환으로 고쳐 추출한다(각 old는 원본에 정확히 1번 있어야 함)."""
    text = read_text(SAMPLE_BY_KEY[key])
    for old, new in edits:
        test.assertEqual(text.count(old), 1, old)
        text = text.replace(old, new)
    return drawio.extract(write_temp(test, text) if edits else SAMPLE_BY_KEY[key])


def inject_symbol(d0=(1, 0)):
    """기호 등록표 주입(등록은 사람 승인 전이라 테스트에서만)."""
    return mock.patch.dict(rules.CHECK_VALVE_SYMBOL_DIRECTIONS, {SYMBOL_KEY: d0})


def node_by_obj(r, obj):
    return [n for n in r["nodes"] if n["source_object_id"] == obj][0]


def cv_view(r, obj):
    """밸브 obj의 (입구 객체 ID, 출구 객체 ID, basis, status) 또는 None, 그리고 밸브 대상 체크밸브 미확인 코드 목록."""
    src = {x["local_id"]: x["source_object_id"] for x in r["nodes"] + r["relations"] + r["unresolved_connectors"]}
    n = node_by_obj(r, obj)
    cd = n["check_direction"]
    view = None if cd is None else (src[cd["inlet"]], src[cd["outlet"]], cd["basis"], cd["status"])
    codes = [u["check"] for u in r["validation"]["unknowns"]
             if u["target"] == n["local_id"] and u["check"] in CV_CODES]
    return view, codes


N14_FD = 'tag="SI-V003" flow_direction="source_to_target"'
N14_NO_FD = (N14_FD, 'tag="SI-V003"')
N14_STYLE = "valveType=check;fontSize=10;verticalLabelPosition=top;verticalAlign=bottom;labelPosition=center;align=center;\" vertex=\"1\" parent=\"1\"><mxGeometry x=\"800\""
EXTRA_PIPE_N14 = ("</root>", '<object id="x9" label="" line_type="process"><mxCell style="" edge="1" parent="1" '
                  'source="n14" target="n15"><mxGeometry relative="1" as="geometry"/></mxCell></object></root>')


class CheckValveDirectionTest(unittest.TestCase):
    """기획서/정보추출.md #check-valve-direction 독립 검증 사례."""

    def test_samples_declared_by_attribute(self):  # 정상(①)
        for (key, obj), (inlet, outlet) in CV_SAMPLE_TABLE.items():
            with self.subTest(sample=key, valve=obj):
                r = extract_sample(self, key)
                self.assertEqual(cv_view(r, obj), ((inlet, outlet, ["attribute"], "declared"), []))
        for key in SAMPLE_BY_KEY:
            r = extract_sample(self, key)
            self.assertFalse([u for u in r["validation"]["unknowns"] if u["check"] in CV_CODES])
            self.assertEqual(sum(1 for n in r["nodes"] if n["kind"] == "check_valve"),
                             sum(1 for k, _ in CV_SAMPLE_TABLE if k == key))

    def test_samples_attribute_and_symbol(self):  # 정상(①+②), 실제 모순
        with inject_symbol():
            for (key, obj), (inlet, outlet) in CV_SAMPLE_TABLE.items():
                with self.subTest(sample=key, valve=obj):
                    r = extract_sample(self, key)
                    if (key, obj) == ("SNP-M-201", "n32"):
                        self.assertEqual(cv_view(r, obj), (None, ["check_valve_direction_conflict"]))
                    else:
                        self.assertEqual(cv_view(r, obj),
                                         ((inlet, outlet, ["attribute", "symbol"], "declared"), []))

    def test_synthetic_conflict_flip(self):  # 모순(합성)
        with inject_symbol():
            r = extract_sample(self, "SNP-M-301", [(N14_STYLE, N14_STYLE.replace("valveType=check;", "valveType=check;flipH=1;"))])
        self.assertEqual(cv_view(r, "n14"), (None, ["check_valve_direction_conflict"]))

    def test_symbol_undecidable_keeps_attribute(self):  # ② 판정 불가 시 ① 유지 (rotation=45 -> ② 없음)
        with inject_symbol():
            r = extract_sample(self, "SNP-M-301", [(N14_STYLE, N14_STYLE.replace("valveType=check;", "valveType=check;rotation=45;"))])
        self.assertEqual(cv_view(r, "n14"), (("e16", "e17", ["attribute"], "declared"), []))

    def test_no_basis(self):  # 근거 없음
        r = extract_sample(self, "SNP-M-301", [N14_NO_FD])
        n = node_by_obj(r, "n14")
        self.assertEqual(cv_view(r, "n14"), (None, ["unknown_check_valve_direction"]))
        u = [u for u in r["validation"]["unknowns"] if u["check"] == "unknown_check_valve_direction"]
        self.assertEqual([(x["target"], x["source_object_id"], x["field"]) for x in u],
                         [(n["local_id"], "n14", "flow_direction")])
        self.assertEqual(r["validation"]["status"], "passed")

    def test_self_loop(self):  # 자기 루프
        with inject_symbol():
            r = extract_sample(self, "SNP-M-301", [N14_NO_FD, ('source="n14" target="n15"', 'source="n14" target="n14"')])
        self.assertEqual(cv_view(r, "n14"), (None, ["check_valve_direction_ambiguous"]))

    def test_valve_inside_parent_shape(self):  # 부모 도형 안 밸브 -> ② 없음
        grp = '<mxCell id="grp1" style="" vertex="1" parent="1"><mxGeometry x="0" y="0" width="10" height="10" as="geometry"/></mxCell>'
        with inject_symbol():
            r = extract_sample(self, "SNP-M-301", [(N14_STYLE, N14_STYLE.replace('parent="1"', 'parent="grp1"')),
                                                   ("</root>", grp + "</root>")])
        self.assertEqual(r["source_locations"][[l["object_id"] for l in r["source_locations"]].index("n14")]["bbox"],
                         [800, 385, 50, 30])  # 좌표는 그대로(부모 원점 0,0)
        self.assertEqual(cv_view(r, "n14"), (("e16", "e17", ["attribute"], "declared"), []))

    def test_symbol_only(self):  # ② 단독 (flipH=1 기호)
        with inject_symbol():
            r = extract_sample(self, "SNP-M-501", [('tag="FW-V502" flow_direction="source_to_target"', 'tag="FW-V502"')])
        self.assertEqual(cv_view(r, "n32"), (("e33", "e35", ["symbol"], "symbol"), []))

    def test_symmetric_conflict(self):  # 대칭 충돌: 출구 쪽 커넥터가 밸브로 들어오는 확인된 흐름
        with inject_symbol():
            r = extract_sample(self, "SNP-M-301", [N14_NO_FD, ('source="n14" target="n15"', 'source="n15" target="n14"')])
        self.assertEqual(cv_view(r, "n14"), (None, ["check_valve_direction_conflict"]))

    def test_invalid_value(self):  # 잘못된 값
        bad = (N14_FD, 'tag="SI-V003" flow_direction="target_to_source"')
        r = extract_sample(self, "SNP-M-301", [bad])
        self.assertEqual(cv_view(r, "n14"), (None, ["invalid_flow_direction"]))
        self.assertEqual(node_by_obj(r, "n14")["attributes"]["flow_direction"], "target_to_source")
        r = extract_sample(self, "SNP-M-301", [bad, EXTRA_PIPE_N14])  # 잘못된 값 + 분기
        self.assertEqual(cv_view(r, "n14"), (None, ["invalid_flow_direction"]))

    def test_branch(self):  # 분기
        r = extract_sample(self, "SNP-M-301", [EXTRA_PIPE_N14])
        self.assertEqual(cv_view(r, "n14"), (None, ["check_valve_direction_ambiguous"]))

    def test_missing_one_connection(self):  # 한쪽 연결 누락
        text = read_text(SAMPLE_BY_KEY["SNP-M-301"])
        e17 = re.search(r'<object id="e17".*?</object>', text).group(0)
        r = extract_sample(self, "SNP-M-301", [(e17, "")])
        self.assertEqual(cv_view(r, "n14"), (None, ["check_valve_direction_ambiguous"]))

    def test_unresolved_connector(self):  # 미해결 커넥터
        r = extract_sample(self, "SNP-M-301", [('source="n14" target="n15"', 'source="n14"')])
        self.assertIn("e17", {x["source_object_id"] for x in r["unresolved_connectors"]})
        self.assertEqual(cv_view(r, "n14"), (None, ["check_valve_direction_ambiguous"]))

    def test_no_propagation_to_pipe(self):  # 비전파
        old = '<object id="e16" label="SI-L002" line_type="process" line_no="SI-L002" flow_direction="source_to_target">'
        r = extract_sample(self, "SNP-M-301", [(old, old.replace(' flow_direction="source_to_target"', ""))])
        self.assertEqual(cv_view(r, "n14"), (("e16", "e17", ["attribute"], "declared"), []))
        e16 = [x for x in r["relations"] if x["source_object_id"] == "e16"][0]
        self.assertIsNone(e16["flow_direction"])
        self.assertIn(("unknown_flow_direction", e16["local_id"]),
                      {(u["check"], u["target"]) for u in r["validation"]["unknowns"]})

    def test_registry_empty_by_default(self):
        self.assertEqual(rules.CHECK_VALVE_SYMBOL_DIRECTIONS, {})
        self.assertNotIn("check_valve", rules.KINDS_NEED_NORMAL_POSITION)


def missing_ports(test, key=None, edits=()):
    """샘플 6세트 전체의 missing_port 합계와 고친 샘플의 추출 결과."""
    total, edited = 0, None
    for k in SAMPLE_BY_KEY:
        r = extract_sample(test, k, edits if k == key else ())
        total += sum(1 for u in r["validation"]["unknowns"] if u["check"] == "missing_port")
        if k == key:
            edited = r
    return total, edited


def conn(r, obj):
    return [x for x in r["relations"] + r["unresolved_connectors"] if x["source_object_id"] == obj][0]


E20 = '<object id="e20" '
E22 = '<object id="e22" '


class PortRuleTest(unittest.TestCase):
    """기획서/정보추출.md #port-rule 독립 검증 사례(SNP-M-401)."""

    def test_samples_missing_port_16(self):  # 샘플 원본
        want = {("SNP-M-101", "e10", "target_port"), ("SNP-M-101", "e12", "source_port"),
                ("SNP-M-101", "e50", "source_port"), ("SNP-M-101", "e52", "target_port"),
                ("SNP-M-201", "e9", "target_port"), ("SNP-M-201", "e10", "source_port"),
                ("SNP-M-201", "e37", "target_port"), ("SNP-M-201", "e39", "source_port"),
                ("SNP-M-201", "e11", "target_port"), ("SNP-M-201", "e13", "source_port"),
                ("SNP-M-201", "e43", "target_port"), ("SNP-M-201", "e45", "source_port"),
                ("SNP-M-401", "e20", "target_port"), ("SNP-M-401", "e22", "source_port"),
                ("SNP-M-401", "e46", "target_port"), ("SNP-M-401", "e48", "source_port")}
        got = []
        for k in SAMPLE_BY_KEY:
            r = extract_sample(self, k)
            self.assertEqual(r["validation"]["status"], "passed")
            for u in r["validation"]["unknowns"]:
                if u["check"] == "missing_port":
                    self.assertEqual(u["target"], conn(r, u["source_object_id"])["local_id"])
                    got.append((k, u["source_object_id"], u["field"]))
            self.assertNotIn("ambiguous_port", all_issue_checks(r))
            for x in r["relations"] + r["unresolved_connectors"]:
                self.assertEqual([ep["port"] for ep in x["endpoints"]], [None, None])
        self.assertEqual(len(got), 16)
        self.assertEqual(set(got), want)

    def test_target_port(self):  # 정상
        total, r = missing_ports(self, "SNP-M-401", [(E20, E20 + 'target_port="tube_in" ')])
        self.assertEqual(conn(r, "e20")["endpoints"][1]["port"], "tube_in")
        self.assertEqual(total, 15)

    def test_port_whitespace_trimmed(self):  # 공백
        total, r = missing_ports(self, "SNP-M-401", [(E20, E20 + 'target_port="  tube_in " ')])
        self.assertEqual(conn(r, "e20")["endpoints"][1]["port"], "tube_in")
        self.assertEqual(conn(r, "e20")["attributes"]["target_port"], "  tube_in ")
        self.assertEqual(total, 15)

    def test_empty_port_is_missing(self):  # 빈 값
        for value in ("", "   "):
            with self.subTest(value=value):
                total, r = missing_ports(self, "SNP-M-401", [(E20, E20 + 'target_port="%s" ' % value)])
                self.assertIsNone(conn(r, "e20")["endpoints"][1]["port"])
                self.assertEqual(total, 16)

    def test_source_side_equipment(self):  # source 쪽 기기
        total, r = missing_ports(self, "SNP-M-401", [(E22, E22 + 'source_port="tube_out" ')])
        self.assertEqual(conn(r, "e22")["endpoints"][0]["port"], "tube_out")
        self.assertEqual(total, 15)

    def test_not_port_target(self):  # 대상 아님 (pump -> check_valve)
        total, r = missing_ports(self, "SNP-M-401")
        e14 = conn(r, "e14")
        self.assertEqual([ep["port"] for ep in e14["endpoints"]], [None, None])
        self.assertFalse([u for u in r["validation"]["unknowns"] if u["target"] == e14["local_id"]])
        self.assertEqual(total, 16)

    def test_port_without_end_is_ambiguous(self):  # 모호
        total, r = missing_ports(self, "SNP-M-401", [(E20, E20 + 'port="shell_in" ')])
        self.assertEqual([u["field"] for u in r["validation"]["unknowns"] if u["check"] == "ambiguous_port"], ["port"])
        self.assertIn(("missing_port", "e20", "target_port"),
                      {(u["check"], u["source_object_id"], u["field"]) for u in r["validation"]["unknowns"]})
        self.assertEqual([ep["port"] for ep in conn(r, "e20")["endpoints"]], [None, None])
        self.assertEqual(conn(r, "e20")["attributes"]["port"], "shell_in")
        self.assertEqual(total, 16)

    def test_port_with_end_port(self):  # 병존
        total, r = missing_ports(self, "SNP-M-401", [(E20, E20 + 'port="shell_in" target_port="tube_in" ')])
        self.assertEqual(conn(r, "e20")["endpoints"][1]["port"], "tube_in")
        self.assertEqual(all_issue_checks(r).count("ambiguous_port"), 1)
        self.assertEqual(total, 15)

    def test_detached_end_keeps_port(self):  # 끝이 붙지 않음
        total, r = missing_ports(self, "SNP-M-401", [(E22, E22 + 'source_port="tube_out" '),
                                                     ('source="n19" target="j21"', 'target="j21"')])
        self.assertIn("e22", {x["source_object_id"] for x in r["unresolved_connectors"]})
        self.assertEqual(conn(r, "e22")["endpoints"][0]["port"], "tube_out")
        self.assertEqual([u["source_object_id"] for u in r["validation"]["unknowns"]
                          if u["check"] == "unconnected_endpoint"], ["e22"])
        self.assertEqual(total, 15)

    def test_constraint_not_port(self):  # 위치로 추정 금지
        total, r = missing_ports(self, "SNP-M-401")
        tgt = conn(r, "e20")["endpoints"][1]
        self.assertEqual(tgt["constraint"]["x"], 0)
        self.assertIsNone(tgt["port"])
        self.assertEqual(total, 16)


class OutputPathTest(unittest.TestCase):

    def test_safe_name(self):
        self.assertEqual(paths.safe_name("SNP-M-101"), "SNP-M-101")
        for bad in ("../../evil", "a/b\\c", "..", "CON", "", "x:y*?"):
            name = paths.safe_name(bad)
            self.assertNotRegex(name, r"[\\/:*?]")
            self.assertNotIn(name, ("", ".", ".."))
            self.assertNotEqual(name.upper(), "CON")

    def test_safe_join_rejects_escape(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        for bad in ("..", "../x", os.path.join("..", "..", "x"), "", "."):
            with self.assertRaises(ValueError):
                paths.safe_join(root, bad)
        self.assertTrue(paths.safe_join(root, "ok").startswith(os.path.realpath(root)))

    def test_cli_writes_inside_out_root_for_hostile_drawing_number(self):
        text = read_text(SAMPLE_101).replace('value="SNP-M-101"', 'value="../../evil"', 1)
        src = write_temp(self, text)
        out_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out_root, True)
        result, out_dir = extract_drawio.run_one(src, out_root, svg=None)
        self.assertEqual(result["drawing"]["drawing_number"], "../../evil")
        self.assertEqual(os.path.dirname(out_dir), os.path.realpath(out_root))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "extraction.json")))


class SvgAlignmentTest(unittest.TestCase):

    def svg_101(self):
        return glob.glob(os.path.join(os.path.dirname(SAMPLE_101), "*.drawio.svg"))[0]

    def test_offset_verified_for_all_samples(self):
        for path in SAMPLES:
            with self.subTest(sample=os.path.basename(path)):
                svgs = glob.glob(os.path.join(os.path.dirname(path), "*.drawio.svg"))
                self.assertEqual(len(svgs), 1)
                al = svg_align.align(svgs[0], drawio.extract(path))
                self.assertEqual(al["status"], "verified", al["reasons"])
                self.assertEqual(al["offset"], [19.0, 19.0])
                self.assertGreater(al["compared_cells"], 10)
                self.assertEqual(al["inconsistent_offsets"], [])
                self.assertEqual(al["cells_missing_in_svg"], [])

    def wrapped_svg(self, transform):
        text = read_text(self.svg_101())
        self.assertIn('<g data-cell-id="0">', text)
        text = text.replace('<g data-cell-id="0">', '<g transform="%s"><g data-cell-id="0">' % transform, 1)
        text = text.replace("</svg>", "</g></svg>")
        return write_temp(self, text, "w.svg")

    def test_ancestor_translate_is_applied(self):
        al = svg_align.align(self.wrapped_svg("translate(10,5)"), drawio.extract(SAMPLE_101))
        self.assertEqual(al["status"], "verified")
        self.assertEqual(al["offset"], [9.0, 14.0])

    def test_ancestor_scale_fails(self):
        al = svg_align.align(self.wrapped_svg("scale(2)"), drawio.extract(SAMPLE_101))
        self.assertEqual(al["status"], "failed")
        self.assertTrue(al["unsupported_transform_cells"])

    def test_local_shape_transform_only_excluded(self):
        al = svg_align.align(self.svg_101(), drawio.extract(SAMPLE_101))
        self.assertEqual(al["status"], "verified")
        self.assertIn("n2", al["excluded_local_transform_cells"])  # flipV 도형


if __name__ == "__main__":
    unittest.main()
