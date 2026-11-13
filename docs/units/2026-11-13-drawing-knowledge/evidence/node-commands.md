# 구간 명령과 AI 구간 도구 (N3 엔진, 2026-11-13)

새 화면(웹 shell)과 채팅이 부를 검토구간 명령과 읽기 도구를 정리했습니다. 구현은 `hazop/study/node_commands.py`(명령)와 `hazop/study/node_tools.py`(읽기 도구·`apply_nodes`·`undo_batch`)이고, 규칙의 주인은 [검토구간 규격](../../../specs/study-node-segmentation.md)(rev 2)과 [채팅 규격](../../../specs/chat-panel.md) §3.2·§4입니다. 시험은 `tests/test_study_node_tools.py`(도구·명령)와 `tests/test_study_storage.py`(저장 규격 v2. 처음 이름은 `tests/test_study_nodes_v2.py`였고 이름 규칙 N7 때문에 c0d49be에서 바꿈)입니다.

## 1. 명령 부르는 법

```python
from hazop.study import node_commands
# 사람이 웹 화면에서
out = node_commands.execute(pg, "rename", {"node_id": "S3", "name": "충전펌프 토출"},
                            author="user", confirmed_by="홍길동", set_rev=41)
# 채팅의 AI 동작: 바로 실행이면 confirmed_by 없음, 확인 상자를 눌렀으면 누른 사람
out = node_commands.execute(pg, "create", {"items": [{"cand_id": "c-…", "name": "…", "design_intent": "…"}]},
                            author="ai", confirmed_by=None, set_rev=41,
                            request={"request_id": "q-…", "request_text": "…", "user_turn": "u-…", "confirmed_rest": False})
node_commands.recover(pg)   # 화면을 열 때 한 번: 끊긴 명령의 ⑤ 결과 쓰기를 마저 함
```

- `pg`: 프로젝트 그래프(`hazop.graph.project.load`). `set_rev`: 화면·채팅이 읽은 집합 판. 저장본과 다르면 거절(`stale`). `None`이면 대조하지 않습니다(시험용).
- **`author`(누가 썼나, 키워드 인자, 기본값 없음)**: `"user"`는 사람이 화면에서 한 일, `"ai"`는 채팅에서 AI가 낸 동작입니다. AI가 쓴 동작은 사람이 확인 상자를 눌러도 `origin: ai`·`name_by: ai`(설계 의도는 `by: ai`)로 저장하고 AI 누적 상한(§4)에 셉니다. 빠지거나 다른 값이면 거절(`bad_actor`).
- **`confirmed_by`(누가 눌렀나)**: 사람 이름. `author="user"`와 확정·확정 해제·잠금·풀기에는 꼭 있어야 합니다(없으면 `bad_actor`). AI 동작에서는 사람이 확인 상자를 눌렀을 때만 넣습니다. 그때만 AI가 사람 구간(`origin: user·script`)이나 사람이 쓴 이름·설계 의도를 고치는 동작과 '나머지' 단계가 열립니다. 웹 화면은 검토자 이름을 설정에서 읽어 넘깁니다.
- 시각(`at`)은 엔진이 채웁니다. 확정·확정 해제·잠금·풀기는 `author="user"`만 됩니다.
- `request`(AI 동작만): `request_id`(요청 하나 = 묶음 하나), `request_text`(500자), `user_turn`(사용자 메시지 ID), `confirmed_rest`(사람이 '나머지' 확인 상자를 누름).
- **저장 순서.** 바뀐 ⑤ 결과를 먼저 옆 파일 `<결과 파일>.pending.json`에 '이 집합 지문을 위한 것'으로 적고 → 집합을 지문 대조로 쓰고 → 결과를 지문 대조로 씁니다. 집합 쓰기가 막히면(`conflict`) 결과는 바뀌지 않습니다. 집합을 쓴 뒤 결과를 쓰기 전에 끊기면, 다음 명령이나 `recover(pg)`가 옆 파일의 집합 지문과 옛 결과 지문이 모두 지금 파일과 맞을 때만 결과를 마저 씁니다.
- 돌려주는 값은 모든 명령이 같습니다. **`ok`가 `false`면 아무것도 저장하지 않은 것**이니 성공으로 기록하지 않습니다.

