# CI 도입 검토 (2026-11-10)

## 결론

1. 저장소 `ReoDe/HAZOP`는 지금 **공개**다(2026-11-10 `gh repo view` 결과 `"visibility":"PUBLIC"`). 공개 저장소는 GitHub가 제공하는 기계를 써도 돈이 들지 않는다. 11-05에 보류한 첫째 이유(비용 불확실)는 공개로 두는 동안에는 사라진다.
2. 권장은 **가벼운 CI(선택지 b)**다. PR을 올릴 때마다 GitHub의 Windows 기계에서 unittest와 화면 없이 도는 검사만 돌린다. 실제 화면·한글 입력·APR1400 원본·Claude 호출이 필요한 검사는 지금처럼 로컬에서 한다.
3. 다만 저장소를 계속 공개로 둘지는 아직 정해지지 않았다(`INTENT.md` 확인 필요 8·12번). CI보다 이 결정이 먼저다. 비공개로 바꾸어도 b는 월 몇 달러 수준으로 추정되지만, 패키징 빌드(c)와 사용자 PC 러너(d)는 권하지 않는다.

## 용어

- **CI(지속적 통합)**: 코드를 올릴 때마다 남의 기계가 자동으로 시험을 돌려 통과·실패를 알려 주는 방식.
- **GitHub Actions**: GitHub가 제공하는 CI 서비스. 이 검토에서 CI라고 하면 이것을 뜻한다.
- **워크플로**: "언제, 어떤 기계에서, 무엇을 돌린다"를 적은 설정 파일. 저장소의 `.github/workflows/` 폴더에 둔다. 지금 이 저장소에는 없다.
- **러너**: 워크플로를 실제로 돌리는 기계. GitHub가 빌려주는 기계(GitHub 호스티드)와 내 PC를 등록해 쓰는 기계(self-hosted)가 있다.
- **PR(풀 리퀘스트)**: 작업 브랜치(`feat/next-units`)의 변경을 기본 브랜치(`main`)에 합쳐 달라는 요청. 이 프로젝트는 지금까지 PR 10개를 만들어 합쳤다(#6~#15, 11-05~11-09).
- **푸시**: 내 PC에서 만든 커밋을 GitHub에 올리는 일. 이 프로젝트는 사용자가 요청할 때만 푸시한다(CLAUDE.md 규칙 6). CI는 GitHub에 올라간 것만 볼 수 있다.
- **offscreen**: 화면에 창을 띄우지 않고 메모리 안에서만 그리는 Qt 실행 방식. 이 프로젝트 시험 45개 파일이 이미 이 방식으로 돈다(`QT_QPA_PLATFORM=offscreen`).
- **비밀값(secret)**: API 키처럼 남이 보면 안 되는 값. 워크플로에 넣을 수는 있지만 이번 권장안에는 필요 없다.

## 1. 지금 상태 (2026-11-10, 커밋 71eb887 기준)

| 항목 | 값 | 출처 |
| --- | --- | --- |
| 저장소 공개 여부 | 공개 | `gh repo view ReoDe/HAZOP --json visibility` |
| Actions 사용 가능 여부 | 켜져 있음, 모든 액션 허용 | `gh api repos/ReoDe/HAZOP/actions/permissions` |
| 워크플로 | 없음(`.github/` 폴더 없음) | 작업트리 확인 |
| 저장된 비밀값 | 0개 | `gh api …/actions/secrets` |
| `main` 보호 규칙 | 없음 | `gh api …/branches/main/protection` → 404 |
| 아직 푸시하지 않은 커밋 | 8개 | `git log origin/feat/next-units..HEAD` |
| git이 추적하는 파일 | 1,258개, 압축 저장 26.5 MiB | `git ls-files`, `git count-objects -vH` |
| 시험 | 약 1,750개, 약 6분 | 작업지시서. 단위 A 보고는 1,748개(실패 0, 건너뜀 20) |
| 시험 파일 | `tests/` 아래 86개 항목 | `ls tests` |

## 2. CI 기계에서 돌 수 있는 것과 없는 것

GitHub 기계는 매번 새로 깔린 빈 Windows다. 공개 저장소용 표준 Windows 러너는 4코어·16GB 메모리·14GB SSD다(GitHub 문서 "GitHub-hosted runners", 2026-11-10 확인). 저장소에 들어 있는 파일만 받아 오므로, `.gitignore`로 뺀 자료는 없다.

### 돌 수 있는 것

| 대상 | 근거 |
| --- | --- |
| unittest 대부분(약 1,750개 중 대부분) | 화면 시험은 이미 offscreen으로 돈다. 가짜 Claude(`tests/fake_claude`)를 쓰므로 키가 필요 없다 |
| SNP 샘플 도면을 쓰는 시험과 `check_snp_baseline.py` | SNP 샘플 도면(`자원/참고자료/P&ID 도면 샘플`, 49개 파일, 9.6MB)은 git이 추적한다 |
| 경로 문자열 검사 `test_path_literals.py`, 기계 경로 검사 `test_machine_paths.py` | 추적 파일만 읽는다. 오히려 다른 기계에서 돌아야 제 몫을 한다 |
| 화면 없는 검사 스크립트 | `check_adapter`, `check_analysis`, `check_compare`, `check_contract`, `check_corrections`, `check_expect`, `check_export`, `check_extract`, `check_graph`, `check_kg`, `check_kg_algo`, `check_kg_context`, `check_register`, `check_review`, `check_study_nodes`, `check_symbols`, `check_version_migration`, `check_viewer`, `check_desktop_support` (이름만 보고 분류. 각 스크립트가 실제로 CI에서 통과하는지는 미확인) |
| offscreen 화면 검사 | `check_app`, `check_edit_screen`, `check_kg_link`, `check_kg_renderer`, `check_kg_screen`, `check_design`. QtWebEngine이 GitHub 기계에서 offscreen으로 뜨는지는 미확인 |

### 돌 수 없는 것

| 대상 | 이유 |
| --- | --- |
| `check_user_scenarios.py`(S1~S6), `desktop_lease.py`, verify-hazop 스킬 | 실제 화면에 창을 띄우고 키보드·마우스로 움직인다 |
| 한글 IME 시험(오늘 단위 C의 결함 3 같은 것) | 한글 입력기를 켠 실제 데스크톱이 필요하다 |
| `check_apr1400.py`, `check_project_kg.py` | APR1400 DCD 원본(`자원/참고자료/APR1400_DCD`, 411MB)이 git에 없다 |
| `check_cli_live.py`, `check_ai_analysis.py` | 실제 Claude 구독 또는 API 키가 필요하다 |
| 개발 PC의 작업 루트(`작업/`, 116MB)를 읽는 시험 | git에 없다. 예: `test_study_refs.py`는 실제 분석 결과 파일이 없으면 건너뛴다 |
| 다른 드라이브 시험(`test_cross_drive.py` 일부) | 임시 폴더와 저장소가 같은 드라이브면 건너뛴다. GitHub Windows 기계에 D: 드라이브가 있는지는 미확인 |

### 확인이 필요한 것

- **맑은 고딕 글꼴.** 11-05 보류의 둘째 이유다. `test_design.py`는 `C:\Windows\Fonts\malgun.ttf`가 없으면 그 시험을 건너뛰고, `test_ai_connection_ui.py`는 있으면 쓴다. 그래서 글꼴이 없어도 CI가 깨지지는 않지만, 1366 폭 검사가 실제와 다른 글꼴로 잴 수 있다. GitHub Windows 기계에 맑은 고딕이 있는지는 미확인이다. 첫 실행에서 파일이 있는지 한 줄로 찍어 보면 바로 알 수 있다.
- **설치 시간.** PySide6, pdfplumber, OpenCV, rapidocr 등을 매번 내려받는다. 한 번 실행에 설치 포함 15~25분으로 추정한다(로컬 시험 6분과 패키지 크기로 짐작한 값이며 실측 아님).

## 3. 지난 2주 사고와 CI가 막았을지

대상: 2026-10-28 이후 커밋 223개, `records/decision-log.md`, `docs/2026-11-10-lessons/README.md`, 오늘 단위 A·B·C 보고(세션 공유 노트 폴더).

| # | 사고 | 근거 | CI가 막았을까 | 이유 |
| --- | --- | --- | --- | --- |
| 1 | 잘못된 인터프리터(LibreOffice Python, 옛 venv)로 시험을 돌려 '순수 HEAD에서도 실패'로 보고 | 교훈 1 | **일부** | CI는 매번 같은 환경에서 깨끗하게 돌리므로 "HEAD에서 정말 실패하는가"의 기준 답을 준다. 다만 이미 `tests/__init__.py`와 `preflight.py`가 잘못된 인터프리터를 바로 멈추게 해 같은 사고는 로컬에서 막힌다 |
| 2 | 다른 세션의 실패를 원인 없이 '기존 실패'로 넘김 | 교훈 2, `records/backlog.md` 334행("기존 실패: test_claude_cli 8건…") | **예, 푸시한 커밋에 한해** | `main`과 PR의 CI 결과가 남으면 '기존 실패'인지 바로 확인할 수 있다 |
| 3 | 섞인 작업트리 코드로 APR1400 기준값을 `--update` | 교훈 3 | **아니오** | APR1400 원본이 CI에 없다. 이미 `devenv.py` 잠금으로 막았다 |
| 3' | 같은 사고가 SNP 기준값에서 난다면 | — | **예** | CI는 커밋된 코드로 `check_snp_baseline.py`를 돌리므로 기준값과 코드가 어긋나면 실패한다 |
| 4 | 데스크톱 차례를 메시지로 넘겨 키 입력이 Claude 창으로 샘 | 교훈 5 | **아니오** | CI는 실제 데스크톱을 쓰지 않는다 |
| 5 | 디스크 부족('No space left'), 임시 폴더 3,000개 | 교훈 9 | **아니오** | 개발 PC의 일이다 |
| 6 | 수치에 출처가 없음(사용률 0.013 vs 0.027%p) | 교훈 5·12 | **아니오** | 보고 방식의 문제다 |
| 7 | 이 컴퓨터에만 있는 경로를 추적 파일에 넣음(`test_ie_bundle.py`의 세션 임시 폴더 기본값) | 교훈 17 | **예** | 다른 기계에서 돌리면 바로 드러난다. 지금은 `test_machine_paths.py`가 막는다 |
| 8 | 다른 세션의 추적 안 한 파일 때문에 시험이 깨짐 | 교훈 8 | **예(드러냄)** | CI에는 추적 파일만 있으므로 추적 안 한 파일에 기대는 시험이 실패한다 |
| 9 | 커밋된 HEAD에서 시험이 깨져 있었음: `test_path_literals` 1건(`devenv.py` 108·110행), `test_register` 3건(`build_graph.py` 31행) | 단위 A 보고("HEAD 분리 작업트리 + 새 시험: 실패 7·오류 11") | **절반** | `test_path_literals`는 어느 기계에서나 실패하므로 CI가 잡는다. `test_register` 3건은 저장소와 임시 폴더가 다른 드라이브일 때만 나는 결함이라, GitHub 기계의 드라이브 구성(미확인)에 따라 잡거나 놓친다 |
| 10 | D 드라이브 이전 뒤 백업 경로·그래프 출처의 `ValueError` | 커밋 977a38a | **불확실** | 9의 `test_register`와 같은 이유. 드라이브가 하나면 `test_cross_drive.py` 일부가 건너뛴다 |
| 11 | `hazop/kg/auto.py` 변경이 ③ 화면 검사를 깨뜨림(11-07, 되돌림) | 결정로그 153행 | **예, 푸시했다면** | `check_kg_screen`이 offscreen으로 돈다면 잡는다. 실제로는 로컬 검사가 먼저 잡았다 |
| 12 | ⑤ 워크시트에서 한글 입력 상태로 A·R·E가 안 들음 | 커밋 43a0cb4, 단위 C | **아니오** | 한글 IME가 필요하다 |
| 13 | 하위 세션이 저장소 밖 `D:\HAZOP-trials\README.md`를 덮어씀 | 결정로그 234행 | **아니오** | 저장소 밖 일이다 |
| 14 | 배포본 검증에서 `check_kg_screen` 3)항 실패 | 단위 B 보고 | **아마 예** | 묶음 밖에서도 재현된다고 보고되었으므로 CI의 `check_kg_screen`에서도 날 것으로 본다(미확인) |

