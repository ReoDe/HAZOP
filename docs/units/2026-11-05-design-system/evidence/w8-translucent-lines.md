# W8 반투명 관계선 대비 처리

> 조사·구현 일시: 2026-11-06 · 대상: `feat/next-units` HEAD `5225cc5` + W8 작업 트리(재작업 2회차 포함) · 작업: hazop-developer · 결정: [D13](../decisions.md)

## 1. 결정과 기준

- 사용자 결정(2026-11-06, `records/decision-log.md` 마지막 행): "모양·범례로도 구분되는 보조 선은 3:1 예외로 기록하고, 색만으로 의미를 전하는 선만 불투명도를 높여 3:1을 맞춘다."
- 총괄 판정(재작업 1회차): has_endpoint 그래프 관계선은 예외가 아니다. 근거: 범례 색 견본·점선은 이 문서에서 신호·계측·미해결 선에도 단서로 세지 않았고(§2), 남는 단서인 마름모 끝 노드는 범례의 "배관 구간" 견본(점, `template.html:778`)과도 맞지 않는다. has_endpoint는 물리 경로 질의가 쓰는 공정 배관 관계라 보조 선으로 볼 근거가 없다.
- 기준은 [W5 §1](w5-contrast.md)과 같다: WCAG 2.1 SC 1.4.11(그래픽 3:1), 정확값 ≥ 3.0이면 통과(반올림 없음). 바탕은 흰 도면 `--card` `#ffffff`(`template.html:30` `#stage`). 합성은 `check_design._over`(채널별 `round(c·a + 255·(1−a))`).
- 판정 규칙: 선 종류마다 색 말고 구분되는 단서(선 모양 dash, 굵기, 화살표, 끝 노드 모양, 범례 표기)를 `template.html`에서 찾는다. 색 견본만 다른 범례는 단서로 세지 않았다 `[추론]`(SC 1.4.1 취지).
- 색 토큰 값은 바꾸지 않았다. 불투명도만 바꿨다.

## 2. 판정 표(행 번호는 W8 작업 트리 `hazop/viewer/template.html`)

| 선 | 종류 | 색 말고 구분되는 단서 | 판정 |
|---|---|---|---|
| `.pipe-line` 도면 연결선 | 물리 `physical_connection` | 없음. 굵기 2.5 공통(:70), 점선은 미확인일 때만(:75·:407), 범례는 실선 색 견본(:183) | 색만 → 조정 |
| | 신호 `signal_connection` | 없음(같은 굵기·실선, 범례 실선 견본 :184) | 색만 → 조정(이미 통과) |
| | 계측 `measurement_connection` | 없음(범례 실선 견본 :185) | 색만 → 조정 |
| | 미해결 `unresolved` | 점선(:407, :75)과 범례 점선 견본(:186). 점선은 "미확인 항목 있음"(:187) 선과 같아 미확인 물리선과는 색으로만 구분 | 색만 → 조정(이미 통과) |
| `.gedge` 그래프 관계선 | `has_endpoint`(물리) | 한쪽 끝이 늘 마름모(구간) 노드(:679, `hazop/graph/build.py:121~122`), 범례 문구 "구간-끝 대상"(:768), 흐름 방향 미확인이면 점선(:670·:786). 범례 노드 견본은 점(:778)이라 마름모 단서와 맞지 않음 | 첫 구현은 예외 → **총괄 판정으로 조정**(§1) |
| | `signal_connection` | 없음. 굵기 1.4 공통(:107), 양 끝 모두 원, 범례는 실선 색 견본(:783) | 색만 → 조정 |
| | `measurement_connection` | 없음(위와 같음) | 색만 → 조정 |

- 도면 연결선 아래에는 원본 도면 SVG의 선(화살표·점선 등)이 깔리지만, 입력 도면마다 달라 템플릿 단서로 세지 않았다.
- 클릭·속성 패널·범례 체크박스(종류 끄기)로도 종류를 알 수 있으나, 보는 것만으로 구분되는 단서가 아니라 세지 않았다.
- 결과: 예외 선은 없다. 모든 관계선이 3:1 판정 대상이다.

## 3. 조정 값과 전후 수치(흰 도면 합성 대비)

불투명도는 3:1을 처음 넘는 두 자리 소수(0.01 낮추면 미달)다. 도면 연결선은 종류 표시 속성이 없어(부모 `<g>`에 `data-kind` 없음) 한 값으로 올렸고, 그래프 관계선은 부모 `<g data-kind>`(:667)로 종류별 규칙을 더했다.

