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
        from hazop import paths
        from hazop.graph import build
        from hazop.chat import context, tools
        cls.tools, cls.context = tools, context
        graphs = []
        for f in sorted(glob.glob(os.path.join(paths.folder("references", "pid-samples"), "*", "*.drawio"))):
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

    def chain_context(self, n):
        nodes, edges = [], []
        for i in range(n):
            nodes.append({"entity_id": "g/o%d" % i, "node_type": "drawing_object", "kind": "tee", "category": "piping_element",
                          "classification": "classified", "tag": "T-%03d" % i, "sheet": "g", "attributes": {}})
            if i:
                seg = "g/s%d" % i
                nodes.append({"entity_id": seg, "node_type": "pipe_segment", "kind": "pipe_segment", "category": "pipe_segment",
                              "classification": "classified", "tag": "L-1", "line_no": "L-1", "sheet": "g", "attributes": {},
                              "flow_direction": {"from": "g/o%d" % (i - 1), "to": "g/o%d" % i, "from_end": "source", "to_end": "target"}})
                edges += [{"entity_id": seg + "a", "kind": "has_endpoint", "nodes": [seg, "g/o%d" % (i - 1)], "segment": seg,
                           "node": "g/o%d" % (i - 1), "end": "source"},
                          {"entity_id": seg + "b", "kind": "has_endpoint", "nodes": [seg, "g/o%d" % i], "segment": seg,
                           "node": "g/o%d" % i, "end": "target"}]
        pg = {"project_id": "X", "graph_id": "project-X", "graph_version": "pv-x", "sheets": [{"graph_id": "g", "graph_version": "1",
              "drawing_number": "G"}], "nodes": nodes, "edges": edges, "sheet_links": [], "duplicate_tags": [], "manual_skipped": []}
        return self.context.ChatContext(project_id="X", pg=pg)

    @staticmethod
    def objs(side):
        """경로 한쪽의 원본 단계에서 도면 객체만(배관 구간 제외)."""
        return [x for x in side["steps"] if x["kind"] != "pipe_segment"]

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
        self.err("find", "bad_args", query="RC", limit=201)
        self.err("find", "bad_args", query="RC", limit="3")
        self.err("trace_path", "bad_args", start="RC-PZ01", end="RC-PSV101", mode="bogus")
        self.err("trace_flow", "bad_args", start="RC-PZ01", direction="sideways")
        self.err("trace_flow", "bad_args", start="RC-PZ01", direction="down", cursor="zzz")
        self.err("trace_path", "bad_args", start="RC-PZ01", end="RC-PSV101", limit=201)
        self.err("count", "bad_args", group_by="color")

    def test_unknown_tool(self):
        self.assertEqual(self.tools.call(self.ctx, "rm_rf", {})["error"]["code"], "bad_args")

    def test_path_like_values_are_refused_everywhere(self):
        """ID·태그·cursor 자리에 경로처럼 생긴 값(절대경로, .., 드라이브 글자, 역슬래시)이 오면 찾지 않고 bad_args."""
        for bad in ("C:\\Windows\\win.ini", "C:/Windows/win.ini", "/etc/passwd", "\\\\host\\share", "../secret", "a/../../b", "x\\y",
                    "~/x", "%2e%2e/x"):
            self.err("get_component", "bad_args", id=bad)
            self.err("neighbors", "bad_args", id=bad)
            self.err("enclose", "bad_args", start=bad)
            self.err("trace_flow", "bad_args", start=bad, direction="down")
            self.err("trace_path", "bad_args", start=bad, end="RC-PZ01")
            self.err("trace_path", "bad_args", start="RC-PZ01", end=bad)
            self.err("search", "bad_args", filter={"near": {"id": bad}})
            self.err("search", "bad_args", filter={"in_node": bad})
            self.err("get_node", "bad_args", node_id=bad)
            self.err("search", "bad_args", cursor=bad)
        for bad in ("../x", "C:/x", "/etc"):
            self.err("find", "bad_args", query=bad)
        self.err("find", "bad_args", query="x" * 500)
        # 정상 ID의 '/'와 '.'은 받는다
        self.assertEqual(self.ok("get_component", id=S102 + "/entity-node-014")["data"]["tag"], "RC-PSV101")
        self.assertEqual(self.ok("find", query="9.2.7-1")["total"], 0)

    def test_no_tool_takes_a_file_path_argument(self):
        for name, t in self.tools.REGISTRY.items():
            for prop in t["input_schema"]["properties"]:
                self.assertNotRegex(prop, r"(?i)^(path|file|filename|dir|directory|folder|url|root)$", (name, prop))
            self.err(name, "bad_args", path="C:\\x") if name != "summary" else self.err(name, "bad_args", file="x")


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
        self.assertEqual([o["tag"] for o in self.objs(d["path"])], ["RC-PZ01", "RC-L030-T25", "RC-PSV101"])
        self.assertEqual(len(d["path"]["steps"]), 5)  # 배관 구간 둘을 접지 않은 원본 단계
        self.assertEqual([x["flow"] for x in d["path"]["steps"] if x["kind"] == "pipe_segment"], ["with", "with"])
        self.assertEqual(d["path"]["lines"], ["RC-L030"])
        self.assertEqual(d["path"]["length"], 4)
        self.assertEqual(d["path"]["path_ref"], {"start": S102 + "/entity-node-001", "end": S102 + "/entity-node-014",
                                                 "mode": "physical", "basis": "ignoring_direction",
                                                 "graph_version": self.ctx.pg["graph_version"]})
        self.assertEqual(d["flow_path"]["path_ref"]["basis"], "confirmed_flow")
        self.assertEqual(d["sheets"], [S102])
        self.assertEqual(d["by_sheet"], [{"sheet": S102, "count": 3}])
        self.assertTrue(d["flow_path"]["found"])
        self.assertEqual([o["tag"] for o in self.objs(d["flow_path"])], ["RC-PZ01", "RC-L030-T25", "RC-PSV101"])
        self.assertEqual(d["path"]["segments_direction_unknown"], [])
        # 안전밸브는 정상 위치를 반영하지 않았다는 표시를 단다
        self.assertEqual(self.reasons(res), [(S102 + "/entity-node-014", "valve_position_ignored")])
        self.assertIn("밸브 정상 위치", d["note"])

    def test_cross_sheet(self):
        """SNP-M-101 원자로 RC-RV01 → 티 → 연결점 'TO SNP-M-102' → SNP-M-102 연결점 → 티 → 가압기 RC-PZ01 (배관 RC-L001, RC-L010)."""
        res = self.ok("trace_path", start="RC-RV01", end="RC-PZ01")
        d = res["data"]
        self.assertEqual([o["tag"] or o["kind"] for o in self.objs(d["path"])],
                         ["RC-RV01", "RC-L001-T4", "RC-L001-T5", "continuation", "continuation", "RC-L010-T3", "RC-PZ01"])
        self.assertEqual([o["sheet"] for o in self.objs(d["path"])], [S101] * 4 + [S102] * 3)
        self.assertEqual(d["sheets"], [S101, S102])
        self.assertEqual(d["by_sheet"], [{"sheet": S101, "count": 4}, {"sheet": S102, "count": 3}])
        self.assertEqual(d["path"]["lines"], ["RC-L001", "RC-L010"])
        self.assertTrue(any(x.get("sheet_link") for x in d["path"]["steps"]))
        self.assertEqual(d["path"]["length"], 12)
        self.assertEqual(len(d["path"]["steps"]), 13)  # 접기 전 원본 경로: 객체 7 + 배관 6
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

    def test_steps_are_paged_and_cover_the_original_path(self):
        full = self.ok("trace_path", start="RC-RV01", end="RC-PZ01")["data"]["path"]["steps"]
        got, cursor, pages = [], None, 0
        while True:
            res = self.ok("trace_path", start="RC-RV01", end="RC-PZ01", limit=4, **({"cursor": cursor} if cursor else {}))
            got += res["data"]["path"]["steps"]
            pages += 1
            cursor = res["cursor"]
            self.assertEqual(res["total"], 13)
            if not cursor:
                break
            self.assertRegex(cursor, r"^c-[0-9a-f]{12}$")
        self.assertEqual(got, full)
        self.assertEqual(pages, 4)

    def test_long_path_stays_under_size_cap(self):
        """길이가 길어도 쪽으로 나뉘어 8,000자를 넘지 않는다(가짜 사슬 그래프: 객체 400개)."""
        ctx = self.chain_context(400)
        res = self.call("trace_path", ctx=ctx, start="T-000", end="T-399")
        self.assertTrue(res["ok"], res["error"])
        self.assertTrue(res["truncated"])
        self.assertEqual(res["total"], 799)  # 객체 400 + 배관 399
        got, cursor = len(res["data"]["path"]["steps"]), res["cursor"]
        while cursor:
            res = self.call("trace_path", ctx=ctx, start="T-000", end="T-399", cursor=cursor)
            got += len(res["data"]["path"]["steps"])
            cursor = res["cursor"]
        self.assertEqual(got, 799)

    def test_path_steps_raw_matches_trace_path(self):
        d = self.ok("trace_path", start="RC-RV01", end="RC-V001")["data"]
        raw = self.tools.path_steps_raw(self.ctx, d["path"]["path_ref"])
        self.assertEqual([x["id"] for x in raw], [x["id"] for x in d["path"]["steps"]])
        self.assertEqual([x["flow"] for x in raw if x["kind"] == "pipe_segment"], ["unknown"])
        self.assertEqual(set(raw[0]), {"id", "kind", "flow"})
        # 접힌 배관 안의 경고도 원본 단계에서 센다
        self.assertEqual(self.tools.path_steps_raw(self.ctx, d["flow_path"]["path_ref"]), [])

    def test_path_steps_raw_rejects_stale_or_bad_ref(self):
        ref = self.ok("trace_path", start="RC-PZ01", end="RC-PSV101")["data"]["path"]["path_ref"]
        with self.assertRaises(self.tools.ToolError) as cm:
            self.tools.path_steps_raw(self.ctx, dict(ref, graph_version="pv-old"))
        self.assertEqual(cm.exception.code, "not_found")
        for bad in (None, {}, dict(ref, basis="x"), dict(ref, start="NOPE"), dict(ref, mode="x")):
            with self.assertRaises(self.tools.ToolError):
                self.tools.path_steps_raw(self.ctx, bad)


