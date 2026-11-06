"""완성본 디자인 시안 3안 × 5화면 생성기.

python 디자인/시안/완성본/build.py          HTML·대비표 생성(대비 미달이면 종료 코드 1)
python 디자인/시안/완성본/build.py --shoot  위 작업 뒤 Chrome 헤드리스로 1366×768·1920×1080 PNG 저장
표준 라이브러리만 쓴다. 데이터는 모두 가상 샘플이다.
"""
import html
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
FONT_CSS = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
FONT_STACK = "'Pretendard Variable', Pretendard, 'Malgun Gothic', '맑은 고딕', 'Apple SD Gothic Neo', system-ui, sans-serif"
MONO_STACK = "'Cascadia Mono', Consolas, 'D2Coding', monospace"

# ---------------------------------------------------------------- 토큰
COMMON_KINDS_LIGHT = {
    "k-equipment": "#1d4ed8", "k-valve": "#0f766e", "k-instrument": "#0b7fb5", "k-piping": "#5b5fe0",
    "k-doc": "#9a5b06", "k-basis": "#7a5c00", "k-failure": "#c0262d",
    "r-physical": "#15803d", "r-signal": "#7c3aed", "r-measurement": "#b86304", "r-unresolved": "#dc2626",
    "hl-path": "#d9480f",
    "risk-ok-bg": "#eef0f3", "risk-ok-ink": "#374151", "risk-ok-line": "#8b93a1",
    "risk-cond-bg": "#fde68a", "risk-cond-ink": "#78350f", "risk-cond-line": "#b36205",
    "risk-deny-bg": "#991b1b", "risk-deny-ink": "#ffffff",
}

VARIANTS = {
    "A-밝은미니멀": {
        "name": "A안 · 밝은 미니멀",
        "short": "A",
        "tokens": {
            "bg": "#f5f6f8", "surface": "#ffffff", "surface-2": "#f2f4f7", "line": "#e3e6eb", "line-strong": "#858d9b",
            "ink": "#111827", "ink-2": "#374151", "muted": "#5b6472",
            "ui": "#2556c8", "ui-weak": "#edf2fd", "ui-ink": "#1b3f94", "on-fill": "#ffffff",
            "ok": "#15803d", "ok-bg": "#e6f5eb", "ok-ink": "#14532d", "on-ok": "#ffffff",
            "warn-bg": "#fff3d6", "warn-ink": "#7c4a03", "warn-line": "#b7791f",
            "err-bg": "#fdeceb", "err-ink": "#b42318", "err-line": "#e5877f",
            "ai-a": "#f3f4f6", "ai-b": "#e8eaee", "ai-line": "#858d9b", "ai-ink": "#3f4753",
            "canvas": "#ffffff", "draw-line": "#3b4351", "draw-ink": "#1f2937", "draw-sig": "#6b7280",
            "seg1": "#0e7490", "seg2": "#7c3aed", "seg3": "#c2410c", "seg4": "#be185d", "seg5": "#4d7c0f", "on-seg": "#ffffff",
            "nav-bg": "#ffffff", "nav-ink": "#111827", "nav-muted": "#5b6472", "nav-active-bg": "#2556c8", "nav-active-ink": "#ffffff",
            **COMMON_KINDS_LIGHT,
        },
        "density": {
            "fs": "14px", "fs-sm": "12.5px", "fs-h1": "22px", "pad": "24px", "gap": "16px",
            "radius": "14px", "r-chip": "999px", "r-btn": "10px", "r-input": "10px",
            "cell-y": "10px", "cell-x": "14px", "ph-pad": "14px 18px", "pb-pad": "18px",
            "btn-pad": "7px 16px", "inp-pad": "7px 12px",
            "shadow": "0 1px 2px rgba(16,24,40,.04), 0 2px 8px rgba(16,24,40,.05)",
        },
    },
    "B-고밀도작업대": {
        "name": "B안 · 고밀도 작업대",
        "short": "B",
        "tokens": {
            "bg": "#e9ebee", "surface": "#fbfbfc", "surface-2": "#f1f2f4", "line": "#d6d9de", "line-strong": "#7f8793",
            "ink": "#0f1419", "ink-2": "#2a313b", "muted": "#525b67",
            "ui": "#0a5fc2", "ui-weak": "#e2edfb", "ui-ink": "#0a4a96", "on-fill": "#ffffff",
            "ok": "#127238", "ok-bg": "#e2f3e8", "ok-ink": "#0f4f28", "on-ok": "#ffffff",
            "warn-bg": "#fdf0d2", "warn-ink": "#74430a", "warn-line": "#a8740d",
            "err-bg": "#fbe7e6", "err-ink": "#a8201a", "err-line": "#d9776f",
            "ai-a": "#eef0f2", "ai-b": "#e3e6ea", "ai-line": "#7f8793", "ai-ink": "#3a414b",
            "canvas": "#fdfdfd", "draw-line": "#2f3742", "draw-ink": "#1a1f26", "draw-sig": "#66707c",
            "seg1": "#0b7285", "seg2": "#6d28d9", "seg3": "#b54708", "seg4": "#a61e4d", "seg5": "#3f6212", "on-seg": "#ffffff",
            "nav-bg": "#23282f", "nav-ink": "#e6e9ee", "nav-muted": "#aab2bd", "nav-active-bg": "#3b4452", "nav-active-ink": "#ffffff",
            **COMMON_KINDS_LIGHT,
        },
        "density": {
            "fs": "12.5px", "fs-sm": "11.5px", "fs-h1": "14px", "pad": "8px", "gap": "8px",
            "radius": "4px", "r-chip": "3px", "r-btn": "4px", "r-input": "3px",
            "cell-y": "3px", "cell-x": "8px", "ph-pad": "5px 10px", "pb-pad": "8px",
            "btn-pad": "3px 10px", "inp-pad": "3px 8px", "shadow": "none",
        },
    },
    "C-다크대시보드": {
        "name": "C안 · 다크 대시보드",
        "short": "C",
        "tokens": {
            "bg": "#0e1217", "surface": "#151b22", "surface-2": "#1c242d", "line": "#27313c", "line-strong": "#64748a",
            "ink": "#e9eef4", "ink-2": "#c5cdd8", "muted": "#95a1b1",
            "ui": "#5ba4ff", "ui-weak": "#14263d", "ui-ink": "#a9cdff", "on-fill": "#07111d",
            "ok": "#3dbb6d", "ok-bg": "#10271a", "ok-ink": "#86e0a8", "on-ok": "#06130b",
            "warn-bg": "#2c2009", "warn-ink": "#f2c063", "warn-line": "#c8922a",
            "err-bg": "#2d1416", "err-ink": "#ff9d96", "err-line": "#c4544d",
            "ai-a": "#1b222b", "ai-b": "#232b35", "ai-line": "#6b788a", "ai-ink": "#c2cad5",
            "canvas": "#10161c", "draw-line": "#a3afbd", "draw-ink": "#dfe5ec", "draw-sig": "#7f8b9a",
            "seg1": "#2dd4bf", "seg2": "#a78bfa", "seg3": "#fb923c", "seg4": "#f472b6", "seg5": "#a3e635", "on-seg": "#0b0f14",
            "nav-bg": "#0a0d11", "nav-ink": "#e9eef4", "nav-muted": "#95a1b1", "nav-active-bg": "#1d2b3c", "nav-active-ink": "#ffffff",
            "k-equipment": "#6ea6ff", "k-valve": "#2ccdb4", "k-instrument": "#4fc3f7", "k-piping": "#a5a8ff",
            "k-doc": "#e7b157", "k-basis": "#d9c36a", "k-failure": "#ff8a80",
            "r-physical": "#4ade80", "r-signal": "#b794f6", "r-measurement": "#f6ad55", "r-unresolved": "#ff6b6b",
            "hl-path": "#ff9a3c",
            "risk-ok-bg": "#232c37", "risk-ok-ink": "#d4dbe4", "risk-ok-line": "#6b788a",
            "risk-cond-bg": "#4a3510", "risk-cond-ink": "#ffd98a", "risk-cond-line": "#d29a2c",
            "risk-deny-bg": "#a32020", "risk-deny-ink": "#ffffff",
        },
        "density": {
            "fs": "13.5px", "fs-sm": "12px", "fs-h1": "20px", "pad": "20px", "gap": "14px",
            "radius": "12px", "r-chip": "6px", "r-btn": "8px", "r-input": "8px",
            "cell-y": "8px", "cell-x": "12px", "ph-pad": "12px 16px", "pb-pad": "16px",
            "btn-pad": "6px 14px", "inp-pad": "6px 10px", "shadow": "none",
        },
    },
}

