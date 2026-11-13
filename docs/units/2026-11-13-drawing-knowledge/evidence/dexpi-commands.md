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

내보내기는 **'쪽 확정'이 `confirmed`인 쪽만** 합니다(규격 §6.1). 그 함수 `hazop.extract.confirmation.sheet_confirmation(name)`(화면 규격 §10.7, 단위 V3)는 아직 저장소에 없습니다. 그래서 내보내기 코드는 그 함수를 `default_confirmation()`으로 찾고, **없으면 내보내지 않고 사유를 보입니다**. V3가 들어오면 같은 서명(`name -> {"state": "open"|"ready"|"confirmed", "unconfirmed": [...], "unplaced": [...]}`)으로 그대로 이어집니다. 개발·시험에서는 `confirmation="assume"`(또는 명령줄 `--assume-confirmed`)이 모두 확정으로 봅니다.

| 하는 일 | 함수 | 인자 | 돌려주는 값 |
| --- | --- | --- | --- |
| 내보낼 수 있는 도면 목록(파일을 쓰지 않음) | `hazop.export.dexpi_export.list_exportable(graph_root=None, extract_root=None, confirmation="auto")` | 없음(기본은 작업 루트의 `output/graph`·`output/extract`) | `[{"name", "drawing_number", "confirmed"(도면 번호를 등록에서 사람이 확정했는가), "graph_ok", "state"(쪽 확정 상태, 함수가 없으면 `None`), "unconfirmed"(남은 미확인 수), "exportable", "why": [문장]}]` |
| 내보내기 실행 | `hazop.export.dexpi_export.export_names(names, out_dir, graph_root=None, extract_root=None, require_confirmed_number=True, now=None, confirmation="auto")` | `names`: 도면 이름 목록(`None`이면 그래프가 있는 모든 도면), `out_dir`: Qt 저장 대화상자가 정한 폴더 | `{"manifest": 경로, "drawings": [{"name", "drawing_number", "files", "graph_version", "stats"}], "not_exported": [{"name", "drawing_number", "state", "unconfirmed"}]}` |
| 내보내지 못함 | 위 함수가 던짐 | — | `hazop.export.dexpi_export.ExportError`. `exc.reasons`가 사람이 읽을 문장 목록(도면별 사유, `<이름>: …`). **아무 파일도 쓰지 않은 상태**입니다. 확정된 쪽이 하나도 없을 때, 확정된 쪽이 검사(§6.5)에 걸릴 때, 확정 함수가 없을 때 |
| 한 도면만 메모리에서 | `export_drawing(graph, extraction=None, require_confirmed_number=True, name=None)` | `build_graph` 결과와 그 추출 결과 | `Export`(`.xml` 바이트, `.excluded`·`.sidecar` dict, `.stats`, `.files`) |
| 쓰기 | `write_drawing(export, out_dir)` | — | `{종류: 경로}` |
| 명령줄 | `python scripts/export_dexpi.py --out <폴더> [도면 이름…]` | `--assume-confirmed`는 개발·시험용 | 성공 0 / 실패 1 |

- **쓰는 파일(도면 하나당).** `<도면 이름>.dexpi.xml`(DEXPI XML 2.0.1), `<도면 이름>.excluded.json`(뺀 구성요소·연결·속성과 근사 목록), `<도면 이름>.hazop.json`(곁 파일). 폴더에는 묶음 목록 `manifest.json`(도면 목록, 앱 판, 내보낸 시각, 그래프 판, DEXPI 판, 출처 표시 문구 `DEXPI Specification 2.0.1, DEXPI e.V., CC BY 4.0`, 확정 함수 이름 `confirmation`, **`not_exported`**)도 씁니다.
- **쪽 확정이 풀리는 때.** 함수를 한 번 부른 뒤 쓰기 직전에 다시 부릅니다. 그 사이 확정이 풀린 쪽은 `not_exported`로 옮깁니다.
- **도면 번호.** 등록에서 사람이 확정한 번호(`extraction["drawing"]["identification_basis"] == "registration_confirmed"`)만 내보냅니다(`require_confirmed_number`). 도면 사이 참조를 쓰려면 번호가 확정이어야 하기 때문입니다.
- **ID(§6.6).** DEXPI에서 가져온 객체는 `id`가 글자 규칙에 맞으면 그대로, 그 밖에는 `HZ_` + 엔터티 ID(또는 Proteus ID)의 규칙 밖 글자를 `_`로 바꾼 값, 겹치면 `_2`, `_3`…. 새로 만드는 노즐은 `HZ_<부모 id>_N<번호>`. 원래 ID와의 대응은 곁 파일의 `entities`·`pipes`에 있습니다.
- **흐름.** 확인된 흐름이 있는 연결은 흐름 순서(상류가 Source)로 적고, 그 연결들은 `FlowDirection=SingleFlowPipingNetworkSegment` 구간에 모읍니다(양방향이었던 것은 `Dual…`). 향하는 쪽 자체는 DEXPI에 자리가 없어 곁 파일에 두고 `excluded.json`의 `notes`에 개수를 적습니다. 체크밸브는 입구 연결이 밸브를 Target으로, 출구 연결이 Source로 쓰게 맞춥니다(흐름 순서보다 먼저).
- **화면 안내 문구 자료.** 구성요소가 불확실한 것(분류 못 함, 끝이 미확정인 연결)은 빠지고(쪽 확정을 막으므로 확정된 쪽에는 원래 없어야 합니다), 구성요소는 확실하고 속성만 없는 것은 그 속성만 빠집니다. 근거·미확인·HAZOP 결과 등은 DEXPI에 자리가 없어 곁 파일에만 있고, 같은 앱이 다시 가져올 때만 되붙습니다. `excluded.json`의 이유 코드:

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

## 3. 이번 단위에서 닫지 못한 것

- **규격 §4.2(개정판 수정 기록 복사·재적용, PDF와 DEXPI 이중 등록의 '쓰는 원본').** `hazop/extract/corrections.py`·`hazop/graph/project.py`를 고치는 일이라 이 단위에서 하지 않았습니다. 같은 도면이 두 번 들어오면 수정 기록이 새 추출 이름에 붙지 않습니다. 별도 단위로 해야 합니다(규격 X1 완료 기준의 '개정판' 시험도 그때).
- **쪽 확정 함수(`sheet_confirmation`).** 화면 규격 V3가 만들 때까지 내보내기는 실제 앱에서 거절합니다(`ExportError`). 서명은 이 문서 §2와 같습니다.
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
