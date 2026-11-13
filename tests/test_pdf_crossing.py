"""벡터 PDF 엇갈림 끊김(pdf_vector._crossing_gaps): 한쪽 선을 다른 선 앞뒤에서 끊어 그린 엇갈림은 분기가 아니다.

R3 개선 7. 규격: docs/specs/extraction.md '읽기 품질 지표'(연결 (가): 점 없이 엇갈리는 선은 이어지지 않음).
"""

import unittest

from hazop.extract.adapters import pdf_vector as pv


def poly(pid, pts):
    return {"id": pid, "pts": pts}


class CrossingGapTest(unittest.TestCase):
    prm = dict(pv.PARAMS)

    def test_broken_line_across_another_is_one_pipe_not_a_tee(self):
        # 가로관(0~100, y=50)을 세로관이 x=50에서 위아래로 끊긴 채 지나감(끝이 가로관에서 1pt씩 떨어짐)
        polys = [poly("h", [(0, 50), (100, 50)]), poly("up", [(50, 0), (50, 49)]), poly("down", [(50, 51), (50, 100)])]
        tees, chains = pv._build_solid([], polys, [], self.prm)
        self.assertEqual(tees, [])
        self.assertEqual(len(chains), 2)  # 가로관 하나, 끊김을 건너 이어진 세로관 하나
        vertical = next(c for c in chains if c["evidence"] == ["down", "up"])
        self.assertEqual({tuple(p) for p in (vertical["pts"][0], vertical["pts"][-1])}, {(50, 0), (50, 100)})

    def test_t_junction_from_one_side_is_still_a_tee(self):
        polys = [poly("h", [(0, 50), (100, 50)]), poly("up", [(50, 0), (50, 49.5)])]
        tees, _ = pv._build_solid([], polys, [], self.prm)
        self.assertEqual(len(tees), 1)

    def test_offset_ends_are_not_a_crossing(self):
        # 두 끝이 한 줄이 아니면(서로 다른 자리의 T 둘) 엇갈림이 아니다
        polys = [poly("h", [(0, 50), (100, 50)]), poly("up", [(30, 0), (30, 49.5)]), poly("down", [(70, 50.5), (70, 100)])]
        tees, _ = pv._build_solid([], polys, [], self.prm)
        self.assertEqual(len(tees), 2)


if __name__ == "__main__":
    unittest.main()
