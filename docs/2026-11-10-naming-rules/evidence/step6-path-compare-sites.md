# 단계 6 전 조사: 기록 경로를 문자열 그대로 쓰는 곳

- 조사일: 2026-11-10, 기준 커밋 `a810b99`. 단위 NAMING N4a.
- 물음: 사용자 파일에 적힌 작업 루트 기준 상대 경로(`출력/그래프/…`, `데이터/구간/…`, `자료저장소/…`)를 `paths.resolve_rel`로 풀지 않고 **문자열로 비교하거나 키·해시 입력으로 쓰는** 코드가 어디인가. 단계 6에서 폴더 이름이 바뀌면 옛 파일의 문자열과 새 코드가 만드는 문자열이 달라진다.
- 방법: `hazop/`, `scripts/`, `packaging/`에서 `rel_or_abs(` 호출과 그 값을 읽는 곳을 따라갔다. 표의 줄은 모두 코드를 읽어 확인했다. 실행해서 확인한 것은 '실행'이라고 적었다. `tests/`는 보지 않았다.

## 1. 경로를 적는 곳 (`rel_or_abs`가 만든 값이 파일에 남는 자리)

| 파일:줄 | 남는 자리 |
| --- | --- |
| `hazop/analysis/run.py:70`, `101` | `analysis.json`의 `analysis_run.input_files[].path` |
| `hazop/analysis/run.py:248` | 구간 JSON `graph_ref.graph_file` |
| `hazop/analysis/ai.py:140` | `analysis.json`의 `analysis_run.ai_client.response_dir` |
| `hazop/extract/drawio.py:861`, `adapters/raster.py:890`, `adapters/pdf_vector.py:2263` | `extraction.json`의 `source.file` |
| `scripts/extract_drawio.py:77`, `scripts/extract_pdf.py:89` | `extraction.json`의 `coordinate_system.svg_alignment.svg_file` |
| `scripts/build_graph.py:31` | `graph.json`의 `source.extraction_file` |
| `hazop/export/worksheet.py:510` | 출력 기록 `<저장 루트>/reviews/…/exports/<시각>.json`의 `file` |
| `scripts/analyze_kg.py:41`, `57` | `algo_result.json`의 `inputs.region_ref.file`, 후보 CSV `file` |
| `scripts/clean_outputs.py:143`, `223`, `294` | 정리 계획의 `rel`, `출력/_보관/<시각>/manifest.json`의 `original`·`archived`(출력 폴더 기준 상대 경로) |
| `hazop/register/registry.py:506` | 등록정보 `input_path`(`rel_or_abs`가 아니라 `_display_path`. 작업 루트 안이면 상대 경로) |

경로를 적지 않는 것: 실행 ID(`run.py:408`, 내용 해시만), 지식 입력(`kg/inputs.py`), `current.json`(판 이름만), 등록 `storage_ref`(프로젝트 폴더 기준 `originals/…`), 검토 기록, 평가 비교 보고서, 초기사건·도면수정·도면연결·검토구간·⑤ 결과(모두 `project_id`·`graph_id`가 키).

## 2. 문자열 그대로 비교하거나 해시에 넣는 곳

