# 시트 정체(sheet identity) 설계

- 날짜: 2026-11-23
- 성격: 설계(2026-11-23 총괄 승인). 저장소에는 1단계(U1: 이름·자리·고르기) 구현 커밋과 함께 넣었고, 2단계(U2: 가드·등록)는 11장이다. 구현하며 바꾼 것은 9장, 규격은 [DEXPI 가져오기·내보내기](../../../specs/dexpi-exchange.md) §4.3이다.
- 앞선 판: 브랜치 `fix/sheet-gid-collision` 0bef8fe(검토 반려). 그 재현 시험 가운데 U1 몫은 `tests/test_sheet_gid_paths.py`로 옮겼고, 가드 몫은 U2에 넘겼다(8장).
- 쓴 원칙: Attack the Premise(1장), Model the Domain(2장), Make Operations Idempotent·Boundary Discipline(4장)

## 0. 한 줄 결론

시트의 정체는 **사람이 확정한 도면 번호가 있으면 그 번호, 없으면 (자료, 쪽)** 이다. 이름 규칙은 `hazop/graph/sheets.py` 한 곳이 정하고,
이 규칙 전에 쓰던 이름은 프로젝트마다 한 번 '자리(seat)'로 붙박는다(`hazop/graph/sources.settle`). 같은 이름을 여러 자료가 원하면 자리 주인이 이기고, 사람이 고르면 바뀐다.

## 1. 결함과 전제

확정 전 시트의 graph_id는 `graph-<번호|쪽 이름|"drawing">`이었다. 확정 전 벡터 PDF는 모두 `graph-drawing`, drawio는 `graph-<쪽 이름>`, DEXPI는
`graph-<도면 이름>`이라 자료·쪽을 가르지 못했다. 그래서

- 번호 없는 PDF 여러 장을 넣으면 프로젝트 그래프에 한 장만 들어오고, 여러 쪽 PDF 한 파일은 마지막 쪽만 들어왔다.
- 쪽 이름이 같은 drawio·도면 이름이 같은 DEXPI가 겹쳐, 앞 도면 구간의 구성요소가 묘비가 되거나 파일 id가 우연히 같은 다른 도면의 기호로 이어졌다.
- 같은 번호의 drawio·PDF가 섞이면 먼저 있던 형식을 그래프 수정 시각으로 정해, 먼저 있던 drawio를 다시 추출하면 PDF로 넘어갔다.

앞선 고침 둘(0bef8fe의 '먼저 등록한 것을 둔다', 붙박이 초안)은 "같은 graph_id 후보 가운데 하나를 잘 고르면 된다"는 전제를 깔았다. 여러 쪽 PDF는 한 자료 안에서
겹치므로 누구를 골라도 나머지 쪽이 빠진다. 고칠 곳은 고르기가 아니라 **이름을 짓는 곳**이다.

번호를 아예 정체로 쓰지 않고 늘 (자료, 쪽)을 쓰는 안은 버렸다. 개정판을 다른 파일로 넣으면 이름이 달라져 판 이전으로 못 잇고, 이미 있는 `graph-<번호>` 자료를 모두 옮겨야 하며,
HZ-GOV-02 §4.8 '그래프 ID는 사용자 데이터라 바꾸지 않는다'와 어긋난다.

## 2. 데이터 모양

```
시트 정체   (material_id, page_index)                    등록 경로의 모든 추출 결과에 있다(쪽은 0부터)
쓸 수 있는 번호 = 사람이 확정한 번호, 단 자료가 한 쪽일 때만    여러 쪽 자료의 자료 단위 번호는 쪽 번호가 아니다
자연 이름 natural = graph-<번호>                         쓸 수 있는 번호가 있으면
                  = graph-<material_id>-p<쪽>            등록 경로인데 번호가 없으면   예: graph-material-0526d60c252a-p2
                  = graph-<쪽 이름|drawing>               등록 없는 추출(표본 실행·검사 스크립트, 이 규칙 전과 같음)
자리 표 seats[graph_id] = {material_id, page, why: legacy|in_use|chosen, name(폴더), by, at, pin?}   그 이름의 주인
붙박기 pin(자리) = legacy 자리면 그 주인, 아니면 pin 칸 {material_id, page, name}    옛 이름을 지키는 쪽
시트 이름 sheet_id = 쓸 수 있는 번호가 없고 이 (자료, 쪽)을 붙박은 자리가 있으면 그 자리 이름, 아니면 natural
```

자리 규칙은 `hazop.graph.sheets`의 `pin`·`seat`·`unchoose`·`owner_live` 한 곳에 있고, 정착·`keep_owner`·`choose`·`sheet_id`·표제란 가드(`owner_if`)가 함께 쓴다(2026-11-23 E1·E2 고침).

- **주인과 붙박기는 따로다.** 자리를 새로 적으면(`sheets.seat`) 앞 자리의 붙박기를 이어받는다. 사람이 붙박힌 쪽을 고르면(`chosen`) 그 쪽은 옛 이름을 지킨다(E2: 전에는 `chosen`이 `legacy`를 덮어 붙박기가 풀렸다).
  붙박힌 쪽이 아닌 다른 파일을 골라도 붙박기는 남는다(12장). 붙박힌 쪽은 다시 추출하거나 제목만 확정해도 그 이름의 고르기 후보로 남아 다시 고르면 구간이 되돌아온다.
  그 쪽을 따로 보려면 번호를 확정한다(쓸 수 있는 번호가 붙박기를 이긴다). 형식 고르기가 고른 파일을 내려놓으면(`unchoose`) 붙박기는 `legacy` 자리로 남는다.
  고르기가 붙박기를 풀던 앱(12장 전)이 쓴 자리 표에서는 붙박기가 풀린 쪽이 지은 graph.json의 옛 이름으로 보이고(다시 고르면 그 이름의 주인이 됨) 기록도 그 이름을 가리킨다. 그래서 표제란 가드는 쪽의 지금 이름을 규칙으로 셈하지 않고 지은 graph.json에서 읽는다(`titleblock._sheets`, 짓지 않은 쪽만 규칙으로 셈). 전에는 임시 이름으로 세어 옮길 구간을 0개로 알리고 허락하거나(퍼즈 시드 214·246) 이름이 그대로인 확정을 거절했다(시드 155).
