"""도면 묶음 자신의 범례 쪽에서 '기호 그림 + 이름 글자' 칸을 자른다(AI 검토 범례판의 '범례 쪽 판', 실측 19).

범례 쪽 알아보기(쪽 번호를 보지 않는다): ① PDF 글자에 LEGEND가 있거나 SYMBOLS가 두 번 이상 나오고
② 아래 규칙으로 자른 칸 가운데 종류가 정해진 칸이 MIN_CELLS개 이상이다. 하나라도 못 채우면 범례 쪽이 아니다([]).
틀려도 부르는 쪽(ai_images)은 범례 쪽 없이 지금 순서(확정 견본 → 표준 칸)로 물러난다.

칸 자르기(목록식 칸: 이름 글자 왼쪽에 기호 그림)
1. 판: 쪽 높이의 PANEL_SPLIT 넘게 이어진 세로 선으로 x를 나누고, 그 칸 너비의 80% 넘게 이어진 가로 선으로 y를 나눈다.
2. 이름 덩어리: NAME_MAX pt 아래 글자 줄을 같은 왼쪽 x(COL_TOL)끼리 묶고, 줄 틈이 JOIN_GAP보다 작으면 한 덩어리로 잇는다.
   이름 열은 왼쪽에 그림 개체가 있는 덩어리가 둘 이상이고 그 몫이 절반 이상인 x 무리다(판 하나에 여럿 있을 수 있다).
   밑줄 친 소제목, 빈칸 표시('_', '@')가 든 줄(설정값 채우기 글), 세 글자 넘는 낱말이 없는 줄은 이름이 아니다.
3. 그림 개체: 이름 덩어리보다 온전히 왼쪽(x1 < 이름 x0)에 있는 선·곡선·사각형과 작은 글자. y가 가장 가까운 이름에 붙이고
   MAX_DIST pt 넘게 떨어지면 버린다. 이름이 아닌 세 줄 이상 글자 덩어리(목록)가 더 가까우면 버린다.
도해식 칸(이름이 그림 아래): 목록식 이름에 쓰이지 않은 네 낱말 이하 줄 바로 위(UNDER_GAP pt 안)에 그림이 있으면 칸으로 본다.
   이름 앞에 같은 판에서 가장 가까운 위쪽 밑줄 소제목을 붙인다('MOTOR OPERATOR' + 'AC MOTOR').
버리는 칸: 지시선(이름 왼쪽 끝에 닿는 긴 가로 선)으로 그림을 가리키는 칸, 그림 상자가 다른 칸 그림과 크게 겹치는 칸,
   그림 높이가 이웃 이름까지 거리의 PITCH_SPAN배를 넘는 칸(이웃 줄 그림이 섞임),
   이름이 애매한 칸(kind_of가 None). 틀린 견본이 판에 들어가는 것이 견본이 없는 것보다 나쁘다.
그림이 가로로 PART_GAP pt 넘게 떨어진 무리로 나뉘면(열림·닫힘 밸브 두 그림) 무리마다 견본 상자(parts)로 둔다.
"""

import re

CUT_VERSION = 1
PANEL_SPLIT = 0.25
NAME_MAX = 5.0
COL_TOL = 2.0
JOIN_GAP = 2.0
MAX_DIST = 20.0
UNDER_GAP = 12.0
PART_GAP = 8.0
MIN_CELLS = 10
OVERLAP = 0.3
PITCH_SPAN = 1.3  # 그림 높이가 이웃 이름과의 거리의 이 배를 넘으면 이웃 줄 그림이 섞인 칸으로 보고 버린다

