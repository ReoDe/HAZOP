"""벡터 PDF 어댑터의 연결 표시(다른 도면·시트로 이어지는 화살표) 글자 읽기.

연결 표시 옆 글자에서 계통 약어와 시트 표기를 읽는 정규식과 _continuation_attributes.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""

import re

from .pdf_vector_common import _inside, _box_gap, _center

SHEET_WORD_RE = re.compile(r"\bSHEET\b")  # 연결 표시 화살표 글자의 DCD 시트 표기('SHEET 2 "E"')
CONTINUATION_RE = re.compile(r"^(TO|FROM)\s+\S*\d")
SYSTEM_LABEL_RE = re.compile(r"^([A-Z]{2,3}):\S")  # 'CV:RDT', 'SI:SAFETY INJECTION LINE 3' — 다른 계통 도면으로 가는 표시
# 쌍점 없이 화살표 바로 옆에 두 글자만 쓴 계통 약어(범례 1.7-1 'MS / SHEET 2"A"'). 밸브 위치 약어(범례 같은 쪽)는 뺀다
BARE_SYSTEM_RE = re.compile(r"^(?!(?:FC|FO|FL|LO|LC|LT|NO|NC)$)[A-Z]{2}$")


SEQUENCE_LETTER_RE = re.compile(r"^[A-Z]{1,2}$")


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
    ax0, ay0, ax1, ay1 = sym.bbox
    across = ax1 - ax0 >= ay1 - ay0

    def code_line(text):
        lines = text.split("\n")
        k = next((k for k, line in enumerate(lines) if SYSTEM_LABEL_RE.match(line)), None)
        return None if k is None else (SYSTEM_LABEL_RE.match(lines[k]).group(1), " ".join(" ".join(lines[k:]).split()))

    def in_place(b):
        bx0, by0, bx1, by1 = b["bbox"]
        if _inside(_center(b["bbox"]), sym.bbox):
            return True
        if across:
            return (by0 + by1) / 2 < (ay0 + ay1) / 2 and bx0 < ax1 and bx1 > ax0  # 문단 가운데가 화살표 가운데보다 위
        return (bx0 + bx1) / 2 < (ax0 + ax1) / 2 and by0 < ay1 and by1 > ay0

    def mine(b, gap):
        return in_place(b) and all(_box_gap(b["bbox"], a.bbox) >= gap for a in arrows if a is not sym)

    if own is not None and code_line(own["text"]) and mine(own, _box_gap(own["bbox"], sym.bbox)):
        code, text = code_line(own["text"])
        return {"to_system": code, "to_label": text}
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
