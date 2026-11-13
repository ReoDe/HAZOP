"""API 키 입력 상자(Qt). 새 웹 화면은 키를 웹으로 받지 않고 이 상자로 Python 쪽에서만 받는다(hazop/shell/api_settings.add_key).

이전 화면 설정 창(hazop/app/settings_dialog.py)의 '새 키 추가'와 같은 확인을 한다: 키 칸은 가려 보이고(보기 단추로만 잠깐 보임),
앞뒤 공백·줄바꿈은 지우고, 형식 문제(apikey.key_problem)는 저장 전에 알리며, 키를 넣은 채 닫으면 버릴지 묻는다.
"""

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout)

from hazop.study import apikey


class KeyDialog(QDialog):
    def __init__(self, name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 키 추가")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        note = QLabel("Anthropic Console에서 발급한 키를 붙여 넣으세요. 키는 이 창에서만 받고 화면·기록에 남기지 않습니다. "
                      "API 키로 분석하면 호출마다 요금이 나갑니다.")
        note.setWordWrap(True)
        lay.addWidget(note)
        form = QFormLayout()
        self.name_edit = QLineEdit(name)
        self.name_edit.setMaxLength(40)
        self.name_edit.setPlaceholderText(apikey.DEFAULT_NAME)
        self.name_edit.setAccessibleName("키 이름")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setAccessibleName("API 키")
        self.show_btn = QPushButton("보기")
        self.show_btn.setCheckable(True)
        self.show_btn.toggled.connect(lambda on: self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.persist = QCheckBox("이 PC에 저장(Windows 계정으로 암호화)")
        self.persist.setChecked(True)
        form.addRow("이름", self.name_edit)
        form.addRow("API 키", self.key_edit)
        form.addRow("", self.show_btn)
        form.addRow("", self.persist)
        lay.addLayout(form)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color:#a8201a")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        box = QDialogButtonBox()
        self.ok = box.addButton("추가하고 시험", QDialogButtonBox.AcceptRole)
        box.addButton("취소", QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.result_value = None

    def accept(self):
        key = apikey.clean_key(self.key_edit.text())
        problem = apikey.key_problem(key)
        if problem:
            self.msg.setText("추가할 키를 붙여 넣으세요." if not key else problem)
            return
        self.result_value = (self.name_edit.text().strip(), key, self.persist.isChecked())
        self.key_edit.clear()
        super().accept()

    def reject(self):
        if self.key_edit.text().strip() and self.ask_discard() is False:
            return
        self.key_edit.clear()
        super().reject()

    def ask_discard(self):
        return QMessageBox.question(self, "추가하지 않은 키", "입력한 키를 아직 추가하지 않았습니다. 버리고 닫을까요?") == QMessageBox.Yes


def ask_key(name="", parent=None):
    """→ (이름, 키, 이 PC에 저장) 또는 None(취소)."""
    dlg = KeyDialog(name, parent)
    dlg.exec()
    value, dlg.result_value = dlg.result_value, None
    return value