| 규칙 | 종류 | 전 불투명도 → 대비 | 후 불투명도 → 대비 | 0.01 낮추면 |
|---|---|---|---|---|
| `.pipe-line`(:70) | 물리 | .75 → 2.4331 | .93 → 3.0456 | |
| | 신호 | .75 → 3.6090 | .93 → 5.0495 | 공통 값이라 함께 오름 |
| | 계측 | .75 → 2.4016 | .93 → **3.0007** | .92 → 2.9775(이 종류가 값을 정함) |
| | 미해결 | .75 → 3.4901 | .93 → 4.5001 | 공통 값이라 함께 오름 |
| `.gedge`(:107, 기본) | has_endpoint | .55 → 1.9069 | .92 → 3.0064 | .91 → 2.9680 |
| `[data-kind="signal_connection"] > .gedge`(:108) | 신호 | .55 → 2.4690 | .66 → 3.0370 | .65 → 2.9833 |
| `[data-kind="measurement_connection"] > .gedge`(:109) | 계측 | .55 → 1.8850 | .93 → **3.0007** | .92 → 2.9775 |

- 계측 3.0007·has_endpoint 3.0064는 여유가 거의 없다. 알파를 8비트로 양자화해도(237/255 → 3.0003, 235/255 → 3.0082) 통과한다. W5처럼 정확값 판정이고 검사가 값 하락을 막는다.
- 선택·강조는 그대로 구분된다: 도면 hover·선택(:72·:77), 그래프 선택(:114), 경로 강조(:126)는 불투명도 1에 색(`--selected`·`--hl-path`)과 굵기(4·4.5·3·5)가 바뀐다. 종류별 규칙은 이 규칙들과 명시도가 같아(0,2,0) 그 **앞**에 두었다(앱의 `.hz-path.gedge`는 `web_css()`가 뒤에 주입). 불투명도 차이(.92~.93 → 1)는 작아졌지만 원래도 색·굵기가 주된 구분이었다.

## 4. 검사(`scripts/check_design.py`)

- `stroke_rows`/`stroke_problems`: 선 종류를 손으로 옮긴 목록 대신 읽는다. `.gedge`는 템플릿 JS `EDGE_COLOR`(:626)를 주석을 지우고 문자열·정규식 리터럴 밖에서만 찾아 해석한다(`_js_code`). `.pipe-line`은 추출 규칙의 관계 종류(`hazop/extract/rules.LINE_TYPE_RELATION` 값) + `unresolved`이며, 템플릿 색 식(:406)·`<g data-kind>` 생성 코드(:667)도 코드 위치에서만 인정한다.
- 불투명도: 최상위(at 규칙 밖) 기본 규칙 `.pipe-line`·`.gedge`와 `[data-kind="종류"] > .gedge`에서 `stroke-opacity`·`opacity`를 읽어 속성별로 겹친 뒤 곱한다(백분율·[0,1] 제한).
- 판정: 합성 대비 < 3:1이면 실패(rc 1, 결과 JSON `color_problems`에 합산). 예외 목록은 없앴다.
- 우회 차단(모두 실패):
  - 인식하지 못한 선택자가 불투명도 < 1을 줌: 선 클래스를 쓴 다른 형식(`#graphsvg .gedge`, `g[data-kind=…] > .gedge`, `.gedge.unknown`, `.gedge:not(…)`, `[data-kind] > .pipe-line`, `EDGE_COLOR`에 없는 종류), 어느 선택자든 `stroke-opacity` < 1, 컨테이너(`#stage`·`#overlay`·`#graphsvg`·`#viewport`)·SVG 요소(`line`·`path`·`polyline`·`g`·`svg`·`*`)·속성/의사 클래스만 있는 선택자의 `opacity` < 1.
  - 인식한 형식이라도 `@media` 등 at 규칙 안에서 < 1(`css_rules_ctx`가 감싼 at 규칙을 구분).
  - 인식한 형식의 불투명도에 `!important`(우선순위를 판정하지 않음).
  - 선에 닿는 선택자(인식한 규칙 포함)의 `filter`에 `opacity(`(재작업 2회차).
  - 선 규칙의 CSS 중첩(규칙 블록 안 `{`): 부모나 자식 선택자가 선에 닿으면 실패. `css_rules_ctx`는 중첩 머리를 부모 선언 뒤 텍스트로 잡고, 감싼 블록 머리에 부모 선택자를 남긴다(재작업 2회차).
  - 템플릿 JS나 HTML이 불투명도를 직접 설정. HTML 주석(안의 style·script 포함)은 보지 않는다. JS는 주석을 지우고, 리터럴 밖 코드의 `opacity`·`strokeOpacity`·`stroke-opacity` 이름과, 문자열이 속성 이름 그 자체(`"stroke-opacity"` 등)이거나 `opacity:` 선언을 담은 경우만 실패로 본다. 템플릿 리터럴의 `${…}`는 코드로 다시 읽는다(재작업 2회차: URL·설명 문자열·`${}` 안 주석 오탐 제거).
  - 구성 문제: `EDGE_COLOR` 없음·해석 불가·빈 값, 색 토큰 없음, 도면 연결선 색 식 없음, 해석 못 하는 불투명도 값, `<g data-kind>` 생성 코드 없음.
