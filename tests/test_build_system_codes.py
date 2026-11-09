import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import build_system_codes as bsc  # noqa: E402

ROWS = [{"그림번호": "5.1.1-1", "시트": "1", "계통명": "원자로냉각재계통(RCS)"},
        {"그림번호": "5.1.2-1", "시트": "1", "계통명": "원자로냉각재계통(RCS)"},
        {"그림번호": "9.3.1-1", "시트": "1", "계통명": "계기용공기계통(IA)"}]


class BuildSystemCodes(unittest.TestCase):

    def test_an_acronym_shared_by_several_figures_is_not_documentary(self):
        table = bsc.build(ROWS, [("9.3.1-1", 1, "RCS", 1), ("9.3.1-1", 1, "IA", 1)], {})
        self.assertEqual([(t["계통약어"], t["출처"]) for t in table], [("IA", "[문서]")])

    def test_a_confirmed_row_survives_a_rebuild_even_with_extra_columns(self):
        old = {"CV": {"계통약어": "CV", "그림번호": "9.3.4-1", "계통명": "x", "출처": "[추론]", "근거": "x",
                      "사람 확인": "확인", "메모": "현장 확인"}}
        table = bsc.build(ROWS, [], old)
        self.assertEqual(table, [{k: old["CV"][k] for k in bsc.FIELDS}])


if __name__ == "__main__":
    unittest.main()