# 이름 구절 -> 종류(일반 P&ID 낱말). 구절은 대문자 낱말 순서로 맞춘다. 종류 None은 '종류 아님' 낱말(이 구절이 들면 다른
# 종류와 겹쳐 애매해진다). 빼는 낱말이 이름에 있으면 그 구절은 보지 않는다. 레지스트리 label_en은 phrases()가 뒤에 더한다.
PHRASES = (
    ("TEST CONNECTION", "test_connection", ()), ("TEST CONECTION", "test_connection", ()),
    ("TEST POINT", "test_connection", ()), ("SAMPLE PROBE", "sample_probe", ()), ("SIGHT GLASS", "sight_glass", ()),
    ("FLAME ARRESTOR", "flame_arrestor", ()), ("FLAME ARRESTER", "flame_arrestor", ()),
    ("SLIP JOINT", "slip_joint", ()), ("EXPANSION JOINT", "expansion_joint", ()),
    ("DIAPHRAGM SEAL", "diaphragm_seal", ()), ("FLEXIBLE HOSE", "flexible_hose", ()),
    ("FLEXIBLE CONNECTION", "flexible_hose", ()), ("HOSE CONNECTION", "hose_connection", ()),
    ("RUPTURE DISC", "rupture_disc", ()), ("RUPTURE DISK", "rupture_disc", ()), ("BURSTING PLUG", None, ()),
    ("SPARGER", "sparger", ()), ("SPRAY NOZZLE", "sparger", ()), ("SILENCER", "silencer", ()), ("MUFFLER", "silencer", ()),
    ("HUMIDIFIER", "humidifier", ()), ("AIR FLOW", "air_flow_arrow", ()),
    ("ORIFICE", "orifice", ()), ("RESTRICTION", "orifice", ()), ("METERING ORIFICE", "flow_element", ()),
    ("FLOW ELEMENT", "flow_element", ()), ("FLOW NOZZLE", "flow_element", ()), ("VENTURI TUBE", "flow_element", ()),
    ("CAVITATING VENTURI", None, ()), ("PITOT", "flow_element", ()), ("ROTAMETER", "flow_element", ()),
    ("METER", "flow_element", ()), ("TEMPERATURE ELEMENT", "temperature_element", ()),
    ("THERMOWELL", "temperature_element", ()), ("LEVEL ELEMENT", "level_element", ()),
    ("TRANSMITTER", "transmitter", ()), ("CONVERTER", "relay_converter", ()), ("STEAM CONVERTER", None, ()),
    ("RELAY", "relay_converter", ()), ("POSITION LIGHT", "pilot_light", ()), ("POSITION LIGHTS", "pilot_light", ()),
    ("PILOT LIGHT", "pilot_light", ()), ("STATUS LIGHTS", "pilot_light", ()), ("HAND SWITCH", None, ()),
    ("ALARM", "alarm", ("VALVE",)), ("INDICATOR", "indicator", ("VALVE",)), ("CONTROLLER", "controller", ()),
    ("SAFETY OR RELIEF", "psv", ()), ("SAFETY RELIEF", "psv", ()), ("SAFETY VALVE", "psv", ()),
    ("VACUUM RELIEF", "relief_valve", ()), ("RELIEF VALVE", "relief_valve", ()),
    ("CHECK", "check_valve", ()), ("NON-RETURN", "check_valve", ()), ("STOP-CHECK", "check_valve", ()),
    ("BACKFLOW PREVENTER", "check_valve", ()), ("FOOT VALVE", "check_valve", ()),
    ("DAMPER", "damper", ()), ("PULSATION DAMPENER", None, ()),
    ("MOTOR OPERATED", "motor_operated_valve", ()), ("MOTOR OPERATOR", "motor_operated_valve", ()),
    ("CONTROL VALVE", "control_valve", ()), ("ISOLATION VALVE", "isolation_valve", ()),
    ("PNEUMATIC OPERATOR", "air_operated_valve", ()), ("PNEUMATIC OPERATORS", "air_operated_valve", ()),
    ("AIR OPERATED", "air_operated_valve", ()), ("CYLINDER OPERATOR", "air_operated_valve", ()),
    ("DIAPHRAGM OPERATOR", "air_operated_valve", ()), ("SOLENOID", "solenoid_valve", ()),
    ("REDUCER", "reducer", ()), ("ENLARGER", "reducer", ()), ("STRAINER", "strainer", ()),
    ("DRAIN", "drain", ()), ("TRAP", None, ()), ("VENT", "vent", ()), ("CAP", "pipe_cap", ()),
    ("COMPRESSOR", "compressor", ()), ("PUMP", "pump", ()), ("FAN", "fan", ()), ("BLOWER", "fan", ()),
    ("VENTILATOR", "fan", ()),
    ("GATE", "manual_valve", ()), ("GLOBE", "manual_valve", ()), ("BUTTERFLY", "manual_valve", ()),
    ("BALL", "manual_valve", ()), ("PLUG", "manual_valve", ()), ("NEEDLE", "manual_valve", ()),
    ("ANGLE", "manual_valve", ()), ("DIAPHRAGM", "manual_valve", ()), ("PACKLESS VALVE", "manual_valve", ()),
    ("THREE-WAY", "manual_valve", ()), ("FOUR-WAY", "manual_valve", ()),
    ("TURBINE", "turbine", ()), ("COOLER", "heat_exchanger", ()), ("COIL", "heat_exchanger", ()),
    ("TANK", "tank", ()), ("VESSEL", "vessel", ()), ("FILTER", "filter", ()), ("SWITCH", "switch", ()),
    ("CONTINUATION", "continuation", ()), ("NOZZLE", "nozzle", ()),
)

