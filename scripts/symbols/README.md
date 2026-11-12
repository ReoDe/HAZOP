# scripts/symbols — 기호 사전 도구

P&ID 기호 사전(`resources/library/symbols/`)을 늘릴 때 쓰는 도구를 둔다.

## 무엇을 넣는가

- 기호를 사전에 더하는 `add_symbols.py`
- 분류되지 않은 기호를 묶는 `cluster_unclassified.py`

## 넣지 않는 것

- 기호 사전 자료는 `resources/library/symbols/`에 둔다.
- 사전을 읽는 앱 코드는 `hazop/extract/symbols.py`에 둔다.

## 이름 형식

`<동사>_<대상>.py`.

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다. 사전 내용이 바뀌면 점수에 닿으므로 기준값 규칙(`CLAUDE.md` 규칙 12)을 따른다.

## 폐기 기준

사전을 더 늘리지 않게 되면 이 폴더를 `obsolete`로 표시하고 남겨 둔다.
