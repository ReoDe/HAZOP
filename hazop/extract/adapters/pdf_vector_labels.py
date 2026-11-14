"""벡터 PDF 어댑터의 라벨 고르기(pdf_vector 설명글 5번·7번).

낱말을 줄·문단으로 묶고(_text_blocks), 보이는 글자로 노드 태그를 정한다(_assign_tags).
글자를 어느 기호에 붙일지는 pdf_vector.build_extraction 안에 남아 있다.
pdf_vector.py에서 그대로 옮겼다(F1-0). 예전 이름은 pdf_vector에서도 쓸 수 있다.
"""

import collections
import math
import re

from hazop.kg.docextract import TAG_RE

from .. import rules
from .pdf_vector_common import _box_gap, _issue

# ISA 계기 글자(기능 문자 + 번호, 예: 'PT 110'·'PIC 110'). 태그 앞 계통 접두는 글자에 없다.
ISA_LABEL_RE = re.compile(r"([A-Z]{1,4})[ \-]*(\d{1,5}[A-Z]?)")
# 수동 밸브 번호(APR1400 'V1681'). 계통 접두는 글자에 없다. 밸브 분류 노드의 라벨 한 줄이 이 꼴이면 그대로 태그로 쓴다
VALVE_TAG_RE = re.compile(r"V\d{3,5}[A-Z]?")
# 기기 번호(범례 1.7-1 2/4 'EQUIPMENT NUMBER': 기기 종류 두 자 + 일련번호 두 자 + 계열 문자, 'PP 01 A')와 댐퍼 번호('Y0029').
# 계통 접두는 글자에 없다. 종류 글자는 범례 NOTE 1 표에서, 도면이 그 표 밖에 쓰는 OR·ST는 기호 바로 아래 찍힌 것(016쪽
# OR05B, 097쪽 ST01A)에서 왔다. 글자 종류가 기호 종류와 맞을 때만 태그로 쓴다(펌프 옆 'TK01A'는 펌프 태그가 아니다)
EQUIPMENT_TAG_RE = re.compile(r"([A-Z]{2})\d{2}[A-Z]?|(Y)\d{4}[A-Z]?")
EQUIPMENT_CODE_KINDS = {
    "AC": {"accumulator"}, "CD": {"condenser"}, "CH": {"chiller"}, "CM": {"compressor"}, "DD": {"demineralizer"},
    "FT": {"filter"}, "HE": {"heat_exchanger"}, "PP": {"pump"}, "RV": {"reactor_vessel"}, "SG": {"steam_generator"},
    "TA": {"turbine"}, "TK": {"tank", "vessel"}, "OR": {"orifice"}, "ST": {"strainer"}, "Y": {"damper"},
}
PAREN_TOKEN_RE = re.compile(r"\(\d{1,5}[A-Z]?\)")  # 계기 원 옆 다른 계열 번호 '(3057)'·'(3004D)'. 설비 번호 '(FT32A)'는 아님
# 밸브 옆 위치 약어(범례 1.7-1 1/4·4/4, 속성 normal_position·fail_position). 'NC,FO'처럼 둘을 함께 쓴다
POSITION_TEXT_RE = re.compile(r"(?:NO|NC|LO|LC|LT|FO|FC|FL|FAI)(?:\s*[,/]?\s*(?:NO|NC|LO|LC|LT|FO|FC|FL|FAI))*")
POSITION_CODE_RE = re.compile(r"NO|NC|LO|LC|LT|FO|FC|FL|FAI")


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


def _number_and_position(a, b):
    """밸브 번호와 위치 약어가 한 줄에 나란히 찍힌 것('V310 LO', 'LO V751'). 번호는 태그, 약어는 속성이라 따로 둔다."""
    return any(VALVE_TAG_RE.fullmatch(x) and POSITION_TEXT_RE.fullmatch(y) for x, y in ((a, b), (b, a)))


def _line_text(ln):
    return "".join(s + w["text"] for s, w in zip(ln["seps"], ln["words"]))


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
                -prm["word_overlap_ratio"] * w["size"] <= w["x0"] - ln["x1"] < reach and
                not _number_and_position(ln["words"][-1]["text"], w["text"])]
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
                    prm["block_gap_min_ratio"] * ln["size"] <= gap <= prm["block_gap_max_ratio"] * ln["size"] and \
                    not _number_and_position(_line_text(last), _line_text(ln)):
                b["lines"].append(ln)
                break
        else:
            blocks.append({"lines": [ln]})
    out = []
    for b in blocks:
        box = (min(l["x0"] for l in b["lines"]), min(l["top"] for l in b["lines"]),
               max(l["x1"] for l in b["lines"]), max(l["bottom"] for l in b["lines"]))
        text = "\n".join(_line_text(l) for l in b["lines"])
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


def _nearest_prefix(node, tagged):
    """tagged [(노드, 태그)] 가운데 node 가운데에서 가장 가까운 노드의 태그 접두. 가장 가까운 거리에 접두가 둘이면 None."""
    def center(n):
        g = n.get("geometry") or {}
        return (g.get("x", 0) + g.get("width", 0) / 2.0, g.get("y", 0) + g.get("height", 0) / 2.0)
    c = center(node)
    ranked = sorted((math.dist(c, center(n)), t.split("-")[0]) for n, t in tagged)
    if not ranked or (len(ranked) > 1 and abs(ranked[0][0] - ranked[1][0]) < 1e-6 and ranked[0][1] != ranked[1][1]):
        return None
    return ranked[0][1]


