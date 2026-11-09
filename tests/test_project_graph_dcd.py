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

    def test_curly_quotes_and_a_spaced_dash_read_as_point_letters(self):
        """9.5.1-1-S4 'SHEET 2 “D”'(굽은 따옴표), 9.2.2-1-S4 'SHEET 3 - X'(띄운 줄표)."""
        got = links(sheet("9.5.1-1-S4", cont("A", "SHEET 2 “D”")), sheet("9.5.1-1-S2", cont("B", 'SHEET 4"D"')))
        self.assertEqual([g[:2] for g in got], [("linked", None)])
        got = links(sheet("9.2.2-1-S4", cont("A", "SHEET 3 - X")), sheet("9.2.2-1-S3", cont("B", 'SHEET 4"X"')))
        self.assertEqual([g[:2] for g in got], [("linked", None)])

    def test_a_code_in_front_of_sheet_means_another_system(self):
        """'FP SHEET 2 “D”'는 'FP\\nSHEET 2'와 같다. FP가 이 그림의 약어라는 문서 근거가 없어 같은 그림으로 잇지 않는다."""
        a = sheet("9.5.1-1-S4", cont("A", "FP SHEET 2 “D”"))
        got = links(a, sheet("9.5.1-1-S2", cont("B", 'SHEET 4"D"')))
        self.assertNotIn("linked", {g[0] for g in got})
        end = project.continuation_key(a, a["nodes"][1])
        self.assertEqual((end["unkeyed"], end["system_ref"]), ("other_system", {"code": "FP", "sheet": 2, "letter": "D"}))

    def test_a_direction_word_in_front_of_sheet_is_not_a_system_code(self):
        a = sheet("9.5.1-1-S4", cont("A", "TO SHEET 2"))
        self.assertIsNone(project._DCD_SHEET.match("TO SHEET 2"))
        self.assertNotEqual(project.continuation_key(a, a["nodes"][1])["unkeyed"], "other_system")

    def test_two_point_letters_on_one_arrow_never_link_to_one_letter_or_none(self):
        """10.4.6-1-S2 'SHEET 1 "C"/"E"': 어느 글자인지 정할 수 없어 사람이 고르게 둔다. 글자 없는 표시나 다른 글자 둘과도
        잇지 않는다(Codex 검토 재현: 글자를 지웠더니 'SHEET 2 "X"/"Y"', 'SHEET 2'와 이어졌다)."""
        two = sheet("10.4.6-1-S2", cont("A", 'SHEET 1 "C"/"E"'))
        for other in ((cont("B", 'SHEET 2"C"'), cont("C", 'SHEET 2"E"')), (cont("B", 'SHEET 2 "X"/"Y"'),),
                      (cont("B", "SHEET 2"),), (cont("B", 'SHEET 2"C"'),)):
            got = links(two, sheet("10.4.6-1-S1", *other))
            self.assertNotIn("linked", {g[0] for g in got}, other)

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


class OtherSystems(unittest.TestCase):
    """다른 계통 표시('CV:RDT / SHEET 5', 'IA\nSHEET 1')는 계통 약어 대응표(계통약어.csv)로 상대 그림을 찾는다.
    양쪽 약어가 모두 확정([문서] 또는 사람 확인)이면 잇고, 하나라도 [추론]이면 후보로만 남긴다."""

    CODES = {"IA": {"figure": "9.3.1-1", "confirmed": True}, "SA": {"figure": "9.3.1-2", "confirmed": True},
             "CV": {"figure": "9.3.4-1", "confirmed": False}, "RC": {"figure": "5.1.2-1", "confirmed": False}}

    def links(self, *graphs, codes=CODES):
        return sorted((l["status"], l["reason"]) for l in project.build("P", list(graphs), (), codes)["sheet_links"])

    def test_confirmed_codes_both_ways_link(self):
        got = self.links(sheet("9.3.1-2-S1", cont("A", 'IA\nSHEET 1"K"')), sheet("9.3.1-1-S1", cont("B", 'SA\nSHEET 1"K"')))
        self.assertEqual(got, [("linked", None)])

    def test_inferred_code_only_makes_candidates(self):
        got = self.links(sheet("5.1.2-1-S1", cont("A", "SHEET 1", to_system="CV")),
                         sheet("9.3.4-1-S1", cont("B", "SHEET 1", to_system="RC")))
        self.assertEqual(got, [("unlinked", "system_candidate"), ("unlinked", "system_candidate")])

    def test_wrong_sheet_or_letter_finds_nothing(self):
        got = self.links(sheet("9.3.1-2-S1", cont("A", 'IA\nSHEET 1"K"')), sheet("9.3.1-1-S1", cont("B", 'SA\nSHEET 1"L"')))
        self.assertEqual({g[1] for g in got}, {"other_system"})

    def test_same_direction_on_both_sides_is_a_conflict(self):
        """Codex 검토 재현: 확정 약어라도 TO·TO면 잇지 않는다."""
        got = self.links(sheet("9.3.1-2-S1", cont("A", 'IA\nSHEET 1"K"', direction="to")),
                         sheet("9.3.1-1-S1", cont("B", 'SA\nSHEET 1"K"', direction="to")))
        self.assertNotIn("linked", {g[0] for g in got})

    def test_different_line_numbers_given_by_people_do_not_pair(self):
        got = self.links(sheet("9.3.1-2-S1", cont("A", 'IA\nSHEET 1"K"', line_no="L-1")),
                         sheet("9.3.1-1-S1", cont("B", 'SA\nSHEET 1"K"', line_no="L-2")))
        self.assertNotIn("linked", {g[0] for g in got})

    def test_duplicate_rows_never_promote_an_inferred_code(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "codes.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("계통약어,그림번호,계통명,출처,근거,사람 확인\n"
                     "CV,9.3.4-1,x,[추론],x,미확인\nCV,9.3.4-1,x,[문서],x,미확인\n"
                     "RC,5.1.2-1,x,[문서],x,미확인\nRC,5.1.1-1,x,[문서],x,미확인\nIA,9.3.1-1,x,[문서],x,미확인\n")
        codes = project.load_system_codes(path)
        self.assertEqual((codes["CV"]["confirmed"], "RC" in codes, codes["IA"]["confirmed"]), (False, False, True))

    def test_a_code_naming_its_own_figure_never_links_a_sheet_to_itself(self):
        got = self.links(sheet("9.3.1-1-S1", cont("A", 'IA\nSHEET 1"K"'), cont("B", 'IA\nSHEET 1"K"')))
        self.assertNotIn("linked", {g[0] for g in got})

    def test_a_table_saved_by_excel_in_cp949_still_loads(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "codes.csv")
        with open(path, "w", encoding="cp949", newline="") as fh:
            fh.write("계통약어,그림번호,계통명,출처,근거,사람 확인\nCV,9.3.4-1,화학체적제어계통,[추론],x,확인\n")
        self.assertEqual(project.load_system_codes(path), {"CV": {"figure": "9.3.4-1", "confirmed": True}})

    def test_a_table_without_the_expected_columns_is_ignored_quietly(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "codes.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("a,b\n1,2\n")
        self.assertEqual(project.load_system_codes(path), {})
        self.assertIsNone(project.load_system_codes(path + ".none"))

    def test_without_the_table_nothing_changes(self):
        got = self.links(sheet("9.3.1-2-S1", cont("A", 'IA\nSHEET 1"K"')), sheet("9.3.1-1-S1", cont("B", 'SA\nSHEET 1"K"')),
                         codes=None)
        self.assertEqual({g[1] for g in got}, {"other_system"})


if __name__ == "__main__":
    unittest.main()
