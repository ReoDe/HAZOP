# hazop/chat — 앱 안 채팅

`hazop` 패키지의 하위 패키지다. 규격은 [채팅 창과 도구 호출](../../docs/specs/chat-panel.md)(HZ-PLN-21)이다.

## 무엇을 넣는가

- 채팅 읽기 도구와 도구 목록(`tools.py`, `registry.py`, `context.py`): 저장된 프로젝트 자료만 읽는 순수 함수
- 도구를 Claude Code CLI에 내놓는 stdio MCP 서버(`mcp_server.py`)와 채팅 세션(`session.py`)
- 답 카드 검사와 화면에 넘길 모양(`card.py`, `view.py`)

## 넣지 않는 것

- Qt 화면은 `hazop/app/`(예: `chat_panel.py`)에 둔다. 이 폴더는 Qt·네트워크 모듈을 import하지 않는다(`tests/test_chat_mcp_server.py` 정적 검사).
- 하위 프로세스는 `hazop/study/claude_cli.py`를 거친다. 이 폴더에서 `subprocess`를 직접 쓰지 않는다.
- 서버의 개발 환경 입구는 `scripts/run_chat_tools_server.py`, 배포본 입구는 `scripts/run_app.py`의 `--chat-tools`다.
- 시험은 `tests/`에 둔다(`test_chat_*.py`, 가짜 CLI·도구는 `tests/fake_claude/`).

## 이름 형식

`<모듈>.py`(소문자, 밑줄). 패키지마다 `__init__.py`가 있다.

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다.
단위별 파일 주인은 규격 §10 표를 따른다(서버·세션은 S-conn, 도구는 C1·C3, 카드는 C2).

## 폐기 기준

쓰지 않는 코드는 호출하는 곳을 모두 옮긴 뒤 같은 커밋에서 지운다.
