"""API 키 설정 창 (4단계 설계 D6). 키는 화면·상태 문구·로그에 보이지 않는다.

연결 시험은 작업 스레드(TaskRunner)에서 돌려 창이 멈추지 않게 한다. 주 창의 작업 줄과 섞이지 않게 자체 TaskRunner를 쓴다.
"""

from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from hazop.app.widgets import TaskRunner
from hazop.study.apikey import key_problem, mask
from hazop.study.claude_http import ClaudeHttpClient


class SettingsDialog(QDialog):
    def __init__(self, store, parent=None, opener=None):
        super().__init__(parent)
        self.store = store
        self.opener = opener
        self.tasks = TaskRunner(self)
        self.setWindowTitle("API 키 설정")
        self.setMinimumWidth(460)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-ant-…  (비워 두면 지금 키 유지)")
        self.persist_box = QCheckBox("이 PC에 저장(Windows 암호화)")
        self.status_label = QLabel("")
        self.message_label = QLabel("")
        self.message_label.setObjectName("muted")
        self.message_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("API 키", self.key_edit)
        form.addRow("", self.persist_box)
        form.addRow("상태", self.status_label)

        self.test_btn = QPushButton("연결 시험")
        save_btn = QPushButton("저장")
        clear_btn = QPushButton("키 지우기")
        close_btn = QPushButton("닫기")
        self.test_btn.clicked.connect(self.test_connection)
        save_btn.clicked.connect(self.save)
        clear_btn.clicked.connect(self.clear_key)
        close_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (self.test_btn, save_btn, clear_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.message_label)
        lay.addLayout(buttons)
        self.refresh()

    def status_text(self):
        if self.store.get():
            return "저장됨(암호화)" if self.store.is_persisted() else "이번 실행만"
        return "없음" + (" (%s)" % self.store.load_error if self.store.load_error else "")

    def refresh(self):
        self.persist_box.setChecked(self.store.is_persisted())
        self.status_label.setText(self.status_text())

    def save(self):
        key = self.key_edit.text().strip()
        if not key:
            self.message_label.setText("저장할 키를 입력하세요.")
            return
        try:
            self.store.set(key, persist=self.persist_box.isChecked())
        except ValueError as exc:  # key_problem 문구(키 값 없음)
            self.message_label.setText(str(exc))
            return
        except OSError as exc:
            self.message_label.setText(mask("키를 암호화해 저장하지 못함: %s" % exc, key))
            return
        self.key_edit.clear()
        self.message_label.setText("저장함.")
        self.refresh()

    def clear_key(self):
        self.store.clear()
        self.key_edit.clear()
        self.message_label.setText("키를 지움.")
        self.refresh()

    def test_connection(self):
        key = self.key_edit.text().strip() or self.store.get()
        if not key:
            self.message_label.setText("시험할 키가 없음. 키를 입력하세요.")
            return
        if key_problem(key):
            self.message_label.setText(key_problem(key))
            return
        client = ClaudeHttpClient(lambda: key, opener=self.opener)
        self.test_btn.setEnabled(False)
        self.message_label.setText("연결 시험 중…")

        def done(res):
            self.test_btn.setEnabled(True)
            self.message_label.setText(res["message"])

        def failed(err):
            self.test_btn.setEnabled(True)
            self.message_label.setText(mask("연결 시험 중 오류: %s" % err, key))

        self.tasks.run("API 연결 시험", client.test_connection, done, failed)