- **주인이 그 이름을 떠난 자리는 낡았다(`owner_live`).** 고르기는 그 자리를 보지 않고, 다른 파일이 그 이름을 받기 전에 `keep_owner`가 지금 주인으로 갈아 적는다(E1: 전에는 낡은 `in_use` 자리가 남아 떠났던 파일이 돌아오면 쓰던 파일에게서 말없이 이름을 가져갔다).
  낡음은 기록이 아니라 지금 그 이름을 원하는 (자료, 쪽)으로 판단하므로 어디서 끊겨도 다음 호출이 같은 끝에 닿는다. 붙박기는 낡지 않는다(그 쪽이 번호를 잃으면 옛 이름으로 돌아온다). 다만 그 이름을 다른 파일이 쓰는 사이 돌아오면 주인은 쓰던 파일이고 돌아온 쪽은 고르기 줄에 오른다.
- **새로 추출한 쪽은 쓰이던 이름을 빼앗지 않는다.** 추출이 그래프를 쓰기 전에 그 쪽이 받을 이름을 다른 자료가 쓰고 있으면 그 자료를 `in_use`로 붙박는다(`hazop.app.data._keep_owners` → `keep_owner`).
  먼저 등록했을 뿐 늦게 추출된 자료는 차례 4('먼저 등록한 자료')로 이기지 못하고 고르기 줄(kind file)에 오른다(E5: 전에는 쓰이던 자료의 구간이 묘비가 됐다). 표제란 확정 길은 하지 않는다: 그 쪽 앞 그래프를 비켜 둔 뒤라 디스크로는 주인을 알 수 없고, 새 이름을 쓰는 파일은 가드가 비키기 전에 붙박았다. 확정 중 앱이 죽어 그 쪽에 비켜 둔 그래프(`graph.superseded.json`)만 남고 살아 있는 그래프가 없으면, 비켜 둔 그래프의 이름도 붙박지 않는다(그 쪽이 비켜 두기 직전까지 쓰던 이름).
- **가드는 읽는 길이 보는 값만 센다.** 문서의 판 표지·옮긴 기록(`ref_versions`·`ref_migrations`, 잃은 참조의 옛 값이 글로 남음)은 지난 일이라 세지 않고(`titleblock.PAST_KEYS`),
  판 이전을 따르는 문서(초기사건·FMEA·잠재 후보 판단)는 원문이 아니라 `follow.catch_up`으로 따라간 값으로 센다(E4: 원문에 남은 옛 이름이 그 번호를 영영 막았다).

- 등록 판(r1, r2)은 이름에 넣지 않는다. 표제란 확정이 새 판을 만들어도 같은 시트다.
- `material-<12자>-p<n>` 꼴은 번호로 확정하지 못하게 막는다(사유 코드 `reserved_number`, 입력 검사는 U2).
- 화면의 쪽은 1부터 센다('two.pdf · 2쪽').
- 자리 표는 원본 형식 선택 파일 `data/drawing-sources/<프로젝트>.json`에 `seats`·`seats_settled`로 더한다. 이 파일은 이미 프로젝트 그래프 입력 지문에 들어 있어
  자리가 바뀌면 그래프와 도면 이름 캐시가 다시 지어진다. 그래서 0bef8fe의 이름 캐시 판 올림(1→2)은 들이지 않았다.
- graph.json 머리 `source`에 시트 정체와 이름 근거를 적는다: `material_id`, `registration_version`, `page_index`, `page_count`, `page_name`, `file`(원본 파일 이름), `format`,
  `number`(추출 결과의 번호 그대로). `source.drawing_number`는 **시트 이름에 쓴 번호**만 둔다(여러 쪽 자료의 자료 단위 번호는 `number`에만). 모두 추출 결과에서
  정해지고 `graph_version` 입력이 아니라 판은 그대로다.

## 3. 고르기 차례

한 graph_id를 여러 그래프가 원할 때(`sources.pick`, 프로젝트 그래프·도면 이름·지식그래프 자동 빌드가 같은 함수를 쓴다):

0. (자료, 쪽)마다 가장 새 등록 판 하나만 남긴다(같은 원본을 번호와 함께 다시 등록해도 한 시트). 붙박기(`pin`)의 폴더는 남은 것과 이름이 다르면 남긴다(정착이 보이던 시트를 숨기지 않게).
1. 자료가 하나면 그것.
2. 사람이 고른 파일(`seats[gid].why == chosen`). 사람이 고른 형식(옛 `chosen[번호].format`)이면 그 형식 안에서 3·4.
3. 자리 주인(`legacy`·`in_use`). 2·3은 자리의 주인이 지금 그 이름을 원할 때만 따른다.
4. 먼저 등록한 자료(등록 색인 `registry.json` 차례, 없는 자료는 맨 뒤에 폴더 이름 차례). 그래프 수정 시각은 쓰지 않는다(다시 추출로 뒤집힘).

정착 전 프로젝트(`seats_settled` 없음)는 이 단위 전 규칙 그대로 고르고 이름도 옛 규칙(`sheets.legacy_name`)으로 짓는다. 열기만 한 프로젝트는 이 단위 전과 똑같이 보인다.

## 4. 정착(settle)

```
settle(project_id, render):              # 작업 루트에서만. 이미 seats_settled면 아무것도 쓰지 않음
  지금(옛) 규칙의 고르기 결과마다: gid != natural → legacy 자리, 같은 gid에 다른 자료가 있으면 → in_use 자리
  후보마다 sheet_id(사실, 자리) != 지금 graph_id → render로 다시 지을 파일을 메모리에 만든다(한 시트를 못 만들면 그 시트만 skipped에 사유)
  바꿀 파일(자리 표·다시 지을 폴더의 네 파일)을 data/backup/<시각>-sheet-identity/로 백업
  폴더마다 파일을 원자적으로 씀 → 자리 표를 맨 끝에 원자적으로 씀(읽은 지문과 다르면 Conflict, data.settle_sheets가 한 번 다시 돈다)
```

- 부르는 곳: `data.extract_and_graph` 맨 앞(`data.settle_sheets`) 한 곳. 화면이 프로젝트를 열 때 명시적으로 부르는 일은 U4다.
  `scripts/build_graph.build_one`은 정착하지 않고 자리 표만 읽는다(정착 전 프로젝트는 옛 이름 그대로). 그래서 읽는 길
  (`project_ctx.project_graph`가 낡은 그래프 표시를 보고 다시 짓는 길 포함)·`sources.pick`·`conflicts`·`sheet_rows`·셸 도면 목록은 정착을 일으키지 않는다.
