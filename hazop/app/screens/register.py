"""① 자료 등록 (기획서/인터페이스.md §3.1). 등록·추출·그래프는 기존 함수(registry.register,
scripts/extract_drawio.run_one 또는 scripts/extract_pdf.run_one, scripts/build_graph.build_one)를 그대로 호출한다.
PDF는 등록이 끝나면 추출까지 자동으로 이어 하고 ② 도면 화면으로 옮긴다(drawio는 '추출·그래프 만들기' 버튼 그대로).
설계 문서(PDF)는 등록이 끝나면 지식 추출(data.extract_document)을 자동으로 하고 ③ 지식그래프로 옮긴다.
추출이 끝나면 프로젝트 지식그래프를 다시 빌드한다(data.build_project_kg)."""

import getpass
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QTextBrowser, QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import data, tokens
from hazop.app.widgets import VALIDATION_LABELS, badge, esc, empty_label
from hazop.extract import svg_align
from hazop.register import fileinfo, registry

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


def material_type_of(rec):
    return rec.get("material_type") or "P&ID"


def kg_line(out):
    """추출 결과의 지식그래프 빌드 한 줄(HTML)."""
    if out.get("kg_error"):
        return "<p style='color:%s'>지식그래프를 만들지 못함: %s</p>" % (tokens.c("err-ink"), esc(out["kg_error"]))
    kg = out["kg"]["kg"]
    st = (kg.get("validation") or {}).get("status")
    return "<p>지식그래프 %s · 버전 %s · 검증 %s — ③ 지식그래프에서 보기</p>" % (
        esc(kg.get("kg_id")), esc(kg.get("kg_version")), esc(VALIDATION_LABELS.get(st, st)))


