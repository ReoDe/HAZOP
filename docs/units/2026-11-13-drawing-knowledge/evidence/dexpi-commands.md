# DEXPI 가져오기·내보내기 엔진 진입 함수 (X1·X2, 2026-11-14)

새 화면(`hazop/shell/`, `s-frame`)이 부를 함수를 정리했습니다. 규격은 `docs/specs/dexpi-exchange.md`(HZ-PLN-22 rev 1). 화면 쪽 코드(등록 패널에서 DEXPI 파일 받기, 내보내기 단추)는 이 문서의 함수를 그대로 부르면 되고, 이 단위는 `hazop/shell/`을 건드리지 않았습니다.

## 1. DEXPI 파일 받기 (등록 → 추출·그래프)

새 함수는 없습니다. 등록·추출 진입 함수가 DEXPI를 알아봅니다. 화면의 끌어 놓기·'추출·그래프 만들기'는 지금 호출 그대로 돌아갑니다.

| 단계 | 함수 | 인자 | 돌려주는 값 | DEXPI일 때 달라진 점 |
| --- | --- | --- | --- | --- |
| ① 등록 | `hazop.register.registry.register(source_path, project_id, material_type="P&ID", store_root=None, metadata=None, actor=None)` | 파일 경로(`.xml`) | `{"outcome", "registration_file", "notes", "record"}` | `record["format"] == "dexpi"`, `record["dexpi_flavor"]`는 `dexpi_xml`(2.0 이후, 뿌리 `Model`) 또는 `proteus`(1.x, 뿌리 `PlantModel`). 쪽(`documents[0].pages`)은 도면(Diagram) 수만큼, 없으면 `page-1` 하나. 표제란 자동 후보(`auto_candidates`)에 도면 번호·도면 이름이 `source: "dexpi_meta"`로 들어감(사람 확정 전). 원본 옆 SVG를 찾지 않으므로 'SVG 없음' 미확인이 없음 |
| ① 등록 거절 | 같은 함수 | — | `outcome: "failed"` + `record["validation"]["blockers"]` | `dexpi_unsafe_xml`(DTD·개체 선언, 크기·요소 수·깊이 한도 초과), `unreadable`, `dexpi_unknown_format`, `dexpi_schema_invalid`(2.0 틀 검사에 어긋남), `format_mismatch`(`.xml`인데 DEXPI가 아님, `.drawio`인데 DEXPI임) |
| ② 추출 + ③ 그래프 | `hazop.app.data.extract_and_graph(registration_file)` | 등록정보 파일 경로 | 지금과 같은 키: `{"extraction", "extract_dir", "graph", "graph_dir", "warnings", "kg"/"kg_error"}` | 추출 결과 `source.format == "dexpi"`, `source.dexpi_version`(파일에서 읽은 DEXPI 판, 예 `2.0.1`·`1.3.1`), `source.dexpi_flavor`. 출력 폴더 이름은 drawio·PDF와 같은 규칙. 새 필드(`read_method`)는 만들지 않았고 `build.py`·`runinfo.py`도 고치지 않았습니다(§4.1) |
| 보조 | `hazop.register.fileinfo.detect_format(bytes)` | 바이트 | `dexpi` / `drawio` / `pdf` / `unsafe_xml` / … | 형식 판별만 |

