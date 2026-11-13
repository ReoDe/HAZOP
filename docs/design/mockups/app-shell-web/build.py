"""도면 중심 웹 화면 시안 생성. 근거: docs/design/app-shell-web.md.

하는 일
- resources/references/pid-samples의 SNP-M-101·102 SVG를 assets/로 복사하면서 바깥 링크(<a href="https://...">)를 지운다.
- 시안에 쓰는 Tabler 아이콘(3.51.0, MIT)을 원본 폴더에서 assets/icons/로 복사하고 HTML 본문에 넣는다.
- HTML 시안 6장과 index.html을 쓰고, Chrome headless로 PNG를 찍는다(1920×1080 = 1536×864 CSS 픽셀 × 125%, 1366×768 × 100%).

도면 위 표시 좌표는 SNP 표본 추출 결과(extraction.json)의 drawio 좌표에서 19를 뺀 SVG 좌표다
(coordinate_system.svg_alignment.offset [19, 19]). 분석 결과·구간 이름·대화 문장은 화면 표현을 보이기 위한 예시 값이다.

실행: <venv>/python.exe docs/design/mockups/app-shell-web/build.py [--no-png]
아이콘 원본 폴더는 환경변수 HAZOP_TABLER_OUTLINE으로 바꿀 수 있다. 없으면 resources/library/icons/tabler에 있는 것만 쓴다.
"""

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[3]
ASSETS = ROOT / "assets"
ICON_DIRS = [pathlib.Path(os.environ.get("HAZOP_TABLER_OUTLINE",
                                         r"D:\HAZOP-trials\2026-11-13-icons\pkg\package\icons\outline")),
             REPO / "resources" / "library" / "icons" / "tabler"]
SHEETS = {"snp-m-101": REPO / "resources/references/pid-samples/SNP-M-101_RCS-main-loop/01_SNP-M-101.svg",
          "snp-m-102": REPO / "resources/references/pid-samples/SNP-M-102_RCS-pressurizer/01_SNP-M-102.svg"}
CURRENT_SHOT = pathlib.Path(r"D:\HAZOP-trials\2026-11-13-first-milestone\run-1920-125\01-start-open.png")
VIEW_W, VIEW_H = 1617, 1132          # SNP SVG viewBox
OFF = 19                              # drawio 좌표 - 19 = SVG 좌표

_icons = {}


def ic(name, cls=""):
    """Tabler 아이콘 SVG를 본문용으로 바꾼다(크기 속성 제거, class="ic")."""
    if name not in _icons:
        for d in ICON_DIRS:
            p = d / ("%s.svg" % name)
            if p.exists():
                ASSETS.joinpath("icons").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, ASSETS / "icons" / p.name)
                raw = p.read_text(encoding="utf-8")
                break
        else:
            raise SystemExit("아이콘 없음: %s" % name)
        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
        raw = re.sub(r'\s(width|height|class)="[^"]*"', "", raw)
        _icons[name] = raw.replace("<svg", '<svg class="ic{cls}" aria-hidden="true"', 1)
    return _icons[name].replace("{cls}", (" " + cls) if cls else "")


def copy_sheets():
    for key, src in SHEETS.items():
        svg = src.read_text(encoding="utf-8")
        svg = re.sub(r"<a [^>]*>.*?</a>", "", svg, flags=re.S)       # drawio '텍스트 표시 문제' 안내 링크
        assert "https://" not in svg.replace("http://www.w3.org", ""), key
        (ASSETS / ("%s.svg" % key)).write_text(svg, encoding="utf-8")


def P(x, y):
    return "%g,%g" % (x - OFF, y - OFF)


def box(bbox, cls, pad=6):
    x, y, w, h = bbox
    return '<rect class="%s" x="%g" y="%g" width="%g" height="%g" rx="6"/>' % (cls, x - OFF - pad, y - OFF - pad, w + 2 * pad, h + 2 * pad)


# SNP-M-101 추출 결과에서 가져온 위치(drawio 좌표)
N = {"RC-RV01": [260, 430, 110, 280], "RC-SG01": [760, 120, 150, 340], "RC-PP01": [820, 640, 110, 135],
     "RC-V020": [745, 910, 30, 50], "RC-V010": [475, 880, 50, 50], "RC-TE101": [460, 400, 40, 40],
     "RC-PT101": [670, 400, 40, 40], "RC-FT101": [1020, 780, 40, 40], "RC-TE102": [850, 880, 40, 40],
     "RC-V001": [300, 360, 30, 50], "CONT-018": [440, 990, 120, 34], "RC-L001-T4": [479, 499, 2, 2],
     "RC-L001-T5": [579, 499, 2, 2], "RC-L001-T6": [689, 499, 2, 2]}
