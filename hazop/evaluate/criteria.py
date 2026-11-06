"""평가 기준 정본 JSON 검사·정규화 (기획서/평가기준비교.md §2.1, §3.1).

- validate_criteria(doc): §2.1의 필수·형식·중복 검사. 오류 목록(빈 목록이면 통과). 행 오류에는 행 ID를 넣는다.
- 정규화는 hazop.extract.adapters.evaluation.normalize_text와 같은 규칙(NFKC → 공백 제거 → 대문자).
- 태그 등장 판정(tag_in_text)은 앞뒤 글자가 [A-Z0-9-]가 아닐 때만 인정한다(한글 조사는 경계).
"""

import re

from hazop.extract.adapters.evaluation import normalize_text

FORMAT = "hazop-criteria"
FORMAT_VERSION = "0.1"
PROVENANCE_KINDS = ("user", "synthetic")
EXPECTED = ("scenarios", "no_scenario")
_TAG_CHAR = re.compile(r"[A-Z0-9-]")
_OR_SPLIT = re.compile(r",|(?<!\S)or(?!\S)")


class CriteriaError(ValueError):
    """기준 읽기·변환 실패. errors에 사유 목록."""

    def __init__(self, errors):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


def norm(text):
    return normalize_text(text)


def alias_map(doc):
    """정규화한 {별칭: 도면 태그}. 형식 검사는 validate_criteria 몫."""
    out = {}
    for k, v in (doc.get("tag_aliases") or {}).items():
        out[norm(k)] = norm(v)
    return out


def norm_tag(tag, aliases):
    t = norm(tag)
    return aliases.get(t, t)


def tag_in_text(tag_n, text_n):
    """정규화한 문장 text_n에 정규화한 태그 tag_n이 경계 조건(§3.1)을 지키며 나오는지."""
    if not tag_n:
        return False
    start = text_n.find(tag_n)
    while start >= 0:
        end = start + len(tag_n)
        before = text_n[start - 1] if start > 0 else ""
        after = text_n[end] if end < len(text_n) else ""
        if not (before and _TAG_CHAR.match(before)) and not (after and _TAG_CHAR.match(after)):
            return True
        start = text_n.find(tag_n, start + 1)
    return False


def groups_satisfied(groups, text_n):
    """키워드 그룹 중 만족한 그룹 수(그룹 안은 OR, 부분 문자열 포함)."""
    return sum(1 for g in groups or [] if any(norm(w) in text_n for w in g))


def all_groups(groups, text_n):
    return groups_satisfied(groups, text_n) == len(groups or [])


def guide_word_forms(guide_word_ko, guide_word_en):
    """후보 가이드워드의 비교 형태(정규화): 한국어, 영문 전체, 영문을 ','·단어 'or'로 나눈 각 부분."""
    forms = {norm(guide_word_ko)}
    if guide_word_en is not None:
        forms.add(norm(guide_word_en))
        forms.update(norm(p) for p in _OR_SPLIT.split(str(guide_word_en)) if norm(p))
    forms.discard("")
    return forms


def deviation_key(dev):
    """§3.1 키: item_id가 있으면 ("item", item_id), 없으면 ("pg", 파라미터, 가이드워드) — 모두 정규화."""
    ref = dev.get("deviation_ref") if isinstance(dev.get("deviation_ref"), dict) else {}
    if ref.get("item_id"):
        return ("item", norm(ref["item_id"]))
    return ("pg", norm(ref.get("parameter")), norm(ref.get("guide_word")))


# ---------------------------------------------------------------- 검사
def _is_text(v):
    return isinstance(v, str) and bool(v.strip())


def _check_groups(groups, where, errs, required):
    if groups is None:
        if required:
            errs.append("%s: keywords 필수(1그룹 이상)" % where)
        return
    if not isinstance(groups, list):
        errs.append("%s: keywords는 그룹 배열이어야 함" % where)
        return
    if required and not groups:
        errs.append("%s: keywords 필수(1그룹 이상)" % where)
    for i, g in enumerate(groups, 1):
        if not isinstance(g, list) or not g:
            errs.append("%s: 키워드 그룹 %d이 빈 그룹이거나 배열이 아님" % (where, i))
            continue
        for w in g:
            if not isinstance(w, str) or not norm(w):
                errs.append("%s: 키워드 그룹 %d에 빈 문자열·문자열 아닌 키워드" % (where, i))


