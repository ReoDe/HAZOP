# 디자인 체계 진행 관리 (SSOT)

> **역할**: 작업 단위별 상세 상태, 완료 기준, 결과, 증거와 다음 행동을 관리하는 유일한 원장.
> **투영 규칙**: [`ROADMAP.md`](ROADMAP.md)는 이 문서의 단계·순서·게이트·현재 행동을 한 장으로 요약한다.
> **갱신 규칙**: 확인 가능한 증거가 있는 변화만 기록하고, 갱신할 때마다 기준 일시와 변경 이력을 함께 바꾼다.
> **기준일**: 2026-11-06 11:25(W9. 앞 W8 기록의 11:40은 실제 시각보다 앞서 적힘)

## 1. 작업 단위 상태 장부

| ID | 상태 | 작업 단위 | 완료 기준 | 의존성 |
|---|---|---|---|---|
| `W1` | 완료 | 초기 조사와 실행 계획 구체화 | 참조 대상 또는 업무 범위를 조사하고 후속 작업 단위와 완료 기준을 등록한다. | 없음 |
| `W2` | 완료 | Windows 1366 검사 기준 정립(실제 플랫폼 측정 스크립트, offscreen 회귀 감시) | 화면 ①~⑤ 최소 폭 측정이 자동 검사로 남음 | 없음 |
| `W3` | 완료 | ④⑤ 긴 칩·라벨 축약·줄임표·툴팁, 작업 영역·125% 판정 | Windows 기준 ①~⑤ 최소 폭 ≤ 1366, 125%(논리 1536×864)에서도 작업 영역 안, 줄임표 문구는 툴팁에 보존 | `W2`, T1 W7과 순차 |
| `W4` | 완료(D6) | 토큰 단일 출처화·뷰어 색 통일(`--valve`·`--selected`) | 뷰어·앱 색 비교 검사 통과 | `W2` |
| `W5` | 완료(D7) | 명암비 조정과 대비 검사 | 지정 토큰 3:1·4.5:1 충족 검사 통과 | `W4` |
| `W6` | 완료(D8·D9) | 앱 코드 색 리터럴 0개, 뷰어 경로 대조 검사 정상화 | `hazop/app/`(tokens.py `COLORS` 제외)·`hazop/viewer/build.py`의 hex 리터럴 0개 검사 통과, `node scripts/check_viewer_paths.js` 저장소 그대로 rc 0 | `W4`, 편집 범위 확대 결정 D8(확정). check_viewer_paths.js는 총괄이 `f3b309e`에서 수정(저장소 그대로 rc 0 확인, 2026-11-06) |
| `W7` | 완료(D10·D11) | 그래프 노드 선택 표시(권장안 A: 흰 테두리 유지 + 바깥 `--ui` 고리) | 독립 뷰어·앱 내장 그래프에서 설비 노드 선택 시 고리 자리에 `--ui` 화소(offscreen 화소 판정 테스트), 명암비 쌍 `card`/`equipment` 추가 후 check_design rc 0, 경로 강조·도면 선택 회귀 없음 | `W5`·`W6`, 편집 범위 D10 |
| `W8` | 완료(D13·D14, 재작업 2회 뒤 총괄 직접 수정) | 반투명 관계선 대비(사용자 결정: 색만으로 구분되는 선만 3:1, 모양·범례로도 구분되는 보조 선은 예외. 총괄 판정: has_endpoint 예외 아님) | 선 종류별 판정 표(근거 파일:행), 관계선 모두 흰 도면 합성 3:1 이상(`check_design` 판정으로 강제. 검사가 막는 범위: 기본·종류별 규칙 밖 선택자의 불투명도 < 1, @media 안, !important, 선에 닿는 filter: opacity(), 선 규칙 CSS 중첩, HTML·JS 직접 설정. 휴리스틱 한계는 [w8 §8](evidence/w8-반투명선.md)), unittest·check_design windows·check_kg_screen·check_viewer_paths 통과, check_viewer(저장소 기본 경로)는 QA 확인 예정 | `W5`(D7), 사용자 결정 2026-11-06 |
| `W9` | 완료(D15, 검토 승인) | 독립 뷰어 색 허용 목록 비우기(D5 열린 항목, 2색 통일) | 템플릿 하드코딩 3곳을 앱 토큰 `var()`로, `VIEWER_COLOR_ALLOW` 비움·다시 채우면 테스트 실패, 바꾼 값이 바탕 위 W5 기준(글자 4.5:1·그래픽 3:1) 통과·대비 쌍 등록, check_design windows·check_kg_screen·check_viewer·check_viewer_paths·unittest 통과 | `W4`(D5)·`W5`(D7), 총괄 결정(사용자 위임 2026-11-06) |