**정리.** 실제 사고 14건과 가정 1건(3') 가운데 CI가 분명히 막거나 드러냈을 것이 4건(2, 7, 8, 3'), 조건이 붙는 것이 5건(1, 9, 10, 11, 14), 막지 못했을 것이 6건(3, 4, 5, 6, 12, 13)이다. 큰 시간 손실(인터프리터, 기준값, 데스크톱 차례, 디스크)은 대부분 CI 밖의 일이고, 이미 스크립트로 막았다. CI가 더하는 몫은 **"깨끗한 다른 기계에서, 커밋된 것만으로 시험이 통과하는가"**를 PR마다 기록해 주는 것이다.

한 가지 한계가 크다. 이 프로젝트는 커밋은 자주 하지만 푸시는 사용자가 요청할 때만 한다. CI는 푸시한 뒤에야 돈다. 그래서 하위 세션이 커밋하는 순간에는 CI가 없고, 깨진 커밋이 여러 개 쌓인 뒤 PR에서 한꺼번에 드러난다. 오늘도 푸시 안 한 커밋이 8개다.

## 4. 선택지 비교

비용은 GitHub 문서 "GitHub Actions billing"(docs.github.com, 2026-11-10 확인, 문서에 갱신 날짜 표시 없음) 기준이다.

