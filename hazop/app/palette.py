"""명령 팔레트 (UIUX 개선명세 U-01). 구성요소·구간·워크시트 칸·지식그래프·명령을 한 상자에서 찾는다.

검색은 순수 함수 search()다. 접두어 '#' 구간, '@' 구성요소, '>' 명령으로 종류를 좁힌다. 검색어는 글자 순서만 맞으면
찾는다(퍼지). 빈 검색어면 최근 연 항목, 그다음 명령을 보인다. Enter는 열기, Ctrl+Enter는 새 탭으로 열기다.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from hazop.app import tokens

KINDS = ("command", "component", "node", "cell", "graph")
KIND_TITLES = {"recent": "최근", "command": "명령", "component": "구성요소", "node": "검토구간", "cell": "워크시트 칸",
               "graph": "지식그래프"}
PREFIXES = {"#": "node", "@": "component", ">": "command"}
LIMIT = 60


@dataclass
class Item:
    kind: str
    label: str
    detail: str = ""
    keys: str = ""
    open: object = None   # open(new_tab) — new_tab은 Ctrl+Enter로 열었는지
    key: tuple = field(default=None)  # 최근 목록에서 같은 항목을 알아보는 값

    def ident(self):
        return self.key or (self.kind, self.label)


def fuzzy_score(query, text):
    """query 글자가 text에 순서대로 모두 있으면 점수(클수록 앞), 없으면 None. 대소문자·공백 무시.
    붙어 있는 글자와 단어 머리 글자에 가산점을 주고 긴 글은 조금 깎는다."""
    q = "".join(query.lower().split())
    if not q:
        return 0
    t = text.lower()
    pos, score, prev = 0, 0, -2
    for ch in q:
        i = t.find(ch, pos)
        if i < 0:
            return None
        score += 3 if i == prev + 1 else 1
        if i == 0 or not t[i - 1].isalnum():
            score += 2
        prev, pos = i, i + 1
    if t.startswith(q):
        score += 5
    return score * 100 - len(t)


def parse(query):
    """(종류 또는 None, 검색어)."""
    q = query.lstrip()
    if q[:1] in PREFIXES:
        return PREFIXES[q[0]], q[1:].strip()
    return None, q.strip()


def search(items, query, recent=(), limit=LIMIT):
    """[(묶음 이름, [Item])] — 묶음은 KINDS 순서. 빈 검색어면 최근(recent의 ident 순서)과 명령."""
    kind, q = parse(query)
    pool = [it for it in items if kind is None or it.kind == kind]
    if not q:
        if kind is None:
            by_id = {it.ident(): it for it in pool}
            rec = [by_id[k] for k in recent if k in by_id][:8]
            groups = [("recent", rec)] if rec else []
            return groups + [("command", [it for it in pool if it.kind == "command"][:limit])]
        return [(kind, pool[:limit])]
    scored = []
    for i, it in enumerate(pool):
        s = fuzzy_score(q, "%s %s" % (it.label, it.detail))
        if s is not None:
            scored.append((-s, i, it))
    scored.sort(key=lambda x: (x[0], x[1]))
    hits = [it for _, _, it in scored[:limit]]
    return [(k, [it for it in hits if it.kind == k]) for k in KINDS if any(it.kind == k for it in hits)]


class PaletteDialog(QDialog):
    """창 위쪽 가운데에 뜨는 검색 상자. items는 열 때 한 번 받는다. 고른 항목은 chosen(Item, new_tab)으로 알린다."""

    def __init__(self, parent, items, recent=(), chosen=None, query=""):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("palette")
        self.items, self.recent, self.chosen = list(items), list(recent), chosen
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.edit = QLineEdit(query)
        self.edit.setPlaceholderText("구간 #  구성요소 @  명령 >  · Enter 열기 · Ctrl+Enter 새 탭")
        self.edit.textChanged.connect(self.refresh)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setObjectName("palette_list")
        self.list.itemActivated.connect(lambda it: self.activate(it))
        lay.addWidget(self.list)
        w = min(640, max(420, parent.width() - 80))
        self.resize(w, min(460, max(260, parent.height() - 120)))
        top = parent.mapToGlobal(parent.rect().topLeft())
        self.move(top.x() + (parent.width() - w) // 2, top.y() + 40)
        self.refresh()

    def refresh(self):
        self.list.clear()
        first = None
        for kind, its in search(self.items, self.edit.text(), self.recent):
            if not its:
                continue
            head = QListWidgetItem(KIND_TITLES[kind])
            head.setFlags(Qt.NoItemFlags)
            head.setForeground(QColor(tokens.c("muted")))
            f = head.font()
            f.setBold(True)
            f.setPixelSize(tokens.FONT_SIZE["xs"])
            head.setFont(f)
            self.list.addItem(head)
            for it in its:
                text = it.label + ("   %s" % it.detail if it.detail else "") + ("   [%s]" % it.keys if it.keys else "")
                row = QListWidgetItem(text)
                row.setData(Qt.UserRole, it)
                row.setToolTip(text)
                self.list.addItem(row)
                first = first or row
        if first is not None:
            self.list.setCurrentItem(first)

    def results(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).data(Qt.UserRole) is not None]

    def _move(self, step):
        n = self.list.count()
        i = self.list.currentRow()
        for _ in range(n):
            i = (i + step) % n if n else -1
            if n and self.list.item(i).data(Qt.UserRole) is not None:
                self.list.setCurrentRow(i)
                return

    def eventFilter(self, obj, ev):  # noqa: N802
        from PySide6.QtCore import QEvent
        if obj is self.edit and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                self._move(1 if k == Qt.Key_Down else -1)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.activate(self.list.currentItem(), bool(ev.modifiers() & Qt.ControlModifier))
                return True
        return super().eventFilter(obj, ev)

    def activate(self, row, new_tab=False):
        it = row.data(Qt.UserRole) if row is not None else None
        if it is None:
            return False
        self.accept()
        if self.chosen:
            self.chosen(it, new_tab)
        return True
