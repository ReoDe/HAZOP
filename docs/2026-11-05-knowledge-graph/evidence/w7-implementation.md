# W7 구현 증거 (WP5: 근거 묶음 지식 맥락·kg_version 고정·⑤ 관련 지식)

- 일시: 2026-11-05 20:02, 브랜치 `feat/next-units`, 규격 커밋 `7d62b0d`(기획서/그래프활용.md §6.4·§7.2 C1~C10, W7-1~W7-10 권고안)
- 담당: hazop-developer. 커밋 전(총괄 검토 대기). 편집 범위는 [decisions.md](../decisions.md) D11 안.

## 변경

| 구분 | 경로 | 내용 |
|---|---|---|
| 새 파일 | `hazop/kg/context.py` | `build_context(kg, graph, node_ids)` 순수 함수: 범위(적용 관계 3종 1단계 + `specified_in`, `algo.v4_items` 재사용), 정렬, 크기 상한, 충돌(`conflict_with`·`conflict_outside`), 범위 노드 분류. `content_blockers`는 `algo.check_inputs` 재사용 |
| 지식 빌더(최소) | `hazop/kg/build.py` | `load_outputs_raw`(포인터 한 번 읽기, 바이트·버전 폴더·포인터 반환)와 포인터 필수 키·자료형 검사(`ValueError`). `load_outputs`는 이 함수를 불러 `(knowledge, kg)`만 반환 |
| ④ | `hazop/analysis/run.py` | `inputs.knowledge_graph` 읽기(읽기 실패 `InputError`), 내용 검사·`knowledge_context_too_large`를 `prepare()` blockers로, 근거 묶음 `knowledge_context`·`ev-kg-*`(지정 시에만), 생략 시 `missing_information`·보류, `versions.knowledge_graph`, 사본 `inputs/knowledge_graph.json`, `_check_derived`는 사본으로 `prepare()` |
| ④ | `hazop/analysis/ai.py` | `SYSTEM_PROMPT` 규칙 11, `TEMPLATE_VERSION` "4" |
| ⑤·③ | `hazop/app/runctx.py`·`data.py`·`render.py`·`screens/review.py`·`screens/knowledge.py` | 버전 상태 4가지(`kg_state`), 시나리오별 관련 지식·배지·분류 문구, "관련 지식 (참고)" 접힘 묶음(원안 아래), 버전 칩·경고 띠, "③에서 보기" → `KnowledgeScreen.open_node`(기존 `selectNode`만 사용) |
| 검사 | `scripts/check_kg_context.py`, `tests/test_kg_context.py`, `tests/test_kg_review.py`, `tests/fixtures/kg_context/` | C1~C10. 픽스처: `c1_pre_w7.json`(7d62b0d 코드로 만든 C1 기준값), `responses/deviation-p86-d09.json`(손으로 쓴 C8 (a1)(a2) 응답) |

`bundle_export.py`는 고치지 않았다(manifest `input_files`에 지식그래프가 자동으로 남음, `ExportTest`로 확인). `tokens.py`는 고치지 않았다(기존 `badge` 종류 plain·warn·err·ui, `Chip`, `Banner` 재사용).

## 검증 결과 (전용 venv `%USERPROFILE%\.hazop\venv-py312`, `PYTHONUTF8=1`)

| 항목 | 결과 |
|---|---|
| `python -m unittest discover -s tests` | 1차 541건(건너뜀 11), 재작업 후 552건 OK(건너뜀 14 — 늘어난 3건은 T3 `test_adapter`의 pdfplumber 없음), rc=0 |
| `scripts/check_kg_context.py` | C1~C10 모두 OK(C1 재확인 포함), 단위 테스트 36건 OK, rc=0 |
| `check_kg`·`check_kg_link`·`check_kg_algo`·`check_kg_screen` | 모두 rc=0 |
| `scripts/check_design.py --platform windows` | 재작업 후에도 통과(모든 측정 ≤ 1366×768). 지식그래프 실행은 이 검사가 열지 않으므로 별도 측정: ⑤ d09에서 관련 지식을 모두 펼친 창 최소 폭 1105(일반)·1121(생략 실행), 칩 148px |
| 변이 확인(검사가 실패를 잡는지) | 6건 모두 검출: 항상 키 추가→C1, 템플릿 v3→C9, 항목 상한 해제→C5, 포인터 두 번 읽기→C7, 사실 인용 배지 제거→C10, 내용 검사 제거→C6 |

C1 기준값은 규격 커밋 `7d62b0d`의 `hazop/`를 저장소 밖 임시 폴더에 풀어(`git archive`) 같은 그래프·고정 응답으로 분석한 값이다. 후보 25개 `bundle_sha256`, AI 상태, 집계(후보 44·시나리오 14·위험도 제안 6·설계보완 후보 11·보류 62)가 W7 구현 후와 같다.

## 규격과 다르게 정한 점·해석