작업 추가·분할은 [`README.md`](README.md)의 확장 규칙을 따른다. 기존 ID·완료 이력·증거는 보존하고 새 작업에는 관련 결정 ID를 연결한다.

## 2. 진행 중 작업 상세

| ID | 현재 상태 | 증거 | 다음 행동 |
|---|---|---|---|
| `W9` | 완료(D15, 검토 승인). 통과 점 `#16a34a` → `var(--ok)`(3.02 → 4.60), 경고 글자 2곳 `#b45309` → `var(--warn-ink)`(5.02 → 7.09), 허용 목록 0곳, 대비 66쌍, 새 토큰 없음 | [w9-허용목록.md](evidence/w9-허용목록.md) | Claude·Codex 검토 → QA |
| `W8` | 완료(D13·D14, 재작업 2회 뒤 총괄 직접 수정). `.pipe-line` .75 → .93, `.gedge` 기본 .55 → .92(has_endpoint, 총괄 판정으로 예외 없앰)·신호 .66·계측 .93(종류별 규칙). check_design 반투명 관계선 판정(종류는 `EDGE_COLOR`·추출 규칙에서 읽음, 우회 차단) | [w8-반투명선.md](evidence/w8-반투명선.md) | Claude·Codex 재검토 → QA(저장소 기본 경로 check_viewer 포함) |
| `W7` | 완료. 재작업 2회 뒤 Codex 하 1건 총괄 직접 수정(D11). 그래프 노드 선택 시 바깥 --ui 고리(노드 층 위·라벨 층 아래) | [w7-선택표시.md](evidence/w7-선택표시.md) | Claude·Codex 검토 → QA. windows 플랫폼 렌더는 미확인 |
| `W6` | 완료. 재작업 2회 뒤 총괄 직접 수정(D9). 앱 코드 색 리터럴 0(허용 3곳, 문맥 결합) | [w6-앱색.md](evidence/w6-앱색.md) | Claude·Codex 검토 → QA. 열린 항목(그래프 설비 노드 선택 표시) 권장안 A(바깥 고리)는 범위 결정 필요 |
| `W5` | 완료. 재작업 1회 뒤 Claude 승인·Codex 조건부 승인(백분율 불투명도·알파 제한은 총괄 직접 수정). 디자인 문서·시안·인터페이스 §4 동기화 완료 | [w5-명암비.md](evidence/w5-명암비.md) | W6 앱 코드 hex 정리, 열린 항목(그래프 설비 노드 선택 표시 — 우선순위 높음, 반투명 관계선 실제 대비) |
| `W4` | 완료. 재작업 2회 뒤 Codex 반려 → 사용자 위임(권장안)으로 총괄 직접 수정(D6) | [w4-토큰.md](evidence/w4-토큰.md) | 재작업 2회차(마지막) 반영 완료 → 재검토 → `W5`(W5 검토 항목: [w4 §5.2](evidence/w4-토큰.md)). 인터페이스 §4.1 340·351행 문구는 [w4 §5.1](evidence/w4-토큰.md) 제안으로 별도 반영 |

