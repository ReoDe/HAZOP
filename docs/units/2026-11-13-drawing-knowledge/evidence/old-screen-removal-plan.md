# 이전 화면 제거 계획 (지우지 않고 계획만)

조사: 2026-11-14, 하위 세션 S-removal-plan(Sonnet 5.5 medium). 기준은 HEAD `3975518` 작업트리다. **코드는 하나도 고치지 않았다.** 지우는 일은 사용자 확인 뒤에 한다. 이전 화면은 `hazop/app/`의 PySide6 위젯 화면(`MainWindow`와 `screens/`)이고, 새 화면은 `hazop/shell/`(웹 화면)이다.

기능 대응 조사는 폴더를 셋으로 나눠 Sonnet 하위 에이전트가 맡았고, 결과 표 원본은 이 문서 3번에 합쳐 두었다. 판정은 코드에서 grep으로 확인한 것이고, 확인하지 못한 것은 '추측'이라고 적었다. **설계 문서(`docs/design/app-shell-web.md`)가 "옮겼다"고 적었어도 코드에 없으면 '없음'으로 셌다.**

## 먼저 알아 둘 것

- 새 화면은 이전 화면 폴더 코드에 **많이 기대고 있다**(1번 표). 폴더를 그냥 지우면 새 화면도 뜨지 않는다. 먼저 옮겨야 한다.
- 새 화면에 없는 이전 화면 기능이 **목록(완료 목록 2, A1~A19) 밖에도 여럿 있다**(3번 표). 지우기 전에 사용자가 "버린다/만든다"를 정해야 한다. 가장 큰 것은 AI 구간 검토(구간 나누기 보조), 도면 연결 짝 지정, 스크리닝 제외, 보호수단 인정, 명령 팔레트다.
- A5(도면 고치기)는 완료 목록에는 '없음'인데 코드(`edit.js`, `api_corrections.py`)에는 이미 들어와 있다. 목록의 '지금' 칸이 옛 것이다(추측이 아니라 코드 확인).
- 설계 문서가 약속했는데 코드에 없는 것: 명령 팔레트(위 막대 찾기 상자), Alt+←/→ 뒤로·앞으로, 지식그래프 '보기 설정', 말풍선 '더 보기'(관련 항목). 문서를 고치거나 기능을 만들거나 둘 중 하나가 필요하다.

---

## 1. 새 화면이 이전 화면 폴더에서 불러 쓰는 것

`hazop/chat/`, `hazop/study/`, `hazop/extract/`, `hazop/ie/`는 `hazop.app`을 **import하지 않는다**(grep 확인). 불러 쓰는 곳은 `hazop/shell/`, `hazop/kg/`, `hazop/register/`, `hazop/export/`, `hazop/viewer/`, `scripts/`, `packaging/`, `tests/`이다. 방향이 거꾸로(`hazop/app` → `hazop/shell`)인 곳도 있다: `app/__init__.py:16`, `app/startup.py:293`.

### 1.1 엔진 폴더(제품 코드)

| 호출하는 곳 | 불러 쓰는 것 | 무엇을·왜 |
| --- | --- | --- |
| `hazop/shell/api.py:184,676,703,718`, `api_aireview.py:49`, `api_docs.py:25`, `chat_actions.py:188,561,901`, `clean_items.py:239`, `register_flow.py:11`, `sheet_refresh.py:58,98` | `app.data` | 등록 목록·추출·그래프 만들기·문서 추출·교정 저장 등 **엔진 접착 함수**. 새 화면 엔진 명령의 몸통이다 |
| `hazop/shell/api.py:188,199,663`, `api_actionlog.py:57`, `api_corrections.py:192,348`, `api_kg.py:87`, `api_nodes.py:35`, `api_results.py:31`, `sheet_refresh.py:74` | `app.project_ctx` | 프로젝트 그래프(`project_graph`)·그래프 이름(`graph_names`)·구간 파일 이전. 공용 |
| `hazop/shell/api.py:709-730` | `data.viewer_build`→`hazop/viewer/build` (`load_graph`, `_svg_path`, `prepare_svg`) | 도면 SVG를 새 화면에 주는 길. 뷰어 폴더의 일부는 **계속 쓴다** |
| `hazop/shell/api.py:602` | `app.icons` | 아이콘 이름 목록 |
| `hazop/shell/api.py:651` | `app.main_window.APP_VERSION` | 버전 글자. **`main_window.py`를 지우면 `state` 읽기가 깨진다** |
| `hazop/shell/api_settings.py:51` | `app.conn_view` | 연결 상태 → 글·해결 동작 표 |
| `hazop/shell/window.py:22,28,101,142-163,236` | `app.webview`(`LocalPage`, `MAX_MESSAGE_CHARS`, `QWebEngineProfile`, `_qwebchannel_js`), `app.icons` | 새 창의 웹뷰 바탕. 같은 파일에 이전 `HazopWebView`·`Bridge`가 섞여 있다 |
| `hazop/shell/window.py:222-223,413` | `app.tokens`, `app.ai_conn.AiConnection`, `app.settings_dialog.ACTION_HELP/show_help` | 색 토큰, AI 연결 객체, 로그인·설치 안내 글 |
| `hazop/shell/analysis_run.py:123`, `api_results.py:501` | `app.screens.results.design_intent` | 구간의 설계 의도 찾기 함수 하나. **지울 화면 파일 안에 있다** |
| `hazop/shell/scheme.py` ← `app/__init__.py:16` | (거꾸로) 앱이 shell을 부른다 | `make_application`이 shell 체계를 등록 |
| `hazop/kg/screen.py:20` | `app.tokens` | 색 |
| `hazop/export/study_xlsx.py:30-31` | `app.conn_view`(`api_cost`, `drafted_cells`, `provenance`), `app.tokens`(`COLORS`, `risk_band`) | Excel 내보내기의 비용·출처·색 |
| `hazop/register/titleblock.py:63,432` | `app.data` | 표제란 후보 읽기 |
| `hazop/viewer/build.py:13` | `app.tokens` | 독립 뷰어 색 |
| `hazop/paths.py:324` | 주석만 | 코드 아님 |

