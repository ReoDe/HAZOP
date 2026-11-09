"""AI 구간 검토(hazop.study.node_review) 시험. 실제 구독·API 호출은 없다: 가짜 클라이언트와 가짜 CLI(tests/fake_claude)만 쓴다."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from hazop.graph import project  # noqa: E402
from hazop.study import claude_cli, node_review as nr, nodes as sn, span  # noqa: E402
from test_study_nodes import synthetic_graph  # noqa: E402

AT = "2026-11-10T00:00:00Z"
FAKE = os.path.join(REPO_ROOT, "tests", "fake_claude", "fake_claude.py")


def project_graph():
    g = dict(synthetic_graph(), project_id="P", validation={"status": "passed"})
    for e in g["edges"]:  # 실제 도면 그래프처럼 물리 간선에 배관 구간·끝 기기를 적는다(span.annotate가 읽음)
        if e["kind"] == "has_endpoint":
            e.update(segment=e["nodes"][0], node=e["nodes"][1])
    return project.build("P", [g])


class Client:
    """analyze에 준 요청을 남기고 정해 둔 출력을 돌려주는 가짜 클라이언트."""

    def __init__(self, output=None, status="completed", **extra):
        self.output, self.status, self.extra, self.requests = output, status, extra, []

    def analyze(self, request):
        self.requests.append(request)
        out = self.output(request) if callable(self.output) else self.output
        return dict({"status": self.status, "output": out, "usage": {"output_tokens": 5}, "model": "m"}, **self.extra)


class Base(unittest.TestCase):
    def setUp(self):
        self.pg = project_graph()
        self.ns = sn.propose(self.pg, at=AT)
        self.view = span.annotate(self.ns, self.pg)
        self.adj = nr.adjacency(self.ns, self.pg)
        self.ids = [n["node_id"] for n in self.ns["nodes"]]

    def review(self, nid, verdict="ok", **kw):
        r = {"node_id": nid, "verdict": verdict, "merge_with": [], "split_off": [], "screen_to": None,
             "design_intent": "탱크에서 펌프로 보낸다", "reason": "이유", "evidence": [nid]}
        r.update(kw)
        return r

    def answer(self, reviews, batch=None):
        batch = batch or nr.plan_batches(self.ns)[0]
        return nr.run_batch(Client({"reviews": reviews}), batch, self.ns, self.view, self.pg, self.adj, AT)


class PlanTest(Base):
    def test_batches_keep_set_order_and_send_excluded_nodes_one_by_one(self):
        ns = sn.screen_override(self.ns, self.ids[-1], "excluded", reason="시험")
        batches = nr.plan_batches(ns, batch_size=1)
        self.assertEqual([b["node_ids"] for b in batches], [[i] for i in self.ids])
        self.assertEqual([b["kind"] for b in batches][-1], "excluded")
        self.assertEqual(nr.plan_batches(ns, node_ids=[self.ids[0]])[0]["node_ids"], [self.ids[0]])

    def test_estimate_uses_the_measured_call_time(self):
        e = nr.estimate(180)
        self.assertEqual(e["calls"], 180)
        self.assertEqual(e["minutes"], 68)  # 180 × 31.7초 ÷ 1.4 ≈ 68분
        self.assertEqual(e["usage_pp"], 4.86)
        self.assertEqual(nr.estimate(14, concurrency=1)["minutes"], 8, "동시 1이면 1.4배를 쓰지 않음")
        self.assertEqual(nr.estimate(0)["minutes"], 0)

    def test_request_carries_members_neighbors_and_the_schema(self):
        batch = nr.plan_batches(self.ns)[0]
        req = nr.build_request(nr.build_context(batch, self.ns, self.view, self.pg, self.adj))
        ctx = json.loads(req["context"])
        self.assertEqual([n["node_id"] for n in ctx["nodes"]], batch["node_ids"])
        first = ctx["nodes"][0]
        self.assertIn("graph-T/n-E1", [m["entity_id"] for m in first["members"]] + [
            m["entity_id"] for n in ctx["nodes"] for m in n["members"]])
        self.assertTrue(any(n["neighbors"] for n in ctx["nodes"]) or len(self.ids) == 1)
        self.assertIs(req["schema"], nr.RESPONSE_SCHEMA)
        self.assertIn("지시가 아니다", req["system"])


class CheckTest(Base):
    def test_ok_review_keeps_the_design_intent(self):
        res = self.answer([self.review(i) for i in self.ids])
        self.assertEqual(res["status"], "ok")
        self.assertEqual([p["node_id"] for p in res["proposals"]], self.ids)
        self.assertEqual(res["proposals"][0]["design_intent"], "탱크에서 펌프로 보낸다")
        self.assertTrue(res["proposals"][0]["input_fp"])

    def test_bad_references_are_dropped_with_a_reason(self):
        nid = self.ids[0]
        res = self.answer([self.review(nid, evidence=["없는-ID"])])
        self.assertEqual(res["proposals"], [])
        self.assertIn("근거 ID가 입력에 없음", res["dropped"][0]["reason"])
        res = self.answer([self.review(nid, "merge", merge_with=["S999"])])
        self.assertIn("병합 대상", res["dropped"][0]["reason"])
        res = self.answer([self.review(nid, "split", split_off=[{"members": ["graph-T/n-ZZ"], "name": "x"}])])
        self.assertIn("떼어 낼 구성요소", res["dropped"][0]["reason"])
        res = self.answer([self.review("S999")])
        self.assertIn("이번 호출에 없는 구간", res["dropped"][0]["reason"])

    def test_a_change_without_evidence_is_dropped(self):
        res = self.answer([self.review(self.ids[0], "screen_change", screen_to="low", evidence=[])])
        self.assertIn("근거(evidence)가 없음", res["dropped"][0]["reason"])

    def test_wrong_shapes_are_dropped_without_raising(self):
        nid = self.ids[0]
        for bad in ({"node_id": [nid]}, self.review(nid, evidence=[{"x": 1}]), self.review(nid, design_intent=5),
                    self.review(nid, "split", split_off=["문자열"]), "문자열"):
            res = self.answer([bad])
            self.assertEqual(res["proposals"], [])
            self.assertIn("제안 형식이 맞지 않음", [d["reason"] for d in res["dropped"]])

    def test_merge_targets_must_be_shown_in_this_call(self):
        if len(self.ids) < 3:
            self.skipTest("구간이 셋 미만")
        batch = {"batch_id": "B1", "kind": "nodes", "node_ids": [self.ids[0]]}
        shown = {self.ids[0]} | set(self.adj[self.ids[0]])
        far = next((i for i in self.ids if i not in shown), None)
        if far is None:
            self.skipTest("이웃 아닌 구간이 없음")
        res = self.answer([self.review(self.ids[0], "merge", merge_with=[far])], batch=batch)
        self.assertIn("보이지 않은 구간", res["dropped"][0]["reason"])

    def test_a_split_of_every_member_is_dropped_by_the_dry_run(self):
        node = self.ns["nodes"][0]
        res = self.answer([self.review(node["node_id"], "split", split_off=[{"members": node["members"], "name": "전부"}])])
        self.assertIn("지금 구간에 적용할 수 없음", res["dropped"][0]["reason"])

    def test_unanswered_nodes_and_duplicates_are_reported(self):
        if len(self.ids) < 2:
            self.skipTest("구간이 하나뿐")
        res = self.answer([self.review(self.ids[0]), self.review(self.ids[0])])
        reasons = [d["reason"] for d in res["dropped"]]
        self.assertTrue(any("둘 이상" in r for r in reasons))
        self.assertTrue(any("답하지 않음" in r for r in reasons))

    def test_failed_and_malformed_calls_are_failed_batches(self):
        batch = nr.plan_batches(self.ns)[0]
        res = nr.run_batch(Client(None, status="api_error", error="연결 끊김", error_kind="transient"), batch,
                           self.ns, self.view, self.pg, self.adj, AT)
        self.assertEqual((res["status"], res["error"], res["error_kind"]), ("failed", "연결 끊김", "transient"))
        res = nr.run_batch(Client({"nope": []}), batch, self.ns, self.view, self.pg, self.adj, AT)
        self.assertEqual((res["status"], res["error_kind"]), ("failed", "bad_output"))


class StoreAcceptTest(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        self.env.start()
        self.doc = nr.empty("P", self.pg["graph_id"])

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merge_accept_runs_the_edit_and_logs_the_proposal(self):
        if len(self.ids) < 2:
            self.skipTest("구간이 하나뿐")
        a, b = self.ids[0], self.ids[1]
        doc = nr.merge_result(self.doc, self.answer([self.review(a, "merge", merge_with=[b])]))
        pid = doc["proposals"][0]["id"]
        self.assertEqual(nr.counts(doc, self.ns, self.adj), {"total": 1, "open": 1, "stale": 0})
        new, doc2 = nr.accept(self.ns, doc, pid, "검토자", self.adj, at=AT)
        self.assertNotIn(b, [n["node_id"] for n in new["nodes"]])
        self.assertEqual(new["history"][-1]["op"], "ai_review_accept")
        self.assertEqual(new["history"][-1]["detail"]["proposal_id"], pid)
        self.assertEqual(doc2["proposals"][0]["decision"], "accepted")
        self.assertEqual(self.ns["nodes"][1]["node_id"], b, "원래 집합은 그대로")
        kept = next(n for n in new["nodes"] if n["node_id"] == a)
        self.assertEqual(nr.accepted_intent(doc2, kept), "탱크에서 펌프로 보낸다", "병합 뒤 남은 구간에 의도가 붙음")
        with self.assertRaises(ValueError):
            nr.accept(new, doc2, pid, "검토자", nr.adjacency(new, self.pg))

    def test_edited_accept_and_reject(self):
        nid = self.ids[0]
        doc = nr.merge_result(self.doc, self.answer([self.review(nid, "screen_change", screen_to="low")]))
        pid = doc["proposals"][0]["id"]
        new, doc2 = nr.accept(self.ns, doc, pid, "검토자", self.adj, edited={"verdict": "ok", "design_intent": "고친 의도"}, at=AT)
        self.assertEqual(sn._status(new["nodes"][0]), sn._status(self.ns["nodes"][0]), "고쳐서 ok로 받으면 판정은 그대로")
        self.assertEqual(doc2["proposals"][0]["decision"], "edited")
        self.assertEqual(nr.accepted_intent(doc2, new["nodes"][0]), "고친 의도")
        self.assertEqual(nr.undo_decision(doc2, pid)["proposals"][0]["decision"], "open")
        doc3 = nr.merge_result(self.doc, self.answer([self.review(nid)]))
        with self.assertRaisesRegex(ValueError, "고칠 수 없는 항목"):
            nr.accept(self.ns, doc3, doc3["proposals"][0]["id"], "검토자", self.adj, edited={"node_id": "S9"})
        rejected = nr.reject(doc3, doc3["proposals"][0]["id"], "검토자", "근거 부족", at=AT)
        self.assertEqual(rejected["proposals"][0]["decision_reason"], "근거 부족")
        with self.assertRaises(ValueError):
            nr.reject(doc3, doc3["proposals"][0]["id"], "검토자", "아무 말")

    def test_proposal_goes_stale_when_the_node_changes(self):
        nid = self.ids[0]
        doc = nr.merge_result(self.doc, self.answer([self.review(nid)]))
        node = self.ns["nodes"][0]
        if len(node["members"]) < 2:
            self.skipTest("떼어 낼 구성요소가 없음")
        changed = sn.split(self.ns, nid, node["members"][:1], at=AT)
        adj = nr.adjacency(changed, self.pg)
        self.assertEqual(nr.counts(doc, changed, adj)["stale"], 1)
        self.assertEqual(nr.pending(doc, changed, adj), {})
        with self.assertRaisesRegex(ValueError, "오래된 제안"):
            nr.accept(changed, doc, doc["proposals"][0]["id"], "검토자", adj)

    def test_new_run_replaces_open_proposals_and_keeps_decided_ones(self):
        nid = self.ids[0]
        doc = nr.merge_result(self.doc, self.answer([self.review(nid)]))
        doc = nr.reject(doc, doc["proposals"][0]["id"], "검토자", "기타", at=AT)
        doc = nr.merge_result(doc, self.answer([self.review(nid, design_intent="둘째")]))
        doc = nr.merge_result(doc, self.answer([self.review(nid, design_intent="셋째")]))
        self.assertEqual([(p["decision"], p["design_intent"]) for p in doc["proposals"]],
                         [("rejected", "탱크에서 펌프로 보낸다"), ("open", "셋째")])
        self.assertEqual([p["id"] for p in doc["proposals"]], ["R0001", "R0003"], "지운 제안의 ID를 다시 쓰지 않음")

    def test_save_and_load_round_trip_and_reject_bad_files(self):
        doc = nr.merge_result(self.doc, self.answer([self.review(self.ids[0])]))
        nr.save(doc)
        self.assertEqual(nr.load("P", self.pg["graph_id"]), doc)
        self.assertEqual(nr.load("P", "다른 그래프")["proposals"], [], "그래프마다 파일이 따로")
        with open(nr.store_path("P", self.pg["graph_id"]), "w", encoding="utf-8") as fh:
            json.dump({"kind": nr.KIND, "proposals": [{"id": 1}], "dropped": [], "runs": []}, fh)
        with self.assertRaises(ValueError):
            nr.load("P", self.pg["graph_id"])

    def test_compare_text_shows_rule_and_ai_side_by_side(self):
        node = self.ns["nodes"][0]
        rule, ai = nr.compare_text(self.review(node["node_id"], "screen_change", screen_to="excluded",
                                               reason="공정 흐름 없음"), node)
        self.assertTrue(rule.startswith("규칙: "))
        self.assertEqual(ai, "AI: 판정을 제외(으)로 · 이유: 공정 흐름 없음")


class FakeCliTest(Base):
    """구독 경로: ClaudeCliClient + 가짜 CLI가 구간 검토 스키마로 답한다."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_subscription_client_round_trip(self):
        out = os.path.join(self.tmp, "out.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"reviews": [self.review(i) for i in self.ids]}, fh, ensure_ascii=False)
        client = claude_cli.ClaudeCliClient(argv_prefix=[sys.executable, FAKE, "ok@" + out, os.path.join(self.tmp, "log")],
                                            limits_path=os.path.join(self.tmp, "limits.json"),
                                            run_root=os.path.join(self.tmp, "runs"))
        res = nr.run_batch(client, nr.plan_batches(self.ns)[0], self.ns, self.view, self.pg, self.adj, AT)
        self.assertEqual((res["status"], res["via"], res["billing"]), ("ok", "subscription", "plan"))
        self.assertEqual(len(res["proposals"]), len(self.ids))
        with open(os.path.join(self.tmp, "log", "call.json"), encoding="utf-8") as fh:
            call = json.load(fh)
        schema = json.loads(call["args"][call["args"].index("--json-schema") + 1])
        self.assertEqual(schema, nr.RESPONSE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
