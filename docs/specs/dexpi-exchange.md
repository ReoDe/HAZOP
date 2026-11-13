---
doc_id: HZ-PLN-22
rev: 0
status: review
author: D-node 세션(2026-11-13)
reviewed: —
approved: —
---

# DEXPI 가져오기·내보내기

[INTENT §2·§3.1·§3.2·§3.8](../../INTENT.md) · [정보 추출](extraction.md) · [지식그래프 스키마 사전](kg-schema-dictionary.md) · [자료 등록](registration.md) · [새 화면 규격](../design/app-shell-web.md) · 구현 코드 `hazop/extract/`, `hazop/graph/`

- 작성일 2026-11-13. 상태는 **규격 초안, 구현 전**입니다. 코드는 고치지 않았습니다. 코드 줄 번호는 커밋 `abb7b2a` 기준입니다.
- 사용자 결정(2026-11-13 대화): 어떤 형태로 들어온 도면이든 한 가지 형태로 노드화해 저장합니다. 내부 저장은 지금의 그래프로 하고, 밖과 주고받는 공개 표준은 DEXPI로 합니다. 이 문서는 그 결정의 가져오기·내보내기 규칙입니다. '정리된 보기'(읽은 결과로 다시 그린 도면)는 `d-chat` 세션이 설계하고, 이 문서는 그 보기가 쓸 위치 정보만 정합니다.
- 용어. 배관 및 계장도(P&ID, piping and instrumentation diagram), 노즐(nozzle), 도면 연결 기호(off-page connector), 배관망 계통(piping network system), 배관망 구간(piping network segment), 계측 기능(process instrumentation function), 고장 시 동작(fail action), 호칭 지름(nominal diameter), 설계 압력·온도(design pressure·temperature), 배관 등급(piping class), 유체 코드(fluid code). 처음 나올 때만 영문을 함께 적습니다.

## 0. 먼저 알릴 것: DEXPI는 2.0부터 Proteus XML을 쓰지 않습니다

사용자 결정과 [INTENT](../../INTENT.md) §2는 공개 표준을 'DEXPI(Proteus XML)'로 적고 있습니다. 공식 자료를 확인해 보니 지금 판은 다릅니다.

- DEXPI 2.0(2025-10-10 발표)부터 교환 파일 형식은 **DEXPI XML**입니다. 공식 발표문은 이 형식이 이전의 Proteus 스키마를 대신한다고 적었고, 사양 페이지는 2.0부터 Proteus XML 스키마를 구현하지 않아도 DEXPI를 쓸 수 있다고 적었습니다(§1 출처 S2·S3).
- 지금 판은 **DEXPI 2.0.1**(2026-09-30, 2.0을 대신하는 수정판)입니다.
- 그러나 지금 CAD 도구가 내보내는 DEXPI 파일은 대부분 1.x(Proteus XML)일 것으로 봅니다. DEXPI 인증 페이지에서 본 예는 2022년 6회차 인증이고, 2.0 형식을 내보내는 CAD 도구가 있는지는 확인하지 못했습니다.

그래서 이 규격은 **가져오기는 두 형식을 다 받고, 내보내기는 DEXPI XML 2.0.1로 합니다**(§9 V-1). INTENT의 '(Proteus XML)' 표기는 총괄이 고칠 일로 남깁니다(§10).

## 1. 확인한 사실과 출처

2026-11-13에 공식 자료를 직접 열어 확인했습니다. '확인 못 함'은 찾아봤지만 공식 근거를 못 찾은 것입니다.

| # | 항목 | 확인한 내용 | 출처 |
| --- | --- | --- | --- |
| F1 | 지금 판 | DEXPI Specification **2.0.1**. GitLab 릴리스 `V2.0.1`(2026-09-30). 2.0을 대신하는 수정판이며, 2.0을 쓰고 있으면 2.0.1로 옮기라고 권함 | S1, S2 |
| F2 | 이전 판 | `V2.0.0` 2025-10-10, `V1.4.0`(Plant) 2024-12-11, `V1.3.0`(P&ID) 2021-05-31, `1.2` 2017-05-19 | S1 |
| F3 | 2.0의 내용 | P&ID 사양 1.4(설비 모델)와 Process 사양을 합침. 설비 모델(plant model) 내용은 1.4와 같고 하위 호환이라고 적음 | S3 |
| F4 | 파일 형식(2.0 이후) | DEXPI XML. 뿌리 `Model`, 그 아래 `Import`(Core·Plant 모델 참조)와 `Object`(`type="Plant/Piping.Pipe"` 꼴). 값은 `Data`, 소유는 `Components`, 참조는 `References`(`objects="#ID"`). 스키마 파일은 `DEXPI_XML_Schema.xsd`(28,664바이트) | S4, S5, 받은 예제 |
| F5 | 파일 형식(1.x) | Proteus XML. 뿌리 `PlantModel`, `PlantInformation`의 `SchemaVersion`(예제는 4.1.1)·`ApplicationVersion`(1.3.1)·`Units="mm"`. 클래스는 `ComponentClass` 속성, 값은 `GenericAttribute`. OPC 30250(OPC UA 연동 사양 v1.0)은 DEXPI 1.2와 Proteus 4.0.1을 참조함. Proteus 저장소의 최신 스키마는 4.2 | S6, S7, 받은 예제 |
| F6 | 사양 라이선스 | **CC BY 4.0**(사양 HTML의 License 절, 2.0 발표문). 출처 표시와 변경 표시를 하면 상업적 이용과 수정이 허용됨. 보증 없음 | S2, S3 |
| F7 | DEXPI XML 스키마(XSD)의 라이선스 | 사양 저장소의 사양 문서 폴더(`src/documentation/_static/`) 안에 있음. 저장소에 LICENSE 파일은 없고 GitLab 라이선스 항목도 비어 있음. 사양 전체의 CC BY 4.0이 적용된다고 보는 것이 자연스럽지만, 파일 단위의 명시는 **확인 못 함** | S1 |
| F8 | Proteus 스키마(XSD)의 라이선스 | GitHub `ProteusXML/proteusxml`에 LICENSE 파일이 없고 README에도 라이선스 문구가 없음 → **이용 조건 확인 못 함**. 앱에 묶지 않음 | S7 |
| F9 | 공개 예제 | (가) 2.0.1 사양 부록의 Reference P&ID `reference_pid.xml`(1,481,865바이트, 사양과 같은 CC BY 4.0). (나) GitLab `dexpi/TrainingTestCases`: DEXPI 1.2·1.3 예제 40여 개(C01 참조 도면, C08 도면 두 장 연결 등). 저장소 라이선스 **CC BY 4.0** | S8, S9 |
| F10 | 'DEXPI' 이름 사용 조건 | 상표·이름 사용 규정을 찾지 못함 → **확인 못 함**. 사이트 바닥글의 법적 고지(Legal Notice) 본문은 열어 보지 못함 | S2 |
| F11 | 인증 | DEXPI 인증(가져오기·내보내기, 시험 회차별)이 있음. 예: AutoCAD P&ID/Plant 3D가 2022년 6회차 가져오기·내보내기 인증. 신청 자격·비용은 **확인 못 함** | S10 |
| F12 | 클래스 이름 | 2.0.1 클래스 정의 원문(`src/model/Plant/*`)에서 확인. 클래스 정의 수는 배관 74, 설비 142, 계장 33(추상 클래스 포함, 정의 줄을 셈). 원자력 고유 설비(원자로용기, 가압기, 원전 증기발생기, 탈염기)는 없음 | S11 |
| F13 | 배관 연결의 방향 | `PipingConnection.SourceItem`·`TargetItem`·`SourceNode`·`TargetNode`의 설명은 '연결이 시작하는/끝나는 곳'뿐이고 **흐름 방향이라는 말은 없음** | S11 |
| F14 | 도면 간 연결 | `PipeOffPageConnector.ConnectorReference`(0..1). 하위 클래스 `PipeOffPageConnectorReferenceByNumber`가 `ReferencedDrawingNumber`·`ReferencedConnectorNumber`를 가짐. 같은 파일 안이면 `PipeOffPageConnectorObjectReference` | S12 |
| F15 | 좌표 | 예제 두 형식 모두 mm 단위, A3(420×297) 도면틀. Proteus 예제는 `Drawing/Extent` Min(0,0)·Max(420,297). Y축 방향은 사양 문장으로 **확인 못 함**(§5.3에서 렌더 비교로 정함) | 받은 예제 |

