"""도면 읽기 품질 검사(scripts/check_read_quality.py)의 채점 규칙 시험. 규격: docs/specs/extraction.md '읽기 품질 지표'."""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_read_quality as rq  # noqa: E402


def node(i, kind, box, tag=None, **attrs):
    x0, y0, x1, y1 = box
    return {"local_id": "n%d" % i, "kind": kind, "tag": tag, "attributes": attrs, "label_text": "",
            "geometry": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}}


def rel(i, a, b, flow=None, pts=None, **attrs):
    eps = [{"end": "source", "node_local_id": a, "point": None}, {"end": "target", "node_local_id": b, "point": None}]
    if pts:
        eps[0]["point"], eps[1]["point"] = pts[0], pts[-1]
    return {"local_id": "r%d" % i, "kind": "physical_connection", "endpoints": eps,
            "flow_direction": {"from": flow[0], "to": flow[1]} if flow else None,
            "waypoints": [list(p) for p in (pts or [])[1:-1]], "attributes": attrs, "line_no": attrs.get("line_no")}


def sym(i, kind, box, tag=None, **attrs):
    return {"id": "s%03d" % i, "kind": kind, "bbox": list(box), "tag": tag, "attributes": attrs}


def key(symbols, connections=(), continuations=(), lines=(), regions=None):
    return {"drawing": "T-1", "regions": regions or [[0, 0, 1000, 1000]], "symbols": list(symbols),
            "connections": list(connections), "continuations": list(continuations), "lines": list(lines)}


def ex(nodes, relations=()):
    return {"nodes": list(nodes), "relations": list(relations)}


class KindTest(unittest.TestCase):
    def test_right_wrong_and_false_positive(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108)), sym(2, "check_valve", (200, 100, 210, 108))])
        e = ex([node(1, "manual_valve", (99, 99, 111, 109)), node(2, "manual_valve", (201, 100, 209, 108)),
                node(3, "pump", (500, 500, 540, 540)), node(4, "tee", (300, 300, 301, 301)),
                node(5, None, (600, 600, 620, 610))])
        s = rq.score_page(k, e)["kind"]
        self.assertEqual((s["correct"], s["units"], s["false_pos"]), (1, 2, 1))

    def test_classified_node_wins_over_nearer_unclassified(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108))])
        e = ex([node(1, None, (100, 100, 110, 108)), node(2, "manual_valve", (102, 101, 112, 109))])
        s = rq.score_page(k, e)["kind"]
        self.assertEqual((s["correct"], s["false_pos"]), (1, 0))

    def test_far_node_does_not_match(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108))])
        e = ex([node(1, "manual_valve", (130, 100, 140, 108))])
        s = rq.score_page(k, e)["kind"]
        self.assertEqual((s["correct"], s["false_pos"]), (0, 1))

    def test_false_positive_outside_region_is_not_counted(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108))], regions=[[0, 0, 300, 300]])
        e = ex([node(1, "manual_valve", (100, 100, 110, 108)), node(2, "pump", (500, 500, 540, 540))])
        self.assertEqual(rq.score_page(k, e)["kind"]["false_pos"], 0)

    def test_relief_valve_and_psv_are_one_kind(self):
        k = key([sym(1, "relief_valve", (100, 100, 110, 108))])
        e = ex([node(1, "psv", (100, 100, 110, 108))])
        self.assertEqual(rq.score_page(k, e)["kind"]["correct"], 1)

    def test_accuracy_counts_false_positives_in_denominator(self):
        self.assertAlmostEqual(rq.accuracy({"correct": 9, "units": 10, "false_pos": 2}), 9 / 12)
        self.assertIsNone(rq.accuracy({"correct": 0, "units": 0, "false_pos": 0}))


