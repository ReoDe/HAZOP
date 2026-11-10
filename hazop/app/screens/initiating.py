"""⑥ 초기사건 화면 (기획서/초기사건-출력설계.md §7, §8 P3, 디자인/시안/초기사건/6-그룹·6-완전성대조).

⑤에서 승인한 원인(IE 후보)을 PSA 초기사건 그룹으로 묶고, 사건수목 표제·최종상태·기본사건 후보를 고치고, 일반 범주
기준표와 대조한다. 탭은 묶음 시트 순서다(후보 · 그룹 · 사건수목 표제 · 최종상태 · 기본사건 · 완전성 대조 · 품질 경고).
- 화면은 얇다. 편집은 hazop.ie.model 함수 하나를 부르고 store.save로 바로 저장한다(떠날 때 물을 것이 없음).
  보이는 것은 모두 bundle.build_bundle의 dict에서 그린다. 화면에서 본 것이 Excel에 그대로 나간다.
- 그룹 상태는 model.effective_status다. [확정] 버튼은 confirm()과 같은 confirm_problems로 켜고 끈다.
- 규칙 초안(§6.3)은 버튼을 눌렀을 때만 만든다. AI·규칙 산출은 빗금, 사람이 정한 것은 흰 바탕 진한 테두리다.
- 사건수목 표제 후보는 목록으로만 보인다(E10). 성공·실패 분기나 순서는 그리지 않는다.
- ⑤ 결과는 마지막으로 저장된 파일을 읽는다(⑤ 화면에만 있고 저장하지 못한 수정은 반영되지 않음, 상태줄에 기준 시각).
  확정과 내보내기 직전에는 저장본을 다시 읽어, 그사이 ⑤가 바뀌었으면 ⑥을 다시 읽는다.
"""

import os
from datetime import datetime, timezone

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSplitter,
                               QStackedWidget, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from hazop.app import data, related, tokens
from hazop.app.widgets import Banner, Chip, empty_label, kst_text, plain_label
from hazop.ie import bundle as ib
from hazop.ie import bundle_xlsx as ix
from hazop.ie import model, store
from hazop.study import nodes, refs
from hazop.study import results as res

INTRO = "⑤에서 승인한 원인을 초기사건 후보로 삼아 PSA 초기사건 그룹으로 묶습니다. 빈도 산정과 정량화는 PSA 도구에서 합니다."
TABS = ("후보", "그룹", "사건수목 표제", "최종상태", "기본사건", "완전성 대조", "품질 경고")
TAB_GROUP, TAB_COVERAGE = 1, 5
ORIGIN_ROLE = Qt.UserRole + 20
ID_ROLE = Qt.UserRole + 21
SCOPE_CHIP = "그룹 확정 조건 검사 %d/%d 통과 — 완전성을 뜻하지 않음"
KEYS = "G 그룹 만들기 · M 옮기기 · S 나누기 · Ctrl+Enter 확정 · Ctrl+R 규칙 초안"
EDIT_LABELS = {
    "group": (("name", "그룹 이름"), ("definition", "정의"), ("categories", "일반 범주(쉼표로 여럿)"),
              ("representative", "대표 후보(IEC)"), ("representative_reason", "대표 선정 이유"),
              ("plant_response", "플랜트 응답"), ("affected_mitigation", "영향받는 완화계통"),
              ("support_ie", "지원계통 IE")),
    "heading": (("name", "표제 이름"), ("targets", "구현 대상(안정 참조, 쉼표)"), ("systems", "관련 계통"),
                ("role", "역할"), ("actuation", "작동 방식"), ("operator_cue", "운전원 조치 단서")),
    "end_state": (("text", "비완화 결과(대표 문장)"), ("category", "결과 범주")),
    "basic_event": (("name", "앱 제안 이름"), ("equipment_kind", "기기 종류"), ("system", "계통"),
                    ("failure_mode", "고장모드 코드"), ("failure_text", "고장모드 설명")),
}
CHOICES = {"support_ie": model.SUPPORT_IE, "role": refs.ROLES, "actuation": refs.ACTUATIONS,
           "category": model.ES_CATEGORIES}
LISTS = ("categories", "targets")
KIND_TABLES = {"heading": "top_events", "end_state": "end_states", "basic_event": "basic_events"}
KIND_IDS = {"heading": "heading_id", "end_state": "end_state_id", "basic_event": "be_id"}
GROUP_CHIP = {"confirmed": "human", "draft": "ai"}


class OriginDelegate(QStyledItemDelegate):
    """AI·규칙 산출 행은 빗금 바탕, '작성' 칸은 칩(AI 초안 = 빗금·점선, 사람 = 흰 바탕·진한 테두리)."""

    def __init__(self, origin_col, parent=None):
        super().__init__(parent)
        self.origin_col = origin_col

    def paint(self, p, option, index):
        origin = index.data(ORIGIN_ROLE)
        c = tokens.COLORS
        if origin == "ai_draft":
            p.save()
            p.fillRect(option.rect, QColor(c["ai-hatch-a"]))
            p.fillRect(option.rect, QBrush(QColor(c["ai-hatch-b"]), Qt.BDiagPattern))
            p.restore()
        if index.column() != self.origin_col or origin is None:
            return super().paint(p, option, index)
        text = index.data() or ""
        fm = option.fontMetrics
        r = option.rect.adjusted(4, 4, -4, -4)
        r.setWidth(min(r.width(), fm.horizontalAdvance(text) + 14))
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        human = origin == "human"
        pen = QPen(QColor(c["human-line"] if human else c["ai-ink"]), 1.5 if human else 1,
                   Qt.SolidLine if human else Qt.DashLine)
        p.setPen(pen)
        p.setBrush(QColor(c["card"] if human else c["ai-hatch-a"]))
        p.drawRoundedRect(r, 3, 3)
        p.setPen(QColor(c["human-line"] if human else c["ai-ink"]))
        p.drawText(r, Qt.AlignCenter, text)
        p.restore()


def _table(columns, name, origin_col=None, multi=False):
    t = QTableWidget(0, len(columns))
    t.setObjectName(name)
    t.setAccessibleName(name)
    t.setHorizontalHeaderLabels([c for c, _ in columns])
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection)
    t.verticalHeader().hide()
    t.setWordWrap(False)
    t.verticalHeader().setDefaultSectionSize(26)
    h = t.horizontalHeader()
    for i, (_, w) in enumerate(columns):
        if w:
            t.setColumnWidth(i, w)
    h.setStretchLastSection(False)
    stretch = [i for i, (_, w) in enumerate(columns) if not w]
    for i in stretch:
        h.setSectionResizeMode(i, QHeaderView.Stretch)
    if origin_col is not None:
        t.setItemDelegate(OriginDelegate(origin_col, t))
    return t