- **읽은 방법 표시.** 화면은 `extraction["source"]["format"] == "dexpi"`일 때 '변환(DEXPI <`source.dexpi_version`>)'으로 보이면 됩니다. Proteus 스키마 판(`4.1.1`)과 응용 프로그램 정보는 `extraction["run"]["dexpi"] = {flavor, version, schema_version, application, diagram_count, process_objects_skipped}`에 있습니다. 곁 파일을 되붙였으면 `run.dexpi.sidecar`(되붙인 개수)도 있습니다.
- **거절 사유를 화면에 보일 때.** `record["validation"]["blockers"]`의 `check`(코드)와 `reason`(한국어 문장)을 그대로 보입니다.
- **미확인.** DEXPI에서 온 추출 결과의 새 미확인 코드: `dexpi_unmapped_class`(대응표에 없는 클래스, field `kind`), `dexpi_no_position`(그림 위치 없음, field `bbox`, **쪽 확정을 막아야 함** — `sheet_confirmation`의 `unconfirmed` 사유에 `no_position`을 더하는 일은 화면 규격 V3), `dexpi_item_order_assumed`(구간 안 부품의 길 순서를 문서 순서로 끼움, target=그 부품), `dexpi_multiple_diagrams`, `dexpi_process_model_skipped`, `dexpi_actuator_kind_unknown`, `dexpi_sidecar_stale`. 나머지는 기존 코드(`unknown_flow_direction`, `unknown_check_valve_direction`, `unconnected_endpoint`, `missing_tag`…)를 그대로 씁니다.
- **한 방향·양방향.** 구간의 `FlowDirection`은 관계 `attributes["flow_class"]`(`single`·`dual`)로 받습니다. 향하는 쪽은 정하지 않습니다(F13). `dual`이면 `unknown_flow_direction`의 reason이 '양방향 흐름 구간'입니다.
- **정리된 보기가 쓸 위치.** 노드 `bbox`(mm, 위가 0, 노드 위치들의 바깥 상자)는 `extraction["source_locations"]`에, 좌표계는 `extraction["coordinate_system"] = {coordinate_space: "dexpi_diagram", unit: "mm", origin: "top_left", source_origin: "top_left"(2.0) | "bottom_left"(Proteus, 이미 뒤집어 둠)}`에 있습니다. 위치가 없는 구성요소는 `bbox` 자리가 없고(`source_locations`에 항목 없음) 미확인 `dexpi_no_position`이 있습니다. 노드의 원래 노드 위치는 `attributes["dexpi:nodes"]`·`attributes["dexpi:nozzles"]`(JSON 문자열)에 있습니다.
- **ID.** `source_object_id`는 DEXPI `id`(2.0)·`ID`(Proteus) 그대로이고, `id`가 없는 객체는 `PlantModel1__ProcessInstrumentationFunctions_0` 꼴의 경로 ID입니다(`/` 대신 `__`).

## 2. DEXPI 내보내기

내보내기는 **'쪽 확정'이 `confirmed`인 쪽만** 합니다(규격 §6.1). 그 함수는 `hazop.extract.confirmation.sheet_confirmation(name)`(화면 규격 §10.7, c0e2f4c, 명령 표 [sheet-commands.md](sheet-commands.md))이고, 내보내기는 `default_confirmation()`으로 찾습니다(없으면 내보내지 않고 사유를 보임). 개발·시험에서는 `confirmation="assume"`(또는 명령줄 `--assume-confirmed`)이 모두 확정으로 봅니다.

**확정한 자료 그대로 내보냅니다(2026-11-14 검토 R1).** `confirmation="auto"`(엔진의 쪽 확정)이면 디스크의 `output/graph/<이름>/graph.json`을 내용으로 쓰지 않습니다. AI 후보 수락처럼 그래프를 다시 만들지 않는 저장 뒤에는 그 파일이 낡을 수 있기 때문입니다. 대신 `confirmation.load_sheet(name)`이 확정을 판정한 바로 그 세 파일 바이트(추출 결과·사람 수정 기록·AI 후보 기록)로 그래프를 그 자리에서 만들어(`hazop.graph.build.build_graph`, `build_graph.build_one`과 같은 입력) 내보냅니다. 디스크 그래프와 판(`graph_version`)이 다르면 `drawings[].graph_rebuilt`가 `true`입니다. 디스크 파일은 고치지 않습니다. 그래프를 만들 수 없으면 그 쪽은 `not_exported`에 `state: "graph_error"`와 `reason`으로 적습니다. 쓰기 직전에 세 파일 지문을 다시 보고, 바뀌었으면 그 쪽을 `not_exported`(`state: "changed"`)로 옮깁니다. `graph_version`의 뜻은 바꾸지 않았습니다(지문은 `drawings[].source_fingerprint`, 그래프 밖).

