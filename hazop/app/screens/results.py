"""⑤ 분석 결과 화면 (stage3-spec §B results.py, 4단계 설계, 디자인/시안/완성본/B-고밀도작업대/5-요약행렬).

확정된 검토구간 집합 × 편차(results.load_deviations) 행렬과 칸별 워크시트. Claude API가 칸을 'AI 초안' 항목으로 채우고
(ai_cells, 작업 스레드는 ai_runner) 사람이 항목을 수정·승인·기각한다. 결과는 바뀔 때마다 results.save로 저장하고
화면을 다시 열면 results.load로 읽는다(확정 구간이 바뀐 저장본은 쓰지 않고 빈 결과로 시작).
AI가 쓴 항목은 승인 전까지 언제나 'AI 초안'으로 표시한다(results.is_ai_draft).
워크시트 아래 '초기사건 판정' 줄은 고른 항목의 ie_hint를 칩으로 보이고(AI 값은 점선 칩, 사람이 정한 값은 채운 칩),
항목 승인과 따로 확정한다(results.set_ie_hint, 기획서/초기사건-출력설계.md §5.3).
"""

import os
import time
from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import QEvent, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from hazop import store_io
from hazop.app import conn_view, data, project_ctx, tokens
from hazop.app.ai_runner import AiRunner, RunMachine
from hazop.app.conn_widgets import NoticeBand, ResolveBand
from hazop.app.screens.results_matrix import MatrixModel, MatrixView, empty_cell_label
from hazop.app.screens.results_paint import DRAFT_ROLE, CellDelegate, GroupHeader, SheetDelegate
from hazop.app.screens.study import seg_icon
from hazop.app.settings_dialog import ACTION_HELP, ask_terms
from hazop.app.widgets import Banner, Chip, empty_label, kst_text, plain_label
from hazop.export import study_xlsx
from hazop.graph import project
from hazop.study import ai_cells, claude_cli, claude_http, node_review, nodes, providers, refs, span
from hazop.study import results as res

AI_NOTE = "AI 결과는 모두 초안 · 사람이 수정·승인·기각"
STATUS_LABELS = {"proposed": "제안", "revised": "수정", "approved": "승인", "rejected": "기각"}
BAND_LABELS = {"ok": "수용", "cond": "조건부 수용", "deny": "불허"}  # tokens.risk_band 구분
SHEET_COLUMNS = ("원인", "결과(보호수단 실패 가정)", "보호수단", "권고", "위험도", "AI 근거", "상태")
CONSEQUENCE_TIP = ("비완화 결과: 보호수단이 하나도 작동하지 않는다고 보고 쓴 결과입니다. "
                   "보호수단이 막아 주는 결과('영향 없음', '경보 후 회복')는 여기에 쓰지 않습니다.")
COL_RISK, COL_BASIS, COL_STATUS = 4, 5, 6
CELL_W, ROW_H, ROW_HEAD_W = 54, 30, 210  # U-20: 1366에서 편차 열 약 11개가 보이게 칸 한 줄
RISK_KEYS = ("칸 숫자 = 최고 위험도 · 미N = 미검토 시나리오 · – 분석 전 · 없음 = AI 초안(해당 없음·시나리오 없음) · "
             "! 실패 = AI 실행 실패(위험도 아님) · 한도로 멈춤 = 구독 한도에 닿아 호출하지 못한 칸(다시 실행)")
CANCEL_TIP = "남은 호출을 멈춤(진행 중인 호출은 끝까지 받아 반영)"
CANCEL_NOW = "바로 끊기"
CANCEL_NOW_TIP = "진행 중인 호출도 바로 끊습니다(그 호출의 결과는 받지 않음)"
NAV_KEYS = "←↑↓→ 칸 이동 · Enter 열기 · J 다음 미검토 · 워크시트 A 승인 · R 기각 · E 수정 · I 초기사건 판정 · Ctrl+Z 실행 취소"
EDIT_TEXT_FIELDS = (("cause", "원인"), ("consequence", "결과"), ("recommendation", "권고"))
# 옛 도면별 결과에서 옮긴 항목 표시(project_ctx.migrate_results). 사람 상태는 그대로 두고 다시 보게만 한다.
ENTRY_FLAGS = (("scope_changed", "범위 바뀜 · 다시 확인", "옛 도면별 구간과 범위가 달라진 구간으로 옮긴 항목"),
               ("source_stale", "옛 결과 · 다시 확인", "옛 확정본과 이미 맞지 않던 옛 결과에서 옮긴 항목"))
NEED_ROW = {"approved": "승인할", "rejected": "기각할", "edit": "수정할", "ie": "초기사건을 판정할"}


def design_intent(node, review=None):
    """구간 JSON(data/regions) 중 이 구간의 구성요소(프로젝트 ID)를 모두 포함하는 것의 설계 의도.
    (글, 출처 설명) 또는 None. 구간 JSON은 도면 하나 기준이라 구성요소를 그 도면의 프로젝트 ID로 바꿔 비교한다.
    상위 구간의 설계 의도이므로 화면에 출처와 지식 상태를 함께 적는다.
    구간 JSON에 없으면 ④ AI 구간 검토에서 사람이 받아들인 설계 의도 초안(review = node_review 묶음)을 쓴다.
    구간 자체에 적은 설계 의도(검토구간 규격 v2 node.design_intent)가 있으면 그것이 먼저다(바뀌면 분석 판이 오름)."""
    own = node.get("design_intent") or {}
    if own.get("text"):
        return own["text"], "이 구간의 설계 의도 · %s가 씀" % {"ai": "AI", "user": "사람", "script": "규칙"}.get(
            own.get("by"), own.get("by") or "-")
    members = set(node["members"])
    for path in data.list_regions():
        try:
            region = data.read_json(path)
        except (OSError, ValueError):
            continue
        gid = (region.get("graph_ref") or {}).get("graph_id")
        if not gid:
            continue
        scope = set(project.lift_ids(gid, [m.get("entity_id") for m in region.get("members") or [] if m.get("entity_id")]))
        intent = region.get("design_intent") or {}
        if members and members <= scope and intent.get("text"):
            return intent["text"], "상위 구간 %s · 지식 상태 %s" % (
                region.get("name") or os.path.basename(path), intent.get("knowledge_status") or "-")
    drafted = node_review.accepted_intent(review, node) if review else None
    return (drafted, "AI 초안 · ④ AI 구간 검토에서 사람이 받아들임") if drafted else None


def risk_text(risk):
    band = tokens.risk_band(risk)
    return "%d %s" % (risk, BAND_LABELS[band]) if band else "미정"


# 실행 전 확인 창의 어림값(기본 모델 Opus 기준). 사용자 실사용 관찰(2026-11-07): 호출 하나 15~60초, 50회 약 $4~5.
# 결정로그: 구간 1개(10회) Opus 실측 $0.86. 같은 모델로 성공한 호출 기록이 있으면 그 평균을 쓴다.
EST_SEC_PER_CALL = 40
EST_USD_PER_CALL = 0.09


