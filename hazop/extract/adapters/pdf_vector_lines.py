"""벡터 PDF 배관 글자(pdf_vector에서 나눔): 구경·배관 번호 글자를 가장 가까운 물리 배관 관계의 속성으로 붙인다.

규격: docs/specs/extraction.md '읽기 품질 지표'(속성: 배관 옆 구경·배관 번호 글자). 글자 꼴로만 고르고, 붙이는 곳은
글자 가운데에서 가장 가까운 물리 배관(경로 거리)이다. 쪽 좌표·번호로 가르는 예외는 두지 않는다.
- 구경: 3/4" · ¾" · 1½" · 24" · 36"X24"(리듀서 표기) → 관계 attributes["size"], ASCII 분수('1-1/2"')로 바꿔 적는다.
- 배관 번호: 계통 약어-L번호(예: RC-L011) → 관계 line_no.
"""

import math
import re

from .pdf_vector_common import _seg_dist, _segs

FRACTIONS = {"¼": "1/4", "½": "1/2", "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}
_NUM = r"(?:\d+\.\d+|\d+(?:[ -]\d+/\d+)?|\d+/\d+)"  # 30.907" 같은 소수도
SIZE_RE = re.compile(r'^(%s)"(?:\s*[Xx]\s*(%s)")?$' % (_NUM, _NUM))
LINE_NO_RE = re.compile(r"^([A-Z]{1,4}-L\d{2,4}[A-Z]?)(?:\s|$)")  # 맨 앞 낱말('RC-L001 HOT LEG'의 RC-L001)
LINE_NO_ANY_RE = re.compile(r"(?<![A-Z0-9-])([A-Z]{1,4}-L\d{2,4}[A-Z]?)(?![A-Z0-9])")
REACH = 8.0         # 글자 가운데에서 배관까지 거리 상한(pt). 12pt면 배관이 못 된 선 옆 글자가 이웃 배관에 붙었다(105쪽 26")
REACH_PER_H = 1.5   # 글자 높이에 비례한 상한(큰 글자)


def _ascii(text):
    out = text.strip().replace("″", '"').replace("”", '"')
    for k, v in FRACTIONS.items():
        out = re.sub(r"(\d)%s" % k, r"\1-%s" % v, out)  # 1½ → 1-1/2
        out = out.replace(k, v)
    return out


def _canon_num(n):
    return n.replace(" ", "-")


def parse_label(text):
    """글자 → ("size", '3/4"') | ("line_no", "RC-L011") | None."""
    t = _ascii(text or "")
    m = SIZE_RE.match(t)
    if m:
        a, b = m.group(1), m.group(2)
        return "size", '%s"' % _canon_num(a) + ('X%s"' % _canon_num(b) if b else "")
    m = LINE_NO_RE.match(t)
    if m:
        return "line_no", m.group(1)
    return None


def _path(r):
    return [tuple(p) for p in ((r.get("evidence") or {}).get("pdf_path") or [])]


LEADER_GAP = 2.0     # 지시선의 떠 있는 끝과 글자 상자 사이 거리 상한(글자 높이의 배수). 134쪽 '4"' 지시선은 1.9·5.4pt(높이 3.1)
LEADER_LEN = 3.0     # 지시선 길이 상한(글자 높이의 배수)
LEADER_TIP = 1.0     # 지시선이 짚은 점에서 배관까지 거리 상한(pt)


def _leader(r, pts, box):
    """미해결 연결 r이 글자에서 배관으로 그은 짧은 지시선인가: 연결되지 않은 끝이 글자 상자 바로 앞에 있고 길이가 글자
    높이 몇 배 안이다. 지시선은 배관이 아니라 글자가 가리키는 배관을 짚는 선이다(APR1400 134쪽 LS 011 아래 '4"'
    지시선이 미해결 연결이 되자 구경 글자가 정답인 세로 배관 대신 지시선에 붙었다). 양 끝이 이어진 관계는 보지 않는다."""
    loose = [e["point"] for e in r.get("endpoints") or () if e.get("node_local_id") is None and e.get("point")]
    if not loose:
        return False
    x0, y0, x1, y1 = box
    h = min(x1 - x0, y1 - y0)
    if sum(math.dist(p, q) for p, q in zip(pts, pts[1:])) > LEADER_LEN * h:
        return False
    return any(max(x0 - e[0], e[0] - x1, y0 - e[1], e[1] - y1, 0.0) <= LEADER_GAP * h for e in loose)


def attach_line_labels(blocks, candidates, relations):
    """candidates(블록 번호) 가운데 배관 글자를 가장 가까운 물리 배관에 붙인다(제자리 고침). → 붙인 블록 번호 집합."""
    pipes = [(r, _path(r)) for r in relations if r.get("kind") == "physical_connection" and len(_path(r)) >= 2]
    used = set()
    for bi in candidates:
        b = blocks[bi]
        parsed = parse_label(b.get("text"))
        if not parsed or not pipes:
            continue
        x0, y0, x1, y1 = b["bbox"]
        c = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        reach = max(REACH, REACH_PER_H * min(x1 - x0, y1 - y0))
        dist, r = min(((min(_seg_dist(c, p, q)[0] for p, q in _segs(pts)), r) for r, pts in pipes),
                      key=lambda t: t[0])
        if _leader(r, _path(r), b["bbox"]):
            # 가장 가까운 것이 이 글자의 지시선이면, 지시선이 짚은 점(이어진 끝)을 지나는 배관 가운데 글자에서 가장 가까운
            # 것에 붙인다. 지시선이 이어 주므로 거리 상한은 보지 않는다. 그 점에서 떨어진 배관(같은 기기에 닿은 먼 배관)은
            # 보지 않는다(139쪽에서 기기 반대편 60pt 밖 배관에 붙던 자리)
            tips = [e["point"] for e in r["endpoints"] if e.get("node_local_id") and e.get("point")]
            target = [(q, pts) for q, pts in pipes if q is not r and any(
                min(_seg_dist(t, a, z)[0] for a, z in _segs(pts)) <= LEADER_TIP for t in tips)]
            if not target and dist > reach:
                continue
            if target:  # 지시선이 배관이 아닌 기호(축소관 등)를 짚으면 예전처럼 지시선에 둔다
                dist, r = min(((min(_seg_dist(c, p, q2)[0] for p, q2 in _segs(pts)), q) for q, pts in target),
                              key=lambda t: t[0])
        elif dist > reach:
            continue
        field, value = parsed
        if field == "line_no":
            if r.get("line_no") in (None, value):
                r["line_no"] = value
                used.add(bi)
        else:
            attrs = r.setdefault("attributes", {})
            if attrs.get("size") in (None, value):
                attrs["size"] = value
                used.add(bi)
    return used


def attach_continuation_line_numbers(nodes, relations):
    """도면 밖 연결 기호의 이름표에 배관 번호가 하나 들어 있고('TO SNP-M-201 CV-L001 LETDOWN') 그 기호에 붙은 물리 배관이
    하나뿐이면 그 배관의 line_no로 매긴다(제자리 고침). → 매긴 관계 수."""
    n = 0
    for node in nodes:
        if node.get("kind") != "continuation":
            continue
        found = set(LINE_NO_ANY_RE.findall((node.get("label_text") or "").upper()))
        if len(found) != 1:
            continue
        pipes = [r for r in relations if r.get("kind") == "physical_connection"
                 and node["local_id"] in [e.get("node_local_id") for e in r["endpoints"]]]
        if len(pipes) == 1 and pipes[0].get("line_no") in (None, next(iter(found))):
            pipes[0]["line_no"] = next(iter(found))
            n += 1
    return n
