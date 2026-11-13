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

## 영역(패널) 등록 방법 — 공유 파일을 직접 고치지 않는다

새 영역(예: 지식그래프, AI 검토, 표제란, 문서, 행동 기록)은 **자기 파일만 만들고**, 공유 파일(`api.py`·`web/js/main.js`·`web/js/panels/index.js`·`shell.css`·`window.py`)에는 **등록 한 줄**만 들어간다. 그 한 줄은 이 틀을 맡은 세션(s-frame)이 넣는다. 총괄에게 "등록 줄을 요청한다"고 말하면 된다. 공유 파일은 이 틀 담당만 고친다.

### 1. Python 쪽: `hazop/shell/api_<이름>.py`

모듈이 내보내는 이름은 아래뿐이다. 모듈 안에서 `hazop.shell.api`는 순환을 피하려고 **함수 안에서** 가져온다(`from hazop.shell import api`).

| 이름 | 필수 | 뜻 |
| --- | --- | --- |
| `read(engine, parts, query)` | 예 | 읽기 API. `parts[0]`이 이 영역의 토픽이다. 답은 `api._json(...)`, 없는 자료는 `None`(404) |
| `register(commands)` | 명령이 있으면 | `commands["<이름>.<동작>"] = api.Command(...)`으로 명령을 올린다. 이름이 겹치면 `ValueError`로 바로 알린다 |
| `TOPICS` | 아니오 | 이 모듈이 읽는 토픽 튜플. 없으면 파일 이름에서 정한다(`api_kg.py` → `("kg",)`, `clean_items.py` → `("clean",)`). 한 모듈이 토픽을 여럿 읽으면(`api_drawings` → `("sheetconf", "dexpi")`) 적는다 |
| `PROJECT_PREFIXES` | 아니오 | 프로젝트에 묶이는 명령 접두어. 없으면 `TOPICS` 각각에 `"."`를 붙인 것이다(`kg.`). 묶인 명령은 웹이 프로젝트 ID를 함께 보내야 하고, 지금 프로젝트와 다르면 거절된다 |

규칙:

- 웹이 보내는 쓰기 명령은 **지문(`ver`)과 판(`rev`)을 받아 어긋나면 `stale`로 거절**한다(엔진 공통 규칙, `docs/design/app-shell-web.md`). `by`·`at`은 Python이 채운다.
- 웹은 **파일 경로를 보내지도 받지도 않는다**. ID만 쓴다. 저장 위치는 Python이 창으로 묻는다(`engine.hooks`).
- 오래 걸리는 일은 `engine.start_job(label, fn, kind)`로 돌린다. 바뀐 것은 `engine.changed(토픽, rev)`로 웹에 알린다.
- 모듈이 깨져도(ImportError) 새 화면은 뜨고 그 영역만 꺼진다.
- 등록 줄은 `api.py` 맨 위 `MODULES` 튜플에 모듈 이름 하나(`"api_kg"`)를 더하는 것이 전부다.

### 2. 웹 쪽: `web/js/panels/<이름>.js`

- 패널 컴포넌트 하나를 `export`한다. 받는 속성은 `{ onClose, onOpen }`다(`onOpen(graphId)`는 도면 열기).
- 이 영역의 상태는 `createStore`로 따로 둔다(`<이름>_state.js`). 공용 `store`에는 열린 패널(`panel`)·보는 도면(`sheet`) 같은 보기 상태만 둔다. 프로젝트를 바꾸면 `areas.js`의 `resetAreas()`가 초기화해야 하니 `reset()`을 내보내고 그 한 줄을 요청한다.
- 엔진 호출은 `bridge.js`의 `cmd`·`read`·`onChanged`만 쓴다.

등록은 `web/js/panels/index.js`의 `PANELS` 배열에 항목 하나다.

```js
{ name: "kg",                 // store.panel에 들어가는 이름(영문 소문자)
  icon: "route",              // 왼쪽 메뉴 아이콘 이름(hazop/app의 아이콘 목록에 있는 이름)
  label: "지식그래프",         // 단추 이름과 제목말. 단축키가 있으면 " (Ctrl+5)"가 뒤에 붙는다
  key: "5",                   // 선택. Ctrl+<key>로 열고 닫는다. 1~4는 이미 쓴다
  component: KgPanel,         // 패널 컴포넌트
  css: "kg.css",              // 선택. 이 패널 전용 CSS(panels/ 안). 있으면 index.js가 한 번만 붙인다
  badge: (s) => 숫자 | null,  // 선택. 메뉴 단추 위의 숫자. s는 공용 store 상태
  place: "bottom" }           // 선택. "bottom"이면 메뉴 아래쪽(설정 옆)
```

### 3. CSS

- 패널 전용 규칙은 `web/js/panels/<이름>.css`에 둔다(`nodes.css` 방식). 클래스 이름은 `kg-`처럼 영역 접두어를 붙여 겹치지 않게 한다.
- `shell.css`에는 **둘 이상의 영역이 함께 쓰는 공통 규칙**만 둔다. 색·간격은 `tokens.css`의 변수만 쓰고 색 값을 새로 적지 않는다.

## 이름 형식

Python 파일은 `<모듈>.py`(소문자, 밑줄). 웹 파일은 소문자·밑줄 영어 이름(`index.html`, `app.css`, `js/main.js`)이다.

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다. `web/js/canvas/`의 구현 파일은 뷰어를 만든 세션(`s-viewer`)이 맡고, 그 밖은 1단계 틀 세션이 맡는다.

## 폐기 기준

이전 화면(`hazop/app/screens/`)을 없애기로 한 4단계 판단 뒤에 이 틀이 유일한 화면이 된다. 쓰지 않는 코드는 호출하는 곳을 모두 옮긴 뒤 같은 커밋에서 지운다.
