# W4 토큰 단일 출처·뷰어 색 통일

> 조사·구현 일시: 2026-11-05 · 대상: `feat/next-units` HEAD `2178ddf` + W4 작업 트리 · 작업: hazop-developer · 결정: [D5](../decisions.md)(확정, 총괄 승인)

## 1. 방식

- 정본은 `hazop/app/tokens.py`(`COLORS`)다. 앱 안의 ② 뷰어는 `web_css()`가 `:root`와 클릭 선택 채움을 덮어쓰므로 원래 앱 색으로 보였다. 차이는 독립 뷰어(빌드한 HTML을 브라우저로 연 경우)에서만 났다([W1 §2](w1-survey.md)).
- `hazop/viewer/build.py`는 편집 허용 범위 밖이라 빌드 때 주입하지 않는다. 템플릿 `:root`를 같은 값으로 맞추고 `scripts/check_design.py` 색 비교로 강제한다(D5).

## 2. 독립 뷰어 `template.html` 전후

| 항목 | 전 | 후 | 앱 값(`tokens.py`) | 구분 |
|---|---|---|---|---|
| `--valve` | `#2563eb` | `#0f766e` | `#0f766e` | **값 통일**(D1, 인터페이스 §4.1 밸브 청록) |
| `--selected` | `#dc2626` | `#2563eb` | `web_css()` `--selected` = `--ui` `#2563eb` | **값 통일**(D1, 인터페이스 §4.1 선택 UI 파랑) |
| `.selected.sym, .selected.tagbox` 채움 | `rgba(220,38,38,.12)` | `rgba(37,99,235,.12)` | `web_css()` 같은 규칙 | **값 통일** |
| `#stage` 바탕, `.gnode` 테두리 | `#fff` | `var(--card)` | `--card` `#ffffff` | 같은 값, 토큰 참조로 |
| `.glabel` | `#374151` | `var(--ink-2)` | `#374151` | 같은 값, `:root`에 `--ink-2` 추가 |
| `.chip.alignwarn` | `#fef3c7`/`#92400e` | `var(--warn-bg)`/`var(--warn-ink)` | 같은 값 | 같은 값, `:root`에 추가 |
| `.onpath` 테두리(2곳) | `#ea580c` | `var(--hl-path)` | `#ea580c` | 같은 값, `:root`에 추가 |
| `.chip.passed::before` | `#16a34a` | 그대로(허용 목록) | `--ok` `#15803d` | **남김**: 값이 달라 통일하면 D1 범위 밖 |
| `aside .warn`, `#pathq .res .bad` | `#b45309` | 그대로(허용 목록) | 토큰 없음(`--warn-ink` `#92400e`) | **남김**: 토큰 없음 |

`.onpath.sym` 채움 `rgba(234,88,12,.15)`, `.sym`·`.tagbox`의 반투명 채움, 그림자 `rgba(0,0,0,…)`는 그대로다. 검사는 이 rgb가 토큰 색 또는 검정인지만 본다.

## 3. 앱 화면·③ 지식그래프 색 변화: 없음

- `tokens.COLORS`·`web_css()`·`qss()`·`kg_css_vars()` 출력이 HEAD와 바이트 단위로 같다(HEAD `tokens.py`를 임시 폴더에 꺼내 비교: 네 값 모두 `True`).
- 앱 안 ②는 전에도 `web_css()`로 `--valve`·`--selected`·선택 채움을 덮어썼다. 바뀐 하드코딩은 모두 같은 값을 토큰으로 바꾼 것이다. 따라서 앱 ②의 보이는 색은 바뀌지 않는다 [추론: 렌더 화면 비교는 하지 않음].
- `hazop/app/widgets.py` `risk_chip`: 문자열 `"#9ca3af"` 비교를 `tokens.COLORS["risk-ok-line"]`로 바꿨다. 값이 같아 출력이 같다(위험도 1·3·5 확인). W5에서 토큰 값을 바꿔도 조용히 어긋나지 않는다.

## 4. 색 비교 검사

