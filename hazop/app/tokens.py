"""디자인 토큰 한 곳 정의 (기획서/인터페이스.md §4.1·§4.2, 디자인/시안/README.md §3·§4.1).

Qt 스타일시트(qss)와 내장 웹뷰 CSS(web_css)가 모두 이 값을 읽는다. ② 뷰어에는 실행 시점에 CSS 변수로 주입하므로
hazop/viewer/template.html의 색은 바꾸지 않는다(단독 뷰어는 기존 색 그대로, 템플릿은 탭 이름만 'P&ID 구조'로 바뀜).
③ 지식그래프 HTML(hazop/kg/screen_template.html)은 생성할 때 kg_css_vars()로 같은 값을 넣는다.
글꼴: Pretendard 배포는 미결정(§9)이므로 포함하지 않고 맑은 고딕을 기본으로 쓴다.
"""

FONT_FAMILY = "Malgun Gothic"

COLORS = {
    # UI: 강조색은 파랑 하나
    "ui": "#2563eb", "ui-weak": "#eff6ff", "ui-ink": "#1e40af",
    "bg": "#f4f5f7", "card": "#ffffff", "line": "#e3e5e9", "line-strong": "#cfd3da",
    "muted": "#6b7280", "ink": "#111827", "ink-2": "#374151",
    # 데이터: 노드 종류(밸브는 UI 파랑과 분리)
    "equipment": "#1d4ed8", "valve": "#0f766e", "instrument": "#0ea5e9", "piping_element": "#6366f1",
    "unclassified": "#9ca3af",
    # 데이터: 관계 종류
    "physical_connection": "#16a34a", "signal_connection": "#7c3aed", "measurement_connection": "#d97706",
    "unresolved": "#dc2626",
    # 시나리오 강조(§3.3 강조 규칙)
    "hl-cause": "#dc2626", "hl-path": "#ea580c", "hl-safeguard": "#c026d3",
    # 상태
    "ok": "#15803d", "warn-bg": "#fef3c7", "warn-ink": "#92400e", "warn-line": "#f59e0b",
    "err-bg": "#fef2f2", "err-ink": "#b91c1c", "err-line": "#fca5a5",
    # 위험도 〈표9〉 허용 구분 3단
    "risk-ok-bg": "#eef0f3", "risk-ok-ink": "#374151", "risk-ok-line": "#9ca3af",
    "risk-cond-bg": "#fde68a", "risk-cond-ink": "#78350f", "risk-cond-line": "#d97706",
    "risk-deny-bg": "#991b1b", "risk-deny-ink": "#ffffff", "risk-deny-line": "#991b1b",
    # 출처: AI·자동 판독 = 빗금(Qt는 옅은 회색 + 점선 테두리로 대신), 사람 확정 = 흰 바탕 진한 실선
    "ai-hatch-a": "#f1f2f4", "ai-hatch-b": "#e8eaee", "ai-ink": "#4b5563", "human-line": "#111827",
    "tag": "#111827",
    # ③ 지식그래프 (디자인/지식그래프화면.md §7). 별칭 토큰(=)은 같은 값을 풀어 적는다
    "kg-document": "#475569", "kg-doc_chunk": "#64748b", "kg-requirement": "#a16207", "kg-setpoint": "#be185d",
    "kg-condition": "#4d7c0f", "kg-analysis_case": "#9a3412", "kg-pipe_segment": "#16a34a",
    "kg-rel-mentions": "#64748b", "kg-rel-docpos": "#cbd5e1", "kg-rel-depends": "#334155",
    "kg-flag": "#f59e0b", "kg-flag-ink": "#92400e", "kg-conflict": "#b91c1c", "kg-nosrc": "#b91c1c",
    "a1-start": "#111827", "a1-down": "#0072b2", "a1-up": "#d55e00", "a1-mixed": "#cc79a7", "a1-unknown": "#9ca3af",
    "a1-adj": "#009e73", "a1-na": "#6b7280", "a1-off": "#d1d5db",
    "comp-1": "#0072b2", "comp-2": "#e69f00", "comp-3": "#009e73", "comp-4": "#cc79a7", "comp-5": "#56b4e9",
    "comp-6": "#d55e00", "comp-other": "#9ca3af",
    "kg-canvas": "#fcfcfd",
}
HL_DIM = 0.16  # 강조 중 나머지 오버레이 불투명도
# ③ 지식그래프 색 외 값(디자인/지식그래프화면.md §2·§5·§7)
KG_STYLE = {"kg-excl-opacity": "0.5", "kg-dash": "5 4", "kg-left": "clamp(232px, 18vw, 300px)"}
KG_RIGHT_MIN, KG_RIGHT_MAX, KG_RIGHT_VW = 320, 420, 0.24  # 우측 상세(Qt) clamp(320px, 24vw, 420px)


