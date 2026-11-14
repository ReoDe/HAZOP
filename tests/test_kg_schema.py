"""타입 레지스트리(hazop/kg/schema) 형식 검사와 '레지스트리 조회 결과 = M0 이전 고정 목록' 동치 검사.
M2(2026-11-08)에서 P&ID 분류가 바뀐 부분(배관 부품, 새 kind)은 차이만 따로 적어 검사한다."""

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest

import networkx as nx

from hazop.extract import rules
from hazop.kg import algo, auto, build, context, schema, screen

# ---- M0 이전(3dd3312) 코드에 있던 고정 목록 그대로
OLD_KIND_CATEGORY = {}
for _k in ("reactor_vessel", "steam_generator", "pressurizer", "pump", "vessel", "tank",
           "heat_exchanger", "turbine", "condenser", "filter", "demineralizer", "orifice", "vent"):
    OLD_KIND_CATEGORY[_k] = "equipment"
for _k in ("manual_valve", "motor_operated_valve", "control_valve", "check_valve", "isolation_valve", "psv"):
    OLD_KIND_CATEGORY[_k] = "valve"
for _k in ("transmitter", "controller", "indicator", "temperature_element"):
    OLD_KIND_CATEGORY[_k] = "instrument"
for _k in ("tee", "pipe_cap", "continuation"):
    OLD_KIND_CATEGORY[_k] = "piping_element"
# M2: 오리피스·벤트는 배관 부품으로 이동(U9), 새 kind(사전 §2.1)
M2_MOVED = {"orifice": "inline_component", "vent": "inline_component"}
M2_NEW_KINDS = {
    "compressor": "equipment", "fan": "equipment", "accumulator": "equipment",
    "air_operated_valve": "valve", "solenoid_valve": "valve", "relief_valve": "valve", "rupture_disc": "valve",
    "drain": "inline_component", "strainer": "inline_component", "reducer": "inline_component",
    "flow_element": "inline_component", "blind_flange": "inline_component",
    "switch": "instrument", "recorder": "instrument", "nozzle": "piping_element",
}
# 기호 사전 연결(레지스트리 0.8.0, 기획서/PID-기호사전.md D4): APR1400 범례의 댐퍼·시험 연결
SYMBOL_DICT_KINDS = {"damper": "valve", "test_connection": "inline_component",
                     # APR1400 범례로 들인 종류(registry 0.9.0)
                     "air_flow_arrow": "piping_element", "slip_joint": "inline_component", "sparger": "inline_component",
                     "hose_connection": "inline_component", "flexible_hose": "inline_component",
                     "diaphragm_seal": "inline_component", "expansion_joint": "inline_component",
                     "silencer": "inline_component", "flame_arrestor": "inline_component",
                     "sight_glass": "inline_component", "pilot_light": "instrument", "alarm": "instrument",
                     "sample_probe": "instrument", "level_element": "instrument", "electric_heater": "equipment",
                     "chiller": "equipment"}
OLD_NODE_PREFIX = {"document": "doc-", "doc_chunk": "chunk-", "requirement": "req-", "setpoint": "setpt-",
                   "condition": "cond-", "analysis_case": "case-"}
OLD_LINK_TYPES = {
    "part_of": ({"doc_chunk"}, {"document"}),
    "mentions": ({"doc_chunk"}, {"pid"}),
    "specified_in": ({"requirement", "setpoint", "condition"}, {"doc_chunk"}),
    "governed_by": ({"pid"}, {"requirement"}),
    "has_setpoint": ({"pid"}, {"setpoint"}),
    "has_condition": ({"pid"}, {"condition"}),
    "depends_on": ({"pid"}, {"pid"}),
    "analyzed_in": ({"pid"}, {"analysis_case"}),
}
OLD_CONFLICT_KINDS = {"has_setpoint": "setpoint", "has_condition": "condition"}
OLD_ALGO_APPLY_KIND_OF = {"requirement": "governed_by", "setpoint": "has_setpoint", "condition": "has_condition",
                          "analysis_case": "analyzed_in"}
