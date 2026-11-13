"""초기사건 패널의 통합 시험(실제 새 화면 창 + 실제 인계 묶음 계산·초기사건 저장). 실행: python -m unittest tests.test_shell_ie_flow

패널이 열리면 후보·완전성 대조·품질 경고가 보이고, 규칙 초안 만들기가 그룹을 만들며, 그룹 상세와 확정 조건이 보이고, 인계 묶음 내보내기가 저장 대화상자 훅을 통해 돈다.
"""

import copy
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.ie import model  # noqa: E402
from hazop.ie import store as ie_store  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_ie_bundle import ie_sample  # noqa: E402
from tests.test_study_export import DEVS as XDEVS  # noqa: E402

pump, wait_for = W.pump, W.wait_for


class IePanelTest(W.ShellBase):
    def setUp(self):
        from hazop.app import project_ctx
        self.r, self.ns, self.pg = ie_sample()
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(XDEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)
        sn.save(self.ns)
        res.save(self.r, self.ns.get("project_id"))
        self.project = self.ns.get("project_id")
        path = ie_store.store_path(self.project)
        if os.path.exists(path):
            os.remove(path)

    def open_panel(self):
        win = self.window()
        win.engine.settings["project_id"] = self.project
        self.assertTrue(self.click(win, ".rail button", 3))
        self.assertTrue(wait_for(lambda: "묶이지 않은 후보" in self.text(win), 15), self.text(win)[-300:])
        return win

    def test_panel_shows_candidates_completeness_and_warnings(self):
        win = self.open_panel()
        text = self.text(win)
        self.assertIn("초기사건", text)
        self.assertIn("IEC-001", text)
        self.assertIn("그룹이 없습니다", text)
        self.assertTrue(self.click(win, "button[aria-label^='완전성 대조']"))
        self.assertTrue(wait_for(lambda: "주급수 완전 상실" in self.text(win), 10), self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label^='품질 경고']"))
        self.assertTrue(wait_for(lambda: "작동 방식 미확인" in self.text(win), 10), self.text(win)[-300:])

    def test_suggest_makes_a_draft_group_and_its_detail_explains_why_it_cannot_be_confirmed(self):
        win = self.open_panel()
        self.assertTrue(self.click(win, "button[aria-label='규칙 초안 만들기']"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "document.querySelector(\"[aria-label='그룹 목록'] .nrow-b\") !== null")), 15), self.text(win)[-300:])
        self.assertTrue(os.path.isfile(ie_store.store_path(self.project)))
        self.assertTrue(self.click(win, "[aria-label='그룹 목록'] .nrow-b"))
        self.assertTrue(wait_for(lambda: "확정할 수 없는 이유" in self.text(win), 10), self.text(win)[-400:])
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='그룹 확정']\").disabled"), True, "AI 초안 표제가 남아 확정 단추가 막힌다")
        self.assertIn("AI 초안", self.text(win))

    def test_export_bundle_uses_the_save_dialog_hook(self):
        win = self.open_panel()
        out = os.path.join(os.path.dirname(win.engine.settings_path), "ie-bundle.xlsx")
        win.engine.hooks["save_path"] = lambda kind, name: out
        self.assertTrue(self.click(win, "button[aria-label='초기사건 인계 묶음 내보내기']"))
        self.assertTrue(wait_for(lambda: os.path.isfile(out), 20))
        self.assertTrue(wait_for(lambda: "ie-bundle.xlsx" in self.text(win), 10))
        self.assertNotIn(os.path.dirname(out), self.text(win))

    def test_human_group_can_be_confirmed_from_the_panel(self):
        doc, fp = ie_store.load(self.project)
        doc = model.sync(doc, self.r, at="2026-11-13T01:00:00Z", node_set=self.ns)
        iec = model.iec_of(doc)[model.key_of(self.r["graph_id"], "c1")]
        doc, gid = model.create_group(doc, "주급수 상실", [iec], at="2026-11-13T01:00:00Z")
        ie_store.save(doc, expect=fp)
        win = self.open_panel()
        self.assertTrue(wait_for(lambda: gid in self.text(win), 10))
        self.assertTrue(self.click(win, "[aria-label='그룹 목록'] .nrow-b"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "document.querySelector(\"button[aria-label='그룹 확정']\") !== null")), 10))
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='그룹 확정']\").disabled"), False)
        self.assertTrue(self.click(win, "button[aria-label='그룹 확정']"))
        self.assertTrue(wait_for(lambda: bool(ie_store.load(self.project)[0]["groups"][gid].get("confirmation")), 10))
        self.assertEqual(ie_store.load(self.project)[0]["groups"][gid]["confirmation"]["by"], "검토자A")
        self.assertTrue(wait_for(lambda: "확정 풀기" in self.text(win), 10))


if __name__ == "__main__":
    unittest.main()
