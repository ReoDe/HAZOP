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
                              {"request_id": rid, "user_turn": turn, "confirmed_rest": rest, "request_text": "구간 나눠 줘"},
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

    def test_commands_round_trip_on_disk(self):
        cands = nt.make_candidates(self.pg, self.ns, limit=5)["candidates"]
        out = cmd.execute(self.pg, "create", {"items": [{"cand_id": cands[0]["cand_id"], "name": "가압기 계통"}]},
                          by="검토자", set_rev=None)
        self.assertTrue(out["ok"], out)
        nid = out["node_ids"][0]
        self.assertEqual(sn.load(self.pg)["nodes"][0]["origin"], "user")
        stale = cmd.execute(self.pg, "rename", {"node_id": nid, "name": "다른 이름"}, by="검토자", set_rev=0)
        self.assertEqual((stale["ok"], stale["refused"][0]["reason"][:5]), (False, "구간이 그"))
        for name, args in (("rename", {"node_id": nid, "name": "새 이름"}),
                           ("set_design_intent", {"node_id": nid, "text": "가압기 압력 유지"}),
                           ("confirm", {"node_ids": [nid]}), ("unconfirm", {"node_id": nid})):
            out = cmd.execute(self.pg, name, args, by="검토자", set_rev=sn.load(self.pg)["set_rev"])
            self.assertTrue(out["ok"], (name, out))
        node = sn.load(self.pg)["nodes"][0]
        self.assertEqual((node["name"], node["design_intent"]["by"], node["state"]), ("새 이름", "user", "applied"))
        undo = cmd.execute(self.pg, "undo", {"batch_id": out_batch(self.pg, "set_design_intent")}, by="검토자",
                           set_rev=sn.load(self.pg)["set_rev"])
        self.assertTrue(undo["ok"], undo)
        lock = cmd.execute(self.pg, "lock", {"node_id": nid}, by="검토자", set_rev=sn.load(self.pg)["set_rev"])
        self.assertFalse(lock["ok"])
        self.assertEqual(sorted(cmd.COMMANDS), sorted(["create", "add_members", "remove_members", "rename",
                                                       "set_design_intent", "merge", "split", "remove", "confirm",
                                                       "unconfirm", "lock", "unlock", "undo"]))
        bad = cmd.execute(self.pg, "explode", {}, by="검토자", set_rev=None)
        self.assertFalse(bad["ok"])


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
