"""AI 연결(API·Claude 구독·고정 응답) 화면 시안 생성. 근거: design/ai-connection-screens.md.

B안 셸 CSS는 design/mockups/final/b-dense-workbench/5-summary-matrix.html의 <style>을 그대로 읽어 쓴다.
데이터(계정·사용률·경로·비용)는 모두 가상 예시다. 실행: python build.py → HTML 10개와 PNG(1366·1920).
"""

import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
BASE = ROOT.parent / "final" / "b-dense-workbench" / "5-summary-matrix.html"

EXTRA_CSS = """
.aic{display:inline-flex;align-items:center;gap:5px;padding:1px 8px;border-radius:3px;font-size:11.5px;font-weight:600;
 border:1px solid var(--line);background:var(--surface-2);color:var(--ink-2);white-space:nowrap;line-height:1.5;cursor:pointer}
.aic svg{width:13px;height:13px;flex-shrink:0}
.aic.ok{background:var(--ok-bg);color:var(--ok-ink);border-color:#9fcfb0}
.aic.warn{background:var(--warn-bg);color:var(--warn-ink);border:1.5px solid var(--warn-line)}
.aic.err{background:var(--err-bg);color:var(--err-ink);border:1.5px solid var(--err-line)}
.aic.test{background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px);color:var(--ai-ink);border:1px dashed var(--ai-line)}
.aic.focus{outline:2px solid var(--ui);outline-offset:1px}
.statusbar .aic{font-size:11px;padding:0 7px;line-height:1.45}
.scrim{position:fixed;inset:0;background:rgba(15,20,25,.38);display:flex;align-items:center;justify-content:center;z-index:5}
.dlg{background:var(--surface);border:1px solid var(--line-strong);border-radius:6px;box-shadow:0 12px 40px rgba(0,0,0,.28);display:flex;flex-direction:column;min-width:0;overflow:hidden}
.dlg-t{display:flex;align-items:center;padding:6px 10px;border-bottom:1px solid var(--line);font-weight:650;background:var(--surface-2)}
.dlg-t .x{margin-left:auto;color:var(--muted);font-weight:400}
.dlg-b{padding:12px;display:flex;flex-direction:column;gap:10px;min-height:0;flex:1;overflow:auto}
.dlg-f{display:flex;align-items:center;gap:8px;padding:8px 12px;border-top:1px solid var(--line)}
.dlg-f .msg{flex:1;color:var(--muted);font-size:var(--fs-sm)}
.set{width:760px;height:560px}
.set .dlg-b{padding:0;flex-direction:row;gap:0}
.mlist{width:220px;flex-shrink:0;border-right:1px solid var(--line);background:var(--surface-2);padding:8px;display:flex;flex-direction:column;gap:4px}
.mlist .lab{font-size:var(--fs-sm);color:var(--muted);padding:0 4px 2px}
.mi{border:1px solid transparent;border-radius:4px;padding:6px 8px;display:flex;flex-direction:column;gap:3px}
.mi b{font-weight:650}
.mi .st{display:flex;align-items:center;gap:5px;font-size:var(--fs-sm);color:var(--ink-2)}
.mi .st svg{width:13px;height:13px}
.mi.on{background:var(--ui-weak);border-color:var(--ui);box-shadow:inset 3px 0 0 var(--ui)}
.mi .use{font-weight:700;color:var(--ink)}
.mdet{flex:1;min-width:0;padding:12px 14px;display:flex;flex-direction:column;gap:10px;overflow:auto}
.mh{display:flex;align-items:center;gap:8px}
.mh h2{margin:0;font-size:14px}
.badge-use{background:var(--ink);color:var(--on-fill);font-size:10.5px;font-weight:700;padding:0 6px;border-radius:3px}
.cost{color:var(--ink-2)}
.card{border:1px solid var(--line);border-radius:4px;padding:8px 10px;display:flex;flex-direction:column;gap:6px;background:var(--surface)}
.card .top{display:flex;align-items:center;gap:8px}
.card .top .btn{margin-left:auto}
.grid2{display:grid;grid-template-columns:72px 1fr;gap:4px 10px;font-size:var(--fs)}
.grid2 .k{color:var(--muted)}
.grid2 .sm{font-size:var(--fs-sm);color:var(--muted)}
.frow{display:grid;grid-template-columns:72px 1fr;gap:8px;align-items:center}
.sel{border:1px solid var(--line-strong);border-radius:3px;padding:3px 8px;background:var(--surface);display:flex;justify-content:space-between}
.hint{font-size:var(--fs-sm);color:var(--muted);line-height:1.5}
.fix{border-radius:4px;padding:8px 10px;display:flex;flex-direction:column;gap:6px;font-size:var(--fs-sm);line-height:1.5}
.fix.warn{background:var(--warn-bg);border:1px solid var(--warn-line);color:var(--warn-ink)}
.fix.err{background:var(--err-bg);border:1px solid var(--err-line);color:var(--err-ink)}
.fix.info{background:var(--surface-2);border:1px solid var(--line);color:var(--ink-2)}
.fix.test{background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px);border:1px dashed var(--ai-line);color:var(--ai-ink)}
.fix .acts{display:flex;gap:6px;flex-wrap:wrap}
.fix .h{font-weight:700;display:flex;gap:6px;align-items:center}
.fix .h svg{width:14px;height:14px}
.u{text-decoration:underline}
.meter{height:6px;border-radius:3px;background:var(--line);overflow:hidden;width:120px;display:inline-block;vertical-align:middle;margin-right:6px}
.meter i{display:block;height:100%;background:var(--ink-2)}
.fold{border-top:1px solid var(--line);padding-top:8px;display:flex;flex-direction:column;gap:6px}
.fold .fh{font-weight:650}
.conf{width:460px}
.conf .kv2{display:grid;grid-template-columns:76px 1fr;gap:6px 10px}
.conf .kv2 .k{color:var(--muted)}
.conf .lead{font-weight:650;font-size:13.5px}
.big{font-weight:700}
.ora{color:var(--warn-ink);font-weight:600}
.pop{position:absolute;width:340px;background:var(--surface);border:1px solid var(--line-strong);border-radius:6px;box-shadow:0 8px 28px rgba(0,0,0,.25);padding:10px 12px;display:flex;flex-direction:column;gap:8px;z-index:6}
.pop h3{margin:0;font-size:13px}
.pop .acts{display:flex;gap:6px;justify-content:space-between}
.gal{overflow:auto!important;background:var(--bg);padding:20px 24px}
.gal h1{font-size:16px;margin:0 0 4px}
.gal h2{font-size:13.5px;margin:22px 0 8px}
.gal .lead{color:var(--muted);margin:0 0 8px}
.sbdemo{background:var(--nav-bg);color:var(--nav-muted);display:flex;align-items:center;gap:16px;padding:0 10px;height:24px;font-size:11.5px;border-radius:3px;white-space:nowrap;overflow:hidden}
.sbdemo .sb-r{margin-left:auto}
.ctab{border-collapse:collapse;background:var(--surface);border:1px solid var(--line)}
.ctab th,.ctab td{border-bottom:1px solid var(--line);padding:5px 10px;text-align:left;vertical-align:middle}
.ctab th{color:var(--muted);font-weight:600;font-size:var(--fs-sm);background:var(--surface-2)}
.row{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
.dlg.static{position:relative}
.matrix{border-collapse:collapse;width:100%}
.matrix th,.matrix td{border:1px solid var(--line);padding:4px 6px;font-size:var(--fs-sm);text-align:center;white-space:nowrap}
.matrix th{background:var(--surface-2);color:var(--muted);font-weight:600}
.matrix td.n{text-align:left;font-weight:650}
.c-ok{background:var(--ok-bg);color:var(--ok-ink)}
.c-prop{background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px);color:var(--ai-ink)}
.c-none{color:var(--muted);background:var(--surface)}
.c-run{background:var(--ui-weak);color:var(--ui-ink);font-weight:700}
.c-fail{background:var(--err-bg);color:var(--err-ink);font-weight:700}
.tagt{display:inline-block;font-size:10px;font-weight:700;border:1px dashed var(--ai-line);padding:0 3px;border-radius:2px;margin-left:3px;background:var(--surface)}
.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:nowrap}
.prog{display:flex;align-items:center;gap:8px;min-width:0;flex:1;color:var(--ink-2);font-size:var(--fs-sm)}
.prog .bar{width:120px;height:8px;background:var(--line);border-radius:4px;overflow:hidden;flex-shrink:0}
.prog .bar i{display:block;height:100%;background:var(--ui)}
.prog span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.band{display:flex;align-items:flex-start;gap:10px;padding:8px 12px;border-radius:4px;border:1px solid}
.band.warn{background:var(--warn-bg);border-color:var(--warn-line);color:var(--warn-ink)}
.band .tx{flex:1;min-width:0;line-height:1.5}
.band .acts{display:flex;gap:6px;flex-shrink:0;align-items:center}
.band svg{width:16px;height:16px;flex-shrink:0;margin-top:2px}
.ws{display:flex;flex-direction:column;gap:8px}
.src{font-size:var(--fs-sm);color:var(--muted)}
.xl{border-collapse:collapse;font-family:Calibri,'Malgun Gothic',sans-serif;font-size:12px;background:#fff}
.xl td,.xl th{border:1px solid #c8ccd2;padding:3px 6px;text-align:left}
.xl th{background:#e9edf3}
.xl td.k{font-weight:700;width:190px}
.xl td.red{color:#991b1b;font-weight:700}
.xl .hl{background:#fff7d6}
.idx a{color:var(--ui);text-decoration:underline}
.idx li{margin:4px 0}
"""