def _node_box(n):
    g = n.get("geometry") or {}
    return (g.get("x", 0), g.get("y", 0), g.get("x", 0) + g.get("width", 0), g.get("y", 0) + g.get("height", 0))


def _assign_tags(nodes, unknowns, instrument_ids=(), valve_number_ids=(), label_lines=None):
    """기호 노드의 tag를 같은 쪽의 보이는 글자로 정한다.
    (a) 글자가 태그 모양(③ 문서 언급과 같은 hazop.kg.docextract.TAG_RE)으로 시작하면 그 낱말.
    (b) 계기(분류가 계기이거나 instrument_ids의 계기 모양 기호)의 ISA 글자(예: 'PT 110')면 <접두>-<문자><번호>.
        접두는 같은 쪽 (a) 태그 두 개 이상이 함께 쓰는 계통 접두 중 가장 많은 것이다. 글자에 없는 값을 고른 것이라
        근거에 [추론]을 남기고, 가장 많은 접두가 둘 이상이면 정하지 않는다. 가장 많은 접두도 태그 하나뿐이거나
        (a) 태그가 없으면(APR1400 DCD처럼 계기 원에 접두를 쓰지 않는 도면) 원 안 글자 그대로 <문자>-<번호>로 둔다.
    (d) 위 (c)가 없고 지시선으로 번호 원이 붙은 밸브(evidence.ident_number)는 그 번호('021').
    (c) valve_number_ids의 밸브 노드(라벨 문단에 가장 가까운 기호가 그 밸브인 것, pdf_vector._valve_labels)는 라벨에
        수동 밸브 번호('V1681') 줄이 하나 있으면 그 번호. 계통 접두는 붙이지 않는다(글자에 없다). (b)의 접두를 셀 때는
        넣지 않는다.
    (e) 위가 없고 라벨 문단의 한 줄이 기기 번호('PP02B', 'OR05B', 댐퍼 'Y0029')이며 그 종류 글자가 노드 종류와 맞고
        그 줄에 가장 가까운 같은 종류 기호가 이 노드면 그 번호. label_lines는 {local_id: [(줄 글자, 줄 상자)]}다.
    같은 tag가 두 노드 이상에 나오면 모두 비우고 duplicate_tag 미확인을 남긴다. 정하지 못한 노드는 missing_tag 미확인."""
    tags, isa, label_lines = {}, {}, label_lines or {}
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
        equipment = [(t.strip(), box, kinds) for t, box in label_lines.get(n["local_id"], ())
                     if (m := EQUIPMENT_TAG_RE.fullmatch(t.strip()))
                     and n["kind"] in (kinds := EQUIPMENT_CODE_KINDS.get(m.group(1) or m.group(2), ()))]
        if len(equipment) == 1:
            number, box, kinds = equipment[0]
            # 문단은 이 기호에 붙었어도 번호 줄은 같은 종류의 다른 기호 밑에 찍혔을 수 있다(063쪽 'OR05B' 줄과 두 이름 줄이
            # 한 문단이 되어 OR04B에 붙음). 번호 줄에 가장 가까운 같은 종류 기호가 이 기호일 때만 쓴다. 다른 종류 기호가 더
            # 가까운 것은 괜찮다(025쪽 펌프 이름 밑 'PP01A' 바로 아래 계기 원)
            if min((o for o in nodes if o["kind"] in kinds), key=lambda o: _box_gap(box, _node_box(o))) is n:
                tags[i] = (number, "equipment_number")
                continue
        ident = (n.get("evidence") or {}).get("ident_number")
        if ident and n["category"] == "valve" and n["kind"]:  # 종류를 못 정한 몸통 조각(일부만 잡힌 조절기 등)에는 붙이지 않는다
            # (d) 지시선으로 이 밸브에 붙은 번호 원(_apply_merges의 ident_number). 도면에 찍힌 번호 그대로(계통 접두 없음)
            tags[i] = (ident, "valve_ident_number")
            continue
        m = ISA_LABEL_RE.fullmatch(" ".join(lines[:2]))
        if m and (n["category"] == "instrument" or n["local_id"] in instrument_ids and _bubble_like(n, m.group(1))):
            isa[i] = (m.group(1), m.group(2))
    counts = collections.Counter(t.split("-")[0] for t, b in tags.values() if b == "label_tag_token").most_common(2)
    tied = len(counts) == 2 and counts[0][1] == counts[1][1]
    prefix = counts[0][0] if counts and not tied and counts[0][1] >= 2 else None
    top = {c for c, k in counts if k == counts[0][1]} if tied and counts[0][1] >= 2 else set()
    for i, (letters, number) in isa.items():
        if prefix:
            tags[i] = ("%s-%s%s" % (prefix, letters, number), "isa_label+page_prefix:%s [추론]" % prefix)
        elif top:
            # 쪽에서 가장 많은 접두가 둘 이상 같은 수면(두 계통이 한 쪽에) 이 계기에서 가장 가까운 글자 태그의 접두를 쓴다
            near = _nearest_prefix(nodes[i], [(nodes[j], t) for j, (t, b) in tags.items()
                                              if b == "label_tag_token" and t.split("-")[0] in top])
            if near:
                tags[i] = ("%s-%s%s" % (near, letters, number), "isa_label+near_prefix:%s [추론]" % near)
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
