"""주 창 (기획서/인터페이스.md §2.1, 디자인/시안/완성본 B안 + A안 단계 표시). 웹뷰는 하나를 공유한다.

틀: 어두운 제목줄(로고·메뉴·현재 위치·검토자) / 왼쪽 단계 레일(①~⑤, 완료 ✓·현재·남음) / 탐색기 트리 / 화면 / 상태줄.
화면 번호(self.screens·go()의 index)는 추가 순서를 유지한다: 0 ①, 1 ②, 2 이전 ④, 3 이전 ⑤, 4 ③, 5 ④, 6 ⑤.
레일 단계는 STAGES, 보기 메뉴는 STEP_ORDER 순서로 보인다."""

import os

from PySide6.QtCore import QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenuBar, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                               QTabBar, QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import palette, related, tokens
from hazop.app.related_panel import RelatedPanel
from hazop.app.screens.analysis import AnalysisScreen
from hazop.app.screens.knowledge import KnowledgeScreen
from hazop.app.screens.register import RegisterScreen
from hazop.app.screens.results import ResultsScreen
from hazop.app.screens.review import ReviewScreen
from hazop.app.screens.study import StudyNodesScreen, seg_icon
from hazop.app.screens.viewer import ViewerScreen
from hazop.app.settings_dialog import SettingsDialog
from hazop.app.webview import HazopWebView
from hazop.app.widgets import VALIDATION_LABELS, Chip, TaskRunner, Toast, esc, kst_text, write_log
from hazop.study.apikey import KEY_FILE_NAME, KeyStore

APP_NAME = "HAZOP 분석 도구"
APP_VERSION = "0.1.0"
STEPS = ("① 자료 등록", "② 도면 추출", "고정 응답 분석(이전 ④)", "설계보완·확정(이전 ⑤)", "③ 지식그래프", "④ 검토구간",
         "⑤ 분석 결과")  # 화면 index 순
STEP_ORDER = (0, 1, 4, 5, 6, 2, 3)  # 보기 메뉴 순서
# 레일 단계: (번호, 짧은 이름, 화면 index들). 첫 화면이 레일 클릭 대상이고 그 화면의 is_done()이 완료(✓)를 정한다.
STAGES = (("1", "등록", (0,)), ("2", "추출", (1,)), ("3", "그래프", (4,)), ("4", "구간", (5,)), ("5", "결과", (6, 2, 3)))
# 탐색기 묶음: (이름, 단계 번호). 자식은 그 단계 첫 화면의 explorer_items() [(글자, key)]
EXPLORER_GROUPS = (("자료", 0), ("지식그래프", 2), ("검토구간", 3), ("권고", 4))
RAIL_W = 52
EXPLORER_MIN, EXPLORER_MAX, EXPLORER_VW = 200, 260, 0.14  # 탐색기 clamp(200px, 14vw, 260px), 끌어서 조절
RELATED_MIN, RELATED_MAX, RELATED_VW = 264, 340, 0.20     # 관련 항목 clamp(264px, 20vw, 340px)
RELATED_DEFAULT = (6,)  # 관련 항목을 처음부터 펴 두는 화면(⑤). ④·③은 자기 오른쪽 패널을 쓴다
# 단축키 표(? 또는 F1). (키, 설명). 화면별 키는 각 화면의 commands()가 더한다
GLOBAL_KEYS = (("Ctrl+P", "명령 팔레트(구간 #, 구성요소 @, 명령 >)"), ("Ctrl+1 ~ Ctrl+5", "단계 ①~⑤로 이동"),
               ("Alt+← / Alt+→", "뒤로 / 앞으로"), ("Ctrl+Z", "방금 한 동작 실행 취소(토스트가 있을 때)"),
               ("Ctrl+Shift+E", "탐색기 필터"), ("Ctrl+Alt+B", "관련 항목 패널 접기/펴기"),
               ("Ctrl+T / Ctrl+W", "새 탭 / 탭 닫기"), ("Ctrl+Tab", "다음 탭"), ("Ctrl+\\", "오른쪽 분할 켜기/끄기"),
               ("Ctrl+Enter (팔레트)", "새 탭으로 열기"), ("?  또는  F1", "단축키 표"))
HISTORY_MAX = 50
DRAWING_SCREENS = (1, 5, 6)  # 도면 선택(combo)이 있는 화면 ②④⑤: 지금 도면을 함께 따른다
EXPLORER_OPEN_MAX = 30  # 이보다 항목이 많은 묶음(권고 등)은 접어서 연다
EXPLORER_FOLDED = (3,)  # 이전 ⑤ 결정 폼은 1366에서 탐색기 폭(200)이면 가로가 6px 모자라 탐색기를 접는다


def clamp_width(total, lo, hi, vw):
    return int(max(lo, min(hi, total * vw)))


def stage_icon(num, state, size=24):
    """레일 단계 원 번호(U-05). 완료는 초록 채움 + 오른쪽 위 ✓ 배지, 현재는 밝은 원, 남음은 테두리만. 번호는 늘 보인다."""
    pm = QPixmap(size + 6, size + 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(1, 1, size - 2, size - 2)
    if state == "done":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tokens.c("ok")))
        ink = tokens.c("on-fill")
    elif state == "now":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tokens.c("nav-active-ink")))
        ink = tokens.c("nav-bg")
    else:
        p.setPen(QColor(tokens.c("nav-muted")))
        p.setBrush(Qt.NoBrush)
        ink = tokens.c("nav-muted")
    p.drawEllipse(r)
    f = QFont(tokens.FONT_FAMILY)
    f.setPixelSize(tokens.FONT_SIZE["sm"])
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(ink))
    p.drawText(r, Qt.AlignCenter, num)
    if state == "done":
        b = QRectF(size - 6, 0, 11, 11)
        p.setPen(QColor(tokens.c("nav-bg")))
        p.setBrush(QColor(tokens.c("nav-bg")))
        p.drawEllipse(b)
        f.setPixelSize(9)
        p.setFont(f)
        p.setPen(QColor(tokens.c("rail-check")))
        p.drawText(b, Qt.AlignCenter, "✓")
    p.end()
    return QIcon(pm)

# 도움말 > 버전·데이터 위치(패키징 W10, D18): 제3자 고지 위치와 법무 검토 전 안내
LICENSE_NOTE = "LGPL 등 제3자 라이선스 의무의 법무 검토 전이므로 내부용으로만 사용하십시오."


class WhereLabel(QLabel):
    """헤더 현재 위치 라벨: 폭이 모자라 잘리면 전체 문장을 툴팁으로 보여 준다."""

    full_text = ""

    def set_where(self, rich, plain):
        self.full_text = plain
        self.setText(rich)
        self._tip()

    def _tip(self):
        self.setToolTip(self.full_text if self.sizeHint().width() > self.width() else "")

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._tip()


