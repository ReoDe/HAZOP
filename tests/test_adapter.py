"""T3 W2 평가 하네스·W3 벡터 PDF 어댑터 테스트. 실행: python -m unittest tests.test_adapter

W3 샘플 시험은 pdfplumber가 있을 때만 돈다(결정 D1). 합성 원시 요소 시험은 pdfplumber 없이 돈다."""

import contextlib
import copy
import io
import glob
import importlib.util
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

import check_adapter  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.extract.adapters import align  # noqa: E402
from hazop.extract.adapters import evaluation as ev  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402

TRUTH = check_adapter.load_json(check_adapter.FIXTURE)


def prf_tuple(m):
    return m["tp"], m["fp"], m["fn"], m["precision"], m["recall"], m["f1"]


class HelperTest(unittest.TestCase):
    def test_normalize_text(self):
        self.assertEqual(ev.normalize_text("TT\n110"), "TT110")
        self.assertEqual(ev.normalize_text(" rc-v111 "), "RC-V111")
        self.assertEqual(ev.normalize_text("ＰＴ１０１"), "PT101")  # NFKC 전각
        self.assertEqual(ev.normalize_text(None), "")

    def test_hungarian_square_and_rectangular(self):
        cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
        pairs = ev.hungarian(cost)
        self.assertEqual(sum(cost[i][j] for i, j in pairs), 5)
        self.assertEqual(len(pairs), 3)
        tall = [[1, 9], [9, 1], [0, 0]]
        pairs = ev.hungarian(tall)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(sum(tall[i][j] for i, j in pairs), 1)
        self.assertEqual(ev.hungarian([]), [])

    def test_iou_and_prf(self):
        self.assertEqual(ev.iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)
        self.assertEqual(ev.iou([0, 0, 10, 10], [20, 20, 5, 5]), 0.0)
        self.assertAlmostEqual(ev.iou([0, 0, 10, 10], [5, 0, 10, 10]), 50 / 150)
        self.assertEqual(ev.prf(0, 0, 0)["f1"], None)
        self.assertEqual(ev.prf(3, 1, 1)["f1"], 0.75)
        # 정답은 있는데 후보가 비면 0(null 아님)
        self.assertEqual(ev.prf(0, 0, 4), {"tp": 0, "fp": 0, "fn": 4, "precision": 0.0, "recall": 0.0, "f1": 0.0})
        self.assertEqual(ev.prf(0, 2, 0)["f1"], 0.0)

    def test_parse_transform(self):
        self.assertEqual(ev.parse_transform({"scale": 2, "offset": [1, 2]}), (2.0, 2.0, 1.0, 2.0))
        self.assertEqual(ev.parse_transform({"scale": [1, -1], "offset": [0, 100]}), (1.0, -1.0, 0.0, 100.0))
        # y 반전: 후보 [10, 70, 20, 10](y 위쪽 증가) → 정답 y = 100 - 80 = 20
        self.assertEqual(ev._apply([10, 70, 20, 10], (1.0, -1.0, 0.0, 100.0)), [10.0, 20.0, 20.0, 10.0])
        for bad in ({"scale": 0}, {"scale": [1, 0]}, {"scale": "x"}, {"offset": [1]}, {"scale": float("inf")},
                    [1, 2]):
            with self.assertRaises(ValueError):
                ev.parse_transform(bad)


def mini(nodes, relations=(), cs=("page_local_2d", "canvas_unit")):
    """nodes: (local_id, kind, text, bbox). relations: (local_id, kind, a, b)."""
    ext = {"extraction_run_id": "mini",
           "nodes": [{"local_id": i, "source_object_id": i, "kind": k, "category": "x", "label_text": t,
                      "attributes": {}} for i, k, t, _ in nodes],
           "source_locations": [{"local_id": i, "bbox": list(b)} for i, _, _, b in nodes],
           "relations": [{"local_id": i, "kind": k, "endpoints": [{"node_local_id": a}, {"node_local_id": b}]}
                         for i, k, a, b in relations]}
    if cs:
        ext["coordinate_system"] = {"coordinate_space": cs[0], "unit": cs[1]}
    return ext


