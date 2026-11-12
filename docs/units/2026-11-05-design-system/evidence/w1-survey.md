# W1 조사 — ④⑤ 최소 폭, 뷰어·앱 색 차이, 대비, 토큰 위치

> 조사 일시: 2026-11-05 17:35 · 대상: `chore/track-workspaces` HEAD `d540288`, 비교 `c617ae6`(W6 이전) · 조사: hazop-developer(코드 수정 없음)
>
> 측정 스크립트와 원시 출력은 세션 임시 폴더(scratchpad)에 두었고 저장소에 넣지 않았다. 작업·저장 루트는 임시 폴더(`HAZOP_WORK_ROOT`·`HAZOP_STORE_ROOT`)를 썼다. 실행은 `tests/run_fixture.py`의 고정 응답 분석 실행을 썼다.

## 0. 요약

- **④⑤ 최소 폭 원인은 줄바꿈 없는 긴 문구 라벨 두 줄**이다. ④ 도구줄의 결과 검증 칩과 ⑤ 도구줄의 실행 라벨·진행 칩이 원인이다. 분할기(패널) 폭은 원인이 아니다.
- **offscreen 수치(1425/1585)는 글꼴 대체로 부풀려진 값이다.** offscreen에서는 맑은 고딕이 잡히지 않아(해석된 글꼴 이름이 빈 문자열) 같은 라틴 문구가 572px로 측정된다. windows 플랫폼에서는 307px이다. windows 플랫폼(100%, 96 DPI)에서는 ④ 1282, ⑤ 1071로 1366 안에 들어간다.
- **W6는 ④⑤ 최소 폭을 바꾸지 않았다.** `c617ae6`과 HEAD의 ④⑤ 값이 두 플랫폼 모두 같다. W6는 헤더를 오히려 줄였다(windows 1301 → 1062).
- 대비: 데이터 색 중 계장 `#0ea5e9`(2.77:1), 미분류 `#9ca3af`(2.54:1)가 흰 캔버스에서 3:1에 미달한다. 계측 연결 `#d97706`은 앱 바탕(`#f4f5f7`)에서 2.92:1로 미달한다. 글자 쌍 중에서는 `--muted` on `--bg`(4.43:1)와 위험도 제안 칩 글자 `#d97706` on 흰색(3.19:1)이 4.5:1에 미달한다.
- 독립 뷰어(`template.html`)와 앱의 색 차이: 의미가 다른 차이는 `--valve`와 `--selected` 두 개다. 나머지는 같은 값을 하드코딩한 것이거나 토큰에 없는 색(`#b45309`)이다.

## 1. ④⑤ 화면 최소 폭 실측

### 1.1 방법

- `MainWindow`를 `WA_DontShowOnScreen`으로 띄우고 `resize(1366, 768)` 뒤 `minimumSizeHint().width()`와 실제 창 폭을 기록했다. 화면 ①~⑤의 `minimumSizeHint`, 헤더·상태줄·메뉴의 `minimumSizeHint`도 함께 기록했다. 위젯 트리는 최소 폭 300px 이상인 가지만 따라가며 가로 레이아웃 항목별 기여를 출력했다.
- 상태: A 데이터 없음(빈 작업 루트) → B 샘플 실행 열림(각 화면 순회, ⑤에서 d09·d12 선택) → C 검토 기록 적재(d12를 수용으로 저장한 뒤 새 창에서 실행을 다시 열고 ⑤ d12 선택).
- 플랫폼: `offscreen`(테스트와 같은 조건)과 `windows`(실제 Windows 글꼴). 화면 정보: offscreen은 논리 800×800, DPR 1.0, windows는 논리 1920×1080, DPR 1.0, 96 DPI.
- 비교: `git archive c617ae6`를 임시 폴더에 풀어 같은 스크립트로 측정했다(작업 트리·`.git` 변경 없음).

### 1.2 측정값 (창 최소 폭 / `resize(1366)` 뒤 실제 폭, 단위 px)

