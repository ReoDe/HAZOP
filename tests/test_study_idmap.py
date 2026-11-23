"""판 이전 대응표·등록부(hazop.study.idmap)와 그것을 쓰는 저장 길 시험: 등록부가 새 필드를 놓치지 않음, 옛 꼴(B꼴) 읽기,
저장 규격 판 올림, 원자적 다시 쓰기, 묘비를 지키는 편집. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다."""

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

from hazop import paths, store_io  # noqa: E402
from hazop.kg import expect  # noqa: E402
from hazop.study import idmap, migrate  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402

AT = "2026-11-18T00:00:00Z"
DEVS = [{"deviation_id": "D01", "item_id": "I1", "parameter": "유량", "guideword": "없음", "label": "유량 없음"},
        {"deviation_id": "D02", "item_id": "I2", "parameter": "유량", "guideword": "많음", "label": "유량 많음"}]
SYMBOLS = {"TK": ("tank", "TK-1", [0, 0, 10, 10]), "V1": ("manual_valve", None, [20, 0, 5, 5]),
           "V2": ("manual_valve", None, [40, 0, 5, 5]), "PP": ("pump", "P-1", [80, 0, 10, 10])}
PIPES = [("TK", "V1"), ("V1", "V2"), ("V2", "PP")]


def drawing(version, order=("TK", "V1", "V2", "PP"), gone=()):
    """벡터 PDF처럼 기호 순번이 source_object_id인 도면. order를 바꾸면 순번이 밀린다."""
    nodes, eid = [], {}
    names = [x for x in order if x not in gone]
    for i, name in enumerate(names, 1):
        kind, tag, box = SYMBOLS[name]
        eid[name] = "entity-node-%03d" % i
        nodes.append({"entity_id": eid[name], "node_type": "drawing_object", "kind": kind, "tag": tag, "bbox": box,
                      "source_object_id": "pdf-p0-sym-%04d" % i, "id_basis": "sequence", "_name": name})
    edges, k = [], 0
    for i, (a, b) in enumerate([p for p in PIPES if p[0] in eid and p[1] in eid], 1):
        sid = "entity-seg-%03d" % i
        nodes.append({"entity_id": sid, "node_type": "pipe_segment", "kind": "pipe_segment", "tag": None,
                      "bbox": [SYMBOLS[a][2][0] + 10, 2, 10, 1], "source_object_id": "pdf-p0-conn-%04d" % i,
                      "id_basis": "sequence", "_name": a + "-" + b})
        for x in (a, b):
            k += 1
            edges.append({"entity_id": "relation-%03d" % k, "kind": "has_endpoint", "nodes": [sid, eid[x]]})
    return {"project_id": None, "graph_id": "graph-T", "graph_version": version, "source": {"drawing_number": "T-1"},
            "nodes": nodes, "edges": edges}


def eid(g, name):
    return next(n["entity_id"] for n in g["nodes"] if n["_name"] == name)


def ref(g, name):
    return idmap.ref_of(next(n for n in g["nodes"] if n["_name"] == name), "graph-T")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp)
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
        self.g1 = drawing("v-1")

    def raw(self, path):
        with open(path, "rb") as fh:
            return fh.read()


