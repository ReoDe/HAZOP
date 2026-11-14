"""T3 W2 평가 하네스·W3 벡터 PDF 어댑터 테스트. 실행: python -m unittest tests.test_adapter

W3 샘플 시험은 pdfplumber가 있을 때만 돈다(결정 D1). 합성 원시 요소 시험은 pdfplumber 없이 돈다."""

import contextlib
import copy
import io
import glob
import importlib.util
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

import check_adapter  # noqa: E402
from hazop.extract import drawio, runinfo  # noqa: E402
from hazop.extract.adapters import align  # noqa: E402
from hazop.extract.adapters import evaluation as ev  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from hazop.extract.adapters import pdf_vector_grouping  # noqa: E402

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


def prim(pts, closed=False, fill=False, white=False, curved=False, ext=None, width=None):
    return {"fill": fill, "stroke": not fill, "fill_white": fill and white, "stroke_white": False,
            "subpaths": [(list(pts), closed, list(ext or pts), curved)], "width": width}


def rect(x0, y0, x1, y1, **kw):
    return prim([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], closed=True, **kw)


def circle(cx, cy, r):
    pts = [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r), (cx + r, cy)]
    ext = pts + [(cx + r, cy + r), (cx - r, cy + r), (cx - r, cy - r), (cx + r, cy - r)]
    return prim(pts, closed=True, curved=True, ext=ext)


def line(*pts, width=None):
    return prim(pts, width=width)


def word(text, x0, top, size=6.0):
    return {"text": text, "x0": x0, "x1": x0 + 0.6 * size * len(text), "top": top, "bottom": top + size,
            "size": size}


