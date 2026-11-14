---
doc_id: HZ-PLN-22
rev: 2
status: review
author: D-node 세션(2026-11-13)
reviewed: —
approved: —
---

# DEXPI 가져오기·내보내기

[INTENT §2·§3.1·§3.2·§3.8](../../INTENT.md) · [정보 추출](extraction.md) · [지식그래프 스키마 사전](kg-schema-dictionary.md) · [자료 등록](registration.md) · [새 화면 규격](../design/app-shell-web.md) · 구현 코드 `hazop/extract/`, `hazop/graph/`

- 작성일 2026-11-13, rev 1 2026-11-14, rev 2 2026-11-14(§6.2 '이대로 확인'한 구성요소는 멈추지 않고 빼고 냄, §6.1 확정한 자료로 그래프를 만들어 냄). 상태는 **규격 초안**입니다. 코드는 고치지 않았습니다. 코드 줄 번호는 rev 0이 커밋 `abb7b2a`, rev 1에서 고친 곳이 커밋 `f6ad283` 기준입니다.
- rev 1은 총괄 반려 12건을 고친 판입니다. `c1-tools` 세션이 rev 0으로 구현을 시작했으므로 바뀐 곳을 §12 표에 모았습니다.
- 사용자 결정(2026-11-13 대화): 어떤 형태로 들어온 도면이든 한 가지 형태로 노드화해 저장합니다. 내부 저장은 지금의 그래프로 하고, 밖과 주고받는 공개 표준은 DEXPI로 합니다. 이 문서는 그 결정의 가져오기·내보내기 규칙입니다. '정리된 보기'(읽은 결과로 다시 그린 도면)는 `d-chat` 세션이 설계하고, 이 문서는 그 보기가 쓸 위치 정보만 정합니다.
- 용어. 배관 및 계장도(P&ID, piping and instrumentation diagram), 노즐(nozzle), 도면 연결 기호(off-page connector), 배관망 계통(piping network system), 배관망 구간(piping network segment), 계측 기능(process instrumentation function), 고장 시 동작(fail action), 호칭 지름(nominal diameter), 설계 압력·온도(design pressure·temperature), 배관 등급(piping class), 유체 코드(fluid code). 원자력 용어: 가압기(pressurizer, U.S. NRC Glossary), 내진 범주(seismic category, NRC 규제지침 RG 1.29 'Seismic Design Classification'), 안전 등급(safety class, ANSI/ANS-51.1의 용어 [일반지식]), 품질 등급(quality group, NRC 표준심사지침 SRP 3.2.2 [일반지식]). 처음 나올 때만 영문을 함께 적습니다(출처 §1 S13·S14).

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
| F7 | DEXPI XML 스키마(XSD)의 라이선스 | 사양 저장소의 사양 문서 폴더(`src/documentation/_static/`) 안에 있음. 저장소에 LICENSE 파일은 없고 GitLab 라이선스 항목도 비어 있음. 사양 전체의 CC BY 4.0이 적용된다고 보지만, 파일 단위의 명시는 **확인 못 함**. 그래서 앱에 묶지 않고 저장소의 참고 자료로만 둡니다(§5.6) | S1 |
| F8 | Proteus 스키마(XSD)의 라이선스 | GitHub `ProteusXML/proteusxml`에 LICENSE 파일이 없고 README에도 라이선스 문구가 없음 → **이용 조건 확인 못 함**. 앱에 묶지 않음 | S7 |
| F9 | 공개 예제 | (가) 2.0.1 사양 부록의 Reference P&ID `reference_pid.xml`(1,481,865바이트, 사양과 같은 CC BY 4.0). (나) GitLab `dexpi/TrainingTestCases`: DEXPI 1.2·1.3 예제 40여 개(C01 참조 도면, C08 도면 두 장 연결 등). 저장소 라이선스 **CC BY 4.0** | S8, S9 |
| F10 | 'DEXPI' 이름 사용 조건 | 상표·이름 사용 규정을 찾지 못함 → **확인 못 함**. 사이트 바닥글의 법적 고지(Legal Notice) 본문은 열어 보지 못함 | S2 |
| F11 | 인증 | DEXPI 인증(가져오기·내보내기, 시험 회차별)이 있음. 예: AutoCAD P&ID/Plant 3D가 2022년 6회차 가져오기·내보내기 인증. 신청 자격·비용은 **확인 못 함** | S10 |
| F12 | 클래스 이름 | 2.0.1 클래스 정의 원문(`src/model/Plant/*`)에서 확인. 클래스 정의 수는 배관 74, 설비 142, 계장 33(추상 클래스 포함, 정의 줄을 셈). 원자력 고유 설비(원자로용기, 가압기, 원전 증기발생기, 탈염기)는 없음 | S11 |
| F13 | 배관 연결과 흐름 | `PipingConnection.SourceItem`·`TargetItem`·`SourceNode`·`TargetNode`의 설명은 '연결이 시작하는/끝나는 곳'뿐이고 흐름 방향이라는 말은 없음. 흐름은 `PipingNetworkSegment.FlowDirection`(`Piping.py:959`)이 있고, 값은 `SingleFlowPipingNetworkSegment`·`DualFlowPipingNetworkSegment` 둘이며 설명은 '양방향 흐름을 허용하는지'뿐임. 어느 쪽으로 흐르는지를 적는 속성은 찾지 못함 | S11, S15 |
| F16 | 구간 안 부품의 순서 | 2.0.1 예제는 구간 안 부품마다 `Pipe`가 따로 있음(예 `PipingNetworkSegment3`: `Nozzle4→GlobeValve2`, `GlobeValve2→Nozzle5`). 같은 도면의 1.3 예제(C01)는 구간의 `Connection`이 `Nozzle-4→Nozzle-5` 하나뿐이고 `GlobeValve-2`는 구간 안에 품기만 함. 23개 구간 모두 1.3의 '문서 순서'가 2.0.1의 연결 순서와 같음(받은 예제로 대조) | 받은 예제 |
| F17 | 고장 시 동작 값 | `FailActionClassification`: `FailClose`, `FailOpen`, `FailRetainPosition` 셋 | S16 |
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
- S13 U.S. NRC Glossary 'Pressurizer': https://www.nrc.gov/reading-rm/basic-ref/glossary/pressurizer.html
- S14 NRC Regulatory Guide 1.29 'Seismic Design Classification'(Rev. 3 사본): https://www.nrc.gov/docs/ML0037/ML003739983.pdf (지금 판이 몇 판인지는 확인 못 함)
- S15 흐름 열거: https://dexpi.org/specification/2.0.1/html/models/Plant/Enumerations/PipingNetworkSegmentFlowClassification.html
- S16 고장 시 동작 열거: https://dexpi.org/specification/2.0.1/html/models/Plant/Enumerations/FailActionClassification.html

받은 파일은 `D:\HAZOP-trials\2026-11-13-dexpi\`에만 두었고(README에 출처와 `keep_until: 2026-11-27`), 저장소에는 넣지 않았습니다. 받은 파일 안의 스크립트는 실행하지 않았습니다.

## 2. 큰 줄기

```
CAD ─ DEXPI 파일 ─┐
                   ├─ ① 등록(형식 판별) ─ ② 변환(인식 없음) ─ extraction.json ─ ③ 그래프(지금 코드 그대로) ─ graph.json
