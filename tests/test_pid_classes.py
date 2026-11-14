"""M2 P&ID 클래스 확장 시험: 배관 부품 분류·새 kind, ISA 태그 파서, 속성 사전 검사(경고만), 정상·고장 위치 수정 연산,
분류 이동이 판 이전에 주는 영향. 실행: python -m unittest tests.test_pid_classes

저장은 임시 HAZOP_WORK_ROOT 아래에만 한다. 근거: 기획서/지식그래프-스키마-사전.md §2.1, §4, 본문 §8.2 M2, §9 U9·U10.
"""

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
from hazop.analysis import equipment  # noqa: E402
from hazop.extract import corrections, isa, properties, rules  # noqa: E402
from hazop.graph import build as gb  # noqa: E402
from hazop.kg import schema, screen  # noqa: E402
from hazop.study import migrate  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402

AT = "2026-11-08T00:00:00Z"


def _data():
    return copy.deepcopy(schema.REGISTRY.data)


def _cls(data, cid):
    return next(c for c in data["classes"] if c["id"] == cid)


class ClassesTest(unittest.TestCase):
    def test_inline_component_category_and_moved_kinds(self):
        r = schema.REGISTRY
        self.assertEqual(r.label("inline_component"), "배관 부품")
        for k in ("orifice", "vent", "drain", "strainer", "reducer", "flow_element", "blind_flange"):
            self.assertEqual(rules.KIND_CATEGORY[k], "inline_component", k)
        for k in ("filter", "demineralizer", "compressor", "fan", "accumulator"):
            self.assertEqual(rules.KIND_CATEGORY[k], "equipment", k)  # U9: 필터·탈염기는 설비 유지
        for k in ("air_operated_valve", "solenoid_valve", "relief_valve", "rupture_disc"):
            self.assertEqual(rules.KIND_CATEGORY[k], "valve", k)
        self.assertEqual(rules.KIND_CATEGORY["switch"], "instrument")
        self.assertEqual(rules.KIND_CATEGORY["nozzle"], "piping_element")

    def test_kind_labels_follow_dictionary(self):
        r = schema.REGISTRY
        for k, label in (("reactor_vessel", "원자로용기"), ("temperature_element", "온도소자"), ("pipe_cap", "끝막음"),
                         ("psv", "안전밸브"), ("relief_valve", "방출밸브"), ("rupture_disc", "파열판"),
                         ("flow_element", "유량요소"), ("blind_flange", "맹플랜지"), ("recorder", "기록계")):
            self.assertEqual(r.label(r.kind_class[k]), label)

    def test_legend_has_inline_component_with_token(self):
        from hazop.app import tokens
        types, _, _ = screen.legend_tables()
        self.assertEqual(types["inline_component"], {"layer": "pid", "name": "배관 부품", "col": "kg-inline_component",
                                                     "shape": "circle"})
        self.assertEqual(list(types).index("inline_component"), list(types).index("valve") + 1)
        for t in types.values():
            self.assertIn(t["col"], tokens.COLORS)

    def test_inline_component_is_still_real_equipment_for_analysis(self):
        self.assertIn("inline_component", equipment.EQUIPMENT_CATEGORIES)
        self.assertIn("orifice", equipment.EQUIPMENT_KINDS)
        self.assertNotIn("nozzle", equipment.EQUIPMENT_KINDS)
        self.assertIn("nozzle", equipment.CONNECTION_KINDS)

    def test_property_dictionary(self):
        r = schema.REGISTRY
        self.assertEqual(r.properties["normal_position"]["values"], ["NO", "NC", "LO", "LC"])
        self.assertEqual(r.properties["fail_position"]["values"], ["FO", "FC", "FL", "FAI"])
        self.assertEqual(rules.KINDS_NEED_NORMAL_POSITION,
                         {"manual_valve", "motor_operated_valve", "air_operated_valve", "solenoid_valve",
                          "control_valve", "isolation_valve", "psv"})
        self.assertNotIn("check_valve", rules.KINDS_NEED_NORMAL_POSITION)
        self.assertEqual(rules.KINDS_NEED_FAIL_POSITION,
                         {"motor_operated_valve", "air_operated_valve", "solenoid_valve", "control_valve"})
        self.assertIn("set_pressure", r.class_properties("psv"))
        self.assertIn("normal_position", r.class_properties("check_valve"))  # 상속(밸브 공통)

    def test_registry_rejects_bad_properties(self):
        cases = [
            (lambda d: d["properties"].append({"id": "x", "type": "enum", "label_ko": "x"}), "values"),
            (lambda d: d["properties"].append({"id": "x", "type": "color", "label_ko": "x"}), "type("),
            (lambda d: d["properties"][0].update(unit="m"), "모르는 키"),
            (lambda d: _cls(d, "pump").update(properties=["no_such"]), "속성 no_such가 없음"),
            (lambda d: _cls(d, "pump").update(required=["normal_position"]), "required normal_position"),
            (lambda d: d["properties"].append(dict(d["properties"][0])), "id 중복"),
        ]
        for mutate, needle in cases:
            with self.subTest(needle=needle):
                d = _data()
                mutate(d)
                probs = schema.validate(d)
                self.assertTrue(any(needle in p for p in probs), probs)

    def test_registry_without_properties_still_loads(self):
        d = _data()
        del d["properties"]
        for c in d["classes"]:
            c.pop("properties", None)
            c.pop("required", None)
        self.assertEqual(schema.validate(d), [])


