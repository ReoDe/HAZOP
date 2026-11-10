"""④ AI 구간 검토 화면 흐름. 실제 구독·API 호출은 없다: 고정 응답(시험) 연결로 돌린다. 실행:
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_study_review_ui
"""

import json
import os
import shutil
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.test_app import tearDownModule  # noqa: E402,F401
from tests.test_project_graph import cont, sheet  # noqa: E402
from tests.test_study_project_ui import A, B, LONE_TEE, STUDY, write_drawing  # noqa: E402

AI_ROLE = 0x0100 + 3


class StudyReviewUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-study-review-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        sheets = {A: sheet(A, cont("C1", "TO %s\nL-1" % B), valve=True, extra=[LONE_TEE]),
                  B: sheet(B, cont("C1", "FROM %s\nL-1" % A), valve=True)}
        for dn, g in sheets.items():
            write_drawing(os.environ["HAZOP_WORK_ROOT"], dn, g)
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.settings = os.path.join(cls.tmp, "settings.json")

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        from hazop.study import nodes
        shutil.rmtree(nodes.store_dir(), ignore_errors=True)

    def open_study(self):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=self.settings, ask_reviewer=False, debug=True)  # 고정 응답(시험) 연결은 디버그 실행에서만
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(1440, 860)
        win.show()
        win.go(STUDY)
        scr = win.screens[STUDY]
        scr.select_drawing(A)
        self.assertEqual(scr.stack.currentIndex(), 1, scr.warn.label.text())
        return win, scr

    def fixed_answers(self, win, scr, answer):
        """지금 집합의 호출마다 고정 응답 파일을 만든다. answer(node, batch) -> 제안 dict."""
        from hazop.study import node_review as nr, providers
        folder = os.path.join(self.tmp, "fixed-%d" % time.monotonic_ns())
        os.makedirs(folder)
        ns, pg = scr.node_set, scr.graph
        view, adj = scr.ctx.view(ns), nr.adjacency(ns, pg)
        by_id = {n["node_id"]: n for n in ns["nodes"]}
        for b in nr.plan_batches(ns):
            req = nr.build_request(nr.build_context(b, ns, view, pg, adj))
            with open(os.path.join(folder, providers.fixed_key(req) + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"output": {"reviews": [answer(by_id[i], b) for i in b["node_ids"]]}}, fh, ensure_ascii=False)
        win.ai_prefs.set_fixed_dir(folder)
        win.ai_prefs.choose("fixed")
        return folder

    def run_review(self, scr, scope="all"):
        self.assertTrue(scr.review_ai(scope, ask=False))
        deadline = time.monotonic() + 20
        started = False
        while time.monotonic() < deadline:
            self.qapp.processEvents()
            started = started or scr.review_runner is not None
            if started and scr.review_runner is None:
                return
            time.sleep(0.02)
        self.fail("AI 구간 검토가 끝나지 않음")

    @staticmethod
    def review(node, verdict="ok", **kw):
        r = {"node_id": node["node_id"], "verdict": verdict, "merge_with": [], "split_off": [], "screen_to": None,
             "design_intent": "%s 설계 의도 초안" % node["node_id"], "reason": "시험 이유", "evidence": [node["node_id"]]}
        r.update(kw)
        return r

    def test_run_shows_chips_and_accept_reject_update_the_set_and_the_store(self):
        from hazop.app import explorer
        from hazop.study import node_review as nr, nodes
        win, scr = self.open_study()
        kept = [n for n in scr.node_set["nodes"] if nodes._status(n) != "excluded"]
        target = kept[0]
        self.fixed_answers(win, scr, lambda n, b: self.review(n, "screen_change", screen_to="low")
                           if n["node_id"] == target["node_id"] else self.review(n))
        self.run_review(scr)
        rows = {scr.node_list.item(i).data(0x0100): scr.node_list.item(i) for i in range(scr.node_list.count())}
        self.assertEqual(rows[target["node_id"]].data(AI_ROLE), "AI 제안")
        self.assertIn("AI 제안", scr.list_head.text())
        info = [t for g in explorer.study_module(win) for t, _tip in g.info]
        self.assertTrue(any(t.startswith("AI 제안 ") for t in info), info)

        scr.select_node(target["node_id"])
        self.assertIn("accept", scr.review_buttons)
        self.assertTrue(scr.review_buttons["accept"].isEnabled())
        self.assertTrue(scr.accept_review(scr.review_pending()[target["node_id"]]["id"]))
        self.assertEqual(nodes._status(scr._node(target["node_id"])), "low")
        self.assertEqual(scr.node_set["history"][-1]["op"], "ai_review_accept")
        saved = nr.load(scr.node_set.get("project_id"), scr.node_set["graph_id"])
        self.assertEqual([p["decision"] for p in saved["proposals"] if p["node_id"] == target["node_id"]], ["accepted"])
        self.assertTrue(os.path.isfile(nodes.store_path(scr.node_set.get("project_id"), scr.node_set["graph_id"])))

        other = next((n for n in kept[1:] if n["node_id"] in scr.review_pending()), None)
        if other is not None:
            pid = scr.review_pending()[other["node_id"]]["id"]
            self.assertTrue(scr.reject_review(pid, reason="근거 부족"))
            self.assertNotIn(other["node_id"], scr.review_pending())

    def test_edited_accept_keeps_the_set_and_records_the_intent_for_results(self):
        from hazop.app.screens.results import design_intent
        from hazop.study import nodes
        win, scr = self.open_study()
        target = next(n for n in scr.node_set["nodes"] if nodes._status(n) != "excluded")
        self.fixed_answers(win, scr, lambda n, b: self.review(n, "screen_change", screen_to="low"))
        self.run_review(scr, "all")
        pid = scr.review_pending()[target["node_id"]]["id"]
        before = nodes._status(scr._node(target["node_id"]))
        self.assertTrue(scr.edit_review(pid, edited={"verdict": "ok", "design_intent": "사람이 고친 의도"}))
        self.assertEqual(nodes._status(scr._node(target["node_id"])), before, "연산 없이 의도만 받음")
        self.assertEqual(design_intent(scr._node(target["node_id"]), scr.review_doc)[0], "사람이 고친 의도")

    def test_confirm_dialog_rows_show_calls_time_and_usage(self):
        from hazop.study import node_review as nr
        _win, scr = self.open_study()
        batches = nr.plan_batches(scr.node_set)
        lead, rows = scr.review_estimate_rows("subscription", batches)
        text = "\n".join(v for _n, v, _s in rows)
        self.assertIn("%d회" % len(batches), text)
        self.assertIn("7일 사용률", text)
        self.assertIn("초안", lead)


if __name__ == "__main__":
    unittest.main()
