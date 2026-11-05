"""주 창 (기획서/인터페이스.md §2.1): 헤더(현재 위치·단계 탭·검토자), 화면 5개, 상태줄, 메뉴. 웹뷰는 하나를 공유한다.

화면 번호(self.screens·go()의 index)는 추가 순서를 유지한다: 0 ①, 1 ②, 2 ④, 3 ⑤, 4 ③(T1 W6에서 추가).
단계 탭과 보기 메뉴는 STEP_ORDER 순서(① ② ③ ④ ⑤)로 보인다."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import tokens
from hazop.app.screens.analysis import AnalysisScreen
from hazop.app.screens.knowledge import KnowledgeScreen
from hazop.app.screens.register import RegisterScreen
from hazop.app.screens.review import ReviewScreen
from hazop.app.screens.viewer import ViewerScreen
from hazop.app.webview import HazopWebView
from hazop.app.widgets import Chip, TaskRunner, esc, kst_text, write_log

APP_NAME = "HAZOP 분석 도구"
APP_VERSION = "0.1.0"
STEPS = ("① 자료 등록", "② 도면·그래프", "④ HAZOP 분석", "⑤ 설계보완·확정", "③ 지식그래프")  # 화면 index 순
STEP_ORDER = (0, 1, 4, 2, 3)  # 화면에 보이는 단계 탭 순서(①②③④⑤)
VALIDATION_LABELS = {"passed": "통과", "blocked": "차단"}


class WhereLabel(QLabel):
    """헤더 현재 위치 라벨: 폭이 모자라 잘리면 전체 문장을 툴팁으로 보여 준다."""

    full_text = ""

    def set_where(self, rich, plain):
        self.full_text = plain
        self.setText(rich)
        self._tip()

    def _tip(self):
        self.setToolTip(self.full_text if self.sizeHint().width() > self.width() else "")

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._tip()


class MainWindow(QMainWindow):
    def __init__(self, settings_path=None, ask_reviewer=True, debug=False):
        super().__init__()
        self.debug = debug  # True면 상태줄에 Python↔웹 메시지 등 개발자 정보를 보여 준다(--debug)
        self.settings_path = settings_path
        self.settings = paths.load_settings(settings_path)
        self.run_ctx = None
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 860)
        self.setStyleSheet(tokens.qss())
        self.tasks = TaskRunner(self)
        self.tasks.started.connect(lambda l: self.task_label.setText("진행 중: %s (취소 불가)" % l))
        self.tasks.finished.connect(lambda l: self.task_label.setText(""))
        self.webview = HazopWebView()
        self.webview.bridge.nodeSelected.connect(self._node_selected)
        self.webview.bridge.highlightResultFor.connect(self._highlight_result)
        self.webview.bridge.linkSelected.connect(self._link_selected)
        self.webview.bridge.algorithmRequested.connect(self._algorithm_requested)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._header())
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.screens = [RegisterScreen(self), ViewerScreen(self), AnalysisScreen(self), ReviewScreen(self),
                        KnowledgeScreen(self)]
        for s in self.screens:
            self.stack.addWidget(s)
        self.screens[2].review_requested.connect(self.review_candidate)
        self._status_bar()
        self._menus()
        self.go(0)
        if ask_reviewer and not self.reviewer_name():
            name, ok = QInputDialog.getText(self, "검토자 이름", "처음 실행입니다. 검토자 이름을 입력하세요(설정에 저장).")
            if ok and name.strip():
                self.set_reviewer_name(name.strip())

    # ------------------------------------------------------------ 틀
    def _header(self):
        h = QWidget()
        h.setObjectName("header")
        h.setFixedHeight(56)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)
        logo = QLabel()
        logo.setObjectName("logo")
        lay.addWidget(logo)
        name = QLabel(APP_NAME)
        name.setObjectName("appname")
        lay.addWidget(name)
        self.where_label = WhereLabel("")
        self.where_label.setObjectName("where")
        self.where_label.setTextFormat(Qt.RichText)
        self.where_label.setMinimumWidth(120)  # 단계 탭 5개(③ 추가) + 긴 위치 글자에도 1366 폭 유지: 넘치면 잘림
        lay.addWidget(self.where_label)
        lay.addStretch(1)
        self.step_group = QButtonGroup(self)
        self.step_buttons = []
        for i, label in enumerate(STEPS):
            b = QPushButton(label)
            b.setObjectName("step")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=i: self.go(k))
            self.step_group.addButton(b)
            self.step_buttons.append(b)
        for i in STEP_ORDER:
            lay.addWidget(self.step_buttons[i])
        lay.addStretch(1)
        self.reviewer_label = QLabel("")
        lay.addWidget(self.reviewer_label)
        return h

    def _status_bar(self):
        sb = self.statusBar()
        self.chip_valid = Chip("결과 검증 —")
        self.task_label = QLabel("")
        self.saved_label = QLabel("최근 저장 —")
        self.msg_label = QLabel("")
        self.msg_label.setObjectName("muted")
        sb.addWidget(self.chip_valid)
        sb.addWidget(self.task_label)
        sb.addWidget(self.saved_label)
        sb.addPermanentWidget(self.msg_label)
        self._update_reviewer_label()

    def _menus(self):
        m = self.menuBar()
        f = m.addMenu("파일")
        f.addAction("구간 열기…", self._open_region)
        f.addAction("실행 열기…", self._open_run_dialog)
        f.addAction("Excel 내보내기…", lambda: (self.go(3), self.screens[3].ask_excel()))
        f.addSeparator()
        f.addAction("설정(검토자 이름)…", self._ask_reviewer)
        f.addSeparator()
        f.addAction("끝내기", self.close)
        v = m.addMenu("보기")
        for i in STEP_ORDER:
            v.addAction(STEPS[i], lambda k=i: self.go(k))
        v.addSeparator()
        v.addAction("도면 보기", lambda: self.webview.set_view("drawing"))
        v.addAction("그래프 보기", lambda: self.webview.set_view("graph"))
        v.addAction("웹 속성 패널 숨기기/보이기", lambda: self.webview.set_mode(not self.webview.hide_panel))
        hm = m.addMenu("도움말")
        hm.addAction("버전·데이터 위치", self._about)

    # ------------------------------------------------------------ 탐색
    def current_screen(self):
        return self.screens[self.stack.currentIndex()]

    def go(self, index):
        """단계 탭은 자유 이동. 앞 단계 결과가 없으면 해당 화면이 빈 화면 안내를 보여 준다(§2.1)."""
        self.stack.setCurrentIndex(index)
        self.step_buttons[index].setChecked(True)
        scr = self.screens[index]
        if getattr(scr, "canvas_host", None) is None:
            self.webview.setParent(None)
            self.webview.hide()
        scr.on_enter()
        self.update_header()

    def attach_webview(self, host):
        """웹뷰 인스턴스 하나를 화면의 캔버스 자리로 옮긴다(§2.2)."""
        if self.webview.parent() is not host:
            host.layout().addWidget(self.webview)
        self.webview.show()

    def review_candidate(self, cid, scenario_id):
        self.go(3)
        self.screens[3].select_candidate(cid, scenario_id or None)

    def set_run(self, ctx):
        """열린 실행 바꾸기. None이면 닫힘(④에서 구간을 바꾸면 이전 실행을 닫는다)."""
        self.run_ctx = ctx
        if ctx is None:
            self.chip_valid.set_state("결과 검증 —")
        else:
            st = ctx.doc["validation"].get("status")
            self.chip_valid.set_state("결과 검증 %s" % VALIDATION_LABELS.get(st, st) +
                                      (" (형식·참조 검증 통과 — 보류 없음을 뜻하지 않음)" if st == "passed" else ""),
                                      "passed" if st == "passed" else "blocked")
        self.update_header()
        if self.stack.currentIndex() == 3:
            self.screens[3].set_ctx(ctx)

    def update_header(self):
        w = self.current_screen().where() or (self.screens[2].where() if self.run_ctx else None)
        if not w:
            self.where_label.set_where("<span style='color:%s'>열린 구간 없음</span>" % tokens.c("muted"), "열린 구간 없음")
            return
        parts, plain = [], []
        if w.get("region"):
            parts.append("<b>%s</b>" % esc(w["region"]))
            plain.append(str(w["region"]))
        if w.get("drawing"):
            parts.append("도면 <b>%s</b>" % esc(w["drawing"]))
            plain.append("도면 %s" % w["drawing"])
        if w.get("run"):
            parts.append("<span style='color:%s'>%s</span>" % (tokens.c("muted"), esc(w["run"])))
            plain.append(str(w["run"]))
        self.where_label.set_where(" · ".join(parts), " · ".join(plain))

    # ------------------------------------------------------------ 브리지
    def _node_selected(self, sel):
        h = getattr(self.current_screen(), "on_node", None)
        if h:
            h(sel)

    def _link_selected(self, link_id):
        h = getattr(self.current_screen(), "on_link", None)
        if h:
            h(link_id)

    def _algorithm_requested(self, req):
        h = getattr(self.current_screen(), "on_algorithm", None)
        if h:
            h(req)

    def _highlight_result(self, request_id, missing):
        h = getattr(self.current_screen(), "on_highlight_result", None)
        if h:
            h(missing, request_id)

    def closeEvent(self, event):  # noqa: N802
        self.tasks.wait(30000)
        self.webview.dispose()
        super().closeEvent(event)

    # ------------------------------------------------------------ 설정·상태
    def reviewer_name(self):
        return (self.settings.get("reviewer_name") or "").strip() or None

    def set_reviewer_name(self, name):
        self.settings["reviewer_name"] = name
        paths.save_settings(self.settings, self.settings_path)
        self._update_reviewer_label()

    def _update_reviewer_label(self):
        n = self.reviewer_name()
        if hasattr(self, "reviewer_label"):
            self.reviewer_label.setText("검토자 %s" % (n or "미설정"))

    def _ask_reviewer(self):
        name, ok = QInputDialog.getText(self, "검토자 이름", "검토자 이름", text=self.reviewer_name() or "")
        if ok and name.strip():
            self.set_reviewer_name(name.strip())

    def debug_message(self, text):
        """개발자 정보(Python↔웹 메시지 등)는 --debug에서만 상태줄에 보인다."""
        if self.debug:
            self.msg_label.setText(text)

    def log_error(self, title, exc):
        write_log(title, "%s: %s" % (type(exc).__name__, exc))

    def status_message(self, text):
        self.msg_label.setText(text)

    def mark_saved(self, utc_iso):
        self.saved_label.setText("최근 저장 %s" % kst_text(utc_iso))

    def _open_region(self):
        path, _ = QFileDialog.getOpenFileName(self, "구간 JSON", paths.work_path("데이터", "구간"), "JSON (*.json)")
        if path:
            scr = self.screens[2]
            i = scr.region_combo.findData(path)
            if i < 0:
                scr.region_combo.addItem(os.path.splitext(os.path.basename(path))[0], path)
                i = scr.region_combo.count() - 1
            scr.region_combo.setCurrentIndex(i)
            self.go(2)

    def _open_run_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "분석 실행 폴더", paths.output_root("분석"))
        if d:
            self.open_run(d)

    def open_run(self, run_dir):
        self.go(2)
        return self.screens[2].open_run(run_dir)

    def _about(self):
        QMessageBox.information(self, "버전·데이터 위치", "%s %s\n자원 루트: %s\n작업 루트: %s\n저장 루트: %s\n설정: %s\n"
                                "AI 호출 없음(고정 응답 폴더만), 웹뷰 외부 네트워크 차단"
                                % (APP_NAME, APP_VERSION, paths.resource_root(), paths.work_root(), paths.store_root(),
                                   self.settings_path or paths.settings_path()))