| # | 파일:줄 | 무엇을 하나 | 이름이 바뀌면 | 위험 | N4b가 할 일 |
| --- | --- | --- | --- | --- | --- |
| 1 | `hazop/graph/build.py:75-78` | 추출 JSON 전체를 해시해 `graph_version`을 만든다. 그 안에 `source.file`과 `svg_file`이 들어 있다 | **등록한 자료를 새 판 앱에서 다시 추출하면** `source.file`이 `자료저장소/<프로젝트>/originals/…`에서 `store/…`로, PDF의 `svg_file`이 `출력/추출/<이름>/page.svg`에서 `output/extract/…`로 바뀌어 판이 달라진다. 그러면 구간의 `graph_ref` 불일치(`run.py:125-128`), 검토구간·⑤ 결과 재확인, 지식그래프 판 변경, 고정 응답 `input_mismatch`가 줄줄이 생긴다. 이미 있는 `extraction.json`으로 그래프만 다시 만들면 문자열이 그대로라 판이 같다. 샘플 도면은 기록 경로(`참고자료/…`)가 고정이라 무관하다 | **높음** | 작업 루트 쪽도 기록 경로를 고정한다. `rel_or_abs`가 저장 루트·출력 폴더 아래 파일을 옮기기 전 이름(`자료저장소/…`, `출력/추출/…`)으로 적게 `OLD_NAMES`에 `record=True` 줄을 둔다(단계 5의 샘플 도면과 같은 방식). 이 PC 배포본 사본의 등록 자료 1건을 새 코드로 다시 추출해 판이 같은지 본다 |
| 2 | `hazop/analysis/run.py:957-960` | 재시도 때 기록된 `ai_client.response_dir`와 이번 값을 `!=`로 견준다 | 옛 실행은 `데이터/고정응답/…`, 새 코드는 `data/fixed-responses/…`를 만들어 "AI 모드가 다름"으로 재시도를 거부한다. `scripts/analyze.py:58`은 기록 문자열을 작업 루트에 그대로 붙이므로 폴더도 못 찾는다 | 중간(CLI 재시도, 고정 응답 실행만) | `analyze.py:58`을 `resolve_rel`로 풀고, 비교는 푼 경로끼리 하거나 #1처럼 기록 경로를 고정한다 |
| 3 | `scripts/clean_outputs.py:106-110`, `164` | 설정 `recent_runs`의 절대 경로를 실행 폴더의 `normcase(abspath)`와 `in`으로 견준다 | 옛 절대 경로(`…\출력\분석\…`)가 새 폴더와 맞지 않아 '보존' 사유가 빠지고 그 실행이 보관 폴더로 옮겨질 수 있다(지우지는 않는다) | 낮음. 앱은 `recent_runs`를 쓰지 않는다(§4) | 설정 경로 변환을 넣는다면 이 읽기도 같은 함수로 |
| 4 | `scripts/analyze_kg.py:41`, `57` → `hazop/kg/algo.py`의 결과 문서 해시와 출력 폴더 이름 | 구간 파일 라벨(`데이터/구간/x.json`)과 후보 CSV 경로가 결과 ID에 들어간다 | 같은 입력이어도 새 결과 폴더가 생긴다. 옛 결과는 남지만 '같은 결과'로 찾지 못한다. 앱 화면은 파일 이름만 써서 무관하다 | 낮음 | 기록 경로를 고정하면 함께 풀린다. 아니면 그대로 두고 적어 둔다 |
| 5 | `packaging/w4_flow.py:190-192` | 표본 구간의 `graph_file`을 작업 루트에 그대로 붙인 경로와 지금 만든 그래프 폴더를 견준다 | `출력` 이름이 바뀌면 어긋나 묶음 검증이 실패한다 | 중간(검사) | `resolve_rel`로 푼다 |
| 6 | `scripts/check_desktop_support.py:98-100` | 새 실행의 `input_files[].path`와 구간 `inputs`의 문자열을 견준다 | 읽기만 해 보면 표본 구간은 `데이터/이탈후보/…`, 새 실행은 `resources/library/…`라 지금도 어긋나 보인다. 실제 데스크톱이 필요한 검사라 돌려 보지 않았다 | 중간(검사). 단계 6과 무관하게 확인할 것 | 실제로 실패하는지 먼저 확인 |
| 7 | `hazop/app/data.py:274-277` | 추출 요약 캐시의 키가 `extraction.json` 절대 경로 | 캐시를 못 맞혀 다시 읽는다. 결과는 같다 | 낮음 | 없음 |
| 8 | `hazop/paths.py`의 `is_reference_rel`(호출 `hazop/app/data.py:255`) | `source.file`이 `참고자료/`로 시작하는지 본다 | 기록 접두를 바꾸지 않는 한 무관하다 | 낮음 | `REFERENCE_LOGICAL`을 바꾸지 않는다 |

같은 세션에서 만든 절대 경로끼리 견주는 곳(`analysis.py:449`, `main_window.py:1374`, `register.py:391`, `knowledge.py:321`·`336`, `data.py:41`, `kg/auto.py:69`·`97`)은 영향이 없다. `extraction_name_for_graph_file`(`data.py:459`)은 마지막 폴더 이름만 쓴다.