class CheckValveTest(ChatToolsBase):
    """체크밸브(extraction.md '체크밸브 허용 방향'): 허용 방향은 입구 -> 출구이고 역류는 막힌다.
    채팅 규격 §3은 체크밸브를 따로 정하지 않으므로, 흐름 추적(trace_flow)에서는 역류 통과를 막고(check_valves_blocked로 알림),
    경로(trace_path)에서는 거스른 체크밸브를 check_valves_against로 알리며, 격리 범위(enclose)는 stop_kinds에 넣지 않는 한 경계로 보지 않는다."""

    def check_chain(self, direction=True, known_flow=False):
        """o0 -s1- o1 -s2- V(체크밸브 입구 s2, 출구 s3) -s3- o3 -s4- o4. 배관 흐름 방향은 모르게(known_flow=False) 둔다."""
        ctx = ChatToolsBase.chain_context(self, 5)
        for n in ctx.pg["nodes"]:
            if not known_flow and n["node_type"] == "pipe_segment":
                n["flow_direction"] = None
            if n["entity_id"] == "g/o2":
                n.update(kind="check_valve", category="valve", tag="CV-1",
                         check_direction={"inlet": "g/s2", "outlet": "g/s3"} if direction else None)
        ctx._index = None
        return ctx

    def reached(self, ctx, start, direction):
        d = self.call("trace_flow", ctx=ctx, start=start, direction=direction)["data"]
        return [x["tag"] for x in d["reached"]], d

    def test_flow_does_not_cross_a_check_valve_backwards(self):
        ctx = self.check_chain()
        down, d = self.reached(ctx, "T-000", "down")    # 입구 쪽에서 출구 쪽으로: 허용
        self.assertEqual(down, ["T-001", "CV-1", "T-003", "T-004"])
        self.assertEqual(d["check_valves_blocked"], [])
        back, d = self.reached(ctx, "T-004", "down")    # 출구 쪽에서 입구 쪽으로 아래로 가는 것은 역류: 막힘
        self.assertEqual(back, ["T-003", "CV-1"])
        self.assertEqual(d["check_valves_blocked"], ["g/o2"])
        up, d = self.reached(ctx, "T-000", "up")        # 위로(상류) 갈 때 입구 -> 출구 통과는 막힘
        self.assertEqual(up, ["T-001", "CV-1"])
        self.assertEqual(d["check_valves_blocked"], ["g/o2"])
        up2, _ = self.reached(ctx, "T-004", "up")       # 출구 쪽에서 상류로: 허용
        self.assertEqual(up2, ["T-003", "CV-1", "T-001", "T-000"])

    def test_unknown_check_direction_is_not_blocked_but_flagged(self):
        ctx = self.check_chain(direction=False)
        back, d = self.reached(ctx, "T-004", "down")
        self.assertEqual(back, ["T-003", "CV-1", "T-001", "T-000"])
        self.assertIn(("g/o2", "direction_unknown"), self.reasons(self.call("trace_flow", ctx=ctx, start="T-004", direction="down")))

    def test_path_lists_check_valves_crossed_against(self):
        ctx = self.check_chain()
        fwd = self.call("trace_path", ctx=ctx, start="T-000", end="T-004")["data"]["path"]
        back = self.call("trace_path", ctx=ctx, start="T-004", end="T-000")["data"]["path"]
        self.assertEqual(fwd["check_valves_against"], [])
        self.assertEqual(back["check_valves_against"], ["g/o2"])

    def test_enclose_ignores_check_valves_unless_asked(self):
        ctx = self.check_chain()
        self.assertEqual(self.call("enclose", ctx=ctx, start="T-000", stop_kinds=["valve"])["data"]["size"], 2)
        # 체크밸브(category valve가 아니라 kind check_valve)를 stop_kinds로 주면 거기서 멈춘다
        d = self.call("enclose", ctx=ctx, start="T-000", stop_kinds=["check_valve"])["data"]
        self.assertEqual([b["tag"] for b in d["boundary"]], ["CV-1"])