1. `truncated.reason`에 `per_item_limits`를 추가했다. C5(d)는 항목 생략 없이 `applies_to`·`specified_in`만 잘려도 `truncated.affected_entity_ids`를 요구하므로 `truncated`가 있어야 하는데, 규격 사유는 `max_items`·`max_bytes` 둘뿐이다. 우선순위는 `max_bytes` > `max_items` > `per_item_limits` > `max_list`(재작업 1회차에 `max_list` 추가).
2. 200개 목록 상한의 "잘림 표시"는 `knowledge_context.truncated_lists`(`{목록 이름: 전체 수}`, 없으면 `{}`)로 둔다(C5(g)). 규격 구조에 이름이 없던 필드다.
3. 크기 상한은 "문구 하나만으로 상한을 넘는 항목"을 먼저 빼고, 그 뒤 정렬 뒤쪽부터 하나씩 뺀다(규격 두 문장을 함께 만족시키는 순서).
4. `affected_entity_ids`는 문자열 오름차순. `specified_in`만 잘린 경우 영향 노드는 없다(인용은 노드에 걸리지 않음).
5. ⑤ 화면 배치·배지 색은 디자인 담당 확인 전이다(기존 토큰·스타일만 재사용). (재작업 1회차: 잠긴 실행에서도 관련 지식 펼치기·③ 이동이 되도록 바꿈 — 해석 철회)
6. 지식그래프 실행의 Excel "입력 파일" 목록에는 `knowledge_graph` 행이 생긴다(`worksheet.py`는 그대로, `input_files`를 그대로 나열).
7. 기존 검사 `check_kg`·`check_kg_algo`는 원래 동작대로 `출력/지식그래프/`에 쓴다(같은 kg_version이라 내용 변화 없음). W7 검사·테스트는 임시 폴더만 쓴다.

## 재작업 1회차 (2026-11-05 21:08, Claude·Codex 조건부 승인 지적 반영)

| # | 지적 | 반영 위치 |
|---|---|---|
| 1 | 목록만 잘린 경우도 생략 경고·보류·⑤ 표시 | `context.py` `build_context`(`max_list` 사유, `reasons`, 잘린 노드를 `affected_entity_ids`에), C5(g)·C10·`ReworkTest.test_list_only_truncation_recorded` |
| 2 | CRLF 사본 resume | `run.py` `resume`(바이트로 해시 후 디코드), `ReworkTest.test_crlf_copy_resume` |
| 3 | 구조가 틀린 지식그래프 | `build.py` `load_outputs_raw`(최상위 객체 아님 → `ValueError` → `InputError`), `context.structure_problems`·`content_blockers`(구조 오류 → blockers), C6 (A)(B) 사례·`test_structure_errors` |
| 4 | C9 병합 뒤 보류 유지 | `tests/fixtures/kg_context/responses_c9/`(C9 묶음 해시 응답), C9가 validated 확인 후 AI 병합·마무리 뒤 구간 입력 보류 목록이 병합 전과 같은지 대조 |
| 5 | ③ 웹 선택 상태·이전 버전 이동 | `test_kg_review.py` `web_state`(웹 `hzKG.state()`의 `sel`·`kg_version`), `test_3_blocked_latest_goes_to_previous_passed`(`showing_prev`) |
| 6 | 고정 응답의 근거 없는 빈도 감소·가설 원인 | `responses/deviation-p86-d09.json`: 시나리오 1·2의 `frequency_with_safeguards`·인정 보호수단 제거(근거 없음 명시), AI 추가 가설 원인을 RC-PT110 지시 오차로 정리 |
| 7 | 잠긴 실행에서 관련 지식·③ 이동 | `review.py` `ScenarioForm.set_editable`(검토 입력만 끔), `_candidate_changed`, `test_locked_run_still_shows_knowledge` |
| 8 | 사유별 생략 문구 | `context.omission_texts`, `data.related_knowledge`(`truncated_text`) |
| 9 | 항목 0개 문구 | `render.related_knowledge_html` |
| 10 | 줄 이음 | `knowledge.py` `open_node` |
| 11 | 그래프 차단 중복 | `context.content_blockers`(P&ID 검증 상태는 prepare만 보고), `test_blocked_graph_reported_once` |
| 12 | out_of_scope·analyzed_in만 있는 노드 | `ClassificationTest` |

추가 해석: `truncated.reasons`(해당 사유 전부)와 `max_list` 사유를 새로 두었다(`reason`은 가장 앞선 사유, 우선순위 max_bytes > max_items > per_item_limits > max_list). missing_information 문구는 사유별로 `항목 N개 중 M개만 포함(max_items)` / `항목은 모두 포함, 적용 설비·인용 연결 일부 생략(per_item_limits)` / `범위 노드 분류 목록 일부 생략(max_list)`.

## 재작업 2회차 (2026-11-05 21:18, Codex 반려 3건)

| # | 지적 | 반영 위치 |
|---|---|---|
| 1 | 중첩 구조 오류가 예외로 샘 | `context.py` `structure_problems`·`_node_problem`·`_link_problem`(source·compute_view.v4·excluded_reasons·node_type·ends.from/to·layer·ref 자료형, V4 밖 행은 id·kind 빈 값 허용), `run.py` `prepare`의 `build_context` 호출을 KeyError·TypeError·AttributeError → 같은 blockers로 바꾸는 방어선. `NestedStructureTest`(5사례 × 구조 검사·방어선 각각) |
| 2 | 고정 응답의 "POSRV가 정상 작동하면 … 희박" 문장 | `responses/`·`responses_c9/` `deviation-p86-d09.json`에서 삭제. 응답 해시(`bundle_sha256`)는 묶음 기준이라 그대로이고 C8·C9 validated 유지 |
| 3 | 항목도 잘렸을 때 "항목은 모두 포함" 문구 | `context.omission_texts`: `omitted_count > 0`이면 `적용 설비·인용 연결 일부 생략(per_item_limits)`만. `OmissionTextTest`(항목 41개 + 연결 21개) |

검증: 전체 unittest 556건 OK(건너뜀 14, rc=0), check_kg_context C1~C10 OK·단위 테스트 40건(rc=0), check_kg·link·algo·screen rc=0.
