"""Excel 한 장 기준 양식(기획서/평가기준비교.md §2.2) → 정본 JSON(§2.1).

- 시트 '평가기준'. 1–9행 A열 항목명·B열 값, 11행 머리글(A–R 고정), 12행부터 원인 행 1개 = Excel 1행.
- 수식 셀은 계산값을 쓰지 않고 차단한다. H·I·J(또는 M·N)의 줄 수가 다르면 차단한다.
- 변환에서 값을 만들지 않는다. 빈 키워드·빈 태그는 그대로 남겨 §2 검사에서 차단되게 한다.
- 정본 기본값(required: true, expected: "scenarios", recommendations: [], safeguards: null)은 명시적으로 채운다.
"""

import datetime

from openpyxl import load_workbook

from hazop.evaluate.criteria import FORMAT, FORMAT_VERSION, CriteriaError

NAME = "xlsx_sheet"
VERSION = "0.1.0"
SHEET = "평가기준"
META_LABELS = ("기준 ID", "기준 버전", "구간 ID", "운전모드", "출처 구분", "작성자", "작성 시각", "메모", "태그 별칭")
HEADER_ROW, FIRST_ROW = 11, 12
HEADERS = ("행 ID", "항목 ID", "파라미터", "가이드워드", "원인", "원인 설비", "원인 키워드", "결과", "결과 설비",
           "결과 키워드", "보호수단 태그", "보호수단 키워드", "권고", "권고 키워드", "필수", "비고", "편차 이름", "편차 기대")
NONE_MARK = "없음"
NO_SCENARIO = "시나리오 없음"


MULTILINE_COLS = (7, 8, 9, 11, 12, 13)  # H·I·J·L·M·N열(0부터): 줄 = 항목이므로 줄바꿈을 보존한다