def full_set(g):
    """등록부의 모든 집합 필드에 값이 든 집합: 제안·분할·병합·빼기(실행 취소 기록), 조각 기록, 경계 힌트, 옛 판 사진."""
    ns = sn.new_set(g)
    every = [n["entity_id"] for n in g["nodes"]]
    ns["nodes"] = [dict({"node_id": "S1", "name": "a", "basis": "b", "members": every[:5]}, **sn._v2_fields("script")),
                   dict({"node_id": "S2", "name": "b", "basis": "b", "members": every[4:]}, **sn._v2_fields("script"))]
    ns = sn.split(ns, "S1", every[:2], at=AT)
    ns = sn.remove_member(ns, "S2", every[-1], at=AT)
    ns = sn.merge(ns, ["S1", "S2"], at=AT)
    node = ns["nodes"][0]
    node["absorbed"] = [{"from": "P1", "members": node["members"][:1], "rule": "R2"}]
    node["parts"] = [{"from": "P2", "members": node["members"][1:2], "rule": "R3"}]
    node["boundary_hint"] = {"from": node["members"][0], "to": node["members"][-1]}
    for b in ns["batches"]:
        for o in b["ops"]:
            for side in ("before", "after"):
                if o[side] is not None:
                    o[side] = dict(o[side], absorbed=copy.deepcopy(node["absorbed"]), parts=copy.deepcopy(node["parts"]),
                                   boundary_hint=dict(node["boundary_hint"]))
    snap = {"nodes": [copy.deepcopy(node)]}
    ns["previous"] = [copy.deepcopy(snap)]
    ns["legacy"] = {"previous": [copy.deepcopy(snap)], "excluded_nodes": [dict(copy.deepcopy(node), node_id="S9")]}
    return sn.confirm_nodes(ns, g, [n["node_id"] for n in ns["nodes"]], "김", at=AT)


def full_results(ns, g):
    """등록부의 모든 ⑤ 필드에 값이 든 결과: 대상 참조·잠재 후보·근거 경로, 편집 기록, 보관 칸."""
    doc = res.empty_results(ns, DEVS)
    tk, v1 = ref(g, "TK"), ref(g, "V1")
    entry = {"entry_id": "e1", "origin": "ai_draft", "status": "proposed", "cause": "c", "consequence": "q",
             "cause_refs": [{"ref": v1}], "consequence_refs": [{"ref": tk}],
             "safeguards": [{"text": "s", "role": "preventive", "refs": [{"ref": v1}]}],
             "expectation_refs": [expect.expectation_id("R-1", v1)],
             "ai_basis": {"kg_paths": [[eid(g, "V1"), g["edges"][0]["entity_id"], "cond-001"]]}}
    doc["cells"][0]["entries"] = [entry]
    doc = res.edit_entry(doc, doc["cells"][0]["node_id"], doc["cells"][0]["deviation_id"], "e1",
                         {"cause_refs": [{"ref": tk}], "consequence_refs": [{"ref": v1}],
                          "safeguards": [{"text": "s2", "role": "preventive", "refs": [{"ref": tk}]}],
                          "expectation_refs": [expect.expectation_id("R-1", tk)]}, at=AT, reason="고침")
    doc["archived_cells"] = [{"cell": copy.deepcopy(doc["cells"][0]), "reason": "deviation_removed", "at": AT, "by": None}]
    return doc


