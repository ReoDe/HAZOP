"""채팅이 제안한 쓰기 동작의 새 화면 연결부(hazop/shell/chat_actions.py). 실행: python -m unittest tests.test_shell_chat_actions

가짜 클라이언트(세션)가 `actions`가 든 답을 내면, 실제 동작 층(ActionPlanner)과 실제 구간 엔진(node_commands)으로 판정·실행해
웹으로 가는 사건(chat.actions · chat.action.result)과 구간 저장이 맞는지 본다. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.shell import api, api_nodes, chat, chat_actions  # noqa: E402
from hazop.study import node_tools, nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_node_tools import DEVS, snp_graph  # noqa: E402


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, event):
        self.items.append(event)

    def of(self, name):
        return [e["data"] for e in self.items if e.get("t") == "event" and e.get("name") == name]

    def changes(self, topic):
        return [e for e in self.items if e.get("t") == "changed" and e.get("topic") == topic]


class FakeSession:
    """질문을 받으면 정해 둔 답을 바로 낸다(answers 목록을 차례로)."""

    def __init__(self, model, cb, answers):
        self.model, self.cb, self.answers, self.n = model, cb, answers, 0

    def start(self):
        return True

    def ask(self, text, view=None):
        self.n += 1
        qid = "q%d" % self.n
        answer = self.answers.pop(0)
        self.cb["on_answer"](qid, answer, {})
        return qid

    def stop(self):
        pass

    def close(self):
        pass

    def set_model(self, model):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellchatact-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.pg = snp_graph()
        from hazop.app import project_ctx
        p = mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg)
        p.start()
        self.addCleanup(p.stop)
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events)
        self.engine.settings["project_id"] = "SNP"
        self.engine.settings["reviewer_name"] = "홍길동"
        self.records = []
        self.answers = []
        self.actions = chat_actions.ChatActions(
            lambda name, data: self.events({"t": "event", "name": name, "data": data}), self.engine.project_id, lambda: self.pg,
            self.engine.reviewer, self.engine.changed, record=lambda pid, **kw: self.records.append(kw) or {"status": "written"})
        self.chat = chat.ChatController(self.events, lambda model, cb: FakeSession(model, cb, self.answers), lambda: (chat.NoEnv(), self.pg),
                                        project_fn=self.engine.project_id, actions=self.actions)
        self.engine.chat = self.chat
        self.chat.set_availability("ok")

    def ns(self):
        return nodes.load(self.pg) or nodes.new_set(self.pg)

    def candidates(self, n):
        return node_tools.make_candidates(self.pg, self.ns(), granularity="normal", limit=30)["candidates"][:n]

    def answer(self, actions, text="답"):
        return {"text": text, "general": "", "refs": [], "paths": [], "highlight": [], "warnings": [], "actions": actions}

    def apply(self, cands, names=None):
        return {"action": "nodes.apply", "args": {"set_rev": self.ns()["set_rev"],
                                                  "ops": [{"op": "add", "cand_id": c["cand_id"], "name": (names or {}).get(i, "구간 %d" % (i + 1))}
                                                          for i, c in enumerate(cands)]}, "why": "대표 구간"}

    def ask(self, actions, text="대표 구간 3개 먼저 만들어 줘"):
        self.answers.append(self.answer(actions))
        before = len(self.events.of("chat.actions"))
        self.assertTrue(self.chat.ask(text))
        got = self.events.of("chat.actions")
        return got[-1] if len(got) > before else None


class ApplyAndUndoTest(Base):
    def test_representative_nodes_are_applied_at_once_and_announced(self):
        out = self.ask([self.apply(self.candidates(3), {0: "가압기 압력 제어"})])
        item = out["items"][0]
        self.assertEqual((item["status"], len(item["node_ids"])), ("applied", 3), item)
        self.assertTrue(item["batch_id"])
        self.assertIn("가압기 압력 제어", item["text"])
        self.assertIn(item["batch_id"], item["text"])
        ns = self.ns()
        self.assertEqual({n["origin"] for n in ns["nodes"]}, {"ai"})
        self.assertTrue(self.events.changes("nodes"), "패널과 도면이 다시 읽도록 changed(nodes)를 보낸다")
        self.assertEqual(self.records[-1]["result"], "ok")

    def test_user_undo_of_the_batch_goes_through_the_node_command(self):
        out = self.ask([self.apply(self.candidates(3))])
        batch = out["items"][0]["batch_id"]
        r = self.engine.dispatch("nodes.undo", {"batch_id": batch, "set_rev": self.ns()["set_rev"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.ns()["nodes"], [], "묶음의 구간이 모두 사라진다")

    def test_a_second_batch_in_the_same_message_is_refused_and_a_new_message_needs_confirmation(self):
        first = self.ask([self.apply(self.candidates(3))])
        self.assertEqual(first["items"][0]["status"], "applied")
        rest = self.candidates(6)[3:]
        second = self.ask([self.apply(rest)], "나머지도 만들어 줘")
        item = second["items"][0]
        self.assertEqual(item["status"], "confirm", "대표 단계 뒤 상한을 넘으면 확인 상자")
        self.assertTrue(item["token"])
        self.assertIn("확인하지 않았습니다", item["text"])
        self.assertEqual(len(self.ns()["nodes"]), 3, "확인 전에는 만들지 않는다")

    def test_nothing_happens_when_the_answer_has_no_actions(self):
        self.answers.append(self.answer([]))
        self.assertTrue(self.chat.ask("그냥 질문"))
        self.assertEqual(self.events.of("chat.actions"), [])


class ConfirmTest(Base):
    def setUp(self):
        super().setUp()
        self.ask([self.apply(self.candidates(3))])
        self.target = self.ns()["nodes"][0]["node_id"]

    def confirm_item(self):
        out = self.ask([{"action": "nodes.confirm", "args": {"node_ids": [self.target]}, "why": "확정"}], "S1 확정해 줘")
        item = out["items"][0]
        self.assertEqual(item["status"], "confirm", item)
        return item

    def test_approve_runs_with_the_reviewer_name_not_a_web_value(self):
        item = self.confirm_item()
        r = self.engine.dispatch("chat.action.approve", {"token": item["token"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["result"], "ok")
        node = next(n for n in self.ns()["nodes"] if n["node_id"] == self.target)
        self.assertEqual(node["confirmed"]["by"], "홍길동")
        res_ev = self.events.of("chat.action.result")[-1]
        self.assertEqual((res_ev["token"], res_ev["item"]["status"]), (item["token"], "applied"))
        self.assertEqual(self.records[-1]["confirmed_by"], "홍길동")

    def test_without_a_reviewer_name_nothing_runs(self):
        item = self.confirm_item()
        self.engine.settings["reviewer_name"] = ""
        r = self.engine.dispatch("chat.action.approve", {"token": item["token"]})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "no_reviewer"))
        node = next(n for n in self.ns()["nodes"] if n["node_id"] == self.target)
        self.assertFalse(node.get("confirmed"))

    def test_decline_does_not_run(self):
        item = self.confirm_item()
        r = self.engine.dispatch("chat.action.decline", {"token": item["token"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.events.of("chat.action.result")[-1]["item"]["status"], "declined")
        self.assertFalse(next(n for n in self.ns()["nodes"] if n["node_id"] == self.target).get("confirmed"))
        again = self.engine.dispatch("chat.action.approve", {"token": item["token"]})
        self.assertTrue(again["ok"] and again["data"]["result"] == "duplicate" or not again["ok"], again)

    def test_a_forged_token_runs_nothing(self):
        self.confirm_item()
        r = self.engine.dispatch("chat.action.approve", {"token": "forged-token"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["result"], "rejected")
        self.assertFalse(any(n.get("confirmed") for n in self.ns()["nodes"]))

    def test_target_changed_after_the_box_was_shown_is_stale(self):
        item = self.confirm_item()
        human = self.engine.dispatch("nodes.rename", {"node_id": self.target, "name": "사람이 고침", "set_rev": self.ns()["set_rev"],
                                                      "targets": [{"node_id": self.target, "rev": 1, "state": "applied"}]})
        self.assertTrue(human["ok"], human)
        r = self.engine.dispatch("chat.action.approve", {"token": item["token"]})
        self.assertEqual(r["data"]["result"], "stale", r)
        self.assertFalse(next(n for n in self.ns()["nodes"] if n["node_id"] == self.target).get("confirmed"))

    def test_new_conversation_drops_the_box(self):
        item = self.confirm_item()
        self.chat.new_conversation()
        r = self.engine.dispatch("chat.action.approve", {"token": item["token"]})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "closed")

    def test_lock_unconfirmed_is_refused_with_a_reason(self):
        out = self.ask([{"action": "nodes.lock", "args": {"node_ids": [self.target]}, "why": "잠금"}], "잠가 줘")
        item = out["items"][0]
        self.assertEqual(item["status"], "rejected", item)
        self.assertTrue(item["reason"])


if __name__ == "__main__":
    unittest.main()