class ReworkCaseTest(unittest.TestCase):
    """검토 반려(1회차) 재현 사례."""

    def pairs(self, result):
        return {m["truth_local_id"]: m["candidate_local_id"] for m in result["matches"]}

    def test_iou_before_kind(self):
        # 두 정답이 서로 IoU 0.667로 겹친다. 후보는 위치 그대로이고 kind만 맞바뀜 → IoU 1 대응이 이겨야 한다.
        truth = mini([("a", "pump", "", (0, 0, 10, 10)), ("b", "valve", "", (2, 0, 10, 10))])
        cand = mini([("a2", "valve", "", (0, 0, 10, 10)), ("b2", "pump", "", (2, 0, 10, 10))])
        r = ev.evaluate(truth, cand)
        self.assertEqual(self.pairs(r), {"a": "a2", "b": "b2"})
        self.assertEqual(r["objects"]["kind_accuracy"], 0.0)

    def test_small_symbols_prefer_nearer_center(self):
        # 2x2 정답 x=0·6, 후보 c2 x=3·c1 x=9: 거리 합 최소는 t1-c2(3), t2-c1(3)
        truth = mini([("t1", "tee", "", (0, 0, 2, 2)), ("t2", "tee", "", (6, 0, 2, 2))])
        cand = mini([("c1", "tee", "", (9, 0, 2, 2)), ("c2", "tee", "", (3, 0, 2, 2))])
        r = ev.evaluate(truth, cand)
        self.assertEqual(self.pairs(r), {"t1": "c2", "t2": "c1"})
        self.assertEqual({m["basis"] for m in r["matches"]}, {"small_center"})

    def test_equal_cost_tie_break_follows_source_object_id(self):
        # 같은 자리에 겹친 tee 2개(비용 동일). 후보의 local_id 순서를 source_object_id와 반대로 두어도
        # 동점은 source_object_id 순으로 풀려야 한다(W1 §4.3, Codex W2 2차 지적).
        truth = mini([("t1", "tee", "", (0, 0, 2, 2)), ("t2", "tee", "", (0, 0, 2, 2))])
        cand = mini([("z1", "tee", "", (0, 0, 2, 2)), ("a2", "tee", "", (0, 0, 2, 2))])
        truth["nodes"][0]["source_object_id"], truth["nodes"][1]["source_object_id"] = "s1", "s2"
        cand["nodes"][0]["source_object_id"], cand["nodes"][1]["source_object_id"] = "s1", "s2"
        r = ev.evaluate(truth, cand)
        self.assertEqual(self.pairs(r), {"t1": "z1", "t2": "a2"})

    def test_unmatched_endpoint_cannot_collide_with_real_id(self):
        # 정답 노드 id가 "cand:x". 후보의 대응 안 된 노드 "x"가 같은 표식을 만들면 안 된다.
        truth = mini([("a", "pump", "A", (0, 0, 10, 10)), ("cand:x", "tank", "T", (100, 0, 10, 10))],
                     [("r1", "physical_connection", "a", "cand:x")])
        cand = mini([("a", "pump", "A", (0, 0, 10, 10)), ("x", "tank", "Z", (900, 900, 10, 10))],
                    [("r1", "physical_connection", "a", "x")])
        r = ev.evaluate(truth, cand)
        self.assertEqual(self.pairs(r), {"a": "a"})
        self.assertEqual((r["relations"]["tp"], r["relations"]["fp"], r["relations"]["fn"]), (0, 1, 1))

    def test_empty_candidate_scores_zero(self):
        truth = mini([("a", "pump", "A", (0, 0, 10, 10))], [])
        r = ev.evaluate(truth, mini([]))
        self.assertEqual((r["objects"]["f1"], r["tags"]["f1"]), (0.0, 0.0))
        self.assertIsNone(r["relations"]["f1"])  # 정답·후보 관계 모두 0개

    def test_spurious_text_node_is_tag_fp(self):
        cand = copy.deepcopy(TRUTH)
        cand["nodes"].append({"local_id": "ghost", "kind": "pump", "label_text": "XX-P99", "attributes": {}})
        cand["source_locations"].append({"local_id": "ghost", "bbox": [1500, 900, 40, 40]})
        r = ev.evaluate(TRUTH, cand)
        self.assertEqual((r["tags"]["tp"], r["tags"]["fp"], r["tags"]["fn"]), (5, 1, 0))
        self.assertEqual(r["tags"]["false_positive_candidates"], ["ghost"])
        self.assertEqual(r["tags"]["precision"], round(5 / 6, 6))

    def test_missing_coordinate_system_blocks(self):
        truth = mini([("a", "pump", "A", (0, 0, 10, 10))])
        r = ev.evaluate(truth, mini([("a", "pump", "A", (0, 0, 10, 10))], cs=None))
        self.assertEqual(r["status"], "blocked")
        self.assertIn("coordinate_system_missing: candidate (transform 없음)", r["reasons"])
        self.assertEqual(ev.evaluate(mini([], cs=None), truth, {"scale": 1})["status"], "blocked")
        ok = ev.evaluate(truth, mini([("a", "pump", "A", (0, 0, 10, 10))], cs=None), {"scale": 1})
        self.assertEqual(ok["status"], "ok")

    def test_duplicate_location_id_blocks(self):
        cand = copy.deepcopy(TRUTH)
        cand["source_locations"].append({"local_id": "local-node-001", "bbox": [0, 0, 1, 1]})
        r = ev.evaluate(TRUTH, cand)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["reasons"], ["duplicate_local_id: candidate source_locations:local-node-001"])

    def test_visible_is_token_based(self):
        self.assertTrue(ev.value_visible("XX-V01", ev.text_tokens("XX-V01\nGATE")))
        self.assertFalse(ev.value_visible("XX-V01", ev.text_tokens("XX-V011")))
        self.assertFalse(ev.value_visible("V01", ev.text_tokens("XX-V01")))
        self.assertTrue(ev.value_visible("17.2 MPa", ev.text_tokens("SET\n17.2 MPA")))
        self.assertFalse(ev.value_visible("", ev.text_tokens("A")))

    def test_flip_y_transform(self):
        cand = check_adapter.inject_page_transform(TRUTH, 0, 1200, 1, -1, "pdf_page_pt", "pt")
        r = ev.evaluate(TRUTH, cand, {"scale": [1, -1], "offset": [0, 1200]})
        self.assertEqual((r["objects"]["f1"], r["relations"]["f1"], r["tags"]["f1"]), (1.0, 1.0, 1.0))


