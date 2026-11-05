"""T3 W2 평가 하네스 테스트. 실행: python -m unittest tests.test_adapter"""

import contextlib
import copy
import io
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_adapter  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.extract.adapters import evaluation as ev  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
