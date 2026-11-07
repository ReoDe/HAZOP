"""데스크톱 인터페이스 테스트 (기획서/인터페이스.md §2·§3·§8). 실행: python -m unittest discover -s tests -t .

QT_QPA_PLATFORM=offscreen으로 창을 만든다. 작업 루트(HAZOP_WORK_ROOT)·저장 루트(HAZOP_STORE_ROOT)·설정 파일은 임시 폴더로
바꿔 저장소의 출력/·자료저장소/·%APPDATA%를 건드리지 않는다. 분석 실행은 tests/run_fixture.py(고정 응답, 임시 폴더).
웹뷰는 offscreen에서 실제로 띄워 브리지(ready·highlight·highlightResult)를 확인하고, 브리지 객체 단위 검사도 따로 한다.
네트워크 사용 없음.
"""

import ast
import glob
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.run_fixture import REPO_ROOT, fresh_run_dir  # noqa: E402

APP_DIR = os.path.join(REPO_ROOT, "hazop", "app")
REGION = "region-SNP-M-102-pzr"
NETWORK_MODULES = ("socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "poplib",
                   "imaplib", "telnetlib", "websocket", "websockets", "xmlrpc", "PySide6.QtNetwork", "anthropic")


def app_sources():
    files = glob.glob(os.path.join(APP_DIR, "**", "*.py"), recursive=True)
    files += [os.path.join(REPO_ROOT, "scripts", n) for n in ("run_app.py", "check_app.py")]
    return [f for f in files if os.path.isfile(f)]


def network_imports(path):
    """파일이 가져오는 네트워크 모듈 목록(ast 기준, 문자열 속 이름은 세지 않음)."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    found = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + ["%s.%s" % (node.module, a.name) for a in node.names]
        for n in names:
            if any(n == m or n.startswith(m + ".") for m in NETWORK_MODULES):
                found.append(n)
    return found


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def pump(win=None, seconds=0.0):
    """작업 스레드를 끝내고 대기 중인 신호를 전달한다."""
    from PySide6.QtCore import QCoreApplication
    if win is not None:
        win.tasks.wait(120000)
    end = time.monotonic() + seconds
    while True:
        QCoreApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.02)


def wait_for(cond, timeout=40.0):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return bool(cond())


def tearDownModule():
    """남은 창·웹뷰 페이지를 인터프리터 종료 전에 정리한다(웹 엔진 페이지가 남은 채 종료되면 비정상 종료될 수 있음)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from hazop.app.webview import HazopWebView
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        if isinstance(w, HazopWebView):
            w.dispose()
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()


class StaticTest(unittest.TestCase):
    def test_no_network_modules(self):
        """앱 코드가 네트워크 모듈을 쓰지 않음(§8 공통 정적 검사)."""
        bad = {os.path.relpath(f, REPO_ROOT): network_imports(f) for f in app_sources()}
        bad = {k: v for k, v in bad.items() if v}
        self.assertEqual(bad, {})
        self.assertGreater(len(app_sources()), 8)

    def test_template_unchanged_script_count(self):
        """qwebchannel.js를 템플릿에 넣지 않음: 템플릿 <script> 3개 유지."""
        from hazop.viewer import build, check
        with open(build.TEMPLATE, encoding="utf-8") as fh:
            tpl = fh.read()
        self.assertEqual(check.TEMPLATE_SCRIPT_COUNT, 3)
        self.assertEqual(tpl.lower().count("<script"), 3)
        self.assertNotIn("qwebchannel", tpl.lower())

    def test_tokens_single_source(self):
        """웹뷰 CSS와 Qt 스타일이 같은 토큰 값을 쓴다."""
        from hazop.app import tokens
        css, qss = tokens.web_css(), tokens.qss()
        for k in ("ui", "valve", "hl-cause", "hl-path", "hl-safeguard"):
            self.assertIn("--%s: %s" % (k, tokens.COLORS[k]), css)
        self.assertEqual(tokens.COLORS["valve"], "#0f766e")
        self.assertEqual(tokens.COLORS["hl-safeguard"], "#c026d3")
        self.assertIn(tokens.COLORS["ui"], qss)
        self.assertIn("Malgun Gothic", qss)
        self.assertNotIn("Pretendard", css + qss)
        self.assertEqual([tokens.risk_band(r) for r in (1, 2, 3, 4, 5, None)], ["ok", "ok", "cond", "cond", "deny", None])


class AppTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src_run = fresh_run_dir()
        cls.tmp = tempfile.mkdtemp(prefix="hazop-app-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        work = os.environ["HAZOP_WORK_ROOT"]
        os.makedirs(os.path.join(work, "데이터", "구간"))
        shutil.copy(os.path.join(REPO_ROOT, "데이터", "구간", REGION + ".json"), os.path.join(work, "데이터", "구간"))
        cls.run_dir = os.path.join(work, "출력", "분석", REGION, os.path.basename(cls.src_run))
        shutil.copytree(cls.src_run, cls.run_dir)
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

    def setUp(self):
        # 테스트마다 저장 루트·설정 파일을 새로 써서 서로 영향을 주지 않게 한다
        os.environ["HAZOP_STORE_ROOT"] = tempfile.mkdtemp(prefix="store-", dir=self.tmp)
        self.settings = os.path.join(tempfile.mkdtemp(prefix="settings-", dir=self.tmp), "settings.json")

    def make_window(self):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=self.settings, ask_reviewer=False)
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(1440, 860)
        return win


class WindowTest(AppTestBase):
    def test_window_steps_and_empty_states(self):
        win = self.make_window()
        win.show()
        from hazop.app.main_window import STEPS
        for i in range(len(STEPS)):
            win.go(i)
            pump(seconds=0.05)
            self.assertEqual(win.stack.currentIndex(), i)
            self.assertTrue(win.step_buttons[i].isChecked())
        self.assertEqual(win.screens[0].list_stack.currentIndex(), 0)  # 등록된 자료 없음 안내
        self.assertEqual(win.screens[1].stack.currentIndex(), 0)       # 추출 결과 없음 안내
        self.assertEqual(win.screens[3].body.currentIndex(), 0)        # ④에서 실행을 열지 않음
        self.assertEqual(win.reviewer_label.text(), "검토자 미설정")

    def test_reviewer_setting_saved(self):
        win = self.make_window()
        win.set_reviewer_name("검토자A")
        with open(self.settings, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["reviewer_name"], "검토자A")
        self.assertIn("검토자A", win.reviewer_label.text())


