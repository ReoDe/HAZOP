"""그래프 판 이전(hazop.study.migrate, U10) 시험. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다."""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.study import migrate  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402

AT = "2026-11-08T00:00:00Z"
OBJECTS = [("TK", "tank", "equipment"), ("V1", "manual_valve", "valve"), ("V2", "manual_valve", "valve"),
           ("PP", "pump", "equipment"), ("LT", "transmitter", "instrument")]
PIPES = [("L1", "TK", "V1"), ("L2", "V1", "V2"), ("L3", "V2", "PP")]


def graph(version, objects=OBJECTS, pipes=PIPES, shift=0):
    """source_object_id는 그대로이고 entity_id 번호만 shift만큼 밀린 도면 그래프(재추출 흉내)."""
    nodes, edges, eid = [], [], {}
    for i, (soid, kind, cat) in enumerate(objects, 1 + shift):
        eid[soid] = "entity-node-%03d" % i
        nodes.append({"entity_id": eid[soid], "node_type": "drawing_object", "kind": kind, "category": cat,
                      "tag": soid, "label_text": soid, "source_object_id": soid, "position": [0.0, 0.0]})
    for i, (soid, a, b) in enumerate(pipes, 1 + shift):
        sid = "entity-seg-%03d" % i
        nodes.append({"entity_id": sid, "node_type": "pipe_segment", "kind": "pipe_segment",
                      "category": "pipe_segment", "tag": "L", "line_no": "L", "source_object_id": soid,
                      "position": [0.0, 0.0]})
        edges += [{"entity_id": "relation-%s-%s" % (sid, x), "kind": "has_endpoint", "nodes": [sid, eid[x]]}
                  for x in (a, b) if x in eid]
    if "LT" in eid and "TK" in eid:
        edges.append({"entity_id": "relation-m1", "kind": "measurement_connection", "nodes": [eid["TK"], eid["LT"]]})
    return {"project_id": None, "graph_id": "graph-T", "graph_version": version,
            "source": {"drawing_number": "T-1"}, "nodes": nodes, "edges": edges}


def entity(g, soid):
    return next(n["entity_id"] for n in g["nodes"] if n["source_object_id"] == soid)


def results_for(ns, g):
    """사람이 고친 항목 1개(승인)와 AI 초안 1개가 든 결과. kg_paths에는 구성요소 ID와 지식 ID가 섞여 있다."""
    doc = res.empty_results(ns, [{"deviation_id": "D01", "item_id": "I1", "parameter": "유량", "guideword": "없음",
                                  "label": "유량 없음"}])
    cell = doc["cells"][0]
    cell["state"] = "analyzed"
    path = [entity(g, "L1"), entity(g, "V1"), "cond-001"]
    cell["entries"] = [
        {"entry_id": "e1", "origin": "ai_draft", "status": "approved", "cause": "V1 닫힘 고착", "consequence": "유량 없음",
         "safeguards": ["LT 저액위 경보"], "recommendation": None, "severity": 2, "frequency": 2, "risk": 2,
         "history": [{"at": AT, "op": "edit", "from": "proposed", "before": {"cause": "AI 문장"}}],
         "ai_basis": {"kg_paths": [path], "sources": [], "equipment_tags": ["V1"], "warnings": []}},
        {"entry_id": "e2", "origin": "ai_draft", "status": "proposed", "cause": "V2 오조작", "consequence": "-",
         "safeguards": [], "recommendation": None, "severity": None, "frequency": None, "risk": None,
         "ai_basis": {"kg_paths": [[entity(g, "V2"), "relation-old-9"]], "sources": [], "equipment_tags": [],
                      "warnings": []}}]
    return doc


