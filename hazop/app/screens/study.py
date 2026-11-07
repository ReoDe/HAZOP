"""④ 검토구간(HAZOP study node) 화면 자리. 3단계 구현 전 빈 화면(stage3-spec §A)."""

from PySide6.QtWidgets import QVBoxLayout, QWidget

from hazop.app.widgets import empty_label


class StudyNodesScreen(QWidget):
    title = "④ 검토구간"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(empty_label("검토구간 화면은 준비 중입니다. ③ 지식그래프까지 만든 뒤 여기서 구간을 제안·확정합니다."), 1)

    def where(self):
        return None

    def on_enter(self):
        pass

    def is_done(self):
        return False
