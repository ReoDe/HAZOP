# W6 앱 코드 색 리터럴 → 토큰 참조

> 기준: HEAD `2727e56`(feat/next-units) + W6 작업 트리(재작업 1회차 반영), 2026-11-06. 편집 범위는 [D8](../decisions.md).

## 1. 방식

- 앱 Python 코드의 색 리터럴을 `hazop/app/tokens.py`의 `COLORS`(`tokens.c(이름)`·`tokens.COLORS[이름]`·qss `%(이름)s`) 참조로 바꿨다. 문자열 서식 인자만 바꾸고 분기·흐름은 바꾸지 않았다.
- 새 토큰 2개(재작업 1회차, 총괄 판정): `on-fill` `#ffffff`(파랑·진한 채움 위 흰 글자), `ok-bg` `#dcfce7`(통과 칩 바탕). 둘 다 기존 리터럴과 같은 값이다.
- 새 상수 `tokens.CARD_SHADOW` = `0 2px 10px rgba(0,0,0,.06)`(카드 그림자). `web_css()` 범례와 독립 뷰어 목록 페이지가 함께 쓴다.
- `hazop/viewer/build.py`는 `from hazop.app import tokens`를 새로 가져온다. `tokens.py`는 아무것도 가져오지 않고 `hazop/app/__init__.py`도 모듈 수준 import가 없어 Qt를 끌어오지 않으며 순환 import도 없다(`hazop/kg/screen.py`가 이미 같은 방식으로 씀).

## 2. 치환 전후(HEAD `2727e56` 행 번호)

