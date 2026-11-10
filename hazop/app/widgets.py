"""공통 위젯: 상태 칩, 경고·오류 띠, 빈 화면 안내, 작업 스레드 실행기, HTML 표시 도우미."""

import datetime
import html
import os
import traceback

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from hazop import paths
from hazop.app import tokens


# 검증 상태(passed·blocked) 한국어 표시. 모르는 코드는 영문 그대로(각 화면에서 .get(st, st)).
VALIDATION_LABELS = {"passed": "통과", "blocked": "차단"}


def log_path():
    """개발자용 오류 기록(traceback) 위치: <작업 루트>/출력/로그/app.log. 화면에는 요약만 보여 준다."""
    return paths.output_root("logs", "app.log")


def write_log(title, detail):
    try:
        os.makedirs(os.path.dirname(log_path()), exist_ok=True)
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n%s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), title, detail))
    except OSError:  # 기록 실패는 화면 동작을 막지 않는다
        pass


def kst_text(utc_iso):
    """UTC ISO 8601('...Z') → 한국 표준시 표시."""
    t = datetime.datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")


class ElidedLabel(QLabel):
    """한 줄 라벨. elide(Qt.ElideRight·ElideMiddle)를 주면 자리가 모자랄 때 줄임표로 줄여 그린다. text()와 접근성
    이름은 늘 전체 문구이고, 줄여 그렸을 때만 툴팁에 전체 문구를 띄운다(헤더 WhereLabel과 같은 동작).
    최소 폭은 앞 min_chars글자 + '…' 폭이다(docs/2026-11-05-design-system W3). elide가 None이면 QLabel과 같다."""

    def __init__(self, text="", parent=None, elide=None, min_chars=8):
        super().__init__(text, parent)
        self.elide, self.min_chars = elide, min_chars
        if elide is not None:
            self.setWordWrap(False)
            self._tip()

    def setText(self, text):
        super().setText(text)
        if self.elide is not None:
            self._tip()

    def _tip(self):
        self.setToolTip(self.text() if self.is_elided() else "")

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.elide is not None:
            self._tip()

    def changeEvent(self, event):  # noqa: N802  글꼴·스타일이 바뀌면 줄임 여부도 바뀐다
        super().changeEvent(event)
        if self.elide is not None and event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._tip()

    def _text_rect(self):
        m = self.margin()
        return self.contentsRect().adjusted(m, m, -m, -m)

    def is_elided(self):
        return self.elide is not None and self.fontMetrics().horizontalAdvance(self.text()) > self._text_rect().width()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        if self.elide is None or not self.text():
            return hint
        cm = self.contentsMargins()
        frame = cm.left() + cm.right() + 2 * self.margin()
        need = self.fontMetrics().horizontalAdvance(self.text()[:self.min_chars] + "…") + frame
        hint.setWidth(min(hint.width(), need))
        return hint

    def paintEvent(self, event):
        if not self.is_elided():
            super().paintEvent(event)
            return
        from PySide6.QtGui import QPainter
        from PySide6.QtWidgets import QStyle
        p = QPainter(self)
        self.drawFrame(p)
        r = self._text_rect()
        shown = self.fontMetrics().elidedText(self.text(), self.elide, r.width())
        align = QStyle.visualAlignment(self.layoutDirection(), self.alignment())
        self.style().drawItemText(p, r, int(align), self.palette(), self.isEnabled(), shown, self.foregroundRole())
        p.end()


def plain_label(text="", name=None, wrap=True, elide=None, min_chars=8):
    """사람 입력·외부 문자열을 쓰는 라벨: 서식 해석 없이 글자 그대로(Qt.PlainText). elide는 ElidedLabel 참고."""
    lab = ElidedLabel(text, elide=elide, min_chars=min_chars)
    lab.setTextFormat(Qt.PlainText)
    lab.setWordWrap(wrap if elide is None else False)
    if name:
        lab.setObjectName(name)
    return lab


def esc(v):
    return html.escape("" if v is None else str(v))


def badge(text, kind="plain"):
    """QTextBrowser용 배지. ai: 점선 테두리(속 빈 칩, '제안'), human: 채운 칩(확정), warn: 호박, err: 빨강."""
    c = tokens.COLORS
    style = {
        "ai": "border:1px dashed %s; color:%s; background:%s;" % (c["ai-ink"], c["ai-ink"], c["ai-hatch-a"]),
        "human": "background:%s; color:%s;" % (c["human-line"], c["on-fill"]),
        "warn": "background:%s; color:%s;" % (c["warn-bg"], c["warn-ink"]),
        "err": "background:%s; color:%s;" % (c["err-bg"], c["err-ink"]),
        "ui": "background:%s; color:%s;" % (c["ui-weak"], c["ui-ink"]),
        "plain": "background:%s; color:%s;" % (c["bg"], c["ink-2"]),
    }[kind]
    return '<span style="%s font-size:11px; padding:1px 6px; border-radius:8px;">&nbsp;%s&nbsp;</span>' % (style, esc(text))


def risk_chip(risk, name=None, proposal=True):
    """위험도 칩: 숫자와 등급명을 함께. 제안(AI)은 속 빈 칩, 확정은 채운 칩. 색은 〈표9〉 3단만."""
    if not isinstance(risk, int):
        return badge("미확정", "warn")
    bg, ink, line = tokens.risk_colors(risk)
    label = "%s %d%s" % ("제안" if proposal else "확정", risk, " %s" % name if name else "")
    if proposal:
        style = "border:1px dashed %s; color:%s; background:%s;" % (line, line if line != tokens.COLORS["risk-ok-line"] else ink,
                                                                     tokens.COLORS["card"])
    else:
        style = "background:%s; color:%s; border:1px solid %s;" % (bg, ink, line)
    return '<span style="%s font-size:11px; padding:1px 6px; border-radius:8px;">&nbsp;%s&nbsp;</span>' % (style, esc(label))


