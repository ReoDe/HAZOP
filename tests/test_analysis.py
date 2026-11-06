"""단계 ④ HAZOP 분석 테스트. 실행: python -m unittest discover -s tests -t .

실제 API 호출 없음: AI는 고정 응답(데이터/고정응답/, tests/fixtures/analysis/)과 모의 SDK 객체만 쓴다.
입력 그래프는 샘플 drawio에서 직접 만든다(출력/ 폴더에 의존하지 않음).
"""

import copy
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock
import importlib.util

# anthropic SDK가 없는 환경(배포용 전용 venv, T2 D1)에서는 SDK를 import하는 경로의 테스트를 건너뛴다.
HAS_ANTHROPIC = importlib.util.find_spec("anthropic") is not None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.analysis import ai, catalog_md, explore as ex_mod, risk, run, validate  # noqa: E402
from hazop.extract import drawio, svg_align  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.graph.query import GraphQuery  # noqa: E402

DATA = os.path.join(REPO_ROOT, "데이터")
REGION_FILE = os.path.join(DATA, "구간", "region-SNP-M-102-pzr.json")
FIXED_DIR = os.path.join(DATA, "고정응답", "region-SNP-M-102-pzr")
BAD_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "analysis", "bad")
GUIDE = os.path.join(REPO_ROOT, "기획서", "HAZOP기법지침.md")
NOW = "2026-11-04T00:00:00Z"
# 지침서 §6 〈표5〉를 코드와 독립적으로 옮김 (행: 강도, 열: 발생빈도)
TABLE5 = {4: {3: 5, 2: 5, 1: 3}, 3: {3: 4, 2: 4, 1: 2}, 2: {3: 3, 2: 2, 1: 1}, 1: {3: 2, 2: 1, 1: 1}}
BASIS = {"severity_basis": "근거", "frequency_basis": "근거"}

PZR, PV101, V111, PSV101, T31, TE120, T37 = ("entity-node-001", "entity-node-008", "entity-node-007",
                                             "entity-node-014", "entity-node-016", "entity-node-018",
                                             "entity-node-019")


def now():
    return NOW


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sample_graph():
    """scripts/extract_drawio.py --samples + build_graph.py 와 같은 방법으로 SNP-M-102 그래프를 만든다."""
    path = [p for p in glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio"))
            if "SNP-M-102" in p][0]
    result = drawio.extract(path, page=0, repo_root=REPO_ROOT)
    svg = glob.glob(os.path.join(os.path.dirname(path), "*.drawio.svg"))
    if len(svg) == 1:
        al = svg_align.align(svg[0], result)
        al["svg_file"] = os.path.relpath(svg[0], REPO_ROOT).replace("\\", "/")
        result["coordinate_system"]["svg_alignment"] = al
    return build.build_graph(result)


GRAPH = sample_graph()
CRIT = _load(os.path.join(DATA, "기준표", "kosha-p86-2017-risk-criteria.json"))


def data_inputs(graph=None, region=None, criteria="default"):
    region = region or _load(REGION_FILE)
    files = {k: os.path.join(REPO_ROOT, v) for k, v in region["inputs"].items()}
    crit = _load(files["risk_criteria"]) if criteria == "default" else criteria
    return run.prepare(region, graph or GRAPH, _load(files["candidate_catalog"]), _load(files["applicability"]),
                       _load(files["patterns"]), crit)


def raw_inputs():
    """저장·재시도용: 입력 원문(raw)과 해시가 있는 입력."""
    inputs = data_inputs()
    inputs["raw"] = {r: json.dumps(d, ensure_ascii=False) for r, d in
                     (("region", inputs["region"]), ("graph", inputs["graph"]),
                      ("candidate_catalog", inputs["catalog"]), ("applicability", inputs["applicability"]),
                      ("patterns", inputs["patterns"]), ("risk_criteria", inputs["criteria"]))}
    inputs["files"] = [{"role": r, "path": None, "sha256": run._sha_text(t)} for r, t in inputs["raw"].items()]
    return inputs


def analyze(inputs=None, client=None, **kw):
    return run.analyze(inputs or data_inputs(), client or ai.FixedResponseClient(FIXED_DIR), run_id="analysis-test",
                       now=now, **kw)


DOC = analyze()


def cand(doc, item):
    return next(c for c in doc["candidates"] if c["item_id"] == item)


def scen(doc, item):
    return [s for s in doc["scenarios"] if s["candidate_id"] == "deviation-%s" % item]


def pat_scen(doc, item, pattern_id):
    return next(s for s in scen(doc, item) if s["pattern_ref"] and s["pattern_ref"]["pattern_id"] == pattern_id)


# ------------------------------------------------------------------ 합성 그래프(분기·순환·경계)
def synthetic_graph(objects, pipes, signals=()):
    """objects: [(id, kind, category, attrs)], pipes: [(seg_id, a, b, directed)]: a->b 흐름(directed=False면 방향 미확인)."""
    nodes, edges, n = [], [], 0
    for oid, kind, catg, attrs in objects:
        nodes.append({"entity_id": oid, "node_type": "drawing_object", "kind": kind, "category": catg, "tag": oid.upper(),
                      "label_text": oid, "attributes": dict(attrs), "local_id": "l-" + oid, "source_object_id": "s-" + oid,
                      "bbox": [0, 0, 1, 1]})
    for sid, a, b, directed in pipes:
        flow = {"from": a, "to": b, "from_end": "source", "to_end": "target", "basis": "source_to_target"} if directed else None
        nodes.append({"entity_id": sid, "node_type": "pipe_segment", "kind": "pipe_segment", "category": "pipe_segment",
                      "tag": None, "label_text": "", "attributes": {}, "flow_direction": flow, "local_id": "l-" + sid,
                      "source_object_id": "s-" + sid, "bbox": None})
        for node, end in ((a, "source"), (b, "target")):
            n += 1
            edges.append({"entity_id": "relation-%03d" % n, "kind": "has_endpoint", "nodes": [sid, node], "segment": sid,
                          "node": node, "end": end, "local_id": "l-" + sid, "source_object_id": "s-" + sid})
    for a, b in signals:
        n += 1
        edges.append({"entity_id": "relation-%03d" % n, "kind": "signal_connection", "nodes": [a, b],
                      "local_id": "l-sig%d" % n, "source_object_id": "s-sig%d" % n})
    return {"graph_id": "graph-syn", "graph_version": "v-syn", "project_id": None, "nodes": nodes, "edges": edges,
            "source": {"drawing_number": "SYN", "extraction_run_id": "x"}, "validation": {"status": "passed",
                                                                                         "blockers": [], "unknowns": []}}


SYN = synthetic_graph(
    [("a", "vessel", "equipment", {}), ("t", "tee", "piping_element", {}), ("v", "manual_valve", "valve", {"normal_position": "NO"}),
     ("b", "vessel", "equipment", {}), ("x", "vessel", "equipment", {}), ("y", "vessel", "equipment", {})],
    [("s1", "a", "t", True), ("s2", "t", "v", True), ("s3", "v", "a", True),  # 분기 + 순환 a-t-v-a
     ("s4", "t", "b", False), ("s5", "b", "x", True), ("s6", "x", "y", True)])  # b 너머 x, y는 구간 밖


class InputAndVersionTest(unittest.TestCase):
    """MVP 사례 1: 정상 운전 선택 구간 입력 -> 범위·모드·설계 의도와 입력 버전 고정."""

    def test_region_pins_pipeline_graph_version(self):
        region = _load(REGION_FILE)
        self.assertEqual(region["graph_ref"]["graph_version"], GRAPH["graph_version"])
        self.assertEqual(region["graph_ref"]["graph_source"], run.graph_source_of(GRAPH))
        self.assertEqual(data_inputs()["blockers"], [])

    def test_run_records_versions_scope_mode_intent(self):
        r = DOC["analysis_run"]
        self.assertEqual(DOC["graph_ref"], {"graph_id": "graph-SNP-M-102", "graph_version": GRAPH["graph_version"]})
        self.assertEqual(DOC["region_ref"], {"region_id": "region-SNP-M-102-pzr",
                                             "region_version": _load(REGION_FILE)["region_version"]})
        self.assertEqual(DOC["operating_mode"], "normal")
        self.assertEqual(r["region"]["design_intent"]["knowledge_status"], "hypothesis")
        self.assertIn("사용자 확인 필요", r["region"]["design_intent"]["basis"])
        for key in ("candidate_catalog", "applicability", "patterns", "risk_criteria", "prompt_template"):
            self.assertIsNotNone(r["versions"][key], key)
        self.assertEqual({f["role"] for f in r["input_files"]}, set(run.INPUT_ROLES))
        self.assertTrue(all(len(f["sha256"]) == 64 for f in r["input_files"]))
        self.assertEqual(r["exploration_settings"]["max_depth"], 12)
        self.assertEqual(r["graph_source"], "samples")

    def test_graph_version_mismatch_blocks(self):
        g = copy.deepcopy(GRAPH)
        g["graph_version"] = "v-other"
        inputs = data_inputs(graph=g)
        self.assertTrue(any("그래프 버전 불일치" in b and "--rebind-graph" in b for b in inputs["blockers"]))
        with self.assertRaises(run.InputError):
            run.analyze(inputs, ai.FixedResponseClient(FIXED_DIR), now=now)

    def test_blocked_graph_and_tag_mismatch_block(self):
        g = copy.deepcopy(GRAPH)
        g["validation"]["status"] = "blocked"
        self.assertTrue(any("passed가 아님" in b for b in data_inputs(graph=g)["blockers"]))
        region = _load(REGION_FILE)
        region["members"][0]["tag"] = "WRONG"
        self.assertTrue(any("태그 불일치" in b for b in data_inputs(region=region)["blockers"]))

    def test_run_level_unknowns_become_holds(self):
        items = [h["item"] for h in DOC["holds"] if h["candidate_id"] is None]
        self.assertIn("가압기 정상 운전압력", items)
        self.assertIn("material_id 미확인", items)
        self.assertIn("RC-TE120 탐색 미도달", items)


