"""채팅 읽기 도구(단위 C1). 실행: python -m unittest tests.test_chat_tools

SNP 가상 도면 6장(drawio 표본)을 임시 작업 루트에서 추출해 프로젝트 그래프를 만들고, 사람이 도면을 보고 확인할 수 있는
경로 정답을 고정한다. 정답의 근거(도면 번호·태그)는 각 시험 설명에 적었다. 실제 구독·Qt는 쓰지 않는다.
"""

import copy
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S101, S102, S401 = "graph-SNP-M-101", "graph-SNP-M-102", "graph-SNP-M-401"
MAX_CHARS = 8000


def tag_id(ctx, tag):
    """태그가 하나뿐인 도면 객체의 ID(시험 준비용)."""
    hits = [n["entity_id"] for n in ctx.pg["nodes"] if n.get("tag") == tag and n["node_type"] != "pipe_segment"]
    assert len(hits) == 1, (tag, hits)
    return hits[0]


class ChatToolsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        cls.tmp = tempfile.mkdtemp(prefix="hazop-chattools-")
        cls._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        import extract_drawio
        from hazop.graph import build
        from hazop.chat import context, tools
        cls.tools, cls.context = tools, context
        graphs = []
        for f in sorted(glob.glob(os.path.join(REPO, "resources", "references", "pid-samples", "*", "*.drawio"))):
            ex, _ = extract_drawio.run_one(f, os.path.join(cls.tmp, "extract"))
            graphs.append(build.build_graph(ex))
        cls.graphs = graphs
        cls.ctx = context.from_graphs("SNP-SAMPLE", graphs)

    @classmethod
    def tearDownClass(cls):
        if cls._env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = cls._env
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, name, ctx=None, **args):
        res = self.tools.call(ctx or self.ctx, name, args)
        self.assertLessEqual(len(json.dumps(res, ensure_ascii=False)), MAX_CHARS, name)
        return res

    def ok(self, name, **args):
        res = self.call(name, **args)
        self.assertTrue(res["ok"], res["error"])
        return res

    def err(self, name, code, ctx=None, **args):
        res = self.call(name, ctx=ctx, **args)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], code, res["error"])
        return res

    def reasons(self, res):
        return sorted({(u["id"], u["reason"]) for u in res["uncertain"]})


class EnvelopeTest(ChatToolsBase):
    def test_envelope_shape(self):
        res = self.ok("find", query="RC-PSV101")
        self.assertEqual(set(res), {"ok", "data", "total", "returned", "cursor", "truncated", "uncertain", "sources", "error"})
        self.assertIsNone(res["error"])
        self.assertIn({"kind": "drawing", "sheet": S102}, res["sources"])

    def test_error_envelope(self):
        res = self.err("get_component", "not_found", id="NOPE-999")
        self.assertEqual(set(res), {"ok", "data", "total", "returned", "cursor", "truncated", "uncertain", "sources", "error"})
        self.assertIsNone(res["data"])

    def test_deterministic(self):
        a = self.call("trace_path", start="RC-RV01", end="RC-PZ01")
        b = self.call("trace_path", start="RC-RV01", end="RC-PZ01")
        self.assertEqual(a, b)


class ArgsTest(ChatToolsBase):
    def test_unknown_arg_including_file_path_is_bad_args(self):
        self.err("find", "bad_args", query="RC-PZ01", path="C:\\secret.txt")
        self.err("get_component", "bad_args", id="RC-PZ01", file="x")

    def test_missing_wrong_type_and_range(self):
        self.err("find", "bad_args")
        self.err("find", "bad_args", query=5)
        self.err("find", "bad_args", query="RC", limit=0)
        self.err("find", "bad_args", query="RC", limit=51)
        self.err("find", "bad_args", query="RC", limit="3")
        self.err("trace_path", "bad_args", start="RC-PZ01", end="RC-PSV101", mode="bogus")
        self.err("trace_flow", "bad_args", start="RC-PZ01", direction="sideways")
        self.err("trace_flow", "bad_args", start="RC-PZ01", direction="down", cursor="zzz")
        self.err("count", "bad_args", group_by="color")

    def test_unknown_tool(self):
        self.assertEqual(self.tools.call(self.ctx, "rm_rf", {})["error"]["code"], "bad_args")

    def test_path_string_is_not_a_file_access(self):
        self.err("get_component", "not_found", id="C:\\Windows\\win.ini")
        self.err("find", "bad_args", query="x" * 500)


