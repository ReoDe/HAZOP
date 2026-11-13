"""채팅의 구간 읽기 도구(find_major_equipment·make_candidates·outside_components)와 get_node·list_nodes(단위 C1/N3 연결).
실행: python -m unittest tests.test_chat_tools_nodes

- 도구 결과를 규격(chat-panel §3.2)의 봉투로 확인하고, 구간 규격 v2의 실제 저장 결과(hazop.study.nodes로 저장·읽기)로
  get_node·list_nodes를 시험한다.
- "대표 구간 3개 먼저 만들어 줘" 흐름(경계 찾기 → 후보 만들기 → 제안 동작)을 가짜 CLI 없이 MCP 서버 직접 호출로 재현한다.
  제안 동작을 실행하는 쪽(앱)은 hazop.study.node_tools.apply_nodes로 흉내 낸다.
"""

import copy
import json
import os
import shutil
import tempfile
import unittest

from hazop.chat import context, mcp_server, registry, tools
from hazop.study import node_tools, nodes
from tests.test_chat_tools import S101, S102, ChatToolsBase

SCOPE = {"drawings": ["SNP-M-102"]}


class NodeToolsBase(ChatToolsBase):
    def setUp(self):
        node_tools.clear_cache()

    def with_sets(self, node_sets):
        c = copy.copy(self.ctx)
        c.node_sets = node_sets
        c._index = None
        c.cursors = {}
        return c