drawio·PDF ───────┘                      ② 추출(인식)      ─┘
확정된 쪽(sheet_confirmation) ─ 내보내기 ─ DEXPI XML 2.0.1 + 뺀 목록 + 곁 파일
```

- **가져오기는 그래프가 아니라 추출 결과(`extraction.json`)를 만듭니다.** drawio·PDF 추출과 같은 계약([추출 결과의 공통 계약](extraction.md))으로 쓰면 ③ 그래프 변환(`hazop/graph/build.py`), 사람 수정(`corrections.py`), 미확인 목록, 그래프 판(`graph_version`), 구간·결과 쪽이 바뀌지 않습니다. 새 코드는 '읽는 쪽' 하나만 생깁니다.
- **내보내기는 사람이 확정한 쪽만 합니다.** 화면의 '쪽 확정'과 같은 함수(`sheet_confirmation`, §6.1)가 `confirmed`라고 답한 쪽만 DEXPI 객체로 바꾸고, 구조 검사를 통과해야만 파일을 씁니다.
- 대응 규칙(우리 `kind` ↔ DEXPI 클래스)은 한 곳(`hazop/extract/dexpi_map.py`, 새 파일)에 두고 가져오기·내보내기가 같이 씁니다. 지식그래프 레지스트리의 `dexpi_class`(`hazop/kg/schema/registry.json`, 23개)는 이 표와 맞춰 고칩니다(§3.6).

## 3. 대응표

'맞음'은 뜻과 구조가 같은 것, '근사'는 뜻은 같지만 모양이나 세분이 달라 정보가 줄거나 늘어나는 것, '없음'은 맞는 자리가 없는 것입니다. DEXPI 클래스 이름은 2.0.1 원문(F12)에서 확인한 것만 적었습니다. Proteus 열은 1.3 예제에서 본 이름입니다.

### 3.1 구조

| 우리 쪽 | DEXPI 2.0.1 | Proteus(1.3) | 정도 | 규칙 |
| --- | --- | --- | --- | --- |
| 도면 1장(`graph.json` 하나, `drawing_number`) | `Core/Diagram.Diagram` 하나 + `Plant/Diagram.PlantMetaData`(`DrawingNumber`, `DrawingName`) | `Drawing` + `MetaData` | 맞음 | 가져올 때 `DrawingNumber`·`DrawingName`은 등록의 '자동 후보'로만 둠(등록 규칙 4) |
| 노드 `drawing_object`(`kind`, `tag`) | `Object`(`type`) | `Equipment`·`PipingComponent` 등 요소 + `ComponentClass` | 맞음 | §3.2~3.4 |
| 배관 관계 `physical_connection` → ③에서 `pipe_segment` 노드 + `has_endpoint` 2개 | `Plant/Piping.Pipe`(또는 `DirectPipingConnection`) 하나. `SourceItem`·`TargetItem` | 구간의 `Connection FromID→ToID`와 그 구간이 품은 부품을 문서 순서로 이은 길(F16) | 2.0 맞음, Proteus 근사 | 이웃한 두 점 하나 = 관계 하나. 구간 안 부품을 빠뜨리지 않음(§5.7) |
| 배관 관계에 실린 라인 속성(`line_no`, `attributes`) | `PipingNetworkSegment`(구간)와 `PipingNetworkSystem`(계통)에 있음 | 같음 | 근사 | 우리는 관계마다 같은 값을 복사해 들고, DEXPI는 구간에 한 번 둠. 가져올 때 구간 값을 그 구간의 관계마다 복사하고 구간 ID를 `attributes["dexpi:segment"]`에 남김. 내보낼 때 같은 `line_no`·`fluid_code`·`pipe_class`·`nominal_diameter`로 이어진 관계를 한 구간으로 묶음 |
| 배관 구간(`pipe_segment`) 노드 | `PipingNetworkSegment` | 같음 | 근사 | 우리 구간 노드는 '연결 하나', DEXPI 구간은 '부품 여러 개를 거치는 줄기'. 이름은 같지만 단위가 다름. 이 차이 때문에 왕복에서 구간 경계가 바뀔 수 있음(§7.4) |
| 포트(`has_endpoint.port`, [포트 규칙](extraction.md)) | `Plant/ProcessEquipment.Nozzle`(및 `ProcessNozzle`·`InstrumentNozzle`·`AccessNozzle`) | `Nozzle` | 근사 | §3.3 |
| 노즐 노드(`kind=nozzle`, 선택) | `Nozzle` | `Nozzle` | 맞음 | 우리 쪽은 노즐을 노드로 두지 않는 것이 기본. §3.3 |
| 분기(`tee`) | `Plant/Piping.PipeTee` | 같음 | 맞음 | |
| 도면 연결점(`continuation`, `to_drawing`, `line_no`, `direction`, `to_object`) | `FlowInPipeOffPageConnector`·`FlowOutPipeOffPageConnector` + `ConnectorReference` → `PipeOffPageConnectorReferenceByNumber`(`ReferencedDrawingNumber`, `ReferencedConnectorNumber`) | `PipeOffPageConnector` | 맞음 | `direction` FROM→FlowIn, TO→FlowOut. `to_drawing`↔`ReferencedDrawingNumber`, `to_object`↔`ReferencedConnectorNumber`. `line_no`는 붙은 구간의 라인 번호에서 읽음 |
| 신호선(`signal_connection`) | `Plant/Instrumentation.SignalConveyingFunction`(하위 `SignalLineFunction`) | `InformationFlow` `SignalConveyingFunction` | 근사 | 우리는 끝 두 개만, DEXPI는 기능 사이 정보 흐름. 끝이 계측 기능·구동계가 아니면 내보내지 못함(§6.2) |
| 측정선(`measurement_connection`) | `MeasuringLineFunction` + `SensingLocation`(구간·설비가 측정 위치) | `InformationFlow` `MeasuringLineFunction` | 근사 | 측정 위치가 배관이면 우리는 구간 노드 끝, DEXPI는 구간 참조 |
| 흐름 방향(`flow_direction`, basis 포함) | `PipingNetworkSegment.FlowDirection`(한 방향·양방향 구분). 어느 쪽으로 흐르는지는 흐름 화살표(`Core/Diagram.PipeFlowArrow`)와 `FlowIn/Out` 연결 기호로만 알 수 있음(F13) | `FlowDirection` 일반 속성, `PipeFlowArrow` | 근사 | 한 방향·양방향 구분은 맞음. 향하는 쪽은 자리가 없음. §5.4 |
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
| `fail_position`(`FO`/`FC`/`FL`/`FAI`) | `ControlledActuator.FailAction`(`FailOpen`·`FailClose`·`FailRetainPosition`, F17) | 근사 | `FO`↔`FailOpen`, `FC`↔`FailClose`, `FAI`↔`FailRetainPosition`. `FL`(고장 시 잠김)은 `FailRetainPosition`으로 내보내고 곁 파일에 `FL`을 남김. 가져올 때 `FailRetainPosition`은 `FAI` |
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
| `safety_class`(안전 등급), `seismic_category`(내진 범주), `quality_group`(품질 등급), `system_code`, `train`, `channel` | — | 없음 | 원자력 고유. 곁 파일 |
| `normal_operating_pressure/temperature`, `normal_level`, `npsh_required`, `shutoff_head`, 설정치·경보치 | — 또는 확인 못 함 | 없음 | 곁 파일 |

### 3.6 맞는 자리가 없는 정보(모음)

DEXPI 쪽에 없는 것: 근거(어느 문서·쪽·좌표에서 읽었나), 확신도, 미확인 목록, 사람 수정 이력(`human_edit`), AI 후보 상태, 지식그래프의 문서·지식 층, 검토구간, HAZOP 결과·권고, 초기사건, 흐름이 향하는 쪽(한 방향·양방향 구분은 있음), 체크밸브 허용 방향, 원자력 고유 속성(안전 등급, 내진 범주, 품질 등급, 계통 코드, 계열), 정상 위치.

우리 쪽에 없는 것(가져올 때 미분류나 `attributes`로만 둠): DEXPI의 공정 모델(Process, 2.0에 합쳐진 PFD·BFD), 설비 내부 부품, 구동 전기계(`ActuatingElectricalSystem`), 플랜트 구조(`PlantStructure`의 구역·계열), 다국어 문자열, 그림 쪽 글자 양식.

레지스트리(`hazop/kg/schema/registry.json`)의 `dexpi_class`는 위 표와 다른 곳이 있습니다. `steam_generator`에 `dexpi_class`가 없는 것은 맞고, 앞으로도 `SteamGenerator`를 넣지 않습니다. 구현 단위(X1)가 레지스트리를 이 표에 맞추고, 대응표는 `dexpi_map.py` 한 곳에서 읽게 합니다.

## 4. 등록 흐름에서의 자리

1. **등록.** `hazop/register/fileinfo.py`의 `detect_format`이 XML 뿌리를 봅니다. 지금은 `mxfile`·`mxGraphModel`이면 `drawio`, 아니면 `xml`입니다. 여기에 뿌리가 `Model`이고 `Import`가 `…/models/2.0.x/Plant.xml`을 가리키거나, 뿌리가 `PlantModel`이고 `PlantInformation`이 있으면 `dexpi`를 더합니다. 두 갈래는 `dexpi_flavor`로 구분합니다(§4.1 표). 확장자는 `.xml`(Proteus 예제도 `.xml`)이라 확장자와 형식이 다른지는 '`.xml`이면 셋 중 하나'로 검사합니다.
2. **도면 수.** 2.0 파일 하나에 `Diagram`이 여럿일 수 있고 Proteus는 보통 `Drawing` 하나입니다. 등록은 PDF처럼 도면마다 쪽 ID(`page-<번호>`)를 줍니다. 도면이 없고 설비 모델만 있는 파일은 쪽 하나로 등록하고 '그림 없음'을 미확인에 적습니다.
3. **표제란.** `PlantMetaData`(2.0) 또는 `MetaData`의 `DrawingNumber`·`DrawingName`·개정 관련 값을 등록의 '자동 후보'로 기록합니다. 사람이 확정하기 전에는 확정값으로 쓰지 않습니다([등록 규칙 4](registration.md)). 파일에 적혀 있다고 바로 확정하지 않는 것은 drawio·PDF와 같습니다.
4. **'추출 시작'.** `hazop/app/data.py:110 extract_and_graph`가 형식으로 갈래를 탑니다(지금 `pdf`와 그 밖). 여기에 `dexpi` 갈래를 더해 새 스크립트 `scripts/extract_dexpi.py`의 `run_one`을 부르고, 그 뒤 그래프 만들기는 지금처럼 `build_graph.build_one`을 씁니다. 원본 옆 SVG 찾기(`registry._unknowns`의 `NO_SVG_FIELD`)는 DEXPI에는 적용하지 않습니다(그림이 파일 안에 있음).
5. **읽은 방법 표시.** 새 필드를 만들지 않고, 추출 결과에 이미 있는 `source.format`(지금 `drawio`는 `drawio.py:870`, PDF는 `pdf_vector.py:61`의 `SOURCE_FORMAT`)에 `dexpi`를 씁니다. 판은 DEXPI 추출에만 있는 `source.dexpi_version`에 둡니다. `graph_version`은 추출 결과 전체의 해시라(`hazop/graph/build.py:75-78`) 기존 drawio·PDF 추출 결과에 필드를 더하면 다시 추출할 때 모든 그래프 판이 바뀝니다. 이 방식은 기존 형식의 추출 결과를 한 글자도 바꾸지 않습니다. 화면은 '변환(DEXPI 2.0.1)'·'변환(DEXPI 1.3.1)'처럼 판과 함께 보입니다. 노드의 `origin`은 지금처럼 `pid_extract`(도면에서 옴)로 두고 새 값을 만들지 않습니다(§9 V-4). '인식했나 변환했나'는 노드가 아니라 도면의 성질이기 때문입니다.
6. **기본 보기.** INTENT §3.8대로 DEXPI로 들어온 도면은 정리된 보기가 기본입니다. 그 보기가 쓸 위치는 §5.3이 만듭니다. DEXPI에는 원본 그림 파일이 따로 없으므로 '원본 보기'와 '원본 조각'이 무엇을 보이는지는 `d-chat`이 정합니다. 이 규격은 가져온 파일에 그림 정보(`Core/Diagram.*`, Proteus의 그림 요소)가 있으면 그 좌표를 §5.3대로 넘기는 것까지만 정합니다.

### 4.1 형식 이름 표

형식 이름은 아래 표 하나만 씁니다. 코드와 화면은 이 표의 값을 그대로 씁니다.

| 자리 | 필드 | DEXPI일 때 | drawio·PDF일 때(지금 값, 바꾸지 않음) |
| --- | --- | --- | --- |
| 등록 기록 | `format` | `dexpi` | `drawio`, `pdf` |
| 등록 기록 | `dexpi_flavor` | `dexpi_xml`(2.0 이후, 뿌리 `Model`), `proteus`(1.x, 뿌리 `PlantModel`) | 없음 |
| 추출 결과 | `source.format` | `dexpi` | `drawio`, `pdf_vector` |
| 추출 결과 | `source.dexpi_version` | 파일에서 읽은 판 문자열(예 `2.0.1`, `1.3.1`) | 없음 |
| 화면 자료 | `source_format`(화면 규격 §10.1) | `dexpi`(= `source.format`) | `drawio`, `pdf_vector` |

rev 0의 `read_method`라는 이름은 쓰지 않습니다. 등록의 `pdf`와 추출의 `pdf_vector`가 다른 것은 지금 코드 그대로입니다.

### 4.2 같은 도면이 두 번 들어올 때

사람이 고친 것은 잃지 않습니다. 사람 수정은 `source_object_id`로 대상을 가리키고(`hazop/extract/corrections.py`), 수정 기록 파일 이름은 추출 출력 폴더 이름(`<자료 ID>-r<등록 버전>-p<쪽>`, `scripts/extract_drawio.py:45`와 같은 꼴)을 따릅니다. 그래서 등록 버전이나 원본 형식이 바뀌면 기록이 새 추출에 붙지 않습니다. 아래 규칙으로 막습니다.

**(가) DEXPI 개정판.** 같은 자료의 새 등록 버전이거나, 같은 도면 번호의 새 DEXPI 파일입니다.

1. 새 판을 추출할 때 앞 판의 수정 기록을 새 이름으로 **복사**합니다. 앞 판의 기록 파일은 그대로 둡니다.
2. 복사한 기록의 op를 `source_object_id`로 다시 적용합니다. 두 판에서 DEXPI `id`가 다르고 `PersistentIdentifier`가 같으면 같은 객체로 보고 op의 대상을 새 `id`로 바꿔 적습니다(바꾼 짝은 기록에 남김).
3. 대상을 못 찾은 op는 지우지 않습니다. '적용 못 함'으로 남기고 사람에게 목록으로 보입니다. 태그가 같은 새 객체가 있으면 짝 후보로 보이되 자동으로 적용하지 않습니다.
4. CAD가 판을 바꿀 때 `id`를 유지하는지는 확인하지 못했습니다. 유지하지 않으면 3번 목록이 커집니다. X1 시험에 '`id`가 모두 바뀐 개정판'을 넣습니다.

**(나) 같은 도면을 PDF와 DEXPI로 둘 다 등록.** 프로젝트 그래프에 같은 도면 번호의 그래프가 둘이면 도면 연결점 짝맞추기와 구간이 겹칩니다.

1. 도면 번호마다 그래프에 쓰는 원본을 하나만 둡니다('쓰는 원본'). 같은 번호의 DEXPI가 들어오면 쓰는 원본을 DEXPI로 바꿀지 사람에게 묻습니다(권장: 바꿈. 변환이 인식보다 정확하므로).
2. 바꾸기 전에, PDF 쪽 사람 수정 목록을 태그로 DEXPI 객체와 맞춘 대조표를 보입니다. 두 쪽의 `source_object_id`가 서로 다른 체계라 자동으로 옮기지 않습니다.
3. PDF 쪽 추출 결과와 수정 기록은 지우지 않습니다. 쓰는 원본을 PDF로 되돌리면 그대로 다시 쓰입니다.
4. 쓰는 원본이 바뀌면 그래프가 바뀌므로 검토구간·결과는 [검토구간 규격](study-node-segmentation.md)의 그래프 판 변경 규칙(재확인)을 그대로 탑니다.
5. 지금 프로젝트 그래프(`hazop/graph/project.py`)가 같은 도면 번호의 그래프 둘을 어떻게 다루는지는 확인하지 않았습니다. X1이 먼저 확인하고, 둘 다 넣고 있으면 '쓰는 원본'만 넣도록 고칩니다.

PDF끼리의 개정판에도 같은 문제가 있습니다. 그 규칙은 이 문서의 범위가 아니어서 §10에 넘깁니다.

## 5. 가져오기 규칙

### 5.1 XML 읽기의 보안

DEXPI 파일은 밖에서 온 파일입니다. 읽기 전에 아래를 모두 지킵니다.

- **DTD·개체 선언 금지.** `xml.etree.ElementTree.XMLParser`에는 expat 파서에 처리기를 걸 자리가 없습니다(시험 venv 3.12.10에서 `hasattr(ET.XMLParser(), 'parser')`가 `False`). 그래서 `pyexpat.ParserCreate()`를 직접 만들고 처리기를 겁니다. `StartDoctypeDeclHandler`·`EntityDeclHandler`·`ExternalEntityRefHandler`가 불리면 예외를 내고, `SetParamEntityParsing(XML_PARAM_ENTITY_PARSING_NEVER)`를 둡니다. 요소는 `StartElementHandler`·`EndElementHandler`·`CharacterDataHandler`에서 `ET.TreeBuilder`로 옮겨 지금 코드가 쓰는 `Element` 나무를 만듭니다. 이 방식으로 2026-11-14에 확인했습니다: 2.0.1 Reference P&ID(요소 19,804개)와 1.3 C01(5,216개)은 읽히고, `<!DOCTYPE`와 `<!ENTITY>`가 든 시험 파일은 DOCTYPE에서 멈춥니다. 거절 사유 코드는 `dexpi_doctype_forbidden`입니다. 시험 venv의 expat은 2.7.1이지만 판에 기대지 않고 선언 자체를 막습니다.
- **네트워크 금지.** `Import source="https://data.dexpi.org/models/2.0.1/Plant.xml"`은 이름표로만 읽고 내려받지 않습니다. 판 번호(`2.0.1`)만 뽑아 앱에 묶은 클래스 목록과 맞춥니다.
- **크기 한도.** 파일 100MB, 요소 300만 개, 깊이 256단계를 넘으면 거절합니다. 파일은 1MB씩 읽어 파서에 넣으며 읽은 양으로 크기를 셉니다. 참고로 2.0.1 Reference P&ID는 1.5MB, 요소 19,804개입니다(받은 예제로 셈). 한도는 상수 하나로 두고 넘으면 '파일이 너무 큼, 한도 ○○'으로 알립니다.
- **XML 밖 내용.** 파일 안의 스크립트·링크·이미지 경로는 읽거나 열지 않습니다. 그림 쪽 글자는 화면에 낼 때 지금 SVG 처리(`hazop/viewer/sanitize.py`)와 같은 규칙으로 걸러 냅니다.
- 이 규칙은 읽기 전용 함수 하나(`hazop/extract/adapters/dexpi_read.py`의 `parse_safely`)에 모으고, 등록의 형식 판별도 이 함수를 씁니다.

### 5.2 ID와 태그

- 추출 노드의 `source_object_id`는 DEXPI `id`(2.0) 또는 `ID`(Proteus)를 그대로 씁니다. 2.0에서는 `id`가 생략될 수 있으므로, 없으면 '부모 `id` + 속성 이름 + 순번'으로 경로 ID를 만듭니다(예 `PlantModel1__PipingNetworkSystems_3`). 경로 ID는 DEXPI XML의 ID 글자 규칙(`[A-Za-z_][A-Za-z_0-9]*`, XSD의 `id-pattern`)을 지키도록 `/` 대신 `__`를 씁니다. 같은 파일이면 늘 같은 값이 나와야 합니다. `PersistentIdentifier`가 있으면 `attributes["dexpi:PersistentIdentifier"]`에 두고 개정판 대응에 씁니다(§4.2).
- `local_id`는 `dx-` + `source_object_id`를 이름 문자 규칙에 맞게 바꾼 값입니다. 그래프 엔터티 ID(`entity-node-NNN`)는 지금처럼 ③이 매깁니다.
- 같은 파일을 다시 가져오면 같은 `extraction.json`이 나와야 합니다(결정적 순서: 파일 안 순서). 그래야 `graph_version`이 같고 구간·결과가 '재확인'으로 가지 않습니다.
- 태그는 §3.5 규칙으로 정합니다. 태그가 없는 객체도 버리지 않습니다(추출 공통 계약). 지금 규칙대로 `tag` 미확인을 남깁니다.

### 5.3 좌표

- 그림 쪽(2.0의 `Core/Diagram.*`, Proteus의 `Position`·`Extent`)을 읽어 노드 `bbox`·`position`과 관계 `waypoints`를 채웁니다. 이 값이 정리된 보기와 원본 보기의 위치가 됩니다.
- 좌표계는 `coordinate_system = {"coordinate_space": "dexpi_diagram", "unit": "mm", "origin": "top_left", "source_origin": …}`로 적습니다.
- **Y축 방향(2026-11-14 구현에서 확인).** 사양 문장은 찾지 못했고 예제 파일로 정했습니다. (가) 2.0.1 Reference P&ID에서 표제란 글자(도면 번호)는 y 291, 칸 글자 A는 y 21, H는 y 274에 있어(도면 높이 297) 위가 0이고 아래로 커집니다. (나) 같은 도면의 Proteus 판(TrainingTestCases C01)에서 같은 노드의 y는 2.0 판과 합이 297(예 154 ↔ 143)이라 **Proteus는 y가 위로 커집니다**. (다) 2.0.1의 흐름 화살표(회전 θ)는 방향이 (cos θ, sin θ)일 때 연결의 Source→Target 방향과 맞는 연결에서 흐름 방향이 일관됩니다. 그래서 가져올 때 2.0은 그대로, Proteus는 `y' = 도면 높이 − y`로 뒤집고(`source_origin`에 `top_left`·`bottom_left`를 적음), 화면은 위가 0인 좌표를 그대로 씁니다. 원래 값은 되돌릴 수 있으므로 따로 두지 않습니다. 확인에 쓴 근거는 `docs/units/2026-11-13-drawing-knowledge/evidence/dexpi-commands.md`에 있습니다.
- 위치 정보가 없는 객체(그림 없이 모델만 있는 파일, 그림 쪽에서 `Represents`가 가리키지 않는 객체)는 버리지 않고 `bbox: null`로 둡니다. 그리고 미확인 `dexpi_no_position`(target=그 노드나 관계, field=`bbox`, reason '그림 위치 없음(DEXPI 파일에 그림 정보가 없음)')을 남깁니다. 이 미확인은 사람이 위치를 정하거나(사람 수정의 이동) '위치 없이 둠'으로 확정해야 풀립니다. 그래서 위치 없는 구성요소가 남은 쪽은 '쪽 확정'을 할 수 없고 내보내지도 않습니다(§6.1). 화면이 이 미확인을 어떻게 세고 그리는지는 `d-chat`이 화면 규격에서 고칩니다(`sheet_confirmation`의 `unconfirmed` 사유에 `no_position`을 더하는 것을 권장).
- 노드 크기는 `ShapeUsage`가 쓰는 `Shape`의 테두리 × `ScaleX/Y`, 회전은 `Rotation`(도)으로 셉니다. 계산이 안 되면 위치만 두고 크기는 '확인 못 함'.