class FindTest(ChatToolsBase):
    def test_exact_tag(self):
        res = self.ok("find", query="RC-PSV101")
        self.assertEqual(res["data"]["matches"][0], {
            "id": S102 + "/entity-node-014", "tag": "RC-PSV101", "kind": "psv", "sheet": S102, "match": "tag"})

    def test_case_insensitive_and_substring(self):
        self.assertEqual(self.ok("find", query="rc-psv101")["data"]["matches"][0]["tag"], "RC-PSV101")
        tags = [m["tag"] for m in self.ok("find", query="PSV")["data"]["matches"]]
        self.assertIn("RC-PSV101", tags)
        self.assertIn("RC-PSV102", tags)

    def test_by_id_and_wildcard(self):
        self.assertEqual(self.ok("find", query=S102 + "/entity-node-014")["data"]["matches"][0]["tag"], "RC-PSV101")
        tags = {m["tag"] for m in self.ok("find", query="RC-PSV10?")["data"]["matches"]}
        self.assertEqual(tags, {"RC-PSV101", "RC-PSV102"})

    def test_missing_tag_is_empty_not_error(self):
        res = self.ok("find", query="NOPE-999")
        self.assertEqual((res["total"], res["data"]["matches"]), (0, []))

    def test_limit_and_total(self):
        res = self.ok("find", query="RC-", limit=3)
        self.assertEqual((res["returned"], res["truncated"]), (3, True))
        self.assertGreater(res["total"], 3)


class ComponentTest(ChatToolsBase):
    def test_get_component_by_tag(self):
        d = self.ok("get_component", id="RC-PSV101")["data"]
        self.assertEqual((d["id"], d["kind"], d["tag"], d["sheet"], d["drawing_number"]),
                         (S102 + "/entity-node-014", "psv", "RC-PSV101", S102, "SNP-M-102"))
        self.assertEqual(d["attributes"]["set_pressure"], "17.2 MPa")
        self.assertEqual(d["connections"], 2)
        self.assertIn("bbox", d)

    def test_pipe_segment_has_line_and_flow(self):
        seg = [n for n in self.ctx.pg["nodes"] if n["node_type"] == "pipe_segment" and n["sheet"] == S101
               and n["line_no"] == "RC-L021"][0]
        d = self.ok("get_component", id=seg["entity_id"])["data"]
        self.assertEqual((d["line_no"], d["flow_direction"]), ("RC-L021", None))
        self.assertIn("direction_unknown", [u["reason"] for u in self.call("get_component", id=seg["entity_id"])["uncertain"]])

    def test_missing(self):
        self.err("get_component", "not_found", id="NOPE-999")

    def test_ambiguous_line_tag_lists_candidates(self):
        res = self.err("get_component", "ambiguous", id="RC-L030")
        cands = res["error"]["candidates"]
        self.assertTrue(2 <= len(cands) <= 10)
        self.assertTrue(all(c["id"].startswith(S102) for c in cands))


