"""다시 추출 뒤 찾지 못한 구성요소(구간의 lost 묘비)를 사람이 확인하고 버리기(nodes.discard_lost). 실행:
python -m unittest tests.test_study_discard_lost

재현: 다시 추출에서 V1을 지우고 같은 자리에 V1B를 새로 그린 도면. 판 이전이 S1의 V1을 묘비로 두고, 사람이 V1B를 S1에 다시
골라도 '찾지 못한 구성요소 1개'가 남는다(묘비를 닫는 길이 없었음).
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.study import idmap, migrate, node_commands, node_tools  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_migrate import AT, DEVS, OBJECTS, PIPES, graph  # noqa: E402

REDRAWN = [o for o in OBJECTS if o[0] != "V1"] + [("V1B", "manual_valve", "valve")]
REPIPED = [("L1", "TK", "V1B"), ("L2", "V1B", "V2"), ("L3", "V2", "PP")]


def eid(g, soid):
    return next(n["entity_id"] for n in g["nodes"] if n["source_object_id"] == soid)


def lost_world(extra_lost=False):
    """(g1, g2, 판 이전한 집합). S1 = TK·V1·V2(+V1·V2 사이 배관), S2 = V2·PP. g2에서 V1은 사라지고 V1B가 새로 생긴다.
    extra_lost면 g2에서 V2도 지워 S1에 묘비가 둘, S2에 하나 생긴다."""
    g1 = graph("v1")
    objs = [o for o in REDRAWN if not (extra_lost and o[0] == "V2")]
    pipes = [p for p in REPIPED if not (extra_lost and "V2" in p[1:])]
    g2 = graph("v2", objects=objs, pipes=pipes)
    ns = sn.new_set(g1)
    ns["nodes"] = [
        dict({"node_id": "S1", "name": "탱크 출구", "basis": "b",
              "members": sorted([eid(g1, "TK"), eid(g1, "V1"), eid(g1, "V2"), eid(g1, "L2")])}, **sn._v2_fields("user")),
        dict({"node_id": "S2", "name": "펌프", "basis": "b", "members": sorted([eid(g1, "V2"), eid(g1, "PP")])},
             **sn._v2_fields("user"))]
    ns.update(idmap.snapshot(g1))
    ns2, plan = migrate.migrate_set(ns, g2, at=AT)
    assert plan["state"] == "kept", plan
    return g1, g2, ns2


def node(ns, nid):
    return next(n for n in ns["nodes"] if n["node_id"] == nid)


class DiscardLostTest(unittest.TestCase):
    def test_repicking_the_redrawn_component_leaves_the_lost_count_until_it_is_discarded(self):
        _g1, g2, ns = lost_world()
        self.assertEqual(idmap.needs_check(ns)["lost_members"], {"S1": 1})
        node_set_rev = ns["set_rev"]
        picked, _res, _bid = node_tools.apply_nodes(ns, None, g2, [{"op": "edit", "node_id": "S1", "add": [eid(g2, "V1B")]}],
                                                    {}, "user", node_set_rev)
        self.assertEqual(idmap.needs_check(picked)["lost_members"], {"S1": 1}, "다시 골라도 묘비는 스스로 닫히지 않음")
        out = sn.discard_lost(picked, "S1", by="김검토", at="t1")
        check = idmap.needs_check(out)
        self.assertEqual(check["lost_members"], {})
        self.assertFalse(check["needs_check"])
        self.assertEqual(check["tombstones"], 0)
        self.assertEqual(check["discarded"], {"S1": 1})

    def test_discard_one_of_several_keeps_the_rest_and_records_who_when_what(self):
        g1, _g2, ns = lost_world(extra_lost=True)
        tombs = node(ns, "S1")["lost"]
        self.assertEqual(len(tombs), 3, "V1·V2와 V1B·V2 사이 배관")
        first = tombs[0]
        out = sn.discard_lost(ns, "S1", [first], by="김검토", at="t1")
        self.assertEqual(node(out, "S1")["lost"], tombs[1:])
        self.assertEqual(node(out, "S1")["discarded"], [first])
        self.assertEqual(idmap.needs_check(out)["lost_members"], {"S1": 2, "S2": 1})
        row = out["history"][-1]
        self.assertEqual((row["op"], row["at"]), ("discard_lost", "t1"))
        d = row["detail"]
        self.assertEqual((d["node_id"], d["by"], d["left"]), ("S1", "김검토", 2))
        rec = ns["tombstones"][first]
        self.assertEqual(d["tombs"], [{"tomb": first, "entity_id": rec["entity_id"], "ref": rec["ref"],
                                       "name": idmap.tomb_name(rec)}])
        self.assertEqual(d["tombs"][0]["name"], rec["ref"], "source 구성요소의 표시 이름은 잃기 전 판의 참조")
        self.assertEqual(out["batches"][-1]["kind"], "discard_lost")
        self.assertEqual(node(out, "S1")["rev"], node(ns, "S1")["rev"], "분석 입력이 아니라 rev는 그대로")
        self.assertEqual(ns["tombstones"], out["tombstones"], "묘비 기록은 지우지 않음")

    def test_discard_all_and_repeat_is_the_same(self):
        _g1, _g2, ns = lost_world(extra_lost=True)
        out = sn.discard_lost(ns, "S1", by="김검토", at="t1")
        self.assertNotIn("lost", node(out, "S1"))
        self.assertEqual(len(node(out, "S1")["discarded"]), 3)
        self.assertIs(sn.discard_lost(out, "S1", by="김검토", at="t2"), out, "버릴 것이 없으면 그대로")
        self.assertIs(sn.discard_lost(out, "S1", node(out, "S1")["discarded"], by="김검토", at="t2"), out)

    def test_broken_input_is_refused(self):
        _g1, _g2, ns = lost_world(extra_lost=True)
        s2_tomb = node(ns, "S2")["lost"][0]
        s1_only = [t for t in node(ns, "S1")["lost"] if t not in node(ns, "S2")["lost"]][0]
        cases = [("S1", ["lost:graph-T:v2:t-000000000000"], "없는 묘비"),
                 ("S2", [s1_only], "다른 구간"),
                 ("S9", None, "없는 검토구간"),
                 ("S1", [], "버릴 묘비")]
        for nid, tombs, why in cases:
            with self.assertRaises(ValueError, msg=why) as cm:
                sn.discard_lost(ns, nid, tombs, by="김검토")
            self.assertIn(why, str(cm.exception))
        with self.assertRaises(ValueError):
            sn.discard_lost(ns, "S1", by=" ")
        self.assertIn(s2_tomb, node(ns, "S1")["lost"], "겹친 구간의 같은 묘비는 S1에서도 버릴 수 있음")

    def test_confirmed_and_locked_nodes_refuse(self):
        _g1, g2, ns = lost_world()
        done = sn.confirm_nodes(ns, g2, ["S1"], "김검토", at="t1")
        with self.assertRaises(ValueError) as cm:
            sn.discard_lost(done, "S1", by="김검토")
        self.assertIn("확정", str(cm.exception))

    def test_undo_brings_the_tomb_back(self):
        _g1, _g2, ns = lost_world()
        out = sn.discard_lost(ns, "S1", by="김검토", at="t1")
        back, _ = node_tools.undo_batch(out, {"cells": []}, out["batches"][-1]["batch_id"], out["set_rev"], "김검토", "user", at="t2")
        self.assertEqual(node(back, "S1")["lost"], node(ns, "S1")["lost"])
        self.assertNotIn("discarded", node(back, "S1"))
        self.assertEqual(idmap.needs_check(back)["lost_members"], {"S1": 1})

    def test_a_discarded_tomb_is_not_recovered_but_an_open_one_is(self):
        def seq(g, shift=0):
            """벡터 PDF처럼 순번 id와 상자를 단 그래프(표시로 되찾을 수 있게). shift는 다시 매긴 순번."""
            g = copy.deepcopy(g)
            spot = {soid: 10.0 * i for i, (soid, _k, _c) in enumerate(OBJECTS)}
            for i, n in enumerate(g["nodes"]):
                n["id_basis"] = "sequence"
                if n["source_object_id"] in spot:
                    n["bbox"] = [spot[n["source_object_id"]], 0.0, 5.0, 5.0]
                n["source_object_id"] = "pdf-p0-sym-%04d" % (i + shift)
            return g
        g1 = seq(graph("v1"))
        g2 = seq(graph("v2", objects=[o for o in OBJECTS if o[0] not in ("V1", "V2")], pipes=[]), shift=50)
        ns = sn.new_set(g1)
        ns["nodes"] = [dict({"node_id": "S1", "name": "n", "basis": "b",
                             "members": sorted(n["entity_id"] for n in g1["nodes"] if n["tag"] in ("TK", "V1", "V2"))},
                            **sn._v2_fields("user"))]
        ns.update(idmap.snapshot(g1))
        ns, _ = migrate.migrate_set(ns, g2, at="t1")
        tombs = {ns["tombstones"][t]["mark"][3]: t for t in node(ns, "S1")["lost"]}
        self.assertEqual(sorted(tombs), ["V1", "V2"])
        out = sn.discard_lost(ns, "S1", [tombs["V1"]], by="김검토", at="t2")
        g3 = seq(graph("v1"), shift=100)  # 앞 판 내용으로 되돌아감: V1·V2가 같은 자리에 다시 나온다
        g3["graph_version"] = "v3"
        back, _plan = migrate.migrate_set(out, g3, at="t3")
        found = {t for t, r in back["tombstones"].items() if r.get("found")}
        self.assertEqual(found, {tombs["V2"]}, "열린 묘비만 되찾고 사람이 버린 묘비는 되찾지 않음")
        self.assertNotIn("lost", node(back, "S1"))
        self.assertEqual(node(back, "S1")["discarded"], [tombs["V1"]])
        v2 = next(n["entity_id"] for n in g3["nodes"] if n["tag"] == "V2")
        v1 = next(n["entity_id"] for n in g3["nodes"] if n["tag"] == "V1")
        self.assertIn(v2, node(back, "S1")["members"])
        self.assertNotIn(v1, node(back, "S1")["members"])
        still = [t for t, r in back["tombstones"].items() if r.get("found") is None]  # 구간 밖에서 잃은 배관도 묘비
        self.assertIn(tombs["V1"], still)
        self.assertEqual(idmap.needs_check(back)["tombstones"], len(still) - 1, "버린 묘비는 되찾지 못한 수에서 빠짐")


class ResultsRefsTest(unittest.TestCase):
    def test_results_refs_to_a_discarded_tomb_stay_and_are_counted_as_discarded(self):
        _g1, _g2, ns = lost_world()
        tomb = node(ns, "S1")["lost"][0]
        doc = res.empty_results(ns, DEVS)
        doc["cells"] = [{"node_id": "S1", "deviation_id": "D01", "state": "analyzed",
                         "entries": [{"entry_id": "e1", "status": "approved", "cause": "V1 닫힘",
                                      "cause_refs": [{"ref": tomb}], "consequence_refs": [], "safeguards": []}]}]
        out = sn.discard_lost(ns, "S1", by="김검토", at="t1")
        check = idmap.needs_check(out, doc)
        self.assertEqual(check["lost_refs"], {"S1": 1}, "⑤ 항목의 대상은 사람이 고칠 몫이라 남는다")
        self.assertEqual(check["discarded_refs"], {"S1": 1})
        self.assertTrue(check["needs_check"])
        self.assertEqual(doc["cells"][0]["entries"][0]["cause_refs"], [{"ref": tomb}])
        gone = idmap.discarded_tombs(out)
        self.assertEqual(idmap.label(tomb, discarded=gone), idmap.DISCARDED_LABEL)
        self.assertEqual(idmap.label(tomb), idmap.LOST_LABEL)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def saved(self):
        _g1, g2, ns = lost_world(extra_lost=True)
        sn.save(ns)
        return g2, ns

    def test_command_discards_by_key_and_saves_with_backup_path(self):
        g2, ns = self.saved()
        items = sn.lost_items(ns, "S1")
        self.assertEqual(len(items), 3)
        self.assertTrue(all(not it["key"].startswith("lost:") and "lost:" not in str(it) for it in items), items)
        out = node_commands.execute(g2, "discard_lost", {"node_id": "S1", "keys": [items[0]["key"]]}, author="user",
                                    confirmed_by="김검토", set_rev=ns["set_rev"])
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["changed"], out["node_ids"]), (True, ["S1"]))
        self.assertIsNotNone(out["batch_id"])
        disk, _fp = sn.load_fp(g2)
        self.assertEqual(len(node(disk, "S1")["lost"]), 2)
        self.assertEqual(disk["history"][-1]["detail"]["by"], "김검토")
        again = node_commands.execute(g2, "discard_lost", {"node_id": "S1"}, author="user", confirmed_by="김검토",
                                      set_rev=disk["set_rev"])
        self.assertTrue(again["ok"], again)
        disk, _fp = sn.load_fp(g2)
        self.assertNotIn("lost", node(disk, "S1"))

    def test_command_refuses_ai_unknown_keys_and_missing_name(self):
        g2, ns = self.saved()
        ai = node_commands.execute(g2, "discard_lost", {"node_id": "S1"}, author="ai", set_rev=ns["set_rev"])
        self.assertEqual((ai["ok"], ai["refused"][0]["code"]), (False, "bad_actor"))
        bad = node_commands.execute(g2, "discard_lost", {"node_id": "S1", "keys": ["L-nope"]}, author="user",
                                    confirmed_by="김검토")
        self.assertFalse(bad["ok"])
        self.assertIn("없는 묘비", bad["refused"][0]["reason"])
        nobody = node_commands.execute(g2, "discard_lost", {"node_id": "S1"}, author="user")
        self.assertEqual(nobody["refused"][0]["code"], "bad_actor")
        disk, _fp = sn.load_fp(g2)
        self.assertEqual(disk, sn.load_fp(g2)[0])
        self.assertEqual(len(node(disk, "S1")["lost"]), 3, "거절하면 저장하지 않음")

    def test_saved_set_with_discarded_passes_the_shape_check(self):
        g2, ns = self.saved()
        out = sn.discard_lost(ns, "S1", by="김검토", at="t1")
        sn.save(out)
        disk, _fp = sn.load_fp(g2)
        self.assertEqual(node(disk, "S1")["discarded"], node(out, "S1")["discarded"])
        broken = copy.deepcopy(out)
        node(broken, "S1")["discarded"] = ["entity-node-001"]
        with self.assertRaises(ValueError):
            sn._check_shape(broken, "x")


if __name__ == "__main__":
    unittest.main()
