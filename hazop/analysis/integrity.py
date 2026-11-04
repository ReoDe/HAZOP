"""④ 기준 데이터 무결성 검사 (로드 시 실행, 위반이면 분석 차단).

- 이탈 후보 카탈로그·적용 판단: p86-d01~d44 44행, ID 고유, 고정 해시(PINNED_SHA256) 일치,
  지침서(기획서/HAZOP기법지침.md §5.3)를 다시 읽어 변환한 내용과 일치
- 위험도 기준표: 고정 해시 일치, 코드 상수(risk.MATRIX_P86)와 〈표5〉 일치, 지침서 §6 〈표5〉~〈표9〉 파싱 결과와 일치
기준 데이터를 정당하게 바꿀 때는 지침서·데이터 파일을 함께 고친 뒤 이 파일의 PINNED_SHA256을 갱신한다
(값: hazop.analysis.integrity.content_sha256(문서)).
"""

import hashlib
import json
import os

from . import catalog_md, risk

GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "기획서", "HAZOP기법지침.md")
EXPECTED_IDS = ["p86-d%02d" % i for i in range(1, 45)]
PINNED_SHA256 = {
    "kosha-p86-2017-deviation-chart": "9fe31d10bc1663e8deea1402452d3d02db4494e4c20550517b579481947a368b",
    "applicability-region-SNP-M-102-pzr": "d87b4cafffa843347e84165a36f2884466399b0296286e5a18ed7ab95c927cb9",
    "kosha-p86-2017-risk-example": "2ae1c539db967dc8c77ed3534aec881605940370bd523f3271488f81bc0f49aa",
}


def content_sha256(doc):
    return hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _pin(doc_id, doc, what):
    want = PINNED_SHA256.get(doc_id)
    if want is None:
        return ["%s %r: 고정 해시 없음 — 검증되지 않은 기준 데이터" % (what, doc_id)]
    if content_sha256(doc) != want:
        return ["%s %r: 내용 해시가 고정값과 다름(변조 또는 미승인 변경)" % (what, doc_id)]
    return []


def check_catalog(catalog, applicability, guide=GUIDE):
    errs = []
    ids = [i.get("item_id") for i in catalog.get("items") or []]
    if ids != EXPECTED_IDS:
        errs.append("이탈 후보 카탈로그가 p86-d01~d44 44행(순서·고유)이 아님: %d행, 고유 %d" % (len(ids), len(set(ids))))
    errs += _pin(catalog.get("catalog_id"), catalog, "이탈 후보 카탈로그")
    if applicability is not None:
        aids = [a.get("item_id") for a in applicability.get("items") or []]
        if aids != EXPECTED_IDS:
            errs.append("적용 판단 파일이 p86-d01~d44 44행이 아님: %d행" % len(aids))
        errs += _pin(applicability.get("applicability_id"), applicability, "적용 판단 파일")
    if not os.path.isfile(guide):
        errs.append("지침서 없음 — 카탈로그 대조 불가: %s" % guide)
    else:
        cat, app = catalog_md.rows_to_files(catalog_md.parse_guide_table(guide))
        if cat != catalog:
            errs.append("이탈 후보 카탈로그가 지침서 §5.3 표와 다름")
        if applicability is not None and applicability.get("applicability_id") == app["applicability_id"] \
                and app != applicability:
            errs.append("적용 판단 파일이 지침서 §5.3 판단 열과 다름")
    return errs


def check_criteria(criteria, guide=GUIDE):
    errs = _pin(criteria.get("criteria_id"), criteria, "위험도 기준표")
    try:
        matrix = {int(s): {int(f): v for f, v in row.items()} for s, row in criteria["matrix"].items()}
    except (KeyError, AttributeError, ValueError):
        matrix = None
    if matrix != risk.MATRIX_P86:
        errs.append("위험도 기준표 〈표5〉가 코드 상수(risk.MATRIX_P86)와 다름")
    if not os.path.isfile(guide):
        errs.append("지침서 없음 — 기준표 대조 불가: %s" % guide)
    else:
        t = catalog_md.parse_risk_tables(guide)
        for k in ("matrix", "severity_levels", "frequency_levels", "risk_levels"):
            if criteria.get(k) != t[k]:
                errs.append("위험도 기준표 %s가 지침서 §6 표와 다름" % k)
    return errs