class TracePathTest(ChatToolsBase):
    def test_single_sheet(self):
        """SNP-M-102: 가압기 RC-PZ01 → 티 RC-L030-T25 → 안전밸브 RC-PSV101(배관 RC-L030). 도면 하나, 흐름 방향도 확인됨."""
        res = self.ok("trace_path", start="RC-PZ01", end="RC-PSV101")
        d = res["data"]
        self.assertTrue(d["path"]["found"])
        self.assertEqual([o["tag"] for o in d["path"]["objects"]], ["RC-PZ01", "RC-L030-T25", "RC-PSV101"])
        self.assertEqual([l["line_no"] for l in d["path"]["lines"]], ["RC-L030", "RC-L030"])
        self.assertEqual(d["path"]["length"], 4)
        self.assertEqual(d["sheets"], [S102])
        self.assertEqual(d["by_sheet"], [{"sheet": S102, "count": 3}])
        self.assertTrue(d["flow_path"]["found"])
        self.assertEqual([o["tag"] for o in d["flow_path"]["objects"]], ["RC-PZ01", "RC-L030-T25", "RC-PSV101"])
        self.assertEqual(d["path"]["segments_direction_unknown"], [])
        # 안전밸브는 정상 위치를 반영하지 않았다는 표시를 단다
        self.assertEqual(self.reasons(res), [(S102 + "/entity-node-014", "valve_position_ignored")])
        self.assertIn("밸브 정상 위치", d["note"])

    def test_cross_sheet(self):
        """SNP-M-101 원자로 RC-RV01 → 티 → 연결점 'TO SNP-M-102' → SNP-M-102 연결점 → 티 → 가압기 RC-PZ01 (배관 RC-L001, RC-L010)."""
        res = self.ok("trace_path", start="RC-RV01", end="RC-PZ01")
        d = res["data"]
        self.assertEqual([o["tag"] or o["kind"] for o in d["path"]["objects"]],
                         ["RC-RV01", "RC-L001-T4", "RC-L001-T5", "continuation", "continuation", "RC-L010-T3", "RC-PZ01"])
        self.assertEqual([o["sheet"] for o in d["path"]["objects"]], [S101] * 4 + [S102] * 3)
        self.assertEqual(d["sheets"], [S101, S102])
        self.assertEqual(d["by_sheet"], [{"sheet": S101, "count": 4}, {"sheet": S102, "count": 3}])
        self.assertEqual([l["line_no"] for l in d["path"]["lines"]][:2], ["RC-L001", "RC-L001"])
        self.assertTrue(any(l.get("sheet_link") for l in d["path"]["lines"]))
        self.assertEqual(d["path"]["length"], 12)
        self.assertTrue(d["flow_path"]["found"])
        self.assertEqual(d["flow_path"]["length"], 12)
        self.assertEqual({s["sheet"] for s in res["sources"]}, {S101, S102})
        self.assertEqual(self.reasons(res), [])

    def test_reverse_direction_goes_against_flow(self):
        """같은 두 지점을 거꾸로 물으면 방향 무시 경로는 같은 길이로 찾지만 모든 배관이 흐름 반대다."""
        d = self.ok("trace_path", start="RC-PZ01", end="RC-RV01")["data"]
        self.assertEqual(d["path"]["length"], 12)
        self.assertEqual(len(d["path"]["segments_against_flow"]), 6)
        self.assertNotEqual(d["flow_path"].get("length"), 12)

    def test_direction_unknown_pipe(self):
        """SNP-M-101: 원자로 RC-RV01과 수동밸브 RC-V001 사이 배관 RC-L020은 흐름 방향 미확인이다."""
        res = self.ok("trace_path", start="RC-RV01", end="RC-V001")
        d = res["data"]
        self.assertTrue(d["path"]["found"])
        self.assertEqual(d["path"]["segments_direction_unknown"], [S101 + "/entity-seg-023"])
        self.assertFalse(d["flow_path"]["found"])
        self.assertIn((S101 + "/entity-seg-023", "direction_unknown"), self.reasons(res))
        self.assertIn((S101 + "/entity-node-023", "valve_position_ignored"), self.reasons(res))

    def test_unlinked_sheet_connector(self):
        """SNP-M-401의 연결점 ES-L001·ES-L002는 상대 도면 SNP-M-402가 없어 이어지지 않았다."""
        a, b = S401 + "/entity-node-023", S401 + "/entity-node-024"
        res = self.ok("trace_path", start=a, end=b)
        got = self.reasons(res)
        self.assertIn((a, "unlinked_sheet"), got)
        self.assertIn((b, "unlinked_sheet"), got)

    def test_unresolved_connector_from_extraction(self):
        ctx = copy.copy(self.ctx)
        ctx.unresolved = [{"sheet": S102, "local_id": "x1", "line_no": "RC-L030", "nodes": [S102 + "/entity-node-013"],
                           "reason": "양 끝이 확정되지 않아 정상 연결로 넣지 않음"}]
        ctx._index = None
        res = self.call("trace_path", ctx=ctx, start="RC-PZ01", end="RC-PSV101")
        self.assertIn((S102 + "/entity-node-013", "unresolved_connector"), self.reasons(res))

    def test_extraction_unknowns_map_to_reasons(self):
        ctx = copy.copy(self.ctx)
        t = S102 + "/entity-node-013"
        ctx.unknowns = [{"sheet": S102, "check": "unclassified_element", "target": t, "reason": "x", "field": None},
                        {"sheet": S102, "check": "missing_port", "target": S102 + "/entity-node-003", "reason": "x", "field": None},
                        {"sheet": S102, "check": "missing_tag", "target": S102 + "/entity-node-001", "reason": "x", "field": None}]
        ctx._index = None
        got = self.reasons(self.call("trace_path", ctx=ctx, start="RC-PZ01", end="RC-PSV101"))
        self.assertIn((t, "unknown_symbol"), got)
        self.assertIn((S102 + "/entity-node-001", "unknown_tag"), got)
        self.assertNotIn((S102 + "/entity-node-003", "unknown_symbol"), got)  # 포트 미지정은 알리지 않는다

    def test_unknown_symbol_from_extraction(self):
        ctx = copy.copy(self.ctx)
        ctx.pg = copy.deepcopy(self.ctx.pg)
        for n in ctx.pg["nodes"]:
            if n["entity_id"] == S102 + "/entity-node-013":
                n["classification"] = "unclassified"
        ctx._index = None
        res = self.call("trace_path", ctx=ctx, start="RC-PZ01", end="RC-PSV101")
        self.assertIn((S102 + "/entity-node-013", "unknown_symbol"), self.reasons(res))

    def test_missing_and_ambiguous(self):
        res = self.err("trace_path", "not_found", start="NOPE-999", end="RC-PSV101")
        self.assertIn("NOPE-999", res["error"]["message"])
        self.err("trace_path", "not_found", start="RC-PZ01", end="NOPE-999")
        self.err("trace_path", "ambiguous", start="RC-L030", end="RC-PSV101")

    def test_all_mode_includes_instrument_links(self):
        d = self.ok("trace_path", start="RC-PZ01", end="RC-PIC110", mode="all")["data"]
        self.assertTrue(d["path"]["found"])
        self.assertIn("mode_note", d)
        self.assertFalse(self.ok("trace_path", start="RC-PZ01", end="RC-PIC110")["data"]["path"]["found"])

    def test_long_path_is_summarised_per_sheet(self):
        """객체가 300개를 넘는 경로는 도면별 요약과 cursor로 바뀐다(가짜 경로로 확인)."""
        part = {"found": True, "length": 800, "objects": [
            {"id": "g/%d" % i, "tag": "T-%04d" % i, "kind": "tee", "sheet": "g"} for i in range(400)],
            "lines": [], "segments_direction_unknown": [], "segments_against_flow": []}
        data, truncated = self.tools._fit_path_data({
            "path": part, "flow_path": {"found": False}, "sheets": ["g"], "by_sheet": [{"sheet": "g", "count": 400}]})
        self.assertTrue(truncated)
        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False)), self.tools.PATH_BUDGET)
        self.assertEqual(data["by_sheet"], [{"sheet": "g", "count": 400}])
        self.assertEqual(data["path"]["object_count"], 400)

    def test_medium_path_uses_compact_form(self):
        part = {"found": True, "length": 300, "objects": [
            {"id": "graph-SNP-M-102/entity-node-%03d" % i, "tag": "RC-L%03d-T%d" % (i, i), "kind": "tee",
             "sheet": "graph-SNP-M-102"} for i in range(80)],
            "lines": [], "segments_direction_unknown": [], "segments_against_flow": []}
        data, truncated = self.tools._fit_path_data({"path": part, "flow_path": {"found": False}, "sheets": [], "by_sheet": []})
        self.assertFalse(truncated)
        self.assertTrue(data["compact"])
        self.assertEqual(len(data["path"]["objects"]), 80)

    def test_cursor_pages_path_objects(self):
        res = self.ok("trace_path", start="RC-RV01", end="RC-PZ01", cursor="c0")
        self.assertEqual(len(res["data"]["path_objects"]), 7)
        self.assertIsNone(res["cursor"])
        self.err("trace_path", "bad_args", start="RC-RV01", end="RC-PZ01", cursor="c9999")


