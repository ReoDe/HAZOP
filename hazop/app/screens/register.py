"""① 자료 등록 (기획서/인터페이스.md §3.1). 등록·추출·그래프는 기존 함수(registry.register,
scripts/extract_drawio.run_one 또는 scripts/extract_pdf.run_one, scripts/build_graph.build_one)를 그대로 호출한다.
PDF는 등록이 끝나면 추출까지 자동으로 이어 하고 ② 도면 화면으로 옮긴다(drawio는 '추출·그래프 만들기' 버튼 그대로).
설계 문서(PDF)는 등록이 끝나면 지식 추출(data.extract_document)을 자동으로 하고 ③ 지식그래프로 옮긴다.
추출이 끝나면 프로젝트 지식그래프를 다시 빌드한다(data.build_project_kg)."""

import getpass
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton, QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import data, tokens
from hazop.app.widgets import VALIDATION_LABELS, badge, esc
from hazop.extract import svg_align
from hazop.register import fileinfo, registry
from hazop.study import nodes as sn

META_FIELDS = (("drawing_number", "도면번호"), ("design_revision", "개정번호"), ("title", "제목"))
OUTCOME_LABELS = {"registered": "등록 완료", "reused": "기존 등록 재사용(같은 해시)", "new_version": "새 등록 버전",
                  "failed": "실패", "on_hold": "보류"}
STATUS_LABELS = {"registered": "등록 완료", "failed": "실패", "on_hold": "보류", "draft": "저장 진행 중"}
# (화면 표시, registry 자료 종류, 파일 대화상자 거르개, 추출 버튼 문구)
MATERIAL_CHOICES = (
    ("P&ID 도면 (drawio·PDF)", "P&ID", "P&ID 원본 (*.drawio *.pdf);;draw.io (*.drawio *.xml);;PDF (*.pdf)",
     "추출·그래프 만들기"),
    ("설계 문서 (PDF)", "design_document", "설계 문서 PDF (*.pdf)", "지식 추출 다시 하기"),
)
EXTRACT_LABELS = {t: label for _, t, _, label in MATERIAL_CHOICES}
DOC_COUNT_LABELS = (("doc_chunk", "문서 조각"), ("setpoint", "설정치"), ("condition", "운전조건"), ("requirement", "요건"))
KNOWLEDGE_SCREEN = 4  # main_window STEPS 인덱스(③ 지식그래프)
# 파일 상태별로 '등록'이 꺼진 이유(R-3)
REGISTER_HINTS = {"none": "파일을 고르면 등록할 수 있습니다", "checking": "파일 확인이 끝나면 등록할 수 있습니다",
                  "many": "파일을 한 개만 고르세요", "error": "파일을 읽을 수 없어 등록할 수 없습니다",
                  "busy": "진행 중인 작업이 끝나면 등록할 수 있습니다"}
JOB_STEPS = {"register": "등록 · 형식 확인·해시·저장", "extract": "선·기호 추출 · 그래프 · 지식그래프",
             "document": "지식 추출 · 지식그래프"}


def material_type_of(rec):
    return rec.get("material_type") or "P&ID"


def page_text(e):
    """목록 '추출' 칸. 여러 쪽 PDF는 추출한 쪽 수와 추출하지 않은 쪽 수를 함께 보인다."""
    pages = e.get("pages") or {}
    if pages.get("total", 0) <= 1:
        return "있음" if e["extracted"] else "없음"
    text = "%d/%d쪽" % (pages["extracted"], pages["total"])
    return text + (" (미추출 %d)" % pages["skipped"] if pages["skipped"] else "")


def one_line(err):
    """작업 실패 문구에서 로그 파일 안내를 뗀 한 줄 원인."""
    return (str(err).split(" (자세한 내용:")[0].splitlines() or ["원인 미상"])[0]


def kg_line(out):
    """추출 결과의 지식그래프 빌드 한 줄(HTML)."""
    if out.get("kg_error"):
        return "<p style='color:%s'>지식그래프를 만들지 못함: %s</p>" % (tokens.c("err-ink"), esc(out["kg_error"]))
    kg = out["kg"]["kg"]
    st = (kg.get("validation") or {}).get("status")
    notes = "".join("<li>%s</li>" % esc(n) for n in out["kg"].get("notes") or [])
    return "<p>지식그래프 %s · 버전 %s · 검증 %s — ③ 지식그래프에서 보기</p>%s" % (
        esc(kg.get("kg_id")), esc(kg.get("kg_version")), esc(VALIDATION_LABELS.get(st, st)),
        "<p>자동 연결·조립 안내</p><ul>%s</ul>" % notes if notes else "")


