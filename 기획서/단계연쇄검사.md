# 단계 연쇄 검사 기획

[단계 간 데이터 규격](전체기획.md#data-contract) · [MVP와 후속 범위](전체기획.md#mvp) · [공통 원칙](전체기획.md#principles)

## 1. 목적과 범위

①등록 → ②추출 → ③그래프 → ④분석 → ⑤검토·출력의 저장 결과를 읽어, ID·버전·해시·검증 상태·확인 수준이 [데이터 규격](전체기획.md#data-contract)대로 이어지는지 확인하는 검사 스크립트 `scripts/check_contract.py`를 정의합니다.

이 문서의 결정은 모두 **총괄 결정(권고안, 사용자 위임 2026-11-06)**입니다.

| 범위 | 내용 |
| --- | --- |
| 포함 | 저장된 결과 파일 사이의 참조·버전·해시·상태 연속성 검사. 읽기 전용 |
| 제외 | 각 단계 내부의 형식·내용 검사(기존 `check_register`·`check_extract`·`check_graph`·`check_analysis`·`check_review`·`check_export`의 몫), 결과 재생성, 자동 수정 |

기존 검사는 단계마다 "그 단계가 바르게 만들었는가"를 봅니다. 이 검사는 "다음 단계가 앞 단계의 바로 그 버전을 가리키는가, 그리고 미확인·가설이 확정으로 바뀌지 않고 전달됐는가"만 봅니다. 단계 내부 검사를 다시 하지 않습니다.

## 2. 입력 (읽기 전용)

검사는 아래 파일을 읽기만 합니다. 어떤 파일도 만들거나 고치지 않습니다(`--report`로 지정한 보고 파일만 예외).

| 단계 | 파일 | 위치 |
| --- | --- | --- |
| ① | 등록 색인, 등록 스냅샷, 저장 원본 | `<저장 루트>/<project_id>/registry.json`, `<저장 루트>/<project_id>/registrations/<material_id>/<registration_version>.json`, 스냅샷의 `storage_ref`(프로젝트 폴더 `<저장 루트>/<project_id>/` 기준 상대 경로, `hazop/register/registry.py` `Store.abs_ref`) |
| ② | 추출 결과 | 분석 실행의 `source.extraction_file`(샘플 경로는 `<작업 루트>/출력/추출/<도면번호>/extraction.json`, 등록 경로는 `출력/samples/추출/…` 등 그 파일 위치) |
| ③ | 그래프, 대상 매핑 | `graph.json`, `entity_mapping.json`. 폴더는 실행 사본 그래프의 `source.extraction_file`(추출 결과)의 형제 `…/그래프/<추출 폴더 이름>/`, 없으면 `<작업 루트>/출력/그래프/<추출 폴더 이름>/` |
| ④ | 구간 JSON, 분석 실행 | `<작업 루트>/데이터/구간/<region_id>.json`, `<작업 루트>/출력/분석/<region_id>/<analysis_run_id>/analysis.json`, 같은 폴더 `inputs/*.json` |
| ⑤ | 검토본, 출력 기록, 워크시트 | `<저장 루트>/reviews/<region_id>/<analysis_run_id>/<candidate_id>/v<n>.json`, 같은 실행의 `exports/<시각>.json`, 출력 기록의 `file`(작업 루트 기준). 실행 폴더 아래의 `exports` 폴더는 후보 폴더로 보지 않음(`hazop/review/store.py` `load_run_reviews`와 같은 규칙) |
| (선택) | 평가 비교 보고 | `<작업 루트>/출력/평가비교/<region_id>/<analysis_run_id>/*.json`([평가 기준 비교 §5.1](평가기준비교.md#51-비교-보고-json)) |

작업 루트·저장 루트는 `hazop.paths.work_root()`·`store_root()`를 따릅니다.

### 2.1 연쇄 찾기

검사 대상은 분석 실행에서 거꾸로 찾습니다.

1. 분석 실행 폴더 → `inputs/region.json`(실행 당시 구간 사본), `inputs/graph.json`(실행 당시 그래프 사본)
2. 그래프 사본의 `source.extraction_file` → 현재 추출 결과
3. 추출 결과의 `project_id`·`source.material_id`·`registration_version` → 등록 스냅샷(`<저장 루트>/<project_id>/registrations/…`)
4. 분석 실행의 `region_ref.region_id`·`analysis_run_id` → 검토본 폴더와 출력 기록

### 2.2 경로 구분: 등록 경로와 샘플 경로

현재 `출력/`의 결과는 등록 없이 만든 **샘플 경로**입니다(`project_id: null`, `source.material_id: null`, 구간의 `graph_ref.graph_source: "samples"`). 등록 경로(`scripts/run_samples.py`. `출력/samples/{추출,그래프,뷰어}`에 씀)는 `project_id`와 `material_id`가 채워집니다.

| 경로 | 판정 | ① 관련 검사 |
| --- | --- | --- |
| 등록 경로 | 그래프의 `project_id`가 있음(`hazop.analysis.run.graph_source_of`와 같은 기준) | 모두 수행 |
| 샘플 경로 | 그래프의 `project_id`가 `null` | ① 연결 검사는 `SKIP`(사유: 샘플 경로). 대신 "등록 미연동이 미확인으로 기록됐는지"(K1)를 검사 |

### 2.3 실행 형태

```
python scripts/check_contract.py [--region <region_id>] [--run latest|all|<analysis_run_id>]
                                 [--work-root <폴더>] [--store-root <폴더>] [--report <JSON 경로>]
```

| 옵션 | 기본값 | 의미 |
| --- | --- | --- |
| `--region` | `데이터/구간/*.json` 전체 | 검사할 구간 |
| `--run` | `latest` | `latest`는 `analysis.json`이 있는 실행 폴더 중 최신(폴더 이름의 시각 순), `all`은 `analysis.json`이 있는 실행 폴더 전부. `analysis.json`이 없는 미완성 폴더는 두 경우 모두 건너뛰고 보고의 `notes`에 남김. `<analysis_run_id>`로 지정한 실행에 `analysis.json`이 없으면 실행 오류(종료 코드 2) |
| `--store-root` | `HAZOP_STORE_ROOT`, 없으면 `<작업 루트>/자료저장소` | 저장 루트 |
| `--report` | 없음 | 결과 JSON을 쓸 경로. 경로는 realpath 기준으로 판정하며, `<작업 루트>/출력`·`<작업 루트>/데이터`·저장 루트 밖이어야 함(상위 폴더는 samefile로 비교). 드라이브 표시(`C:` 등) 뒤에 `:`가 있는 경로, 경로에 링크·정션이 있는 경우, 이미 있는 파일(덮어쓰기)은 거부. 거부하면 종료 코드 2 |

종료 코드: `0` = `FAIL` 없음, `1` = `FAIL` 1개 이상, `2` = 실행 오류 1개 이상. 실행 오류가 있으면 `FAIL`이 함께 있어도 `2`입니다. 실행 오류는 JSON 읽기 실패, JSON이 객체가 아님, 파일 접근 실패(`OSError`), 입력 형식 오류(경로·이름 `ValueError`), 입력 폴더 없음, 지정한 구간·실행 없음, 지정한 실행의 `analysis.json` 없음, 보고 경로 거부, 보고 파일 쓰기 실패입니다. 참조한 파일이 없는 것은 실행 오류가 아니라 해당 항목의 `FAIL`이며, 다른 연쇄의 검사는 계속합니다. 네트워크·AI 호출이 없습니다.

## 3. 판정 등급

| 등급 | 뜻 | 종료 코드 영향 |
| --- | --- | --- |
| `PASS` | 규격대로 이어짐 | 없음 |
| `FAIL` | 규격 위반. 참조가 다른 버전·다른 파일을 가리키거나, 미확인·가설이 확정으로 바뀜 | 1 |
| `WARN` | 위반은 아니나 확인 필요. 예: 실행 이후 현재 그래프가 새 버전으로 바뀜(실행은 당시 버전을 고정하므로 정상) | 없음 |
| `SKIP` | 해당 없음. 반드시 사유를 씀(예: 샘플 경로, 검토본 없음) | 없음 |

`SKIP`을 `PASS`로 세지 않습니다. 요약 줄에 등급별 개수를 따로 표시합니다.

## 4. 검사 항목

메시지 형식: `[등급] <ID> <대상>: <내용> (기대 <값>, 실제 <값>)`. 해시는 앞 12자리만 표시합니다. `PASS`는 항목마다 1줄, `FAIL`·`WARN`은 대상마다 1줄입니다. R1의 대상 이름은 추출 폴더 이름입니다.

버전 값(등록·구간·검토 버전 등)은 ASCII 정수 또는 숫자 문자열을 정수로 정규화해 비교합니다. 정수로 바꿀 수 없으면 해당 항목 `FAIL`입니다.

### 4.1 공통

| ID | 검사 | 근거 | 실패 메시지 예 |
| --- | --- | --- | --- |
| G1 | 등록 스냅샷·추출·그래프·분석·검토본·출력 기록에 `schema_version`이 있고 `"0.1"` | [식별자와 버전](전체기획.md#식별자와-버전) | `[FAIL] G1 extraction SNP-M-102: schema_version 없음` |
| G2 | 대상 파일의 `project_id`가 모두 같음. 대상: 등록 스냅샷(등록 경로만), 현재 추출, 현재 그래프, 실행 사본 `inputs/graph.json`·`inputs/region.json`, `analysis.json`, 검토본 전체. 샘플 경로는 모든 대상 파일의 `project_id`가 `null`이어야 함. 출력 기록은 `project_id` 필드가 없으므로(`hazop/export/worksheet.py` `export_worksheet`의 기록) 대상에서 빼고, E1의 `analysis_run_id`·`analysis_sha256` 대조로 연결을 확인 | 같은 절 | `[FAIL] G2 analysis-…: project_id 불일치 (그래프 'p-A', 분석 'p-B')` |

### 4.2 ① → ② (등록 경로만)

| ID | 검사 | 근거 | 실패 메시지 예 |
| --- | --- | --- | --- |
| R1 | 추출 `source.(material_id, registration_version)`의 등록 스냅샷 파일이 있음 | [① → ②](전체기획.md#data-contract) | `[FAIL] R1 extraction SNP-M-102: 등록 스냅샷 없음 material-003 v2` |
| R2 | 스냅샷 `status: registered`, `validation.status: passed` | 같은 절 | `[FAIL] R2 material-003 v2: 등록 미완료 (status 'on_hold')` |
| R3 | 추출 `source.sha256` = 스냅샷 `sha256` = 저장 원본(`storage_ref`) 파일의 SHA-256 | 같은 절 "파일 해시는 등록정보에 보관" | `[FAIL] R3 material-003 v2: 원본 해시 불일치 (등록 7f4c87c61f8b, 추출 0a1b2c3d4e5f)` |
| R4 | 스냅샷이 해당 자료의 최신 등록 버전이 아니면 알림. 최신 = `registry.json`의 `versions`와 스냅샷 파일 번호 가운데 최댓값(등록 상태 무관) | [이력과 버전](전체기획.md#이력과-버전) "조용히 교체하지 않음" | `[WARN] R4 material-003: 추출은 v2, 최신 등록은 v3` |

샘플 경로이면 R1–R4는 `SKIP 샘플 경로(등록 미연동)`입니다. R1이 `FAIL`이면 R2–R4는 `SKIP`(사유: 등록 스냅샷 없음)입니다(총괄 직접 수정, 최종 재검토 반영).

### 4.3 ② → ③

현재 산출물(`출력/추출/`·`출력/그래프/`)끼리 비교합니다. 실행 당시 사본과의 비교는 4.4에서 합니다.

| ID | 검사 | 근거 | 실패 메시지 예 |
| --- | --- | --- | --- |
| X1 | 그래프 `input_runs`에 추출 `extraction_run_id`가 있고, 그래프 `source.extraction_run_id`와 같음 | [③ → ④](전체기획.md#data-contract) | `[FAIL] X1 graph-SNP-M-102: 추출 실행 ID 불일치` |
| X2 | 현재 추출 결과로 다시 계산한 그래프 버전(`hazop.graph.build._graph_version`)이 그래프 `graph_version`과 같음. 빌더 버전이 바뀌어 다른 경우도 `FAIL`로 둠(엄격). 이때 메시지에 '빌더 버전 변경 — 재생성 필요'와, 그래프에 기록된 빌더 버전으로 다시 계산했을 때 추출이 바뀌었는지를 함께 씀 | 같은 절 "입력이 바뀌면 바뀜" | `[FAIL] X2 graph-SNP-M-102: 추출 결과가 그래프 생성 뒤 바뀜 (기록 v-7ed95b0c74f1, 재계산 v-…)` |
| X3 | `graph.json`의 `entity_mapping` 기준: 추출의 모든 노드·관계 `local_id`가 정확히 한 번 있고, 매핑의 모든 `(extraction_run_id, local_id)`가 추출에 있음. 예외: 그래프 `validation.unknowns`에 `unknown_relation_kind`(target = L)가 정확히 1건 있고 추출 관계 L의 `kind`가 알려진 종류가 아닐 때만 L을 매핑 의무에서 뺌 | 같은 절 "원본·임시 ID 대응을 유지" | `[FAIL] X3 graph-SNP-M-102: 매핑 없는 local_id local-edge-014` |
| X4 | `entity_mapping.json`의 `project_id`·`graph_id`·`graph_version`·`input_runs`가 그래프와 같고, `entity_mapping[]`의 `(extraction_run_id, local_id, entity_id)` 목록이 그래프 `entity_mapping`의 목록과 같음. 파일의 추가 필드(`source_object_id`·`material_id`·`registration_version`, `hazop/graph/build.py` `entity_mapping_document`)는 비교하지 않음 | 같은 절 | `[FAIL] X4 graph-SNP-M-102: entity_mapping.json의 (extraction_run_id, local_id, entity_id) 목록이 graph.json과 다름` |
| X5 | 그래프 `validation.status: passed`(④가 정상 입력으로 쓰려면 필요) | [상태는 역할별로 구분](전체기획.md#상태는-역할별로-구분) | `[FAIL] X5 graph-SNP-M-102: validation.status 'blocked'` |

### 4.4 ③ → ④ (실행 사본 기준)

| ID | 검사 | 근거 | 실패 메시지 예 |
| --- | --- | --- | --- |
| A1 | 실행 폴더 이름 = `analysis_run_id`, 상위 폴더 이름 = `region_ref.region_id` | [④ → ⑤](전체기획.md#data-contract) | `[FAIL] A1 …: 폴더 이름과 analysis_run_id 다름` |
| A2 | `analysis_run.input_files[]`의 각 `sha256` = `inputs/<role>.json` 파일 바이트의 SHA-256(기록 해시는 텍스트로 읽은 내용의 UTF-8 해시이고 사본은 그 텍스트를 그대로 쓴 것이므로 같아야 함, `hazop/analysis/run.py` `load_inputs`·`save`) | [신뢰 경계](전체기획.md#trust-boundary) "입력 사본의 해시 기록" | `[FAIL] A2 …: inputs/graph.json 해시 불일치` |
| A3 | `analysis.graph_ref` = 사본 그래프의 `(graph_id, graph_version)` = 사본 구간의 `graph_ref.(graph_id, graph_version)` | [③ → ④](전체기획.md#data-contract) | `[FAIL] A3 …: graph_ref 불일치 (분석 v-…, 사본 그래프 v-…)` |
| A4 | `analysis.region_ref` = 사본 구간의 `(region_id, region_version)` | [식별자와 버전](전체기획.md#식별자와-버전) | `[FAIL] A4 …: region_version 불일치 (분석 1, 사본 2)` |
| A5 | 시나리오 `graph_evidence.node_ids`·`relation_ids`·`cause_equipment`, 보호수단 `node_id`가 사본 그래프에 있고, 보호수단 `tag`가 그래프 노드 `tag`와 같음 | [④ → ⑤](전체기획.md#data-contract) | `[FAIL] A5 scenario-p86-d09-01: 그래프에 없는 노드 entity-node-099` |
| A6 | 시나리오 `source_locations[]`의 `graph_id`·`graph_version`·`extraction_run_id`가 사본 그래프와 같고, `(extraction_run_id, local_id)`가 사본 그래프 매핑에 있음 | [② → ③](전체기획.md#data-contract) | `[FAIL] A6 scenario-…: source_locations의 graph_version이 실행 그래프와 다름` |
| A7 | 현재 그래프(§2 ③ 위치)와 사본 그래프의 `graph_version` 비교. 현재 그래프 파일이 없어도 `WARN` | [이력과 버전](전체기획.md#이력과-버전) | `[WARN] A7 …: 현재 그래프 v-…는 실행 당시 v-…와 다름(실행은 당시 버전 고정)` |
| A8 | 현재 구간 JSON의 `region_version`이 사본보다 크면 알림. 현재 구간 파일이 없거나 버전이 사본보다 작아져도 `WARN` | 같은 절 | `[WARN] A8 …: 구간이 실행 뒤 v1 → v2로 바뀜` |

### 4.5 ④ → ⑤

검토본이 없으면 C1–C5는 `SKIP 검토본 없음`입니다.

| ID | 검사 | 근거 | 실패 메시지 예 |
| --- | --- | --- | --- |
| C1 | 검토본 `analysis_run_id` = 폴더의 실행 ID = 분석의 `analysis_run_id`, `candidate_id`가 분석 후보에 있고 폴더 이름과 같음, `review_id` = `review-<candidate_id>` | [⑤](전체기획.md#data-contract) | `[FAIL] C1 review-deviation-p86-d09 v2: candidate_id가 분석에 없음` |
| C2 | 검토본 `analysis_ref.analysis_sha256` = 현재 `analysis.json` 바이트 SHA-256, `analysis_ref.region_ref`·`graph_ref` = 분석의 값 | [인터페이스 §5](인터페이스.md#5-검토-확정-데이터-규격) | `[FAIL] C2 review-… v2: 검토 뒤 analysis.json이 바뀜 (기록 3c9d…, 현재 a01f…)` |
| C3 | 버전 파일이 `v1..vn`으로 빠짐없이 이어지고, 각 파일의 `review_version` = 파일 번호, `previous_review_version` = 번호−1(v1은 없거나 `null`). `v0`은 허용하지 않음 | 같은 절 "버전 파일로 이력 보존" | `[FAIL] C3 review-deviation-p86-d10: v2 없음 (v1, v3만 있음)` |
| C4 | `scenario_decisions[].scenario_id`·`design_improvement_decisions[].dic_id`가 그 후보에 속함 | 같은 절 | `[FAIL] C4 review-… v1: 다른 후보의 시나리오 scenario-p86-d10-01` |
| C5 | 저장된 `review_status` = `hazop.review.record.compute_review_status(분석, candidate_id, 검토본)` 재계산 값 | [상태는 역할별로 구분](전체기획.md#상태는-역할별로-구분) | `[FAIL] C5 review-… v3: review_status 'confirmed'이나 재계산 'reviewing'` |

### 4.6 ⑤ 출력 기록

출력 기록이 없으면 `SKIP 출력 기록 없음`입니다.

| ID | 검사 | 근거 | 실패 메시지 예 |
| --- | --- | --- | --- |
| E1 | 출력 기록 `target.analysis_run_id`·`analysis_sha256`·`region_ref`·`graph_ref` = 분석의 값과 현재 파일 해시 | [검토·결과 관리 §구조화 저장](검토결과관리.md#구조화-저장과-excel-출력) "출력 기록" | `[FAIL] E1 export-20261106T…: analysis_sha256 불일치` |
| E2 | `target.reviews[]`의 `(candidate_id, review_version)` 검토본 파일이 있고 `review_status`가 같음 | 같은 절 | `[FAIL] E2 export-…: 검토본 deviation-p86-d09 v4 없음` |
| E3 | `file`이 있으면 그 바이트 SHA-256 = `file_sha256`. 파일이 없으면 `WARN`(삭제됨, 해시 확인 불가) | 같은 절 | `[FAIL] E3 export-…: 워크시트 파일 해시 불일치` |
| E4 | `rows.worksheet[]`·`rows.recommendations[]`의 `candidate_id`·`scenario_id`·`dic_id`가 분석에 있고 소속 관계가 맞음. 워크시트 행은 시나리오의 `candidate_id`가 행의 `candidate_id`와 같아야 함. 권고 행은 설계보완 후보의 `scenario_id`·`candidate_id`가 행의 값과 같아야 함(`hazop/export/worksheet.py` `worksheet_rows`·`recommendation_rows`). 예외: `rows.worksheet[]`의 `scenario_id`가 `null`인 행은 "시나리오 없음" 행이므로, 그 `candidate_id`가 `selected`이고 분석에 그 후보의 시나리오가 0개일 때만 `PASS` | 같은 절 | `[FAIL] E4 export-…: 행 8의 scenario_id가 분석에 없음` / `[FAIL] E4 export-…: 행 9는 시나리오 없음 행이나 deviation-p86-d09에 시나리오 5개` / `[FAIL] E4 export-…: 행 7의 scenario-p86-d10-01은 deviation-p86-d09 소속이 아님` |
| E5 | 분석 `validation.status`가 `blocked`인 실행에 출력 기록이 없음 | [검토결과관리 독립 검증](검토결과관리.md#독립-검증) | `[FAIL] E5 …: blocked 분석 결과에 출력 기록 있음` |
| E6 | (선택) 평가 비교 보고의 `target.analysis_sha256` = 현재 `analysis.json` 해시 | [평가 기준 비교 §5.1](평가기준비교.md#51-비교-보고-json) | `[FAIL] E6 compare-…: 비교 뒤 analysis.json이 바뀜` |

### 4.7 확인 수준 (knowledge_status·미확인) 전달

미확인·가설이 다음 단계에서 확정처럼 바뀌지 않았는지 봅니다([미확인·충돌](전체기획.md#미확인충돌)). K1·K2는 현재 산출물, K3–K6은 실행 사본(`inputs/`)과 `analysis.json` 기준입니다.

| ID | 검사 | 근거 | 실패 메시지 예 |
| --- | --- | --- | --- |
| K1 | 추출 `validation.unknowns`가 그래프 `validation.unknowns`로 이어짐. 규칙은 아래 "K1 대응 규칙" | [② → ③](전체기획.md#data-contract) | `[FAIL] K1 graph-SNP-M-102: 추출 미확인 not_registered/material_id가 그래프에 없음` / `[FAIL] K1 local-edge-007: 흐름 방향 미확인이 구간 노드 entity-seg-004에 다시 기록되지 않음` |
| K2 | 그래프 배관 구간 노드와 직접 관계(`relation-…`, `hazop/graph/build.py`가 `flow_direction`을 싣는 엣지)의 `flow_direction`이 `null`이 아니면, 대응 추출 관계의 `flow_direction`도 `null`이 아니고 두 값이 같음(방향을 새로 만들거나 뒤집지 않음). 비교는 끝점 local_id를 entity_id로 바꾼 뒤(`hazop/graph/build.py` 98–101행 매핑) `from`·`to`·`from_end`·`to_end`·`basis`가 모두 같은지로 함 또한 그래프 체크밸브 노드의 `check_direction`과 대응 추출 노드(같은 local_id)의 `check_direction`은 둘 다 있거나 둘 다 없어야 하고, 추출의 `inlet`·`outlet`(local_id)을 entity_id로 바꾼 값이 그래프의 `inlet`·`outlet`과 각각 같고 `basis`·`status`도 같아야 함. 한쪽만 있거나 입출구가 바뀌었거나 누락되면 FAIL([정보추출](정보추출.md#rules-followup) K2 확장, 총괄 결정 2026-11-06) | 같은 절 | `[FAIL] K2 entity-seg-004: 추출에 없는 흐름 방향` |
| K3 | 사본 그래프 `validation.unknowns` 중 `target`이 `null`이거나 `analysis_run.region_members`에 있는 항목과, 분석 `holds` 중 `source: "graph"`이고 `candidate_id: null`인 보류(상태 무관) 가운데 밸브 정상 위치 보류(`item`이 `"<태그 또는 entity_id> 정상 위치 미확인"`이고 `scope`가 정상 위치 없는 밸브인 것)를 뺀 것을 1:1로 대응. 대응 키는 (`scope`, `item`) = (`target`, 없으면 `"그래프 전체"`; `"<field> 미확인"`)(`hazop/analysis/run.py` `_run_level_holds`). 키별 개수가 같아야 함 | [HAZOP 분석 §정보 부족](HAZOP분석.md#정보-부족과-결과-저장) | `[FAIL] K3 …: 그래프 미확인 (entity-seg-004, flow_direction 미확인)에 대응 보류 0개(기대 1개)` / `[WARN] K3 …: 근거 미확인이 없는 graph 보류 hold-012` |
| K4 | 사본 구간의 미확정 항목과 `source: "input"` 보류를 1:1로 대응. `design_intent.knowledge_status`가 `confirmed`가 아니면 (`scope`, `item`) = (`"구간 설계 의도"`, `"설계 의도 미확정"`) 1개, `normal_operating_conditions[]`에서 `confirmed`가 아닌 항목마다 (`"운전조건"`, 항목의 `item`) 1개. 키별 개수가 같아야 함 | 같은 절 | `[FAIL] K4 …: (운전조건, 가압기 정상 운전압력) 보류 0개(기대 1개)` |
| K5 | 분석 시나리오의 `knowledge_status`가 모두 `hypothesis`(④는 확정하지 않음. 확정은 ⑤의 `review_status`) | [④ → ⑤](전체기획.md#data-contract) | `[FAIL] K5 scenario-p86-d09-01: knowledge_status 'confirmed'` |
| K6 | 위험도 `risk_proposal.status`가 `proposed`가 아닌 시나리오에 등급 값(`risk`)이 없음, 그리고 제외 후보의 위험도는 `not_applicable` | [상태는 역할별로 구분](전체기획.md#상태는-역할별로-구분) | `[FAIL] K6 scenario-…: 보류된 위험도에 등급 3` |

K1 대응 규칙(`hazop/graph/build.py` `build_graph` 기준)은 다음과 같습니다.

| 추출 미확인 | 그래프에 있어야 하는 것 |
| --- | --- |
| `check: unknown_flow_direction`, `target` = 관계 `local_id` L, L이 배관 구간 노드(`entity-seg-…`)로 매핑됨 | 그래프가 구간 노드 기준으로 다시 기록한 `check: unknown_flow_direction`, `target` = L의 entity_id, `field: flow_direction` 항목 1개. 추출 항목 자체는 그대로 넘어오지 않음(빌더가 건너뜀) |
| 위와 같으나 L이 직접 관계(`relation-…`)로 매핑됨 | 방어 규칙. 추출기는 `unknown_flow_direction`을 `physical_connection`에만 만들므로 정상 입력에서는 생기지 않음. 생기면 `WARN`(그래프 unknowns에 다시 기록되지 않음). 방향 값의 검사는 K2가 맡음 |
| 위와 같으나 L이 매핑 없음(양 끝이 확정되지 않은 미해결 커넥터) | 그래프 `unresolved[]`에 local_id L이 있으면 `PASS`(재기록 없음이 정상, 빌더가 건너뜀), 없으면 `FAIL` |
| 그 밖의 항목 | `origin: "extraction"`, `local_id` = 추출 `target`, `target` = 그 local_id의 entity_id(없으면 `null`)인 항목 1개. 대응 키는 (`check`, `field`, `source_object_id`, `local_id`) |
| 샘플 경로 | 위 "그 밖의 항목"으로 `check: not_registered`인 `project_id`·`material_id`·`registration_version` 3건이 반드시 있음 |

반대 방향으로, 그래프의 `unknown_flow_direction` 항목은 대상 구간 노드의 `flow_direction`이 `null`일 때만 있어야 합니다.

K3·K4·K6은 `hazop.analysis.run.check_result`와 `_run_level_holds`가 실행 때 지키는 규칙입니다. 이 검사는 저장 뒤의 파일에서 같은 결과가 남아 있는지 독립적으로 다시 봅니다.

## 5. 출력

콘솔에는 연쇄마다 위 형식의 줄을 쓰고, 끝에 `요약: PASS n · FAIL n · WARN n · SKIP n`을 씁니다. `--report`를 주면 아래 JSON을 씁니다(키 정렬, 끝 줄바꿈).

```json
{
  "schema_version": "0.1",
  "check": "contract",
  "check_version": "0.1.0",
  "checked_at": "2026-11-06T00:00:00Z",
  "roots": {"work_root": "...", "store_root": "..."},
  "chains": [{
    "path": "samples",
    "region_id": "region-SNP-M-102-pzr",
    "analysis_run_id": "analysis-20261104T105431Z-2e14dd",
    "graph_ref": {"graph_id": "graph-SNP-M-102", "graph_version": "v-f65e4ec1135d"},
    "extraction_run_id": "extract-SNP-M-102-p0-drawio-rules-draft-2026-11-03-7f4c87c61f8b",
    "material_ref": null,
    "results": [{"id": "R1", "level": "SKIP", "target": "extraction SNP-M-102", "message": "샘플 경로(등록 미연동)"}]
  }],
  "errors": [],
  "notes": [],
  "summary": {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 1}
}
```

`errors`는 실행 오류 목록(§2.3), `notes`는 건너뛴 미완성 실행(`analysis.json` 없음) 등의 메모입니다.

## 6. 독립 검증

임시 작업 루트·저장 루트(환경변수 `HAZOP_WORK_ROOT`·`HAZOP_STORE_ROOT`)에 샘플을 복사하거나 새로 만든 뒤 검사합니다. 저장소의 `출력/`·`자료저장소/`는 고치지 않습니다. 각 사례는 정상 연쇄를 만든 뒤 한 곳만 바꿉니다.

정상 연쇄 준비(구현 담당):

- **샘플 연쇄 S**: `출력/추출/SNP-M-102/`, `출력/그래프/SNP-M-102/`, `데이터/구간/region-SNP-M-102-pzr.json`, 최신 분석 실행 폴더를 임시 작업 루트로 복사합니다. 기존 검토 API(`build_review`·`save_review`)로 `deviation-p86-d09` 검토본 v1·v2를 만들고(v2에는 미결정 시나리오를 남겨 `review_status: reviewing`), 그 뒤 `export_worksheet`로 출력 기록 1개를 만듭니다. 이 출력 기록의 `target.reviews`는 `deviation-p86-d09` v2를 가리킵니다.
- **등록 연쇄 R**: 임시 저장 루트에 SNP-M-102 drawio를 등록하고(`registry.register`, 프로젝트 `p-test`, 파일 위치 `<임시 저장 루트>/p-test/`), 등록정보를 넣어 추출·그래프를 만듭니다. 구간 JSON의 `project_id`·`graph_ref`를 맞춘 뒤 고정 응답으로 분석 1회를 실행합니다.

| ID | 사례 | 기대 결과 |
| --- | --- | --- |
| V1 | 샘플 연쇄 S 그대로 | `FAIL` 0. R1–R4 `SKIP`(샘플 경로), K1의 `not_registered` 3건 `PASS` |
| V2 | 등록 연쇄 R 그대로 | `FAIL` 0. R1–R3 `PASS` |
| V3 | R에서 저장 원본 파일 1바이트 변경 | R3 `FAIL` |
| V4 | R에서 추출 `project_id`만 `p-other`로 변경 | G2·R1 `FAIL`(추출 project_id로 찾은 등록 스냅샷 없음), R2–R4 `SKIP`(R1 실패), X2 `FAIL`(그래프 버전은 추출 전체로 계산하므로 재계산 값이 달라짐, `hazop/graph/build.py` `_graph_version`) |
| V5 | R에서 같은 원본 파일에 메타데이터(예: `design_revision`)만 바꿔 등록 버전 v2를 만듦(추출은 v1 유지) | R4 `WARN`. 원본 해시가 같으므로 R3 `PASS`, `FAIL` 0 |
| V6 | S에서 추출 결과의 노드 1개 삭제 | X2·X3 `FAIL` |
| V7 | S에서 `entity_mapping.json`의 항목 1개 삭제 | X4 `FAIL`. X3은 `graph.json` 기준이라 `PASS` |
| V8 | S에서 실행 사본 `inputs/graph.json`에 공백 1개 추가 | A2 `FAIL` |
| V9 | S에서 `analysis.json`의 한 시나리오 `graph_evidence.node_ids`에 `entity-node-999` 추가(분석 해시가 바뀌므로 C2·E1도 `FAIL`) | A5·C2·E1 `FAIL` |
| V10 | S에서 drawio 사본의 글자 1개를 바꿔 임시 `출력/추출/SNP-M-102/`에 다시 추출하고, 그 추출로 `출력/그래프/SNP-M-102/`를 다시 빌드(추출과 그래프를 함께 교체) | 현재 추출·그래프가 서로 맞으므로 X1–X4 `PASS`. A7 `WARN`(현재 그래프 버전이 실행 당시와 다름). 실행 사본 기준 검사 A2–A6 `PASS` |
| V11 | S에서 검토본 v2를 지우고 v3을 `previous_review_version: 2`로 둠 | C3 `FAIL`, E2 `FAIL`(출력 기록이 가리키는 v2 없음) |
| V12 | S에서 검토본 v2의 `review_status`를 `confirmed`로 고침(미결정 시나리오는 그대로) | C5 `FAIL`, E2 `FAIL`(출력 기록의 `review_status` `reviewing`과 다름) |
| V13 | S에서 워크시트 xlsx 1바이트 변경 / xlsx 삭제 | E3 `FAIL` / E3 `WARN` |
| V14 | S에서 그래프 `validation.unknowns`의 `not_registered`·`material_id` 항목 삭제 | K1 `FAIL`(X2는 그래프 파일만 바뀌었으므로 `PASS`) |
| V15 | S에서 추출의 `physical_connection` 관계 1개의 `flow_direction`을 `null`로 바꾸고, 추출 `validation.unknowns`에 그 관계의 `unknown_flow_direction` 항목을 추가(그래프는 그대로) | K2 `FAIL`(그래프 구간 노드에는 방향이 있음), K1 `FAIL`(구간 노드 기준 재기록 없음), X2 `FAIL`(추출 변경) |
| V16 | S의 `analysis.json`에서 그래프 미확인에 대응하는 보류 1개 삭제 | K3 `FAIL`(분석 해시가 바뀌므로 C2·E1도 `FAIL`) |
| V17 | S의 `analysis.json`에서 시나리오 1개 `knowledge_status`를 `confirmed`로 변경 | K5 `FAIL`(C2·E1도 `FAIL`) |
| V18 | 검토본·출력 기록이 없는 실행 | C1–C5·E1–E5 `SKIP`(사유 표시), 종료 코드 0 |
| V19 | `--run all`로 같은 구간의 이전 실행까지 검사 | 실행마다 연쇄 결과 분리, 오래된 실행의 필드 누락은 해당 항목 `FAIL`로 표시하고 검사 전체는 중단하지 않음 |
| V20 | 같은 입력으로 두 번 실행(`checked_at` 제외) | 보고 JSON 동일 |
| V21 | S의 출력 기록에서 `rows.worksheet[]` 한 행의 `scenario_id`를 다른 후보(`deviation-p86-d10`)의 유효한 시나리오 ID로 바꿈 | E4 `FAIL`(소속 불일치) |

V8·V16처럼 사람이 결과 파일을 고의로 바꾸는 경우는 [신뢰 경계](전체기획.md#trust-boundary) 밖이지만, 이 검사는 "연결이 끊어진 것을 발견하는가"를 보는 시험이라 사례로 씁니다. 검사를 통과했다고 변조가 없다고 보장하지는 않습니다.

### 6.1 통과 기준

V1–V21이 모두 기대 결과와 같아야 합니다. V1은 현재 저장소의 샘플 결과에 대한 실제 판정이므로, 구현 시 `FAIL`이 나오면 검사 오류인지 실제 연쇄 결함인지 구분해 보고합니다(결함이면 해당 단계 담당에게 넘김).

## 7. 미확정 사항

| 항목 | 현재 처리 |
| --- | --- |
| 직접 관계의 흐름 방향 미확인 | 추출기는 `unknown_flow_direction`을 `physical_connection`에만 만듭니다(미해결 커넥터 포함, `hazop/extract/adapters/pdf_vector.py`도 같음. `hazop/extract/rules.py` `RELATION_KINDS_WITH_FLOW`, `hazop/extract/drawio.py` 591행 부근). 직접 관계에 이 항목이 생기는 경우는 K1 방어 규칙(`WARN`)으로만 다룹니다. 추출 규칙이 바뀌어 직접 관계에도 방향 미확인이 생기면 빌더의 재기록 범위와 K1 규칙을 함께 다시 정해야 합니다(코드 읽기로 확인, 실행 미확인) |
| 지식그래프 입력(`inputs/knowledge_graph.json`) 연쇄 | A2 해시 검사만 포함. 지식그래프 자체의 `kg_version`·`graph_refs` 연쇄는 [그래프 활용](그래프활용.md) 트랙에서 정하면 추가 |
| 변경 알림(`material_changed`·`graph_changed`) | 후속 기능이므로 검사하지 않음 |
