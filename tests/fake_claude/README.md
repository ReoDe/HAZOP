# tests/fake_claude — 시험용 가짜 Claude CLI

Claude CLI 연결 시험이 진짜 CLI 없이 돌도록 흉내 내는 실행 파일을 둔다.

## 무엇을 넣는가

- `fake_claude.py`: 정해진 응답을 내는 가짜 CLI

## 넣지 않는 것

- 진짜 Claude CLI 호출 코드는 `hazop/study/claude_cli.py`에 둔다.

## 이름 형식

`fake_*.py`.

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다.

## 폐기 기준

Claude CLI 연결 시험이 없어지면 함께 지운다.