# 밸브 몸통 꼴 낱말이 정한 종류. 같은 이름에 다른 종류(기능: 체크·안전·구동부)가 함께 있으면 그 종류가 이긴다('ANGLE CHECK').
BODY_KINDS = frozenset({"manual_valve"})

_HEADING = re.compile(r"\b(LEGEND|SYMBOLS)\b")


def words(s):
    return re.findall(r"[A-Z0-9][A-Z0-9\-]*", s.upper())


def phrases():
    """PHRASES 뒤에 레지스트리 label_en(예: 'CONDENSER', 'BLIND FLANGE')을 더한 표."""
    from hazop.kg.schema import REGISTRY
    out = list(PHRASES)
    have = {p for p, _, _ in out}
    for kind in sorted(REGISTRY.kind_category()):
        label = " ".join(words((REGISTRY.classes.get(kind) or {}).get("label_en") or kind.replace("_", " ")))
        if label and label not in have:
            out.append((label, kind, ()))
            have.add(label)
    return tuple(out)


def kind_of(name, table=None):
    """범례 이름 글자 -> 종류, 애매하거나 없으면 None. 괄호 안은 보충 설명이라 보지 않는다.
    맞은 구절 가운데 다른 맞은 구절 안에 든 것은 버린다(좁은 뜻이 이긴다: 'SPRAY NOZZLE' 안의 'NOZZLE').
    남은 종류가 하나면 그것, 몸통 꼴(BODY_KINDS)과 기능 종류 하나면 기능 종류, 그 밖(종류 아님 낱말이 섞이거나 기능 종류가
    둘 이상)은 애매하다."""
    w = words(re.sub(r"\([^)]*\)?", " ", name))
    if not w:
        return None
    spans = []
    for phrase, kind, nots in (table or phrases()):
        if any(n in w for n in nots):
            continue
        p = phrase.split()
        for i in range(len(w) - len(p) + 1):
            if w[i:i + len(p)] == p:
                spans.append((i, i + len(p), kind))
    spans = [s for s in spans if not any(o[0] <= s[0] and s[1] <= o[1] and (o[1] - o[0]) > (s[1] - s[0]) for o in spans)]
    kinds = {k for _, _, k in spans}
    if None in kinds or not kinds:
        return None
    if len(kinds) > 1:
        kinds -= BODY_KINDS
    return kinds.pop() if len(kinds) == 1 else None


# ---------------------------------------------------------------- 쪽 읽기

def heading_lines(pdf_path, page=0):
    """PDF 글자 줄 가운데 LEGEND·SYMBOLS가 든 줄(대문자). 빠른 pypdfium2 글자만 읽는다."""
    import pypdfium2
    doc = pypdfium2.PdfDocument(pdf_path)
    try:
        tp = doc[page].get_textpage()
        text = tp.get_text_range().upper()
        tp.close()
    finally:
        doc.close()
    return [ln.strip() for ln in text.splitlines() if _HEADING.search(ln)]


def has_heading(lines):
    return any("LEGEND" in ln for ln in lines) or sum(len(re.findall(r"\bSYMBOLS\b", ln)) for ln in lines) >= 2