- 정착 전에 옛 검토구간 집합의 판 사진 칸(시트 자료)을 지금 그래프로 채운다(`data.prepare_reextract`). 자리 표가 바뀐 뒤의 판 이전이 시트 자료를 견줄 수 있게.
- 가려진 시트 하나를 다시 짓지 못하면(추출 결과 깨짐 등) 그 시트만 옛 이름으로 두고 `skipped`에 사유를 적어 나머지를 마친다. 사유는 자리 표
  `seats_settled.skipped`에 남고 고르기 줄(`reason: settle_rebuild_failed`)로 보인다. 그 시트를 다시 추출하면 새 이름으로 들어온다.
- 그래프가 아직 없는 새 프로젝트도 정착을 마친 것으로 적는다(붙박을 옛 이름이 없으니 처음부터 새 이름).
- 다시 짓기는 추출을 다시 하지 않는다. graph_version은 그대로이고 이름과 머리 칸만 바뀐다.
- 끊김: 자리 표를 쓰기 전에 끊기면 정착 전 상태로 남는다. 다시 지은 시트는 새 이름이라 옛 규칙으로도 겹치지 않고, 다음 정착이 같은 끝 상태로 간다.
- 정착은 지금 보이던 시트의 이름을 바꾸지 않는다. 가려졌던 시트(첫 PDF, 여러 쪽의 앞쪽)만 새 이름으로 들어오고, 그 이름을 가리키는 기록은 없으므로 잃는 것이 없다.
  이미 겹쳐서 생긴 묘비는 그대로 남는다(drawio 파일 id 정체의 묘비는 표시가 없어 되찾지 못할 수 있다).

## 5. 다른 파일로 갈아탈 때의 판 이전

같은 번호의 다른 파일을 고르면(choose, 또는 주인 파일의 그래프가 사라져 4번 차례로 넘어감) 시트 graph_id는 같고 자료가 바뀐다. 판 이전은 source 근거 구성요소(drawio 파일 id 등)를
`<시트>#<파일 id>` 참조로 잇는데, 다른 파일의 같은 id는 같은 기호라는 증거가 아니다(SNP-M-101과 102의 drawio는 파일 id 일부가 같다). 그래서 `hazop/study/idmap.py`가

- 판 사진에 시트별 자료 `graph_member_sheets {시트 graph_id: material_id}`(프로젝트 그래프 `sheets[].material_id`)를 남기고,
- 옛 사진과 새 그래프의 자료가 다른 시트의 source 구성요소는 참조로 잇지 않으며(표시로 증명하지 못하면 묘비),
- source 묘비 기록에 잃을 때의 시트 자료 `material`을 적고, 자료가 다른 시트에서는 같은 참조·같은 겉모습이어도 되찾지 않는다(그 자료로 돌아가면 되찾는다).
- `material`이 없는 옛 묘비는 이번 판 이전에서 그 시트의 자료가 바뀌었는지만 본다.
- 옛 사진에 그 시트의 자료가 없으면(`graph_member_sheets` 전에 저장) 그 이름을 다른 자료도 원하는 시트(프로젝트 그래프 `sheets[].contested`)에서는
  자료가 바뀌었는지 알 수 없으므로 source 구성요소를 참조로 잇지 않는다(묘비). '빠지면 같다'는 그 이름의 자료가 하나뿐일 때만이다.
  정착·다시 추출 직전에는 그 칸을 채우므로, 이 규칙은 채우기 전에 사람이 파일을 고른 경우에 걸린다.
- 나중에 들인 판 사진 칸(`idmap.OPTIONAL_SNAPSHOT` = `graph_member_looks`·`graph_member_sheets`) 규칙은 하나다. 없는 옛 사진은 `has_snapshot`이 그 칸을 보지 않아
  같은 판을 열기만 해서는 집합을 다시 쓰지 않는다(총괄 조건 5와 같은 쪽). 다시 추출·그래프 다시 짓기 직전의 표지 채우기(`data.prepare_reextract`, `_needs_marks`가 그 칸이 빠진
  집합도 고름)는 `migrate.filling_new_fields()` 안에서 그 칸까지 채운다. 웹 고침 길도 `scripts/build_graph.build_one`에서 이 채우기를 지난다. f945ff2는 looks가 빠진 집합을
  '다르다'로 봐 같은 판 첫 읽기에서 채웠다(열면 다시 씀, 보기 전용 읽기는 needs_open). 그 칸도 이 규칙으로 바꿨다.
- 묘비 지문에는 source 겉모습을 넣지 않고 기록의 `look_key`로 겉모습을 지킨다. 겉모습 칸이 없는 옛 백업으로 되돌린 집합으로 다시 셈해도 같은 잃은 기호는 같은 묘비 id라
  집합과 ⑤ 결과가 한 묘비를 든다(f945ff2 검토 지적 2). f945ff2가 겉모습을 넣어 지은 묘비 id도 알아본다.
- source 묘비를 되찾은 구간의 재확인 사유는 '같은 파일 id·같은 종류로 되찾음'이다(표시로 되찾은 것만 '같은 자리에서').

## 6. 엔진이 돌려주는 값(U4 화면이 읽음)

**고르기 줄** `sources.conflicts(project_id)`:

```
{"kind": "format"|"file", "reason": "same_number_other_format"|"same_number_other_file"|"same_name_before_settle",
 "text": 사람용 한 줄, "graph_id", "drawing_number", "formats",
 "in_use": 지금 쓰는 폴더 이름(셸이 읽던 칸 그대로), "in_use_format", "in_use_material", "in_use_file",
 "chosen": 사람이 고른 형식 또는 None, "chosen_material": 사람이 고른 자료 또는 None,
 "candidates": [{"name", "format", "modified", "material_id", "registration_version", "file", "in_use"}]}
```

- `same_name_before_settle`은 정착 전 프로젝트에서만 나온다(번호 없는 도면이 옛 이름을 나눠 써 하나만 보임). 다음 추출·그래프 짓기에서 없어진다.
- 고르기 `sources.choose(project_id, 번호|graph_id, 형식|None, by, material_id=None)`: 파일을 고르면 `{material_id, page, why: "chosen", name, by, at}`를 돌려준다.
  같은 형식의 다른 파일을 형식으로 고르면 ValueError. 정착 전 프로젝트는 파일을 고르지 못한다(ValueError).

**도면 목록 행** `sources.sheet_rows(project_id)`, 한 줄 `sheets.describe(사실, graph_id)` + 칸:

```
{"graph_id", "label": "SNP-M-101" | "three.pdf · 2쪽", "drawing_number": 이름에 쓴 번호 또는 None,
 "number_state": "confirmed"|"unconfirmed"|"held", "notice": None | {"code", "text"},
 "name": 폴더 이름, "material_id", "page_index", "conflict": 이 이름의 고르기 줄 reason 또는 None}
```

