"""③ 지식그래프 (기획서/인터페이스.md §3.5, 그래프활용.md §5, 디자인/지식그래프화면.md §4·§5).

- 도구줄(Qt): 지식그래프·도면 선택, 검증·충돌·재확인·계산 제외·알고리즘 칩, 버전 정보(kg_version·graph_version은 툴팁)
- 띠(Qt): blocked(차단 목록, 직전 passed 버전 보기), 알고리즘 비활성 사유, S1 노드 수 상한 초과, 재확인 필요
- 캔버스(웹, 공유 웹뷰): hazop/kg/screen_template.html 셸에 loadKnowledge로 데이터를 넘긴다. 좌측 필터도 웹 안에 있다.
- 우측 상세(Qt): 클릭한 노드·관계의 속성·근거·A1~A3·연결 목록, P&ID 노드면 "도면에서 보기"(② 전환 + focus).
  잠재 후보(hazop.kg.expect)면 규칙·근거 수준·후보와 판단 버튼(후보 확인·후보 기각·부재 확정·무관·판단 되돌리기). 판단은
  data/latent-candidates/<project_id>.json에 저장하고 updateExpectations로 캔버스의 잠재 후보만 바꾼다.
- 계산은 Python(hazop.kg.screen → hazop.kg.algo). runAlgorithm(A1) 요청을 받아 algorithmResult로 돌려준다.
"""

import os

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel,
                               QLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QTabWidget,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import data as app_data
from hazop.app import project_ctx, tokens
from hazop.app.related import STATUS_LABELS as ENTRY_STATUS_LABELS
from hazop.app.screens.viewer import OP_LABELS
from hazop.app.widgets import VALIDATION_LABELS, Banner, Chip, badge, empty_label, esc
from hazop.graph import project
from hazop.graph.build import node_origin
from hazop.graph.query import VALVE_POSITION_NOTE, QueryError
from hazop.ie import bundle as ie_bundle
from hazop.ie import model as ie_model
from hazop.ie import store as ie_store
from hazop.kg import algo, auto, build, expect, screen
from hazop.kg.schema import REGISTRY
from hazop.study import nodes as study_nodes
from hazop.study import results as study_results

APP_SHELL = "kg-screen.html"  # output/viewer/ 아래 앱 셸(데이터 없음, loadKnowledge로 받음)
TYPE_NAMES = {"equipment": "설비", "valve": "밸브", "inline_component": "배관 부품", "instrument": "계장",
              "piping_element": "배관 요소", "pipe_segment": "배관 구간", "unclassified": "미분류", "document": "문서",
              "doc_chunk": "문서 조각",
              "requirement": "요건", "setpoint": "설정치", "condition": "운전조건·설계값", "analysis_case": "해석 사례",
              "expectation": "잠재 후보"}
STATUS_ORDER = {"confirmed": 0, "recheck": 1, "excluded": 2, "candidate": 3, "expect": 4}
STATUS_NAMES = {"confirmed": "확인", "recheck": "재확인 필요", "excluded": "계산 제외", "candidate": "후보",
                "expect": "잠재 후보"}
A1_NAMES = {"downstream": "하류", "upstream": "상류", "mixed": "혼합", "unknown": "방향 미확인", "adjacent": "인접 구간",
            "not_applicable": "방향 해당 없음"}
EMPTY_TEXT = ("지식그래프가 없습니다.\n① 자료 등록에서 P&ID 도면(drawio·PDF)을 등록하고 추출하면 지식그래프가 자동으로 "
              "만들어집니다.\n설계 문서 PDF를 등록하면 설정치·운전조건·요건을 자동 추출해 '자동 추출 · 사람 확인 전'으로 "
              "더합니다.")
AUTO_BADGE = "자동 추출 · 사람 확인 전"
AI_BADGE = "AI 초안"
HUMAN_EDIT_BADGE = "사람 수정"
# 우측 상세 빈 상태(U-09): 제목 한 줄 + 이유 + 다음 단계. 파일 경로 같은 내부값은 넣지 않는다. %s = 제목 색, 본문 색
EXPECT_NOTE = "잠재 후보는 사실이 아닙니다. 계산 뷰(V4·V5)와 근거 경로에 넣지 않으며, 부재 확정은 근거를 본 사람만 합니다."
DETAIL_EMPTY = ("<div style='color:%s;font-weight:700'>선택한 항목 없음</div>"
                "<p style='color:%s'>그래프에서 노드나 관계를 누르면 속성·근거·연결 목록이 여기에 나옵니다.<br>"
                "표시·배치는 근거가 아닙니다. 근거는 이 패널의 출처입니다.<br><br>"
                "다음 단계: 왼쪽 검색에서 태그를 찾거나 그래프의 노드를 누르세요.</p>")


def auto_extracted(rec):
    """규칙 추출기가 만들고 사람이 아직 확인하지 않은 지식 노드·관계."""
    return rec.get("method") == "extractor" and rec.get("knowledge_status") != "confirmed"


