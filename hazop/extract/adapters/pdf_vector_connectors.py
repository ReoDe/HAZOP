"""벡터 PDF 어댑터의 연결 표시(다른 도면·시트로 이어지는 화살표) 글자 읽기.

연결 표시 옆 글자에서 계통 약어와 시트 표기를 읽는 정규식과 _continuation_attributes.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""

import math
import re

from .pdf_vector_common import _inside, _box_gap, _center

SHEET_WORD_RE = re.compile(r"\bSHEET\b")  # 연결 표시 화살표 글자의 DCD 시트 표기('SHEET 2 "E"')
CONTINUATION_RE = re.compile(r"^(TO|FROM)\s+\S*\d")
SYSTEM_LABEL_RE = re.compile(r"^([A-Z]{2,3}):\S")  # 'CV:RDT', 'SI:SAFETY INJECTION LINE 3' — 다른 계통 도면으로 가는 표시
# 쌍점 없이 화살표 바로 옆에 두 글자만 쓴 계통 약어(범례 1.7-1 'MS / SHEET 2"A"'). 밸브 위치 약어(범례 같은 쪽)는 뺀다
BARE_SYSTEM_RE = re.compile(r"^(?!(?:FC|FO|FL|LO|LC|LT|NO|NC)$)[A-Z]{2}$")


SEQUENCE_LETTER_RE = re.compile(r"^[A-Z]{1,2}$")
SHEET_REF_RE = re.compile(r"\bSHEET\s*\d")
# 물결 끊김(배관 끝의 '~' 표시) 옆 글자 'FROM & TO WI'(정답지 규약: 다른 계통 이름이 적힌 물결 끊김은 연결 표시)
WAVE_TEXT_RE = re.compile(r"^(?:FROM\s*&\s*TO|FROM|TO)\s+([A-Z]{2})$")


def _label_side(box, arrow):
    """글자 상자가 연결 화살표의 글자 자리에 있는가. DCD는 가로 화살표의 글자를 화살표 위에, 세로 화살표의 글자를 왼쪽에
    쓴다(또는 화살표 안)."""
    ax0, ay0, ax1, ay1 = arrow
    bx0, by0, bx1, by1 = box
    if _inside(_center(box), arrow):
        return True
    if ax1 - ax0 >= ay1 - ay0:
        return (by0 + by1) / 2 < (ay0 + ay1) / 2 and bx0 < ax1 and bx1 > ax0  # 문단 가운데가 화살표 가운데보다 위
    return (bx0 + bx1) / 2 < (ax0 + ax1) / 2 and by0 < ay1 and by1 > ay0


def _has_text(s):
    return bool(re.search(r"[A-Z0-9]", (s or "").upper()))


def attach_continuation_names(nodes, blocks, free, gap_max):
    """계통 약어를 못 읽은 연결 화살표(자기 글자가 'SHEET 4"Q"'뿐이거나 글자가 없음)의 글자 자리에 맞닿은 이름 문단
    ('ACID ADDITION', 'CD CONDENSER A\\nHOTWELL')을 행선으로 붙인다(제자리 고침). to_label은 정답지 규약처럼
    '이름 / 자기 글자'다. 맞닿은 문단이 둘 이상이거나 다른 화살표가 그 문단에 같거나 더 가까우면 붙이지 않는다
    (틀린 행선보다 미확인이 낫다). 이름 맨 앞 두 글자('CD CONDENSER', 'MS DRAIN')는 to_system으로 두지 않는다. 행선
    설비의 계통일 뿐 이 쪽과 다른 계통이라는 뜻이 아니어서(10.3.2-1 시트 2 'MS DRAIN / SHEET 1'은 같은 그림),
    to_system이 생기면 프로젝트 그래프가 같은 그림 시트끼리 잇던 짝을 잃는다(137쪽 14짝).
    free: 아무 데도 붙지 않은 글자 문단 번호(blocks의 색인). → 붙인 화살표 수."""
    arrows = [(n, _node_box(n)) for n in nodes if n.get("kind") == "continuation"]
    done = 0
    for n, box in arrows:
        attrs = n["attributes"]
        own = " ".join((n.get("label_text") or "").split())
        if attrs.get("to_system") or attrs.get("to_label") or not (SHEET_REF_RE.search(own) or not _has_text(own)):
            continue
        near = [bi for bi in free if not SHEET_WORD_RE.search(blocks[bi]["text"]) and _has_text(blocks[bi]["text"])
                and _label_side(blocks[bi]["bbox"], box) and _box_gap(blocks[bi]["bbox"], box) <= gap_max]
        if len(near) != 1:
            continue
        b = blocks[near[0]]
        gap = _box_gap(b["bbox"], box)
        if any(o is not n and _box_gap(b["bbox"], ob) <= gap for o, ob in arrows):
            continue
        name = " ".join(b["text"].split())
        attrs["to_label"] = name + (" / " + own if _has_text(own) else "")
        done += 1
    return done


def is_wave_mark(members):
    """기호 조각이 모두 열린 굽은 선(곡선, 또는 꺾인 점 셋 이상의 선)인가. 물결 끊김 '~'은 077쪽처럼 곡선 대신 꺾은 선
    두 개로 그려지기도 한다."""
    def bent(m):
        if m.get("curved"):
            return True
        pts = m["pts"]
        if m.get("closed") or len(pts) < 3:
            return False
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        chord = math.hypot(x1 - x0, y1 - y0)
        return chord > 0 and max(abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / chord for x, y in pts[1:-1]) > 0.2 * chord
    return bool(members) and all(bent(m) for m in members)


def wave_break_targets(waves, blocks, gap_max):
    """물결 끊김 기호 옆의 'FROM & TO WI' 글자에서 상대 계통을 읽는다. waves: [(키, 상자)] (굽은 선으로만 그린 작은 미분류
    기호), blocks: 글자 문단 전부(다른 물결이 라벨로 가져간 문단도 본다. 한 문단이 공급·환수 두 배관의 물결을 함께
    가리킨다). 가장 가까운 그런 문단이 gap_max 안이고, 계통이 다른 문단이 그 거리의 두 배 안에 없을 때만 정한다.
    → {키: {"to_system", "to_label"}}"""
    texts = [(m.group(1), t, b["bbox"]) for b in blocks
             for t in [" ".join(b["text"].split())] for m in [WAVE_TEXT_RE.match(t)] if m and BARE_SYSTEM_RE.match(m.group(1))]
    out = {}
    for key, box in waves:
        near = sorted((_box_gap(tb, box), code, t) for code, t, tb in texts)
        if not near or near[0][0] > gap_max:
            continue
        g, code, t = near[0]
        if any(c != code and d <= 2 * g + 1.0 for d, c, _ in near[1:]):
            continue
        out[key] = {"to_system": code, "to_label": t}
    return out


def _node_box(n):
    g = n["geometry"]
    return g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"]


def same_sheet_letter_pairs(nodes, relations):
    """같은 쪽 순서 문자 깃발(범례 1.7-1 SEQUENCE LETTER ON SAME FIGURE SHEET) 가운데 글자가 같은 것끼리 짝을 짓는다.
    같은 글자의 깃발은 한 배관이 쪽 안에서 끊겼다 이어지는 자리라 같은 지점으로 본다(정답지 규약 4절, 097쪽 방식).
    물리 배관이 닿은 깃발만 본다. 신호선(점선) 끝 깃발(APR1400 023·025쪽)은 배관이 아니다.
    글자가 같은 깃발이 셋 이상이면 첫 깃발에 나머지를 잇는다. → [(노드 id, 노드 id)]"""
    piped = {e.get("node_local_id") for r in relations if r["kind"] == "physical_connection" for e in r["endpoints"]}
    groups = {}
    for n in nodes:
        letter = (n.get("label_text") or "").strip().upper()
        basis = (n.get("evidence") or {}).get("classification_basis") or ""
        if n.get("kind") == "continuation" and basis.endswith("sequence_letter") and SEQUENCE_LETTER_RE.match(letter) \
                and n["local_id"] in piped:
            groups.setdefault(letter, []).append(n["local_id"])
    return [(ids[0], other) for _, ids in sorted(groups.items()) for other in ids[1:]]


def _continuation_attributes(sym, blocks, prm, own=None, arrows=()):
    """연결 표시 화살표 옆 글자에서 상대 계통을 읽는다. 화살표에 붙은 글자 문단(own)에 'CV:RDT'처럼 계통 약어로
    시작하는 줄이 있으면 그것을, 없으면 그런 줄이 있는 문단 중 화살표에서 label_gap_max 안으로 가장 가까운 것을 쓴다.
    DCD는 가로 화살표의 글자를 화살표 위에, 세로 화살표의 글자를 왼쪽에 쓰므로 그 자리(또는 화살표 안)의 문단만 보고,
    다른 화살표(arrows)가 그 문단에 더 가까우면 그 화살표의 글자로 보아 쓰지 않는다. 화살표가 촘촘히 쌓인 곳에서
    이웃 화살표의 계통을 가져오지 않게 하려는 것이다(같은 계통의 다른 시트로 가면 약어를 생략한다, 범례 1.7-1).
    약어를 to_system, 그 줄부터의 글자를 to_label로 둔다. 없으면 빈 dict
    (계통 약어 없이 'MAKE-UP DEMIN. WATER'처럼 쓴 표시는 상대를 정하지 않는다). 쪽끼리 짝짓기는 하지 않는다."""
    def code_line(text):
        lines = text.split("\n")
        k = next((k for k, line in enumerate(lines) if SYSTEM_LABEL_RE.match(line)), None)
        return None if k is None else (SYSTEM_LABEL_RE.match(lines[k]).group(1), " ".join(" ".join(lines[k:]).split()))

    def mine(b, gap):
        return _label_side(b["bbox"], sym.bbox) and all(_box_gap(b["bbox"], a.bbox) >= gap for a in arrows if a is not sym)

    if own is not None and code_line(own["text"]) and mine(own, _box_gap(own["bbox"], sym.bbox)):
        code, text = code_line(own["text"])
        return {"to_system": code, "to_label": text}
    own_lines = [] if own is None else [line.strip() for line in own["text"].split("\n") if line.strip()]
    bare = next((line for line in own_lines if BARE_SYSTEM_RE.match(line)), None)
    if bare and any(SHEET_REF_RE.search(line) for line in own_lines):
        return {"to_system": bare, "to_label": " ".join(own_lines)}  # 화살표 글자 한 문단에 'CC\nSHEET 4'(범례 'MS / SHEET 2"A"')
    near = []
    sheet_ref = own is not None and re.search(r"SHEET\s*\d", own["text"])  # 범례 꼴: 화살표 안에 시트 번호가 있을 때만
    for b in blocks:
        hit = code_line(b["text"])
        gap = _box_gap(b["bbox"], sym.bbox)
        if not hit and sheet_ref and BARE_SYSTEM_RE.match(b["text"].strip()) and gap <= prm["bare_code_gap_max"]:
            hit = (b["text"].strip(), b["text"].strip())  # 범례 'MS / SHEET 2"A"'처럼 쌍점 없이 바로 옆에 쓴 계통 약어
        if hit and gap <= prm["label_gap_max"] and mine(b, gap):
            near.append((gap,) + hit)
    if not near:
        return {}
    _, code, text = min(near)
    return {"to_system": code, "to_label": text}
