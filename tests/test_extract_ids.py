"""추출 쪽 사실로 정한 id_basis(hazop.extract.ids)와 그래프 노드의 id_basis 시험. 실행: python -m unittest tests.test_extract_ids

어댑터를 실제로 돌려 나온 source_object_id 전부가 sequence·source 가운데 하나를 받고 '모름'이 없는지,
graph_version이 id_basis를 더하기 전과 같은지(추출 결과만 해시)를 본다."""

import copy
import glob
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop import paths  # noqa: E402
from hazop.extract import corrections, drawio, ids  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_read, pdf_vector, raster  # noqa: E402
from hazop.graph import build, project  # noqa: E402

SAMPLES = os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102_RCS-pressurizer")
DRAWIO = os.path.join(SAMPLES, "SNP-M-102_RCS-pressurizer.drawio")
PDF = os.path.join(SAMPLES, "SNP-M-102_RCS-pressurizer.pdf")
DEXPI = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi")
HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None
HAS_CV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None


def all_source_object_ids(extraction):
    """추출 결과 어디에든 source_object_id 열쇠로 적힌 값 전부(노드·관계·글자·끝점·버린 것·무시한 것·미해결 연결)."""
    found = []

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k == "source_object_id" and isinstance(x, str) and x:
                    found.append(x)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(extraction)
    return found


def graph_ids(graph):
    return [n["source_object_id"] for n in graph["nodes"]]