| 상태 | offscreen HEAD | offscreen c617ae6 | windows HEAD | windows c617ae6 |
|---|---|---|---|---|
| A 데이터 없음(모든 화면) | 1201 / 1366 | 1054 / 1366 | 1053 / 1366 | 907 / 1366 |
| B 실행 열림, ⑤ 방문 전 | **1425 / 1425** | 1834 / 1834 | 1282 / 1366 | 1301 / 1366 |
| B 실행 열림, ⑤ 방문 후(d09·d12 선택 포함) | **1585 / 1585** | 1834 / 1834 | 1282 / 1366 | 1301 / 1366 |
| C 기록 적재, ④·⑤ d12 | 1425·1585 | 1834 | 1282 | 1301 |

화면별 `minimumSizeHint`(상태 B, ⑤ 방문 후):

| 플랫폼·커밋 | ① | ② | ④ | ⑤ | ③ | 헤더 | 상태줄 |
|---|---|---|---|---|---|---|---|
| offscreen HEAD | 381 | 764 | **1425** | **1585** | 404 | 1214 | 640 |
| offscreen c617ae6 | 381 | 764 | 1425 | 1585 | — | **1834** | 640 |
| windows HEAD | 341 | 662 | **1282** | 1071 | 351 | 1062 | 497 |
| windows c617ae6 | 341 | 662 | 1282 | 1071 | — | 1301 | 497 |

- ⑤ 폼 내용(스크롤 영역 안) 최소 폭과 보이는 폭: offscreen 615 / 712, windows 520 / 606. 폼은 두 플랫폼 모두 스크롤 영역에 들어간다.
- `QStackedWidget`의 최소 폭은 모든 화면 중 최대값이다. 그래서 ④ 실행을 연 뒤에는 ①②③에 있어도 창 최소 폭이 ④ 값(1425/1282)이 된다. ⑤는 처음 방문할 때 `set_ctx`가 문구를 채우므로 방문 뒤부터 1585가 된다.

### 1.3 원인 (위젯 트리)

| 화면 | 위치 | 기여(offscreen / windows) | 원인 |
|---|---|---|---|
| ④ | 도구줄 `bar`: `hazop/app/screens/analysis.py:162-183` | 행 합계 1401 / 1258 (+ 여백 24) | `chip_valid`(`Chip`, `QLabel` 줄바꿈 없음)의 문구 "결과 검증 통과 — 형식·참조 검증 통과(보류 항목이 없다는 뜻이 아님)"가 **512 / 401px**이다(`analysis.py:418`). 나머지: 구간 콤보 `setMinimumWidth(220)`(`:165`), 실행 콤보 `setMinimumWidth(300)`(`:170`), 버튼 160+121 / 144+105, 라벨 26×2, 간격 6×6 |
| ⑤ | 도구줄 `bar`: `hazop/app/screens/review.py:687-705` | 행 합계 1561 / 1047 (+ 여백 24) | `run_label`이 `setWordWrap(False)`(`review.py:689`)이고 "실행 analysis-… (읽기 전용)"(`:807`)이 **572 / 307px**이다. 진행 칩 "미검토 25 · 검토 중 0 · … · 판정 제외 19"(`:840`)가 **512 / 315px**이다. 고정 폭: 검토자 입력 `setFixedWidth(140)`(`:697`) |
| 공통 | 상태줄 결과 검증 칩: `hazop/app/main_window.py:188-190` | 488 / 377 | "결과 검증 통과 (형식·참조 검증 통과 — 보류 없음을 뜻하지 않음)". 상태줄 전체는 640 / 497이라 1366 미만이다. 지금은 원인이 아니지만 같은 유형이다 |
| 공통 | 헤더: `main_window.py:88-121` | 1214 / 1062 | 단계 탭 5개와 앱 이름이 고정 문구다. `WhereLabel`은 `setMinimumWidth(120)`(`:104`)으로 최소 폭을 120에 묶었다. 그래서 위치 문구 길이(871 / 약 480)는 기여하지 않는다 |

