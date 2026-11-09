"""⑤ 분석 결과 화면의 AI 분석 연결 시험 (4단계 설계 D7·D8). 실행: python -m unittest tests.test_ai_screen

작업 루트·저장 루트·설정 파일은 임시 폴더. 샘플 도면 SNP-M-102를 임시 작업 루트에 추출·그래프로 만들고 검토구간을 확정한다.
가짜 클라이언트(또는 가짜 opener를 끼운 ClaudeHttpClient)만 쓴다. 네트워크 호출 없음.
"""

import contextlib
import io
import json
import logging
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from hazop import paths  # noqa: E402
from tests.test_app import build_temp_drawing, tearDownModule, wait_for  # noqa: E402,F401

RESULTS = 6
KEY = "sk-ant-api03-TESTKEY-must-never-be-written-0123456789"
MODEL = "claude-opus-5-5"
USAGE = {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def asked(request):
    return [d["deviation_id"] for d in json.loads(request["user"].split("\n", 1)[1])]


def output_for(ids, cause="AI 원인"):
    return {"deviations": [{"deviation_id": d, "applicable": True, "note": "",
                            "scenarios": [{"cause": "%s %s" % (cause, d), "consequence": "결과", "safeguards": ["보호"],
                                           "recommendation": "권고", "severity": 3, "frequency": 2,
                                           "equipment_tags": ["NO-SUCH-TAG"], "kg_paths": [], "sources": []}]}
                           for d in ids]}


class FakeClient:
    """analyze만 있는 가짜. fail(ids)가 참이면 api_error. on_call(n)은 n번째 호출 때(작업 스레드에서) 부른다."""

    def __init__(self, fail=None, on_call=None, cause="AI 원인"):
        self.fail, self.on_call, self.cause = fail, on_call, cause
        self.calls = []

    def analyze(self, request):
        ids = asked(request)
        self.calls.append(ids)
        if self.on_call:
            self.on_call(len(self.calls))
        if self.fail and self.fail(ids):
            return {"status": "api_error", "output": None, "usage": None, "model": MODEL, "error_type": "api_status",
                    "status_code": 500, "error": "가짜 실패"}
        return {"status": "completed", "output": output_for(ids, self.cause), "usage": dict(USAGE), "model": MODEL,
                "error_type": None, "status_code": 200, "error": None}


class AiScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-ai-screen-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        _out_dir, cls.graph = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        from hazop.graph import project
        from hazop.study import nodes
        cls.pg = project.load(project.project_id_of(cls.graph))
        cls.node_set = nodes.confirm(nodes.propose(cls.pg), cls.pg, "검토자A")
        nodes.save(cls.node_set)
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
        from hazop import paths
        shutil.rmtree(paths.folder("분석결과"), ignore_errors=True)

    def screen(self, client=None, key=KEY):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=self.settings, ask_reviewer=False)
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(1440, 860)
        win.show()
        if key:
            win.api_keys.set(key, persist=False)
        win.ai_prefs.choose("api")  # 이 파일은 API 키 경로를 본다(구독 경로는 test_ai_run_flow)
        win.go(RESULTS)
        scr = win.screens[RESULTS]
        self.assertEqual(scr.stack.currentIndex(), 1, "확정 구간이 있으면 행렬 화면")
        if client is not None:
            scr.make_client = lambda: client
        return win, scr

    def run_and_wait(self, scr, scope="all"):
        self.assertTrue(scr.run_ai(scope), "실행이 시작됨")
        self.assertTrue(wait_for(lambda: not scr.running(), 120), "실행이 끝남")

    def saved(self):
        from hazop.study import results as res
        return res.load(self.node_set)

    def cell(self, doc, nid, did):
        return next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (nid, did))

    def units(self):
        from hazop.study import ai_cells, results as res
        return ai_cells.plan_units(self.node_set, res.load_deviations())

    def explorer_segment(self, win, node_id):
        from PySide6.QtCore import Qt
        for g in range(win.explorer.topLevelItemCount()):
            grp = win.explorer.topLevelItem(g)
            if grp.text(0).startswith(("검토구간", "구간별 분석")):
                for c in range(grp.childCount()):
                    if grp.child(c).data(0, Qt.UserRole) == (5, node_id):
                        return grp.child(c)
        raise AssertionError("탐색기에 %s 없음" % node_id)

    def test_run_shows_live_progress_and_explorer_keeps_results(self):
        from PySide6.QtCore import QCoreApplication
        from hazop.study import results as res
        gate = threading.Event()
        client = FakeClient(on_call=lambda n: n == 2 and gate.wait(30))
        win, scr = self.screen(client)
        self.assertTrue(scr.run_ai("all"))
        self.addCleanup(gate.set)
        self.assertTrue(wait_for(lambda: len(client.calls) >= 2 and scr.progress.value() >= 1, 30), "두 번째 호출 중")
        for _ in range(20):
            QCoreApplication.processEvents()
        unit = self.units()[1]
        param = next(d["parameter"] for d in res.load_deviations() if d["deviation_id"] == unit["deviation_ids"][0])
        label = scr.progress_label.text()
        self.assertIn("%s · %s 분석 중" % (unit["node_id"], param), label, "지금 구간·변수")
        self.assertIn("경과", label)
        self.assertIn("남음", label)
        self.assertIn("$", label)
        self.assertIn("입력", scr.progress_label.toolTip(), "이번 실행 토큰")
        self.assertTrue(win.msg_label.text().startswith("● AI 분석 실행 중"), "상태 표시줄 실행 중 표시")
        row = scr._row_of(unit["node_id"])
        col = next(i for i, d in enumerate(scr.deviations) if d["deviation_id"] == unit["deviation_ids"][0])
        self.assertEqual(scr.matrix.item(row, col).text(), "분석 중", "호출 중인 칸 표시")
        self.assertNotEqual(scr.matrix.item(0, 0).text(), "분석 전", "끝난 칸은 바로 채워짐")

        other = scr.node_set["nodes"][-1]["node_id"]
        win._explorer_clicked(self.explorer_segment(win, other))
        self.assertEqual(win.stack.currentIndex(), RESULTS, "⑤에서 탐색기 구간을 눌러도 ⑤에 머묾")
        self.assertEqual(scr.selected_node_id(), other, "그 구간 행을 고름")
        self.assertTrue(scr.running(), "분석은 계속됨")
        win.drawing = "다른-도면"
        win._explorer_clicked(self.explorer_segment(win, other))
        self.assertEqual(win.stack.currentIndex(), 5, "⑤가 다른 도면을 열고 있으면 옛 행 대신 ④")
        self.assertTrue(scr.running(), "④로 가도 분석은 계속됨")
        win.drawing = scr.name
        win.go(RESULTS)
        self.assertIn("분석 중", scr.progress_label.text(), "진행 표시 유지")

        gate.set()
        self.assertTrue(wait_for(lambda: not scr.running(), 120), "실행이 끝남")
        self.assertEqual(len(client.calls), len(self.units()))
        self.assertFalse(any(scr.matrix.item(r, c).text() == "분석 중" for r in range(scr.matrix.rowCount())
                             for c in range(scr.matrix.columnCount())), "끝나면 '분석 중' 칸 없음")
        path = res.store_path(self.node_set.get("project_id"), self.node_set["graph_id"])
        self.assertIn("저장: %s" % path, win.msg_label.text(), "끝나면 저장 위치")
        self.assertIn("결과 파일 저장", scr.save_label.text())
        self.assertIn(path, scr.save_label.toolTip())
        right = self.explorer_segment(win, unit["node_id"]).text(1)
        self.assertTrue(right.startswith("미"), "탐색기 구간 옆 미검토 수: %r" % right)
        scr.results = dict(scr.results, study_nodes_ref={"graph_version": "old", "confirmed_at": "old"})
        win._refresh_explorer()
        self.assertEqual(self.explorer_segment(win, unit["node_id"]).text(1), "", "이전 확정본 결과는 진행으로 보이지 않음")

    def test_finish_message_says_when_save_failed(self):
        from hazop import paths
        # 창을 닫을 때 shutdown이 저장을 다시 시도하므로 정리는 창이 닫힌 뒤(가장 나중)에 한다
        self.addCleanup(shutil.rmtree, paths.folder("분석결과"), True)
        client = FakeClient()
        win, scr = self.screen(client)
        with mock.patch("hazop.app.screens.results.res.save", side_effect=PermissionError("잠김")):
            self.run_and_wait(scr)
        self.assertIn("저장 실패", win.msg_label.text())
        self.assertNotIn("저장: ", win.msg_label.text())

    def test_estimate_uses_same_model_successful_calls(self):
        _win, scr = self.screen(FakeClient())
        from hazop.app.screens import results as rscr
        model = scr.app.api_keys.model
        scr.results = dict(scr.results, ai_log=[
            {"status": "failed", "model": model, "cost_usd": 0.0},
            {"status": "ok", "model": "other-model", "cost_usd": 9.0},
            {"status": "ok", "model": model, "cost_usd": 0.2}])
        self.assertAlmostEqual(scr.estimate(10)[1], 2.0, msg="같은 모델 성공 호출만 평균")
        scr.results = dict(scr.results, ai_log=[])
        self.assertGreater(scr.estimate(10)[1], 0)
        self.assertEqual(scr.estimate(10)[0], 10 * rscr.EST_SEC_PER_CALL)

    def test_request_asks_before_many_calls(self):
        client = FakeClient()
        _win, scr = self.screen(client)
        from hazop.study import results as res
        seen = {}

        def ask(dlg):
            seen["text"], seen["title"] = dlg.texts(), dlg.windowTitle()
            return None

        with mock.patch("hazop.app.screens.results.RunConfirmDialog.ask", ask):
            self.assertFalse(scr.request_ai("all"), "취소면 시작 안 함")
        text = seen["text"]
        self.assertIn("AI를 %d회 호출해" % len(self.units()), text)
        self.assertIn("$", text)
        self.assertIn(res.store_path(self.node_set.get("project_id"), self.node_set["graph_id"]), text)
        self.assertEqual(client.calls, [])
        self.assertFalse(scr.running())

    def test_full_run_fills_cells_saves_and_reopens(self):
        from hazop.study import results as res
        client = FakeClient()
        _win, scr = self.screen(client)
        self.assertFalse(scr.kg_chip.isHidden(), "지식그래프가 없으면 이유를 칩으로 보임")
        self.assertEqual(scr.matrix.item(0, 0).text(), "분석 전")
        self.run_and_wait(scr)
        self.assertEqual(len(client.calls), len(self.units()))
        self.assertEqual((scr.progress.value(), scr.progress.maximum()), (len(client.calls),) * 2)
        self.assertTrue(all(c["state"] == "analyzed" for c in scr.results["cells"]))
        self.assertEqual(scr.matrix.item(0, 0).text(), "1건\n위험 %d\n미검토 1" % res.risk_of(3, 2))
        self.assertIn("입력 %s" % format(USAGE["input_tokens"] * len(client.calls), ","), scr.usage.text())
        self.assertTrue(scr.run_all_btn.isEnabled(), "끝나면 다시 실행 가능")
        saved = self.saved()
        self.assertEqual(saved, scr.results, "unit마다 저장한 내용 = 화면 결과")
        self.assertEqual(res.validate(saved, self.node_set), [])

        nid, did = self.node_set["nodes"][0]["node_id"], scr.deviations[0]["deviation_id"]
        _win2, scr2 = self.screen()
        self.assertEqual(scr2.results, saved, "다시 열면 저장본을 읽음")
        self.assertTrue(scr2.stale_chip.isHidden())
        scr2.open_cell(nid, did)
        self.assertEqual(scr2.table.item(0, 0).text(), "AI 원인 %s" % did)
        self.assertEqual(scr2.table.item(0, 4).text(), "%d 조건부 수용" % res.risk_of(3, 2))
        self.assertIn("⚠ 도면에 없는 태그: NO-SUCH-TAG", scr2.table.item(0, 5).text())
        self.assertEqual(scr2.table.item(0, 6).text(), "AI 초안 · 제안")

    def test_cancel_after_first_unit_keeps_completed_units(self):
        holder = {}
        client = FakeClient(on_call=lambda n: holder["scr"].runner.cancel() if n == 1 else None)
        _win, scr = self.screen(client)
        holder["scr"] = scr
        self.run_and_wait(scr)
        self.assertEqual(len(client.calls), 1, "취소 뒤 다음 unit을 부르지 않음")
        first = self.units()[0]
        saved = self.saved()
        for c in saved["cells"]:
            done = c["node_id"] == first["node_id"] and c["deviation_id"] in first["deviation_ids"]
            self.assertEqual(c["state"], "analyzed" if done else "not_analyzed", c["deviation_id"])
        self.assertEqual(scr.progress.value(), 1)
        self.assertTrue(scr.run_all_btn.isEnabled())

    def test_failed_cells_then_retry_fixes_only_those(self):
        from hazop.app import tokens
        bad = set(self.units()[1]["deviation_ids"])
        _win, scr = self.screen(FakeClient(fail=lambda ids: bool(bad & set(ids))))
        self.run_and_wait(scr)
        from hazop.study import ai_cells
        failed = ai_cells.failed_cells(scr.results)
        self.assertEqual(len(failed), len(bad) * len(self.node_set["nodes"]))
        nid, did = failed[0]
        col = [d["deviation_id"] for d in scr.deviations].index(did)
        it = scr.matrix.item(scr._row_of(nid), col)
        self.assertEqual(it.text(), "실패")
        self.assertIn("가짜 실패", it.toolTip())
        self.assertIn("위험도 아님", it.toolTip())
        from hazop.app.screens.results_paint import CELL_ROLE, FAILED_TEXT, cell_style
        bg, ink, border, text = cell_style(it.data(CELL_ROLE))  # U-19: 실패 칸은 위험도 5(불허) 색과 겹치지 않는다
        self.assertEqual((bg, text, border["dash"]), (tokens.c("card"), FAILED_TEXT, True))
        deny = cell_style({"kind": "scored", "risk": 5, "unreviewed": 0, "scenarios": 1})
        self.assertNotEqual((bg, ink), deny[:2])
        self.assertEqual(deny[0], tokens.c("risk-deny-bg"))
        before = {(c["node_id"], c["deviation_id"]): [e["entry_id"] for e in c["entries"]]
                  for c in scr.results["cells"] if (c["node_id"], c["deviation_id"]) not in failed}

        retry = FakeClient(cause="재실행 원인")
        scr.make_client = lambda: retry
        self.run_and_wait(scr, "failed")
        self.assertEqual(sorted(tuple(c) for c in retry.calls), sorted((d,) for _n, d in failed),
                         "실패 칸만 칸 하나씩 다시 부름")
        self.assertEqual(ai_cells.failed_cells(scr.results), [])
        after = {(c["node_id"], c["deviation_id"]): [e["entry_id"] for e in c["entries"]] for c in scr.results["cells"]}
        self.assertEqual({k: after[k] for k in before}, before, "성공했던 칸은 그대로")
        self.assertEqual(self.cell(self.saved(), nid, did)["entries"][0]["cause"], "재실행 원인 %s" % did)

    def test_review_actions_persist_and_survive_rerun(self):
        _win, scr = self.screen(FakeClient())
        self.run_and_wait(scr)
        nid = self.node_set["nodes"][0]["node_id"]
        d1, d2, d3 = (d["deviation_id"] for d in scr.deviations[:3])
        scr.open_cell(nid, d1)
        self.assertTrue(scr.approve_btn.isEnabled(), "칸을 열면 첫 미검토 항목이 골라져 있음")
        scr.table.clearSelection()
        self.assertFalse(scr.approve_btn.isEnabled(), "고른 항목이 없으면 비활성")
        self.assertFalse(scr.set_entry_status("approved"))
        self.assertIn("승인할 항목 행을 먼저 고르세요", _win.msg_label.text(), "고른 행 없이 A = 안내")
        scr.select_entry(0)
        self.assertTrue(scr.set_entry_status("approved"))
        self.assertEqual(scr.table.item(0, 6).text(), "승인")
        scr.open_cell(nid, d2)
        scr.select_entry(0)
        self.assertTrue(scr.set_entry_status("rejected"))
        scr.open_cell(nid, d3)
        scr.select_entry(0)
        self.assertTrue(scr.edit_selected({"cause": "사람이 고친 원인", "severity": 4}))
        self.assertEqual(scr.table.item(0, 6).text(), "AI 초안 · 수정")

        saved = self.saved()
        self.assertEqual(self.cell(saved, nid, d1)["entries"][0]["status"], "approved")
        self.assertEqual(self.cell(saved, nid, d2)["entries"][0]["status"], "rejected")
        edited = self.cell(saved, nid, d3)["entries"][0]
        from hazop.study import results as res
        self.assertEqual((edited["status"], edited["cause"], edited["risk"]),
                         ("revised", "사람이 고친 원인", res.risk_of(4, 2)))

        rerun = FakeClient(cause="두 번째 원인")
        scr.make_client = lambda: rerun
        scr.open_cell(nid, d1)
        self.run_and_wait(scr, "cell")
        self.assertEqual(rerun.calls, [[d1]], "이 칸 다시 실행 = 그 칸만")
        self.run_and_wait(scr, "all")
        saved = self.saved()
        for did, kept in ((d1, "approved"), (d2, "rejected"), (d3, "revised")):
            entries = self.cell(saved, nid, did)["entries"]
            self.assertEqual([e["status"] for e in entries], [kept, "proposed"], "사람이 손댄 항목 + 새 AI 초안")
            self.assertEqual(entries[1]["cause"], "두 번째 원인 %s" % did)
        self.assertEqual(len({e["entry_id"] for c in saved["cells"] for e in c["entries"]}),
                         sum(len(c["entries"]) for c in saved["cells"]), "재실행해도 항목 ID가 겹치지 않음")

    def test_keys_row_actions_toast_undo_and_visible_columns(self):
        """U-02 행렬 키(J·Enter)와 워크시트 키(A·R), U-21 고른 행에만 동작 버튼, U-07 토스트 실행 취소, U-20 열 수."""
        from PySide6.QtWidgets import QApplication
        win, scr = self.screen(FakeClient())
        self.run_and_wait(scr)
        nid = self.node_set["nodes"][0]["node_id"]
        self.assertTrue(scr.next_unreviewed())
        first = scr.cell
        self.assertEqual(first, (nid, scr.deviations[0]["deviation_id"]), "J = 첫 미검토 칸")
        scr.keys["J"].activated.emit()
        self.assertNotEqual(scr.cell, first, "J 다시 = 다음 미검토 칸")
        scr.matrix.setCurrentCell(0, 2)
        scr.keys["Return"].activated.emit()
        self.assertEqual(scr.cell, (nid, scr.deviations[2]["deviation_id"]), "Enter = 지금 칸 열기")

        self.assertEqual(scr.selected_entry()["status"], "proposed", "칸을 열면 첫 미검토 항목을 골라 둠")
        scr.table.clearSelection()
        self.assertTrue(scr.row_actions.isHidden(), "고른 행이 없으면 동작 버튼 없음")
        scr.select_entry(0)
        QApplication.processEvents()
        self.assertFalse(scr.row_actions.isHidden())
        for width in (None, 2200, 1000, 1440):  # 창 폭이 바뀌어 열 폭이 달라져도 버튼은 상태 칸을 따라감
            if width:
                win.resize(width, 860)
                QApplication.processEvents()
            geo, cell = scr.row_actions.geometry(), scr.table.visualRect(scr.table.model().index(0, 6))
            self.assertEqual(geo.right(), cell.right(), "버튼 줄 오른쪽 끝 = 상태 칸 오른쪽 끝(창 폭 %s)" % width)
            self.assertTrue(geo.top() < cell.bottom() and cell.top() < geo.bottom(), "고른 행과 겹침(창 폭 %s)" % width)
        scr.keys["A"].activated.emit()
        self.assertEqual(self.cell(self.saved(), *scr.cell)["entries"][0]["status"], "approved")
        self.assertIn("승인했습니다", win.toast_box.label.text())
        win.undo()
        self.assertEqual(self.cell(self.saved(), *scr.cell)["entries"][0]["status"], "proposed", "실행 취소 = 저장본도 되돌림")
        scr.select_entry(0)
        scr.keys["A"].activated.emit()
        scr.set_results(json.loads(json.dumps(scr.results)))  # 그 뒤 결과가 바뀜(예: AI 결과 반영)
        win.undo()
        self.assertEqual(self.cell(self.saved(), *scr.cell)["entries"][0]["status"], "approved",
                         "그 사이 결과가 바뀌면 실행 취소가 통째로 되돌리지 않음")
        scr.select_entry(0)
        scr.keys["R"].activated.emit()
        self.assertEqual(self.cell(self.saved(), *scr.cell)["entries"][0]["status"], "rejected")

        win.resize(1366, 768)
        QApplication.processEvents()
        shown = (scr.matrix.viewport().width()) / scr.matrix.columnWidth(0)
        self.assertGreaterEqual(shown, 10.0, "1366에서 편차 열 약 11개(명세 U-20, Qt 여백으로 1열 줄 수 있음)")
        self.assertEqual(scr.matrix.rowHeight(0), 30)

    def test_review_actions_blocked_while_running(self):
        _win, scr = self.screen(FakeClient())
        self.run_and_wait(scr)
        nid, did = self.node_set["nodes"][0]["node_id"], scr.deviations[0]["deviation_id"]
        scr.open_cell(nid, did)
        scr.select_entry(0)
        seen = {}
        gate = threading.Event()

        def hold(n):
            if n == 1:
                gate.wait(10)

        scr.make_client = lambda: FakeClient(on_call=hold)
        self.assertTrue(scr.run_ai("all"))
        scr.select_entry(0)
        seen["buttons"] = (scr.approve_btn.isEnabled(), scr.reject_btn.isEnabled(), scr.edit_btn.isEnabled())
        seen["edit"] = scr.edit_selected({"cause": "실행 중 수정"})
        seen["approve"] = scr.set_entry_status("approved")
        gate.set()
        scr.runner.cancel()
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertEqual(seen, {"buttons": (False, False, False), "edit": False, "approve": False})

    def test_unsaved_review_not_replaced_on_reenter(self):
        from hazop.study import results as res
        _win, scr = self.screen(FakeClient())
        self.run_and_wait(scr)
        nid, did = self.node_set["nodes"][0]["node_id"], scr.deviations[0]["deviation_id"]
        scr.open_cell(nid, did)
        scr.select_entry(0)
        with mock.patch.object(res, "save", side_effect=OSError("disk full")):
            self.assertTrue(scr.set_entry_status("approved"))
            scr.on_enter()
            self.assertEqual(self.cell(scr.results, nid, did)["entries"][0]["status"], "approved",
                             "저장 실패한 승인이 디스크 판으로 덮이지 않음")
        scr.on_enter()
        self.assertEqual(self.cell(self.saved(), nid, did)["entries"][0]["status"], "approved", "다음 저장에서 반영")

    def test_empty_cell_labels_distinguish_ai_judgment(self):
        from hazop.app.screens.results import empty_cell_label
        self.assertEqual(empty_cell_label({"applicable": False}), "해당 없음(AI 판단)")
        self.assertEqual(empty_cell_label({"applicable": True}), "시나리오 없음(AI)")
        self.assertEqual(empty_cell_label({}), "항목 없음")

    def test_edit_dialog_reports_only_changed_fields(self):
        from hazop.app.screens.results import EntryDialog
        entry = {"cause": "원인", "consequence": "결과", "safeguards": ["보호1", "보호2"], "recommendation": "권고",
                 "severity": 3, "frequency": None}
        dlg = EntryDialog(entry)
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(dlg.changed(), {})
        dlg.texts["cause"].setPlainText("새 원인")
        dlg.safeguards.setPlainText("보호1\n\n보호3\n")
        dlg.freq.setCurrentIndex(dlg.freq.findText("2"))
        self.assertEqual(dlg.changed(), {"cause": "새 원인", "safeguards": ["보호1", "보호3"], "frequency": 2})

    def test_no_key_opens_key_dialog_and_calls_nothing(self):
        client = FakeClient()
        win, scr = self.screen(client, key=None)
        win.api_keys.clear()
        win.open_ai_settings = mock.Mock()
        self.assertFalse(scr.run_ai("all"))
        win.open_ai_settings.assert_called_once_with("api")
        self.assertEqual(client.calls, [])
        self.assertFalse(scr.running())
        self.assertIsNone(self.saved())

    def test_stale_saved_results_are_not_shown_and_kept_aside(self):
        from hazop.study import results as res
        doc = res.empty_results(dict(self.node_set, confirmed_at="2000-01-01T00:00:00Z"), res.load_deviations())
        path = res.save(doc, self.node_set.get("project_id"))
        _win, scr = self.screen(FakeClient())
        self.assertFalse(scr.stale_chip.isHidden())
        self.assertFalse(res.is_stale(scr.results, self.node_set))
        self.run_and_wait(scr)
        backups = [n for n in os.listdir(os.path.dirname(path)) if n.endswith(".bak.json")]
        self.assertEqual(len(backups), 1, "이전 저장본은 덮어쓰지 않고 보관")

    def test_key_never_written_or_logged(self):
        from hazop.study.claude_http import ClaudeHttpClient
        seen = []
        lock = threading.Lock()

        def opener(url, headers, body, timeout):
            with lock:
                seen.append(headers.get("x-api-key"))
                n = len(seen)
            if n % 3 == 0:  # 서버 오류 본문에 키가 섞여 와도 남지 않아야 함
                return 401, json.dumps({"error": {"message": "invalid x-api-key %s" % KEY}}).encode("utf-8")
            req = json.loads(body.decode("utf-8"))
            ids = asked({"user": req["messages"][0]["content"][1]["text"]})
            doc = {"model": MODEL, "stop_reason": "end_turn", "usage": dict(USAGE),
                   "content": [{"type": "text", "text": json.dumps(output_for(ids), ensure_ascii=False)}]}
            return 200, json.dumps(doc, ensure_ascii=False).encode("utf-8")

        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        handler = Grab(logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            win, scr = self.screen()
            scr.make_client = lambda: ClaudeHttpClient(win.api_keys.get, opener=opener)
            self.run_and_wait(scr)
        self.assertTrue(seen and all(k == KEY for k in seen), "키는 요청 헤더로만 감")
        from hazop.study import ai_cells
        self.assertTrue(ai_cells.failed_cells(scr.results), "401 응답 칸은 실패로 남음")
        self.assertNotIn(KEY, json.dumps(scr.results, ensure_ascii=False))
        hits = []
        for base, _dirs, files in os.walk(self.tmp):
            for name in files:
                with open(os.path.join(base, name), "rb") as fh:
                    if KEY.encode("utf-8") in fh.read():
                        hits.append(os.path.join(base, name))
        self.assertEqual(hits, [], "임시 루트의 어떤 파일에도 키가 없음")
        self.assertNotIn(KEY, "\n".join(records) + out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
