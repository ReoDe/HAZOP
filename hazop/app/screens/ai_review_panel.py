"""① 등록 화면의 'AI 검토' 토글·진행 줄과 AI 후보 확정 창(INTENT.md §3.2, docs/specs/extraction.md '읽기 품질 지표').

- AiReviewBar: 추출 전 토글(기본 꺼짐), 도면당 호출 상한, 대상 쪽, 예상 호출 수·시간, 진행 줄과 멈추기 단추.
  구독(또는 고른 AI 연결)을 쓸 수 없으면 토글 대신 안내만 보인다(docs/specs/chat-panel.md §8과 같은 문구 방식).
- AI 검토는 TaskRunner(스레드 1개)를 오래 막지 않도록 따로 스레드에서 돈다. 진행은 Qt 신호로 UI 스레드에 넘긴다.
- AiReviewDialog: 후보를 필드별로 보고, 확신 높은 것은 필드별로 묶어 수락, 낮은 것은 '도면에서 보기'로 보고 하나씩
  수락·거절, 수락·거절을 되돌리기. 수락은 사람 수정 기록에 연산으로 들어간다(hazop.extract.ai_review.accept).
"""

import getpass
import json
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from hazop import paths
from hazop.extract import ai_review

FIELD_LABELS = {"kind": "기호 종류", "tag": "태그·번호", "normal_position": "정상 위치", "fail_position": "고장 위치",
                "connection": "끊긴 연결", "to_system": "도면 밖 연결 계통"}
STATUS_LABELS = {"proposed": "후보", "accepted": "수락함", "rejected": "거절함"}
TARGET_PAGES = (("all", "추출한 모든 쪽"), ("first", "첫 쪽만"))
TYPICAL_CALLS = 9  # 143쪽 실측 중앙값(b=20, 규격 'AI 검토 호출 수')
# 안내 문구(채팅 창 규격 §8과 같은 방식). 키는 conn_state
UNAVAILABLE = {
    "not_installed": "이 PC에 Claude Code가 없습니다. AI 검토는 Claude 구독(Pro·Max 등)과 Claude Code 설치가 있어야 씁니다. "
                     "추출은 스크립트만으로 그대로 됩니다.",
    "cli_unsupported": "이 PC에 쓸 수 있는 Claude Code가 없습니다. AI 검토는 Claude 구독과 Claude Code(네이티브 설치)가 "
                       "있어야 씁니다. 추출은 스크립트만으로 그대로 됩니다.",
    "login_required": "Claude Code에 로그인하지 않았습니다. 로그인하면 AI 검토를 켤 수 있습니다. 추출은 스크립트만으로 됩니다.",
    "limit_reached": "구독 사용 한도에 닿았습니다. 재설정 뒤 AI 검토를 켤 수 있습니다. 추출은 스크립트만으로 됩니다.",
}


def unavailable_text(state, detail=""):
    return UNAVAILABLE.get(state) or ("AI 연결을 쓸 수 없습니다: %s. 추출은 스크립트만으로 됩니다." % (detail or state))


