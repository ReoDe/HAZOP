"""⑤ 분석 결과 셸(hazop.study.results) 시험. 파일을 쓰지 않는다."""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as sr  # noqa: E402
from test_study_nodes import AT, synthetic_graph  # noqa: E402


def entry(eid, status="proposed", risk=None, origin="ai_draft"):
    return {"entry_id": eid, "cause": "c", "consequence": "q", "safeguards": [], "recommendation": "",
            "risk": risk, "origin": origin, "status": status, "ai_basis": {"kg_paths": [], "sources": []}}


class ResultsTest(unittest.TestCase):
    def setUp(self):
        self.g = synthetic_graph()
        self.nodes = sn.confirm(sn.propose(self.g, at=AT), self.g, "김검토", at=AT)
        self.devs = sr.load_deviations()

    def test_deviations_come_from_kosha_chart(self):
        self.assertEqual(len(self.devs), 44)
        self.assertEqual(self.devs[0]["deviation_id"], "D01")
        no_flow = next(d for d in self.devs if d["item_id"] == "p86-d03")
        self.assertEqual((no_flow["parameter"], no_flow["guideword"], no_flow["label"]), ("유량", "없음", "유량 없음"))
        self.assertEqual(len({d["deviation_id"] for d in self.devs}), 44)

    def test_empty_shell_has_every_cell_unanalysed(self):
        res = sr.empty_results(self.nodes, self.devs)
        self.assertEqual(len(res["cells"]), len(self.nodes["nodes"]) * 44)
        self.assertTrue(all(c["state"] == "not_analyzed" and c["entries"] == [] for c in res["cells"]))
        self.assertEqual(res["study_nodes_ref"], {"graph_version": "v-1", "confirmed_at": AT})
        self.assertEqual(sr.validate(res, self.nodes), [])
        summary = sr.matrix_summary(res)
        self.assertEqual(summary["S1"]["D01"], {"state": "not_analyzed", "scenarios": 0, "max_risk": None,
                                                "unreviewed": 0})

    def test_matrix_summary_counts_live_entries(self):
        res = sr.empty_results(self.nodes, self.devs)
        cell = res["cells"][0]
        cell["state"] = "analyzed"
        cell["entries"] = [entry("e1", risk=3), entry("e2", status="approved", risk=4, origin="human"),
                           entry("e3", status="rejected", risk=5)]
        got = sr.matrix_summary(res)[cell["node_id"]][cell["deviation_id"]]
        self.assertEqual(got, {"state": "analyzed", "scenarios": 2, "max_risk": 4, "unreviewed": 1})
        self.assertEqual(sr.validate(res, self.nodes), [])
        cell["entries"].append(entry("e4", status="revised", risk=2, origin="ai_draft"))
        got = sr.matrix_summary(res)[cell["node_id"]][cell["deviation_id"]]
        self.assertEqual(got["unreviewed"], 2, "고친 AI 초안도 승인 전에는 미검토")
        self.assertTrue(sr.is_ai_draft(cell["entries"][0]))
        self.assertFalse(sr.is_ai_draft(dict(cell["entries"][0], status="approved")))

    def test_validate_reports_bad_values_and_references(self):
        res = sr.empty_results(self.nodes, self.devs)
        res["cells"][0].update(state="done", entries=[entry("e1", risk=7, origin="robot", status="maybe")])
        res["cells"][1]["node_id"] = "S999"
        res["cells"][2]["deviation_id"] = "D99"
        problems = "\n".join(sr.validate(res, self.nodes))
        for needle in ("state 값", "risk 값", "origin 값", "status 값", "없는 검토구간", "없는 편차"):
            self.assertIn(needle, problems)


if __name__ == "__main__":
    unittest.main()