**출처**

- S1 GitLab `dexpi/Specification` API(릴리스·파일 목록·커밋): https://gitlab.com/dexpi/Specification/-/releases
- S2 DEXPI 사양 목록과 2.0.1 사양 HTML(License 절): https://dexpi.org/specifications/ , https://dexpi.org/specification/2.0.1/html/index.html
- S3 DEXPI 2.0 발표문(2025-10-10): https://dexpi.org/dexpi-2-0-specification-published-a-new-standard-for-process-industry-data-exchange/
- S4 DEXPI XML 설명: https://dexpi.org/specification/2.0.1/html/basics/metamodel_and_exchange_format.html
- S5 스키마 파일: GitLab `dexpi/Specification` 태그 `V2.0.1`, `src/documentation/_static/DEXPI_XML_Schema.xsd`
- S6 OPC 30250 §2 참조 규격: https://reference.opcfoundation.org/specs/OPC-30250/2
- S7 Proteus 스키마 저장소: https://github.com/ProteusXML/proteusxml (README, 릴리스 `v4.0.1`)
- S8 Reference P&ID: https://dexpi.org/specification/2.0.1/html/appendix/reference_pid.html
- S9 공개 예제 저장소: https://gitlab.com/dexpi/TrainingTestCases (LICENSE: CC BY 4.0)
- S10 인증: https://dexpi.org/certificates/
- S11 클래스 정의 원문: GitLab `dexpi/Specification` 태그 `V2.0.1`, `src/model/Plant/{Piping,ProcessEquipment,Instrumentation}/`
- S12 도면 연결 클래스: https://dexpi.org/specification/2.0.1/html/models/Plant/Piping/PipeOffPageConnectorReferenceByNumber.html

받은 파일은 `D:\HAZOP-trials\2026-11-13-dexpi\`에만 두었고(README에 출처와 `keep_until: 2026-11-27`), 저장소에는 넣지 않았습니다. 받은 파일 안의 스크립트는 실행하지 않았습니다.

## 2. 큰 줄기

```
CAD ─ DEXPI 파일 ─┐
                   ├─ ① 등록(형식 판별) ─ ② 변환(인식 없음) ─ extraction.json ─ ③ 그래프(지금 코드 그대로) ─ graph.json