PATH_L003 = [(930, 748), (980, 748), (980, 840), (870, 840), (760, 840), (650, 840), (500, 840), (440, 840), (440, 584), (370, 584)]
PATH_L002 = [(857, 460), (857, 560), (780, 560), (780, 748), (820, 748)]
PATH_L001 = [(370, 500), (812, 500), (812, 460)]
STEPS = [(1, (945, 728)), (2, (980, 800)), (3, (870, 840)), (4, (760, 840)), (5, (650, 840)), (6, (500, 840)), (7, (370, 600))]


def sheet_svg(key, crop, overlay="", dim=False):
    x, y, w, h = crop
    return ('<svg class="sheet%s" viewBox="%g %g %g %g" preserveAspectRatio="xMidYMid meet" role="img" aria-label="도면 %s">'
            '<image class="sheet-img" href="assets/%s.svg" x="0" y="0" width="%d" height="%d"/>%s</svg>'
            % (" dim-others" if dim else "", x - OFF, y - OFF, w, h, key.upper(), key, VIEW_W, VIEW_H, overlay))


def polyline(pts, cls):
    return '<polyline class="%s" points="%s"/>' % (cls, " ".join(P(*p) for p in pts))


def path_overlay():
    o = polyline(PATH_L003, "ov-path-halo") + polyline(PATH_L003, "ov-path")
    o += box(N["RC-PP01"], "ov-start") + box(N["RC-RV01"], "ov-box")
    o += box(N["RC-FT101"], "ov-box", 4) + box(N["RC-TE102"], "ov-box", 4) + box(N["RC-V020"], "ov-box", 4)
    o += box(N["CONT-018"], "ov-warn", 5) + box(N["RC-V010"], "ov-warn", 4)
    for n, (x, y) in STEPS:
        o += '<g class="ov-step"><circle cx="%g" cy="%g" r="13"/><text x="%g" y="%g">%d</text></g>' % (x - OFF, y - OFF, x - OFF, y - OFF, n)
    return o


def seg_band(pts, color, label, at):
    o = '<polyline points="%s" fill="none" stroke="%s" stroke-width="16" stroke-opacity=".22" stroke-linejoin="round"/>' % (" ".join(P(*p) for p in pts), color)
    x, y = at
    w = 14 + 9 * len(label)
    o += '<g class="ov-seg-label"><rect x="%g" y="%g" width="%d" height="22" fill="%s"/><text x="%g" y="%g">%s</text></g>' % (x - OFF, y - OFF - 11, w, color, x - OFF + 7, y - OFF, label)
    return o


# ── 틀 부품 ───────────────────────────────────────────────────────────────

RAIL = [("drawings", "files", "도면 목록·등록 (1)"), ("nodes", "route", "구간 (2)"), ("results", "table", "분석 결과 (3)"),
        ("ie", "alert-octagon", "초기사건 (4)"), ("kg", "affiliate", "지식그래프 (5)")]


def rail(active="", tip=""):
    h = '<nav class="rail" aria-label="메뉴"><div class="logo">HZ</div>'
    for key, icon, label in RAIL:
        badge = '<span class="badge">12</span>' if key == "drawings" else ""
        t = '<span class="tip">%s</span>' % label if tip == key else ""
        h += '<button class="%s" title="%s" aria-label="%s">%s%s%s</button>' % ("on" if key == active else "", label, label, ic(icon), badge, t)
    h += '<div class="spacer"></div>'
    h += '<button title="AI 연결: 구독 · Haiku 5.5" aria-label="AI 연결">%s<span class="conn"></span></button>' % ic("plug-connected")
    h += '<button title="설정" aria-label="설정">%s</button></nav>' % ic("settings")
    return h


def topbar(sheet="SNP-M-101", title="REACTOR COOLANT SYSTEM - MAIN LOOP", extra=""):
    return ('<header class="topbar"><div class="crumb"><span class="proj">SNP 표본 프로젝트</span>%s'
            '<button class="sheet">%s %s</button><span class="title">%s</span></div>%s'
            '<div class="search">%s<span>구성요소·구간·명령 찾기</span><kbd>Ctrl P</kbd></div></header>'
            % (ic("chevron-right", "sm"), sheet, ic("chevron-down", "sm"), title, extra, ic("search", "sm")))


def toolbar(mode="move", zoom="110%"):
    def b(m, icon, label, key):
        return '<button class="%s" title="%s (%s)" aria-label="%s">%s</button>' % ("on" if mode == m else "", label, key, label, ic(icon))
    return ('<div class="float toolbar" role="toolbar" aria-label="도면 도구">%s%s<span class="sep"></span>'
            '<button title="축소 (-)" aria-label="축소">%s</button><span class="zoom">%s</span><button title="확대 (+)" aria-label="확대">%s</button>'
            '<button title="전체 맞춤 (0)" aria-label="전체 맞춤">%s</button><span class="sep"></span>'
            '<button title="층: 기호·배관·태그·구간" aria-label="층">%s</button></div>'
            % (b("move", "hand-move", "이동", "V"), b("pick", "marquee-2", "네모로 고르기", "S"),
               ic("zoom-out"), zoom, ic("zoom-in"), ic("arrows-maximize"), ic("stack-2")))