class FieldsRegistryTest(StoreCase):
    """등록부(FIELDS)의 모든 자리가 실제 문서에 나오고, 판 이전이 등록되지 않은 자리에서 옛 id를 만나지 않는다."""

    def test_every_registered_field_is_met(self):
        ns = full_set(self.g1)
        doc = full_results(ns, self.g1)
        for kind, d in ((idmap.SET, ns), (idmap.RESULTS, doc)):
            for path, space in idmap.FIELDS[kind]:
                found = [h[k] for h, k in idmap.walk(d, path)]
                if space == idmap.MEMBERS:
                    found = [x for x in found if isinstance(x, dict) and x.get("members")]
                self.assertTrue(found, "죽은 등록 항목이거나 고정 자료가 그 길을 타지 않음: %s %s" % (kind, path))

    def test_migration_meets_no_old_id_outside_the_registry(self):
        ns = full_set(self.g1)
        doc = full_results(ns, self.g1)
        g2 = drawing("v-2", order=("V2", "TK", "V1", "PP"))
        ns2, p = migrate.migrate_set(ns, g2, at=AT)
        moved, _ = migrate.migrate_results(doc, ns2, at=AT, table=p["table"])
        self.assertEqual(ns2["history"][-1]["detail"]["unregistered"], [])
        self.assertEqual(moved["version_migrations"][-1]["unregistered"], [])
        self.assertTrue(ns2["history"][-1]["detail"]["renamed"], "순번이 밀려 실제로 이름이 바뀜")

    def test_an_id_kept_in_an_unknown_field_is_reported(self):
        ns = full_set(self.g1)
        ns["nodes"][0]["picked"] = [eid(self.g1, "V1")]
        ns2, _ = migrate.migrate_set(ns, drawing("v-2", order=("V2", "TK", "V1", "PP")), at=AT)
        self.assertEqual(ns2["history"][-1]["detail"]["unregistered"], ["nodes[0].picked[0]"])
        self.assertTrue(idmap.needs_check(ns2)["needs_check"])

    def test_tomb_ids_cannot_be_live_ids(self):
        g = drawing("v-1")
        live = {n["entity_id"] for n in g["nodes"]} | {e["entity_id"] for e in g["edges"]} | \
            {idmap.ref_of(n, g["graph_id"]) for n in g["nodes"]} | {g["graph_id"]}
        self.assertFalse([x for x in live if idmap.is_tomb(x)])
        self.assertTrue(idmap.is_tomb(idmap.tomb_id(g["graph_id"], "v-2", 1)))