OLD_GAP_KINDS = ("governed_by", "has_condition", "has_setpoint")
OLD_AUTO_APPLY_KIND = {"setpoint": "has_setpoint", "condition": "has_condition", "requirement": "governed_by"}
OLD_CONTEXT_RELATION_KINDS = ("governed_by", "has_condition", "has_setpoint")
OLD_CONTEXT_TYPE_ORDER = {"requirement": 0, "setpoint": 1, "condition": 2}
OLD_TYPE = {
    "equipment": {"layer": "pid", "name": "설비", "col": "kg-equipment", "shape": "circle"},
    "valve": {"layer": "pid", "name": "밸브", "col": "kg-valve", "shape": "circle"},
    "inline_component": {"layer": "pid", "name": "배관 부품", "col": "kg-inline_component", "shape": "circle"},  # M2
    "instrument": {"layer": "pid", "name": "계장", "col": "kg-instrument", "shape": "circle"},
    "piping_element": {"layer": "pid", "name": "배관 요소",  # M2: 사전 §2.1 이름(② 종류 목록 폭)
                       "col": "kg-piping_element", "shape": "circle"},
    "pipe_segment": {"layer": "pid", "name": "배관 구간", "col": "kg-pipe_segment", "shape": "circle"},
    "unclassified": {"layer": "pid", "name": "미분류", "col": "kg-unclassified", "shape": "circle"},
    "document": {"layer": "kn", "name": "문서", "col": "kg-document", "shape": "page"},
    "doc_chunk": {"layer": "kn", "name": "문서 조각", "col": "kg-doc_chunk", "shape": "square"},
    "requirement": {"layer": "kn", "name": "요건", "col": "kg-requirement", "shape": "hex"},
    "setpoint": {"layer": "kn", "name": "설정치", "col": "kg-setpoint", "shape": "diamond"},
    "condition": {"layer": "kn", "name": "운전조건·설계값", "col": "kg-condition", "shape": "capsule"},
    "analysis_case": {"layer": "kn", "name": "해석 사례", "col": "kg-analysis_case", "shape": "tri"},
}
OLD_GRP_OF = {"has_endpoint": "phys", "measurement_connection": "meas", "signal_connection": "sig", "mentions": "men",
              "governed_by": "app", "has_setpoint": "app", "has_condition": "app", "analyzed_in": "app",
              "part_of": "pos", "specified_in": "pos", "depends_on": "dep"}
OLD_GRP = {
    "phys": {"name": "물리 연결 (has_endpoint)", "w": 2.4},
    "meas": {"name": "계측 연결", "w": 1.4},
    "sig": {"name": "신호 연결", "w": 1.4},
    "men": {"name": "언급 (mentions)", "w": 1.4},
    "app": {"name": "설비 적용 (governed_by·has_setpoint·has_condition·analyzed_in)", "w": 1.8},
    "pos": {"name": "문서 안 위치 (part_of·specified_in)", "w": 1},
    "dep": {"name": "문서 근거 의존 (depends_on)", "w": 1.6},
}
# M4: 기대 층(잠재 후보) 클래스·관계 묶음 추가(설계안 §8.3, 사전 §3.4)
M4_TYPE = {"expectation": {"layer": "exp", "name": "잠재 후보", "col": "kg-edge-hi", "shape": "circle", "line": "dashed"}}
M4_GRP = {"expect": {"name": "기대 (expects·satisfied_by)", "w": 1}}
M4_GRP_OF = {"expects": "expect", "satisfied_by": "expect"}
# M5 검토 층(설계안 §8.3, 사전 §2.5·§3.5). 색은 기존 ③ 토큰에서 고름(디자인 담당 미확인)
M5_TYPE = {k: {"layer": "st", "name": n, "col": c, "shape": "diamond"} for k, n, c in (
    ("study_node", "검토구간", "kg-edge-hi"), ("scenario", "시나리오", "kg-flag-ink"), ("cause", "원인", "kg-conflict"),
    ("consequence", "결과", "kg-flag"), ("safeguard", "보호수단", "kg-pipe_segment"),
    ("recommendation", "권고", "kg-unclassified"))}
M5_GRP = {"study": {"name": "검토 (covers·cause_at·affects·safeguard_by 등)", "w": 1}}
# P3 ⑥ 초기사건 투영(초기사건 출력설계 §8 P3). 같은 검토 층·검토 묶음, 색은 기존 ③ 토큰
M6_TYPE = {k: {"layer": "st", "name": n, "col": c, "shape": sh} for k, n, c, sh in (
    ("ie_candidate", "초기사건 후보", "kg-flag-ink", "tri"), ("ie_group", "초기사건 그룹", "kg-edge-hi", "hex"),
    ("top_event", "사건수목 표제 후보", "kg-pipe_segment", "square"), ("end_state", "최종상태 후보", "kg-flag", "capsule"),
    ("basic_event", "기본사건 후보", "kg-valve", "circle"), ("reference_ie", "일반 초기사건 범주", "kg-requirement", "page"))}
M5_GRP_OF = {k: "study" for k in ("covers", "in_node", "has_cause", "has_consequence", "cause_at", "affects",
                                  "protected_by", "safeguard_by", "addresses", "raised_from", "derived_from",
                                  "member_of", "corresponds_to", "pivotal", "leads_to", "heading_from",
                                  "basic_event_at", "cites")}
# 화면 내부 키만 사전 §4 묶음 ID로 바뀜(화면에 보이지 않음)
GROUP_RENAME = {"phys": "physical", "meas": "measurement", "sig": "signal", "men": "mention", "app": "apply",
                "pos": "doc_location", "dep": "dependency"}