## 3. 완료 결과

| ID | 결과 | 증거 | 비고 |
|---|---|---|---|
| `W3` | ④⑤ 칩·라벨 줄임표, windows 100%·125% 작업 영역 판정 통과 | [w3-작업영역125.md](evidence/w3-작업영역125.md) | 재작업 1회, Claude·Codex 승인 |

## 4. 보류·재개

현재 보류한 작업은 없다. 보류 시 작업 ID, 사유, 재개 조건을 기록한다.

## 5. 열린 결정

- (W9에서 종결 — [D15](decisions.md)) D5 남은 항목: 허용 목록 2색(`#16a34a` 통과 점, `#b45309` 경고 글자)의 값 통일 여부. 총괄 결정(권고안, 사용자 위임 2026-11-06)으로 앱 토큰 `--ok`·`--warn-ink`로 통일하고 허용 목록을 비움. [w9](evidence/w9-허용목록.md)
- W5(D7) 남은 항목:
  - (W7에서 구현, 검토 대기 — [w7](evidence/w7-선택표시.md)) **우선순위 높음** — 그래프 설비 노드 선택 표시가 약함: 선택 테두리 `#2563eb`가 채움 `#1d4ed8`과 1.30:1(선택 색은 인터페이스 §4.1 UI 파랑 — 바꾸려면 결정 필요, 렌더 확인 필요). [w5 §6.1](evidence/w5-명암비.md). 권장안 A(흰 테두리 유지 + 바깥 `--ui` 고리, 템플릿 JS 수정이라 범위 결정 필요): [w6 §5](evidence/w6-앱색.md)
  - T1 후속(W6 재작업 1회차 확인): T1 소유 `hazop/app/screens/knowledge.py`·`webview.py`는 W6 검사 대상에서 뺐다. 같은 검사를 돌린 결과 색 리터럴 0곳이라 지금 후속 작업은 없다. 파일이 바뀌면 T1이 `check_design.app_color_literals`로 확인한다. [w6 §4](evidence/w6-앱색.md)
  - (W8에서 구현, 재검토 대기 — [w8](evidence/w8-반투명선.md), D13. 디자인 시안 `.ovl.line` .75 불일치는 디자인 담당 후속) 반투명 관계선 실제 대비(3:1 미달): `.gedge` 불투명도 .55 → 1.89~2.47:1, `.pipe-line` .75 → 2.40~3.61:1(흰 도면 합성). [w5 §7.1](evidence/w5-명암비.md)
  - 입력란·구분선 테두리(`line-strong` 1.50 등)의 SC 1.4.11 적용 여부. [w5 §7](evidence/w5-명암비.md)

`W3`에서 제안한 D4(판정은 windows 값, offscreen은 회귀 경고만)는 총괄 승인으로 확정했다(2026-11-05). 새 결정은 [`decisions.md`](decisions.md)에 먼저 등록하고 관련 작업 ID와 함께 연결한다.

## 6. 변경 이력

