"""시트 정체 퍼즈(tests.test_sheet_identity_fuzz)가 e33f2de에서 찾은 결함의 고정 재현 시험. 퍼즈 시드에 기대지 않는 정해진 순서다.

E1 붙박은 in_use 자리가 낡은 채 남아, 번호를 쓰던 파일이 있는데도 앞서 붙박였던 파일이 번호로 돌아오면 그 번호의 주인이 말없이 뒤집힌다.
E2 정착이 붙박은 옛 자리(legacy)의 주인 파일을 고르기로 고르면 자리가 chosen으로 바뀌어 옛 이름 붙박기가 풀린다. 다음 추출에서 그 파일은 임시 이름으로
   옮겨 가고 그 이름을 같은 번호의 다른 파일이 이어받으며, 그 사이 표제란 가드는 옛 이름 대신 임시 이름으로 셈해 옮길 구간을 0개로 알린다.
실행: python -m unittest tests.test_sheet_identity_regress
"""

import unittest
from unittest import mock

from tests.test_sheet_gid_paths import NUMBER, SheetCase, legacy_name
from tests.test_titleblock import BY, P

from hazop.app import project_ctx
from hazop.graph import sources


class SeatRegressTest(SheetCase):
    def owner(self, gid):
        return next((s["material_id"] for s in project_ctx.project_graph(P)["sheets"] if s["graph_id"] == gid), None)

    def test_e1_a_file_that_returns_to_a_number_does_not_take_it_from_the_file_using_it(self):
        a, b = self.add("SNP-M-101", "drawio"), self.add("SNP-M-102", "drawio")
        for mid, number in ((a, "SNP-M-555"), (b, "SNP-M-555"), (a, "SNP-M-101")):
            self.assertTrue(self.confirm(mid, {"drawing_number": number})["ok"], number)
        self.assertEqual(self.owner("graph-SNP-M-555"), b, "시험 전제: a가 떠나 b가 쓰는 번호")
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-555"})["ok"])
        self.assertEqual(self.owner("graph-SNP-M-555"), b, "a가 번호로 돌아왔다고 쓰던 b에게서 말없이 넘어옴")
        self.assertEqual([(c["in_use_material"]) for c in sources.conflicts(P)], [b])

    def legacy_pair(self):
        """이 단위 전 앱: 번호 없는 drawio a(쪽 이름 graph-SNP-M-101)와 같은 번호 101을 확정한 PDF b가 한 이름을 나눠 쓴다. 정착하면 a가 옛 자리 주인이다."""
        with mock.patch("hazop.graph.sources.sheet_name", legacy_name, create=True), \
                mock.patch("hazop.app.data.settle_sheets", lambda *a, **k: None, create=True):
            a = self.add("SNP-M-101", "drawio")
            b = self.register(self.copy_in("SNP-M-101", "pdf", "in-b"), dict(NUMBER))
        self.reextract(a)    # 명시적인 차례가 정착을 부른다
        seat = sources.load_seats(P)[0]["graph-SNP-M-101"]
        self.assertEqual((seat["why"], seat["material_id"]), ("legacy", a), "시험 전제: a가 옛 자리 주인")
        return a, b

    def test_e2_choosing_the_legacy_seat_owner_keeps_its_name_when_it_is_extracted_again(self):
        a, b = self.legacy_pair()
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        self.reextract(a)
        self.assertEqual(self.owner("graph-SNP-M-101"), a, "사람이 고른 a가 다음 추출에서 임시 이름으로 옮겨 가고 b가 그 이름을 이어받음")
        self.assertEqual(self.sheet(a)["graph_id"], "graph-SNP-M-101")

    def test_e2_guard_counts_the_segment_on_the_chosen_legacy_name(self):
        a, _b = self.legacy_pair()
        self.make_nodes(a)
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        dry = self.confirm(a, {"drawing_number": "SNP-M-102"}, dry=True)
        self.assertTrue(dry["ok"], dry)
        self.assertEqual(dry["carries"], {"구간": 1}, "가드가 a의 옛 이름 대신 임시 이름으로 셈해 옮길 구간을 놓침")

    def test_e2_choosing_a_format_after_the_legacy_owner_keeps_its_name(self):
        a, b = self.legacy_pair()
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        sources.choose(P, "graph-SNP-M-101", "pdf_vector", BY)
        self.reextract(a)
        self.assertEqual(self.sheet(a)["graph_id"], "graph-SNP-M-101", "형식을 고르며 고른 파일을 내려놓자 옛 이름 붙박기도 풀림")
        self.assertEqual(self.owner("graph-SNP-M-101"), b)


if __name__ == "__main__":
    unittest.main()
