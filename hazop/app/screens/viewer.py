"""② 도면·그래프 조회 (기획서/인터페이스.md §3.2). 웹뷰는 기존 뷰어를 쓰되 'P&ID 구조'(그래프) 탭은 숨긴다
(결정로그 2026-11-06: '그래프'는 지식그래프만 뜻함. 내부 그래프 데이터는 지식그래프 재료로 계속 만든다).

편집 모드(drawing-edit-spec.md '화면'): 사람이 도면 위에서 추출 결과를 고친다. 원본 추출은 그대로 두고 수정 기록(ops)만
쌓는다. 웹뷰는 클릭 좌표·맞은 항목(editPick)만 보내고, 값 편집·실행 취소·저장은 오른쪽 Qt 편집 패널이 맡는다.
EditSession(작업 중 ops·실행 취소/다시 실행)과 tool_pick(여러 번 클릭하는 도구의 상태 기계)은 웹뷰 없이 검사할 수 있다.

도면 연결점(프로젝트 그래프 hazop.graph.project): 보기 모드에서 연결점 옆에 칩을 달고(누르면 상대 도면으로), 오른쪽
'도면 연결점' 패널에 짝·미연결을 보인다. 사람이 짝을 정하거나 끊은 기록은 도면별 수정 기록(hazop.extract.corrections)이
아니라 프로젝트의 도면 연결 지정(project.save_manual, data/drawing-links/<project>.json)에 쓴다. 짝은 두 도면에 걸쳐서
도면 한 장의 수정 기록으로는 적을 수 없다."""

import uuid
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from hazop import store_io
from hazop.app import data, project_ctx, tokens
from hazop.app.widgets import VALIDATION_LABELS, Banner, Chip, empty_label, esc, kst_text
from hazop.extract import corrections
from hazop.extract.rules import KIND_CATEGORY
from hazop.graph import project
from hazop.kg.schema import REGISTRY
from hazop.study import nodes as sn

# 분류·종류 이름과 순서는 타입 레지스트리(사전 §2.1)
CATEGORY_ORDER = REGISTRY.pid_categories()
# 고른 기기에서 고칠 수 있는 속성(값은 레지스트리 속성 사전의 허용값): (수정 연산, 속성)
POSITION_OPS = (("set_normal_position", "normal_position"), ("set_fail_position", "fail_position"))
# (관계 종류, 화면 이름, 새 연결의 line_type)
RELATION_KINDS = (("physical_connection", "공정 배관", "process"), ("signal_connection", "계장 신호", "signal"),
                  ("measurement_connection", "계측 연결", "instrument_tap"))
RELATION_LABELS = {k: label for k, label, _ in RELATION_KINDS}
TOOLS = (("select", "선택"), ("add_node", "기기 추가"), ("connect", "연결 추가"), ("endpoint", "끝점 잇기"),
         ("path", "경로 그리기"))
OP_LABELS = {"set_tag": "태그", "set_kind": "종류", "set_normal_position": "정상 위치", "set_fail_position": "고장 위치",
             "set_flow": "흐름 방향", "set_endpoint": "끝점 잇기",
             "set_path": "경로 다시 그리기", "confirm": "미확인 확정", "add_node": "기기 추가", "delete_node": "기기 삭제",
             "add_relation": "연결 추가", "delete_relation": "연결 삭제"}
NEW_NODE_SIZE = 40  # 기기 추가: 클릭한 점을 가운데로 하는 정사각형(도면 좌표)
# 미연결 칩의 짧은 사유. 전체 문장(project.REASONS)은 툴팁·패널에.
UNLINKED_SHORT = {"unregistered_drawing": "상대 도면 없음", "no_counterpart": "짝 없음", "ambiguous": "짝 여럿",
                  "direction_conflict": "방향 모순", "missing_key": "번호 못 읽음", "manual_unlink": "사람이 끊음",
                  "other_system": "다른 계통", "description_only": "설명만 있음", "system_candidate": "후보·확인 전"}
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
    return "%s · %s" % (REGISTRY.label(cat, "미분류"), REGISTRY.label(REGISTRY.kind_class.get(kind), kind or "종류 없음"))


def position_props(kind):
    """이 kind에서 고칠 수 있는 위치 속성 [(수정 연산, 속성)]. 레지스트리 클래스 properties에 있는 것만."""
    cid = REGISTRY.kind_class.get(kind)
    have = REGISTRY.class_properties(cid) if cid else []
    return [(op, prop) for op, prop in POSITION_OPS if prop in have]


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

    def __init__(self, ops=(), fp=None):
        self.ops = list(ops)
        self.saved = list(ops)
        self.fp = fp  # saved를 읽은 기록 파일의 지문(없던 파일이면 None). 저장할 때 그 뒤 바뀐 파일을 덮어쓰지 않게 한다
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

    def issued_ids(self):
        """작업 중·저장본·실행 취소·다시 실행 목록에 있는 op_id. 되살릴 수 있는 연산의 번호도 새로 발급하지 않는다."""
        return {o.get("op_id") for ops in [self.ops, self.saved, *self.undo_stack, *self.redo_stack] for o in ops}


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