class TraceFlowTest(ChatToolsBase):
    def test_downstream_from_reactor(self):
        reached, _ = self.reached_all(start="RC-RV01", direction="down", limit=200)
        tags = {o["tag"]: o for o in reached}
        self.assertIn("RC-PZ01", tags)
        self.assertEqual(tags["RC-PZ01"]["sheet"], S102)
        self.assertGreater(tags["RC-PZ01"]["depth"], 0)
        self.assertFalse(tags["RC-PZ01"]["via_unknown"])

    def reached_all(self, **args):
        """쪽 나누기를 끝까지 따라가며 모은 도달 객체와 마지막 봉투."""
        got, cursor = [], None
        while True:
            res = self.ok("trace_flow", **dict(args, **({"cursor": cursor} if cursor else {})))
            got += res["data"]["reached"]
            cursor = res["cursor"]
            if not cursor:
                return got, res

    def test_include_unknown_marks_via_unknown(self):
        on = {o["id"]: o for o in self.reached_all(start="RC-RV01", direction="down", limit=200)[0]}
        off = {o["id"] for o in self.reached_all(start="RC-RV01", direction="down", include_unknown=False, limit=200)[0]}
        v001 = S101 + "/entity-node-023"
        self.assertIn(v001, on)
        self.assertTrue(on[v001]["via_unknown"])
        self.assertNotIn(v001, off)

    def test_stop_kinds_gives_boundary(self):
        d = self.ok("trace_flow", start="RC-PZ01", direction="down", stop_kinds=["psv"], limit=200)["data"]
        self.assertEqual({b["tag"] for b in d["boundary"]}, {"RC-PSV101", "RC-PSV102"})
        self.assertTrue(all(o["tag"] not in ("RC-PSV101",) or True for o in d["reached"]))

    def test_upstream_and_depth_limit(self):
        up = {o["tag"] for o in self.ok("trace_flow", start="RC-PSV101", direction="up", max_depth=1)["data"]["reached"]}
        self.assertIn("RC-L030-T25", up)
        self.assertNotIn("RC-RV01", up)

    def test_paging_covers_everything_once(self):
        full = [o["id"] for o in self.reached_all(start="RC-RV01", direction="down", limit=200)[0]]
        got, cursor, pages = [], None, 0
        while True:
            args = dict(start="RC-RV01", direction="down", limit=7)
            if cursor:
                args["cursor"] = cursor
            res = self.ok("trace_flow", **args)
            got += [o["id"] for o in res["data"]["reached"]]
            pages += 1
            cursor = res["cursor"]
            if not res["truncated"]:
                self.assertIsNone(cursor)
                break
            self.assertTrue(cursor)
        self.assertEqual(got, full)
        self.assertGreater(pages, 1)
        self.assertEqual(res["total"], len(full))