class AnalysisScreenTest(AppTestBase):
    def test_open_run_candidates_and_evidence(self):
        win = self.make_window()
        self.assertTrue(win.open_run(self.run_dir))
        scr = win.screens[2]
        self.assertEqual(scr.table.rowCount(), 44)                 # 후보 44 모두 목록에
        excluded = [r for r in scr.rows if r["selection_status"] == "excluded"]
        self.assertEqual(len(excluded), 19)
        self.assertTrue(all(r["reason"] for r in excluded))          # 적용 불가 사유가 남음
        scr.filter.setCurrentIndex(2)                                # 제외만
        self.assertEqual(scr.table.rowCount(), 19)
        scr.filter.setCurrentIndex(0)
        ctx = scr.ctx
        self.assertIn("통과", scr.chip_valid.text())
        # 값이 없는 위험도 열은 '—' 대신 상태 문구
        texts = {scr.table.item(r, 0).text(): scr.table.item(r, 6).text() for r in range(scr.table.rowCount())}
        self.assertTrue(texts["p86-d08"].startswith("해당 없음"))
        self.assertIsNotNone(scr.table.cellWidget(
            next(r for r in range(scr.table.rowCount()) if scr.table.item(r, 0).text() == "p86-d09"), 6))
        for s in ctx.doc["scenarios"]:
            ev = ctx.evidence(s)
            self.assertEqual(ev["n"], len(ev["shown"]) + len(ev["estimated"]) + len(ev["unshown"]))
            self.assertGreater(ev["n"], 0)
        scr.select_candidate("deviation-p86-d09", "scenario-p86-d09-03")
        self.assertEqual(scr.cur_scenario["scenario_id"], "scenario-p86-d09-03")
        self.assertIn("근거", scr.evidence.text())
        self.assertIn("[AI] 제안", scr.scenario_view.toHtml())

    def test_change_decision_requires_reason_and_keeps_run(self):
        from hazop.analysis import candidate_edit
        win = self.make_window()
        win.set_reviewer_name("검토자A")
        win.open_run(self.run_dir)
        scr = win.screens[2]
        apath = os.path.join(self.run_dir, "analysis.json")
        with open(apath, "rb") as fh:
            before = fh.read()
        region_path = scr.ctx.region_path
        v0 = load(region_path)["region_version"]
        with self.assertRaises(candidate_edit.DecisionError):
            scr.change_decision("deviation-p86-d08", "selected", "  ")
        out = scr.change_decision("deviation-p86-d08", "selected", "도면 검토 결과 회분식 아님 확인 필요")
        self.assertEqual(out["region_version"], v0 + 1)
        self.assertIn("재분석", out["notice"])
        region = load(region_path)
        self.assertEqual(region["candidate_decisions"][-1]["decided_by"], "검토자A")
        with open(apath, "rb") as fh:
            self.assertEqual(fh.read(), before)                      # 열린 analysis.json은 바뀌지 않음

    def test_blocked_and_version_mismatch(self):
        from hazop.app.runctx import RunContext
        dst = os.path.join(self.tmp, "blocked-run")
        shutil.copytree(self.run_dir, dst)
        p = os.path.join(dst, "analysis.json")
        doc = load(p)
        doc["validation"]["status"] = "blocked"
        doc["validation"]["errors"] = ["예시 오류"]
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        win = self.make_window()
        win.open_run(dst)
        scr = win.screens[2]
        self.assertIn("예시 오류", scr.banner_blocked.messages)
        win.go(3)
        self.assertFalse(win.screens[3].btn_excel.isEnabled())       # blocked: Excel 출력 막힘
        self.assertFalse(win.screens[3].btn_save.isEnabled())
        self.assertIn("blocked", " ".join(win.screens[3].banner_info.messages))  # 막은 사유 표시
        self.assertIsNone(win.screens[3].export_excel("all"))

    def test_version_mismatch_real_compare(self):
        """현재 도면 그래프와 분석 당시 그래프의 graph_version이 실제로 다를 때(값 조작 없이)."""
        from hazop.app.runctx import RunContext
        out_dir, graph = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        run_graph = load(os.path.join(self.run_dir, "inputs", "graph.json"))
        self.assertNotEqual(run_graph["graph_version"], graph["graph_version"])
        ctx = RunContext(self.run_dir)
        self.assertTrue(ctx.version_mismatch)
        self.assertEqual(ctx.current_graph_version, graph["graph_version"])
        s = ctx.doc["scenarios"][0]
        ev = ctx.evidence(s)
        self.assertEqual(len(ev["unshown"]), ev["n"])                # 불일치면 모두 미표시
        self.assertIsNone(ctx.highlight_spec(s))                    # 강조 끔
        win = self.make_window()
        win.show()
        win.open_run(self.run_dir)
        scr = win.screens[2]
        self.assertIn("불일치", scr.banner_mismatch.label.text())
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready))
        state = []
        self.assertTrue(wait_for(lambda: (win.webview.page().runJavaScript(
            "JSON.stringify([document.getElementById('tab-drawing').disabled, document.body.classList.contains('tab-graph')])",
            0, state.append), state and json.loads(state[-1]) == [True, True])[1], 15), state)  # 도면 탭 끔, 그래프 탭만

    def test_drawing_lock_survives_viewer_reload(self):
        """회귀: 불일치 실행을 ④에서 연 뒤 ②에서 같은 도면 HTML이 다시 만들어져 재로딩되고 ④·⑤로 돌아와도 도면 탭 잠금 유지."""
        out_dir, _ = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        win = self.make_window()
        win.show()

        def drawing_disabled():
            state = []
            ok = wait_for(lambda: win.webview.bridge.is_ready, 20)
            win.webview.page().runJavaScript("document.getElementById('tab-drawing').disabled", 0, state.append)
            got = ok and wait_for(lambda: state, 10)
            return state[-1] if got else None  # 확인 못 하면 None(어느 기대값과도 같지 않음)

        def settle_state(expect):
            return wait_for(lambda: drawing_disabled() == expect, 20)

        win.open_run(self.run_dir)
        self.assertTrue(win.run_ctx.version_mismatch)
        self.assertTrue(settle_state(True), "④ 처음 열 때 도면 탭 잠금 없음")
        for target in (2, 3):
            win.go(1)                                                 # ②: 같은 도면 HTML 재생성·재로딩
            win.screens[1].select_drawing(os.path.basename(out_dir))
            time.sleep(0.05)
            win.screens[1]._load()
            self.assertTrue(settle_state(False), "②에서는 도면 탭 사용 가능")
            win.go(target)
            self.assertTrue(settle_state(True), "②에서 돌아온 %s에서 도면 탭 잠금이 풀림" % ("④" if target == 2 else "⑤"))

    def test_region_switch_closes_run_and_busy_disables(self):
        win = self.make_window()
        win.set_reviewer_name("검토자A")
        win.open_run(self.run_dir)
        scr = win.screens[2]
        self.assertTrue(scr.btn_decision.isEnabled() and scr.btn_review.isEnabled())
        other = os.path.join(os.environ["HAZOP_WORK_ROOT"], "데이터", "구간", "region-other.json")
        region = load(os.path.join(os.environ["HAZOP_WORK_ROOT"], "데이터", "구간", REGION + ".json"))
        region["region_id"] = "region-other"
        with open(other, "w", encoding="utf-8") as fh:
            json.dump(region, fh, ensure_ascii=False)
        self.addCleanup(os.remove, other)
        scr.refresh_regions()
        scr.region_combo.setCurrentIndex(scr.region_combo.findText("region-other"))
        self.assertIsNone(scr.ctx)                                    # 다른 구간: 이전 실행을 닫음
        self.assertIsNone(win.run_ctx)
        self.assertEqual(scr.body.currentIndex(), 0)
        self.assertEqual(scr.run_combo.count(), 0)                    # 그 구간의 실행 목록
        self.assertFalse(scr.btn_decision.isEnabled() or scr.btn_review.isEnabled())
        from hazop.analysis import candidate_edit
        with self.assertRaises(candidate_edit.DecisionError):
            scr.change_decision("deviation-p86-d08", "selected", "사유")
        scr.region_combo.setCurrentIndex(scr.region_combo.findText(REGION))
        scr.set_busy(True)                                           # 작업 중: 선택·실행 버튼 모두 막힘
        for w in (scr.region_combo, scr.run_combo, scr.btn_analyze, scr.btn_export, scr.btn_decision, scr.btn_rebind):
            self.assertFalse(w.isEnabled(), w)
        # 완료 콜백: 시작 당시 구간이 지금과 다르면 화면을 바꾸지 않고 알림만
        scr.set_busy(False)
        scr._analysis_done({"status": "passed", "run_dir": self.run_dir}, started_region=other)
        self.assertIsNone(scr.ctx)
        self.assertIn("다른 구간", win.msg_label.text())


