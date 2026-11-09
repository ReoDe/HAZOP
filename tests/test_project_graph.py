import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.graph import project  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402


def cont(eid, label, soid=None, **attrs):
    return {"entity_id": eid, "node_type": "drawing_object", "kind": "continuation", "category": "piping_element",
            "tag": None, "label_text": label, "attributes": dict(attrs, kind="continuation"),
            "source_object_id": soid or eid}


def sheet(dn, *conts, extra=(), valve=False):
    """연결점 + 기기 E(태그 <dn>-E) + 배관 구간으로 각 연결점을 기기에 잇는 도면.
    valve면 연결점마다 밸브 가지를 달아, 도면을 잇는 배관이 편차원을 가진 제 구간으로 남게 한다."""
    nodes = [{"entity_id": "E", "node_type": "drawing_object", "kind": "tank", "category": "equipment",
              "tag": "%s-E" % dn, "label_text": "", "attributes": {}, "source_object_id": "E"}] + list(conts)
    edges = []
    for i, c in enumerate(conts):
        seg = "S%d" % i
        nodes.append({"entity_id": seg, "node_type": "pipe_segment", "kind": "pipe_segment", "category": "pipe_segment",
                      "tag": None, "line_no": None, "flow_direction": None, "attributes": {}})
        edges += [{"entity_id": seg + "a", "kind": "has_endpoint", "nodes": [seg, c["entity_id"]], "segment": seg,
                   "node": c["entity_id"], "end": "source"},
                  {"entity_id": seg + "b", "kind": "has_endpoint", "nodes": [seg, "E"], "segment": seg, "node": "E",
                   "end": "target"}]
    if valve:
        for i, c in enumerate(conts):
            vid, seg = "V%d" % i, "SV%d" % i
            nodes += [{"entity_id": vid, "node_type": "drawing_object", "kind": "manual_valve", "category": "valve",
                       "tag": "%s-V%d" % (dn, i), "label_text": "", "attributes": {}, "source_object_id": vid},
                      {"entity_id": seg, "node_type": "pipe_segment", "kind": "pipe_segment", "category": "pipe_segment",
                       "tag": None, "line_no": None, "flow_direction": None, "attributes": {}}]
            edges += [{"entity_id": seg + "a", "kind": "has_endpoint", "nodes": [seg, c["entity_id"]], "segment": seg,
                       "node": c["entity_id"], "end": "source"},
                      {"entity_id": seg + "b", "kind": "has_endpoint", "nodes": [seg, vid], "segment": seg, "node": vid,
                       "end": "target"}]
    return {"graph_id": "graph-" + dn, "graph_version": "v1", "project_id": "P", "source": {"drawing_number": dn},
            "nodes": nodes + list(extra), "edges": edges, "validation": {"status": "passed"}}