TEXT, GRAPHIC = 4.5, 3.0
CONTRAST_PAIRS = [
    ("본문 글자 / 바탕", "ink", "bg", TEXT), ("본문 글자 / 패널", "ink", "surface", TEXT),
    ("보조 글자 / 패널", "ink-2", "surface", TEXT), ("흐린 글자 / 패널", "muted", "surface", TEXT),
    ("흐린 글자 / 바탕", "muted", "bg", TEXT), ("흐린 글자 / 보조 패널", "muted", "surface-2", TEXT),
    ("강조 글자(링크) / 패널", "ui", "surface", TEXT), ("선택 행 글자 / 선택 바탕", "ui-ink", "ui-weak", TEXT),
    ("주 버튼 글자 / 강조 채움", "on-fill", "ui", TEXT), ("통과 글자 / 통과 바탕", "ok-ink", "ok-bg", TEXT),
    ("승인 칩 글자 / 승인 채움", "on-ok", "ok", TEXT), ("경고 글자 / 경고 바탕", "warn-ink", "warn-bg", TEXT),
    ("경고 글자 / 패널", "warn-ink", "surface", TEXT), ("오류 글자 / 오류 바탕", "err-ink", "err-bg", TEXT),
    ("오류 글자 / 패널", "err-ink", "surface", TEXT), ("AI 초안 글자 / 빗금 진한 칸", "ai-ink", "ai-b", TEXT),
    ("위험 수용 글자 / 바탕", "risk-ok-ink", "risk-ok-bg", TEXT), ("위험 조건부 글자 / 바탕", "risk-cond-ink", "risk-cond-bg", TEXT),
    ("위험 불허 글자 / 바탕", "risk-deny-ink", "risk-deny-bg", TEXT), ("탐색 글자 / 탐색 바탕", "nav-ink", "nav-bg", TEXT),
    ("탐색 흐린 글자 / 탐색 바탕", "nav-muted", "nav-bg", TEXT), ("탐색 선택 글자 / 선택 바탕", "nav-active-ink", "nav-active-bg", TEXT),
    ("도면 글자 / 도면 바탕", "draw-ink", "canvas", TEXT),
    *[(f"구간 꼬리표 글자 / 구간{i}", "on-seg", f"seg{i}", TEXT) for i in range(1, 6)],
    ("입력란 테두리 / 패널", "line-strong", "surface", GRAPHIC), ("포커스·선택 테두리 / 패널", "ui", "surface", GRAPHIC),
    ("AI 초안 점선 / 패널", "ai-line", "surface", GRAPHIC), ("경고 테두리 / 패널", "warn-line", "surface", GRAPHIC),
    ("도면 배관선 / 도면 바탕", "draw-line", "canvas", GRAPHIC), ("도면 신호선 / 도면 바탕", "draw-sig", "canvas", GRAPHIC),
    *[(f"노드 {k[2:]} / 도면 바탕", k, "canvas", GRAPHIC) for k in
      ("k-equipment", "k-valve", "k-instrument", "k-piping", "k-doc", "k-basis", "k-failure")],
    *[(f"관계 {k[2:]} / 도면 바탕", k, "canvas", GRAPHIC) for k in
      ("r-physical", "r-signal", "r-measurement", "r-unresolved")],
    ("경로 강조 / 도면 바탕", "hl-path", "canvas", GRAPHIC),
    *[(f"구간{i} 색 / 도면 바탕", f"seg{i}", "canvas", GRAPHIC) for i in range(1, 6)],
]


def _lum(hex_):
    h = hex_.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast_table(tok):
    rows, fails = [], []
    for label, fg, bg, need in CONTRAST_PAIRS:
        r = ratio(tok[fg], tok[bg])
        ok = r >= need
        rows.append(f"| {label} | `{fg}` {tok[fg]} | `{bg}` {tok[bg]} | {r:.2f} | {need:g} | {'통과' if ok else '미달'} |")
        if not ok:
            fails.append(f"{label} {r:.2f} < {need}")
    head = "| 쌍 | 전경 | 배경 | 대비 | 기준 | 판정 |\n| --- | --- | --- | ---: | ---: | --- |\n"
    return head + "\n".join(rows) + "\n", fails


# ---------------------------------------------------------------- 가상 샘플 데이터
SCREENS = [
    ("1-자료등록", "자료 등록", "등록"),
    ("2-도면추출", "도면 추출", "추출"),
    ("3-지식그래프", "지식그래프", "그래프"),
    ("4-검토구간", "검토구간", "구간"),
    ("5-요약행렬", "분석 결과", "결과"),
]

SEGMENTS = [
    ("S1", "가압기 본체·히터", 6, "확정"),
    ("S2", "살수 계통", 3, "제안"),
    ("S3", "PORV 방출", 3, "제안"),
    ("S4", "안전밸브 방출·PRT", 5, "제안"),
    ("S5", "밀림관·RCS 고온관", 2, "제안"),
]
UNCOVERED = [("PT-457", "계기", "가압기 압력 3채널"), ("TE-463", "계기", "밀림관 온도"), ("V-8030", "밸브", "PRT 배수")]

# id, kind, shape, x, y, w, h, segment, label
COMPONENTS = [
    ("PZR", "equipment", "rect", 430, 150, 110, 260, "S1", "PZR 가압기"),
    ("HTR", "equipment", "rect", 450, 372, 70, 26, "S1", "HTR 히터"),
    ("PCV-444C", "valve", "valve", 250, 90, 0, 0, "S2", None),
    ("PCV-444D", "valve", "valve", 350, 90, 0, 0, "S2", None),
    ("MOV-8000A", "valve", "valve", 640, 190, 0, 0, "S3", None),
    ("PCV-455A", "valve", "valve", 770, 190, 0, 0, "S3", None),
    ("RV-8010A", "valve", "valve", 650, 50, 0, 0, "S4", None),
    ("RV-8010B", "valve", "valve", 750, 50, 0, 0, "S4", None),
    ("RV-8010C", "valve", "valve", 850, 50, 0, 0, "S4", None),
    ("PRT", "equipment", "rect", 840, 330, 140, 90, "S4", "PRT 방출탱크"),
    ("PT-455", "instrument", "inst", 355, 200, 0, 0, "S1", None),
    ("PT-456", "instrument", "inst", 355, 255, 0, 0, "S1", None),
    ("LT-459", "instrument", "inst", 355, 310, 0, 0, "S1", None),
    ("PT-457", "instrument", "inst", 355, 365, 0, 0, None, None),
    ("TE-463", "instrument", "inst", 548, 470, 0, 0, None, None),
    ("V-8030", "valve", "valve-v", 910, 470, 0, 0, None, None),
]
PIPES = [
    ("살수 배관", [(160, 540), (160, 90), (485, 90), (485, 150)], "S2"),
    ("PORV 배관", [(540, 190), (880, 190), (880, 330)], "S3"),
    ("안전밸브 배관", [(515, 150), (515, 50), (950, 50), (950, 330)], "S4"),
    ("밀림관", [(485, 410), (485, 540)], "S5"),
    ("RCS 고온관", [(110, 540), (920, 540)], "S5"),
    ("PRT 배수", [(910, 420), (910, 525)], "S4"),
]
SEG_LABELS = {"S1": (446, 168), "S2": (190, 74), "S3": (690, 214), "S4": (580, 22), "S5": (200, 562)}


def pid_svg(mode):
    """mode: 'extract'(노드 종류 색, PCV-455A 선택) | 'segment'(구간 색, 미포함 표시)."""
    o = ['<svg viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid meet" role="img" '
         'aria-label="SNP-M-102 가압기 계통 단순화 도면(가상)">']
    seg_of = lambda s: f"seg{s[1]}" if s else None
    for name, pts, seg in PIPES:
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        if mode == "segment":
            o.append(f'<path d="{d}" class="seg-under {seg_of(seg)}"/>')
            o.append(f'<path d="{d}" class="pipe seg-pipe {seg_of(seg)}{" sel" if seg == "S3" else ""}"/>')
        else:
            o.append(f'<path d="{d}" class="pipe rel-phys"/>')
    for cid, kind, shape, x, y, w, h, seg, label in COMPONENTS:
        if kind == "instrument":
            tx = x + 17
            target = 430 if x < 430 else 485
            cls = "sig rel-unres" if (cid == "TE-463" and mode == "extract") else "sig"
            o.append(f'<path d="M{tx},{y} L{target},{y}" class="{cls}"/>')
    o.append('<text x="600" y="566" class="lbl small">RCS 고온관 (Loop 2)</text>')
    o.append('<text x="146" y="330" text-anchor="middle" class="lbl small" transform="rotate(-90 146 330)">살수 배관 (저온관에서)</text>')
    for cid, kind, shape, x, y, w, h, seg, label in COMPONENTS:
        if mode == "segment":
            k = f"seg-stroke {seg_of(seg)}" if seg else "uncov"
        else:
            k = f"kind-{kind}"
        sel = mode == "extract" and cid == "PCV-455A"
        if shape == "rect":
            o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{12 if cid == "PZR" else 6}" class="eq {k}"/>')
            o.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 5 if cid != "PZR" else y + 120}" text-anchor="middle" class="lbl">{label}</text>')
        elif shape in ("valve", "valve-v"):
            if shape == "valve":
                pts = f"{x - 13},{y - 9} {x + 13},{y + 9} {x + 13},{y - 9} {x - 13},{y + 9}"
                ly = y + 28 if cid.startswith("RV") else y - 20
                lx = x
                anchor = "middle"
            else:
                pts = f"{x - 9},{y - 13} {x + 9},{y + 13} {x - 9},{y + 13} {x + 9},{y - 13}"
                lx, ly, anchor = x - 30, y + 4, "end"
            o.append(f'<polygon points="{pts}" class="vlv {k}"/>')
            o.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" class="lbl tag">{cid}</text>')
        else:
            a, b = cid.split("-")
            o.append(f'<circle cx="{x}" cy="{y}" r="17" class="inst {k}"/>')
            o.append(f'<text x="{x}" y="{y - 2}" text-anchor="middle" class="lbl it">{a}</text>')
            o.append(f'<text x="{x}" y="{y + 10}" text-anchor="middle" class="lbl it">{b}</text>')
        if sel:
            o.append(f'<rect x="{x - 21}" y="{y - 14}" width="42" height="28" rx="7" class="sel-ring"/>')
        if mode == "segment" and not seg:
            o.append(f'<circle cx="{x}" cy="{y}" r="25" class="uncov-ring"/>')
    if mode == "segment":
        for sid, (x, y) in SEG_LABELS.items():
            i = sid[1]
            o.append(f'<rect x="{x - 4}" y="{y - 13}" width="34" height="19" rx="5" class="seg-pill seg{i}"/>')
            o.append(f'<text x="{x + 13}" y="{y + 1}" text-anchor="middle" class="seg-pill-t">{sid}</text>')
        o.append('<text x="590" y="476" class="lbl small uncov-t">미포함</text>')
    o.append("</svg>")
    return "".join(o)


