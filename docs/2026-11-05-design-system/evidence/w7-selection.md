# W7 그래프 노드 선택 표시(권장안 A) — 구현·렌더 확인

- 일시: 2026-11-06. 대상: HEAD `54a0ef4` + W7 작업 트리(커밋 전). 결정: [D10](../decisions.md).
- 근거: [w5 §6.1](w5-contrast.md)(선택 테두리 `#2563eb` / 설비 `#1d4ed8` = 1.30:1), [w6 §5](w6-app-colors.md)(권장안 A와 보완 1~3).

## 1. 변경

| 파일 | 변경 |
|---|---|
| `hazop/viewer/template.html` | `.selected.gnode`(테두리 `--selected` 3px) 삭제 → `.gsel-ring`(채움 없음, `--selected` 2.5px, `pointer-events: none`) 추가. JS: `selMark()` 하나 — 그래프 노드가 선택되면 노드·라벨 층 위의 새 층에 원 하나를 반지름 `NODE_R + 4`(배관 구간 마름모는 꼭짓점 거리 `3.5·√2 + 4`)로 그린다. `select()`·배치 전환(`placeAll`)·범례 필터(`applyFilter`)에서 갱신하고, 노드가 아니거나(관계·미해결 커넥터) 숨긴 노드면 감춘다 |
| `hazop/app/tokens.py` | `web_css()`의 `.selected.gnode { stroke: var(--ui) !important }` 선택자 삭제(앱 내장에서도 노드 흰 테두리 유지). 새 토큰 없음 — 고리 색은 `web_css()`가 이미 `--selected: ui`로 둔다 |
| `scripts/check_design.py` | 명암비 쌍 `card`/`equipment`(그래픽 3:1, 흰 띠/설비 채움) 추가. 66 → 67쌍 |
| `tests/test_design.py` | `REQUIRED_GRAPHIC`에 위 쌍 추가 |
| `tests/test_graph_select.py`(새 파일) | 렌더·화소 판정. 재작업 1회차에 별도 프로세스 실행으로 바꿈(§7) |

- `hazop/app/webview.py`는 바꾸지 않았다. 보호수단 고리 `ring()`은 `#overlay` 안의 `.sym`(도면 기호)에만 그린다(`webview.py:271`). 그래서 그래프 탭에는 `.hz-ring`이 생기지 않고, 그래프 선택 고리와 겹치지 않는다. 도면 탭의 선택 표시는 기존 `.selected.sym`(테두리 3px)를 그대로 쓴다. 따라서 w6 §5 보완 1·2(겹침·간격 조정)는 실제로 생기지 않는다(코드 확인).
- 선택 고리 층은 처음에 맨 위였으나 라벨 첫 글자를 가려, 재작업 1회차에 노드 층과 라벨 층 사이로 옮겼다(§7). 노드 강조 테두리보다는 여전히 위다.

## 2. 대비(WCAG 2.1, `check_design.contrast_ratio`)

| 쌍 | 값 | 기준 | 검사 |
|---|---|---|---|
| 고리 `ui` / 흰 그래프 바탕 `card` | 5.17:1 | 3:1 | 기존 `ui`/`card`(4.5:1 쌍) |
| 고리 `ui` / 화면 바탕 `bg` | 4.74:1 | 3:1 | 기존 `ui`/`bg` |
| 흰 띠 `card` / 설비 채움 `equipment` | 6.70:1 | 3:1 | **새 쌍** `card`/`equipment` |
| (참고) 고리 `ui` / 설비 채움 | 1.30:1 | — | 흰 띠(노드 흰 테두리 바깥 0.75 + 바탕 2px)가 떼어 놓아 맞닿지 않음 |

## 3. 렌더 확인(offscreen, 1200×800, `QT_SCALE_FACTOR` 1·1.25)

SNP-M-102 설비 노드 RC-PZ01(`local-node-001`)을 휠 8회(약 3배, 151%)로 확대한 뒤 선택 전후 화면을 잡았다. 판정은 노드 중심에서 반지름 `(7+4)±2` CSS px 고리 안 화소 중 `#2563eb`와 채널별 12 이내인 화소 수다.