| 키 | 뜻 |
| --- | --- |
| `ok` | 실행하고 저장했으면 `true` |
| `command` | 명령 이름 |
| `set_rev` | 실행 뒤 집합 판(거절이면 지금 판). 다음 명령에 넘깁니다 |
| `changed` | 저장한 것이 있으면 `true`. 바뀐 것이 없는 편집(구간에 없는 구성요소 빼기, 같은 이름·같은 설계 의도)은 `ok: true`, `changed: false`이고 아무 파일도 쓰지 않음(묶음·`set_rev`·이력 그대로) |
| `batch_id` | 만든 묶음 `B<번호>`(확정·잠금 계열과 바뀐 것이 없는 편집은 `null`). 앞 묶음 ID를 돌려주는 일은 없음 |
| `node_ids` | 새로 생긴 구간 ID, 없으면 대상 구간 ID |
| `refused` | 거절 사유 `[{target, code, reason}]`. `code`로 갈래를 나누고 `reason`(한국어 문장)은 화면에 그대로 보임 |

거절 코드(`code`):

| 코드 | 뜻 | 부르는 쪽이 할 일 |
| --- | --- | --- |
| `unknown_command` | 모르는 명령 | 명령 이름 확인 |
| `bad_actor` | `author`가 없거나 틀림, 사람 이름이 필요한데 없음, AI가 사람만 하는 명령을 부름 | 서명 확인. 채팅은 사람이 할 곳을 안내 |
| `stale` | `set_rev`가 저장본과 다름 | 다시 읽고 다시 묻기 |
| `conflict` | 읽은 뒤 파일이 바뀌었거나 쓰기 실패(아무것도 저장 안 됨) | 다시 읽고 다시 하기 |
| `unreadable` | 검토구간·⑤ 결과 파일을 읽을 수 없음 | 파일 문제 안내 |
| `read_only` | 0.1 변환을 저장하지 못해 읽기 전용 | 안내만 |
| `rule` | 규칙에 걸림(아래 표의 사유) | `reason`을 그대로 보임 |

### 읽기와 열기

| 함수 | 쓰는가 | 하는 일 |
| --- | --- | --- |
| `nodes.load_view(pg)` → `(집합 또는 None, {needs_open, reason, notice})` | 아무것도 쓰지 않음 | 보기 전용. 0.1 파일은 메모리에서 0.2로 바꾸고, 0.2 파일은 판 이전·참조 채우기를 메모리에서만 적용한다. 그런 일이 있으면 `needs_open: true`, 집합에 `read_only`, `notice`는 판 이전 안내(`migrate.notice`) |
| `results.load_view(node_set)` → 결과 또는 None | 아무것도 쓰지 않음 | 보기 전용 ⑤ 결과. 옛 판(0.1·0.2)이면 `read_only`(열면 바꿈) |
| `nodes.load_fp(pg)` → `(집합, 지문)` | 변환·판 이전을 쓰고 원본을 보관 | 편집용 열기. `node_commands.execute`가 안에서 부름 |
| `results.load_fp(node_set)` → `(결과, 지문)` | 옛 판이면 원본 보관(`.v0.1.bak.json`·`.v0.2.bak.json`) | 편집용 열기 |

새 화면은 목록·도면을 그릴 때 `load_view`를 쓰고, `needs_open`이면 `notice`(또는 `reason`)를 보인 뒤 사용자가 고치려 할 때(또는 '열기'를 누를 때) `load_fp`로 한 번 연다.

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
| `unconfirm` | `node_ids` | 확정 해제(구간마다, 하나라도 막히면 아무것도 바꾸지 않음). ⑤ 칸은 지우지 않고 보관(`hold`) | 사람만 · 확정 구간이 아님 · 잠긴 구간(먼저 풀기) |
| `lock` | `node_ids` | 분석 마침 · 잠금(구간마다) | 사람만 · 확정 구간이 아님 · 분석 안 한 칸 · AI 초안 항목 · 범위 바뀜을 다시 확인 안 함 |
| `unlock` | `node_ids, reason` | 잠금 풀기(→ 확정). 잠근 동안 판이 바뀌었으면 `rev`가 오름 | 사람만 · 이유 없음 · 잠긴 구간이 아님 |
| `undo` | `batch_id` | 묶음 되돌리기(되돌리기도 새 묶음) | 없는 묶음 · 이미 되돌림 · 그 사이 바뀐 구간 · 확정·잠금 구간 · 구간 삭제인데 칸에 판정 · 편집 복원으로 판이 바뀌는데 사람 판정 · AI가 사람 묶음을 되돌림 · AI가 사람이 확정한 적 있는 구간을 되돌림 |

공통 거절: `set_rev` 다름, 검토구간 파일·⑤ 결과 파일을 읽을 수 없음, 읽기 전용으로 연 집합(0.1 변환을 저장하지 못함), 저장 충돌, 모르는 명령.