def chat(msgs, examples=True, placeholder="도면·문서·분석 결과에 대해 물어보세요", ctx="", conn_ok=True):
    ex = ""
    if examples:
        ex = ('<div class="examples"><span class="chip">%s 이 밸브는 어디로 이어져?</span><span class="chip">%s 격리 범위</span>'
              '<span class="chip">%s 확인할 곳</span></div>' % (ic("route", "sm"), ic("lock", "sm"), ic("alert-triangle", "sm")))
    foot = ('<div class="foot"><span class="dot"></span>구독 · Haiku 5.5 빠름 %s<span class="keys" style="margin-left:auto">Enter 보내기 · Shift+Enter 줄 바꿈</span></div>'
            % ic("chevron-down", "sm")) if conn_ok else ('<div class="foot"><span class="dot" style="background:var(--faint)"></span>AI 연결 없음 · 스크립트 기능만</div>')
    return ('<aside class="chat" aria-label="채팅"><div class="chat-h"><b>채팅</b><div class="acts">'
            '<button class="btn ghost icon sm" title="새 대화 (Ctrl+N)" aria-label="새 대화">%s</button>'
            '<button class="btn ghost icon sm" title="채팅 접기 (Ctrl+Alt+K)" aria-label="채팅 접기">%s</button></div></div>'
            '<div class="msgs">%s</div><div class="composer">%s<div class="box"><span class="ph">%s</span>%s<span class="send">%s</span></div>%s</div></aside>'
            % (ic("message-plus"), ic("layout-sidebar-right-collapse"), msgs, ex, placeholder, ctx, ic("send", "sm"), foot))


def page(title, body):
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><link rel="stylesheet" href="assets/app-shell.css"></head><body>%s</body></html>' % (title, body))


def shell(active, center, chat_html, tip=""):
    return '<div class="app">%s<main class="center">%s</main>%s</div>' % (rail(active, tip), center, chat_html)


def idchip(t):
    return '<span class="chip id">%s</span>' % t


# ── 채팅 내용 ─────────────────────────────────────────────────────────────

def path_answer(compact=False):
    steps = [("RC-PP01", "원자로냉각재펌프 · 출발", ""), ("RC-L003-T18", "분기 · RC-FT101 유량 전송", ""),
             ("RC-L003-T19", "분기 · RC-TE102 온도 측정", ""), ("RC-L003-T20", "합류 · CV-L020 충전(RC-V020 역지)", ""),
             ("RC-L003-T21", "분기 · RC-L011 → SNP-M-102", ""), ("RC-L003-T22", "분기 · CV-L001 유출", ic("alert-triangle", "sm")),
             ("RC-RV01", "원자로 용기 · 도착", "")]
    li = "".join('<li><span class="n">%d</span>%s<span class="muted">%s</span><span class="w">%s</span></li>' % (i + 1, idchip(t), d, w)
                 for i, (t, d, w) in enumerate(steps[:7 if not compact else 7]))
    return ('<div class="q">RC-PP01에서 RC-RV01까지 이어지는 배관 경로를 알려 줘</div>'
            '<div class="ans"><div class="src"><div class="lbl">%s 도면에서 확인</div>'
            '<p>RC-PP01 출구에서 저온관 <b>RC-L003</b>을 따라 RC-RV01 입구까지 7단계로 이어집니다. 사이에 분기 5곳이 있고 밸브는 없습니다.</p></div>'
            '<ol class="steps">%s</ol>'
            '<div class="warnline">%s<span>6단계 분기 CV-L001은 SNP-M-201로 이어지는데, 그 도면이 아직 추출되지 않아 끝을 확인하지 못했습니다.</span></div>'
            '<div class="src general"><div class="lbl">%s AI 일반 지식</div><p>저온관은 보통 펌프 출구에서 원자로 용기 입구 노즐까지를 말합니다.</p></div>'
            '<div class="sheets"><span class="chip accent">%s SNP-M-101 · 7단계</span><span class="chip">SNP-M-102 · 분기 1</span></div>'
            '<div class="acts-row"><button class="btn sm">%s 도면에서 다시 보기</button><button class="btn sm">%s 이 경로로 구간 만들기</button></div>'
            '<div class="meta">%s 도구 3회 · 4.8초 · 근거 ID 12개 확인</div></div>'
            % (ic("circle-check", "sm"), li, ic("alert-triangle", "sm"), ic("sparkles", "sm"), ic("map-pin", "sm"),
               ic("focus-centered", "sm"), ic("route", "sm"), ic("info-circle", "sm")))


# ── 시안 ──────────────────────────────────────────────────────────────────

CROP_MAIN = (150, 300, 1000, 760)