class DropZone(QFrame):
    """파일 끌어 놓기(1개). 눌러도(Enter·Space 포함) 파일 선택을 연다. 여러 개를 놓으면 아무것도 고르지 않고 안내한다."""

    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(84)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        self.label = QLabel("P&ID 도면(.drawio·벡터 PDF) 또는 설계 문서 PDF 1개를 여기에 끌어 놓거나 <b>눌러서 선택</b>")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)

    def _hover(self, on):
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            self._hover(True)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):  # noqa: N802
        self._hover(False)

    def dropEvent(self, e):  # noqa: N802
        self._hover(False)
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.files_dropped.emit(files)


class JobRow(QFrame):
    """진행 중이거나 실패한 작업 한 줄(U-11). 단계 수는 화면이 아는 작업 경계(등록 → 자동 추출)만 센다.
    data.extract_and_graph·extract_document는 안쪽 진행을 알려 주지 않아 막대는 끝을 모르는 형태이고 남은 시간은 보이지 않는다.
    TaskRunner 작업은 취소할 수 없어 취소 버튼이 없다."""

    def __init__(self, on_retry, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        self.state = QLabel()
        self.name = QLabel()
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(120, 4)
        self.bar.setObjectName("thin")
        self.step = QLabel()
        self.cause = QLabel()
        self.retry_btn = QPushButton("다시 시도")
        self.retry_btn.clicked.connect(on_retry)
        for w in (self.state, self.name, self.bar, self.step, self.cause):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(self.retry_btn)
        self.hide()

    def running(self, name, text):
        self.state.setText("진행")
        self.name.setText(name)
        self.step.setText(text)
        for w, on in ((self.bar, True), (self.step, True), (self.cause, False), (self.retry_btn, False)):
            w.setVisible(on)
        self.show()

    def failed(self, name, cause):
        self.state.setText("<span style='color:%s'><b>! 실패</b></span>" % tokens.c("err-ink"))
        self.name.setText(name)
        self.cause.setText("<span style='color:%s'>%s</span>" % (tokens.c("err-ink"), esc(cause)))
        self.cause.setToolTip(cause)
        for w, on in ((self.bar, False), (self.step, False), (self.cause, True), (self.retry_btn, True)):
            w.setVisible(on)
        self.show()


class RegisterScreen(QWidget):
    title = "① 자료 등록"
    canvas_host = None

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.source_path = None
        self.preview = None
        self._picked = None  # 확인 중이거나 확인한 파일(자료 종류를 바꾸면 다시 확인)
        self._preview_seq = 0  # 파일 확인 요청 번호: 확인 중 다른 파일을 고르면 앞 결과를 버린다
        self.rows = []
        self._file_state = "none"  # "ready" 또는 REGISTER_HINTS 키("busy" 제외)
        self._busy = False  # 이 화면이 시작한 등록·추출 작업이 도는 중
        self._retry = None  # 실패한 작업을 같은 인자로 다시 시작하는 함수
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # 좌측: 등록 자료 목록
        left = QFrame()
        left.setObjectName("panel")
        ll = QVBoxLayout(left)
        t = QLabel("등록 자료")
        t.setObjectName("title")
        ll.addWidget(t)
        self.list_stack = QStackedWidget()
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["자료 ID", "등록 버전", "원본 파일명", "도면번호", "개정번호", "등록 시각",
                                              "상태", "추출", "그래프"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_row)
        self.list_stack.addWidget(self._empty_state())
        self.list_stack.addWidget(self.table)
        self.job = JobRow(self._retry_job)
        ll.addWidget(self.job)
        ll.addWidget(self.list_stack)
        split.addWidget(left)

        # 우측: 등록 폼 + 결과
        right = QFrame()
        right.setObjectName("panel")
        rl = QVBoxLayout(right)
        t2 = QLabel("등록")
        t2.setObjectName("title")
        rl.addWidget(t2)
        form = QFormLayout()
        self.project = QLineEdit("sample-project")
        self.project.setAccessibleName("프로젝트 ID")
        form.addRow("프로젝트 ID", self.project)
        self.material = QComboBox()
        self.material.setAccessibleName("자료 종류")
        for label, mtype, _, _ in MATERIAL_CHOICES:
            self.material.addItem(label, mtype)
        self.material.currentIndexChanged.connect(lambda _: self._repreview())
        form.addRow("자료 종류", self.material)
        rl.addLayout(form)
        self.drop = DropZone()
        self.drop.files_dropped.connect(self.set_files)
        self.drop.clicked.connect(self._pick)
        rl.addWidget(self.drop)
        self.file_info = QLabel("")
        self.file_info.setWordWrap(True)
        self.file_info.setTextFormat(Qt.RichText)
        rl.addWidget(self.file_info)

        meta = QGridLayout()
        self.meta_edits, self.meta_auto, self.meta_btns = {}, {}, {}
        sec = QLabel("식별정보 (비우면 미확인)")
        sec.setObjectName("section")
        meta.addWidget(sec, 0, 0, 1, 4)
        for i, (key, label) in enumerate(META_FIELDS, start=1):
            ed = QLineEdit()
            ed.setPlaceholderText("미확인")
            ed.setAccessibleName(label)
            auto = QLabel("")
            auto.setTextFormat(Qt.RichText)
            btn = QPushButton()
            btn.hide()
            btn.clicked.connect(lambda _=False, k=key: self._confirm_candidate(k))
            meta.addWidget(QLabel(label), i, 0)
            meta.addWidget(ed, i, 1)
            meta.addWidget(btn, i, 2)
            meta.addWidget(auto, i, 3)
            self.meta_edits[key], self.meta_auto[key], self.meta_btns[key] = ed, auto, btn
        rl.addLayout(meta)
        form2 = QFormLayout()
        self.actor = QLineEdit(app.reviewer_name() or getpass.getuser())
        self.actor.setAccessibleName("등록자")
        self.reason = QLineEdit()
        self.reason.setAccessibleName("사유")
        self.reason.setPlaceholderText("확정 사유(식별정보를 입력한 경우)")
        form2.addRow("등록자", self.actor)
        form2.addRow("사유", self.reason)
        rl.addLayout(form2)
        btns = QHBoxLayout()
        self.btn_register = QPushButton("등록")
        self.btn_register.setObjectName("primary")
        self.btn_register.setEnabled(False)
        self.btn_register.clicked.connect(self.do_register)
        self.btn_extract = QPushButton("추출·그래프 만들기")
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(lambda: self.do_extract())
        self.btn_exclude = QPushButton("구간 분석에서 빼기")
        self.btn_exclude.setEnabled(False)
        self.btn_exclude.setToolTip("범례·기호표처럼 공정 흐름이 없는 도면을 ④ 검토구간 제안에서 뺍니다(스크리닝 R0)")
        self.btn_exclude.clicked.connect(lambda: self.toggle_excluded())
        self.register_hint = QLabel()
        self.register_hint.setObjectName("muted")
        btns.addWidget(self.btn_register)
        btns.addWidget(self.btn_extract)
        btns.addWidget(self.btn_exclude)
        btns.addWidget(self.register_hint)
        btns.addStretch(1)
        rl.addLayout(btns)
        self.result = QTextBrowser()
        self.result.setOpenLinks(False)
        self.result.hide()  # 보일 결과가 생기기 전에는 빈 상자를 두지 않는다(R-2)
        rl.addWidget(self.result, 1)
        rl.addStretch(0)
        split.addWidget(right)
        split.setSizes([640, 560])
        self.refresh()

    def _empty_state(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        title = QLabel("등록된 자료가 없습니다")
        title.setObjectName("title")
        why = QLabel("P&ID 도면이나 설계 문서를 등록해야 추출과 HAZOP 분석을 시작할 수 있습니다.")
        why.setObjectName("muted")
        self.empty_pick = QPushButton("파일 선택…")
        self.empty_pick.clicked.connect(self._pick)
        steps = QLabel("1. P&ID 도면(.drawio·벡터 PDF)이나 설계 문서 PDF를 고르거나 오른쪽에 끌어 놓습니다\n"
                       "2. 식별정보를 확인하고 등록합니다\n"
                       "3. PDF는 등록하면 바로 추출해 ② 도면(설계 문서는 ③ 지식그래프)에서 엽니다")
        steps.setObjectName("muted")
        for lab in (title, why, steps):
            lab.setWordWrap(True)
            lab.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(why)
        lay.addWidget(self.empty_pick, alignment=Qt.AlignCenter)
        lay.addWidget(steps)
        lay.addStretch(1)
        return w

    def commands(self):
        """명령 팔레트용 [(이름, 단축키 문구, 함수)]."""
        return [("파일 선택…", "", self._pick), ("등록", "", self.do_register),
                ("추출·그래프 만들기", "", self.do_extract), ("구간 분석에서 빼기·다시 넣기", "", self.toggle_excluded)]

    # ------------------------------------------------------------ 버튼·작업 상태
    def _update_actions(self):
        """주 버튼은 상태마다 하나(R-3): 등록할 파일 → 등록, 고른 등록 자료 → 추출, 빈 목록 → 파일 선택, 그 밖에는 등록."""
        e = self.selected_registration()
        can_register = self._file_state == "ready" and not self._busy
        can_extract = bool(e) and e["record"].get("status") == "registered" and not self._busy
        self.btn_register.setEnabled(can_register)
        self.btn_extract.setEnabled(can_extract)
        excluded = self.is_excluded(e)
        self.btn_exclude.setEnabled(excluded is not None and not self._busy)
        self.btn_exclude.setText("구간 분석에 다시 넣기" if excluded else "구간 분석에서 빼기")
        self.register_hint.setText("" if can_register else REGISTER_HINTS["busy" if self._busy else self._file_state])
        primary = (self.btn_register if can_register else self.btn_extract if can_extract
                   else self.empty_pick if not self.rows else self.btn_register)
        for b in (self.btn_register, self.btn_extract, self.empty_pick):
            name = "primary" if b is primary else ""
            if b.objectName() != name:
                b.setObjectName(name)
                b.style().unpolish(b)
                b.style().polish(b)

    def _show_result(self, html):
        self.result.setHtml(html)
        self.result.show()

    def _job_running(self, name, index, total, step):
        self._busy = True
        text = ("%d/%d " % (index, total) if total > 1 else "") + JOB_STEPS[step]
        self.job.running(name, text)
        self.app.status_message("%s · %s" % (name, text))
        self._update_actions()

    def _job_done(self, message):
        self._busy, self._retry = False, None
        self.job.hide()
        self.app.status_message("")
        self.app.toast(message)
        self._update_actions()

    def _job_failed(self, name, cause, retry):
        self._busy, self._retry = False, retry
        self.job.failed(name, cause)
        self.app.status_message("실패: %s · %s" % (name, cause))
        self._update_actions()

    def _retry_job(self):
        if self._retry and not self._busy:
            self._retry()

    # ------------------------------------------------------------ 목록
    def where(self):
        return None

    def on_enter(self):
        self.refresh()

    def main_focus(self):
        """화면에 들어오면 초점을 둘 곳: 등록 자료 목록(없으면 빈 목록 안내의 파일 선택)."""
        return self.table if self.rows else self.empty_pick

    def is_done(self):
        return bool(self.rows)

    def explorer_items(self):
        return [(e["record"].get("original_name") or e["record"]["material_id"], e["path"]) for e in self.rows]

    def open_item(self, path):
        r = next((i for i, e in enumerate(self.rows) if e["path"] == path), -1)
        if r >= 0:
            self.table.selectRow(r)

    def refresh(self):
        self.rows = data.list_registrations()
        self.table.setRowCount(len(self.rows))
        for r, e in enumerate(self.rows):
            rec = e["record"]
            hist = rec.get("history") or [{}]
            vals = [rec.get("material_id"), rec.get("registration_version"), rec.get("original_name"),
                    data.unknown_text(rec.get("drawing_number")), data.unknown_text(rec.get("design_revision")),
                    hist[0].get("at"), STATUS_LABELS.get(rec.get("status"), rec.get("status")),
                    page_text(e),
                    "해당 없음" if e["graphed"] is None else "있음" if e["graphed"] else "없음"]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
        self.table.resizeColumnsToContents()
        self.list_stack.setCurrentIndex(1 if self.rows else 0)
        self._update_actions()

    @staticmethod
    def is_excluded(entry):
        """도면을 구간 분석에서 뺐으면 True, 넣었으면 False. 표시할 수 없으면(도면 아님·도면번호 없음·파일 오류) None."""
        rec = (entry or {}).get("record") or {}
        if not (rec.get("drawing_number") or "").strip() or material_type_of(rec) != "P&ID":
            return None
        try:
            return sn.excluded_mark(rec.get("project_id"), rec["drawing_number"]) is not None
        except (OSError, ValueError):
            return None

    @staticmethod
    def excluded_mark(rec):
        """(표시 기록 또는 None, 읽기 문제 글 또는 None)."""
        try:
            return sn.excluded_mark(rec.get("project_id"), rec.get("drawing_number")), None
        except (OSError, ValueError) as exc:
            return None, "구간 분석에서 뺀 도면 표시를 읽지 못함(%s)" % exc

    def toggle_excluded(self):
        """고른 도면을 구간 분석에서 빼거나 다시 넣는다. 사유는 '사유' 칸, 표시한 사람은 '등록자' 칸에서 읽는다."""
        e = self.selected_registration()
        excluded = self.is_excluded(e)
        if excluded is None:
            problem = self.excluded_mark(e["record"])[1] if e else None
            self.app.status_message(problem or "도면번호를 확정한 P&ID 도면만 구간 분석에서 뺄 수 있습니다")
            return False
        rec = e["record"]
        try:
            sn.set_excluded(rec.get("project_id"), rec["drawing_number"], not excluded, self.actor.text(),
                            self.reason.text())
        except (OSError, ValueError) as exc:
            self.app.log_error("구간 분석 표시", exc)
            self.app.toast("구간 분석 표시를 바꾸지 못했습니다: %s" % exc)
            return False
        self.app.toast("%s 도면을 구간 분석에서 %s. ④에서 다시 제안하면 반영됩니다"
                       % (rec["drawing_number"], "다시 넣었습니다" if excluded else "뺐습니다"))
        self._update_actions()
        self.show_record(rec, None, e["path"])
        return True

    def selected_registration(self):
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _on_row(self):
        e = self.selected_registration()
        self.btn_extract.setText(EXTRACT_LABELS[material_type_of(e["record"]) if e else "P&ID"])
        self._update_actions()
        if e:
            self.show_record(e["record"], None, e["path"])

    # ------------------------------------------------------------ 파일 선택·미리보기
    def material_type(self):
        return self.material.currentData()

    def _pick(self):
        label, _, filters, _ = MATERIAL_CHOICES[self.material.currentIndex()]
        path, _ = QFileDialog.getOpenFileName(self, "%s 선택" % label, paths.resource_root(), filters + ";;모든 파일 (*)")
        if path:
            self.set_files([path])

    def _repreview(self):
        """자료 종류를 바꾸면 고른 파일을 그 종류로 다시 확인한다."""
        if self._picked:
            self.set_files([self._picked])

    def set_files(self, files):
        """여러 개를 놓으면 '한 개씩 등록'을 안내하고 아무것도 등록하지 않는다(§3.1).
        파일 확인(PDF는 도면 분석 포함)은 작업 스레드(app.tasks)에서 하고 끝나면 _show_preview가 표시한다.
        확인을 시작했으면 True. 등록 버튼은 확인이 끝나야 켜진다."""
        self.source_path, self.preview, self._picked = None, None, None
        self._preview_seq += 1
        for k in self.meta_auto:
            self.meta_auto[k].setText("")
            self.meta_btns[k].hide()
        if len(files) != 1:
            self.file_info.setText("<span style='color:%s'><b>한 개씩 등록하세요.</b> 놓은 파일 %d개 — 아무것도 등록하지 않음</span>"
                                   % (tokens.c("err-ink"), len(files)))
            self._set_file_state("many")
            return False
        path = files[0]
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            self.file_info.setText("<span style='color:%s'>파일을 읽을 수 없음: %s</span>" % (tokens.c("err-ink"), esc(exc)))
            self._set_file_state("error")
            return False
        self._picked = path
        self._set_file_state("checking")
        seq, mtype = self._preview_seq, self.material_type()
        self.file_info.setText("<b>%s</b> · 파일 확인 중…" % esc(os.path.basename(path)))
        self.app.tasks.run("파일 확인", lambda: fileinfo.inspect(path, raw, mtype),
                           lambda info: self._show_preview(seq, path, mtype, info),
                           lambda err: self._preview_failed(seq, err))
        return True

    def _clear_file(self):
        self.source_path, self.preview, self._picked = None, None, None
        self._preview_seq += 1
        self.file_info.setText("")
        for key, _ in META_FIELDS:
            self.meta_edits[key].clear()
            self.meta_auto[key].setText("")
            self.meta_btns[key].hide()
        self.reason.clear()
        self._set_file_state("none")

    def _set_file_state(self, state):
        self._file_state = state
        self._update_actions()

    def _preview_failed(self, seq, err):
        if seq == self._preview_seq:
            self.file_info.setText("<span style='color:%s'>파일을 읽을 수 없음: %s</span>" % (tokens.c("err-ink"), esc(err)))
            self._set_file_state("error")

    def _show_preview(self, seq, path, mtype, info):
        if seq != self._preview_seq:  # 확인 중에 다른 파일·자료 종류를 골랐다
            return
        self.source_path, self.preview = path, info
        parts = ["<b>%s</b> · 형식 %s · %d바이트" % (esc(os.path.basename(path)), esc(info.get("format")),
                                                 info.get("size_bytes") or 0)]
        for b in info.get("blockers") or []:
            parts.append("<span style='color:%s'>문제: %s %s</span>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("reason"))))
        pages = info.get("pages") or []
        svg = None
        if mtype == "design_document":
            parts.append("설계 문서 PDF %d쪽 · 등록하면 설정치·운전조건·요건을 자동 추출해 ③ 지식그래프에 추가"
                         "(자동 추출 · 사람 확인 전)" % len(pages))
        elif info.get("format") == "pdf":
            parts.append("PDF %d쪽 · 등록하면 모든 쪽을 자동 추출해 ② 도면에 표시(도면은 PDF에서 그림)" % len(pages))
        elif pages:
            svg = svg_align.find_svg(path, 0, pages[0].get("page_name"), len(pages))
        if svg:
            parts.append("SVG 함께 등록(파생 자료): %s" % esc(os.path.basename(svg)))
        elif info.get("format") != "pdf":
            parts.append("<span style='color:%s'>경고: 같은 이름의 SVG 없음 — 도면 오버레이를 만들 수 없음(그래프 보기만 가능)</span>" % tokens.c("warn-ink"))
        self.file_info.setText("<br>".join(parts))
        for key, _ in META_FIELDS:
            cand = (info.get("auto_candidates") or {}).get(key)
            if cand:
                value = str(cand.get("value"))
                self.meta_auto[key].setText("%s %s" % (badge("자동 후보", "ai"), esc(value)))
                short = value if len(value) <= 16 else value[:15] + "…"
                self.meta_btns[key].setText("후보 '%s' 쓰기" % short.replace("&", "&&"))
                self.meta_btns[key].setToolTip(value)
                self.meta_btns[key].show()
            else:
                self.meta_auto[key].setText("<span style='color:%s'>자동 후보 없음</span>" % tokens.c("muted"))
        self._set_file_state("ready")

    def _confirm_candidate(self, key):
        cand = ((self.preview or {}).get("auto_candidates") or {}).get(key)
        if cand:
            self.meta_edits[key].setText(cand["value"])

    def metadata(self):
        meta = {k: self.meta_edits[k].text().strip() for k, _ in META_FIELDS if self.meta_edits[k].text().strip()}
        if meta:
            meta["by"] = self.actor.text().strip() or None
            if self.reason.text().strip():
                meta["reason"] = self.reason.text().strip()
            meta = {k: v for k, v in meta.items() if v}
        return meta or None

    # ------------------------------------------------------------ 등록·추출
    def do_register(self):
        if self._file_state != "ready" or self._busy:
            return
        path, project, meta, actor = self.source_path, self.project.text().strip(), self.metadata(), \
            self.actor.text().strip() or None
        mtype, name = self.material_type(), os.path.basename(self.source_path)
        total = 2 if (self.preview or {}).get("format") == "pdf" else 1  # PDF는 등록 뒤 추출이 이어진다

        def start():
            self._job_running(name, 1, total, "register")
            self.app.tasks.run("등록", lambda: registry.register(path, project, mtype, paths.store_root(), meta, actor),
                               lambda result: self._registered(result, total, start),
                               lambda err: self._failed(name, err, start))
        start()

    def _registered(self, result, total=1, retry=None):
        self.refresh()
        rec = result["record"]
        for r, e in enumerate(self.rows):
            if e["record"].get("material_id") == rec.get("material_id") and \
                    e["record"].get("project_id") == rec.get("project_id"):
                self.table.selectRow(r)
        self.show_record(rec, result, result.get("registration_file"))
        name = rec.get("original_name") or rec.get("material_id")
        outcome = OUTCOME_LABELS.get(result["outcome"], result["outcome"])
        if rec.get("status") != "registered" or result["outcome"] in ("failed", "on_hold"):
            blockers = (rec.get("validation") or {}).get("blockers") or []
            cause = (blockers[0].get("reason") if blockers else None) or next(iter(result.get("notes") or []), None)
            self._job_failed(name, "%s: %s" % (outcome, cause) if cause else outcome, retry)
            return
        self._clear_file()  # 등록을 마친 파일은 내려놓아 다음 주 동작(추출)이 주 버튼이 되게 한다
        if rec.get("format") == "pdf" and result.get("registration_file"):
            self.do_extract(result["registration_file"], auto=True, material_type=material_type_of(rec),
                            name=name, step=(2, total))
        else:
            self._job_done("%s · %s" % (outcome, name))

    def _failed(self, name, err, retry):
        self._show_result("<p style='color:%s'><b>실패 — 완료로 표시하지 않음</b></p><p>%s</p>"
                          % (tokens.c("err-ink"), esc(err)))
        self._job_failed(name, one_line(err), retry)

    def show_record(self, rec, result, path):
        h = []
        if result is not None:
            ok = rec.get("status") == "registered" and result["outcome"] not in ("failed", "on_hold")
            h.append("<p style='color:%s'><b>%s</b></p>" % (tokens.c("ok") if ok else tokens.c("err-ink"),
                                                             esc(OUTCOME_LABELS.get(result["outcome"], result["outcome"]))))
            h += ["<p>안내: %s</p>" % esc(n) for n in result.get("notes") or []]
            if ok:
                h.append("<p>단계: 형식 확인 ✓ → 해시 ✓ → 저장 ✓ → 저장 후 해시 확인 ✓</p>")
        h.append("<p>자료 ID <b>%s</b> · 버전 %s · 상태 %s<br>등록정보: %s</p>" % (
            esc(rec.get("material_id")), esc(rec.get("registration_version")),
            esc(STATUS_LABELS.get(rec.get("status"), rec.get("status"))), esc(path and registry._display_path(path))))
        rows = []
        for key, label in META_FIELDS:
            v = rec.get(key)
            cand = (rec.get("auto_candidates") or {}).get(key)
            val = ("%s %s" % (badge("확정", "human"), esc(v))) if v else "<span style='color:%s'>미확인</span>" % tokens.c("warn-ink")
            if cand:
                val += " &nbsp; %s %s" % (badge("자동 후보", "ai"), esc(cand.get("value")))
            rows.append("<tr><td style='color:%s'>%s</td><td>%s</td></tr>" % (tokens.c("muted"), label, val))
        h.append("<table cellpadding='3'>%s</table>" % "".join(rows))
        mark, problem = self.excluded_mark(rec)
        if problem:
            h.append("<p style='color:%s'>구간 분석: %s</p>" % (tokens.c("err-ink"), esc(problem)))
        elif mark:
            h.append("<p>구간 분석: %s %s (%s)</p>" % (badge("뺌", "human"), esc(mark.get("reason")), esc(mark.get("by"))))
        elif self.is_excluded({"record": rec}) is False and sn.looks_like_legend(rec.get("original_name"), rec.get("title")):
            h.append("<p>구간 분석: %s 범례·기호표 도면으로 보입니다. 공정 흐름이 없으면 '구간 분석에서 빼기'를 누르세요.</p>"
                     % badge("제안", "ai"))
        derived = rec.get("derived_files") or []
        for d in derived:
            h.append("<p>SVG 파생 등록: %s (sha256 %s…)</p>" % (esc(d.get("storage_ref")), esc((d.get("sha256") or "")[:12])))
        val = rec.get("validation") or {}
        for b in val.get("blockers") or []:
            h.append("<p style='color:%s'>문제: %s — %s</p>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("reason"))))
        unk = val.get("unknowns") or []
        if unk:
            h.append("<p><b>미확인 (validation.unknowns)</b></p><ul>%s</ul>" % "".join(
                "<li>%s: %s</li>" % (esc(u.get("field")), esc(u.get("reason"))) for u in unk))
        self._show_result("".join(h))

    def do_extract(self, registration_path=None, auto=False, material_type=None, name=None, step=(1, 1)):
        """auto: PDF 등록 직후 자동 실행. 끝나면 P&ID는 ② 도면 화면으로 옮겨 이 도면을 열고, 설계 문서는 ③으로 옮긴다.
        name·step: 작업 행에 보일 자료 이름과 (몇 번째 단계, 전체 단계 수)."""
        if not registration_path:
            e = self.selected_registration()
            if not e or self._busy or e["record"].get("status") != "registered":
                return
            registration_path, material_type = e["path"], material_type_of(e["record"])
            name = e["record"].get("original_name") or e["record"].get("material_id")
        name = name or os.path.basename(registration_path)
        doc = material_type == "design_document"

        def start():
            self._job_running(name, step[0], step[1], "document" if doc else "extract")
            if doc:
                self.app.tasks.run("지식 추출", lambda: data.extract_document(registration_path),
                                   lambda out: self._document_extracted(out, auto, name),
                                   lambda err: self._failed(name, err, start))
            else:
                self.app.tasks.run("추출·그래프", lambda: data.extract_and_graph(registration_path),
                                   lambda out: self._extracted(out, auto, name),
                                   lambda err: self._failed(name, err, start))
        start()

    def _extracted(self, out, auto=False, name=""):
        ex, g = out["extraction"], out["graph"]
        s = ex["summary"]
        al = ex["coordinate_system"].get("svg_alignment") or {}
        st = g["validation"]["status"]
        h = ["<p style='color:%s'><b>추출·그래프 생성 %s</b></p>" % (tokens.c("ok") if st == "passed" else tokens.c("err-ink"),
                                                              "완료" if st == "passed" else "— 구조 검증 차단(%s)" % esc(st)),
             "<p>추출 검증: %s · 노드 %d · 관계 %d · 미해결 %d · 미확인 %d<br>%s</p>" % (
                 esc(VALIDATION_LABELS.get(ex["validation"]["status"], ex["validation"]["status"])), s["nodes"], s["relations"], s["unresolved_connectors"], s["unknowns"],
                 esc(paths.plain_rel(out["extract_dir"], paths.work_root()))),
             "<p>SVG 대응: %s (출처: %s)</p>" % (esc({"verified": "확인됨"}.get(al.get("status"), al.get("status") or "SVG 없음")), esc({"registered_derived": "등록된 파생 SVG", "input_path_sibling, unregistered": "원본 옆 SVG(미등록)", "rendered_from_pdf": "PDF에서 그린 도면(같은 좌표, 기호 %s/%s개 bbox 일치)" % (al.get("consistent_cells"), al.get("compared_cells"))}.get(al.get("source"), al.get("source") or "없음"))),
             "<p>그래프 %s · 버전 %s · 노드 %d · 관계 %d<br>%s</p>" % (
                 esc(g["graph_id"]), esc(g["graph_version"]), g["structure"]["node_count"], g["structure"]["edge_count"],
                 esc(paths.plain_rel(out["graph_dir"], paths.work_root())))]
        for b in g["validation"].get("blockers") or []:
            h.append("<p style='color:%s'>차단: %s %s</p>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("target"))))
        if not al:
            h.append("<p style='color:%s'>경고: SVG 없음 — 도면 오버레이를 만들 수 없음(그래프 보기만 가능)</p>" % tokens.c("warn-ink"))
        if len(out.get("pages") or []) > 1 or out.get("skipped_pages"):
            h.append("<p>쪽별 추출: %s</p>" % " · ".join(
                "%d쪽 노드 %d · 관계 %d" % (p["page_index"] + 1, p["extraction"]["summary"]["nodes"],
                                          p["extraction"]["summary"]["relations"]) for p in out["pages"]))
        for sk in out.get("skipped_pages") or []:
            h.append("<p style='color:%s'>%d쪽 추출 안 함: %s</p>" % (tokens.c("warn-ink"), sk["page_index"] + 1,
                                                                 esc(sk["reason"])))
        h.append(kg_line(out))
        self._show_result("".join(h))
        self.refresh()
        self._job_done("추출·그래프를 만들었습니다 · %s" % name)
        if auto or self.app.current_screen() is self:  # 다음에 여는 ②④⑤는 방금 추출한 도면(다른 도면을 보는 중이면 그대로)
            self.app.set_drawing(os.path.basename(out["extract_dir"]))
        if auto:
            self.app.go(1)

    def _document_extracted(self, out, auto=False, name=""):
        doc = out["document"]
        s, v = doc["summary"], doc["validation"]
        ok = v["status"] == "passed"
        h = ["<p style='color:%s'><b>설계 문서 지식 추출 %s</b></p>" % (tokens.c("ok") if ok else tokens.c("err-ink"),
                                                                "완료" if ok else "— 차단"),
             "<p>%s %s · 쪽 %s</p>" % (badge("자동 추출 · 사람 확인 전", "ai"),
                                      " · ".join("%s %d" % (label, s.get(k, 0)) for k, label in DOC_COUNT_LABELS),
                                      esc(doc.get("page_count"))),
             "<p>%s</p>" % esc(paths.plain_rel(out["path"], paths.work_root()))]
        for b in v.get("blockers") or []:
            h.append("<p style='color:%s'>차단: %s — %s</p>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("reason"))))
        h.append(kg_line(out))
        self._show_result("".join(h))
        self.refresh()
        self._job_done("설계 문서 지식을 추출했습니다 · %s" % name)
        if auto:
            self.app.go(KNOWLEDGE_SCREEN)
