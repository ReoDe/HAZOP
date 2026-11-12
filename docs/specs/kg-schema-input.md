---
doc_id: HZ-PLN-15
rev: 0
status: draft
author: unknown
reviewed: —
approved: —
---

# 지식그래프 스키마 부속 2: 입력 문서·잠재 후보·추출 갭 (미확정)

[본문](kg-schema.md) · [부속 1: 노드·관계 사전](kg-schema-dictionary.md)

작성일 2026-11-08. 설계안이며 확정되지 않았습니다.

## 1. 입력 문서 목록

**우선순위 기준** [추론]: P1은 (가) 표 형식이라 규칙 추출의 정확도를 잴 수 있고 (나) 지금 그래프의 빈 속성(정상 위치·고장 위치·설정치)을 바로 메우는 문서, P2는 보호수단·원인 연결에 핵심이지만 AI 보조와 사람 확인이 필요한 문서, P3은 참고·교차확인용입니다.

**추출 방식**: `규칙`(결정적 규칙, 지금 `docextract.py`와 같은 방식), `사람`(CSV·화면 입력), `AI 보조`(AI 초안 → 사람 확인 전까지 `hypothesis`, 계산 제외). 이 열은 공개 자료와 일반지식으로 정했으며 실제 사업자 문서로 시험하지 않았습니다.

| 우선 | 문서 (`doc_class`) | 담긴 정보 | 그래프 매핑 | 추출 방식 | 근거 규정·출처 |
| --- | --- | --- | --- | --- | --- |
| P1 | 설정치 목록·설정치 계산서 (`setpoint_list`) | 태그, 경보·트립 설정치, 방향(High/Low), 해석한계·허용값 | `setpoint`(`setpoint_type`) –has_setpoint← 계기 / 안전밸브 | 규칙(표) + 계산서 근거는 사람 | RG 1.105 Rev. 4가 ISA-67.04.01-2018 승인(검색 발췌) |
| P1 | 계기 목록 (`instrument_index`) | 태그, 측정변수, 범위, 루프 번호, P&ID 번호, 안전 등급 | 계기 속성 주장, `in_loop`, `safety_class` | 규칙(표) | 업계 관행 [일반지식] |
| P1 | 기기 데이터시트 (`datasheet`) | 설계압력·온도, 정격, 재질, 구동기 형식, 고장 위치, 안전 등급·내진 범주 | 속성 주장(`design_pressure_max` 등), `actuated_by` | 규칙(표) | 업계 관행 [일반지식] |
| P1 | 라인 목록·배관 등급표 | 라인 번호, 배관 등급, 관경, 설계압력·온도, 유체 | 배관 구간 속성 주장 | 규칙(표) | 업계 관행 [일반지식]. DEXPI 구간 속성 이름 참고 |
| P1 | 계통 설계 기술서 (`sdd`) | 계통 기능, 설계의도, 정상·최소·최대 운전조건, 계통 경계, 고장 시 안전 위치 | `requirement`(`design_intent`), `condition`, `offdrawing_item`(`system`), `part_of_system` | AI 보조 + 사람(양식이 사업자마다 다름) | NRC 의무 문서 아님. 10 CFR 50.2 design bases와 관련 |
| P2 | 기술지침서·Bases (`tech_spec`) | LCO, 적용 모드, 조치·완료시간, 감시요건·주기, LSSS·허용값 | `lco`, `surveillance`, `requires`, `verifies`, `setpoint`(`allowable_value`) | 규칙(LCO 표 형식) + Bases는 AI 보조 | 10 CFR 50.36; 표준 기술지침서 NUREG-1430~1434 |
| P2 | 논리도·제어루프도·결선도 (`logic_diagram`) | 인터록 조건, 논리(2-out-of-4 등), 자동 기동·정지, 우회, 신호 상실 거동 | `logic_function`, `logic_input`, `logic_actuates` | AI 보조 + **사람 확인 필수** | 양식 규정 없음. 10 CFR 50 부록 A GDC 20–29 |
| P2 | 경보대응절차 (`procedure`, ARP) | 경보 → 원인 → 조치 | `alarm`, `alarm_on`, `responded_by`, `operator_action`, `acts_on` | 규칙(표) + AI 보조 | RG 1.33 부록 A(검색 발췌) |
| P2 | 비정상·비상 운전절차 (`procedure`, AOP/EOP) | 진입조건, 운전원 조치, 허용 시간 | `operator_action`, `acts_on` | AI 보조 + 사람 | RG 1.33 부록 A, NUREG-0899(검색 발췌) |
| P2 | 과거 HAZOP·위험성평가 (`prior_hazop`) | 편차·원인·결과·보호수단·권고 | `analysis_case`(`prior_hazop`), `analyzed_in` | 규칙(워크시트 표) | KOSHA C-C-37-2026 별지 5 |
| P3 | FSAR/DCD 5·6·7·9·10장 (`fsar`) | 계통 기능, 설계 조건, 연동 개요 | `requirement`(`design_basis`), `offdrawing_item`(`system`) | AI 보조 + 사람(장·절 구조는 규칙) | 10 CFR 50.34(b), 50.71(e); NUREG-0800 장 구성 |
| P3 | FSAR/DCD 15장 | 초기사건, 해석한계, 가정 고장, 결과 | `analysis_case`(`accident_analysis`), `setpoint`(`analytical_limit`) | AI 보조 + 사람 | NUREG-0800 15장 |
| P3 | 운전경험: LER, NRC Information Notice (`operating_experience`) | 실제 고장 모드·원인·시정조치, EIIS 코드 | `analysis_case`(`operating_experience`), `failure_mode` | 규칙(LER 양식 필드) + AI 보조(서술부) | 10 CFR 50.73 |
| P3 | PRA·초기사건 목록 (`pra`) | 초기사건, 기본사건 | `analysis_case`(`pra_initiating_event`) | 사람(사업자 내부, 형식 다양) | RG 1.200 Rev. 3(검색 발췌) |
| 제외 | INPO OE, EPIX/ICES | 신뢰도·고장 사례 | — | 사용 불가(비공개) | 하위 조사 |
| 보안 확인 | 정비이력(CMMS) | 반복 고장 | `analysis_case` | 규칙(DB 내보내기), 보안 등급 확인 후 | 사업자 내부 |

