"""셸(UIUX 개선명세 U-01 명령 팔레트, U-02 단축키, U-04 탐색기, U-05 레일, U-06 상태 표시줄, U-07 토스트,
U-14 관련 항목) 테스트. 실행: python -m unittest tests.test_shell

작업 루트·저장 루트·설정 파일은 임시 폴더다(자료저장소·출력 폴더를 건드리지 않음). 샘플 도면 SNP-M-102를 임시 작업 루트에
추출·그래프로 만들고, 프로젝트 검토구간 확정본과 분석 결과(고정 값)를 임시 저장 루트에 쓴 뒤 창을 연다.
ProjectExplorerTest는 SNP-M-101·102 두 장을 한 프로젝트로 잇는다. 네트워크·AI 호출 없음.
"""

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from PySide6.QtCore import Qt  # noqa: E402

from tests.test_app import build_temp_drawing, pump, tearDownModule  # noqa: E402,F401

STUDY, RESULTS = 5, 6


class PaletteSearchTest(unittest.TestCase):
    def items(self):
        from hazop.app.palette import Item
        return [Item("command", "이동: ⑤ 분석 결과", keys="Ctrl+5"), Item("command", "구간 확정", keys="Ctrl+Enter"),
                Item("node", "S1 RC-PZ01 가압기"), Item("node", "S2 배관 RC-L010"),
                Item("component", "RC-PZ01", "equipment"), Item("component", "RC-PT110", "instrument"),
                Item("cell", "S1 × 유량 증가 RC-PZ01 가압기", "위험 4")]

    def test_fuzzy_order_and_misses(self):
        from hazop.app.palette import fuzzy_score
        self.assertIsNone(fuzzy_score("xyz", "RC-PZ01"))
        self.assertIsNotNone(fuzzy_score("rcpz", "RC-PZ01"))      # 글자 순서만 맞으면 찾음(구분자 무시)
        self.assertGreater(fuzzy_score("pz01", "RC-PZ01"), fuzzy_score("pz01", "RC-P-Z-0-1-LONGER"))  # 붙은 글자 우선

    def test_prefixes_limit_kind(self):
        from hazop.app.palette import search
        kinds = lambda q: {k for k, its in search(self.items(), q) if its}  # noqa: E731
        self.assertEqual(kinds("#S1"), {"node"})
        self.assertEqual(kinds("@RC"), {"component"})
        self.assertEqual(kinds(">확정"), {"command"})
        self.assertEqual(kinds("PZ01"), {"component", "node", "cell"})
        groups = dict(search(self.items(), "PZ01"))
        self.assertEqual(groups["component"][0].label, "RC-PZ01")

    def test_empty_query_shows_recent_then_commands(self):
        from hazop.app.palette import search
        items = self.items()
        groups = search(items, "", recent=[items[3].ident()])
        self.assertEqual([k for k, _ in groups], ["recent", "command"])
        self.assertEqual(groups[0][1][0].label, "S2 배관 RC-L010")


def fake_results(node_set, deviations, failed, scored):
    """칸 failed는 AI 실행 실패, 칸 scored는 위험 4·미검토 1 항목 하나."""
    from hazop.study import results as res
    doc = res.empty_results(node_set, deviations)
    for c in doc["cells"]:
        key = (c["node_id"], c["deviation_id"])
        if key == failed:
            c["ai_run"] = {"status": "failed", "error": "시간 초과"}
        elif key == scored:
            c["state"] = "analyzed"
            c["ai_run"] = {"status": "ok"}
            c["entries"] = [{"entry_id": "e1", "origin": "ai_draft", "status": "proposed", "cause": "원인",
                             "consequence": "결과", "safeguards": [], "recommendation": "제어 논리 확인",
                             "severity": 2, "frequency": 2, "risk": 4,
                             "history": [{"at": "2026-11-07T00:00:00Z", "op": "status", "from": "proposed",
                                          "to": "revised"}]}]
    return doc


class ShellTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-shell-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        out_dir, cls.graph = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        cls.drawing = os.path.basename(out_dir)
        from hazop.app import project_ctx
        from hazop.study import nodes
        from hazop.study import results as res
        pg = project_ctx.load(cls.drawing).pg
        ns = nodes.confirm(nodes.propose(pg), pg, "검토자A")
        nodes.save(ns)
        cls.node_set = ns
        devs = res.load_deviations()
        n0, n1 = ns["nodes"][0]["node_id"], ns["nodes"][1]["node_id"]
        cls.failed = (n0, devs[1]["deviation_id"])
        cls.scored = (n0, devs[2]["deviation_id"])
        cls.other = (n1, devs[0]["deviation_id"])
        res.save(fake_results(ns, devs, cls.failed, cls.scored), ns.get("project_id"))
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

    def window(self):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=self.settings, ask_reviewer=False)
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(1366, 768)
        win.show()
        pump(win, 0.05)
        return win

    def press(self, win, seq):
        win.shortcuts[seq].activated.emit()
        pump(win, 0.02)

    def test_stage_shortcuts_and_history(self):
        win = self.window()
        for seq in ("Ctrl+P", "Ctrl+Z", "Ctrl+Alt+B", "Ctrl+Shift+E", "Alt+Left", "Alt+Right", "?", "F1"):
            self.assertIn(seq, win.shortcuts)
        self.press(win, "Ctrl+4")
        self.assertEqual(win.stack.currentIndex(), STUDY)
        self.press(win, "Ctrl+2")
        self.assertEqual(win.stack.currentIndex(), 1)
        self.press(win, "Alt+Left")
        self.assertEqual(win.stack.currentIndex(), STUDY, "뒤로")
        self.press(win, "Alt+Right")
        self.assertEqual(win.stack.currentIndex(), 1, "앞으로")
        rows = dict(win.shortcut_rows())
        self.assertIn("Ctrl+P", rows)

    def test_rail_keeps_numbers_with_done_badge(self):
        win = self.window()
        win.go(STUDY)
        b = win.step_buttons[STUDY]
        self.assertEqual(b.text(), "구간")
        self.assertTrue(b.property("done"), "확정 구간이 있으면 ④ 완료")
        self.assertEqual(b.property("state"), "now")
        self.assertFalse(b.icon().isNull(), "번호 원 아이콘")

    def test_explorer_follows_drawing_with_counts_and_hints(self):
        win = self.window()
        win.go(RESULTS)
        self.assertEqual(win.drawing, self.drawing)
        groups = {win.explorer.topLevelItem(i).text(0): win.explorer.topLevelItem(i)
                  for i in range(win.explorer.topLevelItemCount())}
        study = next(g for name, g in groups.items() if name.startswith("검토구간 · "))
        self.assertEqual(study.text(1), str(len(self.node_set["nodes"])))
        self.assertEqual(study.child(0).text(0), "⑤ 결과 행렬 열기", "결과 바로가기는 구간이 많아도 보이게 맨 위")
        first = study.child(1)
        self.assertEqual(first.text(1), "미1·실패1", "미검토 수와 AI 실패 칸 수")
        src = groups["자료"].child(0)
        self.assertEqual(src.text(0), "%s · 등록 없이 추출" % self.drawing, "등록 없이 추출된 도면도 자료에 출처와 함께")
        self.assertEqual(groups["자료"].text(1), "1")
        self.assertEqual(groups["지식그래프"].child(0).flags(), Qt.NoItemFlags, "빈 그룹은 누를 수 없는 안내 한 줄")
        link = study.child(0)
        self.assertEqual(link.text(0), "⑤ 결과 행렬 열기", "결과로 들어가는 입구")
        self.assertEqual(groups["권고"].text(1), "1")
        win.explorer_filter.setText("zzzz")
        self.assertEqual(study.text(1), "0")
        self.assertTrue(first.isHidden())
        win.explorer_filter.setText("")
        self.assertIn("미검토 1", first.toolTip(0))
        nid = self.node_set["nodes"][0]["node_id"]
        win._explorer_clicked(first)
        self.assertEqual(win.stack.currentIndex(), RESULTS, "⑤에서는 결과 행렬의 그 행")
        self.assertEqual(win.screens[RESULTS].selected_node_id(), nid)
        from unittest import mock
        from PySide6.QtWidgets import QApplication
        with mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.AltModifier):
            win._explorer_clicked(first)
        self.assertEqual(win.stack.currentIndex(), STUDY, "Alt+누르기는 ④ 구간")
        self.assertEqual(win.screens[STUDY].current_node_id(), nid)
        win._explorer_clicked(link)
        self.assertEqual(win.stack.currentIndex(), RESULTS)
        win._explorer_clicked(src)
        self.assertEqual(win.stack.currentIndex(), 1, "자료의 추출 도면 → ② 도면")

    def test_palette_finds_and_opens_cell(self):
        win = self.window()
        win.go(RESULTS)
        dlg = win.open_palette("#")
        self.assertEqual({it.kind for it in dlg.results()}, {"node"})
        dev = win.index().deviation(self.scored[1])
        dlg.edit.setText("%s × %s" % (self.scored[0], dev["label"]))
        hit = dlg.results()[0]
        self.assertEqual((hit.kind, hit.detail), ("cell", "위험 4 · 미검토 1"))
        dlg.activate(dlg.list.currentItem())
        pump(win, 0.05)
        self.assertEqual(win.screens[RESULTS].cell, self.scored)
        self.assertEqual(win.recent[0], hit.ident())
        fail = [it for it in win.palette_items() if it.kind == "cell" and it.detail == "! 실패"]
        self.assertEqual(len(fail), 1)

    def test_related_panel_links_cell_component_and_other_cells(self):
        from hazop.app import related
        win = self.window()
        win.go(RESULTS)
        self.assertTrue(win.related.isVisible(), "⑤는 관련 항목을 펴 둔다")
        node = self.node_set["nodes"][0]
        win.set_selection({"kind": "cell", "drawing": self.drawing, "node_id": self.failed[0],
                           "deviation_id": self.failed[1]})
        counts = win.related.counts()
        self.assertEqual(counts["구성요소"], len(node["members"]))
        self.assertEqual(counts["같은 구성요소를 쓰는 다른 칸"], 1, "결과가 있는 다른 칸만(실패 칸 자신은 뺌)")
        rows = dict(related.related(win.index(), win.selection))
        self.assertEqual(rows["같은 구성요소를 쓰는 다른 칸"][0].target["deviation_id"], self.scored[1])
        win.set_selection({"kind": "cell", "drawing": self.drawing, "node_id": self.scored[0],
                           "deviation_id": self.scored[1]})
        rows = dict(related.related(win.index(), win.selection))
        self.assertEqual(rows["같은 구성요소를 쓰는 다른 칸"][0].detail, "! 실패")
        self.assertEqual(rows["변경 이력"][0].text, "제안 → 수정")
        comp = rows["구성요소"][0].target
        self.assertTrue(win.open_target(comp))
        self.assertEqual(win.stack.currentIndex(), 1, "구성요소는 ② 도면에서 연다")
        self.assertEqual(win.selection["entity_id"], comp["entity_id"])
        self.assertFalse(win.related.isVisible(), "②는 관련 항목 기본 접힘")
        self.press(win, "Ctrl+Alt+B")
        self.assertTrue(win.related.isVisible())
        self.assertIn(win.related.counts()["도면 위치"], (1,))

    def test_go_moves_focus_into_the_screen(self):
        win = self.window()
        for index in (RESULTS, 0, STUDY):
            win.go(index)
            pump(win, 0.02)
            scr, w = win.screens[index], win.focusWidget()
            self.assertTrue(w is scr or scr.isAncestorOf(w), "%d: %r" % (index, w))

    def test_toast_undo_with_ctrl_z(self):
        win = self.window()
        done = []
        win.toast("S1을 병합했습니다", undo=lambda: done.append(1))
        self.assertTrue(win.toast_box.isVisible())
        self.assertTrue(win.toast_box.undo_btn.isVisible())
        self.press(win, "Ctrl+Z")
        self.assertEqual(done, [1])
        self.assertFalse(win.toast_box.isVisible())
        self.assertFalse(win.undo() and done == [1, 1], "실행 취소는 한 번만")
        win.toast("S2를 병합했습니다", undo=lambda: done.append(2))
        win.go(1)
        self.assertFalse(win.undo() is True and 2 in done, "화면을 옮겨 사라진 토스트의 실행 취소는 남지 않음")
        self.assertNotIn(2, done)
        win.toast("등록했습니다")
        self.assertFalse(win.toast_box.undo_btn.isVisible(), "되돌릴 수 없는 동작은 실행 취소 링크 없음")

    def test_status_bar_hides_empty_values(self):
        win = self.window()
        win.go(0)
        self.assertFalse(win.chip_valid.isVisible(), "열린 실행이 없으면 결과 검증 칩 숨김")
        self.assertFalse(win.saved_label.isVisible())
        win.go(RESULTS)
        self.assertIn("미검토 1", win.count_label.text())
        self.assertIn("실패 1", win.count_label.text())
        self.assertNotIn("열린 구간 없음", win.where_label.full_text)
        self.assertTrue(win.where_label.full_text.startswith("⑤ 분석 결과"))

    def test_tabs_keep_screen_and_selection(self):
        """U-03 탭: 팔레트 Ctrl+Enter(new_tab)로 연 탭은 따로 기억되고, 탭을 바꾸면 그 화면과 칸이 다시 열린다."""
        win = self.window()
        win.go(STUDY)
        self.assertEqual(win.tab_bar.count(), 1)
        self.assertTrue(win.tab_bar.tabText(0).startswith("구간"))
        cell = {"kind": "cell", "drawing": self.drawing, "node_id": self.scored[0], "deviation_id": self.scored[1]}
        self.assertTrue(win.open_target(cell, new_tab=True))
        self.assertEqual(win.tab_bar.count(), 2)
        self.assertEqual((win.tab_bar.currentIndex(), win.stack.currentIndex()), (1, RESULTS))
        self.assertIn(self.scored[0], win.tab_bar.tabText(1))
        win.tab_bar.setCurrentIndex(0)
        pump(win, 0.02)
        self.assertEqual(win.stack.currentIndex(), STUDY, "첫 탭 = ④")
        win.screens[RESULTS].cell = None
        self.press(win, "Ctrl+Tab")
        self.assertEqual(win.stack.currentIndex(), RESULTS)
        self.assertEqual(win.screens[RESULTS].cell, self.scored, "탭으로 돌아오면 그 칸 워크시트를 다시 연다")
        self.press(win, "Ctrl+W")
        self.assertEqual((win.tab_bar.count(), win.stack.currentIndex()), (1, STUDY))
        self.assertFalse(win.close_tab(0), "마지막 탭은 닫지 않음")
        self.press(win, "Ctrl+T")
        self.assertEqual(win.tab_bar.count(), 2)

    def test_tab_and_split_ask_before_dropping_unsaved_drawing_edits(self):
        """같은 ② 화면·다른 도면 탭으로 옮기거나 분할 오른쪽 ②가 있을 때도 저장 안 한 수정을 묻는다(거절하면 그대로)."""
        from unittest import mock
        win = self.window()
        win.go(1)
        win.new_tab()
        win.tabs[1]["drawing"] = "다른-도면"
        viewer = win.screens[1]
        with mock.patch.object(viewer, "can_leave", return_value=False) as asked:
            win.tab_bar.setCurrentIndex(0)
            win._tab_activated(1)
            self.assertTrue(asked.called, "도면이 다른 탭이면 같은 화면이어도 묻는다")
            self.assertEqual(win.drawing, self.drawing, "거절하면 지금 도면 그대로")
        win.resize(1920, 1080)
        win.go(0)
        win.toggle_split(1)
        self.assertEqual(win.split_index, 1)
        with mock.patch.object(viewer, "can_leave", return_value=False):
            self.assertFalse(win.can_leave(), "분할 오른쪽 ②의 저장 안 한 수정도 묻는다")
        win.unsplit()

    def test_split_study_and_results_side_by_side(self):
        """U-03 분할: ④ 왼쪽 + ⑤ 오른쪽. 도면 신호는 ④가 받고, 오른쪽 화면으로 이동하면 분할을 푼다."""
        win = self.window()
        win.go(STUDY)
        self.press(win, "Ctrl+\\")
        self.assertIsNone(win.split_index, "1366에서는 두 화면 최소 폭이 모자라 나누지 않음(창을 넓히지 않음)")
        self.assertEqual(win.width(), 1366)
        win.resize(1920, 1080)
        pump(win, 0.05)
        self.press(win, "Ctrl+\\")
        res = win.screens[RESULTS]
        self.assertEqual(win.split_index, RESULTS)
        self.assertTrue(res.isVisible() and win.screens[STUDY].isVisible(), "두 화면이 함께 보임")
        self.assertIs(res.parentWidget(), win.right_pane)
        self.assertIs(win.canvas_screen(), win.screens[STUDY])
        self.assertTrue(res.stack.currentIndex() == 1 and res.node_set, "오른쪽 ⑤도 같은 도면 결과를 연다")
        win.go(RESULTS)
        self.assertIsNone(win.split_index)
        self.assertEqual(win.stack.currentWidget(), res, "분할을 풀고 원래 자리로")
        self.assertEqual(win.stack.count(), len(win.screens))
        win.go(1)
        self.assertFalse(win.toggle_split(STUDY), "도면 화면 둘은 나누지 않음")
        self.assertIsNone(win.split_index)