KG_NODES = [
    ("PCV-455A", "PCV-455A PORV", "valve", 520, 290),
    ("PC-455A", "PC-455A 압력제어기", "instrument", 330, 200),
    ("PT-455", "PT-455", "instrument", 150, 130),
    ("PT-456", "PT-456", "instrument", 150, 260),
    ("PZR", "PZR 가압기", "equipment", 330, 400),
    ("MOV-8000A", "MOV-8000A", "valve", 700, 190),
    ("PRT", "PRT 방출탱크", "equipment", 860, 300),
    ("RV-8010A", "RV-8010A", "valve", 700, 420),
    ("D1", "계통설명서 §4.3", "doc", 160, 480),
    ("D2", "OP-RCS-02 §5.2", "doc", 860, 470),
    ("B1", "설계기준 PORV 용량", "basis", 860, 110),
    ("F1", "고장모드 PORV 개방 실패", "failure", 520, 520),
]
KG_EDGES = [
    ("PT-455", "PC-455A", "measurement", True), ("PT-456", "PC-455A", "measurement", False),
    ("PC-455A", "PCV-455A", "signal", True), ("PZR", "MOV-8000A", "physical", False),
    ("MOV-8000A", "PCV-455A", "physical", False), ("PCV-455A", "PRT", "physical", True),
    ("PZR", "RV-8010A", "physical", False), ("RV-8010A", "PRT", "physical", False),
    ("D1", "PC-455A", "doc", False), ("D1", "PCV-455A", "doc", False), ("D2", "PCV-455A", "doc", False),
    ("B1", "PCV-455A", "doc", False), ("F1", "PCV-455A", "doc", False), ("PT-455", "PZR", "measurement", False),
]