### 5.4 흐름 방향

DEXPI 연결의 Source→Target은 '연결이 시작하고 끝나는 곳'이지 흐름 방향이 아닙니다(F13). 구간의 `FlowDirection`은 한 방향인지 양방향인지만 말합니다. 그래서 이 둘만으로 `flow_direction`을 정하지 않습니다. 근거가 될 수 있는 것과 다루는 법:

| 근거 | 다루는 법 |
| --- | --- |
| 연결 Source→Target | `flow_direction`을 만들지 않음. 지금 규칙대로 `unknown_flow_direction`이 남음 |
| 구간 `FlowDirection` = `SingleFlowPipingNetworkSegment` | 향하는 쪽은 정하지 않음. `attributes["flow_class"] = "single"`만 둠 |
| 구간 `FlowDirection` = `DualFlowPipingNetworkSegment` | `attributes["flow_class"] = "dual"`. `unknown_flow_direction`은 남기되 reason을 '양방향 흐름 구간(DEXPI DualFlow)'으로 적음. 양방향을 한쪽으로 확정하지 않음 |
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
2. **틀 검사.** XSD를 실행 중에 읽지 않습니다. DEXPI XML XSD 파일 자체가 `<!DOCTYPE>`와 `<!ENTITY>`(이름 패턴 정의)를 담고 있어 §5.1의 안전 읽기로는 읽을 수 없고, XSD 검사에는 외부 패키지가 필요하기 때문입니다. 대신 XSD의 규칙을 Python 표로 옮긴 구조 검사(`dexpi_read.check_structure`)를 둡니다: 허용 요소와 부모(`Model` > `Import`·`Object`, `Object` > `Components`·`Data`·`References`, `Data` > 값 요소 등), 필수 속성(`Object@type`, `Components@property`, `References@property`·`objects` 등), 글자 규칙(XSD 개체 `id-pattern` `[A-Za-z_][A-Za-z_0-9]*`, `id-reference-pattern` `#` + ID, `name-reference-pattern`). 이 표가 XSD와 같은지는 시험 하나가 확인합니다(§8.1 X1). XSD 원본은 저장소의 참고 자료 `resources/references/dexpi-schema/dexpi-xml-schema-2-0-1.xsd`에만 두고, 그 시험은 저장소 안 파일만 받는 별도 읽기(내부 개체만 허용, 외부 개체·네트워크 금지)로 엽니다. Proteus는 스키마 이용 조건을 모르므로(F8) 같은 방식의 구조 검사만 합니다. 틀 검사 실패는 '형식 오류'로 등록을 막습니다.
3. **클래스 검사.** `type`(2.0)과 `ComponentClass`(Proteus)가 그 판의 클래스 목록에 있는지 봅니다. 클래스 목록은 2.0.1 원문(S11)에서 뽑아 `resources/library/dexpi-schema/classes-2-0-1.json`으로 묶습니다. 없는 클래스는 막지 않고 §5.5대로 미분류로 가져옵니다.
4. **참조 검사.** `#ID` 참조(`References objects`, `ObjectReference`, `SourceItem`·`TargetItem` 등)와 Proteus `Connection FromID/ToID`가 파일 안에 있는지, `id`가 겹치지 않는지 봅니다. 끝을 못 찾는 연결은 정상 관계가 아니라 `unresolved_connectors`로 보내고 지금 규칙대로 `unconnected_endpoint`를 남깁니다. 겹치는 `id`는 차단 오류(`validation.blockers`)로 둡니다(어느 객체를 가리키는지 정할 수 없으므로).
5. **우리 쪽 구조 검사.** 만든 `extraction.json`을 지금 추출 결과 검증에 그대로 넣습니다.