drawio·PDF ───────┘                      ② 추출(인식)      ─┘
graph.json + 사람 확정 + 수락한 AI 후보 ─ 내보내기 ─ DEXPI XML 2.0.1 + 뺀 목록 + 곁 파일
```

- **가져오기는 그래프가 아니라 추출 결과(`extraction.json`)를 만듭니다.** drawio·PDF 추출과 같은 계약([추출 결과의 공통 계약](extraction.md))으로 쓰면 ③ 그래프 변환(`hazop/graph/build.py`), 사람 수정(`corrections.py`), 미확인 목록, 그래프 판(`graph_version`), 구간·결과 쪽이 바뀌지 않습니다. 새 코드는 '읽는 쪽' 하나만 생깁니다.
- **내보내기는 그래프에서 시작합니다.** 프로젝트 그래프(`hazop/graph/project.py`)와 사람 수정·AI 후보 상태를 읽어 DEXPI 객체를 만들고, 스키마 검사를 통과해야만 파일을 씁니다.
- 대응 규칙(우리 `kind` ↔ DEXPI 클래스)은 한 곳(`hazop/extract/dexpi_map.py`, 새 파일)에 두고 가져오기·내보내기가 같이 씁니다. 지식그래프 레지스트리의 `dexpi_class`(`hazop/kg/schema/registry.json`, 23개)는 이 표와 맞춰 고칩니다(§3.6).

## 3. 대응표

'맞음'은 뜻과 구조가 같은 것, '근사'는 뜻은 같지만 모양이나 세분이 달라 정보가 줄거나 늘어나는 것, '없음'은 맞는 자리가 없는 것입니다. DEXPI 클래스 이름은 2.0.1 원문(F12)에서 확인한 것만 적었습니다. Proteus 열은 1.3 예제에서 본 이름입니다.

### 3.1 구조

| 우리 쪽 | DEXPI 2.0.1 | Proteus(1.3) | 정도 | 규칙 |
| --- | --- | --- | --- | --- |
| 도면 1장(`graph.json` 하나, `drawing_number`) | `Core/Diagram.Diagram` 하나 + `Plant/Diagram.PlantMetaData`(`DrawingNumber`, `DrawingName`) | `Drawing` + `MetaData` | 맞음 | 가져올 때 `DrawingNumber`·`DrawingName`은 등록의 '자동 후보'로만 둠(등록 규칙 4) |
| 노드 `drawing_object`(`kind`, `tag`) | `Object`(`type`) | `Equipment`·`PipingComponent` 등 요소 + `ComponentClass` | 맞음 | §3.2~3.4 |
| 배관 관계 `physical_connection` → ③에서 `pipe_segment` 노드 + `has_endpoint` 2개 | `Plant/Piping.Pipe`(또는 `DirectPipingConnection`) 하나. `SourceItem`·`TargetItem` | `Connection FromID/ToID` | 맞음 | 연결 하나 = 관계 하나 |
| 배관 관계에 실린 라인 속성(`line_no`, `attributes`) | `PipingNetworkSegment`(구간)와 `PipingNetworkSystem`(계통)에 있음 | 같음 | 근사 | 우리는 관계마다 같은 값을 복사해 들고, DEXPI는 구간에 한 번 둠. 가져올 때 구간 값을 그 구간의 관계마다 복사하고 구간 ID를 `attributes["dexpi:segment"]`에 남김. 내보낼 때 같은 `line_no`·`fluid_code`·`pipe_class`·`nominal_diameter`로 이어진 관계를 한 구간으로 묶음 |
| 배관 구간(`pipe_segment`) 노드 | `PipingNetworkSegment` | 같음 | 근사 | 우리 구간 노드는 '연결 하나', DEXPI 구간은 '부품 여러 개를 거치는 줄기'. 이름은 같지만 단위가 다름. 이 차이 때문에 왕복에서 구간 경계가 바뀔 수 있음(§7.4) |
| 포트(`has_endpoint.port`, [포트 규칙](extraction.md)) | `Plant/ProcessEquipment.Nozzle`(및 `ProcessNozzle`·`InstrumentNozzle`·`AccessNozzle`) | `Nozzle` | 근사 | §3.3 |
| 노즐 노드(`kind=nozzle`, 선택) | `Nozzle` | `Nozzle` | 맞음 | 우리 쪽은 노즐을 노드로 두지 않는 것이 기본. §3.3 |
| 분기(`tee`) | `Plant/Piping.PipeTee` | 같음 | 맞음 | |
| 도면 연결점(`continuation`, `to_drawing`, `line_no`, `direction`, `to_object`) | `FlowInPipeOffPageConnector`·`FlowOutPipeOffPageConnector` + `ConnectorReference` → `PipeOffPageConnectorReferenceByNumber`(`ReferencedDrawingNumber`, `ReferencedConnectorNumber`) | `PipeOffPageConnector` | 맞음 | `direction` FROM→FlowIn, TO→FlowOut. `to_drawing`↔`ReferencedDrawingNumber`, `to_object`↔`ReferencedConnectorNumber`. `line_no`는 붙은 구간의 라인 번호에서 읽음 |
| 신호선(`signal_connection`) | `Plant/Instrumentation.SignalConveyingFunction`(하위 `SignalLineFunction`) | `InformationFlow` `SignalConveyingFunction` | 근사 | 우리는 끝 두 개만, DEXPI는 기능 사이 정보 흐름. 끝이 계측 기능·구동계가 아니면 내보내지 못함(§6.2) |
| 측정선(`measurement_connection`) | `MeasuringLineFunction` + `SensingLocation`(구간·설비가 측정 위치) | `InformationFlow` `MeasuringLineFunction` | 근사 | 측정 위치가 배관이면 우리는 구간 노드 끝, DEXPI는 구간 참조 |
| 흐름 방향(`flow_direction`, basis 포함) | **없음**(F13). `FlowIn/Out` 연결 기호와 흐름 화살표(`Core/Diagram.PipeFlowArrow`)는 그림 쪽 | `PipeFlowArrow` | 없음 | §5.4 |
| 체크밸브 허용 방향(`check_direction`) | 없음(클래스 `CheckValve`·`SwingCheckValve`만) | 없음 | 없음 | 내보낼 때 연결의 Source→Target을 입구→출구로 맞춰 적고, 곁 파일에 근거를 남김 |
| 그림 위치(`bbox`, `position`) | `Core/Diagram.ShapeUsage`의 `Position`·`Rotation`·`ScaleX/Y`, `RepresentationGroup.Represents`로 객체와 이음. 선은 `PolyLine.Points` | `Position/Location`, `Extent`, `CenterLine` | 근사 | §5.3 |
| 원본 객체 ID(`source_object_id`) | `Object id`(파일 안에서만 고유, 생략 가능) | `ID` | 맞음 | §5.2 |

### 3.2 설비

| 우리 `kind` | DEXPI 2.0.1 클래스 | 정도 | 비고 |
| --- | --- | --- | --- |
| `pump` | `Pump`(하위 `CentrifugalPump`·`ReciprocatingPump`·`RotaryPump`·`EjectorPump`) | 맞음 | 가져올 때 하위 클래스 이름은 `attributes["dexpi:type"]`에 남김 |
| `compressor` | `Compressor`(하위 넷) | 맞음 | |
| `fan` | `Fan`(하위 `AxialFan`·`RadialFan`), `Blower` | 맞음 | `Blower`는 가져올 때 `fan` |
| `turbine` | `Turbine`(하위 `SteamTurbine`·`GasTurbine`) | 맞음 | |
| `tank` | `Tank` | 맞음 | |
| `vessel` | `Vessel`, `PressureVessel` | 맞음 | |
| `heat_exchanger` | `HeatExchanger`(하위 `TubularHeatExchanger`·`PlateHeatExchanger` 등) | 맞음 | |
| `filter` | `Filter`(하위 `LiquidFilter`·`GasFilter`) | 맞음 | |
| `condenser` | `HeatExchanger`(보통 `TubularHeatExchanger`) | 근사 | DEXPI에 복수기 클래스가 없음. 내보낼 때 `HeatExchanger` + 곁 파일에 `condenser` |
| `steam_generator` | `HeatExchanger` | 근사 | DEXPI `SteamGenerator`는 `Heater`(가열로 계열)의 하위 클래스라 원전 증기발생기와 뜻이 다릅니다. 이름이 같다고 `SteamGenerator`로 내보내지 않습니다 |
| `reactor_vessel`, `pressurizer`, `accumulator` | `PressureVessel` | 근사 | 원자력 고유 설비. 원래 종류는 곁 파일(§6.3)에 남김 |
| `demineralizer` | `PressureVessel` | 근사 | 이온교환기 클래스 없음 |
| (가져올 때만) DEXPI의 그 밖의 설비(`Mixer`, `Dryer`, `Centrifuge`, `Agitator`, `Heater`, `Motor` 등) | — | 없음 | 미분류로 가져옴(§5.5) |
| 설비 내부(`Chamber`, `TubeBundle`, `Impeller`, `Displacer`) | — | 없음 | 노드를 만들지 않고 부모 설비의 `attributes`에 넣음. 설계 조건은 §3.5 |

### 3.3 노즐과 포트

DEXPI는 배관이 설비에 직접 붙지 않고 설비가 가진 노즐에 붙습니다. 우리 그래프는 배관 끝이 설비 노드에 붙고 어느 접속점인지는 끝점의 `port` 문자열로 둡니다([포트 규칙 A2](extraction.md)).

- **가져오기(권장, §9 V-3).** 노즐에 붙은 연결의 끝을 노즐의 부모 설비로 바꾸고, 끝점 `port`에 노즐 이름(`SubTagName`, 없으면 DEXPI ID)을 넣습니다. 노즐 노드는 만들지 않습니다. 노즐의 클래스·호칭 지름·그림 위치는 설비 노드 `attributes["dexpi:nozzles"]`에 목록으로 둡니다. 이러면 지금 그래프 모양(설비―구간―설비)과 검토구간 분할·경로 탐색이 그대로 돌아갑니다.
- **내보내기.** 설비마다 끝점 `port` 값별로 노즐 하나를 만듭니다. `port`가 없는 끝은 연결 순서대로 `N1`, `N2`…를 붙인 노즐을 만들고 뺀 목록이 아니라 '근사' 목록(§6.4)에 적습니다. 가져온 도면이면 `dexpi:nozzles`의 원래 노즐을 그대로 씁니다.

### 3.4 밸브·배관 부품·계장

| 우리 `kind` | DEXPI 2.0.1 | 정도 | 비고 |
| --- | --- | --- | --- |
| `manual_valve`, `isolation_valve` | `valve_type`이 있으면 `GateValve`·`GlobeValve`·`BallValve`·`ButterflyValve`·`PlugValve`·`NeedleValve`, 없으면 `OperatedValve` | 근사 | DEXPI의 `OperatedValve`는 모든 밸브의 부모인 구체 클래스입니다(이름과 달리 '구동 밸브'만 뜻하지 않음, F12). 가져올 때는 구동계가 없으면 `manual_valve` |
| `motor_operated_valve`, `air_operated_valve`, `solenoid_valve`, `control_valve` | 밸브 클래스(위와 같음) + `ActuatingSystem` → `ControlledActuator` + `OperatedValveReference`(밸브 참조) | 근사 | 구동 방식(`motive_power`)은 DEXPI 속성 이름을 확인하지 못함 → 곁 파일. 가져올 때: 구동계가 있고 측정·제어 루프에 들면 `control_valve`, 아니면 미분류 구동 밸브로 두고 미확인 `dexpi_actuator_kind_unknown`을 남김(구동 방식을 지어내지 않음) |
| `fail_position`(`FO`/`FC`/`FL`/`FAI`) | `ControlledActuator.FailAction`(`FailOpen`·`FailClose`·…) | 맞음 | 열거값 이름은 예제에서 `FailClose`만 봄. 나머지 값 이름은 구현 때 원문으로 확인 |
| `normal_position`(`NO`/`NC`/`LO`/`LC`) | 확인 못 함 | 없음 | 곁 파일 |
| `check_valve` | `CheckValve`(하위 `SwingCheckValve`·`GlobeCheckValve`) | 맞음 | 허용 방향은 §3.1 |
| `psv`, `relief_valve` | `SafetyValveOrFitting`(하위 `SpringLoadedGlobeSafetyValve`·`SpringLoadedAngleGlobeSafetyValve`·`BreatherValve`) | 맞음 | `set_pressure`는 §3.5 |
| `rupture_disc` | `RuptureDisc` | 맞음 | |
| `damper` | — | 없음 | 내보낼 때 뺌(§6.2) |
| `orifice` | `RestrictionOrifice` | 맞음 | |
| `flow_element` | `FlowMeasuringElement`(하위 여럿) | 맞음 | |
| `reducer` | `PipeReducer` | 맞음 | |
| `blind_flange` | `BlindFlange` | 맞음 | |
| `strainer` | `Strainer`, `ConicalStrainer` | 맞음 | |
| `vent` | `VentLine` | 근사 | 설비 벤트(`EquipmentVent`)와 배관 벤트를 우리는 구분하지 않음 |
| `drain`, `test_connection`, `pipe_cap` | — | 없음 | 뺌 |
| (가져올 때만) `Flange`, `SightGlass`, `Compensator`, `Hose`, `SteamTrap`, `Silencer`, `FlameArrestor` 등 | — | 없음 | 미분류 배관 부품으로 가져옴(§5.5) |
| 계기(`transmitter`, `controller`, `indicator`, `recorder`, `switch`, `temperature_element`) | `ProcessInstrumentationFunction`(태그 단위 기능). 측정 소자·신호 발생은 `ProcessSignalGeneratingFunction`, 루프는 `InstrumentationLoopFunction`, 안전 쪽은 `ProcessSafetyFunction`·`ProcessControlFunction` | 근사 | 우리 계기 노드는 태그 하나 = 노드 하나. DEXPI는 기능과 장치를 나눔. 가져올 때 계측 기능 하나를 계기 노드 하나로 보고, `kind`는 기능 문자(`ProcessInstrumentationFunctionCategory`+`Functions`)를 `hazop/extract/isa.py`로 읽어 정함. 못 정하면 미분류 계기 |
| `isa`(측정변수·기능 문자·루프 번호) | `ProcessInstrumentationFunctionCategory`, `ProcessInstrumentationFunctions`, `ProcessInstrumentationFunctionNumber`, `InstrumentationLoopFunctionNumber` | 맞음 | |

### 3.5 태그·번호·속성

| 우리 쪽 | DEXPI 2.0.1 속성 | 정도 | 규칙 |
| --- | --- | --- | --- |
| 설비 `tag` | `TagName`(또는 `TagNamePrefix`+`TagNameSequenceNumber`+`TagNameSuffix`) | 맞음 | `TagName`을 먼저 씀. 없으면 세 조각을 이어 붙이고 `tag_basis`에 '조각 결합'을 남김 |
| 밸브·부품 `tag` | `PipingComponentNumber`, 없으면 `SubTagName` | 근사 | DEXPI는 부품 번호가 태그가 아닐 수 있음. 가져온 `tag`에 근거 이름을 남김 |
| 계기 `tag` | `ProcessInstrumentationFunctionCategory` + `ProcessInstrumentationFunctionNumber` | 근사 | 예제 `P`·`4712.02` 같은 표기. 우리 태그 모양(`PT-4712`)과 다름. 가져올 때 두 값을 공백 없이 이은 값을 `tag`로, 원래 조각은 `attributes`에 둠 |
| `line_no` | `PipingNetworkSystem.LineNumber` | 맞음 | |
| `fluid_code` | `FluidCode`(구간·계통) | 맞음 | |
| `pipe_class` | `PipingClassCode` | 맞음 | |
| `nominal_diameter` | `NominalDiameterRepresentation`(예 `DN 80`), `NominalDiameterNumericalValueRepresentation`, `NominalDiameterStandard`(열거) | 맞음 | 원문 문자열을 그대로 보존(우리 규칙: 단위 원문 보존) |
| `material` | `MaterialOfConstructionCode` | 맞음 | 설비는 `Chamber` 단위로 있음 |
| `design_pressure_max/min`, `design_temperature_max/min` | `UpperLimitDesignPressure`·`LowerLimitDesignPressure`·`UpperLimitDesignTemperature`·`LowerLimitDesignTemperature`. 값은 `Core/PhysicalQuantities.PhysicalQuantity`(`Value` + `Unit`, 예 `PressureGaugeUnit.Bar`) | 근사 | DEXPI는 설비의 **챔버**에 둡니다. 챔버가 하나면 설비 값으로, 둘 이상이면(열교환기 관측·동체측) 설비 값으로 합치지 않고 `attributes["dexpi:chambers"]`에 챔버별로 둠. 압력 기준(계기압·절대압)은 단위 열거 이름(`PressureGaugeUnit`·`PressureAbsoluteUnit`)에서 읽음 |
| `insulation` | `InsulationType`, `InsulationThickness` | 맞음 | |
| `set_pressure` | `SetPressureHigh` 등 | 확인 못 함 | 구현 때 원문 확인. 못 찾으면 곁 파일 |
| `rated_flow`, `rated_head` | `DesignVolumeFlowRate`, `DesignPressureHead` | 근사 | '정격'과 '설계'의 뜻 차이를 곁 파일에 적음 |
| `safety_class`, `seismic_category`, `quality_group`, `system_code`, `train`, `channel` | — | 없음 | 원자력 고유. 곁 파일 |
| `normal_operating_pressure/temperature`, `normal_level`, `npsh_required`, `shutoff_head`, 설정치·경보치 | — 또는 확인 못 함 | 없음 | 곁 파일 |

### 3.6 맞는 자리가 없는 정보(모음)

DEXPI 쪽에 없는 것: 근거(어느 문서·쪽·좌표에서 읽었나), 확신도, 미확인 목록, 사람 수정 이력(`human_edit`), AI 후보 상태, 지식그래프의 문서·지식 층, 검토구간, HAZOP 결과·권고, 초기사건, 흐름 방향, 체크밸브 허용 방향, 원자력 고유 속성(안전 등급, 내진 범주, 품질 등급, 계통 코드, 계열), 정상 위치.

우리 쪽에 없는 것(가져올 때 미분류나 `attributes`로만 둠): DEXPI의 공정 모델(Process, 2.0에 합쳐진 PFD·BFD), 설비 내부 부품, 구동 전기계(`ActuatingElectricalSystem`), 플랜트 구조(`PlantStructure`의 구역·계열), 다국어 문자열, 그림 쪽 글자 양식.

레지스트리(`hazop/kg/schema/registry.json`)의 `dexpi_class`는 위 표와 다른 곳이 있습니다. `steam_generator`에 `dexpi_class`가 없는 것은 맞고, 앞으로도 `SteamGenerator`를 넣지 않습니다. 구현 단위(X1)가 레지스트리를 이 표에 맞추고, 대응표는 `dexpi_map.py` 한 곳에서 읽게 합니다.

## 4. 등록 흐름에서의 자리

1. **등록.** `hazop/register/fileinfo.py`의 `detect_format`이 XML 뿌리를 봅니다. 지금은 `mxfile`·`mxGraphModel`이면 `drawio`, 아니면 `xml`입니다. 여기에 뿌리가 `Model`이고 `Import`가 `…/models/2.0.x/Plant.xml`을 가리키면 `dexpi_xml`, 뿌리가 `PlantModel`이고 `PlantInformation`이 있으면 `proteus`를 더합니다. 확장자는 `.xml`(Proteus 예제도 `.xml`)이라 확장자와 형식이 다른지는 '`.xml`이면 셋 중 하나'로 검사합니다.
2. **도면 수.** 2.0 파일 하나에 `Diagram`이 여럿일 수 있고 Proteus는 보통 `Drawing` 하나입니다. 등록은 PDF처럼 도면마다 쪽 ID(`page-<번호>`)를 줍니다. 도면이 없고 설비 모델만 있는 파일은 쪽 하나로 등록하고 '그림 없음'을 미확인에 적습니다.
3. **표제란.** `PlantMetaData`(2.0) 또는 `MetaData`의 `DrawingNumber`·`DrawingName`·개정 관련 값을 등록의 '자동 후보'로 기록합니다. 사람이 확정하기 전에는 확정값으로 쓰지 않습니다([등록 규칙 4](registration.md)). 파일에 적혀 있다고 바로 확정하지 않는 것은 drawio·PDF와 같습니다.
4. **'추출 시작'.** `hazop/app/data.py:110 extract_and_graph`가 형식으로 갈래를 탑니다(지금 `pdf`와 그 밖). 여기에 `dexpi_xml`·`proteus` 갈래를 더해 새 스크립트 `scripts/extract_dexpi.py`의 `run_one`을 부르고, 그 뒤 그래프 만들기는 지금처럼 `build_graph.build_one`을 씁니다. 원본 옆 SVG 찾기(`registry._unknowns`의 `NO_SVG_FIELD`)는 DEXPI에는 적용하지 않습니다(그림이 파일 안에 있음).
5. **읽은 방법 표시.** 추출 실행 정보(`runinfo`)와 그래프 `source`에 `read_method`를 둡니다. 값은 `drawio`·`pdf_vector`·`raster`·`dexpi`. 화면은 `dexpi`를 '변환(DEXPI 2.0.1)'·'변환(DEXPI 1.3, Proteus 4.1.1)'처럼 판과 함께 보입니다. 노드의 `origin`은 지금처럼 `pid_extract`(도면에서 옴)로 두고 새 값을 만들지 않습니다(§9 V-4). '인식했나 변환했나'는 노드가 아니라 도면의 성질이기 때문입니다.
6. **기본 보기.** INTENT §3.8대로 DEXPI로 들어온 도면은 정리된 보기가 기본입니다. 그 보기가 쓸 위치는 §5.3이 만듭니다.

## 5. 가져오기 규칙

### 5.1 XML 읽기의 보안

DEXPI 파일은 밖에서 온 파일입니다. 읽기 전에 아래를 모두 지킵니다.

- **DTD·개체 선언 금지.** `xml.etree.ElementTree.XMLParser`의 expat 파서에 `StartDoctypeDeclHandler`·`EntityDeclHandler`를 걸어, `<!DOCTYPE`나 `<!ENTITY`가 나오면 바로 거절합니다(사유 `dexpi_doctype_forbidden`). DEXPI 예제는 둘 다 쓰지 않습니다. 시험 venv의 파서는 expat 2.7.1이라 외부 개체를 가져오지 않지만, 판에 기대지 않고 선언 자체를 막습니다.
- **네트워크 금지.** `Import source="https://data.dexpi.org/models/2.0.1/Plant.xml"`은 이름표로만 읽고 내려받지 않습니다. 판 번호(`2.0.1`)만 뽑아 앱에 묶은 클래스 목록과 맞춥니다.
- **크기 한도.** 파일 100MB, 요소 300만 개, 깊이 256단계를 넘으면 거절합니다. 참고로 2.0.1 Reference P&ID는 1.5MB, 요소 약 2만 개입니다(받은 예제로 셈). 한도는 상수 하나로 두고 넘으면 '파일이 너무 큼, 한도 ○○'으로 알립니다.
- **XML 밖 내용.** 파일 안의 스크립트·링크·이미지 경로는 읽거나 열지 않습니다. 그림 쪽 글자는 화면에 낼 때 지금 SVG 처리(`hazop/viewer/sanitize.py`)와 같은 규칙으로 걸러 냅니다.
- 이 규칙은 읽기 전용 함수 하나(`hazop/extract/adapters/dexpi_read.py`의 `parse_safely`)에 모으고, 등록의 형식 판별도 이 함수를 씁니다.

### 5.2 ID와 태그

- 추출 노드의 `source_object_id`는 DEXPI `id`(2.0) 또는 `ID`(Proteus)를 그대로 씁니다. 2.0에서는 `id`가 생략될 수 있으므로, 없으면 '부모 `id` + 속성 이름 + 순번'으로 경로 ID를 만듭니다(예 `PlantModel1/PipingNetworkSystems/3`). 같은 파일이면 늘 같은 값이 나와야 합니다.
- `local_id`는 `dx-` + `source_object_id`를 이름 문자 규칙에 맞게 바꾼 값입니다. 그래프 엔터티 ID(`entity-node-NNN`)는 지금처럼 ③이 매깁니다.
- 같은 파일을 다시 가져오면 같은 `extraction.json`이 나와야 합니다(결정적 순서: 파일 안 순서). 그래야 `graph_version`이 같고 구간·결과가 '재확인'으로 가지 않습니다.
- 태그는 §3.5 규칙으로 정합니다. 태그가 없는 객체도 버리지 않습니다(추출 공통 계약). 지금 규칙대로 `tag` 미확인을 남깁니다.

### 5.3 좌표

- 그림 쪽(2.0의 `Core/Diagram.*`, Proteus의 `Position`·`Extent`)을 읽어 노드 `bbox`·`position`과 관계 `waypoints`를 채웁니다. 이 값이 정리된 보기와 원본 보기의 위치가 됩니다.
- 좌표계는 `coordinate_system = {"coordinate_space": "dexpi_diagram", "unit": "mm", "origin": "top_left", "source_origin": …}`로 적습니다. **Y축 방향은 사양 문장으로 확인하지 못했습니다**(F15). 그래서 구현 첫 작업으로 2.0.1 Reference P&ID의 공식 SVG 그림(사양 부록에 있음)과 읽은 좌표를 겹쳐 보고 방향을 정해 이 절을 고칩니다. 화면은 위가 0인 좌표를 쓰므로 필요하면 `y' = 도면 높이 − y`로 뒤집고, 원래 값은 `attributes["dexpi:position"]`에 둡니다.
- 위치 정보가 없는 객체(그림 없이 모델만 있는 파일, 그림 쪽에서 `Represents`가 가리키지 않는 객체)는 `bbox: null`로 둡니다. 정리된 보기가 이런 객체를 어떻게 놓을지는 `d-chat` 규격이 정합니다.
- 노드 크기는 `ShapeUsage`가 쓰는 `Shape`의 테두리 × `ScaleX/Y`, 회전은 `Rotation`(도)으로 셉니다. 계산이 안 되면 위치만 두고 크기는 '확인 못 함'.