- `python scripts/check_design.py --colors-only`(Qt 없이) 또는 기본 실행의 첫 단계. 실패하면 플랫폼과 관계없이 rc 1.
- 검사 항목: [D5](../decisions.md) ①~⑤. CSS 주석을 지운 뒤 규칙(선택자·속성·값) 단위로 파싱한다. `:root`는 정확히 하나여야 하며, 뒤쪽 재선언·다른 규칙이나 인라인 `style`의 `--변수` 재선언·`:root` 안 중복을 거부한다. `var( --x , 대체값 )`의 공백·대체값·중첩을 읽는다. 색 리터럴(3·4·6·8자리 hex, `rgb()`·`rgba()`·`hsl()`·`hsla()` 쉼표형·공백형, 색 속성 값의 CSS 이름 색)은 `<style>`·HTML 속성·JS 문자열을 포함한 템플릿 전체에서 찾는다. 스타일 밖 이름 색은 색 속성(`color`·`background`·`border`·`outline`·`fill`·`stroke`)의 값 위치만 본다: `style="fill:red"`, 속성 `fill="red"`, JS `.fill = "red"`·`{ fill: "red" }`·`setAttribute("fill", "red")`.
- 허용 목록(`VIEWER_COLOR_ALLOW`)은 (선택자, 속성, 값) 조합 3개다: `.chip.passed::before`·`color`·`#16a34a`, `aside .warn`·`color`·`#b45309`, `#pathq .res .bad`·`color`·`#b45309`. 다른 위치·속성의 같은 값은 실패한다. 반투명 `rgba`는 rgb가 앱 토큰 색·검정이고 알파 < 1일 때만 통과한다(불투명 `rgb()`는 `var()`로 바꿔야 함).
- 템플릿 JS·HTML 속성에는 색 리터럴이 없어 허용 목록에 넣을 JS 항목이 없다. `EDGE_COLOR`에 없는 관계 종류는 리터럴이 아니라 `undefined`가 되고(아래 §5), 범례의 대체 색은 `var(--muted)`다.
- 변경 전 템플릿(`git show HEAD:hazop/viewer/template.html`)에 돌리면 10건 실패: `--valve`·`--selected` 값 차이, 하드코딩 `#fff`×2·`#fef3c7`·`#92400e`·`#374151`·`#ea580c`×2, 선택 채움 차이. 변경 후 0건(재작업 1회차 검사기로 다시 확인).
- `tests/test_design.ViewerColorTest` 15건(재작업 2회차 5건 추가: 선택 채움 재선언 3종·한 규칙 안 중복, `--UI`/`var(--Card)` 대소문자·`VAR()`/`Var()` 함수명, `box-shadow`·`text-shadow`·`stop-color`·`flood-color`·SVG `stop-color` 속성·JS `backgroundColor`·`borderTopColor`·`stopColor`·`boxShadow`, HTML·JS 실패 줄 번호 = 원본 행, 결과 JSON rc = 종료 코드): 실제 템플릿 통과, W4 이전 템플릿(`git show 2178ddf:…`, git 없으면 건너뜀) 10건 실패, 정상 주석·공백 문법·HTML·JS 정상 문법(`"none"`·`transparent`·`"var(--" + 종류`) 통과, 재현 입력 23종 실패(뒤쪽 `:root` 재선언, 다른 규칙·인라인 변수 재선언, `var( --does-not-exist )`·대체값 안 정의 없는 변수, `#123456ff`·`#fffa`, 다른 위치·다른 속성의 `#b45309`, 인라인 `style="color:#ff0000"`, JS 문자열 hex, `red`·인라인 `white`·대체값 안 `red`, `rgb(1, 2, 3)`·`rgb(1,2,3)`, 토큰 색이라도 불투명 `rgb()`, `rgba(1 2 3 / .5)`, `hsl()`, 이름 색 `red`의 SVG 속성·JS 대입·JS 객체 키·`setAttribute` 위치), 허용 목록이 규칙 단위인지, 선택 채움·데이터 종류 변수 누락, 리터럴 추출 함수.

## 5. 남은 일·한계