class TagTest(unittest.TestCase):
    def test_tag_rules(self):
        k = key([sym(1, "transmitter", (100, 100, 120, 120), tag="PT 106"),
                 sym(2, "manual_valve", (200, 100, 210, 108), tag="V1430"),
                 sym(3, "manual_valve", (300, 100, 310, 108))])
        e = ex([node(1, "transmitter", (100, 100, 120, 120), tag="PT-106"),
                node(2, "manual_valve", (200, 100, 210, 108), tag="V1431"),
                node(3, "manual_valve", (300, 100, 310, 108), tag="V9"),
                node(4, "pump", (500, 500, 540, 540), tag="PP01")])
        s = rq.score_page(k, e)["tag"]
        # 맞음 1(PT106), 틀림 1(V1431은 놓친 것으로만 셈), 오검출 2(태그 없는 기호에 붙은 V9, 짝 없는 PP01)
        self.assertEqual((s["correct"], s["units"], s["false_pos"]), (1, 2, 2))

    def test_system_prefix_added_by_extractor_is_the_same_tag(self):
        self.assertTrue(rq.same_tag("RC-TE110", "TE 110"))
        self.assertTrue(rq.same_tag("TE-110", "TE 110"))
        self.assertFalse(rq.same_tag("TE110", "RC-TE110"))  # 찍힌 앞머리를 빠뜨리면 틀림
        self.assertFalse(rq.same_tag("RC-TE111", "TE 110"))

    def test_function_letters_without_number_are_not_tag_units(self):
        k = key([sym(1, "indicator", (100, 100, 120, 120), tag="PI")])
        e = ex([node(1, "indicator", (100, 100, 120, 120), tag="PI")])
        s = rq.score_page(k, e)["tag"]
        self.assertEqual((s["correct"], s["units"], s["false_pos"]), (0, 0, 0))


class ConnectionTest(unittest.TestCase):
    def setUp(self):
        self.k = key([sym(1, "manual_valve", (100, 100, 110, 108)), sym(2, "check_valve", (200, 100, 210, 108)),
                      sym(3, "pump", (300, 90, 330, 120))],
                     connections=[{"a": "s001", "b": "s002", "flow": "a_to_b"}, {"a": "s002", "b": "s003", "flow": None}])

    def test_pairs_through_tee_and_false_positive(self):
        e = ex([node(1, "manual_valve", (100, 100, 110, 108)), node(2, "check_valve", (200, 100, 210, 108)),
                node(3, "pump", (300, 90, 330, 120)), node(4, "tee", (150, 104, 151, 105))],
               [rel(1, "n1", "n4"), rel(2, "n4", "n2"), rel(3, "n4", "n3")])
        s = rq.score_page(self.k, e)["connection"]
        # 쌍 s1-s2 맞음, s2-s3 맞음(티를 지남), s1-s3은 정답에 없는 쌍 → 오검출. 흐름 1건은 방향이 없어 틀림
        self.assertEqual(s["detail"]["pairs"], {"correct": 2, "units": 2, "false_pos": 1})
        self.assertEqual(s["detail"]["flows"], {"correct": 0, "units": 1, "false_pos": 0})
        self.assertEqual((s["correct"], s["units"], s["false_pos"]), (2, 3, 1))

    def test_pairs_with_instruments_are_not_units(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108)), sym(2, "indicator", (200, 80, 220, 100)),
                 sym(3, "flow_element", (300, 100, 310, 108))],
                connections=[{"a": "s001", "b": "s002", "flow": None}, {"a": "s001", "b": "s003", "flow": None}])
        e = ex([node(1, "manual_valve", (100, 100, 110, 108)), node(2, "indicator", (200, 80, 220, 100)),
                node(3, "flow_element", (300, 100, 310, 108))],
               [rel(1, "n1", "n2"), rel(2, "n1", "n3")])
        s = rq.score_page(k, e)["connection"]["detail"]["pairs"]
        self.assertEqual(s, {"correct": 1, "units": 1, "false_pos": 0})
        self.assertEqual(len([u for u in rq.key_units(k) if u["item"] == "connection"]), 1)

    def test_flow_direction(self):
        e = ex([node(1, "manual_valve", (100, 100, 110, 108)), node(2, "check_valve", (200, 100, 210, 108)),
                node(4, "tee", (150, 104, 151, 105))],
               [rel(1, "n1", "n4", flow=("n1", "n4")), rel(2, "n2", "n4", flow=("n4", "n2"))])
        s = rq.score_page(self.k, e)["connection"]
        self.assertEqual(s["detail"]["flows"]["correct"], 1)

    def test_reverse_flow_is_wrong(self):
        e = ex([node(1, "manual_valve", (100, 100, 110, 108)), node(2, "check_valve", (200, 100, 210, 108))],
               [rel(1, "n2", "n1", flow=("n2", "n1"))])
        self.assertEqual(rq.score_page(self.k, e)["connection"]["detail"]["flows"]["correct"], 0)

    def test_continuation_target(self):
        k = key([sym(1, "continuation", (100, 100, 130, 110))],
                continuations=[{"symbol": "s001", "label": "CV:RDT / SHEET 5", "target_system": "CV",
                                "target_sheet": "5", "target_drawing": None}])
        right = ex([dict(node(1, "continuation", (100, 100, 130, 110)), label_text="CV:RDT SHEET 5")])
        wrong = ex([dict(node(1, "continuation", (100, 100, 130, 110)), attributes={"to_system": "RC"})])
        self.assertEqual(rq.score_page(k, right)["connection"]["detail"]["continuations"]["correct"], 1)
        self.assertEqual(rq.score_page(k, wrong)["connection"]["detail"]["continuations"]["correct"], 0)

    def test_continuation_drawing_number_in_label(self):
        k = key([sym(1, "continuation", (100, 100, 130, 110))],
                continuations=[{"symbol": "s001", "label": "FROM SNP-M-101", "target_drawing": "SNP-M-101"}])
        right = ex([dict(node(1, "continuation", (100, 100, 130, 110)), label_text="FROM SNP-M-101\nRC-L010")])
        wrong = ex([dict(node(1, "continuation", (100, 100, 130, 110)), label_text="FROM SNP-M-102")])
        self.assertEqual(rq.score_page(k, right)["connection"]["detail"]["continuations"]["correct"], 1)
        self.assertEqual(rq.score_page(k, wrong)["connection"]["detail"]["continuations"]["correct"], 0)


