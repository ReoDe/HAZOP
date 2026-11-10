"""확정 해제 → 다시 제안·편집 → 다시 확정할 때 옛 구간·⑤ 결과를 잇는 시험. 근거: 기획서/검토구간-분할설계.md §4.6."""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.study import nodes as sn, remap, results as res, span  # noqa: E402
from tests.test_study_segment import AT, G  # noqa: E402

AT2 = "2026-11-10T00:00:00Z"


def plant():
    """탱크 A - 밸브 V1 - 탱크 B - 밸브 V2 - 탱크 C. 고립 T 하나(제외 묶음)."""
    g = G()
    a, b, c = (g.add(e, "tank", "equipment", t) for e, t in (("a-tank", "TK-A"), ("b-tank", "TK-B"), ("c-tank", "TK-C")))
    v1, v2 = g.add("v1", "manual_valve", "valve", "V-1"), g.add("v2", "manual_valve", "valve", "V-2")
    g.pipe(a, v1)
    g.pipe(v1, b)
    g.pipe(b, v2)
    g.pipe(v2, c)
    g.add("x-tee", "tee", "piping_element")
    return g.graph()


def node_of(ns, eid):
    return next(n["node_id"] for n in ns["nodes"] if eid in n["members"])


def approve(results, node_id, did, entry_id):
    doc = copy.deepcopy(results)
    cell = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (node_id, did))
    cell.update(state="analyzed", entries=[{"entry_id": entry_id, "cause": "누설", "consequence": "수위 저하",
                                            "safeguards": [], "recommendation": "권고", "risk": None,
                                            "origin": "ai_draft", "status": "approved"}])
    return doc