def kg_css_vars():
    """③ 지식그래프 HTML(hazop/kg/screen_template.html)의 :root 변수. 색은 COLORS 한 곳에서 읽는다."""
    items = ["--%s: %s" % (k, v) for k, v in COLORS.items()]
    items += ["--%s: %s" % (k, v) for k, v in KG_STYLE.items()]
    items.append("--hl-dim: %s" % HL_DIM)
    return ":root { %s; }" % "; ".join(items)

FONT_SIZE = {"xs": 11, "sm": 12, "md": 13, "lg": 15, "xl": 20}


def c(name):
    return COLORS[name]


def risk_band(risk):
    """위험도 1–5 → 'ok'(1·2 수용) / 'cond'(3·4 조건부 수용) / 'deny'(5 불허). 값이 없으면 None.
    〈표9〉 비고 칸을 허용 구분으로 해석한 것은 [추론](HAZOP기법지침 §6)."""
    if not isinstance(risk, int):
        return None
    return "ok" if risk <= 2 else ("cond" if risk <= 4 else "deny")


def risk_colors(risk):
    band = risk_band(risk) or "ok"
    return COLORS["risk-%s-bg" % band], COLORS["risk-%s-ink" % band], COLORS["risk-%s-line" % band]


def web_css():
    """내장 웹뷰에 주입하는 CSS: 토큰 변수 덮어쓰기 + 선택색(UI 파랑) + 시나리오 강조 + 내장 모드 표시."""
    root = "; ".join("--%s: %s" % (k, v) for k, v in COLORS.items())
    return """
:root { %(root)s; --selected: %(ui)s; --hl-dim: %(dim)s; }
html, body { font-family: "%(font)s", sans-serif; }
.selected.sym, .selected.tagbox { stroke: var(--ui) !important; fill: rgba(37,99,235,.12); }
.selected.pipe-line, .selected.gnode, .selected.gedge { stroke: var(--ui) !important; }
body.hz-embedded a.back, body.hz-embedded header .logo, body.hz-embedded header .app, body.hz-embedded header .sep { display: none; }
body.hz-hide-panel aside#panel, body.hz-hide-panel #pathq { display: none; }
body.hz-dim #overlay .sym:not(.hz-on), body.hz-dim #overlay .tagbox:not(.hz-on),
body.hz-dim #overlay .pipe-line:not(.hz-on), body.hz-dim #graphsvg .gnode:not(.hz-on),
body.hz-dim #graphsvg .gedge:not(.hz-on), body.hz-dim #graphsvg .glabel { opacity: var(--hl-dim); }
.hz-path.sym, .hz-path.gnode { stroke: var(--hl-path) !important; stroke-width: 3.5; }
.hz-path.pipe-line, .hz-path.gedge { stroke: var(--hl-path) !important; stroke-width: 5; stroke-opacity: 1; }
.hz-est { stroke-dasharray: 9 6 !important; }
.hz-cause.sym, .hz-cause.gnode, .hz-cause.tagbox { stroke: var(--hl-cause) !important; stroke-width: 4; fill: rgba(220,38,38,.30) !important; }
.hz-sg.sym, .hz-sg.gnode, .hz-sg.tagbox { stroke: var(--hl-safeguard) !important; stroke-width: 2.5; }
.hz-ring { fill: none; stroke: var(--hl-safeguard); stroke-width: 2; pointer-events: none; }
.hz-badge rect { fill: var(--hl-safeguard); }
.hz-badge text { fill: #fff; font-size: 11px; font-family: "%(font)s", sans-serif; }
.hz-badge.weak rect { fill: #fff; stroke: var(--hl-safeguard); }
.hz-badge.weak text { fill: var(--hl-safeguard); }
.hz-legend { position: absolute; left: 50%%; bottom: 16px; transform: translateX(-50%%); background: var(--card);
  border: 1px solid var(--line); border-radius: 999px; padding: 4px 14px; font-size: 12px; color: var(--ink-2);
  box-shadow: 0 2px 10px rgba(0,0,0,.06); display: none; white-space: normal; max-width: 92%%; text-align: center; }
body.hz-dim .hz-legend { display: block; }
.hz-legend i { display: inline-block; width: 16px; height: 0; border-top: 3px solid; vertical-align: middle; margin: 0 4px 0 10px; }
""" % {"root": root, "ui": COLORS["ui"], "dim": HL_DIM, "font": FONT_FAMILY}