class ReviewScreenTest(AppTestBase):
    def open_review(self, run_dir=None):
        win = self.make_window()
        win.set_reviewer_name("검토자A")
        win.open_run(run_dir or self.run_dir)
        win.go(3)
        return win, win.screens[3]

    def test_save_blocks_empty_risk_then_saves_new_versions(self):
        win, scr = self.open_review()
        cid = "deviation-p86-d12"
        scr.select_candidate(cid)
        self.assertEqual(scr.cid, cid)
        (sid, sf), = scr.sforms.items()
        (did, df), = scr.dforms.items()
        sf.radios.set_value("accept")
        sf.reason.setPlainText("원안 수용")
        df.radios.set_value("accept")
        df.reason.setPlainText("권고 필요")
        df.recommendation.setPlainText("가압기 고온 경보 추가 검토")
        scr.summary_reason.setText("편차 검토 요약")
        self.assertIsNone(scr.save(ask_name=False))                 # 위험도가 비어 저장 차단
        self.assertTrue(any("강도·빈도 필수" in e or "비어 있음" in e for e in scr.last_errors), scr.last_errors)
        self.assertEqual(sf.reason.toPlainText(), "원안 수용")       # 실패해도 입력 유지
        d = os.path.join(os.environ["HAZOP_STORE_ROOT"], "reviews", REGION, scr.ctx.doc["analysis_run_id"], cid)
        self.assertFalse(os.path.isdir(d) and os.listdir(d))
        for cb, v in ((sf.sev, 3), (sf.f0, 2), (sf.f, 2)):
            cb.setCurrentIndex(cb.findData(v))
        sf.sev_basis.setText("강도 근거")
        sf.f_basis.setText("빈도 근거")
        self.assertIn("잠김", sf.risk_out.text())                     # 계산 표시(직접 입력 없음)
        p1 = scr.save(ask_name=False)
        self.assertTrue(p1 and os.path.isfile(p1), scr.last_errors)
        rec = load(p1)
        rc = rec["scenario_decisions"][0]["risk_confirmation"]
        self.assertEqual((rc["severity"], rc["frequency"], rc["risk"], rc["source"]), (3, 2, 4, "human"))
        self.assertEqual(rec["reviewer_id"], "검토자A")
        self.assertEqual(rec["review_status"], "confirmed")
        with open(p1, "rb") as fh:
            b1 = fh.read()
        p2 = scr.save(ask_name=False)
        self.assertTrue(p2.endswith("v2.json"))
        with open(p1, "rb") as fh:
            self.assertEqual(fh.read(), b1)                          # 이전 파일 바이트 그대로
        self.assertEqual(scr.ctx.summary["by_candidate"][cid], "confirmed")
        out = scr.export_excel("all")
        self.assertTrue(out and out.endswith(".xlsx") and os.path.isfile(out))
        time.sleep(1.1)  # 출력 파일 이름은 초 단위 시각 — 같은 초에는 덮어쓰지 않고 막힘
        out2 = scr.export_excel("accepted_modified")
        self.assertTrue(out2 and os.path.isfile(out2) and out2 != out, scr.banner_info.messages)

    def test_reviewer_required_and_reason_required(self):
        win, scr = self.open_review()
        win.settings["reviewer_name"] = None
        scr.reviewer_edit.setText("")
        scr.select_candidate("deviation-p86-d12")
        sf = next(iter(scr.sforms.values()))
        sf.radios.set_value("defer")
        scr.summary_reason.setText("요약")
        self.assertIsNone(scr.save(ask_name=False))
        self.assertTrue(any("검토자" in e for e in scr.last_errors), scr.last_errors)
        self.assertTrue(any("사유 없음" in e for e in scr.last_errors), scr.last_errors)

    def test_ai_adopt_and_credited_safeguard_gate(self):
        win, scr = self.open_review()
        scr.select_candidate("deviation-p86-d09")
        sf = scr.sforms["scenario-p86-d09-03"]
        sf.radios.set_value("accept")
        self.assertTrue(sf.btn_ai.isEnabled())
        self.assertIsNone(sf.sev.currentData())                      # 자동 복사 없음
        sf.adopt_ai()
        rp = sf.s["risk_proposal"]
        self.assertEqual((sf.sev.currentData(), sf.f.currentData()), (rp["severity"], rp["frequency_used"]))
        self.assertEqual(sf.risk_source, "ai_proposal_adopted")
        self.assertIn("근거 확인 필요", sf.ai_note.text())
        self.assertEqual(sf.risk_confirmation()["source"], "ai_proposal_adopted")
        sf.f.setCurrentIndex(sf.f.findData(1))                       # 직접 바꾸면 human
        self.assertEqual(sf.risk_source, "human")
        row = sf.credit_rows[0]
        self.assertFalse(row["check"].isEnabled())                   # 확인 근거 없으면 선택 불가
        row["ref"].setText("DOC-001 rev.0")
        self.assertFalse(row["check"].isEnabled())
        row["desc"].setText("용량·설정·독립성 확인")
        self.assertTrue(row["check"].isEnabled())

    def test_reject_makes_dic_not_applicable(self):
        win, scr = self.open_review()
        scr.select_candidate("deviation-p86-d12")
        sf = next(iter(scr.sforms.values()))
        df = next(iter(scr.dforms.values()))
        sf.radios.set_value("reject")
        sf.reason.setPlainText("도면상 해당 원인 없음")
        self.assertFalse(df.radios.isEnabled())
        self.assertIn("해당 없음", df.na.text())
        scr.summary_reason.setText("요약")
        p = scr.save(ask_name=False)
        self.assertTrue(p, scr.last_errors)
        rec = load(p)
        dd = rec["design_improvement_decisions"][0]
        self.assertEqual((dd["decision"], dd["reason"]), ("not_applicable", "도면상 해당 원인 없음"))

    def _locked(self, mutate, name):
        dst = os.path.join(self.tmp, name, os.path.basename(self.run_dir))
        shutil.copytree(self.run_dir, dst)
        win, scr = self.open_review(dst)
        scr.select_candidate("deviation-p86-d12")
        self.assertTrue(scr.btn_excel.isEnabled())
        mutate(os.path.join(dst, "analysis.json"))
        scr.select_candidate("deviation-p86-d12")
        self.assertFalse(scr.btn_save.isEnabled())
        self.assertTrue(scr.banner_lock.messages)
        self.assertIsNone(scr.save(ask_name=False))
        self.assertFalse(scr.btn_excel.isEnabled())                   # Excel 버튼도 막힘 + 사유
        self.assertTrue(scr.banner_info.messages)
        pattern = os.path.join(os.environ["HAZOP_WORK_ROOT"], "출력", "워크시트", "**", "*.xlsx")
        before = len(glob.glob(pattern, recursive=True))
        self.assertIsNone(scr.export_excel("all"))
        self.assertEqual(len(glob.glob(pattern, recursive=True)), before)  # 파일을 만들지 않음
        return scr

    def test_hash_lock_changed(self):
        def change(p):
            with open(p, "ab") as fh:
                fh.write(b"\n")                                       # CLI --resume 재작성처럼 바이트 변경
        scr = self._locked(change, "lock-changed")
        self.assertTrue(any("바뀜" in m for m in scr.banner_lock.messages), scr.banner_lock.messages)

    def test_hash_lock_deleted(self):
        scr = self._locked(os.remove, "lock-deleted")
        self.assertTrue(any("없음" in m for m in scr.banner_lock.messages), scr.banner_lock.messages)

    def test_save_os_error_shown(self):
        from unittest import mock
        win, scr = self.open_review()
        scr.select_candidate("deviation-p86-d12")
        sf = next(iter(scr.sforms.values()))
        sf.radios.set_value("defer")
        sf.reason.setPlainText("자료 확인 후 결정")
        scr.summary_reason.setText("요약")
        with mock.patch("hazop.review.save_review", side_effect=PermissionError(13, "액세스가 거부되었습니다")):
            self.assertIsNone(scr.save(ask_name=False))
        self.assertTrue(any("저장 실패" in e for e in scr.last_errors), scr.last_errors)
        self.assertTrue(any("다음 조치" in e for e in scr.last_errors))
        self.assertEqual(sf.reason.toPlainText(), "자료 확인 후 결정")  # 입력 유지

    def test_export_os_error_shown(self):
        from unittest import mock
        win, scr = self.open_review()
        with mock.patch("hazop.app.screens.review.export_worksheet", side_effect=OSError(28, "디스크 공간 부족")):
            self.assertIsNone(scr.export_excel("all"))
        self.assertIn("Excel 출력 실패", scr.banner_info.label.text())
        self.assertTrue(any("다음 조치" in m for m in scr.banner_info.messages))

    def test_defer_clears_risk_and_sources_and_confirmed(self):
        win, scr = self.open_review()
        scr.select_candidate("deviation-p86-d09")
        sf = scr.sforms["scenario-p86-d09-03"]
        sf.radios.set_value("accept")
        for cb, v in ((sf.sev, 3), (sf.f0, 2), (sf.f, 2)):
            cb.setCurrentIndex(cb.findData(v))
        self.assertIn("잠김", sf.risk_out.text())
        sf.radios.set_value("defer")                                  # 보류: 계산 칩 지우고 미확정
        self.assertNotIn("잠김", sf.risk_out.text())
        self.assertIn("미확정", sf.risk_out.text())
        self.assertIn("AI 해석 원안 — 수정하면 사람 수정", sf.src_labels["cause"].text())
        self.assertIn("그래프 확인", sf.src_labels["safeguards"].text())
        sf.cause.setPlainText("검토자가 고친 원인")
        self.assertEqual(sf.src_labels["cause"].text(), "값 출처: 사람 수정")
        # 저장된 결정은 사람 확정 상자로 표시
        scr.select_candidate("deviation-p86-d12")
        f = next(iter(scr.sforms.values()))
        self.assertTrue(f.confirmed.isHidden())
        f.radios.set_value("defer")
        f.reason.setPlainText("자료 확인 후 결정")
        scr.summary_reason.setText("요약")
        self.assertTrue(scr.save(ask_name=False), scr.last_errors)
        f = next(iter(scr.sforms.values()))
        self.assertFalse(f.confirmed.isHidden())
        self.assertEqual(f.confirmed.objectName(), "human_box")
        self.assertIn("확정", f.confirmed.label.text())

    def test_import_prior_resets_form(self):
        """이전 검토 가져오기: 현재 폼의 수정값·위험도·결정을 모두 비운 뒤 가져온 값만 채운다."""
        win, scr = self.open_review()
        sid = "scenario-p86-d12-01"
        prior_rec = {"scenario_decisions": [{"scenario_id": "x", "decision": "defer", "reason": "이전 보류",
                                             "revised": None, "risk_confirmation": None,
                                             "ai_original": {"match_key": None}}]}
        scr.select_candidate("deviation-p86-d12")
        sf = scr.sforms.get(sid) or next(iter(scr.sforms.values()))
        prior_rec["scenario_decisions"][0]["ai_original"]["match_key"] = rv_match_key(sf.s)
        scr.prior = {"analysis_run_id": "analysis-old", "review_version": 1, "record": prior_rec}
        # 현재 폼에 다른 값을 넣어 둔다
        sf.radios.set_value("modify")
        sf.cause.setPlainText("현재 입력 원인")
        for cb, v in ((sf.sev, 4), (sf.f0, 3), (sf.f, 3)):
            cb.setCurrentIndex(cb.findData(v))
        sf.sev_basis.setText("현재 근거")
        sf.reason.setPlainText("새 사유")
        self.assertTrue(sf.import_prior(None))
        self.assertEqual(sf.radios.value(), "defer")
        self.assertEqual(sf.cause.toPlainText(), (sf.base["cause"]["value"] or ""))   # 수정값 초기화
        self.assertIsNone(sf.sev.currentData())                       # 위험도 초기화
        self.assertEqual(sf.sev_basis.text(), "")
        self.assertEqual(sf.reason.toPlainText(), "새 사유")           # 사유는 새로 기록
        self.assertEqual(sf.imported_from["analysis_run_id"], "analysis-old")
        d = sf.collect("검토자A")
        self.assertEqual((d["decision"], d["revised"], d["risk_confirmation"]), ("defer", None, None))


