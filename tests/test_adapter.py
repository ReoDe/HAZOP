"""T3 W2 평가 하네스·W3 벡터 PDF 어댑터 테스트. 실행: python -m unittest tests.test_adapter

W3 샘플 시험은 pdfplumber가 있을 때만 돈다(결정 D1). 합성 원시 요소 시험은 pdfplumber 없이 돈다."""

import contextlib
import copy
import io
import glob
import importlib.util
import json
import math
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

    def test_stacked_arrowheads_are_not_a_valve_body(self):
        # APR1400 056쪽 신호 상자 'A▶ / B▶': 같은 쪽을 가리키는 화살촉 둘을 위아래로 쌓았다. 꼭짓점을 맞댄 나비가 아니다
        stacked = [prim([(100, 100), (100, 106), (105, 103), (100, 100)], closed=True),
                   prim([(100, 106), (100, 112), (105, 109), (100, 106)], closed=True)]
        bowtie = [prim([(200, 100), (200, 106), (203, 103), (200, 100)], closed=True),
                  prim([(206, 100), (206, 106), (203, 103), (206, 100)], closed=True)]
        kinds = {n["geometry"]["x"]: n["kind"] for n in pdf_run(stacked + bowtie)["nodes"]}
        self.assertEqual((kinds.get(100), kinds.get(200)), (None, "manual_valve"))

    def test_equipment_name_word_needs_a_body_of_equipment_size(self):
        # 이름 글자 옆 몇 pt짜리 조각(APR1400 121·122쪽 'CONDENSER A' 옆 배관 끝 막대)은 이름 낱말로 설비가 되지 않는다.
        # 같은 글자를 단 설비 크기 상자는 응축기다
        ext = pdf_run([rect(100, 100, 103, 101), rect(300, 100, 340, 140)],
                      words=[word("CONDENSER", 90, 103, size=3), word("CONDENSER", 305, 117, size=3)])
        kinds = {n["geometry"]["x"]: n["kind"] for n in ext["nodes"]}
        self.assertEqual((kinds[100], kinds[300]), (None, "condenser"))

    def test_pipe_between_two_bodies(self):
        ext = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160), line((140, 130), (300, 130))])
        self.assertEqual(ext["validation"]["blockers"], [])
        self.assertEqual(len(ext["nodes"]), 2)
        self.assertEqual([r["kind"] for r in ext["relations"]], ["physical_connection"])
        self.assertEqual(ext["source"]["format"], "pdf_vector")
        self.assertEqual(ext["coordinate_system"]["coordinate_space"], "pdf_page_pt")
        self.assertEqual(ext["nodes"][0]["source_object_id"], "pdf-p0-sym-0001")
        self.assertEqual(ext["nodes"][0]["geometry"], {"x": 100, "y": 100, "width": 40, "height": 60})

    def test_wave_drawn_in_pipe_path_is_flexible_hose_node(self):
        # APR1400 097쪽: 유연 호스(범례 1.7-1 1/4 FLEXIBLE HOSE)를 배관과 한 경로로 긋는다(곧은 선 → 반원 셋 → 곧은 선).
        # 물결이 호스 노드가 되고 양쪽 배관이 호스에 붙는다. 상자 안에 통째로 든 물결은 그 상자 기호의 무늬다
        def hose(x0, y, r=3.0, lead=8.0):
            pts, fine, x = [(x0, y), (x0 + lead, y)], [(x0, y), (x0 + lead, y)], x0 + lead
            for k in range(3):
                side = -1 if k % 2 == 0 else 1
                pts += [(x + r, y + side * r), (x + 2 * r, y)]
                fine += [(x + r - r * math.cos(math.pi * t / 12), y + side * r * math.sin(math.pi * t / 12))
                         for t in range(1, 13)]
                x += 2 * r
            pts.append((x + lead, y))
            fine.append((x + lead, y))
            return dict(prim(pts, curved=True), fine=[fine])
        ext = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160), line((140, 130), (200, 130)),
                       hose(200, 130), line((234, 130), (300, 130))])
        kinds = {n["local_id"]: n["kind"] for n in ext["nodes"]}
        self.assertEqual(sorted(k or "-" for k in kinds.values()), ["-", "-", "flexible_hose"])
        hose_id = next(i for i, k in kinds.items() if k == "flexible_hose")
        ends = [{e["node_local_id"] for e in r["endpoints"]} for r in ext["relations"]]
        self.assertEqual(len(ends), 2)
        self.assertTrue(all(hose_id in e for e in ends))
        boxed = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160), line((140, 130), (196, 130)),
                         rect(196, 120, 238, 140), hose(200, 130, lead=2.0), line((238, 130), (300, 130))])
        self.assertNotIn("flexible_hose", [n["kind"] for n in boxed["nodes"]])

    def test_pipe_ending_at_arrowhead_inside_equipment_is_connection_not_stem(self):
        # APR1400 033쪽 펌프 PP01A: 밸브에서 온 배관이 펌프 원 안 화살촉까지 그어진다. 끝이 몸체 깊숙이 들어갔어도 화살촉에서
        # 끝나는 선은 구동부 축이 아니라 장비로 들어가는 배관이다. 밸브·배관·펌프가 한 기호로 묶이지 않는다
        head = prim([(196, 127), (203, 130), (196, 133), (196, 127)], closed=True, fill=True)
        ext = pdf_run([rect(80, 120, 100, 140), circle(200, 130, 12), head, line((100, 130), (197, 130))])
        nodes = [n for n in ext["nodes"] if n["kind"] != "tee"]
        self.assertEqual(len(nodes), 2)
        self.assertEqual([{e["node_local_id"] for e in r["endpoints"]} for r in ext["relations"]],
                         [{n["local_id"] for n in nodes}])

    def test_big_outline_holds_drawn_contents_apart(self):
        # APR1400 072쪽 HVAC CHASE·공조기 구간, 012쪽 IRWST: 큰 닫힌 외곽 안에 그린 몸체·선은 외곽에 담긴 것이다. 안의 몸체는
        # 제 노드가 되고, 외곽 안에서 끝나는 배관은 구동부 축이 아니어서 반대 끝 밸브를 외곽에 합치지 않는다
        room, inner, valve = rect(100, 100, 160, 180), rect(140, 150, 150, 160), rect(200, 120, 210, 130)
        ext = pdf_run([room, inner, valve, line((200, 125), (120, 125))])
        boxes = sorted((n["geometry"]["x"], n["geometry"]["width"]) for n in ext["nodes"] if n["kind"] != "tee")
        self.assertEqual(boxes, [(100, 60), (140, 10), (200, 10)])
        small = pdf_run([rect(100, 100, 115, 140), rect(105, 110, 110, 115)])  # 짧은 변 15pt 상자는 담는 외곽이 아니다
        self.assertEqual(len([n for n in small["nodes"] if n["kind"] != "tee"]), 1)
        # SNP-M-301 스캔: 위가 트인 빗금 탱크는 벽 칸 여럿이고 그 한 칸이 담는 외곽 크기다. 칸이 기호의 절반도 안 되면 그 기호는
        # 담는 외곽이 아니어서, 트인 위쪽으로 들어오는 배관이 벽 칸에서 멀어도 탱크에 닿는다
        def poly(*pts):  # 표 칸으로 읽히지 않게 사다리꼴로 그린다
            return prim(list(pts) + [pts[0]], closed=True)
        wall = pdf_run([rect(100, 100, 125, 160), rect(110, 110, 115, 115),
                        poly((275, 100), (300, 100), (300, 160), (280, 160)),
                        poly((125, 140), (280, 140), (280, 160), (130, 160)),
                        rect(195, 30, 205, 40), line((200, 40), (200, 99))])
        x = {n["local_id"]: n["geometry"]["x"] for n in wall["nodes"]}
        self.assertEqual([sorted(x[e["node_local_id"]] for e in r["endpoints"]) for r in wall["relations"]], [[100, 195]])

    def test_pipe_at_outline_wall_goes_to_drawn_content(self):
        # 072쪽 공조기 팬 출구: 팬이 구간 상자 오른쪽 변에 겹쳐 그려져, 덕트 끝이 상자 변에 0.01pt 더 가깝다. 덕트는 팬에 닿는다.
        # 012쪽 IRWST: 살포기로 가는 배관이 탱크 윗변에서 두 경로로 나뉘어 그려진다. 배관은 벽을 지나 살포기에 닿는다
        def pairs(ext):
            x = {n["local_id"]: n["geometry"]["x"] for n in ext["nodes"]}
            return sorted(sorted(x[e["node_local_id"]] for e in r["endpoints"]) for r in ext["relations"])
        fan = pdf_run([rect(100, 100, 160, 140), rect(140, 110, 159.99, 130), rect(250, 115, 260, 125),
                       line((160, 120), (250, 120))])
        self.assertEqual(pairs(fan), [[140, 250]])
        tank = pdf_run([rect(100, 100, 200, 200), rect(140, 170, 160, 180), rect(145, 30, 155, 40),
                        line((150, 40), (150, 100)), line((150, 100), (150, 170))])
        self.assertEqual(pairs(tank), [[140, 145]])

    def test_small_box_set_on_outline_wall_is_own_node_touching_it(self):
        # 046쪽 압축기 위 필터 F: 압축기 상자 윗변 바깥에 작은 상자를 붙여 그린다. 필터는 제 노드가 되고 압축기와 맞닿아 이어진다
        # 압축기 상자는 안에 칸막이 상자를 담고 있어 담는 외곽이다
        ext = pdf_run([rect(100, 100, 160, 150), rect(130, 120, 150, 140), rect(110, 90, 122, 100)])
        nodes = sorted((n["geometry"]["x"], n["local_id"]) for n in ext["nodes"] if n["kind"] != "tee")
        self.assertEqual([x for x, _ in nodes], [100, 110, 130])
        self.assertEqual([sorted(e["node_local_id"] for e in r["endpoints"]) for r in ext["relations"]],
                         [sorted(i for _, i in nodes[:2])])

    def test_air_handler_panels_are_filters_and_coils_linked_in_a_row(self):
        # APR1400 072쪽 공조기(범례 1.7-1 2/4): 칸을 변끼리 맞대 한 줄로 그리고, 여과 판은 변에서 변까지 빗금, 코일 판은 폭을
        # 가로지르는 지그재그와 HC 글자다. 판은 표 칸이 아니라 노드(filter·heat_exchanger)이고, 덕트 선이 없는 칸 사이는 공기가
        # 지나는 차례대로 이어진다. 칸 줄에 들지 않은 빗금 상자(007쪽 단면)는 판이 아니다
        hatch = [line((130, 100 + 5 * k), (142, 105 + 5 * k)) for k in range(7)]
        hatch += [line((130, 105 + 5 * k), (142, 100 + 5 * k)) for k in range(7)]
        coil_box = [(160, 105), (160, 100), (172, 100), (172, 140), (160, 140), (160, 135)]
        coil = [prim(coil_box + [coil_box[0]], closed=True, fill=True, white=True), line(*coil_box),
                line((166, 105), (160, 105), (160, 135), (166, 135), (166, 130), (160, 125), (172, 118), (166, 112),
                     (166, 105), (172, 105), (172, 135), (166, 135))]
        lone = [rect(400, 100, 412, 140)] + [line((400, 100 + 5 * k), (412, 105 + 5 * k)) for k in range(7)] + [
            line((400, 105 + 5 * k), (412, 100 + 5 * k)) for k in range(7)]
        # 빈 칸 142~160은 판과 변을 맞대 예전처럼 표 칸으로 빠진다. 그 칸 위로 내려온 계기 선은 칸을 계기에 합치지 않는다(081쪽)
        bubble = [circle(150, 80, 5), line((150, 80), (150, 100))]
        prims = [rect(100, 100, 131, 140), rect(130, 100, 142, 140)] + hatch + [rect(142, 100, 160, 140)] + coil + [
            rect(172, 100, 200, 140), circle(188, 120, 10), rect(40, 115, 50, 125), line((50, 120), (100, 120)),
            line((200, 120), (260, 120)), rect(260, 115, 270, 125)] + lone + bubble
        ext = pdf_run(prims, words=[word("HC", 162, 101, size=3)])
        kind = {n["geometry"]["x"]: n["kind"] for n in ext["nodes"]}
        self.assertEqual((kind[130], kind[160]), ("filter", "heat_exchanger"))
        self.assertNotIn("filter", [k for x, k in kind.items() if x >= 400])
        self.assertEqual([n["geometry"]["width"] for n in ext["nodes"] if n["geometry"]["x"] == 145], [10])
        x = {n["local_id"]: n["geometry"]["x"] for n in ext["nodes"]}
        pairs = sorted(sorted(x[e["node_local_id"]] for e in r["endpoints"]) for r in ext["relations"])
        self.assertEqual(pairs, [[40, 100], [100, 130], [130, 160], [160, 172], [172, 178], [172, 260]])

    def test_dot_grid_in_outline_is_pattern_not_nodes(self):
        # APR1400 007쪽 베어링 냉각기: 담는 외곽 안에 그린 관 다발 점 격자는 무늬다. 점마다 노드를 두지 않고, 점에 닿은 선 끝도
        # 붙이지 않는다. 한 줄로만 늘어선 같은 모양(008쪽 SPARGER 분사구 줄)은 무늬가 아니다
        dots = [rect(130 + 4 * i, 130 + 4 * j, 132 + 4 * i, 132 + 4 * j) for i in range(4) for j in range(3)]
        row = [rect(300 + 4 * i, 130, 302 + 4 * i, 132) for i in range(4)]
        ext = pdf_run([rect(100, 100, 200, 200)] + dots + row + [line((110, 131), (130, 131))],
                      words=[word("COOLER", 140, 180)])
        ignored = [o for o in ext["drawing"]["ignored_objects"] if o.get("reason") == "pattern_grid"]
        self.assertEqual(len(ignored), 12)
        self.assertEqual(sorted(n["geometry"]["x"] for n in ext["nodes"] if n["kind"] != "tee"), [100, 300, 304, 308, 312])
        ids = {n["local_id"] for n in ext["nodes"]}
        ends = [e for r in ext["relations"] + ext["unresolved_connectors"] for e in r["endpoints"]]
        self.assertEqual([e["status"] for e in ends if e["point"][0] == 130], ["unconnected"])
        self.assertTrue(all(e["node_local_id"] in ids for e in ends if e["node_local_id"]))

    def test_unconnected_flat_piece_empty_frame_and_hatch_are_ignored(self):
        # 089쪽 글자 밑줄처럼 아무 선도 닿지 않은 넓이 없는 선 조각, 080쪽 그림 틀처럼 이름도 연결도 없는 빈 큰 상자, 007쪽 베어링
        # 단면처럼 빗금만 친 상자는 노드가 아니다. 이름이 붙은 상자, 기기 크기(40pt) 상자, X자로 엇갈려 그은 상자(필터)는 노드다
        hatch = [rect(400, 100, 415, 104)] + [line((402 + 4 * k, 104), (405 + 4 * k, 100)) for k in range(3)]
        cross = [rect(500, 100, 515, 104), line((502, 104), (505, 100)), line((502, 100), (505, 104)),
                 line((506, 104), (509, 100))]
        ext = pdf_run([line((100, 300), (108, 300)), rect(100, 100, 180, 160), rect(200, 100, 280, 160),
                       rect(300, 100, 340, 140)] + hatch + cross, words=[word("TANK", 220, 115)])
        reasons = sorted(o.get("reason") for o in ext["drawing"]["ignored_objects"]
                         if o.get("reason") in ("stray_stroke", "bare_outline", "hatch_block"))
        self.assertEqual(reasons, ["bare_outline", "hatch_block", "stray_stroke"])
        self.assertEqual(sorted(n["geometry"]["x"] for n in ext["nodes"] if n["kind"] != "tee"), [200, 300, 500])

    def test_triangle_row_on_line_is_one_sparger(self):
        # 범례 1.7-1 SPRAY NOZZLE OR SPARGER(008쪽 SPARGER): 막대 하나에 같은 삼각형이 같은 간격으로 매달린 것은 분사구 하나다.
        # 삼각형마다 노드가 생기지 않고, 막대 가운데로 들어온 공급 배관은 그 분사구에 닿는다
        tris = [prim([(100 + 4 * i, 132.2), (101.25 + 4 * i, 130.2), (102.5 + 4 * i, 132.2), (100 + 4 * i, 132.2)],
                     closed=True) for i in range(4)]
        ext = pdf_run([rect(97, 60, 117, 80), line((107, 80), (107, 130)), line((100, 130), (114.5, 130))] + tris)
        nodes = [n for n in ext["nodes"] if n["kind"] != "tee"]
        self.assertEqual(sorted((n["geometry"]["x"], n["kind"]) for n in nodes), [(97, None), (100, "sparger")])
        self.assertEqual([sorted(e["node_local_id"] for e in r["endpoints"]) for r in ext["relations"]],
                         [sorted(n["local_id"] for n in nodes)])

    def test_air_flow_arrow_head_stays_with_shaft(self):
        # 범례 1.7-1(2 of 4) 공조 덕트 끝 화살표(080쪽): 덕트 끝 막대와 굵은 몸통, 화살촉이 한 기호다. 화살촉이 따로 떨어져
        # 몸통만 노드가 되지 않는다. 선과 표식으로 된 모양이지만 체크밸브가 아니라 공기 흐름 표시(air_flow_arrow)다
        head = prim([(158, 128.6), (164, 130), (158, 131.4), (158, 128.6)], closed=True, fill=True)
        ext = pdf_run([rect(100, 120, 120, 140), line((120, 130), (150, 130), width=1.1),
                       line((150, 128.5), (150, 131.5), width=1.1), line((151.9, 130), (158, 130), width=1.1), head])
        arrows = [n for n in ext["nodes"] if n["kind"] != "tee" and n["geometry"]["x"] >= 150]
        self.assertEqual([(n["kind"], round(n["geometry"]["x"] + n["geometry"]["width"], 1)) for n in arrows],
                         [("air_flow_arrow", 164)])
        self.assertEqual(len(ext["relations"]), 1)

    def test_thick_duct_starting_inside_symbol_is_not_stem(self):
        # 072쪽 AU02A 송풍기: 굵은 출구 덕트(1.08pt)가 가는 선(0.13pt) 송풍기 그림 안에서 시작한다. 구동부 축으로 보아 송풍기와
        # 덕트 끝 상자를 한 기호로 합치지 않는다. 같은 굵기의 선이면 예전처럼 축이다
        def nodes(width):
            r = 8
            pts = [(100 + r, 100), (100, 100 + r), (100 - r, 100), (100, 100 - r), (100 + r, 100)]
            fan = prim(pts, closed=True, curved=True, ext=pts + [(108, 108), (92, 108), (92, 92), (108, 92)], width=0.13)
            ext = pdf_run([fan, line((100, 100), (160, 100), width=width), rect(160, 95, 170, 105, width=0.13)])
            return sorted(n["geometry"]["x"] for n in ext["nodes"] if n["kind"] != "tee")
        self.assertEqual(nodes(1.08), [92, 160])
        self.assertEqual(nodes(0.13), [92])

    def test_air_flow_arrow_needs_short_bar_on_its_line(self):
        # 072쪽 덕트 끝(s029): 굵은 몸통·화살촉과 화살촉 앞 막대가 한 기호로 묶인다. 막대가 있어야 덕트 끝 화살표다.
        # 막대 없이 선과 화살촉만(012쪽 배기)이거나 몸통 줄 양쪽으로 길게 뻗은 칸막이 선 옆(128쪽 건물 경계)이면 아니다
        def kind_at(bar):
            head = prim([(288.3, 228.0), (288.3, 226.1), (284.5, 227.1), (288.3, 228.0)], closed=True, fill=True)
            prims = [line((288.3, 227.1), (299.5, 227.1), width=1.1), head] + ([line(*bar, width=1.1)] if bar else [])
            ext = pdf_run(prims)
            return [n["kind"] for n in ext["nodes"] if n["geometry"]["x"] < 300 and n["kind"] != "tee"]
        self.assertEqual(kind_at([(282.6, 225.6), (282.6, 228.6)]), ["air_flow_arrow"])
        self.assertNotIn("air_flow_arrow", kind_at(None))
        self.assertNotIn("air_flow_arrow", kind_at([(282.6, 215), (282.6, 240)]))

    def test_line_continuing_same_pen_is_not_a_symbol(self):
        # 007쪽 펌프 몸체선: 같은 굵기로 이어 그은 곧은 선 토막은 한 끝이 떠 있어도 선 기호 노드가 아니다. 글자 지시선(더 가는
        # 선)이 끝에 닿은 경계 표시 눈금(025쪽 CCW HX BLDG.)과 비스듬한 빗금 조각(083쪽 필터)은 예전처럼 선 기호로 묶는다
        ext = pdf_run([rect(90, 80, 110, 100), line((100, 100), (100, 150), width=0.13),
                       line((100, 150), (130, 150), width=0.13),
                       rect(280, 80, 290, 90), line((290, 90), (300, 100), width=0.026), line((300, 100), (300, 106), width=0),
                       rect(380, 80, 390, 90), line((390, 85), (400, 85), width=0.124),
                       line((400, 85), (408, 93), width=0.124)])
        self.assertEqual(sorted(n["geometry"]["x"] for n in ext["nodes"] if n["kind"] != "tee"), [90, 280, 300, 380, 400])

    def test_cylinder_operator_cells_stay_with_valve_body(self):
        # 054·134쪽 실린더 구동부: 밸브 몸통 옆 두 칸 상자의 한 칸을 검게 칠하고 외곽선을 따로 긋는다. 작은 두 칸은 표 칸이 아니고,
        # 외곽선이 있는 검은 얇은 칸은 점선 조각이 아니다. 한 기호로 묶여야 몸통이 조각 노드로 갈라지지 않는다
        cells = pdf_run([rect(100, 100, 105, 105), rect(105, 100, 110, 105)])
        self.assertEqual(len([n for n in cells["nodes"] if n["kind"] != "tee"]), 1)
        table = pdf_run([rect(100, 100, 130, 108), rect(130, 100, 160, 108)])
        self.assertEqual([n for n in table["nodes"] if n["kind"] != "tee"], [])
        black = pdf_run([rect(100, 100, 102, 104), rect(102, 100, 103.5, 104, fill=True), rect(102, 100, 103.5, 104),
                         rect(103.6, 100, 107, 104)])
        self.assertEqual(len([n for n in black["nodes"] if n["kind"] != "tee"]), 1)

    def test_pipe_drawn_under_square_body_is_cut_at_it(self):
        # APR1400 072쪽 댐퍼 Y1202A: 덕트 하나가 정사각형 몸체 밑을 가운데 줄로 지나간다. 흐름 축을 몰라도 마주 보는 두 변을
        # 꿰뚫는 선은 그 몸체에서 나뉘어 양쪽 이웃이 몸체를 건너뛰지 않는다. 몸체 옆을 스치는 선은 나누지 않는다
        a, b, damper = rect(100, 120, 120, 140), rect(300, 120, 320, 140), rect(200, 125, 210, 135)
        ext = pdf_run([a, b, damper, line((120, 130), (300, 130))])
        ids = {n["geometry"]["x"]: n["local_id"] for n in ext["nodes"]}
        pairs = sorted(sorted(ids_x for ids_x, nid in ids.items() if nid in {e["node_local_id"] for e in r["endpoints"]})
                       for r in ext["relations"])
        self.assertEqual(pairs, [[100, 200], [200, 300]])
        grazing = pdf_run([a, b, damper, line((120, 136), (300, 136))])
        self.assertEqual(len(grazing["relations"]), 1)
        # 105쪽 PC 0612: 두 배관이 엇갈리는 자리에 얹은 글자 상자는 두 축 모두로 꿰뚫린다. 나누면 네 갈래가 한데 이어진다
        crossing = pdf_run([a, b, damper, rect(195, 40, 215, 60), rect(195, 200, 215, 220),
                            line((120, 130), (300, 130)), line((205, 60), (205, 200))])
        self.assertEqual(len(crossing["relations"]), 2)

    def test_short_lines_hanging_at_pipe_end_become_end_symbol(self):
        # APR1400 097쪽 호스 연결 ⊔·128쪽 벤트 끝 눈금: 배관이 짧은 가로대 가운데에서 끝난다. 가로대 반쪽 둘이 매달린
        # 분기점이 아니라 끝 기호 노드다. 기호에서 짧게 나온 축 끝의 가로대(008쪽 V236 위 T자 손잡이)는 그대로 둔다
        ext = pdf_run([rect(100, 100, 140, 160), line((140, 130), (200, 130)), line((200, 127), (200, 133))])
        self.assertEqual(sorted(n["kind"] or "-" for n in ext["nodes"]), ["-", "-"])
        self.assertEqual(len(ext["relations"]), 1)
        self.assertTrue(all(e["node_local_id"] for e in ext["relations"][0]["endpoints"]))
        def run(rest_len):
            box = pdf_vector._Sym([{"id": "b", "pts": [(0, 0), (1, 1)], "bbox": (0, 0, 1, 1), "kind_": "body"}])
            tee, free = ("tee", 0), ("free", 0)
            chains = [{"pts": [(-rest_len, 0), (0, 0)], "ends": [(("sym", box), (-rest_len, 0), "x"), (tee, (0, 0), "j")],
                       "evidence": ["p1"]},
                      {"pts": [(0, 0), (0, 3)], "ends": [(tee, (0, 0), "j"), (free, (0, 3), "j")], "evidence": ["p2"]},
                      {"pts": [(0, 0), (0, -3)], "ends": [(tee, (0, 0), "j"), (free, (0, -3), "j")], "evidence": ["p2"]}]
            made, left, tees = pdf_vector._stub_ends([(0, 0)], chains)
            return len(made), len(left), len(tees)
        self.assertEqual(run(30), (1, 1, 0))
        self.assertEqual(run(5), (0, 3, 1))

    def test_part_drawn_between_two_plates_is_one_inline_node(self):
        # APR1400 097쪽 Y형 거름망 ST01A: 배관이 두 판 '|  |' 가운데에서 끊기고, 판 사이에 축 선과 아래로 빠진 다리·눈금이
        # 있다. 판·축 선·다리가 한 노드가 되고 양쪽 배관이 그 노드에 붙는다. 오리피스(평행 판)로 읽지 않는다
        ext = pdf_run([rect(100, 100, 140, 160), rect(300, 100, 340, 160),
                       line((140, 130), (200, 130)), line((207.5, 130), (300, 130)),
                       line((200, 128.1), (200, 131.9)), line((207.5, 128.1), (207.5, 131.9)),
                       line((200, 130), (207.5, 130)), line((202.6, 130), (204.7, 132.3)), line((204.2, 132.8), (205.2, 131.8))])
        inline = [n for n in ext["nodes"] if n["geometry"]["x"] >= 199 and n["geometry"]["x"] + n["geometry"]["width"] <= 209]
        self.assertEqual(len(inline), 1)
        self.assertIsNone(inline[0]["kind"])
        self.assertEqual(sorted(len({e["node_local_id"] for e in r["endpoints"]} & {inline[0]["local_id"]})
                                for r in ext["relations"]), [1, 1])

    def test_pipe_drawn_through_valve_along_its_axis_is_split_at_the_valve(self):
        # APR1400 105쪽 전동 밸브·128쪽 축소관: 한 선으로 그은 배관 위에 얹은 밸브. 흐름 축을 따라 가운데를 지나는 선은
        # 밸브 양 끝에서 나뉘어 밸브에 붙는다. 축을 가로지르는 선은 나누지 않는다
        def run(valve):
            ext = pdf_run([rect(80, 100, 100, 120), rect(300, 100, 320, 120), rect(193, 30, 213, 50),
                           rect(193, 170, 213, 190), valve, line((100, 110), (300, 110)), line((203, 50), (203, 170))])
            at = {n["local_id"]: (n["geometry"]["x"], n["geometry"]["y"]) for n in ext["nodes"]}
            return sorted(tuple(sorted(at[e["node_local_id"]] for e in r["endpoints"])) for r in ext["relations"])
        bowtie = prim([(200, 108.5), (206, 111.5), (206, 108.5), (200, 111.5), (200, 108.5)], closed=True)
        self.assertEqual(run(bowtie), [((80, 100), (200, 108.5)), ((193, 30), (193, 170)), ((200, 108.5), (300, 100))])
        # 세로로 긴 몸체는 세로가 흐름 축이다. 가로 배관은 축을 가로지르므로 나누지 않는다
        upright = prim([(201.5, 107), (204.5, 107), (201.5, 113), (204.5, 113), (201.5, 107)], closed=True)
        self.assertEqual(run(upright), [((80, 100), (300, 100)), ((193, 30), (201.5, 107)), ((193, 170), (201.5, 107))])

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

    def test_boundary_mark_line_is_not_a_symbol(self):
        # APR1400 046쪽 CB|UCT 경계 표시: 가는 표시선 위 꼭짓점을 마주 댄 화살촉 둘(▶◀)과 배관까지 가는 눈금. 표시선을
        # 선 기호로 남기면 눈금을 거쳐 배관에 붙은 가짜 가지가 생긴다. 경계 표시는 공정 기호가 아니다
        thick, thin = 1.3, 0.16
        ext = pdf_run([rect(80, 145, 100, 155, width=thin), rect(260, 145, 280, 155, width=thin),
                       line((100, 150), (260, 150), width=thick), line((196.2, 150), (196.2, 180), (240, 180), width=thick),
                       rect(240, 175, 260, 185, width=thin), line((190, 150.9), (190, 176), width=thin),
                       line((187.9, 163), (196.1, 163), width=thin),
                       prim([(189.4, 160.7), (190.6, 160.7), (190, 163), (189.4, 160.7)], closed=True, fill=True),
                       prim([(189.4, 165.3), (190.6, 165.3), (190, 163), (189.4, 165.3)], closed=True, fill=True)])
        self.assertFalse([n for n in ext["nodes"] if "pdf-path-0005" in n["evidence"]["pdf_objects"]])
        self.assertEqual([n["kind"] for n in ext["nodes"]].count("tee"), 1)
        self.assertEqual(len(ext["relations"]), 3)

    def test_single_line_does_not_take_equipment_word(self):
        # APR1400 025쪽: 'CCW HX BLDG.' 경계 표시 옆에 남은 눈금 토막이 열교환기가 되던 자리. 곧은 선 하나는 설비가 아니다
        # 선이 닿지 않은 곧은 선 토막은 노드로도 내지 않는다(_noise_symbols stray_stroke)
        ext = pdf_run([line((100, 100), (100, 108))], [word("CCW", 90, 101), word("HX", 103, 101)])
        self.assertEqual([n["kind"] for n in ext["nodes"]], [])
        self.assertIn("stray_stroke", [o.get("reason") for o in ext["drawing"]["ignored_objects"]])

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

    def test_pipe_broken_where_another_line_crosses_is_one_pipe(self):
        # 범례 'LINE NOT CONNECTED': 잇지 않는 선을 끊어 그린다(APR1400 008쪽 배출 상승관이 일점쇄선 자리에서 끊김).
        # 끊긴 두 조각은 한 배관이고, 가로지르는 점선과는 잇지 않는다. 빈칸이 넓거나 가로지르는 선이 없으면 잇지 않는다
        def run(gap, crossing=True):
            dash = [dict(line((80, 150), (320, 150), width=0.25), dash=[[6.0, 3.0], 0.0])] if crossing else []
            ext = pdf_run([rect(190, 60, 210, 80), rect(190, 220, 210, 240), rect(60, 140, 80, 160),
                           rect(320, 140, 340, 160), line((200, 80), (200, 150 - gap / 2), width=0.25),
                           line((200, 150 + gap / 2), (200, 220), width=0.25)] + dash)
            ys = {n["local_id"]: n["geometry"]["y"] for n in ext["nodes"]}
            return sorted((r["kind"], tuple(sorted(ys[e["node_local_id"]] for e in r["endpoints"])))
                          for r in ext["relations"])
        self.assertEqual(run(2.4), [("physical_connection", (60, 220)), ("signal_connection", (140, 140))])
        self.assertNotIn(("physical_connection", (60, 220)), run(6.0))
        self.assertNotIn(("physical_connection", (60, 220)), run(2.4, crossing=False))

    def test_pipe_broken_across_line_drawn_into_symbol_is_one_pipe(self):
        # APR1400 134쪽: LS 012 지시선이 LS 원과 한 기호로 묶이고, 그 선 앞뒤에서 끊어 그린 AOV 256 배관의 두 끝이 그
        # 기호에 붙어 위아래가 기호를 거쳐 이어졌다. 끊어 그린 배관은 그 선을 건너가는 한 배관이다. 굵기가 다르면 그대로 둔다
        def run(lower_width):
            lead = {"id": "lead", "pts": [(150, 150), (242, 150)], "bbox": (150, 150, 242, 150), "kind_": "poly",
                    "width": 0.26}
            sym = pdf_vector._Sym([lead], stroke_only=True)
            polys = [{"id": "up", "pts": [(200, 80), (200, 148.8)], "width": 0.26},
                     {"id": "down", "pts": [(200, 151.2), (200, 220)], "width": lower_width}]
            _, chains = pdf_vector._build_solid([sym], polys, [], dict(pdf_vector.PARAMS))
            return sorted(tuple(ch["evidence"]) for ch in chains)
        self.assertEqual(run(0.26), [("down", "up")])
        self.assertEqual(run(0.13), [("down",), ("up",)])

    def test_pipe_junction_beside_symbol_is_tee_not_attached(self):
        # APR1400 134쪽 AOV 001 오른쪽: 6" 관 셋이 끝끼리 만나는 분기점이 번호 원 001에서 1.3pt 떨어져 있다. 세 끝이
        # 그 원에 붙으면 배관이 번호 원으로 끝난다. 원에 닿지 않고 끝끼리 만나는 자리는 분기점이다. 밸브 몸통 옆 분기점은
        # 몸통 포트에 붙은 분기라 그대로 몸통에 붙인다
        def run(beside):
            ext = pdf_run([beside, rect(80, 90, 100, 110), rect(300, 90, 320, 110), rect(190, 200, 210, 220),
                           line((100, 99.3), (200, 99.3), width=0.26), line((200, 99.3), (300, 99.3), width=0.26),
                           line((200, 99.3), (200, 200), width=0.26)])
            return [n["kind"] for n in ext["nodes"]].count("tee")
        self.assertEqual(run(circle(200, 90, 8)), 1)
        self.assertEqual(run(rect(192, 88, 208, 98)), 0)

    def test_pipe_corner_beside_symbol_is_not_attached(self):
        # APR1400 008쪽 MOV 상승관 꼭대기 모서리가 TEW 상자 변에서 1.8pt 떨어져 있다. 두 선이 끝을 맞댄 모서리는 배관이
        # 꺾이는 자리라 상자에 붙이지 않는다
        ext = pdf_run([rect(190, 220, 210, 240), rect(300, 90, 320, 110), rect(170, 98, 198.2, 130),
                       line((200, 220), (200, 100), width=0.25), line((300, 100), (200, 100), width=0.25)])
        pos = {n["local_id"]: (n["geometry"]["x"], n["geometry"]["y"]) for n in ext["nodes"]}
        self.assertEqual([(r["kind"], sorted(pos[e["node_local_id"]] for e in r["endpoints"]))
                          for r in ext["relations"]], [("physical_connection", [(190, 220), (300, 90)])])
        # 배관 끝이 다른 선 중간에 얹히면(그 선 끝이 end_tol 안이어도) 끝끼리 맞댄 모서리가 아니라서 기호에 붙인 그대로
        # 둔다(APR1400 134쪽 FI-041: 배관 끝이 플랜지 판 가운데에 얹힘)
        ext = pdf_run([rect(300, 90, 320, 110), rect(170, 98, 198.2, 130), rect(190, 220, 210, 240),
                       line((300, 100), (200, 100), width=0.25), line((200, 99.0), (200, 220), width=0.25)])
        pos = {n["local_id"]: (n["geometry"]["x"], n["geometry"]["y"]) for n in ext["nodes"]}
        self.assertIn(("physical_connection", [(170, 98), (300, 90)]),
                      [(r["kind"], sorted(pos[e["node_local_id"]] for e in r["endpoints"])) for r in ext["relations"]])

    def test_crossing_gap_beside_lead_corner_or_symbol_is_joined(self):
        # APR1400 008쪽 배출 상승관이 일점쇄선 자리에서 끊긴 위 조각 끝에 TEW 지시선 끝이 맞닿거나(분기), 상승관이 TEW
        # 상자 옆을 나란히 지나 끊긴다. 둘 다 끊어 그린 한 배관이다. 배관 끝에 가로 판이 얹히면 잇지 않는다
        def run(extra):
            dash = dict(line((80, 150), (320, 150), width=0.25), dash=[[6.0, 3.0], 0.0])
            ext = pdf_run([rect(190, 60, 210, 80), rect(190, 220, 210, 240), rect(60, 140, 80, 160),
                           rect(320, 140, 340, 160), line((200, 80), (200, 148.8), width=0.25),
                           line((200, 151.2), (200, 220), width=0.25), dash] + extra)
            ys = {n["local_id"]: n["geometry"]["y"] for n in ext["nodes"] if n.get("kind") != "tee"}
            adj = {}
            for r in ext["relations"]:
                if r["kind"] == "physical_connection":
                    a, b = (e["node_local_id"] for e in r["endpoints"])
                    adj.setdefault(a, set()).add(b)
                    adj.setdefault(b, set()).add(a)
            return {frozenset(ys[x] for x in (a, c)) for a in adj if a in ys for b in adj[a]
                    for c in ({b} if b in ys else adj[b] - {a}) if c in ys}
        lead = run([rect(120, 100, 140, 120), line((130, 120), (130, 147.8), (200, 147.8), width=0.12)])
        self.assertEqual(lead, {frozenset((60, 220)), frozenset((60, 100)), frozenset((100, 220))})
        self.assertEqual(run([rect(170, 128, 197.9, 148)]), {frozenset((60, 220))})
        self.assertNotIn(frozenset((60, 220)), run([line((198.6, 148.8), (201.4, 148.8), width=0.12)]))
        # 판이 배관 끝에서 0.6pt 떨어져 있어도 판 끝이 end_tol 안이면 판에 얹힌 끝이다(APR1400 065쪽 플랜지)
        self.assertNotIn(frozenset((60, 220)), run([line((199.0, 149.4), (201.0, 149.4), width=0.12)]))
        # 빈칸 양쪽 끝이 모두 기호 옆이면 기호 자리의 빈칸일 수 있어 잇지 않는다(APR1400 134쪽 LS 013 원 옆)
        self.assertNotIn(frozenset((60, 220)), run([rect(170, 140, 198.9, 160)]))

    def test_two_pieces_on_one_line_are_not_orifice_plates(self):
        # 오리피스 판은 배관을 가로질러 나란히 선 두 판이다. 한 줄 위에 이어 놓인 두 조각은 판이 아니다
        side = pdf_run([line((200, 100), (200, 108)), line((203, 100), (203, 108))])
        inline = pdf_run([line((200, 100), (200, 108)), line((200, 110), (200, 118))])
        self.assertEqual([n["kind"] for n in side["nodes"]], ["orifice"])
        self.assertNotIn("orifice", [n["kind"] for n in inline["nodes"]])

    def test_dashed_line_continuing_a_pipe_end_is_pipe(self):
        # APR1400 008쪽 파일럿 밸브 옆 출구 일점쇄선이 배출 상승관 아래 끝에 끝을 맞대고 이어진다. 점선이 배관을 이어 그린
        # 것이라 한 배관이다. 같은 점선이 계기에서 나오면 신호선으로 둔다
        def run(source, words=()):
            dash = dict(line((120, 210), (200, 210), (200, 180), width=0.25), dash=[[6.0, 3.0], 0.0])
            ext = pdf_run(source + [dash, line((200, 180), (200, 100), (300, 100), width=0.25),
                                    rect(300, 90, 320, 110)], words)
            return [(r["kind"], r["line_type"]) for r in ext["relations"]], ext["unresolved_connectors"]
        self.assertEqual(run([rect(100, 200, 120, 220)]), ([("physical_connection", "pdf_dashed")], []))
        relations, unresolved = run([circle(106, 210, 14)], [word("PT", 101, 202), word("101", 101, 209)])
        self.assertEqual((relations, unresolved), ([("signal_connection", "pdf_dashed")], []))

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

    def test_dashed_path_end_touching_symbol_wins_over_nearer_last_piece(self):
        # APR1400 008쪽 V310: 점선 무늬의 빈칸 때문에 끝 조각이 경로 끝점보다 짧아, 조각만 보면 옆 계기 원이 더 가깝다.
        # 경로 끝점이 닿은 기호가 선이 끝나는 기호다
        def ends(prims):
            ext = pdf_run(prims)
            xy = {n["local_id"]: (n["geometry"]["x"], n["geometry"]["y"]) for n in ext["nodes"]}
            return [sorted(xy[e["node_local_id"]] for e in r["endpoints"]) for r in ext["relations"]]
        dash = dict(line((102, 130), (102, 110), width=0.25), dash=[[3.0, 4.0], 0.0])
        self.assertEqual(ends([rect(100, 104, 104, 110), rect(92, 111, 101, 119), rect(100, 130, 104, 134), dash]),
                         [[(100, 104), (100, 130)]])

    def test_dashed_path_grazing_symbol_side_passes_by(self):
        # APR1400 008쪽 V313: 두 끝이 모두 밖인 점선이 몸체 변 0.3pt 옆을 지나면 그 기호를 꿰뚫는 선이 아니다. 조각을
        # 기호에 넣지 않고, 선은 끊기지 않고 두 끝 기호를 잇는다
        dash = dict(line((103.3, 80), (103.3, 130), width=0.25), dash=[[3.0, 2.0], 0.0])
        analysis = pdf_vector.analyze(600.0, 400.0, [], [rect(100, 100, 103, 106), rect(98, 70, 108, 80),
                                                         rect(98, 130, 108, 140), dash])
        valve = next(s for s in analysis["symbols"] if s.bbox[0] == 100)
        self.assertEqual(valve.dashes, [])
        ext = pdf_vector.build_extraction(analysis, 600.0, 400.0, 1, 0, "synthetic.pdf", "0" * 64)
        xy = {n["local_id"]: n["geometry"]["y"] for n in ext["nodes"]}
        self.assertEqual([sorted(xy[e["node_local_id"]] for e in r["endpoints"]) for r in ext["relations"]], [[70, 130]])

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

    def test_orifice_box_with_pipe_stub_on_plate(self):
        # APR1400 016쪽 OR08D: 아래 판에 0.5pt 배관 토막이 닿고 그 끝에서 배관이 이어진다. 토막은 판 사이 칸 안의 선이
        # 아니고, 이어지는 선은 같은 배관이라 판에 닿는 배관 끝은 하나다
        ext = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), line((140, 109.6), (220, 109.6)),
                       line((220, 108.15), (220, 111.05)), line((222.9, 108.15), (222.9, 111.05)),
                       line((221.45, 108.875), (221.45, 110.325)), line((222.9, 109.6), (223.38, 109.6)),
                       line((223.38, 109.6), (300, 109.6))])
        self.assertEqual([n["kind"] for n in ext["nodes"] if 215 < n["geometry"]["x"] < 225], ["orifice"])
        self.assertEqual(len(ext["relations"]), 2)

    def test_thin_filled_triangle_is_arrowhead_not_dash(self):
        # APR1400 105쪽 벤트 끝 화살촉(1.4×2.9pt): 점선 조각 크기 안이지만 닫힌 삼각형은 화살촉이다. 검정 견본 묶음에는
        # 넣지 않는다(016쪽 V420 나비 몸통 옆 위치 표시 화살촉이 몸통 묶음을 바꾸지 않게)
        tri = prim([(300, 109.3), (302.9, 110), (300, 110.7), (300, 109.3)], closed=True, fill=True)
        bar = rect(200, 109.5, 204, 110.5, fill=True)
        cls = pdf_vector._classify_primitives(600, 400, [tri, bar], dict(pdf_vector.PARAMS))
        self.assertEqual(([d["id"] for d in cls["dashes"]], [m["id"] for m in cls["markers"]]),
                         (["pdf-path-0001"], ["pdf-path-0000"]))
        self.assertEqual(pdf_vector._black_fills(cls), [])

    def test_filled_half_disc_is_body_not_marker(self):
        # APR1400 105쪽 공기구동 밸브 위 검은 반달꼴(5.1×2.5pt)은 다이어프램 구동부다. 화살촉 같은 표식으로 두면 구동부
        # 견본에 대 보지 못해 밸브가 수동 밸브로 남는다. 같은 크기의 검은 삼각형은 그대로 표식이다
        dome = prim([(300, 112.5), (305.1, 112.5), (302.55, 110), (300, 112.5)], fill=True, curved=True,
                    ext=[(300, 112.5), (305.1, 112.5), (305.1, 110), (300, 110)])
        tri = prim([(200, 112.5), (205.1, 112.5), (202.55, 110), (200, 112.5)], closed=True, fill=True)
        cls = pdf_vector._classify_primitives(600, 400, [dome, tri], dict(pdf_vector.PARAMS))
        self.assertEqual(([b["id"] for b in cls["bodies"]], [m["id"] for m in cls["markers"]]),
                         (["pdf-path-0000"], ["pdf-path-0001"]))

    def test_pipe_ending_in_outward_arrowhead_is_vent_end(self):
        # 범례의 대기 방출 화살표(APR1400 046쪽 ATM, 105쪽 지붕 위 벤트): 기호에 닿지 않은 배관 끝이 바깥을 향한 화살촉에서
        # 끝나면 그 화살촉이 끝 기호다. 글자가 VENT·ATM이면 vent, 없으면 미분류
        def head(x, d=1):
            return prim([(x, 109.3), (x + d * 2.9, 110), (x, 110.7), (x, 109.3)], closed=True, fill=True)

        def ends(ext):
            kind = {n["local_id"]: n["kind"] for n in ext["nodes"]}
            return sorted(tuple(sorted(str(kind[e["node_local_id"]]) for e in r["endpoints"] if e.get("node_local_id")))
                          for r in ext["relations"])
        base = [rect(100, 90, 140, 130), line((140, 110), (300, 110))]
        self.assertEqual(ends(pdf_run(base + [head(300)])), [("None", "None")])
        self.assertEqual(ends(pdf_run(base + [head(300)], [word("ATM", 296, 100, size=3.0)])), [("None", "vent")])
        # 배관 안쪽을 가리키는 화살촉(흘러드는 끝), 화살촉 끝이 다른 선에 닿는 지시선, 점선(신호선) 끝은 끝 기호가 아니다
        inward = pdf_run(base + [prim([(302.9, 109.3), (300, 110), (302.9, 110.7), (302.9, 109.3)], closed=True, fill=True)])
        self.assertEqual(len(inward["nodes"]), 1)
        leader = pdf_run(base + [head(300), rect(100, 200, 140, 240), line((303.5, 60), (303.5, 160))])
        self.assertEqual(sum(1 for n in leader["nodes"] if n["geometry"]["x"] >= 299 and n["kind"] != "tee"), 0)
        dashed = line((140, 110), (300, 110))
        dashed["dash"] = [[3.0, 2.0], 0.0]
        self.assertEqual(len(pdf_run([rect(100, 90, 140, 130), dashed, head(300)])["nodes"]), 1)
        # 배관 중간의 흐름 화살촉은 두 배관 끝을 잇는다(끝 기호가 아니다)
        mid = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), line((140, 110), (220, 110)), head(220),
                       line((222.9, 110), (300, 110))])
        self.assertEqual(ends(mid), [("None", "None")])
        self.assertEqual(len(mid["nodes"]), 2)

    def test_bracket_opening_away_from_pipe_end_is_hose_connection(self):
        # 범례 1.7-1 1/4 HOSE CONNECTION (COUPLER) '—[' (APR1400 097쪽 FILL·이동 장비 연결구): 배관 끝이 괄호 등판에 닿고 두 발이
        # 배관 반대쪽으로 뻗는다. 발이 배관 쪽이면 나사 마개 '—]', 등판이 둘이면 막음 플랜지 '—| |'라 호스 연결구가 아니다
        def kind_at_end(*parts):
            ext = pdf_run([rect(100, 90, 140, 130), line((140, 110), (300, 110))] + list(parts), [word("FILL", 305, 107, size=3.0)])
            return [n["kind"] for n in ext["nodes"] if n["geometry"]["x"] >= 290]
        self.assertEqual(kind_at_end(line((302, 108), (300, 108), (300, 112), (302, 112))), ["hose_connection"])
        self.assertNotIn("hose_connection", kind_at_end(line((298, 108), (300, 108), (300, 112), (298, 112))))
        self.assertNotIn("hose_connection", kind_at_end(line((300, 108), (300, 112)), line((301.5, 108), (301.5, 112))))
        # 등판과 발 길이가 같은 작은 'ㅂ'꼴(024쪽 'V' 옆 벤트 마개)도 아니다
        self.assertNotIn("hose_connection", kind_at_end(line((301.5, 109.25), (300, 109.25), (300, 110.75), (301.5, 110.75))))

    def test_short_outlet_arrow_of_line_symbol_is_part_of_it(self):
        # APR1400 025·033쪽 기기 드레인: 깔때기(열린 선) 아래에서 짧은 출구가 'DE' 쪽 얇은 화살촉으로 끝난다. 출구는 깔때기의
        # 일부라 벤트 끝 기호를 따로 만들지 않는다. 얇은 화살촉은 기호 안에서 점선 조각으로 세어 '선과 표식' 체크밸브가 아니다
        tip = prim([(109, 104.8), (111.9, 105.5), (109, 106.2), (109, 104.8)], closed=True, fill=True)
        ext = pdf_run([line((100, 100), (100, 102), (108, 102), (108, 100)), line((104, 102), (104, 105.5), (109, 105.5)), tip])
        self.assertEqual([(n["kind"], n["geometry"]["width"]) for n in ext["nodes"]], [("drain", 11.9)])
        self.assertEqual(ext["relations"], [])

    def test_thin_arrowhead_inside_line_symbol_is_not_check_valve(self):
        # 얇은 화살촉이 선 기호 상자 안에 들면 예전처럼 점선 조각으로 센다(표식으로 세면 '선과 표식' 체크밸브 규칙에 걸린다.
        # APR1400 025쪽 체크밸브 오검출 7개)
        tip = prim([(103, 104.3), (105.9, 105), (103, 105.7), (103, 104.3)], closed=True, fill=True)
        ext = pdf_run([line((100, 100), (110, 110)), line((100, 110), (110, 100)), tip])
        self.assertEqual([n["kind"] for n in ext["nodes"]], [None])

    def test_outward_arrowhead_attaches_only_at_its_tip(self):
        # APR1400 105쪽: 벤트 관이 지붕 빗금 묶음 사이 틈을 지나 화살촉에서 끝난다. 화살촉 밑동은 옆 빗금 묶음 상자에서
        # 2.5pt 안이지만 화살촉 끝은 멀다. 배관은 옆 묶음에 붙지 않고 화살촉 끝 기호에서 끝난다
        ext = pdf_run([rect(100, 200, 140, 240), rect(122.2, 150.8, 150, 154), line((120, 200), (120, 150)),
                       prim([(119.3, 150), (120, 147.1), (120.7, 150), (119.3, 150)], closed=True, fill=True)])
        at = {n["local_id"]: n["geometry"]["y"] for n in ext["nodes"]}
        self.assertEqual(sorted(tuple(sorted(at[e["node_local_id"]] for e in r["endpoints"])) for r in ext["relations"]),
                         [(147.1, 200)])

    def test_arrowhead_tip_on_pipe_middle_is_branch(self):
        # APR1400 033쪽 V1022A 위·128쪽 12인치 모관: 배관이 흐름 화살촉으로 끝나고 그 끝이 다른 배관 중간에 닿으면 분기다.
        # 화살촉 밑동은 그 배관에서 3pt 넘게 떨어져 있다
        ext = pdf_run([rect(100, 90, 140, 130), rect(300, 90, 340, 130), rect(200, 200, 240, 240),
                       line((140, 110), (300, 110)), line((220, 200), (220, 113.1)),
                       prim([(219.2, 113.1), (220, 110), (220.8, 113.1), (219.2, 113.1)], closed=True, fill=True)])
        self.assertEqual([n["kind"] for n in ext["nodes"]].count("tee"), 1)
        self.assertEqual(len(ext["relations"]), 3)
        # 화살촉 너머로 같은 방향의 짧은 토막이 이어지면 배관 중간의 흐름 화살촉이다. 늘이지 않고 토막을 지나 기호에
        # 붙는다(SNP-M-401 스캔: 체크밸브 앞 화살촉 너머 1.7pt 토막)
        ext = pdf_run([rect(260, 330, 300, 360), rect(338.2, 333.1, 373.9, 354.5), line((300, 343.2), (336.5, 343.2)),
                       line((338.2, 343.3), (336.5, 343.3)),
                       prim([(334.2, 342.5), (337.1, 343.3), (334.2, 344.1), (334.2, 342.5)], closed=True, fill=True)])
        at = {n["local_id"]: n["geometry"]["x"] for n in ext["nodes"]}
        self.assertEqual(sorted(tuple(sorted(at[e["node_local_id"]] for e in r["endpoints"])) for r in ext["relations"]),
                         [(260, 338.2)])

    def test_flange_beside_nozzle_stub_of_plate_length(self):
        # APR1400 025쪽 열교환기: 배관이 플랜지(판 둘)를 지나 짧은 토막으로 노즐에 닿는다. 두 노즐 토막은 길이·방향이 같아
        # 판 짝으로도 잡히지만 플랜지 판 가운데에 수직으로 닿는 배관이다. 플랜지를 건너 배관이 열교환기까지 이어진다
        prims = [rect(759.6, 137.8, 781.6, 152.4), rect(600, 120, 620, 170)]
        for y in (141.4, 148.8):
            prims += [line((620, y), (753.2, y)), line((753.2, y - 1.47), (753.2, y + 1.47)),
                      line((755.0, y - 1.47), (755.0, y + 1.47)), line((755.0, y), (759.6, y))]
        ext = pdf_run(prims)
        self.assertNotIn("tee", [n["kind"] for n in ext["nodes"]])
        at = {n["local_id"]: n["geometry"]["x"] for n in ext["nodes"]}
        self.assertEqual(sorted(tuple(sorted(at[e["node_local_id"]] for e in r["endpoints"])) for r in ext["relations"]),
                         [(600, 759.6), (600, 759.6)])

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

    def test_side_by_side_valve_numbers_stay_apart(self):
        # APR1400 097쪽: 이웃한 두 밸브 번호가 낱말 간격 안에 나란히 찍히고, 번호는 'V'·'4103'·'A'로 끊겨 온다
        def pieces(x, parts, top=100.0, size=4.0):
            out = []
            for p in parts:
                out.append(word(p, x, top, size))
                x = out[-1]["x1"]
            return out
        blocks = pdf_vector._text_blocks(pieces(100, ["V", "4103", "A"]) + pieces(116.4, ["V", "4019", "A"]),
                                         pdf_vector.PARAMS)
        self.assertEqual([b["text"] for b in blocks], ["V4103A", "V4019A"])
        stacked = [word("V707", 100, 100, 3.0), word("V717", 100, 104.2, 3.0)]
        self.assertEqual([b["text"] for b in pdf_vector._text_blocks(stacked, pdf_vector.PARAMS)], ["V707", "V717"])
        # 062쪽 V2120: 배관 구경 글자 바로 뒤에 찍힌 밸브 번호
        after_size = [word("⅜\"X¾\"", 100, 100, 4.0), word("V2120", 113.5, 100, 4.0)]
        self.assertEqual([b["text"] for b in pdf_vector._text_blocks(after_size, pdf_vector.PARAMS)],
                         ["⅜\"X¾\"", "V2120"])

    def test_sideways_glyph_column_reads_bottom_up(self):
        # APR1400 025쪽 V1115: 바로 선 글자로 찍혔지만 눕힌 글꼴 모양을 한 자씩 위로 쌓았다(폭 3.1 > 높이 1.73)
        col = [{"text": t, "x0": 602.56, "x1": 605.67, "top": top, "bottom": top + h, "size": h, "upright": True}
               for t, top, h in (("5", 325.41, 1.73), ("1", 327.14, 1.73), ("1", 328.87, 1.73), ("1", 330.59, 1.73),
                                 ("V", 332.32, 2.07))]
        blocks = pdf_vector._text_blocks(col, pdf_vector.PARAMS)
        self.assertEqual([(b["text"], b.get("rotated")) for b in blocks], [("V1115", True)])

    def test_valve_number_replaces_nearer_non_number_label(self):
        # APR1400 008쪽 V2300: 옆 계기 상자의 경보 글자 'IAH'가 밸브 번호보다 가까워 라벨을 먼저 차지한다.
        # 105쪽 V1153은 번호가 소문자 'v1153'으로 찍혀 위치 약어 'LT'에 밀린다
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        for near, number in (("IAH", "V2300"), ("LT", "v1153")):
            ext = pdf_run(bowtie(100, 100) + [line((40, 111), (100, 111)), line((136, 111), (200, 111))],
                          [word(near, 137, 104), word(number, 110, 126)])
            self.assertEqual([n["tag"] for n in ext["nodes"] if n["kind"] == "manual_valve"], [number])

    def test_rotated_valve_number_across_the_pipe_is_not_line_label(self):
        # APR1400 128쪽 V1623: 밸브 옆 돌린 번호를 가로 배관이 가로지른다. 돌린 글자에는 가로 배관이 줄 방향이 아니다
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        number = {"text": "V1623", "x0": 137.0, "x1": 143.0, "top": 102.0, "bottom": 120.0, "size": 6.0,
                  "upright": False, "direction": "btt"}
        ext = pdf_run(bowtie(100, 100) + [line((40, 111), (100, 111)), line((136, 111), (200, 111))], [number])
        self.assertEqual([n["tag"] for n in ext["nodes"] if n["kind"] == "manual_valve"], ["V1623"])

    def test_valve_number_taken_by_farther_valve_returns_to_its_valve(self):
        # APR1400 016쪽 V413: 위치 약어 'LO'가 밸브 라벨을 먼저 차지하자 바로 밑 번호는 11pt 떨어진 다른 밸브가 가져갔다
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        ext = pdf_run(bowtie(100, 100) + bowtie(100, 140) + [line((40, 111), (100, 111)), line((136, 111), (200, 111)),
                                                              line((40, 151), (100, 151)), line((136, 151), (200, 151))],
                      [word("LO", 112, 93.5), word("V413", 106, 123)])
        tags = {n["geometry"]["y"]: n["tag"] for n in ext["nodes"] if n["kind"] == "manual_valve"}
        self.assertEqual(tags, {100: "V413", 140: None})

    def test_valve_number_under_valve_and_touching_part_goes_to_valve(self):
        # APR1400 062쪽 V2130: 밸브 몸통과 옆에 붙인 부품의 아랫변이 같아 밑 번호까지 거리가 같다. 번호 가운데는 밸브 밑이다
        def bowtie(x, y):
            return [prim([(x, y), (x + 18, y + 11), (x, y + 22), (x, y)], closed=True),
                    prim([(x + 36, y), (x + 18, y + 11), (x + 36, y + 22), (x + 36, y)], closed=True)]
        ext = pdf_run(bowtie(100, 100) + [rect(84, 112, 96, 122), line((40, 117), (84, 117)),
                                          line((96, 111), (100, 111)), line((136, 111), (200, 111))],
                      [word("V2130", 95.8, 123.5, 14.8)])
        self.assertEqual([n["tag"] for n in ext["nodes"] if n["kind"] == "manual_valve"], ["V2130"])

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

    def test_white_fill_traced_by_open_strokes_is_equipment(self):
        # APR1400 033·046·097쪽 탱크·용기: 흰 채움 도형 위에 가장자리를 열린 선 넷으로 따로 그었다. 예전에는 그 선이 배관
        # 고리가 되어 장비 노드가 없고, 위·옆에 닿은 두 배관이 고리를 거쳐 서로 이어졌다
        fill = prim([(200, 100), (300, 100), (300, 150), (200, 150), (200, 100)], closed=True, fill=True, white=True,
                    curved=True)
        edges = [line((200, 100), (300, 100)), line((300, 100), (300, 150)), line((300, 150), (200, 150)),
                 line((200, 150), (200, 100))]
        ext = pdf_run([rect(240, 40, 260, 60), rect(360, 115, 380, 135), fill] + edges
                      + [line((250, 60), (250, 100)), line((300, 125), (360, 125))],
                      words=[word("TANK", 240, 120)])
        tank = [n for n in ext["nodes"] if n["geometry"].get("width") == 100]
        self.assertEqual([n["kind"] for n in tank], ["tank"])
        ends = [[e["node_local_id"] for e in r["endpoints"]] for r in ext["relations"]]
        self.assertEqual(len(ends), 2)
        self.assertTrue(all(tank[0]["local_id"] in e for e in ends))
        # 외곽 상자에 바짝 붙여 그린 계기 상자는 장비와 한 기호가 아니다(125쪽 증기발생기 옆 수위 전송기)
        beside = pdf_run([fill] + edges + [rect(300.3, 110, 315, 130)], words=[word("TANK", 240, 120)])
        self.assertEqual(sorted((n["geometry"]["x"], n["geometry"]["width"]) for n in beside["nodes"]),
                         [(200, 100), (300.3, 14.7)])

    def test_point_beside_rounded_equipment_corner_is_not_on_it(self):
        # 둥근 귀퉁이 장비 외곽은 상자 귀퉁이가 비어 있다. 귀퉁이 옆 점은 외곽에 닿지 않는다(033쪽 TK03A 옆 깔때기)
        ring = [(10, 0), (90, 0), (100, 10), (100, 40), (90, 50), (10, 50), (0, 40), (0, 10), (10, 0)]
        sym = pdf_vector_grouping._Sym([{"id": "t", "pts": ring, "bbox": (0, 0, 100, 50), "traced": True, "kind_": "body"}])
        self.assertGreater(pdf_vector_grouping._sym_dist((101, 1), sym), pdf_vector.PARAMS["attach_tol"])
        self.assertEqual(pdf_vector_grouping._sym_dist((50, 25), sym), 0.0)
        self.assertLessEqual(pdf_vector_grouping._sym_dist((101, 25), sym), 1.0)

    def test_pipe_end_bent_back_half_a_turn_is_vent(self):
        # 범례 1.7-1 1/4 ATMOSPHERIC VENT: 배관 끝이 반원으로 돌아 아래를 향한다. 반원이 따로 그은 곡선이거나(025쪽), 배관과 한
        # 경로이고 끝에 짧은 막대(WITH SCREEN, 128쪽)가 있다. 90도로만 꺾여 끝난 배관은 벤트로 단정하지 않는다
        def arc(x0, x1, top, base):
            cx, r = (x0 + x1) / 2, (x1 - x0) / 2
            fine = [(cx - r * math.cos(math.pi * t / 12), base - (base - top) * math.sin(math.pi * t / 12)) for t in range(13)]
            return fine

        def kinds(*parts, pipe=True):
            ext = pdf_run([rect(100, 180, 140, 220)] + ([line((140, 200), (200, 200), (200, 120))] if pipe else []) + list(parts))
            return sorted(str(n["kind"]) for n in ext["nodes"])
        sep = arc(200, 206, 117, 120)
        self.assertIn("vent", kinds(dict(prim([sep[0], sep[6], sep[-1]], curved=True,
                                               ext=[(200, 117), (206, 117), (206, 120), (200, 120)]), fine=[sep])))
        one = [(140, 200), (200, 200)] + sep
        self.assertIn("vent", kinds(dict(prim([(140, 200), (200, 200), (200, 120), sep[6], (206, 120)], curved=True,
                                              ext=one + [(206, 117)]), fine=[one]),
                                    line((205, 120), (207, 120)), pipe=False))
        quarter = [(200 + 4 * math.sin(math.pi * t / 12), 120 - 4 * (1 - math.cos(math.pi * t / 12))) for t in range(7)]
        self.assertNotIn("vent", kinds(dict(prim([quarter[0], quarter[3], quarter[-1]], curved=True,
                                                 ext=[(200, 116), (204, 116), (204, 120), (200, 120)]), fine=[quarter])))

    def test_arc_and_chord_drawn_apart_is_pipe_cap(self):
        # APR1400 046·105·128쪽 배관 끝막음: 곧은 막음선과 반원 곡선을 두 경로로 따로 그었다. 예전에는 배관이 막음선
        # 가운데에 닿아 분기점이 되고 끝막음 노드가 없었다
        chord = line((200, 118.5), (200, 121.5))
        arc = prim([(200, 118.5), (201.5, 120), (200, 121.5)], curved=True,
                   ext=[(200, 118.5), (201.6, 118.5), (201.6, 121.5), (200, 121.5)])
        ext = pdf_run([rect(100, 110, 120, 130), line((120, 120), (200, 120)), chord, arc])
        self.assertEqual(sorted(str(n["kind"]) for n in ext["nodes"]), ["None", "pipe_cap"])
        self.assertEqual([r["kind"] for r in ext["relations"]], ["physical_connection"])

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

    def test_circle_drawn_as_short_lines_is_instrument_circle(self):
        # APR1400 051쪽 PI 원: 곡선 명령 없이 직선 64개로 원을 긋고 'h' 없이 시작점으로 돌아온다. 닫힌 원으로 읽어야
        # 계기 원이 된다. 꼭짓점이 한 원 위에 있지 않은 꺾은선(돌아오는 지그재그)은 원이 아니다
        def path(pts):
            return {"path": [("m", pts[0])] + [("l", p) for p in pts[1:]]}
        ring = [(100 + 5.5 * math.cos(2 * math.pi * k / 64), 100 + 5.5 * math.sin(2 * math.pi * k / 64)) for k in range(65)]
        zigzag = [(100 + 5.5 * math.cos(2 * math.pi * k / 64) * (1 if k % 2 else 0.6),
                   100 + 5.5 * math.sin(2 * math.pi * k / 64) * (1 if k % 2 else 0.6)) for k in range(65)]
        self.assertEqual([(c, cv) for _, c, _, cv in pdf_vector._subpaths(path(ring))], [(True, True)])
        self.assertEqual([(c, cv) for _, c, _, cv in pdf_vector._subpaths(path(zigzag))], [(False, False)])
        drawn = dict(prim([]), subpaths=pdf_vector._subpaths(path(ring)))
        ext = pdf_run([drawn], [word("PI", 97, 97, size=4)])
        self.assertEqual([n["kind"] for n in ext["nodes"]], ["indicator"])
        # 번호 없는 FC는 밸브 고장 위치 표기다(054쪽 빈 번호 원 옆). 원이 그 글자를 받아도 조절계가 아니다
        self.assertEqual(pdf_vector._instrument_kind("FC", 11), (None, None))
        self.assertEqual(pdf_vector._instrument_kind("FC\n101", 11), ("controller", "isa_letters:FC"))

    def test_empty_circle_does_not_take_isa_tag_from_text_outside(self):
        # APR1400 055쪽: 조절 밸브 옆 빈 번호 원이 위쪽 랙 이름 'LP12'를 라벨로 받는다. 원 밖 글자라 계기 태그가 아니다
        outside = pdf_run([circle(100, 100, 5.5)], [word("LP12", 96, 80, size=4)])
        inside = pdf_run([circle(100, 100, 5.5)], [word("LP12", 96, 98, size=4)])
        self.assertEqual([n["tag"] for n in outside["nodes"]], [None])
        self.assertEqual([n["tag"] for n in inside["nodes"]], ["LP-12"])

    def test_instrument_circle_on_line_into_equipment_stays_separate(self):
        # APR1400 051쪽 SAMPLE PUMP 위 HS 원: 원 아래에서 내려온 선이 펌프 상자 안 깊숙이 들어간다. 구동부 축처럼 원을 펌프에
        # 합치지 않는다
        pump = prim([(116, 100), (116, 108), (108, 108), (108, 116), (100, 116), (100, 124), (124, 124), (124, 100),
                     (116, 100)], closed=True)
        ext = pdf_run([pump, circle(112, 70, 5), line((112, 75), (112, 108)), line((124, 110), (200, 110))],
                      [word("HS", 109, 68, size=3)])
        self.assertEqual(sorted(n["kind"] or "-" for n in ext["nodes"] if n["kind"] != "tee"), ["-", "switch"])

    def test_legend_instrument_codes(self):
        cases = {"ZL\n202C": "pilot_light", "ZL": "pilot_light", "PDAH\n031": "alarm", "PAL": "alarm",
                 "AX\n134": "sample_probe", "FG": "sight_glass", "LE\n058": "level_element", "LL": None, "ZAC": "controller",
                 "TW\n311": "temperature_element"}
        for text, kind in cases.items():
            with self.subTest(text=text):
                ext = pdf_run([circle(100, 100, 14)], [word(t, 95, 92 + 7 * i) for i, t in enumerate(text.split("\n"))])
                self.assertEqual([n["kind"] for n in ext["nodes"]], [kind])

    def test_larger_concentric_reducer_matches_dictionary(self):
        # APR1400 012쪽 솔레노이드 밸브 옆 축소관(4.6pt): 사전 견본(3~3.6pt)과 같은 사다리꼴이고 크기만 크다
        def kind(s):
            tr = prim([(200, 100), (200 + s, 100 + s / 4), (200 + s, 100 + 3 * s / 4), (200, 100 + s), (200, 100)], closed=True)
            ext = pdf_run([rect(100, 90, 140, 130), line((140, 100 + s / 2), (200, 100 + s / 2)), tr,
                           line((200 + s, 100 + s / 2), (300, 100 + s / 2)), rect(300, 90, 340, 130)])
            return [n["kind"] for n in ext["nodes"] if n["geometry"]["x"] == 200]
        self.assertEqual(kind(3.36), ["reducer"])
        self.assertEqual(kind(4.65), ["reducer"])
        self.assertEqual(kind(6.5), [None])

    def test_lone_triangle_at_line_end_is_not_a_pipe_cap(self):
        cap = pdf_run([line((100, 100), (200, 100)), rect(200, 97, 204, 103)])
        nozzle = pdf_run([line((100, 100), (200, 100)), prim([(200, 97), (200, 103), (204, 100), (200, 97)], closed=True)])
        self.assertEqual([n["kind"] for n in cap["nodes"]], ["pipe_cap"])
        self.assertEqual([n["kind"] for n in nozzle["nodes"]], [None])

    def test_square_box_or_triangle_piece_at_line_end_is_not_a_pipe_cap(self):
        # 끝막음은 납작한 막대·괄호·반원이다. 배관 끝 네모 상자(S 상자, 범례 쪽 X·* 상자)와 LT 반쪽 칠한 밸브의 흰 반쪽 +
        # 축소관 조각은 끝막음이 아니다(APR1400 143쪽 pipe_cap 표본 40개 중 20개)
        box = pdf_run([line((100, 100), (200, 100)), rect(200, 97, 206, 103)])
        piece = pdf_run([line((100, 100), (200, 100)), prim([(200, 97), (200, 103), (203, 100), (200, 97)], closed=True),
                         prim([(203, 100), (206, 98), (206, 102), (203, 100)], closed=True)])
        self.assertEqual([n["kind"] for n in box["nodes"]], [None])
        self.assertNotIn("pipe_cap", [n["kind"] for n in piece["nodes"]])

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

    def test_five_letter_isa_function_gets_tag(self):
        # 072쪽 'FICKS 031'·'TICKS 3048': 기능 문자 다섯 자도 종류 규칙(6자까지)과 같이 태그로 읽는다
        nodes, _ = self.tags([("circle", ["FICKS", "031"])])
        self.assertEqual((nodes[0]["kind"], nodes[0]["tag"]), ("controller", "FICKS-031"))

    def test_alarm_column_glued_to_loop_number_is_split_off(self):
        # 072쪽 TIS 3043A: 원 옆에 줄마다 쌓은 경보 표기(HHL / HL / LL)의 가운데 줄이 번호와 틈 없이 붙어 '3043AHL' 한 낱말로
        # 온다. 070쪽은 윗줄 'HHL'도 'TISHHL'로 붙는다. 표기의 왼쪽 끝이 위아래 줄 경보 표기의 왼쪽 끝과 같으면 떼어 내고(뗀
        # 표기가 다시 이웃 줄의 근거가 된다), 경보 표기 열은 원 안 글자와 한 줄·한 문단으로 잇지 않는다
        def w(text, x0, top, step=1.9, h=3.3):
            chars = [{"text": c, "x0": x0 + step * i, "x1": x0 + step * (i + 1), "top": top, "bottom": top + h}
                     for i, c in enumerate(text)]
            return {"text": text, "x0": x0, "x1": x0 + step * len(text), "top": top, "bottom": top + h, "chars": chars}
        top, mid = w("TISHHL", 318.6, 307.6), w("3043AHL", 316.4, 311.5)
        top["chars"][3]["x0"] = mid["chars"][5]["x0"] = 326.6
        column = [top, mid, w("LL", 326.9, 314.6)]
        self.assertEqual([x["text"] for x in pdf_vector._split_alarm_tails(column)], ["TIS", "HHL", "3043A", "HL", "LL"])
        self.assertEqual([x["text"] for x in pdf_vector._split_alarm_tails([mid])], ["3043AHL"])  # 열이 없으면 그대로
        ext = pdf_run([circle(110, 110, 10)], [word("TIS", 104, 104, size=4), word("HHL", 114.5, 104.5, size=4),
                                               word("3043A", 102, 110, size=4), word("HL", 114.5, 110, size=4),
                                               word("LL", 114.5, 115.5, size=4), word("PDIS", 104, 121, size=4)])
        self.assertEqual(ext["nodes"][0]["tag"], "TIS-3043A")
        self.assertEqual(sorted(b["text"] for b in pdf_vector._text_blocks(
            [dict(x, upright=True) for x in (word("HHL", 114.5, 104.5, size=4), word("LL", 114.5, 110, size=4),
                                             word("PDIS", 115, 115.5, size=4))], dict(pdf_vector.PARAMS))),
            ["HHL\nLL", "PDIS"])

    def test_bubble_letters_and_number_in_two_paragraphs_join(self):
        # 072쪽 표시 상자: 칸막이 선 위 'PDAH', 아래 '031'. 줄 간격(3.5pt)이 문단 간격 상한(0.5 × 6pt)보다 넓어 문단이 갈린다
        ext = pdf_run([circle(110, 110, 10)], [word("PDAH", 103, 104), word("031", 105, 113.5)])
        bubble = ext["nodes"][0]
        self.assertEqual((bubble["label_text"], bubble["tag"]), ("PDAH\n031", "PDAH-031"))
        self.assertEqual(ext["texts"], [])

    def test_bubble_number_taken_by_outside_neighbour_comes_back(self):
        # 008쪽 표시등 'ZL' / '310A': 번호 문단이 원 바로 오른쪽 아래 밸브 몸통에 먼저 붙는다. 원 안 번호는 원의 것이다
        ext = pdf_run([circle(110, 110, 10), rect(121, 116, 124, 122), line((124, 119), (200, 119))],
                      [word("ZL", 106, 104), word("310A", 105, 113.5)])
        bubble = next(n for n in ext["nodes"] if n["label_text"].startswith("ZL"))
        self.assertEqual(bubble["label_text"], "ZL\n310A")
        self.assertNotIn("310A", [n["label_text"] for n in ext["nodes"] if n is not bubble])

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

    def test_rotated_number_and_position_columns_stay_two_words(self):
        # APR1400 008쪽 V315: 돌린 3pt 글자 두 줄('V315' 옆 'LO')이 2.9pt 간격이다. 한 낱말 'VL3O15'로 섞이면 밸브 번호를 잃는다
        content = b"BT /F1 3.01 Tf 0 1 -1 0 102 150 Tm (V315) Tj ET BT /F1 3.01 Tf 0 1 -1 0 104.9 151 Tm (LO) Tj ET"
        font = b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> "
        words = pdf_vector.load_page(io.BytesIO(make_pdf(content, resources=font)))[3]
        self.assertEqual(sorted((w["text"], w["upright"]) for w in words), [("LO", False), ("V315", False)])

    def test_glued_valve_numbers_split_into_words(self):
        # APR1400 016쪽 'V705V703', 097쪽 'V4319AV4320A': 이웃한 두 밸브의 번호가 틈 없이 찍혀 한 낱말로 온다
        font = b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> "
        for glued, want in ((b"V705V703", ["V705", "V703"]), (b"V4319AV4320A", ["V4319A", "V4320A"]),
                            (b"V1203AB", ["V1203AB"])):
            content = b"BT /F1 3.07 Tf 100 150 Td (" + glued + b") Tj ET"
            words = pdf_vector.load_page(io.BytesIO(make_pdf(content, resources=font)))[3]
            self.assertEqual([w["text"] for w in sorted(words, key=lambda w: w["x0"])], want)
            if len(words) == 2:
                self.assertLessEqual(round(min(w["x1"] for w in words), 3), round(max(w["x0"] for w in words), 3))
        rotated = b"BT /F1 3.07 Tf 0 1 -1 0 102 150 Tm (V707V717) Tj ET"
        words = pdf_vector.load_page(io.BytesIO(make_pdf(rotated, resources=font)))[3]
        self.assertEqual([w["text"] for w in sorted(words, key=lambda w: -w["bottom"])], ["V707", "V717"])

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
