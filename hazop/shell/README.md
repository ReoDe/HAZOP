# hazop/shell — 도면 중심 웹 화면의 Python 쪽

`hazop` 패키지의 하위 패키지다. 새 화면(HTML·CSS·JS)을 앱 안의 웹 화면 하나로 띄우는 틀이다. 규격은 [`docs/design/app-shell-web.md`](../../docs/design/app-shell-web.md)(HZ-DSN-05)다.

## 무엇을 넣는가

- `window.py`: 창 하나에 웹 화면 하나를 올리는 틀
- `scheme.py`: 앱 전용 주소 체계 `hazop-app://`의 등록과 처리기, 경로 검사
- `api.py`: 웹이 보내는 명령 표(`COMMANDS`)와 읽기 API
- `web/`: 빌드 없이 그대로 읽는 웹 화면(HTML·CSS·JS, 묶음 라이브러리 `vendor/`)

## 넣지 않는 것

- 이전 위젯 화면은 `hazop/app/`에 둔다. 이 폴더는 이전 화면을 부르지 않는다.
- 추출·그래프·구간 저장·분석 같은 엔진은 각자의 패키지(`hazop/extract/`, `hazop/study/` 등)에 둔다.
- 시험은 `tests/`에 둔다.

## 이름 형식

Python 파일은 `<모듈>.py`(소문자, 밑줄). 웹 파일은 소문자·밑줄 영어 이름(`index.html`, `app.css`, `js/main.js`)이다.

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다. `web/js/canvas/`의 구현 파일은 뷰어를 만든 세션(`s-viewer`)이 맡고, 그 밖은 1단계 틀 세션이 맡는다.

## 폐기 기준

이전 화면(`hazop/app/screens/`)을 없애기로 한 4단계 판단 뒤에 이 틀이 유일한 화면이 된다. 쓰지 않는 코드는 호출하는 곳을 모두 옮긴 뒤 같은 커밋에서 지운다.