외부 패키지는 더하지 않습니다(§9 V-5). 지금 시험 venv에는 `lxml`도 `xmlschema`도 없습니다(2026-11-13 확인).

### 5.7 배관 길 만들기

구간 안 부품이 배관 길에서 빠지지 않게, 형식마다 아래처럼 '이웃한 두 점'을 만들고 그 하나하나를 `physical_connection` 관계 하나로 씁니다.

- **2.0(DEXPI XML).** 구간(`PipingNetworkSegment`)의 `Connections`에 있는 `Pipe`·`DirectPipingConnection` 하나가 관계 하나입니다. 2.0.1 예제는 구간 안 부품마다 연결이 따로 있습니다(F16: `PipingNetworkSegment3`은 `Nozzle4→GlobeValve2`와 `GlobeValve2→Nozzle5` 둘). 예제의 23개 구간 모두 `Items`의 부품이 연결 어딘가의 끝에 나옵니다. 만약 `Items`에 있는데 어느 연결의 끝에도 없는 부품이 있으면, 아래 Proteus 규칙처럼 `Items` 순서로 길에 끼우고 미확인 `dexpi_item_order_assumed`(target=그 부품)를 남깁니다.
- **1.x(Proteus).** 구간의 `Connection`은 구간 전체의 처음(`FromID`)과 끝(`ToID`)만 가리키는 경우가 많습니다. 구간 안 부품(구간의 자식 `PipingComponent`·`PipeOffPageConnector` 등)은 문서 순서가 곧 길 순서입니다. 길은 `FromID` → 구간 안 부품(문서 순서, 단 `FromID`·`ToID`와 같은 부품은 한 번만) → `ToID`이고, 이웃한 두 점마다 관계 하나를 만듭니다. 예: C01 `PipingNetworkSegment-3`은 `Nozzle-4 → GlobeValve-2 → Nozzle-5`로 관계 둘, `PipingNetworkSegment-4`는 `Nozzle-6 → ButterflyValve-1 → SwingCheckValve-1`로 관계 둘. 이 순서가 같은 도면의 2.0.1 연결과 23개 구간 모두 같음을 받은 예제로 대조했습니다(F16). 한 구간에 `Connection`이 둘 이상이면 각 `Connection`을 따로 길로 보고, 어느 `Connection`에도 들지 못한 부품은 `dexpi_item_order_assumed`를 남기고 문서 순서로 가장 가까운 길에 끼웁니다.
- **끝이 없는 연결.** `FromID`·`ToID`나 `SourceItem`·`TargetItem`이 비어 있으면(예제의 구간 20~23, 장비 노즐에서 도면 밖으로 나가는 배관) 정상 관계가 아니라 `unresolved_connectors`로 보내고 열린 끝(`open`)으로 둡니다.
- 관계의 라인 속성은 그 구간·계통의 값을 복사하고 구간 ID를 `attributes["dexpi:segment"]`에, 길 안의 순번을 `attributes["dexpi:segment_order"]`에 둡니다(내보낼 때 구간을 되묶는 데 씀, §7.4).
- Proteus `Connection`의 `FromNode`·`ToNode`(부품의 몇 번째 접속점인지)는 끝점 `attributes`에 남깁니다. 체크밸브 입구·출구 판정에는 쓰지 않습니다(번호의 뜻을 사양으로 확인하지 못함).