class ReviewLayoutTest(AppTestBase):
    def test_form_fits_1366(self):
        """1366×768에서 ⑤ 폼이 가로로 잘리지 않음: 내용 최소 폭이 스크롤 영역 폭 이하."""
        win = self.make_window()
        win.show()
        win.resize(1366, 768)
        win.open_run(self.run_dir)
        win.go(3)
        scr = win.screens[3]
        scr.select_candidate("deviation-p86-d09")
        pump(seconds=0.2)
        need = scr.scroll.widget().minimumSizeHint().width()
        have = scr.scroll.viewport().width()
        self.assertLessEqual(need, have, "폼 최소 폭 %d > 보이는 폭 %d" % (need, have))
        sf = scr.sforms["scenario-p86-d09-03"]
        for w in (sf.sev_basis, sf.f_basis, sf.sg_pick):
            right = w.mapTo(scr.scroll.widget(), w.rect().topRight()).x()
            self.assertLessEqual(right, have, w)


def rv_match_key(scenario):
    from hazop import review as rv
    return rv.scenario_match_key(scenario)


def build_temp_drawing(work):
    """작업 루트 안으로 샘플 도면을 복사해 추출·그래프를 만든다(뷰어 SVG는 작업 루트·저장 루트 안만 허용).
    반환 (추출 폴더, 그래프). 추출 경로가 달라 graph_version은 분석 실행의 그래프와 다르다."""
    from hazop.app import data
    src = [p for p in glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*")) if "SNP-M-102" in p][0]
    dst = os.path.join(work, "샘플", os.path.basename(src))
    if not os.path.isdir(dst):
        shutil.copytree(src, dst)
    ex = data.script_module("extract_drawio")
    bg = data.script_module("build_graph")
    drawio = glob.glob(os.path.join(dst, "*.drawio"))[0]
    _, out_dir = ex.run_one(drawio, os.path.join(work, "출력", "추출"))
    graph, _ = bg.build_one(os.path.join(out_dir, "extraction.json"), os.path.join(work, "출력", "그래프"))
    return out_dir, graph


class GraphOnlyViewerTest(AppTestBase):
    def test_no_svg_shows_graph_view(self):
        """SVG 없는 추출 결과 → 경고 띠 + 그래프 보기(앱이 만든 그래프 전용 HTML)."""
        from hazop.app import data
        work = os.environ["HAZOP_WORK_ROOT"]
        src = [p for p in glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio"))
               if "SNP-M-102" in p][0]
        dst = os.path.join(work, "nosvg", "SNP-M-102.drawio")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)                                         # SVG는 복사하지 않음
        ex = data.script_module("extract_drawio")
        bg = data.script_module("build_graph")
        result, out_dir = ex.run_one(dst, os.path.join(work, "출력", "추출"), svg=None)
        self.assertIsNone(result["coordinate_system"].get("svg_alignment"))
        graph, _ = bg.build_one(os.path.join(out_dir, "extraction.json"), os.path.join(work, "출력", "그래프"))
        win = self.make_window()
        win.show()
        win.go(1)
        scr = win.screens[1]
        scr.select_drawing(os.path.basename(out_dir))
        self.assertTrue(scr.info and scr.info.get("graph_only"))
        self.assertIn("그래프 보기만 가능", " ".join([scr.warn.label.text()] + scr.warn.messages))
        self.assertFalse(scr.warn.isHidden())
        self.assertEqual(scr.stack.currentIndex(), 1)
        with open(scr.info["html"], encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn('id="graphsvg"', page)
        self.assertEqual(page.count('class="gnode"'), len([n for n in graph["nodes"] if n.get("position")]))
        self.assertNotIn("<script", page.lower())
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "그래프 보기 브리지 ready 없음")
        nodes = []
        win.webview.bridge.nodeSelected.connect(nodes.append)
        win.webview.page().runJavaScript(
            "document.querySelector('#graphsvg [data-entity-id=\"entity-node-001\"]')"
            ".dispatchEvent(new MouseEvent('click',{bubbles:true}));")
        self.assertTrue(wait_for(lambda: nodes))
        self.assertEqual(nodes[-1]["entity_id"], "entity-node-001")


