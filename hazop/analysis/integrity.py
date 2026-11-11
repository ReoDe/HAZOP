"""④ 기준 데이터 무결성 검사 (로드 시 실행, 위반이면 분석 차단).

- 이탈 후보 카탈로그·적용 판단: p86-d01~d44 44행, ID 고유, 고정 해시(PINNED_SHA256) 일치,
  지침서(specs/hazop-method-guide.md §5.3)를 다시 읽어 변환한 내용과 일치
- 위험도 기준표: 고정 해시 일치, 코드 상수(risk.MATRIX_P86)와 〈표5〉 일치, 지침서 §6 〈표5〉~〈표9〉 파싱 결과와 일치
- 패턴 라이브러리: library_id별 고정 해시(PINNED_SHA256) 일치(패키징 W5, 신뢰 경계 A안 D1)
- 지침서: 파일 해시(GUIDE_SHA256) 일치. check_catalog·check_criteria가 표를 파싱하기 전에 각각 검사한다(_guide_errs).
  없음·읽기 실패·해시 불일치·파싱 실패는 예외를 올리지 않고 blocker 사유로 돌려준다(해시가 다르면 파싱하지 않음)(패키징 W5)

주의: specs/hazop-method-guide.md는 문구 한 글자만 고쳐도 모든 분석이 차단된다. 지침서를 고치는 같은 작업 단위에서
GUIDE_SHA256을 갱신해야 한다(기획 담당이 고칠 때 개발 담당과 함께).

해시 방식(패키징 W5)
- JSON 기준 데이터(카탈로그·적용 판단·기준표·패턴): content_sha256 = 파싱한 문서를 키 정렬·공백 없는 JSON(UTF-8)으로
  직렬화한 SHA-256. 줄바꿈·들여쓰기·키 순서와 무관하고 값이 하나라도 바뀌면 달라진다.
- 지침서(Markdown): guide_sha256 = 파일 바이트에서 CRLF를 LF로 바꾼 뒤의 SHA-256(디코딩·BOM 제거 없음). Windows
  core.autocrlf 체크아웃(CRLF)과 git 저장 내용(LF)이 같은 값을 낸다. 단독 CR·BOM·그 밖의 바이트 변경은 모두 검출한다.

기준 데이터를 정당하게 바꾸는 절차
1. 지침서와 데이터 파일(데이터/이탈후보·기준표·패턴)을 함께 고치고 사람 검토를 받는다. 패턴은 library_version을 올린다.
2. 새 값을 계산한다(저장소 루트, 전용 venv):
   python -c "import json; from hazop.analysis import integrity as I; print(I.content_sha256(json.load(open('<JSON 파일>', encoding='utf-8'))))"
   python -c "from hazop.analysis import integrity as I; print(I.guide_sha256(I.GUIDE))"
3. 이 파일의 PINNED_SHA256(문서 ID 키: catalog_id·applicability_id·criteria_id·library_id) 또는 GUIDE_SHA256을 갱신한다.
4. 전체 테스트와 scripts/check_analysis.py를 돌린다. 배포본은 다시 빌드한다.
5. 실행 폴더 영향: JSON 4종이 바뀌면 예전 실행 폴더는 --resume 때 입력 사본(inputs/) 검사에서 차단된다(새로 분석해야 함).
   지침서만 바뀐 경우는 차단되지 않는다. 실행 폴더에 지침서 사본이 없고 input_files에도 기록되지 않으며, resume의
   검사는 현재 자원 루트의 지침서를 새 GUIDE_SHA256과 대조하기 때문이다.
"""

import hashlib
import json
import os

from hazop import paths

from . import catalog_md, risk

