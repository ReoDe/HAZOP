"""오른쪽 채팅 창의 내용물(단위 C2, docs/specs/chat-panel.md §5·§7·§8).

입력 칸(Enter로 보내기), 비었을 때 종류별 예시 질문, 모델 드롭다운(빠름·보통·깊게), 진행 표시와 멈추기, 답 카드, 구독이 없는
PC의 안내를 보인다. 대화는 저장하지 않는다(창을 닫으면 사라짐). 채팅 세션은 `session_factory(model, callbacks)`로 받는다
(`hazop.chat.view.SessionPort` 모양). 세션의 콜백은 읽기 스레드에서 오므로 Qt 신호로 넘겨 받는다.
카드 검사는 `hazop.chat.card`, 도면 변환은 `hazop.chat.view`가 하고, 여기서는 그리기와 뷰어 호출만 한다.
"""

import json
import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from hazop.app import tokens
from hazop.chat import card as cardmod
from hazop.chat import view as chatview

MODELS = (("빠름", "fast"), ("보통", "normal"), ("깊게", "deep"))
MODEL_NAME = {key: name for name, key in MODELS}
GUIDE_BUTTONS = {"install": "설치 방법 보기", "login": "로그인 창 열기", "enable": "켜기"}
INPUT_HINT = "도면에 대해 물어보세요 (Enter로 보내기, Shift+Enter로 줄 바꾸기)"


class _NoEnv(cardmod.CardEnv):
    """프로젝트 자료를 아직 못 읽을 때: 아무것도 확인하지 않는다(모든 항목이 '프로젝트에 없음'으로 빠진다)."""

    def component(self, ref):
        return None

    def exists(self, kind, ident):
        return False

    def describe(self, ident):
        return None

    def reasons(self, ident):
        return set()

    def path_steps(self, path_ref):
        return None


class FlowLayout(QLayout):
    """칩이 폭을 넘으면 다음 줄로 넘기는 배치(Qt 예제와 같은 방식)."""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        x0, y = rect.x() + m.left(), rect.y() + m.top()
        right = rect.right() - m.right()
        x, row_h = x0, 0
        sp = self.spacing()
        for it in self._items:
            w = it.sizeHint()
            width = min(w.width(), max(40, right - x0 + 1))
            if x + width - 1 > right and row_h > 0:
                x, y, row_h = x0, y + row_h + sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), QSize(width, w.height())))
            x += width + sp
            row_h = max(row_h, w.height())
        return y + row_h - rect.y() + m.bottom()