class ReadToolsTest(NodeToolsBase):
    def test_find_major_equipment(self):
        res = self.ok("find_major_equipment", scope=SCOPE)
        self.assertEqual([(i["tag"], i["kind"], i["drawing"]) for i in res["data"]["items"]], [("RC-PZ01", "pressurizer", "SNP-M-102")])
        self.assertEqual(res["data"]["granularity"], "normal")
        self.assertEqual(res["sources"], [{"kind": "drawing", "sheet": S102}])
        every = self.ok("find_major_equipment")["data"]["items"]
        self.assertGreater(len(every), 10)
        fine = self.ok("find_major_equipment", granularity="fine")["total"]
        coarse = self.ok("find_major_equipment", granularity="coarse")["total"]
        self.assertGreater(fine, coarse)   # 굵기가 가늘수록 경계가 늘어난다

    def test_make_candidates_shape_and_order(self):
        res = self.ok("make_candidates", limit=30)
        d = res["data"]
        self.assertEqual(d["granularity"], "normal")
        self.assertEqual(d["set_rev"], None)        # 구간이 아직 없는 프로젝트
        self.assertRegex(d["params_digest"], r"^[0-9a-f]{16}$")
        c = d["candidates"][0]
        self.assertRegex(c["cand_id"], r"^c-[0-9a-f]{16}$")
        self.assertEqual(set(c) - {"overlap_count"}, {"cand_id", "member_count", "start", "end", "majors", "valves", "instruments",
                                                      "drawings", "grade", "score", "overlaps", "basis"})
        grades = [x["grade"] for x in d["candidates"]]
        self.assertEqual(grades, sorted(grades, key=lambda g: {"주요": 0, "일반": 1, "낮음": 2, None: 3}[g]))   # 등급 순
        self.assertEqual(d["outside"]["count"], 259)
        self.assertEqual(self.ok("make_candidates")["data"]["params_digest"], d["params_digest"])   # 같은 입력이면 같다
        self.assertEqual([x["cand_id"] for x in self.ok("make_candidates")["data"]["candidates"]],
                         [x["cand_id"] for x in self.ok("make_candidates")["data"]["candidates"]])

    def test_make_candidates_scope_and_granularity_change_the_digest(self):
        base = self.ok("make_candidates")["data"]["params_digest"]
        self.assertNotEqual(base, self.ok("make_candidates", scope=SCOPE)["data"]["params_digest"])
        self.assertNotEqual(base, self.ok("make_candidates", granularity="fine")["data"]["params_digest"])
        near = self.ok("make_candidates", scope={"around": "RC-PZ01", "hops": 2})
        self.assertTrue(near["ok"])

    def test_candidates_page_without_loss_and_stay_small(self):
        full, cursor = [], None
        while True:
            res = self.ok("make_candidates", limit=3, **({"cursor": cursor} if cursor else {}))
            full += [c["cand_id"] for c in res["data"]["candidates"]]
            cursor = res["cursor"]
            if not cursor:
                break
        one = [c["cand_id"] for c in self.ok("make_candidates", limit=30)["data"]["candidates"]]
        self.assertEqual(full[:len(one)], one)
        self.assertEqual(len(full), len(set(full)))
        self.assertEqual(len(full), self.ok("make_candidates")["total"])

    def test_cursor_is_bound_to_the_arguments(self):
        cur = self.ok("make_candidates", limit=2)["cursor"]
        self.err("make_candidates", "bad_args", limit=2, granularity="fine", cursor=cur)
        self.err("make_candidates", "bad_args", limit=2, scope=SCOPE, cursor=cur)
        self.err("outside_components", "bad_args", cursor=cur)

    def test_skip_existing_removes_candidates_that_overlap_existing_nodes(self):
        first = self.ok("make_candidates", limit=30)["data"]["candidates"][0]
        members = node_tools.resolve_candidate(self.ctx.pg, {"nodes": []}, first["cand_id"])["members"]
        existing = [{"node_id": "S1", "name": "x", "state": "applied", "origin": "user", "members": members}]
        ctx = self.with_sets([{"set_rev": 3, "nodes": existing}])
        node_tools.clear_cache()
        res = self.call("make_candidates", ctx=ctx, limit=30)["data"]
        self.assertNotIn(first["cand_id"], [c["cand_id"] for c in res["candidates"]])
        self.assertEqual(res["set_rev"], 3)
        kept = self.call("make_candidates", ctx=ctx, skip_existing=False, limit=30)["data"]["candidates"]
        hit = next(c for c in kept if c["cand_id"] == first["cand_id"])
        self.assertEqual(hit["overlaps"][0]["node_id"], "S1")

    def test_outside_components(self):
        res = self.ok("outside_components", limit=5)
        self.assertEqual((res["data"]["count"], res["data"]["sources"], res["returned"]), (80, 80, 5))
        self.assertEqual(self.ok("outside_components", only_sources=False)["data"]["count"], 259)
        ctx = self.with_sets([{"set_rev": 1, "nodes": [{"node_id": "S1", "name": "a", "state": "applied", "origin": "ai",
                                                        "members": [S102 + "/entity-node-001"]}]}])
        left = self.call("outside_components", ctx=ctx, scope=SCOPE, limit=200)["data"]
        self.assertGreater(left["count"], 0)
        ids = {i["entity_id"] for i in left["items"]}
        self.assertNotIn(S102 + "/entity-node-001", ids)

    def test_arguments_are_checked(self):
        self.err("make_candidates", "bad_args", scope={"drawings": ["SNP-M-102"], "system": "RC"})
        self.err("make_candidates", "bad_args", scope={"hops": 2})
        self.err("make_candidates", "bad_args", scope={"colour": "red"})
        self.err("make_candidates", "bad_args", scope={"around": "../x"})
        self.err("make_candidates", "not_found", scope={"around": "NOPE-999"})
        self.err("make_candidates", "bad_args", granularity="huge")
        self.err("make_candidates", "bad_args", limit=31)
        self.err("make_candidates", "bad_args", extra_boundaries=["C:\\Windows"])
        self.err("make_candidates", "not_found", extra_boundaries=["NOPE-999"])
        self.err("find_major_equipment", "bad_args", path="C:/x")
        self.err("outside_components", "bad_args", scope={"node_ids": ["../S1"]})
        self.err("make_candidates", "bad_args", scope={"drawings": ["x"] * 21})

    def test_extra_boundaries_accept_tags_and_cut_the_path(self):
        base = self.ok("make_candidates", scope=SCOPE, limit=30)["data"]
        cut = self.ok("make_candidates", scope=SCOPE, cut_at=["RC-PV101"], limit=30)["data"]
        self.assertNotEqual(base["params_digest"], cut["params_digest"])

    def test_registry_lists_the_node_tools(self):
        for name in ("find_major_equipment", "make_candidates", "outside_components"):
            self.assertIn(name, registry.REGISTRY)
            props = registry.REGISTRY[name]["input_schema"]["properties"]
            self.assertIn("scope", props)
            self.assertEqual(registry.REGISTRY[name]["returns"], ("component",))
        props = registry.REGISTRY["make_candidates"]["input_schema"]["properties"]
        self.assertEqual(props["limit"]["maximum"], 30)
        for name in ("find_major_equipment", "outside_components"):
            self.assertEqual(registry.REGISTRY[name]["input_schema"]["properties"]["limit"]["maximum"], 200)


