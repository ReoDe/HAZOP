# DEXPI 사양 출처·변경 표시

HAZOP는 DEXPI(Data Exchange in the Process Industry) 파일을 가져오고 내보낸다(`docs/specs/dexpi-exchange.md`, HZ-PLN-22).
아래 자료를 쓰는 곳의 출처와 변경을 이 파일에 적는다.

## 쓰는 자료

| 자료 | 저작자 | 라이선스 | 어디에 썼는가 |
|---|---|---|---|
| DEXPI Specification 2.0.1(사양 문서와 모델 정의 `src/model/Plant/{Piping,ProcessEquipment,Instrumentation}`) | DEXPI e.V. | CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) | `resources/library/dexpi-schema/classes-2-0-1.json`의 클래스 이름·상속, `hazop/extract/dexpi_map.py`의 대응표, DEXPI XML 구조(요소·속성 이름) |
| DEXPI Reference P&ID(2.0.1 사양 부록)와 TrainingTestCases 예제 | DEXPI e.V. | CC BY 4.0 | 시험 입력으로만 쓴다. 저장소에 넣지 않고 환경변수 `HAZOP_DEXPI_SAMPLES`가 가리키는 폴더에서 읽는다 |

## 변경 표시 (CC BY 4.0 §3(a)(1)(B))

- `classes-2-0-1.json`은 사양의 클래스 정의 파일에서 클래스 이름·소속 묶음(package)·추상 여부·상위 클래스만 뽑아 JSON으로 다시 쓴 것이다(`scripts/build_dexpi_library.py`). 설명문·속성 정의는 옮기지 않았다.
- 대응표는 우리 `kind`와 DEXPI 클래스를 잇는 우리 쪽 해석이다. DEXPI e.V.가 만든 것도 보증한 것도 아니다.
- 사양 문서와 예제 파일을 그대로 복사하지 않았다. 시험용 DEXPI 파일(`tests/fixtures/dexpi/`)은 이 저장소에서 손으로 만들었다.

## 앱에 묶지 않는 자료

- DEXPI XML 스키마 파일(`DEXPI_XML_Schema.xsd`)은 앱에 묶지 않는다. 파일 단위 이용 조건이 따로 적혀 있지 않아(HZ-PLN-22 F7) 참고 자료로만
  `resources/references/dexpi-schema/dexpi-xml-schema-2-0-1.xsd`에 원본 그대로(이름만 바꿔) 두고 시험만 읽는다. 출처는 GitLab
  `dexpi/Specification` 태그 `V2.0.1`의 `src/documentation/_static/DEXPI_XML_Schema.xsd`이고, 사양 전체의 CC BY 4.0이 적용된다고 본다(저작자 DEXPI e.V.).
  앱은 그 스키마가 정한 인스턴스 규칙(요소·속성·글자 규칙)을 `hazop/extract/adapters/dexpi_read.py`의 `check_structure`로 직접 검사하고,
  시험 `tests/test_dexpi_rules.py`가 이 표가 참고 자료 XSD와 같은지 확인한다.
- Proteus XML 스키마는 이용 조건을 확인하지 못해(F8) 저장소에도 넣지 않는다.

## 이름 사용

앱은 'DEXPI 파일을 가져오고 내보낸다'고만 적는다. 'DEXPI 인증' 같은 표현은 DEXPI e.V.의 인증을 받기 전에는 쓰지 않는다(F10·F11).

내보낸 파일의 출처 표시 문구: `DEXPI Specification 2.0.1, DEXPI e.V., CC BY 4.0`