- 분할기는 원인이 아니다. ④ 분할기 최소 416 / ⑤ 592(offscreen)로, 도구줄보다 훨씬 작다. `setSizes([460, 560, 430])`(`analysis.py:276`)·`([330, 380, 660])`(`review.py:774`)는 초기 비율이며 최소 폭을 늘리지 않는다.
- 칩 문구만 줄였을 때의 계산: "결과 검증 통과" 칩은 128 / 106px이다. ④ 화면 최소 폭은 약 1041 / 987로 줄어든다(1425−512+128, 1282−401+106). [추론] 실제 재배치 뒤 재측정이 필요하다.
- offscreen과 windows의 차이: offscreen에서 `QFontInfo(QFont("Malgun Gothic")).family()`가 빈 문자열이다. 같은 문구 폭이 572 vs 307px이다(한글 10자는 130 vs 130으로 같고, 라틴·숫자 폭이 크게 다르다). 메모리 `backlog.md:49`의 1425/1585는 offscreen 값이다.

### 1.4 테스트 관련 사실

- `tests/test_app.py:559-576` `test_form_fits_1366`은 ⑤ 폼 내용 폭과 스크롤 보이는 폭만 비교한다. offscreen에서는 창 최소 폭 때문에 `resize(1366, 768)` 뒤에도 실제 창 폭이 1585가 된다(1.2 표). 즉 이 테스트는 1585 폭에서 통과하고 있으며, 창 자체가 1366에 들어가는지는 검사하지 않는다.
- 실행 결과: `python -m unittest tests.test_app.ReviewLayoutTest tests.test_app.StaticTest` → 4개 통과(OK).

### 1.5 남는 위험

- [추론] Windows 배율 125%에서 물리 1366 폭 화면의 논리 폭은 약 1093px이다. 이때 windows 기준 ④(1282)·헤더(1062)는 넘치거나 빠듯하다. 배율별 실측은 하지 않았다([미확인]).
- 실행 ID·구간 이름이 더 긴 실제 자료에서는 ⑤ `run_label`이 더 넓어진다. 샘플 실행 ID 길이로만 측정했다.
- 이전 검토가 있는 상태(다른 실행의 검토 기록, `PriorImport` 라벨)는 만들지 않았다([미확인]). `PriorImport.label`(`review.py:118`)은 `plain_label` 기본값(줄바꿈 있음)이라 폭을 늘리지 않을 것으로 본다 [추론].

## 2. 독립 실행 뷰어와 앱 토큰의 색 차이

기준: 앱 토큰 `hazop/app/tokens.py:11-44`(`COLORS`), `web_css()` `:78-106`, 인터페이스 §4.1(`docs/specs/interface.md:334-353`). 앱 안에서는 `web_css()`가 `:root`를 덮어써서 아래 차이가 보이지 않는다. 차이는 독립 실행(브라우저로 연 `template.html`)에서만 나타난다.