- 공개 저장소에서 표준 GitHub 기계는 무료다.
- 비공개 저장소에는 계정 요금제에 따라 매달 포함 사용액이 있다. Free $12, Pro $18, Team $18이다.
- 포함 사용액을 넘으면 Windows 2코어 기준 분당 $0.010이 든다(Linux 2코어는 $0.006).
- 결과 파일(아티팩트) 저장 한도는 비공개 기준 Free 500MB, Pro 1GB다. 캐시는 저장소마다 10GB다.
- 작업 하나는 최대 6시간까지 돈다. Free 요금제의 동시 실행은 20개다(문서 "Actions limits").
- `ReoDe` 계정이 Free인지 Pro인지는 미확인이다.

### (a) 지금처럼 로컬만

- **막는 것**: 지금 로컬 장치(venv 잠금, 기준값 잠금, 경로 검사, 데스크톱 잠금)가 막는 것 그대로.
- **못 막는 것**: "이 PC에서만 통과"하는 결함(사고 7·8·9). '기존 실패'를 가릴 기준 기록이 없다(사고 2).
- **비용**: 0원. 대신 총괄 세션이 매번 6분 시험을 돌리는 시간과 구독 사용량이 든다.
- **노력**: 0.
- **보안 위험**: 없음.
- **세션 운영과의 궁합**: 지금 방식 그대로.