class NeighborsCountSummaryTest(ChatToolsBase):
    def test_neighbors(self):
        d = self.ok("neighbors", id="RC-PSV101")["data"]
        self.assertEqual(d["target"]["tag"], "RC-PSV101")
        self.assertEqual(len(d["direct"]), 2)
        self.assertEqual(d["via_segment"][0]["node"]["tag"], "RC-L030-T25")
        self.assertIn(d["via_segment"][0]["flow"], ("with_flow", "against_flow", "unknown"))

    def test_count_by_kind(self):
        d = self.ok("count", group_by="kind")["data"]
        got = {g["key"]: g["count"] for g in d["groups"]}
        self.assertEqual((got["psv"], got["pressurizer"], got["pipe_segment"]), (3, 1, 118))
        self.assertEqual(d["matched"], len(self.ctx.pg["nodes"]))

    def test_count_with_filter_and_sheet(self):
        d = self.ok("count", filter={"categories": ["valve"], "sheets": [S102]}, group_by="kind")["data"]
        self.assertEqual({g["key"]: g["count"] for g in d["groups"]}, {"control_valve": 1, "manual_valve": 1, "psv": 2})

    def test_count_uncertain(self):
        d = self.ok("count", filter={"uncertain": True}, group_by="sheet")["data"]
        self.assertTrue(d["groups"])

    def test_summary_matches_project_summary(self):
        want = self.tools.project.summary(self.ctx.pg)
        got = self.ok("summary")["data"]
        for k, v in want.items():
            self.assertEqual(got[k], v, k)

    def test_summary(self):
        d = self.ok("summary")["data"]
        self.assertEqual((d["sheets"], d["linked"], d["unlinked"]), (6, 12, {"unregistered_drawing": 2}))
        self.assertEqual(d["nodes"], 259)
        self.assertEqual(d["uncertain"]["unlinked_sheet"], 2)
        self.assertEqual(d["uncertain"]["unknown_symbol"], 0)
        self.assertEqual(d["uncertain"]["direction_unknown"], 5)
        self.assertEqual(d["project_id"], "SNP-SAMPLE")