## 3. `resolve_rel`을 거치지 않고 작업 루트에 바로 붙여 여는 곳

비교는 아니지만, 폴더 이름이 바뀌면 옛 기록을 못 찾는다. 옛 접두를 `OLD_NAMES`에 넣어도 여기는 풀리지 않는다.

| 파일:줄 | 무엇을 여나 | 못 찾으면 |
| --- | --- | --- |
| `hazop/app/data.py:485` `current_graph` | 구간 `graph_ref.graph_file` | "구간의 그래프 파일이 없음" 배너 |
| `hazop/app/runctx.py:27` | 실행 구간 사본의 `inputs.knowledge_graph` | 지식그래프 상태 '읽을 수 없음' |
| `hazop/contract/chain.py:98` `_resolve`(154행 `source.extraction_file`, 792행 출력 기록 `file`) | 추출 결과, 워크시트 | 연쇄 검사 FAIL·WARN |
| `scripts/analyze.py:58` | 기록된 `response_dir` | 고정 응답 없음 |
| `scripts/extract_drawio.py:70` | 등록정보 `input_path` 옆 SVG | 옆 SVG를 못 찾으면 `svg_alignment`가 바뀌고 판도 바뀐다(#1과 같은 결과) |
| `hazop/study/providers.py:110` | 설정 `fixed_response_dir`(절대 경로) | 고정 응답 폴더 없음 |

`resolve_rel`로 푸는 곳은 10곳이다(`run.py:50`과 그것을 쓰는 64·93·217행, `viewer/build.py:112`, `candidate_edit.py:37`, `check_analysis.py:122`·`124`, `check_kg_context.py:330`, `check_desktop_support.py:74`, `w4_flow.py:164`). 지금 `OLD_NAMES`에는 작업 루트 쪽 줄(`출력/`, `데이터/…`, `자료저장소/`)이 없어서, 이 10곳도 단계 6 뒤에는 줄을 더해야 풀린다.

## 4. 설정 파일의 `recent_runs`·`recent_regions`

- 쓰는 코드가 없다. `paths.DEFAULT_SETTINGS`가 빈 목록으로 두고, 앱은 읽은 설정을 그대로 다시 쓸 뿐이다(`main_window.py:132`·`1307`, `AiPrefs._set`). `git grep -n "recent_runs\|recent_regions" -- '*.py'`로 확인했다.
- 읽는 코드는 `scripts/clean_outputs.py:99-110` 하나다. `recent_runs`의 각 항목이 문자열이면 그 값, dict면 그 값들을 모아 원문과 `normcase(abspath)` 둘 다 집합에 넣는다. 모양을 정한 곳이 없어 둘 다 받는다.
- 이 PC의 `%APPDATA%\HAZOP\settings.json`(읽기만): `reviewer_name`, `work_root: null`, `recent_regions: []`, `recent_runs: []` 네 키뿐이다.
- 앱 코드로 임시 설정 폴더에 만들어 본 모양(실행, `AiPrefs`로 고정 응답 폴더를 고른 뒤 `save_settings`):

```json
{
  "reviewer_name": null,
  "work_root": null,
  "recent_regions": [],
  "recent_runs": [],
  "fixed_response_dir": "<작업 루트 절대 경로>\\데이터\\고정응답\\region-SNP-M-102-pzr"
}
```

- 그래서 설정 파일에서 옛 폴더를 가리킬 수 있는 값은 `fixed_response_dir`(절대 경로)와, 누가 손으로 적은 `recent_runs`뿐이다. `recent_regions`는 읽는 곳도 쓰는 곳도 없다. HZ-GOV-02 §6.6 대책 3의 '설정 파일 경로 변환'은 `fixed_response_dir`를 대상으로 삼아야 한다.

## 5. 못 본 것

- `tests/` 전체, `docs/`, `resources/samples`의 다른 파일.
- `hazop/app/screens/results.py`, `study.py`, `initiating.py` 안쪽(경로 비교로 찾은 줄은 없었다).
- `hazop/extract/adapters/evaluation.py:389`의 `source_file`(보고서 표시로만 보았다).
