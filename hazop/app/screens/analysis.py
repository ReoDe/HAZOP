"""④ HAZOP 분석 결과 (기획서/인터페이스.md §3.3). 분석·내보내기·판단 변경·그래프 재연결은 기존 API만 호출한다."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from hazop import paths
from hazop.analysis import api, bundle_export, candidate_edit, run as run_mod
from hazop.app import data, render, tokens
from hazop.app.widgets import VALIDATION_LABELS, Banner, Chip, empty_label, esc, plain_label, risk_chip

STEP_LABELS = (("input_check", "입력 확인"), ("candidates", "후보"), ("exploration", "탐색"), ("patterns", "패턴"),
               ("ai", "AI"), ("risk", "위험도"))
FILTERS = (("all", "전체"), ("selected", "선택"), ("excluded", "제외"), ("deferred", "보류"))
COLUMNS = ("ID", "편차", "판단", "사유", "AI 상태", "시나리오", "최고 위험도 제안", "설계보완 후보", "열린 보류")
STEP_STATUS = {"completed": "완료", "partial": "일부", "failed": "실패", "skipped": "건너뜀", "not_run": "안 함"}


def ai_status_text(row):
    if row["selection_status"] != "selected":
        return "해당 없음(%s)" % data.SELECTION_LABELS.get(row["selection_status"])
    return data.AI_STATUS_LABELS.get(row["ai_status"], row["ai_status"] or "미요청")


def risk_text(row):
    """최고 위험도 제안 열의 상태 문구(값이 없을 때 '—' 대신)."""
    if row["selection_status"] != "selected":
        return "해당 없음(%s)" % data.SELECTION_LABELS.get(row["selection_status"])
    if row["max_risk"]:
        return "제안 %d" % row["max_risk"]
    return "시나리오 없음" if not row["scenarios"] else "제안 보류"


def fill_candidate_table(table, rows, extra=None):
    """편차 목록 표 채우기. extra: {candidate_id: 검토 상태}(⑤, ID 바로 다음 열 — 1366 폭에서도 보이게)."""
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        vals = [row["item_id"]]
        if extra is not None:
            vals.append(extra.get(row["candidate_id"], "판정 제외"))
        vals += [row["deviation"], data.SELECTION_LABELS.get(row["selection_status"]), row["reason"],
                 ai_status_text(row), row["scenarios"], risk_text(row), row["dics"], row["holds"]]
        risk_col = 6 + (extra is not None)
        for c, v in enumerate(vals):
            it = QTableWidgetItem("" if v is None else str(v))
            it.setData(Qt.UserRole, row["candidate_id"])
            if row["selection_status"] == "excluded":
                it.setForeground(QColor(tokens.c("muted")))
            table.setItem(r, c, it)
            if c == risk_col:
                table.removeCellWidget(r, c)
                if row["max_risk"]:  # AI 제안: 속 빈 칩(시안 README §2)
                    lab = QLabel(risk_chip(row["max_risk"], proposal=True))
                    lab.setTextFormat(Qt.RichText)
                    lab.setAlignment(Qt.AlignCenter)
                    it.setText("")
                    table.setCellWidget(r, c, lab)
    table.resizeColumnsToContents()
    dev_col = 1 + (extra is not None)
    table.setColumnWidth(dev_col, min(table.columnWidth(dev_col), 220))
    table.setColumnWidth(dev_col + 2, min(table.columnWidth(dev_col + 2), 200))


def make_candidate_table(extra_col=None):
    t = QTableWidget(0, len(COLUMNS) + (1 if extra_col else 0))
    t.setHorizontalHeaderLabels(list(COLUMNS[:1]) + ([extra_col] if extra_col else []) + list(COLUMNS[1:]))
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(24)
    return t


def user_text(line):
    """CLI 옵션 안내(--confirm 등)를 화면 문구로 바꾼다."""
    if "--confirm" in line:
        return "확인: 아래에 변경자·사유를 입력하고 '확인'을 누르면 갱신함"
    if "--by" in line and "--reason" in line:
        return "변경자와 사유가 필요함 — 변경하지 않음"
    return line


class AnalysisDialog(QDialog):
    """새 분석 실행: AI 응답 출처(고정 응답 폴더만 활성, API 호출은 비활성 확장 지점) + 응답 폴더."""

    def __init__(self, parent, default_dir):
        super().__init__(parent)
        self.setWindowTitle("새 분석 실행")
        lay = QFormLayout(self)
        self.source = QComboBox()
        self.source.addItem("고정 응답 폴더", "fixed_response")
        self.source.addItem("API 호출 (후속 — 이번 구현에서 비활성)", "api")
        self.source.model().item(1).setEnabled(False)
        lay.addRow("AI 응답 출처", self.source)
        row = QHBoxLayout()
        self.folder = QLineEdit(default_dir or "")
        b = QPushButton("폴더 선택")
        b.clicked.connect(self._pick)
        row.addWidget(self.folder)
        row.addWidget(b)
        lay.addRow("응답 폴더", row)
        lay.addRow(QLabel("프로그램은 AI를 호출하지 않습니다. 응답 폴더의 <candidate_id>.json을 불러와 검증·계산합니다."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "고정 응답 폴더", self.folder.text() or paths.work_root())
        if d:
            self.folder.setText(d)


class DecisionDialog(QDialog):
    """후보 판단 변경: 사유 필수. 저장하면 구간 버전이 오르고 재분석이 필요하다."""

    def __init__(self, parent, cand, region_version):
        super().__init__(parent)
        self.setWindowTitle("후보 판단 변경")
        lay = QFormLayout(self)
        lay.addRow("후보", QLabel("%s %s" % (cand["candidate_id"], cand.get("deviation"))))
        lay.addRow("현재 판단", QLabel("%s — %s" % (data.SELECTION_LABELS.get(cand["selection_status"]), cand.get("reason"))))
        self.status = QComboBox()
        for k, v in data.SELECTION_LABELS.items():
            self.status.addItem(v, k)
        lay.addRow("새 판단", self.status)
        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText("사유(필수)")
        self.reason.setFixedHeight(70)
        lay.addRow("사유", self.reason)
        lay.addRow(QLabel("저장하면 구간 버전이 올라가고(v%d → v%d) 재분석이 필요합니다. 열린 분석 결과는 바뀌지 않습니다."
                          % (region_version, region_version + 1)))
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        self.bb.button(QDialogButtonBox.Ok).setEnabled(False)
        self.reason.textChanged.connect(
            lambda: self.bb.button(QDialogButtonBox.Ok).setEnabled(bool(self.reason.toPlainText().strip())))
        lay.addRow(self.bb)


class AnalysisScreen(QWidget):
    title = "고정 응답 분석(이전 ④)"
    review_requested = Signal(str, str)  # candidate_id, scenario_id

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.ctx = None
        self.rows = []
        self.cur_scenario = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("구간"))
        self.region_combo = QComboBox()
        self.region_combo.setMinimumWidth(220)
        self.region_combo.currentIndexChanged.connect(self._region_changed)
        bar.addWidget(self.region_combo)
        bar.addWidget(QLabel("실행"))
        self.run_combo = QComboBox()
        self.run_combo.setMinimumWidth(300)
        self.run_combo.activated.connect(lambda _: self._open_selected_run())
        bar.addWidget(self.run_combo)
        self.btn_export = QPushButton("근거 묶음 내보내기")
        self.btn_export.clicked.connect(self.ask_export)
        self.btn_analyze = QPushButton("새 분석 실행")
        self.btn_analyze.setObjectName("primary")
        self.btn_analyze.clicked.connect(self.ask_analyze)
        bar.addWidget(self.btn_export)
        bar.addWidget(self.btn_analyze)
        self.chip_valid = Chip()
        bar.addWidget(self.chip_valid)
        # 결과 검증 통과의 단서는 줄이지 않고 칩 옆 라벨에서 줄바꿈해 늘 보인다(W3)
        self.valid_note = plain_label("", "muted")
        bar.addWidget(self.valid_note, 1)
        lay.addLayout(bar)
        self.counts = plain_label("", "muted")
        lay.addWidget(self.counts)
        self.progress = plain_label("")
        lay.addWidget(self.progress)
        self.banner_blocked = Banner("err")
        self.banner_input = Banner("err")
        self.banner_graph = Banner("warn")
        rebind_row = QHBoxLayout()
        self.btn_rebind = QPushButton("그래프 재연결…")
        self.btn_rebind.clicked.connect(self.ask_rebind)
        self.btn_rebind.hide()
        rebind_row.addWidget(self.banner_graph, 1)
        rebind_row.addWidget(self.btn_rebind)
        self.banner_mismatch = Banner("warn")
        for w in (self.banner_blocked, self.banner_input):
            lay.addWidget(w)
        lay.addLayout(rebind_row)
        lay.addWidget(self.banner_mismatch)

        self.body = QStackedWidget()
        self.empty = empty_label("구간을 선택하거나 새 분석을 실행하세요.")
        self.body.addWidget(self.empty)
        split = QSplitter(Qt.Horizontal)
        self.body.addWidget(split)
        lay.addWidget(self.body, 1)

        left = QFrame()
        left.setObjectName("panel")
        ll = QVBoxLayout(left)
        frow = QHBoxLayout()
        lt = QLabel("편차 후보")
        lt.setObjectName("title")
        frow.addWidget(lt)
        frow.addStretch(1)
        self.filter = QComboBox()
        for k, v in FILTERS:
            self.filter.addItem(v, k)
        self.filter.currentIndexChanged.connect(self._fill_table)
        frow.addWidget(self.filter)
        ll.addLayout(frow)
        self.table = make_candidate_table()
        self.table.itemSelectionChanged.connect(self._candidate_changed)
        ll.addWidget(self.table, 1)
        self.btn_decision = QPushButton("판단 변경…")
        self.btn_decision.clicked.connect(self.ask_change_decision)
        ll.addWidget(self.btn_decision, alignment=Qt.AlignLeft)
        split.addWidget(left)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        self.canvas_host = QWidget()
        QVBoxLayout(self.canvas_host).setContentsMargins(0, 0, 0, 0)
        self.canvas_note = empty_label("")
        self.canvas_stack = QStackedWidget()
        self.canvas_stack.addWidget(self.canvas_note)
        self.canvas_stack.addWidget(self.canvas_host)
        cl.addWidget(self.canvas_stack, 1)
        self.evidence = plain_label("시나리오를 고르면 원인·경로·보호수단을 도면에 강조합니다", "chip")
        cl.addWidget(self.evidence)
        split.addWidget(center)

        right = QFrame()
        right.setObjectName("panel")
        rl = QVBoxLayout(right)
        self.cand_title = plain_label("", "title")
        rl.addWidget(self.cand_title)
        self.cand_reason = plain_label("", "muted")
        rl.addWidget(self.cand_reason)
        self.tabs = QTabWidget()
        sc = QWidget()
        scl = QVBoxLayout(sc)
        scl.setContentsMargins(0, 0, 0, 0)
        self.scenario_list = QListWidget()
        self.scenario_list.setMaximumHeight(130)
        self.scenario_list.currentRowChanged.connect(self._scenario_changed)
        self.scenario_view = QTextBrowser()
        scl.addWidget(self.scenario_list)
        scl.addWidget(self.scenario_view, 1)
        self.dic_view = QTextBrowser()
        self.hold_view = QTextBrowser()
        self.ai_view = QTextBrowser()
        self.tabs.addTab(sc, "시나리오")
        self.tabs.addTab(self.dic_view, "설계보완 후보")
        self.tabs.addTab(self.hold_view, "자료 요청")
        self.tabs.addTab(self.ai_view, "AI 실행 기록")
        rl.addWidget(self.tabs, 1)
        self.btn_review = QPushButton("검토하기 → ⑤")
        self.btn_review.setObjectName("primary")
        self.btn_review.clicked.connect(self._go_review)
        rl.addWidget(self.btn_review)
        split.addWidget(right)
        split.setSizes([460, 560, 430])
        self.busy = False
        self.refresh_regions()

    # ------------------------------------------------------------ 구간·실행
    def where(self):
        if not self.ctx:
            return None
        return {"region": self.ctx.doc["analysis_run"]["region"].get("name") or self.ctx.region_id,
                "drawing": self.ctx.drawing_name, "run": self.ctx.doc["analysis_run_id"]}

    def on_enter(self):
        self.app.webview.set_mode(hide_panel=True)
        if self.ctx and self.ctx.html():
            self.app.attach_webview(self.canvas_host)
            # 잠금은 로드 결과와 무관하게 열린 실행의 graph_version 비교로 매번 적용
            self.app.webview.set_drawing_enabled(not self.ctx.version_mismatch)
            self.app.webview.load_file(self.ctx.html())
            if self.cur_scenario:
                self._highlight(self.cur_scenario)

    def refresh_regions(self):
        self.region_combo.blockSignals(True)
        self.region_combo.clear()
        for p in data.list_regions():
            self.region_combo.addItem(os.path.splitext(os.path.basename(p))[0], p)
        self.region_combo.blockSignals(False)
        self._region_changed()

    def region_path(self):
        return self.region_combo.currentData()

    def selected_region_id(self):
        rp = self.region_path()
        if not rp:
            return None
        try:
            return data.read_json(rp).get("region_id")
        except (OSError, ValueError):
            return None

    def ctx_matches_region(self):
        """열린 실행(ctx)이 구간 선택기의 구간과 같은지."""
        return self.ctx is not None and self.ctx.region_id == self.selected_region_id()

    def update_buttons(self):
        """작업 중이면 구간·실행 선택과 모든 실행 버튼을 막는다. 판단 변경·검토하기는 열린 실행이 선택 구간과 같을 때만."""
        idle = not self.busy
        rp = bool(self.region_path())
        for w in (self.region_combo, self.run_combo, self.btn_rebind):
            w.setEnabled(idle)
        self.btn_analyze.setEnabled(idle and rp)
        self.btn_export.setEnabled(idle and rp)
        ok = idle and self.ctx_matches_region()
        self.btn_decision.setEnabled(ok)
        self.btn_review.setEnabled(ok)

    def set_busy(self, busy):
        self.busy = bool(busy)
        self.update_buttons()

    def close_run(self, note):
        """열린 실행 닫기: 구간 선택이 바뀌면 이전 구간의 실행을 화면에 남기지 않는다."""
        self.ctx = None
        self.cur_scenario = None
        self.rows = []
        self.table.setRowCount(0)
        self.empty.setText(note)
        self.body.setCurrentIndex(0)
        self.chip_valid.set_state("")
        self.valid_note.setText("")
        self.counts.setText("")
        self.progress.setText("")
        for b in (self.banner_blocked, self.banner_mismatch):
            b.set_messages(None)
        self.app.webview.clear_highlight()
        self.app.set_run(None)

    def _region_changed(self):
        self.run_combo.clear()
        rp = self.region_path()
        self.banner_graph.set_messages(None)
        self.btn_rebind.hide()
        try:
            self._fill_region(rp)
        finally:
            if self.ctx is not None and not self.ctx_matches_region():
                self.close_run("구간이 바뀌었습니다. 이 구간의 실행을 고르거나 새 분석을 실행하세요.")
            self.update_buttons()

    def _fill_region(self, rp):
        if not rp:
            return
        try:
            region = data.read_json(rp)
        except (OSError, ValueError) as exc:
            self.banner_graph.set_messages("구간 JSON을 읽을 수 없음: %s" % exc)
            return
        for d in data.list_runs(region["region_id"]):
            self.run_combo.addItem(os.path.basename(d), d)
        cur = data.current_graph(region)
        ref = region.get("graph_ref") or {}
        if cur is None:
            self.banner_graph.set_messages("구간의 그래프 파일이 없음: %s" % ref.get("graph_file"),
                                           ["①에서 추출·그래프를 만들거나 그래프를 재연결하세요"])
        elif cur.get("graph_version") != ref.get("graph_version"):
            self.banner_graph.set_messages("구간이 가리키는 그래프 버전(%s)과 현재 그래프 버전(%s)이 다름"
                                           % (ref.get("graph_version"), cur.get("graph_version")),
                                           ["'그래프 재연결'로 차이를 확인하고 변경자·사유를 입력해 갱신할 수 있음"])
            self.btn_rebind.show()

    def _open_selected_run(self):
        d = self.run_combo.currentData()
        if d:
            self.open_run(d)

    def open_run(self, run_dir):
        """실행 폴더 열기(읽기 전용). 실패하면 오류를 표시하고 이전 상태를 유지한다."""
        from hazop.app.runctx import RunContext
        try:
            ctx = RunContext(run_dir)
        except Exception as exc:  # analysis.json 없음·형식 오류
            self.banner_input.set_messages("실행을 열 수 없음", [str(exc)])
            return False
        self.banner_input.set_messages(None)
        i = self.region_combo.findText(ctx.region_id)
        if i >= 0 and i != self.region_combo.currentIndex():  # 다른 구간의 실행을 열면 선택기도 그 구간으로 맞춘다
            self.region_combo.blockSignals(True)
            self.region_combo.setCurrentIndex(i)
            self.region_combo.blockSignals(False)
            self.run_combo.clear()
            self._fill_region(self.region_path())
        self.ctx = ctx
        self.app.set_run(ctx)
        self.show_ctx()
        self.update_buttons()
        return True

    def show_ctx(self):
        ctx = self.ctx
        doc = ctx.doc
        v = doc["validation"]
        st = v.get("status")
        self.chip_valid.set_state("결과 검증 %s" % VALIDATION_LABELS.get(st, st), "passed" if st == "passed" else "blocked")
        self.valid_note.setText("형식·참조 검증 통과(보류 항목이 없다는 뜻이 아님)" if st == "passed" else "")
        self.banner_blocked.set_messages(
            "결과 검증 차단 — 열람만 가능. ⑤ 확정 저장과 Excel 출력이 막힘" if st != "passed" else None, v.get("errors") or [])
        n = v.get("counts") or {}
        self.counts.setText("후보 %s(선택 %s · 제외 %s · 보류 %s) · 시나리오 %s · 위험도 제안 %s · 설계보완 후보 %s · 열린 보류 %s"
                            % (n.get("candidates"), n.get("selected"), n.get("excluded"), n.get("deferred"),
                               n.get("scenarios"), n.get("risk_proposed"), n.get("design_improvement_candidates"),
                               n.get("holds_open")))
        steps = doc["analysis_run"].get("steps") or {}
        self.progress.setText("분석 단계: " + " → ".join("%s(%s)" % (lbl, STEP_STATUS.get(steps.get(k), steps.get(k) or "기록 없음"))
                                                       for k, lbl in STEP_LABELS))
        msgs = []
        if ctx.version_mismatch:
            msgs.append("분석 당시 그래프 %s ≠ 현재 도면 그래프 %s — 도면 탭과 강조를 끄고 그래프 보기만 제공"
                        % ((ctx.run_graph or {}).get("graph_version"), ctx.current_graph_version))
        self.banner_mismatch.set_messages("그래프 버전 불일치" if ctx.version_mismatch else
                                          (ctx.viewer_error and "도면 표시 안 됨"), msgs or
                                          ([ctx.viewer_error] if ctx.viewer_error else []))
        if ctx.html():
            self.canvas_stack.setCurrentIndex(1)
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_mode(hide_panel=True)
            # 버전 불일치: 다른 버전의 도면을 원래 근거처럼 보이지 않게 도면 탭을 끈다(그래프 탭만)
            self.app.webview.set_drawing_enabled(not ctx.version_mismatch)
            self.app.webview.load_file(ctx.html())
        else:
            self.canvas_stack.setCurrentIndex(0)
            self.canvas_note.setText(ctx.viewer_error or "")
        idx = self.run_combo.findData(ctx.run_dir)
        if idx < 0:
            self.run_combo.addItem(os.path.basename(ctx.run_dir), ctx.run_dir)
            idx = self.run_combo.count() - 1
        self.run_combo.setCurrentIndex(idx)
        self.rows = data.candidate_rows(doc)
        self.body.setCurrentIndex(1)
        self._fill_table()
        self.app.update_header()

    def _fill_table(self):
        f = self.filter.currentData()
        rows = [r for r in self.rows if f == "all" or r["selection_status"] == f]
        self.table.blockSignals(True)
        fill_candidate_table(self.table, rows)
        self.table.blockSignals(False)
        if rows:
            self.table.selectRow(0)
        self._candidate_changed()

    def current_candidate_id(self):
        it = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def select_candidate(self, cid, scenario_id=None):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == cid:
                self.table.selectRow(r)
                break
        if scenario_id:
            for i in range(self.scenario_list.count()):
                if self.scenario_list.item(i).data(Qt.UserRole) == scenario_id:
                    self.scenario_list.setCurrentRow(i)

    # ------------------------------------------------------------ 상세
    def _candidate_changed(self):
        cid = self.current_candidate_id()
        self.scenario_list.blockSignals(True)
        self.scenario_list.clear()
        self.scenario_list.blockSignals(False)
        self.cur_scenario = None
        if not cid or not self.ctx:
            self.cand_title.setText("")
            self.cand_reason.setText("")
            for v in (self.scenario_view, self.dic_view, self.hold_view, self.ai_view):
                v.setHtml("")
            return
        ctx = self.ctx
        c = ctx.candidate(cid)
        self.cand_title.setText("%s · %s(%s) — %s" % (c.get("item_id"), c.get("parameter_ko"), c.get("guide_word_ko"),
                                                      c.get("deviation")))
        self.cand_reason.setText("판단: %s — %s" % (data.SELECTION_LABELS.get(c["selection_status"]), c.get("reason")))
        scen = ctx.scenarios_of(cid)
        for s in scen:
            rp = s.get("risk_proposal") or {}
            label = "%s  %s%s" % (s["scenario_id"].replace("scenario-", ""), (s.get("cause") or "")[:40],
                                  ("  [제안 %d]" % rp["risk"]) if isinstance(rp.get("risk"), int) else "")
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, s["scenario_id"])
            self.scenario_list.addItem(it)
        if not scen:
            self.scenario_view.setHtml("<p style='color:%s'>시나리오 없음 — %s</p>" % (tokens.c("muted"), esc(
                "제외·보류 후보는 시나리오를 만들지 않음" if c["selection_status"] != "selected" else
                "AI 상태: %s" % data.AI_STATUS_LABELS.get((c.get("analysis") or {}).get("ai_status"), "미확인"))))
            self.app.webview.clear_highlight()
            self.evidence.setText("시나리오 없음")
        holds_by_id = {h["hold_id"]: h for h in ctx.doc["holds"]}
        dics = ctx.dics_of(cid)
        self.dic_view.setHtml("".join(render.dic_html(d, holds_by_id) for d in dics) or
                              "<p style='color:%s'>설계보완 후보 없음</p>" % tokens.c("muted"))
        self.hold_view.setHtml(render.holds_html(ctx.holds_of(cid)))
        self.ai_view.setHtml(render.ai_runs_html(ctx.doc, c))
        if scen:
            self.scenario_list.setCurrentRow(0)

    def _scenario_changed(self, row):
        if row < 0 or not self.ctx:
            return
        sid = self.scenario_list.item(row).data(Qt.UserRole)
        s = self.ctx.scenario(sid)
        self.cur_scenario = s
        self._highlight(s)

    def _highlight(self, s):
        ctx = self.ctx
        ctx.missing_local = set()
        spec = ctx.highlight_spec(s)
        if spec:
            self.app.webview.highlight(spec)
            self.app.debug_message("Python→웹 highlight(원인 %d · 경로 %d · 보호수단 %d)"
                                    % (len(spec["cause"]), len(spec["path"]) + len(spec["estimated"]),
                                       len(spec["safeguards"])))
        else:
            self.app.webview.clear_highlight()
        self._render_scenario(s)

    def _render_scenario(self, s):
        ev = self.ctx.evidence(s)
        st = self.ctx.summary["by_candidate"].get(s["candidate_id"])
        self.scenario_view.setHtml(render.scenario_html(self.ctx.doc, s, self.ctx.tags, st, ev))
        txt = data.evidence_text(ev)
        if self.ctx.version_mismatch:
            txt += " — 그래프 버전 불일치로 모두 미표시"
        self.evidence.setText(txt)

    def on_highlight_result(self, missing, request_id=None):
        """웹이 그리지 못한 ID. 이전 시나리오 요청의 늦은 응답(request_id 불일치)은 무시한다."""
        if self.ctx and self.cur_scenario:
            if request_id is not None and request_id != self.cur_scenario["scenario_id"]:
                return
            self.ctx.missing_local = set(missing)
            self._render_scenario(self.cur_scenario)

    def on_node(self, sel):
        if not self.ctx:
            return
        eid = sel.get("entity_id") or next((e for e, l in self.ctx.local_map.items() if l == sel.get("local_id")), None)
        self.app.status_message("선택한 객체: %s" % (self.ctx.tags.get(eid) or eid or "태그 미확인"))
        self.app.debug_message("nodeSelected: %s" % eid)

    def _go_review(self):
        cid = self.current_candidate_id()
        if cid:
            self.review_requested.emit(cid, (self.cur_scenario or {}).get("scenario_id") or "")

    # ------------------------------------------------------------ 동작(대화상자와 검사가 같은 함수를 씀)
    def ask_analyze(self):
        dlg = AnalysisDialog(self, paths.folder("고정응답", self.region_combo.currentText()))
        if dlg.exec() == QDialog.Accepted:
            self.start_analysis(dlg.folder.text().strip())

    def start_analysis(self, response_dir):
        rp = self.region_path()
        if not rp or not response_dir:
            return
        self.progress.setText("분석 중: " + " → ".join(lbl for _, lbl in STEP_LABELS))
        self.set_busy(True)
        self.app.tasks.run("분석 실행", lambda: api.run_analysis(rp, response_dir=response_dir),
                           lambda res: self._analysis_done(res, rp), self._analysis_failed)

    def _analysis_done(self, res, started_region=None):
        self.set_busy(False)
        if started_region is not None and started_region != self.region_path():
            # 시작 당시 구간과 지금 선택이 다르면 화면을 바꾸지 않고 알리기만 한다
            self.app.status_message("다른 구간(%s)의 분석이 끝남 — 그 구간을 고르면 실행 목록에 있음"
                                    % os.path.splitext(os.path.basename(started_region))[0])
            return
        if res["status"] == "input_blocked":
            self.progress.setText("")
            self.banner_input.set_messages("입력 차단 — 분석하지 않음", res["blockers"])
            return
        self._region_changed()
        self.open_run(res["run_dir"])

    def _analysis_failed(self, err):
        self.set_busy(False)
        self.progress.setText("")
        self.banner_input.set_messages("분석 실패 — 결과를 만들지 않음", [err])

    def ask_export(self):
        if QMessageBox.question(self, "근거 묶음 내보내기", bundle_export.EXPORT_NOTE + "\n\n내보낼까요?") != QMessageBox.Yes:
            return
        self.export_bundles(lambda out: QMessageBox.information(self, "근거 묶음 내보내기", "내보냄: %s\n응답 폴더: %s"
                                                                 % (out["export_dir"], out["response_dir"])))

    def export_bundles(self, on_done=None):
        rp = self.region_path()
        if not rp:
            return

        def done(out):
            self.set_busy(False)
            self.app.status_message("근거 묶음 내보냄: %s (후보 %d)" % (out["export_dir"], len(out["manifest"]["candidates"])))
            if on_done:
                on_done(out)

        def failed(e):
            self.set_busy(False)
            self.banner_input.set_messages("내보내기 실패", [e])
        self.set_busy(True)
        self.app.tasks.run("근거 묶음 내보내기", lambda: bundle_export.export_bundles(rp), done, failed)

    def ask_change_decision(self):
        cid = self.current_candidate_id()
        if not cid or not self.ctx or not self.ctx.region_path:
            QMessageBox.warning(self, "판단 변경", "구간 JSON(데이터/구간)을 찾을 수 없어 판단을 바꿀 수 없음")
            return
        region = data.read_json(self.ctx.region_path)
        dlg = DecisionDialog(self, self.ctx.candidate(cid), region["region_version"])
        if dlg.exec() == QDialog.Accepted:
            try:
                out = self.change_decision(cid, dlg.status.currentData(), dlg.reason.toPlainText())
            except (candidate_edit.DecisionError, run_mod.InputError, OSError) as exc:
                QMessageBox.warning(self, "판단 변경 실패", str(exc))
                return
            QMessageBox.information(self, "판단 변경", "구간 버전 v%d로 저장함. %s. 열린 분석 결과는 바뀌지 않음."
                                    % (out["region_version"], out["notice"]))

    def change_decision(self, cid, status, reason):
        """구간 JSON candidate_decisions에 덧붙이고 region_version +1(candidate_edit). 사유·변경자 필수.
        열린 실행이 구간 선택과 다르거나 작업 중이면 바꾸지 않는다."""
        if self.busy or not self.ctx_matches_region():
            raise candidate_edit.DecisionError("열린 실행과 선택한 구간이 다르거나 작업 중 — 실행을 다시 연 뒤 바꾸세요")
        by = self.app.reviewer_name() or ""
        out = candidate_edit.change_candidate_decision(self.ctx.region_path, cid, status, by, reason)
        self.app.status_message("판단 변경 저장(구간 v%d) — %s" % (out["region_version"], out["notice"]))
        return out

    def ask_rebind(self):
        rp = self.region_path()
        if not rp:
            return
        lines, _ = run_mod.rebind_graph(rp, None, paths.work_root(), None, None, False)
        lines = [user_text(x) for x in lines]
        dlg = QDialog(self)
        dlg.setWindowTitle("그래프 재연결")
        lay = QFormLayout(dlg)
        view = QPlainTextEdit("\n".join(lines))
        view.setReadOnly(True)
        lay.addRow(view)
        by = QLineEdit(self.app.reviewer_name() or "")
        reason = QLineEdit()
        lay.addRow("변경자", by)
        lay.addRow("사유", reason)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            out, changed = run_mod.rebind_graph(rp, None, paths.work_root(), by.text().strip(), reason.text().strip(), True)
            QMessageBox.information(self, "그래프 재연결", "\n".join(user_text(x) for x in out[-3:]))
            if changed:
                self._region_changed()
