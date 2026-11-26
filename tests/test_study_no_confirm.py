"""구간 '확정' 단계를 없앤 규칙(검토구간 규격 §0.2, 사용자 결정 2026-11-26) 시험. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
실행: python -m unittest tests.test_study_no_confirm

지키는 것: 만든 구간은 확정 없이 분석·결과·인계에 든다. 잠금이 아니면 바로 고친다. 구성요소가 바뀐 판정은 지우지 않고
'범위 바뀜'을 달아 사람이 다시 승인할 때까지 인계에서 뺀다. 더하기·빼기는 한 번에 저장한다. 사람이 승인한 항목만 인계에 든다.
"""

import copy
import itertools
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.chat import actions as chat_actions  # noqa: E402
from hazop.ie import bundle as ie_bundle  # noqa: E402
from hazop.ie import model as ie_model  # noqa: E402
from hazop.shell import api_results  # noqa: E402
from hazop.study import ai_cells, idmap, migrate  # noqa: E402
from hazop.study import node_commands as cmd  # noqa: E402
from hazop.study import node_tools as nt  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_migrate import AT, DEVS, OBJECTS, PIPES, graph  # noqa: E402

BY = "김검토"


def eid(g, soid):
    return next(n["entity_id"] for n in g["nodes"] if n["source_object_id"] == soid)


def entry(entry_id, status="approved", origin="human"):
    return {"entry_id": entry_id, "origin": origin, "status": status, "cause": "V1 닫힘 고착", "consequence": "유량 없음",
            "safeguards": [], "recommendation": None, "severity": None, "frequency": None, "risk": None}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-no-confirm-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
        self.g = graph("v1")

    def run_cmd(self, name, args, author="user", by=BY, request=None):
        ns = sn.load(self.g) or sn.new_set(self.g)
        return cmd.execute(self.g, name, args, author=author, confirmed_by=by,
                           set_rev=ns["set_rev"] if author == "ai" else None, request=request)

    def ids(self, *soids):
        return [eid(self.g, s) for s in soids]

    def make(self, name, *soids, author="user", by=BY, request=None):
        out = self.run_cmd("create", {"items": [{"members": self.ids(*soids), "name": name}]}, author=author, by=by,
                           request=request)
        self.assertTrue(out["ok"], out)
        return out["node_ids"][0]

    def loaded(self):
        ns = sn.load(self.g)
        doc, _fp = res.load_fp(ns)
        return ns, doc

    def put_entries(self, nid, entries, state="analyzed"):
        """칸 하나에 항목을 넣어 저장한다(화면·AI 분석이 쓴 것처럼)."""
        ns, doc = self.loaded()
        doc = doc or res.empty_results(ns, DEVS)
        cell = next(c for c in doc["cells"] if c["node_id"] == nid)
        cell.update(state=state, entries=entries)
        res.save(doc, ns.get("project_id"))

    def node(self, nid, ns=None):
        return next(n for n in (ns or sn.load(self.g))["nodes"] if n["node_id"] == nid)

    def handed(self, ns=None, doc=None):
        """인계 묶음에 드는 승인 항목 entry_id."""
        if ns is None:
            ns, doc = self.loaded()
        picked, _left = ie_bundle.approved_entries(doc, ns)
        return sorted(e["entry_id"] for _n, _d, e in picked)