## 6. 내보내기 규칙

### 6.1 범위와 형식

- 형식은 DEXPI XML 2.0.1 하나입니다(§9 V-1). Proteus 내보내기는 받을 쪽 CAD가 2.0을 못 읽는다는 것이 확인되면 별도 단위로 합니다.
- 단위는 **도면 하나 = 파일 하나**입니다. 프로젝트 전체는 도면별 파일 여러 개와 묶음 목록(`manifest.json`)으로 냅니다. 도면 사이는 연결 기호의 `PipeOffPageConnectorReferenceByNumber`(상대 도면 번호·연결 번호)로 잇습니다. 프로젝트 그래프가 맞춘 연결점 짝(`hazop/graph/project.py`의 `continuation_key`)을 그대로 씁니다.
- 내보낼 수 있는 도면은 도면 번호가 사람 확정된 도면뿐입니다. 도면 번호 없이는 도면 간 참조를 쓸 수 없기 때문입니다.

**내보내는 조건은 '쪽 확정'과 같은 함수 하나입니다(권장, §9 V-2).** 사용자 결정은 '사람이 확정한 결과를 내보낸다'(INTENT §3.2)이고, 화면 규격은 정리된 보기·'미확인 n곳'·DEXPI 내보내기가 같은 답을 쓰도록 정했습니다([화면 규격 §10.6](../design/app-shell-web.md)).

- 함수는 화면 규격이 제안한 `sheet_confirmation(extraction, review_log)`이고, 자리도 그 제안대로 엔진 쪽 새 파일 `hazop/extract/confirmation.py`입니다. 이 규격은 자리를 따로 정하지 않습니다. 함수를 만드는 일은 화면 규격의 단위 V3가 하고, 내보내기(X2)는 부르기만 합니다.
- 그 함수가 `state == "confirmed"`라고 답한 쪽만 내보냅니다. `open`(미확인 있음)과 `ready`(미확인 0, 사람 확정 전)인 쪽은 내보내지 않습니다. 확정 전 쪽을 '확정 전' 표시와 함께 내보내는 길은 두지 않습니다. 받는 CAD가 그 표시를 모른 채 확정 도면으로 읽을 수 있기 때문입니다.
- 프로젝트 내보내기에서는 확정된 쪽만 파일로 쓰고, 나머지 쪽은 `manifest.json`의 `not_exported`에 쪽과 상태(`open`·`ready`)와 남은 미확인 수를 적습니다. 확정된 쪽이 하나도 없으면 아무 파일도 쓰지 않고 이유를 보입니다.
- 쪽 확정 뒤 추출 결과가 바뀌면 확정이 풀립니다(화면 규격 §10.7의 지문). 내보내기는 쓰기 직전에 함수를 다시 불러 확인합니다.
- 내보내는 그래프는 확정을 판정한 세 파일(추출 결과·사람 수정 기록·AI 후보 기록)로 내보낼 때 만듭니다. 디스크의 `graph.json`은 AI 후보 수락처럼 그래프를 다시 만들지 않는 저장 뒤에 낡을 수 있어 내용으로 쓰지 않습니다(rev 2, 구현 `dexpi_export.export_names`).

### 6.2 무엇을 내보내는가

| 대상 | 내보냄 | 뺌 |
| --- | --- | --- |
| 추출 노드·관계(`origin: pid_extract`) | 확정된 쪽의 것. 속성 미확인만 남은 것은 그 속성을 빼고 냄 | 아래 '뺌' 조건에 걸린 것 |
| 사람 수정(`origin: human_edit`) | 모두(사람이 고친 것이 최종 값) | — |
| AI 후보 | 사람이 수락한 것(`status: accepted`, 노드 `origin: ai` + `accepted_by`) | 기각(`rejected`)인 것. 제안 상태(`proposed`)는 쪽 확정을 막으므로 확정된 쪽에 없음 |
| 끝이 미확정인 연결(`unresolved_connectors`) | — | 모두. 쪽 확정을 막으므로 확정된 쪽에는 사람이 '이대로 확인'한 것만 남고, 그것은 빼고 냄 |
| 분류 못 한 노드(`kind` 없음) | DEXPI에서 가져온 미분류 노드를 사람이 '그대로 둠'으로 확정한 것은 원문 조각으로 되살림(§7.2) | 그 밖에는 모두. 확정된 쪽에는 사람이 '이대로 확인'한 것만 남고, 그것과 그 노드에 붙은 연결은 빼고 냄 |
| 대응이 '없음'인 `kind`(`damper`, `drain`, `test_connection`, `pipe_cap`) | — | 모두. 그 노드에 붙은 연결은 양쪽 이웃을 직접 잇지 않고(없는 연결을 지어내지 않음) 끊긴 채 둠 |
| 지식그래프 문서·지식 층, 기대 후보, 검토구간, HAZOP 결과, 초기사건 | — | 모두(DEXPI에 자리가 없음, §6.3) |

**확정된 쪽 안에 남는 것의 처리.** 쪽 확정은 추출 미확인 목록 전체를 막습니다(화면 규격 §10.4). 그래서 확정된 쪽에 남는 불확실한 것은 사람이 값을 고치지 않고 '이대로 확인'한 것뿐입니다(미분류 기호, 끝이 미확정인 연결, 속성 미확인 등).

