# 구간 명령과 AI 구간 도구 (N3 엔진, 2026-11-13)

새 화면(웹 shell)과 채팅이 부를 검토구간 명령과 읽기 도구를 정리했습니다. 구현은 `hazop/study/node_commands.py`(명령)와 `hazop/study/node_tools.py`(읽기 도구·`apply_nodes`·`undo_batch`)이고, 규칙의 주인은 [검토구간 규격](../../../specs/study-node-segmentation.md)(rev 2)과 [채팅 규격](../../../specs/chat-panel.md) §3.2·§4입니다. 시험은 `tests/test_study_node_tools.py`, `tests/test_study_storage.py`입니다.

## 1. 명령 부르는 법

```python
from hazop.study import node_commands
out = node_commands.execute(pg, "rename", {"node_id": "S3", "name": "충전펌프 토출"}, by="홍길동", set_rev=41)
```

- `pg`: 프로젝트 그래프(`hazop.graph.project.load`). `by`: 검토자 이름(비면 거절). `set_rev`: 화면·채팅이 읽은 집합 판. 저장본과 다르면 거절합니다. `None`이면 대조하지 않습니다(시험용).
- `origin`: `"user"`(화면, 채팅 확인 상자)가 기본입니다. 채팅의 '바로' 동작은 `"ai"`와 `request={"request_id", "request_text", "user_turn", "confirmed_rest"}`를 넘깁니다.
- 실행은 저장본을 읽고(0.1 파일은 이때 0.2로 바뀜), 명령 하나를 적용한 뒤 바뀐 ⑤ 결과 → 집합 순서로 지문을 대조해 저장합니다. 읽은 뒤 파일이 바뀌었으면 쓰지 않고 거절합니다.
- 돌려주는 값은 모든 명령이 같습니다.

| 키 | 뜻 |
| --- | --- |
| `ok` | 실행하고 저장했으면 `true` |
| `command` | 명령 이름 |
| `set_rev` | 실행 뒤 집합 판(거절이면 지금 판). 다음 명령에 넘깁니다 |
| `batch_id` | 만든 묶음 `B<번호>`(확정·잠금 계열은 `null`) |
| `node_ids` | 새로 생긴 구간 ID, 없으면 대상 구간 ID |
| `refused` | 거절 사유 `[{target, reason}]`. `reason`은 화면에 그대로 보일 한국어 문장 |

## 2. 명령 표

