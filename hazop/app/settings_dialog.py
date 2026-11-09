"""'AI 연결 설정' 창(디자인/AI연결-화면설계.md §3). 키는 화면·상태 문구·로그에 보이지 않는다(끝 4자리 hint만).

왼쪽 연결 방식 목록(Claude 구독, API 키, 디버그 실행이면 고정 응답)에서 고르면 오른쪽 상세만 바뀐다. 방식은
'이 방식으로 사용'을 눌러야 바뀐다(A2). 모델·키 선택·이름 변경·삭제는 지금처럼 바로 적용한다. 배포본은 목록 없이 API 키
상세만 보인다(§3.8). 상태 글자·아이콘·해결 띠는 conn_view 표에서 온다. 연결 확인·연결 시험은 AiConnection이 작업
스레드에서 돌려 창이 멈추지 않는다. AI 분석이 돌고 있으면 위에 잠금 띠를 띄우고 방식·모델·키 선택을 막는다(§3.7).
"""

import os

from PySide6.QtCore import QSize, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

from hazop.app import conn_view, tokens
from hazop.app.ai_conn import AiConnection
from hazop.app.conn_widgets import ConnBadge, ResolveBand, icon_pixmap
from hazop.app.widgets import TaskRunner, esc, kst_text, log_path
from hazop.study import claude_cli, claude_http
from hazop.study.ai_settings import AiPrefs
from hazop.study.apikey import clean_key, key_problem, mask

TARGET_HOST = claude_http.API_BASE.split("//", 1)[1]
SIZE, MIN_SIZE, SIDE_W = (760, 560), (720, 520), 220
BUNDLE_SIZE = (600, 560)

# '방법 보기' 창: (제목, 본문, 복사할 명령). 웹뷰는 외부 네트워크를 막으므로 주소는 글자로 적는다(§9.1)
HELP = {
    "login": ("로그인 방법", "명령 프롬프트나 PowerShell을 열고 아래 명령을 실행하세요. 브라우저가 열리면 구독 계정"
              "(Pro·Max)으로 로그인합니다. 로그인은 Claude Code에서 직접 하며, 앱은 계정 정보를 받지도 저장하지도 않습니다. "
              "끝나면 이 창에서 다시 확인을 누르세요.", "claude auth login"),
    "update": ("업데이트 방법", "명령 프롬프트나 PowerShell을 열고 아래 명령을 실행하세요. 끝나면 다시 확인을 누르세요.",
               "claude update"),
    "install": ("설치 방법", "PowerShell을 열고 아래 명령으로 네이티브 설치본을 설치하세요. npm으로 설치한 claude.cmd는 쓸 수 "
                "없습니다. 설치 안내 문서: https://code.claude.com/docs/en/setup", "irm https://claude.ai/install.ps1 | iex"),
    "privacy": ("학습 설정 확인 방법", "웹 브라우저에서 claude.ai에 로그인한 뒤 설정 › 개인정보에서 '모델 개선' 항목을 "
                "확인하세요. 보안 등급이 있는 자료를 분석하려면 이 항목을 끄는 것이 좋습니다.", ""),
}
ACTION_HELP = {"terminal_login": "login", "login_help": "login", "terminal_update": "update", "install_help": "install"}

TERMS_TITLE = "Claude 구독으로 분석하기 전에"
TERMS_LEAD = "이 PC에 설치하고 본인 계정으로 로그인한 Claude Code를 거쳐 본인 구독 사용량으로 AI 분석을 합니다."
TERMS_POINTS = (
    "본인 계정을 본인 PC에서 쓰는 경우만 해당합니다. 다른 사람의 계정이나 공용 계정으로 쓰지 마세요.",
    "Claude 구독은 소비자 약관을 따릅니다. claude.ai 개인정보 설정에서 '모델 개선'이 켜져 있으면 보낸 도면 정보가 학습에 "
    "쓰일 수 있습니다. 보안 등급이 있는 자료를 분석하기 전에 그 설정을 확인하세요.",
    "앱은 로그인 정보를 읽거나 저장하지 않습니다. 로그인은 Claude Code에서 직접 합니다.")
SUB_NOTES = ("구독 한도는 claude.ai와 Claude Code에서 쓰는 양과 함께 셉니다. 큰 분석을 돌리면 같은 시간대의 다른 작업이 먼저 "
             "한도에 닿을 수 있습니다.",
             "Claude 구독은 소비자 약관을 따릅니다. claude.ai 개인정보 설정에서 '모델 개선'이 켜져 있으면 보낸 도면 정보가 "
             "학습에 쓰일 수 있습니다. <a href='privacy'>설정 확인 방법</a>")
TO_METHOD = {"subscription": "Claude 구독으로", "api": "API 키로", "fixed": "고정 응답(시험)으로"}
LOCK_TITLE = "AI 분석이 돌고 있어 연결 방식과 모델을 바꿀 수 없습니다."
LOCK_TEXT = "실행이 끝나거나 실행을 취소한 뒤 바꾸세요."