class RegisterScreenTest(AppTestBase):
    def test_register_extract_graph(self):
        win = self.make_window()
        scr = win.screens[0]
        sample = [p for p in glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio"))
                  if "SNP-M-102" in p][0]
        self.assertFalse(scr.set_files([sample, sample]))            # 여러 개: 아무것도 고르지 않음
        self.assertIn("한 개씩", scr.file_info.text())
        self.assertFalse(scr.btn_register.isEnabled())
        self.assertTrue(scr.set_files([sample]))
        pump(win)  # 파일 확인은 작업 스레드에서 끝난다
        self.assertTrue(scr.meta_btns["drawing_number"].isEnabled())
        self.assertIn("자동 후보", scr.meta_auto["drawing_number"].text())
        scr._confirm_candidate("drawing_number")
        self.assertEqual(scr.meta_edits["drawing_number"].text(), "SNP-M-102")
        scr.reason.setText("표제란 대조")
        scr.do_register()
        pump(win, 0.1)
        self.assertEqual(scr.list_stack.currentIndex(), 1)
        self.assertEqual(len(scr.rows), 1)
        rec = scr.rows[0]["record"]
        self.assertEqual((rec["status"], rec["drawing_number"]), ("registered", "SNP-M-102"))
        self.assertTrue(any(d["role"] == "svg" for d in rec.get("derived_files") or []))
        scr.table.selectRow(0)
        self.assertTrue(scr.btn_extract.isEnabled())
        scr.do_extract()
        pump(win, 0.1)
        self.assertIn("추출·그래프 생성 완료", scr.result.toHtml())
        name = scr.rows[0]["extract_name"]
        work = os.environ["HAZOP_WORK_ROOT"]
        ex = load(os.path.join(work, "출력", "추출", name, "extraction.json"))
        self.assertEqual(ex["coordinate_system"]["svg_alignment"]["source"], "registered_derived")
        self.assertTrue(os.path.isfile(os.path.join(work, "출력", "그래프", name, "graph.json")))
        self.assertTrue(scr.rows[0]["extracted"] and scr.rows[0]["graphed"])
        self.assertEqual(win.stack.currentIndex(), 0)                 # drawio는 자동 추출·화면 이동 없음
        win.refresh_stages()  # 레일 단계 표시: ①·② 완료(✓), ①이 현재, ④ 남음
        rail = {i: (win.step_buttons[i].text().split("\n")[0], win.step_buttons[i].property("state")) for i in (0, 1, 5)}
        self.assertEqual(rail, {0: ("✓", "now"), 1: ("✓", "done"), 5: ("4", "todo")})
        win.go(1)
        item = win.explorer.topLevelItem(0).child(0)                  # 탐색기 자료 → ① 그 행 선택
        self.assertEqual(item.text(0), rec["original_name"])
        win._explorer_clicked(item)
        self.assertEqual((win.stack.currentIndex(), scr.table.currentRow()), (0, 0))

    def test_drawio_register_does_not_auto_extract(self):
        win = self.make_window()
        scr = win.screens[0]
        self.assertTrue(scr.set_files([sample_file("SNP-M-102", "drawio")]))
        pump(win)  # 파일 확인은 작업 스레드에서 끝난다
        scr.do_register()
        pump(win, 0.1)
        pump(win, 0.1)
        self.assertEqual(scr.rows[0]["record"]["status"], "registered")
        self.assertFalse(scr.rows[0]["extracted"])
        self.assertFalse(os.path.isdir(os.path.join(os.environ["HAZOP_WORK_ROOT"], "출력", "추출", scr.rows[0]["extract_name"])))
        self.assertEqual(win.stack.currentIndex(), 0)

    def test_preview_result_of_previous_file_is_dropped(self):
        """파일 확인 중에 다른 파일을 고르면 앞 파일의 확인 결과는 화면에 쓰지 않는다."""
        win = self.make_window()
        scr = win.screens[0]
        pdf, dwg = sample_file("SNP-M-102", "pdf"), sample_file("SNP-M-101", "drawio")
        self.assertTrue(scr.set_files([pdf]))
        self.assertTrue(scr.set_files([dwg]))
        pump(win)
        self.assertEqual(scr.source_path, dwg)
        self.assertIn(os.path.basename(dwg), scr.file_info.text())
        self.assertNotIn(os.path.basename(pdf), scr.file_info.text())

    def test_multi_page_pdf_shows_pages_and_unextracted_page(self):
        from tests.test_adapter import merged_pdf
        win = self.make_window()
        scr = win.screens[0]
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        src = merged_pdf(os.path.join(tmp, "merged.pdf"), [sample_file("SNP-M-101", "pdf"), sample_file("SNP-M-102", "pdf")])
        self.assertTrue(scr.set_files([src]))
        pump(win)
        self.assertIn("PDF 3쪽", scr.file_info.text())
        scr.do_register()
        self.assertTrue(wait_for(lambda: (win.tasks.wait(1000), win.stack.currentIndex() == 1)[1], 180),
                        scr.result.toPlainText())
        text = scr.result.toPlainText()
        self.assertIn("1쪽 노드", text)
        self.assertIn("2쪽 노드", text)
        self.assertIn("3쪽 추출 안 함", text)
        self.assertEqual(scr.table.item(0, 7).text(), "2/3쪽 (미추출 1)")

    def test_pdf_register_auto_extracts_and_opens_viewer_without_graph_tab(self):
        win = self.make_window()
        win.show()
        scr = win.screens[0]
        self.assertTrue(scr.set_files([sample_file("SNP-M-102", "pdf")]))
        self.assertIn("확인 중", scr.file_info.text())
        self.assertFalse(scr.btn_register.isEnabled())
        pump(win)  # 파일 확인은 작업 스레드에서 끝난다
        self.assertIn("모든 쪽을 자동 추출", scr.file_info.text())
        scr.do_register()
        self.assertTrue(wait_for(lambda: (win.tasks.wait(1000), win.stack.currentIndex() == 1)[1], 180),
                        scr.result.toPlainText())
        row = scr.rows[0]
        self.assertEqual(row["record"]["format"], "pdf")
        self.assertTrue(row["extracted"] and row["graphed"])
        viewer = win.screens[1]
        self.assertEqual(viewer.combo.currentText(), row["extract_name"])
        self.assertTrue(viewer.info and viewer.info["html"] and not viewer.info.get("graph_only"), viewer.info)
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "② 뷰어 브리지 ready 없음")
        probe = ("JSON.stringify([document.body.classList.contains('hz-no-graph'),"
                 " getComputedStyle(document.querySelector('header .tabs')).display])")

        def state():
            got = []
            win.webview.page().runJavaScript(probe, 0, got.append)
            return json.loads(got[-1]) if wait_for(lambda: got, 10) else None

        self.assertTrue(wait_for(lambda: state() == [True, "none"], 15), state())   # ②: 'P&ID 구조' 탭 숨김
        pipes = []  # PDF 배관도 근사 점선이 아니라 배경 SVG의 실제 경로로 그린다
        win.webview.page().runJavaScript("JSON.stringify(['data-pipe-svg','data-pipe-approx'].map(function (a) {"
                                         " return document.getElementById('overlay').getAttribute(a); }))", 0, pipes.append)
        self.assertTrue(wait_for(lambda: pipes, 10))
        self.assertEqual(json.loads(pipes[-1]), [str(sum(len(viewer.info["extraction"][k]) for k in ("relations", "unresolved_connectors"))), "0"])
        win.go(2)                                                                   # ④는 그래프 탭을 그대로 씀
        self.assertTrue(wait_for(lambda: (state() or [True])[0] is False, 15), state())
        self.assertNotEqual(state()[1], "none")

    def test_drawing_and_design_document_build_knowledge_graph(self):
        """도면 등록·추출 → kg-<프로젝트> 자동 생성·③ 표시, 설계 문서 등록 → 자동 추출 항목이 ③에 근거와 함께 더해짐."""
        from hazop.app.screens import knowledge
        win = self.make_window()
        scr = win.screens[0]
        scr.project.setText("X")
        self.assertTrue(scr.set_files([sample_file("SNP-M-102", "drawio")]))
        pump(win)  # 파일 확인은 작업 스레드에서 끝난다
        scr.do_register()
        pump(win, 0.1)
        scr.table.selectRow(next(r for r, e in enumerate(scr.rows) if e["record"]["project_id"] == "X"))
        self.assertEqual(scr.btn_extract.text(), "추출·그래프 만들기")
        scr.do_extract()
        pump(win, 0.1)
        self.assertIn("지식그래프 kg-X", scr.result.toPlainText())
        kg_root = os.path.join(os.environ["HAZOP_WORK_ROOT"], "출력", "지식그래프", "kg-X")
        self.assertTrue(os.path.isfile(os.path.join(kg_root, "current.json")))
        win.go(4)
        kscr = win.screens[4]
        kscr.kg_combo.setCurrentIndex(kscr.kg_combo.findText("kg-X"))
        self.assertEqual(kscr.stack.currentIndex(), 1, kscr.empty.text())
        self.assertTrue(any(n["layer"] == "pid" for n in kscr.data["nodes"]))

        win.go(0)
        scr.material.setCurrentIndex(scr.material.findData("design_document"))
        doc_pdf = glob.glob(os.path.join(REPO_ROOT, "tests", "fixtures", "docextract", "*.pdf"))[0]
        self.assertTrue(scr.set_files([doc_pdf]))
        pump(win)  # 파일 확인은 작업 스레드에서 끝난다
        self.assertIn("자동 추출", scr.file_info.text())
        scr.do_register()
        self.assertTrue(wait_for(lambda: (win.tasks.wait(1000), win.stack.currentIndex() == 4)[1], 120),
                        scr.result.toPlainText())
        self.assertIn("설정치", scr.result.toPlainText())
        self.assertIn(knowledge.AUTO_BADGE, scr.result.toPlainText())
        row = next(e for e in scr.rows if e["record"].get("material_type") == "design_document")
        self.assertEqual((row["extracted"], row["graphed"]), (True, None))
        kscr.kg_combo.setCurrentIndex(kscr.kg_combo.findText("kg-X"))
        setpoints = [n for n in kscr.kg["nodes"] if n["node_type"] == "setpoint"]
        self.assertTrue(setpoints)
        self.assertTrue(all(n["source"]["page"] for n in setpoints))
        shown = {n["id"] for n in kscr.data["nodes"]}
        self.assertTrue({n["id"] for n in setpoints} <= shown)
        kscr.render_node(setpoints[0]["id"])
        html = kscr.detail.toPlainText()
        self.assertIn(knowledge.AUTO_BADGE, html)
        self.assertIn("hazop.kg.docextract", html)
        auto_link = next(l for l in kscr.data["links"] if l["st"] == "candidate" and l["kind"] == "has_setpoint")
        kscr.render_link(auto_link["id"])
        self.assertIn(knowledge.AUTO_BADGE, kscr.detail.toPlainText())
        self.assertNotIn("link_candidates.csv", kscr.detail.toPlainText())

    def test_document_only_project_and_missing_kg_rebuilt_on_enter(self):
        """도면 없이 설계 문서만 있는 프로젝트: ③은 개발 명령 없이 항목 수와 도면 등록 안내. 지식그래프가 지워져 있으면 ③ 진입 때 다시 만듦."""
        from hazop.app import data
        from hazop.register import registry
        work = os.environ["HAZOP_WORK_ROOT"]
        doc_pdf = glob.glob(os.path.join(REPO_ROOT, "tests", "fixtures", "docextract", "*.pdf"))[0]
        r = registry.register(doc_pdf, "Y", "design_document", os.environ["HAZOP_STORE_ROOT"], None, "tester")
        data.extract_document(r["registration_file"])
        shutil.rmtree(os.path.join(work, "출력", "지식그래프", "kg-Y"))
        win = self.make_window()
        win.go(4)
        kscr = win.screens[4]
        self.assertGreaterEqual(kscr.kg_combo.findText("kg-Y"), 0)
        kscr.kg_combo.setCurrentIndex(kscr.kg_combo.findText("kg-Y"))
        self.assertEqual(kscr.stack.currentIndex(), 0)
        text = kscr.empty.text()
        self.assertIn("P&ID 도면을 등록", text)
        self.assertNotIn("build_kg", text)
        self.assertNotIn("참조한 도면 그래프가 없습니다", text)