class AttributeTest(unittest.TestCase):
    def test_symbol_and_line_attributes(self):
        k = key([sym(1, "motor_operated_valve", (100, 100, 110, 108), normal_position="NO", fail_position="FL"),
                 sym(2, "manual_valve", (200, 100, 210, 108)), sym(3, "manual_valve", (300, 100, 310, 108))],
                lines=[{"id": "l001", "at": [150, 104], "size": "3/4\""}, {"id": "l002", "at": [250, 104], "size": "2\""}])
        e = ex([node(1, "motor_operated_valve", (100, 100, 110, 108), normal_position="NO"),
                node(2, "manual_valve", (200, 100, 210, 108), normal_position="LC"),
                node(3, "manual_valve", (300, 100, 310, 108))],
               [rel(1, "n1", "n2", pts=[(110, 104), (200, 104)], size="3/4"),
                rel(2, "n2", "n3", pts=[(210, 104), (300, 104)], size="3")])
        s = rq.score_page(k, e)["attribute"]
        # 맞음: NO, 구경 3/4. 놓침: FL, 2". 오검출: 정답에 없는 LC
        self.assertEqual((s["correct"], s["units"], s["false_pos"]), (2, 4, 1))


class SizeNormTest(unittest.TestCase):
    def test_fraction_spellings_match(self):
        self.assertEqual(rq.norm_size('¾"'), rq.norm_size('3/4"'))
        self.assertEqual(rq.norm_size('1½"'), rq.norm_size('1-1/2"'))
        self.assertEqual(rq.norm_size('1 1/2"'), rq.norm_size('1-1/2"'))
        self.assertNotEqual(rq.norm_size('11/2"'), rq.norm_size('1-1/2"'))
        self.assertNotEqual(rq.norm_size('36"X24"'), rq.norm_size('36"'))


class AiCandidateTest(unittest.TestCase):
    def test_first_candidate_replaces_script_value(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108)), sym(2, "check_valve", (200, 100, 210, 108))])
        e = ex([node(1, None, (100, 100, 110, 108)), node(2, "check_valve", (200, 100, 210, 108))])
        cands = {"candidates": [
            {"node_local_id": "n1", "field": "kind", "values": ["manual_valve", "check_valve"]},
            {"node_local_id": "n2", "field": "kind", "values": ["globe_valve_wrong", "check_valve"]}]}
        merged = rq.apply_candidates(e, cands)
        self.assertEqual(rq.score_page(k, e)["kind"]["correct"], 1)
        self.assertEqual(rq.score_page(k, merged)["kind"]["correct"], 1)  # 하나 고치고 하나 망침
        self.assertIsNone(e["nodes"][0]["kind"])  # 원본 추출은 바꾸지 않는다

    def test_new_symbol_and_connection_candidates(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108)), sym(2, "check_valve", (200, 100, 210, 108))],
                connections=[{"a": "s001", "b": "s002", "flow": None}])
        e = ex([node(1, "manual_valve", (100, 100, 110, 108))])
        cands = {"candidates": [
            {"new_id": "ai-1", "bbox": [200, 100, 210, 108], "field": "kind", "values": ["check_valve"]},
            {"field": "connection", "a": "n1", "b": "ai-1", "values": ["connected"]}]}
        s = rq.score_page(k, rq.apply_candidates(e, cands))
        self.assertEqual(s["kind"]["correct"], 2)
        self.assertEqual(s["connection"]["detail"]["pairs"]["correct"], 1)