class NewNodeIsActiveTest(Base):
    def test_new_node_enters_analysis_results_and_handover_without_confirm(self):
        nid = self.make("탱크 출구", "TK", "V1", "L1")
        ns = sn.load(self.g)
        node = self.node(nid, ns)
        self.assertEqual((node["state"], node["confirmed"]), ("applied", None), "확정을 부르지 않고 이름도 적지 않음")
        self.assertTrue(sn.is_active(node))
        self.assertEqual([u["node_id"] for u in ai_cells.plan_units(ns, DEVS)], [nid], "AI 분석 대상")
        self.assertEqual([n["node_id"] for n in api_results.scope_rows(ns)], [nid], "분석 결과 행")
        self.assertEqual([n["node_id"] for n in sn.active_nodes(ns)], [nid], "지식그래프 검토 층이 쓰는 목록")
        doc = res.reconcile(res.empty_results(ns, DEVS), ns, DEVS)
        self.assertEqual([(c["node_id"], c["hold"]) for c in doc["cells"]], [(nid, False)], "칸을 보관하지 않음")
        self.put_entries(nid, [entry("e1")])
        self.assertEqual(self.handed(), ["e1"], "초기사건 인계")
        ns, doc = self.loaded()
        facts = ie_model.entry_facts(doc, ns)
        self.assertEqual([(f["excluded"], f["held"], f["scope_changed"]) for f in facts.values()], [(False, False, False)],
                         "초기사건 화면의 근거")

    def test_old_applied_node_with_held_cells_comes_back_marked_when_its_scope_moved(self):
        """확정을 풀고 고친 뒤 저장된 옛 자료: 적용됨 구간, 칸은 보관(hold), 칸의 판보다 구간 rev가 높다."""
        nid = self.make("탱크 출구", "TK", "V1")
        ns = sn.load(self.g)
        doc = res.empty_results(ns, DEVS)
        doc["cells"][0].update(state="analyzed", hold=True, entries=[entry("e1")])
        node = self.node(nid, ns)
        node["rev"] = 3
        sn.save(ns)
        res.save(doc, ns.get("project_id"))
        ns, doc = self.loaded()
        cell = doc["cells"][0]
        self.assertFalse(cell["hold"])
        self.assertEqual(cell["entries"][0]["scope_changed"]["from_rev"], 1)
        self.assertEqual(self.handed(ns, doc), [], "범위가 바뀐 판정은 사람이 다시 볼 때까지 인계에 없음")