class BasisTableTest(unittest.TestCase):
    """판단표: (형식, id) -> 근거. 형식이 정하고, 연산이 만든 id만 형식과 무관하게 고정이다."""

    def test_vector_pdf_and_scan_are_sequence(self):
        for fmt in ("pdf_vector", "raster", "raster_png", "raster_jpeg", "raster_scan_pdf", "png", "jpeg"):
            self.assertEqual(ids.basis(fmt, "pdf-p0-sym-0012"), "sequence", fmt)
        self.assertEqual(ids.basis("raster", "img-sym-0012"), "sequence")
        self.assertEqual(ids.basis("pdf_vector", "pdf-p3-conn-0007"), "sequence")

    def test_drawio_and_dexpi_are_source_whatever_the_id_looks_like(self):
        for soid in ("n1", "cell-7", "pdf-p0-sym-0001", "img-sym-0001", "7f3a-b2"):
            self.assertEqual(ids.basis("drawio", soid), "source", soid)
            self.assertEqual(ids.basis("dexpi", soid), "source", soid)

    def test_operation_ids_are_source_in_every_format(self):
        for fmt in ("pdf_vector", "raster", "raster_png", "drawio", "dexpi", None):
            for soid in ("manual-c-0001", "pdf-p0-split-c-0003", "img-split-c-0003"):
                self.assertEqual(ids.basis(fmt, soid), "source", (fmt, soid))

    def test_unknown_format_is_sequence_whatever_the_id_looks_like(self):
        """형식을 모르면 id를 믿지 않는다(위치로 다시 확인하는 안전한 쪽). drawio처럼 형식이 분명한 것만 source."""
        for fmt in (None, "", "mystery"):
            for soid in ("pdf-p0-sym-0012", "img-conn-0003", "n12", "cell-7", None):
                self.assertEqual(ids.basis(fmt, soid), "sequence", (fmt, soid))

    def test_operation_id_stays_source_when_format_is_unknown(self):
        self.assertEqual(ids.basis(None, "manual-c-0001"), "source")
        self.assertEqual(ids.basis("mystery", "pdf-p0-split-c-0003"), "source")

    def test_known_format_beats_id_shape(self):
        self.assertEqual(ids.basis("drawio", "pdf-p0-sym-0001"), "source")
        self.assertEqual(ids.basis("pdf_vector", "weird-id"), "sequence")

    def test_adapter_made_id_is_sequence_in_a_fixed_format(self):
        self.assertEqual(ids.basis("dexpi", "Seg_1__Connection_2"), "source")
        self.assertEqual(ids.basis("dexpi", "Seg_1__Connection_2", made=True), "sequence")
        self.assertEqual(ids.basis("dexpi", "manual-c-0001", made=True), "source")

    def test_is_made_reads_only_facts_the_importer_wrote(self):
        self.assertTrue(ids.is_made({"id_made": True}))
        self.assertTrue(ids.is_made({"evidence": {"dexpi": {"id": None}}}))
        self.assertFalse(ids.is_made({"evidence": {"dexpi": {"id": "P-1"}}}))
        self.assertFalse(ids.is_made({"evidence": {"dexpi": {}}}))
        self.assertFalse(ids.is_made({"source_object_id": "n1"}))
        self.assertTrue(ids.is_made({"source_object_id": "Seg__item_2"}, {"Seg__item_2"}))
        self.assertFalse(ids.is_made(None))

    def test_importer_constants_match_the_ids_module(self):
        self.assertEqual(ids.PROTEUS_FLAVOR, dexpi_read.FMT_PROTEUS)
        self.assertEqual(ids.DEXPI_ITEM_WITHOUT_ID, "dexpi_item_without_id")

    def test_manual_prefix_is_one_constant(self):
        self.assertIs(corrections.MANUAL_PREFIX, ids.MANUAL_PREFIX)


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음: 시험용 venv로 실행할 것")
class VectorPdfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ext = pdf_vector.extract(PDF)
        cls.graph = build.build_graph(cls.ext)

    def test_every_id_the_adapter_made_is_sequence(self):
        found = all_source_object_ids(self.ext)
        self.assertGreater(len(found), 50)
        self.assertEqual(self.ext["source"]["format"], "pdf_vector")
        for soid in set(found):
            self.assertEqual(ids.basis(self.ext["source"]["format"], soid), "sequence", soid)

    def test_every_graph_node_has_a_basis_and_none_is_unknown(self):
        self.assertTrue(self.graph["nodes"])
        self.assertTrue(any(n["node_type"] == "pipe_segment" for n in self.graph["nodes"]))
        self.assertEqual({n.get("id_basis") for n in self.graph["nodes"]}, {"sequence"})

    def test_ids_really_are_enumeration_counters(self):
        pat = re.compile(r"^pdf-p\d+-[a-z]+-\d+$")
        self.assertTrue(all(pat.match(s) for s in graph_ids(self.graph)))

    def test_scan_retag_of_the_same_extraction_is_sequence(self):
        """OpenCV 없이: 스캔 어댑터가 같은 함수로 낸 결과의 id를 raster._retag로 바꾼 꼴(img-…)도 순번이다."""
        for fmt in ("raster", "raster_png", "raster_jpeg"):
            scan = raster._retag(copy.deepcopy(self.ext))
            scan["source"]["format"] = fmt
            found = all_source_object_ids(scan)
            self.assertTrue(any(s.startswith("img-sym-") for s in found))
            self.assertFalse(any(s.startswith("pdf-p0-") for s in found))
            self.assertEqual({ids.basis(fmt, s) for s in found}, {"sequence"}, fmt)
            g = build.build_graph(scan)
            self.assertEqual({n["id_basis"] for n in g["nodes"]}, {"sequence"}, fmt)

    def test_graph_version_comes_from_the_extraction_only(self):
        canon = json.dumps(self.ext, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        want = "v-" + hashlib.sha256((build.BUILDER_VERSION + "|" + canon).encode("utf-8")).hexdigest()[:12]
        self.assertEqual(self.graph["graph_version"], want)
        self.assertEqual(build.build_graph(copy.deepcopy(self.ext))["graph_version"], want)

    def test_human_edits_on_a_pdf_extraction_are_source(self):
        ops, base = [], self.ext
        a = base["nodes"][0]["source_object_id"]
        add = corrections.make_op(base, "add_node", None, {"category": "valve", "kind": "manual_valve",
                                                           "tag": "RC-V900", "bbox": [500, 500, 20, 20]}, "시험")
        ops.append(add)
        mid = "manual-" + add["op_id"]
        ops.append(corrections.make_op(base, "add_relation", None, {"kind": "physical_connection", "line_type": "process",
                                                                    "line_no": "RC-L900", "from": mid, "to": a}, "시험", existing_ops=ops))
        edited = corrections.apply(base, ops)
        self.assertEqual(edited["corrections"]["not_applicable"], [])
        g = build.build_graph(edited)
        manual = [n for n in g["nodes"] if n["source_object_id"].startswith("manual-")]
        self.assertEqual({n["node_type"] for n in manual}, {"drawing_object", "pipe_segment"})
        self.assertEqual({n["id_basis"] for n in manual}, {"source"})
        self.assertEqual({n["id_basis"] for n in g["nodes"] if n not in manual}, {"sequence"})
        self.assertEqual(g["graph_version"], build._graph_version(edited))


class DrawioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ext = drawio.extract(DRAWIO)
        cls.graph = build.build_graph(cls.ext)

    def test_every_id_the_adapter_made_is_source(self):
        found = all_source_object_ids(self.ext)
        self.assertGreater(len(found), 30)
        self.assertEqual(self.ext["source"]["format"], "drawio")
        self.assertEqual({ids.basis("drawio", s) for s in found}, {"source"})

    def test_every_graph_node_has_a_basis_and_none_is_unknown(self):
        self.assertEqual({n.get("id_basis") for n in self.graph["nodes"]}, {"source"})

    def test_human_edits_on_a_drawio_extraction_are_source(self):
        base = self.ext
        a = base["nodes"][0]["source_object_id"]
        add = corrections.make_op(base, "add_node", None, {"category": "valve", "kind": "manual_valve",
                                                           "tag": "RC-V900", "bbox": [500, 500, 20, 20]}, "시험")
        rel = corrections.make_op(base, "add_relation", None, {"kind": "physical_connection", "line_type": "process",
                                                               "line_no": "RC-L900", "from": "manual-" + add["op_id"], "to": a},
                                  "시험", existing_ops=[add])
        g = build.build_graph(corrections.apply(base, [add, rel]))
        self.assertEqual({n["id_basis"] for n in g["nodes"]}, {"source"})


def _dexpi_graph(raw):
    ext = dexpi_import.extract_bytes(raw.encode("utf-8") if isinstance(raw, str) else raw, "x.xml")[0]
    return ext, build.build_graph(ext)


def _segments(graph):
    """{source_object_id: (id_basis, 양 끝 태그 또는 id)} 구간만."""
    name = {n["entity_id"]: n.get("tag") or n["source_object_id"] for n in graph["nodes"]}
    out = {}
    for n in graph["nodes"]:
        if n["node_type"] == "pipe_segment":
            ends = sorted(name[e["node"]] for e in graph["edges"] if e["kind"] == "has_endpoint" and e["segment"] == n["entity_id"])
            out[n["source_object_id"]] = (n["id_basis"], ends)
    return out


class DexpiTest(unittest.TestCase):
    """DEXPI는 파일에 있던 id만 source다. 어댑터가 지은 id(Proteus Connection, 쪼갠 조각, ID 없는 부품·객체)는 sequence."""

    def read(self, name):
        with open(os.path.join(DEXPI, name), encoding="utf-8") as fh:
            return fh.read()

    def test_dexpi2_ids_all_come_from_the_file(self):
        ext, g = _dexpi_graph(self.read("small-pid-dexpi2.xml"))
        found = all_source_object_ids(ext)
        self.assertTrue(found)
        self.assertEqual(ext["source"]["format"], "dexpi")
        self.assertEqual({n["id_basis"] for n in g["nodes"]}, {"source"})

    def test_proteus_connection_segments_are_sequence_and_parts_are_source(self):
        ext, g = _dexpi_graph(self.read("small-pid-proteus.xml"))
        seg = [n for n in g["nodes"] if n["node_type"] == "pipe_segment"]
        self.assertTrue(seg)
        self.assertEqual({n["id_basis"] for n in seg}, {"sequence"}, [n["source_object_id"] for n in seg])
        self.assertTrue(all("__Connection_" in n["source_object_id"] for n in seg))
        parts = [n for n in g["nodes"] if n["node_type"] == "drawing_object"]
        self.assertTrue(parts)
        self.assertEqual({n["id_basis"] for n in parts}, {"source"})

    def test_revised_proteus_file_shifts_a_made_segment_id_and_it_is_marked_sequence(self):
        """Connection 한 줄을 지운 개정판을 다시 가져오면 Seg_1__Connection_2가 다른 배관을 가리킨다.
        그 id를 'source'(다시 추출해도 같은 기호)로 적으면 판 이전이 조용히 다른 배관으로 잇는다."""
        raw = self.read("small-pid-proteus.xml")
        gone = [l for l in raw.splitlines(True) if 'FromID="Valve-1"' in l and 'ToID="Tee-1"' in l]
        self.assertEqual(len(gone), 1)
        old, new = _segments(_dexpi_graph(raw)[1]), _segments(_dexpi_graph(raw.replace(gone[0], ""))[1])
        key = "Seg_1__Connection_2"
        self.assertNotEqual(old[key][1], new[key][1], "개정판에서 같은 id가 다른 배관을 가리켜야 이 시험이 뜻이 있다")
        self.assertEqual(old[key][0], "sequence")
        self.assertEqual(new[key][0], "sequence")

    def test_split_connection_piece_id_is_sequence(self):
        raw = self.read("small-pid-proteus.xml")
        gone = [l for l in raw.splitlines(True) if 'FromID="Valve-1"' in l and 'ToID="Tee-1"' in l][0]
        _, g = _dexpi_graph(raw.replace(gone, ""))
        pieces = [n for n in g["nodes"] if n["node_type"] == "pipe_segment" and re.search(r"__Connection_\d+_\d+$", n["source_object_id"])]
        self.assertTrue(pieces, [n["source_object_id"] for n in g["nodes"] if n["node_type"] == "pipe_segment"])
        self.assertEqual({n["id_basis"] for n in pieces}, {"sequence"})

    def test_part_without_id_gets_a_made_item_id_that_is_sequence(self):
        raw = self.read("small-pid-proteus.xml")
        victim = ' ID="Valve-1"'
        self.assertIn(victim, raw)
        ext, g = _dexpi_graph(raw.replace(victim, "", 1))
        warn = [u for u in ext["validation"]["unknowns"] if u["check"] == "dexpi_item_without_id"]
        self.assertEqual(len(warn), 1)
        made = [n for n in g["nodes"] if n["source_object_id"] == warn[0]["source_object_id"]]
        self.assertEqual([n["id_basis"] for n in made], ["sequence"])
        others = [n for n in g["nodes"] if n["node_type"] == "drawing_object" and n["source_object_id"] != warn[0]["source_object_id"]]
        self.assertEqual({n["id_basis"] for n in others}, {"source"})

    def test_dexpi2_connection_without_id_is_sequence(self):
        raw = self.read("small-pid-dexpi2.xml")
        self.assertIn('<Object id="Pipe2" type="Plant/Piping.Pipe">', raw)
        ext, g = _dexpi_graph(raw.replace('<Object id="Pipe2" type="Plant/Piping.Pipe">', '<Object type="Plant/Piping.Pipe">'))
        made = [r for r in ext["relations"] if r.get("id_made")]
        self.assertEqual(len(made), 1)
        by_soid = {n["source_object_id"]: n["id_basis"] for n in g["nodes"] if n["node_type"] == "pipe_segment"}
        self.assertEqual(by_soid[made[0]["source_object_id"]], "sequence")
        self.assertEqual(sorted(v for k, v in by_soid.items() if k != made[0]["source_object_id"]), ["source"] * (len(by_soid) - 1))

    def test_made_id_flag_is_sparse_in_the_extraction(self):
        ext, _ = _dexpi_graph(self.read("small-pid-dexpi2.xml"))
        self.assertFalse([r for r in ext["relations"] if "id_made" in r])


@unittest.skipUnless(HAS_CV, "OpenCV 없음(결정 D7: 래스터 전용 venv에서 실행)")
class RasterImageTest(unittest.TestCase):
    def test_real_raster_adapter_ids_are_sequence(self):
        import cv2
        import numpy as np
        img = np.full((842, 1191), 255, np.uint8)
        cv2.rectangle(img, (100, 100), (180, 160), 0, 2)
        cv2.rectangle(img, (400, 100), (480, 160), 0, 2)
        cv2.line(img, (181, 130), (399, 130), 0, 2)
        params = {"nominal_page_width_pt": 1191 / 2.75}
        w, h, words, prims, info = raster.detect(img, [], params)
        ext = raster.build_extraction(w, h, words, prims, info, "disabled", "synthetic.png", "0" * 64, "raster_png", params)
        found = all_source_object_ids(ext)
        self.assertTrue(any(s.startswith("img-") for s in found))
        self.assertEqual({ids.basis("raster_png", s) for s in found}, {"sequence"})
        self.assertEqual({n["id_basis"] for n in build.build_graph(ext)["nodes"]}, {"sequence"})


class OldGraphTest(unittest.TestCase):
    """id_basis가 없는 옛 graph.json을 읽는 길: 노드 값 -> 추출 파일의 source.format -> 글자 꼴."""

    @staticmethod
    def node(soid, **kw):
        return dict({"entity_id": "entity-node-001", "source_object_id": soid}, **kw)

    def test_node_value_wins(self):
        n = self.node("n1", id_basis="sequence")
        self.assertEqual(ids.node_basis(n, {"source": {"format": "drawio"}}), "sequence")

    def test_explicit_format_argument(self):
        self.assertEqual(ids.node_basis(self.node("anything"), None, fmt="pdf_vector"), "sequence")
        self.assertEqual(ids.node_basis(self.node("manual-c-0001"), None, fmt="pdf_vector"), "source")
        self.assertEqual(ids.node_basis(self.node("pdf-p0-sym-0001"), None, fmt="drawio"), "source")

    def test_graph_header_keeps_its_frame(self):
        g = build.build_graph(drawio.extract(DRAWIO))
        self.assertEqual(sorted(g["source"]), ["drawing_number", "extraction_file", "extraction_run_id", "file", "format", "material_id", "number",
                                            "page_count", "page_index", "page_name", "registration_version"])  # 판 칸(id_basis)은 머리 틀을 바꾸지 않음, 시트 정체 칸만 더함

    def test_extraction_file_format(self):
        with tempfile.TemporaryDirectory() as d:
            for name, fmt, want in (("a", "raster", "sequence"), ("b", "drawio", "source")):
                path = os.path.join(d, name + ".json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump({"source": {"format": fmt}}, fh)
                g = {"source": {"extraction_file": path}}
                self.assertEqual(ids.node_basis(self.node("cell-9"), g), want, name)

    def test_extraction_file_unreadable_is_sequence(self):
        g = {"source": {"extraction_file": os.path.join(tempfile.gettempdir(), "no-such-hazop-extraction.json")}}
        self.assertEqual(ids.node_basis(self.node("pdf-p0-sym-0001"), g), "sequence")
        self.assertEqual(ids.node_basis(self.node("n7"), g), "sequence")
        self.assertEqual(ids.node_basis(self.node("manual-c-0001"), g), "source")

    def test_no_source_at_all(self):
        self.assertEqual(ids.node_basis(self.node("img-sym-0003"), {}), "sequence")
        self.assertEqual(ids.node_basis(self.node("n7"), None), "sequence")

    def test_graph_source_that_is_not_a_dict_does_not_raise(self):
        for src in ("x", ["a"], 7, True):
            self.assertEqual(ids.node_basis(self.node("n7"), {"source": src}), "sequence", src)
            self.assertEqual(ids.node_basis(self.node("manual-c-0001"), {"source": src}), "source", src)
        for g in ("graph", ["g"], 3):
            self.assertEqual(ids.node_basis(self.node("n7"), g), "sequence", g)
        self.assertEqual(ids.node_basis(self.node("n7"), {"source": {"extraction_file": 5}}), "sequence")
        self.assertEqual(ids.node_basis(None, None), "sequence")

    def test_extraction_file_whose_source_is_not_a_dict_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            for body in ('{"source": "x"}', '[1]', '{"source": {"format": ["drawio"]}}', "not json"):
                path = os.path.join(d, "e.json")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(body)
                ids._FORMAT_CACHE.clear()
                self.assertEqual(ids.node_basis(self.node("cell-9"), {"source": {"extraction_file": path}}), "sequence", body)

    def test_old_graph_decided_by_extraction_not_by_shape(self):
        """drawio 셀 id가 순번 꼴이어도 추출 형식이 drawio면 고정이다. 정규식만 썼다면 틀렸을 경우."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "e.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"source": {"format": "drawio"}}, fh)
            g = {"source": {"extraction_file": path}}
            self.assertEqual(ids.node_basis(self.node("pdf-p0-sym-0001"), g), "source")


class ProjectGraphTest(unittest.TestCase):
    def test_project_graph_carries_id_basis_into_every_sheet_node(self):
        graphs = [build.build_graph(drawio.extract(DRAWIO))]
        pg = project.build(project.UNREGISTERED_PROJECT, graphs)
        sheet_nodes = [n for n in pg["nodes"] if n.get("sheet")]
        self.assertTrue(sheet_nodes)
        self.assertEqual({n.get("id_basis") for n in sheet_nodes}, {"source"})


class ProjectSheetLinkBasisTest(unittest.TestCase):
    """프로젝트 그래프의 id_basis: 시트 노드는 그 시트의 추출 파일에서, 도면 연결(xlink) 구간은 두 끝에서 정한다."""

    @staticmethod
    def pair(basis_a=None, basis_b=None, ext_dir=None, fmts=(None, None)):
        from tests.test_project_graph import cont, sheet
        gs = []
        for dn, other, kind, basis, fmt in (("A", "B", "TO", basis_a, fmts[0]), ("B", "A", "FROM", basis_b, fmts[1])):
            g = sheet(dn, cont("C1", "%s %s\nL-1" % (kind, other)))
            for n in g["nodes"]:
                if basis:
                    n["id_basis"] = basis
            if fmt:
                path = os.path.join(ext_dir, dn + ".json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump({"source": {"format": fmt}}, fh)
                g["source"]["extraction_file"] = path
            gs.append(g)
        return project.build("P", gs)

    @staticmethod
    def xlink(pg):
        found = [n for n in pg["nodes"] if str(n["entity_id"]).startswith("xlink-")]
        assert len(found) == 1, found
        return found[0]

    def test_xlink_is_source_only_when_both_ends_are_source(self):
        self.assertEqual(self.xlink(self.pair("source", "source"))["id_basis"], "source")
        self.assertEqual(self.xlink(self.pair("source", "sequence"))["id_basis"], "sequence")
        self.assertEqual(self.xlink(self.pair("sequence", "source"))["id_basis"], "sequence")
        self.assertEqual(self.xlink(self.pair("sequence", "sequence"))["id_basis"], "sequence")

    def test_old_sheet_graphs_are_read_from_each_sheets_own_extraction_file(self):
        with tempfile.TemporaryDirectory() as d:
            pg = self.pair(ext_dir=d, fmts=("drawio", "pdf_vector"))
            by_sheet = {}
            for n in pg["nodes"]:
                if n.get("sheet"):
                    by_sheet.setdefault(n["sheet"], set()).add(n["id_basis"])
            self.assertEqual(by_sheet, {"graph-A": {"source"}, "graph-B": {"sequence"}})
            self.assertEqual(self.xlink(pg)["id_basis"], "sequence")
            pg = self.pair(ext_dir=d, fmts=("drawio", "drawio"))
            self.assertEqual(self.xlink(pg)["id_basis"], "source")

    def test_old_sheet_graph_without_extraction_file_is_sequence(self):
        pg = self.pair()
        self.assertEqual({n["id_basis"] for n in pg["nodes"] if n.get("sheet")}, {"sequence"})
        self.assertEqual(self.xlink(pg)["id_basis"], "sequence")

    def test_every_project_node_has_a_basis(self):
        self.assertEqual({n.get("id_basis") for n in self.pair("source", "source")["nodes"]}, {"source"})
        self.assertEqual({n.get("id_basis") for n in self.pair()["nodes"]}, {"sequence"})

    def test_project_graph_version_does_not_depend_on_id_basis(self):
        self.assertEqual(self.pair("source", "source")["graph_version"], self.pair("sequence", "sequence")["graph_version"])


class ShapeOverlapTest(unittest.TestCase):
    def test_no_sample_id_starts_with_the_manual_prefix(self):
        for path in sorted(glob.glob(os.path.join(paths.folder("references", "pid-samples"), "*", "*.drawio"))):
            for s in all_source_object_ids(drawio.extract(path)):
                self.assertFalse(s.startswith(ids.MANUAL_PREFIX), (path, s))


if __name__ == "__main__":
    unittest.main()
