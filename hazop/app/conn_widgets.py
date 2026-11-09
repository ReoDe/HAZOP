"""AI 연결 표시 부품: SVG 아이콘, 상태 배지, 해결 띠, 상태줄 연결 칩과 상세 창(화면 설계 §2.2·§5·§9).

모양·글자는 모두 conn_view 표에서 온다. 아이콘은 글꼴 기호가 아니라 앱이 그리는 SVG다(맑은 고딕에 없는 기호가 깨지지 않게).
"""

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from hazop.app import conn_view, tokens

ICON_PX = 14
ACTION_HELP_NAMES = ("terminal_login", "terminal_update", "login_help", "install_help")  # 칩 상세 창에 둘 해결 동작
_SVG = {  # 16×16, 선 색은 {c}로 채운다
    "check": '<circle cx="8" cy="8" r="6.3"/><path d="M5 8.2l2 2 4-4.2"/>',
    "dots": '<circle cx="8" cy="8" r="6.3" stroke-dasharray="2.2 2.2"/>',
    "question": '<circle cx="8" cy="8" r="6.3"/><path d="M6.2 6.3a1.9 1.9 0 1 1 2.6 1.8c-.6.3-.8.6-.8 1.3"/>'
                '<circle cx="8" cy="11.4" r=".5" fill="{c}"/>',
    "clock": '<circle cx="8" cy="8" r="6.3"/><path d="M8 4.6V8l2.4 1.5"/>',
    "download": '<path d="M8 2.5v7.5M4.8 7l3.2 3.2L11.2 7M3 13h10"/>',
    "warn": '<path d="M8 2.2l6.2 11H1.8z"/><path d="M8 6.5v3.2"/><circle cx="8" cy="11.6" r=".5" fill="{c}"/>',
    "cross": '<circle cx="8" cy="8" r="6.3"/><path d="M5.7 5.7l4.6 4.6M10.3 5.7l-4.6 4.6"/>',
    "flask": '<path d="M6.3 2.5h3.4M7 2.5v4L3.3 12.6a.9.9 0 0 0 .8 1.4h7.8a.9.9 0 0 0 .8-1.4L9 6.5v-4"/>',
}


def icon_pixmap(name, color_token, px=ICON_PX, ratio=1.0):
    c = tokens.c(color_token)
    body = _SVG.get(name, _SVG["question"]).replace("{c}", c)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="%s" stroke-width="1.4" '
           'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (c, body))
    size = int(px * ratio)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def paint_badge(p, rect, lk, text, font_metrics, focus=False, pad=7):
    """둥근 사각 배지: 바탕(시험 방식은 빗금), 테두리(실행 불가 1.5px, 시험은 점선), 아이콘, 글자."""
    bg, ink, line = lk.colors
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(rect).adjusted(lk.border / 2 + .5, lk.border / 2 + .5, -lk.border / 2 - .5, -lk.border / 2 - .5)
    path = QPainterPath()
    path.addRoundedRect(r, 3, 3)
    p.fillPath(path, QColor(tokens.c(bg)))
    if lk.dashed:  # AI 초안과 같은 빗금 바탕
        p.save()
        p.setClipPath(path)
        p.setPen(QPen(QColor(tokens.c("ai-hatch-b")), 2))
        x = r.left() - r.height()
        while x < r.right():
            p.drawLine(QPointF(x, r.bottom()), QPointF(x + r.height(), r.top()))
            x += 6
        p.restore()
    pen = QPen(QColor(tokens.c("ui" if focus else line)), 2 if focus else lk.border)
    if lk.dashed and not focus:
        pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawPath(path)
    ix = r.left() + pad
    iy = r.center().y() - ICON_PX / 2
    p.drawPixmap(QPointF(ix, iy), icon_pixmap(lk.icon, ink, ICON_PX, p.device().devicePixelRatioF() or 1.0))
    p.setPen(QColor(tokens.c(ink)))
    tr = QRectF(ix + ICON_PX + 5, r.top(), r.right() - ix - ICON_PX - 5 - pad + 2, r.height())
    p.drawText(tr, int(Qt.AlignVCenter | Qt.AlignLeft), text)