### (b) 가벼운 CI — PR마다 Windows 기계에서 unittest와 화면 없는 검사 (권장)

- **막는 것**: 사고 2·7·8과 3'. 조건이 맞으면 9·11·14도. PR을 합치기 전에 "다른 기계에서도 통과" 기록이 PR 화면에 남는다.
- **못 막는 것**: 실제 화면·한글 입력·APR1400·실제 Claude(사고 3·4·12). 커밋 시점의 결함(푸시 전).
- **비용**: 공개 저장소면 0원. 비공개라면 한 번에 약 20분(추정) × 분당 $0.010 = 약 $0.20이다. PR이 주 2~5개면 월 10~20회, 수정 푸시까지 넣어 월 30회로 잡아도 약 $6로 Free 포함액($12) 안이다. 이 값은 실행 시간 추정에 기댄 것이라 첫 실행으로 실측해야 한다.
- **노력**: 처음 설정 반나절 정도(하위 세션 1개). 첫 실행에서 글꼴·QtWebEngine·드라이브 문제가 나오면 고칠 일이 조금 생긴다. 그 뒤 유지는 패키지 버전을 올릴 때 설정 한 줄을 맞추는 정도다.
- **보안 위험**: 낮다. 가짜 Claude를 쓰므로 비밀값이 필요 없다. 워크플로 권한을 읽기 전용으로 두고, 남의 저장소에서 가져온 액션은 판 번호를 고정한다. 공개 저장소라 실행 기록(로그)이 누구에게나 보인다는 점만 기억하면 된다. 로그에는 시험 이름과 경로가 찍히고, APR1400 원본은 CI에 없으므로 찍히지 않는다.
- **세션 운영과의 궁합**: 좋다. 하위 세션의 커밋 방식은 바꾸지 않는다. 사용자가 푸시를 요청하거나 PR을 만들 때만 돈다. 여러 세션의 커밋이 한 PR에 섞이므로, 실패하면 총괄이 어느 커밋 탓인지 가려야 한다.

### (c) b에 패키징 빌드까지

- **막는 것**: b에 더해 PyInstaller 빌드가 깨지는 일(빠진 모듈, spec 오류 같은 것).
- **못 막는 것**: b와 같다. 빌드본을 실제로 띄워 보는 `verify_bundle`의 화면 부분은 여전히 로컬에서 해야 한다.
- **비용**: 공개면 0원. 빌드본이 569~577MB(단위 B 보고: 배포용 569.1MB, 검증용 576.7MB)라 결과 파일로 올리면 비공개 Free 저장 한도(500MB)를 한 번에 넘는다. 실행 시간도 b보다 길다(미측정).
- **노력**: b보다 크다. 빌드용 venv를 따로 꾸려야 한다.
- **보안·라이선스 위험**: **크다.** 2026-11-06 결정은 "LGPL 요건은 법무 검토 전까지 판단 보류, 배포본은 내부용으로만"이다(결정로그 103행). 공개 저장소에서 빌드본을 결과 파일로 올리면 외부 배포가 될 수 있다. 빌드만 하고 결과는 올리지 않는다는 조건이면 위험은 줄어든다.
- **세션 운영과의 궁합**: 보통. 패키징은 PR마다 바뀌지 않으므로 PR마다 돌릴 필요가 없다. 손으로 누를 때만 도는 방식이 맞다.