ICON = {
    "ok": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.5"/><path d="M5 8.2l2 2 4-4.4"/></svg>',
    "q": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6.5"/><path d="M6.2 6.3a1.9 1.9 0 1 1 2.6 1.8c-.6.3-.8.6-.8 1.3"/><circle cx="8" cy="11.6" r=".5" fill="currentColor"/></svg>',
    "warn": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1.8l6.6 11.7H1.4z" stroke-linejoin="round"/><path d="M8 6v3.6"/><circle cx="8" cy="11.6" r=".5" fill="currentColor"/></svg>',
    "clock": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6.5"/><path d="M8 4.2V8l2.6 1.6"/></svg>',
    "x": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.5"/><path d="M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8"/></svg>',
    "dl": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 2v8M4.8 7l3.2 3.2L11.2 7M2.5 13.5h11"/></svg>',
    "test": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M6 1.8h4M6.6 1.8v4.4L2.6 13a1 1 0 0 0 .9 1.3h9a1 1 0 0 0 .9-1.3L9.4 6.2V1.8"/><path d="M4.4 10h7.2"/></svg>',
    "busy": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="2.2 2"><circle cx="8" cy="8" r="6.5"/></svg>',
}


MORE_CSS = """
.aic.need{border:1.5px solid var(--line-strong)}
.c-lim{background:var(--warn-bg);color:var(--warn-ink);font-weight:700}
.mi .off{color:var(--muted)}
.note-top{font-size:var(--fs-sm);color:var(--ink-2);background:var(--ui-weak);border:1px solid var(--ui);border-radius:4px;padding:6px 10px}
.terms{width:520px}
.terms ul{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px;line-height:1.5}
.scrim2{position:fixed;inset:0;background:rgba(15,20,25,.25);display:flex;align-items:center;justify-content:center;z-index:7}
"""

