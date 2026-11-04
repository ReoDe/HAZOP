"""단계 ③ 그래프 변환·질의 테스트. 실행: python -m unittest discover -s tests -t ."""

import copy
import glob
import json
import os
import sys
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.extract import drawio, svg_align  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.graph.query import GraphQuery, QueryError  # noqa: E402
from hazop.viewer import build as vbuild, check as vcheck  # noqa: E402

SAMPLES = sorted(glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio")))
SAMPLE = {os.path.basename(os.path.dirname(p)).split("_")[0]: p for p in SAMPLES}


def xml_counts(path):
    """원본 XML에서 직접 센다(추출·그래프 코드와 독립): 도형 노드 수와 line_type별 커넥터 수."""
    shapes, lines = 0, {}
    for o in ET.parse(path).getroot().iter("object"):
        cell = o.find("mxCell")
        if "pidIgnore=1" in (cell.get("style") or ""):
            continue
        if cell.get("vertex") == "1" and o.get("kind"):
            shapes += 1
        if cell.get("edge") == "1":
            lines[o.get("line_type")] = lines.get(o.get("line_type"), 0) + 1
    return shapes, lines


def graph_for(key):
    return build.build_graph(drawio.extract(SAMPLE[key], repo_root=REPO_ROOT))


class GraphBuildTest(unittest.TestCase):

    def test_counts_match_independent_xml_count(self):
        for key, path in SAMPLE.items():
            with self.subTest(sample=key):
                g = graph_for(key)
                shapes, lines = xml_counts(path)
                physical = lines.get("process", 0) + lines.get("process_secondary", 0)
                signal = lines.get("signal_electric", 0)
                measure = lines.get("instrument_tap", 0)
                self.assertEqual(len(g["nodes"]), shapes + physical)
                self.assertEqual(len(g["edges"]), 2 * physical + signal + measure)
                k = g["structure"]["edge_kinds"]
                self.assertEqual(k.get("has_endpoint", 0), 2 * physical)
                self.assertEqual(k.get("signal_connection", 0), signal)
                self.assertEqual(k.get("measurement_connection", 0), measure)
                self.assertEqual(g["validation"]["status"], "passed")
                self.assertEqual(g["structure"]["segments_with_endpoint_count_not_2"], [])

    def test_segment_preserves_source_and_flow_only_when_confirmed(self):
        ex = drawio.extract(SAMPLE["SNP-M-101"])
        g = build.build_graph(ex)
        rel = {r["local_id"]: r for r in ex["relations"]}
        ent = {n["entity_id"]: n for n in g["nodes"]}
        segs = [n for n in g["nodes"] if n["node_type"] == "pipe_segment"]
        self.assertTrue(segs)
        for s in segs:
            r = rel[s["local_id"]]
            self.assertEqual((s["line_no"], s["line_type"], s["source_object_id"]),
                             (r["line_no"], r["line_type"], r["source_object_id"]))
            if r["flow_direction"] is None:
                self.assertIsNone(s["flow_direction"])
            else:
                fd = s["flow_direction"]
                self.assertEqual(ent[fd["from"]]["local_id"], r["flow_direction"]["from"])
                self.assertEqual(ent[fd["to"]]["local_id"], r["flow_direction"]["to"])
                self.assertEqual((fd["from_end"], fd["to_end"], fd["basis"]),
                                 ("source", "target", "source_to_target"))
            ends = sorted((e["end"], ent[e["node"]]["local_id"]) for e in g["edges"]
                          if e["kind"] == "has_endpoint" and e["segment"] == s["entity_id"])
            self.assertEqual(ends, sorted((ep["end"], ep["node_local_id"]) for ep in r["endpoints"]))
        unknown_segs = {u["target"] for u in g["validation"]["unknowns"] if u["check"] == "unknown_flow_direction"}
        self.assertEqual(unknown_segs, {s["entity_id"] for s in segs if s["flow_direction"] is None})
        self.assertEqual({u["field"] for u in g["validation"]["unknowns"] if u["check"] == "unknown_flow_direction"},
                         {"flow_direction"})

    def test_mapping_covers_all_extraction_items(self):
        ex = drawio.extract(SAMPLE["SNP-M-101"])
        g = build.build_graph(ex)
        mapped = {m["local_id"] for m in g["entity_mapping"]}
        self.assertEqual(mapped, {n["local_id"] for n in ex["nodes"]} | {r["local_id"] for r in ex["relations"]})
        self.assertEqual(g["input_runs"], [ex["extraction_run_id"]])

    def test_same_input_same_output(self):
        ex = drawio.extract(SAMPLE["SNP-M-201"])
        a = json.dumps(build.build_graph(ex), sort_keys=True)
        b = json.dumps(build.build_graph(copy.deepcopy(ex)), sort_keys=True)
        self.assertEqual(a, b)

    def test_unresolved_connector_not_in_graph(self):
        ex = drawio.extract(SAMPLE["SNP-M-101"])
        moved = ex["relations"].pop(0)
        moved["endpoints"][1].update({"status": "unconnected", "node_local_id": None, "source_object_id": None})
        ex["unresolved_connectors"].append(moved)
        g = build.build_graph(ex)
        self.assertEqual([u["local_id"] for u in g["unresolved"]], [moved["local_id"]])
        self.assertNotIn(moved["local_id"], {n["local_id"] for n in g["nodes"]})
        self.assertNotIn(moved["local_id"], {e["local_id"] for e in g["edges"]})

    def test_blocked_input_and_missing_endpoint(self):
        ex = drawio.extract(SAMPLE["SNP-M-101"])
        ex["validation"]["status"] = "blocked"
        ex["relations"][0]["endpoints"][0]["node_local_id"] = "local-node-999"
        g = build.build_graph(ex)
        self.assertEqual(g["validation"]["status"], "blocked")
        checks = [b["check"] for b in g["validation"]["blockers"]]
        self.assertIn("input_blocked", checks)
        self.assertIn("missing_reference", checks)
        self.assertNotIn(ex["relations"][0]["local_id"], {e["local_id"] for e in g["edges"]})

    def test_relation_target_rule_flags_review_item(self):
        ex = drawio.extract(SAMPLE["SNP-M-101"])
        meas = [r for r in ex["relations"] if r["kind"] == "measurement_connection"][0]
        equip = [n for n in ex["nodes"] if n["category"] == "equipment"]
        meas["endpoints"][0]["node_local_id"] = equip[0]["local_id"]
        meas["endpoints"][1]["node_local_id"] = equip[1]["local_id"]
        g = build.build_graph(ex)
        items = [r for r in g["review_items"] if r["check"] == "relation_target_unexpected"]
        self.assertEqual([r["level"] for r in items], ["검토"])
        self.assertNotIn("relation_target_unexpected", [u["check"] for u in g["validation"]["unknowns"]])
        self.assertEqual(g["validation"]["status"], "passed")  # 검토 항목이지 차단 오류가 아님

    def test_signal_rule_is_reference_level_only(self):
        ex = drawio.extract(SAMPLE["SNP-M-101"])
        sig = [r for r in ex["relations"] if r["kind"] == "signal_connection"][0]
        pump = [n for n in ex["nodes"] if n["kind"] == "pump"][0]
        sig["endpoints"][1]["node_local_id"] = pump["local_id"]  # 예: 펌프 트립 신호
        g = build.build_graph(ex)
        items = [r for r in g["review_items"] if r["check"] == "relation_target_unexpected"]
        self.assertEqual([r["level"] for r in items], ["참고"])

    def test_self_loop_segment_is_review_item(self):
        ex = drawio.extract(SAMPLE["SNP-M-101"])
        rel = [r for r in ex["relations"] if r["kind"] == "physical_connection"][0]
        rel["endpoints"][1]["node_local_id"] = rel["endpoints"][0]["node_local_id"]
        rel["flow_direction"]["to"] = rel["flow_direction"]["from"]
        g = build.build_graph(ex)
        loops = [r for r in g["review_items"] if r["check"] == "self_loop_segment"]
        self.assertEqual(len(loops), 1)
        seg = loops[0]["target"]
        ends = sorted(e["end"] for e in g["edges"] if e["kind"] == "has_endpoint" and e["segment"] == seg)
        self.assertEqual(ends, ["source", "target"])
        q = GraphQuery(g)
        e_src = [e for e in g["edges"] if e.get("segment") == seg and e["end"] == "source"][0]["entity_id"]
        e_tgt = [e for e in g["edges"] if e.get("segment") == seg and e["end"] == "target"][0]["entity_id"]
        # 흐름 판정은 노드가 아니라 end 기준: 같은 노드라도 source 쪽으로 들어와 target 쪽으로 나가면 흐름 방향
        self.assertEqual(q.flow_relation(seg, e_src, e_tgt), "with_flow")
        self.assertEqual(q.flow_relation(seg, e_tgt, e_src), "against_flow")

    def test_graph_version_follows_input(self):
        ex = drawio.extract(SAMPLE["SNP-M-102"])
        v1 = build.build_graph(ex)["graph_version"]
        self.assertEqual(v1, build.build_graph(copy.deepcopy(ex))["graph_version"])
        ex["nodes"][0]["attributes"]["note"] = "changed"
        self.assertNotEqual(v1, build.build_graph(ex)["graph_version"])


class GraphQueryTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.q = GraphQuery(graph_for("SNP-M-101"))

    def test_physical_path_reactor_to_pump(self):
        p = self.q.path("RC-RV01", "RC-PP01", "physical")
        self.assertTrue(p["ignoring_direction"]["found"])
        self.assertTrue(p["confirmed_flow_direction"]["found"])
        kinds = {n["kind"] for n in p["ignoring_direction"]["nodes"]}
        self.assertNotIn("transmitter", kinds)
        self.assertIn("pipe_segment", kinds)

    def test_instrument_only_reachable_in_all_mode(self):
        self.assertFalse(self.q.path("RC-RV01", "RC-PT101", "physical")["ignoring_direction"]["found"])
        p = self.q.path("RC-RV01", "RC-PT101", "all")
        self.assertTrue(p["ignoring_direction"]["found"])
        self.assertFalse(p["confirmed_flow_direction"]["found"])  # 계측 연결은 방향이 없으므로
        self.assertIn("note", p)
        others = {x["tag"] for x in self.q.components()["not_physically_connected"]}
        self.assertTrue({"RC-PT101", "RC-TE101", "RC-TT101"} <= others)

    def test_unknown_direction_segment_is_reported(self):
        p = self.q.path("RC-V001", "RC-PP01", "physical")
        u = p["ignoring_direction"]
        self.assertTrue(u["found"])
        self.assertEqual(len(u["segments_direction_unknown"]), 1)
        seg = self.q.nodes[u["segments_direction_unknown"][0]]
        self.assertIsNone(seg["flow_direction"])
        self.assertFalse(p["confirmed_flow_direction"]["found"])

    def test_against_flow_is_marked(self):
        u = self.q.path("RC-PP01", "RC-SG01", "physical")["ignoring_direction"]
        self.assertTrue(u["found"])
        self.assertTrue(u["segments_against_flow"])
        ids = [n["entity_id"] for n in u["nodes"]]
        for seg in u["segments_against_flow"]:  # 흐름 반대로 지난 구간이 실제로 to -> from 순서인지
            i = ids.index(seg)
            fd = self.q.nodes[seg]["flow_direction"]
            self.assertEqual((ids[i - 1], ids[i + 1]), (fd["to"], fd["from"]))
        for n in u["nodes"]:
            if n["kind"] == "pipe_segment" and n["entity_id"] not in u["segments_against_flow"]:
                self.assertIn(n.get("flow"), ("with_flow", "unknown", None))

    def test_not_found_cases(self):
        p = self.q.path("RC-TE101", "RC-PP01", "physical")
        self.assertFalse(p["ignoring_direction"]["found"])
        self.assertFalse(p["confirmed_flow_direction"]["found"])
        self.assertIn("reason", p["confirmed_flow_direction"])
        self.assertIn("밸브 정상 위치", p["note"])

    def test_directed_signal_edge_not_used_for_flow_path(self):
        g = copy.deepcopy(self.q.graph)
        sig = [e for e in g["edges"] if e["kind"] == "signal_connection"][0]
        a, b = sig["nodes"]
        sig["flow_direction"] = {"from": a, "to": b, "from_end": "source", "to_end": "target", "basis": "test"}
        q = GraphQuery(g)
        p = q.path(a, b, "all")
        self.assertTrue(p["ignoring_direction"]["found"])
        self.assertEqual([e["kind"] for e in p["ignoring_direction"]["edges"]], ["signal_connection"])
        self.assertFalse(p["confirmed_flow_direction"]["found"])  # 신호·계측 엣지는 흐름 경로에 쓰지 않음

    def test_bfs_is_deterministic_and_ordered(self):
        adj = {"a": [("c", "e2"), ("b", "e1")], "b": [("d", "e3")], "c": [("d", "e4")], "d": []}
        for k in adj:
            adj[k].sort()
        self.assertEqual(GraphQuery.bfs(adj, "a", "d"), (["a", "b", "d"], ["e1", "e3"]))
        self.assertEqual(GraphQuery.bfs(adj, "a", "a"), (["a"], []))
        self.assertIsNone(GraphQuery.bfs(adj, "d", "a"))

    def test_neighbors_via_segment(self):
        nb = self.q.neighbors("RC-PP01")
        self.assertTrue(all(d["neighbor"]["kind"] == "pipe_segment" for d in nb["direct"]))
        flows = {v["node"]["tag"]: v["flow"] for v in nb["via_segment"]}
        self.assertEqual(flows.get("RC-L002-T11"), "against_flow")

    def test_resolve_errors(self):
        with self.assertRaises(QueryError):
            self.q.resolve("NO-SUCH-TAG")
        with self.assertRaises(QueryError):
            self.q.resolve("RC-L001")  # 여러 구간이 공유하는 라인 번호
        self.assertEqual(self.q.resolve("rc-pp01"), self.q.resolve("RC-PP01"))
        with self.assertRaises(QueryError):
            self.q.path("RC-RV01", "RC-PP01", "nope")

    def test_one_physical_component(self):
        comps = self.q.components()["physical_components"]
        self.assertEqual(len(comps), 1)


class ViewerGraphTest(unittest.TestCase):

    def page(self, key, graph="build"):
        ex = drawio.extract(SAMPLE[key], repo_root=REPO_ROOT)
        svg = glob.glob(os.path.join(os.path.dirname(SAMPLE[key]), "*.drawio.svg"))[0]
        al = svg_align.align(svg, ex)
        al["svg_file"] = os.path.relpath(svg, REPO_ROOT).replace("\\", "/")
        ex["coordinate_system"]["svg_alignment"] = al
        g = build.build_graph(ex) if graph == "build" else graph
        with open(svg, encoding="utf-8") as fh:
            svg_text = fh.read()
        return ex, g, vbuild.build_drawing_html(ex, svg_text, g)

    def test_embedded_graph_passes_checks(self):
        for key in SAMPLE:
            with self.subTest(sample=key):
                ex, g, page = self.page(key)
                self.assertEqual(vcheck.check_drawing_html(page, ex, g), [])
                self.assertEqual(len(vcheck.embedded_data(page, "graph")["nodes"]), len(g["nodes"]))

    def test_without_graph_still_builds(self):
        ex, _, page = self.page("SNP-M-102", graph=None)
        self.assertIsNone(vcheck.embedded_data(page, "graph"))
        self.assertEqual(vcheck.check_drawing_html(page, ex), [])

    def test_stale_graph_rejected_and_mismatch_flagged(self):
        ex, g, page = self.page("SNP-M-101")
        stale = copy.deepcopy(g)
        stale["input_runs"] = ["extract-old"]
        with self.assertRaises(ValueError):
            self.page("SNP-M-101", graph=stale)
        other = copy.deepcopy(g)
        other["nodes"] = other["nodes"][1:]
        self.assertTrue(any("불일치" in p for p in vcheck.check_drawing_html(page, ex, other)))

    def test_graph_json_escaped(self):
        ex, g, _ = self.page("SNP-M-101")
        g["nodes"][0]["label_text"] = "</script><!--"
        svg = glob.glob(os.path.join(os.path.dirname(SAMPLE["SNP-M-101"]), "*.drawio.svg"))[0]
        with open(svg, encoding="utf-8") as fh:
            page = vbuild.build_drawing_html(ex, fh.read(), g)
        self.assertEqual(vcheck.active_content(page), [])
        self.assertEqual(vcheck.embedded_data(page, "graph")["nodes"][0]["label_text"], "</script><!--")


if __name__ == "__main__":
    unittest.main()