def kg_svg():
    pos = {n[0]: (n[3], n[4]) for n in KG_NODES}
    o = ['<svg viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid meet" role="img" aria-label="지식그래프 로컬 보기(가상)">']
    seed = 7
    bg = []
    for _ in range(26):
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        x = 40 + seed % 920
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        y = 30 + seed % 540
        bg.append((x, y))
    for (x1, y1), (x2, y2) in zip(bg, bg[3:]):
        o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="kg-bg-e"/>')
    for x, y in bg:
        o.append(f'<circle cx="{x}" cy="{y}" r="4" class="kg-bg-n"/>')
    for a, b, rel, hl in KG_EDGES:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        if hl:
            o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="kg-hl"/>')
        o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="kg-e rel-{rel}"/>')
    for nid, label, kind, x, y in KG_NODES:
        if kind in ("doc", "basis", "failure"):
            w = 14 * len(label) * 0.62 + 24
            o.append(f'<rect x="{x - w / 2}" y="{y - 15}" width="{w}" height="30" rx="8" class="kg-k kind-{kind}"/>')
            o.append(f'<text x="{x}" y="{y + 5}" text-anchor="middle" class="lbl">{label}</text>')
        else:
            r = 22 if nid == "PCV-455A" else 15
            o.append(f'<circle cx="{x}" cy="{y}" r="{r}" class="kg-n kind-{kind}"/>')
            if nid == "PCV-455A":
                o.append(f'<circle cx="{x}" cy="{y}" r="30" class="sel-ring"/>')
            o.append(f'<text x="{x}" y="{y + r + 17}" text-anchor="middle" class="lbl">{label}</text>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------- 공통 조각
def chip(text, cls):
    return f'<span class="chip {cls}">{text}</span>'


RISK = {"ok": ("수용", "r-ok"), "cond": ("조건부", "r-cond"), "deny": ("불허", "r-deny")}


def risk_chip(level, n, proposed=False):
    name, cls = RISK[level]
    return f'<span class="risk {cls}{" prop" if proposed else ""}">위험 {n} · {name}{" (제안)" if proposed else ""}</span>'


STATUS = {"제안": "ai", "수정": "edit", "승인": "appr", "기각": "rej"}


def status_chip(s):
    label = {"제안": "제안 · AI 초안", "수정": "수정 · 사람", "승인": "승인", "기각": "기각"}[s]
    return chip(label, STATUS[s])


def kpis(items):
    out = []
    for label, value, tone in items:
        out.append(f'<div class="kpi {tone}"><span class="kpi-l">{label}</span><span class="kpi-v">{value}</span></div>')
    return f'<div class="kpis">{"".join(out)}</div>'


def panel(title, body, extra="", cls="", head_right=""):
    return (f'<section class="panel {cls}"><div class="panel-h"><span class="ph-t">{title}</span>{extra}'
            f'<span class="ph-r">{head_right}</span></div><div class="panel-b">{body}</div></section>')


# ---------------------------------------------------------------- 화면 본문
def screen_register():
    rows = [
        ("SRC-0007", "SNP-M-102_RCS-pressurizer.drawio", "SNP-M-102", "3", chip("등록 완료", "ok"), chip("추출 완료", "ok"), True),
        ("SRC-0008", "SNP-M-103_RCS-loop2.pdf", "SNP-M-103", "2", chip("등록 완료", "ok"), chip("추출 완료", "ok"), False),
        ("SRC-0009", "SNP-M-104_SI-accumulator.pdf", '<span class="unk">미확인</span>', '<span class="unk">미확인</span>', chip("보류", "warn"), '<span class="muted">추출 대기</span>', False),
        ("DOC-0002", "RCS-계통설명서.pdf", '<span class="muted">문서</span>', "—", chip("등록 완료", "ok"), chip("지식 추출 완료", "ok"), False),
        ("DOC-0003", "OP-RCS-02_운전절차.pdf", '<span class="muted">문서</span>', "—", chip("실패", "err"), '<span class="err-t">저장 후 해시 불일치</span>', False),
    ]
    trs = "".join(
        f'<tr class="{"sel" if s else ""}"><td class="mono">{a}</td><td>{b}</td><td{' class="mono"' if c.startswith("SNP") else ""}>{c}</td><td>{d}</td><td>{e}</td><td>{f}</td></tr>'
        for a, b, c, d, e, f, s in rows)
    table = (f'<table class="t"><thead><tr><th>자료 ID</th><th>원본</th><th>도면 번호</th><th>개정</th><th>등록</th><th>추출</th></tr></thead>'
             f'<tbody>{trs}</tbody></table>')
    left = panel("등록 자료", table, extra=chip("5건", "neutral"),
                 head_right='<input class="input" placeholder="자료 검색" aria-label="자료 검색">')

    fields = "".join(
        f'<div class="field"><label>{lab}</label><div class="frow"><input class="input" value="{val}" aria-label="{lab}">'
        f'{chip("자동 후보", "ai")}<button class="btn sm">후보 확정</button></div></div>'
        for lab, val in (("도면 번호", "SNP-M-105"), ("개정 번호", "1"), ("제목", "CVCS 유출 계통")))
    steps = "".join(
        f'<li class="{st}"><span class="dot"></span>{t}<span class="step-r">{r}</span></li>'
        for t, st, r in (("형식 확인", "done", "벡터 PDF"), ("해시 계산", "done", '<span class="mono">a91f…3c0e</span>'),
                         ("저장", "done", "원본 보관"), ("저장 후 해시 확인", "now", "진행 중"), ("첫 쪽 자동 추출", "todo", "대기")))
    right_body = (
        '<div class="drop"><div class="drop-t">draw.io 원본 또는 벡터 PDF를 여기에 놓으세요</div>'
        '<div class="muted">한 번에 1개 · .drawio .pdf · 같은 이름 SVG는 함께 등록</div>'
        '<button class="btn">파일 선택</button></div>'
        '<div class="file"><span class="ftype">PDF</span><div><b>SNP-M-105_CVCS-letdown.pdf</b>'
        '<div class="muted">벡터 PDF 3쪽 · 2.4 MB · 등록하면 첫 쪽을 자동 추출해 ② 도면에 표시</div></div></div>'
        f'<div class="sub-h">표제란 식별정보 <span class="muted">비우면 미확인으로 저장</span></div>{fields}'
        f'<div class="sub-h">등록 단계</div><ol class="steps">{steps}</ol>'
        '<div class="actions"><button class="btn primary">등록</button><button class="btn" disabled>추출 실행</button></div>')
    right = panel("새 자료 등록", right_body, cls="reg-new")
    return left + right


def screen_extract():
    toolbar = ('<div class="cv-tools"><input class="input" placeholder="태그 검색 (예: PCV-455A)" aria-label="태그 검색">'
               '<span class="toggles">' + "".join(f'<label class="tg"><input type="checkbox" checked> {t}</label>' for t in ("심볼", "배관·연결", "태그")) +
               '</span><span class="legend">' +
               "".join(f'<span class="lg"><i class="sw kind-{k}"></i>{t}</span>' for k, t in
                       (("equipment", "설비"), ("valve", "밸브"), ("instrument", "계기"))) +
               '<span class="lg"><i class="ln rel-phys"></i>물리 연결</span><span class="lg"><i class="ln dash"></i>신호</span>'
               '<span class="lg"><i class="ln dash unres"></i>미해결</span></span></div>')
    canvas = f'{toolbar}<div class="canvas">{pid_svg("extract")}</div><div class="zoom"><button class="btn sm">−</button><span class="mono">100%</span><button class="btn sm">+</button><button class="btn sm">맞춤</button></div>'
    left = panel("SNP-M-102 Rev.3 · RCS 가압기 계통", canvas, extra=chip("구조 검증 통과", "ok"), cls="cv-panel",
                 head_right='<span class="muted">원본 SRC-0007 · drawio</span>')
    props = "".join(f'<div class="kv"><span>{k}</span><b>{v}</b></div>' for k, v in (
        ("태그", '<span class="mono">PCV-455A</span>'), ("종류", "밸브 · 압력방출(PORV)"), ("원본 셀", '<span class="mono">cell-7f2a</span>'),
        ("구간", "S3 PORV 방출 (제안)"), ("정상 위치", '<span class="unk">미확인</span> <span class="muted">표제란·주석에 없음</span>')))
    links = "".join(f'<li><span class="mono">{a}</span><span class="muted">{b}</span></li>' for a, b in (
        ("MOV-8000A", "물리 연결 · 상류"), ("PRT", "물리 연결 · 하류"), ("PC-455A", "신호 · 제어 입력")))
    right = panel("선택한 객체", f'{props}<div class="sub-h">연결 3</div><ul class="links">{links}</ul>'
                  '<div class="actions"><button class="btn">지식그래프에서 보기</button></div>', cls="props")
    banner = ('<div class="banner warn"><b>미해결 관계 1개</b> TE-463 신호 대상이 도면에서 확인되지 않음. 도면 원본에서 연결을 확인하세요.'
              '<button class="btn sm">위치로 이동</button></div>')
    return banner, left + right


def screen_kg():
    kinds = [("equipment", "설비", 18), ("valve", "밸브", 41), ("instrument", "계기", 37), ("piping", "배관 요소", 22),
             ("doc", "문서 절", 19), ("basis", "설계기준", 6), ("failure", "고장모드", 5)]
    rels = [("phys", "물리 연결"), ("signal", "신호"), ("meas", "측정"), ("doc", "근거 문서")]
    filt = ('<input class="input full" placeholder="노드 검색" aria-label="노드 검색"><div class="sub-h">노드 종류</div>' +
            "".join(f'<label class="tg row"><input type="checkbox" checked><i class="sw kind-{k}"></i>{t}<span class="cnt">{n}</span></label>' for k, t, n in kinds) +
            '<div class="sub-h">관계</div>' +
            "".join(f'<label class="tg row"><input type="checkbox" checked><i class="ln rel-{k}"></i>{t}</label>' for k, t in rels) +
            '<div class="sub-h">표시</div><label class="tg row"><input type="checkbox"> 미확인·가설 노드</label>'
            '<label class="tg row"><input type="checkbox" checked> 계산 제외 노드 흐리게</label>')
    left = panel("필터", filt, cls="filters")
    cv = ('<div class="cv-tools"><span class="seg-ctl"><button class="on">로컬</button><button>전역</button></span>'
          '<span class="muted">표시 노드 12 · 관계 14 · 깊이 2</span><span class="legend"><span class="lg"><i class="ln hl"></i>AI 근거 경로</span></span></div>'
          f'<div class="canvas">{kg_svg()}</div><div class="cv-note muted">배치는 근거가 아님 · 노드 위치는 보기 편의용</div>')
    center = panel("지식그래프 · RCS 가압기", cv, extra=chip("kg v12 검증 통과", "ok"), cls="cv-panel")
    path = ('<div class="path"><span class="pn">PT-455</span><span class="pe">측정</span><span class="pn">PC-455A</span>'
            '<span class="pe">신호</span><span class="pn sel">PCV-455A</span><span class="pe">물리</span><span class="pn">PRT</span></div>')
    srcs = "".join(f'<li><b>{a}</b><span class="muted">{b}</span></li>' for a, b in (
        ("RCS 계통설명서 §4.3 가압기 압력제어", "DOC-0002 · 27쪽"), ("OP-RCS-02 §5.2 PORV 수동 조작", "DOC-0003 · 확인 필요"),
        ("설계기준: PORV 방출 용량", "DOC-0002 · 31쪽")))
    detail = (f'<div class="kv"><span>노드</span><b class="mono">PCV-455A</b></div><div class="kv"><span>종류</span><b>밸브 · PORV</b></div>'
              f'<div class="kv"><span>중심성(A1)</span><b>0.42 · 상위 5%</b></div><div class="sub-h">AI 근거 경로</div>{path}'
              f'<div class="sub-h">출처 문서 3</div><ul class="links docs">{srcs}</ul>'
              '<div class="banner warn compact">OP-RCS-02는 등록 실패 상태라 재확인 필요</div>'
              '<div class="actions"><button class="btn">도면에서 보기</button></div>')
    right = panel("PCV-455A 상세", detail, cls="props")
    return left + center + right


def screen_segments():
    left = panel("검토구간 제안 · SNP-M-102", f'<div class="canvas">{pid_svg("segment")}</div>', extra=chip("규칙 제안 · 사람 확정 필요", "ai"),
                 cls="cv-panel", head_right='<span class="muted">구간 색은 범례와 목록의 S 번호로 함께 구분</span>')
    seg_rows = "".join(
        f'<li class="seg-row{" sel" if sid == "S3" else ""}"><input type="checkbox"{" checked" if sid in ("S2", "S3") else ""} aria-label="{sid} 선택">'
        f'<span class="seg-sw seg{sid[1]}">{sid}</span><span class="seg-n">{name}</span>'
        f'<span class="muted">{n}개</span>{chip(st, "ok" if st == "확정" else "ai")}</li>'
        for sid, name, n, st in SEGMENTS)
    unc = "".join(f'<li><span class="mono">{a}</span><span class="muted">{b} · {c}</span><button class="btn sm">구간에 넣기</button></li>' for a, b, c in UNCOVERED)
    body = ('<div class="cover"><div class="cover-t"><b>19 / 22</b> 컴포넌트를 덮음 <span class="muted">86%</span></div>'
            '<div class="bar"><span style="width:86%"></span></div>'
            '<div class="cover-w">미포함 <b>3</b> · 모두 덮어야 확정할 수 있음</div></div>'
            '<div class="seg-tools"><button class="btn">병합 (2개 선택)</button><button class="btn">분할</button><button class="btn ghost">이름 바꾸기</button></div>'
            f'<ul class="seg-list">{seg_rows}</ul><div class="sub-h">미포함 컴포넌트 3</div><ul class="links unc">{unc}</ul>'
            '<div class="actions"><button class="btn primary" disabled>구간 확정</button><span class="muted">미포함 0이 되면 켜짐</span></div>')
    right = panel("구간 5", body, cls="props seg-side")
    return left + right


DEVIATIONS = [("유량", "없음"), ("유량", "많음"), ("역류", ""), ("압력", "높음"), ("압력", "낮음"), ("온도", "높음"), ("수위", "높음"), ("수위", "낮음")]
MATRIX = {
    "S1": [(1, "ok", 0), None, "x", (3, "cond", 1), (2, "cond", 2), (2, "cond", 0), (2, "ok", 1), (3, "deny", 2)],
    "S2": [(2, "cond", 1), (1, "ok", 0), (1, "ok", 1), (2, "cond", 1), (1, "ok", 0), "x", "x", "x"],
    "S3": [(1, "ok", 0), (2, "cond", 1), "x", (4, "cond", 2), (2, "cond", 1), (1, "ok", 0), "x", "x"],
    "S4": [(1, "cond", 1), (1, "ok", 0), (1, "ok", 1), (2, "cond", 0), "…", "…", "x", "x"],
    "S5": [(1, "ok", 0), (1, "ok", 0), (2, "cond", 1), (1, "ok", 0), (1, "ok", 0), (1, "cond", 0), "x", "x"],
}


def screen_matrix():
    head = "".join(f'<th><span>{a}</span><span>{b}</span></th>' for a, b in DEVIATIONS)
    rows = []
    for sid, name, *_ in SEGMENTS:
        cells = []
        for j, v in enumerate(MATRIX[sid]):
            sel = sid == "S3" and j == 3
            if v == "x":
                cells.append('<td class="mx na"><span>제외</span></td>')
            elif v == "…":
                cells.append('<td class="mx pending"><span>분석 전</span></td>')
            elif v is None:
                cells.append('<td class="mx none"><span>0건</span></td>')
            else:
                n, lvl, un = v
                un_t = f'<span class="mx-u">미검토 {un}</span>' if un else '<span class="mx-u done">완료</span>'
                cells.append(f'<td class="mx {RISK[lvl][1]}{" sel" if sel else ""}"><b>{n}</b><span class="mx-r">{RISK[lvl][0]}</span>{un_t}</td>')
        rows.append(f'<tr><th class="rh"><span class="seg-sw seg{sid[1]}">{sid}</span>{name}</th>{"".join(cells)}</tr>')
    legend = ('<div class="mx-legend"><span class="muted">칸 = 시나리오 수 · 최고 위험 등급 · 미검토 수(완료 = 모두 검토)</span>'
              f'{risk_chip("ok", 2)}{risk_chip("cond", 4)}{risk_chip("deny", 5)}</div>')
    mtx = f'<div class="mx-wrap"><table class="matrix"><thead><tr><th class="rh">구간 \\ 편차</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>{legend}'
    left = panel("구간 × 편차 요약", mtx, extra=chip("AI 일괄 분석 31건 · 모두 초안", "ai"), cls="mx-panel")

    def ws(no, st, risk, cause, cons, guards, rec, ev=None, note=""):
        evid = ""
        if ev:
            evid = ('<div class="evid"><div class="evid-h">AI 근거 <span class="muted">지식그래프 경로 · 출처 문서</span></div>'
                    '<div class="path"><span class="pn">PZR</span><span class="pe">물리</span><span class="pn">MOV-8000A</span>'
                    '<span class="pe">물리</span><span class="pn sel">PCV-455A</span><span class="pe">물리</span><span class="pn">PRT</span></div>'
                    '<ul class="links docs"><li><b>RCS 계통설명서 §4.3</b><span class="muted">DOC-0002 · 27쪽</span></li>'
                    '<li><b>OP-RCS-02 §5.2</b><span class="muted">DOC-0003 · 재확인 필요</span></li></ul></div>')
        acts = ('<div class="actions"><button class="btn primary sm">승인</button><button class="btn sm">수정</button>'
                '<button class="btn sm">기각</button></div>') if st == "제안" else ""
        cls = {"제안": "ai", "수정": "human edited", "승인": "human", "기각": "rej"}[st]
        if st == "기각":
            return (f'<article class="sc {cls}"><header><b>#{no}</b>{status_chip(st)}<span class="sc-one">{cause}</span></header>'
                    f'<div class="muted rej-why">{note}</div></article>')
        dl = "".join(f'<div class="ws-k">{k}</div><div class="ws-v">{v}</div>' for k, v in
                     (("원인", cause), ("결과", cons), ("보호수단", guards), ("권고", rec)))
        return (f'<article class="sc {cls}"><header><b>#{no}</b>{status_chip(st)}{risk}{f"<span class=muted>{note}</span>" if note else ""}</header>'
                f'<div class="ws">{dl}</div>{evid}{acts}</article>')

    cards = (
        ws(1, "제안", risk_chip("cond", 4, proposed=True),
           "PORV 차단밸브 MOV-8000A가 닫힌 채 운전되어 PCV-455A 방출 경로가 막힘",
           "가압기 압력이 올라도 PORV로 낮추지 못해 안전밸브 RV-8010A~C 개방 요구가 늘고 PRT 압력이 상승",
           "RV-8010A/B/C 안전밸브 · 가압기 압력 높음 원자로 정지 신호",
           "MOV-8000A 열림 위치가 주제어실 경보로 확인되는지 검토", ev=True)
        + ws(2, "수정", risk_chip("cond", 3), "PT-455 지시가 낮게 고장 나 PC-455A가 PORV 개방 신호를 내지 않음",
             "압력 상승을 늦게 감지해 안전밸브가 먼저 열림", "PT-456·PT-457 다중 채널(2/3 논리) · 압력 높음 경보",
             "채널 간 편차 경보 설정값 확인", note="권고 문구를 검토자가 수정함")
        + ws(3, "승인", risk_chip("ok", 2), "살수 제어 실패와 히터 연속 가동이 겹침(S1 연계)", "가압기 압력 상승",
             "PORV 자동 개방 · 살수밸브 수동 조작", "추가 권고 없음. 기존 보호수단 적정")
        + ws(4, "기각", "", "PRT 배수밸브 V-8030 열림", "", "", "", note="기각 사유: 이 구간의 압력 높음과 관련 없음(검토자)")
    )
    head_ws = ('<div class="ws-head"><div class="ws-title"><span class="seg-sw seg3">S3</span><b>PORV 방출</b><span class="x">×</span><b>압력 높음</b></div>'
               '<div class="muted">설계 의도: 가압기 압력이 설정값을 넘으면 PCV-455A가 열려 PRT로 방출</div>'
               '<div class="ws-tools"><button class="btn sm">도면에서 보기</button><button class="btn sm">경로 보기</button>'
               '<span class="muted">시나리오 4 · 미검토 2</span></div></div>')
    right = panel("상세 워크시트", head_ws + cards, cls="ws-panel")
    return left + right


SCREEN_SPEC = {
    "1-자료등록": dict(title="자료 등록", sub="도면(drawio·PDF)과 문서(PDF)를 등록하고 추출을 실행합니다",
                    actions='<button class="btn">폴더 열기</button><button class="btn primary">파일 등록</button>',
                    kpis=[("등록 자료", "5", ""), ("추출 완료", "3", "ok"), ("보류", "1", "warn"), ("실패", "1", "err")],
                    body=screen_register, cls="reg"),
    "2-도면추출": dict(title="도면 추출", sub="SNP-M-102 Rev.3 · 추출 결과를 원본 도면 위에서 대조합니다",
                    actions='<button class="btn">추출 결과 선택</button><button class="btn primary">지식그래프 만들기</button>',
                    kpis=[("노드", "22", ""), ("관계", "26", ""), ("미해결", "1", "err"), ("미확인 속성", "2", "warn")],
                    body=screen_extract, cls="ext"),
    "3-지식그래프": dict(title="지식그래프", sub="도면 추출 결과와 문서 지식을 한 그래프에서 탐색합니다",
                     actions='<button class="btn">버전 v12</button><button class="btn primary">구간 제안 만들기</button>',
                     kpis=[("지식 노드", "148", ""), ("관계", "312", ""), ("출처 문서", "6", ""), ("재확인 필요", "4", "warn")],
                     body=screen_kg, cls="kg"),
    "4-검토구간": dict(title="검토구간", sub="자동 제안된 구간을 병합·분할해 모든 컴포넌트를 덮도록 확정합니다",
                    actions='<button class="btn">다시 제안</button><button class="btn primary" disabled>구간 확정</button>',
                    kpis=[("컴포넌트", "22", ""), ("덮음", "19 · 86%", "ok"), ("미포함", "3", "warn"), ("구간", "5", "")],
                    body=screen_segments, cls="seg"),
    "5-요약행렬": dict(title="분석 결과", sub="구간 × 편차 요약에서 칸을 눌러 워크시트를 검토합니다. AI 결과는 모두 초안입니다",
                    actions='<button class="btn">권고 추적</button><button class="btn primary">Excel 내보내기</button>',
                    kpis=[("구간", "5", ""), ("시나리오", "31", ""), ("미검토", "12", "warn"), ("불허 위험", "1", "err")],
                    body=screen_matrix, cls="mat"),
}


# ---------------------------------------------------------------- 셸(안마다 다름)
def shell_a(idx, inner):
    steps = []
    for i, (_, label, _) in enumerate(SCREENS):
        st = "done" if i < idx else ("now" if i == idx else "todo")
        mark = "✓" if i < idx else str(i + 1)
        steps.append(f'<a class="step {st}" href="{SCREENS[i][0]}.html"><span class="num">{mark}</span>{label}</a>')
    sep = '<span class="step-sep"></span>'
    return (f'<div class="app shell-a"><header class="topbar"><div class="brand"><span class="logo">H</span><b>HAZOP</b>'
            f'<span class="crumb">SNP-M-102 · RCS 가압기</span></div><nav class="stepper" aria-label="단계">{sep.join(steps)}</nav>'
            f'<div class="user"><span class="avatar">김</span><span>검토자 김OO</span></div></header>'
            f'<main class="main">{inner}</main>{statusbar()}</div>')


def shell_b(idx, inner):
    rail = "".join(
        f'<a class="rail-i{" on" if i == idx else ""}" href="{s[0]}.html" aria-label="{s[1]}"><b>{i + 1}</b><span>{s[2]}</span></a>'
        for i, s in enumerate(SCREENS))
    tree = ('<div class="ex-h">탐색기</div><ul class="tree">'
            '<li class="grp">자료</li><li>SNP-M-102.drawio</li><li>SNP-M-103.pdf</li><li class="warn-t">SNP-M-104.pdf · 보류</li>'
            '<li class="grp">지식그래프</li><li>RCS 가압기 · v12</li>'
            '<li class="grp">검토구간</li>' +
            "".join(f'<li class="{"on" if s[0] == "S3" else ""}"><span class="seg-sw seg{s[0][1]}">{s[0]}</span>{s[1]}</li>' for s in SEGMENTS) +
            '<li class="grp">권고</li><li>열린 권고 7</li></ul>')
    tabs = "".join(f'<span class="tab{" on" if i == idx else ""}">{s[1]}{"<i>×</i>" if i == idx else ""}</span>'
                   for i, s in enumerate(SCREENS) if i in (idx, (idx + 1) % 5))
    return (f'<div class="app shell-b"><header class="titlebar"><b class="logo">HAZOP</b>'
            '<span class="menu">파일</span><span class="menu">편집</span><span class="menu">보기</span><span class="menu">도움말</span>'
            '<span class="crumb">SNP-M-102 / RCS 가압기 / 실행 run-1106-a</span><span class="user">검토자 김OO</span></header>'
            f'<nav class="rail" aria-label="단계">{rail}</nav><aside class="explorer">{tree}</aside>'
            f'<section class="work"><div class="tabs">{tabs}</div><main class="main">{inner}</main></section>{statusbar()}</div>')


def shell_c(idx, inner):
    counts = ["5", "22", "148", "3", "12"]
    nav = "".join(
        f'<a class="nav-i{" on" if i == idx else ""}" href="{s[0]}.html"><span class="num">{i + 1}</span>{s[1]}<span class="cnt">{counts[i]}</span></a>'
        for i, s in enumerate(SCREENS))
    return (f'<div class="app shell-c"><aside class="sidenav"><div class="brand"><span class="logo">H</span><b>HAZOP</b></div>'
            '<div class="proj"><span class="muted">프로젝트</span><b>SNP-M-102</b><span class="muted">RCS 가압기 · Rev.3</span></div>'
            f'<nav aria-label="단계">{nav}</nav><div class="side-foot"><span class="avatar">김</span><div><b>김OO</b><span class="muted">검토자</span></div></div></aside>'
            f'<section class="work"><main class="main">{inner}</main>{statusbar()}</section></div>')


def statusbar():
    return ('<footer class="statusbar"><span class="chip ok">형식·참조 검증 통과 — 보류 없음을 뜻하지 않음</span>'
            '<span>최근 저장 14:32 KST</span><span class="sb-r">가상 샘플 데이터 · 실제 설계값 아님</span></footer>')


SHELLS = {"A": shell_a, "B": shell_b, "C": shell_c}


# ---------------------------------------------------------------- CSS
BASE_CSS = """
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{font-family:var(--font);font-size:var(--fs);color:var(--ink);background:var(--bg);overflow:hidden;line-height:1.45;-webkit-font-smoothing:antialiased;font-feature-settings:"tnum"}
a{color:inherit;text-decoration:none}
.mono{font-family:var(--mono);font-size:.94em}
.muted{color:var(--muted)}
.unk{color:var(--warn-ink);font-weight:600}
.err-t{color:var(--err-ink);font-weight:600}
.warn-t{color:var(--warn-ink)}
.app{height:100vh;display:grid;min-width:0}
.main{min-height:0;min-width:0;display:flex;flex-direction:column;gap:var(--gap);padding:var(--pad);overflow:hidden}
.page-head{display:flex;align-items:flex-end;gap:16px;flex-wrap:nowrap}
.page-head .ph-txt{min-width:0;flex:1}
.page-head h1{font-size:var(--fs-h1);margin:0;font-weight:700;letter-spacing:-.015em}
.page-head .sub{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.page-head .acts{display:flex;gap:8px;flex-shrink:0}
.kpis{display:flex;gap:var(--gap)}
.kpi{display:flex;flex-direction:column}
.kpi-l{color:var(--muted);font-size:var(--fs-sm)}
.kpi-v{font-weight:700}
.kpi.warn .kpi-v{color:var(--warn-ink)} .kpi.err .kpi-v{color:var(--err-ink)} .kpi.ok .kpi-v{color:var(--ok-ink)}
.body{flex:1;min-height:0;display:grid;gap:var(--gap)}
.body.reg{grid-template-columns:minmax(0,1.3fr) minmax(380px,1fr)}
.body.ext{grid-template-columns:minmax(0,1fr) 300px}
.body.kg{grid-template-columns:210px minmax(0,1fr) 300px}
.body.seg{grid-template-columns:minmax(0,1fr) 360px}
.body.mat{grid-template-columns:minmax(0,1fr) minmax(460px,.9fr)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);min-height:0;min-width:0;display:flex;flex-direction:column;overflow:hidden;box-shadow:var(--shadow)}
.panel-h{display:flex;align-items:center;gap:8px;padding:var(--ph-pad);border-bottom:1px solid var(--line);font-weight:650;white-space:nowrap}
.panel-h .ph-r{margin-left:auto;font-weight:400;display:flex;align-items:center;gap:8px;min-width:0;overflow:hidden}
.panel-b{padding:var(--pb-pad);overflow:auto;min-height:0;flex:1;display:flex;flex-direction:column;gap:calc(var(--gap) * .75)}
.cv-panel .panel-b{padding:0;gap:0;position:relative}
.sub-h{font-weight:650;font-size:var(--fs-sm);color:var(--ink-2);display:flex;gap:8px;align-items:baseline;margin-top:4px}
table.t{width:100%;border-collapse:collapse}
.t th{text-align:left;font-weight:600;color:var(--muted);font-size:var(--fs-sm);padding:var(--cell-y) var(--cell-x);border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--surface);white-space:nowrap}
.t td{padding:var(--cell-y) var(--cell-x);border-bottom:1px solid var(--line);white-space:nowrap}
.t td:nth-child(2){white-space:normal;word-break:break-all;min-width:9em}
.t td:last-child{white-space:normal}
.t tr.sel td{background:var(--ui-weak);color:var(--ui-ink)}
.t tr.sel td:first-child{box-shadow:inset 3px 0 0 var(--ui)}
.panel-b:has(> table.t){padding:0}
.chip{display:inline-flex;align-items:center;gap:4px;padding:1px 8px;border-radius:var(--r-chip);font-size:var(--fs-sm);font-weight:600;border:1px solid transparent;white-space:nowrap;line-height:1.55}
.chip.ok{background:var(--ok-bg);color:var(--ok-ink)}
.chip.warn{background:var(--warn-bg);color:var(--warn-ink);border-color:var(--warn-line)}
.chip.err{background:var(--err-bg);color:var(--err-ink);border-color:var(--err-line)}
.chip.neutral{background:var(--surface-2);color:var(--ink-2);border-color:var(--line)}
.chip.ai{background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px);color:var(--ai-ink);border:1px dashed var(--ai-line)}
.chip.edit{background:var(--ui-weak);color:var(--ui-ink);border-color:var(--ui)}
.chip.appr{background:var(--ok);color:var(--on-ok)}
.chip.rej{background:var(--surface-2);color:var(--muted);border-color:var(--line-strong)}
.risk{display:inline-flex;align-items:center;padding:1px 8px;border-radius:var(--r-chip);font-size:var(--fs-sm);font-weight:700;white-space:nowrap;border:1.5px solid transparent;line-height:1.5}
.risk.r-ok{background:var(--risk-ok-bg);color:var(--risk-ok-ink);border-color:var(--risk-ok-line)}
.risk.r-cond{background:var(--risk-cond-bg);color:var(--risk-cond-ink);border-color:var(--risk-cond-line)}
.risk.r-deny{background:var(--risk-deny-bg);color:var(--risk-deny-ink);border-color:var(--risk-deny-bg)}
.risk.prop{background:var(--surface);color:var(--ink);border-style:dashed}
.btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);border-radius:var(--r-btn);padding:var(--btn-pad);font:inherit;font-weight:600;white-space:nowrap;cursor:pointer}
.btn.sm{padding:1px 8px;font-size:var(--fs-sm)}
.btn.primary{background:var(--ui);border-color:var(--ui);color:var(--on-fill)}
.btn.ghost{border-color:transparent;background:transparent;color:var(--ui)}
.btn[disabled]{opacity:.55;cursor:not-allowed}
.input{border:1px solid var(--line-strong);border-radius:var(--r-input);padding:var(--inp-pad);background:var(--surface);color:var(--ink);font:inherit;min-width:0}
.input::placeholder{color:var(--muted)}
.input.full{width:100%}
.banner{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:var(--r-btn);border:1px solid}
.banner .btn{margin-left:auto}
.banner.warn{background:var(--warn-bg);color:var(--warn-ink);border-color:var(--warn-line)}
.banner.compact{padding:6px 10px;font-size:var(--fs-sm)}
.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kv{display:flex;justify-content:space-between;gap:12px;padding:4px 0;border-bottom:1px dashed var(--line)}
.kv span{color:var(--muted);white-space:nowrap}
.kv b{font-weight:600;text-align:right}
ul.links{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
ul.links li{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:4px 0}
ul.links.docs li{flex-direction:column;align-items:flex-start;gap:0}
ul.links.unc li .btn{margin-left:auto}
/* 등록 */
.drop{border:2px dashed var(--line-strong);border-radius:var(--radius);padding:18px;display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;background:var(--surface-2)}
.drop-t{font-weight:650}
.file{display:flex;gap:12px;align-items:center;border:1px solid var(--line);border-radius:var(--r-btn);padding:10px 12px}
.ftype{font-weight:800;font-size:var(--fs-sm);padding:6px 8px;border-radius:6px;background:var(--err-bg);color:var(--err-ink)}
.field{display:flex;flex-direction:column;gap:3px}
.field label{font-size:var(--fs-sm);color:var(--muted)}
.frow{display:flex;gap:8px;align-items:center}
.frow .input{flex:1}
ol.steps{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
ol.steps li{display:flex;align-items:center;gap:10px}
ol.steps .dot{width:10px;height:10px;border-radius:50%;border:2px solid var(--line-strong);flex-shrink:0}
ol.steps .done .dot{background:var(--ok);border-color:var(--ok)}
ol.steps .now .dot{border-color:var(--ui);box-shadow:0 0 0 3px var(--ui-weak)}
ol.steps .now{color:var(--ui-ink);font-weight:650}
ol.steps .todo{color:var(--muted)}
.step-r{margin-left:auto;color:var(--muted);font-size:var(--fs-sm)}
/* 도면·그래프 */
.cv-tools{display:flex;align-items:center;gap:12px;padding:8px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.cv-tools .input{width:200px}
.toggles{display:flex;gap:10px}
.tg{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.tg input{accent-color:var(--ui);margin:0}
.tg.row{display:flex;padding:2px 0}
.tg .cnt{margin-left:auto;color:var(--muted);font-size:var(--fs-sm)}
.legend{display:flex;gap:10px;margin-left:auto;flex-wrap:wrap;font-size:var(--fs-sm);color:var(--ink-2)}
.lg{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
i.sw{width:11px;height:11px;border-radius:3px;display:inline-block;border:2px solid currentColor;flex-shrink:0}
i.ln{width:18px;height:0;border-top:3px solid var(--r-physical);display:inline-block;flex-shrink:0}
i.ln.dash{border-top:2px dashed var(--draw-sig)} i.ln.unres{border-top-color:var(--r-unresolved)}
i.ln.rel-signal{border-top:2px dashed var(--r-signal)} i.ln.rel-meas{border-top:2px dashed var(--r-measurement)} i.ln.rel-doc{border-top:2px dotted var(--k-doc)}
i.ln.hl{border-top:5px solid var(--hl-path)}
i.kind-equipment{color:var(--k-equipment)} i.kind-valve{color:var(--k-valve)} i.kind-instrument{color:var(--k-instrument)} i.kind-piping{color:var(--k-piping)}
i.kind-doc{color:var(--k-doc)} i.kind-basis{color:var(--k-basis)} i.kind-failure{color:var(--k-failure)}
.canvas{background:var(--canvas);flex:1;min-height:0;position:relative}
.canvas svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.zoom{position:absolute;left:12px;bottom:12px;display:flex;gap:6px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-btn);padding:4px 6px}
.cv-note{position:absolute;right:12px;bottom:10px;font-size:var(--fs-sm)}
.pipe{fill:none;stroke:var(--draw-line);stroke-width:2.5;stroke-linejoin:round}
.sig{fill:none;stroke:var(--draw-sig);stroke-width:1.6;stroke-dasharray:5 4}
.sig.rel-unres{stroke:var(--r-unresolved);stroke-width:2}
.eq{fill:var(--canvas);stroke:var(--draw-line);stroke-width:2}
.vlv{fill:var(--canvas);stroke:var(--draw-line);stroke-width:2}
.inst{fill:var(--canvas);stroke:var(--draw-line);stroke-width:2}
.lbl{fill:var(--draw-ink);font-family:var(--font);font-size:14px;font-weight:600}
.lbl.small{font-size:12px;font-weight:500;fill:var(--muted)}
.lbl.tag{font-family:var(--mono);font-size:12.5px}
.lbl.it{font-size:9.5px;font-family:var(--mono);font-weight:700}
.kind-equipment.eq,.kind-equipment.kg-n{stroke:var(--k-equipment);stroke-width:2.5}
.kind-valve.vlv{fill:var(--k-valve);stroke:var(--k-valve)}
.kind-instrument.inst,.kind-instrument.kg-n{stroke:var(--k-instrument);stroke-width:2.5}
.kg-n.kind-valve{fill:var(--k-valve);stroke:var(--k-valve)}
.kg-n{fill:var(--canvas);stroke-width:2.5}
.kg-k{fill:var(--canvas);stroke-width:2}
.kg-k.kind-doc{stroke:var(--k-doc)} .kg-k.kind-basis{stroke:var(--k-basis)} .kg-k.kind-failure{stroke:var(--k-failure);stroke-dasharray:4 3}
.kg-e{stroke-width:1.8}
.kg-e.rel-physical{stroke:var(--r-physical)} .kg-e.rel-signal{stroke:var(--r-signal);stroke-dasharray:6 4}
.kg-e.rel-measurement{stroke:var(--r-measurement);stroke-dasharray:6 4} .kg-e.rel-doc{stroke:var(--k-doc);stroke-dasharray:2 4}
.kg-hl{stroke:var(--hl-path);stroke-width:9;stroke-linecap:round;opacity:.9}
.kg-bg-n{fill:var(--line-strong);opacity:.35} .kg-bg-e{stroke:var(--line-strong);opacity:.2;stroke-width:1}
.sel-ring{fill:none;stroke:var(--ui);stroke-width:3}
.seg-under{fill:none;stroke-width:16;stroke-linejoin:round;opacity:.16}
.seg-pipe{stroke-width:4}
.seg-pipe.sel{stroke-width:6}
.seg1{stroke:var(--seg1)} .seg2{stroke:var(--seg2)} .seg3{stroke:var(--seg3)} .seg4{stroke:var(--seg4)} .seg5{stroke:var(--seg5)}
.seg-stroke{stroke-width:3}
.vlv.seg-stroke{fill:var(--canvas)}
.uncov{stroke:var(--draw-sig);stroke-dasharray:3 3}
.uncov-ring{fill:none;stroke:var(--warn-line);stroke-width:2.5;stroke-dasharray:5 4}
.uncov-t{fill:var(--warn-ink);font-weight:700}
.seg-pill{stroke:none}
.seg-pill.seg1{fill:var(--seg1)} .seg-pill.seg2{fill:var(--seg2)} .seg-pill.seg3{fill:var(--seg3)} .seg-pill.seg4{fill:var(--seg4)} .seg-pill.seg5{fill:var(--seg5)}
.seg-pill-t{fill:var(--on-seg);font-family:var(--mono);font-size:12px;font-weight:800}
.seg-sw{display:inline-flex;align-items:center;justify-content:center;min-width:28px;padding:0 5px;border-radius:5px;font-family:var(--mono);font-size:var(--fs-sm);font-weight:800;color:var(--on-seg);flex-shrink:0}
.seg-sw.seg1{background:var(--seg1)} .seg-sw.seg2{background:var(--seg2)} .seg-sw.seg3{background:var(--seg3)} .seg-sw.seg4{background:var(--seg4)} .seg-sw.seg5{background:var(--seg5)}
.seg-ctl{display:inline-flex;border:1px solid var(--line-strong);border-radius:var(--r-btn);overflow:hidden}
.seg-ctl button{font:inherit;border:0;background:var(--surface);color:var(--ink);padding:2px 12px;font-weight:600}
.seg-ctl button.on{background:var(--ui);color:var(--on-fill)}
.path{display:flex;flex-wrap:wrap;align-items:center;gap:4px}
.pn{font-family:var(--mono);font-size:var(--fs-sm);font-weight:700;padding:1px 6px;border-radius:5px;border:1.5px solid var(--hl-path);background:var(--surface)}
.pn.sel{border-color:var(--ui);color:var(--ui-ink);background:var(--ui-weak)}
.pe{font-size:var(--fs-sm);color:var(--muted)}
.pe::before{content:"→ "}
/* 구간 */
.cover{display:flex;flex-direction:column;gap:6px}
.bar{height:8px;border-radius:99px;background:var(--surface-2);border:1px solid var(--line-strong);overflow:hidden}
.bar span{display:block;height:100%;background:var(--ok)}
.cover-w{color:var(--warn-ink);font-weight:600}
.seg-tools{display:flex;gap:8px;flex-wrap:wrap}
ul.seg-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
.seg-row{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:var(--r-btn);border:1px solid transparent}
.seg-row.sel{background:var(--ui-weak);border-color:var(--ui)}
.seg-row .seg-n{flex:1;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seg-row input{accent-color:var(--ui);margin:0}
/* 행렬 */
.mx-wrap{overflow:auto}
table.matrix{border-collapse:separate;border-spacing:3px;width:100%;table-layout:fixed}
.matrix th{font-size:var(--fs-sm);font-weight:650;color:var(--ink-2);padding:2px}
.matrix thead th span{display:block;line-height:1.25}
.matrix thead th span+span{color:var(--muted);font-weight:500}
.matrix th.rh{text-align:left;white-space:nowrap;width:138px;display:table-cell}
.matrix tbody th.rh{font-weight:600;color:var(--ink)}
.matrix th.rh .seg-sw{margin-right:6px}
.mx{text-align:center;border-radius:6px;padding:4px 2px;line-height:1.2;border:1.5px solid transparent;height:58px;vertical-align:middle}
.mx b{display:block;font-size:1.15em}
.mx span{display:block;font-size:11px;white-space:nowrap}
.mx-r{font-weight:700}
.mx.r-ok{background:var(--risk-ok-bg);color:var(--risk-ok-ink);border-color:var(--risk-ok-line)}
.mx.r-cond{background:var(--risk-cond-bg);color:var(--risk-cond-ink);border-color:var(--risk-cond-line)}
.mx.r-deny{background:var(--risk-deny-bg);color:var(--risk-deny-ink)}
.mx.na{background:transparent;color:var(--muted);border:1px dashed var(--line)}
.mx.pending{background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px);color:var(--ai-ink);border:1px dashed var(--ai-line)}
.mx.none{background:var(--surface-2);color:var(--muted)}
.mx.sel{outline:3px solid var(--ui);outline-offset:1px}
.mx-u.done{opacity:.85}
.mx-legend{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:4px}
/* 워크시트 */
.ws-head{display:flex;flex-direction:column;gap:4px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.ws-title{display:flex;gap:8px;align-items:center;font-size:1.08em}
.ws-title .x{color:var(--muted)}
.ws-tools{display:flex;gap:8px;align-items:center}
.ws-tools .muted{margin-left:auto}
.sc{border-radius:var(--r-btn);padding:10px 12px;display:flex;flex-direction:column;gap:8px}
.sc header{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sc.ai{border:1.5px dashed var(--ai-line);background:linear-gradient(var(--surface),var(--surface)) padding-box}
.sc.ai header{margin:-10px -12px 0;padding:6px 12px;background:repeating-linear-gradient(135deg,var(--ai-a) 0 6px,var(--ai-b) 6px 12px);border-radius:var(--r-btn) var(--r-btn) 0 0}
.sc.human{border:1.5px solid var(--ink)}
.sc.edited{border-color:var(--ui)}
.sc.rej{border:1px solid var(--line);background:var(--surface-2);padding:6px 12px}
.sc-one{color:var(--muted)}
.rej-why{font-size:var(--fs-sm)}
.ws{display:grid;grid-template-columns:72px 1fr;gap:4px 10px}
.ws-k{color:var(--muted);font-size:var(--fs-sm);font-weight:600;padding-top:1px}
.evid{border-top:1px dashed var(--line);padding-top:8px;display:flex;flex-direction:column;gap:6px}
.evid-h{font-weight:650;font-size:var(--fs-sm);display:flex;gap:8px}
/* 상태줄 */
.statusbar{display:flex;align-items:center;gap:16px;padding:0 16px;font-size:var(--fs-sm);color:var(--muted);border-top:1px solid var(--line);background:var(--surface);white-space:nowrap;overflow:hidden}
.sb-r{margin-left:auto}
.statusbar .chip{line-height:1.3}
"""

SHELL_CSS = {
    "A": """
.shell-a{grid-template-rows:60px minmax(0,1fr) 30px}
.topbar{display:flex;align-items:center;gap:24px;padding:0 24px;background:var(--nav-bg);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;white-space:nowrap;min-width:0}
.brand .crumb{color:var(--muted);overflow:hidden;text-overflow:ellipsis}
.logo{width:28px;height:28px;border-radius:8px;background:var(--ui);color:var(--on-fill);display:grid;place-items:center;font-weight:800}
.stepper{display:flex;align-items:center;gap:8px;margin:0 auto}
.step{display:flex;align-items:center;gap:8px;white-space:nowrap;color:var(--muted);font-weight:600;padding:6px 12px 6px 6px;border-radius:999px}
.step .num{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;border:1.5px solid var(--line-strong);font-size:12px}
.step.done{color:var(--ink-2)} .step.done .num{background:var(--ok-bg);color:var(--ok-ink);border-color:var(--ok)}
.step.now{background:var(--ui-weak);color:var(--ui-ink)} .step.now .num{background:var(--ui);border-color:var(--ui);color:var(--on-fill)}
.step-sep{width:20px;height:1.5px;background:var(--line-strong)}
.user{display:flex;align-items:center;gap:8px;white-space:nowrap;color:var(--ink-2)}
.avatar{width:28px;height:28px;border-radius:50%;background:var(--surface-2);border:1px solid var(--line-strong);display:grid;place-items:center;font-weight:700}
.kpis .kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px 16px;min-width:130px;box-shadow:var(--shadow)}
.kpi-v{font-size:20px;letter-spacing:-.02em}
.page-head .sub{margin-top:4px}
@media (max-width:1500px){.brand .crumb{display:none}.step{padding:6px 10px 6px 6px}.step-sep{width:12px}}
""",
    "B": """
.shell-b{grid-template-columns:52px 224px minmax(0,1fr);grid-template-rows:34px minmax(0,1fr) 24px}
.titlebar{grid-column:1/-1;display:flex;align-items:center;gap:4px;padding:0 10px;background:var(--nav-bg);color:var(--nav-ink);font-size:12px}
.titlebar .logo{margin-right:12px;letter-spacing:.06em}
.titlebar .menu{padding:3px 8px;border-radius:3px;color:var(--nav-ink)}
.titlebar .crumb{margin:0 auto;color:var(--nav-muted);font-family:var(--mono)}
.titlebar .user{color:var(--nav-muted)}
.rail{background:var(--nav-bg);display:flex;flex-direction:column;gap:2px;padding:6px 4px;border-top:1px solid #000}
.rail-i{display:flex;flex-direction:column;align-items:center;gap:1px;padding:6px 0;border-radius:4px;color:var(--nav-muted);border-left:2px solid transparent}
.rail-i b{font-size:14px;font-family:var(--mono)}
.rail-i span{font-size:11px}
.rail-i.on{background:var(--nav-active-bg);color:var(--nav-active-ink);border-left-color:var(--ui)}
.explorer{background:var(--surface-2);border-right:1px solid var(--line);overflow:auto;font-size:12px}
.ex-h{padding:7px 10px;font-weight:700;color:var(--muted);font-size:11.5px;border-bottom:1px solid var(--line)}
ul.tree{list-style:none;margin:0;padding:4px 0}
ul.tree li{padding:3px 10px 3px 22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;gap:6px;align-items:center}
ul.tree li.grp{padding-left:10px;font-weight:700;color:var(--ink-2);margin-top:6px}
ul.tree li.grp::before{content:"▾";color:var(--muted)}
ul.tree li.on{background:var(--ui-weak);color:var(--ui-ink);box-shadow:inset 2px 0 0 var(--ui)}
ul.tree .seg-sw{min-width:24px;font-size:10.5px;padding:0 3px}
.work{display:flex;flex-direction:column;min-width:0;min-height:0}
.tabs{display:flex;background:var(--surface-2);border-bottom:1px solid var(--line);height:30px;flex-shrink:0}
.tab{display:flex;align-items:center;gap:10px;padding:0 14px;border-right:1px solid var(--line);color:var(--muted);font-size:12px}
.tab.on{background:var(--surface);color:var(--ink);box-shadow:inset 0 2px 0 var(--ui);font-weight:600}
.tab i{font-style:normal;color:var(--muted)}
.statusbar{grid-column:1/-1;background:var(--nav-bg);color:var(--nav-muted);border-top:0;padding:0 10px;font-size:11.5px}
.statusbar .chip{font-size:11px;padding:0 6px}
.main{gap:var(--gap);flex:1}
.page-head{align-items:center;gap:10px}
.page-head h1{font-size:14px}
.page-head .ph-txt{display:flex;gap:10px;align-items:baseline}
.page-head .sub{font-size:12px}
.kpis{gap:0;border:1px solid var(--line);background:var(--surface);border-radius:4px;align-self:flex-start}
.kpis .kpi{flex-direction:row;gap:6px;align-items:baseline;padding:3px 12px;border-left:1px solid var(--line)}
.kpis .kpi:first-child{border-left:0}
.kpi-v{font-family:var(--mono)}
.panel-h{background:var(--surface-2);font-size:12px;color:var(--ink-2);min-height:28px}
.panel{border-color:var(--line)}
.cv-tools{padding:4px 8px;gap:8px}
.cv-tools .input{width:180px}
.sc{padding:6px 8px;gap:5px}
.sc.ai header{margin:-6px -8px 0;padding:4px 8px}
.ws{grid-template-columns:60px 1fr;gap:2px 8px}
.mx{height:46px}
.matrix th.rh{width:128px}
.drop{padding:10px;gap:4px}
.kv{padding:2px 0}
.seg-row{padding:3px 6px}
.body.reg{grid-template-columns:minmax(0,1.25fr) minmax(360px,1fr)}
.body.ext{grid-template-columns:minmax(0,1fr) 270px}
.body.kg{grid-template-columns:190px minmax(0,1fr) 270px}
.body.seg{grid-template-columns:minmax(0,1fr) 330px}
.body.mat{grid-template-columns:minmax(0,1fr) minmax(420px,.85fr)}
""",
    "C": """
.shell-c{grid-template-columns:224px minmax(0,1fr)}
.sidenav{background:var(--nav-bg);border-right:1px solid var(--line);display:flex;flex-direction:column;gap:14px;padding:16px 12px}
.brand{display:flex;align-items:center;gap:10px;padding:0 6px;font-size:16px}
.logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--ui),var(--seg1));color:var(--on-fill);display:grid;place-items:center;font-weight:800}
.proj{display:flex;flex-direction:column;gap:1px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--surface)}
.proj .muted{font-size:12px}
.sidenav nav{display:flex;flex-direction:column;gap:2px}
.nav-i{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:8px;color:var(--nav-muted);font-weight:600}
.nav-i .num{width:22px;height:22px;border-radius:6px;display:grid;place-items:center;background:var(--surface-2);font-size:12px;color:var(--nav-ink)}
.nav-i .cnt{margin-left:auto;font-size:12px;font-family:var(--mono)}
.nav-i.on{background:var(--nav-active-bg);color:var(--nav-active-ink);box-shadow:inset 3px 0 0 var(--ui)}
.nav-i.on .num{background:var(--ui);color:var(--on-fill)}
.side-foot{margin-top:auto;display:flex;gap:10px;align-items:center;padding:8px 6px;border-top:1px solid var(--line)}
.side-foot div{display:flex;flex-direction:column;font-size:12.5px}
.avatar{width:30px;height:30px;border-radius:50%;background:var(--surface-2);border:1px solid var(--line-strong);display:grid;place-items:center;font-weight:700}
.work{display:grid;grid-template-rows:minmax(0,1fr) 28px;min-width:0;min-height:0}
.statusbar{background:var(--nav-bg)}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--gap)}
.kpis .kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px 16px;position:relative;overflow:hidden;flex-direction:row;align-items:baseline;justify-content:space-between}
.kpis .kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--line-strong)}
.kpis .kpi.ok::before{background:var(--ok)} .kpis .kpi.warn::before{background:var(--warn-line)} .kpis .kpi.err::before{background:var(--err-line)}
.kpi-v{font-size:24px;letter-spacing:-.02em;font-family:var(--mono)}
.kpi-l{font-size:12.5px}
.page-head .sub{margin-top:2px}
.panel-h{font-size:13px}
.sc.human{border-color:var(--ink-2)}
""",
}


def page(variant_key, idx):
    v = VARIANTS[variant_key]
    key, label, _ = SCREENS[idx]
    spec = SCREEN_SPEC[key]
    out = spec["body"]()
    banner, body = (out if isinstance(out, tuple) else ("", out))
    inner = (f'<div class="page-head"><div class="ph-txt"><h1>{spec["title"]}</h1><div class="sub">{spec["sub"]}</div></div>'
             f'<div class="acts">{spec["actions"]}</div></div>{kpis(spec["kpis"])}{banner}'
             f'<div class="body {spec["cls"]}">{body}</div>')
    root = {**{k: val for k, val in v["tokens"].items()}, **v["density"]}
    root_css = ":root{" + ";".join(f"--{k}:{val}" for k, val in root.items()) + f";--font:{FONT_STACK};--mono:{MONO_STACK}" + "}"
    scheme = "dark" if v["short"] == "C" else "light"
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(v["name"])} · {label}</title><link rel="stylesheet" href="{FONT_CSS}">'
            f'<style>{root_css}\nhtml{{color-scheme:{scheme}}}{BASE_CSS}{SHELL_CSS[v["short"]]}</style></head>'
            f'<body>{SHELLS[v["short"]](idx, inner)}</body></html>')


