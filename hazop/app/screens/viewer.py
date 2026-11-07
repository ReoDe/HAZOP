"""② 도면·그래프 조회 (기획서/인터페이스.md §3.2). 웹뷰는 기존 뷰어를 쓰되 'P&ID 구조'(그래프) 탭은 숨긴다
(결정로그 2026-11-06: '그래프'는 지식그래프만 뜻함. 내부 그래프 데이터는 지식그래프 재료로 계속 만든다).

편집 모드(drawing-edit-spec.md '화면'): 사람이 도면 위에서 추출 결과를 고친다. 원본 추출은 그대로 두고 수정 기록(ops)만
쌓는다. 웹뷰는 클릭 좌표·맞은 항목(editPick)만 보내고, 값 편집·실행 취소·저장은 오른쪽 Qt 편집 패널이 맡는다.
EditSession(작업 중 ops·실행 취소/다시 실행)과 tool_pick(여러 번 클릭하는 도구의 상태 기계)은 웹뷰 없이 검사할 수 있다."""

from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from hazop.app import data, tokens
from hazop.app.widgets import VALIDATION_LABELS, Banner, Chip, empty_label, esc, kst_text
from hazop.extract import corrections
from hazop.extract.rules import KIND_CATEGORY

CATEGORY_LABELS = {"equipment": "설비", "valve": "밸브", "instrument": "계기", "piping_element": "배관 요소"}
KIND_LABELS = {
    "reactor_vessel": "원자로 용기", "steam_generator": "증기발생기", "pressurizer": "가압기", "pump": "펌프",
    "vessel": "용기", "tank": "탱크", "heat_exchanger": "열교환기", "turbine": "터빈", "condenser": "복수기",
    "filter": "필터", "demineralizer": "탈염기", "orifice": "오리피스", "vent": "벤트",
    "manual_valve": "수동 밸브", "motor_operated_valve": "전동 밸브(MOV)", "control_valve": "제어 밸브",
    "check_valve": "체크 밸브", "isolation_valve": "격리 밸브", "psv": "안전 밸브(PSV)",
    "transmitter": "전송기", "controller": "제어기", "indicator": "지시계", "temperature_element": "온도 검출기",
    "tee": "티", "pipe_cap": "배관 캡", "continuation": "도면 연결",
}
# (관계 종류, 화면 이름, 새 연결의 line_type)
RELATION_KINDS = (("physical_connection", "공정 배관", "process"), ("signal_connection", "계장 신호", "signal"),
                  ("measurement_connection", "계측 연결", "instrument_tap"))
RELATION_LABELS = {k: label for k, label, _ in RELATION_KINDS}
TOOLS = (("select", "선택"), ("add_node", "기기 추가"), ("connect", "연결 추가"), ("endpoint", "끝점 잇기"),
         ("path", "경로 그리기"))
OP_LABELS = {"set_tag": "태그", "set_kind": "종류", "set_flow": "흐름 방향", "set_endpoint": "끝점 잇기",
             "set_path": "경로 다시 그리기", "confirm": "미확인 확정", "add_node": "기기 추가", "delete_node": "기기 삭제",
             "add_relation": "연결 추가", "delete_relation": "연결 삭제"}
NEW_NODE_SIZE = 40  # 기기 추가: 클릭한 점을 가운데로 하는 정사각형(도면 좌표)
HINTS = {
    "select": "도면에서 항목을 클릭해 고르세요.",
    "add_node": "기기를 놓을 자리를 클릭하세요.",
    "connect": "연결을 시작할 기기를 클릭하세요.",
    "connect_b": "연결할 다른 기기를 클릭하세요.",
    "endpoint": "바꿀 끝(source·target)을 고르세요.",
    "endpoint_node": "그 끝을 이을 기기를 클릭하세요.",
    "path": "경로 점을 차례로 클릭한 뒤 '경로 완료'를 누르세요(첫·끝 점이 양 끝이 됨).",
}


def kind_label(kind):
    cat = KIND_CATEGORY.get(kind)
    return "%s · %s" % (CATEGORY_LABELS.get(cat, "미분류"), KIND_LABELS.get(kind, kind or "종류 없음"))


def index_items(extraction):
    """local_id → ("node" | "relation", 항목). 미해결 커넥터도 관계로 본다."""
    out = {n["local_id"]: ("node", n) for n in extraction.get("nodes") or []}
    for r in (extraction.get("relations") or []) + (extraction.get("unresolved_connectors") or []):
        out[r["local_id"]] = ("relation", r)
    return out