# (아이콘, 칩 종류, 넓은 글자, 좁은 글자, 접근성 이름)
CHIPS = [
    ("ok", "ok", "구독 · Opus 5.5 · 연결됨", "구독 · Opus · 연결됨", "AI 연결: Claude 구독, 모델 Opus 5.5, 연결됨"),
    ("busy", "", "구독 · Opus 5.5 · 확인 중", "구독 · Opus · 확인 중", "AI 연결: Claude 구독, 모델 Opus 5.5, 확인 중"),
    ("clock", "warn", "구독 · Opus 5.5 · 한도 가까움 · 17:40 재설정", "구독 · Opus · 한도 가까움", "AI 연결: Claude 구독, 모델 Opus 5.5, 한도 가까움, 17시 40분 재설정"),
    ("clock", "warn need-w", "구독 · Opus 5.5 · 한도 도달 · 17:40 재설정", "구독 · Opus · 한도 · 17:40", "AI 연결: Claude 구독, 모델 Opus 5.5, 한도 도달, 17시 40분 재설정"),
    ("warn", "warn need-w", "구독 · Opus 5.5 · 로그인 필요", "구독 · Opus · 로그인 필요", "AI 연결: Claude 구독, 모델 Opus 5.5, 로그인 필요"),
    ("warn", "warn need-w", "구독 · Opus 5.5 · 다시 로그인 필요", "구독 · Opus · 재로그인", "AI 연결: Claude 구독, 모델 Opus 5.5, 로그인 기간 끝남"),
    ("warn", "warn need-w", "구독 · Opus 5.5 · 구독 계정 아님", "구독 · Opus · 구독 아님", "AI 연결: Claude 구독, 모델 Opus 5.5, 구독 계정이 아님, 요금이 나갈 수 있음"),
    ("dl", "warn need-w", "구독 · Opus 5.5 · 미설치", "구독 · Opus · 미설치", "AI 연결: Claude 구독, 모델 Opus 5.5, Claude Code 미설치"),
    ("dl", "warn need-w", "구독 · Opus 5.5 · 업데이트 필요", "구독 · Opus · 업데이트", "AI 연결: Claude 구독, 모델 Opus 5.5, Claude Code 업데이트 필요"),
    ("x", "err", "구독 · Opus 5.5 · 연결 못 함", "구독 · Opus · 연결 못 함", "AI 연결: Claude 구독, 모델 Opus 5.5, 서버에 연결하지 못함"),
    ("ok", "ok", "API 키 · Opus 5.5 · 연결됨", "API 키 · Opus · 연결됨", "AI 연결: API 키, 모델 Opus 5.5, 연결됨"),
    ("q", "", "API 키 · Opus 5.5 · 확인 안 함", "API 키 · Opus · 확인 안 함", "AI 연결: API 키, 모델 Opus 5.5, 확인 안 함"),
    ("q", "need", "API 키 · Opus 5.5 · 키 없음", "API 키 · Opus · 키 없음", "AI 연결: API 키, 모델 Opus 5.5, 키 없음"),
    ("x", "err", "API 키 · Opus 5.5 · 키 거부됨", "API 키 · Opus · 키 거부됨", "AI 연결: API 키, 모델 Opus 5.5, 키 거부됨"),
    ("test", "test", "시험 · 고정 응답", "시험 · 고정 응답", "AI 연결: 고정 응답 시험 방식, AI를 호출하지 않음"),
]


def chip(icon, kind, text, extra=""):
    kind = kind.replace("need-w", "")
    return '<span class="aic %s %s" role="button" tabindex="0">%s%s</span>' % (kind, extra, ICON[icon], text)


def css():
    t = BASE.read_text(encoding="utf-8")
    return t[t.find("<style>") + 7:t.find("</style>")] + EXTRA_CSS + MORE_CSS


def page(title, body, body_class=""):
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>%s</title><style>%s</style></head>'
            '<body class="%s">%s</body></html>' % (title, css(), body_class, body))


RAIL = [("1", "등록"), ("2", "추출"), ("3", "그래프"), ("4", "구간"), ("5", "결과"), ("6", "초기사건")]
COLS = ["유량 없음", "유량 많음", "유량 적음", "역류", "압력 높음", "압력 낮음"]
CELL = {"ok": '<td class="c-ok">승인 2</td>', "prop": '<td class="c-prop">제안 3</td>',
        "none": '<td class="c-none">분석 전</td>', "run": '<td class="c-run">분석 중</td>',
        "fail": '<td class="c-fail">✕ 실패</td>', "lim": '<td class="c-lim">◷ 한도로 멈춤</td>'}
DEFAULT_STATES = [("S1", ["ok", "ok", "prop", "prop", "ok", "prop"]), ("S2", ["prop"] * 6),
                  ("S3", ["prop", "prop", "prop", "prop", "none", "none"]), ("S4", ["none"] * 6), ("S5", ["none"] * 6)]
SAVE = '<span class="mono" style="font-size:11px;word-break:break-all">C:\\HAZOP\\프로젝트\\가상PWR\\results\\SNP-M-102.json</span>'
CLI_PATH = "C:\\Users\\사용자\\.local\\bin\\claude.exe"


def matrix(states):
    head = "<tr><th>구간</th>" + "".join("<th>%s</th>" % c for c in COLS) + "</tr>"
    rows = "".join('<tr><td class="n">%s</td>%s</tr>' % (n, "".join(CELL[c] for c in cells)) for n, cells in states)
    return '<table class="matrix">%s%s</table>' % (head, rows)


def shell(title, ai_chip, main, overlay="", msg="최근 저장 14:20 KST"):
    rail = "".join('<a class="rail-i%s" aria-label="%s"><b>%s</b><span>%s</span></a>'
                   % (" on" if n == "5" else "", t, n, t) for n, t in RAIL)
    explorer = ('<div class="ex-h">탐색기</div><ul class="tree"><li class="grp">검토구간 5</li>'
                '<li class="on">S1 가압기 살수 배관</li><li>S2 가압기 본체</li><li>S3 서지 배관</li>'
                '<li>S4 방출 밸브 계통</li><li>S5 방출 탱크</li><li class="grp">실행 기록</li><li>AI 분석 실행 3회</li></ul>')
    tabs = '<span class="tab on">요약 행렬</span><span class="tab">워크시트</span><span class="tab">권고 목록</span>'
    sb = ('<footer class="statusbar"><span>SNP-M-102</span><span>구간 5 · 칸 30</span>'
          '<span class="sb-r">%s</span>%s<span>Ctrl+P 명령 · ? 단축키</span></footer>' % (msg, ai_chip))
    body = ('<div class="app shell-b"><header class="titlebar"><b class="logo">HAZOP</b>'
            '<span class="menu">파일</span><span class="menu">편집</span><span class="menu">보기</span>'
            '<span class="menu">도움말</span><span class="crumb">가상 PWR 예시 / ⑤ 분석 결과</span>'
            '<span class="user">검토자 김OO</span></header><nav class="rail" aria-label="단계">%s</nav>'
            '<aside class="explorer">%s</aside><section class="work"><div class="tabs">%s</div>'
            '<main class="main">%s</main></section>%s</div>%s' % (rail, explorer, tabs, main, sb, overlay))
    return page(title, body)


def results_main(toolbar_extra="", band="", states=None):
    head = ('<div class="page-head"><div class="ph-txt"><h1>⑤ 분석 결과 · 구간 × 편차</h1>'
            '<div class="sub">AI 결과는 초안입니다. 사람이 승인한 항목만 확정입니다</div></div>'
            '<div class="acts"><button class="btn">Excel로 내보내기</button></div></div>')
    toolbar = ('<div class="toolbar"><button class="btn" title="Claude 구독 · Opus 5.5로 실행합니다">AI 분석 실행</button>'
               '<button class="btn">선택 구간만</button><button class="btn">실패 칸 다시</button>%s</div>' % toolbar_extra)
    grid = ('<div class="body" style="grid-template-columns:minmax(0,1fr)"><section class="panel"><div class="panel-h">'
            '요약 행렬</div><div class="panel-b">%s</div></section></div>' % matrix(states or DEFAULT_STATES))
    return head + toolbar + band + grid


