"""④ 검토구간 데이터 모델(hazop.study.nodes) 시험. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다."""

import codecs
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from hazop import paths  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402

AT = "2026-11-07T00:00:00Z"


def _node(eid, kind, category, tag=None, position=(0.0, 0.0), **kw):
    d = {"entity_id": eid, "node_type": "pipe_segment" if category == "pipe_segment" else "drawing_object",
         "kind": kind, "category": category, "tag": tag, "label_text": tag or "",
         "position": list(position) if position else None}
    d.update(kw)
    return d


def synthetic_graph():
    """탱크 E1 - 밸브 7개 직렬 - 펌프 P1. 계기: E1 액위(LT1→LI1), 배관 유량(FT1), 연결 없는 계기 2개(위치 있음/없음)."""
    nodes = [_node("n-E1", "tank", "equipment", "TK-01", (0, 0)),
             _node("n-P1", "pump", "equipment", "PP-01", (900, 0))]
    edges = []
    chain = ["n-E1"] + ["n-V%d" % i for i in range(1, 8)] + ["n-P1"]
    for i in range(1, 8):
        nodes.append(_node("n-V%d" % i, "manual_valve", "valve", "V-%d" % i, (100 * i, 0)))
    for i in range(1, 9):
        seg = "s-%d" % i
        nodes.append(_node(seg, "pipe_segment", "pipe_segment", "L-01", (100 * i - 50, 0), line_no="L-01"))
        for end in (chain[i - 1], chain[i]):
            edges.append({"entity_id": "r-%s-%s" % (seg, end), "kind": "has_endpoint", "nodes": [seg, end]})
    nodes += [_node("n-LT1", "transmitter", "instrument", "LT-1", (0, -50)),
              _node("n-LI1", "indicator", "instrument", "LI-1", (0, -100)),
              _node("n-FT1", "transmitter", "instrument", "FT-1", (150, -50)),
              _node("n-TI9", "indicator", "instrument", "TI-9", (700, 300)),
              _node("n-TI0", "indicator", "instrument", "TI-0", None)]
    edges += [{"entity_id": "m1", "kind": "measurement_connection", "nodes": ["n-E1", "n-LT1"]},
              {"entity_id": "g1", "kind": "signal_connection", "nodes": ["n-LT1", "n-LI1"]},
              {"entity_id": "m2", "kind": "measurement_connection", "nodes": ["s-2", "n-FT1"]}]
    return {"project_id": None, "graph_id": "graph-T", "graph_version": "v-1",
            "source": {"drawing_number": "T-1"}, "nodes": nodes, "edges": edges}


def active_count(node, graph):
    by = {n["entity_id"]: n for n in graph["nodes"]}
    return sum(sn.is_active(by[m]) for m in node["members"])


def node_named(node_set, entity_id):
    ids = sn.nodes_of(node_set, entity_id)
    return next(n for n in node_set["nodes"] if n["node_id"] == ids[0])


class ProposeTest(unittest.TestCase):
    def setUp(self):
        self.g = synthetic_graph()
        self.s = sn.propose(self.g, at=AT)

    def test_full_coverage_and_active_limit(self):
        cov = sn.coverage(self.s, self.g)
        self.assertEqual((cov["covered"], cov["total"], cov["uncovered"], cov["ratio"]),
                         (len(self.g["nodes"]), len(self.g["nodes"]), [], 1.0))
        for n in self.s["nodes"]:
            self.assertLessEqual(active_count(n, self.g), sn.MAX_ACTIVE, n["node_id"])
        self.assertEqual(self.s["status"], "proposed")
        self.assertEqual([n["node_id"] for n in self.s["nodes"]], ["S%d" % i for i in range(1, len(self.s["nodes"]) + 1)])

    def test_equipment_is_its_own_boundary(self):
        tank = node_named(self.s, "n-E1")
        self.assertEqual(sn.nodes_of(self.s, "n-E1"), [tank["node_id"]])
        self.assertNotIn("n-V1", tank["members"])
        self.assertNotEqual(sn.nodes_of(self.s, "n-P1"), sn.nodes_of(self.s, "n-V7"))

    def test_long_path_is_split_in_connection_order(self):
        first, second = node_named(self.s, "n-V1"), node_named(self.s, "n-V7")
        self.assertNotEqual(first["node_id"], second["node_id"])
        self.assertEqual(active_count(first, self.g), 5)
        self.assertEqual(active_count(second, self.g), 2)
        self.assertIn("n-V5", first["members"])
        self.assertIn("n-V6", second["members"])

    def test_instruments_attach_by_link_then_position_then_other(self):
        self.assertEqual(sn.nodes_of(self.s, "n-LI1"), sn.nodes_of(self.s, "n-E1"))
        self.assertEqual(sn.nodes_of(self.s, "n-FT1"), sn.nodes_of(self.s, "s-2"))
        self.assertEqual(sn.nodes_of(self.s, "n-TI9"), sn.nodes_of(self.s, "n-V7"))
        other = node_named(self.s, "n-TI0")
        self.assertEqual((other["name"], other["members"]), (sn.OTHER_NAME, ["n-TI0"]))

    def test_deterministic_regardless_of_input_order(self):
        shuffled = synthetic_graph()
        rnd = random.Random(7)
        rnd.shuffle(shuffled["nodes"])
        rnd.shuffle(shuffled["edges"])
        self.assertEqual(sn.propose(shuffled, at=AT), self.s)

    def test_real_sample_drawing_is_fully_covered(self):
        import test_kg
        g = test_kg.pid_graph()
        s = sn.propose(g, at=AT)
        self.assertEqual(sn.coverage(s, g)["ratio"], 1.0)
        self.assertEqual(s["graph_version"], g["graph_version"])
        self.assertEqual(s["drawing_number"], "SNP-M-102")