- '이대로 확인'한 구성요소 단위의 것(미분류 기호, 끝이 미확정인 연결)은 멈추지 않고 빼고 내보냅니다([INTENT §3.2](../../INTENT.md) '미확인이 남은 구성요소는 빼거나 표시한다', 총괄 판정 2026-11-14). 뺀 구성요소 때문에 내지 못한 연결 수를 `excluded.json`의 `cut_by_excluded`(`pipes`·`signal_lines`)와 내보내기 결과 요약(`cut_pipes`)에 적습니다. rev 1의 '남아 있으면 멈춤'은 이것으로 바꿉니다.
- 구성요소는 확실하고 속성만 미확인인 것(흐름 방향 미확인, 고장 시 위치 미확인, 노즐 이름 없음 등)은 구성요소를 내보내고 그 속성은 쓰지 않습니다. 추측값을 넣지 않습니다.
- 대응 클래스가 없는 `kind`는 위 표대로 빼고 목록에 적습니다.
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

1. §5.6의 틀 검사(XSD 규칙을 옮긴 구조 검사) 통과.
2. 모든 `type`이 2.0.1 클래스 목록(`classes-2-0-1.json`)에 있음. 모든 `id`가 §6.6 글자 규칙에 맞음.
3. 모든 `#ID` 참조가 파일 안에 있음, `id`가 겹치지 않음.
4. 되읽기: 쓴 내용을 §5 가져오기로 다시 읽어, 내보낸 구성요소 수·연결 수·태그 목록이 같음.

받은 CAD에서 실제로 열리는지는 이 앱이 검사할 수 없습니다. 공개 검증 도구(DEXPI 검증기 `dexpi/dexpi-verificator`)는 저장소에 README만 있어 쓸 수 있는지 **확인 못 함**입니다.

### 6.6 내보낼 때의 ID

DEXPI XML의 `id`는 `[A-Za-z_][A-Za-z_0-9]*`만 됩니다(XSD `id-pattern`). 우리 엔터티 ID(`entity-node-003`)와 Proteus ID(`Nozzle-4`)에는 `-`가 들어 있어 그대로 쓸 수 없습니다.

1. DEXPI에서 가져온 객체이고 `source_object_id`가 이미 글자 규칙에 맞으면(2.0 파일의 `id`, §5.2의 경로 ID) 그대로 씁니다.
2. 그 밖에는 `HZ_` + 원래 ID에서 `[A-Za-z0-9_]` 밖의 글자를 `_`로 바꾼 값을 씁니다. 예: `entity-node-003` → `HZ_entity_node_003`, Proteus `Nozzle-4` → `HZ_Nozzle_4`.
3. 바꾼 값이 파일 안에서 겹치면 뒤에 `_2`, `_3`…을 붙입니다. 순서는 엔터티 ID 순이라 같은 그래프면 같은 결과가 나옵니다.
4. 원래 ID ↔ 내보낸 `id` 대응은 곁 파일(§6.3)에 모두 적습니다. 다시 가져올 때 이 대응으로 원래 노드에 근거와 수정 이력을 되붙입니다(§7.3).
5. 노즐처럼 내보낼 때 새로 만드는 객체는 `HZ_` + 부모 `id` + `_N` + 번호입니다.

## 7. 왕복에서 지켜야 할 것

### 7.1 DEXPI → 우리 → DEXPI (사람 수정 없음)

사람이 고친 것은 없고, 쪽 확정만 거친 경우입니다. 미분류로 가져온 객체는 쪽 확정을 막으므로(미확인 기호), 사람이 그 미확인을 '이 종류 그대로 둠'으로 확정해야 쪽 확정이 됩니다. 이 확정은 분류나 연결을 바꾸지 않으므로 §7.2의 '고치지 않았을 때'에 듭니다.

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

가져올 때 남긴 원문 조각(`evidence.dexpi.xml`)은 사람이 그 노드를 고치지 않았을 때만 그대로 되씁니다(미확인을 '그대로 둠'으로 확정한 것은 고친 것으로 보지 않음). 되쓸 때 원문 조각 안의 `id`와 참조도 §6.6 규칙을 지키는지 확인하고, 안 맞으면 되살리지 않고 뺀 목록에 적습니다. 사람이 분류나 연결을 고쳤으면 원문을 버리고 고친 값으로 냅니다. 원문 조각이 4KB에서 잘렸으면 되살리지 않고 뺀 목록에 적습니다.

### 7.3 우리 → DEXPI → 우리

drawio·PDF에서 읽은 도면을 내보내고 다시 가져왔을 때:

- 같아야 함: 내보낸 노드 수와 `kind`(근사 대응은 곁 파일로 되돌림), 연결의 양 끝, 태그, 라인 속성, 도면 간 연결.
- 달라도 됨: 엔터티 ID 번호(③이 다시 매김), `origin`(원래 `human_edit`였어도 다시 가져오면 `pid_extract`, 대신 곁 파일의 수정 이력이 남음), 흐름이 향하는 쪽(DEXPI에는 한 방향·양방향 구분만 있음. 내보낼 때 확인된 흐름이 있는 구간은 `FlowDirection=SingleFlowPipingNetworkSegment`로 쓰고 연결을 흐름 순서로 적지만, 다시 가져오면 §5.4대로 향하는 쪽이 미확인으로 돌아옴. 이 차이는 뺀 목록에 적고, 곁 파일이 있으면 되붙임).
- 곁 파일이 있으면 가져오기가 `entity_id` 대응표로 원래 노드에 근거와 수정 이력을 되붙입니다. 곁 파일의 그래프 판이 다르면 되붙이지 않고 알립니다.

### 7.4 구간 경계

우리 배관 구간 노드는 연결 하나이고 DEXPI 구간은 줄기 하나라서(§3.1), 내보낼 때 묶은 구간이 원래 DEXPI 구간과 다를 수 있습니다. 원래 구간 ID(`dexpi:segment`)가 남아 있으면 그 묶음을 먼저 따릅니다.

## 8. 구현 단위

### 8.1 단위표

| 단위 | 대상 파일 | 완료 기준 | 시험 | 모델(배정표) |
| --- | --- | --- | --- | --- |
| **X1 가져오기** | 새: `hazop/extract/adapters/dexpi_read.py`(안전한 읽기, 2.0·Proteus 두 읽기를 같은 중간 형태로), `hazop/extract/adapters/dexpi_import.py`(중간 형태 → `extraction.json`), `hazop/extract/dexpi_map.py`(대응표, X2와 공유), `scripts/extract_dexpi.py`, `resources/library/dexpi-schema/classes-2-0-1.json`(앱에 묶음), `resources/references/dexpi-schema/dexpi-xml-schema-2-0-1.xsd`(참고 자료, 시험만 읽음), `licenses/dexpi/`(CC BY 4.0 출처·변경 표시). 고침: `hazop/register/fileinfo.py`(형식 판별), `hazop/register/registry.py`(쪽 목록, 표제란 후보, SVG 찾기 제외), `hazop/app/data.py`(갈래), `hazop/extract/corrections.py`(개정판 수정 기록 복사, §4.2), `hazop/graph/project.py`(같은 도면 번호는 '쓰는 원본'만, §4.2 확인 뒤), `hazop/kg/schema/registry.json`(`dexpi_class`). `hazop/graph/build.py`·`runinfo.py`는 고치지 않음(§4 5번) | §5 규칙대로 두 형식을 읽어 지금 그래프 변환을 통과. 같은 파일을 두 번 가져오면 같은 `graph_version`. 기존 drawio·PDF 추출 결과는 한 바이트도 바뀌지 않음. Y축 방향을 정해 §5.3을 고침 | `tests/test_dexpi_import.py`: 손으로 만든 작은 DEXPI 파일(펌프―밸브―탱크, 노즐 둘, 도면 연결 기호 하나, 모르는 클래스 하나, 흐름 화살표 하나, 위치 없는 부품 하나, 구간 안에 밸브를 품고 `Connection`은 하나뿐인 Proteus 구간 하나)을 2.0과 Proteus 두 형식으로 `tests/fixtures/dexpi/`에 둠. 구간 안 밸브가 길에 들어감(§5.7). DOCTYPE·개체 선언·크기 초과·겹친 `id`·끊긴 참조 거절. 틀 검사 표가 참고 자료 XSD의 요소·속성과 같음. 개정판(`id`가 모두 바뀐 판, `PersistentIdentifier`만 같은 판)에서 사람 수정이 남거나 '적용 못 함'으로 보임. 공개 예제(Reference P&ID 2.0.1, TrainingTestCases C01·C03·C08)는 `HAZOP_DEXPI_SAMPLES`가 있을 때만 돌고 없으면 건너뜀 | Opus 5.5 medium(ID·출처 경로). Y축 확인 같은 곁일은 Sonnet 하위 에이전트 |
| **X2 내보내기** | 새: `hazop/export/dexpi_export.py`, `scripts/export_dexpi.py`. 씀: `dexpi_map.py`, `resources/library/dexpi-schema/`, `hazop/extract/confirmation.py`(화면 규격 V3가 만듦) | §6 규칙대로 확정된 쪽만 내보내고 §6.5 검사 통과. 뺀 목록·곁 파일·묶음 목록 | `tests/test_dexpi_export.py`: 확정 전 쪽(`open`·`ready`)은 내보내지 않고 `not_exported`에 적힘. 가상 도면 SNP 6세트(drawio)를 쪽 확정한 뒤 내보내 틀 검사 통과, `id`가 모두 글자 규칙에 맞음, 뺀 목록이 남은 속성 미확인과 맞음(예: `missing_port` 16건은 노즐 이름 `N1`… 근사로 적힘). §7.3 왕복. X1이 끝난 뒤 §7.1 왕복(손으로 만든 파일과 공개 예제) | Opus 5.5 medium(무엇을 뺄지의 판정 경로) |
| **X3 화면 자리** | 화면 쪽 파일(`hazop/shell/`)은 [화면 규격](../design/app-shell-web.md)의 단위·주인 표를 따릅니다. 이 규격은 화면 파일의 주인을 정하지 않습니다 | §8.2 자리에 붙음 | 화면 규격 단위의 시험 | 화면 규격 단위가 정함 |
| X4 Proteus 내보내기(필요할 때만) | `hazop/export/dexpi_proteus.py` | 받을 CAD가 2.0을 못 읽는다는 확인 + 사용자 결정 뒤 | Proteus 스키마 이용 조건이 확인되기 전에는 구조 검사만 | 나중에 정함 |