class ProcedureTextTest(unittest.TestCase):
    def test_procedure_is_in_tool_descriptions_and_exported(self):
        text = registry.NODE_CREATION_PROCEDURE
        for phrase in ("대표 구간 3~5개", "주요 장비에서 주요 장비까지", "이름", "설계 의도", "nodes.apply", "set_rev",
                       "새로 요청", "같은 답 안에서 이어 내지 않는다", "잠긴 구간", "확정 구간", "by=user", "outside_components"):
            self.assertIn(phrase, text)
        self.assertIn(text, registry.REGISTRY["make_candidates"]["description"])
        self.assertIn(text, registry.REGISTRY["find_major_equipment"]["description"])
        self.assertNotIn(text, registry.REGISTRY["find"]["description"])


class StoredNodeSetTest(NodeToolsBase):
    """구간 규격 v2의 실제 저장 파일(hazop.study.nodes.save → load)로 get_node·list_nodes를 시험한다."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pg = cls.ctx.pg
        node_tools.clear_cache()
        ns = nodes.new_set(pg)
        a = [S102 + "/entity-node-001", S102 + "/entity-node-003", S102 + "/entity-node-014"]
        b = [S102 + "/entity-node-014", S102 + "/entity-node-015", S102 + "/entity-node-013"]   # a와 entity-node-014를 같이 가짐
        c = [S101 + "/entity-node-001", S101 + "/entity-node-004"]
        d = [S101 + "/entity-node-002"]
        req = {"request_id": "q-20261113-152031-3f9a", "request_text": "대표 구간 만들어 줘", "stage": "representative"}
        ns, _res, batch = node_tools.apply_nodes(ns, None, pg, [
            {"op": "add", "members": a, "name": "가압기 압력 제어", "design_intent": "압력을 정상 범위에 유지", "basis": "가압기에서 안전밸브까지"},
            {"op": "add", "members": b, "name": "안전밸브 방출"}], req, "ai", ns["set_rev"])
        cls.batch_ai = batch
        ns, _res, cls.batch_user = node_tools.apply_nodes(ns, None, pg, [
            {"op": "add", "members": c, "name": "원자로 출구", "design_intent": "냉각재 송출"},
            {"op": "add", "members": d, "name": "증기발생기"}], {"request_id": "u-1"}, "user", ns["set_rev"], by="홍길동")
        ns = copy.deepcopy(ns)
        for n in ns["nodes"]:   # 확정·잠금 상태는 ④ 화면이 만든다: 같은 모양으로 직접 둔다(저장 검사를 거치게 파일로 쓴다)
            if n["name"] == "원자로 출구":
                n.update(state="confirmed", confirmed={"at": "2026-11-13T10:00:00Z", "by": "홍길동", "rev": n["rev"]})
            if n["name"] == "증기발생기":
                n.update(state="locked", locked={"at": "2026-11-13T11:00:00Z", "by": "홍길동", "reason": "분석 마침"},
                         confirmed={"at": "2026-11-13T10:00:00Z", "by": "홍길동", "rev": n["rev"]})
        cls.stored = ns
        cls.tmp_store = tempfile.mkdtemp(prefix="hazop-nodes-store-")
        cls._env_store = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp_store, "work")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        nodes.save(ns)
        cls.loaded = nodes.load(pg)
        cls.sctx = context.ChatContext(project_id="SNP-SAMPLE", pg=pg, node_sets=[cls.loaded], unknowns=cls.ctx.unknowns,
                                       unresolved=cls.ctx.unresolved)

    @classmethod
    def tearDownClass(cls):
        if cls._env_store is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = cls._env_store
        shutil.rmtree(cls.tmp_store, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.ctx = self.sctx

    def ids(self, **flt):
        return [n["node_id"] for n in self.ok("list_nodes", filter=flt)["data"]["items"]]

    def test_file_round_trip_keeps_v2_fields(self):
        self.assertEqual(self.loaded["schema_version"], "0.2")
        self.assertEqual(self.loaded["set_rev"], self.stored["set_rev"])
        self.assertEqual([n["node_id"] for n in self.loaded["nodes"]], ["S1", "S2", "S3", "S4"])

    def test_get_node_ai_applied(self):
        res = self.ok("get_node", node_id="S1")
        d = res["data"]
        self.assertEqual((d["state"], d["origin"], d["rev"], d["batch_id"]), ("applied", "ai", 1, self.batch_ai))
        self.assertEqual((d["design_intent"], d["design_intent_by"], d["name_by"]), ("압력을 정상 범위에 유지", "ai", "ai"))
        self.assertEqual((d["basis"], d["locked"], d["confirmed"]), ("가압기에서 안전밸브까지", None, None))
        self.assertEqual(d["set_rev"], self.loaded["set_rev"])
        self.assertEqual((d["member_count"], d["sheets"]), (3, [S102]))
        self.assertEqual(d["overlaps"], [{"node_id": "S2", "shared": 1}])   # entity-node-014를 S2와 같이 가진다
        self.assertEqual(d["overlap_count"], 1)
        self.assertEqual(d["members"][0]["tag"], "RC-PZ01")

    def test_get_node_without_intent_and_user_origin(self):
        d = self.ok("get_node", node_id="S2")["data"]
        self.assertEqual((d["design_intent"], d["design_intent_by"]), (None, None))
        u = self.ok("get_node", node_id="S3")["data"]
        self.assertEqual((u["origin"], u["state"], u["design_intent_by"], u["batch_id"]), ("user", "confirmed", "user", self.batch_user))
        self.assertEqual((u["confirmed"]["by"], u["confirmed"]["rev"]), ("홍길동", u["rev"]))

    def test_get_node_locked(self):
        d = self.ok("get_node", node_id="S4")["data"]
        self.assertEqual(d["state"], "locked")
        self.assertEqual((d["locked"]["by"], d["locked"]["reason"]), ("홍길동", "분석 마침"))

    def test_list_nodes_rows_and_filters(self):
        rows = {n["node_id"]: n for n in self.ok("list_nodes")["data"]["items"]}
        self.assertEqual({k: (v["state"], v["origin"], v["locked"]) for k, v in rows.items()},
                         {"S1": ("applied", "ai", False), "S2": ("applied", "ai", False),
                          "S3": ("confirmed", "user", False), "S4": ("locked", "user", True)})
        self.assertEqual(self.ids(state="applied"), ["S1", "S2"])
        self.assertEqual(self.ids(state="locked"), ["S4"])
        self.assertEqual(self.ids(origin="user"), ["S3", "S4"])
        self.assertEqual(self.ids(batch_id=self.batch_ai), ["S1", "S2"])
        self.assertEqual(self.ids(sheet=S101), ["S3", "S4"])
        self.assertEqual(self.ids(contains="안전밸브"), ["S2"])
        self.assertEqual(self.ok("list_nodes")["data"]["set_rev"], self.loaded["set_rev"])

    def test_nodes_appear_in_component_and_search(self):
        self.assertEqual(self.ok("get_component", id=S102 + "/entity-node-014")["data"]["nodes"], ["S1", "S2"])
        self.assertEqual(self.ok("search", filter={"in_node": "S1"})["total"], 3)

    def test_outside_components_counts_members_of_stored_nodes(self):
        out = self.ok("outside_components", only_sources=False)["data"]["count"]
        inside = {m for n in self.loaded["nodes"] for m in n["members"]}
        self.assertEqual(out, 259 - len(inside))


class RepresentativeFlowTest(NodeToolsBase):
    """'대표 구간 3개 먼저 만들어 줘' -> 경계 찾기 -> 후보 만들기 -> 제안 동작 -> (사람 확인 전) 나머지는 막힘."""

    def setUp(self):
        node_tools.clear_cache()
        self.state = {"set": nodes.new_set(self.ctx.pg)}
        self.qdir = tempfile.mkdtemp(prefix="hazop-nodes-q-")
        self.qfile = os.path.join(self.qdir, "question.json")
        self.n = 0
        self.server = mcp_server.Server(registry.REGISTRY, "SNP-SAMPLE", self.qfile, loader=lambda pid: self.current(),
                                        refresher=lambda ctx: self.current())
        self.question()

    def tearDown(self):
        shutil.rmtree(self.qdir, ignore_errors=True)

    def current(self):
        c = copy.copy(self.ctx)
        c.node_sets = [self.state["set"]]
        c._index = None
        c.cursors = getattr(self, "_cursors", {})
        self._cursors = c.cursors
        return c

    def question(self):
        self.n += 1
        with open(self.qfile, "w", encoding="utf-8") as fh:
            json.dump({"question_id": "q-%d" % self.n}, fh)

    def rpc(self, name, **args):
        rep = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        text = rep["result"]["content"][0]["text"]
        self.assertLessEqual(len(text), mcp_server.MAX_RESULT_CHARS)
        return json.loads(text.split("\n", 1)[1])

    def apply(self, ops, request_id, **extra):
        """앱이 제안 동작 nodes.apply를 실행하는 것(여기서는 apply_nodes를 직접 부른다). set_rev는 모델이 읽은 값."""
        ns, _res, batch = node_tools.apply_nodes(self.state["set"], None, self.ctx.pg, ops,
                                                 dict({"request_id": request_id, "request_text": "대표 구간 3개 먼저 만들어 줘",
                                                       "stage": "representative"}, **extra), "ai", self.state["set"]["set_rev"])
        self.state["set"] = ns
        return batch

    def test_three_representative_nodes(self):
        # 1) 경계가 되는 주요 장비
        eq = self.rpc("find_major_equipment")   # scope는 서버가 ID 인자로 취급해 객체를 거절한다(보고 참고). 범위 없이 부른다
        self.assertTrue(eq["ok"], eq["error"])
        self.assertIn("RC-PZ01", {i["tag"] for i in eq["data"]["items"]})
        # 2) 후보
        cand = self.rpc("make_candidates", limit=10)
        self.assertTrue(cand["ok"], cand["error"])
        set_rev = cand["data"]["set_rev"]
        picks = cand["data"]["candidates"][:3]
        self.assertEqual(len(picks), 3)
        self.assertTrue(all(p["grade"] == "주요" for p in picks))
        # 3) 제안 동작 -> 앱이 실행
        ops = [{"op": "add", "cand_id": p["cand_id"], "name": "구간 %d" % (i + 1), "design_intent": "초안 %d" % (i + 1),
                "basis": p["basis"]} for i, p in enumerate(picks)]
        action = {"action": "nodes.apply", "args": {"set_rev": set_rev, "graph_id": self.ctx.pg["graph_id"], "ops": ops},
                  "why": "대표 구간"}
        self.assertEqual(set(action["args"]["ops"][0]), {"op", "cand_id", "name", "design_intent", "basis"})
        batch = self.apply(ops, "q-20261113-100000-aaaa")
        self.assertRegex(batch, r"^B\d+$")
        self.question()
        # 4) 다시 읽으면 3개가 AI가 만든 적용됨 구간이고, 같은 후보는 빠지고, 구간 밖 수가 줄었다
        listed = self.rpc("list_nodes", filter={"origin": "ai"})
        self.assertEqual([(n["state"], n["origin"], n["batch_id"]) for n in listed["data"]["items"]], [("applied", "ai", batch)] * 3)
        again = self.rpc("make_candidates", limit=30)
        self.assertEqual(again["data"]["set_rev"], self.state["set"]["set_rev"])
        self.assertNotEqual(again["data"]["set_rev"], set_rev)
        self.assertTrue({p["cand_id"] for p in picks}.isdisjoint({c["cand_id"] for c in again["data"]["candidates"]}))
        self.assertLess(again["data"]["outside"]["count"], cand["data"]["outside"]["count"])
        node = self.rpc("get_node", node_id="S1")
        self.assertEqual((node["data"]["design_intent"], node["data"]["design_intent_by"]), ("초안 1", "ai"))

    def test_rest_needs_the_human_to_confirm_first(self):
        cand = self.rpc("make_candidates", limit=10)
        picks = cand["data"]["candidates"]
        first = [{"op": "add", "cand_id": p["cand_id"], "name": "구간 %d" % i} for i, p in enumerate(picks[:3])]
        self.apply(first, "q-1-aaaa")
        self.question()
        more = [{"op": "add", "cand_id": p["cand_id"], "name": "나머지 %d" % i} for i, p in enumerate(picks[3:6])]
        if len(more) < 3:
            self.skipTest("후보가 6개 미만")
        with self.assertRaises(node_tools.Refused) as cm:     # 사람이 확인하기 전에는 누적 5개를 넘길 수 없다
            self.apply(more, "q-2-bbbb")
        self.assertIn("확인", str(cm.exception))
        self.assertEqual(len(self.state["set"]["nodes"]), 3)

    def test_locked_and_confirmed_nodes_are_not_touched_by_ai_edits(self):
        picks = self.rpc("make_candidates", limit=3)["data"]["candidates"]
        self.apply([{"op": "add", "cand_id": picks[0]["cand_id"], "name": "구간 1"}], "q-1-aaaa")
        self.state["set"]["nodes"][0]["state"] = "confirmed"
        listed = self.rpc("list_nodes")["data"]["items"][0]
        self.assertEqual(listed["state"], "confirmed")     # 도구가 상태를 보여 주므로 모델이 건드리지 않을 수 있다
        with self.assertRaises(node_tools.Refused):
            self.apply([{"op": "edit", "node_id": "S1", "name": "바꿈"}], "q-3-cccc")


if __name__ == "__main__":
    unittest.main()
