# 문서 상태 제안표 (specs 20개 + flows 6개 + design 4개 = 30개)

작성 2026-11-12. 제안만 한다. 문서 머리는 고치지 않았고 `approved`로 바꾸는 일은 총괄 몫이다.
상태 값의 뜻은 `governance/naming-rules/README.md` §4.7을 따른다.

## 요약

| 제안 상태 | 개수 | 문서 |
| --- | --- | --- |
| `approved` 후보 | 11 | PLN-01, 03, 07, 08, 10, 11, 12, 16, FLW-00, 01, 03 |
| `review` | 18 | PLN-02, 04, 05, 06, 09, 13, 14, 15, 17, 18, 19, 20, FLW-02, 04, 05, DSN-02, 03, 04 |
| `draft` | 1 | DSN-01 |
| `obsolete` 후보 | 0 | — |
| 합계 | 30 | |

## 조사 기준과 한계

- 본 것: 각 문서의 머리, 목차, 결정·미결 절, 핵심 표. 문서 전체를 줄 단위로 대조하지는 않았다.
- 대조한 것: `hazop/` 모듈 존재, `tests/` 시험 이름, `scripts/check_*.py`, `records/decision-log.md` DEC 번호, 문서 마지막 수정일(`git log -1`).
- 코드를 실행해 확인하지 않았다. "구현됨"은 모듈·시험 파일이 있다는 뜻이다.
- 어긋난 곳은 절 번호나 행 번호를 적었지만, 같은 취지의 문장이 더 있을 수 있다.
- 확신은 높음/보통/낮음으로 적었다. 낮음은 총괄이 직접 열어 볼 것을 권한다.
- `review`가 많은 까닭은 "구현 전"·"미확정"·"후속" 같은 머리 문구가 그 뒤의 구현으로 낡았기 때문이다. 내용 자체는 대체로 맞다.
- `obsolete` 후보는 찾지 못했다. 다른 문서로 완전히 대체된 문서는 없었다.

## specs/ (20개)