class FixtureTest(unittest.TestCase):
    def run_eval(self, cand, tf=None):
        return ev.evaluate(TRUTH, cand, tf)

    def test_self_is_perfect(self):
        r = self.run_eval(copy.deepcopy(TRUTH))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(prf_tuple(r["objects"]), (6, 0, 0, 1.0, 1.0, 1.0))
        self.assertEqual(prf_tuple(r["relations"]), (5, 0, 0, 1.0, 1.0, 1.0))
        self.assertEqual((r["tags"]["exact"], r["tags"]["visible_total"], r["tags"]["accuracy"]), (5, 5, 1.0))
        self.assertEqual(r["tags"]["excluded_no_visible_text"], 1)  # tee
        self.assertEqual(r["ged"], {"status": "exact", "value": 0, "method": "isomorphism", "reason": None})
        self.assertEqual({m["basis"] for m in r["matches"]}, {"text", "iou"})

    def test_non_visual_attributes(self):
        r = self.run_eval(copy.deepcopy(TRUTH))
        nv = r["non_visual"]
        self.assertEqual(nv["nodes_with_tag_but_no_visible_text"], ["local-node-003"])
        # tag: n4(XX-PT101, 화면 PT 101)·j3(글자 없음)만 화면 근거 없음
        self.assertEqual(nv["by_attribute"]["tag"],
                         {"total": 6, "visible": 4, "non_visual": 2, "non_visual_recovered": 2})
        self.assertEqual(nv["by_attribute"]["normal_position"]["non_visual"], 1)
        self.assertNotIn("kind", nv["by_attribute"])

    def test_fault_expectations(self):
        node = check_adapter.pick_text_node(TRUTH)
        self.assertEqual(node, "local-node-001")
        r = self.run_eval(check_adapter.inject_node_drop(TRUTH, node))
        self.assertEqual(prf_tuple(r["objects"]), (5, 0, 1, 1.0, 0.833333, 0.909091))
        self.assertEqual(prf_tuple(r["relations"]), (4, 0, 1, 1.0, 0.8, 0.888889))
        self.assertEqual(r["unmatched_truth"], ["local-node-001"])

        r = self.run_eval(check_adapter.inject_tag_typo(TRUTH, node))
        self.assertEqual(r["tags"]["accuracy"], 0.8)
        self.assertEqual(r["tags"]["mismatches"],
                         [{"truth_local_id": "local-node-001", "truth_text": "XX-P01", "candidate_text": "XX-P0Q"}])
        self.assertEqual(r["objects"]["f1"], 1.0)

        rel1, rel2 = check_adapter.pick_swap(TRUTH)
        self.assertEqual((rel1, rel2), ("local-edge-001", "local-edge-005"))
        r = self.run_eval(check_adapter.inject_relation_swap(TRUTH, rel1, rel2))
        self.assertEqual(prf_tuple(r["relations"]), (3, 2, 2, 0.6, 0.6, 0.6))
        self.assertEqual(r["relations"]["false_negatives"], ["local-edge-001", "local-edge-005"])

        r = self.run_eval(check_adapter.inject_node_move(TRUTH, node))
        self.assertEqual(prf_tuple(r["objects"]), (5, 1, 1, 0.833333, 0.833333, 0.833333))
        self.assertEqual(prf_tuple(r["relations"]), (4, 1, 1, 0.8, 0.8, 0.8))

    def test_small_symbol_and_text_basis(self):
        cand = copy.deepcopy(TRUTH)
        check_adapter._shift_node(cand, "local-node-003", 3, 0)       # tee 2×2: IoU 0, 중심 거리 3
        check_adapter._shift_node(cand, "local-node-005", 30, 30)     # 큰 tank: IoU<0.5지만 글자 일치
        r = self.run_eval(cand)
        basis = {m["truth_local_id"]: m["basis"] for m in r["matches"]}
        self.assertEqual(basis["local-node-003"], "small_center")
        self.assertEqual(basis["local-node-005"], "text")
        self.assertEqual(r["relations"]["f1"], 1.0)

    def test_coordinate_normalization(self):
        cand = check_adapter.inject_page_transform(TRUTH, 20, 20, 2, 2, "image_px", "px")
        blocked = self.run_eval(cand)
        self.assertEqual(blocked["status"], "blocked")
        self.assertNotIn("objects", blocked)
        r = self.run_eval(cand, {"scale": 0.5, "offset": [-10, -10]})
        self.assertEqual(r["relations"]["f1"], 1.0)
        self.assertEqual(r["coordinate_normalization"]["basis"], "input_transform")
        shifted = check_adapter.inject_page_transform(TRUTH, 3000, 2000)
        self.assertEqual(self.run_eval(shifted)["objects"]["tp"], 0)

    def test_deterministic(self):
        cand = check_adapter.inject_relation_swap(TRUTH, "local-edge-001", "local-edge-005")
        a = ev.dumps(ev.evaluate(TRUTH, cand))
        b = ev.dumps(ev.evaluate(check_adapter.reverse_order(TRUTH), check_adapter.reverse_order(cand)))
        self.assertEqual(a, b)

    def test_suite_on_fixture(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_adapter.run_suite("fixture", TRUTH), [])

    def test_cli_writes_json_and_report(self):
        tmp = tempfile.mkdtemp()
        try:
            cand_path = os.path.join(tmp, "cand.json")
            with open(cand_path, "w", encoding="utf-8") as fh:
                json.dump(check_adapter.inject_node_drop(TRUTH, "local-node-001"), fh)
            out = os.path.join(tmp, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = check_adapter.main(["--truth", check_adapter.FIXTURE, "--candidate", cand_path, "--out", out])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "evaluation.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["objects"]["fn"], 1)
            with open(os.path.join(out, "evaluation.md"), encoding="utf-8") as fh:
                self.assertIn("관계(주 지표)", fh.read())
        finally:
            shutil.rmtree(tmp)


class CliGuardTest(unittest.TestCase):
    def test_out_overwriting_input_is_refused(self):
        tmp = tempfile.mkdtemp()
        try:
            truth = os.path.join(tmp, "evaluation.json")
            shutil.copy(check_adapter.FIXTURE, truth)
            with open(truth, "rb") as fh:
                before = fh.read()
            with contextlib.redirect_stdout(io.StringIO()):
                rc = check_adapter.main(["--truth", truth, "--candidate", check_adapter.FIXTURE, "--out", tmp])
                rc2 = check_adapter.main(["--truth", truth, "--candidate", check_adapter.FIXTURE, "--out", truth])
            self.assertEqual((rc, rc2), (2, 2))
            with open(truth, "rb") as fh:
                self.assertEqual(fh.read(), before)
            self.assertFalse(os.path.exists(os.path.join(tmp, "evaluation.md")))
        finally:
            shutil.rmtree(tmp)


class SampleTest(unittest.TestCase):
    def test_sample_102_suite(self):
        paths = [p for p in glob.glob(check_adapter.SAMPLE_GLOB) if "SNP-M-102" in p]
        self.assertEqual(len(paths), 1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_adapter.run_suite("SNP-M-102", drawio.extract(paths[0])), [])


# ---------------- T3 W3: 벡터 PDF 어댑터 ----------------
# 합성 원시 요소(pdf_vector.load_page와 같은 형식)로 규칙을 시험한다. pdfplumber 없이 돈다.

HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None


def prim(pts, closed=False, fill=False, white=False, curved=False, ext=None):
    return {"fill": fill, "stroke": not fill, "fill_white": fill and white, "stroke_white": False,
            "subpaths": [(list(pts), closed, list(ext or pts), curved)]}


def rect(x0, y0, x1, y1, **kw):
    return prim([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], closed=True, **kw)


def circle(cx, cy, r):
    pts = [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r), (cx + r, cy)]
    ext = pts + [(cx + r, cy + r), (cx - r, cy + r), (cx - r, cy - r), (cx + r, cy - r)]
    return prim(pts, closed=True, curved=True, ext=ext)