def badge_width(font_metrics, text, pad=7):
    return pad * 2 + ICON_PX + 5 + font_metrics.horizontalAdvance(text) + 6


class ConnBadge(QWidget):
    """설정 창 상태 칩·칩 상세 창 상태 칸. 아이콘은 장식이고 상태는 글자와 접근성 이름으로 읽힌다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lk, self._text = conn_view.LOOKS["unchecked"], ""
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def text(self):
        return self._text

    def set_look(self, lk, text, name="", desc=""):
        self.lk, self._text = lk, text
        self.setAccessibleName(name or text)
        self.setAccessibleDescription(desc)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(badge_width(self.fontMetrics(), self._text), self.fontMetrics().height() + 8)

    minimumSizeHint = sizeHint

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        paint_badge(p, self.rect(), self.lk, self._text, self.fontMetrics())
        p.end()


class ConnChip(QToolButton):
    """상태줄 연결 칩(§5.1). 평평한 단추라 Tab으로 닿고 Enter·Space로 상세 창을 연다. 말줄임하지 않는다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("conn_chip")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoRaise(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lk, self.wide, self.narrow, self.narrow_mode = conn_view.LOOKS["unchecked"], "", "", False

    def set_chip(self, lk, wide, narrow, name):
        self.lk, self.wide, self.narrow = lk, wide, narrow
        self.setText(self.shown())
        self.setAccessibleName(name)
        self.setAccessibleDescription(conn_view.CHIP_HINT)
        self.setToolTip(name.replace("AI 연결: ", "AI 연결 · ", 1))
        self.updateGeometry()
        self.update()

    def shown(self):
        return self.narrow if self.narrow_mode else self.wide

    def width_for(self, text):
        return badge_width(self.fontMetrics(), text)

    def set_narrow(self, on):
        if on != self.narrow_mode:
            self.narrow_mode = on
            self.setText(self.shown())
            self.updateGeometry()
            self.update()

    def sizeHint(self):
        return QSize(self.width_for(self.shown()), self.fontMetrics().height() + 8)

    minimumSizeHint = sizeHint

    def keyPressEvent(self, e):  # noqa: N802  Enter도 Space처럼 누름으로 받는다
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        paint_badge(p, self.rect(), self.lk, self.shown(), self.fontMetrics(), focus=self.hasFocus())
        p.end()


class ResolveBand(QFrame):
    """해결 띠(§9): 제목(아이콘) · 안내 · 해결 동작 단추. 실행할 수 있는 상태면 숨는다. 단추는 action(이름)을 낸다."""

    action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.icon = QLabel()
        self.icon.setAccessibleName("")
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 700")
        head.addWidget(self.icon)
        head.addWidget(self.title, 1)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.PlainText)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(head)
        lay.addWidget(self.text)
        lay.addLayout(self.buttons)
        self.btns = {}
        self.hide()

    def set_band(self, lk, guide, actions=None, labels=None):
        bg, ink, line = lk.colors
        self.setStyleSheet("ResolveBand { background: %s; border: %spx %s %s; border-radius: 4px; } "
                           "ResolveBand QLabel { color: %s; background: transparent; }"
                           % (tokens.c(bg), lk.border, "dashed" if lk.dashed else "solid", tokens.c(line),
                              tokens.c(ink)))
        self.icon.setPixmap(icon_pixmap(lk.icon, ink, ICON_PX, self.devicePixelRatioF() or 1.0))
        self.title.setText(lk.title)
        self.text.setText(guide)
        self.text.setVisible(bool(guide))
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.btns = {}
        for name in (lk.actions if actions is None else actions):
            b = QPushButton((labels or {}).get(name) or conn_view.ACTIONS[name])
            b.clicked.connect(lambda _c=False, n=name: self.action.emit(n))
            self.buttons.addWidget(b)
            self.btns[name] = b
        self.buttons.addStretch(1)
        self.setAccessibleName("알림: %s" % lk.title)
        self.setAccessibleDescription(guide)
        self.show()


