"""④ 검토구간(HAZOP study node) 화면 (stage3-spec §A·§B, 디자인/시안/완성본/B-고밀도작업대/4-검토구간).

프로젝트 그래프(모든 도면을 이은 것, hazop.app.project_ctx)에서 구간 집합(hazop.study.nodes)을 제안·편집·확정한다.
도면 고르기는 어느 도면을 *볼지*만 정한다. 구간 ID S1…Sn은 프로젝트 전체에서 하나다(사용자 결정 2026-11-07).
화면 상태의 기준은 self.node_set(저장하는 원본) 하나이고, 표기·경계·칩은 다시 그릴 때마다 ctx.view로 만든 사본(self.view)에서 읽는다.
편집은 모두 nodes의 순수 함수로 새 집합을 만든 뒤 저장하고 다시 그린다. 처음 제안은 사용자가 편집하거나 확정할 때 저장된다.
도면 위 구간 색은 seg1..seg5를 순환하고, 목록의 S 번호 배지에도 같은 색을 써서 색만으로 구분하지 않는다.
"""

import html
import os

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QStackedWidget,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTabWidget, QVBoxLayout, QWidget)

from hazop.app import data, project_ctx, tokens
from hazop.app.widgets import Banner, Chip, empty_label, kst_text
from hazop.graph import project
from hazop.study import migrate, nodes, remap, span

SEG_COUNT = 5
PANEL_MIN_W, PANEL_MAX_W = 264, 340     # 셸 오른쪽 열 clamp(264px, 20vw, 340px)
ROW_H = 24
MIN_ROWS = 4                            # 패널 높이가 모자랄 때도 구간 목록에 남기는 행 수
COUNT_ROLE = Qt.UserRole + 1
SCOPES = ("이 도면 구간", "프로젝트 전체")


def panel_width(window_width):
    return max(PANEL_MIN_W, min(PANEL_MAX_W, int(window_width * 0.2)))


def seg_token(index):
    return "seg%d" % (index % SEG_COUNT + 1)


def seg_icon(index, text):
    """구간 번호 배지(색 + S 번호 글자). 목록·행렬 머리에 쓴다."""
    pm = QPixmap(30, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(tokens.c(seg_token(index))))
    p.drawRoundedRect(QRectF(0, 0, 30, 16), 3, 3)
    p.setPen(QColor(tokens.c("on-seg")))
    f = QFont(tokens.FONT_FAMILY)
    f.setPixelSize(tokens.FONT_SIZE["xs"])
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, 30, 16), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


def entity_label(node):
    if node is None:
        return "?"
    first = (node.get("label_text") or "").split("\n")[0].strip()
    return node.get("tag") or first or node.get("kind") or node["entity_id"]


def section(text):
    lab = QLabel(text)
    lab.setObjectName("section")
    return lab


def hint(text):
    """빈 목록 대신 보이는 흐린 안내 한 줄(U-09)."""
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


def tab_page(lst, empty_hint, button=None, top=None):
    page = QWidget()
    v = QVBoxLayout(page)
    v.setContentsMargins(0, 4, 0, 0)
    v.setSpacing(4)
    if top is not None:
        v.addWidget(top)
    v.addWidget(lst, 1)
    v.addWidget(empty_hint)
    v.addStretch(0)
    if button is not None:
        v.addWidget(button)
    return page


def show_list_or_hint(lst, empty_hint):
    lst.setVisible(lst.count() > 0)
    empty_hint.setVisible(lst.count() == 0)


class _SegList(QListWidget):
    """구간 목록: 행 수만큼만 높이를 원하고(전부 보이게), 패널이 좁으면 MIN_ROWS까지 줄어든다."""

    def __init__(self):
        super().__init__()
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # 긴 이름은 행 안에서 말줄임
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _rows_h(self, rows):
        return rows * ROW_H + 2 * self.frameWidth()

    def sizeHint(self):  # noqa: N802
        return QSize(super().sizeHint().width(), self._rows_h(max(self.count(), 1)))

    def minimumSizeHint(self):  # noqa: N802
        return QSize(super().minimumSizeHint().width(), self._rows_h(min(max(self.count(), 1), MIN_ROWS)))


class _SegRowDelegate(QStyledItemDelegate):
    """24px 행: 체크 + 색 배지 + 이름(말줄임) + 오른쪽 "N개"(흐린 글자)."""

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(super().sizeHint(option, index).width(), ROW_H)

    def paint(self, painter, option, index):
        o = QStyleOptionViewItem(option)
        self.initStyleOption(o, index)
        widget = o.widget
        style = widget.style()
        count = index.data(COUNT_ROLE) or ""
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, o, widget)
        room = rect.width() - o.fontMetrics.horizontalAdvance(count) - 10
        o.text = o.fontMetrics.elidedText(o.text, Qt.ElideMiddle, max(room, 0))  # 끝의 도면 범위 [101 → 102] ⇄를 남긴다
        style.drawControl(QStyle.CE_ItemViewItem, o, painter, widget)
        painter.save()
        painter.setPen(QColor(tokens.c("muted")))
        painter.drawText(rect.adjusted(0, 0, -4, 0), Qt.AlignRight | Qt.AlignVCenter, count)
        painter.restore()