SUB_DETAIL = """<div class="mh"><h2>Claude 구독</h2><span class="badge-use">사용 중</span></div>
<div class="cost">건별 요금이 없습니다. 쓴 만큼 구독 사용 한도에서 빠집니다.</div>
<div class="card"><div class="top">%(chip)s<span class="muted">14:02 확인</span><button class="btn sm">연결 확인(T)</button></div>
<div class="grid2"><span class="k">프로그램</span><span>claude 2.1.319 <span class="sm">· %(path)s</span></span>
<span class="k">계정</span><span>로그인됨 <span class="sm">· Max 20x 요금제</span></span>
<span class="k">사용량</span><span><span class="meter"><i style="width:38%%"></i></span>5시간 한도 38%% 사용 · 17:40 재설정 <span class="sm">(14:02 호출 기준)</span></span></div></div>
<div class="frow"><label>모델(M)</label><span class="sel" %(dis)s>Opus 5.5 · 한도 소모 큼<span>▾</span></span></div>
<div class="hint">구독 한도는 claude.ai와 Claude Code에서 쓰는 양과 함께 셉니다. 큰 분석을 돌리면 같은 시간대의 다른 작업이 먼저 한도에 닿을 수 있습니다.</div>
<div class="hint">Claude 구독은 소비자 약관을 따릅니다. claude.ai 개인정보 설정에서 '모델 개선'이 켜져 있으면 보낸 도면 정보가 학습에 쓰일 수 있습니다. <a class="u" style="color:var(--ui)">설정 확인 방법</a></div>"""


def sub_detail(dis=""):
    return SUB_DETAIL % {"chip": chip("ok", "ok", "연결됨"), "path": CLI_PATH, "dis": dis}


def mlist(active, viewing, states):
    names = [("sub", "Claude 구독"), ("api", "API 키")]
    items = ""
    for key, name in names:
        icon, text = states[key]
        use = ' · <span class="use">사용 중</span>' if key == active else ""
        items += ('<div class="mi%s" role="option" aria-label="%s, %s%s"><b>%s</b><span class="st">%s%s%s</span></div>'
                  % (" on" if key == viewing else "", name, text, ", 사용 중" if key == active else "", name,
                     ICON[icon], text, use))
    return ('<div class="mlist" role="listbox"><div class="lab">연결 방식(<span class="u">W</span>)</div>%s'
            '<div class="hint" style="margin-top:auto">고정 응답(시험)은 디버그 실행에서만 보입니다.</div></div>' % items)


def settings_dialog(viewing, detail, states, footer_btn, msg="", active="sub"):
    return ('<div class="scrim"><div class="dlg set" role="dialog" aria-label="AI 연결 설정"><div class="dlg-t">AI 연결 설정'
            '<span class="x">✕</span></div><div class="dlg-b">%s<div class="mdet">%s</div></div>'
            '<div class="dlg-f"><span class="msg">%s</span>%s<button class="btn">닫기</button></div></div></div>'
            % (mlist(active, viewing, states), detail, msg, footer_btn))


ST_OK = {"sub": ("ok", "연결됨"), "api": ("q", "확인 안 함")}
CHIP_OK = chip("ok", "ok", "구독 · Opus 5.5 · 연결됨")


def page1():
    return shell("AI 연결 설정 · 구독", CHIP_OK, results_main(),
                 settings_dialog("sub", sub_detail(), ST_OK, '<button class="btn" disabled>사용 중</button>', "연결 확인 성공."))


API_DETAIL = """<div class="mh"><h2>API 키</h2></div>
<div class="cost">호출마다 요금이 나갑니다. Anthropic Console에서 발급한 키가 필요합니다.</div>
<div class="card"><div class="top">%s<button class="btn sm primary">연결 시험(T)</button></div>
<div class="grid2"><span class="k">키</span><span>회사 워크스페이스 (…a1B2) <span class="sm">· 이 PC에 암호화 저장</span></span>
<span class="k">대상</span><span>Anthropic API api.anthropic.com <span class="sm">· 모델 claude-opus-5-5 · API 버전 2023-06-01</span></span>
<span class="k"></span><span class="sm">아직 연결 시험을 하지 않았습니다. 연결 시험을 누르세요(토큰 비용 없음).</span></div></div>
<div class="frow"><label>사용할 키(K)</label><span style="display:flex;gap:6px"><span class="sel" style="flex:1">회사 워크스페이스 (…a1B2 · 이 PC 저장)<span>▾</span></span><button class="btn sm">이름 변경(R)</button><button class="btn sm">삭제(D)…</button></span></div>
<div class="frow"><label>모델(M)</label><span class="sel">Opus 5.5 (기본, 품질 우선)<span>▾</span></span></div>
<div class="frow"><span></span><span class="hint">백만 토큰당 입력 $4.00 · 출력 $20.00. 검토구간 1개 분석에 약 $0.86(실측).</span></div>
<div class="fold"><span class="fh">▸ 새 키 추가</span><span class="hint">접혀 있음. 키가 하나도 없으면 펼쳐 둡니다.</span></div>"""


def page2():
    return shell("AI 연결 설정 · API 키", CHIP_OK, results_main(),
                 settings_dialog("api", API_DETAIL % chip("q", "", "확인 안 함"), ST_OK,
                                 '<button class="btn primary">이 방식으로 사용(U)</button>',
                                 "보기만 하는 중입니다. 지금 쓰는 방식은 Claude 구독입니다."))


def page3():
    lock = ('<div class="fix info"><span class="h">%s AI 분석이 돌고 있어 연결 방식과 모델을 바꿀 수 없습니다.</span>'
            '<span>실행이 끝나거나 실행을 취소한 뒤 바꾸세요.</span><span class="acts"><button class="btn sm">실행 취소</button></span></div>'
            % ICON["busy"])
    detail = lock + sub_detail('style="opacity:.55" aria-disabled="true"')
    prog = ('<div class="prog"><span class="bar"><i style="width:40%"></i></span><span>AI 4/10 호출 · S3 · 유량 분석 중 · '
            '2:41 경과 · 약 4:00 남음 · 구독 사용량 차감</span><button class="btn sm">취소</button></div>')
    states = DEFAULT_STATES[:2] + [("S3", ["run"] * 4 + ["none"] * 2)] + DEFAULT_STATES[3:]
    return shell("AI 연결 설정 · 실행 중", CHIP_OK, results_main(prog, states=states),
                 settings_dialog("sub", detail, ST_OK, '<button class="btn" disabled>사용 중</button>',
                                 "실행 중에는 모델 선택과 '이 방식으로 사용'을 쓸 수 없습니다."),
                 "● AI 분석 실행 중 · 4/10 호출")


