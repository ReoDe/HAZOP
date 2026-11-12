"""벡터 PDF 어댑터의 라벨 고르기(pdf_vector 설명글 5번·7번).

낱말을 줄·문단으로 묶고(_text_blocks), 보이는 글자로 노드 태그를 정한다(_assign_tags).
글자를 어느 기호에 붙일지는 pdf_vector.build_extraction 안에 남아 있다.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""

import collections
import re

from hazop.kg.docextract import TAG_RE

from .. import rules
from .pdf_vector_common import _issue

# ISA 계기 글자(기능 문자 + 번호, 예: 'PT 110'·'PIC 110'). 태그 앞 계통 접두는 글자에 없다.
ISA_LABEL_RE = re.compile(r"([A-Z]{1,4})[ \-]*(\d{1,5}[A-Z]?)")
# 수동 밸브 번호(APR1400 'V1681'). 계통 접두는 글자에 없다. 밸브 분류 노드의 라벨 한 줄이 이 꼴이면 그대로 태그로 쓴다
VALVE_TAG_RE = re.compile(r"V\d{3,5}[A-Z]?")
PAREN_TOKEN_RE = re.compile(r"\(\d{1,5}[A-Z]?\)")  # 계기 원 옆 다른 계열 번호 '(3057)'·'(3004D)'. 설비 번호 '(FT32A)'는 아님


def _text_blocks(words, prm):
    """단어 → 줄 → 문단. 반환: [{text, bbox, size, line_boxes}] (위→아래, 왼→오 순). line_boxes는 줄마다의 상자다.
    90° 돌린 낱말(upright 거짓, 아래→위 또는 위→아래로 읽음)은 읽는 방향이 가로가 되게 좌표를 돌려 같은 규칙으로
    묶은 뒤 되돌린다."""
    upright = [w for w in words if w.get("upright", True)]
    up_turn = [dict(w, x0=-w["bottom"], x1=-w["top"], top=w["x0"], bottom=w["x1"])  # 아래→위: x' = -y, y' = x
               for w in words if not w.get("upright", True) and w.get("direction", "btt") == "btt"]
    down_turn = [dict(w, x0=w["top"], x1=w["bottom"], top=-w["x1"], bottom=-w["x0"])  # 위→아래: x' = y, y' = -x
                 for w in words if not w.get("upright", True) and w.get("direction") == "ttb"]
    out = _upright_blocks(upright, prm)
    for b in _upright_blocks(up_turn, prm):
        x0, y0, x1, y1 = b["bbox"]
        out.append(dict(b, bbox=(y0, -x1, y1, -x0), rotated=True,
                        line_boxes=[(t, -c, u, -a) for a, t, c, u in b["line_boxes"]]))
    for b in _upright_blocks(down_turn, prm):
        x0, y0, x1, y1 = b["bbox"]
        out.append(dict(b, bbox=(-y1, x0, -y0, x1), rotated=True,
                        line_boxes=[(-u, a, -t, c) for a, t, c, u in b["line_boxes"]]))
    out.sort(key=lambda b: (round(b["bbox"][1], 2), round(b["bbox"][0], 2)))
    return out


def _upright_blocks(words, prm):
    """가로 글자 단어 → 줄 → 문단."""
    # 글자 크기가 조금씩 다르면 pdfplumber가 'SHEET 3"A"'를 한 자씩 끊는다. 그런 조각은 윗변이 조금씩 달라 윗변 순으로
    # 보면 오른쪽 조각이 먼저 줄을 열어 왼쪽 조각이 붙지 못하고(10.4.9-1-S1 'SHEET 2' / '"E"'), 커닝으로 앞 조각과
    # 조금 겹치기도 한다(9.5.1-1-S1 'S'·'H' -0.006pt). 그래서 왼쪽부터 보고, 조금 겹쳐도 같은 줄로 보며 띄어 쓰지 않는다.
    # 괄호로 싼 낱말('(3057)', 계기 원 옆 다른 계열 번호)은 붙어 있지 않으면 따로 둔다(9.4.5-1-S2 'PDIS'가 태그를 잃음)
    words = sorted(words, key=lambda w: (w["x0"], w["top"]))
    lines = []
    for w in words:
        reach = (prm["word_join_ratio"] if PAREN_TOKEN_RE.fullmatch(w["text"]) else prm["word_gap_ratio"]) * w["size"]
        fits = [ln for ln in lines if abs(ln["size"] - w["size"]) <= prm["line_size_tol"] and
                abs(ln["top"] - w["top"]) <= prm["line_top_ratio"] * w["size"] and
                -prm["word_overlap_ratio"] * w["size"] <= w["x0"] - ln["x1"] < reach]
        if fits:
            ln = min(fits, key=lambda ln: (abs(ln["top"] - w["top"]), w["x0"] - ln["x1"]))
            gap = w["x0"] - ln["x1"]
            ln["words"].append(w)
            ln["seps"].append("" if gap < prm["word_join_ratio"] * w["size"] else " ")
            ln["x1"] = w["x1"]
            ln["bottom"] = max(ln["bottom"], w["bottom"])
        else:
            lines.append({"words": [w], "seps": [""], "x0": w["x0"], "x1": w["x1"], "top": w["top"],
                          "bottom": w["bottom"], "size": w["size"]})
    lines.sort(key=lambda ln: (round(ln["top"], 1), ln["x0"]))
    blocks = []
    for ln in lines:
        for b in blocks:
            last = b["lines"][-1]
            gap = ln["top"] - last["bottom"]
            overlap = min(ln["x1"], last["x1"]) - max(ln["x0"], last["x0"])
            if abs(last["size"] - ln["size"]) <= prm["line_size_tol"] and overlap > 0 and \
                    prm["block_gap_min_ratio"] * ln["size"] <= gap <= prm["block_gap_max_ratio"] * ln["size"]:
                b["lines"].append(ln)
                break
        else:
            blocks.append({"lines": [ln]})
    out = []
    for b in blocks:
        box = (min(l["x0"] for l in b["lines"]), min(l["top"] for l in b["lines"]),
               max(l["x1"] for l in b["lines"]), max(l["bottom"] for l in b["lines"]))
        text = "\n".join("".join(s + w["text"] for s, w in zip(l["seps"], l["words"])) for l in b["lines"])
        out.append({"text": text, "bbox": box, "size": b["lines"][0]["size"],
                    "line_boxes": [(l["x0"], l["top"], l["x1"], l["bottom"]) for l in b["lines"]]})
    out.sort(key=lambda b: (round(b["bbox"][1], 2), round(b["bbox"][0], 2)))
    return out


# ---------------------------------------------------------------- 태그

def _bubble_like(node, letters):
    """종류를 못 정한 계기 모양 기호가 계기 원으로 볼 만한가: 기능 문자 두 자 이상이고 기호 짧은 변 8pt 이상.
    밸브 힌지 점·댐퍼 축 점처럼 작은 원 옆 밸브 번호('V5402', 'Y0013A')를 계기 태그로 읽지 않게 한다."""
    g = node.get("geometry") or {}
    return len(letters) >= 2 and min(g.get("width", 0), g.get("height", 0)) >= 8


def _assign_tags(nodes, unknowns, instrument_ids=(), valve_number_ids=()):
    """기호 노드의 tag를 같은 쪽의 보이는 글자로 정한다.
    (a) 글자가 태그 모양(③ 문서 언급과 같은 hazop.kg.docextract.TAG_RE)으로 시작하면 그 낱말.
    (b) 계기(분류가 계기이거나 instrument_ids의 계기 모양 기호)의 ISA 글자(예: 'PT 110')면 <접두>-<문자><번호>.
        접두는 같은 쪽 (a) 태그 두 개 이상이 함께 쓰는 계통 접두 중 가장 많은 것이다. 글자에 없는 값을 고른 것이라
        근거에 [추론]을 남기고, 가장 많은 접두가 둘 이상이면 정하지 않는다. 가장 많은 접두도 태그 하나뿐이거나
        (a) 태그가 없으면(APR1400 DCD처럼 계기 원에 접두를 쓰지 않는 도면) 원 안 글자 그대로 <문자>-<번호>로 둔다.
    (c) valve_number_ids의 밸브 노드(라벨 문단에 가장 가까운 기호가 그 밸브인 것, pdf_vector._valve_labels)는 라벨에
        수동 밸브 번호('V1681') 줄이 하나 있으면 그 번호. 계통 접두는 붙이지 않는다(글자에 없다). (b)의 접두를 셀 때는
        넣지 않는다.
    같은 tag가 두 노드 이상에 나오면 모두 비우고 duplicate_tag 미확인을 남긴다. 정하지 못한 노드는 missing_tag 미확인."""
    tags, isa = {}, {}
    for i, n in enumerate(nodes):
        if n["kind"] in rules.KINDS_WITHOUT_TAG:
            continue
        m = TAG_RE.match(n["label_text"].strip())
        if m:
            tags[i] = (m.group(0), "label_tag_token")
            continue
        lines = [" ".join(l.split()) for l in n["label_text"].splitlines() if l.strip()]
        numbers = [l for l in lines if VALVE_TAG_RE.fullmatch(l)]
        if n["local_id"] in valve_number_ids and n["category"] == "valve" and len(numbers) == 1:
            tags[i] = (numbers[0], "valve_number")
            continue
        m = ISA_LABEL_RE.fullmatch(" ".join(lines[:2]))
        if m and (n["category"] == "instrument" or n["local_id"] in instrument_ids and _bubble_like(n, m.group(1))):
            isa[i] = (m.group(1), m.group(2))
    counts = collections.Counter(t.split("-")[0] for t, b in tags.values() if b == "label_tag_token").most_common(2)
    tied = len(counts) == 2 and counts[0][1] == counts[1][1]
    prefix = counts[0][0] if counts and not tied and counts[0][1] >= 2 else None
    for i, (letters, number) in isa.items():
        if prefix:
            tags[i] = ("%s-%s%s" % (prefix, letters, number), "isa_label+page_prefix:%s [추론]" % prefix)
        elif not tied:
            tags[i] = ("%s-%s" % (letters, number), "isa_label")
    seen = collections.Counter(t.casefold() for t, _ in tags.values())
    for i, n in enumerate(nodes):
        if n["kind"] in rules.KINDS_WITHOUT_TAG:
            continue
        tag, basis = tags.get(i, (None, None))
        if tag is not None and seen[tag.casefold()] > 1:
            _issue(unknowns, "duplicate_tag", "같은 쪽에서 태그 %r 가 두 노드 이상에 나옴(어느 것인지 정하지 않음)" % tag,
                   n["source_object_id"], n["local_id"], "tag")
            tag, basis = None, "duplicate_on_page"
        n["tag"] = tag
        n["evidence"]["tag_basis"] = basis
        if tag is None and basis is None:
            reason = ("ISA 계기 글자는 있으나 같은 쪽 계통 접두를 하나로 정할 수 없음" if i in isa
                      else "보이는 글자에서 태그를 정하지 못함(글자는 label_text에 보존)")
            _issue(unknowns, "missing_tag", reason, n["source_object_id"], n["local_id"], "tag")