### 5.4 흐름 방향

DEXPI 연결의 Source→Target은 '연결이 시작하고 끝나는 곳'이지 흐름 방향이 아닙니다(F13). 그래서 이것만으로 `flow_direction`을 정하지 않습니다. 근거가 될 수 있는 것과 다루는 법:

| 근거 | 다루는 법 |
| --- | --- |
| 연결 Source→Target | `flow_direction`을 만들지 않음. 지금 규칙대로 `unknown_flow_direction`이 남음 |
| 흐름 화살표 그림(`PipeFlowArrow`)이 그 구간에 있고 방향이 선과 맞음 | `flow_direction` + `basis: "dexpi_flow_arrow"`, 상태는 drawio의 작성자 선언과 같은 `declared` |
| 구간 끝이 `FlowInPipeOffPageConnector`/`FlowOutPipeOffPageConnector` | 같은 방식으로 `basis: "dexpi_off_page_connector"`, `declared` |
| 체크밸브 | 방향을 정하지 않음. 지금처럼 `unknown_check_valve_direction` |

`declared`는 사람 확인 전 값이라 ④·⑤에서 지금처럼 '작성자 선언(미확인)'으로 보입니다.

### 5.5 모르는 클래스와 속성

- 대응표에 없는 클래스는 버리지 않고 **미분류 노드**(`kind: null`, `classification: "unclassified"`)로 가져옵니다. `category`는 DEXPI 상위 클래스로 정합니다(`ProcessEquipment` 하위 → `equipment`, `PipingComponent` 하위 → `inline_component`, 계장 → `instrument`). 미확인 `dexpi_unmapped_class`(target=그 노드, field=`kind`, reason에 DEXPI 클래스 이름)를 남깁니다.
- 근거로 DEXPI 원문을 남깁니다: 노드 `evidence.dexpi = {"type", "id", "xml"}`. `xml`은 그 객체의 원문 조각이며, 그림 쪽을 뺀 4KB까지만 두고 넘으면 잘랐다고 적습니다.
- 대응표에 없는 속성은 `attributes["dexpi:<속성 이름>"]`에 문자열로 둡니다. 물리량은 `"60.0 PressureGaugeUnit.Bar"`처럼 값과 단위를 함께 적습니다.
- 공정 모델(Process)의 객체는 이번 범위에서 가져오지 않고 개수만 실행 정보에 적습니다.