### 1.2 `scripts/`·`packaging/`

| 파일:줄 | 불러 쓰는 것 | 무엇을 |
| --- | --- | --- |
| `scripts/run_app.py:55,60,75,81,90` | `startup`(`check_settings`, `offer_work_root_move`, `single_instance`, `window_kind`), `make_application`, `main_window.MainWindow`, `screenshots.take_all` | **제품 시작 길.** `--classic`·`--screenshots`·`--run`이 이전 화면을 연다 |
| `scripts/migrate_names.py:385` | `startup.LOCK_NAME` | 단일 실행 잠금 이름 |
| `scripts/check_layout.py:34`, `check_edit_screen.py:35`, `check_work_root_counts.py:59`, `check_kg_context.py:765` | `app.data`, `related`, `runctx` | 엔진 검사. 옮기면 된다 |
| `scripts/check_app.py:30-52`, `check_design.py:152,221,232,437,770,899,1258,1542`, `check_kg_renderer.py:207,226`, `check_kg_screen.py:127,251-261`, `check_edit_screen.py:72-73`, `check_user_scenarios.py:1500-1532`, `bench_results_screen.py:72-73` | `make_application`, `MainWindow`, `HazopWebView`, `ElidedLabel`, `tokens`, `STEPS` | **이전 화면을 띄우는 검사** |
| `scripts/shoot_*.py` 9개(`shoot_ai_connection/ai_run/expectations/initiating/project_kg/results/stage_explorer/study_refs/uiux`) | `make_application`, `MainWindow`, `screenshots`, `screens.results.EntryDialog`, `settings_dialog` | 이전 화면 캡처 |
| `packaging/verify_bundle.py:248,340`, `w4_flow.py:169` | `TRANSLATION_FAILED`, `app.data` | 묶음 검사. 줄 20·74-78은 이전 화면 PNG(레일 단계)를 기대한다 |

### 1.3 `tests/`

`hazop.app`을 import하는 시험 파일은 **71개**다. 엔진 값만 쓰는 것(Qt 없음)과 이전 화면을 띄우는 것으로 갈린다(4번 표).

---

## 2. 옮길 것과 지울 것 (`hazop/app/` 35개 파일)

본문 괄호의 줄 수는 빈 줄을 뺀 근사치이고, 6번 표는 `wc -l`이라 더 크다.

이름·위치는 `docs/governance/naming-rules/README.md`(HZ-GOV-02) §4를 따라야 한다. 아래 제안 위치는 **추측**이며, 확정은 §4.2·§4.3과 맞대어 총괄이 한다. 총괄이 예로 든 `hazop/core/`로 적었다. `data`는 100곳 넘게 `from hazop.app import data`로 불리므로 옮기는 단계는 `scripts/migrate_names.py`로 한다(손으로 고치지 않는다).

### (가) 화면과 무관해 옮길 것