- 허용 목록 2색(`#16a34a`, `#b45309`)의 통일 여부는 결정 대상이다(D5에 열린 항목으로 기록).
- 템플릿 JS의 알 수 없는 관계 종류 대체 색(`EDGE_COLOR` 없음 → `undefined`, [W1 §2](w1-survey.md))은 JS라 "색·CSS만" 범위 밖이다. 고치지 않았다.
- 글꼴 차이(템플릿 Pretendard 우선)는 T2 글꼴 결정(인터페이스 §9) 대기라 그대로 두었다.
- 범위 밖 하드코딩(앱 코드 hex 0개는 [PROGRESS](../PROGRESS.md) `W6`으로 넘김):
  - 편집 허용 범위 밖: `hazop/viewer/build.py` 목록 페이지 CSS, `hazop/app/data.py` `#fff` 3곳, `render.py`·`register.py` 인라인 색, `analysis.py`·`review.py` 인라인 색(배치·폭만 허용).
  - 범위 안이지만 새 토큰(흰 글자·흰 바탕·통과 칩 바탕)이 필요해 W4 완료 기준 밖으로 본 것: `tokens.py` `qss()`·`web_css()` 안의 `#ffffff`·`#fff`·`#dcfce7`·`rgba()`, `hazop/app/widgets.py` `#ffffff` 116행(`badge` 사람 확정 글자)·132행(`risk_chip` 제안 칩 바탕)·144행(`box` 사람 확정 바탕).
- 재작업 2회차 보강: `:root` 밖 다른 규칙이 `.selected.sym`·`.selected.tagbox`의 `fill`을 다시 선언하거나(뒤 규칙·일부 선택자·더 구체적인 선택자) 한 규칙 안에 같은 속성을 두 번 쓰면 실패한다. 선택 채움 값은 마지막 선언으로 비교한다. 같은 선택자를 `@media` 안에서 다시 쓰는 것은 지금 템플릿에 많아(header·aside 등) 선택자 단위 중복은 금지하지 않았다. `--변수` 이름은 대소문자를 그대로 두고(`--UI` ≠ `--ui`), `var` 함수명은 대소문자를 무시한다. 색 검사 결과는 배치 판정 결과 JSON의 `rc`·`verdict`·`color_problems`에 합산한 뒤 저장한다.
- 색 속성 목록(`_COLOR_PROP`)은 JS camelCase를 잡으려고 대소문자 무시·하이픈 생략을 허용한다. 그래서 `backgroundcolor`처럼 CSS에 없는 이름도 색 속성으로 보지만, 그 값에 이름 색이 있을 때만 실패하므로 오탐은 작다 [추론]. JS 변수 이름이 색 속성과 같고(`var color = "red"`) 그 값이 이름 색이면 실패로 잡힌다(지금 템플릿의 `color` 변수는 `"var(--"`로 시작해 해당 없음).
- 정규식 검사라 HTML·JS 안의 `#abc`처럼 16진 글자 3·4·6·8자로만 된 id 참조를 색으로 오인할 수 있다. `<style>`은 선언 값에서만 찾으므로 선택자는 대상이 아니다. 오인하면 실패로 드러난다(지금 템플릿에는 없음).
- 검사는 템플릿 문자열만 본다. JS가 실행 중에 만드는 `"var(--" + 종류 + ")"`는 데이터 종류 변수 목록(`VIEWER_DATA_VARS`)이 `:root`에 있는지로만 확인한다.

- 최종 재검토(Claude) 경미 한계: 앞에 다른 단어가 붙은 camelCase 속성(`textColor` 등)의 이름 색은 놓친다(hex는 잡힘). 색 속성 값 자리의 식별자가 CSS 이름 색과 철자가 같으면(`o.stroke = Math.tan(x)`의 `tan`) 오탐한다 — 현재 템플릿엔 없고 오탐은 rc 1로 드러난다. `check_design.py` 결과 JSON의 rc는 실행 한 번 기준이라 100% JSON은 125% 결과 합산 전 값이다(기존 동작). 총괄 수정(D6): 선택 채움 판정을 복합 선택자별 클래스 집합으로 하고 기준 규칙의 fill 중복 선언을 금지.

### 5.1 후속 제안(이번에 편집하지 않음)