### 5.6 검증

가져오기는 아래 순서로 검사하고, 어느 층에서 걸렸는지 사람에게 따로 보입니다.

1. **보안 검사**(§5.1). 걸리면 등록하지 않습니다.
2. **스키마 검사.** 2.0: 앱에 묶은 DEXPI XML 스키마(`dexpi-xml-schema.xsd`)로 검사합니다. 이 XSD는 `Model`·`Object`·`Data` 같은 틀만 검사하고 클래스 이름은 검사하지 않습니다(DEXPI XML은 클래스를 `type` 문자열로 적는 일반 틀이기 때문). 그래서 3번이 따로 필요합니다. Proteus: 스키마를 묶지 못하므로(F8) 3·4번 구조 검사만 합니다. 스키마 검사 실패는 '형식 오류'로 등록을 막습니다.
3. **클래스 검사.** `type`(2.0)과 `ComponentClass`(Proteus)가 그 판의 클래스 목록에 있는지 봅니다. 클래스 목록은 2.0.1 원문(S11)에서 뽑아 `resources/library/dexpi/2-0-1/classes.json`으로 묶습니다. 없는 클래스는 막지 않고 §5.5대로 미분류로 가져옵니다.
4. **참조 검사.** `#ID` 참조(`References objects`, `ObjectReference`, `SourceItem`·`TargetItem` 등)와 Proteus `Connection FromID/ToID`가 파일 안에 있는지, `id`가 겹치지 않는지 봅니다. 끝을 못 찾는 연결은 정상 관계가 아니라 `unresolved_connectors`로 보내고 지금 규칙대로 `unconnected_endpoint`를 남깁니다. 겹치는 `id`는 차단 오류(`validation.blockers`)로 둡니다(어느 객체를 가리키는지 정할 수 없으므로).
5. **우리 쪽 구조 검사.** 만든 `extraction.json`을 지금 추출 결과 검증에 그대로 넣습니다.

