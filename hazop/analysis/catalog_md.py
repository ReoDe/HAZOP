"""기획서/HAZOP기법지침.md §5.3 표 -> 이탈 후보 카탈로그·적용 판단 JSON (§8.1 필드).

데이터 파일(데이터/이탈후보/)은 이 변환 결과를 저장한 것이다. 검사 스크립트는 지침서 표를 다시 읽어
저장된 파일과 같은지 대조한다(지침서와 데이터 파일이 어긋나면 실패).
"""

import re

GUIDE_DOC = "기획서/HAZOP기법지침.md"
SECTION = "### 5.3 기계 판독용 이탈 후보 목록"
CATALOG_ID = "kosha-p86-2017-deviation-chart"
CATALOG_VERSION = 1
APPLICABILITY_ID = "applicability-region-SNP-M-102-pzr"
APPLICABILITY_VERSION = 1
REGION_ID = "region-SNP-M-102-pzr"
APPLICABILITY_MAP = {"적용": "applicable", "적용 불가": "not_applicable", "검토 필요": "needs_review"}
SAME = "같음"


def parse_guide_table(md_path):
    """§5.3 표의 데이터 행(p86-dNN)을 열 이름 -> 값 dict 목록으로 돌려준다."""
    with open(md_path, encoding="utf-8") as fh:
        text = fh.read()
    start = text.index(SECTION)
    end = text.index("\n### ", start + len(SECTION))
    rows = []
    for line in text[start:end].splitlines():
        if not line.startswith("| p86-d"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 8:
            raise ValueError("§5.3 표 열 수가 8이 아님: %r" % line)
        rows.append(dict(zip(("id", "parameter", "guide_word", "deviation", "deviation_en", "batch_specific",
                              "applicability", "basis"), cells)))
    return rows


def _guide_word(cell):
    m = re.fullmatch(r"(.+?) \((.+)\)", cell)
    ko, en = m.group(1), m.group(2)
    if en == "-":
        return ko, None, None
    if en.endswith("[추론]"):
        return ko, en.replace("[추론]", "").strip(), "추론"
    return ko, en, "표2"


def _deviation_en(cell):
    """'More flow (별표2)' -> (영문, 출처, 참고). '-'로 시작하면 영문 없음(번역하지 않음)."""
    if cell.startswith("-"):
        note = re.search(r"\((참고: .+)\)", cell)
        return None, None, note.group(1) if note else None
    m = re.fullmatch(r"(.+?) \((.+)\)", cell)
    return m.group(1), m.group(2), None


def _batch(cell):
    if cell == "아니오":
        return False, None
    m = re.fullmatch(r"예 \((.+)\)", cell)
    return True, m.group(1)


def rows_to_files(rows):
    """(카탈로그 dict, 적용 판단 dict). '같음'은 바로 앞 행의 판단 근거로 풀어 쓰고 원문도 남긴다."""
    items, app_items = [], []
    prev_reason = None
    for r in rows:
        gw_ko, gw_en, gw_src = _guide_word(r["guide_word"])
        dev_en, dev_src, dev_note = _deviation_en(r["deviation_en"])
        batch, batch_basis = _batch(r["batch_specific"])
        written = r["basis"]
        if written == SAME:
            reason = prev_reason
        elif written.startswith(SAME + "."):
            reason = prev_reason + written[len(SAME):]
        else:
            reason = written
            prev_reason = written  # '같음'은 덧붙인 문장 없이 마지막으로 새로 쓴 근거를 가리킨다고 봄 [추론]
        items.append({
            "item_id": r["id"], "parameter_ko": r["parameter"], "guide_word_ko": gw_ko, "guide_word_en": gw_en,
            "guide_word_en_source": gw_src, "deviation_ko": r["deviation"], "deviation_en": dev_en,
            "deviation_en_source": dev_src, "deviation_en_note": dev_note,
            "batch_specific": batch, "batch_specific_basis": batch_basis,
        })
        applicability = APPLICABILITY_MAP[r["applicability"]]
        app_items.append({
            "item_id": r["id"], "applicability": applicability,
            "applicability_basis": ("사용자 결정 2026-11-04" if applicability == "not_applicable"
                                    else "HAZOP기법지침 §5.3 판단 열"),
            "applicability_reason": reason,
            "applicability_reason_as_written": written,
            "applicability_knowledge_status": "hypothesis" if ("[추론]" in reason or "[일반지식]" in reason)
            else "confirmed",
        })
    catalog = {
        "catalog_id": CATALOG_ID, "catalog_version": CATALOG_VERSION,
        "source": {"doc": "KOSHA GUIDE P-86-2017", "table": "별표3", "pdf_page": 24, "is_example": True,
                   "transcribed_from": GUIDE_DOC + " §5.3"},
        "note": "원문 표는 (예시). 이 파일은 지침서 §5.3 표를 hazop/analysis/catalog_md.py로 옮긴 것",
        "review_items": [
            {"item": "대체/기타", "reason": "별표3 열 이름은 '대체', 표2·별표6은 '기타(Other than)'. 대체->Other than 대응은 [추론]"},
            {"item": "열 순서", "reason": "별표3과 별표6의 반대·부분·부가 순서가 다름. 의미 없다고 봄 [추론]"},
            {"item": "반응·혼합 분류", "reason": "표1은 일반변수, 별표3은 가이드워드와 조합. 별표3을 따름"},
            {"item": "시퀀스 명칭", "reason": "별표3 '부가 조작'·'틀린 조작'을 표4 '다른 조작'·'기타 오조작'에 대응 [추론]"},
            {"item": "별표3에 없는 변수", "reason": "점도·압력방출·시료채취 등은 집계 제외(지침서 §5.4 보조 후보)"},
        ],
        "items": items,
    }
    applicability = {
        "applicability_id": APPLICABILITY_ID, "applicability_version": APPLICABILITY_VERSION,
        "region_id": REGION_ID, "operating_mode": "normal",
        "catalog_ref": {"catalog_id": CATALOG_ID, "catalog_version": CATALOG_VERSION},
        "source": GUIDE_DOC + " §5.3 applicability·판단 근거 열 (사용자 결정 2026-11-04)",
        "items": app_items,
    }
    return catalog, applicability


# ---------------------------------------------------------------- §6 위험도 기준표(〈표5〉~〈표9〉)
def _table_after(text, marker):
    """marker 다음에 나오는 첫 마크다운 표의 데이터 행(머리·구분선 제외)."""
    lines = text[text.index(marker):].splitlines()
    rows, started = [], False
    for line in lines[1:]:
        if line.startswith("|"):
            started = True
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif started:
            break
    return rows[2:]


def parse_risk_tables(md_path):
    """지침서 §6 표 -> 기준표 JSON의 matrix·severity_levels·frequency_levels·risk_levels 형식."""
    with open(md_path, encoding="utf-8") as fh:
        text = fh.read()
    lead = lambda s: re.match(r"(\d)", s).group(1)  # noqa: E731
    label = lambda s: re.search(r"\((.+)\)", s).group(1)  # noqa: E731
    t5 = _table_after(text, "〈표5〉 위험도 대조표")
    cols = ["3", "2", "1"]
    matrix = {lead(r[0]): {c: int(v) for c, v in zip(cols, r[1:])} for r in t5}
    names = {r[0]: r[1] for r in _table_after(text, "〈표6〉 위험도 기준")}
    freq = {lead(r[0]): "%s: %s" % (label(r[0]), r[1]) for r in _table_after(text, "〈표7〉 발생빈도의 구분")}
    sev = {lead(r[0]): "%s: %s" % (label(r[0]), r[1]) for r in _table_after(text, "〈표8〉 강도의 구분")}
    levels, prev = {}, None
    for r in _table_after(text, "〈표9〉 위험도 평가"):
        k = lead(r[0])
        acc = prev if r[2] == "(위와 병합)" else r[2].split(" (")[0]
        prev = acc
        levels[k] = {"name": names[k], "management": r[1], "acceptance": acc}
    return {"matrix": matrix, "severity_levels": sev, "frequency_levels": freq, "risk_levels": levels}