# ---------------------------------------------------------------- 도면 연결점(순수 함수)
def link_points(ctx):
    """이 도면의 연결점과 짝 상태. 미연결 먼저, 그다음 이름순. 항목: {entity_id, local_id, label, line_no, to_drawing,
    source_object_id, status, reason, reason_text, origin, op_id, peer}. peer = {entity_id, drawing, label}(짝 있을 때)."""
    out = []
    for l in ctx.pg["sheet_links"]:
        ends = (l["from"], l.get("to"))
        for i, end in enumerate(ends):
            if not end or end["graph_id"] != ctx.graph_id:
                continue
            eid, other = project.nid(end["graph_id"], end["entity_id"]), ends[1 - i]
            n = ctx.by_id.get(eid) or {}
            peer = None
            if other:
                pid = project.nid(other["graph_id"], other["entity_id"])
                peer = {"entity_id": pid, "drawing": other["drawing_number"],
                        "label": project_ctx.continuation_label(ctx.by_id.get(pid) or {})}
            out.append({"entity_id": eid, "local_id": ctx.local_of.get(eid) or n.get("local_id"),
                        "label": project_ctx.continuation_label(n), "line_no": end.get("line_no"),
                        "to_drawing": end.get("to_drawing"),
                        "source_object_id": end.get("source_object_id") or n.get("source_object_id"),
                        "status": l["status"], "reason": l["reason"],
                        "reason_text": project.REASONS.get(l["reason"], l["reason"]) if l["reason"] else None,
                        "origin": l.get("origin"), "op_id": l.get("op_id"),
                        "peer": peer if l["status"] == project.LINKED else None})
    return sorted(out, key=lambda p: (p["status"] == project.LINKED, p["line_no"] or p["label"] or "", p["entity_id"]))


def drawing_chips(ctx, view=None):
    """② 도면 칩 [{local_id, text, key, kind, tip, row}]. 저장한 구간 집합의 보기(ctx.view)가 있으면 연결점마다
    "S7 → SNP-M-101에서 계속", 구간 칩이 없는 연결점은 "→ SNP-M-101 (RC-L011)", 미연결은 "미연결 · 사유".
    key는 "link|상대 도면 번호|구간 ID(없으면 빈칸)|상대 연결점 ID" 또는 "unlinked|연결점 ID"."""
    points = link_points(ctx)
    peer_of = {p["entity_id"]: p["peer"] for p in points if p["peer"]}
    chips, done = [], set()
    for n in (view or {}).get("nodes") or []:
        for c in ctx.chips(n):
            peer = peer_of.get(c["entity_id"])
            if not c["local_id"] or not peer:
                continue
            chips.append({"local_id": c["local_id"], "text": c["text"], "kind": "link",
                          "key": "link|%s|%s|%s" % (c["drawing"], c["node_id"], peer["entity_id"]),
                          "tip": "%s — 누르면 %s의 같은 구간으로 이동" % (c["text"], c["drawing"])})
            done.add(c["entity_id"])
    for p in points:
        if not p["local_id"] or p["entity_id"] in done:
            continue
        if p["peer"]:
            text = "→ %s (%s)" % (p["peer"]["drawing"], p["line_no"] or p["peer"]["label"])
            chips.append({"local_id": p["local_id"], "text": text, "kind": "link",
                          "key": "link|%s||%s" % (p["peer"]["drawing"], p["peer"]["entity_id"]),
                          "tip": "%s — 누르면 %s로 이동" % (text, p["peer"]["drawing"])})
        else:
            chips.append({"local_id": p["local_id"], "text": "미연결 · %s" % UNLINKED_SHORT.get(p["reason"], p["reason"]),
                          "kind": "unlinked", "key": "unlinked|%s" % p["entity_id"],
                          "tip": "%s — 누르면 짝 지정" % p["reason_text"]})
    rows = {}
    for c in chips:
        c["row"] = rows.get(c["local_id"], 0)
        rows[c["local_id"]] = c["row"] + 1
    return chips