class StudyNodesScreen(QWidget):
    title = "④ 검토구간"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.name = None        # 추출 폴더 이름(보는 도면)
        self.ctx = None         # project_ctx.ProjectContext
        self.graph = None       # 구간 연산의 기준 = 프로젝트 그래프(ctx.pg)
        self.node_set = None
        self.view = None        # node_set의 표기 사본(ctx.view)
        self.saved = False      # node_set이 저장본과 같은가(처음 제안은 False)
        self.disk_fp = None     # 읽을 때 저장 파일의 nodes.fingerprint. 저장 직전 다르면 다른 창이 먼저 저장한 것
        self.unreadable = False  # 저장 파일을 읽지 못했음. 처음 덮어쓰기 전에 묻고 원본을 백업한다
        self.entities = {}      # 프로젝트 ID → 프로젝트 그래프 node
        self.local_map = {}     # 프로젝트 ID → 보는 도면의 data-local-id
        self.entity_of_local = {}
        self.picked_entity = None  # 도면에서 누른 구성요소
        self.notice = None      # 옛 도면별 저장본을 옮겼다는 알림(이번 실행 동안 띠로 보임)
        self._pending = None    # 도면을 바꾼 뒤 고를 구간(칩으로 건너갈 때)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("도면"))
        self.combo = QComboBox()
        self.combo.setAccessibleName("보는 도면")
        self.combo.setMinimumWidth(200)
        self.combo.currentIndexChanged.connect(self._load)
        bar.addWidget(self.combo)
        self.chip_status = Chip(elide=Qt.ElideRight, min_chars=8)  # 긴 확정 정보가 도구줄 최소 폭을 늘리지 않게
        bar.addWidget(self.chip_status)
        bar.addStretch(1)
        self.repropose_btn = QPushButton("다시 제안…")
        self.repropose_btn.setObjectName("danger")
        self.repropose_btn.setToolTip("지금 구간 집합을 버리고 그래프로 새로 제안합니다. 편집한 내용이 있으면 먼저 묻습니다.")
        self.repropose_btn.clicked.connect(lambda: self.repropose())
        self.reopen_btn = QPushButton("확정 해제")
        self.reopen_btn.clicked.connect(self.reopen)
        self.confirm_btn = QPushButton("구간 확정  Ctrl+Enter")
        self.confirm_btn.setObjectName("primary")
        self.confirm_btn.clicked.connect(lambda: self.confirm())
        for b in (self.repropose_btn, self.reopen_btn, self.confirm_btn):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.stale = Banner("warn")
        self.warn = Banner("warn")
        self.notice_bar = Banner("warn")
        lay.addWidget(self.notice_bar)
        lay.addWidget(self.stale)
        lay.addWidget(self.warn)

        self.stack = QStackedWidget()
        self.empty = empty_label("추출 결과가 없습니다. ② 도면 추출과 그래프를 만든 뒤 여기서 검토구간을 제안·확정합니다.")
        self.stack.addWidget(self.empty)
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        self.canvas_host = QWidget()
        QVBoxLayout(self.canvas_host).setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.canvas_host, 1)
        bl.addWidget(self._panel())
        self.stack.addWidget(body)
        lay.addWidget(self.stack, 1)
        self._shortcuts()
        self.main_focus = self.node_list

    # ------------------------------------------------------------ 오른쪽 패널
    def _panel(self):
        """구간 목록(전부 보임) + 고른 구간의 하위 탭(구성요소·미포함·속한 구간) (U-18)."""
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        self.panel.setFixedWidth(PANEL_MAX_W)
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
        head = QHBoxLayout()
        self.list_head = section("검토구간")
        head.addWidget(self.list_head, 1)
        self.overview_btn = QPushButton("전체 보기 Esc")
        self.overview_btn.setToolTip("구간 선택을 풀고 모든 구간 색을 다시 보여 줍니다 (Esc)")
        self.overview_btn.clicked.connect(self.show_overview)
        head.addWidget(self.overview_btn)
        v.addLayout(head)
        self.kpi = QLabel()
        self.kpi.setWordWrap(True)
        v.addWidget(self.kpi)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        v.addWidget(self.progress)
        self.gate = QLabel()
        self.gate.setObjectName("muted")
        self.gate.setWordWrap(True)
        v.addWidget(self.gate)
        self.scope = QComboBox()
        self.scope.addItems(SCOPES)
        self.scope.setAccessibleName("구간 목록 범위")
        self.scope.setToolTip("이 도면을 지나는 구간(걸친 구간 포함)만 볼지, 프로젝트의 모든 구간을 볼지 고릅니다")
        self.scope.currentIndexChanged.connect(lambda _i: self._render())
        v.addWidget(self.scope)

        self.node_list = _SegList()
        self.node_list.setIconSize(QSize(30, 16))
        self.node_list.setItemDelegate(_SegRowDelegate(self.node_list))
        self.node_list.setToolTip("체크한 구간끼리 병합합니다")
        self.node_list.currentRowChanged.connect(self._node_changed)
        self.node_list.itemChanged.connect(lambda _i: self._update_buttons())
        v.addWidget(self.node_list)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.merge_btn = QPushButton("병합 M")
        self.merge_btn.setToolTip("체크한 구간을 하나로 합칩니다 (M)")
        self.merge_btn.clicked.connect(self.merge_checked)
        self.split_btn = QPushButton("분할")
        self.split_btn.setToolTip("구성요소 탭에서 선택한 구성요소를 떼어 바로 뒤에 새 구간으로 만든다. 일부만 선택할 수 있다.")
        self.split_btn.clicked.connect(self.split_selected)
        self.rename_btn = QPushButton("이름 F2")
        self.rename_btn.setToolTip("고른 구간의 이름을 바꿉니다 (F2)")
        self.rename_btn.clicked.connect(lambda: self.rename_current())
        self.to_results_btn = QPushButton("⑤ →")
        self.to_results_btn.setToolTip("⑤ 결과에서 보기")
        self.to_results_btn.clicked.connect(self.open_in_results)
        for b in (self.merge_btn, self.split_btn, self.rename_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.to_results_btn)
        v.addLayout(row)
        v.addWidget(self._node_card())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(False)   # 좁은 패널에서도 세 탭을 화살표 없이 한 줄에
        self.tabs.setElideMode(Qt.ElideRight)
        self.member_list = QListWidget()
        self.member_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.member_list.itemSelectionChanged.connect(self._member_selection)
        self.member_hint = hint("")
        self.remove_btn = QPushButton("구간에서 빼기")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.tabs.addTab(tab_page(self.member_list, self.member_hint, self.remove_btn), "구성요소")
        self.uncovered_list = QListWidget()
        self.uncovered_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.uncovered_list.itemSelectionChanged.connect(self._update_buttons)
        self.uncovered_hint = hint("미포함 구성요소가 없습니다. 모든 구성요소가 구간에 들어 있습니다.")
        self.add_btn = QPushButton("고른 구간에 넣기")
        self.add_btn.clicked.connect(self.add_uncovered)
        self.tabs.addTab(tab_page(self.uncovered_list, self.uncovered_hint, self.add_btn), "미포함")
        self.owner_title = section("")
        self.owner_list = QListWidget()
        self.owner_list.setIconSize(QSize(30, 16))
        self.owner_list.itemClicked.connect(self._owner_clicked)
        self.owner_hint = hint("")
        self.tabs.addTab(tab_page(self.owner_list, self.owner_hint, top=self.owner_title), "속한 구간")
        # 하위 탭은 남는 높이만 쓴다. 크기 힌트를 무시해야 구간 목록이 먼저 전부 보이는 높이를 얻는다.
        self.tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.tabs.setMinimumHeight(140)
        v.addWidget(self.tabs, 1)
        v.addWidget(self._pick_card())
        self.msg = QLabel()
        self.msg.setObjectName("muted")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        return self.panel

    def _pick_card(self):
        """오른쪽 패널 맨 아래 '선택 구성요소' 카드: 고른 구성요소의 태그·종류·속한 구간·주요 속성."""
        self.pick_card = QFrame()
        self.pick_card.setObjectName("pickcard")
        v = QVBoxLayout(self.pick_card)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)
        v.addWidget(section("선택 구성요소"))
        self.pick_text = QLabel()
        self.pick_text.setWordWrap(True)
        self.pick_text.setTextFormat(Qt.RichText)
        v.addWidget(self.pick_text)
        self.pick_card.hide()
        return self.pick_card

    def _node_card(self):
        """고른 구간 카드: 경계·구성요소 수와 다른 도면으로 이어지는 칩(누르면 그 도면에서 같은 구간을 연다)."""
        self.node_card = QFrame()
        self.node_card.setObjectName("pickcard")
        v = QVBoxLayout(self.node_card)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)
        self.node_text = QLabel()
        self.node_text.setWordWrap(True)
        v.addWidget(self.node_text)
        self.jump_host = None
        self.jump_buttons = []
        self.node_card.hide()
        return self.node_card

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.panel.setFixedWidth(panel_width(self.window().width()))

    def _shortcuts(self):
        """화면 단축키(U-02). 버튼을 누르는 것과 같아서 비활성 버튼이면 아무 일도 하지 않는다."""
        keys = [("M", self.merge_btn), ("F2", self.rename_btn), ("Esc", self.overview_btn),
                ("Ctrl+Return", self.confirm_btn), ("Ctrl+Enter", self.confirm_btn)]
        self.shortcuts = []
        for key, btn in keys:
            sc = QShortcut(QKeySequence(key), self, context=Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(btn.click)
            self.shortcuts.append(sc)

    def commands(self):
        """명령 팔레트 항목 (label, 단축키 글자, 함수). 함수는 버튼을 누르는 것과 같다."""
        return [("전체 보기", "Esc", self.overview_btn.click), ("병합", "M", self.merge_btn.click), ("분할", "", self.split_btn.click),
                ("이름 바꾸기", "F2", self.rename_btn.click), ("구간 확정", "Ctrl+Enter", self.confirm_btn.click),
                ("확정 해제", "", self.reopen_btn.click), ("다시 제안", "", self.repropose_btn.click),
                ("⑤ 결과에서 보기", "", self.to_results_btn.click)]

    # ------------------------------------------------------------ 틀 연결
    def where(self):
        if not self.node_set:
            return None
        return {"drawing": self.ctx.drawing_number if self.ctx else self.name, "region": None, "run": None}

    def is_done(self):
        if self.node_set is not None:
            return self.node_set.get("status") == "confirmed"
        return nodes.any_confirmed(project_only=True)

    def explorer_items(self):
        if not self.view:
            return []
        return [(project_ctx.node_label(n), n["node_id"]) for n in self.view["nodes"]]

    def open_item(self, key):
        self.select_node(key)

    def on_enter(self):
        self.app.webview.set_mode(hide_panel=True, hide_graph=True)
        self.app.webview.clear_highlight()
        names = [e["name"] for e in data.list_extractions()]
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if cur in names:
            self.combo.setCurrentText(cur)
        self.combo.blockSignals(False)
        self._load()

    def select_drawing(self, name):
        if self.combo.findText(name) >= 0:
            self.combo.setCurrentText(name)

    # ------------------------------------------------------------ 읽기
    def _load(self):
        name = self.combo.currentText()
        pending, self._pending = self._pending, None
        self.name, self.ctx, self.graph, self.node_set, self.view = name or None, None, None, None, None
        self.picked_entity = None
        self.stale.set_messages(None)
        self.warn.set_messages(None)
        if not name:
            self.stack.setCurrentIndex(0)
            self._render()
            return
        try:
            info = data.viewer_html_for(name)
            ctx = project_ctx.load(name)
        except (OSError, ValueError, KeyError) as exc:
            info, ctx = {"html": None, "graph": None, "error": "추출 결과를 읽을 수 없음: %s" % exc}, None
        if not info.get("graph") or ctx is None:
            self.stack.setCurrentIndex(0)
            self.empty.setText("이 도면의 그래프가 없습니다. ① 자료 등록에서 '추출·그래프 만들기'를 실행하세요.")
            self._render()
            return
        if ctx.pg is None:
            self.stack.setCurrentIndex(0)
            self.empty.setText("프로젝트 그래프가 없어 검토구간을 보여 줄 수 없습니다.")
            self.warn.set_messages(ctx.error)
            self._render()
            return
        self.ctx, self.graph = ctx, ctx.pg
        self.entities = ctx.by_id
        self.local_map, self.entity_of_local = ctx.local_of, ctx.pid_of_local
        self.warn.set_messages(info.get("error"))
        self.unreadable = False
        try:
            self.node_set, self.saved = ctx.load_set()
        except (OSError, ValueError) as exc:
            sheets, problem = nodes.exclusion_for(self.graph)
            self.node_set, self.saved, self.unreadable = nodes.propose(self.graph, exclude_sheets=sheets), False, True
            self.warn.set_messages("저장된 검토구간을 읽을 수 없어 새로 제안합니다", [str(exc)] + ([problem] if problem else []))
        try:
            self.disk_fp = nodes.fingerprint(self._store_path())
        except OSError:  # 지금 읽지 못하는 파일이면 저장 때 다시 지문을 구해 보고, 그때 읽히면 다른 값이라 저장하지 않는다
            self.disk_fp = None
        if ctx.notice:
            self.notice = ctx.notice
            self.app.toast(ctx.notice)
        self.stack.setCurrentIndex(1)
        if info.get("html"):
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_drawing_enabled(True)
            self.app.webview.load_file(info["html"])
        self._render(pending)
        if pending and self.current_node_id() != pending:
            self.select_node(pending)

    # ------------------------------------------------------------ 그리기
    def _coverage(self):
        return nodes.coverage(self.node_set, self.graph)

    def _view_node(self, node_id):
        return next((n for n in self.view["nodes"] if n["node_id"] == node_id), None) if self.view else None

    def _shown(self):
        """목록에 보일 구간(표기 사본). '이 도면 구간'은 이 도면을 지나는 구간과 어느 도면에도 없는 빈 구간."""
        if self.scope.currentIndex() == 1:
            return self.view["nodes"]
        here = {n["node_id"] for n in span.nodes_on_drawing(self.view, self.ctx.drawing_number)}
        return [n for n in self.view["nodes"] if n["node_id"] in here or not n["drawings"]]

    def _drawing_of(self, eid):
        sheet = (self.entities.get(eid) or {}).get("sheet")
        return next((s["drawing_number"] for s in self.graph["sheets"] if s["graph_id"] == sheet), None)

    def _entity_text(self, eid, missing="-", always_drawing=False):
        """"RC-P01 · pump", 다른 도면 것이면 뒤에 "(101)". 도면 연결 구간은 "(도면 연결)"."""
        node = self.entities.get(eid)
        dn = self._drawing_of(eid)
        text = "%s · %s" % (entity_label(node), (node or {}).get("kind") or missing)
        if dn is None and node is not None:
            return text + " (도면 연결)"
        if dn and (always_drawing or dn != self.ctx.drawing_number):
            return text + " (%s)" % self.ctx.short.get(dn, dn)
        return text

    def _render(self, keep=None):
        """node_set 기준으로 패널·도면 색·머리말을 다시 그린다. keep은 다시 선택할 node_id."""
        ns = self.node_set
        keep = keep or self.current_node_id()
        self.node_list.blockSignals(True)
        self.node_list.clear()
        self.uncovered_list.clear()
        if ns is None:
            self.view = None
            self.node_list.blockSignals(False)
            self.node_list.updateGeometry()
            self.chip_status.set_state("검토구간 —")
            self.list_head.setText("검토구간")
            self.kpi.setText("")
            self.gate.setText("")
            self.member_list.clear()
            self.owner_list.clear()
            self.notice_bar.set_messages(None)
            self._fill_node_card()
            self._update_buttons()
            self.app.update_header()
            self.app.refresh_stages()
            return
        self.view = self.ctx.view(ns)
        confirmed = ns["status"] == "confirmed"
        # 옮긴 집합은 다시 확정해야 한다는 알림이라 확정되면 내린다.
        self.notice_bar.set_messages(None if confirmed else self.notice)
        index = {n["node_id"]: i for i, n in enumerate(ns["nodes"])}   # 색은 집합 순서로(목록 거르기와 무관하게 같은 색)
        dn = self.ctx.drawing_number
        shown = self._shown()
        for n in shown:
            here = (n.get("members_by_drawing") or {}).get(dn, 0)
            it = QListWidgetItem(seg_icon(index[n["node_id"]], n["node_id"]), project_ctx.node_label(n))
            it.setData(Qt.UserRole, n["node_id"])
            it.setData(COUNT_ROLE, "%d개" % n["member_count"] if here == n["member_count"]
                       else "%d/%d" % (here, n["member_count"]))
            it.setToolTip("%s\n%s\n%s\n근거: %s" % (project_ctx.node_label(n), project_ctx.counts_text(n, dn),
                                                 project_ctx.boundary_text(n), n.get("basis") or "-"))
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | (Qt.NoItemFlags if confirmed else Qt.ItemIsUserCheckable)
            it.setFlags(flags)
            if not confirmed:
                it.setCheckState(Qt.Unchecked)
            self.node_list.addItem(it)
        self.node_list.blockSignals(False)
        self.node_list.updateGeometry()
        cov = self._coverage()
        empties = [n["node_id"] for n in ns["nodes"] if not n["members"]]
        # 확정·제안은 구간 하나가 아니라 집합 전체의 상태라 목록 머리에 한 번만 쓴다.
        total = len(ns["nodes"])
        count = "%d개" % total if len(shown) == total else "%d/%d개" % (len(shown), total)
        self.list_head.setText("검토구간 · %s · %s" % (count, "확정" if confirmed else "제안"))
        self.kpi.setText("구성요소 <b>%d</b> · 미포함 <b>%d</b> · 덮음 %s"
                         % (cov["total"], len(cov["uncovered"]), html.escape(self.ctx.coverage_text(ns)[0])))
        self.progress.setRange(0, max(cov["total"], 1))
        self.progress.setValue(cov["covered"])
        for eid in cov["uncovered"]:
            it = QListWidgetItem(self._entity_text(eid, always_drawing=True))
            it.setData(Qt.UserRole, eid)
            self.uncovered_list.addItem(it)
        self.tabs.setTabText(1, "미포함 %d" % len(cov["uncovered"]))
        show_list_or_hint(self.uncovered_list, self.uncovered_hint)
        stale = nodes.is_stale(ns, self.graph)
        self.stale.set_messages(
            "프로젝트 그래프(도면·도면 연결)가 바뀌었습니다(저장본 %s → 현재 %s). '다시 제안'으로 새로 만들거나 확정 해제 뒤 고치세요."
            % (ns.get("graph_version"), self.graph.get("graph_version")) if stale else migrate.notice(ns))
        if confirmed:
            at = ns.get("confirmed_at")
            try:
                at = kst_text(at)
            except (TypeError, ValueError):
                pass
            self.chip_status.set_state("확정 · %s · %s" % (ns.get("confirmed_by"), at), "passed")
            self.gate.setText("확정됨. 고치려면 '확정 해제'를 누르세요.")
        else:
            self.chip_status.set_state("제안 · 저장됨" if self.saved else "제안 · 저장 전(편집·확정하면 저장)", "warn")
            reasons = []
            if cov["uncovered"]:
                reasons.append("미포함 %d" % len(cov["uncovered"]))
            if empties:
                reasons.append("빈 구간 %s" % ", ".join(empties))
            if stale:
                reasons.append("그래프 판 바뀜")
            self.gate.setText("확정 가능" if not reasons else "확정하려면 해결: " + " · ".join(reasons))
        row = next((i for i, n in enumerate(shown) if n["node_id"] == keep), -1)   # 고른 구간이 없으면 전체 보기
        # setCurrentRow(-1)만으로는 목록이 초점을 받을 때(main_focus) Qt가 첫 행을 골라 전체 보기가 풀린다.
        self.node_list.setCurrentIndex(self.node_list.model().index(row, 0))
        self._fill_members()
        self._sync_pick()
        self._fill_owner()
        self._fill_node_card()
        self._paint()
        self._update_buttons()
        self._publish_node()
        self.app.update_header()
        self.app.refresh_stages()

    def _paint(self):
        if not self.node_set or self.app.webview.current_file is None:
            return
        cur = self.current_node_id()
        groups = [{"color": "var(--%s)" % seg_token(i), "active": n["node_id"] == cur, "label": n["node_id"],
                   "ids": [self.local_map[m] for m in n["members"] if m in self.local_map]}
                  for i, n in enumerate(self.node_set["nodes"])]
        # 이 도면에 없는 구간은 범례·색에서 뺀다. 고른 구간은 이 도면에 없어도 넘겨서 나머지를 흐리게 한다.
        groups = [g for g in groups if g["ids"] or g["active"]]
        unc = [self.local_map[e] for e in self._coverage()["uncovered"] if e in self.local_map]
        self.app.webview.set_segments(groups, unc)
        chips = self.drawing_chips()
        self._chip_keys = {c["key"] for c in chips}  # on_chip은 이 화면이 단 칩의 key만 받는다(웹 메시지는 신뢰하지 않음)
        self.app.webview.set_chips(chips)
        self.app.webview.pick(self.local_map.get(self.picked_entity) if self.picked_entity else None)

    # ------------------------------------------------------------ 도면 연결 칩
    def _chip_target(self, chip):
        """칩이 여는 추출 이름과 열 수 없는 사유(열 수 있으면 None)."""
        name = chip.get("name")
        if not name or self.combo.findText(name) < 0:
            return None, "%s 추출 결과가 없어 열 수 없습니다. ① 자료 등록에서 그 도면을 추출하세요." % chip["drawing"]
        return name, None

    def drawing_chips(self):
        """도면 위 칩. 고른 구간이 있으면 그 구간 것만, 전체 보기면 이 도면의 모든 구간 것.
        같은 연결점·같은 상대(도면, 구간)는 한 번만, 같은 연결점의 칩 여러 개는 row로 쌓는다."""
        if not self.view:
            return []
        cur = self._view_node(self.current_node_id())
        out, seen, rows = [], set(), {}
        for n in [cur] if cur else self.view["nodes"]:
            for c in self.ctx.chips(n):
                key = (c["local_id"], c["drawing"], c["node_id"])
                if not c["local_id"] or key in seen:
                    continue
                seen.add(key)
                name, why = self._chip_target(c)
                rows[c["local_id"]] = rows.get(c["local_id"], -1) + 1
                out.append({"local_id": c["local_id"], "text": c["text"], "kind": "link", "row": rows[c["local_id"]],
                            "key": "%s|%s" % (c["node_id"], name or ""),
                            "tip": why or "%s에서 %s 열기" % (c["drawing"], c["node_id"])})
        return out

    def on_chip(self, key):
        """도면 위 칩을 누름. key = "<구간 ID>|<추출 이름>"(이름이 비면 열 수 없는 도면)."""
        if key not in getattr(self, "_chip_keys", ()):
            return False
        node_id, _, name = str(key).partition("|")
        if not name:
            self.msg.setText("상대 도면의 추출 결과가 없어 열 수 없습니다.")
            return False
        return self.jump(name, node_id)

    def jump(self, name, node_id):
        """name 도면으로 바꾸고 같은 구간을 고른다(같은 도면이면 구간만 고른다)."""
        if not name or self.combo.findText(name) < 0:
            return False
        if name == self.combo.currentText():
            return self.select_node(node_id)
        self._pending = node_id
        self.combo.setCurrentText(name)
        return self.current_node_id() == node_id

    def _fill_node_card(self):
        """고른 구간의 경계·구성요소 수와 이어지는 도면 버튼. 이 도면에 없는 구간이면 그 구간이 있는 도면 버튼."""
        # 버튼은 담는 상자째 바꾼다. 버튼만 deleteLater하면 지워지기 전 재진입(도면 바꿈 중 다시 그림)에서 남은 버튼이
        # 레이아웃 밖 640×480으로 떠서 카드 글자를 덮었다.
        if self.jump_host is not None:
            self.jump_host.hide()
            self.jump_host.setParent(None)
            self.jump_host.deleteLater()
        self.jump_host = QWidget()
        self.jump_box = QVBoxLayout(self.jump_host)
        self.jump_box.setContentsMargins(0, 0, 0, 0)
        self.jump_box.setSpacing(2)
        self.node_card.layout().addWidget(self.jump_host)
        self.jump_buttons = []
        n = self._view_node(self.current_node_id())
        self.node_card.setVisible(n is not None)
        if n is None:
            return
        dn = self.ctx.drawing_number
        lines = [project_ctx.boundary_text(n), project_ctx.counts_text(n, dn)]
        if dn in n["drawings"]:
            targets = self.ctx.chips(n)
        else:
            lines.append("이 도면에는 이 구간의 구성요소가 없습니다.")
            targets = [{"text": "%s에서 보기" % d, "drawing": d, "name": self.ctx.drawing_names.get(d),
                        "node_id": n["node_id"]} for d in n["drawings"]]
        self.node_text.setText("\n".join(lines))
        for c in targets:
            name, why = self._chip_target(c)
            b = QPushButton(c["text"])
            b.setToolTip(why or "%s 도면으로 가서 %s을(를) 고릅니다" % (c["drawing"], c["node_id"]))
            b.setEnabled(name is not None)
            b.clicked.connect(lambda _c=False, nm=name, nid=c["node_id"]: self.jump(nm, nid))
            self.jump_box.addWidget(b)
            self.jump_buttons.append(b)

    def _fill_members(self):
        self.member_list.blockSignals(True)   # 목록을 다시 채우는 것은 구성요소 선택이 아니다
        self.member_list.clear()
        n = self.current_node()
        for eid in (n["members"] if n else []):
            it = QListWidgetItem(self._entity_text(eid, missing="그래프에 없음"))
            it.setData(Qt.UserRole, eid)
            self.member_list.addItem(it)
            it.setSelected(eid == self.picked_entity)
        self.member_list.blockSignals(False)
        self.tabs.setTabText(0, "구성요소 %d" % len(n["members"]) if n else "구성요소")
        self.member_hint.setText("%s은(는) 빈 구간입니다. 미포함 탭에서 구성요소를 넣거나 병합하세요." % n["node_id"]
                                 if n else "구간을 고르면 구성요소가 여기에 나옵니다.")
        show_list_or_hint(self.member_list, self.member_hint)

    def _fill_owner(self):
        self.owner_list.clear()
        eid = self.picked_entity
        owners = nodes.nodes_of(self.node_set, eid) if eid and self.node_set else []
        index = {n["node_id"]: i for i, n in enumerate(self.node_set["nodes"])} if self.node_set else {}
        for nid in owners:
            it = QListWidgetItem(seg_icon(index[nid], nid), project_ctx.node_label(self._view_node(nid)))
            it.setData(Qt.UserRole, nid)
            self.owner_list.addItem(it)
        label = entity_label(self.entities.get(eid)) if eid else None
        self.owner_title.setText("%s 이(가) 속한 구간" % label if label else "")
        self.owner_title.setVisible(bool(label))
        self.owner_hint.setText("%s 은(는) 어느 구간에도 없습니다(미포함)." % label if label
                                else "도면에서 구성요소를 누르면 그 구성요소가 속한 구간이 여기에 나옵니다.")
        self.tabs.setTabText(2, "속한 구간 %d" % len(owners) if label else "속한 구간")
        show_list_or_hint(self.owner_list, self.owner_hint)

    def _update_buttons(self):
        ns = self.node_set
        editable = bool(ns) and ns["status"] != "confirmed"
        checked = self.checked_node_ids()
        cur = self.current_node()
        picked = self.selected_members()
        cov = self._coverage() if ns else {"uncovered": [1]}
        empties = bool(ns) and any(not n["members"] for n in ns["nodes"])
        stale = bool(ns) and nodes.is_stale(ns, self.graph)
        self.merge_btn.setText("병합 %d M" % len(checked) if checked else "병합 M")
        self.merge_btn.setEnabled(editable and len(checked) >= 2)
        self.rename_btn.setEnabled(editable and cur is not None)
        self.split_btn.setEnabled(editable and cur is not None and 0 < len(picked) < len(cur["members"]))
        self.remove_btn.setEnabled(editable and bool(picked))
        self.add_btn.setEnabled(editable and cur is not None and bool(self.uncovered_list.selectedItems()))
        self.confirm_btn.setEnabled(editable and not cov["uncovered"] and not empties and not stale and bool(ns["nodes"]))
        self.reopen_btn.setEnabled(bool(ns) and ns["status"] == "confirmed")
        self.repropose_btn.setEnabled(bool(ns) and ns["status"] != "confirmed")
        self.to_results_btn.setEnabled(cur is not None)
        self.overview_btn.setEnabled(cur is not None or self.picked_entity is not None)

    # ------------------------------------------------------------ 선택
    def _node(self, node_id):
        return next((n for n in self.node_set["nodes"] if n["node_id"] == node_id), None) if self.node_set else None

    def current_node_id(self):
        it = self.node_list.currentItem()
        return it.data(Qt.UserRole) if it is not None else None

    def current_node(self):
        nid = self.current_node_id()
        return self._node(nid) if nid else None

    def checked_node_ids(self):
        return [self.node_list.item(i).data(Qt.UserRole) for i in range(self.node_list.count())
                if self.node_list.item(i).checkState() == Qt.Checked]

    def selected_members(self):
        return [it.data(Qt.UserRole) for it in self.member_list.selectedItems()]

    def select_node(self, node_id):
        """목록에서 구간을 고른다. '이 도면 구간'에 없는 프로젝트 구간이면 목록을 '프로젝트 전체'로 넓혀 고른다."""
        for i in range(self.node_list.count()):
            if self.node_list.item(i).data(Qt.UserRole) == node_id:
                self.node_list.setCurrentRow(i)
                return True
        if self._node(node_id) is None or self.scope.currentIndex() == 1:
            return False
        self.scope.blockSignals(True)
        self.scope.setCurrentIndex(1)
        self.scope.blockSignals(False)
        self._render(node_id)
        return self.current_node_id() == node_id

    def set_checked(self, node_ids):
        for i in range(self.node_list.count()):
            it = self.node_list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in node_ids else Qt.Unchecked)

    def _publish_node(self):
        nid = self.current_node_id()
        if self.name and nid:
            self.app.set_selection({"kind": "node", "drawing": self.name, "node_id": nid})

    def _node_changed(self, _row):
        if self.node_set is None:
            return
        self._fill_members()
        self._sync_pick()
        self._fill_owner()
        self._fill_node_card()
        self._paint()
        self._update_buttons()
        self._publish_node()

    def _member_selection(self):
        ids = self.selected_members()
        self._set_pick(ids[0] if len(ids) == 1 else None, center=True)
        self._update_buttons()

    def show_overview(self):
        """Esc: 고른 구성요소가 있으면 그것만 풀고, 없으면 구간 선택을 풀어 전체 보기로 돌아간다."""
        if self.picked_entity is not None:
            self.member_list.blockSignals(True)
            self.member_list.clearSelection()
            self.member_list.blockSignals(False)
            self._set_pick(None)
        else:
            self.node_list.setCurrentRow(-1)
        self._update_buttons()

    def _sync_pick(self):
        """고른 구간 밖의 구성요소 선택은 푼다(전체 보기에서는 유지)."""
        cur = self.current_node()
        if self.picked_entity and cur is not None and self.picked_entity not in cur["members"]:
            self.picked_entity = None
        self._fill_pick()

    def _set_pick(self, eid, center=False):
        self.picked_entity = eid
        self._fill_pick()
        self._fill_owner()
        if self.node_set and self.app.webview.current_file is not None:
            self.app.webview.pick(self.local_map.get(eid) if eid else None, center=center)

    def pick_info(self):
        """선택 구성요소 카드의 내용 [(항목, 값)]. 고른 구성요소가 없으면 빈 목록."""
        eid = self.picked_entity
        node = self.entities.get(eid) if eid else None
        if node is None:
            return []
        rows = [("태그", entity_label(node)), ("종류", node.get("kind") or "-"),
                ("속한 구간", ", ".join(nodes.nodes_of(self.node_set, eid)) or "없음(미포함)")]
        desc = [x.strip() for x in (node.get("label_text") or "").split("\n")[1:] if x.strip()]
        if desc:
            rows.append(("설명", " ".join(desc)))
        for key in ("line_no", "line_type"):
            if node.get(key):
                rows.append((key, node[key]))
        if node.get("node_type") == "pipe_segment":
            rows.append(("흐름 방향", "확인됨" if node.get("flow_direction") else "미확인"))
        shown = {"kind", "tag", "line_no", "line_type", "flow_direction"}
        rows += [(k, v) for k, v in (node.get("attributes") or {}).items() if k not in shown and v not in (None, "")]
        return rows

    def _fill_pick(self):
        rows = self.pick_info()
        self.pick_card.setVisible(bool(rows))
        self.pick_text.setText("".join("<div><span style='color:%s'>%s</span>&nbsp; <b>%s</b></div>"
                                       % (tokens.c("muted"), html.escape(str(k)), html.escape(str(v))) for k, v in rows))

    def _owner_clicked(self, item):
        nid = item.data(Qt.UserRole)
        if nid:
            self.select_node(nid)

    def on_node(self, sel):
        """도면에서 누른 구성요소. 지금 구간에 있거나 속한 구간이 하나면 그 구간에서 구성요소를 고르고,
        없으면 미포함 탭, 여럿이면 속한 구간 탭을 연다."""
        if not self.node_set:
            return
        eid = sel.get("entity_id")
        if eid not in self.entities and eid:   # 뷰어는 도면 안 entity_id를 보낸다
            eid = project.nid(self.ctx.graph_id, eid)
        if eid not in self.entities:
            eid = self.entity_of_local.get(sel.get("local_id"))
        if eid not in self.entities:
            return
        owners = nodes.nodes_of(self.node_set, eid)
        cur = self.current_node_id()
        target = cur if cur in owners else owners[0] if len(owners) == 1 else None
        self.picked_entity = eid
        if target is not None:
            self.select_node(target)
        self.member_list.blockSignals(True)   # 도면에서 누른 것이라 화면을 옮기지 않는다
        for i in range(self.member_list.count()):
            it = self.member_list.item(i)
            it.setSelected(it.data(Qt.UserRole) == eid)
        self.member_list.blockSignals(False)
        self._set_pick(eid)
        self._update_buttons()
        for i in range(self.uncovered_list.count()):
            it = self.uncovered_list.item(i)
            it.setSelected(it.data(Qt.UserRole) == eid)
        self.tabs.setCurrentIndex(0 if target is not None else 1 if not owners else 2)
        self.app.set_selection({"kind": "component", "drawing": self.name, "entity_id": eid})

    # ------------------------------------------------------------ 편집
    def _apply(self, fn, keep=None, done=None):
        """nodes의 순수 함수 하나를 적용하고 저장한다. 실패 사유는 패널에 보여 주고 집합은 그대로 둔다."""
        try:
            new = fn(self.node_set)
        except ValueError as exc:
            self.msg.setText("할 수 없음: %s" % exc)
            return False
        return self._replace(new, keep, done)

    def _replace(self, new, keep=None, done=None):
        """new를 저장하고 화면에 반영한다. done이 있으면 토스트를 띄우고, 실행 취소는 직전 집합을 다시 저장한다(U-07)."""
        old, self.node_set = self.node_set, new
        if not self._save():
            self.node_set = old
            self._render(keep)
            return False
        self.msg.setText("")
        self._render(keep)
        if done:
            self.app.toast(done, undo=self._undo_to(old, keep))
        return True

    def _undo_to(self, old, keep):
        """확정·확정 해제도 집합 상태가 바뀐 것이므로 같은 길(저장)로 직전 집합을 되살린다.
        토스트가 떠 있는 사이 다른 도면으로 옮겼으면 old만 저장하고 지금 화면은 건드리지 않는다."""
        def undo():
            if self.node_set is not None and self.node_set["graph_id"] == old["graph_id"]:
                self._replace(old, keep)
                return
            try:
                nodes.save(old)
            except OSError as exc:
                self.app.log_error("검토구간 실행 취소 실패", exc)
        return undo

    def _store_path(self):
        return nodes.store_path(self.node_set.get("project_id"), self.node_set["graph_id"])

    def ask_overwrite_unreadable(self, path):
        return QMessageBox.question(
            self, "검토구간 파일을 읽을 수 없음",
            "저장된 검토구간 파일을 읽지 못했습니다.\n%s\n\n원래 파일을 백업 폴더에 남기고 지금 내용으로 저장할까요?" % path
        ) == QMessageBox.Yes

    def _save(self):
        """디스크에 쓴 경우에만 True. 실패하면 화면은 이전 집합으로 되돌린다(확정이 저장된 것처럼 보이지 않게).
        읽은 뒤 다른 창이 먼저 저장했으면 쓰지 않는다. 읽지 못한 파일은 사용자가 허락할 때만 백업한 뒤 덮어쓴다."""
        path = self._store_path()
        if self.unreadable and os.path.isfile(path):
            if not self.ask_overwrite_unreadable(path):
                self.msg.setText("저장하지 않았습니다. 읽지 못한 검토구간 파일은 그대로 있습니다.")
                return False
            try:
                migrate._backup(path, "읽기실패")
            except OSError as exc:
                self.app.log_error("검토구간 백업 실패", exc)
                self.msg.setText("원래 파일을 백업하지 못해 저장하지 않았습니다: %s" % exc)
                return False
        try:
            nodes.save(self.node_set, expect=self.disk_fp)
        except nodes.Conflict:
            self.msg.setText("다른 창에서 이 검토구간을 먼저 저장해서 이번 변경은 저장하지 않았습니다. "
                             "도면을 다시 열어 최신 내용을 불러온 뒤 고치세요.")
            return False
        except OSError as exc:
            self.app.log_error("검토구간 저장 실패", exc)
            self.msg.setText("저장 실패 — 변경을 적용하지 않음: %s" % exc)
            return False
        self.unreadable = False
        self.disk_fp = nodes.fingerprint(path)
        self.saved = True
        self.app.mark_saved(self.node_set["history"][-1]["at"])
        return True

    def merge_checked(self):
        ids = self.checked_node_ids()
        first = next((n["node_id"] for n in self.node_set["nodes"] if n["node_id"] in ids), None)
        return self._apply(lambda s: nodes.merge(s, ids), keep=first, done="%s를 병합했습니다" % "·".join(ids))

    def split_selected(self):
        cur, picked = self.current_node_id(), self.selected_members()
        before = {n["node_id"] for n in self.node_set["nodes"]}
        ok = self._apply(lambda s: nodes.split(s, cur, picked), keep=cur,
                         done="%s에서 구성요소 %d개를 새 구간으로 분할했습니다" % (cur, len(picked)))
        if ok:
            new = next(n["node_id"] for n in self.node_set["nodes"] if n["node_id"] not in before)
            self.select_node(new)
        return ok

    def remove_selected(self):
        cur, picked = self.current_node_id(), self.selected_members()

        def fn(s):
            for eid in picked:
                s = nodes.remove_member(s, cur, eid)
            return s
        return self._apply(fn, keep=cur, done="%s에서 구성요소 %d개를 뺐습니다" % (cur, len(picked)))

    def add_uncovered(self):
        cur = self.current_node_id()
        ids = [it.data(Qt.UserRole) for it in self.uncovered_list.selectedItems()]

        def fn(s):
            for eid in ids:
                s = nodes.add_member(s, cur, eid)
            return s
        return self._apply(fn, keep=cur, done="%s에 구성요소 %d개를 넣었습니다" % (cur, len(ids)))

    def rename_current(self, name=None):
        cur = self.current_node()
        if cur is None:
            return False
        if name is None:
            name, ok = QInputDialog.getText(self, "이름 바꾸기", "%s 새 이름" % cur["node_id"], text=cur["name"])
            if not ok:
                return False
        return self._apply(lambda s: nodes.rename(s, cur["node_id"], name), keep=cur["node_id"],
                           done="%s 이름을 바꿨습니다" % cur["node_id"])

    def repropose(self, ask=True):
        """현재 그래프로 다시 제안한다. 저장본에 편집 기록이 있으면 버릴지 묻는다. 새 제안은 바로 저장하고,
        버린 집합은 토스트의 실행 취소로 되살릴 수 있다."""
        if not self.graph or (self.node_set and self.node_set["status"] == "confirmed"):
            return False
        edited = self.saved and len(self.node_set.get("history") or []) > 1
        if ask and edited and QMessageBox.question(
                self, "다시 제안", "지금 구간 편집 내용을 버리고 다시 제안할까요?") != QMessageBox.Yes:
            return False
        sheets, problem = nodes.exclusion_for(self.graph)
        if problem:
            self.warn.set_messages(problem)
        new = nodes.propose(self.graph, exclude_sheets=sheets)
        previous = (self.node_set or {}).get("previous")
        if previous:  # 확정 해제한 집합이면 옛 확정본과의 대응을 보이고, 사람이 '이대로 적용'해야 바꾼다(§4.6)
            new["previous"] = previous
            from hazop.study import results as res
            pv = remap.preview(self.node_set, new, res.load_deviations())
            text = ("옛 확정본과 새 제안의 대응(새 구간 수): 같음 %(same)d · 합쳐짐 %(merged)d · 나뉨 %(split)d · "
                    "범위 바뀜 %(changed)d · 새 구간 %(new)d · 제외 구간 %(excluded)d" % pv["counts"])
            text += "\n옛 구간 중 스크리닝 제외로 가는 것 %d개 · 새 제안과 겹치지 않는 것 %d개" % (
                pv["to_excluded_old"], pv["unmatched_old"])
            if pv["blocked_by"]:
                b = pv["blocked_by"]
                text += ("\n\n주의: 이대로 다시 확정하면 ⑤ 결과를 옮기지 못합니다. 사람이 판정한 항목이 있는 옛 구간 %d개가 "
                         "스크리닝 제외로 가고, 옮길 곳이 없는 옛 칸이 %d개입니다. 적용한 뒤 ④에서 해당 구성요소를 꺼내 "
                         "다시 확정하세요(옛 결과는 보관본으로 남고, 다시 확정하면 거기서 옮깁니다)." % (
                             len(b["to_excluded"]), len(b["unmapped"])))
            else:
                text += "\n\n같음 구간의 ⑤ 결과는 다시 확정하면 그대로 이어지고, 나머지는 '범위 바뀜 · 다시 확인'으로 옮깁니다."
            text += " 이대로 적용할까요?"
            if ask and QMessageBox.question(self, "다시 제안 대응표", text) != QMessageBox.Yes:
                return False
            path = self._store_path()
            if os.path.isfile(path):
                try:
                    project_ctx.backup([path], "검토구간-다시제안")
                except OSError as exc:
                    self.app.log_error("검토구간 백업 실패", exc)
                    self.msg.setText("다시 제안하기 전 백업을 하지 못해 바꾸지 않았습니다: %s" % exc)
                    return False
        return self._replace(new, done="다시 제안했습니다" + (" · 뺀 도면 표시를 읽지 못함" if problem else ""))

    def confirm(self, reviewer=None):
        reviewer = reviewer or self.app.reviewer_name()
        if not reviewer:
            name, ok = QInputDialog.getText(self, "검토자 이름", "확정하려면 검토자 이름이 필요합니다(설정에 저장).")
            if not ok or not name.strip():
                return False
            self.app.set_reviewer_name(name.strip())
            reviewer = name.strip()
        if not self._apply(lambda s: nodes.confirm(s, self.graph, reviewer), done="구간을 확정했습니다"):
            return False
        self._carry_results()
        return True

    def _carry_results(self):
        """다시 확정했으면 옛 확정본의 ⑤ 결과를 바로 옮겨 저장한다(⑤를 열기 전에도 ⑥·탐색기가 같은 결과를 읽게)."""
        from hazop.study import results as res
        try:
            carried, report = remap.carry_saved(self.node_set, res.load_deviations())
        except (OSError, ValueError) as exc:
            self.app.log_error("분석 결과 옮기기 실패", exc)
            return
        if carried is not None:
            self.app.toast("이전 확정본의 ⑤ 결과를 옮겼습니다: 범위 바뀜 %d건은 다시 확인" % report["scope_changed_entries"])
        elif report.get("to_excluded") or report.get("unmapped"):
            self.app.toast("⑤ 결과를 옮기지 못했습니다: %s" % report.get("reason"))

    def reopen(self):
        return self._apply(nodes.reopen, done="확정을 해제했습니다")

    def open_in_results(self):
        nid = self.current_node_id()
        if self.name and nid:
            self.app.open_results_for(self.name, nid)