class IsaTest(unittest.TestCase):
    def test_parses_sample_tags(self):
        cases = {
            "RC-PT101": ("RC", "P", None, "T", "101", None),
            "CV-PIC201": ("CV", "P", None, "IC", "201", None),
            "RC-TE110": ("RC", "T", None, "E", "110", None),
            "FW-FIC503": ("FW", "F", None, "IC", "503", None),
            "PDT-102A": (None, "P", "D", "T", "102", "A"),
            "FQI 7": (None, "F", "Q", "I", "7", None),
            "rc-lt110": ("RC", "L", None, "T", "110", None),
        }
        for tag, (prefix, mv, mod, fn, loop, suffix) in cases.items():
            with self.subTest(tag=tag):
                p = isa.parse_tag(tag)
                self.assertEqual((p["system_prefix"], p["measured_variable"], p["variable_modifier"], p["functions"],
                                  p["loop_no"], p["suffix"]), (prefix, mv, mod, fn, loop, suffix))
                self.assertIn("[일반지식]", p["basis"])

    def test_failure_is_none(self):
        for tag in (None, "", "RC-V001", "PT", "RC-L001-T4", "RC-PSV101-X", 12, "온도계-1"):
            self.assertIsNone(isa.parse_tag(tag), tag)

    def test_graph_adds_isa_only_to_instruments_and_keeps_tag(self):
        ext = _tiny_extraction()
        g = gb.build_graph(ext)
        by_tag = {n["tag"]: n for n in g["nodes"] if n["node_type"] == "drawing_object"}
        self.assertEqual(by_tag["RC-PT101"]["isa"]["loop_no"], "101")
        self.assertIsNone(by_tag["RC-XX"]["isa"])
        self.assertNotIn("isa", by_tag["RC-V001"])
        self.assertEqual(by_tag["RC-PT101"]["tag"], "RC-PT101")
        self.assertEqual(gb.build_graph(ext)["graph_version"], g["graph_version"])