class EditTest(unittest.TestCase):
    def setUp(self):
        self.g = synthetic_graph()
        self.s = sn.propose(self.g, at=AT)

    def test_merge_unions_members_and_keeps_first_id(self):
        a, b = sn.nodes_of(self.s, "n-E1")[0], sn.nodes_of(self.s, "n-P1")[0]
        merged = sn.merge(self.s, [b, a], at=AT)
        self.assertEqual(len(merged["nodes"]), len(self.s["nodes"]) - 1)
        self.assertEqual(sn.nodes_of(merged, "n-E1"), sn.nodes_of(merged, "n-P1"))
        node = node_named(merged, "n-P1")
        self.assertEqual(node["origin"], "merged")
        self.assertEqual(merged["history"][-1]["op"], "merge")
        self.assertEqual(sn.coverage(merged, self.g)["ratio"], 1.0)
        self.assertEqual(len(self.s["history"]), 1, "input not mutated")
        with self.assertRaises(ValueError):
            sn.merge(self.s, [a])
        with self.assertRaises(ValueError):
            sn.merge(self.s, [a, "S999"])

    def test_split_moves_members_to_new_node(self):
        src = node_named(self.s, "n-V1")
        out = sn.split(self.s, src["node_id"], ["n-V1", "s-1"], name="앞쪽", at=AT)
        new_id = sn.nodes_of(out, "n-V1")[0]
        self.assertNotEqual(new_id, src["node_id"])
        self.assertEqual(sn.nodes_of(out, "s-1"), [new_id])
        self.assertIn("n-V2", node_named(out, "n-V2")["members"])
        self.assertEqual(sn.nodes_of(out, "n-V2"), [src["node_id"]])
        new = node_named(out, "n-V1")
        self.assertEqual((new["name"], new["origin"], new["members"]), ("앞쪽", "split", ["n-V1", "s-1"]))
        ids = [n["node_id"] for n in out["nodes"]]
        self.assertEqual(ids.index(new_id), ids.index(src["node_id"]) + 1)
        with self.assertRaises(ValueError):
            sn.split(self.s, src["node_id"], src["members"])
        with self.assertRaises(ValueError):
            sn.split(self.s, src["node_id"], ["n-E1"])

    def test_rename_and_member_edits(self):
        nid = sn.nodes_of(self.s, "n-E1")[0]
        out = sn.rename(self.s, nid, "  탱크  ", at=AT)
        self.assertEqual(node_named(out, "n-E1")["name"], "탱크")
        out = sn.add_member(out, nid, "n-V1", at=AT)
        self.assertEqual(len(sn.nodes_of(out, "n-V1")), 2)
        out = sn.remove_member(out, nid, "n-V1", at=AT)
        self.assertEqual(len(sn.nodes_of(out, "n-V1")), 1)
        self.assertEqual([h["op"] for h in out["history"]], ["propose", "rename", "add", "remove"])

    def test_confirm_refuses_uncovered_empty_and_stale(self):
        nid = sn.nodes_of(self.s, "n-TI0")[0]
        emptied = sn.add_member(sn.remove_member(self.s, nid, "n-TI0", at=AT), sn.nodes_of(self.s, "n-E1")[0], "n-TI0")
        with self.assertRaisesRegex(ValueError, "빈 구간"):
            sn.confirm(emptied, self.g, "검토자", at=AT)
        pump = sn.nodes_of(self.s, "n-P1")[0]
        dropped = sn.remove_member(sn.add_member(self.s, pump, "n-V1"), pump, "n-P1")
        self.assertEqual(sn.coverage(dropped, self.g)["uncovered"], ["n-P1"])
        with self.assertRaisesRegex(ValueError, "어느 구간에도 없는"):
            sn.confirm(dropped, self.g, "검토자", at=AT)
        newer = dict(self.g, graph_version="v-2")
        self.assertTrue(sn.is_stale(self.s, newer))
        with self.assertRaisesRegex(ValueError, "그래프 판"):
            sn.confirm(self.s, newer, "검토자", at=AT)
        with self.assertRaises(ValueError):
            sn.confirm(self.s, self.g, "  ", at=AT)

    def test_confirm_locks_until_reopen(self):
        done = sn.confirm(self.s, self.g, "김검토", at=AT)
        self.assertEqual((done["status"], done["confirmed_by"], done["confirmed_at"]), ("confirmed", "김검토", AT))
        nid = done["nodes"][0]["node_id"]
        with self.assertRaises(ValueError):
            sn.rename(done, nid, "x")
        again = sn.reopen(done, at=AT)
        self.assertEqual((again["status"], again["confirmed_by"]), ("proposed", None))
        self.assertEqual(sn.rename(again, nid, "x")["nodes"][0]["name"], "x")
        self.assertEqual([h["op"] for h in again["history"]], ["propose", "confirm", "reopen"])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    def test_round_trip_and_any_confirmed(self):
        g = synthetic_graph()
        self.assertIsNone(sn.load(g))
        self.assertFalse(sn.any_confirmed())
        s = sn.propose(g, at=AT)
        path = sn.save(s)
        self.assertEqual(path, os.path.join(self.tmp, "데이터", "검토구간", "SNP-SAMPLE", "graph-T.json"))
        self.assertEqual(sn.load(g), s)
        self.assertFalse(sn.any_confirmed())
        sn.save(sn.confirm(s, g, "김검토", at=AT))
        self.assertTrue(sn.any_confirmed())
        self.assertEqual(sn.load(g)["status"], "confirmed")
        self.assertEqual(os.listdir(os.path.dirname(path)), ["graph-T.json"])

    def test_saved_set_from_older_graph_is_stale(self):
        g = synthetic_graph()
        sn.save(sn.propose(g, at=AT))
        newer = dict(g, graph_version="v-2")
        self.assertTrue(sn.is_stale(sn.load(newer), newer))

    def test_broken_file_is_not_confirmed_and_load_rejects_foreign_kind(self):
        g = synthetic_graph()
        path = sn.store_path(None, "graph-T")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"kind": "other"}, fh)
        with open(os.path.join(os.path.dirname(path), "broken.json"), "w", encoding="utf-8") as fh:
            fh.write("{")
        self.assertFalse(sn.any_confirmed())
        with self.assertRaises(ValueError):
            sn.load(g)


    def test_save_refuses_when_file_changed_since_read(self):
        g = synthetic_graph()
        path = sn.store_path(None, "graph-T")
        self.assertIsNone(sn.fingerprint(path))
        mine = sn.propose(g, at=AT)
        theirs = sn.rename(mine, "S1", "다른 창")
        seen = sn.fingerprint(path)
        sn.save(theirs, expect=seen)
        with open(path, "rb") as fh:
            written = fh.read()
        with self.assertRaises(sn.Conflict):
            sn.save(sn.rename(mine, "S2", "늦은 창"), expect=seen)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), written, "거절하면 쓰지 않음")
        sn.save(sn.rename(theirs, "S2", "이어서"), expect=sn.fingerprint(path))
        self.assertEqual(sn.load(g)["nodes"][1]["name"], "이어서")

    def test_load_accepts_bom_and_rejects_broken_shape(self):
        g = synthetic_graph()
        s = sn.propose(g, at=AT)
        path = sn.save(s)
        with open(path, "rb") as fh:
            raw = fh.read()
        with open(path, "wb") as fh:
            fh.write(codecs.BOM_UTF8 + raw)
        self.assertEqual(sn.load(g), s)
        for broken in ({"members": None}, {"node_id": 3}, "S1"):
            doc = json.loads(raw.decode("utf-8"))
            if isinstance(broken, dict):
                doc["nodes"][0].update(broken)
            else:
                doc["nodes"][0] = broken
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                sn.load(g)
        doc = json.loads(raw.decode("utf-8"))
        for n in doc["nodes"]:
            del n["members"]
        doc["status"] = "confirmed"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        with self.assertRaises(ValueError):
            sn.load(g)

if __name__ == "__main__":
    unittest.main()