| 상태 | 100% | 125% |
|---|---|---|
| 독립 뷰어 선택 전 / 후 | 0 / 308 (전체 629) | 0 / 503 (989) |
| 독립 뷰어 선택 + 경로 강조(`onpath`, RC-PZ01→RC-PSV101) | 307 | 502 |
| 앱 내장 선택 전 / 후 | 0 / 308 | 0 / 503 |
| 앱 내장 선택 + 흐림(`hz-dim`) + 원인(`hz-cause`) | 308 | 502 |
| 앱 내장 선택 + 흐림 + 보호수단(`hz-sg`) | 308 | 502 |
| 앱 내장 선택 + 흐림 + 경로(`hz-path`) | 309 | 506 |

- 같은 판정을 HEAD 템플릿에 돌리면 선택 후에도 0 / 629로 실패한다(고리가 없고, 옛 3px 테두리는 반지름 8.5까지라 판정 고리 밖).
- 눈으로 본 결과: 설비 노드 바깥에 흰 띠와 파란 고리가 분리되어 보인다. 원인 4px·경로 3.5px·보호수단 2.5px 테두리 위에서도 고리가 따로 보인다(원인 테두리 바깥 끝 r+2와 고리 안쪽 끝 r+2.75 사이 0.75px). 흐림 중에도 고리는 흐려지지 않는다(계산 `opacity` 1).
- 작은 노드(배관 구간 마름모, 계기 r5, 배관 요소 r4)도 확대 후 고리가 노드와 떨어져 보인다. 배관 구간을 선택하면 기존대로 해당 has_endpoint 선도 파랗게 된다(변경 없음).
- 확대·축소: 고리는 노드와 같은 그래프 좌표에 그려 함께 커지고 작아진다(`vector-effect` 없음). 맞춤 배율(약 49%)에서는 설비 고리 반지름이 약 5.4px, 선 약 1.2px이다.
- 스크린샷(저장소 밖): 작업 세션 scratchpad `w7\s1-*.png`(100%)·`w7\s125-*.png`(125%). 파일 이름은 `<배율>-<standalone|embedded>-<1before|2after|3…|4…>.png`, `-full`은 창 전체.
- 미확인: windows 플랫폼(실제 DPI) 렌더, 1366 실제 화면에서 맞춤 배율 가독성.

## 4. 회귀 확인

- `tests/test_graph_select.py`가 함께 확인: 노드 테두리 계산값은 `card`(흰 띠 유지), 경로 강조 중 노드 테두리는 `hl-path`, 도면 선택 `.selected.sym`은 `--ui` 3px 그대로, 계장 신호선을 고르면 고리가 숨음, 고리는 노드 층 위·라벨 층 아래, 앱 내장 흐림 중 고리 `opacity` 1.
- hover: 그래프 노드에는 hover 스타일이 없고 도면 hover CSS는 바꾸지 않았다.
- 경로 질의 결과·경로 엔진은 바꾸지 않았다(`check_viewer_paths.js` 불일치 0).

## 5. 검증(전용 venv `%USERPROFILE%\.hazop\venv-py312`)

| 명령 | 결과 |
|---|---|
| `python -m unittest discover -s tests -t .` | 첫 구현 664개 OK(건너뜀 14). 재작업 1회차 663개 OK(건너뜀 14, 렌더 2건 → 하위 프로세스 1건·배율 2개 subTest), rc 0 |
| `python scripts/check_design.py --platform windows` | rc 0(색 비교 통과, 명암비 67쌍 통과, 앱 코드 색 리터럴 0(허용 3곳), 100%·125% 작업 영역 통과) |
| `python scripts/check_viewer.py` | 결과 통과, rc 0 |
| `node scripts/check_viewer_paths.js` | 도면 6개·사례 9560건·불일치 0건, rc 0 |
| `python scripts/check_kg_screen.py` | 결과 통과, rc 0 |
| `python scripts/check_app.py` | 결과 전부 통과, rc 0 |

## 6. 남은 점