| 명령 | 인자 | 하는 일 | 거절 사유(주요) |
| --- | --- | --- | --- |
| `create` | `items: [{cand_id 또는 members, name, design_intent?, basis?, params?}]` | 새 구간(`state: applied`, `origin`은 부른 쪽). 여러 개도 묶음 하나. `cand_id`면 같은 매개변수로 후보를 다시 만들어 구성요소를 얻음(`params`는 캐시가 없을 때 `{granularity, scope, extra_boundaries, cut_at}`) | 이름 없음 · 빈 구간 · 그래프에 없는 구성요소 · 후보를 다시 만들 수 없음(그래프 판·매개변수가 바뀜) · 구성요소가 같은 구간이 이미 있음 · AI: 도면에 없는 태그, 누적 상한(§4) |
| `add_members` | `node_id, members` | 구성요소 더하기(분석 판 `rev`가 오름) | 없는 구간 · 확정·잠금 구간(확정 해제 뒤) · 그래프에 없는 구성요소 · AI: AI가 만든 적용됨 구간만 |
| `remove_members` | `node_id, members` | 구성요소 빼기. 다 빼면 빈 구간이라 거절(지우기는 `remove`) | 위와 같음 · 빈 구간 |
| `rename` | `node_id, name` | 이름 바꾸기(`name_by`가 부른 쪽) | 빈 이름 · 확정·잠금 · AI: 사람이 쓴 이름 |
| `set_design_intent` | `node_id, text` | 설계 의도 `{text, by}`. 빈 글이면 지움. `rev`가 오름 | 확정·잠금 · AI: 사람이 쓴 설계 의도(`by: user`) |
| `merge` | `node_ids`(2개 이상, 첫 구간 ID가 남음) | 합치기. 사라지는 구간의 ⑤ 칸 항목을 남는 구간의 같은 편차 칸으로 옮기고 '범위 바뀜'을 붙임 | 확정·잠금 · AI: 칸에 항목이 있는 구간 |
| `split` | `node_id, members, name?` | 나누기. 떼어 낸 구성요소로 새 구간 | 떼어 낼 것이 그 구간의 일부(전부 아님)가 아님 · 확정·잠금 · AI: 칸에 항목이 있는 구간 |
| `remove` | `node_id, archive?` | 지우기. ⑤ 칸에 판정(항목 또는 analyzed·excluded)이 있으면 `archive: true`일 때만 칸을 결과 파일의 `archived_cells`로 옮기고 지움(사람만) | 확정·잠금 · 판정 있는 칸(보관을 고르지 않음) · AI는 보관 불가 |
| `confirm` | `node_ids` | 확정(`confirmed: {at, by, rev}`). 구간 밖 구성요소는 막지 않음. ⑤ 칸이 생기거나 보관이 풀림 | 사람만 · 이미 확정·잠금 · 빈 구간 · 그래프에 없는 구성요소 · 그래프 판이 바뀜 |
| `unconfirm` | `node_id` | 확정 해제. ⑤ 칸은 지우지 않고 보관(`hold`) | 사람만 · 확정 구간이 아님 · 잠긴 구간(먼저 풀기) |
| `lock` | `node_id` | 분석 마침 · 잠금 | 사람만 · 확정 구간이 아님 · 분석 안 한 칸 · AI 초안 항목 · 범위 바뀜을 다시 확인 안 함 |
| `unlock` | `node_id, reason` | 잠금 풀기(→ 확정). 잠근 동안 판이 바뀌었으면 `rev`가 오름 | 사람만 · 이유 없음 · 잠긴 구간이 아님 |
| `undo` | `batch_id` | 묶음 되돌리기(되돌리기도 새 묶음) | 없는 묶음 · 이미 되돌림 · 그 사이 바뀐 구간 · 확정·잠금 구간 · 구간 삭제인데 칸에 판정 · 편집 복원으로 판이 바뀌는데 사람 판정 · AI가 사람 묶음을 되돌림 |

공통 거절: `set_rev` 다름, 검토구간 파일·⑤ 결과 파일을 읽을 수 없음, 읽기 전용으로 연 집합(0.1 변환을 저장하지 못함), 저장 충돌, 모르는 명령.

## 3. AI 읽기 도구(채팅 도구 목록에 올릴 것)

모두 순수 함수이고 집합을 바꾸지 않습니다. 채팅 계층이 `pg`와 지금 집합(`nodes.load(pg)`)을 넘깁니다.

| 도구 | 인자(JSON 스키마 요약) | 돌려주는 것 | 상한 |
| --- | --- | --- | --- |
| `find_major_equipment` | `scope?: object`, `granularity: "coarse"\|"normal"\|"fine" = "normal"`, `extra_boundaries: string[] = []`, `limit: int = 100`, `cursor?: string` | `{items: [{entity_id, tag, kind, part, drawing}], unrecognized_equipment, total, truncated, next_cursor}` | 200 |
| `make_candidates` | `scope?`, `granularity = "normal"`, `extra_boundaries = []`, `cut_at: string[] = []`, `skip_existing: bool = true`, `limit: int = 30`, `cursor?` | `{candidates: [{cand_id, member_count, start: {tag, entity_id}, end, majors, valves, instruments, drawings, grade, score, overlaps: [{node_id, shared}], basis}], outside: {count, sources}, total, next_cursor, params_digest, set_rev}` | 30 |
| `outside_components` | `scope?`, `only_sources: bool = true`, `limit: int = 100`, `cursor?` | `{items: [{entity_id, tag, kind, drawing}], count, sources, next_cursor}` | 200 |