class RebindGraphTest(unittest.TestCase):
    """그래프 버전 재고정: 차이를 보여 주고, 확인(--confirm) 후에만 구간 JSON을 갱신하며 이력을 남긴다."""

    def test_rebind_shows_diff_then_updates_with_history(self):
        tmp = tempfile.mkdtemp()
        try:
            rpath, gpath = os.path.join(tmp, "region.json"), os.path.join(tmp, "graph.json")
            shutil.copy(REGION_FILE, rpath)
            g = copy.deepcopy(GRAPH)
            g.update(graph_version="v-registered", project_id="sample-project")
            with open(gpath, "w", encoding="utf-8") as fh:
                json.dump(g, fh)
            self.assertTrue(any("그래프 버전 불일치" in b for b in data_inputs(graph=g)["blockers"]))
            lines, changed = run.rebind_graph(rpath, gpath, REPO_ROOT, None, None, False)
            self.assertFalse(changed)
            self.assertTrue(any("v-registered" in x for x in lines))
            self.assertEqual(_load(rpath), _load(REGION_FILE))
            lines, changed = run.rebind_graph(rpath, gpath, REPO_ROOT, "tester", "등록 경로 그래프 사용", True, now=now)
            self.assertTrue(changed)
            r = _load(rpath)
            self.assertEqual((r["graph_ref"]["graph_version"], r["graph_ref"]["graph_source"], r["project_id"],
                              r["region_version"]), ("v-registered", "registration", "sample-project", _load(REGION_FILE)["region_version"] + 1))
            hist = r["graph_ref_history"][-1]
            self.assertEqual((hist["from"]["graph_version"], hist["changed_by"]), (GRAPH["graph_version"], "tester"))
            self.assertEqual(data_inputs(graph=g, region=r)["blockers"], [])
            next(n for n in g["nodes"] if n["entity_id"] == PZR)["tag"] = "X"
            g["graph_version"] = "v-third"
            with open(gpath, "w", encoding="utf-8") as fh:
                json.dump(g, fh)
            lines, changed = run.rebind_graph(rpath, gpath, REPO_ROOT, "tester", "x", True, now=now)
            self.assertFalse(changed)
            self.assertTrue(any("태그 불일치" in x for x in lines))
            self.assertEqual(_load(rpath)["region_version"], _load(REGION_FILE)["region_version"] + 1)
        finally:
            shutil.rmtree(tmp)


class ExplorationTest(unittest.TestCase):
    """MVP 사례 2: 분기·순환·경계 밖 연결 -> 탐색 종료, 관계 종류·경계·제한 기록."""

    def explore(self, members, depth=20, ext=0, max_reached=100):
        return ex_mod.explore(GraphQuery(SYN), "a", ex_mod.region_members(SYN, members), ["has_endpoint"],
                              depth, max_reached, ext)

    def test_cycle_branch_boundary(self):
        r = self.explore(["a", "t", "v", "b"])
        self.assertTrue(r["terminated"])
        reached = {x["entity_id"] for x in r["reached"]}
        self.assertTrue({"t", "v", "b", "s1", "s2", "s3", "s4"} <= reached)
        self.assertNotIn("x", reached)
        self.assertEqual([c["outside_node"] for c in r["boundary_crossings"]], ["s5"])
        self.assertEqual(r["boundary_crossings"][0]["action"], "not_expanded")
        self.assertTrue(r["cycle_or_merge_edges"])  # 순환 a-t-v-a
        self.assertEqual(r["settings"]["relation_kinds"], ["has_endpoint"])
        b = next(x for x in r["reached"] if x["entity_id"] == "b")
        self.assertEqual(b["direction_from_start"], "direction_unknown")  # s4 방향 미확인 — 버리지 않고 표시
        self.assertEqual(b["path_edge_kinds"], ["has_endpoint"] * 4)

    def test_boundary_extension_marks_outside(self):
        r = self.explore(["a", "t", "v", "b"], ext=2)
        x = next(n for n in r["reached"] if n["entity_id"] == "x")
        self.assertTrue(x["outside_region"])
        self.assertNotIn("y", {n["entity_id"] for n in r["reached"]})

    def test_depth_and_count_limits_recorded(self):
        r = self.explore(["a", "t", "v", "b", "x", "y"], depth=2)
        self.assertIn("max_depth", r["limits_hit"])
        self.assertTrue(all(n["depth"] <= 2 for n in r["reached"]))
        r = self.explore(["a", "t", "v", "b", "x", "y"], max_reached=3)
        self.assertEqual(len(r["reached"]), 3)
        self.assertIn("max_reached", r["limits_hit"])

    def test_sample_records_external_drawings_and_kinds(self):
        ex = DOC["explorations"][0]
        self.assertEqual(sorted(t["to_drawing"] for t in ex["truncations"] if t["reason"] == "external_drawing"),
                         ["SNP-M-101", "SNP-M-101", "SNP-M-301"])
        self.assertEqual(ex["unreached_region_members"], [TE120, T37])
        pt = next(r for r in ex["reached"] if r["entity_id"] == "entity-node-009")
        self.assertEqual(pt["path_edge_kinds"], ["measurement_connection"])
        self.assertEqual(pt["normal_operation_flow"], "not_material_path")


class ValvePositionTest(unittest.TestCase):
    """MVP 사례 3·4: NC 밸브 경로 구분 / 정상 위치 미확인은 가정하지 않고 보류."""

    def reached(self, doc, nid):
        return next(r for r in doc["explorations"][0]["reached"] if r["entity_id"] == nid)

    def test_nc_valve_path_distinguished(self):
        pv = self.reached(DOC, PV101)
        self.assertEqual((pv["valve_state"], pv["normal_operation_flow"]), ("no_valves", True))
        v = self.reached(DOC, V111)
        self.assertEqual((v["valve_state"], v["normal_operation_flow"]), ("closed_valve_on_path", False))
        self.assertEqual(v["valves_on_path"], [{"entity_id": PV101, "tag": "RC-PV101", "kind": "control_valve",
                                                "normal_position": "NC", "fail_position": "FC", "state": "closed"}])
        self.assertEqual(self.reached(DOC, T31)["valve_state"], "closed_valve_on_path")  # POSRV(NC) 하류
        ev = next(e for e in DOC["evidence_bundles"]["deviation-p86-d09"]["evidence"]
                  if e["evidence_id"] == "ev-path-%s" % V111)
        self.assertEqual(ev["valves_on_path"][0]["normal_position"], "NC")

    def test_unknown_position_not_assumed(self):
        g = copy.deepcopy(GRAPH)
        next(n for n in g["nodes"] if n["entity_id"] == PV101)["attributes"].pop("normal_position")
        doc = analyze(data_inputs(graph=g))
        v = self.reached(doc, V111)
        self.assertEqual(v["valve_state"], "position_unknown_on_path")
        self.assertIsNone(v["normal_operation_flow"])
        self.assertEqual(v["valves_on_path"][0]["state"], "unknown")
        self.assertTrue(any(h["item"] == "RC-PV101 정상 위치 미확인" for h in doc["holds"]))
        na = doc["evidence_bundles"]["deviation-p86-d09"]["pattern_matches"]["not_applied"]
        self.assertTrue(any(x["target"] == PV101 and x["status"] == "condition_unknown" for x in na))
        self.assertFalse(any(s["pattern_ref"] and s["pattern_ref"]["match_id"].endswith(PV101)
                             for s in scen(doc, "p86-d09")))
        self.assertEqual(pat_scen(doc, "p86-d09", "pat-mv-no-d09-closed")["scenario_status"], "deferred")
        # 입력이 바뀌었으므로 고정 응답은 근거 묶음 해시 불일치로 쓰지 않음
        self.assertEqual(cand(doc, "p86-d09")["analysis"]["ai_status"], "input_mismatch")


