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
        return ca.score_page({"nodes": nodes, "summary": {"unknowns": 0}}, self.TL)

    def test_one_giant_continuation_counts_once(self):
        s = self.score([node("c", 0, 0, 1000, 1000, kind="continuation", label="RC:A")])
        self.assertEqual(s["connectors_detected"], 1)

    def test_continuation_target_must_match_its_label(self):
        s = self.score([node("c", 295, 95, 10, 10, kind="continuation", label="RC:WRONG")])
        self.assertEqual((s["connectors_detected"], s["connector_bad_target"]), (1, 1))

    def stacked(self, up_system, down_system):
        """글자 SI:C(300,100)가 위 화살표(y 88~94)와 아래 화살표(y 106~112)에 거의 똑같이 가깝다(9.3.4-1 시트 6).
        위 화살표 자기 글자는 이 쪽에 없다(계통 약어를 생략한 표시)."""
        up = dict(node("u", 280, 88, 40, 6, kind="continuation"), attributes={"to_system": up_system} if up_system else {})
        down = dict(node("d", 280, 106, 40, 6, kind="continuation"), attributes={"to_system": down_system})
        return self.score([up, down])

    def test_stacked_arrows_pair_with_the_arrow_below_the_label(self):
        s = self.stacked(None, "SI")
        self.assertEqual((s["connectors_detected"], s["connector_bad_target"]), (1, 0))

    def test_borrowing_the_neighbours_system_is_a_wrong_target(self):
        """위 화살표가 아래 화살표의 글자 SI:C에서 계통을 가져오면 짝 없는 계통으로 틀린 대상(opus 검토 재현)."""
        s = self.stacked("SI", "SI")
        self.assertEqual((s["connectors_detected"], s["connector_bad_target"]), (1, 1))

    def test_swapped_systems_on_stacked_arrows_are_wrong_targets(self):
        """짝은 위치로만 정하므로 이웃 화살표의 계통이 뒤바뀌면 둘 다 틀린 대상으로 센다(Codex 검토 재현)."""
        s = self.stacked("SI", "RC")
        self.assertEqual((s["connectors_detected"], s["connector_bad_target"]), (1, 2))

    def test_label_glued_to_pipe_size_is_still_a_label(self):
        """9.2.1-1의 '4"CV:IRWST'(배관 크기와 붙어 한 낱말)."""
        self.assertEqual([ca.OFFPAGE_RE.match(t) and ca.OFFPAGE_RE.match(t).group(1)
                          for t in ('4"CV:IRWST', "CV:RDT", '3"X4"', "PDIS")], ["CV", "CV", None, None])

    def test_unread_system_is_a_miss_not_a_wrong_target(self):
        s = self.score([node("c", 295, 95, 10, 10, kind="continuation", label="SHEET 4")])
        self.assertEqual((s["connectors_detected"], s["connector_bad_target"]), (1, 0))

    def test_arrow_without_a_system_is_not_a_wrong_target(self):
        s = self.score([node("m", 500, 500, 30, 6, kind="continuation", label="MAKE-UP\nDEMIN. WATER")])
        self.assertEqual(s["connector_bad_target"], 0)

    def test_tag_exact_needs_same_text_at_same_place(self):
        s = self.score([node("a", 5, 5, 10, 10, tag="PT-1"), node("b", 45, 5, 10, 10, tag="PT-1"),
                        node("c", 400, 400, 10, 10, tag="LINE-1B")])
        self.assertEqual((s["tag_exact"], s["tag_not_in_text"]), (1, 1))


class AprLabelWords(unittest.TestCase):
    def test_char_by_char_label_is_joined_but_words_stay_apart(self):
        """9.3.2-1 시트 1: 'RC:RCS HOT'를 글자마다 따로 놓아 pdfplumber가 'R'·'C'·':'·'RC'·'S'로 쪼갠다."""
        def w(t, x0, x1, top=125.5):
            return {"text": t, "x0": x0, "x1": x1, "top": top, "bottom": top + 3}
        got = ca.join_fragments([w("R", 265.0, 267.3), w("C", 267.3, 269.6), w(":", 269.6, 270.5), w("RC", 270.5, 275.2),
                                 w("S", 275.2, 277.3), w("H", 278.2, 280.6), w("(S", 265.0, 268.2, top=129.3)])
        self.assertEqual(sorted(x["text"] for x in got), ["(S", "H", "RC:RCS"])


class AprTagInText(unittest.TestCase):
    """계기 글자로 만든 태그는 노드 상자 안 위아래 두 줄과 같아야 한다(접두 조각·번호 끝 글자 누락도 틀림)."""
    # 상자 (0,0)-(10,10) 안: 윗줄 'PDIS', 아랫줄 '3014A'. 상자 밖(40,40): 'V5402'
    CHARS = [(c, 1.5 + k, 3, 2, 1 + k, 2 + k) for k, c in enumerate("PDIS")] + \
        [(c, 1.5 + k, 7, 6, 1 + k, 2 + k) for k, c in enumerate("3014A")] + \
        [(c, 40.5 + k, 40, 39, 40 + k, 41 + k) for k, c in enumerate("V5402")] + \
        [(c, -2.5 + k, 3, 2, -3 + k, -2 + k) for k, c in enumerate("LL")]  # 상자에 걸친 옆 경보 글자
    TL = {"chars": CHARS, "tokens": {"PDIS", "3014A", "V5402"}}

    def isa(self, tag, x=0, w=10):
        return dict(node("n", x, 0 if x == 0 else 38, w, 10, tag=tag), evidence={"tag_basis": "isa_label"})

    def test_exact_two_lines_pass(self):
        self.assertTrue(ca.tag_in_text(self.isa("PDIS-3014A"), self.TL))

    def test_dropped_letters_or_suffix_fail(self):
        for tag in ("PD-3014A", "PDIS-3014", "VP-PDIS3014A"):
            self.assertFalse(ca.tag_in_text(self.isa(tag), self.TL), tag)

    def test_number_outside_the_symbol_fails(self):
        self.assertFalse(ca.tag_in_text(self.isa("V-5402", x=45, w=3), self.TL))

    def test_label_tag_uses_page_words(self):
        n = dict(node("a", 40, 38, 30, 6, tag="V5402"), evidence={"tag_basis": "label_tag_token"})
        self.assertTrue(ca.tag_in_text(n, self.TL))


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