| 문서번호 | 경로 | 한 줄 요약 | 제안 | 이유 | 확신 |
| --- | --- | --- | --- | --- | --- |
| HZ-PLN-01 | `specs/overview.md` | 전체 기획: 목적, 공통 원칙, 단계 간 데이터 규격, MVP 범위 | approved 후보 | 11-11 DEC-0256에서 범위 문구를 초기사건 인계까지 맞춤. 데이터 규격 표(`selection_status`·`review_status` 등)가 `hazop/contract/chain.py`·`hazop/analysis`와 대응. 50행 "모두 초안" 문구는 승인 때 한 줄 손봐야 함 | 보통 |
| HZ-PLN-02 | `specs/integration.md` | 정보 통합·관리: 통합 그래프, 노드 단위, 검증·통과 기준 | review | 본문은 `hazop/graph/`·`hazop/kg/`와 맞음. 단 "다음에 결정할 내용"(159행)이 "사용자 draw.io 샘플에 맞춰 MVP 노드·관계 확정"으로 남아 낡음. 최종 수정 11-10 | 보통 |
| HZ-PLN-03 | `specs/registration.md` | 자료 등록: 파일 검증, 해시, ID, 등록 버전 | approved 후보 | 11-11 수정. 등록 절차가 draw.io와 벡터 PDF를 모두 다루며 `hazop/register/registry.py`·`tests/test_register*.py`와 대응. 도면번호 충돌 판정은 "후속"으로 명시돼 어긋남 아님 | 보통 |
| HZ-PLN-04 | `specs/extraction.md` | 정보 추출: draw.io 1차 추출, 체크밸브 방향(A1), 포트(A2) | review | 결정 상태 표는 "draw.io 1차, PDF 2차" 틀인데 PDF 추출(`hazop/extract/adapters/pdf_vector.py`)과 F1 단위(DEC-0269~0289)가 구현됨. "다른 자료형 (후속)"(303행)과 체크밸브 적용 범위의 "PDF는 후속"이 낡았을 가능성 | 낮음 |
| HZ-PLN-05 | `specs/hazop-analysis.md` | HAZOP 분석: 편차 후보, 원인·결과, 위험도 제안, AI 역할 | review | 결정 표 "AI 모델" 행이 "① API ② 팀 구독 ③ 로컬 LLM" 순서인데 DEC-0266(2026-11-11)이 구독 기본으로 바꿈. 구간 분할·스크리닝(`study-node-segmentation`)도 반영 안 됨 | 높음 |
| HZ-PLN-06 | `specs/review-results.md` | 검토·결과 관리: Excel 출력, 평가 기준 비교, 편차별 확정 | review | "MVP와 후속 범위"(30~35행)가 "검토 화면·편차별 확정·이력은 후속"인데 ⑤ 화면(`hazop/app/screens/results.py`, `hazop/review/`)이 이미 구현됨. 28행 "구현 전 조정할 수 있습니다"도 낡음 | 높음 |
| HZ-PLN-07 | `specs/hazop-method-guide.md` | KOSHA P-86-2017 요약·구조화(가이드워드, 위험도 표) | approved 후보 | 기준 자료 요약이라 "쓰였는가"로 봄. `hazop/analysis/catalog_md.py`·`risk.py`가 이 표를 씀. §5.2 표 사이 불일치는 "판정 보류"로 원문 그대로 둔 것이라 결함 아님 | 보통 |
| HZ-PLN-08 | `specs/graph-survey.md` | Obsidian식 화면과 그래프 알고리즘 조사(2026-11-05) | approved 후보 | 조사 문서. 결론이 `graph-usage.md` D8(force-graph 채택)과 `hazop/kg/screen.py`로 이어짐 | 보통 |
| HZ-PLN-09 | `specs/graph-usage.md` | 그래프 활용: 알고리즘 A1~A11, 지식그래프 화면, WP0~WP6 | review | 머리가 "구상 단계, 구현을 의미하지 않음"인데 `hazop/kg/{algo,build,link,context}.py`와 ③ 화면이 구현됨(`tests/test_kg*.py`). §8.2 D1~D9는 채택 완료, WP6(A6~A11)는 후속 | 높음 |
| HZ-PLN-10 | `specs/interface.md` | 데스크톱 인터페이스: 화면·메뉴·저장 위치·완료 기준 | approved 후보 | 가장 최근(11-12) 수정, 메뉴 배치를 단위 H-a(DEC-0282)에 맞춤. §9 "남은 미결정 사항 없음". 화면 구성이 `hazop/app/main_window.py`·`screens/`와 대응 | 보통 |
| HZ-PLN-11 | `specs/stage-chain-check.md` | 단계 연쇄 검사 K1~K6, V 시험 | approved 후보 | `hazop/contract/chain.py`·`scripts/check_contract.py`·`tests/test_contract.py`가 대응. §7 미확정 3건은 처리 방침이 정해진 후속 | 보통 |
| HZ-PLN-12 | `specs/criteria-comparison.md` | 평가 기준 비교 기획: 대응 규칙, 지표, E1~E15 시험 | approved 후보 | `hazop/evaluate/`·`scripts/compare_criteria.py`·`tests/test_evaluate.py` 구현(DEC-0114). §8 미확정 5건은 사용자 기준 수령 대기(backlog "사용자 제공 대기")라 설계 결함이 아닌 외부 입력 대기 | 낮음 |
| HZ-PLN-13 | `specs/kg-schema.md` | 지식그래프 스키마 설계안(타입 레지스트리, 단계 M0~M6) | review | U1~U10 채택, M0~M5 구현(`hazop/kg/schema/registry.json`, `tests/test_kg_schema.py`). M6은 실제 표본 문서 대기. 제목의 "설계안" 표현이 현재와 안 맞음 | 보통 |
| HZ-PLN-14 | `specs/kg-schema-dictionary.md` | 스키마 부속 1: 노드·관계 사전 | review | 제목이 "(미확정)"인데 본문이 U1~U10 채택 뒤 구현됨. 제목·머리 문구만 낡았을 가능성이 큼. 사전과 `registry.json` 일치는 대조하지 않음 | 낮음 |
| HZ-PLN-15 | `specs/kg-schema-input.md` | 스키마 부속 2: 입력 문서·잠재 후보·추출 갭 | review | 제목이 "(미확정)". 갭 처리 단계(§3.2)가 구현됐는지 항목별 대조 못 함 | 낮음 |
| HZ-PLN-16 | `specs/ie-hazop-survey.md` | HAZOP 결과로 원전 초기사건(IE)을 도출하는 방법 조사 | approved 후보 | 조사 문서. DEC-0187·0188이 이 조사를 근거로 최종 목표와 D1~D7을 정했고 `ie-output-design.md`로 이어짐. §10 결정 항목도 처리됨 | 높음 |
| HZ-PLN-17 | `specs/ie-output-design.md` | 초기사건 출력 설계 E1~E10, 시트, 단계별 구현 | review | `hazop/ie/`·`screens/initiating.py`·`tests/test_ie_*.py` 구현(DEC-0188, 0257~0261). 단 E9(안전기능 값 출처) 보류, P5(FMEA 입력)는 §8.1에 초안과 질문 8개만 있고 미구현(DEC-0260) | 높음 |
| HZ-PLN-18 | `specs/ai-subscription.md` | AI 연결: Claude Code 구독제 기술 설계 U1~U12, P1~P4 | review | 머리가 "구현 전"인데 `hazop/study/{claude_cli,providers}.py`, `hazop/app/{ai_conn,ai_runner}.py`, `tests/test_claude_cli.py`·`test_ai_connection_ui.py`가 있고 DEC-0266(결정)·0278(실측)이 있음. P1~P4 완료 범위와 DEC-0278 실측 반영 여부는 확인 못 함 | 보통 |
| HZ-PLN-19 | `specs/pid-symbol-dictionary.md` | P&ID 기호 사전 기획: 형식, 위치, 새 kind, 검정 밸브 | review | D1~D14 채택, `resources/library/symbols/` 구현. 단 366행 "검게 칠한 플러그·다이어프램·볼 밸브는 사전 항목이 없어 그대로"가 DEC-0285(플러그 밸브 견본 추가, 11-12)와 어긋남. 문서 수정은 11-11 | 높음 |
| HZ-PLN-20 | `specs/study-node-segmentation.md` | 검토구간 분할 설계: C6 분할, 스크리닝 R0~R4, 성능 | review | 머리가 "설계 확정, 구현 전"인데 본문에 S1~S5 구현 기록이 있고 `hazop/study/{nodes,remap,span}.py`가 있음. §4.5 '낮음 빼기' 선택과 S4의 탐색기 접기가 남음. S6(AI 구간 검토)는 DEC-0262·0263으로 구현 쪽 | 높음 |