| 하는 일 | 함수 | 인자 | 돌려주는 값 |
| --- | --- | --- | --- |
| 내보낼 수 있는 도면 목록(파일을 쓰지 않음) | `hazop.export.dexpi_export.list_exportable(graph_root=None, extract_root=None, confirmation="auto")` | 없음(기본은 작업 루트의 `output/graph`·`output/extract`) | `[{"name", "drawing_number", "confirmed"(도면 번호를 등록에서 사람이 확정했는가), "graph_ok", "state"(쪽 확정 상태, 함수가 없으면 `None`), "unconfirmed"(남은 미확인 수), "exportable", "why": [문장]}]` |
| 내보내기 실행 | `hazop.export.dexpi_export.export_names(names, out_dir, graph_root=None, extract_root=None, require_confirmed_number=True, now=None, confirmation="auto", overwrite=False)` | `names`: 도면 이름 목록(`None`이면 그래프가 있는 모든 도면), `out_dir`: Qt 저장 대화상자가 정한 폴더, `overwrite`: 이미 있는 파일을 덮을지(사용자가 확인한 뒤에만 `True`) | `{"status": "written" \| "exists", "manifest": 경로 또는 null, "existing": [파일 이름], "drawings": [{"name", "drawing_number", "files", "graph_version", "graph_rebuilt", "source_fingerprint", "stats"}], "not_exported": [{"name", "drawing_number", "state", "unconfirmed", "reason"?}]}` |
| 내보내지 못함 | 위 함수가 던짐 | — | `hazop.export.dexpi_export.ExportError`. `exc.reasons`가 사람이 읽을 문장 목록(도면별 사유, `<이름>: …`). **아무 파일도 쓰지 않은 상태**입니다. 확정된 쪽이 하나도 없을 때, 확정된 쪽이 검사(§6.5)에 걸릴 때, 확정 함수가 없을 때 |
| 한 도면만 메모리에서 | `export_drawing(graph, extraction=None, require_confirmed_number=True, name=None)` | `build_graph` 결과와 그 추출 결과 | `Export`(`.xml` 바이트, `.excluded`·`.sidecar` dict, `.stats`, `.files`) |
| 쓰기 | `write_drawing(export, out_dir)` | — | `{종류: 경로}`(바로 씀. `export_names`는 임시 폴더에 쓴 뒤 바꿔 넣음) |
| 명령줄 | `python scripts/export_dexpi.py --out <폴더> [도면 이름…]` | `--assume-confirmed`는 개발·시험용, `--overwrite`는 이미 있는 파일을 덮음 | 성공 0 / 실패·이미 있음 1 |

- **이미 있는 파일(R4).** 쓸 파일(도면별 세 파일과 `manifest.json`)이 `out_dir`에 하나라도 있고 `overwrite`가 거짓이면 아무것도 쓰지 않고 `{"status": "exists", "existing": [...]}`를 돌려줍니다. 화면은 그 목록을 보여 주고 사용자가 덮기를 고르면 `overwrite=True`로 다시 부릅니다. 그때 `status: "written"`이고 `existing`에 덮은 파일이 있습니다. `ExportError`(검사 실패 등)는 이 확인보다 먼저 나옵니다.
- **쓰기 실패.** 모든 파일을 `out_dir` 안 임시 폴더(`.hazop-dexpi-new-…`)에 다 쓴 뒤, 있던 파일을 옆 임시 폴더로 비켜 두고 새 파일을 옮겨 넣습니다. 쓰기나 옮기기가 실패하면 새 파일을 지우고 비켜 둔 파일을 제자리로 돌린 뒤 `OSError`를 올립니다. 앞 내보내기는 그대로 남습니다.
- **파일 이름 겹침(R3).** 도면 이름이 대소문자만 다르면(Windows에서 같은 파일) 겹침으로 보고 `ExportError`(`파일 이름이 겹침: …`)를 던집니다.
- **끊긴 배관 수(R2).** '이대로 확인'으로 확정한 미분류 기호처럼 뺀 구성요소 때문에 내지 못한 연결 수를 `excluded.json`의 `cut_by_excluded: {"pipes", "signal_lines"}`와 `drawings[].stats`의 `cut_pipes`·`cut_signal_lines`에 적습니다.