class EditTest(Base):
    def setUp(self):
        super().setUp()
        self.nid = self.make("탱크 출구", "TK", "V1", "L1")
        self.put_entries(self.nid, [entry("e1")])
        self.assertEqual(self.handed(), ["e1"])

    def test_member_change_keeps_the_verdict_marks_it_and_reapproval_brings_it_back(self):
        out = self.run_cmd("edit_members", {"node_id": self.nid, "add": self.ids("V2", "L2"), "remove": self.ids("L1")})
        self.assertTrue(out["ok"], out)
        ns, doc = self.loaded()
        self.assertEqual(sorted(self.node(self.nid, ns)["members"]), sorted(self.ids("TK", "V1", "V2", "L2")))
        e = doc["cells"][0]["entries"][0]
        self.assertEqual((e["entry_id"], e["status"]), ("e1", "approved"), "판정을 지우지 않고 같은 칸에 둠")
        self.assertEqual(e["scope_changed"]["to_rev"], self.node(self.nid, ns)["rev"])
        self.assertEqual(doc.get("archived_cells"), [], "보관 목록으로 가지 않음")
        self.assertEqual(self.handed(ns, doc), [], "'범위 바뀜' 승인은 인계에서 빠짐")
        facts = ie_model.entry_facts(doc, ns)
        self.assertTrue(all(f["scope_changed"] and not ie_model.is_evidence(f) for f in facts.values()), "그룹 확정 근거도 아님")
        again = res.load_fp(ns)[0]
        self.assertTrue(again["cells"][0]["entries"][0]["scope_changed"], "다시 읽어도 표시는 스스로 풀리지 않음")
        back = res.set_status(doc, self.nid, "D01", "e1", "approved", at=AT, node_set=ns, by=BY)
        res.save(back, ns.get("project_id"))
        self.assertEqual(self.handed(), ["e1"], "사람이 다시 승인하면 돌아옴")

    def test_add_and_remove_is_one_save(self):
        before = sn.load(self.g)
        out = self.run_cmd("edit_members", {"node_id": self.nid, "add": self.ids("V2"), "remove": self.ids("L1")})
        self.assertTrue(out["ok"], out)
        after = sn.load(self.g)
        self.assertEqual(after["batch_seq"], before["batch_seq"] + 1, "묶음 하나")
        self.assertEqual(after["set_rev"], before["set_rev"] + 1, "저장 한 번")
        b = after["batches"][-1]
        self.assertEqual([o["op"] for o in b["ops"]], ["edit"])
        self.assertEqual(self.node(self.nid, after)["rev"], self.node(self.nid, before)["rev"] + 1, "분석 판도 한 번만 오름")
        undone = self.run_cmd("undo", {"batch_id": out["batch_id"]})
        self.assertTrue(undone["ok"], undone)
        self.assertEqual(sorted(self.node(self.nid)["members"]), sorted(self.ids("TK", "V1", "L1")))

    def test_an_edit_records_the_content_digest_so_a_redraw_can_tell_what_changed(self):
        self.assertTrue(self.run_cmd("edit_members", {"node_id": self.nid, "add": self.ids("V2")})["ok"])
        ns = sn.load(self.g)
        self.assertEqual(ns["member_digest"][self.nid], migrate.node_digest(self.g, self.node(self.nid, ns)["members"]),
                         "고친 그때 지문을 셈(확정 때 세던 것)")
        path = sn.store_path(None, self.g["graph_id"])
        with open(path, "rb") as fh:
            raw = fh.read()
        sn.load(self.g)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), raw, "읽기만으로 파일을 다시 쓰지 않음")

    def test_failed_save_leaves_the_node_as_it_was(self):
        path = sn.store_path(None, self.g["graph_id"])
        with open(path, "rb") as fh:
            raw = fh.read()
        with mock.patch.object(cmd.nodes, "save_fp", side_effect=OSError("꺼짐")):
            out = self.run_cmd("edit_members", {"node_id": self.nid, "add": self.ids("V2"), "remove": self.ids("L1")})
        self.assertFalse(out["ok"])
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), raw, "반쯤 고친 상태가 남지 않음")
        self.assertEqual(self.handed(), ["e1"])

    def test_bad_edit_members_args_are_refused(self):
        for args in ({"node_id": self.nid}, {"node_id": self.nid, "add": self.ids("V2"), "remove": self.ids("V2")},
                     {"node_id": self.nid, "add": "V2"}):
            out = self.run_cmd("edit_members", args)
            self.assertEqual((out["ok"], out["refused"][0]["code"]), (False, "bad_args"), args)

    def test_refused_duplicate_keeps_the_node_in_analysis(self):
        other = self.make("같아질 구간", "TK", "V1", "V2", "L1")
        out = self.run_cmd("edit_members", {"node_id": self.nid, "add": self.ids("V2")})
        self.assertFalse(out["ok"])
        self.assertIn("구성요소가 같은 구간", out["refused"][0]["reason"])
        ns, _doc = self.loaded()
        self.assertEqual(sorted(self.node(self.nid, ns)["members"]), sorted(self.ids("TK", "V1", "L1")))
        self.assertEqual([n["node_id"] for n in api_results.scope_rows(ns)], [self.nid, other])
        self.assertIn(self.nid, {u["node_id"] for u in ai_cells.plan_units(ns, DEVS)})
        self.assertEqual(self.handed(), ["e1"], "거절돼도 분석·인계에서 빠지지 않음")

    def test_old_confirmed_node_is_edited_directly(self):
        ns = sn.load(self.g)
        sn.save(sn.confirm_nodes(ns, self.g, [self.nid], "옛 검토자", at=AT))
        for name, args in (("rename", {"node_id": self.nid, "name": "새 이름"}),
                           ("edit_members", {"node_id": self.nid, "add": self.ids("V2")}),
                           ("set_design_intent", {"node_id": self.nid, "text": "유량 보냄"})):
            out = self.run_cmd(name, args)
            self.assertTrue(out["ok"], (name, out))
        node = self.node(self.nid)
        self.assertEqual(node["state"], "confirmed", "옛 확정 기록은 그대로 둠")
        self.assertEqual(node["confirmed"]["by"], "옛 검토자", "확정자 이름을 새로 적지 않음")
        self.assertEqual(self.handed(), [], "구성요소가 바뀐 판정은 빠짐")

    def test_locked_node_is_not_changed(self):
        ns = sn.load(self.g)
        locked = sn.confirm_nodes(ns, self.g, [self.nid], "옛 검토자", at=AT)
        sn._find(locked, self.nid).update(state="locked", locked={"at": AT, "by": "옛 검토자", "reason": None})
        sn.save(locked)
        for name, args in (("rename", {"node_id": self.nid, "name": "새 이름"}),
                           ("edit_members", {"node_id": self.nid, "add": self.ids("V2")}),
                           ("add_members", {"node_id": self.nid, "members": self.ids("V2")}),
                           ("remove", {"node_id": self.nid, "archive": True})):
            out = self.run_cmd(name, args)
            self.assertFalse(out["ok"], name)
            self.assertIn("잠긴", out["refused"][0]["reason"])
        ns, doc = self.loaded()
        self.assertEqual(self.node(self.nid, ns)["state"], "locked")
        self.assertNotIn(self.nid, {u["node_id"] for u in ai_cells.plan_units(ns, DEVS)}, "잠금은 다시 분석하지 않음")
        self.assertEqual([n["node_id"] for n in api_results.scope_rows(ns)], [self.nid], "결과에는 듦")
        self.assertEqual(self.handed(ns, doc), ["e1"], "인계에도 듦")
        self.assertTrue(self.run_cmd("unlock", {"node_ids": [self.nid], "reason": "고칠 것이 있음"})["ok"], "풀기는 남음")

    def test_removing_a_judged_node_archives_its_verdicts(self):
        refused = self.run_cmd("remove", {"node_id": self.nid})
        self.assertFalse(refused["ok"], "판정이 있으면 보관을 고르지 않고는 지우지 않음")
        out = self.run_cmd("remove", {"node_id": self.nid, "archive": True})
        self.assertTrue(out["ok"], out)
        ns, doc = self.loaded()
        self.assertEqual(ns["nodes"], [])
        self.assertEqual([a["cell"]["entries"][0]["entry_id"] for a in doc["archived_cells"]], ["e1"])
        self.assertEqual(doc["archived_cells"][0]["reason"], "node_removed")
        self.assertEqual(self.handed(ns, doc), [])