### (d) 사용자 PC를 self-hosted 러너로 쓰기

- **막는 것**: 이론상 가장 많다. 실제 글꼴, 한글 입력, APR1400 원본, 실제 화면이 다 있다.
- **못 막는 것**: 데스크톱 차례 충돌은 오히려 늘어난다. CI가 창을 띄우는 동안 Claude 하위 세션이나 사용자가 같은 화면을 쓰면 사고 4가 다시 난다.
- **비용**: GitHub 요금은 0원. PC가 켜져 있어야 하고 전기·디스크를 쓴다.
- **노력**: 크다. 러너 프로그램 설치·갱신, 실행 계정 분리, 디스크 정리를 사람이 맡아야 한다. GitHub 문서도 "운영체제와 모든 소프트웨어의 갱신은 사용자 책임"이라고 적는다.
- **보안 위험**: **매우 크다.** GitHub 보안 문서("Secure use reference")는 공개 저장소에서 self-hosted 러너를 거의 쓰지 말라고 한다. 누구든 PR을 열어 그 기계에서 코드를 돌릴 수 있기 때문이다. 사용자 PC에는 APR1400 자료, Claude 로그인 정보, 개인 파일이 있다.
- **세션 운영과의 궁합**: 나쁘다. 데스크톱 잠금(`desktop_lease`)과 다투고, 같은 체크아웃을 쓰는 세션들과 디스크·임시 폴더를 함께 쓴다.

### 한눈에 보기

| | a 로컬만 | b 가벼운 CI | c b+빌드 | d 사용자 PC 러너 |
| --- | --- | --- | --- | --- |
| 새로 막는 사고(3장 표 기준) | 0 | 4건 + 조건부 5건 | b와 같음 + 빌드 깨짐 | 가장 많음 |
| 월 비용(공개) | 0 | 0 | 0 | 0(전기 제외) |
| 월 비용(비공개, 추정) | 0 | 약 $6, Free 포함액 안 | b보다 큼, 저장 한도 초과 위험 | 0 |
| 설정·유지 | 없음 | 반나절, 이후 적음 | 하루 이상 | 큼, 계속 |
| 보안 위험 | 없음 | 낮음 | 라이선스 위험 | 매우 큼 |
| 세션 운영 궁합 | 그대로 | 좋음 | 보통 | 나쁨 |

## 5. 권장안

**b(가벼운 CI)를 권한다.** 저장소를 공개로 두는 동안 비용이 0원이고, 비공개로 바꾸어도 추정상 Free 포함액 안이다. 비밀값이 필요 없어 공개 저장소의 위험도 작다. "이 PC에서만 통과"하는 결함과 '기존 실패' 논란을 PR마다 기록으로 정리해 준다. 큰 사고들은 이미 로컬 장치가 막고 있으므로 CI는 그 위에 얹는 두 번째 확인이지 대체가 아니다. c는 라이선스 결정이 풀린 뒤 손으로 누르는 방식으로만, d는 쓰지 않는다.

**도입한다면 첫 단계**(하위 세션 하나, 반나절):

1. `.github/workflows/tests.yml` 하나를 만든다. `main`으로 가는 PR과 손으로 누를 때만 돌고, 권한은 읽기 전용, 기계는 `windows-2022`나 `windows-2025` 중 하나로 고정한다.
2. 그 안에서 Python 3.12를 깔고 `packaging/requirements.txt`, `requirements-pdf.txt`, `requirements-raster.txt`를 설치한 뒤, `scripts/preflight.py`와 `python -m unittest discover -s tests -t .`를 `PYTHONIOENCODING=utf-8`, `QT_QPA_PLATFORM=offscreen`으로 돌린다.
3. 첫 실행 로그에 맑은 고딕 파일 유무, 임시 폴더 드라이브, 실행 시간을 찍어 3장의 미확인 항목을 채운다.
4. 첫 실행에서 통과하지 않는 시험은 고치거나 "CI 기계에서는 건너뜀"으로 표시하되 이유를 남긴다. 그런 다음에 화면 없는 `check_*.py` 몇 개와 `check_snp_baseline.py`를 더한다.
5. CI 결과를 보고 `main` 보호 규칙(시험 통과 전 합치기 금지)을 켤지 사용자에게 묻는다.

