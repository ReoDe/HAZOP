"""오른쪽 관련 항목 패널 (UIUX 개선명세 U-14, 옵시디언 백링크에 해당).

고른 대상(칸·구성요소·구간)의 도면 위치, 구성요소, 지식그래프 근거, 같은 구성요소를 쓰는 다른 칸, 변경 이력을
섹션마다 개수와 함께 보인다. 섹션은 머리를 눌러 접는다. 행을 누르면 open_target(target)을 부른다.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QLabel, QListWidget, QListWidgetItem, QScrollArea, QToolButton, QVBoxLayout,
                               QWidget)

from hazop.app import related

ROW_H = 22


class Section(QWidget):
    def __init__(self, title, on_open, parent=None):
        super().__init__(parent)
        self.title, self.on_open = title, on_open
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = QToolButton()
        self.head.setObjectName("rel_head")
        self.head.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.head.setArrowType(Qt.DownArrow)
        self.head.setCheckable(True)
        self.head.setChecked(True)
        self.head.toggled.connect(self._toggle)
        lay.addWidget(self.head)
        self.list = QListWidget()
        self.list.setObjectName("rel_list")
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.itemClicked.connect(self._clicked)
        lay.addWidget(self.list)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setContentsMargins(10, 0, 0, 4)
        lay.addWidget(self.hint)

    def set_rows(self, rows, hint):
        self.rows = rows
        self.head.setText("%s   %d" % (self.title, len(rows)))
        self.list.clear()
        for r in rows:
            it = QListWidgetItem(r.text + ("   ·  %s" % r.detail if r.detail else ""))
            it.setToolTip("%s\n%s" % (r.text, r.detail) if r.detail else r.text)
            it.setData(Qt.UserRole, r.target)
            if r.target is None:
                it.setFlags(Qt.ItemIsEnabled)
            self.list.addItem(it)
        self.list.setFixedHeight(len(rows) * ROW_H + (2 if rows else 0))
        self.hint.setText(hint if not rows else "")
        self._toggle(self.head.isChecked())

    def _toggle(self, on):
        self.head.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.list.setVisible(on and bool(getattr(self, "rows", None)))
        self.hint.setVisible(on and bool(self.hint.text()))

    def _clicked(self, item):
        target = item.data(Qt.UserRole)
        if target:
            self.on_open(target)


EMPTY_HINTS = {"도면 위치": "도면 위치 없음", "구성요소": "구성요소 없음", "지식그래프 근거": "연결된 지식 항목 없음",
               "같은 구성요소를 쓰는 다른 칸": "결과가 있는 다른 칸 없음", "변경 이력": "기록 없음"}


class RelatedPanel(QFrame):
    """show(index, sel)로 다시 그린다. open_target은 행을 누를 때 부를 함수."""

    def __init__(self, open_target, parent=None):
        super().__init__(parent)
        self.setObjectName("related")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title = QLabel("관련 항목")
        self.title.setObjectName("rel_title")
        self.title.setTextFormat(Qt.PlainText)
        lay.addWidget(self.title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("rel_body")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 4, 0, 4)
        self.body.setSpacing(2)
        self.sections = {k: Section(k, open_target) for k in related.SECTIONS}
        for s in self.sections.values():
            self.body.addWidget(s)
        self.empty = QLabel("행렬 칸·구간·도면의 구성요소를 고르면\n도면 위치, 지식그래프 근거, 같은 구성요소를 쓰는\n"
                            "다른 칸이 여기에 모입니다.")
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        self.empty.setContentsMargins(12, 12, 12, 12)
        self.body.addWidget(self.empty)
        self.body.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        self.sel = None
        self.show_for(None, None)

    def show_for(self, index, sel):
        self.sel = sel
        has = bool(sel) and index is not None and index.graph is not None
        self.title.setText("관련 항목" + (" · %s" % related.selection_title(index, sel) if has else ""))
        self.empty.setVisible(not has)
        groups = related.related(index, sel) if has else [(k, []) for k in related.SECTIONS]
        for name, rows in groups:
            self.sections[name].set_rows(rows, EMPTY_HINTS[name])
            self.sections[name].setVisible(has)

    def counts(self):
        return {k: len(getattr(s, "rows", [])) for k, s in self.sections.items()}