**사유 코드**(`hazop.graph.sheets`):

| 코드 | 언제 | 사람용 글(요지) |
| --- | --- | --- |
| `settle_rebuild_failed` | 고르기 줄: 정착이 가려진 도면을 다시 짓지 못함 | 그 도면을 다시 추출하면 따로 들어옴(사유 포함) |
| `confirm_title_block_first` | 등록 경로 시트에 번호가 없음 | 구간을 만들기 전에 표제란을 확정하면 도면 연결·DEXPI 내보내기·개정판 이어 받기를 쓸 수 있음 |
| `multi_page_number` | 여러 쪽 자료에 자료 단위 번호가 있음(이름에 쓰지 않음). 등록 쪽 보류 사유로도 씀(U2) | 쪽을 파일로 나눠 등록하면 쪽마다 번호를 확정할 수 있음 |
| `reserved_number` | 번호가 임시 이름 꼴 | 임시 이름과 같은 꼴이라 쓸 수 없음 |

등록·표제란이 번호를 받기 전에 묻는 함수는 `sheets.number_problem(번호, 쪽 수)`(None 또는 `{"code", "text"}`)다.

**정착 결과** `data.settle_sheets(project_id)`:

```
{"project_id", "changed", "state": "already"|"settled", "seats", "renamed": [{"name", "from", "to"}],
 "skipped": [{"name", "reason"}](추출 결과가 없어 다시 짓지 못한 폴더), "backup", "backup_files"}
```

프로젝트 그래프에는 `source_notes`(고르기 줄의 `text` 목록)와 `sheets[].material_id`·`page_index`·`label`(번호 없는 등록 시트)·`contested`가 더해진다
(판 문자열에는 넣지 않음).

**사람용 도면 이름 한 곳** `sheets.display_name(시트)`: 번호, 없으면 `label`('파일 · n쪽'), 그것도 없으면 graph-를 뗀 이름, 임시 이름이면 '번호 미확정 도면'.
`study/span.sheet_label`, `kg/screen.py`(지식그래프 화면 묶음 이름), `chat`(카드의 도면 이름)이 이 함수를 쓴다. 표제란 가드의 거절 글도 임시 이름 대신 파일 이름·쪽을 쓴다.
셸에서 임시 이름이 그대로 보일 수 있는 곳(U4, s-viewer 몫, 이 단위는 고치지 않음): `hazop/shell/api_nodes.py` 기본 구간 이름('<graph_id에서 graph-를 뗀 것> 구간'),
`web/js/panels/drawings.js` 도면 목록 행·내보내기 빠진 쪽, `web/js/main.js` 위 막대 도면 칩, `web/js/panels/nodes_logic.js` 구간 패널 도면 이름.

## 7. 시험과 지키는 불변식

| 시험(`tests.`) | 확인하는 것 |
| --- | --- |
| `test_sheet_gid_paths` 두 PDF·세 PDF·3쪽 PDF·drawio 쪽 이름·DEXPI 도면 이름 | 넣은 시트가 모두 들어오고 앞 도면 구간이 그대로(P1·P2·P8, 여러 쪽) |
| `…reextracting_the_first_format…` | 먼저 있던 drawio를 다시 추출해도 PDF로 안 넘어감(P9) |
| `…registering_the_same_file_again…` | 같은 원본을 번호와 함께 다시 등록해도 한 시트(P3 고르기 쪽) |
| `…mixed_formats_and_files…`, `…same_format_other_file…` | 같은 번호의 다른 형식·파일은 말없이 갈아타지 않고 고르기 줄에 오름, 사람이 고르면 갈아탐 |
| `…choosing_another_drawio_file…` | 같은 번호의 다른 drawio로 갈아타도 같은 파일 id로 잇지 않음(묘비) |
| `…saved_collision…`(PDF·drawio) | 이 단위 전에 겹쳐 저장된 프로젝트를 열면 뒤집히지 않고 가려진 도면만 들어옴, 두 번 열어도 같음 |
| `test_sheet_settle` | 읽는 길·다른 그래프 폴더는 쓰지 않음, 정착 전 백업, 두 번 = 한 번, 다시 짓지 못한 시트만 사유와 함께 건너뜀(깨진 가려진 도면이 보이던 도면의 다시 추출을 막지 않음), 옛 집합의 같은 번호 다른 drawio 갈아타기, ⑤·⑥ 참조가 있는 저장본, 임시 이름 시트의 DEXPI 내보내기 |
| `test_sheet_gid_paths` 번호 확정 둘 | 구간 없는 새 도면의 번호 확정은 다른 도면 구간에 막히지 않음(판 사진·판 이전 줄의 도면 목록은 참조로 세지 않음), 거절 글에 임시 이름 대신 파일 이름 |
| `test_sheet_identity` | 이름 규칙·사유 코드·엔진 값의 꼴, 판 이전의 자료 바뀜 규칙(`MaterialSwitchIdmapTest`) |
| `test_study_source_tombs` | f945ff2 검토 지적: 묘비 id가 겉모습 유무와 무관, 재확인 사유, 집합 수준 버린 묘비, 태그 규칙 양쪽, 옛 0.3 집합은 열기만으로 안 씀·다시 추출 직전(웹 길 포함) 채움, 실제 drawio 사람 수정 길의 되찾기 |

설계 퍼즈 불변식(U3가 퍼즈로 묶는다) 가운데 U1이 지키는 것과 그것을 지키는 시험:

| 불변식 | U1 | 지키는 시험(변이를 넣으면 깨질 것) |
| --- | --- | --- |
| 1 시트 유일: (자료, 쪽)마다 시트 하나, graph_id마다 (자료, 쪽) 하나 | 지킴 | 세 PDF·3쪽 PDF(이름 규칙 변이), `…same_file_registered_again…`(차례 0 변이), `RuleTest.test_names` |
| 2 등록 단조: 새 자료를 넣어도 있던 시트의 이름·주인이 안 바뀌고 묘비가 안 늚 | 지킴 | 두 PDF, drawio 쪽 이름, DEXPI, `…same_format_other_file…`·`…mixed_formats…`(차례 3·4 변이) |
| 3 다시 추출 불변 | 지킴 | 두 PDF의 다시 추출, P9(시각으로 고르는 변이) |
| 4 정착 멱등, 보이던 시트 이름 불변 | 지킴 | `test_sheet_settle`의 정착·실패 시험, `…saved_collision…`(legacy 자리 변이) |
| 5 다른 도면으로 안 이음 | 지킴(갈아타기 포함) | `…choosing_another_drawio_file…`, `MaterialSwitchIdmapTest`(시트 자료 검사를 지우는 변이) |
| 6 가드 건전 | U2가 지킴 | 11장의 표(`tests/test_sheet_guard.py`, 변이 16개 모두 잡힘) |