def page4():
    terms = ('<div class="scrim"><div class="dlg terms" role="dialog" aria-label="Claude 구독으로 분석하기 전에"><div class="dlg-t">Claude 구독으로 분석하기 전에'
             '<span class="x">✕</span></div><div class="dlg-b"><div>이 PC에 설치하고 본인 계정으로 로그인한 Claude Code를 거쳐 본인 구독 사용량으로 AI 분석을 합니다.</div>'
             '<ul><li>본인 계정을 본인 PC에서 쓰는 경우만 해당합니다. 다른 사람의 계정이나 공용 계정으로 쓰지 마세요.</li>'
             '<li>Claude 구독은 소비자 약관을 따릅니다. claude.ai 개인정보 설정에서 &#39;모델 개선&#39;이 켜져 있으면 보낸 도면 정보가 학습에 쓰일 수 있습니다. '
             '보안 등급이 있는 자료를 분석하기 전에 그 설정을 확인하세요.</li>'
             '<li>앱은 로그인 정보를 읽거나 저장하지 않습니다. 로그인은 Claude Code에서 직접 합니다.</li></ul>'
             '<label><input type="checkbox"> 위 내용을 확인했습니다</label>'
             '<div class="hint">처음 한 번만 묻습니다. 확인하면 AI 분석 시작 창으로 넘어갑니다.</div></div>'
             '<div class="dlg-f"><span class="msg"></span><button class="btn primary" disabled>확인하고 계속(O)</button>'
             '<button class="btn">API 키로 분석…</button><button class="btn">취소</button></div></div></div>')
    return shell("구독 처음 사용", CHIP_OK, results_main(), terms)


def page10():
    detail = ('<div class="hint" style="background:var(--surface-2);border:1px solid var(--line);border-radius:4px;padding:6px 10px">'
              '이 배포본은 API 키로만 AI에 연결합니다.</div>' + API_DETAIL % chip("ok", "ok", "연결됨"))
    detail = detail.replace("아직 연결 시험을 하지 않았습니다. 연결 시험을 누르세요(토큰 비용 없음).", "마지막 시험 11-09 09:12 · 성공")
    dlg = ('<div class="scrim"><div class="dlg set" style="width:600px" role="dialog" aria-label="AI 연결 설정"><div class="dlg-t">AI 연결 설정'
           '<span class="x">✕</span></div><div class="dlg-b"><div class="mdet">%s</div></div>'
           '<div class="dlg-f"><span class="msg"></span><button class="btn">닫기</button></div></div></div>' % detail)
    return shell("배포본 AI 연결 설정", chip("ok", "ok", "API 키 · Opus 5.5 · 연결됨"), results_main(), dlg)


def page5():
    rows = "".join("<tr><td>%s</td><td>%s</td><td class=muted>%s</td></tr>" % (
        chip(i, k, w), chip(i, k, n), a)
        for i, k, w, n, a in CHIPS)
    sb_wide = ('<div class="sbdemo" style="width:1880px;max-width:100%%"><span>SNP-M-102</span><span>구간 5 · 칸 30</span>'
               '<span class="sb-r">최근 저장 14:20 KST</span>%s<span>Ctrl+P 명령 · ? 단축키</span></div>'
               % chip("clock", "warn", CHIPS[3][2]))
    sb_narrow = ('<div class="sbdemo" style="width:1318px;max-width:100%%"><span>SNP-M-102</span><span>구간 5 · 칸 30</span>'
                 '<span class="sb-r" style="overflow:hidden;text-overflow:ellipsis">AI 분석 멈춤(한도 도달): 4/10 호출 · 2:41 걸림 · 저장: C:\\…\\SNP-M-102.json</span>%s'
                 '<span>Ctrl+P 명령 · ? 단축키</span></div>' % chip("clock", "warn", CHIPS[3][3], "focus"))
    pop = ('<div class="pop" style="position:relative"><h3>AI 연결</h3><div class="grid2">%s</div>%s'
           '<div class="acts">%s</div></div>')
    kv = lambda rows: "".join('<span class="k">%s</span><span>%s</span>' % r for r in rows)
    btns = lambda *bs: "".join('<button class="btn sm%s">%s</button>' % (" primary" if b.startswith("연결 설정") else "", b) for b in bs)
    pop_ok = pop % (kv([("방식", "Claude 구독 <span class='sm'>(사용 중)</span>"), ("모델", "Opus 5.5"),
                        ("상태", chip("ok", "ok", "연결됨") + " <span class='sm'>14:02 확인</span>"),
                        ("사용량", "5시간 한도 38% · 17:40 재설정"), ("계정", "로그인됨 · Max 20x 요금제")]), "",
                    btns("다시 확인(R)", "연결 설정…(S)"))
    pop_lim = pop % (kv([("방식", "Claude 구독 <span class='sm'>(사용 중)</span>"), ("모델", "Opus 5.5"),
                         ("상태", chip("clock", "warn", "한도 도달")), ("사용량", "5시간 한도 도달 · <b>17:40 재설정</b>"),
                         ("멈춘 실행", "4/10 호출 · 남은 칸 18")]), "",
                     btns("다시 확인(R)", "API 키로 바꾸기…", "연결 설정…(S)"))
    pop_login = pop % (kv([("방식", "Claude 구독 <span class='sm'>(사용 중)</span>"), ("모델", "Opus 5.5"),
                           ("상태", chip("warn", "warn", "로그인 필요"))]),
                       '<div class="hint">터미널에서 claude auth login을 실행해 구독 계정으로 로그인한 뒤 다시 확인을 누르세요.</div>',
                       btns("터미널에서 로그인(L)", "다시 확인(R)", "연결 설정…(S)"))
    body = ('<h1>연결 칩(상태줄)</h1><p class="lead">아이콘 모양과 글자로 상태를 알립니다. 실행할 수 없는 상태는 테두리가 1.5px로 두껍습니다. '
            '시험 방식은 AI 초안과 같은 빗금 바탕입니다. 가상 예시.</p>'
            '<h2>상태별 글자</h2><table class="ctab"><tr><th>넓은 형식(들어가면)</th><th>좁은 형식(안 들어가면)</th>'
            '<th>UIA accessibleName</th></tr>%s</table>'
            '<h2>상태줄 안에서</h2><p class="lead">넓은 형식(1920)</p>%s<p class="lead" style="margin-top:8px">좁은 형식(1366). '
            '메시지 칸이 먼저 말줄임으로 줄고 칩은 줄지 않습니다. 파란 외곽선은 키보드 포커스.</p>%s'
            '<h2>칩 상세 창(Enter·클릭)</h2><div class="row">%s%s%s</div>'
            % (rows, sb_wide, sb_narrow, pop_ok, pop_lim, pop_login))
    return page("연결 칩", body, "gal")


