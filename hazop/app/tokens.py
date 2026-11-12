"""디자인 토큰 한 곳 정의 (기획서/인터페이스.md §4.1·§4.2, 디자인/시안/README.md §3·§4.1).

Qt 스타일시트(qss)와 내장 웹뷰 CSS(web_css)가 모두 이 값을 읽는다. ② 뷰어에는 실행 시점에 CSS 변수로 주입한다.
독립 뷰어(hazop/viewer/template.html)의 :root는 같은 값을 직접 적고, scripts/check_design.py 색 비교가 web_css()의
:root와 같은지 검사한다(docs/units/2026-11-05-design-system D5). 여기 값을 바꾸면 템플릿 :root도 함께 바꾼다.
③ 지식그래프 HTML(hazop/kg/screen_template.html)은 생성할 때 kg_css_vars()로 같은 값을 넣는다.
글꼴: Pretendard는 배포본에 넣지 않음(2026-11-10 사용자 결정, §9). 맑은 고딕을 기본으로 쓴다.
"""

FONT_FAMILY = "Malgun Gothic"

COLORS = {
    # 명암비(WCAG 2.1 4.5:1·3:1)는 scripts/check_design.py CONTRAST_PAIRS로 검사한다(design-system D7)
    # UI: 강조색은 파랑 하나
    "ui": "#0a5fc2", "ui-weak": "#e2edfb", "ui-ink": "#0a4a96",
    "on-fill": "#ffffff",  # 파랑·진한 채움 위 흰 글자(주 버튼·선택 탭·사람 확정 배지·보호수단 배지)
    "bg": "#f4f5f7", "card": "#ffffff", "surface-2": "#f1f2f4", "line": "#d6d9de", "line-strong": "#7f8793",
    "muted": "#525b67", "ink": "#0f1419", "ink-2": "#2a313b",
    # 데이터: 노드 종류(밸브는 UI 파랑과 분리)
    "equipment": "#1d4ed8", "valve": "#0f766e", "instrument": "#0d97d6", "piping_element": "#6366f1",
    "unclassified": "#868e9d",
    "inline_component": "#1e3a8a",  # 배관 부품(2026-11-08 설비에서 나뉨): 설비 파랑의 진한 쪽이라 옛 도면 인상을 크게 바꾸지 않음
    # 데이터: 관계 종류
    "physical_connection": "#16a34a", "signal_connection": "#7c3aed", "measurement_connection": "#d67506",
    "unresolved": "#dc2626",
    # 시나리오 강조(§3.3 강조 규칙)
    "hl-cause": "#dc2626", "hl-path": "#ea580c", "hl-safeguard": "#c026d3",
    # 상태
    "ok": "#127238", "ok-bg": "#e2f3e8", "warn-bg": "#fdf0d2", "warn-ink": "#74430a", "warn-line": "#a8740d",
    "err-bg": "#fbe7e6", "err-ink": "#a8201a", "err-line": "#cc665e",  # err-line: 연결 칩 테두리 3:1(err-bg)
    # 위험도 〈표9〉 허용 구분 3단
    "risk-ok-bg": "#eef0f3", "risk-ok-ink": "#374151", "risk-ok-line": "#9ca3af",
    "risk-cond-bg": "#fde68a", "risk-cond-ink": "#78350f", "risk-cond-line": "#b36205",
    "risk-deny-bg": "#991b1b", "risk-deny-ink": "#ffffff", "risk-deny-line": "#991b1b",
    # 출처: AI·자동 판독 = 빗금(Qt는 옅은 회색 + 점선 테두리로 대신), 사람 확정 = 흰 바탕 진한 실선
    "ai-hatch-a": "#eef0f2", "ai-hatch-b": "#e3e6ea", "ai-ink": "#3a414b", "human-line": "#111827",
    "tag": "#111827",
    "human-edit": "#db2777",  # ② 도면 사람 수정 표시(뷰어 번짐·편집 미리보기)
    # ③ 지식그래프 (디자인/지식그래프화면.md §7). 별칭 토큰(=)은 같은 값을 풀어 적는다
    # 노드 종류(2026-11-08 옵시디언식): 채도 낮은 4계열(P&ID 회청·배관 구간 녹회·지식 회보라·문서 회색), 계열 안은 명도만 다름.
    # ②의 equipment·valve 등과 별도 키라 ② 색은 그대로다. 간선은 회색 하나(kg-edge 반투명, 강조 때 kg-edge-hi)
    "kg-equipment": "#3b5472", "kg-valve": "#4d6889", "kg-instrument": "#5e7ca1", "kg-piping_element": "#788da5",
    "kg-unclassified": "#8d939a", "kg-pipe_segment": "#54836b",
    "kg-inline_component": "#6a7f99",  # P&ID 회청 계열, 계장(#5e7ca1)과 배관 요소(#788da5) 사이 명도
    "kg-analysis_case": "#503c67", "kg-requirement": "#65507c", "kg-setpoint": "#796293", "kg-condition": "#88759f",
    "kg-document": "#575f6b", "kg-doc_chunk": "#757e8a",
    "kg-edge": "#9aa1ab", "kg-edge-hi": "#5b6470",
    "kg-flag": "#f59e0b", "kg-flag-ink": "#92400e", "kg-conflict": "#b91c1c", "kg-nosrc": "#b91c1c",
    "a1-start": "#111827", "a1-down": "#0072b2", "a1-up": "#d55e00", "a1-mixed": "#cc79a7", "a1-unknown": "#9ca3af",
    "a1-adj": "#009e73", "a1-na": "#6b7280", "a1-off": "#d1d5db",
    "comp-1": "#0072b2", "comp-2": "#e69f00", "comp-3": "#009e73", "comp-4": "#cc79a7", "comp-5": "#56b4e9",
    "comp-6": "#d55e00", "comp-other": "#9ca3af",
    "kg-canvas": "#fcfcfd",
    # 셸(디자인/시안/완성본 B안): 어두운 제목줄·단계 레일·상태줄
    "nav-bg": "#23282f", "nav-ink": "#e6e9ee", "nav-muted": "#aab2bd", "nav-active-bg": "#3b4452", "nav-active-ink": "#ffffff",
    "rail-check": "#4ade80", "nav-field": "#353c46",  # 레일 완료 ✓ 배지, 제목줄 명령 찾기 상자(UIUX U-01·U-05)
    # 토스트(U-07): 어두운 바탕 알림, 실행 취소 링크
    "toast-bg": "#1f2937", "toast-ink": "#f9fafb", "toast-link": "#93c5fd",
    # ④ 검토구간 색(구간 번호 S1~S5 순환, 꼬리표 글자 on-seg)
    "seg1": "#0b7285", "seg2": "#6d28d9", "seg3": "#b54708", "seg4": "#a61e4d", "seg5": "#3f6212", "on-seg": "#ffffff",
}
HL_DIM = 0.16  # 강조 중 나머지 오버레이 불투명도
CARD_SHADOW = "0 2px 10px rgba(0,0,0,.06)"  # 카드 그림자(장식). web_css() 범례·독립 뷰어 목록 페이지(hazop/viewer/build.py)
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
.selected.sym, .selected.tagbox { stroke: var(--ui) !important; fill: rgba(10,95,194,.12); }
.selected.pipe-line, .selected.gedge { stroke: var(--ui) !important; }
body.hz-embedded a.back, body.hz-embedded header .logo, body.hz-embedded header .app, body.hz-embedded header .sep { display: none; }
body.hz-hide-panel aside#panel, body.hz-hide-panel #pathq { display: none; }
body.hz-no-graph header .tabs, body.hz-no-graph #glegend, body.hz-no-graph #stage > #graphsvg { display: none; }
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
.hz-badge text { fill: %(onfill)s; font-size: 11px; font-family: "%(font)s", sans-serif; }
.hz-badge.weak rect { fill: %(card)s; stroke: var(--hl-safeguard); }
.hz-badge.weak text { fill: var(--hl-safeguard); }
.hz-legend { position: absolute; left: 16px; bottom: 64px; background: var(--card);
  border: 1px solid var(--line); border-radius: 12px; padding: 4px 12px; font-size: 12px; line-height: 18px; color: var(--ink-2);
  box-shadow: %(shadow)s; display: none; max-width: calc(100%% - 32px); max-height: 82px; overflow-y: auto; box-sizing: border-box; }