- **쓰는 파일(도면 하나당).** `<도면 이름>.dexpi.xml`(DEXPI XML 2.0.1), `<도면 이름>.excluded.json`(뺀 구성요소·연결·속성과 근사 목록), `<도면 이름>.hazop.json`(곁 파일). 폴더에는 묶음 목록 `manifest.json`(도면 목록, 앱 판, 내보낸 시각, 그래프 판, DEXPI 판, 출처 표시 문구 `DEXPI Specification 2.0.1, DEXPI e.V., CC BY 4.0`, 확정 함수 이름 `confirmation`, **`not_exported`**)도 씁니다.
- **쪽 확정이 풀리는 때.** 함수를 한 번 부른 뒤 쓰기 직전에 다시 부릅니다. 그 사이 확정이 풀렸거나 세 파일 지문이 바뀐 쪽은 `not_exported`로 옮깁니다. 확정 기록이 깨진 쪽(`record_error`)은 확정되지 않은 쪽으로 봅니다.
- **도면 번호.** 등록에서 사람이 확정한 번호(`extraction["drawing"]["identification_basis"] == "registration_confirmed"`)만 내보냅니다(`require_confirmed_number`). 도면 사이 참조를 쓰려면 번호가 확정이어야 하기 때문입니다.
- **ID(§6.6).** DEXPI에서 가져온 객체는 `id`가 글자 규칙에 맞으면 그대로, 그 밖에는 `HZ_` + 엔터티 ID(또는 Proteus ID)의 규칙 밖 글자를 `_`로 바꾼 값, 겹치면 `_2`, `_3`…. 새로 만드는 노즐은 `HZ_<부모 id>_N<번호>`. 원래 ID와의 대응은 곁 파일의 `entities`·`pipes`에 있습니다.
- **흐름.** 확인된 흐름이 있는 연결은 흐름 순서(상류가 Source)로 적고, 그 연결들은 `FlowDirection=SingleFlowPipingNetworkSegment` 구간에 모읍니다(양방향이었던 것은 `Dual…`). 향하는 쪽 자체는 DEXPI에 자리가 없어 곁 파일에 두고 `excluded.json`의 `notes`에 개수를 적습니다. 체크밸브는 입구 연결이 밸브를 Target으로, 출구 연결이 Source로 쓰게 맞춥니다(흐름 순서보다 먼저).
- **화면 안내 문구 자료.** 구성요소가 불확실한 것(분류 못 함, 끝이 미확정인 연결)은 빠집니다. 쪽 확정은 이것들을 막으므로, 확정된 쪽에 남은 것은 사람이 '이대로 확인'한 것뿐이고, 내보내기는 멈추지 않고 빼고 냅니다(규격 §6.2 rev 2). 구성요소는 확실하고 속성만 없는 것은 그 속성만 빠집니다. 근거·미확인·HAZOP 결과 등은 DEXPI에 자리가 없어 곁 파일에만 있고, 같은 앱이 다시 가져올 때만 되붙습니다. `excluded.json`의 이유 코드:

| 목록 | `reason` 코드 | 뜻 |
| --- | --- | --- |
| `excluded_components` | `unclassified` | 종류를 못 정한 구성요소(DEXPI에서 가져와 원문 조각이 있고 사람이 고치지 않은 것은 `approximations`의 `restored_from_original_text`로 되살림) |
| | `no_dexpi_class` | DEXPI에 맞는 클래스가 없는 kind(댐퍼·드레인·시험 연결·끝막음) |
| | `direction_unknown` | 도면 연결 기호의 FlowIn·FlowOut을 정할 근거가 없음 |
| `excluded_connections` | `endpoint_excluded` | 한 끝이 빠진 구성요소라 연결을 내지 않음(없는 연결을 지어내지 않음) |
| | `unresolved_connector` | 끝이 미확정인 연결 |
| | `sensing_location_not_piping_component` | 측정 위치가 배관 부품이 아님(설비에 직접 붙은 측정선) |
| | `signal_end_not_instrument_or_actuator` | 신호선 끝이 계측 기능·구동 밸브가 아님 |
| | `bad_endpoint_count` | 끝점이 둘이 아닌 연결 |
| `excluded_attributes` | `no_dexpi_slot` | DEXPI 속성 이름이 없음(곁 파일에는 있음). 예: `normal_position` |
| | `no_dexpi_value` | 값이 DEXPI 열거에 없음 |
| | `tag_not_isa_form` | 계기 태그가 ISA 모양이 아님 |
| `approximations` | `approximate_class` | 비슷한 DEXPI 클래스로 냄(복수기·증기발생기·원자로용기·가압기·축압기·탈염기 등) |
| | `nozzle_name_generated` | 포트가 없는 설비 끝에 N1, N2… 노즐을 만듦 |
| | `restored_from_original_text` | 가져온 미분류 객체를 원문 조각으로 되살림(조각 안 id·참조가 §6.6 규칙에 맞을 때만) |
| | `actuating_system_added_for_signal_line`, `instrument_tag_not_isa_form` | 구동계를 새로 달았거나 태그를 번호로 냄 |

- **되읽기(같은 앱).** 내보낸 파일을 다시 가져올 때는 `python scripts/extract_dexpi.py <파일>`이 파일 옆 `<이름>.hazop.json`을 찾아 되붙입니다. 함수로는 `hazop.extract.adapters.dexpi_import.extract_bytes(data, 파일 이름, registration=None, sidecar=<곁 파일 dict>)`입니다. 곁 파일의 `dexpi_sha256`이 파일과 다르면(내보낸 뒤 바뀜) 되붙이지 않고 미확인 `dexpi_sidecar_stale`을 남깁니다.