def pair_candidates(ctx, entity_id):
    """짝 후보: 다른 도면의 연결점 전부. 짝 없는 것 → 이 도면을 가리키는 것 → 배관 번호가 같은 것 순.
    [{entity_id, drawing_number, source_object_id, label, line_no, to_drawing, linked}]"""
    point = next((p for p in link_points(ctx) if p["entity_id"] == entity_id), {})
    dn = {s["graph_id"]: s["drawing_number"] for s in ctx.pg["sheets"]}
    out = []
    for n in ctx.pg["nodes"]:
        if n.get("kind") != "continuation" or n.get("sheet") in (None, ctx.graph_id):
            continue
        k = project.continuation_key({"graph_id": n["sheet"], "source": {"drawing_number": dn.get(n["sheet"])}}, n)
        out.append({"entity_id": n["entity_id"], "drawing_number": dn.get(n["sheet"]),
                    "source_object_id": n.get("source_object_id"), "label": project_ctx.continuation_label(n),
                    "line_no": k["line_no"], "to_drawing": k["to_drawing"],
                    "linked": (n.get("sheet_link") or {}).get("status") == project.LINKED})
    return sorted(out, key=lambda c: (c["linked"], c["to_drawing"] != ctx.drawing_number,
                                      c["line_no"] != point.get("line_no"), c["drawing_number"] or "", c["label"]))


def _end_key(end):
    return ((end.get("drawing_number") or "").strip().upper(), end.get("source_object_id"))


def replace_link_ops(ops, new):
    """도면 연결 지정 목록에 new를 더한다. new가 가리키는 연결점을 건드리는 앞선 지정은 뺀다
    (project.match는 앞선 지정을 쓰고 같은 연결점의 뒤 지정을 건너뛰므로, 남겨 두면 새 지정이 무시된다)."""
    keys = {_end_key(e) for e in new["ends"]}
    return [o for o in ops if not keys & {_end_key(e) for e in o.get("ends") or []}] + [new]


def new_link_op(op, ends, by, reason=""):
    return {"op_id": "sl-%s" % uuid.uuid4().hex[:12], "op": op, "ends": ends, "by": by, "at": sn.now_utc(),
            "reason": reason or ""}


class PairDialog(QDialog):
    """연결점 짝 지정: 다른 도면의 연결점 후보 중 하나와 사유. chosen()은 (후보, 사유) 또는 None."""

    def __init__(self, parent, point, drawing_number, candidates):
        super().__init__(parent)
        self.setWindowTitle("연결점 짝 지정")
        self.candidates = candidates
        v = QVBoxLayout(self)
        head = QLabel("%s · %s (%s)의 짝을 고르세요." % (drawing_number, point["line_no"] or "-", point["label"]))
        head.setWordWrap(True)
        v.addWidget(head)
        if point.get("reason_text"):
            why = QLabel("지금: %s" % (point["reason_text"] if not point.get("peer") else
                                      "%s와 연결됨(지정하면 바뀜)" % point["peer"]["drawing"]))
            why.setObjectName("muted")
            why.setWordWrap(True)
            v.addWidget(why)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("도면 번호·배관 번호로 찾기")
        self.filter.setAccessibleName("후보 찾기")
        self.filter.textChanged.connect(self._filter)
        v.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setAccessibleName("짝 후보 목록")
        for c in candidates:
            text = "%s · %s · %s" % (c["drawing_number"], c["line_no"] or "-", c["label"])
            if c["linked"]:
                text += " · 이미 짝 있음(지정하면 그 짝이 풀림)"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, c["entity_id"])
            if c["linked"]:
                it.setForeground(QBrush(QColor(tokens.c("muted"))))
            self.list.addItem(it)
        self.list.itemDoubleClicked.connect(lambda _it: self.accept())
        v.addWidget(self.list, 1)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("사유(선택): 예) 도면 개정으로 배관 번호가 바뀜")
        self.reason.setAccessibleName("지정 사유")
        v.addWidget(self.reason)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("짝 지정", QDialogButtonBox.AcceptRole)
        bb.addButton("취소", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.list.currentRowChanged.connect(lambda _r: self.ok.setEnabled(self.list.currentItem() is not None))
        self.ok.setEnabled(False)
        self.resize(520, 420)

    def _filter(self, text):
        t = text.strip().casefold()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().casefold())

    def chosen(self):
        it = self.list.currentItem()
        if it is None or it.isHidden():
            return None
        c = next(c for c in self.candidates if c["entity_id"] == it.data(Qt.UserRole))
        return c, self.reason.text().strip()


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