class PatternTest(unittest.TestCase):
    """MVP 사례 5·6: 패턴 적용/미적용 구분, 도달 경로만 있는 대상은 원인과 구분."""

    def test_pattern_source_version_recorded(self):
        for s in scen(DOC, "p86-d09"):
            self.assertEqual(s["pattern_ref"]["source"], "[일반지식], 미검증")
            self.assertEqual(s["pattern_ref"]["pattern_version"], 3)
            self.assertNotIn("가열", s["cause"] + s["consequence"])  # 도면에 없는 전열기 암시 금지
            self.assertEqual(s["knowledge_status"], "hypothesis")
        b = DOC["evidence_bundles"]["deviation-p86-d09"]
        self.assertEqual(b["kinds_without_patterns"], ["continuation", "indicator", "tee", "temperature_element"])
        self.assertEqual(DOC["analysis_run"]["versions"]["patterns"]["version"], 4)

    def test_normal_state_not_used_as_cause(self):
        lib = _load(os.path.join(DATA, "패턴", "pressurizer-patterns.json"))
        self.assertNotIn("pat-cv-nc-d44-no-flow", {p["pattern_id"] for p in lib["patterns"]})
        self.assertFalse(any(s["cause_equipment"] == [PV101] for s in scen(DOC, "p86-d44")))

    def test_ai_hypothesis_separate_from_pattern(self):
        tmp = tempfile.mkdtemp()
        try:
            d = _load(os.path.join(FIXED_DIR, "deviation-p86-d09.json"))
            d["output"]["scenarios"][3].update(cause="RC-PZ01 증기 공간 압력 제어 이상(도면 설비 기반 가설)",
                                               interpretation="도면 설비 기반 가설", outside_graph_equipment=[])
            with open(os.path.join(tmp, "deviation-p86-d09.json"), "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            doc = analyze(client=ai.FixedResponseClient(tmp), only={"p86-d09"})
        finally:
            shutil.rmtree(tmp)
        hyp = [s for s in scen(doc, "p86-d09") if s["origin"] == "ai_additional_hypothesis"]
        self.assertEqual(len(hyp), 1)
        self.assertIsNone(hyp[0]["pattern_ref"])
        self.assertEqual(hyp[0]["statement_type"], "additional_hypothesis")
        self.assertFalse(hyp[0]["registered_as_graph_fact"])
        self.assertEqual(hyp[0]["cause_equipment"], [PZR])
        interp = pat_scen(DOC, "p86-d09", "pat-cv-ncfc-d09-fail-closed")["ai_interpretation"]
        self.assertEqual(interp["statement_type"], "interpretation")
        self.assertTrue(all(f["statement_type"] == "fact" and f["evidence_ids"]
                            for f in cand(DOC, "p86-d09")["analysis"]["ai_facts"]))

    def test_reachable_only_is_not_cause(self):
        b = DOC["evidence_bundles"]["deviation-p86-d09"]
        only = {x["entity_id"] for x in b["connection_only"]}
        self.assertTrue({"entity-node-003", "entity-node-013", T31, "entity-node-011"} <= only)
        cause_t = {m["target"] for m in b["pattern_matches"]["applied"]}
        safe_t = {g["node_id"] for g in b["candidate_safeguards"]}
        reached = {r["entity_id"] for r in DOC["explorations"][0]["reached"] if r["node_type"] != "pipe_segment"}
        self.assertEqual(only & (cause_t | safe_t), set())  # 연결만 있는 대상은 원인·보호수단 패턴과 겹치지 않음
        self.assertEqual(only | cause_t | safe_t, reached | {PZR})  # 도달 대상이 셋 중 하나로 빠짐없이 분류됨
        caused = {e for s in scen(DOC, "p86-d09") for e in s["cause_equipment"]}
        self.assertEqual(caused & only, set())
        path_ev = [e for e in b["evidence"] if e["type"] == "exploration_path"]
        self.assertTrue(all("인과관계를 입증하지 않음" in e["note"] for e in path_ev))

    def test_structural_and_attribute_conditions(self):
        na = DOC["evidence_bundles"]["deviation-p86-d09"]["pattern_matches"]["not_applied"]
        self.assertTrue(any(x["tag"] == "RC-LT110" and x["status"] == "condition_not_met" for x in na))
        na14 = DOC["evidence_bundles"]["deviation-p86-d14"]["pattern_matches"]["not_applied"]
        self.assertTrue(any(x["tag"] == "RC-LI110" and x["status"] == "condition_unknown" for x in na14))

    def test_safeguard_filter_and_independence(self):
        out = pat_scen(DOC, "p86-d10", "pat-pzr-d10-outsurge")
        self.assertEqual([g["tag"] for g in out["safeguards"]], ["RC-PT110"])  # 액위 계기 RC-LT110 제외
        cv = pat_scen(DOC, "p86-d10", "pat-cv-nc-d10-spurious-open")
        self.assertEqual({g["tag"]: (g["independence"], g["counts_as_found"]) for g in cv["safeguards"]},
                         {"RC-PT110": ("same_control_loop_as_cause", False)})
        psv = pat_scen(DOC, "p86-d09", "pat-cv-ncfc-d09-fail-closed")
        self.assertEqual({g["independence"] for g in psv["safeguards"]}, {"unknown"})


class AIValidationTest(unittest.TestCase):
    """MVP 사례 7: AI가 존재하지 않는 노드·근거를 인용 -> 참조 오류, 통과 금지."""

    def test_bad_response_rejected(self):
        doc = analyze(client=ai.FixedResponseClient(BAD_DIR))
        c = cand(doc, "p86-d09")
        self.assertEqual(c["analysis"]["ai_status"], "validation_failed")
        run_rec = next(r for r in doc["ai_runs"] if r["candidate_id"] == "deviation-p86-d09")
        details = " ".join(e["detail"] for e in run_rec["validation"]["errors"])
        self.assertIn("'entity-node-099': 그래프에 없음", details)
        self.assertIn("'relation-999': 그래프에 없음", details)
        self.assertIn("'%s': 그래프에는 있으나 근거 묶음 밖" % TE120, details)
        self.assertIn("적용된 cause 패턴이 아님", details)
        self.assertTrue(all(e["type"] in ("reference_error", "value_error") for e in run_rec["validation"]["errors"]))
        self.assertEqual(c["analysis"]["ai_facts"], [])
        for s in scen(doc, "p86-d09"):
            self.assertEqual(s["origin"], "pattern")
            self.assertIsNone(s["ai_interpretation"])
            self.assertEqual(s["risk_proposal"]["status"], "deferred")
        self.assertTrue(any(h["candidate_id"] == c["candidate_id"] and h["source"] == "ai" and h["status"] == "open"
                            for h in doc["holds"]))
        self.assertEqual(doc["validation"]["status"], "passed")

    def test_all_fixed_samples_validate(self):
        for item in ("p86-d09", "p86-d10", "p86-d12", "p86-d43", "p86-d44"):
            self.assertEqual(cand(DOC, item)["analysis"]["ai_status"], "validated", item)
        self.assertEqual(cand(DOC, "p86-d01")["analysis"]["ai_status"], "no_response")

    def test_schema_errors(self):
        out = _load(os.path.join(FIXED_DIR, "deviation-p86-d12.json"))["output"]
        bad = copy.deepcopy(out)
        bad["scenarios"][0]["risk"]["severity"] = 5
        bad["extra"] = 1
        errors, _, _ = validate.validate_response(bad, DOC["evidence_bundles"]["deviation-p86-d12"], GRAPH,
                                                  ai.RESPONSE_SCHEMA)
        self.assertEqual({e["type"] for e in errors}, {"schema_error"})
        self.assertEqual(len(errors), 2)


class DrawingOnlyTest(unittest.TestCase):
    """사용자 결정(2026-11-04): 도면에 없는 설비를 전제한 시나리오는 거부하고 사유를 실행 기록에 남긴다."""

    def test_heater_assumption_rejected(self):
        rec = next(r for r in DOC["ai_runs"] if r["candidate_id"] == "deviation-p86-d09")
        self.assertEqual(rec["status"], "validated")
        rej = rec["validation"]["rejected_scenarios"]
        self.assertEqual([x["index"] for x in rej], [3])
        self.assertIn("전열기", rej[0]["cause"])
        self.assertIn("도면에 없는 설비", rej[0]["reason"])
        self.assertFalse(any("전열기" in s["cause"] for s in DOC["scenarios"]))
        self.assertFalse(any(s["origin"] == "ai_additional_hypothesis" for s in scen(DOC, "p86-d09")))
        self.assertEqual(sum(s["ai_interpretation"] is not None for s in scen(DOC, "p86-d09")), 3)
        self.assertEqual(len(cand(DOC, "p86-d09")["analysis"]["rejected_ai_scenarios"]), 1)
        self.assertEqual(DOC["validation"]["counts"]["ai_rejected_scenarios"], 2)  # d09 전열기, d44 연속 살수

    def test_missing_assumed_equipment_and_segment_safeguard(self):
        b = DOC["evidence_bundles"]["deviation-p86-d12"]
        out = _load(os.path.join(FIXED_DIR, "deviation-p86-d12.json"))["output"]
        o1 = copy.deepcopy(out)
        o1["scenarios"][0]["cause_entity_ids"] = []
        errors, _, rejected = validate.validate_response(o1, b, GRAPH, ai.RESPONSE_SCHEMA)
        self.assertEqual((errors, [r["index"] for r in rejected]), ([], [0]))
        o2 = copy.deepcopy(out)
        o2["scenarios"][0]["safeguards"][0]["node_id"] = "entity-seg-002"
        o2["scenarios"][0]["risk"]["credited_safeguard_node_ids"] = []
        errors, warnings, _ = validate.validate_response(o2, b, GRAPH, ai.RESPONSE_SCHEMA)
        self.assertEqual(errors, [])
        self.assertTrue(any(w["type"] == "safeguard_not_recognized" and w["node_id"] == "entity-seg-002" for w in warnings))
        self.assertIn("도면에 없는 설비", ai.SYSTEM_PROMPT)

    def test_every_scenario_is_drawing_based(self):
        nodes = {n["entity_id"]: n for n in GRAPH["nodes"]}
        for s in DOC["scenarios"]:
            self.assertTrue(s["cause_equipment"])
            self.assertTrue(all(nodes[e]["node_type"] == "drawing_object" for e in s["cause_equipment"]))


class DesignImprovementTest(unittest.TestCase):
    """설계보완 후보: 표9 조건부 수용 이상 또는 그래프에서 보호수단 미발견. 자동 확정 금지."""

    def test_from_risk(self):
        dics = DOC["design_improvement_candidates"]
        self.assertTrue(dics)
        for d in dics:
            self.assertEqual((d["status"], d["confirmed"]), ("candidate", False))
            sc = next(s for s in DOC["scenarios"] if s["scenario_id"] == d["scenario_id"])
            self.assertEqual(sc["scenario_status"], "draft")
        pv = pat_scen(DOC, "p86-d09", "pat-cv-ncfc-d09-fail-closed")
        d = next(x for x in dics if x["scenario_id"] == pv["scenario_id"])
        self.assertIn("risk_conditional_or_worse", d["triggers"])
        self.assertEqual((d["basis"]["risk"], d["basis"]["acceptance"]), (4, "조건부 위험작업 수용"))
        self.assertEqual(d["basis"]["criteria_version"], "KOSHA P-86-2017 예시(MVP 임시 기준표)")
        for d in dics:
            if "risk_conditional_or_worse" in d["triggers"]:
                self.assertGreaterEqual(d["basis"]["risk"], 3)
        # 위험도 2 이하이고 독립 보호수단(PSV)이 있는 시나리오는 후보가 아님 (d09 패턴 해석 중 위험도 미제안이 아닌 것)
        quiet = [s["scenario_id"] for s in DOC["scenarios"] if s["risk_proposal"].get("risk") in (1, 2)
                 and any(g["counts_as_found"] for g in s["safeguards"])]
        self.assertFalse({x["scenario_id"] for x in dics} & set(quiet))

    def test_no_safeguard_found_adds_data_request(self):
        doc = copy.deepcopy(DOC)
        sc = pat_scen(doc, "p86-d12", "pat-pzr-d12-overheat")
        sc["safeguards"] = []
        sc["ai_interpretation"]["safeguards"] = []
        run.finalize(doc, GRAPH, CRIT, now)
        d = next(x for x in doc["design_improvement_candidates"] if x["scenario_id"] == sc["scenario_id"])
        self.assertIn("no_safeguard_found_in_graph", d["triggers"])
        self.assertIn("단정하지 않음", d["basis"]["safeguard_note"])
        hold = next(h for h in doc["holds"] if h["hold_id"] == d["hold_ids"][0])
        self.assertEqual((hold["item"], hold["scope"], hold["status"]), ("보호수단 존재 확인", sc["scenario_id"], "open"))
        n = len(doc["holds"])
        run.finalize(doc, GRAPH, CRIT, now)
        self.assertEqual(len(doc["holds"]), n)  # 다시 계산해도 자료 요청을 중복 생성하지 않음

    def test_auto_confirm_detected(self):
        doc = copy.deepcopy(DOC)
        doc["design_improvement_candidates"][0]["confirmed"] = True
        self.assertEqual(run.check_result(doc, GRAPH, CRIT)["status"], "blocked")


class RiskTest(unittest.TestCase):
    """MVP 사례 8, 위험도 조회표, 보호수단 미확인 시 빈도 감소 미반영."""

    def test_lookup_table(self):
        for sev, row in TABLE5.items():
            for freq, want in row.items():
                self.assertEqual(risk.lookup(CRIT, sev, freq), want)
        p = risk.evaluate(CRIT, dict(BASIS, severity=4, frequency_without_safeguards=1), {}, ["ev"])
        self.assertEqual((p["risk"], p["risk_name"], p["status"], p["confirmed"]), (3, "상당한 위험", "proposed", False))

    def test_criteria_match_guide_tables(self):
        t = catalog_md.parse_risk_tables(GUIDE)
        for key in ("matrix", "severity_levels", "frequency_levels", "risk_levels"):
            self.assertEqual(t[key], CRIT[key], key)
        self.assertEqual({int(s): {int(f): v for f, v in row.items()} for s, row in t["matrix"].items()}, TABLE5)

    def test_invalid_values_deferred(self):
        for bad in ({"severity": 5, "frequency_without_safeguards": 1}, {"severity": 2, "frequency_without_safeguards": 0},
                    {"severity": True, "frequency_without_safeguards": 1}):
            self.assertEqual(risk.evaluate(CRIT, dict(BASIS, **bad), {}, ["ev"])["status"], "deferred")

    def test_unconfirmed_safeguard_no_frequency_reduction(self):
        ai_risk = dict(BASIS, severity=3, frequency_without_safeguards=2, frequency_with_safeguards=1,
                       credited_safeguard_node_ids=["n1"])
        p = risk.evaluate(CRIT, ai_risk, {"n1": {"adequacy": "unknown"}}, ["ev"])
        self.assertEqual((p["frequency_used"], p["safeguard_credit_applied"], p["risk"]), (2, False, 4))
        self.assertIn("미반영", p["safeguard_credit_reason"])
        p = risk.evaluate(CRIT, ai_risk, {"n1": {"adequacy": "confirmed"}}, ["ev"])
        self.assertEqual((p["frequency_used"], p["safeguard_credit_applied"], p["risk"]), (1, True, 2))
        sc = pat_scen(DOC, "p86-d09", "pat-cv-ncfc-d09-fail-closed")
        rp = sc["risk_proposal"]
        self.assertEqual((rp["frequency_with_safeguards_ai"], rp["frequency_used"], rp["safeguard_credit_applied"], rp["risk"]),
                         (1, 2, False, TABLE5[3][2]))
        self.assertTrue(all(s["adequacy"] == "unknown" for s in sc["safeguards"]))

    def test_no_criteria_defers_without_grades(self):
        doc = analyze(data_inputs(criteria=None), client=ai.FixedResponseClient(FIXED_DIR, verify_bundle=False))
        self.assertTrue(doc["scenarios"])
        for s in doc["scenarios"]:
            rp = s["risk_proposal"]
            self.assertEqual(rp["status"], "deferred")
            self.assertIsNone(rp["risk"])
            self.assertIsNone(rp["severity"])
        self.assertTrue(any(w["type"] == "risk_without_criteria"
                            for r in doc["ai_runs"] if r["validation"] for w in r["validation"]["warnings"]))
        self.assertEqual(doc["analysis_run"]["steps"]["risk"], "deferred_no_criteria")
        self.assertIsNone(doc["evidence_bundles"]["deviation-p86-d09"]["risk_criteria"])
        self.assertFalse(any("risk_conditional_or_worse" in d["triggers"] for d in doc["design_improvement_candidates"]))


class CandidateTest(unittest.TestCase):

    def test_all_44_have_judgment(self):
        self.assertEqual(len(DOC["candidates"]), 44)
        self.assertEqual(sorted(c["item_id"] for c in DOC["candidates"]), ["p86-d%02d" % i for i in range(1, 45)])
        for c in DOC["candidates"]:
            self.assertIn(c["selection_status"], ("selected", "excluded", "deferred"))
            self.assertTrue(c["judgments"] and c["reason"] and c["judgments"][0]["decided_by"].startswith("rule:"))
        counts = DOC["validation"]["counts"]
        self.assertEqual((counts["selected"], counts["excluded"], counts["deferred"]), (25, 19, 0))

    def test_19_excluded_with_reason(self):
        app = {a["item_id"]: a for a in _load(os.path.join(DATA, "이탈후보", "applicability-region-SNP-M-102-pzr.json"))["items"]}
        ex = [c for c in DOC["candidates"] if c["selection_status"] == "excluded"]
        self.assertEqual(len(ex), 19)
        self.assertEqual(sum(c["batch_specific"] for c in ex), 11)
        for c in ex:
            self.assertEqual(c["judgments"][0]["decided_by"], "rule:R1")
            self.assertEqual(c["reason"], app[c["item_id"]]["applicability_reason"])
            self.assertEqual(c["risk_proposal"], {"status": "not_applicable", "reason": c["reason"]})

    def test_catalog_matches_guide(self):
        cat, app = catalog_md.rows_to_files(catalog_md.parse_guide_table(GUIDE))
        self.assertEqual(cat, _load(os.path.join(DATA, "이탈후보", "kosha-p86-2017-deviation-chart.json")))
        self.assertEqual(app, _load(os.path.join(DATA, "이탈후보", "applicability-region-SNP-M-102-pzr.json")))

    def test_missing_basis_deferred_and_manual_inputs(self):
        inputs = data_inputs()
        inputs["applicability"]["items"] = [a for a in inputs["applicability"]["items"] if a["item_id"] != "p86-d17"]
        inputs["region"]["manual_candidates"] = [{"parameter_ko": "유량", "guide_word_ko": "부가", "deviation": "계측 연결선 누설",
                                                  "added_by": "tester", "reason": "instrument_tap 누출 재검토"}]
        inputs["region"]["candidate_decisions"] = [{"item_id": "p86-d01", "selection_status": "excluded",
                                                    "decided_by": "tester", "reason": "시험용 제외"}]
        doc = analyze(inputs)
        d17 = cand(doc, "p86-d17")
        self.assertEqual((d17["selection_status"], d17["judgments"][0]["decided_by"]), ("deferred", "rule:R5"))
        manual = next(c for c in doc["candidates"] if c["origin"] == "manual")
        self.assertEqual((manual["candidate_id"], manual["selection_status"]), ("deviation-manual-001", "deferred"))
        d01 = cand(doc, "p86-d01")
        self.assertEqual([j["selection_status"] for j in d01["judgments"]], ["selected", "excluded"])
        self.assertEqual(d01["judgments"][1]["previous"], "selected")
        self.assertEqual(len(doc["candidates"]), 45)


class AnthropicClientTest(unittest.TestCase):
    """AnthropicClient 요청 본문 형태와 응답·오류 처리(모의 SDK 객체, 네트워크 없음)."""

    def client(self, reply=None, raises=None):
        calls = []

        def create(**kw):
            calls.append(kw)
            if raises:
                raise raises
            return reply
        fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
        return ai.AnthropicClient(client=fake), calls

    @staticmethod
    def msg(stop="end_turn", text='{"a": 1}', details=None):
        return types.SimpleNamespace(id="msg_1", model="claude-opus-5-5", stop_reason=stop, stop_details=details,
                                     usage={"input_tokens": 1}, content=[types.SimpleNamespace(type="text", text=text)])

    def request(self):
        return ai.build_request(DOC["evidence_bundles"]["deviation-p86-d09"])

    @unittest.skipUnless(HAS_ANTHROPIC, "anthropic SDK 미설치(배포용 venv)")
    def test_request_shape(self):
        c, calls = self.client(self.msg())
        self.assertEqual(c.infer(self.request())["status"], "completed")
        kw = calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["max_tokens"], 16000)
        self.assertEqual(kw["output_config"]["effort"], "high")
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertIs(kw["output_config"]["format"]["schema"], ai.RESPONSE_SCHEMA)
        for banned in ("thinking", "temperature", "top_p", "top_k", "tool_choice", "tools", "region_id", "bundle_sha256"):
            self.assertNotIn(banned, kw)
        self.assertEqual([m["role"] for m in kw["messages"]], ["user"])  # assistant prefill 없음
        self.assertEqual(kw["extra_body"], {"fallbacks": "default"})
        self.assertEqual(kw["extra_headers"], {"anthropic-beta": "server-side-fallback-2026-07-01"})

    @unittest.skipUnless(HAS_ANTHROPIC, "anthropic SDK 미설치(배포용 venv)")
    def test_stop_reasons_and_parse(self):
        c, _ = self.client(self.msg(stop="refusal", details={"type": "refusal", "category": "x", "explanation": "y"}))
        r = c.infer(self.request())
        self.assertEqual((r["status"], r["stop_details"]["category"]), ("refused", "x"))
        c, _ = self.client(self.msg(stop="max_tokens"))
        self.assertEqual(c.infer(self.request())["status"], "truncated")
        c, _ = self.client(self.msg(text="not json"))
        self.assertEqual(c.infer(self.request())["status"], "parse_error")

    @unittest.skipUnless(HAS_ANTHROPIC, "anthropic SDK 미설치(배포용 venv)")
    def test_sdk_errors(self):
        import anthropic
        import httpx
        req = httpx.Request("POST", "https://example.invalid/v1/messages")
        cases = [(anthropic.RateLimitError("rl", response=httpx.Response(429, request=req), body=None), "rate_limit"),
                 (anthropic.InternalServerError("ise", response=httpx.Response(500, request=req), body=None), "api_status"),
                 (anthropic.APIConnectionError(request=req), "connection"),
                 (anthropic.APIResponseValidationError(response=httpx.Response(200, request=req), body=None),
                  "APIResponseValidationError")]
        for exc, kind in cases:
            c, _ = self.client(raises=exc)
            r = c.infer(self.request())
            self.assertEqual((r["status"], r["error_type"]), ("api_error", kind))

    @unittest.skipUnless(HAS_ANTHROPIC, "anthropic SDK 미설치(배포용 venv)")
    def test_refusal_keeps_candidates_and_exploration(self):
        c, _ = self.client(self.msg(stop="refusal", details={"type": "refusal", "category": None, "explanation": None}))
        doc = analyze(client=c, only={"p86-d09"})
        self.assertEqual(cand(doc, "p86-d09")["analysis"]["ai_status"], "refused")
        self.assertEqual(len(doc["candidates"]), 44)
        self.assertTrue(doc["explorations"][0]["reached"])
        self.assertTrue(scen(doc, "p86-d09"))
        self.assertEqual(cand(doc, "p86-d10")["analysis"]["ai_status"], "not_requested")
        rec = doc["ai_runs"][0]
        self.assertEqual(rec["request"]["params"]["model"], "claude-opus-5-5")
        self.assertNotIn("thinking", rec["request"]["params"])

    def test_live_requires_credentials(self):
        import analyze as script
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(ai.AnthropicClient, "credentials_available", staticmethod(lambda: False)):
            self.assertEqual(script.main(["--live"]), 2)


