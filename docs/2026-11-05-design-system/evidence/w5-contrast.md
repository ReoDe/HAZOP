# W5 명암비 조정과 대비 검사

> 조사·구현 일시: 2026-11-06 · 대상: `feat/next-units` HEAD `dbcc855` + W5 작업 트리(재작업 1회차 포함) · 작업: hazop-developer · 결정: [D7](../decisions.md)

## 1. 기준과 출처

- 출처: W3C, *Web Content Accessibility Guidelines (WCAG) 2.1* (W3C Recommendation, https://www.w3.org/TR/WCAG21/).
  - SC 1.4.3 Contrast (Minimum), 수준 AA: 글자 4.5:1, 큰 글자(18pt 이상 또는 굵은 14pt 이상) 3:1. 비활성 구성요소의 글자는 예외.
  - SC 1.4.11 Non-text Contrast, 수준 AA: UI 구성요소(상태 표시 포함)와 내용 이해에 필요한 그래픽 요소는 인접 색과 3:1.
  - 용어 정의 "relative luminance"·"contrast ratio": L = 0.2126 R + 0.7152 G + 0.0722 B(sRGB 채널을 선형화, 문턱 0.04045 [^1]), 대비 = (L1 + 0.05) / (L2 + 0.05), L1은 밝은 쪽.
  - 이 문서의 SC 내용은 원문을 이번 작업에서 다시 열람하지 않고 쓴 것이다(네트워크 사용 금지) `[일반지식]`. 계산 구현은 알려진 값(#000/#fff = 21:1, #777/#fff ≈ 4.48:1)으로 확인했다(`tests/test_design.ContrastTest`).
- 적용: 앱 글자는 11~15px(`tokens.FONT_SIZE`)이라 모두 "일반 글자"로 보고 4.5:1을 쓴다([W1 §3](w1-survey.md)). 노드·관계 색, 시나리오 강조, 선택·포커스 테두리는 3:1.

[^1]: WCAG 2.1 정의문은 0.03928을 적었으나 sRGB 표준값은 0.04045다. 8비트 색에서는 두 문턱 사이에 값이 없어 결과가 같다 `[일반지식]`.

## 2. 검사 방법

- `scripts/check_design.py`의 `CONTRAST_PAIRS`(67쌍)를 `tokens.COLORS`로 계산한다. 판정은 **불투명 토큰 값 기준**이고 정확값이 기준 이상이면 통과다(반올림하지 않음). `--colors-only`와 기본 실행 모두 뷰어·앱 색 비교 뒤에 이어서 돌고, 미달이 있으면 rc 1, 결과 JSON의 `color_problems`·`verdict`에 합산한다(D5 방식과 같음). 진단 출력은 소수 넷째 자리까지 적는다.
- 쌍은 [W1 §3](w1-survey.md)의 측정 대상과 실제 쓰는 곳에서 골랐다. 근거 위치는 §3 표의 "근거" 칸에 적었다(행 번호는 W5 작업 트리 기준). 이름은 `COLORS` 키이고, `#`로 시작하는 값은 토큰 밖 리터럴이다(qss의 `#ffffff`·`#dcfce7`, 뷰어 허용 목록 `#b45309`·`#16a34a`).
- 노드·관계 색이 실제로 그려지는 바탕은 둘이다: 흰 도면(②·독립 뷰어 `#stage` = `--card`, `template.html:30`; `data.graph_only_html`의 `#graphsvg` `#fff`, `data.py:190`)과 ③ 캔버스(`--kg-canvas`, `screen_template.html:38`). `--bg`(`#viewport`, `template.html:28`)는 그리는 바탕이 **아니다**. `--bg` 쌍은 D1이 계측 연결 조정을 확정한 근거([W1 §3.1](w1-survey.md))를 지키려고 남긴 회귀 방지 쌍이며, `measurement_connection` 조정은 이 D1 결정에 따른 것이다(흰 도면·③ 캔버스에서는 전에도 3.19·3.11로 통과).
- `ai-hatch-b`(`#e8eaee`)는 정의(`tokens.py:34`) 말고 쓰는 곳이 없어(앱·뷰어·③ 검색) 쌍에 넣지 않았다. `kg-flag-ink`(③ 경고 글자, `warn-ink`와 같은 값)는 T1 소유라 넣지 않았다.
- 반투명 rgba 허용(D5 ④)을 용도별로 좁혔다: 글자색 `color` 속성에 쓴 반투명 rgba는 실패(`반투명 글자색 …`), 채움·그림자 등은 허용하되 아래 §7.1 합성 대비 보고에 넣는다.
- 반투명 선·채움을 흰 도면에 합성한 대비는 `translucent_rows`/`translucent_check`가 **보고만** 한다(종료 코드 미반영, §7.1).

## 3. 쌍별 명암비 전후

전 = `dbcc855`, 후 = W5 작업 트리. 굵게 = 전에 미달. 경계값은 소수 셋째 자리까지 적었다. 근거의 `tokens`는 `hazop/app/tokens.py`, `tpl`은 `hazop/viewer/template.html`, `kg`는 `hazop/kg/screen_template.html`이다.

### 3.1 글자(4.5:1, SC 1.4.3)

| 글자 / 바탕 | 전 값 | 전 | 후 값 | 후 | 쓰는 곳 | 근거 |
|---|---|---|---|---|---|---|
| `ink` / `card` | `#111827` | 17.74 | 같음 | 같음 | 본문(카드·표·상세) | tokens:116·149 |
| `ink` / `bg` | | 16.26 | | 같음 | 화면 바탕 본문 | tokens:116·117 |
| `ink` / `ui-weak` | | 16.30 | | 같음 | 선택된 표 행 | tokens:151 |
| `ink` / `ai-hatch-a` | | 15.84 | | 같음 | AI 산출 상자 글자 | tokens:142, widgets.py:142 |
| `ink` / `kg-canvas` | | 17.30 | | 같음 | ③ 캔버스 노드 값 글자·범례 제목 | kg:52·385 |
| `ink-2` / `bg` | `#374151` | 9.45 | 같음 | 같음 | 기본 칩·plain 배지 | tokens:130, widgets.py:120 |
| `ink-2` / `card` | | 10.31 | | 같음 | 그래프 라벨·강조 범례 | tpl:105, tokens:104, data.py:184 |
| `ink-2` / `kg-canvas` | | 10.05 | | 같음 | ③ 관계 라벨·칩 | kg:46·442 |
| `muted` / `card` | `#6b7280` | 4.83 | `#6a717e` | 4.91 | 단계 탭·섹션 제목·뷰어 패널 보조 글자 | tokens:122·136, tpl:21·55~58 |
| `muted` / `bg` | | **4.43** | | 4.502 | 표 머리·`QLabel#muted`·뷰어 `.chip` | tokens:134·152, tpl:23 |
| `muted` / `ui-weak` | | **4.44** | | 4.513 | 선택된 표 행의 제외 후보 글자 | analysis.py:54 + tokens:151 |
| `muted` / `kg-canvas` | | 4.72 | | 4.79 | ③ 범례 메모·캔버스 안내 | kg:55·57 |
| `ui` / `card` | `#2563eb` | 5.17 | 같음 | 같음 | 링크. 선택·포커스 테두리(3:1)도 이 쌍으로 충족 | tpl:26·60·75, tokens:126·147 |
| `#ffffff` / `ui` | | 5.17 | | 같음 | 선택된 단계 탭·주 버튼 | tokens:123·128 |
| `ui-ink` / `ui-weak` | | 8.01 | | 같음 | ui 배지 | widgets.py:119 |
| `ok` / `#dcfce7` | | 4.57 | | 같음 | 통과 칩 | tokens:131 |
| `err-ink` / `err-bg` | | 5.91 | | 같음 | 막힘 칩·오류 띠 | tokens:132·141 |
| `warn-ink` / `warn-bg` | | 6.37 | | 같음 | 경고 칩·띠·뷰어 정렬 경고 | tokens:133·140, tpl:80, data.py:189 |
| `warn-ink` / `card` | | 7.09 | | 같음 | ③ 오른쪽 상세 경고 글자(QTextBrowser 흰 바탕) | knowledge.py:409·434·439·463·516·543 |
| `err-ink` / `card` | | 6.47 | | 같음 | ③ 오른쪽 상세 "근거 없음" | knowledge.py:414 |
| `ai-ink` / `ai-hatch-a` | | 6.75 | | 같음 | AI 배지 | widgets.py:115 |
| `#ffffff` / `human-line` | | 17.74 | | 같음 | 사람 확정 배지 | widgets.py:116 |
| `risk-ok/cond/deny-ink` / 각 `-bg` | | 9.03·7.28·8.31 | | 같음 | 위험도 확정 칩 | widgets.py:134 |
| `risk-ok-ink` / `#ffffff` | | 10.31 | | 같음 | 위험도 제안 칩 1·2 글자 | widgets.py:132 |
| `risk-cond-line` / `#ffffff` | `#d97706` | **3.19** | `#b36205` | 4.501 | 위험도 제안 칩 3·4 글자 | widgets.py:132 |
| `risk-deny-line` / `#ffffff` | | 8.31 | | 같음 | 위험도 제안 칩 5 글자 | widgets.py:132 |
| `#ffffff` / `hl-safeguard`, 반대 | | 4.71·4.71 | | 같음 | 보호수단 배지, 약한 배지 | tokens:99~102 |
| `#b45309` / `card` | | 5.02 | | 같음 | 뷰어 경고 글자(허용 목록) | tpl:62·115 |

### 3.2 그래픽·UI 구성요소(3:1, SC 1.4.11) — 바탕 `card` / `bg` / `kg-canvas`

노드·관계 색 근거: 도면 기호 `tpl:381~383`, 연결선 `tpl:398~418`, 그래프 `tpl:610·653·662~666`, `data.py:171·177`, ③ `kg:135~151`.

| 색 | 전 값 | 전 | 후 값 | 후 | 쓰는 곳 |
|---|---|---|---|---|---|
| `equipment` | `#1d4ed8` | 6.70 / 6.14 / 6.54 | 같음 | 같음 | 설비 노드 |
| `valve` | `#0f766e` | 5.47 / 5.02 / 5.34 | 같음 | 같음 | 밸브 노드 |
| `instrument` | `#0ea5e9` | **2.77 / 2.54 / 2.70** | `#0d97d6` | 3.27 / 3.001 / 3.19 | 계장 노드 |
| `piping_element` | `#6366f1` | 4.47 / 4.09 / 4.36 | 같음 | 같음 | 배관 요소 |
| `unclassified` | `#9ca3af` | **2.54 / 2.33 / 2.48** | `#868e9d` | 3.30 / 3.02 / 3.22 | 미분류 노드·알 수 없는 관계 |
| `physical_connection` | `#16a34a` | 3.30 / 3.02 / 3.21 | 같음 | 같음 | 물리 연결, 배관 구간 |
| `signal_connection` | `#7c3aed` | 5.70 / 5.22 / 5.56 | 같음 | 같음 | 신호 연결 |
| `measurement_connection` | `#d97706` | 3.19 / **2.92** / 3.11 | `#d67506` | 3.28 / 3.005 / 3.20 | 계측 연결 |
| `unresolved` | `#dc2626` | 4.83 / 4.43 / 4.71 | 같음 | 같음 | 미해결 연결 |
| `hl-cause`·`hl-path`·`hl-safeguard` (card / bg) | | 4.83·3.56·4.71 / 4.43·3.26·4.32 | 같음 | 같음 | 시나리오 강조(tokens:93~98) |
| `ui` / `bg` | | 4.74 | | 같음 | 화면 바탕 위 버튼 hover·입력 포커스 테두리(tokens:126·147) |
| `tag` / `card` | | 17.74 | | 같음 | 태그 상자 테두리(tpl:72) |
| `#16a34a` / `bg` | | 3.02 | | 같음 | 뷰어 통과 점(tpl:24, `.chip` 바탕) |

미달 10쌍(전) → 0쌍(후). 재작업 1회차에서 더한 5쌍(`ink`·`ink-2`·`muted` / `kg-canvas`, `warn-ink`·`err-ink` / `card`)은 전후 모두 통과다.

## 4. 조정한 토큰

방법: HSL에서 색상(H)·채도(S)를 두고 명도(L)만 0.001씩 낮춰, 그 토큰이 든 모든 지정 쌍을 처음 넘는 값(가장 작은 변화)을 골랐다. 8비트 반올림 때문에 H·S가 소수점 수준으로 흔들린다.

| 토큰 | 전 | 후 | H | S | L | 묶는 쌍 |
|---|---|---|---|---|---|---|
| `muted` | `#6b7280` | `#6a717e` | 220.0 → 219.0 | 0.089 → 0.086 | 0.461 → 0.455 | `bg`·`ui-weak` 4.5 |
| `instrument` | `#0ea5e9` | `#0d97d6` | 198.6 → 198.8 | 0.887 → 0.885 | 0.484 → 0.445 | `bg` 3 |
| `unclassified` | `#9ca3af` | `#868e9d` | 217.9 → 219.1 | 0.106 → 0.105 | 0.649 → 0.571 | `bg` 3 |
| `measurement_connection` | `#d97706` | `#d67506` | 32.1 → 32.0 | 0.946 → 0.945 | 0.437 → 0.431 | `bg` 3 |
| `risk-cond-line` | `#d97706` | `#b36205` | 32.1 → 32.1 | 0.946 → 0.946 | 0.437 → 0.361 | `#ffffff` 4.5 |

- `measurement_connection`과 `risk-cond-line`은 전에 같은 값이었으나 기준이 달라(3:1 대 4.5:1) 다른 값이 됐다. 키가 따로라 코드 영향은 없다.
- 같은 옛 값을 쓰는 T1 소유 토큰(`a1-na` `#6b7280`, `a1-unknown`·`comp-other` `#9ca3af`)은 바꾸지 않았다(README §8).
- 여유 없이 기준을 막 넘는 값이다(4.502·4.501·3.001 등). 총괄 판정으로 이 값을 유지한다. 근거: WCAG 2.1은 정확값 ≥ 기준으로 판정하고(반올림하지 않음), 이 검사가 정확값으로 계산해 값이 조금이라도 내려가면 rc 1로 회귀를 막는다(`test_design.ContrastTest.test_boundary`가 4.5·3.0 통과, 4.4999·2.9999 실패를 고정). 다른 바탕을 쌍에 더하면 다시 미달할 수 있다.
- **한계: 미분류와 보조 글자가 가까워졌다.** `unclassified` `#868e9d`와 `muted` `#6a717e`의 대비는 1.49:1이다(전 `#9ca3af`/`#6b7280` 1.90:1). 독립 뷰어 그래프의 분류 없는 노드는 `unclassified` 채움에 `muted` 점선 테두리(`tpl:102` `.gnode.unknown`)를 쓰고, 알 수 없는 관계 종류의 범례 대체 색도 `muted`(`tpl:754`)라 둘의 구분이 약해졌다. 점선 모양으로는 구분된다. 값 조정은 하지 않았다.

## 5. 영향 범위(전후)

| 출력 | 바뀐 값 | 영향 |
|---|---|---|
| `tokens.qss()` | `muted`만 | `QPushButton#step`·`:disabled`·`QLabel#muted`·`QLabel#section`·`QHeaderView::section`·`QTabBar::tab` 글자색 `#6b7280` → `#6a717e`. `instrument`·`unclassified`·`measurement_connection`·`risk-cond-line`은 qss에 안 쓰임 |
| `tokens.web_css()` `:root` | 5개 모두 | 앱 안 ② 뷰어의 `--muted`·`--instrument`·`--unclassified`·`--measurement_connection`·`--risk-cond-line` |
| `tokens.kg_css_vars()`(③) | 5개 모두 | ③ `--muted`(14곳), 계장·미분류 노드 색(`TYPE.instrument`·`unclassified`), 계측 연결 선(`meas`). `--kg-*`·`--a1-*`·`--comp-*` 값은 그대로 |
| `widgets.risk_chip` | `risk-cond-line` | 제안 칩 3·4 글자·점선 테두리, 확정 칩 3·4 테두리. `risk-ok-line` 비교는 W4에서 토큰 참조로 바꿔 둠(값 불변) |
| `data.graph_only_html` | `instrument`·`unclassified`·`measurement_connection` | `COLORS`를 읽어 자동 반영 |
| `template.html` `:root` | `muted`·`instrument`·`unclassified`·`measurement_connection` | 같은 값으로 바꿈(D5 색 비교 통과). `--risk-cond-line`은 템플릿에 없음 |
| 범위 밖 하드코딩 | — | `render.py:102,133`·`analysis.py:511,519`·`register.py:241,304`·`viewer/build.py:83,86`의 `#6b7280`, `render.py:146`의 `#9ca3af`는 옛 값 그대로. 편집 허용 범위 밖(W6 대상) |

## 6. W4 관찰 판정([w4 §5.2](w4-tokens.md))

### 6.1 선택 테두리 `#2563eb`와 설비 `#1d4ed8`

- 두 색의 대비는 1.30:1이다. 색만으로는 구분되지 않는다.
- 도면 기호(`.sym`): 평소 설비 테두리 `#1d4ed8` 1.5px → 선택 `#2563eb` 3px + 채움. 상태 변화는 굵기(2배)와 채움으로 드러나고, 선택 테두리는 인접한 흰 도면과 5.17:1이다. SC 1.4.11(표시가 인접 색과 3:1)과 1.4.1(색만으로 구분하지 않음)을 충족한다고 판정 `[일반지식]`. **조정 없음.**
- 그래프 노드(`.gnode`): 설비 노드는 `#1d4ed8` 채움 + 흰 테두리 1.5px → 선택하면 테두리가 `#2563eb` 3px가 된다. 테두리 안쪽이 채움과 1.30:1이라 흰 띠가 사라지고 원이 조금 커지는 정도로만 보인다. 바깥쪽 흰 캔버스와는 5.17:1이다. **약점으로 남긴다.** 선택 색을 바꾸면 인터페이스 §4.1(선택 = UI 파랑)과 어긋나고, 테두리 구조(바깥 고리 등)를 바꾸는 것은 최소 조정 범위를 넘는다. 렌더 확인과 함께 별도 결정 대상으로 넘긴다([PROGRESS §5](../PROGRESS.md)).

### 6.2 hover 채움 `.18`과 선택 채움 `.12`

- 흰 바탕에 합성한 색: 평소 `.06` `#f2f6fe`(1.08:1), 선택 `.12` `#e5ecfd`(1.18:1), hover `.18` `#d8e3fb`(1.29:1). 어느 채움도 3:1 근처가 아니다. 채움은 상태를 식별하는 표시가 아니고, 선택의 식별 표시는 3px 테두리(5.17:1, 선택 채움 위에서도 4.37:1)다.
- `.selected.sym`과 `.sym:hover`는 명시도가 같고 선택 규칙이 뒤에 있어(`template.html` 68행·75행, `web_css()`도 뒤에 주입), 선택된 기호 위에 마우스를 올려도 선택 채움(`.12`)과 테두리가 유지된다. hover가 선택 표시를 덮지 않는다.
- **조정 없음.** 채움 농도를 맞추는 것은 명암비 기준이 아니라 시각 위계 선택이다.

## 7. 검사에서 뺀 것과 이유

| 항목 | 이유 |
|---|---|
| `line`·`line-strong` 테두리(1.26·1.50), `warn-line`·`err-line` 띠 테두리(1.93·1.74) | 띠·칩·패널은 바탕색과 글자로 식별된다. 입력란 테두리(`line-strong` on 흰색 1.50)는 SC 1.4.11 해석이 갈린다([W1 §3.3](w1-survey.md)). 3:1로 올리면 화면 전체 선이 진해져 최소 조정 범위를 넘는다 — 열린 결정으로 남김 |
| 비활성 버튼 글자(`muted` on `bg`, `QPushButton:disabled`) | SC 1.4.3 예외. 다만 `muted` 조정으로 이 쌍도 4.502가 됨 |
| 반투명 선·채움(`.pipe-line` `stroke-opacity .75`, `.gedge` `.55`, rgba 채움·그림자) | 판정은 불투명 토큰 값 기준. 합성 대비는 §7.1에 보고만 한다(총괄 판정: 불투명도는 시각 설계라 이번에 바꾸지 않음, PROGRESS §5 열린 항목). 강조 중 흐림(`--hl-dim`)은 보고에도 넣지 않음 |
| `--kg-*`·`--a1-*`·`--comp-*` | T1 소유(README §8). 값 판정은 T1 |
| 허용 목록 2색(`#16a34a`, `#b45309`)의 값 통일 | D5 열린 항목. 대비는 둘 다 통과(3.02, 5.02)해 W5 근거로는 바꿀 이유가 없음 |

### 7.1 반투명 합성 대비(보고 전용, `check_design` 출력, 바탕 흰 도면 `--card`)

| 대상 | 불투명도 | 합성 대비(후) | 비고 |
|---|---|---|---|
| `.gedge` 그래프 관계선(`tpl:103`): 물리·신호·계측 | .55 | 1.9069 · 2.4690 · 1.8850 | 모두 3:1 미만. 선택·경로 강조 때는 불투명도 1 |
| `.pipe-line` 도면 연결선(`tpl:69`): 물리·신호·계측·미해결 | .75 | 2.4331 · 3.6090 · 2.4016 · 3.4901 | 물리·계측 3:1 미만. hover·선택 때 1 |
| `.sym`·`.sym:hover`·`.selected` 채움, `.tagbox`·hover 채움, `.onpath.sym` 채움 | .06~.18 | 1.08~1.40 | 상태 식별 표시가 아님(§6.2) |
| 그림자 `rgba(0,0,0,.06~.12)` | | 1.14~1.32 | 장식 |

같은 계산을 W5 이전 계측 연결 `#d97706`으로 하면 `.gedge` 1.86, `.pipe-line` 2.37이다. 총괄 지시의 범위(`.gedge` 1.81~2.49, `.pipe-line` 2.33~3.61)와 소수 둘째 자리에서 조금 다르다. 재검토에서 원인이 확인됐다: 검토자 수치는 미분류 색(`unclassified`)을 포함한 값이었고, `.gedge`·`.pipe-line`에는 미분류 색이 그려지지 않는다(`template.html` 398·610행). 이 표는 위 구현의 출력값이며 겹치는 색은 두 계산이 일치한다.

## 8. 후속 제안 → 반영됨(같은 변경에서 designer·planner가 디자인 문서·시안·인터페이스 §4를 갱신)

- `디자인/지식그래프화면.md` §1.2 표(27행 계장 "약 2.8:1 (3:1 미달, 기존 토큰)")와 40·246행 계장 대비 메모는 W5 뒤 값(`#0d97d6`, 흰 바탕 3.27:1)과 어긋난다. `디자인/시안/*.html` `:root`의 옛 값도 같다. `디자인/`은 다른 담당이 고치고 있어 이번에 고치지 않았다.
- `기획서/인터페이스.md` §4.1 345~349행의 `--muted` `#6b7280`, `--instrument` `#0ea5e9`, `--unclassified` `#9ca3af`, `--measurement_connection` `#d97706`, `--risk-cond-*` `#d97706`은 W5 값과 다르다. [w4 §5.1](w4-tokens.md)의 "값의 정본은 `hazop/app/tokens.py`" 문구를 반영하면서 값 칸을 지우거나 W5 값으로 바꿀 것을 제안한다.

## 9. 검증 결과(전용 venv `%USERPROFILE%\.hazop\venv-py312`)

| 명령 | 첫 구현 | 재작업 1회차 |
|---|---|---|
| `python -m unittest discover -s tests -t .` | 629개 OK(건너뜀 14), rc 0 | 633개 OK(건너뜀 14), rc 0 |
| `python -m unittest tests.test_design` | 29개 OK | 33개 OK(`ContrastTest` 8건: 알려진 값, 기준·문구, 필수 쌍·기준 4.5/3.0 고정, 경계값 4.5·3.0 통과/4.4999·2.9999 실패, 지정 쌍 통과, W5 이전 미달 쌍·기준 집합, 반투명 글자색 실패, 반투명 합성 보고) |
| `python scripts/check_design.py --colors-only` | 색 비교·명암비(62쌍) 통과, rc 0 | 색 비교·명암비(67쌍) 통과, 반투명 합성 17건 보고, rc 0 |
| `python scripts/check_design.py --platform windows` | 100% 최대 1062×673 ≤ 1366×689, 125% 최대 1062×678 ≤ 1536×785, 종합 rc 0 | 같음(색 비교·명암비 67쌍 통과, 반투명 보고 17건), 종합 rc 0 |
| `python scripts/check_kg_screen.py` | [OK] 14건, rc 0 | [OK] 14건, rc 0 |
| `python scripts/check_viewer.py` | 결과 통과, rc 0 | unittest 633개 OK 포함, 결과 통과, rc 0 |
| `node scripts/check_viewer_paths.js` | 불일치 0건, rc 0 | 도면 6개·사례 9560건·불일치 0건, rc 0 |

## 10. 최종 재검토 뒤 남은 한계(총괄)

- `TRANSLUCENT_STROKES`는 템플릿 JS `EDGE_COLOR`(`template.html:610`)를 손으로 옮긴 목록이다. 관계 종류가 늘면 합성 대비 보고에서 빠질 수 있다(보고 전용이라 영향 작음).
- 반투명 글자색 실패는 `color` 속성에만 적용된다. SVG 글자 `fill`(예: `.glabel`)은 대상이 아니다(현재 템플릿엔 해당 사례 없음).
- 총괄 수정(Codex 재검토): `stroke-opacity`의 백분율(`50%`) 해석, 알파를 [0,1]로 제한(음수·1 초과 입력 방지). 회귀 테스트 추가.

