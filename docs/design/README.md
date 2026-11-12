# docs/design — 화면 설계와 시안

화면 설계 문서와 HTML 시안을 둔다(옛 디자인/ 폴더).

## 무엇을 넣는가

- 화면 설계·분석 문서(화면 명세, 지식그래프 화면, AI 연결 화면). 문서번호 `HZ-DSN-nn`
- `mockups/`: HTML 시안과 그 PNG, 시안을 만드는 `build.py`

## 넣지 않는 것

- 제품 규격은 `docs/specs/`에 둔다.
- 앱의 디자인 토큰 코드는 `hazop/app/tokens.py`에 둔다.

## 이름 형식

문서는 `<주제>.md`(kebab-case). 시안은 `mockups/<주제>/<번호>-<화면>[-<폭>].<확장자>`.

## 주인

문서는 해당 담당(기획 `hazop-planner`, 디자인 `hazop-designer`, 기록 `hazop-recorder`)이 쓰고, `approved`로 바꾸는 일은 총괄만 한다(HZ-GOV-02 §4.7).

## 폐기 기준

지우지 않는다. 쓰지 않게 된 문서는 `status: obsolete`로 두고, 문서번호는 다시 쓰지 않는다(HZ-GOV-02 §4.6, §4.12).