## specs/flows/ (6개)

가장 늦게 수정된 것이 FLW-00(11-11)이고 나머지는 11-10이다. 흐름도 본문은 열어 대조하지 않고 짝 기획서와 키워드(구독·스크리닝·⑥ 등)로만 봤다.

| 문서번호 | 경로 | 한 줄 요약 | 제안 | 이유 | 확신 |
| --- | --- | --- | --- | --- | --- |
| HZ-FLW-00 | `specs/flows/00-overview.md` | 최상위 단계 흐름과 되돌림 경로 | approved 후보 | 11-11에 초기사건 인계(⑥)를 반영(`⑥` 표기 3곳) | 보통 |
| HZ-FLW-01 | `specs/flows/01-registration.md` | 자료 등록 상세 흐름 | approved 후보 | `registration.md`(approved 후보)와 짝. PDF 언급은 없으나 흐름이 확장자와 무관한 검증이라 어긋나지 않음 | 낮음 |
| HZ-FLW-02 | `specs/flows/02-extraction.md` | 정보 추출 상세 흐름 | review | 짝 `extraction.md`가 review. 흐름도에 PDF 추출·보정 경로(F1 단위)가 없을 가능성(PDF 언급 0건) | 낮음 |
| HZ-FLW-03 | `specs/flows/03-integration.md` | 정보 통합·관리 상세 흐름 | approved 후보 | 짝 `integration.md` 본문(통과·보류 기준)과 맞음. 짝이 review라 함께 재판정 필요 | 낮음 |
| HZ-FLW-04 | `specs/flows/04-hazop-analysis.md` | ④ HAZOP 분석 상세 흐름 | review | 구간 분할·스크리닝·AI 구간 검토와 구독 연결이 흐름에 없음(관련 키워드 1건뿐) | 보통 |
| HZ-FLW-05 | `specs/flows/05-review-results.md` | ⑤ 검토·결과 관리 상세 흐름 | review | 짝 `review-results.md`가 review. 흐름도는 편차별 확정·재검토 표시까지 그려 구현과 가깝지만 초기사건 열(⑥ 인계)이 없음(`⑥` 0건) | 낮음 |