- ③ 지식그래프(`hazop/kg/screen_template.html`, T1)와 앱의 그래프 전용 HTML(SVG 없는 도면, 스크립트 없음)은 이번 범위 밖이다. 그래프 전용 HTML은 원래 선택 표시가 없다.
- 디자인 문서(`디자인/`)의 그래프 선택 표시 설명 갱신은 제안만 한다: "그래프 노드 선택 = 흰 테두리 유지 + 바깥 UI 파랑 고리(반지름 +4, 2.5px)".

## 7. 재작업 1회차(Claude·Codex 조건부 승인 반영)

### 7.1 변경

- 고리 층 위치: `groot.insertBefore(선택 층, 라벨 층)`. 이제 고리는 노드 층 바로 다음에 있고 라벨 층 바로 앞에 있다.
- `select()`: 없는 ID(null·삭제된 대상)가 오면 이전 항목이 있을 때만 `selected` 클래스를 떼고, 선택을 해제한 뒤 고리를 숨기고 끝낸다. 이전에는 `it.els`에서 예외가 났고, 그 뒤의 선택도 모두 예외가 났다.
  - 해제 경로 확인: 템플릿에 명시적인 선택 해제 동작은 없다. 없는 ID가 들어오는 실제 경로는 클릭한 요소의 `data-local-id`가 색인에 없는 경우다. `select(null)`을 부르는 곳은 없다(`data-goto`·`data-local-id` 속성이 있어야 호출됨).
- `selMark()`: 노드 요소가 DOM에서 빠지면(`!isConnected`) 고리를 숨긴다.
- `디자인/시안/README.md` §5 '클릭 선택색' 행에 그래프 노드 바깥 고리를 반영했다.

### 7.2 테스트(`tests/test_graph_select.py`)

- 별도 프로세스로 실행한다. `QT_QPA_PLATFORM=offscreen`과 `QT_SCALE_FACTOR` 1·1.25를 명시한다. 실패하면 화면 폴더 경로와 출력을 보여 준다.
- 기다림은 신호(loadFinished·ready·runJavaScript 콜백)와 QTimer 확인(시간 상한, sleep 없음)으로만 한다. 좌표 클릭은 페이지의 click 처리가 끝날 때까지 확인한다.
- 판정 항목:
  - 선택은 좌표 클릭(QTest)으로 한다. 노드 중심의 `elementFromPoint`는 노드다.
  - 고리 위 계측 간선 좌표의 `elementFromPoint`는 `gedge-hit`이고, 클릭하면 그 간선이 선택되고 고리는 숨는다. 고리의 계산된 `pointer-events`는 `none`이다.
  - 화소: 고리 자리를 8개 각도 구간으로 나눠 모든 구간에서 `--ui` 화소가 15% 이상이다. 선택 전에는 고리 자리 `--ui` 화소가 5개 이하다. 고리 영역 전체가 뷰포트 안에 있다.
  - 라벨: 'RC-PZ01' 첫 글자 상자(`getExtentOfChar(0)`)의 어두운 화소 수가 선택 전의 90% 이상이다. 고리 층을 맨 위로 되돌린 템플릿으로 돌리면 7 → 1로 실패한다.
  - DOM: 고리는 항상 1개다. 굵기 2.5px, 색 `--ui`, 반지름 11이다. 줌·이동 뒤, 힘 기반 배치 전환과 복귀 뒤에도 cx·cy가 노드와 같고 화면 중심 차이가 0.5px 미만이며 반경비가 11/7이다. 범례 필터로 숨기면 `display: none`이고 복원하면 다시 보인다. 없는 ID를 클릭하면 숨김·노드 선택 해제·JS 오류 0이다. 노드 요소를 DOM에서 지우면 다음 갱신에서 숨는다.
  - 회귀: 노드 흰 테두리 유지, 경로 강조 중 노드 테두리 `hl-path`, 앱 내장 흐림+원인에서 고리 opacity 1, 도면 `.selected.sym`은 `--ui` 3px 그대로.
- 안정성: 배율 1·1.25를 번갈아 하위 프로세스로 8회 돌려 모두 OK였다. 좌표 클릭 순서 맞춤을 넣기 전에는 6회 중 3회 실패했다(클릭 처리 전에 다음 단계가 실행됨).
- 스크린샷: 작업 세션 scratchpad `w7r1\s1-*`·`w7r1\s125-*`. `1before`·`2after`·`3label`(라벨 확대)·`4onpath`·`4dim-cause`가 있다.

