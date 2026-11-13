"""벡터 PDF 배관 글자(pdf_vector_lines): 구경·배관 번호 글자를 가장 가까운 물리 배관의 속성으로 붙인다.

규격: docs/specs/extraction.md '읽기 품질 지표'(속성: 배관 옆 구경·배관 번호 글자). 쪽 좌표·번호로 가르지 않는다.
"""

import glob
import os
import tempfile
import unittest

from hazop import paths
from hazop.extract.adapters import pdf_vector as pv
from hazop.extract.adapters import pdf_vector_lines as pl

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ParseTest(unittest.TestCase):
    def test_sizes(self):
        for raw, want in (('3/4"', '3/4"'), ('¾"', '3/4"'), ('1½"', '1-1/2"'), ('24"', '24"'),
                          ('36"X24"', '36"X24"'), ('2 1/2"', '2-1/2"'), ('6"x4"', '6"X4"'),
                         ('30.907"', '30.907"')):
            self.assertEqual(pl.parse_label(raw), ("size", want), raw)

    def test_line_numbers(self):
        self.assertEqual(pl.parse_label("RC-L011"), ("line_no", "RC-L011"))
        self.assertEqual(pl.parse_label("FW-L010A"), ("line_no", "FW-L010A"))
        self.assertEqual(pl.parse_label("RC-L001 HOT LEG"), ("line_no", "RC-L001"))

    def test_continuation_label_line_number(self):
        nodes = [{"local_id": "c", "kind": "continuation", "label_text": "TO SNP-M-201\nCV-L001 LETDOWN"}]
        r = {"local_id": "r", "kind": "physical_connection", "line_no": None,
             "endpoints": [{"node_local_id": "c"}, {"node_local_id": "v"}]}
        self.assertEqual(pl.attach_continuation_line_numbers(nodes, [r]), 1)
        self.assertEqual(r["line_no"], "CV-L001")

    def test_not_labels(self):
        for raw in ("V1430", "PT", "SHEET 2", '"A"', "24", "RC-V111", "NO,FL"):
            self.assertIsNone(pl.parse_label(raw), raw)


def rel(i, pts):
    return {"local_id": "r%d" % i, "kind": "physical_connection", "line_no": None, "attributes": {},
            "evidence": {"pdf_path": [list(p) for p in pts]}}


class AttachTest(unittest.TestCase):
    def test_nearest_pipe_gets_label(self):
        rels = [rel(1, [(0, 0), (100, 0)]), rel(2, [(0, 30), (100, 30)])]
        blocks = [{"text": '3/4"', "bbox": [40, 3, 52, 9]}, {"text": "RC-L011", "bbox": [40, 22, 70, 28]},
                  {"text": '2"', "bbox": [40, 200, 46, 206]}]
        used = pl.attach_line_labels(blocks, range(len(blocks)), rels)
        self.assertEqual(rels[0]["attributes"].get("size"), '3/4"')
        self.assertEqual(rels[1]["line_no"], "RC-L011")
        self.assertEqual(used, {0, 1})  # 멀리 떨어진 2"는 붙이지 않는다

    def test_signal_line_is_not_a_pipe(self):
        r = dict(rel(1, [(0, 0), (100, 0)]), kind="signal_connection")
        pl.attach_line_labels([{"text": '2"', "bbox": [40, 2, 46, 8]}], [0], [r])
        self.assertNotIn("size", r["attributes"])


class SnpLineNumberTest(unittest.TestCase):
    def test_snp_relations_carry_printed_line_numbers(self):
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        ex = pv.extract(pdf, page=0, repo_root=tempfile.mkdtemp())
        got = {r["line_no"] for r in ex["relations"] + ex["unresolved_connectors"] if r.get("line_no")}
        self.assertTrue({"RC-L010", "RC-L011"} <= got, got)


if __name__ == "__main__":
    unittest.main()
