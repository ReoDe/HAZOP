"""도면 중심 웹 화면 시안 생성. 근거: docs/design/app-shell-web.md.

하는 일
- resources/references/pid-samples의 SNP-M-101·102 SVG를 assets/로 복사하면서 바깥 링크(<a href="https://...">)를 지운다.
- 시안에 쓰는 Tabler 아이콘(3.51.0, MIT)을 원본 폴더에서 assets/icons/로 복사하고 HTML 본문에 넣는다.
- HTML 시안 8장과 index.html을 쓰고, Chrome headless로 PNG를 찍는다(1920×1080 = 1536×864 CSS 픽셀 × 125%, 1366×768 × 100%).

도면 위 표시 좌표는 SNP 표본 추출 결과(extraction.json)의 drawio 좌표에서 19를 뺀 SVG 좌표다
(coordinate_system.svg_alignment.offset [19, 19]). 분석 결과·구간 이름·대화 문장은 화면 표현을 보이기 위한 예시 값이다.

시안 7·8(정리된 보기)은 SNP-M-101 drawio를 hazop.extract.drawio로 읽어 다시 그린다. 읽은 값은 assets/snp-m-101-clean.json에 남기고,
엔진을 못 부르는 환경에서는 그 파일을 쓴다. 기호 그림은 시안용이고 HZ-DSN-05 §10.3의 기호 한 벌이 아니다.

실행: <venv>/python.exe docs/design/mockups/app-shell-web/build.py [--no-png] [--only 7-clean-view,8-clean-unknown]
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


# ── 정리된 보기(시안 7·8, HZ-DSN-05 §10) ─────────────────────────────────

CLEAN_JSON = ASSETS / "snp-m-101-clean.json"
DRAWIO_101 = REPO / "resources/references/pid-samples/SNP-M-101_RCS-main-loop/SNP-M-101_RCS-main-loop.drawio"


def tidy(data):
    """시안용 정돈(HZ-DSN-05 §10.11의 일부). 이어짐은 바꾸지 않는다.
    - 직각·한 줄: 배관 한 개 안에서 0 초과 6 단위 이하로 어긋난 이웃 점을 맞춘다. 끝점(연결점)의 값을 남기고 꺾임점을 옮긴다.
    - 설비(stretch)·펌프: 이어진 배관 끝을 모아 노즐·축(axis)으로 둔다. 그리기가 그 끝에 정확히 닿게 한다."""
    for pp in data["pipes"]:
        pts = pp["points"]
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            for k in (0, 1):
                d = abs(a[k] - b[k])
                if 0 < d <= 6:
                    if i + 1 == len(pts) - 1:      # b가 끝점이면 b의 값을 남긴다
                        a[k] = b[k]
                    else:
                        b[k] = a[k]
    for n in data["nodes"]:
        x, y, w, h = n["bbox"]
        ends = []
        for pp in data["pipes"]:
            for q in (pp["points"][0], pp["points"][-1]):
                if x - 0.6 <= q[0] <= x + w + 0.6 and y - 0.6 <= q[1] <= y + h + 0.6:
                    ends.append(q)
        n["ends"] = ends
    return data


def clean_data():
    """SNP-M-101 drawio 추출 결과에서 정리된 보기에 쓰는 값만 뽑는다(SVG 좌표). 엔진을 못 부르면 저장해 둔 JSON을 쓴다."""
    import json
    try:
        sys.path.insert(0, str(REPO))
        from hazop.extract import drawio
    except Exception:
        return tidy(json.loads(CLEAN_JSON.read_text(encoding="utf-8")))
    r = drawio.extract(str(DRAWIO_101))
    nodes, pipes = [], []
    for n in r["nodes"]:
        g = n["geometry"]
        st = dict(kv.split("=", 1) for kv in (n.get("style") or "").split(";") if "=" in kv)
        rot = {"south": 90, "west": 180, "north": 270}.get(st.get("direction"), 0) + float(st.get("rotation", 0) or 0)
        lb = (n.get("label_location") or {}).get("bbox")
        nodes.append({"id": n["local_id"], "kind": n["kind"], "tag": n["tag"], "text": n.get("label_text"),
                      "bbox": [g["x"] - OFF, g["y"] - OFF, g["width"], g["height"]], "rot": rot % 360,
                      "flip_h": st.get("flipH") == "1", "label": [lb[0] - OFF, lb[1] - OFF, lb[2], lb[3]] if lb else None})
    for e in r["relations"]:
        src = [ep["point"] for ep in e["endpoints"] if ep["end"] == "source"]
        dst = [ep["point"] for ep in e["endpoints"] if ep["end"] == "target"]
        pts = [[x - OFF, y - OFF] for x, y in src + (e.get("waypoints") or []) + dst]
        pipes.append({"id": e["local_id"], "line_type": e.get("line_type"), "line_no": e.get("line_no"),
                      "flow": bool(e.get("flow_direction")), "points": pts})
    data = {"source": "hazop.extract.drawio.extract(%s)" % DRAWIO_101.name, "nodes": nodes, "pipes": pipes}
    CLEAN_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return tidy(data)


SW = 'vector-effect="non-scaling-stroke"'


def _valve(n, cls):
    """밸브 그림 좌표: 가로 40 × 세로 20, 연결점 (0,10)·(40,10). 회전한 뒤 bbox에 가로세로 비를 지켜 맞춘다."""
    x, y, w, h = n["bbox"]
    cx, cy, rot = x + w / 2, y + h / 2, n["rot"]
    bw, bh = (h, w) if rot in (90, 270) else (w, h)
    k = min(bw / 40.0, bh / 20.0)
    body = '<path d="M0 0 L40 20 V0 L0 20 Z" %s/>' % SW
    if n["kind"] == "check_valve":
        body = '<path d="M0 0 L20 10 L0 20 Z" %s/><path class="fill" d="M40 0 L20 10 L40 20 Z" %s/>' % (SW, SW)
    if n["kind"] == "motor_operated_valve":
        body += ('<line x1="20" y1="10" x2="20" y2="-4" %s/><circle cx="20" cy="-10" r="6" %s/>'
                 '<text class="ct-in" x="20" y="-10" style="font-size:7px">M</text>' % (SW, SW))
    t = "translate(%g %g) rotate(%g) scale(%g) translate(-20 -10)" % (cx, cy, rot, k)
    return '<g class="%s" transform="%s">%s</g>' % (cls, t, body)


def _sym(n, cls):
    """kind별 시안용 기호(V2 기호 한 벌이 아니다)."""
    x, y, w, h = n["bbox"]
    cx, cy = x + w / 2, y + h / 2
    kind = n["kind"]
    if kind in ("reactor_vessel", "steam_generator"):
        hh = min(32.0, h / 4)
        s = ('<path d="M%g %g A%g %g 0 0 1 %g %g V%g A%g %g 0 0 1 %g %g Z" %s/>'
             % (x, y + hh, w / 2, hh, x + w, y + hh, y + h - hh, w / 2, hh, x, y + h - hh, SW))
        for ex, ey in n.get("ends", []):          # 노즐: 머리 곡선에서 배관 끝까지 곧게(§10.11 규칙 6)
            if abs(ey - y) < 0.7 or abs(ey - (y + h)) < 0.7:
                t = ((ex - cx) / (w / 2)) ** 2
                oy = hh * (1 - max(0.0, 1 - t) ** 0.5)
                yy = y + oy if abs(ey - y) < 0.7 else y + h - oy
                if abs(yy - ey) > 0.2:
                    s += '<line x1="%g" y1="%g" x2="%g" y2="%g" %s/>' % (ex, yy, ex, ey, SW)
        if kind == "steam_generator":
            s += ('<path d="M%g %g V%g A%g %g 0 0 0 %g %g V%g" fill="none" %s/>'
                  % (cx - w * .18, y + h * .35, y + h * .78, w * .18, w * .18, cx + w * .18, y + h * .78, y + h * .35, SW))
            s += '<line x1="%g" y1="%g" x2="%g" y2="%g" %s/>' % (x, y + h * .3, x + w, y + h * .3, SW)
        else:
            s += '<line x1="%g" y1="%g" x2="%g" y2="%g" %s/>' % (x + 6, y + h * .22, x + w - 6, y + h * .22, SW)
        return '<g class="%s">%s</g>' % (cls, s)
    if kind == "pump":
        side = [q for q in n.get("ends", []) if abs(q[0] - x) < 0.7 or abs(q[0] - (x + w)) < 0.7]
        ay = side[0][1] if side else cy                     # 배관 축(들고 나는 배관의 y)
        r = min(w * .36, (y + h - ay) * .62, 40.0)
        s = '<circle cx="%g" cy="%g" r="%g" %s/>' % (cx, ay, r, SW)
        s += '<line x1="%g" y1="%g" x2="%g" y2="%g" %s/>' % (x, ay, cx - r, ay, SW)           # 흡입 연결점까지
        s += '<line x1="%g" y1="%g" x2="%g" y2="%g" %s/>' % (cx + r, ay, x + w, ay, SW)       # 토출 연결점까지
        s += '<path d="M%g %g L%g %g H%g L%g %g" fill="none" %s/>' % (cx - r * .7, ay + r * .7, cx - r * .95, y + h, cx + r * .95, cx + r * .7, ay + r * .7, SW)
        return '<g class="%s">%s</g>' % (cls, s)
    if kind in ("transmitter", "indicator", "temperature_element"):
        r = min(w, h) / 2
        m = re.match(r"(?:[A-Z]+-)?([A-Z]+)(\d+)$", n["tag"] or "")
        a, b = (m.group(1), m.group(2)) if m else ("", "")
        s = '<circle cx="%g" cy="%g" r="%g" %s/>' % (cx, cy, r, SW)
        s += '<line x1="%g" y1="%g" x2="%g" y2="%g" %s/>' % (cx - r, cy, cx + r, cy, SW)
        s += ('<text class="ct-in" x="%g" y="%g">%s</text><text class="ct-in" x="%g" y="%g">%s</text>'
              % (cx, cy - r * .42, a, cx, cy + r * .45, b))
        return '<g class="%s">%s</g>' % (cls, s)
    if kind in ("manual_valve", "check_valve", "motor_operated_valve"):
        return _valve(n, cls)
    if kind == "pipe_cap":
        return '<g class="%s"><rect x="%g" y="%g" width="%g" height="%g" %s/></g>' % (cls, x + w * .15, y + h * .15, w * .7, h * .7, SW)
    if kind == "continuation":
        tip = 14
        if n["flip_h"]:
            d = "M%g %g H%g V%g H%g L%g %g Z" % (x + tip, y, x + w, y + h, x + tip, x, y + h / 2)
            tx0 = x + tip + (w - tip) / 2
        else:
            d = "M%g %g H%g L%g %g L%g %g H%g Z" % (x, y, x + w - tip, x + w, y + h / 2, x + w - tip, y + h, x)
            tx0 = x + (w - tip) / 2
        lines = (n["text"] or "").split("\n")
        tx = "".join('<text class="ct-cont" x="%g" y="%g">%s</text>' % (tx0, y + h / 2 + (i - (len(lines) - 1) / 2) * 10, s)
                     for i, s in enumerate(lines))
        return '<g class="%s"><path d="%s" %s/>%s</g>' % (cls, d, SW, tx)
    return '<g class="%s"><rect x="%g" y="%g" width="%g" height="%g" rx="4" %s/></g>' % (cls, x, y, w, h, SW)


PIPE_CLS = {"process": "cp-proc", "process_secondary": "cp-sec", "instrument_tap": "cp-tap", "signal_electric": "cp-sig"}


def _pipe(p, cls=""):
    return '<polyline class="%s %s" points="%s" %s/>' % (PIPE_CLS.get(p["line_type"] or "", "cp-proc"), cls,
                                                          " ".join("%g,%g" % tuple(q) for q in p["points"]), SW)


def _seglen(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _line_labels(pipes, dim_ids):
    best = {}
    for p in pipes:
        if not p["line_no"]:
            continue
        for a, b in zip(p["points"], p["points"][1:]):
            if _seglen(a, b) > best.get(p["line_no"], (0,))[0]:
                best[p["line_no"]] = (_seglen(a, b), a, b, p["id"])
    out = ""
    for no, (_L, a, b, pid) in best.items():
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        cls = "ct-line" + (" dim" if pid in dim_ids else "")
        if abs(a[0] - b[0]) < 1:
            out += '<text class="%s" transform="translate(%g %g) rotate(-90)">%s</text>' % (cls, mx - 5, my + 30, no)
        else:
            out += '<text class="%s" x="%g" y="%g">%s</text>' % (cls, mx + 30, my - 5, no)
    return out


def _flow_arrows(pipes, dim_ids):
    import math
    out = ""
    for p in pipes:
        if not p["flow"] or p["line_type"] not in ("process", "process_secondary"):
            continue
        segs = list(zip(p["points"], p["points"][1:]))
        if max(_seglen(*sg) for sg in segs) < 40:
            segs = [max(segs, key=lambda sg: _seglen(*sg))]
        for a, b in segs:
            L = _seglen(a, b)
            if L < 40 and len(segs) > 1:
                continue
            k = max(1, round(L / 110))
            ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            for j in range(k):
                t = (j + .5) / k
                if min(t, 1 - t) * L < 12:
                    continue
                out += ('<path class="ct-arrow%s" d="M-5 -3.5 L5 0 L-5 3.5 Z" transform="translate(%g %g) rotate(%g)"/>'
                        % (" dim" if p["id"] in dim_ids else "", a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, ang))
    return out


def _tag(n, cls="ct-tag"):
    t = n["tag"]
    if not t or n["kind"] in ("tee", "continuation", "transmitter", "indicator", "temperature_element", "pipe_cap"):
        return ""
    if n["label"]:
        x, y, w, h = n["label"]
        return '<text class="%s" x="%g" y="%g" style="text-anchor:start">%s</text>' % (cls, x, y + 9, t)
    x, y, w, h = n["bbox"]
    return '<text class="%s" x="%g" y="%g">%s</text>' % (cls, x + w / 2, y + h + 12, t)


def clean_sheet(data, crop, marks=None, unknown=None, extra=""):
    """정리된 도면 한 장. marks {"path","start","warn": set(local_id)}는 그 객체의 색을 바꾼다(겹쳐 그리는 띠·상자 없음).
    unknown {"symbol","notag","ai": set, "open": {pipe_id: "source"|"target"}}는 자리표로 그린다(§10.4)."""
    marks = marks or {}
    unknown = unknown or {"symbol": set(), "notag": set(), "ai": set(), "open": {}}
    marked = set().union(*marks.values()) if marks else set()
    every = {p["id"] for p in data["pipes"]} | {n["id"] for n in data["nodes"]}
    dim_ids = (every - marked) if marks else set()
    d = lambda i: " dim" if i in dim_ids else ""
    s = '<rect class="ct-paper" x="0" y="0" width="%d" height="%d"/><rect class="ct-frame" x="8" y="8" width="%d" height="%d"/>' % (
        VIEW_W, VIEW_H, VIEW_W - 16, VIEW_H - 16)
    tx, ty = VIEW_W - 400, VIEW_H - 92
    s += ('<g class="ct-title"><rect x="%g" y="%g" width="384" height="76"/><line x1="%g" y1="%g" x2="%g" y2="%g"/>'
          '<text class="t1" x="%g" y="%g">SNP-M-101 · REV. 0</text><text class="t2" x="%g" y="%g">REACTOR COOLANT SYSTEM - MAIN LOOP</text></g>'
          % (tx, ty, tx, ty + 34, tx + 384, ty + 34, tx + 12, ty + 22, tx + 12, ty + 58))
    for p in data["pipes"]:
        if p["id"] not in marked:
            s += _pipe(p, d(p["id"]).strip())
    for n in data["nodes"]:
        if n["kind"] == "tee":
            x, y, w, h = n["bbox"]
            s += '<circle class="ct-dot%s" cx="%g" cy="%g" r="2.6"/>' % (d(n["id"]), x + w / 2, y + h / 2)
    s += _flow_arrows(data["pipes"], dim_ids) + _line_labels(data["pipes"], dim_ids)
    for n in data["nodes"]:
        if n["kind"] == "tee" or n["id"] in marked:
            continue
        x, y, w, h = n["bbox"]
        if n["id"] in unknown["symbol"]:
            s += ('<g class="cu-ph"><rect x="%g" y="%g" width="%g" height="%g" rx="3"/><text x="%g" y="%g">?</text></g>'
                  % (x - 3, y - 3, w + 6, h + 6, x + w / 2, y + h / 2)) + ('<text class="ct-tag faint" x="%g" y="%g">%s</text>' % (x + w / 2, y + h + 22, n["tag"]) if n["tag"] else "")   # 자리표 글자는 아래(선택 테두리와 겹치지 않게)
        elif n["id"] in unknown["ai"]:
            s += _sym(n, "cu-ai") + _tag(n, "ct-tag ai")
            s += ('<g class="cu-ai-tag"><rect x="%g" y="%g" width="20" height="12" rx="3"/><text x="%g" y="%g">AI</text></g>'
                  % (x + w + 2, y - 14, x + w + 12, y - 8))
        else:
            s += _sym(n, "cs" + d(n["id"]))
            if n["id"] in unknown["notag"]:
                s += ('<g class="cu-notag"><line x1="%g" y1="%g" x2="%g" y2="%g"/><text x="%g" y="%g">태그 없음</text></g>'
                      % (x - 8, y + h + 16, x + w + 8, y + h + 16, x + w / 2, y + h + 12))
            else:
                s += _tag(n, "ct-tag" + d(n["id"]))
    for pid, end in unknown["open"].items():
        p = next(q for q in data["pipes"] if q["id"] == pid)
        s += '<circle class="cu-open" cx="%g" cy="%g" r="4.5"/>' % tuple(p["points"][0 if end == "source" else -1])
    for k in ("path", "warn", "start"):            # 표시 걸린 객체를 같은 자리에 그 색으로(정리된 보기의 '객체 색 바꾸기')
        for p in data["pipes"]:
            if p["id"] in marks.get(k, ()):
                s += _pipe(p, "cs-" + k)
        for n in data["nodes"]:
            if n["id"] in marks.get(k, ()):
                if n["kind"] == "tee":
                    x, y, w, h = n["bbox"]
                    s += '<circle class="ct-dot cs-%s-f" cx="%g" cy="%g" r="3.4"/>' % (k, x + w / 2, y + h / 2)
                else:
                    s += _sym(n, "cs-" + k) + _tag(n, "ct-tag cs-%s-t" % k)
    x, y, w, h = crop
    return ('<svg class="sheet clean" viewBox="%g %g %g %g" preserveAspectRatio="xMidYMid meet" role="img" aria-label="정리된 도면 SNP-M-101">%s%s</svg>'
            % (x - OFF, y - OFF, w, h, s, extra))


def view_switch(view, n_unknown, confirmed=False):
    if confirmed:
        chip = '<span class="unk ok">%s 미확인 0 · 쪽 확정됨</span>' % ic("circle-check", "sm")
    else:
        chip = '<button class="unk" title="다음 미확인 (N)" aria-label="다음 미확인">%s 미확인 %d곳 <kbd>N</kbd></button>' % (ic("alert-triangle", "sm"), n_unknown)
    return ('<div class="float viewsw" role="group" aria-label="도면 보기"><div class="seg2">'
            '<button class="%s" title="원본 보기 (O)" aria-label="원본 보기">원본</button>'
            '<button class="%s" title="정리된 보기 (O)" aria-label="정리된 보기">정리</button></div>%s</div>'
            % ("on" if view == "original" else "", "on" if view == "clean" else "", chip))


def _ids(data, tags=(), line_nos=(), cont=()):
    return ({n["id"] for n in data["nodes"] if n["tag"] in tags}
            | {n["id"] for n in data["nodes"] if n["kind"] == "continuation" and any(c in (n["text"] or "") for c in cont)}
            | {p["id"] for p in data["pipes"] if p["line_no"] in line_nos})


def page7():
    data = clean_data()
    tees = ("RC-L003-T18", "RC-L003-T19", "RC-L003-T20", "RC-L003-T21", "RC-L003-T22")
    marks = {"path": _ids(data, tees + ("RC-RV01", "RC-FT101", "RC-TE102", "RC-V020"), ("RC-L003",)),
             "start": _ids(data, ("RC-PP01",)),
             "warn": _ids(data, ("RC-V010",), cont=("CV-L001",))}
    steps = "".join('<g class="ov-step"><circle cx="%g" cy="%g" r="13"/><text x="%g" y="%g">%d</text></g>'
                    % (x - OFF, y - OFF, x - OFF, y - OFF, k) for k, (x, y) in STEPS)
    svg = clean_sheet(data, CROP_MAIN, marks, extra=steps)
    legend = ('<div class="float legend"><div><i style="border-color:var(--path)"></i>경로 (7단계)</div>'
              '<div><i style="border-color:var(--accent)"></i>출발</div><div><i style="border-color:var(--warn-line)"></i>확인 못 한 곳</div>'
              '<div><i style="border-color:#c3c9d1"></i>경로 밖</div>'
              '<div class="x"><span class="muted">채팅 답 #2</span><button class="btn ghost sm">%s 지우기</button></div></div>' % ic("x", "sm"))
    center = topbar() + '<div class="canvas clean-bg">%s%s%s%s</div>' % (svg, view_switch("clean", 0, confirmed=True), legend, toolbar())
    return page("7 정리된 보기", shell("", center, chat(path_answer())))


UNK = {"symbol": ("RC-V002",), "notag": ("RC-TE102",), "ai": ("RC-V010",), "open": {"local-edge-032": "target"}}


def page8():
    data = clean_data()
    by_tag = {n["tag"]: n for n in data["nodes"] if n["tag"]}
    unk = {"symbol": {by_tag[t]["id"] for t in UNK["symbol"]}, "notag": {by_tag[t]["id"] for t in UNK["notag"]},
           "ai": {by_tag[t]["id"] for t in UNK["ai"]}, "open": UNK["open"]}
    x, y, w, h = by_tag["RC-V002"]["bbox"]
    sel = '<rect class="ov-sel" x="%g" y="%g" width="%g" height="%g" rx="4" style="fill:none"/>' % (x - 8, y - 8, w + 16, h + 16)
    svg = clean_sheet(data, (300, 520, 760, 550), unknown=unk, extra=sel)
    crop_svg = ('<svg class="orig-crop" viewBox="%g %g %g %g" role="img" aria-label="원본 조각">'
                '<image href="assets/snp-m-101.svg" x="0" y="0" width="%d" height="%d"/>'
                '<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#d9a23a" stroke-width="1.5" stroke-dasharray="4 3"/></svg>'
                % (x - 24, y - 24, w + 48, h + 48, VIEW_W, VIEW_H, x - 3, y - 3, w + 6, h + 6))
    pop = ('<div class="float pop" style="left:63%%;top:15%%;width:300px"><h4>%s 미확인 기호</h4>'
           '<div class="muted">붙은 글자 RC-V002 · 종류를 읽지 못함</div><div class="crop-lbl">원본 조각 (사방 24 단위)</div>%s'
           '<dl><dt>배관</dt><dd class="mono">RC-L021</dd><dt>사전 후보</dt><dd>수동 밸브 · 체크 밸브</dd></dl>'
           '<div class="acts"><button class="btn sm primary">종류 고르기</button><button class="btn sm">%s AI에 묻기</button>'
           '<button class="btn ghost sm">도면에 없음</button></div></div>' % (ic("help-circle", "sm"), crop_svg, ic("sparkles", "sm")))
    legend = ('<div class="float legend"><div><i style="border-color:var(--warn-line);border-top-style:dashed"></i>미확인 기호 · 태그 없음</div>'
              '<div><i style="border-color:var(--warn-line);width:6px;height:6px;border:2px solid var(--warn-line);border-radius:50%"></i>끊긴 연결(열린 끝)</div>'
              '<div><i style="border-color:var(--ai-line);border-top-style:dashed"></i>AI 후보(수락 전)</div></div>')
    msgs = ('<div class="q">이 쪽에서 확인할 곳 알려 줘</div><div class="ans"><div class="src"><div class="lbl">%s 도면에서 확인</div>'
            '<p>SNP-M-101에 미확인이 4곳 있습니다. 도구 막대의 <b>미확인 4곳</b>이나 <kbd>N</kbd>으로 차례로 볼 수 있습니다.</p></div>'
            '<ol class="steps"><li><span class="n">1</span>%s<span class="muted">종류를 읽지 못한 기호</span></li>'
            '<li><span class="n">2</span>%s<span class="muted">AI 후보 · 전동 밸브, 수락 전</span></li>'
            '<li><span class="n">3</span>%s<span class="muted">온도 측정점 · 태그를 읽지 못함</span></li>'
            '<li><span class="n">4</span>%s<span class="muted">계측 연결 끝이 열림</span></li></ol>'
            '<div class="warnline">%s<span>미확인이 남아 있어 이 쪽은 아직 확정할 수 없습니다. DEXPI 내보내기도 같은 조건을 씁니다.</span></div>'
            '<div class="meta">%s 도구 1회 · 0.9초</div></div>'
            % (ic("circle-check", "sm"), idchip("RC-V002"), idchip("RC-V010"), idchip("local-node-032"), idchip("local-edge-032"),
               ic("alert-triangle", "sm"), ic("info-circle", "sm")))
    center = topbar() + '<div class="canvas clean-bg">%s%s%s%s%s</div>' % (svg, view_switch("clean", 4), pop, legend, toolbar(zoom="140%"))
    return page("8 미확인이 섞인 정리된 보기", shell("", center, chat(msgs, examples=False)))


PAGES = [
    ("1-home", page1, "기본 화면", "도면과 채팅. 경로 질문의 답 카드(근거·단계·경고·일반 지식 구분)와 도면 위 경로 표시.", 1536),
    ("2-drawings-panel", page2, "도면 목록·등록 패널", "왼쪽 메뉴의 '도면'. 파일 끌어 놓기, 표제란 후보, AI 검토 토글과 호출 상한.", 1536),
    ("3-make-node", page3, "네모로 골라 구간 만들기", "고르기 모드, 고른 것 막대, 새 구간 초안 카드, 채팅이 만든 S1~S3 묶음과 되돌리기.", 1536),
    ("4-results-panel", page4, "분석 결과 패널", "구간×편차 표와 고른 칸의 워크시트, 수용·수정·기각·보류.", 1536),
    ("5-home-narrow", page5, "1366 폭 기본 화면", "메뉴·채팅이 좁아진 배치. 구성요소를 누른 속성 말풍선.", 1366),
    ("6-no-ai", page6, "AI 연결 없는 PC", "구독이 없을 때 채팅 자리의 안내와 스크립트로 되는 일.", 1536),
    ("7-clean-view", page7, "정리된 보기", "SNP-M-101을 읽은 결과로 다시 그린 도면. 시안 1과 같은 경로 답을 객체 색으로 보인다.", 1536),
    ("8-clean-unknown", page8, "미확인이 섞인 정리된 보기", "점선 자리표, 열린 끝, 태그 없음, AI 후보와 원본 조각 말풍선. 미확인은 예시로 섞은 것.", 1536),
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
            '<section><h2>원본 ↔ 정리 (같은 도면, 같은 자리)</h2><div class="cmp">'
            '<figure><a href="1-home.html"><img src="1-home-1920.png" alt="원본 보기"></a><figcaption><b>원본 보기 (시안 1)</b>'
            '원본 도면 SVG 위에 경로 띠와 상자를 얹는다.</figcaption></figure>'
            '<figure><a href="7-clean-view.html"><img src="7-clean-view-1920.png" alt="정리된 보기"></a><figcaption><b>정리된 보기 (시안 7)</b>'
            '읽은 결과로 같은 좌표에 다시 그리고, 경로에 든 객체의 색을 바꾼다. 경로 밖은 회색.</figcaption></figure>'
            '<figure><a href="5-home-narrow.html"><img src="5-home-narrow-1366.png" alt="원본 확대"></a><figcaption><b>원본 보기 확대 (시안 5)</b>'
            '같은 부분의 원본.</figcaption></figure>'
            '<figure><a href="8-clean-unknown.html"><img src="8-clean-unknown-1920.png" alt="미확인이 섞인 정리된 보기"></a><figcaption><b>미확인이 섞인 정리된 보기 (시안 8)</b>'
            '못 읽은 곳은 점선 자리표로 남기고, 누르면 원본 조각을 보인다.</figcaption></figure></div></section>'
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
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    for name, fn, _t, _d, w in PAGES:
        if only and name not in only:
            continue
        (ROOT / ("%s.html" % name)).write_text(fn(), encoding="utf-8")
    (ROOT / "index.html").write_text(index(), encoding="utf-8")
    if "--no-png" not in sys.argv:
        for name, _f, _t, _d, w in PAGES:
            if not only or name in only:
                shoot(name, w)
    print("ok:", ", ".join(p[0] for p in PAGES), "icons:", len(_icons))
