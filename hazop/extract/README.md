# hazop/extract — 도면 추출(②)

`hazop` 패키지의 하위 패키지다.

## 무엇을 넣는가

- draw.io·PDF 도면에서 설비·배관·계기를 읽는 규칙, 기호 사전 읽기, 수정 연산, 추출 결과 보고
- DEXPI 파일(DEXPI XML 2.0, Proteus 1.x)을 읽어 같은 추출 결과로 옮기는 코드(`adapters/dexpi_read.py`·`dexpi_import.py`)와 DEXPI 클래스 대응표(`dexpi_map.py`)

## 넣지 않는 것

- 추출한 결과로 그래프를 만드는 코드는 `hazop/graph/`에 둔다.
- 시험은 `tests/`에 둔다.

## 이름 형식

`<모듈>.py`(소문자, 밑줄). 패키지마다 `__init__.py`가 있다.

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다.

## 폐기 기준

쓰지 않는 코드는 호출하는 곳을 모두 옮긴 뒤 같은 커밋에서 지운다.