def _check_tags(tags, where, errs):
    if tags is None:
        return
    if not isinstance(tags, list) or any(not isinstance(t, str) or not norm(t) for t in tags):
        errs.append("%s: equipment는 빈 값이 아닌 태그 문자열 배열이어야 함" % where)


def _check_opt_str(d, key, where, errs):
    if key in d and d[key] is not None and not isinstance(d[key], str):
        errs.append("%s: %s는 문자열이어야 함" % (where, key))


def validate_criteria(doc):
    """§2.1 검사. 오류 목록."""
    errs = []
    if not isinstance(doc, dict):
        return ["기준 파일 최상위가 객체가 아님"]
    if doc.get("format") != FORMAT or doc.get("format_version") != FORMAT_VERSION:
        errs.append("format·format_version이 %r·%r가 아님: %r·%r"
                    % (FORMAT, FORMAT_VERSION, doc.get("format"), doc.get("format_version")))
    if not _is_text(doc.get("criteria_id")):
        errs.append("criteria_id 없음")
    cv = doc.get("criteria_version")
    if type(cv) is not int or cv < 1:
        errs.append("criteria_version은 1 이상 정수: %r" % (cv,))
    for key in ("region_id", "operating_mode"):
        if not _is_text(doc.get(key)):
            errs.append("%s 없음" % key)
    prov = doc.get("provenance")
    if not isinstance(prov, dict) or prov.get("kind") not in PROVENANCE_KINDS:
        errs.append("provenance.kind는 user 또는 synthetic: %r" % ((prov or {}).get("kind") if isinstance(prov, dict)
                                                                   else prov,))
    else:
        for key in ("author", "created_at", "note"):
            _check_opt_str(prov, key, "provenance", errs)
    aliases = doc.get("tag_aliases")
    if aliases is not None:
        if not isinstance(aliases, dict) or any(not isinstance(k, str) or not norm(k) or not isinstance(v, str)
                                                or not norm(v) for k, v in aliases.items()):
            errs.append("tag_aliases는 {별칭: 도면 태그} 문자열 객체여야 함")
        else:
            keys = [norm(k) for k in aliases]
            if len(set(keys)) != len(keys):
                errs.append("tag_aliases: 정규화 후 같은 별칭이 둘 이상")
            for k, v in aliases.items():
                if norm(v) in keys:
                    errs.append("tag_aliases: 별칭 연쇄 금지 — %s → %s의 대상이 다시 별칭임" % (k, v))
    devs = doc.get("deviations")
    if not isinstance(devs, list) or not devs:
        errs.append("deviations는 1개 이상 배열이어야 함")
        return errs
    seen_rows, seen_devs = set(), set()
    for di, dev in enumerate(devs, 1):
        dw = "편차 %d" % di
        if not isinstance(dev, dict):
            errs.append("%s: 객체가 아님" % dw)
            continue
        ref = dev.get("deviation_ref")
        if not isinstance(ref, dict):
            errs.append("%s: deviation_ref 없음" % dw)
            ref = {}
        if not _is_text(ref.get("parameter")):
            errs.append("%s: deviation_ref.parameter 없음" % dw)
        if not isinstance(ref.get("guide_word"), str) or not norm(ref.get("guide_word")):
            errs.append("%s: deviation_ref.guide_word가 정규화 후 빈 문자열" % dw)
        _check_opt_str(ref, "item_id", dw, errs)
        _check_opt_str(dev, "label", dw, errs)
        key = deviation_key(dev)
        if key in seen_devs:
            errs.append("%s: 같은 편차가 두 번 나옴 %r" % (dw, key))
        seen_devs.add(key)
        expected = dev.get("expected", "scenarios")
        if expected not in EXPECTED:
            errs.append("%s: expected는 scenarios 또는 no_scenario: %r" % (dw, expected))
        rows = dev.get("rows")
        if not isinstance(rows, list):
            errs.append("%s: rows는 배열이어야 함" % dw)
            continue
        if expected == "scenarios" and not rows:
            errs.append("%s: expected가 scenarios면 rows 1개 이상" % dw)
        if expected == "no_scenario" and rows:
            errs.append("%s: expected가 no_scenario면 rows는 빈 배열" % dw)
        for ri, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                errs.append("%s 행 %d: 객체가 아님" % (dw, ri))
                continue
            rid = row.get("row_id")
            w = "행 %s" % rid
            if not _is_text(rid):
                errs.append("%s 행 %d: row_id 없음" % (dw, ri))
                w = "%s 행 %d" % (dw, ri)
            elif rid in seen_rows:
                errs.append("%s: row_id 중복" % w)
            else:
                seen_rows.add(rid)
            if "required" in row and not isinstance(row["required"], bool):
                errs.append("%s: required는 true/false" % w)
            cause = row.get("cause")
            if not isinstance(cause, dict):
                errs.append("%s: cause 없음" % w)
                cause = {}
            if not _is_text(cause.get("text")):
                errs.append("%s: cause.text 없음" % w)
            _check_tags(cause.get("equipment"), "%s cause" % w, errs)
            _check_groups(cause.get("keywords"), "%s cause" % w, errs, required=False)
            if not cause.get("equipment") and not cause.get("keywords"):
                errs.append("%s: cause.equipment와 cause.keywords가 모두 비어 있음" % w)
            cons = row.get("consequences")
            if not isinstance(cons, list) or not cons:
                errs.append("%s: consequences는 1개 이상 배열" % w)
                cons = []
            for ci, c in enumerate(cons, 1):
                cw = "%s 결과 #%d" % (w, ci)
                if not isinstance(c, dict) or not _is_text(c.get("text")):
                    errs.append("%s: text 없음" % cw)
                    continue
                _check_tags(c.get("equipment"), cw, errs)
                _check_groups(c.get("keywords"), cw, errs, required=True)
            sgs = row.get("safeguards")
            if sgs is not None:
                if not isinstance(sgs, list):
                    errs.append("%s: safeguards는 배열 또는 null" % w)
                    sgs = []
                for gi, g in enumerate(sgs, 1):
                    gw = "%s 보호수단 #%d" % (w, gi)
                    if not isinstance(g, dict):
                        errs.append("%s: 객체가 아님" % gw)
                        continue
                    if g.get("tag") is None and g.get("keywords") is None:
                        errs.append("%s: tag 또는 keywords 중 하나 이상 필요" % gw)
                    if g.get("tag") is not None and (not isinstance(g["tag"], str) or not norm(g["tag"])):
                        errs.append("%s: tag가 빈 값" % gw)
                    if g.get("keywords") is not None:
                        _check_groups(g["keywords"], gw, errs, required=True)
                    _check_opt_str(g, "text", gw, errs)
            recs = row.get("recommendations", [])
            if not isinstance(recs, list):
                errs.append("%s: recommendations는 배열" % w)
                recs = []
            for ki, r in enumerate(recs, 1):
                kw = "%s 권고 #%d" % (w, ki)
                if not isinstance(r, dict) or not _is_text(r.get("text")):
                    errs.append("%s: text 없음" % kw)
                    continue
                _check_groups(r.get("keywords"), kw, errs, required=True)
            _check_opt_str(row, "note", w, errs)
    return errs


def criteria_tags(doc):
    """기준에 쓰인 태그 목록 [(원래 값, 행 ID, 위치)] — 원인 설비·결과 설비·보호수단 태그."""
    out = []
    for dev in doc.get("deviations") or []:
        for row in dev.get("rows") or []:
            rid = row.get("row_id")
            for t in (row.get("cause") or {}).get("equipment") or []:
                out.append((t, rid, "cause"))
            for c in row.get("consequences") or []:
                for t in c.get("equipment") or []:
                    out.append((t, rid, "consequence"))
            for g in row.get("safeguards") or []:
                if g.get("tag") is not None:
                    out.append((g["tag"], rid, "safeguard"))
    return out
