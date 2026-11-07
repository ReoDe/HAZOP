"""주 창 (기획서/인터페이스.md §2.1, 디자인/시안/완성본 B안 + A안 단계 표시). 웹뷰는 하나를 공유한다.

틀: 어두운 제목줄(로고·메뉴·현재 위치·검토자) / 왼쪽 단계 레일(①~⑤, 완료 ✓·현재·남음) / 탐색기 트리 / 화면 / 상태줄.
화면 번호(self.screens·go()의 index)는 추가 순서를 유지한다: 0 ①, 1 ②, 2 이전 ④, 3 이전 ⑤, 4 ③, 5 ④, 6 ⑤.
레일 단계는 STAGES, 보기 메뉴는 STEP_ORDER 순서로 보인다."""

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenuBar,
                               QMessageBox, QPushButton, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from hazop import paths
from hazop.app import tokens
from hazop.app.screens.analysis import AnalysisScreen
from hazop.app.screens.knowledge import KnowledgeScreen
from hazop.app.screens.register import RegisterScreen
from hazop.app.screens.results import ResultsScreen
from hazop.app.screens.review import ReviewScreen
from hazop.app.screens.study import StudyNodesScreen
from hazop.app.screens.viewer import ViewerScreen
from hazop.app.webview import HazopWebView
from hazop.app.widgets import VALIDATION_LABELS, Chip, TaskRunner, esc, kst_text, write_log

APP_NAME = "HAZOP 분석 도구"
APP_VERSION = "0.1.0"
STEPS = ("① 자료 등록", "② 도면 추출", "고정 응답 분석(이전 ④)", "설계보완·확정(이전 ⑤)", "③ 지식그래프", "④ 검토구간",
         "⑤ 분석 결과")  # 화면 index 순
