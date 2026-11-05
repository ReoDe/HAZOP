"""② 도면·그래프 조회 (기획서/인터페이스.md §3.2). 웹뷰는 기존 뷰어 그대로(도면/그래프 탭은 웹뷰 안, §2.2)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from hazop.app import data
from hazop.app.widgets import Banner, Chip, empty_label


class ViewerScreen(QWidget):
    title = "② 도면·그래프"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.info = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("도면"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(320)
        self.combo.currentIndexChanged.connect(self._load)
        bar.addWidget(self.combo)
        self.chip_valid = Chip()
        self.chip_stats = Chip()
        bar.addWidget(self.chip_valid)
        bar.addWidget(self.chip_stats)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.blockers = Banner("err")
        self.warn = Banner("warn")
        lay.addWidget(self.blockers)
        lay.addWidget(self.warn)
        self.stack = QStackedWidget()
        self.empty = empty_label("추출 결과가 없습니다. ① 자료 등록에서 등록한 뒤 '추출·그래프 만들기'를 실행하세요.")
        self.canvas_host = QWidget()
        QVBoxLayout(self.canvas_host).setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.canvas_host)
        lay.addWidget(self.stack, 1)

    def where(self):
        if not self.info:
            return None
        d = self.info["extraction"]["drawing"]
        return {"drawing": d.get("drawing_number"), "region": None, "run": None}

    def on_enter(self):
        self.app.webview.set_mode(hide_panel=False)
        self.app.webview.clear_highlight()
        names = [e["name"] for e in data.list_extractions()]
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if cur in names:
            self.combo.setCurrentText(cur)
        self.combo.blockSignals(False)
        self._load()

    def select_drawing(self, name):
        if self.combo.findText(name) >= 0:
            self.combo.setCurrentText(name)

    def _load(self):
        name = self.combo.currentText()
        if not name:
            self.info = None
            self.stack.setCurrentIndex(0)
            self.chip_valid.set_state("구조 검증 —")
            self.chip_stats.set_state("노드 — · 관계 — · 미확인 —")
            self.blockers.set_messages(None)
            self.warn.set_messages(None)
            self.app.update_header()
            return
        try:
            self.info = info = data.viewer_html_for(name)
        except (OSError, ValueError, KeyError) as exc:
            self.info = None
            self.stack.setCurrentIndex(0)
            self.empty.setText("추출 결과를 읽을 수 없음: %s" % exc)
            return
        g, ex = info["graph"], info["extraction"]
        if g:
            st = g["validation"]["status"]
            self.chip_valid.set_state("구조 검증 %s" % {"passed": "통과", "blocked": "차단"}.get(st, st), "passed" if st == "passed" else "blocked")
            self.chip_stats.set_state("노드 %d · 관계 %d · 미확인 %d" % (
                g["structure"]["node_count"], g["structure"]["edge_count"], len(g["validation"].get("unknowns") or [])))
            self.blockers.set_messages("그래프 구조 검증 차단 — 도면은 조회만 허용" if st != "passed" else None,
                                       ["%s %s" % (b.get("check"), b.get("target") or "") for b in
                                        g["validation"].get("blockers") or []])
        else:
            s = ex["summary"]
            self.chip_valid.set_state("그래프 없음", "warn")
            self.chip_stats.set_state("노드 %d · 관계 %d · 미확인 %d" % (s["nodes"], s["relations"], s["unknowns"]))
            self.blockers.set_messages(None)
        self.warn.set_messages(info["error"])
        if info["html"]:
            self.stack.setCurrentIndex(1)
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_drawing_enabled(True)  # ②는 현재 도면 그대로(분석 실행 기준 잠금 없음)
            self.app.webview.load_file(info["html"])
            if info.get("graph_only"):
                self.app.status_message("SVG 없음 — 그래프 보기만 표시")
        else:
            self.stack.setCurrentIndex(0)
            self.empty.setText(info["error"] or "")
        self.app.update_header()

    def on_node(self, sel):
        self.app.debug_message("nodeSelected: %s" % (sel.get("entity_id") or sel.get("local_id")))