def line(*pts):
    return prim(pts)


def word(text, x0, top, size=6.0):
    return {"text": text, "x0": x0, "x1": x0 + 0.6 * size * len(text), "top": top, "bottom": top + size,
            "size": size}


def make_pdf(content, width=400, height=300):
    """내용 스트림 하나짜리 1쪽 PDF 바이트(메모리 시험용, 외부 라이브러리 없음)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R >>" % (width, height),
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def pdf_run(prims, words=(), width=600.0, height=400.0):
    analysis = pdf_vector.analyze(width, height, list(words), list(prims))
    return pdf_vector.build_extraction(analysis, width, height, 1, 0, "synthetic.pdf", "0" * 64)


class PdfVectorRuleTest(unittest.TestCase):
    def test_negative_or_nonfinite_dash_is_solid(self):
        # 음수·비유한 dash 값은 규격 밖이므로 실선 취급(0 나눔·무한 반복 방지, 검토 B1)
        for value in (([5, -5], 0), ([5, -6], 0), ([float("inf"), 2], 0), ([4, 2], float("nan"))):
            self.assertIsNone(pdf_vector._dash(value), value)
        self.assertEqual(pdf_vector._dash(([4, 2], 1)), [[4.0, 2.0], 1.0])

    def test_pipe_between_two_bodies(self):
        ext = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160), line((140, 130), (300, 130))])
        self.assertEqual(ext["validation"]["blockers"], [])
        self.assertEqual(len(ext["nodes"]), 2)
        self.assertEqual([r["kind"] for r in ext["relations"]], ["physical_connection"])
        self.assertEqual(ext["source"]["format"], "pdf_vector")
        self.assertEqual(ext["coordinate_system"]["coordinate_space"], "pdf_page_pt")
        self.assertEqual(ext["nodes"][0]["source_object_id"], "pdf-p0-sym-0001")
        self.assertEqual(ext["nodes"][0]["geometry"], {"x": 100, "y": 100, "width": 40, "height": 60})

    def test_three_line_junction_is_tee_and_crossing_is_not(self):
        tee = pdf_run([rect(100, 100, 140, 160), rect(300, 40, 340, 80), rect(300, 180, 340, 220),
                       line((140, 130), (200, 130)), line((200, 130), (200, 60), (300, 60)),
                       line((200, 130), (200, 200), (300, 200))])
        kinds = sorted(n["kind"] or "-" for n in tee["nodes"])
        self.assertEqual(kinds.count("tee"), 1)
        self.assertEqual(len(tee["relations"]), 3)
        tee_node = [n for n in tee["nodes"] if n["kind"] == "tee"][0]
        self.assertEqual(tee_node["geometry"], {"x": 199, "y": 129, "width": 2, "height": 2})
        cross = pdf_run([rect(100, 200, 120, 220), rect(300, 200, 320, 220), rect(200, 100, 220, 120),
                         rect(200, 300, 220, 320), line((120, 210), (300, 210)), line((210, 120), (210, 300))])
        self.assertNotIn("tee", [n["kind"] for n in cross["nodes"]])
        self.assertEqual(len(cross["relations"]), 2)

    def test_line_end_on_other_line_middle_is_tee(self):
        ext = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160), rect(200, 250, 240, 290),
                       line((140, 130), (300, 130)), line((220, 130), (220, 250))])
        self.assertEqual([n["kind"] for n in ext["nodes"]].count("tee"), 1)
        self.assertEqual(len(ext["relations"]), 3)

    def test_dashed_signal_measurement_and_isa_letters(self):
        dashes = [rect(x, 99.65, x + 4, 100.35, fill=True) for x in range(116, 184, 6)]
        ext = pdf_run([circle(100, 100, 14), circle(200, 100, 14), rect(80, 200, 120, 260),
                       line((100, 114), (100, 200))] + dashes,
                      [word("PT", 95, 92), word("101", 95, 99), word("FIC", 194, 92), word("102", 194, 99)])
        kinds = {n["label_text"]: n["kind"] for n in ext["nodes"]}
        self.assertEqual(kinds["PT\n101"], "transmitter")
        self.assertEqual(kinds["FIC\n102"], "controller")
        by_kind = sorted(r["kind"] for r in ext["relations"])
        self.assertEqual(by_kind, ["measurement_connection", "signal_connection"])
        self.assertEqual(ext["unresolved_connectors"], [])

    def test_labels_line_label_and_title_block(self):
        ext = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160), line((140, 130), (300, 130)),
                       rect(400, 300, 450, 315), rect(450, 300, 550, 315)],
                      [word("TK-01", 145, 112), word("TANK", 145, 119), word("L-001", 200, 127),
                       word("DWG", 402, 304), word("NO.", 418, 304), word("X-100", 452, 304)])
        labels = {n["label_text"]: n["kind"] for n in ext["nodes"]}
        self.assertEqual(labels.get("TK-01\nTANK"), "tank")
        self.assertEqual([t["text"] for t in ext["texts"]], ["L-001"])  # 선 위 글자는 선 라벨(노드 아님)
        self.assertEqual(ext["drawing"]["drawing_number"], "X-100")
        self.assertEqual(len(ext["nodes"]), 2)  # 표 칸은 기호가 아니다
        sample = [p for p in glob.glob(check_adapter.SAMPLE_GLOB) if "SNP-M-102" in p][0]
        self.assertEqual(check_adapter.schema_problems(ext, drawio.extract(sample)), [])

    def test_valve_shapes_and_actuator_mark(self):
        def bowtie(x, y):  # 두 삼각형이 가운데 꼭짓점을 맞댄 밸브 몸통 (폭 36, 높이 22)
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        dome = prim([(109, 80), (118, 75), (127, 80), (109, 80)], closed=True, curved=True)
        ext = pdf_run(bowtie(0, 100) + bowtie(100, 100) + [dome, line((118, 80), (118, 111))]
                      + bowtie(200, 100) + [rect(212, 70, 224, 82), line((218, 82), (218, 111))]
                      + [line((36, 111), (100, 111)), line((136, 111), (200, 111))],
                      [word("V-1", 5, 125), word("CV-1", 105, 125), word("MV-1", 205, 125), word("M", 216, 73)])
        kinds = {n["label_text"]: n["kind"] for n in ext["nodes"]}
        self.assertEqual(kinds, {"V-1": "manual_valve", "CV-1": "control_valve", "MV-1": "motor_operated_valve"})
        mv = [n for n in ext["nodes"] if n["label_text"] == "MV-1"][0]
        self.assertEqual(mv["evidence"]["symbol_marks"], ["M"])
        self.assertEqual(len(ext["relations"]), 2)

    def test_no_content_is_blocked(self):
        ext = pdf_run([])
        self.assertEqual(ext["validation"]["status"], "blocked")
        self.assertEqual([b["check"] for b in ext["validation"]["blockers"]], ["no_vector_content"])

    def test_deterministic_and_no_agpl_import(self):
        prims = [rect(100, 100, 140, 160), rect(300, 100, 340, 160), line((140, 130), (300, 130))]
        self.assertEqual(ev.dumps(pdf_run(prims)), ev.dumps(pdf_run(copy.deepcopy(prims))))
        for mod in (pdf_vector, align):
            with open(mod.__file__, encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotRegex(src, r"(?im)^\s*(import|from)\s+(fitz|pymupdf)\b")  # AGPL 금지(결정 D1)
            self.assertNotRegex(src, r"(?m)^(import|from) pdfplumber")  # 모듈 수준 import 금지(지연 import)

    def test_instrument_notations(self):
        for text in ("PT\n101", "PT\n101\nA1", "PT-101", "PT 101"):
            with self.subTest(text=text):
                self.assertEqual(pdf_vector._instrument_kind(text), ("transmitter", "isa_letters:PT"))
                ext = pdf_run([circle(100, 100, 14)], [word(t, 95, 92 + 7 * i) for i, t in enumerate(text.split("\n"))])
                self.assertEqual([n["kind"] for n in ext["nodes"]], ["transmitter"])
        self.assertEqual(pdf_vector._instrument_kind("PUMP"), (None, None))

    def test_circle_with_equipment_word_is_not_instrument(self):
        ext = pdf_run([circle(100, 100, 20), rect(200, 80, 240, 120), line((120, 100), (200, 100))],
                      [word("P-01", 90, 124), word("PUMP", 90, 131)])
        kinds = {n["label_text"]: n["kind"] for n in ext["nodes"]}
        self.assertEqual(kinds["P-01\nPUMP"], "pump")
        self.assertEqual([r["kind"] for r in ext["relations"]], ["physical_connection"])  # 계기 아님 → 측정 아님

    def test_graph_stage_accepts_pdf_extraction(self):
        ext = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160), line((140, 130), (300, 130))])
        self.assertEqual(check_adapter.graph_problems("synthetic", ext), [])


class AlignTest(unittest.TestCase):
    def nodes(self, scale, offset, moved=None):
        out = []
        for i, (x, y) in enumerate([(100, 100), (500, 120), (300, 400), (700, 600), (150, 650)]):
            dx = 40 if moved == i else 0
            out.append(("n%d" % i, "pump", "TAG-%d" % i,
                        ((x + dx) * scale + offset[0], y * scale + offset[1], 40 * scale, 40 * scale)))
        return out

    def test_recovers_transform_and_drops_outlier(self):
        truth = mini(self.nodes(1.0, (0, 0)))
        cand = mini(self.nodes(0.72, (3, -2)), cs=("pdf_page_pt", "pt"))
        al = align.estimate_transform(truth, cand)
        self.assertEqual(al["status"], "ok")
        self.assertAlmostEqual(al["transform"]["scale"][0], 1 / 0.72, places=5)
        self.assertAlmostEqual(al["transform"]["offset"][1], 2 / 0.72, places=4)
        self.assertLess(al["residual_rms"], 1e-6)
        moved = mini(self.nodes(0.72, (3, -2), moved=2), cs=("pdf_page_pt", "pt"))
        al2 = align.estimate_transform(truth, moved)
        self.assertEqual((al2["status"], al2["outliers"], al2["anchors_used"]), ("ok", ["TAG-2"], 4))
        self.assertGreater(al2["residual_rms_all"], 1.0)
        r = ev.evaluate(truth, cand, al["transform"])
        self.assertEqual(r["objects"]["f1"], 1.0)

    def test_blocked_when_anchors_missing(self):
        truth = mini(self.nodes(1.0, (0, 0))[:2])
        al = align.estimate_transform(truth, copy.deepcopy(truth))
        self.assertEqual((al["status"], al["transform"]), ("blocked", None))

    def test_blocked_when_truth_centers_identical(self):
        cand = mini(self.nodes(1.0, (0, 0)), cs=("pdf_page_pt", "pt"))
        truth = mini([(i, k, t, (500, 500, 40, 40)) for i, k, t, _ in self.nodes(1.0, (0, 0))])
        al = align.estimate_transform(truth, cand)
        self.assertEqual((al["status"], al["transform"]), ("blocked", None))
        self.assertIn("scale 0", al["reason"])

    def test_high_leverage_outlier(self):
        pts = [(0, 0), (100, 100), (200, 200), (300, 300), (400, 400)]
        truth = mini([("n%d" % i, "pump", "TAG-%d" % i, (x, y, 40, 40)) for i, (x, y) in enumerate(pts)])
        cand_pts = pts[:-1] + [(10000, 10000)]
        cand = mini([("n%d" % i, "pump", "TAG-%d" % i, (x, y, 40, 40)) for i, (x, y) in enumerate(cand_pts)],
                    cs=("pdf_page_pt", "pt"))
        al = align.estimate_transform(truth, cand)
        self.assertEqual((al["status"], al["outliers"], al["anchors_used"]), ("ok", ["TAG-4"], 4))
        self.assertEqual(al["transform"], {"scale": [1.0, 1.0], "offset": [0.0, 0.0]})
        self.assertEqual(ev.dumps(al), ev.dumps(align.estimate_transform(truth, cand)))  # 결정적

    def test_first_of_many_anchors_is_outlier(self):
        # 기준점 502개(쌍 125,751개 > 상한 500)에서 첫 기준점만 이상치여도 앞쪽 쌍에 치우치지 않아야 한다
        pts = [(i * 2.0, i * 3.0) for i in range(502)]
        truth = mini([("n%03d" % i, "pump", "TAG-%03d" % i, (x, y, 4, 4)) for i, (x, y) in enumerate(pts)])
        cand_pts = [(10000.0, 10000.0)] + pts[1:]
        cand = mini([("n%03d" % i, "pump", "TAG-%03d" % i, (x, y, 4, 4)) for i, (x, y) in enumerate(cand_pts)],
                    cs=("pdf_page_pt", "pt"))
        al = align.estimate_transform(truth, cand)
        self.assertEqual((al["status"], al["outliers"], al["anchors_used"]), ("ok", ["TAG-000"], 501))
        self.assertEqual(al["transform"], {"scale": [1.0, 1.0], "offset": [0.0, 0.0]})
        self.assertEqual(len(align._candidate_pairs(502, 500)), 500)
        self.assertEqual(len(align._candidate_pairs(5, 500)), 10)  # 적으면 전수


class SkipReportTest(unittest.TestCase):
    def test_skipped_w3_is_reported_in_last_line(self):
        real = check_adapter.importlib.util.find_spec

        def no_pdfplumber(name, *args, **kwargs):  # pdfplumber·OpenCV가 없는 환경을 흉내 낸다(W4 래스터도 건너뜀)
            return None if name in ("pdfplumber", "cv2") else real(name, *args, **kwargs)
        buf = io.StringIO()
        with mock.patch.object(check_adapter.importlib.util, "find_spec", no_pdfplumber):
            with contextlib.redirect_stdout(buf):
                rc = check_adapter.run_checks()
        self.assertEqual(rc, 0)
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(lines[-1], "== 결과: 전부 통과 (W3 건너뜀) (W4 건너뜀)")
        self.assertIn("[건너뜀] pdfplumber 없음", buf.getvalue())
        self.assertIn("[건너뜀] OpenCV 또는 rapidocr 없음", buf.getvalue())


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1: PATH python에서 실행)")
class PdfVectorSampleTest(unittest.TestCase):
    def test_samples_contract_alignment_and_evaluation(self):
        samples = check_adapter.pdf_samples()
        self.assertEqual(len(samples), 6)
        for name, drawio_path, pdf_path in samples:
            with self.subTest(name=name):
                errs, row, outputs = check_adapter.evaluate_pdf(name, drawio_path, pdf_path)
                self.assertEqual(errs, [])
                self.assertEqual(row["blockers"], 0)
                self.assertEqual(outputs["evaluation"]["status"], "ok")
                self.assertFalse(os.path.isabs(outputs["extraction"]["source"]["file"]))

    def test_quality_floor_catches_relation_drop(self):
        name, drawio_path, pdf_path = check_adapter.pdf_samples()[0]

        def drop(ext):
            ext["relations"] = ext["relations"][1:]
            return ext
        errs, row, _ = check_adapter.evaluate_pdf(name, drawio_path, pdf_path, mutate=drop)
        self.assertTrue(any("relations_f1" in e for e in errs), errs)
        self.assertLess(row["relations"]["f1"], 1.0)

    def mem_extract(self, content):
        page_count, w, h, words, prims = pdf_vector.load_page(io.BytesIO(make_pdf(content)))
        ext = pdf_vector.build_extraction(pdf_vector.analyze(w, h, words, prims), w, h, page_count, 0,
                                          "memory.pdf", "0" * 64)
        self.assertEqual(ext["validation"]["blockers"], [])
        return prims, ext

    def test_memory_pdf_filled_and_stroked_dashes(self):
        dashes = b"".join(b"%d 219.65 4 0.7 re f\n" % x for x in range(82, 198, 6))
        content = (b"40 200 40 40 re S\n200 200 40 40 re S\n" + dashes +
                   b"40 60 40 40 re S\n200 60 40 40 re S\n[4 2] 0 d 80 80 m 200 80 l S\n[] 0 d\n")
        prims, ext = self.mem_extract(content)
        self.assertEqual([p["dash"] for p in prims if p["dash"]], [[[4.0, 2.0], 0.0]])
        self.assertEqual(len(ext["nodes"]), 4)
        self.assertEqual(sorted(r["kind"] for r in ext["relations"]), ["signal_connection"] * 2)
        self.assertEqual(ext["unresolved_connectors"], [])

    def test_memory_pdf_dash_phase_and_invisible(self):
        # 위상이 0이 아닌 점선: 보이는 조각이 있으므로 신호 관계 1개
        prims, ext = self.mem_extract(b"40 60 40 40 re S\n200 60 40 40 re S\n[4 2] 3 d 80 80 m 200 80 l S\n")
        self.assertEqual([p["dash"] for p in prims if p["dash"]], [[[4.0, 2.0], 3.0]])
        self.assertEqual([r["kind"] for r in ext["relations"]], ["signal_connection"])
        # 길이 120에 [1 200] 20: 위상 때문에 그려지는 구간이 없다 → 선 없음(관계·미해결 모두 0)
        prims, ext = self.mem_extract(b"40 60 40 40 re S\n200 60 40 40 re S\n[1 200] 20 d 80 80 m 200 80 l S\n")
        self.assertEqual((len(ext["nodes"]), ext["relations"], ext["unresolved_connectors"]), (2, [], []))
        self.assertIn("dashed_path_no_visible_piece", [u["check"] for u in ext["validation"]["unknowns"]])

    def ends_of(self, ext):
        label = {n["local_id"]: tuple(n["geometry"].values()) for n in ext["nodes"]}
        return sorted(tuple(sorted(label[e["node_local_id"]] for e in r["endpoints"])) for r in ext["relations"])

    def test_memory_pdf_dashed_through_symbol_is_cut(self):
        # 점선 경로 하나가 A–B–C를 관통: B 안 조각이 빠진 자리에서 끊어 A–B, B–C 두 관계(A–C 아님)
        _, ext = self.mem_extract(b"20 140 20 20 re S\n110 140 20 20 re S\n200 140 20 20 re S\n"
                                  b"[4 2] 0 d 40 150 m 200 150 l S\n")
        boxes = {n["geometry"]["x"]: tuple(n["geometry"].values()) for n in ext["nodes"]}
        a, b, c = boxes[20], boxes[110], boxes[200]
        self.assertEqual(self.ends_of(ext), sorted([tuple(sorted((a, b))), tuple(sorted((b, c)))]))
        self.assertEqual(ext["unresolved_connectors"], [])

    def test_memory_pdf_dashed_paths_joined_only_end_to_end(self):
        # 서로 다른 스트로크 점선 경로 두 개가 끝점끼리 만나는 꺾임 → 한 사슬(A–D 관계 1개)
        _, ext = self.mem_extract(b"20 140 20 20 re S\n110 50 20 20 re S\n"
                                  b"[4 2] 0 d 40 150 m 120 150 l S\n120 150 m 120 70 l S\n")
        self.assertEqual([r["kind"] for r in ext["relations"]], ["signal_connection"])
        self.assertEqual(ext["unresolved_connectors"], [])

    def test_memory_pdf_filled_dashes_crossing(self):
        # 독립된 채운 사각형 점선 두 개가 교차해도 각각 관계 하나
        horiz = b"".join(b"%d 149.65 4 0.7 re f\n" % x for x in range(42, 198, 6))
        vert = b"".join(b"119.65 %d 0.7 4 re f\n" % y for y in range(72, 228, 6))
        _, ext = self.mem_extract(b"20 140 20 20 re S\n200 140 20 20 re S\n110 230 20 20 re S\n110 50 20 20 re S\n"
                                  + horiz + vert)
        self.assertEqual([r["kind"] for r in ext["relations"]], ["signal_connection"] * 2)
        self.assertEqual(ext["unresolved_connectors"], [])
        boxes = {(n["geometry"]["x"], n["geometry"]["y"]): tuple(n["geometry"].values()) for n in ext["nodes"]}
        self.assertEqual(len(boxes), 4)

    def test_memory_pdf_crossing_and_short_dashed(self):
        # 서로 교차하는 독립 점선 두 개는 각각 관계 하나
        _, ext = self.mem_extract(b"20 140 20 20 re S\n200 140 20 20 re S\n110 230 20 20 re S\n110 50 20 20 re S\n"
                                  b"[4 2] 0 d 40 150 m 200 150 l S\n120 230 m 120 70 l S\n")
        self.assertEqual([r["kind"] for r in ext["relations"]], ["signal_connection"] * 2)
        self.assertEqual(ext["unresolved_connectors"], [])
        # 길이 8.5pt·9pt 점선도 양 끝 기호를 잇는다
        _, ext = self.mem_extract(b"20 20 20 20 re S\n48.5 20 20 20 re S\n20 200 20 20 re S\n49 200 20 20 re S\n"
                                  b"[4 2] 0 d 40 30 m 48.5 30 l S\n40 210 m 49 210 l S\n")
        self.assertEqual([r["kind"] for r in ext["relations"]], ["signal_connection"] * 2)
        self.assertEqual(ext["unresolved_connectors"], [])

    def test_extract_pdf_cli_writes_outputs(self):
        import extract_pdf
        sample = [s for s in check_adapter.pdf_samples() if "SNP-M-102" in s[0]][0][2]
        tmp = tempfile.mkdtemp()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = extract_pdf.main([sample, "--out-root", tmp])
            self.assertEqual(rc, 0)
            with open(os.path.join(tmp, "SNP-M-102", "extraction.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["validation"]["blockers"], [])
            self.assertTrue(os.path.isfile(os.path.join(tmp, "SNP-M-102", "validation_report.md")))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