def conf(lead, rows, start="시작(S)", note="", top=""):
    kv = "".join('<span class="k">%s</span><span>%s</span>' % r for r in rows)
    return ('<div class="dlg conf static" role="dialog" aria-label="AI 분석 시작"><div class="dlg-t">AI 분석 시작<span class="x">✕</span></div>'
            '<div class="dlg-b">%s<div class="lead">%s</div><div class="kv2">%s</div>%s</div>'
            '<div class="dlg-f"><span class="msg"></span><button class="btn primary">%s</button><button class="btn">취소</button></div></div>'
            % (top, lead, kv, note, start))


def page6():
    lead = "AI를 10회 호출해 30칸을 채웁니다."
    api = conf(lead, [
        ("연결", "API 키 · '회사 워크스페이스'(…a1B2) · Opus 5.5 <button class='btn sm ghost'>바꾸기…</button>"),
        ("예상 시간", "약 7분 (호출 하나 15~60초)"),
        ("예상 비용", "<span class='big'>약 $0.90</span> <span class='muted'>(이 모델 지난 호출 평균 $0.09)</span>"),
        ("저장 위치", SAVE)], note='<div class="hint">칸은 호출이 끝날 때마다 바로 화면에 채워지고 저장됩니다.</div>')
    sub = conf(lead, [
        ("연결", "Claude 구독 · Opus 5.5 <button class='btn sm ghost'>바꾸기…</button>"),
        ("예상 시간", "약 7분 (호출 하나 15~60초)"),
        ("비용", "<span class='big'>건별 요금 없음.</span> 구독 사용량에서 차감"),
        ("사용량", "<span class='meter'><i style='width:86%'></i></span>5시간 한도 86% 사용 · 17:40 재설정 <span class='muted'>(14:02 호출 기준)</span>"
                   "<br><span class='ora'>한도가 가까워 도중에 멈출 수 있습니다.</span>"),
        ("멈출 때", "한도에 닿으면 남은 호출을 멈추고 받은 칸은 저장합니다. 남은 칸은 재설정 뒤에 이어서 돌리거나 API 키로 돌릴 수 있습니다."),
        ("저장 위치", SAVE)])
    sub_unknown = conf(lead, [
        ("연결", "Claude 구독 · Sonnet 5.5 <button class='btn sm ghost'>바꾸기…</button>"),
        ("예상 시간", "약 7분 (호출 하나 15~60초)"),
        ("비용", "<span class='big'>건별 요금 없음.</span> 구독 사용량에서 차감"),
        ("사용량", "<span class='muted'>한도 정보가 없습니다. 첫 호출 뒤에 보입니다.</span>"),
        ("멈출 때", "한도에 닿으면 남은 호출을 멈추고 받은 칸은 저장합니다."),
        ("저장 위치", SAVE)])
    api_resume = conf("AI를 6회 호출해 남은 18칸을 채웁니다.", [
        ("연결", "API 키 · '회사 워크스페이스'(…a1B2) · Opus 5.5"),
        ("예상 시간", "약 4분 (호출 하나 15~60초)"),
        ("예상 비용", "<span class='big'>약 $0.54</span> <span class='muted'>(기록이 없어 기본 어림값 호출당 $0.09)</span>"),
        ("저장 위치", SAVE)],
        top='<div class="note-top">이번 남은 호출만 API 키로 돌립니다. 끝나면 Claude 구독으로 돌아갑니다.</div>')
    fixed = conf("AI를 호출하지 않습니다. 저장된 응답으로 30칸을 채웁니다.", [
        ("연결", "고정 응답(시험) · 응답 폴더 <span class='mono'>…\\시험응답\\SNP-M-102</span> <button class='btn sm ghost'>바꾸기…</button>"),
        ("예상 시간", "1분 안쪽"), ("비용", "없음"),
        ("맞는 응답", "30칸 중 28칸. 응답이 없는 2칸은 '분석 전'으로 둡니다."),
        ("저장 위치", '<span class="mono" style="font-size:11px">C:\\HAZOP\\…\\results\\SNP-M-102-시험.json</span>')],
        "시험 시작(S)", '<div class="fix test">시험 결과는 실제 결과와 따로 시험용 파일에 저장합니다.</div>')
    body = ('<h1>AI 실행 확인 대화상자</h1><p class="lead">호출이 2회 이상일 때 뜹니다. 칸 이름은 같고 비용 줄만 방식마다 다릅니다. '
            'Claude 구독에는 $를 보이지 않습니다. 가상 예시(구간 5 × 편차 6 = 30칸, 호출 10회).</p>'
            '<h2>API 키 · Claude 구독(한도 가까움)</h2><div class="row">%s%s</div>'
            '<h2>Claude 구독(한도 정보 없음) · 한도 도달 뒤 API 키로 이어서</h2><div class="row">%s%s</div>'
            '<h2>고정 응답(디버그 실행)</h2><div class="row">%s</div>' % (api, sub, sub_unknown, api_resume, fixed))
    return page("AI 실행 확인", body, "gal")


def page7():
    band = ('<div class="band warn" role="alert" aria-label="알림: 구독 사용 한도에 닿아 AI 분석을 멈춤">%s<span class="tx">'
            '<b>구독 사용 한도에 닿아 AI 분석을 멈췄습니다.</b> 호출 10회 중 4회의 결과(12칸)는 저장했습니다. '
            '남은 6회(18칸)는 17:40 재설정 뒤에 이어서 돌리거나 API 키로 돌릴 수 있습니다.</span><span class="acts">'
            '<button class="btn sm primary">남은 칸 이어서 실행(C)</button><button class="btn sm">API 키로 이어서 실행…</button>'
            '<button class="btn sm ghost">닫기</button></span></div>' % ICON["clock"])
    prog = '<div class="prog"><span class="bar"><i style="width:40%"></i></span><span>AI 4/10 호출 · 한도 도달로 멈춤 · 2:41 걸림</span></div>'
    states = [("S1", ["prop"] * 6), ("S2", ["prop"] * 6), ("S3", ["lim"] * 4 + ["none"] * 2),
              ("S4", ["none"] * 6), ("S5", ["none"] * 6)]
    toast = ('<div style="position:fixed;right:16px;bottom:34px;background:var(--toast-bg,#1f2937);color:#f9fafb;padding:8px 12px;'
             'border-radius:4px;font-size:12px;display:flex;gap:10px;align-items:center;box-shadow:0 6px 20px rgba(0,0,0,.3)">'
             '<span>(17:40 뒤 예시) 구독 한도가 재설정됐습니다. 남은 18칸을 이어서 실행할 수 있습니다.</span>'
             '<a style="color:#93c5fd;text-decoration:underline">이어서 실행</a></div>')
    return shell("⑤ 한도 도달", chip("clock", "warn", "구독 · Opus 5.5 · 한도 도달 · 17:40 재설정"),
                 results_main(prog, band, states), toast,
                 "AI 분석 멈춤(한도 도달): 4/10 호출 · 2:41 걸림 · 저장: C:\\…\\SNP-M-102.json")


