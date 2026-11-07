"""④ 검토구간·⑤ 분석 결과 화면 테스트 (stage3-spec). 실행: python -m unittest tests.test_study_screens

작업 루트·저장 루트·설정 파일은 임시 폴더(자료저장소·출력 폴더를 건드리지 않음). 샘플 도면 SNP-M-102를 임시 작업 루트에
추출·그래프로 만든 뒤 화면을 실제로 조작한다. 네트워크·AI 호출 없음.
"""

import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from PySide6.QtCore import Qt  # noqa: E402

from tests.test_app import build_temp_drawing, pump, tearDownModule, wait_for  # noqa: E402,F401

STUDY, RESULTS = 5, 6


class StudyScreensTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-study-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        out_dir, cls.graph = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        cls.drawing = os.path.basename(out_dir)
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

    def window(self):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=self.settings, ask_reviewer=False)
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(1440, 860)
        win.show()
        win.set_reviewer_name("검토자A")
        return win

    def open_study(self, win):
        win.go(STUDY)
        scr = win.screens[STUDY]
        scr.select_drawing(self.drawing)
        self.assertEqual(scr.combo.currentText(), self.drawing)
        return scr

    def js(self, win, code):
        out = []
        win.webview.page().runJavaScript(code, 0, out.append)
        self.assertTrue(wait_for(lambda: out), "JS 응답 없음: %s" % code)
        return out[0]

    @staticmethod
    def sole_member(scr):
        """구간 하나에만 든 구성요소가 2개 이상인 구간과 그 구성요소."""
        from hazop.study import nodes
        for n in scr.node_set["nodes"]:
            only = [m for m in n["members"] if nodes.nodes_of(scr.node_set, m) == [n["node_id"]]]
            if len(n["members"]) >= 2 and only:
                return n["node_id"], only[0]
        raise AssertionError("빼 볼 구성요소가 없음")

    def select_members(self, scr, ids):
        for i in range(scr.member_list.count()):
            it = scr.member_list.item(i)
            it.setSelected(it.data(Qt.UserRole) in ids)

    def test_propose_edit_confirm_persist_and_results(self):
        win = self.window()
        win.go(RESULTS)
        self.assertEqual(win.screens[RESULTS].stack.currentIndex(), 0, "확정 전 ⑤는 빈 화면 안내")
        scr = self.open_study(win)
        total = len(self.graph["nodes"])
        cov = scr._coverage()
        self.assertEqual((cov["covered"], cov["total"]), (total, total), "제안은 모든 구성요소를 덮음")
        self.assertFalse(scr.saved, "처음 제안은 저장 전")
        self.assertIn("구성요소 <b>%d</b>" % total, scr.kpi.text())
        self.assertTrue(scr.confirm_btn.isEnabled())
        self.assertEqual([k for _, k in scr.explorer_items()], [n["node_id"] for n in scr.node_set["nodes"]])

        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "④ 도면 브리지 ready 없음")
        pump(seconds=0.3)
        painted = self.js(win, "document.querySelectorAll('[data-hz-seg^=\"S\"]').length")
        self.assertGreater(painted, 0, "도면에 구간 색이 칠해짐")
        badges = json.loads(self.js(win, "JSON.stringify(Array.prototype.map.call("
                                         "document.querySelectorAll('.hz-seg-badge text'), function (t) { return t.textContent; }))"))
        self.assertEqual(sorted(badges), sorted(n["node_id"] for n in scr.node_set["nodes"]), "구간마다 S 번호 꼬리표")

        count = scr.node_list.count()
        first_two = [n["node_id"] for n in scr.node_set["nodes"][:2]]
        scr.set_checked(first_two)
        self.assertTrue(scr.merge_btn.isEnabled())
        scr.merge_btn.click()
        self.assertEqual(scr.node_list.count(), count - 1)
        self.assertTrue(scr.saved, "편집 뒤 저장")

        big = next(n for n in scr.node_set["nodes"] if len(n["members"]) >= 2)
        scr.select_node(big["node_id"])
        self.select_members(scr, big["members"][:1])
        self.assertTrue(scr.split_btn.isEnabled())
        scr.split_btn.click()
        self.assertEqual(scr.node_list.count(), count)
        self.assertEqual(scr.current_node()["members"], big["members"][:1], "새 구간 = 선택한 구성요소")

        node_id, eid = self.sole_member(scr)
        scr.select_node(node_id)
        self.select_members(scr, [eid])
        scr.remove_btn.click()
        self.assertFalse(scr.confirm_btn.isEnabled(), "미포함이 있으면 확정 불가")
        self.assertEqual([scr.uncovered_list.item(i).data(Qt.UserRole) for i in range(scr.uncovered_list.count())], [eid])
        scr.on_node({"entity_id": eid, "local_id": None})
        self.assertIn("미포함", scr.owner_list.item(0).text())

        scr.select_node(node_id)
        scr.uncovered_list.item(0).setSelected(True)
        scr.add_btn.click()
        self.assertEqual(scr.uncovered_list.count(), 0)
        self.assertTrue(scr.confirm_btn.isEnabled())
        self.assertTrue(scr.rename_current("가압기 검토구간"))
        scr.confirm_btn.click()
        self.assertEqual(scr.node_set["status"], "confirmed")
        self.assertEqual(scr.node_set["confirmed_by"], "검토자A")
        self.assertFalse(scr.merge_btn.isEnabled())
        self.assertTrue(win.step_buttons[STUDY].text().startswith("✓"), "레일 ④ 완료 표시")
        expected = scr.node_set["nodes"]

        win2 = self.window()
        scr2 = self.open_study(win2)
        self.assertEqual(scr2.node_set["status"], "confirmed", "재시작 후에도 확정 유지")
        self.assertEqual(scr2.node_set["nodes"], expected)
        self.assertIn("가압기 검토구간", [scr2.node_list.item(i).text().split(" · ")[0]
                                      for i in range(scr2.node_list.count())])

        member = expected[-1]["members"][0]
        scr2.on_node({"entity_id": member, "local_id": None})
        owners = [scr2.owner_list.item(i).data(Qt.UserRole) for i in range(scr2.owner_list.count())]
        self.assertIn(expected[-1]["node_id"], owners)
        scr2.owner_list.itemClicked.emit(scr2.owner_list.item(owners.index(expected[-1]["node_id"])))
        self.assertEqual(scr2.current_node_id(), expected[-1]["node_id"])

        scr2.to_results_btn.click()
        self.assertEqual(win2.stack.currentIndex(), RESULTS)
        res = win2.screens[RESULTS]
        self.assertEqual(res.stack.currentIndex(), 1)
        self.assertEqual(res.matrix.rowCount(), len(expected))
        self.assertEqual(res.matrix.columnCount(), 44)
        self.assertEqual(res.matrix.item(0, 0).text(), "분석 전")
        self.assertEqual(res.cell[0], expected[-1]["node_id"], "④에서 고른 구간의 워크시트")
        res.matrix.cellClicked.emit(0, 3)
        self.assertEqual(res.cell, (expected[0]["node_id"], res.deviations[3]["deviation_id"]))
        self.assertEqual(res.sheet_stack.currentIndex(), 1)
        self.assertFalse(res.ai_banner.isHidden())
        self.assertIn("AI 결과는 모두 초안", res.ai_banner_label.text())
        self.assertIn("항목 없음", res.table.item(0, 0).text())

        doc = json.loads(json.dumps(res.results))
        cell = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == res.cell)
        cell["state"] = "analyzed"
        cell["entries"] = [{"entry_id": "E1", "cause": "원인 예", "consequence": "결과 예", "safeguards": ["보호 예"],
                            "recommendation": "권고 예", "risk": 4, "origin": "ai_draft", "status": "proposed",
                            "ai_basis": {"kg_paths": [[member]], "sources": [{"doc": "DOC-1", "where": "p.1"}]}}]
        res.set_results(doc)
        self.assertEqual(res.table.item(0, 6).text(), "AI 초안 · 제안")
        self.assertIn("DOC-1", res.table.item(0, 5).text())
        self.assertEqual(res.matrix.item(0, 3).text(), "1건\n위험 4\n미검토 1")
        res.legacy_btn.click()
        self.assertEqual(win2.stack.currentIndex(), 2)

    def test_stale_saved_set_blocks_confirm(self):
        from hazop.study import nodes
        ns = nodes.rename(nodes.propose(self.graph), "S1", "옛 판")
        ns["graph_version"] = "v-old"
        nodes.save(ns)
        win = self.window()
        scr = self.open_study(win)
        self.assertFalse(scr.stale.isHidden(), "그래프 판이 바뀌면 경고")
        self.assertFalse(scr.confirm_btn.isEnabled())
        self.assertTrue(scr.repropose(ask=False))
        self.assertTrue(scr.stale.isHidden())
        self.assertTrue(scr.confirm_btn.isEnabled())
        self.assertEqual(nodes.load(self.graph)["graph_version"], self.graph["graph_version"], "다시 제안은 저장됨")

    def test_confirm_not_shown_when_save_fails(self):
        from unittest import mock
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        with mock.patch.object(nodes, "save", side_effect=OSError(28, "디스크 부족")):
            self.assertFalse(scr.confirm("검토자A"))
        self.assertEqual(scr.node_set["status"], "proposed", "저장 못 하면 확정으로 보이지 않음")
        self.assertIsNone(nodes.load(self.graph))

    def test_results_refuse_stale_confirmed_set(self):
        from hazop.study import nodes
        ns = nodes.confirm(nodes.propose(self.graph), self.graph, "검토자A")
        ns["graph_version"] = "v-old"
        nodes.save(ns)
        win = self.window()
        win.go(RESULTS)
        res = win.screens[RESULTS]
        res._load()
        self.assertEqual(res.stack.currentIndex(), 0, "옛 도면 판의 확정본은 결과 셸에 쓰지 않음")
        self.assertIn("다시 확정", res.empty.text())


if __name__ == "__main__":
    unittest.main()