- 반투명 채움·그림자(rgba)는 전처럼 보고만 한다(`translucent_rows`, 종료 코드 미반영).
- W8 이전 불투명도(`.pipe-line` .75, `.gedge` .55 일괄)에서는 5건 실패(`.pipe-line` 물리·계측, `.gedge` has_endpoint·신호·계측).

## 5. 테스트(`tests/test_design.py` `TranslucentStrokeTest` 11건, `ContrastTest.test_translucent_report` 갱신)

실제 템플릿 통과·불투명도 값 고정·예외 목록 없음, 경계값(조정 값 4곳 각각 0.01 낮추면 그 선만 실패), W8 이전 불투명도 5건 실패, 선택·hover·경로 강조 규칙의 `stroke-opacity` = 1·`opacity` 없음·종류별 규칙보다 뒤, 우회 12종 실패(위 §4 목록)와 정상 3종 통과(강조 1, 선과 무관한 opacity, `@media` 안 1), `opacity` 곱, JS 속성·JS `style.strokeOpacity`·HTML `style="opacity"` 실패와 JS 주석 속 언급 무시, 선 종류 읽기(새 종류는 기본 불투명도로 판정, 주석·문자열 속 `EDGE_COLOR` 미끼 무시, 정규식 리터럴 속 따옴표 처리, 읽기 실패 5종), 백분율·제한. 재작업 2회차: 오탐 4종 통과(HTML 주석 속 style·script, URL·설명 문자열, `${}` 안 블록·줄 주석, 문자열 속 설명과 `${}` 안 중괄호), 차단 6종 실패(`.gedge`·`#graphsvg .gedge`·종류별 규칙의 `filter: opacity()`, 선 규칙 중첩 2종, `${}` 안 `style.opacity` 대입)와 정상 2종 통과(선과 무관한 중첩·`.gnode` filter), 중첩 머리 파싱.

## 6. 화면 확인(offscreen, 스크래치 폴더 — 저장소 밖)

스크래치 스크립트로 SNP-M-102 뷰어를 임시 폴더에 만들고(`tests/test_graph_select.build_viewer_html`) 1366×768 offscreen으로 띄워 계산 스타일을 읽었다(재작업 1회차 값).

| 대상 | 계산 `stroke-opacity`(굵기) |
|---|---|
| 도면 물리·신호·계측 | 0.93(2.5px) |
| 그래프 has_endpoint / 신호 / 계측 | 0.92 / 0.66 / 0.93(1.4px) |
| 도면 선택 | 1(4.5px, `rgb(37,99,235)`) |
| 그래프 신호·계측·has_endpoint 선택 | 1(3px, `--selected`) |
| 그래프 신호·계측 경로 강조(`onpath`) | 1(5px, `rgb(234,88,12)`) |

PNG 경로는 작업 보고에 적는다(스크래치, 저장소에 넣지 않음). ③ 화면(`check_kg_screen --screenshots`)은 `hazop/kg/screen_template.html`이라 이번 변경과 무관하며 회귀 확인용이다.

## 7. 검증 결과(전용 venv `%USERPROFILE%\.hazop\venv-py312`)

| 명령 | 첫 구현 | 재작업 1회차 | 재작업 2회차 |
|---|---|---|---|
| `python -m unittest discover -s tests -t .` | 674개 OK(건너뜀 14) | 676개 OK(건너뜀 14), rc 0 | 678개 OK(건너뜀 14), rc 0 |
| `python -m unittest tests.test_design` | 56개 OK | 57개 OK | 59개 OK |
| `python scripts/check_design.py --platform windows --out <스크래치>` | 종합 rc 0 | 색 비교·명암비 67쌍·반투명 관계선 7종·앱 코드 색 리터럴 통과, 100%·125% 통과, 종합 rc 0 | 같음, 종합 rc 0 |
| `python scripts/check_kg_screen.py --screenshots <스크래치>` | 통과 | [OK] 14건·테스트 33개, 결과 통과, rc 0 | 같음, rc 0 |
| `node scripts/check_viewer_paths.js` | 저장소 `출력/`(이전 빌드, 읽기만)·스크래치 빌드 모두 rc 0 | 같음: 도면 6·사례 9560·불일치 0, rc 0(스크래치 빌드는 재작업 템플릿으로 다시 만듦) | 같음, rc 0(스크래치 빌드 다시 만듦) |
| `python scripts/check_viewer.py` | 스크래치 작업 루트(`HAZOP_WORK_ROOT`·`HAZOP_STORE_ROOT`)에서 1~3단계 통과, 4단계 unittest 29건 실패(작업 루트에 의존하는 지식그래프·등록 테스트) | 다시 돌리지 않음. 저장소 기본 경로 실행은 QA 확인 예정(총괄) | 같음 |

