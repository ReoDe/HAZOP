"""⑤ AI 실행 흐름: 상태 기계(기술 설계 §6.4), 작업자 N개, 구독 경로 전체(가짜 CLI), 한도·취소·창 닫기, 이어서 실행,
결과 기록(칸 상세·Excel·시험용 파일). 실행: python -m unittest tests.test_ai_run_flow

실제 구독·실제 API 호출은 없다. 구독은 tests/fake_claude_flow.py(가짜 CLI)를 ClaudeCliClient(argv_prefix=…)로 주입하고,
API 키 경로는 analyze만 있는 가짜 클라이언트를 쓴다. 작업 루트·저장 루트·설정·한도 파일은 모두 임시 폴더.
"""

import collections
import copy
import glob
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from hazop import paths  # noqa: E402
from tests.test_ai_screen import FakeClient  # noqa: E402
from tests.test_app import REPO_ROOT, build_temp_drawing, tearDownModule, wait_for  # noqa: E402,F401

RESULTS = 6
KEY = "sk-ant-api03-TESTKEY-must-never-be-written-0123456789"
FLOW = os.path.join(REPO_ROOT, "tests", "fake_claude_flow.py")


# ---------------------------------------------------------------- 상태 기계(Qt 없음)

class RunMachineTest(unittest.TestCase):
    def setUp(self):
        from hazop.app import ai_runner
        self.t, self.alive, self.ended = ai_runner.TRANSITIONS, ai_runner.PROCESS_ALIVE, ai_runner.PROCESS_ENDED

    def test_table_matches_design_counts(self):
        self.assertEqual(len(self.t), 8, "상태 8개(§6.4)")
        self.assertEqual(sum(len(v) for v in self.t.values()), 33, "전이 32개(§6.4) + 닫기 거절")
        self.assertEqual(self.t["closed"], {"close_refused": "idle"}, "closed에서 나가는 길은 창이 닫기를 거절할 때뿐")

    def test_closed_reachable_from_every_state(self):
        for start in self.t:
            seen, todo = {start}, [start]
            while todo:
                for nxt in self.t[todo.pop()].values():
                    if nxt not in seen:
                        seen.add(nxt)
                        todo.append(nxt)
            self.assertIn("closed", seen, "%s에서 closed에 닿음" % start)

    def test_live_process_handles_window_close_and_timeout(self):
        for s in self.alive:
            closing = s in ("close_wait", "killing_close")
            self.assertTrue(closing or ("close_wait" in self.t[s] and "close_now" in self.t[s]),
                            "%s: 창 닫기 두 가지를 모두 받음" % s)
            killing = s in ("killing", "killing_close")
            self.assertTrue(killing or "timeout" in self.t[s], "%s: 시간 초과를 받음" % s)
            self.assertTrue(not killing or "killed" in self.t[s], "%s: 종료 완료를 받음" % s)

    def test_never_closed_while_process_alive(self):
        for s in self.alive:
            for event, nxt in self.t[s].items():
                if nxt in ("closed", "idle"):
                    self.assertIn(event, self.ended, "%s --%s--> %s는 프로세스가 끝난 사건이어야 함" % (s, event, nxt))

    def test_machine_ignores_events_not_in_table(self):
        from hazop.app.ai_runner import RunMachine
        m = RunMachine()
        self.assertIsNone(m.fire("cancel"), "idle의 취소는 무시")
        self.assertEqual(m.fire("start"), "preflight")
        self.assertTrue(m.busy)
        self.assertFalse(m.alive, "확인 중에는 프로세스 없음")
        self.assertEqual(m.fire("check_ok"), "calling")
        self.assertTrue(m.alive)
        self.assertEqual(m.fire("cancel"), "draining")
        self.assertEqual(m.fire("cancel"), "killing", "기다리는 중 한 번 더 누르면 끊음")
        self.assertEqual(m.fire("close_wait"), "killing_close")
        self.assertIsNone(m.fire("wait_expired"))
        self.assertEqual(m.fire("killed"), "closed")


# ---------------------------------------------------------------- 공통 준비

class FlowCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-ai-flow-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT", "PYTHONUTF8")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.environ["PYTHONUTF8"] = "1"  # 원본 가짜 CLI(fake_claude.py)가 콘솔 코드 페이지로 쓰지 않게(보고서 참고)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        _out_dir, cls.graph = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        from hazop.graph import project
        from hazop.study import nodes
        cls.pg = project.load(project.project_id_of(cls.graph))
        cls.node_set = nodes.confirm(nodes.propose(cls.pg), cls.pg, "검토자A")
        nodes.save(cls.node_set)
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.case = tempfile.mkdtemp(dir=self.tmp)
        self.limits = os.path.join(self.case, "ai_limits.json")
        self.state = os.path.join(self.case, "fake")
        self.addCleanup(self.clean_results)  # 창을 닫으며 저장한 뒤(가장 나중)에 지운다

    @staticmethod
    def clean_results():
        from hazop import paths
        for d in ("analysis-results", "analysis-results-test"):
            shutil.rmtree(paths.folder(d), ignore_errors=True)

    def window(self, method="subscription", scenarios="ok", terms=True, concurrency=1, debug=False, api_client=None):
        """구독은 가짜 CLI, API 키는 api_client(가짜). 창을 닫을 때 묻는 창은 시험이 정한 답(기본: 바로 끊음).
        method=None이면 방식을 고르지 않은 개발자 PC: 앱 시작 확인(start)으로 앱이 방식을 정한다."""
        from hazop.app.main_window import MainWindow
        from hazop.study import claude_cli
        win = MainWindow(settings_path=os.path.join(self.case, "settings.json"), ask_reviewer=False, debug=debug)
        self.addCleanup(win.deleteLater)
        win.resize(1440, 860)
        win.api_keys.set(KEY, persist=False)
        run_root = os.path.join(self.case, "run")
        win.ai_conn.cli_factory = lambda path, **kw: claude_cli.ClaudeCliClient(
            argv_prefix=[sys.executable, FLOW, scenarios, self.state], limits_path=self.limits, run_root=run_root,
            **kw)
        if method:
            win.ai_prefs.choose(method)
        else:
            win.ai_conn.start()
            self.assertTrue(wait_for(lambda: win.ai_conn.status("subscription")["state"] != "checking", 30))
        if terms:
            win.ai_prefs.ack_terms()
        win.settings["ai_concurrency"] = concurrency
        win.show()
        win.go(RESULTS)
        scr = win.screens[RESULTS]
        scr.ask_close = lambda n: "now"
        if api_client is not None:
            default = scr.make_client
            scr.make_client = lambda: api_client if scr.run_method == "api" else default()

        def close():
            scr.ask_close = lambda n: "now"
            win.close()
            wait_for(lambda: not win.isVisible() and not scr.runner, 30)
            win.ai_conn.tasks.wait(20000)
        self.addCleanup(close)
        win.close_for_test = close
        self.assertEqual(scr.stack.currentIndex(), 1, "확정 구간이 있으면 행렬 화면")
        return win, scr

    def calls(self):
        return len(glob.glob(os.path.join(self.state, "call-*")))

    def units(self, node_only=True):
        from hazop.study import ai_cells, results as res
        ns = self.node_set
        if node_only:
            ns = dict(ns, nodes=ns["nodes"][:1])
        return ai_cells.plan_units(ns, res.load_deviations())

    def run_node(self, scr, ask=None, wait=True):
        """첫 구간만 실행(실행 확인은 ask가 답한다, 기본 시작). 끝날 때까지 기다린다."""
        scr.matrix.setCurrentCell(0, 0)
        seen = {}

        def fake_ask(dlg):
            seen.setdefault("texts", []).append(dlg.texts())
            seen.setdefault("dialogs", []).append(dlg)
            return ask(dlg) if ask else "start"
        self._ask = mock.patch("hazop.app.screens.results.RunConfirmDialog.ask", fake_ask)
        self._ask.start()
        self.addCleanup(self._ask.stop)
        self.assertTrue(scr.request_ai("node"), "실행 요청이 받아짐")
        if wait:
            self.assertTrue(wait_for(lambda: not scr.running(), 60), "실행이 끝남")
        return seen

    def saved(self, test=False):
        from hazop.study import results as res
        path = (res.test_store_path if test else res.store_path)(self.node_set.get("project_id"),
                                                                  self.node_set["graph_id"])
        return res.read(path)

    def cell_texts(self, scr, row=0):
        return [scr.matrix.item(row, c).text() for c in range(scr.matrix.columnCount())]

    def fix_reset_clock(self, other_day):
        """가짜 CLI의 한도 재설정 시각을 한 시간 뒤로 고정하고, 앱의 '지금'을 그 시각과 같은 날(또는 하루 전)로 맞춘다.
        돌리는 시각(자정 근처 등)과 무관하게 표시가 정해진다. 기대하는 재설정 표시 글자를 돌려준다."""
        import datetime
        from hazop.app import conn_view
        resets = int(time.time()) + 3600
        at = conn_view._kst(resets)
        now = at - datetime.timedelta(days=1) if other_day else at.replace(hour=0, minute=0, second=0)
        env = mock.patch.dict(os.environ, {"FAKE_CLAUDE_RESETS_AT": str(resets)})
        clock = mock.patch.object(conn_view, "_now", lambda: now)
        for p in (env, clock):
            p.start()
            self.addCleanup(p.stop)
        return at.strftime("%m-%d %H:%M" if other_day else "%H:%M")


# ---------------------------------------------------------------- 구독 경로(가짜 CLI)