- 실제 설계자료는 보안 등급이 있을 수 있습니다. 문서 추출은 로컬에서만 하고, AI 보조 추출은 [CLAUDE.md](../CLAUDE.md) 총괄 규칙 7과 같이 사용자 확인 없이 외부로 보내지 않습니다.
- AI 보조 추출로 만든 노드·관계는 모두 `origin: ai_draft`, `knowledge_status: hypothesis`로 시작합니다(본문 §3).

## 2. 잠재 후보(기대 패턴) 규칙과 상태 모델

### 2.1 상태 모델

| 상태 | 뜻 | 들어오는 길 | 계산 뷰 | 화면 |
| --- | --- | --- | --- | --- |
| `expected` 기대됨 | 규칙상 있어야 하는데 아직 못 찾음 | 규칙 적용, 후보 기각, 판 변경 재확인 | 제외 | 점선 노드, '기대 공백'에 셈 |
| `candidate_found` 후보 발견 | 규칙이 맞을 법한 노드·속성을 찾음(사람 확인 전) | 규칙 적용 | 제외 | 점선 + `satisfied_by` 파선 |
| `confirmed_present` 확인됨 | 사람이 후보(또는 직접 지정한 대상)를 확인 | 사람 | 제외(기대 노드 자체). 실제 대상은 원래 규칙대로 | 기본 숨김 |
| `confirmed_absent` 부재 확정 | 사람이 근거를 보고 없음을 확정 | 사람(사유·근거 문서 필수) | 제외 | 강조. ⑤ 힌트로 전달 |
| `not_applicable` 무관 | 이 대상에는 기대가 맞지 않음 | 사람(사유 필수) | 제외 | 기본 숨김 |

- **판정 키** = `(rule_id, rule_version, target 안정 참조, target 판 정보)`. 기존 연결 후보 키(그래프활용 §3.2)와 같은 원리입니다. 도면·문서 판이 바뀌면 사람 판정을 `previous_state`로 보여 주고 `expected`로 되돌립니다. 규칙 판이 바뀌어도 같습니다.
- 판정 저장은 `data/latent-candidates/<project_id>.json`(제안). 원본 파일을 고치지 않습니다.
- 잠재 후보는 **사실이 아닙니다**. "PSV가 없다"가 아니라 "과압 보호수단을 이 그래프에서 확인하지 못했다"입니다. 도면 범위 밖(다른 도면, 미등록 도면)에 있을 수 있으므로 부재 확정은 사람만 합니다.

### 2.2 초기 규칙 목록