def _data():
    return copy.deepcopy(schema.REGISTRY.data)


def _cls(data, cid):
    return next(c for c in data["classes"] if c["id"] == cid)


def _rel(data, rid):
    return next(r for r in data["relations"] if r["id"] == rid)


class RegistryFormatTest(unittest.TestCase):
    def assertProblem(self, data, needle):
        probs = schema.validate(data)
        self.assertTrue(any(needle in p for p in probs), probs)
        with self.assertRaises(schema.RegistryError):
            schema.Registry(data)

    def test_shipped_registry_passes(self):
        self.assertEqual(schema.validate(_data()), [])
        self.assertRegex(schema.REGISTRY.sha256, r"^[0-9a-f]{64}$")

    def test_top_level(self):
        self.assertEqual(schema.validate([]), ["최상위가 JSON 객체가 아님"])
        d = _data()
        del d["registry_version"]
        self.assertProblem(d, "registry_version 없음")
        d = _data()
        d["extra"] = 1
        self.assertProblem(d, "모르는 최상위 키")

    def test_r1_parent_missing_and_cycle(self):
        d = _data()
        _cls(d, "valve")["parent"] = "nothing"
        self.assertProblem(d, "(R1)")
        d = _data()
        _cls(d, "plant_item")["parent"] = "pump"
        self.assertProblem(d, "순환(R1)")

    def test_r2_relation_class_missing(self):
        d = _data()
        _rel(d, "governed_by")["to"] = ["no_such_class"]
        self.assertProblem(d, "(R2)")

    def test_r4_kind_overlap(self):
        d = _data()
        _cls(d, "tank")["kind"] = "pump"
        self.assertProblem(d, "(R4)")

    def test_field_types(self):
        cases = [
            (lambda d: _cls(d, "valve").update(legend={"shape": "star", "token": "kg-valve"}), "legend"),
            (lambda d: _cls(d, "valve").update(legend={"shape": "circle", "token": "valve"}), "legend"),
            (lambda d: _cls(d, "valve").update(colour="x"), "모르는 키"),
            (lambda d: _cls(d, "valve").pop("label_en"), "label_en 없음"),
            (lambda d: _cls(d, "knowledge_item").update(layer="other"), "layer"),
            (lambda d: _cls(d, "document").update(layer="pid"), "상위 클래스와 다름"),
            (lambda d: _cls(d, "equipment").update(kind="equipment"), "kind 클래스의 상위"),
            (lambda d: _rel(d, "analyzed_in").pop("evidence_gap"), "evidence_gap(참·거짓) 필요"),
            (lambda d: _rel(d, "mentions").update(evidence_gap=True), "evidence_gap은 설비 적용 관계에만"),
            (lambda d: _rel(d, "governed_by").update(group="nope"), "범례 묶음"),
            (lambda d: _rel(d, "governed_by").update(v4="yes"), "v4"),
            (lambda d: _rel(d, "governed_by").update(a2_role="other"), "a2_role"),
            (lambda d: _rel(d, "has_endpoint").pop("pid_view"), "pid_view"),
            (lambda d: _rel(d, "governed_by").update(pid_view="V1"), "pid_view는 P&ID 관계에만"),
            (lambda d: _rel(d, "analyzed_in").update(to=["setpoint"]), "같은 클래스 setpoint"),
            (lambda d: d["groups"][0].update(width="2"), "width"),
            (lambda d: d["relations"].append(dict(d["relations"][0])), "id 중복"),
        ]
        for mutate, needle in cases:
            with self.subTest(needle=needle):
                d = _data()
                mutate(d)
                self.assertProblem(d, needle)

    def test_load_rejects_bad_json(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "r.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{")
        with self.assertRaises(schema.RegistryError):
            schema.load(p)

    def test_hash_ignores_formatting(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "r.json")
        with open(p, "w", encoding="utf-8", newline="\r\n") as fh:
            json.dump(_data(), fh, ensure_ascii=False, indent=4)
        self.assertEqual(schema.load(p).sha256, schema.REGISTRY.sha256)

    def test_inheritance(self):
        r = schema.REGISTRY
        self.assertTrue(r.is_a("control_valve", "valve"))
        self.assertTrue(r.is_a("control_valve", "plant_item"))
        self.assertFalse(r.is_a("control_valve", "knowledge_item"))
        self.assertFalse(r.is_a("not_registered", "plant_item"))
        self.assertEqual(r.layer("control_valve"), "pid")
        self.assertEqual(r.layer("setpoint"), "knowledge")


