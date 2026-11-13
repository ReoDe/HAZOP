# ⑤ 결과 명령과 판정의 보류·사유 (결과 단위 RS, 2026-11-13)

새 화면(웹 shell) 3단계의 분석 결과 패널과 채팅이 부를 ⑤ 결과 명령을 정리했습니다. 구현은 `hazop/study/result_commands.py`(명령)와 `hazop/study/results.py`(판정 규칙)이고, 근거는 [INTENT §3.6](../../../../INTENT.md) '검토 확정: 수용·수정·기각·보류 + 사유', [웹 화면 규격](../../../design/app-shell-web.md) §6 'E. 결과 판정 보강'·§8 UW11, [결과 검토 규격](../../../specs/review-results.md)입니다. 시험은 `tests/test_results_hold.py`입니다. 구간 명령은 [node-commands.md](node-commands.md)와 같은 꼴입니다.

## 1. 판정 규칙

| 판정(화면 글자) | 저장 값 `status` | 사유 | 비고 |
| --- | --- | --- | --- |
| 수용 | `approved` | 선택(비워도 됨) | 초기사건 인계는 수용(승인) 항목만 넘김 |
| 수정 | `revised` | 필수 | 항목 내용을 고치면(`edit_entry`) 수정이 되고 다시 수용해야 함. 보류 항목은 고쳐도 보류로 남음 |
| 기각 | `rejected` | 필수 | 살아 있는 시나리오·권고에서 빠짐 |
| 보류 | `on_hold` | 필수 | 아직 결론을 내지 않음. 미검토로 셈, 구간 잠금을 막음, 인계하지 않음, 권고는 남김. 사람이 판정(`set_status`)을 바꿀 때만 풀림(내용 고치기로는 풀리지 않음) |
| (AI 초안) | `proposed` | — | 사람이 정할 수 없는 값(AI 재실행이 덮어씀) |

- 판정 기록은 항목의 `history`에 `{at, op: "status"|"edit", from, to, reason, by}`로 남습니다. `at`은 엔진이 채웁니다. `by`는 부르는 쪽이 넘긴 검토자 이름입니다(웹 화면은 설정의 검토자 이름).
- 지금 판정은 `results.verdict(entry)` → `{status, reason, by, at}`(마지막 상태·수정 기록). 옛 기록은 `reason`·`by`가 `null`입니다.
- 사유는 앞뒤 공백을 지운 글이고, 수정·기각·보류에서 비면 거절합니다.

## 2. 결과 파일 판

- 결과 파일 `schema_version`은 `0.3`입니다(보류와 사유). `0.2` 파일(보류·사유 없음)은 그대로 읽고 옛 판정·이력은 바꾸지 않습니다. `0.1`은 앞 단위(N1)의 변환 그대로입니다.
- **읽기는 파일을 쓰지 않습니다**(`load`·`load_fp`·`load_view`·`load_test_fp`, 읽기 명령). 원본 보관은 결과 파일을 쓰는 단 하나의 길(`results._put`, `save_fp`·`write`가 부름)이 옛 판(`0.1`·`0.2`) 파일을 덮기 직전에 한 번 합니다(`<이름>.v<판>.bak.json`, 같은 이름에 다른 내용이 있으면 새 이름). 보관하지 못하면 쓰지 않고 `OSError`를 올립니다. 이 앱이 모르는 판의 결과 파일은 덮지 않습니다(`store_io.Conflict`).
- 시험용(고정 응답) 결과 파일도 같은 규칙으로 읽습니다(`results.load_test_fp`). 이전 화면은 옛 판이면 바꿔 읽고, 읽을 수 없거나 문서에 문제가 있으면 빈 결과로 덮지 않게 읽기 전용으로 엽니다.
- 옛 앱(0.2까지 아는 판)은 `0.3` 파일을 '이 앱보다 새 파일'로 읽지 않아, 보류 항목을 모르는 앱이 덮어쓰지 않습니다.

## 3. 명령 부르는 법

