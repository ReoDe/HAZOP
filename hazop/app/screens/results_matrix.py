"""⑤ 구간 × 편차 행렬의 모델과 뷰.

1,800행 × 44열이면 칸마다 아이템을 만드는 데만 1초가 넘게 걸려서, 칸 글자·상태·툴팁을 보이는 칸만 그때그때 계산한다.
뷰는 QTableWidget과 같은 이름으로 칸을 읽고 고르게 한다(item, verticalHeaderItem, setCurrentCell, cellClicked).
"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QTableView

from hazop.app.screens.results_paint import CELL_ROLE

EMPTY_SUMMARY = {"state": "not_analyzed", "scenarios": 0, "max_risk": None, "unreviewed": 0}


def empty_cell_label(run):
    """항목 없는 분석 칸의 문구. AI가 '해당 없음'이라 한 칸과, 해당한다면서 시나리오를 내지 않은 칸을 구분한다."""
    if run.get("applicable") is False:
        return "해당 없음(AI 판단)"
    if run.get("applicable") is True:
        return "시나리오 없음(AI)"
    return "항목 없음"


def cell(name, label, s, run, mark):
    """칸 하나의 (글자, 상태, 툴팁). mark는 None, "running", "limit", "failed" 중 하나, run은 그 칸의 ai_run."""
    tip = "%s × %s" % (name, label)
    if mark == "running":
        return "분석 중", {"kind": "running"}, "%s\nAI 호출 중" % tip
    if mark == "limit":
        return ("한도로 멈춤", {"kind": "limit"},
                "%s\n구독 사용 한도에 닿아 멈춤(실패 아님, 다시 실행): %s" % (tip, run.get("error") or "-"))
    if mark == "failed":
        return "실패", {"kind": "failed"}, "%s\nAI 실행 실패(위험도 아님): %s" % (tip, run.get("error") or "-")
    if s["state"] == "not_analyzed":
        return "분석 전", {"kind": "not_analyzed"}, tip
    if s["state"] == "excluded":
        return "제외", {"kind": "excluded"}, tip
    state = {"kind": "scored", "risk": s["max_risk"], "unreviewed": s["unreviewed"], "scenarios": s["scenarios"]}
    lines = ["%d건" % s["scenarios"]]
    if s["max_risk"] is not None:
        lines.append("위험 %d" % s["max_risk"])
    if s["scenarios"] == 0 and not s["unreviewed"] and run.get("status") == "ok":
        lines = [empty_cell_label(run), "AI 초안"]
        state = {"kind": "empty"}
    else:
        lines.append("미검토 %d" % s["unreviewed"] if s["unreviewed"] else "완료")
    text = "\n".join(lines)
    return text, state, "%s\n%s" % (tip, " · ".join(lines))


class MatrixModel(QAbstractTableModel):
    """rows: [{"node", "color", "label", "tip"}], deviations, summary {node_id: {deviation_id: 요약}},
    runs {(node_id, deviation_id): ai_run}, marks {(node_id, deviation_id): mark}. 칸 값은 처음 읽을 때 계산해 둔다."""

    def __init__(self, icon_of, parent=None):
        super().__init__(parent)
        self.icon_of = icon_of
        self.rows, self.deviations, self.summary, self.runs, self.marks = [], [], {}, {}, {}
        self._cells = {}

    def set_data(self, rows, deviations, summary, runs, marks):
        self.beginResetModel()
        self.rows, self.deviations, self.summary, self.runs, self.marks = rows, deviations, summary, runs, marks
        self._cells = {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.deviations)

    def cell_at(self, r, c):
        hit = self._cells.get((r, c))
        if hit is None:
            n, d = self.rows[r]["node"], self.deviations[c]
            key = (n["node_id"], d["deviation_id"])
            s = self.summary.get(key[0], {}).get(key[1]) or EMPTY_SUMMARY
            hit = cell("%s %s" % (n["node_id"], n["name"]), d["label"], s, self.runs.get(key) or {}, self.marks.get(key))
            self._cells[(r, c)] = hit
        return hit

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows) or index.column() >= len(self.deviations):
            return None
        if role == Qt.DisplayRole:
            return self.cell_at(index.row(), index.column())[0]
        if role == CELL_ROLE:
            return self.cell_at(index.row(), index.column())[1]
        if role == Qt.ToolTipRole:
            return self.cell_at(index.row(), index.column())[2]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal:
            if not 0 <= section < len(self.deviations):
                return None
            d = self.deviations[section]
            if role == Qt.DisplayRole:
                return "%s %s" % (d["parameter"], d["guideword"])
            if role == Qt.ToolTipRole:
                return "%s %s" % (d["deviation_id"], d["label"])
            return None
        if not 0 <= section < len(self.rows):
            return None
        row = self.rows[section]
        if role == Qt.DisplayRole:
            return row["label"]
        if role == Qt.ToolTipRole:
            return row["tip"]
        if role == Qt.DecorationRole:
            return self.icon_of(row)
        return None


class _Read:
    """QTableWidgetItem처럼 읽기만 하는 칸·머리(text, toolTip, data)."""

    def __init__(self, get):
        self._get = get

    def text(self):
        return self._get(Qt.DisplayRole)

    def toolTip(self):  # noqa: N802
        return self._get(Qt.ToolTipRole)

    def data(self, role):
        return self._get(role)


class MatrixView(QTableView):
    cellClicked = Signal(int, int)  # noqa: N815

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clicked.connect(lambda ix: self.cellClicked.emit(ix.row(), ix.column()))

    def rowCount(self):  # noqa: N802
        return self.model().rowCount()

    def columnCount(self):  # noqa: N802
        return self.model().columnCount()

    def currentRow(self):  # noqa: N802
        return self.currentIndex().row()

    def currentColumn(self):  # noqa: N802
        return self.currentIndex().column()

    def setCurrentCell(self, r, c):  # noqa: N802
        self.setCurrentIndex(self.model().index(r, c))

    def item(self, r, c):
        ix = self.model().index(r, c)
        return _Read(lambda role: ix.data(role)) if ix.isValid() else None

    def verticalHeaderItem(self, r):  # noqa: N802
        m = self.model()
        return _Read(lambda role: m.headerData(r, Qt.Vertical, role)) if 0 <= r < m.rowCount() else None