def fixed_match_text(match):
    """고정 응답 '맞는 칸' 줄(화면 설계 §3.5·§9.3). match = (맞는 칸, 전체 칸) 또는 None(셀 수 없음)."""
    if not match:
        return "확정된 검토구간이 있고 응답 폴더가 준비되면 셉니다."
    n, total = match
    if not n:
        return "고른 폴더에 지금 검토구간에 맞는 응답이 없습니다. 다른 폴더를 고르세요."
    return "지금 검토구간의 %d칸 중 %d칸에 맞는 응답이 있습니다." % (total, n)


def usd(v):
    return ("$%.2f" % v) if v >= 0.1 else ("$%.3f" % v).rstrip("0")


def show_help(parent, kind):
    """'방법 보기' 창: 안내와 복사할 수 있는 명령. 앱이 명령을 대신 실행하지 않는다."""
    title, body, command = HELP[kind]
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(440)
    lay = QVBoxLayout(dlg)
    text = QLabel(body)
    text.setWordWrap(True)
    text.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(text)
    if command:
        row = QHBoxLayout()
        edit = QLineEdit(command)
        edit.setReadOnly(True)
        edit.setAccessibleName("명령")
        copy = QPushButton("명령 복사(&C)")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(command))
        row.addWidget(edit, 1)
        row.addWidget(copy)
        lay.addLayout(row)
    close = QPushButton("닫기")
    close.clicked.connect(dlg.accept)
    end = QHBoxLayout()
    end.addStretch(1)
    end.addWidget(close)
    lay.addLayout(end)
    dlg.exec()
    return dlg


class TermsDialog(QDialog):
    """구독 처음 사용(이용 조건 창, §3.6). 520×380. 확인란을 고를 때만 '확인하고 계속'을 누를 수 있다.
    choice: 'ok'(확인하고 계속) · 'api'(API 키로 분석…) · None(취소)."""

    def __init__(self, parent=None, context="run"):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle(TERMS_TITLE)
        self.resize(520, 380)
        self.setMinimumSize(520, 380)
        lay = QVBoxLayout(self)
        lead = QLabel(TERMS_LEAD)
        lead.setWordWrap(True)
        lay.addWidget(lead)
        points = QLabel("<ul style='margin:0 0 0 -24px'>%s</ul>" % "".join(
            "<li style='margin-bottom:6px'>%s</li>" % esc(t) for t in TERMS_POINTS))
        points.setWordWrap(True)
        points.setTextFormat(Qt.RichText)
        points.setAccessibleName(" ".join(TERMS_POINTS))
        lay.addWidget(points)
        self.agree = QCheckBox("위 내용을 확인했습니다")
        lay.addWidget(self.agree)
        note = QLabel("처음 한 번만 묻습니다." + (" 확인하면 AI 분석 시작 창으로 넘어갑니다." if context == "run" else ""))
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        self.ok_btn = QPushButton("확인하고 계속(&O)")
        self.ok_btn.setObjectName("primary")
        self.ok_btn.setEnabled(False)
        self.agree.toggled.connect(self.ok_btn.setEnabled)
        self.api_btn = QPushButton("API 키로 분석…")
        cancel = QPushButton("취소")
        self.ok_btn.clicked.connect(lambda: self._pick("ok"))
        self.api_btn.clicked.connect(lambda: self._pick("api"))
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        for b in (self.ok_btn, self.api_btn, cancel):
            row.addWidget(b)
        lay.addLayout(row)
        self.agree.setFocus()

    def _pick(self, choice):
        if choice == "ok" and not self.agree.isChecked():
            return
        self.choice = choice
        self.accept()


def ask_terms(parent, prefs, context="run", dialog=None):
    """이용 조건을 아직 확인하지 않았으면 창을 띄운다. 'ok'(확인, 시각 저장) · 'api' · None. 이미 확인했으면 'ok'.
    배포본에는 구독이 없으므로 부르지 않는다. dialog는 시험용 대역(exec()와 choice가 있는 객체)."""
    if prefs.terms_ack_at:
        return "ok"
    dlg = dialog or TermsDialog(parent, context)
    dlg.exec()
    if dlg.choice == "ok":
        prefs.ack_terms()
    return dlg.choice


def _muted(text="", wrap=True, rich=False):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(wrap)
    lab.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    return lab