def make_pdf(content, width=400, height=300, resources=b""):
    """내용 스트림 하나짜리 1쪽 PDF 바이트(메모리 시험용, 외부 라이브러리 없음)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R %s>>" % (width, height, resources),
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

    def test_four_way_junction_of_lines_with_different_widths_is_crossing(self):
        # APR1400 072쪽: 가는 방 경계선이 굵은 덕트 위에서 끊겨 네 갈래로 모여도 분기가 아니다. 굵기가 같으면 분기다
        def run(thin):
            ext = pdf_run([rect(100, 200, 120, 220), rect(300, 200, 320, 220), rect(200, 100, 220, 120),
                           rect(200, 300, 220, 320), line((120, 210), (300, 210), width=1.08),
                           line((210, 120), (210, 210), width=thin), line((210, 210), (210, 300), width=thin)])
            ids = {n["local_id"]: n["geometry"]["x"] for n in ext["nodes"] if n["kind"] != "tee"}
            ends = sorted(tuple(sorted(ids.get(e["node_local_id"], -1) for e in r["endpoints"]))
                          for r in ext["relations"])
            return [n["kind"] for n in ext["nodes"]].count("tee"), ends
        self.assertEqual(run(1.08)[0], 1)
        self.assertEqual(run(0.13), (0, [(100, 300), (200, 200)]))

    def test_pocket_hanging_on_pipe_is_one_symbol(self):
        # APR1400 105쪽 드레인 포트: 배관 아래 짧은 세로선 둘과 둥근 바닥. 주머니가 배관 두 가닥과 드레인 선을 잇는
        # 고리가 되지 않고, 배관과 입구 한 곳에서 만나는 기호 하나가 된다
        ext = pdf_run([rect(100, 200, 120, 220), rect(300, 200, 320, 220), rect(200, 300, 220, 320),
                       line((120, 210), (300, 210)), line((208.7, 210.3), (208.7, 214.3)),
                       line((211.3, 210.3), (211.3, 214.3)), line((208.7, 214.3), (210, 215)),
                       line((211.3, 214.3), (210, 215)), line((210, 215), (210, 300))])
        pocket = [n for n in ext["nodes"] if n["kind"] != "tee" and 205 < n["geometry"]["y"] < 215]
        self.assertEqual(len(pocket), 1)
        self.assertIsNone(pocket[0]["kind"])  # 주머니 벽 두 줄을 오리피스 판으로 읽지 않는다
        tees = [n["local_id"] for n in ext["nodes"] if n["kind"] == "tee"]
        self.assertEqual(len(tees), 1)
        by_node = {}
        for r in ext["relations"]:
            ids = [e["node_local_id"] for e in r["endpoints"]]
            for i in ids:
                by_node.setdefault(i, set()).update(x for x in ids if x != i)
        self.assertEqual(by_node[pocket[0]["local_id"]], {tees[0]} | {n["local_id"] for n in ext["nodes"]
                                                                      if n["geometry"]["y"] == 300})

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

    def test_dashed_line_through_valve_axis_is_pipe(self):
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        along = [rect(x, 110.65, x + 4, 111.35, fill=True) for x in range(40, 96, 6)]
        side = [rect(217.65, y, 218.35, y + 4, fill=True) for y in range(44, 96, 6)]
        ext = pdf_run(bowtie(0, 100) + bowtie(100, 100) + along + bowtie(200, 100) + [rect(208, 20, 228, 40)] + side)
        kinds = sorted((r["kind"], r["line_type"]) for r in ext["relations"])
        self.assertEqual(kinds, [("physical_connection", "pdf_dashed"), ("signal_connection", "pdf_dashed")])

    def test_bent_dashed_path_between_valve_axes_is_pipe(self):
        # APR1400 008쪽 POSRV 파일럿 일점쇄선: 한 경로가 꺾여 두 밸브의 흐름 축으로 들어가면 배관이다. 같은 무늬라도
        # 밸브 몸통 옆으로 꺾여 들어가는 선, 닫힌 점선 상자는 배관이 아니다
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        dash_dot = [[10.667, 5.333, 1.333, 5.333], 0.0]
        bent = prim([(36, 111), (70, 111), (70, 211), (100, 211)])
        side = prim([(300, 40), (318, 40), (318, 100)])
        for p in (bent, side):
            p["dash"] = dash_dot
        ext = pdf_run(bowtie(0, 100) + bowtie(100, 200) + bowtie(300, 100) + [rect(290, 20, 300, 60), bent, side])
        kinds = sorted((r["kind"], r["line_type"]) for r in ext["relations"])
        self.assertEqual(kinds, [("physical_connection", "pdf_dashed"), ("signal_connection", "pdf_dashed")])
        box = rect(36, 100, 100, 133)
        box["dash"] = dash_dot
        ext = pdf_run(bowtie(0, 100) + bowtie(100, 100) + [box])
        self.assertNotIn("physical_connection", [r["kind"] for r in ext["relations"]])

    def test_locked_throttled_is_normal_position(self):
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        ext = pdf_run(bowtie(100, 100) + [line((40, 111), (100, 111)), line((136, 111), (200, 111))],
                      [word("LT", 110, 90), word("V1321", 105, 125)])
        valve = [n for n in ext["nodes"] if n["kind"] == "manual_valve"][0]
        self.assertEqual(valve["attributes"].get("normal_position"), "LT")
        self.assertEqual(valve["tag"], "V1321")

    def test_safety_class_diamond_is_not_valve(self):
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        ext = pdf_run(bowtie(100, 100) + [line((118, 100), (118, 122)), line((40, 111), (100, 111)),
                                          line((136, 111), (200, 111))],
                      [word("CI", 103, 107), word("DII", 122, 107)])
        body = [n for n in ext["nodes"] if n["geometry"]["x"] == 100][0]
        self.assertIsNone(body["kind"])
        self.assertEqual(body["evidence"]["classification_basis"], "safety_class_boundary")

    def test_position_label_does_not_push_valve_number_to_class_diamond(self):
        # APR1400 016쪽 V290: 밸브 바로 밑 'LC'가 밸브 라벨을 먼저 차지하면 그 밑 번호는 다음으로 가까운 안전등급 마름모로
        # 갔다. 마름모(몸통 안 글자)는 밸브 번호를 받지 못하므로 번호는 위치 약어만 가진 밸브 몫이다
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        ext = pdf_run(bowtie(100, 100) + [line((40, 111), (100, 111)), line((136, 111), (200, 111))]
                      + bowtie(100, 144) + [line((118, 144), (118, 166))],
                      [word("LC", 112, 123, size=5.0), word("V290", 110, 130, size=5.0),
                       word("CI", 103, 151), word("DII", 122, 151)])
        valve = [n for n in ext["nodes"] if n["kind"] == "manual_valve"][0]
        self.assertEqual((valve["tag"], valve["attributes"].get("normal_position")), ("V290", "LC"))

    def test_safety_class_diamond_does_not_pull_in_number_bubble_and_valve(self):
        # APR1400 105쪽 주증기 안전밸브: 밸브 번호 원의 상자 귀퉁이가 안전등급 마름모 상자에 겹친다. 두 도형은 닿지
        # 않는다. 한 기호로 묶이면 큰 상자 한가운데 놓인 배관 끝(마름모 아래 꼭짓점)이 몸체 깊숙이 든 선으로 읽혀
        # 아래 안전밸브까지 끌려 들어간다
        diamond = [prim([(435.71, 143.41), (443.3, 146.72), (435.71, 150.02), (435.71, 143.41)], closed=True),
                   prim([(428.13, 146.72), (435.71, 150.02), (435.71, 143.41), (428.13, 146.72)], closed=True)]
        valve = prim([(431.26, 163.94), (434.88, 163.94), (434.88, 160.33), (431.26, 163.94)], closed=True)
        prims = diamond + [circle(425.32, 153.99, 4.34), valve, line((435.71, 150.02), (435.71, 161.36)),
                           line((428.38, 157.06), (432.18, 160.86))]
        words = [word("BI", 430.5, 145.1, size=3.0), word("DII", 435.0, 145.1, size=3.0),
                 word("1302", 421.9, 152.4, size=3.0)]
        analysis = pdf_vector.analyze(600.0, 400.0, words, prims)
        bodies = sorted(len(s.bodies) for s in analysis["symbols"])
        self.assertEqual(bodies, [1, 1, 2])  # 원 하나, 밸브 하나, 마름모(삼각형 둘)
        ext = pdf_vector.build_extraction(analysis, 600.0, 400.0, 1, 0, "synthetic.pdf", "0" * 64)
        diamond_node = [n for n in ext["nodes"] if abs(n["geometry"]["x"] - 428.13) < 0.01][0]
        self.assertEqual(diamond_node["evidence"]["classification_basis"], "safety_class_boundary")

    def test_spring_ticks_next_to_number_bubble_corner_stay_on_valve(self):
        # APR1400 008쪽 POSRV 파일럿 안전밸브: 스프링 빗금 끝이 밸브 번호 원의 상자 귀퉁이 옆(2.2pt)에 있지만 원
        # 둘레에서는 3pt 넘게 떨어져 있다. 원에 닿은 연결선으로 보지 않고 밸브에 넣는다
        valve = prim([(464.43, 210.59), (464.43, 207.04), (460.87, 207.04), (464.43, 210.59)], closed=True)
        ticks = [line((461.54, 209.53), (460.16, 208.11)), line((462.1, 209.53), (460.71, 208.11)),
                 line((462.65, 209.53), (461.27, 208.11))]
        prims = [valve, circle(456.25, 201.69, 4.265), line((464.43, 207.04), (462.65, 208.82)),
                 line((460.16, 208.82), (462.65, 208.82)), line((457.14, 203.31), (460.87, 207.04))] + ticks
        analysis = pdf_vector.analyze(600.0, 400.0, [word("303", 453.7, 200.6, size=3.0)], prims)
        sym = [s for s in analysis["symbols"] if any(not b.get("curved") for b in s.bodies)][0]
        self.assertTrue(pdf_vector._has_spring(sym))
        self.assertEqual(len(sym.strokes), 5)
        bubble = [s for s in analysis["symbols"] if any(b.get("curved") for b in s.bodies)][0]
        self.assertEqual((len(bubble.bodies), bubble.strokes), (1, []))

    def test_label_inside_two_symbols_goes_to_smaller(self):
        # 건물 경계처럼 큰 상자 안의 밸브 번호 원: 원 안 글자는 원의 것이다(APR1400 105쪽 '1304')
        frame = prim([(150, 100), (100, 100), (100, 130), (150, 130)])  # 끝이 뜬 선으로만 된 경계(선 기호)
        ext = pdf_run([frame, circle(125, 115, 5), rect(200, 110, 210, 120), line((130, 115), (200, 115))],
                      [word("1304", 121.4, 113.5, size=3.0)])
        self.assertEqual(len(ext["nodes"]), 3)
        bubble = [n for n in ext["nodes"] if n["geometry"]["width"] < 20][0]
        self.assertEqual(bubble["label_text"], "1304")

    def test_dashed_pipes_leaving_one_symbol_are_not_joined(self):
        # 밸브 한 변에서 따로 나가는 두 점선 배관: 시작점이 1.2pt로 붙어 있어도 꺾임으로 잇지 않는다. 밸브 상자 안의
        # 끝 조각도 밸브에 넣지 않는다(APR1400 008쪽 POSRV 파일럿 안전밸브와 MOV)
        prims = [rect(100, 100, 110, 110), rect(160, 94, 180, 114), rect(120, 200, 140, 220),
                 prim([(110, 104), (160, 104)]), prim([(110, 105.2), (130, 105.2), (130, 200)])]
        for p in prims[3:]:
            p["dash"] = [[2.0, 1.0], 0.0]
        analysis = pdf_vector.analyze(600.0, 400.0, [], prims)
        valve = [s for s in analysis["symbols"] if s.bbox[0] == 100][0]
        self.assertEqual(valve.dashes, [])
        ext = pdf_vector.build_extraction(analysis, 600.0, 400.0, 1, 0, "synthetic.pdf", "0" * 64)
        ends = sorted(tuple(sorted(n["geometry"]["x"] for n in ext["nodes"] if n["local_id"] in
                                   {e["node_local_id"] for e in r["endpoints"]})) for r in ext["relations"])
        self.assertEqual(ends, [(100, 120), (100, 160)])

    def test_continuation_arrow_sets_flow(self):
        def flag(x, y, right):  # 오각 깃발 40×12: right면 뾰족한 쪽이 오른쪽
            pts = ([(x, y), (x + 30, y), (x + 40, y + 6), (x + 30, y + 12), (x, y + 12), (x, y)] if right else
                   [(x + 10, y), (x + 40, y), (x + 40, y + 12), (x + 10, y + 12), (x, y + 6), (x + 10, y)])
            return prim(pts, closed=True)
        ext = pdf_run([rect(100, 100, 140, 160), flag(300, 124, True), line((140, 130), (300, 130)),
                       rect(100, 250, 140, 310), flag(300, 274, False), line((140, 280), (300, 280))],
                      [word("TO", 302, 116), word("CV:RDT", 312, 116), word("FROM", 302, 266), word("CV:VCT", 322, 266)])
        node = {n["local_id"]: n for n in ext["nodes"]}
        flows = sorted((node[r["flow_direction"]["from"]]["kind"] or "-", node[r["flow_direction"]["to"]]["kind"] or "-")
                       for r in ext["relations"] if r.get("flow_direction"))
        self.assertEqual(flows, [("-", "continuation"), ("continuation", "-")])

    def test_orifice_box_between_pipes(self):
        # 범례 1.7-1 1/4 RESTRICTION ORIFICE '|ı|'(16쪽 OR01B와 같은 치수): 판 2.9pt 둘 사이 가운데에 짧은 선. 판이 짧아
        # 선 기호 최소 크기(4pt)에 못 미쳐 예전에는 배관 조각으로 남았다. 가운데 선이 없으면 플랜지라 기호가 아니다
        def body(x):
            return [line((x, 108.15), (x, 111.05)), line((x + 2.9, 108.15), (x + 2.9, 111.05))]
        ext = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), line((140, 109.6), (220, 109.6)),
                       *body(220), line((221.45, 108.875), (221.45, 110.325)), line((222.9, 109.6), (300, 109.6))])
        box = [n for n in ext["nodes"] if 215 < n["geometry"]["x"] < 225]
        self.assertEqual([n["kind"] for n in box], ["orifice"])
        self.assertEqual(len(ext["relations"]), 2)
        flange = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), line((140, 109.6), (220, 109.6)),
                          *body(220), line((222.9, 109.6), (300, 109.6))])
        self.assertNotIn("orifice", [n["kind"] for n in flange["nodes"]])
        # 판 가운데(배관 끝 자리)에서 갈라지는 선은 배관 분기라 상자를 그대로 본다(8쪽 OR 아래 AI|BI 지시선)
        branch = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), rect(212, 150, 232, 170),
                          line((140, 109.6), (220, 109.6)), *body(220), line((221.45, 108.875), (221.45, 110.325)),
                          line((222.9, 109.6), (300, 109.6)), line((222.9, 109.6), (222.9, 150))])
        self.assertIn("orifice", [n["kind"] for n in branch["nodes"]])
        # 판 끝(상자 귀퉁이)에 차압 탭선이 닿으면 FE 원과 묶이는 유량 요소라 오리피스 상자로 보지 않는다(63쪽 FE 202)
        tapped = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), rect(200, 40, 216, 56),
                          line((140, 109.6), (220, 109.6)), *body(220), line((221.45, 108.875), (221.45, 110.325)),
                          line((222.9, 109.6), (300, 109.6)), line((220, 108.15), (208, 56)), line((222.9, 108.15), (212, 56))])
        self.assertNotIn("orifice", [n["kind"] for n in tapped["nodes"]])

    def test_alarm_box_words_are_not_equipment(self):
        ext = pdf_run([rect(100, 100, 180, 120), rect(300, 100, 380, 120)],
                      [word("PUMP", 105, 104), word("START/STOP", 120.5, 104), word("PUMP", 305, 104), word("P-01", 320.5, 104)])
        self.assertEqual(sorted(n["kind"] or "-" for n in ext["nodes"]), ["-", "pump"])

    def test_valve_number_and_position_stacked_are_tag_and_attribute(self):
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        ext = pdf_run(bowtie(100, 100) + [line((40, 111), (100, 111)), line((136, 111), (200, 111))],
                      [word("V310", 140, 92), word("LO", 140, 99)])
        valve = [n for n in ext["nodes"] if n["kind"] == "manual_valve"][0]
        self.assertEqual((valve["tag"], valve["attributes"].get("normal_position")), ("V310", "LO"))

    def test_number_circle_touching_valve_body_is_valve_tag(self):
        # APR1400 008쪽 방출 밸브 200(좌표 그대로): 번호 원이 지시선으로 몸통에 닿아 밸브와 한 기호로 묶이고, 원 안
        # 숫자가 밸브 라벨이 된다. 원 안 숫자는 밸브 번호다. 원이 없으면 같은 자리의 맨 숫자라도 태그로 쓰지 않는다
        valve = [prim([(351.12, 180.39), (354.67, 180.39), (354.67, 176.84), (351.12, 180.39)], closed=True),
                 rect(350.23, 161.56, 355.56, 166.89), line((352.89, 176.13), (352.89, 166.89)),
                 line((352.89, 176.12), (352.89, 178.61)), line((354.67, 180.39), (352.89, 178.61)),
                 line((345.96, 174.52), (349.69, 178.26))]
        valve += [line((352.18, y), (353.6, y - 1.38)) for y in (177.51, 178.06, 178.61)]
        words = [word("P", 351.88, 163.11, size=3.0), word("200", 342.2, 172.23, size=3.0)]
        circled = pdf_run(valve + [circle(344.72, 173.28, 4.27)], words)
        self.assertEqual([(n["kind"], n["tag"]) for n in circled["nodes"] if n["label_text"] == "200"], [("psv", "200")])
        bare = pdf_run(valve, words)
        self.assertEqual([n["tag"] for n in bare["nodes"] if n["category"] == "valve"], [None])

    def test_size_text_beside_valve_goes_to_pipe(self):
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        ext = pdf_run(bowtie(100, 100) + [rect(300, 90, 340, 132), line((136, 111), (300, 111))],
                      [word("¾\"", 140, 104)])
        self.assertEqual([(r["attributes"] or {}).get("size") for r in ext["relations"]], ['3/4"'])
        self.assertEqual([n["label_text"] for n in ext["nodes"]], ["", ""])

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

    @staticmethod
    def letter_box_valve(letter, stem_end_x=145):
        """나비 밸브 몸통 위 5.8pt 글자 상자와 (145, 100)에서 내려오는 축(012쪽 S 상자 치수) → (추출 결과, 밸브 노드)."""
        ext = pdf_run([rect(80, 100, 100, 120), rect(200, 100, 220, 120),
                       prim([(140, 107), (145, 110), (140, 113), (140, 107)], closed=True),
                       prim([(150, 107), (145, 110), (150, 113), (150, 107)], closed=True),
                       line((100, 110), (140, 110)), line((150, 110), (200, 110)),
                       rect(142.1, 94.2, 147.9, 100), line((145, 100), (stem_end_x, 107.5))],
                      [word(letter, 143.5, 95.5, size=4.0), word("V-1", 141, 116)])
        return ext, [n for n in ext["nodes"] if n["label_text"] == "V-1"][0]

    def test_letter_box_on_valve_stem_merges_into_valve(self):
        # 범례 1.7-1 1/4 L1-078·솔레노이드 구동부: 밸브 위 짧은 세로 축 끝 글자 상자는 밸브의 한 부분이다(008쪽 P, 012쪽 S).
        # 사선 지시선에 매달린 상자(062쪽 G)는 합치지 않는다
        ext, valve = self.letter_box_valve("G")
        self.assertEqual(valve["evidence"]["actuator_marks"], ["G"])
        self.assertNotIn("G", [n["label_text"] for n in ext["nodes"]])
        self.assertEqual(len(ext["relations"]), 2)  # 축은 밸브 안의 선이다
        self.assertIn("actuator_merged", [o.get("reason") for o in ext["drawing"]["ignored_objects"]])
        ext, valve = self.letter_box_valve("G", stem_end_x=141.5)
        self.assertNotIn("actuator_marks", valve["evidence"])
        self.assertIn("G", [n["label_text"] for n in ext["nodes"]])

    def test_letter_box_kind_only_where_legend_defines_letter(self):
        # 범례 1.7-1 1/4 SOLENOID OPERATORS: S 상자를 단 밸브는 전자 밸브다. 범례에 없는 글자(G)는 몸통 kind를 그대로 둔다
        _, plain = self.letter_box_valve("G")
        _, valve = self.letter_box_valve("S")
        self.assertEqual(valve["kind"], "solenoid_valve")
        self.assertEqual(valve["attributes"], dict(plain["attributes"], actuator_type="solenoid", motive_power="electric"))
        self.assertNotEqual(plain["kind"], "solenoid_valve")
        self.assertEqual(valve["evidence"]["classification_basis"], plain["evidence"]["classification_basis"]
                         + "+actuator_mark:S")

    def test_box_check_valve_between_pipes(self):
        # APR1400 상자형 체크밸브 '|\|'(16쪽 V405와 같은 치수): 세로 막대 2.9pt 가운데에 배관 끝이 닿아 막대 끝과 배관 끝이
        # 1.45pt로 end_tol 안이다. 예전에는 배관 조각으로 이어져 노드가 없었다
        def dot(cx, cy, r=0.36):
            pts = [(cx + r, cy), (cx, cy - r), (cx - r, cy), (cx, cy + r), (cx + r, cy)]
            return prim(pts, fill=True, curved=True)
        n_shape = line((223.88, 113.05), (223.88, 110.15), (229.68, 113.05), (229.68, 110.15))
        ext = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), line((140, 111.6), (223.88, 111.6)),
                       n_shape, dot(223.88, 110.15), line((229.68, 111.6), (300, 111.6))])
        cv = [n for n in ext["nodes"] if n["geometry"]["x"] > 200 and n["geometry"]["x"] < 230]
        self.assertEqual([n["kind"] for n in cv], ["check_valve"])
        self.assertEqual(len(ext["relations"]), 2)  # 탱크—체크밸브—탱크(밸브를 건너뛰는 한 줄이 아니다)
        # 한쪽 막대에만 배관이 닿거나, 배관이 막대와 같은 줄로 겹치면 이 규칙으로 세우지 않는다
        def polys(*shapes):
            return [{"id": "p%d" % i, "pts": s["subpaths"][0][0], "bbox": pdf_vector._bbox_pts(s["subpaths"][0][0])}
                    for i, s in enumerate(shapes)]
        prm = dict(pdf_vector.PARAMS)
        both = polys(line((140, 111.6), (223.88, 111.6)), n_shape, line((229.68, 111.6), (300, 111.6)))
        self.assertEqual(len(pdf_vector_grouping._bar_fed_strokes(both, prm)[0]), 1)
        one = polys(line((140, 111.6), (223.88, 111.6)), n_shape)
        self.assertEqual(pdf_vector_grouping._bar_fed_strokes(one, prm)[0], [])
        along = polys(line((223.88, 111.6), (223.88, 140)), n_shape, line((229.68, 111.6), (300, 111.6)))
        self.assertEqual(pdf_vector_grouping._bar_fed_strokes(along, prm)[0], [])

    def test_scanned_check_valve_with_rounded_arrowhead(self):
        # 스캔 SNP-M-301 체크밸브(300dpi를 벡터로 바꾼 좌표, pt): 화살촉이 꼭짓점 다섯 개 볼록 다각형이 되고, 사선은 화살촉 앞에서
        # 끊기며 화살촉과 오른쪽 판 사이에 짧은 토막이 남는다. 예전에는 화살촉을 꺾인 점선 모서리로 읽어 'orifice'가 됐다
        def at(*pts):
            return [(x - 400, y) for x, y in pts]
        head = at((606.0, 295.44), (606.0, 297.36), (608.88, 297.6), (609.12, 296.4), (607.68, 294.72), (606.0, 295.44))
        ext = pdf_run([rect(60, 270, 100, 305), rect(300, 270, 340, 305),
                       line(*at((500, 287.4), (575.28, 287.4))), line(*at((611.28, 287.4), (700, 287.4))),
                       line(*at((575.28, 276.96), (575.28, 298.32))), line(*at((611.28, 276.96), (611.28, 298.32))),
                       line(*at((577.1, 278.08), (605.66, 295.21))), line(*at((611.28, 296.16), (609.12, 296.16))),
                       prim(head, closed=True, fill=True)])
        cv = [n for n in ext["nodes"] if 170 < n["geometry"]["x"] < 215]
        self.assertEqual([n["kind"] for n in cv], ["check_valve"])
        self.assertEqual(len([r for r in ext["relations"] if r["kind"] == "physical_connection"]), 2)
        # 오목한 L자 조각(꺾인 점선 모서리)은 그대로 점선 조각이다
        corner = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4), (0, 0)]
        cls = pdf_vector._classify_primitives(600, 400, [prim(corner, closed=True, fill=True),
                                                         prim(head, closed=True, fill=True)], dict(pdf_vector.PARAMS))
        self.assertEqual(([d["id"] for d in cls["dashes"]], [m["id"] for m in cls["markers"]]),
                         (["pdf-path-0000"], ["pdf-path-0001"]))

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

    def test_legend_instrument_codes(self):
        cases = {"ZL\n202C": "pilot_light", "ZL": "pilot_light", "PDAH\n031": "alarm", "PAL": "alarm",
                 "AX\n134": "sample_probe", "FG": "sight_glass", "LE\n058": "level_element", "LL": None, "ZAC": "controller"}
        for text, kind in cases.items():
            with self.subTest(text=text):
                ext = pdf_run([circle(100, 100, 14)], [word(t, 95, 92 + 7 * i) for i, t in enumerate(text.split("\n"))])
                self.assertEqual([n["kind"] for n in ext["nodes"]], [kind])

    def test_lone_triangle_at_line_end_is_not_a_pipe_cap(self):
        cap = pdf_run([line((100, 100), (200, 100)), rect(200, 97, 204, 103)])
        nozzle = pdf_run([line((100, 100), (200, 100)), prim([(200, 97), (200, 103), (204, 100), (200, 97)], closed=True)])
        self.assertEqual([n["kind"] for n in cap["nodes"]], ["pipe_cap"])
        self.assertEqual([n["kind"] for n in nozzle["nodes"]], [None])

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


class PdfTagTest(unittest.TestCase):
    """PDF 기호 노드의 tag: 글자 맨 앞 태그, ISA 계기 글자 + 같은 쪽 최다 접두([추론]), 중복·동률이면 비움."""

    def tags(self, labels):
        prims, words = [], []
        for i, (shape, lines) in enumerate(labels):
            x = 60 + 90 * i
            prims.append(circle(x + 10, 110, 10) if shape == "circle" else rect(x, 100, x + 20, 120))
            for k, text in enumerate(lines):  # 기호 안에 줄마다 한 단어
                words.append(word(text, x + 3, 104 + 6.5 * k))
        ext = pdf_run(prims, words)
        nodes = sorted(ext["nodes"], key=lambda n: n["geometry"]["x"])
        unknown = {(u["check"], u["source_object_id"]): u["reason"] for u in ext["validation"]["unknowns"]}
        return nodes, unknown

    def test_leading_tag_and_inferred_instrument_prefix(self):
        nodes, unknown = self.tags([("rect", ["RC-V111"]), ("rect", ["RC-PP01"]), ("rect", ["CV-V201"]),
                                    ("circle", ["PT", "110"]), ("rect", ["FILTER"])])
        self.assertEqual([n["tag"] for n in nodes], ["RC-V111", "RC-PP01", "CV-V201", "RC-PT110", None])
        self.assertEqual(nodes[0]["evidence"]["tag_basis"], "label_tag_token")
        self.assertIn("[추론]", nodes[3]["evidence"]["tag_basis"])
        self.assertEqual([k for k in unknown if k[0] == "missing_tag"], [("missing_tag", nodes[4]["source_object_id"])])

    def test_equipment_number_line_matching_kind_is_tag(self):
        # 범례 기기 번호 'TK 02 A': 종류 글자가 기호 종류와 맞을 때만 태그다. 탱크 글자 옆 'PP01A'는 탱크 태그가 아니다
        nodes, unknown = self.tags([("rect", ["TANK", "TK02A"]), ("rect", ["TANK", "PP01A"])])
        self.assertEqual([n["kind"] for n in nodes], ["tank", "tank"])
        self.assertEqual([n["tag"] for n in nodes], ["TK02A", None])
        self.assertEqual(nodes[0]["evidence"]["tag_basis"], "equipment_number")
        self.assertIn(("missing_tag", nodes[1]["source_object_id"]), unknown)

    def test_bubble_letters_and_number_in_two_paragraphs_join(self):
        # 072쪽 표시 상자: 칸막이 선 위 'PDAH', 아래 '031'. 줄 간격(3.5pt)이 문단 간격 상한(0.5 × 6pt)보다 넓어 문단이 갈린다
        ext = pdf_run([circle(110, 110, 10)], [word("PDAH", 103, 104), word("031", 105, 113.5)])
        bubble = ext["nodes"][0]
        self.assertEqual((bubble["label_text"], bubble["tag"]), ("PDAH\n031", "PDAH-031"))
        self.assertEqual(ext["texts"], [])

    def test_duplicate_and_tied_prefix_leave_tag_empty(self):
        nodes, unknown = self.tags([("rect", ["RC-V111"]), ("rect", ["RC-V111"]), ("rect", ["CV-V201"]),
                                    ("circle", ["PT", "110"])])
        self.assertEqual([n["tag"] for n in nodes], [None, None, "CV-V201", "RC-PT110"])  # 중복 태그도 접두 집계에는 든다
        self.assertIn(("duplicate_tag", nodes[0]["source_object_id"]), unknown)
        self.assertNotIn(("missing_tag", nodes[0]["source_object_id"]), unknown)
        nodes, unknown = self.tags([("rect", ["RC-V111"]), ("rect", ["CV-V201"]), ("circle", ["PT", "110"])])
        self.assertIsNone(nodes[2]["tag"])
        self.assertIn("접두", unknown[("missing_tag", nodes[2]["source_object_id"])])


def merged_pdf(out, sources, blank=True):
    """샘플 PDF 여러 개를 쪽으로 이어 붙이고(blank면 빈 쪽 하나 더) out에 저장한다(pypdfium2)."""
    import pypdfium2 as pdfium
    doc, srcs = pdfium.PdfDocument.new(), [pdfium.PdfDocument(p) for p in sources]
    try:
        for s in srcs:
            doc.import_pages(s)
        if blank:
            doc.new_page(*doc[0].get_size())
        doc.save(out)
    finally:
        doc.close()
        for s in srcs:
            s.close()
    return out


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음: 시험용 venv(~/.hazop/venv-py312)로 실행할 것. PATH의 python은 LibreOffice 것")
class PdfViewerPathTest(unittest.TestCase):
    """② 뷰어용 배경 SVG의 data-cell-id, 정렬 측정, 분석 결과 재사용, 여러 쪽 추출."""

    def setUp(self):
        self.pdf = [s for s in check_adapter.pdf_samples() if "SNP-M-102" in s[0]][0][2]

    def test_svg_marks_keep_drawing_and_cover_every_object(self):
        from hazop.extract.adapters import pdf_svg
        ex = pdf_vector.extract(self.pdf)
        svg = pdf_svg.render_page_svg(self.pdf, 0, ex)
        conns = ex["relations"] + ex["unresolved_connectors"]
        self.assertTrue(conns and all(len(r["evidence"]["pdf_path"]) >= 2 for r in conns))
        for r in conns:
            self.assertIn('<g data-cell-id="%s"><path d="M' % r["source_object_id"], svg)
        for n in ex["nodes"]:
            self.assertIn('data-cell-id="%s"' % n["source_object_id"], svg)
        # 그림 자체는 표식 없는 SVG와 같다(속성만 붙고, 표식 묶음은 도면 뒤에 덧붙음)
        body = re.sub(r' data-cell-id="[^"]+"', "", re.sub(r'\n<g data-cell-id="[^"]+">.*?</g>', "", svg))
        self.assertEqual(body, pdf_svg.render_page_svg(self.pdf, 0))

    def test_alignment_measures_symbol_boxes(self):
        from hazop.extract.adapters import pdf_svg
        ex = pdf_vector.extract(self.pdf)
        svg = pdf_svg.render_page_svg(self.pdf, 0, ex)
        al = pdf_svg.measure_alignment(svg, ex)
        symbols = [n for n in ex["nodes"] if n["evidence"]["pdf_objects"]]
        self.assertEqual((al["status"], al["compared_cells"], al["consistent_cells"]),
                         ("verified", len(symbols), len(symbols)))
        self.assertLessEqual(al["max_residual"], al["tolerance"])
        self.assertIn("독립 정답", al["note"])
        moved = copy.deepcopy(ex)
        target = next(n for n in moved["nodes"] if n["evidence"]["pdf_objects"])
        target["geometry"]["x"] += 2
        bad = pdf_svg.measure_alignment(svg, moved)
        self.assertEqual(bad["status"], "failed")
        self.assertEqual([c["cell"] for c in bad["inconsistent_offsets"]], [target["source_object_id"]])

    def test_preview_registration_and_extraction_analyze_once(self):
        from hazop.register import fileinfo
        with open(self.pdf, "rb") as fh:
            data = fh.read()
        pdf_vector._cache.clear()
        with mock.patch.object(pdf_vector, "load_page", wraps=pdf_vector.load_page) as load:
            info = fileinfo.inspect(self.pdf, data)
            first, again = pdf_vector.extract(self.pdf), pdf_vector.extract(self.pdf)
        self.assertEqual(info["blockers"], [])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(ev.dumps(first), ev.dumps(again))  # 함께 쓰는 분석 결과를 바꾸지 않는다

    def test_cli_extracts_every_page_and_records_blank_page(self):
        import extract_pdf
        samples = check_adapter.pdf_samples()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        src = merged_pdf(os.path.join(tmp, "merged.pdf"), [samples[0][2], samples[1][2]])
        out = os.path.join(tmp, "out")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = extract_pdf.main([src, "--pages", "all", "--out-root", out])
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertEqual(sorted(os.listdir(out)), ["SNP-M-101", "SNP-M-102-p1", "merged-p2"])
        with open(os.path.join(out, "SNP-M-102-p1", "extraction.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["source_context"]["page_id"], "page-2")
        self.assertEqual(sorted(os.listdir(os.path.join(out, "merged-p2"))), [runinfo.FILE_NAME, extract_pdf.NOT_EXTRACTED])
        self.assertIn("p2: 미추출", buf.getvalue())

    def test_reextract_switches_page_state_without_leftovers(self):
        import extract_pdf
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        name = lambda _p: "page"  # noqa: E731
        done, _ = extract_pdf.run_pages(self.pdf, tmp, [0], out_name=name)
        self.assertEqual(len(done), 1)
        with mock.patch.object(extract_pdf.pdf_vector, "extract", side_effect=ValueError("읽기 실패")):
            done, skipped = extract_pdf.run_pages(self.pdf, tmp, [0], out_name=name)
        self.assertEqual((done, len(skipped)), ([], 1))
        self.assertEqual(sorted(os.listdir(os.path.join(tmp, "page"))), [runinfo.FILE_NAME, extract_pdf.NOT_EXTRACTED])
        done, _ = extract_pdf.run_pages(self.pdf, tmp, [0], out_name=name)
        self.assertEqual(len(done), 1)
        self.assertNotIn(extract_pdf.NOT_EXTRACTED, os.listdir(os.path.join(tmp, "page")))


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


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음: 시험용 venv(~/.hazop/venv-py312)로 실행할 것. PATH의 python은 LibreOffice 것")
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

    def test_tight_two_line_text_stays_two_lines(self):
        # 3pt 글자 두 줄, 줄 간격 2.85pt(APR1400 계기 비석 'FT' 위 '1011X')
        content = b"BT /F1 3.06 Tf 102 152.85 Td (FT) Tj ET BT /F1 3.06 Tf 100 150 Td (1011X) Tj ET"
        font = b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> "
        words = pdf_vector.load_page(io.BytesIO(make_pdf(content, resources=font)))[3]
        self.assertEqual(sorted(w["text"] for w in words), ["1011X", "FT"])
        glued = b"BT /F1 3.27 Tf 100 150 Td (PDIS\\(3053\\)) Tj ET"
        words = pdf_vector.load_page(io.BytesIO(make_pdf(glued, resources=font)))[3]
        self.assertEqual([w["text"] for w in words], ["PDIS", "(3053)"])
        self.assertLessEqual(words[0]["x1"], words[1]["x0"])

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
