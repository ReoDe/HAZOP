"""계기 태그 계통 접두(pdf_vector_labels._assign_tags): 쪽에서 가장 많은 접두가 둘 이상 같은 수면 가장 가까운 글자 태그의 접두.

R3 개선 3. 규격: docs/specs/extraction.md '읽기 품질 지표'(태그·번호: 찍히지 않은 계통 앞머리를 붙인 태그는 같은 태그).
"""

import glob
import os
import tempfile
import unittest

from hazop import paths
from hazop.extract.adapters import pdf_vector as pv
from hazop.extract.adapters import pdf_vector_labels as pl

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def node(i, kind, cat, x, label):
    return {"local_id": "n%d" % i, "source_object_id": "s%d" % i, "kind": kind, "category": cat, "label_text": label,
            "geometry": {"x": x, "y": 0, "width": 20, "height": 20}, "evidence": {}}


class TiedPrefixTest(unittest.TestCase):
    def test_tied_prefix_uses_nearest_tagged_symbol(self):
        nodes = [node(1, "manual_valve", "valve", 0, "MS-V001"), node(2, "manual_valve", "valve", 10, "MS-V002"),
                 node(3, "manual_valve", "valve", 500, "FW-V001"), node(4, "manual_valve", "valve", 510, "FW-V002"),
                 node(5, "transmitter", "instrument", 30, "PT\n501"), node(6, "transmitter", "instrument", 480, "FT\n502")]
        unknowns = []
        pl._assign_tags(nodes, unknowns)
        self.assertEqual(nodes[4]["tag"], "MS-PT501")
        self.assertEqual(nodes[5]["tag"], "FW-FT502")
        self.assertIn("[추론]", nodes[4]["evidence"]["tag_basis"])

    def test_single_majority_prefix_is_unchanged(self):
        nodes = [node(1, "manual_valve", "valve", 0, "RC-V001"), node(2, "manual_valve", "valve", 10, "RC-V002"),
                 node(3, "transmitter", "instrument", 900, "PT\n110")]
        pl._assign_tags(nodes, [])
        self.assertEqual(nodes[2]["tag"], "RC-PT110")


class SnpTwoSystemsTest(unittest.TestCase):
    def test_two_system_page_instruments_get_tags(self):
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-501*", "*.pdf"))[0]
        ex = pv.extract(pdf, page=0, repo_root=tempfile.mkdtemp())
        tags = {n["tag"] for n in ex["nodes"] if n.get("category") == "instrument" and n.get("tag")}
        self.assertTrue({"MS-PT501", "FW-FT503"} <= tags, tags)


if __name__ == "__main__":
    unittest.main()