```python
from hazop.study import result_commands
cell = result_commands.execute(pg, "get_cell", {"node_id": "S3", "deviation_id": "D07"}, by="홍길동", fingerprint=None)
out = result_commands.execute(pg, "set_status",
                              {"node_id": "S3", "deviation_id": "D07", "entry_id": "e12", "status": "on_hold",
                               "reason": "운전 절차서 확인 뒤 판단", "node_rev": cell["node_rev"]},
                              by="홍길동", fingerprint=cell["fingerprint"], set_rev=cell["set_rev"])
```

- 서명은 `execute(pg, name, args, by, fingerprint, set_rev=None)`입니다. `pg`는 프로젝트 그래프(구간 명령 `node_commands.execute`의 `pg`와 같음)입니다. **검토구간 집합은 넘기지 않습니다.** 엔진이 실행할 때마다 직접 읽습니다(읽기 명령은 `nodes.load_view`로 쓰지 않고, 쓰는 명령은 `nodes.load_fp`). 그래서 그 사이 다른 창이 잠근 구간은 낡은 화면에서 고칠 수 없습니다.
- 옛 호출 꼴 `execute(집합, name, args, by=…, fingerprint=…, pg=그래프)`도 당분간 받습니다. 이때 첫 인자(집합)는 쓰지 않고 `pg`로 읽습니다. 집합만 넘기고 `pg`가 없으면 `bad_actor`로 거절합니다. 웹 화면(`hazop/shell/api_results.py`)이 새 꼴로 옮기면 `pg=` 자리를 지웁니다.
- **쓰는 명령은 실행 직전에 셋을 대조합니다.** ① `set_rev`(화면이 읽은 집합 판, 읽는 명령이 돌려줌)가 `None`이 아니면 지금 집합 판과, ② `args.node_rev`(`get_cell`이 돌려줌)가 있으면 대상 구간의 지금 `rev`와, ③ `fingerprint`(결과 파일 지문, `"sha256:…"`)가 `None`이 아니면 지금 결과 파일 지문과. 하나라도 다르면 `stale`로 거절합니다. 잠긴 구간·보관 칸은 지금 집합으로 막습니다(`rule`). `None`은 대조하지 않음(시험용)입니다.
- 돌려주는 값은 모든 명령이 `{ok, command, fingerprint, set_rev, refused: [{target, code, reason}], …명령별 값}`입니다. `ok`가 `false`면 아무것도 저장하지 않은 것입니다. `fingerprint`는 실행 뒤(쓰지 않았으면 지금) 결과 파일 지문, `set_rev`는 지금 집합 판입니다.
- 거절 `code`는 구간 명령과 같은 갈래에 파일 입출력을 더한 것입니다: `unknown_command`(모르는 명령), `bad_actor`(검토자 이름 없음·그래프 없음), `stale`(판·rev·지문이 다름), `conflict`(저장 직전 파일이 바뀜), `unreadable`(집합·결과 파일을 읽을 수 없음, 집합 파일 없음), `read_only`(읽기 전용 집합·결과), `rule`(판정 규칙·잠금·보관 칸·없는 칸), `io`(저장·내보내기 파일을 쓰지 못함). 내보내기의 `OSError`도 예외로 올리지 않고 `io`로 돌려줍니다.

## 4. 명령 표

