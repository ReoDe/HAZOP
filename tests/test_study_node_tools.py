"""AI가 쓰는 구간 도구와 구간 명령(검토구간 규격 rev 2 N3, 채팅 규격 §3.2·§4.5) 시험. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
그래프는 저장소의 SNP 표본 도면 6장(drawio)으로 만든 프로젝트 그래프이고, 원인 참조는 앱이 쓰는 안정 참조 형식이다.
실행: python -m unittest tests.test_study_node_tools
"""

import copy
import glob
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.graph import build, project  # noqa: E402
from hazop.study import node_commands as cmd  # noqa: E402
from hazop.study import node_tools as nt  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from hazop.study import segment  # noqa: E402

AT = "2026-11-13T00:00:00Z"
DEVS = [{"deviation_id": "D01", "item_id": "I1", "parameter": "유량", "guideword": "없음", "label": "유량 없음"}]
_PG = {}


def snp_graph():
    """SNP 표본 6장의 프로젝트 그래프(모듈 안에서 한 번만 만든다)."""
    if "pg" not in _PG:
        import extract_drawio
        tmp = tempfile.mkdtemp(prefix="hazop-snp-")
        try:
            with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": tmp}):
                graphs = []
                for p in sorted(glob.glob(extract_drawio.SAMPLE_GLOB)):
                    ex, _ = extract_drawio.run_one(p, os.path.join(tmp, "x"))
                    graphs.append(build.build_graph(ex))
                _PG["pg"] = project.build("SNP", graphs)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return copy.deepcopy(_PG["pg"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-node-tools-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
        nt.clear_cache()
        self.pg = snp_graph()
        self.ns = sn.new_set(self.pg)

    def ai(self, ns, ops, rid, turn, rest=False, doc=None):
        return nt.apply_nodes(ns, doc if doc is not None else res.empty_results(ns, DEVS), self.pg, ops,
                              {"request_id": rid, "user_turn": turn, "confirmed_rest": rest, "request_text": "구간 나눠 줘",
                               "confirmed_by": "검토자" if rest else None},
                              "ai", ns["set_rev"], at=AT)

    def adds(self, cands, n):
        return [{"op": "add", "cand_id": c["cand_id"], "name": "후보 %d" % i, "design_intent": "흐름을 보냄"}
                for i, c in enumerate(cands[:n])]


class ReadToolTest(Base):
    def test_1_normal_candidates_follow_rev0_plus_turbine_boundary(self):
        legacy = [s for s in segment.cut(self.pg) if isinstance(s, segment.Kept)]
        out = nt.make_candidates(self.pg, self.ns, granularity="normal", skip_existing=False, limit=200)
        turbines = [n for n in self.pg["nodes"] if n.get("kind") in ("turbine", "compressor")]
        self.assertEqual(len(legacy), 29, "rev 0 S1 남긴 구간 수")
        self.assertEqual(out["total"], len(legacy) + len(turbines), "보통 = 용기류 + 터빈·압축기 경계(V-6)")

    def test_2_granularity_changes_count_and_size(self):
        size = {}
        for g in ("coarse", "normal", "fine"):
            out = nt.make_candidates(self.pg, self.ns, granularity=g, skip_existing=False, limit=200)
            size[g] = (out["total"], max(c["member_count"] for c in out["candidates"]))
        self.assertLess(size["coarse"][0], size["normal"][0])
        self.assertLess(size["normal"][0], size["fine"][0])
        self.assertLessEqual(size["fine"][1], segment.GRANULARITY["fine"][1])
        with self.assertRaises(ValueError):
            nt.make_candidates(self.pg, self.ns, granularity="huge")

    def test_3_same_input_same_cand_id_and_paging(self):
        a = nt.make_candidates(self.pg, self.ns, limit=10)
        nt.clear_cache()
        b = nt.make_candidates(self.pg, self.ns, limit=10)
        self.assertEqual([c["cand_id"] for c in a["candidates"]], [c["cand_id"] for c in b["candidates"]])
        self.assertTrue(a["next_cursor"])
        nxt = nt.make_candidates(self.pg, self.ns, limit=10, cursor=a["next_cursor"])
        self.assertFalse({c["cand_id"] for c in a["candidates"]} & {c["cand_id"] for c in nxt["candidates"]})
        self.assertEqual(len(nt.make_candidates(self.pg, self.ns, limit=999)["candidates"]), nt.CANDIDATE_LIMIT)
        c = a["candidates"][0]
        self.assertEqual(set(c), {"cand_id", "member_count", "start", "end", "majors", "valves", "instruments",
                                  "drawings", "grade", "score", "overlaps", "basis"})
        self.assertEqual((a["set_rev"], a["params_digest"]), (self.ns["set_rev"], b["params_digest"]))

    def test_major_equipment_scope_and_outside(self):
        out = nt.find_major_equipment(self.pg, granularity="normal")
        kinds = {i["kind"] for i in out["items"]}
        self.assertIn("turbine", kinds)
        self.assertNotIn("pump", kinds)
        fine = nt.find_major_equipment(self.pg, granularity="fine")
        self.assertIn("pump", {i["kind"] for i in fine["items"]})
        drawing = self.pg["sheets"][0]["drawing_number"]
        one = nt.find_major_equipment(self.pg, scope={"drawings": [drawing]})
        self.assertTrue(one["items"] and all(i["drawing"] == drawing for i in one["items"]))
        cands = nt.make_candidates(self.pg, self.ns, scope={"drawings": [drawing]}, limit=200)
        self.assertTrue(all(c["drawings"] == [drawing] for c in cands["candidates"]))
        outside = nt.outside_components(self.pg, self.ns, only_sources=True, limit=500)
        self.assertEqual(outside["count"], sum(1 for n in self.pg["nodes"] if segment.is_source(n)))
        with self.assertRaises(ValueError):
            nt.make_candidates(self.pg, self.ns, scope={"planet": "x"})

    def test_existing_nodes_are_skipped_and_overlaps_reported(self):
        first = nt.make_candidates(self.pg, self.ns, limit=5)["candidates"]
        ns, _r, _b = self.ai(self.ns, self.adds(first, 1), "q-1", "u-1")
        again = nt.make_candidates(self.pg, ns, skip_existing=True, limit=200)
        self.assertNotIn(first[0]["cand_id"], [c["cand_id"] for c in again["candidates"]])
        every = nt.make_candidates(self.pg, ns, skip_existing=False, limit=200)
        hit = next(c for c in every["candidates"] if c["cand_id"] == first[0]["cand_id"])
        self.assertEqual(hit["overlaps"], [{"node_id": "S1", "shared": first[0]["member_count"]}])

    def test_9_unrecognized_equipment_is_counted(self):
        pg = snp_graph()
        for n in pg["nodes"]:
            if n.get("kind") == "tank":
                n["kind"] = "mystery_box"
        out = nt.find_major_equipment(pg)
        self.assertGreaterEqual(out["unrecognized_equipment"], 4)

    def test_10_legend_sheet_gives_no_candidates(self):
        sheet = self.pg["sheets"][0]
        with mock.patch.object(sn, "exclusion_for", lambda pg: (frozenset({sheet["graph_id"]}), None)):
            out = nt.make_candidates(self.pg, self.ns, limit=200)
        self.assertFalse(any(sheet["drawing_number"] in c["drawings"] and len(c["drawings"]) == 1
                             for c in out["candidates"]))


class ApplyTest(Base):
    def setUp(self):
        super().setUp()
        self.cands = nt.make_candidates(self.pg, self.ns, limit=30)["candidates"]

    def test_representative_then_rest_after_a_new_message_then_undo_only_that_request(self):
        ns, _r, b1 = self.ai(self.ns, self.adds(self.cands, 4), "q-1", "u-1")
        made = [n for n in ns["nodes"] if n["batch_id"] == b1]
        self.assertEqual(len(made), 4)
        self.assertTrue(all(n["origin"] == "ai" and n["state"] == "applied" for n in made))
        self.assertEqual(made[0]["design_intent"], {"text": "흐름을 보냄", "by": "ai"})
        self.assertEqual(nt.pending_ai(ns), 4)
        with self.assertRaises(nt.Refused):  # 같은 메시지 안에서 나머지로 넘어가지 못함(나누기로 상한 피하기 막음)
            self.ai(ns, self.adds(self.cands[4:], 2), "q-2", "u-1", rest=True)
        with self.assertRaises(nt.Refused):  # 새 메시지라도 사람이 확인 상자를 누르지 않았으면 거절
            self.ai(ns, self.adds(self.cands[4:], 2), "q-2", "u-2")
        human = sn.set_design_intent(ns, made[0]["node_id"], "사람이 고친 설계 의도", at=AT)
        self.assertEqual(sn._find(human, made[0]["node_id"])["design_intent"]["by"], "user")
        self.assertEqual(nt.pending_ai(human), 3, "사람이 손댄 구간은 확인한 것으로 셈")
        rest, _r, b2 = self.ai(human, self.adds(self.cands[4:], 20), "q-3", "u-2", rest=True)
        self.assertEqual(nt.pending_ai(rest), 20, "확인 상자를 누르면 앞 묶음은 확인됨")
        with self.assertRaises(nt.Refused):
            self.ai(rest, self.adds(self.cands[24:], 1), "q-3", "u-3", rest=True)  # 요청 하나 = 묶음 하나
        undone, _d = nt.undo_batch(rest, res.empty_results(rest, DEVS), b2, rest["set_rev"], "AI", "ai", at=AT)
        self.assertEqual(len(undone["nodes"]), 4)
        self.assertEqual(sn._find(undone, made[0]["node_id"])["design_intent"]["text"], "사람이 고친 설계 의도")

    def test_8_more_than_five_at_once_and_more_than_thirty_are_refused(self):
        with self.assertRaises(nt.Refused):
            self.ai(self.ns, self.adds(self.cands, 6), "q-1", "u-1")
        with self.assertRaises(nt.Refused):
            more = nt.make_candidates(self.pg, self.ns, granularity="fine", limit=30)["candidates"]
            more += nt.make_candidates(self.pg, self.ns, granularity="fine", limit=30, cursor="30")["candidates"]
            self.ai(self.ns, self.adds(more, 31), "q-1", "u-1", rest=True)

    def test_4_old_cand_id_after_graph_change_is_refused(self):
        changed = copy.deepcopy(self.pg)
        changed["graph_version"] = "v-other"
        with self.assertRaises(nt.Refused) as why:
            nt.apply_nodes(self.ns, res.empty_results(self.ns, DEVS), changed, self.adds(self.cands, 1),
                           {"request_id": "q", "user_turn": "u"}, "ai", self.ns["set_rev"], at=AT)
        self.assertIn("후보", str(why.exception))

    def test_5_6_7_unknown_members_tags_states_and_set_rev(self):
        with self.assertRaises(nt.Refused):
            self.ai(self.ns, [{"op": "add", "members": ["graph-X/없는"], "name": "x"}], "q", "u")
        with self.assertRaises(nt.Refused):
            self.ai(self.ns, [{"op": "add", "cand_id": self.cands[0]["cand_id"], "name": "ZZ-999 펌프"}], "q", "u")
        ns, _r, _b = self.ai(self.ns, self.adds(self.cands, 1), "q-1", "u-1")
        conf = sn.confirm_nodes(ns, self.pg, ["S1"], "검토자", at=AT)
        with self.assertRaises(nt.Refused):
            self.ai(conf, [{"op": "edit", "node_id": "S1", "name": "바꿈"}], "q-2", "u-2")
        with self.assertRaises(nt.Refused):
            nt.apply_nodes(ns, res.empty_results(ns, DEVS), self.pg, self.adds(self.cands[1:], 1),
                           {"request_id": "q-3", "user_turn": "u-3"}, "ai", ns["set_rev"] - 1, at=AT)

    def test_12_batch_carries_request_and_turn(self):
        ns, _r, bid = self.ai(self.ns, self.adds(self.cands, 2), "q-20261113-1", "u-7")
        b = next(x for x in ns["batches"] if x["batch_id"] == bid)
        self.assertEqual((b["request_id"], b["user_turn"], b["origin"], b["kind"]), ("q-20261113-1", "u-7", "ai", "apply"))
        self.assertEqual([o["op"] for o in b["ops"]], ["add", "add"])


class CommandTest(Base):
    """구간 명령(node_commands.execute): 파일을 읽어 실행하고 결과·집합을 지문 대조로 저장한다."""

    def run_cmd(self, name, args, author="user", confirmed_by="검토자", set_rev="now", request=None):
        rev = (sn.load(self.pg) or self.ns)["set_rev"] if set_rev == "now" else set_rev
        return cmd.execute(self.pg, name, args, author=author, confirmed_by=confirmed_by, set_rev=rev, request=request)

    def test_commands_round_trip_on_disk(self):
        cands = nt.make_candidates(self.pg, self.ns, limit=5)["candidates"]
        out = self.run_cmd("create", {"items": [{"cand_id": cands[0]["cand_id"], "name": "가압기 계통"}]}, set_rev=None)
        self.assertTrue(out["ok"], out)
        nid = out["node_ids"][0]
        self.assertEqual(sn.load(self.pg)["nodes"][0]["origin"], "user")
        stale = self.run_cmd("rename", {"node_id": nid, "name": "다른 이름"}, set_rev=0)
        self.assertEqual((stale["ok"], stale["refused"][0]["code"]), (False, "stale"))
        for name, args in (("rename", {"node_id": nid, "name": "새 이름"}),
                           ("set_design_intent", {"node_id": nid, "text": "가압기 압력 유지"}),
                           ("confirm", {"node_ids": [nid]}), ("unconfirm", {"node_ids": [nid]})):
            out = self.run_cmd(name, args)
            self.assertTrue(out["ok"], (name, out))
        node = sn.load(self.pg)["nodes"][0]
        self.assertEqual((node["name"], node["design_intent"]["by"], node["state"]), ("새 이름", "user", "applied"))
        undo = self.run_cmd("undo", {"batch_id": out_batch(self.pg, "set_design_intent")})
        self.assertTrue(undo["ok"], undo)
        lock = self.run_cmd("lock", {"node_ids": [nid]})
        self.assertEqual((lock["ok"], lock["refused"][0]["code"]), (False, "rule"))
        self.assertEqual(sorted(cmd.COMMANDS), sorted(["create", "add_members", "remove_members", "rename",
                                                       "set_design_intent", "merge", "split", "remove", "confirm",
                                                       "unconfirm", "lock", "unlock", "undo"]))
        self.assertEqual(self.run_cmd("explode", {})["refused"][0]["code"], "unknown_command")
        with self.assertRaises(TypeError):
            cmd.execute(self.pg, "rename", {"node_id": nid, "name": "x"}, confirmed_by="검토자")  # author 기본값 없음
        self.assertEqual(self.run_cmd("rename", {"node_id": nid, "name": "x"}, author="robot")["refused"][0]["code"],
                         "bad_actor")
        self.assertEqual(self.run_cmd("rename", {"node_id": nid, "name": "x"}, confirmed_by=None)["refused"][0]["code"],
                         "bad_actor")
        self.assertEqual(self.run_cmd("confirm", {"node_ids": [nid]}, author="ai")["refused"][0]["code"], "bad_actor")

    def make_judged_pair(self):
        """사람이 확정했다가 해제한 S1·S2. S2 칸에 사람 승인 항목."""
        cands = nt.make_candidates(self.pg, self.ns, limit=5)["candidates"]
        self.assertTrue(self.run_cmd("create", {"items": [{"cand_id": cands[0]["cand_id"], "name": "A"},
                                                          {"cand_id": cands[1]["cand_id"], "name": "B"}]})["ok"])
        self.assertTrue(self.run_cmd("confirm", {"node_ids": ["S1", "S2"]})["ok"])
        ns, _fp = sn.load_fp(self.pg)
        doc, rfp = res.load_fp(ns)
        doc = doc or res.empty_results(ns, DEVS)
        next(c for c in doc["cells"] if c["node_id"] == "S2").update(state="analyzed", entries=[
            {"entry_id": "e1", "origin": "human", "status": "approved", "cause": "c", "consequence": "q", "safeguards": []}])
        res.save_fp(doc, ns.get("project_id"), expect=rfp)
        self.assertTrue(self.run_cmd("unconfirm", {"node_ids": ["S1", "S2"]})["ok"])

    def raw_entries(self):
        ns = sn.load(self.pg)
        raw = res.read(res.store_path(ns.get("project_id"), ns["graph_id"]))
        return {c["node_id"]: [e["entry_id"] for e in c["entries"]] for c in raw["cells"] if c["entries"]}

    def test_r1_set_conflict_leaves_results_untouched(self):
        self.make_judged_pair()
        real = sn.load_fp

        def racing(graph):
            got = real(graph)
            sn.save_fp(sn.rename(got[0], "S1", "다른 창"), expect=got[1])
            return got
        with mock.patch.object(cmd.nodes, "load_fp", racing):
            out = self.run_cmd("merge", {"node_ids": ["S1", "S2"]}, set_rev=None)
        self.assertEqual((out["ok"], out["refused"][0]["code"]), (False, "conflict"))
        self.assertEqual([n["node_id"] for n in sn.load(self.pg)["nodes"]], ["S1", "S2"])
        self.assertEqual(self.raw_entries(), {"S2": ["e1"]}, "결과 파일은 그대로(항목이 다른 구간에 붙지 않음)")

    def test_r1_crash_between_writes_is_recovered(self):
        self.make_judged_pair()
        with mock.patch.object(cmd.res, "save_fp", side_effect=OSError("꺼짐")):
            out = self.run_cmd("merge", {"node_ids": ["S1", "S2"]})
        self.assertFalse(out["ok"])
        self.assertEqual([n["node_id"] for n in sn.load(self.pg)["nodes"]], ["S1"], "집합은 이미 씀")
        self.assertEqual(self.raw_entries(), {"S2": ["e1"]}, "결과는 아직")
        self.assertTrue(cmd.recover(self.pg))
        self.assertEqual(self.raw_entries(), {"S1": ["e1"]}, "다음에 열 때 마저 씀")
        self.assertFalse(cmd.recover(self.pg), "두 번 쓰지 않음")

    def test_r6_ai_authored_stays_ai_even_when_a_person_confirms(self):
        cands = nt.make_candidates(self.pg, self.ns, limit=30)["candidates"]
        self.assertTrue(self.run_cmd("create", {"items": [{"cand_id": cands[0]["cand_id"], "name": "사람 구간"}]})["ok"])
        items = [{"cand_id": c["cand_id"], "name": "AI %d" % i} for i, c in enumerate(cands[1:6])]
        req = {"request_id": "q-1", "user_turn": "u-1"}
        refused = self.run_cmd("rename", {"node_id": "S1", "name": "AI가 바꿈"}, author="ai", confirmed_by=None,
                               request=dict(req, request_id="q-0"))
        self.assertFalse(refused["ok"], "사람 구간을 AI가 바꾸려면 사람 확인이 필요")
        ok = self.run_cmd("rename", {"node_id": "S1", "name": "AI가 바꿈"}, author="ai", confirmed_by="검토자",
                          request=dict(req, request_id="q-00"))
        self.assertTrue(ok["ok"], ok)
        made = self.run_cmd("create", {"items": items}, author="ai", confirmed_by="검토자", request=req)
        self.assertTrue(made["ok"], made)
        ns = sn.load(self.pg)
        self.assertEqual({(n["origin"], n["name_by"]) for n in ns["nodes"] if n["node_id"] in made["node_ids"]},
                         {("ai", "ai")})
        self.assertEqual(nt.pending_ai(ns), 5, "사람이 확인 상자를 눌러도 AI 상한에 셈")
        more = self.run_cmd("create", {"items": [{"cand_id": cands[7]["cand_id"], "name": "AI 6"}]}, author="ai",
                            confirmed_by="검토자", request={"request_id": "q-2", "user_turn": "u-1", "confirmed_rest": True})
        self.assertFalse(more["ok"], "같은 질문 안에서 6번째는 거절")

    def test_r5_ai_cannot_undo_a_batch_a_person_confirmed(self):
        cands = nt.make_candidates(self.pg, self.ns, limit=5)["candidates"]
        made = self.run_cmd("create", {"items": [{"cand_id": cands[0]["cand_id"], "name": "AI"}]}, author="ai",
                            confirmed_by=None, request={"request_id": "q-5", "user_turn": "u-5"})
        nid = made["node_ids"][0]
        self.assertTrue(self.run_cmd("confirm", {"node_ids": [nid]})["ok"])
        self.assertTrue(self.run_cmd("unconfirm", {"node_ids": [nid]})["ok"])
        undo = self.run_cmd("undo", {"batch_id": made["batch_id"]}, author="ai", confirmed_by=None)
        self.assertFalse(undo["ok"])
        self.assertIn("확정한 적", undo["refused"][0]["reason"])

    def test_hops_have_a_cap(self):
        start = self.pg["nodes"][0]["entity_id"]
        with self.assertRaises(ValueError):
            nt.scope_ids(self.pg, None, {"around": start, "hops": 2000000})
        self.assertIn(start, nt.scope_ids(self.pg, None, {"around": start, "hops": nt.MAX_HOPS}))


class NoChangeTest(Base):
    """바뀐 것이 없는 편집은 묶음·판·이력을 건드리지 않고 묶음 ID 없이 돌려준다(새 화면 2단계 검토 재현)."""

    def test_no_op_edits_return_no_batch(self):
        cands = nt.make_candidates(self.pg, self.ns, limit=5)["candidates"]
        ns, doc, b1 = nt.apply_nodes(self.ns, res.empty_results(self.ns, DEVS), self.pg,
                                     [{"op": "add", "cand_id": cands[0]["cand_id"], "name": "가압기"},
                                      {"op": "add", "cand_id": cands[1]["cand_id"], "name": "충전"}], {}, "user",
                                     self.ns["set_rev"], at=AT)
        other = cands[1]
        outside = [m for m in nt.resolve_candidate(self.pg, None, other["cand_id"])["members"]]
        for ops in ([{"op": "edit", "node_id": "S1", "remove": outside}],
                    [{"op": "edit", "node_id": "S1", "name": "가압기 "}],
                    [{"op": "edit", "node_id": "S1", "design_intent": ""}]):
            with self.subTest(ops):
                same, same_doc, bid = nt.apply_nodes(ns, doc, self.pg, ops, {}, "user", ns["set_rev"], at=AT)
                self.assertEqual((same is ns, same_doc is doc, bid), (True, True, None))
        bare = dict(ns, batches=[])  # 묶음이 하나도 없음(0.1에서 바꾼 집합, 묶음을 다 줄인 집합)
        self.assertIsNone(nt.apply_nodes(bare, doc, self.pg, [{"op": "edit", "node_id": "S1", "name": "가압기"}], {},
                                         "user", bare["set_rev"], at=AT)[2])
        renamed, _d, b2 = nt.apply_nodes(bare, doc, self.pg, [{"op": "edit", "node_id": "S1", "name": "새"}], {}, "user",
                                         bare["set_rev"], at=AT)
        self.assertEqual((b2, renamed["batches"][-1]["batch_id"]), ("B2", "B2"), "묶음 번호는 batch_seq로 이어짐")

    def test_no_op_command_writes_nothing(self):
        cands = nt.make_candidates(self.pg, self.ns, limit=5)["candidates"]
        made = cmd.execute(self.pg, "create", {"items": [{"cand_id": cands[0]["cand_id"], "name": "가압기"}]},
                           author="user", confirmed_by="검토자")
        path = sn.store_path(self.pg.get("project_id"), self.pg["graph_id"])
        with open(path, "rb") as fh:
            before = fh.read()
        out = cmd.execute(self.pg, "rename", {"node_id": made["node_ids"][0], "name": "가압기"}, author="user",
                          confirmed_by="검토자", set_rev=made["set_rev"])
        self.assertEqual((out["ok"], out["changed"], out["batch_id"], out["set_rev"]), (True, False, None, made["set_rev"]))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)


class CrossProcessTest(Base):
    def test_r3_cand_id_made_in_another_process_applies_here(self):
        import subprocess
        code = ("import os, sys, json; sys.path.insert(0, %r); sys.path.insert(0, %r);\n"
                "from tests.test_study_node_tools import snp_graph;\n"
                "from hazop.study import node_tools as nt, nodes as sn;\n"
                "pg = snp_graph(); out = nt.make_candidates(pg, sn.new_set(pg), limit=3);\n"
                "print(json.dumps([c['cand_id'] for c in out['candidates']]))"
                % (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")))
        env = dict(os.environ, HAZOP_WORK_ROOT=self.tmp, PYTHONIOENCODING="utf-8")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, cwd=REPO_ROOT)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        import json
        ids = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
        nt.clear_cache()
        ns, _r, _b = nt.apply_nodes(self.ns, res.empty_results(self.ns, DEVS), self.pg,
                                    [{"op": "add", "cand_id": ids[0], "name": "다른 프로세스 후보"}],
                                    {"request_id": "q", "user_turn": "u"}, "ai", self.ns["set_rev"], at=AT)
        self.assertEqual(ns["nodes"][0]["cand_id"], ids[0])
        nt.clear_cache()
        with mock.patch.object(nt.time, "time", lambda: 10 ** 11):  # 기록이 지나면 다시 찾게 함
            with self.assertRaises(nt.Refused):
                nt.apply_nodes(self.ns, res.empty_results(self.ns, DEVS), self.pg,
                               [{"op": "add", "cand_id": ids[1], "name": "지난 후보"}],
                               {"request_id": "q2", "user_turn": "u"}, "ai", self.ns["set_rev"], at=AT)


class OldScreenPathTest(unittest.TestCase):
    """옛 화면의 '다시 제안' 길(reapply·take_out·detach)이 0.2 저장 API와 어긋나지 않는다: 묶음의 after가 저장된 구간과
    같아 undo_batch로 되돌릴 수 있고, 새 구간은 0.2 필드를 갖는다."""

    def test_take_out_and_detach_record_undoable_batches(self):
        from tests.test_study_segment import ScreenRecordTest
        case = ScreenRecordTest("test_people_can_override_take_out_and_detach")
        case.setUp()
        ns = case.ns
        bucket = next(n for n in ns["nodes"] if n["screen"]["status"] == "excluded")
        keep = next(n for n in ns["nodes"] if n.get("absorbed"))
        for after in (sn.take_out(ns, bucket["node_id"], []),
                      sn.detach(ns, keep["node_id"], keep["absorbed"][0]["members"][:1])):
            b = after["batches"][-1]
            for o in b["ops"]:
                if o["after"] is not None:
                    self.assertEqual(o["after"], sn._find(after, o["node_id"]))
            self.assertTrue(all(n.get("state") == "applied" and n.get("rev") for n in after["nodes"]))
            undone, _d = nt.undo_batch(after, res.empty_results(after, DEVS), b["batch_id"], after["set_rev"], "검토자",
                                       "user", at=AT)
            shape = lambda s: [(n["node_id"], n["members"]) for n in s["nodes"]]  # noqa: E731
            self.assertEqual(shape(undone), shape(ns))
        again, dropped = sn.reapply(ns, sn.propose(case.graph, at=AT))
        self.assertEqual((dropped, again["schema_version"]), ([], sn.SCHEMA_VERSION))


def out_batch(pg, kind):
    return next(b["batch_id"] for b in reversed(sn.load(pg)["batches"]) if b["kind"] in (kind, "apply"))


if __name__ == "__main__":
    unittest.main()
