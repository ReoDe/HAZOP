"""그래프 판 이전(hazop.study.migrate, U10) 시험. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다."""

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
from hazop.study import idmap, migrate, refs  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402

AT = "2026-11-08T00:00:00Z"
DEVS = [{"deviation_id": "D01", "item_id": "I1", "parameter": "유량", "guideword": "없음", "label": "유량 없음"}]
OBJECTS = [("TK", "tank", "equipment"), ("V1", "manual_valve", "valve"), ("V2", "manual_valve", "valve"),
           ("PP", "pump", "equipment"), ("LT", "transmitter", "instrument")]
PIPES = [("L1", "TK", "V1"), ("L2", "V1", "V2"), ("L3", "V2", "PP")]


def graph(version, objects=OBJECTS, pipes=PIPES, shift=0):
    """source_object_id는 그대로이고 entity_id 번호만 shift만큼 밀린 도면 그래프(재추출 흉내)."""
    nodes, edges, eid = [], [], {}
    for i, (soid, kind, cat) in enumerate(objects, 1 + shift):
        eid[soid] = "entity-node-%03d" % i
        nodes.append({"entity_id": eid[soid], "node_type": "drawing_object", "kind": kind, "category": cat,
                      "tag": soid, "label_text": soid, "source_object_id": soid, "id_basis": "source",
                      "position": [0.0, 0.0]})
    for i, (soid, a, b) in enumerate(pipes, 1 + shift):
        sid = "entity-seg-%03d" % i
        nodes.append({"entity_id": sid, "node_type": "pipe_segment", "kind": "pipe_segment",
                      "category": "pipe_segment", "tag": "L", "line_no": "L", "source_object_id": soid,
                      "id_basis": "source", "position": [0.0, 0.0]})
        edges += [{"entity_id": "relation-%s-%s" % (sid, x), "kind": "has_endpoint", "nodes": [sid, eid[x]]}
                  for x in (a, b) if x in eid]
    if "LT" in eid and "TK" in eid:
        edges.append({"entity_id": "relation-m1", "kind": "measurement_connection", "nodes": [eid["TK"], eid["LT"]]})
    return {"project_id": None, "graph_id": "graph-T", "graph_version": version,
            "source": {"drawing_number": "T-1"}, "nodes": nodes, "edges": edges}


def entity(g, soid):
    return next(n["entity_id"] for n in g["nodes"] if n["source_object_id"] in (soid, SID.get(soid)))


