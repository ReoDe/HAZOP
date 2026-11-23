# 시트 정체(sheet identity) 설계

- 날짜: 2026-11-23
- 성격: 설계(2026-11-23 총괄 승인). 저장소에는 1단계(U1: 이름·자리·고르기) 구현 커밋과 함께 넣었다. 구현하며 바꾼 것은 9장, 규격은 [DEXPI 가져오기·내보내기](../../../specs/dexpi-exchange.md) §4.3이다.
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
자리 표 seats[graph_id] = {material_id, page, why: legacy|in_use|chosen, name(폴더), by, at}
시트 이름 sheet_id = 쓸 수 있는 번호가 없고 이 (자료, 쪽)이 legacy 자리를 가지면 그 자리 이름, 아니면 natural
```

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

0. (자료, 쪽)마다 가장 새 등록 판 하나만 남긴다(같은 원본을 번호와 함께 다시 등록해도 한 시트). legacy 자리가 붙박은 폴더는 남은 것과 이름이 다르면 남긴다(정착이 보이던 시트를 숨기지 않게).
1. 자료가 하나면 그것.
2. 사람이 고른 파일(`seats[gid].why == chosen`). 사람이 고른 형식(옛 `chosen[번호].format`)이면 그 형식 안에서 3·4.
3. 자리 주인(`legacy`·`in_use`).
4. 먼저 등록한 자료(등록 색인 `registry.json` 차례, 없는 자료는 맨 뒤에 폴더 이름 차례). 그래프 수정 시각은 쓰지 않는다(다시 추출로 뒤집힘).

정착 전 프로젝트(`seats_settled` 없음)는 이 단위 전 규칙 그대로 고르고 이름도 옛 규칙(`sheets.legacy_name`)으로 짓는다. 열기만 한 프로젝트는 이 단위 전과 똑같이 보인다.

## 4. 정착(settle)

```
settle(project_id, render):              # 작업 루트에서만. 이미 seats_settled면 아무것도 쓰지 않음
  지금(옛) 규칙의 고르기 결과마다: gid != natural → legacy 자리, 같은 gid에 다른 자료가 있으면 → in_use 자리
  후보마다 sheet_id(사실, 자리) != 지금 graph_id → render로 다시 지을 파일을 메모리에 만든다(실패하면 아무것도 안 씀)
  바꿀 파일(자리 표·다시 지을 폴더의 네 파일)을 data/backup/<시각>-sheet-identity/로 백업
  폴더마다 파일을 원자적으로 씀 → 자리 표를 맨 끝에 원자적으로 씀(읽은 지문과 다르면 Conflict, data.settle_sheets가 한 번 다시 돈다)
```

- 부르는 곳: `data.extract_and_graph` 맨 앞, 그래프를 앱 작업 루트에 짓는 `scripts/build_graph.build_one`(사람 수정 저장·AI 수락 뒤 다시 짓기·낡은 그래프 다시 짓기가 모두 지난다).
  읽는 길(`project_ctx.project_graph`·`graph_names`, `sources.pick`·`conflicts`·`sheet_rows`, 셸 도면 목록)에서는 부르지 않는다.
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
- `material`이 없는 옛 묘비는 이번 판 이전에서 그 시트의 자료가 바뀌었는지만 본다. `graph_member_sheets`가 없는 옛 사진은 전처럼 참조로 잇는다(10장 남은 위험).
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
| `confirm_title_block_first` | 등록 경로 시트에 번호가 없음 | 구간을 만들기 전에 표제란을 확정하면 도면 연결·DEXPI 내보내기·개정판 이어 받기를 쓸 수 있음 |
| `multi_page_number` | 여러 쪽 자료에 자료 단위 번호가 있음(이름에 쓰지 않음). 등록 쪽 보류 사유로도 씀(U2) | 쪽을 파일로 나눠 등록하면 쪽마다 번호를 확정할 수 있음 |
| `reserved_number` | 번호가 임시 이름 꼴 | 임시 이름과 같은 꼴이라 쓸 수 없음 |

등록·표제란이 번호를 받기 전에 묻는 함수는 `sheets.number_problem(번호, 쪽 수)`(None 또는 `{"code", "text"}`)다.

**정착 결과** `data.settle_sheets(project_id)`:

```
{"project_id", "changed", "state": "already"|"settled", "seats", "renamed": [{"name", "from", "to"}],
 "skipped": [{"name", "reason"}](추출 결과가 없어 다시 짓지 못한 폴더), "backup", "backup_files"}