- `scope`는 하나만: `{"drawings": [도면번호]}` · `{"system": "태그·배관 번호 접두"}` · `{"around": entity_id, "hops": 2}` · `{"node_ids": [..]}`. 모르는 키는 거절.
- `granularity`(규격 §7.1): `coarse`는 원자로용기·증기발생기·가압기·탱크·응축기만 경계(예산 80·상한 120), `normal`은 용기류 전부 + 터빈·압축기(40·60), `fine`은 그에 더해 펌프·필터·제어·안전·릴리프 밸브(20·30). `cut_at`의 구성요소는 경계로 두어 경로를 끊습니다.
- `cand_id`는 (그래프 판, 매개변수 지문, 구성요소 집합)의 해시라 같은 입력이면 같고, 판이 바뀌면 옛 `cand_id`로 적용할 수 없습니다. 범례로 표시한 도면(R0)은 후보를 만들지 않습니다. `skip_existing`이면 이미 있는 구간이 후보 구성요소의 80%를 넘게 품을 때 그 후보를 뺍니다.

## 4. AI 구간 만들기의 누적 상한(채팅 규격 §4.5)

- `pending_ai`: 사람이 아직 손대지 않은 AI 구간 수(AI 묶음이 만들었고, 적용됨이고, 확인 상자로 본 적이 없음). 사람이 고치거나 확정하면 빠집니다.
- 바로 적용: `pending_ai + 이번 요청의 새 구간 수 ≤ 5`(대표 단계). 나누기로 생긴 구간도 셉니다.
- 넘으면 '나머지': `request.confirmed_rest`(사람이 확인 상자를 누름)가 참이고, `request.user_turn`이 확인 안 된 AI 구간을 만든 메시지와 다른 새 사용자 메시지일 때만, 한 요청 30개까지. 그때 앞의 AI 묶음은 `human_seen`이 됩니다.
- 요청 하나는 묶음 하나입니다. 같은 `request_id`로 두 번 적용하면 거절합니다. 묶음에는 `request_id`·`request_text`(500자)·`user_turn`이 남습니다.

## 5. 잰 값

| 일 | 값 | 조건 |
| --- | --- | --- |
| `make_candidates` 첫 쪽(분할 포함, 캐시 없음) | `normal` 중앙 1.83초(1.75~1.88), `coarse` 1.77초, `fine` 1.86초 | APR1400 143장 프로젝트 그래프 사본(구성요소 46,119·관계 45,057), 5회, 실행 뒤 CPU 부하 39%. 스크립트 `D:\HAZOP-trials\2026-11-13-n1-storage-v2\bench_node_tools.py` |
| 다음 쪽(캐시) | 0.065~0.085초 | 같음 |
| `find_major_equipment` | 0.05초(경계 395개, 못 알아본 기기 0) | 같음 |
| `outside_components` | 0.04초 | 같음 |
| 후보 수·최대 크기 | APR: `coarse` 1,349개·120, `normal` 1,811개·60, `fine` 2,442개·30. SNP 6장: `coarse` 23개·93, `normal` 30개·55, `fine` 45개·22 | SNP는 저장소 표본 drawio 6장 |

- SNP `normal` 후보 30개는 rev 0 S1의 29개보다 하나 많습니다. 터빈 하나가 경계가 되었기 때문입니다(규격 V-6). 규격 N3 시험 ①의 '29와 같음'은 V-6 이전 값이라 시험은 '29 + 터빈·압축기 수'로 두었습니다.
- 크기 예산(`coarse` 80·120, `fine` 20·30)은 규격 §7.1의 초기값 그대로이고 위 측정에서 상한을 넘는 후보는 없었습니다. 값을 바꿀지는 규격 주인이 정합니다.