class SettingsDialog(QDialog):
    def __init__(self, store, parent=None, opener=None, conn=None, debug=False):
        super().__init__(parent)
        self.store = store
        self.opener = opener
        self.conn = conn or AiConnection(AiPrefs(), store, debug=debug, opener=opener, parent=self)
        self.tasks = TaskRunner(self)  # 창이 직접 돌리는 작업은 없다. 시험이 기다리는 자리(옛 창과 같음)
        self.setWindowTitle("AI 연결 설정")
        self.methods = self.conn.methods()
        self.single = len(self.methods) == 1
        self.resize(*(BUNDLE_SIZE if self.single else SIZE))
        self.setMinimumSize(*((560, 520) if self.single else MIN_SIZE))
        self.viewed = self.conn.method
        self._said = ("", False)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        if not self.single:
            body.addWidget(self._side())
        self.stack = QStackedWidget()
        self.pages = {}
        for m in self.methods:
            self.pages[m] = {"subscription": self._sub_page, "api": self._api_page, "fixed": self._fixed_page}[m]()
            self.stack.addWidget(self.pages[m])
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(10)
        self.lock_band = self._lock_band()
        cl.addWidget(self.lock_band)
        if self.single:
            only = QLabel("이 배포본은 API 키로만 AI에 연결합니다.")
            only.setObjectName("bundle_note")
            only.setStyleSheet("QLabel#bundle_note { background: %s; border: 1px solid %s; border-radius: 4px; "
                               "padding: 6px 10px; color: %s; }" % (tokens.c("surface-2"), tokens.c("line"),
                                                                     tokens.c("muted")))
            cl.addWidget(only)
        cl.addWidget(self.stack)
        cl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        body.addWidget(scroll, 1)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.use_btn = QPushButton("이 방식으로 사용(&U)")
        self.use_btn.setObjectName("primary")
        self.use_btn.clicked.connect(self.use_viewed)
        self.use_btn.setVisible(not self.single)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        bottom = QFrame()
        bottom.setObjectName("dialog_foot")
        bottom.setStyleSheet("QFrame#dialog_foot { border-top: 1px solid %s; }" % tokens.c("line"))
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(14, 8, 14, 8)
        bl.addWidget(self.message_label, 1)
        bl.addWidget(self.use_btn)
        bl.addWidget(close_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(body, 1)
        lay.addWidget(bottom)
        self.conn.changed.connect(self.refresh)
        self.refresh()
        self.select(self.viewed)

    # ------------------------------------------------------------ 틀
    def _side(self):
        side = QFrame()
        side.setObjectName("conn_side")
        side.setFixedWidth(SIDE_W)
        side.setStyleSheet("QFrame#conn_side { background: %s; border-right: 1px solid %s; }"
                           "QListWidget#conn_list { background: transparent; border: 0; }"
                           "QListWidget#conn_list::item { border: 1px solid transparent; border-radius: 4px; "
                           "margin: 2px 0; }"
                           "QListWidget#conn_list::item:selected { background: %s; border: 1.5px solid %s; }"
                           % (tokens.c("surface-2"), tokens.c("line"), tokens.c("ui-weak"), tokens.c("ui")))
        lay = QVBoxLayout(side)
        lay.setContentsMargins(8, 12, 8, 10)
        lab = _muted("연결 방식(&W)")
        lab.setTextFormat(Qt.AutoText)
        self.method_list = QListWidget()
        self.method_list.setObjectName("conn_list")
        self.method_list.setAccessibleName("연결 방식")
        lab.setBuddy(self.method_list)
        self.items = {}
        for m in self.methods:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, m)
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(8, 6, 8, 6)
            wl.setSpacing(2)
            name = QLabel(conn_view.METHOD_NAMES[m])
            name.setStyleSheet("font-weight: 700; background: transparent")
            line = QHBoxLayout()
            line.setSpacing(4)
            icon, text = QLabel(), QLabel()
            text.setStyleSheet("background: transparent")
            line.addWidget(icon)
            line.addWidget(text, 1)
            wl.addWidget(name)
            wl.addLayout(line)
            it.setSizeHint(QSize(SIDE_W - 20, 2 * self.fontMetrics().height() + 22))
            self.method_list.addItem(it)
            self.method_list.setItemWidget(it, w)
            self.items[m] = (it, icon, text)
        self.method_list.currentRowChanged.connect(lambda r: r >= 0 and self.select(self.methods[r]))
        lay.addWidget(lab)
        lay.addWidget(self.method_list, 1)
        if "fixed" not in self.methods and "subscription" in self.methods:
            lay.addWidget(_muted("고정 응답(시험)은 디버그 실행에서만 보입니다."))
        return side

    def _lock_band(self):
        band = QFrame()
        band.setObjectName("lock_band")
        band.setStyleSheet("QFrame#lock_band { background: %s; border: 1px solid %s; border-radius: 4px; }"
                           % (tokens.c("surface-2"), tokens.c("line-strong")))
        band.setAccessibleName("알림: " + LOCK_TITLE)
        bl = QVBoxLayout(band)
        bl.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(icon_pixmap("dots", "ink-2"))
        title = QLabel(LOCK_TITLE)
        title.setStyleSheet("font-weight: 700")
        title.setWordWrap(True)
        head.addWidget(icon)
        head.addWidget(title, 1)
        self.cancel_run_btn = QPushButton("실행 취소")
        self.cancel_run_btn.clicked.connect(self.conn.cancel_run)
        row = QHBoxLayout()
        row.addWidget(self.cancel_run_btn)
        row.addStretch(1)
        bl.addLayout(head)
        bl.addWidget(_muted(LOCK_TEXT))
        bl.addLayout(row)
        band.hide()
        return band

    def _head(self, page_lay, method):
        row = QHBoxLayout()
        title = QLabel(conn_view.METHOD_NAMES[method])
        title.setStyleSheet("font-weight: 700; font-size: %dpx" % tokens.FONT_SIZE["lg"])
        badge = QLabel("사용 중")
        badge.setObjectName("in_use")
        badge.setStyleSheet("QLabel#in_use { background: %s; color: %s; border-radius: 3px; padding: 1px 6px; "
                            "font-weight: 700; }" % (tokens.c("human-line"), tokens.c("on-fill")))
        row.addWidget(title)
        row.addWidget(badge)
        row.addStretch(1)
        page_lay.addLayout(row)
        cost = QLabel(conn_view.METHOD_COST[method])
        cost.setWordWrap(True)
        page_lay.addWidget(cost)
        return badge

    def _card(self, chip, button):
        card = QFrame()
        card.setObjectName("panel")
        cl = QVBoxLayout(card)
        top = QHBoxLayout()
        when = _muted(wrap=False)
        top.addWidget(chip)
        top.addWidget(when)
        top.addStretch(1)
        top.addWidget(button)
        cl.addLayout(top)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        return card, when, grid

    @staticmethod
    def _grid_row(grid, r, name, widget):
        lab = _muted(name, wrap=False)
        grid.addWidget(lab, r, 0, Qt.AlignTop)
        grid.addWidget(widget, r, 1)

    def _sub_page(self):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.sub_badge = self._head(pl, "subscription")
        self.sub_chip = ConnBadge()
        self.sub_check_btn = QPushButton("연결 확인(&T)")
        self.sub_check_btn.clicked.connect(lambda: self.conn.check("subscription"))
        card, self.sub_when, grid = self._card(self.sub_chip, self.sub_check_btn)
        prog = QWidget()
        prl = QHBoxLayout(prog)
        prl.setContentsMargins(0, 0, 0, 0)
        self.prog_label = QLabel()
        self.prog_label.setWordWrap(True)
        self.prog_btn = QPushButton("위치 지정…")
        self.prog_btn.clicked.connect(lambda: self.on_action("locate"))
        prl.addWidget(self.prog_label, 1)
        prl.addWidget(self.prog_btn, 0, Qt.AlignTop)
        self.account_label = QLabel()
        usage = QWidget()
        ul = QHBoxLayout(usage)
        ul.setContentsMargins(0, 0, 0, 0)
        self.usage_bar = QProgressBar()
        self.usage_bar.setFixedSize(120, 6)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setRange(0, 100)
        self.usage_label = QLabel()
        self.usage_label.setWordWrap(True)
        ul.addWidget(self.usage_bar, 0, Qt.AlignVCenter)
        ul.addWidget(self.usage_label, 1)
        self._grid_row(grid, 0, "프로그램", prog)
        self._grid_row(grid, 1, "계정", self.account_label)
        self._grid_row(grid, 2, "사용량", usage)
        pl.addWidget(card)
        self.sub_band = ResolveBand()
        self.sub_band.action.connect(self.on_action)
        pl.addWidget(self.sub_band)
        self.sub_model = QComboBox()
        for mid in claude_http.MODELS:
            self.sub_model.addItem("%s · %s" % (conn_view.model_name(mid), conn_view.SUB_MODEL_COST[mid]), mid)
        self.sub_model.activated.connect(lambda i: self._set_model("subscription", self.sub_model.itemData(i)))
        form = QFormLayout()
        lab = QLabel("모델(&M)")
        lab.setBuddy(self.sub_model)
        form.addRow(lab, self.sub_model)
        pl.addLayout(form)
        for t in SUB_NOTES:
            n = _muted(t, rich="<a" in t)
            n.linkActivated.connect(lambda _h: show_help(self, "privacy"))
            pl.addWidget(n)
        self.terms_note = _muted("구독으로 처음 분석할 때 이용 조건을 한 번 확인합니다.")
        pl.addWidget(self.terms_note)
        return page

    def _api_page(self):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.api_badge = self._head(pl, "api")
        self.state_chip = ConnBadge()
        self.test_btn = QPushButton("연결 시험(&T)")
        self.test_btn.setObjectName("primary")
        self.test_btn.clicked.connect(self.test_connection)
        card, self.api_when, grid = self._card(self.state_chip, self.test_btn)
        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.RichText)
        grid.addWidget(self.detail_label, 0, 0, 1, 2)
        pl.addWidget(card)
        self.api_band = ResolveBand()
        self.api_band.action.connect(self.on_action)
        pl.addWidget(self.api_band)

        self.key_combo = QComboBox()
        self.key_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.key_combo.setMinimumContentsLength(20)
        self.key_combo.activated.connect(self._select_key)
        self.rename_btn = QPushButton("이름 변경(&R)")
        self.delete_btn = QPushButton("삭제(&D)…")
        self.rename_btn.clicked.connect(self.rename_key)
        self.delete_btn.clicked.connect(self.delete_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_combo, 1)
        key_row.addWidget(self.rename_btn)
        key_row.addWidget(self.delete_btn)
        self.model_combo = QComboBox()
        for mid, m in claude_http.MODELS.items():
            self.model_combo.addItem(m["label"], mid)
        self.model_combo.activated.connect(self._select_model)
        self.price_label = _muted()
        use = QFormLayout()
        key_lab, model_lab = QLabel("사용할 키(&K)"), QLabel("모델(&M)")
        key_lab.setBuddy(self.key_combo)
        model_lab.setBuddy(self.model_combo)
        use.addRow(key_lab, key_row)
        use.addRow(model_lab, self.model_combo)
        use.addRow("", self.price_label)
        pl.addLayout(use)

        self.add_toggle = QToolButton()
        self.add_toggle.setText("새 키 추가")
        self.add_toggle.setCheckable(True)
        self.add_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.add_toggle.setArrowType(Qt.RightArrow)
        self.add_toggle.setStyleSheet("QToolButton { border: 0; font-weight: 700; background: transparent; }")
        self.add_toggle.toggled.connect(self._show_add)
        pl.addWidget(self.add_toggle)
        self.add_box = QWidget()
        al = QVBoxLayout(self.add_box)
        al.setContentsMargins(0, 0, 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 회사 워크스페이스, 개인 시험용")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-ant-…  붙여 넣기(공백은 자동 정리)")
        self.key_edit.returnPressed.connect(self.add_key)
        self.show_btn = QPushButton("보기(&V)")
        self.show_btn.setCheckable(True)
        self.show_btn.toggled.connect(self._toggle_echo)
        self.persist_box = QCheckBox("이 PC에 저장(Windows 암호화, 현재 사용자만 읽음)")
        self.persist_box.setChecked(True)
        self.add_btn = QPushButton("추가하고 시험(&A)")
        self.add_btn.clicked.connect(self.add_key)
        key_in = QHBoxLayout()
        key_in.addWidget(self.key_edit, 1)
        key_in.addWidget(self.show_btn)
        add = QFormLayout()
        name_lab, keyin_lab = QLabel("이름(&N)"), QLabel("API 키(&P)")
        name_lab.setBuddy(self.name_edit)
        keyin_lab.setBuddy(self.key_edit)
        add.addRow(name_lab, self.name_edit)
        add.addRow(keyin_lab, key_in)
        persist_row = QHBoxLayout()
        persist_row.addWidget(self.persist_box, 1)
        persist_row.addWidget(self.add_btn)
        add.addRow("", persist_row)
        help_label = _muted(
            "키는 <a href='%s'>Anthropic Console › API keys</a>에서 발급합니다. 워크스페이스를 먼저 고른 뒤 "
            "<b>Create Key</b>를 누르고, 한 번만 보이는 키를 복사해 붙여 넣으세요. 키 전체는 이 창에 다시 보이지 않고 "
            "끝 4자리로만 구분합니다." % claude_http.CONSOLE_KEYS_URL, rich=True)
        help_label.setOpenExternalLinks(True)
        al.addLayout(add)
        al.addWidget(help_label)
        pl.addWidget(self.add_box)
        self.add_box.hide()
        return page

    def _fixed_page(self):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.fixed_badge = self._head(pl, "fixed")
        self.fixed_chip = ConnBadge()
        check = QPushButton("다시 확인")
        check.clicked.connect(lambda: self.conn.check("fixed"))
        card, self.fixed_when, grid = self._card(self.fixed_chip, check)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.fixed_path = QLabel()
        self.fixed_path.setWordWrap(True)
        self.fixed_btn = QPushButton("찾아보기…")
        self.fixed_btn.clicked.connect(lambda: self.on_action("browse"))
        rl.addWidget(self.fixed_path, 1)
        rl.addWidget(self.fixed_btn)
        lab = _muted("응답 폴더(&F)", wrap=False)
        lab.setTextFormat(Qt.AutoText)
        lab.setBuddy(self.fixed_btn)
        grid.addWidget(lab, 0, 0)
        grid.addWidget(row, 0, 1)
        self.fixed_match = QLabel()
        self.fixed_match.setWordWrap(True)
        grid.addWidget(_muted("맞는 칸", wrap=False), 1, 0)
        grid.addWidget(self.fixed_match, 1, 1)
        pl.addWidget(card)
        self.fixed_band = ResolveBand()
        self.fixed_band.action.connect(self.on_action)
        pl.addWidget(self.fixed_band)
        pl.addWidget(_muted("시험 결과는 실제 결과와 따로 시험용 파일에 저장합니다. 실제 검토 결과로 쓰지 마세요."))
        return page

    # ------------------------------------------------------------ 표시
    def select(self, method):
        """왼쪽 목록에서 고른 방식의 상세를 보인다. 방식은 바꾸지 않는다."""
        if method not in self.pages:
            return
        self.viewed = method
        self.stack.setCurrentWidget(self.pages[method])
        if not self.single and self.method_list.currentRow() != self.methods.index(method):
            self.method_list.setCurrentRow(self.methods.index(method))
        self._show_use()
        self._show_message()

    def refresh(self):
        current = self.conn.method
        for m in self.methods:
            st = self.conn.status(m)
            lk = conn_view.look(m, st["state"])
            if not self.single:
                it, icon, text = self.items[m]
                icon.setPixmap(icon_pixmap(lk.icon, "ink-2"))
                text.setText(lk.label + (" · 사용 중" if m == current else ""))
                it.setData(Qt.AccessibleTextRole, conn_view.list_accessible(m, st, m == current))
        if "subscription" in self.pages:
            self._show_sub()
        if "api" in self.pages:
            self._show_api()
        if "fixed" in self.pages:
            self._show_fixed()
        for m, badge in (("subscription", getattr(self, "sub_badge", None)), ("api", getattr(self, "api_badge", None)),
                         ("fixed", getattr(self, "fixed_badge", None))):
            if badge is not None:
                badge.setVisible(m == current)
        running = self.conn.running
        self.lock_band.setVisible(running)
        self.cancel_run_btn.setEnabled(self.conn.cancel_handler is not None)
        for w in (getattr(self, "sub_model", None), getattr(self, "model_combo", None),
                  getattr(self, "key_combo", None), getattr(self, "delete_btn", None)):
            if w is not None and running:
                w.setEnabled(False)
        self._show_use()
        self._show_message()

    def _set_chip(self, chip, when, method, status):
        lk = conn_view.look(method, status["state"])
        name, desc = conn_view.status_accessible(method, status)
        chip.set_look(lk, lk.label, name, desc)
        when.setText(conn_view.checked_text(status))
        return lk

    def _band(self, band, method, status, labels=None):
        lk = conn_view.look(method, status["state"])
        if lk.can_start or status["state"] == "checking":
            band.hide()
            return
        actions = [a for a in lk.actions if a != "to_api" or "api" in self.methods]
        band.set_band(lk, conn_view.guide_text(method, status, self.conn.fixed_count()), actions, labels)

    def _show_sub(self):
        st = self.conn.status("subscription")
        self._set_chip(self.sub_chip, self.sub_when, "subscription", st)
        self.sub_check_btn.setEnabled(st["state"] != "checking")
        path, found = claude_cli.find_cli(self.conn.prefs.cli_path)
        if path:
            self.prog_label.setText(path)
            self.prog_btn.setText("위치 지정…")
        else:
            self.prog_label.setText("찾지 못함" if found == "not_installed" else "npm 설치본만 찾음(claude.cmd)")
            self.prog_btn.setText("설치 방법 보기")
        self.prog_btn.clicked.disconnect()
        self.prog_btn.clicked.connect(lambda: self.on_action("locate" if path else "install_help"))
        state = st["state"]
        plan = conn_view.plan_name(st.get("plan"))
        if state in ("login_required",):
            self.account_label.setText("로그인 안 됨")
        elif state == "login_expired":
            self.account_label.setText("로그인 기간 끝남")
        elif state == "not_subscription":
            self.account_label.setText("구독이 아닌 계정으로 로그인됨")
        elif plan or state in ("ok", "limit_warning", "limit_reached", "overage_risk"):
            self.account_label.setText("로그인됨" + (" · " + plan if plan else ""))
        else:
            self.account_label.setText("—")
        lines = conn_view.usage_lines(st.get("limit"))
        text, say, warn = lines[0]
        util = (st.get("limit") or {}).get("utilization")
        self.usage_bar.setVisible(util is not None)
        if util is not None:
            self.usage_bar.setValue(round(util * 100))
        self.usage_label.setText(text + ("\n" + warn if warn else ""))
        self.usage_label.setAccessibleName(say)
        self._band(self.sub_band, "subscription", st)
        self.sub_model.setCurrentIndex(self.sub_model.findData(self.conn.model("subscription")))
        self.sub_model.setEnabled(not self.conn.running)
        self.terms_note.setVisible(not self.conn.terms_acked())

    def _show_api(self):
        entries = self.store.entries()
        self.key_combo.clear()
        for e in entries:
            where = "이 PC 저장" if e["persisted"] else "이번 실행만"
            self.key_combo.addItem("%s  (%s · %s)" % (e["name"], e["hint"], where), e["id"])
            if e["active"]:
                self.key_combo.setCurrentIndex(self.key_combo.count() - 1)
        if not entries:
            self.key_combo.addItem("키 없음. 아래에서 추가하세요", None)
        for w in (self.key_combo, self.rename_btn, self.delete_btn):
            w.setEnabled(bool(entries))
        self.model_combo.setCurrentIndex(self.model_combo.findData(self.store.model))
        self.model_combo.setEnabled(not self.conn.running)
        m = claude_http.MODELS[self.store.model]
        p = claude_http.PRICES[self.store.model]
        basis = "실측" if self.store.model == claude_http.DEFAULT_MODEL else "추정, Opus 실측을 단가 비율로 환산"
        self.price_label.setText("백만 토큰당 입력 %s · 출력 %s. 검토구간 1개 분석에 약 %s(%s)."
                                 % (usd(p["input"]), usd(p["output"]), usd(m["section_usd"]), basis))
        st = self.conn.status("api")
        self._set_chip(self.state_chip, self.api_when, "api", st)
        self.test_btn.setEnabled(bool(entries) and st["state"] != "checking")
        e = self.store.active()
        rows = []
        if e:
            rows.append("<b>키</b> %s (%s) · %s" % (esc(e["name"]), esc(e["hint"]),
                                                   "이 PC에 암호화 저장" if e["persisted"] else "이번 실행만(저장 안 함)"))
        rows.append("<b>대상</b> Anthropic API %s · 모델 %s · API 버전 %s"
                    % (TARGET_HOST, self.store.model, claude_http.API_VERSION))
        t = e and e["last_test"]
        if t:
            rows.append("<b>마지막 시험</b> %s · %s%s" % (
                kst_text(t["at"]), "성공" if t["ok"] else "실패",
                "" if t.get("model") == self.store.model else " (다른 모델 %s로 시험함)" % esc(t.get("model") or "?")))
        elif e:
            rows.append("아직 연결 시험을 하지 않았습니다. <b>연결 시험</b>을 누르세요(토큰 비용 없음).")
        else:
            rows.append("아래 <b>새 키 추가</b>에서 키를 넣으세요.")
        if self.store.load_error:
            rows.append("<span style='color:%s'>%s</span>" % (tokens.c("err-ink"), esc(self.store.load_error)))
        self.detail_label.setText("<br>".join(rows))
        self._band(self.api_band, "api", st, {"test": "연결 시험"})
        if not entries and not self.add_toggle.isChecked():
            self.add_toggle.setChecked(True)

    def _show_fixed(self):
        st = self.conn.status("fixed")
        self._set_chip(self.fixed_chip, self.fixed_when, "fixed", st)
        if st["state"] == "ok":
            self.fixed_chip.set_look(self.fixed_chip.lk, "준비됨 · 응답 %d개" % self.conn.fixed_count(),
                                     *conn_view.status_accessible("fixed", st))
        self.fixed_path.setText(self.conn.prefs.fixed_dir or "고르지 않음")
        self.fixed_match.setText(fixed_match_text(self.conn.fixed_match() if self.conn.fixed_match and st["state"] == "ok"
                                                  else None))
        self._band(self.fixed_band, "fixed", st)

    def _show_use(self):
        in_use = self.viewed == self.conn.method
        self.use_btn.setText("사용 중" if in_use else "이 방식으로 사용(&U)")
        self.use_btn.setEnabled(not in_use and not self.conn.running)

    def _show_message(self):
        text, error = self._said
        if not text:
            if self.conn.running:
                text = "실행 중에는 모델 선택과 '이 방식으로 사용'을 쓸 수 없습니다."
            elif self.viewed != self.conn.method:
                text = "보기만 하는 중입니다. 지금 쓰는 방식은 %s입니다." % conn_view.METHOD_NAMES[self.conn.method]
        self.message_label.setStyleSheet("color: %s" % tokens.c("err-ink" if error else "muted"))
        self.message_label.setText(text)

    def say(self, text, error=False):
        self._said = (text, error)
        self._show_message()

    def _toggle_echo(self, on):
        self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self.show_btn.setText("숨기기(&V)" if on else "보기(&V)")

    def _show_add(self, on):
        self.add_box.setVisible(on)
        self.add_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    # ------------------------------------------------------------ 방식 바꾸기
    def use_viewed(self):
        """'이 방식으로 사용'. API 키로 바꿀 때만 요금 확인, 구독은 처음 한 번 이용 조건 창."""
        m = self.viewed
        if self.conn.running or m == self.conn.method:
            return False
        if m == "api" and not self._ask_api_switch():
            return False
        if m == "subscription":
            choice = ask_terms(self, self.conn.prefs, "settings", self._terms_dialog())
            if choice == "api":
                self.select("api")
                return False
            if choice != "ok":
                return False
        switched = "%s 바꿨습니다." % TO_METHOD[m]
        self.say(switched + " 연결을 확인하는 중입니다.")

        def checked(status):
            lk = conn_view.look(m, status["state"])
            if lk.can_start:
                self.say(switched)
            else:
                self.say("%s %s. 해결한 뒤 AI를 실행할 수 있습니다." % (switched, lk.title), True)

        self.conn.prefs.choose(m)
        self.conn.changed.emit()
        self.conn.check(m, checked)
        return True

    def _terms_dialog(self):
        return None  # 시험에서 대역으로 바꿔 끼운다

    def _ask_api_switch(self):
        model = conn_view.model_name(self.store.model)
        cost = usd(claude_http.MODELS[self.store.model]["section_usd"])
        box = QMessageBox(QMessageBox.Question, "API 키로 바꾸기",
                          "API 키로 바꾸면 호출마다 요금이 나갑니다. 지금 모델(%s)로 검토구간 1개를 분석하면 약 %s입니다. "
                          "바꿀까요?" % (model, cost), parent=self)
        yes = box.addButton("API 키로 바꾸기", QMessageBox.AcceptRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _set_model(self, method, model):
        if self.conn.running:
            return
        try:
            self.conn.set_model(method, model)
        except OSError as exc:
            self.say("설정 파일에 쓰지 못함: %s" % exc, True)
            return
        self.say("모델을 바꿈." + (" 새 모델로 연결 시험을 해 보세요." if method == "api" else ""))

    # ------------------------------------------------------------ 해결 동작
    def on_action(self, name):
        if name in ACTION_HELP:
            show_help(self, ACTION_HELP[name])
        elif name == "check":
            if self.viewed == "api":
                self.test_connection()
            else:
                self.conn.check(self.viewed)
        elif name == "test":
            self.test_connection()
        elif name == "to_api":
            self.select("api")
            self.use_btn.setFocus()
        elif name == "locate":
            path, _ = QFileDialog.getOpenFileName(self, "Claude Code 실행 파일", self.conn.prefs.cli_path or "",
                                                  "실행 파일 (claude.exe)")
            if path:
                self.conn.prefs.set_cli_path(path)
                self.conn.check("subscription")
        elif name == "browse":
            folder = QFileDialog.getExistingDirectory(self, "고정 응답 폴더", self.conn.prefs.fixed_dir or "")
            if folder:
                self.conn.prefs.set_fixed_dir(folder)
                self.conn.check("fixed")
        elif name == "copy_error":
            QGuiApplication.clipboard().setText(self.error_report(self.viewed))
            self.say("오류 내용을 복사했습니다.")
        elif name == "open_logs":
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(log_path())))
        elif name == "add_key":
            self.add_toggle.setChecked(True)
            self.key_edit.setFocus()

    def error_report(self, method):
        """'오류 내용 복사': 방식·상태·내용·확인 시각만. 계정 이메일·조직 ID·키는 넣지 않는다."""
        st = self.conn.status(method)
        return "AI 연결 오류\n방식: %s\n상태: %s\n내용: %s\n확인 시각: %s" % (
            conn_view.METHOD_NAMES[method], st["state"], mask(st.get("detail") or "", self.store.get()),
            st.get("checked_at") or "")

    # ------------------------------------------------------------ API 키 동작(지금 창과 같음)
    def _apply(self, fn, done_text):
        """저장소를 바꾸는 동작. 파일 쓰기·암호화 실패는 창에 알린다(화면과 파일이 어긋난 채 조용히 넘어가지 않게)."""
        try:
            fn()
        except OSError as exc:
            self.conn.refresh()
            self.say(mask("설정 파일에 쓰지 못함: %s" % exc, self.store.get()), True)
            return False
        self.conn.refresh()
        self.say(done_text)
        return True

    def _select_key(self, i):
        kid = self.key_combo.itemData(i)
        if kid and not self.conn.running:
            self._apply(lambda: self.store.select(kid), "사용할 키를 바꿈.")

    def _select_model(self, i):
        model = self.model_combo.itemData(i)
        if not self.conn.running:
            self._apply(lambda: self.store.set_model(model), "모델을 바꿈. 새 모델로 연결 시험을 해 보세요.")

    def add_key(self):
        key = clean_key(self.key_edit.text())
        if not key:
            self.say("추가할 키를 붙여 넣으세요.", True)
            return
        try:
            self.store.add(self.name_edit.text(), key, persist=self.persist_box.isChecked())
        except ValueError as exc:  # key_problem 문구(키 값 없음)
            self.say(str(exc), True)
            return
        except OSError as exc:
            self.say(mask("키를 암호화해 저장하지 못함: %s" % exc, key), True)
            return
        self.key_edit.clear()
        self.name_edit.clear()
        self.show_btn.setChecked(False)
        self.say("키를 추가함.")
        self.conn.refresh()
        self.test_connection()

    def rename_key(self):
        e = self.store.active()
        if not e:
            return
        name = self._ask_name(e["name"])
        if name and name.strip():
            self._apply(lambda: self.store.rename(e["id"], name), "이름을 바꿈.")

    def delete_key(self):
        e = self.store.active()
        if not e or self.conn.running or not self._ask_delete(e):
            return
        self._apply(lambda: self.store.remove(e["id"]), "'%s' 키를 지움." % e["name"])

    def clear_key(self):
        """사용 중인 키를 확인 없이 지운다(스크립트·테스트용)."""
        self.store.clear()
        self.conn.refresh()

    def test_connection(self):
        """API 키 연결 시험(작업 스레드, 토큰 비용 없음). 결과는 키별로 저장되고 상태 칸에 보인다."""
        e = self.store.active()
        key = self.store.get()
        if not key:
            self.say("시험할 키가 없음. 키를 추가하세요.", True)
            return
        if key_problem(key):
            self.say(key_problem(key), True)
            return
        self.say("연결 시험 중… (%s, 모델 %s)" % (e["name"], self.store.model))

        def finish(status):
            ok = status["state"] == "ok"
            self.say("연결 시험 성공." if ok else "연결 시험 실패. 위의 안내를 확인하세요.", not ok)

        self.conn.check("api", finish)

    # ------------------------------------------------------------ 확인 창(테스트에서 바꿔 끼움)
    def _ask_name(self, current):
        name, ok = QInputDialog.getText(self, "키 이름 변경", "새 이름", text=current)
        return name if ok else None

    def _ask_delete(self, e):
        return QMessageBox.question(
            self, "키 삭제", "'%s' (%s) 키를 지울까요?\n이 PC에 저장한 암호화 사본도 지워지며 되돌릴 수 없습니다."
            % (e["name"], e["hint"])) == QMessageBox.Yes

    def _ask_discard(self):
        return QMessageBox.question(
            self, "추가하지 않은 키", "입력한 키를 아직 추가하지 않았습니다. 버리고 닫을까요?") == QMessageBox.Yes

    def done(self, r):
        if self.key_edit.text().strip() and not self._ask_discard():
            return
        self.key_edit.clear()
        super().done(r)