class AiRunTest(unittest.TestCase):
    """--ai-run 경로: AI 검토 후보를 '스크립트 + AI 후보' 값으로 센다(가짜 클라이언트)."""

    def test_ai_candidates_raise_second_value_only(self):
        k = key([sym(1, "manual_valve", (100, 100, 110, 108)), sym(2, "continuation", (300, 100, 330, 110))],
                continuations=[{"symbol": "s002", "label": "CV:RDT", "target_system": "CV"}])
        e = ex([dict(node(1, None, (100, 100, 110, 108)), source_object_id="p1"),
                dict(node(2, "continuation", (300, 100, 330, 110)), source_object_id="p2")])
        e["drawing"] = {"drawing_number": "T-1"}

        class Stub:
            def analyze(self, request):
                items = __import__("json").loads(request["context"])["items"]
                ans = [{"item_id": i["item_id"], "field": i["ask"][0],
                        "values": ["manual_valve" if i["ask"][0] == "kind" else "CV"], "confidence": 0.9, "reason": "x"}
                       for i in items]
                return {"status": "completed", "error_kind": None, "output": {"answers": ans}}

        cands, stats = rq.ai_candidates(e, Stub(), cap=3)
        self.assertEqual(stats["calls"], 1)
        before, after = rq.score_page(k, e), rq.score_page(k, rq.apply_candidates(e, cands))
        self.assertEqual((before["kind"]["correct"], after["kind"]["correct"]), (1, 2))
        self.assertEqual(after["connection"]["detail"]["continuations"]["correct"], 1)
        self.assertIsNone(e["nodes"][0]["kind"])  # 원본 추출은 그대로


class BaselineTest(unittest.TestCase):
    def page(self, c, u, f):
        return {it: {"correct": c, "units": u, "false_pos": f} for it in rq.ITEMS}

    def test_ratchet(self):
        base = {"pages": {"a": self.page(5, 10, 1)}}
        self.assertEqual(rq.ratchet(base, {"pages": {"a": self.page(5, 10, 1)}}), [])
        self.assertEqual(rq.ratchet(base, {"pages": {"a": self.page(6, 10, 0)}}), [])
        self.assertTrue(rq.ratchet(base, {"pages": {"a": self.page(4, 10, 1)}}))
        self.assertTrue(rq.ratchet(base, {"pages": {"a": self.page(5, 10, 2)}}))
        self.assertTrue(rq.ratchet(base, {"pages": {"a": self.page(5, 11, 1)}}))  # 정답지가 바뀌면 기준값도
        self.assertTrue(rq.ratchet(base, {"pages": {}}))


class AlignTest(unittest.TestCase):
    def test_uniform_scale_fit(self):
        pts = [(10, 20), (300, 50), (120, 400), (700, 650)]
        pairs = [(p, (0.7188 * p[0] + 0.4, 0.7188 * p[1] + 0.7)) for p in pts] + [((50, 50), (999, 999))]
        s, tx, ty, used = rq.fit_scale(pairs)
        self.assertAlmostEqual(s, 0.7188, places=4)
        self.assertAlmostEqual(tx, 0.4, places=3)
        self.assertEqual(used, 4)  # 어긋난 짝 하나는 뺀다


class SampleTest(unittest.TestCase):
    def test_units_and_sampling_are_deterministic(self):
        k = key([sym(i, "manual_valve", (10 * i, 10, 10 * i + 8, 18), tag="V%d" % i, normal_position="LO")
                 for i in range(1, 16)],
                connections=[{"a": "s%03d" % i, "b": "s%03d" % (i + 1), "flow": None} for i in range(1, 15)])
        units = rq.key_units(k)
        self.assertEqual(len([u for u in units if u["item"] == "kind"]), 15)
        self.assertEqual(len([u for u in units if u["item"] == "connection"]), 14)
        a = rq.sample_units(units, 20, seed=1)
        self.assertEqual(len(a), 20)
        self.assertEqual(a, rq.sample_units(units, 20, seed=1))
        self.assertEqual(len(rq.sample_units(units[:5], 20, seed=1)), 5)