def unknowns_of(extraction, local_id):
    return [u for u in (extraction.get("validation") or {}).get("unknowns") or [] if u.get("target") == local_id]


class EditSession:
    """작업 중 수정 기록. ops는 적용 순서대로, saved는 마지막 저장본. 실행 취소·다시 실행은 ops 목록 전체의 사본을 쌓는다."""

    def __init__(self, ops=()):
        self.ops = list(ops)
        self.saved = list(ops)
        self.undo_stack, self.redo_stack = [], []

    @property
    def dirty(self):
        return self.ops != self.saved

    def change(self, ops):
        self.undo_stack.append(self.ops)
        self.ops = list(ops)
        self.redo_stack = []

    def add(self, op):
        self.change(self.ops + [op])

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.ops)
        self.ops = self.undo_stack.pop()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.ops)
        self.ops = self.redo_stack.pop()
        return True

    def revert(self):
        """저장본으로 되돌리기(이것도 실행 취소할 수 있다)."""
        if not self.dirty:
            return False
        self.change(self.saved)
        return True

    def mark_saved(self):
        self.saved = list(self.ops)


@dataclass(frozen=True)
class ToolState:
    """여러 번 클릭하는 도구의 진행 상태. connect: first(A 기기) → B 기기. endpoint: end 선택 → 기기.
    path: points를 모으다가 finish_path. endpoint·path는 relation(고른 관계)에 대해 동작한다."""
    tool: str = "select"
    first: str = None
    end: str = None
    relation: str = None
    points: tuple = ()

    @property
    def hint(self):
        if self.tool == "connect" and self.first:
            return HINTS["connect_b"]
        if self.tool == "endpoint" and self.end:
            return HINTS["endpoint_node"]
        return HINTS[self.tool]


def start_tool(tool, selected, items):
    """도구 고르기 → (ToolState, 안내 문구). 끝점 잇기·경로 그리기는 연결(관계)을 먼저 골라야 한다."""
    if tool in ("endpoint", "path"):
        hit = items.get(selected)
        if not hit or hit[0] != "relation":
            return ToolState(), "먼저 도면에서 연결(배관·신호선)을 고르세요."
        st = ToolState(tool, relation=selected)
    else:
        st = ToolState(tool)
    return st, st.hint


def choose_end(state, end):
    if state.tool != "endpoint" or end not in ("source", "target"):
        return state, state.hint
    st = replace(state, end=end)
    return st, st.hint


def _sid(items, local_id):
    return items[local_id][1]["source_object_id"]


def tool_pick(state, pick, items, defaults):
    """도면 클릭 하나 → (새 ToolState, 요청 {"op","target","value"} 또는 None, 안내 문구).
    pick = {"point": [x, y] 도면 좌표, "local_id"}. defaults = {"kind", "tag", "relation_kind"}. 대상은 source_object_id."""
    hit = items.get(pick.get("local_id"))
    node = pick["local_id"] if hit and hit[0] == "node" else None
    x, y = pick["point"]
    if state.tool == "add_node":
        kind = defaults["kind"]
        h = NEW_NODE_SIZE
        req = {"op": "add_node", "target": None,
               "value": {"category": KIND_CATEGORY.get(kind, "equipment"), "kind": kind,
                         "tag": (defaults.get("tag") or "").strip(), "bbox": [x - h / 2, y - h / 2, h, h]}}
        return state, req, state.hint
    if state.tool == "connect":
        if not node:
            return state, None, "기기를 클릭하세요(빈 곳·연결선은 고를 수 없음)."
        if not state.first:
            st = replace(state, first=node)
            return st, None, st.hint
        if node == state.first:
            return state, None, "같은 기기입니다. 다른 기기를 클릭하세요."
        kind = defaults["relation_kind"]
        line_type = next(lt for k, _, lt in RELATION_KINDS if k == kind)
        req = {"op": "add_relation", "target": None,
               "value": {"kind": kind, "line_type": line_type, "line_no": None,
                         "from": _sid(items, state.first), "to": _sid(items, node)}}
        st = ToolState("connect")
        return st, req, st.hint
    if state.tool == "endpoint":
        if not state.end:
            return state, None, HINTS["endpoint"]
        if not node:
            return state, None, "기기를 클릭하세요."
        req = {"op": "set_endpoint", "target": _sid(items, state.relation),
               "value": {"end": state.end, "node": _sid(items, node)}}
        return ToolState(), req, HINTS["select"]
    if state.tool == "path":
        st = replace(state, points=state.points + ((x, y),))
        return st, None, "점 %d개 · %s" % (len(st.points), HINTS["path"])
    return state, None, state.hint