U3(퍼즈)로 넘기는 변이 목록:

- 판 이전 퍼즈(`tests/test_study_migrate_fuzz.py`)에 '같은 시트 graph_id인데 자료가 바뀜'(합성 도면 `sheets[].material_id`를 바꾸고 파일 id를 일부 겹치게)을 넣는다.
  `idmap.compute`의 `moved` 검사나 묘비 `material` 검사를 지우는 변이가 '다른 기호로 이음'으로 잡혀야 한다.
- 같은 파일 id·같은 종류로 돌아온 다른 기호(퍼즈 한계 `LIMIT_SOURCE`)가 700시드에서 0건이다. 생성기가 지운 source 기호 자리에 같은 id로 다른 기호를 그리는 연산을
  더해야 이 한계 셈이 시험된다.
- 시트 정체 불변식 1~5(7장 표)를 등록·확정·다시 추출·고르기·정착 연산을 섞는 퍼즈로 묶는다.

## 8. U2로 넘긴 시험(0bef8fe에서)

U1 커밋에는 넣지 않았다(실패하는 시험·기대 실패를 두지 않음). U2가 가드를 고치며 `tests/test_sheet_guard.py`로 옮겼다(11장).

- `test_guard_counts_fmea_rows`(P4): FMEA 행만 가리켜도 번호 바꾸기를 막음
- `test_guard_counts_sheet_links_in_their_stored_form`(P5): 도면 연결 지정의 끝(번호)만 가리켜도 막음
- `test_numbering_the_left_out_drawing_brings_it_in`: U1 뒤에는 빠진 자료가 없으므로 '둘째 자료도 따로 확정됨'으로 바꿔 씀
- 구간 제외 표시(`구간제외도면.json`)만 가리켜도 막음, 지식그래프 판단 CSV만 가리켜도 막음
- `test_guard_blocks_title_block_number_change_and_unconfirm_with_a_confirmed_node`(P0 가드 고정)
- 여러 쪽 + 자료 번호 등록 보류(`multi_page_number`), 재사용 가지 번호 바꿈 보류(P3 등록 쪽), 예약 꼴 거절(`reserved_number`)
- 정착 전 프로젝트에서 확정 취소를 할 때 예측 이름과 정착 뒤 실제 이름이 다른 경우(표제란 확정 맨 앞에서 정착)

## 9. 구현하며 바꾼 것

- 표제란(`register/titleblock.py`)의 이름 사본 둘(`_graph_id_of`, `_gid`)은 U1에서 `sources.sheet_name`·`name_for`를 부르게 했다.
  사본을 두면 표제란 패널·가드가 새 이름의 시트를 옛 이름으로 세어, 참조가 있는 시트의 번호 바꾸기를 놓친다.
  이름이 바뀌면서 가드가 새 도면의 번호 확정에서도 참조를 세게 되어, 검토구간 집합의 판 사진(그래프 전체 구성요소 목록)과 판 이전 줄의 도면 목록을
  참조로 잘못 세는 회귀가 드러났다(검토 지적). 그 둘은 세지 않게 고쳤다. 주인일 때만 세는 일·FMEA·도면 연결·구간 제외는 U2 그대로다.
- 정착은 읽는 길에서 부르지 않는다(총괄 조건). 이미 겹친 저장본의 가려진 도면은 다음 추출·그래프 짓기, 또는 화면이 프로젝트를 열 때 명시적으로 부르는
  `data.settle_sheets`(U4)에서 들어온다.
- `scripts/build_graph.build_one`을 쓰지 않고 만드는 `render_one`과 쓰는 `build_one`으로 나누고, 파일마다 원자적으로 쓴다. 정착이 다시 지을 것을 모두 만든 뒤 쓰기 위함이다.
- 지식그래프 자동 빌드는 자기 읽기 캐시를 그대로 쓰고 고르기만 `sources.pick`을 부른다(규칙은 한 곳). 옛 알림 '가장 최근 추출만 씀'은 지웠다.
- 판 이전의 자료 바뀜 규칙(5장)은 설계에 없던 것이다. 설계는 '고르기 카드의 미리 셈이 위험을 줄인다'로 받아들였으나 조용히 다른 기호로 잇는 길을 남기지 않으려고 넣었다.
  나누기 되찾기 단위(f945ff2)가 같은 함수에 source 묘비 되찾기를 더해, 그 위에서 그 단위 검토의 비차단 지적(5장 끝 셋, 시험 `tests/test_study_source_tombs.py`,
  판 이전 퍼즈의 옛 꼴 생성기)도 함께 고쳤다.

## 10. 남은 위험

- U1과 U4 사이에는 '같은 번호의 다른 파일'이 고르기 카드 없이 옛 파일을 지킨다. 셸의 옛 원본 고르기 카드는 `kind: file` 줄을 형식 하나짜리 충돌로 보이고, 형식으로 고르면 엔진이 거절한다.
  이 사이에는 배포본을 묶지 않는다.
- `graph_member_sheets`가 없는 옛 집합은 그 이름의 자료가 하나뿐인 시트에서 전처럼 참조로 잇는다. 주인 파일의 그래프가 사라져 남은 다른 파일 하나가 그 이름을 얻고,
  그 사이 집합이 한 번도 다시 쓰이거나 채워지지 않았으면(정착·다시 추출 직전에 채움) 다른 파일의 같은 id로 이을 수 있다. `material`이 없는 옛 묘비도 같은 경우에 되찾을 수 있다.
- 주인 파일의 그래프가 사라지면 4번 차례로 다른 파일이 말없이 그 이름을 얻는다. 판 이전은 5장 규칙으로 묘비를 내지만 알림은 고르기 줄뿐이다.
- 정착이 건너뛴 가려진 시트(`settle_rebuild_failed`)는 그 시트를 다시 추출할 때까지 가려진 채다. 정착은 한 번뿐이라 저절로 다시 시도하지 않는다.
- 정착 전 프로젝트에서 표제란 확정 취소의 예측 이름이 정착 뒤 이름과 다를 수 있었다. U2에서 사람이 승인한 확정이 번호를 바꾸기 전에 정착해 닫았다. dry는 정착하지 않는다(11장).