- 인터페이스 §4.1 340행 "아래 값은 `hazop/viewer/template.html`의 `:root`를 기준으로 하고"는 D5와 어긋난다(정본은 `tokens.py`). "값의 정본은 `hazop/app/tokens.py`이며 독립 뷰어 `:root`는 검사로 맞춘다" 취지로 바꿀 것을 제안한다.
- 인터페이스 §4.1 351행 "클릭 선택은 `--selected`(빨강) 대신 UI 파랑 … `template.html` 수정이 필요합니다"는 이번 작업으로 반영이 끝났다. 현재형("클릭 선택은 UI 파랑(`--selected` = `--ui`)")으로 바꿀 것을 제안한다.
- 두 문구 모두 `specs/interface.md` 담당 순서(T2 작업 뒤)에 맞춰 반영한다.

### 5.2 W5 검토 항목으로 넘기는 관찰

- 클릭 선택 테두리 `--selected` = `--ui` `#2563eb`와 설비 노드 `--equipment` `#1d4ed8`이 같은 파랑 계열이라, 설비를 선택했을 때 구분이 약할 수 있다(굵기 3으로만 구분) [추론, 렌더 확인 안 함].
- 선택 채움 `rgba(37,99,235,.12)`가 hover 채움 `.sym:hover` `rgba(37,99,235,.18)`보다 옅다. 선택 상태가 hover보다 덜 진하게 보인다.

## 6. 검증 결과(전용 venv `%USERPROFILE%\.hazop\venv-py312`, Python 3.12.10)

| 명령 | 결과 |
|---|---|
| `python -m unittest discover -s tests -t .` | 576개 OK(건너뜀 14), rc 0 |
| `python scripts/check_design.py --platform windows` | 색 비교 통과. 100% 최대 1062×673 ≤ 1366×689, 125% 최대 1062×678 ≤ 1536×785(각 25측정, W3와 같은 값). 종합 rc 0 |
| `python scripts/check_kg_screen.py` | V2·V1·S1 포함 [OK] 14건, 결과 통과, rc 0 |
| `python scripts/check_viewer.py` | 샘플 재추출·뷰어 재빌드·HTML 검사·unittest 580개 OK(건너뜀 14, 동시 작업 중인 `tests/test_packaging.py` 변경 포함), rc 0 |
| 재작업 1회차 다시 실행 | unittest 583개 OK(건너뜀 14) rc 0, check_design windows 색 비교 통과·100%·125% 통과 rc 0, check_kg_screen [OK] 14건 rc 0, check_viewer unittest 583개 OK rc 0 |
| 재작업 1회차 이어서(2026-11-06, 담당 교체) | unittest 617개 OK(건너뜀 14) rc 0 — 같은 시각 T2 담당이 `tests/test_packaging.py`·`scripts/build_package.py`를 고치는 중이라 앞선 두 번은 `test_packaging` 1~2건 실패(T6 변경과 무관), 세 번째 rc 0. `test_design` 20개 OK. check_design windows 색 비교 통과·100%·125% 통과 종합 rc 0, check_kg_screen [OK] 14건 rc 0, check_viewer unittest 617개 OK rc 0, check_viewer_paths 도면 6개·사례 9560건·불일치 0건 rc 0 |
| 재작업 2회차(2026-11-06 02:00) | unittest 622개 OK(건너뜀 14) rc 0, `test_design` OK, `check_design --colors-only` rc 0(W4 이전 템플릿은 함수로 돌려 10건 실패), check_design windows 색 비교 통과·100%·125% 통과 종합 rc 0(결과 JSON 2개 `color_problems: []`), check_kg_screen [OK] 14건 rc 0, check_viewer unittest 622개 OK rc 0, check_viewer_paths 도면 6개·사례 9560건·불일치 0건 rc 0 |
| `node scripts/check_viewer_paths.js` | 총괄 수정 `f3b309e` 뒤 저장소 그대로 도면 6개·사례 9560건·불일치 0건, rc 0. 그 전에는 rc 1: `출력/뷰어/kg-screen.html`(③ 산출물, 그래프 JSON 없음)을 도면으로 읽어 "내장 그래프 없음"으로 멈춘다. W4 변경과 무관(색·CSS만 바꿈)하며, 이 파일만 뺀 임시 복사본에서는 도면 6개·사례 9560건·불일치 0건, rc 0 |