## 2.5 같은 도면 번호의 원본이 여러 형식일 때 (가져오기 검토 4번, `hazop/graph/sources.py`)

같은 도면 번호의 drawio·PDF·DEXPI 그래프는 `graph_id`(`graph-<번호>`)가 같아 지금까지 마지막에 추출한 것이 말없이 이겼습니다. 이제 **형식이 섞이면 사람이 고르기 전에는 바꾸지 않습니다**(먼저 있던 형식을 씀). 같은 형식끼리는 지금 규칙(가장 최근) 그대로라 기존 프로젝트(SNP drawio 6장)의 선택과 `graph_version`은 그대로입니다. 등록 없이 추출한 DEXPI 폴더 이름은 `<도면 번호>-dexpi`라 같은 번호의 drawio·PDF 폴더와 사람 수정 기록(`data/drawing-edits/<폴더>.json`)이 섞이지 않습니다(등록 경로는 원래 자료마다 폴더가 따로입니다).

| 하는 일 | 함수 | 인자 | 돌려주는 값 |
| --- | --- | --- | --- |
| 충돌 사실(파일을 쓰지 않음) | `hazop.graph.sources.conflicts(project_id, graph_root=None, choices_root=None)` | 프로젝트 ID | `[{"drawing_number", "graph_id", "formats": ["dexpi","drawio"], "candidates": [{"name"(output/graph 폴더), "format", "modified"}], "in_use"(지금 프로젝트 그래프에 쓰는 폴더), "in_use_format", "chosen"(사람이 고른 형식 또는 None)}]`. 충돌이 없으면 `[]` |
| 선택 받기 | `hazop.graph.sources.choose(project_id, drawing_number, source_format_name, by, at=None, graph_root=None, choices_root=None)` | `source_format_name`은 `drawio`·`pdf_vector`·`dexpi`(추출 결과 `source.format`), `by`는 고른 사람 | 저장한 `{"format", "by", "at"}`. 충돌이 없거나 그 형식의 그래프가 없거나 이름이 비면 `ValueError`, 읽은 뒤 파일이 바뀌었으면 `hazop.store_io.Conflict`(아무것도 쓰지 않음) |
| 등록에서 알릴 충돌 | `hazop.register.registry.register(...)`의 결과에 `conflicts`(`[{"drawing_number", "materials": [{"material_id", "format", "registration_version"}]}]`)와 `notes`의 알림 문장이 더해짐. 같은 프로젝트에 사람이 확정한 같은 번호를 형식이 다른 자료가 이미 쓰고 있을 때만 | 기존 인자 그대로 | 등록 자체는 막지 않고 그래프에 쓰는 원본도 바꾸지 않음. 목록만 따로 보려면 `hazop.graph.sources.registration_conflicts(project_id, store_root=None)` |
| 그래프 고르기(읽기) | `hazop.graph.project.pick_graphs`·`hazop.kg.auto.project_graphs`가 같은 규칙을 씀 | — | 선택이 반영된 도면 그래프 |

- 선택은 `data/drawing-sources/<프로젝트>.json`(`{"kind": "hazop_drawing_sources", "chosen": {"<번호>": {"format", "by", "at"}}}`)에 원자적으로 씁니다. 파일이 없거나 깨졌거나 고른 형식의 그래프가 없으면 기본(먼저 있던 형식)으로 돌아갑니다. 선택을 되돌려도(다른 형식을 다시 고르면) 양쪽 추출 결과·수정 기록이 그대로라 이전 상태가 그대로 다시 쓰입니다.
- 화면 쪽에서 할 일: 등록 결과의 `conflicts`가 있거나 `conflicts()`가 비어 있지 않으면 고르게 하고, 고른 값을 `choose`로 보냅니다. 고르기 전에는 '먼저 있던 형식을 쓰는 중'이라고 보입니다(`in_use`·`in_use_format`).

## 2.6 가져오기 검토 반영으로 달라진 읽기 결과 (2026-11-14)