## 6. 사용자가 정할 것

1. **저장소를 공개로 둘까요, 비공개로 바꿀까요?** CI보다 먼저 정할 일이다. APR1400 자료와 기호 사전을 다루는 지금, 이미 `INTENT.md` 확인 필요 12번으로 열려 있다. 공개면 CI가 무료이고, 비공개면 아래 2번이 필요하다.
2. **비공개로 바꾼다면 월 비용 상한을 얼마로 둘까요?** 예: $0(포함액을 넘으면 멈춤) 또는 $5. 계정 요금제(Free/Pro)도 함께 확인해야 한다.
3. **푸시를 지금보다 자주 할까요?** CI는 푸시한 뒤에만 돈다. 예를 들어 작업 단위가 끝날 때마다 총괄이 푸시하게 하면 CI가 더 일찍 잡는다. 지금 규칙(푸시는 사용자 요청 때만)을 바꾸는 일이라 사용자 결정이 필요하다.
4. **CI가 실패하면 PR 합치기를 막을까요?** 막으면 안전하지만, 글꼴 같은 CI 기계 문제로 급한 PR이 멈출 수 있다. 처음 몇 주는 알림만 받고 나중에 막는 순서를 권한다.
5. **빌드본을 GitHub에 올려도 되나요?** 지금 결정(내부용, LGPL 판단 보류)으로는 안 된다. c를 하려면 이 결정이 먼저 바뀌어야 한다.

## 7. 첫 실행 결과

가벼운 CI(b)를 `.github/workflows/tests.yml`로 들였다. 워크플로는 Python을 깔고 `scripts/preflight.py --profile test`와 `scripts/run_ci.py`만 부른다. 무엇을 돌릴지는 `run_ci.py`의 `CHECKS`·`NOT_IN_CI` 표가 정한다.

`tests/test_ci_config.py`가 지키는 범위는 아래까지다.

- 모든 `scripts/check_*.py`가 두 표 중 하나에만 들어 있고, 표에 적힌 스크립트가 실제로 있다.
- 워크플로가 적은 `scripts/…`·`packaging/…` 경로가 있다. 워크플로에 ASCII 밖 글자와 `check_` 이름이 없다.
- 워크플로 글자 어디에도 `secrets`, `pull_request_target`, `write-all`·`: write`, `continue-on-error`, `${{ runner.` 가 없다. 최상단 `permissions`는 `contents: read` 한 줄뿐이다. 액션은 40자리 SHA로 고정되어 있고, checkout마다 `persist-credentials: false`가 있으며, `runs-on`에 `latest`가 없다.
- 위 규칙마다 일부러 망가뜨린 변형 14개를 넣어 모두 잡히는지 시험이 확인한다.

CI venv에 PyYAML이 없어 YAML을 구조로 읽지 않고 정규식으로 본다. 그래서 YAML 의미는 검사하지 않는다. 예를 들어 단계 순서, `if:` 조건, 다른 컨텍스트를 쓰지 못하는 자리에 쓴 표현식은 GitHub에서 돌려 봐야 드러난다. 이름 이전 단위가 경로를 바꾸면 이 시험이 먼저 깨진다.

러너 이미지는 `windows-2025`로 고정했지만 판 번호가 이미지 내용까지 고정하지는 않는다. 검토 의견(2026-11-10, 이 세션에서는 확인하지 않음)에 따르면 이 이름은 지금 VS2026이 든 이미지로 연결되어 있다. GitHub이 같은 이름 아래 이미지를 바꾸면 글꼴·도구 판이 말없이 달라질 수 있다. 진단 줄(맑은 고딕 유무, Python·PySide6 판)을 실행마다 찍는 이유다.

checkout은 `fetch-depth: 0`으로 전체 이력을 받는다. `tests/test_design.py`의 두 시험(271행 커밋 2178ddf, 621행 커밋 2727e56)이 과거 커밋을 읽기 때문이다. 얕게 받으면 이 둘이 건너뛴다. 저장소가 26MB 정도라 받는 시간은 크지 않다(추정).

### 로컬 리허설 (2026-11-10, 이 PC)