## 8. 남은 한계

- 계측(3.0007)·has_endpoint(3.0064)는 여유가 거의 없다. 1.4px 그래프 선과 2.5px 도면 선은 안티에일리어싱으로 가장자리 화소가 바탕과 섞여, 실제 화면 대비가 계산값(선 중심의 단색 합성)보다 낮을 수 있다. 화소 측정은 하지 않았다.
- `data.graph_only_html`(앱 ② 그래프 보기 단독 HTML)은 관계선을 불투명(1)으로 그려 3.30:1로 통과한다(`hazop/app/data.py`, 편집 범위 밖, 검사 대상 아님).
- 도면 연결선은 종류 표시 속성이 없어 한 값(.93)으로 올렸다. 신호·미해결은 필요보다 진해졌다(.66이면 충분). 종류별로 하려면 템플릿 JS에 `data-kind`를 더해야 한다(README §8의 template.html 범위는 "색·CSS만").
- 검사는 휴리스틱이라 모든 우회를 막지 않는다(총괄 판정, 재작업 2회차). 알려진 한계:
  - 클래스만 쓴 상위 요소 선택자(예: `.edges`, `#stage > div`)와 `body`·`main`의 `opacity`는 보지 않는다(`g.edges`처럼 SVG 요소를 쓴 선택자는 판정한다). CSS 이스케이프 클래스(`.g5 dge`)도 선 클래스로 인식하지 못한다. `opacity` 판정은 선 클래스·컨테이너 id(`#stage`·`#overlay`·`#graphsvg`·`#viewport`)·SVG 요소 선택자에만 한다.
  - 반투명 stroke 색(`stroke: rgba(…)`·`#rrggbbaa`)은 합성에 넣지 않는다. 선 색은 템플릿 JS의 `var(--토큰)`만 읽는다.
  - JS 정규식 리터럴은 앞 문자로 가리므로 `return /…/`·`typeof /…/`처럼 키워드 뒤 정규식은 나눗셈으로 본다(그 안의 따옴표가 문자열 판정을 흐릴 수 있음).
  - JS 문자열 조합으로 만든 `style`(예: `"stro" + "ke-opacity"`)은 잡지 않는다.
  - 앱이 주입하는 `web_css()`의 `body.hz-dim … .gedge` 흐림(`--hl-dim`)은 강조 중 흐림이라 W5처럼 대상이 아니다.
- `design/mockups/interface-mockup.html:322`의 `.ovl.line { stroke-opacity: .75 }`는 새 값(.93)과 다르다. `design/`은 편집 범위 밖이라 후속(디자인 담당)으로 넘긴다.
- `check_viewer.py`는 기본으로 저장소 `출력/`에 다시 쓰므로 작업지시서(출력/ 쓰기 금지)에 따라 실행하지 않았다. 4단계 unittest와 같은 테스트를 환경변수 없이 돌린 결과(재작업 2회차 678개 OK)는 위 표에 있다.

## 9. 총괄 직접 수정(D14, 재작업 한도 뒤)

- `_scan_js`: 템플릿 리터럴의 `${`를 한 글자씩 넣어 `len(out)`이 문자 위치와 맞게 했다(보간식이 여럿일 때 문자열 구간이 어긋나 `line.style["opacity"]=.1`이 통과하고 정상 URL이 실패하던 결함).
- `_template_parts`: HTML 주석·`<style>`·`<script>` 중 앞에서 먼저 시작하는 것을 취한다. script·style 안의 `"<!--"`·`"-->"` 문자열이 그 사이 코드를 지우던 결함을 막았다.
- JS 문자열 판정에 SVG 속성 꼴 `opacity="…"`를 더했고, `-webkit-filter: opacity()`도 `filter`와 같이 실패로 본다.
- 회귀 테스트: `TranslucentStrokeTest.test_direct_bypasses_rework2`에 위 4종과 보간식 8개 뒤 URL 정상 통과 사례를 더했다. `tests.test_design` 59개 OK.