### 7.3 공용 `web_css()`에서 `.selected.gnode`를 지운 영향(코드 검색 근거)

| 화면 | `web_css()` 적용 | 선택 표시 | 판정 |
|---|---|---|---|
| ②④⑤ 앱 내장 뷰어(템플릿 HTML) | 적용(`webview.py:182` 주입) | 템플릿 `select()`가 고리를 그림 | 고리로 대체됨. 테스트 `test_embedded_viewer` |
| 그래프 전용 HTML(`hazop/app/data.py:146` `graph_only_html`, SVG 없는 도면) | 적용(같은 웹뷰) | 스크립트가 없다. 브리지 `onClick`(`webview.py:189`)은 `nodeSelected`만 보내고 클래스를 붙이지 않는다 | 원래 `.selected`가 붙지 않아 선택 표시가 없던 화면이다. 영향 없음 |
| ③ 지식그래프(`hazop/kg/screen_template.html`) | 미적용(`webview.py:176` `hzKG` 분기가 CSS 주입 전에 `return`) | 자체 처리 | 영향 없음 |
| 독립 뷰어(브라우저) | 미적용 | 템플릿 고리 | 테스트 `test_standalone_viewer` |

- 그 밖에 `web_css()`를 쓰는 곳은 `scripts/check_app.py:42`(문자열 검사)와 `check_design`(색 비교)뿐이다. 둘 다 `.selected.gnode`에 기대지 않고, 두 검사 모두 rc 0이다.
- `hazop/` 안에서 `selected` 클래스를 붙이는 JS는 템플릿에만 있다(검색 결과 `.py`에는 후보 선택 상태 문자열만 있음).

### 7.4 검증(재작업 1회차)

| 명령 | 결과 |
|---|---|
| `python -m unittest discover -s tests -t .` | 663개 OK(건너뜀 14), rc 0 |
| `python scripts/check_design.py --platform windows` | 색 비교 통과, 명암비 67쌍 통과, 앱 코드 색 리터럴 0(허용 3곳), 100%·125% 판정 통과, 종합 rc 0 |
| `python scripts/check_viewer.py` | 결과 통과, rc 0 |
| `node scripts/check_viewer_paths.js` | 도면 6개·사례 9560건·불일치 0건, rc 0 |
| `python scripts/check_kg_screen.py` | 결과 통과, rc 0 |
| `python scripts/check_app.py` | 결과 전부 통과, rc 0 |

## 8. 재작업 2회차(Claude 승인·Codex 반려 반영, 마지막 회차)

### 8.1 변경

- `select()`(`template.html:507~517`): 없는 ID(null·undefined·색인에 없음)가 오면 다음을 한다.
  - 이전 선택 클래스를 떼고 선택을 해제한다.
  - 고리를 숨긴다(`selMark()`).
  - 속성 패널을 초기 내용(`panelEmpty`, `template.html:491`에서 로드 때 저장한 `template.html:190`의 안내 문구)으로 되돌린다. 이전 선택의 패널 링크(`data-goto`)도 함께 사라진다.
- 문구: "맨 위 층" → "노드 층 위·라벨 층 아래"(`template.html:106` 주석, evidence/README.md, 이 문서 §4).
- `tests/test_graph_select.py`:
  - `wait_until`은 `check()`를 시작할 때 타이머를 멈추고, 조건이 거짓이면 다시 시작한다.
  - 없는 ID 클릭 뒤에 패널이 빈 상태인지 단정한다(안내 문구 있음, 링크 0, 제목 없음).
  - `select(undefined)` 테스트를 추가했다. 이어서 다시 선택해 정상 동작하는지도 본다.
  - 패널 초기화를 뺀 템플릿으로 돌리면 링크 10·제목 있음이 남아 실패하는 것을 확인했다.

### 8.2 실제 경로 확인(코드 근거)