class ViewerHost(QObject):
    """도면 한 장을 띄운 웹뷰 위에서 여러 도면에 걸친 표시를 맡는다(docs/specs/chat-panel.md §6.4).

    - names() → {graph_id: 도면 이름}, switch(이름) → 화면이 그 도면으로 바꾼다(ViewerScreen.select_drawing).
    - 도면별로 그릴 것을 맡겨 두고(show_marks), 도면을 옮겨 읽기가 끝나면(sheetReady) 그 도면 것을 다시 그린다.
    - 맡기는 항목은 {"op": "mark", "groups", "dim_others", "center"} 또는 {"op": "path", "steps", "style", "numbered"}.
      한 요청에 항목이 여럿이면 둘째부터 웹 쪽 request_id를 "<id>#<번호>"로 나눠 보낸다(같은 id는 웹에서 덮어쓰므로)."""

    def __init__(self, webview, names, switch, parent=None):
        super().__init__(parent or webview)
        self.webview = webview
        self._names = names
        self._switch = switch
        self._marks = {}      # request_id → {graph_id: [항목]}
        self._sent = {}       # request_id → 웹에 보낸 request_id 목록(지우려고)
        self._wait = None     # (graph_id, then)
        webview.bridge.sheetReady.connect(self._sheet_ready)

    def current_sheet(self):
        return self.webview.current_graph_id

    def show_sheet(self, graph_id, then=None):
        """지금 도면이면 then을 바로 부른다. 아니면 도면을 바꾸고 sheetReady 뒤에 부른다. 모르는 도면이면 False."""
        if graph_id == self.current_sheet() and self.webview.bridge.is_ready:
            if then:
                then()
            return True
        name = self._names().get(graph_id)
        if graph_id != self.current_sheet() and not name:
            return False
        self._wait = (graph_id, then)
        if graph_id != self.current_sheet():
            self._switch(name)
        return True

    def show_marks(self, request_id, marks_by_sheet, sheet=None):
        """도면마다 그릴 것을 맡겨 두고, 지금(또는 sheet) 도면 것을 그린다. 도면을 옮기면 맡긴 것을 그 도면에 그린다."""
        self.clear(request_id)
        self._marks[request_id] = {g: list(v) for g, v in (marks_by_sheet or {}).items()}
        if sheet and sheet != self.current_sheet():
            self.show_sheet(sheet)
        elif self.webview.bridge.is_ready:
            self._draw(request_id, self.current_sheet())

    def clear(self, request_id=None):
        """맡긴 것과 웹에 그린 것을 지운다(None이면 전부)."""
        if request_id is None:
            self._marks, self._sent = {}, {}
            self.webview.clear_marks(None)
            return
        self._marks.pop(request_id, None)
        for web_id in self._sent.pop(request_id, [request_id]):
            self.webview.clear_marks(web_id)

    def _draw(self, request_id, sheet):
        sent = []
        for i, item in enumerate(self._marks.get(request_id, {}).get(sheet, [])):
            web_id = request_id if i == 0 else "%s#%d" % (request_id, i)
            sent.append(web_id)
            if item.get("op") == "path":
                self.webview.draw_path(web_id, item.get("steps") or [], item.get("style", "path"), item.get("numbered", True))
            else:
                self.webview.mark(web_id, item.get("groups") or [], item.get("dim_others", True), item.get("center", False))
        self._sent[request_id] = sent

    def _sheet_ready(self, graph_id):
        for rid in list(self._marks):
            self._draw(rid, graph_id)
        wait, self._wait = self._wait, None
        if wait and wait[0] == graph_id:
            if wait[1]:
                wait[1]()
        elif wait:
            self._wait = wait   # 다른 도면이 먼저 열렸다. 기다리던 도면이 열릴 때까지 둔다


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
        self.ctx = None           # 보기 모드의 프로젝트 맥락(project_ctx.ProjectContext)
        self.points = []          # 이 도면 연결점(link_points)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("도면"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(320)
        self.combo.setAccessibleName("도면")
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
        self.link_panel = self._link_panel()
        self.link_panel.hide()
        body.addWidget(self.link_panel)
        lay.addLayout(body, 1)

    def main_focus(self):
        """화면에 들어오면 초점: 도면이 보이면 도면, 아니면 도면 고르기."""
        return self.app.webview if self.stack.currentIndex() == 1 else self.combo

    # ------------------------------------------------------------ 도면 연결점 패널
    def _link_panel(self):
        box = QFrame()
        box.setObjectName("panel")
        box.setFixedWidth(260)
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        v.addWidget(_section("도면 연결점"))
        self.link_counts = QLabel("")
        v.addWidget(self.link_counts)
        self.link_list = QListWidget()
        self.link_list.setAccessibleName("도면 연결점 목록")
        self.link_list.setWordWrap(True)
        self.link_list.currentRowChanged.connect(lambda _r: self._sync_link_buttons())
        self.link_list.itemDoubleClicked.connect(lambda it: self.open_pair(it.data(Qt.UserRole)))
        v.addWidget(self.link_list, 1)
        row = QHBoxLayout()
        self.pair_btn = QPushButton("짝 지정…")
        self.pair_btn.setToolTip("고른 연결점의 짝을 다른 도면의 연결점에서 사람이 고릅니다")
        self.pair_btn.clicked.connect(lambda: self.open_pair())
        self.unlink_btn = QPushButton("연결 끊기")
        self.unlink_btn.setToolTip("고른 연결점을 '연결하지 않음'으로 지정합니다")
        self.unlink_btn.clicked.connect(lambda: self.unlink())
        row.addWidget(self.pair_btn)
        row.addWidget(self.unlink_btn)
        v.addLayout(row)
        self.link_note = QLabel("")
        self.link_note.setObjectName("muted")
        self.link_note.setWordWrap(True)
        v.addWidget(self.link_note)
        return box

    def _point(self, entity_id=None):
        if entity_id is None:
            it = self.link_list.currentItem()
            entity_id = it.data(Qt.UserRole) if it else None
        return next((p for p in self.points if p["entity_id"] == entity_id), None)

    def _sync_link_buttons(self):
        p = self._point()
        self.pair_btn.setEnabled(p is not None)
        self.unlink_btn.setEnabled(bool(p and p["status"] == project.LINKED))

    def _refresh_links(self):
        """프로젝트 맥락을 다시 읽어 칩과 '도면 연결점' 패널을 채운다(보기 모드)."""
        try:
            self.ctx = project_ctx.load(self.name)
        except (OSError, ValueError, KeyError) as exc:
            self.app.log_error("프로젝트 그래프 읽기", exc)
            self.ctx = None
        ctx = self.ctx
        self.points = link_points(ctx) if ctx and ctx.pg else []
        view = None
        if self.points:
            try:
                saved = sn.load(ctx.pg)
                view = ctx.view(saved) if saved else None
            except (OSError, ValueError, KeyError) as exc:
                self.app.log_error("검토구간 읽기(도면 칩)", exc)
        self.app.webview.set_chips(drawing_chips(ctx, view) if self.points else [])
        self.link_panel.setVisible(bool(self.points) or bool(ctx and ctx.error))
        if ctx and ctx.error:
            self.link_counts.setText(ctx.error)
        self._fill_link_panel()

    def _fill_link_panel(self):
        linked = sum(1 for p in self.points if p["status"] == project.LINKED)
        if self.points:
            self.link_counts.setText("짝 %d · 미연결 %d" % (linked, len(self.points) - linked))
        manual, skipped = {}, []
        if self.ctx and self.ctx.pg:
            try:
                manual = {o["op_id"]: o for o in (project.load_manual(self.ctx.project_id) or {}).get("ops") or []}
            except (OSError, ValueError) as exc:
                skipped.append("도면 연결 지정 파일을 읽을 수 없음: %s" % exc)
            skipped += ["%s: %s" % (s.get("op_id"), s.get("reason")) for s in self.ctx.pg.get("manual_skipped") or []]
        cur = self.link_list.currentItem().data(Qt.UserRole) if self.link_list.currentItem() else None
        self.link_list.clear()
        for p in self.points:
            if p["peer"]:
                text = "%s → %s" % (p["line_no"] or p["label"], p["peer"]["drawing"])
            else:
                text = "미연결 · %s · %s\n%s" % (p["line_no"] or "-", p["label"], p["reason_text"])
            if p["origin"] == "manual":
                o = manual.get(p["op_id"]) or {}
                try:
                    at = kst_text(o.get("at") or "")
                except ValueError:
                    at = o.get("at") or "-"
                text += "\n사람 지정 · %s · %s%s" % (o.get("by") or "-", at, " · %s" % o["reason"] if o.get("reason") else "")
            it = QListWidgetItem(text)
            it.setToolTip(text)
            it.setData(Qt.UserRole, p["entity_id"])
            if not p["peer"]:
                it.setForeground(QBrush(QColor(tokens.c("warn-ink"))))
            self.link_list.addItem(it)
            if p["entity_id"] == cur:
                self.link_list.setCurrentItem(it)
        self.link_note.setText("적용하지 못한 사람 지정: %s" % "; ".join(skipped) if skipped else
                               "칩이나 목록에서 미연결 연결점을 골라 짝을 지정할 수 있습니다.")
        self._sync_link_buttons()

    def on_chip(self, key):
        """도면 칩: 연결된 칩은 상대 도면으로 가서(구간이 있으면 그 구간을 선택) 상대 연결점에 초점, 미연결 칩은 짝 지정."""
        parts = key.split("|")
        if parts[0] == "unlinked" and len(parts) == 2 and self._point(parts[1]):
            self.open_pair(parts[1])
            return
        if parts[0] != "link" or len(parts) != 4 or not self.ctx:
            return
        dn, node_id, peer = parts[1:]
        name = self.ctx.drawing_names.get(dn)
        if not name or self.combo.findText(name) < 0:
            self.app.status_message("상대 도면 %s의 추출 결과가 ② 목록에 없습니다." % dn)
            return
        self.select_drawing(name)
        if self.combo.currentText() != name:  # 저장하지 않은 수정 때문에 떠나지 않음
            return
        if node_id:
            self.app.set_selection({"kind": "node", "drawing": name, "node_id": node_id})
        local = self.ctx.local_of.get(peer) if self.ctx else None
        if local:
            self.app.webview.focus(local)

    def open_pair(self, entity_id=None):
        """짝 지정 대화상자를 열고 고르면 저장한다."""
        p = self._point(entity_id)
        if p is None or not self.ctx:
            return False
        dlg = PairDialog(self, p, self.ctx.drawing_number, pair_candidates(self.ctx, p["entity_id"]))
        if dlg.exec() != QDialog.Accepted or dlg.chosen() is None:
            return False
        cand, reason = dlg.chosen()
        return self.pair(p["entity_id"], cand, reason)

    def pair(self, entity_id, cand, reason=""):
        """이 도면 연결점 entity_id와 다른 도면 연결점 cand(pair_candidates 항목)를 짝으로 지정해 저장한다."""
        p = self._point(entity_id)
        ends = [{"drawing_number": self.ctx.drawing_number, "source_object_id": p["source_object_id"]},
                {"drawing_number": cand["drawing_number"], "source_object_id": cand["source_object_id"]}]
        return self._save_link_op("link", ends, reason, "%s ↔ %s %s 짝을 지정했습니다." % (
            p["line_no"] or p["label"], cand["drawing_number"], cand["line_no"] or cand["label"]))

    def unlink(self, entity_id=None, reason=""):
        """연결된 연결점 하나를 '연결하지 않음'으로 지정해 저장한다."""
        p = self._point(entity_id)
        if p is None or p["status"] != project.LINKED:
            return False
        ends = [{"drawing_number": self.ctx.drawing_number, "source_object_id": p["source_object_id"]}]
        return self._save_link_op("unlink", ends, reason, "%s 연결을 끊었습니다." % (p["line_no"] or p["label"]))

    def _ask_name(self):
        name, ok = QInputDialog.getText(self, "지정한 사람", "도면 연결을 지정한 사람 이름(검토자 이름이 설정되어 있지 않음):")
        return name.strip() if ok else None

    def _save_link_op(self, op, ends, reason, done_text):
        by = self.app.reviewer_name() or self._ask_name()
        if not by:
            return False
        pid = self.ctx.project_id
        try:
            prev = (project.load_manual(pid) or {}).get("ops") or []
            new = new_link_op(op, ends, by, reason)
            project.save_manual(pid, replace_link_ops(prev, new), by=by, at=new["at"])
        except (OSError, ValueError) as exc:
            self.app.log_error("도면 연결 지정 저장", exc)
            notify(self, "저장 실패", "도면 연결 지정을 저장하지 못했습니다: %s" % exc, warn=True)
            return False
        self._refresh_links()
        self.app.toast(done_text + self._stale_note(), undo=lambda: self._restore_link_ops(pid, prev, by))
        return True

    def _restore_link_ops(self, pid, ops, by):
        try:
            project.save_manual(pid, ops, by=by, at=sn.now_utc())
        except (OSError, ValueError) as exc:
            self.app.log_error("도면 연결 지정 되돌리기", exc)
            return
        if self.ctx and self.ctx.project_id == pid and self.app.current_screen() is self:
            self._refresh_links()
        self.app.toast("도면 연결 지정을 되돌렸습니다.")

    def _stale_note(self):
        """연결이 바뀌면 프로젝트 그래프 판이 바뀌어 저장한 ④ 검토구간이 옛 판이 된다."""
        try:
            saved = sn.load(self.ctx.pg) if self.ctx and self.ctx.pg else None
        except (OSError, ValueError):
            return ""
        return " ④ 검토구간은 이전 연결 기준이라 다시 확인이 필요합니다." if saved and sn.is_stale(saved, self.ctx.pg) else ""

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
        self.new_kind.setAccessibleName("새 기기 종류")
        nd.addWidget(self.new_kind, 0, 1)
        nd.addWidget(QLabel("기기 태그"), 1, 0)
        self.new_tag = QLineEdit()
        self.new_tag.setPlaceholderText("비워도 됨")
        self.new_tag.setAccessibleName("새 기기 태그")
        nd.addWidget(self.new_tag, 1, 1)
        nd.addWidget(QLabel("연결 종류"), 2, 0)
        self.new_rel = QComboBox()
        self.new_rel.setAccessibleName("새 연결 종류")
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
        self.tag_edit.setAccessibleName("고른 항목 태그")
        sg.addWidget(self.tag_edit, 0, 1)
        self.tag_apply = QPushButton("적용")
        self.tag_apply.clicked.connect(self._apply_tag)
        sg.addWidget(self.tag_apply, 0, 2)
        self.kind_label = QLabel("종류")
        sg.addWidget(self.kind_label, 1, 0)
        self.kind_combo = self._kind_combo()
        self.kind_combo.setAccessibleName("고른 항목 종류")
        sg.addWidget(self.kind_combo, 1, 1)
        self.kind_apply = QPushButton("적용")
        self.kind_apply.clicked.connect(self._apply_kind)
        sg.addWidget(self.kind_apply, 1, 2)
        sg.setColumnStretch(1, 1)
        v.addLayout(sg)
        pg = QGridLayout()  # 따로 둔다: 긴 이름(정상 위치)이 태그·종류 칸을 넓혀 패널이 가로로 잘리지 않게
        pg.setSpacing(4)
        self.pos_rows = {}
        for row, (op, prop) in enumerate(POSITION_OPS):
            spec = REGISTRY.properties[prop]
            lab = QLabel(spec["label_ko"])
            cb = QComboBox()
            cb.setAccessibleName("고른 항목 %s" % spec["label_ko"])
            cb.addItem("—", None)
            for val in spec["values"]:
                cb.addItem(val, val)
            btn = QPushButton("적용")
            btn.clicked.connect(lambda _=False, o=op, p=prop: self._apply_position(o, p))
            pg.addWidget(lab, row, 0)
            pg.addWidget(cb, row, 1)
            pg.addWidget(btn, row, 2)
            self.pos_rows[prop] = (lab, cb, btn)
        pg.setColumnStretch(1, 1)
        v.addLayout(pg)
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
        self.unknown_list.setAccessibleName("미확인 목록")
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
        self.op_list.setAccessibleName("수정 기록 목록")
        self.op_list.setWordWrap(True)
        self.op_list.setMinimumHeight(90)
        v.addWidget(self.op_list, 1)
        scroll.setWidget(box)
        return scroll

    def _kind_combo(self):
        cb = QComboBox()
        for k in sorted(KIND_CATEGORY, key=lambda k: (CATEGORY_ORDER.index(KIND_CATEGORY[k]), kind_label(k))):
            cb.addItem(kind_label(k), k)
        return cb

    # ------------------------------------------------------------ 화면
    def where(self):
        if not self.info:
            return None
        d = self.info["extraction"]["drawing"]
        return {"drawing": d.get("drawing_number"), "region": None, "run": None}

    def on_enter(self):
        self.app.webview.set_mode(hide_panel=False, hide_graph=True, hide_status=True)
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
        self.link_panel.hide()
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
            doc, fp = corrections.load_fp(name)
            self.session = EditSession((doc or {}).get("ops") or [], fp)
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
        if self.session and self.session.dirty and g:  # 편집 중 그래프는 고친 내용으로 만든 것이라 저장본과 같은 기준이다
            self.chip_stats.set_state("노드 %d · 관계 %d · 미확인 %d (저장 전)" % (
                g["structure"]["node_count"], g["structure"]["edge_count"], len(g["validation"].get("unknowns") or [])),
                "warn")
        self.warn.set_messages(info["error"])
        if info["html"]:
            self.stack.setCurrentIndex(1)
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_drawing_enabled(True)  # ②는 현재 도면 그대로(분석 실행 기준 잠금 없음)
            editing = self.editable() and self.edit_btn.isChecked()
            self.app.webview.set_mode(hide_panel=editing, hide_graph=True, hide_status=True)  # 편집 중에는 Qt 편집 패널이 속성 패널을 대신함
            self.app.webview.set_edit_mode(editing, self.tool.tool)
            self.app.webview.load_file(info["html"], graph_id=(g or {}).get("graph_id") or "")
            if keep_view and self.view:
                self.app.webview.restore_view(self.view)
            if editing:  # 편집 중에는 칩이 클릭을 가리지 않게 단다
                self.app.webview.set_chips([])
            else:
                self._refresh_links()
            if info.get("graph_only"):
                self.app.status_message("SVG 없음 — 그래프 보기만 표시")
        else:
            self.stack.setCurrentIndex(0)
            self.empty.setText(info["error"] or "")
        self._sync_edit_ui()
        self.app.update_header()

    def editable(self):
        return bool(self.info and self.info.get("html") and not self.info.get("graph_only"))

    def selection_for(self, local_id, entity_id=None):
        """도면에서 고른 항목 → 관련 항목 패널 선택. 도면 오버레이는 entity_id를 보내지 않으므로 그래프에서 찾는다.
        그래프에 없는 항목(신호·계측 연결, 그래프가 없는 도면)은 entity_id 없이 local_id만 둔다. 고른 것이 없으면 None."""
        if not local_id or not self.name:
            return None
        if not entity_id:
            g = (self.info or {}).get("graph") or {}
            entity_id = next((n["entity_id"] for n in g.get("nodes") or [] if n.get("local_id") == local_id), None)
        return {"kind": "component", "drawing": self.name, "entity_id": entity_id, "local_id": local_id}

    def commands(self):
        """명령 팔레트 항목 (label, 단축키 글자, 함수)."""
        wv = self.app.webview
        return [("경로 질의 열기", "", wv.open_path_query),
                ("레이어: 태그 보이기/숨기기", "", lambda: wv.toggle_layer("tag")),
                ("레이어: 심볼 보이기/숨기기", "", lambda: wv.toggle_layer("symbol")),
                ("레이어: 배관 보이기/숨기기", "", lambda: wv.toggle_layer("pipe")),
                ("도면 편집 켜기/끄기", "", self.edit_btn.click)]

    def on_node(self, sel):
        self.app.debug_message("nodeSelected: %s" % (sel.get("entity_id") or sel.get("local_id")))
        self.app.set_selection(self.selection_for(sel.get("local_id"), sel.get("entity_id")))
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
                                     existing_ops=self.session.ops, used_ids=self.session.issued_ids(), name=self.name)
        except (OSError, ValueError) as exc:
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

    def _apply_position(self, op, prop):
        kind, item = self._selected_item()
        val = self.pos_rows[prop][1].currentData()
        if kind == "node" and val:
            self.commit({"op": op, "target": item["source_object_id"], "value": {"value": val}})

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
            res = data.save_corrections(self.name, self.session.ops, by, expect=self.session.fp)
        except store_io.Conflict:
            notify(self, "저장하지 않음", "편집을 시작한 뒤 수정 기록 파일이 바뀌어 저장하지 않았습니다. "
                   "작업 중 수정은 화면에 남아 있습니다. 편집을 껐다 켜면 최신 기록을 읽습니다(작업 중 수정은 버려짐).", warn=True)
            return False
        except (OSError, ValueError) as exc:
            self.app.log_error("도면 수정 저장", exc)
            notify(self, "저장 실패", "수정 기록을 저장하지 못했습니다: %s" % exc, warn=True)
            return False
        self.session.mark_saved()
        self.session.fp = res["fingerprint"]
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
            self.session = EditSession(self.session.saved, self.session.fp)
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
        self.edit_btn.setToolTip("도면 위에서 추출 결과(흐름 방향·연결·태그·종류·밸브 위치·기기·배관 경로)를 고칩니다"
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
            for row in self.pos_rows.values():
                for w in row:
                    w.setVisible(False)
            return
        is_node = kind == "node"
        if is_node:
            self.sel_title.setText("<b>%s</b> · %s · %s" % (esc(item.get("tag") or "(태그 없음)"),
                                                            esc(kind_label(item.get("kind"))), esc(self.selected)))
            self.tag_label.setText("태그")
            self.tag_edit.setAccessibleName("고른 항목 태그")
            self.tag_edit.setText(item.get("tag") or "")
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(item.get("kind")))  # 목록 밖 종류면 빈 칸
        else:
            self.sel_title.setText("<b>%s</b> · %s · %s" % (esc(item.get("line_no") or "(배관 번호 없음)"),
                                                            RELATION_LABELS.get(item.get("kind"), "미해결 커넥터"),
                                                            esc(self.selected)))
            self.tag_label.setText("배관 번호")
            self.tag_edit.setAccessibleName("고른 항목 배관 번호")
            self.tag_edit.setText(item.get("line_no") or "")
        for w in (self.kind_label, self.kind_combo, self.kind_apply):
            w.setVisible(is_node)
        editable = {prop for _, prop in position_props(item.get("kind"))} if is_node else set()
        for prop, (lab, cb, btn) in self.pos_rows.items():
            for w in (lab, cb, btn):
                w.setVisible(prop in editable)
            if prop in editable:
                cur = (item.get("attributes") or {}).get(prop)
                cb.setCurrentIndex(max(cb.findData(cur), 0))  # 허용값 밖·없음이면 '—'(적용해도 바뀌지 않음)
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