def sample_file(drawing, ext):
    return [p for p in glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*." + ext))
            if drawing in p][0]


class BridgeTest(unittest.TestCase):
    """브리지 객체 단위 검사(웹뷰 로딩과 무관)."""

    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    def test_messages(self):
        from hazop.app.webview import Bridge
        b = Bridge()
        sent, nodes, results = [], [], []
        b.toWeb.connect(sent.append)
        b.nodeSelected.connect(nodes.append)
        b.highlightResult.connect(results.append)
        b.send("highlight", cause=["local-node-001"])
        self.assertEqual(sent, [])                                    # ready 전에는 보류
        b.fromWeb(json.dumps({"type": "ready"}))
        self.assertEqual(json.loads(sent[0])["type"], "highlight")
        b.fromWeb(json.dumps({"type": "nodeSelected", "local_id": "local-node-001", "entity_id": "entity-node-001"}))
        self.assertEqual(nodes[-1]["entity_id"], "entity-node-001")
        b.fromWeb(json.dumps({"type": "highlightResult", "missing": ["x", 3]}))
        self.assertEqual(results[-1], ["x"])
        b.fromWeb("not json")                                         # 형식 오류는 버림
        b.fromWeb("[1, 2]")
        self.assertEqual(len(nodes), 1)

    def test_network_blocking_configuration(self):
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from hazop.app.webview import HazopWebView, url_allowed
        for u in ("http://example.com/a.js", "https://example.com", "ws://x", "ftp://x/y"):
            self.assertFalse(url_allowed(u), u)
        for u in ("file:///C:/x.html", "qrc:///qtwebchannel/qwebchannel.js", "data:text/plain,1", "about:blank"):
            self.assertTrue(url_allowed(u), u)
        v = HazopWebView()
        self.addCleanup(v.deleteLater)
        self.addCleanup(v.dispose)
        s = v.page().settings()
        self.assertFalse(s.testAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls))
        self.assertFalse(s.testAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls))
        self.assertIs(v.profile, v.page().profile())
        self.assertTrue(v.profile.isOffTheRecord())
        names = [sc.name() for sc in v.page().scripts().toList()]
        self.assertEqual(names, ["hazop-qwebchannel", "hazop-bridge"])
        self.assertFalse(v.page().acceptNavigationRequest(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl(
            "https://example.com"), 0, True))