def page1():
    legend = ('<div class="float legend"><div><i style="border-color:var(--path)"></i>경로 (7단계)</div>'
              '<div><i style="border-color:var(--accent)"></i>출발</div><div><i style="border-color:var(--warn-line);border-top-style:dashed"></i>확인 못 한 곳</div>'
              '<div class="x"><span class="muted">채팅 답 #2</span><button class="btn ghost sm">%s 지우기</button></div></div>' % ic("x", "sm"))
    center = topbar() + '<div class="canvas">%s%s%s</div>' % (sheet_svg("snp-m-101", CROP_MAIN, path_overlay(), dim=True), legend, toolbar())
    return page("1 기본 화면", shell("", center, chat(path_answer())))


def page2():
    rows = [("snp-m-101", "SNP-M-101", "RCS 주 배관 · drawio", '<span class="chip warn">미확인 12</span>', True),
            ("snp-m-102", "SNP-M-102", "RCS 가압기 · drawio", '<span class="chip warn">미확인 3</span>', False)]
    lst = ""
    for key, dwg, sub, st, on in rows:
        lst += ('<div class="row%s"><span class="thumb" style="background-image:url(assets/%s.svg)"></span><div class="main"><b>%s</b><span>%s</span></div>%s'
                '<button class="btn ghost icon sm" aria-label="더 보기">%s</button></div>' % (" on" if on else "", key, dwg, sub, st, ic("dots-vertical")))
    for dwg, sub in (("SNP-M-201", "CVCS · PDF 1쪽"), ("SNP-M-301", "SIS · PDF 1쪽")):
        lst += ('<div class="row"><span class="thumb" style="display:grid;place-items:center;color:var(--muted)">%s</span><div class="main"><b>%s</b>'
                '<span>%s · 표제란 후보 <span class="chip ai" style="height:18px">%s · rev 0</span></span></div><span class="chip">추출 전</span>'
                '<button class="btn ghost icon sm" aria-label="빼기">%s</button></div>' % (ic("file-type-pdf"), dwg, sub, dwg, ic("x")))
    panel = ('<section class="panel" aria-label="도면 목록"><div class="panel-h"><h2>도면</h2><span class="chip">4장</span><div class="acts">'
             '<button class="btn ghost icon sm" title="닫기 (Esc)" aria-label="닫기">%s</button></div></div><div class="panel-b">'
             '<div class="drop">%s<div><b>PDF·drawio 파일을 끌어 놓기</b><br>또는 <u>파일 고르기</u> · 여러 개 가능</div></div>'
             '<div class="list">%s</div>'
             '<div class="card"><h3>새 도면 2장 추출</h3>'
             '<div class="kv"><div class="k"><b>AI 검토</b><span>못 읽은 기호·태그·끊긴 연결을 AI가 후보로 제안합니다. 후보는 사람이 확정합니다.</span></div><span class="switch on" role="switch" aria-checked="true"></span></div>'
             '<div class="kv"><div class="k"><b>호출 상한</b><span>예상 약 18회 (2장 · 쪽마다 9회 안팎)</span></div><span class="select">30회 %s</span></div>'
             '<div class="kv"><div class="k"><b>AI 연결</b><span>구독 · Haiku 5.5</span></div><span class="chip ok">%s 연결됨</span></div>'
             '<div style="display:flex;gap:8px;margin-top:8px"><button class="btn primary">%s 2장 추출 시작</button><button class="btn ghost">표제란 먼저 확정</button></div></div>'
             '<p class="sample">표제란 값은 후보(빗금)로 두고 사람이 확정합니다. 목록의 상태 칩을 누르면 미확인 목록이 열립니다.</p>'
             '</div></section>' % (ic("x"), ic("upload", "lg"), lst, ic("chevron-down", "sm"), ic("circle-check", "sm"), ic("player-play", "sm")))
    center = topbar() + '<div class="canvas">%s%s</div>%s' % (sheet_svg("snp-m-101", (0, 0, VIEW_W, VIEW_H)), toolbar(zoom="68%"), panel)
    msgs = ('<div class="q">새 도면 두 장 넣었어. 추출 전에 확인할 거 있어?</div><div class="ans"><div class="src"><div class="lbl">%s 앱 자료에서 확인</div>'
            '<p>SNP-M-201·301은 PDF라 기호 인식이 drawio보다 낮습니다. AI 검토를 켜 두면 못 읽은 기호 후보를 받을 수 있습니다. 예상 호출은 약 18회입니다.</p></div>'
            '<div class="acts-row"><button class="btn sm">%s 2장 추출 시작</button></div></div>' % (ic("circle-check", "sm"), ic("player-play", "sm")))
    return page("2 도면 목록과 등록", shell("drawings", center, chat(msgs)))