## 11. 2단계 U2: 가드·등록(2026-11-23)

사용자가 갇히거나(남의 기록 때문에 번호를 못 고침) 가드가 놓치는(기록이 끊기는 바꾸기를 허락) 길을 닫았다. 고친 곳은 `hazop/register/titleblock.py`(가드)와
`hazop/register/registry.py`(등록) 둘이고, 규격은 [표제란 명령](titleblock-commands.md) §2와 [DEXPI 가져오기·내보내기](../../../specs/dexpi-exchange.md) §4.3이다.

**가드(`titleblock._guard_number`).**

- 사람 기록의 **지금 값만** 센다(`_references`). 검토구간 집합은 구성원, 또는 찾지 못한·버린 구성요소(묘비 기록의 `ref`·`lost_from`)가 그 도면인
  구간 수를 세고, 되돌리기 묶음(`batches`)·이력(`history`·`log`)·판 사진(`graph_member_*`)·판 이전 줄의 도면 목록은 세지 않는다. 다른 기록은 이력·기록 줄을 뺀 값 안의 참조 수다.
  첫 판(8abab18, 반려)은 지운 구간의 되돌리기 묶음까지 세어 '그 기록을 먼저 정리하세요'대로 해도 풀리지 않았고(구간 1개가 '구간 12곳'),
  묶음은 50개까지 남아 다른 편집 50번 전에는 풀리지 않았다.
- 앞 이름의 참조는 이 쪽이 그 이름의 지금 주인(프로젝트 그래프가 그 이름에 고른 폴더의 (자료, 쪽))일 때만 센다(`_owns`).
- 새 이름을 다른 파일이 이미 쓰면 그 파일을 주인으로 붙박고(`sources.keep_owner`, 자리 `in_use`) 허락한다. 먼저 있던 파일이 주인으로 남고 고르기 줄에 오른다.
  결과 `notes`에 '도면 번호 X는 이미 다른 파일(…)이 씁니다. 번호를 확정하면 도면 목록에서 어느 파일을 쓸지 고를 수 있고…'를 단다.
  붙박아도 이 쪽이 주인이 되는 경우(사람이 고른 원본 형식이 이 쪽 형식)에만 새 이름의 참조를 세어 막는다(`sources.owner_if`가 미리 셈, 파일을 쓰지 않음).
  첫 판은 남의 도면 구간을 '먼저 정리하세요'로 안내해 표제란 확정만 갇혔다(같은 파일을 명령줄로 번호와 함께 새로 등록하면 됐다, 검토 R7).
  같은 형식의 같은 번호도 같은 길이다(U1이 `kind: file` 고르기 줄을 만들었으므로 '같은 형식이면 막음'은 지웠다). 글자만 다른 번호는 지금처럼 막는다.
  아직 추출하지 않은 자료가 쓰이는 번호를 받아도 주인을 붙박는다(추출하면 그 이름을 함께 원함).
- 아무 파일도 쓰지 않는 새 이름의 참조(그 도면의 그래프가 사라진 기록)는 늘 세어 막는다. 받으면 그 기록이 이 파일의 기호에 붙는다.
- 세는 곳을 더했다: FMEA(`.fmea.json`, P4), 도면 연결 지정의 끝(도면 번호로 적힘, P5), 구간 제외 표시(`구간제외도면.json`, 맨 도면 번호),
  지식그래프 판단 CSV(따옴표 없는 `graph-X:태그`. 판단 열이 있으면 사람이 판단한 행만).
- 번호 꼴은 `sheets.number_problem` 한 곳으로 본다. 여러 쪽 자료의 번호 확정은 `multi_page_number`, 임시 이름 꼴은 `reserved_number`로 막는다. 여러 쪽 자료의
  번호 취소는 이름이 바뀌지 않으므로 막지 않는다.
- **정착은 사람이 승인한 확정에서만.** 정착 전 프로젝트에서 번호를 바꾸면 실제 확정(dry가 아님)이 가드 앞에서 정착한다(`_settle`). dry는 정착하지 않고
  이름으로 셈하는 검사를 건너뛰며 알림(`SETTLE_FIRST_NOTE`)을 단다. 첫 판은 dry도 정착해, 웹 확정 단추와 채팅 제안이 사람 승인 전에 파일 10개를 바꾸고 구간 집합을
  낡음으로 만들었다(총괄 판정으로 되돌림, §4.3 '정착은 명시적인 차례에서만'). 앱을 열 때 정착하므로(b4d0066 `settle_on_open`) 정착 전 프로젝트는 드물다.
  정착이 실패하면 예외 글을 사람용 글에 넣지 않고 기록(로그)에만 남긴다.
- 거절 글의 도면 이름은 번호가 없으면(임시 이름, 정착이 붙박은 옛 이름 `graph-drawing`) '파일 · n쪽'이다. 수는 '구간 n개'·'… n곳'이다.

**번호가 바뀐 뒤 되돌리기 묶음(판단).** 묶음은 버리지 않는다. 번호를 바꾼 뒤 그 앞의 구간 지우기를 되돌리면 옛 이름의 구성원이 돌아오지만, 프로젝트 그래프에
그 이름이 없으므로 찾지 못한 구성요소(사람이 버리거나 다시 고름)로 보인다. 옛 번호를 다른 파일이 받은 뒤 되돌려도 판 이전의 자료 바뀜 규칙(5장)이 그 파일의 기호로
잇지 않는다(재현 시험 둘, 구성원 6개가 모두 찾지 못한 구성요소). 버리지 않는 까닭은 이름 바뀜 잇기(U5)가 옛 이름 → 새 이름을 판 이전으로 이으면 같은 묶음의 구성원이
새 이름으로 돌아올 수 있어서다. U5는 묶음의 `before`·`after` 구성원과 묘비 `ref`를 같은 대응표로 옮기면 된다.

| `reason_code` | 언제 | 사람용 글(요지) |
| --- | --- | --- |
| `sheet_has_records` | 지금 이름(주인일 때)이나 아무도 쓰지 않는 새 이름을 사람 기록이 가리킴 | '이 도면(SNP-M-101)을 가리키는 기록이 있어(구간 1개) 도면 번호를 바꾸면 끊기거나 섞임. 그 기록을 먼저 정리' |
| `confirm_title_block_first` | 번호 없는 도면에 구간 등이 먼저 생김 | '번호가 확정되지 않은 이 도면(<파일 · n쪽>)을 가리키는 기록이 있어(…) 지금 확정하면 끊김(구간 전에 확정하면 이런 일이 없음)' |
| `multi_page_number` | 여러 쪽 자료에 번호 | `sheets.TEXTS` 그대로 |
| `reserved_number` | 임시 이름 꼴 번호 | `sheets.TEXTS` 그대로 |
| `source_choice_pinned` | 앞 번호에 사람이 고른 원본 형식 선택 | '그 선택은 새 번호로 옮겨지지 않음' |
| `number_taken` | 글자만 다른 번호, 또는 사람이 고른 원본 형식 때문에 이 파일이 쓰이는 번호를 차지하게 됨 | '…도면 목록에서 원본 고르기를 먼저 바꾸세요' |