class WebViewIntegrationTest(AppTestBase):
    """offscreen에서 실제 뷰어 HTML을 띄워 브리지·노드 클릭·강조·외부 요청 차단을 확인한다."""

    def test_viewer_bridge_highlight(self):
        out_dir, graph = build_temp_drawing(os.environ["HAZOP_WORK_ROOT"])
        # 같은 도면에서 만든 그래프라 entity ID는 같지만 추출 경로가 달라 graph_version이 다르다.
        # 강조 경로를 검사하려고 복사한 실행의 분석 당시 그래프(inputs/graph.json)를 이 그래프로 맞춘다(검사 전용).
        run_dir = os.path.join(self.tmp, "viewer-run", os.path.basename(self.run_dir))
        shutil.copytree(self.run_dir, run_dir)
        old = load(os.path.join(run_dir, "inputs", "graph.json"))
        self.assertEqual(sorted(n["entity_id"] for n in old["nodes"]), sorted(n["entity_id"] for n in graph["nodes"]))
        with open(os.path.join(run_dir, "inputs", "graph.json"), "w", encoding="utf-8") as fh:
            json.dump(graph, fh, ensure_ascii=False)
        win = self.make_window()
        win.show()
        win.open_run(run_dir)
        ctx = win.screens[2].ctx
        self.assertTrue(ctx.html(), ctx.viewer_error)
        self.assertFalse(ctx.version_mismatch)
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "웹뷰 브리지 ready 신호 없음(offscreen)")
        results = []
        win.webview.bridge.highlightResult.connect(results.append)
        scr = win.screens[2]
        scr.select_candidate("deviation-p86-d09", "scenario-p86-d09-03")
        self.assertTrue(wait_for(lambda: results), "highlightResult 없음")
        self.assertEqual(results[-1], [])                             # 요청한 local_id를 모두 그림
        done = []
        win.webview.page().runJavaScript(
            "JSON.stringify(['.hz-cause', '.hz-path', '.hz-sg', '.hz-ring'].map(function (q) {"
            " return document.querySelectorAll(q).length; }))", 0, done.append)
        self.assertTrue(wait_for(lambda: done))
        cause, path, sg, ring = json.loads(done[0])
        self.assertGreater(cause, 0)
        self.assertGreater(path, 0)
        self.assertGreater(sg, 0)
        self.assertGreater(ring, 0)                                   # 보호수단 테두리
        # 강조 범례는 줌·맞춤 버튼 등 떠 있는 카드와 겹치지 않고, 구조 검증 칩은 한국어 값(design-system W10, D16)
        from scripts import check_design as cd
        for width in (1366, 900):
            win.resize(width, 689)
            wait_for(lambda: False, 0.5)                              # 크기 변경·맞춤이 웹 쪽에 반영되게 이벤트만 돌림
            got = []
            self.assertTrue(wait_for(lambda: (win.webview.page().runJavaScript(cd.LEGEND_JS, 0, got.append),
                                              got and got[-1])[1], 15))
            self.assertEqual(cd.legend_problems([{"width": width, "screen": "④", "measure": json.loads(got[-1])}]), [])
        chip = []
        self.assertTrue(wait_for(lambda: (win.webview.page().runJavaScript(
            "document.getElementById('status').textContent", 0, chip.append), chip)[1]))
        self.assertRegex(chip[-1], r"^구조 검증 (통과|차단) · ")
        ev = ctx.evidence(scr.cur_scenario)
        self.assertEqual(ev["n"], len(ev["shown"]) + len(ev["estimated"]) + len(ev["unshown"]))
        self.assertGreater(len(ev["shown"]), 0)
        nodes = []
        win.webview.bridge.nodeSelected.connect(nodes.append)
        win.webview.page().runJavaScript(
            "var e=document.querySelector('#overlay [data-local-id=\"local-node-001\"]');"
            "e.dispatchEvent(new MouseEvent('click',{bubbles:true}));")
        self.assertTrue(wait_for(lambda: nodes), "nodeSelected 없음")
        self.assertEqual(nodes[-1]["local_id"], "local-node-001")
        # 뷰어 페이지 안의 외부 이미지 요청은 실패해야 함(가로채기 기록 검사는 test_interceptor_blocks_remote_request)
        loaded = []
        win.webview.page().runJavaScript(
            "window.__hz_img='pending'; var i=new Image(); i.onload=function(){window.__hz_img='loaded'};"
            "i.onerror=function(){window.__hz_img='error'}; i.src='http://example.invalid/x.png';")
        self.assertTrue(wait_for(lambda: (win.webview.page().runJavaScript("window.__hz_img", 0, loaded.append),
                                          loaded and loaded[-1] != "pending")[1], 15))
        self.assertEqual(loaded[-1], "error")
        # 원격 주소로 이동도 막힘
        win.webview.page().runJavaScript("location.href='http://example.invalid/';")
        self.assertTrue(wait_for(lambda: any("example.invalid" in u for u in win.webview.page().blocked_navigation), 10))
        self.assertTrue(win.webview.current_file and win.webview.url().isLocalFile())
        # 주 프레임은 data:·blob:로도 이동할 수 없음
        from PySide6.QtCore import QUrl
        for u in ("data:text/html,<b>x</b>", "blob:file:///x", "file:///C:/other.html"):
            self.assertFalse(win.webview.page().acceptNavigationRequest(QUrl(u), 0, True), u)
        # 같은 경로라도 파일이 다시 만들어지면 다시 읽음
        path = win.webview.current_file
        self.assertFalse(win.webview.load_file(path))
        time.sleep(0.02)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n<!-- rebuilt -->\n")
        self.assertTrue(win.webview.load_file(path))
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready))

    def test_interceptor_blocks_remote_request(self):
        """요청 가로채기 판정: 원격 접근 설정을 켠 새 페이지(앱과 같은 프로필)에서 외부 이미지를 요청하면
        interceptor.blocked에 기록되어야 한다. 프로필에 가로채기를 붙이지 않으면 이 검사가 실패한다."""
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from hazop.app.webview import HazopWebView
        page = os.path.join(self.tmp, "probe.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write('<!DOCTYPE html><html><body><img src="http://example.invalid/hz-probe-%d.png"></body></html>'
                     % os.getpid())
        v = HazopWebView()
        self.addCleanup(v.deleteLater)
        self.addCleanup(v.dispose)
        v.page().settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        v.resize(400, 300)
        v.show()
        v.load_file(page)
        self.assertTrue(wait_for(lambda: any("hz-probe-%d.png" % os.getpid() in u for u in v.interceptor.blocked), 30),
                        "외부 요청이 가로채기에서 차단 기록되지 않음: %s" % v.interceptor.blocked[-5:])

    def test_stale_highlight_result_ignored(self):
        win = self.make_window()
        win.open_run(self.run_dir)
        scr = win.screens[2]
        scr.select_candidate("deviation-p86-d09", "scenario-p86-d09-03")
        scr.ctx.missing_local = set()
        win.webview.bridge.fromWeb(json.dumps({"type": "highlightResult", "request_id": "scenario-p86-d09-01",
                                               "missing": ["local-node-001"]}))
        self.assertEqual(scr.ctx.missing_local, set())               # 이전 요청 응답 무시
        win.webview.bridge.fromWeb(json.dumps({"type": "highlightResult", "request_id": "scenario-p86-d09-03",
                                               "missing": ["local-node-001"]}))
        self.assertEqual(scr.ctx.missing_local, {"local-node-001"})