def finish_path(state, items):
    """경로 완료 → (ToolState, 요청 또는 None, 안내 문구). 점이 2개 이상이어야 한다."""
    if state.tool != "path":
        return state, None, state.hint
    if len(state.points) < 2:
        return state, None, "점을 2개 이상 클릭하세요."
    req = {"op": "set_path", "target": _sid(items, state.relation),
           "value": {"points": [list(p) for p in state.points]}}
    return ToolState(), req, HINTS["select"]


def flow_request(items, local_id, flip):
    """흐름 방향 요청. flip=False: source 끝 → target 끝으로 지정. flip=True: 지금 방향을 뒤집는다(방향이 없으면
    target → source). 양 끝이 모두 기기여야 한다. 만들 수 없으면 (None, 사유)."""
    r = items[local_id][1]
    ends = {ep.get("end"): ep.get("node_local_id") for ep in r.get("endpoints") or []}
    a, b = ends.get("source"), ends.get("target")
    if a not in items or b not in items:
        return None, "양 끝이 모두 기기에 이어져야 흐름 방향을 정할 수 있습니다(끝점 잇기 먼저)."
    fd = r.get("flow_direction")
    if flip:
        a, b = (fd["to"], fd["from"]) if fd and fd.get("from") in items and fd.get("to") in items else (b, a)
    return {"op": "set_flow", "target": r["source_object_id"],
            "value": {"from": _sid(items, a), "to": _sid(items, b)}}, None


def op_status(op, corrected):
    """수정 기록 한 줄의 적용 상태: ("적용" | "적용 불가: 사유" | "—", 적용 불가 여부)."""
    c = (corrected or {}).get("corrections") or {}
    for na in c.get("not_applicable") or []:
        if na.get("op_id") == op.get("op_id"):
            return "적용 불가: %s" % na.get("reason"), True
    return ("적용", False) if op.get("op_id") in (c.get("applied") or []) else ("—", False)


def ask_choice(parent, title, text, choices):
    """버튼 글자를 한국어로 쓰는 선택 상자. choices = [(key, 글자)], 첫 항목이 기본. 고른 key(닫으면 마지막 key)."""
    box = QMessageBox(QMessageBox.Question, title, text, parent=parent)
    buttons = [(box.addButton(label, QMessageBox.AcceptRole), key) for key, label in choices]
    box.setDefaultButton(buttons[0][0])
    box.setEscapeButton(buttons[-1][0])
    box.exec()
    return next((key for b, key in buttons if box.clickedButton() is b), choices[-1][0])


def notify(parent, title, text, warn=False):
    (QMessageBox.warning if warn else QMessageBox.information)(parent, title, text)


def _section(text):
    lab = QLabel(text)
    lab.setObjectName("section")
    return lab


