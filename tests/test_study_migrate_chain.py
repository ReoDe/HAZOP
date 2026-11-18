"""판 이전을 여러 번 잇는 길의 재현 시험(M2 검토 차단 1~5와 경미 지적). 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
- 차단 1: 같은 판으로 두 번 와도(X→Y, Y→Z, Z→Y) 묘비 id 하나는 기호 하나다.
- 차단 2: 앞 판으로 돌아온 뒤(A→B→A) 그 판에서 새로 단 ⑤ 참조는 읽을 때 옮기지 않는다.
- 차단 3: 프로젝트 그래프에서 한 도면만 다시 추출해도 도면 연결 구간과 상자 없는 배관 구간은 끝으로 이어진다.
- 차단 4: 결과가 늦게 따라와도(집합 저장 뒤 결과 저장 실패) 즉시 옮긴 것과 같다.
- 차단 5: 다시 추출 전에 받은 구간 AI 검토 제안은 오래됨이다.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.kg import expect  # noqa: E402
from hazop.study import idmap, migrate, node_review as nr, refs  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from tests.test_study_idmap import drawing  # noqa: E402

G = "graph-T"


def sym(i, uid, kind, box, tag=None, sheet_ids=False):
    return {"entity_id": "entity-node-%03d" % i, "source_object_id": "pdf-p0-sym-%04d" % i, "node_type": "drawing_object",
            "kind": kind, "tag": tag, "bbox": box, "id_basis": "sequence", "_uid": uid}


def graph(version, syms):
    return {"project_id": None, "graph_id": G, "graph_version": version, "edges": [],
            "nodes": [sym(i + 1, *s) for i, s in enumerate(syms)]}


def add_node(ns, nid, members):
    ns["nodes"].append(dict({"node_id": nid, "name": nid, "basis": "b", "members": members}, **sn._v2_fields("script")))
    return ns


def uid_of(g, eid):
    return next(n["_uid"] for n in g["nodes"] if n["entity_id"] == eid)


def entry(cause=(), consequence=(), kg=()):
    return {"cause_refs": [{"ref": r} for r in cause], "consequence_refs": [{"ref": r} for r in consequence],
            "safeguards": [], "expectation_refs": [expect.expectation_id("R-1", r) for r in cause],
            "ai_basis": {"kg_paths": [list(kg)]}}


def results(version, entries):
    return {"schema_version": "0.3", "graph_id": G, "graph_version": version,
            "cells": [{"node_id": "S1", "entries": list(entries)}]}


class WorkRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp)


P = ("p", "pump", [0, 0, 5, 5])
Q = ("q", "manual_valve", [40, 0, 5, 5])
W = ("w", "check_valve", [80, 0, 5, 5])


class TombIdTest(WorkRoot):
    def test_returning_to_a_version_never_reuses_a_tomb_id(self):
        """X(p,q) → Y(q) → Z(q,w) → Y → Z: p와 w는 둘 다 Y에서 잃지만 묘비가 다르고, 돌아온 w는 w의 구간에만 들어간다."""
        gx, gy, gz = graph("vX", [P, Q]), graph("vY", [Q]), graph("vZ", [Q, W])
        ns = sn.confirm_nodes(add_node(add_node(sn.new_set(gx), "S1", ["entity-node-001"]), "S2", ["entity-node-002"]),
                              gx, ["S1", "S2"], "x", at="t")
        ns, _ = migrate.migrate_set(ns, gy, at="t1")
        pump_tomb = ns["nodes"][0]["lost"][0]
        first = copy.deepcopy(ns["tombstones"][pump_tomb])
        ns, _ = migrate.migrate_set(ns, gz, at="t2")
        ns = add_node(ns, "S3", [next(n["entity_id"] for n in gz["nodes"] if n["_uid"] == "w")])
        ns, _ = migrate.migrate_set(ns, gy, at="t3")
        ns, _ = migrate.migrate_set(ns, gz, at="t4")
        by = {n["node_id"]: n for n in ns["nodes"]}
        self.assertEqual([uid_of(gz, m) for m in by["S1"]["members"]], [], "펌프 구간에 체크밸브가 들어오지 않음")
        self.assertEqual(by["S1"]["lost"], [pump_tomb])
        self.assertEqual([uid_of(gz, m) for m in by["S3"]["members"]], ["w"], "체크밸브는 제 구간으로 돌아옴")
        self.assertEqual({k: ns["tombstones"][pump_tomb][k] for k in first if k != "found"},
                         {k: v for k, v in first.items() if k != "found"}, "앞 묘비 기록을 덮어쓰지 않음")
        late, _ = migrate.migrate_results(results("vX", [entry(cause=[G + "#pdf-p0-sym-0001"], kg=["entity-node-001"])]), ns)
        e = late["cells"][0]["entries"][0]
        self.assertTrue(idmap.is_tomb(e["cause_refs"][0]["ref"]), "늦게 따라온 펌프 원인 참조는 묘비(체크밸브가 아님)")
        self.assertTrue(idmap.is_tomb(e["ai_basis"]["kg_paths"][0][0]))


class ResultsStepTest(WorkRoot):
    def test_refs_made_after_returning_to_a_version_stay_put(self):
        a = {"project_id": None, "graph_id": G, "graph_version": "vA", "edges": [],
             "nodes": [sym(1, "p", "pump", [0, 0, 5, 5]), sym(2, "t", "tank", None)]}
        b = {"project_id": None, "graph_id": G, "graph_version": "vB", "edges": [], "nodes": [sym(1, "p", "pump", [0, 0, 5, 5])]}
        ns = sn.confirm_nodes(add_node(sn.new_set(a), "S1", ["entity-node-001"]), a, ["S1"], "x", at="t")
        ns, _ = migrate.migrate_set(ns, b, at="t1")
        ns, _ = migrate.migrate_set(ns, a, at="t2")
        fresh = results("vA", [entry(cause=[G + "#pdf-p0-sym-0001"], consequence=[G + "#pdf-p0-sym-0002"],
                                     kg=["entity-node-001", "entity-node-002"])])
        out, n = migrate.migrate_results(fresh, ns)
        self.assertEqual((out, n), (fresh, None), "같은 판에서 단 참조는 그대로(이력의 A→B→A를 다시 거치지 않음)")

    def test_results_moved_once_are_not_moved_again_after_a_round_trip(self):
        a, b = drawing("v-a"), drawing("v-b", order=("V1", "TK", "V2", "PP"))
        ns = sn.confirm_nodes(add_node(sn.new_set(a), "S1", ["entity-node-001"]), a, ["S1"], "x", at="t")
        res = results("v-a", [entry(cause=[G + "#pdf-p0-sym-0001"], kg=["entity-node-001"])])
        ns, p = migrate.migrate_set(ns, b, at="t1")
        res, _ = migrate.migrate_results(res, ns, table=p["table"])
        ns, p = migrate.migrate_set(ns, a, at="t2")
        res, _ = migrate.migrate_results(res, ns, table=p["table"])
        self.assertEqual(res["cells"][0]["entries"][0]["cause_refs"][0]["ref"], G + "#pdf-p0-sym-0001", "탱크로 돌아옴")
        self.assertEqual(migrate.migrate_results(res, ns)[0], res, "다시 읽어도 그대로")
        self.assertEqual([m.get("step") for m in res["version_migrations"]], [1, 2])


def sheet(name, version, order, other, direction):
    """벡터 PDF 도면: 연결점(상대 도면으로 가는 배관 L-1)·밸브와 그 둘을 잇는 상자 없는 배관 구간. order로 순번을 섞는다."""
    items = {"K": {"kind": "continuation", "bbox": [0, 0, 5, 5], "label_text": "%s %s\nL-1" % (direction, other),
                   "attributes": {"kind": "continuation"}},
             "V": {"kind": "manual_valve", "bbox": [40, 0, 5, 5], "attributes": {}}}
    nodes, eid = [], {}
    for i, key in enumerate(order, 1):
        eid[key] = "entity-node-%03d" % i
        nodes.append(dict({"entity_id": eid[key], "source_object_id": "pdf-p0-sym-%04d" % i, "node_type": "drawing_object",
                           "tag": None, "id_basis": "sequence", "_uid": name + key}, **items[key]))
    nodes.append({"entity_id": "entity-seg-001", "source_object_id": "pdf-p0-conn-0001", "node_type": "pipe_segment",
                  "kind": "pipe_segment", "tag": None, "bbox": None, "id_basis": "sequence", "_uid": name + "L"})
    edges = [{"entity_id": "relation-%03d" % i, "kind": "has_endpoint", "nodes": ["entity-seg-001", eid[k]]}
             for i, k in enumerate("KV", 1)]
    return {"project_id": "P", "graph_id": "graph-" + name, "graph_version": version, "source": {"drawing_number": name},
            "validation": {"status": "passed"}, "nodes": nodes, "edges": edges}


class SheetLinkTest(WorkRoot):
    def project_graph(self, version_a, order_a):
        return project.build("P", [sheet("A", version_a, order_a, "B", "TO"), sheet("B", "b1", "KV", "A", "FROM")])

    def confirmed(self, pg):
        ns = sn.new_set(pg)
        for i, n in enumerate(sorted(pg["nodes"], key=lambda n: n["entity_id"]), 1):
            add_node(ns, "S%d" % i, [n["entity_id"]])
        return sn.confirm_nodes(ns, pg, [n["node_id"] for n in ns["nodes"]], "x", at="t")

    def test_one_sheet_reextracted_with_same_content_keeps_links_and_confirmation(self):
        pg1 = self.project_graph("a1", "KV")
        pg2 = self.project_graph("a2", "KV")
        self.assertNotEqual(pg1["graph_version"], pg2["graph_version"])
        ns = self.confirmed(pg1)
        out, p = migrate.migrate_set(ns, pg2, at="t1")
        self.assertEqual((p["recheck"], [n.get("lost") for n in out["nodes"] if n.get("lost")]), ({}, []))
        self.assertTrue(all(n["state"] == "confirmed" for n in out["nodes"]))

    def test_renumbered_sheet_moves_the_link_to_its_new_id(self):
        pg1, pg2 = self.project_graph("a1", "KV"), self.project_graph("a2", "VK")
        old_link = next(n["entity_id"] for n in pg1["nodes"] if n["entity_id"].startswith("xlink-"))
        new_link = next(n["entity_id"] for n in pg2["nodes"] if n["entity_id"].startswith("xlink-"))
        self.assertNotEqual(old_link, new_link, "연결점 순번이 바뀌면 연결 구간 id도 바뀜")
        ns = self.confirmed(pg1)
        out, p = migrate.migrate_set(ns, pg2, at="t1")
        truth2 = {n["entity_id"]: n.get("_uid") for n in pg2["nodes"]}
        for before, after in zip(ns["nodes"], out["nodes"]):
            want = [{n["entity_id"]: n.get("_uid") for n in pg1["nodes"]}[m] for m in before["members"]]
            self.assertEqual([truth2[m] for m in after["members"]], want, before["node_id"])
            self.assertNotIn("lost", after)
        self.assertIn(new_link, [m for n in out["nodes"] for m in n["members"]])
        self.assertEqual(p["recheck"], {}, "순번만 다시 매겨진 것은 내용이 바뀐 것이 아님")


class LateResultsTest(WorkRoot):
    def test_late_results_match_immediate_migration(self):
        """옛 판 사진에 없던 이 도면의 참조(새 판에서 다른 기호가 그 번호를 가짐)는 즉시 옮겨도 늦게 옮겨도 묘비다."""
        a = drawing("v-a", gone=("PP",))
        b = drawing("v-b")
        stale = G + "#pdf-p0-sym-0004"   # a에는 없고 b에서는 펌프
        ns = sn.confirm_nodes(add_node(sn.new_set(a), "S1", ["entity-node-001"]), a, ["S1"], "x", at="t")
        res = results("v-a", [entry(cause=[G + "#pdf-p0-sym-0001", stale], kg=["entity-node-001", "entity-node-004"])])
        ns2, p = migrate.migrate_set(ns, b, at="t1")
        now, _ = migrate.migrate_results(res, ns2, at="t1", table=p["table"])
        later, _ = migrate.migrate_results(res, ns2, at="t1")   # 집합만 저장되고 결과 저장이 실패한 뒤 다시 읽음
        self.assertEqual(json.dumps(later, sort_keys=True), json.dumps(now, sort_keys=True))
        e = later["cells"][0]["entries"][0]
        self.assertEqual(e["cause_refs"][0]["ref"], G + "#pdf-p0-sym-0001")
        self.assertTrue(idmap.is_tomb(e["cause_refs"][1]["ref"]))
        self.assertTrue(idmap.is_tomb(e["ai_basis"]["kg_paths"][0][1]))


class ReviewStaleTest(WorkRoot):
    def setUp(self):
        super().setUp()
        self.g1 = {"project_id": None, "graph_id": G, "graph_version": "v1", "edges": [],
                   "nodes": [sym(1, "pump", "pump", [0, 0, 5, 5]), sym(2, "valve", "manual_valve", [40, 0, 5, 5])]}
        self.g2 = {"project_id": None, "graph_id": G, "graph_version": "v2", "edges": [],
                   "nodes": [sym(1, "valve", "manual_valve", [40, 0, 5, 5]), sym(2, "pump", "pump", [0, 0, 5, 5])]}
        self.ns = add_node(sn.new_set(self.g1), "S1", ["entity-node-001", "entity-node-002"])
        self.adj = {"S1": {}}
        fp = nr.input_fingerprint(self.ns["nodes"][0], self.ns, self.adj)
        self.prop = {"id": "R1", "node_id": "S1", "verdict": "split", "split_off": [{"members": ["entity-node-001"],
                     "name": "펌프만"}], "merge_with": [], "screen_to": None, "decision": "open", "input_fp": fp,
                     "graph_version": "v1", "at": "2026-11-18T00:00:00Z"}

    def test_proposal_made_before_reextraction_is_stale(self):
        ns2, _ = migrate.migrate_set(self.ns, self.g2, at="2026-11-18T01:00:00Z")
        self.assertEqual(sorted(ns2["nodes"][0]["members"]), ["entity-node-001", "entity-node-002"], "순번이 맞바뀜")
        self.assertFalse(nr.is_stale(self.prop, self.ns, self.adj))
        self.assertTrue(nr.is_stale(self.prop, ns2, self.adj))
        with self.assertRaises(ValueError):
            nr.accept(ns2, {"proposals": [self.prop]}, "R1", "x", self.adj, at="t")

    def test_old_proposal_without_version_is_stale_after_a_later_migration(self):
        old = {k: v for k, v in self.prop.items() if k != "graph_version"}
        ns2, _ = migrate.migrate_set(self.ns, self.g2, at="2026-11-18T01:00:00Z")
        self.assertFalse(nr.is_stale(old, self.ns, self.adj))
        self.assertTrue(nr.is_stale(old, ns2, self.adj))


class DigestTest(WorkRoot):
    def test_renumbering_alone_keeps_confirmation(self):
        a, b = drawing("v-a"), drawing("v-b", order=("PP", "V2", "V1", "TK"))
        mem = sorted(n["entity_id"] for n in a["nodes"])
        ns = sn.confirm_nodes(add_node(sn.new_set(a), "S1", mem), a, ["S1"], "x", at="t")
        out, p = migrate.migrate_set(ns, b, at="t1")
        self.assertEqual((p["recheck"], out["nodes"][0]["state"]), ({}, "confirmed"))

    def test_changed_position_still_rechecks_after_renumbering(self):
        a = drawing("v-a")
        b = copy.deepcopy(drawing("v-b", order=("PP", "V2", "V1", "TK")))
        next(n for n in b["nodes"] if n.get("_name") == "V1")["attributes"] = {"normal_position": "NC"}
        ns = sn.confirm_nodes(add_node(sn.new_set(a), "S1", sorted(n["entity_id"] for n in a["nodes"])), a, ["S1"], "x", at="t")
        self.assertEqual(migrate.plan(ns, b)["recheck"], {"S1": "구성요소의 종류·태그·흐름·연결·정상 위치·고장 위치가 바뀜"})

    def test_reason_names_lost_components_by_look_not_by_old_id(self):
        a, b = drawing("v-a"), drawing("v-b", gone=("PP",))
        ns = sn.confirm_nodes(add_node(sn.new_set(a), "S1", sorted(n["entity_id"] for n in a["nodes"])), a, ["S1"], "x", at="t")
        why = migrate.plan(ns, b)["recheck"]["S1"]
        self.assertIn("pump P-1", why)
        self.assertNotIn("entity-", why)


class LabelTest(unittest.TestCase):
    def test_lost_expectation_is_shown_without_its_tomb_id(self):
        tomb = idmap.tomb_id(G, "v-b", 1) + idmap.EXP_SEP + "R-1"
        text = " ".join(t for _k, t in refs.lines({"expectation_refs": [tomb]}, {}, None, None, {}))
        self.assertIn(idmap.LOST_LABEL, text)
        self.assertNotIn("lost:", text)


class LegacyConvertTest(WorkRoot):
    def test_01_set_read_on_its_own_version_gets_marks_and_survives_reextraction(self):
        """0.1 집합(표시 없음)을 같은 판 그래프로 처음 읽으면 변환과 함께 판 사진(표시)이 채워져 다음 판 이전에서 잇는다."""
        a, b = drawing("v-a"), drawing("v-b", order=("PP", "V2", "V1", "TK"))
        set01 = {"schema_version": "0.1", "kind": sn.KIND, "project_id": None, "graph_id": G, "graph_version": "v-a",
                 "status": "confirmed", "confirmed_at": "t1", "confirmed_by": "x", "history": [],
                 "nodes": [{"node_id": "S1", "name": "구간", "origin": "rule", "members": ["entity-node-001", "entity-node-002"]}]}
        path = sn.store_path(None, G)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(set01, fh, ensure_ascii=False)
        ns = sn.load(a)
        self.assertEqual(set(ns["graph_member_marks"]), {n["entity_id"] for n in a["nodes"] if n.get("bbox")})
        out, _p = migrate.migrate_set(ns, b, at="t2")
        names = {n["entity_id"]: n["_name"] for n in b["nodes"]}
        self.assertEqual(sorted(names[m] for m in out["nodes"][0]["members"]), ["TK", "V1"])
        self.assertNotIn("lost", out["nodes"][0])


if __name__ == "__main__":
    unittest.main()