class MainWindow(QMainWindow):
    def __init__(self, settings_path=None, ask_reviewer=True, debug=False):
        super().__init__()
        self.debug = debug  # True면 상태줄에 Python↔웹 메시지 등 개발자 정보를 보여 준다(--debug)
        self.settings_path = settings_path
        self.settings = paths.load_settings(settings_path)
        self.api_keys = KeyStore(os.path.join(os.path.dirname(settings_path or paths.settings_path()), KEY_FILE_NAME))
        self._key_dialog = None
        self.run_ctx = None
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 860)
        self.setStyleSheet(tokens.qss())
        self.tasks = TaskRunner(self)
        self.tasks.started.connect(self._task)
        self.tasks.finished.connect(lambda _l: self._task(""))
        self.webview = HazopWebView()
        self.webview.bridge.nodeSelected.connect(self._node_selected)
        self.webview.bridge.highlightResultFor.connect(self._highlight_result)
        self.webview.bridge.linkSelected.connect(self._link_selected)
        self.webview.bridge.algorithmRequested.connect(self._algorithm_requested)
        self.webview.bridge.editPick.connect(self._edit_pick)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._rail())
        self.split = QSplitter(Qt.Horizontal)
        self.split.setObjectName("shell_split")
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(1)
        self.split.addWidget(self._explorer_box())
        self.center = QWidget()
        cv = QVBoxLayout(self.center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._tab_row())
        self.panes = QSplitter(Qt.Horizontal)
        self.panes.setChildrenCollapsible(False)
        self.stack = QStackedWidget()
        self.panes.addWidget(self.stack)
        self.right_pane = QWidget()
        self.right_pane.setObjectName("right_pane")
        QVBoxLayout(self.right_pane).setContentsMargins(0, 0, 0, 0)
        self.right_pane.hide()
        self.panes.addWidget(self.right_pane)
        cv.addWidget(self.panes, 1)
        self.split.addWidget(self.center)
        self.tabs = []            # 탭마다 {"index": 화면, "drawing", "sel"}(U-03)
        self._tab_switching = False
        self.split_index = None   # 오른쪽 분할에 옮겨 둔 화면 index
        self._placeholder = None
        self.related = RelatedPanel(self.open_target)
        self.split.addWidget(self.related)
        self.split.setStretchFactor(1, 1)
        body.addWidget(self.split, 1)
        cl.addLayout(body, 1)
        self.setCentralWidget(central)
        self.drawing = None       # 지금 보는 도면(추출 이름). ②④⑤ 도면 선택이 함께 따른다(U-04)
        self.selection = None     # 관련 항목 패널의 기준(set_selection)
        self._index = None        # ((도면, 세대), related.DrawingIndex) 캐시
        self._index_gen = 0
        self.related_shown = {i: i in RELATED_DEFAULT for i in range(len(STEPS))}
        self.history, self.history_pos = [], -1  # 뒤로·앞으로(Alt+←/→)
        self.recent = []          # 명령 팔레트 최근 항목 ident
        self.screens = [RegisterScreen(self), ViewerScreen(self), AnalysisScreen(self), ReviewScreen(self),
                        KnowledgeScreen(self), StudyNodesScreen(self), ResultsScreen(self)]
        for s in self.screens:
            self.stack.addWidget(s)
            if self.stack.count() - 1 in DRAWING_SCREENS:
                s.combo.currentTextChanged.connect(lambda _t, scr=s: self._drawing_changed(scr))
        self.screens[2].review_requested.connect(self.review_candidate)
        self._status_bar()
        self._menus()
        self._shortcuts()
        self.toast_box = Toast(central)
        self._size_panels()
        self.go(0)
        if ask_reviewer and not self.reviewer_name():
            name, ok = QInputDialog.getText(self, "검토자 이름", "처음 실행입니다. 검토자 이름을 입력하세요(설정에 저장).")
            if ok and name.strip():
                self.set_reviewer_name(name.strip())

    # ------------------------------------------------------------ 틀
    def _header(self):
        h = QWidget()
        h.setObjectName("header")
        h.setFixedHeight(32)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(4)
        logo = QLabel("HAZOP")
        logo.setObjectName("logo")
        lay.addWidget(logo)
        self.menu_bar = QMenuBar()
        self.menu_bar.setObjectName("titlemenu")
        lay.addWidget(self.menu_bar, 0, Qt.AlignVCenter)
        self.where_label = WhereLabel("")
        self.where_label.setObjectName("where")
        self.where_label.setTextFormat(Qt.RichText)
        self.where_label.setMinimumWidth(80)  # 긴 위치 글자에도 1366 폭 유지: 넘치면 잘리고 툴팁
        lay.addWidget(self.where_label, 1)
        self.cmd_box = QPushButton("⌕  구간·구성요소·명령 찾기")
        self.cmd_box.setObjectName("cmdbox")
        self.cmd_box.setToolTip("명령 팔레트 (Ctrl+P)")
        self.cmd_box.setFixedWidth(340)
        self.cmd_box.setCursor(Qt.PointingHandCursor)
        self.cmd_box.clicked.connect(lambda: self.open_palette())
        lay.addWidget(self.cmd_box)
        kbd = QLabel("Ctrl+P")
        kbd.setObjectName("kbd_nav")
        lay.addWidget(kbd)
        lay.addStretch(1)
        self.reviewer_label = QLabel("")
        self.reviewer_label.setObjectName("reviewer")
        lay.addWidget(self.reviewer_label)
        return h

    def _rail(self):
        """단계 레일. step_buttons[i]는 화면 i마다 하나(같은 QButtonGroup). 보이는 것은 단계 첫 화면 버튼 5개다."""
        self.rail = QWidget()
        self.rail.setObjectName("rail")
        self.rail.setFixedWidth(RAIL_W)
        lay = QVBoxLayout(self.rail)
        lay.setContentsMargins(2, 6, 2, 6)
        lay.setSpacing(2)
        self.step_group = QButtonGroup(self)
        self.step_buttons = []
        for i, label in enumerate(STEPS):
            b = QToolButton(self.rail)
            b.setObjectName("step")
            b.setText(label)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(30, 26))
            b.setCheckable(True)
            b.setFixedWidth(RAIL_W - 4)
            b.setToolTip(label)
            b.setAccessibleName(label)
            b.clicked.connect(lambda _=False, k=i: self.go(k))
            self.step_group.addButton(b)
            self.step_buttons.append(b)
            b.hide()
        for k, (_, _, idxs) in enumerate(STAGES):
            b = self.step_buttons[idxs[0]]
            b.setToolTip("%s (Ctrl+%d)" % (STEPS[idxs[0]], k + 1))
            b.show()
            lay.addWidget(b)
        lay.addStretch(1)
        return self.rail

    def stage_of(self, index):
        return next(k for k, (_, _, idxs) in enumerate(STAGES) if index in idxs)

    def refresh_stages(self):
        """레일 단계 표시(U-05)와 탐색기를 다시 계산한다. done = 단계 첫 화면의 is_done(), now = 현재 화면의 단계.
        글자는 짧은 이름, 번호는 원 아이콘에 늘 남고 완료는 ✓ 배지가 붙는다(state의 done 속성)."""
        now = self.stage_of(self.stack.currentIndex())
        for k, (num, short, idxs) in enumerate(STAGES):
            done = bool(getattr(self.screens[idxs[0]], "is_done", lambda: False)())
            b = self.step_buttons[idxs[0]]
            state = "now" if k == now else "done" if done else "todo"
            b.setText(short)
            b.setIcon(stage_icon(num, "done" if done else state))
            b.setProperty("state", state)
            b.setProperty("done", done)
            b.setAccessibleDescription("완료" if done else "")
            b.style().unpolish(b)
            b.style().polish(b)
        self._refresh_explorer()
        self._refresh_status()

    # ------------------------------------------------------------ 탐색기(U-04)
    def _explorer_box(self):
        self.explorer_panel = QWidget()
        self.explorer_panel.setObjectName("explorer_box")
        v = QVBoxLayout(self.explorer_panel)
        v.setContentsMargins(6, 6, 0, 0)
        v.setSpacing(4)
        self.explorer_filter = QLineEdit()
        self.explorer_filter.setObjectName("explorer_filter")
        self.explorer_filter.setPlaceholderText("⌕ 필터 (Ctrl+Shift+E)")
        self.explorer_filter.setClearButtonEnabled(True)
        self.explorer_filter.textChanged.connect(self._apply_filter)
        v.addWidget(self.explorer_filter)
        self.explorer = QTreeWidget()
        self.explorer.setObjectName("explorer")
        self.explorer.setColumnCount(2)
        self.explorer.setHeaderHidden(True)
        self.explorer.setIndentation(10)
        self.explorer.setIconSize(QSize(10, 10))
        self.explorer.header().setStretchLastSection(False)
        self.explorer.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.explorer.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.explorer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.explorer.setTextElideMode(Qt.ElideRight)
        self.explorer.itemClicked.connect(self._explorer_clicked)
        v.addWidget(self.explorer, 1)
        self.explorer_wanted = True  # 보기 메뉴로 접고 편다. 창이 좁으면 자동으로 숨긴다(_fit_explorer)
        return self.explorer_panel

    def _explorer_groups(self):
        """[(이름, 화면 index, [(글자, key, 오른쪽 글자, 아이콘)], 빈 안내)]. 검토구간·권고는 지금 도면 기준."""
        idx = self.index()
        dwg = idx.drawing_number if idx and idx.graph else None
        reg = list(self.screens[0].explorer_items())
        kgs = list(self.screens[4].explorer_items())
        groups = [("자료", 0, [(t, k, "", None) for t, k in reg], "① 자료 등록에서 도면·문서를 올리세요"),
                  ("지식그래프", 4, [(t, k, "", None) for t, k in kgs], "① 등록과 추출이 끝나면 자동으로 만듭니다")]
        study = self.screens[5]
        live = study.node_set if study.node_set and study.name == self.drawing else None
        ns = live or (idx.node_set if idx else None)
        items = []
        for i, n in enumerate((ns or {}).get("nodes", [])):
            usable = idx is not None and (live is None or live.get("status") == "confirmed")  # 결과는 확정본에만 있다
            u = idx.unreviewed(n["node_id"]) if usable else 0
            items.append(("%s %s" % (n["node_id"], n["name"]), n["node_id"], "미%d" % u if u else "",
                          seg_icon(i, "")))
        groups.append(("검토구간" + (" · %s" % dwg if dwg else ""), 5, items,
                       "④ 검토구간에서 구간을 제안·확정합니다" if dwg else "도면을 고르면 그 도면의 구간이 보입니다"))
        recs = []
        if idx and idx.results:
            for c in idx.results["cells"]:
                for e in c.get("entries") or []:
                    if e.get("recommendation") and e.get("status") != "rejected":
                        d = idx.deviation(c["deviation_id"])
                        recs.append(("%s × %s · %s" % (c["node_id"], d["label"] if d else c["deviation_id"],
                                                        e["recommendation"]),
                                     (c["node_id"], c["deviation_id"]), "", None))
        groups.append(("권고", 6, recs, "AI 분석 후 권고가 모입니다"))
        return groups

    def _refresh_explorer(self):
        """내용이 같으면 다시 만들지 않는다(선택 유지, 항목 클릭 처리 중 항목 삭제 방지)."""
        groups = self._explorer_groups()
        sig = [(n, i, [(t, k, r) for t, k, r, _ in its], e) for n, i, its, e in groups]
        if sig != getattr(self, "_explorer_sig", None):
            self._explorer_sig = sig
            self.explorer.clear()
            muted = QColor(tokens.c("muted"))
            for name, idx, items, hint in groups:
                grp = QTreeWidgetItem([name, str(len(items))])
                f = grp.font(0)
                f.setBold(True)
                grp.setFont(0, f)
                grp.setForeground(1, muted)
                grp.setFlags(Qt.ItemIsEnabled)
                grp.setToolTip(0, name)
                for text, key, right, icon in items:
                    child = QTreeWidgetItem([text, right])
                    child.setData(0, Qt.UserRole, (idx, key))
                    child.setToolTip(0, text)
                    child.setForeground(1, muted)
                    if icon is not None:
                        child.setIcon(0, icon)
                    grp.addChild(child)
                if not items:
                    empty = QTreeWidgetItem([hint])
                    empty.setFlags(Qt.NoItemFlags)
                    empty.setForeground(0, muted)
                    f = empty.font(0)
                    f.setItalic(True)
                    empty.setFont(0, f)
                    empty.setData(0, Qt.UserRole + 1, "hint")
                    empty.setToolTip(0, hint)
                    grp.addChild(empty)
                self.explorer.addTopLevelItem(grp)
                grp.setExpanded(len(items) <= EXPLORER_OPEN_MAX)
            self._apply_filter()
        self._mark_explorer_current()

    def _apply_filter(self):
        q = self.explorer_filter.text().strip()
        for g in range(self.explorer.topLevelItemCount()):
            grp = self.explorer.topLevelItem(g)
            shown = total = 0
            for c in range(grp.childCount()):
                ch = grp.child(c)
                hint = ch.data(0, Qt.UserRole + 1) == "hint"
                hide = bool(q) and (hint or palette.fuzzy_score(q, ch.text(0)) is None)
                ch.setHidden(hide)
                total += not hint
                shown += not hide and not hint
            grp.setText(1, str(shown if q else total))

    def _mark_explorer_current(self):
        """지금 화면이 연 대상(④ 구간·⑤ 칸의 구간)을 탐색기에서 선택해 왼쪽 파랑 선으로 보인다."""
        cur = self.stack.currentIndex()
        key = None
        if cur == 5:
            key = (5, self.screens[5].current_node_id())
        elif cur == 6 and self.screens[6].cell:
            key = (5, self.screens[6].cell[0])
        self.explorer.blockSignals(True)
        self.explorer.clearSelection()
        for g in range(self.explorer.topLevelItemCount()):
            grp = self.explorer.topLevelItem(g)
            for c in range(grp.childCount()):
                ch = grp.child(c)
                if key is not None and ch.data(0, Qt.UserRole) == key:
                    ch.setSelected(True)
        self.explorer.blockSignals(False)

    def _explorer_clicked(self, item, _col=0):
        target = item.data(0, Qt.UserRole)
        if not target:
            return
        idx, key = target
        if idx == 6:
            self.open_target({"kind": "cell", "drawing": self.drawing, "node_id": key[0], "deviation_id": key[1]})
            return
        if idx == 5:
            self.open_target({"kind": "node", "drawing": self.drawing, "node_id": key})
            return
        if not self.go(idx):
            return
        h = getattr(self.screens[idx], "open_item", None)
        if h:
            h(key)

    def toggle_explorer(self):
        self.explorer_wanted = not self.explorer_wanted
        self._fit_explorer()

    def focus_explorer_filter(self):
        if not self.explorer_wanted:
            self.explorer_wanted = True
            self._fit_explorer()
        self.explorer_filter.setFocus()
        self.explorer_filter.selectAll()

    def _fit_explorer(self):
        """탐색기는 원할 때, 그리고 창 폭이 레일 + 탐색기 + 화면 최소 폭 이상일 때만 보인다(1366 폭 유지).
        관련 항목은 화면마다 기억한 펼침 상태를 따른다."""
        need = RAIL_W + EXPLORER_MIN + self.stack.minimumSizeHint().width()
        ex, rel = self.explorer_panel.isHidden(), self.related.isHidden()
        self.explorer_panel.setVisible(self.explorer_wanted and self.width() >= need
                                       and self.stack.currentIndex() not in EXPLORER_FOLDED)
        self.related.setVisible(self.related_shown.get(self.stack.currentIndex(), False))
        if (ex, rel) != (self.explorer_panel.isHidden(), self.related.isHidden()):
            self._size_panels()

    def _size_panels(self):
        """처음과 창 크기가 바뀔 때: 탐색기·관련 항목 폭을 명세의 clamp 값으로 맞춘다(가운데가 나머지)."""
        w = self.width()
        ew = clamp_width(w, EXPLORER_MIN, EXPLORER_MAX, EXPLORER_VW)
        rw = clamp_width(w, RELATED_MIN, RELATED_MAX, RELATED_VW)
        self.explorer_panel.setMinimumWidth(160)
        self.related.setMinimumWidth(220)
        ew = 0 if self.explorer_panel.isHidden() else ew
        rw = 0 if self.related.isHidden() else rw
        self.split.setSizes([ew, max(200, w - RAIL_W - ew - rw), rw])

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "split"):
            self._size_panels()
            self._fit_explorer()
        if hasattr(self, "toast_box") and self.toast_box.isVisible():
            self.toast_box.place()

    # ------------------------------------------------------------ 상태 표시줄(U-06)
    def _status_bar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.drawing_label = QLabel("")
        self.count_label = QLabel("")
        self.chip_valid = Chip("결과 검증 —")
        self.chip_valid.hide()  # 열린 실행(이전 ④⑤)이 있을 때만
        self.task_label = QLabel("")
        self.saved_label = QLabel("")
        self.msg_label = QLabel("")
        self.msg_label.setObjectName("muted")
        self.keys_label = QLabel("Ctrl+P 명령 · ? 단축키")
        self.keys_label.setObjectName("muted")
        for w in (self.drawing_label, self.count_label, self.chip_valid):
            sb.addWidget(w)
        for w in (self.msg_label, self.task_label, self.saved_label, self.keys_label):
            sb.addPermanentWidget(w)
        self._update_reviewer_label()

    def _refresh_status(self):
        """왼쪽은 지금 도면과 개수, 오른쪽은 메시지·진행·저장·단축키 안내. 값이 없는 칸은 숨긴다."""
        if not hasattr(self, "count_label"):
            return
        idx = self.index()
        dwg = idx.drawing_number if idx and idx.graph else None
        self.drawing_label.setText(dwg or "")
        parts = []
        if idx and idx.node_set:
            parts.append("구간 %d%s" % (len(idx.node_set["nodes"]),
                                       "" if idx.node_set.get("status") == "confirmed" else " (제안)"))
        if idx and idx.results:
            summ = idx.summary()
            parts.append("미검토 %d" % sum(s.get("unreviewed") or 0 for row in summ.values() for s in row.values()))
            failed = sum(1 for c in idx.results["cells"] if (c.get("ai_run") or {}).get("status") == "failed")
            if failed:
                parts.append("실패 %d" % failed)
        self.count_label.setText("   ".join(parts))
        for lab in (self.drawing_label, self.count_label, self.task_label, self.saved_label, self.msg_label):
            lab.setVisible(bool(lab.text()))

    def _menus(self):
        m = self.menu_bar
        f = m.addMenu("파일")
        f.addAction("구간 열기…", self._open_region)
        f.addAction("실행 열기…", self._open_run_dialog)
        f.addAction("Excel 내보내기…", lambda: (self.go(3), self.screens[3].ask_excel()))
        f.addSeparator()
        f.addAction("설정(검토자 이름)…", self._ask_reviewer)
        f.addAction("API 키 설정…", self.open_key_settings)
        f.addSeparator()
        f.addAction("끝내기", self.close)
        v = m.addMenu("보기")
        v.addAction("명령 팔레트\tCtrl+P", self.open_palette)
        v.addSeparator()
        for i in STEP_ORDER:
            v.addAction(STEPS[i], lambda k=i: self.go(k))
        v.addSeparator()
        v.addAction("뒤로\tAlt+←", self.back)
        v.addAction("앞으로\tAlt+→", self.forward)
        v.addAction("탐색기 접기/펴기", self.toggle_explorer)
        v.addAction("관련 항목 접기/펴기\tCtrl+Alt+B", self.toggle_related)
        v.addAction("도면 보기", lambda: self.webview.set_view("drawing"))
        v.addAction("그래프 보기", lambda: self.webview.set_view("graph"))
        v.addAction("웹 속성 패널 숨기기/보이기", lambda: self.webview.set_mode(
            not self.webview.hide_panel, self.webview.hide_graph, self.webview.hide_status))
        hm = m.addMenu("도움말")
        hm.addAction("단축키\t?", self.show_shortcuts)
        hm.addAction("버전·데이터 위치", self._about)

    # ------------------------------------------------------------ 단축키(U-02)·팔레트(U-01)
    def _shortcuts(self):
        """창 전체 단축키. 화면별 한 글자 키(A·R·J·M…)는 각 화면이 자기 범위(WidgetWithChildrenShortcut)로 단다.
        글 입력칸에 초점이 있으면 글자 키는 입력이 먼저 받는다(Qt ShortcutOverride)."""
        keys = [("Ctrl+P", self.open_palette), ("Ctrl+Shift+P", lambda: self.open_palette(">")),
                ("Ctrl+Z", self.undo), ("Ctrl+Alt+B", self.toggle_related),
                ("Ctrl+Shift+E", self.focus_explorer_filter), ("Alt+Left", self.back), ("Alt+Right", self.forward),
                ("?", self.show_shortcuts), ("F1", self.show_shortcuts),
                ("Ctrl+T", self.new_tab), ("Ctrl+W", lambda: self.close_tab(self.tab_bar.currentIndex())),
                ("Ctrl+Tab", lambda: self.cycle_tab(1)), ("Ctrl+Shift+Tab", lambda: self.cycle_tab(-1)),
                ("Ctrl+\\", self.toggle_split)]
        for k, (_, _, idxs) in enumerate(STAGES):
            keys.append(("Ctrl+%d" % (k + 1), lambda i=idxs[0]: self.go(i)))
        self.shortcuts = {}
        for seq, fn in keys:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(fn)
            self.shortcuts[seq] = sc

    def undo(self):
        """Ctrl+Z: 토스트에 실행 취소가 남아 있으면 그것, 아니면 지금 화면의 undo(② 편집 등)."""
        if self.toast_box.undo is not None:
            return self.toast_box.run_undo()
        h = getattr(self.current_screen(), "undo", None)
        if h:
            h()
            return True
        return False

    def screen_commands(self, index):
        h = getattr(self.screens[index], "commands", None)
        return list(h()) if h else []

    def palette_items(self):
        """명령 팔레트 항목: 명령(창 + 모든 화면), 지금 도면의 구성요소·구간·칸, 지식그래프."""
        items = []
        for k, (_, _, idxs) in enumerate(STAGES):
            items.append(palette.Item("command", "이동: %s" % STEPS[idxs[0]], "", "Ctrl+%d" % (k + 1),
                                      lambda _n, i=idxs[0]: self.go(i)))
        for label, keys, fn in (("뒤로", "Alt+←", self.back), ("앞으로", "Alt+→", self.forward),
                                ("관련 항목 접기/펴기", "Ctrl+Alt+B", self.toggle_related),
                                ("탐색기 접기/펴기", "", self.toggle_explorer),
                                ("탐색기 필터", "Ctrl+Shift+E", self.focus_explorer_filter),
                                ("단축키 표", "?", self.show_shortcuts), ("API 키 설정…", "", self.open_key_settings),
                                ("새 탭", "Ctrl+T", self.new_tab), ("오른쪽 분할 켜기/끄기", "Ctrl+\\", self.toggle_split),
                                ("검토자 이름 설정…", "", self._ask_reviewer)):
            items.append(palette.Item("command", label, "", keys, lambda _n, f=fn: f()))
        for _num, short, idxs in STAGES:
            for i in idxs:
                for label, keys, fn in self.screen_commands(i):
                    items.append(palette.Item("command", "%s: %s" % (short, label), STEPS[i], keys,
                                              lambda _n, i=i, f=fn: (self.stack.currentIndex() == i or self.go(i)) and f()))
        idx = self.index()
        if idx and idx.graph:
            dw = self.drawing
            for eid, text, kind in idx.components():
                items.append(palette.Item("component", text, "%s · %s" % (kind, idx.drawing_number), "",
                                          lambda nt, e=eid: self.open_target(
                                              {"kind": "component", "drawing": dw, "entity_id": e, "open": "drawing"}, nt),
                                          ("component", dw, eid)))
            for n in (idx.node_set or {}).get("nodes", []):
                items.append(palette.Item("node", "%s %s" % (n["node_id"], n["name"]),
                                          "구성요소 %d · %s" % (len(n["members"]), idx.drawing_number), "",
                                          lambda nt, nid=n["node_id"]: self.open_target(
                                              {"kind": "node", "drawing": dw, "node_id": nid}, nt),
                                          ("node", dw, n["node_id"])))
            for node, dev, s in idx.cells():
                text, tail = related.cell_text(idx, node, dev, s)
                items.append(palette.Item("cell", "%s %s" % (text, node["name"]), tail, "",
                                          lambda nt, a=node["node_id"], b=dev["deviation_id"]: self.open_target(
                                              {"kind": "cell", "drawing": dw, "node_id": a, "deviation_id": b}, nt),
                                          ("cell", dw, node["node_id"], dev["deviation_id"])))
        for text, path in self.screens[4].explorer_items():
            items.append(palette.Item("graph", "그래프: %s" % text, "", "",
                                      lambda _n, p=path: self.go(4) and self.screens[4].open_item(p), ("graph", path)))
        return items

    def open_palette(self, query=""):
        def chosen(item, new_tab):
            ident = item.ident()
            self.recent = [ident] + [r for r in self.recent if r != ident][:19]
            if item.open:
                item.open(new_tab)
        self.palette_dialog = palette.PaletteDialog(self, self.palette_items(), self.recent, chosen, query)
        self.palette_dialog.show()
        self.palette_dialog.edit.setFocus()
        return self.palette_dialog

    def shortcut_rows(self):
        rows = list(GLOBAL_KEYS)
        cur = self.stack.currentIndex()
        rows += [(keys, "%s · %s" % (STEPS[cur], label)) for label, keys, _fn in self.screen_commands(cur) if keys]
        return rows

    def show_shortcuts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("단축키")
        lay = QVBoxLayout(dlg)
        rows = self.shortcut_rows()
        t = QTableWidget(len(rows), 2)
        t.setHorizontalHeaderLabels(["키", "동작"])
        t.verticalHeader().hide()
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        for r, (k, label) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(k))
            t.setItem(r, 1, QTableWidgetItem(label))
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(t)
        dlg.resize(520, 420)
        self.shortcut_dialog = dlg
        dlg.show()
        return dlg

    # ------------------------------------------------------------ 탭·분할(U-03)
    def _tab_row(self):
        row = QWidget()
        row.setObjectName("tabrow")
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 0, 6, 0)
        h.setSpacing(4)
        self.tab_bar = QTabBar()
        self.tab_bar.setObjectName("tabs")
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setElideMode(Qt.ElideRight)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setDocumentMode(True)
        self.tab_bar.currentChanged.connect(self._tab_activated)
        self.tab_bar.tabCloseRequested.connect(self.close_tab)
        h.addWidget(self.tab_bar, 1)
        self.split_btn = QPushButton("분할")
        self.split_btn.setObjectName("tool")
        self.split_btn.setCheckable(True)
        self.split_btn.setToolTip("오른쪽 분할 (Ctrl+\\): 도면이나 구간 옆에 결과를 함께 봅니다")
        self.split_btn.clicked.connect(lambda: self.toggle_split())
        h.addWidget(self.split_btn)
        return row

    def _dirty(self, index):
        scr = self.screens[index]
        session = getattr(scr, "session", None)
        return bool(getattr(session, "dirty", False) or getattr(scr, "_unsaved", False))

    def tab_title(self, tab):
        i = tab["index"]
        k = self.stage_of(i)
        name = STAGES[k][1] if STAGES[k][2][0] == i else STEPS[i]
        dwg = tab.get("drawing") if i in DRAWING_SCREENS else None
        sel = tab.get("sel") or {}
        what = sel.get("node_id") if i in (5, 6) and sel.get("node_id") else None
        return "%s%s%s%s" % ("● " if self._dirty(i) else "", name, " · %s" % what if what else "",
                              " · %s" % dwg if dwg else "")

    def _refresh_tab_titles(self):
        for k, t in enumerate(self.tabs):
            title = self.tab_title(t)
            if self.tab_bar.tabText(k) != title:
                self.tab_bar.setTabText(k, title)
                self.tab_bar.setTabToolTip(k, title)

    def _tab_follow(self, index):
        """지금 탭이 지금 화면·도면을 가리키게 한다(탭이 없으면 하나 만든다)."""
        if self._tab_switching:
            return
        if not self.tabs:
            self.tabs.append({"index": index, "drawing": self.drawing, "sel": None})
            self._tab_switching = True
            self.tab_bar.addTab("")
            self._tab_switching = False
        t = self.tabs[self.tab_bar.currentIndex()]
        if t["index"] != index or t["drawing"] != self.drawing:
            t.update(index=index, drawing=self.drawing, sel=None)
        self._refresh_tab_titles()

    def new_tab(self):
        """지금 화면을 복제한 새 탭을 열고 그 탭으로 간다."""
        cur = self.stack.currentIndex()
        self.tabs.append({"index": cur, "drawing": self.drawing, "sel": self.selection})
        self._tab_switching = True
        self.tab_bar.addTab("")
        self.tab_bar.setCurrentIndex(len(self.tabs) - 1)
        self._tab_switching = False
        self._tab_prev = len(self.tabs) - 1
        self._refresh_tab_titles()
        return len(self.tabs) - 1

    def _tab_activated(self, k):
        """탭을 누르면 그 탭의 화면·도면·선택(칸·구간)을 다시 연다. 화면이 떠나기를 거절하면 원래 탭으로 돌아간다."""
        if self._tab_switching or not (0 <= k < len(self.tabs)):
            return
        t = dict(self.tabs[k])
        prev = getattr(self, "_tab_prev", 0)
        self._tab_switching = True
        try:
            before = self.drawing
            # 같은 화면에서 도면만 다른 탭이면 go()가 떠나기 확인을 건너뛰므로 여기서 먼저 묻는다(② 저장 안 한 수정)
            ok = t["drawing"] == before or t["index"] != self.stack.currentIndex() or self.can_leave()
            if ok and t["drawing"]:
                self.drawing = t["drawing"]
            ok = ok and self.go(t["index"])
            if not ok:
                self.drawing = before
            sel = t.get("sel") or {}
            if ok and sel.get("kind") == {6: "cell", 5: "node"}.get(t["index"]):
                self.open_target(sel)
        finally:
            self._tab_switching = False
        if not ok:
            self._tab_switching = True
            self.tab_bar.setCurrentIndex(min(prev, len(self.tabs) - 1))
            self._tab_switching = False
            return
        self._tab_prev = k
        self.tabs[k].update(drawing=self.drawing)
        self._refresh_tab_titles()

    def close_tab(self, k):
        """탭 닫기. 마지막 탭은 닫지 않는다. 닫는 탭이 지금 탭이면 옆 탭을 연다."""
        if len(self.tabs) <= 1 or not (0 <= k < len(self.tabs)):
            return False
        current = k == self.tab_bar.currentIndex()
        if current and not self.can_leave():
            return False
        self.tabs.pop(k)
        self._tab_switching = True
        self.tab_bar.removeTab(k)
        self._tab_switching = False
        if current:
            self._tab_activated(self.tab_bar.currentIndex())
        self._tab_prev = self.tab_bar.currentIndex()
        return True

    def cycle_tab(self, step):
        if self.tabs:
            self.tab_bar.setCurrentIndex((self.tab_bar.currentIndex() + step) % len(self.tabs))

    @staticmethod
    def _has_canvas(scr):
        return getattr(scr, "canvas_host", None) is not None

    def _split_uses_canvas(self):
        return self.split_index is not None and self._has_canvas(self.screens[self.split_index])

    def canvas_screen(self):
        """도면 웹뷰의 신호를 받을 화면: 지금 화면이 캔버스가 없고 분할 오른쪽에 있으면 그쪽."""
        cur = self.current_screen()
        if not self._has_canvas(cur) and self._split_uses_canvas():
            return self.screens[self.split_index]
        return cur

    def toggle_split(self, index=None):
        """오른쪽 분할 켜기/끄기. 오른쪽 화면은 index, 없으면 최근에 본 다른 화면(④ ↔ ⑤ 우선).
        도면 웹뷰는 하나라 두 쪽 모두 도면을 쓰는 화면(②·③·④)이면 나누지 않는다."""
        if self.split_index is not None:
            self.unsplit()
            return True
        cur = self.stack.currentIndex()
        if index is None:
            prefer = {5: 6, 6: 5, 1: 6}.get(cur)
            recent = [i for i in reversed(self.history) if i != cur]
            index = prefer if prefer is not None else (recent[0] if recent else 6)
        if index == cur or (self._has_canvas(self.screens[index]) and self._has_canvas(self.screens[cur])):
            self.status_message("도면을 쓰는 화면 둘은 함께 나눌 수 없습니다(도면 보기는 하나).")
            self.split_btn.setChecked(False)
            return False
        scr = self.screens[index]
        # 두 화면의 최소 폭이 창에 들어가야 나눈다. 모자라면 관련 항목·탐색기를 접고, 그래도 모자라면 나누지 않는다
        # (창이 화면 밖으로 넓어지지 않게)
        need = self.stack.currentWidget().minimumSizeHint().width() + scr.minimumSizeHint().width() + 8
        if need > self.width() - RAIL_W:
            self.status_message("창 폭이 모자라 나누지 않았습니다(가운데 폭 %dpx 이상 필요)." % need)
            self.split_btn.setChecked(False)
            return False
        self._split_restore = ((cur, self.related_shown.get(cur, False)), self.explorer_wanted)
        ew = 0 if self.explorer_panel.isHidden() else self.explorer_panel.width()
        rw = 0 if self.related.isHidden() else self.related.width()
        if need > self.width() - RAIL_W - ew - rw:
            self.related_shown[cur] = False
            if need > self.width() - RAIL_W - ew:
                self.explorer_wanted = False
            self._fit_explorer()
        self._placeholder = QWidget()
        self.stack.removeWidget(scr)
        self.stack.insertWidget(index, self._placeholder)
        self.stack.setCurrentIndex(cur)
        self.right_pane.layout().addWidget(scr)
        scr.show()
        self.right_pane.show()
        self.split_index = index
        self.split_btn.setChecked(True)
        self._sync_drawing_into(scr)
        scr.on_enter()
        w = self.panes.width()
        self.panes.setSizes([w // 2, w - w // 2])
        self.refresh_stages()
        return True

    def unsplit(self):
        if self.split_index is None:
            return False
        index, scr = self.split_index, self.screens[self.split_index]
        cur = self.stack.currentIndex()
        self.right_pane.layout().removeWidget(scr)
        self.stack.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._placeholder = None
        self.stack.insertWidget(index, scr)
        self.stack.setCurrentIndex(cur)
        self.right_pane.hide()
        self.split_index = None
        self.split_btn.setChecked(False)
        restore = getattr(self, "_split_restore", None)
        if restore:
            (cur_at_split, related_on), self.explorer_wanted = restore[0], restore[1]
            self.related_shown[cur_at_split] = related_on
            self._split_restore = None
            self._fit_explorer()
        if self.webview.parent() is getattr(scr, "canvas_host", object()) and not self._has_canvas(self.current_screen()):
            self.webview.setParent(None)
            self.webview.hide()
        return True

    # ------------------------------------------------------------ 도면·선택·관련 항목(U-04·U-14)
    def index(self):
        """지금 도면의 읽기 전용 색인(캐시). 저장·화면 이동 때 다시 읽는다."""
        key = (self.drawing, self._index_gen)
        if self._index is None or self._index[0] != key:
            self._index = (key, related.DrawingIndex(self.drawing) if self.drawing else None)
        return self._index[1]

    def invalidate_index(self):
        self._index_gen += 1

    def _drawing_changed(self, scr):
        if scr is not self.current_screen():
            return
        name = scr.combo.currentText() or None
        if name and name != self.drawing:
            self.drawing = name
            self.selection = None
            self.invalidate_index()
            self._tab_follow(self.stack.currentIndex())
            self.refresh_related()
            self._refresh_explorer()
            self._refresh_status()

    def _sync_drawing_into(self, scr):
        """도면을 고르는 화면(②④⑤)에 들어갈 때 지금 도면을 미리 넣어 둔다(on_enter가 그 도면을 그대로 연다)."""
        if self.screens.index(scr) not in DRAWING_SCREENS or not self.drawing:
            return
        combo = scr.combo
        if combo.currentText() != self.drawing:
            combo.blockSignals(True)
            if combo.findText(self.drawing) < 0:
                combo.addItem(self.drawing)
            combo.setCurrentText(self.drawing)
            combo.blockSignals(False)

    def set_selection(self, sel):
        """화면에서 고른 대상(관련 항목 패널의 기준). sel: {"kind": "component"|"node"|"cell", "drawing",
        "entity_id", "node_id", "deviation_id"} 중 해당 키. None이면 선택 없음."""
        self.selection = sel
        if self.tabs and not self._tab_switching:
            self.tabs[self.tab_bar.currentIndex()]["sel"] = sel
            self._refresh_tab_titles()
        self.refresh_related()
        self._mark_explorer_current()

    def refresh_related(self):
        if not self.related.isVisible():
            self._related_stale = True
            return
        self._related_stale = False
        sel = self.selection
        idx = self.index() if sel and sel.get("drawing") in (None, self.drawing) else None
        self.related.show_for(idx, sel)

    def toggle_related(self):
        cur = self.stack.currentIndex()
        self.related_shown[cur] = not self.related_shown.get(cur, False)
        self._fit_explorer()
        if self.related.isVisible() and getattr(self, "_related_stale", True):
            self.refresh_related()

    def open_target(self, sel, new_tab=False):
        """관련 항목·팔레트·탐색기에서 고른 대상을 연다. 구성요소 → ② 도면에서 초점, 구간 → ④, 칸 → ⑤ 워크시트."""
        kind, dwg = sel.get("kind"), sel.get("drawing") or self.drawing
        if new_tab:
            self.new_tab()
        if kind == "component":
            if not self.go(1):
                return False
            self.screens[1].select_drawing(dwg)
            idx = self.index()
            node = (idx.entities if idx else {}).get(sel.get("entity_id")) or {}
            if node.get("local_id"):
                self.webview.focus(node["local_id"])
            self.set_selection(dict(sel, drawing=dwg))
            return True
        if kind == "node":
            if not self.go(5):
                return False
            self.screens[5].select_drawing(dwg)
            return self.screens[5].select_node(sel.get("node_id"))
        if kind == "cell":
            self.open_results_for(dwg, sel.get("node_id"))
            if self.stack.currentIndex() != 6 or not self.screens[6].node_set:
                return False
            return bool(self.screens[6].open_cell(sel.get("node_id"), sel.get("deviation_id")))
        return False

    # ------------------------------------------------------------ 탐색
    def current_screen(self):
        return self.screens[self.stack.currentIndex()]

    def can_leave(self):
        """지금 화면이 떠나도 되는지(저장하지 않은 수정이 있으면 화면이 묻는다)."""
        for scr in (self.current_screen(),) + ((self.screens[self.split_index],) if self.split_index is not None else ()):
            h = getattr(scr, "can_leave", None)  # 분할 오른쪽 화면의 저장 안 한 수정도 묻는다
            if h and not h():
                return False
        return True

    def go(self, index, record=True):
        """단계 탭은 자유 이동. 앞 단계 결과가 없으면 해당 화면이 빈 화면 안내를 보여 준다(§2.1).
        지금 화면이 떠나기를 거절하면(can_leave) 이동하지 않고 False. record면 뒤로·앞으로 기록에 남긴다."""
        if index != self.stack.currentIndex() and not self.can_leave():
            self.step_buttons[self.stack.currentIndex()].setChecked(True)
            return False
        if record and (not self.history or self.history[self.history_pos] != index):
            self.history = self.history[:self.history_pos + 1][-HISTORY_MAX + 1:] + [index]
            self.history_pos = len(self.history) - 1
        if index != self.stack.currentIndex():
            self.toast_box.dismiss()
        if index == self.split_index or (self._split_uses_canvas() and self._has_canvas(self.screens[index])):
            self.unsplit()
        self._sync_drawing_into(self.screens[index])
        self.stack.setCurrentIndex(index)
        self.step_buttons[index].setChecked(True)
        scr = self.screens[index]
        if not self._split_uses_canvas():
            if getattr(scr, "canvas_host", None) is None:
                self.webview.setParent(None)
                self.webview.hide()
            self.webview.clear_segments()  # ④ 구간 색은 ④에서만 보인다(④는 on_enter에서 다시 칠함)
            self.webview.set_edit_mode(False)  # ② 편집은 ②에서만(②는 on_enter에서 다시 켬)
        scr.on_enter()
        if index in DRAWING_SCREENS and scr.combo.currentText() and scr.combo.currentText() != self.drawing:
            self.drawing = scr.combo.currentText()
            self.selection = None
        self.invalidate_index()
        self._tab_follow(index)
        self.update_header()
        self.refresh_stages()
        self._fit_explorer()
        self.refresh_related()
        return True

    def back(self):
        """Alt+←: 바로 전에 본 화면. 떠나기를 거절하면 기록 위치를 그대로 둔다."""
        if self.history_pos <= 0:
            return False
        if not self.go(self.history[self.history_pos - 1], record=False):
            return False
        self.history_pos -= 1
        return True

    def forward(self):
        if self.history_pos >= len(self.history) - 1:
            return False
        if not self.go(self.history[self.history_pos + 1], record=False):
            return False
        self.history_pos += 1
        return True

    def attach_webview(self, host):
        """웹뷰 인스턴스 하나를 화면의 캔버스 자리로 옮긴다(§2.2)."""
        if self.webview.parent() is not host:
            host.layout().addWidget(self.webview)
        self.webview.show()

    def open_results_for(self, drawing_name, node_id):
        """④에서 고른 구간을 ⑤ 분석 결과에서 연다."""
        self.go(6)
        self.screens[6].show_node(drawing_name, node_id)

    def review_candidate(self, cid, scenario_id):
        self.go(3)
        self.screens[3].select_candidate(cid, scenario_id or None)

    def set_run(self, ctx):
        """열린 실행 바꾸기. None이면 닫힘(④에서 구간을 바꾸면 이전 실행을 닫는다)."""
        self.run_ctx = ctx
        self.chip_valid.setVisible(ctx is not None)
        if ctx is None:
            self.chip_valid.set_state("결과 검증 —")
        else:
            st = ctx.doc["validation"].get("status")
            self.chip_valid.set_state("결과 검증 %s" % VALIDATION_LABELS.get(st, st) +
                                      (" (형식·참조 검증 통과 — 보류 없음을 뜻하지 않음)" if st == "passed" else ""),
                                      "passed" if st == "passed" else "blocked")
        self.update_header()
        if self.stack.currentIndex() == 3:
            self.screens[3].set_ctx(ctx)

    def update_header(self):
        """제목줄 문구 = 지금 화면 이름 + 그 화면이 연 대상(U-06). 연 것이 없으면 화면 이름만."""
        scr = self.current_screen()
        w = scr.where() or (self.screens[2].where() if self.run_ctx and self.stack.currentIndex() in (2, 3) else None)
        name = STEPS[self.stack.currentIndex()]
        parts, plain = ["<b>%s</b>" % esc(name)], [name]
        w = w or {}
        if w.get("region"):
            parts.append("<b>%s</b>" % esc(w["region"]))
            plain.append(str(w["region"]))
        if w.get("drawing"):
            parts.append("도면 <b>%s</b>" % esc(w["drawing"]))
            plain.append("도면 %s" % w["drawing"])
        if w.get("run"):
            parts.append("<span style='color:%s'>%s</span>" % (tokens.c("nav-muted"), esc(w["run"])))
            plain.append(str(w["run"]))
        self.where_label.set_where(" · ".join(parts), " · ".join(plain))

    # ------------------------------------------------------------ 브리지
    def _node_selected(self, sel):
        h = getattr(self.canvas_screen(), "on_node", None)
        if h:
            h(sel)

    def _link_selected(self, link_id):
        h = getattr(self.canvas_screen(), "on_link", None)
        if h:
            h(link_id)

    def _algorithm_requested(self, req):
        h = getattr(self.canvas_screen(), "on_algorithm", None)
        if h:
            h(req)

    def _edit_pick(self, pick):
        h = getattr(self.canvas_screen(), "on_edit_pick", None)
        if h:
            h(pick)

    def _highlight_result(self, request_id, missing):
        h = getattr(self.canvas_screen(), "on_highlight_result", None)
        if h:
            h(missing, request_id)

    def closeEvent(self, event):  # noqa: N802
        if not self.can_leave():
            event.ignore()
            return
        self.screens[6].shutdown()
        self.tasks.wait(30000)
        self.webview.dispose()
        super().closeEvent(event)

    # ------------------------------------------------------------ 설정·상태
    def reviewer_name(self):
        return (self.settings.get("reviewer_name") or "").strip() or None

    def set_reviewer_name(self, name):
        self.settings["reviewer_name"] = name
        paths.save_settings(self.settings, self.settings_path)
        self._update_reviewer_label()

    def _update_reviewer_label(self):
        n = self.reviewer_name()
        if hasattr(self, "reviewer_label"):
            self.reviewer_label.setText("검토자 %s" % (n or "미설정"))

    def open_key_settings(self):
        if self._key_dialog is None:  # 연결 시험 작업이 창을 닫은 뒤에도 끝날 수 있어 창 하나를 재사용한다
            self._key_dialog = SettingsDialog(self.api_keys, self)
        self._key_dialog.refresh()
        self._key_dialog.exec()

    def _ask_reviewer(self):
        name, ok = QInputDialog.getText(self, "검토자 이름", "검토자 이름", text=self.reviewer_name() or "")
        if ok and name.strip():
            self.set_reviewer_name(name.strip())

    def debug_message(self, text):
        """개발자 정보(Python↔웹 메시지 등)는 --debug에서만 상태줄에 보인다."""
        if self.debug:
            self.msg_label.setText(text)

    def log_error(self, title, exc):
        write_log(title, "%s: %s" % (type(exc).__name__, exc))

    def toast(self, text, undo=None):
        """동작 결과 알림(U-07). undo는 인자 없는 함수로, 토스트의 [실행 취소]나 Ctrl+Z가 한 번 부른다."""
        self.toast_box.show_message(text, undo)

    def status_message(self, text):
        self.msg_label.setText(text)
        self.msg_label.setVisible(bool(text))

    def mark_saved(self, utc_iso):
        """저장됨 표시. 저장된 자료가 바뀌었으므로 도면 색인(탐색기·관련 항목·팔레트)도 다시 읽는다."""
        self.saved_label.setText("● 저장됨 %s" % kst_text(utc_iso)[11:16])
        self.saved_label.setToolTip("최근 저장 %s" % kst_text(utc_iso))
        self.saved_label.show()
        self.invalidate_index()
        self._refresh_explorer()
        self._refresh_status()
        if self.selection:
            self.refresh_related()

    def _task(self, label):
        self.task_label.setText("진행 중: %s" % label if label else "")
        self.task_label.setVisible(bool(label))

    def _open_region(self):
        path, _ = QFileDialog.getOpenFileName(self, "구간 JSON", paths.work_path("데이터", "구간"), "JSON (*.json)")
        if path:
            scr = self.screens[2]
            i = scr.region_combo.findData(path)
            if i < 0:
                scr.region_combo.addItem(os.path.splitext(os.path.basename(path))[0], path)
                i = scr.region_combo.count() - 1
            scr.region_combo.setCurrentIndex(i)
            self.go(2)

    def _open_run_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "분석 실행 폴더", paths.output_root("분석"))
        if d:
            self.open_run(d)

    def open_run(self, run_dir):
        self.go(2)
        return self.screens[2].open_run(run_dir)

    def about_text(self):
        return ("%s %s\n자원 루트: %s\n작업 루트: %s\n저장 루트: %s\n설정: %s\n"
                "AI 호출: ⑤ 분석 결과의 AI 분석 실행 때만 Claude API(api.anthropic.com), 웹뷰 외부 네트워크 차단\n\n제3자 라이선스 고지: %s\n%s"
                % (APP_NAME, APP_VERSION, paths.resource_root(), paths.work_root(), paths.store_root(),
                   self.settings_path or paths.settings_path(), paths.licenses_dir(), LICENSE_NOTE))

    def _about(self):
        box = QMessageBox(QMessageBox.Information, "버전·데이터 위치", self.about_text(), parent=self)
        open_btn = box.addButton("라이선스 고지 열기", QMessageBox.ActionRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.open_licenses()

    def open_licenses(self):
        """고지 폴더(paths.licenses_dir())를 탐색기로 연다. 폴더가 없거나 열지 못하면 경로를 보여 주고 False."""
        d = paths.licenses_dir()
        if not os.path.isdir(d):
            QMessageBox.warning(self, "라이선스 고지", "라이선스 고지 폴더가 없습니다.\n%s" % d)
            return False
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(d)):
            QMessageBox.information(self, "라이선스 고지", "탐색기로 폴더를 열지 못했습니다. 아래 폴더를 직접 여십시오.\n%s" % d)
            return False
        return True