class OldFormTest(StoreCase):
    """0.2 파일(cff108c~49033f1의 B꼴: lost_members·`~lost`)을 같은 판으로 읽으면 묘비 꼴로 바꾸되 새로 잃는 것은 없다."""

    def save_b_form(self, ns, lost_members, doc=None):
        b = {k: v for k, v in ns.items() if k not in ("graph_member_basis", "tombstones")}
        b.update(schema_version="0.2", graph_member_marks=idmap.legacy_marks(self.g1))
        for n in b["nodes"]:
            n.update(lost_members=lost_members.get(n["node_id"], [])) if n["node_id"] in lost_members else None
        sn.save(b)
        return res.save(doc, None) if doc is not None else None

    def start(self):
        ns = sn.new_set(self.g1)
        ns["nodes"] = [dict({"node_id": "S1", "name": "a", "basis": "b", "members": [eid(self.g1, "TK"), eid(self.g1, "V1")]},
                            **sn._v2_fields("script")),
                       dict({"node_id": "S2", "name": "b", "basis": "b", "members": [eid(self.g1, "V2"), eid(self.g1, "PP")]},
                            **sn._v2_fields("script"))]
        ns = sn.confirm(ns, self.g1, "김", at=AT)
        return ns, "S1"

    def test_lost_members_and_their_refs_become_one_tombstone(self):
        ns, s1 = self.start()
        mark = ["drawing_object", None, "pump", None, 300.0, 0.0, 310.0, 10.0]
        rec = {"entity_id": "entity-node-009", "ref": "graph-T#pdf-p0-sym-0009", "mark": mark, "from": "v-0"}
        doc = res.empty_results(ns, DEVS)
        doc["cells"][0]["entries"] = [{"entry_id": "e1", "cause_refs": [{"ref": rec["ref"] + "~lost"}],
                                       "expectation_refs": [expect.expectation_id("R-1", rec["ref"]) + "~lost"],
                                       "ai_basis": {"kg_paths": [["entity-node-009~lost"]]}}]
        rpath = self.save_b_form(ns, {s1: [rec]}, doc)
        got = sn.load(self.g1)
        node = next(n for n in got["nodes"] if n["node_id"] == s1)
        (t,) = node["lost"]
        self.assertEqual((got["schema_version"], "lost_members" in node), (sn.SCHEMA_VERSION, False))
        self.assertEqual((got["tombstones"][t]["ref"], got["tombstones"][t]["mark"]), (rec["ref"], mark))
        self.assertEqual(node["state"], "confirmed", "같은 판으로 읽기만 해서는 재확인하지 않음")
        with open(rpath, encoding="utf-8") as fh:
            e = json.load(fh)["cells"][0]["entries"][0]
        self.assertEqual(e["cause_refs"][0]["ref"], t)
        self.assertEqual(e["expectation_refs"][0], t + idmap.EXP_SEP + "R-1")
        self.assertEqual(e["ai_basis"]["kg_paths"][0][0], t)
        with mock.patch.dict(SYMBOLS, PX=("pump", None, [300, 0, 10, 10])):
            g2 = drawing("v-2", order=("TK", "V1", "PX", "V2", "PP"))
        got2 = sn.load(g2)
        node = next(n for n in got2["nodes"] if n["node_id"] == s1)
        self.assertNotIn("lost", node, "같은 자리에 같은 기호가 다시 나오면 되찾음")
        with open(rpath, encoding="utf-8") as fh:
            e = json.load(fh)["cells"][0]["entries"][0]
        self.assertEqual(e["cause_refs"][0]["ref"], ref(g2, "PX"))
        self.assertEqual(e["expectation_refs"][0], expect.expectation_id("R-1", ref(g2, "PX")))

    def test_one_legacy_key_shared_by_two_lost_symbols_is_never_refound(self):
        """49033f1 판에서 두 기호가 같은 순번으로 차례로 잃히면 `~lost` 글자가 같다. 어느 쪽인지 모르므로 되찾지 않는다."""
        ns, s1 = self.start()
        s2 = ns["nodes"][1]["node_id"]
        mark = ["drawing_object", None, "pump", None, 300.0, 0.0, 310.0, 10.0]
        shared = "graph-T#pdf-p0-sym-0009"
        recs = {s1: [{"entity_id": "entity-node-009", "ref": shared, "mark": mark, "from": "v-0"}],
                s2: [{"entity_id": "entity-node-009", "ref": shared, "mark": mark[:4] + [500.0, 0.0, 510.0, 10.0],
                      "from": "v-00"}]}
        doc = res.empty_results(ns, DEVS)
        doc["cells"][0]["entries"] = [{"entry_id": "e1", "cause_refs": [{"ref": shared + "~lost"}]}]
        rpath = self.save_b_form(ns, recs, doc)
        got = sn.load(self.g1)
        self.assertEqual(len(got["tombstones"]), 2)
        with open(rpath, encoding="utf-8") as fh:
            t = json.load(fh)["cells"][0]["entries"][0]["cause_refs"][0]["ref"]
        self.assertTrue(idmap.is_tomb(t))
        self.assertNotIn(t, got["tombstones"], "어느 묘비와도 잇지 않은, 되찾지 않는 묘비")

    def test_out_of_node_lost_ref_and_damaged_records(self):
        ns, s1 = self.start()
        doc = res.empty_results(ns, DEVS)
        doc["cells"][0]["entries"] = [{"entry_id": "e1", "consequence_refs": [{"ref": "graph-T#pdf-p0-sym-0077~lost"}]}]
        rpath = self.save_b_form(ns, {s1: [None, "x", {}]}, doc)
        got = sn.load(self.g1)
        self.assertEqual((got.get("tombstones"), "lost" in got["nodes"][0]), ({}, False))
        with open(rpath, encoding="utf-8") as fh:
            self.assertTrue(idmap.is_tomb(json.load(fh)["cells"][0]["entries"][0]["consequence_refs"][0]["ref"]))


class SchemaGateTest(StoreCase):
    def test_saved_sets_carry_the_tomb_schema_and_newer_files_are_refused(self):
        path = sn.save(sn.propose(self.g1, at=AT))
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["schema_version"], "0.3", "0.2만 아는 앱은 '이 앱보다 새 파일'로 거절한다")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(doc, schema_version="0.4"), fh)
        with self.assertRaisesRegex(ValueError, "새 검토구간 파일"):
            sn.load(self.g1)
        with self.assertRaisesRegex(ValueError, "새 검토구간 파일"):
            sn.load_view(self.g1)