def _fill(table, rows, ids=None, origins=None):
    """rows: [[글자, ...]]. ids·origins는 행마다 ID_ROLE·ORIGIN_ROLE 값."""
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem("" if v is None else str(v))
            it.setToolTip(it.text())
            if ids is not None:
                it.setData(ID_ROLE, ids[r])
            if origins is not None:
                it.setData(ORIGIN_ROLE, origins[r])
            table.setItem(r, c, it)


def _selected_ids(table):
    rows = sorted({i.row() for i in table.selectedItems()})
    return [table.item(r, 0).data(ID_ROLE) for r in rows if table.item(r, 0)]


def _joined(xs):
    return ", ".join(xs or [])


class FieldsDialog(QDialog):
    """EDIT_LABELS 한 종류의 필드를 고치는 대화상자. 고른 값(바뀐 것만)을 fields()로."""

    def __init__(self, title, kind, record, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.record, self.inputs = record, {}
        form = QFormLayout(self)
        for key, label in EDIT_LABELS[kind]:
            v = record.get(key)
            if key in CHOICES:
                w = QComboBox()
                for k, text in CHOICES[key].items():
                    w.addItem(text, k)
                w.setCurrentIndex(max(0, w.findData(v)))
            else:
                w = QLineEdit(", ".join(v) if key in LISTS else (v or ""))
                w.setMinimumWidth(360)
            w.setAccessibleName(label)
            form.addRow(label, w)
            self.inputs[key] = w
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def fields(self):
        out = {}
        for key, w in self.inputs.items():
            if isinstance(w, QComboBox):
                v = w.currentData()
            elif key in LISTS:
                v = [x.strip() for x in w.text().split(",") if x.strip()]
            elif key == "representative":
                v = w.text().strip() or None
            else:
                v = w.text().strip()
            if v != self.record.get(key):
                out[key] = v
        return out


class InitiatingScreen(QWidget):
    title = "⑥ 초기사건"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.name = None          # 프로젝트를 정한 도면(추출 이름)
        self.project_id = None
        self.pg = self.node_set = self.results = None
        self.doc, self.fp, self.view = None, None, None
        self.unreadable = None    # store.Unreadable(읽기 전용으로 멈춤)
        self.results_at = None    # ⑤ 결과 파일 저장 시각(UTC)
        self.group_id = None      # 그룹 탭에서 보는 그룹
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        lay.addLayout(self._top())
        self.kpi = QLabel("")
        self.kpi.setObjectName("muted")
        self.kpi.setTextFormat(Qt.PlainText)
        lay.addWidget(self.kpi)
        self.banner = Banner("warn")
        lay.addWidget(self.banner)
        self.replace_btn = QPushButton("원본을 백업하고 빈 문서로 새로 시작…")
        self.replace_btn.clicked.connect(lambda: self.replace_unreadable())
        self.replace_btn.hide()
        lay.addWidget(self.replace_btn, 0, Qt.AlignLeft)
        self.stack = QStackedWidget()
        self.empty = empty_label("")
        self.stack.addWidget(self.empty)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for build in (self._candidates_tab, self._group_tab, self._headings_tab, self._end_states_tab,
                      self._basic_events_tab, self._coverage_tab, self._warnings_tab):
            w, title = build()
            self.tabs.addTab(w, title)
        self.stack.addWidget(self.tabs)
        lay.addWidget(self.stack, 1)
        foot = QHBoxLayout()
        self.scope_chip = Chip(elide=Qt.ElideRight)
        foot.addWidget(self.scope_chip)
        self.basis = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=12)
        foot.addWidget(self.basis, 1)
        keys = plain_label(KEYS, name="muted", elide=Qt.ElideRight, min_chars=12)
        foot.addWidget(keys, 1)
        lay.addLayout(foot)
        self._update_buttons()

    # ------------------------------------------------------------ 틀
    def _top(self):
        row = QHBoxLayout()
        head = QLabel("⑥ 초기사건 후보·그룹")
        head.setObjectName("title")
        row.addWidget(head)
        intro = plain_label(INTRO, name="muted", elide=Qt.ElideRight, min_chars=12)
        row.addWidget(intro, 1)
        self.suggest_btn = QPushButton("규칙 초안 만들기")
        self.suggest_btn.setToolTip("같은 일반 범주 안에서 보호수단이 같은 후보끼리 초안 그룹으로 묶습니다(§6.3). "
                                    "확정한 그룹은 건드리지 않고, 만든 것은 모두 'AI 초안'입니다.")
        self.suggest_btn.clicked.connect(lambda: self.suggest())
        self.export_btn = QPushButton("IE 인계 묶음 내보내기")
        self.export_btn.setObjectName("primary")
        self.export_btn.setToolTip("승인한 항목만으로 IE 인계 묶음(Excel + JSON 원본)을 저장합니다. HAZOP 위험도는 넣지 않습니다.")
        self.export_btn.clicked.connect(lambda: self.export_bundle())
        row.addWidget(self.suggest_btn)
        row.addWidget(self.export_btn)
        return row

    def _buttons(self, *specs):
        row = QHBoxLayout()
        row.setSpacing(6)
        out = []
        for text, tip, fn in specs:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
            out.append(b)
        row.addStretch(1)
        return row, out

    def _candidates_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 0)
        row, (self.create_btn, self.move_btn, self.unassign_btn, self.accept_member_btn) = self._buttons(
            ("그룹 만들기… (G)", "고른 후보로 새 그룹을 만듭니다(사람이 정한 소속)", lambda: self.create_group()),
            ("그룹으로 옮기기… (M)", "고른 후보를 다른 그룹으로 옮깁니다", lambda: self.move_selected()),
            ("그룹에서 빼기", "고른 후보를 그룹 없음으로 둡니다", lambda: self.move_selected(None)),
            ("규칙 배정 확인", "규칙이 배정한 소속을 사람이 확인한 것으로 바꿉니다", lambda: self.accept_members()))
        v.addLayout(row)
        self.cand_table = _table((("후보", 74), ("판정", 46), ("원인", 0), ("구간 · 편차", 150), ("일반 범주", 110),
                                  ("그룹", 64), ("배정 작성", 70), ("판정 작성", 72)), "IE 후보 표", origin_col=7, multi=True)
        self.cand_table.itemSelectionChanged.connect(self._update_buttons)
        v.addWidget(self.cand_table, 1)
        return w, TABS[0]

    def _group_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 4, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        center = QWidget()
        v = QVBoxLayout(center)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        head = QHBoxLayout()
        self.group_combo = QComboBox()
        self.group_combo.setAccessibleName("초기사건 그룹")
        self.group_combo.setMinimumWidth(220)
        self.group_combo.currentIndexChanged.connect(lambda _i: self.show_group(self.group_combo.currentData()))
        head.addWidget(self.group_combo)
        self.group_chip = Chip()
        head.addWidget(self.group_chip)
        head.addStretch(1)
        _row, (self.edit_group_btn, self.split_btn, self.delete_btn, self.reopen_btn, self.confirm_btn) = self._buttons(
            ("고치기…", "그룹 이름·정의·범주·대표 후보·플랜트 응답 등을 고칩니다", lambda: self.edit_group()),
            ("나누기… (S)", "소속 후보 일부를 새 그룹으로 나눕니다(옛 ID는 '나뉨' 기록)", lambda: self.split_group()),
            ("지우기", "초안 그룹만 지웁니다(ID는 '삭제' 기록으로 남음)", lambda: self.delete_group()),
            ("확정 풀기", "확정을 풀어 초안으로 되돌립니다", lambda: self.reopen_group()),
            ("확정 (Ctrl+Enter)", "검토자 이름으로 그룹을 확정합니다. 확정 조건이 모두 맞을 때만 켜집니다",
             lambda: self.confirm_group()))
        self.confirm_btn.setObjectName("primary")
        for b in (self.edit_group_btn, self.split_btn, self.delete_btn, self.reopen_btn, self.confirm_btn):
            head.addWidget(b)
        v.addLayout(head)
        self.group_box = QFrame()
        self.group_box.setObjectName("ai_box")
        form = QFormLayout(self.group_box)
        form.setContentsMargins(10, 6, 10, 6)
        form.setVerticalSpacing(2)
        self.group_fields = {}
        for key, label in (("definition", "정의"), ("categories", "일반 범주"), ("representative", "대표 후보"),
                           ("plant_response", "플랜트 응답"), ("affected_mitigation", "완화계통"),
                           ("support_ie", "지원계통 IE"), ("frequency", "빈도 근거")):
            lab = plain_label("", elide=Qt.ElideRight, min_chars=20)
            form.addRow(label, lab)
            self.group_fields[key] = lab
        self.group_fields["frequency"].setText("앱에서 다루지 않음 — PSA 담당 기입 칸")
        v.addWidget(self.group_box)
        self.members_label = QLabel("")
        self.members_label.setObjectName("muted")
        v.addWidget(self.members_label)
        self.member_table = _table((("후보", 74), ("원인", 0), ("구간 · 편차", 150), ("위치", 110), ("⑤ 상태", 60),
                                    ("배정 작성", 70)), "소속 후보 표", origin_col=5, multi=True)
        self.member_table.itemSelectionChanged.connect(self._show_trace)
        v.addWidget(self.member_table, 3)
        hl = QLabel("사건수목 표제 후보 · ⑤ 보호수단에서 모음 · 순서·분기·성공기준은 PSA 담당이 정함")
        hl.setObjectName("muted")
        v.addWidget(hl)
        self.group_heading_table = _table((("표제", 56), ("이름(제안)", 150), ("구현 대상", 0), ("작동 방식", 90),
                                           ("작성", 70)), "그룹 표제 표", origin_col=4)
        v.addWidget(self.group_heading_table, 2)
        self.group_end_label = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=20)
        v.addWidget(self.group_end_label)
        split.addWidget(center)
        side = QFrame()
        side.setObjectName("panel")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(8, 6, 8, 6)
        t = QLabel("확정 조건")
        t.setObjectName("h2")
        sv.addWidget(t)
        self.problem_list = QListWidget()
        self.problem_list.setAccessibleName("확정하지 못하는 이유")
        self.problem_list.setWordWrap(True)
        self.problem_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.problem_list.setResizeMode(QListWidget.Adjust)
        sv.addWidget(self.problem_list, 2)
        t = QLabel("추적")
        t.setObjectName("h2")
        sv.addWidget(t)
        self.trace = QLabel("소속 후보를 고르면 편차 → 원인 → 위치·고장모드 → 판정 → 그룹 → 최종상태를 봅니다.")
        self.trace.setWordWrap(True)
        self.trace.setTextFormat(Qt.PlainText)
        self.trace.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sv.addWidget(self.trace, 3)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([760, 300])
        h.addWidget(split)
        return w, TABS[1]

    def _record_tab(self, kind, columns, title, origin_col, extra=()):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 0)
        specs = [("받아들이기", "AI 초안을 사람이 확인한 것으로 바꿉니다", lambda: self.accept_record(kind)),
                 ("고치기…", "고른 행을 고칩니다(사람이 쓴 것이 됨)", lambda: self.edit_record(kind)),
                 ("지우기", "고른 행을 지웁니다(ID는 기록으로 남고, 붙어 있던 그룹에서 떨어짐)",
                  lambda: self.remove_record(kind))] + list(extra)
        row, btns = self._buttons(*specs)
        v.addLayout(row)
        table = _table(columns, title + " 표", origin_col=origin_col)
        table.itemSelectionChanged.connect(self._update_buttons)
        v.addWidget(table, 1)
        setattr(self, kind + "_table", table)
        setattr(self, kind + "_btns", btns)
        return w

    def _headings_tab(self):
        w = self._record_tab("heading", (("표제", 56), ("이름(제안)", 150), ("출처 보호수단", 0), ("구현 대상", 150),
                                         ("역할", 50), ("작동 방식", 70), ("적용 그룹", 110), ("작성", 70)),
                             "사건수목 표제 후보", 7,
                             (("그룹에 표제 더하기…", "그룹 탭에서 보는 그룹에 사람이 쓴 표제를 더합니다",
                               lambda: self.add_heading()),))
        return w, TABS[2]

    def _end_states_tab(self):
        w = self._record_tab("end_state", (("ES", 56), ("비완화 결과(대표 문장)", 0), ("결과 범주", 110),
                                           ("관련 그룹", 120), ("출처 항목 수", 80), ("작성", 70)), "최종상태 후보", 5,
                             (("그룹에 최종상태 더하기…", "그룹 탭에서 보는 그룹에 사람이 쓴 최종상태를 더합니다",
                               lambda: self.add_end_state()),))
        return w, TABS[3]

    def _basic_events_tab(self):
        w = self._record_tab("basic_event", (("BE", 64), ("앱 제안 이름", 0), ("기기 태그", 110), ("계통", 60),
                                             ("고장모드", 70), ("관련 표제·후보", 150), ("출처", 120), ("작성", 70)),
                             "기본사건 후보", 7)
        return w, TABS[4]

    def _coverage_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 4, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 0, 0)
        note = QLabel("공백은 \"HAZOP이 이 범주의 후보를 내지 않았다\"는 뜻입니다. 사건이 없다는 뜻이 아니며, 앱이 초기사건을 "
                      "대신 만들지 않습니다. 공백마다 다른 기법(FMEA·운전경험·MLD) 확인이나 범위 밖 사유를 적으세요.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        v.addWidget(note)
        self.coverage_table = _table((("범주 코드", 80), ("범주 이름", 190), ("대응 그룹", 90), ("후보", 44),
                                      ("상태", 80), ("메모(사유)", 0)), "완전성 대조 표")
        self.coverage_table.itemSelectionChanged.connect(self._show_coverage)
        v.addWidget(self.coverage_table, 1)
        split.addWidget(left)
        side = QFrame()
        side.setObjectName("panel")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(8, 6, 8, 6)
        self.coverage_title = QLabel("공백 행을 고르면 처리와 사유를 적을 수 있습니다")
        self.coverage_title.setObjectName("h2")
        self.coverage_title.setWordWrap(True)
        sv.addWidget(self.coverage_title)
        self.coverage_why = plain_label("", name="muted")
        sv.addWidget(self.coverage_why)
        t = QLabel("검토자 판정")
        t.setObjectName("h2")
        sv.addWidget(t)
        self.coverage_group = QButtonGroup(self)
        self.coverage_radios = {}
        for key, label in model.COVERAGE.items():
            rb = QRadioButton(label)
            self.coverage_group.addButton(rb)
            self.coverage_radios[key] = rb
            sv.addWidget(rb)
        self.coverage_reason = QLineEdit()
        self.coverage_reason.setPlaceholderText("사유(필수)")
        self.coverage_reason.setAccessibleName("공백 사유")
        sv.addWidget(self.coverage_reason)
        row, (self.coverage_save, self.coverage_clear) = self._buttons(
            ("판정 저장", "고른 공백 행의 처리와 사유를 저장합니다", lambda: self.set_coverage()),
            ("판정 지우기", "고른 행의 사람 판정을 지웁니다", lambda: self.set_coverage(None, "")))
        sv.addLayout(row)
        sv.addStretch(1)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([760, 300])
        h.addWidget(split)
        return w, TABS[5]

    def _warnings_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 0)
        self.warning_summary = QLabel("")
        self.warning_summary.setWordWrap(True)
        self.warning_summary.setAccessibleName("품질 경고 요약")
        v.addWidget(self.warning_summary)
        self.warning_table = _table((("경고", 190), ("대상", 160), ("내용", 0), ("근거", 170)), "품질 경고 표")
        v.addWidget(self.warning_table, 1)
        return w, TABS[6]

    # ------------------------------------------------------------ 주 창이 부르는 것
    def where(self):
        return {"drawing": None, "region": "프로젝트 %s" % self.project_id, "run": None} if self.project_id else None

    def main_focus(self):
        return self.tabs.currentWidget() if self.stack.currentIndex() == 1 else None

    def is_done(self):
        """모든 그룹이 확정이고, 완전성 대조의 공백 행마다 사람 판정이 있으면 완료."""
        if not self.view or not self.view["groups"]:
            return False
        gaps = [r for r in self.view["completeness"] if r["status"] == "gap" and r["code"] not in self.doc["coverage"]]
        return all(g["status"] == "confirmed" for g in self.view["groups"]) and not gaps

    def commands(self):
        return [("그룹 만들기…", "G", lambda: self.create_group()), ("그룹으로 옮기기…", "M", lambda: self.move_selected()),
                ("그룹 나누기…", "S", lambda: self.split_group()), ("그룹 확정", "Ctrl+Enter", lambda: self.confirm_group()),
                ("그룹 확정 풀기", "", lambda: self.reopen_group()), ("규칙 초안 만들기", "Ctrl+R", lambda: self.suggest()),
                ("IE 인계 묶음 내보내기…", "", lambda: self.export_bundle()),
                ("완전성 대조 보기", "", lambda: self.tabs.setCurrentIndex(TAB_COVERAGE))]

    def keyPressEvent(self, e):  # noqa: N802
        if isinstance(self.focusWidget(), QLineEdit):
            return super().keyPressEvent(e)
        mods, key = e.modifiers(), e.key()
        acts = {(Qt.NoModifier, Qt.Key_G): self.create_group, (Qt.NoModifier, Qt.Key_M): self.move_selected,
                (Qt.NoModifier, Qt.Key_S): self.split_group, (Qt.ControlModifier, Qt.Key_Return): self.confirm_group,
                (Qt.ControlModifier, Qt.Key_Enter): self.confirm_group, (Qt.ControlModifier, Qt.Key_R): self.suggest}
        fn = acts.get((mods & ~Qt.KeypadModifier, key))
        if fn is None:
            return super().keyPressEvent(e)
        fn()

    def open_item(self, key):
        """탐색기 대상: ("group", IEG) · ("tab", 탭 번호)."""
        kind, value = key
        if kind == "group":
            self.tabs.setCurrentIndex(TAB_GROUP)
            self.show_group(value)
        elif kind == "tab":
            self.tabs.setCurrentIndex(value)

    def on_enter(self):
        names = [e["name"] for e in data.list_extractions()]
        name = getattr(self.app, "drawing", None) or (names[0] if names else None)
        self.load(name)

    # ------------------------------------------------------------ 읽기
    def load(self, name):
        """도면 name이 속한 프로젝트의 확정 구간·⑤ 결과(저장본)·⑥ 문서를 읽고 ⑤와 맞춘다. 맞춘 결과가 다르면 저장한다."""
        self.name, self.unreadable = name, None
        self.pg = self.node_set = self.results = self.doc = self.fp = self.view = None
        self.banner.set_messages(None)
        self.replace_btn.hide()
        idx = related.DrawingIndex(name) if name else None
        self.project_id = idx.graph.get("project_id") if idx and idx.graph else None
        if idx is None or idx.graph is None:
            return self._empty("도면을 추출하고 ④에서 검토구간을 확정한 뒤, ⑤에서 원인을 승인하면 여기서 초기사건 그룹을 묶습니다.")
        if idx.results is None:
            return self._empty("확정된 검토구간의 ⑤ 분석 결과가 없습니다. ⑤에서 항목을 승인하면 승인한 원인이 초기사건 후보로 "
                               "들어옵니다.")
        self.pg, self.node_set, self.results = idx.graph, idx.node_set, idx.results
        path = res.store_path(self.node_set.get("project_id"), self.node_set["graph_id"])
        self.results_at = (datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                           if os.path.isfile(path) else None)
        try:
            doc, self.fp = store.load(self.project_id)
        except store.Unreadable as exc:
            self.unreadable = exc
            self.banner.set_messages("초기사건 저장 파일을 읽을 수 없어 고치지 않고 멈췄습니다", [str(exc)])
            self.replace_btn.show()
            return self._empty("저장 파일을 읽지 못했습니다. 파일을 직접 고치거나, 원본을 백업하고 빈 문서로 새로 시작하세요"
                               "(그룹·표제를 다시 묶어야 하고, 원인마다 IEC 번호를 새로 받습니다).")
        except OSError as exc:
            return self._empty("초기사건 저장 파일을 읽지 못함: %s" % exc)
        synced = model.sync(doc, self.results)
        if synced is not doc and not self._save(synced):
            return
        self.doc = synced
        self.render()
        self.stack.setCurrentIndex(1)
        self.app.update_header()
        return True

    def _empty(self, text):
        self.empty.setText(text)
        self.stack.setCurrentIndex(0)
        self.kpi.setText("")
        self.scope_chip.set_state("")
        self.basis.setText("")
        self._update_buttons()
        self.app.update_header()
        return False

    def replace_unreadable(self, ask=True):
        """읽지 못한 파일을 백업하고 빈 문서로 새로 시작한다. 백업이 실패하면 쓰지 않는다."""
        if self.unreadable is None:
            return False
        if ask and QMessageBox.question(
                self, "초기사건 저장 파일", "읽지 못한 파일을 data/backup 아래에 복사한 뒤 빈 문서로 바꿉니다.\n"
                "그룹·표제는 다시 묶어야 합니다. 번호는 원본에 있던 가장 큰 번호 다음부터 매기므로 옛 ID를 다시 쓰지 않지만, "
                "원인마다 받았던 IEC 번호는 이어지지 않습니다. 계속할까요?\n%s" % self.unreadable.path) != QMessageBox.Yes:
            return False
        try:
            _doc, _fp, saved = store.replace_unreadable(self.project_id)
        except (OSError, ValueError, store.Conflict) as exc:
            self.app.status_message("백업하지 못해 바꾸지 않았습니다: %s" % exc)
            return False
        self.app.toast("원본을 백업했습니다: %s. 원인마다 IEC 번호를 새로 받았습니다(옛 번호는 다시 쓰지 않음)." % saved,
                       ms=8000)
        return self.load(self.name)

    def _reload_if_results_changed(self, then):
        """⑤ 결과 저장본을 다시 읽어 ⑥이 본 것과 다르면 ⑥을 처음부터 다시 읽고(⑤와 맞추고 저장) 상태줄에 알린다.
        분할 화면에서 ⑤를 고쳐 저장한 뒤 ⑥에서 바로 내보내거나 확정할 때 옛 ⑤ 결과를 쓰지 않게 한다. 다시 읽었으면 True."""
        try:
            fresh = res.load(self.node_set)
        except (OSError, ValueError):
            fresh = None
        if fresh == self.results:
            return False
        self.load(self.name)
        self.app.status_message("⑤ 결과 저장본이 바뀌어 ⑥을 다시 읽었습니다. " + then)
        return True

    # ------------------------------------------------------------ 저장(모든 편집이 지나는 길)
    def _save(self, new_doc):
        try:
            self.fp = store.save(new_doc, expect=self.fp)
        except store.Conflict:
            self.app.status_message("초기사건 파일이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽습니다.")
            self.load(self.name)
            return False
        except (OSError, ValueError) as exc:
            self.app.log_error("초기사건 저장 실패", exc)
            self.app.status_message("초기사건 파일을 저장하지 못함: %s" % exc)
            return False
        self.doc = new_doc
        self.app.mark_saved(nodes.now_utc())
        return True

    def _apply(self, fn):
        """fn(doc) → 새 문서(또는 (새 문서, 값)). 규칙에 막히면(ValueError) 상태줄에 이유만 띄우고 저장하지 않는다."""
        if self.doc is None:
            self.app.status_message("열린 초기사건 문서가 없습니다.")
            return None
        try:
            out = fn(self.doc)
        except ValueError as exc:
            self.app.status_message(str(exc))
            return None
        new, value = out if isinstance(out, tuple) else (out, True)
        if new is not self.doc and not self._save(new):
            return None
        self.render()
        return value

    # ------------------------------------------------------------ 그리기
    def render(self):
        self.view = ib.build_bundle(self.results, self.node_set, self.pg, self.doc, nodes.now_utc())
        v = self.view
        cands = v["candidates"]
        judged = lambda j: sum(c["judgement"] == j for c in cands)  # noqa: E731
        gaps = sum(r["status"] == "gap" for r in v["completeness"])
        open_gaps = sum(r["status"] == "gap" and r["code"] not in self.doc["coverage"] for r in v["completeness"])
        self.kpi.setText("승인된 원인 %d · IE 후보 %d · 제외(사유 기록) %d · 보류 %d · 그룹 %d · 대조 공백 범주 %d"
                         "(처리 대기 %d)" % (len(cands), judged("yes"), judged("no"), judged("undecided"),
                                             len(v["groups"]), gaps, open_gaps))
        counts = (len(cands), len(v["groups"]), len(v["top_events"]), len(v["end_states"]), len(v["basic_events"]),
                  None, len(v["warnings"]))
        for i, n in enumerate(counts):
            self.tabs.setTabText(i, TABS[i] + ("" if n is None else " %d" % n))
        by_iec = {c["candidate_id"]: c for c in cands}
        _fill(self.cand_table, [[c["candidate_id"], res.IE_CANDIDATES[c["judgement"]], c["cause"],
                                 "%s · %s" % (c["node_id"], c["deviation_label"]),
                                 res.ie_category_label(c["category"]), c["group_id"] or "미배정",
                                 self._placed_text(c["candidate_id"]), ix.ORIGINS.get(c["ie_origin"], "판정 전")]
                                for c in cands],
              ids=[c["candidate_id"] for c in cands], origins=[c["ie_origin"] or "ai_draft" for c in cands])
        self.by_iec = by_iec
        self._fill_records()
        cov = v["completeness"]
        _fill(self.coverage_table, [[r["code"] or res.UNCLASSIFIED_LABEL, r["name_ko"], r["group_id"] or "—",
                                     r["candidate_count"], ix.COVERAGE[r["status"]], r["note"]] for r in cov],
              ids=[r["code"] for r in cov])
        for row, r in enumerate(cov):
            if r["status"] == "gap" and r["code"] not in self.doc["coverage"]:
                for c in range(self.coverage_table.columnCount()):
                    self.coverage_table.item(row, c).setBackground(QColor(tokens.c("warn-bg")))
        self.warning_summary.setText(ib.warning_summary_text(v))
        _fill(self.warning_table, [[ib.WARNING_KINDS[w["kind"]][0], w["target"], w["text"], w["basis"]]
                                   for w in v["warnings"]])
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for g in v["groups"]:
            self.group_combo.addItem("%s %s · %s" % (g["group_id"], g["name"], model.GROUP_STATUSES[g["status"]]),
                                     g["group_id"])
        self.group_combo.blockSignals(False)
        live = [g["group_id"] for g in v["groups"]]
        self.show_group(self.group_id if self.group_id in live else (live[0] if live else None))
        ok = sum(not g["problems"] for g in v["groups"])
        self.scope_chip.set_state(SCOPE_CHIP % (ok, len(v["groups"])),
                                  "passed" if v["groups"] and ok == len(v["groups"]) else "warn")
        self.basis.setText("⑤ 결과 기준: %s 저장본 · 프로젝트 %s" % (
            kst_text(self.results_at)[5:16] if self.results_at else "저장 전", self.project_id))
        self._show_coverage()
        self._update_buttons()

    def _placed_text(self, iec):
        c = self.doc["candidates"][iec]
        return {"human": "사람", "ai_draft": "AI 초안"}.get(c["placed_by"], "—")

    def _fill_records(self):
        v = self.view
        hs = v["top_events"]
        _fill(self.heading_table, [[h["heading_id"], h["name"], " / ".join(h["sources"]), _joined(h["targets"]),
                                    refs.ROLES[h["role"]], refs.ACTUATIONS[h["actuation"]], _joined(h["group_ids"]),
                                    ix.ORIGINS[h["origin"]]] for h in hs],
              ids=[h["heading_id"] for h in hs], origins=[h["origin"] for h in hs])
        es = v["end_states"]
        _fill(self.end_state_table, [[e["end_state_id"], e["text"], model.ES_CATEGORIES[e["category"]],
                                      _joined(e["group_ids"]), e["source_count"], ix.ORIGINS[e["origin"]]] for e in es],
              ids=[e["end_state_id"] for e in es], origins=[e["origin"] for e in es])
        bs = v["basic_events"]
        _fill(self.basic_event_table, [[b["be_id"], b["name"], b["tag"], b["system"], b["failure_mode"] or "코드 미정",
                                        _joined(b["candidate_ids"] + b["heading_ids"]),
                                        "·".join(model.SOURCE_KINDS[k] for k in b["source_kinds"]),
                                        ix.ORIGINS[b["origin"]]] for b in bs],
              ids=[b["be_id"] for b in bs], origins=[b["origin"] for b in bs])

    def current_group(self):
        return next((g for g in (self.view or {}).get("groups", []) if g["group_id"] == self.group_id), None)

    def show_group(self, gid):
        self.group_id = gid
        i = self.group_combo.findData(gid)
        if i >= 0 and self.group_combo.currentIndex() != i:
            self.group_combo.blockSignals(True)
            self.group_combo.setCurrentIndex(i)
            self.group_combo.blockSignals(False)
        g = self.current_group()
        self.problem_list.clear()
        if g is None:
            self.group_chip.set_state("그룹 없음 · 후보 탭에서 만들거나 규칙 초안을 만드세요", "")
            for lab in self.group_fields.values():
                lab.setText("")
            _fill(self.member_table, [])
            _fill(self.group_heading_table, [])
            self.members_label.setText("")
            self.group_end_label.setText("")
            self._update_buttons()
            return
        st = g["status"]
        self.group_chip.set_state("확정 · 검토자 %s" % g["confirmed_by"] if st == "confirmed"
                                  else "%s%s" % (model.GROUP_STATUSES[st], " · AI 초안 포함" if g["origin"] == "ai_draft"
                                                 else ""), GROUP_CHIP.get(st, ""))
        self.group_box.setObjectName("human_box" if g["origin"] == "human" else "ai_box")
        self.group_box.style().unpolish(self.group_box)
        self.group_box.style().polish(self.group_box)
        cats = ", ".join(res.ie_category_label(c) for c in g["categories"]) or "미정"
        rep = g["representative"]
        rep_text = "%s %s" % (rep, self.by_iec[rep]["cause"]) if rep in self.by_iec else (rep or "미정")
        source = " · 출처 " + g["category_source"] if g["category_source"] else ""
        reason = " · " + g["representative_reason"] if g["representative_reason"] else ""
        for key, text in (("definition", g["definition"] or "미정"), ("categories", cats + source),
                          ("representative", rep_text + reason),
                          ("plant_response", g["plant_response"] or "미정"),
                          ("affected_mitigation", g["affected_mitigation"] or "미정"),
                          ("support_ie", model.SUPPORT_IE[g["support_ie"]])):
            self.group_fields[key].setText(text)
        everyone = g["members"] + g["held_members"]
        rows, origins = [], []
        for m in everyone:
            c = self.by_iec.get(m)
            if c is None:
                rows.append([m, "(⑤ 승인 해제 · 묶음에 나가지 않음)", "", "", "승인 해제", self._placed_text(m)])
            else:
                rows.append([m, c["cause"], "%s · %s" % (c["node_id"], c["deviation_label"]),
                             _joined(c["cause_location"]), "승인", self._placed_text(m)])
            origins.append(self.doc["candidates"][m]["placed_by"])
        _fill(self.member_table, rows, ids=everyone, origins=origins)
        self.members_label.setText("소속 후보 %d · 원인 단위 · ⑤ 승인 항목에서 옴%s" % (
            g["member_count"], " · 승인 해제로 빠진 후보 %d(묶음에 나가지 않음)" % len(g["held_members"])
            if g["held_members"] else ""))
        hs = [h for h in self.view["top_events"] if h["heading_id"] in g["heading_ids"]]
        _fill(self.group_heading_table, [[h["heading_id"], h["name"], _joined(h["targets"]),
                                          refs.ACTUATIONS[h["actuation"]], ix.ORIGINS[h["origin"]]] for h in hs],
              ids=[h["heading_id"] for h in hs], origins=[h["origin"] for h in hs])
        es = [e for e in self.view["end_states"] if e["end_state_id"] in g["end_state_ids"]]
        self.group_end_label.setText("최종상태 후보: %s. 성공 경로의 최종상태(안전 정지 등)는 PSA 담당이 정합니다." % (
            "; ".join("%s %s(%s)" % (e["end_state_id"], e["text"], ix.ORIGINS[e["origin"]]) for e in es) or "없음"))
        ok = ("검토자 %s가 확정했습니다. 그룹이나 소속 후보의 ⑤ 항목이 바뀌면 다시 초안이 됩니다." % g["confirmed_by"]
              if st == "confirmed" else "확정 조건을 모두 갖췄습니다. 검토자 이름으로 확정할 수 있습니다.")
        for p in g["problems"] or [ok]:
            self.problem_list.addItem(QListWidgetItem(p))
        self._show_trace()
        self._update_buttons()

    def _show_trace(self):
        ids = _selected_ids(self.member_table)
        c = self.by_iec.get(ids[0]) if ids and getattr(self, "by_iec", None) else None
        if c is None:
            self.trace.setText("소속 후보를 고르면 편차 → 원인 → 위치·고장모드 → 판정 → 그룹 → 최종상태를 봅니다.")
            return
        t = next((t for t in self.view["trace"] if t["candidate_id"] == c["candidate_id"]), {})
        self.trace.setText("\n".join((
            "편차: %s · %s" % (c["node_id"], c["deviation_label"]),
            "원인(⑤ 승인): %s  [%s]" % (c["cause"], c["entry_id"]),
            "원인 위치 · 고장모드: %s · %s" % (_joined(c["cause_location"]) or "미정", _joined(c["failure_modes"]) or "미정"),
            "IE 판정: %s · 교란 %s · 도전 %s (%s)" % (res.IE_CANDIDATES[c["judgement"]], ix.ANSWERS[c["disturbs"]],
                                                ix.ANSWERS[c["challenges"]], ix.ORIGINS.get(c["ie_origin"], "판정 전")),
            "초기사건 그룹: %s" % (c["group_id"] or "미배정"),
            "최종상태 후보: %s" % (_joined(t.get("end_state_ids")) or "없음"),
            "근거 경로: %s" % ("; ".join(t.get("kg_paths") or []) or "없음"))))

    def _coverage_row(self):
        rows = sorted({i.row() for i in self.coverage_table.selectedItems()})
        if not rows or not self.view:
            return None
        return self.view["completeness"][rows[0]]

    def _show_coverage(self):
        r = self._coverage_row()
        gap = bool(r and r["code"] and r["status"] != "covered")
        self.coverage_title.setText("공백 · %s %s" % (r["code"], r["name_ko"]) if gap else
                                    "공백 행을 고르면 처리와 사유를 적을 수 있습니다")
        done = self.doc["coverage"].get(r["code"]) if gap and self.doc else None
        self.coverage_group.setExclusive(False)
        for k, rb in self.coverage_radios.items():
            rb.setChecked(bool(done) and done["disposition"] == k)
            rb.setEnabled(gap)
        self.coverage_group.setExclusive(True)
        self.coverage_reason.setText(done["reason"] if done else "")
        self.coverage_reason.setCursorPosition(0)
        self.coverage_why.setText("대응하는 후보 %d · 대응 그룹 %s%s" % (
            r["candidate_count"], r["group_id"] or "없음", " · " + r["note"] if r["note"] else "") if gap else "")
        self.coverage_reason.setEnabled(gap)
        self.coverage_save.setEnabled(gap)
        self.coverage_clear.setEnabled(bool(done))

    def _update_buttons(self):
        ready = self.doc is not None
        sel = bool(ready and _selected_ids(self.cand_table))
        for b in (self.create_btn, self.move_btn, self.unassign_btn, self.accept_member_btn):
            b.setEnabled(sel)
        self.create_btn.setEnabled(ready)
        g = self.current_group() if ready else None
        self.confirm_btn.setEnabled(bool(g) and not g["problems"] and g["status"] != "confirmed")
        self.confirm_btn.setToolTip("확정 조건이 모두 맞을 때만 켜집니다" if not g or g["problems"] else
                                    "검토자 이름으로 그룹을 확정합니다")
        stored = (self.doc["groups"].get(g["group_id"], {}).get("status") if g else None)
        self.reopen_btn.setEnabled(stored == "confirmed")
        self.delete_btn.setEnabled(stored == "draft")
        self.edit_group_btn.setEnabled(bool(g))
        self.split_btn.setEnabled(bool(g) and len(g["members"]) + len(g["held_members"]) >= 2)
        for kind in KIND_TABLES:
            has = ready and bool(_selected_ids(getattr(self, kind + "_table")))
            for b in getattr(self, kind + "_btns")[:3]:
                b.setEnabled(has)
            for b in getattr(self, kind + "_btns")[3:]:
                b.setEnabled(bool(g))
        self.suggest_btn.setEnabled(ready)
        self.export_btn.setEnabled(ready)

    # ------------------------------------------------------------ 편집(모두 model 함수 하나 + 저장)
    def selected_candidates(self):
        return _selected_ids(self.cand_table)

    def create_group(self, name=None, iecs=None):
        iecs = self.selected_candidates() if iecs is None else iecs
        if name is None:
            name, ok = QInputDialog.getText(self, "그룹 만들기", "그룹 이름(예: 주급수 상실)")
            if not ok:
                return None
        gid = self._apply(lambda d: model.create_group(d, name, iecs))
        if gid:
            self.show_group(gid)
            self.app.toast("%s 그룹을 만들었습니다(초안)" % gid)
        return gid

    def _pick_group(self, title):
        groups = (self.view or {}).get("groups", [])
        if not groups:
            self.app.status_message("옮길 그룹이 없습니다. 먼저 그룹을 만드세요.")
            return False, None
        labels = ["%s %s" % (g["group_id"], g["name"]) for g in groups]
        text, ok = QInputDialog.getItem(self, title, "그룹", labels, 0, False)
        return ok, groups[labels.index(text)]["group_id"] if ok else None

    def move_selected(self, gid="ask", iecs=None):
        """고른 후보를 gid로 옮긴다(None이면 그룹에서 뺌). gid를 주지 않으면 고르게 묻는다."""
        iecs = self.selected_candidates() if iecs is None else iecs
        if not iecs:
            self.app.status_message("옮길 후보를 고르세요.")
            return False
        if gid == "ask":
            ok, gid = self._pick_group("그룹으로 옮기기")
            if not ok:
                return False

        def apply(d):
            for i in iecs:
                d = model.place(d, i, gid)
            return d
        return bool(self._apply(apply))

    def accept_members(self, iecs=None):
        iecs = self.selected_candidates() if iecs is None else iecs

        def apply(d):
            for i in iecs:
                d = model.accept(d, ("member", i))
            return d
        return bool(self._apply(apply))

    def edit_group(self, fields=None):
        g = self.current_group()
        if g is None:
            return False
        if fields is None:
            dlg = FieldsDialog("%s 고치기" % g["group_id"], "group", self.doc["groups"][g["group_id"]], self)
            if dlg.exec() != QDialog.Accepted:
                return False
            fields = dlg.fields()
        return bool(self._apply(lambda d: model.edit(d, ("group", g["group_id"]), fields)))

    def confirm_group(self, reviewer=None):
        g = self.current_group()
        if g is None:
            return False
        if self._reload_if_results_changed("바뀐 내용을 확인한 뒤 다시 확정하세요."):
            return False
        reviewer = reviewer if reviewer is not None else self.app.reviewer_name()
        if not reviewer:
            reviewer, ok = QInputDialog.getText(self, "검토자 이름", "확정하려면 검토자 이름이 필요합니다(설정에 저장).")
            if not ok or not reviewer.strip():
                return False
            self.app.set_reviewer_name(reviewer.strip())
        done = self._apply(lambda d: model.confirm(d, g["group_id"], self.results, reviewer))
        if done:
            self.app.toast("%s 그룹을 확정했습니다 · 검토자 %s" % (g["group_id"], reviewer.strip()))
            getattr(self.app, "refresh_stages", lambda: None)()
        return bool(done)

    def reopen_group(self):
        g = self.current_group()
        return bool(g and self._apply(lambda d: model.reopen(d, g["group_id"])))

    def delete_group(self, ask=True):
        g = self.current_group()
        if g is None:
            return False
        if ask and QMessageBox.question(self, "그룹 지우기", "%s 그룹(%s)을 지울까요? 소속 후보는 미배정이 되고, ID는 '삭제' 기록으로 "
                                        "남아 다시 쓰지 않습니다." % (g["group_id"], g["name"])) != QMessageBox.Yes:
            return False
        return bool(self._apply(lambda d: model.delete_group(d, g["group_id"])))

    def split_group(self, moved=None):
        g = self.current_group()
        if g is None:
            return None
        if moved is None:
            moved = _selected_ids(self.member_table)
            if not moved:
                self.app.status_message("그룹 탭의 소속 후보 표에서 새 그룹으로 옮길 후보를 고른 뒤 나누세요.")
                return None
        pair = self._apply(lambda d: model.split(d, g["group_id"], moved))
        if pair:
            self.show_group(pair[1])
            self.app.toast("%s 그룹을 %s · %s 그룹으로 나눴습니다(옛 ID는 '나뉨' 기록)" % (g["group_id"], pair[0], pair[1]))
        return pair

    def suggest(self):
        before = self.doc
        if self._apply(lambda d: model.suggest(d, self.results, self.pg)) and self.doc is not before:
            self.app.toast("규칙 초안을 만들었습니다. 빗금은 사람이 확인하기 전의 초안입니다.")
            return True
        if self.doc is before:
            self.app.status_message("규칙으로 새로 묶을 후보가 없습니다(판정이 '후보'이고 범주가 있는 미배정 후보만 묶음).")
        return False

    def _selected_record(self, kind):
        ids = _selected_ids(getattr(self, kind + "_table"))
        return ids[0] if ids else None

    def accept_record(self, kind, rid=None):
        rid = rid or self._selected_record(kind)
        return bool(rid and self._apply(lambda d: model.accept(d, (kind, rid))))

    def edit_record(self, kind, rid=None, fields=None):
        rid = rid or self._selected_record(kind)
        if not rid:
            return False
        if fields is None:
            dlg = FieldsDialog("%s 고치기" % rid, kind, self.doc[model.COLLECTIONS[kind][0]][rid], self)
            if dlg.exec() != QDialog.Accepted:
                return False
            fields = dlg.fields()
        return bool(self._apply(lambda d: model.edit(d, (kind, rid), fields)))

    def remove_record(self, kind, rid=None):
        rid = rid or self._selected_record(kind)
        return bool(rid and self._apply(lambda d: model.remove(d, (kind, rid))))

    def _add_record(self, kind, fields, add):
        g = self.current_group()
        if g is None:
            self.app.status_message("그룹 탭에서 붙일 그룹을 먼저 고르세요.")
            return None
        if fields is None:
            dlg = FieldsDialog("%s에 더하기" % g["group_id"], kind, {}, self)
            if dlg.exec() != QDialog.Accepted:
                return None
            fields = dlg.fields()
        return self._apply(lambda d: add(d, g["group_id"], fields))

    def add_heading(self, fields=None):
        return self._add_record("heading", fields, model.add_heading)

    def add_end_state(self, fields=None):
        return self._add_record("end_state", fields, model.add_end_state)

    def set_coverage(self, disposition="form", reason=None, code=None):
        r = self._coverage_row() if code is None else next(x for x in self.view["completeness"] if x["code"] == code)
        if r is None or not r["code"]:
            return False
        if disposition == "form":
            disposition = next((k for k, rb in self.coverage_radios.items() if rb.isChecked()), None)
            if disposition is None:
                self.app.status_message("처리(범위 밖 · 다른 기법 · 해당 없음)를 고르세요.")
                return False
        reason = self.coverage_reason.text() if reason is None else reason
        return bool(self._apply(lambda d: model.set_coverage(d, r["code"], disposition, reason,
                                                             self.app.reviewer_name() or "")))

    # ------------------------------------------------------------ 내보내기
    def export_bundle(self, path=None):
        """IE 인계 묶음(승인 항목만, Excel + 같은 이름의 JSON). ⑥만 IEC 대응표를 쓰므로 내보내기도 여기서만 한다.
        path를 주면 대화상자 없이(검사용). 저장한 .xlsx 경로 또는 None."""
        if self.view is None:
            self.app.status_message("내보낼 초기사건 자료가 없습니다. ⑤에서 항목을 승인하세요.")
            return None
        if self._reload_if_results_changed("다시 읽은 내용으로 내보냅니다.") and self.doc is None:
            return None
        now = nodes.now_utc()
        b = ib.build_bundle(self.results, self.node_set, self.pg, self.doc, now)
        if not b["candidates"]:
            self.app.status_message("승인한 항목이 없어 IE 인계 묶음을 만들지 않았습니다. 항목을 승인한 뒤 다시 내보내세요.")
            return None
        if path is None:
            folder = getattr(self, "_export_dir", None) or QStandardPaths.writableLocation(
                QStandardPaths.DocumentsLocation)
            path, _ = QFileDialog.getSaveFileName(self, "IE 인계 묶음 내보내기", os.path.join(
                folder, ix.default_stem(self.project_id, now) + ".xlsx"), "Excel 통합 문서 (*.xlsx)")
            if not path:
                return None
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            json_path = os.path.splitext(path)[0] + ".json"
            if os.path.exists(json_path) and QMessageBox.question(
                    self, "IE 인계 묶음 내보내기", "같은 이름의 JSON 파일이 이미 있습니다. 덮어쓸까요?\n%s" % json_path
            ) != QMessageBox.Yes:
                return None
        try:
            path, json_path = ix.export(path, b)
        except (OSError, ValueError) as exc:
            self.app.log_error("IE 인계 묶음 내보내기 실패", exc)
            QMessageBox.warning(self, "IE 인계 묶음 내보내기", "저장하지 못했습니다(파일이 열려 있으면 닫고 다시 하세요).\n%s"
                                % exc)
            return None
        self._export_dir = os.path.dirname(path)
        self.app.toast("IE 인계 묶음 내보냄: %s · 후보 %d건 · 그룹 %d건 · JSON 원본 %s" % (
            os.path.basename(path), len(b["candidates"]), len(b["groups"]), os.path.basename(json_path)), ms=10000,
            actions=(("열기", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path))),
                     ("폴더 열기", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))))))
        return path