- 흐름 화살표는 배관의 실제 경로(2.0 `ConnectorLine`의 시작·안쪽 점·끝, Proteus 구간의 `CenterLine`)에서 화살표가 놓인 선분의 방향과 견줍니다. 경로에서 1.5mm보다 멀거나 두 길에 0.5mm 안으로 가깝거나 방향이 맞지 않으면 방향을 정하지 않고 미확인 `dexpi_flow_arrow_unplaced`를 남깁니다. 공개 예제 구간 3·19는 밸브 → 탱크입니다.
- 처리하지 않는 요소는 흔적을 남깁니다: 대응표에 없는 설비 클래스·구간 안 `ProcessInstrument`·`Equipment`·`PropertyBreak` 등은 미분류 노드(길에 그대로 있음), ID 없는 부품은 경로 ID(`…__item_<순번>`)와 미확인 `dexpi_item_without_id`, 그래프에 자리가 없는 것(`InstrumentationLoopFunction`·`PlantStructureItem` 등)은 종류별 개수를 `run.dexpi.not_imported`와 미확인 `dexpi_not_imported`에 남깁니다.
- 새 미확인 코드: `dexpi_flow_arrow_unplaced`, `dexpi_item_without_id`, `dexpi_not_imported`, `dexpi_version_mixed`(Core·Plant 판이 다름), `dexpi_version_unknown`(모르는 판 또는 Proteus 파일에 DEXPI 판 없음), `dexpi_tag_not_unique`(같은 태그가 여럿, 합치지 않음). `source.dexpi_version`은 공식 주소(`data.dexpi.org/models/<판>/…`)의 Plant 판, Proteus는 `Application`이 `Dexpi`일 때의 `ApplicationVersion`(CAD 프로그램 버전은 `run.dexpi.application`에만).

## 3. 이번 단위에서 닫지 못한 것

- **규격 §4.2 (가) 개정판 수정 기록 복사·재적용**은 하지 않았습니다(`corrections.py`를 고치는 일). 같은 자료의 새 등록 버전이나 새 DEXPI 파일이 들어오면 수정 기록이 새 추출 이름에 붙지 않습니다. (나) 이중 등록의 '쓰는 원본'은 §2.5로 닫았습니다.
- **쪽 확정 함수(`sheet_confirmation`).** c0e2f4c로 들어왔습니다(§2).
- 등록 하나에 도면(Diagram)이 둘 이상인 2.0 파일은 첫 도면 기준으로만 추출합니다(미확인 `dexpi_multiple_diagrams`). 쪽 목록(`pages`)은 도면 수만큼 만들지만 둘째 쪽 추출은 없습니다.
- 흐름 화살표는 모양이 이등변 삼각형 윤곽일 때만 방향으로 읽고(2.0.1 Reference P&ID의 두 모양이 그렇다), 연결에 맞는 것(코사인 0.7 이상)만 `declared`로 씁니다.
- 내보낸 파일의 그림은 노드 위치(`PipingNodePosition`)와 테두리뿐입니다. 기호 모양(`ShapeUsage`)·글자·선은 내보내지 않으므로 CAD에서 열면 위치 점만 보입니다. 가져오기 위치가 없던(drawio·PDF) 도면은 도면 크기를 A3(420×297mm)에 맞춰 줄인 위치(`scale`은 곁 파일에 있음)입니다.
- 내보낸 DEXPI가 받는 CAD에서 열리는지는 확인할 수 없습니다(규격 §6.5). 스키마 검사는 앱에 XSD를 묶지 않고 같은 규칙을 코드(`check_structure`)로 검사하며, 그 표가 참고 자료 XSD와 같은지는 시험(`tests/test_dexpi_rules.py`)이 봅니다.

## 4. 좌표 방향 확인 근거 (규격 §5.3에 반영)

| 확인한 것 | 값 | 뜻 |
| --- | --- | --- |
| 2.0.1 Reference P&ID 표제란 글자(도면 번호 `123/A93`) | y 291.25 (도면 높이 297) | 표제란은 아래쪽 → 위가 0, 아래로 증가 |
| 같은 도면의 칸 글자 | A y 21.6 … H y 274.5 | 위에서 아래로 A→H |
| 같은 노드의 2.0 판 y와 Proteus 판 y | 154 ↔ 143, 합 297 | Proteus는 y가 위로 커짐(도면 높이에서 뺌) |
| 흐름 화살표 회전 θ (2.0.1) | 90° 화살표가 아래(+y)로 흐르는 세그먼트 끝점과 맞음 | 방향 벡터 = (cos θ, sin θ), 위가 0인 좌표 |
