# 표제란 후보와 사람 확정 (A3, 2026-11-14)

표제란에서 읽은 도면 번호·개정·제목은 후보로만 두고 사람이 확정합니다([INTENT §3.1](../../../../INTENT.md)). 화면 규격은 [HZ-DSN-05](../../../design/app-shell-web.md)의 '표제란 후보 + 후보 확정'(도면 패널 행, §2.3)과 명령 표의 `register.confirm_title`입니다. 새 화면 명령 이름은 영역 모듈 규약(`hazop/shell/README.md`)에 맞춰 `titleblock.confirm`·`titleblock.unconfirm`으로 했습니다.

- 엔진: `hazop/register/titleblock.py`(화면·채팅 공용). 등록정보의 확정 취소는 `hazop/register/registry.py`의 `clear_metadata`, 최신 버전 읽기는 `latest`.
- 새 화면: `hazop/shell/api_titleblock.py`(읽기 토픽 `titleblock`, 명령 둘), `web/js/panels/titleblock.js`·`titleblock.css`.
- 시험: `tests/test_titleblock.py`(엔진), `tests/test_shell_titleblock.py`(새 화면 명령).

## 1. 어디에 무엇이 남나

| 값 | 자리 | 뜻 |
| --- | --- | --- |
| 후보 | 등록정보 `auto_candidates[항목]` `{value, source, page_id, key_object_id, value_object_id}` | 등록할 때 표제란(drawio 칸, PDF 표제란, DEXPI 도면 정보)에서 읽은 값. 확정 전에는 어디에도 확정값으로 쓰지 않음 |
| 확정값 | 등록정보 `drawing_number`·`design_revision`·`title` | 사람이 확정한 값만. 추출 결과 `drawing.drawing_number` 등과 그래프 ID(`graph-<도면 번호>`)가 이 값을 씀 |
| 누가·언제 | 등록정보 `history[]` `{action: "confirm_metadata"\|"unconfirm_metadata", field, before, after, by, at, reason}` | 확정·취소마다 새 등록 버전이 생기고 이력이 쌓임(지난 버전 파일은 그대로) |

확정 전 항목은 등록정보의 미확인(`validation.unknowns`)으로 남고, 추출 결과에 쪽 전체 미확인 `registration_unknown`으로 넘어갑니다. 쪽 확정은 미확인 전체가 0이어야 하므로(화면 규격 §10.4) **표제란 세 항목을 확정하기 전에는 쪽 확정이 되지 않습니다.** 규격에 따로 '표제란 확정' 조건을 더하지 않아도 지금 규칙이 그대로 막습니다(시험 `test_candidates_with_evidence_and_nothing_confirmed_until_a_person_does`). 쪽 전체 미확인이라 '이대로 확인'으로는 끝낼 수 없고 표제란을 확정해야 합니다.

## 2. 확정하면 생기는 일

1. 새 등록 버전(`r<n+1>`)을 만듭니다(원본·파생 SVG는 그대로 씀).
2. 이미 추출한 도면이면 새 버전으로 다시 추출하고 그래프를 다시 만듭니다(`data.extract_and_graph`). 추출 결과 폴더 이름에 등록 버전이 들어가므로(`<프로젝트>__<자료>-r<버전>-p<쪽>`) 새 폴더가 생깁니다.
3. 앞 버전 이름의 **사람 수정 기록**(`data/drawing-edits/`)과 **AI 후보 기록**(`data/ai-review/`)을 새 이름으로 옮겨 씁니다(`extraction_name`을 새 이름으로, `carried_from`에 앞 이름). 같은 원본이라 사람 수정은 다시 추출해도 그대로 적용됩니다. 앞 파일은 지우지 않습니다. 새 이름에 이미 기록이 있으면 덮지 않습니다.
4. **쪽 확정 기록은 옮기지 않습니다.** 추출 결과가 바뀌어 어차피 풀리고, 사람이 바뀐 도면을 다시 보고 확정해야 합니다. 풀린 쪽은 결과의 `released_sheet_confirmations`에 적습니다.

**도면 번호가 바뀌는 경우(권장안으로 정함).** 도면 번호는 그래프 ID이고 검토구간·분석 결과의 열쇠입니다(`study-nodes/<프로젝트>/<그래프 ID>`, `analysis-results/…`). 그래프 ID를 옮기는 길은 아직 없으므로:

- 확정·취소로 그래프 ID가 바뀌는데 **앞 ID나 새 ID에 구간·분석 결과가 있으면 막고** 이유를 보입니다(`code: rule`). 확정 전 번호가 없을 때의 그래프 ID는 쪽 이름(drawio 쪽 이름, 보통 도면 번호와 같음)이라, 후보 그대로 확정하면 ID가 바뀌지 않아 막히지 않습니다.
- **같은 형식의 다른 자료가 같은 번호를 이미 확정해 쓰면 막습니다**(`code: conflict`, 대소문자 무시). 그래프 ID가 겹쳐 한 도면이 가려지기 때문입니다.
- **다른 형식(drawio·PDF·DEXPI)이면 막지 않고** 등록이 돌려주는 충돌(`hazop.graph.sources`의 길, 0078bc5)을 알립니다. 그래프에 쓸 원본은 도면 패널의 충돌 고르기에서 사람이 고릅니다.
- **여러 쪽 자료(PDF 여러 쪽)는 도면 번호를 확정하지 않습니다.** 등록정보의 번호 하나를 모든 쪽이 나눠 써서 쪽마다 그래프 ID가 겹치기 때문입니다. 쪽별 확정은 후속입니다(개정·제목도 같은 까닭으로 자료 하나에 한 값).

## 3. 새 화면 명령과 읽기

| 이름 | 인자 | 하는 일 · 답 |
| --- | --- | --- |
| 읽기 `titleblock` | — | `{project_id, reviewer, rows: [행], fields: [{id, label}], totals: {materials, confirmed}}`. 행은 확정 전 → 일부 → 확정 순 |
| 읽기 `titleblock/<자료 ID>` | — | 행 하나(없으면 404) |
| `titleblock.confirm` | `material_id`, `fields` {`drawing_number`?, `design_revision`?, `title`?: 값}, `reason`?, `ver` | 검사를 바로 하고 막히면 오류 답(`stale`·`bad_args`·`failed`와 사유). 통과하면 이미 추출한 쪽이 있을 때 작업을 시작해 `{changed: true, job}`, 없으면 바로 `{changed: true, row, …}`. 바뀐 값이 없으면 `{changed: false, row}` |
| `titleblock.unconfirm` | `material_id`, `fields` [항목]?(없으면 셋 다), `reason`?, `ver` | 확정 취소. 답은 위와 같음 |

행: `{material_id, project_id, version, name, format, material_type, status, pages, multi_page, state: "unconfirmed"|"partial"|"confirmed", ver, fields: [{field, label, value, candidate, evidence: {source, page_id, key_object_id, value_object_id, text}, confirmed_by, confirmed_at}], sheets: [{page, name, graph_id, page_name}], review_data: ["구간"?, "분석 결과"?]}`.

- `by`는 설정의 검토자 이름이고 `at`은 엔진이 채웁니다. 검토자 이름이 없으면 거절합니다.
- `ver`는 최신 등록정보 파일의 지문입니다. 본 뒤 다른 창·채팅이 확정했으면 `stale`.
- 작업이 끝나면 `job.done`의 `result`가 `{material_id, version, re_extracted, carried: [{from, to, edits, ai_review}], released, number_conflicts: [도면 번호], notes}`이고, 바뀜 알림 `titleblock`·`sheetconf`·`kg`(그리고 작업 공통의 `drawings`)을 보냅니다. 작업 안에서 다시 검사해 막히면 `job.failed`(사유 한 줄)입니다.
- 웹은 경로를 보내지 않습니다(자료 ID만).

화면 쪽 등록 줄(`api.py` `MODULES`, `panels/index.js` `PANELS`, `areas.js` `resetAreas`)과 도면 패널 행에서 여는 자리(`titleblock.js`의 `focusSheet(graph_id)`)는 틀 담당(s-frame)이 넣습니다.

## 4. 채팅이 부를 실행 함수

`hazop.register.titleblock.execute(project_id, command, args, by, ver)` — 채팅 연결은 d-chat이 합니다.

| `command` | `args` | 답 |
| --- | --- | --- |
| `view` | `material_id`?(없으면 프로젝트 전체) | `{ok, rows: [행]}` |
| `confirm` | `material_id`, `fields` {항목: 값}, `reason`? | `{ok, changed, version, re_extracted, carried, released_sheet_confirmations, conflicts, notes, row}` |
| `unconfirm` | `material_id`, `fields` [항목]?, `reason`? | 위와 같음 |

- 거절은 `{ok: false, refused: [{target, code, reason}]}`이고 `code`는 `unknown_command`·`bad_actor`(사람 이름 없음)·`bad_args`·`stale`·`not_found`·`rule`(번호를 바꾸면 끊김, 여러 쪽 자료, 등록 미완료)·`conflict`(같은 형식 같은 번호)·`io`입니다.
- `confirm`·`unconfirm`은 사람이 확인 상자를 누른 뒤에만 부릅니다(사람의 판단을 기록하는 일). `by`는 누른 사람 이름입니다. 다시 추출이 들면 오래 걸리므로 작업으로 돌립니다(`progress(text, done, total)` 인자를 받음). `dry=True`면 검사만 합니다.