def _text_lines(words_):
    lines = []
    for w in sorted(words_, key=lambda w: (round(w["top"]), w["x0"])):
        for ln in lines:
            if abs(ln["top"] - w["top"]) < 1.0 and 0 <= w["x0"] - ln["x1"] < 4.0:
                ln.update(text=ln["text"] + " " + w["text"], x1=w["x1"], bottom=max(ln["bottom"], w["bottom"]),
                          size=max(ln["size"], w["size"]))
                break
        else:
            lines.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"],
                          "size": w["size"]})
    return lines


def read_layout(pdf_path, page=0):
    """pdfplumber로 쪽의 글자 줄·그림 개체·선을 읽는다 -> {'lines', 'objs', 'edges', 'height'}."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[page]
        lines = _text_lines(p.extract_words(extra_attrs=["size"]))
        objs = [(o["x0"], o["top"], o["x1"], o["bottom"]) for o in p.lines + p.curves + p.rects]
        edges = [(e["orientation"], e["x0"], e["top"], e["x1"], e["bottom"]) for e in p.edges]
        return {"lines": lines, "objs": objs, "edges": edges, "height": float(p.height)}


# ---------------------------------------------------------------- 칸 자르기

def _splits(vals, tol=3.0):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _runs(segs, tol=1.0, gap=1.5):
    """같은 좌표(tol 안) 선분을 이어 가장 긴 이어진 구간 -> {좌표: (길이, 시작, 끝)}."""
    rows = {}
    for c, a, b in sorted(segs):
        key = next((k for k in rows if abs(k - c) <= tol), c)
        rows.setdefault(key, []).append((a, b))
    out = {}
    for c, iv in rows.items():
        iv.sort()
        best, (s, e) = (0.0, 0.0), iv[0]
        for a, b in iv[1:] + [(float("inf"), float("inf"))]:
            if a <= e + gap:
                e = max(e, b)
                continue
            if e - s > best[1] - best[0]:
                best = (s, e)
            s, e = a, b
        out[c] = (best[1] - best[0], best[0], best[1])
    return out


def panels(layout):
    vert = _runs([((x0 + x1) / 2, t, b) for o, x0, t, x1, b in layout["edges"] if o == "v"])
    hor = _runs([((t + b) / 2, x0, x1) for o, x0, t, x1, b in layout["edges"] if o == "h"])
    vx = _splits([x for x, (n, _, _) in vert.items() if n > PANEL_SPLIT * layout["height"]])
    out = []
    for a, b in zip(vx, vx[1:]):
        if b - a < 40:
            continue
        hy = _splits([y for y, (n, s, e) in hor.items() if s <= a + 5 and e >= b - 5 and n > 0.8 * (b - a)])
        out += [(a, t, b, u) for t, u in zip(hy, hy[1:]) if u - t > 12]
    return out


def _inside(o, p):
    cx, cy = (o[0] + o[2]) / 2, (o[1] + o[3]) / 2
    return p[0] < cx < p[2] and p[1] < cy < p[3]


def _underline(ln, objs):
    w = ln["x1"] - ln["x0"]
    for o in objs:
        if o[3] - o[1] < 1.0 and -1.5 <= o[1] - ln["bottom"] <= 2.0 and min(o[2], ln["x1"]) - max(o[0], ln["x0"]) > 0.8 * w:
            return o
    return None


def _wordy(text):
    return any(len(re.sub(r"[^A-Z]", "", t)) >= 3 for t in words(text)) and not re.search(r"[_@]", text)


def _blocks(lines, centered=False):
    """줄 틈이 JOIN_GAP보다 작은 줄을 한 덩어리로 잇는다. 왼쪽 맞춤(x0가 같음)만, centered면 가로로 겹치는 줄도."""
    out = []
    for ln in sorted(lines, key=lambda ln: (ln["top"], ln["x0"])):
        for b in reversed(out):
            if not 0 <= ln["top"] - b["bottom"] < JOIN_GAP:
                continue
            if abs(ln["x0"] - b["x0"]) <= COL_TOL * 2 or (centered and min(ln["x1"], b["x1"]) > max(ln["x0"], b["x0"])):
                b.update(text=b["text"] + " " + ln["text"], bottom=max(b["bottom"], ln["bottom"]), x0=min(b["x0"], ln["x0"]),
                         x1=max(b["x1"], ln["x1"]), n=b["n"] + 1)
                break
        else:
            out.append(dict(ln, n=1))
    return out


def _box(objs):
    return (min(o[0] for o in objs), min(o[1] for o in objs), max(o[2] for o in objs), max(o[3] for o in objs))


def _parts(objs):
    """그림 개체를 가로 틈 PART_GAP 넘는 무리로 나눈 상자들(왼쪽부터)."""
    out = []
    for o in sorted(objs):
        if out and o[0] <= out[-1][2] + PART_GAP:
            b = out[-1]
            out[-1] = (b[0], min(b[1], o[1]), max(b[2], o[2]), max(b[3], o[3]))
        else:
            out.append(tuple(o))
    return out


def _touches(o, t, tol=1.5):
    """선 o의 한쪽 끝이 글자 상자 t 둘레 tol 안에 있다."""
    ends = ((o[0], o[1]), (o[2], o[3])) if o[3] - o[1] >= 1.0 else ((o[0], (o[1] + o[3]) / 2), (o[2], (o[1] + o[3]) / 2))
    return any(t[0] - tol <= x <= t[2] + tol and t[1] - tol <= y <= t[3] + tol for x, y in ends)


def _ydist(cy, b):
    return 0.0 if b["top"] <= cy <= b["bottom"] else min(abs(cy - b["top"]), abs(cy - b["bottom"]))


def _panel_cells(p, lines, objs):
    pw = p[2] - p[0]
    pobjs = [o for o in objs if _inside(o, p) and o[3] - o[1] < 0.4 * (p[3] - p[1]) and o[2] - o[0] < 0.6 * pw]
    small = [ln for ln in lines if ln["size"] < NAME_MAX and _inside((ln["x0"], ln["top"], ln["x1"], ln["bottom"]), p)]
    heads = [ln for ln in small if _underline(ln, objs)]
    unders = {_underline(ln, objs) for ln in heads}
    pobjs = [o for o in pobjs if o not in unders]
    plain = [ln for ln in small if ln not in heads]
    groups = {}
    last = None
    for ln in sorted(plain, key=lambda ln: ln["x0"]):
        if last is None or ln["x0"] - last > COL_TOL:
            key = ln["x0"]
        groups.setdefault(key, []).append(ln)
        last = ln["x0"]

    def pic_left(b):
        return any(o[2] < b["x0"] - 1 and b["top"] - 6 <= (o[1] + o[3]) / 2 <= b["bottom"] + 6 for o in pobjs)

    names = []
    for g in groups.values():
        bl = [b for b in _blocks(g) if _wordy(b["text"])]
        with_pic = [b for b in bl if pic_left(b)]
        if len(with_pic) >= 2 and len(with_pic) * 2 >= len(bl) and min(b["x0"] for b in bl) - p[0] >= 0.15 * pw:
            names += with_pic
    used = {id(ln) for ln in plain for b in names if b["top"] <= ln["top"] <= b["bottom"] and abs(ln["x0"] - b["x0"]) <= COL_TOL * 2}
    others = _blocks([ln for ln in plain if id(ln) not in used], centered=True)
    lists = [b for b in others if b["n"] >= 3]
    for b in names:
        b["objs"] = []
    pieces = list(pobjs) + [(ln["x0"], ln["top"], ln["x1"], ln["bottom"]) for ln in plain if id(ln) not in used]
    claimed = set()
    for o in pieces:
        cy = (o[1] + o[3]) / 2
        cand = [b for b in names if o[2] < b["x0"] - 0.5]
        if not cand:
            continue
        best = min(cand, key=lambda b: (_ydist(cy, b), b["x0"]))
        d = _ydist(cy, best)
        if d > MAX_DIST or any(_ydist(cy, lb) < d and lb["x1"] < best["x0"] for lb in lists):
            continue
        best["objs"].append(o)
        claimed.add(o)
    cells = []
    for b in names:
        if not b["objs"]:
            continue
        leader = any(o[3] - o[1] < 1.0 and o[2] - o[0] > 15 and abs(o[2] - b["x0"]) < 3 and b["top"] - 2 <= o[1] <= b["bottom"] + 2
                     for o in b["objs"])
        mid = (b["top"] + b["bottom"]) / 2
        pitch = min([abs(mid - (o["top"] + o["bottom"]) / 2) for o in names if o is not b and abs(o["x0"] - b["x0"]) <= COL_TOL * 2]
                    or [float("inf")])
        box = _box(b["objs"])
        callout = False
        for ln in plain:
            t = (ln["x0"], ln["top"], ln["x1"], ln["bottom"])
            if id(ln) in used or t in b["objs"]:
                continue
            if _wordy(ln["text"]) and any(_touches(o, t) for o in b["objs"] if o[3] - o[1] < 1.0 or o[2] - o[0] < 1.0):
                callout = True       # 그림의 선이 다른 설명 글에 닿는다(지시선)
            if _overlap(box, t) <= 0:
                continue
            if re.search(r"[_@]", ln["text"]):
                b["objs"].append(t)  # 설정값 채우기 글(SET @_ _ PSIG)은 그림의 일부라 통째로 싣는다
            elif _wordy(ln["text"]):
                callout = True       # 그림 상자를 가로지르는 다른 설명 글: 설명 글로 가리키는 도해라 견본으로 쓰지 않는다
        box = _box(b["objs"])
        flat = min(box[2] - box[0], box[3] - box[1]) < 0.5   # 선 하나뿐인 그림은 기호가 아니다
        cells.append({"name": b["text"], "box": box, "parts": _parts(b["objs"]),
                      "leader": leader or callout or flat or box[3] - box[1] > PITCH_SPAN * pitch})
    # 도해식 칸: 이름이 그림 아래. 앞에 붙이는 소제목은 밑줄 친 줄과 그 바로 위로 이어진 줄들(여러 줄 소제목)
    titles = [t for t in _blocks(small, centered=True) if any(t["top"] <= h["top"] <= t["bottom"] for h in heads)]
    for b in others:
        if b["n"] > 2 or len(words(b["text"])) > 4 or not _wordy(b["text"]):
            continue
        above = [o for o in pobjs if o not in claimed and b["top"] - UNDER_GAP <= o[3] <= b["top"] + 1
                 and b["x0"] - 6 <= (o[0] + o[2]) / 2 <= b["x1"] + 6]
        if not above:
            continue
        head = [h for h in titles if h["bottom"] <= b["top"]]
        title = max(head, key=lambda h: h["bottom"])["text"] + " " if head else ""
        cells.append({"name": title + b["text"], "box": _box(above), "parts": _parts(above), "leader": False})
    return cells


def _overlap(a, b):
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1e-6
    return w * h / small


def cut(layout, table=None):
    """범례 쪽 layout -> 칸 [{'name', 'kind', 'box', 'parts'}]. 버리는 칸(지시선·겹침·애매한 이름)은 뺀다."""
    table = table or phrases()
    raw = []
    for p in panels(layout):
        raw += _panel_cells(p, layout["lines"], layout["objs"])
    out = []
    for i, c in enumerate(raw):
        if c["leader"] or any(j != i and _overlap(c["box"], o["box"]) > OVERLAP for j, o in enumerate(raw)):
            continue
        kind = kind_of(c["name"], table)
        if kind:
            out.append({"name": c["name"], "kind": kind, "box": [round(v, 2) for v in c["box"]],
                        "parts": [[round(v, 2) for v in q] for q in c["parts"]]})
    return out


def legend_cells(pdf_path, page=0, table=None):
    """범례 쪽이면 종류가 정해진 칸 목록, 아니면 []. 읽을 수 없는 PDF도 []."""
    try:
        if not has_heading(heading_lines(pdf_path, page)):
            return []
        cells = cut(read_layout(pdf_path, page), table)
    except Exception:  # noqa: BLE001  범례 쪽 판은 덤이다. 못 읽으면 범례 쪽이 없는 것으로 물러난다
        return []
    return cells if len(cells) >= MIN_CELLS else []
