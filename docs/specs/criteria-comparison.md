---
doc_id: HZ-PLN-12
rev: 0
status: review
author: unknown
reviewed: doc-status 2026-11-12
approved: —
---

# 평가 기준 비교 기획

[검토·결과 관리](review-results.md) · [HAZOP 분석 §품질 평가](hazop-analysis.md#품질-평가) · [MVP와 후속 범위](overview.md#mvp) · [공통 원칙](overview.md#principles)

## 1. 목적과 범위

MVP의 성공 여부는 ④·⑤ 결과를 사용자의 평가 기준(정답 HAZOP 항목)과 비교해 판단합니다([MVP](overview.md#mvp)). 사용자는 아직 기준을 주지 않았습니다. 이 문서는 기준을 받기 전에도 비교 기능을 구현·검증할 수 있도록 **권고 기준 형식, 대응 규칙, 지표, 출력**을 정합니다.

이 문서의 결정은 모두 **총괄 결정(권고안, 사용자 위임 2026-11-06)**입니다. 사용자가 다른 형식으로 기준을 주면 §6의 변환 어댑터를 추가하며, 비교 규칙(§3)과 지표(§4)는 그대로 씁니다.

| 범위 | 내용 |
| --- | --- |
| 포함 | 기준 파일 형식(JSON 정본, Excel 한 장 입력), 결정적 대응 규칙, 지표, 비교 보고 JSON·Excel, 독립 검증 |
| 제외 | AI 판정(의미 유사도 판단 포함), 기준 자체의 공학적 타당성 판단, 기준 편집 화면 |

비교는 결정적(deterministic)이어야 합니다. 같은 기준·같은 분석 실행·같은 검토 기록·같은 옵션이면 비교 시각(`compared_at`)을 뺀 보고 JSON이 바이트 단위로 같아야 합니다.

## 2. 평가 기준 파일 형식

### 2.1 정본: JSON

정본은 UTF-8 JSON 한 파일입니다. 한 파일은 검토 구간 1개·운전모드 1개의 기준을 담습니다. 행 단위는 "편차 1개 아래 원인 1개" 입니다. 한 원인 행에는 결과 여러 개, 보호수단 여러 개, 권고 여러 개를 둘 수 있습니다. 이는 KOSHA P-86-2017 〈별표7〉 워크시트의 행 구조(이탈–원인–결과–현재안전조치–개선권고사항)와 맞춘 것입니다([HAZOP 기법 지침](hazop-method-guide.md)).

```json
{
  "format": "hazop-criteria",
  "format_version": "0.1",
  "criteria_id": "criteria-SNP-M-102-pzr-sample",
  "criteria_version": 1,
  "region_id": "region-SNP-M-102-pzr",
  "operating_mode": "normal",
  "provenance": {"kind": "synthetic", "author": "hazop-planner", "created_at": "2026-11-06T00:00:00Z",
                 "note": "[추론]·가상 샘플. 정답이 아님"},
  "tag_aliases": {"PZR": "RC-PZ01"},
  "deviations": [
    {
      "deviation_ref": {"item_id": "p86-d09", "parameter": "압력", "guide_word": "증가"},
      "label": "압력 증가",
      "rows": [
        {
          "row_id": "R01",
          "required": true,
          "cause": {"text": "써지 배관을 통한 인서지로 증기 공간 압축", "equipment": ["PZR"],
                    "keywords": [["인서지", "유입"]]},
          "consequences": [
            {"text": "가압기 압력 상승", "equipment": ["RC-PZ01"], "keywords": [["압력"], ["상승", "증가"]]}
          ],
          "safeguards": [{"tag": "RC-PSV101"}, {"tag": "RC-PSV102"}],
          "recommendations": []
        }
      ]
    }
  ]
}
```

#### 최상위 필드

| 필드 | 필수 | 형식 | 의미·검사 |
| --- | --- | --- | --- |
| `format`, `format_version` | 필수 | 문자열 `"hazop-criteria"`, `"0.1"` | 다른 값이면 차단(blocked) |
| `criteria_id`, `criteria_version` | 필수 | 문자열, 정수 ≥ 1 | 기준의 ID·버전 쌍. 기준을 고치면 버전을 올림 |
| `region_id` | 필수 | 문자열 | 분석 실행의 `region_ref.region_id`와 다르면 차단 |
| `operating_mode` | 필수 | 문자열 | 분석 실행의 `operating_mode`와 다르면 차단 |
| `provenance.kind` | 필수 | `user`, `synthetic` | 사용자 제공 기준인지 가상 기준인지. `synthetic`이면 보고서 맨 앞에 "가상 기준 — MVP 성공 판단에 쓰지 않음"을 표시 |
| `provenance.author`, `created_at`, `note` | 선택 | 문자열 | 작성 정보 |
| `tag_aliases` | 선택 | `{별칭: 도면 태그}` | 기준 작성자가 다른 이름을 쓸 때. 별칭을 태그로 바꾼 뒤 비교. 별칭의 대상이 다시 별칭이면 차단(연쇄 금지) |
| `deviations` | 필수 | 배열, 1개 이상 | 기준 편차 목록 |

#### 편차 필드 (`deviations[]`)

| 필드 | 필수 | 형식 | 의미·검사 |
| --- | --- | --- | --- |
| `deviation_ref.parameter` | 필수 | 문자열 | 파라미터(KOSHA 표기, 예: 압력) |
| `deviation_ref.guide_word` | 필수 | 문자열 | 가이드워드. KOSHA 표기가 표준이며 영문 표기(More, No 등)도 받음. 비교 방법은 §3.1. 정규화 후 빈 문자열이면 차단 |
| `deviation_ref.item_id` | 선택 | 문자열 | 이탈 후보 카탈로그 항목 ID(예: `p86-d09`). 있으면 우선 사용 |
| `label` | 선택 | 문자열 | 표시용 편차 이름 |
| `expected` | 선택 | `scenarios`(기본), `no_scenario` | `no_scenario`: 이 편차는 검토하되 신빙성 있는 시나리오가 없다는 기준. 이때 `rows`는 빈 배열 |
| `rows` | 필수 | 배열 | `expected`가 `scenarios`면 1개 이상 |

같은 편차(§3.1 키 기준)가 두 번 나오면 차단합니다. 서로 다른 기준 편차 둘이 같은 후보에 대응해도 차단합니다. 필드 자료형이 틀리면 예외 없이 형식 오류로 차단합니다.

#### 원인 행 필드 (`rows[]`)

| 필드 | 필수 | 형식 | 의미·검사 |
| --- | --- | --- | --- |
| `row_id` | 필수 | 문자열 | 파일 안에서 유일. 중복이면 차단 |
| `required` | 선택 | 불리언(기본 `true`) | `false`면 지표 분모에서 빼고 "선택 항목 일치"로만 따로 집계 |
| `cause.text` | 필수 | 문자열 | 원인 문장(표시용, 비교에 직접 쓰지 않음) |
| `cause.equipment` | 조건부 | 태그 배열 | 원인 설비 태그. `keywords`와 둘 다 비면 차단 |
| `cause.keywords` | 조건부 | 키워드 그룹 배열 | 아래 "키워드 그룹" 참조 |
| `consequences[]` | 필수 | 배열, 1개 이상 | 각 항목: `text`(필수), `equipment`(선택), `keywords`(필수, 1그룹 이상) |
| `safeguards` | 선택 | 배열 또는 `null`(기본 `null`) | `null`: 보호수단은 평가하지 않음. `[]`: 보호수단이 없어야 한다는 기준(출력에 있으면 초과로 기록). 각 항목은 `tag` 또는 `keywords` 중 하나 이상, `text`는 선택 |
| `recommendations` | 선택 | 배열(기본 `[]`) | 각 항목: `text`(필수), `keywords`(필수). 검토 반영 기준(§3.5)에서만 평가 |
| `note` | 선택 | 문자열 | 메모 |

키워드 그룹은 `[["압력"], ["상승", "증가"]]`처럼 배열의 배열입니다. **그룹 사이는 모두 만족(AND), 그룹 안은 하나 이상 만족(OR)**입니다. 빈 그룹이나 빈 문자열 키워드는 차단합니다.

### 2.2 입력: Excel 한 장

사용자가 Excel로 기준을 쓰는 경우를 위한 권고 양식입니다. 변환 어댑터(`xlsx_sheet`, §6)가 이 양식을 §2.1 JSON으로 바꾼 뒤 같은 검사를 거칩니다. 시트 이름은 `평가기준`입니다.

| 행 | 내용 |
| --- | --- |
| 1–9행 | A열 항목명, B열 값: `기준 ID`, `기준 버전`, `구간 ID`, `운전모드`, `출처 구분`(user/synthetic), `작성자`, `작성 시각`, `메모`, `태그 별칭`(`PZR=RC-PZ01; ...`). `작성자`·`작성 시각`·`메모`는 빈칸 허용 |
| 11행 | 머리글(아래 열 순서 고정) |
| 12행부터 | 원인 행 1개 = Excel 1행. 시나리오가 없어야 하는 편차는 A–D열, Q열(선택), R열(`시나리오 없음`)만 쓴 행 1개로 표시. 이 행의 A열 행 ID는 중복 검사에만 쓰고 정본에는 남지 않음 |

| 열 | 머리글 | JSON 필드 | 여러 값 구분 |
| --- | --- | --- | --- |
| A | 행 ID | `row_id` | — |
| B | 항목 ID | `deviation_ref.item_id` | — |
| C | 파라미터 | `deviation_ref.parameter` | — |
| D | 가이드워드 | `deviation_ref.guide_word` | — |
| E | 원인 | `cause.text` | — |
| F | 원인 설비 | `cause.equipment` | `;` |
| G | 원인 키워드 | `cause.keywords` | 그룹은 `;`, 그룹 안 동의어는 `\|` |
| H | 결과 | `consequences[].text` | 줄바꿈(결과 1개 = 1줄) |
| I | 결과 설비 | `consequences[].equipment` | 줄은 H열과 1:1, 줄 안은 `;` |
| J | 결과 키워드 | `consequences[].keywords` | 줄은 H열과 1:1, 줄 안은 G열 규칙 |
| K | 보호수단 태그 | `safeguards[].tag` | `;`. K·L 규칙은 아래 표 |
| L | 보호수단 키워드 | 태그 없는 `safeguards[].keywords` | 보호수단 1개 = 1줄, 줄 안은 G열 규칙 |
| M | 권고 | `recommendations[].text` | 줄바꿈 |
| N | 권고 키워드 | `recommendations[].keywords` | 줄은 M열과 1:1 |
| O | 필수 | `required` | `Y`/`N`(빈칸은 Y) |
| P | 비고 | `note` | — |
| Q | 편차 이름 | `label` | 같은 편차의 행끼리 다르면 차단 |
| R | 편차 기대 | `expected` | 빈칸 = `scenarios`, `시나리오 없음` = `no_scenario`(이때 E–P열은 비어야 함) |

K·L열 조합 규칙:

| K열 | L열 | `safeguards` |
| --- | --- | --- |
| 빈칸 | 빈칸 | `null`(평가 안 함) |
| `없음` | 빈칸 | `[]` |
| `없음` | 값 있음 | 차단(서로 모순) |
| 빈칸 | 값 있음 | 키워드 항목만의 목록 |
| 태그 있음 | 빈칸 또는 값 있음 | 태그 항목(K열 순서) 뒤에 키워드 항목(L열 줄 순서)을 이은 목록 |

정본 필드 중 Excel로 그대로 받지 않는 것은 아래 셋입니다. 나머지 정본 필드는 위 1–9행과 A–R열로 모두 받습니다.

| 정본 필드 | Excel 처리 |
| --- | --- |
| `safeguards[].text` | 받지 않음. 변환 결과에서 생략. 비교에 쓰지 않는 표시용 필드라 지표 영향 없음 |
| `tag`와 `keywords`를 함께 가진 보호수단 항목 | 표현 불가. K·L 규칙상 태그 항목과 키워드 항목으로 나뉘어 들어옴. 정본 JSON으로 직접 써야 함 |
| `format`, `format_version` | 시트에 없음. 어댑터가 상수 `"hazop-criteria"`, `"0.1"`로 채움 |

같은 (항목 ID 또는 파라미터·가이드워드) 행은 한 편차로 묶습니다. 같은 편차로 묶인 행끼리 B–D열 값이 다르면 차단합니다. H·I·J열(또는 M·N열)의 줄 수가 다르면 차단합니다. H·I·J·L·M·N열은 줄바꿈을 보존하고 앞뒤 공백·탭만 다듬습니다. 셀 값이 수식이면 계산값이 아니라 차단으로 처리합니다(수식 결과를 기준으로 쓰지 않음). `기준 버전` 셀이 날짜·시간형이면 문자열로 바꿔 형식 오류로 차단합니다.

## 3. 대응 규칙 (결정적, AI 미사용)

### 3.1 정규화

| 대상 | 규칙 |
| --- | --- |
| 자유 문장·키워드 | `hazop.extract.adapters.evaluation.normalize_text`와 같은 규칙: 유니코드 NFKC → 모든 공백·줄바꿈 제거 → 대문자. 키워드도 같은 규칙으로 정규화 |
| 태그 | 위 정규화 후 `tag_aliases` 적용 |
| 문장 안의 태그 등장 | 정규화한 문장에서 태그 앞 글자가 `[A-Z0-9-]`가 아니고 뒤 글자가 `[A-Z0-9-]`가 아닐 때만 등장으로 인정. 예: `RC-L010`은 `RC-L010-T3` 안에서 등장으로 보지 않음. 한글 조사(예: `RC-PV101를`)는 경계로 인정 |
| 가이드워드 | 기준 값을 위 문장 규칙으로 정규화한 뒤, 후보의 `guide_word_ko`, 또는 `guide_word_en`(같은 정규화, 대문자라 대소문자 무시)과 비교. `guide_word_en` 전체, 그리고 정규화 전 원문을 `,`와 공백으로 둘러싸인 단어 `or`로 나눈 각 부분(빈 부분은 버림)을 각각 정규화해 비교(정규화 후에는 공백이 없어져 나눌 수 없으므로). 예: 후보 영문 `No, Not, or None`([대응표](hazop-method-guide.md#guide-words) 원문 표기)은 기준 `No`·`not`·`None`·`No, Not, or None`과 모두 일치. 후보 영문이 `null`이면 한국어로만 비교 |

키워드 일치는 "정규화한 출력 문장이 정규화한 키워드를 부분 문자열로 포함"으로 판정합니다. 형태소 분석·유사도 점수는 쓰지 않습니다.

### 3.2 편차 대응

1. 기준 편차에 `item_id`가 있으면 분석 실행의 후보 중 `item_id`가 같은 후보와 대응합니다. 그 후보가 없으면 2번으로 대신 대응하지 않고 `not_in_catalog`로 기록합니다.
2. 없으면 `parameter_ko`가 정규화 후 같고 가이드워드가 §3.1 규칙으로 일치하는 후보와 대응합니다. 같은 키의 후보가 2개 이상이면 그 편차를 `ambiguous_deviation`으로 기록하고 대응하지 않습니다(누락으로 셈).
3. 대응 후보가 없으면 "카탈로그에 없는 편차"로 기록하고 누락으로 셉니다. 차단하지 않습니다(도구가 다루지 못한 편차 종류를 드러내는 것이 목적).

**재현된 편차**는 대응 후보가 `selection_status: selected`이고 비교 대상 시나리오(§3.5)가 1개 이상인 편차입니다. `expected: no_scenario`인 기준 편차는 대응 후보가 `selected`이고 비교 대상 시나리오가 0개일 때 재현으로 봅니다.

### 3.3 원인 행 ↔ 출력 시나리오 대응

재현된 편차 안에서만 대응합니다.

1. **설비 조건**: 기준 `cause.equipment`가 있으면 출력 시나리오의 원인 설비 태그 집합(`cause_equipment`의 entity_id를 실행 사본 `inputs/graph.json`의 `tag`로 바꾼 것)과 교집합이 1개 이상이어야 합니다. 기준 설비가 없으면 이 조건은 건너뜁니다.
2. **키워드 조건**: 기준 `cause.keywords`가 있으면 출력 원인 문장(§3.5)이 모든 그룹을 만족해야 합니다. 없으면 건너뜁니다.
3. 두 조건을 모두 통과한 (기준 행, 출력 시나리오) 쌍이 대응 후보입니다.
4. 1:1 할당: 점수 = `10 × 설비 교집합 수 + 만족한 키워드 그룹 수`. 기준 행을 `row_id` 순, 출력 시나리오를 `scenario_id` 순으로 정렬해 고정한 뒤, 비용 = `−점수`(대응 불가 쌍은 금지 비용)로 `hazop.extract.adapters.evaluation.hungarian`을 써서 최소 비용 할당을 구합니다. 금지 비용 쌍은 할당 결과에서 버립니다.

출력 원인 문장은 설비 조건을 보지 않습니다. 설비 정보는 구조화된 `cause_equipment`만 씁니다(문장에 태그가 나와도 원인 설비로 보지 않음).

### 3.4 대응 쌍의 필드 비교

| 필드 | 일치 판정 |
| --- | --- |
| 결과 항목 | 출력 결과 문장이 그 항목의 모든 키워드 그룹을 만족하고, 항목의 `equipment` 태그가 모두 출력 결과 문장에 등장(§3.1)하면 일치 |
| 보호수단 항목 | 아래 "보호수단 배정 순서"로 출력 보호수단 1개를 배정받으면 일치 |
| 초과 보호수단 | 기준 `safeguards`가 `null`이 아닐 때, 어떤 기준 항목에도 배정되지 않은 출력 보호수단 |
| 권고 항목 | 출력 권고 문장 중 하나가 모든 키워드 그룹을 만족하면 일치 |

보호수단 배정 순서(한 출력 보호수단은 기준 항목 1개에만 배정):

1. 출력 보호수단을 안정 정렬 키 `(정규화 태그, 없으면 빈 문자열; 정규화 설명 문장; 뷰 안 원래 순번)`으로 정렬합니다.
2. **태그 항목 먼저**: 기준의 `tag` 항목을 기준 순서대로 보며, 정렬 순서상 태그가 같은 첫 번째 미배정 출력에 배정합니다. `tag`와 `keywords`를 둘 다 가진 항목은 태그가 같고 설명 문장이 키워드를 만족해야 배정합니다.
3. **키워드 항목 다음**: `keywords`만 가진 항목을 기준 순서대로 보며, 정렬 순서상 설명 문장(`description`)이 모든 그룹을 만족하는 첫 번째 미배정 출력에 배정합니다.

태그 항목이 키워드 항목보다 먼저 출력을 선점합니다. 그래서 같은 출력 보호수단이 태그 항목과 키워드 항목 모두에 맞으면 태그 항목에 배정됩니다.

### 3.5 비교 대상 값 (`basis`)

비교는 Excel을 다시 읽지 않고, Excel 2–4열과 같은 병합 함수(`hazop.review.merge_display`)로 만든 구조화 값을 씁니다. Excel 문자열은 보조 표기가 섞여 있어 다시 파싱하면 결정성이 떨어지기 때문입니다. 비교 보고에는 같은 실행의 출력 기록(`exports/<시각>.json`)이 있으면 그 ID와 워크시트 행 번호를 함께 남겨 Excel 행으로 찾아갈 수 있게 합니다.

| `basis` | 비교 대상 시나리오 | 원인·결과 | 보호수단 | 권고 |
| --- | --- | --- | --- | --- |
| `draft`(기본) | 선택 편차의 모든 시나리오 | `merge_display(s, None)`의 `cause`·`consequence` 값 | `merge_display(s, None)`의 `safeguards` 값 | 평가 안 함(`not_evaluated`) |
| `reviewed` | 선택 편차의 시나리오 중 최신 검토본 결정이 `reject`가 아닌 것 | `merge_display(s, 최신 결정)` | 같은 함수의 `safeguards`. 항목 태그는 `tag`, 없으면 `node_id`의 그래프 태그 | 해당 시나리오에 연결된 설계보완 후보 중 결정이 `accept`·`modify`인 것의 `recommendation` |

`draft`는 도구가 만든 초안의 품질을, `reviewed`는 사람이 검토한 뒤 Excel에 나가는 결과의 품질을 봅니다. MVP 성공 판단의 주 지표는 `draft`입니다. 검토 기록이 없는 시나리오는 `reviewed`에서도 원안 값이 쓰이며, 보고서에 검토 기록이 있는 시나리오 수를 함께 표시합니다.

### 3.6 비교 입력 뷰

분석 실행 폴더와 검토 저장소를 직접 읽는 부분과 비교 핵심을 분리합니다. 비교 핵심 함수는 아래 **비교 입력 뷰**만 받습니다. 이렇게 하면 §7의 독립 검증을 분석 실행 없이 할 수 있습니다.

```json
{
  "analysis_run_id": "analysis-...",
  "analysis_sha256": "...",
  "region_ref": {"region_id": "region-SNP-M-102-pzr", "region_version": 1},
  "graph_ref": {"graph_id": "graph-SNP-M-102", "graph_version": "v-f65e4ec1135d"},
  "operating_mode": "normal",
  "basis": "draft",
  "export_id": null,
  "reviews": [{"candidate_id": "deviation-p86-d09", "review_version": 1}],
  "excluded_by_review": 0,
  "graph_tags": ["RC-L010", "RC-L011", "RC-L031", "RC-PIC110", "RC-PSV101", "RC-PSV102", "RC-PT110", "RC-PV101",
                 "RC-PZ01"],
  "deviations": [
    {"candidate_id": "deviation-p86-d09", "item_id": "p86-d09", "parameter_ko": "압력", "guide_word_ko": "증가",
     "guide_word_en": "More", "selection_status": "selected"}
  ],
  "scenarios": [
    {"scenario_id": "scenario-p86-d09-01", "candidate_id": "deviation-p86-d09", "worksheet_row": null,
     "cause": "...", "consequence": "...", "cause_equipment_tags": ["RC-PZ01"],
     "safeguards": [{"tag": "RC-PSV101", "description": "..."}], "recommendations": [],
     "decision": null}
  ]
}
```

뷰 생성기는 `basis` 규칙(§3.5)을 적용한 결과만 `scenarios`에 넣습니다. `reviews`는 `comparison_id` 계산에 쓰는 검토본 `(candidate_id, review_version)` 목록입니다(`candidate_id`·`review_version` 오름차순, 검토본이 없으면 빈 목록). `excluded_by_review`는 `reviewed`에서 `reject`로 빠진 시나리오 수입니다(`draft`는 항상 0). `graph_tags`는 실행 사본 `inputs/graph.json`의 모든 노드 `tag`(값이 있는 것)를 정규화해 중복 없이 정렬한 목록입니다. 위 예시의 `graph_tags`는 줄여 적은 것입니다.

기준 태그 경고는 두 종류로 나눕니다.

| 종류 | 조건 | 처리 |
| --- | --- | --- |
| `tag_not_in_graph` | 별칭 적용 후 기준 태그(원인 설비·결과 설비·보호수단 태그)가 `graph_tags`에 없음 | `criteria_warnings`. 그 태그로는 대응이 생기지 않으므로 해당 행·항목은 누락으로 셈 |
| `alias_unused` | `tag_aliases`의 별칭이 기준 어디에도 쓰이지 않음 | `criteria_warnings` |

기준 태그가 그래프에는 있지만 출력 시나리오에 나오지 않는 경우는 경고가 아닙니다. 이 경우는 누락 목록(`missing.rows`·`missing.safeguards`)으로만 드러납니다.

## 4. 지표

기호는 다음과 같습니다.

- `Dc`: 기준 필수 편차 집합. 편차의 필수 행이 1개 이상이거나 `expected: no_scenario`이면 필수 편차입니다.
- `Dr ⊆ Dc`: 재현된 필수 편차 집합.
- `Do`: 출력의 선택 편차 중 비교 대상 시나리오가 있는 편차의 집합.
- `So`: `Dc ∩ Do`에 속한 출력 시나리오 집합.
- `Rc`: 기준 필수 행 집합. 재현 여부와 무관하게 모든 필수 행을 넣습니다.
- `M`: §3.3에서 할당된 모든 대응 쌍.
- `Mc ⊆ M`: 그중 편차가 `Dc`에 속한 쌍. 필수 행 쌍과, 필수 편차 안의 선택 행(`required: false`) 쌍을 포함합니다.

| 지표 | 정의식 | 분모 0일 때 |
| --- | --- | --- |
| 편차 재현율 | `|Dr| / |Dc|` | `null` |
| 원인 재현율 | `|{m ∈ M : m의 행 ∈ Rc}| / |Rc|` | `null` |
| 원인 정밀도 | `|Mc| / |So|`. 1:1 할당이라 `Mc`의 시나리오는 서로 다르고 모두 `So`에 속하므로 항상 1 이하 | `null` |
| 결과 일치율 | 대응 쌍(필수 행)의 일치 결과 항목 수 합 / 대응 쌍(필수 행)의 기준 결과 항목 수 합 | `null` |
| 보호수단 일치율 | 대응 쌍(필수 행, `safeguards`가 `null` 아님)의 일치 항목 수 합 / 같은 쌍의 기준 보호수단 항목 수 합 | `null` |
| 권고 일치율 | `reviewed`에서만. 대응 쌍(필수 행)의 일치 권고 항목 수 합 / 같은 쌍의 기준 권고 항목 수 합. `draft`는 `not_evaluated` | `null` |

- 결과·보호수단·권고 일치율은 **대응된 행 안에서의 조건부 비율**입니다. 원인 자체를 놓친 행의 결과는 원인 재현율에 이미 반영되므로 다시 세지 않습니다.
- 비율은 소수점 6자리로 반올림합니다(`evaluation._r`와 같은 방식). 분모가 0이면 0이 아니라 `null`입니다.
- `required: false` 행이 대응되면 `optional_matched`로 셉니다. 그 행이 필수 편차(`Dc`)에 속하면 대응 시나리오를 `Mc`에 넣어 초과로 세지 않습니다. 필수 행이 없는 편차(선택 행만 있는 편차)의 쌍은 `Mc`에도 `So`에도 들어가지 않으므로 정밀도에 영향이 없습니다.

### 누락·초과 목록

| 목록 | 내용 |
| --- | --- |
| `missing.deviations` | `Dc − Dr`. 사유: `not_in_catalog`, `ambiguous_deviation`, `not_selected`(제외·보류, `selection_status` 함께), `no_scenario`(선택됐으나 시나리오 0), `unexpected_scenarios`(`expected: no_scenario`인데 시나리오 있음) |
| `missing.rows` | 대응되지 않은 필수 행. 사유: `deviation_not_reproduced`, `no_equipment_match`, `no_keyword_match`(설비 조건을 통과했거나 설비 조건이 없는데, 키워드 조건을 만족하는 시나리오가 없음), `assigned_elsewhere`(대응 후보는 있었으나 1:1 할당에서 밀림) |
| `missing.consequences`, `missing.safeguards`, `missing.recommendations` | 대응 쌍에서 일치하지 않은 기준 항목(행 ID·항목 번호·기준 문장) |
| `extra.deviations` | `Do − Dc`(기준에 없는 편차의 출력 시나리오. 정밀도 분모에 넣지 않고 목록만) |
| `extra.scenarios` | `So` 중 대응되지 않은 시나리오 |
| `extra.safeguards` | §3.4 초과 보호수단 |
| `criteria_warnings` | `tag_not_in_graph`, `alias_unused`(§3.6) |

## 5. 출력

### 5.1 비교 보고 JSON

위치: `<작업 루트>/output/evaluation-compare/<region_id>/<analysis_run_id>/compare-<criteria_id>-v<criteria_version>-<basis>-<YYYYMMDDTHHMMSSZ>.json`. 같은 이름이 있으면 덮어쓰지 않고 실패합니다. 아래는 필드 형태 예시이며 지표 값은 §7.3 E1, 목록은 줄여 적었습니다.

```json
{
  "schema_version": "0.1",
  "comparison_id": "compare-3f2a9c0d1e4b",
  "compare_version": "0.1.0",
  "compared_at": "2026-11-06T00:00:00Z",
  "status": "ok",
  "reasons": [],
  "criteria": {"criteria_id": "...", "criteria_version": 1, "sha256": "...", "provenance_kind": "synthetic",
               "source_format": "json", "adapter": null},
  "target": {"analysis_run_id": "...", "analysis_sha256": "...", "region_ref": {}, "graph_ref": {},
             "basis": "draft", "export_id": null, "reviewed_scenarios": 0, "excluded_by_review": 0},
  "metrics": {"deviation_recall": 0.666667, "cause_recall": 0.666667, "cause_precision": 0.8,
              "consequence_match": 0.6, "safeguard_match": 0.6, "recommendation_match": "not_evaluated",
              "counts": {"Dc": 3, "Dr": 2, "Do": 3, "Rc": 6, "M": 4, "Mc": 4, "So": 5, "optional_matched": 0}},
  "pairs": [{"row_id": "R01", "scenario_id": "scenario-p86-d09-01", "worksheet_row": null, "score": 11,
             "consequences": [true], "safeguards": [true, true], "recommendations": []}],
  "missing": {"deviations": [], "rows": [], "consequences": [], "safeguards": [], "recommendations": []},
  "extra": {"deviations": [], "scenarios": [], "safeguards": []},
  "criteria_warnings": []
}
```

`status`는 `ok` 또는 `blocked`입니다. `blocked`이면 `reasons`에 사유를 쓰고 지표를 만들지 않습니다. JSON은 키 정렬·들여쓰기 2칸·끝 줄바꿈으로 씁니다(`evaluation.dumps`와 같은 방식).

결정성 규칙은 다음과 같습니다.

- `comparison_id`는 시각이 아니라 입력에서 만듭니다. `"compare-" + SHA-256(criteria.sha256 | analysis_sha256 | basis | 검토본 (candidate_id, review_version) 정렬 목록 | export_id | compare_version)`의 앞 12자리입니다. 입력은 `|`로 잇고, 검토본 목록은 `cid:ver`를 쉼표로 이으며, `export_id`가 없으면 빈 문자열입니다. `draft`도 검토본 목록을 해시에 넣습니다. 예시 값은 형태만 보인 것입니다.
- 시각에 따라 달라지는 값은 `compared_at` 필드와 파일 이름의 시각 부분뿐입니다. 결정성 비교(§7.3 E3)는 `compared_at`을 뺀 내용으로 합니다.
- 파일은 덮어쓰지 않습니다. 같은 입력으로 다시 비교하면 `comparison_id`는 같고, 파일 이름은 시각이 달라 새 파일이 됩니다. 같은 시각(`--now`)으로 다시 쓰려 하면 실패합니다.

차단 조건: 기준 형식 오류(§2의 필수·형식·중복 검사), `region_id`·`operating_mode` 불일치, 분석 결과 `validation.status`가 `passed`가 아님, `analysis.json` 해시가 지정한 출력 기록의 `target.analysis_sha256`과 다름, `basis: reviewed`에서 검토 기록의 `analysis_ref.analysis_sha256`이 현재 `analysis.json` 해시와 다름, 실행 사본 `inputs/graph.json` 없음, 지정한 출력 기록을 읽을 수 없음.

차단 보고는 `metrics`·`pairs`·`missing`·`extra`·`criteria_warnings`를 `null`로 둡니다. 기준 ID가 유효하면 차단 보고도 파일로 씁니다.

파일 이름: 기준 버전이 1 이상의 정수가 아니면 버전 부분을 `vX`로 씁니다. 이름 전체가 경로 한 단계 규칙(경로 구분자 등 금지)을 어기면 파일을 쓰지 않습니다.

예시에 없는 필드: `notice`(가상 기준이면 "가상 기준 — MVP 성공 판단에 쓰지 않음" 문구, 아니면 `null`), `criteria.notes`(변환 메모 목록), 누락 항목의 `scenario_id`·`required`, 경고(`criteria_warnings`)의 `row_ids`. `basis: draft`에서는 `pairs[].recommendations`가 항목마다 `null`입니다.

### 5.2 Excel 보고

같은 폴더에 같은 이름의 `.xlsx`를 만듭니다. 시트는 `요약`(기준·대상·지표·가상 기준 표시), `행별 대응`(기준 행마다 대응 시나리오·워크시트 행·필드별 일치), `누락`, `초과` 4장입니다. 셀 쓰기는 워크시트 출력과 같은 규칙(`None`은 `미확인`이 아니라 `없음`·`평가 안 함` 등 의미를 쓴 문자열, 수식처럼 시작하는 문자열은 문자열 셀)으로 합니다. HTML 보고는 만들지 않습니다(Excel과 JSON으로 충분하고 기존 출력 방식과 같음).

### 5.3 실행 형태 (구현 권고)

| 항목 | 권고 |
| --- | --- |
| 모듈 | `hazop/evaluate/criteria.py`(읽기·검사·정규화), `hazop/evaluate/view.py`(비교 입력 뷰 생성), `hazop/evaluate/match.py`(대응·지표), `hazop/evaluate/report.py`(JSON·Excel), `hazop/evaluate/adapters/`(§6) |
| 명령 | `python scripts/compare_criteria.py --criteria <파일> --run <분석 실행 폴더> [--store-root] [--basis draft\|reviewed] [--export <출력 기록 JSON>] [--format json\|xlsx_sheet] [--now]`. 출력 루트를 바꾸는 옵션(`--out-root`)은 없고, 작업 루트(`HAZOP_WORK_ROOT`)를 바꿔 정함 |
| 검사 스크립트 | `scripts/check_compare.py`·`tests/test_evaluate.py`: §7 사례 전체, 종료 코드 0 = 통과. 네트워크·AI 호출 없음 |
| 샘플 기준 파일 | §7.1의 JSON을 `data/evaluation-criteria/criteria-SNP-M-102-pzr-sample.json`으로 저장(구현 담당) |

## 6. 변환 어댑터 자리

사용자 기준이 §2와 다른 형식(예: 기존 HAZOP 워크시트 Excel, 다른 열 순서, PDF 표)으로 오면 **어댑터가 정본 JSON(§2.1)으로 바꾸고, 그 뒤는 같은 경로**를 탑니다. 이는 추출 단계의 "형식별 어댑터 + 같은 계약" 구조([MVP](overview.md#mvp) 사용자 결정)와 같은 방식입니다.

| 항목 | 규칙 |
| --- | --- |
| 인터페이스 | `load(path) -> (criteria_dict, notes)`. `notes`는 변환 중 해석한 내용(열 대응, 건너뛴 행)의 목록 |
| 등록 | `hazop/evaluate/adapters/__init__.py`의 `ADAPTERS = {"json": ..., "xlsx_sheet": ...}`. 새 형식은 키 하나 추가 |
| 검사 | 어댑터 출력은 §2 검사를 그대로 거침. 어댑터가 형식 검사를 대신하지 않음 |
| 기록 | 보고 JSON `criteria.source_format`·`adapter`(이름·버전)·`sha256`(원본 파일 바이트 해시)과 `notes` |
| 금지 | 어댑터가 없는 값을 만들지 않음. 원본에 원인 설비나 키워드가 없으면 빈 값으로 두어 §2 검사에서 차단되게 함. 자유 문장에서 키워드를 자동 추출하지 않음(사람이 키워드를 채움) |

사용자 기준이 원인 설비·키워드 없이 자유 문장만 담고 있으면, 사람이 기준 Excel(§2.2)에 키워드를 채우는 작업이 필요합니다. 이 작업을 AI로 대신하지 않습니다.

## 7. 독립 검증

분석 실행·검토 저장소 없이 **비교 입력 뷰(§3.6) 고정 사례 + 가상 기준 파일**만으로 검증합니다. 뷰 생성기(§3.6)는 별도 사례로 실제 실행 폴더에서 검증합니다.

### 7.1 가상 기준 파일 (`criteria-SNP-M-102-pzr-sample`)

아래 내용은 모두 **[추론]·가상**입니다. 태그는 샘플 도면 SNP-M-102의 실제 태그를 쓰지만, 원인·결과·보호수단의 공학적 타당성은 검증하지 않았으며 정답이 아닙니다. 용어 출처는 다음과 같습니다.

- 가압기(pressurizer): [일반지식] (U.S. NRC Glossary "Pressurizer", 원문 미확인)
- 인서지·살수(insurge·spray): [일반지식] 수준의 가압경수로 운전 용어이며 원문 출처는 미확인입니다.
- POSRV(Pilot-Operated Safety Relief Valve, 파일럿 구동 안전방출밸브): [일반지식] (APR1400 설계 문서의 용어로 알려져 있음, 원문 미확인). 샘플 구간 설계 의도 문장에 이 용어가 나옵니다.

```json
{
  "format": "hazop-criteria", "format_version": "0.1",
  "criteria_id": "criteria-SNP-M-102-pzr-sample", "criteria_version": 1,
  "region_id": "region-SNP-M-102-pzr", "operating_mode": "normal",
  "provenance": {"kind": "synthetic", "author": "hazop-planner", "created_at": "2026-11-06T00:00:00Z",
                 "note": "[추론]·가상 샘플. 비교 기능 검증용이며 정답이 아님"},
  "tag_aliases": {"PZR": "RC-PZ01"},
  "deviations": [
    {"deviation_ref": {"item_id": "p86-d03", "parameter": "유량", "guide_word": "없음"}, "label": "유량 없음",
     "rows": [
       {"row_id": "R06", "cause": {"text": "써지 배관 막힘", "equipment": ["RC-L010"], "keywords": [["막힘", "폐색"]]},
        "consequences": [{"text": "가압기 압력 제어 곤란", "keywords": [["압력"]]}], "safeguards": null}
     ]},
    {"deviation_ref": {"item_id": "p86-d09", "parameter": "압력", "guide_word": "증가"}, "label": "압력 증가",
     "rows": [
       {"row_id": "R01", "cause": {"text": "인서지로 증기 공간 압축", "equipment": ["PZR"], "keywords": [["인서지", "유입"]]},
        "consequences": [{"text": "가압기 압력 상승", "equipment": ["RC-PZ01"], "keywords": [["압력"], ["상승", "증가"]]}],
        "safeguards": [{"tag": "RC-PSV101"}, {"tag": "RC-PSV102"}]},
       {"row_id": "R02", "cause": {"text": "살수 밸브 개방 실패", "equipment": ["RC-PV101"], "keywords": [["개방실패", "열림실패"]]},
        "consequences": [{"text": "압력 상승 억제 실패", "keywords": [["압력"], ["상승"]]},
                         {"text": "과압으로 POSRV 개방 요구", "keywords": [["과압"]]}],
        "safeguards": [{"tag": "RC-PSV101"}, {"tag": "RC-PSV102"}],
        "recommendations": [{"text": "살수 개방 실패 경보 검토", "keywords": [["살수"], ["경보"]]}]},
       {"row_id": "R03", "cause": {"text": "가압기 히터 제어 오류로 과열", "keywords": [["히터"]]},
        "consequences": [{"text": "가압기 압력 상승", "keywords": [["압력"], ["상승"]]}], "safeguards": null}
     ]},
    {"deviation_ref": {"parameter": "압력", "guide_word": "Less"}, "label": "압력 감소",
     "rows": [
       {"row_id": "R04", "cause": {"text": "살수 밸브 오개방", "equipment": ["RC-PV101"], "keywords": [["오개방", "열림고착"]]},
        "consequences": [{"text": "가압기 압력 감소", "keywords": [["압력"], ["감소", "저하"]]}], "safeguards": []},
       {"row_id": "R05", "cause": {"text": "POSRV 시트 누설", "equipment": ["RC-PSV101"], "keywords": [["시트누설", "오개방"]]},
        "consequences": [{"text": "RC-L031로 냉각재 방출", "equipment": ["RC-L031"], "keywords": [["방출"]]}],
        "safeguards": [{"keywords": [["경보"]], "text": "저압 경보 후 운전원 조치"}]}
     ]}
  ]
}
```

이 파일은 `item_id` 대응(d03·d09), 영문 가이드워드 대응(`Less`가 후보 `guide_word_en`과 일치, d10), 별칭(`PZR`), 설비 없는 원인(R03), `safeguards`의 `null`·`[]`·키워드 항목을 모두 포함합니다.

### 7.2 고정 비교 입력 뷰 (`view-fixture-draft`)

시나리오 문장은 실제 실행 `analysis-20261104T105431Z-2e14dd`의 패턴·AI 문장을 참고해 고정한 **가상 사례**입니다(실제 실행의 값과 같다고 보장하지 않음).

| 편차 (`candidate_id`, 선택 상태) | 시나리오 | 원인 설비 | 원인 문장 | 결과 문장 | 보호수단 태그 |
| --- | --- | --- | --- | --- | --- |
| `deviation-p86-d03` 유량/없음, selected | (없음) | | | | |
| `deviation-p86-d09` 압력/증가, selected | S1 `scenario-p86-d09-01` | RC-PZ01 | RC-L010 써지 배관을 통한 냉각재 유입(인서지) 증가 | 증기 공간 압축으로 RC-PZ01 압력 상승 | RC-PSV101, RC-PSV102 |
| 〃 | S2 `scenario-p86-d09-03` | RC-PIC110 | RC-PIC110 제어기 출력 오류로 RC-PV101 오동작 | RC-PV101가 조절하는 유입량 이상으로 연결 용기 압력 이탈 | RC-PSV101 |
| 〃 | S3 `scenario-p86-d09-04` | RC-PV101 | RC-PV101 개방 실패(정상 닫힘)로 압력 상승 시 유량 공급 불가 | RC-PV101를 통한 압력 상승 억제 기능 상실 | RC-PSV101 |
| `deviation-p86-d10` 압력/감소, selected | S4 `scenario-p86-d10-04` | RC-PV101 | RC-PV101 오개방 또는 열림 고착(정상 닫힘 밸브) | RC-PV101를 통한 과도 유입으로 연결 용기 압력 감소·혼합 증가 | RC-PSV101 |
| 〃 | S5 `scenario-p86-d10-05` | RC-PSV101 | RC-PSV101 오개방·개방 고착 또는 시트 누설 | 보호 대상 압력 감소, 방출 배관 하류로 유체 방출 | (없음) |
| `deviation-p86-d12` 온도/증가, selected | S6 `scenario-p86-d12-01` | RC-PZ01 | RC-PZ01 압력 상승에 따른 포화온도 상승 | RC-PZ01 및 연결 배관 온도 증가 | (없음) |

뷰의 나머지 값은 다음과 같습니다. 후보의 `guide_word_en`은 d03 `No, Not, or None`, d09·d12 `More`, d10 `Less`입니다. `graph_tags`는 `RC-L010, RC-L031, RC-PIC110, RC-PSV101, RC-PSV102, RC-PT110, RC-PV101, RC-PZ01`이고, 보호수단 `description`은 모두 빈 문자열이며, `excluded_by_review`는 0입니다.

`view-fixture-reviewed`는 위 뷰에서 다음만 바꿉니다(`excluded_by_review: 1`): S2 결정 `reject`(비교 대상에서 빠짐), S3 결정 `modify`·보호수단 수정 `RC-PSV101, RC-PSV102`·권고 "RC-PV101 살수 개방 실패 대비 경보 검토"(설계보완 후보 `accept`).

### 7.3 사례와 기대 결과

| ID | 사례 | 기대 결과 |
| --- | --- | --- |
| E1 | 7.1 기준 × `view-fixture-draft` | `status: ok`. 대응 R01–S1, R02–S3, R04–S4, R05–S5(`M` = `Mc` = 4). 편차 재현율 2/3 = 0.666667, 원인 재현율 4/6 = 0.666667, 원인 정밀도 4/5 = 0.8, 결과 일치율 3/5 = 0.6, 보호수단 일치율 3/5 = 0.6, 권고 `not_evaluated`, `criteria_warnings` 없음 |
| E1-a | E1의 누락 목록 | 편차 d03(`no_scenario`). 행 R03(`no_keyword_match`, 설비 조건 없음), R06(`deviation_not_reproduced`). 결과 R02 #2(과압), R05 #1(`RC-L031`이 문장에 없음). 보호수단 R02 `RC-PSV102`, R05 키워드 `경보` |
| E1-b | E1의 초과 목록 | 편차 d12(S6). 시나리오 S2. 보호수단 R04–S4 `RC-PSV101`(기준 `[]`) |
| E1-c | E1의 대응 근거 | R01은 별칭 `PZR` → `RC-PZ01`로 설비 일치. S2 원인 문장에 `RC-PV101`이 있어도 원인 설비가 RC-PIC110이므로 R02와 대응하지 않음. d10은 기준 `Less`가 후보 `guide_word_en` `Less`와 일치해 대응 |
| E2 | 7.1 기준 × `view-fixture-reviewed` | 원인 정밀도 4/4 = 1.0(`excluded_by_review: 1`), 보호수단 일치율 4/5 = 0.8, 권고 일치율 1/1 = 1.0. 나머지 지표는 E1과 같음 |
| E3 | E1을 메모리에서 두 번 계산(파일 쓰기 없음)해 각각 `dumps` | `compared_at`을 뺀 문자열이 같고 `comparison_id`도 같음. 파일 쓰기까지 확인할 때는 임시 작업 루트에서 서로 다른 `--now`로 두 번 실행해 두 파일의 `compared_at` 제외 내용이 같음을 확인. 같은 `--now`로 다시 쓰면 실패(덮어쓰지 않음) |
| E4 | 기준 `region_id`를 `region-OTHER`로 변경 | `blocked`, 지표 없음 |
| E5 | `row_id` 중복 / R03의 `keywords` 삭제(설비·키워드 모두 없음) / 키워드 그룹 `[]` | 각각 `blocked`, 사유에 행 ID |
| E6 | `tag_aliases`에 `{"A": "B", "B": "RC-PZ01"}` | `blocked`(별칭 연쇄) |
| E7 | 기준 편차 `{"parameter": "누출", "guide_word": "있음"}`을 필수 행 1개(`R07`)와 함께 추가 | `missing.deviations`에 `not_in_catalog`, 편차 재현율 2/4 = 0.5, 원인 재현율 4/7 = 0.571429, 원인 정밀도 4/5 = 0.8(변화 없음). 차단하지 않음 |
| E8 | R01 원인 설비 `PZR`을 `RC-PZ99`로 변경 | `criteria_warnings`: `tag_not_in_graph` `RC-PZ99`, `alias_unused` `PZR`. R01은 `no_equipment_match`로 누락, S1은 초과 시나리오. 원인 재현율 3/6 = 0.5, 원인 정밀도 3/5 = 0.6, 결과 일치율 2/4 = 0.5, 보호수단 일치율 1/3 = 0.333333, 편차 재현율 2/3 = 0.666667 |
| E9 | 태그 경계: 기준 결과 설비 `RC-L010`, 출력 결과 문장 "RC-L010-T3 부근 누설" | 불일치 |
| E10 | §2.2 Excel 양식으로 7.1과 같은 내용을 작성해 `xlsx_sheet` 어댑터로 읽음 | 변환 결과가 §2.2에서 Excel로 받는다고 명시한 모든 필드에서 7.1과 같음(양쪽 모두 생략 필드에 기본값 `required: true`·`expected: "scenarios"`·`recommendations: []`·`safeguards: null`을 채운 뒤 키 정렬 비교). 다른 점은 R05 보호수단의 `text`("저압 경보 후 운전원 조치")가 없는 것 하나. 지표는 E1과 같음 |
| E11 | Excel H열 2줄, J열 1줄 | `blocked`(줄 수 불일치) |
| E12 | Excel 셀에 `=1+1` 수식 | `blocked`(수식 셀) |
| E13 | 뷰 생성기: 실제 실행 폴더(`output/analysis/region-SNP-M-102-pzr/` 최신 실행)를 임시 작업 루트에 복사하고, 빈 임시 저장 루트(검토 기록 없음)로 `draft` 뷰 생성 | 뷰의 시나리오 수 = analysis.json에서 선택 편차의 시나리오 수, 각 원인·결과 문장 = `merge_display(s, None)` 값, `analysis_sha256` = 파일 SHA-256, `graph_tags` = 사본 `inputs/graph.json` 태그. 저장소의 `output/`은 바뀌지 않음 |
| E14 | E13의 임시 사본에서 `export_worksheet`로 출력 기록을 만든 뒤, 사본 `analysis.json`을 1바이트 바꾸고 `--export`로 비교 | `blocked`(해시 불일치) |
| E15 | `provenance.kind: synthetic` | 보고 JSON·Excel 요약에 "가상 기준 — MVP 성공 판단에 쓰지 않음" 표시 |

### 7.4 통과 기준

E1–E15가 모두 기대 결과와 같아야 합니다. 지표 값은 6자리 반올림 값으로 비교합니다. 비교 기능의 통과는 비교 계산이 규칙대로라는 뜻이며, 분석 결과가 공학적으로 옳다는 뜻이 아닙니다([공통 원칙 §검증](overview.md#principles)).

## 8. 미확정 사항

| 항목 | 현재 처리 |
| --- | --- |
| 사용자 평가 기준의 실제 형식 | 미제공. 받으면 §2와 비교해 그대로 쓰거나 §6 어댑터 추가 |
| MVP 성공 문턱값(예: 원인 재현율 몇 % 이상) | 정하지 않음. 사용자 기준 수령 후 사용자에게 확인 |
| 키워드 포함 판정의 한계 | 부정문("상승하지 않음")도 "상승" 포함으로 일치 처리됨. 기준 작성자가 키워드를 구체적으로 써서 줄이며, 자동 보정은 하지 않음 |
| 여러 구간·운전모드를 한 파일에 담는 형식 | 후속. MVP는 1파일 = 1구간·1모드 |
| 용어 출처(Pressurizer, POSRV) | 원문 미확인. 실제 원전 자료에 적용하기 전에 NRC Glossary·APR1400 설계 문서와 대조 |