class OldDataTest(Base):
    def test_stored_states_read_under_the_new_rule(self):
        a = self.make("적용됨", "TK", "V1")
        c = self.make("확정", "V1", "V2", "L2")
        k = self.make("잠금", "V2", "PP", "L3")
        ns = sn.confirm_nodes(sn.load(self.g), self.g, [c, k], "옛 검토자", at=AT)
        sn._find(ns, k).update(state="locked", locked={"at": AT, "by": "옛 검토자", "reason": None})
        sn.save(ns)
        for nid in (a, c, k):
            self.put_entries(nid, [entry("e-" + nid)])
        ns, doc = self.loaded()
        self.assertEqual([self.node(n, ns)["state"] for n in (a, c, k)], ["applied", "confirmed", "locked"], "판을 올리지 않음")
        self.assertEqual(ns["schema_version"], sn.SCHEMA_VERSION)
        self.assertEqual([n["node_id"] for n in api_results.scope_rows(ns)], [a, c, k])
        self.assertEqual(sorted({u["node_id"] for u in ai_cells.plan_units(ns, DEVS)}), sorted([a, c]))
        self.assertEqual(self.handed(ns, doc), sorted("e-" + n for n in (a, c, k)))
        self.assertTrue(self.run_cmd("rename", {"node_id": c, "name": "고침"})["ok"])
        self.assertTrue(self.run_cmd("rename", {"node_id": a, "name": "고침 2"})["ok"])
        self.assertFalse(self.run_cmd("rename", {"node_id": k, "name": "고침 3"})["ok"])


class ReReadTest(Base):
    def test_recheck_after_redrawing_stays_a_mark_not_a_demotion(self):
        g1 = self.g
        ns = sn.new_set(g1)
        ns["nodes"] = [
            dict({"node_id": "S1", "name": "탱크 출구", "basis": "b", "members": sorted(self.ids("TK", "V1", "V2", "L2"))},
                 **sn._v2_fields("user")),
            dict({"node_id": "S2", "name": "펌프", "basis": "b", "members": sorted(self.ids("V2", "PP"))},
                 **sn._v2_fields("ai"))]
        ns = sn.confirm_nodes(ns, g1, ["S1"], "옛 검토자", at=AT)
        ns.update(idmap.snapshot(g1))
        ns["member_digest"] = migrate.node_digests(g1, {n["node_id"]: n["members"] for n in ns["nodes"]})
        doc = res.empty_results(ns, DEVS)
        for cell, eid_ in zip(doc["cells"], ("e1", "e2")):
            cell.update(state="analyzed", entries=[entry(eid_)])
        g2 = graph("v2", objects=[o for o in OBJECTS if o[0] != "V2"], pipes=[p for p in PIPES if "V2" not in p[1:]])
        moved, plan = migrate.migrate_set(ns, g2, at=AT)
        self.assertEqual(sorted(plan["recheck"]), ["S1", "S2"])
        self.assertEqual([n["state"] for n in moved["nodes"]], ["confirmed", "applied"], "상태를 내리지 않음")
        self.assertEqual([n["rev"] for n in moved["nodes"]], [2, 2])
        self.assertTrue(all(n.get("lost") for n in moved["nodes"]), "찾지 못한 구성요소 표시")
        self.assertIn("찾지 못한", moved["history"][-1]["detail"]["recheck"]["S1"], "재확인 사유 글은 남음")
        self.assertEqual(moved["history"][-1]["detail"].get("demoted"), [], "확정을 푼 구간이 없음")
        out = res.reconcile(migrate.migrate_results(doc, moved, table=plan["table"])[0], moved, DEVS, at=AT)
        self.assertTrue(all(e["scope_changed"] for c in out["cells"] for e in c["entries"]), "'범위 바뀜'으로 알림")
        self.assertEqual(self.handed(moved, out), [])
        self.assertIn("다시 확인", migrate.notice(moved))

    def test_applied_node_without_a_content_record_is_rechecked(self):
        ns = sn.new_set(self.g)
        ns["nodes"] = [dict({"node_id": "S1", "name": "탱크", "basis": "b", "members": sorted(self.ids("TK", "V1"))},
                            **sn._v2_fields("user"))]
        ns.update(idmap.snapshot(self.g))
        ns["member_digest"] = {}
        _moved, plan = migrate.migrate_set(ns, graph("v2"), at=AT)
        self.assertIn("S1", plan["recheck"], "분석했을 수 있으니 기록이 없으면 다시 확인")


