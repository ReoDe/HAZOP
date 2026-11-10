"""탐색기 ⑤ 구간 진행 표(hazop.app.related.progress_table)가 구간마다 따로 센 값과 같은지 본다.
실행: python -m unittest tests.test_progress_table
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.app import related  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests import test_study_export as tse  # noqa: E402


def one_node(results, node_id, n):
    """구간 하나만 보고 센 기준값(고치기 전 방식)."""
    cells = [c for c in results["cells"] if c["node_id"] == node_id]
    return related._progress(cells, res.matrix_summary(results).get(node_id, {}), n)


class ProgressTableTest(unittest.TestCase):
    def test_matches_per_node_count(self):
        r, ns, *_ = tse.sample()
        n = len(tse.DEVS)
        table = related.progress_table(r, n)
        ids = [x["node_id"] for x in ns["nodes"]]
        self.assertEqual(set(table), set(ids))
        for nid in ids:
            self.assertEqual(related.node_progress(table, nid, n), one_node(r, nid, n), nid)
        texts = {related.node_progress(table, nid, n)[0] for nid in ids}
        self.assertTrue(any(t.startswith("미") for t in texts), texts)
        self.assertTrue(any("실패" in t for t in texts), texts)

    def test_summary_passed_in_is_used(self):
        r, ns, *_ = tse.sample()
        nid = ns["nodes"][0]["node_id"]
        fake = {nid: {"D01": {"unreviewed": 7}}}
        self.assertTrue(related.progress_table(r, 3, fake)[nid][0].startswith("미7"))

    def test_no_results_and_missing_node(self):
        self.assertEqual(related.progress_table(None, 3), {})
        self.assertEqual(related.node_progress(None, "S1", 3), related.NO_RESULTS)
        self.assertEqual(related.node_progress({}, "S9", 3)[0], "분석 전")


if __name__ == "__main__":
    unittest.main()
