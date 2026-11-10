---
doc_id: HZ-GOV-02
rev: 1
status: review
author: 이름 규칙 설계 하위 세션
reviewed: —
approved: —
---

# 작업물 관리·이름 규칙 (확정본)과 이전 계획

작성 2026-11-10. 개정 0(초안, 세 안 비교) → 개정 1(사용자 결정 8개 반영, 이전 계획 추가). 이 문서는 설계만 담는다. 파일을 옮기거나 이름을 바꾸지 않았다. 실제 이전은 §7의 단계마다 별도 작업 단위로 한다.

## 결론

1. 사용자는 **원자력 문서관리식 엄격안(안 C)**과 **전부 영어 이름**을 골랐다(2026-11-10). 저장소 추적 파일 1,261개 중 647개(한글이나 공백이 든 경로)와 코드가 만드는 작업 폴더 이름 약 30종이 바뀐다.
2. 이전은 **7단계(0~6)**로 나눈다. 코드가 읽지 않는 것(저장소 밖, `docs/` 안 파일, 사람 문서 폴더)을 먼저 옮기고, 코드가 읽는 `자원/`·`작업/`은 마지막에 옮긴다. 단계마다 따로 커밋하고 `git revert` 하나로 되돌릴 수 있게 짠다.
3. 가장 큰 위험은 세 가지다. 이미 깔린 배포본의 사용자 작업 폴더, 그래프 판 해시와 고정 응답·지침서 해시가 줄줄이 바뀌는 문제, 문서 88개 480곳의 경로 언급과 동시에 도는 다른 세션이다. 단계 5·6은 다른 세션이 하나도 돌지 않을 때만 한다.

---

## 0. 먼저 알아 둘 말

| 말 | 뜻 |
| --- | --- |
| 형상관리(Configuration Management, CM) | 무엇이 있는지 이름을 붙여 구분하고, 바뀔 때마다 누가 왜 바꿨는지 남겨, 언제든 특정 시점의 상태를 되짚을 수 있게 하는 일. 원자력의 설계 형상관리와 같은 뜻이다 |
| 저장소(repository) | git이 이력을 관리하는 폴더. 여기서는 `D:\HAZOP` |
| 추적 파일 | git이 이력을 남기는 파일. 추적하지 않는 파일(`작업/` 등)은 지워지면 되살릴 수 없다 |
| 커밋(commit) | 저장소에 남기는 변경 한 묶음. 원자력 문서의 개정 한 번과 비슷하다 |
| 브랜치(branch) | 본선(`main`)과 따로 작업하는 갈래. 끝나면 본선에 합친다(병합) |
| 작업트리(worktree) | 같은 저장소를 다른 폴더에 하나 더 펼친 사본. 다른 세션과 겹치지 않게 시험할 때 쓴다 |
| 접두어(prefix) | 이름 앞에 붙이는 분류 표시. 예: `check_apr1400.py`의 `check_` |
| 태그(tag) | 특정 커밋에 붙이는 고정 이름표. 배포본 `v0.1.0`처럼 쓴다 |
| 기준값(baseline) | 회귀 검사가 비교 기준으로 삼는 점수 파일(`tests/baselines/`) |
| 해시 고정(pin) | 파일 내용으로 계산한 지문 값을 코드에 적어 두고, 파일이 바뀌면 검사가 실패하게 하는 장치 |
| 머리(front matter) | 문서 맨 위 `---` 사이에 적는 문서번호·개정·상태 같은 항목. 이 문서 맨 위에 예가 있다 |
| 작업 루트 | 앱이 사람의 작업 데이터를 쓰는 폴더. 개발 환경은 `D:\HAZOP\작업`, 배포본은 `%LOCALAPPDATA%\HAZOP` |

---

## 1. 지금 상태 (개정 0 조사, 2026-11-10)

### 1.1 규모

| 항목 | 값 | 출처 |
| --- | --- | --- |
| 추적 파일 | 1,261개. 그중 경로에 한글이 든 것 640개(`docs` 332, `자원` 162, `디자인` 119, `기획서` 21, `메모리` 3, `지식` 1, `packaging` 1, `tests` 1), 공백만 든 `flow chart/` 7개 | `git ls-files \| wc -l`, `git ls-files \| perl -CSDA -ne 'print if /\p{Hangul}/'` |
| 한글·공백이 든 추적 폴더 | 34개(`flow chart` 포함) | 위 목록에서 폴더 단위로 셈 |
| 한글 이름 파일 | 169개 | 위 목록에서 파일 이름만 셈 |
| 최상위 폴더 | 15개(한글 8, 영어 7). `데이터/`·`참고자료/`는 빈 하위 폴더만 남은 옛 자리(추적 파일 0) | `ls D:\HAZOP`, `git ls-files 데이터 참고자료` |
| `scripts/*.py` | 73개, 이름은 모두 영어. 접두 `check_` 31, `shoot_` 9, `build_` 5, `extract_`·`export_` 각 3, 그 밖 22종 | `ls scripts/*.py` 접두 집계 |
| `docs/` 작업 공간 | 14개. 날짜 없는 것 1(`screenshots-pdf`), README 없는 것 3 | `ls docs`, README 유무 검사 |
| 커밋 | 227개. 한글 제목 17개, 나머지 영어 문장형. `feat:` 같은 종류 표시 0개 | `git log --format=%s` 집계 |
| 로컬 브랜치 | 18개. 16개는 이미 `main`에 병합됨(`claude/*` 2, `worktree-agent-*` 8 포함) | `git branch --merged main` |
| 태그 | 0개 | `git tag` |
| `D:\HAZOP-trials` | 폴더 20, 루트 낱개 파일 53. 자기 README가 있는 폴더는 `pkg-20261110` 하나. 총 크기 미확인 | `ls D:\HAZOP-trials` |
| 배포본 작업 루트(이 PC) | `%LOCALAPPDATA%\HAZOP` 안에 `자료저장소/`, `출력/`, `logs/`, `cache/`, `cli-run/`, `venv-py312/` | `ls "$LOCALAPPDATA/HAZOP"` |

### 1.2 같은 종류인데 이름이나 위치가 제각각인 사례

| # | 종류 | 사례(실제 경로) | 문제 |
| --- | --- | --- | --- |
| 1 | 최상위 폴더 언어 | 한글 `기획서/ 디자인/ 메모리/ 지식/ 자원/ 작업/` · 영어 `docs/ hazop/ scripts/ tests/ packaging/ licenses/` · 공백 섞인 `flow chart/` | 적힌 규칙이 없다 |
| 2 | 남은 빈 폴더 | `데이터/기준표`, `참고자료/P&ID 도면 샘플/SNP-M-101_RCS-main-loop` 등 | 2026-11-09 이전 뒤 빈 껍데기만 남았다 |
| 3 | 날짜 형식 | `docs/2026-11-10-lessons` · `HAZOP-trials\ie-20261109` · `HAZOP-trials\apr1400-2026-11-09` · `작업\데이터\백업\20261108T124409Z-판이전` · `HAZOP-trials\manual-1802`(시각만) | 다섯 가지가 섞여 있다 |
| 4 | 날짜 위치 | 저장소 `docs/<날짜>-<주제>` · 시험 폴더 `<주제>-<날짜>` | 정렬 순서가 반대다 |
| 5 | 작업 공간 구성 | 7문서 세트는 `docs/2026-11-05-*` 4곳뿐. `docs/2026-11-07-drawing-edit/`, `docs/2026-11-09-dev-framework/`, `docs/2026-11-10-plan/`은 README가 없다 | 들어가 보기 전에는 내용을 모른다 |
| 6 | 날짜 없는 작업 공간 | `docs/screenshots-pdf/`(2026-11-07 커밋) | 다른 13곳과 형식이 다르다 |
| 7 | 문서 이름 언어 | 작업 공간 폴더는 영어, 안의 파일은 한글(`D드라이브-이전.md`) · `flow chart/00-overview.md`는 영어 | 언어가 정해져 있지 않다 |
| 8 | 단어 구분 | `지식그래프-스키마-사전.md`(하이픈) · `검토결과관리.md`(붙여 씀) · `사전항목_시제품.csv`(밑줄) | 세 방식이 섞였다 |
| 9 | 시안 번호 | `디자인/시안/AI연결/1-연결설정-구독-1366.png` · `디자인/시안/완성본/A-밝은미니멀` · `디자인/시안/interface-mockup.html` | 숫자·글자·번호 없음이 섞였다 |
| 10 | 스크립트 동사 | `check_*` 31개 · 같은 검사인데 `packaging/verify_bundle.py`, `packaging/*_probe.py` · 동사 없음 `apr1400_key_overlay.py`, `unknowns_breakdown.py`, `devenv.py` | 이름만으로 검사인지 도구인지 모른다 |
| 11 | 검사 위치 | `tests/test_*.py` · `scripts/check_*.py` · `packaging/verify_bundle.py` | 위치마다 뜻이 다르지만 적혀 있지 않다 |
| 12 | 스크린샷 위치 | `작업/출력/스크린샷/` · `docs/screenshots-pdf/` · `디자인/시안/*/*.png` · `HAZOP-trials\bad1.png` | 시험 폴더 루트의 낱개 PNG는 주인을 모른다 |
| 13 | '지식' | `지식/위험도분석-결합방법론.md`(방법론) · `작업/데이터/지식/`(지식그래프) · `자원/표본/지식/` | 한 말이 두 뜻이다 |
| 14 | '참고자료' | `자원/참고자료/` · 빈 `참고자료/` · 기록용 논리 경로 `참고자료/…`(`hazop/paths.py` `REFERENCE_LOGICAL`) | 세 곳이 같은 이름이다 |
| 15 | 결정 기록 | `메모리/결정로그.md` · 작업 공간 `decisions.md` 4개 · `INTENT.md` · 데이터 정리 문서의 D1~D9 | 결정로그를 "n행"으로 부른다(`INTENT.md` 7행) |
| 16 | 작업 단위 ID 겹침 | `S`: 사용자 시나리오 S1~S12(`scripts/check_user_scenarios.py` 1473행), 검토구간 데이터 ID, 작업 단위 '검토구간 분할 S1~S6'. `U`: APR1400 U0~U5와 사용자 결정 U1~U10. `D`: 지식그래프 결정 D1~D7과 데이터 정리 D9 | 한 글자가 서너 뜻이다 |
| 17 | 시험 폴더 이름 | `wt-36e7335`, `u2-dev`, `arch-s1`, `adv-par`, `pairs` | 날짜도 주인도 없다 |
| 18 | 시험 폴더 낱개 파일 | `patch_u2.py`, `u2.diff`, `u1-final.tar`, `계통약어.csv`·`계통약어_draft.csv`·`계통약어_v2.csv` | 53개. 무엇이 최신인지 모른다 |
| 19 | 시험 폴더 README | `D:\HAZOP-trials\README.md`가 2026-11-10 12:54에 덮어써짐 | CLAUDE.md 규칙 14가 있어도 지켜진 폴더는 하나 |
| 20 | 브랜치 | `feat/*` 5 · `chore/track-workspaces` · `claude/pdf-extract-fix-b525b8` · `worktree-agent-*` 8 | 자동 생성 브랜치가 병합 뒤에도 남는다 |
| 21 | 커밋 언어 | 영어 문장형 다수, 2026-11-10부터 한글 | 바뀐 시점에 규칙이 없었다 |
| 22 | 버전 표기 | `APP_VERSION = "0.1.0"`(`hazop/app/main_window.py:36`) · `SCHEMA_VERSION = "0.1"` 3곳 · 그래프 판 `v-7ed95b0c74f1` · 손 버전 `_v2` | 배포본에 맞춘 태그가 없다 |
| 23 | 공백·특수문자 | `자원/참고자료/P&ID 도면 샘플/`(48), `자원/참고자료/P&ID 기호 카탈로그/`(49), `flow chart/`(7) | 따옴표를 빠뜨리면 명령이 깨진다 |

