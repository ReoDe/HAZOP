"""벡터 PDF 흐름 방향(pdf_vector): 선 위·끝의 채운 화살촉 삼각형과 분기점·2포트 기호의 흐름 보존으로 방향을 정한다.

규격: docs/specs/extraction.md '읽기 품질 지표'(연결 (나) 흐름 방향). 특정 쪽 좌표·번호로 가르지 않는다.
"""

import glob
import os
import unittest

from hazop import paths
from hazop.extract.adapters import pdf_vector as pv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tri(tip, base_mid, half=2.5):
    """tip 쪽을 가리키는 채운 삼각형 marker(닫힌 4점)."""
    dx, dy = tip[0] - base_mid[0], tip[1] - base_mid[1]
    L = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / L * half, dx / L * half
    a, b = (base_mid[0] + nx, base_mid[1] + ny), (base_mid[0] - nx, base_mid[1] - ny)
    pts = [tip, a, b, tip]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"id": "m", "pts": pts, "bbox": [min(xs), min(ys), max(xs), max(ys)]}


class ChainFlowTest(unittest.TestCase):
    prm = dict(pv.PARAMS)

    def test_arrow_at_end_points_along_chain(self):
        ch = {"pts": [(0, 0), (100, 0)]}
        self.assertEqual(pv._chain_flow(ch, [tri((100, 0), (94, 0))], self.prm), 1)
        self.assertEqual(pv._chain_flow(ch, [tri((0, 0), (6, 0))], self.prm), -1)

    def test_arrow_in_middle_of_bent_chain(self):
        ch = {"pts": [(0, 0), (50, 0), (50, 80)]}
        self.assertEqual(pv._chain_flow(ch, [tri((50, 40), (50, 34))], self.prm), 1)

    def test_no_or_conflicting_or_off_line_arrows(self):
        ch = {"pts": [(0, 0), (100, 0)]}
        self.assertIsNone(pv._chain_flow(ch, [], self.prm))
        self.assertIsNone(pv._chain_flow(ch, [tri((100, 0), (94, 0)), tri((0, 0), (6, 0))], self.prm))
        self.assertIsNone(pv._chain_flow(ch, [tri((50, 20), (44, 20))], self.prm))  # 선에서 떨어진 화살촉
        self.assertIsNone(pv._chain_flow(ch, [tri((50, 6), (50, 0))], self.prm))   # 선과 직각인 화살촉

    def test_non_triangle_marker_is_ignored(self):
        diamond = {"id": "d", "pts": [(48, 0), (50, -2), (52, 0), (50, 2), (48, 0)], "bbox": [48, -2, 52, 2]}
        self.assertIsNone(pv._chain_flow({"pts": [(0, 0), (100, 0)]}, [diamond], self.prm))


def rel(i, a, b, flow=None):
    return {"local_id": "r%d" % i, "kind": "physical_connection",
            "endpoints": [{"end": "source", "node_local_id": a}, {"end": "target", "node_local_id": b}],
            "flow_direction": {"from": a, "to": b} if flow == "+" else ({"from": b, "to": a} if flow == "-" else None)}


class PropagateTest(unittest.TestCase):
    def test_through_two_port_valve_and_tee(self):
        nodes = {"v": "manual_valve", "t": "tee", "p": "pump", "a": "tank", "b": "tank"}
        # a → v → t → (p, b): a-v 방향만 앎. 밸브를 지나 v-t, 분기점은 나가는 쪽 하나만 모름이 아니므로 그대로
        rels = [rel(1, "a", "v", "+"), rel(2, "v", "t"), rel(3, "t", "p"), rel(4, "t", "b", "+")]
        n = pv._propagate_flows(rels, nodes)
        self.assertEqual(rels[1]["flow_direction"]["from"], "v")
        self.assertEqual(rels[2]["flow_direction"], None)  # 분기점: 들어옴 1·나감 1·모름 1이면 정하지 않는다
        self.assertEqual(n, 1)

    def test_tee_with_all_known_out_gets_inlet(self):
        nodes = {"t": "tee", "x": "tank", "y": "tank", "z": "tank"}
        rels = [rel(1, "t", "x", "+"), rel(2, "t", "y", "+"), rel(3, "z", "t")]
        pv._propagate_flows(rels, nodes)
        self.assertEqual((rels[2]["flow_direction"]["from"], rels[2]["flow_direction"]["to"]), ("z", "t"))

    def test_pump_passes_flow_suction_to_discharge(self):
        nodes = {"a": "tank", "p": "pump", "b": "tank"}
        rels = [rel(1, "a", "p"), rel(2, "p", "b", "+")]
        pv._propagate_flows(rels, nodes)
        self.assertEqual(rels[0]["flow_direction"]["to"], "p")

    def test_equipment_is_not_propagated_through(self):
        nodes = {"a": "tank", "k": "tank", "b": "tank"}
        rels = [rel(1, "a", "k", "+"), rel(2, "k", "b")]
        self.assertEqual(pv._propagate_flows(rels, nodes), 0)
        self.assertIsNone(rels[1]["flow_direction"])


class SnpFlowTest(unittest.TestCase):
    """SNP 가상 도면은 drawio에서 그린 화살촉이 PDF에 그대로 있다. 추출이 방향을 하나 이상 정하는지."""

    def test_snp_extraction_has_flow_directions(self):
        import tempfile
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        ex = pv.extract(pdf, page=0, repo_root=tempfile.mkdtemp())
        flows = [r for r in ex["relations"] if r.get("flow_direction")]
        self.assertGreaterEqual(len(flows), 5)
        for r in flows:
            self.assertIn(r["flow_direction"]["basis"], ("pdf_arrowhead", "flow_continuity"))
        unknown = {u["target"] for u in ex["validation"]["unknowns"] if u["check"] == "unknown_flow_direction"}
        self.assertFalse(unknown & {r["local_id"] for r in flows})


if __name__ == "__main__":
    unittest.main()