@unittest.skipUnless(sys.platform == "win32", "가짜 CLI는 claude_cli의 Windows 프로세스 정리를 쓴다")
class SubscriptionFlowTest(FlowCase):
    def test_normal_run_has_no_dollar_and_records_subscription(self):
        win, scr = self.window(scenarios="slow,ok")
        seen = self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner is not None and scr.progress.value() == 0
                                 and scr.run_info and scr.run_info["unit"], 30), "첫 호출 중")
        label, tip = scr.progress_label.text(), scr.progress_label.toolTip()
        self.assertIn("구독 사용량 차감", label)
        self.assertNotIn("$", label + tip + win.msg_label.text(), "구독 진행 줄·도구 설명·상태줄에 $ 없음")
        self.assertIn("구독 사용량에서 차감", tip)
        self.assertNotIn("실행 중", win.conn_chip.text(), "칩 글자는 그대로(진행은 상세 창에만)")
        self.assertIn("AI 분석 실행 중", win.ai_conn.progress)
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        text = "\n".join(seen["texts"])
        self.assertIn("AI를 %d회 호출해" % len(self.units()), text)
        self.assertIn("건별 요금 없음. 구독 사용량에서 차감", text)
        self.assertIn("한도에 닿으면 남은 호출을 멈추고", text)
        self.assertNotIn("$", text, "구독 실행 확인에 $ 없음")
        dlg = seen["dialogs"][0]
        self.assertEqual(dlg.start_btn.text(), "시작(&S)")
        self.assertTrue(dlg.start_btn.isDefault(), "시작이 기본 단추")
        self.assertEqual(dlg.width(), 460)
        cost = [w for w in dlg.values["비용"]][0]
        self.assertEqual(cost.accessibleName(), "비용: 건별 요금 없음, 구독 사용량에서 차감")
        doc = self.saved()
        nid = self.node_set["nodes"][0]["node_id"]
        runs = [c["ai_run"] for c in doc["cells"] if c["node_id"] == nid]
        self.assertTrue(all(r["via"] == "subscription" and r["status"] == "ok" for r in runs))
        self.assertTrue(all(r["cost_usd"] is None for r in doc["ai_log"]), "구독 기록의 요금은 null")
        self.assertEqual(self.calls(), len(self.units()))
        self.assertNotIn("$", win.msg_label.text() + scr.usage.text() + scr.kpi.toolTip())
        self.assertIn("구독 %d회(Opus 5.5)" % len(self.units()), scr.usage.text())
        scr.open_cell(nid, scr.deviations[0]["deviation_id"])
        self.assertRegex(scr.sheet_source.text(), r"^AI 초안 · Opus 5\.5 · Claude 구독 · \d\d-\d\d \d\d:\d\d KST$")
        self.assertEqual(scr.run_all_btn.toolTip(), "Claude 구독 · Opus 5.5로 실행합니다")

    def test_login_required_shows_resolve_instead_of_confirm(self):
        _win, scr = self.window(scenarios="logged_out")
        shown = []
        scr.show_resolve = lambda method, status: shown.append((method, status["state"])) or None
        seen = self.run_node(scr)
        self.assertEqual(shown, [("subscription", "login_required")], "해결 안내")
        self.assertNotIn("texts", seen, "실행 확인은 뜨지 않음")
        self.assertEqual(self.calls(), 0)
        self.assertEqual(scr.machine.state, "idle")

    def test_resolve_dialog_lists_fix_actions(self):
        from hazop.app.screens.results import ResolveDialog
        dlg = ResolveDialog("subscription", {"state": "login_required"})
        self.addCleanup(dlg.deleteLater)
        self.assertIn("터미널에서 claude auth login", dlg.band.text.text())
        self.assertEqual([b.text() for b in dlg.band.btns.values()], ["로그인 방법 보기(&L)", "다시 확인(&R)"])
        dlg.band.btns["check"].click()
        self.assertEqual(dlg.choice, "check")

    def test_first_subscription_run_asks_terms_once(self):
        _win, scr = self.window(scenarios="ok", terms=False)
        asked = []
        with mock.patch("hazop.app.screens.results.ask_terms", lambda parent, prefs, context: asked.append(context)):
            seen = self.run_node(scr)
        self.assertEqual(asked, ["run"])
        self.assertNotIn("texts", seen, "이용 조건을 확인하지 않으면 실행 확인으로 가지 않음")
        self.assertEqual(self.calls(), 0)

    def test_limit_reached_halts_marks_cells_band_and_resume(self):
        from PySide6.QtWidgets import QApplication
        from hazop.app.screens.results_paint import CELL_ROLE
        from hazop.study import ai_cells
        units = self.units()
        self.assertGreaterEqual(len(units), 3, "시험에는 호출 3회 이상인 구간이 필요")
        reset = self.fix_reset_clock(other_day=False)
        win, scr = self.window(scenarios="ok,rejected")
        scr.matrix.setFocus()
        self.run_node(scr)
        self.assertEqual(self.calls(), 2, "한도에 닿으면 남은 호출을 부르지 않음")
        texts = self.cell_texts(scr)
        n_first, n_second = len(units[0]["deviation_ids"]), len(units[1]["deviation_ids"])
        self.assertEqual(texts.count("한도로 멈춤"), n_second)
        col = next(i for i, d in enumerate(scr.deviations) if d["deviation_id"] == units[1]["deviation_ids"][0])
        self.assertEqual(scr.matrix.item(0, col).data(CELL_ROLE), {"kind": "limit"}, "실패와 다른 칸 모양")
        self.assertEqual(texts.count("분석 전"), len(texts) - n_first - n_second, "부르지 않은 칸은 분석 전")
        self.assertFalse(scr.run_band.isHidden())
        self.assertEqual(scr.run_band.kind, "limit_reached")
        body = scr.run_band.text.text()
        left = len(units) - 1
        self.assertIn("구독 사용 한도에 닿아 AI 분석을 멈췄습니다.", body)
        self.assertIn("호출 %d회 중 1회의 결과(%d칸)는 저장했습니다." % (len(units), n_first), body)
        self.assertIn("남은 %d회(%d칸)는 %s 재설정 뒤에" % (left, len(texts) - n_first, reset), body,
                      "같은 날이면 시각만")
        self.assertEqual(scr.run_band.accessibleName(), "알림: 구독 사용 한도에 닿아 AI 분석을 멈춤")
        first = scr.run_band.first_button()
        self.assertEqual(first.text(), "남은 칸 이어서 실행(&C)")
        self.assertEqual(list(scr.run_band.btns), ["resume", "resume_api", "close"])
        QApplication.processEvents()
        self.assertFalse(scr.run_band.isAncestorOf(QApplication.focusWidget()), "띠가 포커스를 빼앗지 않음")
        scr.keys["F6"].activated.emit()
        self.assertIs(QApplication.focusWidget(), first, "F6 = 띠의 첫 단추")
        self.assertIn("멈춤(한도 도달)", win.msg_label.text())
        self.assertIn("한도 도달", win.conn_chip.wide)
        self.assertEqual(win.ai_conn.status("subscription")["state"], "limit_reached")
        # 이어서 실행 범위: 한도로 멈춘 칸 + 부르지 않은 호출 단위를 일괄 실행과 같은 묶음으로
        expect = ai_cells.plan_units(dict(self.node_set, nodes=self.node_set["nodes"][:1]), scr.deviations,
                                     [(units[0]["node_id"], d) for u in units[1:] for d in u["deviation_ids"]],
                                     group=True)
        self.assertEqual(scr._plan("resume"), expect)
        self.assertEqual(scr._plan("resume"), units[1:], "칸 하나당 호출 하나로 늘지 않음")
        seen = {}
        with mock.patch("hazop.app.screens.results.RunConfirmDialog.ask",
                        lambda dlg: seen.setdefault("text", dlg.texts()) and "start"):
            first.click()
            self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertIn("AI를 %d회 호출해" % left, seen["text"], "아직 한도여도 이어서 실행은 부름(재설정 전에도 누를 수 있음)")
        self.assertEqual(self.calls(), 3)
        self.assertFalse(scr.run_band.isHidden(), "첫 호출에서 같은 띠가 다시 뜸")

    def test_limit_reset_on_another_day_shows_date(self):
        reset = self.fix_reset_clock(other_day=True)
        win, scr = self.window(scenarios="ok,rejected")
        self.run_node(scr)
        self.assertEqual(scr.run_band.kind, "limit_reached")
        self.assertIn("는 %s 재설정 뒤에" % reset, scr.run_band.text.text(), "다른 날이면 날짜(MM-DD)도 붙임")
        self.assertIn("%s 재설정" % reset, win.conn_chip.wide, "칩도 같은 규칙")

    def test_reset_time_rechecks_and_toasts_without_running(self):
        from hazop.study import claude_cli
        win, scr = self.window(scenarios="ok,rejected")
        self.run_node(scr)
        self.assertTrue(scr._reset_timer.isActive(), "재설정 시각에 다시 확인하도록 맞춰 둠")
        claude_cli.save_limit(self.limits, {"status": "limit_ok", "window": "seven_day",
                                            "resets_at": int(time.time()) - 10, "utilization": 0.1})
        toasts = []
        win.toast = lambda text, undo=None, actions=(), ms=5000: toasts.append((text, [a[0] for a in actions]))
        scr._limit_reset_check()
        self.assertTrue(wait_for(lambda: toasts, 30))
        cells = sum(len(u["deviation_ids"]) for u in self.units()[1:])
        self.assertEqual(toasts, [("구독 한도가 재설정됐습니다. 남은 %d칸을 이어서 실행할 수 있습니다." % cells, ["이어서 실행"])])
        self.assertEqual(win.ai_conn.status("subscription")["state"], "ok", "칩은 연결됨으로")
        self.assertFalse(scr.running(), "자동으로 실행하지 않음(D2)")
        self.assertEqual(self.calls(), 2)

    def test_resume_with_api_key_is_this_run_only(self):
        api = FakeClient()
        gate = threading.Event()
        api.on_call = lambda n: gate.wait(20)
        win, scr = self.window(scenarios="ok,rejected", api_client=api)
        self.run_node(scr)
        self.assertEqual(scr.run_band.kind, "limit_reached")
        left = len(self.units()) - 1
        seen = {}
        with mock.patch("hazop.app.screens.results.RunConfirmDialog.ask",
                        lambda dlg: seen.setdefault("text", dlg.texts()) and "start"):
            scr.run_band.btns["resume_api"].click()
            self.assertTrue(wait_for(lambda: len(api.calls) >= 1, 30), "API 키로 부름")
            self.assertIn("이번 실행만", win.conn_chip.wide, "칩: API 키 · 모델 · 이번 실행만")
            self.assertTrue(win.conn_chip.wide.startswith("API 키"))
            gate.set()
            self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertIn("이번 남은 호출만 API 키로 돌립니다. 끝나면 Claude 구독으로 돌아갑니다.", seen["text"])
        self.assertIn("AI를 %d회 호출해" % left, seen["text"])
        self.assertIn("$", seen["text"], "API 키 기준 확인 창은 예상 비용을 보임")
        self.assertEqual(len(api.calls), left)
        self.assertEqual(win.ai_conn.method, "subscription", "방식은 구독 그대로")
        self.assertEqual(win.ai_prefs.chosen_method, "subscription", "설정 파일의 방식도 그대로")
        self.assertIsNone(win.ai_conn.run_override)
        self.assertTrue(win.conn_chip.wide.startswith("구독"), "끝나면 칩도 구독으로")
        vias = collections.Counter(r["via"] for r in self.saved()["ai_log"])
        self.assertEqual(vias, {"subscription": 2, "api": left})
        scr.open_cell(self.node_set["nodes"][0]["node_id"], scr.deviations[0]["deviation_id"])
        shown = []
        scr.show_resolve = lambda method, status: shown.append((method, status["state"])) or None
        scr.run_ai("cell")
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertEqual(shown, [("subscription", "limit_reached")], "다음 실행은 다시 구독(아직 한도라 해결 안내)")
        self.assertEqual(len(api.calls), left, "API 키로 번지지 않음")

    def test_resume_stays_on_app_chosen_subscription(self):
        """앱이 정한 방식(구독)은 실행 전 확인에서 다시 정하지 않는다. 한도 뒤 '남은 칸 이어서 실행'은 몇 번을 눌러도 구독."""
        api = FakeClient()
        win, scr = self.window(method=None, scenarios="ok,rejected", api_client=api)
        self.assertEqual((win.ai_conn.method, win.ai_prefs.chosen_method), ("subscription", None))
        self.run_node(scr)
        self.assertEqual(scr.run_band.kind, "limit_reached")
        seen = []
        with mock.patch("hazop.app.screens.results.RunConfirmDialog.ask", lambda dlg: seen.append(dlg.texts()) or "start"):
            for _ in range(2):
                scr.run_band.btns["resume"].click()
                self.assertTrue(wait_for(lambda: not scr.running(), 60))
                self.assertEqual(scr.run_band.kind, "limit_reached", "아직 한도라 같은 띠")
                self.assertEqual(win.ai_conn.method, "subscription", "확인이 한도를 봐도 방식은 그대로")
        self.assertEqual(len(seen), 2)
        self.assertTrue(all("$" not in t and "이번 남은 호출만" not in t for t in seen), "구독 확인 창")
        self.assertEqual(api.calls, [], "API 키로 부르지 않음")
        self.assertEqual({r["via"] for r in self.saved()["ai_log"]}, {"subscription"})

    def test_failed_rerun_while_viewing_test_file_uses_real_failed_cells(self):
        """시험 결과를 보는 중 구독으로 '실패 칸 다시 실행': 실패 칸은 실행이 쓸 실제 결과에서 뽑는다."""
        from hazop.study import results as res
        _win, scr = self.window(scenarios="ok", debug=True)
        self.run_node(scr)
        real = self.saved()
        nid = self.node_set["nodes"][0]["node_id"]
        test = res.empty_results(self.node_set, scr.deviations)
        dids = [d["deviation_id"] for d in scr.deviations[:3]]
        for c in test["cells"]:
            if c["node_id"] == nid and c["deviation_id"] in dids:
                c["ai_run"] = {"status": "failed", "error": "응답 없음", "at": "2026-11-09T01:00:00Z", "model": None,
                               "note": None, "applicable": None, "via": "fixed", "error_kind": "bad_output"}
        res.write(res.test_store_path(self.node_set.get("project_id"), self.node_set["graph_id"]), test)
        scr.set_fixed_view(True)
        n0 = self.calls()
        self.assertFalse(scr.run_ai("failed"), "실제 결과에는 실패 칸이 없음")
        self.assertEqual(self.calls(), n0)
        self.assertEqual(self.saved(), real, "실제 결과의 AI 초안을 덮지 않음")
        self.assertTrue(scr.fixed_view, "시작하지 않았으니 보기도 그대로")

    def test_overage_risk_asks_before_start(self):
        from hazop.study import claude_cli
        claude_cli.save_limit(self.limits, {"status": "limit_warning", "window": "five_hour",
                                            "resets_at": int(time.time()) + 3600, "utilization": 0.95,
                                            "overage": "on", "seen_at": claude_cli.now_kst()})
        _win, scr = self.window(scenarios="ok")
        asked = []
        scr.ask_overage = lambda: asked.append(1) and False
        seen = self.run_node(scr)
        self.assertEqual(asked, [1], "초과 사용이 켜져 있고 한도가 거의 차면 시작 전에 묻는다")
        self.assertNotIn("texts", seen)
        self.assertEqual(self.calls(), 0)

    def test_overage_in_use_keeps_result_but_halts(self):
        _win, scr = self.window(scenarios="overage")
        self.run_node(scr)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(scr.run_band.kind, "overage")
        run = next(c["ai_run"] for c in self.saved()["cells"] if c.get("ai_run"))
        self.assertEqual((run["status"], run["error_kind"]), ("ok", "overage"), "받은 결과는 반영")

    def test_login_lost_mid_run_band_then_recheck_offers_resume(self):
        _win, scr = self.window(scenarios="ok,notlogged")
        self.run_node(scr)
        self.assertEqual(self.calls(), 2)
        self.assertEqual(scr.run_band.kind, "login")
        self.assertIn("Claude Code 로그인이 풀려 AI 분석을 멈췄습니다.", scr.run_band.text.text())
        self.assertEqual(list(scr.run_band.btns), ["login_help", "recheck", "close"])
        scr.run_band.btns["recheck"].click()
        self.assertTrue(wait_for(lambda: "resume" in scr.run_band.btns, 30), "확인에 성공하면 '다시 확인' 자리에 이어서 실행")
        self.assertEqual(list(scr.run_band.btns), ["login_help", "resume", "close"])

    def test_auth_mismatch_band_says_charges(self):
        _win, scr = self.window(scenarios="console")
        self.run_node(scr)
        self.assertEqual(scr.run_band.kind, "not_subscription")
        self.assertIn("이대로 쓰면 건마다 요금이 나갑니다.", scr.run_band.text.text())

    def test_cancel_receives_in_flight_call(self):
        _win, scr = self.window(scenarios="slow")
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.run_info and scr.run_info["unit"], 30))
        scr.cancel_ai()
        self.assertEqual(scr.machine.state, "draining")
        self.assertEqual(scr.cancel_btn.text(), "바로 끊기")
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertEqual(self.calls(), 1, "남은 호출은 부르지 않음")
        nid = self.node_set["nodes"][0]["node_id"]
        done = [c for c in self.saved()["cells"] if c["node_id"] == nid and c.get("ai_run")]
        self.assertTrue(done and all(c["ai_run"]["status"] == "ok" for c in done), "진행 중이던 1건은 받아 저장")
        self.assertTrue(scr.run_band.isHidden(), "취소에는 띠가 없음")

    def test_second_cancel_kills_in_flight_call(self):
        _win, scr = self.window(scenarios="hang")
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: self.calls() == 1 and scr.runner.calls_in_flight() == 1, 30))
        scr.cancel_ai()
        t0 = time.monotonic()
        scr.cancel_ai()
        self.assertIn(scr.machine.state, ("killing", "idle"))
        self.assertTrue(wait_for(lambda: not scr.running(), 30), "바로 끊김")
        self.assertLess(time.monotonic() - t0, 20)
        run = next(c["ai_run"] for c in self.saved()["cells"] if c.get("ai_run"))
        self.assertEqual(run["error_kind"], "cancelled")
        self.assertEqual(scr.last_run and len(scr.last_run["cells"]), sum(len(u["deviation_ids"]) for u in self.units()),
                         "끊긴 칸과 부르지 않은 칸이 이어서 실행 대상")

    def test_close_without_run_closes_at_once(self):
        win, scr = self.window(scenarios="ok")
        win.close()
        self.assertFalse(win.isVisible())
        self.assertEqual(scr.machine.state, "closed")

    def test_close_wait_receives_in_flight_then_closes(self):
        win, scr = self.window(scenarios="slow")
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        asked = []
        scr.ask_close = lambda n: asked.append(n) or "wait"
        win.close()
        self.assertEqual(asked, [1], "진행 중인 호출이 있을 때만 묻는다")
        self.assertTrue(win.isVisible(), "기다리는 동안 창은 열려 있음")
        self.assertEqual(scr.machine.state, "close_wait")
        self.assertTrue(wait_for(lambda: scr._close_wait_box.isVisible(), 5))
        self.assertRegex(scr._close_wait_box.label.text(), r"\d:\d\d 뒤에는 끊고 닫습니다")
        self.assertTrue(wait_for(lambda: not win.isVisible(), 60), "호출이 끝나면 닫힘")
        self.assertEqual(scr.machine.state, "closed")
        self.assertEqual(self.calls(), 1, "남은 호출은 부르지 않음")
        self.assertTrue(any((c.get("ai_run") or {}).get("status") == "ok" for c in self.saved()["cells"]),
                        "받은 칸을 저장")

    def test_close_now_kills_and_closes(self):
        win, scr = self.window(scenarios="hang")
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        t0 = time.monotonic()
        scr.ask_close = lambda n: "now"
        win.close()
        self.assertTrue(wait_for(lambda: not win.isVisible(), 30))
        self.assertLess(time.monotonic() - t0, 20, "바로 끊고 닫음")
        self.assertEqual(scr.machine.state, "closed")

    def test_close_wait_expires_then_kills(self):
        win, scr = self.window(scenarios="hang")
        scr.CLOSE_WAIT_SEC = 1
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        scr.ask_close = lambda n: "wait"
        win.close()
        self.assertTrue(wait_for(lambda: not win.isVisible(), 30), "대기 시간이 지나면 끊고 닫음")
        self.assertEqual(scr.machine.state, "closed")

    def test_call_ending_while_asking_closes_at_once(self):
        win, scr = self.window(scenarios="slow")
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        scr.cancel_ai()

        def ask(n):
            wait_for(lambda: not scr.running(), 60)  # 물음 창이 떠 있는 동안 진행 중이던 호출이 끝남
            return "wait"
        scr.ask_close = ask
        win.close()
        self.assertFalse(win.isVisible(), "끝난 뒤에는 기다릴 것이 없어 바로 닫힘")
        self.assertEqual(scr.machine.state, "closed")

    def test_close_cancelled_keeps_running(self):
        win, scr = self.window(scenarios="slow")
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        scr.ask_close = lambda n: None
        win.close()
        self.assertTrue(win.isVisible())
        self.assertEqual(scr.machine.state, "calling")
        scr.cancel_ai()
        self.assertTrue(wait_for(lambda: not scr.running(), 60))