## 3. AI 읽기 도구(채팅 도구 목록에 올릴 것)

모두 순수 함수이고 집합을 바꾸지 않습니다. 채팅 계층이 `pg`와 지금 집합(`nodes.load(pg)`)을 넘깁니다.

| 도구 | 인자(JSON 스키마 요약) | 돌려주는 것 | 상한 |
| --- | --- | --- | --- |
| `find_major_equipment` | `scope?: object`, `granularity: "coarse"\|"normal"\|"fine" = "normal"`, `extra_boundaries: string[] = []`, `limit: int = 100`, `cursor?: string` | `{items: [{entity_id, tag, kind, part, drawing}], unrecognized_equipment, total, truncated, next_cursor}` | 200 |
| `make_candidates` | `scope?`, `granularity = "normal"`, `extra_boundaries = []`, `cut_at: string[] = []`, `skip_existing: bool = true`, `limit: int = 30`, `cursor?` | `{candidates: [{cand_id, member_count, start: {tag, entity_id}, end, majors, valves, instruments, drawings, grade, score, overlaps: [{node_id, shared}], basis}], outside: {count, sources}, total, next_cursor, params_digest, set_rev}` | 30 |
| `outside_components` | `scope?`, `only_sources: bool = true`, `limit: int = 100`, `cursor?` | `{items: [{entity_id, tag, kind, drawing}], count, sources, next_cursor}` | 200 |

- `scope`는 하나만: `{"drawings": [도면번호]}` · `{"system": "태그·배관 번호 접두"}` · `{"around": entity_id, "hops": 2}`(hops 0~30) · `{"node_ids": [..]}`. 모르는 키는 거절.
- `granularity`(규격 §7.1): `coarse`는 원자로용기·증기발생기·가압기·탱크·응축기만 경계(예산 80·상한 120), `normal`은 용기류 전부 + 터빈·압축기(40·60), `fine`은 그에 더해 펌프·필터·제어·안전·릴리프 밸브(20·30). `cut_at`의 구성요소는 경계로 두어 경로를 끊습니다.
- `cand_id`는 `c-<매개변수 지문 16자>-<(그래프 판, 지문, 구성요소 집합) 해시 12자>`라 같은 입력이면 같고, 판이 바뀌면 옛 `cand_id`로 적용할 수 없습니다. 후보를 만들 때 매개변수를 `<작업 루트>/data/study-nodes/<프로젝트>/candidates/<지문>.json`에 원자적으로 남겨, 후보를 만든 프로세스(채팅 도구 서버)와 적용하는 프로세스(앱)가 달라도 `cand_id`만으로 후보를 다시 만듭니다. 기록은 24시간까지 믿고, 지나면 "후보를 다시 만들 수 없음"으로 거절해 AI가 후보를 다시 찾게 합니다. 범례로 표시한 도면(R0)은 후보를 만들지 않습니다. `skip_existing`이면 이미 있는 구간이 후보 구성요소의 80%를 넘게 품을 때 그 후보를 뺍니다.

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
| 구간 525개가 있을 때 첫 쪽(겹침 계산 포함) | `normal`, `skip_existing` 켬 중앙 1.38초(1.31~1.44), 끔 1.35초. 다음 쪽 0.05초 | 같은 사본에 `fine` 후보 525개를 구간으로 넣음. 5회, 실행 뒤 CPU 부하 53%. 겹침은 구성요소 → 구간 색인으로 셈. 스크립트 `bench_overlap.py` |
| `find_major_equipment` | 0.05초(경계 395개, 못 알아본 기기 0) | 같음 |
| `outside_components` | 0.04초 | 같음 |
| 후보 수·최대 크기 | APR: `coarse` 1,349개·120, `normal` 1,811개·60, `fine` 2,442개·30. SNP 6장: `coarse` 23개·93, `normal` 30개·55, `fine` 45개·22 | SNP는 저장소 표본 drawio 6장 |

- SNP `normal` 후보 30개는 rev 0 S1의 29개보다 하나 많습니다. 터빈 하나가 경계가 되었기 때문입니다(규격 V-6). 규격 N3 시험 ①의 '29와 같음'은 V-6 이전 값이라 시험은 '29 + 터빈·압축기 수'로 두었습니다.
- 크기 예산(`coarse` 80·120, `fine` 20·30)은 규격 §7.1의 초기값 그대로이고 위 측정에서 상한을 넘는 후보는 없었습니다. 값을 바꿀지는 규격 주인이 정합니다.