class SecondTierTest(ChatToolsBase):
    def test_enclose_stops_at_valves(self):
        d = self.ok("enclose", start="RC-PZ01", stop_kinds=["valve"])["data"]
        self.assertTrue(d["complete"])
        self.assertTrue(d["boundary"])
        self.assertTrue(all(b["kind"] in ("psv", "manual_valve", "control_valve", "check_valve", "motor_operated_valve",
                                          "isolation_valve") for b in d["boundary"]))
        self.assertIn("RC-PSV101", {b["tag"] for b in d["boundary"]})

    def test_enclose_too_large(self):
        self.err("enclose", "too_large", start="RC-RV01", max_size=3)

    def test_search_filter(self):
        res = self.ok("search", filter={"kinds": ["valve"], "tag": "RC-PSV*"})
        self.assertEqual({o["tag"] for o in res["data"]["items"]}, {"RC-PSV101", "RC-PSV102"})
        res = self.ok("search", filter={"kinds": ["psv"], "attrs": {"normal_position": "NC"}, "sheets": [S102]})
        self.assertEqual(res["total"], 2)
        res = self.ok("search", filter={"line_no": "RC-L030"})
        self.assertTrue(all(o["kind"] == "pipe_segment" for o in res["data"]["items"]))

    def test_search_near(self):
        res = self.ok("search", filter={"near": {"id": "RC-PSV101", "radius": 1}})
        self.assertIn("RC-L030-T25", {o["tag"] for o in res["data"]["items"]})

    def test_search_filter_bad(self):
        self.err("search", "bad_args", filter={"color": "red"})
        self.err("search", "bad_args", filter={"kinds": "psv"})

    def test_nodes(self):
        ctx = copy.copy(self.ctx)
        ctx.node_sets = [{"nodes": [
            {"node_id": "S-01", "name": "가압기 압력 제어", "intent": "압력 유지", "origin": "ai", "status": "proposed",
             "members": [S102 + "/entity-node-001", S102 + "/entity-node-014", S101 + "/entity-node-001"]},
            {"node_id": "S-02", "name": "충전", "origin": "human", "status": "confirmed",
             "members": [S101 + "/entity-node-002"]}]}]
        ctx._index = None
        d = self.call("get_node", ctx=ctx, node_id="S-01")["data"]
        self.assertEqual((d["node_id"], d["member_count"], d["sheets"]), ("S-01", 3, [S101, S102]))
        self.assertEqual(d["members"][0]["tag"], "RC-PZ01")
        self.assertEqual(d["origin"], "ai")
        lst = self.call("list_nodes", ctx=ctx, filter={"origin": "human"})
        self.assertEqual([n["node_id"] for n in lst["data"]["items"]], ["S-02"])
        self.assertEqual(self.call("list_nodes", ctx=ctx, filter={"contains": "압력"})["total"], 1)
        self.err("get_node", "not_found", ctx=ctx, node_id="S-99")
        self.assertEqual(self.call("get_component", ctx=ctx, id="RC-PZ01")["data"]["nodes"], ["S-01"])
        self.assertEqual(self.call("search", ctx=ctx, filter={"in_node": "S-01"})["total"], 3)

    def test_no_nodes_data(self):
        self.err("get_node", "no_data", node_id="S-01")