def box(inner, kind="ai"):
    """AI 산출 = 옅은 회색 바탕 + 점선(빗금 대체), 사람 확정 = 흰 바탕 + 진한 실선."""
    c = tokens.COLORS
    if kind == "ai":
        st = "background-color:%s; border:1px dashed %s;" % (c["ai-hatch-a"], c["ai-ink"])
    else:
        st = "background-color:%s; border:2px solid %s;" % (c["card"], c["human-line"])
    return '<table width="100%%" cellpadding="8" style="%s margin:4px 0;"><tr><td>%s</td></tr></table>' % (st, inner)


class Chip(ElidedLabel):
    def __init__(self, text="", parent=None, elide=None, min_chars=8):
        super().__init__(text, parent, elide, min_chars)
        self.setObjectName("chip")

    def set_state(self, text, state=""):
        self.setText(text)
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)


class Banner(QFrame):
    """경고(warn)·오류(err) 띠. 메시지가 없으면 숨는다."""

    def __init__(self, kind="warn", parent=None):
        super().__init__(parent)
        self.setObjectName("banner_" + kind)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        lay.addWidget(self.label)
        self.messages = []
        self.hide()

    def set_messages(self, title, messages=()):
        self.messages = list(messages)
        if not title and not self.messages:
            self.hide()
            return
        body = "<b>%s</b>" % esc(title) if title else ""
        if self.messages:
            body += "<ul style='margin:2px 0 0 -20px'>%s</ul>" % "".join("<li>%s</li>" % esc(m) for m in self.messages)
        self.label.setText(body)
        self.show()


def empty_label(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    lab.setAlignment(Qt.AlignCenter)
    return lab


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self):
        try:
            result = self.fn()
        except Exception as exc:  # 작업 실패는 화면에 사유로 보여 준다(성공으로 표시하지 않음)
            write_log("작업 실패", traceback.format_exc())  # traceback은 로그 파일에만
            self.signals.failed.emit("%s (자세한 내용: %s)" % (exc, log_path()))
        else:
            self.signals.done.emit(result)


class TaskRunner(QObject):
    """긴 작업을 QThreadPool에서 실행해 창이 멈추지 않게 한다. started/finished로 상태줄에 진행을 표시한다."""

    started = Signal(str)
    finished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)  # 단일 사용자·순차 처리
        self._live = set()

    def run(self, label, fn, on_done, on_error):
        task = _Task(fn)
        self._live.add(task)

        def finish(handler, value):
            self._live.discard(task)
            self.finished.emit(label)
            handler(value)

        task.signals.done.connect(lambda r: finish(on_done, r))
        task.signals.failed.connect(lambda e: finish(on_error, e))
        task.setAutoDelete(False)
        self.started.emit(label)
        self.pool.start(task)

    def wait(self, msecs=-1):
        return self.pool.waitForDone(msecs)


class Toast(QFrame):
    """오른쪽 아래 알림 한 줄(U-07). undo가 있으면 [실행 취소] 링크와 Ctrl+Z 안내를 붙인다. ms 뒤 사라진다.
    되돌릴 수 없는 동작은 토스트 대신 확인 대화상자를 쓴다(명세 U-07)."""

    def __init__(self, parent):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(12)
        self.label = QLabel()
        self.label.setObjectName("toast_text")
        self.label.setTextFormat(Qt.PlainText)
        lay.addWidget(self.label)
        self.undo_btn = QPushButton("실행 취소")
        self.undo_btn.setObjectName("toast_undo")
        self.undo_btn.setCursor(Qt.PointingHandCursor)
        self.undo_btn.clicked.connect(self.run_undo)
        lay.addWidget(self.undo_btn)
        self.key = QLabel("Ctrl+Z")
        self.key.setObjectName("kbd")
        lay.addWidget(self.key)
        self.action_btns = []  # show_message(actions=)의 [열기]·[폴더 열기] 같은 버튼(누르면 실행하고 닫힘)
        self.undo = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.hide()

    def show_message(self, text, undo=None, ms=5000, actions=()):
        from PySide6.QtWidgets import QPushButton
        self.undo = undo
        self.label.setText(text)
        for b in self.action_btns:
            b.deleteLater()
        self.action_btns = []
        for label, fn in actions:
            b = QPushButton(label)
            b.setObjectName("toast_undo")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, f=fn: (self.dismiss(), f()))
            self.layout().insertWidget(1 + len(self.action_btns), b)
            self.action_btns.append(b)
        self.undo_btn.setVisible(undo is not None)
        self.key.setVisible(undo is not None)
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self.timer.start(ms)

    def place(self):
        p = self.parentWidget()
        self.move(max(0, p.width() - self.width() - 24), max(0, p.height() - self.height() - 40))

    def run_undo(self):
        """실행 취소를 한 번 실행한다. 되돌린 것이 있으면 True."""
        fn, self.undo = self.undo, None
        self.dismiss()
        if fn is None:
            return False
        fn()
        return True

    def dismiss(self):
        """사라진 토스트의 실행 취소는 남기지 않는다(나중 Ctrl+Z가 오래된 상태로 되돌리지 않게)."""
        self.undo = None
        self.timer.stop()
        self.hide()
