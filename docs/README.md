# docs — 모든 문서

이 저장소의 문서를 한곳에 모은다. 바로 아래는 여섯 폴더뿐이다(HZ-GOV-02 §4.2).

## 무엇을 넣는가

- [specs](specs/README.md): 제품 규격과 흐름도
- [design](design/README.md): 화면 설계와 시안
- [methodology](methodology/README.md): 방법론 카드
- [records](records/README.md): 결정로그와 남은 작업
- [units](units/README.md): 작업 단위별 기록
- [governance](governance/README.md): 이름 규칙 같은 운영 문서

## 넣지 않는 것

- 코드와 시험 입력은 `hazop/`, `scripts/`, `tests/`에 둔다.
- 기준 자료와 표본은 `resources/`에 둔다.
- 사용자 작업 데이터는 `work/`(git 제외)에 둔다.
- 프로젝트 소개와 진입 파일(`README.md`, `CLAUDE.md`, `INTENT.md`)은 저장소 최상위에 둔다.

## 이름 형식

폴더 이름은 영어 소문자와 `-`다. 여섯 폴더 밖에 일곱 번째 폴더를 만들려면 사용자 결정을 받는다. 검사는 `tests/test_naming_rules.py` N3이 한다.

## 주인

총괄. 하위 폴더는 각자의 규칙서가 주인을 적는다.

## 폐기 기준

폴더를 지우지 않는다. 문서는 하위 폴더의 폐기 기준을 따른다.