class AtomicRewriteTest(StoreCase):
    """판 이전 다시 쓰기는 백업 뒤 원자적으로 쓴다. 쓰다가 실패하면 원본 바이트가 그대로다."""

    def setUp(self):
        super().setUp()
        self.ns = sn.confirm(sn.propose(self.g1, at=AT), self.g1, "김", at=AT)
        self.path = sn.save(self.ns)
        self.g2 = drawing("v-2", order=("V2", "TK", "V1", "PP"))

    def test_failed_replace_keeps_the_original_and_is_reported_unwritten(self):
        before = self.raw(self.path)
        with mock.patch.object(store_io.os, "replace", side_effect=OSError("디스크 가득 참")):
            got = sn.load(self.g2)
        self.assertEqual(self.raw(self.path), before)
        self.assertEqual(got["graph_version"], "v-1")
        self.assertTrue(migrate.unwritten(got, self.g2))
        self.assertTrue(os.listdir(paths.folder_in(self.tmp, "backup")), "쓰기 전에 백업을 남김")
        self.assertEqual(sn.load(self.g2)["graph_version"], "v-2", "다음 읽기에서 다시 옮김")

    def test_error_while_writing_keeps_the_original(self):
        before = self.raw(self.path)
        with mock.patch.object(store_io.os, "fsync", side_effect=RuntimeError("끊김")):
            with self.assertRaises(RuntimeError):
                sn.load(self.g2)
        self.assertEqual(self.raw(self.path), before)
        folder = os.path.dirname(self.path)
        self.assertEqual([f for f in os.listdir(folder) if f.endswith(".tmp")], [])


class EditsKeepTombsTest(StoreCase):
    """판 이전에서 잃은 구성요소의 묘비는 병합·빈 구간 지우기·확정을 거쳐도 사라지지 않고 기록된다."""

    def lost_set(self):
        ns = sn.propose(self.g1, at=AT)
        ns["nodes"] = [dict({"node_id": "S1", "name": "a", "basis": "b", "members": [eid(self.g1, "TK"), eid(self.g1, "V1")]},
                            **sn._v2_fields("script")),
                       dict({"node_id": "S2", "name": "b", "basis": "b", "members": [eid(self.g1, "V2"), eid(self.g1, "PP")]},
                            **sn._v2_fields("script"))]
        g2 = drawing("v-2", gone=("V1", "PP"))
        ns2, _ = migrate.migrate_set(ns, g2, at=AT)
        self.assertEqual([len(n["lost"]) for n in ns2["nodes"]], [1, 1])
        return ns2, g2

    def test_merge_keeps_both_tombstones(self):
        ns, _ = self.lost_set()
        lost = sorted(t for n in ns["nodes"] for t in n["lost"])
        out = sn.merge(ns, ["S1", "S2"], at=AT)
        self.assertEqual(out["nodes"][0]["lost"], lost)

    def test_removing_an_emptied_node_records_its_tombstones(self):
        ns, _ = self.lost_set()
        node = ns["nodes"][0]
        for m in list(node["members"])[:-1]:
            ns = sn.remove_member(ns, "S1", m, at=AT)
        last = next(n for n in ns["nodes"] if n["node_id"] == "S1")["members"][0]
        out = sn.remove_member(ns, "S1", last, at=AT)
        self.assertEqual(out["history"][-1]["detail"]["lost"], node["lost"])
        self.assertTrue(all(t in out["tombstones"] for t in node["lost"]), "묘비 기록은 집합에 남음")

    def test_confirming_a_node_with_tombstones_records_how_many(self):
        ns, g2 = self.lost_set()
        out = sn.confirm_nodes(ns, g2, ["S1"], "김", at=AT)
        self.assertEqual(out["nodes"][0]["confirmed"]["lost"], 1)
        self.assertEqual(out["history"][-1]["detail"]["with_lost"], {"S1": 1})