| 지금 | 제안 자리 | 이유 |
| --- | --- | --- |
| `app/data.py`(618) | `hazop/core/data.py` | 엔진 접착. `viewer_html_for`는 아래 뷰어 결정을 따른다 |
| `app/project_ctx.py`(287) | `hazop/core/project_ctx.py` | 프로젝트 그래프·구간 파일 이전 |
| `app/related.py`(247) | `hazop/core/related.py` | `progress_table`·`DrawingIndex`를 시험·검사가 씀. 새 화면은 아직 안 부르나 5섹션 관련 항목을 만들면 필요(3번) |
| `app/runctx.py`(90) | `hazop/core/runctx.py` | `check_kg_context`·`test_kg_review`가 씀 |
| `app/ai_conn.py`(199) | `hazop/core/ai_conn.py` | 새 창이 그대로 얹는다. `widgets.TaskRunner`에 기댄다 |
| `app/conn_view.py`(500) | `hazop/core/conn_view.py` | `api_settings`·`study_xlsx`가 씀 |
| `app/icons.py`(106), `app/tokens.py`(256) | `hazop/core/` | 새 창·kg·viewer·export가 씀. 아이콘은 Qt 부분(줄 107~)이 있다 |
| `app/startup.py`(260) | `hazop/core/startup.py` | 설정 확인·옛 작업 폴더 옮기기·단일 실행. **`window_kind`·`run_shell`의 이전 화면 전환 줄(271-306)은 지운다** |
| `app/__init__.py`(40) | `hazop/core/__init__` 또는 `make_application`만 | `make_application`, `TRANSLATION_FAILED`. shell을 부르는 줄(16)은 새 방향이라 그대로 |
| `app/webview.py`(940) 일부 | 나눈다 | `LocalPage`·`LocalOnlyInterceptor`·`ALLOWED_SCHEMES`·`MAX_*`·`clean_*`·`_qwebchannel_js`는 새 창이 쓴다(~줄 1-234). `Bridge`·`BRIDGE_JS`(235-767)·`VIEWER_CSS`·`HazopWebView`(818~)는 이전 도면 뷰어 전용이라 지운다(추측: `Bridge`에 새 창이 기대는 것이 없는지 이동 단계에서 다시 확인) |
| `app/widgets.py`(259) 일부 | `TaskRunner`(200-250)만 `hazop/core/`로 | `ai_conn`이 씀. 나머지(`ElidedLabel`, `Chip`, `Banner`, `Toast`, `badge` …)는 위젯이라 지운다. 단 `kst_text`·`write_log`·`log_path`는 이전 설정창 전용인지 확인(추측) |
| `app/settings_dialog.py`(846) 일부 | `HELP`·`ACTION_HELP`·`show_help`(31-103)만 | 새 창이 로그인·설치 안내를 이 글로 띄운다. 나머지는 지운다 |
| `app/main_window.py` 일부 | `APP_VERSION`·`APP_NAME` 상수 | `api.py:651`, `lock_probe.py:33`이 씀 |
| `app/screens/results.py` 일부 | `design_intent`(59-84) | `analysis_run`·`api_results`가 씀. `hazop/study/`로 옮기는 것이 맞다(추측) |

### (나) 이전 화면에만 쓰여 지울 것

- `app/screens/` 전부: `ai_review_panel`, `analysis`, `initiating`, `knowledge`, `register`, `results`, `results_matrix`, `results_paint`, `review`, `study`, `viewer`, `__init__`(합계 약 10,000줄).
- `app/main_window.py`, `chat_panel.py`, `conn_widgets.py`, `explorer.py`, `palette.py`, `related_panel.py`, `render.py`, `screenshots.py`.
- `app/webview.py`·`widgets.py`·`settings_dialog.py`의 위 (가)가 아닌 부분.
- 시험·검사·캡처 스크립트 중 이전 화면을 띄우는 것(4번 표).

### (다) 판단이 필요한 것

| 대상 | 쟁점 | 권장안(추측) |
| --- | --- | --- |
| `hazop/viewer/`의 `template.html`(1094), `check.py`(182), `build.py`(149), `sanitize.py`(176), `scripts/build_viewer.py`(43), `check_viewer.py`, `run_samples.py` | 이전 화면 도면 뷰어의 HTML 템플릿이자 **독립 뷰어 HTML 내보내기**(`build_package.py:70`이 묶음에 넣는다). 새 화면은 `load_graph`·`_svg_path`·`prepare_svg`만 쓴다 | 독립 HTML 뷰어를 계속 낼지 사용자가 정한다. 안 낸다면 `build.py`에서 3개 함수만 남기고 `template.html`·`check.py`를 지운다. `data.viewer_html_for`·`runctx.viewer`도 같이 정리 |
| `app/ai_runner.py`(152) | 새 `shell/analysis_run.py`(Qt 없음)가 규칙을 옮겼으나, `remaining`(이어서 실행)·kill·작업자 N개는 안 옮김(3번) | 이어서 실행을 만들지 정한 뒤 지운다 |
| `scripts/check_design.py`(1598) | 색 토큰·1366 레이아웃·`hazop/app/**` 색 리터럴 검사. 이전 화면 검사와 토큰 검사가 한 파일 | 토큰·색 검사는 남기고 위젯 검사만 지운다(분리 필요) |
| `scripts/check_kg_screen.py`(544), `check_kg_renderer.py`(356) | 이전 지식그래프 화면 검사. `kg/screen.py`는 새 패널도 쓴다 | 새 패널 시험(`test_shell_kg*`)이 대신하는지 확인 후 결정 |
| `scripts/check_user_scenarios.py`(1703)와 `verify-hazop` 스킬 | 실제 창 시나리오 S1~S15가 **이전 화면**을 운다 | 새 화면용으로 다시 써야 한다(4번) |
| `app/explorer.py`(278), `palette.py`(143), `related_panel.py`(105) | 지우되 3번 기능은 사용자가 정해야 한다 | 3번 결정 뒤 |

---

## 3. 새 화면에 아직 없는 이전 화면 기능

판정: **있음**은 줄였고, **없음**·**부분**만 적는다. 새 화면 근거를 확인한 곳은 표의 '근거'이다. 'A번호'는 완료 목록 2이고, A번호가 없는 것은 **목록 밖**이다. "지운 뒤 기능이 사라졌다"가 나올 수 있는 쪽은 **목록 밖**이다.