def qss():
    """Qt 스타일시트. 위계는 글자 크기·굵기, 버튼·탭·칩은 알약 모양."""
    k = dict(COLORS)
    k.update(font=FONT_FAMILY, md=FONT_SIZE["md"], sm=FONT_SIZE["sm"], xs=FONT_SIZE["xs"], lg=FONT_SIZE["lg"])
    return """
* { font-family: "%(font)s"; font-size: %(md)spx; color: %(ink)s; }
QMainWindow, QWidget#screen { background: %(bg)s; }
QWidget#header { background: %(card)s; border-bottom: 1px solid %(line)s; }
QLabel#appname { font-weight: 700; font-size: %(lg)spx; }
QLabel#where { color: %(ink)s; }
QLabel#logo { background: %(ui)s; border-radius: 12px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }
QPushButton#step { border: 0; border-radius: 14px; padding: 5px 14px; background: transparent; color: %(muted)s; }
QPushButton#step:checked { background: %(ui)s; color: #ffffff; font-weight: 700; }
QPushButton#step:hover:!checked { background: %(bg)s; }
QPushButton { border: 1px solid %(line-strong)s; border-radius: 14px; padding: 5px 14px; background: %(card)s; }
QPushButton:hover { border-color: %(ui)s; }
QPushButton:disabled { color: %(muted)s; background: %(bg)s; }
QPushButton#primary { background: %(ui)s; color: #ffffff; border-color: %(ui)s; font-weight: 700; }
QPushButton#primary:disabled { background: %(line-strong)s; border-color: %(line-strong)s; }
QLabel#chip { border-radius: 10px; padding: 3px 10px; background: %(bg)s; color: %(ink-2)s; font-size: %(sm)spx; }
QLabel#chip[state="passed"] { background: #dcfce7; color: %(ok)s; }
QLabel#chip[state="blocked"] { background: %(err-bg)s; color: %(err-ink)s; }
QLabel#chip[state="warn"] { background: %(warn-bg)s; color: %(warn-ink)s; }
QLabel#muted { color: %(muted)s; }
QLabel#title { font-size: %(lg)spx; font-weight: 700; }
QLabel#section { font-size: %(sm)spx; color: %(muted)s; font-weight: 700; }
QFrame#panel { background: %(card)s; border: 1px solid %(line)s; border-radius: 16px; }
QFrame#banner_warn { background: %(warn-bg)s; border: 1px solid %(warn-line)s; border-radius: 8px; }
QFrame#banner_err { background: %(err-bg)s; border: 1px solid %(err-line)s; border-radius: 8px; }
QFrame#banner_warn QLabel { color: %(warn-ink)s; }
QFrame#banner_err QLabel { color: %(err-ink)s; }
QFrame#ai_box { background: %(ai-hatch-a)s; border: 1px dashed %(ai-ink)s; border-radius: 12px; }
QFrame#human_box { background: #ffffff; border: 2px solid %(human-line)s; border-radius: 12px; }
QFrame#dropzone { background: %(card)s; border: 2px dashed %(line-strong)s; border-radius: 12px; }
QFrame#dropzone[hover="true"] { border-color: %(ui)s; background: %(ui-weak)s; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { border: 1px solid %(line-strong)s; border-radius: 8px; padding: 4px 8px; background: #ffffff; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: %(ui)s; }
QLineEdit:read-only { background: %(bg)s; }
QTableWidget, QTableView, QListWidget, QTreeWidget, QTextBrowser { background: #ffffff; border: 1px solid %(line)s; border-radius: 8px; gridline-color: %(line)s; }
QTableWidget::item, QListWidget::item { padding: 3px 6px; }
QTableWidget::item:selected, QListWidget::item:selected { background: %(ui-weak)s; color: %(ink)s; }
QHeaderView::section { background: %(bg)s; color: %(muted)s; border: 0; border-bottom: 1px solid %(line)s; padding: 4px 6px; font-size: %(sm)spx; font-weight: 700; }
QTabWidget::pane { border: 0; }
QTabBar::tab { border-radius: 12px; padding: 4px 12px; margin: 2px; background: transparent; color: %(muted)s; }
QTabBar::tab:selected { background: %(card)s; color: %(ink)s; font-weight: 700; border: 1px solid %(line)s; }
QStatusBar { background: %(card)s; border-top: 1px solid %(line)s; }
QStatusBar QLabel { font-size: %(sm)spx; }
QGroupBox { background: %(card)s; border: 1px solid %(line)s; border-radius: 12px; margin-top: 14px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: %(ink)s; font-weight: 700; }
QSplitter::handle { background: %(line)s; }
""" % k
