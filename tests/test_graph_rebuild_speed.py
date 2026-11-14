"""그래프 다시 만들기를 빠르게 한 부분이 결과를 바꾸지 않는지. 실행: python -m unittest tests.test_graph_rebuild_speed"""

import glob
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.graph.query import MODES, GraphQuery  # noqa: E402

SAMPLES = sorted(glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio")))


def pairwise_expectations(q):
    """고치기 전 path_expectations의 정의 그대로: 쌍마다 path_signature(목표에서 멈추는 BFS)."""
    everyone = sorted(q.nodes)
    cases = {}
    for i, a in enumerate(everyone):
        for j, b in enumerate(everyone):
            if a == b:
                continue
            has_seg = "pipe_segment" in (q.nodes[a]["node_type"], q.nodes[b]["node_type"])
            if has_seg and (i * 31 + j) % q.SEGMENT_SAMPLE_STEP:
                continue
            for mode in MODES:
                cases["%s|%s|%s" % (a, b, mode)] = q.path_signature(a, b, mode)
    return cases


@unittest.skipUnless(SAMPLES, "SNP 샘플 없음")
class PathExpectationsSameTest(unittest.TestCase):

    def test_same_as_pairwise_bfs_on_every_sample(self):
        flows = 0
        for path in SAMPLES:
            g = build.build_graph(drawio.extract(path, repo_root=REPO_ROOT))
            q = GraphQuery(g)
            want = pairwise_expectations(q)
            got = q.path_expectations()["cases"]
            self.assertEqual(sorted(got), sorted(want), path)
            for k in want:
                self.assertEqual(got[k], want[k], (path, k))
            flows += sum(1 for v in want.values() if v[1])
        self.assertGreater(flows, 0, "확인된 흐름 경로가 하나는 있어야 방향 경로까지 견준 것이다")


if __name__ == "__main__":
    unittest.main()
