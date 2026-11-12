# resources/references — 참고 자료

검사와 시험의 입력이 되는 참고 자료와 외부 문서를 둔다(옛 자원/참고자료/ 폴더).

## 무엇을 넣는가

- `pid-samples/`: 샘플 도면(검사·시험 입력). 폴더 이름은 기준값의 키다
- `pid-symbol-catalog/`: 받은 P&ID 기호 카탈로그
- `APR1400_DCD/`: APR1400 DCD 도면 목록과 추출 도구(원본 PDF는 git에 없다)
- `hazop-method/`, `photos/`: 로컬 전용 자료(git 제외)

## 넣지 않는 것

- 앱이 분석에 쓰는 기준 자료는 `resources/library/`에 둔다.
- 표본 입력은 `resources/samples/`에 둔다.

## 이름 형식

받은 파일 이름을 그대로 두는 폴더가 있다(`pid-samples`, `pid-symbol-catalog`, `APR1400_DCD`. HZ-GOV-02 §5.5).

## 주인

총괄이 승인한다. 샘플 도면 이름은 그래프 판 해시와 기준값에 들어가므로 바꾸지 않는다.

## 폐기 기준

쓰지 않는 자료는 참조하는 시험과 기준값을 먼저 옮긴 뒤 지운다.