STEP_ORDER = (0, 1, 4, 5, 6, 2, 3)  # 보기 메뉴 순서
# 레일 단계: (번호, 짧은 이름, 화면 index들). 첫 화면이 레일 클릭 대상이고 그 화면의 is_done()이 완료(✓)를 정한다.
STAGES = (("1", "등록", (0,)), ("2", "추출", (1,)), ("3", "그래프", (4,)), ("4", "구간", (5,)), ("5", "결과", (6, 2, 3)))
# 탐색기 묶음: (이름, 단계 번호). 자식은 그 단계 첫 화면의 explorer_items() [(글자, key)]
EXPLORER_GROUPS = (("자료", 0), ("지식그래프", 2), ("검토구간", 3), ("권고", 4))
RAIL_W, EXPLORER_W = 52, 180
# 도움말 > 버전·데이터 위치(패키징 W10, D18): 제3자 고지 위치와 법무 검토 전 안내
LICENSE_NOTE = "LGPL 등 제3자 라이선스 의무의 법무 검토 전이므로 내부용으로만 사용하십시오."


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
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._rail())
        self.explorer = QTreeWidget()
        self.explorer.setObjectName("explorer")
        self.explorer.setHeaderHidden(True)
        self.explorer.setFixedWidth(EXPLORER_W)
        self.explorer.itemClicked.connect(self._explorer_clicked)
        self.explorer_wanted = True  # 보기 메뉴로 접고 편다. 창이 좁으면 자동으로 숨긴다(_fit_explorer)
        body.addWidget(self.explorer)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        cl.addLayout(body, 1)
        self.setCentralWidget(central)
        self.screens = [RegisterScreen(self), ViewerScreen(self), AnalysisScreen(self), ReviewScreen(self),
                        KnowledgeScreen(self), StudyNodesScreen(self), ResultsScreen(self)]
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
        h.setFixedHeight(34)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(4)
        logo = QLabel("HAZOP")
        logo.setObjectName("logo")
        lay.addWidget(logo)
        self.menu_bar = QMenuBar()
        self.menu_bar.setObjectName("titlemenu")
        lay.addWidget(self.menu_bar, 0, Qt.AlignVCenter)
        lay.addStretch(1)
        self.where_label = WhereLabel("")
        self.where_label.setObjectName("where")
        self.where_label.setTextFormat(Qt.RichText)
        self.where_label.setMinimumWidth(120)  # 긴 위치 글자에도 1366 폭 유지: 넘치면 잘리고 툴팁
        lay.addWidget(self.where_label)
        lay.addStretch(1)
        self.reviewer_label = QLabel("")
        self.reviewer_label.setObjectName("reviewer")
        lay.addWidget(self.reviewer_label)
        return h

    def _rail(self):
        """단계 레일. step_buttons[i]는 화면 i마다 하나(같은 QButtonGroup). 보이는 것은 단계 첫 화면 버튼 5개다."""
        self.rail = QWidget()
        self.rail.setObjectName("rail")
        self.rail.setFixedWidth(RAIL_W)
        lay = QVBoxLayout(self.rail)
        lay.setContentsMargins(4, 6, 4, 6)
        lay.setSpacing(2)
        self.step_group = QButtonGroup(self)
        self.step_buttons = []
        for i, label in enumerate(STEPS):
            b = QPushButton(label, self.rail)
            b.setObjectName("step")
            b.setCheckable(True)
            b.setToolTip(label)
            b.setAccessibleName(label)
            b.clicked.connect(lambda _=False, k=i: self.go(k))
            self.step_group.addButton(b)
            self.step_buttons.append(b)
            b.hide()
        for _, _, idxs in STAGES:
            b = self.step_buttons[idxs[0]]
            b.show()
            lay.addWidget(b)
        lay.addStretch(1)
        return self.rail

    def stage_of(self, index):
        return next(k for k, (_, _, idxs) in enumerate(STAGES) if index in idxs)

    def refresh_stages(self):
        """레일 단계 표시(A안)와 탐색기를 다시 계산한다. done = 단계 첫 화면의 is_done(), now = 현재 화면의 단계."""
        now = self.stage_of(self.stack.currentIndex())
        for k, (num, short, idxs) in enumerate(STAGES):
            done = bool(getattr(self.screens[idxs[0]], "is_done", lambda: False)())
            b = self.step_buttons[idxs[0]]
            b.setText("%s\n%s" % ("✓" if done else num, short))
            b.setProperty("state", "now" if k == now else "done" if done else "todo")
            b.style().unpolish(b)
            b.style().polish(b)
        self._refresh_explorer()

    def _refresh_explorer(self):
        """내용이 같으면 다시 만들지 않는다(선택 유지, 항목 클릭 처리 중 항목 삭제 방지)."""
        groups = []
        for name, k in EXPLORER_GROUPS:
            idx = STAGES[k][2][0]
            groups.append((name, idx, list(getattr(self.screens[idx], "explorer_items", lambda: [])())))
        if groups == getattr(self, "_explorer_groups", None):
            return
        self._explorer_groups = groups
        self.explorer.clear()
        for name, idx, items in groups:
            grp = QTreeWidgetItem([name])
            f = grp.font(0)
            f.setBold(True)
            grp.setFont(0, f)
            grp.setFlags(Qt.ItemIsEnabled)
            for text, key in items:
                child = QTreeWidgetItem([text])
                child.setData(0, Qt.UserRole, (idx, key))
                child.setToolTip(0, text)
                grp.addChild(child)
            if not items:
                empty = QTreeWidgetItem(["없음"])
                empty.setFlags(Qt.NoItemFlags)
                grp.addChild(empty)
            self.explorer.addTopLevelItem(grp)
            grp.setExpanded(True)

    def _explorer_clicked(self, item, _col=0):
        target = item.data(0, Qt.UserRole)
        if not target:
            return
        idx, key = target
        self.go(idx)
        h = getattr(self.screens[idx], "open_item", None)
        if h:
            h(key)

    def toggle_explorer(self):
        self.explorer_wanted = not self.explorer_wanted
        self._fit_explorer()

    def _fit_explorer(self):
        """탐색기는 원할 때, 그리고 창 폭이 레일 + 탐색기 + 화면 최소 폭 이상일 때만 보인다(1366 폭 유지)."""
        need = RAIL_W + EXPLORER_W + self.stack.minimumSizeHint().width()
        self.explorer.setVisible(self.explorer_wanted and self.width() >= need)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "stack"):
            self._fit_explorer()

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
        m = self.menu_bar
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
        v.addAction("탐색기 접기/펴기", self.toggle_explorer)
        v.addAction("도면 보기", lambda: self.webview.set_view("drawing"))
        v.addAction("그래프 보기", lambda: self.webview.set_view("graph"))
        v.addAction("웹 속성 패널 숨기기/보이기", lambda: self.webview.set_mode(not self.webview.hide_panel, self.webview.hide_graph))
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
        self.webview.clear_segments()  # ④ 구간 색은 ④에서만 보인다(④는 on_enter에서 다시 칠함)
        scr.on_enter()
        self.update_header()
        self.refresh_stages()
        self._fit_explorer()

    def attach_webview(self, host):
        """웹뷰 인스턴스 하나를 화면의 캔버스 자리로 옮긴다(§2.2)."""
        if self.webview.parent() is not host:
            host.layout().addWidget(self.webview)
        self.webview.show()

    def open_results_for(self, drawing_name, node_id):
        """④에서 고른 구간을 ⑤ 분석 결과에서 연다."""
        self.go(6)
        self.screens[6].show_node(drawing_name, node_id)

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
            self.where_label.set_where("<span style='color:%s'>열린 구간 없음</span>" % tokens.c("nav-muted"), "열린 구간 없음")
            return
        parts, plain = [], []
        if w.get("region"):
            parts.append("<b>%s</b>" % esc(w["region"]))
            plain.append(str(w["region"]))
        if w.get("drawing"):
            parts.append("도면 <b>%s</b>" % esc(w["drawing"]))
            plain.append("도면 %s" % w["drawing"])
        if w.get("run"):
            parts.append("<span style='color:%s'>%s</span>" % (tokens.c("nav-muted"), esc(w["run"])))
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

    def about_text(self):
        return ("%s %s\n자원 루트: %s\n작업 루트: %s\n저장 루트: %s\n설정: %s\n"
                "AI 호출 없음(고정 응답 폴더만), 웹뷰 외부 네트워크 차단\n\n제3자 라이선스 고지: %s\n%s"
                % (APP_NAME, APP_VERSION, paths.resource_root(), paths.work_root(), paths.store_root(),
                   self.settings_path or paths.settings_path(), paths.licenses_dir(), LICENSE_NOTE))

    def _about(self):
        box = QMessageBox(QMessageBox.Information, "버전·데이터 위치", self.about_text(), parent=self)
        open_btn = box.addButton("라이선스 고지 열기", QMessageBox.ActionRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.open_licenses()

    def open_licenses(self):
        """고지 폴더(paths.licenses_dir())를 탐색기로 연다. 폴더가 없거나 열지 못하면 경로를 보여 주고 False."""
        d = paths.licenses_dir()
        if not os.path.isdir(d):
            QMessageBox.warning(self, "라이선스 고지", "라이선스 고지 폴더가 없습니다.\n%s" % d)
            return False
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(d)):
            QMessageBox.information(self, "라이선스 고지", "탐색기로 폴더를 열지 못했습니다. 아래 폴더를 직접 여십시오.\n%s" % d)
            return False
        return True