class RemapTest(unittest.TestCase):

    def setUp(self):
        self.graph = plant()
        self.devs = res.load_deviations()
        self.did = self.devs[0]["deviation_id"]
        self.first = sn.confirm(sn.propose(self.graph, at=AT), self.graph, "검토자", at=AT)
        self.v1 = node_of(self.first, "v1")
        self.tank = node_of(self.first, "c-tank")
        doc = res.empty_results(self.first, self.devs)
        doc = approve(doc, self.v1, self.did, "E1")
        self.results = approve(doc, self.tank, self.did, "E2")

    def reconfirm(self, edit):
        opened = sn.reopen(self.first, at=AT)
        self.assertEqual(opened["previous"][-1]["study_nodes_ref"],
                         {"graph_version": "v1", "confirmed_at": AT})
        return sn.confirm(edit(opened), self.graph, "검토자", at=AT2)

    def test_unchanged_nodes_keep_their_cells_and_changed_ones_are_marked(self):
        merged = self.reconfirm(lambda s: sn.merge(s, [self.v1, node_of(s, "b-tank")], at=AT))
        self.assertTrue(res.is_stale(self.results, merged))
        carried, report = remap.carry_results(self.results, merged, self.devs)
        self.assertEqual(res.validate(carried, merged), [])
        self.assertFalse(res.is_stale(carried, merged))
        cell = lambda nid: next(c for c in carried["cells"] if (c["node_id"], c["deviation_id"]) == (nid, self.did))  # noqa: E731
        same = cell(node_of(merged, "c-tank"))
        self.assertEqual((same["state"], [e["entry_id"] for e in same["entries"]]), ("analyzed", ["E2"]))
        self.assertNotIn("scope_changed", same["entries"][0])
        moved = cell(node_of(merged, "v1"))
        self.assertEqual([e["entry_id"] for e in moved["entries"]], ["E1"])
        self.assertTrue(moved["entries"][0]["scope_changed"])
        self.assertEqual(moved["entries"][0]["status"], "approved")  # 사람 판정은 그대로, 다시 보게만 한다
        self.assertGreaterEqual(report["same_cells"], 1)
        self.assertEqual(report["scope_changed_entries"], 1)

    def test_mapping_rows_name_what_happened(self):
        merged = self.reconfirm(lambda s: sn.merge(s, [self.v1, node_of(s, "b-tank")], at=AT))
        _old, rows = remap.node_map(remap.latest(merged), merged)
        self.assertEqual(rows[node_of(merged, "v1")]["kind"], "merged")
        self.assertEqual(rows[node_of(merged, "c-tank")]["kind"], "same")
        bucket = next(n["node_id"] for n in merged["nodes"] if n["screen"]["status"] == "excluded")
        self.assertEqual(rows[bucket]["kind"], "excluded")
        self.assertEqual(remap.summary(rows)["merged"], 1)

    def test_human_entries_never_move_into_an_exclusion_bucket(self):
        opened = sn.reopen(self.first, at=AT)
        bucket = next(n["node_id"] for n in opened["nodes"] if n["screen"]["status"] == "excluded")
        moved = sn.add_member(sn.remove_member(opened, self.tank, "c-tank", at=AT), bucket, "c-tank", at=AT)
        moved["nodes"] = [n for n in moved["nodes"] if n["members"]]
        again = sn.confirm(moved, self.graph, "검토자", at=AT2)
        carried, report = remap.carry_results(self.results, again, self.devs)
        self.assertIsNone(carried)
        self.assertEqual(report["to_excluded"], [self.tank])

    def test_results_from_another_confirmation_are_not_carried(self):
        merged = self.reconfirm(lambda s: s)
        other = dict(self.results, study_nodes_ref={"graph_version": "v1", "confirmed_at": "2026-01-01T00:00:00Z"})
        carried, report = remap.carry_results(other, merged, self.devs)
        self.assertIsNone(carried)
        self.assertIn("reason", report)

    def test_repropose_keeps_the_snapshot_and_map_members_renames_it(self):
        opened = sn.reopen(self.first, at=AT)
        renamed = sn.map_members(opened, {"c-tank": "c-tank-2"})
        self.assertIn("c-tank-2", [m for n in renamed["previous"][-1]["nodes"] for m in n["members"]])

    def test_reopening_twice_before_saving_results_still_finds_their_confirmation(self):
        second = sn.confirm(sn.reopen(self.first, at=AT), self.graph, "검토자", at=AT2)
        third = sn.confirm(sn.reopen(second, at=AT2), self.graph, "검토자", at="2026-11-11T00:00:00Z")
        self.assertEqual([p["study_nodes_ref"]["confirmed_at"] for p in third["previous"]], [AT, AT2])
        carried, report = remap.carry_results(self.results, third, self.devs)
        self.assertIsNotNone(carried, report)
        self.assertEqual(sorted(e["entry_id"] for c in carried["cells"] for e in c["entries"]), ["E1", "E2"])

    def test_entries_without_a_new_home_stop_the_carry(self):
        again = self.reconfirm(lambda s: s)
        orphan = copy.deepcopy(self.results)
        orphan["cells"].append({"node_id": "S99", "deviation_id": self.did, "state": "analyzed",
                                "entries": [{"entry_id": "E3", "origin": "ai_draft", "status": "proposed"}]})
        again["previous"][-1]["nodes"].append({"node_id": "S99", "members": ["없는-구성요소"]})
        carried, report = remap.carry_results(orphan, again, self.devs)
        self.assertIsNone(carried)
        self.assertEqual(report["unmapped"], [{"node_id": "S99", "deviation_id": self.did}])

    def test_new_graph_content_marks_every_carried_entry_for_review(self):
        changed = copy.deepcopy(self.graph)
        changed["graph_version"] = "v2"
        next(n for n in changed["nodes"] if n["entity_id"] == "v1")["attributes"] = {"normal_position": "closed"}
        opened = sn.reopen(self.first, at=AT)
        fresh = dict(sn.propose(changed, at=AT), previous=opened["previous"])
        again = sn.confirm(fresh, changed, "검토자", at=AT2)
        carried, report = remap.carry_results(self.results, again, self.devs)
        self.assertIsNotNone(carried, report)
        self.assertFalse(res.is_stale(carried, again))
        entries = [e for c in carried["cells"] for e in c["entries"]]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e.get("scope_changed") for e in entries))  # 같은 구성요소라도 내용이 바뀌면 다시 본다
        self.assertEqual(report["same_cells"], 0)

    def test_carry_saved_writes_the_carry_and_recovers_from_an_archived_file(self):
        import tempfile
        from hazop import paths
        tmp, env = tempfile.mkdtemp(), os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = tmp
        try:
            path = res.save(self.results, self.first.get("project_id"))
            os.replace(path, path[:-5] + ".2026-11-09T010000Z.bak.json")  # ⑤가 첫 저장 때 보관본으로 옮긴 상태
            again = self.reconfirm(lambda s: s)
            carried, report = remap.carry_saved(again, self.devs)
            self.assertIsNotNone(carried, report)
            saved = res.load(again)
            self.assertFalse(res.is_stale(saved, again))
            self.assertEqual(sorted(e["entry_id"] for c in saved["cells"] for e in c["entries"]), ["E1", "E2"])
            self.assertEqual(remap.carry_saved(again, self.devs)[0], None)  # 두 번째 부르면 할 일이 없다
        finally:
            if env is None:
                os.environ.pop(paths.ENV_WORK_ROOT, None)
            else:
                os.environ[paths.ENV_WORK_ROOT] = env

    def test_legacy_migration_stops_before_hiding_human_entries_in_a_bucket(self):
        bucket = next(n for n in self.first["nodes"] if n["screen"]["status"] == "excluded")
        old_set = {"graph_id": "graph-T", "graph_version": "v1", "status": "confirmed", "confirmed_at": AT,
                   "nodes": [{"node_id": "S1", "members": list(bucket["members"])}]}
        old_res = approve(res.empty_results(dict(old_set, project_id=None), self.devs), "S1", self.did, "E9")
        project_set = copy.deepcopy(self.first)
        for n in project_set["nodes"]:
            n["members"] = ["graph-T/" + m for m in n["members"]]
        _out, report = span.migrate_results([old_res], [old_set], project_set, self.devs)
        self.assertIn("to_excluded", span.blocked(report))


if __name__ == "__main__":
    unittest.main()