INDEX = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>완성본 시안 비교</title>
<style>body{margin:0;font-family:'Malgun Gothic',sans-serif;display:flex;flex-direction:column;height:100vh;background:#e5e7eb}
nav{display:flex;gap:6px;padding:8px;align-items:center;background:#111827;color:#fff;flex-wrap:wrap}
button{font:inherit;border:1px solid #6b7280;background:#1f2937;color:#fff;padding:4px 10px;border-radius:6px;cursor:pointer}
button.on{background:#fff;color:#111827}iframe{flex:1;border:0;background:#fff}span{margin:0 8px;color:#d1d5db}</style></head>
<body><nav><span>안</span>%s<span>화면</span>%s<span>키보드: A·B·C, 1~5</span></nav><iframe id="f"></iframe>
<script>const V=%s,S=%s;let v=0,s=0;function go(){f.src=encodeURI(V[v]+'/'+S[s]+'.html');
document.querySelectorAll('[data-v]').forEach(b=>b.classList.toggle('on',+b.dataset.v===v));
document.querySelectorAll('[data-s]').forEach(b=>b.classList.toggle('on',+b.dataset.s===s));}
document.onclick=e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.v)v=+b.dataset.v;if(b.dataset.s)s=+b.dataset.s;go()};
document.onkeydown=e=>{const k=e.key.toUpperCase();if('ABC'.includes(k)&&k.length===1){v='ABC'.indexOf(k);go()}if('12345'.includes(e.key)){s=+e.key-1;go()}};go();</script></body></html>"""


def build():
    fails_all = []
    for vk, v in VARIANTS.items():
        d = ROOT / vk
        d.mkdir(exist_ok=True)
        for i, (key, _, _) in enumerate(SCREENS):
            (d / f"{key}.html").write_text(page(vk, i), encoding="utf-8")
        table, fails = contrast_table(v["tokens"])
        (d / "대비표.md").write_text(
            f"# {v['name']} 대비 계산\n\n`build.py`가 WCAG 2.1 상대 휘도 공식으로 계산한 값이다. 글자는 4.5:1, 그래픽(테두리·도면 선·구간 색)은 3:1이 기준이다.\n\n{table}",
            encoding="utf-8")
        fails_all += [f"{vk}: {f}" for f in fails]
    vs = list(VARIANTS)
    sc = [s[0] for s in SCREENS]
    (ROOT / "index.html").write_text(INDEX % (
        "".join(f'<button data-v="{i}">{VARIANTS[k]["name"]}</button>' for i, k in enumerate(vs)),
        "".join(f'<button data-s="{i}">{i + 1} {s[1]}</button>' for i, s in enumerate(SCREENS)),
        repr(vs).replace("'", '"'), repr(sc).replace("'", '"')), encoding="utf-8")
    return fails_all


def shoot():
    chrome = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    prof = pathlib.Path.home() / "AppData/Local/Temp/hazop-shoot-profile"
    for vk in VARIANTS:
        for key, _, _ in SCREENS:
            src = ROOT / vk / f"{key}.html"
            for w, h in ((1366, 768), (1920, 1080)):
                out = ROOT / vk / f"{key}-{w}.png"
                subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={prof}",
                                "--force-device-scale-factor=1", f"--window-size={w},{h}", "--virtual-time-budget=6000",
                                f"--screenshot={out}", src.as_uri()], check=True, capture_output=True, timeout=120)
                print("saved", out.relative_to(ROOT))


if __name__ == "__main__":
    fails = build()
    for f in fails:
        print("대비 미달:", f)
    if "--shoot" in sys.argv:
        shoot()
    sys.exit(1 if fails else 0)
