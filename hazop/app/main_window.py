"""주 창 (기획서/인터페이스.md §2.1, 디자인/시안/완성본 B안 + A안 단계 표시). 웹뷰는 하나를 공유한다.

틀: 어두운 제목줄(로고·메뉴·현재 위치·검토자) / 왼쪽 단계 레일(①~⑥, 완료 ✓·현재·남음) / 탐색기 트리 / 화면 / 상태줄.
화면 번호(self.screens·go()의 index)는 추가 순서를 유지한다: 0 ①, 1 ②, 2 이전 ④, 3 이전 ⑤, 4 ③, 5 ④, 6 ⑤, 7 ⑥.
레일 단계는 STAGES, 보기 메뉴는 STEP_ORDER 순서로 보인다."""

import os

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenuBar, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                               QTabBar, QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import conn_view, data, explorer, icons, palette, project_ctx, related, tokens
from hazop.app.related_panel import RelatedPanel
from hazop.app.screens.analysis import AnalysisScreen
from hazop.app.screens.initiating import InitiatingScreen
from hazop.app.screens.knowledge import KnowledgeScreen
from hazop.app.screens.register import RegisterScreen
from hazop.app.screens.results import ResultsScreen
from hazop.app.screens.review import ReviewScreen
from hazop.app.screens.study import StudyNodesScreen
from hazop.app.chat_panel import ChatPanel
from hazop.app.screens.viewer import ViewerHost, ViewerScreen
from hazop.app.ai_conn import AiConnection
from hazop.app.conn_widgets import ConnChip, ConnPopup
from hazop.app.settings_dialog import ACTION_HELP, SettingsDialog, show_help
from hazop.app.webview import HazopWebView
from hazop.app.widgets import VALIDATION_LABELS, Chip, ElidedLabel, TaskRunner, Toast, esc, kst_text, write_log
from hazop.study.ai_settings import AiPrefs
from hazop.study.apikey import STORE_FILE_NAME, KeyStore

APP_NAME = "HAZOP 분석 도구"
APP_VERSION = "0.2.0"
STEPS = ("① 자료 등록", "② 도면 추출", "고정 응답 분석(이전 ④)", "설계보완·확정(이전 ⑤)", "③ 지식그래프", "④ 검토구간",
         "⑤ 분석 결과", "⑥ 초기사건")  # 화면 index 순
STEP_ORDER = (0, 1, 4, 5, 6, 7)  # 보기 메뉴 순서(지금 단계만)
LEGACY_STEPS = (2, 3)  # 이전 MVP 화면(DEC-0123): 보기 > 이전 MVP 하위 메뉴에만 둔다
RESULTS_INDEX = 6  # ⑤ 분석 결과
# 레일 단계: (번호, 짧은 이름, 화면 index들). 첫 화면이 레일 클릭 대상이고 그 화면의 is_done()이 완료(✓)를 정한다.
STAGES = (("1", "등록", (0,)), ("2", "추출", (1,)), ("3", "그래프", (4,)), ("4", "구간", (5,)), ("5", "결과", (6, 2, 3)),
          ("6", "초기사건", (7,)))
STAGE_GLYPHS = "①②③④⑤⑥"
assert len(explorer.STAGE_MODULES) == len(STAGES) == len(STAGE_GLYPHS)  # 단계마다 탐색기 모듈·원 번호가 하나씩
RAIL_W = 52
EXPLORER_MIN, EXPLORER_MAX, EXPLORER_VW = 200, 260, 0.14  # 탐색기 clamp(200px, 14vw, 260px), 끌어서 조절
RELATED_MIN, RELATED_MAX, RELATED_VW = 264, 340, 0.20     # 관련 항목 clamp(264px, 20vw, 340px)
RELATED_DEFAULT = (6,)  # 관련 항목을 처음부터 펴 두는 화면(⑤). ④·③은 자기 오른쪽 패널을 쓴다
# 단축키 표(? 또는 F1). (키, 설명). 화면별 키는 각 화면의 commands()가 더한다
GLOBAL_KEYS = (("Ctrl+P", "명령 팔레트(구간 #, 구성요소 @, 명령 >)"), ("Ctrl+1 ~ Ctrl+6", "단계 ①~⑥으로 이동"),
               ("Alt+← / Alt+→", "뒤로 / 앞으로"), ("Ctrl+Z", "방금 한 동작 실행 취소(토스트가 있을 때)"),
               ("Ctrl+Shift+E", "탐색기 필터"), ("Ctrl+Alt+B", "관련 항목 패널 접기/펴기"),
               ("Ctrl+K / Ctrl+Alt+K", "채팅 창 펴기 / 접기·펴기"),
               ("Ctrl+T / Ctrl+W", "새 탭 / 탭 닫기"), ("Ctrl+Tab", "다음 탭"), ("Ctrl+\\", "오른쪽 분할 켜기/끄기"),
               ("Ctrl+Enter (팔레트)", "새 탭으로 열기"), ("?  또는  F1", "단축키 표"))
HISTORY_MAX = 50
DRAWING_SCREENS = (1, 5, 6)  # 도면 선택(combo)이 있는 화면 ②④⑤: 지금 도면을 함께 따른다
EXPLORER_RIGHT_MAX = 84  # 탐색기 오른쪽 글자 열 최대 폭(미확인 11·미3·실패2)
EXPLORER_OPEN_MAX = 30  # 이보다 항목이 많은 묶음(권고 등)은 접어서 연다
MSG_KEEP = 480  # 상태줄 메시지가 연결 칩보다 먼저 받는 폭(넘으면 메시지가 줄어듦)
CHAT_MIN, CHAT_DEFAULT, CHAT_MAX, CHAT_STRIP = 320, 360, 480, 36  # 오른쪽 열 폭(끌어서 조절)과 접힌 띠 폭(화면 명세 §12.1)
RELATED_COL_MIN = 240   # 관련 항목 탭일 때 오른쪽 열의 최소 폭(좁은 창에서 ⑤가 탐색기와 함께 보이도록 채팅보다 좁게 허용)
CENTER_MIN = 640   # 가운데 단계 본문의 최소 폭. 모자라면 오른쪽 열을 먼저 접고 그다음 왼쪽 목록을 접는다
START_W, START_H, WIDE_START_W = 1440, 860, 1600  # 처음 뜨는 창 크기. 화면이 CHAT_OPEN_FROM 이상이면 WIDE_START_W까지 키운다
CHAT_OPEN_FROM = 1500  # 창 폭이 이 값 미만이면 저장된 선택이 없을 때 접힌 채 시작(1366 접힘, 1920 펼침)
EXPLORER_FOLDED = (3,)  # 이전 ⑤ 결정 폼은 1366에서 탐색기 폭(200)이면 가로가 6px 모자라 탐색기를 접는다


def plan_columns(free, center_min, explorer_wanted, column_wanted, column_min=CHAT_MIN):
    """레일을 뺀 폭 free에서 (왼쪽 목록을 보일지, 오른쪽 열을 펼칠지)를 정한다. 가운데가 center_min보다 좁아지면
    오른쪽 열을 먼저 접고, 그래도 모자라면 왼쪽 목록을 접는다(화면 명세 §12.1). 접힌 오른쪽 열은 띠 폭만 쓴다."""
    ex = EXPLORER_MIN if explorer_wanted else 0
    column_on = column_wanted and free - ex - column_min >= center_min
    strip_or_col = column_min if column_on else CHAT_STRIP
    explorer_on = explorer_wanted and free - EXPLORER_MIN - strip_or_col >= center_min
    return explorer_on, column_on