class AiRunsTabTest(unittest.TestCase):
    """AI 실행 기록 탭: 검증 오류(dict 목록)를 문자열로 보여 주고(TypeError 없음), 원문 오류·병합 오류를 표시한다.
    상태는 한국어 라벨, 영문 코드는 툴팁(title)에만."""

    def test_validation_errors_and_raw_errors_rendered(self):
        from hazop.analysis import ai
        from hazop.app import data, render
        from tests.test_analysis import BAD_DIR, analyze
        doc = analyze(client=ai.FixedResponseClient(BAD_DIR))
        c = next(x for x in doc["candidates"] if x["candidate_id"] == "deviation-p86-d09")
        html_text = render.ai_runs_html(doc, c)  # 수정 전: "; ".join(dict 목록)에서 TypeError
        self.assertIn("reference_error $.", html_text)
        self.assertIn("검증 실패", html_text)
        self.assertIn("title='validation_failed'", html_text)
        self.assertIs(data.AI_STATUS_LABELS, ai.STATUS_LABELS_KO)
        self.assertNotIn("(input_mismatch)", data.AI_STATUS_LABELS["input_mismatch"])
        rec = {"ai_run_id": "airun-x-01", "attempt": 1, "status": "merge_error", "client": {},
               "result": {"status": "api_error", "error": "Error code: 500 raw"}, "merge_error": "RuntimeError: 병합 실패",
               "validation": None, "warnings": []}
        d = {"ai_runs": [dict(rec, candidate_id="c1")]}
        out = render.ai_runs_html(d, {"candidate_id": "c1", "analysis": {"ai_status": "merge_error"}})
        self.assertIn("Error code: 500 raw; RuntimeError: 병합 실패", out)
        self.assertIn("반영 오류", out)


if __name__ == "__main__":
    unittest.main()
