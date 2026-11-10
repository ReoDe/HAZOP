# W9 뷰어 색 허용 목록 비우기(2색 통일)

> 구현 일시: 2026-11-06 · 대상: `feat/next-units` HEAD `3231a54` + W9 작업 트리 · 작업: hazop-developer · 결정: [D15](../decisions.md)(총괄 결정, 권고안, 사용자 위임 2026-11-06)

## 1. 바꾼 것

D5 열린 항목(허용 목록 2색)을 권고안대로 닫았다. 하드코딩 색 3곳을 기존 앱 토큰으로 바꾸고 `VIEWER_COLOR_ALLOW`를 비웠다. 맞는 토큰이 이미 있어 `hazop/app/tokens.py`는 바꾸지 않았다(새 토큰 0개).

| 위치(`hazop/viewer/template.html`) | 전 | 후 | 바탕 | 대비 전 → 후 | 기준 |
|---|---|---|---|---|---|
| `.chip.passed::before`(구조 검증 통과 점, 24행) | `#16a34a` | `var(--ok)` `#15803d` | `.chip` `--bg` `#f4f5f7` | 3.0212 → 4.5978 | 그래픽 3:1 |
| `aside .warn`(속성 패널 경고 글자, 62행) | `#b45309` | `var(--warn-ink)` `#92400e` | `aside` `--card` `#ffffff` | 5.0216 → 7.0900 | 글자 4.5:1 |
| `#pathq .res .bad`(경로 질의 경고 글자, 122행) | `#b45309` | `var(--warn-ink)` `#92400e` | `.float` `--card` `#ffffff` | 5.0216 → 7.0900 | 글자 4.5:1 |

- 토큰 선택 근거: `--ok`는 앱 통과 칩 글자(`qss()` `QLabel#chip[state="passed"]`)와 같은 의미이고 [W1 §2](w1-survey.md) 표가 "값 다름(용도 같음)"으로 짝지었다. `--warn-ink`는 앱 경고 칩·경고 띠 글자와 뷰어 `.chip.alignwarn` 글자에 이미 쓰는 경고 글자 토큰이다. 디자인 시안(`디자인/시안/interface-mockup.html:122`, `kg-graph-mockup.html:85`)도 통과 점을 `var(--ok)`로 그린다.
- `:root`에 `--ok: #15803d` 1개를 더했다(`--warn-ink`는 W4부터 있음). D5 ①에 따라 앱 `web_css()` `:root` 값과 같다.
- 바탕 확인: `aside { background: var(--card) }`(51행), `#pathq`는 `class="float"`(165행)이고 `.float { background: var(--card) }`(33행).

## 2. 검사·테스트

- `scripts/check_design.py`: `VIEWER_COLOR_ALLOW = {}`(기능은 남김 — (선택자, 속성, 값) 단위 판정). 출력 문구 "허용 목록 0곳".
- 대비 쌍(`CONTRAST_PAIRS`) 67 → 66쌍: `("#b45309", "card", TEXT)` 삭제 — 같은 쓰임은 기존 `("warn-ink", "card", TEXT)` 쌍이 맡도록 쓰는 곳 설명에 뷰어 경고 글자를 더했다(쌍 중복 금지 테스트 때문에 새 쌍을 만들지 않음). `("#16a34a", "bg", GRAPHIC)` → `("ok", "bg", GRAPHIC)`. 이제 `#` 리터럴 쌍은 없다.
- `tests/test_design.py`:
  - `test_allow_list_is_empty`(새): `VIEWER_COLOR_ALLOW == {}`(다시 채우면 실패), W8까지 허용하던 3조합이 이제 실패.
  - `test_allow_list_is_rule_bound`(고침): 목록을 `mock.patch.dict`로 임시로 채워 같은 규칙만 통과·다른 선택자는 실패하는지 확인하고, 끝난 뒤 목록이 비어 있는지 확인.
  - `test_pre_w4_template_fails`: W4 이전 템플릿 실패 10 → 13건(허용 목록이 사라져 `#16a34a` 1·`#b45309` 2건이 더해짐)과 그 3건을 따로 확인.
  - `ContrastTest.REQUIRED_*`: `#b45309`/`card` 삭제(=`warn-ink`/`card`가 대신), `#16a34a`/`bg` → `ok`/`bg`.

## 3. 영향

- 독립 뷰어: 통과 점이 조금 어두운 초록, 경고 글자가 더 어두운 갈색이 된다. 대비는 세 곳 모두 올라갔다.
- 앱 안 ② 뷰어: `web_css()`가 `:root`를 `COLORS` 전체로 덮어쓰지만, 전에는 세 규칙이 리터럴이라 덮어쓰기가 닿지 않았다. 이제 `var()`라 앱 안에서도 `#15803d`·`#92400e`로 보인다(앱 ①~⑤ Qt 화면의 `qss()`·`web_css()` 출력은 바뀌지 않음 — `tokens.py` 무변경).
- ③ 지식그래프·앱 코드 색 리터럴 검사: 해당 없음.

## 4. 검증 결과(전용 venv `%USERPROFILE%\.hazop\venv-py312`, Python 3.12.10, 2026-11-06 11:2x)

| 명령 | 결과 |
|---|---|
| `python -m unittest tests.test_design` | 60개 OK, rc 0(첫 실행은 `test_pre_w4_template_fails` 13 ≠ 10 실패 → 기대값 갱신) |
| `python scripts/check_design.py --platform windows --out <스크래치>` | 색 비교 통과(허용 목록 0곳), 명암비 통과(66쌍), 반투명 관계선 통과(7종), 앱 코드 색 리터럴 없음, 100%·125% 배치 통과, 종합 rc 0 |
| `python scripts/check_kg_screen.py --screenshots <스크래치>` | [OK] 14건, 결과 통과, rc 0 |
| `node scripts/check_viewer_paths.js` | 도면 6개·사례 9560건·불일치 0건, rc 0 |
| `python -m unittest discover -s tests -t .` | 690개 OK(건너뜀 5), rc 0 |
| `python scripts/check_viewer.py`(저장소 기본 경로, `출력/` 재기록) | unittest 691개 OK(건너뜀 5 — 동시 작업 중인 다른 담당의 테스트 추가분 포함), 결과 통과, rc 0 |

## 5. 남은 한계

- 렌더 화면 비교는 하지 않았다. 색 값·대비는 계산으로 확인했고, 실제 보이는 차이는 [추론]이다.
- 통과 점(글리프 ●)은 W5와 같이 그래픽 3:1로 판정했다. `ok`/`bg` 4.5978이라 글자 기준 4.5:1도 넘는다.
- `VIEWER_COLOR_ALLOW` 기능은 지우지 않고 비워 두었다. 다시 채우려면 `test_allow_list_is_empty`를 함께 고쳐야 하므로 결정 없이 허용 목록이 늘어나지 않는다.
- `기획서/인터페이스.md`·`디자인/`에 고칠 문구는 찾지 못했다(두 곳 모두 `#b45309`·허용 목록 언급 없음, 시안은 이미 `var(--ok)`).