- `select(null)`의 직접 호출: `select()`는 IIFE(`template.html:297`부터) 안의 비공개 함수라 페이지 밖에서 부를 수 없다. 이를 위해 함수를 공개하는 것은 기능 추가라 하지 않았다.
  - 템플릿 안의 호출처는 세 곳이다. 그래프·도면 클릭은 `closest("[data-local-id]")`로 찾은 요소의 속성값을 넘기고, 패널 링크와 경로 결과 링크는 `select(a.dataset.goto, true)`(`template.html:562`·`880`)를 부른다.
  - null이 들어가는 경로는 없다. undefined는 `data-goto`가 없는 링크에서 생긴다. 테스트는 이 실제 처리기로 `select(undefined, true)`를 부른다(null과 같은 분기).
- 선택된 ID의 데이터가 삭제되는 경로: 없다. 색인 `byLocal`은 로드 때 `template.html:324`·`328`에서만 채우고 지우는 코드가 없다(`delete`·재할당 검색 0건).
- 그래프 노드를 지우거나 다시 만드는 경로: 없다.
  - 노드는 그래프 절에서 한 번만 만든다(`template.html:668~686`, `gNodeLayer` `template.html:644`).
  - `placeAll`(`template.html:701`)은 좌표만 옮긴다. 범례 필터 `applyFilter`(`template.html:781`)는 `ghide` 클래스만 바꾼다.
  - 템플릿 전체에 `.remove()`·`removeChild`·`replaceChild`·`replaceWith`가 0건이다. 두 함수의 끝에서는 이미 `selMark()`를 부른다.
  - 따라서 `isConnected` 확인은 방어 코드다. `run_detached` 테스트는 실제 경로가 없어 노드를 직접 지우고 범례 change로 갱신을 일으킨다. 이 의도(방어 코드 회귀 확인)를 테스트 docstring에 적었다.

### 8.3 공용 `web_css()`의 `.selected.gnode` 삭제 — 사용처 근거 보강(§7.3)

- 웹뷰 로드는 `hazop/app/webview.py:339` `load_file` 하나다. 호출처는 `screens/viewer.py:104`, `analysis.py:295`·`446`, `review.py:847`·`863`(템플릿 뷰어 HTML 또는 그래프 전용 HTML), `knowledge.py:279`(③)다.
- CSS 주입: `webview.py:182`(`style` 추가)에서 한다. 그 전에 `webview.py:176`의 `window.hzKG` 분기가 `return`하므로 ③ 지식그래프에는 주입되지 않는다.
- 그래프 전용 HTML(`hazop/app/data.py:146` `graph_only_html`, 기록 `data.py:125`):
  - `<script>`가 없다(`test_app.py`가 `assertNotIn("<script", page.lower())`로 확인).
  - 노드는 `data.py:178`의 정적 `circle.gnode`다.
  - 브리지 클릭 처리 `webview.py:189~192`는 `nodeSelected`만 보내고 클래스를 붙이지 않는다.
  - 따라서 `.selected.gnode`가 적용될 일이 없었다.
- 그 밖에 `web_css()`를 쓰는 곳은 `scripts/check_app.py:42`·`scripts/check_design.py:660`(검사)뿐이다.

### 8.4 한계(이번에 고치지 않음)

- 각도 구간 화소 판정(8구간 각각 15% 이상)은 고리가 "보이는지"만 확인한다. 고리가 끊김 없이 이어지는지, 두께가 맞는지는 보장하지 않는다. 두께는 DOM 단정(계산된 `stroke-width` 2.5px, 반지름 11, 화면 반경비 11/7)으로 확인한다.
- `web_css()` 영향은 위 사용처 조사로 갈음한다. 새 사용처가 생기면 다시 확인해야 한다.

### 8.5 검증(재작업 2회차)

| 명령 | 결과 |
|---|---|
| `python -m unittest discover -s tests -t .` | 663개 OK(건너뜀 14), rc 0 |
| `python -m unittest tests.test_graph_select` 3회 반복 | 3회 모두 OK(회당 하위 프로세스 배율 1·1.25), rc 0 |
| `python scripts/check_design.py --platform windows` | 명암비 67쌍 통과, 100%·125% 판정 통과, 종합 rc 0 |
| `python scripts/check_viewer.py`·`check_kg_screen.py`·`check_app.py` | 모두 통과, rc 0 |
| `node scripts/check_viewer_paths.js` | 도면 6개·사례 9560건·불일치 0건, rc 0 |