class FlowLayout(QLayout):
    """도구줄 칩을 폭에 맞춰 여러 줄로 접는 배치(디자인 §5: 1366에서 칩이 두 줄로 접힐 수 있음)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 (Qt 이름)
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):  # noqa: N802
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):  # noqa: N802
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._place(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, True)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _place(self, rect, apply):
        x, y, line = rect.x(), rect.y(), 0
        for it in self.items:
            if it.widget() is not None and it.widget().isHidden():
                continue
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self.spacing(), 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line = max(line, hint.height())
        return y + line - rect.y()


def info_tooltip(meta, standalone=None):
    """도구줄 '버전 정보' 칩의 툴팁: 내부 버전 해시와 브라우저 단독 모드 HTML 위치."""
    lines = ["kg_version %s" % meta["kg_version"], "graph_version %s" % meta["graph_version"]]
    if meta["graph_ref_version"] != meta["graph_version"]:
        lines.append("지식그래프 기준 graph_version %s" % meta["graph_ref_version"])
    if standalone:
        lines.append("브라우저 단독 모드 HTML(미리 계산된 결과만): %s" % standalone)
    return "\n".join(lines)


def kg_root_dir():
    return paths.output_root("knowledge-graph")


def standalone_path(kg, graph_id):
    """브라우저 단독 모드 HTML: output/knowledge-graph/<kg_id>/screen/<kg_version>/<graph_id>.html."""
    base = paths.safe_join(kg_root_dir(), paths.safe_name(kg["kg_id"]))
    return os.path.join(base, "screen", paths.safe_name(kg["kg_version"]), paths.safe_name(graph_id) + ".html")


class KnowledgeScreen(QWidget):
    title = "③ 지식그래프"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.kg = None
        self.graph = None
        self.graph_dir = None
        self.data = None
        self.regions = []
        self.a1_full = None
        self.prev = None         # blocked일 때 (kg_version, kg)
        self.showing_prev = False
        self.sel = None          # ("n"|"l", id)
        self.expect = None       # 잠재 후보(expect.evaluate 결과)
        self.expect_error = None  # 판단 파일을 읽지 못한 사유(있으면 판단 버튼을 막음)
        self.expect_calc_error = None  # 잠재 후보를 계산하지 못한 사유(③의 나머지는 그대로 보임)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)
        bar_w = QWidget()
        bar = FlowLayout(bar_w)
        bar.addWidget(QLabel("지식그래프"))
        self.kg_combo = QComboBox()
        self.kg_combo.setMinimumWidth(150)
        self.kg_combo.setAccessibleName("지식그래프")
        self.kg_combo.currentIndexChanged.connect(lambda _: self._load())
        bar.addWidget(self.kg_combo)
        bar.addWidget(QLabel("도면"))
        self.graph_combo = QComboBox()
        self.graph_combo.setMinimumWidth(140)
        self.graph_combo.setAccessibleName("도면")
        self.graph_combo.currentIndexChanged.connect(lambda _: self._load(keep_kg=True))
        bar.addWidget(self.graph_combo)
        self.chips = {k: Chip() for k in ("valid", "graph", "conf", "recheck", "excl", "algo")}
        for c in self.chips.values():
            bar.addWidget(c)
        # 내부 버전 해시(kg_version·graph_version)는 도구줄 글자로 보이지 않고 툴팁으로만(U-15). Chip은 줄임이 없을 때
        # 툴팁을 지우므로 일반 QLabel에 칩 모양만 입힌다.
        self.info_chip = QLabel("버전 정보")
        self.info_chip.setObjectName("chip")
        bar.addWidget(self.info_chip)
        lay.addWidget(bar_w)
        self.blockers = Banner("err")
        self.prev_btn = QPushButton("이전 버전 보기")
        self.prev_btn.hide()
        self.prev_btn.clicked.connect(self._toggle_prev)
        brow = QHBoxLayout()
        brow.addWidget(self.blockers, 1)
        brow.addWidget(self.prev_btn, 0, Qt.AlignTop)
        lay.addLayout(brow)
        self.algo_band = Banner("warn")
        self.s1_band = Banner("warn")
        self.recheck_band = Banner("warn")
        for b in (self.algo_band, self.s1_band, self.recheck_band):
            lay.addWidget(b)
        self.stack = QStackedWidget()
        self.empty = empty_label(EMPTY_TEXT)
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.canvas_host = QWidget()
        QVBoxLayout(self.canvas_host).setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.canvas_host, 1)
        self.detail_box = QFrame()
        self.detail_box.setObjectName("panel")
        dl = QVBoxLayout(self.detail_box)
        dl.setContentsMargins(8, 6, 8, 8)
        dh = QHBoxLayout()
        self.detail_toggle = QPushButton("접기")
        self.detail_toggle.setToolTip("상세 패널 접기/펴기")
        self.detail_toggle.clicked.connect(self._toggle_detail)
        dh.addWidget(self.detail_toggle)
        self.detail_title = QLabel("상세")
        self.detail_title.setObjectName("section")
        dh.addWidget(self.detail_title)
        dh.addStretch(1)
        dl.addLayout(dh)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(self._anchor)
        self.detail_empty = QLabel(DETAIL_EMPTY % (tokens.c("ink"), tokens.c("muted")))
        self.detail_empty.setWordWrap(True)
        self.detail_empty.setAlignment(Qt.AlignCenter)
        self.detail_empty.setContentsMargins(12, 12, 12, 12)
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self.detail_empty)
        self.detail_stack.addWidget(self.detail)
        self.side_tabs = QTabWidget()
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.addTab(self.detail_stack, "상세")
        self.side_tabs.addTab(self._project_panel(), "도면 경계")
        dl.addWidget(self.side_tabs, 1)
        foot = QHBoxLayout()
        self.goto_btn = QPushButton("도면에서 보기")
        self.goto_btn.setEnabled(False)
        self.goto_btn.clicked.connect(self.show_in_drawing)
        foot.addWidget(self.goto_btn)
        foot.addStretch(1)
        dl.addLayout(foot)
        xrow = QGridLayout()  # 상세 폭(최소 320px)에서 버튼 글자가 잘리지 않게 두 칸씩
        xrow.setSpacing(4)
        self.expect_btns = {}
        for k, (action, label, tip) in enumerate((("confirm", "후보 확인", "찾은 후보가 기대를 채운다고 확인합니다"),
                                   ("reject", "후보 기각", "찾은 후보가 맞지 않습니다. 기대됨으로 돌아갑니다"),
                                   ("absent", "부재 확정…", "근거를 보고 없다고 확정합니다(사유·근거 필수)"),
                                   ("not_applicable", "무관…", "이 대상에는 기대가 맞지 않습니다(사유 필수)"),
                                   ("undo", "판단 되돌리기", "사람 판단을 거두고 자동 판정으로 돌아갑니다(이전 기록은 남김)"))):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, a=action: self.judge_expectation(a))
            b.hide()
            xrow.addWidget(b, k // 2, k % 2)
            self.expect_btns[action] = b
        dl.addLayout(xrow)
        self.detail_collapsed = False
        self.pg, self.pg_error, self.path_steps = None, None, None
        bl.addWidget(self.detail_box)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(body)
        lay.addWidget(self.stack, 1)
        self._clear_detail()

    # ------------------------------------------------------------ 틀
    def where(self):
        if not self.kg:
            return None
        return {"region": self.kg.get("kg_id"), "drawing": self.graph_dir,
                "run": "이전 버전" if self.showing_prev else None}  # kg_version은 도구줄 '버전 정보' 툴팁(헤더 폭 1366 유지)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._size_detail()

    def _size_detail(self):
        """우측 상세 폭 clamp(320px, 24vw, 420px)(디자인 §5). 접으면 펴기 버튼 폭만."""
        if self.detail_collapsed:
            self.detail_box.setFixedWidth(self.detail_toggle.sizeHint().width() + 20)
            return
        w = self.window().width() if self.window() else self.width()
        self.detail_box.setFixedWidth(int(min(tokens.KG_RIGHT_MAX, max(tokens.KG_RIGHT_MIN, w * tokens.KG_RIGHT_VW))))

    def _toggle_detail(self):
        self.detail_collapsed = not self.detail_collapsed
        for w in (self.side_tabs, self.goto_btn, self.detail_title):
            w.setVisible(not self.detail_collapsed)
        self.detail_toggle.setText("펴기" if self.detail_collapsed else "접기")
        self._size_detail()

    def _build_missing(self):
        """등록·추출 결과는 있는데 지식그래프가 아직 없는 프로젝트를 빌드한다(실패는 기록만, 화면은 계속)."""
        try:
            pids = auto.project_ids(paths.output_root("graph"), app_data.doc_root())
        except OSError as exc:
            self.app.log_error("지식그래프 자동 생성", exc)
            return
        for pid in pids:
            if os.path.isfile(os.path.join(kg_root_dir(), paths.safe_name("kg-%s" % pid), build.POINTER_FILE)):
                continue
            try:
                app_data.build_project_kg(pid)
            except (OSError, ValueError, KeyError) as exc:
                self.app.log_error("지식그래프 자동 생성(%s)" % pid, exc)

    def on_enter(self):
        self.app.webview.set_mode(hide_panel=False)
        self._build_missing()
        cur = self.kg_combo.currentData()
        self.kg_combo.blockSignals(True)
        self.kg_combo.clear()
        for kg_id, path in screen.list_kg_roots(kg_root_dir()):
            self.kg_combo.addItem(kg_id, path)
        i = self.kg_combo.findData(cur)
        if i >= 0:
            self.kg_combo.setCurrentIndex(i)
        self.kg_combo.blockSignals(False)
        self.showing_prev = False
        self.pg = None
        self._load()

    def is_done(self):
        return bool(screen.list_kg_roots(kg_root_dir()))

    def explorer_items(self):
        return screen.list_kg_roots(kg_root_dir())

    def open_item(self, path):
        i = self.kg_combo.findData(path)
        if i >= 0:
            self.kg_combo.setCurrentIndex(i)

    # ------------------------------------------------------------ 읽기
    def _set_empty(self, text):
        self.kg = self.graph = self.data = None
        self.stack.setCurrentIndex(0)
        self.empty.setText(text)
        for c in list(self.chips.values()) + [self.info_chip]:
            c.hide()
        for b in (self.blockers, self.algo_band, self.s1_band, self.recheck_band):
            b.set_messages(None)
        self.prev_btn.hide()
        self.app.update_header()

    def _load(self, keep_kg=False):
        root = self.kg_combo.currentData()
        if not root:
            self._set_empty(EMPTY_TEXT)
            return
        try:
            if not keep_kg or self.kg is None:
                _, kg = build.load_outputs(root)
                self.prev = screen.previous_passed(root, kg["kg_version"]) \
                    if (kg.get("validation") or {}).get("status") != "passed" else None
                if self.showing_prev and self.prev:
                    kg = self.prev[1]
                self.kg = kg
                self._fill_graphs()
            kg = self.kg
            refs = kg.get("graph_refs") or []
            if not refs:
                n = sum(1 for k in kg.get("nodes") or [] if k.get("node_type") != "document")
                self._set_empty("지식그래프 %s에 설계 문서에서 추출한 항목 %d개가 있습니다(%s).\n그래프에서 보려면 ① 자료 "
                                "등록에서 같은 프로젝트(%s)의 P&ID 도면을 등록하고 추출하세요."
                                % (kg.get("kg_id"), n, AUTO_BADGE, kg.get("project_id")))
                self.kg = kg
                return
            gid = self.graph_combo.currentData()
            ref_ver = {r["graph_id"]: r["graph_version"] for r in refs}.get(gid)
            found = screen.graph_for_ref(paths.output_root("graph"), gid, ref_ver)
            if found is None:
                self._set_empty("지식그래프 %s가 참조한 도면 그래프가 없습니다: %s. ①에서 추출·그래프를 만드세요."
                                % (kg.get("kg_id"), ", ".join(r["graph_id"] for r in refs)))
                self.kg = kg
                return
            self.graph_dir, self.graph = found
            self.regions = screen.load_regions(paths.folder("regions"))
            cands = screen.read_candidates(paths.safe_join(paths.folder("knowledge-graph"), kg.get("project_id") or ""))
            self._load_project()
            self.expect = self._expectations()
            self.data = screen.screen_data(kg, self.graph, self.regions, cands,
                                           standalone_note="이전 버전" if self.showing_prev else None,
                                           expectations=self.expect, study=self._study())
            self.a1_full = None
            shell = screen.write_html(paths.output_root("viewer", APP_SHELL), screen.build_html(None))
            self.standalone = screen.write_html(standalone_path(kg, gid), screen.build_html(self.data))
        except (OSError, ValueError, KeyError) as exc:
            self.app.log_error("지식그래프 읽기", exc)
            self._set_empty("지식그래프를 읽을 수 없음: %s" % exc)
            return
        self._fill_status()
        self.stack.setCurrentIndex(1)
        self.app.attach_webview(self.canvas_host)
        self.app.webview.load_file(shell)
        self.app.webview.bridge.send("loadKnowledge", data=self.data)
        self._clear_detail()
        self._size_detail()
        self.app.update_header()

    def _fill_graphs(self):
        cur = self.graph_combo.currentData()
        self.graph_combo.blockSignals(True)
        self.graph_combo.clear()
        for r in self.kg.get("graph_refs") or []:
            self.graph_combo.addItem(r["graph_id"].replace("graph-", "", 1), r["graph_id"])
        i = self.graph_combo.findData(cur)
        self.graph_combo.setCurrentIndex(max(i, 0))
        self.graph_combo.blockSignals(False)

    def _fill_status(self):
        m, a = self.data["meta"], self.data["algo"]
        v = self.kg.get("validation") or {}
        ch = self.chips
        for c in list(ch.values()) + [self.info_chip]:
            c.show()
        same = m["graph_ref_version"] == m["graph_version"]
        self.info_chip.setText("버전 정보 · 이전 버전" if self.showing_prev else "버전 정보")
        self.info_chip.setToolTip(info_tooltip(m, getattr(self, "standalone", None)))
        st = m["status"]
        ch["valid"].set_state("검증 %s · 차단 %d · 미확인 %d" % (VALIDATION_LABELS.get(st, st),
                                                            m["blockers"], m["unknowns"]),
                              "passed" if st == "passed" else "blocked")
        ch["graph"].set_state("도면 그래프가 지식그래프 기준과 다름(버전 정보 참고)", "warn")
        ch["graph"].setVisible(not same)
        ch["conf"].set_state("충돌 %d" % m["conflicts"], "warn" if m["conflicts"] else "")
        ch["recheck"].set_state("재확인 필요 %d" % m["recheck"], "warn")
        ch["recheck"].setVisible(m["recheck"] > 0)
        c = m["candidates"]
        ch["excl"].set_state("계산 제외 노드 %d · 관계 %d · 후보 %s" % (m["excluded_nodes"], m["excluded_links"],
                                                                 c["shown"] if c["file"] else "파일 없음"))
        ch["algo"].set_state("알고리즘: 현재 버전으로 계산" if a["enabled"] else "알고리즘 비활성",
                             "" if a["enabled"] else "warn")
        if st != "passed":
            self.blockers.set_messages("지식그래프 검증 차단 — 알고리즘을 실행하지 않음(A1·A2·A3·A5 비활성). 아래 항목의 "
                                       "입력(도면·설계 문서·지식 입력)을 고친 뒤 ① 자료 등록에서 다시 등록·추출하세요"
                                       + (". 직전 passed 버전 %s가 있음" % self.prev[0] if self.prev else ""),
                                       ["[%s] %s %s: %s" % (b.get("rule"), b.get("check"), b.get("target") or "",
                                                            b.get("reason")) for b in v.get("blockers") or []])
        else:
            self.blockers.set_messages("이전 버전 표시 중(최신 버전은 차단됨)" if self.showing_prev else None)
        self.prev_btn.setVisible(bool(self.prev))
        self.prev_btn.setText("최신(차단) 버전 보기" if self.showing_prev else
                              "이전 버전 보기 (%s)" % self.prev[0] if self.prev else "")
        self.algo_band.set_messages("알고리즘 비활성: %s" % a["reason"] if not a["enabled"] and st == "passed" else None)
        self.s1_band.set_messages(screen.s1_message(self.data))
        rk = [l for l in self.kg.get("links") or [] if l.get("recheck")]
        msgs = []
        if rk:
            msgs.append("재확인 필요 %d건 — 계산에서 빠짐. 후보 CSV에서 다시 판단한 뒤 반영하세요" % len(rk))
        x_msgs, x_details = self._expect_band()
        self.recheck_band.set_messages(" · ".join(msgs + x_msgs) if msgs or x_msgs else None,
                                       ["%s: %s" % (l["id"], l.get("recheck")) for l in rk] + x_details)

    def _expect_band(self):
        """재확인 띠에 넣을 잠재 후보 안내 (문장 목록, 상세 목록)."""
        xr = [i for i in (self.expect or {}).get("items") or [] if i["recheck"]]
        lost = (self.expect or {}).get("orphan_judgements") or []
        bad = (self.expect or {}).get("bad_judgements") or []
        msgs = []
        if self.expect_calc_error:
            msgs.append("잠재 후보를 계산하지 못함: %s" % self.expect_calc_error)
        if xr:
            msgs.append("잠재 후보 재확인 필요 %d건 — 도면·문서 내용이나 규칙 판이 바뀌어 판단을 다시 봐야 함" % len(xr))
        if lost:
            msgs.append("대상을 찾지 못한 잠재 후보 판단 %d건 — 도면에서 대상이 없어졌거나 바뀜(판단 파일에는 보존)" % len(lost))
        if bad:
            msgs.append("잠재 후보 판단 기록 %d건을 읽지 못해 적용하지 않음(파일은 그대로 둠)" % len(bad))
        if self.expect_error:
            msgs.append("잠재 후보 판단 파일을 읽지 못해 판단을 보이지 않음(파일은 그대로 둠): %s" % self.expect_error)
        details = (["%s %s: 이전 %s" % (i["rule_id"], i["target_tag"] or i["target"], expect.previous_label(i)) for i in xr]
                   + ["대상 없음: %s" % k for k in lost]
                   + ["읽지 못한 판단 %s: %s" % (b["key"], ", ".join(b["problems"])) for b in bad])
        return msgs, details

    def open_node(self, kg_id, graph_id, entity_id, kg_version):
        """⑤ '③에서 보기' 진입(그래프활용 §6.4.5). kg_id 지식그래프와 실행 도면을 고른 뒤, ③이 연 버전(현재 또는
        이전 버전)이 분석 당시 kg_version과 같을 때만 기존 selectNode를 보낸다(loadKnowledge 뒤, 브리지 전송 순서).
        다르면 이동만 하고 상태줄에 안내한다(W7-9). 반환: 노드를 자동 선택했으면 True."""
        i = self.kg_combo.findText(kg_id)
        if i < 0:
            self._status("지식그래프 %s 없음 — 노드를 자동 선택하지 않음" % kg_id)
            return False
        if i != self.kg_combo.currentIndex():
            self.kg_combo.setCurrentIndex(i)  # _load
        j = self.graph_combo.findData(graph_id)
        if j >= 0 and j != self.graph_combo.currentIndex():
            self.graph_combo.setCurrentIndex(j)  # _load(keep_kg)
        if self.kg and self.kg.get("kg_version") != kg_version and self.prev and self.prev[0] == kg_version \
                and not self.showing_prev:
            self._toggle_prev()
        if not self.kg or self.kg.get("kg_version") != kg_version:
            self._status("분석 당시와 다른 버전 — 노드를 자동 선택하지 않음(자세한 내용은 툴팁)",
                         "분석 당시 지식그래프 %s, ③ 표시 %s" % (kg_version, (self.kg or {}).get("kg_version")))
            return False
        if self.graph_combo.currentData() != graph_id or entity_id not in self._nodes():
            self._status("이 도면에서 노드를 찾을 수 없음: %s" % entity_id)
            return False
        self.app.webview.bridge.send("selectNode", id=entity_id)
        self.render_node(entity_id)
        return True

    def _toggle_prev(self):
        self.showing_prev = not self.showing_prev
        self.kg = None
        self._load()

    # ------------------------------------------------------------ 상세
    def _expectations(self):
        """프로젝트 그래프·지식그래프·판단 파일로 잠재 후보를 계산한다. 프로젝트 그래프가 없으면 None."""
        self.expect_error = self.expect_calc_error = None
        if self.pg is None:
            return None
        pid = self.pg["project_id"]
        try:
            judgements = expect.load_judgements(expect.store_path(pid), pid)
        except (OSError, expect.ExpectError) as exc:
            self.app.log_error("잠재 후보 판단 읽기", exc)
            self.expect_error = str(exc)
            judgements = {}
        try:
            return expect.evaluate_cached(self.pg, self.kg, judgements)
        except expect.ExpectError as exc:
            self.app.log_error("잠재 후보 계산", exc)
            self.expect_calc_error = str(exc)
            return None

    def _study(self):
        """검토 층 원본 {"node_set", "results", "note"}(⑤와 같은 조건의 확정 구간·결과만). 읽기만 하고 고치지 않는다."""
        if self.pg is None:
            return None
        try:
            ns = study_nodes.load(self.pg)
        except (OSError, ValueError) as exc:
            return {"node_set": None, "results": None, "note": "검토구간 파일을 읽을 수 없음: %s" % exc}
        if not ns or not study_nodes.active_nodes(ns) or study_nodes.is_stale(ns, self.pg):
            return {"node_set": None, "results": None, "note": "확정된 프로젝트 검토구간이 없거나 지금 도면과 맞지 않습니다."}
        try:
            doc = study_results.load(ns)
        except (OSError, ValueError) as exc:
            return {"node_set": ns, "results": None, "note": "분석 결과를 읽을 수 없음: %s" % exc}
        if doc is not None:
            doc, problems, _bad = study_results.partition(doc, ns)
            if problems:
                return {"node_set": ns, "results": None, "note": "분석 결과 파일에 문제가 있어 투영하지 않습니다(%s)."
                        % problems[0]}
        return {"node_set": ns, "results": doc, "note": None if doc else "아직 분석 결과가 없습니다.",
                "ie": self._ie(ns, doc)}

    def _ie(self, ns, doc):
        """⑥ 초기사건 투영용 IE 인계 묶음 dict. ⑥ 파일을 읽기만 하고 ⑤와 맞추는 것도 메모리 안에서만 한다(저장은 ⑥ 화면)."""
        if not doc:
            return None
        try:
            ie_doc = ie_store.load(self.pg["project_id"])[0]
            return ie_bundle.build_bundle(doc, ns, self.pg, ie_model.sync(ie_doc, doc, node_set=ns),
                                          study_nodes.now_utc())
        except (OSError, ValueError, ie_store.Unreadable) as exc:
            self.app.log_error("초기사건 투영", exc)
            return None

    def render_study(self, n):
        """검토 층 노드 상세(읽기 전용, 원본은 ⑤ 결과 파일)."""
        self._show_expect_buttons(None)
        self.goto_btn.setEnabled(False)
        self.app.set_selection(None)
        d = dict(n.get("detail") or {})
        if d.get("status"):
            d["status"] = ENTRY_STATUS_LABELS.get(d["status"], d["status"])
        h = "<div style='font-size:11px;color:%s'>검토 층 · %s</div><div style='font-size:15px;font-weight:700'>%s</div>" % (
            tokens.c("muted"), esc(REGISTRY.label(n["type"], n["type"])), esc(n.get("label")))
        h += "<div style='color:%s'>%s</div><p>%s" % (tokens.c("muted"), esc(n["id"]), badge("읽기 전용", "plain"))
        if n.get("draft"):
            h += " " + badge(AI_BADGE, "ai")
        if n.get("missing"):
            h += " " + badge("대상 없음(재확인) %d" % n["missing"], "warn")
        names = {"name": "이름", "here": "이 도면 구성요소", "members": "전체 구성요소", "deviation": "편차", "cause": "원인",
                 "consequence": "결과", "text": "내용", "role": "역할", "status": "상태", "risk": "위험도"}
        rows = [(names[k], esc(v)) for k, v in d.items() if k in names and v not in (None, "")]
        rows += [("대상 없음", esc(r)) for r in d.get("missing") or []]
        h += "</p>" + self._kv(rows) + "<h4>연결 목록</h4>" + self._connections(n["id"])
        h += "<p style='color:%s'>⑤ 분석 결과에서 고칩니다. 여기서는 보기만 하고 계산 뷰(V4·V5)와 알고리즘에 넣지 않습니다.</p>" \
             % tokens.c("muted")
        self.detail.setHtml(h)

    def _expect_item(self, xid):
        return next((i for i in (self.expect or {}).get("items") or [] if i["id"] == xid), None)

    def _show_expect_buttons(self, item):
        for action, b in self.expect_btns.items():
            b.setVisible(item is not None)
            b.setEnabled(bool(item) and not self.expect_error and action in item["actions"])

    def judge_expectation(self, action, reason=None, evidence=None, by=None):
        """선택한 잠재 후보에 사람 판단을 적용·저장한다. reason·evidence·by가 None이면 입력 상자로 묻는다. 반환: 저장했으면 True."""
        item = self._expect_item(self.sel[1]) if self.sel and self.sel[0] == "n" else None
        if item is None or self.expect_error or self.pg is None or action not in item["actions"]:
            return False
        by = by or self.app.reviewer_name()
        if not by:
            name, ok = QInputDialog.getText(self, "검토자 이름", "판단을 저장하려면 검토자 이름이 필요합니다(설정에 저장).")
            if not ok or not name.strip():
                return False
            self.app.set_reviewer_name(name.strip())
            by = name.strip()
        row = expect.transition(item["state"], action=action)
        if "reason" in row[4] and reason is None:
            reason, ok = QInputDialog.getText(self, expect.ACTION_LABELS[action], "%s 사유" % item["label"])
            if not ok:
                return False
        if "evidence" in row[4] and evidence is None:
            evidence, ok = QInputDialog.getText(self, expect.ACTION_LABELS[action], "근거 문서·쪽(예: 계통설계기술서 3.2절)")
            if not ok:
                return False
        pid = self.pg["project_id"]
        try:
            rec = expect.apply_action(item, action, by, reason or "", evidence or "", at=study_nodes.now_utc())
            expect.save_judgement(expect.store_path(pid), pid, rec)
        except (OSError, expect.ExpectError) as exc:
            self.app.log_error("잠재 후보 판단 저장", exc)
            self._status("판단을 저장하지 못함(사유는 툴팁)", str(exc))
            return False
        self.expect = self._expectations()
        x_nodes, x_links, x_info = screen.expectation_view(self.expect, self.graph)
        self.data["nodes"] = [n for n in self.data["nodes"] if n["layer"] != screen.EXP_LAYER] + x_nodes
        self.data["links"] = [l for l in self.data["links"] if l["layer"] != screen.EXP_LAYER] + x_links
        self.data["meta"]["expectations"] = x_info
        self.app.webview.bridge.send("updateExpectations", kg_version=self.kg["kg_version"], nodes=x_nodes,
                                     links=x_links, info=x_info)
        self._fill_status()
        self._status("%s: %s %s → %s" % (expect.ACTION_LABELS[action], item["rule_id"], item["target_tag"] or "",
                                         expect.STATES[rec["state"]]))
        self.render_node(item["id"])
        return True

    def render_expectation(self, xid):
        item = self._expect_item(xid)
        if item is None:
            return
        self._show_expect_buttons(item)
        self.goto_btn.setEnabled(False)
        self.app.set_selection(None)
        st = item["state"]
        h = "<div style='font-size:11px;color:%s'>잠재 후보 · 규칙 %s</div><div style='font-size:15px;font-weight:700'>%s</div>" % (
            tokens.c("muted"), esc(item["rule_id"]), esc(item["label"]))
        h += "<div style='color:%s'>%s</div><p>" % (tokens.c("muted"), esc(xid))
        h += badge(item["state_label"], "warn" if st in expect.GAP_STATES else "plain")
        if item["recheck"]:
            h += " " + badge(expect.RECHECK_LABEL, "warn")
        h += " " + badge("계산 제외", "plain") + " " + badge(item["basis_label"], "ai")
        target = "<a href='node:%s'>%s</a>" % (esc(item["target_entity"]), esc(item["target_tag"] or item["target"])) \
            if item["target_entity"] in self._nodes() else esc(item["target_tag"] or item["target"])
        rows = [("대상", target), ("대상 참조", esc(item["target"])), ("규칙", "%s (판 %s)" % (esc(item["rule_id"]),
                                                                                    esc(item["rule_version"]))),
                ("근거 수준", esc(item["basis_label"])), ("근거", esc(item["basis"])), ("HAZOP 쓰임", esc(item["hazop"])),
                ("자동 판정", esc(expect.STATES[item["auto_state"]]))]
        if item["note"]:
            rows.append(("비고", esc(item["note"])))
        if item["recheck"]:
            rows.append(("재확인", "이전 판단 %s — 대상·후보 내용이나 규칙 판이 바뀜" % esc(expect.previous_label(item))))
        h += "</p><h4>기대</h4>" + self._kv(rows)
        h += "<h4>찾은 후보</h4>"
        if item["found"]:
            for f in item["found"]:
                bits = [f.get("tag") or f.get("ref") or "-"]
                for k, fmt in (("relation", "%s"), ("property", "%s"), ("value", "값 %s"), ("unit", "%s"),
                               ("hops", "%s홉"), ("direction", "%s")):
                    if f.get(k) not in (None, ""):
                        bits.append(fmt % f[k])
                link = "<a href='node:%s'>%s</a>" % (esc(f["entity"]), esc(bits[0])) if f.get("entity") in self._nodes() \
                    else esc(bits[0])
                h += "<div>%s %s</div>" % (link, esc(" · ".join(str(b) for b in bits[1:])))
        else:
            h += "<div style='color:%s'>못 찾음 — 다른 도면·미등록 도면에 있을 수 있음</div>" % tokens.c("warn-ink")
        if item["rejected"]:
            h += "<div style='color:%s'>기각한 후보: %s</div>" % (tokens.c("muted"), esc(", ".join(item["rejected"])))
        j = item["judgement"]
        if j:
            h += "<h4>판단</h4>" + self._kv([(k, esc(j.get(f))) for k, f in (
                ("판단", "action"), ("판단한 사람", "by"), ("판단 시각", "at"), ("사유", "reason"), ("근거", "evidence"))
                if j.get(f)] + [("기록 상태", esc(expect.STATES.get(j.get("state"))))])
        h += "<p style='color:%s'>%s</p>" % (tokens.c("muted"), EXPECT_NOTE)
        if self.expect_error:
            h += "<p style='color:%s'>판단 파일을 읽지 못해 판단 버튼을 막음: %s</p>" % (tokens.c("err-ink"), esc(self.expect_error))
        self.detail.setHtml(h)

    def _clear_detail(self):
        self.sel = None
        self._show_expect_buttons(None)
        self.goto_btn.setEnabled(False)
        self.detail.clear()
        self.detail_stack.setCurrentWidget(self.detail_empty)

    def _nodes(self):
        return {n["id"]: n for n in self.data["nodes"]} if self.data else {}

    def on_node(self, sel):
        nid = sel.get("entity_id")
        self.app.debug_message("nodeSelected: %s" % nid)
        if self.data and nid in self._nodes():
            self.render_node(nid)

    def on_link(self, lid):
        self.app.debug_message("linkSelected: %s" % lid)
        if self.data:
            self.render_link(lid)

    def _anchor(self, url):
        s = url.toString()
        if s.startswith("node:"):
            nid = s[5:]
            self.app.webview.bridge.send("selectNode", id=nid)
            self.render_node(nid)
        elif s.startswith("link:"):
            self.render_link(s[5:])

    def _kv(self, rows):
        h = "<table cellspacing='0' cellpadding='2' width='100%'>"
        for k, v in rows:
            h += "<tr><td style='color:%s' width='92'>%s</td><td>%s</td></tr>" % (tokens.c("muted"), esc(k), v)
        return h + "</table>"

    def _val(self, n, field):
        v = n.get(field)
        if v is None or v == "":
            return "<span style='color:%s'>미확인 — %s</span>" % (
                tokens.c("warn-ink"), esc((n.get("null_reasons") or {}).get(field) or "사유 기록 없음"))
        return esc(v)

    def _source(self, src, inherited=None):
        if not src:
            return "<span style='color:%s'>∅ 근거 없음</span>" % tokens.c("err-ink")
        rows = [(k, self._val(src, f)) for k, f in (("자료 ID", "material_id"), ("등록 버전", "registration_version"),
                                                    ("문서", "document_id"), ("쪽", "page"), ("위치", "locator"))]
        if src.get("unregistered_reason"):
            rows.append(("미등록 사유", esc(src["unregistered_reason"])))
        if inherited:
            rows.append(("근거 상속", esc(inherited)))
        return self._kv(rows)

    def _member_label(self, member):
        """충돌 상대 이름: 도면 주장(graph_id#source_object_id)이면 '도면 <태그>', 지식 노드면 ID."""
        gid, sep, soid = member.partition("#")
        if not sep:
            return member
        g = next((x for x in self.graph["nodes"] if x.get("source_object_id") == soid), None) \
            if gid == self.graph["graph_id"] else None
        return "도면 %s" % ((g.get("tag") or soid) if g else member)

    def _conflict_box(self, member):
        """member(지식 노드 ID 또는 도면 주장 참조)가 든 충돌. 어느 값도 고르지 않고 모두 보인다."""
        rows = [c for c in self.kg.get("conflicts") or [] if member in (c.get("members") or ())]
        if not rows:
            return ""
        partners = sorted({m for c in rows for m in c["members"] if m != member})
        lines = []
        for c in rows:
            prop = REGISTRY.properties.get(c.get("property"))
            vals = " ≠ ".join("%s%s (%s)" % (v.get("value"), " " + v["unit"] if v.get("unit") else "(단위 미확인)",
                                              self._member_label(v["id"]))
                              for v in c["values"])
            lines.append("%s: %s" % (prop["label_ko"] if prop else c.get("item"), vals))
        return "<table width='100%%' cellpadding='6' style='border:2px solid %s;margin-top:4px'><tr><td>" \
               "<b>충돌</b>: 같은 대상·항목에 다른 값 — %s 보존(%s)<br>%s</td></tr></table>" % (
                   tokens.c("kg-conflict"), "둘 다" if len(partners) <= 1 else "모두", esc(", ".join(self._member_label(m) for m in partners)),
                   "<br>".join(esc(x) for x in lines))

    def _connections(self, nid):
        nodes = self._nodes()
        ls = [l for l in self.data["links"] if nid in (l["s"], l["t"])]
        ls.sort(key=lambda l: (STATUS_ORDER.get(l["st"], 9), l["kind"], l["id"]))
        h = ""
        for l in ls:
            other = l["t"] if l["s"] == nid else l["s"]
            o = nodes.get(other, {})
            h += "<div><a href='link:%s'>%s</a> → <a href='node:%s'>%s</a> %s</div>" % (
                esc(l["id"]), esc(l["kind"]), esc(other), esc(o.get("label") or other),
                badge(STATUS_NAMES.get(l["st"], l["st"]), "plain" if l["st"] == "confirmed" else "warn"))
        return h or "<span style='color:%s'>연결 없음 — '해당 없음'이 아니라 '지식 입력 미확인'</span>" % tokens.c("warn-ink")

    def _algo_section(self, nid):
        a = self.data["algo"]
        if not a["enabled"]:
            return "<p style='color:%s'>알고리즘 비활성: %s</p>" % (tokens.c("warn-ink"), esc(a["reason"]))
        h = ""
        a1 = a.get("A1") or {}
        if a1.get("active"):
            if nid == a1["start"]:
                h += "<div>A1: 시작점 (구간 %s)</div>" % esc(a1["region_id"])
            elif nid in a1["reached"]:
                r = a1["reached"][nid]
                h += "<div>A1: %s · 깊이 %s%s · 경유 밸브 %s</div>" % (
                    esc(A1_NAMES.get(r["dir"], r["dir"])), esc(r["depth"]),
                    " · <b>정상 유로 아님(NC·LC 경유)</b>" if r["nnf"] else "", esc(r["valve"]))
            elif nid in a1["members"]:
                h += "<div>A1: 구간 멤버, 미도달</div>"
            else:
                h += "<div>A1: 대상 아님(시작 %s)</div>" % esc(a1["start"])
            if nid in (a1.get("truncated") or {}):
                h += "<div>A1: <b>%s</b>(탐색이 여기서 멈춤)</div>" % esc(a1["truncated"][nid])
        else:
            h += "<div>A1 비활성: %s</div>" % esc(a1.get("reason"))
        a2 = a.get("A2") or {}
        if nid in a2.get("orphans", {}):
            h += "<div>A2: <b>고아</b> — %s</div>" % esc(a2["orphans"][nid])
        if nid in a2.get("no_input", []) or nid in a2.get("no_input_cont", []):
            h += "<div style='color:%s'>A2: 지식 입력 없음%s — '해당 없음'이 아님</div>" % (
                tokens.c("warn-ink"), "(도면 연결점)" if nid in a2.get("no_input_cont", []) else "")
        if nid in a2.get("gaps", {}):
            h += "<div>A2: <b>근거 공백</b>(자료 요청 메모 후보) — 언급 %s</div>" % esc(", ".join(a2["gaps"][nid]))
        deg = (a.get("A3") or {}).get(nid)
        h += "<div>A3 연결 수(V5): %s</div>" % ("계산 제외(V5 밖)" if deg is None else deg)
        h += "<div style='color:%s'>연결·도달은 인과관계를 입증하지 않음. HAZOP 근거로 쓰려면 사람 확인 필요</div>" % tokens.c("muted")
        return h

    def render_node(self, nid):
        self.sel = ("n", nid)
        self.side_tabs.setCurrentIndex(0)
        self.detail_stack.setCurrentWidget(self.detail)
        n = self._nodes()[nid]
        if n["layer"] == screen.EXP_LAYER:
            self.render_expectation(nid)
            return
        if n["layer"] == screen.STUDY_LAYER:
            self.render_study(n)
            return
        self._show_expect_buttons(None)
        # P&ID 노드는 도면 구성요소와 같은 entity_id(관련 항목 패널이 따라감). 지식 노드는 도면 구성요소가 아님.
        self.app.set_selection({"kind": "component", "drawing": self.graph_dir, "entity_id": nid}
                               if n["layer"] == "pid" else None)
        h = "<div style='font-size:11px;color:%s'>%s</div><div style='font-size:15px;font-weight:700'>%s</div>" % (
            tokens.c("muted"), esc(TYPE_NAMES.get(n["type"], n["type"])), esc(n.get("label")))
        h += "<div style='color:%s'>%s</div><p>" % (tokens.c("muted"), esc(nid))
        if n["layer"] == "kn":
            kn = next(k for k in self.kg["nodes"] if k["id"] == nid)
            ks = kn.get("knowledge_status")
            h += badge("확인됨 confirmed", "human") if ks == "confirmed" else badge({"unknown": "미확인", "hypothesis": "가설"}
                                                                                  .get(ks, ks), "warn")
            if not n["v5"]:
                h += " " + badge("계산 제외", "plain")
            if not kn.get("has_source"):
                h += " " + badge("∅ 근거 없음", "err")
            if kn.get("conflict_with") or kn.get("conflict_with_pid"):
                h += " " + badge("≠ 충돌", "err")
            if auto_extracted(kn):
                h += " " + badge(AUTO_BADGE, "ai")
            if build.origin_of(kn) == "ai_draft":
                h += " " + badge(AI_BADGE, "ai")
            h += "</p><h4>내용</h4>"
            fields = [("이름", "name"), ("원문", "text"), ("항목", "item"), ("값", "value"), ("단위", "unit"),
                      ("압력 기준", "pressure_basis"), ("운전 모드", "operating_mode")]
            # 값이 있는 칸만 보이고, 설정치·운전조건의 값·단위·압력 기준·운전 모드는 비어 있어도 "미확인 — 사유"로 보인다
            always = ("value", "unit", "pressure_basis", "operating_mode") if n["type"] in ("setpoint", "condition") else ()
            rows = [(k, self._val(kn, f)) for k, f in fields if kn.get(f) not in (None, "") or f in always]
            rows += [("방법", esc(kn.get("method"))), ("작성자", esc(kn.get("author")))]
            if kn.get("extractor"):
                rows.append(("추출기", esc(kn["extractor"])))
            if kn.get("reason"):
                rows.append(("사유", esc(kn["reason"])))
            if kn.get("compute_view", {}).get("excluded_reasons"):
                rows.append(("계산 제외 사유", esc(", ".join(kn["compute_view"]["excluded_reasons"]))))
            h += self._kv(rows)
            h += self._conflict_box(nid)
            h += "<h4>근거(출처)</h4>" + self._source(kn.get("source"))
            self.goto_btn.setEnabled(False)
        else:
            g = next(x for x in self.graph["nodes"] if x["entity_id"] == nid)
            at = g.get("attributes") or {}
            rows = [("kind", esc(g.get("kind"))), ("도면", esc(self.graph_dir)), ("객체 ID", esc(g.get("source_object_id"))),
                    ("local_id", esc(g.get("local_id")))]
            if g.get("category") == "valve":
                rows += [("정상 위치", self._val(at, "normal_position")), ("고장 위치", self._val(at, "fail_position"))]
            if g.get("node_type") == "pipe_segment":
                fd = g.get("flow_direction")
                rows.append(("흐름 방향", "%s → %s" % (esc(fd.get("from")), esc(fd.get("to"))) if fd else
                             "<span style='color:%s'>미확인(화살표 없음)</span>" % tokens.c("warn-ink")))
            if g.get("kind") == "continuation":
                rows.append(("도면 연결점", "이어지는 도면(이 그래프 밖)"))
            edited = node_origin(g) == "human_edit"
            if edited:
                he = g.get("human_edit") or {}
                rows.append(("사람 수정", esc(" · ".join(OP_LABELS.get(o, o) for o in he.get("ops") or []) or "수정 기록 있음")
                             + (" (%s)" % esc(he["by"]) if he.get("by") else "")))
            conflict = self._conflict_box("%s#%s" % (self.graph["graph_id"], g.get("source_object_id")))
            h += badge("P&ID 레이어", "plain") + (" " + badge(HUMAN_EDIT_BADGE, "human") if edited else "")
            h += (" " + badge("≠ 충돌", "err") if conflict else "")
            h += "</p><h4>속성</h4>" + self._kv(rows) + conflict
            self.goto_btn.setEnabled(bool(g.get("local_id")))
        h += "<h4>알고리즘</h4>" + self._algo_section(nid)
        h += "<h4>연결 목록</h4>" + self._connections(nid)
        if n["layer"] == "kn":
            h += "<p style='color:%s'>근거 문서·쪽은 위 출처 참고(문서 원문 열기 기능 없음)</p>" % tokens.c("muted")
        self.detail.setHtml(h)

    def render_link(self, lid):
        self.sel = ("l", lid)
        self._show_expect_buttons(None)
        self.goto_btn.setEnabled(False)
        d = next((l for l in self.data["links"] if l["id"] == lid), None)
        if d is None:
            return
        self.side_tabs.setCurrentIndex(0)
        self.detail_stack.setCurrentWidget(self.detail)
        h = "<div style='font-size:11px;color:%s'>관계</div><div style='font-size:15px;font-weight:700'>%s</div>" \
            "<div style='color:%s'>%s</div>" % (tokens.c("muted"), esc(d["kind"]), tokens.c("muted"), esc(lid))
        h += self._kv([("시작", "<a href='node:%s'>%s</a>" % (esc(d["s"]), esc(d["s"]))),
                       ("끝", "<a href='node:%s'>%s</a>" % (esc(d["t"]), esc(d["t"]))),
                       ("표시 상태", esc(STATUS_NAMES.get(d["st"], d["st"])))])
        if d["st"] == "candidate" and d["id"].startswith("cand:"):  # link_candidates.csv 표시 전용 후보
            h += "<h4>연결 후보</h4>" + self._kv([
                ("방법", esc(d.get("method"))), ("점수", esc(d.get("conf"))), ("모호", "예" if d.get("amb") else "아니오"),
                ("일치 원문", esc(d.get("match"))), ("후보 키", esc(d.get("key")))])
            h += "<p style='color:%s'>자동 생성 후보 — 계산 제외. 판단은 link_candidates.csv에서(점수는 정렬용, 확인을 대신하지 않음)</p>" \
                 % tokens.c("warn-ink")
        elif d["layer"] == screen.EXP_LAYER:
            h += "<p>잠재 후보 관계(%s) — 사실 아님, 계산 제외. 상태는 잠재 후보 노드를 눌러 바꿉니다.</p>" % esc(
                REGISTRY.relations[d["kind"]]["label_ko"])
        elif d["layer"] == screen.STUDY_LAYER:
            h += "<p>검토 층 관계(%s) — ⑤ 결과 파일에서 읽은 투영(읽기 전용), 계산 제외.</p>" % esc(
                REGISTRY.relations[d["kind"]]["label_ko"])
        elif d["layer"] == "kn":
            kl = next(l for l in self.kg["links"] if l["id"] == lid)
            if auto_extracted(kl):
                h += "<p>%s</p>" % badge(AUTO_BADGE, "ai")
            if build.origin_of(kl) == "ai_draft":
                h += "<p>%s</p>" % badge(AI_BADGE, "ai")
            rows = [("link_status", esc(kl.get("link_status"))), ("knowledge_status", esc(kl.get("knowledge_status"))),
                    ("방법", esc(kl.get("method"))), ("확인자", esc(kl.get("reviewed_by"))),
                    ("확인일", esc(kl.get("reviewed_at")))]
            if kl.get("extractor"):
                rows.append(("추출기", esc(kl["extractor"])))
            if kl.get("reason"):
                rows.append(("사유", esc(kl["reason"])))
            if kl.get("compute_view", {}).get("excluded_reasons"):
                rows.append(("계산 제외 사유", esc(", ".join(kl["compute_view"]["excluded_reasons"]))))
            if kl.get("recheck"):
                rows.append(("재확인", esc(kl["recheck"])))
            h += "<h4>상태</h4>" + self._kv(rows)
            m = kl.get("mention")
            if m:
                h += "<h4>언급 일치</h4>" + self._kv([("조각", esc(m.get("chunk_id"))),
                                                   ("위치", "%s–%s" % (esc(m.get("match_start")), esc(m.get("match_end")))),
                                                   ("원문 해시", esc((m.get("text_sha256") or "")[:12] + "…"))])
            h += "<h4>근거(출처)</h4>" + self._source(kl.get("source"), kl.get("source_inherited_from"))
        else:
            h += "<p>P&ID 레이어 관계(도면에서 추출)</p>"
        self.detail.setHtml(h)

    # ------------------------------------------------------------ 동작
    def show_in_drawing(self):
        """② 도면·그래프로 전환하고 기존 focus 메시지로 해당 객체를 강조한다(배관 구간은 구간 local_id로 지정)."""
        if not self.sel or self.sel[0] != "n" or not self.graph:
            return
        g = next((x for x in self.graph["nodes"] if x["entity_id"] == self.sel[1]), None)
        if g is None or not g.get("local_id"):
            return
        self.app.go(1)
        viewer = self.app.screens[1]
        viewer.select_drawing(self.graph_dir)
        if viewer.combo.currentText() != self.graph_dir:
            self._status("도면에서 보기 불가(자세한 사유는 툴팁)",
                         "② 도면 목록에 %s 추출 결과가 없어 도면에서 보일 수 없음" % self.graph_dir)
            return
        self.app.webview.set_view("drawing")
        self.app.webview.focus(g["local_id"])

    def _status(self, short, full=None):
        """상태줄은 짧게, 전체 문장은 툴팁으로(긴 문장이 창 최소 폭을 늘리지 않게)."""
        self.app.status_message(short)
        self.app.msg_label.setToolTip(full or "")

    def on_algorithm(self, req):
        """웹 runAlgorithm 요청: A1만(시작점을 바꿔 다시 계산). 결과는 algorithmResult로 돌려준다."""
        if not self.data or req.get("algorithm") != "A1":
            return
        if req.get("start") not in self._nodes():  # 현재 그래프에 없는 ID는 처리하지 않음(웹 내용은 신뢰하지 않음)
            self.app.debug_message("runAlgorithm 무시: 현재 그래프에 없는 ID")
            return
        try:
            full, compact = screen.run_a1(self.kg, self.graph, self.regions, req["start"])
        except algo.AlgoError as exc:
            self._status("A1 실행 안 함(사유는 툴팁)", "A1 실행 안 함: %s" % exc)
            return
        self.a1_full = full
        self.data["algo"]["A1"] = compact
        self.app.webview.bridge.send("algorithmResult", algorithm="A1", start=req["start"],
                                     kg_version=self.kg["kg_version"], result=compact)
        self._status("A1 계산: 시작 %s — %s" % (req["start"], "도달 %d" % len(compact["reached"])
                                               if compact["active"] else "비활성(사유는 툴팁)"),
                     None if compact["active"] else compact["reason"])
        if self.sel and self.sel[0] == "n":
            self.render_node(self.sel[1])

    # ------------------------------------------------------------ 도면 경계(프로젝트 그래프)
    def _project_panel(self):
        """프로젝트 그래프에서 도면 경계를 넘는 경로 찾기와 도면 연결 표. 도면 필터는 둘 다에 적용한다."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        self.project_note = QLabel("")
        self.project_note.setObjectName("muted")
        self.project_note.setWordWrap(True)
        v.addWidget(self.project_note)
        g = QGridLayout()
        g.setSpacing(4)
        g.addWidget(QLabel("시작"), 0, 0)
        self.path_from = QLineEdit()
        self.path_from.setPlaceholderText("태그 또는 구성요소 ID")
        self.path_from.setAccessibleName("경로 시작 태그")
        g.addWidget(self.path_from, 0, 1)
        g.addWidget(QLabel("끝"), 1, 0)
        self.path_to = QLineEdit()
        self.path_to.setPlaceholderText("태그 또는 구성요소 ID")
        self.path_to.setAccessibleName("경로 끝 태그")
        g.addWidget(self.path_to, 1, 1)
        self.path_btn = QPushButton("찾기")
        self.path_btn.clicked.connect(self.find_path)
        self.path_from.returnPressed.connect(self.find_path)
        self.path_to.returnPressed.connect(self.find_path)
        g.addWidget(self.path_btn, 0, 2, 2, 1)
        g.addWidget(QLabel("도면"), 2, 0)
        self.drawing_filter = QComboBox()
        self.drawing_filter.setAccessibleName("도면 필터")
        self.drawing_filter.currentIndexChanged.connect(lambda _: self._fill_project_lists())
        g.addWidget(self.drawing_filter, 2, 1, 1, 2)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        self.path_summary = QLabel("두 태그를 넣고 찾기를 누르면 도면 경계를 넘는 물리 배관 경로가 나옵니다.")
        self.path_summary.setWordWrap(True)
        v.addWidget(self.path_summary)
        self.path_list = QListWidget()
        self.path_list.setAccessibleName("경로 단계")
        v.addWidget(self.path_list, 2)
        sec = QLabel("도면 연결")
        sec.setObjectName("section")
        v.addWidget(sec)
        self.link_table = QTableWidget(0, 5)
        self.link_table.setAccessibleName("도면 연결 표")
        self.link_table.setHorizontalHeaderLabels(["출발", "도착", "배관", "상태", "사유"])
        self.link_table.verticalHeader().hide()
        self.link_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.link_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.link_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        v.addWidget(self.link_table, 3)
        return box

    def _project_id(self):
        """③의 프로젝트: 고른 지식그래프의 프로젝트, 없으면 지금 도면의 프로젝트, 그것도 없으면 샘플 프로젝트."""
        if self.kg and self.kg.get("project_id"):
            return self.kg["project_id"]
        ctx = project_ctx.load(self.app.drawing) if getattr(self.app, "drawing", None) else None
        return ctx.project_id if ctx else project.UNREGISTERED_PROJECT

    def _load_project(self):
        """프로젝트 그래프를 읽고(같은 프로젝트면 화면 진입 때만 다시) 도면 필터·목록을 채운다."""
        pid = self._project_id()
        if self.pg is not None and self.pg.get("project_id") == pid:
            return
        try:
            self.pg, self.pg_error = project_ctx.project_graph(pid), None
        except (OSError, ValueError, KeyError) as exc:
            self.pg, self.pg_error = None, "프로젝트 그래프를 만들 수 없음: %s" % exc
        self.path_steps = None
        cur = self.drawing_filter.currentData()
        self.drawing_filter.blockSignals(True)
        self.drawing_filter.clear()
        self.drawing_filter.addItem("모든 도면", None)
        for s in (self.pg or {}).get("sheets") or []:
            self.drawing_filter.addItem(s["drawing_number"], s["drawing_number"])
        self.drawing_filter.setCurrentIndex(max(self.drawing_filter.findData(cur), 0))
        self.drawing_filter.blockSignals(False)
        if self.pg:
            linked = sum(1 for l in self.pg["sheet_links"] if l["status"] == project.LINKED)
            self.project_note.setText("프로젝트 %s · 도면 %d장 · 도면 연결 %d · 미연결 %d" % (
                pid, len(self.pg["sheets"]), linked, len(self.pg["sheet_links"]) - linked))
        else:
            self.project_note.setText(self.pg_error)
        for w in (self.path_from, self.path_to, self.path_btn, self.drawing_filter):
            w.setEnabled(self.pg is not None)
        self._fill_project_lists()

    def find_path(self):
        """두 태그 사이 물리 경로(프로젝트 그래프). 대상이 없거나 여럿이면 사유를 보인다."""
        a, b = self.path_from.text().strip(), self.path_to.text().strip()
        if not self.pg or not a or not b:
            self.path_summary.setText("시작과 끝 태그를 모두 넣으세요.")
            return
        try:
            self.path_steps = screen.cross_path(self.pg, a, b)
        except QueryError as exc:
            self.path_steps = None
            self.path_summary.setText("찾을 수 없음: %s" % exc)
        else:
            if self.path_steps is None:
                self.path_summary.setText("%s와 %s 사이에 물리 배관 경로가 없습니다(도면 연결이 끊겼거나 신호 연결만 있음)."
                                          % (a, b))
            else:
                cross = sum(1 for s in self.path_steps if s["kind"] == "boundary")
                self.path_summary.setText("구성요소 %d개 · 도면 경계 %d번 넘음 · 흐름 방향 무시. %s" % (
                    len(self.path_steps) - cross, cross, VALVE_POSITION_NOTE))
        self._fill_project_lists()

    def _fill_project_lists(self):
        dwg = self.drawing_filter.currentData()
        self.path_list.clear()
        for s in screen.filter_by_drawing(self.path_steps or [], dwg):
            it = QListWidgetItem(s["text"])
            if s["kind"] == "boundary":
                it.setForeground(QBrush(QColor(tokens.c("ui"))))
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.path_list.addItem(it)
        rows = screen.filter_by_drawing(screen.sheet_link_rows(self.pg), dwg) if self.pg else []
        self.link_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = ("%s · %s" % (r["from_drawing"], r["from_label"]),
                     "%s · %s" % (r["to_drawing"] or "-", r["to_label"] or "짝 없음"), r["line_no"] or "-",
                     ("연결" if r["status"] == project.LINKED else "미연결")
                     + (" · 사람 지정" if r["origin"] == "manual" else ""), r["reason"] or "")
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.link_table.setItem(i, j, item)