class PropertyCheckTest(unittest.TestCase):
    def issues(self, kind, attrs):
        return [(c, f) for c, f, _ in properties.node_issues(kind, attrs)]

    def test_required_and_enum_values(self):
        self.assertEqual(self.issues("control_valve", {"kind": "control_valve", "tag": "PV-1"}),
                         [("missing_normal_position", "normal_position"), ("missing_fail_position", "fail_position")])
        self.assertEqual(self.issues("control_valve", {"normal_position": "OPEN", "fail_position": "FAI"}),
                         [("invalid_normal_position", "normal_position")])
        self.assertEqual(self.issues("check_valve", {}), [])
        self.assertEqual(self.issues("check_valve", {"normal_position": "XX"}), [("invalid_normal_position", "normal_position")])
        self.assertEqual(self.issues("air_operated_valve", {"normal_position": "NC", "fail_position": "FC"}), [])

    def test_quantity_and_unknown_names(self):
        self.assertEqual(self.issues("psv", {"normal_position": "NC", "set_pressure": "17.2 MPa"}), [])
        self.assertEqual(self.issues("psv", {"normal_position": "NC", "set_pressure": "미정"}),
                         [("invalid_set_pressure", "set_pressure")])
        self.assertEqual(self.issues("pump", {"normal_postion": "NO", "symbol_id": "x"}),
                         [("unknown_attribute", "normal_postion")])
        self.assertEqual(self.issues(None, {"kind": None}), [])  # kind 없음은 추출기가 따로 기록

    def test_legacy_reasons_kept_for_confirmed_unknowns(self):
        out = {c: r for c, _, r in properties.node_issues("manual_valve", {})}
        self.assertEqual(out["missing_normal_position"], "밸브 정상 위치 미확인")
        out = {c: r for c, _, r in properties.node_issues("manual_valve", {"normal_position": "X"})}
        self.assertEqual(out["invalid_normal_position"], "규칙에 없는 값 'X'")

    def test_samples_have_no_unknown_attribute_warnings(self):
        import glob
        from hazop.extract import drawio
        for f in sorted(glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio"))):
            checks = [u["check"] for u in drawio.extract(f)["validation"]["unknowns"]]
            self.assertNotIn("unknown_attribute", checks, f)
            self.assertFalse([c for c in checks if c.startswith("invalid_")], f)


def _tiny_extraction():
    """밸브 2개(수동·제어)와 계기 2개, 물리 배관 1개짜리 추출 결과."""
    def node(i, kind, tag, attrs=None):
        return {"local_id": "local-node-%03d" % i, "source_object_id": "s%d" % i, "classification": "classified",
                "category": rules.KIND_CATEGORY[kind], "kind": kind, "tag": tag, "label": tag, "label_text": tag,
                "attributes": dict({"kind": kind, "tag": tag}, **(attrs or {})), "style": None, "parent": None,
                "geometry": {"x": i * 50, "y": 0, "width": 20, "height": 20}}
    nodes = [node(1, "manual_valve", "RC-V001", {"normal_position": "NO"}),
             node(2, "control_valve", "RC-PV101", {"normal_position": "NC"}),
             node(3, "transmitter", "RC-PT101"), node(4, "indicator", "RC-XX")]
    rel = {"local_id": "local-edge-001", "source_object_id": "e1", "kind": "physical_connection", "line_type": "process",
           "line_no": "RC-L001", "endpoints": [
               {"end": "source", "node_local_id": "local-node-001", "source_object_id": "s1", "constraint": None,
                "point": [10, 10], "point_basis": "x", "status": "connected", "port": None},
               {"end": "target", "node_local_id": "local-node-002", "source_object_id": "s2", "constraint": None,
                "point": [60, 10], "point_basis": "x", "status": "connected", "port": None}],
           "flow_direction": None, "waypoints": [], "label": "", "label_text": "", "label_cells": [], "attributes": {},
           "style": None, "parent": None, "geometry": None}
    locs = [{"object_id": n["source_object_id"], "local_id": n["local_id"], "coordinate_space": "page_local_2d",
             "unit": "canvas_unit", "bbox": [n["geometry"]["x"], 0, 20, 20], "approximate": False} for n in nodes]
    unknowns = [{"check": "missing_fail_position", "target": "local-node-002", "source_object_id": "s2",
                 "field": "fail_position", "reason": "밸브 고장 위치 미확인"}]
    ext = {"schema_version": "0.1", "project_id": None, "extraction_run_id": "run-t",
           "drawing": {"drawing_number": "T-1", "ignored_objects": []},
           "coordinate_system": {"coordinate_space": "page_local_2d", "unit": "canvas_unit"},
           "nodes": nodes, "relations": [rel], "unresolved_connectors": [], "texts": [], "unclassified": [],
           "source_locations": locs, "validation": {"status": "passed", "blockers": [], "unknowns": unknowns}}
    from hazop.extract.drawio import summarize
    ext["summary"] = summarize(ext)
    return ext


class PositionOpsTest(unittest.TestCase):
    def make(self, ext, op, target, value, ops=()):
        return corrections.make_op(ext, op, target, value, "검토자", at=AT, existing_ops=list(ops))

    def test_set_positions_change_attribute_and_clear_unknown(self):
        ext = _tiny_extraction()
        ops = [self.make(ext, "set_fail_position", "s2", {"value": "FC"})]
        ops.append(self.make(ext, "set_normal_position", "s1", {"value": "LC"}, ops))
        out = corrections.apply(ext, ops)
        by = {n["source_object_id"]: n for n in out["nodes"]}
        self.assertEqual(by["s2"]["attributes"]["fail_position"], "FC")
        self.assertEqual(by["s1"]["attributes"]["normal_position"], "LC")
        self.assertEqual(out["validation"]["unknowns"], [])
        self.assertEqual(out["corrections"]["resolved_unknowns"], 1)
        self.assertEqual(by["s2"]["human_edit"]["ops"], ["set_fail_position"])
        self.assertEqual(ext["nodes"][1]["attributes"].get("fail_position"), None)  # 원본은 그대로

    def test_rejects_bad_value_and_wrong_kind(self):
        ext = _tiny_extraction()
        with self.assertRaisesRegex(ValueError, "정상 위치는 NO/NC/LO/LC"):
            self.make(ext, "set_normal_position", "s1", {"value": "OPEN"})
        with self.assertRaisesRegex(ValueError, "고장 위치를 두지 않음"):
            self.make(ext, "set_fail_position", "s1", {"value": "FC"})  # 수동 밸브에는 고장 위치가 없음
        with self.assertRaisesRegex(ValueError, "정상 위치를 두지 않음"):
            self.make(ext, "set_normal_position", "s3", {"value": "NO"})  # 전송기
        with self.assertRaisesRegex(ValueError, "relation 대상"):
            self.make(ext, "set_normal_position", "e1", {"value": "NO"})

    def test_confirm_saved_with_old_reason_still_clears_unknown(self):
        ext = _tiny_extraction()
        op = self.make(ext, "confirm", "s2", {"items": [{"check": "missing_fail_position", "reason": "밸브 고장 위치 미확인"}]})
        op["value"]["items"][0]["reason"] = "제어밸브 실패 위치 미확인"   # M2 이전에 저장된 확정 기록
        out = corrections.apply(ext, [op])
        self.assertEqual(out["corrections"]["not_applicable"], [])
        self.assertEqual(out["validation"]["unknowns"], [])

    def test_legacy_digest_is_upgraded_while_version_is_same(self):
        g0 = gb.build_graph(_tiny_extraction())
        ns = sn.confirm(sn.propose(g0, at=AT), g0, "검토자A", at=AT)
        fresh = dict(ns["member_digest"])
        ns["member_digest"], ns["legacy"] = {}, {"member_digest": migrate.legacy_member_digest(g0)}  # 0.1에서 바꾼 집합
        up = migrate.with_refs(ns, g0)
        self.assertEqual(up["member_digest"], fresh, "판이 같을 때 구간 지문(md3)으로 채움")
        ext = _tiny_extraction()
        g1 = gb.build_graph(corrections.apply(ext, [self.make(ext, "set_normal_position", "s1", {"value": "NC"})]))
        self.assertTrue(migrate.plan(up, g1)["recheck"])

    def test_kind_change_before_position_is_checked_at_apply(self):
        ext = _tiny_extraction()
        ops = [self.make(ext, "set_kind", "s1", {"kind": "control_valve", "category": "valve"})]
        ops.append(self.make(ext, "set_fail_position", "s1", {"value": "FO"}, ops))
        out = corrections.apply(ext, ops)
        self.assertEqual(out["nodes"][0]["attributes"]["fail_position"], "FO")
        skipped = corrections.apply(ext, ops[1:])["corrections"]["not_applicable"]
        self.assertEqual(len(skipped), 1)

    def test_position_edit_sends_confirmed_span_to_recheck(self):
        """정상·고장 위치는 ⑤ 판단이 기대므로 판정 해시에 들어간다. 고치면 판이 바뀌고 확정 구간은 재확인으로 간다."""
        ext = _tiny_extraction()
        g0 = gb.build_graph(ext)
        ns = sn.confirm(sn.propose(g0, at=AT), g0, "검토자A", at=AT)
        ops = [self.make(ext, "set_normal_position", "s1", {"value": "NC"})]
        g1 = gb.build_graph(corrections.apply(ext, ops))
        self.assertNotEqual(g1["graph_version"], g0["graph_version"])
        hit = set(sn.nodes_of(ns, next(n["entity_id"] for n in g0["nodes"] if n["source_object_id"] == "s1")))
        self.assertLessEqual(hit, set(migrate.plan(ns, g1)["recheck"]))
        tag_ops = [self.make(ext, "set_tag", "s1", {"tag": "RC-V009"})]
        self.assertLessEqual(hit, set(migrate.plan(ns, gb.build_graph(corrections.apply(ext, tag_ops)))["recheck"]))

    def test_ops_saved_before_m2_still_apply_to_moved_kinds(self):
        """M2 이전 수정 기록: 오리피스 지문(base·refs)의 분류가 equipment여도, set_kind·add_node 값이 equipment여도 적용된다."""
        old = _tiny_extraction()
        old["nodes"][0].update(kind="orifice", category="equipment")
        ops = [self.make(old, "set_tag", "s1", {"tag": "RC-FO09"})]
        ops.append(self.make(old, "set_flow", "e1", {"from": "s2", "to": "s1"}, ops))
        ops.append(self.make(old, "set_kind", "s2", {"kind": "vent", "category": "equipment"}, ops))
        ops.append(self.make(old, "add_node", None, {"kind": "orifice", "category": "equipment", "tag": "RC-FO10",
                                                     "bbox": [0, 50, 10, 10]}, ops))
        new = copy.deepcopy(old)
        new["nodes"][0]["category"] = "inline_component"   # M2 이후 다시 추출한 결과
        out = corrections.apply(new, ops)
        self.assertEqual(out["corrections"]["not_applicable"], [])
        by = {n["source_object_id"]: n for n in out["nodes"]}
        self.assertEqual(by["s1"]["tag"], "RC-FO09")
        self.assertEqual((by["s2"]["kind"], by["s2"]["category"]), ("vent", "inline_component"))
        self.assertEqual(by["manual-c-0004"]["category"], "inline_component")
        with self.assertRaisesRegex(ValueError, "category는 equipment"):
            self.make(new, "set_kind", "s2", {"kind": "pump", "category": "valve"})


class DigestTest(unittest.TestCase):
    def graph(self, kind_cat):
        ext = _tiny_extraction()
        for n in ext["nodes"]:
            if n["source_object_id"] == "s1":
                n["kind"], n["category"] = kind_cat
        return gb.build_graph(ext)

    def test_category_only_change_is_kept(self):
        g0 = self.graph(("orifice", "equipment"))       # M2 이전 분류
        ns = sn.confirm(sn.propose(g0, at=AT), g0, "검토자A", at=AT)
        g1 = copy.deepcopy(g0)
        g1["graph_version"] = "v-new"
        next(n for n in g1["nodes"] if n["source_object_id"] == "s1")["category"] = "inline_component"
        self.assertEqual((migrate.plan(ns, g1)["state"], migrate.plan(ns, g1)["recheck"]), ("kept", {}))
        moved, _ = migrate.migrate_set(ns, g1, at=AT)
        self.assertTrue(all(d.startswith("md3-") for d in moved["member_digest"].values()))

    def test_legacy_digest_compares_with_old_categories(self):
        g_old = self.graph(("orifice", "equipment"))
        ns = sn.confirm(sn.propose(g_old, at=AT), g_old, "검토자A", at=AT)
        legacy = migrate._digest(g_old, "md-", lambda n: n.get("category"))  # M2 이전 계산식 그대로
        ns["member_digest"], ns["legacy"] = {}, {"member_digest": legacy}  # 0.1에서 바꾼 집합(구간 지문 없음)
        g_new = self.graph(("orifice", "inline_component"))
        g_new["graph_version"] = "v-new"
        self.assertEqual(migrate.legacy_member_digest(g_new), legacy)
        self.assertEqual(migrate.plan(ns, g_new)["recheck"], {})
        g_kind = self.graph(("vent", "inline_component"))   # kind가 실제로 바뀌면 재확인
        g_kind["graph_version"] = "v-kind"
        self.assertTrue(migrate.plan(ns, g_kind)["recheck"])

    def test_legacy_digest_treats_new_kinds_as_unclassified_then(self):
        g = self.graph(("drain", "inline_component"))
        before = copy.deepcopy(g)
        next(n for n in before["nodes"] if n["source_object_id"] == "s1")["category"] = None
        self.assertEqual(migrate.legacy_member_digest(g), migrate._digest(before, "md-", lambda n: n.get("category")))


class PositionUiTest(unittest.TestCase):
    def test_kind_label_and_position_rows(self):
        from hazop.app.screens import viewer
        self.assertEqual(viewer.kind_label("orifice"), "배관 부품 · 오리피스")
        self.assertEqual(viewer.kind_label("nope"), "미분류 · nope")
        self.assertEqual(viewer.position_props("control_valve"),
                         [("set_normal_position", "normal_position"), ("set_fail_position", "fail_position")])
        self.assertEqual(viewer.position_props("check_valve"), [("set_normal_position", "normal_position")])
        self.assertEqual(viewer.position_props("pump"), [])
        self.assertEqual(viewer.OP_LABELS["set_fail_position"], "고장 위치")


class SaveRebuildTest(unittest.TestCase):
    """② 저장 경로(hazop.app.data.save_corrections): 위치 수정 저장 → 그래프 다시 빌드 → 확정 구간 판 이전."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-m2-")
        self._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(self.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(self.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_position_rebuilds_graph_and_asks_recheck(self):
        from tests.test_app import build_temp_drawing
        from hazop.app import data
        out_dir, graph = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        name = os.path.basename(out_dir)
        ext = data.read_json(os.path.join(out_dir, "extraction.json"))
        node_set = sn.confirm(sn.propose(graph, at=AT), graph, "검토자A", at=AT)
        sn.save(node_set)
        op = corrections.make_op(ext, "set_normal_position", "n11", {"value": "NC"}, "검토자", at=AT)
        res = data.save_corrections(name, [op], "검토자")
        g1 = res["graph"]
        self.assertNotEqual(g1["graph_version"], graph["graph_version"])
        node = next(n for n in g1["nodes"] if n["source_object_id"] == "n11")
        self.assertEqual(node["attributes"]["normal_position"], "NC")
        self.assertEqual(node["origin"], "human_edit")
        self.assertEqual(res["recheck"], ["④ 검토구간 확정본이 고치기 전 도면 기준입니다. 재확인이 필요합니다."])
        moved = sn.load(g1)  # ④가 열면 판 이전: 고친 요소가 든 구간만 확정을 푼다(규격 §2.6)
        self.assertFalse(sn.is_stale(moved, g1))
        n11 = node["entity_id"]
        self.assertEqual({n["state"] for n in moved["nodes"] if n11 in n["members"]}, {"applied"})
        with open(corrections.store_path(name), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["ops"][0]["op"], "set_normal_position")


if __name__ == "__main__":
    unittest.main()