def page8():
    hatch = 'background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px);border:1px dashed var(--ai-line);padding:6px 8px;border-radius:4px'
    detail = ('<section class="panel"><div class="panel-h">S3 · 압력 높음</div><div class="panel-b ws">'
              '<div class="src">AI 초안 · Sonnet 5.5(요청 Opus 5.5) · Claude 구독 · 11-09 14:20 KST</div>'
              '<div class="sub-h">원인</div><div style="%s">가압기 살수 밸브 PCV-444C 닫힘 고착(가상 예시)</div>'
              '<div class="sub-h">결과</div><div class="muted">가압기 압력 상승, 방출 밸브 개방 요구(가상)</div>'
              '<div class="actions"><button class="btn sm primary">승인</button><button class="btn sm">수정</button><button class="btn sm">기각</button></div></div></section>'
              % hatch)
    test_detail = ('<div class="fix test" style="margin-bottom:8px"><span class="h">%s 시험 결과를 보는 중입니다</span><span>고정 응답으로 채운 칸이며 실제 분석 결과가 아닙니다.</span>'
                   '<span class="acts"><button class="btn sm">실제 결과로 돌아가기</button></span></div>'
                   '<section class="panel"><div class="panel-h">S2 · 유량 없음</div><div class="panel-b ws">'
                   '<div class="src">시험 · 고정 응답 · 응답 파일 S2-유량.json · 11-09 13:05 KST</div></div></section>' % ICON["test"])
    xl = ('<table class="xl"><tr><td class="k" colspan=2 style="font-size:15px">HAZOP 분석 결과 (⑤ 구간 × 편차)</td></tr>'
          '<tr><td class="k">고지</td><td class="red">AI 결과는 초안이며 사람이 승인한 항목만 확정입니다. …</td></tr>'
          '<tr><td class="k">프로젝트</td><td>가상 PWR</td></tr><tr><td class="k">…</td><td>…</td></tr>'
          '<tr class="hl"><td class="k">AI 초안 생성</td><td>Opus 5.5 · 구독 39칸, Sonnet 5.5 · API 키 12칸</td></tr>'
          '<tr class="hl"><td class="k">AI 사용 요금(API 키 호출분)</td><td>$0.36</td></tr>'
          '<tr><td class="k">실패 칸</td><td>1</td></tr></table>')
    xl_test = ('<table class="xl"><tr><td class="k" colspan=2 style="font-size:15px">HAZOP 분석 결과 (⑤ 구간 × 편차)</td></tr>'
               '<tr><td class="k">고지</td><td class="red">AI 결과는 초안이며 사람이 승인한 항목만 확정입니다. …</td></tr>'
               '<tr class="hl"><td class="k"></td><td class="red">시험용 고정 응답으로 채운 결과입니다. 실제 검토 결과로 쓰지 마세요.</td></tr>'
               '<tr><td class="k">파일 이름</td><td>SNP-M-102-결과-시험.xlsx</td></tr></table>')
    ws = ('<table class="xl"><tr><th>구간</th><th>편차</th><th>원인</th><th>…</th><th>상태</th><th class="hl">AI 초안 생성</th></tr>'
          '<tr><td>S3</td><td>압력 높음</td><td>살수 밸브 닫힘 고착</td><td>…</td><td>제안</td><td class="hl">Sonnet 5.5(요청 Opus 5.5) · 구독 · 11-09 14:20</td></tr>'
          '<tr><td>S1</td><td>유량 없음</td><td>살수 펌프 정지</td><td>…</td><td>승인</td><td class="hl">Sonnet 5.5 · API 키 · 11-08 10:12</td></tr>'
          '<tr><td>S1</td><td>유량 없음</td><td>검토자가 더한 원인</td><td>…</td><td>승인</td><td class="hl"></td></tr></table>')
    body = ('<h1>결과 기록에 연결 방식 남기기</h1><p class="lead">⑤ 칸 상세에는 모델·방식·시각 한 줄, Excel에는 표지 요약과 워크시트 열을 남깁니다. '
            '노란 칸이 새로 더하는 곳입니다. 가상 예시.</p><h2>⑤ 칸 상세 · 시험용 파일을 열었을 때</h2><div class="row"><div style="width:420px">%s</div>'
            '<div style="width:420px">%s</div></div><h2>Excel 표지·요약(실제 결과 · 시험용 파일)</h2><div class="row">%s%s</div>'
            '<h2>Excel 워크시트(오른쪽 끝 열)</h2>%s' % (detail, test_detail, xl, xl_test, ws))
    return page("결과 기록", body, "gal")


def fixbox(kind, icon, head, text, acts):
    return ('<div class="fix %s" style="width:420px"><span class="h">%s %s</span><span>%s</span><span class="acts">%s</span></div>'
            % (kind, ICON[icon], head, text, "".join('<button class="btn sm">%s</button>' % a for a in acts)))