## design/ (4개)

| 문서번호 | 경로 | 한 줄 요약 | 제안 | 이유 | 확신 |
| --- | --- | --- | --- | --- | --- |
| HZ-DSN-01 | `design/output-screen-ax-demo.md` | 외부 '출력화면 AX' 데모 분석(참고용) | draft | 분석 문서이고 §5 미결정 3건 중 "디자인 토큰의 실제 값"이 열려 있음(나머지 둘은 `screen-spec.md` §10으로 정해짐). 참조 자료라 `obsolete`로 두는 안도 가능하나 DEC-0036이 아직 근거로 씀 | 낮음 |
| HZ-DSN-02 | `design/kg-screen.md` | ③ 지식그래프 화면의 시각 규칙·배치 | review | `hazop/app/screens/knowledge.py`·`hazop/kg/screen_template.html` 구현. 단 §10 "구현 전에 직접 확인할 것" 5건(대비 측정, Canvas 그리기, 1366×768 칩 줄, 힘 기본값 등)이 확인됐다는 기록을 못 찾음 | 보통 |
| HZ-DSN-03 | `design/screen-spec.md` | 현재 화면 명세 ①~⑤ | review | 가장 최근(11-12) 수정이나 제목이 "①~⑤"이고 본문에 `⑥`이 0건. ⑥ 초기사건 화면(`screens/initiating.py`)이 빠졌을 가능성 | 보통 |
| HZ-DSN-04 | `design/ai-connection-screens.md` | AI 연결 화면 설계(API 키와 구독) | review | D1~D6 결정 완료, `hazop/app/{ai_conn,conn_view,conn_widgets}.py`·`settings_dialog.py` 구현. 11-10 수정이라 DEC-0278 실측과 단위 H(DEC-0279~0282) 반영 여부 불명 | 낮음 |

## 판단이 어려웠던 문서

1. **HZ-PLN-12 criteria-comparison**: 구현은 있으나 §8 미확정 5건이 남음. 사용자 평가 기준이 오기 전이라 `approved`로 올리면 "기준 확정"으로 읽힐 수 있음. `review`로 낮추는 선택도 타당함.
2. **HZ-PLN-14·15 스키마 부속**: 제목에 "(미확정)"이 있고 본문과 코드 대조를 못 함. 본문이 결정을 반영했는지 열어 봐야 정함.
3. **HZ-DSN-01 AX 데모 분석**: 구현 대상이 아닌 참조 자료라 상태 기준이 맞지 않음. `draft`는 임시 제안이며 "참조 자료" 분류가 필요하면 총괄이 정함.
4. **HZ-FLW-01·03·05**: 흐름도 본문을 열지 않고 짝 기획서와 키워드로만 봄. 확신 낮음.
5. **`approved` 후보 전반**: "승인해도 되는 후보"일 뿐이다. 승인 전에 총괄이 문서를 한 번 훑어야 하고, 특히 HZ-PLN-01 50행의 "모두 초안" 문구는 고쳐야 한다.

## 본문에서 눈에 띈 낡은 문구 (고치지 않음)

- `specs/overview.md` 50행: "모든 기획서·플로우차트는 초안이며 구현 완료를 의미하지 않습니다."
- `specs/review-results.md` 28행, 30~35행: 검토 화면을 후속으로 적음.
- `specs/hazop-analysis.md` 결정 표 "AI 모델" 행: 연결 우선순위가 DEC-0266 이전 순서.
- `specs/pid-symbol-dictionary.md` 366행: 플러그 밸브 사전 항목 없음(DEC-0285 이후 사실과 다름).
- `specs/ai-subscription.md` 12행, `specs/study-node-segmentation.md` 14행: "구현 전".
- `specs/kg-schema-dictionary.md`·`kg-schema-input.md` 제목: "(미확정)".