집계(조사원 보고): 1묶음(register·study·viewer·analysis·review) 없음 25·부분 23, 2묶음(results·initiating·knowledge·ai_review_panel) 없음 23·부분 43, 3묶음(창 틀·설정·채팅·탐색기·팔레트·관련 항목·시작) 없음 30·부분 38. 이 가운데 사소한 것(키 하나, 열 하나)이 절반쯤이다. 아래는 **사용자 결정이 필요한 것**을 먼저, 경미한 것은 뒤에 한 줄씩 모았다.

### 3.1 목록 밖이고 중요한 것 (지우기 전에 "만든다/버린다"를 정해야 한다)

| # | 이전 화면 기능(파일:줄) | 판정 | 근거 | 영향 |
| --- | --- | --- | --- | --- |
| 1 | **AI 구간 검토**: 전체·한 구간 실행, 호출 수·시간·사용량 확인, 진행·멈추기, 제안 목록 받기·고쳐 받기·기각·되돌리기(`study.py:1585-1810, 1307-1580`) | 없음 | `node_review`를 쓰는 새 화면 코드는 읽기(`api_results.py:391,503`)뿐. 채팅 동작에도 없음. 설계서 §2.3은 '채팅 진행 표시'로 옮긴다고 했으나 코드 없음 | 구간 나누기를 AI가 돕는 길이 사라진다 |
| 2 | **도면 연결 짝 지정·연결 끊기**(미연결 연결점의 짝을 사람이 고름, 지정 사유·사람 기록, 오래됨 안내)(`viewer.py:351-410, 708-774`) | 없음 | `project.save_manual`을 부르는 새 코드 없음, 명령 목록에 없음 | 자동으로 못 이은 도면 연결을 사람이 고칠 길이 없다(A13은 '부분') |
| 3 | **구간 스크리닝 제외**(옮기기·꺼내기·이유, 확정 때 확인, 목록 등급 표시)(`study.py:149-150, 1176-1210, 1283-1300`) | 없음 | `nodes.*`에 명령 없음. `api_nodes.py:135`가 값을 내려도 화면이 안 쓴다. 분석(`api_results.py:63-70`)은 이 값으로 행을 거른다 | 제외를 바꿀 길이 없는데 분석은 그 값을 쓴다 |
| 4 | **분석에서 범례·기호표 도면 빼기·다시 넣기**(`register.py:287, 460-480`) | 없음 | `chat_actions.py:31` NOT_YET에 "생기면 잇는다"로 적혀 있다. 엔진(`study/nodes.py:962,968`)은 남아 있다 | 범례 도면이 구간 분석에 섞인다 |
| 5 | **보호수단 인정(빈도 낮추기) 체크와 근거**, 보호수단 추가·제거·참조 편집, 설계 의도·AI 근거(경로·출처 문서·⚠) 열(`review.py:105-132,350-382`, `results.py:107-158,228,282-343,2098-2139`) | 없음 | `results.edit_entry`는 원인·결과·권고·강도·빈도만. `cause_kind`가 내려오나 화면이 안 씀 | 위험도 판정의 근거를 화면에서 못 본다·못 고친다 |
| 6 | **명령 팔레트 Ctrl+P**(구간#·구성요소@·명령>, 퍼지·최근)와 도면 구성요소 찾기(`palette.py`, `main_window.py:1193`) | 없음 | `web/js`에 palette 0건. 설계서 §2.3은 '위 막대 찾기 상자'라 했으나 코드 없음 | 키보드 중심 탐색이 없다 |
| 7 | **관련 항목 5섹션**(도면 위치·구성요소·지식그래프 근거·같은 구성요소를 쓰는 다른 칸·변경 이력)과 말풍선 '더 보기'(`related_panel.py`, `related.py:14`) | 없음 | 말풍선(`sheet_host.js`)에 '분석 결과 추적'·'고치기'뿐 | 지식 근거로 가는 지름길이 줄었다 |
| 8 | **AI 연결**: Claude Code 프로그램 위치 지정(`settings_dialog.py:783`), 구독 사용량·5시간/주간 한도·초기화 시각 줄(`conn_view.py:225`), API 키 이름 바꾸기 단추, 연결 막힘 자동 안내 | 없음/부분 | `settings.js`에 limit·사용량 없음(`api_settings`는 값을 내려 준다), `rename_key` 명령만 있고 단추 없음 | PATH에 없으면 구독 연결을 지정할 수 없다. A8 '구독·API 상태 표시'의 남은 부분 |
| 9 | **API 키·고정 응답 방식으로 분석**, '이어서 실행'(남은 칸·API 키로 이어서), 사용량 초과 확인, 예상 비용($), 방식 바꿔 이번만 실행(`results.py:512-596,1421-1556,1912-1943`, `conn_view.py:536-578`, `ai_conn.py:216`) | 없음 | `analysis_run.py:6`이 "이전 화면에 남는다. 4단계에서 정한다"고 적었다 | 구독이 막혔을 때 API 키로 이어 갈 길이 없다 |
| 10 | **초기사건 추적 패널**(소속 후보 → 편차 → 원인 → 위치·고장모드 → IE 판정 → 그룹 → 최종상태 → 근거 경로)과 후보별 IE 판정(교란·도전)(`initiating.py:775-790,351-357`), 항목별 초기사건 판정 단추(`results.py:384-436`) | 없음 | `ie*.js`·`api_ie.py`에 trace·교란·도전 0건. A10은 그룹 편집·범주 대조만 다룸 | 초기사건의 근거를 따라가는 길이 없다(INTENT §3.7의 핵심일 수 있음: 추측) |
| 11 | **지식그래프 알고리즘 A1~A3(도달 범위·고아·근거 공백·연결 수)**, 보기 설정(종류·관계 체크, 고아·근거 공백 강조, 접기, 깊이, 힘, 색)(`knowledge.py:978-998`, `screen_template.html:70-105`) | 없음 | `kg*.js`에 algo·orphan·depth 0건. 설계서 §2.3 약속과 다름. A6은 '옵시디언식 보기'라 일부는 의도적 단순화(2026-11-14 사용자: 단순하게) | 사용자가 단순함을 원하니 '버린다'일 가능성이 크다. 확인 필요 |
| 12 | **검토 층**(시나리오·보호수단·IE를 지식그래프에 투영) 노드·관계, 링크 클릭 상세(`knowledge.py:534-592, 901-955`) | 없음 | `api_kg`에서 study 층 구성 호출 없음, `onLinkClick` 없음 | 위와 같음 |
| 13 | **창 닫을 때 분석 기다리기**(기다렸다 닫기/바로 끊기), 결과 파일 위치·저장 시각, 옛 도면별 결과 이전 안내(`results.py:630-665, 1263-1283, 1167-1181`) | 부분/없음 | `window.py:BUSY_TEXT`가 분석·등록·내보내기 도는 중 닫기를 묻는다(부분). 위치 표시·이전 안내는 없음 | 닫을 때 작업 손실은 막혀 있다 |

### 3.2 완료 목록 안에 있는데 아직 없는 것 (지우기 전에 끝나 있어야 하는 것)

| A | 내용 | 코드 상태 |
| --- | --- | --- |
| A5 | 도면 고치기 | **이미 있음**(목록 '지금' 칸이 옛 것). 전부 아님: 한 번에 전부 버리는 '저장본으로 되돌리기' 단추 없음(사소) |
| A8 | 구독·API 상태 표시 | 구독 사용량 없음, 칩 팝업·해결 띠 없음 |
| A9 | 행렬 건너뛴 이유, Excel 범위 | 범위 3종은 구현. '한도로 멈춤 n'·'스크리닝 제외 n개'·진행 막대·경과·토큰·비용 없음 |
| A11 | 채팅으로 앱 기능 | 구간 동작 외 확대 중. 팔레트 대신 채팅이라는 설계가 서려면 필요 |
| A12 | 행동 기록 보기 | `actionlog` 패널 있음 |
| A13 | 여러 도면 구간 표기·다른 도면 칩 | 구간 표기·칩 있음. 도면 패널의 '도면 연결 n' 목록·짝 지정은 없음 |
| A14 | 1366×768, 큰 도면 성능 | 채팅 폭은 고정 380px(끌기·저장 없음) |

### 3.3 경미한 것 (한 줄씩)

- 단축키: 결과 J·A·R·E·I, 초기사건 G·M·S·Ctrl+Enter·Ctrl+R, 구간 M·F2(코드에는 단추 title만), Alt+←/→ 뒤로·앞으로, 전역 Ctrl+Z와 토스트 [되돌리기]·[열기]·[폴더 열기], `?`/F1 단축키 표.
- 창 틀: 단계 ✓ 표시, 상태줄(구간·미검토·실패 수, 저장됨 HH:MM, 연결 막힘 알림), 위 막대 검토자 표시, 프로젝트 목록에서 고르기(지금은 ID를 직접 침), 정보 화면의 데이터 위치·라이선스 폴더 열기, 오류 복사·로그 폴더 열기.
- 등록: 등록 전 미리보기·식별정보 입력, 재사용·새 버전 구분 표시, 쪽별 건너뛴 사유, 자료 목록 열(자료 ID·시각·개정), '다시 시도' 단추, 도면 행의 직접 '추출 다시' 단추.
- 구간: '속한 구간' 탭, 구간 상세 '⑤ →', 구간 목록의 '미포함' 구성요소 목록.
- 결과: 행 머리 툴팁, 변수로 묶는 두 단 열 머리, 위험도 수용·조건부·불허 문구, 항목별 '범위 바뀜'·'옛 결과' 표지, 'AI 초안 n건' 칩, 지식그래프 없음 칩.
- 초기사건: 후보 표 '배정 작성'·'판정 작성' 열, 읽기 화면의 대표 후보·완화계통, 기본사건 기기 태그·계통 열, 확정 조건 n/m 칩, 출처 빗금.
- 지식그래프: 검증·충돌·계산 제외 칩과 버전 정보, 차단 항목 목록·'이전 버전 보기', 분석 당시 kg_version 대조, 도면 경계 경로(채팅 도구 `trace_path`가 대신), 상세 패널 접기.
- AI 검토: 대상 쪽 선택(모든 쪽/첫 쪽만), 진행 막대·멈추기 단추(작업 줄이 대신하는지는 추측), 여러 행 한꺼번에 수락.
- 이전 MVP(`analysis.py`·`review.py`, 고정 응답 분석·설계보완 후보·시나리오·근거 묶음·실행 열기·`--run`): 설계서가 '삭제 시점에 정한다'고 보류한 것. 전부 '없음'이며 **사용자가 버린다고 확인하면 그대로 지운다**(엔진 `hazop/analysis/`은 위험도 표 때문에 남는다: `api_results.py:15`).

---

## 4. 지우면 깨지는 것

### 4.1 시험(`tests/test_*`) 71개

가름은 **한 파일씩 열어 보지 않은 어림**이다(추측). 확정은 이동 단계에서 `Qt를 쓰는지`·`이전 화면 클래스를 import하는지`로 다시 가른다. 이전 화면을 띄우는 시험 약 35개, 엔진·새 화면 시험 약 36개다.

| 갈래 | 파일(어림) |
| --- | --- |
| **엔진 시험으로 남길 것**(Qt 없음, `data`·`project_ctx`만 import. 이동 때 import만 고친다) | `test_clean_items`, `test_corrections`, `test_cross_drive`, `test_dexpi_import`, `test_extraction_run`, `test_progress_table`, `test_project_ctx`, `test_register`, `test_titleblock`, `test_store_conflicts`, `test_workroot`(LOCK_NAME), `test_shell_actionlog`, `_aireview`, `_chat_actions`, `_chat_flow`, `_chat_review`, `_clean_flow`, `_corrections`, `_docs`, `_docs_flow`, `_ie`, `_ie_edit`, `_ie_flow`, `_kg`, `_kg_flow`, `_nodes`, `_project`, `_results`, `_results_flow`, `_sources`, `_settings`, `_titleblock`, `_scheme`, `_web`, `test_icons` |
| **새 화면 시험으로 대신할 것**(이전 화면의 같은 기능을 새 화면 시험이 이미 덮는지 확인 뒤 지움) | `test_register_ui`→`test_shell_*`, `test_study_screens`·`test_study_project_ui`·`test_study_review_ui`→`test_shell_nodes`, `test_results_hold`·`test_results_project_ui`→`test_shell_results*`, `test_ie_screen`→`test_shell_ie*`, `test_kg_expect`·`test_kg_screen`→`test_shell_kg*`, `test_ai_review_ui`→`test_shell_aireview`, `test_chat_panel`·`test_chat_frame`·`test_chat_integration`→`test_shell_chat_*`, `test_viewer_api`·`test_viewer_edit`·`test_viewer_links`→`test_shell_corrections`·`_sources`, `test_ai_screen`·`test_ai_run_flow`·`test_ai_key`·`test_ai_connection_ui`→`test_shell_settings`(구독 외 API 키는 3번 9번 결정에 따름) |
| **섞여 있어 쪼갤 것**(앞부분은 엔진, 뒤는 이전 화면) | `test_app`(1072줄), `test_app_startup`(startup은 남김), `test_design`(tokens 검사는 남김), `test_packaging`(1933줄, Qt 92곳), `test_shell`(`MainWindow` 사용: 이름과 달리 이전 화면 연결 시험), `test_workroot_app`·`test_workroot_review`·`test_startup_caches`(작업 폴더 규칙은 남기고 창은 지움), `test_pid_classes`(screens import), `test_kg_review`·`test_kg_renderer`·`test_graph_select`·`test_display_layout`·`test_run_ci_watch` |
| **지울 것**(위젯 전용 부분) | `test_window_defects`의 `RAIL_W`·`MainWindow` 부분, `test_viewer_*`의 위젯 부분 |

### 4.2 스크립트·스킬

| 대상 | 영향 |
| --- | --- |
| `scripts/check_user_scenarios.py` S1~S15, `verify-hazop` 스킬(`.claude/skills/verify-hazop`) | 이전 화면의 UIA 위젯·`MainWindow`·`screenshots.wait`를 직접 쓴다. **새 화면용(웹 CDP)으로 다시 써야 한다.** 당분간 실제 창 검증이 없다 |
| `scripts/run_app.py` | `--classic`, `--screenshots`, `--run`, `startup.window_kind` 정리. 새 화면 스크린샷 길이 없으면 `--screenshots`도 같이 사라진다(`--chat-tools`는 남김) |
| `scripts/shoot_*.py` 9개, `check_app.py`, `check_edit_screen.py`, `bench_results_screen.py` | 이전 화면 전용. 지운다. 새 화면 캡처는 `docs/units/…/evidence/`의 구동 스크립트가 대신 |
| `scripts/check_design.py` | 3(다) 참고. 색 리터럴 검사 대상이 `hazop/app/**`라 폴더를 옮기면 대상도 고쳐야 한다(`hazop/core/`로) |
| `scripts/build_package.py`(`70`: `hazop/viewer/template.html`), `packaging/verify_bundle.py`(레일 PNG `APP_PNG`, `--screenshots`), `packaging/w4_flow.py:213`(`viewer_html_for`), `packaging/lock_probe.py:33`(`APP_NAME`) | 묶음 파일 목록과 검사가 이전 화면 PNG·템플릿을 기대한다 |
| 설정 `ui_shell`, `api.py:398,493-520` `app.open_classic`·`settings.set_default_shell`, `window.py:257,270,416-421` `_open_classic`, `settings.js` '이전 화면 열기', `startup.py:271-306` | 이전 화면이 없으면 이 줄들을 없앤다. 설정 파일에 남은 `ui_shell` 값은 읽고 버린다(호환) |

### 4.3 문서(이전 화면을 가리키는 곳)

`docs/design/screen-spec.md`(442줄), `ai-connection-screens.md`, `kg-screen.md`, `mockups/` 일부, `app-shell-web.md`(§6·UW9), `docs/specs/{chat-panel,interface,kg-schema,extraction,…}.md`, `docs/units/2026-11-05-*/evidence/*`(역사 기록), `docs/records/{decision-log,backlog}.md`, `docs/governance/naming-rules/README.md`와 `evidence/`. **역사 기록(`docs/units/2026-11-05-*`, 결정로그)은 고치지 않는다.** 규격(`docs/specs/`·`docs/design/`)만 "이전 화면"을 "새 화면"으로 고치거나 `obsolete`로 둔다.

---

## 5. 차례

규칙 4: **다른 세션이 하나도 돌지 않을 때만** 하는 단계에 ⚠를 붙였다(저장소 전체 이동·이름 바꾸기).

| 단계 | 내용 | 커밋 단위 | 단계 뒤 검사 |
| --- | --- | --- | --- |
| 0 | 3번 결정 받기(**사용자**): 만든다/버린다. 지우기 확인. 독립 HTML 뷰어(2(다)) 유지 여부 | 없음 | — |
| 1 | 이전 화면에서만 쓰이는 것 만들기·정하기: 3.1에서 "만든다"로 정한 것(예: 짝 지정, 스크리닝 제외, 보호수단 인정)을 새 화면에 만든다 | 기능별 커밋 | 기능별 시험 |
| 2 | 새로 가르기: `app/webview`·`widgets`·`settings_dialog`·`main_window`·`screens/results`에서 (가)의 일부(`LocalPage` 등, `TaskRunner`, `HELP`, `APP_VERSION`, `design_intent`)만 새 자리로 뽑아 둔다. import는 아직 그대로 | `refactor:` | `tests.test_shell*` 전부, `scripts/check_work_root_counts.py` |
| 3 ⚠ | **옮기기**: (가) 파일을 `hazop/core/`로 `git mv`(`scripts/migrate_names.py` + `name-map.csv`, 링크 손으로 고치지 않음) | `refactor:` 하나 | `tests/test_naming_rules.py`, 시험 전체(`run_ci`), `check_apr1400.py`·`check_snp_baseline.py`(기준값 불변 확인) |
| 4 ⚠ | **import 고치기**: `hazop.app.X` → `hazop.core.X`(제품·스크립트·시험·패키징) | `refactor:` | 위와 같음 + `scripts/preflight.py` |
| 5 | **시험 옮기기**: 4.1의 '엔진 시험으로 남길 것'은 import만, '섞인 것'은 쪼갠다. '새 화면 시험으로 대신할 것'은 대응 시험이 있는지 표로 확인 | `test:` | `run_ci`(시험 모듈별 시간 한도 안), 시험 개수 차이 설명 |
| 6 | **지우기**: `app/screens/`, `main_window.py` 등 (나)를 지운다. `startup.window_kind`의 classic 길, `--classic`·`--screenshots`·`--run`, `ui_shell`·`app.open_classic` 정리 | `refactor:` | 시험 전체, `run_app.py`로 새 화면이 뜨는지(오프스크린), 묶음 import 검사 |
| 7 | **묶음·문서 정리**: `build_package.py` 파일 목록, `verify_bundle.py`·`w4_flow.py`·`check_user_scenarios.py`·`verify-hazop` 스킬을 새 화면용으로 다시 쓴다, 규격 문서 정리 | `ci:`·`docs:` | **배포본 빌드와 묶음 검사**(A16), 실제 창 검증(새 시나리오) |

이름 바꾸기 단계(3·4)는 `docs/governance/naming-rules/README.md` §7의 순서를 따르고, 한 단계를 마치면 `tests/test_naming_rules.py`의 `EXEMPT` 줄을 지운다.

---

## 6. 지울 파일 목록 (사용자에게 그대로 보여 확인받는 목록)

줄 수는 `wc -l` 기준이다(2026-11-14). **(가)로 옮길 부분이 있는 파일은 목록에서 '일부'로 표시했다.** 파일 전체를 지우는 것은 '전부'다.

| 구분 | 경로 | 줄 수 |
| --- | --- | ---: |
| 전부 | `hazop/app/screens/__init__.py` | 1 |
| 전부 | `hazop/app/screens/ai_review_panel.py` | 397 |
| 전부 | `hazop/app/screens/analysis.py` | 681 |
| 전부 | `hazop/app/screens/initiating.py` | 1064 |
| 전부 | `hazop/app/screens/knowledge.py` | 1131 |
| 전부 | `hazop/app/screens/register.py` | 791 |
| 전부 | `hazop/app/screens/results.py` | 2444 |
| 전부 | `hazop/app/screens/results_matrix.py` | 160 |
| 전부 | `hazop/app/screens/results_paint.py` | 210 |
| 전부 | `hazop/app/screens/review.py` | 1164 |
| 전부 | `hazop/app/screens/study.py` | 1815 |
| 전부 | `hazop/app/screens/viewer.py` | 1394 |
| 전부 | `hazop/app/main_window.py` | 1898 |
| 전부 | `hazop/app/chat_panel.py` | 867 |
| 전부 | `hazop/app/conn_widgets.py` | 413 |
| 전부 | `hazop/app/explorer.py` | 314 |
| 전부 | `hazop/app/palette.py` | 166 |
| 전부 | `hazop/app/related_panel.py` | 121 |
| 전부 | `hazop/app/render.py` | 177 |
| 전부 | `hazop/app/screenshots.py` | 138 |
| 일부(옮길 부분을 뺀 나머지) | `hazop/app/webview.py` | 1034 |
| 일부(옮길 부분을 뺀 나머지) | `hazop/app/widgets.py` | 322 |
| 일부(옮길 부분을 뺀 나머지) | `hazop/app/settings_dialog.py` | 918 |
| 결정 뒤(2(다)) | `hazop/app/ai_runner.py` | 179 |
| 결정 뒤(2(다)) | `hazop/viewer/template.html` | 1122 |
| 결정 뒤(2(다)) | `hazop/viewer/check.py` | 182 |
| 결정 뒤(2(다)) | `scripts/build_viewer.py` | 43 |
| 전부(스크립트) | `scripts/shoot_ai_connection.py` | 168 |
| 전부(스크립트) | `scripts/shoot_ai_run.py` | 204 |
| 전부(스크립트) | `scripts/shoot_expectations.py` | 91 |
| 전부(스크립트) | `scripts/shoot_initiating.py` | 147 |
| 전부(스크립트) | `scripts/shoot_project_kg.py` | 104 |
| 전부(스크립트) | `scripts/shoot_results.py` | 166 |
| 전부(스크립트) | `scripts/shoot_stage_explorer.py` | 79 |
| 전부(스크립트) | `scripts/shoot_study_refs.py` | 139 |
| 전부(스크립트) | `scripts/shoot_uiux.py` | 146 |
| 전부(스크립트) | `scripts/check_app.py` | 88 |
| 전부(스크립트) | `scripts/check_edit_screen.py` | 180 |
| 전부(스크립트) | `scripts/bench_results_screen.py` | 161 |
| 다시 쓸 것(새 화면용) | `scripts/check_user_scenarios.py` | 1703 |
| 일부/결정 뒤 | `scripts/check_design.py` | 1598 |
| 일부/결정 뒤 | `scripts/check_kg_screen.py` | 544 |
| 일부/결정 뒤 | `scripts/check_kg_renderer.py` | 356 |

구분별 합계: 전부 15346줄, 일부(옮길 부분을 뺀 나머지) 2274줄, 결정 뒤(2(다)) 1526줄, 전부(스크립트) 1673줄, 다시 쓸 것(새 화면용) 1703줄, 일부/결정 뒤 2498줄.

시험 파일(4.1의 "새 화면 시험으로 대신할 것"·"지울 것"·"섞인 것")은 줄 수 합계가 크다. 이동 단계 5에서 파일별로 확정해 목록을 다시 붙인다(지금 어림은 추측이다).

| 시험(대신할 것·지울 것 후보) | 줄 수 |
| --- | ---: |
| `tests/test_register_ui.py` | 183 |
| `tests/test_study_screens.py` | 761 |
| `tests/test_study_project_ui.py` | 252 |
| `tests/test_study_review_ui.py` | 337 |
| `tests/test_results_hold.py` | 290 |
| `tests/test_results_project_ui.py` | 253 |
| `tests/test_ie_screen.py` | 304 |
| `tests/test_kg_expect.py` | 626 |
| `tests/test_kg_screen.py` | 706 |
| `tests/test_ai_review_ui.py` | 129 |
| `tests/test_chat_panel.py` | 654 |
| `tests/test_chat_frame.py` | 304 |
| `tests/test_chat_integration.py` | 141 |
| `tests/test_viewer_api.py` | 587 |
| `tests/test_viewer_edit.py` | 410 |
| `tests/test_viewer_links.py` | 176 |
| `tests/test_ai_screen.py` | 543 |
| `tests/test_ai_run_flow.py` | 862 |
| `tests/test_ai_key.py` | 549 |
| `tests/test_ai_connection_ui.py` | 603 |
| `tests/test_window_defects.py` | 379 |
| `tests/test_kg_renderer.py` | 161 |
| `tests/test_graph_select.py` | 507 |
| `tests/test_display_layout.py` | 265 |
| 합계 | 9982 |