| 이름 | 독립 뷰어 값(위치) | 앱 값(위치) | 용도 | 판정 |
|---|---|---|---|---|
| `--valve` | `#2563eb`(`template.html:9`) | `#0f766e`(`tokens.py:17`) | 밸브 노드 | **의미 차이**. §4.1은 밸브를 UI 파랑과 분리하도록 정했다 |
| `--selected` | `#dc2626` 빨강(`template.html:11`), `.selected` 채움 `rgba(220,38,38,.12)`(`:74`) | `var(--ui)` `#2563eb`, `rgba(37,99,235,.12)`(`tokens.py:82,84`) | 클릭 선택 | **의미 차이**. §4.1은 "`template.html` 수정이 필요"라고 적었다. 앱 `COLORS`에는 `selected` 키가 없고 `web_css`에서만 만든다 |
| 경로 강조 `.onpath` | `#ea580c`, `rgba(234,88,12,.15)` 하드코딩(`template.html:116-118`) | `--hl-path` `#ea580c`(`tokens.py:23`) | 경로 질의 결과 | 값 같음, 토큰 미사용 |
| 통과 점 `.chip.passed::before` | `#16a34a`(`template.html:23`) | `--ok` `#15803d`(`tokens.py:25`) | 구조 검증 통과 표시 | 값 다름(용도 같음) |
| 정렬 경고 칩 `.chip.alignwarn` | `#fef3c7`/`#92400e` 하드코딩(`template.html:79`) | `--warn-bg`/`--warn-ink` | SVG 정렬 경고 | 값 같음, 토큰 미사용 |
| 경고 글자 `aside .warn`, `#pathq .res .bad` | `#b45309`(`template.html:61,114`) | 해당 토큰 없음(`--warn-ink` `#92400e`) | 속성 패널·경로 질의 경고 | 토큰에 없는 색 |
| 그래프 라벨 `.glabel` | `#374151`(`template.html:104`) | `--ink-2` `#374151` | 그래프 노드 라벨 | 값 같음, 토큰 미사용 |
| 캔버스·노드 테두리 | `#fff`(`template.html:29,100`) | `--card` `#ffffff` | 도면 바탕, 노드 흰 테두리 | 값 같음, 토큰 미사용 |
| 글꼴 | `"Pretendard", "Malgun Gothic", …`(`template.html:14`) | `"Malgun Gothic"`(`tokens.py:9,83`) | 본문 | 차이. §4.2와 T2 글꼴 결정(인터페이스 §9) 대기 |
| 토큰 없음 | `--ui-weak`, `--ink-2`, `--line-strong`, `--hl-*`, 상태·위험도·출처 토큰 | `tokens.py`에만 있음 | — | 독립 뷰어는 쓰지 않음 |
| 알 수 없는 관계 종류 | `EDGE_COLOR[e.kind]` 없으면 `stroke:undefined`(`template.html:609-610,652`) | `graph_only_html`은 `unclassified`(`data.py:147-148,158`) | 그래프 관계 선 | 대체 색 다름 |

`hazop/app/data.py:133-184` `graph_only_html`: 색을 `tokens.COLORS`에서 읽는다. 노드 종류·관계·`bg`·`ink`·`ink-2`·`line`·`warn-*`가 여기에 해당한다. 하드코딩은 헤더 바탕·그래프 바탕·노드 테두리 `#fff` 3곳(`:165,175,177`)뿐이며 값은 `--card`와 같다. 독립 뷰어와는 `valve`(앱 값 사용)와 글꼴만 다르다.

`hazop/viewer/build.py:82-86`(독립 뷰어 목록 페이지)도 `#f4f5f7`·`#111827`·`#6b7280`·`#e3e5e9`·`#2563eb`를 하드코딩했다. 값은 토큰과 같고, 글꼴은 Pretendard가 먼저다.

## 3. 색 대비 (WCAG 2.x 상대 휘도 공식)

기준(`[일반지식]`, WCAG 2.1 SC 1.4.3·1.4.11): 일반 글자 4.5:1, 큰 글자(18pt 이상 또는 굵은 14pt 이상) 3:1, 그래픽·UI 구성 요소 3:1. 비활성 요소는 예외다. 앱 글자는 11~15px(`FONT_SIZE`, `tokens.py:58`)이라 모두 "일반 글자"로 본다.

### 3.1 데이터 색(그래픽, 3:1) — 흰 캔버스 / `--bg` `#f4f5f7` / `--kg-canvas` `#fcfcfd`

| 토큰 | 값 | 흰색 | bg | kg-canvas | 비고 |
|---|---|---|---|---|---|
| `--instrument` | `#0ea5e9` | **2.77** | **2.54** | **2.70** | 계장 노드. 미달 |
| `--unclassified` | `#9ca3af` | **2.54** | **2.33** | **2.48** | 미분류 노드·알 수 없는 관계. 미달 |
| `--measurement_connection` | `#d97706` | 3.19 | **2.92** | 3.11 | 독립 뷰어 `#viewport` 바탕이 `--bg`(`template.html:27`) |
| `--physical_connection` | `#16a34a` | 3.30 | 3.02 | 3.21 | 겨우 통과 |
| `--hl-path` | `#ea580c` | 3.56 | 3.26 | 3.47 | 통과 |
| `--piping_element` | `#6366f1` | 4.47 | 4.09 | 4.36 | 통과 |
| 그 외 `--equipment` 6.70, `--valve` 5.47, `--signal_connection` 5.70, `--unresolved`·`--hl-cause` 4.83, `--hl-safeguard` 4.71, `--ui` 5.17 | | | | | 통과 |