class ProjectExplorerTest(unittest.TestCase):
    """탐색기 검토구간: 기본은 프로젝트 전체 구간, 도면 필터는 그 도면을 지나는 구간(걸친 구간 포함)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-project-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        cls.names = {dn: os.path.basename(build_temp_drawing(os.environ["HAZOP_WORK_ROOT"], dn)[0])
                     for dn in ("SNP-M-101", "SNP-M-102")}
        from hazop.app import project_ctx
        from hazop.study import nodes
        ctx = project_ctx.load(cls.names["SNP-M-102"])
        ns = nodes.confirm(nodes.propose(ctx.pg), ctx.pg, "검토자A")
        nodes.save(ns)
        cls.view = ctx.view(ns)
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.settings = os.path.join(cls.tmp, "settings.json")

    tearDownClass = classmethod(ShellTest.tearDownClass.__func__)
    window = ShellTest.window

    def study_group(self, win):
        return next(win.explorer.topLevelItem(i) for i in range(win.explorer.topLevelItemCount())
                    if win.explorer.topLevelItem(i).text(0).startswith("검토구간"))

    def test_project_nodes_by_default_and_drawing_filter(self):
        from hazop.app import project_ctx
        from hazop.study import span
        win = self.window()
        win.set_drawing(self.names["SNP-M-102"])
        grp = self.study_group(win)
        self.assertEqual(grp.text(0), "검토구간 · 프로젝트 SNP-SAMPLE")
        labels = [project_ctx.node_label(n) for n in self.view["nodes"]]
        nodes = [grp.child(i) for i in range(grp.childCount()) if grp.child(i).data(0, Qt.UserRole + 1) is None]
        self.assertEqual([c.text(0) for c in nodes], labels, "어느 도면에서 보든 S1…Sn 전체")
        self.assertEqual(grp.text(1), str(len(labels)))
        spanning = [n for n in self.view["nodes"] if n["spans_drawings"]]
        self.assertTrue(spanning and all(project_ctx.node_label(n).endswith("⇄") for n in spanning))
        self.assertIn("프로젝트 100% · 이 도면 100%", grp.toolTip(0))
        box = win.explorer_drawing
        self.assertEqual(box.accessibleName(), "탐색기 도면 필터")
        self.assertEqual([box.itemText(i) for i in range(box.count())], ["모든 도면", "SNP-M-101", "SNP-M-102"])
        box.setCurrentIndex(box.findData("SNP-M-101"))
        grp = self.study_group(win)
        on101 = span.nodes_on_drawing(self.view, "SNP-M-101")
        self.assertEqual(grp.text(0), "검토구간 · SNP-M-101")
        self.assertEqual([c.data(0, Qt.UserRole)[1] for c in (grp.child(i) for i in range(grp.childCount()))
                          if c.data(0, Qt.UserRole + 1) is None], [n["node_id"] for n in on101])
        self.assertTrue(any(n["spans_drawings"] for n in on101), "걸친 구간도 그 도면 필터에 남는다")
        self.assertLess(len(on101), len(labels))
        box.setCurrentIndex(0)
        self.assertEqual(self.study_group(win).text(1), str(len(labels)))

    def test_node_of_another_drawing_opens_where_it_exists(self):
        only101 = next(n for n in self.view["nodes"] if n["drawings"] == ["SNP-M-101"])
        win = self.window()
        win.set_drawing(self.names["SNP-M-102"])
        grp = self.study_group(win)
        item = next(grp.child(i) for i in range(grp.childCount())
                    if grp.child(i).data(0, Qt.UserRole) == (STUDY, only101["node_id"]))
        win._explorer_clicked(item)
        self.assertEqual(win.stack.currentIndex(), STUDY)
        self.assertEqual(win.drawing, self.names["SNP-M-101"], "그 구간이 있는 도면에서 연다")
        self.assertEqual(win.screens[STUDY].current_node_id(), only101["node_id"])


if __name__ == "__main__":
    unittest.main()