def page3():
    sel = [N[k] for k in ("RC-RV01", "RC-TE101", "RC-PT101", "RC-SG01")]
    o = seg_band(PATH_L003, "var(--seg1)", "S1", (995, 860)) + seg_band(PATH_L002, "var(--seg2)", "S2", (870, 600))
    o += polyline(PATH_L001, "ov-path-halo").replace("ov-path-halo", "ov-path-halo") + '<polyline class="ov-sel" style="fill:none;stroke-width:6" points="%s"/>' % " ".join(P(*p) for p in PATH_L001)
    for b in sel:
        o += box(b, "ov-sel", 5)
    o += '<rect class="ov-marquee" x="%g" y="%g" width="%g" height="%g"/>' % (240 - OFF, 380 - OFF, 480, 150)
    o += box(N["RC-V001"], "ov-out", 4)
    form = ('<div class="float" style="right:16px;top:16px;width:320px;padding:14px 16px;display:flex;flex-direction:column;gap:10px">'
            '<div style="display:flex;align-items:center;gap:8px"><span class="seg-dot" style="background:var(--seg4)"></span><b style="font-size:15px">새 구간 S4</b><span class="chip">구성요소 9</span>'
            '<button class="btn ghost icon sm" style="margin-left:auto" aria-label="닫기">%s</button></div>'
            '<div class="field"><label>이름</label><div class="input" style="color:var(--ink)">고온관 RC-L001: 원자로 용기 → 증기발생기</div></div>'
            '<div class="field"><label>설계 의도 <span class="chip ai" style="height:18px;margin-left:4px">AI 초안</span></label>'
            '<div class="textarea" style="background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px)">원자로 출구 냉각재를 정격 유량으로 증기발생기 입구까지 보낸다. 운전 압력 15.5 MPa, 온도 약 324 °C.</div></div>'
            '<div class="field"><label>경계</label><div style="display:flex;align-items:center;gap:6px">%s%s%s</div></div>'
            '<div style="display:flex;gap:8px"><button class="btn primary">%s 만들기 <kbd style="background:transparent;color:#fff;border-color:rgba(255,255,255,.5)">Enter</kbd></button>'
            '<button class="btn ghost">채팅으로 다듬기</button></div></div>'
            % (ic("x", "sm"), idchip("RC-RV01"), ic("arrow-right", "sm"), idchip("RC-SG01"), ic("check", "sm")))
    selbar = ('<div class="float selbar"><span class="count">9개 고름</span><span class="hint">끌기: 더하기 · Alt+끌기: 빼기 · 클릭: 넣고 빼기 · Esc: 비우기</span>'
              '<button class="btn sm">%s 채팅에 묻기</button><button class="btn sm primary">%s 구간 만들기</button></div>' % (ic("message-circle", "sm"), ic("route", "sm")))
    center = topbar(extra='<span class="chip accent" style="margin-left:8px">%s 고르기 모드</span>' % ic("marquee-2", "sm"))
    center += '<div class="canvas">%s%s%s%s</div>' % (sheet_svg("snp-m-101", (150, 90, 1000, 860), o), form, selbar, toolbar("pick", "96%"))
    msgs = ('<div class="q">대표 구간 3개 먼저 만들어 줘</div><div class="ans"><p>주요 장비에서 주요 장비까지를 기준으로 세 구간을 만들어 바로 적용했습니다. 이름과 설계 의도는 초안입니다.</p>'
            '<div class="applied"><div class="h">%s 적용함 · 묶음 B1</div>'
            '<div><span class="seg-dot" style="background:var(--seg1)"></span> <b>S1</b> 저온관 RC-L003: RC-PP01 → RC-RV01</div>'
            '<div><span class="seg-dot" style="background:var(--seg2)"></span> <b>S2</b> 교차관 RC-L002: RC-SG01 → RC-PP01</div>'
            '<div><span class="seg-dot" style="background:var(--seg3)"></span> <b>S3</b> 가압기 밀림관 [101 → 102]</div>'
            '<div class="acts-row"><button class="btn sm">%s 되돌리기</button><button class="btn sm">나머지도 나누기</button></div></div></div>'
            '<div class="q">고온관은 내가 직접 고를게<span class="sel-ref">%s 도면에서 고른 9개가 질문에 함께 갑니다</span></div>'
            '<div class="ans"><p>좋습니다. 고른 범위로 S4 초안을 채웠습니다. RC-V001은 배기 쪽이라 뺐습니다. 다시 넣으려면 눌러 주세요.</p></div>'
            % (ic("circle-check", "sm"), ic("arrow-back-up", "sm"), ic("marquee-2", "sm")))
    ctx = '<span class="ctx"><span class="chip accent">%s 9개</span></span>' % ic("marquee-2", "sm")
    return page("3 네모로 골라 구간 만들기", shell("nodes", center, chat(msgs, examples=False, placeholder="고른 것에 대해 묻거나 시키기", ctx=ctx)))