스키마 검사 도구는 순수 Python 패키지 `xmlschema`(MIT 라이선스)를 권장합니다(§9 V-5). 지금 시험 venv에는 `lxml`도 `xmlschema`도 없습니다(2026-11-13 확인). 배포 묶음(`packaging/requirements.txt`)에 판과 해시를 고정해 더합니다.

## 6. 내보내기 규칙

### 6.1 범위와 형식

- 형식은 DEXPI XML 2.0.1 하나입니다(§9 V-1). Proteus 내보내기는 받을 쪽 CAD가 2.0을 못 읽는다는 것이 확인되면 별도 단위로 합니다.
- 단위는 **도면 하나 = 파일 하나**입니다. 프로젝트 전체는 도면별 파일 여러 개와 묶음 목록(`manifest.json`)으로 냅니다. 도면 사이는 연결 기호의 `PipeOffPageConnectorReferenceByNumber`(상대 도면 번호·연결 번호)로 잇습니다. 프로젝트 그래프가 맞춘 연결점 짝(`hazop/graph/project.py`의 `continuation_key`)을 그대로 씁니다.
- 내보낼 수 있는 도면은 도면 번호가 사람 확정된 도면뿐입니다. 도면 번호 없이는 도면 간 참조를 쓸 수 없기 때문입니다.

### 6.2 무엇을 내보내는가

| 대상 | 내보냄 | 뺌 |
| --- | --- | --- |
| 추출 노드·관계(`origin: pid_extract`) | 미확인이 없거나 속성 미확인만 있는 것 | 아래 '뺌' 조건에 걸린 것 |
| 사람 수정(`origin: human_edit`) | 모두(사람이 고친 것이 최종 값) | — |
| AI 후보 | 사람이 수락한 것(`status: accepted`, 노드 `origin: ai` + `accepted_by`) | 제안 상태(`proposed`)·기각(`rejected`)인 것 전부 |
| 끝이 미확정인 연결(`unresolved_connectors`) | — | 모두 |
| 분류 못 한 노드(`kind` 없음) | — | 모두. 단 DEXPI에서 가져온 미분류 노드는 원문 조각으로 되살림(§7.2) |
| 대응이 '없음'인 `kind`(`damper`, `drain`, `test_connection`, `pipe_cap`) | — | 모두. 그 노드에 붙은 연결은 양쪽 이웃을 직접 잇지 않고(없는 연결을 지어내지 않음) 끊긴 채 둠 |
| 지식그래프 문서·지식 층, 기대 후보, 검토구간, HAZOP 결과, 초기사건 | — | 모두(DEXPI에 자리가 없음, §6.3) |

**미확인이 남은 구성요소의 처리(권장, §9 V-2).** '빼기'와 '표시' 가운데 **구성요소 단위는 빼고, 속성 단위는 그 속성만 빼는 것**을 권장합니다.

- 구성요소 자체가 불확실한 것(분류 못 함, 끝이 미확정인 연결, 제안 상태 AI 후보)은 뺍니다.
- 구성요소는 확실하고 속성만 미확인인 것(태그 미확인, 흐름 방향 미확인, 고장 시 위치 미확인 등)은 구성요소를 내보내고 그 속성은 쓰지 않습니다. 추측값을 넣지 않습니다.
- 'DEXPI 파일 안에 미확인이라고 표시'하는 방식은 고르지 않습니다. DEXPI에 미확인을 적는 표준 자리가 없어 확장(`ClassExtension`)을 써야 하고, 받는 CAD는 그 표시를 모른 채 값을 확정값으로 읽을 수 있습니다.
- 뺀 것과 속성을 뺀 것은 함께 내는 목록(§6.4)에 모두 적습니다.

### 6.3 DEXPI에 자리가 없는 정보

**권장(§9 V-6): DEXPI 파일에는 넣지 않고 곁 파일로 냅니다.** 근거, 확신도, 수정 이력, 미확인, 검토구간, HAZOP 결과, 원자력 고유 속성은 `<도면번호>.hazop.json`(곁 파일)에 담고, DEXPI 객체 `id` ↔ 우리 `entity_id` 대응표를 함께 둡니다.

- 확장 속성(`ClassExtension`)으로 DEXPI 파일 안에 넣는 방법도 있지만, 받는 도구가 모르는 확장을 거절할 수 있고 인증 시험과도 어긋날 수 있습니다. 앞으로 필요해지면 확장 이름공간을 `HAZOP`으로 따로 두는 별도 단위로 합니다.
- 곁 파일은 같은 앱이 다시 가져올 때만 씁니다(§7). 다른 도구는 무시해도 DEXPI 파일만으로 온전합니다.

### 6.4 함께 내는 파일

| 파일 | 내용 |
| --- | --- |
| `<도면번호>.dexpi.xml` | DEXPI XML 2.0.1 |
| `<도면번호>.excluded.json` | 뺀 구성요소(`entity_id`, `kind`, `tag`, 사유 코드)와 뺀 속성(`entity_id`, 속성, 사유), '근사'로 바꾼 것(`condenser` → `HeatExchanger` 등). 사유 코드는 미확인 코드를 그대로 씀 |
| `<도면번호>.hazop.json` | 곁 파일(§6.3) |
| `manifest.json`(프로젝트 내보내기일 때) | 도면 목록, 앱 판, 내보낸 시각, 그래프 판(`graph_version`), DEXPI 판, 출처 표시 문구(CC BY 4.0: 'DEXPI Specification 2.0.1, DEXPI e.V., CC BY 4.0') |

### 6.5 내보내기 검사

파일을 쓰기 전에 아래를 통과해야 합니다. 하나라도 실패하면 아무 파일도 쓰지 않고 실패 이유를 보입니다.

1. 앱에 묶은 DEXPI XML 스키마(`dexpi-xml-schema.xsd`) 검사 통과.
2. 모든 `type`이 2.0.1 클래스 목록(`classes.json`)에 있음.
3. 모든 `#ID` 참조가 파일 안에 있음, `id`가 겹치지 않음.
4. 되읽기: 쓴 내용을 §5 가져오기로 다시 읽어, 내보낸 구성요소 수·연결 수·태그 목록이 같음.

