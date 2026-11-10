# 전체 기획

[프로젝트 소개](../README.md) · [최상위 플로우차트](<../flow chart/00-overview.md>)

## 목적

설계도면과 문서에 흩어진 설비·연결·운전조건·보호수단 정보를 통합하고, 원본 근거를 추적할 수 있는 전문가 검토용 HAZOP 초안을 만드는 것을 목표로 합니다.

궁극적인 대상은 원자력발전소 계통입니다. 이 프로젝트는 **HAZOP 결과를 만드는 것까지**를 범위로 하며, 그 결과를 PSA 초기사건 도출 등에 활용하는 작업은 다른 곳에서 수행합니다(사용자 결정, 2026-11-03). 현재 실험은 사용자가 draw.io로 직접 만든 샘플 P&ID로 "도면을 데이터로 분리해 HAZOP 분석에 쓸 수 있는가"를 확인하는 데 집중합니다. 실제 도면의 자료형 문제는 실험이 성공한 뒤 다룹니다.

### 용어

| 용어 | 이 프로젝트에서의 의미 | 출처 |
| --- | --- | --- |
| 검토 구간 (HAZOP node) | 여러 설비·배관을 묶은 HAZOP 분석 단위. 그래프의 개별 노드와 구분 | HAZOP 실무 통용 용어 "node" |
| 파라미터·가이드워드·편차 | 유량·압력 등의 파라미터와 없음·증가·감소·반대 등의 가이드워드를 조합한 설계 의도 이탈. 가이드워드는 KOSHA 표기를 표준으로 하고 영문·IEC 61882 대응을 병기([대응표](HAZOP기법지침.md#guide-words), 사용자 결정, 2026-11-04) | IEC 61882 (HAZOP 적용 지침), KOSHA GUIDE P-86-2017 |
| 보호수단 (safeguard) | 편차의 원인 발생이나 결과 진전을 막거나 줄이는 설비·기능 | IEC 61882 |
| 배관 구간 (pipe segment) | draw.io 커넥터 1개에 대응하는 그래프 노드. HAZOP 검토 구간(node)과 다름 | 이 프로젝트 정의([노드 단위](정보통합관리.md#node-unit)) |

## 전체 구성

1. [자료 등록](자료등록.md): 도면·표·문서의 원본과 버전을 관리합니다.
2. [정보 추출](정보추출.md): 자료 유형에 맞는 스크립트로 대상, 관계, 값과 조건을 추출합니다.
3. [정보 통합·관리](정보통합관리.md): 추출 결과를 공통 그래프 구조로 모으고 동일 대상 연결과 검증을 수행합니다.
4. [HAZOP 분석](HAZOP분석.md): 선택 구간의 정상 운전부터 편차별로 그래프 탐색과 원인·결과 패턴을 적용하고, AI가 해석·가설·위험도를 제안합니다.
5. [검토·결과 관리](검토결과관리.md): 편차별로 검토·확정하고 재검토와 Excel 출력을 관리합니다.

화면은 [데스크톱 인터페이스](인터페이스.md)에서 정의합니다(①~⑤ 화면과 Excel 출력). ③ 지식그래프 화면의 상세는 [그래프 활용 §5](그래프활용.md#5-obsidian식-그래프-화면)를 따릅니다(2026-11-05 사용자 확정).

그래프 알고리즘으로 P&ID와 비P&ID 성분을 통합·활용하는 방안과 Obsidian식 그래프 화면은 [그래프 활용](그래프활용.md)에서 구상합니다.

<a id="principles"></a>

## 공통 원칙

이 절은 모든 단계에 적용합니다. 각 단계 기획서는 이 원칙을 반복하지 않고 단계 고유의 내용만 기술합니다.

### 문서 상태

- 모든 기획서·플로우차트는 초안이며 구현 완료를 의미하지 않습니다. 구현 상태와 남은 작업은 [메모리](../메모리/README.md)에서 관리합니다.
- 결정에는 출처(사용자 결정 또는 제안)를 표시합니다. 표시가 없는 항목은 제안이며 조정할 수 있습니다.

### 근거와 식별

- 추출한 모든 정보에는 원본 자료·등록 버전·문서/페이지·원본 객체 또는 문장 위치의 근거를 남깁니다. 근거는 노드뿐 아니라 개별 사실과 관계에도 연결합니다.
- 내부 ID는 태그·파일명·도면 개정번호와 구분합니다. 동일 태그라도 프로젝트와 공정 맥락을 확인하여 대상을 식별하며, 태그만으로 대상의 종류를 판단하지 않습니다.
- 그래프의 개별 노드와 HAZOP의 검토 구간은 구분합니다.

### 미확인·충돌

- 미확인 값은 `null`과 확인 상태·사유로 표현하며 0·안전·없음으로 바꾸지 않습니다. 해당 없음과 미확인도 구분합니다.
- 원본에 없는 값·연결·흐름 방향·의미를 만들어 넣지 않습니다. 확인된 사실과 추론·가설을 구분합니다.
- 상충하는 정보는 근거와 함께 모두 보존하고 충돌로 표시하며, 임의로 확정하거나 덮어쓰지 않습니다.
- 정보가 부족하면 전체를 중단하지 않고, 영향받는 판단만 보류하고 필요한 자료를 기록합니다.

### 이력과 버전

- 원본 파일·과거 버전·확정본은 덮어쓰지 않습니다. 변경은 새 버전과 이력(주체·시각·변경 전후·사유)으로 남깁니다.
- 실행은 입력 ID·버전을 고정하며 최신 버전으로 조용히 교체하지 않습니다.
- 자동 재처리가 사람의 수정을 조용히 덮어쓰지 않으며, 같은 입력을 다시 처리해도 중복 대상이 생기지 않게 합니다.

### 검증

- 구조 검증의 차단 오류(형식 오류·잘못된 참조·모호한 병합 등)와 명시적으로 표시된 미확인 정보를 구분합니다. 차단 오류가 있는 변경은 초안으로만 보관합니다.
- 구조 검증 통과나 자동 검증은 설계 내용의 공학적 정확성·완전성을 보장하지 않으며 사람의 판단을 대신하지 않습니다.
- 각 단계는 입력·출력·검증 사례·통과/보류 기준을 갖고, 다른 단계와 AI 없이 샘플 입력으로 독립 검증할 수 있어야 합니다.

### 자동 처리·사람·AI

- 자료 등록·추출·통합은 Python 자동 처리를 기본으로 합니다.
- 사람은 노드·사실을 수동 생성·수정하고 관계를 연결·해제할 수 있으며, 자동 처리와 같은 검증을 거칩니다.
- AI의 주 용도는 ④에서 그래프 탐색 결과와 원인·결과 패턴을 근거로 한 추론입니다. 앞 단계에서는 결과가 불만족스러울 때 선택적으로 원문 대조·보정 제안에 사용할 수 있습니다.
- AI 결과는 제안입니다. 사람이 확인한 뒤 반영하며 같은 검증을 거치고, 검증을 통과시키기 위해 근거 없는 값을 생성하지 않습니다.

### 정보 관리

- 위키·Markdown은 기획과 열람에 쓰고, 분석에 필요한 값·단위·관계·적용 조건은 구조화합니다.
- 대화 중 결정은 [메모리의 결정 로그](../메모리/결정로그.md)에, 미구현 작업은 [남은 작업](../메모리/남은작업.md)에 기록합니다.

<a id="trust-boundary"></a>

### 신뢰 경계 (위협 모델)

정직한 입력에서도 결과가 틀리는 논리 결함은 고칩니다. 저장 결과나 저장소 데이터를 고의로 변조하는 경우는 신뢰 경계 밖으로 둡니다(사용자 결정, 2026-11-04).

| 구분 | 대상 | 대응 |
| --- | --- | --- |
| 신뢰하지 않는 입력 | AI 응답 | 구조·참조·근거와 도면 설비 한정 여부를 검증 |
| 신뢰하지 않는 입력 | 사용자가 제공한 원본 파일 | 형식·해시 검증 |
| 신뢰하지 않는 입력 | AI 요청에 넣는 지식 문자열(문서 조각·요건의 `text`, 이름, 위치. 사람이 지식 CSV에 옮겨 적은 것과 추출기가 뽑은 것 모두) | 지시가 아닌 자료로 구분해 전달, 구조·참조 검증([그래프 활용 §6.3](그래프활용.md#63-신뢰-경계)·§6.4. 그래프활용 D7, 권고안 채택(위임)) |
| 신뢰하는 입력 (변조는 범위 밖) | 구간 정의 | 사람 검토와 버전 관리 |
| 신뢰하는 입력 (변조는 범위 밖) | 이탈 카탈로그·적용 판단·위험도 기준표·패턴 라이브러리, [지침](HAZOP기법지침.md) | 내용 해시로 고정(`hazop/analysis/integrity.py`)하고, 불일치하면 분석 차단. 카탈로그·기준표는 지침과 대조(패키징 T2 D1·D12, [W5 근거](../docs/2026-11-05-packaging/evidence/w5-trust-boundary.md)) |
| 신뢰하는 입력 (변조는 범위 밖) | 실행 결과 폴더(`출력/`) | 입력 사본의 해시 기록 |
| 사람 기록 (변조는 범위 밖) | 지식 CSV의 구조(노드·관계의 ID·종류·참조·상태). 문자열 값을 AI 요청에 넣을 때는 위 '신뢰하지 않는 입력' 행을 따름 | 형식·참조·타입 쌍 검증, `kg_version`으로 버전 이력([그래프 활용 §6.3](그래프활용.md#63-신뢰-경계). 그래프활용 D7, 권고안 채택(위임)) |
| 사람 기록 (변조는 범위 밖) | 검토 기록(`자료저장소/reviews/`) | 버전 파일로 이력 보존([인터페이스 §5](인터페이스.md#5-검토-확정-데이터-규격), 총괄 결정(권고안, 사용자 위임 2026-11-04)) |

알려진 남은 위험은 다음 2가지입니다. 실제 발전소 자료를 쓰기 전에 다시 검토합니다.

- 패턴 라이브러리를 바꾸려면 고정 해시도 함께 갱신해야 합니다. 편차 매핑 변경이 보호수단 탐색 범위를 바꾸므로 갱신 때 사람 검토가 필요합니다.
- 저장된 `analysis.json`의 상태와 AI 응답을 함께 고친 뒤 `--resume`으로 이어서 실행하는 경우는 막지 못합니다.

<a id="mvp"></a>

## MVP와 후속 범위

첫 구현은 **수직 슬라이스**입니다(권고 승인, 2026-11-03). 사용자가 draw.io로 만든 소규모 샘플 P&ID 한 장을 ①~⑤ 전 단계에 끝까지 통과시켜, 도면을 데이터로 분리해 HAZOP 초안을 만들 수 있는지 먼저 확인합니다. 각 단계의 완성도보다 단계 사이 연결과 결과의 쓸모를 우선 검증합니다.

| 단계 | MVP (수직 슬라이스) | 후속 |
| --- | --- | --- |
| ① 자료 등록 | 지정 폴더의 draw.io 원본 1개를 Python 스크립트로 등록. 내부 ID·등록 버전·해시·미확인 항목을 등록정보 JSON으로 저장 | 웹 화면(파일 선택·드래그 앤 드롭), 개정 충돌 판정, 메타데이터 수정 이력, 설계자료 10종 |
| ② 정보 추출 | draw.io XML에서 객체·속성·커넥터를 읽어 추출 결과 JSON 생성. [작성 규칙](정보추출.md#drawio-rules)을 따르는 샘플 기준. 추출 결과를 도면 SVG 위에 보여주는 노드 선택 뷰어(로컬 정적 HTML) | 선택 구간 재처리, 오버레이 화면의 수동 편집, 형식별 어댑터(PDF·이미지·CAD), OCR·기호 탐지 |
| ③ 정보 통합·관리 | 도면 1장의 추출 결과를 networkx 그래프로 변환하고 최소 정의로 구조 검증. 검증용으로 뷰어의 그래프 보기 탭과 기본 질의(이웃·연결 경로 확인)가 이 결과를 읽어 표시. HAZOP 편차용 경로 탐색은 ④ | 여러 도면·문서의 동일 대상 통합, 값 충돌 관리, 수동 병합·분리, 데이터 사전 분리 |
| ④ HAZOP 분석 | 사람이 지정한 구간 1개·정상 운전, 소수 편차, 소규모 원인·결과 패턴, 제한된 그래프 탐색, AI 해석(Claude Code 구독제 세션에서 만든 고정 응답, 사용자 결정 2026-11-04) | 자동 구간 분할, 기동·정지 모드, 패턴 확장, Claude 팀 구독제·로컬 LLM 연결 |
| ⑤ 검토·결과 관리 | 분석 결과를 Excel 워크시트로 출력하고 사용자 평가 기준과 비교 | 검토 화면, 편차별 확정·이력, 개선 조치, 재검토 운영 |

- MVP에서도 아래 데이터 규격의 ID·버전·검증 상태·확인 수준은 따릅니다. 변경 알림·재검토·동시 수정 처리는 후속입니다.
- MVP의 성공 여부는 사용자가 제공할 평가 기준(정답 HAZOP 항목 등)과 비교해 판단합니다. 기준의 형식은 제공 시 확정합니다. 그 전까지는 [평가 기준 비교](평가기준비교.md)의 권고 형식으로 구현·검증합니다(총괄 결정(권고안, 사용자 위임 2026-11-06)).
- 실제 자료형이 실험과 다르면 형식별 읽기 어댑터를 모듈로 추가하고, 추출 결과 JSON 이후 단계는 그대로 사용하는 구조로 만듭니다(사용자 결정).
- 위 표의 후속 항목 중 ① 등록 화면, ④ 후보 판단 화면, ⑤ 검토 화면·확정 기록은 Windows 데스크톱 인터페이스로 앞당겨 구현합니다. 범위와 위 표와의 차이는 [인터페이스 기획](인터페이스.md#1-목적과-범위)을 따릅니다(사용자 결정, 2026-11-04).

## 통합 예시

### 원본 설계자료의 활용

모든 자료는 등록 후 추출 대상이 되며, 아래는 추출·통합·분석에서 각각의 역할입니다. MVP는 P&ID만 사용합니다.

| 원본 자료 | 추출 내용 | 통합 대상 | HAZOP 활용 |
| --- | --- | --- | --- |
| 공정 설계 의도 및 설명서 | 목적·역할·정상 운전 설명 | 공정·설비·운전모드 | 설계 의도와 검토 구간 |
| PFD 및 물질·열수지 | 흐름·스트림·유량·조성·열량 | 설비·스트림·물질 | 정상 흐름과 이탈 영향 |
| P&ID | 기호·태그·배관·계기·연결 | 설비·포트·배관·제어 관계 | 원인·영향 경로 |
| 물성·위험성 자료 | 물성·독성·인화성·반응성·혼합 금기 | 물질·취급 구간 | 누출·화재·독성·반응 결과 |
| 운전조건 및 허용 한계 | 정상 범위·운전 한계·설계 한계 | 설비·배관·운전모드별 조건 | 편차와 한계 초과 |
| 주요 기기·배관 설계 사양 | 용량·재질·등급·성능 | 설비·배관 | 한계와 손상 가능성 |
| 제어·경보·인터록 설계 | 측정값·설정값·조건·동작 | 계기·제어 대상·차단 대상 | 제어 실패와 보호 기능 |
| 압력 방출 및 비상 배출 설계 | 설정압력·용량·방출 경로 | 보호장치·보호 대상·배출처 | 과압 보호와 방출 영향 |
| 운전모드 및 주요 운전 절차 | 작업 순서·전환 조건·격리 방식 | 운전모드·설비·작업 | 기동·정지·정비 중 편차 |
| 유틸리티 및 외부 연결 조건 | 공급 조건·의존 관계·외부 접속 | 공급원·사용 설비·외부 시스템 | 공급 상실과 상·하류 영향 |

자료 종류와 파일 형식은 구분합니다. 한 자료에 도면·표·설명문이 함께 있으면 각 부분에 적합한 추출 방식을 적용합니다. 통합 단계의 직접 입력은 그 추출 결과이며, 원본은 검수와 추적을 위한 근거로 유지합니다.

### 동일 대상 연결 사례

아래 태그와 수치는 구조 설명을 위한 가상 예시입니다. 이 문서의 모든 예시에서 P-101은 펌프, V-101은 용기입니다.

| 원본 자료 | 추출할 정보 | 통합 방식 |
| --- | --- | --- |
| P&ID | 펌프 P-101과 용기 V-101의 연결 | 설비 사이의 배관 연결로 저장 |
| 운전조건 보고서 | V-101의 정상 운전압력 5 bar | V-101의 운전조건으로 연결 |
| 인터록 설명서 | V-101 압력이 8 bar 이상이면 P-101 정지 | 적용 조건과 정지 동작을 관련 설비에 연결 |

각 사실의 원문 근거는 별도로 유지합니다. 문서별 정보 열람과 설비별 정보 열람이 모두 가능하도록 구상합니다.

## 노드·관계·속성 정의 관리

현재는 [정보 통합·관리 기획](정보통합관리.md)의 정의 초안에서 종류와 속성, 필요한 이유와 예시를 관리합니다. P&ID 데이터 교환 표준인 DEXPI의 클래스 체계는 따르지 않고, 용어 대응표만 [정보 추출](정보추출.md#dexpi-terms)에 둡니다 (총괄 결정(권고안, 사용자 위임 2026-11-06)). 규모가 커지면 별도 데이터 사전으로 분리하고, Python이 검사할 수 있는 JSON Schema 등의 정의와 연결합니다.

정의에는 이름·의미·적용 대상·자료형·단위·필수 여부·허용값을 포함합니다.

<a id="data-contract"></a>

## 단계 간 데이터 규격 초안

이 절을 ①~⑤가 공유하는 ID·버전·상태·변경 알림의 기준으로 사용합니다. 아래 JSON은 가상 자료의 최소 전달 예시이며 실행 코드·완전한 JSON Schema·DB 테이블 정의가 아닙니다. 실제 필수 필드는 MVP 구현 시 샘플로 구체화합니다.

### 식별자와 버전

| 필드 | 의미 |
| --- | --- |
| `schema_version`, `project_id` | 전달 형식 버전과 프로젝트. 모든 단계 기록에 포함 |
| `material_id`, `registration_version` | 자료와 등록 스냅샷. 설계 문서의 개정번호와 구분. 원본·메타데이터 변경 시 새 버전 |
| `extraction_run_id`, `local_id` | 추출 실행과 그 실행 안의 임시 노드·관계. 원본 객체 ID와 구분 |
| `graph_id`, `graph_version`, `entity_id` | 통합 그래프 스냅샷과 통합 대상. 각 대상의 원본·임시 ID 대응을 유지 |
| `region_id`, `region_version` | HAZOP 검토 구간과 설계 의도·경계·운전모드의 스냅샷 |
| `analysis_run_id`, `candidate_id`, `scenario_id` | 분석 실행, 편차 후보, 원인·결과 시나리오 |
| `review_id`, `review_version` | 전문가 검토본. AI 원안·이전 검토본과 별도 보존 |
| `event_id` | 변경 알림의 고유 ID. 같은 알림 재수신 시 재검토 이력을 중복 생성하지 않도록 사용 |

버전 참조는 ID와 버전의 쌍으로 고정합니다. 해시는 파일 무결성 확인용이며 메타데이터 버전이나 그래프 버전을 대신하지 않습니다. 원본 객체 ID도 자료·등록 버전·문서/페이지 범위 안에서 해석합니다.

### 상태는 역할별로 구분

| 종류 | 필드와 값 예시 | 의미 |
| --- | --- | --- |
| 구조 검증 | `validation.status`: `passed`, `blocked` | 필수 형식·참조·제약 검사. `passed`여도 미확인 값이 있을 수 있음 |
| 미확인 정보 | `validation.unknowns` | 대상·항목·사유가 있는 목록. 차단 오류는 `blockers`에 따로 기록 |
| 정보의 확인 수준 | `knowledge_status`: `confirmed`, `unknown`, `hypothesis` | 원문/검토에서 확인한 정보, 미확인 정보, 추론 가설 구분 |
| 후보 판단 | `selection_status`: `selected`, `excluded`, `deferred` | 선택·제외·보류. 판단 주체·이유·시각을 별도 이력으로 유지 |
| 전문가 검토 | `review_status`: `not_reviewed`, `reviewing`, `deferred`, `confirmed` | 미검토·검토 중·보류·확정. 후보 판단과 독립 |
| 시나리오 초안 | `scenario_status`: `draft`, `deferred` | ④가 만든 원인·결과 초안과, 근거 부족으로 보류한 초안을 구분. 확정은 ⑤의 `review_status` |
| 위험도 | `risk_proposal.status`: `proposed`, `deferred`, `not_applicable`; `risk_confirmation` | AI 제안·보류·비적용(제외 후보 등, 사유 필수)과 사람의 확정값을 분리 |
| 재검토 | `review_required`, `review_resolution`: `rereviewed`, `no_impact` | 변경에 따른 재검토 필요 여부와 해소 방식. 과거 확정본을 삭제하지 않음 |
| 체크밸브 방향 | 노드 `check_direction.status`: `declared`, `symbol` | `declared`는 작성자 선언(도형 속성 근거, 사람 확인 전), `symbol`은 기호만으로 판정. 판정하지 못하면 `check_direction`은 `null`([정보 추출](정보추출.md)) (총괄 결정(권고안, 사용자 위임 2026-11-06)) |

`not_applicable`은 근거가 있는 비적용에만 쓰며, 판단할 수 없는 경우는 `deferred`로 둡니다. 개선 조치의 상태는 별도로 관리하며 자료 요청 메모에 조치 상태를 강제하지 않습니다.

### ① → ②: 등록 원본 참조

```json
{
  "schema_version": "0.1",
  "project_id": "project-001",
  "material_id": "material-001",
  "registration_version": 1,
  "format": "drawio",
  "storage_ref": "originals/material-001/1/sample.drawio",
  "drawing_number": null,
  "design_revision": null,
  "documents": [{"document_id": "document-001", "page_ids": ["page-001"]}],
  "validation": {
    "status": "passed",
    "blockers": [],
    "unknowns": [{"field": "design_revision", "reason": "미확인"}]
  }
}
```

저장 시 파일 해시는 등록정보에 보관합니다. `storage_ref`는 예시 저장 키이며 외부 URL이 아닙니다. ①은 문서·페이지 식별정보를 주고 ②가 실제 객체를 읽어 원본 참조를 완성합니다.

### ② → ③: 추출 결과와 원본 객체 근거

```json
{
  "schema_version": "0.1",
  "project_id": "project-001",
  "extraction_run_id": "extract-001",
  "source": {"material_id": "material-001", "registration_version": 1},
  "nodes": [
    {"local_id": "local-node-001", "kind": "pump", "tag": "P-101", "source_object_id": "cell-001"},
    {"local_id": "local-node-002", "kind": "vessel", "tag": "V-101", "source_object_id": "cell-002"},
    {"local_id": "local-node-003", "kind": "check_valve", "tag": "CV-101", "source_object_id": "cell-003",
     "check_direction": {"inlet": "local-edge-002", "outlet": "local-edge-003",
                         "basis": ["attribute"], "status": "declared"}}
  ],
  "relations": [{
    "local_id": "local-edge-001",
    "kind": "physical_connection",
    "endpoints": [
      {"end": "source", "node_local_id": "local-node-001", "source_object_id": "cell-001",
       "constraint": {"x": 1.0, "y": 0.5, "dx": 0, "dy": 0}, "point": [180, 130],
       "point_basis": "constraint", "status": "connected", "port": null},
      {"end": "target", "node_local_id": "local-node-002", "source_object_id": "cell-002",
       "constraint": null, "point": [300, 130],
       "point_basis": "terminal_center_approx", "status": "connected", "port": null}
    ],
    "source_object_id": "edge-001",
    "flow_direction": {"from": "local-node-001", "to": "local-node-002",
                       "from_end": "source", "to_end": "target", "basis": "source_to_target"}
  }],
  "unresolved_connectors": [],
  "review_status": "not_reviewed",
  "source_context": {"document_id": "document-001", "page_id": "page-001"},
  "source_locations": [{
    "object_id": "cell-001",
    "coordinate_space": "page_local_2d",
    "unit": "canvas_unit",
    "bbox": [100, 100, 80, 60]
  }],
  "validation": {
    "status": "passed",
    "blockers": [],
    "unknowns": []
  }
}
```

`endpoints`는 접속 끝점 객체의 나열이며 순서가 흐름 방향을 뜻하지 않습니다. `end`는 원본 커넥터의 source/target 중 어느 끝인지를 나타냅니다. 흐름 방향은 확인된 경우에만 `flow_direction`에 `{"from": "local-node-001", "to": "local-node-002"}`처럼 기록하고, `from_end`·`to_end`·`basis`(원본 값)를 근거로 함께 남깁니다. 확인되지 않으면 `null`로 두고 `validation.unknowns`에 기록합니다. 양 끝이 확정되지 않은 커넥터는 정상 관계와 분리해 `unresolved_connectors`에 둡니다. `review_status`는 사람의 원본 대조 상태이며 위 표의 값(`not_reviewed` 등)을 쓰고 기본값은 `not_reviewed`입니다. 임시 ID 접두어는 노드 `local-node-`, 관계 `local-edge-`, 문자 `local-text-`입니다. draw.io 커넥터의 source/target도 그리는 순서일 뿐이므로 [작성 규칙](정보추출.md#drawio-rules)에 따른 표시가 있을 때만 방향으로 해석합니다. 예시는 설비 단위 연결입니다. 포트를 구분하는 기기는 끝점의 `port` 필드(포트 이름 문자열)에 기록하며, 포트를 별도 노드·ID로 만들지 않습니다([포트 규칙](정보추출.md#port-rule)). 체크밸브 노드의 `check_direction`은 입구·출구 커넥터의 `local_id`와 근거(`basis`)·상태(`status`)이며, 예시의 `local-edge-002`·`local-edge-003`은 생략한 관계입니다 (총괄 결정(권고안, 사용자 위임 2026-11-06)).

원본 참조는 `source`·`source_context`·`source_object_id`를 합쳐 식별합니다. 좌표가 없는 객체에는 빈 좌표를 만들어 넣지 않습니다. 다른 자료형은 후속 어댑터에서 좌표계·차원·단위를 명시해 추가합니다.

### ① → ③: 설계 문서 지식(자동 추출)과 지식그래프 자동 생성

①에서 자료 종류를 `design_document`(설계 문서, 글자가 있는 PDF)로 등록하면 문서 지식 추출기가 `출력/문서지식/<등록 출력 이름>/document_knowledge.json`을 씁니다. 노드·관계 레코드는 지식 입력(`knowledge.json`)과 같은 계약이며, 모든 추출 항목은 `method: extractor`, `knowledge_status: unknown`(자동 추출, 사람 확인 전), 근거 `source`(자료 ID·등록 버전·문서·쪽·위치)를 가집니다. P&ID 도면을 추출하거나 설계 문서를 등록하면 프로젝트 지식그래프 `출력/지식그래프/kg-<project_id>/`를 다시 빌드합니다. 입력은 그 프로젝트의 도면 그래프(`graph.json`의 `project_id`), 문서 지식, 사람이 쓴 지식 CSV(있을 때만)입니다. 규칙은 [그래프 활용 §9](그래프활용.md#9-지식그래프-자동-생성과-문서-지식-추출)를 따릅니다 (사용자 결정 2026-11-06 범위, 세부는 총괄 결정(권고안, 위임) 2026-11-07).

### ③ → ④: 검증된 그래프 버전

```json
{
  "schema_version": "0.1",
  "project_id": "project-001",
  "graph_id": "graph-001",
  "graph_version": "v-0b1677ccb8b6",
  "input_runs": ["extract-001"],
  "entity_mapping": [
    {"extraction_run_id": "extract-001", "local_id": "local-node-001", "entity_id": "entity-node-001"},
    {"extraction_run_id": "extract-001", "local_id": "local-node-002", "entity_id": "entity-node-002"},
    {"extraction_run_id": "extract-001", "local_id": "local-edge-001", "entity_id": "entity-seg-001"}
  ],
  "edges": [
    {"entity_id": "relation-001", "kind": "has_endpoint", "segment": "entity-seg-001", "node": "entity-node-001", "end": "source"}
  ],
  "validation": {
    "status": "passed",
    "blockers": [],
    "unknowns": [{"target": "entity-seg-001", "field": "flow_direction", "reason": "흐름 방향 미확인(원본에 지정 없음)"}],
    "review_items": [{"target": "relation-001", "reason": "관계 양 끝 대상 제약은 가정 수준의 규칙"}]
  }
}
```

그래프 entity_id 접두어는 도형 노드 `entity-node-`, 배관 구간 노드 `entity-seg-`, 관계 `relation-`입니다. 배관 구간 노드의 흐름 속성 이름은 `flow_direction`입니다. `review_items`는 미확인(`unknowns`)과 별도로, 근거 규칙이 가정 수준인 검토 항목(예: 관계 양 끝 대상 제약)을 담습니다. `graph_version`은 입력 해시로 만든 문자열(예: `v-0b1677ccb8b6`)이며 입력이 바뀌면 바뀝니다. 그래프 본문과 원문 근거는 이 ID·버전으로 참조합니다. ④는 버전을 고정하고 관련 운전조건·물질·보호수단의 확인 여부를 추가 점검합니다.

### ④ → ⑤: 후보·시나리오·AI 제안 보존

```json
{
  "schema_version": "0.1",
  "project_id": "project-001",
  "analysis_run_id": "analysis-001",
  "graph_ref": {"graph_id": "graph-001", "graph_version": "v-0b1677ccb8b6"},
  "region_ref": {"region_id": "region-001", "region_version": 1},
  "operating_mode": "normal",
  "candidates": [
    {"candidate_id": "deviation-001", "deviation": "유량 없음", "selection_status": "selected", "reason": "검토 대상으로 선택"},
    {"candidate_id": "deviation-002", "deviation": "유체 역류", "selection_status": "deferred", "reason": "정상 흐름 방향 확인 대기"}
  ],
  "scenarios": [{
    "scenario_id": "scenario-001",
    "candidate_id": "deviation-001",
    "scenario_status": "draft",
    "knowledge_status": "hypothesis",
    "cause": "P-101 정지로 인한 V-101 유입 유량 상실 가능성",
    "pattern_ref": {"pattern_id": "pattern-pump-no-flow", "pattern_version": 1},
    "cause_equipment": ["entity-node-001"],
    "graph_evidence": {"node_ids": ["entity-node-001"], "relation_ids": ["relation-001"], "evidence_ids": ["evidence-001"]},
    "risk_proposal": {"status": "deferred", "criteria_version": null, "reason": "운전조건 미확인으로 강도 판단 근거 부족"}
  }],
  "design_improvement_candidates": []
}
```

`design_improvement_candidates`는 ④가 도면 설비 기반 시나리오에서 찾은 설계보완 후보 목록입니다. 확정은 ⑤에서 사람이 합니다([HAZOP 분석](HAZOP분석.md)). `graph_evidence`는 근거가 된 노드·관계·근거 묶음 ID 목록을 담은 객체이고, 원인 설비는 `cause_equipment`에 따로 둡니다(구현 형식 채택, 총괄 판정 2026-11-04).

후보의 판단 이력, 실행 당시 설계자료·규칙·패턴·AI 입력/응답 기록은 연결된 실행 기록에 보관합니다. 후보·시나리오 ID는 실행에 소속되며 재분석 시 이전 ID와의 대응을 유지합니다. 위험도를 제안하는 경우 적용 기준표 버전·심각도·가능성·계산 결과·근거와 가정을 남깁니다. MVP는 임시 기준표(KOSHA P-86-2017 예시, [지침](HAZOP기법지침.md))가 있으므로, 판단 근거가 있으면 `proposed`로 제안합니다(사용자 결정, 2026-11-04). 예시는 판단 근거가 부족해 위험도만 보류한 경우입니다.

### ⑤: 전문가 검토 기록

```json
{
  "schema_version": "0.1",
  "project_id": "project-001",
  "review_id": "review-001",
  "review_version": 1,
  "analysis_run_id": "analysis-001",
  "candidate_id": "deviation-001",
  "review_status": "deferred",
  "review_required": false,
  "risk_confirmation": null,
  "reviewer_id": "reviewer-001",
  "reason": "운전조건과 위험도 평가 기준 확인 필요",
  "action_ids": [],
  "material_request_memos": ["정상 유량과 위험도 기준표 확인"]
}
```

`review_required: false`는 변경에 따른 재검토 표시가 없다는 뜻이며 검토 확정을 뜻하지 않습니다. 실제 저장 시 검토 시각·시나리오별 수정 내용·메모 식별자와 변경 이력을 추가합니다.

검토 결정(`decision` 등)의 규격은 [인터페이스 §5](인터페이스.md#5-검토-확정-데이터-규격)를 따릅니다.

### 변경 알림과 구간 전체 재검토 (후속)

①의 등록 버전 변경은 `material_changed`, ③의 그래프 새 버전 발행은 `graph_changed` 알림으로 기록합니다. 변경 종류(`change_kind`: 원본 교체, 메타데이터 정정, 그래프 편집 등)를 남깁니다. 이 알림은 논리적 데이터이며 메시지 큐 등 특정 구현을 요구하지 않습니다.

```json
{
  "schema_version": "0.1",
  "project_id": "project-001",
  "event_id": "change-001",
  "event_type": "graph_changed",
  "change_kind": "graph_edit",
  "subject": {"graph_id": "graph-001", "from_version": 1, "to_version": 2},
  "changed_entity_ids": ["entity-002"],
  "affected_region_ids": ["region-001"],
  "reason": "V-101의 연결 대상 수정",
  "review_scope": "all_candidates_in_affected_regions"
}
```

`affected_region_ids`는 변경 대상과 원문 참조·구간 소속을 대조해 산정합니다. 해당 구간이 정해지면 **선택·제외·보류를 포함한 구간 전체 편차**에 재검토 표시를 생성합니다(사용자 결정). 구간을 판별할 수 없으면 영향 범위 미확인으로 기록하고 영향 없음으로 처리하지 않습니다.

재검토 표시는 다음 두 경우에만 해소합니다.

- `rereviewed`: 새 버전에서 해당 편차를 다시 검토·확정한 경우
- `no_impact`: 사람이 변경 내용을 확인해 해당 구간에 영향이 없다고 판정하고 판정자·사유·대상 변경을 기록한 경우. 메타데이터 정정처럼 내용이 바뀌지 않은 변경은 구간 단위로 일괄 판정할 수 있습니다(권고 승인, 2026-11-03).

자동 해소는 하지 않으며, 과거 버전 조회나 같은 알림 재처리만으로 표시를 해소하지 않습니다. 이전 확정본은 변경하지 않고 새 버전에 대한 재검토 기록을 덧붙입니다.

### 연쇄 검사

저장된 결과가 이 절의 ID·버전·해시·검증 상태·확인 수준대로 ①→⑤에 이어지는지는 [단계 연쇄 검사](단계연쇄검사.md)(`scripts/check_contract.py`)로 확인합니다(총괄 결정(권고안, 사용자 위임 2026-11-06)).

## 다음 논의

MVP 수직 슬라이스를 구현하기 전에 사용자가 만든 draw.io 샘플 P&ID와 평가 기준을 받아 작성 규칙, 최소 노드·관계 정의, 소규모 원인·결과 패턴을 확정합니다. 실제 사용 화면과 구성의 뼈대는 `디자인/` 폴더에서 별도로 작성합니다.