**근거 수준**: `표준`(원문 확인), `2차`(2차 출처), `발췌`(검색 결과 발췌만), `일반`(일반지식), `기존`(이 프로젝트에 이미 있는 미확인 항목을 옮김). 초기 구현은 E01~E08을 권합니다.

| ID | 대상 | 기대 | 충족 판정(후보 발견) | HAZOP 연결 | 근거 수준 |
| --- | --- | --- | --- | --- | --- |
| E01 | 펌프 | 출구 쪽 역류 방지 체크밸브 | 펌프에서 물리 연결로 k홉(초기 3) 안 `check_valve`. 흐름 방향이 확인되면 하류 여부를 표시만 하고 후보를 버리지 않음 | 역류 편차의 보호수단·원인 | 일반 |
| E02 | 압력 경계 설비(용기·탱크·가압기·열교환기) | 과압 보호수단 | `protects` 관계, 또는 물리 연결 k홉 안 안전밸브·방출밸브·파열판 | 압력 증가 편차의 보호수단. 부재 확정 시 원인·권고 검토 힌트 | 일반(압력용기 과압 보호는 ASME 규격 요구로 알려져 있으나 조항 원문 미확인) |
| E03 | 탱크·용기 | 수위 계측 | `measurement_connection`으로 이어진 계기 중 측정변수 `L` | 수위 증가·감소 편차의 감지 | 일반 |
| E04 | 구동 밸브(전동·공기구동·전자·제어) | 고장 위치 속성 | `fail_position` 주장 존재 | 공기·전원 상실 편차 | 일반. DEXPI도 고장 동작을 별도 속성으로 둠(2.0.1 확인) |
| E05 | 구동 밸브 | 구동원 의존(공기·전원) | `depends_on`(`air`·`power`) 또는 `actuated_by` | 지원계통 상실 원인, 공통원인 | 일반 |
| E06 | 안전밸브·방출밸브 | 설정압력과 보호 대상 설계압력 | 두 값의 주장이 모두 있음. 있으면 `설정압력 ≤ 설계압력` 비교 결과를 표시(단위·기준이 다르면 비교 안 함) | 보호수단 적정성 질문(판정은 사람) | 일반(기존 [정보통합관리](integration.md#hazop-탐색에-필요한-최소-정의) '설계 한계' 행) |
| E07 | 계기(ISA 기능 문자에 경보 `A` 또는 스위치 `S`가 있는 태그) | 설정치 | `has_setpoint` | 경보·트립 보호수단의 작동점 | 2차(ISA-5.1 문자 의미는 2차 출처) |
| E08 | 제어기 | 루프 완결: 측정 계기 → 제어기 → 최종제어요소 | 제어기 양쪽에 `signal_connection`(입력 계기, 출력 밸브) | 제어 실패 원인 편차 | 일반(기존 정보통합관리 '제어루프' 행) |
| E09 | 체크밸브 | 허용 방향 | `check_direction` 확정 | 역류 | 기존(`unknown_check_valve_direction`) |
| E10 | 열교환기·증기발생기 | 포트(관측·동체측) | 끝점 `port` | 내부 누설·유로 | 기존(`missing_port`) |
| E11 | 배관 구간 | 라인 번호·설계압력·설계온도 | 속성 주장 | 누출·과압 경로 | 일반 |
| E12 | 도면 연결점 | 상대 도면 짝 | `sheet_link` 연결 | 도면 경계에서 끊긴 전파 | 기존(`project.py` 미연결 사유) |
| E13 | 문서가 언급한 태그 | 도면 노드 | 프로젝트 도면에 태그가 하나 있음 | '도면에 없는 언급'(예 RC-V999): 도면 누락 또는 문서 오류 | 기존(그래프활용 §3.1) |
| E14 | 안전 관련 표시가 있는 기기 | 안전 등급 속성 | `safety_class` 주장 | 결과 심각도 판단 참고 | 일반(값 목록은 본문 U8) |
| E15 | 경보 | 대응 운전원 조치 | `responded_by` | 수동 보호수단의 성립 조건 | 발췌(RG 1.33 부록 A) |
| E16 | 격리 대상 기기(펌프·열교환기) | 입출구 격리밸브 | 물리 연결 k홉 안 격리·수동밸브 | 정비 중 누출 편차 | 일반, 우선 낮음 |

- E09·E10·E12·E13은 이미 미확인 항목으로 기록되는 것을 같은 상태 모델로 옮기는 것입니다. 새 판정 규칙이 아니라 표현 통일입니다.
- "k홉 안"은 화면 계산과 같은 V1(물리 무방향)을 쓰고, 방향은 표시만 합니다(그래프활용 §4.1 물리 탐색 규칙). 홉 수는 샘플로 정합니다.
- 규칙은 레지스트리와 같은 방식의 데이터 파일(`hazop/kg/schema/expectations.json`, 제안)에 두고 `rule_version`을 매깁니다. 코드에는 판정 함수 종류(이웃 탐색·속성 존재·관계 존재·값 비교)만 둡니다.

### 2.3 HAZOP 원인·보호수단과 A2로 이어지는 방식

```mermaid
flowchart LR
  R[기대 규칙 E02<br/>용기 과압 보호] --> X{그래프에서 찾음?}
  X -- 예 --> CF[후보 발견<br/>PSV-101]
  X -- 아니오 --> EXP[기대됨]
  CF -- 사람 확인 --> OK[확인됨<br/>→ 보호수단 후보]
  EXP -- 사람: 근거 보고 없음 --> AB[부재 확정]
  EXP --> A2[③ A2 '기대 공백']
  AB --> A2
  AB --> H[⑤ AI 맥락: 새 필드(확인되지 않은 기대 항목)<br/>검토 화면: 보호수단 확인 힌트]
  OK --> SG[⑤ 보호수단 후보 목록]
  H -. 사람이 판단 .-> RC[권고 작성]
```

- ⑤ AI 맥락에는 `confirmed_absent`와 `expected` 상태를 "확인되지 않은 기대 항목"으로 넣습니다. 지금 ⑤ 결과 형식에는 이런 칸이 없으므로(`ai_basis.warnings`만 있음) 새 필드로 둡니다. AI는 이를 근거로 "보호수단 없음"이라고 결론 내지 않고 정보 부족으로 다룹니다(④의 `missing_information`·규칙 11과 같은 방향).
- `confirmed_present`의 실제 대상(예: PSV-101)은 ⑤ 보호수단 후보 목록에 대상 태그로 보입니다. 보호수단의 독립성·용량·작동 적정성은 확정하지 않습니다(기존 원칙).

## 3. P&ID 속성 추출 갭

### 3.1 기기 종류별 핵심 속성과 출처

**"P&ID에서"**: 도면에 보통 표기됨(기호·태그·주기). **"문서에서"**: 데이터시트·목록에서 와야 함. **"사람"**: 판단이 필요해 사람이 넣어야 함. 판단은 [일반지식]입니다.

| 기기 | 속성 | P&ID에서 | 문서에서 | 사람 | drawio 추출기(지금) | PDF 추출기(지금) |
| --- | --- | --- | --- | --- | --- | --- |
| 밸브 | 정상 위치(NO/NC/LO/LC) | ○(LO·LC 표기, 기호) | 운전절차 밸브 목록 | 확인 | 속성으로 읽고 검사(`rules.py:26–28`) | **없음** |
| 밸브 | 고장 위치(FO/FC/FL) | ○(FO·FC 표기) | 데이터시트 | — | 제어밸브만 검사(`rules.py:30`) | **없음** |
| 밸브 | 구동 방식 | ○(기호) | 데이터시트 | — | `kind`로 일부(전동·제어) | 기호로 일부 |
| 밸브 | 크기 | △(라인 관경으로 추정 금지) | 데이터시트 | — | 속성이 있으면 복사만 | 없음 |
| 체크밸브 | 허용 방향 | ○(기호 화살표) | — | 확인 | 규칙 있음(A1) | 분류만 |
| 안전밸브 | 설정압력 | △(주기에 있을 때) | 설정치 목록·데이터시트 | — | 속성이 있으면 복사만 | 없음 |
| 안전밸브 | 보호 대상 | △(연결로 추정) | 데이터시트·SDD | 확인 | 없음 | 없음 |
| 펌프 | 정격 유량·양정, 구동기 | ✕ | 데이터시트 | — | 속성이 있으면 복사만 | 없음 |
| 용기·탱크 | 설계압력·온도 | △(표기될 때) | 데이터시트 | — | 속성이 있으면 복사만 | 없음 |
| 계기 | 측정변수·기능·루프 번호 | ○(태그 문자) | 계기 목록 | — | 태그만(파싱 없음) | 태그만(ISA 접두 추정 `[추론]`) |
| 계기 | 범위·설정치 | ✕(대개) | 계기 목록·설정치 목록 | — | 없음 | 없음 |
| 계기 | 안전 등급·채널 | △ | 계기 목록 | — | 없음 | 없음 |
| 배관 | 라인 번호 | ○ | 라인 목록 | — | `line_no` 읽음 | **없음** |
| 배관 | 배관 등급·관경·유체 | ○(라인 번호에 포함되는 경우가 많음) | 라인 목록 | — | 속성이 있으면 복사만 | 없음 |
| 배관 | 설계압력·온도·재질 | ✕ | 라인 목록·배관 등급표 | — | 속성이 있으면 복사만 | 없음 |
| 배관 | 흐름 방향 | ○(화살표) | — | 확인 | 확인된 것만(`flow_direction`) | 없음 |
| 공통 | 안전 등급·내진 범주·품질군 | △(일부 도면 표기) | 데이터시트·Q-list | 확인 | 없음 | 없음 |

### 3.2 갭 요약과 처리 단계

| 갭 | 영향 | 처리 | 단계 |
| --- | --- | --- | --- |
| PDF 추출은 속성이 0개(`pdf_vector.py`, `attributes={}`) | PDF로 등록한 도면은 A1 정상 유로 판단이 모두 미확인 | 기호 옆 표기(LO·LC·FO·FC) 읽기 규칙 추가, 못 읽으면 미확인 | M2 |
| 사람 수정 연산에 정상 위치·고장 위치·속성 편집이 없음(`corrections.py:358–377`) | 사람이 고칠 길이 없음 | `set_attribute` 연산 추가(속성 주장 `origin: human_edit`) | M2 |
| drawio는 모든 속성을 이름 검사 없이 복사 | 오타 속성이 조용히 무시됨 | 레지스트리 속성 사전으로 검사(경고만, 차단 아님) | M2 |
| 계기 태그를 파싱하지 않음 | 편차 변수와 계기 대응이 안 됨(E03·E07 판정 불가) | ISA 태그 파서(원전 고유 문자 허용, 못 읽으면 미확인) | M2 |
| 사람 수정 표시가 그래프에서 사라짐(`graph/build.py`) | 어떤 값이 사람 수정인지 ④⑤가 모름 | `origin: human_edit` 전달 | M1 |
| 값이 모두 문자열 | 설정압력 ≤ 설계압력 같은 비교 불가 | 속성 주장에 정규화 값 추가(원문 보존) | M3 |
| 데이터시트·목록 입력 경로 없음 | 문서에서 와야 하는 속성이 모두 비어 있음 | 표 추출기(CSV·Excel 우선) | M6 |

## 4. 어디에 둘지 애매한 항목의 배치

| 항목 | P&ID 층 | 지식 층 | 기대 층 | 검토 층 | 판단 |
| --- | --- | --- | --- | --- | --- |
| 도면에 그려진 안전밸브 | ● | | | | 도면 객체 |
| 문서에만 있는 인터록 논리 | | ● `logic_function` | | | 도면에 없음 |
| 공기 공급 계통(도면에 안 그려짐) | | ● `offdrawing_item` | | | `on_drawing: false` |
| "이 용기에 과압 보호가 있어야 함" | | | ● | | 규칙 기대 |
| PSV 설정압력 값 | | ● `setpoint`(노드) | | | 값 주장, 그래프에 보임 |
| 밸브 정상 위치 값 | 노드 안 속성 주장(`inline`) | | | | 그래프 노드 아님 |
| 과거 HAZOP 기록 | | ● `analysis_case` | | | 참고 사례 |
| 이번 HAZOP 결과 행 | | | | ● 투영 | 원본은 결과 파일 |
| 고장 모드 FTC | | ● `failure_mode` | | | 원인과 `cause_mode`로 연결 |
| 지지물 | | ● `offdrawing_item`(`support`) | | | 클래스만 예약 |

## 5. 조사 출처

확인일은 모두 2026-11-08입니다. **확인**은 본문을 읽음, **발췌**는 검색 결과 발췌만, **2차**는 2차 출처입니다. 저작물은 요약만 했습니다.

| 주제 | 출처 | 확인 수준 |
| --- | --- | --- |
| DEXPI 2.0.1 클래스·속성 | https://dexpi.org/specification/2.0.1/html/ (Plant 모델, Piping·Instrumentation·ProcessEquipment 패키지, `PipingNetworkSegment`·`Nozzle`·`Chamber`·`ControlledActuator` 쪽) | 확인 |
| DEXPI 2.0.1 발표·라이선스(CC BY 4.0) | https://dexpi.org/dexpi-2-0-1-specification-published-the-update-replacing-dexpi-2-0/ | 확인 |
| CFIHOS 태그 클래스·기기 클래스 구분 | https://www.jip36-cfihos.org/ , https://posccaesar.org/cfihos/v2.0/CFIHOS-00000071 | 확인(홈·RDL 항목), 구분 설명은 2차 |
| ISO 15926 기능 태그와 설치 기기 | https://15926.blog/blogs/20240303.html | 2차 |
| IEC 81346 관점 접두(=, -, +) | https://en.wikipedia.org/wiki/IEC_81346 | 2차 |
| ISA-5.1-2024 태그 구조 | https://www.isa.org/news-press-releases/2024/october/widely-used-engineering-symbols-and-drawings-stand , https://en.wikipedia.org/wiki/Piping_and_instrumentation_diagram | 발표문 확인, 문자 규칙은 2차 |
| KKS(VGB-S-811-01) | https://www.dinmedia.de/en/technical-rule/vgb-s-811-01/291233973 | 목록만. 국내 원전 사용 여부 미확인 |
| EIIS(10 CFR 50.73) | https://www.law.cornell.edu/cfr/text/10/50.73 | 확인(LII) |
| IEC 61882:2016 | https://webstore.iec.ch/publication/24321 , https://assets.vde-verlag.de/iec-normen/preview-pdf/info_iec61882%7Bed2.0%7Db.pdf , https://www.primatech.com/images/docs/comparison-of-hazop-application-guide.pdf | 미리보기 일부, 비교 백서 확인. 본문 정의 미확인 |
| KOSHA C-C-37-2026(연속공정 HAZOP) | https://portal.kosha.or.kr/openapi/v1/file/down/CTC2026013015285726898044/2 | 확인 |
| 보호수단 예방·완화(bow-tie) | Hatch 외, CEP 2019-02, https://www.aiche.org/sites/default/files/cep/20190220.pdf | 확인 |
| IPL 기준(효과·독립·감사 가능) | https://www.primatech.com/technical/pt-notes/171 | 확인 |
| PHA 소프트웨어 구조 | https://www.kenexis.com/wp-content/uploads/2024/06/Open-PHA-Brochure-12JUN2024.pdf , https://www.primatech.com/software/phaworks/phaworks-and-lopa , https://sphera.com/wp-content/uploads/2024/09/PHA-Pro-Brochure-Updated.pdf | 홍보 자료 확인. 필드 수준 스키마는 공개되지 않음 |
| 10 CFR 50.2, 50.34, 50.36, 50.71, 부록 A | https://www.law.cornell.edu/cfr/text/10/50.2 , https://www.law.cornell.edu/cfr/text/10/50.36 , https://www.law.cornell.edu/cfr/text/10/appendix-A_to_part_50 | 확인(LII 사본. eCFR은 자동 접근 차단) |
| NUREG-0800 장 구성 | https://www.nrc.gov/reading-rm/doc-collections/nuregs/staff/sr0800 | 확인 |
| APR1400 DCD 장 구성 | https://www.nrc.gov/facilities-safety/new-reactors/large-light-water-reactors/design-certification-applications-for-new-reactors/apr1400/apr1400-design-control-document-and-environmental-report | 확인(Rev. 3이 최종 인증본인지는 미확인) |
| 표준 기술지침서 NUREG-1430~1434 | https://www.nrc.gov/reactors/operating/licensing/techspecs/current-approved-sts.html | 발췌 |
| RG 1.105 Rev. 4 / ISA-67.04.01-2018 | https://regulations.justia.com/regulations/fedreg/2021/02/22/2021-03466.html | 발췌 |
| RG 1.33, NUREG-0899 | https://www.nrc.gov/docs/ml1310/ml13109a458.pdf , https://www.nrc.gov/sr0933/reference/0192.html | 열람 실패, 발췌 |
| 안전 등급(RG 1.26·1.29, ANS-58.14, IEEE 308, 원안위 고시) | https://www.nrc.gov/docs/ML2132/ML21323A025.pdf , https://www.nrc.gov/docs/ML1924/ML19246A282.pdf , https://www.nssc.go.kr/attach/namo/files/000001/20240214100409986_QSN9QU4Z.pdf | 발췌 |
| ISO 14224 고장 모드 코드 | 업체 페이지(2차) | 2차, 원문 미확인 |
