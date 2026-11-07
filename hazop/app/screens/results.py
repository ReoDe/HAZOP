"""⑤ 분석 결과 화면 자리. 3단계 구현 전 빈 화면(stage3-spec §A)."""

from PySide6.QtWidgets import QVBoxLayout, QWidget

from hazop.app.widgets import empty_label


class ResultsScreen(QWidget):
    title = "⑤ 분석 결과"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(empty_label("분석 결과 화면은 준비 중입니다. ④ 검토구간을 확정하면 여기서 편차별 결과를 봅니다."), 1)

    def where(self):
        return None

    def on_enter(self):
        pass

    def is_done(self):
        return False
