"""⑤ 설계보완·확정 (기획서/인터페이스.md §3.4, §5). 결정 기록·검사·저장·Excel은 hazop.review·hazop.export API만 호출한다.

- 실행은 읽기 전용으로 연다. 저장할 때마다 새 버전 파일(save_review), 실패하면 입력을 폼에 유지하고 오류 목록을 보여 준다.
- 위험도 등급은 사람이 입력하지 않는다: 강도·빈도를 고르면 rv.compute_risk가 〈표5〉로 계산한 값을 보여 준다.
- AI 제안은 'AI 제안 가져오기'를 눌러야 채워진다(rv.adopt_ai_proposal, source ai_proposal_adopted).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
                               QScrollArea, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from hazop import paths
from hazop import review as rv
from hazop.analysis.risk import FREQUENCIES, SEVERITIES
from hazop.app import data, render, runctx
from hazop.app.screens.analysis import fill_candidate_table, make_candidate_table
from hazop.app.widgets import Banner, Chip, badge, empty_label, esc, kst_text, plain_label, risk_chip
from hazop.export import SCOPES, ExportError, export_worksheet

SAVE_FAIL_NEXT = "다음 조치: 저장 위치(자료저장소)의 쓰기 권한·디스크 공간을 확인한 뒤 다시 저장하세요. 입력 내용은 폼에 남아 있습니다."


def confirmed_box():
    """사람 확정 상자(흰 바탕·진한 실선, QFrame#human_box). 저장된 결정이 없으면 숨는다."""
    box = QFrame()
    box.setObjectName("human_box")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(10, 6, 10, 6)
    box.label = QLabel("")
    box.label.setTextFormat(Qt.RichText)
    box.label.setWordWrap(True)
    lay.addWidget(box.label)
    box.hide()
    return box


def set_confirmed(box, dec, reviewed_at=None):
    if not dec:
        box.hide()
        return
    h = "%s <b>저장된 결정: %s</b> · 사유: %s<br><small>결정 %s · %s</small>" % (
        badge("확정", "human"), esc(data.DECISION_LABELS.get(dec.get("decision"), dec.get("decision"))),
        esc(dec.get("reason")), esc(dec.get("decided_by")),
        esc(kst_text(dec["decided_at"]) if dec.get("decided_at") else "시각 미확인"))
    rc = dec.get("risk_confirmation")
    if isinstance(rc, dict) and isinstance(rc.get("risk"), int):
        h += "<br>위험도 %s <small>(%s)</small>" % (
            risk_chip(rc["risk"], rc.get("risk_name"), proposal=False),
            "사람 확정 — AI 제안 채택" if rc.get("source") == "ai_proposal_adopted" else "사람 확정 — 직접 선택")
    if dec.get("imported_from"):
        h += "<br><small>이전 실행 %s에서 가져옴</small>" % esc(dec["imported_from"].get("analysis_run_id"))
    box.label.setText(h)
    box.show()

SCENARIO_CHOICES = (("accept", "수용"), ("modify", "수정"), ("reject", "기각"), ("defer", "보류"))
NOTE_SEVERITY = "보호수단 효과를 반영하지 않음(보호수단이 없다고 보고 정함)"


def _text_edit(text="", height=54, placeholder=""):
    t = QPlainTextEdit(text or "")
    t.setFixedHeight(height)
    t.setPlaceholderText(placeholder)
    return t


def _int_combo(values):
    cb = QComboBox()
    cb.addItem("선택", None)
    for v in values:
        cb.addItem(str(v), v)
    return cb


def _set_combo(cb, value):
    i = cb.findData(value)
    cb.setCurrentIndex(i if i >= 0 else 0)


class DecisionRadios(QWidget):
    changed = Signal()

    def __init__(self, choices=SCENARIO_CHOICES, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, label in choices:
            b = QRadioButton(label)
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
            b.toggled.connect(lambda on: on and self.changed.emit())
        lay.addStretch(1)

    def value(self):
        return next((k for k, b in self.buttons.items() if b.isChecked()), None)

    def set_value(self, key):
        self.group.setExclusive(False)
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self.group.setExclusive(True)
        self.changed.emit()


class PriorImport(QWidget):
    """이전 검토 대응 표시와 가져오기(§5.3): 0개 대응 없음, 1개 가져오기, 2개 이상 대상 선택 필수."""

    requested = Signal(object)  # choice(None 또는 고른 ID)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = plain_label("", "muted")
        self.choice = QComboBox()
        self.btn = QPushButton("가져오기")
        self.btn.clicked.connect(lambda: self.requested.emit(self.choice.currentData() if self.choice.count() else None))
        lay.addWidget(self.label)
        lay.addWidget(self.choice)
        lay.addWidget(self.btn)
        lay.addStretch(1)
        self.set_matches(None, [])

    def set_matches(self, prior, matches, id_key="scenario_id"):
        self.choice.clear()
        self.choice.hide()
        if prior is None:
            self.hide()
            return
        self.show()
        st = rv.match_status(matches)
        if st == "none":
            self.label.setText("이전 검토(%s): 대응 없음" % prior["analysis_run_id"])
            self.btn.setEnabled(False)
        elif st == "single":
            m = matches[0]
            self.label.setText("이전 검토(%s v%s): %s — %s" % (prior["analysis_run_id"], prior["review_version"],
                                                            data.DECISION_LABELS.get(m.get("decision"), "결정 미확인"),
                                                            m.get("reason")))
            self.btn.setEnabled(True)
        else:
            self.label.setText("이전 검토 대응 %d개 — 가져올 대상을 고르세요(자동 가져오기 없음)" % len(matches))
            self.choice.addItem("대상 선택", None)
            for m in matches:
                self.choice.addItem("%s — %s" % (m.get(id_key), data.DECISION_LABELS.get(m.get("decision"), "결정 미확인")),
                                    m.get(id_key))
            self.choice.show()
            self.btn.setEnabled(True)


class RelatedKnowledge(QWidget):
    """'관련 지식 (참고)' 묶음(그래프활용 §6.4.5): 기본 접힘. 실행의 근거 묶음 knowledge_context만 보여 준다.
    '③에서 보기'(kg:<entity_id> 링크)는 ReviewScreen.open_in_knowledge로 간다."""

    def __init__(self, screen, scenario):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        ctx = screen.ctx
        self.rk = data.related_knowledge(ctx.doc, scenario)
        self.toggle = self.view = None
        if self.rk is None:
            lay.addWidget(plain_label(runctx.KG_UNUSED, "muted"))
            return
        self.toggle = QPushButton()
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggled)
        lay.addWidget(self.toggle, 0, Qt.AlignLeft)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setHtml(render.related_knowledge_html(self.rk, ctx.tags, ctx.kg["state"] != "unreadable"))
        self.view.setMinimumHeight(120)
        self.view.setMaximumHeight(240)
        self.view.anchorClicked.connect(lambda url: screen.open_in_knowledge(url.toString()[len("kg:"):])
                                        if url.toString().startswith("kg:") else None)
        lay.addWidget(self.view)
        self._toggled(False)

    def _toggled(self, on):
        self.view.setVisible(on)
        self.toggle.setText("관련 지식 (참고) %d건 %s" % (len(self.rk["items"]), "▾ 접기" if on else "▸ 펼치기"))


class ScenarioForm(QGroupBox):
    """시나리오 하나의 결정 폼: 원안 ↔ 검토값, 결정·사유, 수정값, 위험도 확정."""

    decision_changed = Signal()

    def __init__(self, screen, scenario):
        super().__init__("시나리오 %s" % scenario["scenario_id"])
        self.screen, self.s = screen, scenario
        ctx = screen.ctx
        self.sid = scenario["scenario_id"]
        self.imported_from = None
        self.risk_source = "human"
        lay = QVBoxLayout(self)
        # 저장된 확정 결정: 사람 확정 표현(흰 바탕·진한 실선·'확정' 배지, 시안 README §2)
        self.confirmed = confirmed_box()
        lay.addWidget(self.confirmed)
        # 원안(위) → 검토값(아래) 세로 배치: 좁은 창(1366)에서도 가로로 잘리지 않게 한다
        cols = QVBoxLayout()
        orig = QTextBrowser()
        orig.setHtml(render.scenario_html(ctx.doc, scenario, ctx.tags))
        orig.setMinimumHeight(160)
        orig.setMaximumHeight(240)
        left = QVBoxLayout()
        lt = QLabel("원안 (읽기 전용)")
        lt.setObjectName("section")
        left.addWidget(lt)
        left.addWidget(orig)
        self.knowledge = RelatedKnowledge(screen, scenario)
        left.addWidget(self.knowledge)
        cols.addLayout(left)
        right = QVBoxLayout()
        rt = QLabel("검토값")
        rt.setObjectName("section")
        right.addWidget(rt)
        self.radios = DecisionRadios()
        self.radios.changed.connect(self._decision_changed)
        right.addWidget(self.radios)
        self.reason = _text_edit(placeholder="사유(필수)")
        right.addWidget(self.reason)
        base = rv.merge_display(scenario)
        self.base = base
        self.rev_box = QGroupBox("수정 (수정을 고를 때만)")
        rg = QGridLayout(self.rev_box)
        self.cause = _text_edit(base["cause"]["value"], 48)
        self.consequence = _text_edit(base["consequence"]["value"], 48)
        # 필드별 값 출처(merge_display): 미리 채운 원안은 고치면 '사람 수정'이 된다
        self.src_labels = {}
        for row, (key, label, w) in enumerate((("cause", "원인", self.cause), ("consequence", "결과", self.consequence))):
            rg.addWidget(QLabel(label), row * 2, 0)
            rg.addWidget(w, row * 2, 1)
            self.src_labels[key] = plain_label("", "muted")
            rg.addWidget(self.src_labels[key], row * 2 + 1, 1)
            w.textChanged.connect(self._update_sources)
        self.sg_list = QListWidget()
        self.sg_list.setMaximumHeight(70)
        for g in base["safeguards"]["value"]:
            self._add_sg_item(g)
        rg.addWidget(QLabel("보호수단"), 4, 0)
        rg.addWidget(self.sg_list, 4, 1)
        self.src_labels["safeguards"] = plain_label("", "muted")
        rg.addWidget(self.src_labels["safeguards"], 5, 1)
        sg_row = QHBoxLayout()
        self.sg_pick = QComboBox()
        for n in (ctx.run_graph or {}).get("nodes", []):
            if n.get("node_type") != "pipe_segment" and n.get("tag"):
                self.sg_pick.addItem("%s (%s)" % (n["tag"], n["entity_id"]), n["entity_id"])
        b_add = QPushButton("그래프 노드 추가")
        b_add.clicked.connect(self._add_sg)
        b_del = QPushButton("선택 제거")
        b_del.clicked.connect(self._remove_sg)
        self.sg_pick.setMinimumContentsLength(12)
        self.sg_pick.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        rg.addWidget(self.sg_pick, 6, 1)
        sg_row.addWidget(b_add)
        sg_row.addWidget(b_del)
        sg_row.addStretch(1)
        rg.addLayout(sg_row, 7, 1)
        hint = QLabel("도면에 없는 보호수단은 자료 요청 메모로 남깁니다.")
        hint.setWordWrap(True)
        rg.addWidget(hint, 8, 1)
        rg.setColumnStretch(1, 1)
        right.addWidget(self.rev_box)

        self.risk_box = QGroupBox("위험도 확정 (수용·수정은 강도·빈도·근거 필수)")
        kg = QGridLayout(self.risk_box)
        self.sev = _int_combo(SEVERITIES)
        self.sev_basis = QLineEdit()
        self.sev_basis.setPlaceholderText("강도 근거")
        kg.addWidget(QLabel("강도(1–4)"), 0, 0)
        kg.addWidget(self.sev, 0, 1)
        kg.addWidget(self.sev_basis, 0, 2)
        note = QLabel(NOTE_SEVERITY)
        note.setObjectName("muted")
        note.setWordWrap(True)
        kg.addWidget(note, 1, 1, 1, 2)
        self.f0 = _int_combo(FREQUENCIES)
        self.f = _int_combo(FREQUENCIES)
        self.f_basis = QLineEdit()
        self.f_basis.setPlaceholderText("빈도 근거")
        kg.addWidget(QLabel("빈도(보호수단 미반영)"), 2, 0)
        kg.addWidget(self.f0, 2, 1)
        kg.addWidget(QLabel("빈도(확정)"), 3, 0)
        kg.addWidget(self.f, 3, 1)
        kg.addWidget(self.f_basis, 3, 2)
        credit_title = QLabel("빈도를 낮출 때 인정한 보호수단 (확인 근거가 없으면 선택할 수 없음)")
        credit_title.setWordWrap(True)
        kg.addWidget(credit_title, 4, 0, 1, 3)
        kg.setColumnStretch(1, 1)
        kg.setColumnStretch(2, 2)
        self.credit_rows = []
        r = 5
        for g in scenario.get("safeguards") or []:
            cb = QCheckBox(g.get("tag") or g.get("node_id"))
            cb.setEnabled(False)
            ref = QLineEdit()
            ref.setPlaceholderText("확인 근거: 문서 참조")
            desc = QLineEdit()
            desc.setPlaceholderText("확인 근거: 설명(독립성·용량·작동)")
            why = QLabel("적정성·독립성 미확인 — 근거 입력 전 선택 불가")
            why.setObjectName("muted")
            why.setWordWrap(True)  # 좁은 폼에서 줄바꿈(가로 잘림 방지, W3)
            row = {"node_id": g.get("node_id"), "check": cb, "ref": ref, "desc": desc, "why": why}
            for w in (ref, desc):
                w.textChanged.connect(lambda _=None, rr=row: self._credit_enable(rr))
            kg.addWidget(cb, r, 0)
            kg.addWidget(ref, r, 1)
            kg.addWidget(desc, r, 2)
            kg.addWidget(why, r + 1, 1, 1, 2)
            r += 2
            self.credit_rows.append(row)
        if not self.credit_rows:
            kg.addWidget(QLabel("그래프 확인 보호수단 없음 — 빈도를 낮출 수 없음"), r, 0, 1, 3)
            r += 1
        self.risk_out = QLabel("")
        self.risk_out.setTextFormat(Qt.RichText)
        self.risk_out.setWordWrap(True)
        kg.addWidget(self.risk_out, r, 0, 1, 3)
        self.btn_ai = QPushButton("AI 제안 가져오기")
        self.btn_ai.setEnabled((scenario.get("risk_proposal") or {}).get("status") == "proposed")
        self.btn_ai.clicked.connect(self.adopt_ai)
        kg.addWidget(self.btn_ai, r + 1, 0)
        self.ai_note = QLabel("")
        self.ai_note.setTextFormat(Qt.RichText)
        kg.addWidget(self.ai_note, r + 1, 1, 1, 2)
        right.addWidget(self.risk_box)
        for cb in (self.sev, self.f0, self.f):
            cb.currentIndexChanged.connect(self._manual_risk)
        self.prior = PriorImport()
        self.prior.requested.connect(self.import_prior)
        right.addWidget(self.prior)
        cols.addLayout(right)
        lay.addLayout(cols)
        self._decision_changed()
        self._update_sources()

    def set_editable(self, on):
        """검토 입력(결정·사유·수정·위험도·이전 검토 가져오기)만 켜고 끈다. 원안·관련 지식은 항상 열람 가능."""
        self.editable = on
        for w in (self.radios, self.reason, self.prior):
            w.setEnabled(on)
        self._decision_changed()  # 수정·위험도 상자는 결정 값과 편집 가능 여부를 함께 따름

    def _sg_ids(self):
        return [self.sg_list.item(i).data(Qt.UserRole).get("node_id") for i in range(self.sg_list.count())]

    def _update_sources(self):
        """값 출처 표시: 원안 그대로면 '<출처> — 수정하면 사람 수정', 바꾸면 '사람 수정'."""
        if "safeguards" not in getattr(self, "src_labels", {}):
            return
        cur = {"cause": self.cause.toPlainText().strip(), "consequence": self.consequence.toPlainText().strip()}
        for key in ("cause", "consequence"):
            b = self.base[key]
            same = cur[key] == (b["value"] or "").strip()
            self.src_labels[key].setText("값 출처: %s" % (
                "%s — 수정하면 사람 수정" % rv.SOURCE_LABELS[b["source"]] if same else rv.SOURCE_LABELS["revised"]))
        same = self._sg_ids() == [g.get("node_id") for g in self.base["safeguards"]["value"]]
        self.src_labels["safeguards"].setText("값 출처: %s" % (
            "%s — 바꾸면 사람 수정" % rv.SOURCE_LABELS[self.base["safeguards"]["source"]] if same
            else rv.SOURCE_LABELS["revised"]))

    def _add_sg_item(self, g):
        it = QListWidgetItem("%s (%s)" % (g.get("tag") or self.screen.ctx.tags.get(g.get("node_id")) or "", g.get("node_id")))
        it.setData(Qt.UserRole, dict(g))
        self.sg_list.addItem(it)
        self._update_sources()

    def _add_sg(self):
        nid = self.sg_pick.currentData()
        if nid and nid not in [self.sg_list.item(i).data(Qt.UserRole)["node_id"] for i in range(self.sg_list.count())]:
            self._add_sg_item({"node_id": nid, "tag": self.screen.ctx.tags.get(nid), "source": "reviewer_selected"})

    def _remove_sg(self):
        self.sg_list.takeItem(self.sg_list.currentRow())
        self._update_sources()

    def _credit_enable(self, row):
        ok = bool(row["ref"].text().strip()) and bool(row["desc"].text().strip())
        row["check"].setEnabled(ok)
        row["why"].setText("" if ok else "적정성·독립성 미확인 — 근거 입력 전 선택 불가")
        if not ok:
            row["check"].setChecked(False)

    def _decision_changed(self):
        d = self.radios.value()
        on = getattr(self, "editable", True)
        self.rev_box.setEnabled(on and d == "modify")
        self.risk_box.setEnabled(on and d in ("accept", "modify"))
        if d == "defer":
            self.risk_box.setTitle("위험도 — 보류: 미확정(AI 제안은 참고만)")
        else:
            self.risk_box.setTitle("위험도 확정 (수용·수정은 강도·빈도·근거 필수)")
        self._update_risk()
        self.decision_changed.emit()

    def _manual_risk(self):
        if not getattr(self, "_filling", False):
            self.risk_source = "human"
            self.ai_note.setText("")
        self._update_risk()

    def _update_risk(self):
        sev, f = self.sev.currentData(), self.f.currentData()
        d = self.radios.value()
        if d in ("defer", "reject"):  # 보류·기각: 위험도는 저장하지 않음(미확정)
            self.risk_out.setText("위험도: %s — %s 결정은 위험도를 확정하지 않음" % (
                badge("미확정", "warn"), "보류" if d == "defer" else "기각"))
            return
        if sev is None or f is None:
            self.risk_out.setText("위험도: %s — 강도·빈도를 고르면 〈표5〉로 계산(직접 입력 불가)" % badge("미확정", "warn"))
            return
        try:
            calc = rv.compute_risk(self.screen.ctx.run["criteria"], sev, f)
        except rv.ReviewError as exc:
            self.risk_out.setText("<span style='color:#b91c1c'>%s</span>" % esc(exc))
            return
        self.risk_out.setText("위험도 %s (잠김 — 〈표5〉 계산값, 직접 입력 불가) <small>%s · 출처 %s</small>" % (
            risk_chip(calc["risk"], calc["risk_name"], proposal=False), esc(calc["calculation"]),
            "사람(AI 제안 채택)" if self.risk_source == "ai_proposal_adopted" else "사람(직접 선택)"))

    def adopt_ai(self):
        """'AI 제안 가져오기'(rv.adopt_ai_proposal). 근거 문장·인정 보호수단은 비워 둔다."""
        try:
            v = rv.adopt_ai_proposal(self.screen.ctx.run, self.sid)
        except rv.ReviewError as exc:
            self.ai_note.setText(esc(exc))
            return
        self._filling = True
        _set_combo(self.sev, v["severity"])
        _set_combo(self.f0, v["frequency_without_safeguards"])
        _set_combo(self.f, v["frequency"])
        self._filling = False
        self.sev_basis.clear()
        self.f_basis.clear()
        for row in self.credit_rows:
            row["check"].setChecked(False)
        self.risk_source = "ai_proposal_adopted"
        self.ai_note.setText(badge(v.get("note") or "AI 값에서 가져옴 — 근거 확인 필요", "ai"))
        self._update_risk()

    def risk_confirmation(self):
        sev, f0, f = self.sev.currentData(), self.f0.currentData(), self.f.currentData()
        credited = [{"node_id": r["node_id"], "basis": {"reference": r["ref"].text().strip(),
                                                        "description": r["desc"].text().strip()}}
                    for r in self.credit_rows if r["check"].isChecked()]
        if sev is None and f0 is None and f is None:
            return None
        if sev is None or f is None:  # 계산 불가 — 검사(validate_review)가 '비어 있음'으로 막는다
            return {"severity": sev, "severity_basis": self.sev_basis.text().strip(), "frequency_without_safeguards": f0,
                    "frequency": f, "frequency_basis": self.f_basis.text().strip(), "credited_safeguards": credited,
                    "source": self.risk_source}
        return rv.make_risk_confirmation(self.screen.ctx.run, sev, self.sev_basis.text().strip(), f0, f,
                                         self.f_basis.text().strip(), credited, self.risk_source)

    def revised(self):
        sgs = [self.sg_list.item(i).data(Qt.UserRole) for i in range(self.sg_list.count())]
        return {"cause": self.cause.toPlainText().strip(), "consequence": self.consequence.toPlainText().strip(),
                "safeguards": sgs}

    def collect(self, reviewer):
        d = self.radios.value()
        if d is None:
            return None
        rc = self.risk_confirmation() if d in ("accept", "modify") else None
        return rv.scenario_decision(self.screen.ctx.run, self.sid, d, self.reason.toPlainText().strip(), reviewer,
                                    revised=self.revised() if d == "modify" else None, risk_confirmation=rc,
                                    imported_from=self.imported_from)

    def reset(self):
        """결정·사유·수정값·위험도·인정 보호수단을 원안 기준 빈 상태로 되돌린다(가져오기 전에 섞이지 않게)."""
        self.radios.set_value(None)
        self.reason.clear()
        self.imported_from = None
        self.cause.setPlainText(self.base["cause"]["value"] or "")
        self.consequence.setPlainText(self.base["consequence"]["value"] or "")
        self.sg_list.clear()
        for g in self.base["safeguards"]["value"]:
            self._add_sg_item(g)
        self._filling = True
        for cb in (self.sev, self.f0, self.f):
            cb.setCurrentIndex(0)
        self._filling = False
        self.sev_basis.clear()
        self.f_basis.clear()
        for row in self.credit_rows:
            row["ref"].clear()
            row["desc"].clear()
            row["check"].setChecked(False)
        self.risk_source = "human"
        self.ai_note.setText("")
        self._update_risk()

    def show_confirmed(self, dec, reviewed_at=None):
        """저장된 결정을 사람 확정 상자로 보여 준다."""
        set_confirmed(self.confirmed, dec, reviewed_at)

    def fill(self, dec):
        """저장된(또는 가져온) 결정을 폼에 채운다. 먼저 폼을 비워 이전 값과 섞이지 않게 한다."""
        self.reset()
        self.radios.set_value(dec.get("decision"))
        self.reason.setPlainText(dec.get("reason") or "")
        self.imported_from = dec.get("imported_from")
        rev = dec.get("revised") or {}
        if "cause" in rev:
            self.cause.setPlainText(rev["cause"])
        if "consequence" in rev:
            self.consequence.setPlainText(rev["consequence"])
        if "safeguards" in rev:
            self.sg_list.clear()
            for g in rev["safeguards"]:
                self._add_sg_item(g)
        self._update_sources()
        rc = dec.get("risk_confirmation") or {}
        if rc:
            self._filling = True
            _set_combo(self.sev, rc.get("severity"))
            _set_combo(self.f0, rc.get("frequency_without_safeguards"))
            _set_combo(self.f, rc.get("frequency"))
            self._filling = False
            self.sev_basis.setText(rc.get("severity_basis") or "")
            self.f_basis.setText(rc.get("frequency_basis") or "")
            self.risk_source = rc.get("source") or "human"
            if self.risk_source == "ai_proposal_adopted":
                self.ai_note.setText(badge("AI 값에서 가져옴 — 근거 확인 필요", "ai"))
            credited = {c.get("node_id"): c.get("basis") or {} for c in rc.get("credited_safeguards") or []}
            for row in self.credit_rows:
                b = credited.get(row["node_id"])
                if b is not None:
                    row["ref"].setText(b.get("reference") or "")
                    row["desc"].setText(b.get("description") or "")
                    row["check"].setChecked(row["check"].isEnabled())
        self._update_risk()

    def import_prior(self, choice):
        prior = self.screen.prior
        try:
            dec = rv.import_scenario_decision(self.screen.ctx.run, self.sid, prior, self.reason.toPlainText().strip(),
                                              self.screen.reviewer(), choice=choice)
        except rv.ReviewError as exc:
            QMessageBox.warning(self, "가져오기", "\n".join(exc.errors))
            return False
        reason = self.reason.toPlainText()
        self.fill(dec)
        self.reason.setPlainText(reason)  # 사유는 새로 기록(가져오지 않음)
        return True


class DicForm(QGroupBox):
    """설계보완 후보 결정 폼. 연결 시나리오가 기각이면 '해당 없음'(자동, 사유 상속)."""

    def __init__(self, screen, dic, scenario_form):
        super().__init__("설계보완 후보 %s" % dic["dic_id"])
        self.screen, self.dic, self.sf = screen, dic, scenario_form
        self.did = dic["dic_id"]
        self.imported_from = None
        lay = QVBoxLayout(self)
        self.confirmed = confirmed_box()
        lay.addWidget(self.confirmed)
        orig = QTextBrowser()
        holds = {h["hold_id"]: h for h in screen.ctx.doc["holds"]}
        orig.setHtml(render.dic_html(dic, holds))
        orig.setMinimumHeight(110)
        orig.setMaximumHeight(170)
        lay.addWidget(orig)
        right = QVBoxLayout()
        self.na = QLabel("")
        self.na.setWordWrap(True)
        right.addWidget(self.na)
        self.radios = DecisionRadios()
        self.radios.changed.connect(self._changed)
        right.addWidget(self.radios)
        self.reason = _text_edit(placeholder="사유(필수)")
        right.addWidget(self.reason)
        self.recommendation = _text_edit(height=48, placeholder="개선 권고 문안(수용·수정 필수)")
        right.addWidget(self.recommendation)
        self.trigger = _text_edit(height=40, placeholder="발생 조건 설명(수정일 때만)")
        right.addWidget(self.trigger)
        self.prior = PriorImport()
        self.prior.requested.connect(self.import_prior)
        right.addWidget(self.prior)
        lay.addLayout(right)
        if scenario_form is not None:
            scenario_form.decision_changed.connect(self._changed)
        self._changed()

    def linked_rejected(self):
        return self.sf is not None and self.sf.radios.value() == "reject"

    def _changed(self):
        na = self.linked_rejected()
        self.radios.setEnabled(not na)
        self.reason.setEnabled(not na)
        d = self.radios.value()
        self.recommendation.setEnabled(not na and d in ("accept", "modify"))
        self.trigger.setEnabled(not na and d == "modify")
        if na:
            self.na.setText("%s 연결 시나리오 기각 — 사유 상속: %s" % (badge("해당 없음", "plain"),
                                                              esc(self.sf.reason.toPlainText().strip() or "(시나리오 사유 입력 필요)")))
            self.na.setTextFormat(Qt.RichText)
        else:
            self.na.setText("")

    def collect(self, reviewer):
        if self.linked_rejected():
            return None  # build_review가 not_applicable로 자동 지정
        d = self.radios.value()
        if d is None:
            return None
        trig = self.trigger.toPlainText().strip()
        return rv.dic_decision(self.screen.ctx.run, self.did, d, self.reason.toPlainText().strip(), reviewer,
                               recommendation=self.recommendation.toPlainText().strip() or None,
                               revised={"trigger_description": trig} if d == "modify" and trig else None,
                               imported_from=self.imported_from)

    def reset(self):
        self.radios.set_value(None)
        for w in (self.reason, self.recommendation, self.trigger):
            w.clear()
        self.imported_from = None
        self._changed()

    def show_confirmed(self, dec, reviewed_at=None):
        set_confirmed(self.confirmed, dec, reviewed_at)

    def fill(self, dec):
        """먼저 폼을 비우고 채운다(가져온 값과 이전 입력이 섞이지 않게)."""
        self.reset()
        if dec.get("decision") == "not_applicable":
            return
        self.radios.set_value(dec.get("decision"))
        self.reason.setPlainText(dec.get("reason") or "")
        self.recommendation.setPlainText(dec.get("recommendation") or "")
        self.trigger.setPlainText((dec.get("revised") or {}).get("trigger_description") or "")
        self.imported_from = dec.get("imported_from")

    def import_prior(self, choice):
        try:
            dec = rv.import_dic_decision(self.screen.ctx.run, self.did, self.screen.prior,
                                         self.reason.toPlainText().strip(), self.screen.reviewer(), choice=choice)
        except rv.ReviewError as exc:
            QMessageBox.warning(self, "가져오기", "\n".join(exc.errors))
            return False
        reason = self.reason.toPlainText()
        self.fill(dec)
        self.reason.setPlainText(reason)
        return True


class NoScenarioForm(QGroupBox):
    def __init__(self, screen, cand):
        super().__init__("시나리오 없음 확인")
        self.screen = screen
        self.imported_from = None
        lay = QVBoxLayout(self)
        an = cand.get("analysis") or {}
        self.confirmed = confirmed_box()
        lay.addWidget(self.confirmed)
        lay.addWidget(plain_label("이 선택 편차에는 시나리오가 없습니다(AI 상태: %s). 확인하면 사유와 함께 기록합니다."
                                  % data.AI_STATUS_LABELS.get(an.get("ai_status"), "미확인")))
        self.check = QCheckBox("시나리오 없음 확인")
        lay.addWidget(self.check)
        self.reason = _text_edit(placeholder="사유(필수)")
        lay.addWidget(self.reason)
        self.prior = PriorImport()
        self.prior.requested.connect(self.import_prior)
        lay.addWidget(self.prior)

    def collect(self, reviewer):
        if not self.check.isChecked():
            return None
        return rv.no_scenario_confirmation(self.reason.toPlainText().strip(), reviewer, imported_from=self.imported_from)

    def fill(self, nsc):
        self.check.setChecked(False)
        self.reason.clear()
        self.imported_from = None
        if nsc:
            self.check.setChecked(True)
            self.reason.setPlainText(nsc.get("reason") or "")
            self.imported_from = nsc.get("imported_from")

    def import_prior(self, _choice):
        try:
            dec = rv.import_no_scenario_confirmation(self.screen.prior, self.reason.toPlainText().strip(),
                                                     self.screen.reviewer())
        except rv.ReviewError as exc:
            QMessageBox.warning(self, "가져오기", "\n".join(exc.errors))
            return False
        self.check.setChecked(True)
        self.imported_from = dec["imported_from"]
        return True


class ExcelDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Excel 내보내기")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("KOSHA P-86 워크시트 양식(.xlsx). 위험도 열에는 사람 확정값만 들어갑니다."))
        self.radios = DecisionRadios(tuple(SCOPES.items()))
        self.radios.set_value("all")
        lay.addWidget(self.radios)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class ReviewScreen(QWidget):
    title = "⑤ 설계보완·확정"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("screen")
        self.ctx = None
        self.cid = None
        self.prior = None
        self.priors = []
        self.sforms, self.dforms, self.nsform = {}, {}, None
        self.memos = []
        self.last_errors = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        bar = QHBoxLayout()
        self.run_label = plain_label("", "muted", elide=Qt.ElideMiddle, min_chars=20)  # 좁으면 가운데 줄임, 전체는 툴팁(W3)
        bar.addWidget(self.run_label)
        self.chip_progress = Chip(elide=Qt.ElideRight, min_chars=14)
        bar.addWidget(self.chip_progress)
        self.chip_kg = Chip(elide=Qt.ElideMiddle, min_chars=10)  # 지식그래프 버전이 분석 당시와 같을 때 "지식 v-xxxx"(그래프활용 §6.4.3)
        self.chip_kg.hide()
        bar.addWidget(self.chip_kg)
        bar.addStretch(1)
        bar.addWidget(QLabel("검토자"))
        self.reviewer_edit = QLineEdit()
        self.reviewer_edit.setPlaceholderText("검토자 이름(필수)")
        self.reviewer_edit.setFixedWidth(140)
        bar.addWidget(self.reviewer_edit)
        b = QPushButton("검토자 저장")
        b.clicked.connect(self._save_reviewer)
        bar.addWidget(b)
        self.btn_excel = QPushButton("Excel 내보내기")
        self.btn_excel.clicked.connect(self.ask_excel)
        bar.addWidget(self.btn_excel)
        lay.addLayout(bar)
        self.banner_lock = Banner("err")
        self.banner_info = Banner("warn")
        self.banner_kg = Banner("warn")  # 지식그래프 바뀜·읽기 불가(그래프활용 §6.4.3)
        lay.addWidget(self.banner_lock)
        lay.addWidget(self.banner_info)
        lay.addWidget(self.banner_kg)

        self.body = QStackedWidget()
        self.empty = empty_label("④에서 분석 실행을 열면 검토할 수 있습니다.")
        self.body.addWidget(self.empty)
        split = QSplitter(Qt.Horizontal)
        self.body.addWidget(split)
        lay.addWidget(self.body, 1)

        left = QFrame()
        left.setObjectName("panel")
        ll = QVBoxLayout(left)
        lt = QLabel("편차 후보")
        lt.setObjectName("title")
        ll.addWidget(lt)
        self.table = make_candidate_table("검토 상태")
        self.table.itemSelectionChanged.connect(self._candidate_changed)
        ll.addWidget(self.table, 3)
        il = QLabel("시나리오 · 설계보완 후보")
        il.setObjectName("section")
        ll.addWidget(il)
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self._item_changed)
        ll.addWidget(self.items, 2)
        split.addWidget(left)

        self.canvas_host = QWidget()
        QVBoxLayout(self.canvas_host).setContentsMargins(0, 0, 0, 0)
        self.canvas_note = empty_label("")
        self.canvas_stack = QStackedWidget()
        self.canvas_stack.addWidget(self.canvas_note)
        self.canvas_stack.addWidget(self.canvas_host)
        split.addWidget(self.canvas_stack)

        right = QFrame()
        right.setObjectName("panel")
        rl = QVBoxLayout(right)
        self.form_title = plain_label("", "title")
        rl.addWidget(self.form_title)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("이전 검토(참고)"))
        self.prior_combo = QComboBox()
        self.prior_combo.currentIndexChanged.connect(self._prior_changed)
        prow.addWidget(self.prior_combo, 1)
        rl.addLayout(prow)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rl.addWidget(self.scroll, 1)
        self.errors = QListWidget()
        self.errors.setMaximumHeight(110)
        self.errors.setStyleSheet("QListWidget { color: #b91c1c; border-color: #fca5a5; }")
        self.errors.hide()
        rl.addWidget(self.errors)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("검토 요약 사유"))
        self.summary_reason = QLineEdit()
        self.summary_reason.setPlaceholderText("편차 검토 요약(필수)")
        srow.addWidget(self.summary_reason, 1)
        self.btn_save = QPushButton("저장(새 버전)")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self.save)
        srow.addWidget(self.btn_save)
        rl.addLayout(srow)
        split.addWidget(right)
        split.setSizes([330, 380, 660])

    # ------------------------------------------------------------ 공통
    def where(self):
        if not self.ctx:
            return None
        return {"region": self.ctx.doc["analysis_run"]["region"].get("name") or self.ctx.region_id,
                "drawing": self.ctx.drawing_name, "run": self.ctx.doc["analysis_run_id"]}

    def reviewer(self):
        return self.reviewer_edit.text().strip() or (self.app.reviewer_name() or "")

    def _save_reviewer(self):
        name = self.reviewer_edit.text().strip()
        if name:
            self.app.set_reviewer_name(name)

    def on_enter(self):
        self.app.webview.set_mode(hide_panel=True)
        self.reviewer_edit.setText(self.app.reviewer_name() or "")
        if self.ctx is not self.app.run_ctx:
            self.set_ctx(self.app.run_ctx)
        elif self.ctx and self.ctx.html():
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_drawing_enabled(not self.ctx.version_mismatch)
            self.app.webview.load_file(self.ctx.html())

    def set_ctx(self, ctx):
        self.ctx = ctx
        if ctx is None:
            self.body.setCurrentIndex(0)
            return
        self.body.setCurrentIndex(1)
        self.run_label.setText("실행 %s (읽기 전용)" % ctx.doc["analysis_run_id"])
        self.chip_kg.set_state(ctx.kg["text"] if ctx.kg["state"] == "same" else "")
        self.chip_kg.setVisible(ctx.kg["state"] == "same")
        self.banner_kg.set_messages(ctx.kg["text"] if ctx.kg["state"] in ("changed", "unreadable") else None)
        if ctx.html():
            self.canvas_stack.setCurrentIndex(1)
            self.app.attach_webview(self.canvas_host)
            self.app.webview.set_drawing_enabled(not ctx.version_mismatch)  # 그래프 버전 불일치면 도면 탭 잠금
            self.app.webview.load_file(ctx.html())
        else:
            self.canvas_stack.setCurrentIndex(0)
            self.canvas_note.setText(ctx.viewer_error or "")
        self.refresh_table()

    def open_in_knowledge(self, entity_id):
        """'③에서 보기': ③으로 가서 실행의 kg_id·도면을 고르고 기존 selectNode로 노드를 고른다(새 브리지 메시지 없음).
        ③이 연 버전이 기록 kg_version과 다르면 이동만 하고 자동 선택하지 않는다(W7-9). 반환: 자동 선택 여부."""
        st = self.ctx.kg if self.ctx else {"state": "unused"}
        if st["state"] in ("unused", "unreadable"):
            return False
        self.app.go(4)
        return self.app.screens[4].open_node(st["kg_id"], self.ctx.doc["graph_ref"]["graph_id"], entity_id,
                                             st["recorded"])

    def excel_block_reasons(self):
        """Excel 출력을 막는 사유: blocked 결과, analysis.json 삭제·변경, 검토 기록의 analysis_sha256 불일치."""
        ctx = self.ctx
        if ctx is None:
            return ["열린 실행 없음"]
        reasons = list(rv.check_editable(ctx.run, None)["reasons"])
        for cid, rec in sorted(ctx.records.items()):
            for r in rv.check_editable(ctx.run, rec)["reasons"]:
                if r not in reasons:
                    reasons.append("%s: %s" % (cid, r) if "검토 기록" in r else r)
        return reasons

    def update_excel_state(self):
        reasons = self.excel_block_reasons()
        self.btn_excel.setEnabled(not reasons)
        self.btn_excel.setToolTip("\n".join(reasons))
        self.banner_info.set_messages("Excel 출력 막힘" if reasons else None, reasons)

    def refresh_table(self, keep=None):
        ctx = self.ctx
        ctx.reload_reviews()
        c = ctx.summary["counts"]
        self.chip_progress.set_state("미검토 %d · 검토 중 %d · 보류 %d · 확정 %d · 판정 제외 %d" % (
            c["not_reviewed"], c["reviewing"], c["deferred"], c["confirmed"],
            len(ctx.summary["excluded"]) + len(ctx.summary["selection_deferred"])))
        extra = {k: data.STATUS_LABELS[v] for k, v in ctx.summary["by_candidate"].items()}
        self.table.blockSignals(True)
        fill_candidate_table(self.table, data.candidate_rows(ctx.doc), extra)
        self.table.blockSignals(False)
        self.update_excel_state()
        self.select_candidate(keep or self.cid or next(iter(ctx.summary["by_candidate"]), None))

    def select_candidate(self, cid, scenario_id=None):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == cid:
                self.table.selectRow(r)
                if cid == self.cid:
                    self._candidate_changed(force=True)
                break
        if scenario_id:
            for i in range(self.items.count()):
                if self.items.item(i).data(Qt.UserRole) == ("scenario", scenario_id):
                    self.items.setCurrentRow(i)

    # ------------------------------------------------------------ 폼
    def _candidate_changed(self, force=False):
        r = self.table.currentRow()
        cid = self.table.item(r, 0).data(Qt.UserRole) if r >= 0 else None
        if cid == self.cid and not force:
            return
        self.cid = cid
        self.errors.hide()
        self.items.blockSignals(True)
        self.items.clear()
        self.items.blockSignals(False)
        self.sforms, self.dforms, self.nsform = {}, {}, None
        holder = QWidget()
        vl = QVBoxLayout(holder)
        self.scroll.setWidget(holder)
        if not cid:
            return
        ctx = self.ctx
        cand = ctx.candidate(cid)
        self.form_title.setText("%s · %s" % (cand.get("item_id"), cand.get("deviation")))
        rec = ctx.records.get(cid)
        ed = ctx.editable(cid)
        self.banner_lock.set_messages(None if ed["editable"] else "열람 전용 — 편집·저장·Excel 출력 막힘", ed["reasons"])
        self.update_excel_state()
        self.priors = rv.find_prior_reviews(ctx.store_root, ctx.region_id, ctx.doc["analysis_run_id"], cid)
        self.prior_combo.blockSignals(True)
        self.prior_combo.clear()
        self.prior_combo.addItem("없음" if not self.priors else "사용 안 함", None)
        for i, p in enumerate(self.priors):
            self.prior_combo.addItem("%s v%s (%s)" % (p["analysis_run_id"], p["review_version"],
                                                      p["record"].get("reviewed_at")), i)
        self.prior_combo.setCurrentIndex(1 if self.priors else 0)
        self.prior_combo.blockSignals(False)
        if cand["selection_status"] != "selected":
            vl.addWidget(empty_label("판정 제외 후보(%s) — 검토 확정 대상이 아님. 사유: %s"
                                     % (data.SELECTION_LABELS.get(cand["selection_status"]), cand.get("reason"))))
            self.btn_save.setEnabled(False)
            vl.addStretch(1)
            return
        scen = ctx.scenarios_of(cid)
        sdec = {d["scenario_id"]: d for d in (rec or {}).get("scenario_decisions") or []}
        ddec = {d["dic_id"]: d for d in (rec or {}).get("design_improvement_decisions") or []}
        for s in scen:
            f = ScenarioForm(self, s)
            if s["scenario_id"] in sdec:
                f.fill(sdec[s["scenario_id"]])
                f.show_confirmed(sdec[s["scenario_id"]])
            self.sforms[s["scenario_id"]] = f
            vl.addWidget(f)
            it = QListWidgetItem("시나리오 %s" % s["scenario_id"].replace("scenario-", ""))
            it.setData(Qt.UserRole, ("scenario", s["scenario_id"]))
            self.items.addItem(it)
        for d in ctx.dics_of(cid):
            f = DicForm(self, d, self.sforms.get(d["scenario_id"]))
            if d["dic_id"] in ddec:
                f.fill(ddec[d["dic_id"]])
                f.show_confirmed(ddec[d["dic_id"]])
            self.dforms[d["dic_id"]] = f
            vl.addWidget(f)
            it = QListWidgetItem("설계보완 후보 %s" % d["dic_id"].replace("dic-scenario-", ""))
            it.setData(Qt.UserRole, ("dic", d["dic_id"]))
            self.items.addItem(it)
        if not scen:
            self.nsform = NoScenarioForm(self, cand)
            nsc = (rec or {}).get("no_scenario_confirmation")
            self.nsform.fill(nsc)
            set_confirmed(self.nsform.confirmed, dict(nsc, decision="confirm_no_scenario") if nsc else None)
            vl.addWidget(self.nsform)
        self.memos = [dict(m) for m in (rec or {}).get("memo_records") or []]
        vl.addWidget(self._memo_box(cid))
        vl.addStretch(1)
        self.summary_reason.setText((rec or {}).get("reason") or "")
        self._prior_changed()
        # 잠긴 실행: 편집 입력만 끈다. 원안·관련 지식(펼치기·③에서 보기)은 열람용이라 켜 둔다
        for i in range(vl.count()):
            w = vl.itemAt(i).widget()
            if isinstance(w, ScenarioForm):
                w.set_editable(ed["editable"])
            elif w is not None:
                w.setEnabled(ed["editable"])
        self.btn_save.setEnabled(ed["editable"])
        if self.items.count():
            self.items.setCurrentRow(0)
        else:
            self.app.webview.clear_highlight()

    def _memo_box(self, cid):
        box = QGroupBox("자료 요청 메모 (조치로 자동 전환하지 않음)")
        lay = QVBoxLayout(box)
        self.memo_list = QListWidget()
        self.memo_list.setMaximumHeight(80)
        for m in self.memos:
            self.memo_list.addItem("%s: %s (%s)" % (m["memo_id"], m["content"], ", ".join(m.get("hold_ids") or [])))
        lay.addWidget(self.memo_list)
        self.memo_holds = QListWidget()
        self.memo_holds.setSelectionMode(QAbstractItemView.MultiSelection)
        self.memo_holds.setMaximumHeight(70)
        for h in self.ctx.holds_of(cid):
            if h.get("status") == "open":
                it = QListWidgetItem("%s %s" % (h["hold_id"], h.get("item")))
                it.setData(Qt.UserRole, h["hold_id"])
                self.memo_holds.addItem(it)
        lay.addWidget(QLabel("관련 열린 보류(여러 개 선택 가능)"))
        lay.addWidget(self.memo_holds)
        self.memo_content = QLineEdit()
        self.memo_content.setPlaceholderText("요청 내용")
        self.memo_reason = QLineEdit()
        self.memo_reason.setPlaceholderText("사유")
        b = QPushButton("메모 추가")
        b.clicked.connect(self.add_memo)
        row = QHBoxLayout()
        row.addWidget(self.memo_content, 2)
        row.addWidget(self.memo_reason, 1)
        row.addWidget(b)
        lay.addLayout(row)
        return box

    def add_memo(self):
        content = self.memo_content.text().strip()
        if not content:
            return False
        holds = [it.data(Qt.UserRole) for it in self.memo_holds.selectedItems()]
        mid = "memo-%03d" % (len(self.memos) + 1)
        self.memos.append(rv.memo_record(mid, content, self.memo_reason.text().strip(), self.reviewer(), holds))
        self.memo_list.addItem("%s: %s (%s)" % (mid, content, ", ".join(holds)))
        self.memo_content.clear()
        self.memo_reason.clear()
        return True

    def _prior_changed(self):
        i = self.prior_combo.currentData()
        self.prior = self.priors[i] if i is not None and i < len(self.priors) else None
        p = self.prior
        for sid, f in self.sforms.items():
            f.prior.set_matches(p, rv.match_scenario(p["record"], f.s) if p else [], "scenario_id")
        for did, f in self.dforms.items():
            f.prior.set_matches(p, rv.match_dic(p["record"], self.ctx.doc, f.dic) if p else [], "dic_id")
        if self.nsform is not None:
            nsc = (p or {}).get("record", {}).get("no_scenario_confirmation") if p else None
            self.nsform.prior.set_matches(p, [nsc] if nsc else [], "candidate_id")

    def _item_changed(self, row):
        if row < 0:
            return
        kind, iid = self.items.item(row).data(Qt.UserRole)
        if kind == "scenario":
            sid, w = iid, self.sforms.get(iid)
        else:
            w = self.dforms.get(iid)
            sid = w.dic["scenario_id"] if w else None
        if w is not None:
            self.scroll.ensureWidgetVisible(w, 0, 0)
        if sid:
            spec = self.ctx.highlight_spec(self.ctx.scenario(sid))
            if spec:
                self.app.webview.highlight(spec)
            else:
                self.app.webview.clear_highlight()

    def on_node(self, sel):
        eid = sel.get("entity_id")
        tag = self.ctx.tags.get(eid) if self.ctx and eid else None
        self.app.status_message("선택한 객체: %s" % (tag or eid or "태그 미확인"))
        self.app.debug_message("nodeSelected: %s" % (eid or sel.get("local_id")))

    # ------------------------------------------------------------ 저장·출력
    def build_record(self):
        reviewer = self.reviewer()
        sds = [d for d in (f.collect(reviewer) for f in self.sforms.values()) if d is not None]
        dds = [d for d in (f.collect(reviewer) for f in self.dforms.values()) if d is not None]
        nsc = self.nsform.collect(reviewer) if self.nsform is not None else None
        return rv.build_review(self.ctx.run, self.cid, reviewer, self.summary_reason.text().strip(), sds, dds, nsc,
                               self.memos)

    def show_errors(self, errs):
        self.last_errors = list(errs)
        self.errors.clear()
        if errs:
            self.errors.addItem("저장하지 않음 — 아래 %d건을 고친 뒤 다시 저장하세요" % len(errs))
            self.errors.addItems(errs)
            self.errors.show()
        else:
            self.errors.hide()

    def save(self, ask_name=True):
        """저장: 검토자 확인 → build_review → validate_review → save_review(새 버전). 성공하면 경로, 실패하면 None."""
        if not self.ctx or not self.cid:
            return None
        if not self.reviewer() and ask_name:
            name, ok = QInputDialog.getText(self, "검토자 이름", "저장 전에 검토자 이름을 입력하세요")
            if ok and name.strip():
                self.app.set_reviewer_name(name.strip())
                self.reviewer_edit.setText(name.strip())
        try:
            rec = self.build_record()
            errs = rv.validate_review(self.ctx.run, rec)
            if errs:
                self.show_errors(errs)
                return None
            path, saved = rv.save_review(self.ctx.store_root, self.ctx.run, rec)
        except rv.ReviewError as exc:
            self.show_errors(exc.errors)
            return None
        except OSError as exc:  # 권한·디스크 부족 등: 실패를 성공으로 표시하지 않음
            self.app.log_error("검토 저장 실패", exc)
            self.show_errors(["저장 실패: %s" % (exc.strerror or exc), SAVE_FAIL_NEXT])
            return None
        self.show_errors([])
        self.app.mark_saved(saved["reviewed_at"])
        self.app.status_message("검토 저장: v%d — %s" % (saved["review_version"], paths.rel_or_abs(path, self.ctx.store_root)))
        self.refresh_table(keep=self.cid)
        return path

    def ask_excel(self):
        dlg = ExcelDialog(self)
        if dlg.exec() == QDialog.Accepted:
            out = self.export_excel(dlg.radios.value())
            if out:
                QMessageBox.information(self, "Excel 내보내기", "만든 파일: %s" % out)

    def export_excel(self, scope="all"):
        if not self.ctx:
            return None
        reasons = self.excel_block_reasons()
        if reasons:
            self.update_excel_state()
            return None
        try:
            res = export_worksheet(self.ctx.run_dir, self.ctx.store_root, paths.output_root("워크시트"), scope)
        except (ExportError, rv.ReviewError) as exc:  # ExportError는 ReviewError의 하위 클래스
            self.banner_info.set_messages("Excel 출력 실패 — 파일을 만들지 않음", exc.errors)
            return None
        except OSError as exc:
            self.app.log_error("Excel 출력 실패", exc)
            self.banner_info.set_messages("Excel 출력 실패 — 파일을 만들지 않음",
                                          ["%s" % (exc.strerror or exc),
                                           "다음 조치: 출력 폴더의 쓰기 권한·디스크 공간을 확인하고, 같은 파일이 열려 있으면 닫은 뒤 다시 시도하세요."])
            return None
        path = res["path"]
        self.banner_info.set_messages(None)
        self.app.status_message("Excel 출력: %s" % path)
        return path