| 명령 | 인자 | 하는 일 · 명령별 값 | 거절 사유(주요) |
| --- | --- | --- | --- |
| `get_matrix` | — | 구간×편차 칸 요약 `matrix: {node_id: {deviation_id: {state, scenarios, max_risk, unreviewed}}}`. `scenarios`는 기각을 뺀 항목 수, `unreviewed`는 제안·보류와 승인 전 AI 초안 | 결과 파일을 읽을 수 없음 |
| `get_cell` | `node_id, deviation_id` | 칸 하나 `cell`(항목마다 `verdict` 덧붙임), `editable`(보관 칸·잠긴 구간이면 `false`), `node_rev`(쓰는 명령에 넘길 구간 rev) | 없는 칸 |
| `set_status` | `node_id, deviation_id, entry_id, status, reason?, node_rev?` | 판정(§1). '범위 바뀜' 표시를 지움 | 사람 이름 없음 · 판·rev·지문 다름 · 사람이 정할 수 없는 상태 · 사유 없음 · 보관 칸(확정 해제한 구간) · 잠긴 구간 · 없는 항목 · 읽기 전용 결과 |
| `edit_entry` | `node_id, deviation_id, entry_id, fields, reason, node_rev?` | 항목 고치기(판정 '수정', 보류 항목은 보류 그대로). `fields`는 원인·결과·보호수단·권고·강도·빈도·참조·원인 유형·결과 기준. 강도·빈도를 고치면 위험도를 다시 셈 | 위와 같음 · 고칠 수 없는 필드 · 값 범위 밖 · 참조 형식 |
| `recheck_cell` | `node_id, deviation_id, node_rev?` | 범위가 바뀐 칸의 판정을 다시 확인했다고 적음(칸 `scope_changed`를 지움) | 사람 이름 없음 · 지문 다름 · 보관 칸 · 잠긴 구간 |
| `export_excel` | `path, scope?("all"·"approved"·"nodes"), node_ids?` | ⑤ Excel(워크시트에 '상태'·'판정 사유' 열). `path`, `rows` | 쓰기 실패(`io`) |
| `export_ie_bundle` | `path` | IE 인계 묶음 .xlsx와 같은 이름 .json(수용 항목만). `path`, `json_path`, `candidates` | ⑥ 문서 문제 · 쓰기 실패(`io`) |

**분석 실행·멈춤**은 이 명령에 없습니다. AI 호출은 구독 연결의 실행기(`hazop/app/ai_runner.py`, 계획은 `hazop/study/ai_cells.plan_units`)가 맡고, 새 화면은 그 실행기를 `hazop/shell/`에서 감싸 부릅니다. 실행기가 칸을 쓸 때도 같은 결과 파일 지문 대조(`results.save_fp`의 `expect`)를 지켜, 실행 중 사람이 고친 칸을 덮지 않습니다. 잠긴 구간·적용됨 구간은 계획에서 빠집니다.

## 5. 보류가 닿는 곳

| 곳 | 보류 처리 |
| --- | --- |
| 구간 잠금(`nodes.lock_problems`) | 보류 항목이 남으면 잠글 수 없음("보류 항목 N개(결론을 낸 뒤 잠금)") |
| 초기사건 인계(`hazop/ie/bundle.py`, `model.py`) | 넘기지 않음(승인만). 넣지 않은 항목 수에 셈. ⑥ 그룹의 소속 후보가 보류로 바뀌면 '승인 풀림'으로 확정이 풀림 |
| 구간×편차 표 칸 요약(`results.matrix_summary`) | 시나리오에 셈(살아 있음), 미검토에 셈 |
| 권고 추적(Excel '권고' 시트, 탐색기 권고 목록) | 기각만 빼므로 보류 항목의 권고는 남음 |
| Excel(`hazop/export/study_xlsx.py`) | 상태 '보류'(AI 초안이면 '보류 · AI 초안'), 새 열 '판정 사유', 표지 '상태별: 보류' 줄, 수정 이력 요약에 '→보류' |
| 이전 화면(`hazop/app/screens/results.py`, `related.py`) | 글자 '보류'만 더함. 기각·수정 때 사유를 묻는 창(취소하면 저장 안 함). 보류 단추는 두지 않음(새 화면 몫) |
| 채팅 도구 `get_worksheet`(`hazop/chat/tools.py`, c1-tools) | 고치지 않음. 필요한 것: `ENTRY_STATUSES`에 `on_hold`, 항목마다 `results.verdict(e)`의 `reason`·`by`·`at`, `status` 필터 enum에 `on_hold`. 채팅 동작 `results.set_status`(`hazop/chat/actions.py`)의 `RESULT_STATUSES`의 `pending`은 `on_hold`로, 인자에 `reason` |

## 6. Excel 출력의 차이

같은 입력(보류·사유 없는 결과)에서 바뀌는 것은 두 가지입니다. ① 워크시트에 '판정 사유' 열이 '상태' 바로 뒤에 생기고(옛 결과는 빈칸), 그 뒤 열이 한 칸씩 밀립니다. ② 표지에 '상태별: 보류' 줄(0)이 '상태별: 기각' 뒤에 생깁니다. 나머지 값은 같습니다. 열 이름으로 읽는 기존 시험은 그대로 통과하고, 열 순서를 고정한 비교는 없습니다.