조건: `D:\HAZOP-trials\ci-rehearsal-20261110\`에 HEAD 3db5f55를 `git clone --no-local`로 받고 새 CI 파일 3개를 얹었다. 새 venv(Python 3.12.10)에 워크플로와 같은 두 줄로 설치했다(`--no-cache-dir`). `HAZOP_WORK_ROOT`는 그 아래 빈 폴더, `QT_QPA_PLATFORM=offscreen`이다. 이 PC는 맑은 고딕이 있고, 임시 폴더는 C:, 작업 폴더는 D:다. 러너 시간과 섞어 읽지 않는다.

| 항목 | 1차 (검사 19개) | 2차 (확정한 검사 10개) |
| --- | --- | --- |
| 설치 | 29초, 성공 | 같은 venv |
| unittest | 1,761개, 실패 0, 건너뜀 23, 348초 | 1,761개, 실패 0, 건너뜀 23, 334초 |
| 검사 스크립트 | 6개 실패, 1,484초 | 10개 모두 rc 0, 87초 |
| `run_ci.py` 전체 | rc 1, 1,835초 | rc 0, 422초 |

건너뜀 23개의 이유는 OpenCV·rapidocr 없음 14(결정 D7, raster venv 몫), anthropic SDK 없음 5, 저장소 밖 출력·예시 파일 없음 3, pefile 없음 1이다. 모두 '없는 것'을 이유로 건너뛴다. 같은 날 `D:\HAZOP`에서 평소 시험용 venv(`%USERPROFILE%\.hazop\venv-py312`)로 돌린 unittest는 1,761개 중 20개를 건너뛰었다(실패 0, 347초). 작업 트리는 커밋 a21af4e 직전 내용이고, 기록은 `D:\HAZOP-trials\ci-rehearsal-20261110\local-unittest-a21af4e.log`에 있다. 차이 3개는 깨끗한 복제에 없는 저장소 밖 출력·예시 파일 몫이다.

1차에서 뺀 검사는 두 갈래다.

- `check_analysis`, `check_expect`, `check_kg`, `check_kg_algo`, `check_contract`는 작업 루트의 git 제외 데이터(`데이터/구간`, `데이터/지식`, `출력/그래프`, `출력/분석`)를 읽는다. 깨끗한 복제에는 그 데이터가 없어 실패한다.
- `check_extract`, `check_graph`, `check_register`, `check_viewer`는 안에서 unittest 전체를 다시 돈다. 하나에 330~395초가 걸려 같은 시험을 네 번 더 도는 셈이다. 이 스크립트들에 unittest를 끄는 옵션이 생기면 앞부분 검사만 CI에 넣는다(후속).

1차의 `check_extract` 안 unittest에서 `test_ai_run_flow.SubscriptionFlowTest.test_close_now_kills_and_closes`가 한 번 실패했다(창이 30초 안에 닫히지 않음). 같은 실행의 본 unittest와 2차에서는 통과했다. 간헐 실패라서 건너뛰기 표시를 하지 않고 후속으로 남긴다.

### 확정한 CI 검사 목록

`check_adapter`, `check_compare`, `check_corrections`, `check_export`, `check_kg_context`, `check_review`, `check_study_nodes`, `check_symbols`, `check_version_migration`, `check_snp_baseline`. 빼는 검사와 이유는 `scripts/run_ci.py`의 `NOT_IN_CI`에 있다.

### 러너에서만 하는 건너뛰기 표시

없다. 러너에서 건너뛴 25개는 로컬 리허설의 23개에 '빌드 TOC 없음'과 '빌드 venv 없음' 2개를 더한 것이고, 모두 '없는 것'을 이유로 이미 달려 있던 표시다.

### GitHub 실행

| run | 커밋 | 결과 | 시간 | 내용 |
| --- | --- | --- | --- | --- |
| 42771584149 | 97edda1 | 실패, 0초 | - | 워크플로 파일 무효(`tests.yml` 50행). `--only-binary=:all: -r`의 ': '가 따옴표 없는 한 줄 값에 들어갔다. 총괄이 블록 스칼라로 고쳤다(90b9cf6) |
| 42771733162 | 90b9cf6 | 실패 | 11분 10초 | 끝까지 돌았다. 받아오기 8초, 설치 30초(런타임 24초, PDF 6초), Preflight 1초, 시험·검사 10분 21초(unittest 475.2초, 검사 144.4초). unittest 1,759개 중 실패 11, 오류 3, 건너뜀 25. 검사는 `check_compare`·`check_export` rc 1, 나머지 8개 rc 0 |

42771733162 진단 줄: 맑은 고딕 있음, 임시 폴더 C:, 작업 디렉터리와 작업 루트 D:. 로그는 `D:\HAZOP-trials\ci-rehearsal-20261110\gh-42771733162-full.log`에 받아 두었다.

**실패 원인은 하나였다. 드라이브가 아니라 8.3 단축 이름이다.** 러너의 TEMP는 `C:\Users\RUNNER~1\…`로 단축 이름이다. `paths.safe_join`은 안팎을 realpath로 판정한 뒤 그 realpath(긴 이름 `runneradmin`)를 돌려주었다. 그래서 단축 이름 루트와 긴 이름 결과가 섞였다. 이 PC에서 TEMP·TMP를 8.3 단축 이름 폴더로 두면 14개가 똑같이 재현된다.

| 실패 시험 | 분류 | 증상 |
| --- | --- | --- |
| `test_desktop_support` SplitRootsTest | 앱 결함(저장 경로) | `rel_or_abs`가 `../../../../../../runneradmin/…/자료저장소/…`를 저장 경로로 썼다 |
| `test_contract` SampleChainTest 6개, RegistrationChainTest 1개 | 앱 결함 | `_link_in_path`가 realpath ≠ abspath를 링크로 보아 단축 이름 경로의 보고 쓰기를 거부했다. 판정 E3·G2도 이 때문에 달라졌다 |
| `test_desktop_support` BundleExportTest, `test_evaluate` Hardening, `test_export` TestHeaderAndFiles, `test_kg_screen` KnowledgeTabTest, `test_packaging` SplitRootsFlowTest, `test_register` PdfRegisterTest 2개 | 같은 원인 | 앱이 돌려준 경로가 들어간 루트와 다른 표기(긴 이름)라 비교가 어긋났다 |
| `check_compare`, `check_export` | 같은 원인 | 안에서 돌린 `test_evaluate`·`test_export`가 위와 같이 실패했다 |

계정 이름이 길거나 한글인 사용자 PC도 TEMP가 단축 이름일 수 있다. 그래서 이것은 러너 고유 한계가 아니라 앱 결함으로 보고 고쳤다. 고친 커밋의 러너 결과는 총괄이 다음 푸시 뒤 이 표에 더한다.

- `paths.safe_join`은 안팎 판정을 realpath로 그대로 하고, 결과를 루트가 들어온 형태 그대로 돌려준다.
- `paths.long_path`를 새로 두었다. 이미 있는 앞부분의 단축 이름을 긴 이름으로 펼친다. `contract.chain._link_in_path`는 이것과 realpath를 견준다. 진짜 링크·정션은 그대로 거부한다.
- 재현 시험은 `tests/test_short_path_names.py`(4개)다. 8.3 이름을 만들지 않는 볼륨에서는 건너뛴다.
- `tests/test_extract_drawio.py`의 두 단언은 'safe_join이 realpath를 돌려준다'는 옛 규약을 적고 있어서, '루트 형태 그대로'로 바꿨다. 안팎 판정은 그대로다.
- `tests/test_ci_config.py`에 '따옴표 없는 한 줄 값의 ': '' 규칙을 더했다. 97edda1의 워크플로를 넣으면 이 규칙으로 잡힌다.

## 미확인 목록

- GitHub Windows 기계에 맑은 고딕(`malgun.ttf`)이 있는지
- GitHub Windows 기계에서 임시 폴더와 작업 폴더가 다른 드라이브인지(`test_cross_drive.py`·`test_register` 3건이 돌지 여부)
- QtWebEngine이 GitHub 기계에서 offscreen으로 뜨는지
- 설치 포함 한 번 실행 시간(추정 15~25분)
- 화면 없는 `check_*.py` 각각이 CI에서 통과하는지
- `ReoDe` 계정의 요금제(Free/Pro)와 지출 한도 설정

## 출처

- GitHub Docs, "GitHub Actions billing", https://docs.github.com/en/billing/concepts/product-billing/github-actions (2026-11-10 확인)
- GitHub Docs, "GitHub-hosted runners reference", https://docs.github.com/en/actions/reference/runners/github-hosted-runners (2026-11-10 확인)
- GitHub Docs, "Actions limits", https://docs.github.com/en/actions/reference/limits (2026-11-10 확인)
- GitHub Docs, "Secure use reference", https://docs.github.com/en/actions/reference/security/secure-use (2026-11-10 확인)
- GitHub Docs, "Self-hosted runners", https://docs.github.com/en/actions/concepts/runners/self-hosted-runners (2026-11-10 확인)
- 저장소: `docs/2026-11-10-lessons/README.md`, `records/decision-log.md`(103·153·234행), `records/backlog.md`(334행), `INTENT.md` 확인 필요 8·12번, 커밋 977a38a·43a0cb4, 단위 A·B·C 보고(세션 공유 노트 폴더)
- 11-05 보류 결정: 에이전트 메모리 `ci-deferred.md`
