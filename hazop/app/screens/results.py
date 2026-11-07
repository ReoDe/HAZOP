"""⑤ 분석 결과 화면 (stage3-spec §B results.py, 4단계 설계, 디자인/시안/완성본/B-고밀도작업대/5-요약행렬).

확정된 검토구간 집합 × 편차(results.load_deviations) 행렬과 칸별 워크시트. Claude API가 칸을 'AI 초안' 항목으로 채우고
(ai_cells, 작업 스레드는 ai_runner) 사람이 항목을 수정·승인·기각한다. 결과는 바뀔 때마다 results.save로 저장하고
화면을 다시 열면 results.load로 읽는다(확정 구간이 바뀐 저장본은 쓰지 않고 빈 결과로 시작).
AI가 쓴 항목은 승인 전까지 언제나 'AI 초안'으로 표시한다(results.is_ai_draft).
"""

import os

from PySide6.QtCore import QCoreApplication, QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                               QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import data, tokens
from hazop.app.ai_runner import AiRunner
from hazop.app.screens.results_paint import CELL_ROLE, DRAFT_ROLE, CellDelegate, GroupHeader, SheetDelegate
from hazop.app.screens.study import seg_icon
from hazop.app.widgets import Chip, empty_label, plain_label
from hazop.study import ai_cells, nodes
from hazop.study import results as res
from hazop.study.claude_http import ClaudeHttpClient
from hazop.viewer import build as viewer_build

AI_NOTE = "AI 결과는 모두 초안 · 사람이 수정·승인·기각"
STATUS_LABELS = {"proposed": "제안", "revised": "수정", "approved": "승인", "rejected": "기각"}
BAND_LABELS = {"ok": "수용", "cond": "조건부 수용", "deny": "불허"}  # tokens.risk_band 구분
SHEET_COLUMNS = ("원인", "결과", "보호수단", "권고", "위험도", "AI 근거", "상태")
COL_RISK, COL_BASIS, COL_STATUS = 4, 5, 6
CELL_W, ROW_H, ROW_HEAD_W = 54, 30, 210  # U-20: 1366에서 편차 열 약 11개가 보이게 칸 한 줄
RISK_KEYS = ("칸 숫자 = 최고 위험도 · 미N = 미검토 시나리오 · – 분석 전 · 없음 = AI 초안(해당 없음·시나리오 없음) · "
             "! 실패 = AI 실행 실패(위험도 아님)")
NAV_KEYS = "←↑↓→ 칸 이동 · Enter 열기 · J 다음 미검토 · 워크시트 A 승인 · R 기각 · E 수정 · Ctrl+Z 실행 취소"
EDIT_TEXT_FIELDS = (("cause", "원인"), ("consequence", "결과"), ("recommendation", "권고"))


def design_intent(node, graph_id):
    """구간 JSON(데이터/구간) 중 같은 그래프를 가리키고 이 구간의 구성요소를 모두 포함하는 것의 설계 의도.
    (글, 출처 설명) 또는 None. 상위 구간의 설계 의도이므로 화면에 출처와 지식 상태를 함께 적는다."""
    members = set(node["members"])
    for path in data.list_regions():
        try:
            region = data.read_json(path)
        except (OSError, ValueError):
            continue
        if (region.get("graph_ref") or {}).get("graph_id") != graph_id:
            continue
        scope = {m.get("entity_id") for m in region.get("members") or []}
        intent = region.get("design_intent") or {}
        if members and members <= scope and intent.get("text"):
            return intent["text"], "상위 구간 %s · 지식 상태 %s" % (
                region.get("name") or os.path.basename(path), intent.get("knowledge_status") or "-")
    return None


def risk_text(risk):
    band = tokens.risk_band(risk)
    return "%d %s" % (risk, BAND_LABELS[band]) if band else "미정"


def usage_text(total):
    inp = total["input_tokens"] + total["cache_read_input_tokens"] + total["cache_creation_input_tokens"]
    return "입력 {:,} · 출력 {:,} 토큰 · 추정 ${:.2f}".format(inp, total["output_tokens"], total["cost_usd"])