body.hz-dim .hz-legend { display: block; }
.hz-legend span { display: inline-block; white-space: nowrap; margin-right: 10px; }
.hz-legend i { display: inline-block; width: 16px; height: 0; border-top: 3px solid; vertical-align: middle; margin-right: 4px; }
body.hz-editing #viewport { cursor: crosshair; }
.hz-preview polyline { fill: none; stroke: var(--human-edit); stroke-width: 2.5; stroke-dasharray: 6 4; }
.hz-preview circle { fill: var(--human-edit); }
@media (max-width: 760px) { .hz-legend { left: 8px; bottom: 56px; max-width: calc(100%% - 16px); } }
""" % {"root": root, "ui": COLORS["ui"], "dim": HL_DIM, "font": FONT_FAMILY, "onfill": COLORS["on-fill"],
       "card": COLORS["card"], "shadow": CARD_SHADOW}


def qss():
    """Qt 스타일시트(디자인/시안/완성본 B안 고밀도 작업대): 모서리 4px, 사각 버튼, 촘촘한 여백, 어두운 제목줄·레일·상태줄."""
    k = dict(COLORS)
    k.update(font=FONT_FAMILY, md=FONT_SIZE["md"], sm=FONT_SIZE["sm"], xs=FONT_SIZE["xs"], lg=FONT_SIZE["lg"])
    return """