def text_of(doc):
    keep = ("entry_id", "origin", "status", "cause", "consequence", "safeguards", "recommendation",
            "severity", "frequency", "risk", "history")
    return [{k: e.get(k) for k in keep} for c in doc["cells"] for e in c["entries"]]


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        self.g1 = graph("v-1")
        self.ns = sn.confirm(sn.propose(self.g1, at=AT), self.g1, "김검토", at=AT)

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    def raw(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_confirm_records_stable_refs(self):
        refs = self.ns["member_refs"]
        self.assertEqual(refs[entity(self.g1, "V1")], "graph-T#V1")
        self.assertEqual(len(refs), len(self.g1["nodes"]))

    def test_all_mapped_keeps_confirmation_and_logs(self):
        sn.save(self.ns)
        g2 = graph("v-2", shift=10)
        got = sn.load(g2)
        self.assertEqual((got["status"], got["confirmed_by"], got["confirmed_at"]), ("confirmed", "김검토", AT))
        self.assertEqual(got["graph_version"], "v-2")
        self.assertFalse(sn.is_stale(got, g2))
        self.assertEqual(sn.coverage(got, g2)["uncovered"], [])
        by_soid = {n["source_object_id"]: n["entity_id"] for n in g2["nodes"]}
        old_soid = {e: r.split("#")[1] for e, r in self.ns["member_refs"].items()}
        for before, after in zip(self.ns["nodes"], got["nodes"]):
            self.assertEqual(after["node_id"], before["node_id"])
            self.assertEqual(after["members"], sorted(by_soid[old_soid[m]] for m in before["members"]))
        last = got["history"][-1]
        self.assertEqual((last["op"], last["detail"]["from"], last["detail"]["to"], last["detail"]["matched"]),
                         ("migrate_version", "v-1", "v-2", len(g2["nodes"])))
        self.assertEqual(migrate.notice(got), "그래프 판이 바뀌어(v-1 → v-2) 구성요소 %d개를 새 판에 다시 맞췄습니다. 확정은 그대로입니다."
                         % len(g2["nodes"]))
        self.assertEqual(got["history"][:-1], self.ns["history"])
        self.assertTrue(os.path.isdir(paths.folder_in(self.tmp, "backup")))
        with open(sn.store_path(None, "graph-T"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), got)

    def test_one_missing_component_needs_recheck(self):
        path = sn.save(self.ns)
        before = self.raw(path)
        g2 = graph("v-2", objects=OBJECTS[:-1], shift=3)
        got = sn.load(g2)
        self.assertEqual(got, self.ns)
        self.assertTrue(sn.is_stale(got, g2))
        self.assertEqual(self.raw(path), before)
        self.assertEqual(migrate.plan(self.ns, g2)["state"], "recheck")
        self.assertIn("새 판에 없는", migrate.plan(self.ns, g2)["reason"])

    def test_added_or_ambiguous_component_needs_recheck(self):
        extra = graph("v-2", objects=OBJECTS + [("FT", "transmitter", "instrument")])
        self.assertIn("늘어난", migrate.plan(self.ns, extra)["reason"])
        dup = graph("v-2")
        dup["nodes"][1]["source_object_id"] = "TK"
        self.assertIn("모호", migrate.plan(self.ns, dup)["reason"])
        unproposed = sn.propose(self.g1, at=AT)
        self.assertEqual(migrate.plan(unproposed, graph("v-2"))["state"], "skip")

    def test_changed_tag_kind_or_link_needs_recheck(self):
        """② 사람 수정처럼 참조는 같고 내용만 바뀐 판은 유지하지 않는다(결정로그 2026-11-07 '재확인 필요')."""
        tag = graph("v-2", shift=10)
        tag["nodes"][1]["tag"] = "V1-NEW"
        kind = graph("v-2", objects=[("TK", "tank", "equipment"), ("V1", "pump", "equipment")] + OBJECTS[2:])
        link = graph("v-2", pipes=[("L1", "TK", "V2"), ("L2", "V1", "V2"), ("L3", "V2", "PP")])
        for g in (tag, kind, link):
            p = migrate.plan(self.ns, g)
            self.assertEqual((p["state"], p["reason"]), ("recheck", "구성요소의 종류·태그·흐름·연결·정상 위치·고장 위치가 바뀜"))
        extra_field = graph("v-2", shift=10)
        for n in extra_field["nodes"]:
            n["origin"] = "drawing"
            n["attributes"] = {"claims": []}
        self.assertEqual(migrate.plan(self.ns, extra_field)["state"], "kept")

    def test_twice_is_same(self):
        sn.save(self.ns)
        g2 = graph("v-2", shift=10)
        first = sn.load(g2)
        path = sn.store_path(None, "graph-T")
        after_first = self.raw(path)
        self.assertEqual(sn.load(g2), first)
        self.assertEqual(self.raw(path), after_first)
        self.assertEqual([h["op"] for h in first["history"]].count("migrate_version"), 1)
        again, p = migrate.migrate_set(first, g2, at=AT)
        self.assertIs(again, first)
        self.assertEqual(p["state"], "same")

    def test_results_move_with_set_and_keep_content(self):
        sn.save(self.ns)
        doc = results_for(self.ns, self.g1)
        rpath = res.save(doc, None)
        g2 = graph("v-2", shift=10)
        ns2 = sn.load(g2)
        with open(rpath, encoding="utf-8") as fh:
            moved = json.load(fh)
        self.assertEqual(moved["study_nodes_ref"], {"graph_version": "v-2", "confirmed_at": AT})
        self.assertFalse(res.is_stale(moved, ns2))
        self.assertEqual(res.validate(moved, ns2), [])
        self.assertEqual(text_of(moved), text_of(doc))
        self.assertEqual(moved["cells"][0]["state"], "analyzed")
        paths_ = [e["ai_basis"]["kg_paths"] for e in moved["cells"][0]["entries"]]
        self.assertEqual(paths_[0], [[entity(g2, "L1"), entity(g2, "V1"), "cond-001"]])
        self.assertEqual(paths_[1], [[entity(g2, "V2"), "relation-old-9"]])
        log = moved["version_migrations"][-1]
        self.assertEqual((log["from"], log["to"], log["kg_path_ids_changed"], log["kg_path_ids_unmapped"]),
                         ("v-1", "v-2", 3, 1))
        self.assertEqual(res.load(ns2), moved)
        before = self.raw(rpath)
        sn.load(g2)
        self.assertEqual(self.raw(rpath), before)

    def test_results_saved_on_old_version_after_set_moved_are_moved_on_read(self):
        sn.save(self.ns)
        doc = results_for(self.ns, self.g1)
        ns2 = sn.load(graph("v-2", shift=10))
        rpath = res.save(doc, None)  # 판 이전 뒤 옛 판 결과가 다시 저장된 경우(화면이 옛 사본을 들고 있었음)
        got = res.load(ns2)
        self.assertFalse(res.is_stale(got, ns2))
        self.assertEqual(text_of(got), text_of(doc))
        with open(rpath, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["study_nodes_ref"]["graph_version"], "v-1")

    def test_results_of_other_confirmation_stay_stale(self):
        doc = results_for(self.ns, self.g1)
        doc["study_nodes_ref"]["confirmed_at"] = "2026-01-01T00:00:00Z"
        ns2, _ = migrate.migrate_set(self.ns, graph("v-2", shift=10), at=AT)
        self.assertEqual(migrate.migrate_results(doc, ns2), (doc, None))

    def test_old_files_without_refs(self):
        legacy = copy.deepcopy(self.ns)
        del legacy["member_refs"], legacy["member_digest"]
        path = sn.save(legacy)
        doc = results_for(self.ns, self.g1)
        res.save(doc, None)
        self.assertEqual(res.load(legacy), doc)
        g2 = graph("v-2", shift=10)
        self.assertEqual(sn.load(g2), legacy)  # 참조가 없으면 판 이전하지 않음(재확인)
        self.assertEqual(migrate.plan(legacy, g2)["state"], "recheck")
        filled = sn.load(self.g1)  # 판이 같을 때 읽으면 참조를 채워 둔다
        self.assertEqual((filled["member_refs"], filled["member_digest"]),
                         (self.ns["member_refs"], self.ns["member_digest"]))
        self.assertEqual({k: v for k, v in filled.items() if k not in ("member_refs", "member_digest")}, legacy)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("member_refs", json.load(fh))
        self.assertEqual(sn.load(g2)["graph_version"], "v-2")

    def test_graph_stub_without_nodes_writes_nothing(self):
        path = sn.save(self.ns)
        before = self.raw(path)
        self.assertEqual(sn.load({"graph_id": "graph-T", "project_id": None}), self.ns)
        self.assertEqual(self.raw(path), before)

    def test_digest_handles_missing_values(self):
        g = {"graph_id": "g", "nodes": [{"entity_id": "a", "kind": None, "tag": None, "flow_direction": None},
                                        {"entity_id": "b", "kind": "x", "tag": "T", "flow_direction": {"from": "a"}}],
             "edges": [{"kind": None, "nodes": ["a", "b"]}, {"kind": "k", "nodes": ["b", "a"]}]}
        self.assertEqual(migrate.member_digest(g), migrate.member_digest(dict(g, nodes=g["nodes"][::-1])))

    def test_project_graph_refs(self):
        sheet_node = {"entity_id": "graph-A/entity-node-001", "sheet": "graph-A", "source_object_id": "c7"}
        link = {"entity_id": "xlink-abc", "sheet": None, "sheet_link": {"link_id": "xlink-abc"}}
        self.assertEqual(migrate.ref_of(sheet_node, "project-P"), "graph-A#c7")
        self.assertEqual(migrate.ref_of(link, "project-P"), "xlink-abc")
        self.assertIsNone(migrate.ref_of({"entity_id": "x"}, "project-P"))


if __name__ == "__main__":
    unittest.main()
