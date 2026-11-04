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
import xml.etree.ElementTree as ET
import zlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import extract_drawio  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.extract import drawio, svg_align  # noqa: E402

SAMPLES = sorted(glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio")))
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


    def test_check_valve_direction_kept_but_unresolved(self):
        r = drawio.extract(SAMPLE_101)
        cvs = [n for n in r["nodes"] if n["kind"] == "check_valve"]
        self.assertTrue(cvs)
        listed = {u["source_object_id"] for u in r["validation"]["unknowns"]
                  if u["check"] == "check_valve_direction_basis_unresolved"}
        for n in cvs:
            self.assertEqual(n["attributes"]["flow_direction"], "source_to_target")  # 값 보존
            self.assertNotIn("flow_direction", {k for k in n if k != "attributes"})  # 방향 생성 안 함
            self.assertIn(n["source_object_id"], listed)

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