class ConnPopup(QFrame):
    """칩 상세 창(§5.2): 폭 340px 팝업. Esc로 닫으면 칩으로 포커스가 돌아간다. 단추는 action(이름)을 낸다:
    check(다시 확인), settings(연결 설정…), to_api(API 키로 바꾸기…), 그리고 해결 동작 이름."""

    action = Signal(str)
    WIDTH = 340

    def __init__(self, chip):
        super().__init__(chip, Qt.Popup)
        self.chip = chip
        self.setObjectName("conn_popup")
        self.setFixedWidth(self.WIDTH)
        # 상태줄 안 위젯이라 상태줄 글자 색(어두운 바탕용)을 물려받지 않게 글자 색·크기를 다시 정한다
        self.setStyleSheet("QFrame#conn_popup { background: %(card)s; border: 1px solid %(line-strong)s; "
                           "border-radius: 4px; }"
                           "QFrame#conn_popup QLabel { color: %(ink)s; font-size: %(sm)dpx; }"
                           "QFrame#conn_popup QLabel#muted { color: %(muted)s; }"
                           "QFrame#conn_popup QPushButton { font-size: %(sm)dpx; padding: 2px 7px; }"
                           % dict(tokens.COLORS, sm=tokens.FONT_SIZE["sm"]))
        self.setAccessibleName("AI 연결")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        title = QLabel("AI 연결")
        title.setStyleSheet("font-weight: 700")
        lay.addWidget(title)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnStretch(1, 1)
        lay.addLayout(self.grid)
        self.guide = QLabel()
        self.guide.setWordWrap(True)
        self.guide.setObjectName("muted")
        lay.addWidget(self.guide)
        self.btn_row = QHBoxLayout()
        self.btn_row.setSpacing(6)
        lay.addLayout(self.btn_row)
        self.btns = {}

    def _row(self, r, name, widget):
        lab = QLabel(name)
        lab.setObjectName("muted")
        self.grid.addWidget(lab, r, 0, Qt.AlignTop)
        self.grid.addWidget(widget, r, 1)

    def fill(self, conn):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        method = conn.method
        status = conn.status(method)
        lk = conn_view.look(method, status["state"])
        model = conn.model(method)
        rows = [("방식", QLabel("%s (사용 중)" % conn_view.METHOD_NAMES[method]))]
        if method != "fixed":
            rows.append(("모델", QLabel(conn_view.model_name(model))))
        state_box = QWidget()
        sl = QHBoxLayout(state_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        badge = ConnBadge()
        name, desc = conn_view.status_accessible(method, status)
        badge.set_look(lk, lk.label, name, desc)
        sl.addWidget(badge)
        when = QLabel(conn_view.checked_text(status))
        when.setObjectName("muted")
        sl.addWidget(when)
        sl.addStretch(1)
        rows.append(("상태", state_box))
        if conn.running:
            rows.append(("실행", QLabel(conn.progress or "AI 분석 실행 중")))
        if method == "subscription":
            for text, say, warn in conn_view.usage_lines(status.get("limit")):
                lab = QLabel(text + ("\n" + warn if warn else ""))
                lab.setWordWrap(True)
                lab.setAccessibleName(say)
                rows.append(("사용량", lab))
            plan = conn_view.plan_name(status.get("plan"))
            if lk.can_start or status["state"] in ("limit_reached",):
                rows.append(("계정", QLabel("로그인됨" + (" · " + plan if plan else ""))))
        for r, (n, w) in enumerate(rows):
            if isinstance(w, QLabel):
                w.setWordWrap(True)
            self._row(r, n, w)
        blocked = not lk.can_start and status["state"] not in ("checking", "unchecked")
        self.guide.setText(conn_view.guide_text(method, status, conn.fixed_count()) if blocked else "")
        self.guide.setVisible(blocked)
        while self.btn_row.count():
            w = self.btn_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.btns = {}
        names = [a for a in lk.actions if a in ACTION_HELP_NAMES] if blocked else []
        names.append("check")
        if "to_api" in lk.actions and "api" in conn.methods() and method != "api":
            names.append("to_api")
        for n in names:
            self._button(n, "다시 확인(&R)" if n == "check" else conn_view.ACTIONS[n])
        self.btn_row.addStretch(1)
        self._button("settings", "연결 설정…(&S)").setObjectName("primary")
        self.adjustSize()

    def _button(self, name, text):
        b = QPushButton(text)
        b.clicked.connect(lambda _c=False, n=name: (self.close(), self.action.emit(n)))
        self.btn_row.addWidget(b)
        self.btns[name] = b
        return b

    def show_above(self):
        self.adjustSize()
        top_left = self.chip.mapToGlobal(self.chip.rect().topRight())
        x = top_left.x() - self.width()
        y = top_left.y() - self.height() - 4
        self.move(max(0, x), max(0, y))
        self.show()
        first = next(iter(self.btns.values()), None)
        if first is not None:
            first.setFocus()

    def hideEvent(self, e):  # noqa: N802
        super().hideEvent(e)
        self.chip.setFocus(Qt.PopupFocusReason)


class NoticeBand(QFrame):
    """⑤ 위 안내 띠(§7.3·§7.4·§8.1): 아이콘 · 굵은 첫 문장과 본문(두 줄까지 줄바꿈) · 오른쪽 단추. 떠도 포커스를 옮기지
    않는다. 시험 결과 띠(tone ai)는 AI 초안과 같은 빗금 바탕이다. 단추는 action(이름)을 낸다."""

    action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("notice_band")
        self.kind = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(8)
        self.icon = QLabel()
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.text, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(self.buttons)
        self.btns = {}
        self._tone = "warn"
        self.hide()

    def set_band(self, kind, band, body, labels):
        """band: conn_view.Band, labels: {동작 이름: 단추 글자}."""
        from html import escape
        self.kind = kind
        self._tone = band.tone
        bg, ink, line = conn_view.TONES[band.tone]
        dashed = band.tone == "ai"
        self.setStyleSheet("QFrame#notice_band { background: %s; border: 1.5px %s %s; border-radius: 4px; } "
                           "QFrame#notice_band QLabel { color: %s; background: transparent; }"
                           % ("transparent" if dashed else tokens.c(bg), "dashed" if dashed else "solid",
                              tokens.c(line), tokens.c(ink)))
        self.icon.setPixmap(icon_pixmap(band.icon, ink, ICON_PX, self.devicePixelRatioF() or 1.0))
        self.text.setText("<b>%s</b> %s" % (escape(band.title), escape(body)))
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.btns = {}
        for i, name in enumerate(band.actions):
            b = QPushButton(labels.get(name) or conn_view.BAND_ACTIONS[name])
            if i == 0 and name != "close":
                b.setObjectName("primary")
            b.setAutoDefault(False)
            b.clicked.connect(lambda _c=False, n=name: self.action.emit(n))
            self.buttons.addWidget(b)
            self.btns[name] = b
        self.setAccessibleName("알림: %s" % (band.a11y or band.title.rstrip(".")))
        self.setAccessibleDescription("%s %s" % (band.title, body))
        self.show()

    def first_button(self):
        return next(iter(self.btns.values()), None)

    def paintEvent(self, e):  # noqa: N802  시험 결과 띠는 빗금 바탕
        if self._tone == "ai":
            p = QPainter(self)
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            p.fillRect(r, QColor(tokens.c("ai-hatch-a")))
            p.setPen(QPen(QColor(tokens.c("ai-hatch-b")), 2))
            p.setClipRect(r)
            x = r.left() - r.height()
            while x < r.right():
                p.drawLine(QPointF(x, r.bottom()), QPointF(x + r.height(), r.top()))
                x += 8
            p.end()
        super().paintEvent(e)