GUIDE_PARTS = paths.FILES["guide"].rel  # 자원 루트 기준
GUIDE = paths.resource_path(*GUIDE_PARTS)  # 가져올 때의 값(참고용). 검사는 호출 시점의 자원 루트를 쓴다
EXPECTED_IDS = ["p86-d%02d" % i for i in range(1, 45)]
PINNED_SHA256 = {
    "kosha-p86-2017-deviation-chart": "9fe31d10bc1663e8deea1402452d3d02db4494e4c20550517b579481947a368b",
    "applicability-region-SNP-M-102-pzr": "d87b4cafffa843347e84165a36f2884466399b0296286e5a18ed7ab95c927cb9",
    "kosha-p86-2017-risk-example": "2ae1c539db967dc8c77ed3534aec881605940370bd523f3271488f81bc0f49aa",
    "hazop-cause-consequence-patterns": "cd4a05d65162e6bb0b4fba6be2523fc9a263f7fa7d27d7b8fb0bdc7122677f31",
}
GUIDE_SHA256 = "8ea801b44800b6bc7f0b2dd8dc87df8fea87230d9bdac869171893b47757e942"
# 지침서 표 파싱(catalog_md)이 낼 수 있는 예외: 읽기 실패·UTF-8 디코딩 실패(ValueError)·표/구역 없음·형식 오류
GUIDE_PARSE_ERRORS = (OSError, ValueError, KeyError, IndexError, AttributeError, TypeError)


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


def guide_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def _guide_errs(guide, what):
    """지침서 존재·읽기·고정 해시 검사. 문제가 있으면 사유 1건(호출자는 표 파싱·대조를 하지 않음), 없으면 []."""
    if not os.path.isfile(guide):
        return ["지침서 없음 — %s 대조 불가: %s" % (what, guide)]
    try:
        got = guide_sha256(guide)
    except OSError as exc:
        return ["지침서 읽기 실패 — %s 대조 불가: %s (%s: %s)" % (what, guide, type(exc).__name__, exc)]
    if got != GUIDE_SHA256:
        return ["지침서 파일 해시가 고정값과 다름(변조 또는 미승인 변경) — %s 대조 불가: %s" % (what, guide)]
    return []


def _parse_failed(guide, section, exc):
    return "지침서 %s 파싱 실패 — 대조 불가: %s (%s: %s)" % (section, guide, type(exc).__name__, exc)


def check_patterns(patterns):
    return _pin(patterns.get("library_id"), patterns, "패턴 라이브러리")


def check_catalog(catalog, applicability, guide=None):
    guide = guide or paths.resource_file("guide")
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
    guide_errs = _guide_errs(guide, "카탈로그")
    if guide_errs:
        return errs + guide_errs
    try:
        cat, app = catalog_md.rows_to_files(catalog_md.parse_guide_table(guide))
    except GUIDE_PARSE_ERRORS as exc:
        return errs + [_parse_failed(guide, "§5.3 표", exc)]
    if cat != catalog:
        errs.append("이탈 후보 카탈로그가 지침서 §5.3 표와 다름")
    if applicability is not None and applicability.get("applicability_id") == app["applicability_id"] \
            and app != applicability:
        errs.append("적용 판단 파일이 지침서 §5.3 판단 열과 다름")
    return errs


def check_criteria(criteria, guide=None):
    guide = guide or paths.resource_file("guide")
    errs = _pin(criteria.get("criteria_id"), criteria, "위험도 기준표")
    try:
        matrix = {int(s): {int(f): v for f, v in row.items()} for s, row in criteria["matrix"].items()}
    except (KeyError, AttributeError, ValueError):
        matrix = None
    if matrix != risk.MATRIX_P86:
        errs.append("위험도 기준표 〈표5〉가 코드 상수(risk.MATRIX_P86)와 다름")
    guide_errs = _guide_errs(guide, "기준표")
    if guide_errs:
        return errs + guide_errs
    try:
        t = catalog_md.parse_risk_tables(guide)
    except GUIDE_PARSE_ERRORS as exc:
        return errs + [_parse_failed(guide, "§6 표", exc)]
    for k in ("matrix", "severity_levels", "frequency_levels", "risk_levels"):
        if criteria.get(k) != t[k]:
            errs.append("위험도 기준표 %s가 지침서 §6 표와 다름" % k)
    return errs