DEVS = ["유량 없음", "유량 많음", "유량 적음", "역류", "압력 높음", "압력 낮음", "온도 높음", "온도 낮음", "액위 높음", "액위 낮음", "오염"]
MATRIX = {
    "S1": ["3:4", "1:1", "2:3", "1:3a", "1:1", "2:1", "1:3", "1:1", "-", "-", "1:1"],
    "S2": ["2:3", "1:1", "2:1", "1:1", "1:1", "1:1", "1:1", "1:1", "-", "-", "1:1a"],
    "S3": ["1:3", "-", "1:1", "1:3", "2:5", "1:3", "1:1", "1:1", "2:3", "1:3", "-"],
    "S4": ["2:3a", "1:1a", "1:1a", "1:1a", "1:1a", "1:1a", "1:3a", "1:1a", "-", "-", "1:1a"],
    "S5": ["", "", "", "", "", "", "", "", "", "", ""],
}
NODES = [("S1", "seg1", "저온관 RC-L003", "SNP-M-101", "확정"), ("S2", "seg2", "교차관 RC-L002", "SNP-M-101", "확정"),
         ("S3", "seg3", "가압기 밀림관", "[101 → 102]", "검토 중"), ("S4", "seg4", "고온관 RC-L001", "SNP-M-101", "AI 초안"),
         ("S5", "seg5", "충전 유로 CV-L020", "[101 → 201]", "분석 전")]


def cell(v, sel=False):
    if v == "":
        return '<span class="cell na">·</span>'
    if v == "-":
        return '<span class="cell na" title="해당 없음: 액위가 없는 배관 구간">해당 없음</span>'
    ai = v.endswith("a")
    n, r = v.rstrip("a").split(":")
    band = {"1": "1", "2": "1", "3": "3", "4": "3", "5": "5"}[r]
    return '<span class="cell r%s%s%s" title="시나리오 %s개 · 최고 위험도 %s">%s<sup style="font-weight:400;opacity:.7;margin-left:2px">%s</sup></span>' % (band, " ai" if ai else "", " sel" if sel else "", n, r, r, n)


def page4():
    head = "".join("<th style='text-align:center;white-space:nowrap'>%s</th>" % d for d in DEVS)
    body = ""
    for key, seg, name, dw, st in NODES:
        stc = {"확정": "ok", "검토 중": "warn", "AI 초안": "ai", "분석 전": ""}[st]
        body += "<tr><th style='white-space:nowrap'><span class='seg-dot' style='background:var(--%s)'></span> <b>%s</b> %s<br><span class='muted' style='font-weight:400'>%s</span> <span class='chip %s' style='height:18px'>%s</span></th>" % (seg, key, name, dw, stc, st)
        body += "".join("<td class='c'>%s</td>" % cell(v, key == "S1" and i == 0) for i, v in enumerate(MATRIX[key])) + "</tr>"
    matrix = '<table class="grid matrix"><thead><tr><th>구간</th>%s</tr></thead><tbody>%s</tbody></table>' % (head, body)
    ws_rows = [
        ("RC-PP01 정지(전원 상실)", "노심 유량 감소, 원자로 출구 온도 상승", "RC-FT101 저유량 원자로 정지", "-", "4 · 2 → 3", "수용"),
        ("RC-V020 역지 밸브 고착 닫힘", "충전 유량 끊김(주 유량 영향 작음)", "CV 계통 유량 경보", "충전 유로 감시 보강 검토", "2 · 3 → 3", "수정"),
        ("RC-L003 배관 파단", "냉각재 상실", "안전주입(SNP-M-301)", "IE 후보로 넘김", "5 · 1 → 3", "AI 초안"),
    ]
    ws = ""
    for c_, e, s, r, risk, st in ws_rows:
        stc = {"수용": "ok", "수정": "accent", "AI 초안": "ai"}[st]
        ws += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td style='white-space:nowrap'><span class='cell r3' style='padding:0 6px'>%s</span></td><td><span class='chip %s'>%s</span></td></tr>" % (c_, e, s, r, risk, stc, st)
    sheet = ('<div style="display:flex;flex-direction:column;gap:10px;min-width:0">'
             '<div style="display:flex;align-items:center;gap:8px"><span class="seg-dot" style="background:var(--seg1)"></span><b style="font-size:15px">S1 저온관 · 유량 없음</b><span class="chip">시나리오 3</span>'
             '<span style="margin-left:auto;display:flex;gap:6px"><button class="btn sm">%s 도면에서 보기</button><button class="btn sm">%s Excel</button></span></div>'
             '<div class="card" style="padding:10px 12px"><div class="muted" style="font-size:12px">설계 의도</div>RC-PP01 출구 냉각재를 정격 유량으로 RC-RV01 입구까지 보낸다.</div>'
             '<table class="grid"><thead><tr><th>원인</th><th>결과</th><th>보호수단</th><th>권고</th><th>위험도 강도·빈도</th><th>상태</th></tr></thead><tbody>%s</tbody></table>'
             '<div class="card" style="display:flex;align-items:center;gap:8px;padding:10px 12px"><span class="muted">3행 선택:</span>'
             '<button class="btn sm">%s 수용</button><button class="btn sm">%s 수정</button><button class="btn sm">기각</button><button class="btn sm">보류</button>'
             '<span class="muted" style="margin-left:auto;font-size:12px">사유를 적어야 저장됩니다</span></div></div>'
             % (ic("focus-centered", "sm"), ic("file-spreadsheet", "sm"), ws, ic("check", "sm"), ic("pencil", "sm")))
    panel = ('<section class="panel wide" aria-label="분석 결과"><div class="panel-h"><h2>분석 결과</h2>'
             '<span class="chip">구간 5 · 편차 11</span><span class="chip warn">검토 안 한 칸 14</span>'
             '<div class="acts"><span class="select">모든 구간 %s</span><button class="btn sm">%s 분석 실행</button>'
             '<button class="btn ghost icon sm" title="닫기 (Esc)" aria-label="닫기">%s</button></div></div>'
             '<div class="panel-b">'
             '<div style="display:flex;flex-direction:column;gap:8px;min-width:0"><div style="overflow:auto">%s</div>'
             '<div class="sample">큰 숫자 = 그 칸의 최고 위험도(회색 1·2 수용, 노랑 3·4 조건부, 빨강 5 불허), 작은 숫자 = 시나리오 수. 점선 테두리 = 사람이 아직 보지 않은 AI 초안. 값은 예시입니다.</div></div>%s</div></section>'
             % (ic("chevron-down", "sm"), ic("player-play", "sm"), ic("x"), matrix, sheet))
    center = topbar() + '<div class="canvas">%s</div>%s' % (sheet_svg("snp-m-101", CROP_MAIN), panel)
    msgs = ('<div class="q">위험도 3 이상인데 아직 확정 안 한 칸만 알려 줘</div><div class="ans"><div class="src"><div class="lbl">%s 분석 결과에서 확인</div>'
            '<p>4칸입니다. S3 압력 높음(5)이 가장 높고, 나머지는 3입니다.</p></div>'
            '<div class="sheets"><span class="chip id">S3 · 압력 높음 · 5</span><span class="chip id">S3 · 유량 없음 · 3</span><span class="chip id">S3 · 역류 · 3</span><span class="chip id">S4 · 유량 없음 · 3</span></div>'
            '<div class="acts-row"><button class="btn sm">%s 표에서 표시</button></div></div>' % (ic("circle-check", "sm"), ic("table", "sm")))
    return page("4 분석 결과 패널", shell("results", center, chat(msgs, examples=False)))