받은 CAD에서 실제로 열리는지는 이 앱이 검사할 수 없습니다. 공개 검증 도구(DEXPI 검증기 `dexpi/dexpi-verificator`)는 저장소에 README만 있어 쓸 수 있는지 **확인 못 함**입니다.

## 7. 왕복에서 지켜야 할 것

### 7.1 DEXPI → 우리 → DEXPI (사람 수정 없음)

| 지켜야 함 | 허용하는 차이 |
| --- | --- |
| 대응이 '맞음'·'근사'인 객체의 `id`와 클래스(`type`) | 하위 클래스 → 상위 클래스로 바뀌지 않아야 함(가져올 때 `dexpi:type`을 남겼다가 되씀) |
| 연결의 양 끝(어느 객체의 어느 노즐) | 연결 순서 |
| 태그·라인 번호·유체 코드·배관 등급·호칭 지름 원문 | 없음 |
| 설계 압력·온도 값과 단위 | 없음 |
| 도면 간 연결 참조(상대 도면 번호, 연결 번호) | 없음 |
| 그림 위치(`Position`) | 0.01mm 이하 |
| 대응이 없어 미분류로 가져온 객체 | 원문 조각으로 되살림(§7.2) |
| 공정 모델(Process) 객체 | 되살리지 않음(이번 범위 밖). 뺀 목록에 개수 |
| 그림 쪽 글자 양식·색·선 굵기 | 되살리지 않아도 됨 |

### 7.2 미분류 객체 되살리기

가져올 때 남긴 원문 조각(`evidence.dexpi.xml`)은 사람이 그 노드를 고치지 않았을 때만 그대로 되씁니다. 사람이 분류나 연결을 고쳤으면 원문을 버리고 고친 값으로 냅니다. 원문 조각이 4KB에서 잘렸으면 되살리지 않고 뺀 목록에 적습니다.

### 7.3 우리 → DEXPI → 우리

drawio·PDF에서 읽은 도면을 내보내고 다시 가져왔을 때:

- 같아야 함: 내보낸 노드 수와 `kind`(근사 대응은 곁 파일로 되돌림), 연결의 양 끝, 태그, 라인 속성, 도면 간 연결.
- 달라도 됨: 엔터티 ID 번호(③이 다시 매김), `origin`(원래 `human_edit`였어도 다시 가져오면 `pid_extract`, 대신 곁 파일의 수정 이력이 남음), 흐름 방향(§5.4 근거가 없으면 미확인으로 돌아옴. 이 차이는 뺀 목록에 '흐름 방향은 DEXPI에 자리가 없음'으로 적음).
- 곁 파일이 있으면 가져오기가 `entity_id` 대응표로 원래 노드에 근거와 수정 이력을 되붙입니다. 곁 파일의 그래프 판이 다르면 되붙이지 않고 알립니다.

### 7.4 구간 경계

우리 배관 구간 노드는 연결 하나이고 DEXPI 구간은 줄기 하나라서(§3.1), 내보낼 때 묶은 구간이 원래 DEXPI 구간과 다를 수 있습니다. 원래 구간 ID(`dexpi:segment`)가 남아 있으면 그 묶음을 먼저 따릅니다.

## 8. 구현 단위

### 8.1 단위표

| 단위 | 대상 파일 | 완료 기준 | 시험 | 모델(배정표) |
| --- | --- | --- | --- | --- |
| **X1 가져오기** | 새: `hazop/extract/adapters/dexpi_read.py`(안전한 읽기, 2.0·Proteus 두 읽기를 같은 중간 형태로), `hazop/extract/adapters/dexpi_import.py`(중간 형태 → `extraction.json`), `hazop/extract/dexpi_map.py`(대응표, X2와 공유), `scripts/extract_dexpi.py`, `resources/library/dexpi/2-0-1/`(`dexpi-xml-schema.xsd`는 원본 `DEXPI_XML_Schema.xsd`를 이름 규칙에 맞게 바꾼 것, `classes.json`), `licenses/dexpi/`(CC BY 4.0 출처·변경 표시). 고침: `hazop/register/fileinfo.py`(형식 판별), `hazop/register/registry.py`(쪽 목록, 표제란 후보, SVG 찾기 제외), `hazop/app/data.py`(갈래), `hazop/extract/runinfo.py`·`hazop/graph/build.py`(`read_method` 전달, `BUILDER_VERSION`은 올리지 않음), `hazop/kg/schema/registry.json`(`dexpi_class`), `packaging/requirements.txt`(`xmlschema`) | §5 규칙대로 두 형식을 읽어 지금 그래프 변환을 통과. 같은 파일을 두 번 가져오면 같은 `graph_version`. Y축 방향을 정해 §5.3을 고침 | `tests/test_dexpi_import.py`: 손으로 만든 작은 DEXPI 파일(펌프―밸브―탱크, 노즐 둘, 도면 연결 기호 하나, 모르는 클래스 하나, 흐름 화살표 하나)을 2.0과 Proteus 두 형식으로 `tests/fixtures/dexpi/`에 둠. DOCTYPE·개체 선언·크기 초과·겹친 `id`·끊긴 참조 거절. 공개 예제(Reference P&ID 2.0.1, TrainingTestCases C01·C03·C08)는 `HAZOP_DEXPI_SAMPLES`가 있을 때만 돌고 없으면 건너뜀 | Opus 5.5 medium(ID·출처 경로). Y축 확인 같은 곁일은 Sonnet 하위 에이전트 |
| **X2 내보내기** | 새: `hazop/export/dexpi_export.py`, `scripts/export_dexpi.py`. 씀: `dexpi_map.py`, `resources/library/dexpi/2-0-1/` | §6 규칙대로 내보내고 §6.5 검사 통과. 뺀 목록·곁 파일·묶음 목록 | `tests/test_dexpi_export.py`: 가상 도면 SNP 6세트(drawio)를 내보내 스키마 검사 통과, 뺀 목록이 미확인과 맞음(예: `missing_port` 16건은 노즐 이름 `N1`… 근사로 적힘). §7.3 왕복. X1이 끝난 뒤 §7.1 왕복(손으로 만든 파일과 공개 예제) | Opus 5.5 medium(무엇을 뺄지의 판정 경로) |
| **X3 화면 자리** | `hazop/shell/`(등록 끌어 놓기, 내보내기 단추) | §8.2 자리에 붙음 | `tests/test_shell_*`의 해당 시험 | Sonnet 5.5 medium |
| X4 Proteus 내보내기(필요할 때만) | `hazop/export/dexpi_proteus.py` | 받을 CAD가 2.0을 못 읽는다는 확인 + 사용자 결정 뒤 | Proteus 스키마 이용 조건이 확인되기 전에는 구조 검사만 | 나중에 정함 |

- 순서: X1 → X2 → X3. X2는 X1의 `dexpi_map.py`와 되읽기를 쓰므로 이어서 합니다. INTENT §3.8이 '정리된 보기와 DEXPI 내보내기는 같은 단위로 만든다'고 정했으므로, X2는 `d-chat`이 설계하는 정리된 보기 단위와 같은 차례에 묶고, 두 단위가 같이 쓰는 위치 계산(§5.3)은 X1이 만든 것을 씁니다.
- 파일 주인: `dexpi_map.py`는 X1이 만들고 X2는 읽기만 합니다. `registry.json`은 X1만 고칩니다.
- 기준값: 가져오기는 기존 추출 점수(`check_apr1400.py`, `check_snp_baseline.py`)의 입력을 바꾸지 않습니다. `hazop/graph/build.py`를 고치므로 X1 커밋 전에 두 검사가 그대로인지 확인합니다(CLAUDE.md 규칙 12).

### 8.2 화면 자리(새 화면 규격 `app-shell-web.md` 기준, 그 문서는 고치지 않음)