T1 소유 토큰(값 변경 대상 아님, 참고): `--kg-rel-docpos` 1.48, `--kg-flag` 2.15, `--a1-mixed`·`--comp-4` 3.06(bg 2.81), `--a1-unknown`·`--comp-other` 2.54, `--a1-off` 1.47, `--comp-2` 2.25, `--comp-5` 2.31이 흰색 또는 bg 기준으로 3:1에 미달한다. 이 중 `docpos`·`a1-off`는 의도적으로 옅게 한 색이다(`docs/design/kg-screen.md:96,115`). 지식그래프화면.md §1.2의 표기값(계장 약 2.8:1 등)은 흰 바탕 계산값과 일치한다.

### 3.2 글자 쌍(4.5:1)

| 글자 / 바탕 | 값 | 비율 | 사용 위치 |
|---|---|---|---|
| `--muted` / `--bg` | `#6b7280`/`#f4f5f7` | **4.43** | 표 머리(`QHeaderView::section`, `tokens.py:150`, 12px 굵게), 화면 바탕의 `QLabel#muted`(④ 집계 `analysis.py:184`, ⑤ 실행 라벨 `review.py:688`), 독립 뷰어 `.chip`(`template.html:22`) |
| `--muted` / `--ui-weak` | `#6b7280`/`#eff6ff` | **4.44** | 선택된 표 행의 회색 글자(제외 후보 `analysis.py:54` + 선택색 `tokens.py:149`) [추론] |
| `--risk-cond-line` / 흰색 | `#d97706`/`#ffffff` | **3.19** | 위험도 **제안** 칩 3·4 글자(속 빈 칩, `widgets.py:70`, 11px) |
| `--ok` / `#dcfce7` | `#15803d`/`#dcfce7` | 4.57 | 통과 칩(`tokens.py:129`). 겨우 통과. `#dcfce7`은 토큰에 없음 |
| 흰색 / `--hl-safeguard` | `#ffffff`/`#c026d3` | 4.71 | 보호수단 배지(`tokens.py:98`) |
| `--muted` / `--card` | `#6b7280`/`#ffffff` | 4.83 | 단계 탭·섹션·상태줄. 통과 |
| 그 외 `ink`·`ink-2`·`ui`·`err-ink`·`warn-ink`·`ai-ink`·위험도 확정 칩 3단·`#b45309` | | 5.0 이상 | 통과 |

### 3.3 경계선(UI 구성 요소, 3:1)

`--line` on 흰색 1.26, `--line-strong` on 흰색 1.50(입력란 테두리 `tokens.py:144`), `--err-line` on `--err-bg` 1.74, `--warn-line` on `--warn-bg` 1.93이다. 모두 3:1 미만이다. [일반지식] SC 1.4.11은 구성 요소를 "식별하는 데 필요한" 시각 정보에만 적용한다. 입력란은 바탕색 차이와 자리 표시 글자로 식별되므로 위반 여부는 해석이 갈린다. 결정 대상으로 남긴다.

## 4. 토큰 정의가 흩어진 위치