* { font-family: "%(font)s"; font-size: %(md)spx; color: %(ink)s; }
QMainWindow, QWidget#screen { background: %(bg)s; }
QWidget#header { background: %(nav-bg)s; }
QLabel#logo { color: %(nav-ink)s; font-weight: 700; padding-right: 8px; }
QLabel#where { color: %(nav-ink)s; }
QLabel#reviewer { color: %(nav-muted)s; font-size: %(sm)spx; }
QMenuBar#titlemenu { background: transparent; border: 0; }
QMenuBar#titlemenu::item { color: %(nav-ink)s; background: transparent; padding: 3px 8px; border-radius: 3px; }
QMenuBar#titlemenu::item:selected, QMenuBar#titlemenu::item:pressed { background: %(nav-active-bg)s; color: %(nav-active-ink)s; }
QMenu { background: %(card)s; border: 1px solid %(line-strong)s; }
QMenu::item { padding: 4px 20px; }
QMenu::item:selected { background: %(ui-weak)s; color: %(ink)s; }
QWidget#rail { background: %(nav-bg)s; }
QPushButton#step { border: 0; border-left: 2px solid transparent; border-radius: 4px; padding: 5px 0; margin: 0;
  background: transparent; color: %(nav-muted)s; font-size: %(xs)spx; }