def _text(v, keep_lines=False):
    """셀 값 → 문자열(빈칸·공백만이면 None). 정수 같은 실수는 정수 표기.
    keep_lines: 여러 줄 열은 앞뒤 공백·탭만 다듬고 줄바꿈은 지우지 않는다(빈 첫 줄도 항목 1개)."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, datetime.datetime):
        v = v.isoformat()
    s = str(v).replace("\r\n", "\n")
    if not s.strip():
        return None
    return s.strip(" \t") if keep_lines else s.strip()


def _lines(s):
    return s.split("\n") if s is not None else []


def _tags(s):
    return [t.strip() for t in s.split(";")]


def _groups(s):
    return [[w.strip() for w in g.split("|")] for g in s.split(";")]


def _formula_cells(ws):
    return [c.coordinate for row in ws.iter_rows() for c in row if c.data_type == "f"]


def _meta(ws, errs):
    meta = {}
    for i, label in enumerate(META_LABELS, 1):
        got = _text(ws.cell(row=i, column=1).value)
        if got != label:
            errs.append("%d행 A열 항목명이 %r가 아님: %r" % (i, label, got))
        meta[label] = ws.cell(row=i, column=2).value
    return meta


def _aliases(s, errs):
    out = {}
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            errs.append("태그 별칭 %r: '별칭=태그' 형식이 아님" % part)
            continue
        k, v = (x.strip() for x in part.split("=", 1))
        if k in out:
            errs.append("태그 별칭 %r가 두 번 나옴" % k)
        out[k] = v
    return out


def _safeguards(k, l, where, errs):
    if k is None and l is None:
        return None
    if k == NONE_MARK:
        if l is not None:
            errs.append("%s: K열 '없음'과 L열 보호수단 키워드가 함께 있음(모순)" % where)
        return []
    items = [{"tag": t} for t in _tags(k)] if k is not None else []
    items += [{"keywords": _groups(line)} for line in _lines(l)]
    return items


def _row(cells, where, errs):
    (rid, _item, _param, _gw, cause, c_eq, c_kw, cons, cons_eq, cons_kw, sg_tag, sg_kw, rec, rec_kw,
     required, note, _label, _expected) = cells
    row = {"row_id": rid}
    cause_obj = {"text": cause}
    if c_eq is not None:
        cause_obj["equipment"] = _tags(c_eq)
    if c_kw is not None:
        cause_obj["keywords"] = _groups(c_kw)
    row["cause"] = cause_obj
    h, i, j = _lines(cons), _lines(cons_eq), _lines(cons_kw)
    if len(j) != len(h) or (cons_eq is not None and len(i) != len(h)):
        errs.append("%s: H·I·J열 줄 수가 다름(결과 %d줄, 결과 설비 %s줄, 결과 키워드 %d줄)"
                    % (where, len(h), len(i) if cons_eq is not None else "빈칸", len(j)))
    consequences = []
    for n, text in enumerate(h):
        c = {"text": text.strip()}
        if n < len(i) and i[n].strip():
            c["equipment"] = _tags(i[n])
        if n < len(j):
            c["keywords"] = _groups(j[n])
        consequences.append(c)
    row["consequences"] = consequences
    row["safeguards"] = _safeguards(sg_tag, sg_kw, where, errs)
    m, nk = _lines(rec), _lines(rec_kw)
    if len(m) != len(nk):
        errs.append("%s: M·N열 줄 수가 다름(권고 %d줄, 권고 키워드 %d줄)" % (where, len(m), len(nk)))
    row["recommendations"] = [{"text": t.strip(), "keywords": _groups(k)} for t, k in zip(m, nk)]
    row["required"] = {None: True, "Y": True, "N": False}.get(required, required)
    if note is not None:
        row["note"] = note
    return row


def load(path):
    """반환 (criteria_dict, notes). 양식 오류·수식 셀·줄 수 불일치는 CriteriaError."""
    try:
        wb = load_workbook(path)  # data_only=False: 수식 셀을 수식으로 읽어 차단한다
    except Exception as exc:  # openpyxl은 손상 파일에서 여러 종류의 예외를 낸다
        raise CriteriaError("기준 Excel을 열 수 없음: %s" % exc)
    if SHEET not in wb.sheetnames:
        raise CriteriaError("시트 '%s' 없음(있는 시트: %s)" % (SHEET, ", ".join(wb.sheetnames)))
    ws = wb[SHEET]
    errs = []
    formulas = _formula_cells(ws)
    if formulas:
        errs.append("수식 셀은 기준으로 쓰지 않음(계산값 미사용): %s" % ", ".join(formulas))
    meta = _meta(ws, errs)
    headers = tuple(_text(ws.cell(row=HEADER_ROW, column=c).value) for c in range(1, len(HEADERS) + 1))
    if headers != HEADERS:
        errs.append("%d행 머리글이 고정 양식(A–R)과 다름: %r" % (HEADER_ROW, headers))
    if errs:
        raise CriteriaError(errs)

    version = meta["기준 버전"]
    if isinstance(version, float) and version.is_integer():
        version = int(version)
    if version is not None and not isinstance(version, (int, float, str, bool)):
        version = _text(version)  # 날짜·시간형 셀(예: "1-1" 자동 변환)은 문자열로 — 기준 검사에서 차단됨
    doc = {"format": FORMAT, "format_version": FORMAT_VERSION, "criteria_id": _text(meta["기준 ID"]),
           "criteria_version": version, "region_id": _text(meta["구간 ID"]),
           "operating_mode": _text(meta["운전모드"]), "provenance": {"kind": _text(meta["출처 구분"])}}
    for label, key in (("작성자", "author"), ("작성 시각", "created_at"), ("메모", "note")):
        if _text(meta[label]) is not None:
            doc["provenance"][key] = _text(meta[label])
    if _text(meta["태그 별칭"]) is not None:
        doc["tag_aliases"] = _aliases(_text(meta["태그 별칭"]), errs)

    groups, order, seen_ids, skipped = {}, [], set(), 0
    for r in range(FIRST_ROW, ws.max_row + 1):
        cells = [_text(ws.cell(row=r, column=c).value, c - 1 in MULTILINE_COLS) for c in range(1, len(HEADERS) + 1)]
        if all(v is None for v in cells):
            skipped += 1
            continue
        where = "%d행(행 ID %s)" % (r, cells[0])
        if cells[0] is None:
            errs.append("%d행: A열 행 ID 없음" % r)
        elif cells[0] in seen_ids:
            errs.append("%s: 행 ID 중복" % where)
        seen_ids.add(cells[0])
        item, param, gw, label, expected = cells[1], cells[2], cells[3], cells[16], cells[17]
        key = ("item", item) if item is not None else ("pg", param, gw)
        if key not in groups:
            groups[key] = {"ref": (item, param, gw), "label": label, "expected": [], "rows": [], "first": r}
            order.append(key)
        g = groups[key]
        if g["ref"] != (item, param, gw):
            errs.append("%s: 같은 편차의 항목 ID·파라미터·가이드워드가 %d행과 다름" % (where, g["first"]))
        if g["label"] != label:
            errs.append("%s: 같은 편차의 Q열 편차 이름이 %d행과 다름" % (where, g["first"]))
        exp = {None: "scenarios", NO_SCENARIO: "no_scenario"}.get(expected, expected)
        g["expected"].append(exp)
        if exp == "no_scenario":
            if any(v is not None for v in cells[4:16]):
                errs.append("%s: '시나리오 없음' 행은 E–P열이 비어야 함" % where)
            continue
        g["rows"].append(_row(cells, where, errs))
    if errs:
        raise CriteriaError(errs)

    deviations = []
    for key in order:
        g = groups[key]
        item, param, gw = g["ref"]
        ref = {"parameter": param, "guide_word": gw}
        if item is not None:
            ref["item_id"] = item
        exps = set(g["expected"])
        if "no_scenario" in exps and len(g["expected"]) > 1:
            raise CriteriaError("%d행 편차: '시나리오 없음' 행은 그 편차의 유일한 행이어야 함" % g["first"])
        dev = {"deviation_ref": ref, "expected": g["expected"][0] if len(exps) == 1 else sorted(exps),
               "rows": g["rows"]}
        if g["label"] is not None:
            dev["label"] = g["label"]
        deviations.append(dev)
    doc["deviations"] = deviations
    notes = ["시트 '%s' 고정 양식(§2.2, 1–9행 메타·11행 머리글·A–R열)으로 읽음" % SHEET,
             "원인 행 %d개·편차 %d개 변환, 빈 행 %d개 건너뜀" % (sum(len(groups[k]["rows"]) for k in order),
                                                    len(order), skipped),
             "safeguards[].text는 양식에 없어 생략(§2.2)"]
    return doc, notes