```

프로젝트 그래프에는 `source_notes`(고르기 줄의 `text` 목록)와 `sheets[].material_id`·`page_index`가 더해진다(판 문자열에는 넣지 않음).

## 7. 시험과 지키는 불변식

| 시험(`tests.`) | 확인하는 것 |
| --- | --- |
| `test_sheet_gid_paths` 두 PDF·세 PDF·3쪽 PDF·drawio 쪽 이름·DEXPI 도면 이름 | 넣은 시트가 모두 들어오고 앞 도면 구간이 그대로(P1·P2·P8, 여러 쪽) |
| `…reextracting_the_first_format…` | 먼저 있던 drawio를 다시 추출해도 PDF로 안 넘어감(P9) |
| `…registering_the_same_file_again…` | 같은 원본을 번호와 함께 다시 등록해도 한 시트(P3 고르기 쪽) |
| `…mixed_formats_and_files…`, `…same_format_other_file…` | 같은 번호의 다른 형식·파일은 말없이 갈아타지 않고 고르기 줄에 오름, 사람이 고르면 갈아탐 |
| `…choosing_another_drawio_file…` | 같은 번호의 다른 drawio로 갈아타도 같은 파일 id로 잇지 않음(묘비) |
| `…saved_collision…`(PDF·drawio) | 이 단위 전에 겹쳐 저장된 프로젝트를 열면 뒤집히지 않고 가려진 도면만 들어옴, 두 번 열어도 같음 |
| `test_sheet_settle` | 읽는 길·다른 그래프 폴더는 쓰지 않음, 정착 전 백업, 실패하면 옛 상태 그대로, 두 번 = 한 번 |
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
| 6 가드 건전 | U2 | U2 시험 |

U3(퍼즈)로 넘기는 변이 목록:

- 판 이전 퍼즈(`tests/test_study_migrate_fuzz.py`)에 '같은 시트 graph_id인데 자료가 바뀜'(합성 도면 `sheets[].material_id`를 바꾸고 파일 id를 일부 겹치게)을 넣는다.
  `idmap.compute`의 `moved` 검사나 묘비 `material` 검사를 지우는 변이가 '다른 기호로 이음'으로 잡혀야 한다.
- 같은 파일 id·같은 종류로 돌아온 다른 기호(퍼즈 한계 `LIMIT_SOURCE`)가 700시드에서 0건이다. 생성기가 지운 source 기호 자리에 같은 id로 다른 기호를 그리는 연산을
  더해야 이 한계 셈이 시험된다.
- 시트 정체 불변식 1~5(7장 표)를 등록·확정·다시 추출·고르기·정착 연산을 섞는 퍼즈로 묶는다.

## 8. U2로 넘긴 시험(0bef8fe에서)

U1 커밋에는 넣지 않았다(실패하는 시험·기대 실패를 두지 않음). U2가 가드를 고치며 옮긴다.

- `test_guard_counts_fmea_rows`(P4): FMEA 행만 가리켜도 번호 바꾸기를 막음
- `test_guard_counts_sheet_links_in_their_stored_form`(P5): 도면 연결 지정의 끝(번호)만 가리켜도 막음
- `test_numbering_the_left_out_drawing_brings_it_in`: U1 뒤에는 빠진 자료가 없으므로 '둘째 자료도 따로 확정됨'으로 바꿔 씀
- 구간 제외 표시(`구간제외도면.json`)만 가리켜도 막음, 지식그래프 판단 CSV만 가리켜도 막음
- `test_guard_blocks_title_block_number_change_and_unconfirm_with_a_confirmed_node`(P0 가드 고정)
- 여러 쪽 + 자료 번호 등록 보류(`multi_page_number`), 재사용 가지 번호 바꿈 보류(P3 등록 쪽), 예약 꼴 거절(`reserved_number`)
- 정착 전 프로젝트에서 확정 취소를 할 때 예측 이름과 정착 뒤 실제 이름이 다른 경우(표제란 확정 맨 앞에서 정착)

## 9. 구현하며 바꾼 것

- 표제란(`register/titleblock.py`)의 이름 사본 둘(`_graph_id_of`, `_gid`)은 U1에서 `sources.sheet_name`·`name_for`를 부르게 했다. 가드 논리는 그대로다.
  사본을 두면 표제란 패널·가드가 새 이름의 시트를 옛 이름으로 세어, 참조가 있는 시트의 번호 바꾸기를 놓친다.
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
- `graph_member_sheets`가 없는 옛 집합(이 단위 전에 저장)과 `material`이 없는 옛 묘비는 갈아타기 직전에 집합이 한 번도 다시 쓰이지 않았으면 전처럼 참조로 잇거나 되찾을 수 있다.
- 주인 파일의 그래프가 사라지면 4번 차례로 다른 파일이 말없이 그 이름을 얻는다. 판 이전은 5장 규칙으로 묘비를 내지만 알림은 고르기 줄뿐이다.
- 정착 전 프로젝트에서 표제란 확정 취소의 예측 이름이 정착 뒤 이름과 다를 수 있다(8장, U2).