class WrapButton(QPushButton):
    """글이 길면 줄을 바꾸는 단추(예시 질문). 그려지는 글은 안의 라벨이고 text()는 원래 글을 돌려준다."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label.setTextFormat(Qt.PlainText)
        lay.addWidget(self.label)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.setToolTip(_tip(text))

    def text(self):  # noqa: A003
        return self._text

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, w):  # noqa: N802
        return self.layout().totalHeightForWidth(w)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(60, self.label.minimumSizeHint().height() + 8)


def _tip(text):
    """툴팁은 Qt가 리치 텍스트로 자동 판별하므로, 도면 태그·오류 글이 들어가면 이스케이프한 한 덩어리로 보낸다."""
    plain = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "<span>%s</span>" % plain


def _plain_all(widget):
    """위젯 안의 모든 라벨을 일반 글로 고정한다(모델·도면·오류에서 온 글이 리치 텍스트로 해석되지 않게)."""
    for lab in widget.findChildren(QLabel):
        lab.setTextFormat(Qt.PlainText)


def _label(text, name=None, wrap=True):
    lab = QLabel(text)
    lab.setTextFormat(Qt.PlainText)  # 모델이 낸 글은 해석하지 않는다(마크다운·HTML 없음)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if name:
        lab.setObjectName(name)
    lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
    return lab


class CardWidget(QFrame):
    """답 카드 하나(§5.3). 검사가 끝난 `Card`만 받는다."""

    chipClicked = Signal(str, str)      # (구성요소 ID, 도면 graph_id)
    sheetClicked = Signal(int, str)     # (경로 번호, 도면 graph_id)

    def __init__(self, card, footer, parent=None):
        super().__init__(parent)
        self.card = card
        self.setObjectName("chat_card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("QFrame#chat_card { background: %s; border: 1px solid %s; border-radius: 6px; }"
                           % (tokens.c("card"), tokens.c("line")))
        self._expanded = set()
        self._path_boxes = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(4)
        for b in card.badges:
            chip = QLabel(b)
            chip.setObjectName("chip")
            head.addWidget(chip)
        if card.no_evidence:
            head.addWidget(QLabel("도면·문서에서 확인한 내용 없음"))
        head.addStretch(1)
        if card.badges or card.no_evidence:
            lay.addLayout(head)
        if card.text.strip():
            lay.addWidget(_label(card.text, "chat_text"))
        for i, p in enumerate(card.paths):
            box = QWidget()
            self._path_boxes.append(box)
            lay.addWidget(box)
            self._fill_path(i, p)
        for n in card.path_notes:
            note = _label(n, "chat_note")
            note.setStyleSheet("color: %s;" % tokens.c("muted"))
            lay.addWidget(note)
        if card.warnings:
            warn = QFrame()
            warn.setObjectName("chat_warn")
            warn.setStyleSheet("QFrame#chat_warn { background: %s; border: 1px solid %s; border-radius: 4px; } QLabel { color: %s; }"
                               % (tokens.c("warn-bg"), tokens.c("warn-line"), tokens.c("warn-ink")))
            wl = QVBoxLayout(warn)
            wl.setContentsMargins(8, 4, 8, 4)
            wl.setSpacing(2)
            for w in card.warnings:
                row = QHBoxLayout()
                row.setSpacing(4)
                text = "⚠ 경로에 " + w["text"] if w.get("scope") == "path" and w["reason"] != "valve_position_ignored" else "⚠ " + w["text"]
                line = _label(text, "chat_warn_line")
                row.addWidget(line, 1)
                toggle = QPushButton("대상 ▾")
                toggle.setObjectName("chat_warn_toggle")
                toggle.setFlat(True)
                targets = _label(", ".join(w.get("labels") or w["ids"]), "chat_warn_targets")
                targets.hide()
                toggle.clicked.connect(lambda _=False, t=targets, b=toggle: self._toggle_targets(t, b))
                row.addWidget(toggle)
                wl.addLayout(row)
                wl.addWidget(targets)
            lay.addWidget(warn)
        for w in card.model_warnings:
            lab = _label("AI가 덧붙인 주의: " + w, "chat_model_warn")
            lab.setStyleSheet("color: %s;" % tokens.c("muted"))
            lay.addWidget(lab)
        if card.general.strip():
            box = QFrame()
            box.setObjectName("ai_box")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(8, 6, 8, 6)
            bl.setSpacing(2)
            title = QLabel("일반 지식 · 도면에서 확인 안 함")
            title.setStyleSheet("color: %s; font-size: 11px;" % tokens.c("ai-ink"))
            bl.addWidget(title)
            bl.addWidget(_label(card.general, "chat_general"))
            lay.addWidget(box)
        self.details = None
        self._footer(lay, footer)
        _plain_all(self)

    @staticmethod
    def _toggle_targets(label, button):
        label.setVisible(not label.isVisible())
        button.setText("대상 ▴" if label.isVisible() else "대상 ▾")

    # ------------------------------------------------------------ 경로
    def _fill_path(self, index, path):
        box = self._path_boxes[index]
        old = box.layout()
        if old is not None:
            while old.count():
                w = old.takeAt(0).widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
            QWidget().setLayout(old)  # 옛 배치를 떼어 낸다
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        title = QLabel("경로 · " + path.label)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        title.setTextFormat(Qt.PlainText)
        v.addWidget(title)
        holder = QWidget()
        flow = FlowLayout(holder)
        v.addWidget(holder)
        expanded = index in self._expanded
        for item in cardmod.fold_chips(path.chips, expanded=expanded):
            if "fold" in item:
                b = QPushButton("… %d개" % item["fold"])
                b.setObjectName("chat_fold_chips")
                b.setToolTip("가운데 칩을 모두 펼칩니다")
                b.clicked.connect(lambda _=False, i=index: self._expand(i))
                flow.addWidget(b)
                continue
            text = item["tag"] if not item.get("via") else item["tag"]
            b = QPushButton(text)
            b.setObjectName("chat_chip")
            tip = ("%s 배관을 지나 " % item["via"] if item.get("via") else "") + "%s (%s)" % (item["tag"], item.get("sheet") or "-")
            b.setToolTip(_tip(tip))
            b.setAccessibleName("경로 칩 " + item["tag"])
            if item["warn"]:
                b.setStyleSheet("border: 1.5px solid %s;" % tokens.c("warn-line"))
            b.clicked.connect(lambda _=False, it=item: self.chipClicked.emit(it["id"], it.get("sheet") or ""))
            flow.addWidget(b)
        _plain_all(box)
        if len(path.sheets) > 1:
            row = QWidget()
            fl = FlowLayout(row)
            lab = QLabel("도면별")
            fl.addWidget(lab)
            for sheet, n in path.sheets:
                b = QPushButton("%s · %d" % (path.sheet_labels.get(sheet, sheet), n))
                b.setObjectName("chat_sheet")
                b.setToolTip("이 도면을 열고 경로를 표시합니다")
                b.clicked.connect(lambda _=False, s=sheet, i=index: self.sheetClicked.emit(i, s))
                fl.addWidget(b)
            v.addWidget(row)
        elif path.sheets:
            sheet = path.sheets[0][0]
            b = QPushButton("%s · %d" % (path.sheet_labels.get(sheet, sheet), path.sheets[0][1]))
            b.setObjectName("chat_sheet")
            b.clicked.connect(lambda _=False, s=sheet, i=index: self.sheetClicked.emit(i, s))
            v.addWidget(b, 0, Qt.AlignLeft)

    def _expand(self, index):
        self._expanded.add(index)
        self._fill_path(index, self.card.paths[index])

    # ------------------------------------------------------------ 바닥
    def _footer(self, lay, footer):
        notes = self.card.footer_notes()
        bar = QHBoxLayout()
        bar.setSpacing(6)
        text = " · ".join(["도구 %d회" % footer["tools"], footer["model"], "%.1f초" % footer["seconds"]] + notes)
        lab = _label(text, "chat_footer")
        lab.setStyleSheet("color: %s; font-size: 11px;" % tokens.c("muted"))
        bar.addWidget(lab, 1)
        if footer["calls"]:
            self.toggle = QPushButton("근거 보기 ▾")
            self.toggle.setObjectName("chat_evidence")
            self.toggle.setFlat(True)
            self.toggle.clicked.connect(self._toggle_details)
            bar.addWidget(self.toggle)
        lay.addLayout(bar)
        self._calls = footer["calls"]

    def _toggle_details(self):
        if self.details is None:
            lines = []
            for name, args in self._calls:
                try:
                    shown = json.dumps(args, ensure_ascii=False)
                except (TypeError, ValueError):
                    shown = str(args)
                lines.append("%s %s" % (name, shown[:200]))
            self.details = _label("\n".join(lines), "chat_details")
            self.details.setStyleSheet("color: %s; font-size: 11px;" % tokens.c("muted"))
            self.layout().addWidget(self.details)
            self.toggle.setText("근거 접기 ▴")
        else:
            self.details.setVisible(not self.details.isVisible())
            self.toggle.setText("근거 접기 ▴" if self.details.isVisible() else "근거 보기 ▾")


class ChatInput(QPlainTextEdit):
    submitted = Signal()
    escaped = Signal()
    enterCards = Signal()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Down and event.modifiers() & Qt.AltModifier:
            self.enterCards.emit()  # Alt+↓: 마지막 카드의 첫 칩으로(화면 명세 §5.3 키보드)
            return
        if event.key() == Qt.Key_Escape:
            self.escaped.emit()  # 입력칸에서 Esc: 가운데 작업면으로 돌아간다(화면 명세 §12.1)
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatPanel(QWidget):
    modelChanged = Signal(str)     # "fast"|"normal"|"deep": 호출한 쪽이 설정(chat_model)에 남긴다
    guideRequested = Signal(str)   # "install"|"login"|"enable": 안내 단추를 눌렀다
    escaped = Signal()             # 입력칸에서 Esc
    answered = Signal()            # 답 카드가 붙었다(접혀 있으면 띠에 점을 찍는 데 쓴다)

    _answer = Signal(str, object, object)
    _error = Signal(str, object)
    _tool = Signal(str, str)
    _state = Signal(str, str)

    def __init__(self, session_factory, env_provider=None, host=None, view_fn=None, model="fast", parent=None, project_fn=None):
        super().__init__(parent)
        self.setObjectName("chat_panel")
        self._factory = session_factory
        self._env_provider = env_provider
        self._host = host
        self._view_fn = view_fn
        self._session = None
        self._project_fn = project_fn
        self._session_project = None
        self._halt = None        # 한도·인증·초과 사용으로 채팅이 스스로 건 막힘. 연결 상태 갱신으로는 풀지 않는다
        self._last_qid = None
        self._model = model if model in MODEL_NAME else "fast"
        self._log = chatview.QuestionLog()
        self._busy = False
        self._qid = None
        self._started = 0.0
        self._rid = None
        self._cards = []
        self._avail = chatview.availability(None)
        self._progress = None
        self._prewarmed = False
        self._answer.connect(self._on_answer)
        self._error.connect(self._on_error)
        self._tool.connect(self._on_tool)
        self._state.connect(self._on_state)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(8, 4, 8, 4)
        head.addWidget(QLabel("모델"))
        self.model_combo = QComboBox()
        for name, _ in MODELS:
            self.model_combo.addItem(name)
        self.model_combo.setCurrentText(MODEL_NAME[self._model])
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        self.model_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.model_combo.setMinimumContentsLength(3)
        head.addWidget(self.model_combo)
        head.addStretch(1)
        self.new_button = QPushButton("새 대화")
        self.new_button.setToolTip("지금까지의 대화를 지우고 새로 시작합니다")
        self.new_button.clicked.connect(self.new_conversation)
        head.addWidget(self.new_button)
        root.addLayout(head)

        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.chat_page = QWidget()
        cp = QVBoxLayout(self.chat_page)
        cp.setContentsMargins(0, 0, 0, 0)
        cp.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.flow = QWidget()
        self.fl = QVBoxLayout(self.flow)
        self.fl.setContentsMargins(8, 8, 8, 8)
        self.fl.setSpacing(8)
        self.scroll.setWidget(self.flow)
        cp.addWidget(self.scroll, 1)
        self.empty = QWidget()
        self.empty_lay = QVBoxLayout(self.empty)
        self.empty_lay.setContentsMargins(0, 0, 0, 0)
        self.empty_lay.setSpacing(4)
        self.fl.addWidget(self.empty)
        self.fl.addStretch(1)
        self.notice = QLabel("")
        self.notice.setObjectName("chat_limit")
        self.notice.setWordWrap(True)
        self.notice.hide()
        cp.addWidget(self.notice)
        row = QHBoxLayout()
        row.setContentsMargins(8, 6, 8, 8)
        self.input = ChatInput()
        self.input.setPlaceholderText(INPUT_HINT)
        self.input.setFixedHeight(56)
        self.input.setAccessibleName("채팅 질문")
        self.input.submitted.connect(self._submit)
        self.input.escaped.connect(self.escaped)
        self.input.enterCards.connect(self._enter_cards)
        self.input.textChanged.connect(self._typing)
        row.addWidget(self.input, 1)
        self.send_button = QPushButton("보내기")
        self.send_button.clicked.connect(self._send_clicked)
        row.addWidget(self.send_button)
        cp.addLayout(row)
        self.pages.addWidget(self.chat_page)

        self.guide_page = QWidget()
        gl = QVBoxLayout(self.guide_page)
        gl.setContentsMargins(16, 24, 16, 16)
        self.guide_text = QLabel("")
        self.guide_text.setWordWrap(True)
        self.guide_text.setObjectName("chat_guide")
        gl.addWidget(self.guide_text)
        self.guide_button = QPushButton("")
        self.guide_button.setObjectName("chat_guide_button")
        self.guide_button.clicked.connect(lambda: self.guideRequested.emit(self._avail["button"]))
        gl.addWidget(self.guide_button, 0, Qt.AlignLeft)
        gl.addStretch(1)
        self.pages.addWidget(self.guide_page)
        self._fill_examples(None)
        _plain_all(self)

    def minimumSizeHint(self):  # noqa: N802
        """안쪽 글·단추의 일시적인 긴 최소 폭이 창을 넓히지 않게 한다. 좁아지면 글은 줄을 바꾸고 칩은 다음 줄로 넘어간다."""
        return QSize(160, 160)

    # ------------------------------------------------------------ 공개
    def busy(self):
        return self._busy

    def model(self):
        return self._model

    def cards(self):
        return list(self._cards)

    def focus_input(self):
        """Ctrl+K: 입력칸으로 간다(막힌 상태면 안내 단추로)."""
        if self.pages.currentWidget() is self.chat_page and self.input.isEnabled():
            self.input.setFocus()

    def set_host(self, host):
        self._host = host

    def set_availability(self, conn_state, message="", reset_text=None, user_check=False):
        """§8: conn_state에 따라 입력칸 대신 안내만 보이거나 입력을 막는다. 채팅이 스스로 건 막힘(한도·인증·초과 사용)은
        연결 상태가 정상으로 돌아와도 곧바로 풀지 않는다. 사용자가 연결을 다시 확인해 정상이 됐거나(user_check) 한도 재설정
        시각이 지났을 때만 푼다."""
        a = chatview.availability(conn_state, message, reset_text)
        if self._halt is not None:
            if a["blocked"]:
                self._halt = None          # 연결 쪽 막힘이 이제 직접 말한다
            elif user_check or self._halt_expired():
                self._halt = None
            else:
                return
        self._avail = a
        self._apply_availability(conn_state)

    def _halt_expired(self):
        at = (self._halt or {}).get("resets_at")
        return bool(at) and time.time() >= at

    def _block(self, state, message, limit):
        """세션이 보낸 막는 오류: 화면도 입력을 막고, 풀리는 조건(재설정 시각)을 기억한다."""
        limit = limit or {}
        at = limit.get("resets_at")
        self._halt = {"state": state, "resets_at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else None}
        reset = limit.get("resets_at_text") or limit.get("reset_text")
        if not reset and self._halt["resets_at"]:
            import datetime
            reset = datetime.datetime.fromtimestamp(self._halt["resets_at"]).strftime("%m-%d %H:%M")
        self._avail = chatview.availability(state, message, reset)
        self._apply_availability(state)

    def prewarm(self):
        """채팅 창을 펼칠 때 프로세스를 미리 띄운다(첫 질문의 시작 비용을 숨김, §2.4). 막힌 상태에서는 하지 않는다."""
        if self._avail["blocked"] or self._prewarmed:
            return
        self._prewarmed = True
        session = self._ensure_session()
        if session is not None:
            import threading
            threading.Thread(target=session.start, daemon=True).start()

    def ask(self, text):
        text = (text or "").strip()
        if self._halt is not None and self._halt_expired():
            self._halt = None
            self._avail = chatview.availability("ok")
            self._apply_availability("ok")
        if not text or self._busy or self._avail["blocked"]:
            return False
        self.check_project()
        session = self._ensure_session()
        if session is None:
            return False
        self._busy = True
        self._qid = None
        self._started = time.monotonic()
        self.empty.hide()
        self._add_bubble(text)
        self._show_progress("답을 찾는 중…")
        self._update_send()
        view = dict(self._view_fn() if self._view_fn else {})
        self._qid = session.ask(text, view)
        return True

    def _project_changed(self):
        if self._project_fn is None or self._session is None:
            return False
        try:
            return self._project_fn() != self._session_project
        except Exception:  # noqa: BLE001 - 프로젝트를 못 알아내면 바뀌었다고 보지 않는다
            return False

    def check_project(self):
        """프로젝트가 바뀌었으면 대화를 끝낸다(세션은 만들 때의 프로젝트에 묶여 있다, 규격 §2.4)."""
        if not self._project_changed():
            return False
        old, self._session = self._session, None
        self._prewarmed = False
        if old is not None:
            old.close()
        self.new_conversation()
        self._add_notice("프로젝트가 바뀌어 대화를 새로 시작했습니다. 지금까지의 대화는 지워졌습니다.")
        return True

    def new_conversation(self):
        """대화를 지우고 새로 시작한다. 세션은 다음 질문에서 새 프로세스로 뜬다."""
        if self._session is not None:
            self._session.stop()
        self._busy, self._qid = False, None
        self._clear_marks()
        for i in reversed(range(self.fl.count())):
            w = self.fl.itemAt(i).widget()
            if w is not None and w is not self.empty:
                w.deleteLater()
                self.fl.removeWidget(w)
        self._cards = []
        self._progress = None
        self.fl.addStretch(1)
        self.empty.show()
        self._update_send()

    def shutdown(self):
        """창·앱을 닫을 때. 진행 중 질문도 묻지 않고 끊는다."""
        if self._session is not None:
            self._session.close()
            self._session = None

    # ------------------------------------------------------------ 세션
    def _ensure_session(self):
        if self._session is None:
            cb = {"on_tool_event": self._cb_tool, "on_answer": self._cb_answer, "on_error": self._cb_error,
                  "on_state": self._cb_state}
            try:
                self._session = self._factory(self._model, cb)
                self._session_project = self._project_fn() if self._project_fn else None
            except Exception as exc:  # noqa: BLE001 - 프로젝트가 없거나 채팅 부품이 없을 때: 앱은 계속 돈다
                self._add_notice(str(exc) or "채팅을 시작하지 못했습니다.")
                self._session = None
        return self._session

    # 읽기 스레드에서 불린다: 신호로 화면 스레드에 넘긴다
    def _cb_tool(self, qid, name, args, result):
        self._log.tool_event(qid, name, args, result)
        self._tool.emit(qid, name)

    def _cb_answer(self, qid, answer, tool_ids):
        self._answer.emit(qid, answer, tool_ids)

    def _cb_error(self, qid, error):
        self._error.emit(qid or "", error)

    def _cb_state(self, state, message):
        self._state.emit(state, message)

    def _mine(self, qid):
        return self._busy and (self._qid is None or not qid or qid == self._qid)

    def _on_tool(self, qid, name):
        if self._mine(qid) and self._progress is not None:
            self._progress.setText("도구 %d회 · %s" % (self._log.tool_count(qid), name))

    def _on_state(self, state, message):
        if state == "renewed" and message:
            self._add_notice(message)

    def _on_answer(self, qid, answer, tool_ids):
        if not self._mine(qid):
            return
        seconds = time.monotonic() - self._started
        self._busy, self._qid = False, None
        self._last_qid = qid
        self._remove_progress()
        stale = self._project_changed()   # 질문 중에 프로젝트가 바뀌었다: 옛 프로젝트 도구에서 받은 근거는 새 프로젝트의 근거가 아니다
        try:
            env, pg = (self._env_provider() if self._env_provider else None) or (_NoEnv(), {"nodes": []})
        except Exception:  # noqa: BLE001 - 자료를 못 읽어도 답 글은 보여 준다
            env, pg = _NoEnv(), {"nodes": []}
        if stale:
            card = cardmod.build_card(answer, {}, env)
            self._add_notice("질문하는 동안 프로젝트가 바뀌어 이 답의 근거는 확인하지 않았습니다.")
        else:
            card = cardmod.build_card(answer, tool_ids, env, path_refs=self._log.path_refs(qid),
                                      tool_names=self._log.tool_names(qid), source_kinds=self._log.source_kinds(qid))
        footer = {"tools": self._log.tool_count(qid), "model": MODEL_NAME[self._model], "seconds": seconds,
                  "calls": self._log.tool_calls(qid)}
        widget = CardWidget(card, footer)
        widget.chipClicked.connect(lambda ident, sheet, p=pg: self._chip(p, ident, sheet))
        widget.sheetClicked.connect(lambda i, sheet, c=card, p=pg, q=qid: self._sheet(p, c, i, sheet, q))
        self._insert(widget)
        self._cards.append(widget)
        self._show_on_drawing(pg, card, qid)
        self._log.forget(qid)
        self._update_send()
        self.answered.emit()

    def _on_error(self, qid, error):
        qid = qid or ""
        mine = bool(qid) and self._mine(qid)
        late = bool(qid) and not mine and qid == self._last_qid  # 답이 정상으로 온 뒤 이어지는 한도·초과 사용 오류
        if qid and not (mine or late):
            return                                           # 다른 질문의 오류
        if mine:
            self._busy, self._qid = False, None
            self._remove_progress()
        error = error or {}
        message = error.get("message") or "오류가 났습니다."
        state = error.get("conn_state") or error.get("error_kind")
        # 세션이 남은 질문을 막는 오류(HALT_KINDS)와 연결 상태: 화면도 입력을 막아, 초과 사용 뒤 다시 물어 요금이 나가지 않게 한다
        blocking = state in ("limit_reached", "overage", "not_installed", "cli_unsupported", "cli_too_old", "login_required",
                             "login_expired", "disabled", "auth_mismatch", "not_ready", "tool_guard_failed", "not_subscription",
                             "account_blocked")
        if blocking:
            self._block(state, message, error.get("limit"))
        else:
            self._add_notice(message)   # 질문 ID가 없는 세션 오류(미리 띄우기 실패 등)는 진행 중인 질문을 끝내지 않는다
        self._update_send()

    # ------------------------------------------------------------ 도면
    def _clear_marks(self):
        if self._host is not None and self._rid:
            self._host.clear(self._rid)
        self._rid = None

    def _show_on_drawing(self, pg, card, qid):
        if self._host is None:
            return
        self._clear_marks()
        marks = chatview.marks_for_card(pg, card, path_index=0 if card.paths else None)
        if marks:
            self._rid = "chat-" + qid
            self._host.show_marks(self._rid, marks)

    def _sheet(self, pg, card, index, sheet, qid):
        if self._host is None:
            return
        marks = chatview.marks_for_card(pg, card, path_index=index)
        self._rid = "chat-" + qid
        self._host.show_marks(self._rid, marks, sheet=sheet)

    def _chip(self, pg, ident, sheet):
        if self._host is None or not sheet:
            return
        ids = chatview.split_by_sheet(pg, [ident]).get(sheet) or []

        def zoom():
            wv = getattr(self._host, "webview", None)
            if wv is not None and ids:
                wv.zoom_to(ids)
        self._host.show_sheet(sheet, then=zoom)

    # ------------------------------------------------------------ 그리기
    def _insert(self, widget):
        self.fl.insertWidget(self.fl.count() - 1, widget)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def _add_bubble(self, text):
        lab = _label(text, "chat_user")
        lab.setStyleSheet("QLabel#chat_user { background: %s; border-radius: 6px; padding: 6px 8px; }" % tokens.c("surface-2"))
        self._insert(lab)

    def _add_notice(self, text):
        lab = _label(text, "chat_notice")
        lab.setStyleSheet("color: %s; font-size: 11px;" % tokens.c("muted"))
        self._insert(lab)

    def _show_progress(self, text):
        self._remove_progress()
        self._progress = _label(text, "chat_progress")
        self._progress.setStyleSheet("color: %s;" % tokens.c("muted"))
        self._insert(self._progress)

    def _remove_progress(self):
        if self._progress is not None:
            self._progress.deleteLater()
            self.fl.removeWidget(self._progress)
            self._progress = None

    def _fill_examples(self, pg):
        while self.empty_lay.count():
            w = self.empty_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        intro = _label("도면과 문서에 대해 물어보세요. 아래 질문을 눌러 시작할 수도 있습니다.", "chat_intro")
        intro.setStyleSheet("color: %s;" % tokens.c("muted"))
        self.empty_lay.addWidget(intro)
        for group, questions in chatview.examples(pg):
            head = QLabel(group)
            head.setStyleSheet("font-weight: bold; margin-top: 4px;")
            self.empty_lay.addWidget(head)
            for q in questions:
                b = WrapButton(q)
                b.setObjectName("chat_example")
                b.clicked.connect(lambda _=False, t=q: self.ask(t))
                self.empty_lay.addWidget(b)

    def refresh_examples(self):
        """채팅 창을 펼치거나 프로젝트가 바뀌었을 때 예시 질문의 태그를 지금 프로젝트에서 다시 채운다(빈 화면일 때만)."""
        if self._cards or self._busy:
            return
        try:
            got = self._env_provider() if self._env_provider else None
            self._fill_examples(got[1] if got else None)
        except Exception:  # noqa: BLE001 - 프로젝트를 못 읽으면 태그 없는 예시를 그대로 둔다
            pass

    # ------------------------------------------------------------ 입력
    def _typing(self):
        if self.input.toPlainText().strip():
            self.prewarm()

    def _submit(self):
        text = self.input.toPlainText()
        if self.ask(text):
            self.input.clear()

    def _send_clicked(self):
        if self._busy:
            self._stop()
        else:
            self._submit()

    def _enter_cards(self):
        """Alt+↓: 마지막 카드의 첫 칩(없으면 첫 단추)으로 초점을 옮긴다."""
        if not self._cards:
            return
        buttons = [b for b in self._cards[-1].findChildren(QPushButton) if b.isVisible()]
        chips = [b for b in buttons if b.objectName() == "chat_chip"]
        target = (chips or buttons or [None])[0]
        if target is not None:
            target.setFocus()

    def _stop(self):
        qid = self._qid
        if self._session is not None:
            self._busy, self._qid = False, None  # 세션이 보내는 cancelled 오류는 무시한다
            self._session.stop()
        self._remove_progress()
        self._add_notice("질문을 멈췄습니다. 지금까지의 대화는 지워지고 다음 질문은 새 대화로 시작합니다.")
        if qid:
            self._log.forget(qid)
        self._update_send()

    def _update_send(self):
        self.send_button.setText("멈추기" if self._busy else "보내기")
        self.send_button.setEnabled(not self._avail["blocked"] or self._busy)

    def _model_changed(self, _i):
        self._model = MODELS[self.model_combo.currentIndex()][1]
        if self._session is not None:
            self._session.set_model(self._model)
        self.modelChanged.emit(self._model)

    def _apply_availability(self, state):
        a = self._avail
        limit = state in ("limit_reached", "overage")
        if a["blocked"] and not limit:
            self.guide_text.setText(a["text"])
            btn = a["button"]
            self.guide_button.setVisible(bool(btn))
            self.guide_button.setText(GUIDE_BUTTONS.get(btn, ""))
            self.pages.setCurrentWidget(self.guide_page)
            return
        self.pages.setCurrentWidget(self.chat_page)
        self.input.setEnabled(not a["blocked"])
        self.notice.setText(a["text"] if limit else "")
        self.notice.setVisible(limit)
        self._update_send()
