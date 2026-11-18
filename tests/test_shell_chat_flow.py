"""채팅이 만든 구간이 새 화면의 패널·도면·되돌리기까지 이어지는 통합 시험. 실행: python -m unittest tests.test_shell_chat_flow

실제 새 화면 창(ShellWindow)과 실제 채팅 조종기·동작 층·구간 엔진을 쓰고 모델 쪽만 가짜 세션으로 둔다(실제 구독 호출 없음):
"대표 구간 3개 먼저 만들어 줘" -> 적용 상자(묶음 B1) -> 구간 패널에 3개 -> '이 요청 되돌리기' -> 패널이 비고 저장도 비어 있음,
그리고 확인 상자(확정)의 실행·하지 않음. 구간 자료는 SNP 표본 그래프(tests/test_study_node_tools)로 만들고 임시 작업 루트에만 쓴다.
"""

import copy
import json
import os
import sys
import shutil
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.study import node_tools, nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_chat_card import answer  # noqa: E402
from tests.test_study_node_tools import DEVS, snp_graph  # noqa: E402

pump, wait_for = W.pump, W.wait_for
tearDownModule = W.shell_teardown


class ChatToPanelTest(W.ShellBase):
    def setUp(self):
        self.pg = snp_graph()
        from hazop.app import project_ctx
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)
        shutil.rmtree(os.path.join(nodes.store_dir(), "SNP"), ignore_errors=True)   # 시험마다 빈 구간 저장(작업 루트는 시험 묶음이 함께 쓴다)

    def ns(self):
        return nodes.load(self.pg) or nodes.new_set(self.pg)

    def cands(self, n):
        return node_tools.make_candidates(self.pg, self.ns(), granularity="normal", limit=30)["candidates"][:n]

    def propose(self, win, actions, text="대표 구간 3개 먼저 만들어 줘"):
        self.js(win, "window.__hz.cmd('chat.ask', {text: %s})" % json.dumps(text))
        self.assertTrue(wait_for(lambda: bool(self.sessions) and bool(self.sessions[-1].asked), 10))
        s = self.sessions[-1]
        qid = "q%d" % len(s.asked)
        ans = answer(text="대표 구간을 제안합니다.")
        ans["actions"] = actions
        t = threading.Thread(target=lambda: s.cb["on_answer"](qid, ans, {}))
        t.start()
        t.join()
        pump(0.6)

    def apply_action(self, cands):
        return {"action": "nodes.apply", "args": {"set_rev": self.ns()["set_rev"],
                "ops": [{"op": "add", "cand_id": c["cand_id"], "name": "대표 구간 %d" % (i + 1)} for i, c in enumerate(cands)]}, "why": "대표 구간"}

    def test_create_then_see_in_panel_then_undo(self):
        win = self.window()
        self.switch_project(win, "SNP")
        self.propose(win, [self.apply_action(self.cands(3))])
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.applied').length") or 0) == 1, 10), self.text(win)[-400:])
        text = self.text(win)
        self.assertIn("구간 3개를 만들었습니다", text)
        self.assertIn("이 요청 되돌리기", text)
        self.assertIn("나머지도 나누기", text)
        self.assertEqual(len(self.ns()["nodes"]), 3)
        # 구간 패널에 곧바로 보인다
        self.assertTrue(self.click(win, ".rail button", 1))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.nrow').length") or 0) == 3, 10), self.text(win)[-400:])
        self.assertIn("대표 구간 1", self.text(win))
        # 되돌리기
        self.assertTrue(self.click(win, "button[aria-label='이 요청 되돌리기']"))
        self.assertTrue(wait_for(lambda: len(self.ns()["nodes"]) == 0, 10), "되돌리면 저장본에서도 사라진다")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.nrow').length") or 0) == 0, 10))
        self.assertIn("되돌렸습니다", self.text(win))

    def test_rest_button_asks_a_new_question(self):
        win = self.window()
        self.switch_project(win, "SNP")
        self.propose(win, [self.apply_action(self.cands(3))])
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.applied').length") or 0) == 1, 10))
        before = len(self.sessions[-1].asked)
        s = self.sessions[-1]
        s.cb["on_state"]("ok", "")
        self.assertTrue(self.click(win, "button[aria-label='나머지도 나누기']"))
        self.assertTrue(wait_for(lambda: len(self.sessions[-1].asked) == before + 1, 10))
        self.assertIn("나머지 구간도 나눠 주세요", self.sessions[-1].asked[-1][0])

    def test_confirm_box_runs_only_after_the_button_and_uses_the_reviewer(self):
        win = self.window()
        self.switch_project(win, "SNP")
        self.propose(win, [self.apply_action(self.cands(3))])
        target = self.ns()["nodes"][0]["node_id"]
        self.propose(win, [{"action": "nodes.confirm", "args": {"node_ids": [target]}, "why": "확정"}], "S1 확정해 줘")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.confirm').length") or 0) == 1, 10), self.text(win)[-400:])
        self.assertFalse(next(n for n in self.ns()["nodes"] if n["node_id"] == target).get("confirmed"), "누르기 전에는 확정하지 않는다")
        self.assertTrue(self.click(win, "button[aria-label='실행']"))
        self.assertTrue(wait_for(lambda: bool(next(n for n in self.ns()["nodes"] if n["node_id"] == target).get("confirmed")), 10))
        node = next(n for n in self.ns()["nodes"] if n["node_id"] == target)
        self.assertEqual(node["confirmed"]["by"], "검토자A")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.confirm').length") or 0) == 0, 10))

    def test_decline_leaves_everything_as_it_was(self):
        win = self.window()
        self.switch_project(win, "SNP")
        self.propose(win, [self.apply_action(self.cands(3))])
        target = self.ns()["nodes"][0]["node_id"]
        self.propose(win, [{"action": "nodes.confirm", "args": {"node_ids": [target]}, "why": "확정"}], "S1 확정해 줘")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.confirm').length") or 0) == 1, 10))
        self.assertTrue(self.click(win, "button[aria-label='하지 않음']"))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.confirm').length") or 0) == 0, 10))
        self.assertFalse(next(n for n in self.ns()["nodes"] if n["node_id"] == target).get("confirmed"))

    def test_confirm_box_lists_the_real_targets_and_expands_many(self):
        win = self.window()
        self.switch_project(win, "SNP")
        self.propose(win, [self.apply_action(self.cands(3))])
        ids = [n["node_id"] for n in self.ns()["nodes"]]
        win.chat.new_conversation()                      # 앞 대화의 AI 묶음 -> 지우려면 사람 확인
        pump(0.4)
        remove = {"action": "nodes.apply", "args": {"set_rev": self.ns()["set_rev"], "ops": [{"op": "remove", "node_id": i} for i in ids]}, "why": "정리"}
        self.propose(win, [remove], "구간 정리해 줘")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.confirm').length") or 0) == 1, 10), self.text(win)[-400:])
        text = self.text(win)
        self.assertIn("대상 3개", text)
        for i in ids[:3]:
            self.assertIn(i, text, "지울 구간이 상자에 보인다")
        self.assertEqual(len(self.ns()["nodes"]), 3, "확인 전에는 지우지 않는다")

    def test_model_text_in_names_is_never_html(self):
        win = self.window()
        self.switch_project(win, "SNP")
        c = self.cands(1)[0]
        act = {"action": "nodes.apply", "args": {"set_rev": self.ns()["set_rev"],
               "ops": [{"op": "add", "cand_id": c["cand_id"], "name": "<img src=x onerror=window.__pwned=1>구간"}]}, "why": "x"}
        self.propose(win, [act])
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.actbox.applied').length") or 0) == 1, 10))
        self.assertEqual(self.js(win, "typeof window.__pwned"), "undefined")
        self.assertEqual(self.js(win, "document.querySelectorAll('.actbox img').length"), 0)


if __name__ == "__main__":
    unittest.main()