class RegistryEquivalenceTest(unittest.TestCase):
    def test_extract_rules(self):
        old_part = {k: v for k, v in rules.KIND_CATEGORY.items() if k in OLD_KIND_CATEGORY}
        self.assertEqual(old_part, dict(OLD_KIND_CATEGORY, **M2_MOVED))
        self.assertEqual({k: v for k, v in rules.KIND_CATEGORY.items() if k not in OLD_KIND_CATEGORY},
                         dict(M2_NEW_KINDS, **SYMBOL_DICT_KINDS))
        self.assertEqual([k for k in rules.KIND_CATEGORY if k in OLD_KIND_CATEGORY and k not in M2_MOVED],
                         [k for k in OLD_KIND_CATEGORY if k not in M2_MOVED])

    def test_build(self):
        self.assertEqual(build.NODE_PREFIX, OLD_NODE_PREFIX)
        self.assertEqual(build.LINK_TYPES, OLD_LINK_TYPES)
        self.assertEqual(build.CONFLICT_KINDS, OLD_CONFLICT_KINDS)

    def test_apply_kinds_keep_per_caller_difference(self):
        self.assertEqual(algo.APPLY_KIND_OF, OLD_ALGO_APPLY_KIND_OF)          # 4종(analyzed_in 포함)
        self.assertEqual(algo.APPLY_KINDS, tuple(sorted(OLD_ALGO_APPLY_KIND_OF.values())))
        self.assertEqual(algo.GAP_KINDS, OLD_GAP_KINDS)
        self.assertEqual(auto.APPLY_KIND, OLD_AUTO_APPLY_KIND)                # 3종
        self.assertEqual(context.RELATION_KINDS, OLD_CONTEXT_RELATION_KINDS)  # 3종
        self.assertEqual(context.TYPE_ORDER, OLD_CONTEXT_TYPE_ORDER)

    def test_algo_views(self):
        self.assertEqual(algo.PHYSICAL_KINDS, ("has_endpoint",))
        self.assertEqual(algo.INSTRUMENT_KINDS, ("measurement_connection", "signal_connection"))

    def test_screen_tables_same_labels_colors_order(self):
        types, grp_of, grps = screen.legend_tables()
        self.assertEqual(list(types.items()), list(OLD_TYPE.items()) + list(M4_TYPE.items()) + list(M5_TYPE.items())
                         + list(M6_TYPE.items()))
        self.assertEqual(list(grps.items()), [(GROUP_RENAME[k], v) for k, v in OLD_GRP.items()] + list(M4_GRP.items())
                         + list(M5_GRP.items()))
        self.assertEqual(grp_of, dict({k: GROUP_RENAME[v] for k, v in OLD_GRP_OF.items()}, **M4_GRP_OF, **M5_GRP_OF))

    def test_html_has_tables_once(self):
        html = screen.build_html(None)
        self.assertNotIn("/*@SCHEMA@*/", html)
        self.assertEqual(html.count("var TYPE = "), 1)
        self.assertEqual(html.count("var GRP_OF = "), 1)
        self.assertEqual(html.count("var GRP = "), 1)


class KgVersionTest(unittest.TestCase):
    KNOWLEDGE = {"schema_version": "0.1", "project_id": "P", "kg_id": "kg-P", "inputs": {}, "pid_graphs": [],
                 "nodes": [], "links": []}

    def test_kg_version_adds_registry_only(self):
        kg = build.build_kg(self.KNOWLEDGE, [])
        canon = build._canon({"knowledge": self.KNOWLEDGE, "graph_refs": []})
        old_head = "%s|nx=%s|" % (build.BUILDER_VERSION, nx.__version__)
        new_head = old_head + "registry=%s:%s|" % (schema.REGISTRY.version, schema.REGISTRY.sha256)
        self.assertEqual(kg["kg_version"], "v-" + hashlib.sha256((new_head + canon).encode("utf-8")).hexdigest()[:12])
        self.assertNotEqual(kg["kg_version"], "v-" + hashlib.sha256((old_head + canon).encode("utf-8")).hexdigest()[:12])
        self.assertEqual(kg["registry"], {"version": schema.REGISTRY.version, "sha256": schema.REGISTRY.sha256})
        self.assertEqual(kg["schema_version"], "0.2")

    def test_reads_old_schema_version_rejects_unknown(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        for ver, ok in (("0.1", True), ("0.2", True), ("9.9", False)):
            root = os.path.join(tmp, ver)
            kg = build.build_kg(self.KNOWLEDGE, [])
            kg["schema_version"] = ver
            if ver == "0.1":
                kg.pop("registry")
            build.write_outputs(root, self.KNOWLEDGE, kg)
            with self.subTest(ver=ver):
                if ok:
                    self.assertEqual(build.load_outputs(root)[1]["schema_version"], ver)
                else:
                    with self.assertRaises(ValueError):
                        build.load_outputs(root)


if __name__ == "__main__":
    unittest.main()
