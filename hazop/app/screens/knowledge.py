"""③ 지식그래프 (기획서/인터페이스.md §3.5, 그래프활용.md §5, 디자인/지식그래프화면.md §4·§5).

- 도구줄(Qt): 지식그래프·도면 선택, kg_version·검증·graph_version·충돌·재확인·계산 제외·알고리즘 칩
- 띠(Qt): blocked(차단 목록, 직전 passed 버전 보기), 알고리즘 비활성 사유, S1 노드 수 상한 초과, 재확인 필요
- 캔버스(웹, 공유 웹뷰): hazop/kg/screen_template.html 셸에 loadKnowledge로 데이터를 넘긴다. 좌측 필터도 웹 안에 있다.
- 우측 상세(Qt): 클릭한 노드·관계의 속성·근거·A1~A3·연결 목록, P&ID 노드면 "도면에서 보기"(② 전환 + focus)
- 계산은 Python(hazop.kg.screen → hazop.kg.algo). runAlgorithm(A1) 요청을 받아 algorithmResult로 돌려준다.
"""

import os

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QStackedWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from hazop import paths
from hazop.app import data as app_data
from hazop.app import tokens
from hazop.app.widgets import VALIDATION_LABELS, Banner, Chip, badge, empty_label, esc
from hazop.kg import algo, auto, build, screen

APP_SHELL = "kg-screen.html"  # 출력/뷰어/ 아래 앱 셸(데이터 없음, loadKnowledge로 받음)
TYPE_NAMES = {"equipment": "설비", "valve": "밸브", "instrument": "계장", "piping_element": "배관 요소",
              "pipe_segment": "배관 구간", "unclassified": "미분류", "document": "문서", "doc_chunk": "문서 조각",
              "requirement": "요건", "setpoint": "설정치", "condition": "운전조건·설계값", "analysis_case": "해석 사례"}
STATUS_ORDER = {"confirmed": 0, "recheck": 1, "excluded": 2, "candidate": 3}
STATUS_NAMES = {"confirmed": "확인", "recheck": "재확인 필요", "excluded": "계산 제외", "candidate": "후보"}
A1_NAMES = {"downstream": "하류", "upstream": "상류", "mixed": "혼합", "unknown": "방향 미확인", "adjacent": "인접 구간",
            "not_applicable": "방향 해당 없음"}
EMPTY_TEXT = ("지식그래프가 없습니다.\n① 자료 등록에서 P&ID 도면(drawio·PDF)을 등록하고 추출하면 지식그래프가 자동으로 "
              "만들어집니다.\n설계 문서 PDF를 등록하면 설정치·운전조건·요건을 자동 추출해 '자동 추출 · 사람 확인 전'으로 "
              "더합니다.")
AUTO_BADGE = "자동 추출 · 사람 확인 전"


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


def kg_root_dir():
    return paths.output_root("지식그래프")