---

## 2. 업계 관행

확인일은 모두 2026-11-10이다. 원문을 직접 열지 못한 것은 '2차 출처'로 적었다.

| 관행 | 핵심 | 출처 | 이 규칙에 쓴 곳 |
| --- | --- | --- | --- |
| 형상관리 일반(ISO 10007:2017, IEEE 828-2012) | 식별, 변경 통제, 상태 기록, 감사 네 가지. 기준선은 특정 시점에 승인된 형상 | [ANSI 블로그](https://blog.ansi.org/ansi/configuration-management-iso-10007-2017/), [Wikipedia ISO 10007](https://EN.wikipedia.com/wiki/ISO_10007)(2차). IEEE 828-2012는 2023-03-30 폐지로 나온 목록이 있음([SAI Global](https://infostore.saiglobal.com/en-us/Standards/IEEE-828-2012-1521963/), 현행판 미확인) | §4 규칙표의 뼈대(식별 = 이름·번호, 변경 통제 = 커밋·개정, 상태 기록 = 문서 상태, 감사 = 시험) |
| 10 CFR 50 부록 B 기준 III·VI·XVII | III: 설계 변경은 원설계와 같은 수준으로 통제. VI: 품질에 영향을 주는 문서와 그 변경은 승인 뒤 발행. XVII: 기록은 '식별·검색 가능'해야 하고 보존 기간·장소·책임을 정한다 | [Cornell LII](https://www.law.cornell.edu/cfr/text/10/appendix-B_to_part_50) | 문서 머리(작성·검토·승인), 상태 전이, 보존 기간표 |
| ASME NQA-1 요건 6·17 | 부록 B를 구체화. 형상·데이터 관리 직무를 요건 3·5·6·17에 묶는다 | [ANS 발표 2026-01-21](https://sandiego.ans.org/file/2544/NQA-1+Overview+Parts+1+%26+2%2C+ANS+Mtg+1-21-2026.pdf), [Wikipedia](https://en.wikipedia.org/wiki/ASME_NQA)(2차). 조문 원문 미확인 | 위와 같음 |
| KEPIC QAP | 참조 표준이 ASME NQA-1이고 기술 내용은 같게 번안 | [한국과학기술정보 논문](https://koreascience.kr/article/JAKO201174648809751.pdf)(2차). 현행판·조문 미확인 | 조문 번호는 적지 않는다 |
| 설계문서 번호·개정 | 문서마다 고유 번호와 개정 번호. 변경 절차서 자체도 번호·개정으로 관리 | [Eskom 331-85](https://www.eskom.co.za/wp-content/uploads/2024/04/331-85_Design_Documentation_Change_Process.pdf), [NUREG-1397 기록](https://www.osti.gov/biblio/6178666-assessment-design-control-practices-design-reconstitution-programs-nuclear-power-industry) | 문서번호 `HZ-<분류>-<번호>`, 개정 |
| 저장소 구조(Python) | 패키지 폴더, `tests/`, `docs/`, `scripts/`. 앱은 평평한 배치가 흔하다 | [Python Packaging User Guide](https://Packaging.Python.org/discussions/src-layout-vs-flat-layout/) | `hazop/`는 `src/`로 옮기지 않는다 |
| Conventional Commits 1.0.0 | `<종류>(<범위>): <요약>`. `fix`는 수, `feat`는 부, `!`는 호환이 깨지는 변경 | [conventionalcommits.org](https://www.conventionalcommits.org/en/v1.0.0/) | 커밋 규칙 |
| SemVer 2.0.0 | `주.부.수`. `0.y.z`는 초기 개발 | [semver.org](https://semver.org/) | 앱 버전·태그 |
| 결정 기록(ADR) | 결정마다 고정 번호, 상태, 맥락, 결정, 결과 | [Microsoft 플레이북](https://microsoft.github.io/code-with-engineering-playbook/design/design-reviews/decision-log/doc/adr/0001-record-architecture-decisions/), [Red Hat](https://redhat.com/en/blog/architecture-decision-records)(2차) | 결정로그 고정 번호 |

---

## 3. 사용자 결정 (2026-11-10)

개정 0의 권장은 안 B(중간안)였다. 사용자는 아래처럼 정했다(총괄 세션 전달).

| # | 질문 | 결정 |
| --- | --- | --- |
| 1 | 어느 안 | **안 C(엄격안)** |
| 2 | 이름 언어 | **전부 영어.** 한글 최상위 폴더와 한글 파일 이름도 바꾼다 |
| 3 | 날짜 형식 | `2026-11-10`, 시각은 `2026-11-10T1530`. 코드가 찍는 시각 형식은 그대로 |
| 4 | 시험 폴더 보존 | 단위가 끝나고 14일 뒤 지운다. 다시 만드는 비용이 큰 결과(예: `ie-20261109`)는 기간 없이 남긴다 |
| 5 | 문서번호 | `HZ-PLN-07` 같은 영어 약어. 번호와 개정은 **문서 머리**에 적는다(파일 이름에 넣지 않음) |
| 6 | 커밋 | 제목 앞에 `feat:`·`fix:`·`docs:` 같은 종류 표시, 요약과 본문은 한국어 |
| 7 | 승인 | 상태를 '승인'으로 바꾸는 일은 총괄 세션까지 맡긴다 |
| 8 | 시험 폴더 낱개 파일 53개 | 지우지 않고 `2026-11-10-unsorted\` 한 폴더로 모은다 |

결정 5에 따라 개정 0의 안 C 규칙 C1(파일 이름에 문서번호)은 빠졌다. C3(스크립트 하위 폴더)은 §9 질문 2로 남겼다.

---

## 4. 확정 규칙표

### 4.1 공통

| 규칙 | 형식 | 예 |
| --- | --- | --- |
| 글자 | 영어 소문자, 숫자, `-`. Python 파일과 Python이 읽는 JSON 키는 `_` | `study-node-segmentation.md`, `check_naming.py` |
| 금지 | 한글, 공백, `&`, 괄호, 대문자(예외: 도면번호·고유명사 `APR1400`, `SNP-M-101`, 관례 파일 `README.md`·`CLAUDE.md`·`AGENTS.md`·`INTENT.md`·`PROGRESS.md`·`ROADMAP.md`) | `P&ID 도면 샘플` → `pid-samples` |
| 날짜 | 사람이 붙이는 이름은 맨 앞에 `YYYY-MM-DD`, 시각이 필요하면 `YYYY-MM-DDTHHMM`(현지 시각) | `2026-11-10-unsorted`, `2026-11-10T1530-apr1400-run` |
| 코드가 찍는 시각 | 지금 형식 그대로 | `20261108T124409Z-...` |
| 손 버전 금지 | `_v2`, `_draft`, `_final`, `-new` 대신 커밋이나 날짜로 구분 | `계통약어_v2.csv` → `system-codes.csv` 하나 |
| 내용은 한국어 | 파일 안의 글, 커밋 요약·본문, 화면 문구는 한국어 그대로 | — |

### 4.2 폴더

| 최상위 | 무엇 | 하위 규칙 |
| --- | --- | --- |
| `hazop/` | 앱 코드 | `hazop/<단계>/<모듈>.py` |
| `scripts/` | 실행 명령 | §4.4 |
| `tests/` | 단위 시험, 시험 입력, 기준값 | `tests/test_<모듈>.py`, `tests/fixtures/<주제>/`, `tests/baselines/` |
| `packaging/` | 배포 도구 | `verify_*`(배포본 검사), `*_probe`(한 가지 떠보기) |
| `licenses/` | 제3자 고지 | 지금 그대로 |
| `specs/` | 제품 규격(옛 `기획서/`) | `specs/<주제>.md`, 흐름도는 `specs/flows/<번호>-<주제>.md` |
| `design/` | 화면 설계와 시안(옛 `디자인/`) | `design/<주제>.md`, 시안은 `design/mockups/<주제>/<번호>-<화면>[-<폭>].<확장자>` |
| `methodology/` | 방법론 카드(옛 `지식/`) | `methodology/<주제>.md` |
| `records/` | 결정로그·남은 작업(옛 `메모리/`) | `records/decision-log.md`, `records/backlog.md` |
| `resources/` | 읽기 전용 자료(옛 `자원/`) | `library/`(배포본에 묶는 기준 자료), `references/`(참고), `samples/`(표본) |
| `work/` | 개발 작업 루트(옛 `작업/`, git 제외) | 배포본 작업 루트와 같은 배치: `data/`, `output/`, `store/`, `logs/` |
| `docs/` | 작업 단위 기록 | `docs/YYYY-MM-DD-<slug>/`, README 필수 |
| 그 밖 | `CLAUDE.md`, `INTENT.md`, `README.md`, `.claude/`, `.gitignore`, `.gitattributes` | — |

이 목록에 없는 최상위 폴더를 만들려면 사용자 결정을 받는다.

### 4.3 파일

| 대상 | 형식 | 예 |
| --- | --- | --- |
| 문서 | `<주제>[-<부주제>].md`, 영어 kebab-case(소문자와 `-`) | `kg-schema-dictionary.md` |
| 작업 공간 7문서 | `README.md`, `AGENTS.md`, `CLAUDE.md`, `PROGRESS.md`, `ROADMAP.md`, `decisions.md`, `evidence/` | 지금 그대로 |
| 근거 문서 | `evidence/<단위 ID>-<내용>.md` | `evidence/w3-paths.md` |
| 표·데이터 | `<내용>.csv`·`.json`, kebab-case. Python이 키로 읽는 JSON 내부 키는 `snake_case` | `system-codes.csv` |
| 그림 | `<번호>-<내용>[-<폭>].png` | `1-settings-subscription-1366.png` |

### 4.4 스크립트

| 대상 | 형식 | 예 |
| --- | --- | --- |
| 새 스크립트 | `<동사>_<대상>.py`. 동사: `check`(합격·불합격 검사), `build`, `extract`, `export`, `shoot`(스크린샷), `run`, `analyze`, `migrate`(한 번 쓰는 이전), `seed`, `register`, `clean`, `query`, `link`, `compare`, `bench`(측정), `refresh`, `inventory` | `check_naming.py`, `migrate_names.py` |
| 기존 스크립트 | 이름이 이미 영어라 바꾸지 않는다. 앱이 이름으로 불러오기 때문이다(`hazop/app/data.py:40`) | — |
| 동사 없는 기존 7개 | `devenv`, `preflight`, `desktop_lease`, `codemod_data_paths`, `unknowns_breakdown`, `apr1400_key_overlay`, `degrade_raster`는 예외 목록에 둔다 | — |

### 4.5 시험

| 대상 | 형식 | 예 |
| --- | --- | --- |
| 단위 시험 | `tests/test_<모듈 또는 기능>.py` | `tests/test_naming_rules.py` |
| 하네스 검사 | `scripts/check_<대상>.py`. 종료 코드 0이 합격 | `scripts/check_apr1400.py` |
| 배포본 검사 | `packaging/verify_<대상>.py` | `packaging/verify_bundle.py` |
| 시험 입력 | `tests/fixtures/<주제>/<내용>.<확장자>` | `tests/fixtures/docextract/SNP-DOC-102-pzr-pressure-control-design-description-fictional.pdf` |
| 기준값 | `tests/baselines/<대상>.json` | 지금 그대로 |

### 4.6 문서번호와 분류 약어

형식은 `HZ-<분류>-<번호 두 자리>`다. 번호는 한 번 주면 바꾸지 않고, 폐기한 번호도 다시 쓰지 않는다. 기존 문서는 처음 커밋한 날짜 순서로 번호를 준다(§5.2).

| 약어 | 분류 | 대상 | 지금 수 |
| --- | --- | --- | --- |
| `PLN` | 제품 규격 | `specs/*.md` | 20 |
| `FLW` | 흐름도 | `specs/flows/*.md`. 번호는 파일 앞 번호와 같게(`00`~`05`) | 6 |
| `DSN` | 화면 설계 | `design/*.md` | 4 |
| `MTH` | 방법론 | `methodology/*.md` | 1 |
| `REC` | 기록 | `records/*.md` | 3 |
| `GOV` | 운영 규칙·목표 | `INTENT.md`(GOV-01), 이 문서(GOV-02) | 2 |
| `CHK` | 점검표·절차 | `packaging/other-pc-checklist.md` | 1 |

머리를 달지 않는 문서: `README.md`(최상위), `CLAUDE.md`(도구가 읽는 진입 파일), `docs/` 작업 공간 문서(폴더 이름 `YYYY-MM-DD-<slug>`가 식별자), `.claude/` 에이전트·스킬(도구가 읽는 머리가 따로 있음), `licenses/`.

### 4.7 문서 머리 양식

```yaml
---
doc_id: HZ-PLN-20
rev: 2
status: approved        # draft | review | approved | obsolete
author: unit-c-screens  # 작성한 세션 이름이나 사람
reviewed: hazop-reviewer 2026-11-10
approved: director 2026-11-10
---
```

| 항목 | 규칙 |
| --- | --- |
| `rev` | 0부터. 승인된 문서의 내용이 바뀌어 다시 승인될 때 1 올린다. 오탈자·링크 수정은 올리지 않는다. 개정 이력은 git이 맡는다 |
| `status` | `draft`(작성 중) → `review`(검토 담당이 검토를 마침) → `approved`(총괄 또는 사용자가 승인) → `obsolete`(폐기, 파일은 남김). 승인된 문서를 고치면 `review`로 돌아간다 |
| `author` | 영어 세션 이름이나 사람 이름 |
| `reviewed` | `<검토 담당> <날짜>`. 아직이면 `—` |
| `approved` | `director <날짜>`(총괄 세션) 또는 `user <날짜>`. 아직이면 `—` |

### 4.8 식별·버전

| 대상 | 규칙 |
| --- | --- |
| 결정 번호 | `records/decision-log.md`에 고정 번호 열 `DEC-0001`부터. 기존 238행은 지금 행 번호를 그대로 고정 번호로 삼는다. 행 번호로 부르지 않는다 |
| 작업 단위 ID | 두 글자 이상 영어 접두 + 번호(`SC1`, `NR3`). 접두는 `records/README.md`의 'ID 접두 표'에 먼저 등록한다. 이미 쓴 한 글자(`S`, `U`, `D`, `W`, `N`, `P`, `C`, `A`~`E`, `T`)는 새 뜻으로 다시 쓰지 않는다. 기존 기록은 고치지 않는다 |
| 데이터 안의 ID | 검토구간 `S1`, 그래프 ID, 도면번호는 사용자 데이터라 바꾸지 않는다 |
| 앱 버전 | SemVer `0.y.z`를 `APP_VERSION`에 둔다. 배포본을 만들 때 같은 커밋에 태그 `v<버전>`. 작업 루트 이름이 바뀌는 단계 6에서 `0.2.0`으로 올린다 |
| 데이터 형식 버전 | `SCHEMA_VERSION` 등은 그대로. 바꿀 때 커밋 본문에 이유 |

### 4.9 브랜치

| 형식 | 종류 | 예 |
| --- | --- | --- |
| `<종류>/<slug>`, slug는 영어 소문자 kebab-case 4단어 이내 | `feat`, `fix`, `docs`, `chore`, `refactor`, `test` | `chore/naming-migration` |

자동으로 생긴 `claude/*`, `worktree-agent-*` 브랜치는 병합 뒤 지운다. `main`에 직접 커밋하지 않는다.

### 4.10 커밋

```
<종류>(<범위>)!: <한국어 요약>

<한국어 본문: 왜 바꿨는지, 영향, 기준값을 바꿨으면 그 이유>
```

| 항목 | 규칙 |
| --- | --- |
| 종류 | `feat`(기능), `fix`(결함 수정), `docs`(문서), `test`(시험), `refactor`(동작이 같은 정리), `perf`(속도), `build`(배포·빌드), `ci`(CI 설정), `chore`(그 밖), `baseline`(기준값 갱신, CLAUDE.md 규칙 12) |
| 범위 | 선택. 영어 모듈 이름(`study`, `kg`, `extract`, `packaging`, `naming`) |
| `!` | 사용자 데이터나 작업 루트 배치, 파일 형식의 호환이 깨질 때 |
| 요약 | 한국어 한 줄, 끝은 '~한다', 70자 안팎 |
| 예 | `docs(naming): 이름 규칙 확정본과 이전 계획을 남긴다` · `refactor(paths)!: 작업 루트 폴더 이름을 영어로 바꾼다` |

이 규칙은 단계 0의 커밋부터 적용한다. 그 전 227개 커밋은 검사하지 않는다.

### 4.11 저장소 밖

| 대상 | 형식 | 예 |
| --- | --- | --- |
| 시험 폴더 | `D:\HAZOP-trials\<YYYY-MM-DD>-<단위 ID>-<slug>\` | `2026-11-10-unit-b-packaging\` |
| 시험 폴더 README | 주인, 목적, 지워도 되는 하위 폴더, `keep_until`(지울 날짜, 단위 종료 + 14일) 또는 `keep_until: forever`(다시 만드는 비용이 큰 결과) | — |
| 루트 낱개 파일 | 두지 않는다 | — |
| 분류 안 된 것 | `D:\HAZOP-trials\2026-11-10-unsorted\` | — |
| 백업 | `D:\HAZOP-backup\<YYYY-MM-DD>-<무엇>.<확장자>` | `2026-11-10-feat-next-units.bundle` |

### 4.12 보존 기간과 정리 주기

| 종류 | 보존 | 언제 치우나 |
| --- | --- | --- |
| 추적 파일(코드·문서·기록) | 지우지 않는다. 폐기 문서는 `status: obsolete`로 남긴다 | — |
| 사용자 작업 데이터(`work/data`, `work/store`) | 사람이 지울 때까지 | 배포본을 만들 때 백업 |
| 생성 결과(`work/output`) | 구간별 최근 5개 | 주 1회 `clean_outputs.py --keep 5`(목록 확인 뒤 `--apply`) |
| 캐시(`work/data/cache`) | 언제든 지움 | — |
| 시험 폴더 | 단위 종료 + 14일, 비용 큰 결과는 기간 없음 | `preflight.py`가 날짜 지난 폴더를 알림, 지우기는 사람 확인 뒤 |
| 실행 중 임시 파일 | 실행 끝나면 | `preflight.py --clean-temp` |
| 병합된 브랜치·작업트리 | 단위가 끝날 때 | `git branch -d`, `git worktree remove` |

---

## 5. 한글 → 영어 이름 대응표

표의 '근거'는 이름을 고른 이유다. 고르기 어려운 이름은 §9 질문 1에 모았다. 굵은 이름은 코드가 읽는 경로라 단계 5·6에서 코드와 함께 바꾼다.

### 5.1 최상위

| 지금 | 새 이름 | 근거 |
| --- | --- | --- |
| `기획서/` | `specs/` | 담긴 것이 '앞으로 만들 제품의 규격'이다. `plans/`는 일정 계획과 헷갈린다 |
| `flow chart/` | `specs/flows/` | 흐름도는 규격의 한 부분이고, 파일 이름(`00-overview.md`)은 이미 영어 |
| `디자인/` | `design/` | 그대로 옮김 |
| `지식/` | `methodology/` | 방법론 카드다. `knowledge/`로 하면 지식그래프(`knowledge-graph`)와 다시 겹친다(사례 13) |
| `메모리/` | `records/` | 결정로그·남은 작업은 품질보증의 '기록'(부록 B 기준 XVII)이다. `memory/`는 에이전트 메모리와 헷갈린다 |
| **`자원/`** | **`resources/`** | 그대로 옮김 |
| **`작업/`** | **`work/`** | 그대로 옮김. 배포본 작업 루트 `%LOCALAPPDATA%\HAZOP` 안 배치도 같이 바뀐다 |
| `데이터/`(빈 폴더) | 지움 | 추적 파일 0 |
| `참고자료/`(빈 폴더) | 지움 | 추적 파일 0 |

### 5.2 `specs/`, `design/`, `methodology/`, `records/` 문서 (번호는 처음 커밋한 날짜순)

| 지금 | 새 이름 | 문서번호 |
| --- | --- | --- |
| `기획서/전체기획.md` | `specs/overview.md` | HZ-PLN-01 |
| `기획서/정보통합관리.md` | `specs/integration.md` | HZ-PLN-02 |
| `기획서/자료등록.md` | `specs/registration.md` | HZ-PLN-03 |
| `기획서/정보추출.md` | `specs/extraction.md` | HZ-PLN-04 |
| `기획서/HAZOP분석.md` | `specs/hazop-analysis.md` | HZ-PLN-05 |
| `기획서/검토결과관리.md` | `specs/review-results.md` | HZ-PLN-06 |
| **`기획서/HAZOP기법지침.md`** | **`specs/hazop-method-guide.md`** | HZ-PLN-07 |
| `기획서/그래프조사.md` | `specs/graph-survey.md` | HZ-PLN-08 |
| `기획서/그래프활용.md` | `specs/graph-usage.md` | HZ-PLN-09 |
| `기획서/인터페이스.md` | `specs/interface.md` | HZ-PLN-10 |
| `기획서/단계연쇄검사.md` | `specs/stage-chain-check.md` | HZ-PLN-11 |
| `기획서/평가기준비교.md` | `specs/criteria-comparison.md` | HZ-PLN-12 |
| `기획서/지식그래프-스키마.md` | `specs/kg-schema.md` | HZ-PLN-13 |
| `기획서/지식그래프-스키마-사전.md` | `specs/kg-schema-dictionary.md` | HZ-PLN-14 |
| `기획서/지식그래프-스키마-입력.md` | `specs/kg-schema-input.md` | HZ-PLN-15 |
| `기획서/초기사건-HAZOP-조사.md` | `specs/ie-hazop-survey.md` | HZ-PLN-16 |
| `기획서/초기사건-출력설계.md` | `specs/ie-output-design.md` | HZ-PLN-17 |
| `기획서/AI연결-구독제.md` | `specs/ai-subscription.md` | HZ-PLN-18 |
| `기획서/PID-기호사전.md` | `specs/pid-symbol-dictionary.md` | HZ-PLN-19 |
| `기획서/검토구간-분할설계.md` | `specs/study-node-segmentation.md` | HZ-PLN-20 |
| `기획서/.gitkeep` | 지움 | 폴더에 파일이 있으므로 필요 없음 |
| `flow chart/00-overview.md` ~ `05-review-results.md` | `specs/flows/00-overview.md` ~ `05-review-results.md` | HZ-FLW-00 ~ 05 |
| `flow chart/.gitkeep` | 지움 | 위와 같음 |
| `디자인/출력화면AX-데모분석.md` | `design/output-screen-ax-demo.md` | HZ-DSN-01 |
| `디자인/지식그래프화면.md` | `design/kg-screen.md` | HZ-DSN-02 |
| `디자인/화면명세.md` | `design/screen-spec.md` | HZ-DSN-03 |
| `디자인/AI연결-화면설계.md` | `design/ai-connection-screens.md` | HZ-DSN-04 |
| `지식/위험도분석-결합방법론.md` | `methodology/combined-risk-methods.md` | HZ-MTH-01 |
| `메모리/README.md` | `records/README.md` | HZ-REC-01 |
| `메모리/결정로그.md` | `records/decision-log.md` | HZ-REC-02 |
| `메모리/남은작업.md` | `records/backlog.md` | HZ-REC-03 |
| `INTENT.md` | 그대로 | HZ-GOV-01 |
| `packaging/다른PC-점검표.md` | `packaging/other-pc-checklist.md` | HZ-CHK-01 |

### 5.3 `design/mockups/` (옛 `디자인/시안/`, 추적 파일 119개 중 한글 이름 106개)

| 지금 | 새 이름 |
| --- | --- |
| `디자인/시안/` | `design/mockups/` |
| `시안/AI연결/` | `mockups/ai-connection/` |
| `AI연결/1-연결설정-구독` · `2-연결설정-API키` · `3-연결설정-실행중` · `4-구독처음사용` · `5-연결칩` · `6-실행확인` · `7-한도도달` · `8-결과기록` · `9-상태안내` · `10-배포본` (각 `.html`, `-1366.png`, `-1920.png`) | `1-settings-subscription` · `2-settings-api-key` · `3-settings-running` · `4-subscription-first-use` · `5-connection-chip` · `6-run-confirm` · `7-limit-reached` · `8-result-record` · `9-status-notice` · `10-bundle` |
| `시안/UIUX-디테일/` | `mockups/uiux-detail/` |
| `1-결과-셸` · `2-구간-미리보기` · `3-명령팔레트` · `4-등록-진행오류` · `5-결과-빈상태` (`.html`, `png/*-1366.png`, `png/*-1920.png`) | `1-results-shell` · `2-region-preview` · `3-command-palette` · `4-register-progress-error` · `5-results-empty` |
| `UIUX-디테일/개선명세.md` · `결함목록.md` · `조사요약.md` | `improvement-spec.md` · `defect-list.md` · `survey-summary.md` |
| `시안/완성본/` | `mockups/final/` |
| `완성본/A-밝은미니멀/` · `B-고밀도작업대/` · `C-다크대시보드/` | `a-light-minimal/` · `b-dense-workbench/` · `c-dark-dashboard/` |
| 그 안 `1-자료등록` · `2-도면추출` · `3-지식그래프` · `4-검토구간` 등 화면 이름 | `1-registration` · `2-drawing-extract` · `3-knowledge-graph` · `4-study-nodes` 등. 전체 목록은 단계 3에서 `build.py`의 이름표로 만든다(이 시안들은 각 폴더의 `build.py`가 이름을 정해 찍는다) |
| `시안/초기사건/` | `mockups/initiating-events/` |
| `초기사건/6-그룹` · `6-완전성대조` | `6-groups` · `6-completeness-check` |
| `시안/interface-mockup.html`, `kg-graph-mockup.html`, `README.md` | 그대로 |

### 5.4 `docs/` 안

| 지금 | 새 이름 |
| --- | --- |
| `docs/screenshots-pdf/` | `docs/2026-11-07-screenshots-pdf/` |
| `docs/2026-11-05-design-system/evidence/w1-조사.md` · `w2-1366기준.md` · `w3-작업영역125.md` · `w4-토큰.md` · `w5-명암비.md` · `w6-앱색.md` · `w7-선택표시.md` · `w8-반투명선.md` · `w9-허용목록.md` · `w10-범례칩.md` | `w1-survey.md` · `w2-1366-baseline.md` · `w3-workspace-125.md` · `w4-tokens.md` · `w5-contrast.md` · `w6-app-colors.md` · `w7-selection.md` · `w8-translucent-lines.md` · `w9-allowlist.md` · `w10-legend-chips.md` |
| `docs/2026-11-05-input-adapter/evidence/w1-조사.md` · `w2-하네스.md` · `w4-래스터.md` · `w5-열화.md` | `w1-survey.md` · `w2-harness.md` · `w4-raster.md` · `w5-degradation.md` |
| `docs/2026-11-05-packaging/evidence/w1-조사.md` · `w3-경로.md` · `w4-빌드.md` · `w5-신뢰경계.md` · `w6-라이선스.md` · `w6-묶음수집목록.md` · `w8-경로통제.md` · `w8b-모듈제외.md` · `w9-고지원문.md` · `w10-정보창.md` · `w11-최종빌드.md` | `w1-survey.md` · `w3-paths.md` · `w4-build.md` · `w5-trust-boundary.md` · `w6-licenses.md` · `w6-bundle-collect-list.md` · `w8-path-control.md` · `w8b-module-exclusion.md` · `w9-notice-text.md` · `w10-about-dialog.md` · `w11-final-build.md` |
| `docs/2026-11-09-symbol-library/그림/도면/`(60) · `그림/범례/`(239) | `figures/drawings/` · `figures/legend/` |
| `docs/2026-11-09-symbol-library/도면미분류묶음.csv` · `라벨_APR1400.csv` · `범례항목.csv` · `사전항목_시제품.csv` · `항목정보.csv` | `drawing-unclassified-groups.csv` · `labels-apr1400.csv` · `legend-items.csv` · `dictionary-items-prototype.csv` · `item-info.csv` |
| `docs/2026-11-10-lessons/D드라이브-이전.md` | `d-drive-move.md` |
| `docs/2026-11-10-plan/pstack-자문.md` · `향후작업-세션배치.html` | `pstack-advice.md` · `session-plan.html` |
| `docs/2026-11-09-data-consolidation/inventory/*` | 그대로(영어) |

### 5.5 `resources/` (옛 `자원/`, 추적 162개 + 추적 안 하는 큰 파일)

| 지금 | 새 이름 | 근거 |
| --- | --- | --- |
| **`자원/기준/`** | **`resources/library/`** | 배포본에 묶는 기준 자료 묶음. `standards/`는 KEPIC 같은 기술기준, `baseline/`은 회귀 기준값과 겹친다 |
| **`기준/기준표/`** | **`library/risk-criteria/`** | 위험도 기준표(`kosha-p86-2017-risk-criteria.json`), 초기사건 분류표 |
| **`기준/기호/`** | **`library/symbols/`** | 기호 사전 |
| **`기호/묶음.json`** | **`symbols/bundles.json`** | 파일 안 키가 이미 `bundles` |
| **`기호/공통/`** | **`symbols/common/`** | 파일 안 `prefix`가 이미 `common` |
| **`기호/APR1400/그림/`**, **`공통/그림/`** | **`.../images/`** | — |
| **`기준/이탈후보/`** | **`library/deviations/`** | 이탈 후보 카탈로그·적용 판단 |
| **`기준/패턴/`** | **`library/patterns/`** | 원인·결과 패턴 |
| **`자원/참고자료/`** | **`resources/references/`** | — |
| **`참고자료/P&ID 도면 샘플/`** | **`references/pid-samples/`** | 공백·`&` 제거. 안의 `SNP-M-101_RCS-main-loop` 등은 그대로(이미 영어, 기준값 키) |
| **`참고자료/P&ID 기호 카탈로그/`** | **`references/pid-symbol-catalog/`** | 안의 파일은 이미 영어 |
| `참고자료/참고 사진/`(추적 안 함) | `references/photos/` | 로컬 전용 |
| `참고자료/HAZOP 기법/`(PDF는 추적 안 함) | `references/hazop-method/` | 로컬 전용. PDF 이름 `P-86-2017 회분식 공정의 …pdf` → `kosha-p-86-2017-batch-hazop-guide.pdf` |
| **`APR1400_DCD/계통약어.csv`** | **`APR1400_DCD/system-codes.csv`** | `scripts/build_system_codes.py`가 만드는 표 |
| **`APR1400_DCD/도면목록.csv`** · `도면목록.md` | **`drawing-list.csv`** · `drawing-list.md` | — |
| **`APR1400_DCD/후보_제외도면.csv`** | **`excluded-drawings.csv`** | — |
| **`APR1400_DCD/스크립트/`** | **`APR1400_DCD/scripts/`** | `extract_pid.py`, `make_index.py` |
| **`APR1400_DCD/원본/`**, **`도면별/`**(추적 안 함, 약 411MB) | **`source/`**, **`by-drawing/`** | 각 PC에서 손으로 옮긴다 |
| `APR1400_DCD/APR1400_DCD_Rev3_PID_전체.pdf`(추적 안 함) | `APR1400_DCD_Rev3_PID_all.pdf` | — |
| **`자원/표본/`** | **`resources/samples/`** | — |
| **`표본/고정응답/`** · **`구간/`** · **`지식/`** · **`평가기준/`** | **`fixed-responses/`** · **`regions/`** · **`knowledge-graph/`** · **`evaluation-criteria/`** | 작업 루트 쪽 이름과 같게 |

### 5.6 `work/` (옛 `작업/`)와 배포본 작업 루트. 모두 코드가 만드는 이름

| 지금 | 새 이름 | 코드 위치 |
| --- | --- | --- |
| `작업/` | `work/` | `paths.DEV_WORK_ROOT` |
| `데이터/` | `data/` | `FOLDERS` "작업데이터" |
| `데이터/구간` · `고정응답` · `지식` · `검토구간` · `분석결과` · `분석결과-시험` · `백업` · `초기사건` · `도면수정` · `도면연결` · `잠재후보` · `캐시` | `data/regions` · `fixed-responses` · `knowledge-graph` · `study-nodes` · `analysis-results` · `analysis-results-test` · `backup` · `initiating-events` · `drawing-edits` · `drawing-links` · `latent-candidates` · `cache` | `paths.FOLDERS` |
| `기호후보/` | `symbol-candidates/` | `paths.FOLDERS` |
| `자료저장소/` | `store/` | `paths.store_root()`. 안의 `originals/<material_id>/…`는 이미 영어이고 `storage_ref`는 프로젝트 폴더 기준 상대 경로라 기록을 고치지 않아도 된다 |
| `출력/` | `output/` | `paths.output_root()` |
| `출력/그래프` · `분석` · `추출` · `지식그래프` · `뷰어` · `스크린샷` · `사용자검증` · `디자인검사` · `근거묶음` · `워크시트` · `평가비교` · `내보내기` | `output/graph` · `analysis` · `extract` · `knowledge-graph` · `viewer` · `screenshots` · `user-scenarios` · `design-check` · `evidence-bundles` · `worksheets` · `evaluation-compare` · `exports` | `scripts/*`, `hazop/*`에 흩어진 문자열(§6.1) |
| `출력/_보관/` | `output/_archive/` | `scripts/clean_outputs.py` |
| `백업/_외부/` | `backup/_external/` | `paths.EXTERNAL_BACKUP_DIR` |
| `데이터/백업/20261108T124409Z-판이전` 같은 기존 백업 폴더 | 그대로 | 코드가 찍은 이름(결정 3) |
| `logs/`, `cache/`, `cli-run/` | 그대로 | 이미 영어 |

`paths.FOLDERS`의 키(`"이탈후보"` 등)도 영어(`"deviations"` 등)로 바꾼다. 코드 안의 식별자라 사용자에게 보이지 않지만, 규칙 2(전부 영어)와 `test_path_literals.py`의 단순화를 위해서다.

### 5.7 저장소 밖

| 지금 | 새 이름 |
| --- | --- |
| `D:\HAZOP-trials\` 루트 낱개 파일 53개 | `D:\HAZOP-trials\2026-11-10-unsorted\`(README에 원래 위치와 '분류 전' 표시) |
| `ie-20261109\` | `2026-11-09-ie-subscription-run\`, `keep_until: forever` |
| `apr1400-2026-11-09\`, `apr1400-final-2026-11-10\`, `symbols-2026-11-09\`, `u5-20261109\`, `node-seg-20261109\`, `pkg-20261110\` | `2026-11-09-apr1400\`, `2026-11-10-apr1400-final\`, `2026-11-09-symbols\`, `2026-11-09-u5\`, `2026-11-09-node-seg\`, `2026-11-10-unit-b-packaging\` |
| `manual-1802\`, `u1-wip-1732\`, `u2-dev\`, `u3-check\`, `arch-s1\`, `adv-par\`, `pairs\`, `symbols-impl\` | 날짜를 모르므로 폴더 수정 시각으로 `<YYYY-MM-DD>-<지금 이름>\` |
| `wt-*` 5개(분리 작업트리) | 옮기지 않고 `git worktree remove`로 지운다(작업트리는 경로를 절대 경로로 적는다) |
| `D:\HAZOP-backup\feat-next-units.bundle`, `*.log` | `2026-11-10-feat-next-units.bundle`, `2026-11-10-<무엇>.log` |

2026-11-10 이전 문서에 적힌 시험 폴더 경로(예: `D:\HAZOP-trials\symbols-2026-11-09`)는 옛 이름이다. 그 문서들은 지난 기록이라 고치지 않는다. 새 이름은 이동 기록 `evidence/step1-moves.csv`에서 찾는다.

---

## 6. 이전 위험과 대책

### 6.1 `hazop/paths.py`의 `FOLDERS`와 `LEGACY_PREFIXES`

- **위험.** 데이터 폴더 21개가 이 표 하나로 열린다(`paths.folder` 호출 224곳, 파일 87개). 반대로 `출력/` 아래 이름(`그래프`, `분석`, `추출`, `지식그래프` 등)은 표에 없고 각 스크립트와 모듈이 문자열로 적는다. `"출력` 문자열은 파일 55개 209줄, `"그래프`는 80개 179줄에 나온다(`git grep -c -F '"출력' -- '*.py'`). 화면 문구도 섞여 있어 실제 경로 문자열 수는 이보다 적다(미확인).
- **대책.** 단계 6 앞에 `output_root()`처럼 `FOLDERS`에 출력 하위 폴더 행을 더하는 정리 단위를 먼저 둔다(CLAUDE.md 규칙 4 "두 번 막히면 파일을 나누는 단위를 먼저"). 그다음 이름 바꾸기는 표 한 곳만 고치면 된다. `LEGACY_PREFIXES`에는 옛 한글 접두를 지우지 말고 새로 더한다(`자원/기준/이탈후보/` → `deviations` 등). 사용자 파일에 남은 옛 경로는 계속 읽혀야 한다.

### 6.2 그래프 판(`graph_version`)과 표본 JSON의 `inputs`

- **위험 1: 그래프 판.** `graph_version`은 추출 결과 전체(JSON)의 해시다(`hazop/graph/build.py:78`). 추출 결과의 `source.file`에는 `참고자료/P&ID 도면 샘플/SNP-M-101_RCS-main-loop/…drawio` 같은 기록용 논리 경로가 들어간다(`paths.rel_or_abs`). 샘플 폴더 이름을 `pid-samples`로 바꾸면 이 문자열이 바뀌어 샘플 6장의 그래프 판이 모두 바뀐다. 그러면 구간 JSON의 `graph_ref`가 맞지 않게 되고(`hazop/analysis/run.py:125`), 고정 응답의 `bundle_sha256`도 다시 매겨야 할 수 있다(`scripts/refresh_fixture_hashes.py`).
- **대책(권장).** 기록용 논리 경로는 폴더 이름이 아니라 **데이터 식별자**로 본다. `paths.rel_or_abs`가 새 폴더 `references/pid-samples/` 아래 파일을 지금처럼 `참고자료/P&ID 도면 샘플/…`로 적게 대응표를 한 줄 둔다. 판이 바뀌지 않으므로 재연결과 해시 재계산이 필요 없다. 다른 길은 §9 질문 3이다.
- **위험 2: 표본 `inputs`.** `resources/samples/regions/region-SNP-M-102-pzr.json`의 `inputs`는 `데이터/이탈후보/kosha-p86-2017-deviation-chart.json`처럼 옛 경로를 적는다. 읽을 때 `LEGACY_PREFIXES`가 푼다.
- **대책.** 표본 파일은 고치지 않는다. 고치면 표본을 복사해 만드는 시험 데이터와 고정 응답이 함께 흔들린다. 대신 `LEGACY_PREFIXES`가 새 폴더로 풀게만 한다.
- **위험 3: 지침서·카탈로그 해시 고정.** `hazop/analysis/integrity.py`는 `기획서/HAZOP기법지침.md`의 SHA-256(`GUIDE_SHA256`)과 카탈로그 JSON 4개의 SHA-256(`PINNED_SHA256`)을 고정해 둔다. 지침서에 문서 머리를 달거나, 카탈로그 JSON 안의 출처 문자열(`"기획서/HAZOP기법지침.md §5.3"`)을 고치면 무결성 검사가 실패한다.
- **대책.** 지침서 이동·머리 추가와 해시 재고정을 한 커밋에 넣고, 커밋 본문에 새 해시와 이유를 적는다. 카탈로그 JSON 안의 출처 문자열은 '어느 문서에서 왔나'라는 기록이므로 고치지 않는다. 지침서의 옛 이름은 `HZ-PLN-07`로 찾을 수 있게 대응표(§5.2)에 남긴다. `catalog_md.py`가 지침서 표를 파싱하므로, 머리를 단 뒤에도 같은 카탈로그가 나오는지 `tests/test_integrity_pins.py`로 확인한다.
- **위험 4: 지식그래프 CSV 출처.** `resources/samples/knowledge-graph/SNP-SAMPLE/*.csv`와 `tests/fixtures/kg/*/*.csv`에 `기획서/…` 출처가 들어 있다(`grep -rl 기획서 자원 tests/fixtures`). 이것도 출처 기록이다.
- **대책.** 고치지 않는다. 링크로 열어야 하는 화면이 있으면 읽을 때 옛 문서 경로를 새 경로로 바꾸는 대응표(§5.2 기반)를 `paths`에 둔다.

### 6.3 기준값 파일(`tests/baselines/`)

- **위험.** `snp_baseline.json`과 `apr1400_score.json` 안에는 한글 경로가 없다(`grep -c 자원 tests/baselines/*.json` = 0). 키는 샘플 폴더 이름(`SNP-M-101_RCS-main-loop`)과 정답지 이름이고, 둘 다 바뀌지 않는다. 다만 기호 사전 폴더를 옮기면 `scripts/devenv.py`의 갱신 잠금이 그 폴더를 '점수에 닿는 입력의 수정'으로 본다(`SCORING_PATHS`).
- **대책.** 이전 단계에서는 기준값을 갱신하지 않는다. 옮긴 뒤 `check_snp_baseline.py`와 `check_apr1400.py`를 `--update` 없이 돌려 **점수가 그대로**인지 본다. 점수가 1이라도 바뀌면 이전에 결함이 있는 것이다. 되돌리고 원인을 찾는다. `SCORING_PATHS`는 `paths.folder_rel`로 만들어지므로 따라 바뀐다. `check_apr1400.py`는 추적하지 않는 `APR1400_DCD/도면별/`과 `계통약어.csv`가 새 이름으로 옮겨져 있어야 돈다. 저장소 밖 시험 폴더의 사본도 같다.

### 6.4 `tests/test_path_literals.py`가 막는 문자열

- **위험.** 지금 금지 패턴은 경로 구성요소 `데이터|참고자료|자원|작업`이다. 영어로 바꾼 뒤 `data`, `work`, `resources` 같은 흔한 단어를 그대로 막으면 엉뚱한 문자열까지 걸린다.
- **대책.** 새 금지 목록은 두 가지다. ① 새 최상위 이름이 경로의 첫 구성요소로 나올 때(`resources/…`, `work/…`, 앞이 `/`이거나 문자열 맨 앞). ② 옛 한글 이름 전부(`데이터`, `참고자료`, `자원`, `작업`, `기준`, `표본`, `출력`, `자료저장소`, `기획서`, `디자인`, `메모리`, `지식`). ②는 `paths.py`의 옛 경로 대응표와 이전 도구만 허용한다. 이렇게 하면 이전 뒤 누가 옛 한글 경로를 새로 쓰는 일도 막힌다.

### 6.5 배포본이 묶는 자원 경로

- **위험.** `scripts/build_package.py`의 `DATA_DIRS`는 `FOLDERS`의 resource 행에서 만들어져 따라 바뀐다. 하지만 지침서는 `"기획서/HAZOP기법지침.md"`로 직접 적혀 있고(74행), `hazop/analysis/integrity.py`(`GUIDE_PARTS`), `hazop/analysis/catalog_md.py`(`GUIDE_DOC`), `packaging/w4_flow.py`(`GUIDE_REL`)에도 같은 문자열이 있다. 배포본 안에서도 같은 상대 위치를 쓰므로 한 곳이라도 빠지면 배포본에서만 지침서를 못 찾는다. 지금 `packaging/`은 단위 B가 고치는 중이다(`git status`: `lock_probe.py`, `verify_bundle.py`, `다른PC-점검표.md` 수정).
- **대책.** 지침서 경로를 `FOLDERS`에 한 행(`"guide"`)으로 올리고 네 곳이 그 행을 쓰게 한다. 이 정리를 단계 3 앞에 넣는다. 단계 3과 5에서는 배포본을 실제로 빌드하고 `packaging/verify_bundle.py`로 확인한다. `packaging/` 파일은 단위 B가 끝나고 커밋한 뒤에만 건드린다.

### 6.6 사용자 작업 루트(`%LOCALAPPDATA%\HAZOP`)에 이미 저장된 옛 경로

- **위험.** 이 PC의 배포본 작업 루트에 이미 `자료저장소/`와 `출력/`이 있다(`ls "$LOCALAPPDATA/HAZOP"`). 다른 PC에 깐 배포본도 같다(`packaging/다른PC-점검표.md`). 새 버전이 `store/`, `output/`만 보면 사용자의 등록 자료와 분석 결과가 '없는 것'처럼 보인다. 설정 파일 `%APPDATA%\HAZOP\settings.json`의 `recent_runs`·`recent_regions`는 절대 경로를 적어서 옛 폴더를 가리킨다. 분석 결과(`analysis.json`)의 `inputs` 기록, 검토 기록, 평가 비교 보고서도 옛 상대 경로를 담을 수 있다(전수는 미확인).
- **대책.**
  1. 이전 도구 `scripts/migrate_names.py`를 만든다. 기존 `scripts/migrate_data_layout.py`처럼 기본은 목록만 보여 주고, `--apply`일 때 **복사**한 뒤 해시를 비교하고 `manifest.json`을 남긴다. 옛 폴더는 지우지 않고 `_before-0.2.0`으로 이름만 바꾼다. `--undo <manifest>`로 되돌린다.
  2. 앱은 `0.2.0`부터 시작할 때 옛 한글 폴더를 찾으면 이전할지 묻는다(§9 질문 4). 거절하면 옛 폴더를 읽기 전용으로 연다.
  3. 설정 파일의 경로는 읽을 때 옛 접두를 새 접두로 바꿔 보고, 저장할 때 새 경로로 쓴다.
  4. 사용자 파일 안의 상대 경로는 고치지 않고 `LEGACY_PREFIXES`로 읽는다(2026-11-09 정리와 같은 원칙).
  5. 개발 환경의 `D:\HAZOP\작업\`도 같은 도구로 옮긴다. `.gitignore`의 `작업/` 줄은 `work/`로 바꾸되, 옛 줄도 한동안 둔다.

### 6.7 git 이력 추적(`git mv`)

- **위험.** 이름을 바꾸면서 같은 커밋에서 내용을 많이 고치면 git이 '이동'이 아니라 '삭제 + 새 파일'로 보고, `git log --follow`로 이력을 이어 볼 수 없다.
- **대책.** 단계마다 커밋을 둘로 나눈다. ① `git mv`만 한 커밋(내용 변경 0). ② 링크·경로 문자열·머리를 고친 커밋. 이력은 `git log --follow specs/interface.md`로 확인한다. 한글 경로는 `git -c core.quotepath=off`로 봐야 읽힌다. 단계마다 시작 전에 `git bundle create D:\HAZOP-backup\<날짜>-before-step<n>.bundle --all`로 백업한다.

### 6.8 `.claude/` 에이전트·스킬 안의 경로

- **위험.** `.claude/agents/hazop-designer.md`(`디자인/`), `hazop-developer.md`, `hazop-planner.md`(`기획서/`, `flow chart/`), `hazop-recorder.md`(`메모리/결정로그.md` 등), `.claude/skills/verify-hazop/SKILL.md`와 `features/README.md`가 옛 경로를 적는다(`git grep -l -E '기획서/|디자인/|메모리/|자원/|작업/|flow chart' -- .claude`). 고치지 않으면 담당 에이전트가 없는 폴더에 문서를 새로 만든다. 저장소 밖 `~/.claude/skills/init-work`와 에이전트 메모리(`~/.claude/projects/D--HAZOP/memory/*.md`)도 옛 경로를 적을 수 있다(미확인).
- **대책.** 각 단계의 ② 커밋에 `.claude/` 수정을 함께 넣는다. 저장소 밖 메모리는 단계가 끝날 때 총괄이 고친다. `test_naming_rules.py`가 `.claude/` 안의 옛 한글 경로도 찾는다.

### 6.9 `CLAUDE.md`, `INTENT.md`, 기록 문서 안의 링크

- **위험.** 문서 88개에 옛 최상위 경로 언급이 480곳 있다(`git grep -c -E '(기획서|디자인|메모리|지식|자원|작업|flow chart)/' -- '*.md' '*.html'`). 그중 `메모리/결정로그.md`가 86곳, `README.md` 38곳, `INTENT.md` 16곳이다. 결정로그는 링크가 136개다. 이 문서들은 결정의 근거라서 링크가 깨지면 '식별·검색 가능'(부록 B 기준 XVII)을 잃는다.
- **대책.** 링크 바꾸기를 사람이나 세션이 손으로 하지 않는다. 기존 `scripts/codemod_data_paths.py`처럼 §5 대응표를 입력으로 받는 `scripts/migrate_names.py --rewrite-links`가 `.md`·`.html`의 상대 링크와 백틱 경로만 바꾸고, 바꾼 줄 목록을 남긴다. 바꾼 뒤 '링크 대상이 실제로 있는가'를 검사한다(§8.1 N9). 결정로그·남은작업의 **본문 문장**에 적힌 옛 이름은 그 시점의 기록이라 링크 말고는 고치지 않는다.

### 6.10 다른 세션과의 충돌

- **위험.** CLAUDE.md 규칙 4는 저장소 전체를 옮기는 일을 다른 세션이 돌지 않을 때만 하게 한다. 지금은 단위 B(패키징)가 같은 체크아웃에서 `packaging/`를 고치고 있다. 다른 세션의 작업트리나 브랜치는 옛 경로를 기준으로 만들어져 있어서, 이전 뒤 병합하면 옛 경로에 새 파일이 다시 생긴다.
- **대책.**
  1. 단계 0~2는 코드와 겹치는 파일이 적어 다른 세션이 돌아도 할 수 있다. 다만 단계 2의 `docs/`는 그 작업 공간을 쓰는 세션이 없을 때 한다.
  2. 단계 3~6은 `ListAgents`·세션 목록에서 돌고 있는 세션이 0일 때 시작하고, 시작 전에 열린 브랜치·작업트리를 모두 병합하거나 닫는다.
  3. 단계 사이에 새 세션을 띄울 때는 작업지시서 머리말(§8.3)에 '지금 이름'을 적는다.
  4. 이전 뒤 옛 경로에 파일이 생기면 `test_naming_rules.py`가 바로 실패한다.

---

## 7. 이전 단계

모든 단계는 `chore/naming-migration` 같은 한 브랜치에서 한다. 단계마다 ① `git mv`만 한 커밋과 ② 내용 수정 커밋으로 나눈다. 시험은 시험용 venv(`%USERPROFILE%\.hazop\venv-py312\python.exe`, `PYTHONIOENCODING=utf-8`)로 돌린다(CLAUDE.md 규칙 11).

| 단계 | 옮기는 것 | 수 | 다른 세션 | 확인 | 되돌리기 |
| --- | --- | --- | --- | --- | --- |
| **0. 규칙 도입** | 옮기지 않음. 이 문서 승인, CLAUDE.md 규칙 18, 작업지시서 머리말, `tests/test_naming_rules.py`(지금 위반을 모두 예외 목록에 넣은 상태), 커밋 메시지 검사, `preflight.py` 경고 | 파일 이동 0 | 돌아도 됨(`CLAUDE.md` 주인 확인) | 전체 unittest, `test_naming_rules`가 통과 | 커밋 revert |
| **1. 저장소 밖·브랜치** | 시험 폴더 낱개 53개를 `2026-11-10-unsorted\`로 모음, 시험 폴더 이름(§5.7), README 채움, 병합된 로컬 브랜치 16개와 `wt-*` 작업트리 5개 정리, 백업 이름 | 폴더 이름 약 15개, 파일 53개, 브랜치 16개, 작업트리 5개 | 그 폴더의 주인 세션이 끝났을 때만 | `preflight.py` 경고 0, `git worktree list` | 이동 기록(`moves.csv`)대로 되돌림. 브랜치는 시작 전 bundle과 reflog로 되살림 |
| **2. `docs/` 안** | §5.4: evidence 25개, symbol-library CSV 5개와 그림 폴더 2개(299파일), lessons·plan 3개, `screenshots-pdf` 날짜 붙이기, README 없는 3곳에 README | 파일 약 335개 | 그 작업 공간을 쓰는 세션이 없을 때 | 링크 대상 검사(N9), unittest | ①② 커밋 revert |
| **3. 사람 문서 폴더** | `기획서/`→`specs/`, `flow chart/`→`specs/flows/`, `디자인/`→`design/`(시안 106개 이름 포함), `지식/`→`methodology/`, `메모리/`→`records/`, `packaging/다른PC-점검표.md`, 문서 머리 37개, 결정로그 번호 열, 지침서 해시 재고정, `.claude/` 경로, 링크 480곳. 앞서 지침서 경로를 `FOLDERS`로 모으는 정리 1커밋 | 파일 약 155개 | **다른 세션 0**(문서·`.claude/`를 모두 건드림), 단위 B 완료 뒤 | unittest(특히 `test_integrity_pins`, `test_packaging`), 시안 `build.py` 재실행으로 같은 그림이 나오는지, 배포본 빌드 + `verify_bundle.py`, 링크 검사 | ①② 커밋 revert. 지침서 해시는 ②에 함께 있어 같이 돌아감 |
| **4. 시험 입력의 한글 이름** | `tests/fixtures/docextract/SNP-DOC-102_가압기압력제어_설계설명서(가상).pdf`(이 파일을 만드는 `make_design_doc.py`와 읽는 시험 함께) | 파일 1개 + 코드 | 돌아도 됨 | 해당 시험, 전체 unittest | revert |
| **5. `자원/` → `resources/`** | §5.5 전체: 추적 162개, 추적 안 하는 APR1400 원본·도면별·PDF·사진(각 PC에서 손으로), `FOLDERS` resource·repo 행, `LEGACY_PREFIXES` 추가, 샘플 논리 경로 고정(§6.2), `test_path_literals.py` 패턴, `.gitignore`, `devenv.py` 확인 | 추적 162개 + 로컬 약 411MB | **다른 세션 0** | unittest, `check_snp_baseline.py`와 `check_apr1400.py`를 `--update` 없이(점수 그대로여야 함, '맞은 수/분모 @커밋'으로 기록), `refresh_fixture_hashes.py --check`, 배포본 빌드 + `verify_bundle.py`, 앱 S1~S6 시나리오(`check_user_scenarios.py`, 데스크톱 잠금 안에서) | ①② revert. 추적 안 하는 파일은 이동 기록으로 되돌림 |
| **6. `작업/` → `work/`, 출력 하위 이름** | 앞서 출력 하위 폴더를 `FOLDERS`로 모으는 정리 단위. 그다음 §5.6 전체, `FOLDERS` 키 영어화, `scripts/migrate_names.py`(복사·해시 비교·manifest·undo), 앱 시작 시 옛 폴더 감지, 설정 파일 경로 변환, `APP_VERSION` `0.2.0`과 태그 | 코드 이름 약 30종, 파일 수십 개(정리 단위에서 셈), 사용자 작업 루트 2곳(개발, 이 PC 배포본) | **다른 세션 0** | unittest, 임시 작업 루트에 옛 배치를 만들어 이전 도구 `--apply`·`--undo` 왕복 시험, 기준값 두 개 그대로, 배포본으로 옛 작업 루트 열기(이 PC의 `%LOCALAPPDATA%\HAZOP` 사본으로), 앱 S1~S6 | 코드는 revert. 사용자 데이터는 `migrate_names.py --undo <manifest>`(옛 폴더는 `_before-0.2.0`으로 남아 있음) |

**정리 순서의 이유.** 단계 0~4는 코드가 읽지 않거나 읽는 곳이 몇 군데뿐이다. 실패해도 문서 링크가 깨지는 정도라 되돌리기 쉽다. 단계 5는 저장소 안 데이터 계약을 바꾸고, 단계 6은 저장소 밖 사용자 데이터까지 건드린다. 위험이 큰 것을 뒤에 두면, 앞 단계에서 이전 도구와 링크 검사가 한 번씩 검증된 뒤에 쓰인다.

**각 단계의 작업 단위.** 단계마다 `/pstack:poteto-mode` 하위 세션 하나를 쓰고(CLAUDE.md 규칙 10), 검토 1회와 QA를 거쳐 커밋한다. 단계 5·6은 '대' 작업이라 Codex 교차검증을 함께 한다(규칙 7. 공개 자료라 사용자 확인 없이 쓸 수 있음).

---

## 8. 기계로 지키는 방법

### 8.1 `tests/test_naming_rules.py` 검사 항목

`test_path_literals.py`처럼 git이 추적하는 파일만 보고, 단계 0에서 지금의 위반을 모두 `EXEMPT` 표에 넣어 처음부터 통과하게 한다. 단계를 하나 마칠 때마다 그 단계의 예외 줄을 지운다. 예외 표가 비면 이전이 끝난 것이다.

| # | 검사 | 실패 예 |
| --- | --- | --- |
| N1 | 추적 경로의 모든 구성요소가 §4.1 글자 규칙(영어 소문자·숫자·`-`·`_`·`.`, 대문자 예외 목록)을 지킴 | `기획서/전체기획.md`, `P&ID 도면 샘플/` |
| N2 | 최상위 폴더가 §4.2 목록 안에 있음 | `notes/` |
| N3 | `docs/` 아래 폴더가 `^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*$`이고 `README.md`가 있음 | `docs/screenshots-pdf/` |
| N4 | 새 `scripts/*.py`의 접두가 §4.4 동사 목록에 있음(예외 7개 제외) | `scripts/helper.py` |
| N5 | `tests/` 아래 시험 파일이 `test_*.py` | `tests/check_x.py` |
| N6 | 머리 대상 문서(§4.6)에 `doc_id`·`rev`·`status`·`author`·`reviewed`·`approved`가 있고, `doc_id` 형식이 `^HZ-(PLN\|FLW\|DSN\|MTH\|REC\|GOV\|CHK)-\d{2}$`, 번호가 겹치지 않음, `status`가 네 값 중 하나, `approved`면 `approved:`가 `—`가 아님 | 번호 겹침, `status: done` |
| N7 | 손 버전 이름이 없음(`_v\d`, `_draft`, `_final`, `-new`, `복사본`) | `system-codes_v2.csv` |
| N8 | `.md`·`.html`·`.claude/` 안에 옛 한글 최상위 경로(`기획서/`, `디자인/`, `메모리/`, `지식/`, `자원/`, `작업/`, `flow chart/`)가 링크나 백틱 경로로 나오지 않음(결정로그·남은작업 본문 문장, 이 문서의 대응표는 예외) | `.claude/agents/hazop-planner.md`의 `기획서/` |
| N9 | `.md`의 상대 링크 대상이 실제로 있음 | `[인터페이스](기획서/인터페이스.md)` |
| N10 | 커밋 메시지: 단계 0 커밋(기준 커밋) 이후 `git log <기준>..HEAD`의 제목이 `^(feat\|fix\|docs\|test\|refactor\|perf\|build\|ci\|chore\|baseline)(\([a-z0-9-]+\))?!?: \S`이고 요약에 한글이 있음. 병합 커밋, `git revert` 기본 제목(`Revert "…`), GitHub 병합 제목(`Merge pull request #…`, `Merge branch …`), 스쿼시 병합 기본 제목(`… (#숫자)`로 끝남)은 제외 | `Add the core of …` |
| N11 | 브랜치: 현재 브랜치 이름이 `^(feat\|fix\|docs\|chore\|refactor\|test)/[a-z0-9]+(-[a-z0-9]+){0,3}$`이거나 `main` | `my-branch` |

N10·N11은 CI(결정로그 237행의 가벼운 CI)에서도 돌린다. 처음 몇 주는 CI 결정대로 실패해도 병합을 막지 않는다.

### 8.2 `scripts/preflight.py` 경고

실패가 아니라 경고로 둔다. 다른 세션의 폴더 때문에 내 시험이 깨지면 안 된다(교훈 8).

- `D:\HAZOP-trials`(또는 `HAZOP_TRIALS_ROOT`) 루트에 낱개 파일이 있음
- 시험 폴더 이름이 `YYYY-MM-DD-…`가 아님, README가 없음, README에 `keep_until`이 없음
- `keep_until`이 오늘보다 앞섬(지울 후보 목록. 지우기는 사람 확인 뒤)
- `main`에 병합된 로컬 브랜치, 디스크에 폴더가 없는 작업트리 기록
- 개발 작업 루트나 배포본 작업 루트에 옛 한글 폴더(`작업`, `출력`, `자료저장소`)가 남아 있음(단계 6 뒤)

### 8.3 작업지시서 머리말 (총괄이 하위 세션에 붙임)

```
- 이름·보관 위치는 docs/2026-11-10-naming-rules/README.md(HZ-GOV-02) §4를 따른다.
- 지금 이전 단계: <n>. 아직 옮기지 않은 옛 이름은 그대로 쓰고, 새로 만드는 것만 영어 이름으로 만든다.
- 새 문서에는 §4.7 머리를 단다. status는 review까지 올리고, approved는 총괄이 바꾼다.
- 커밋 제목: <종류>(<범위>): <한국어 요약>. 브랜치: <종류>/<slug>.
- 시험 폴더: D:\HAZOP-trials\<YYYY-MM-DD>-<단위>-<slug>\ + README(주인·목적·keep_until).
- 새 작업 단위 ID는 records/README.md(옮기기 전에는 메모리/README.md) 'ID 접두 표'에 먼저 올린다.
- scripts/ 파일 이름과 사용자 데이터 안의 경로·ID는 바꾸지 않는다.
```

### 8.4 CLAUDE.md에 넣을 규칙

```
18. **이름과 보관 위치.** 폴더·파일·문서번호·브랜치·커밋·시험 폴더 이름은
    docs/2026-11-10-naming-rules/README.md(HZ-GOV-02) §4를 따르고, tests/test_naming_rules.py가 지킨다.
    문서 상태를 approved로 바꾸는 일은 총괄 세션이 한다. 이름을 옮기는 단계(§7)는 그 문서의 순서대로만 하고,
    단계 3~6은 다른 세션이 하나도 돌지 않을 때만 한다(규칙 4).
```

규칙 14(시험 폴더 README)에는 "README에 `keep_until`(단위 종료 + 14일, 다시 만들기 비싼 결과는 `forever`)을 적는다"를 더한다.

---

## 9. 남은 질문

꼭 필요한 것만 남겼다. 각 질문의 첫 번째가 권장이다.

1. **이름 네 개 확인.** 대응표에서 뜻을 골라야 했던 이름입니다. 이대로 갈까요?
   - `기획서/` → `specs/` (다른 후보 `plans/`)
   - `지식/` → `methodology/` (다른 후보 `knowledge/`. 지식그래프와 겹침)
   - `메모리/` → `records/` (다른 후보 `memory/`)
   - `자원/기준/` → `resources/library/` (다른 후보 `resources/standards/`)
2. **스크립트 하위 폴더.** 개정 0의 엄격안에는 `scripts/check/apr1400.py`처럼 스크립트를 종류별 하위 폴더로 나누는 규칙이 있었습니다. 스크립트 이름은 이미 영어이고, 앱이 `scripts/<이름>.py`를 이름으로 불러오며, 문서 71개가 493번 가리킵니다. **나누지 않고 접두 규칙만 둘까요**, 아니면 나눌까요?
3. **샘플 도면의 기록용 경로.** 그래프 판 해시에 들어가는 `참고자료/P&ID 도면 샘플/…` 문자열을 **옛 그대로 고정할까요**(권장. 폴더만 영어로 바뀌고 해시·재연결 작업 없음)? 아니면 `references/pid-samples/…`로 바꾸고 샘플 6장의 그래프 판 재연결, 고정 응답 해시와 시험 입력을 다시 매길까요?
4. **배포본의 옛 작업 폴더.** 새 버전 앱이 처음 켜질 때 옛 한글 폴더(`자료저장소/`, `출력/`)를 찾으면, **물어보고 복사해 옮길까요**(옛 폴더는 `_before-0.2.0`으로 남김)? 아니면 묻지 않고 자동으로 옮길까요?

---

## 부록. 조사에 쓴 명령

모두 읽기 전용이다. 2026-11-10, `feat/next-units` HEAD `03dd7b4`, 단위 B의 커밋하지 않은 수정이 있는 상태에서 돌렸다.

```bash
git ls-files | wc -l
git -c core.quotepath=off ls-files | perl -CSDA -ne 'print if /\p{Hangul}/'
git -c core.quotepath=off ls-files | awk -F/ '{print $1}' | sort | uniq -c
ls D:/HAZOP/scripts/*.py | xargs -n1 basename | sed -E 's/_.*//; s/\.py$//' | sort | uniq -c
git log --format=%s | perl -CS -ne '$k++ if /\p{Hangul}/; $n++; END{print "ko=$k total=$n\n"}'
git branch -a; git branch --merged main; git tag; git worktree list
git grep -c -F '"출력' -- '*.py'
git grep -o -E 'folder(_in|_rel)?\(' -- '*.py' | wc -l
git grep -c -E '(기획서|디자인|메모리|지식|자원|작업|flow chart)/' -- '*.md' '*.html'
git grep -l -E '기획서/|디자인/|메모리/|자원/|작업/|flow chart' -- .claude
grep -c 자원 tests/baselines/*.json
grep -rl 기획서 자원 tests/fixtures
git log --diff-filter=A --follow --format=%ad --date=format:%Y-%m-%dT%H%M -- <문서>
ls "$LOCALAPPDATA/HAZOP"; ls D:/HAZOP-trials; ls D:/HAZOP-backup
```
