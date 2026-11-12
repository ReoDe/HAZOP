# tests — 시험

단위 시험, 시험 입력, 회귀 기준값을 둔다. 시험은 시험용 venv(`%USERPROFILE%\.hazop\venv-py312`)로 돌린다(`CLAUDE.md` 규칙 11).

## 무엇을 넣는가

- `test_<모듈 또는 기능>.py`: 단위 시험(`python -m unittest`로 전부 돌린다)
- `fixtures/<주제>/`: 시험 입력
- `baselines/`: 회귀 기준값
- `fake_claude/`: 시험용 가짜 Claude CLI

## 넣지 않는 것

- 합격·불합격 검사 명령은 `scripts/check_*.py`에 둔다.
- 배포본 검사는 `packaging/verify_*.py`에 둔다.

## 이름 형식

`test_*.py`. 시험 클래스가 든 파일 이름이 `test_`로 시작하지 않으면 `unittest`가 건너뛰므로 검사가 막는다(N5).

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다.

## 폐기 기준

시험이 가리키던 코드가 없어지면 그 시험도 같은 커밋에서 지운다.