class SaveAndResumeTest(unittest.TestCase):
    """AI 단계 전 저장·후보별 이어 저장, 예외·중단 시 보존, 같은 AI 모드로만 재시도."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_resume_from_failed_ai_step(self):
        doc, run_dir = run.execute(raw_inputs(), ai.FixedResponseClient(FIXED_DIR), self.out, run_id="analysis-resume",
                                   now=now, only={"p86-d10"})
        self.assertEqual(cand(doc, "p86-d09")["analysis"]["ai_status"], "not_requested")
        with self.assertRaises(run.InputError):
            run.save(doc, raw_inputs(), self.out)  # 덮어쓰지 않음
        doc2 = run.resume(run_dir, ai.FixedResponseClient(FIXED_DIR), now=now)
        d09 = cand(doc2, "p86-d09")
        self.assertEqual(d09["analysis"]["ai_status"], "validated")
        self.assertEqual(len(doc2["candidates"]), 44)
        self.assertTrue(os.path.isfile(os.path.join(run_dir, "history", "analysis-001.json")))
        closed = [h for h in doc2["holds"] if h["candidate_id"] == d09["candidate_id"] and h["source"] == "ai"]
        self.assertTrue(closed and all(h["status"] == "closed" for h in closed))
        self.assertEqual(doc2["validation"]["status"], "passed")
        self.assertEqual(_load(os.path.join(run_dir, "analysis.json")), json.loads(json.dumps(doc2)))

    def test_resume_refuses_other_ai_mode(self):
        _, run_dir = run.execute(raw_inputs(), ai.FixedResponseClient(FIXED_DIR), self.out, run_id="analysis-mode",
                                 now=now, only={"p86-d10"})
        for other in (ai.FixedResponseClient(BAD_DIR), ai.FixedResponseClient(FIXED_DIR, verify_bundle=False),
                      ai.AnthropicClient(client=object())):
            with self.assertRaises(run.InputError):
                run.resume(run_dir, other, now=now)
        import analyze as script
        self.assertEqual(script.main(["--resume", run_dir, "--live"]), 1)

    def test_interrupt_keeps_saved_progress(self):
        inner = ai.FixedResponseClient(FIXED_DIR)
        calls = []

        class Interrupting:
            def describe(self):
                return inner.describe()

            def infer(self, request):
                calls.append(request["candidate_id"])
                if len(calls) == 2:
                    raise RuntimeError("예상 밖 오류")
                if len(calls) == 10:
                    raise KeyboardInterrupt
                return inner.infer(request)
        with self.assertRaises(KeyboardInterrupt):
            run.execute(raw_inputs(), Interrupting(), self.out, run_id="analysis-int", now=now)
        run_dir = os.path.join(self.out, "region-SNP-M-102-pzr", "analysis-int")
        saved = _load(os.path.join(run_dir, "analysis.json"))
        self.assertEqual(saved["analysis_run"]["steps"]["ai"], "interrupted")
        self.assertEqual(len(saved["ai_runs"]), 9)
        self.assertEqual(saved["ai_runs"][1]["status"], "client_error")
        self.assertEqual(len(saved["candidates"]), 44)
        self.assertTrue(saved["explorations"][0]["reached"])
        doc = run.resume(run_dir, inner, now=now)
        self.assertEqual(sum(c["analysis"]["ai_status"] == "validated" for c in doc["candidates"]), 5)
        self.assertEqual(doc["analysis_run"]["steps"]["ai"], "partial")

    def test_broken_fixed_json_and_mismatch(self):
        os.makedirs(self.out)
        target = os.path.join(self.out, "deviation-p86-d09.json")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        req = ai.build_request(DOC["evidence_bundles"]["deviation-p86-d09"])
        self.assertEqual(ai.FixedResponseClient(self.out).infer(req)["status"], "parse_error")
        d = _load(os.path.join(FIXED_DIR, "deviation-p86-d09.json"))
        for change in ({"region_id": "region-other"}, {"bundle_sha256": "0" * 64}):
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(dict(d, **change), fh, ensure_ascii=False)
            self.assertEqual(ai.FixedResponseClient(self.out).infer(req)["status"], "input_mismatch")


class DrawingOnlyBypassTest(unittest.TestCase):
    """검토자 재현 사례: 연결 요소·연결점 너머 설비 전제, 서술 속 도면 밖 설비, 후보 목록 밖 보호수단."""

    def base(self):
        return copy.deepcopy(_load(os.path.join(FIXED_DIR, "deviation-p86-d09.json"))["output"])

    def check(self, out):
        return validate.validate_response(out, DOC["evidence_bundles"]["deviation-p86-d09"], GRAPH, ai.RESPONSE_SCHEMA)

    def test_reviewer_case_continuation_and_tee(self):
        out = self.base()
        s = out["scenarios"][0]
        s.update(assumed_equipment=["entity-node-002"], outside_graph_equipment=[],
                 safeguards=[{"node_id": "entity-node-003", "description": "분기점"}])
        s["risk"]["credited_safeguard_node_ids"] = []
        errors, warnings, rejected = self.check(out)
        self.assertEqual(errors, [])
        self.assertIn(0, [r["index"] for r in rejected])
        self.assertIn("다른 도면 연결점(to_drawing SNP-M-101)", rejected[0]["reason"])
        self.assertTrue(any(w["type"] == "safeguard_not_recognized" and w["node_id"] == "entity-node-003" for w in warnings))
        out = self.base()
        out["scenarios"][0]["cause_entity_ids"] = ["entity-node-003"]
        self.assertIn("연결 요소(tee)", self.check(out)[2][0]["reason"])

    def test_pzr_only_with_heater_narrative(self):
        out = self.base()
        h = out["scenarios"][3]
        self.assertEqual(h["cause_entity_ids"], [PZR])
        self.assertIn("전열기", h["cause"])
        self.assertIn(3, [r["index"] for r in self.check(out)[2]])  # 자기 신고 -> 거부
        h["outside_graph_equipment"] = []
        self.assertNotIn(3, [r["index"] for r in self.check(out)[2]])  # 신고하지 않으면 구조 검증만으로는 못 잡음(한계)
        self.assertIn("자동 대조하지 않음", DOC["analysis_run"]["drawing_only_check"]["limit"])
        interp = pat_scen(DOC, "p86-d09", "pat-cv-ncfc-d09-fail-closed")["ai_interpretation"]
        self.assertEqual(interp["narrative_check"], DOC["analysis_run"]["drawing_only_check"])

    def test_equipment_kinds_defined_once(self):
        from hazop.analysis import equipment
        self.assertTrue({"pressurizer", "psv", "transmitter"} <= equipment.EQUIPMENT_KINDS)
        self.assertFalse({"tee", "continuation", "pipe_cap", "pipe_segment"} & equipment.EQUIPMENT_KINDS)

    def test_ai_safeguard_outside_candidate_list_not_counted(self):
        tmp = tempfile.mkdtemp()
        try:
            d = _load(os.path.join(FIXED_DIR, "deviation-p86-d43.json"))
            d["output"]["scenarios"][0]["safeguards"] = [{"node_id": "entity-node-009", "description": "RC-PT110"}]
            with open(os.path.join(tmp, "deviation-p86-d43.json"), "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            doc = analyze(client=ai.FixedResponseClient(tmp), only={"p86-d43"})
        finally:
            shutil.rmtree(tmp)
        sc = scen(doc, "p86-d43")[0]
        self.assertEqual(sc["ai_interpretation"]["safeguards"], [])
        self.assertEqual([g["node_id"] for g in sc["ai_interpretation"]["excluded_safeguards"]], ["entity-node-009"])
        d = next(x for x in doc["design_improvement_candidates"] if x["scenario_id"] == sc["scenario_id"])
        self.assertIn("no_safeguard_found_in_graph", d["triggers"])


class DeviationSafeguardTest(unittest.TestCase):
    """보호수단은 편차(후보)별: PSV는 압력 증가에만. 같은 제어루프 요소는 '찾음'으로 세지 않음."""

    def test_psv_only_for_more_pressure(self):
        b = DOC["evidence_bundles"]
        self.assertEqual([g["tag"] for g in b["deviation-p86-d09"]["candidate_safeguards"]], ["RC-PSV101", "RC-PSV102"])
        for item in ("p86-d10", "p86-d43", "p86-d44"):
            self.assertFalse(any(g["kind"] == "psv" for g in b["deviation-%s" % item]["candidate_safeguards"]), item)
            for s in scen(DOC, item):
                self.assertFalse(any(g["kind"] == "psv" for g in s["safeguards"]), s["scenario_id"])

    def test_no_safeguard_design_improvement_reappears(self):
        dics = {d["scenario_id"]: d for d in DOC["design_improvement_candidates"]}
        no_safe = {k for k, d in dics.items() if "no_safeguard_found_in_graph" in d["triggers"]}
        self.assertTrue({s["scenario_id"] for s in scen(DOC, "p86-d44")} <= no_safe)
        pic = pat_scen(DOC, "p86-d10", "pat-pic-d09d10-output-fault")
        self.assertIn(pic["scenario_id"], no_safe)
        self.assertEqual(dics[pic["scenario_id"]]["basis"]["not_counted_safeguards"], ["entity-node-009"])
        for k in no_safe:
            hold = next(h for h in DOC["holds"] if h["hold_id"] == dics[k]["hold_ids"][0])
            self.assertEqual((hold["item"], hold["status"]), ("보호수단 존재 확인", "open"))

    def test_ids_stable_and_resolved_holds_closed(self):
        self.assertTrue(all(d["dic_id"] == "dic-" + d["scenario_id"] for d in DOC["design_improvement_candidates"]))
        doc = copy.deepcopy(DOC)
        sc = pat_scen(doc, "p86-d09", "pat-cv-ncfc-d09-fail-closed")
        keep = sc["safeguards"], sc["ai_interpretation"]["safeguards"]
        sc["safeguards"], sc["ai_interpretation"]["safeguards"] = [], []
        run.finalize(doc, GRAPH, CRIT, now)
        hold_id = next(d for d in doc["design_improvement_candidates"] if d["scenario_id"] == sc["scenario_id"])["hold_ids"][0]
        sc["safeguards"], sc["ai_interpretation"]["safeguards"] = keep
        run.finalize(doc, GRAPH, CRIT, now)
        h = next(x for x in doc["holds"] if x["hold_id"] == hold_id)
        self.assertEqual((h["status"], h["closed_by"]), ("closed", "condition_resolved"))
        self.assertEqual([d["dic_id"] for d in doc["design_improvement_candidates"]],
                         [d["dic_id"] for d in DOC["design_improvement_candidates"]])


class ExploreOrderTest(unittest.TestCase):

    def test_continuation_at_max_depth_recorded(self):
        q = GraphQuery(GRAPH)
        members = ex_mod.region_members(GRAPH, [m["entity_id"] for m in _load(REGION_FILE)["members"]])
        r = ex_mod.explore(q, PZR, members, ["has_endpoint", "measurement_connection", "signal_connection"], 4, 200)
        ext = {t["at"] for t in r["truncations"] if t["reason"] == "external_drawing"}
        self.assertIn("entity-node-002", ext)  # 깊이 4 = 최대 깊이에 걸린 연결점
        self.assertIn("max_depth", r["limits_hit"])

    def test_physical_path_preferred(self):
        q = GraphQuery(GRAPH)
        members = ex_mod.region_members(GRAPH, [m["entity_id"] for m in _load(REGION_FILE)["members"]])
        phys = ex_mod.explore(q, PZR, members, ["has_endpoint"], 12, 200)
        reachable = {r["entity_id"] for r in phys["reached"]}
        for r in DOC["explorations"][0]["reached"]:
            if r["entity_id"] in reachable:
                self.assertTrue(r["material_flow_path"], r["entity_id"])


class MergeAndModelTest(unittest.TestCase):

    def test_validated_only_after_successful_merge(self):
        with mock.patch.object(run, "_merge_ai", side_effect=RuntimeError("병합 실패")):
            doc = analyze(only={"p86-d09"})
        c = cand(doc, "p86-d09")
        self.assertEqual(c["analysis"]["ai_status"], "merge_error")
        self.assertTrue(all(s["ai_interpretation"] is None for s in scen(doc, "p86-d09")))
        rec = next(r for r in doc["ai_runs"] if r["candidate_id"] == c["candidate_id"])
        self.assertEqual(rec["status"], "merge_error")
        self.assertIn("병합 실패", rec["merge_error"])

    def fake(self, model):
        text = json.dumps(_load(os.path.join(FIXED_DIR, "deviation-p86-d09.json"))["output"], ensure_ascii=False)
        msg = types.SimpleNamespace(id="m", model=model, stop_reason="end_turn", stop_details=None, usage=None,
                                    content=[types.SimpleNamespace(type="text", text=text)])
        return types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: msg))

    @unittest.skipUnless(HAS_ANTHROPIC, "anthropic SDK 미설치(배포용 venv)")
    def test_response_model_mismatch_allowed_by_user_decision_with_warning(self):
        """사용자 결정(2026-11-04, '서버측 fallback은 켜되 응답 모델을 기록·표시')에 따른 허용:
        다른 모델이 응답해도 결과를 채택하되, 결과 JSON의 후보와 AI 실행 기록 양쪽에 response_model_differs 경고를 남긴다."""
        doc = analyze(client=ai.AnthropicClient(client=self.fake("claude-other-model")), only={"p86-d09"})
        c = cand(doc, "p86-d09")
        rec = next(r for r in doc["ai_runs"] if r["candidate_id"] == c["candidate_id"])
        self.assertEqual((rec["requested_model"], rec["response_model"], rec["model_mismatch"]),
                         ("claude-opus-5-5", "claude-other-model", True))
        self.assertEqual(c["analysis"]["warnings"][0]["type"], "response_model_differs")
        self.assertEqual(rec["warnings"][0]["type"], "response_model_differs")
        self.assertEqual(c["analysis"]["ai_status"], "validated")  # 채택됨
        self.assertEqual(pat_scen(doc, "p86-d09", "pat-cv-ncfc-d09-fail-closed")["ai_interpretation"]["response_model"],
                         "claude-other-model")
        same = analyze(client=ai.AnthropicClient(client=self.fake("claude-opus-5-5")), only={"p86-d09"})
        self.assertEqual(cand(same, "p86-d09")["analysis"]["warnings"], [])

    def test_model_allow_list(self):
        with self.assertRaises(ValueError):
            ai.AnthropicClient(model="claude-x-test")
        import analyze as script
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            script.main(["--live", "--model", "claude-x-test"])
        doc = analyze(client=ai.AnthropicClient(client=self.fake("claude-opus-5-5")), only={"p86-d09"})
        rec = doc["ai_runs"][0]
        self.assertEqual((rec["client"]["model"], rec["request"]["params"]["model"]), ("claude-opus-5-5", "claude-opus-5-5"))
        args = script.argparse.Namespace(live=True, model="claude-opus-5-5", fixed_dir=FIXED_DIR)
        with mock.patch.object(ai.AnthropicClient, "credentials_available", staticmethod(lambda: True)):
            self.assertEqual(script.make_client(args).model, "claude-opus-5-5")

    def test_rel_or_abs_other_drive(self):
        from hazop import paths
        with mock.patch.object(paths.os.path, "relpath", side_effect=ValueError("path is on mount 'D:'")):
            self.assertEqual(paths.rel_or_abs(FIXED_DIR, REPO_ROOT), os.path.abspath(FIXED_DIR).replace("\\", "/"))


class ReviewB12Test(unittest.TestCase):
    """Codex 적대적 검토 B1·B2 채택 항목 재현 테스트."""

    def test_1_detector_counts_only_with_confirmed_action(self):
        sc = pat_scen(DOC, "p86-d12", "pat-pzr-d12-overheat")
        te = next(g for g in sc["safeguards"] if g["tag"] == "RC-TE110")
        self.assertEqual((te["protective_action"], te["action_confirmed"], te["counts_as_found"]), ("detection", False, False))
        d = next(x for x in DOC["design_improvement_candidates"] if x["scenario_id"] == sc["scenario_id"])
        self.assertIn("no_safeguard_found_in_graph", d["triggers"])
        self.assertTrue(d["hold_ids"])
        psv = pat_scen(DOC, "p86-d09", "pat-cv-ncfc-d09-fail-closed")["safeguards"]
        self.assertTrue(all(g["protective_action"] == "self_acting" and g["counts_as_found"] for g in psv))
        g = copy.deepcopy(GRAPH)
        next(n for n in g["nodes"] if n["entity_id"] == "entity-node-004")["attributes"]["alarm_setpoint"] = "350 C"
        doc = analyze(data_inputs(graph=g), client=ai.FixedResponseClient(FIXED_DIR, verify_bundle=False))
        te2 = next(x for x in pat_scen(doc, "p86-d12", "pat-pzr-d12-overheat")["safeguards"] if x["tag"] == "RC-TE110")
        self.assertTrue(te2["counts_as_found"])

    def test_2_conservative_merge_of_ai_and_pattern_verdicts(self):
        doc = copy.deepcopy(DOC)
        sc = pat_scen(doc, "p86-d09", "pat-cv-ncfc-d09-fail-closed")
        for g in sc["ai_interpretation"]["safeguards"]:
            g["counts_as_found"] = False  # AI 쪽 판정이 부정
        self.assertTrue(all(g["counts_as_found"] for g in sc["safeguards"]))
        run.finalize(doc, GRAPH, CRIT, now)
        d = next(x for x in doc["design_improvement_candidates"] if x["scenario_id"] == sc["scenario_id"])
        self.assertIn("no_safeguard_found_in_graph", d["triggers"])

    def test_3_library_non_equipment_kind_blocks(self):
        inputs = data_inputs()
        lib = copy.deepcopy(inputs["patterns"])
        lib["patterns"][0]["equipment_kind"] = "tee"
        lib["deviation_safeguards"][0]["kind"] = "pipe_segment"
        bl = run.prepare(inputs["region"], GRAPH, inputs["catalog"], inputs["applicability"], lib, CRIT)["blockers"]
        self.assertTrue(any("'tee'는 실제 기기가 아님" in b for b in bl))
        self.assertTrue(any("'pipe_segment'는 실제 기기가 아님" in b for b in bl))
        out = copy.deepcopy(_load(os.path.join(FIXED_DIR, "deviation-p86-d09.json"))["output"])
        out["scenarios"][0]["safeguards"] = [{"node_id": "entity-node-003", "description": "tee"}]
        out["scenarios"][0]["risk"]["credited_safeguard_node_ids"] = []
        _, _, rej = validate.validate_response(out, DOC["evidence_bundles"]["deviation-p86-d09"], GRAPH, ai.RESPONSE_SCHEMA)
        self.assertTrue(any(r["index"] == 0 and "보호수단 entity-node-003" in r["reason"] for r in rej))

    def test_4_catalog_truncated_or_tampered_blocks(self):
        inputs = data_inputs()
        short = copy.deepcopy(inputs["catalog"])
        short["items"] = short["items"][:43]
        bl = run.prepare(inputs["region"], GRAPH, short, inputs["applicability"], inputs["patterns"], CRIT)["blockers"]
        self.assertTrue(any("44행" in b for b in bl))
        bad = copy.deepcopy(inputs["catalog"])
        bad["items"][8]["deviation_ko"] = "압력 변조"
        bl = run.prepare(inputs["region"], GRAPH, bad, inputs["applicability"], inputs["patterns"], CRIT)["blockers"]
        self.assertTrue(any("고정값과 다름" in b for b in bl) and any("지침서 §5.3" in b for b in bl))
        app = copy.deepcopy(inputs["applicability"])
        app["items"][16]["applicability"] = "applicable"
        bl = run.prepare(inputs["region"], GRAPH, inputs["catalog"], app, inputs["patterns"], CRIT)["blockers"]
        self.assertTrue(any("적용 판단 파일" in b for b in bl))

    def test_5_risk_criteria_tamper_blocks_and_independent_check(self):
        inputs = data_inputs()
        bad = copy.deepcopy(CRIT)
        bad["matrix"]["3"]["2"] = 2
        bl = run.prepare(inputs["region"], GRAPH, inputs["catalog"], inputs["applicability"], inputs["patterns"], bad)["blockers"]
        self.assertTrue(any("고정값과 다름" in b for b in bl))
        self.assertTrue(any("risk.MATRIX_P86" in b for b in bl))
        self.assertTrue(any("지침서 §6" in b for b in bl))
        self.assertEqual(risk.MATRIX_P86, TABLE5)
        doc = copy.deepcopy(DOC)
        s = next(x for x in doc["scenarios"] if x["risk_proposal"]["status"] == "proposed" and x["risk_proposal"]["risk"] == 4)
        s["risk_proposal"]["risk"] = 2  # 변조된 표대로 계산된 값
        self.assertEqual(run.check_result(doc, GRAPH, bad)["status"], "blocked")  # 기준표 파일이 아니라 코드 상수와 대조

    def test_6_pattern_and_cause_mismatch_rejected(self):
        out = copy.deepcopy(_load(os.path.join(FIXED_DIR, "deviation-p86-d09.json"))["output"])
        out["scenarios"][0]["cause_entity_ids"] = [PZR]  # 패턴 대상은 RC-PV101
        _, _, rej = validate.validate_response(out, DOC["evidence_bundles"]["deviation-p86-d09"], GRAPH, ai.RESPONSE_SCHEMA)
        self.assertTrue(any(r["index"] == 0 and "패턴과 원인 불일치" in r["reason"] for r in rej))

    def test_7_empty_evidence_or_basis_defers_risk(self):
        r = dict(BASIS, severity=3, frequency_without_safeguards=2)
        self.assertEqual(risk.evaluate(CRIT, r, {}, [])["status"], "deferred")
        self.assertEqual(risk.evaluate(CRIT, dict(r, severity_basis=" "), {}, ["ev"])["status"], "deferred")
        self.assertEqual(risk.evaluate(CRIT, dict(r, frequency_basis=""), {}, ["ev"])["status"], "deferred")
        self.assertEqual(risk.evaluate(CRIT, r, {}, ["ev"])["status"], "proposed")

    def test_8_resume_blocks_tampered_derived_results(self):
        tmp = tempfile.mkdtemp()
        try:
            _, run_dir = run.execute(raw_inputs(), ai.FixedResponseClient(FIXED_DIR), tmp, run_id="analysis-tamper",
                                     now=now, only={"p86-d10"})
            path = os.path.join(run_dir, "analysis.json")
            doc = _load(path)
            sc = next(x for x in doc["scenarios"] if x["origin"] == "pattern" and x["safeguards"]
                      and not x["safeguards"][0]["counts_as_found"])
            sc["safeguards"][0]["counts_as_found"] = True
            sc["safeguards"][0]["action_confirmed"] = True
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            with self.assertRaises(run.InputError) as cm:
                run.resume(run_dir, ai.FixedResponseClient(FIXED_DIR), now=now)
            self.assertIn("패턴 시나리오", str(cm.exception))
            doc["candidates"][16]["selection_status"] = "selected"
            sc["safeguards"][0]["counts_as_found"] = False
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            with self.assertRaises(run.InputError):
                run.resume(run_dir, ai.FixedResponseClient(FIXED_DIR), now=now)
        finally:
            shutil.rmtree(tmp)

    def test_9_interrupt_during_merge_rolls_back_and_hypothesis_ids_dedupe(self):
        doc = run.prepare_doc(data_inputs(), ai.FixedResponseClient(FIXED_DIR), "analysis-merge", now)
        before = copy.deepcopy((doc["scenarios"], [h for h in doc["holds"] if h["candidate_id"] == "deviation-p86-d09"]))
        with mock.patch.object(run, "_merge_ai", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run.run_ai_step(doc, GRAPH, CRIT, ai.FixedResponseClient(FIXED_DIR), now=now, only={"p86-d09"})
        self.assertEqual((doc["scenarios"], [h for h in doc["holds"] if h["candidate_id"] == "deviation-p86-d09"]), before)
        self.assertEqual(cand(doc, "p86-d09")["analysis"]["ai_status"], "not_requested")
        tmp = tempfile.mkdtemp()
        try:
            d = _load(os.path.join(FIXED_DIR, "deviation-p86-d09.json"))
            h = d["output"]["scenarios"][3]
            h.update(cause="RC-PZ01 압력 제어 이상", interpretation="도면 설비 기반", outside_graph_equipment=[])
            d["output"]["scenarios"].append(copy.deepcopy(h))  # 같은 가설 두 번
            with open(os.path.join(tmp, "deviation-p86-d09.json"), "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            doc = analyze(client=ai.FixedResponseClient(tmp), only={"p86-d09"})
        finally:
            shutil.rmtree(tmp)
        hyp = [x["scenario_id"] for x in scen(doc, "p86-d09") if x["origin"] == "ai_additional_hypothesis"]
        self.assertEqual(len(hyp), 1)
        self.assertRegex(hyp[0], r"^scenario-p86-d09-h-[0-9a-f]{10}$")

    def test_10_depth_by_shortest_kind_start_valve_and_chain_scope(self):
        g = synthetic_graph([("a", "vessel", "equipment", {}), ("b", "tank", "equipment", {}),
                             ("c", "transmitter", "instrument", {}), ("z", "controller", "instrument", {})],
                            [("s1", "a", "b", True), ("s2", "b", "c", True)], signals=[("a", "c"), ("c", "z")])
        r = ex_mod.explore(GraphQuery(g), "a", ex_mod.region_members(g, ["a", "b", "c", "z"]),
                           ["has_endpoint", "signal_connection"], 4, 100)
        got = {x["entity_id"]: x for x in r["reached"]}
        self.assertIn("z", got)  # 물리 4홉 경로에 깊이를 고정했다면 누락됨
        self.assertEqual(got["c"]["shortest_depth"], 1)
        self.assertEqual(got["c"]["path_basis"], "physical_preferred")
        self.assertEqual(got["c"]["depth"], len(got["c"]["path_edges"]))
        v = synthetic_graph([("v", "manual_valve", "valve", {}), ("t", "tank", "equipment", {})], [("s", "v", "t", True)])
        t = next(x for x in ex_mod.explore(GraphQuery(v), "v", {"v", "t", "s"}, ["has_endpoint"], 4, 10)["reached"]
                 if x["entity_id"] == "t")
        self.assertEqual((t["valve_state"], t["normal_operation_flow"]), ("position_unknown_on_path", None))
        from hazop.analysis import patterns as pat
        inputs = data_inputs()
        region = copy.deepcopy(inputs["region"])
        region["exploration"]["relation_kinds"] = ["has_endpoint", "measurement_connection"]
        doc = run.prepare_doc(run.prepare(region, GRAPH, inputs["catalog"], inputs["applicability"], inputs["patterns"],
                                          CRIT), None, "x", now)
        ids = {m["pattern_id"] for m in doc["evidence_bundles"]["deviation-p86-d09"]["pattern_matches"]["applied"]}
        self.assertFalse({"pat-tx-d09d10-loop-signal-fault", "pat-pic-d09d10-output-fault"} & ids)
        self.assertIsNone(pat.chain_scope(doc["explorations"][0]))

    def test_11_unknown_knowledge_status_defers(self):
        inputs = data_inputs()
        inputs["applicability"]["items"][16]["applicability_knowledge_status"] = "unknown"
        d17 = cand(analyze(inputs), "p86-d17")
        self.assertEqual((d17["selection_status"], d17["judgments"][0]["decided_by"]), ("deferred", "rule:R5"))


class ReviewB12Round2Test(unittest.TestCase):
    """Codex 재검토(B1·B2) 2회차 채택 항목 재현 테스트."""

    def tmp_response(self, item, mutate):
        tmp = tempfile.mkdtemp()
        d = _load(os.path.join(FIXED_DIR, "deviation-%s.json" % item))
        mutate(d["output"])
        with open(os.path.join(tmp, "deviation-%s.json" % item), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        try:
            return analyze(client=ai.FixedResponseClient(tmp), only={item})
        finally:
            shutil.rmtree(tmp)

    def test_1_premise_equipment_not_counted_as_safeguard(self):
        def m(out):
            s = out["scenarios"][0]  # RC-PV101 개방 실패, 패턴 보호수단 = PSV
            s["safeguards"] = []
            s["assumed_equipment"] = s["assumed_equipment"] + ["entity-node-014", "entity-node-015"]
            s["risk"]["credited_safeguard_node_ids"] = []
        doc = self.tmp_response("p86-d09", m)
        sc = pat_scen(doc, "p86-d09", "pat-cv-ncfc-d09-fail-closed")
        self.assertTrue(all(g["counts_as_found"] for g in sc["safeguards"]))  # 패턴 쪽 인정은 남아 있음
        d = next(x for x in doc["design_improvement_candidates"] if x["scenario_id"] == sc["scenario_id"])
        self.assertIn("no_safeguard_found_in_graph", d["triggers"])
        self.assertEqual(d["basis"]["premise_or_same_loop_overlap"], ["entity-node-014", "entity-node-015"])

    def test_2_resume_rechecks_ai_interpretation_and_risk(self):
        tmp = tempfile.mkdtemp()
        try:
            _, run_dir = run.execute(raw_inputs(), ai.FixedResponseClient(FIXED_DIR), tmp, run_id="analysis-ai-tamper",
                                     now=now, only={"p86-d09"})
            path = os.path.join(run_dir, "analysis.json")
            doc = _load(path)
            sc = next(x for x in doc["scenarios"] if x["risk_proposal"]["status"] == "proposed")
            sc["risk_proposal"]["risk"] = 1  # 저장 결과 변조(위험도 낮춤)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            with self.assertRaises(run.InputError) as cm:
                run.resume(run_dir, ai.FixedResponseClient(FIXED_DIR), now=now)
            self.assertIn("AI 해석·위험도", str(cm.exception))
            doc = _load(path)
            rec = next(r for r in doc["ai_runs"] if r["status"] == "validated")
            rec["response"]["scenarios"][0]["risk"]["severity"] = 1  # 실행 기록 원문 변조
            sc = next(x for x in doc["scenarios"] if x["risk_proposal"]["status"] == "proposed")
            sc["risk_proposal"]["risk"] = 4
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            with self.assertRaises(run.InputError):
                run.resume(run_dir, ai.FixedResponseClient(FIXED_DIR), now=now)
        finally:
            shutil.rmtree(tmp)

    def test_2b_untampered_resume_passes_replay(self):
        tmp = tempfile.mkdtemp()
        try:
            _, run_dir = run.execute(raw_inputs(), ai.FixedResponseClient(FIXED_DIR), tmp, run_id="analysis-replay",
                                     now=now, only={"p86-d09", "p86-d44"})
            doc = run.resume(run_dir, ai.FixedResponseClient(FIXED_DIR), now=now)
            self.assertEqual(sum(c["analysis"]["ai_status"] == "validated" for c in doc["candidates"]), 5)
            run.resume(run_dir, ai.FixedResponseClient(FIXED_DIR), now=now)  # 두 번째 재시도도 재검증 통과
        finally:
            shutil.rmtree(tmp)

    def test_3_self_acting_only_for_self_acting_kinds(self):
        inputs = data_inputs()
        lib = copy.deepcopy(inputs["patterns"])
        te = next(g for g in lib["deviation_safeguards"] if g["kind"] == "temperature_element")
        te["protective_action"] = "self_acting"
        bl = run.prepare(inputs["region"], GRAPH, inputs["catalog"], inputs["applicability"], lib, CRIT)["blockers"]
        self.assertTrue(any("자력식 기기가 아님" in b for b in bl))
        from hazop.analysis import equipment
        node = next(n for n in GRAPH["nodes"] if n["entity_id"] == "entity-node-004")
        self.assertFalse(equipment.protective_action_confirmed(node, "self_acting"))
        psv = next(n for n in GRAPH["nodes"] if n["entity_id"] == PSV101)
        self.assertTrue(equipment.protective_action_confirmed(psv, "self_acting"))

    def test_4_same_cause_hypotheses_kept_order_independent(self):
        def make(order):
            def m(out):
                h = out["scenarios"][3]
                h.update(cause="RC-PZ01 압력 제어 이상", interpretation="도면 설비 기반", outside_graph_equipment=[])
                low = copy.deepcopy(h)
                low["risk"].update(severity=1, frequency_without_safeguards=1, frequency_with_safeguards=None)
                high = copy.deepcopy(h)
                high["risk"].update(severity=4, frequency_without_safeguards=3, frequency_with_safeguards=None)
                out["scenarios"][3:] = [low, high] if order else [high, low]
            return m
        results = []
        for order in (True, False):
            doc = self.tmp_response("p86-d09", make(order))
            hyp = [x for x in scen(doc, "p86-d09") if x["origin"] == "ai_additional_hypothesis"]
            results.append(sorted((x["scenario_id"], x["risk_proposal"]["risk"], x["same_cause_hypotheses"]) for x in hyp))
        self.assertEqual(results[0], results[1])
        self.assertEqual(sorted(r[1] for r in results[0]), [1, 5])  # 위험도 높은 가설도 남음
        self.assertTrue(all(r[2] == 2 for r in results[0]))

    def test_5_boundary_extension_revisits_with_better_state(self):
        g = synthetic_graph([(n, "transmitter", "instrument", {}) for n in ("a", "b", "c", "y", "z")], [],
                            signals=[("a", "b"), ("b", "c"), ("c", "z"), ("a", "y"), ("y", "c")])
        r = ex_mod.explore(GraphQuery(g), "a", {"a", "y"}, ["signal_connection"], 4, 100, boundary_extension_depth=2)
        got = {x["entity_id"]: x for x in r["reached"]}
        self.assertIn("z", got)  # 최초 방문(a-b-c, 경계 밖 2)에 고정했다면 누락
        self.assertTrue(got["z"]["outside_region"])
        self.assertEqual(got["z"]["path_nodes"], ["a", "y", "c", "z"])


class ReviewRound3Test(unittest.TestCase):
    """3회차: 정직한 입력에서도 결과가 틀리는 논리 결함 재현."""

    def tmp_response(self, item, mutate, graph=None):
        tmp = tempfile.mkdtemp()
        d = _load(os.path.join(FIXED_DIR, "deviation-%s.json" % item))
        mutate(d["output"])
        with open(os.path.join(tmp, "deviation-%s.json" % item), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        try:
            inputs = data_inputs(graph=graph) if graph else None
            return analyze(inputs, client=ai.FixedResponseClient(tmp, verify_bundle=graph is None), only={item})
        finally:
            shutil.rmtree(tmp)

    def test_1_safeguard_only_variants_kept_and_conservative(self):
        def make(order):
            def m(out):
                h = out["scenarios"][3]
                h.update(cause="RC-PZ01 압력 제어 이상", interpretation="도면 설비 기반", outside_graph_equipment=[])
                with_sg = copy.deepcopy(h)
                with_sg["safeguards"] = [{"node_id": "entity-node-014", "description": "RC-PSV101"}]
                without = copy.deepcopy(h)
                without["safeguards"] = []
                out["scenarios"][3:] = [with_sg, without] if order else [without, with_sg]
            return m
        res = []
        for order in (True, False):
            doc = self.tmp_response("p86-d09", make(order))
            hyp = [x for x in scen(doc, "p86-d09") if x["origin"] == "ai_additional_hypothesis"]
            dics = {d["scenario_id"]: d for d in doc["design_improvement_candidates"]}
            res.append(sorted((x["scenario_id"], len(x["safeguards"]),
                               "no_safeguard_found_in_graph" in dics.get(x["scenario_id"], {}).get("triggers", []))
                              for x in hyp))
        self.assertEqual(res[0], res[1])
        self.assertEqual(len(res[0]), 2)  # 보호수단만 달라도 둘 다 남김
        self.assertTrue(all(r[2] for r in res[0]))  # 보수적으로 둘 다 보호수단 미발견

    def test_2_deferred_scenario_with_high_risk_is_candidate(self):
        g = copy.deepcopy(GRAPH)
        next(n for n in g["nodes"] if n["entity_id"] == PV101)["attributes"].pop("normal_position")

        def m(out):  # RC-V111(정상 위치 미확인 경로 뒤) 패턴을 위험도 4로 해석
            s = copy.deepcopy(out["scenarios"][0])
            s.update(pattern_match_id="m-pat-mv-no-d09-closed-entity-node-007", cause_entity_ids=["entity-node-007"],
                     assumed_equipment=["entity-node-007"], node_ids=["entity-node-007"], relation_ids=[],
                     evidence_ids=["ev-node-entity-node-007"], safeguards=[])
            s["risk"].update(credited_safeguard_node_ids=[], frequency_with_safeguards=None)
            out["scenarios"] = [s]
        doc = self.tmp_response("p86-d09", m, graph=g)
        sc = pat_scen(doc, "p86-d09", "pat-mv-no-d09-closed")
        self.assertEqual((sc["scenario_status"], sc["risk_proposal"]["risk"]), ("deferred", 4))
        d = next(x for x in doc["design_improvement_candidates"] if x["scenario_id"] == sc["scenario_id"])
        self.assertEqual(d["triggers"], ["risk_conditional_or_worse"])
        self.assertEqual(d["basis"]["scenario_status"], "deferred")
        self.assertIn("밸브 정상 위치 미확인", d["basis"]["scenario_status_reason"])

    def test_3_only_positive_action_evidence(self):
        from hazop.analysis import equipment
        node = lambda a: {"kind": "temperature_element", "attributes": a}  # noqa: E731
        for a in ({"interlock": False}, {"interlock": ""}, {"alarm_setpoint": 0}, {"alarm_setpoint": "0"},
                  {"alarm_setpoint": " "}, {"alarm_setpoint": None}, {"alarm_setpoint": True}, {"trip_setpoint": "none"},
                  {"alarm_setpoint": "없음"}):
            self.assertFalse(equipment.protective_action_confirmed(node(a), "detection"), a)
        for a in ({"interlock": True}, {"interlock": "yes"}, {"alarm_setpoint": "350 C"}, {"trip_setpoint": 16.5}):
            self.assertTrue(equipment.protective_action_confirmed(node(a), "detection"), a)

    def test_4_same_loop_as_ai_premise_not_counted(self):
        g = copy.deepcopy(GRAPH)
        next(n for n in g["nodes"] if n["entity_id"] == "entity-node-009")["attributes"]["alarm_setpoint"] = "16.0 MPa"

        def m(out):  # 압력 감소: PSV 개방 고착 시나리오의 전제에 PIC110 추가, 보호수단 비움
            s = out["scenarios"][1]
            s["assumed_equipment"] = s["assumed_equipment"] + ["entity-node-010"]
            s["safeguards"] = []
        doc = self.tmp_response("p86-d10", m, graph=g)
        sc = pat_scen(doc, "p86-d10", "pat-psv-nc-d10-open-stuck")
        pt = next(x for x in sc["safeguards"] if x["tag"] == "RC-PT110")
        self.assertTrue(pt["counts_as_found"])  # 패턴만 보면 '찾음'
        d = next(x for x in doc["design_improvement_candidates"] if x["scenario_id"] == sc["scenario_id"])
        self.assertIn("no_safeguard_found_in_graph", d["triggers"])
        self.assertIn("entity-node-009", d["basis"]["premise_or_same_loop_overlap"])

    def test_5_depth_matches_recorded_path_after_revisit(self):
        g = synthetic_graph([(n, "transmitter", "instrument", {}) for n in ("a", "b", "c", "x", "y", "z")], [],
                            signals=[("a", "b"), ("b", "c"), ("c", "z"), ("a", "x"), ("x", "y"), ("y", "c")])
        r = ex_mod.explore(GraphQuery(g), "a", {"a", "y"}, ["signal_connection"], 3, 100, boundary_extension_depth=3)
        got = {x["entity_id"]: x for x in r["reached"]}
        for x in got.values():
            self.assertEqual(x["depth"], len(x["path_edges"]))
            self.assertEqual(x["shortest_depth"], x["depth"])
        self.assertEqual((got["c"]["depth"], got["c"]["path_nodes"]), (2, ["a", "b", "c"]))
        self.assertEqual((got["z"]["depth"], got["z"]["path_nodes"]), (3, ["a", "b", "c", "z"]))


class ResultCheckTest(unittest.TestCase):

    def test_result_valid_and_storage_units_present(self):
        self.assertEqual(DOC["validation"]["status"], "passed", DOC["validation"]["errors"])
        for key in ("analysis_run", "candidates", "explorations", "evidence_bundles", "scenarios",
                    "design_improvement_candidates", "holds", "ai_runs"):
            self.assertIn(key, DOC)
        self.assertTrue(all(s["scenario_status"] in ("draft", "deferred") for s in DOC["scenarios"]))
        rec = next(r for r in DOC["ai_runs"] if r["status"] == "validated")
        self.assertEqual(rec["template"]["template_id"], ai.TEMPLATE_ID)
        self.assertIn("bundle_sha256", rec)
        self.assertEqual(rec["client"]["type"], "fixed_response")

    def test_tampered_risk_detected(self):
        doc = copy.deepcopy(DOC)
        s = next(x for x in doc["scenarios"] if x["risk_proposal"]["status"] == "proposed")
        s["risk_proposal"]["risk"] = 1 if s["risk_proposal"]["risk"] != 1 else 5
        self.assertEqual(run.check_result(doc, GRAPH, CRIT)["status"], "blocked")


class MaxDepthNotExpandedTest(unittest.TestCase):
    """남은작업 A4: max_depth 기록의 not_expanded가 지정한 모든 관계 종류(계측·신호 포함)의 미탐색 이웃을 담는다."""

    def test_not_expanded_covers_all_relation_kinds(self):
        q = GraphQuery(GRAPH)
        members = ex_mod.region_members(GRAPH, [m["entity_id"] for m in _load(REGION_FILE)["members"]])
        kinds = ["has_endpoint", "measurement_connection", "signal_connection"]
        adj = q.adjacency("all")
        non_physical = 0
        for depth in (1, 2, 3, 4):
            r = ex_mod.explore(q, PZR, members, kinds, depth, 200)
            reached = {x["entity_id"] for x in r["reached"]} | {PZR}
            recs = {t["at"]: t["not_expanded"] for t in r["truncations"] if t["reason"] == "max_depth"}
            for x in r["reached"]:
                if x["shortest_depth"] != depth:
                    continue
                for nb, eid in adj[x["entity_id"]]:
                    if q.edges[eid]["kind"] in kinds and nb not in reached:
                        self.assertIn(nb, recs.get(x["entity_id"], []), (depth, x["entity_id"], eid))
                        non_physical += q.edges[eid]["kind"] != "has_endpoint"
        self.assertGreater(non_physical, 0)  # 옛 2단계 방식에서 빠지던 계측·신호 이웃이 기록됨


class AIErrorMessageTest(unittest.TestCase):
    """남은작업 A11: 사용자에게 보이는 보류 문구는 한국어로 감싸고, 원문 예외·필드명은 실행 기록에만 남긴다."""

    RAW = ("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
           "'message': 'output_config.format.schema: unsupported'}}")

    def hold(self, doc, cid):
        return next(h for h in doc["holds"] if h["candidate_id"] == cid and h["source"] == "ai" and h["status"] == "open")

    def test_api_error_hidden_from_hold(self):
        raw = self.RAW

        class Failing:
            def describe(self):
                return {"type": "fake", "model": None}

            def infer(self, request):
                return {"status": "api_error", "error_type": "api_status", "status_code": 400, "error": raw}
        doc = analyze(client=Failing(), only={"p86-d09"})
        h = self.hold(doc, "deviation-p86-d09")
        text = h["item"] + h["reason"]
        for leak in ("output_config", "invalid_request_error", "Error code", "api_error", "api_status"):
            self.assertNotIn(leak, text)
        self.assertEqual(h["item"], "AI 해석 없음(AI 서비스 오류)")
        self.assertIn("AI 서비스가 오류 응답을 보냄(HTTP 400)", h["reason"])
        rec = next(r for r in doc["ai_runs"] if r["candidate_id"] == "deviation-p86-d09")
        self.assertIn(rec["ai_run_id"], h["reason"])
        self.assertEqual(rec["result"]["error"], raw)  # 원문은 실행 기록에 보존

    def test_client_exception_hidden_from_hold(self):
        class Raising:
            def describe(self):
                return {"type": "fake", "model": None}

            def infer(self, request):
                raise KeyError("output_config")
        doc = analyze(client=Raising(), only={"p86-d09"})
        h = self.hold(doc, "deviation-p86-d09")
        self.assertNotIn("output_config", h["reason"])
        self.assertNotIn("KeyError", h["reason"])
        rec = next(r for r in doc["ai_runs"] if r["candidate_id"] == "deviation-p86-d09")
        self.assertEqual((rec["result"]["error_type"], rec["result"]["error"]), ("KeyError", "'output_config'"))

    def test_validation_paths_hidden_from_hold(self):
        doc = analyze(client=ai.FixedResponseClient(BAD_DIR))
        h = self.hold(doc, "deviation-p86-d09")
        self.assertNotIn("$.", h["reason"])
        self.assertNotIn("reference_error", h["reason"])
        self.assertIn("참조 오류", h["reason"])
        rec = next(r for r in doc["ai_runs"] if r["candidate_id"] == "deviation-p86-d09")
        self.assertTrue(all(e["path"].startswith("$") for e in rec["validation"]["errors"]))

    def test_user_message_never_includes_raw_error(self):
        for status in ("no_response", "input_mismatch", "refused", "truncated", "parse_error", "client_error",
                       "merge_error", "api_error"):
            for et in ("rate_limit", "api_status", "connection", "APIResponseValidationError", None):
                msg = ai.user_message(status, {"error": self.RAW, "error_type": et, "status_code": 500})
                self.assertNotIn("output_config", msg)
                self.assertNotIn(et or "\0", msg)
                self.assertNotEqual(ai.status_label(status), status)


if __name__ == "__main__":
    unittest.main()