QPushButton#step:hover { background: %(nav-active-bg)s; }
QPushButton#step[state="done"] { color: %(nav-ink)s; }
QPushButton#step[state="now"] { background: %(nav-active-bg)s; color: %(nav-active-ink)s; border-left-color: %(ui)s; font-weight: 700; }
QTreeWidget#explorer { background: %(surface-2)s; border: 0; border-right: 1px solid %(line)s; border-radius: 0; font-size: %(sm)spx; }
QTreeWidget#explorer::item { padding: 2px 4px; }
QTreeWidget#explorer::item:selected { background: %(ui-weak)s; color: %(ui-ink)s; }
QPushButton { border: 1px solid %(line-strong)s; border-radius: 4px; padding: 3px 10px; background: %(card)s; }
QPushButton:hover { border-color: %(ui)s; }
QPushButton:disabled { color: %(muted)s; background: %(bg)s; border-color: %(line)s; }
QPushButton#primary { background: %(ui)s; color: %(on-fill)s; border-color: %(ui)s; font-weight: 700; }
QPushButton#tool:checked { background: %(ui-weak)s; border-color: %(ui)s; color: %(ui-ink)s; font-weight: 700; }
QPushButton#primary:disabled { background: %(line)s; border-color: %(line)s; color: %(muted)s; }
QLabel#chip { border-radius: 3px; padding: 2px 8px; background: %(bg)s; color: %(ink-2)s; font-size: %(sm)spx; }
QLabel#chip[state="passed"] { background: %(ok-bg)s; color: %(ok)s; }
QLabel#chip[state="blocked"] { background: %(err-bg)s; color: %(err-ink)s; }
QLabel#chip[state="warn"] { background: %(warn-bg)s; color: %(warn-ink)s; }
QLabel#chip[state="ai"] { background: %(ai-hatch-a)s; color: %(ai-ink)s; border: 1px dashed %(ai-ink)s; }
QLabel#chip[state="human"] { background: %(human-line)s; color: %(on-fill)s; }
QLabel#muted { color: %(muted)s; }
QLabel#title { font-size: %(lg)spx; font-weight: 700; }
QLabel#section { font-size: %(sm)spx; color: %(muted)s; font-weight: 700; }
QFrame#panel { background: %(card)s; border: 1px solid %(line)s; border-radius: 4px; }
QFrame#pickcard { background: %(ui-weak)s; border: 1px solid %(ui)s; border-radius: 4px; }
QFrame#banner_warn { background: %(warn-bg)s; border: 1px solid %(warn-line)s; border-radius: 4px; }
QFrame#banner_err { background: %(err-bg)s; border: 1px solid %(err-line)s; border-radius: 4px; }
QFrame#banner_warn QLabel { color: %(warn-ink)s; }
QFrame#banner_err QLabel { color: %(err-ink)s; }
QFrame#ai_box { background: %(ai-hatch-a)s; border: 1px dashed %(ai-ink)s; border-radius: 4px; }
QFrame#human_box { background: %(card)s; border: 2px solid %(human-line)s; border-radius: 4px; }
QFrame#dropzone { background: %(card)s; border: 2px dashed %(line-strong)s; border-radius: 4px; }
QFrame#dropzone[hover="true"] { border-color: %(ui)s; background: %(ui-weak)s; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { border: 1px solid %(line-strong)s; border-radius: 3px; padding: 3px 8px; background: %(card)s; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: %(ui)s; }
QLineEdit:read-only { background: %(bg)s; }
QTableWidget, QTableView, QListWidget, QTreeWidget, QTextBrowser { background: %(card)s; border: 1px solid %(line)s; border-radius: 4px; gridline-color: %(line)s; }
QTableWidget::item, QListWidget::item { padding: 2px 6px; }
QTableWidget::item:selected, QListWidget::item:selected { background: %(ui-weak)s; color: %(ink)s; }
QHeaderView::section { background: %(surface-2)s; color: %(muted)s; border: 0; border-bottom: 1px solid %(line)s; padding: 3px 6px; font-size: %(sm)spx; font-weight: 700; }
QTabWidget::pane { border: 0; }
QTabBar::tab { border-radius: 0; padding: 4px 12px; margin: 0; background: transparent; color: %(muted)s; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: %(ink)s; font-weight: 700; border-bottom-color: %(ui)s; }
QStatusBar { background: %(nav-bg)s; }
QStatusBar::item { border: 0; }
QStatusBar QLabel, QStatusBar QLabel#muted { color: %(nav-muted)s; font-size: %(sm)spx; }
QToolButton#conn_chip { font-size: %(sm)spx; border: 0; background: transparent; }  /* 모양은 conn_widgets가 그림 */
QGroupBox { background: %(card)s; border: 1px solid %(line)s; border-radius: 4px; margin-top: 12px; padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: %(ink)s; font-weight: 700; }
QSplitter::handle { background: %(line)s; }
QToolButton#step { border: 0; border-left: 2px solid transparent; border-radius: 4px; padding: 3px 0; margin: 0;
  background: transparent; color: %(nav-muted)s; font-size: %(xs)spx; }