**등록(`registry._register_one`).** 옛 Qt 등록 화면과 명령줄이 모두 지나는 한 곳에서 번호를 받기 전에 묻는다(`_number_hold`, P&ID만).

- 이미 등록한 원본을 **다른** 번호와 함께 다시 등록하면 새 등록 판을 만들지 않고 보류한다(`outcome: on_hold`, `registration_file: null`, 지금 판의 사본에
  `validation.blockers: [{check: "confirm_title_block_first", field: "drawing_number", reason}]`). 글은 '번호는 표제란 확정에서 바꾸세요'다.
  표제란 확정은 가드를 지난 뒤 `register(..., number_checked=True)`로 부른다. 번호가 같은 다시 등록은 번호 꼴도 보지 않고 전처럼 `reused`다(옛 저장본의 여러 쪽 번호 포함, 첫 판 회귀).
- 새 자료의 여러 쪽 번호는 `multi_page_number`, 임시 이름 꼴은 `reserved_number`로 보류한다.
- 마지막 판이 등록 완료가 아니면(첫 등록이 저장 중 끊김) 번호 바꿈 보류를 건너뛴다. 재현해 보니 다시 등록이 그 번호로 등록을 마치고, 그 자료는 추출한 쪽이 없어
  끊길 기록이 없다(시험으로 고정, 결함 아님).

**가드 건전 시험 표**(불변식 6). 변이 검사 `D:\HAZOP-trials\2026-11-14-r3-read-quality\fixflow\migrate2\sheetid\u2\mutate_guard.py`가
고친 코드에 변이를 하나씩 넣어 그 시험이 실패하는지 본다(16개 모두 잡힘, `out_mutate2.log`).

| 지키는 것 | 시험(`tests.test_sheet_guard.`) | 잡는 변이 |
| --- | --- | --- |
| 구간이 있는 도면은 번호 바꾸기·취소가 막히고 구간이 그대로(P0) | `GuardOwnerTest.test_guard_blocks_title_block_number_change_and_unconfirm_with_a_node` | 주인도 안 세기 |
| FMEA 행(P4) | `GuardCountsTest.test_guard_counts_fmea_rows` | FMEA 자리 빼기 |
| 도면 연결 지정의 끝(P5) | `…test_guard_counts_sheet_links_in_their_stored_form` | 끝 세지 않기 |
| 구간 제외 표시 | `…test_guard_counts_the_excluded_drawing_mark` | 표시 세지 않기 |
| 지식그래프 판단 CSV, 판단 전 후보는 막지 않음 | `…test_guard_counts_knowledge_graph_judgements_in_csv` | CSV 세지 않기, 후보도 세기 |
| 주인이 아닌 같은 번호 파일은 번호를 고침, 주인은 막힘 | `GuardOwnerTest.test_other_file_with_the_same_number_can_change_its_number` | 늘 세기 |
| 쓰이는 번호를 받으면 먼저 있던 파일이 주인으로 남음 | `…test_another_file_can_take_a_number_in_use_and_the_first_file_stays` | 주인 붙박기 빼기 |
| 아무도 쓰지 않는 번호의 기록은 막음 | `…test_taking_a_number_whose_records_have_no_drawing_is_refused` | 새 이름 참조 안 세기 |
| 구간을 지우면 번호를 확정할 수 있고 수는 구간 수 | `…test_removing_the_segment_lets_the_number_be_confirmed` | 되돌리기 묶음도 세기 |
| 번호를 바꾼 뒤 되돌리기는 찾지 못한 구성요소로, 다른 도면에 안 붙음 | `…test_undoing_a_removal_after_the_number_changed_shows_the_members_as_not_found`, `…test_undo_after_the_old_number_went_to_another_file_does_not_attach_to_it` | - |
| 정착 전 저장본의 가려진 도면은 번호로 들어오고 주인은 막힘 | `…test_left_out_second_drawing_can_be_numbered` | (정착·주인 검사 둘 다 지워야 깨짐) |
| 정착 전 확정 취소는 실제 확정이 정착한 뒤 셈하고 dry는 쓰지 않음 | `…test_unconfirm_before_settle_uses_the_settled_name` | 정착 빼기 |
| dry·채팅 제안은 정착 전에도 아무것도 쓰지 않음 | `DryTest.test_dry_and_the_chat_proposal_write_nothing_before_settle` | dry가 정착 |
| 정착 실패 글에 예외 글 없음 | `DryTest.test_settle_failure_is_told_in_plain_words` | - |
| 임시 이름 꼴 번호 거절·보류 | `NumberRuleTest.test_reserved_number_is_refused_by_the_title_block_and_held_by_registration` | 번호 꼴 검사 빼기 |
| 여러 쪽 자료 번호 등록 보류 | `…test_multi_page_pdf_with_a_number_is_held_at_registration` | 등록 여러 쪽 보류 빼기 |
| 여러 쪽 PDF를 같은 번호로 다시 등록하면 reused | `…test_registering_a_multi_page_pdf_again_with_its_old_number_is_reused` | 번호 안 바꾼 다시 등록도 보류 |
| 끝나지 않은 첫 등록의 다시 등록은 번호로 마침 | `…test_retrying_an_unfinished_first_registration_with_a_number_completes` | - |
| 여러 쪽 번호 확정 거절, 받아 둔 번호 취소는 됨 | `…test_multi_page_number_is_refused_but_a_held_number_can_be_cleared` | - |
| 재사용 가지의 번호 바꿈 보류(P3 등록 쪽), 보류는 등록정보 경로를 돌려주지 않음 | `…test_registering_the_same_file_again_with_another_number_is_held` | 재사용 가지 보류 빼기 |
| 거절에 사유 코드, 글에 내부 말·'쪽를'·옛 이름 없음 | `RefusalWordsTest.test_refusals_carry_a_code_and_plain_words` | - |

**남은 일.**

