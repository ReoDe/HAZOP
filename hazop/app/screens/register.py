"""① 자료 등록 (기획서/인터페이스.md §3.1). 등록·추출·그래프는 기존 함수(registry.register,
scripts/extract_drawio.run_one, scripts/build_graph.build_one)를 그대로 호출한다."""

import getpass
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
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


class DropZone(QFrame):
    """파일 끌어 놓기(1개). 여러 개를 놓으면 아무것도 고르지 않고 안내한다."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(84)
        lay = QVBoxLayout(self)
        self.label = QLabel("draw.io 원본 파일(.drawio) 1개를 여기에 끌어 놓거나 '파일 선택'을 누르세요")
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
        self.list_stack.addWidget(empty_label("등록된 자료가 없습니다. 오른쪽에 draw.io 원본을 놓아 등록하세요."))
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
        self.btn_extract.clicked.connect(self.do_extract)
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
                    "있음" if e["extracted"] else "없음", "있음" if e["graphed"] else "없음"]
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
        if e:
            self.show_record(e["record"], None, e["path"])

    # ------------------------------------------------------------ 파일 선택·미리보기
    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "draw.io 원본 선택", paths.resource_root(),
                                              "draw.io (*.drawio *.xml);;모든 파일 (*)")
        if path:
            self.set_files([path])

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
            info = fileinfo.inspect(path, raw)
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
        if pages:
            svg = svg_align.find_svg(path, 0, pages[0].get("page_name"), len(pages))
        if svg:
            parts.append("SVG 함께 등록(파생 자료): %s" % esc(os.path.basename(svg)))
        else:
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
        self.result.setHtml("<p>등록 중: 형식 확인 → 해시 → 저장 → 저장 후 해시 확인</p>")
        self.btn_register.setEnabled(False)
        self.app.tasks.run("등록", lambda: registry.register(path, project, "P&ID", paths.store_root(), meta, actor),
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

    def do_extract(self):
        e = self.selected_registration()
        if not e:
            return
        self.btn_extract.setEnabled(False)
        self.result.setHtml("<p>추출 → 그래프 생성 중…</p>")
        self.app.tasks.run("추출·그래프", lambda: data.extract_and_graph(e["path"]), self._extracted, self._failed)

    def _extracted(self, out):
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
             "<p>SVG 대응: %s (출처: %s)</p>" % (esc({"verified": "확인됨"}.get(al.get("status"), al.get("status") or "SVG 없음")), esc({"registered_derived": "등록된 파생 SVG", "input_path_sibling, unregistered": "원본 옆 SVG(미등록)"}.get(al.get("source"), al.get("source") or "없음"))),
             "<p>그래프 %s · 버전 %s · 노드 %d · 관계 %d<br>%s</p>" % (
                 esc(g["graph_id"]), esc(g["graph_version"]), g["structure"]["node_count"], g["structure"]["edge_count"],
                 esc(paths.rel_or_abs(out["graph_dir"], paths.work_root())))]
        for b in g["validation"].get("blockers") or []:
            h.append("<p style='color:%s'>차단: %s %s</p>" % (tokens.c("err-ink"), esc(b.get("check")), esc(b.get("target"))))
        if not al:
            h.append("<p style='color:%s'>경고: SVG 없음 — 도면 오버레이를 만들 수 없음(그래프 보기만 가능)</p>" % tokens.c("warn-ink"))
        self.result.setHtml("".join(h))
        self.refresh()