class MatchTest(unittest.TestCase):

    def statuses(self, graphs, ops=()):
        return sorted((l["status"], l["reason"]) for l in project.build("P", graphs, ops)["sheet_links"])

    def test_pair_links_and_flows_from_to_side(self):
        a = sheet("A", cont("C1", "FROM B\nL-1 FEED"))
        b = sheet("B", cont("C1", "TO A\nL-1 FEED"))
        pg = project.build("P", [a, b])
        link = pg["sheet_links"][0]
        self.assertEqual((link["status"], link["from"]["drawing_number"], link["to"]["drawing_number"]),
                         ("linked", "B", "A"))
        self.assertEqual(project.summary(pg)["physical_components"], 1)
        seg = next(n for n in pg["nodes"] if n["entity_id"] == link["link_id"])
        self.assertEqual(seg["flow_direction"]["from"], "graph-B/C1")

    def test_label_only_continuation_is_read(self):
        a = sheet("A", cont("C1", "TO B\nL-1"))
        b = sheet("B", cont("C1", "FROM A\nL-1"))
        self.assertEqual(self.statuses([a, b]), [("linked", None)])

    def test_attributes_win_over_label(self):
        a = sheet("A", cont("C1", "TO X\nZZ", to_drawing="B", line_no="L-1"))
        b = sheet("B", cont("C1", "FROM A\nL-1"))
        self.assertEqual(self.statuses([a, b]), [("linked", None)])

    def test_unregistered_and_no_counterpart(self):
        a = sheet("A", cont("C1", "TO Q\nL-1"), cont("C2", "TO B\nL-2"))
        b = sheet("B", cont("C1", "FROM A\nL-9"))
        self.assertEqual(self.statuses([a, b]), [("unlinked", "no_counterpart"), ("unlinked", "no_counterpart"),
                                                 ("unlinked", "unregistered_drawing")])

    def test_ambiguous_links_nothing(self):
        a = sheet("A", cont("C1", "TO B\nL-1"), cont("C2", "TO B\nL-1"))
        b = sheet("B", cont("C1", "FROM A\nL-1"))
        self.assertEqual(self.statuses([a, b]), [("unlinked", "ambiguous")] * 3)

    def test_direction_conflict(self):
        a = sheet("A", cont("C1", "TO B\nL-1"))
        b = sheet("B", cont("C1", "TO A\nL-1"))
        self.assertEqual(self.statuses([a, b]), [("unlinked", "direction_conflict")] * 2)

    def test_manual_ops_come_first(self):
        a = sheet("A", cont("C1", "TO B\nL-1"))
        b = sheet("B", cont("C1", "FROM A\nL-7"))
        ends = [{"drawing_number": "A", "source_object_id": "C1"}, {"drawing_number": "B", "source_object_id": "C1"}]
        link = {"op_id": "1", "op": "link", "ends": ends, "by": "kim"}
        self.assertEqual(self.statuses([a, b], [link]), [("linked", None)])
        cut = {"op_id": "1", "op": "unlink", "ends": ends[:1], "by": "kim"}
        self.assertEqual(self.statuses([a, b], [cut]), [("unlinked", "manual_unlink"), ("unlinked", "no_counterpart")])
        bad = {"op_id": "2", "op": "link", "ends": ends[:1], "by": "kim"}
        self.assertEqual(project.build("P", [a, b], [bad])["manual_skipped"][0]["op_id"], "2")

    def test_manual_link_of_same_direction_has_no_flow(self):
        a, b = sheet("A", cont("C1", "TO B\nL-1")), sheet("B", cont("C1", "TO A\nL-1"))
        ends = [{"drawing_number": "A", "source_object_id": "C1"}, {"drawing_number": "B", "source_object_id": "C1"}]
        pg = project.build("P", [a, b], [{"op_id": "1", "op": "link", "ends": ends, "by": "kim"}])
        link = pg["sheet_links"][0]
        self.assertEqual((link["status"], link["flow_known"]), ("linked", False))
        self.assertIsNone(next(n for n in pg["nodes"] if n["entity_id"] == link["link_id"])["flow_direction"])

    def test_manual_op_matching_several_continuations_is_skipped(self):
        a, b = sheet("A", cont("C1", "TO B\nL-1")), sheet("a", cont("C1", "TO B\nL-2"))
        cut = {"op_id": "1", "op": "unlink", "ends": [{"drawing_number": "A", "source_object_id": "C1"}], "by": "kim"}
        pg = project.build("P", [a, b, sheet("B")], [cut])
        self.assertEqual(pg["manual_skipped"], [{"op_id": "1", "reason": "가리키는 연결점이 여럿이라 고르지 않음"}])

    def test_duplicate_tag_across_sheets_is_reported_not_merged(self):
        dup = {"entity_id": "D", "node_type": "drawing_object", "kind": "tank", "category": "equipment", "tag": "T-1"}
        pg = project.build("P", [sheet("A", extra=[dup]), sheet("B", extra=[dup])])
        self.assertEqual([d["tag"] for d in pg["duplicate_tags"]], ["T-1"])
        self.assertEqual(sum(1 for n in pg["nodes"] if n.get("tag") == "T-1"), 2)


class StudyAcrossSheetsTest(unittest.TestCase):

    def test_proposal_crosses_linked_sheets_and_covers_all(self):
        a = sheet("A", cont("C1", "FROM B\nL-1"))
        b = sheet("B", cont("C1", "TO A\nL-1"))
        pg = project.build("P", [a, b])
        s = sn.propose(pg, at="2026-11-07T00:00:00Z")
        self.assertEqual(sn.coverage(s, pg)["ratio"], 1.0)
        self.assertTrue(any(project.sheets_of(pg, n["members"]) == ["graph-A", "graph-B"] for n in s["nodes"]))
        view = project.sheet_view(s, pg, "graph-A")
        self.assertEqual(sorted(m for v in view for m in v["members"]), ["C1", "E", "S0"])

    def test_project_id_of_unregistered(self):
        self.assertEqual(project.project_id_of({"project_id": None}), project.UNREGISTERED_PROJECT)
        self.assertEqual(project.project_id_of({"project_id": "X"}), "X")


if __name__ == "__main__":
    unittest.main()