- 순서: X1 → X2 → X3. X2는 X1의 `dexpi_map.py`와 되읽기, 화면 규격 V3의 `sheet_confirmation`을 쓰므로 둘 다 끝난 뒤 합니다. INTENT §3.8이 '정리된 보기와 DEXPI 내보내기는 같은 단위로 만든다'고 정했으므로, X2는 `d-chat`이 설계하는 정리된 보기 단위와 같은 차례에 묶고, 두 단위가 같이 쓰는 위치 계산(§5.3)은 X1이 만든 것을 씁니다.
- 파일 주인: `dexpi_map.py`는 X1이 만들고 X2는 읽기만 합니다. `registry.json`·`corrections.py`·`project.py`는 X1만 고칩니다. `confirmation.py`는 화면 규격 V3의 파일이고 X2는 부르기만 합니다. 화면 쪽 파일은 화면 규격의 주인 표를 따릅니다.
- 기준값: 가져오기는 기존 추출 점수(`check_apr1400.py`, `check_snp_baseline.py`)의 입력을 바꾸지 않습니다. X1은 `corrections.py`·`project.py`를 고치므로 커밋 전에 두 검사가 그대로인지 확인합니다(CLAUDE.md 규칙 12).

### 8.2 화면 자리(새 화면 규격 `app-shell-web.md` 기준, 그 문서는 고치지 않음)

| 기능 | 들어갈 자리 | 근거 줄 |
| --- | --- | --- |
| DEXPI 파일 받기 | 패널 '도면'의 끌어 놓기 자리(§2.3 ①등록 표, '등록'과 '추출·그래프 만들기'를 합친 줄). 엔진 쪽은 `register.add`(웹이 보내지 않고 Qt가 경로를 받음, §5.2 명령표) | `app-shell-web.md:165`, `:519` |
| 읽은 방법 '변환(DEXPI …)' 표시 | 패널 '도면' 목록 행의 상태 칩과 '더 보기' '추출 보고' | `app-shell-web.md:160`, `:170` |
| DEXPI 내보내기 단추 | 정리된 보기와 같은 자리에 둘지 분석 결과 머리 '내보내기'(Excel·IE 인계 묶음 옆)에 둘지는 `d-chat`이 정합니다. 이 규격의 권장은 **패널 '도면' 머리**입니다. DEXPI는 도면의 내보내기이고, 분석 결과 내보내기와 섞으면 '한 기능은 한 자리'(§2.2 원칙 5)를 지키기 어렵기 때문입니다 | `app-shell-web.md:96`, `:146`, `:234` |
| 웹 명령 | `dexpi.export`(구현된 이름. `graph_ids`: 도면 ID 목록, 내보낼 수 있는 쪽만 보낸다. 작업 스레드에서 돌고 결과는 `job.done`, 저장 위치·덮어쓰기는 Qt 대화상자), 읽기 `dexpi`(내보낼 수 있는 쪽 목록과 사유). 처음 규격 이름 `export.dexpi`는 쓰지 않는다(2026-11-14 정함, 검토 지적 7). `export.excel`·`export.ie_bundle` 줄과 같은 꼴 | `app-shell-web.md:533` |

### 8.3 공개 예제를 시험 입력으로 쓰는 법