# ---------------------------------------------------------------- 동시 호출·API 키·고정 응답·기록

class ConcurrencyAndRecordTest(FlowCase):
    @staticmethod
    def normalized(doc):
        """시각·항목 ID·기록 순서를 뺀 결과(동시 수가 달라도 같아야 하는 부분)."""
        cells = []
        for c in doc["cells"]:
            entries = [{k: v for k, v in e.items() if k not in ("entry_id", "history")} for e in c["entries"]]
            run = {k: v for k, v in (c.get("ai_run") or {}).items() if k != "at"}
            cells.append((c["node_id"], c["deviation_id"], c["state"], json.dumps(entries, sort_keys=True),
                          json.dumps(run, sort_keys=True)))
        log = sorted(json.dumps({k: v for k, v in r.items() if k != "at"}, sort_keys=True) for r in doc["ai_log"])
        return sorted(cells), log

    def test_two_workers_give_same_results_as_one(self):
        out = {}
        for n in (1, 2):
            peak, live, lock = [0], [0], threading.Lock()

            class Counting(FakeClient):
                def analyze(self, request):
                    with lock:
                        live[0] += 1
                        peak[0] = max(peak[0], live[0])
                    time.sleep(0.05)
                    try:
                        return super().analyze(request)
                    finally:
                        with lock:
                            live[0] -= 1
            client = Counting()
            _win, scr = self.window(method="api", concurrency=n, api_client=client)
            self.assertTrue(scr.run_ai("all"))
            self.assertTrue(wait_for(lambda: not scr.running(), 120))
            out[n] = self.normalized(self.saved())
            self.assertEqual(peak[0], n, "동시 %d" % n)
            _win.close_for_test()
            self.clean_results()
        self.assertEqual(out[1], out[2], "동시 2의 최종 결과 = 동시 1(칸 순서 무관)")

    def test_same_error_three_times_halts_with_streak_band(self):
        client = FakeClient(fail=lambda ids: True)
        _win, scr = self.window(method="api", api_client=client)
        self.assertTrue(scr.run_ai("all"))
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertEqual(len(client.calls), 3, "같은 오류 3회면 멈춤")
        self.assertEqual(scr.run_band.kind, "streak")
        self.assertNotIn("resume_api", scr.run_band.btns)
        self.assertNotIn("구독", scr.run_band.text.text(), "API 키 실행 띠에는 구독 문구 없음")

    def test_api_confirm_shows_cost_and_key(self):
        _win, scr = self.window(method="api", api_client=FakeClient())
        seen = {}
        with mock.patch("hazop.app.screens.results.RunConfirmDialog.ask",
                        lambda dlg: seen.setdefault("text", dlg.texts()) and None):
            self.assertFalse(scr.request_ai("all"), "취소면 시작 안 함")
        text = seen["text"]
        self.assertIn("예상 비용 약 $", text)
        self.assertIn("기록이 없어 기본 어림값 호출당 $", text)
        self.assertIn("…%s" % KEY[-4:], text)
        self.assertNotIn(KEY, text)
        self.assertFalse(scr.running())

    def test_change_button_reopens_with_new_method(self):
        api = FakeClient()
        win, scr = self.window(method="api", api_client=api)
        answers = iter(["change", None])
        win.open_ai_settings = lambda method=None: win.ai_prefs.choose("subscription")
        seen = self.run_node(scr, ask=lambda dlg: next(answers))
        self.assertTrue(wait_for(lambda: len(seen["texts"]) == 2 and not scr.running(), 30), "다시 채운 확인 창")
        self.assertIn("예상 비용", seen["texts"][0])
        self.assertIn("건별 요금 없음", seen["texts"][1], "바꾼 방식으로 다시 채움")

    def test_old_records_read_as_api(self):
        from hazop.app import conn_view
        old = {"status": "ok", "model": "claude-opus-5-5", "at": "2026-11-09T05:20:00.000001Z"}
        self.assertEqual(conn_view.provenance(old), "AI 초안 · Opus 5.5 · API 키 · 11-09 14:20 KST")
        self.assertEqual(conn_view.provenance(dict(old, via="subscription", model="claude-sonnet-5-5",
                                                   model_requested="claude-opus-5-5"), excel=True),
                         "Sonnet 5.5(요청 Opus 5.5) · 구독 · 11-09 14:20")
        self.assertEqual(conn_view.usage_summary([dict(old, cost_usd=0.36, usage={"input_tokens": 1000})]),
                         "이 결과의 AI 호출: API 키 1회(Opus 5.5) $0.36 · 토큰 입력 1,000 · 출력 0")
        from hazop.study.ai_settings import AiPrefs
        prefs = AiPrefs({"reviewer_name": "갑"})
        self.assertEqual((prefs.chosen_method, prefs.concurrency, prefs.allow_overage), (None, 1, False))

    def test_api_success_clears_earlier_network_error(self):
        class Flaky(FakeClient):
            def analyze(self, request):
                r = super().analyze(request)
                if len(self.calls) == 1:
                    return {"status": "api_error", "output": None, "usage": None, "model": r["model"],
                            "error_type": "connection", "status_code": None, "error": "네트워크 오류(가짜)"}
                return r
        api = Flaky()
        win, scr = self.window(method="api", api_client=api)
        self.run_node(scr)
        self.assertEqual([r["status"] for r in self.saved()["ai_log"]][:2], ["failed", "ok"])
        self.assertEqual(win.ai_conn.status("api")["state"], "ok", "뒤의 호출이 성공했으니 연결됨")
        n = len(api.calls)
        self.assertTrue(scr.run_ai("node"), "다음 실행이 막히지 않음")
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertGreater(len(api.calls), n)

    def test_second_cancel_then_close_wait_is_capped(self):
        """API 키(끊을 수 없음)에서 취소 두 번 뒤 '기다렸다 닫기': 상한이 지나면 받은 칸을 저장하고 결과를 버린 채 닫는다."""
        gate = threading.Event()
        self.addCleanup(gate.set)
        win, scr = self.window(method="api", api_client=FakeClient(on_call=lambda n: gate.wait(60)))
        scr.CLOSE_WAIT_SEC = 1
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        scr.cancel_ai()
        scr.cancel_ai()
        self.assertEqual(scr.machine.state, "killing", "끊을 수 없어 호출이 끝나기를 기다림")
        scr.ask_close = lambda n: "wait"
        win.close()
        self.assertTrue(wait_for(lambda: not win.isVisible(), 10), "대기 상한이 지나면 닫힘")
        self.assertEqual(scr.machine.state, "closed")

    def test_second_cancel_then_close_wait_shows_time_and_close_now(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        win, scr = self.window(method="api", api_client=FakeClient(on_call=lambda n: gate.wait(60)))
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        scr.cancel_ai()
        scr.cancel_ai()
        scr.ask_close = lambda n: "wait"
        win.close()
        self.assertEqual(scr.machine.state, "killing_close")
        self.assertTrue(scr._close_wait_box.isVisible(), "남은 시간 창")
        self.assertRegex(scr._close_wait_box.label.text(), r"\d:\d\d 뒤에는 끊고 닫습니다")
        scr._close_wait_box.now_btn.click()
        self.assertTrue(wait_for(lambda: not win.isVisible(), 10), "바로 끊고 닫기")
        self.assertEqual(scr.machine.state, "closed")

    def test_close_refused_after_wait_accepts_new_run(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        api = FakeClient(on_call=lambda n: gate.wait(60))
        win, scr = self.window(method="api", api_client=api)
        self.run_node(scr, wait=False)
        self.assertTrue(wait_for(lambda: scr.runner and scr.runner.calls_in_flight() == 1, 30))
        scr.ask_close = lambda n: "wait"
        win.close()
        self.assertEqual(scr.machine.state, "close_wait")
        with mock.patch.object(type(win), "can_leave", lambda self: False):  # 기다리는 사이 저장 안 한 변경 -> '취소'
            gate.set()
            self.assertTrue(wait_for(lambda: not scr.running() and scr.runner is None, 30))
            wait_for(lambda: False, 0.5)
        self.assertTrue(win.isVisible())
        self.assertEqual(scr.machine.state, "idle", "닫기가 거절되면 다시 실행을 받음")
        n = len(api.calls)
        self.assertTrue(scr.run_ai("node"))
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertGreater(len(api.calls), n)

    def test_fixed_run_keeps_view_and_file_until_it_ends(self):
        """고정 응답 실행 중에는 '실제 결과로 돌아가기'가 막히고, 시험 값은 시험용 파일에만 들어간다."""
        from hazop.study import ai_cells, providers
        from tests.test_ai_screen import output_for
        win, scr = self.window(method="api", debug=True, api_client=FakeClient(cause="실제 AI"))
        scr.matrix.setCurrentCell(0, 0)
        self.assertTrue(scr.run_ai("node"))
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        real_before = self.saved()
        folder = os.path.join(self.case, "응답")
        os.makedirs(folder)
        units = ai_cells.plan_units(self.node_set, scr.deviations)
        ctxs = scr._contexts(units)
        for u in units:
            key = providers.fixed_key(ai_cells.build_request(u, ctxs[u["node_id"]], scr.deviations))
            with open(os.path.join(folder, key + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"output": output_for(u["deviation_ids"], "시험 원인")}, fh, ensure_ascii=False)
        win.ai_prefs.set_fixed_dir(folder)
        win.ai_prefs.choose("fixed")
        gate = threading.Event()
        self.addCleanup(gate.set)
        default = scr.make_client

        def held():
            c = default()
            analyze = c.analyze
            c.analyze = lambda req: (gate.wait(30), analyze(req))[1]
            return c
        scr.make_client = held
        with mock.patch("hazop.app.screens.results.RunConfirmDialog.ask", lambda dlg: "start"):
            self.assertTrue(scr.request_ai("all"))
            self.assertTrue(wait_for(lambda: scr.runner is not None, 30))
            self.assertTrue(scr.fixed_view)
            self.assertFalse(scr.test_band.btns["to_real"].isEnabled(), "실행 중에는 보기 전환 단추를 막음")
            self.assertFalse(scr.set_fixed_view(False), "실행 중에는 보기를 바꾸지 않음")
            self.assertTrue(scr.fixed_view)
            gate.set()
            self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertEqual(self.saved(), real_before, "실제 결과 파일은 그대로")
        self.assertEqual({r["via"] for r in self.saved(test=True)["ai_log"]}, {"fixed"})
        self.assertTrue(scr.test_band.btns["to_real"].isEnabled(), "끝나면 다시 누를 수 있음")

    def test_excel_cover_and_worksheet_column(self):
        from openpyxl import load_workbook
        _win, scr = self.window(method="api", api_client=FakeClient())
        scr.matrix.setCurrentCell(0, 0)
        self.assertTrue(scr.run_ai("node"))
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        doc = copy.deepcopy(scr.results)
        nid = self.node_set["nodes"][0]["node_id"]
        sub = next(c for c in doc["cells"] if c["node_id"] == nid)
        sub["ai_run"] = dict(sub["ai_run"], via="subscription")
        scr.results = doc
        path = scr.export_excel(os.path.join(self.case, "out.xlsx"), "all")
        wb = load_workbook(path)
        cover = {r[0].value: r[1].value for r in wb["표지·요약"].iter_rows(max_col=2)}
        cells = sum(1 for c in doc["cells"] if (c.get("ai_run") or {}).get("status") == "ok")
        self.assertEqual(sorted(cover["AI 초안 생성"].split(", ")),
                         sorted(["Opus 5.5 · 구독 1칸", "Opus 5.5 · API 키 %d칸" % (cells - 1)]))
        self.assertRegex(cover["AI 사용 요금(API 키 호출분)"], r"^\$\d+\.\d\d$")
        self.assertNotIn("시험 결과", cover)
        ws = wb["워크시트"]
        head = [c.value for c in ws[1]]
        self.assertEqual(head[-1], "AI 초안 생성")
        self.assertEqual(ws.column_dimensions[ws.cell(row=1, column=len(head)).column_letter].width, 22)
        col = [r[len(head) - 1].value for r in ws.iter_rows(min_row=2)]
        self.assertTrue(any(v and " · 구독 · " in v for v in col))
        self.assertTrue(any(v and " · API 키 · " in v for v in col))

    def test_fixed_run_uses_separate_test_file_and_band(self):
        from hazop.study import ai_cells, providers
        win, scr = self.window(method="api", debug=True, api_client=FakeClient())
        scr.matrix.setCurrentCell(0, 0)
        self.assertTrue(scr.run_ai("node"))  # 실제 결과 파일에 API 결과를 먼저 남긴다
        self.assertTrue(wait_for(lambda: not scr.running(), 60))
        real_before = self.saved()
        folder = os.path.join(self.case, "응답")
        os.makedirs(folder)
        units = ai_cells.plan_units(self.node_set, scr.deviations)
        ctxs = scr._contexts(units)
        from tests.test_ai_screen import output_for
        for u in units[:-1]:  # 마지막 호출 단위는 응답이 없다
            key = providers.fixed_key(ai_cells.build_request(u, ctxs[u["node_id"]], scr.deviations))
            with open(os.path.join(folder, key + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"output": output_for(u["deviation_ids"], "시험 원인")}, fh, ensure_ascii=False)
        win.ai_prefs.set_fixed_dir(folder)
        win.ai_prefs.choose("fixed")
        total = sum(len(u["deviation_ids"]) for u in units)
        missing = len(units[-1]["deviation_ids"])
        self.assertEqual(scr.fixed_match(), (total - missing, total), "맞는 칸 N/M")
        seen = {}

        def ask(dlg):
            seen["text"], seen["start"] = dlg.texts(), dlg.start_btn.text()
            return "start"
        with mock.patch("hazop.app.screens.results.RunConfirmDialog.ask", ask):
            self.assertTrue(scr.request_ai("all"))
            self.assertTrue(wait_for(lambda: not scr.running(), 60))
        self.assertIn("AI를 호출하지 않습니다. 저장된 응답으로 %d칸을 채웁니다." % (total - missing), seen["text"])
        self.assertIn("응답이 없는 %d칸은 '분석 전'으로 둡니다." % missing, seen["text"])
        self.assertEqual(seen["start"], "시험 시작(&S)")
        self.assertNotIn("$", seen["text"])
        self.assertTrue(scr.fixed_view)
        self.assertFalse(scr.test_band.isHidden())
        self.assertIn("시험 결과를 보는 중입니다. 고정 응답으로 채운 칸이며 실제 분석 결과가 아닙니다.",
                      scr.test_band.accessibleDescription())
        self.assertEqual(scr.test_band.accessibleName(), "알림: 시험 결과를 보는 중")
        self.assertEqual(list(scr.test_band.btns), ["to_real"])
        test_doc = self.saved(test=True)
        self.assertEqual({r["via"] for r in test_doc["ai_log"]}, {"fixed"})
        self.assertEqual(self.saved(), real_before, "실제 결과 파일은 그대로")
        self.assertIn("시험 %d/%d" % (len(units) - 1, len(units) - 1), scr.progress_label.text())
        scr.open_cell(units[0]["node_id"], units[0]["deviation_ids"][0])
        self.assertRegex(scr.sheet_source.text(), r"^시험 · 고정 응답 · \d\d-\d\d \d\d:\d\d KST$")
        from openpyxl import load_workbook
        from hazop.export import study_xlsx
        self.assertTrue(study_xlsx.default_filename("P", "2026-11-09T05:20:00Z", test=True).endswith("-시험.xlsx"))
        path = scr.export_excel(os.path.join(self.case, "test.xlsx"), "all")
        cover = load_workbook(path)["표지·요약"]
        self.assertEqual((cover["A3"].value, cover["B3"].value),
                         ("시험 결과", "시험용 고정 응답으로 채운 결과입니다. 실제 검토 결과로 쓰지 마세요."))
        self.assertEqual(cover["B3"].font.color.rgb[-6:], "991B1B")
        scr.test_band.btns["to_real"].click()
        self.assertFalse(scr.fixed_view)
        self.assertTrue(scr.test_band.isHidden())
        self.assertEqual(scr.results["ai_log"], real_before["ai_log"], "실제 결과로 돌아감")


if __name__ == "__main__":
    unittest.main()