def start_size(avail_w, avail_h=None):
    """처음 뜨는 창 크기. 넓은 화면(논리 폭 1,500 이상)에서는 채팅 창이 펴진 채 시작하는 폭까지 키운다."""
    if avail_w >= CHAT_OPEN_FROM:
        return min(avail_w, WIDE_START_W), min(avail_h or START_H, START_H)
    return START_W, START_H


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


class CurrentPageStack(QStackedWidget):
    """최소·권장 크기를 지금 보이는 화면만으로 정하는 스택(기본 QStackedWidget은 모든 화면 중 가장 넓은 값을 쓴다).
    그래야 ⑤처럼 관련 항목을 펴 두는 화면이 다른 화면(⑥ 등)의 최소 폭까지 떠안아 1366 창을 넓히지 않는다(결함 8)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def minimumSizeHint(self):  # noqa: N802
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()

    def sizeHint(self):  # noqa: N802
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()


class ChatColumn(QWidget):
    """오른쪽 열 틀(화면 명세 §12.1). 탭 둘: '채팅'(첫 탭) · '관련 항목'. 접히면 폭 36 띠(채팅·관련 항목 단추)만 남는다.
    채팅 내용물은 뒤 단위가 MainWindow.set_chat_widget으로 끼운다. 지금은 '준비 중' 안내 위젯이 들어 있다."""

    def __init__(self, main):
        super().__init__()
        self.setObjectName("chat_column")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.strip = QWidget()
        self.strip.setObjectName("chat_strip")
        self.strip.setFixedWidth(CHAT_STRIP)
        sl = QVBoxLayout(self.strip)
        sl.setContentsMargins(2, 6, 2, 6)
        sl.setSpacing(4)
        self.strip_chat = QPushButton()
        self.strip_chat.setObjectName("chat_strip_chat")
        self.strip_chat.setToolTip("채팅 창 펴기 (Ctrl+K)")
        self.strip_chat.setAccessibleName("채팅 창 펴기")
        self.strip_chat.clicked.connect(main.open_chat)
        self.unread = False
        self.strip_related = QPushButton()
        self.strip_related.setObjectName("chat_strip_related")
        self.strip_related.setToolTip("관련 항목 펴기 (Ctrl+Alt+B)")
        self.strip_related.setAccessibleName("관련 항목 펴기")
        self.strip_related.clicked.connect(main.open_related)
        self.strip_chat.setIcon(icons.icon("message-circle", size=20))
        self.strip_related.setIcon(icons.icon("link", size=20))
        for b in (self.strip_chat, self.strip_related):
            b.setIconSize(QSize(20, 20))
            b.setFixedSize(CHAT_STRIP - 4, 32)
            b.setFocusPolicy(Qt.TabFocus)
            sl.addWidget(b)
        sl.addStretch(1)
        lay.addWidget(self.strip)
        self.body = QWidget()
        self.body.setObjectName("chat_body")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(6, 6, 6, 6)
        hl.setSpacing(4)
        self.tab_chat = QPushButton("채팅")
        self.tab_related = QPushButton("관련 항목")
        self.tab_chat.setIcon(icons.icon("message-circle", size=14))
        self.tab_related.setIcon(icons.icon("link", size=14))
        for b in (self.tab_chat, self.tab_related):
            b.setCheckable(True)
            b.setObjectName("chat_tab")
            hl.addWidget(b)
        self.tab_chat.clicked.connect(main.open_chat)
        self.tab_related.clicked.connect(main.open_related)
        hl.addStretch(1)
        self.fold = QPushButton()
        self.fold.setIcon(icons.icon("layout-sidebar-right-collapse", size=18))
        self.fold.setObjectName("chat_fold")
        self.fold.setFixedWidth(30)
        self.fold.setToolTip("오른쪽 열 접기 (Ctrl+Alt+K)")
        self.fold.setAccessibleName("오른쪽 열 접기")
        self.fold.clicked.connect(main.toggle_chat)
        hl.addWidget(self.fold)
        bl.addWidget(head)
        self.pages = QStackedWidget()
        bl.addWidget(self.pages, 1)
        self.chat_page = QWidget()
        self.holder = QVBoxLayout(self.chat_page)
        self.holder.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.chat_page)
        lay.addWidget(self.body, 1)
        self.widget = None
        self.set_tab("chat")

    def set_unread(self, unread):
        """접힌 띠의 채팅 단추에 '새 답' 점을 찍거나 지운다."""
        self.unread = bool(unread)
        # 새 답이 있으면 채팅 아이콘이 강조색으로 바뀐다(글자 점 대신 아이콘)
        self.strip_chat.setIcon(icons.icon("message-circle", color="warn-line" if self.unread else None, size=20))
        self.strip_chat.setToolTip("채팅 창 펴기 (Ctrl+K)" + (" · 새 답이 있습니다" if self.unread else ""))
        self.strip_chat.setAccessibleName("채팅 창 펴기, 새 답 있음" if self.unread else "채팅 창 펴기")

    def attach_related(self, panel):
        self.related_page = panel
        self.pages.addWidget(panel)

    @staticmethod
    def placeholder():
        w = QLabel("AI 채팅은 준비 중입니다.")
        w.setObjectName("chat_placeholder")
        w.setAlignment(Qt.AlignCenter)
        w.setWordWrap(True)
        return w

    def set_widget(self, widget):
        if self.widget is not None:
            self.holder.removeWidget(self.widget)
            self.widget.hide()
            if self.widget.objectName() == "chat_placeholder":
                self.widget.deleteLater()  # 안내 위젯만 이 틀이 소유한다. 끼워 준 위젯은 건드리지 않는다
            else:
                self.widget.setParent(None)
        self.widget = widget if widget is not None else self.placeholder()
        self.holder.addWidget(self.widget)
        self.widget.show()

    def set_collapsed(self, collapsed):
        self.strip.setVisible(collapsed)
        self.body.setVisible(not collapsed)

    def set_tab(self, name):
        related = name == "related" and getattr(self, "related_page", None) is not None
        self.pages.setCurrentWidget(self.related_page if related else self.chat_page)
        self.tab_chat.setChecked(not related)
        self.tab_related.setChecked(related)


class MainWindow(QMainWindow):
    stage_changed = Signal(int, int)  # (화면 index, 단계 번호 0~5): 단계 화면이 바뀔 때. 채팅이 '지금 단계'를 알게 한다
    drawing_changed = Signal(object)  # 지금 도면(추출 이름 또는 None)이 바뀔 때

    def __init__(self, settings_path=None, ask_reviewer=True, debug=False):
        super().__init__()
        self.debug = debug  # True면 상태줄에 Python↔웹 메시지 등 개발자 정보를 보여 준다(--debug)
        self.settings_path = settings_path
        self.settings = paths.load_settings(settings_path)
        self.api_keys = KeyStore(os.path.join(os.path.dirname(settings_path or paths.settings_path()), STORE_FILE_NAME))
        self.ai_prefs = AiPrefs(self.settings, lambda s: paths.save_settings(s, settings_path))
        self.ai_conn = AiConnection(self.ai_prefs, self.api_keys, debug=debug, parent=self)
        self._key_dialog = None
        self._conn_popup = None
        self._conn_alerted = None
        self.run_ctx = None
        self.setWindowTitle(APP_NAME)
        self.resize(*start_size(*self._screen_size()))
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
        self.webview.bridge.chipClicked.connect(self._chip_clicked)

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
        self.stack = CurrentPageStack()
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
        self.chat_column = ChatColumn(self)
        self.chat_column.set_widget(None)
        self.chat_column.attach_related(self.related)
        self.split.addWidget(self.chat_column)
        self.split.setStretchFactor(1, 1)
        self._chat_open = False       # 사용자(또는 창 폭 규칙)가 정한 채팅 펼침. 처음 보일 때(showEvent) 정한다
        self._ex_yielded = False      # 오른쪽 열을 열려고 왼쪽 목록이 비켜 준 상태
        self._col_on = False          # 지금 실제로 펼쳐져 있는지(자리가 모자라면 펼치기를 원해도 접힌다)
        self._chat_w = CHAT_DEFAULT
        try:
            self._chat_w = max(CHAT_MIN, min(CHAT_MAX, int(self.settings.get("chat_width") or CHAT_DEFAULT)))
        except (TypeError, ValueError):
            pass
        self._chat_started = False
        self._chat_view = None
        self.chat_column.set_collapsed(True)
        self.split.splitterMoved.connect(self._chat_dragged)
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
                        KnowledgeScreen(self), StudyNodesScreen(self), ResultsScreen(self), InitiatingScreen(self)]
        for s in self.screens:
            self.stack.addWidget(s)
            s.setFocusPolicy(Qt.ClickFocus)  # 주 작업 영역이 없을 때 화면 자체가 초점을 받아 화면 단축키가 듣게
            if self.stack.count() - 1 in DRAWING_SCREENS:
                s.combo.currentTextChanged.connect(lambda _t, scr=s: self._drawing_changed(scr))
        self.screens[2].review_requested.connect(self.review_candidate)
        self.ai_conn.fixed_match = self.screens[6].fixed_match  # 설정 창 고정 응답 '맞는 칸'(§3.5)
        self._status_bar()
        self.ai_conn.changed.connect(self._update_conn_chip)
        self.ai_conn.notice.connect(lambda text: self.toast(text, actions=[("AI 연결 설정", self.open_ai_settings)],
                                                            ms=10000))
        self._menus()
        self._shortcuts()
        self._chat_setup()
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
        self.explorer_title = QLabel("")
        self.explorer_title.setObjectName("explorer_title")
        v.addWidget(self.explorer_title)
        self.explorer_filter = QLineEdit()
        self.explorer_filter.setObjectName("explorer_filter")
        self.explorer_filter.setPlaceholderText("⌕ 찾기 (Ctrl+Shift+E)")
        self.explorer_filter.setClearButtonEnabled(True)
        self.explorer_filter.setAccessibleName("탐색기 필터")
        self.explorer_filter.setToolTip("지금 단계 목록 안에서 찾습니다")
        self.explorer_filter.textChanged.connect(self._apply_filter)
        v.addWidget(self.explorer_filter)
        self.explorer_drawing = QComboBox()  # 검토구간 묶음을 그 도면을 지나는 구간으로 좁힌다(걸친 구간 포함)
        self.explorer_drawing.setObjectName("explorer_drawing")
        self.explorer_drawing.setAccessibleName("탐색기 도면 필터")
        self.explorer_drawing.setToolTip("검토구간: 모든 도면(프로젝트 전체) 또는 고른 도면을 지나는 구간만")
        self.explorer_drawing.addItem("모든 도면", None)
        self.explorer_drawing.currentIndexChanged.connect(lambda _i: self._refresh_explorer())
        v.addWidget(self.explorer_drawing)
        self.explorer = QTreeWidget()
        self.explorer.setObjectName("explorer")
        self.explorer.setColumnCount(2)
        self.explorer.setHeaderHidden(True)
        self.explorer.setIndentation(10)
        self.explorer.setIconSize(QSize(10, 10))
        self.explorer.header().setStretchLastSection(False)
        self.explorer.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.explorer.header().setSectionResizeMode(1, QHeaderView.Fixed)  # 진행 글자 열이 좁은 탐색기에서 이름 열을 밀어내지 않게
        self.explorer.header().resizeSection(1, 64)
        self.explorer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.explorer.setTextElideMode(Qt.ElideMiddle)  # 구간 이름 끝의 도면 범위 [101 → 102] ⇄를 남긴다
        self.explorer.itemClicked.connect(self._explorer_clicked)
        v.addWidget(self.explorer, 1)
        self.explorer_wanted = True  # 보기 메뉴로 접고 편다. 창이 좁으면 자동으로 숨긴다(_fit_explorer)
        return self.explorer_panel

    def explorer_stage(self):
        return self.stage_of(self.stack.currentIndex())

    def _explorer_groups(self):
        """지금 단계의 탐색기 모듈이 만든 [explorer.Group](hazop/app/explorer.py)."""
        return explorer.STAGE_MODULES[self.explorer_stage()](self)

    def explorer_drawing_choice(self, pg):
        """도면 필터 목록을 프로젝트 도면으로 맞추고 고른 도면 번호(모든 도면이면 None)를 돌려준다."""
        box = self.explorer_drawing
        numbers = [s["drawing_number"] for s in pg["sheets"]] if pg else []
        have = [box.itemData(i) for i in range(1, box.count())]
        if have != numbers:
            cur = box.currentData()
            box.blockSignals(True)
            while box.count() > 1:
                box.removeItem(1)
            for d in numbers:
                box.addItem(d, d)
            box.setCurrentIndex(box.findData(cur) if cur in numbers else 0)
            box.blockSignals(False)
        box.setVisible(len(numbers) > 1)
        return box.currentData()

    def _refresh_explorer(self):
        """지금 단계 모듈만 보인다. 내용이 같으면 다시 만들지 않는다(선택 유지, 항목 클릭 처리 중 항목 삭제 방지)."""
        stage = self.explorer_stage()
        if stage != getattr(self, "_explorer_stage", stage):
            self.explorer_filter.clear()  # 다른 단계 목록을 앞 단계 검색어로 거르지 않는다
        self._explorer_stage = stage
        _num, short, idxs = STAGES[stage]
        self.explorer_title.setText("%s %s" % (STAGE_GLYPHS[stage], short))
        self.explorer_title.setToolTip("%s 단계의 목록입니다. 다른 단계 항목은 레일(Ctrl+1~6)이나 명령 팔레트(Ctrl+P)로 찾습니다."
                                       % STEPS[idxs[0]])
        if stage not in explorer.DRAWING_FILTER_STAGES:
            self.explorer_drawing.hide()
        groups = self._explorer_groups()
        sig = [stage] + [(g.name, [(t, k, r, tip) for t, k, r, _, tip in g.items], g.empty, g.action, g.about, list(g.info))
                         for g in groups]
        if sig != getattr(self, "_explorer_sig", None):
            self._explorer_sig = sig
            self.explorer.clear()
            muted = QColor(tokens.c("muted"))
            for gi, g in enumerate(groups):
                grp = QTreeWidgetItem([g.name, str(len(g.items))])
                f = grp.font(0)
                f.setBold(True)
                grp.setFont(0, f)
                grp.setForeground(1, muted)
                grp.setFlags(Qt.ItemIsEnabled)
                grp.setToolTip(0, "%s\n%s" % (g.name, g.about) if g.about else g.name)
                self.explorer.addTopLevelItem(grp)
                for text, tip in g.info:
                    row = QTreeWidgetItem([text, ""])
                    row.setFlags(Qt.ItemIsEnabled)
                    row.setForeground(0, muted)
                    row.setData(0, Qt.UserRole + 1, "info")
                    row.setToolTip(0, tip)
                    grp.addChild(row)
                    row.setFirstColumnSpanned(True)  # 안내 줄은 개수 열까지 써서 덜 잘린다(결함 9)
                if g.action is not None:
                    link = QTreeWidgetItem([g.action[0], ""])
                    link.setData(0, Qt.UserRole, g.action[1])
                    link.setData(0, Qt.UserRole + 1, "action")
                    link.setForeground(0, QColor(tokens.c("ui")))
                    link.setToolTip(0, g.action[2])
                    grp.addChild(link)  # 항목이 많아도 펼치면 바로 보이게 목록 위
                    link.setFirstColumnSpanned(True)
                for text, target, right, icon, tip in g.items:
                    child = QTreeWidgetItem([text, right])
                    child.setData(0, Qt.UserRole, target)
                    child.setToolTip(0, tip)
                    child.setToolTip(1, tip)
                    child.setForeground(1, muted)
                    if icon is not None:
                        child.setIcon(0, icon)
                    grp.addChild(child)
                hint, button = g.empty
                if not g.items and hint:
                    empty = QTreeWidgetItem([hint])
                    empty.setFlags(Qt.NoItemFlags)
                    empty.setForeground(0, muted)
                    f = empty.font(0)
                    f.setItalic(True)
                    empty.setFont(0, f)
                    empty.setData(0, Qt.UserRole + 1, "hint")
                    empty.setToolTip(0, hint)
                    grp.addChild(empty)
                    empty.setFirstColumnSpanned(True)
                    if button is not None:  # 빈 상태의 다음 할 일
                        row = QTreeWidgetItem([""])
                        row.setFlags(Qt.ItemIsEnabled)
                        row.setData(0, Qt.UserRole + 1, "hint")
                        grp.addChild(row)
                        row.setFirstColumnSpanned(True)
                        b = QPushButton(button[0])
                        b.setObjectName("explorer_next")
                        b.setToolTip(button[2])
                        b.setAccessibleName(button[0])
                        b.setCursor(Qt.PointingHandCursor)
                        b.clicked.connect(lambda _=False, t=button[1]: self._explorer_open(t))
                        self.explorer.setItemWidget(row, 0, b)
                grp.setExpanded(len(g.items) <= EXPLORER_OPEN_MAX or gi == 0)  # 단계의 첫 묶음(주 목록)은 늘 편다
            rights = [r for g in groups for _t, _k, r, _i, _tip in g.items if r] + [str(len(g.items)) for g in groups]
            fm = self.explorer.fontMetrics()  # 오른쪽 글자 열은 이 단계에서 쓰는 만큼만(이름 열이 덜 잘리게)
            self.explorer.header().resizeSection(1, min(EXPLORER_RIGHT_MAX, max(fm.horizontalAdvance(r) for r in rights) + 14))
            self._apply_filter()
        self._mark_explorer_current()

    def _apply_filter(self):
        """필터는 지금 단계 모듈 안에서만 찾는다. 안내·정보·바로가기 줄은 개수에 세지 않고 찾는 동안 숨긴다."""
        q = self.explorer_filter.text().strip()
        for g in range(self.explorer.topLevelItemCount()):
            grp = self.explorer.topLevelItem(g)
            shown = total = 0
            for c in range(grp.childCount()):
                ch = grp.child(c)
                hint = ch.data(0, Qt.UserRole + 1) in ("hint", "action", "info")
                hide = bool(q) and (hint or palette.fuzzy_score(q, ch.text(0)) is None)
                ch.setHidden(hide)
                total += not hint
                shown += not hide and not hint
            grp.setText(1, str(shown if q else total) if total or grp.childCount() == 0 or q
                        or any(grp.child(c).data(0, Qt.UserRole + 1) == "hint" for c in range(grp.childCount())) else "")

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
        if target:
            self._explorer_open(target)

    def _explorer_open(self, target):
        idx, key = target
        if idx == "cmd":
            explorer.COMMANDS[key](self)
            return
        if idx == 6 and key is None:
            self.go(6)
            return
        if idx == 6:
            self.open_target({"kind": "cell", "drawing": self.drawing, "node_id": key[0], "deviation_id": key[1]})
            return
        if idx == 5:
            # ⑤에서는 결과 행렬의 그 행을 고르고 ⑤에 머문다(실행 중이어도 분석은 그대로). Alt+누르기는 ④ 구간.
            alt = bool(QApplication.keyboardModifiers() & Qt.AltModifier)
            rs = self.screens[6]
            if self.stack.currentIndex() == 6 and not alt and rs.name == self.drawing and rs._row_of(key) is not None:
                rs.show_node(self.drawing, key)
                self.set_selection({"kind": "node", "drawing": self.drawing, "node_id": key})
                self._mark_explorer_current()
                return
            idx = self.index()
            self.open_target({"kind": "node", "drawing": idx.node_drawing_name(key) if idx else self.drawing,
                              "node_id": key})
            return
        if idx == 1:
            if self.go(1):
                self.screens[1].select_drawing(key)
            return
        if not self.go(idx):
            return
        h = getattr(self.screens[idx], "open_item", None)
        if h:
            h(key)

    def toggle_explorer(self):
        self.explorer_wanted = not self.explorer_wanted
        self._ex_yielded = False
        self._fit_explorer()

    def focus_explorer_filter(self):
        if not self.explorer_wanted:
            self.explorer_wanted = True
            self._fit_explorer()
        self.explorer_filter.setFocus()
        self.explorer_filter.selectAll()

    def _screen_size(self):
        scr = QApplication.primaryScreen()
        geo = scr.availableGeometry() if scr is not None else None
        return (geo.width(), geo.height()) if geo is not None else (START_W, START_H)

    def _col_min(self):
        return RELATED_COL_MIN if self.related_shown.get(self.stack.currentIndex(), False) else CHAT_MIN

    def _column_wanted(self):
        return self._chat_open or self.related_shown.get(self.stack.currentIndex(), False)

    def _fit_explorer(self):
        """왼쪽 목록과 오른쪽 열을 정한다. 가운데가 CENTER_MIN(또는 화면 자체의 최소 폭)보다 좁아지면 오른쪽 열을 먼저 접고
        그다음 왼쪽 목록을 접는다(plan_columns). 오른쪽 열의 탭은 화면마다 기억한 관련 항목 펼침을 따른다."""
        cur = self.stack.currentIndex()
        rel = self.related_shown.get(cur, False)
        cmin = max(CENTER_MIN, self.stack.minimumSizeHint().width())
        ex_ok = self.explorer_wanted and cur not in EXPLORER_FOLDED
        ex_on, col_on = plan_columns(self.width() - RAIL_W, cmin, ex_ok, self._column_wanted(), self._col_min())
        before = (self.explorer_panel.isHidden(), self._col_on, self.chat_column.pages.currentWidget())
        self.explorer_panel.setVisible(ex_on)
        self._col_on = col_on
        self.chat_column.set_tab("related" if rel else "chat")
        self.chat_column.set_collapsed(not col_on)
        if col_on and not rel:
            self.chat_column.set_unread(False)  # 채팅 탭이 보이면 새 답 표시를 지운다
        self._apply_chat_limits()
        if before != (self.explorer_panel.isHidden(), self._col_on, self.chat_column.pages.currentWidget()):
            self._size_panels()

    def _size_panels(self):
        """처음과 창 크기가 바뀔 때: 왼쪽 목록·오른쪽 열 폭을 맞춘다(가운데가 나머지, CENTER_MIN은 지킨다)."""
        w = self.width()
        free = w - RAIL_W
        cmin = max(CENTER_MIN, self.stack.minimumSizeHint().width())
        self.explorer_panel.setMinimumWidth(160)
        ew_min = 0 if self.explorer_panel.isHidden() else EXPLORER_MIN
        cw = CHAT_STRIP
        if self._col_on:
            cw = max(self._col_min(), min(self._chat_w, free - ew_min - cmin))
        ew = 0 if self.explorer_panel.isHidden() else max(ew_min, min(clamp_width(w, EXPLORER_MIN, EXPLORER_MAX, EXPLORER_VW),
                                                                        free - cw - cmin))
        self.split.setSizes([ew, max(200, free - ew - cw), cw])

    # ------------------------------------------------------------ 오른쪽 열 틀(S-frame)
    def _apply_chat_limits(self):
        col = self.chat_column
        if self._col_on:
            # 최소 폭은 Qt의 하드 최소로 두지 않는다. 화면 힌트가 일시적으로 낡은 값일 때 창 최소 폭이 부풀어 창이 넓어지기 때문이다.
            # 대신 plan_columns·_size_panels가 가운데 폭을 지키고, 끌어서 줄이는 것은 _chat_dragged가 최소로 되돌린다.
            col.setMinimumWidth(0)
            col.setMaximumWidth(CHAT_MAX)
        else:
            col.setFixedWidth(CHAT_STRIP)

    def chat_collapsed(self):
        """채팅을 접어 두었는지(사용자 선택). 자리가 모자라 자동으로 접힌 것은 따로 _col_on으로 본다."""
        return not self._chat_open

    def chat_widget(self):
        return self.chat_column.widget

    def set_chat_widget(self, widget):
        """채팅 창 내용물을 끼운다(뒤 단위 C2의 hazop/app/chat_panel.py). None이면 '준비 중' 안내로 되돌린다.
        끼운 위젯의 소유는 호출한 쪽이 이어 간다(이 틀은 떼기만 한다)."""
        self.chat_column.set_widget(widget)

    # 채팅 창 내용물(C2): 세션·프로젝트 자료·뷰어를 이어 준다. 부품(hazop.chat.*)이 없어도 앱은 뜬다.
    def _chat_setup(self):
        self._chat_ctx = None
        self.viewer_host = ViewerHost(self.webview, self._chat_names, self._chat_switch, parent=self)
        self.chat_panel = ChatPanel(self._chat_session, env_provider=self._chat_env, host=self.viewer_host,
                                    view_fn=self._chat_view_dict, model=self.settings.get("chat_model") or "fast", parent=self,
                                    project_fn=self._chat_project_id)
        self.chat_panel.modelChanged.connect(self._chat_model_saved)
        self.chat_panel.guideRequested.connect(self._chat_guide)
        self.chat_panel.answered.connect(self._chat_answered)
        self.drawing_changed.connect(lambda _d: self.chat_panel.check_project())  # 프로젝트가 바뀌면 대화를 끝낸다
        self.chat_panel.escaped.connect(lambda: self._focus_main(self.current_screen()))
        self.ai_conn.changed.connect(self._chat_availability)
        self.set_chat_widget(self.chat_panel)
        self._chat_availability()

    def _chat_project_id(self):
        names = [self.drawing] if self.drawing else []
        names += [e["name"] for e in data.list_extractions() if e["name"] not in names]
        for name in names[:1]:
            try:
                ctx = project_ctx.load(name)
            except (OSError, ValueError, KeyError):
                return None
            return ctx.project_id if ctx and not ctx.error else None
        return None

    def _chat_names(self):
        pid = self._chat_project_id()
        return project_ctx.graph_names(pid) if pid else {}

    def _chat_switch(self, name):
        if not self._has_canvas(self.current_screen()):
            self.go(1)
        scr = self.canvas_screen()
        h = getattr(scr, "select_drawing", None)
        if h:
            h(name)

    def _chat_env(self):
        """-> (CardEnv, 프로젝트 그래프) 또는 None. 같은 프로젝트면 파일 지문이 같을 때 읽은 묶음을 다시 쓴다."""
        pid = self._chat_project_id()
        if not pid:
            return None
        from hazop.chat import card as chatcard
        from hazop.chat import context as chatcontext
        ctx = self._chat_ctx
        ctx = chatcontext.refresh(ctx) if ctx is not None and ctx.project_id == pid else chatcontext.load_context(pid)
        self._chat_ctx = ctx
        return chatcard.ContextEnv(ctx), ctx.pg

    def _chat_session(self, model, callbacks):
        pid = self._chat_project_id()
        if not pid:
            raise ValueError("프로젝트가 없습니다. 먼저 도면을 등록하고 추출하세요.")
        try:
            from hazop.chat.session import ChatSession
        except ImportError as exc:
            raise ValueError("이 설치에는 채팅 부품이 없습니다(%s)." % exc) from exc
        from hazop.chat import card as chatcard
        return ChatSession(pid, model=model, schema=chatcard.CARD_SCHEMA, system_prompt=chatcard.SYSTEM_PROMPT, **callbacks)

    def _chat_view_dict(self):
        sel = self.selection or {}
        picked = [sel[k] for k in ("entity_id", "node_id") if sel.get(k)]
        return {"stage": STAGE_GLYPHS[self.stage_of(self.stack.currentIndex())], "sheet": self.drawing, "selected": picked}

    def _chat_answered(self):
        """답이 왔는데 채팅 탭이 보이지 않으면(접힘·자리 모자람·관련 항목 탭) 띠에 점을 찍는다."""
        if not self._col_on or self.related_shown.get(self.stack.currentIndex(), False):
            self.chat_column.set_unread(True)

    def _chat_model_saved(self, model):
        self.settings["chat_model"] = model
        try:
            paths.save_settings(self.settings, self.settings_path)
        except OSError:
            pass

    def _chat_availability(self, user_check=False):
        """연결 상태를 채팅 창에 알린다. 채팅이 스스로 건 막힘은 ai_conn.changed(다른 AI 작업·확인·모델 변경마다 옴)로 풀지 않고
        사용자가 연결을 다시 확인한 결과(user_check)나 한도 재설정 시각으로만 푼다."""
        st = self.ai_conn.status("subscription")
        self.chat_panel.set_availability(st.get("state"), st.get("detail") or "", user_check=user_check)

    def _chat_guide(self, name):
        if name == "install":
            self.conn_action("install_help", "subscription")
        elif name == "login":
            self.conn_action("terminal_login", "subscription")
        else:
            self.open_ai_settings("subscription")

    def chat_view(self):
        """채팅이 알아야 할 지금 화면: 화면 index, 단계 번호(0~5), 지금 도면."""
        idx = self.stack.currentIndex()
        return {"index": idx, "stage": self.stage_of(idx), "drawing": self.drawing}

    def _notify_chat(self):
        """단계와 도면이 바뀌었으면 stage_changed·drawing_changed를 낸다(같은 값이면 내지 않는다)."""
        idx = self.stack.currentIndex()
        old = self._chat_view
        self._chat_view = (idx, self.drawing)
        if old is None or old[0] != idx:
            self.stage_changed.emit(idx, self.stage_of(idx))
        if old is None or old[1] != self.drawing:
            self.drawing_changed.emit(self.drawing)

    def _save_chat_pref(self):
        self.settings["chat_collapsed"] = not self._chat_open
        self.settings["chat_width"] = self._chat_w
        try:
            paths.save_settings(self.settings, self.settings_path)
        except OSError:
            pass  # 창 배치 기억을 못 써도 앱은 계속 쓴다

    def _refit(self, remember=False):
        was = self._col_on
        self._fit_explorer()
        self._size_panels()
        if remember:
            self._save_chat_pref()
        if self._col_on and not was and hasattr(self, "chat_panel"):
            QTimer.singleShot(0, self.chat_panel.refresh_examples)  # 펼칠 때 예시 질문의 태그를 지금 프로젝트에서 채운다

    def _make_room(self):
        """사용자가 오른쪽 열을 직접 열 때 자리가 모자라면 왼쪽 목록이 비켜 준다(창을 줄일 때의 순서와는 따로).
        열을 닫으면 비켜 준 왼쪽 목록이 돌아온다."""
        cur = self.stack.currentIndex()
        cmin = max(CENTER_MIN, self.stack.minimumSizeHint().width())
        free = self.width() - RAIL_W
        ex_ok = self.explorer_wanted and cur not in EXPLORER_FOLDED
        low = self._col_min()
        if ex_ok and not plan_columns(free, cmin, True, True, low)[1] and plan_columns(free, cmin, False, True, low)[1]:
            self.explorer_wanted, self._ex_yielded = False, True

    def _give_back(self):
        if self._ex_yielded:
            self.explorer_wanted, self._ex_yielded = True, False

    def _set_chat_open(self, open_, remember=True):
        """open_이면 채팅 탭으로, 아니면 오른쪽 열 전체(채팅·관련 항목)를 접는다."""
        self._chat_open = open_
        self.related_shown[self.stack.currentIndex()] = False
        if open_:
            self._make_room()
        else:
            self._give_back()
        self._refit(remember)

    def toggle_chat(self):
        """Ctrl+Alt+K: 오른쪽 열을 접거나 편다. 접으면 채팅과 관련 항목이 함께 접힌다."""
        if self._column_wanted():
            self._set_chat_open(False)
        else:
            self._set_chat_open(True)

    def open_chat(self):
        """Ctrl+K: 채팅 탭으로 펴고 입력칸으로 간다."""
        self._set_chat_open(True)
        h = getattr(self.chat_widget(), "focus_input", None)
        if h:
            h()

    def open_related(self):
        """오른쪽 열을 관련 항목 탭으로 편다(이 화면에서)."""
        cur = self.stack.currentIndex()
        self.related_shown[cur] = True
        self._make_room()
        self._refit()
        if self.related.isVisible() and getattr(self, "_related_stale", True):
            self.refresh_related()

    def chat_width(self):
        """펴졌을 때 오른쪽 열의 폭(사용자가 끌어 바꾼 값, 설정 chat_width)."""
        return self._chat_w

    def set_chat_width(self, width):
        self._chat_w = max(CHAT_MIN, min(CHAT_MAX, int(width)))
        self._refit(remember=True)

    def _chat_dragged(self, _pos, _index):
        """가운데와 오른쪽 열 사이 손잡이를 끌면 새 폭을 기억한다."""
        if not self._col_on or not self.chat_column.isVisible():
            return
        low = self._col_min()
        if self.chat_column.width() < low:
            self._size_panels()  # 최소보다 좁게 끌었으면 최소로 되돌린다
            return
        w = max(CHAT_MIN, min(CHAT_MAX, self.chat_column.width()))
        if w != self._chat_w:
            self._chat_w = w
            self._save_chat_pref()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._chat_started:
            # 처음 보일 때 한 번: 저장된 선택이 있으면 그것, 없으면 창 폭이 1500 미만이면 접고 이상이면 편다
            self._chat_started = True
            pref = self.settings.get("chat_collapsed")
            open_ = (not pref) if isinstance(pref, bool) else self.width() >= CHAT_OPEN_FROM
            self._chat_open = open_
            self._refit()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "split"):
            self._size_panels()
            self._fit_explorer()
        if hasattr(self, "toast_box") and self.toast_box.isVisible():
            self.toast_box.place()
        self._fit_conn_chip()

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
        self.msg_label = ElidedLabel("", elide=Qt.ElideMiddle)  # 상태줄이 모자라면 연결 칩보다 먼저 줄어든다(§5.1)
        self.msg_label.setObjectName("muted")
        self.keys_label = QLabel("Ctrl+P 명령 · ? 단축키")
        self.keys_label.setObjectName("muted")
        for w in (self.drawing_label, self.count_label, self.chip_valid):
            sb.addWidget(w)
        self.conn_chip = ConnChip()  # AI 연결 칩(화면 설계 §5). 누르면(또는 Tab 후 Enter·Space) 상세 창
        self.conn_chip.clicked.connect(self.open_conn_popup)
        sb.addPermanentWidget(self.msg_label, 1)
        for w in (self.task_label, self.saved_label, self.conn_chip, self.keys_label):
            sb.addPermanentWidget(w)
        self._update_conn_chip()
        self._update_reviewer_label()

    def _update_conn_chip(self):
        """칩 글자·모양·접근성 이름을 연결 상태 표(conn_view)로 다시 만든다. 실행할 수 없는 상태로 바뀔 때만
        상태줄 메시지로도 알린다(화면 낭독기가 읽게, §10.3)."""
        conn = self.ai_conn
        this_run = conn.run_override is not None
        method = conn.run_override or conn.method
        status, model = conn.status(method), conn.model(method)
        self.conn_chip.set_chip(conn_view.chip_look(method, status, this_run),
                                conn_view.chip_text(method, status, model, False, this_run),
                                conn_view.chip_text(method, status, model, True, this_run),
                                conn_view.chip_accessible(method, status, model, this_run))
        self._fit_conn_chip()
        lk = conn_view.look(method, status["state"])
        key = (method, status["state"])
        if lk.can_start or status["state"] == "checking":
            self._conn_alerted = None
        elif key != self._conn_alerted:
            self._conn_alerted = key
            self.status_message("AI 연결(%s): %s." % (conn_view.METHOD_NAMES[method], lk.title))
        if self._conn_popup is not None and self._conn_popup.isVisible():
            self._conn_popup.fill(conn)

    def _fit_conn_chip(self):
        """넓은 형식이 실제로 들어가면 넓게, 아니면 좁게(창 폭 기준이 아님, §5.1). 메시지는 MSG_KEEP까지는 칩보다
        먼저 자리를 받고, 그보다 길면 메시지가 말줄임으로 줄어든다(칩은 줄이지 않음). 나머지 칸은 지금 폭 그대로 센다."""
        if not hasattr(self, "conn_chip"):
            return
        sb = self.statusBar()
        fixed = [self.drawing_label, self.count_label, self.chip_valid, self.task_label, self.saved_label,
                 self.keys_label]
        used = sum(w.sizeHint().width() for w in fixed if not w.isHidden())
        msg = min(self.msg_label.sizeHint().width(), MSG_KEEP) if self.msg_label.text() else 0
        room = sb.width() - used - msg - 12 * (len(fixed) + 2)
        chip = self.conn_chip
        chip.set_narrow(chip.width_for(chip.wide) > min(room, 340))

    def set_conn_status(self, status):
        """⑤ 실행 흐름이 받은 연결 상태(ConnStatus)를 칩·설정 창에 반영한다."""
        self.ai_conn.set_status(status)

    def set_run_override(self, method):
        """'API 키로 이어서 실행' 동안 칩을 'API 키 · 모델 · 이번 실행만'으로 둔다. None이면 되돌린다(D4)."""
        self.ai_conn.set_run_override(method)

    def open_conn_popup(self):
        if self._conn_popup is None:
            self._conn_popup = ConnPopup(self.conn_chip)
            self._conn_popup.action.connect(self.conn_action)
        self._conn_popup.fill(self.ai_conn)
        self._conn_popup.show_above()
        return self._conn_popup

    def conn_action(self, name, method=None):
        """칩 상세 창·해결 안내의 동작. method를 주면 그 방식에 대해 한다(없으면 지금 방식)."""
        if name == "check":
            self.ai_conn.check(method, done=lambda _st: self._chat_availability(user_check=True))
        elif name == "to_api":
            self.open_ai_settings("api")
        elif name in ACTION_HELP:
            show_help(self, ACTION_HELP[name])
        else:  # settings와 설정 창에서 하는 동작(위치 지정·연결 시험·찾아보기·키 추가·오류 복사)
            self.open_ai_settings(method)

    def recheck_ai(self):
        self.ai_conn.check(done=lambda _st: self._chat_availability(user_check=True))

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
        self._fit_conn_chip()

    def _menus(self):
        m = self.menu_bar
        f = m.addMenu("파일")
        f.addAction("Excel 내보내기…", self.export_results_excel)
        f.addSeparator()
        f.addAction("설정(검토자 이름)…", self._ask_reviewer)
        f.addAction("AI 연결 설정…", self.open_ai_settings)
        f.addSeparator()
        f.addAction("끝내기", self.close)
        v = m.addMenu("보기")
        v.addAction("명령 팔레트\tCtrl+P", self.open_palette)
        v.addSeparator()
        for i in STEP_ORDER:
            v.addAction(STEPS[i], lambda k=i: self.go(k))
        legacy = v.addMenu("이전 MVP")
        for i in LEGACY_STEPS:
            legacy.addAction(STEPS[i], lambda k=i: self.go(k))
        legacy.addSeparator()
        legacy.addAction("구간 열기…", self._open_region)
        legacy.addAction("실행 열기…", self._open_run_dialog)
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

    def export_results_excel(self):
        """파일 > Excel 내보내기: 지금 ⑤ 분석 결과(구간 × 편차)를 내보낸다. 이전 ⑤ 화면은 자기 단추로 내보낸다."""
        if self.go(RESULTS_INDEX):
            self.screens[RESULTS_INDEX].export_excel()

    # ------------------------------------------------------------ 단축키(U-02)·팔레트(U-01)
    def _shortcuts(self):
        """창 전체 단축키. 화면별 한 글자 키(A·R·J·M…)는 각 화면이 자기 범위(WidgetWithChildrenShortcut)로 단다.
        글 입력칸에 초점이 있으면 글자 키는 입력이 먼저 받는다(Qt ShortcutOverride)."""
        keys = [("Ctrl+P", self.open_palette), ("Ctrl+Shift+P", lambda: self.open_palette(">")),
                ("Ctrl+Z", self.undo), ("Ctrl+Alt+B", self.toggle_related),
                ("Ctrl+K", self.open_chat), ("Ctrl+Alt+K", self.toggle_chat),
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
                                ("단축키 표", "?", self.show_shortcuts), ("AI 연결 설정", "", self.open_ai_settings),
                                ("AI 연결 다시 확인", "", self.recheck_ai),
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
                items.append(palette.Item("component", text, kind, "",
                                          lambda nt, e=eid, d=idx.drawing_name_of(eid) or dw: self.open_target(
                                              {"kind": "component", "drawing": d, "entity_id": e, "open": "drawing"}, nt),
                                          ("component", dw, eid)))
            for n in (idx.view or idx.node_set or {}).get("nodes", []):
                items.append(palette.Item("node", project_ctx.node_label(n), "구성요소 %d" % len(n["members"]), "",
                                          lambda nt, nid=n["node_id"], d=idx.node_drawing_name(n["node_id"]):
                                          self.open_target({"kind": "node", "drawing": d, "node_id": nid}, nt),
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
            self.screen_notice("도면을 쓰는 화면 둘은 함께 나눌 수 없습니다(도면 보기는 하나).")
            self.split_btn.setChecked(False)
            return False
        scr = self.screens[index]
        # 두 화면의 최소 폭이 창에 들어가야 나눈다. 모자라면 관련 항목·탐색기를 접고, 그래도 모자라면 나누지 않는다
        # (창이 화면 밖으로 넓어지지 않게)
        need = self.stack.currentWidget().minimumSizeHint().width() + scr.minimumSizeHint().width() + 8
        if need > self.width() - RAIL_W:
            self._refuse_split(need)
            return False
        self._split_restore = ((cur, self.related_shown.get(cur, False)), self.explorer_wanted, self._chat_open)
        ew = 0 if self.explorer_panel.isHidden() else self.explorer_panel.width()
        rw = self.chat_column.width()
        if need > self.width() - RAIL_W - ew - rw:
            self.related_shown[cur] = False
            self._chat_open = False
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
        grown = self._split_min_width()
        if grown > self.width():  # 막이(결함 3): 나눈 화면들의 최소 폭이 창을 넓히려 들면 되돌린다
            self.unsplit()
            self._refuse_split(max(need, grown - RAIL_W))
            return False
        w = self.panes.width()
        self.panes.setSizes([w // 2, w - w // 2])
        self.refresh_stages()
        return True

    def _split_min_width(self):
        """나눈 상태의 창 최소 폭을 부분 합으로 잰다. 창·분할기의 최소 폭 힌트는 배치가 다시 계산되기 전까지 옛 값이거나
        접힌 쪽을 빼므로 쓰지 않는다: 레일 + 보이는 탐색기·관련 항목 + 왼쪽 화면 + 오른쪽 칸 + 분할기 손잡이."""
        def least(w):
            return max(w.minimumSizeHint().width(), w.minimumWidth())
        side = least(self.chat_column) + (0 if self.explorer_panel.isHidden() else least(self.explorer_panel))
        handles = self.split.handleWidth() * 2 + self.panes.handleWidth()
        return RAIL_W + side + least(self.stack.currentWidget()) + least(self.right_pane) + handles

    def _refuse_split(self, need):
        """필요한 폭은 창 폭 하나로 말한다(레일 + 두 화면 최소 폭, 탐색기·관련 항목은 나눌 때 접힌다)."""
        self.screen_notice("창 폭이 모자라 두 화면으로 나누지 않았습니다. 이 두 화면을 나누려면 창 폭이 %dpx 이상이어야 "
                           "합니다(지금 %dpx)." % (need + RAIL_W, self.width()))
        self.split_btn.setChecked(False)

    def screen_notice(self, text):
        """지금 화면에서만 뜻이 있는 상태줄 안내. 다른 화면으로 옮기면 지운다(go)."""
        self._screen_notice = text
        self.status_message(text)

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
            (cur_at_split, related_on), self.explorer_wanted, self._chat_open = restore[0], restore[1], restore[2]
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
        if self.set_drawing(scr.combo.currentText() or None):
            self._tab_follow(self.stack.currentIndex())
            self.refresh_related()

    def set_drawing(self, name):
        """지금 도면을 바꾼다(다음에 들어가는 ②④⑤가 이 도면을 연다). 바뀌었으면 True."""
        if not name or name == self.drawing:
            return False
        self.drawing = name
        self.selection = None
        self.invalidate_index()
        self._refresh_explorer()
        self._refresh_status()
        self._notify_chat()
        return True

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
        if self.related_shown[cur]:
            self._make_room()
        elif not self._chat_open:
            self._give_back()
        self._fit_explorer()
        self._size_panels()
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
        notice = getattr(self, "_screen_notice", None)
        if notice and index != self.stack.currentIndex():
            if self.msg_label.text() == notice:
                self.status_message("")
            self._screen_notice = None
        self.stack.setCurrentIndex(index)
        self.step_buttons[index].setChecked(True)
        scr = self.screens[index]
        if not self._split_uses_canvas():
            if getattr(scr, "canvas_host", None) is None:
                self.webview.setParent(None)
                self.webview.hide()
            self.webview.clear_segments()  # ④ 구간 색은 ④에서만 보인다(④는 on_enter에서 다시 칠함)
            self.webview.set_chips([])  # 도면 연결점 칩도 ②④에서만(on_enter에서 다시 닮)
            self.webview.set_edit_mode(False)  # ② 편집은 ②에서만(②는 on_enter에서 다시 켬)
        scr.on_enter()
        self._focus_main(scr)
        if index in DRAWING_SCREENS and scr.combo.currentText() and scr.combo.currentText() != self.drawing:
            self.drawing = scr.combo.currentText()
            self.selection = None
        self.invalidate_index()
        self._refresh_status()  # 상태줄 개수도 방금 읽은 화면 상태를 따른다(확정 해제 뒤 옛 '미검토'가 남지 않게)
        self._tab_follow(index)
        self.update_header()
        self.refresh_stages()
        self._fit_explorer()
        self.refresh_related()
        self._notify_chat()
        return True

    @staticmethod
    def _focus_main(scr):
        """화면을 바꾸면 초점을 그 화면의 주 작업 영역으로 옮긴다(머리말 찾기 버튼에 남으면 화면 단축키가 듣지 않음)."""
        w = getattr(scr, "main_focus", None)
        w = w() if callable(w) else w
        if w is not None and w.isVisible():
            w.setFocus(Qt.OtherFocusReason)
        elif scr.isVisible():
            scr.setFocus(Qt.OtherFocusReason)

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

    def _chip_clicked(self, key):
        h = getattr(self.canvas_screen(), "on_chip", None)
        if h:
            h(key)

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
            self.screens[6].close_refused()
            event.ignore()
            return
        if not self.screens[6].shutdown():  # 진행 중인 AI 호출: 물은 뒤 기다리거나 끊고, 끝나면 다시 닫는다
            event.ignore()
            return
        self.screens[5].kill_review()  # ④ AI 구간 검토: 받은 호출은 이미 저장했다. 남은 호출은 끊는다
        self.chat_panel.shutdown()  # 채팅은 결과 파일을 쓰지 않으므로 진행 중 질문도 묻지 않고 끊는다
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

    def open_ai_settings(self, method=None):
        """'AI 연결 설정' 창. method를 주면 그 방식의 상세를 고른 채 연다(방식은 바꾸지 않음). 열 때 지금 방식을 다시
        확인한다(API 키는 연결 시험을 누를 때만, 화면 설계 §2.4)."""
        if self._key_dialog is None:  # 창 하나를 재사용한다(열린 동안 받은 확인 결과를 그대로 그림)
            self._key_dialog = SettingsDialog(self.api_keys, self, conn=self.ai_conn)
        dlg = self._key_dialog
        dlg.say("")
        dlg.select(method if method in dlg.pages else self.ai_conn.method)
        if self.ai_conn.method != "api":
            self.ai_conn.check()
        dlg.refresh()
        dlg.exec()
        self._update_conn_chip()
        return dlg

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

    def toast(self, text, undo=None, actions=(), ms=5000):
        """동작 결과 알림(U-07). undo는 인자 없는 함수로, 토스트의 [실행 취소]나 Ctrl+Z가 한 번 부른다.
        actions는 [(버튼 글, 함수)]로 토스트에 버튼을 더한다(예: 내보낸 파일 [열기]·[폴더 열기])."""
        self.toast_box.show_message(text, undo, ms, actions)

    def status_message(self, text):
        self.msg_label.setText(text)
        self.msg_label.setVisible(bool(text))
        self._fit_conn_chip()

    def mark_saved(self, utc_iso):
        """저장됨 표시. 저장된 자료가 바뀌었으므로 도면 색인(탐색기·관련 항목·팔레트)도 다시 읽는다."""
        self.saved_label.setText("● 저장됨 %s" % kst_text(utc_iso)[11:16])
        self.saved_label.setToolTip("최근 저장 %s" % kst_text(utc_iso))
        self.saved_label.show()
        self._fit_conn_chip()
        self.invalidate_index()
        self._refresh_explorer()
        self._refresh_status()
        if self.selection:
            self.refresh_related()

    def _task(self, label):
        self.task_label.setText("진행 중: %s" % label if label else "")
        self.task_label.setVisible(bool(label))
        self._fit_conn_chip()

    def _open_region(self):
        path, _ = QFileDialog.getOpenFileName(self, "구간 JSON", paths.folder("regions"), "JSON (*.json)")
        if path:
            scr = self.screens[2]
            i = scr.region_combo.findData(path)
            if i < 0:
                scr.region_combo.addItem(os.path.splitext(os.path.basename(path))[0], path)
                i = scr.region_combo.count() - 1
            scr.region_combo.setCurrentIndex(i)
            self.go(2)

    def _open_run_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "분석 실행 폴더", paths.output_root("analysis"))
        if d:
            self.open_run(d)

    def open_run(self, run_dir):
        self.go(2)
        return self.screens[2].open_run(run_dir)

    def about_text(self):
        return ("%s %s\n자원 루트: %s\n작업 루트: %s\n저장 루트: %s\n설정: %s\n"
                "%s\n\n제3자 라이선스 고지: %s\n%s"
                % (APP_NAME, APP_VERSION, paths.resource_root(), paths.work_root(), paths.store_root(),
                   self.settings_path or paths.settings_path(),
                   conn_view.ai_call_line(getattr(getattr(self, "ai_conn", None), "method", "api")),
                   paths.licenses_dir(), LICENSE_NOTE))

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
