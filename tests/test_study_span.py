import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.graph import project  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import remap  # noqa: E402
from hazop.study import results as res  # noqa: E402
from hazop.study import span  # noqa: E402
from tests.test_project_graph import cont, sheet  # noqa: E402

AT = "2026-11-07T00:00:00Z"
DEVS = [{"deviation_id": "D01", "item_id": "i1", "parameter": "흐름", "guideword": "없음", "label": "흐름 없음"}]


def two_sheets():
    a = sheet("SNP-M-101", cont("C1", "TO SNP-M-102\nL-1"))
    b = sheet("SNP-M-102", cont("C1", "FROM SNP-M-101\nL-1"))
    pg = project.build("P", [a, b])
    return a, b, pg, sn.propose(pg, at=AT)


class SpanTest(unittest.TestCase):

    def test_short_numbers_cut_at_separator(self):
        self.assertEqual(span.short_numbers(["SNP-M-101", "SNP-M-102", "SNP-M-201"]),
                         ("SNP-M-", {"SNP-M-101": "101", "SNP-M-102": "102", "SNP-M-201": "201"}))
        self.assertEqual(span.short_numbers(["SNP-M-102"]), ("SNP-M-", {"SNP-M-102": "102"}))

    def test_spanning_node_name_order_boundary_and_chip(self):
        _, _, pg, s = two_sheets()
        a = span.annotate(s, pg)
        node = next(n for n in a["nodes"] if n["spans_drawings"])
        self.assertTrue(node["display_name"].endswith("[101 → 102]"))
        self.assertEqual(node["drawings"], ["SNP-M-101", "SNP-M-102"])
        self.assertEqual(node["member_count"], sum(node["members_by_drawing"].values()) + 1)  # + 도면 연결 구간
        # 도면을 잇는 배관에는 편차원이 없어 번호가 앞선 탱크 구간에 붙는다(R2). 경계는 안쪽 탱크에서 밖의 다른 도면 탱크까지
        self.assertIn("graph-SNP-M-101/E", node["members"])
        self.assertEqual(span.worksheet_header(node)["start"], "SNP-M-101-E(SNP-M-101)")
        self.assertEqual(span.worksheet_header(node)["end"], "SNP-M-102-E(SNP-M-102)")
        chips = [span.continuation_chip(node["node_id"], c) for c in node["continuations"]]
        self.assertIn("%s → SNP-M-102에서 계속" % node["node_id"], chips)
        self.assertEqual(span.drawing_column(node), "SNP-M-101, SNP-M-102")
        single = next(n for n in a["nodes"] if not n["spans_drawings"])
        self.assertRegex(single["display_name"], r"\[10[12]\]$")

    def test_filter_and_coverage_per_drawing(self):
        _, _, pg, s = two_sheets()
        a = span.annotate(s, pg)
        on = span.nodes_on_drawing(a, "SNP-M-102")
        self.assertTrue(any(n["spans_drawings"] for n in on))
        cov = span.coverage_by_drawing(s, pg)
        self.assertEqual(cov["project"]["ratio"], 1.0)
        self.assertEqual(set(cov["drawings"]), {"SNP-M-101", "SNP-M-102"})

    def test_label_tags_marks_other_drawing_only(self):
        _, _, pg, _ = two_sheets()
        td = span.tag_drawings(pg)
        out = span.label_tags("SNP-M-101-E와 SNP-M-102-E", td, "SNP-M-102", {"SNP-M-101": "101"})
        self.assertEqual(out, "SNP-M-101-E(101)와 SNP-M-102-E")

    def test_migration_keeps_human_entries_and_legacy_ids(self):
        a, _, pg, s = two_sheets()
        s = sn.confirm(s, pg, "검토자", at=AT)  # 도면별 결과는 확정한 프로젝트 집합으로만 옮긴다
        old = sn.propose(a, at=AT)
        entry = {"entry_id": "S1-D01-x", "origin": "ai_draft", "status": "approved", "cause": "c",
                 "ai_basis": {"kg_paths": [["entity-x", "cond-1"]]}}
        old_res = remap.empty_legacy(old, DEVS)  # 옛 도면별 결과(0.1)
        cell = next(c for c in old_res["cells"] if c["node_id"] == "S1")
        cell.update(state="analyzed", entries=[entry])
        moved = span.migrate_set([old], s)
        self.assertEqual(sorted(i for n in moved["nodes"] for i in n["legacy_ids"]),
                         sorted("graph-SNP-M-101:%s" % n["node_id"] for n in old["nodes"]))
        out, report = span.migrate_results([old_res], [old], s, DEVS)
        self.assertEqual(res.validate(out, s), [])
        got = [e for c in out["cells"] for e in c["entries"]]
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["status"], got[0]["legacy"]["entry_id"]), ("approved", "S1-D01-x"))
        self.assertEqual(got[0]["ai_basis"]["kg_paths"], [["graph-SNP-M-101/entity-x", "cond-1"]])
        self.assertEqual((report["moved_entries"], report["human_entries"], report["unmapped"]), (1, 1, []))
        self.assertTrue(got[0]["scope_changed"])  # 구간이 SNP-M-102까지 넓어짐
        self.assertEqual(entry["entry_id"], "S1-D01-x")  # 옛 결과는 바꾸지 않음


    def old_result(self, old, state="analyzed", entries=None):
        r = remap.empty_legacy(old, DEVS)
        cell = next(c for c in r["cells"] if c["node_id"] == "S1")
        cell.update(state=state, entries=entries or [])
        return r

    def test_stale_source_is_flagged(self):
        a, _, pg, s = two_sheets()
        s = sn.confirm(s, pg, "검토자", at=AT)  # 도면별 결과는 확정한 프로젝트 집합으로만 옮긴다
        old = sn.propose(a, at=AT)
        r = self.old_result(old, entries=[{"entry_id": "e", "origin": "human", "status": "approved"}])
        r["study_nodes_ref"] = {"graph_version": "v-old", "confirmed_at": None}
        out, report = span.migrate_results([r], [old], s, DEVS, pg)
        self.assertEqual(report["stale_entries"], 1)
        self.assertTrue(next(e for c in out["cells"] for e in c["entries"])["source_stale"])

    def test_deviation_matched_by_item_not_id(self):
        a, _, pg, s = two_sheets()
        s = sn.confirm(s, pg, "검토자", at=AT)  # 도면별 결과는 확정한 프로젝트 집합으로만 옮긴다
        old = sn.propose(a, at=AT)
        r = self.old_result(old, entries=[{"entry_id": "e", "origin": "human", "status": "approved"}])
        r["deviations"][0]["item_id"] = "other"
        _, report = span.migrate_results([r], [old], s, DEVS, pg)
        self.assertEqual(span.blocked(report), ["unmapped_deviations"])

    def test_widened_scope_does_not_inherit_excluded(self):
        a, _, pg, s = two_sheets()
        s = sn.confirm(s, pg, "검토자", at=AT)  # 도면별 결과는 확정한 프로젝트 집합으로만 옮긴다
        old = sn.propose(a, at=AT)
        widened = next(k for k, v in span.legacy_map([old], s, pg).items() if not v["exact"])
        r = remap.empty_legacy(old, DEVS)
        for c in r["cells"]:
            c["state"] = "excluded"
        out, _ = span.migrate_results([r], [old], s, DEVS, pg)
        target = span.legacy_map([old], s, pg)[widened]["node_id"]
        self.assertEqual(next(c for c in out["cells"] if c["node_id"] == target)["state"], "not_analyzed")

    def test_existing_legacy_ids_kept_and_unmapped_recorded(self):
        a, _, pg, s = two_sheets()
        old = sn.propose(a, at=AT)
        old["nodes"].append({"node_id": "S99", "name": "x", "members": ["gone"]})
        s["nodes"][0]["legacy_ids"] = ["previous:S9"]
        moved = span.migrate_set([old], s, pg)
        self.assertIn("previous:S9", moved["nodes"][0]["legacy_ids"])
        self.assertEqual(moved["legacy_unmapped"], ["graph-SNP-M-101:S99"])
        _, report = span.migrate_results([], [old], s, DEVS, pg)
        self.assertEqual(span.blocked(report), ["unmapped_nodes"])


if __name__ == "__main__":
    unittest.main()