def standalone_path(kg, graph_id):
    """브라우저 단독 모드 HTML: 출력/지식그래프/<kg_id>/screen/<kg_version>/<graph_id>.html."""
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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)
        bar_w = QWidget()
        bar = FlowLayout(bar_w)
        bar.addWidget(QLabel("지식그래프"))
        self.kg_combo = QComboBox()
        self.kg_combo.setMinimumWidth(150)
        self.kg_combo.currentIndexChanged.connect(lambda _: self._load())
        bar.addWidget(self.kg_combo)
        bar.addWidget(QLabel("도면"))
        self.graph_combo = QComboBox()
        self.graph_combo.setMinimumWidth(140)
        self.graph_combo.currentIndexChanged.connect(lambda _: self._load(keep_kg=True))
        bar.addWidget(self.graph_combo)
        self.chips = {k: Chip() for k in ("ver", "valid", "graph", "conf", "recheck", "excl", "algo")}
        for c in self.chips.values():
            bar.addWidget(c)
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
        dl.addWidget(self.detail, 1)
        foot = QHBoxLayout()
        self.goto_btn = QPushButton("도면에서 보기")
        self.goto_btn.setEnabled(False)
        self.goto_btn.clicked.connect(self.show_in_drawing)
        foot.addWidget(self.goto_btn)
        foot.addStretch(1)
        dl.addLayout(foot)
        self.detail_collapsed = False
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
                "run": "이전 버전" if self.showing_prev else None}  # kg_version은 도구줄 칩에 있음(헤더 폭 1366 유지)

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
        for w in (self.detail, self.goto_btn, self.detail_title):
            w.setVisible(not self.detail_collapsed)
        self.detail_toggle.setText("펴기" if self.detail_collapsed else "접기")
        self._size_detail()

    def _build_missing(self):
        """등록·추출 결과는 있는데 지식그래프가 아직 없는 프로젝트를 빌드한다(실패는 기록만, 화면은 계속)."""
        try:
            pids = auto.project_ids(paths.output_root("그래프"), app_data.doc_root())
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
        self._load()

    # ------------------------------------------------------------ 읽기
    def _set_empty(self, text):
        self.kg = self.graph = self.data = None
        self.stack.setCurrentIndex(0)
        self.empty.setText(text)
        for c in self.chips.values():
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
            found = screen.graph_for_ref(paths.output_root("그래프"), gid, ref_ver)
            if found is None:
                self._set_empty("지식그래프 %s가 참조한 도면 그래프가 없습니다: %s. ①에서 추출·그래프를 만드세요."
                                % (kg.get("kg_id"), ", ".join(r["graph_id"] for r in refs)))
                self.kg = kg
                return
            self.graph_dir, self.graph = found
            self.regions = screen.load_regions(paths.work_path("데이터", "구간"))
            cands = screen.read_candidates(paths.safe_join(paths.work_path("데이터", "지식"), kg.get("project_id") or ""))
            self.data = screen.screen_data(kg, self.graph, self.regions, cands,
                                           standalone_note="이전 버전" if self.showing_prev else None)
            self.a1_full = None
            shell = screen.write_html(paths.output_root("뷰어", APP_SHELL), screen.build_html(None))
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
        for c in ch.values():
            c.show()
        ch["ver"].set_state("kg_version %s%s" % (m["kg_version"], " · 이전 버전" if self.showing_prev else ""))
        st = m["status"]
        ch["valid"].set_state("검증 %s · 차단 %d · 미확인 %d" % (VALIDATION_LABELS.get(st, st),
                                                            m["blockers"], m["unknowns"]),
                              "passed" if st == "passed" else "blocked")
        same = m["graph_ref_version"] == m["graph_version"]
        ch["graph"].set_state("graph_version %s%s" % (m["graph_version"], "" if same else " (지식그래프 기준 %s)"
                                                      % m["graph_ref_version"]), "" if same else "warn")
        ch["conf"].set_state("충돌 %d" % m["conflicts"], "warn" if m["conflicts"] else "")
        ch["recheck"].set_state("재확인 필요 %d" % m["recheck"], "warn")
        ch["recheck"].setVisible(m["recheck"] > 0)
        c = m["candidates"]
        ch["excl"].set_state("계산 제외 노드 %d · 관계 %d · 후보 %s" % (m["excluded_nodes"], m["excluded_links"],
                                                                 c["shown"] if c["file"] else "파일 없음"))
        ch["algo"].set_state("알고리즘: 이 kg_version으로 계산" if a["enabled"] else "알고리즘 비활성",
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
        self.recheck_band.set_messages("재확인 필요 %d건 — 계산에서 빠짐. 후보 CSV에서 다시 판단한 뒤 반영하세요" % len(rk)
                                       if rk else None, ["%s: %s" % (l["id"], l.get("recheck")) for l in rk])

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
    def _clear_detail(self):
        self.sel = None
        self.goto_btn.setEnabled(False)
        h = ("<p style='color:%s'>노드나 관계를 클릭하면 속성·근거·연결 목록이 여기에 나옵니다. "
             "표시·배치는 근거가 아닙니다. 근거는 이 패널의 출처입니다.</p>" % tokens.c("muted"))
        if getattr(self, "standalone", None):
            h += "<p style='color:%s'>브라우저 단독 모드 HTML(미리 계산된 결과만): %s</p>" % (tokens.c("muted"),
                                                                                esc(self.standalone))
        self.detail.setHtml(h)

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
        n = self._nodes()[nid]
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
            if kn.get("conflict_with"):
                h += " " + badge("≠ 충돌", "err")
            if auto_extracted(kn):
                h += " " + badge(AUTO_BADGE, "ai")
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
            if kn.get("conflict_with"):
                h += "<table width='100%%' cellpadding='6' style='border:2px solid %s;margin-top:4px'><tr><td>" \
                     "<b>충돌</b>: 같은 대상·항목에 다른 값 — 둘 다 보존(%s)</td></tr></table>" % (
                         tokens.c("kg-conflict"), esc(", ".join(kn["conflict_with"])))
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
            h += badge("P&ID 레이어", "plain") + "</p><h4>속성</h4>" + self._kv(rows)
            self.goto_btn.setEnabled(bool(g.get("local_id")))
        h += "<h4>알고리즘</h4>" + self._algo_section(nid)
        h += "<h4>연결 목록</h4>" + self._connections(nid)
        if n["layer"] == "kn":
            h += "<p style='color:%s'>근거 문서·쪽은 위 출처 참고(문서 원문 열기 기능 없음)</p>" % tokens.c("muted")
        self.detail.setHtml(h)

    def render_link(self, lid):
        self.sel = ("l", lid)
        self.goto_btn.setEnabled(False)
        d = next((l for l in self.data["links"] if l["id"] == lid), None)
        if d is None:
            return
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
        elif d["layer"] == "kn":
            kl = next(l for l in self.kg["links"] if l["id"] == lid)
            if auto_extracted(kl):
                h += "<p>%s</p>" % badge(AUTO_BADGE, "ai")
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
