"""⑤ 분석 결과 화면 (stage3-spec §B results.py, 디자인/시안/완성본/B-고밀도작업대/5-요약행렬).

확정된 검토구간 집합 × 편차(results.load_deviations) 행렬과 칸별 워크시트. AI 분석은 4단계에서 연결되므로 이 단계의 결과는
빈 셸(results.empty_results)이고 저장하지 않는다. set_results로 결과 dict를 넣으면 같은 화면이 그 내용을 보여 준다.
AI가 쓴 항목은 승인 전까지 언제나 'AI 초안'으로 표시한다(results.is_ai_draft).
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import data, tokens
from hazop.app.screens.study import seg_icon
from hazop.app.widgets import Chip, empty_label, plain_label
from hazop.study import nodes
from hazop.study import results as res
from hazop.viewer import build as viewer_build

AI_NOTE = "AI 분석은 4단계에서 연결됩니다 · AI 결과는 모두 초안"
STATUS_LABELS = {"proposed": "제안", "revised": "수정", "approved": "승인", "rejected": "기각"}
SHEET_COLUMNS = ("원인", "결과", "보호수단", "권고", "AI 근거", "상태")
CELL_W, SHEET_W = 66, 430


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
        self.deviations = res.load_deviations()
        self.cell = None       # (node_id, deviation_id)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("도면"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        self.combo.currentIndexChanged.connect(self._load)
        bar.addWidget(self.combo)
        self.kpi = Chip()
        bar.addWidget(self.kpi)
        bar.addStretch(1)
        self.legacy_btn = QPushButton("이전 고정 응답 분석 열기")
        self.legacy_btn.setToolTip("MVP 고정 응답 분석·설계보완 화면(이전 ④⑤)")
        self.legacy_btn.clicked.connect(lambda: self.app.go(2))
        bar.addWidget(self.legacy_btn)
        lay.addLayout(bar)

        self.stack = QStackedWidget()
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        self.empty = empty_label("확정된 검토구간이 없습니다. ④ 검토구간에서 구간을 확정하면 여기서 구간 × 편차 결과를 봅니다.")
        el.addWidget(self.empty)
        self.to_study_btn = QPushButton("④ 검토구간으로")
        self.to_study_btn.clicked.connect(lambda: self.app.go(5))
        el.addWidget(self.to_study_btn, 0, Qt.AlignHCenter)
        el.addStretch(1)
        self.stack.addWidget(empty)

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(4)
        head = QHBoxLayout()
        t = QLabel("구간 × 편차 요약")
        t.setObjectName("section")
        head.addWidget(t)
        self.ai_chip = Chip(AI_NOTE)
        head.addWidget(self.ai_chip)
        head.addStretch(1)
        left.addLayout(head)
        self.matrix = QTableWidget()
        self.matrix.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.matrix.setSelectionMode(QAbstractItemView.SingleSelection)
        self.matrix.horizontalHeader().setDefaultSectionSize(CELL_W)
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.matrix.verticalHeader().setDefaultSectionSize(40)
        self.matrix.cellClicked.connect(lambda r, c: self.open_cell(self._node_at(r), self.deviations[c]["deviation_id"]))
        left.addWidget(self.matrix, 1)
        note = QLabel("칸 = 시나리오 수 · 최고 위험 · 미검토 수. 빗금 '분석 전' = 아직 분석하지 않은 칸")
        note.setObjectName("muted")
        note.setWordWrap(True)
        left.addWidget(note)
        bl.addLayout(left, 1)
        bl.addWidget(self._sheet())
        self.stack.addWidget(body)
        lay.addWidget(self.stack, 1)

    def _sheet(self):
        frame = QFrame()
        frame.setObjectName("panel")
        frame.setFixedWidth(SHEET_W)
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
        t = QLabel("상세 워크시트")
        t.setObjectName("section")
        v.addWidget(t)
        self.sheet_stack = QStackedWidget()
        self.sheet_stack.addWidget(empty_label("행렬의 칸을 누르면 구간 × 편차 워크시트가 열립니다."))
        sheet = QWidget()
        sv = QVBoxLayout(sheet)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(4)
        hrow = QHBoxLayout()
        self.sheet_badge = QLabel()
        hrow.addWidget(self.sheet_badge)
        self.sheet_title = plain_label("", wrap=True)
        self.sheet_title.setObjectName("title")
        hrow.addWidget(self.sheet_title, 1)
        sv.addLayout(hrow)
        self.ai_banner = QFrame()
        self.ai_banner.setObjectName("ai_box")
        al = QVBoxLayout(self.ai_banner)
        al.setContentsMargins(8, 4, 8, 4)
        self.ai_banner_label = QLabel(AI_NOTE)
        self.ai_banner_label.setWordWrap(True)
        al.addWidget(self.ai_banner_label)
        sv.addWidget(self.ai_banner)
        self.intent = plain_label("", wrap=True)
        sv.addWidget(self.intent)
        self.intent_src = plain_label("", name="muted", wrap=True)
        sv.addWidget(self.intent_src)
        self.table = QTableWidget(0, len(SHEET_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(SHEET_COLUMNS))
        self.table.horizontalHeaderItem(4).setToolTip("AI 근거: 지식그래프 경로 · 출처 문서")
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        sv.addWidget(self.table, 1)
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

    def on_enter(self):
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
        if self.combo.findText(drawing_name) >= 0 and self.combo.currentText() != drawing_name:
            self.combo.setCurrentText(drawing_name)
        row = self._row_of(node_id)
        if row is not None:
            self.matrix.selectRow(row)
            self.open_cell(node_id, self.deviations[0]["deviation_id"])

    # ------------------------------------------------------------ 읽기
    def _load(self):
        name = self.combo.currentText()
        self.name, self.graph, self.node_set, self.results, self.cell = name or None, None, None, None, None
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
            self.set_results(res.empty_results(saved, self.deviations))
            self.stack.setCurrentIndex(1)
        else:
            if self.graph is None:
                self.empty.setText("이 도면의 그래프가 없습니다. ① 자료 등록에서 '추출·그래프 만들기'를 실행하세요."
                                   if name else "추출 결과가 없습니다. ①·②에서 도면을 등록·추출하세요.")
            elif saved is None or saved.get("status") != "confirmed":
                self.empty.setText("이 도면의 검토구간이 아직 확정되지 않았습니다. ④ 검토구간에서 구간을 확정하세요.")
            self.kpi.set_state("구간 — · 편차 %d" % len(self.deviations))
            self.stack.setCurrentIndex(0)
        self.app.update_header()

    def set_results(self, doc):
        """결과 dict(hazop_study_results)를 보여 준다. 칸·워크시트는 이 dict에서만 그린다."""
        self.results = doc
        self._fill_matrix()
        if self.cell:
            self.open_cell(*self.cell)
        else:
            self.sheet_stack.setCurrentIndex(0)

    # ------------------------------------------------------------ 행렬
    def _node_at(self, row):
        return self.node_set["nodes"][row]["node_id"]

    def _row_of(self, node_id):
        if not self.node_set:
            return None
        return next((i for i, n in enumerate(self.node_set["nodes"]) if n["node_id"] == node_id), None)

    def _fill_matrix(self):
        ns, summary = self.node_set, res.matrix_summary(self.results)
        m = self.matrix
        m.clear()
        m.setRowCount(len(ns["nodes"]))
        m.setColumnCount(len(self.deviations))
        m.setHorizontalHeaderLabels(["%s\n%s" % (d["parameter"], d["guideword"]) for d in self.deviations])
        for c, d in enumerate(self.deviations):
            m.horizontalHeaderItem(c).setToolTip("%s %s" % (d["deviation_id"], d["label"]))
        hatch = QBrush(QColor(tokens.c("ai-hatch-b")), Qt.BDiagPattern)
        total_s = total_u = 0
        for r, n in enumerate(ns["nodes"]):
            head = QTableWidgetItem(seg_icon(r, n["node_id"]), "%s %s" % (n["node_id"], n["name"]))
            head.setToolTip("%s %s · 구성요소 %d" % (n["node_id"], n["name"], len(n["members"])))
            m.setVerticalHeaderItem(r, head)
            for c, d in enumerate(self.deviations):
                s = summary.get(n["node_id"], {}).get(d["deviation_id"]) or {"state": "not_analyzed", "scenarios": 0,
                                                                            "max_risk": None, "unreviewed": 0}
                it = QTableWidgetItem()
                it.setTextAlignment(Qt.AlignCenter)
                if s["state"] == "not_analyzed":
                    it.setText("분석 전")
                    it.setBackground(hatch)
                    it.setForeground(QColor(tokens.c("muted")))
                elif s["state"] == "excluded":
                    it.setText("제외")
                    it.setForeground(QColor(tokens.c("muted")))
                else:
                    lines = ["%d건" % s["scenarios"]]
                    if s["max_risk"] is not None:
                        lines.append("위험 %d" % s["max_risk"])
                        bg, ink, _line = tokens.risk_colors(s["max_risk"])
                        it.setBackground(QColor(bg))
                        it.setForeground(QColor(ink))
                    lines.append("미검토 %d" % s["unreviewed"] if s["unreviewed"] else "완료")
                    it.setText("\n".join(lines))
                total_s += s["scenarios"]
                total_u += s["unreviewed"]
                it.setToolTip("%s %s × %s" % (n["node_id"], n["name"], d["label"]))
                m.setItem(r, c, it)
        m.resizeRowsToContents()
        self.kpi.set_state("구간 %d · 편차 %d · 시나리오 %d · 미검토 %d"
                           % (len(ns["nodes"]), len(self.deviations), total_s, total_u))

    # ------------------------------------------------------------ 워크시트
    def _entity_label(self, eid):
        for n in (self.graph or {}).get("nodes", []):
            if n["entity_id"] == eid:
                return n.get("tag") or n.get("kind") or eid
        return eid

    def open_cell(self, node_id, deviation_id):
        node = next((n for n in self.node_set["nodes"] if n["node_id"] == node_id), None)
        dev = next((d for d in self.deviations if d["deviation_id"] == deviation_id), None)
        cell = next((c for c in self.results["cells"]
                     if c["node_id"] == node_id and c["deviation_id"] == deviation_id), None)
        if node is None or dev is None:
            return False
        self.cell = (node_id, deviation_id)
        row = self._row_of(node_id)
        self.sheet_badge.setPixmap(seg_icon(row, node_id).pixmap(30, 16))
        self.sheet_title.setText("%s × %s" % (node["name"], dev["label"]))
        intent = design_intent(node, self.node_set.get("graph_id"))
        self.intent.setText("설계 의도: %s" % intent[0] if intent else "설계의도 미입력")
        self.intent_src.setText("출처: %s" % intent[1] if intent else "")
        entries = (cell or {}).get("entries") or []
        t = self.table
        t.setRowCount(max(len(entries), 1))
        t.clearSpans()
        if not entries:
            t.setSpan(0, 0, 1, len(SHEET_COLUMNS))
            for c in range(len(SHEET_COLUMNS)):
                t.setItem(0, c, QTableWidgetItem(""))
            t.item(0, 0).setText("분석 전 · 항목 없음 (AI 분석은 4단계에서 연결)")
            t.item(0, 0).setForeground(QColor(tokens.c("muted")))
        for r, e in enumerate(entries):
            basis = e.get("ai_basis") or {}
            paths_txt = [" → ".join(self._entity_label(x) for x in p) for p in basis.get("kg_paths") or []]
            srcs = ["%s %s" % (s.get("doc") or "", s.get("where") or "") for s in basis.get("sources") or []]
            status = STATUS_LABELS.get(e.get("status"), e.get("status") or "-")
            draft = res.is_ai_draft(e)
            values = (e.get("cause"), e.get("consequence"), ", ".join(e.get("safeguards") or []),
                      e.get("recommendation"), "\n".join(paths_txt + srcs) or "-",
                      ("AI 초안 · " if draft else "") + status)
            for c, v in enumerate(values):
                it = QTableWidgetItem(v or "-")
                if draft:
                    it.setBackground(QColor(tokens.c("ai-hatch-a")))
                t.setItem(r, c, it)
        t.resizeRowsToContents()
        self.sheet_stack.setCurrentIndex(1)
        if row is not None:
            c = next(i for i, d in enumerate(self.deviations) if d["deviation_id"] == deviation_id)
            self.matrix.setCurrentCell(row, c)
        return True