| 파일:행 | 전 | 토큰 | 후 값 | 값 변화 |
|---|---|---|---|---|
| `render.py:15·20·33` | `#92400e` | `warn-ink` | `#92400e` | 없음 |
| `render.py:102·133` | `#6b7280` | `muted` | `#6a717e` | W5(D7) 정렬. 흰 바탕 4.83 → 4.91:1 |
| `render.py:146` | `#9ca3af` | `muted` | `#6a717e` | **새 판단(D8)**. "③에서 보기(현재 지식그래프 읽기 불가)" 흰 바탕 2.54(SC 1.4.3 미달) → 4.91:1. 일반 보조 글자와 같은 색이 돼 "읽기 불가"는 문구로만 구분된다 |
| `analysis.py:511·519` | `#6b7280` | `muted` | `#6a717e` | W5 정렬 |
| `register.py:210·219·225·283·289·311·332·342` | `#b91c1c` | `err-ink` | `#b91c1c` | 없음 |
| `register.py:289·332` | `#15803d` | `ok` | `#15803d` | 없음 |
| `register.py:233·301·344` | `#92400e` | `warn-ink` | `#92400e` | 없음 |
| `register.py:241·304` | `#6b7280` | `muted` | `#6a717e` | W5 정렬 |
| `review.py:421·808` | `#b91c1c` | `err-ink` | `#b91c1c` | 없음 |
| `review.py:808` | `#fca5a5` | `err-line` | `#fca5a5` | 없음 |
| `widgets.py:116`(사람 확정 배지 글자) | `#ffffff` | `on-fill` | `#ffffff` | 없음 |
| `widgets.py:132`(위험도 제안 칩 바탕)·`144`(사람 확정 상자 바탕) | `#ffffff` | `card` | `#ffffff` | 없음 |
| `data.py:178`(그래프 노드 테두리)·`188`(header)·`190`(#graphsvg) | `#fff` | `card` | `#ffffff` | 표기만 |
| `viewer/build.py:34`(SVG 루트 배경) | `#ffffff` | `card` | `#ffffff` | 없음 |
| `viewer/build.py:82` | `#f4f5f7`·`#111827` | `bg`·`ink` | 같음 | 없음 |
| `viewer/build.py:83·86` | `#6b7280` | `muted` | `#6a717e` | W5 정렬 |
| `viewer/build.py:84` | `#fff`·`rgba(0,0,0,.06)` | `card`·`CARD_SHADOW` | 같음 | 없음 |
| `viewer/build.py:85·86` | `#e3e5e9`·`#2563eb` | `line`·`ui` | 같음 | 없음 |
| `tokens.py:100` `.hz-badge text` | `#fff` | `on-fill` | `#ffffff` | 표기만 |
| `tokens.py:101` `.hz-badge.weak rect` | `#fff` | `card` | `#ffffff` | 표기만 |
| `tokens.py:105` `.hz-legend` 그림자 | `rgba(0,0,0,.06)` | `CARD_SHADOW` | 같음 | 없음 |
| `tokens.py:123·128` 선택 단계 탭·주 버튼 글자 | `#ffffff` | `on-fill` | 같음 | 없음 |
| `tokens.py:131` 통과 칩 바탕 | `#dcfce7` | `ok-bg` | 같음 | 없음 |
| `tokens.py:143·146·149` 사람 확정 상자·입력란·표 바탕 | `#ffffff` | `card` | 같음 | 없음 |

**합계(재작업 2회차 검사 기준, 한 행에 둘이면 둘로 셈)**: HEAD에는 리터럴 52곳(`tokens.py` `COLORS` 블록 밖 11곳 포함)이 있었다. 이 중 50곳을 토큰·상수 참조로 바꿨다. 남은 리터럴은 허용 목록 3곳뿐이다(§4): HEAD부터 있던 반투명 채움 2곳과 새 `CARD_SHADOW` 정의 1곳. 허용 목록을 적용한 HEAD 실패 수는 50건이고(`test_pre_w6_code_fails`가 고정; 2회차부터 허용이 문맥에 묶여 HEAD `web_css` 범례 그림자 `rgba(0,0,0,.06)`도 실패로 셈), 작업 트리는 0건이다. 값이 바뀐 곳은 `muted` 9곳뿐이다.

- `.hz-badge`는 규칙이 `tokens.web_css()`(T6 범위)에 있어 직접 고쳤다. 배지 요소는 `webview.py`(T1) JS가 그리지만, 그 파일은 고치지 않았다.
- `#9ca3af`를 `muted`로 바꾼 이유: 이 글자는 "읽기 불가" 안내이고, 같은 값을 가진 토큰(`risk-ok-line`·T1 `a1-unknown`·`comp-other`)은 쓰임이 다르다. 비활성 버튼 글자도 `muted`를 쓴다(`QPushButton:disabled`).

## 3. 출력 비교(같은 입력의 전후)

| 대상 | 결과 |
|---|---|
| `tokens.qss()` | 바이트 단위로 같음 |
| `tokens.web_css()` | `:root`에 `--on-fill: #ffffff`·`--ok-bg: #dcfce7`가 추가됐고 `.hz-badge` 2곳은 `#fff` → `#ffffff`로 표기만 바뀜. 이 두 가지를 정규화하면 바이트 단위로 같음 |
| `tokens.kg_css_vars()`(③) | `--on-fill`·`--ok-bg` 변수 추가만. 나머지는 같음 |
| `widgets.badge`·`risk_chip`·`box`, `viewer/build.prepare_svg` | 같음 |
| `data.graph_only_html`(샘플) | `#fff` → `#ffffff` 표기 3곳만 다름 |
| `viewer/build.build_index([])` | `#6b7280` → `#6a717e` 2곳, `#fff` → `#ffffff` 1곳만 다름 |
| `render.holds_html([])` 등 | `#6b7280` → `#6a717e`만 다름 |
| `check_design --platform windows` 결과 JSON(100%·125%) | `rows`·`environment`·`limit`·`rc`(0)·`color_problems`([])가 전후 같음. 배치 시각 회귀 없음 |

## 4. 검사(`scripts/check_design.py`)

- 대상(`app_color_files()`, 14개): `hazop/app/**/*.py`와 `hazop/viewer/build.py`. `tokens.py`는 포함하되 `COLORS` 대입문만 뺀다. 범위는 AST 노드의 시작·끝 위치(열 포함)로 정한다(`APP_COLOR_EXCLUDE_BLOCKS`). 그래서 `COLORS = {...}; OTHER = "#000"`처럼 같은 행에 이어 쓴 대입은 검사된다. T1 소유인 `screens/knowledge.py`·`webview.py`(`APP_COLOR_T1`)는 대상에서 뺀다. 이 두 파일에 같은 검사를 돌린 결과는 리터럴 0곳이라 T1 후속 항목은 없다.
- `app_color_literals()`:
  - 주석은 보지 않는다. tokenize로 문자열 리터럴만 본다(문서 문자열·f-string 포함). 이어 붙인 문자열은 한 덩어리로 보고, 보고하는 행은 원본 행이다.
  - hex는 **기본이 색**이다(재작업 2회차). 다음 경우만 색으로 보지 않는다.
    - `href=`·`src=`·`url(` 뒤의 참조
    - 앞 글자가 이름 글자인 객체 이름 선택자(`QFrame#abc`)
    - CSS 선택자 문맥: 뒤에 `;`·`}` 없이 `{`가 오는 경우(`#abc {`, `#abc:not(.active) {`, `:not(#abc) {`)
    - 그래서 `setAttribute("fill", "#fff")`·`var c = '#fff'`·`<rect fill=#ffffff>`는 색으로 잡는다.
  - `rgb()`·`rgba()`·`hsl()`·`hsla()`는 여러 줄에 걸쳐도 잡는다. 보고할 때는 따옴표를 빼고 공백을 정리한다(이어 붙인 `'rgb(1, ' '2, 3)'` → `rgb(1, 2, 3)`).
  - CSS 이름 색은 선언 값 전체(`border: 1px solid red`)와 색 속성 따옴표 값(`fill="white"`, JS `x.color = "red"`)에서 찾는다. `--변수`·`%(이름)s`·`url(…)`(예: `url(red.png)`)은 빼고, CSS 주석(`/* … */`) 안은 hex를 포함해 아예 보지 않는다.
  - QColor와 Qt 전역 색은 ast로 본다. `QColor("red")`·`QColor(1, …)`(인자가 다음 줄이면 인자 행), `Qt.white`·`Qt.GlobalColor.darkRed`를 잡는다.
- 허용 목록 `APP_COLOR_ALLOW`(경로, 리터럴, 최상위 문장 이름, CSS 선택자) → 사유. 넷이 모두 맞을 때만 허용한다(재작업 2회차). 최상위 문장 이름은 리터럴을 감싼 최상위 def·class 이름이나 대입 대상 이름이다. 그래서 같은 rgba라도 tokens.py의 다른 함수·다른 규칙·다른 파일에 있으면 실패한다.

  | 경로 | 리터럴 | 문장 | 선택자 | 사유 |
  |---|---|---|---|---|
  | `hazop/app/tokens.py` | `rgba(37,99,235,.12)` | `web_css` | `.selected.sym, .selected.tagbox` | 클릭 선택 채움(반투명 ui). 독립 뷰어와 같은 값이어야 함(D5 ⑤ 검사) |
  | `hazop/app/tokens.py` | `rgba(220,38,38,.30)` | `web_css` | `.hz-cause.sym, .hz-cause.gnode, .hz-cause.tagbox` | 원인 설비 강조 채움(반투명 hl-cause). 반투명 채움은 토큰 밖(D7) |
  | `hazop/app/tokens.py` | `rgba(0,0,0,.06)` | `CARD_SHADOW` | 없음 | `CARD_SHADOW` 정의(장식 그림자) |

- 명암비 쌍: `"#ffffff"`·`"#dcfce7"` 리터럴 쌍을 토큰 이름으로 바꿨다(`on-fill`/`ui`·`human-line`·`hl-safeguard`, `ok`/`ok-bg`, 위험도 제안 칩 3쌍·보호수단 약한 배지 글자는 `/card`). `hl-safeguard`/`card`가 글자(4.5:1)와 그래픽(3:1)으로 겹쳐서, 더 엄격한 글자 쌍만 남겼다. 그래서 쌍 수가 67에서 66이 됐다(판정 범위는 줄지 않음). 모두 통과한다.
- 남은 한계(총괄 판정으로 기록만 하고 이번에 고치지 않음). 이 검사는 회귀 방지용 휴리스틱이다. hex·rgb·hsl 형태는 아래 경우에도 잡는다(예외: `href=`·`src=` 뒤, `url(…)` 안 전체, 객체 이름 선택자, 따옴표 없이 `{`가 이어지는 CSS 선택자 문맥). 놓치는 것은 CSS 이름 색과 일부 Qt 표기뿐이다. 현재 대상 코드에는 아래 사례가 0건이다. 근거: 대상 14개 파일의 모든 문자열 덩어리에서 CSS 이름 색과 같은 단어를 문맥 없이 찾았더니 `white-space`의 `white` 1건뿐이었다. `QColor.` 정적 생성자와 `import Qt as`도 0건이다.
  - 여러 줄에 걸친 CSS 선언 값의 이름 색(`border: 1px\n solid red`). 선언 값은 줄바꿈에서 끊는다.
  - 문자열 연결·이스케이프: `("border: 1px " "solid red")`(따옴표에서 값이 끊김), `fill=\"red\"`(역슬래시 때문에 속성 값으로 보지 못함).
  - 파이썬 dict·키워드 인자의 이름 색(`dict(color="red")`, `{"fill": "red"}`). 코드는 문자열 문맥 판정 대상이 아니다.
  - `QColor.fromRgb(…)`·`QColor.fromString("red")` 같은 QColor 정적 생성자, `Qt`를 다른 이름으로 가져와 쓴 전역 색(`Q.white`). `Qt.white`·`Qt.GlobalColor.white`라고 직접 쓴 표기는 잡는다.
  - 그 밖: 따옴표 없는 JS 대입(`x.color = red`), 앞에 다른 단어가 붙은 camelCase 속성(`textColor`), `QColor(변수)`를 놓친다. hex 기본값이 색이라 `#`이 붙은 hex 글자 id(`#fade` 등)는 색으로 오인할 수 있다. 오인하면 rc 1로 드러난다. f-string의 `{식}` 부분도 문자열 원문으로 본다. 선택자 판정은 뒤에 `{`가 오는지로 하므로, 세미콜론 없이 이어진 JS 코드에서 색 뒤에 `{`가 먼저 나오면 놓칠 수 있다.

`tests/test_design.py` `AppColorTest` 14건:
- 대상 파일: T1 제외, tokens·build 포함
- 실제 코드 0건
- 허용 목록이 실제로 쓰이고 사유가 있음
- COLORS 블록만 제외(같은 행 `; OTHER = "#000"`은 실패)
- 재현 입력 14가지
- 선언 값 전체(`border … red`, outline)
- 여러 줄(rgba·`QColor(` 다음 줄 "red"·이어 붙인 rgb의 따옴표 정리·f-string)
- 음성 13가지(주석 `# color: red`, 코드 `color = red`, 선택자 `#abc {`·줄 앞 선택자, `href='#abc'`, 위젯 이름, 문자 참조, 자리표시자 등)
- hex 기본 색: `setAttribute("fill", "#fff")`·`var c = '#fff'`·`<rect fill=#ffffff>`
- hex 예외: `#abc:not(.active) {`·`:not(#abc)`·`a#def`·`url(#abc)`·`src=`·`href=#abc`
- CSS 주석·`url(red.png)`
- 허용 목록 문맥(다른 함수·규칙·대입·파일이면 실패)
- 허용 목록이 경로에 묶임
- W6 이전 코드 50건

## 5. 열린 항목 권장안 — 그래프 설비 노드 선택 표시(이번 범위 밖, 구현하지 않음)

현재 상태([w5 §6.1](w5-명암비.md)): 설비 노드는 `#1d4ed8` 채움에 흰 테두리 1.5px이다. 선택하면 테두리가 `#2563eb` 3px로 바뀐다(`template.html:106`). 선택 테두리와 채움의 대비가 1.30:1이라, 선택하면 흰 띠가 사라지는 변화로만 보인다.

- **권장안 A — 바깥 고리**:
  - 선택된 그래프 노드는 흰 테두리(`--card`)를 유지하고, 반지름 +4px 위치에 `--ui` 2.5px 고리(채움 없음)를 따로 그린다. 앱의 보호수단 표시 `.hz-ring`(`webview.py:216~224`)과 같은 방식이다.
  - 대비는 고리/흰 캔버스 5.17:1, 흰 띠/설비 채움 6.70:1이다. 고리가 채움과 섞이지 않는다. 선택 색은 인터페이스 §4.1(선택 = UI 파랑)을 그대로 지킨다.
  - 필요한 것: 템플릿 JS의 선택 처리 수정(T6 범위는 "색·CSS만"이라 범위 결정 필요), 앱에 내장할 때의 `web_css()` 규칙, 렌더 확인.
  - **보완 1 — 보호수단 고리와 겹침**: `.hz-ring`은 노드 bbox에서 pad 6(계수된 보호수단은 6·10 두 겹)만큼 떨어진 둥근 사각형(`rx` 6, 선 2px)이다. 설비 노드(`NODE_R` 7, `template.html:609`)의 정축 방향 기준으로, 선택 고리는 선 중심이 11이고 바깥 가장자리가 12.25이다. 보호수단 고리는 선 중심이 13이고 안쪽 가장자리가 12이다. 그래서 두 선이 약 0.25px 겹친다. 모서리 쪽은 사각형이 멀어 떨어진다 [추론, 계산값·렌더 미확인].
  - **보완 2 — 겹칠 때 우선순위**: 선택 표시가 사용자 조작의 즉시 피드백이므로 맨 위로 그린다. 보호수단 고리는 그대로 두되, 같은 노드가 선택+보호수단이면 선택 고리를 +4 대신 보호수단 고리 안쪽(+2, 1.5px)으로 줄이는 것을 제안한다. 다른 안은 보호수단 고리 pad를 8·12로 넓히는 것이다(T1 `webview.py` 소유라 T1과 합의 필요).
  - **보완 3 — 렌더 확인 항목**:
    - 100%·125%에서 노드 크기별(`NODE_R` 설비 7·밸브 6·계장 5·배관 요소 4·배관 구간 3.5) 고리 간격
    - 선택+보호수단(계수·미계수)·선택+원인(`.hz-cause` 4px 테두리)·선택+경로 강조(`.hz-path` 3.5px)가 겹치는 상태
    - 강조 중 흐림(`hz-dim`)에서 선택 고리가 흐려지지 않는지
    - 확대·축소 시 고리 두께(`vector-effect` 여부)
    - 독립 뷰어와 앱 내장 뷰어에서 같게 보이는지
- 대안 B — CSS만 수정: `.selected.gnode`에 흰 테두리를 유지하고 `filter: drop-shadow(...)` 겹치기나 `outline`으로 바깥 표시를 한다. JS 수정은 없지만 QtWebEngine(Chromium)에서 SVG 원에 원형으로 그려지는지 확인하지 않았다 [추론, 렌더 미확인].
- 대안 C — 선택 색 변경(예: `--ink`): 설비 채움과 2.65:1로 3:1에 못 미치고 §4.1과 어긋나서 권하지 않는다.

## 6. 검증 결과(전용 venv `%USERPROFILE%\.hazop\venv-py312`)

| 명령 | 첫 구현 | 재작업 1·2회차 |
|---|---|---|
| `python -m unittest discover -s tests -t .` | 639개 OK(건너뜀 14), rc 0 | §6.1 |
| `python -m unittest tests.test_design` | 39개 OK | 1회차 43개 OK, 2회차 47개 OK(`AppColorTest` 14건) |
| `python scripts/check_design.py --colors-only` | rc 0 | 색 비교 통과, 명암비 66쌍 통과, 앱 코드 색 리터럴 14개 파일 0건(허용 3곳), rc 0 |
| `python scripts/check_design.py --platform windows` | 100%·125% 통과, 결과 JSON 전후 동일, rc 0 | §6.1 |
| `check_kg_screen`·`check_viewer`·`check_app`·`node check_viewer_paths.js` | 모두 rc 0 | §6.1 |

### 6.1 재작업 1회차 전체 검증

| 명령 | 결과 |
|---|---|
| `python -m unittest discover -s tests -t .` | 643개 OK(건너뜀 14), rc 0 |
| `python scripts/check_design.py --platform windows` | 색 비교·명암비 66쌍·앱 코드 색 리터럴 통과, 100% 1366×689·125% 1536×785 통과, 결과 JSON `rows`·`rc`·`color_problems` 작업 전 HEAD와 같음, 종합 rc 0 |
| `python scripts/check_kg_screen.py` | [OK] 14건, rc 0 |
| `python scripts/check_app.py` | 결과 전부 통과, rc 0 |
| `python scripts/check_viewer.py` | unittest 643개 OK 포함, 결과 통과, rc 0 |
| `node scripts/check_viewer_paths.js` | 도면 6개·사례 9560건·불일치 0건, rc 0 |
| 재작업 2회차 다시 실행 | unittest 647개 OK(건너뜀 14) rc 0, check_design windows 66쌍·앱 코드 0건(허용 3곳)·100%·125% 통과·결과 JSON rows 동일 rc 0, check_kg_screen [OK] 14건 rc 0, check_app rc 0, check_viewer(unittest 647 OK) rc 0, check_viewer_paths 불일치 0건 rc 0 |

- 최종 재검토 뒤 총괄 수정(D9): ① f-string·format 자리표시자 `{` 앞의 hex(`'#fff'>{msg}`)를 선택자로 오인해 놓치던 문제 — `{` 앞에 따옴표가 있으면 선택자로 보지 않음(CSS 자식 결합자 `>`는 막지 않음). ② `url(images/#fff.svg)`·`url(rgb(1,2,3).png)` 오탐 — `url(…)` 전체를 위치 보존 공백으로 가린 뒤 검사. 회귀 테스트 2건 추가.