| 기능 | 들어갈 자리 | 근거 줄 |
| --- | --- | --- |
| DEXPI 파일 받기 | 패널 '도면'의 끌어 놓기 자리(§2.3 ①등록 표, '등록'과 '추출·그래프 만들기'를 합친 줄). 엔진 쪽은 `register.add`(웹이 보내지 않고 Qt가 경로를 받음, §5.2 명령표) | `app-shell-web.md:165`, `:519` |
| 읽은 방법 '변환(DEXPI …)' 표시 | 패널 '도면' 목록 행의 상태 칩과 '더 보기' '추출 보고' | `app-shell-web.md:160`, `:170` |
| DEXPI 내보내기 단추 | 정리된 보기와 같은 자리에 둘지 분석 결과 머리 '내보내기'(Excel·IE 인계 묶음 옆)에 둘지는 `d-chat`이 정합니다. 이 규격의 권장은 **패널 '도면' 머리**입니다. DEXPI는 도면의 내보내기이고, 분석 결과 내보내기와 섞으면 '한 기능은 한 자리'(§2.2 원칙 5)를 지키기 어렵기 때문입니다 | `app-shell-web.md:96`, `:146`, `:234` |
| 웹 명령 | `export.dexpi`(`scope`: 도면 번호 목록 또는 프로젝트, 저장 위치는 Qt 대화상자), 읽기 명령. `export.excel`·`export.ie_bundle` 줄과 같은 꼴 | `app-shell-web.md:533` |

### 8.3 공개 예제를 시험 입력으로 쓰는 법

- 쓸 수 있음: 2.0.1 Reference P&ID와 TrainingTestCases(둘 다 CC BY 4.0, F9). 출처 표시는 시험 파일 머리 주석과 `licenses/dexpi/`에 적습니다.
- 저장소에는 넣지 않습니다(총괄 지시). 시험은 환경변수 `HAZOP_DEXPI_SAMPLES`가 가리키는 폴더(지금은 `D:\HAZOP-trials\2026-11-13-dexpi\`)에 파일이 있을 때만 돌고, 없으면 건너뜁니다. CI에서는 손으로 만든 작은 파일만 돕니다.
- 앱에 묶는 것은 2.0.1 XSD와 클래스 목록뿐입니다(CC BY 4.0, 출처·변경 표시). Proteus XSD는 이용 조건을 확인하기 전에는 묶지 않습니다.

## 9. 총괄 위임으로 정한 것

질문 창을 띄우지 않고 권장안으로 정했습니다. 사용자가 다르게 정하면 이 표와 해당 절을 고칩니다.

| # | 정할 것 | 고른 것 | 이유 | 다른 안 |
| --- | --- | --- | --- | --- |
| V-1 | 어느 형식으로 주고받나 | 가져오기는 DEXPI XML 2.0.x와 Proteus 4.x(DEXPI 1.2~1.4) 둘 다, 내보내기는 DEXPI XML 2.0.1만 | 2.0부터 Proteus를 쓰지 않는 것이 공식 판(F1·F4). 그러나 지금 CAD 도구는 1.x 파일을 낼 가능성이 커서 받을 때는 둘 다 받아야 함. 2.0.1 스키마는 CC BY 4.0이라 앱에 묶어 검사할 수 있지만 Proteus 스키마는 이용 조건을 모름(F8) | 내보내기도 Proteus(받는 CAD 호환이 큼, 스키마 검사를 못 함) |
| V-2 | 미확인이 남은 구성요소 | 구성요소가 불확실하면 빼고, 속성만 미확인이면 그 속성만 뺌. 뺀 목록을 함께 냄 | 받는 쪽이 미확인 표시를 모른 채 확정값으로 읽는 일을 막음 | 확장 속성으로 표시 |
| V-3 | 노즐 | 가져올 때 노즐을 노드로 만들지 않고 끝점 `port`로 바꿈 | 지금 그래프 모양·구간 분할·탐색을 그대로 씀. 포트 규칙(A2)과 같은 자리 | 노즐을 노드로 둠(`kind=nozzle`, 탐색 경로가 한 단계 길어짐) |
| V-4 | 가져온 노드의 `origin` | 새 값을 만들지 않고 `pid_extract`. 도면에 `read_method: dexpi` | 읽은 방법은 도면의 성질. `origin`을 쓰는 곳(지식그래프 상태, ④ 근거, 화면 표시)을 바꾸지 않음 | `origin: dexpi_import` 신설 |
| V-5 | 스키마 검사 도구 | `xmlschema`(순수 Python, MIT) | 패키징이 쉽고 1.5MB 파일엔 속도가 충분. 네트워크 없이 묶은 XSD만 씀 | `lxml`(빠름, C 확장 묶음 필요) |
| V-6 | DEXPI에 자리가 없는 정보 | DEXPI 파일에 넣지 않고 곁 파일 | 받는 도구와의 호환과 인증 시험을 해치지 않음 | `ClassExtension`으로 파일 안에 |
| V-7 | DEXPI `SteamGenerator` | 원전 증기발생기를 이 클래스로 내보내지 않고 `HeatExchanger`로 | DEXPI의 것은 가열로 계열(F12) | 이름이 같은 `SteamGenerator` |
| V-8 | 흐름 방향 | 연결 Source→Target으로 정하지 않음. 흐름 화살표·연결 기호만 `declared`로 | 사양이 흐름 방향이라고 적지 않음(F13) | Source→Target을 흐름으로 봄 |

## 10. 사용자·총괄에게 넘길 것

- **INTENT 표기.** §2·§3.1·§3.2의 'DEXPI(Proteus XML)'은 2.0 이후와 맞지 않습니다(§0). 'DEXPI(지금 판 2.0.1, DEXPI XML. 받을 때는 1.x Proteus도)'로 고칠지 총괄이 정합니다. 이 문서는 INTENT를 고치지 않았습니다.
- **INTENT §6의 보류 'DEXPI 판(2.0 여부)과 라이선스 조건'**은 F1~F11로 대부분 닫힙니다. 남은 것: DEXPI XML 스키마 파일 단위 라이선스(F7), Proteus 스키마 이용 조건(F8), 'DEXPI' 이름 사용 조건(F10). 앱이 'DEXPI 지원'이라고 표시하려면 F10을 DEXPI e.V.에 묻는 것이 안전합니다.
- **문서 목록.** `docs/specs/README.md`의 문서 목록에 이 문서를 더하는 일은 그 파일 주인이 합니다(이 단위의 파일 주인은 이 문서와 문서번호 표 한 줄뿐).
- **추출 규격의 'DEXPI 용어 대응(A13)'** 절(`extraction.md`)은 '원문 미확인' 후보 표입니다. 이 문서 §3이 원문으로 확인한 표이므로, 그 절을 이 문서로 가리키게 고치는 일을 `extraction.md` 주인에게 넘깁니다.

## 11. 확인하지 못한 것

- Y축 방향(F15). X1 첫 작업에서 정합니다.
- DEXPI XML 스키마 파일 단위의 라이선스 명시(F7), Proteus 스키마 이용 조건(F8), 'DEXPI' 이름 사용 조건(F10), 인증 신청 자격(F11).
- 2.0 형식을 내보내는 CAD 도구가 있는지.
- `FailAction` 열거값 가운데 `FailClose` 말고 다른 값 이름, `set_pressure`·구동 방식에 맞는 DEXPI 속성 이름.
- DEXPI 검증기(`dexpi/dexpi-verificator`)를 쓸 수 있는지(저장소에 README만 있음).
- 공정 모델(Process) 객체를 가져올지는 이번 범위 밖으로 두었습니다.
- pstack: 지난 차례에 Skill 호출이 `disable-model-invocation`으로 막힌 것을 확인했으므로, 이번에는 총괄 지시대로 `technical-writing`·`unslop`의 SKILL.md를 직접 읽고 그 기준으로 이 문서를 다듬었습니다. 설계 판단은 대부분 공식 자료 확인에 달려 있어 `architect`·`poteto-mode`의 절차는 쓰지 않았습니다.
