"""실제 창 검증 결함 후보 단위 H-a(창·메뉴·흐름) 시험. 근거: docs/2026-11-10-plan/pstack-advice.md '단위 H'.
실행: python -m unittest tests.test_window_defects

ShellTest와 같은 임시 작업 루트(샘플 도면 SNP-M-102, 확정 검토구간, 고정 분석 결과)를 쓴다. 네트워크·AI 호출 없음.
"""

import hashlib
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.test_app import pump, tearDownModule  # noqa: E402,F401
from tests import test_app as base  # noqa: E402
from tests import test_shell as shell  # noqa: E402

STUDY, RESULTS = shell.STUDY, shell.RESULTS

LEGACY_ANALYSIS, LEGACY_REVIEW = 2, 3


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _keep_files(test, paths):
    """시험이 공용 작업 루트의 파일을 바꿔도 끝나면 처음 내용으로 되돌린다."""
    saved = {}
    for p in paths:
        with open(p, "rb") as fh:
            saved[p] = fh.read()

    def restore():
        for p, raw in saved.items():
            with open(p, "wb") as fh:
                fh.write(raw)
    test.addCleanup(restore)


class WindowDefectTest(unittest.TestCase):
    setUpClass = classmethod(shell.ShellTest.setUpClass.__func__)
    tearDownClass = classmethod(shell.ShellTest.tearDownClass.__func__)
    window = shell.ShellTest.window

    @staticmethod
    def menu(win, title):
        return next(a.menu() for a in win.menu_bar.actions() if a.text() == title)

    # 결함 1: 파일 > Excel 내보내기는 지금 ⑤ 분석 결과를 내보낸다
    def test_file_menu_excel_exports_current_results(self):
        win = self.window()
        called = []
        win.screens[RESULTS].export_excel = lambda *a, **k: called.append(win.stack.currentIndex())
        win.screens[LEGACY_REVIEW].ask_excel = lambda *a, **k: called.append("legacy")
        act = next(a for a in self.menu(win, "파일").actions() if a.text() == "Excel 내보내기…")
        act.trigger()
        pump(win, 0.05)
        self.assertEqual(called, [RESULTS], "⑤ 화면으로 가서 그 화면의 export_excel을 부른다")

    # 결함 13: 옛 화면과 옛 기능은 보기 > 이전 MVP 하위 메뉴에만 있다
    def test_legacy_screens_live_under_previous_mvp_submenu(self):
        from hazop.app.main_window import STEPS
        win = self.window()
        view = self.menu(win, "보기")
        top = [a.text() for a in view.actions()]
        self.assertNotIn(STEPS[LEGACY_ANALYSIS], top)
        self.assertNotIn(STEPS[LEGACY_REVIEW], top)
        for i in (0, 1, 4, 5, 6, 7):
            self.assertIn(STEPS[i], top, "지금 단계는 보기 메뉴 첫 층에 그대로")
        sub = next(a.menu() for a in view.actions() if a.text() == "이전 MVP")
        self.assertEqual([a.text() for a in sub.actions() if not a.isSeparator()],
                         [STEPS[LEGACY_ANALYSIS], STEPS[LEGACY_REVIEW], "구간 열기…", "실행 열기…"])
        file_items = [a.text() for a in self.menu(win, "파일").actions()]
        self.assertNotIn("구간 열기…", file_items)
        self.assertNotIn("실행 열기…", file_items)
        next(a for a in sub.actions() if a.text() == STEPS[LEGACY_ANALYSIS]).trigger()
        self.assertEqual(win.stack.currentIndex(), LEGACY_ANALYSIS, "하위 메뉴에서도 옛 화면이 열린다")

    # 결함 2: ④ 확정을 해제하면 ⑤ 본문·상태줄·관련 항목이 같은 상태를 말하고, 결과 파일은 그대로다
    def test_unconfirm_keeps_results_and_screens_agree(self):
        from hazop.study import nodes
        from hazop.study import results as res
        ns = self.node_set
        node_file = nodes.store_path(ns.get("project_id"), ns["graph_id"])
        res_file = res.store_path(ns.get("project_id"), ns["graph_id"])
        _keep_files(self, (node_file, res_file))
        before = _sha(res_file)
        win = self.window()
        win.go(RESULTS)
        scr = win.screens[RESULTS]
        scr.open_cell(*self.scored)
        pump(win, 0.05)
        self.assertIn("미검토", win.count_label.text())
        win.go(STUDY)
        self.assertTrue(win.screens[STUDY].reopen())
        pump(win, 0.05)
        win.go(RESULTS)
        pump(win, 0.05)
        self.assertEqual(scr.stack.currentIndex(), 0, "확정본이 없으면 행렬 대신 빈 상태")
        self.assertIn("확정을 해제", scr.empty_title.text(), "제목이 '결과 없음'이 아니라 숨긴 까닭을 말한다")
        self.assertNotIn("확정을 해제", scr.empty.text(), "본문은 제목을 되풀이하지 않는다")
        self.assertIn("보관", scr.empty.text(), "이미 만든 결과가 남아 있음을 알린다")
        self.assertNotIn("미검토", win.count_label.text(), "상태줄도 결과 개수를 말하지 않는다")
        self.assertIn("(제안)", win.count_label.text())
        self.assertNotEqual((win.selection or {}).get("kind"), "cell", "보이지 않는 칸을 관련 항목 기준으로 두지 않음")
        # 메뉴 내보내기도 본문과 같은 말을 한다: 결과가 없는 게 아니라 숨겨 둔 것
        win.export_results_excel()
        pump(win, 0.05)
        msg = win.msg_label.text()
        self.assertIn("숨긴 상태라 내보낼 수 없습니다", msg)
        self.assertIn("다시 확정", msg)
        self.assertNotIn("내보낼 분석 결과가 없습니다", msg)
        self.assertEqual(_sha(res_file), before, "결과 파일은 그대로")
        # 결과 파일이 있어도 분석한 칸이 하나도 없으면 '이미 만든 결과'를 말하지 않는다
        res.write(res_file, res.empty_results(ns, scr.deviations))
        win.go(STUDY)
        win.go(RESULTS)
        pump(win, 0.05)
        self.assertNotIn("확정을 해제", scr.empty_title.text())
        self.assertNotIn("보관", scr.empty.text())
        win.export_results_excel()
        pump(win, 0.05)
        self.assertIn("내보낼 분석 결과가 없습니다", win.msg_label.text())

    # 결함 10: 실패 칸 다시 실행을 시작하면 대상 수와 이번 실행의 실패를 가른다
    def _progress(self, scr, scope, done, total, failed_now=0):
        scr.run_info = scr._new_run_info("api", False, [{}] * total, scope)
        scr.run_info["failed"] = [{"status": "failed"}] * failed_now
        scr.progress.setRange(0, total)
        scr.progress.setValue(done)
        scr._progress_text()
        return scr.progress_label.text()

    def test_rerun_progress_text(self):
        import re
        win = self.window()
        win.go(RESULTS)
        scr = win.screens[RESULTS]
        self.addCleanup(setattr, scr, "run_info", None)
        self.assertTrue(scr.results and [c for c in scr.results["cells"] if (c.get("ai_run") or {}).get("status") == "failed"],
                        "시험 자료에 옛 실패 칸이 있다")
        start = self._progress(scr, "failed", 0, 12)
        self.assertTrue(start.startswith("다시 돌릴 칸 12 · 0/12 호출"), start)
        self.assertNotIn("실패", start, "시작 때 옛 실패 칸 수를 이번 실패처럼 말하지 않는다")
        self.assertTrue(re.search(r"(\d+)\s*/\s*(\d+)\s*호출", start), "사용자 시나리오의 실행 중 판정과 맞음")
        self.assertIn("이번 실패 호출 2", self._progress(scr, "failed", 5, 12, failed_now=2))
        full = self._progress(scr, "all", 0, 30)
        self.assertTrue(full.startswith("AI 0/30 호출"), full)
        self.assertNotIn("실패", full)
        # 실측(2026-11-12): 칸 하나를 돌리는데 'AI 0/1 호출 · 실패 12'가 보였다. 옛 실패 수가 새 실행 진행에 섞이면 안 된다
        one = self._progress(scr, "cell", 0, 1)
        self.assertTrue(one.startswith("AI 0/1 호출"), one)
        self.assertNotIn("실패", one, "칸 하나 실행 중에 결과 파일의 옛 실패 칸 수를 붙이지 않는다")
        # 실행이 끝난 뒤(run_info 없음): 지난 실행 호출 수 옆의 실패 수는 결과 파일 전체 것이라고 이름 붙인다
        left = len([c for c in scr.results["cells"] if (c.get("ai_run") or {}).get("status") == "failed"])
        scr.run_info = None
        scr.progress.setRange(0, 1)
        scr.progress.setValue(1)
        scr._progress_text()
        idle = scr.progress_label.text()
        self.assertRegex(idle, r"^AI 1/1 호출 · 결과에 남은 실패 칸 \d+$")
        self.assertNotRegex(idle, r"호출 · 실패 \d")
        from hazop.app.screens.results import failure_note
        done_note = failure_note({"failed": [{}]}, left)
        self.assertEqual(done_note, " · 이번 실패 호출 1 · 결과에 남은 실패 칸 %d" % left, "끝남 알림도 두 수를 가른다")

    # 결함 12: 분할 거절 문구는 그 화면에서만 보이고, 필요한 폭은 창 폭 하나로 말한다
    def test_split_refusal_names_window_width_and_clears_on_move(self):
        import re
        from hazop.app.main_window import RAIL_W
        win = self.window()
        widths = []
        for idx in (0, 1, STUDY):
            win.go(idx)
            self.assertFalse(win.toggle_split(RESULTS))
            text = win.msg_label.text()
            m = re.search(r"창 폭이 (\d+)px 이상이어야 합니다\(지금 (\d+)px\)", text)
            self.assertTrue(m, text)
            self.assertEqual(int(m.group(2)), win.width())
            need = win.stack.currentWidget().minimumSizeHint().width() + win.screens[RESULTS].minimumSizeHint().width() + 8
            self.assertEqual(int(m.group(1)), need + RAIL_W, "레일 + 두 화면 최소 폭 = 필요한 창 폭")
            widths.append(int(m.group(1)))
            win.go(7)
            self.assertEqual(win.msg_label.text(), "", "다른 화면으로 옮기면 거절 문구가 사라진다")
        self.assertTrue(all(w > win.width() for w in widths))

    # 결함 3: 분할을 켜도 창이 넓어지지 않는다(나눈 뒤 최소 폭이 창보다 크면 되돌린다)
    def test_split_never_widens_window(self):
        win = self.window()
        for idx in (0, 1, STUDY, RESULTS, 7):
            win.go(idx)
            win.toggle_split()
            pump(win, 0.05)
            self.assertLessEqual(win.width(), 1366, "1366 창에서 나누기를 눌러도 창이 넓어지지 않음(%d)" % idx)
            if win.split_index is not None:
                win.unsplit()
        win.resize(1920, 1080)
        pump(win, 0.05)
        win.go(STUDY)
        win.right_pane.setMinimumWidth(1700)  # 나눈 뒤 오른쪽이 넓어지려는 경우를 흉내 냄(사전 검사는 통과)
        self.addCleanup(win.right_pane.setMinimumWidth, 0)
        self.assertFalse(win.toggle_split(RESULTS))
        pump(win, 0.05)
        self.assertIsNone(win.split_index)
        self.assertEqual(win.width(), 1920)
        self.assertIn("창 폭이", win.msg_label.text())
        self.assertIs(win.screens[RESULTS].parentWidget(), win.stack, "되돌린 화면은 원래 자리로")

    # 결함 8: 1366에서 ⑤(관련 항목 펼침)가 창을 넓히지 않고 위젯이 창 안에 있다
    def test_results_fits_1366_with_explorer_and_related(self):
        win = self.window()
        for idx in (0, 1, 4, STUDY, RESULTS, 7):
            win.go(idx)
            pump(win, 0.1)
            self.assertLessEqual(win.minimumSizeHint().width(), 1366, "단계 %d 최소 폭" % idx)
            self.assertEqual(win.width(), 1366, "단계 %d에서 창이 넓어지지 않음" % idx)
        win.go(RESULTS)
        pump(win, 0.1)
        self.assertTrue(win.related.isVisible() and win.explorer_panel.isVisible(), "1366에서도 탐색기·관련 항목을 함께 보임")
        right = win.related.mapTo(win, win.related.rect().topRight()).x()
        self.assertLess(right, win.width(), "관련 항목 패널 오른쪽 끝이 창 안")

    # 결함 9: 1366에서 탐색기 안내 줄·다음 할 일 단추가 말줄임 없이 보인다(안내 줄은 개수 열까지 쓴다)
    def test_explorer_hints_fit_at_1366(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        from hazop.study import nodes
        from hazop.study import results as res
        ns = self.node_set
        _keep_files(self, [nodes.store_path(ns.get("project_id"), ns["graph_id"]),
                           res.store_path(ns.get("project_id"), ns["graph_id"])])
        win = self.window()
        win.go(STUDY)
        self.assertTrue(win.screens[STUDY].reopen())
        checked = []
        for idx in (STUDY, RESULTS):  # 보고된 화면(Ctrl+4, Ctrl+5). ⑥의 긴 안내 문장은 줄바꿈이 필요해 후속
            win.go(idx)
            pump(win, 0.1)
            t = win.explorer
            fm = t.fontMetrics()
            it = QTreeWidgetItemIterator(t)
            while it.value():
                item = it.value()
                it += 1
                if item.data(0, Qt.UserRole + 1) in ("hint", "info", "action") and item.text(0):
                    checked.append(item.text(0))
                    self.assertLessEqual(fm.horizontalAdvance(item.text(0)), t.visualItemRect(item).width() - 4,
                                         "잘림: %s" % item.text(0))
                b = t.itemWidget(item, 0)
                if b is not None:
                    checked.append(b.text())
                    self.assertLessEqual(b.sizeHint().width(), b.width(), "단추 잘림: %s" % b.text())
        self.assertTrue(any("확정" in c for c in checked), checked)

    # 결함 5: Qt 입력 창 단추가 한국어다(앱을 만들 때 Qt 기본 번역을 건다)
    def test_input_dialog_buttons_are_korean(self):
        from PySide6.QtWidgets import QInputDialog, QPushButton
        from PySide6.QtWidgets import QApplication
        # 시험이 번역을 직접 걸지 않는다: make_application이 걸었는지만 본다(그 한 줄을 지우면 여기서 실패)
        app = QApplication.instance()
        self.assertIs(app, self.qapp, "setUpClass의 make_application이 만든 앱")
        tr = getattr(app, "_hazop_qt_translator", None)
        self.assertIsNotNone(tr, "make_application이 Qt 기본 번역을 걸었다")
        self.assertFalse(tr.isEmpty())
        dlg = QInputDialog()
        self.addCleanup(dlg.deleteLater)
        dlg.setLabelText("이름")
        dlg.show()
        pump(None, 0.05)
        texts = sorted(b.text().replace("&", "") for b in dlg.findChildren(QPushButton))
        dlg.reject()
        self.assertEqual(texts, ["취소", "확인"])


class BundleTranslationTest(unittest.TestCase):
    """결함 5의 배포본 쪽: verify_bundle이 번역 파일과 앱 로그의 번역 실패 줄을 본다."""

    def test_translation_problems(self):
        import importlib.util
        import shutil
        import tempfile
        from hazop.app import TRANSLATION_FAILED
        spec = importlib.util.spec_from_file_location("hazop_vb_tr", os.path.join(base.REPO_ROOT, "packaging", "verify_bundle.py"))
        vb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vb)
        tmp = tempfile.mkdtemp(prefix="hazop-vb-tr-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertEqual(len(vb.translation_problems(tmp, "")), 1, "번역 파일이 없으면 문제")
        qm = os.path.join(tmp, "_internal", *vb.QT_TRANSLATION_FILE)
        os.makedirs(os.path.dirname(qm))
        open(qm, "wb").close()
        self.assertEqual(vb.translation_problems(tmp, "시작 pid=1"), [])
        self.assertEqual(len(vb.translation_problems(tmp, "WARNING " + TRANSLATION_FAILED)), 1, "앱이 읽지 못했으면 문제")


def _tree(root):
    """{상대 경로: sha256}. 폴더가 없으면 빈 dict."""
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = _sha(p)
    return out


class RegisterBeforeExtractTest(base.AppTestBase):
    """결함 7: 새 파일을 고르기만 하고 등록하지 않은 동안 '추출·그래프 만들기'는 꺼져 있다. 눌러도(팔레트 명령)
    목록에서 고른 이전 자료를 다시 추출하지 않고, 등록 기록·사람 수정은 그대로다."""

    def test_extract_is_off_while_a_new_file_waits_for_registration(self):
        from hazop import paths
        from hazop.extract import corrections
        win = self.make_window()
        win.show()
        scr = win.screens[0]
        self.assertTrue(scr.set_files([base.sample_file("SNP-M-102", "drawio")]))
        base.pump(win)
        scr.do_register()
        base.pump(win, 0.1)
        scr.table.selectRow(0)
        self.assertTrue(scr.btn_extract.isEnabled(), "등록한 자료를 고르면 추출할 수 있다")
        scr.do_extract()
        base.pump(win, 0.1)
        name = os.path.basename(scr.rows[0]["path"])
        edits = corrections.store_path("SNP-M-102-사람수정")
        os.makedirs(os.path.dirname(edits), exist_ok=True)
        with open(edits, "w", encoding="utf-8") as fh:
            fh.write('{"ops": []}')
        store, edit_dir = os.environ["HAZOP_STORE_ROOT"], os.path.dirname(edits)
        before = (_tree(store), _tree(edit_dir), _tree(paths.output_root("extract")))
        scr.table.selectRow(0)
        self.assertTrue(scr.set_files([base.sample_file("SNP-M-102", "pdf")]))
        base.pump(win)
        self.assertEqual(scr._file_state, "ready")
        self.assertFalse(scr.btn_extract.isEnabled(), "고른 파일을 등록하기 전에는 추출 단추가 꺼진다")
        self.assertIn("먼저 등록", scr.btn_extract.toolTip())
        calls = []
        real = register_mod().data.extract_and_graph
        with mock.patch.object(register_mod().data, "extract_and_graph", side_effect=lambda p: (calls.append(p), real(p))[1]):
            scr.do_extract()  # 팔레트 명령도 같은 함수를 부른다
            base.pump(win, 0.1)
        after = (_tree(store), _tree(edit_dir), _tree(paths.output_root("extract")))
        for label, a, b in zip(("등록 기록", "사람 수정", "추출 결과"), before, after):
            self.assertEqual(b, a, "%s가 그대로(바뀐 파일: %s)" % (label, sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))))
        self.assertEqual(calls, [], "이전 자료(%s)를 다시 추출하지 않는다" % name)
        self.assertIn("먼저 등록", win.msg_label.text())
        # 고른 파일을 등록할 수 없는 상태(여러 개를 고름·읽을 수 없는 파일)에서도 추출은 꺼진 채다
        missing = os.path.join(os.environ["HAZOP_STORE_ROOT"], "없는-파일.drawio")
        for state, files in (("many", [base.sample_file("SNP-M-102", "drawio")] * 2), ("error", [missing])):
            scr.table.selectRow(0)
            self.assertFalse(scr.set_files(files))
            base.pump(win, 0.05)
            self.assertEqual(scr._file_state, state)
            self.assertFalse(scr.btn_extract.isEnabled(), "%s 상태에서 추출 단추가 다시 켜지지 않는다" % state)
            self.assertIn("파일 선택 지우기", scr.btn_extract.toolTip())
            with mock.patch.object(register_mod().data, "extract_and_graph", side_effect=lambda p: calls.append(p)):
                scr.do_extract()
                base.pump(win, 0.1)
            self.assertEqual(calls, [], "%s 상태에서 목록의 이전 자료를 추출하지 않는다" % state)
        self.assertEqual((_tree(store), _tree(edit_dir), _tree(paths.output_root("extract"))), before)
        # 선택을 비우면 목록에서 고른 등록 자료를 다시 추출할 수 있다
        clear = next(f for n, _, f in scr.commands() if n == "파일 선택 지우기")
        clear()
        scr.table.selectRow(0)
        self.assertEqual(scr._file_state, "none")
        self.assertTrue(scr.btn_extract.isEnabled())
        self.assertEqual(scr.btn_extract.toolTip(), "")


def register_mod():
    from hazop.app.screens import register
    return register


if __name__ == "__main__":
    unittest.main()
