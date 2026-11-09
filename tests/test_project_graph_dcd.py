"""APR1400 DCD식 도면 연결 표시 짝짓기 시험. 실행: python -m unittest tests.test_project_graph_dcd

DCD는 같은 그림의 다른 시트로 가는 화살표에 'SHEET 5"RC"'(시트 번호 + 짝 글자)나 'SHEET 2'만 쓰고, 다른 계통으로
가는 화살표에는 'CV:RDT / SHEET 5'처럼 계통 약어를 붙인다(범례 그림 1.7-1). 도면번호는 '<그림 번호>-S<시트>'로
등록한다(예: 9.3.4-1-S1). 다른 계통 화살표 짝짓기는 계통 약어→그림 번호 대응표가 있어야 해 이 시험 범위 밖이다.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hazop.graph import project  # noqa: E402
from test_project_graph import cont, sheet  # noqa: E402


def links(*graphs):
    return sorted((l["status"], l["reason"], (l["from"] or {}).get("drawing_number"), (l["to"] or {}).get("drawing_number"))
                  for l in project.build("P", list(graphs))["sheet_links"])


class SameFigureSheets(unittest.TestCase):

    def test_sheet_and_point_letter_pair_both_ways(self):
        got = links(sheet("9.3.4-1-S1", cont("A", 'RDT\nSHEET 5"RC"')), sheet("9.3.4-1-S5", cont("B", 'SHEET 1"RC"')))
        self.assertEqual([g[:2] for g in got], [("linked", None)])

    def test_different_point_letters_do_not_pair(self):
        got = links(sheet("9.3.4-1-S1", cont("A", 'SHEET 5"RC"')), sheet("9.3.4-1-S5", cont("B", 'SHEET 1"RD"')))
        self.assertEqual({g[:2] for g in got}, {("unlinked", "no_counterpart")})

    def test_sheet_only_pairs_when_the_return_arrow_is_unique(self):
        got = links(sheet("6.3.2-1-S1", cont("A", "SHEET 2")), sheet("6.3.2-1-S2", cont("B", "SHEET 1")))
        self.assertEqual([g[:2] for g in got], [("linked", None)])

    def test_sheet_only_with_two_return_arrows_is_ambiguous(self):
        got = links(sheet("6.3.2-1-S1", cont("A", "SHEET 2")),
                    sheet("6.3.2-1-S2", cont("B", "SHEET 1"), cont("C", "SHEET 1")))
        self.assertTrue(all(g[0] == "unlinked" for g in got))
        self.assertIn(("unlinked", "ambiguous"), {g[:2] for g in got})

    def test_sheet_only_with_a_lettered_return_arrow_too_is_ambiguous(self):
        """S2에 'SHEET 1'과 'SHEET 1"X"'가 함께 있으면 S1의 'SHEET 2'가 어느 것인지 정하지 않는다(Codex 검토 재현)."""
        got = links(sheet("6.3.2-1-S1", cont("A", "SHEET 2")),
                    sheet("6.3.2-1-S2", cont("B", "SHEET 1"), cont("C", 'SHEET 1"X"')))
        self.assertNotIn("linked", {g[0] for g in got})

    def test_line_no_attribute_wins_over_the_label_letter(self):
        a = sheet("9.3.4-1-S1", cont("A", 'SHEET 5"RC"', line_no="L-99"))
        b = sheet("9.3.4-1-S5", cont("B", 'SHEET 1"RD"', line_no="L-99"))
        self.assertEqual([g[:2] for g in links(a, b)], [("linked", None)])

    def test_end_without_a_key_is_never_a_counterpart(self):
        """'TO 9.3.4-1-S2'(배관 번호 없음)은 missing_key 한 번만 남고 'SHEET 1'과 잇지 않는다(검토 재현: 같은 끝이 두 번 기록)."""
        recs = project.build("P", [sheet("9.3.4-1-S1", cont("A", "TO 9.3.4-1-S2")),
                                   sheet("9.3.4-1-S2", cont("B", "SHEET 1"))])["sheet_links"]
        refs = [project._ref(x) for l in recs for x in (l["from"], l["to"]) if x]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertNotIn("linked", {l["status"] for l in recs})

    def test_bare_system_code_line_is_another_system(self):
        """9.2.7-2 시트 1 'CC\nSHEET 4': 쌍점 없이 쓴 계통 약어."""
        got = links(sheet("9.2.7-2-S1", cont("A", "CC\nSHEET 4")), sheet("9.2.7-2-S4", cont("B", "SHEET 1")))
        self.assertNotIn("linked", {g[0] for g in got})

    def test_legend_style_code_on_a_lettered_reference_is_another_system(self):
        """범례 1.7-1 예 'MS / SHEET 2"A"', 10.4.2-1 'WI / SHEET 2"B"'(opus 검토 재현)."""
        got = links(sheet("10.4.2-1-S1", cont("A", 'WI\nSHEET 2 "B"')), sheet("10.4.2-1-S2", cont("B", 'SHEET 1 "B"')))
        self.assertNotIn("linked", {g[0] for g in got})

    def test_description_starting_with_from_is_still_dcd(self):
        """9.2.7-1 시트 2 'FROM QUADRANT A\nSUPPLY HEADER\nSHEET 1 "C"'."""
        got = links(sheet("9.2.7-1-S2", cont("A", 'FROM QUADRANT A\nSUPPLY HEADER\nSHEET 1 "C"')),
                    sheet("9.2.7-1-S1", cont("B", 'TO QUADRANT A\nSUPPLY HEADER\nSHEET 2 "C"')))
        self.assertEqual([g[:2] for g in got], [("linked", None)])

    def test_equipment_name_above_a_lettered_reference_still_pairs(self):
        got = links(sheet("9.3.4-1-S1", cont("A", 'RDT\nSHEET 5"RC"')), sheet("9.3.4-1-S5", cont("B", 'SHEET 1"RC"')))
        self.assertEqual([g[:2] for g in got], [("linked", None)])

    def test_dash_letter_and_zero_padded_sheets(self):
        """10.4.8-1의 'SHEET 2-A', 도면번호 '-S01'."""
        got = links(sheet("10.4.8-1-S01", cont("A", "SHEET 2-A")), sheet("10.4.8-1-S2", cont("B", "SHEET 01-A")))
        self.assertEqual([g[:2] for g in got], [("linked", None)])

    def test_other_figure_is_not_paired_by_sheet_number(self):
        got = links(sheet("9.3.4-1-S1", cont("A", 'SHEET 2"A"')), sheet("6.3.2-1-S2", cont("B", 'SHEET 1"A"')))
        self.assertTrue(all(g[0] == "unlinked" for g in got))

    def test_other_system_arrow_is_left_for_the_code_table(self):
        got = links(sheet("9.3.4-1-S1", cont("A", "SHEET 5", to_system="RC")),
                    sheet("5.1.2-1-S1", cont("B", "SHEET 1", to_system="CV")))
        self.assertEqual({g[:2] for g in got}, {("unlinked", "other_system")})

    def test_own_sheet_number_is_another_system_not_a_pair(self):
        """10.4.7-1 시트 2의 'PS / SHEET 2' 두 개(계통 약어 PS를 쌍점 없이 따로 씀)를 서로 잇지 않는다."""
        got = links(sheet("10.4.7-1-S2", cont("A", "SHEET 2"), cont("B", "SHEET 2")))
        self.assertEqual({g[:2] for g in got}, {("unlinked", "other_system")})

    def test_description_only_and_code_only_labels_have_their_own_reasons(self):
        """5.1.2-1의 'SPRAY LINE'(설명뿐), 9.1.3-1의 'CS:IRWST RETURN LINE'(시트 없이 계통 약어만)."""
        got = links(sheet("5.1.2-1-S1", cont("A", "SPRAY LINE"), cont("B", "CS:IRWST\nRETURN LINE", to_system="CS")))
        self.assertEqual(sorted(g[1] for g in got), ["description_only", "other_system"])

    def test_drawing_number_without_sheet_suffix_cannot_resolve(self):
        got = links(sheet("9.3.4-1", cont("A", 'SHEET 5"RC"')))
        self.assertEqual({g[:2] for g in got}, {("unlinked", "missing_key")})

    def test_snp_style_labels_are_read_as_before(self):
        got = links(sheet("A", cont("C1", "FROM B\nL-1 FEED")), sheet("B", cont("C1", "TO A\nL-1 FEED")))
        self.assertEqual(got, [("linked", None, "B", "A")])


if __name__ == "__main__":
    unittest.main()