def results_for(ns, g):
    """사람이 고친 항목 1개(승인)와 AI 초안 1개가 든 결과. kg_paths에는 구성요소 ID와 지식 ID가 섞여 있다."""
    doc = res.empty_results(ns, DEVS)
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
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
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
        refs = self.ns["graph_member_refs"]
        self.assertEqual(refs[entity(self.g1, "V1")], "graph-T#V1")
        self.assertEqual(len(refs), len(self.g1["nodes"]), "그래프 전체(구간 밖 포함)")
        self.assertEqual({n["node_id"] for n in self.ns["nodes"]}, set(self.ns["member_digest"]))
        self.assertTrue(all(d.startswith("md3-") for d in self.ns["member_digest"].values()))

    def test_all_mapped_keeps_confirmation_and_logs(self):
        sn.save(self.ns)
        g2 = graph("v-2", shift=10)
        got = sn.load(g2)
        self.assertEqual({(n["state"], n["confirmed"]["by"], n["confirmed"]["at"], n["rev"]) for n in got["nodes"]},
                         {("confirmed", "김검토", AT, 1)})
        self.assertEqual(got["graph_version"], "v-2")
        self.assertFalse(sn.is_stale(got, g2))
        self.assertEqual(sn.coverage(got, g2)["uncovered"], [])
        by_soid = {n["source_object_id"]: n["entity_id"] for n in g2["nodes"]}
        old_soid = {e: r.split("#")[1] for e, r in self.ns["graph_member_refs"].items()}
        for before, after in zip(self.ns["nodes"], got["nodes"]):
            self.assertEqual(after["node_id"], before["node_id"])
            self.assertEqual(after["members"], sorted(by_soid[old_soid[m]] for m in before["members"]))
        last = got["history"][-1]
        self.assertEqual((last["op"], last["detail"]["from"], last["detail"]["to"], last["detail"]["matched"]),
                         ("migrate_version", "v-1", "v-2", len(g2["nodes"])))
        self.assertEqual(migrate.notice(got), "그래프 판이 바뀌어(v-1 → v-2) 구성요소 %d개를 새 판에 다시 맞췄습니다. 확정은 그대로입니다."
                         % len(g2["nodes"]))
        self.assertEqual(got["history"][:-1], self.ns["history"])
        self.assertEqual(last["detail"]["recheck"], {})
        self.assertTrue(os.path.isdir(paths.folder_in(self.tmp, "backup")))
        with open(sn.store_path(None, "graph-T"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), got)

    def test_one_missing_component_rechecks_only_its_node(self):
        sn.save(self.ns)
        g2 = graph("v-2", objects=OBJECTS[:-1], shift=3)
        lost = sn.nodes_of(self.ns, entity(self.g1, "LT"))
        got = sn.load(g2)
        self.assertFalse(sn.is_stale(got, g2))
        p = got["history"][-1]["detail"]
        self.assertEqual(sorted(p["recheck"]), lost)
        self.assertIn("새 판에서 찾지 못한", p["recheck"][lost[0]])
        for n in got["nodes"]:
            self.assertEqual((n["state"], n["rev"]), ("applied", 2) if n["node_id"] in lost else ("confirmed", 1))

    def test_added_component_is_not_a_reason_but_ambiguity_is(self):
        extra = graph("v-2", objects=OBJECTS + [("FT", "transmitter", "instrument")])
        self.assertEqual(migrate.plan(self.ns, extra)["recheck"], {}, "구간 밖 구성요소가 늘어도 재확인 아님(§1 #18)")
        dup = graph("v-2")
        dup["nodes"][1]["source_object_id"] = "TK"
        hit = set(sn.nodes_of(self.ns, entity(self.g1, "TK")) + sn.nodes_of(self.ns, entity(self.g1, "V1")))
        self.assertEqual(set(migrate.plan(self.ns, dup)["recheck"]), hit)
        self.assertEqual(migrate.plan({"schema_version": "0.1", "nodes": []}, graph("v-2"))["state"], "skip")

    def test_changed_tag_kind_or_link_needs_recheck(self):
        """② 사람 수정처럼 참조는 같고 내용만 바뀐 판은 유지하지 않는다(결정로그 2026-11-07 '재확인 필요')."""
        tag = graph("v-2", shift=10)
        tag["nodes"][1]["tag"] = "V1-NEW"
        kind = graph("v-2", objects=[("TK", "tank", "equipment"), ("V1", "pump", "equipment")] + OBJECTS[2:])
        link = graph("v-2", pipes=[("L1", "TK", "V2"), ("L2", "V1", "V2"), ("L3", "V2", "PP")])
        for g in (tag, kind, link):
            p = migrate.plan(self.ns, g)
            self.assertTrue(p["recheck"])
            self.assertEqual(set(p["recheck"].values()), {"구성요소의 종류·태그·흐름·연결·정상 위치·고장 위치가 바뀜"})
        extra_field = graph("v-2", shift=10)
        for n in extra_field["nodes"]:
            n["origin"] = "drawing"
            n["attributes"] = {"claims": []}
        self.assertEqual((migrate.plan(self.ns, extra_field)["state"], migrate.plan(self.ns, extra_field)["recheck"]),
                         ("kept", {}))

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
        self.assertEqual(moved["graph_version"], "v-2")
        self.assertFalse(res.is_stale(moved, ns2))
        self.assertEqual(res.validate(moved, ns2), [])
        self.assertEqual(text_of(moved), text_of(doc))
        self.assertEqual(moved["cells"][0]["state"], "analyzed")
        paths_ = [e["ai_basis"]["kg_paths"] for e in moved["cells"][0]["entries"]]
        self.assertEqual(paths_[0], [[entity(g2, "L1"), entity(g2, "V1"), "cond-001"]])
        self.assertEqual(paths_[1][0][0], entity(g2, "V2"))
        self.assertTrue(idmap.is_tomb(paths_[1][0][1]), "관계 id는 판 사진에 없고 순번이라 다른 관계를 가리킬 수 있음")
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
            self.assertEqual(json.load(fh)["graph_version"], "v-1", "파일은 사람이 저장할 때 씀")

    def test_results_without_a_migration_chain_stay_as_they_are(self):
        doc = dict(results_for(self.ns, self.g1), graph_version="v-0")
        ns2, _ = migrate.migrate_set(self.ns, graph("v-2", shift=10), at=AT)
        self.assertEqual(migrate.migrate_results(doc, ns2), (doc, None))

    def test_converted_01_file_without_digests_follows_the_legacy_whole_graph_digest(self):
        """0.1에서 바꾼 집합(구간 지문 없음, legacy.member_digest만 있음)도 내용이 같은 새 판에서 확정을 잇는다."""
        legacy = copy.deepcopy(self.ns)
        legacy["member_digest"] = {}
        legacy["legacy"] = {"member_digest": migrate.member_digest(self.g1)}
        same, p = migrate.migrate_set(legacy, graph("v-2", shift=10), at=AT)
        self.assertEqual((p["recheck"], sn.all_confirmed(same)), ({}, True))
        tag = graph("v-2", shift=10)
        tag["nodes"][1]["tag"] = "V1-NEW"
        changed, p = migrate.migrate_set(legacy, tag, at=AT)
        self.assertEqual(set(p["recheck"]), {n["node_id"] for n in legacy["nodes"]}, "옛 기록은 그래프 전체라 모두 재확인")
        filled = migrate.with_refs(legacy, self.g1)
        self.assertEqual(filled["member_digest"], self.ns["member_digest"], "판이 같을 때는 구간 지문을 채움")

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