class ViewerScreen(QWidget):
    title = "② 도면 추출"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.info = None
        self.name = None
        self.session = None       # 편집 모드일 때 EditSession
        self.tool = ToolState()
        self.items = {}
        self.selected = None      # 고른 항목 local_id
        self.view = None          # 마지막으로 알려진 웹 확대·위치
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("도면"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(320)
        self.combo.currentIndexChanged.connect(self._combo_changed)
        bar.addWidget(self.combo)
        self.chip_valid = Chip()
        self.chip_stats = Chip()
        bar.addWidget(self.chip_valid)
        bar.addWidget(self.chip_stats)
        bar.addStretch(1)
        self.edit_btn = QPushButton("편집")
        self.edit_btn.setCheckable(True)
        self.edit_btn.setObjectName("tool")
        self.edit_btn.toggled.connect(self.set_editing)
        bar.addWidget(self.edit_btn)
        lay.addLayout(bar)
        self.blockers = Banner("err")
        self.warn = Banner("warn")
        lay.addWidget(self.blockers)
        lay.addWidget(self.warn)
        self.stack = QStackedWidget()
        self.empty = empty_label("추출 결과가 없습니다. ① 자료 등록에서 PDF를 등록하거나(자동 추출) draw.io 원본을 등록한 뒤 '추출·그래프 만들기'를 실행하세요.")
        self.canvas_host = QWidget()
        QVBoxLayout(self.canvas_host).setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.canvas_host)
        body = QHBoxLayout()
        body.setSpacing(8)
        body.addWidget(self.stack, 1)
        self.edit_panel = self._edit_panel()
        self.edit_panel.hide()
        body.addWidget(self.edit_panel)
        lay.addLayout(body, 1)

    # ------------------------------------------------------------ 편집 패널
    def _edit_panel(self):
        scroll = QScrollArea()
        scroll.setObjectName("edit_panel")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(300)
        box = QFrame()
        box.setObjectName("panel")
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        v.addWidget(_section("도구"))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.tool_group = QButtonGroup(self)
        self.tool_btns = {}
        for i, (key, label) in enumerate(TOOLS):
            b = QPushButton(label)
            b.setObjectName("tool")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k))
            self.tool_group.addButton(b)
            self.tool_btns[key] = b
            grid.addWidget(b, i // 3, i % 3)
        v.addLayout(grid)
        self.end_row = QWidget()
        er = QHBoxLayout(self.end_row)
        er.setContentsMargins(0, 0, 0, 0)
        self.end_btns = {}
        for end in ("source", "target"):
            b = QPushButton("%s 끝" % end)
            b.setObjectName("tool")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, e=end: self._choose_end(e))
            self.end_btns[end] = b
            er.addWidget(b)
        v.addWidget(self.end_row)
        self.path_row = QWidget()
        pr = QHBoxLayout(self.path_row)
        pr.setContentsMargins(0, 0, 0, 0)
        self.path_done = QPushButton("경로 완료")
        self.path_done.setObjectName("primary")
        self.path_done.clicked.connect(self._finish_path)
        self.path_cancel = QPushButton("취소")
        self.path_cancel.clicked.connect(lambda: self.set_tool("select"))
        pr.addWidget(self.path_done)
        pr.addWidget(self.path_cancel)
        v.addWidget(self.path_row)
        self.hint = QLabel(HINTS["select"])
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        v.addWidget(_section("새 항목 기본값"))
        nd = QGridLayout()
        nd.setSpacing(4)
        nd.addWidget(QLabel("기기 종류"), 0, 0)
        self.new_kind = self._kind_combo()
        nd.addWidget(self.new_kind, 0, 1)
        nd.addWidget(QLabel("기기 태그"), 1, 0)
        self.new_tag = QLineEdit()
        self.new_tag.setPlaceholderText("비워도 됨")
        nd.addWidget(self.new_tag, 1, 1)
        nd.addWidget(QLabel("연결 종류"), 2, 0)
        self.new_rel = QComboBox()
        for k, label, _ in RELATION_KINDS:
            self.new_rel.addItem(label, k)
        nd.addWidget(self.new_rel, 2, 1)
        nd.setColumnStretch(1, 1)
        v.addLayout(nd)

        v.addWidget(_section("고른 항목"))
        self.sel_title = QLabel("도면에서 항목을 클릭하세요.")
        self.sel_title.setWordWrap(True)
        v.addWidget(self.sel_title)
        sg = QGridLayout()
        sg.setSpacing(4)
        self.tag_label = QLabel("태그")
        sg.addWidget(self.tag_label, 0, 0)
        self.tag_edit = QLineEdit()
        sg.addWidget(self.tag_edit, 0, 1)
        self.tag_apply = QPushButton("적용")
        self.tag_apply.clicked.connect(self._apply_tag)
        sg.addWidget(self.tag_apply, 0, 2)
        self.kind_label = QLabel("종류")
        sg.addWidget(self.kind_label, 1, 0)
        self.kind_combo = self._kind_combo()
        sg.addWidget(self.kind_combo, 1, 1)
        self.kind_apply = QPushButton("적용")
        self.kind_apply.clicked.connect(self._apply_kind)
        sg.addWidget(self.kind_apply, 1, 2)
        sg.setColumnStretch(1, 1)
        v.addLayout(sg)
        self.flow_row = QWidget()
        fr = QVBoxLayout(self.flow_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(4)
        self.flow_text = QLabel("")
        self.flow_text.setWordWrap(True)
        fr.addWidget(self.flow_text)
        fb = QHBoxLayout()
        self.flow_set = QPushButton("지정 A→B")
        self.flow_set.setToolTip("source 끝 → target 끝 방향으로 정합니다")
        self.flow_set.clicked.connect(lambda: self._apply_flow(False))
        self.flow_flip = QPushButton("뒤집기")
        self.flow_flip.clicked.connect(lambda: self._apply_flow(True))
        fb.addWidget(self.flow_set)
        fb.addWidget(self.flow_flip)
        fr.addLayout(fb)
        v.addWidget(self.flow_row)
        self.unknown_list = QListWidget()
        self.unknown_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.unknown_list.setWordWrap(True)
        self.unknown_list.setMaximumHeight(96)
        v.addWidget(self.unknown_list)
        ub = QHBoxLayout()
        self.confirm_btn = QPushButton("미확인 확정")
        self.confirm_btn.setToolTip("목록에서 고른 미확인만, 고르지 않으면 이 항목의 미확인 전부를 '이대로 맞음'으로 확정합니다")
        self.confirm_btn.clicked.connect(self._confirm)
        self.delete_btn = QPushButton("삭제")
        self.delete_btn.clicked.connect(self._delete)
        ub.addWidget(self.confirm_btn)
        ub.addWidget(self.delete_btn)
        v.addLayout(ub)

        v.addWidget(_section("수정 기록"))
        hb = QGridLayout()
        hb.setSpacing(4)
        self.undo_btn = QPushButton("실행 취소")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = QPushButton("다시 실행")
        self.redo_btn.clicked.connect(self.redo)
        self.save_btn = QPushButton("저장")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save)
        self.revert_btn = QPushButton("저장본으로 되돌리기")
        self.revert_btn.clicked.connect(self.revert)
        hb.addWidget(self.undo_btn, 0, 0)
        hb.addWidget(self.redo_btn, 0, 1)
        hb.addWidget(self.save_btn, 1, 0)
        hb.addWidget(self.revert_btn, 1, 1)
        v.addLayout(hb)
        self.op_list = QListWidget()
        self.op_list.setWordWrap(True)
        self.op_list.setMinimumHeight(90)
        v.addWidget(self.op_list, 1)
        scroll.setWidget(box)
        return scroll

    def _kind_combo(self):
        cb = QComboBox()
        for k in sorted(KIND_CATEGORY, key=lambda k: (list(CATEGORY_LABELS).index(KIND_CATEGORY[k]), kind_label(k))):
            cb.addItem(kind_label(k), k)
        return cb

    # ------------------------------------------------------------ 화면
    def where(self):
        if not self.info:
            return None
        d = self.info["extraction"]["drawing"]
        return {"drawing": d.get("drawing_number"), "region": None, "run": None}

    def on_enter(self):
        self.app.webview.set_mode(hide_panel=False, hide_graph=True)
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

    def is_done(self):
        return bool(data.list_extractions())

    def select_drawing(self, name):
        if self.combo.findText(name) >= 0:
            self.combo.setCurrentText(name)

    def _combo_changed(self):
        if self.name and self.combo.currentText() != self.name and not self.can_leave():
            self.combo.blockSignals(True)
            self.combo.setCurrentText(self.name)
            self.combo.blockSignals(False)
            return
        self._load()

    def _load(self, keep_view=False):
        name = self.combo.currentText()
        if name != self.name:
            self.session, self.selected, self.view, self.tool = None, None, None, ToolState()
        self.name = name or None
        if not name:
            self.info = None
            self.stack.setCurrentIndex(0)
            self.chip_valid.set_state("구조 검증 —")
            self.chip_stats.set_state("노드 — · 관계 — · 미확인 —")
            self.blockers.set_messages(None)
            self.warn.set_messages(None)
            self._sync_edit_ui()
            self.app.update_header()
            return
        if self.edit_btn.isChecked() and self.session is None:
            doc = corrections.load(name)
            self.session = EditSession((doc or {}).get("ops") or [])
        try:
            self.info = info = data.viewer_html_for(name, ops=self.session.ops if self.session else None)
        except (OSError, ValueError, KeyError) as exc:
            self.info = None
            self.stack.setCurrentIndex(0)
            self.empty.setText("추출 결과를 읽을 수 없음: %s" % exc)
            self._sync_edit_ui()
            return
        corrected = info.get("corrected") or info["extraction"]
        self.items = index_items(corrected)
        g, ex = info["graph"], info["extraction"]
        if g:
            st = g["validation"]["status"]
            self.chip_valid.set_state("구조 검증 %s" % VALIDATION_LABELS.get(st, st), "passed" if st == "passed" else "blocked")
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
        if self.session and self.session.dirty:  # 저장 전에는 그래프가 그대로라 고친 추출의 개수를 보인다
            s = corrected["summary"]
            self.chip_stats.set_state("노드 %d · 관계 %d · 미확인 %d (저장 전)" % (s["nodes"], s["relations"], s["unknowns"]),
                                      "warn")
        self.warn.set_messages(info["error"])
        if info["html"]:
            self.stack.setCurrentIndex(1)
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_drawing_enabled(True)  # ②는 현재 도면 그대로(분석 실행 기준 잠금 없음)
            editing = self.editable() and self.edit_btn.isChecked()
            self.app.webview.set_mode(hide_panel=editing, hide_graph=True)  # 편집 중에는 Qt 편집 패널이 속성 패널을 대신함
            self.app.webview.set_edit_mode(editing, self.tool.tool)
            self.app.webview.load_file(info["html"])
            if keep_view and self.view:
                self.app.webview.restore_view(self.view)
            if info.get("graph_only"):
                self.app.status_message("SVG 없음 — 그래프 보기만 표시")
        else:
            self.stack.setCurrentIndex(0)
            self.empty.setText(info["error"] or "")
        self._sync_edit_ui()
        self.app.update_header()

    def editable(self):
        return bool(self.info and self.info.get("html") and not self.info.get("graph_only"))

    def on_node(self, sel):
        self.app.debug_message("nodeSelected: %s" % (sel.get("entity_id") or sel.get("local_id")))
        if self.session is not None and sel.get("local_id") in self.items:
            self.selected = sel["local_id"]
            self._show_selected()

    # ------------------------------------------------------------ 편집 모드
    def set_editing(self, on):
        if not on and not self.can_leave():
            self.edit_btn.blockSignals(True)
            self.edit_btn.setChecked(True)
            self.edit_btn.blockSignals(False)
            return
        if not on:
            self.session = None
            self.tool = ToolState()
        self.app.webview.edit_preview([])
        self._rebuild()

    def set_tool(self, tool):
        self.tool, msg = start_tool(tool, self.selected, self.items)
        self.app.webview.edit_preview([])
        self.app.webview.set_edit_mode(True, self.tool.tool)
        self._sync_tool_ui(msg)

    def _choose_end(self, end):
        self.tool, msg = choose_end(self.tool, end)
        self._sync_tool_ui(msg)

    def on_edit_pick(self, pick):
        if self.session is None:
            return
        self.view = pick.get("view") or self.view
        self.tool, req, msg = tool_pick(self.tool, pick, self.items, self.defaults())
        if self.tool.tool == "path":
            self.app.webview.edit_preview(self.tool.points)
        self._sync_tool_ui(msg)
        if req:
            self.commit(req)

    def _finish_path(self):
        self.tool, req, msg = finish_path(self.tool, self.items)
        self._sync_tool_ui(msg)
        if req:
            self.app.webview.edit_preview([])
            self.app.webview.set_edit_mode(True, self.tool.tool)
            self.commit(req)

    def defaults(self):
        return {"kind": self.new_kind.currentData(), "tag": self.new_tag.text(), "relation_kind": self.new_rel.currentData()}

    def _tag_ok(self, tag, exclude_local=None):
        """태그는 프로젝트 전체에서 유일해야 한다. 겹치면 경고하고, 그래도 진행할지 묻는다."""
        if not tag:
            return True
        # 이 도면은 저장본이 아니라 작업 중 상태(self.items)로 본다
        hits = [h for h in data.tag_conflicts(tag, self.info["extraction"].get("project_id"))
                if h.get("name") != self.name]
        hits += [{"name": self.name, "local_id": lid} for lid, (kind, item) in self.items.items()
                 if kind == "node" and lid != exclude_local
                 and (item.get("tag") or "").strip().casefold() == tag.strip().casefold()]
        if not hits:
            return True
        where = ", ".join("%s(%s)" % (h.get("name"), h.get("local_id")) for h in hits[:5])
        return ask_choice(self, "태그 중복", "태그 '%s'가 이미 있습니다: %s\n태그는 프로젝트 전체에서 유일해야 합니다. 그래도 진행할까요?"
                          % (tag, where), (("cancel", "취소"), ("go", "그래도 진행"))) == "go"

    def commit(self, req):
        """요청 하나를 수정 기록(op)으로 만들어 작업 중 ops에 더하고 도면을 다시 그린다. 만들지 못하면 False."""
        node_tag = req["op"] == "add_node" or (req["op"] == "set_tag" and self._selected_item()[0] == "node")
        if node_tag and not self._tag_ok(req["value"]["tag"], self.selected if req["op"] == "set_tag" else None):
            return False
        try:
            op = corrections.make_op(self.info["original"], req["op"], req["target"], req["value"], self._by(),
                                     existing_ops=self.session.ops)
        except ValueError as exc:
            notify(self, "수정할 수 없음", str(exc), warn=True)
            return False
        self.session.add(op)
        if req["op"] in ("add_node", "add_relation"):
            self.selected = "manual-" + op["op_id"]
            if req["op"] == "add_node":
                self.new_tag.clear()
        elif req["op"].startswith("delete_"):
            self.selected = None
        self._rebuild()
        return True

    def _by(self):
        return self.app.reviewer_name() or "검토자 미설정"

    def _selected_item(self):
        return self.items.get(self.selected, (None, None))

    def _apply_tag(self):
        kind, item = self._selected_item()
        if item:
            self.commit({"op": "set_tag", "target": item["source_object_id"], "value": {"tag": self.tag_edit.text().strip()}})

    def _apply_kind(self):
        kind, item = self._selected_item()
        if kind == "node":
            k = self.kind_combo.currentData()
            self.commit({"op": "set_kind", "target": item["source_object_id"],
                         "value": {"kind": k, "category": KIND_CATEGORY[k]}})

    def _apply_flow(self, flip):
        req, why = flow_request(self.items, self.selected, flip)
        if why:
            notify(self, "흐름 방향", why, warn=True)
        else:
            self.commit(req)

    def _confirm(self):
        kind, item = self._selected_item()
        if item:
            picked = self.unknown_list.selectedItems() or [self.unknown_list.item(i) for i in range(self.unknown_list.count())]
            items = [i.data(Qt.UserRole) for i in picked]
            self.commit({"op": "confirm", "target": item["source_object_id"], "value": {"items": items}})

    def _delete(self):
        kind, item = self._selected_item()
        if item:
            self.commit({"op": "delete_node" if kind == "node" else "delete_relation",
                         "target": item["source_object_id"], "value": {}})

    def undo(self):
        if self.session and self.session.undo():
            self._rebuild()

    def redo(self):
        if self.session and self.session.redo():
            self._rebuild()

    def revert(self):
        if self.session and self.session.revert():
            self._rebuild()

    def save(self):
        """수정 기록 저장 → 그래프·지식그래프 다시 만들기. ④·⑤ 저장본이 있으면 재확인 안내."""
        if self.session is None or not self.name:
            return False
        by = self.app.reviewer_name()
        if not by:
            notify(self, "저장할 수 없음", "검토자 이름이 없습니다. 파일 > 설정(검토자 이름)에서 먼저 정하세요.", warn=True)
            return False
        try:
            res = data.save_corrections(self.name, self.session.ops, by)
        except (OSError, ValueError) as exc:
            self.app.log_error("도면 수정 저장", exc)
            notify(self, "저장 실패", "수정 기록을 저장하지 못했습니다: %s" % exc, warn=True)
            return False
        self.session.mark_saved()
        lines = ["수정 기록 %d건을 저장하고 그래프를 다시 만들었습니다." % len(self.session.ops)]
        if res.get("kg_error"):
            lines.append("지식그래프 다시 만들기 실패: %s" % res["kg_error"])
        recheck = list(res.get("recheck") or [])
        if recheck:
            lines.append("도면이 바뀌어 재확인 필요:")
            lines += ["· %s" % m for m in recheck]
        notify(self, "도면 수정 저장", "\n".join(lines), warn=bool(recheck or res.get("kg_error")))
        self._rebuild()
        self.app.refresh_stages()
        return True

    def can_leave(self):
        """저장하지 않은 수정이 있으면 저장·버리기·취소를 묻는다. 떠나도 되면 True."""
        if self.session is None or not self.session.dirty:
            return True
        c = ask_choice(self, "저장하지 않은 수정", "저장하지 않은 도면 수정이 있습니다(%s). 어떻게 할까요?" % self.name,
                       (("save", "저장"), ("discard", "버리기"), ("cancel", "취소")))
        if c == "save":
            return self.save()
        if c == "discard":  # 도면은 다음에 읽을 때(화면 진입·도면 바꾸기·편집 끄기) 저장본으로 다시 그려진다
            self.session = EditSession(self.session.saved)
            return True
        return False

    def _rebuild(self):
        """작업 중 ops로 뷰어를 다시 만들고 읽은 뒤 확대·위치를 되돌린다."""
        def done(view):
            self.view = view or self.view
            self._load(keep_view=True)
        if self.stack.currentIndex() == 1 and self.app.webview.current_file:
            self.app.webview.current_view(done)
        else:
            self._load()

    # ------------------------------------------------------------ 패널 표시
    def _sync_edit_ui(self):
        on = self.edit_btn.isChecked() and self.session is not None and self.editable()
        self.edit_btn.setEnabled(self.editable() or self.edit_btn.isChecked())
        self.edit_btn.setToolTip("도면 위에서 추출 결과(흐름 방향·연결·태그·종류·기기·배관 경로)를 고칩니다"
                                 if self.editable() else "SVG가 있는 도면 오버레이에서만 편집할 수 있습니다")
        self.edit_panel.setVisible(on)
        if not on:
            return
        if self.selected not in self.items:
            self.selected = None
        if self.tool.relation and self.tool.relation not in self.items:  # 실행 취소 등으로 대상 관계가 사라짐
            self.tool = ToolState()
            self.app.webview.set_edit_mode(True, "select")
        self._sync_tool_ui(None)
        self._show_selected()
        s = self.session
        self.undo_btn.setEnabled(bool(s.undo_stack))
        self.redo_btn.setEnabled(bool(s.redo_stack))
        self.save_btn.setEnabled(s.dirty)
        self.revert_btn.setEnabled(s.dirty)
        self.op_list.clear()
        corrected = (self.info or {}).get("corrected")
        names = {item["source_object_id"]: item.get("tag") or item.get("line_no") or lid
                 for lid, (_, item) in self.items.items()}
        for op in s.ops:
            status, bad = op_status(op, corrected)
            at = op.get("at") or ""
            try:
                at = kst_text(at)
            except ValueError:
                pass
            text = "%s · %s\n%s · %s · %s" % (OP_LABELS.get(op["op"], op["op"]),
                                             names.get(op.get("target"), op.get("target") or "새 항목"),
                                             op.get("by") or "—", at, status)
            it = QListWidgetItem(text)
            it.setToolTip(text)
            if bad:
                it.setForeground(QBrush(QColor(tokens.c("warn-ink"))))
            self.op_list.addItem(it)

    def _sync_tool_ui(self, msg):
        t = self.tool.tool
        self.tool_btns[t].setChecked(True)
        self.end_row.setVisible(t == "endpoint")
        for end, b in self.end_btns.items():
            b.setEnabled(t == "endpoint")
            b.setChecked(self.tool.end == end)
        self.path_row.setVisible(t == "path")
        self.path_done.setEnabled(len(self.tool.points) >= 2)
        self.hint.setText(msg or self.tool.hint)

    def _node_name(self, local_id):
        hit = self.items.get(local_id)
        return (hit[1].get("tag") if hit else None) or local_id

    def _show_selected(self):
        kind, item = self._selected_item()
        widgets = (self.tag_edit, self.tag_apply, self.confirm_btn, self.delete_btn, self.unknown_list)
        for w in widgets:
            w.setEnabled(item is not None)
        self.unknown_list.clear()
        if item is None:
            self.sel_title.setText("도면에서 항목을 클릭하세요.")
            self.tag_edit.clear()
            for w in (self.kind_label, self.kind_combo, self.kind_apply, self.flow_row):
                w.setVisible(False)
            return
        is_node = kind == "node"
        if is_node:
            self.sel_title.setText("<b>%s</b> · %s · %s" % (esc(item.get("tag") or "(태그 없음)"),
                                                            esc(kind_label(item.get("kind"))), esc(self.selected)))
            self.tag_label.setText("태그")
            self.tag_edit.setText(item.get("tag") or "")
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(item.get("kind")))  # 목록 밖 종류면 빈 칸
        else:
            self.sel_title.setText("<b>%s</b> · %s · %s" % (esc(item.get("line_no") or "(배관 번호 없음)"),
                                                            RELATION_LABELS.get(item.get("kind"), "미해결 커넥터"),
                                                            esc(self.selected)))
            self.tag_label.setText("배관 번호")
            self.tag_edit.setText(item.get("line_no") or "")
        for w in (self.kind_label, self.kind_combo, self.kind_apply):
            w.setVisible(is_node)
        physical = not is_node and item.get("kind") == "physical_connection"
        self.flow_row.setVisible(physical)
        if physical:
            fd = item.get("flow_direction")
            self.flow_text.setText("흐름: %s → %s" % (self._node_name(fd["from"]), self._node_name(fd["to"]))
                                   if fd else "흐름: 방향 미확인")
        corrected = (self.info or {}).get("corrected") or {}
        for u in unknowns_of(corrected, self.selected):
            li = QListWidgetItem("%s%s: %s" % (u.get("check"), " [%s]" % u["field"] if u.get("field") else "",
                                               u.get("reason") or ""))
            li.setData(Qt.UserRole, {"check": u.get("check"), "reason": u.get("reason") or ""})
            self.unknown_list.addItem(li)
        self.confirm_btn.setEnabled(self.unknown_list.count() > 0)
        if not self.unknown_list.count():
            self.unknown_list.addItem("미확인 없음")
            self.unknown_list.setEnabled(False)