class DropZone(QFrame):
    """파일 끌어 놓기(1개). 여러 개를 놓으면 아무것도 고르지 않고 안내한다."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(84)
        lay = QVBoxLayout(self)
        self.label = QLabel("P&ID 도면(.drawio·벡터 PDF) 또는 설계 문서 PDF 1개를 여기에 끌어 놓거나 '파일 선택'을 누르세요")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)

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


class RegisterScreen(QWidget):
    title = "① 자료 등록"
    canvas_host = None

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.source_path = None
        self.preview = None
        self.rows = []
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
        self.list_stack.addWidget(empty_label("등록된 자료가 없습니다. 오른쪽에 P&ID 도면(draw.io·벡터 PDF) 또는 "
                                              "설계 문서 PDF를 놓아 등록하세요."))
        self.list_stack.addWidget(self.table)
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
        form.addRow("프로젝트 ID", self.project)
        self.material = QComboBox()
        for label, mtype, _, _ in MATERIAL_CHOICES:
            self.material.addItem(label, mtype)
        self.material.currentIndexChanged.connect(lambda _: self._repreview())
        form.addRow("자료 종류", self.material)
        rl.addLayout(form)
        self.drop = DropZone()
        self.drop.files_dropped.connect(self.set_files)
        rl.addWidget(self.drop)
        pick = QPushButton("파일 선택")
        pick.clicked.connect(self._pick)
        rl.addWidget(pick, alignment=Qt.AlignLeft)
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
            auto = QLabel("")
            auto.setTextFormat(Qt.RichText)
            btn = QPushButton("후보 확정")
            btn.setEnabled(False)
            btn.clicked.connect(lambda _=False, k=key: self._confirm_candidate(k))
            meta.addWidget(QLabel(label), i, 0)
            meta.addWidget(ed, i, 1)
            meta.addWidget(btn, i, 2)
            meta.addWidget(auto, i, 3)
            self.meta_edits[key], self.meta_auto[key], self.meta_btns[key] = ed, auto, btn
        rl.addLayout(meta)
        form2 = QFormLayout()
        self.actor = QLineEdit(app.reviewer_name() or getpass.getuser())
        self.reason = QLineEdit()
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
        btns.addWidget(self.btn_register)
        btns.addWidget(self.btn_extract)
        btns.addStretch(1)
        rl.addLayout(btns)
        self.result = QTextBrowser()
        self.result.setOpenLinks(False)
        rl.addWidget(self.result, 1)
        split.addWidget(right)
        split.setSizes([640, 560])
        self.refresh()

    # ------------------------------------------------------------ 목록
    def where(self):
        return None

    def on_enter(self):
        self.refresh()

    def refresh(self):
        self.rows = data.list_registrations()
        self.table.setRowCount(len(self.rows))
        for r, e in enumerate(self.rows):
            rec = e["record"]
            hist = rec.get("history") or [{}]
            vals = [rec.get("material_id"), rec.get("registration_version"), rec.get("original_name"),
                    data.unknown_text(rec.get("drawing_number")), data.unknown_text(rec.get("design_revision")),
                    hist[0].get("at"), STATUS_LABELS.get(rec.get("status"), rec.get("status")),
                    "있음" if e["extracted"] else "없음",
                    "해당 없음" if e["graphed"] is None else "있음" if e["graphed"] else "없음"]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
        self.table.resizeColumnsToContents()
        self.list_stack.setCurrentIndex(1 if self.rows else 0)

    def selected_registration(self):
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _on_row(self):
        e = self.selected_registration()
        self.btn_extract.setEnabled(bool(e) and e["record"].get("status") == "registered")
        self.btn_extract.setText(EXTRACT_LABELS[material_type_of(e["record"]) if e else "P&ID"])
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
        if self.source_path:
            self.set_files([self.source_path])

    def set_files(self, files):
        """여러 개를 놓으면 '한 개씩 등록'을 안내하고 아무것도 등록하지 않는다(§3.1)."""
        self.source_path, self.preview = None, None
        self.btn_register.setEnabled(False)
        for k in self.meta_auto:
            self.meta_auto[k].setText("")
            self.meta_btns[k].setEnabled(False)
        if len(files) != 1:
            self.file_info.setText("<span style='color:%s'><b>한 개씩 등록하세요.</b> 놓은 파일 %d개 — 아무것도 등록하지 않음</span>"
                                   % (tokens.c("err-ink"), len(files)))
            return False
        path = files[0]
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            info = fileinfo.inspect(path, raw, self.material_type())
        except (OSError, ValueError) as exc:
            self.file_info.setText("<span style='color:%s'>파일을 읽을 수 없음: %s</span>" % (tokens.c("err-ink"), esc(exc)))
            return False
        self.source_path, self.preview = path, info
        parts = ["<b>%s</b> · 형식 %s · %d바이트" % (esc(os.path.basename(path)), esc(info.get("format")),
                                                 info.get("size_bytes") or 0)]
        for b in info.get("blockers") or []:
            parts.append("<span style='color:%s'>문제: %s %s</span>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("reason"))))
        pages = info.get("pages") or []
        svg = None
        if self.material_type() == "design_document":
            parts.append("설계 문서 PDF %d쪽 · 등록하면 설정치·운전조건·요건을 자동 추출해 ③ 지식그래프에 추가"
                         "(자동 추출 · 사람 확인 전)" % len(pages))
        elif info.get("format") == "pdf":
            parts.append("PDF %d쪽 · 등록하면 첫 쪽을 자동 추출해 ② 도면에 표시(도면은 PDF에서 그림)" % len(pages))
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
                self.meta_auto[key].setText("%s %s" % (badge("자동 후보", "ai"), esc(cand.get("value"))))
                self.meta_btns[key].setEnabled(True)
            else:
                self.meta_auto[key].setText("<span style='color:%s'>자동 후보 없음</span>" % tokens.c("muted"))
        self.btn_register.setEnabled(True)
        return True

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
        if not self.source_path:
            return
        path, project, meta, actor = self.source_path, self.project.text().strip(), self.metadata(), \
            self.actor.text().strip() or None
        mtype = self.material_type()
        self.result.setHtml("<p>등록 중: 형식 확인 → 해시 → 저장 → 저장 후 해시 확인</p>")
        self.btn_register.setEnabled(False)
        self.app.tasks.run("등록", lambda: registry.register(path, project, mtype, paths.store_root(), meta, actor),
                           self._registered, self._failed)

    def _registered(self, result):
        self.btn_register.setEnabled(bool(self.source_path))
        self.refresh()
        rec = result["record"]
        for r, e in enumerate(self.rows):
            if e["record"].get("material_id") == rec.get("material_id") and \
                    e["record"].get("project_id") == rec.get("project_id"):
                self.table.selectRow(r)
        self.show_record(rec, result, result.get("registration_file"))
        if rec.get("format") == "pdf" and rec.get("status") == "registered" and \
                result["outcome"] not in ("failed", "on_hold") and result.get("registration_file"):
            self.do_extract(result["registration_file"], auto=True, material_type=material_type_of(rec))

    def _failed(self, err):
        self.btn_register.setEnabled(bool(self.source_path))
        self.btn_extract.setEnabled(self.selected_registration() is not None)
        self.result.setHtml("<p style='color:%s'><b>실패 — 완료로 표시하지 않음</b></p><p>%s</p>" % (tokens.c("err-ink"), esc(err)))

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
        self.result.setHtml("".join(h))

    def do_extract(self, registration_path=None, auto=False, material_type=None):
        """auto: PDF 등록 직후 자동 실행. 끝나면 P&ID는 ② 도면 화면으로 옮겨 이 도면을 열고, 설계 문서는 ③으로 옮긴다."""
        if not registration_path:
            e = self.selected_registration()
            if not e:
                return
            registration_path, material_type = e["path"], material_type_of(e["record"])
        self.btn_extract.setEnabled(False)
        if material_type == "design_document":
            self.result.setHtml("<p>설계 문서 지식 추출 → 지식그래프 빌드 중…</p>")
            self.app.tasks.run("지식 추출", lambda: data.extract_document(registration_path),
                               lambda out: self._document_extracted(out, auto), self._failed)
            return
        self.result.setHtml("<p>추출 → 그래프 생성 중…</p>")
        self.app.tasks.run("추출·그래프", lambda: data.extract_and_graph(registration_path),
                           lambda out: self._extracted(out, auto), self._failed)

    def _extracted(self, out, auto=False):
        self.btn_extract.setEnabled(True)
        ex, g = out["extraction"], out["graph"]
        s = ex["summary"]
        al = ex["coordinate_system"].get("svg_alignment") or {}
        st = g["validation"]["status"]
        h = ["<p style='color:%s'><b>추출·그래프 생성 %s</b></p>" % (tokens.c("ok") if st == "passed" else tokens.c("err-ink"),
                                                              "완료" if st == "passed" else "— 구조 검증 차단(%s)" % esc(st)),
             "<p>추출 검증: %s · 노드 %d · 관계 %d · 미해결 %d · 미확인 %d<br>%s</p>" % (
                 esc(VALIDATION_LABELS.get(ex["validation"]["status"], ex["validation"]["status"])), s["nodes"], s["relations"], s["unresolved_connectors"], s["unknowns"],
                 esc(paths.rel_or_abs(out["extract_dir"], paths.work_root()))),
             "<p>SVG 대응: %s (출처: %s)</p>" % (esc({"verified": "확인됨"}.get(al.get("status"), al.get("status") or "SVG 없음")), esc({"registered_derived": "등록된 파생 SVG", "input_path_sibling, unregistered": "원본 옆 SVG(미등록)", "rendered_from_pdf": "PDF에서 그린 도면(같은 좌표, 셀 비교 없음)"}.get(al.get("source"), al.get("source") or "없음"))),
             "<p>그래프 %s · 버전 %s · 노드 %d · 관계 %d<br>%s</p>" % (
                 esc(g["graph_id"]), esc(g["graph_version"]), g["structure"]["node_count"], g["structure"]["edge_count"],
                 esc(paths.rel_or_abs(out["graph_dir"], paths.work_root())))]
        for b in g["validation"].get("blockers") or []:
            h.append("<p style='color:%s'>차단: %s %s</p>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("target"))))
        if not al:
            h.append("<p style='color:%s'>경고: SVG 없음 — 도면 오버레이를 만들 수 없음(그래프 보기만 가능)</p>" % tokens.c("warn-ink"))
        h.append(kg_line(out))
        self.result.setHtml("".join(h))
        self.refresh()
        if auto:
            self.app.go(1)
            self.app.screens[1].select_drawing(os.path.basename(out["extract_dir"]))

    def _document_extracted(self, out, auto=False):
        self.btn_extract.setEnabled(True)
        doc = out["document"]
        s, v = doc["summary"], doc["validation"]
        ok = v["status"] == "passed"
        h = ["<p style='color:%s'><b>설계 문서 지식 추출 %s</b></p>" % (tokens.c("ok") if ok else tokens.c("err-ink"),
                                                                "완료" if ok else "— 차단"),
             "<p>%s %s · 쪽 %s</p>" % (badge("자동 추출 · 사람 확인 전", "ai"),
                                      " · ".join("%s %d" % (label, s.get(k, 0)) for k, label in DOC_COUNT_LABELS),
                                      esc(doc.get("page_count"))),
             "<p>%s</p>" % esc(paths.rel_or_abs(out["path"], paths.work_root()))]
        for b in v.get("blockers") or []:
            h.append("<p style='color:%s'>차단: %s — %s</p>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("reason"))))
        h.append(kg_line(out))
        self.result.setHtml("".join(h))
        self.refresh()
        if auto:
            self.app.go(KNOWLEDGE_SCREEN)