UNTAGGED = [("TK", "tank", "equipment"), ("V1", "manual_valve", "valve"), ("V2", "manual_valve", "valve"),
            ("V3", "manual_valve", "valve"), ("PP", "pump", "equipment")]
UNTAGGED_PIPES = [("L1", "TK", "V1"), ("L2", "V1", "V2"), ("L3", "V2", "V3"), ("L4", "V3", "PP")]


SID = {"TK": "pdf-p0-sym-0001", "V1": "pdf-p0-sym-0002", "V2": "pdf-p0-sym-0003", "V3": "pdf-p0-sym-0004",
       "PP": "pdf-p0-sym-0005", "L1": "pdf-p0-conn-0001", "L2": "pdf-p0-conn-0002", "L3": "pdf-p0-conn-0003",
       "L4": "pdf-p0-conn-0004"}


def REF(name):
    return "graph-T#" + SID[name]


def drawn(version, at, objects=UNTAGGED, fixed_ids=False, shift=0):
    """태그 없는 같은 종류 밸브 셋이 있는 도면 그래프. at {이름: 상자 [x, y, w, h]}. 벡터 PDF처럼 source_object_id가
    순번(pdf-p0-sym-0002)이라 다시 추출해 순번이 밀리면 같은 id가 다른 자리의 밸브를 가리킨다(종류·태그·연결은 그대로라
    구간 지문이 같다). fixed_ids면 drawio처럼 이름이 곧 고정 id다."""
    g = graph(version, objects=objects, pipes=UNTAGGED_PIPES, shift=shift)
    for n in g["nodes"]:
        name = n["source_object_id"]
        n["bbox"] = at.get(name)
        if n["kind"] == "manual_valve":
            n["tag"] = n["label_text"] = None
        if not fixed_ids:
            n["source_object_id"] = SID[name]
            n["id_basis"] = "sequence"
    return g


PLACES = {"TK": [0, 0, 10, 10], "V1": [20, 0, 5, 5], "V2": [40, 0, 5, 5], "V3": [60, 0, 5, 5], "PP": [80, 0, 10, 10],
          "L1": [10, 2, 10, 1], "L2": [25, 2, 15, 1], "L3": [45, 2, 15, 1], "L4": [65, 2, 15, 1]}