def page5():
    pop = ('<div class="float pop" style="left:63%%;top:50%%"><h4>%s RC-V020</h4><div class="muted">역지 밸브 · SNP-M-101</div>'
           '<dl><dt>배관</dt><dd class="mono">CV-L020 → RC-L003</dd><dt>구간</dt><dd><span class="seg-dot" style="background:var(--seg5)"></span> S5 충전 유로</dd><dt>상태</dt><dd><span class="chip ok" style="height:20px">읽음 확인</span></dd></dl>'
           '<div class="acts"><button class="btn sm">%s 채팅에 묻기</button><button class="btn sm">%s 고치기</button></div></div>'
           % (ic("circle-dashed", "sm"), ic("message-circle", "sm"), ic("pencil", "sm")))
    o = path_overlay() + box(N["RC-V020"], "ov-sel", 6)
    center = topbar() + '<div class="canvas">%s%s%s</div>' % (sheet_svg("snp-m-101", (300, 520, 760, 550), o, dim=True), pop, toolbar(zoom="140%"))
    return page("5 기본 화면 1366", shell("", center, chat(path_answer())))


def page6():
    msgs = ('<div class="ans"><div class="card" style="display:flex;flex-direction:column;gap:8px">'
            '<b style="display:flex;align-items:center;gap:6px">%s 이 PC에는 AI 연결이 없습니다</b>'
            '<p class="muted" style="margin:0">채팅과 추출 AI 검토는 Claude 구독 연결이 있어야 씁니다. 도면 보기, 경로 찾기, 구간 만들기, 분석 결과 보기와 Excel 내보내기는 그대로 됩니다.</p>'
            '<div class="acts-row"><button class="btn sm primary">%s AI 연결 설정</button><button class="btn sm">연결 없이 쓰기</button></div></div>'
            '<div class="src general"><div class="lbl">연결 없이 쓰는 법</div><p>도면에서 구성요소를 누르면 속성과 이어진 곳이 나옵니다. 경로는 두 구성요소를 차례로 누르고 <kbd>P</kbd>를 누르면 스크립트가 찾습니다.</p></div></div>'
            % (ic("plug-connected"), ic("settings", "sm")))
    center = topbar() + '<div class="canvas">%s%s</div>' % (sheet_svg("snp-m-101", (0, 0, VIEW_W, VIEW_H)), toolbar(zoom="68%"))
    return page("6 AI 연결 없는 PC", shell("", center, chat(msgs, examples=False, placeholder="AI 연결이 없어 질문을 보낼 수 없습니다", conn_ok=False)))