| 위치 | 내용 | 소유 |
|---|---|---|
| `hazop/app/tokens.py:9-56` | `FONT_FAMILY`, `COLORS`(기존 + `--kg-*`·`--a1-*`·`--comp-*`), `HL_DIM`, `KG_STYLE`, `KG_RIGHT_*`, `kg_css_vars()` | 앱 공통(T6) / `kg-*`·`kg_css_vars`는 T1 |
| `hazop/app/tokens.py:58` | `FONT_SIZE` | T6 |
| `hazop/app/tokens.py:113-159` `qss()` | 하드코딩: `#ffffff`(`:121,126,141,144,147`), `#dcfce7`(`:129`). 모서리 14·12·10·8·16px, 여백 등 간격 값 전부 | T6 |
| `hazop/app/tokens.py:81-106` `web_css()` | `rgba(37,99,235,.12)`(`:84`), `rgba(220,38,38,.30)`(`:94`), `#fff`(`:98-99`), 그림자 `rgba(0,0,0,.06)`(`:103`), 파선 `9 6`(`:93`) | T6 |
| `hazop/viewer/template.html:7-12` 및 본문 CSS | 별도 `:root`(값 2개 다름) + 하드코딩(2절 표) | T6(색·CSS만), T1 W6이 탭 이름 변경 |
| `hazop/viewer/build.py:34,82-86` | 목록 페이지 CSS 하드코딩 | 편집 허용 범위 밖 |
| `hazop/app/data.py:165,175,177` | `#fff` 3곳 | 편집 허용 범위 밖 |
| `hazop/app/widgets.py:54,70,82` | `#ffffff`, `"#9ca3af"` 문자열 비교(`:70`, 토큰 값이 바뀌면 조용히 어긋남) | T6 |
| `hazop/app/render.py:15,20,33,102` | `#92400e`, `#6b7280` 인라인 | 편집 허용 범위 밖 |
| `hazop/app/screens/analysis.py:508,516` | `#6b7280` 인라인 | T6(배치·폭만 허용 → 색은 범위 밖) |
| `hazop/app/screens/register.py:210-344` | `#b91c1c`·`#92400e`·`#6b7280`·`#15803d` 인라인 13줄 | 편집 허용 범위 밖 |
| `hazop/app/screens/review.py:377,760` | `#b91c1c`, `#fca5a5`(`setStyleSheet`) | T6(배치·폭만 허용 → 색은 범위 밖) |
| `hazop/kg/screen_template.html:128` | 대체값 `#9ca3af` | T1 |
| `docs/specs/interface.md:334-363` §4.1·§4.2 | 토큰 표(일부만: `ink-2`·`line-strong`·`ui-weak`·상태·출처 토큰 없음) | T6(§4만) |
| `docs/design/mockups/README.md:50-67` §3 | 토큰 제안 표(간격 `--sp-*`, 모서리 `--r-*`, 그림자, `--mono` 포함) | T6 |
| `docs/design/mockups/interface-mockup.html:12-37` | 시안 `:root`(앱 `COLORS`와 값 일치, 간격·모서리 토큰 추가) | T6 |
| `docs/design/kg-screen.md:19-40,85-122,198-209`, `docs/design/mockups/kg-graph-mockup.html` | ③ 토큰 | T1 |
| `tests/test_app.py:117-130` | 토큰 값 일부 고정(`valve`, `hl-safeguard`, 글꼴) | 편집 허용 범위 밖(T6 검사는 `tests/test_design.py`) |

### 4.1 단일 출처화 제안 [추론]

1. **정본은 `tokens.py` 하나로 둔다.** 색·글꼴·글자 크기 외에 간격·모서리·그림자(시안 README §3의 `--sp-*`·`--r-*`·`--shadow`)도 `tokens.py`에 넣는다. `qss()`·`web_css()`는 이 값만 읽게 한다.
2. **독립 뷰어**: `template.html`의 `:root`를 `tokens.py`와 같은 값으로 맞춘다(`--valve`, `--selected` → `--ui`). 하드코딩 색은 `var(--…)`로 바꾼다. 템플릿은 빌드 없이 브라우저로 열리므로 생성 주입보다 **검사로 동기화**하는 편이 단순하다. `scripts/check_design.py`가 템플릿 `:root`의 각 변수와 `tokens.COLORS`의 같은 이름 값을 비교하는 방식이다.
3. **인라인 색**(`render.py`·`register.py`·`analysis.py`·`review.py`·`data.py`·`build.py`)은 `tokens.c(...)`로 바꾼다. 다만 대부분이 현재 T6 편집 허용 범위 밖이다. 범위 확장 결정이 먼저 필요하다.
4. **문서**: 인터페이스 §4.1은 표를 `tokens.py`와 1:1로 맞추거나, "값의 정본은 `tokens.py`"라고 명시하고 의미·용도만 남긴다. 시안 README §3은 이력(BASELINE)으로 표시한다.
5. `scripts/check_design.py` 검사 항목 예: (a) 템플릿 `:root` = `tokens.COLORS`, (b) 앱 코드의 `#rrggbb` 리터럴 0개(`tokens.py` 제외, 허용 목록 별도), (c) 3절 대비 기준표.