class ShiftedSymbolTest(unittest.TestCase):
    """규칙 판이 바뀐 다시 추출로 순번이 밀려도, 구간 구성요소가 조용히 다른 기호를 가리키지 않는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
        self.g1 = drawn("v-1", PLACES)
        self.ns = sn.confirm(sn.propose(self.g1, at=AT), self.g1, "김검토", at=AT)
        sn.save(self.ns)

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    def places(self, ns, g):
        box = {n["entity_id"]: n["bbox"] for n in g["nodes"]}
        return sorted(box[m] for n in ns["nodes"] for m in n["members"])

    def landed(self, got, g2):
        """옛 구성요소마다 판 이전이 이은 새 구성요소의 상자."""
        renamed = got["history"][-1]["detail"]["renamed"]
        box = {n["entity_id"]: n["bbox"] for n in g2["nodes"]}
        return {m: box[renamed.get(m, m)] for n in self.ns["nodes"] for m in n["members"]}

    def test_members_keep_their_drawn_symbol_when_ids_shift(self):
        shifted = dict(PLACES, V1=PLACES["V2"], V2=PLACES["V3"], V3=PLACES["V1"])
        g2 = drawn("v-2", shifted)
        got = sn.load(g2)
        before = {n["entity_id"]: n["bbox"] for n in self.g1["nodes"]}
        self.assertEqual(self.landed(got, g2), {m: before[m] for m in self.landed(got, g2)},
                         "구성요소는 같은 자리의 밸브를 가리켜야 함")

    def test_member_without_a_unique_place_is_reported_not_guessed(self):
        moved = dict(PLACES, V2=[200, 0, 5, 5])
        g2 = drawn("v-2", moved)
        got = sn.load(g2)
        holder = sn.nodes_of(self.ns, entity(self.g1, "V2"))
        detail = got["history"][-1]["detail"]
        self.assertEqual(sorted(detail["recheck"]), holder)
        self.assertIn("새 판에서 찾지 못한", detail["recheck"][holder[0]])
        self.assertTrue(all(n["state"] == "applied" for n in got["nodes"] if n["node_id"] in holder))

    def test_same_place_on_another_drawing_is_not_the_same_symbol(self):
        g2 = drawn("v-2", dict(PLACES, V2=[200, 0, 5, 5]))
        g2["nodes"].append({"entity_id": "graph-X/entity-node-001", "node_type": "drawing_object", "kind": "manual_valve",
                            "sheet": "graph-X", "source_object_id": "V9", "bbox": PLACES["V2"], "position": [0.0, 0.0]})
        lost = sn.nodes_of(self.ns, entity(self.g1, "V2"))
        self.assertEqual(sorted(migrate.plan(sn.load(self.g1), g2)["recheck"]), lost)

    def test_same_places_keep_confirmation(self):
        g2 = drawn("v-2", PLACES)
        got = sn.load(g2)
        self.assertEqual(got["history"][-1]["detail"]["recheck"], {})
        self.assertEqual(self.places(got, g2), self.places(self.ns, self.g1))

    def cause_refs_after(self, g2):
        """V1·V2를 원인 위치로 가리킨 ⑤ 항목을 저장하고, g2로 판 이전한 뒤 그 참조가 가리키는 상자."""
        doc = results_for(self.ns, self.g1)
        doc["cells"][0]["entries"][0]["cause_refs"] = [{"ref": REF("V1")}, {"ref": REF("V2")}]
        rpath = res.save(doc, None)
        sn.load(g2)
        with open(rpath, encoding="utf-8") as fh:
            moved = json.load(fh)
        from hazop.study import refs
        idx = refs.index(g2)
        return [(idx[r["ref"]]["bbox"] if r["ref"] in idx else None)
                for r in moved["cells"][0]["entries"][0]["cause_refs"]]

    def test_result_refs_follow_the_drawn_symbol(self):
        shifted = dict(PLACES, V1=PLACES["V2"], V2=PLACES["V3"], V3=PLACES["V1"])
        self.assertEqual(self.cause_refs_after(drawn("v-2", shifted)), [PLACES["V1"], PLACES["V2"]])

    def test_result_ref_to_a_symbol_not_found_does_not_point_elsewhere(self):
        self.assertEqual(self.cause_refs_after(drawn("v-2", dict(PLACES, V2=[200, 0, 5, 5]))), [PLACES["V1"], None])

    def test_other_result_pointers_do_not_point_elsewhere(self):
        """잠재 후보 ID와 근거 경로의 구성요소 ID도 같은 대응으로 옮기고, 찾지 못한 것은 어디도 가리키지 않게 표시한다."""
        from hazop.kg import expect
        doc = results_for(self.ns, self.g1)
        e = doc["cells"][0]["entries"][0]
        e["expectation_refs"] = [expect.expectation_id("R-1", REF("V1")), expect.expectation_id("R-1", REF("V2"))]
        e["ai_basis"]["kg_paths"] = [[entity(self.g1, "V1"), entity(self.g1, "V2"), "cond-001"]]
        rpath = res.save(doc, None)
        g2 = drawn("v-2", dict(PLACES, V1=PLACES["V3"], V3=PLACES["V1"], V2=[200, 0, 5, 5]))
        sn.load(g2)
        with open(rpath, encoding="utf-8") as fh:
            moved = json.load(fh)
        got = moved["cells"][0]["entries"][0]
        self.assertEqual(got["expectation_refs"][0], expect.expectation_id("R-1", REF("V3")))
        self.assertTrue(idmap.is_tomb(got["expectation_refs"][1]))
        ids = {n["entity_id"] for n in g2["nodes"]}
        path = got["ai_basis"]["kg_paths"][0]
        self.assertEqual(path[0], entity(g2, "V3"))
        self.assertNotIn(path[1], ids, "찾지 못한 구성요소 ID가 새 판의 다른 구성요소를 가리키면 안 됨")
        self.assertEqual(moved["version_migrations"][-1]["check"], "mark")

    def test_old_set_without_marks_loses_numbered_members_instead_of_guessing(self):
        """A꼴(cff108c 전: 표시·id 근거 없음)을 다른 판으로 처음 읽으면 순번 구성요소는 확인할 길이 없어 묘비다.
        구간 지문(md3)은 위치를 담지 않아 같은 종류·태그의 다른 자리 기호를 가려내지 못한다."""
        bare = {k: v for k, v in self.ns.items() if k not in ("graph_member_marks", "graph_member_basis", "tombstones")}
        sn.save(dict(bare, schema_version="0.2"))
        rpath = res.save(results_for(self.ns, self.g1), None)
        got = sn.load(drawn("v-2", PLACES))
        self.assertEqual([m for n in got["nodes"] for m in n["members"]], [])
        self.assertEqual({n["state"] for n in got["nodes"]}, {"applied"})
        with open(rpath, encoding="utf-8") as fh:
            moved = json.load(fh)
        self.assertTrue(all(idmap.is_tomb(r["ref"]) for c in moved["cells"] for e in c["entries"]
                            for r in e.get("cause_refs") or []))

    def test_set_saved_without_marks_gets_them_on_same_version_load(self):
        bare = {k: v for k, v in self.ns.items() if k not in ("graph_member_marks", "graph_member_basis", "tombstones")}
        sn.save(dict(bare, schema_version="0.2"))
        got = sn.load(self.g1)
        self.assertEqual(got["schema_version"], sn.SCHEMA_VERSION)
        self.assertEqual(got["graph_member_marks"], idmap.snapshot(self.g1)["graph_member_marks"])
        self.assertEqual(got["nodes"], self.ns["nodes"], "같은 판으로 읽기만 해서는 구성요소를 잃지 않음")
        self.assertEqual(got.get("tombstones") or {}, {})

class LostMemberTest(unittest.TestCase):
    """검토 차단 1~4·(a)~(c): 고정 id 도면, 같은 자리 다른 기호, 잃은 구성요소, 참조 확인 필요."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    def start(self, g1):
        self.g1 = g1
        self.ns = sn.confirm(sn.propose(g1, at=AT), g1, "김검토", at=AT)
        sn.save(self.ns)
        doc = results_for(self.ns, g1)
        gid = g1["graph_id"]
        doc["cells"][0]["entries"][0]["cause_refs"] = [{"ref": "%s#%s" % (gid, entity_soid(g1, "V1"))}]
        self.rpath = res.save(doc, None)

    def cause_ref(self):
        with open(self.rpath, encoding="utf-8") as fh:
            return json.load(fh)["cells"][0]["entries"][0]["cause_refs"][0]["ref"]

    def test_block1_fixed_id_drawing_keeps_a_moved_symbol(self):
        self.start(drawn("v-1", PLACES, fixed_ids=True))
        g2 = drawn("v-2", dict(PLACES, V1=[30, 0, 5, 5]), fixed_ids=True)
        got = sn.load(g2)
        self.assertEqual(got["history"][-1]["detail"]["recheck"], {}, "drawio처럼 id가 고정이면 옮겨도 같은 기호")
        self.assertEqual(self.cause_ref(), "graph-T#V1")

    def test_block2_other_symbol_on_the_same_place_is_not_the_same(self):
        self.start(drawn("v-1", PLACES))
        cv = [("TK", "tank", "equipment"), ("V1", "control_valve", "valve")] + UNTAGGED[2:]
        g2 = drawn("v-2", PLACES, objects=cv)
        node = next(n for n in g2["nodes"] if n["source_object_id"] == SID["V1"])
        node["tag"] = "CV-9"
        got = sn.load(g2)
        holder = sn.nodes_of(self.ns, entity(self.g1, "V1"))
        self.assertEqual(sorted(got["history"][-1]["detail"]["recheck"]), holder)
        self.assertNotEqual(self.cause_ref(), REF("V1"), "⑤ 원인이 같은 자리의 CV-9를 가리키면 안 됨")

    def test_block3_lost_member_stays_lost_over_next_migration(self):
        self.start(drawn("v-1", PLACES))
        gone = entity(self.g1, "V2")
        holder = sn.nodes_of(self.ns, gone)[0]
        g2 = drawn("v-2", dict(PLACES, V2=[200, 0, 5, 5]))
        b = sn.load(g2)
        node = next(n for n in b["nodes"] if n["node_id"] == holder)
        self.assertNotIn(gone, node["members"], "찾지 못한 구성요소는 새 판의 어떤 기호도 가리키지 않음")
        self.assertEqual([b["tombstones"][t]["ref"] for t in node["lost"]], [REF("V2")])
        g3 = drawn("v-3", dict(PLACES, V2=[200, 0, 5, 5], V1=[20, 0, 5, 5]))
        g3["nodes"][0]["tag"] = "TK-NEW"  # 판만 바꾸는 다른 고침
        c = sn.load(g3)
        node = next(n for n in c["nodes"] if n["node_id"] == holder)
        self.assertNotIn(gone, node["members"])
        self.assertEqual(node["state"], "applied", "사람이 다시 확인할 때까지 재확인 상태")
        self.assertTrue(node["lost"])

    def test_lost_member_id_reused_by_a_moved_member(self):
        """잃은 구성요소의 옛 entity_id를 새 판의 다른 구성요소가 받아도(번호가 한 칸 당겨짐) 이전이 멈추지 않는다."""
        self.start(drawn("v-1", PLACES))
        g2 = drawn("v-2", dict(PLACES, V1=[200, 0, 5, 5]), shift=-1)
        got = sn.load(g2)
        self.assertEqual(got["graph_version"], "v-2")
        self.assertEqual(got["graph_member_marks"], idmap.snapshot(g2)["graph_member_marks"])

    def test_a_lost_member_comes_back_when_its_symbol_returns(self):
        self.start(drawn("v-1", PLACES))
        gone = entity(self.g1, "V1")
        holder = sn.nodes_of(self.ns, gone)[0]
        sn.load(drawn("v-2", dict(PLACES, V1=[200, 0, 5, 5])))
        self.assertTrue(idmap.is_tomb(self.cause_ref()))
        g3 = drawn("v-3", PLACES)
        c = sn.load(g3)
        node = next(n for n in c["nodes"] if n["node_id"] == holder)
        self.assertIn(entity(g3, "V1"), node["members"])
        self.assertFalse(node.get("lost"))
        self.assertEqual(node["state"], "applied", "되찾아도 재확인")
        self.assertEqual(self.cause_ref(), REF("V1"), "⑤ 잃은 참조도 되찾음")

    def test_block4_check_needed_reports_nodes_and_counts(self):
        self.start(drawn("v-1", PLACES))
        g2 = drawn("v-2", dict(PLACES, V1=[200, 0, 5, 5]))
        ns2 = sn.load(g2)
        doc = res.load(ns2)
        got = idmap.needs_check(ns2, doc)
        holder = sn.nodes_of(self.ns, entity(self.g1, "V1"))[0]
        self.assertEqual(got["lost_members"], {holder: 1})
        self.assertEqual(got["lost_refs"], {doc["cells"][0]["node_id"]: 1})
        self.assertFalse(got["unverified"])
        self.assertEqual(got["tombstones"], 1)
        self.assertTrue(got["needs_check"])

    def test_c_damaged_marks_and_tombstones_are_refused(self):
        """손으로 고쳤거나 깨진 저장본은 형식 검사(ValueError)로 읽지 않는다. TypeError로 멈추거나 덮어쓰지 않는다."""
        self.start(drawn("v-1", PLACES))
        path = sn.store_path(None, "graph-T")
        with open(path, encoding="utf-8") as fh:
            good = json.load(fh)
        k0 = sorted(good["graph_member_marks"])[0]
        cases = [lambda d: d["graph_member_marks"].__setitem__(k0, {"x": 1}),
                 lambda d: d["graph_member_marks"].__setitem__(k0, [["x"], None, "tank", None, 0, 0, 10, 10]),
                 lambda d: d["nodes"][0].__setitem__("lost_members", 5),
                 lambda d: d["nodes"][0].__setitem__("lost", ["entity-node-001"]),
                 lambda d: d.__setitem__("tombstones", {"entity-node-001": {}}),
                 lambda d: d.__setitem__("graph_member_basis", {k0: "maybe"})]
        for spoil in cases:
            doc = copy.deepcopy(good)
            spoil(doc)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            before = self.raw(path)
            for g in (self.g1, drawn("v-2", PLACES)):
                with self.assertRaises(ValueError):
                    sn.load(g)
            self.assertEqual(self.raw(path), before)

    def raw(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_b_lost_ref_label_says_check_needed(self):
        from hazop.study import refs
        text = refs.label("lost:graph-T:v-2:1", {})
        self.assertNotIn("lost:", text)
        self.assertIn("확인 필요", text)

    def test_b_initiating_event_does_not_show_lost_ref_as_tag(self):
        from hazop.ie import model
        o = {"basic_events": {}, "counters": {"BE": 0}}
        model._add_be(o, {}, {}, "lost:graph-T:v-2:1", "fail_closed", "hazop", "k", None)
        be = next(iter(o["basic_events"].values()))
        self.assertEqual(be["tag"], "확인 필요")
        self.assertNotIn("lost:", be["name"])


class ReviewReproTest(unittest.TestCase):
    """재검토가 49033f1에서 재현한 넷(사라짐·두 번 잃음·스캔 id·실행 취소). 퍼즈가 놓쳐도 이 넷은 지킨다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp)
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)

    def boxes(self, g, ids_):
        box = {n["entity_id"]: (n["kind"], n["bbox"]) for n in g["nodes"]}
        return sorted((box[m] for m in ids_), key=json.dumps)

    def test_repro1_member_that_takes_a_lost_id_stays_in_its_node(self):
        """V1을 잃고 뒤 기호의 entity_id가 한 칸씩 당겨져도, 같은 구간의 다른 구성요소는 members에 남고 V1만 묘비가 된다."""
        g1 = drawn("v-1", PLACES)
        ns = sn.confirm(sn.propose(g1, at=AT), g1, "r", at=AT)
        everything = sorted({m for n in ns["nodes"] for m in n["members"]})
        ns["nodes"] = [dict(ns["nodes"][0], members=everything)]
        ns["member_digest"] = {ns["nodes"][0]["node_id"]: migrate.node_digest(g1, everything)}
        sn.save(ns)
        g2 = drawn("v-2", PLACES, objects=[o for o in UNTAGGED if o[0] != "V1"])
        got = sn.load(g2)
        node = got["nodes"][0]
        want = [b for b in self.boxes(g1, everything) if b[1] != PLACES["V1"]]
        self.assertEqual(self.boxes(g2, node["members"]), want)
        self.assertEqual([got["tombstones"][t]["entity_id"] for t in node["lost"]], [entity(g1, "V1")])

    def test_repro2_two_symbols_lost_on_one_number_stay_apart(self):
        """서로 다른 두 기호가 같은 순번 참조로 차례로 잃혀도 묘비가 둘이라, 한쪽만 돌아오면 그쪽 ⑤ 참조만 되찾는다."""
        places = {"TK": [0, 0, 10, 10], "V1": [20, 0, 5, 5], "V2": [40, 0, 5, 5], "PP": [80, 0, 10, 10]}
        tags = {"TK": "TK-1", "V1": "V-101", "V2": "V-102", "PP": "P-1"}
        kinds = {"TK": "tank", "V1": "manual_valve", "V2": "manual_valve", "PP": "pump"}

        def g(version, names):
            return {"project_id": None, "graph_id": "graph-T", "graph_version": version, "edges": [], "nodes": [
                {"entity_id": "entity-node-%03d" % i, "node_type": "drawing_object", "kind": kinds[x], "tag": tags[x],
                 "source_object_id": "pdf-p0-sym-%04d" % i, "id_basis": "sequence", "bbox": places[x]}
                for i, x in enumerate(names, 1)]}

        def who(gr, ref):
            n = refs.index(gr).get(ref)
            return n["tag"] if n else ("묘비" if idmap.is_tomb(ref) else None)
        g1 = g("v-1", ["TK", "V1", "V2", "PP"])
        ns = sn.new_set(g1)
        ns["nodes"] = [dict({"node_id": "S1", "name": "a", "basis": "b", "members": ["entity-node-001", "entity-node-002"]},
                            **sn._v2_fields("script")),
                       dict({"node_id": "S2", "name": "b", "basis": "b", "members": ["entity-node-003", "entity-node-004"]},
                            **sn._v2_fields("script"))]
        doc = {"schema_version": "0.3", "graph_id": "graph-T", "graph_version": "v-1", "cells": [
            {"node_id": "S1", "entries": [{"entry_id": "e1", "cause_refs": [{"ref": "graph-T#pdf-p0-sym-0002"}]}]},
            {"node_id": "S2", "entries": [{"entry_id": "e2", "cause_refs": [{"ref": "graph-T#pdf-p0-sym-0003"}]}]}]}
        seen = []
        for gr in (g("v-2", ["TK", "V2", "PP"]), g("v-3", ["TK", "PP"]), g("v-4", ["TK", "V1", "PP"])):
            ns, p = migrate.migrate_set(ns, gr, at=AT)
            doc, _ = migrate.migrate_results(doc, ns, at=AT, table=p["table"])
            seen.append([who(gr, c["entries"][0]["cause_refs"][0]["ref"]) for c in doc["cells"]])
        self.assertEqual(seen, [["묘비", "V-102"], ["묘비", "묘비"], ["V-101", "묘비"]])

    def test_repro3_scan_ids_are_checked_by_place(self):
        """스캔 추출의 순번 id(img-sym-0002)도 위치로 확인한다. 순번이 밀려도 구간과 ⑤ 원인이 같은 자리 밸브를 가리킨다."""
        from hazop.extract.adapters import raster

        def scan(g):
            for n in g["nodes"]:
                n["source_object_id"] = raster._retag_id(n["source_object_id"])
            return g
        g1 = scan(drawn("v-1", PLACES))
        ns = sn.confirm(sn.propose(g1, at=AT), g1, "r", at=AT)
        self.assertEqual(len(ns["graph_member_marks"]), len(g1["nodes"]))
        sn.save(ns)
        r1 = "graph-T#" + raster._retag_id(SID["V1"])
        doc = res.empty_results(ns, DEVS)
        doc["cells"][0]["entries"] = [{"entry_id": "e1", "cause_refs": [{"ref": r1}]}]
        rpath = res.save(doc, None)
        g2 = scan(drawn("v-2", dict(PLACES, V1=PLACES["V2"], V2=PLACES["V3"], V3=PLACES["V1"])))
        got = sn.load(g2)
        for before, after in zip(ns["nodes"], got["nodes"]):
            self.assertEqual(self.boxes(g2, after["members"]), self.boxes(g1, before["members"]))
        with open(rpath, encoding="utf-8") as fh:
            r2 = json.load(fh)["cells"][0]["entries"][0]["cause_refs"][0]["ref"]
        self.assertEqual(refs.index(g2)[r2]["bbox"], PLACES["V1"])

    def test_repro4_undo_after_migration_keeps_the_tombstone(self):
        """지운 구간의 실행 취소 기록도 같은 대응을 받는다. TK를 잃은 뒤 되돌리면 S1은 묘비만 갖고 V1을 가리키지 않는다."""
        from hazop.study import node_tools
        g1 = drawn("v-1", PLACES)
        ns = sn.propose(g1, at=AT)
        tk = entity(g1, "TK")
        holder = sn.nodes_of(ns, tk)[0]
        for m in [m for m in _find(ns, holder)["members"] if m != tk]:
            ns = sn.remove_member(ns, holder, m, at=AT)
        ns = sn.remove_member(ns, holder, tk, at=AT)
        bid = ns["batches"][-1]["batch_id"]
        g2 = drawn("v-2", PLACES, objects=[o for o in UNTAGGED if o[0] != "TK"])
        ns2, _ = migrate.migrate_set(ns, g2, at=AT)
        out, _ = node_tools.undo_batch(ns2, {"cells": []}, bid, ns2["set_rev"], "김", "user", at=AT)
        node = _find(out, holder)
        self.assertEqual(node["members"], [], "되돌린 구간이 TK 자리를 받은 다른 기호를 가리키면 안 됨")
        self.assertEqual([out["tombstones"][t]["entity_id"] for t in node["lost"]], [tk])


def _find(ns, node_id):
    return next(n for n in ns["nodes"] if n["node_id"] == node_id)


def entity_soid(g, name):
    return next(n["source_object_id"] for n in g["nodes"] if n["entity_id"] == entity(g, name))


if __name__ == "__main__":
    unittest.main()
