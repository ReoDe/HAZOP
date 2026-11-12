# docs/specs — 제품 규격

앞으로 만들 제품의 규격(옛 기획서/ 폴더)과 단계별 흐름도를 둔다.

## 무엇을 넣는가

- 제품 규격 문서(전체 기획, 단계별 기획, 인터페이스, 지식그래프 스키마 등). 문서번호 `HZ-PLN-nn`
- `flows/`: 단계별 흐름도. 문서번호 `HZ-FLW-nn`
- HAZOP 기법 지침서(`hazop-method-guide.md`). 앱이 읽고 내용 해시로 고정한 문서라 한 글자도 바꾸지 않는다

## 넣지 않는 것

- 화면 설계와 시안은 `docs/design/`에 둔다.
- 작업 단위의 진행·근거 기록은 `docs/units/`에 둔다.
- 결정과 남은 작업은 `docs/records/`에 둔다.

## 이름 형식

`<주제>.md`, 영어 소문자 kebab-case(예: `kg-schema.md`). 문서 머리(`doc_id`, `rev`, `status`, `author`, `reviewed`, `approved`)를 단다.

## 주인

문서는 해당 담당(기획 `hazop-planner`, 디자인 `hazop-designer`, 기록 `hazop-recorder`)이 쓰고, `approved`로 바꾸는 일은 총괄만 한다(HZ-GOV-02 §4.7).

## 폐기 기준

지우지 않는다. 쓰지 않게 된 문서는 `status: obsolete`로 두고, 문서번호는 다시 쓰지 않는다(HZ-GOV-02 §4.6, §4.12).