- 번호 미확정 도면에 구간을 먼저 만들면 그 도면의 번호는 구간을 정리하기 전에는 확정하지 못한다(`confirm_title_block_first`). 그래프 ID를 옮기는 길(U5)이 생기면 풀린다.
  화면이 구간을 만들기 전에 알림(도면 목록 행 `notice`)을 보이는 일은 U4다.
- 사람이 고른 원본 형식이 이 파일 형식이면, 쓰이는 번호를 받을 때 이 파일이 주인이 되므로 그 도면에 기록이 있으면 막힌다(`number_taken`). 원본 고르기를 먼저 바꾸면 된다.
- 정착 전 프로젝트의 dry는 이름 검사를 건너뛰므로, dry가 통과해도 실제 확정이 정착 뒤 검사에서 거절할 수 있다(작업이 거절로 끝남, 데이터는 그대로).

## 12. 되찾기: 다른 파일을 골랐다가 다시 고르기(2026-11-24)

**결함.** 옛 자리 주인 a(번호 없는 drawio, 옛 이름 `graph-SNP-M-101`)에 구간이 있는 채 같은 번호의 b를 고르면 a의 구성요소는 묘비가 된다. 고르기 카드는
'다시 고르면 바로 되돌아옵니다'라고 약속한다. 그런데 고르기가 a의 붙박기를 풀었으므로, 그 뒤 a를 다시 추출하거나 제목만 확정하면 a는 임시 이름으로 옮겨 가고
그 이름의 고르기 줄이 사라졌다. 두 길 모두 아무 알림 없이 허락됐고(`carries`·`carries_lost` 비어 있음) a를 다시 고를 길이 없어 묘비가 영구히 남았다.
재현은 `tests/test_sheet_identity_regress.py`의 `test_choosing_back_after_*` 둘이다.

**견준 두 안.**

| 안 | 내용 | 판정 |
| --- | --- | --- |
| 가. 붙박기를 남겨 되찾기 길을 지킨다 | `sheets.seat`가 사람이 다른 파일을 골라도 앞 자리의 붙박기를 이어받는다. a는 다시 추출·제목 확정 뒤에도 옛 이름으로 지어져 그 이름의 후보로 남고, 다시 고르면 같은 자료로 돌아온 시트에서 5장 규칙이 묘비를 되찾는다 | 고름 |
| 나. 세어서 미리 알리고 막는다 | 다시 추출·제목 확정이 되돌릴 수 없게 만들 묘비 수를 `carries_lost`로 세어 dry가 알리고 확정은 막거나 확인을 받는다 | 버림 |

가를 고른 까닭. 자리 규칙은 이미 '주인과 붙박기는 따로다'(2장)인데, 고르기만 그 둘을 묶어 붙박기를 풀었다. 가는 그 예외 한 줄을 지운다. 자리 표 꼴·고르기 차례(3장)·
정착(4장)·`owner_live`·`keep_owner`·`unchoose`는 그대로이고, 이름이 바뀌는 길이 하나 줄어 시드 155·214·246 꼴(지은 이름과 규칙 이름이 어긋난 틈)도 새로 생기지 않는다.
붙박힌 쪽은 고르기 카드에 후보로 남으므로 도면 목록에 따로 보이지 않는다. 같은 이름을 원하는 번호 붙은 파일과 붙박힌 쪽이 함께 있는 이름은 옛 쪽 이름이 그 번호와
같았던 경우뿐이라 대개 같은 도면의 다른 형식이고, 따로 보려면 번호를 확정하면 된다.
나를 버린 까닭. 다시 추출은 막을 수 없는 차례라 알림만 남고, 제목 확정을 막으면 묘비를 되찾지 못하는 채 사람이 할 일만 늘어난다. 카드의 약속도 지키지 못한다.

**알려진 결함 E6(고치지 않음, `hazop/study/idmap.compute`).** 같은 기호(같은 자료·쪽·파일 id)가 두 이름에서 묘비가 되면(옛 이름에서 한 번, 그 쪽이 잠시
보이던 다른 이름에서 한 번) 다시 고를 때 두 묘비가 한 구성요소를 다투고, '묘비 둘이 한 구성요소를 다투면 둘 다 못 찾는다' 규칙으로 둘 다 묘비로 남는다.
가로 고친 길(다시 추출·제목 확정)은 그 쪽이 다른 이름으로 보이지 않으므로 걸리지 않는다. 걸리는 길은 b를 고른 뒤 a가 번호를 취소했다가(임시 이름으로 보임) 같은 번호를
다시 확정하고 a를 다시 고르는 것이고, 시험 `test_e6_*` 둘이 expectedFailure로 재현한다. 두 묘비의 자료·쪽·파일 id가 모두 같으면 같은 기호라는 증명이므로,
그 경우는 다투지 않는 것으로 보아 둘 다 되찾으면 된다(판 이전 쪽 단위 몫).

**이미 갇힌 프로젝트.** 고르기가 붙박기를 풀던 앱에서 a를 다시 추출한 프로젝트는 a가 임시 이름에 있고 묘비가 옛 이름에 남아 있다. 자동 되찾기는 하지 않는다.
a를 옛 이름으로 되돌리려면 a의 이름을 바꿔야 하고(그 사이 임시 이름에 생긴 기록이 있으면 끊김), 그 판단은 표제란 가드를 지나는 사람의 확정 몫이다.
사람의 길은 a에 b와 같은 번호를 확정한 뒤 고르기 카드에서 a를 고르는 것이다(가드가 a의 임시 이름 기록을 센다). 그 길은 a가 잠시 임시 이름으로 보였던 탓에
E6에 걸려 지금은 묘비가 돌아오지 않는다(`test_e6_a_stuck_project_*`). E6을 고치면 같은 길로 되찾는다.

**확정 거절 글 `titleblock.NOT_OWNER`.** 새 번호를 다른 파일이 쓰고 이 쪽이 그 번호의 주인이 되지 못하는데 이 쪽에 옮길 기록이 있을 때의 글이다. 전에는 '도면 목록에서
원본을 먼저 고르세요'라고 했지만, 확정 전에는 그 번호의 고르기 줄에 이 쪽이 없어 할 수 없는 일이다. 형식을 먼저 골라도 같은 형식의 다른 파일이 붙박혀 이 쪽이 주인이
되지 않는다. 그래서 글은 남은 길(다른 번호를 쓰기, 그 번호를 쓰는 파일의 번호를 먼저 바꾸기, 기록을 정리하기)만 알리고 그 파일 이름을 밝힌다. 사유 코드는 그대로다.
