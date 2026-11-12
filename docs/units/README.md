# docs/units — 작업 단위 기록

작업 단위(과제)마다 폴더를 하나 두고 계획·진행·근거를 남긴다(옛 docs/YYYY-MM-DD-<slug>/ 폴더).

## 무엇을 넣는가

- 작업 단위 폴더 `YYYY-MM-DD-<slug>/`. 안에 `README.md`가 필수이고, 필요하면 `AGENTS.md`, `CLAUDE.md`, `PROGRESS.md`, `ROADMAP.md`, `decisions.md`, `evidence/`를 둔다.

## 넣지 않는 것

- 단위가 끝난 뒤에도 이어서 쓰는 규격은 `docs/specs/`에 둔다.
- 이 폴더 바로 아래에는 이 `README.md` 말고 낱개 파일을 두지 않는다(검사 N3).

## 이름 형식

`YYYY-MM-DD-<slug>`. 날짜는 단위를 연 날이고 slug는 영어 소문자 kebab-case다. 근거 문서는 `evidence/<단위 ID>-<내용>.md`.

## 주인

단위를 연 세션이 쓰고, 단위가 끝나면 총괄이 마감을 확인한다.

## 폐기 기준

지우지 않는다. 결정의 근거라 링크가 깨지면 안 된다. 쓰지 않게 된 단위는 README 맨 위에 '폐기'라고 적는다.
