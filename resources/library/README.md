# resources/library — 배포본에 묶는 기준 자료

앱이 분석에 쓰는 기준 자료다. 배포본에 폴더째 묶인다(옛 자원/기준/ 폴더).

## 무엇을 넣는가

- `risk-criteria/`: 위험도 기준표, 초기사건 분류표
- `symbols/`: P&ID 기호 사전
- `dexpi-schema/`: DEXPI 2.0.1 클래스 이름·상속 목록(`classes-2-0-1.json`, DEXPI 가져오기·내보내기가 읽음)
- `deviations/`: 이탈 후보 카탈로그와 적용 판단
- `patterns/`: 원인·결과 패턴

## 넣지 않는 것

- 참고용 원문과 도면은 `resources/references/`에 둔다.
- 사용자 작업 데이터는 `work/`에 둔다.
- 이 폴더 바로 아래에는 파일을 두지 않는다.

## 이름 형식

하위 폴더는 `FOLDERS`의 열쇠와 같은 이름이다. 파일은 `<내용>.json`(kebab-case).

## 주인

총괄이 승인한다. 카탈로그 JSON 4개는 `hazop/analysis/integrity.py`가 SHA-256으로 고정하므로 한 글자도 함부로 바꾸지 않는다.

## 폐기 기준

쓰지 않는 기준은 읽는 코드와 시험을 옮긴 뒤 지운다.