class AiNodeTest(Base):
    def request(self, rid, turn="u-1"):
        return {"request_id": rid, "user_turn": turn, "request_text": "구간 나눠 줘"}

    def test_ai_node_is_analyzed_but_its_verdicts_wait_for_a_person(self):
        nid = self.make("AI 구간", "TK", "V1", author="ai", by=None, request=self.request("q-1"))
        ns = sn.load(self.g)
        self.assertEqual((self.node(nid, ns)["origin"], self.node(nid, ns)["state"]), ("ai", "applied"))
        self.assertIn(nid, {u["node_id"] for u in ai_cells.plan_units(ns, DEVS)}, "사람 확인 없이 분석 대상")
        self.put_entries(nid, [entry("a1", status="proposed", origin="ai_draft")])
        self.assertEqual(self.handed(), [], "AI 초안은 사람이 승인하기 전 인계에 없음")
        ns, doc = self.loaded()
        _picked, left = ie_bundle.approved_entries(doc, ns)
        self.assertEqual(left, 1, "넣지 않은 수로 셈")
        doc = res.set_status(doc, nid, "D01", "a1", "approved", at=AT, node_set=ns, by=BY)
        res.save(doc, ns.get("project_id"))
        self.assertEqual(self.handed(), ["a1"], "사람이 승인하면 듦")

    def test_no_five_node_cap_only_thirty_per_request(self):
        ns = sn.new_set(self.g)
        ids = [n["entity_id"] for n in self.g["nodes"]]
        sets = list(itertools.combinations(ids, 2)) + list(itertools.combinations(ids, 3))
        ops = [{"op": "add", "members": list(m), "name": "AI %d" % i} for i, m in enumerate(sets)]
        self.assertGreater(len(ops), nt.REST_LIMIT)
        doc = res.empty_results(ns, DEVS)
        out, _d, _b = nt.apply_nodes(ns, doc, self.g, ops[:8], self.request("q-1"), "ai", ns["set_rev"], at=AT)
        self.assertEqual(len(out["nodes"]), 8, "확인 전 AI 구간 5개 상한 없음")
        out2, _d, _b = nt.apply_nodes(out, doc, self.g, ops[8:16], self.request("q-2"), "ai", out["set_rev"], at=AT)
        self.assertEqual(len(out2["nodes"]), 16, "같은 질문이어도 이어 만듦")
        with self.assertRaises(nt.Refused) as why:
            nt.apply_nodes(ns, doc, self.g, ops[:nt.REST_LIMIT + 1], self.request("q-3"), "ai", ns["set_rev"], at=AT)
        self.assertIn("30", str(why.exception))

    def test_chat_has_no_confirm_unconfirm_lock_actions(self):
        for name in ("nodes.confirm", "nodes.unconfirm", "nodes.lock"):
            self.assertNotIn(name, chat_actions.ACTIONS)
        self.assertNotIn("nodes.confirm", chat_actions.node_executors(self.g, lambda *a, **k: None))
        from hazop.shell import chat_actions as shell_chat
        self.assertEqual(shell_chat.NODE_ACTIONS, ("nodes.apply", "nodes.undo"))


if __name__ == "__main__":
    unittest.main()
