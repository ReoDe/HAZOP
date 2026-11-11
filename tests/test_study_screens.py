"""④ 검토구간·⑤ 분석 결과 화면 테스트 (stage3-spec). 실행: python -m unittest tests.test_study_screens

작업 루트·저장 루트·설정 파일은 임시 폴더(store·출력 폴더를 건드리지 않음). 샘플 도면 SNP-M-102를 임시 작업 루트에
추출·그래프로 만든 뒤 화면을 실제로 조작한다. 네트워크·AI 호출 없음.
"""

import codecs
import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from PySide6.QtCore import Qt  # noqa: E402

from hazop import paths  # noqa: E402
from tests.test_app import build_temp_drawing, pump, tearDownModule, wait_for  # noqa: E402,F401

STUDY, RESULTS = 5, 6


def nodes_load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


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

    def pg(self):
        """④가 구간을 다루는 기준 = 이 도면이 든 프로젝트 그래프(도면 한 장)."""
        from hazop.graph import project
        return project.load(project.project_id_of(self.graph))

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
        self.assertTrue(scr.owner_list.isHidden() and not scr.owner_hint.isHidden(), "속한 구간 없음은 빈 상자 대신 안내")
        self.assertIn("미포함", scr.owner_hint.text())
        self.assertEqual(scr.tabs.currentIndex(), 1, "미포함 구성요소를 누르면 미포함 탭")

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
        self.assertTrue(win.step_buttons[STUDY].property("done"), "레일 ④ 완료 표시")
        expected = scr.node_set["nodes"]

        win2 = self.window()
        scr2 = self.open_study(win2)
        self.assertEqual(scr2.node_set["status"], "confirmed", "재시작 후에도 확정 유지")
        self.assertEqual(scr2.node_set["nodes"], expected)
        self.assertTrue(any("가압기 검토구간" in scr2.node_list.item(i).text() for i in range(scr2.node_list.count())))

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
        self.assertFalse(res.ai_chip.isHidden())
        self.assertIn("AI 결과는 모두 초안", res.ai_chip.text())
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
        self.assertEqual(res.draft_chip.text(), "AI 초안 1건")
        dict((label, fn) for label, _k, fn in res.commands())["이전 고정 응답 분석 열기"]()
        self.assertEqual(win2.stack.currentIndex(), 2)

    def test_stale_saved_set_blocks_confirm(self):
        from hazop.study import nodes
        pg = self.pg()
        ns = nodes.rename(nodes.propose(pg), "S1", "옛 판")
        ns["graph_version"] = "v-old"
        nodes.save(ns)
        win = self.window()
        scr = self.open_study(win)
        self.assertFalse(scr.stale.isHidden(), "그래프 판이 바뀌면 경고")
        self.assertFalse(scr.confirm_btn.isEnabled())
        self.assertTrue(scr.repropose(ask=False))
        self.assertTrue(scr.stale.isHidden())
        self.assertTrue(scr.confirm_btn.isEnabled())
        self.assertEqual(nodes.load(pg)["graph_version"], pg["graph_version"], "다시 제안은 저장됨")

    def test_confirm_not_shown_when_save_fails(self):
        from unittest import mock
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        with mock.patch("os.replace", side_effect=OSError(28, "디스크 부족")):
            self.assertFalse(scr.confirm("검토자A"))
        self.assertEqual(scr.node_set["status"], "proposed", "저장 못 하면 확정으로 보이지 않음")
        self.assertIsNone(nodes.load(self.pg()))

    def test_all_segments_visible_at_1366(self):
        """구간 10개(제안 5개를 나눠 만든 집합)가 1366×768에서 스크롤 없이 보인다(U-18 완료 기준)."""
        from hazop.study import nodes
        ns = nodes.propose(self.pg())
        while len(ns["nodes"]) < 10:
            big = max(ns["nodes"], key=lambda n: len(n["members"]))
            ns = nodes.split(ns, big["node_id"], big["members"][:1])
        nodes.save(ns)
        win = self.window()
        win.resize(1366, 768)
        scr = self.open_study(win)
        pump(seconds=0.3)
        lst = scr.node_list
        self.assertEqual(lst.count(), 10)
        self.assertEqual(scr.panel.width(), 273, "패널 폭 = clamp(264, 20vw, 340)")
        self.assertEqual(lst.visualItemRect(lst.item(0)).height(), 24, "행 높이 24px")
        last = lst.visualItemRect(lst.item(lst.count() - 1))
        self.assertLessEqual(last.bottom(), lst.viewport().height(), "구간 10개가 스크롤 없이 모두 보임")
        self.assertIn("제안", scr.list_head.text(), "확정·제안 상태는 목록 머리에 한 번")
        self.assertNotIn("제안", lst.item(0).text())

    def test_shortcuts_merge_rename_confirm(self):
        from unittest import mock
        from PySide6.QtTest import QTest
        win = self.window()
        scr = self.open_study(win)
        win.activateWindow()
        scr.node_list.setFocus()
        pump(seconds=0.2)
        count = scr.node_list.count()
        scr.set_checked([n["node_id"] for n in scr.node_set["nodes"][:2]])
        QTest.keyClick(scr.node_list, Qt.Key_M)
        self.assertEqual(scr.node_list.count(), count - 1, "M = 병합")
        nid = scr.current_node_id()
        with mock.patch("hazop.app.screens.study.QInputDialog.getText", return_value=("단축키 이름", True)):
            QTest.keyClick(scr.node_list, Qt.Key_F2)
        self.assertEqual(scr._node(nid)["name"], "단축키 이름", "F2 = 이름 바꾸기")
        QTest.keyClick(scr.node_list, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual(scr.node_set["status"], "confirmed", "Ctrl+Enter = 구간 확정")
        self.assertEqual([c[0] for c in scr.commands()],
                         ["전체 보기", "병합", "분할", "이름 바꾸기", "구간 확정", "확정 해제", "다시 제안", "⑤ 결과에서 보기",
                          "스크리닝 제외에서 꺼내기", "붙인 조각 떼기", "스크리닝 제외로 옮기기", "스크리닝 제외 구간 보기·접기",
                          "AI 구간 검토"])

    def test_toast_undo_restores_saved_set(self):
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        self.assertFalse(scr.rename_current("첫 이름"), "처음은 전체 보기라 이름을 바꿀 구간이 없음")
        scr.select_node(scr.node_set["nodes"][0]["node_id"])
        self.assertTrue(scr.rename_current("첫 이름"))
        pg = self.pg()
        before = nodes.load(pg)
        scr.set_checked([n["node_id"] for n in scr.node_set["nodes"][:2]])
        self.assertTrue(scr.merge_checked())
        self.assertFalse(win.toast_box.isHidden())
        self.assertIn("병합했습니다", win.toast_box.label.text())
        self.assertTrue(win.toast_box.run_undo())
        self.assertEqual(nodes.load(pg), before, "실행 취소 = 병합 전 집합을 다시 저장")
        self.assertEqual(scr.node_set, before)

        self.assertTrue(scr.confirm("검토자A"))
        self.assertEqual(nodes.load(pg)["status"], "confirmed")
        self.assertTrue(win.toast_box.run_undo())
        self.assertEqual(nodes.load(pg), before, "확정 실행 취소 = 확정 전 집합")
        self.assertEqual(scr.node_set["status"], "proposed")

        self.assertTrue(scr.repropose(ask=False))
        self.assertNotEqual(nodes.load(pg), before)
        self.assertTrue(win.toast_box.run_undo())
        self.assertEqual(nodes.load(pg), before, "다시 제안으로 버린 집합도 되살림")

    def test_second_window_stale_save_is_refused(self):
        """두 창이 같은 구간 파일을 열었을 때, 먼저 저장한 창의 확정·이름 변경을 나중 창이 덮어쓰지 않는다."""
        from hazop.study import nodes
        w1, w2 = self.window(), self.window()
        s1, s2 = self.open_study(w1), self.open_study(w2)
        s1.select_node("S1")
        self.assertTrue(s1.rename_current("창1 이름"))
        self.assertTrue(s1.confirm("검토자1"))
        path = nodes.store_path(s1.node_set.get("project_id"), s1.node_set["graph_id"])
        with open(path, "rb") as fh:
            first = fh.read()
        before = s2.node_set
        s2.select_node("S2")
        self.assertFalse(s2.rename_current("창2 이름"), "읽은 뒤 다른 창이 저장했으면 저장하지 않음")
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), first, "먼저 저장한 창의 내용이 그대로")
        self.assertEqual(s2.node_set, before, "거절된 창은 이전 집합을 그대로 보임")
        self.assertIn("다시 열", s2.msg.text())
        self.assertTrue(s1.reopen(), "먼저 저장한 창은 계속 저장할 수 있음")

    def _unreadable_cases(self):
        """확정본을 저장하고 (이름, 망가뜨린 바이트) 목록과 원래 바이트를 돌려준다."""
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        scr.select_node("S1")
        self.assertTrue(scr.rename_current("사람이 정한 이름"))
        self.assertTrue(scr.confirm("검토자A"))
        path = nodes.store_path(scr.node_set.get("project_id"), scr.node_set["graph_id"])
        win.close()
        with open(path, "rb") as fh:
            good = fh.read()
        no_members = json.loads(good.decode("utf-8"))
        for n in no_members["nodes"]:
            n.pop("members")
        return path, good, [("잘린 파일", good[: len(good) // 2]), ("빈 파일", b""),
                            ("members 없음", json.dumps(no_members, ensure_ascii=False).encode("utf-8"))]

    @staticmethod
    def _backups(path):
        from hazop import paths
        root = paths.folder("backup")
        return [os.path.join(d, f) for d, _s, fs in os.walk(root) for f in fs if f == os.path.basename(path)]

    def test_unreadable_saved_file_is_backed_up_before_overwrite(self):
        from unittest import mock
        from hazop import paths
        self.addCleanup(shutil.rmtree, paths.folder("backup"), True)
        path, _good, cases = self._unreadable_cases()
        for label, raw in cases:
            with self.subTest(label):
                with open(path, "wb") as fh:
                    fh.write(raw)
                win = self.window()
                scr = self.open_study(win)
                self.assertEqual(scr.stack.currentIndex(), 1, "못 읽어도 화면은 열림")
                self.assertIn("읽을 수 없어", scr.warn.label.text())
                scr.select_node("S2")
                with mock.patch.object(scr, "ask_overwrite_unreadable", return_value=False) as ask:
                    self.assertFalse(scr.rename_current("새 이름"))
                ask.assert_called_once()
                with open(path, "rb") as fh:
                    self.assertEqual(fh.read(), raw, "아니요 = 원본 그대로")
                self.assertEqual(self._backups(path), [])
                with mock.patch.object(scr, "ask_overwrite_unreadable", return_value=True):
                    self.assertTrue(scr.rename_current("새 이름"))
                backups = self._backups(path)
                self.assertEqual(len(backups), 1, "예 = 원본을 백업한 뒤 저장")
                with open(backups[0], "rb") as fh:
                    self.assertEqual(fh.read(), raw)
                self.assertEqual(nodes_load(path)["nodes"][1]["name"], "새 이름")
                with mock.patch.object(scr, "ask_overwrite_unreadable") as ask:
                    self.assertTrue(scr.rename_current("한 번 더"))
                ask.assert_not_called()
                win.close()
                shutil.rmtree(paths.folder("backup"), ignore_errors=True)

    def test_repropose_over_unreadable_file_asks(self):
        from unittest import mock
        from hazop import paths
        self.addCleanup(shutil.rmtree, paths.folder("backup"), True)
        path, _good, cases = self._unreadable_cases()
        raw = cases[0][1]
        with open(path, "wb") as fh:
            fh.write(raw)
        scr = self.open_study(self.window())
        with mock.patch.object(scr, "ask_overwrite_unreadable", return_value=False) as ask:
            self.assertFalse(scr.repropose(ask=True))
        ask.assert_called_once()
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), raw, "다시 제안도 묻고, 아니요면 쓰지 않음")
        self.assertIn("저장하지 않았", scr.msg.text())

    def test_file_locked_at_open_is_saved_over_after_one_backup(self):
        """열 때 OSError(권한·잠금)로 못 읽은 파일이 저장할 때는 읽히면, 한 번 묻고 백업한 뒤 저장한다
        ('읽은 뒤 바뀜'으로 거절하며 편집마다 다시 묻고 백업을 쌓지 않는다)."""
        from unittest import mock
        from hazop import paths
        self.addCleanup(shutil.rmtree, paths.folder("backup"), True)
        path, good, _cases = self._unreadable_cases()
        real = open

        def locked(file, *args, **kwargs):
            if isinstance(file, str) and os.path.normcase(os.path.abspath(file)) == os.path.normcase(path):
                raise PermissionError(13, "다른 프로그램이 쓰는 중", file)
            return real(file, *args, **kwargs)
        win = self.window()
        with mock.patch("builtins.open", side_effect=locked):
            scr = self.open_study(win)
        self.assertIn("읽을 수 없어", scr.warn.label.text())
        scr.select_node("S2")
        with mock.patch.object(scr, "ask_overwrite_unreadable", return_value=True) as ask:
            self.assertTrue(scr.rename_current("새 이름"), scr.msg.text())
        ask.assert_called_once()
        backups = self._backups(path)
        self.assertEqual(len(backups), 1)
        with open(backups[0], "rb") as fh:
            self.assertEqual(fh.read(), good, "확정본 원본이 백업에 남음")
        with mock.patch.object(scr, "ask_overwrite_unreadable") as ask:
            self.assertTrue(scr.rename_current("한 번 더"))
        ask.assert_not_called()
        self.assertEqual(len(self._backups(path)), 1, "백업이 쌓이지 않음")
        self.assertEqual(nodes_load(path)["nodes"][1]["name"], "한 번 더")

    # ---------------------------------------------------------------- 교차검증 지적 2·3·5·6 (화면 경로)

    def _outside_edit(self, path, **change):
        """저장 파일을 화면 밖에서 고친 것처럼 바꾸고 그 바이트를 돌려준다."""
        doc = dict(nodes_load(path), **change)
        data = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(data)
        return data

    def test_undo_after_leaving_the_drawing_does_not_overwrite_an_outside_change(self):
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        scr.select_node("S1")
        self.assertTrue(scr.rename_current("바꾼 이름"))
        path = nodes.store_path(scr.node_set.get("project_id"), scr.node_set["graph_id"])
        outside = self._outside_edit(path, drawing_number="밖에서 고침")
        scr.node_set = None  # 토스트가 떠 있는 사이 다른 도면으로 옮긴 상태
        self.assertTrue(win.toast_box.run_undo())
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), outside, "읽은 뒤 바뀐 파일은 실행 취소로 덮어쓰지 않음")

    def test_undo_then_split_again_does_not_reuse_the_number(self):
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        members = scr.node_set["nodes"][0]["members"]
        self.assertGreater(len(members), 2)
        self.assertTrue(scr._apply(lambda s: nodes.split(s, "S1", members[:1]), done="나눴습니다"))
        first = scr.node_set["history"][-1]["detail"]["new_node_id"]
        self.assertTrue(win.toast_box.run_undo())
        self.assertEqual(len(scr.node_set["nodes"]), len(nodes.propose(self.pg())["nodes"]), "되돌림")
        self.assertTrue(scr._apply(lambda s: nodes.split(s, "S1", members[1:2]), done="나눴습니다"))
        second = scr.node_set["history"][-1]["detail"]["new_node_id"]
        self.assertNotEqual(second, first, "되돌린 분할의 번호를 다른 구성요소에 다시 주지 않음")
        self.assertEqual(nodes.load(self.pg()), scr.node_set)

    def test_review_proposals_changed_outside_are_not_overwritten(self):
        from hazop.study import node_review as nr
        win = self.window()
        scr = self.open_study(win)
        path = nr.save(dict(scr.review_doc, next_id=40))  # 화면이 읽은 뒤 다른 프로그램이 쓴 묶음
        with open(path, "rb") as fh:
            outside = fh.read()
        self.assertFalse(scr._save_review(dict(scr.review_doc, next_id=2)))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), outside)
        self.assertIn("바뀌어", scr.msg.text())

    def test_results_changed_outside_are_not_overwritten(self):
        from hazop.study import nodes, results as res_mod
        win = self.window()
        scr = self.open_study(win)
        self.assertTrue(scr.confirm("검토자A"))
        win.go(RESULTS)
        rs = win.screens[RESULTS]
        rs._load()
        self.assertEqual(rs.stack.currentIndex(), 1)
        self.assertTrue(rs._apply_review(dict(rs.results, ai_log=[{"at": "2026-11-07T00:00:00Z"}])) is None)
        path = res_mod.store_path(rs.node_set.get("project_id"), rs.node_set["graph_id"])
        self.assertEqual(nodes_load(path)["ai_log"], [{"at": "2026-11-07T00:00:00Z"}], "보통 때는 저장됨")
        doc = dict(nodes_load(path), ai_log=[{"by": "다른 프로그램"}])
        with open(path, "wb") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        with open(path, "rb") as fh:
            outside = fh.read()
        rs._apply_review(dict(rs.results, ai_log=[]))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), outside, "읽은 뒤 바뀐 결과 파일은 덮어쓰지 않음")
        rs._load()
        self.assertEqual(rs.results["ai_log"], [{"by": "다른 프로그램"}], "다시 읽으면 바깥 내용을 봄")
        nodes  # noqa: B018

    def test_failed_version_migration_is_shown(self):
        """확정본에 참조를 채워 다시 써야 하는데 쓰지 못하면, 저장본을 그대로 열고 이유를 알린다."""
        from unittest import mock
        from hazop import paths
        from hazop.study import nodes
        self.addCleanup(shutil.rmtree, paths.folder("backup"), True)
        pg = self.pg()
        ns = nodes.confirm(nodes.propose(pg), pg, "검토자A")
        ns.pop("member_refs")
        nodes.save(ns)
        win = self.window()
        with mock.patch("os.replace", side_effect=OSError(13, "잠김")):
            scr = self.open_study(win)
        self.assertEqual(scr.node_set["status"], "confirmed")
        self.assertIn("저장하지 못", scr.warn.label.text())

    def test_knowledge_index_follows_the_knowledge_graph_files(self):
        """지식그래프 파일이 바뀌면 ④가 쥔 지식 색인도 바뀐다(그래프 객체가 같아도). 실제 파일을 두 번 써서 본다."""
        import copy
        from hazop import paths
        from hazop.kg import build
        from hazop.study import ai_cells, node_review as nr
        from scripts import check_kg_context as chk
        win = self.window()
        scr = self.open_study(win)
        kg_root = paths.output_root(ai_cells.KG_DIR, paths.safe_name("kg-%s" % scr.node_set["project_id"]))
        self.addCleanup(shutil.rmtree, kg_root, True)
        knowledge = chk.sample_knowledge()

        def write(text):
            k = copy.deepcopy(knowledge)
            next(n for n in k["nodes"] if n["id"] == "req-001")["text"] = text
            build.write_outputs(kg_root, k, build.build_kg(k, [self.graph]))

        def req_text(kn):
            node = next(n for n in scr.node_set["nodes"] if any(m in kn["by_entity"] for m in n["members"]))
            return next(i["text"] for i in nr.node_knowledge(node, kn)[0] if i["knowledge_id"] == "req-001")
        write("첫 문구")
        self.assertEqual(req_text(scr._knowledge(force=True)), "첫 문구")
        scr.review_doc = dict(scr.review_doc, proposals=[{"decision": "open", "knowledge_fp": "x"}])
        self.assertEqual(req_text(scr._knowledge()), "첫 문구")
        write("바뀐 문구")
        self.assertEqual(req_text(scr._knowledge()), "바뀐 문구", "오래됨 판정이 쓰는 색인도 새 지식그래프를 따른다")
        self.assertEqual(req_text(scr._knowledge(force=True)), "바뀐 문구")

    # ---------------------------------------------------------------- 빈 구간(2026-11-11 사용자 실행에서 난 IndexError)

    def _walk_the_app(self, win):
        """저장 뒤에 도는 화면 갱신과 단계 이동이 예외 없이 도는지 본다(빈 구간이 든 집합에서 span이 죽던 길)."""
        win._refresh_explorer()
        win._refresh_status()
        self.assertIsNotNone(win.index())
        self.assertTrue(win.go(RESULTS))
        self.assertTrue(win.go(STUDY))

    def test_removing_every_member_removes_the_node_and_keeps_the_app_running(self):
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        target = scr.node_set["nodes"][1]
        nid, members = target["node_id"], list(target["members"])
        top = max(int(n["node_id"][1:]) for n in scr.node_set["nodes"])
        scr.select_node(nid)
        scr.member_list.selectAll()
        self.assertEqual(len(scr.selected_members()), len(members))
        from unittest import mock
        with mock.patch.object(win, "toast") as toast:
            self.assertTrue(scr.remove_selected(), scr.msg.text())
        self.assertIn("없앴", toast.call_args[0][0])
        self.assertNotIn(nid, [n["node_id"] for n in scr.node_set["nodes"]], "구성요소가 하나도 없는 구간은 남기지 않음")
        saved = nodes.load(self.pg())
        self.assertEqual(saved, scr.node_set)
        self.assertTrue(all(n["members"] for n in saved["nodes"]))
        self.assertEqual(sorted(nodes.coverage(saved, self.pg())["uncovered"]), sorted(members), "뺀 구성요소는 미포함으로 남음")
        self.assertEqual(scr.uncovered_list.count(), len(members))
        self._walk_the_app(win)
        first = saved["nodes"][0]
        again = nodes.split(saved, first["node_id"], first["members"][:1])
        self.assertEqual(again["history"][-1]["detail"]["new_node_id"], "S%d" % (top + 1), "없앤 구간의 번호를 다시 내지 않음")

    def test_saved_file_with_an_empty_node_opens_and_the_empty_node_can_be_removed(self):
        """빈 구간이 이미 저장된 파일(고치기 전 판이 쓴 것)도 읽히고, 다른 구간을 잃지 않으며, 빈 구간을 지울 수 있다."""
        from hazop.study import nodes
        pg = self.pg()
        ns = nodes.propose(pg)
        ns = nodes.rename(ns, ns["nodes"][0]["node_id"], "사람이 정한 이름")
        empty = ns["nodes"][1]["node_id"]
        ns["nodes"][1]["members"] = []
        nodes.save(ns)
        win = self.window()
        scr = self.open_study(win)
        self.assertEqual(scr.stack.currentIndex(), 1)
        self.assertEqual(scr.node_set["nodes"][0]["name"], "사람이 정한 이름")
        self.assertNotIn("읽을 수 없어", scr.warn.label.text())
        self._walk_the_app(win)
        rows = {scr.node_list.item(i).data(Qt.UserRole): scr.node_list.item(i).text() for i in range(scr.node_list.count())}
        self.assertIn("구성요소 없음", rows[empty])
        scr.select_node(empty)
        self.assertTrue(scr.remove_btn.isEnabled())
        self.assertEqual(scr.remove_btn.text(), "빈 구간 지우기")
        self.assertTrue(scr.remove_selected(), scr.msg.text())
        self.assertNotIn(empty, [n["node_id"] for n in nodes.load(pg)["nodes"]])
        scr.select_node(scr.node_set["nodes"][0]["node_id"])
        self.assertEqual(scr.remove_btn.text(), "구간에서 빼기")

    def test_refresh_failure_after_the_file_is_written_is_reported_as_saved(self):
        from unittest import mock
        from hazop.study import nodes
        win = self.window()
        scr = self.open_study(win)
        scr.select_node("S1")
        with mock.patch.object(win, "mark_saved", side_effect=RuntimeError("탐색기 갱신 오류")):
            self.assertTrue(scr.rename_current("저장은 된 이름"))
        self.assertEqual(nodes.load(self.pg())["nodes"][0]["name"], "저장은 된 이름")
        self.assertEqual(scr.node_set["nodes"][0]["name"], "저장은 된 이름")
        self.assertIn("저장했지만", scr.msg.text())

    def test_bom_saved_file_loads_unchanged(self):
        from hazop.study import nodes
        path, good, _cases = self._unreadable_cases()
        with open(path, "wb") as fh:
            fh.write(codecs.BOM_UTF8 + good)
        scr = self.open_study(self.window())
        self.assertEqual(scr.node_set["status"], "confirmed", "메모장이 붙인 BOM이 있어도 그대로 읽음")
        self.assertEqual(scr.node_set["nodes"][0]["name"], "사람이 정한 이름")
        self.assertNotIn("읽을 수 없어", scr.warn.label.text())
        self.assertEqual(nodes.load(self.pg())["status"], "confirmed")

    def test_empty_hints_and_selection(self):
        win = self.window()
        scr = self.open_study(win)
        self.assertEqual(scr.uncovered_list.count(), 0)
        self.assertTrue(scr.uncovered_list.isHidden() and not scr.uncovered_hint.isHidden(), "미포함 0은 안내 한 줄")
        self.assertTrue(scr.owner_list.isHidden() and not scr.owner_hint.isHidden(), "구성요소를 누르기 전 안내")
        nid = scr.node_set["nodes"][1]["node_id"]
        scr.select_node(nid)
        self.assertEqual(win.selection, {"kind": "node", "drawing": self.drawing, "node_id": nid})
        node_id, eid = self.sole_member(scr)
        scr.on_node({"entity_id": eid, "local_id": None})
        self.assertEqual(win.selection, {"kind": "component", "drawing": self.drawing, "entity_id": eid})
        self.assertEqual(scr.current_node_id(), node_id)
        self.assertEqual(scr.tabs.currentIndex(), 0)
        self.assertEqual(scr.selected_members(), [eid])

    def seg_state(self, win):
        return json.loads(self.js(win, """JSON.stringify({
            focus: document.body.classList.contains('hz-segfocus'),
            painted: Array.from(new Set(Array.prototype.map.call(document.querySelectorAll('[data-hz-seg]'),
                                                                  function (e) { return e.getAttribute('data-hz-seg'); }))),
            inside: Array.from(new Set(Array.prototype.map.call(document.querySelectorAll('.hz-seg-in'),
                                                                 function (e) { return e.getAttribute('data-local-id')
                                                                   || e.previousElementSibling.getAttribute('data-local-id'); }))),
            badges: Array.prototype.map.call(document.querySelectorAll('.hz-seg-badge text'), function (t) { return t.textContent; }),
            picked: Array.from(new Set(Array.prototype.map.call(document.querySelectorAll('.hz-pick, .selected'),
                                                                 function (e) { return e.getAttribute('data-local-id')
                                                                   || e.previousElementSibling.getAttribute('data-local-id'); }))),
            scale: window.hzView.get().s })"""))

    def test_segment_focus_and_component_pick(self):
        win = self.window()
        scr = self.open_study(win)
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "④ 도면 브리지 ready 없음")
        pump(seconds=0.3)
        all_ids = sorted(n["node_id"] for n in scr.node_set["nodes"])
        st = self.seg_state(win)
        self.assertIsNone(scr.current_node_id(), "처음은 고른 구간 없이 전체 보기")
        self.assertFalse(st["focus"])
        self.assertEqual(sorted(st["badges"]), all_ids, "전체 보기는 모든 구간을 칠함")
        self.assertFalse(scr.overview_btn.isEnabled())

        node = next(n for n in scr.node_set["nodes"] if len(n["members"]) >= 2)
        scr.select_node(node["node_id"])
        pump(seconds=0.3)
        st = self.seg_state(win)
        mine = {scr.local_map[m] for m in node["members"] if m in scr.local_map}
        self.assertTrue(st["focus"], "구간을 고르면 나머지를 흐리게")
        self.assertEqual(st["painted"], [node["node_id"]], "고른 구간만 칠함")
        self.assertEqual(st["badges"], [node["node_id"]])
        self.assertTrue(st["inside"] and set(st["inside"]) <= mine, "흐리지 않는 요소는 고른 구간 구성요소뿐")
        self.assertTrue(scr.pick_card.isHidden(), "구성요소를 고르기 전에는 카드 없음")

        eid = node["members"][0]
        self.select_members(scr, [eid])
        pump(seconds=0.3)
        st = self.seg_state(win)
        self.assertEqual(scr.picked_entity, eid)
        self.assertEqual(st["picked"], [scr.local_map[eid]], "고른 구성요소 하나만 따로 강조")
        self.assertGreaterEqual(st["scale"], 1.5, "목록에서 고르면 가운데로 확대")
        self.assertFalse(scr.pick_card.isHidden())
        info = dict(scr.pick_info())
        from hazop.study import nodes
        from hazop.app.screens.study import entity_label
        self.assertEqual(info["태그"], entity_label(scr.entities[eid]))
        self.assertEqual(info["종류"], scr.entities[eid]["kind"])
        self.assertEqual(info["속한 구간"], ", ".join(nodes.nodes_of(scr.node_set, eid)))
        self.assertIn(node["node_id"], scr.pick_text.text())

        other = node["members"][1]
        self.js(win, "(function(){var e=document.querySelector('#overlay [data-local-id=\"%s\"]');"
                     "if(e)e.dispatchEvent(new MouseEvent('click',{bubbles:true}));return !!e})()" % scr.local_map[other])
        self.assertTrue(wait_for(lambda: scr.picked_entity == other), "도면 클릭 = 구성요소 선택")
        pump(seconds=0.3)
        self.assertEqual(scr.current_node_id(), node["node_id"], "도면에서 누른 구성요소가 고른 구간에 있으면 구간 유지")
        self.assertEqual(self.seg_state(win)["picked"], [scr.local_map[other]])
        self.assertEqual(dict(scr.pick_info())["태그"], entity_label(scr.entities[other]))


        from PySide6.QtTest import QTest
        win.activateWindow()
        scr.node_list.setFocus()
        QTest.keyClick(scr.node_list, Qt.Key_Escape)
        pump(seconds=0.3)
        self.assertIsNone(scr.picked_entity, "Esc 한 번 = 구성요소 선택만 풂")
        self.assertTrue(scr.pick_card.isHidden())
        self.assertEqual(scr.current_node_id(), node["node_id"])
        self.assertEqual(self.seg_state(win)["picked"], [])
        scr.overview_btn.click()
        pump(seconds=0.3)
        st = self.seg_state(win)
        self.assertIsNone(scr.current_node_id(), "Esc 두 번 = 전체 보기")
        self.assertFalse(st["focus"])
        self.assertEqual(sorted(st["badges"]), all_ids, "전체 보기로 돌아오면 모든 구간 색")

        scr.select_node(node["node_id"])
        self.select_members(scr, [eid])
        pump(seconds=0.3)
        self.assertEqual(self.seg_state(win)["picked"], [scr.local_map[eid]])
        win.go(2)
        pump(seconds=0.5)
        if win.webview.bridge.is_ready:
            self.assertEqual(self.js(win, "document.querySelectorAll('.hz-pick, .hz-seg-in').length"), 0,
                             "다른 화면으로 가면 ④ 강조가 남지 않음")

    def test_results_refuse_stale_confirmed_set(self):
        from hazop.graph import project
        from hazop.study import nodes
        pg = project.load(project.project_id_of(self.graph))
        ns = nodes.confirm(nodes.propose(pg), pg, "검토자A")
        ns["graph_version"] = "v-old"
        ns["member_refs"][sorted(ns["member_refs"])[0]] = "graph-gone#x"  # 새 판에 대응 없음 -> 판 이전하지 않음
        nodes.save(ns)
        win = self.window()
        win.go(RESULTS)
        res = win.screens[RESULTS]
        res._load()
        self.assertEqual(res.stack.currentIndex(), 0, "옛 도면 판의 확정본은 결과 셸에 쓰지 않음")
        self.assertIn("다시 확정", res.empty.text())


if __name__ == "__main__":
    unittest.main()