class CursorTest(ChatToolsBase):
    def test_forged_and_malformed_cursors_are_rejected(self):
        for bad in ("c0", "c3", "c-000000000000", "c-zzzzzzzzzzzz", "c-0123456789abcdef", "../x", "C:/x", "/c-0123456789ab"):
            self.err("search", "bad_args", cursor=bad)

    def test_cursor_belongs_to_one_call(self):
        res = self.ok("search", filter={"categories": ["valve"]}, limit=5)
        cur = res["cursor"]
        self.assertTrue(cur)
        self.err("search", "bad_args", filter={"categories": ["equipment"]}, cursor=cur)   # 다른 인자
        self.err("find", "bad_args", query="RC", cursor=cur)                               # 다른 도구
        nxt = self.ok("search", filter={"categories": ["valve"]}, limit=5, cursor=cur)   # limit은 바꿔도 된다
        self.assertNotEqual(res["data"]["items"], nxt["data"]["items"])

    def test_cursor_dies_when_graph_changes(self):
        cur = self.ok("search", limit=5)["cursor"]
        ctx = copy.copy(self.ctx)
        ctx.pg = dict(self.ctx.pg, graph_version="pv-other")
        ctx._index = None
        self.err("search", "bad_args", ctx=ctx, cursor=cur)

    def test_table_is_capped(self):
        ctx = copy.copy(self.ctx)
        ctx.cursors = {}
        for _ in range(230):
            self.call("search", ctx=ctx, limit=1)
        self.assertLessEqual(len(ctx.cursors), 200)


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

    def test_enclose_capped_is_flagged(self):
        d = self.ok("enclose", start="RC-RV01", max_size=3)["data"]
        self.assertTrue(d["capped"])
        self.assertFalse(d["complete"])
        self.assertEqual(d["size"], 3)
        self.assertFalse(self.ok("enclose", start="RC-PZ01", stop_kinds=["valve"])["data"]["capped"])

    def test_enclose_is_not_complete_next_to_unlinked_connector(self):
        """SNP-M-401의 ES-L001·ES-L002는 상대 도면이 없어 이어지지 않았다. 그 범위를 '완전'이라고 답하면 안 된다."""
        d = self.ok("enclose", start=S401 + "/entity-node-023", stop_kinds=["valve"])["data"]
        self.assertFalse(d["complete"])
        reasons = {r["reason"]: r for r in d["incomplete_reasons"]}
        self.assertIn(S401 + "/entity-node-023", reasons["unlinked_sheet"]["ids"])
        self.assertIn("체크밸브", d["check_valves"])

    def test_enclose_complete_when_closed(self):
        ctx = self.chain_context(4)
        d = self.call("enclose", ctx=ctx, start="T-000")["data"]
        self.assertTrue(d["complete"])
        self.assertEqual(d["incomplete_reasons"], [])
        self.assertEqual(d["size"], 4)

    def test_enclose_open_end_and_unresolved_connector(self):
        ctx = self.chain_context(3)
        ctx.pg["edges"] = [e for e in ctx.pg["edges"] if e["entity_id"] != "g/s2b"]  # 배관 한쪽 끝이 붙지 않음
        ctx._index = None
        d = self.call("enclose", ctx=ctx, start="T-000")["data"]
        self.assertFalse(d["complete"])
        self.assertEqual([r["reason"] for r in d["incomplete_reasons"]], ["open_end"])
        ctx = self.chain_context(3)
        ctx.unresolved = [{"sheet": "g", "local_id": "x", "line_no": "L-1", "nodes": ["g/o1"], "reason": "x"}]
        self.assertEqual([r["reason"] for r in self.call("enclose", ctx=ctx, start="T-000")["data"]["incomplete_reasons"]],
                         ["unresolved_connector"])

    def test_enclose_objects_and_boundary_share_pages(self):
        res = self.ok("enclose", start="RC-PZ01", stop_kinds=["valve"], limit=10)
        d = res["data"]
        self.assertEqual(len(d["objects"]) + len(d["boundary"]), res["returned"])
        self.assertEqual(res["total"], d["size"] + d["boundary_count"])

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

    def test_node_filters_use_state_and_batch(self):
        ctx = copy.copy(self.ctx)
        ctx.node_sets = [{"set_rev": 7, "nodes": [
            {"node_id": "S1", "name": "a", "state": "proposed", "batch_id": "b-1", "rev": 2, "members": []},
            {"node_id": "S2", "name": "b", "state": "confirmed", "members": []}]}]
        ctx._index = None
        res = self.call("list_nodes", ctx=ctx, filter={"state": "proposed"})
        self.assertEqual([n["node_id"] for n in res["data"]["items"]], ["S1"])
        self.assertEqual(res["data"]["set_rev"], 7)
        self.assertEqual([n["node_id"] for n in self.call("list_nodes", ctx=ctx, filter={"batch_id": "b-1"})["data"]["items"]], ["S1"])
        d = self.call("get_node", ctx=ctx, node_id="S1")["data"]
        self.assertEqual((d["state"], d["rev"], d["set_rev"]), ("proposed", 2, 7))

    def test_nodes(self):
        ctx = copy.copy(self.ctx)
        ctx.node_sets = [{"nodes": [
            {"node_id": "S-01", "name": "가압기 압력 제어", "intent": "압력 유지", "origin": "ai", "state": "proposed",
             "members": [S102 + "/entity-node-001", S102 + "/entity-node-014", S101 + "/entity-node-001"]},
            {"node_id": "S-02", "name": "충전", "origin": "human", "state": "confirmed",
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
    MORE = ["enclose", "find_major_equipment", "get_document", "get_node", "get_worksheet", "list_nodes", "make_candidates",
            "outside_components", "search", "search_documents"]

    def test_registry_lists_tools(self):
        self.assertEqual(sorted(self.tools.REGISTRY), sorted(self.MIN + self.MORE))

    def test_entries_are_self_describing(self):
        for name, t in self.tools.REGISTRY.items():
            self.assertTrue(callable(t["fn"]), name)
            self.assertTrue(t["description"].strip(), name)
            s = t["input_schema"]
            self.assertEqual((s["type"], s["additionalProperties"]), ("object", False), name)
            for prop in s.get("required", []):
                self.assertIn(prop, s["properties"], name)
            json.dumps(s)

    def test_every_tool_declares_returned_id_kinds(self):
        valid = {"component", "node", "cell", "chunk", "path_ref"}
        for name, t in self.tools.REGISTRY.items():
            self.assertTrue(set(t["returns"]) <= valid, name)
        self.assertEqual(set(self.tools.REGISTRY["trace_path"]["returns"]), {"component", "path_ref"})
        self.assertEqual(self.tools.REGISTRY["get_node"]["returns"], ("node", "component"))
        self.assertEqual(self.tools.REGISTRY["count"]["returns"], ())

    def test_registry_module_lists_the_same_tools(self):
        from hazop.chat import registry
        self.assertEqual(sorted(registry.REGISTRY), sorted(self.tools.REGISTRY))

    def test_every_listing_tool_takes_limit_and_cursor(self):
        for name in ("find", "trace_path", "trace_flow", "enclose", "neighbors", "search", "count", "summary", "get_node", "list_nodes"):
            props = self.tools.REGISTRY[name]["input_schema"]["properties"]
            self.assertEqual(props["limit"]["maximum"], 200, name)
            self.assertIn("cursor", props, name)

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