QToolButton#step:hover { background: %(nav-active-bg)s; }
QToolButton#step[done="true"] { color: %(nav-ink)s; }
QToolButton#step[state="now"] { background: %(nav-active-bg)s; color: %(nav-active-ink)s; border-left-color: %(ui)s; font-weight: 700; }
QPushButton#cmdbox { background: %(nav-field)s; color: %(nav-muted)s; border: 1px solid %(nav-active-bg)s; border-radius: 4px;
  padding: 2px 10px; text-align: left; font-size: %(sm)spx; }
QPushButton#cmdbox:hover { border-color: %(nav-muted)s; color: %(nav-ink)s; }
QLabel#kbd_nav { color: %(nav-muted)s; border: 1px solid %(nav-active-bg)s; border-radius: 3px; padding: 0 4px; font-size: %(xs)spx; }
QLabel#kbd { color: %(toast-ink)s; border: 1px solid %(toast-link)s; border-radius: 3px; padding: 0 4px; font-size: %(xs)spx; }
QWidget#explorer_box { background: %(surface-2)s; border-right: 1px solid %(line)s; }
QLineEdit#explorer_filter { font-size: %(sm)spx; padding: 2px 6px; margin-right: 6px; }
QLabel#explorer_title { font-weight: 700; font-size: %(sm)spx; color: %(ink)s; padding: 0 2px; }
QPushButton#explorer_next { font-size: %(xs)spx; padding: 1px 8px; color: %(ui-ink)s; border-color: %(ui)s; }
QTreeWidget#explorer::item:selected { border-left: 2px solid %(ui)s; }
QFrame#related { background: %(card)s; border-left: 1px solid %(line)s; }
QLabel#rel_title { font-weight: 700; padding: 8px 10px; border-bottom: 1px solid %(line)s; }
QWidget#rel_body { background: %(card)s; }
QToolButton#rel_head { border: 0; background: transparent; font-weight: 700; padding: 4px 6px; text-align: left; }
QListWidget#rel_list { border: 0; background: %(card)s; font-size: %(sm)spx; }
QListWidget#rel_list::item { padding: 1px 10px; height: 20px; }
QListWidget#rel_list::item:hover { background: %(ui-weak)s; }
QFrame#toast { background: %(toast-bg)s; border-radius: 6px; }
QLabel#toast_text { color: %(toast-ink)s; }
QPushButton#toast_undo { background: transparent; border: 0; color: %(toast-link)s; font-weight: 700; padding: 0 4px; }
QPushButton#danger { color: %(err-ink)s; border-color: %(err-line)s; }
QPushButton#danger:hover { border-color: %(err-ink)s; background: %(err-bg)s; }
QProgressBar#thin { border: 0; border-radius: 2px; background: %(line)s; }
QProgressBar#thin::chunk { background: %(ui)s; border-radius: 2px; }
QWidget#tabrow { background: %(surface-2)s; border-bottom: 1px solid %(line)s; }
QTabBar#tabs::tab { padding: 5px 10px; max-width: 240px; }
QTabBar#tabs::tab:selected { background: %(card)s; }
QDialog#palette { background: %(card)s; border: 1px solid %(line-strong)s; border-radius: 6px; }
QListWidget#palette_list { border: 0; }
QListWidget#palette_list::item { padding: 3px 8px; }
QListWidget#palette_list::item:selected { background: %(ui-weak)s; color: %(ink)s; }
""" % k