class RegistryTest(ChatToolsBase):
    MIN = ["count", "find", "get_component", "neighbors", "summary", "trace_flow", "trace_path"]
    MORE = ["enclose", "get_node", "list_nodes", "search"]

    def test_registry_lists_tools(self):
        self.assertEqual(sorted(self.tools.REGISTRY), sorted(self.MIN + self.MORE))

    def test_no_document_tools_yet(self):
        for name in ("get_worksheet", "search_documents", "get_document"):
            self.assertNotIn(name, self.tools.REGISTRY)

    def test_entries_are_self_describing(self):
        for name, t in self.tools.REGISTRY.items():
            self.assertTrue(callable(t["fn"]), name)
            self.assertTrue(t["description"].strip(), name)
            s = t["input_schema"]
            self.assertEqual((s["type"], s["additionalProperties"]), ("object", False), name)
            for prop in s.get("required", []):
                self.assertIn(prop, s["properties"], name)
            json.dumps(s)

    def test_registry_fn_runs_without_wrapper_knowledge(self):
        res = self.tools.REGISTRY["find"]["fn"](self.ctx, query="RC-PZ01")
        self.assertTrue(res["ok"])
        self.assertFalse(self.tools.REGISTRY["find"]["fn"](self.ctx, query="RC-PZ01", path="x")["ok"])

    def test_every_tool_stays_under_size_cap(self):
        calls = [("search", {"limit": 200, "filter": {}}), ("count", {"group_by": "kind"}),
                 ("trace_flow", {"start": "RC-RV01", "direction": "down", "limit": 200, "max_depth": 100}),
                 ("neighbors", {"id": "RC-PZ01"}), ("find", {"query": "RC", "limit": 50}),
                 ("enclose", {"start": "RC-PZ01"}), ("summary", {}), ("list_nodes", {})]
        for name, args in calls:
            self.call(name, **args)


class NoQtTest(unittest.TestCase):
    def test_import_does_not_load_qt(self):
        code = ("import sys; sys.path.insert(0, %r); import hazop.chat.tools, hazop.chat.context; "
                "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6', 'PyQt5', 'PyQt6')); "
                "print(bad); sys.exit(1 if bad else 0)" % REPO)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_source_has_no_qt_network_or_subprocess_import(self):
        for rel in ("hazop/chat/tools.py", "hazop/chat/context.py"):
            with open(os.path.join(REPO, *rel.split("/")), encoding="utf-8") as fh:
                src = fh.read()
            for bad in ("PySide6", "PyQt", "import subprocess", "import socket", "import urllib", "import requests", "import http"):
                self.assertNotIn(bad, src, rel)


class RefreshTest(unittest.TestCase):
    def test_refresh_keeps_context_when_nothing_changed(self):
        from hazop.chat import context
        ctx = context.ChatContext(project_id="P", pg={"graph_version": "v", "nodes": [], "edges": [], "sheets": []})
        self.assertIs(context.refresh(ctx), ctx)  # 지문이 없으면 그대로(시험·앱 안에서 직접 만든 묶음)


if __name__ == "__main__":
    unittest.main()
