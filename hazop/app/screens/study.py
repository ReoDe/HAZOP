"""④ 검토구간(HAZOP study node) 화면 (stage3-spec §A·§B, 디자인/시안/완성본/B-고밀도작업대/4-검토구간).

도면 하나의 그래프에서 구간 집합(hazop.study.nodes)을 제안·편집·확정한다. 화면 상태의 기준은 self.node_set 하나이고,
편집은 모두 nodes의 순수 함수로 새 집합을 만든 뒤 저장하고 다시 그린다. 처음 제안은 사용자가 편집하거나 확정할 때 저장된다.
도면 위 구간 색은 seg1..seg5를 순환하고, 목록의 S 번호 배지에도 같은 색을 써서 색만으로 구분하지 않는다.
"""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QStackedWidget,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTabWidget, QVBoxLayout, QWidget)

from hazop.app import data, tokens
from hazop.app.widgets import Banner, Chip, empty_label, kst_text
from hazop.study import nodes

SEG_COUNT = 5
PANEL_MIN_W, PANEL_MAX_W = 264, 340     # 셸 오른쪽 열 clamp(264px, 20vw, 340px)
ROW_H = 24
MIN_ROWS = 4                            # 패널 높이가 모자랄 때도 구간 목록에 남기는 행 수
COUNT_ROLE = Qt.UserRole + 1


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
        o.text = o.fontMetrics.elidedText(o.text, Qt.ElideRight, max(room, 0))
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
        self.name = None        # 추출 폴더 이름(도면 선택)
        self.graph = None
        self.node_set = None
        self.saved = False      # node_set이 저장본과 같은가(처음 제안은 False)
        self.entities = {}      # entity_id → graph node
        self.local_map = {}     # entity_id → 뷰어 data-local-id
        self.entity_of_local = {}
        self.picked_entity = None  # 도면에서 누른 구성요소
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("도면"))
        self.combo = QComboBox()
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

    # ------------------------------------------------------------ 오른쪽 패널
    def _panel(self):
        """구간 목록(전부 보임) + 고른 구간의 하위 탭(구성요소·미포함·속한 구간) (U-18)."""
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        self.panel.setFixedWidth(PANEL_MAX_W)
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
        self.list_head = section("검토구간")
        v.addWidget(self.list_head)
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
        self.msg = QLabel()
        self.msg.setObjectName("muted")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        return self.panel

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.panel.setFixedWidth(panel_width(self.window().width()))

    def _shortcuts(self):
        """화면 단축키(U-02). 버튼을 누르는 것과 같아서 비활성 버튼이면 아무 일도 하지 않는다."""
        keys = [("M", self.merge_btn), ("F2", self.rename_btn),
                ("Ctrl+Return", self.confirm_btn), ("Ctrl+Enter", self.confirm_btn)]
        self.shortcuts = []
        for key, btn in keys:
            sc = QShortcut(QKeySequence(key), self, context=Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(btn.click)
            self.shortcuts.append(sc)

    def commands(self):
        """명령 팔레트 항목 (label, 단축키 글자, 함수). 함수는 버튼을 누르는 것과 같다."""
        return [("병합", "M", self.merge_btn.click), ("분할", "", self.split_btn.click),
                ("이름 바꾸기", "F2", self.rename_btn.click), ("구간 확정", "Ctrl+Enter", self.confirm_btn.click),
                ("확정 해제", "", self.reopen_btn.click), ("다시 제안", "", self.repropose_btn.click),
                ("⑤ 결과에서 보기", "", self.to_results_btn.click)]

    # ------------------------------------------------------------ 틀 연결
    def where(self):
        if not self.node_set:
            return None
        return {"drawing": self.node_set.get("drawing_number") or self.name, "region": None, "run": None}

    def is_done(self):
        return nodes.any_confirmed()

    def explorer_items(self):
        if not self.node_set:
            return []
        return [("%s %s" % (n["node_id"], n["name"]), n["node_id"]) for n in self.node_set["nodes"]]

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
        self.name, self.graph, self.node_set, self.picked_entity = name or None, None, None, None
        self.stale.set_messages(None)
        self.warn.set_messages(None)
        if not name:
            self.stack.setCurrentIndex(0)
            self._render()
            return
        try:
            info = data.viewer_html_for(name)
        except (OSError, ValueError, KeyError) as exc:
            info = {"html": None, "graph": None, "error": "추출 결과를 읽을 수 없음: %s" % exc}
        self.graph = info.get("graph")
        if not self.graph:
            self.stack.setCurrentIndex(0)
            self.empty.setText("이 도면의 그래프가 없습니다. ① 자료 등록에서 '추출·그래프 만들기'를 실행하세요.")
            self._render()
            return
        self.entities = {n["entity_id"]: n for n in self.graph.get("nodes", [])}
        self.local_map = data.entity_local_map(self.graph)
        self.entity_of_local = {n["local_id"]: n["entity_id"] for n in self.graph.get("nodes", []) if n.get("local_id")}
        self.warn.set_messages(info.get("error"))
        try:
            saved = nodes.load(self.graph)
        except (OSError, ValueError) as exc:
            saved = None
            self.warn.set_messages("저장된 검토구간을 읽을 수 없어 새로 제안합니다", [str(exc)])
        if saved is not None:
            self.node_set, self.saved = saved, True
        else:
            self.node_set, self.saved = nodes.propose(self.graph), False
        self.stack.setCurrentIndex(1)
        if info.get("html"):
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_drawing_enabled(True)
            self.app.webview.load_file(info["html"])
        self._render()

    # ------------------------------------------------------------ 그리기
    def _coverage(self):
        return nodes.coverage(self.node_set, self.graph)

    def _render(self, keep=None):
        """node_set 기준으로 패널·도면 색·머리말을 다시 그린다. keep은 다시 선택할 node_id."""
        ns = self.node_set
        keep = keep or self.current_node_id()
        self.node_list.blockSignals(True)
        self.node_list.clear()
        self.uncovered_list.clear()
        if ns is None:
            self.node_list.blockSignals(False)
            self.node_list.updateGeometry()
            self.chip_status.set_state("검토구간 —")
            self.list_head.setText("검토구간")
            self.kpi.setText("")
            self.gate.setText("")
            self.member_list.clear()
            self.owner_list.clear()
            self._update_buttons()
            self.app.update_header()
            self.app.refresh_stages()
            return
        confirmed = ns["status"] == "confirmed"
        for i, n in enumerate(ns["nodes"]):
            it = QListWidgetItem(seg_icon(i, n["node_id"]), n["name"])
            it.setData(Qt.UserRole, n["node_id"])
            it.setData(COUNT_ROLE, "%d개" % len(n["members"]))
            it.setToolTip("%s %s · 구성요소 %d개\n근거: %s" % (n["node_id"], n["name"], len(n["members"]),
                                                          n.get("basis") or "-"))
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
        self.list_head.setText("검토구간 · %d개 · %s" % (len(ns["nodes"]), "확정" if confirmed else "제안"))
        self.kpi.setText("구성요소 <b>%d</b> · 덮음 <b>%d/%d</b> · 미포함 <b>%d</b>"
                         % (cov["total"], cov["covered"], cov["total"], len(cov["uncovered"])))
        self.progress.setRange(0, max(cov["total"], 1))
        self.progress.setValue(cov["covered"])
        for eid in cov["uncovered"]:
            node = self.entities.get(eid)
            it = QListWidgetItem("%s · %s" % (entity_label(node), (node or {}).get("kind") or "-"))
            it.setData(Qt.UserRole, eid)
            self.uncovered_list.addItem(it)
        self.tabs.setTabText(1, "미포함 %d" % len(cov["uncovered"]))
        show_list_or_hint(self.uncovered_list, self.uncovered_hint)
        stale = nodes.is_stale(ns, self.graph)
        self.stale.set_messages(
            "도면 그래프가 바뀌었습니다(저장본 %s → 현재 %s). '다시 제안'으로 새로 만들거나 확정 해제 뒤 고치세요."
            % (ns.get("graph_version"), self.graph.get("graph_version")) if stale else None)
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
        row = next((i for i, n in enumerate(ns["nodes"]) if n["node_id"] == keep), 0 if ns["nodes"] else -1)
        self.node_list.setCurrentRow(row)
        self._fill_members()
        self._fill_owner()
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
        unc = [self.local_map[e] for e in self._coverage()["uncovered"] if e in self.local_map]
        self.app.webview.set_segments(groups, unc)

    def _fill_members(self):
        self.member_list.clear()
        n = self.current_node()
        for eid in (n["members"] if n else []):
            node = self.entities.get(eid)
            it = QListWidgetItem("%s · %s" % (entity_label(node), (node or {}).get("kind") or "그래프에 없음"))
            it.setData(Qt.UserRole, eid)
            self.member_list.addItem(it)
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
            it = QListWidgetItem(seg_icon(index[nid], nid), self._node(nid)["name"])
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
        for i in range(self.node_list.count()):
            if self.node_list.item(i).data(Qt.UserRole) == node_id:
                self.node_list.setCurrentRow(i)
                return True
        return False

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
        self._paint()
        self._update_buttons()
        self._publish_node()

    def _member_selection(self):
        self._update_buttons()
        ids = self.selected_members()
        if len(ids) == 1 and ids[0] in self.local_map:
            self.app.webview.focus(self.local_map[ids[0]])

    def _owner_clicked(self, item):
        nid = item.data(Qt.UserRole)
        if nid:
            self.select_node(nid)

    def on_node(self, sel):
        """도면에서 누른 구성요소. 속한 구간이 하나면 그 구간과 구성요소를 고르고, 없으면 미포함 탭, 여럿이면 속한 구간 탭을 연다."""
        if not self.node_set:
            return
        eid = sel.get("entity_id")
        if eid not in self.entities:
            eid = self.entity_of_local.get(sel.get("local_id"))
        if eid not in self.entities:
            return
        self.picked_entity = eid
        self._fill_owner()
        owners = nodes.nodes_of(self.node_set, eid)
        if len(owners) == 1:
            self.select_node(owners[0])
            for i in range(self.member_list.count()):
                it = self.member_list.item(i)
                it.setSelected(it.data(Qt.UserRole) == eid)
        for i in range(self.uncovered_list.count()):
            it = self.uncovered_list.item(i)
            it.setSelected(it.data(Qt.UserRole) == eid)
        self.tabs.setCurrentIndex(0 if len(owners) == 1 else 1 if not owners else 2)
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

    def _save(self):
        """디스크에 쓴 경우에만 True. 실패하면 화면은 이전 집합으로 되돌린다(확정이 저장된 것처럼 보이지 않게)."""
        try:
            nodes.save(self.node_set)
        except OSError as exc:
            self.app.log_error("검토구간 저장 실패", exc)
            self.msg.setText("저장 실패 — 변경을 적용하지 않음: %s" % exc)
            return False
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
        return self._replace(nodes.propose(self.graph), done="다시 제안했습니다")

    def confirm(self, reviewer=None):
        reviewer = reviewer or self.app.reviewer_name()
        if not reviewer:
            name, ok = QInputDialog.getText(self, "검토자 이름", "확정하려면 검토자 이름이 필요합니다(설정에 저장).")
            if not ok or not name.strip():
                return False
            self.app.set_reviewer_name(name.strip())
            reviewer = name.strip()
        return self._apply(lambda s: nodes.confirm(s, self.graph, reviewer), done="구간을 확정했습니다")

    def reopen(self):
        return self._apply(nodes.reopen, done="확정을 해제했습니다")

    def open_in_results(self):
        nid = self.current_node_id()
        if self.name and nid:
            self.app.open_results_for(self.name, nid)