class CompareKeysTest(unittest.TestCase):
    def test_agreement_and_disputes(self):
        a = key([sym(1, "manual_valve", (100, 100, 110, 108), tag="V1", normal_position="LO"),
                 sym(2, "check_valve", (200, 100, 210, 108)), sym(3, "pump", (300, 90, 330, 120), tag="PP01")],
                connections=[{"a": "s001", "b": "s002", "flow": "a_to_b"}, {"a": "s002", "b": "s003", "flow": None}],
                lines=[{"id": "l001", "at": [150, 104], "size": "2\""}])
        b = key([sym(7, "manual_valve", (101, 100, 111, 108), tag="V1", normal_position="LC"),
                 sym(8, "globe_wrong", (201, 100, 211, 108)), sym(9, "tank", (600, 600, 640, 640))],
                connections=[{"a": "s007", "b": "s008", "flow": "a_to_b"}],
                lines=[{"id": "l001", "at": [152, 104], "size": "2"}])
        r = rq.compare_keys(a, b)
        self.assertEqual(r["agree"]["symbol"], 2)          # 1↔7, 2↔8
        self.assertEqual(r["disagree"]["symbol"], 2)       # A만 pump, B만 tank
        self.assertEqual((r["agree"]["kind"], r["disagree"]["kind"]), (1, 1))
        self.assertEqual((r["agree"]["tag"], r["disagree"]["tag"]), (1, 0))   # PP01은 짝 없는 기호라 symbol에서 셈
        self.assertEqual((r["agree"]["attribute"], r["disagree"]["attribute"]), (1, 1))  # LO≠LC, 구경 2"=2
        self.assertEqual((r["agree"]["connection"], r["disagree"]["connection"]), (2, 1))  # 쌍 1, 흐름 1 같음 / s2-s3
        kinds = {d["item"] for d in r["disputes"]}
        self.assertEqual(kinds, {"symbol", "kind", "attribute", "connection"})


class AnswerKeyFileTest(unittest.TestCase):
    """저장소의 APR1400 정답지가 채점기가 읽는 꼴을 지키는가."""

    def test_answer_keys_are_well_formed(self):
        from hazop.extract import rules
        kinds = set(rules.KIND_CATEGORY) | {"unlisted"}
        keys = rq.load_keys()
        self.assertGreaterEqual(len(keys), 10)
        for name, k in keys:
            with self.subTest(name):
                self.assertEqual(name, "apr1400-%03d" % k["seq"])
                ids = [s["id"] for s in k["symbols"]]
                self.assertEqual(len(ids), len(set(ids)))
                for s in k["symbols"]:
                    self.assertIn(s["kind"], kinds, s["id"])
                    x0, y0, x1, y1 = s["bbox"]
                    self.assertTrue(x0 <= x1 and y0 <= y1, s["id"])
                    self.assertTrue(rq.in_regions(rq._center(s["bbox"]), k["regions"]), "영역 밖 기호 %s" % s["id"])
                for c in k["connections"]:
                    self.assertIn(c["a"], ids)
                    self.assertIn(c["b"], ids)
                    self.assertNotEqual(c["a"], c["b"])
                    self.assertIn(c.get("flow"), (None, "a_to_b", "b_to_a"))
                pairs = [frozenset((c["a"], c["b"])) for c in k["connections"]]
                self.assertEqual(len(pairs), len(set(pairs)), "같은 쌍을 두 번 적음")
                for c in k["continuations"]:
                    self.assertIn(c["symbol"], ids)
                for s in k["symbols"]:
                    for f, v in (s.get("attributes") or {}).items():
                        self.assertIn(f, rq.SYMBOL_FIELDS, s["id"])
                    # 위치 속성의 출처(규격 '위치 속성의 출처'): 글자·검게 칠한 몸통·둘 다. 몸통만이면 값은 NC다
                    for f, src in (s.get("position_sources") or {}).items():
                        self.assertIn(src, ("text", "shape", "text+shape"), s["id"])
                        self.assertIn(f, (s.get("attributes") or {}), s["id"])
                        if src == "shape":
                            self.assertEqual(s["attributes"][f], "NC", s["id"])
                for c in k.get("position_conflicts", []):
                    self.assertIn(c["symbol"], ids)
                    self.assertEqual(c.get("shape"), "NC")
                    self.assertIn(c.get("text"), ("NO", "LO", "LT"))


if __name__ == "__main__":
    unittest.main()