def clock(seconds):
    m, s = divmod(int(seconds), 60)
    return "%d:%02d" % (m, s) if m < 60 else "%d시간 %d분" % (m // 60, m % 60)


def usage_diff(now, base):
    return {k: now[k] - base.get(k, 0) for k in now}


class RefPicker(QWidget):
    """그래프 대상 고르기: 찾기 칸 + 체크 목록. 지금 참조(대상이 없어진 것 포함)를 맨 위에 체크해 두어 조용히 빠지지 않게 한다.
    choices [(안정 참조, 표시 글)]은 구간 구성요소가 먼저 온다."""

    def __init__(self, name, current, choices, label_of, height=96, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.find = QLineEdit()
        self.find.setPlaceholderText("태그로 찾기")
        self.find.setAccessibleName("%s 찾기" % name)
        self.find.textChanged.connect(self._filter)
        v.addWidget(self.find)
        self.list = QListWidget()
        self.list.setAccessibleName(name)
        self.list.setFixedHeight(height)
        seen = set()
        for ref in current:
            self._add(ref, label_of(ref), True)
            seen.add(ref)
        for ref, text in choices:
            if ref not in seen:
                self._add(ref, text, False)
                seen.add(ref)
        v.addWidget(self.list)

    def _add(self, ref, text, checked):
        it = QListWidgetItem(text)
        it.setData(Qt.UserRole, ref)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.list.addItem(it)

    def _filter(self, text):
        q = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(q) and q not in it.text().lower() and it.checkState() != Qt.Checked)

    def set_checked(self, ref, on=True):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == ref:
                self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
                return True
        return False

    def checked(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


def _keep_refs(chosen, old, extra_keys=()):
    """고른 참조 -> [{ref, ...}]. 원래 있던 참조는 원래 값(origin·고장 모드)을 그대로, 새로 고른 것은 origin human."""
    by_ref = {r.get("ref"): r for r in old or [] if isinstance(r, dict)}
    out = []
    for ref in chosen:
        o = by_ref.get(ref)
        out.append({k: o[k] for k in ("ref", "origin") + tuple(extra_keys) if k in o} if o else
                   {"ref": ref, "origin": "human"})
    return out


class EntryDialog(QDialog):
    """항목 수정: 원인·결과·보호수단(한 줄에 하나)과 역할·구현 대상·권고·강도·발생빈도, 원인 위치·영향 대상·관련 잠재 후보.
    changed()는 바뀐 필드만 돌려준다. ref_ctx가 없으면(그래프 없음) 참조 고르기 칸을 숨기고 지금 참조는 그대로 둔다.
    ref_ctx: {"choices": [(안정 참조, 표시 글)], "label": 참조 -> 표시 글, "expectations": [(잠재 후보 ID, 표시 글)]}."""

    SG_COLUMNS = ("보호수단", "역할", "작동 방식", "구현 대상")

    def __init__(self, entry, parent=None, ref_ctx=None):
        super().__init__(parent)
        self.entry = entry
        self.ref_ctx = ref_ctx
        self.label_of = (ref_ctx or {}).get("label") or (lambda r: r)
        self.setWindowTitle("항목 수정")
        self.setMinimumWidth(480 if ref_ctx is None else 900)
        outer = QVBoxLayout(self)
        cols = QHBoxLayout()
        outer.addLayout(cols)
        lay = QFormLayout()
        cols.addLayout(lay, 3)
        self.texts = {}
        for key, label in EDIT_TEXT_FIELDS:
            ed = QPlainTextEdit(entry.get(key) or "")
            ed.setFixedHeight(60)
            ed.setAccessibleName(label)
            if key == "consequence":
                ed.setToolTip(CONSEQUENCE_TIP)
            self.texts[key] = ed
            lay.addRow("결과\n(보호수단 실패 가정)" if key == "consequence" else label, ed)
        # 줄 순서로 원래 보호수단과 짝짓는다. 같은 문장의 보호수단이 둘일 수 있어 문장을 열쇠로 쓰면 하나로 합쳐진다
        raws = [s for s in entry.get("safeguards") or [] if isinstance(s, (str, dict))]
        self.sg_orig = list(zip(raws, refs.safeguard_items({"safeguards": raws})))
        self.safeguards = QPlainTextEdit("\n".join(refs.safeguard_texts(entry)))
        self.safeguards.setFixedHeight(60)
        self.safeguards.setAccessibleName("보호수단")
        lay.insertRow(2, "보호수단\n(한 줄에 하나)", self.safeguards)
        self.sg_table = QTableWidget(0, len(self.SG_COLUMNS))
        self.sg_table.setAccessibleName("보호수단 역할·작동 방식·구현 대상")
        self.sg_table.setHorizontalHeaderLabels(list(self.SG_COLUMNS))
        self.sg_table.verticalHeader().hide()
        self.sg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sg_table.setFixedHeight(96)
        lay.insertRow(3, "역할·작동·대상", self.sg_table)
        self.safeguards.textChanged.connect(self._sync_safeguards)
        self._sync_safeguards()
        self.sev = self._combo(res.SEVERITIES, entry.get("severity"))
        self.sev.setAccessibleName("강도")
        self.freq = self._combo(res.FREQUENCIES, entry.get("frequency"))
        self.freq.setAccessibleName("발생빈도")
        lay.addRow("강도(1–4)", self.sev)
        lay.addRow("발생빈도(1–3)", self.freq)
        self.cause_kind = QComboBox()
        self.cause_kind.setAccessibleName("원인 유형")
        self.cause_kind.addItem(res.UNKNOWN_LABEL, None)
        for key, name in res.CAUSE_KINDS.items():
            self.cause_kind.addItem(name, key)
        self.cause_kind.setCurrentIndex(max(self.cause_kind.findData(entry.get("cause_kind")), 0))
        lay.insertRow(1, "원인 유형", self.cause_kind)
        self.basis = QCheckBox("보호수단이 모두 실패했다고 보고 쓴 결과(비완화)")
        self.basis.setAccessibleName("비완화 결과 확인")
        self.basis.setToolTip(CONSEQUENCE_TIP)
        self.basis.setChecked(entry.get("consequence_basis") == "unmitigated")
        lay.insertRow(3, "결과 기준", self.basis)
        self.pickers = {}
        if ref_ctx is not None:
            right = QFormLayout()
            cols.addLayout(right, 2)
            for key, title in refs.REF_FIELDS:
                p = RefPicker(title, [r.get("ref") for r in entry.get(key) or [] if isinstance(r, dict)],
                              ref_ctx["choices"], self.label_of)
                self.pickers[key] = p
                right.addRow(title, p)
            xs = dict(ref_ctx.get("expectations") or [])
            p = RefPicker("관련 잠재 후보", list(entry.get("expectation_refs") or []),
                          list(xs.items()), lambda x: xs.get(x) or "%s %s" % (x, refs.MISSING), height=80)
            self.pickers["expectation_refs"] = p
            right.addRow("관련 잠재 후보", p)
            hint = QLabel("원인 위치·영향 대상은 이 검토구간 구성요소가 먼저 나옵니다. 잠재 후보는 근거가 아니라 확인할 단서입니다.")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            right.addRow(hint)
        note = QLabel("고치면 상태가 '수정'이 됩니다. 승인한 항목도 다시 승인해야 합니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        outer.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확인")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def _target_choices(self, current):
        """구현 대상 고르기 항목 [(표시 글, 참조 목록)]. 지금 참조가 여럿이면 그 묶음을 한 항목으로 둔다(잃지 않게)."""
        out = [("지정 안 함", [])]
        if len(current) > 1:
            out.append(("여러 대상: %s" % ", ".join(self.label_of(r) for r in current), list(current)))
        elif current:
            out.append((self.label_of(current[0]), list(current)))
        for ref, text in (self.ref_ctx or {}).get("choices") or []:
            if [ref] != current:
                out.append((text, [ref]))
        return out

    def _sg_state(self):
        """표의 지금 상태 [(역할, 작동 방식, 참조 목록)] (줄 순서)."""
        return [tuple(self.sg_table.cellWidget(r, c).currentData() for c in (1, 2, 3))
                for r in range(self.sg_table.rowCount())]

    def _sg_lines(self):
        return [s.strip() for s in self.safeguards.toPlainText().splitlines() if s.strip()]

    def _sync_safeguards(self):
        """보호수단 글이 바뀌면 줄마다 역할·구현 대상 행을 다시 만든다. 같은 순서의 행이 고른 값을 이어받는다."""
        state = self._sg_state()
        lines = self._sg_lines()
        t = self.sg_table
        t.setRowCount(len(lines))
        for r, text in enumerate(lines):
            if r < len(state):
                role, actuation, targets = state[r]
            elif r < len(self.sg_orig):
                old = self.sg_orig[r][1]
                role, actuation = old["role"], old["actuation"]
                targets = [x.get("ref") for x in old["refs"] if x.get("ref")]
            else:
                role, actuation, targets = "unknown", "unknown", []
            it = QTableWidgetItem(text)
            it.setToolTip(text)
            t.setItem(r, 0, it)
            rc = QComboBox()
            rc.setAccessibleName("역할 %d" % (r + 1))
            for key, name in refs.ROLES.items():
                rc.addItem(name, key)
            rc.setCurrentIndex(max(rc.findData(role), 0))
            t.setCellWidget(r, 1, rc)
            ac = QComboBox()
            ac.setAccessibleName("작동 방식 %d" % (r + 1))
            for key, name in refs.ACTUATIONS.items():
                ac.addItem(name, key)
            ac.setCurrentIndex(max(ac.findData(actuation), 0))
            t.setCellWidget(r, 2, ac)
            tc = QComboBox()
            tc.setAccessibleName("구현 대상 %d" % (r + 1))
            for name, refs_ in self._target_choices(targets):
                tc.addItem(name, refs_)
            tc.setCurrentIndex(1 if targets else 0)
            t.setCellWidget(r, 3, tc)

    def _safeguards_value(self):
        """줄마다 같은 순서의 원래 보호수단과 비교한다. 문자열 줄은 역할·작동 방식 미정·구현 대상 없음이면 문자열(옛 형식)
        그대로. 객체 줄은 문장·역할·작동 방식·구현 대상이 모두 같으면 원래 값(AI 초안 표시 origin 포함) 그대로 두고,
        무엇이든 바뀌면 나머지 키·참조(대상 없는 참조 포함)를 이어받은 채 그 줄만 origin human이 된다."""
        state = self._sg_state()
        out = []
        for r, text in enumerate(self._sg_lines()):
            role, actuation, targets = state[r] if r < len(state) else ("unknown", "unknown", [])
            raw = self.sg_orig[r][0] if r < len(self.sg_orig) else None
            if not isinstance(raw, dict):
                out.append(text if role == "unknown" and actuation == "unknown" and not targets else dict(
                    {"text": text, "role": role, "refs": _keep_refs(targets, None), "ipl": None, "origin": "human"},
                    **({"actuation": actuation} if actuation != "unknown" else {})))
                continue
            if (raw.get("text") or "").strip() == text and raw.get("role", "unknown") == role and \
                    raw.get("actuation", "unknown") == actuation and \
                    [x.get("ref") for x in raw.get("refs") or [] if isinstance(x, dict)] == targets:
                out.append(raw)
                continue
            new = dict(raw, text=text, role=role, refs=_keep_refs(targets, raw.get("refs")), origin="human")
            if actuation != "unknown" or "actuation" in raw:  # 옛 객체에 미확인 값을 새로 쓰지 않는다
                new["actuation"] = actuation
            out.append(new)
        return out

    @staticmethod
    def _combo(values, current):
        cb = QComboBox()
        cb.addItem("미정", None)
        for v in values:
            cb.addItem(str(v), v)
        cb.setCurrentIndex(values.index(current) + 1 if current in values else 0)
        return cb

    def fields(self):
        out = {k: ed.toPlainText().strip() for k, ed in self.texts.items()}
        out["safeguards"] = self._safeguards_value()
        out["severity"] = self.sev.currentData()
        out["frequency"] = self.freq.currentData()
        out["cause_kind"] = self.cause_kind.currentData()
        out["consequence_basis"] = "unmitigated" if self.basis.isChecked() else None
        for key, _title in refs.REF_FIELDS:
            if key in self.pickers:
                out[key] = _keep_refs(self.pickers[key].checked(), self.entry.get(key),
                                      ("failure_mode",) if key == "cause_refs" else ())
        if "expectation_refs" in self.pickers:
            out["expectation_refs"] = self.pickers["expectation_refs"].checked()
        return out

    def changed(self):
        """바뀐 필드. 참조 필드는 없던 것과 빈 목록을 같게 본다(옛 항목에 빈 필드를 새로 쓰지 않음)."""
        out = {}
        for k, v in self.fields().items():
            old = self.entry.get(k)
            if k in ("cause_refs", "consequence_refs", "expectation_refs"):
                if (old or []) != v:
                    out[k] = v
            elif k in ("cause_kind", "consequence_basis"):
                if old != v:
                    out[k] = v
            elif old != v:
                out[k] = v
        return out


class IeHintDialog(QDialog):
    """초기사건 판정(ie_hint) 정하기: 후보·제외·보류, 정상운전 교란, 안전기능 도전, 일반 범주, 안전기능, 이유.
    확인하면 사람이 정한 판정이 되고 항목 상태(승인 등)는 바뀌지 않는다."""

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.setWindowTitle("초기사건 판정")
        self.setMinimumWidth(520)
        h = entry.get("ie_hint") if isinstance(entry.get("ie_hint"), dict) else {}
        lay = QFormLayout(self)
        self.combos = {}
        for key, title, values, default in (("candidate", "초기사건 후보", res.IE_CANDIDATES, "undecided"),
                                            ("disturbs", "정상운전 교란", res.IE_ANSWERS, "unknown"),
                                            ("challenges", "안전기능 도전", res.IE_ANSWERS, "unknown")):
            cb = QComboBox()
            cb.setAccessibleName(title)
            for k, name in values.items():
                cb.addItem(name, k)
            cb.setCurrentIndex(max(cb.findData(h.get(key, default)), 0))
            self.combos[key] = cb
            lay.addRow(title, cb)
        self.category = QComboBox()
        self.category.setAccessibleName("일반 범주")
        self.category.addItem(res.UNCLASSIFIED_LABEL, None)
        for c in res.ie_categories():
            self.category.addItem(res.ie_category_label(c["code"]), c["code"])
        self.category.setCurrentIndex(max(self.category.findData(h.get("category")), 0))
        lay.addRow("일반 범주", self.category)
        self.functions = QLineEdit(", ".join(h.get("safety_functions") or []))
        self.functions.setAccessibleName("도전받는 안전기능")
        self.functions.setPlaceholderText("쉼표로 나눔. 예: 노심 냉각, 원자로냉각재 재고 유지")
        lay.addRow("안전기능", self.functions)
        self.reason = QPlainTextEdit(h.get("reason") or "")
        self.reason.setAccessibleName("판정 이유")
        self.reason.setFixedHeight(60)
        lay.addRow("판정 이유", self.reason)
        note = QLabel("항목 승인과 따로 확정합니다. 확인하면 사람이 정한 판정으로 저장되고 항목 상태는 그대로입니다. "
                      "맞는 범주가 없으면 일반 과도사건(TRANS)으로 넣지 말고 미분류로 두세요.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확정")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def hint(self):
        out = {k: cb.currentData() for k, cb in self.combos.items()}
        out.update(category=self.category.currentData(), reason=self.reason.toPlainText(),
                   safety_functions=[x.strip() for x in self.functions.text().split(",") if x.strip()])
        return out


def ie_chips(entry):
    """초기사건 판정 줄 칩 [(글, 상태)]. 상태 ai = AI 초안(점선), human = 사람이 정함(채움)."""
    h = entry.get("ie_hint") if isinstance(entry.get("ie_hint"), dict) else None
    if h is None:
        return [("미판정", "")]
    st = "human" if h.get("origin") == "human" else "ai"
    return [(res.IE_CANDIDATES.get(h.get("candidate"), "보류"), st),
            ("교란 %s · 도전 %s" % (res.IE_ANSWERS.get(h.get("disturbs"), "모름"),
                                 res.IE_ANSWERS.get(h.get("challenges"), "모름")), st),
            (res.ie_category_label(h.get("category")), st),
            ("사람 확정" if st == "human" else "AI 초안", "" if st == "human" else "warn")]


class ExportDialog(QDialog):
    """Excel 내보내기 범위: 전체 / 승인만 / 선택한 구간만(목록에서 고름, 기본은 행렬에서 고른 구간) + 검토자."""

    def __init__(self, nodes, selected, reviewer="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Excel로 내보내기")
        self.setMinimumWidth(460)
        lay = QFormLayout(self)
        self.scope = QComboBox()
        self.scope.setAccessibleName("내보낼 범위")
        for key, label in study_xlsx.SCOPES.items():
            self.scope.addItem(label, key)
        lay.addRow("범위", self.scope)
        self.nodes = QListWidget()
        self.nodes.setAccessibleName("내보낼 구간")
        self.nodes.setFixedHeight(140)
        for n in nodes:
            it = QListWidgetItem(project_ctx.node_label(n))
            it.setData(Qt.UserRole, n["node_id"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if n["node_id"] == selected else Qt.Unchecked)
            self.nodes.addItem(it)
        lay.addRow("구간", self.nodes)
        self.reviewer = QLineEdit(reviewer)
        self.reviewer.setAccessibleName("검토자")
        self.reviewer.setPlaceholderText("표지에 적을 이름(비워도 됨)")
        lay.addRow("검토자", self.reviewer)
        note = QLabel(AI_NOTE + ". 표지에도 같은 고지를 적습니다.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("저장 위치 고르기…")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.scope.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        self.nodes.setEnabled(self.scope.currentData() == "nodes")

    def node_ids(self):
        return [self.nodes.item(i).data(Qt.UserRole) for i in range(self.nodes.count())
                if self.nodes.item(i).checkState() == Qt.Checked]

    def accept(self):
        if self.scope.currentData() == "nodes" and not self.node_ids():
            QMessageBox.information(self, "Excel로 내보내기", "내보낼 구간을 하나 이상 고르세요.")
            return
        super().accept()


RESUME_KINDS = ("limit_reached", "overage", "cancelled", "not_ready", "auth_mismatch")  # 기술 설계 §11 3번 (가)
RESUME_API_NOTE = "이번 남은 호출만 API 키로 돌립니다. 끝나면 Claude 구독으로 돌아갑니다."
FIXED_NOTE = "시험 결과는 실제 결과와 따로 시험용 파일에 저장합니다."
OVERAGE_TEXT = ("구독 한도가 거의 찼고 초과 사용(유료)이 켜져 있습니다. 한도를 넘은 호출에는 요금이 붙을 수 있습니다. "
                "초과 사용을 허용하지 않았으므로 한도를 넘는 순간 남은 호출을 멈춥니다. 시작할까요?")


class RunConfirmDialog(QDialog):
    """AI 실행 확인(화면 설계 §6): 폭 460, 칸 이름 왼쪽·값 오른쪽. 시작(&S)이 기본 단추이고 Esc는 취소.
    ask() -> 'start' · 'change'('바꾸기…') · None."""

    CHANGE = 2

    def __init__(self, method, lead, rows, note="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("시험 실행" if method == "fixed" else "AI 분석 시작")
        self.setFixedWidth(460)
        self.setMaximumHeight(480)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        if note:
            self.note = QLabel(note)
            self.note.setWordWrap(True)
            self.note.setStyleSheet("QLabel { background: %s; color: %s; border: 1px solid %s; border-radius: 3px; "
                                    "padding: 4px 6px; }" % (tokens.c("ui-weak"), tokens.c("ui-ink"), tokens.c("ui")))
            v.addWidget(self.note)
        self.lead = QLabel(lead)
        self.lead.setWordWrap(True)
        self.lead.setStyleSheet("font-weight: 700")
        v.addWidget(self.lead)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        self.values = {}
        for r, (name, value, say) in enumerate(rows):
            lab = QLabel(name)
            lab.setObjectName("muted")
            grid.addWidget(lab, r, 0, Qt.AlignTop)
            val = QLabel(value)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setAccessibleName(say)
            if name == "비용":
                val.setStyleSheet("font-weight: 700")
            if name == "연결":
                box = QHBoxLayout()
                box.setSpacing(6)
                box.addWidget(val, 1)
                self.change_btn = QPushButton("바꾸기…")
                self.change_btn.setAutoDefault(False)
                self.change_btn.clicked.connect(lambda: self.done(self.CHANGE))
                box.addWidget(self.change_btn, 0, Qt.AlignTop)
                grid.addLayout(box, r, 1)
            else:
                grid.addWidget(val, r, 1)
            self.values.setdefault(name, []).append(val)
        v.addLayout(grid)
        if method == "fixed":
            test_note = QLabel(FIXED_NOTE)
            test_note.setWordWrap(True)
            test_note.setStyleSheet("QLabel { background: %s; color: %s; border: 1px dashed %s; border-radius: 3px; "
                                    "padding: 4px 6px; }" % (tokens.c("ai-hatch-a"), tokens.c("ai-ink"),
                                                            tokens.c("line-strong")))
            v.addWidget(test_note)
        row = QHBoxLayout()
        row.addStretch(1)
        self.start_btn = QPushButton("시험 시작(&S)" if method == "fixed" else "시작(&S)")
        self.start_btn.setObjectName("primary")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(self.start_btn)
        row.addWidget(cancel)
        v.addLayout(row)
        self.start_btn.setFocus()

    def texts(self):
        """시험·접근성 검사용: 보이는 글자 전부."""
        return "\n".join(w.text() for w in self.findChildren(QLabel))

    def fit(self):
        """줄바꿈 글자에 맞춰 높이를 다시 잡는다(남는 세로 공간이 줄 사이로 퍼지지 않게, 최대 480)."""
        self.setFixedHeight(min(480, self.layout().totalHeightForWidth(self.width())))

    def ask(self):
        self.fit()
        r = self.exec()
        return "start" if r == QDialog.Accepted else "change" if r == self.CHANGE else None


class ResolveDialog(QDialog):
    """실행할 수 없는 상태일 때 실행 확인 대신 뜨는 해결 안내(§6 끝, §9). choice는 고른 해결 동작 이름 또는 'settings'."""

    def __init__(self, method, status, count=0, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle("AI 분석을 시작할 수 없습니다")
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        self.band = ResolveBand()
        lk = conn_view.look(method, (status or {}).get("state") or "error")
        acts = tuple(a for a in lk.actions if a in ACTION_HELP or a in ("check", "to_api", "copy_error", "open_logs")
                     and (a != "to_api" or "api" in providers.available_methods()))
        self.band.set_band(lk, conn_view.guide_text(method, status, count), acts)
        self.band.action.connect(self._pick)
        v.addWidget(self.band)
        row = QHBoxLayout()
        row.addStretch(1)
        settings = QPushButton("AI 연결 설정…")
        settings.clicked.connect(lambda: self._pick("settings"))
        close = QPushButton("닫기")
        close.setDefault(True)
        close.clicked.connect(self.reject)
        row.addWidget(settings)
        row.addWidget(close)
        v.addLayout(row)

    def _pick(self, name):
        self.choice = name
        self.accept()


class CloseWaitBox(QDialog):
    """'기다렸다 닫기' 동안 남은 시간을 보이는 창(모달 아님). '바로 끊고 닫기'로 기다림을 끝낼 수 있다."""

    def __init__(self, on_now, parent=None):
        super().__init__(parent)
        self.setWindowTitle(conn_view.CLOSE_TITLE)
        self.setModal(False)
        self.setMinimumWidth(400)
        v = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setWordWrap(True)
        v.addWidget(self.label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.now_btn = QPushButton(conn_view.CLOSE_NOW)
        self.now_btn.clicked.connect(on_now)
        row.addWidget(self.now_btn)
        v.addLayout(row)

    def set_left(self, text):
        self.label.setText(conn_view.CLOSE_WAITING % text)
        self.label.setAccessibleName(self.label.text())
        if not self.isVisible():
            self.show()

    def reject(self):  # Esc는 창만 숨긴다(기다림은 계속)
        self.hide()


EMPTY_TITLE = "아직 볼 분석 결과가 없습니다"
KEPT_TITLE = "검토구간 확정을 해제해 결과를 숨겼습니다"
KEPT_TEXT = ("이미 만든 분석 결과는 지우지 않고 보관해 두었습니다. "
             "④ 검토구간에서 다시 확정하면 같은 구간의 결과가 다시 보입니다.")
EXPORT_KEPT = ("검토구간 확정을 해제해 분석 결과를 숨긴 상태라 내보낼 수 없습니다. "
               "결과는 보관해 두었으니 ④에서 다시 확정한 뒤 내보내세요.")


def failure_note(info, left):
    """진행 글자 뒤에 붙는 실패 수. 이번 실행의 실패(info['failed'])와 결과 파일 전체에 남은 실패 칸(left)은
    서로 다른 수라 섞지 않고 이름을 달리 붙인다. 칸 하나를 돌릴 때 'AI 0/1 호출 · 실패 12'처럼 보이지 않게."""
    now = len((info or {}).get("failed") or [])
    return (" · 이번 실패 호출 %d" % now if now else "") + (" · 결과에 남은 실패 칸 %d" % left if left else "")


def is_limit_stop(run):
    """구독 한도로 멈춘 칸(실패와 구분, D6)."""
    return (run or {}).get("status") == "failed" and (run or {}).get("error_kind") == "limit_reached"


def _status(node):
    return ((node or {}).get("screen") or {}).get("status") or "keep"


class ResultsScreen(QWidget):
    title = "⑤ 분석 결과"
    CLOSE_WAIT_SEC = 120  # 창 닫기 '기다렸다 닫기'의 최대 대기(U9)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.name = None
        self.ctx = None        # project_ctx.ProjectContext(고른 도면 기준)
        self.graph = None      # 프로젝트 그래프(ctx.pg)
        self.node_set = None   # 확정된 프로젝트 검토구간 집합만(저장·결과 기준은 이 원본)
        self.view = {}         # {node_id: 표기·경계를 붙인 구간(ctx.view)} 화면 표시용
        self.results = None
        self.summary_of = (None, None)
        self._empty = (None, None)
        self.kg, self.kg_reason = None, None
        self.node_review = None
        self.expectations = None  # 잠재 후보(expect.evaluate). AI 맥락·관련 잠재 후보 보기용, 근거 아님
        self.ref_idx = {}         # {안정 참조: 프로젝트 그래프 노드}
        self.deviations = res.load_deviations()
        self.cell = None       # (node_id, deviation_id)
        self.runner = None
        self.machine = RunMachine()  # 실행 수명(기술 설계 §6.4). running()·창 닫기·취소는 이 상태만 본다
        self._pending = None   # 연결 확인 중인 요청 {"scope", "units", "method", "ask", "override"}
        self.run_method = None  # 지금(또는 마지막) 실행의 연결 방식
        self.run_info = None   # 실행 중: {"start", "base"(시작 때 사용량), "unit", "method", "override", 집계…}
        self.last_run = None   # 멈춘 실행에서 이어서 돌릴 칸(메모리에만)
        self.fixed_view = False  # 시험용 결과 파일(고정 응답)을 보는 중
        self.in_progress = set()  # 지금 호출 중인 칸 (node_id, deviation_id)
        self._orphans = []     # 끊을 수 없어 두고 닫은 실행(데몬 작업자가 끝날 때까지 살려 둠)
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._limit_reset_check)
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(1000)
        self._close_timer.timeout.connect(self._close_tick)
        self._close_deadline = 0.0
        self._close_wait_box = CloseWaitBox(self._close_now, self)
        self.tick = QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(self._progress_text)
        self._fps = {}          # {결과 파일 경로: 화면이 읽거나 쓴 내용의 지문}. 저장할 때 그 뒤 바뀐 파일을 덮어쓰지 않게 한다
        self._unsaved = False   # 마지막 저장이 실패해 화면에만 있는 변경이 있음
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)  # U-20: 1366에서 편차 열 약 11개(가운데 폭 − 행 머리 210) ÷ 54
        lay.setSpacing(4)
        bar = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setToolTip("도면(행렬은 프로젝트 전체 구간, 고른 도면은 '이 도면' 기준)")
        self.combo.setAccessibleName("도면")
        self.combo.setMinimumWidth(140)
        self.combo.currentIndexChanged.connect(self._load)
        bar.addWidget(self.combo)
        self.kpi = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=6)  # 줄어도 툴팁에 전체(1366에 맞게)
        bar.addWidget(self.kpi, 1)
        bar.addLayout(self._toolbar())
        lay.addLayout(bar)
        self.banner = Banner("warn")  # 옛 도면별 저장본 이전 알림
        lay.addWidget(self.banner)
        self.test_band = NoticeBand()  # 시험 결과를 보는 중(§8.1)
        self.test_band.action.connect(self._band_action)
        lay.addWidget(self.test_band)
        self.run_band = NoticeBand()   # 한도 도달·도중 사건(§7.3·§7.4). 떠도 포커스를 옮기지 않는다(F6로 닿음)
        self.run_band.action.connect(self._band_action)
        lay.addWidget(self.run_band)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_page())

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(4)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        top_w = QWidget()
        top = QVBoxLayout(top_w)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(2)
        head = QHBoxLayout()
        self.ai_chip = Chip(AI_NOTE, elide=Qt.ElideRight)
        head.addWidget(self.ai_chip)
        self.stale_chip = Chip(elide=Qt.ElideRight)
        self.stale_chip.hide()
        head.addWidget(self.stale_chip)
        self.kg_chip = Chip(elide=Qt.ElideRight)
        self.kg_chip.hide()
        head.addWidget(self.kg_chip)
        head.addStretch(1)
        self.save_label = QLabel("")  # 결과 파일 위치·마지막 저장 시각. 누르면 폴더를 연다
        self.save_label.setObjectName("muted")
        self.save_label.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        self.save_label.linkActivated.connect(self._open_save_dir)
        head.addWidget(self.save_label)
        top.addLayout(head)
        self.matrix = MatrixView()
        self.matrix_model = MatrixModel(lambda row: seg_icon(row["color"], row["node"]["node_id"]), self.matrix)
        self.matrix.setModel(self.matrix_model)
        self.matrix.setObjectName("matrix")
        self.matrix.setAccessibleName("구간 × 편차 행렬")
        self.matrix.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.matrix.setSelectionMode(QAbstractItemView.SingleSelection)
        self.matrix.setHorizontalHeader(GroupHeader(self.matrix))
        self.matrix.horizontalHeader().setDefaultSectionSize(CELL_W)
        self.matrix.horizontalHeader().setMinimumSectionSize(CELL_W)
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.matrix.verticalHeader().setDefaultSectionSize(ROW_H)
        self.matrix.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.matrix.verticalHeader().setFixedWidth(ROW_HEAD_W)  # 긴 구간 이름은 줄임표 + 툴팁
        self.matrix.verticalHeader().setTextElideMode(Qt.ElideMiddle)  # 끝의 도면 범위 [101 → 102] ⇄를 남긴다
        self.matrix.setIconSize(QSize(30, 16))
        self.matrix.setWordWrap(False)
        self.matrix.setItemDelegate(CellDelegate(self.matrix))
        self.matrix.cellClicked.connect(lambda r, c: self.open_cell(self._node_at(r), self.deviations[c]["deviation_id"]))
        top.addWidget(self.matrix, 1)
        legend = plain_label(RISK_KEYS, name="muted", elide=Qt.ElideRight, min_chars=12)
        top.addWidget(legend)
        keys = plain_label(NAV_KEYS, name="muted", elide=Qt.ElideRight, min_chars=12)
        top.addWidget(keys)
        split.addWidget(top_w)
        split.addWidget(self._sheet())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([300, 420])
        bv.addWidget(split, 1)
        self.stack.addWidget(body)
        lay.addWidget(self.stack, 1)
        self._shortcuts()

    def _empty_page(self):
        """빈 상태(U-09): 제목 한 줄 + 이유 + 주 버튼 + 다음 단계."""
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        self.empty_title = title = QLabel(EMPTY_TITLE)
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        el.addWidget(title)
        self.empty = empty_label("확정된 검토구간이 없습니다. ④ 검토구간에서 구간을 확정하면 여기서 구간 × 편차 결과를 봅니다.")
        el.addWidget(self.empty)
        self.to_study_btn = QPushButton("④ 검토구간으로")
        self.to_study_btn.setObjectName("primary")
        self.to_study_btn.clicked.connect(lambda: self.app.go(5))
        el.addWidget(self.to_study_btn, 0, Qt.AlignHCenter)
        steps = empty_label("다음 단계: ④에서 구간 확정 → 여기서 'AI 일괄 분석' → 칸마다 AI 초안을 승인·기각·수정")
        el.addWidget(steps)
        el.addStretch(1)
        return empty

    def _toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(6)
        self.progress = QProgressBar()
        self.progress.setObjectName("thin")
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(80, 4)  # 1366에서 탐색기·관련 항목과 함께 창 안에 들어가게(결함 8)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("muted")
        row.addWidget(self.progress, 0, Qt.AlignVCenter)
        row.addWidget(self.progress_label)
        self.run_all_btn = QPushButton("AI 일괄 분석")
        self.run_all_btn.setObjectName("primary")
        self.run_all_btn.setToolTip("확정된 모든 구간 × 편차를 Claude API로 분석(사람이 손댄 항목은 유지)")
        self.run_all_btn.clicked.connect(lambda: self.request_ai("all"))
        self.run_node_btn = QPushButton("선택 구간 분석")
        self.run_node_btn.setToolTip("행렬에서 고른 행의 구간만 분석")
        self.run_node_btn.clicked.connect(lambda: self.request_ai("node"))
        self.retry_btn = QPushButton("실패 칸 다시 실행")
        self.retry_btn.setToolTip("마지막 AI 실행이 실패한 칸만 칸마다 다시 호출")
        self.retry_btn.clicked.connect(lambda: self.request_ai("failed"))
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setToolTip(CANCEL_TIP)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_ai)
        self.usage = QLabel()  # 토큰·비용은 도구 설명으로(도구줄 폭 절약)
        self.usage.hide()
        # 내보내기 두 가지를 버튼 하나의 메뉴로 묶는다. 버튼을 하나 더 두면 1366 폭과 ④⑤ 분할(U-03)에 도구줄이 들어가지 않는다
        self.export_btn = QPushButton("내보내기")
        self.export_btn.setToolTip("Excel 워크시트(전체·승인만·선택한 구간만) 또는 IE 인계 묶음(승인 항목만, Excel + JSON 원본)")
        menu = QMenu(self.export_btn)
        self.excel_action = menu.addAction("Excel로 내보내기…", lambda: self.export_excel())
        self.excel_action.setToolTip("구간 × 편차 결과를 HAZOP 워크시트 Excel(.xlsx)로 저장")
        self.ie_export_action = menu.addAction("IE 인계 묶음 내보내기…", lambda: self.export_ie_bundle())
        self.ie_export_action.setToolTip("⑥ 초기사건 화면으로 가서 승인 항목만으로 초기사건 인계 묶음을 저장. "
                                         "HAZOP 위험도는 넣지 않음")
        menu.setToolTipsVisible(True)
        self.export_btn.setMenu(menu)
        for w in (self.export_btn, self.retry_btn, self.run_node_btn, self.cancel_btn, self.run_all_btn):
            row.addWidget(w)
        return row

    def _sheet(self):
        frame = QFrame()
        frame.setObjectName("panel")
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)
        self.sheet_stack = QStackedWidget()
        self.sheet_stack.addWidget(empty_label("행렬의 칸을 누르면 구간 × 편차 워크시트가 열립니다."))
        sheet = QWidget()
        sv = QVBoxLayout(sheet)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(4)
        hrow = QHBoxLayout()
        self.sheet_badge = QLabel()
        hrow.addWidget(self.sheet_badge)
        self.sheet_title = plain_label("", elide=Qt.ElideRight, min_chars=12)
        self.sheet_title.setObjectName("title")
        hrow.addWidget(self.sheet_title)
        self.draft_chip = Chip()
        hrow.addWidget(self.draft_chip)
        self.intent = plain_label("", elide=Qt.ElideRight, min_chars=10)
        hrow.addWidget(self.intent, 1)
        self.sheet_count = QLabel()
        self.sheet_count.setObjectName("muted")
        hrow.addWidget(self.sheet_count)
        sv.addLayout(hrow)
        self.sheet_source = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=10)  # 출처 줄(§8.1)
        self.sheet_source.setAccessibleName("AI 초안 출처")
        self.sheet_source.hide()
        sv.addWidget(self.sheet_source)
        self.sheet_span = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=10)
        sv.addWidget(self.sheet_span)
        self.intent_src = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=10)
        sv.addWidget(self.intent_src)
        self.run_note = plain_label("", wrap=True)
        self.run_note.hide()
        sv.addWidget(self.run_note)
        self.table = QTableWidget(0, len(SHEET_COLUMNS))
        self.table.setAccessibleName("워크시트")
        self.table.setHorizontalHeaderLabels(list(SHEET_COLUMNS))
        self.table.horizontalHeaderItem(1).setToolTip(CONSEQUENCE_TIP)
        self.table.horizontalHeaderItem(COL_RISK).setToolTip("위험도 = 강도 × 발생빈도 〈표5〉(KOSHA P-86) · 구분 〈표9〉")
        self.table.horizontalHeaderItem(COL_BASIS).setToolTip("AI 근거: 지식그래프 경로 · 출처 문서 · ⚠ 근거 확인 경고. '확인할 단서'는 사람이 고른 잠재 후보(근거 아님)")
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setWordWrap(True)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        for c in (COL_RISK, COL_STATUS):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setItemDelegate(SheetDelegate(COL_BASIS, self.table))
        self.table.itemSelectionChanged.connect(self._update_entry_buttons)
        self.table.verticalScrollBar().valueChanged.connect(lambda _v: self._place_row_actions())
        # 창 폭이 바뀌어 열 폭이 달라지면 동작 버튼도 상태 칸을 따라간다. 머리말은 열을 하나씩 늘이며 신호를 내므로
        # 마지막 열까지 자리 잡은 뒤(이벤트 한 바퀴 뒤)에 놓는다
        hh.sectionResized.connect(lambda *_a: QTimer.singleShot(0, self._place_row_actions))
        self.table.viewport().installEventFilter(self)
        sv.addWidget(self.table, 1)
        # 행 단위 동작(U-21): 고른 행의 상태 칸 위에만 승인 A · 기각 R · 수정 E를 띄운다
        self.row_actions = QWidget(self.table.viewport())
        self.row_actions.setObjectName("row_actions")
        ra = QHBoxLayout(self.row_actions)
        ra.setContentsMargins(2, 2, 2, 2)
        ra.setSpacing(3)
        self.approve_btn = QPushButton("승인 A")
        self.approve_btn.clicked.connect(lambda: self.set_entry_status("approved"))
        self.reject_btn = QPushButton("기각 R")
        self.reject_btn.clicked.connect(lambda: self.set_entry_status("rejected"))
        self.edit_btn = QPushButton("수정 E")
        self.edit_btn.clicked.connect(lambda: self.edit_selected())
        for b in (self.approve_btn, self.reject_btn, self.edit_btn):
            b.setObjectName("row_btn")
            ra.addWidget(b)
        self.row_actions.hide()
        ie = QHBoxLayout()
        ie.setSpacing(4)
        self.ie_title = QLabel("초기사건 판정")
        self.ie_title.setObjectName("section")
        ie.addWidget(self.ie_title)
        self.ie_chips = []
        for i in range(4):
            c = Chip(min_chars=4)
            c.setAccessibleName("초기사건 판정 %d" % (i + 1))
            c.hide()  # 보이는 칩 수가 바뀌면 워크시트 폭이 달라져 행 동작 버튼 위치가 어긋나므로 처음부터 숨겨 둔다
            self.ie_chips.append(c)
            ie.addWidget(c)
        self.ie_reason = plain_label("", name="muted", elide=Qt.ElideRight, min_chars=10)
        ie.addWidget(self.ie_reason, 1)
        self.ie_btn = QPushButton("판정 I")
        self.ie_btn.setToolTip("고른 항목의 초기사건 판정을 정합니다(항목 승인과 따로)")
        self.ie_btn.clicked.connect(lambda: self.set_ie_selected())
        ie.addWidget(self.ie_btn)
        sv.addLayout(ie)
        act = QHBoxLayout()
        act.addStretch(1)
        self.rerun_cell_btn = QPushButton("이 칸 다시 실행")
        self.rerun_cell_btn.setToolTip("이 칸만 다시 AI 분석(승인·수정·기각한 항목은 유지)")
        self.rerun_cell_btn.clicked.connect(lambda: self.run_ai("cell"))
        act.addWidget(self.rerun_cell_btn)
        sv.addLayout(act)
        self.sheet_stack.addWidget(sheet)
        v.addWidget(self.sheet_stack, 1)
        return frame

    # ------------------------------------------------------------ 틀 연결
    def where(self):
        if not self.node_set:
            return None
        return {"drawing": (self.ctx.drawing_number if self.ctx else None) or self.name, "region": None, "run": None}

    def main_focus(self):
        """화면에 들어오면 초점: 칸이 열려 있으면 워크시트, 아니면 행렬(J·A·R·E가 바로 듣게)."""
        return self.table if self.sheet_stack.currentIndex() == 1 else self.matrix

    def is_done(self):
        return False

    def commands(self):
        """명령 팔레트(U-01) 항목 [(이름, 단축키, 함수)]."""
        return [("AI 일괄 분석", "", lambda: self.request_ai("all")), ("선택 구간 분석", "", lambda: self.request_ai("node")),
                ("실패 칸 다시 실행", "", lambda: self.request_ai("failed")), ("이 칸 다시 실행", "", lambda: self.run_ai("cell")),
                ("다음 미검토 칸", "J", self.next_unreviewed), ("칸 열기", "Enter", self.open_current),
                ("항목 승인", "A", lambda: self.set_entry_status("approved")),
                ("항목 기각", "R", lambda: self.set_entry_status("rejected")),
                ("항목 수정…", "E", lambda: self.edit_selected()),
                ("초기사건 판정…", "I", lambda: self.set_ie_selected()),
                ("칸 판정 다시 확인함", "", lambda: self.recheck_cell()),
                ("Excel로 내보내기…", "", lambda: self.export_excel()),
                ("IE 인계 묶음 내보내기…", "", lambda: self.export_ie_bundle()),
                ("이전 고정 응답 분석 열기", "", lambda: self.app.go(2))]

    def _shortcuts(self):
        """행렬·워크시트 단축키(U-02). 이 화면 안에서만 듣고, 글 입력칸에 초점이 있으면 입력이 먼저다."""
        keys = (("J", self.next_unreviewed), ("A", lambda: self.set_entry_status("approved")),
                ("R", lambda: self.set_entry_status("rejected")), ("E", lambda: self.edit_selected()),
                ("I", lambda: self.set_ie_selected()))
        self.keys = {}
        for seq, fn in keys:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self.keys[seq] = sc
        sc = QShortcut(QKeySequence("F6"), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.focus_band)
        self.keys["F6"] = sc
        for seq in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(seq), self.matrix)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self.open_current)
            self.keys[seq] = sc

    def open_current(self):
        r, c = self.matrix.currentRow(), self.matrix.currentColumn()
        if self.node_set is None or r < 0 or c < 0:
            return False
        return self.open_cell(self._node_at(r), self.deviations[c]["deviation_id"])

    def next_unreviewed(self):
        """J: 지금 칸 다음(행 순서)의 미검토 시나리오가 있는 칸을 연다. 끝에서는 처음으로 돌아간다."""
        if not self.results:
            return False
        summary = res.matrix_summary(self.results)
        order = [(n["node_id"], d["deviation_id"]) for n in self._rows() for d in self.deviations]
        start = order.index(self.cell) + 1 if self.cell in order else 0
        for key in order[start:] + order[:start]:
            if (summary.get(key[0], {}).get(key[1]) or {}).get("unreviewed"):
                return self.open_cell(*key)
        self.app.status_message("미검토 시나리오가 있는 칸이 없습니다.")
        return False

    def on_enter(self):
        if self.running():  # 실행 중에는 같은 결과를 계속 보여 준다(도면을 바꾸면 반영할 곳이 사라짐)
            return
        names = [e["name"] for e in data.list_extractions()]
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if cur in names:
            self.combo.setCurrentText(cur)
        self.combo.blockSignals(False)
        self._load()

    def show_node(self, drawing_name, node_id):
        """④에서 넘어온 구간: 그 도면을 고르고 행의 첫 칸 워크시트를 연다(확정 전이면 빈 화면 안내)."""
        if not self.running() and self.combo.findText(drawing_name) >= 0 and self.combo.currentText() != drawing_name:
            self.combo.setCurrentText(drawing_name)
        row = self._row_of(node_id)
        if row is not None:
            self.matrix.selectRow(row)
            self.open_cell(node_id, self.deviations[0]["deviation_id"])
        elif self.node_set and any(n["node_id"] == node_id for n in self.node_set["nodes"]):
            self.matrix.clearSelection()
            self.app.status_message("%s는 스크리닝 제외 구간이라 ⑤ 행이 없습니다. ④에서 꺼내면 볼 수 있습니다." % node_id)

    # ------------------------------------------------------------ 읽기
    def _load(self):
        if self.running():
            return
        if self._unsaved and self.results is not None and not self._save():
            # 저장하지 못한 검토 내용을 디스크 판으로 덮어쓰지 않는다
            self.combo.blockSignals(True)
            self.combo.setCurrentText(self.name or "")
            self.combo.blockSignals(False)
            self.app.status_message("저장하지 못한 분석 결과가 있어 다시 읽지 않음. 저장 위치를 확인하세요.")
            return
        name = self.combo.currentText()
        self.name, self.graph, self.node_set, self.results, self.cell = name or None, None, None, None, None
        self.ctx, self.view = None, {}
        self.kg, self.kg_reason = None, None
        self._fps = {}
        self.node_review = None
        self.expectations, self.ref_idx = None, {}
        self.fixed_view, self.last_run = False, None
        self.test_band.hide()
        self.run_band.hide()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_label.setText("")
        self.banner.set_messages(None)
        self.empty_title.setText(EMPTY_TITLE)
        self.results_kept = False  # 확정 해제로 결과를 숨기고 보관 중인지(본문·내보내기 안내가 같은 말을 하게)
        self.ctx = project_ctx.load(name) if name else None
        saved = None
        if self.ctx is not None and self.ctx.pg is None:
            self.empty.setText(self.ctx.error)
        elif self.ctx is not None:
            self.graph = self.ctx.pg
            try:
                saved, _was_saved = self.ctx.load_set()
            except (OSError, ValueError) as exc:
                self.empty.setText("검토구간 파일을 읽을 수 없음: %s" % exc)
            if self.ctx.problem:
                self.banner.set_messages("검토구간을 지금 그래프 판에 맞춰 저장하지 못함", [self.ctx.problem])
            if self.ctx.notice:
                self.banner.set_messages("옛 도면별 검토구간을 옮김", [self.ctx.notice])
        confirmed = bool(saved) and bool(nodes.active_nodes(saved))  # 확정·잠금 구간이 하나라도 있으면 연다(구간 밖과 상관없음)
        usable = confirmed and not nodes.is_stale(saved, self.graph)
        if confirmed and not usable:
            self.empty.setText("확정된 프로젝트 검토구간이 지금 도면들과 맞지 않습니다(도면이 바뀜). "
                               "④ 검토구간에서 다시 확인하세요.")
        if usable:
            self.node_set = saved
            self.view = {n["node_id"]: n for n in self.ctx.view(saved)["nodes"]}
            self.kg, self.kg_reason = ai_cells.load_kg_for(saved)
            try:
                self.node_review = node_review.load(saved.get("project_id"), saved["graph_id"])
            except (OSError, ValueError):
                self.node_review = None  # 제안 파일을 못 읽으면 AI 설계 의도 초안만 빠진다(④에서 알림)
            self.kg_chip.set_state("지식그래프 없음: %s · 도면만으로 분석" % self.kg_reason, "warn")
            self.kg_chip.setVisible(self.kg is None)
            self.ref_idx = refs.index(self.graph)
            self.expectations, x_note = ai_cells.expectations_for(self.graph, self.kg)
            if x_note:
                self.banner.set_messages("잠재 후보", list(self.banner.messages) + [x_note])
            self._migrate_results(saved)
            self.set_results(self._saved_results(saved))
            self._show_save_info()
            self.stack.setCurrentIndex(1)
        else:
            if self.ctx is None:
                self.empty.setText("이 도면의 그래프가 없습니다. ① 자료 등록에서 '추출·그래프 만들기'를 실행하세요."
                                   if name else "추출 결과가 없습니다. ①·②에서 도면을 등록·추출하세요.")
            elif saved is not None and not confirmed and self._has_saved_results(saved):
                self.results_kept = True
                self.empty_title.setText(KEPT_TITLE)
                self.empty.setText(KEPT_TEXT)
            elif saved is not None and not confirmed:
                self.empty.setText("프로젝트 검토구간이 아직 확정되지 않았습니다. ④ 검토구간에서 구간을 확정하세요."
                                   + (" (옛 도면별 검토구간을 옮겨 '제안' 상태로 두었습니다.)" if self.ctx.notice else ""))
            if (getattr(self.app, "selection", None) or {}).get("kind") == "cell":  # 행렬이 없으면 칸도 없다(관련 항목이 옛 칸을 말하지 않게)
                self.app.set_selection(None)
            self.kpi.setText("구간 — · 편차 %d" % len(self.deviations))
            self.stack.setCurrentIndex(0)
        self._update_buttons()
        self.app.update_header()

    @staticmethod
    def _has_saved_results(node_set):
        """확정 전 집합이라도 같은 프로젝트·그래프의 저장 파일에 실제 분석 결과(항목이 있거나 분석한 칸)가 있는지.
        확정 해제 뒤 보관 중인 결과를 말할 때만 참이다. 빈 결과 파일만 있으면 거짓."""
        try:
            doc = res.read_fp(res.store_path(node_set.get("project_id"), node_set["graph_id"]))[0]
        except (OSError, KeyError, TypeError, ValueError):
            return False
        return any(c.get("entries") or c.get("state") not in (None, "not_analyzed") for c in (doc or {}).get("cells") or [])

    def _migrate_results(self, node_set):
        """확정된 프로젝트 집합에 결과가 없고 옛 도면별 결과가 있으면 백업 뒤 옮겨 저장한다(migrate_results는 있는 프로젝트
        결과를 덮어쓰지 않음). 옮기지 못하면 사유만 띄우고 옛 파일은 그대로 둔다."""
        try:
            moved = project_ctx.migrate_results(self.graph, node_set)
        except (OSError, ValueError) as exc:
            self.app.log_error("옛 분석 결과 이전 실패", exc)
            moved = (None, "옛 분석 결과를 옮기지 못함(%s). 옛 파일은 그대로 있습니다." % exc)
        if moved is None:
            return
        doc, text = moved
        msgs = list(self.banner.messages) + [text]
        self.banner.set_messages("옛 도면별 분석 결과를 옮김" if doc is not None else "옛 분석 결과를 옮기지 않음", msgs)
        if doc is not None:
            self.app.toast("옛 도면별 분석 결과를 프로젝트 구간으로 옮겼습니다")

    def _saved_results(self, node_set):
        """저장본(칸마다 판을 맞춘 0.2, results.load_fp)을 돌려준다. 결과 전체를 빈 결과로 바꾸지 않는다(§2.4):
        칸 문제는 그 칸만 떼어 두고(저장할 때 그대로 다시 씀), 문서 문제나 읽을 수 없는 파일은 읽기 전용으로 연다."""
        path = res.store_path(node_set.get("project_id"), node_set["graph_id"])
        try:
            doc, self._fps[path] = res.load_fp(node_set, self.deviations)
        except (OSError, ValueError) as exc:
            self.stale_chip.set_state("저장된 분석 결과를 읽을 수 없음(%s) · 읽기 전용(파일은 그대로 둠)" % exc, "warn")
            self.stale_chip.show()
            return dict(self._empty_for(node_set), read_only="저장된 분석 결과를 읽을 수 없음(%s)" % exc)
        if doc is None:
            self.stale_chip.hide()
            return self._empty_for(node_set)
        doc, problems, cell_problems = res.partition(doc, node_set)
        notes = []
        if problems:
            doc = dict(doc, read_only="분석 결과 파일에 문제 %d건(%s)" % (len(problems), problems[0]))
            notes.append("%s · 읽기 전용(파일은 그대로 둠)" % doc["read_only"])
        if cell_problems:
            notes.append("문제 칸 %d개(따로 둠: %s)" % (len(doc.get("quarantined_cells") or []), cell_problems[0]))
        if doc.get("archived_cells"):
            notes.append("옛 결과 %d칸은 갈 구간이 없어 결과 파일의 보관 칸으로 둠(지우지 않음 · ⑤에서 옮기는 기능은 아직 없음)"
                         % len(doc["archived_cells"]))
        changed = sum(1 for c in doc["cells"] if not c.get("hold") for e in c["entries"] if e.get("scope_changed"))
        judged = sum(1 for c in doc["cells"] if not c.get("hold") and c.get("scope_changed"))
        if changed or judged:
            notes.append("범위 바뀜 항목 %d건 · 칸 판정 %d칸(다시 확인)" % (changed, judged))
        if notes:
            self.stale_chip.set_state(" · ".join(notes), "warn")
            self.stale_chip.show()
        else:
            self.stale_chip.hide()
        return doc

    def _empty_for(self, node_set):
        """분석 전 빈 결과. 같은 확정본이면 지난번 것을 그대로 쓴다(1,800구간이면 만드는 데 0.3초, 결과 dict는 고칠 때마다
        새로 만들어지므로 함께 써도 바뀌지 않는다)."""
        key = (node_set["graph_id"], node_set.get("graph_version"),
               tuple((n["node_id"], n.get("rev"), nodes.node_state(n)) for n in node_set["nodes"]),
               tuple(d["deviation_id"] for d in self.deviations))
        if self._empty[0] != key:
            self._empty = (key, res.empty_results(node_set, self.deviations))
        return self._empty[1]

    def set_results(self, doc):
        """결과 dict(hazop_study_results)를 보여 준다. 칸·워크시트·사용량은 이 dict에서만 그린다."""
        self.results = doc
        self._fill_matrix()
        self.usage.setText(conn_view.usage_summary(doc.get("ai_log")))
        self.kpi.setToolTip("%s\n%s" % (self.kpi.text(), self.usage.text()))
        if self.cell:
            self.open_cell(*self.cell)
        else:
            self.sheet_stack.setCurrentIndex(0)

    def _save(self):
        """현재 결과를 저장한다. 실패해도 화면의 결과는 유지하고 상태줄·로그에 남긴다."""
        path = self.store_path()
        try:
            expect = self._fps.get(path, store_io.ANY)
            if self.fixed_view:  # 시험 값은 시험용 파일에만(실제 결과의 AI 초안을 덮지 않음, D5)
                res.write(path, self.results, expect)
            else:
                res.save(self.results, self.node_set.get("project_id"), expect)
            self._fps[path] = res.written_fp(self.results)
        except store_io.Conflict:  # 다시 저장해도 같으므로 '저장 실패'로 두지 않는다. 도면을 다시 고르면 최신 결과를 읽는다
            self.app.status_message("읽은 뒤 분석 결과 파일이 바뀌어 이번 변경은 저장하지 않았습니다. "
                                    "도면을 다시 골라 최신 결과를 불러온 뒤 고치세요.")
            self._unsaved = False
            return False
        except OSError as exc:
            self.app.log_error("분석 결과 저장 실패", exc)
            self.app.status_message("분석 결과를 저장하지 못함: %s" % exc)
            self._unsaved = True
            return False
        self._unsaved = False
        self.app.mark_saved(nodes.now_utc())
        self._show_save_info()
        return True

    def _show_save_info(self):
        """'결과 파일 저장 11-07 20:31 · 폴더' (저장본이 없으면 '아직 저장 안 됨'). 전체 경로는 도구 설명."""
        path = self.store_path()
        if not path:
            self.save_label.setText("")
            return
        if os.path.isfile(path):
            at = kst_text(datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))[5:16]
            text = "결과 파일 저장 %s" % at
        else:
            text = "결과 파일 아직 저장 안 됨"
        self.save_label.setText("%s · <a href='open'>폴더</a>" % text)
        self.save_label.setToolTip("분석 결과 파일(AI 호출이 끝날 때마다·항목을 고칠 때마다 저장):\n%s" % path)

    def _open_save_dir(self, _link=None):
        path = self.store_path()
        if path:
            d = os.path.dirname(path)
            os.makedirs(d, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    # ------------------------------------------------------------ Excel 내보내기
    def export_excel(self, path=None, scope=None, node_ids=None, reviewer=None):
        """범위 대화상자 → 저장 대화상자 → .xlsx 저장 → 토스트 [열기]·[폴더 열기]. path·scope를 주면 대화상자 없이
        (검사용). 저장한 경로 또는 None."""
        if self.node_set is None or self.results is None:
            self.app.status_message(EXPORT_KEPT if getattr(self, "results_kept", False)
                                    else "내보낼 분석 결과가 없습니다. ④에서 검토구간을 확정하세요.")
            return None
        now = nodes.now_utc()
        if scope is None:
            dlg = ExportDialog([self.view[n["node_id"]] for n in self._rows() if n["node_id"] in self.view],
                               self.selected_node_id(),
                               getattr(self, "_export_reviewer", ""), self)
            if dlg.exec() != QDialog.Accepted:
                return None
            scope, node_ids, reviewer = dlg.scope.currentData(), dlg.node_ids(), dlg.reviewer.text().strip()
            self._export_reviewer = reviewer
        if path is None:
            folder = getattr(self, "_export_dir", None) or QStandardPaths.writableLocation(
                QStandardPaths.DocumentsLocation)
            name = study_xlsx.default_filename(self.node_set.get("project_id"), now, test=self.fixed_view)
            path, _ = QFileDialog.getSaveFileName(self, "Excel로 내보내기", os.path.join(folder, name),
                                                  "Excel 통합 문서 (*.xlsx)")
            if not path:
                return None
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
        intents = {}
        for nid, n in self.view.items():
            found = design_intent(n, self.node_review)
            if found:
                intents[nid] = found[0]
        try:
            rows = {n["node_id"] for n in self._rows()}
            path, n_rows = study_xlsx.export(path, self.results, self._scope_set(), self.graph, self.deviations,
                                             scope=scope, node_ids=[x for x in node_ids or () if x in rows] or None
                                             if scope == "nodes" else node_ids, reviewer=reviewer or "",
                                             intents=intents, now=now, expectations=self.expectations,
                                             test=self.fixed_view)
        except (OSError, ValueError) as exc:
            self.app.log_error("Excel 내보내기 실패", exc)
            QMessageBox.warning(self, "Excel로 내보내기", "저장하지 못했습니다(파일이 열려 있으면 닫고 다시 하세요).\n%s"
                                % exc)
            return None
        self._export_dir = os.path.dirname(path)
        self.app.toast("Excel로 내보냄: %s · 워크시트 %d행" % (os.path.basename(path), n_rows), ms=10000, actions=(
            ("열기", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path))),
            ("폴더 열기", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))))))
        return path

    def export_ie_bundle(self, path=None):
        """IE 인계 묶음은 ⑥ 초기사건 화면이 내보낸다(IEC 대응표를 쓰는 곳이 ⑥ 하나). ⑥으로 가서 내보내기를 연다."""
        return self.app.screens[7].export_bundle(path) if self.app.go(7) else None

    # ------------------------------------------------------------ AI 실행
    # 흐름: 요청 → preflight(지금 방식만 확인, 구독 처음이면 이용 조건) → 실행 확인 → calling → 끝·멈춤·취소·창 닫기.
    # 수명은 RunMachine(기술 설계 §6.4 상태표) 하나로만 따진다. 결과 dict는 UI 스레드에서만 바꾼다.
    def running(self):
        return self.machine.busy

    def make_client(self):
        """이번 실행의 클라이언트(self.run_method 방식). 시험·검사 스크립트는 이 함수를 바꿔 끼운다."""
        return self.app.ai_conn.make_client(self.run_method)

    def selected_node_id(self):
        row = self.matrix.currentRow()
        return self._node_at(row) if self.node_set and 0 <= row < len(self._rows()) else None

    def _plan(self, scope, test=None):
        """test: 실행이 쓸 결과 파일이 시험용인지(None이면 보고 있는 쪽). 실패 칸은 그 파일에서 뽑는다."""
        ns = self._scope_set()  # 스크리닝 제외 구간은 AI 일괄 범위에서 뺀다(행이 없는 구간을 몰래 분석하지 않게)
        if scope == "all":
            return ai_cells.plan_units(ns, self.deviations)
        if scope == "node":
            nid = self.selected_node_id()
            return [] if nid is None else ai_cells.plan_units(
                dict(ns, nodes=[n for n in ns["nodes"] if n["node_id"] == nid]), self.deviations)
        if scope == "failed":
            doc = self.results if test is None else self._results_for(test)
            rows = {n["node_id"] for n in ns["nodes"]}
            return ai_cells.plan_units(ns, self.deviations, [c for c in ai_cells.failed_cells(doc) if c[0] in rows])
        if scope == "resume":
            return ai_cells.plan_units(ns, self.deviations, (self.last_run or {}).get("cells") or [], group=True)
        return [] if self.cell is None else ai_cells.plan_units(ns, self.deviations, [self.cell])

    def _results_for(self, test):
        """시험용(test) 또는 실제 결과. 보고 있는 쪽이면 화면의 결과, 아니면 저장본."""
        if test == self.fixed_view:
            return self.results
        return self._test_results() if test else self._saved_results(self.node_set)

    def _test_results(self):
        path = res.test_store_path(self.node_set.get("project_id"), self.node_set["graph_id"])
        try:
            doc, self._fps[path] = res.read_fp(path)
        except (OSError, ValueError):
            doc = None
        if doc is None:
            return res.empty_results(self.node_set, self.deviations)
        if doc.get("schema_version") != res.SCHEMA_VERSION:  # 시험 결과는 옛 판이면 다시 만든다(실제 결과가 아님)
            return res.empty_results(self.node_set, self.deviations)
        doc, problems, _bad = res.partition(res.reconcile(doc, self.node_set, self.deviations), self.node_set)
        return res.empty_results(self.node_set, self.deviations) if problems else doc

    def store_path(self):
        if not self.node_set:
            return None
        if self.fixed_view:
            return res.test_store_path(self.node_set.get("project_id"), self.node_set["graph_id"])
        return res.store_path(self.node_set.get("project_id"), self.node_set["graph_id"])

    def estimate(self, n_calls, method="api"):
        """(초, 달러) 어림값. 지금 모델로 성공한 호출 기록이 있으면 그 평균 비용, 없으면 기본 Opus 어림값을 모델 단가 비율로
        바꾼다. 동시 호출이 2면 시간을 나눈다. 세 번째 값은 근거가 기록인지."""
        model = self.app.api_keys.model
        ok = [r["cost_usd"] for r in (self.results or {}).get("ai_log") or []
              if r.get("status") != "failed" and r.get("model") == model and r.get("cost_usd")
              and conn_view.record_via(r) == "api"]
        if ok:
            usd = sum(ok) / len(ok)
        else:
            base, cur = claude_http.PRICES[claude_http.DEFAULT_MODEL], claude_http.PRICES.get(model)
            usd = EST_USD_PER_CALL * (cur["output"] / base["output"] if cur else 1)
        workers = 1 if method == "fixed" else self.app.ai_conn.prefs.concurrency
        return n_calls * EST_SEC_PER_CALL / workers, n_calls * usd, bool(ok)

    def request_ai(self, scope="all"):
        """버튼·팔레트: 호출이 2회 이상이면 실행 확인(화면 설계 §6)을 거친다. 시작했거나 연결 확인 중이면 True."""
        return self._request(scope, ask=True)

    def run_ai(self, scope="all"):
        """scope: all(모든 구간) · node(선택 행 구간) · failed(실패 칸) · cell(열린 칸) · resume(남은 칸). 묻지 않는다."""
        return self._request(scope, ask=False)

    def _request(self, scope, ask, method=None):
        """method를 주면 이번 실행만 그 방식으로 돌린다('API 키로 이어서', D4). 없으면 지금 방식."""
        if self.machine.busy or self.node_set is None:
            return False
        if self.app.screens[5].review_busy():  # ④ AI 구간 검토와 겹치면 사용량 확인·멈춤·설정 잠금이 어긋난다
            self.app.status_message("④ AI 구간 검토가 끝난 뒤에 실행하세요.")
            return False
        conn = self.app.ai_conn
        override = method is not None and method != conn.method
        method = method or conn.method
        units = self._plan(scope, test=method == "fixed")
        if not units:
            self.app.status_message({"node": "행렬에서 분석할 구간의 행을 고르세요.",
                                     "failed": "다시 실행할 실패 칸이 없습니다.",
                                     "resume": "이어서 실행할 칸이 없습니다."}.get(scope, "분석할 칸이 없습니다."))
            return False
        self.machine.fire("start")
        self._pending = {"scope": scope, "units": units, "method": method, "ask": ask, "override": override}
        self._update_buttons()
        if method == "api":  # API 키는 시작 전 네트워크 확인을 하지 않는다(키 저장소의 마지막 시험만, §2.4)
            self._preflight_done(conn.status("api"))
        else:
            self.app.status_message("AI 연결을 확인하는 중…")
            conn.check(method, done=self._preflight_done)
        return self.machine.state in ("preflight", "calling")

    def _abort(self, text=None):
        self.machine.fire("check_fail")
        self._pending = None
        if text:
            self.app.status_message(text)
        self._update_buttons()

    def _preflight_done(self, status):
        p = self._pending
        if p is None or self.machine.state != "preflight":
            return
        conn, method = self.app.ai_conn, p["method"]
        if method != "api":
            self.app.status_message("")  # 'AI 연결을 확인하는 중…'을 남기지 않는다
        state = (status or {}).get("state") or "unchecked"
        resume_anyway = p["scope"] == "resume" and state == "limit_reached"  # 아직 한도면 첫 호출에서 같은 띠가 다시 뜬다
        if not conn_view.can_start(method, state) and not resume_anyway:
            self._abort()
            self._resolve(method, status, p)
            return
        if method == "subscription" and not conn.terms_acked():
            choice = ask_terms(self, conn.prefs, "run")
            if choice != "ok":
                self._abort()
                if choice == "api":
                    self.app.open_ai_settings("api")
                return
        if state == "overage_risk" and not conn.prefs.allow_overage and not self.ask_overage():
            self._abort()
            return
        units, ctxs = p["units"], self._contexts(p["units"])
        missing = 0
        if method == "fixed":
            units, missing = self._fixed_units(units, ctxs)
            if not units:
                self._abort("고른 폴더에 지금 검토구간에 맞는 응답이 없습니다. 다른 폴더를 고르세요.")
                return
        if p["ask"] and (len(units) > 1 or p["override"]):
            choice = self._confirm(method, units, missing, p["override"])
            if choice == "change":
                self._abort()
                self.app.open_ai_settings(method)
                if not p["override"]:
                    self._request(p["scope"], True)
                return
            if choice != "start":
                self._abort()
                return
        self.machine.fire("check_ok")
        self._start(method, units, ctxs, p["override"])

    def _contexts(self, units):
        by_id = {n["node_id"]: n for n in self.node_set["nodes"]}
        ctxs = {}
        for u in units:
            if u["node_id"] not in ctxs:
                node = by_id[u["node_id"]]
                ctxs[u["node_id"]] = ai_cells.node_context(node, self.graph, self.kg, design_intent(node, self.node_review),
                                                           expectations=self.expectations)
        return ctxs

    def _fixed_units(self, units, ctxs):
        """고정 응답이 있는 호출 단위만(응답이 없는 칸은 '분석 전'으로 둔다, §6). (단위 목록, 빠진 칸 수)."""
        folder = self.app.ai_conn.prefs.fixed_dir
        try:
            have = {n[:-5] for n in os.listdir(folder) if n.endswith(".json")} if folder else set()
        except OSError:
            have = set()
        keep = [u for u in units
                if providers.fixed_key(ai_cells.build_request(u, ctxs[u["node_id"]], self.deviations)) in have]
        missing = sum(len(u["deviation_ids"]) for u in units if u not in keep)
        return keep, missing

    def fixed_match(self):
        """(맞는 칸, 전체 칸): 지금 검토구간에서 고정 응답이 있는 칸 수(화면 설계 §3.5·§9.3)."""
        if self.node_set is None:
            return None
        units = self._plan("all")
        keep, _missing = self._fixed_units(units, self._contexts(units))
        return sum(len(u["deviation_ids"]) for u in keep), sum(len(u["deviation_ids"]) for u in units)

    def _resolve(self, method, status, pending):
        """실행할 수 없는 상태: 확인 대화상자 대신 해결 안내(§6 끝). API 키가 없으면 설정 창의 API 키 상세를 바로 연다."""
        state = (status or {}).get("state")
        if method == "api" and state == "no_key":
            self.app.open_ai_settings("api")
            if self.app.api_keys.get():
                self._request(pending["scope"], pending["ask"])
            else:
                self.app.status_message("API 키가 없어 AI 분석을 시작하지 않았습니다(파일 > AI 연결 설정).")
            return
        if state in ("checking", "unchecked"):
            self.app.status_message("AI 연결을 아직 확인하지 못해 시작하지 않았습니다. 다시 실행해 보세요.")
            return
        choice = self.show_resolve(method, status)
        if choice:
            self.app.conn_action(choice, method)

    def show_resolve(self, method, status):
        """해결 안내 창. 고른 동작 이름(없으면 None)."""
        dlg = ResolveDialog(method, status, self.app.ai_conn.fixed_count(), self)
        dlg.exec()
        return dlg.choice

    def ask_overage(self):
        box = QMessageBox(QMessageBox.Warning, "초과 사용 주의", OVERAGE_TEXT, parent=self)
        go = box.addButton("시작", QMessageBox.AcceptRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is go

    def _confirm(self, method, units, missing, override):
        """실행 확인(§6). 'start' · 'change'(바꾸기…) · None(취소)."""
        conn = self.app.ai_conn
        calls, cells = len(units), sum(len(u["deviation_ids"]) for u in units)
        sec, usd, from_log = self.estimate(calls, method)
        if method == "api":
            e, key = self.app.api_keys.active(), self.app.api_keys.get() or ""
            link = "API 키 · '%s'(…%s) · %s" % ((e or {}).get("name") or "-", key[-4:],
                                               conn_view.model_name(self.app.api_keys.model))
        elif method == "subscription":
            link = "Claude 구독 · %s" % conn_view.model_name(conn.model(method))
        else:
            folder = conn.prefs.fixed_dir or ""
            link = "고정 응답(시험) · 응답 폴더 …\\%s" % os.path.basename(folder.rstrip("\\/"))
        lead, rows = conn_view.confirm_rows(
            method, calls, cells, link, sec, usd, conn_view.cost_basis(usd / max(calls, 1), from_log),
            conn.status(method).get("limit"), missing,
            res.test_store_path(self.node_set.get("project_id"), self.node_set["graph_id"]) if method == "fixed"
            else res.store_path(self.node_set.get("project_id"), self.node_set["graph_id"]),
            resume=self._pending is not None and self._pending["scope"] == "resume")
        dlg = RunConfirmDialog(method, lead, rows, RESUME_API_NOTE if override else "", self)
        return dlg.ask()

    def _new_run_info(self, method, override, units, scope):
        """실행 하나의 집계. failed는 이번 실행에서 실패한 호출만 담는다(결과 파일에 남은 옛 실패와 섞지 않음)."""
        return {"start": time.monotonic(), "base": ai_cells.usage_total(self.results), "unit": None,
                "method": method, "override": override, "calls": len(units), "ok_calls": 0, "ok_cells": 0,
                "limit": None, "failed": [], "scope": scope}

    def _start(self, method, units, ctxs, override):
        conn = self.app.ai_conn
        scope = (self._pending or {}).get("scope")
        self._pending = None
        self._switch_view(method == "fixed")
        self.run_method = method
        client = self.make_client()
        workers = 1 if method == "fixed" else conn.prefs.concurrency
        self.runner = AiRunner([(u, ctxs[u["node_id"]]) for u in units], self.deviations, client, workers)
        self.runner.unit_started.connect(self._on_unit_started)
        self.runner.unit_done.connect(self._on_unit_done)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(lambda reason, r=self.runner: self._finish_run(r, reason))
        self.run_info = self._new_run_info(method, override, units, scope)
        self.run_band.hide()
        self._reset_timer.stop()
        if override:
            self.app.set_run_override(method)
        conn.cancel_handler = self.cancel_ai
        conn.set_running(True, ("실패 칸 다시 실행 중 · 다시 돌릴 칸 %d" if scope == "failed" else "AI 분석 실행 중 · 0/%d 호출")
                         % len(units))
        self.progress.setRange(0, len(units))
        self.progress.setValue(0)
        self._progress_text()
        self._update_buttons()
        self.tick.start()
        self.runner.start()

    def cancel_ai(self):
        """처음 누르면 남은 호출을 멈추고 진행 중인 1건은 받는다. 기다리는 중에 한 번 더 누르면 바로 끊는다(§6.3)."""
        if self.runner is None:
            return
        if self.machine.state == "calling":
            self.machine.fire("cancel")
            self.runner.cancel()
            self.app.status_message("취소 요청: 진행 중인 호출을 마친 뒤 멈춥니다. 한 번 더 누르면 바로 끊습니다.")
        elif self.machine.state == "draining":
            self.machine.fire("cancel")
            if self.runner.kill():
                self.app.status_message("진행 중인 호출을 끊는 중…")
            else:
                self.app.status_message("이 연결은 진행 중인 호출을 끊을 수 없어 끝날 때까지 기다립니다.")
        self._update_buttons()

    # ---- 창 닫기(기술 설계 §6.3·§11 10번, U9)
    def shutdown(self, ask=None):
        """창을 닫을 때. 바로 닫아도 되면 받은 칸을 저장하고 True. 진행 중인 호출이 있으면 물은 뒤 False를 돌려주고,
        기다림·끊기가 끝나면 창을 다시 닫는다(그때는 True)."""
        st = self.machine.state
        if not self.machine.alive:
            if st != "closed":
                self.machine.fire("close_now")
            self._save_if_unsaved()
            return True
        if st in ("close_wait", "killing_close"):
            self._close_tick()  # Esc로 숨긴 남은 시간 창을 다시 보인다
            return False
        n = self.runner.calls_in_flight() if self.runner else 0
        choice = (ask or self.ask_close)(max(n, 1))
        if choice is not None and not self.machine.alive:  # 묻는 사이에 호출이 끝났으면 바로 닫는다
            return self.shutdown()
        if choice in ("now", "wait"):
            self._close_deadline = time.monotonic() + self.CLOSE_WAIT_SEC
        if choice == "now":
            self._close_now()
        elif choice == "wait":
            self.machine.fire("close_wait")
            self.runner.cancel()
            self._close_timer.start()
            self._close_tick()
        return False

    def close_refused(self):
        """창이 닫기를 거절했다(저장 안 한 변경에서 '취소'). 창은 열려 있으니 다시 실행을 받는다."""
        if self.machine.fire("close_refused"):
            self._update_buttons()

    def ask_close(self, n_calls):
        box = QMessageBox(QMessageBox.Question, conn_view.CLOSE_TITLE, conn_view.CLOSE_TEXT % n_calls, parent=self)
        wait = box.addButton(conn_view.CLOSE_WAIT, QMessageBox.AcceptRole)
        now = box.addButton(conn_view.CLOSE_NOW, QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(wait)
        box.exec()
        return {id(wait): "wait", id(now): "now"}.get(id(box.clickedButton()))

    def _close_tick(self):
        """기다렸다 닫기의 남은 시간. close_wait뿐 아니라 이미 끊는 중(killing)에 닫기를 기다린 killing_close도
        상한을 둔다. 끊을 수 없는 클라이언트(API)는 취소를 두 번 눌러도 호출이 끝날 때까지 살아 있다."""
        st = self.machine.state
        if st not in ("close_wait", "killing_close"):
            self._close_timer.stop()
            self._close_wait_box.hide()
            return
        left = self._close_deadline - time.monotonic()
        if left <= 0:
            self._end_close_wait("wait_expired")
            return
        self._close_wait_box.set_left(clock(left))

    def _close_now(self):
        self._end_close_wait("close_now")

    def _end_close_wait(self, event):
        self._close_timer.stop()
        self._close_wait_box.hide()
        if self.machine.state == "killing_close":  # 이미 끊기를 보냈는데 아직 살아 있다
            self._abandon_run()
            return
        self.machine.fire(event)
        self._kill_for_close()

    def _kill_for_close(self):
        """killing_close: 앱이 띄운 트리만 끊는다(client.cancel). 끊을 수 없는 클라이언트는 기다리지 않고 닫는다.
        끊기를 보냈는데도 끝나지 않으면 처음 닫기를 누른 때부터 2분이 지나면 버리고 닫는다(_close_tick)."""
        if self.runner is None:
            return
        if self.runner.kill():
            self._close_timer.start()
        else:
            self._abandon_run()

    def _abandon_run(self):
        """받은 칸은 이미 저장했다. 아직 오지 않은 결과는 버리고 닫는다(작업 스레드는 데몬이라 앱 종료를 막지 않는다)."""
        runner = self.runner
        if runner is None:
            return
        for sig in (runner.unit_started, runner.unit_done, runner.progress, runner.finished):
            sig.disconnect()
        self._orphans.append(runner)  # 데몬 작업자가 끝날 때까지 신호를 받을 객체를 살려 둔다
        self._finish_run(runner, "killed")

    def _save_if_unsaved(self):
        if self._unsaved and self.results is not None:
            self._save()

    # ---- 진행
    def _on_unit_started(self, unit):
        if self.run_info is not None:
            self.run_info["unit"] = unit
        self.in_progress |= {(unit["node_id"], did) for did in unit["deviation_ids"]}
        self._fill_matrix()
        self._progress_text()

    def _on_unit_done(self, ur):
        self.in_progress -= {(ur["node_id"], did) for did in ur["cells"]}
        info = self.run_info
        if info is not None:
            if ur["status"] == "ok":
                info["ok_calls"] += 1
                info["ok_cells"] += len(ur["cells"])
            else:
                info["failed"].append(ur)
            if ur.get("limit"):
                info["limit"] = ur["limit"]
            self._conn_from_result(info["method"], ur)
        try:
            doc = ai_cells.apply_unit(self.results, ur)
        except ValueError as exc:
            self.app.log_error("AI 결과 반영 실패", exc)
            return
        self.results = doc
        self._save()
        self.set_results(doc)
        if self.machine.state == "calling":
            self.machine.fire("call_more")

    def _conn_from_result(self, method, ur):
        """호출 결과의 연결 상태·한도를 칩과 설정 창에 반영한다(실행 중에도 칩 글자만 바뀌고 진행은 보이지 않는다).
        성공한 호출은 앞서 받은 연결 오류(예: 한 번의 network)를 지운다. 연결과 무관한 실패(응답 형식 등)는 그대로 둔다."""
        if method == "fixed":
            return
        state = ur.get("conn_state")
        if not state and not ur.get("limit") and ur["status"] != "ok":
            return
        prev = self.app.ai_conn.status(method)
        limit = ur.get("limit") or prev.get("limit")
        state = state or (claude_cli.limit_state(limit) if method == "subscription" else None) or "ok"
        if (state, limit) == (prev.get("state"), prev.get("limit")):
            return
        self.app.set_conn_status({"via": method, "state": state, "detail": ur.get("error") or "",
                                  "plan": prev.get("plan"), "limit": limit})

    def _on_progress(self, done, total):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        if self.runner is not None:
            self.app.ai_conn.set_running(True, "AI 분석 실행 중 · %d/%d 호출" % (done, total))
        self._progress_text()

    def unit_text(self, unit):
        """'S1 · 유량' (구간 · 변수)."""
        by_id = {d["deviation_id"]: d for d in self.deviations}
        params = []
        for did in unit["deviation_ids"]:
            p = (by_id.get(did) or {}).get("parameter") or did
            if p not in params:
                params.append(p)
        return "%s · %s" % (unit["node_id"], "·".join(params))

    def _spent(self, info):
        return usage_diff(ai_cells.usage_total(self.results), info["base"]) if self.results else None

    def _progress_text(self):
        """막대 옆 짧은 줄 + 상태 표시줄 긴 줄(§7.1). 마지막 칸만 방식에 따라 바뀐다(API 키 $, 구독 '구독 사용량 차감')."""
        failed = len(ai_cells.failed_cells(self.results)) if self.results else 0
        done, total = self.progress.value(), self.progress.maximum()
        info = self.run_info
        method = info["method"] if info else None
        if method == "fixed":
            now = self.unit_text(info["unit"]) if info["unit"] else "시작 중"
            self.progress_label.setText("시험 %d/%d · %s · 고정 응답" % (done, total, now))
            self.progress_label.setToolTip("이번 실행: %s\n칸은 호출마다 시험용 파일에 저장됩니다: %s"
                                           % (conn_view.run_usage_line(method, None), self.store_path()))
            self.app.status_message("● 시험 실행 중 · 시험 %d/%d · %s · 고정 응답" % (done, total, now))
            return
        if info is None:  # 실행 밖: 지난 실행 호출 수와 결과 파일 전체의 실패 칸 수는 다른 수라 따로 이름 붙인다
            self.progress_label.setText(("시험 %d/%d" if self.fixed_view else "AI %d/%d 호출%s") % (
                (done, total) if self.fixed_view else (done, total, failure_note(None, failed))))
            return
        if self.fixed_view:
            text = "시험 %d/%d" % (done, total)
        elif info.get("scope") == "failed":  # 다시 돌릴 대상 수와 이번 실행의 실패를 가른다
            text = "다시 돌릴 칸 %d · %d/%d 호출" % (total, done, total)
        else:
            text = "AI %d/%d 호출" % (done, total)
        if not self.fixed_view:
            text += failure_note(info, None)
        elapsed = time.monotonic() - info["start"]
        left = "남은 시간 계산 중" if not done else "약 %s 남음" % clock(elapsed / done * (total - done))
        spent = self._spent(info)
        tail = conn_view.progress_tail(method, spent, info["limit"])
        now = "%s 분석 중" % self.unit_text(info["unit"]) if info["unit"] else "시작 중"
        usage = conn_view.run_usage_line(method, spent)
        self.progress_label.setText("%s · %s · %s 경과 · %s · %s" % (text, now, clock(elapsed), left, tail))
        self.progress_label.setToolTip("이번 실행: %s\n칸은 호출마다 저장됩니다: %s" % (usage, self.store_path()))
        self.app.status_message("● AI 분석 실행 중 · %s · %s · %s 경과 · %s · %s"
                                % (text, now, clock(elapsed), left, usage))

    def _finish_run(self, runner, reason):
        if runner is None or runner is not self.runner:
            return
        if runner not in self._orphans:
            runner.wait(5000)  # finished는 마지막 작업자가 끝나며 보내므로 곧 돌아온다
        st = self.machine.state
        if st == "calling":
            self.machine.fire("limit" if reason == "halted" else "call_last")
        elif st in ("draining", "close_wait"):
            self.machine.fire("call_last")
        elif st in ("killing", "killing_close"):
            self.machine.fire("killed")
        self.tick.stop()
        done, total = self.progress.value(), self.progress.maximum()
        info, self.run_info, self.runner, self.in_progress = self.run_info, None, None, set()
        conn = self.app.ai_conn
        conn.cancel_handler = None
        conn.set_running(False)
        if info and info["override"]:
            self.app.set_run_override(None)  # 'API 키로 이어서'는 이번 실행만(D4)
        self._save_if_unsaved()
        failed = len(ai_cells.failed_cells(self.results))
        spent = self._spent(info) if info else None
        method = info["method"] if info else None
        kind = conn_view.band_kind(method, runner.halted_by) if reason == "halted" else None
        self._remember_run(info, runner, reason)
        self._fill_matrix()
        self._progress_text()
        verb = {"halted": "멈춤", "cancelled": "취소됨", "killed": "끊음"}.get(reason, "끝남")
        if kind == "limit_reached":
            verb = "멈춤(한도 도달)"
        word = "시험" if method == "fixed" else "AI 분석"
        self.app.status_message("%s %s: %d/%d 호출%s · %s 걸림%s · %s" % (
            word, verb, done, total, failure_note(info, failed),
            clock(time.monotonic() - info["start"]) if info else "-",
            " · " + conn_view.run_usage_line(method, spent) if spent and method != "fixed" else "",
            "저장 실패 — 화면에만 있음(다시 저장을 시도하려면 항목을 고치거나 화면을 다시 여세요)" if self._unsaved
            else "저장: %s" % self.store_path()))
        if kind and self.machine.state != "closed":
            self._show_run_band(kind)
        self._update_buttons()
        if self.machine.state == "closed":
            self._close_wait_box.hide()
            QTimer.singleShot(0, self.app.close)

    # ---- 멈춘 뒤: 안내 띠와 이어서 실행(§7.3·§7.4, 기술 설계 §11 3번)
    def _remember_run(self, info, runner, reason):
        """이번 실행에서 다시 돌릴 칸: (가) limit_reached·overage·cancelled·not_ready·auth_mismatch로 끝난 칸과 멈춤을
        부른 호출의 칸, (나) 아직 부르지 않은 호출 단위의 칸. 메모리에만 둔다."""
        if info is None:
            return
        cells = []
        halted_id = (runner.halted_by or {}).get("unit_id")
        for ur in info["failed"]:
            if ur.get("error_kind") in RESUME_KINDS or ur["unit_id"] == halted_id:
                cells += [(ur["node_id"], did) for did in ur["cells"]]
        for u in runner.remaining:
            cells += [(u["node_id"], did) for did in u["deviation_ids"]]
        seen = set()
        cells = [c for c in cells if not (c in seen or seen.add(c))]
        self.last_run = {"method": info["method"], "cells": cells, "reason": reason, "halted": runner.halted_by,
                         "calls": info["calls"], "ok_calls": info["ok_calls"], "ok_cells": info["ok_cells"],
                         "limit": info["limit"]} if cells else None

    def _show_run_band(self, kind, actions=None):
        lr = self.last_run or {}
        units = self._plan("resume") if lr else []
        band = conn_view.BANDS[kind]
        if actions is not None:
            band = replace(band, actions=actions)
        if "resume_api" in band.actions and "api" not in self.app.ai_conn.methods():
            band = replace(band, actions=tuple(a for a in band.actions if a != "resume_api"))
        if not units:
            band = replace(band, actions=tuple(a for a in band.actions if a not in ("resume", "resume_api")))
        halted = lr.get("halted") or {}
        guide = conn_view.guide_text(lr.get("method") or "api",
                                     {"state": halted.get("conn_state") or "error", "detail": halted.get("error") or ""})
        body = conn_view.band_text(kind, lr.get("calls", 0), lr.get("ok_calls", 0), lr.get("ok_cells", 0), len(units),
                                   sum(len(u["deviation_ids"]) for u in units), lr.get("limit"),
                                   guide if kind == "not_ready" else "")
        self.run_band.set_band(kind, band, body, {})
        limit = lr.get("limit") or {}
        if kind == "limit_reached" and limit.get("resets_at"):
            ms = int((limit["resets_at"] - time.time()) * 1000) + 5000
            self._reset_timer.start(max(1000, min(ms, 2 ** 31 - 1)))

    def _band_action(self, name):
        conn, lr = self.app.ai_conn, self.last_run or {}
        method = lr.get("method") or conn.method
        if name == "close":
            self.run_band.hide()
        elif name == "resume":
            self.run_band.hide()
            self._request("resume", True)
        elif name == "resume_api":
            if not self.app.api_keys.get():
                self.app.open_ai_settings("api")
                return
            self._request("resume", True, "api")
        elif name == "login_help":
            self.app.conn_action("login_help", method)
        elif name == "recheck":
            kind = self.run_band.kind

            def checked(status):
                if conn_view.can_start(method, status.get("state")) and self.last_run:
                    self._show_run_band(kind, actions=tuple("resume" if a == "recheck" else a
                                                            for a in conn_view.BANDS[kind].actions))
            conn.check(method, done=checked)
        elif name == "copy_error":
            halted = lr.get("halted") or {}
            QGuiApplication.clipboard().setText("사유: %s · %s\n시각: %s" % (
                halted.get("error_kind") or "-", halted.get("error") or "-", claude_cli.now_kst()))
            self.app.toast("오류 내용을 복사했습니다")
        elif name == "settings":
            self.app.open_ai_settings(method)
        elif name == "to_real":
            self.set_fixed_view(False)

    def _limit_reset_check(self):
        """재설정 시각이 지나면 다시 확인하고 토스트로만 알린다(자동 실행 없음, D2)."""
        conn = self.app.ai_conn
        if not self.last_run or "subscription" not in conn.methods():
            return

        def checked(status):
            units = self._plan("resume") if self.last_run else []
            if units and conn_view.can_start("subscription", status.get("state")) and status.get("state") != "limit_reached":
                cells = sum(len(u["deviation_ids"]) for u in units)
                self.app.toast(conn_view.reset_toast(cells), ms=15000,
                               actions=(("이어서 실행", lambda: self._band_action("resume")),))
        conn.check("subscription", done=checked)

    def focus_band(self):
        """F6: 떠 있는 안내 띠의 첫 단추로(띠가 떠도 포커스를 빼앗지 않으므로 사용자가 직접 간다)."""
        for band in (self.run_band, self.test_band):
            b = band.first_button() if band.isVisible() else None
            if b is not None:
                b.setFocus(Qt.ShortcutFocusReason)
                return True
        return False

    # ---- 시험 결과(고정 응답) 파일(D5, §8.1)
    def set_fixed_view(self, on):
        """시험용 결과 파일을 보거나(on) 실제 결과로 돌아온다. 실행 중에는 바꾸지 않는다(실행이 받는 칸은 시작할 때
        정한 파일에만 들어간다). 바꿨으면 True."""
        if self.running():
            return False
        self._switch_view(on)
        return True

    def _switch_view(self, on):
        if self.node_set is None or bool(on) == self.fixed_view:
            return
        self._save_if_unsaved()
        self.fixed_view = bool(on)
        if on:
            doc = self._test_results()
            self.test_band.set_band("fixed_view", conn_view.BANDS["fixed_view"], conn_view.FIXED_VIEW_TEXT, {})
        else:
            self.test_band.hide()
            doc = self._saved_results(self.node_set)
        self.set_results(doc)
        self._show_save_info()
        self._update_buttons()

    def _update_buttons(self):
        idle = not self.running() and self.node_set is not None
        for b in (self.run_all_btn, self.run_node_btn, self.retry_btn, self.rerun_cell_btn):
            b.setEnabled(idle)
        conn = getattr(self.app, "ai_conn", None)  # 화면만 띄우는 시험 틀에는 연결이 없다
        if conn is not None:
            self.run_all_btn.setToolTip(conn_view.run_tooltip(conn.method, conn.model(conn.method)))
        self.export_btn.setEnabled(self.node_set is not None and self.results is not None)
        st = self.machine.state
        self.cancel_btn.setEnabled(st in ("calling", "draining"))
        self.cancel_btn.setVisible(self.machine.alive)
        self.cancel_btn.setText(CANCEL_NOW if st in ("draining", "killing") else "취소")
        self.cancel_btn.setToolTip(CANCEL_NOW_TIP if st == "draining" else CANCEL_TIP)
        has_failed = bool(self.results) and bool(self._plan("failed"))
        self.retry_btn.setVisible(has_failed)
        self.combo.setEnabled(not self.running())
        for b in self.test_band.btns.values():
            b.setEnabled(not self.running())
        self._update_entry_buttons()

    # ------------------------------------------------------------ 행렬
    def _rows(self):
        """행렬 행이 되는 구간: 확정·잠금 구간만(적용됨 구간은 ⑤ 행이 없음, §2.2). 스크리닝 제외 구간은 행이 없고(④에서 확인),
        낮음 구간은 맨 아래에 모은다(D6)."""
        if not self.node_set:
            return []
        shown = [n for n in self.node_set["nodes"] if _status(n) != "excluded" and nodes.is_active(n)]
        return [n for n in shown if _status(n) != "low"] + [n for n in shown if _status(n) == "low"]

    def _scope_set(self):
        """AI 일괄·Excel의 기본 범위 = 행렬 행과 같은 구간."""
        return dict(self.node_set, nodes=self._rows())

    def _color_of(self, node_id):
        """구간 색 번호는 ④와 같게 집합 순서로 정한다(행 순서가 달라도 같은 구간은 같은 색)."""
        return next((i for i, n in enumerate(self.node_set["nodes"]) if n["node_id"] == node_id), 0)

    def _node_at(self, row):
        return self._rows()[row]["node_id"]

    def _row_of(self, node_id):
        return next((i for i, n in enumerate(self._rows()) if n["node_id"] == node_id), None)

    def _fill_matrix(self):
        """칸 한 줄(U-20). 칸 글자·상태·툴팁은 MatrixModel이 보이는 칸만 계산하고, 그리기는 CellDelegate가 CELL_ROLE 상태로 한다.
        AI 실행 실패 칸은 위험도 색을 쓰지 않는다(U-19): 흰 바탕 + 빨강 점선 테두리 + '! 실패'."""
        cached, counted = self.summary_of
        ns, summary = self._scope_set(), counted if cached is self.results else res.matrix_summary(self.results)
        self.summary_of = (self.results, summary)  # 탐색기·다음 진입이 같은 결과로 다시 세지 않게(결과는 바뀔 때마다 새 dict다)
        hidden = [n for n in self.node_set["nodes"] if _status(n) == "excluded"]
        runs = {(c["node_id"], c["deviation_id"]): c.get("ai_run") or {} for c in self.results["cells"]}
        shown = {n["node_id"] for n in ns["nodes"]}
        failed = {k for k, r in runs.items() if r.get("status") == "failed" and k[0] in shown}
        limited = {k for k in failed if is_limit_stop(runs[k])}
        marks = {k: "failed" for k in failed}
        marks.update((k, "limit") for k in limited)
        marks.update((k, "running") for k in self.in_progress)
        color = {n["node_id"]: i for i, n in enumerate(self.node_set["nodes"])}
        rows = []
        for n in ns["nodes"]:
            v = self.view.get(n["node_id"]) or n
            label = project_ctx.node_label(v)
            rows.append({"node": n, "color": color.get(n["node_id"], 0), "label": label,
                         "tip": "%s\n%s\n구성요소 %s%s" % (label, project_ctx.boundary_text(v),
                                                         project_ctx.counts_text(v, self.ctx.drawing_number)
                                                         if self.ctx else len(n["members"]),
                                                         "\n스크리닝 낮음: 편차원을 알아보지 못한 배관 묶음(맨 아래, 주배관일 수 있음)"
                                                         if _status(n) == "low" else "")})
        m = self.matrix
        cur = (m.currentRow(), m.currentColumn())
        m.horizontalHeader().set_groups([(d["parameter"], d["guideword"]) for d in self.deviations])
        self.matrix_model.set_data(rows, self.deviations, summary, runs, marks)
        dev_ids = {d["deviation_id"] for d in self.deviations}
        cells = [s for nid in shown for did, s in summary.get(nid, {}).items() if did in dev_ids]
        total_s, total_u = sum(s["scenarios"] for s in cells), sum(s["unreviewed"] for s in cells)
        if cur[0] >= 0 and cur[1] >= 0 and cur[0] < len(rows) and cur[1] < len(self.deviations):
            m.setCurrentCell(*cur)
        self.kpi.setText("구간 %d · 편차 %d · 시나리오 %d · 미검토 %d%s"
                         % (len(ns["nodes"]), len(self.deviations), total_s, total_u,
                            " · 실패 %d" % (len(failed) - len(limited)) if len(failed) > len(limited) else "")
                         + (" · 한도로 멈춤 %d" % len(limited) if limited else "")
                         + (" · 스크리닝 제외 %d개(④에서 확인)" % len(hidden) if hidden else ""))
        self._update_buttons()

    # ------------------------------------------------------------ 워크시트
    def _entity_label(self, eid):
        n = self.ctx.by_id.get(eid) if self.ctx and self.ctx.pg else None
        return (n.get("tag") or n.get("kind") or eid) if n else eid

    def _shown(self, text):
        """다른 도면 태그에 도면번호를 붙인 표시 글("RC-P01(101)"). 저장값은 그대로."""
        return self.ctx.tag_label(text) if text and self.ctx and self.ctx.pg else text

    def _span_text(self, node_id):
        """워크시트 머리말: "도면 SNP-M-101 → SNP-M-102 · 시작: X(SNP-M-102) / 끝: Y(SNP-M-101)"."""
        v = self.view.get(node_id)
        if not v:
            return ""
        h = span.worksheet_header(v)
        return "도면 %s · 시작: %s / 끝: %s" % (" → ".join(h["drawings"]) or "-", h["start"] or "-", h["end"] or "-")

    def _cell_doc(self):
        if not self.cell or not self.results:
            return None
        return next((c for c in self.results["cells"] if (c["node_id"], c["deviation_id"]) == self.cell), None)

    def _basis_text(self, e):
        basis = e.get("ai_basis") or {}
        lines = [" → ".join(self._entity_label(x) for x in p) for p in basis.get("kg_paths") or []]
        lines += ["%s %s" % (s.get("doc") or "", s.get("where") or "") for s in basis.get("sources") or []]
        lines += ["⚠ %s" % w for w in list(basis.get("warnings") or [])
                  + [res.quality_line(k, t) for k, t in res.quality_warnings(e)]]
        clues = [t for k, t in self._ref_lines(e) if k == "expectation"]
        if clues:  # 사람이 고른 잠재 후보는 AI 근거가 아니라 확인할 단서라 따로 묶는다
            lines += ([""] if lines else []) + ["확인할 단서(근거 아님)"] + clues
        return "\n".join(lines) or "-"

    def _expect_items(self):
        return {i["id"]: i for i in (self.expectations or {}).get("items") or []}

    def _ref_label(self, ref):
        dn = {s["graph_id"]: s["drawing_number"] for s in self.graph["sheets"]} if self.graph else {}
        return refs.label(ref, self.ref_idx, dn, self.ctx.short if self.ctx and self.ctx.pg else None)

    def _ref_lines(self, e):
        dn = {s["graph_id"]: s["drawing_number"] for s in self.graph["sheets"]} if self.graph else {}
        return refs.lines(e, self.ref_idx, dn, self.ctx.short if self.ctx and self.ctx.pg else None,
                          self._expect_items() if self.expectations is not None else None)

    def _safeguard_cell(self, e):
        """보호수단 칸: 역할·작동 방식·구현 대상이 있는 항목은 줄마다 "문장 — 완화 · 자체작동 · RC-PSV101(102)"
        (승인 전 AI 참조는 "AI 초안")."""
        items = refs.safeguard_items(e)
        if not any(s["role"] != "unknown" or s["actuation"] != "unknown" or s["refs"] for s in items):
            return self._shown(", ".join(s["text"] for s in items))
        out = []
        for s in items:
            bits = [refs.ROLES[s["role"]]] if s["role"] != "unknown" else []
            bits += [refs.ACTUATIONS[s["actuation"]]] if s["actuation"] != "unknown" else []
            bits += [self._ref_label(r["ref"]) for r in s["refs"] if r.get("ref")]
            draft = not refs.is_confirmed(s, e) or any(not refs.is_confirmed(r, e) for r in s["refs"])
            out.append("%s — %s%s" % (self._shown(s["text"]), " · ".join(bits) or "미정", " · AI 초안" if draft else ""))
        return "\n".join(out)

    def _with_refs(self, text, e, kind):
        extra = [t for k, t in self._ref_lines(e) if k == kind]
        return "\n".join([self._shown(text) or "-"] + extra) if extra else self._shown(text)

    def ref_context(self, node_id):
        """수정 창 ref_ctx: 구간 구성요소(먼저)와 태그가 있는 프로젝트 그래프 대상, 구간에 걸린 잠재 후보.
        도면 연결 구간처럼 "도면#원본 객체" 꼴 참조가 없는 대상은 결과 파일에 저장할 수 없어 고르기 목록에서 뺀다."""
        node = next((n for n in self.node_set["nodes"] if n["node_id"] == node_id), {"members": []})
        members = set(node["members"])
        first, rest = [], []
        for ref, n in sorted(self.ref_idx.items(), key=lambda kv: refs.node_text(kv[1]) or ""):
            if not refs.drawing_of(ref):
                continue
            if n["entity_id"] in members:
                first.append((ref, "%s · 이 검토구간" % self._ref_label(ref)))
            elif n.get("tag") and n.get("node_type") == "drawing_object":
                rest.append((ref, self._ref_label(ref)))
        mine = {r for r, n in self.ref_idx.items() if n["entity_id"] in members}
        xs = [(i["id"], "%s %s %s · %s" % (i["rule_id"], i.get("target_tag") or i["target"], i["label"], i["state_label"]))
              for i in (self.expectations or {}).get("items") or [] if i["target"] in mine]
        return {"choices": first + rest, "label": self._ref_label, "expectations": xs}

    def open_cell(self, node_id, deviation_id):
        node = next((n for n in self.node_set["nodes"] if n["node_id"] == node_id), None)
        dev = next((d for d in self.deviations if d["deviation_id"] == deviation_id), None)
        if node is None or dev is None:
            return False
        if self._row_of(node_id) is None:  # 스크리닝 제외 구간은 행이 없다
            self.app.status_message("%s는 스크리닝 제외 구간입니다. ④에서 꺼내면 ⑤에서 볼 수 있습니다." % node_id)
            return False
        keep = (self.selected_entry() or {}).get("entry_id") if self.cell == (node_id, deviation_id) else None
        self.cell = (node_id, deviation_id)
        cell = self._cell_doc()
        row = self._row_of(node_id)
        self.sheet_badge.setPixmap(seg_icon(self._color_of(node_id), node_id).pixmap(30, 16))
        self.sheet_title.setText("%s × %s" % (project_ctx.node_label(self.view.get(node_id) or node), dev["label"]))
        self.sheet_span.setText(self._span_text(node_id))
        self.sheet_span.setToolTip(self.sheet_span.text())
        self.app.set_selection({"kind": "cell", "drawing": self.name, "node_id": node_id, "deviation_id": deviation_id})
        run = (cell or {}).get("ai_run") or {}
        self.sheet_source.setText(conn_view.provenance(run) if run.get("status") == "ok" else "")
        self.sheet_source.setVisible(bool(self.sheet_source.text()))
        if is_limit_stop(run):
            self.run_note.setText("구독 한도로 멈춤: %s" % (run.get("error") or "-"))
        elif run.get("status") == "failed":
            self.run_note.setText("AI 실행 실패: %s" % (run.get("error") or "-"))
        else:
            self.run_note.setText("AI 메모: %s" % run["note"] if run.get("note") else "")
        self.run_note.setVisible(bool(self.run_note.text()))
        intent = design_intent(node, self.node_review)
        self.intent.setText("설계 의도: %s" % intent[0] if intent else "설계의도 미입력")
        self.intent_src.setText("출처: %s" % intent[1] if intent else "")
        self.intent_src.setVisible(bool(intent))
        entries = (cell or {}).get("entries") or []
        drafts = sum(1 for e in entries if res.is_ai_draft(e))
        self.draft_chip.set_state("AI 초안 %d건" % drafts if drafts else "", "warn" if drafts else "")
        self.draft_chip.setVisible(bool(drafts))
        live = [e for e in entries if e.get("status") != "rejected"]
        self.sheet_count.setText("시나리오 %d · 기각 %d" % (len(live), len(entries) - len(live)) if entries else "")
        t = self.table
        t.clearSelection()
        t.setRowCount(max(len(entries), 1))
        t.clearSpans()
        if not entries:
            t.setSpan(0, 0, 1, len(SHEET_COLUMNS))
            for c in range(len(SHEET_COLUMNS)):
                t.setItem(0, c, QTableWidgetItem(""))
            state = "한도로 멈춤" if is_limit_stop(run) else "AI 실행 실패" if run.get("status") == "failed" else (
                "AI 초안 · %s" % empty_cell_label(run) if (cell or {}).get("state") == "analyzed" else "분석 전")
            t.item(0, 0).setText("%s · 항목 없음" % state)
            t.item(0, 0).setForeground(QColor(tokens.c("muted")))
            t.item(0, 0).setFlags(Qt.ItemIsEnabled)
        for r, e in enumerate(entries):
            draft = res.is_ai_draft(e)
            status = STATUS_LABELS.get(e.get("status"), e.get("status") or "-")
            basis = self._basis_text(e)
            flags = [f for f in ENTRY_FLAGS if e.get(f[0])]
            values = (self._with_refs(e.get("cause"), e, "cause"), self._with_refs(e.get("consequence"), e, "consequence"),
                      self._safeguard_cell(e), self._shown(e.get("recommendation")),
                      risk_text(e.get("risk")), basis,
                      "".join(f[1] + " · " for f in flags) + ("AI 초안 · " if draft else "") + status)
            for c, v in enumerate(values):
                it = QTableWidgetItem(v or "-")
                # 편집 가능 항목이면 Qt가 IME를 켜서 한글 상태의 A·R·E가 조합 글자로 먹힌다. 편집은 대화상자로만 한다
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setData(Qt.UserRole, e["entry_id"])
                it.setData(DRAFT_ROLE, draft)
                t.setItem(r, c, it)
            risk_it = t.item(r, COL_RISK)
            risk_it.setToolTip("강도 %s · 발생빈도 %s" % (e.get("severity") or "-", e.get("frequency") or "-"))
            if tokens.risk_band(e.get("risk")):
                bg, ink, _line = tokens.risk_colors(e["risk"])
                risk_it.setBackground(QColor(bg))
                risk_it.setForeground(QColor(ink))
            for c in range(3):  # 참조 줄이 붙은 원인·결과·보호수단 칸은 줄이 잘려도 전체 글을 볼 수 있게
                if "\n" in (values[c] or ""):
                    t.item(r, c).setToolTip(values[c])
            basis_it = t.item(r, COL_BASIS)
            basis_it.setToolTip(basis)
            if flags:
                st = t.item(r, COL_STATUS)
                st.setToolTip("\n".join(f[2] for f in flags) + "\n(상태는 옛 결과 그대로. 내용을 다시 확인하세요)")
                st.setForeground(QColor(tokens.c("warn-ink")))
            if e.get("status") == "rejected":
                for c in range(len(SHEET_COLUMNS)):
                    t.item(r, c).setForeground(QColor(tokens.c("muted")))
        t.resizeRowsToContents()
        ids = [e["entry_id"] for e in entries]
        if keep in ids:
            t.selectRow(ids.index(keep))
        else:  # 처음 연 칸은 첫 미검토 항목을 골라 둔다(A·R·E가 바로 듣게)
            first = next((i for i, e in enumerate(entries) if e.get("status") not in ("approved", "rejected")), None)
            if first is not None:
                t.selectRow(first)
        self.sheet_stack.setCurrentIndex(1)
        if row is not None:
            c = next(i for i, d in enumerate(self.deviations) if d["deviation_id"] == deviation_id)
            self.matrix.setCurrentCell(row, c)
        self._update_entry_buttons()
        return True

    # ------------------------------------------------------------ 항목 검토
    def selected_entry(self):
        ids = {i.data(Qt.UserRole) for i in self.table.selectedItems()}
        cell = self._cell_doc()
        if len(ids) != 1 or cell is None:
            return None
        eid = ids.pop()
        return next((e for e in cell["entries"] if e["entry_id"] == eid), None)

    def select_entry(self, index):
        self.table.selectRow(index)

    def _update_entry_buttons(self):
        # 실행 중에는 AI 결과가 같은 칸의 제안 항목을 바꿔 끼울 수 있어 검토 조작을 막는다(수정 내용 유실 방지)
        e = None if self.running() else self.selected_entry()
        self.approve_btn.setEnabled(e is not None and e.get("status") != "approved")
        self.reject_btn.setEnabled(e is not None and e.get("status") != "rejected")
        self.edit_btn.setEnabled(e is not None)
        self.ie_btn.setEnabled(e is not None)
        chips = ie_chips(e) if e is not None else []
        for i, c in enumerate(self.ie_chips):
            c.set_state(*(chips[i] if i < len(chips) else ("", "")))
            c.setVisible(i < len(chips))
        h = (e or {}).get("ie_hint") if isinstance((e or {}).get("ie_hint"), dict) else {}
        self.ie_reason.setText(h.get("reason") or ("항목을 고르면 판정이 보입니다" if e is None else ""))
        self.ie_reason.setToolTip(self.ie_reason.text())
        self._place_row_actions()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Resize and obj is self.table.viewport():
            QTimer.singleShot(0, self._place_row_actions)
        return super().eventFilter(obj, event)

    def _place_row_actions(self):
        """고른 행의 상태 칸 아래쪽에 동작 버튼을 띄운다. 그 행 높이는 버튼이 들어가게 늘린다."""
        rows = {i.row() for i in self.table.selectedItems()}
        if len(rows) != 1 or self.selected_entry() is None:
            self.row_actions.hide()
            return
        row = rows.pop()
        need = self.row_actions.sizeHint()
        cell = self.table.visualRect(self.table.model().index(row, COL_STATUS))
        text_h = self.table.fontMetrics().height() + 8
        if cell.height() < text_h + need.height():
            self.table.setRowHeight(row, text_h + need.height())
            cell = self.table.visualRect(self.table.model().index(row, COL_STATUS))
        w = max(need.width(), cell.width())
        self.row_actions.setGeometry(cell.right() - w + 1, cell.bottom() - need.height(), w, need.height())
        self.row_actions.show()
        self.row_actions.raise_()

    def _apply_review(self, doc):
        self.results = doc
        self._save()
        self.set_results(doc)

    def _undo_to(self, old, cell):
        """토스트 실행 취소: 바로 전 결과로 되돌려 저장한다. 이 동작 뒤 결과가 조금이라도 바뀌었으면(다른 승인·AI 결과
        반영·도면 바꾸기) 되돌리지 않는다. 결과 문서 전체를 바꿔 끼우므로 그 사이 변경을 지우지 않게 한다."""
        after = self.results

        def undo():
            if self.running() or self.results is not after:
                self.app.status_message("그 뒤에 결과가 바뀌어 되돌리지 않았습니다.")
                return
            self._apply_review(old)
            self.open_cell(*cell)
        return undo

    def _entry_or_hint(self, action):
        """고른 항목. 없으면 왜 안 되는지 상태줄에 알리고 None(A·R·E가 조용히 무시되지 않게)."""
        e = None if self.running() else self.selected_entry()
        if e is None:
            if self.running():
                text = "AI 분석 중에는 항목을 승인·기각·수정할 수 없습니다. 끝난 뒤 다시 하세요."
            elif self.node_set is None or self._cell_doc() is None:
                text = "행렬에서 칸을 먼저 여세요 (←↑↓→ 후 Enter 또는 클릭)."
            elif not self._cell_doc()["entries"]:
                text = "이 칸에는 검토할 항목이 없습니다."
            else:
                text = "%s 항목 행을 먼저 고르세요 (↑↓ 또는 클릭)." % NEED_ROW[action]
            self.app.status_message(text)
        return e

    def recheck_cell(self, by=None):
        """범위가 바뀐 칸의 판정을 사람이 다시 확인했다고 적는다(칸에 '범위 바뀜'이 없으면 할 일 없음)."""
        if self.cell is None or self._locked_message():
            return False
        by = by or getattr(self.app, "reviewer_name", lambda: "")() or "검토자"
        try:
            new = res.recheck_cell(self.results, self.cell[0], self.cell[1], by, node_set=self.node_set)
        except ValueError as exc:
            self.app.status_message(str(exc))
            return False
        if new is self.results:
            self.app.status_message("이 칸에는 다시 확인할 범위 바뀜이 없습니다.")
            return False
        old, cell = self.results, self.cell
        self._apply_review(new)
        self.app.toast("%s 칸 판정을 다시 확인했습니다" % cell[0], self._undo_to(old, cell))
        return True

    def _locked_message(self):
        """고른 칸을 사람이 고칠 수 없는 이유(잠긴 구간·보관 칸·읽기 전용)를 상태줄에 띄우고 True. 고칠 수 있으면 False."""
        why = (self.results or {}).get("read_only") or (
            res.editable_problem(self.results, self.cell[0], self.cell[1], self.node_set) if self.cell else None)
        if why:
            self.app.status_message(why)
        return bool(why)

    def set_entry_status(self, status):
        e = self._entry_or_hint(status)
        if e is None or self._locked_message():
            return False
        old, cell = self.results, self.cell
        self._apply_review(res.set_status(self.results, self.cell[0], self.cell[1], e["entry_id"], status,
                                          node_set=self.node_set))
        dev = next((d["label"] for d in self.deviations if d["deviation_id"] == cell[1]), cell[1])
        self.app.toast("%s × %s 시나리오를 %s했습니다" % (cell[0], dev, STATUS_LABELS[status]), self._undo_to(old, cell))
        return True

    def edit_selected(self, fields=None):
        """fields가 없으면 수정 창을 띄운다. 바뀐 필드가 없으면 저장하지 않는다."""
        e = self._entry_or_hint("edit")
        if e is None or self._locked_message():
            return False
        dlg = None if fields is not None else EntryDialog(e, self, self.ref_context(self.cell[0]) if self.ref_idx else None)
        while True:
            if dlg is not None:
                if dlg.exec() != QDialog.Accepted:
                    return False
                fields = dlg.changed()
            if not fields:
                return False
            try:
                new = res.edit_entry(self.results, self.cell[0], self.cell[1], e["entry_id"], fields,
                                     node_set=self.node_set)
                break
            except ValueError as exc:
                self.app.log_error("항목 수정 저장 실패", exc)
                QMessageBox.warning(self, "항목 수정", "저장할 수 없는 값이 있어 저장하지 않았습니다.%s" % (
                    " 고친 내용은 창에 그대로 남아 있습니다." if dlg is not None else ""))
                if dlg is None:
                    return False
        old, cell = self.results, self.cell
        self._apply_review(new)
        self.app.toast("%s 시나리오를 수정했습니다" % cell[0], self._undo_to(old, cell))
        return True

    def set_ie_selected(self, hint=None):
        """hint가 없으면 초기사건 판정 창을 띄운다. 항목 상태는 그대로 두고 판정만 사람 확정으로 저장한다."""
        e = self._entry_or_hint("ie")
        if e is None or self._locked_message():
            return False
        if hint is None:
            dlg = IeHintDialog(e, self)
            if dlg.exec() != QDialog.Accepted:
                return False
            hint = dlg.hint()
        try:
            new = res.set_ie_hint(self.results, self.cell[0], self.cell[1], e["entry_id"], hint, node_set=self.node_set)
        except ValueError as exc:
            self.app.log_error("초기사건 판정 저장 실패", exc)
            QMessageBox.warning(self, "초기사건 판정", "저장할 수 없는 값이 있어 저장하지 않았습니다.")
            return False
        old, cell = self.results, self.cell
        self._apply_review(new)
        self.app.toast("%s 시나리오의 초기사건 판정을 정했습니다" % cell[0], self._undo_to(old, cell))
        return True
