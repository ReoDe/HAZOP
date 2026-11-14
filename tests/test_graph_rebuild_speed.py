"""그래프 다시 만들기를 빠르게 한 부분이 결과를 바꾸지 않는지. 실행: python -m unittest tests.test_graph_rebuild_speed"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.graph import build, project  # noqa: E402
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


def read_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


@unittest.skipUnless(SAMPLES, "SNP 샘플 없음")
class SheetCacheSameTest(unittest.TestCase):
    """쪽별 캐시를 쓴 프로젝트 그래프가 캐시 없이 처음부터 지은 것과 같은지(한 쪽을 고친 뒤 포함)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-sheetcache-")
        self.root = os.path.join(self.tmp, "graph")
        for path in SAMPLES:
            g = build.build_graph(drawio.extract(path, repo_root=REPO_ROOT))
            self.write(g, g["graph_id"])
        self.pid = project.project_id_of(g)
        project.clear_sheet_cache()

    def tearDown(self):
        project.clear_sheet_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, g, name):
        d = os.path.join(self.root, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(g, fh, ensure_ascii=False, indent=2)

    def fresh(self):
        """캐시 없이: 파일을 새로 읽고 노드를 새로 복사한다."""
        project.clear_sheet_cache()
        pg = project.load(self.pid, self.root)
        project.clear_sheet_cache()
        graphs = [read_json(os.path.join(self.root, n, "graph.json")) for n in sorted(os.listdir(self.root))]
        plain = project.build(self.pid, graphs, (project.load_manual(self.pid) or {}).get("ops") or (),
                              project.load_system_codes(paths.folder("APR1400", project.SYSTEM_CODES_FILE)))
        self.assertEqual(canon(pg), canon(plain))
        return pg

    def test_cached_equals_fresh_after_editing_one_sheet(self):
        first = project.load(self.pid, self.root)            # 캐시를 채운다
        again = project.load(self.pid, self.root)            # 모두 캐시에서
        self.assertEqual(canon(again), canon(first))
        self.assertEqual(canon(again), canon(self.fresh()))
        project.load(self.pid, self.root)                    # 캐시를 다시 채운다

        name = sorted(os.listdir(self.root))[0]
        p = os.path.join(self.root, name, "graph.json")
        g = read_json(p)
        node = next(n for n in g["nodes"] if n.get("tag") and n.get("node_type") == "drawing_object")
        old = node["tag"]
        node["tag"] = old[:-1] + ("X" if old[-1] != "X" else "Y")   # 같은 길이: 파일 크기가 같아도 알아채야 한다
        self.write(g, name)
        warm = project.load(self.pid, self.root)
        ids = {n["entity_id"]: n for n in warm["nodes"]}
        self.assertEqual(ids[project.nid(g["graph_id"], node["entity_id"])]["tag"], node["tag"])
        self.assertEqual(canon(warm), canon(self.fresh()))

    def test_callers_cannot_spoil_the_cache(self):
        pg = project.load(self.pid, self.root)
        want = canon(pg)
        for n in pg["nodes"]:
            n["tag"] = "SPOILED"
        for _key, g, _name in project.pick_graphs(self.pid, self.root).values():
            g["nodes"].clear()
        self.assertEqual(canon(project.load(self.pid, self.root)), want)

    def test_removed_sheet_leaves_project(self):
        project.load(self.pid, self.root)
        name = sorted(os.listdir(self.root))[0]
        shutil.rmtree(os.path.join(self.root, name))
        pg = project.load(self.pid, self.root)
        self.assertNotIn(name, [s["graph_id"] for s in pg["sheets"]])
        self.assertEqual(canon(pg), canon(self.fresh()))


if __name__ == "__main__":
    unittest.main()
