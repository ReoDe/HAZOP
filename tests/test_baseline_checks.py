"""회귀 기준판 검사(scripts/check_snp_baseline.py·check_apr1400.py)의 판정 규칙 시험. 실행: python -m unittest tests.test_baseline_checks

검사가 진짜 후퇴를 놓치거나 진짜 나아짐을 막지 않는지 본다(2026-11-09 U0 검토 지적).
"""

import copy
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_apr1400 as ca  # noqa: E402
import check_snp_baseline as cs  # noqa: E402


def snp_base():
    drawing = {"kinds": {"pump": 1, "tee": 2, "unclassified": 2}, "tags": ["CC-PP01", "CC-PT401"], "pipes": 5,
               "unknowns": 10, "unclassified": 2, "proposed_nodes": 3}
    truth = dict(drawing, tags=["CC-PP01", "CC-PP02", "CC-PT401"], kinds={"pump": 3, "tee": 2}, unclassified=0)
    proj = {"sheets": 1, "linked": 11, "direction_conflicts": 0, "unlinked": {"no_counterpart": 1}, "proposed_nodes": 4}
    return {"drawio": {"S": truth}, "pdf": {"S": drawing}, "project": {"drawio": proj, "pdf": copy.deepcopy(proj)}}


class SnpCompare(unittest.TestCase):
    def check(self, mutate):
        base = snp_base()
        now = copy.deepcopy(base)
        mutate(now)
        return cs.compare(base, now)

    def test_unchanged_passes(self):
        self.assertEqual(self.check(lambda n: None), ([], []))

    def test_unclassified_to_pump_is_better(self):
        def m(n):
            n["pdf"]["S"].update(kinds={"pump": 3, "tee": 2, "unclassified": 0}, unclassified=0)
        bad, better = self.check(m)
        self.assertEqual(bad, [])
        self.assertTrue(better)

    def test_classified_kind_shrinking_fails(self):
        def m(n):
            n["pdf"]["S"]["kinds"] = {"pump": 0, "tee": 3, "unclassified": 2}
        self.assertTrue(self.check(m)[0])

    def test_more_links_is_better(self):
        def m(n):
            n["project"]["pdf"].update(linked=12, unlinked={})
        bad, better = self.check(m)
        self.assertEqual(bad, [])
        self.assertTrue(better)

    def test_tag_in_drawio_is_better_but_unknown_tag_fails(self):
        def good(n):
            n["pdf"]["S"]["tags"] = ["CC-PP01", "CC-PP02", "CC-PT401"]
        self.assertEqual(self.check(good)[0], [])

        def fake(n):
            n["pdf"]["S"]["tags"] = ["CC-PP01", "CC-PT401", "FAKE-999"]
        self.assertTrue(self.check(fake)[0])

    def test_losing_one_of_two_duplicate_tags_fails(self):
        base = snp_base()
        base["pdf"]["S"]["tags"] = ["CC-PP01", "CC-PP01", "CC-PT401"]
        now = copy.deepcopy(base)
        now["pdf"]["S"]["tags"] = ["CC-PP01", "CC-PT401"]
        self.assertTrue(cs.compare(base, now)[0])

    def test_drawio_change_fails(self):
        def m(n):
            n["drawio"]["S"]["pipes"] = 6
        self.assertTrue(self.check(m)[0])


def node(local_id, x, y, w, h, kind=None, tag=None, label=""):
    return {"local_id": local_id, "kind": kind, "tag": tag, "label_text": label, "attributes": {},
            "geometry": {"x": x, "y": y, "width": w, "height": h}}


class AprScore(unittest.TestCase):
    TL = {"bubbles": [("PT", "1", 10, 10), ("FT", "2", 50, 10)],
          "offpage": [("RC:A", "RC", 100, 100), ("RC:B", "RC", 200, 100), ("SI:C", "SI", 300, 100)],
          "tokens": {"PT1", "FT2", "RCA", "RCB", "SIC"}}

    def score(self, nodes):
        return ca.score_page({"nodes": nodes, "summary": {"unknowns": 0}}, self.TL, {"RC", "SI"})

    def test_one_giant_continuation_counts_once(self):
        s = self.score([node("c", 0, 0, 1000, 1000, kind="continuation", label="RC:A")])
        self.assertEqual(s["connectors_detected"], 1)

    def test_continuation_target_must_match_its_label(self):
        s = self.score([node("c", 295, 95, 10, 10, kind="continuation", label="RC:WRONG")])
        self.assertEqual((s["connectors_detected"], s["connector_bad_target"]), (1, 1))

    def test_tag_exact_needs_same_text_at_same_place(self):
        s = self.score([node("a", 5, 5, 10, 10, tag="PT-1"), node("b", 45, 5, 10, 10, tag="PT-1"),
                        node("c", 400, 400, 10, 10, tag="LINE-1B")])
        self.assertEqual((s["tag_exact"], s["tag_not_in_text"]), (1, 1))


class AprRatchet(unittest.TestCase):
    def base(self):
        totals = {"pages": 2, "bubbles": 5, "offpage_labels": 3, "failed_pages": 0, "tag_exact": 4, "paired": 0,
                  "connectors_detected": 0, "tag_not_in_text": 2, "connector_bad_target": 0}
        key = {"D": {"instrument_hits": 3, "connector_hits": 0, "tagged": 3, "tagged_correct": 3,
                     "continuations": 0, "continuations_correct": 0}}
        pages = {"1": {"tag_exact": 2, "connectors_detected": 0, "tag_not_in_text": 2, "connector_bad_target": 0},
                 "2": {"tag_exact": 2, "connectors_detected": 0, "tag_not_in_text": 0, "connector_bad_target": 0}}
        return {"totals": totals, "answer_key": key, "pages": pages}

    def test_same_passes(self):
        self.assertEqual(ca.ratchet(self.base(), self.base()), [])

    def test_page_regression_hidden_by_other_page_fails(self):
        now = self.base()
        now["pages"]["1"]["tag_not_in_text"] = 0
        now["pages"]["2"]["tag_not_in_text"] = 2
        self.assertTrue(ca.ratchet(self.base(), now))

    def test_answer_key_drop_fails(self):
        now = self.base()
        now["answer_key"]["D"]["instrument_hits"] = 2
        self.assertTrue(ca.ratchet(self.base(), now))

    def test_wrong_tags_on_key_page_fail(self):
        now = self.base()
        now["answer_key"]["D"]["tagged"] = 5
        self.assertTrue(ca.ratchet(self.base(), now))

    def test_changed_input_set_fails(self):
        now = self.base()
        now["totals"]["pages"] = 1
        self.assertTrue(ca.ratchet(self.base(), now))


if __name__ == "__main__":
    unittest.main()