def source_drawing(version, gone=(), kinds=None):
    """drawio처럼 source_object_id가 파일 id인 도면. kinds {이름: 종류}로 같은 id의 종류를 바꾼다."""
    g = drawing(version, gone=gone)
    for n in g["nodes"]:
        n["source_object_id"] = "cell-" + n["_name"]
        n["id_basis"] = "source"
        n["kind"] = (kinds or {}).get(n["_name"], n["kind"])
    return g


class SourceTombTest(StoreCase):
    """source 구성요소의 묘비는 같은 참조가 같은 종류(기록에 태그가 있으면 같은 태그)로 돌아오면 되찾는다."""

    def lost_v1(self):
        g1 = source_drawing("v-1")
        ns = sn.propose(g1, at=AT)
        ns["nodes"] = [dict({"node_id": "S1", "name": "a", "basis": "b", "members": [eid(g1, "TK"), eid(g1, "V1")]},
                            **sn._v2_fields("script"))]
        ns2, _ = migrate.migrate_set(ns, source_drawing("v-2", gone=("V1",)), at=AT)
        self.assertEqual(len(ns2["nodes"][0]["lost"]), 1)
        return ns2

    def back(self, ns, **kw):
        g3 = source_drawing("v-3", **kw)
        out, _ = migrate.migrate_set(ns, g3, at=AT)
        return out, g3

    def test_same_ref_and_kind_brings_the_member_back(self):
        out, g3 = self.back(self.lost_v1())
        self.assertEqual(sorted(out["nodes"][0]["members"]), sorted([eid(g3, "TK"), eid(g3, "V1")]))
        self.assertFalse(out["nodes"][0].get("lost"))

    def test_same_ref_with_other_kind_stays_a_tomb(self):
        ns = self.lost_v1()
        out, _ = self.back(ns, kinds={"V1": "check_valve"})
        self.assertEqual(out["nodes"][0]["lost"], ns["nodes"][0]["lost"], "같은 id의 다른 종류는 다른 기호")

    def test_edited_look_in_the_record_does_not_open_the_tomb(self):
        ns = self.lost_v1()
        t = ns["nodes"][0]["lost"][0]
        ns["tombstones"][t]["look"][2] = "check_valve"
        out, _ = self.back(ns, kinds={"V1": "check_valve"})
        self.assertEqual(out["nodes"][0]["lost"], [t], "지문이 묘비 id와 맞지 않으면 되찾지 않음")

    def test_tomb_without_a_recorded_look_is_not_refound_by_ref(self):
        ns = self.lost_v1()
        t = ns["nodes"][0]["lost"][0]
        rec = ns["tombstones"].pop(t)
        old = idmap.tomb_id("graph-T", rec["lost_at"], idmap.tomb_key("graph-T", rec["lost_from"], rec["lost_at"],
                                                                     rec["entity_id"], rec["ref"], rec["mark"]))
        ns["tombstones"][old] = {k: v for k, v in rec.items() if k != "look"}  # 이 고침 전에 지은 묘비
        ns["nodes"][0]["lost"] = [old]
        out, _ = self.back(ns)
        self.assertEqual(out["nodes"][0]["lost"], [old], "기록에 겉모습이 없으면 같은 기호인지 몰라 묘비로 둠")

    def test_discarded_source_tomb_is_not_refound(self):
        ns = sn.discard_lost(self.lost_v1(), "S1", None, by="김검토", at=AT)
        out, _ = self.back(ns)
        self.assertNotIn(eid(source_drawing("v-3"), "V1"), out["nodes"][0]["members"])
        t = out["nodes"][0]["discarded"][0]
        self.assertIsNone(out["tombstones"][t]["found"], "버린 묘비는 같은 기호가 돌아와도 닫힌 채")


if __name__ == "__main__":
    unittest.main()