- 쓸 수 있음: 2.0.1 Reference P&ID와 TrainingTestCases(둘 다 CC BY 4.0, F9). 출처 표시는 시험 파일 머리 주석과 `licenses/dexpi/`에 적습니다.
- 저장소에는 넣지 않습니다(총괄 지시). 시험은 환경변수 `HAZOP_DEXPI_SAMPLES`가 가리키는 폴더(지금은 `D:\HAZOP-trials\2026-11-13-dexpi\`)에 파일이 있을 때만 돌고, 없으면 건너뜁니다. CI에서는 손으로 만든 작은 파일만 돕니다.
- 앱에 묶는 것은 2.0.1 사양 원문에서 뽑은 클래스 목록뿐입니다(사양 CC BY 4.0, 출처·변경 표시). DEXPI XML XSD는 파일 단위 라이선스를 확인하지 못해(F7) 앱에 묶지 않고, 저장소의 참고 자료로 출처와 함께 두어 시험만 읽습니다. Proteus XSD는 이용 조건을 확인하기 전에는 저장소에도 넣지 않습니다(F8).

## 9. 총괄 위임으로 정한 것

질문 창을 띄우지 않고 권장안으로 정했습니다. 사용자가 다르게 정하면 이 표와 해당 절을 고칩니다.

| # | 정할 것 | 고른 것 | 이유 | 다른 안 |
| --- | --- | --- | --- | --- |
| V-1 | 어느 형식으로 주고받나 | 가져오기는 DEXPI XML 2.0.x와 Proteus 4.x(DEXPI 1.2~1.4) 둘 다, 내보내기는 DEXPI XML 2.0.1만 | 2.0부터 Proteus를 쓰지 않는 것이 공식 판(F1·F4). 그러나 지금 CAD 도구는 1.x 파일을 낼 가능성이 커서 받을 때는 둘 다 받아야 함. Proteus 스키마는 이용 조건을 모름(F8) | 내보내기도 Proteus(받는 CAD 호환이 큼, 스키마 검사를 못 함) |
| V-2 | 무엇을 내보내나 | 화면의 '쪽 확정'과 같은 함수(`sheet_confirmation`)가 `confirmed`라고 답한 쪽만. 그 안의 속성 미확인은 그 속성만 빼고 목록을 함께 냄 | 사용자 결정 '사람이 확정한 결과를 내보낸다'(INTENT §3.2)와 화면 규격 §10.6. 받는 쪽이 표시를 모른 채 확정값으로 읽는 일을 막음 | 확정 전 쪽도 '확정 전' 표시와 함께 냄 |
| V-3 | 노즐 | 가져올 때 노즐을 노드로 만들지 않고 끝점 `port`로 바꿈 | 지금 그래프 모양·구간 분할·탐색을 그대로 씀. 포트 규칙(A2)과 같은 자리 | 노즐을 노드로 둠(`kind=nozzle`, 탐색 경로가 한 단계 길어짐) |
| V-4 | 가져온 노드의 `origin` | 새 값을 만들지 않고 `pid_extract`. 도면은 기존 `source.format`에 `dexpi`(§4.1) | 읽은 방법은 도면의 성질. `origin`을 쓰는 곳(지식그래프 상태, ④ 근거, 화면 표시)을 바꾸지 않음 | `origin: dexpi_import` 신설 |
| V-5 | 스키마 검사 | XSD를 실행 중에 읽지 않고, XSD 규칙을 옮긴 Python 구조 검사. XSD와 같은지는 시험이 확인 | 외부 패키지를 더하지 않음. XSD 자체가 DOCTYPE·개체를 담아 안전 읽기로 못 읽음. XSD 파일 단위 라이선스 미확인(F7) | `xmlschema`(MIT) 또는 `lxml` 추가 |
| V-6 | DEXPI에 자리가 없는 정보 | DEXPI 파일에 넣지 않고 곁 파일 | 받는 도구와의 호환과 인증 시험을 해치지 않음 | `ClassExtension`으로 파일 안에 |
| V-7 | DEXPI `SteamGenerator` | 원전 증기발생기를 이 클래스로 내보내지 않고 `HeatExchanger`로 | DEXPI의 것은 가열로 계열(F12) | 이름이 같은 `SteamGenerator` |
| V-8 | 흐름 방향 | 연결 Source→Target과 구간 `FlowDirection`으로 향하는 쪽을 정하지 않음. 흐름 화살표·연결 기호만 `declared`로. 한 방향·양방향 구분은 `flow_class`로 받음 | 사양이 Source→Target을 흐름이라 적지 않고, `FlowDirection`은 양방향 여부만 말함(F13) | Source→Target을 흐름으로 봄 |
| V-9 | 개정판과 이중 등록 | 개정판은 앞 판의 수정 기록을 복사해 다시 적용하고 못 붙인 것은 목록으로. PDF와 DEXPI가 같은 도면이면 '쓰는 원본' 하나(권장 DEXPI), PDF 쪽 기록은 지우지 않음 | '사람이 고친 것은 잃지 않는다' | 개정판마다 수정 기록을 새로 시작 |
| V-10 | 위치 없는 구성요소 | 버리지 않고 미확인 `dexpi_no_position`. 쪽 확정을 막음 | 정리된 보기에서 안 보이고 세어지지도 않는 구성요소를 없앰 | 자동 배치 |

## 10. 사용자·총괄에게 넘길 것

- **INTENT 표기.** §2·§3.1·§3.2의 'DEXPI(Proteus XML)'은 2.0 이후와 맞지 않습니다(§0). 'DEXPI(지금 판 2.0.1, DEXPI XML. 받을 때는 1.x Proteus도)'로 고칠지 총괄이 정합니다. 이 문서는 INTENT를 고치지 않았습니다.
- **INTENT §6의 보류 'DEXPI 판(2.0 여부)과 라이선스 조건'**은 F1~F11로 대부분 닫힙니다. 남은 것: DEXPI XML 스키마 파일 단위 라이선스(F7), Proteus 스키마 이용 조건(F8), 'DEXPI' 이름 사용 조건(F10). 앱이 'DEXPI 지원'이라고 표시하려면 F10을 DEXPI e.V.에 묻는 것이 안전합니다.
- **문서 목록.** `docs/specs/README.md`의 문서 목록에 이 문서를 더하는 일은 그 파일 주인이 합니다(이 단위의 파일 주인은 이 문서와 문서번호 표 한 줄뿐).
- **화면 규격(`d-chat`).** `sheet_confirmation`의 `unconfirmed` 사유에 `no_position`(§5.3)을 더하는 일, DEXPI 도면의 '원본 보기'와 '원본 조각'이 무엇을 보이는지(§4 6번), `source_format` 값(§4.1 표와 같음).
- **PDF 개정판의 수정 기록.** §4.2 (가)와 같은 문제가 PDF·drawio 개정판에도 있습니다. 같은 규칙을 쓸지 정하는 일을 `extraction.md` 주인에게 넘깁니다.
- **추출 규격의 'DEXPI 용어 대응(A13)'** 절(`extraction.md`)은 '원문 미확인' 후보 표입니다. 이 문서 §3이 원문으로 확인한 표이므로, 그 절을 이 문서로 가리키게 고치는 일을 `extraction.md` 주인에게 넘깁니다.

## 11. 확인하지 못한 것

- (닫힘 2026-11-14) Y축 방향(F15)은 §5.3에 적은 대로 예제 파일로 정했습니다. 공식 SVG 그림과 겹쳐 보지는 않았습니다.
- DEXPI XML 스키마 파일 단위의 라이선스 명시(F7), Proteus 스키마 이용 조건(F8), 'DEXPI' 이름 사용 조건(F10), 인증 신청 자격(F11).
- 2.0 형식을 내보내는 CAD 도구가 있는지.
- `set_pressure`·구동 방식에 맞는 DEXPI 속성 이름. CAD가 판을 바꿀 때 `id`나 `PersistentIdentifier`를 유지하는지(§4.2).
- Proteus `Connection`의 `FromNode`·`ToNode` 번호의 뜻(§5.7).
- NRC RG 1.29의 지금 판 번호(S14는 Rev. 3 사본).
- DEXPI 검증기(`dexpi/dexpi-verificator`)를 쓸 수 있는지(저장소에 README만 있음).
- 공정 모델(Process) 객체를 가져올지는 이번 범위 밖으로 두었습니다.
- pstack(rev 0): 지난 차례에 Skill 호출이 `disable-model-invocation`으로 막힌 것을 확인했으므로, 이번에는 총괄 지시대로 `technical-writing`·`unslop`의 SKILL.md를 직접 읽고 그 기준으로 이 문서를 다듬었습니다. 설계 판단은 대부분 공식 자료 확인에 달려 있어 `architect`·`poteto-mode`의 절차는 쓰지 않았습니다.

## 12. rev 1에서 바뀐 곳(구현 중인 `c1-tools` 세션용)

총괄 반려(2026-11-14) 12건을 고쳤습니다. rev 0으로 이미 만든 코드가 있다면 아래 줄을 먼저 보십시오.

| # | 지적 | 바뀐 곳 | 구현에 미치는 것 |
| ---: | --- | --- | --- |
| 1 | Proteus 구간 안 밸브가 길에서 빠짐 | §3.1 배관 줄, 새 §5.7, F16 | Proteus는 `FromID` → 구간 안 부품(문서 순서) → `ToID`로 길을 만들고 이웃한 두 점마다 관계 하나. 2.0은 연결 하나 = 관계 하나(예제 23개 구간에서 두 형식이 같음을 대조) |
| 2 | 확정 안 된 결과가 DEXPI로 나감 | §2, §6.1, §6.2, V-2 | 내보내기는 `hazop/extract/confirmation.py`의 `sheet_confirmation`이 `confirmed`인 쪽만. 확정 전 쪽은 `manifest.json`의 `not_exported` |
| 3 | `ET.XMLParser`에 처리기를 걸 수 없음, XSD에 DOCTYPE | §5.1, §5.6, V-5 | `pyexpat.ParserCreate()` + `ET.TreeBuilder`로 안전 읽기. XSD는 실행 중에 읽지 않고 Python 구조 검사(`check_structure`). `xmlschema`를 더하지 않음 |
| 4 | 위치 없는 구성요소 | §5.3, V-10 | 미확인 `dexpi_no_position`(field `bbox`). 쪽 확정을 막음 |
| 5 | '흐름 방향 자리 없음'이 틀림 | F13, §3.1 흐름 줄, §3.6, §5.4, §7.3, V-8 | `PipingNetworkSegment.FlowDirection`(Single/Dual)을 `attributes["flow_class"]`로 받음. 향하는 쪽은 여전히 정하지 않음 |
| 6 | PDF·DEXPI 이중 등록, 개정판 | 새 §4.2, V-9 | `corrections.py`에 앞 판 기록 복사·재적용, `project.py`에 '쓰는 원본' 하나 |
| 7 | `read_method`가 `graph_version`을 바꿈 | §4 5번, §8.1 | 새 필드 없음. 기존 `source.format`에 `dexpi`, 판은 `source.dexpi_version`. `build.py`·`runinfo.py`는 고치지 않음 |
| 8 | 형식 이름이 세 곳에서 다름 | 새 §4.1 표 | 등록 `format: dexpi` + `dexpi_flavor`(`dexpi_xml`·`proteus`), 추출·화면은 `dexpi`. rev 0의 `dexpi_xml`·`proteus` 형식 값과 `read_method`는 쓰지 않음 |
| 9 | X3 파일 주인 | §8.1 X3 줄과 파일 주인 줄 | 화면 쪽 파일은 화면 규격의 주인 표를 따름 |
| 10 | `DOC_IDS`에 없음 | `scripts/migrate_doc_headers.py` | 이 문서를 HZ-PLN-22로 등록 |
| 11 | ID가 XSD 이름 규칙에 안 맞음 | §5.2 경로 ID, 새 §6.6 | 경로 ID는 `__`, 내보낼 때 `HZ_` + `[A-Za-z0-9_]` 밖 글자를 `_`로, 겹치면 `_2` |
| 12 | 경로 이름, 라이선스 표현, 원자력 용어 | 머리말 용어, F7, §5.6, §8.1, §8.3, S13·S14 | 클래스 목록 경로가 `resources/library/dexpi/2-0-1/classes.json`에서 `resources/library/dexpi-schema/classes-2-0-1.json`으로 바뀜. XSD는 앱에 묶지 않고 `resources/references/dexpi-schema/`에만. `licenses/dexpi/` 출처 표시는 그대로 |

그 밖에 바뀐 것: `FailAction` 값(F17)을 확인해 §3.4 고장 시 동작 줄을 '근사'로 고쳤습니다(`FL`은 `FailRetainPosition`으로 내고 곁 파일에 남김).
