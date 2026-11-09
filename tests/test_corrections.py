"""② 도면 사람 수정 기록(hazop.extract.corrections)과 앱 데이터 연결(hazop.app.data) 시험. 실행: python -m unittest tests.test_corrections

작업 루트·저장 루트는 임시 폴더. 샘플 도면 SNP-M-102를 임시 작업 루트에 추출·그래프로 만들고 프로젝트 ID를 붙인다.
미확인 항목은 PDF 추출처럼 보이게 사본에 직접 넣는다(SNP-M-102 drawio에는 대상이 있는 미확인이 없음).
"""

import copy
import json
import os
import shutil
import tempfile
import unittest

from hazop import paths  # noqa: E402
from tests.test_app import build_temp_drawing

PROJECT = "corr-test"
NAME = "SNP-M-102"
COPY = "SNP-M-102-copy"


def by_sid(ext, sid):
    for key in ("nodes", "relations", "unresolved_connectors"):
        for x in ext[key]:
            if x["source_object_id"] == sid:
                return x
    return None


def unknown(ext, check, sid, field, reason="미확인"):
    obj = by_sid(ext, sid)
    ext["validation"]["unknowns"].append({"check": check, "target": obj["local_id"], "source_object_id": sid,
                                          "field": field, "reason": reason})


def without_flow(ext, sids):
    """물리 배관의 흐름 방향을 지우고 unknown_flow_direction 미확인을 넣은 사본(PDF 추출 모양)."""
    ext = copy.deepcopy(ext)
    for sid in sids:
        by_sid(ext, sid)["flow_direction"] = None
        unknown(ext, "unknown_flow_direction", sid, "flow_direction")
    return ext


def checks_of(ext, sid):
    local = by_sid(ext, sid)["local_id"]
    return sorted(u["check"] for u in ext["validation"]["unknowns"] if u.get("target") == local)


class CorrectionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-corrections-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop import paths
        from hazop.app import data
        out_dir, _ = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        path = os.path.join(out_dir, "extraction.json")
        ext = data.read_json(path)
        ext["project_id"] = PROJECT  # 등록 경로를 거친 도면처럼 프로젝트를 붙인다(지식그래프 빌드 대상)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(ext, fh, ensure_ascii=False, indent=2)
        shutil.copytree(out_dir, os.path.join(paths.output_root("추출"), COPY))
        for name in (NAME, COPY):
            data.script_module("build_graph").build_one(data.extraction_path(name), paths.output_root("그래프"))
        cls.ext = ext

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        from hazop import paths
        for name in ("도면수정", "검토구간", "분석결과"):
            shutil.rmtree(paths.folder(name), ignore_errors=True)

    def op(self, ops, base_ext, name, target, value):
        from hazop.extract import corrections
        ops.append(corrections.make_op(base_ext, name, target, value, "검토자", at="2026-11-07T00:00:00Z",
                                       existing_ops=ops))
        return ops[-1]

    # ---------------------------------------------------------------- 연산별 효과

    def test_value_ops_change_targets_and_clear_their_unknowns(self):
        from hazop.extract import corrections
        base = without_flow(self.ext, ["e4"])
        unknown(base, "missing_tag", "n6", "tag")
        unknown(base, "missing_kind", "n7", "kind")
        unknown(base, "approximate_geometry", "e13", "geometry")
        unknown(base, "missing_normal_position", "n11", "normal_position")
        ops = []
        self.op(ops, base, "set_tag", "n6", {"tag": " RC-TE999 "})
        self.op(ops, base, "set_tag", "e13", {"tag": "RC-L777"})
        self.op(ops, base, "set_kind", "n7", {"kind": "indicator", "category": "instrument"})
        self.op(ops, base, "set_flow", "e4", {"from": "j3", "to": "c2"})
        self.op(ops, base, "set_path", "e13", {"points": [[100, 100], [150, 120], [200, 100]]})
        self.op(ops, base, "confirm", "n11", {"items": [{"check": "missing_normal_position", "reason": "미확인"}]})
        out = corrections.apply(base, ops)

        n6, e13, n7, e4 = (by_sid(out, s) for s in ("n6", "e13", "n7", "e4"))
        self.assertEqual((n6["tag"], n6["attributes"]["tag"]), ("RC-TE999", "RC-TE999"))
        self.assertEqual((e13["line_no"], e13["attributes"]["line_no"]), ("RC-L777", "RC-L777"))
        self.assertEqual((n7["kind"], n7["category"], n7["classification"]), ("indicator", "instrument", "classified"))
        self.assertEqual(e4["flow_direction"], {"from": by_sid(out, "j3")["local_id"], "to": by_sid(out, "c2")["local_id"],
                                                "from_end": "target", "to_end": "source", "basis": "human"})
        self.assertEqual([ep["point"] for ep in e13["endpoints"]], [[100, 100], [200, 100]])
        self.assertEqual((e13["waypoints"], e13["geometry_source"]), ([[150, 120]], "human"))
        loc = next(l for l in out["source_locations"] if l["local_id"] == e13["local_id"])
        self.assertEqual(loc["bbox"], [100, 100, 100, 20])
        for sid in ("n6", "n7", "e4", "e13", "n11"):
            self.assertEqual(checks_of(out, sid), [], sid)
        self.assertEqual(e13["human_edit"], {"op_ids": ["c-0002", "c-0005"], "ops": ["set_tag", "set_path"],
                                             "by": "검토자", "at": "2026-11-07T00:00:00Z"})
        self.assertEqual(out["corrections"], {"ops": 6, "applied": [o["op_id"] for o in ops], "not_applicable": [],
                                              "resolved_unknowns": 5})
        self.assertEqual(out["summary"]["unknowns"], len(out["validation"]["unknowns"]))
        self.assertEqual(out["summary"]["unknowns"], base["summary"]["unknowns"])  # base 요약은 미확인을 넣기 전 값

    def test_set_endpoint_connects_unresolved_connector(self):
        from hazop.extract import corrections
        base = copy.deepcopy(self.ext)
        rel = by_sid(base, "e14")
        base["relations"].remove(rel)
        base["unresolved_connectors"].append(rel)
        rel["endpoints"][1].update(node_local_id=None, source_object_id=None, status="unconnected")
        unknown(base, "unconnected_endpoint", "e14", "target", "target 끝이 기호·분기점에 닿지 않음")
        ops = []
        self.op(ops, base, "set_endpoint", "e14", {"end": "target", "node": "n12"})
        out = corrections.apply(base, ops)
        e14 = by_sid(out, "e14")
        self.assertIn(e14, out["relations"])
        self.assertEqual(out["unresolved_connectors"], [])
        n12 = by_sid(out, "n12")
        self.assertEqual(e14["endpoints"][1]["node_local_id"], n12["local_id"])
        self.assertEqual(e14["endpoints"][1]["status"], "connected")
        g = n12["geometry"]
        self.assertEqual(e14["endpoints"][1]["point"], [g["x"] + g["width"] / 2.0, g["y"] + g["height"] / 2.0])
        self.assertEqual(e14["flow_direction"]["to"], n12["local_id"])
        self.assertEqual(checks_of(out, "e14"), [])

    def test_add_and_delete_ops(self):
        from hazop.extract import corrections
        from hazop.graph import build
        base = copy.deepcopy(self.ext)
        unknown(base, "missing_port", "e15", "target_port")
        ops = []
        add = self.op(ops, base, "add_node", None,
                      {"category": "valve", "kind": "check_valve", "tag": "RC-V900", "bbox": [500, 500, 20, 20]})
        mid = "manual-" + add["op_id"]
        self.assertIsNone(add["base"])
        self.op(ops, base, "add_relation", None, {"kind": "physical_connection", "line_type": "process",
                                                  "line_no": "RC-L900", "from": mid, "to": "n1"})
        self.op(ops, base, "set_tag", mid, {"tag": "RC-V901"})
        self.op(ops, base, "delete_node", "n12", {})
        self.op(ops, base, "delete_relation", "e24", {})
        out = corrections.apply(base, ops)

        node = by_sid(out, mid)
        self.assertEqual((node["local_id"], node["kind"], node["category"], node["tag"]),
                         (mid, "check_valve", "valve", "RC-V901"))
        rel = by_sid(out, "manual-c-0002")
        n1 = by_sid(out, "n1")
        self.assertEqual(rel["flow_direction"], {"from": mid, "to": n1["local_id"], "from_end": "source",
                                                 "to_end": "target", "basis": "human"})
        self.assertEqual(rel["endpoints"][0]["point"], [510.0, 510.0])
        for gone in ("n12", "e14", "e15", "e20", "e24"):  # n12와 그 노드에 걸린 관계
            self.assertIsNone(by_sid(out, gone), gone)
        live = {x["local_id"] for x in out["nodes"] + out["relations"]}
        self.assertTrue({l["local_id"] for l in out["source_locations"]} >= {mid, "manual-c-0002"})
        self.assertFalse([u for u in out["validation"]["unknowns"] if u.get("target") and u["target"] not in live])
        self.assertEqual(out["corrections"]["resolved_unknowns"], 1)
        self.assertEqual(out["summary"]["nodes"], len(base["nodes"]))
        self.assertEqual(build.build_graph(out)["validation"]["status"], "passed")

    # ---------------------------------------------------------------- 적용 불가

    def test_not_applicable_ops_are_skipped_and_later_ops_still_apply(self):
        from hazop.extract import corrections
        ops = []
        self.op(ops, self.ext, "set_tag", "n6", {"tag": "RC-TE111"})
        stale = self.op(ops, self.ext, "set_tag", "n7", {"tag": "RC-TT999"})
        stale["base"] = dict(stale["base"], kind="pump")
        self.op(ops, self.ext, "delete_node", "n16", {})
        ops.append({"op_id": "c-0004", "op": "set_tag", "target": "n16", "base": None, "value": {"tag": "x"}})
        ops.append({"op_id": "c-0005", "op": "set_tag", "target": "no-such", "base": None, "value": {"tag": "x"}})
        ops.append({"op_id": "c-0006", "op": "set_tag", "target": "n17", "base": None, "value": {"tag": ""}})
        self.op(ops, self.ext, "set_tag", "n21", {"tag": "RC-LT999"})
        out = corrections.apply(self.ext, ops)
        reasons = {s["op_id"]: s["reason"] for s in out["corrections"]["not_applicable"]}
        self.assertTrue(reasons["c-0002"].startswith("대상이 바뀜: kind 'pump'"))
        self.assertEqual(reasons["c-0004"], "삭제된 대상")
        self.assertEqual(reasons["c-0005"], "대상 없음")
        self.assertTrue(reasons["c-0006"].startswith("형식 오류"))
        self.assertEqual(out["corrections"]["applied"], ["c-0001", "c-0003", "c-0007"])
        self.assertEqual(by_sid(out, "n7")["tag"], by_sid(self.ext, "n7")["tag"])
        self.assertEqual(by_sid(out, "n21")["tag"], "RC-LT999")

    def test_confirm_clears_only_the_picked_unknown(self):
        from hazop.extract import corrections
        base = copy.deepcopy(self.ext)
        unknown(base, "unconnected_endpoint", "e4", None, "source 끝이 닿지 않음")
        unknown(base, "unconnected_endpoint", "e4", None, "target 끝이 닿지 않음")
        ops = []
        self.op(ops, base, "confirm", "e4", {"items": [{"check": "unconnected_endpoint", "reason": "source 끝이 닿지 않음"}]})
        out = corrections.apply(base, ops)
        left = [u["reason"] for u in out["validation"]["unknowns"] if u.get("source_object_id") == "e4"]
        self.assertEqual(left, ["target 끝이 닿지 않음"])
        unknown(base, "missing_port", "e4", None, "다시 추출 때 새로 생긴 미확인")
        self.assertIn("missing_port", checks_of(corrections.apply(base, ops), "e4"))
        with self.assertRaises(ValueError):
            corrections.make_op(base, "confirm", "e4", {"items": []}, "검토자")

    def test_renumbered_target_or_changed_reference_is_not_applicable(self):
        from hazop.extract import corrections
        ops = []
        self.op(ops, self.ext, "set_tag", "n6", {"tag": "RC-TE111"})
        self.op(ops, self.ext, "add_relation", None, {"kind": "signal_connection", "line_type": "signal",
                                                      "from": "n6", "to": "n7"})
        moved = copy.deepcopy(self.ext)
        loc = next(l for l in moved["source_locations"] if l["local_id"] == by_sid(moved, "n6")["local_id"])
        loc["bbox"] = [loc["bbox"][0] + 300, loc["bbox"][1], loc["bbox"][2], loc["bbox"][3]]
        out = corrections.apply(moved, ops)
        reasons = {s["op_id"]: s["reason"] for s in out["corrections"]["not_applicable"]}
        self.assertTrue(reasons["c-0001"].startswith("대상이 바뀜: at"))
        self.assertTrue(reasons["c-0002"].startswith("연결 대상 기기가 바뀌었거나 없음: n6"))
        self.assertEqual(corrections.apply(self.ext, ops)["corrections"]["not_applicable"], [])

    def test_newly_filled_kind_or_tag_keeps_target(self):
        """미분류였던 기호에 사전이 kind·태그를 채워도 같은 자리의 사람 수정은 그대로 적용된다(D14).
        이미 있던 kind가 다른 값으로 바뀐 것은 여전히 '대상이 바뀜'이다."""
        from hazop.extract import corrections
        ops = []
        self.op(ops, self.ext, "set_tag", "n6", {"tag": "RC-TE111"})
        ops[0]["base"] = dict(ops[0]["base"], kind=None, tag=None)
        out = corrections.apply(self.ext, ops)
        self.assertEqual(out["corrections"]["applied"], ["c-0001"])
        self.assertEqual(by_sid(out, "n6")["tag"], "RC-TE111")
        ops[0]["base"] = dict(ops[0]["base"], kind="pump")
        reasons = {s["op_id"]: s["reason"] for s in corrections.apply(self.ext, ops)["corrections"]["not_applicable"]}
        self.assertTrue(reasons["c-0001"].startswith("대상이 바뀜: kind 'pump'"))

    def test_relation_becoming_measurement_keeps_target(self):
        """끝 기호가 계기로 밝혀져 같은 선이 physical → measurement로 바뀌어도 그 선의 사람 수정은 적용된다(D14)."""
        from hazop.extract import corrections
        rel = next(r for r in self.ext["relations"] if r["kind"] == "physical_connection")
        ops = []
        self.op(ops, self.ext, "delete_relation", rel["source_object_id"], {})
        changed = copy.deepcopy(self.ext)
        next(r for r in changed["relations"] if r["source_object_id"] == rel["source_object_id"])["kind"] = \
            "measurement_connection"
        self.assertEqual(corrections.apply(changed, ops)["corrections"]["applied"], ["c-0001"])

    def test_set_kind_drops_properties_the_new_kind_cannot_have(self):
        from hazop.extract import corrections
        base = copy.deepcopy(self.ext)
        node = by_sid(base, "n6")
        node["attributes"] = {"valve_type": "gate", "note": "keep"}
        ops = []
        self.op(ops, base, "set_kind", "n6", {"kind": "drain", "category": "inline_component"})
        out = by_sid(corrections.apply(base, ops), "n6")
        self.assertEqual(out["attributes"], {"note": "keep", "kind": "drain"})

    def test_renumbered_target_is_found_by_position(self):
        """다시 추출로 id만 바뀐 같은 대상(같은 종류·태그·위치)은 새 id로 적용하고 retargeted에 남긴다(D14)."""
        from hazop.extract import corrections
        ops = []
        self.op(ops, self.ext, "set_tag", "n6", {"tag": "RC-TE111"})
        moved = copy.deepcopy(self.ext)
        by_sid(moved, "n6")["source_object_id"] = "n6-renumbered"
        out = corrections.apply(moved, ops)
        self.assertEqual(out["corrections"]["applied"], ["c-0001"])
        self.assertEqual(out["corrections"]["retargeted"], [{"op_id": "c-0001", "from": "n6", "to": "n6-renumbered"}])
        self.assertEqual(by_sid(out, "n6-renumbered")["tag"], "RC-TE111")

    def test_two_candidates_at_same_position_are_not_guessed(self):
        from hazop.extract import corrections
        ops = []
        self.op(ops, self.ext, "set_tag", "n6", {"tag": "RC-TE111"})
        moved = copy.deepcopy(self.ext)
        twin = copy.deepcopy(by_sid(moved, "n6"))
        by_sid(moved, "n6")["source_object_id"] = "n6-a"
        twin.update(source_object_id="n6-b", local_id=twin["local_id"] + "-b")
        moved["nodes"].append(twin)
        loc = copy.deepcopy(next(l for l in moved["source_locations"] if l["local_id"] == by_sid(moved, "n6-a")["local_id"]))
        loc["local_id"] = twin["local_id"]
        moved["source_locations"].append(loc)
        out = corrections.apply(moved, ops)
        self.assertEqual(out["corrections"]["applied"], [])
        self.assertNotIn("retargeted", out["corrections"])

    def test_make_op_rejects_invalid_ops(self):
        from hazop.extract import corrections
        bad = [("rename", "n1", {}), ("set_tag", "nope", {"tag": "a"}), ("set_kind", "n1", {"kind": "pump", "category": "valve"}),
               ("set_flow", "e9", {"from": "n6", "to": "n7"}), ("set_flow", "e4", {"from": "n1", "to": "j3"}),
               ("add_node", "n1", {"category": "valve", "kind": "psv", "bbox": [0, 0, 1, 1]}),
               ("set_path", "e4", {"points": [[0, 0]]}), ("set_tag", "manual-c-0009", {"tag": "a"})]
        for op, target, value in bad:
            with self.assertRaises(ValueError, msg=op):
                corrections.make_op(self.ext, op, target, value, "검토자")

    def test_apply_never_mutates_input_and_empty_ops_keep_graph_version(self):
        from hazop.extract import corrections
        from hazop.graph import build
        snap = json.dumps(self.ext, sort_keys=True)
        ops = []
        self.op(ops, self.ext, "delete_node", "n1", {})
        corrections.apply(self.ext, ops)
        self.assertEqual(json.dumps(self.ext, sort_keys=True), snap)
        same = corrections.apply(self.ext, [])
        self.assertNotIn("corrections", same)
        self.assertEqual(build.build_graph(same)["graph_version"], build.build_graph(self.ext)["graph_version"])

    def test_unknown_ratio_drops_when_reviewer_sets_flows(self):
        from hazop.extract import corrections
        sids = ["e4", "e5", "e13", "e14", "e15"]
        base = without_flow(self.ext, sids)
        ops = []
        for sid in sids:
            ends = [ep["source_object_id"] for ep in by_sid(base, sid)["endpoints"]]
            self.op(ops, base, "set_flow", sid, {"from": ends[0], "to": ends[1]})
        out = corrections.apply(base, ops)
        n = len(base["nodes"]) + len(base["relations"])
        self.assertAlmostEqual(corrections.unknown_ratio(base), (3 + len(sids)) / n)
        self.assertAlmostEqual(corrections.unknown_ratio(out), 3 / n)

    # ---------------------------------------------------------------- 저장·다시 추출·앱 연결

    def test_save_then_reload_gives_same_corrected_result(self):
        from hazop.app import data
        from hazop.extract import corrections
        ops = []
        self.op(ops, self.ext, "set_tag", "n1", {"tag": "RC-PZ99"})
        corrections.save(NAME, ops, "검토자", drawing_number=NAME)
        self.op(ops, self.ext, "set_tag", "n6", {"tag": "RC-TE99"})
        del ops[0]
        path = corrections.save(NAME, ops, "검토자B")
        doc = corrections.load(NAME)
        self.assertEqual(path, corrections.store_path(NAME))
        self.assertEqual(doc["drawing_number"], NAME)
        self.assertEqual([(e["by"], e["added"], e["removed"]) for e in doc["log"]],
                         [("검토자", ["c-0001"], []), ("검토자B", ["c-0002"], ["c-0001"])])
        original, saved = data.load_extraction(NAME)
        self.assertEqual(saved, corrections.apply(original, ops))
        self.assertEqual(data.load_extraction(NAME, ops=[])[1], original)

    def test_op_ids_are_never_reissued_after_removal(self):
        """저장했다가 지운 op_id(=manual- ID)는 다시 쓰지 않고, 지운 연산 내용은 log에 남는다."""
        from hazop.extract import corrections
        self.assertEqual(corrections.issued_op_ids(NAME), set())
        value = {"category": "equipment", "kind": "pump", "tag": "RC-P900", "bbox": [500, 500, 20, 20]}
        first = corrections.make_op(self.ext, "add_node", None, value, "검토자")
        corrections.save(NAME, [first], "검토자", drawing_number=NAME)
        corrections.save(NAME, [], "검토자")
        again = corrections.make_op(self.ext, "add_node", None, dict(value, tag="RC-P901"), "검토자",
                                    used_ids=corrections.issued_op_ids(NAME))
        self.assertNotEqual(again["op_id"], first["op_id"], "빈 기록으로 저장한 뒤에도 새 번호")
        corrections.save(NAME, [again], "검토자")
        doc = corrections.load(NAME)
        self.assertEqual(doc["log"][1]["removed"], [first["op_id"]])
        self.assertEqual(doc["log"][1]["removed_ops"], [first], "지운 사람 수정 내용이 기록에 남음")
        self.assertEqual(corrections.issued_op_ids(NAME), {first["op_id"], again["op_id"]})

    def test_load_rejects_other_kind(self):
        from hazop.extract import corrections
        os.makedirs(os.path.dirname(corrections.store_path(NAME)))
        with open(corrections.store_path(NAME), "w", encoding="utf-8") as fh:
            json.dump({"kind": "something_else"}, fh)
        with self.assertRaises(ValueError):
            corrections.load(NAME)

    def test_reextraction_keeps_corrections_and_original_file(self):
        from hazop import paths
        from hazop.app import data
        from hazop.extract import corrections
        path = data.extraction_path(COPY)
        with open(path, "rb") as fh:
            before = fh.read()
        ops = []
        self.op(ops, self.ext, "set_tag", "n1", {"tag": "RC-PZ55"})
        data.save_corrections(COPY, ops, "검토자")
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        with open(path, "wb") as fh:  # 다시 추출: extraction.json만 새로 써진다
            fh.write(before)
        bg = data.script_module("build_graph")
        graph, _ = bg.build_one(path, paths.output_root("그래프"))
        self.assertIn("RC-PZ55", {n["tag"] for n in graph["nodes"]})
        corrections.save(COPY, [], "검토자")
        graph, _ = bg.build_one(path, paths.output_root("그래프"))
        self.assertNotIn("RC-PZ55", {n["tag"] for n in graph["nodes"]})

    def test_tag_conflicts_finds_other_drawing_and_skips_excluded(self):
        from hazop.app import data
        n1 = by_sid(self.ext, "n1")
        hits = data.tag_conflicts(" rc-pz01 ", PROJECT, (NAME, n1["local_id"]))
        self.assertEqual(hits, [{"name": COPY, "local_id": n1["local_id"]}])
        both = {(NAME, n1["local_id"]), (COPY, n1["local_id"])}
        self.assertEqual(data.tag_conflicts("RC-PZ01", PROJECT, both), [])
        self.assertEqual(data.tag_conflicts("RC-PZ01", "other-project", ()), [])
        self.assertEqual(data.tag_conflicts("  ", PROJECT, ()), [])
        ops = []
        self.op(ops, self.ext, "set_tag", "n1", {"tag": "RC-PZ77"})
        from hazop.extract import corrections
        corrections.save(COPY, ops, "검토자")
        self.assertEqual(data.tag_conflicts("RC-PZ01", PROJECT, (NAME, n1["local_id"])), [])

    def test_save_corrections_rebuilds_graph_and_kg_and_flags_saved_study(self):
        from hazop import paths
        from hazop.app import data
        from hazop.study import nodes, results
        bg = data.script_module("build_graph")
        graph, _ = bg.build_one(data.extraction_path(NAME), paths.output_root("그래프"))
        node_set = nodes.confirm(nodes.propose(graph), graph, "검토자A")
        ns_path = nodes.save(node_set)
        res_path = results.save(results.empty_results(node_set, results.load_deviations()), PROJECT)
        saved = {}
        for p in (ns_path, res_path):
            with open(p, "rb") as fh:
                saved[p] = fh.read()
        ops = []
        self.op(ops, self.ext, "set_tag", "n1", {"tag": "RC-PZ02"})
        out = data.save_corrections(NAME, ops, "검토자")
        self.assertEqual(out["path"], os.path.join(paths.folder("도면수정"), NAME + ".json"))
        self.assertNotEqual(out["graph"]["graph_version"], graph["graph_version"])
        on_disk = data.read_json(os.path.join(paths.output_root("그래프"), NAME, "graph.json"))
        self.assertEqual(on_disk["graph_version"], out["graph"]["graph_version"])
        self.assertNotIn("kg_error", out)
        self.assertIn(out["graph"]["graph_version"], json.dumps(out["kg"]["kg"]["graph_refs"]))
        self.assertEqual(len(out["recheck"]), 2)
        self.assertIn("확정본", out["recheck"][0])
        self.assertIn("분석 결과", out["recheck"][1])
        for p, b in saved.items():
            with open(p, "rb") as fh:
                self.assertEqual(fh.read(), b, p)
        again = data.save_corrections(NAME, ops, "검토자")
        self.assertEqual(again["graph"]["graph_version"], out["graph"]["graph_version"])

    def test_viewer_uses_working_ops(self):
        from hazop.app import data
        ops = []
        self.op(ops, self.ext, "set_tag", "n1", {"tag": "RC-PZ03"})
        info = data.viewer_html_for(NAME, ops=ops)
        self.assertIsNone(info["error"])
        self.assertEqual(by_sid(info["corrected"], "n1")["tag"], "RC-PZ03")
        self.assertEqual(by_sid(info["original"], "n1")["tag"], "RC-PZ01")
        self.assertIn("RC-PZ03", {n["tag"] for n in info["graph"]["nodes"]})
        with open(info["html"], encoding="utf-8") as fh:
            self.assertIn("RC-PZ03", fh.read())
        self.assertNotIn("corrections", data.viewer_html_for(NAME)["corrected"])


if __name__ == "__main__":
    unittest.main()
