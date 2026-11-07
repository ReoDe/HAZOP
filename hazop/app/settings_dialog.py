"""API 키 설정 창 (4단계 설계 D6). 키는 화면·상태 문구·로그에 보이지 않는다(끝 4자리 hint만).

위에서부터 연결 상태(무엇에 어떻게 연결됐는지), 사용할 키 드롭다운, 모델 드롭다운(단가·구간당 예상 비용), 새 키 추가 순이다.
키 선택·모델·이름 변경·삭제는 바로 적용한다. 저장하지 않는 변경은 새 키 입력칸뿐이라 닫을 때 그것만 확인한다.
연결 시험은 작업 스레드(TaskRunner)에서 돌려 창이 멈추지 않게 한다. 주 창의 작업 줄과 섞이지 않게 자체 TaskRunner를 쓴다.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from hazop.app import tokens
from hazop.app.widgets import Chip, TaskRunner, esc, kst_text
from hazop.study import claude_http
from hazop.study.apikey import clean_key, key_problem, mask
from hazop.study.claude_http import ClaudeHttpClient
from hazop.study.nodes import now_utc

TARGET_HOST = claude_http.API_BASE.split("//", 1)[1]


def connection_state(store):
    """(상태, 짧은 문구). 상태: none(키 없음) · unknown(확인 안 함) · ok(연결됨) · fail(연결 안 됨).
    마지막 시험이 지금 모델이 아닌 다른 모델로 한 것이면 확인 안 함으로 본다."""
    e = store.active()
    if e is None:
        return "none", "API 키 없음"
    t = e["last_test"]
    if not t or t.get("model") != store.model:
        return "unknown", "확인 안 함"
    return ("ok", "연결됨") if t["ok"] else ("fail", "연결 안 됨")


def status_bar_html(store):
    """주 창 상태 표시줄 링크(어두운 바탕). 점 색과 글자로 상태를 함께 보인다."""
    state, text = connection_state(store)
    dot = {"ok": "rail-check", "fail": "err-line"}.get(state, "nav-muted")
    e = store.active()
    label = "AI %s%s" % (text, " · %s" % e["name"] if e else "")
    return ('<a href="key" style="color:%s; text-decoration:none"><span style="color:%s">●</span> %s</a>'
            % (tokens.c("nav-ink"), tokens.c(dot), esc(label)))


def usd(v):
    return ("$%.2f" % v) if v >= 0.1 else ("$%.3f" % v).rstrip("0")


class SettingsDialog(QDialog):
    def __init__(self, store, parent=None, opener=None):
        super().__init__(parent)
        self.store = store
        self.opener = opener
        self.tasks = TaskRunner(self)
        self.setWindowTitle("API 키 설정")
        self.setMinimumWidth(620)

        # 연결 상태
        card = QFrame()
        card.setObjectName("panel")
        cl = QVBoxLayout(card)
        top = QHBoxLayout()
        self.state_chip = Chip("")
        self.test_btn = QPushButton("연결 시험(&T)")
        self.test_btn.setObjectName("primary")
        self.test_btn.clicked.connect(self.test_connection)
        top.addWidget(self.state_chip)
        top.addStretch(1)
        top.addWidget(self.test_btn)
        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.RichText)
        cl.addLayout(top)
        cl.addWidget(self.detail_label)

        # 사용할 키·모델
        self.key_combo = QComboBox()
        self.key_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.key_combo.setMinimumContentsLength(24)
        self.key_combo.activated.connect(self._select_key)
        self.rename_btn = QPushButton("이름 변경(&R)")
        self.delete_btn = QPushButton("삭제(&D)…")
        self.rename_btn.clicked.connect(self.rename_key)
        self.delete_btn.clicked.connect(self.delete_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_combo, 1)
        key_row.addWidget(self.rename_btn)
        key_row.addWidget(self.delete_btn)
        self.model_combo = QComboBox()
        for mid, m in claude_http.MODELS.items():
            self.model_combo.addItem(m["label"], mid)
        self.model_combo.activated.connect(self._select_model)
        self.price_label = QLabel("")
        self.price_label.setObjectName("muted")
        self.price_label.setWordWrap(True)
        use = QFormLayout()
        key_lab, model_lab = QLabel("사용할 키(&K)"), QLabel("모델(&M)")
        key_lab.setBuddy(self.key_combo)
        model_lab.setBuddy(self.model_combo)
        use.addRow(key_lab, key_row)
        use.addRow(model_lab, self.model_combo)
        use.addRow("", self.price_label)

        # 새 키 추가
        add_title = QLabel("새 키 추가")
        add_title.setObjectName("section")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 회사 워크스페이스, 개인 시험용")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-ant-…  붙여 넣기(공백은 자동 정리)")
        self.key_edit.returnPressed.connect(self.add_key)
        self.show_btn = QPushButton("보기(&V)")
        self.show_btn.setCheckable(True)
        self.show_btn.toggled.connect(self._toggle_echo)
        self.persist_box = QCheckBox("이 PC에 저장(Windows 암호화, 현재 사용자만 읽음)")
        self.persist_box.setChecked(True)
        self.add_btn = QPushButton("추가하고 시험(&A)")
        self.add_btn.clicked.connect(self.add_key)
        key_in = QHBoxLayout()
        key_in.addWidget(self.key_edit, 1)
        key_in.addWidget(self.show_btn)
        add = QFormLayout()
        name_lab, keyin_lab = QLabel("이름(&N)"), QLabel("API 키(&P)")
        name_lab.setBuddy(self.name_edit)
        keyin_lab.setBuddy(self.key_edit)
        add.addRow(name_lab, self.name_edit)
        add.addRow(keyin_lab, key_in)
        persist_row = QHBoxLayout()
        persist_row.addWidget(self.persist_box, 1)
        persist_row.addWidget(self.add_btn)
        add.addRow("", persist_row)
        help_label = QLabel(
            "키는 <a href='%s'>Anthropic Console › API keys</a>에서 발급합니다. 워크스페이스를 먼저 고른 뒤 "
            "<b>Create Key</b>를 누르고, 한 번만 보이는 키를 복사해 붙여 넣으세요. 키 전체는 이 창에 다시 보이지 않고 "
            "끝 4자리로만 구분합니다." % claude_http.CONSOLE_KEYS_URL)
        help_label.setObjectName("muted")
        help_label.setWordWrap(True)
        help_label.setOpenExternalLinks(True)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addWidget(self.message_label, 1)
        bottom.addWidget(close_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(card)
        lay.addLayout(use)
        lay.addSpacing(6)
        lay.addWidget(add_title)
        lay.addLayout(add)
        lay.addWidget(help_label)
        lay.addLayout(bottom)
        self.refresh()

    # ------------------------------------------------------------ 표시
    def refresh(self):
        entries = self.store.entries()
        self.key_combo.clear()
        for e in entries:
            where = "이 PC 저장" if e["persisted"] else "이번 실행만"
            self.key_combo.addItem("%s  (%s · %s)" % (e["name"], e["hint"], where), e["id"])
            if e["active"]:
                self.key_combo.setCurrentIndex(self.key_combo.count() - 1)
        if not entries:
            self.key_combo.addItem("키 없음. 아래에서 추가하세요", None)
        for w in (self.key_combo, self.rename_btn, self.delete_btn, self.test_btn):
            w.setEnabled(bool(entries))
        self.model_combo.setCurrentIndex(self.model_combo.findData(self.store.model))
        m = claude_http.MODELS[self.store.model]
        p = claude_http.PRICES[self.store.model]
        basis = "실측" if self.store.model == claude_http.DEFAULT_MODEL else "추정, Opus 실측을 단가 비율로 환산"
        self.price_label.setText("백만 토큰당 입력 %s · 출력 %s. 검토구간 1개 분석에 약 %s(%s)."
                                 % (usd(p["input"]), usd(p["output"]), usd(m["section_usd"]), basis))
        self._show_state()

    def _show_state(self):
        state, text = connection_state(self.store)
        self.state_chip.set_state({"ok": "● 연결됨", "fail": "● 연결 안 됨", "unknown": "○ 확인 안 함",
                                   "none": "○ 키 없음"}[state],
                                  {"ok": "passed", "fail": "blocked", "unknown": "warn"}.get(state, ""))
        e = self.store.active()
        rows = []
        if e:
            rows.append("<b>키</b> %s (%s) · %s" % (esc(e["name"]), esc(e["hint"]),
                                                   "이 PC에 암호화 저장" if e["persisted"] else "이번 실행만(저장 안 함)"))
        rows.append("<b>대상</b> Anthropic API %s · 모델 %s · API 버전 %s"
                    % (TARGET_HOST, self.store.model, claude_http.API_VERSION))
        t = e and e["last_test"]
        if t:
            rows.append("<b>마지막 시험</b> %s · %s%s" % (
                kst_text(t["at"]), "성공" if t["ok"] else "실패",
                "" if t.get("model") == self.store.model else " (다른 모델 %s로 시험함)" % esc(t.get("model") or "?")))
            if not t["ok"]:
                rows.append("<span style='color:%s'>%s</span>" % (tokens.c("err-ink"), esc(t["message"])))
        elif e:
            rows.append("아직 연결 시험을 하지 않았습니다. <b>연결 시험</b>을 누르세요(토큰 비용 없음).")
        else:
            rows.append("아래 <b>새 키 추가</b>에서 키를 넣으세요.")
        if self.store.load_error:
            rows.append("<span style='color:%s'>%s</span>" % (tokens.c("err-ink"), esc(self.store.load_error)))
        self.detail_label.setText("<br>".join(rows))
        lay = self.layout()
        if lay is not None:  # 줄바꿈 라벨 줄 수가 바뀌면 높이를 다시 잡는다(잘림 방지)
            lay.activate()
            need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.sizeHint().height()
            if need > self.height():
                self.resize(self.width(), need)

    def say(self, text, error=False):
        self.message_label.setStyleSheet("color: %s" % tokens.c("err-ink" if error else "muted"))
        self.message_label.setText(text)
        self._show_state()

    def _toggle_echo(self, on):
        self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self.show_btn.setText("숨기기(&V)" if on else "보기(&V)")

    # ------------------------------------------------------------ 동작
    def _apply(self, fn, done_text):
        """저장소를 바꾸는 동작. 파일 쓰기·암호화 실패는 창에 알린다(화면과 파일이 어긋난 채 조용히 넘어가지 않게)."""
        try:
            fn()
        except OSError as exc:
            self.refresh()
            self.say(mask("설정 파일에 쓰지 못함: %s" % exc, self.store.get()), True)
            return False
        self.refresh()
        self.say(done_text)
        return True

    def _select_key(self, i):
        kid = self.key_combo.itemData(i)
        if kid:
            self._apply(lambda: self.store.select(kid), "사용할 키를 바꿈.")

    def _select_model(self, i):
        model = self.model_combo.itemData(i)
        self._apply(lambda: self.store.set_model(model), "모델을 바꿈. 새 모델로 연결 시험을 해 보세요.")

    def add_key(self):
        key = clean_key(self.key_edit.text())
        if not key:
            self.say("추가할 키를 붙여 넣으세요.", True)
            return
        try:
            self.store.add(self.name_edit.text(), key, persist=self.persist_box.isChecked())
        except ValueError as exc:  # key_problem 문구(키 값 없음)
            self.say(str(exc), True)
            return
        except OSError as exc:
            self.say(mask("키를 암호화해 저장하지 못함: %s" % exc, key), True)
            return
        self.key_edit.clear()
        self.name_edit.clear()
        self.show_btn.setChecked(False)
        self.say("키를 추가함.")
        self.refresh()
        self.test_connection()

    def rename_key(self):
        e = self.store.active()
        if not e:
            return
        name = self._ask_name(e["name"])
        if name and name.strip():
            self._apply(lambda: self.store.rename(e["id"], name), "이름을 바꿈.")

    def delete_key(self):
        e = self.store.active()
        if not e or not self._ask_delete(e):
            return
        self._apply(lambda: self.store.remove(e["id"]), "'%s' 키를 지움." % e["name"])

    def clear_key(self):
        """사용 중인 키를 확인 없이 지운다(스크립트·테스트용)."""
        self.store.clear()
        self.refresh()

    def test_connection(self):
        e = self.store.active()
        key = self.store.get()
        if not key:
            self.say("시험할 키가 없음. 키를 추가하세요.", True)
            return
        if key_problem(key):
            self.say(key_problem(key), True)
            return
        kid, model = e["id"], self.store.model
        client = ClaudeHttpClient(lambda: key, model=model, opener=self.opener)
        self.test_btn.setEnabled(False)
        self.say("연결 시험 중… (%s, 모델 %s)" % (e["name"], model))

        def finish(ok, message):
            self.test_btn.setEnabled(True)
            if kid in {x["id"] for x in self.store.entries()}:
                try:
                    self.store.record_test(kid, ok, message, now_utc(), model)
                except OSError:
                    pass  # 시험 결과 기록 실패는 화면 표시만 못 남길 뿐 키에는 영향 없음
            self.refresh()
            self.say("연결 시험 성공." if ok else "연결 시험 실패. 위의 안내를 확인하세요.", not ok)

        self.tasks.run("API 연결 시험", client.test_connection, lambda res: finish(res["ok"], res["message"]),
                       lambda err: finish(False, mask("연결 시험 중 오류: %s" % err, key)))

    # ------------------------------------------------------------ 확인 창(테스트에서 바꿔 끼움)
    def _ask_name(self, current):
        name, ok = QInputDialog.getText(self, "키 이름 변경", "새 이름", text=current)
        return name if ok else None

    def _ask_delete(self, e):
        return QMessageBox.question(
            self, "키 삭제", "'%s' (%s) 키를 지울까요?\n이 PC에 저장한 암호화 사본도 지워지며 되돌릴 수 없습니다."
            % (e["name"], e["hint"])) == QMessageBox.Yes

    def _ask_discard(self):
        return QMessageBox.question(
            self, "추가하지 않은 키", "입력한 키를 아직 추가하지 않았습니다. 버리고 닫을까요?") == QMessageBox.Yes

    def done(self, r):
        if self.key_edit.text().strip() and not self._ask_discard():
            return
        self.key_edit.clear()
        super().done(r)
