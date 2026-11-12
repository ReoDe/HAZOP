# hazop — 앱 코드

HAZOP 분석 데스크톱 앱의 Python 코드다. 단계별 하위 패키지로 나눈다.

## 무엇을 넣는가

- 공용 모듈: `paths.py`(폴더 표), `store_io.py`(저장), `workroot.py`(작업 루트 이전), `console.py`
- 하위 패키지: `register`, `extract`, `graph`, `kg`, `study`, `analysis`, `review`, `evaluate`, `export`, `ie`, `contract`, `viewer`, `app`

## 넣지 않는 것

- 실행 명령은 `scripts/`에 둔다.
- 시험은 `tests/`에 둔다.
- 배포 도구는 `packaging/`에 둔다.
- 기준 자료와 표본은 `resources/`에 둔다.

## 이름 형식

파일은 `<모듈>.py`(소문자, 밑줄). 폴더 경로 문자열은 직접 쓰지 않고 `paths.folder()` 등으로 얻는다(`tests/test_path_literals.py`가 막는다).

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다.

## 폐기 기준

쓰지 않는 코드는 호출하는 곳을 모두 옮긴 뒤 같은 커밋에서 지운다.
