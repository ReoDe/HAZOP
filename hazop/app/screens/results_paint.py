"""⑤ 행렬·워크시트 그리기 (UIUX 개선명세 U-19·U-20·U-21).

- CellDelegate: 행렬 칸 한 줄. 숫자 = 최고 위험도(〈표9〉 3단 색), 오른쪽 위 '미N' = 미검토 수.
  AI 실행 실패 칸은 위험도 색을 쓰지 않는다: 흰 바탕 + 빨강 점선 테두리 + '! 실패'(U-19, 결함 W-1).
  구독 한도로 멈춘 칸은 실패와 구분한다: 주황 바탕 + 주황 실선 테두리 + '한도로 멈춤' 두 줄(화면 설계 §7.3, D6).
- GroupHeader: 편차 머리 두 단(위 변수, 아래 가이드워드). 같은 변수가 이어진 열은 위 칸을 하나로 그린다.
- SheetDelegate: 워크시트 첫 열 왼쪽 띠(AI 초안 회색, 선택 파랑), AI 근거 열의 ⚠ 경고는 빨강 테두리 칩(W-6).
칸 상태는 아이템의 CELL_ROLE에 {"kind", "risk", "unreviewed", "scenarios"}로 둔다. 아이템 text()는 화면 읽기·테스트용
설명 글자 그대로다.
"""

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtWidgets import QHeaderView, QStyle, QStyledItemDelegate

from hazop.app import tokens

CELL_ROLE = Qt.UserRole + 10
DRAFT_ROLE = Qt.UserRole + 11
FAILED_TEXT = "! 실패"
LIMIT_TEXT = "한도로\n멈춤"
WARN_PREFIX = "⚠ "


def _font(px, bold=False):
    f = QFont(tokens.FONT_FAMILY)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


RUNNING_TEXT = "분석 중"


def cell_style(state):
    """칸 상태 → (바탕, 글자색, 테두리 dict 또는 None, 가운데 글자). 실패는 위험도 색과 겹치지 않는다."""
    kind = state["kind"]
    c = tokens.COLORS
    if kind == "failed":
        return c["card"], c["err-ink"], {"color": c["err-ink"], "dash": True}, FAILED_TEXT
    if kind == "limit":
        return c["warn-bg"], c["warn-ink"], {"color": c["warn-line"], "dash": False}, LIMIT_TEXT
    if kind == "not_analyzed":
        return "hatch", c["muted"], None, "–"
    if kind == "running":
        return c["ui-weak"], c["ui-ink"], {"color": c["ui"], "dash": False}, RUNNING_TEXT
    if kind == "excluded":
        return c["card"], c["muted"], None, "제외"
    if kind == "empty":  # AI가 해당 없음·시나리오 없음이라 한 칸도 사람이 보기 전까지 AI 초안이다(점선 = AI)
        return "hatch", c["ai-ink"], {"color": c["ai-ink"], "dash": True}, "없음"
    risk = state.get("risk")
    if risk is None:
        return c["card"], c["ink-2"], None, "%d건" % (state.get("scenarios") or 0)
    bg, ink, _line = tokens.risk_colors(risk)
    return bg, ink, None, str(risk)


class CellDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        state = index.data(CELL_ROLE)
        if not state:
            return super().paint(p, option, index)
        bg, ink, border, text = cell_style(state)
        r = option.rect.adjusted(1, 1, -1, -1)
        p.save()
        if bg == "hatch":
            p.fillRect(r, QColor(tokens.c("card")))
            p.fillRect(r, QBrush(QColor(tokens.c("ai-hatch-b")), Qt.BDiagPattern))
        else:
            p.fillRect(r, QColor(bg))
        if border:
            pen = QPen(QColor(border["color"]), 1.5, Qt.DashLine if border["dash"] else Qt.SolidLine)
            p.setPen(pen)
            p.drawRect(r.adjusted(0, 0, -1, -1) if state["kind"] == "limit" else r.adjusted(2, 2, -3, -3))
        p.setPen(QColor(ink))
        p.setFont(_font(10 if state["kind"] == "limit" else tokens.FONT_SIZE["sm"],
                        bold=state["kind"] in ("scored", "failed", "limit")))
        p.drawText(r, Qt.AlignCenter, text)
        if state["kind"] == "empty":
            p.setFont(_font(9))
            p.drawText(r.adjusted(3, 1, 0, 0), Qt.AlignLeft | Qt.AlignTop, "AI")
        if state.get("unreviewed") and state["kind"] == "scored":
            p.setFont(_font(9))
            p.drawText(r.adjusted(0, 1, -3, 0), Qt.AlignRight | Qt.AlignTop, "미%d" % state["unreviewed"])
        if option.state & QStyle.State_Selected:
            p.setPen(QPen(QColor(tokens.c("ui")), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(r).adjusted(1, 1, -1, -1))
        p.restore()


class GroupHeader(QHeaderView):
    """가로 머리 두 단. groups[col] = (변수, 가이드워드)."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.groups = []
        self.setDefaultAlignment(Qt.AlignCenter)
        self.setSectionsClickable(True)

    def set_groups(self, groups):
        self.groups = list(groups)
        self.viewport().update()

    def sizeHint(self):  # noqa: N802
        s = super().sizeHint()
        return QSize(s.width(), 40)

    def _span(self, col):
        param = self.groups[col][0]
        a = col
        while a > 0 and self.groups[a - 1][0] == param:
            a -= 1
        b = col
        while b + 1 < len(self.groups) and self.groups[b + 1][0] == param:
            b += 1
        return a, b

    def paintSection(self, p, rect, col):  # noqa: N802
        if not rect.isValid() or col >= len(self.groups):
            return super().paintSection(p, rect, col)
        param, guide = self.groups[col]
        c = tokens.COLORS
        half = rect.height() // 2
        top = QRect(rect.left(), rect.top(), rect.width(), half)
        bottom = QRect(rect.left(), rect.top() + half, rect.width(), rect.height() - half)
        p.save()
        p.fillRect(rect, QColor(c["surface-2"]))
        p.setPen(QColor(c["line"]))
        p.drawLine(bottom.topLeft(), bottom.topRight())
        p.drawLine(bottom.topRight(), bottom.bottomRight())
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        a, b = self._span(col)
        if col == b:
            p.drawLine(top.topRight(), top.bottomRight())
        left = self.sectionViewportPosition(a)
        right = self.sectionViewportPosition(b) + self.sectionSize(b)
        group = QRect(left, top.top(), right - left, half).intersected(self.viewport().rect())
        p.setClipRect(top)
        p.setPen(QColor(c["ink-2"]))
        p.setFont(_font(tokens.FONT_SIZE["sm"], bold=True))
        p.drawText(group, Qt.AlignCenter, param)
        p.setClipping(False)
        p.setPen(QColor(c["muted"]))
        p.setFont(_font(tokens.FONT_SIZE["xs"]))
        p.drawText(bottom, Qt.AlignCenter, guide)
        p.restore()


class SheetDelegate(QStyledItemDelegate):
    """워크시트: 0열 왼쪽 띠, 근거 열(basis_col)의 ⚠ 줄은 빨강 테두리 칩."""

    def __init__(self, basis_col, parent=None):
        super().__init__(parent)
        self.basis_col = basis_col

    def _split(self, text):
        lines = (text or "").split("\n")
        return [l for l in lines if not l.startswith(WARN_PREFIX)], [l for l in lines if l.startswith(WARN_PREFIX)]

    def sizeHint(self, option, index):  # noqa: N802
        s = super().sizeHint(option, index)
        if index.column() != self.basis_col:
            return s
        plain, warns = self._split(index.data())
        fm = option.fontMetrics
        w = max(60, option.rect.width() - 12) if option.rect.width() > 0 else 160
        h = sum(fm.boundingRect(QRect(0, 0, w, 10000), Qt.TextWordWrap, l).height() for l in plain)
        h += sum(fm.boundingRect(QRect(0, 0, w - 12, 10000), Qt.TextWordWrap, l).height() + 10 for l in warns)
        return QSize(s.width(), max(s.height(), h + 10))

    def paint(self, p, option, index):
        draft = index.data(DRAFT_ROLE)
        if index.column() == self.basis_col and WARN_PREFIX in (index.data() or ""):
            self._paint_basis(p, option, index)
        else:
            super().paint(p, option, index)
        if index.column() == 0:
            selected = bool(option.state & QStyle.State_Selected)
            if selected or draft:
                p.fillRect(QRect(option.rect.left(), option.rect.top(), 3, option.rect.height()),
                           QColor(tokens.c("ui") if selected else tokens.c("line-strong")))

    def _paint_basis(self, p, option, index):
        opt = option
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, p, opt.widget)
        plain, warns = self._split(index.data())
        c = tokens.COLORS
        r = option.rect.adjusted(6, 4, -6, -4)
        fm = option.fontMetrics
        p.save()
        y = r.top()
        p.setPen(QColor(c["ui-ink"]))
        for l in plain:
            br = fm.boundingRect(QRect(r.left(), y, r.width(), 10000), Qt.TextWordWrap, l)
            p.drawText(QRect(r.left(), y, r.width(), br.height()), Qt.TextWordWrap, l)
            y += br.height()
        for l in warns:
            y += 3
            br = fm.boundingRect(QRect(0, 0, r.width() - 12, 10000), Qt.TextWordWrap, l)
            chip = QRect(r.left(), y, min(r.width(), br.width() + 12), br.height() + 6)
            p.setPen(QPen(QColor(c["err-line"]), 1))
            p.setBrush(QColor(c["err-bg"]))
            p.drawRoundedRect(chip, 3, 3)
            p.setPen(QColor(c["err-ink"]))
            p.drawText(chip.adjusted(6, 3, -6, -3), Qt.TextWordWrap, l)
            y += chip.height() + 4
        p.restore()