class EntryDialog(QDialog):
    """항목 수정: 원인·결과·보호수단(한 줄에 하나)·권고·강도·발생빈도. changed()는 바뀐 필드만 돌려준다."""

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setWindowTitle("항목 수정")
        self.setMinimumWidth(480)
        lay = QFormLayout(self)
        self.texts = {}
        for key, label in EDIT_TEXT_FIELDS:
            ed = QPlainTextEdit(entry.get(key) or "")
            ed.setFixedHeight(60)
            self.texts[key] = ed
            lay.addRow(label, ed)
        self.safeguards = QPlainTextEdit("\n".join(entry.get("safeguards") or []))
        self.safeguards.setFixedHeight(60)
        lay.insertRow(2, "보호수단\n(한 줄에 하나)", self.safeguards)
        self.sev = self._combo(res.SEVERITIES, entry.get("severity"))
        self.freq = self._combo(res.FREQUENCIES, entry.get("frequency"))
        lay.addRow("강도(1–4)", self.sev)
        lay.addRow("발생빈도(1–3)", self.freq)
        note = QLabel("고치면 상태가 '수정'이 됩니다. 승인한 항목도 다시 승인해야 합니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    @staticmethod
    def _combo(values, current):
        cb = QComboBox()
        cb.addItem("미정", None)
        for v in values:
            cb.addItem(str(v), v)
        cb.setCurrentIndex(values.index(current) + 1 if current in values else 0)
        return cb

    def fields(self):
        out = {k: ed.toPlainText().strip() for k, ed in self.texts.items()}
        out["safeguards"] = [s.strip() for s in self.safeguards.toPlainText().splitlines() if s.strip()]
        out["severity"] = self.sev.currentData()
        out["frequency"] = self.freq.currentData()
        return out

    def changed(self):
        return {k: v for k, v in self.fields().items() if self.entry.get(k) != v}


def empty_cell_label(run):
    """항목 없는 분석 칸의 문구. AI가 '해당 없음'이라 한 칸과, 해당한다면서 시나리오를 내지 않은 칸을 구분한다."""
    if run.get("applicable") is False:
        return "해당 없음(AI 판단)"
    if run.get("applicable") is True:
        return "시나리오 없음(AI)"
    return "항목 없음"


class ResultsScreen(QWidget):
    title = "⑤ 분석 결과"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.name = None
        self.graph = None
        self.node_set = None   # 확정된 검토구간 집합만
        self.results = None
        self.kg, self.kg_reason = None, None
        self.deviations = res.load_deviations()
        self.cell = None       # (node_id, deviation_id)
        self.runner = None
        self._old_saved = None  # 쓰지 않기로 한 저장본 경로(처음 저장할 때 옆에 보관본으로 옮김)
        self._unsaved = False   # 마지막 저장이 실패해 화면에만 있는 변경이 있음
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)  # U-20: 1366에서 편차 열 약 11개(가운데 폭 − 행 머리 210) ÷ 54
        lay.setSpacing(4)
        bar = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setToolTip("도면")
        self.combo.setMinimumWidth(140)
        self.combo.currentIndexChanged.connect(self._load)
        bar.addWidget(self.combo)
        self.kpi = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=10)
        bar.addWidget(self.kpi, 1)
        bar.addLayout(self._toolbar())
        lay.addLayout(bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_page())

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(4)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        top_w = QWidget()
        top = QVBoxLayout(top_w)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(2)
        head = QHBoxLayout()
        self.ai_chip = Chip(AI_NOTE, elide=Qt.ElideRight)
        head.addWidget(self.ai_chip)
        self.stale_chip = Chip(elide=Qt.ElideRight)
        self.stale_chip.hide()
        head.addWidget(self.stale_chip)
        self.kg_chip = Chip(elide=Qt.ElideRight)
        self.kg_chip.hide()
        head.addWidget(self.kg_chip)
        head.addStretch(1)
        top.addLayout(head)
        self.matrix = QTableWidget()
        self.matrix.setObjectName("matrix")
        self.matrix.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.matrix.setSelectionMode(QAbstractItemView.SingleSelection)
        self.matrix.setHorizontalHeader(GroupHeader(self.matrix))
        self.matrix.horizontalHeader().setDefaultSectionSize(CELL_W)
        self.matrix.horizontalHeader().setMinimumSectionSize(CELL_W)
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.matrix.verticalHeader().setDefaultSectionSize(ROW_H)
        self.matrix.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.matrix.verticalHeader().setFixedWidth(ROW_HEAD_W)  # 긴 구간 이름은 줄임표 + 툴팁
        self.matrix.verticalHeader().setTextElideMode(Qt.ElideRight)
        self.matrix.setIconSize(QSize(30, 16))
        self.matrix.setWordWrap(False)
        self.matrix.setItemDelegate(CellDelegate(self.matrix))
        self.matrix.cellClicked.connect(lambda r, c: self.open_cell(self._node_at(r), self.deviations[c]["deviation_id"]))
        top.addWidget(self.matrix, 1)
        legend = plain_label(RISK_KEYS, name="muted", elide=Qt.ElideRight, min_chars=12)
        top.addWidget(legend)
        keys = plain_label(NAV_KEYS, name="muted", elide=Qt.ElideRight, min_chars=12)
        top.addWidget(keys)
        split.addWidget(top_w)
        split.addWidget(self._sheet())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([300, 420])
        bv.addWidget(split, 1)
        self.stack.addWidget(body)
        lay.addWidget(self.stack, 1)
        self._shortcuts()

    def _empty_page(self):
        """빈 상태(U-09): 제목 한 줄 + 이유 + 주 버튼 + 다음 단계."""
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        title = QLabel("아직 볼 분석 결과가 없습니다")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        el.addWidget(title)
        self.empty = empty_label("확정된 검토구간이 없습니다. ④ 검토구간에서 구간을 확정하면 여기서 구간 × 편차 결과를 봅니다.")
        el.addWidget(self.empty)
        self.to_study_btn = QPushButton("④ 검토구간으로")
        self.to_study_btn.setObjectName("primary")
        self.to_study_btn.clicked.connect(lambda: self.app.go(5))
        el.addWidget(self.to_study_btn, 0, Qt.AlignHCenter)
        steps = empty_label("다음 단계: ④에서 구간 확정 → 여기서 'AI 일괄 분석' → 칸마다 AI 초안을 승인·기각·수정")
        el.addWidget(steps)
        el.addStretch(1)
        return empty

    def _toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(6)
        self.progress = QProgressBar()
        self.progress.setObjectName("thin")
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(120, 4)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("muted")
        row.addWidget(self.progress, 0, Qt.AlignVCenter)
        row.addWidget(self.progress_label)
        self.run_all_btn = QPushButton("AI 일괄 분석")
        self.run_all_btn.setObjectName("primary")
        self.run_all_btn.setToolTip("확정된 모든 구간 × 편차를 Claude API로 분석(사람이 손댄 항목은 유지)")
        self.run_all_btn.clicked.connect(lambda: self.run_ai("all"))
        self.run_node_btn = QPushButton("선택 구간 분석")
        self.run_node_btn.setToolTip("행렬에서 고른 행의 구간만 분석")
        self.run_node_btn.clicked.connect(lambda: self.run_ai("node"))
        self.retry_btn = QPushButton("실패 칸 다시 실행")
        self.retry_btn.setToolTip("마지막 AI 실행이 실패한 칸만 칸마다 다시 호출")
        self.retry_btn.clicked.connect(lambda: self.run_ai("failed"))
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setToolTip("남은 호출을 멈춤(진행 중인 호출 1건은 끝까지 받아 반영)")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_ai)
        self.usage = QLabel()  # 토큰·비용은 도구 설명으로(도구줄 폭 절약)
        self.usage.hide()
        for w in (self.retry_btn, self.run_node_btn, self.cancel_btn, self.run_all_btn):
            row.addWidget(w)
        return row

    def _sheet(self):
        frame = QFrame()
        frame.setObjectName("panel")
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)
        self.sheet_stack = QStackedWidget()
        self.sheet_stack.addWidget(empty_label("행렬의 칸을 누르면 구간 × 편차 워크시트가 열립니다."))
        sheet = QWidget()
        sv = QVBoxLayout(sheet)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(4)
        hrow = QHBoxLayout()
        self.sheet_badge = QLabel()
        hrow.addWidget(self.sheet_badge)
        self.sheet_title = plain_label("", elide=Qt.ElideRight, min_chars=12)
        self.sheet_title.setObjectName("title")
        hrow.addWidget(self.sheet_title)
        self.draft_chip = Chip()
        hrow.addWidget(self.draft_chip)
        self.intent = plain_label("", elide=Qt.ElideRight, min_chars=10)
        hrow.addWidget(self.intent, 1)
        self.sheet_count = QLabel()
        self.sheet_count.setObjectName("muted")
        hrow.addWidget(self.sheet_count)
        sv.addLayout(hrow)
        self.intent_src = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=10)
        sv.addWidget(self.intent_src)
        self.run_note = plain_label("", wrap=True)
        self.run_note.hide()
        sv.addWidget(self.run_note)
        self.table = QTableWidget(0, len(SHEET_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(SHEET_COLUMNS))
        self.table.horizontalHeaderItem(COL_RISK).setToolTip("위험도 = 강도 × 발생빈도 〈표5〉(KOSHA P-86) · 구분 〈표9〉")
        self.table.horizontalHeaderItem(COL_BASIS).setToolTip("AI 근거: 지식그래프 경로 · 출처 문서 · ⚠ 근거 확인 경고")
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setWordWrap(True)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        for c in (COL_RISK, COL_STATUS):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setItemDelegate(SheetDelegate(COL_BASIS, self.table))
        self.table.itemSelectionChanged.connect(self._update_entry_buttons)
        self.table.verticalScrollBar().valueChanged.connect(lambda _v: self._place_row_actions())
        sv.addWidget(self.table, 1)
        # 행 단위 동작(U-21): 고른 행의 상태 칸 위에만 승인 A · 기각 R · 수정 E를 띄운다
        self.row_actions = QWidget(self.table.viewport())
        self.row_actions.setObjectName("row_actions")
        ra = QHBoxLayout(self.row_actions)
        ra.setContentsMargins(2, 2, 2, 2)
        ra.setSpacing(3)
        self.approve_btn = QPushButton("승인 A")
        self.approve_btn.clicked.connect(lambda: self.set_entry_status("approved"))
        self.reject_btn = QPushButton("기각 R")
        self.reject_btn.clicked.connect(lambda: self.set_entry_status("rejected"))
        self.edit_btn = QPushButton("수정 E")
        self.edit_btn.clicked.connect(lambda: self.edit_selected())
        for b in (self.approve_btn, self.reject_btn, self.edit_btn):
            b.setObjectName("row_btn")
            ra.addWidget(b)
        self.row_actions.hide()
        act = QHBoxLayout()
        act.addStretch(1)
        self.rerun_cell_btn = QPushButton("이 칸 다시 실행")
        self.rerun_cell_btn.setToolTip("이 칸만 다시 AI 분석(승인·수정·기각한 항목은 유지)")
        self.rerun_cell_btn.clicked.connect(lambda: self.run_ai("cell"))
        act.addWidget(self.rerun_cell_btn)
        sv.addLayout(act)
        self.sheet_stack.addWidget(sheet)
        v.addWidget(self.sheet_stack, 1)
        return frame

    # ------------------------------------------------------------ 틀 연결
    def where(self):
        if not self.node_set:
            return None
        return {"drawing": self.node_set.get("drawing_number") or self.name, "region": None, "run": None}

    def is_done(self):
        return False

    def commands(self):
        """명령 팔레트(U-01) 항목 [(이름, 단축키, 함수)]."""
        return [("AI 일괄 분석", "", lambda: self.run_ai("all")), ("선택 구간 분석", "", lambda: self.run_ai("node")),
                ("실패 칸 다시 실행", "", lambda: self.run_ai("failed")), ("이 칸 다시 실행", "", lambda: self.run_ai("cell")),
                ("다음 미검토 칸", "J", self.next_unreviewed), ("칸 열기", "Enter", self.open_current),
                ("항목 승인", "A", lambda: self.set_entry_status("approved")),
                ("항목 기각", "R", lambda: self.set_entry_status("rejected")),
                ("항목 수정…", "E", lambda: self.edit_selected()),
                ("이전 고정 응답 분석 열기", "", lambda: self.app.go(2))]

    def _shortcuts(self):
        """행렬·워크시트 단축키(U-02). 이 화면 안에서만 듣고, 글 입력칸에 초점이 있으면 입력이 먼저다."""
        keys = (("J", self.next_unreviewed), ("A", lambda: self.set_entry_status("approved")),
                ("R", lambda: self.set_entry_status("rejected")), ("E", lambda: self.edit_selected()))
        self.keys = {}
        for seq, fn in keys:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self.keys[seq] = sc
        for seq in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(seq), self.matrix)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self.open_current)
            self.keys[seq] = sc

    def open_current(self):
        r, c = self.matrix.currentRow(), self.matrix.currentColumn()
        if self.node_set is None or r < 0 or c < 0:
            return False
        return self.open_cell(self._node_at(r), self.deviations[c]["deviation_id"])

    def next_unreviewed(self):
        """J: 지금 칸 다음(행 순서)의 미검토 시나리오가 있는 칸을 연다. 끝에서는 처음으로 돌아간다."""
        if not self.results:
            return False
        summary = res.matrix_summary(self.results)
        order = [(n["node_id"], d["deviation_id"]) for n in self.node_set["nodes"] for d in self.deviations]
        start = order.index(self.cell) + 1 if self.cell in order else 0
        for key in order[start:] + order[:start]:
            if (summary.get(key[0], {}).get(key[1]) or {}).get("unreviewed"):
                return self.open_cell(*key)
        self.app.status_message("미검토 시나리오가 있는 칸이 없습니다.")
        return False

    def on_enter(self):
        if self.running():  # 실행 중에는 같은 결과를 계속 보여 준다(도면을 바꾸면 반영할 곳이 사라짐)
            return
        names = [e["name"] for e in data.list_extractions()]
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if cur in names:
            self.combo.setCurrentText(cur)
        self.combo.blockSignals(False)
        self._load()

    def show_node(self, drawing_name, node_id):
        """④에서 넘어온 구간: 그 도면을 고르고 행의 첫 칸 워크시트를 연다(확정 전이면 빈 화면 안내)."""
        if not self.running() and self.combo.findText(drawing_name) >= 0 and self.combo.currentText() != drawing_name:
            self.combo.setCurrentText(drawing_name)
        row = self._row_of(node_id)
        if row is not None:
            self.matrix.selectRow(row)
            self.open_cell(node_id, self.deviations[0]["deviation_id"])

    # ------------------------------------------------------------ 읽기
    def _load(self):
        if self.running():
            return
        if self._unsaved and self.results is not None and not self._save():
            # 저장하지 못한 검토 내용을 디스크 판으로 덮어쓰지 않는다
            self.combo.blockSignals(True)
            self.combo.setCurrentText(self.name or "")
            self.combo.blockSignals(False)
            self.app.status_message("저장하지 못한 분석 결과가 있어 다시 읽지 않음. 저장 위치를 확인하세요.")
            return
        name = self.combo.currentText()
        self.name, self.graph, self.node_set, self.results, self.cell = name or None, None, None, None, None
        self.kg, self.kg_reason, self._old_saved = None, None, None
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_label.setText("")
        if name:
            self.graph = viewer_build.load_graph(paths.output_root("그래프"), name)
        saved = None
        if self.graph:
            try:
                saved = nodes.load(self.graph)
            except (OSError, ValueError) as exc:
                self.empty.setText("검토구간 파일을 읽을 수 없음: %s" % exc)
        usable = (saved and saved.get("status") == "confirmed" and not nodes.is_stale(saved, self.graph)
                  and not nodes.coverage(saved, self.graph)["uncovered"])
        if saved and saved.get("status") == "confirmed" and not usable:
            self.empty.setText("확정된 검토구간이 현재 도면과 맞지 않습니다(도면이 바뀜 또는 미포함 구성요소). "
                               "④ 검토구간에서 다시 확정하세요.")
        if usable:
            self.node_set = saved
            self.kg, self.kg_reason = ai_cells.load_kg_for(saved)
            self.kg_chip.set_state("지식그래프 없음: %s · 도면만으로 분석" % self.kg_reason, "warn")
            self.kg_chip.setVisible(self.kg is None)
            self.set_results(self._saved_results(saved))
            self.stack.setCurrentIndex(1)
        else:
            if self.graph is None:
                self.empty.setText("이 도면의 그래프가 없습니다. ① 자료 등록에서 '추출·그래프 만들기'를 실행하세요."
                                   if name else "추출 결과가 없습니다. ①·②에서 도면을 등록·추출하세요.")
            elif saved is None or saved.get("status") != "confirmed":
                self.empty.setText("이 도면의 검토구간이 아직 확정되지 않았습니다. ④ 검토구간에서 구간을 확정하세요.")
            self.kpi.setText("구간 — · 편차 %d" % len(self.deviations))
            self.stack.setCurrentIndex(0)
        self._update_buttons()
        self.app.update_header()

    def _saved_results(self, node_set):
        """저장본이 있고 지금 확정본으로 만든 것이면 그것, 아니면 빈 결과. 쓰지 않은 저장본은 지우지 않고 첫 저장 때
        보관본으로 옮긴다(사람이 승인·수정한 내용을 덮어쓰지 않음)."""
        problem = None
        try:
            doc = res.load(node_set)
        except (OSError, ValueError) as exc:
            doc, problem = None, "저장된 분석 결과를 읽을 수 없음(%s)" % exc
        if doc is not None:
            if res.is_stale(doc, node_set):
                problem = "저장된 분석 결과가 이전 검토구간 확정본으로 만든 것"
            else:
                bad = res.validate(doc, node_set)
                if bad:
                    problem = "저장된 분석 결과에 문제 %d건(%s)" % (len(bad), bad[0])
        if problem:
            self._old_saved = res.store_path(node_set.get("project_id"), node_set["graph_id"])
            self.stale_chip.set_state("%s · 빈 결과로 시작(이전 파일은 첫 저장 때 보관본으로 옮김)" % problem, "warn")
            self.stale_chip.show()
            return res.empty_results(node_set, self.deviations)
        self.stale_chip.hide()
        return doc if doc is not None else res.empty_results(node_set, self.deviations)

    def set_results(self, doc):
        """결과 dict(hazop_study_results)를 보여 준다. 칸·워크시트·사용량은 이 dict에서만 그린다."""
        self.results = doc
        self._fill_matrix()
        self.usage.setText(usage_text(ai_cells.usage_total(doc)))
        self.kpi.setToolTip("%s\nAI 사용량: %s" % (self.kpi.text(), self.usage.text()))
        if self.cell:
            self.open_cell(*self.cell)
        else:
            self.sheet_stack.setCurrentIndex(0)

    def _save(self):
        """현재 결과를 저장한다. 실패해도 화면의 결과는 유지하고 상태줄·로그에 남긴다."""
        try:
            if self._old_saved and os.path.isfile(self._old_saved):
                os.replace(self._old_saved, "%s.%s.bak.json" % (self._old_saved[:-5], nodes.now_utc().replace(":", "")))
            self._old_saved = None
            res.save(self.results, self.node_set.get("project_id"))
        except OSError as exc:
            self.app.log_error("분석 결과 저장 실패", exc)
            self.app.status_message("분석 결과를 저장하지 못함: %s" % exc)
            self._unsaved = True
            return False
        self._unsaved = False
        self.app.mark_saved(nodes.now_utc())
        return True

    # ------------------------------------------------------------ AI 실행
    def running(self):
        return self.runner is not None

    def make_client(self):
        return ClaudeHttpClient(self.app.api_keys.get, model=self.app.api_keys.model)

    def selected_node_id(self):
        row = self.matrix.currentRow()
        return self._node_at(row) if self.node_set and 0 <= row < len(self.node_set["nodes"]) else None

    def _plan(self, scope):
        ns = self.node_set
        if scope == "all":
            return ai_cells.plan_units(ns, self.deviations)
        if scope == "node":
            nid = self.selected_node_id()
            return [] if nid is None else ai_cells.plan_units(
                dict(ns, nodes=[n for n in ns["nodes"] if n["node_id"] == nid]), self.deviations)
        if scope == "failed":
            return ai_cells.plan_units(ns, self.deviations, ai_cells.failed_cells(self.results))
        return [] if self.cell is None else ai_cells.plan_units(ns, self.deviations, [self.cell])

    def run_ai(self, scope="all"):
        """scope: all(모든 구간) · node(선택 행 구간) · failed(실패 칸) · cell(열린 칸). 시작했으면 True."""
        if self.running() or self.node_set is None:
            return False
        units = self._plan(scope)
        if not units:
            self.app.status_message({"node": "행렬에서 분석할 구간의 행을 고르세요.",
                                     "failed": "다시 실행할 실패 칸이 없습니다."}.get(scope, "분석할 칸이 없습니다."))
            return False
        if not self.app.api_keys.get():
            self.app.open_key_settings()
            if not self.app.api_keys.get():
                self.app.status_message("API 키가 없어 AI 분석을 시작하지 않았습니다(파일 > API 키 설정).")
                return False
        by_id = {n["node_id"]: n for n in self.node_set["nodes"]}
        ctxs = {}
        for u in units:
            if u["node_id"] not in ctxs:
                node = by_id[u["node_id"]]
                ctxs[u["node_id"]] = ai_cells.node_context(node, self.graph, self.kg,
                                                           design_intent(node, self.node_set.get("graph_id")))
        self.runner = AiRunner([(u, ctxs[u["node_id"]]) for u in units], self.deviations, self.make_client())
        self.runner.unit_done.connect(self._on_unit_done)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)
        self.progress.setRange(0, len(units))
        self.progress.setValue(0)
        self._progress_text()
        self._update_buttons()
        self.app.status_message("AI 분석 중: %d회 호출 예정" % len(units))
        self.runner.start()
        return True

    def cancel_ai(self):
        if self.running():
            self.runner.cancel()
            self.cancel_btn.setEnabled(False)
            self.app.status_message("취소 요청: 진행 중인 호출 1건을 마친 뒤 멈춥니다.")

    def shutdown(self):
        """창을 닫을 때: 남은 호출을 멈추고 진행 중인 호출의 결과까지 반영·저장한다(이미 비용이 든 결과를 버리지 않음)."""
        if self.running():
            self.runner.cancel()
            self.runner.wait()
            QCoreApplication.processEvents()
        if self._unsaved and self.results is not None:
            self._save()

    def _on_unit_done(self, unit_result):
        try:
            doc = ai_cells.apply_unit(self.results, unit_result)
        except ValueError as exc:
            self.app.log_error("AI 결과 반영 실패", exc)
            return
        self.results = doc
        self._save()
        self.set_results(doc)

    def _on_progress(self, done, total):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self._progress_text()

    def _progress_text(self):
        """'AI 12/50 · 실패 2' 한 줄을 막대 옆과 상태 표시줄에 같이 보인다."""
        failed = len(ai_cells.failed_cells(self.results)) if self.results else 0
        text = "AI %d/%d 호출%s" % (self.progress.value(), self.progress.maximum(), " · 실패 %d" % failed if failed else "")
        self.progress_label.setText(text)
        if self.running():
            self.app.status_message("AI 분석 중: " + text)

    def _on_finished(self, cancelled):
        self.runner.wait()
        done, total = self.progress.value(), self.progress.maximum()
        self.runner = None
        failed = len(ai_cells.failed_cells(self.results))
        self._progress_text()
        self.app.status_message("AI 분석 %s: %d/%d 호출%s" % ("취소됨" if cancelled else "끝남", done, total,
                                                         " · 실패 칸 %d" % failed if failed else ""))
        self._update_buttons()

    def _update_buttons(self):
        idle = not self.running() and self.node_set is not None
        for b in (self.run_all_btn, self.run_node_btn, self.retry_btn, self.rerun_cell_btn):
            b.setEnabled(idle)
        self.cancel_btn.setEnabled(self.running())
        self.cancel_btn.setVisible(self.running())
        has_failed = bool(self.results) and bool(ai_cells.failed_cells(self.results))
        self.retry_btn.setVisible(has_failed)
        self.combo.setEnabled(not self.running())
        self._update_entry_buttons()

    # ------------------------------------------------------------ 행렬
    def _node_at(self, row):
        return self.node_set["nodes"][row]["node_id"]

    def _row_of(self, node_id):
        if not self.node_set:
            return None
        return next((i for i, n in enumerate(self.node_set["nodes"]) if n["node_id"] == node_id), None)

    def _fill_matrix(self):
        """칸 한 줄(U-20). 아이템 text()는 설명 글자, 그리기는 CellDelegate가 CELL_ROLE 상태로 한다.
        AI 실행 실패 칸은 위험도 색을 쓰지 않는다(U-19): 흰 바탕 + 빨강 점선 테두리 + '! 실패'."""
        ns, summary = self.node_set, res.matrix_summary(self.results)
        failed = {(c["node_id"], c["deviation_id"]): c["ai_run"].get("error") for c in self.results["cells"]
                  if (c.get("ai_run") or {}).get("status") == "failed"}
        runs = {(c["node_id"], c["deviation_id"]): c.get("ai_run") or {} for c in self.results["cells"]}
        m = self.matrix
        cur = (m.currentRow(), m.currentColumn())
        m.clear()
        m.setRowCount(len(ns["nodes"]))
        m.setColumnCount(len(self.deviations))
        m.horizontalHeader().set_groups([(d["parameter"], d["guideword"]) for d in self.deviations])
        for c, d in enumerate(self.deviations):
            h = QTableWidgetItem("%s %s" % (d["parameter"], d["guideword"]))
            h.setToolTip("%s %s" % (d["deviation_id"], d["label"]))
            m.setHorizontalHeaderItem(c, h)
        total_s = total_u = 0
        for r, n in enumerate(ns["nodes"]):
            head = QTableWidgetItem(seg_icon(r, n["node_id"]), "%s %s" % (n["node_id"], n["name"]))
            head.setToolTip("%s %s · 구성요소 %d" % (n["node_id"], n["name"], len(n["members"])))
            m.setVerticalHeaderItem(r, head)
            for c, d in enumerate(self.deviations):
                s = summary.get(n["node_id"], {}).get(d["deviation_id"]) or {"state": "not_analyzed", "scenarios": 0,
                                                                            "max_risk": None, "unreviewed": 0}
                it = QTableWidgetItem()
                tip = "%s %s × %s" % (n["node_id"], n["name"], d["label"])
                key = (n["node_id"], d["deviation_id"])
                state = {"kind": "scored", "risk": s["max_risk"], "unreviewed": s["unreviewed"],
                         "scenarios": s["scenarios"]}
                if key in failed:
                    it.setText("실패")
                    state = {"kind": "failed"}
                    tip = "%s\nAI 실행 실패(위험도 아님): %s" % (tip, failed[key] or "-")
                elif s["state"] == "not_analyzed":
                    it.setText("분석 전")
                    state = {"kind": "not_analyzed"}
                elif s["state"] == "excluded":
                    it.setText("제외")
                    state = {"kind": "excluded"}
                else:
                    lines = ["%d건" % s["scenarios"]]
                    if s["max_risk"] is not None:
                        lines.append("위험 %d" % s["max_risk"])
                    if s["scenarios"] == 0 and not s["unreviewed"] and runs.get(key, {}).get("status") == "ok":
                        lines = [empty_cell_label(runs[key]), "AI 초안"]
                        state = {"kind": "empty"}
                    else:
                        lines.append("미검토 %d" % s["unreviewed"] if s["unreviewed"] else "완료")
                    it.setText("\n".join(lines))
                    tip = "%s\n%s" % (tip, " · ".join(lines))
                it.setData(CELL_ROLE, state)
                total_s += s["scenarios"]
                total_u += s["unreviewed"]
                it.setToolTip(tip)
                m.setItem(r, c, it)
        if cur[0] >= 0 and cur[1] >= 0:
            m.setCurrentCell(*cur)
        self.kpi.setText("구간 %d · 편차 %d · 시나리오 %d · 미검토 %d%s"
                         % (len(ns["nodes"]), len(self.deviations), total_s, total_u,
                            " · 실패 %d" % len(failed) if failed else ""))
        self._update_buttons()

    # ------------------------------------------------------------ 워크시트
    def _entity_label(self, eid):
        for n in (self.graph or {}).get("nodes", []):
            if n["entity_id"] == eid:
                return n.get("tag") or n.get("kind") or eid
        return eid

    def _cell_doc(self):
        if not self.cell or not self.results:
            return None
        return next((c for c in self.results["cells"] if (c["node_id"], c["deviation_id"]) == self.cell), None)

    def _basis_text(self, e):
        basis = e.get("ai_basis") or {}
        lines = [" → ".join(self._entity_label(x) for x in p) for p in basis.get("kg_paths") or []]
        lines += ["%s %s" % (s.get("doc") or "", s.get("where") or "") for s in basis.get("sources") or []]
        lines += ["⚠ %s" % w for w in basis.get("warnings") or []]
        return "\n".join(lines) or "-"

    def open_cell(self, node_id, deviation_id):
        node = next((n for n in self.node_set["nodes"] if n["node_id"] == node_id), None)
        dev = next((d for d in self.deviations if d["deviation_id"] == deviation_id), None)
        if node is None or dev is None:
            return False
        keep = (self.selected_entry() or {}).get("entry_id") if self.cell == (node_id, deviation_id) else None
        self.cell = (node_id, deviation_id)
        cell = self._cell_doc()
        row = self._row_of(node_id)
        self.sheet_badge.setPixmap(seg_icon(row, node_id).pixmap(30, 16))
        self.sheet_title.setText("%s × %s" % (node["name"], dev["label"]))
        self.app.set_selection({"kind": "cell", "drawing": self.name, "node_id": node_id, "deviation_id": deviation_id})
        run = (cell or {}).get("ai_run") or {}
        if run.get("status") == "failed":
            self.run_note.setText("AI 실행 실패: %s" % (run.get("error") or "-"))
        else:
            self.run_note.setText("AI 메모: %s" % run["note"] if run.get("note") else "")
        self.run_note.setVisible(bool(self.run_note.text()))
        intent = design_intent(node, self.node_set.get("graph_id"))
        self.intent.setText("설계 의도: %s" % intent[0] if intent else "설계의도 미입력")
        self.intent_src.setText("출처: %s" % intent[1] if intent else "")
        self.intent_src.setVisible(bool(intent))
        entries = (cell or {}).get("entries") or []
        drafts = sum(1 for e in entries if res.is_ai_draft(e))
        self.draft_chip.set_state("AI 초안 %d건" % drafts if drafts else "", "warn" if drafts else "")
        self.draft_chip.setVisible(bool(drafts))
        live = [e for e in entries if e.get("status") != "rejected"]
        self.sheet_count.setText("시나리오 %d · 기각 %d" % (len(live), len(entries) - len(live)) if entries else "")
        t = self.table
        t.clearSelection()
        t.setRowCount(max(len(entries), 1))
        t.clearSpans()
        if not entries:
            t.setSpan(0, 0, 1, len(SHEET_COLUMNS))
            for c in range(len(SHEET_COLUMNS)):
                t.setItem(0, c, QTableWidgetItem(""))
            state = "AI 실행 실패" if run.get("status") == "failed" else (
                "AI 초안 · %s" % empty_cell_label(run) if (cell or {}).get("state") == "analyzed" else "분석 전")
            t.item(0, 0).setText("%s · 항목 없음" % state)
            t.item(0, 0).setForeground(QColor(tokens.c("muted")))
            t.item(0, 0).setFlags(Qt.ItemIsEnabled)
        for r, e in enumerate(entries):
            draft = res.is_ai_draft(e)
            status = STATUS_LABELS.get(e.get("status"), e.get("status") or "-")
            basis = self._basis_text(e)
            values = (e.get("cause"), e.get("consequence"), ", ".join(e.get("safeguards") or []),
                      e.get("recommendation"), risk_text(e.get("risk")), basis,
                      ("AI 초안 · " if draft else "") + status)
            for c, v in enumerate(values):
                it = QTableWidgetItem(v or "-")
                it.setData(Qt.UserRole, e["entry_id"])
                it.setData(DRAFT_ROLE, draft)
                t.setItem(r, c, it)
            risk_it = t.item(r, COL_RISK)
            risk_it.setToolTip("강도 %s · 발생빈도 %s" % (e.get("severity") or "-", e.get("frequency") or "-"))
            if tokens.risk_band(e.get("risk")):
                bg, ink, _line = tokens.risk_colors(e["risk"])
                risk_it.setBackground(QColor(bg))
                risk_it.setForeground(QColor(ink))
            basis_it = t.item(r, COL_BASIS)
            basis_it.setToolTip(basis)
            if e.get("status") == "rejected":
                for c in range(len(SHEET_COLUMNS)):
                    t.item(r, c).setForeground(QColor(tokens.c("muted")))
        t.resizeRowsToContents()
        ids = [e["entry_id"] for e in entries]
        if keep in ids:
            t.selectRow(ids.index(keep))
        self.sheet_stack.setCurrentIndex(1)
        if row is not None:
            c = next(i for i, d in enumerate(self.deviations) if d["deviation_id"] == deviation_id)
            self.matrix.setCurrentCell(row, c)
        self._update_entry_buttons()
        return True

    # ------------------------------------------------------------ 항목 검토
    def selected_entry(self):
        ids = {i.data(Qt.UserRole) for i in self.table.selectedItems()}
        cell = self._cell_doc()
        if len(ids) != 1 or cell is None:
            return None
        eid = ids.pop()
        return next((e for e in cell["entries"] if e["entry_id"] == eid), None)

    def select_entry(self, index):
        self.table.selectRow(index)

    def _update_entry_buttons(self):
        # 실행 중에는 AI 결과가 같은 칸의 제안 항목을 바꿔 끼울 수 있어 검토 조작을 막는다(수정 내용 유실 방지)
        e = None if self.running() else self.selected_entry()
        self.approve_btn.setEnabled(e is not None and e.get("status") != "approved")
        self.reject_btn.setEnabled(e is not None and e.get("status") != "rejected")
        self.edit_btn.setEnabled(e is not None)
        self._place_row_actions()

    def _place_row_actions(self):
        """고른 행의 상태 칸 아래쪽에 동작 버튼을 띄운다. 그 행 높이는 버튼이 들어가게 늘린다."""
        rows = {i.row() for i in self.table.selectedItems()}
        if len(rows) != 1 or self.selected_entry() is None:
            self.row_actions.hide()
            return
        row = rows.pop()
        need = self.row_actions.sizeHint()
        cell = self.table.visualRect(self.table.model().index(row, COL_STATUS))
        text_h = self.table.fontMetrics().height() + 8
        if cell.height() < text_h + need.height():
            self.table.setRowHeight(row, text_h + need.height())
            cell = self.table.visualRect(self.table.model().index(row, COL_STATUS))
        w = max(need.width(), cell.width())
        self.row_actions.setGeometry(cell.right() - w + 1, cell.bottom() - need.height(), w, need.height())
        self.row_actions.show()
        self.row_actions.raise_()

    def _apply_review(self, doc):
        self.results = doc
        self._save()
        self.set_results(doc)

    def _undo_to(self, old, cell):
        """토스트 실행 취소: 바로 전 결과로 되돌려 저장한다. 이 동작 뒤 결과가 조금이라도 바뀌었으면(다른 승인·AI 결과
        반영·도면 바꾸기) 되돌리지 않는다. 결과 문서 전체를 바꿔 끼우므로 그 사이 변경을 지우지 않게 한다."""
        after = self.results

        def undo():
            if self.running() or self.results is not after:
                self.app.status_message("그 뒤에 결과가 바뀌어 되돌리지 않았습니다.")
                return
            self._apply_review(old)
            self.open_cell(*cell)
        return undo

    def set_entry_status(self, status):
        e = None if self.running() else self.selected_entry()
        if e is None:
            return False
        old, cell = self.results, self.cell
        self._apply_review(res.set_status(self.results, self.cell[0], self.cell[1], e["entry_id"], status))
        dev = next((d["label"] for d in self.deviations if d["deviation_id"] == cell[1]), cell[1])
        self.app.toast("%s × %s 시나리오를 %s했습니다" % (cell[0], dev, STATUS_LABELS[status]), self._undo_to(old, cell))
        return True

    def edit_selected(self, fields=None):
        """fields가 없으면 수정 창을 띄운다. 바뀐 필드가 없으면 저장하지 않는다."""
        e = None if self.running() else self.selected_entry()
        if e is None:
            return False
        if fields is None:
            dlg = EntryDialog(e, self)
            if dlg.exec() != QDialog.Accepted:
                return False
            fields = dlg.changed()
        if not fields:
            return False
        old, cell = self.results, self.cell
        self._apply_review(res.edit_entry(self.results, self.cell[0], self.cell[1], e["entry_id"], fields))
        self.app.toast("%s 시나리오를 수정했습니다" % cell[0], self._undo_to(old, cell))
        return True