def extraction_of(name):
    path = paths.output_root("extract", name, "extraction.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def graph_id_of(name):
    try:
        with open(paths.output_root("graph", name, "graph.json"), encoding="utf-8") as fh:
            return json.load(fh).get("graph_id")
    except (OSError, ValueError):
        return None


class _Signals(QObject):
    progress = Signal(str, int, int, int)   # 도면 이름, 끝낸 호출, 이번 도면 호출 수, 남은 항목
    finished = Signal(list)                  # [(도면 이름, 후보 수, stats)]
    failed = Signal(str)


class AiReviewBar(QWidget):
    """토글·상한·대상 쪽·예상 + 진행 줄. start(pages)로 돌리고 끝나면 reviewed 신호."""

    reviewed = Signal(list)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._stop = threading.Event()
        self._client = None
        self.sig = _Signals(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        row = QHBoxLayout()
        self.toggle = QCheckBox("추출 뒤 AI 검토")
        self.toggle.setToolTip("스크립트가 못 읽은 기호 종류·태그·위치·끊긴 연결에 AI가 후보를 냅니다. 후보는 추출 결과를 바꾸지 "
                               "않고, 확인해서 수락한 것만 도면 수정 기록에 들어갑니다.")
        self.toggle.setChecked(False)
        self.cap = QSpinBox()
        self.cap.setRange(1, 100)
        self.cap.setValue(ai_review.DEFAULT_CAP)
        self.cap.setSuffix("회")
        self.cap.setAccessibleName("도면당 AI 호출 상한")
        self.cap.lineEdit().setAccessibleName("도면당 AI 호출 상한")
        self.pages = QComboBox()
        for key, label in TARGET_PAGES:
            self.pages.addItem(label, key)
        self.pages.setAccessibleName("AI 검토 대상 쪽")
        self.estimate = QLabel("")
        self.estimate.setWordWrap(True)
        row.addWidget(self.toggle)
        row.addWidget(QLabel("도면당 상한"))
        row.addWidget(self.cap)
        row.addWidget(self.pages)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.estimate)
        self.notice = QLabel("")
        self.notice.setWordWrap(True)
        lay.addWidget(self.notice)
        prog = QHBoxLayout()
        self.progress_text = QLabel("")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.btn_stop = QPushButton("AI 검토 멈추기")
        self.btn_stop.clicked.connect(self.stop)
        prog.addWidget(self.progress_text, 1)
        prog.addWidget(self.progress, 1)
        prog.addWidget(self.btn_stop)
        self.progress_box = QWidget()
        self.progress_box.setLayout(prog)
        self.progress_box.hide()
        lay.addWidget(self.progress_box)
        for w in (self.toggle, self.cap, self.pages):
            (w.toggled if w is self.toggle else w.valueChanged if w is self.cap else w.currentIndexChanged).connect(
                self._update)
        self.sig.progress.connect(self._on_progress)
        self.sig.finished.connect(self._on_finished)
        self.sig.failed.connect(self._on_failed)
        conn = getattr(app, "ai_conn", None)
        if conn is not None:
            conn.changed.connect(self.refresh_availability)
        self.refresh_availability()

    # ---- 상태
    def available(self):
        conn = getattr(self.app, "ai_conn", None)
        return conn is not None and conn.can_start()

    def refresh_availability(self):
        ok = self.available()
        for w in (self.toggle, self.cap, self.pages, self.estimate):
            w.setVisible(ok)
        conn = getattr(self.app, "ai_conn", None)
        st = conn.status() if conn is not None else {"state": "not_installed", "detail": ""}
        self.notice.setText("" if ok else unavailable_text(st.get("state"), st.get("detail")))
        self.notice.setVisible(not ok)
        self._update()

    def enabled(self):
        return self.available() and self.toggle.isChecked()

    def running(self):
        return self.progress_box.isVisible()

    def _update(self):
        self.cap.setEnabled(self.toggle.isChecked())
        self.pages.setEnabled(self.toggle.isChecked())
        if not self.toggle.isChecked():
            self.estimate.setText("끄면 스크립트만으로 추출합니다(기본).")
            return
        cap = self.cap.value()
        per = min(cap, TYPICAL_CALLS)
        self.estimate.setText("예상: 도면당 보통 %d회 안팎, 많아도 %d회 · 호출 하나에 %d초쯤이라 도면당 약 %d분(최대 %d분). "
                              "정확한 호출 수는 추출이 끝나면 진행 줄에 보입니다. 상한에 닿으면 남은 곳은 미확인으로 둡니다."
                              % (per, cap, ai_review.SECONDS_PER_CALL, max(1, per * ai_review.SECONDS_PER_CALL // 60),
                                 max(1, cap * ai_review.SECONDS_PER_CALL // 60)))

    # ---- 실행
    def start(self, pages):
        """pages = [(추출 이름, extraction dict)]. 대상 쪽 고르기를 적용해 따로 스레드에서 돌린다."""
        if self.pages.currentData() == "first":
            pages = pages[:1]
        if not pages or self.running():
            return False
        self._stop.clear()
        self._client = self.app.ai_conn.make_client()
        client, cap = self._client, self.cap.value()
        self.progress.setRange(0, 0)
        self.progress_text.setText("AI 검토 준비 중 · %d개 도면" % len(pages))
        self.progress_box.show()
        self.toggle.setEnabled(False)

        def work():
            done = []
            try:
                for name, ex in pages:
                    if self._stop.is_set():
                        break
                    result = ai_review.run(ex, client, cap=cap,
                                           on_progress=lambda d, t, left, n=name: self.sig.progress.emit(n, d, t, left),
                                           should_stop=self._stop.is_set)
                    doc = ai_review.load_doc(name) or ai_review.new_doc(name, ex)
                    desc = client.describe() if hasattr(client, "describe") else {}
                    ai_review.merge_run(doc, result, via=desc.get("via"), model=desc.get("model"))
                    ai_review.save_doc(doc)
                    done.append((name, len(result["candidates"]), result["stats"]))
                    if result["stats"]["halted"]:
                        break
                self.sig.finished.emit(done)
            except Exception as exc:  # 스레드 안 예외는 화면에 사유로 보인다
                self.sig.failed.emit("%s: %s" % (type(exc).__name__, exc))

        threading.Thread(target=work, name="ai-review", daemon=True).start()
        return True

    def stop(self):
        self._stop.set()
        if self._client is not None and hasattr(self._client, "cancel"):
            self._client.cancel()
        self.progress_text.setText("멈추는 중 · 진행 중인 호출을 끊습니다")

    def _on_progress(self, name, done, total, left):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.progress_text.setText("AI 검토 %s · 호출 %d/%d · 남은 항목 %d" % (name, done, total, left))

    def _finish(self):
        self.progress_box.hide()
        self.toggle.setEnabled(True)
        self._client = None

    def _on_finished(self, done):
        self._finish()
        self.reviewed.emit(done)

    def _on_failed(self, text):
        self._finish()
        self.app.status_message("AI 검토 실패: %s" % text)


def summary_text(done):
    """[(이름, 후보 수, stats)] → 한 줄 요약."""
    cands = sum(n for _, n, _ in done)
    left = sum(st["left"] for _, _, st in done)
    calls = sum(st["calls"] for _, _, st in done)
    halt = [k for _, _, st in done if st["halted"] for k in st["error_kinds"][-1:]]
    text = "AI 후보 %d건 · 호출 %d회" % (cands, calls)
    if left:
        text += " · 미확인으로 남은 곳 %d" % left
    if any(st["stopped"] for _, _, st in done):
        text += " · 멈춤"
    if halt:
        text += " · 오류로 멈춤(%s)" % ", ".join(halt)
    return text


class AiReviewDialog(QDialog):
    """한 도면의 AI 후보 확정 창. 창은 모달이 아니라서 '도면에서 보기'로 ② 도면을 보며 정할 수 있다."""

    COLS = ("필드", "지금 값", "후보", "확신도", "근거", "상태")

    def __init__(self, app, name, parent=None):
        super().__init__(parent)
        self.app, self.name = app, name
        self.setWindowTitle("AI 후보 확정 · %s" % name)
        self.setModal(False)
        self.resize(900, 520)
        self.original = extraction_of(name)
        self.doc = ai_review.load_doc(name) or ai_review.new_doc(name, self.original)
        lay = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        bulk = QHBoxLayout()
        self.bulk_field = QComboBox()
        self.bulk_field.setAccessibleName("묶어 수락할 필드")
        self.btn_bulk = QPushButton("확신 높은 후보 묶어 수락")
        self.btn_bulk.clicked.connect(self.accept_bulk)
        bulk.addWidget(QLabel("확신도 %.2f 이상:" % ai_review.DEFAULT_THRESHOLD))
        bulk.addWidget(self.bulk_field, 1)
        bulk.addWidget(self.btn_bulk)
        lay.addLayout(bulk)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda *_: self.show_on_drawing())
        lay.addWidget(self.table, 1)
        btns = QHBoxLayout()
        self.btn_show = QPushButton("도면에서 보기")
        self.btn_accept = QPushButton("수락")
        self.btn_reject = QPushButton("거절")
        self.btn_revert = QPushButton("되돌리기")
        close = QPushButton("닫기")
        self.btn_show.clicked.connect(self.show_on_drawing)
        self.btn_accept.clicked.connect(lambda: self.decide("accept"))
        self.btn_reject.clicked.connect(lambda: self.decide("reject"))
        self.btn_revert.clicked.connect(lambda: self.decide("revert"))
        close.clicked.connect(self.close)
        for b in (self.btn_show, self.btn_accept, self.btn_reject, self.btn_revert):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.fill()

    # ---- 표
    def _rows(self):
        return sorted(self.doc["candidates"], key=lambda c: (c["status"] != "proposed", list(FIELD_LABELS).index(c["field"]),
                                                             -c["confidence"]))

    def fill(self):
        rows = self._rows()
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            cur = self._current(c)
            vals = (FIELD_LABELS.get(c["field"], c["field"]), cur, " / ".join(c["values"]), "%.2f" % c["confidence"],
                    c.get("reason") or "", STATUS_LABELS.get(c["status"], c["status"]))
            for col, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setData(Qt.UserRole, c["cand_id"])
                self.table.setItem(r, col, it)
        self.table.resizeColumnsToContents()
        n = {s: sum(1 for c in rows if c["status"] == s) for s in STATUS_LABELS}
        last = (self.doc.get("runs") or [{}])[-1]
        self.head.setText("후보 %d건(남은 후보 %d · 수락 %d · 거절 %d). 후보는 추출 결과를 바꾸지 않습니다. 수락한 것만 도면 수정 "
                          "기록에 들어가고 되돌릴 수 있습니다. 마지막 실행: 호출 %s회, 미확인으로 남은 곳 %s."
                          % (len(rows), n["proposed"], n["accepted"], n["rejected"], last.get("calls", "-"),
                             last.get("left", "-")))
        groups = ai_review.bulk_groups(self.doc)
        self.bulk_field.clear()
        for f, ids in groups.items():
            self.bulk_field.addItem("%s %d건" % (FIELD_LABELS.get(f, f), len(ids)), f)
        self.btn_bulk.setEnabled(bool(groups))
        self._update_buttons()

    def _current(self, c):
        if c["field"] == "connection":
            return "열린 끝"
        node = next((n for n in self.original["nodes"] if n["source_object_id"] == c["target"]), None)
        if node is None:
            return ""
        if c["field"] in ("kind", "tag"):
            return node.get(c["field"]) or "없음"
        return (node.get("attributes") or {}).get(c["field"]) or "없음"

    def selected(self):
        ids = []
        for it in self.table.selectedItems():
            cid = it.data(Qt.UserRole)
            if cid not in ids:
                ids.append(cid)
        return ids

    def _update_buttons(self):
        sel = [c for c in self.doc["candidates"] if c["cand_id"] in self.selected()]
        self.btn_show.setEnabled(len(sel) == 1)
        self.btn_accept.setEnabled(any(c["status"] == "proposed" for c in sel))
        self.btn_reject.setEnabled(any(c["status"] == "proposed" for c in sel))
        self.btn_revert.setEnabled(any(c["status"] != "proposed" for c in sel))

    # ---- 결정
    def _by(self):
        try:
            return "%s (AI 후보 확정)" % getpass.getuser()
        except Exception:
            return "사용자 (AI 후보 확정)"

    def _apply(self, action, ids):
        try:
            if action == "accept":
                failed = ai_review.accept(self.doc, ids, self.original, self.name, by=self._by())
                if failed:
                    QMessageBox.warning(self, "수락하지 못한 후보", "\n".join("%s: %s" % f for f in failed))
            elif action == "reject":
                ai_review.reject(self.doc, ids, by=self._by())
            else:
                ai_review.revert(self.doc, ids, self.name, by=self._by())
        except Exception as exc:  # 저장 충돌(그새 ②에서 수정 저장) 등은 다시 읽고 알린다
            QMessageBox.warning(self, "저장하지 못함", "%s\n다시 읽은 뒤 다시 하세요." % exc)
            self.doc = ai_review.load_doc(self.name) or self.doc
        self.fill()
        if action in ("accept", "revert"):
            self.app.status_message("AI 후보를 %s · ② 도면을 다시 열면 반영됩니다" % ("수락함" if action == "accept" else "되돌림"))

    def decide(self, action):
        ids = self.selected()
        if ids:
            self._apply(action, ids)

    def accept_bulk(self):
        field = self.bulk_field.currentData()
        ids = ai_review.bulk_groups(self.doc).get(field) or []
        if not ids:
            return
        ok = QMessageBox.question(self, "묶어 수락", "%s 후보 %d건을 한 번에 수락합니다. 수락한 뒤에도 하나씩 되돌릴 수 있습니다."
                                  % (FIELD_LABELS.get(field, field), len(ids)))
        if ok == QMessageBox.Yes:
            self._apply("accept", ids)

    def show_on_drawing(self):
        ids = self.selected()
        c = next((c for c in self.doc["candidates"] if ids and c["cand_id"] == ids[0]), None)
        host = getattr(self.app, "viewer_host", None)
        if c is None or host is None:
            return
        gid = graph_id_of(self.name)
        self.app.set_drawing(self.name)
        self.app.go(1)
        mark = [{"op": "mark", "groups": [{"ids": [c["local_id"]], "style": "warn", "label": "AI 후보"}], "dim_others": False,
                 "center": True}]
        if gid:
            host.show_marks("ai-review", {gid: mark}, sheet=gid)
        host.webview.zoom_to([c["local_id"]])