| 일시 | 변경 |
|---|---|
| 2026-11-06 11:25 | `W9` 등록·구현 완료(검토 대기): D15(총괄 결정, 권고안, 사용자 위임) — `template.html` 통과 점 `var(--ok)`·경고 글자 2곳 `var(--warn-ink)`, `:root`에 `--ok`, `VIEWER_COLOR_ALLOW` 비움, `CONTRAST_PAIRS` 66쌍(`ok`/`bg`, 경고 글자는 `warn-ink`/`card`), `test_design` 허용 목록 비어 있음·옛 3조합 실패·W4 이전 템플릿 13건 실패. `tokens.py` 무변경. [w9](evidence/w9-허용목록.md) |
| 2026-11-06 11:40 | `W8` 재작업 2회차(마지막, Claude 조건부 승인·Codex 반려): 오탐 제거(HTML 주석 속 style·script 제외, JS 문자열 내용·템플릿 리터럴 `${…}` 안 주석 제외 — 문자열은 속성 이름 그 자체이거나 `opacity:` 선언일 때만 실패), 차단 2종(선에 닿는 선택자의 `filter: opacity()`, 선 규칙 CSS 중첩), 사례별 테스트(`TranslucentStrokeTest` 11건), 한계 3건 기록(상위 요소 opacity, rgba stroke 색, 정규식 앞 return·typeof), `--colors-only` 도움말, 상태 표기·ROADMAP 기준일 정리. [w8 §8](evidence/w8-반투명선.md) |
| 2026-11-06 10:30 | `W8` 재작업 1회차(Claude·Codex 조건부 승인): 총괄 판정으로 has_endpoint 예외 삭제(`.gedge` 기본 .92, 예외 목록·관련 테스트 제거, D13 문구 정정), 검사기 우회 차단(인식 못 한 선택자·`opacity` 곱·`!important`·@media·JS/HTML 직접 설정 실패, JS 주석·문자열 밖에서 종류 읽기), 강조 규칙 불투명도 1 테스트·우회 사례별 실패 테스트(`TranslucentStrokeTest` 9건), 안티에일리어싱 한계·디자인 시안 후속 기록, ROADMAP 반영. [w8](evidence/w8-반투명선.md) |
| 2026-11-06 09:10 | `W8` 등록·구현 완료(검토 대기): 사용자 결정 D13 기록, 선 종류별 판정 표(예외 has_endpoint 그래프 관계선 1종), `template.html` CSS 불투명도(`.pipe-line` .93, `[data-kind] > .gedge` 신호 .66·계측 .93), `check_design` 반투명 관계선 판정(`stroke_rows`·`stroke_problems`, 예외 허용 목록), `test_design.TranslucentStrokeTest` 8건. [w8](evidence/w8-반투명선.md) |
| 2026-11-06 05:50 | `W7` 재작업 2회차(Claude 승인·Codex 반려, 마지막 회차): 없는 ID 선택 시 속성 패널·링크를 빈 상태로 초기화, `select(undefined)` 회귀 테스트, 노드 제거·데이터 삭제 경로 없음을 근거(파일:행)로 기록, 문구 '노드 층 위·라벨 층 아래', `wait_until` 타이머 정지·재시작, 화소 판정 한계·web_css 사용처 근거 보강. [w7 §8](evidence/w7-선택표시.md) |
| 2026-11-06 05:10 | `W7` 재작업 1회차(Claude·Codex 조건부 승인): 고리 층을 노드·라벨 사이로(라벨 가림 해소), 없는 ID·분리된 노드에서 고리 숨김, 렌더 테스트를 하위 프로세스(offscreen, 배율 1·1.25)로 격리하고 좌표 클릭·8구간 화소·라벨 화소·DOM(줌·이동·배치·필터·개수) 판정 추가, 디자인 시안 README 선택색 행 반영, `web_css()` 영향 근거 기록. [w7 §7](evidence/w7-선택표시.md) |
| 2026-11-06 04:20 | `W7` 등록·구현 완료(검토 대기): D10 편집 범위 확정(README §8 반영), 그래프 선택 바깥 고리(`template.html` `.gsel-ring`·`selMark()`), `web_css()` `.selected.gnode` 삭제, 명암비 67쌍(`card`/`equipment`), `tests/test_graph_select.py` 렌더·화소 판정 2건. [w7](evidence/w7-선택표시.md) |
| 2026-11-05 17:15 | `W1`을 진행 중으로 등록하고 작업 진행 관리 원장을 생성 |
| 2026-11-05 17:30 | `W1` 완료: [W1 조사](evidence/w1-조사.md). 권고안 D1 채택, W2~W5 등록. analysis.py·review.py 작업은 T1 W7과 순차 |
| 2026-11-05 18:30 | `W2` 완료: `scripts/check_design.py`(windows 기준 15건 통과, 최대 1282×673), `tests/test_design.py`. D2 기록. W3 착수 시 test_design의 현재 원인 단정(④ 칩·⑤ 라벨) 테스트를 함께 갱신 |
| 2026-11-05 19:00 | D3: 지원 화면 기준 확정(1366×768 100%, 1920×1080 125%), 작업 영역 높이 기준은 `W3`에서 적용 |
| 2026-11-05 22:00 | `W3` 구현 완료(검토 대기): ④⑤ 칩·라벨 줄임표·툴팁, `check_design.py` 작업 영역·125% 판정·지식그래프 실행 상태, `test_design.py` 원인 단정 테스트 갱신. D4(안) 등록 |
| 2026-11-05 22:40 | `W3` 재작업 1회차: ④ 단서 줄바꿈 라벨 분리, 툴팁은 줄였을 때만, 125% DPR 확인·⑤ 폼 판정·작업 영역 크기 측정 추가, 테스트 보강. D4 확정(총괄 승인) |
| 2026-11-05 22:50 | `W3` 완료: 재작업 1회 뒤 Claude 승인·Codex 승인. 총괄 직접 반영 — D4에 그림 테스트 글꼴 등록 예외 명시, `test_design.real_font`에 offscreen 기본 글꼴 부작용 기록. 인터페이스 §4 제안 문구는 `기획서/인터페이스.md` 담당 순서에 맞춰 후속 반영 |
| 2026-11-05 23:30 | `W4` 구현 완료(검토 대기): 독립 뷰어 `--valve`·`--selected`·선택 채움 통일, 하드코딩 색 `var()`화, `check_design.py` 색 비교·`--colors-only`, `test_design.ViewerColorTest`, `widgets.risk_chip` 토큰 참조. D5(안) 등록 |
| 2026-11-05 23:55 | `W4` 재작업 1회차(Claude·Codex 조건부 승인): 색 검사를 주석 제거·규칙 단위 파싱, `:root` 단일·재선언 거부, `var()` 공백·대체값·중첩, 템플릿 전체 색 리터럴(hex 3·4·6·8, rgb/rgba/hsl, 이름 색), (선택자·속성·값) 허용 목록으로 보강. 재현 입력 테스트 추가. D5① 문구 정정, `W6` 등록(앱 코드 hex 0개·check_viewer_paths), 인터페이스 §4.1 제안·W5 관찰 기록 |
| 2026-11-06 01:40 | `W4` 재작업 1회차 이어서(담당 교체): HTML·JS의 이름 색 위치(속성 `fill="…"`, JS 대입·객체 키·`setAttribute`) 검사 추가, 재현 입력 5종(`rgb(1,2,3)`·이름 색 4위치)·W4 이전 템플릿(`2178ddf`) 10건 실패·HTML·JS 정상 문법 통과 테스트 추가. D5 확정(총괄 승인, 권고안), `W6`의 check_viewer_paths 수정 완료 반영 |
| 2026-11-06 02:00 | `W4` 재작업 2회차(Codex 반려·Claude 승인): 선택 채움 재선언·한 규칙 안 속성 중복 거부(값은 마지막 선언), `--변수` 대소문자 보존·`VAR()` 함수명 대소문자 무시, 색 검사 결과를 결과 JSON rc·verdict·`color_problems`에 합산(`write_result`), HTML·JS 실패 줄 번호를 원본 행으로, 색 속성에 `box-shadow`·`text-shadow`·`stop-color`·`flood-color`·JS camelCase 추가, "D5안"→"D5". `ViewerColorTest` 15건 |
| 2026-11-06 02:20 | `W4` 완료(D6): 최종 재검토 Claude 승인·Codex 반려(선택 채움 우회 2건). 총괄 직접 수정(클래스 집합 판정, 기준 규칙 fill 중복 금지), test_design 25 OK, check_design --colors-only rc 0 |
| 2026-11-06 02:30 | `W5` 구현 완료(검토 대기): `check_design.py` 명암비 검사(`CONTRAST_PAIRS` 62쌍, WCAG 2.1 4.5:1·3:1, 결과 JSON·rc 합산), `tokens.py`·`template.html` `:root` 5개(뷰어는 4개) 명도 조정, `test_design.ContrastTest` 4건, D7 기록. unittest 629 OK, check_design windows rc 0 |
| 2026-11-06 03:00 | `W5` 재작업 1회차(Claude·Codex 조건부 승인): 쌍 5개 추가(67쌍)·근거 파일:행, 반투명 글자색 rgba 실패·채움·그림자 허용, 반투명 합성 대비 보고(rc 미반영), 진단 소수 넷째 자리, test_design 필수 쌍·기준 고정·경계값·미달 쌍 집합·반투명 테스트, evidence `--bg` 근거 정정·여유 유지 근거·미분류/보조 글자 1.49 한계, 열린 항목 2건 등록, D7 문구 갱신 |
| 2026-11-06 | `기획서/인터페이스.md` §4 반영(W3·W4·W5 후속): §4.1 정본 `tokens.py`(D5)·검사 강제·명암비 D7 명시, 값 칸 삭제, 선택 문구 현재형. §4.2에 줄임표·툴팁·줄바꿈 단서, 지원 화면·작업 영역(D3·D4) 추가 |
| 2026-11-06 05:30 | `W6` 재작업 2회차(Claude 조건부 승인·Codex 반려, 마지막 회차): hex 판정을 기본 색 + 예외(href·src·url, 객체 이름, 선택자 문맥)로, COLORS 제외를 AST 위치(열 포함)로, 허용 목록을 문맥(최상위 문장·선택자)에 묶음, CSS 주석·`url(…)` 오탐 제거, 보고 리터럴 따옴표 정리, D8에 66쌍 기록, 검사 한계 기록. [w6 §4](evidence/w6-앱색.md) |
| 2026-11-06 04:30 | `W6` 재작업 1회차(Claude·Codex 조건부 승인): tokens.py `COLORS` 밖 리터럴 정리(`on-fill`·`ok-bg`·`CARD_SHADOW`), 명암비 쌍 토큰 이름화(66쌍), 검사를 tokenize·ast 기반으로(주석 제외·색 문맥·선언 값 전체·여러 줄·원본 행), T1 파일 제외, D8 문구 정정(`render.py:146`), 권장안 A 보완. [w6](evidence/w6-앱색.md) |
| 2026-11-06 03:30 | `W6` 구현 완료(검토 대기): D8 편집 범위 확장 등록(README §8 반영), 앱 코드 색 리터럴 41곳 토큰 참조화(`tokens.CARD_SHADOW` 추가), `check_design` 앱 코드 색 리터럴 검사, `test_design.AppColorTest` 6건. [w6-앱색.md](evidence/w6-앱색.md) |
| 2026-11-06 02:55 | `W5` 완료(D7): 재검토 Claude 승인·Codex 조건부 승인. 총괄 직접 수정(백분율 불투명도 해석·알파 [0,1] 제한, 테스트 추가), 문서 표기 정리. test_design 33 OK. 디자인 문서·시안(designer)·인터페이스 §4(planner) 동기화 |
| 2026-11-06 03:45 | `W6` 완료(D9): 최종 재검토 Claude 조건부·Codex 반려. 총괄 직접 수정(f-string 자리표시자 앞 hex, url(…) 마스킹), test_design 48 OK, --colors-only rc 0 |
| 2026-11-06 05:05 | `W7` 완료(D11): 최종 재검토 Codex 조건부 승인(하 1건). 총괄 직접 수정(프로토타입 없는 사전), test_graph_select OK·수정 전 템플릿에서 실패 확인 |