## 5. W2 이후 작업 단위 제안 (완료 기준 포함)

| 제안 ID | 작업 | 완료 기준 | 대상 파일 | 순서 제약 |
|---|---|---|---|---|
| W2 | ④⑤ 1366 폭 해소 | windows·offscreen 두 플랫폼에서 상태 A·B·C의 창 최소 폭 ≤ 1366, 그리고 `resize(1366,768)` 뒤 `win.width() == 1366`. 긴 문구는 칩을 짧게 하고 상세는 툴팁·줄바꿈 라벨로 옮긴다(의미 문구 유지). `tests/test_design.py`에 창 폭 검사 추가 | `analysis.py`(도구줄), `review.py`(도구줄), 필요하면 `main_window.py` 상태줄 칩 | **T1 W7과 순차**(`analysis.py`·`review.py`). `main_window.py`는 T6 편집 허용 범위 밖이라 범위 결정 필요 |
| W3 | offscreen 측정 기준 정리 | 테스트에서 글꼴을 고정하는 방법(offscreen에 글꼴 등록 등)을 정하거나, offscreen 값과 windows 값 중 판정 기준을 결정(decisions.md) | `tests/test_design.py` | W2와 함께 결정 |
| W4 | 토큰 단일 출처 + 검사 | `check_design.py`가 4.1의 (a)(b)를 검사하고 rc=0. `qss()`·`web_css()`·`widgets.py`의 하드코딩 색 0개 | `tokens.py`, `widgets.py`, `scripts/check_design.py` | `tokens.py`는 T1 W7과 순차, `kg-*` 값 불변 |
| W5 | 독립 뷰어 색 통일 | `template.html` `:root` = `tokens.COLORS`(겹치는 이름), `--selected` = `--ui`, 하드코딩 색은 `var()`. `check_viewer.py`·`check_viewer_paths.js`·`test_template_unchanged_script_count` 통과 | `hazop/viewer/template.html`(색·CSS만) | T1 W7과 순차 |
| W6 | 대비 개선 | 3.1·3.2 미달 항목별로 값을 바꿀지, 모양 단서로 대체할지 결정을 등록한다. 바꾼 값은 `check_design.py` 대비 검사(3:1/4.5:1)를 통과한다. 후보: `--instrument`, `--unclassified`, `--measurement_connection`(bg), `--muted` on `--bg`, 위험도 제안 칩 글자 | `tokens.py`, `docs/design/` | 값 변경은 ②④⑤ 화면과 ③(공유 토큰)에 영향. T1과 협의 |
| W7 | 인터페이스 §4 정리 | §4.1 표가 `tokens.py`와 일치하거나 정본 위치를 명시. T2 글꼴 결정 반영 | `docs/specs/interface.md` §4 | T1·T2와 같은 시점 편집 금지 |

**T1 W7과 순서를 맞춰야 할 파일**: `hazop/app/screens/analysis.py`, `hazop/app/screens/review.py`(W2), `hazop/app/tokens.py`(W4·W6), `hazop/viewer/template.html`(W5), `docs/specs/interface.md`(W7, T1·T2와도 순차), `docs/design/`(W6).

## 6. 미확인·한계

- Windows 배율 125%·150%에서는 측정하지 않았다.
- 이전 검토 대응이 있는 ⑤ 상태(다른 실행의 검토 기록)는 만들지 않았다.
- 대비는 불투명 색만 계산했다. 반투명 채움(`rgba(…,.12)` 등)과 `--hl-dim` 흐림 상태의 실제 대비는 계산하지 않았다.
- `tokens.py`의 색 대비 기준(WCAG)을 이 프로젝트에 적용할지는 결정된 바 없다. 이 문서는 측정값만 제시한다.