PAGES = [
    ("1-home", page1, "기본 화면", "도면과 채팅. 경로 질문의 답 카드(근거·단계·경고·일반 지식 구분)와 도면 위 경로 표시.", 1536),
    ("2-drawings-panel", page2, "도면 목록·등록 패널", "왼쪽 메뉴의 '도면'. 파일 끌어 놓기, 표제란 후보, AI 검토 토글과 호출 상한.", 1536),
    ("3-make-node", page3, "네모로 골라 구간 만들기", "고르기 모드, 고른 것 막대, 새 구간 초안 카드, 채팅이 만든 S1~S3 묶음과 되돌리기.", 1536),
    ("4-results-panel", page4, "분석 결과 패널", "구간×편차 표와 고른 칸의 워크시트, 수용·수정·기각·보류.", 1536),
    ("5-home-narrow", page5, "1366 폭 기본 화면", "메뉴·채팅이 좁아진 배치. 구성요소를 누른 속성 말풍선.", 1366),
    ("6-no-ai", page6, "AI 연결 없는 PC", "구독이 없을 때 채팅 자리의 안내와 스크립트로 되는 일.", 1536),
]


def index():
    cur = '<img src="0-current-1920.png" alt="지금 화면">' if (ROOT / "0-current-1920.png").exists() else '<p class="muted">지금 화면 캡처 없음</p>'
    shots = ""
    for name, _f, title, desc, w in PAGES:
        png = "%s-%d.png" % (name, 1366 if w == 1366 else 1920)
        shots += '<figure><a href="%s.html"><img src="%s" alt="%s"></a><figcaption><b>%s</b>%s · <a href="%s.html">HTML 열기</a></figcaption></figure>' % (name, png, title, title, desc, name)
    body = ('<div class="gal"><div><h1>도면 중심 웹 화면 시안</h1><p>근거: <a href="../../app-shell-web.md">docs/design/app-shell-web.md</a>. '
            '도면은 SNP 표본 SVG(<code>resources/references/pid-samples</code>), 분석 결과·구간 이름·대화는 예시 값입니다. 네트워크 요청이 없습니다.</p></div>'
            '<section><h2>지금 → 새</h2><div class="cmp"><figure>%s<figcaption><b>지금 (② 추출, 1920×1080 125%%)</b>'
            '단계 레일 6칸, 왼쪽 목록, 도면 옆 연결점 목록이 늘 떠 있고, 오른쪽에 채팅·관련 항목 탭. 도면이 화면 폭의 약 40%%.</figcaption></figure>'
            '<figure><a href="1-home.html"><img src="1-home-1920.png" alt="새 기본 화면"></a><figcaption><b>새 기본 화면 (같은 크기)</b>'
            '얇은 메뉴 · 도면 · 채팅 세 칸만. 연결점·속성·관련 항목은 필요할 때 말풍선이나 패널로 엽니다. 도면이 화면 폭의 약 70%%.</figcaption></figure></div>'
            '<ul><li>단계 레일(①~⑥)과 단계별 왼쪽 목록 → 왼쪽 얇은 메뉴 5개(도면·구간·분석 결과·초기사건·지식그래프)와 여닫는 패널</li>'
            '<li>도면 연결점 목록·속성 칸·관련 항목 탭(늘 떠 있음) → 구성요소를 누르면 뜨는 말풍선, 채팅 답 카드</li>'
            '<li>모드 단추(분할·편집·경로 질의·층 토글 여러 개) → 도면 아래 도구 막대 하나(이동·네모로 고르기·확대·층)</li></ul></section>'
            '<section><h2>시안</h2><div class="shots">%s</div></section></div>' % (cur, shots))
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>도면 중심 웹 화면 시안</title>'
            '<link rel="stylesheet" href="assets/app-shell.css"></head><body class="gallery">%s</body></html>' % body)


def shoot(name, width):
    chrome = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    w, h, dsf = (1366, 768, 1) if width == 1366 else (1536, 864, 1.25)
    out = ROOT / ("%s-%d.png" % (name, 1366 if width == 1366 else 1920))
    with tempfile.TemporaryDirectory() as prof:
        subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                        "--user-data-dir=%s" % prof, "--window-size=%d,%d" % (w, h), "--force-device-scale-factor=%s" % dsf,
                        "--virtual-time-budget=3000", "--screenshot=%s" % out, (ROOT / ("%s.html" % name)).as_uri()],
                       check=True, capture_output=True, timeout=120)


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    copy_sheets()
    if CURRENT_SHOT.exists():
        shutil.copyfile(CURRENT_SHOT, ROOT / "0-current-1920.png")
    for name, fn, _t, _d, w in PAGES:
        (ROOT / ("%s.html" % name)).write_text(fn(), encoding="utf-8")
    (ROOT / "index.html").write_text(index(), encoding="utf-8")
    if "--no-png" not in sys.argv:
        for name, _f, _t, _d, w in PAGES:
            shoot(name, w)
    print("ok:", ", ".join(p[0] for p in PAGES), "icons:", len(_icons))