def page9():
    subs = [
        fixbox("warn", "dl", "Claude Code를 찾지 못했습니다", "이 PC에서 Claude Code를 찾지 못했습니다. 설치한 뒤 다시 확인을 누르세요. 다른 곳에 설치했다면 위치를 지정하세요.", ["설치 방법 보기", "위치 지정…", "다시 확인"]),
        fixbox("warn", "dl", "업데이트가 필요합니다", "Claude Code 버전이 낮습니다(v2.1.259 이상 필요). 터미널에서 claude update를 실행한 뒤 다시 확인을 누르세요.", ["터미널에서 업데이트", "다시 확인"]),
        fixbox("warn", "dl", "지원하지 않는 설치 방식입니다", "npm으로 설치한 Claude Code는 쓸 수 없습니다. 네이티브 설치본으로 바꾼 뒤 다시 확인을 누르세요.", ["설치 방법 보기", "다시 확인"]),
        fixbox("warn", "warn", "로그인이 필요합니다", "Claude Code에 로그인돼 있지 않습니다. 터미널에서 claude auth login을 실행해 구독 계정으로 로그인한 뒤 다시 확인을 누르세요.", ["터미널에서 로그인", "다시 확인"]),
        fixbox("warn", "warn", "다시 로그인해야 합니다", "Claude Code 로그인 기간이 끝났습니다. 터미널에서 claude auth login으로 다시 로그인한 뒤 다시 확인을 누르세요.", ["터미널에서 로그인", "다시 확인"]),
        fixbox("warn", "warn", "구독 계정이 아닙니다", "Claude Code가 구독이 아닌 계정(API 키나 Console)으로 로그인돼 있습니다. 이대로 쓰면 건마다 요금이 나갑니다. claude auth login으로 구독 계정에 다시 로그인하거나, 요금을 내고 쓰려면 API 키 방식을 고르세요.", ["로그인 방법 보기", "API 키로 바꾸기…", "다시 확인"]),
        fixbox("warn", "clock", "한도가 가까워졌습니다", "구독 사용 한도가 가까워졌습니다(86%, 17:40 재설정). 큰 분석은 도중에 멈출 수 있습니다.", []),
        fixbox("warn", "clock", "구독 사용 한도에 닿았습니다", "17:40에 다시 쓸 수 있습니다.", ["API 키로 바꾸기…", "다시 확인"]),
        fixbox("warn", "clock", "구독 사용 한도에 닿았습니다", "재설정 시각은 아직 알 수 없습니다.", ["API 키로 바꾸기…", "다시 확인"]),
        fixbox("err", "x", "서버에 연결하지 못했습니다", "Anthropic 서버에 연결하지 못했습니다. 인터넷 연결이나 회사 프록시 설정을 확인하세요.", ["다시 확인", "오류 내용 복사"]),
        fixbox("err", "x", "확인하다 오류가 났습니다", "Claude Code를 확인하는 중에 오류가 났습니다. 오류 내용을 복사해 담당자에게 보내 주세요.", ["오류 내용 복사", "로그 폴더 열기", "다시 확인"]),
    ]
    apis = [
        fixbox("info", "q", "API 키가 없습니다", "아래 새 키 추가에서 키를 넣으세요.", []),
        fixbox("err", "x", "키가 거부됐습니다", "(연결 시험이 돌려준 사유. 예: 워크스페이스 키가 아니거나 크레딧이 모자람. 다음 할 일을 함께 적습니다.)", ["연결 시험"]),
        fixbox("warn", "clock", "요청이 잠시 거절됐습니다", "짧은 시간에 요청이 많아 API가 잠시 거절했습니다. 1분쯤 뒤에 다시 시도하세요.", ["연결 시험"]),
    ]
    fixed = [
        fixbox("test", "test", "준비됨", "응답 28개를 찾았습니다. 지금 검토구간의 30칸 중 28칸에 맞습니다.", ["찾아보기…"]),
        fixbox("info", "q", "응답 폴더가 없습니다", "응답 폴더를 고르세요.", ["찾아보기…"]),
    ]
    body = ('<h1>상태별 안내</h1><p class="lead">무슨 일인지, 무엇을 하면 되는지 순서로 씁니다. 같은 띠를 설정 창 상태 칸 아래, '
            '칩 상세 창, 실행 전 안내에 씁니다. 가상 예시.</p>'
            '<h2>Claude 구독</h2><div class="row">%s</div><h2>API 키</h2><div class="row">%s</div>'
            '<h2>고정 응답(디버그 실행)</h2><div class="row">%s</div>' % ("".join(subs), "".join(apis), "".join(fixed)))
    return page("상태 안내", body, "gal")


PAGES = [
    ("1-settings-subscription", page1, "설정 창, Claude 구독 상세(연결됨, 사용량 앎)", False),
    ("2-settings-api-key", page2, "설정 창, API 키 상세(보기만 하는 중)", False),
    ("3-settings-running", page3, "설정 창, 실행 중 잠금 띠(모델 선택 비활성)", False),
    ("4-subscription-first-use", page4, "구독으로 처음 분석할 때의 이용 조건 창", False),
    ("5-connection-chip", page5, "상태줄 칩 상태별(넓은·좁은 형식), 칩 상세 창", (1060, 1020)),
    ("6-run-confirm", page6, "실행 확인 대화상자 API 키·구독·API 키로 이어서·고정 응답", (1300, 1300)),
    ("7-limit-reached", page7, "⑤ 화면 한도 도달 띠, 한도로 멈춤·분석 전 칸, 칩, 재설정 토스트", False),
    ("8-result-record", page8, "⑤ 칸 상세 출처 줄, 시험 결과 띠, Excel 표지·워크시트 열", (820, 820)),
    ("9-status-notice", page9, "상태별 해결 띠", (1000, 900)),
    ("10-bundle", page10, "배포본 설정 창(API 키만), 칩", False),
]


def index():
    items = "".join('<li><a href="%s.html">%s</a> · %s · PNG <a href="%s-1366.png">1366</a> · <a href="%s-1920.png">1920</a></li>'
                    % (n, n, d, n, n) for n, _f, d, _g in PAGES)
    body = ('<h1>AI 연결 화면 시안</h1><p class="lead">근거: design/ai-connection-screens.md, specs/ai-subscription.md. 데이터는 모두 가상 예시입니다.</p>'
            '<ul class="idx">%s</ul>' % items)
    return page("AI 연결 시안 목차", body, "gal")


def shoot(name, gallery):
    chrome = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    for w, h in ((1366, 768), (1920, 1080)):
        if gallery:
            h = gallery[0] if w == 1366 else gallery[1]
        out = ROOT / ("%s-%d.png" % (name, w))
        with tempfile.TemporaryDirectory() as prof:
            subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--user-data-dir=%s" % prof, "--window-size=%d,%d" % (w, h),
                            "--screenshot=%s" % out, (ROOT / ("%s.html" % name)).as_uri()],
                           check=True, capture_output=True, timeout=120)


if __name__ == "__main__":
    (ROOT / "index.html").write_text(index(), encoding="utf-8")
    for name, fn, _d, gallery in PAGES:
        (ROOT / ("%s.html" % name)).write_text(fn(), encoding="utf-8")
        shoot(name, gallery)
