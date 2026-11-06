# 패키징 진행 관리 (SSOT)

> **역할**: 작업 단위별 상세 상태, 완료 기준, 결과, 증거와 다음 행동을 관리하는 유일한 원장.
> **투영 규칙**: [`ROADMAP.md`](ROADMAP.md)는 이 문서의 단계·순서·게이트·현재 행동을 한 장으로 요약한다.
> **갱신 규칙**: 확인 가능한 증거가 있는 변화만 기록하고, 갱신할 때마다 기준 일시와 변경 이력을 함께 바꾼다.
> **기준일**: 2026-11-06 13:25

## 1. 작업 단위 상태 장부

| ID | 상태 | 작업 단위 | 완료 기준 | 의존성 |
|---|---|---|---|---|
| `W1` | 완료 | 초기 조사와 실행 계획 구체화 | 참조 대상 또는 업무 범위를 조사하고 후속 작업 단위와 완료 기준을 등록한다. | 없음 |
| `W2` | 완료 | 전용 venv(python.org CPython 3.12, PySide6 6.12.0·networkx 3.7·openpyxl 3.1.5 고정) | venv에서 전체 테스트 통과 | 사용자 설치 승인 |
| `W3` | 완료 | 경로·importlib 로딩 정리, `tests/test_packaging.py` | 소스·빌드 경로 양쪽에서 자원 로딩 테스트 통과. 빌드 경로 = 모의 frozen(`sys.frozen`·`_MEIPASS` 패치)으로 확인하는 경로 선택 검증이며, 실빌드·저장소 없는 환경의 ①~⑤는 `W4` 완료 기준 | `W2` |
| `W4` | 완료(D8, 알려진 한계 기록) | 첫 PyInstaller one-folder 빌드 | ASCII·한글 경로에서 화면 ①~⑤ 스크린샷, ③ V1·V2·S1 통과 | `W3` |
| `W5` | 완료(D12) | 신뢰 경계 해시 고정 확대 | 패턴 라이브러리·지침서 변조 시 차단 테스트 | `W3`, D12 |
| `W6` | 고지 초안 완료, 사용자 확인·추가 원문 대기 | `licenses/` 제3자 고지(force-graph 번들·ColorBrewer Apache-2.0·Qt LGPL) | 고지 파일과 원문 대조 | 라이선스 원문 다운로드 승인(D2), 편집 범위 확장(D9), 추가 원문 다운로드는 사용자 승인 필요 |
| `W7` | 대기(의존성) | `os.link` 비NTFS 실측과 대응(`store.py` 범위 확대 결정 필요) | FAT32/exFAT 시험 결과와 대응 테스트 | `W2` |
| `W8` | 분할(`W8-A` 완료(D11), `W8-B` 완료(D13·D14)) | 빌드 수집 범위 정리: `W8-A` PATH 경유 DLL 수집 차단, `W8-B` 앱이 쓰지 않는 Qt 모듈 제외 | 묶음에 제외 대상 모듈(`W8-B`)·PATH 출처 DLL(`W8-A`)이 없고 화면 ①~⑤ 검증 통과 | `W8-A`·`W8-B` |
| `W8-A` | 완료(D11) | PATH 경유 DLL(JDK UCRT·Git OpenSSL) 수집 차단: 빌드 PATH 통제, Qt TLS 플러그인 허용 목록, 빌드 뒤 바이너리 검사(D10) | 묶음에 venv·기반 CPython 밖 출처 바이너리와 이름 거부 목록·허용 목록 밖 TLS 플러그인이 없고(빌드가 검사), ASCII·한글 경로에서 검증용·배포용 verify 통과 | `W4`, D10 |
| `W8-B` | 완료(D13·D14) | 앱이 쓰지 않는 Qt 모듈(GPL 전용 Charts·DataVisualization·Graphs·Quick3D·VirtualKeyboard·QuickTimeline·ShaderTools 등) 제외 | 묶음에 제외 대상 모듈이 없고(빌드가 검사) 화면 ①~⑤ 검증 통과 | 사용자 선택(W6 evidence §9-2 (가), D13) |
| `W9` | 완료(D15·D16) | 라이선스 고지 원문 동봉(VC++ 재배포·liblzma·Qt 내부 제3자·PDFium·WebEngine 목록·Mesa·LLVM, Qt판 LGPL·GPL), pdfplumber와 의존성 묶음 포함, 고지를 실행 파일 옆 `licenses/`로 | 받은 원문마다 출처·날짜·SHA-256·크기 기록, 고지 목록 대조 테스트 통과, 빌드가 실행 파일 옆 고지·PDF 모듈을 검사하고 묶인 실행에서 PDF 어댑터 동작, 재빌드 2종·ASCII·한글 verify 4회 통과 | 사용자 결정(2026-11-06, D15), `W6`·`W8-B` |
| `W9-B` | 완료(D17·D19) | 남은 고지 원문: VS 2022 사용 조건 .docx(텍스트 사본 포함), cryptography 안 OpenSSL 4.0.0·Rust 크레이트 원문 | 받은 원문마다 URL·SHA-256·크기 기록, 고지 목록 대조 테스트 통과, 재빌드 고지 검사·verify 통과 | 총괄 결정(권고안, 사용자 위임 2026-11-06), `W9` |
| `W10` | 완료(D18·D19) | 앱 정보 창(고지 위치·열기·법무 검토 전 안내), 설정 파일 손상 시 한국어 대화상자(백업 후 기본값/종료)·비대화형 rc 2, verify 미처리 예외 시험을 창 없는 방식으로 | 테스트(손상 설정·정보 창 경로·verify 변경) 통과, 재빌드 2종·ASCII·한글 verify 4회 통과, verify 중 모달·오류 창 없음(`--screenshots` 스크린샷 단계는 비모달 창이 잠깐 뜸) | 총괄 결정(권고안, 사용자 위임 2026-11-06), `W9-B` |
| `W11` | 구현 완료(검토 대기, D20) | 배포본 최종 빌드(새 기능 없음, 기준 `ad9175b`) | 스냅숏 재빌드 2종 rc=0, ASCII·한글 verify 4회 통과, 배포용 묶음 zip 크기·SHA-256 기록(저장소 밖) | `W10`, 사용자 목표(2026-11-06 빠른 패키징) |

작업 추가·분할은 [`README.md`](README.md)의 확장 규칙을 따른다. 기존 ID·완료 이력·증거는 보존하고 새 작업에는 관련 결정 ID를 연결한다.

## 2. 진행 중 작업 상세

| ID | 현재 상태 | 증거 | 다음 행동 |
|---|---|---|---|
| `W3` | 완료. Claude 승인·Codex 조건부 승인(재작업 1회, 잔여 테스트 격리·역슬래시 문자열은 총괄 직접 수정). 판정 범위는 경로 선택 검증(실빌드는 W4) | [w3-경로.md](evidence/w3-경로.md) | — |
| `W4` | 완료. 재작업 2회 뒤 Claude 승인·Codex 반려 → 사용자 위임(권장안)으로 총괄 직접 수정 후 완료(D8). 남은 한계는 evidence §6 | [w4-빌드.md](evidence/w4-빌드.md) | 재검토(Claude·Codex) → D7 승인 → 완료 처리. 재작업 한도(2회) 도달 |
| `W8-A` | 완료. 재작업 2회 뒤 Claude 승인·Codex 조건부 승인 → tls_probe 3건 총괄 직접 수정(D11) | [w8-경로통제.md](evidence/w8-경로통제.md) | 재검토 → 완료 판정 |
| `W8-B` | 완료(D14): 최종 재검토 Codex 승인·Claude 조건부 승인(문서 4건 총괄 직접 수정). 재검토 Codex 반려·Claude 조건부 승인 반영: 이름 규칙(설치본 전체 이름 70개, 위치 무관)·폴더 규칙(PySide6 기준 경로만)으로 판정해 절대 경로 상위 이름·접두사 과매칭 제거, 이동한 플러그인 DLL 검출, `QtSpatialAudio.pyd`, spec 연결 모의 실행 테스트, 링크 폴더·is_dir 오류 폴더 실패 처리. 오탐 0(설치본 3,893개·W8-A 묶음). 배포용 2,234개·527.4 MiB(−885개·−36.9 MiB), 빌드 rc=0 실측, 두 경로 verify 4회 통과, venv 681 OK(건너뜀 14) | [w8b-모듈제외.md](evidence/w8b-모듈제외.md) | 재검토(Claude·Codex) → QA |
| `W5` | 완료. 재작업 1회 뒤 Claude 승인(문서 2건 총괄 정정)·Codex 승인. 기준 자료 5종 해시 고정, 기획서(전체기획 신뢰 경계·인터페이스 §7.2·§9) 반영 | [w5-신뢰경계.md](evidence/w5-신뢰경계.md) | 재검토(Claude·Codex) → QA |
| `W9` | 완료(D16): 재검토 Claude·Codex 조건부 승인, 문서 4건 총괄 직접 수정. 1회차 내용: Claude·Codex 조건부 승인 반영 — verify PDF 필수 키 검사, 고지 대조 탐색 오류 실패, qtbase LicenseFile·CopyrightFile 원문 25개 추가(libjpeg-turbo `COPYRIGHT.txt` 포함), cryptography SBOM 2개 동봉, README 표 연속성 검사, finish_bundle rc=3 테스트. 재빌드 2종 rc=0, 배포용 2,529개·567.3 MiB, verify 4회 통과, test_packaging 63 OK, venv 689 OK(건너뜀 5). 1차: 원문 52개 받음·1개 받지 못함(VS 2022 사용 조건 본문은 .docx), `licenses/` 원문 79개 추가·2개 교체, pdfplumber 등 8개를 해시 고정 설치(`pip freeze` +8, 그 밖 변화 없음). 스냅숏 `cd3194d` 재빌드 2종 rc=0(D10·D13 검사 통과), 배포용 2,502개·567.1 MiB(+268개·+39.7 MiB), verify 4회 통과(검증용 pdf_probe 통과). test_packaging 60 OK, venv 686 OK(건너뜀 5) | [w9-고지원문.md](evidence/w9-고지원문.md) | 재검토(Claude·Codex) → 사용자 확인: ① VS 2022 사용 조건 본문(.docx) 받기 여부 ② cryptography 안 OpenSSL·Rust 크레이트 원문 내려받기 승인 여부(지금은 휠 동봉 SBOM만, [evidence §10.2](evidence/w9-고지원문.md)). 앱 정보 창 안내는 `W10` |
| `W9-B` | 재작업 1회차 반영(재검토 대기, D17): OpenSSL·크레이트 행 수정 열을 "휠 파일 미수정(RECORD 대조), 소스 수정 여부 미확인"으로. 1차: 원문 63개 추가(.docx 1·텍스트 사본 1·OpenSSL 1·crates.io 크레이트 32개의 원문 60), 받지 못함 0. `.crate` 32개 SHA-256 = SBOM. 크레이트는 SBOM으로 런타임·빌드를 다 구분하지 못해 32개 전부. test_packaging 65 OK | [w9-고지원문.md](evidence/w9-고지원문.md) §11 | 검토(Claude·Codex) → QA |
| `W10` | 완료(D19, 재검토 Claude 승인·Codex 조건부 승인 → 권한 오류 경로 총괄 직접 수정). 재작업 1회차: 시험 트리거를 검증용 빌드 표지 훅으로 한정(배포용 verify는 트리거 꺼짐 rc 2 확인), 대화상자 뒤 파일 재확인, 설정 읽기 OSError 안내, WARNING 기록, BOM 허용, 정보 창 "닫기"·열기 실패 안내, verify 단계 4 대역 실행 테스트. HEAD `c155845` 스냅숏 재빌드 2종 rc=0, verify 4회 통과, 스냅숏 전체 708 OK(건너뜀 8), test_packaging 66·test_app_startup 15 OK([evidence §7](evidence/w10-정보창.md)). 1차: `paths.licenses_dir()`, 정보 창 보강(메뉴 이름은 기획서대로 "버전·데이터 위치"), `hazop/app/startup.py`, `run_app` 시작 전 확인·시험 트리거, verify 단계 4 교체. 스냅숏 `3231a54` 재빌드 2종 rc=0, 배포용 2,592개·595,326,751 bytes, verify 4회 통과(손상 설정 0.2초 rc 2, 시험 트리거 0.1초 rc 70), venv 703 OK(건너뜀 5). 기획서 문안은 evidence §5 | [w10-정보창.md](evidence/w10-정보창.md) | 검토(Claude·Codex) → 기획서 문안 반영(planner) → QA |
| `W11` | 구현 완료(검토 대기, D20). 스냅숏 `ad9175b`(603개, overlay 0) 재빌드 2종 rc=0(검증용 89초·배포용 64초), 배포용 2,592개·595,431,756 bytes, verify 4회 통과, zip `HAZOP-0.1.0-20261106.zip` 230,288,644 bytes·SHA-256 `8be9acf9…cdcd`, 푼 zip verify 통과, 스냅숏 841 OK(건너뜀 9). 새 스크립트 3개는 묶지 않음(현행 유지) | [w11-최종빌드.md](evidence/w11-최종빌드.md) | 검토 → QA |
| `W6` | 고지 초안 완료, 사용자 확인·추가 원문 대기. 재작업 1회차(Codex 반려·Claude 조건부 승인 반영): `licenses/` 원문 42개·안내문 2개·고지 목록(수정 여부·SHA-256), 기준 목록 대조 테스트, 묶음 대비 누락 목록·수집 목록 첨부, verify_bundle licenses 검사(재빌드로 확인). venv 전체 605 OK(건너뜀 14) | [w6-라이선스.md](evidence/w6-라이선스.md), [첨부](evidence/w6-묶음수집목록.md) | 재검토 → 사용자 확인 항목(evidence §9) 판단: Chromium 등 추가 원문 다운로드 승인, GPL 전용 모듈 (가)/(나), LGPL 요건·소스 제공 방식 |

## 3. 완료 결과

| ID | 결과 | 증거 | 비고 |
|---|---|---|---|

## 4. 보류·재개

현재 보류한 작업은 없다. 보류 시 작업 ID, 사유, 재개 조건을 기록한다.

## 5. 열린 결정

D7(묶인 실행 로그를 런타임 훅으로 `<작업 루트>/logs/app.log`에 남김)은 확정(총괄 승인, 권고안, 2026-11-06 00:25)이다([decisions.md](decisions.md)). 후속 결정 후보: HAZOP.exe 자체에서 importlib 스크립트 로딩을 확인하려면 `run_app.py`/`screenshots.py` 편집이 필요함(D6 한계). 새 결정은 [`decisions.md`](decisions.md)에 먼저 등록하고 관련 작업 ID와 함께 연결한다.

## 6. 변경 이력

| 일시 | 변경 |
|---|---|
| 2026-11-05 17:15 | `W1`을 진행 중으로 등록하고 작업 진행 관리 원장을 생성 |
| 2026-11-05 17:30 | `W1` 완료: [W1 조사](evidence/w1-조사.md). 권고안 D1 채택, 설치·다운로드는 승인 대기. W2~W7 등록 |
| 2026-11-05 18:30 | `W2` 완료: CPython 3.12.10 + 전용 venv, venv 전체 테스트 478 OK(건너뜀 5), check_app·check_kg_screen 통과. D3 기록 |
| 2026-11-05 19:00 | D4: venv를 `%USERPROFILE%\.hazop\venv-py312`로 재생성(489 OK·건너뜀 5), 3.12.10 유지 |
| 2026-11-05 21:36 | `W3` 구현 완료(검토 대기): [W3 경로](evidence/w3-경로.md). venv 562 OK(건너뜀 14), HEAD+W3 사본 PATH python 562 OK. 1차 실행 PATH python 실패 2건은 T6 진행 중 변경 기인, 재실행 양쪽 566 OK·check_app rc=0 |
| 2026-11-05 21:56 | `W3` 재작업 1회차(Claude M1·L1~L4, Codex 6~10 반영): ④ 음성 단계·회귀 검출 확인, 이름 허용 목록·경로 키 캐시, frozen 조합 테스트, 판정 범위를 경로 선택 검증으로 한정. venv 571 OK(건너뜀 14), PATH python 571 OK, check_app rc=0 |
| 2026-11-05 22:10 | `W3` 완료: 재작업 1회 뒤 Claude 승인, Codex 조건부 승인. 총괄 직접 수정 — FrozenMock이 sys.frozen을 항상 패치하고 bundle=None이면 _MEIPASS를 임시 제거·복원, 테스트 머리말에 판정 범위(경로 선택만, 실빌드 W4) 명시, 역슬래시 이름 거부 사례를 raw 문자열로. 인터페이스 §7.1 program_root 문구는 W4에서 함께 반영 |
| 2026-11-05 22:45 | `W4` 구현 완료(검토 대기): [W4 빌드](evidence/w4-빌드.md). PyInstaller 6.22.3 빌드 rc=0(76초, 네트워크 연결 0건), 묶음 578.8 MiB. `%TEMP%\hz_ascii`·`%TEMP%\한글테스트` 모두 통과. venv 전체 테스트 작업 트리 583 OK·스냅숏 575 OK(건너뜀 14). 인터페이스 §7.1 program_root 문구 반영. D5(안) 등록 |
| 2026-11-05 23:15 | `W4` 재작업 1회차(Codex 반려 1~10, Claude M2·M3·L1·L4·L5, 총괄 M1·L2 반영): 검증용(`dist/HAZOP-verify`)·배포용(`dist/HAZOP`, `check_dist` 통과) 두 빌드, 두 경로 verify 통과, venv 작업 트리 592 OK·스냅숏 584 OK(건너뜀 14). D5 확정, D6 등록(확정), D7 등록(안) |
| 2026-11-06 00:10 | `W4` 재작업 2회차(Codex 1~7, Claude N1~N3 반영): 스냅숏 `f3b309e` 재생성·검증용/배포용 재빌드(묶음 포함 파일 rthook·check_entry 변경), 두 경로 4회 verify 통과, 런타임 네트워크 원격 0(242표본, QtWebEngineProcess 포함). venv 작업 트리 599 OK·스냅숏 591 OK(건너뜀 14). D7 미정 항목 보강 |
| 2026-11-06 00:25 | `W4` 완료(D8): 최종 재검토 Claude 승인·Codex 반려(make_snapshot 경로 2건·테스트 공백). 총괄이 make_snapshot 경로 2건을 직접 고치고 test_packaging 30건 OK. 테스트 공백과 R1·R2는 알려진 한계로 기록. D7 확정(권고안) |
| 2026-11-06 00:50 | `W6` 구현 완료(검토 대기): [W6 라이선스](evidence/w6-라이선스.md). D9 등록(확정, `licenses/` 신규·datas 추가). force-graph 의존성 LICENSE 31건 다운로드(D2 범위, 재작업 1회차에 건수 정정), Qt LGPL·GPL 원문은 로컬 사본. venv 전체 603 OK(건너뜀 14) |
| 2026-11-06 01:50 | `W6` 재작업 1회차: 상태를 "고지 초안 완료, 사용자 확인·추가 원문 대기"로 변경. 기준 목록 대조 테스트, Qt 휠별 구성, 묶음 대비 누락 목록(PATH 경유 DLL 45개 발견), hooks-contrib 미포함, verify_bundle licenses 검사·재빌드 확인, qt.io 조회가 D2 범위 밖이었음을 기록. `W8` 후보 등록(사용자 결정 대기). venv 전체 605 OK(건너뜀 14) |
| 2026-11-06 01:30 | `W6` 재검토: Claude 승인·Codex 조건부 승인. 총괄 직접 반영 — force-graph 간접 의존성 수정 열을 '미확인(upstream 미대조)'으로, 안내 절 번호 정정(§8·§9, QT-SOURCE §9-2와 README 해시 갱신), evidence §9-8 Visual C++ 런타임 고지 결정 항목 추가. test_packaging 35 OK. 상태: 고지 초안 완료, 사용자 확인(§9)·추가 원문 대기 |
| 2026-11-06 01:40 | `W8` 분할: `W8-A`(PATH 경유 DLL 수집 차단) 구현 완료(검토 대기), `W8-B`(GPL 전용 Qt 모듈 제외) 후보 유지. D10 등록(확정, 총괄 판정 — 사용자 위임 권장안). [W8 경로 통제](evidence/w8-경로통제.md): PATH 경유 DLL 45→0, W6 §8 UCRT·OpenSSL `-x64` 행 '해당 없음'. venv 611 OK(건너뜀 14) |
| 2026-11-06 02:05 | `W8-A` 재작업 1회차(Claude 1·2·5~8, Codex 1~6 반영): Qt OpenSSL TLS 플러그인 제외, 허용 루트 축소·이름 거부 목록, TOC 형식·이름 바꾼 DATA·상대 경로·SYMLINK 검사, 전용 venv 확인, verify 자식 환경 정리. 재빌드 2종·verify 4회 통과, 사용자 PATH 전체에서 `libssl-3-x64` 미로드. D10 개정. venv 617 OK(건너뜀 14) |
| 2026-11-06 02:25 | `W8-A` 재작업 2회차(Codex 1~5, Claude 6·7 반영, 재작업 한도 도달): TLS 플러그인 허용 목록과 출처 긴 파일명 검사(이름 바꾸기·8.3 단축명·junction 별칭 시험), 인터프리터 경로 realpath 비교, 검증기 문구, TLS 측정 스크립트 `packaging/tls_probe.py`와 원본 출력 보존, 완료 기준 문구 정정. 기준 HEAD `dbcc855`(T6 W4 커밋 반영). 재빌드 2종·verify 4회 통과. venv 629 OK(건너뜀 14) |
| 2026-11-06 02:40 | `W8-A` 완료(D11): 최종 재검토 Claude 승인·Codex 조건부 승인(tls_probe 3건). 총괄 직접 수정·재측정(모듈 72·오류 0·schannel·libssl-3-x64 미로드), test_packaging 48 OK |
| 2026-11-06 03:30 | `W5` 구현 완료(검토 대기): [W5 신뢰 경계](evidence/w5-신뢰경계.md). D12 등록(확정). `integrity.py`에 패턴 라이브러리·지침서 고정값, `run.prepare`에 패턴 검사 연결, `tests/test_integrity_pins.py` 7건. venv 655 OK(건너뜀 14). 로컬 실행 폴더 resume 영향 없음. 기획서 문안 반영 대기 |
| 2026-11-06 03:45 | `W5` 기획서 문안 반영(D12, 검토 대기): `기획서/전체기획.md` 신뢰 경계 표 2행·남은 위험 1줄, `기획서/인터페이스.md` §7.2 신뢰 경계 행·§9 머리 문장(미결 행 삭제) |
| 2026-11-06 04:10 | `W5` 재작업 1회차(Claude·Codex 조건부 승인 반영): 지침서 검사를 공통 함수로 묶어 `check_catalog`·`check_criteria` 양쪽에 적용, 해시 불일치 시 파싱 생략, 읽기·파싱 실패를 경로·원인 blocker로, 회귀 테스트 7건 추가(14건), 지침서 수정 시 `GUIDE_SHA256` 동시 갱신 주의(D12·evidence)와 resume 영향 문구 정정, 이력 시간순 정렬(02:40 행). venv 662 OK(건너뜀 14) |
| 2026-11-06 04:25 | `W5` 완료: 재검토 Claude 승인(조건부, 문서 2건 총괄 정정)·Codex 승인. test_integrity_pins 14 OK, 인터페이스 §7.2 제외 범위·evidence 문구 정정 |
| 2026-11-06 09:10 | `W8-B` 구현 완료(검토 대기): [W8-B 모듈 제외](evidence/w8b-모듈제외.md). D13 등록(사용자 결정). `build_package.py` 제외 규칙·spec 필터·빌드 뒤 검사, test_packaging D13 3건(51 OK). 스냅숏 `5225cc5` 재빌드 2종(바이너리 검사 통과), 배포용 3,119→2,235개·564.3→528.1 MiB, ASCII·한글 경로 verify 4회 통과. venv 674 OK(건너뜀 14) |
| 2026-11-06 09:45 | `W8-B` 재작업 1회차(Codex 반려·Claude 조건부 승인, 총괄 판정 반영): 결과 폴더 검사를 묶음 전체 이름·상대 경로 꼬리 판정으로(현재·이전 묶음 오탐 0), `os.walk` 탐색 오류·결과 폴더 없음은 검사 실패, main rc=3 테스트를 결과 폴더 위반 없이 분리, 고아 DLL(Qt6SpatialAudio 제외, Qt6OpenGLWidgets·opengl32sw 남김 사유) 기록, D13을 사용자 결정·총괄 판정으로 분리. 스냅숏 `5225cc5` 재빌드 2종 rc=0(실측), 배포용 2,234개·527.4 MiB, verify 4회 통과. test_packaging 52 OK, venv 676 OK(건너뜀 14) |
| 2026-11-06 10:30 | `W8-B` 완료(D14): Codex 승인, Claude 조건부 승인 → PROGRESS §5 D7 상태, evidence 66행 표현·§7 한계 3건(isjunction 3.12 이상, assimp.dll 이름, tls_rejected 같은 유형), build_package 머리 주석을 총괄이 직접 수정 |
| 2026-11-06 10:10 | `W8-B` 재작업 2회차(마지막, Codex 반려·Claude 조건부 승인 반영): 판정을 이름 규칙(설치본에서 뽑은 전체 이름)·폴더 규칙(PySide6 기준 상대 경로)으로 바꿔 절대 경로 상위 이름·접두사 과매칭 제거, 이동한 플러그인 DLL 검출, `QtSpatialAudio.pyd` 추가, spec 모의 실행 테스트(필터 연결 4줄 삭제 시 모두 검출), 링크 폴더·`is_dir()` 오류 폴더 검사 실패, w6 §9-2 결정 구분, ROADMAP D7 상태 정정. 오탐 확인(설치본 전체 896/3,893 의도 범위, W8-A 885, 재빌드 0). 스냅숏 `5225cc5` 재빌드 2종 rc=0, 배포용 2,234개·527.4 MiB, verify 4회 통과. test_packaging 55 OK, venv 681 OK(건너뜀 14) |
| 2026-11-06 10:45 | `W9` 구현 완료(검토 대기): [W9 고지 원문](evidence/w9-고지원문.md). D15 등록(사용자 결정). 원문 52개 내려받기(1개 받지 못함), pdfplumber 등 8개 해시 고정 설치, 고지를 실행 파일 옆 `licenses/`로, 빌드 뒤 고지·PDF 검사와 verify pdf_probe 추가. 재빌드 2종 rc=0, 배포용 2,502개·567.1 MiB, verify 4회 통과, test_packaging 60 OK, venv 686 OK(건너뜀 5) |
| 2026-11-06 11:30 | `W9` 완료(D16): 재검토 Claude 조건부 승인(문서 4건: PSL 버전 전체 값·근거 문서 지시·w6 PDF 행 상태·w9 절 번호)을 총괄이 직접 수정. Codex 남은 2건(OpenSSL·Rust 크레이트 원문, VS 2022 사용 조건)은 사용자 위임(2026-11-06 목표)에 따라 권고안(받아서 동봉)으로 `W9-B`에서 처리 |
| 2026-11-06 11:10 | `W9` 재작업 1회차(Claude·Codex 조건부 승인 반영): verify PDF 필수 키 검사, `_tree_hashes` 탐색 오류 실패, qtbase 원문 25개·cryptography SBOM 2개 추가, README 표 빈 줄 제거·연속성 검사, finish_bundle rc=3 테스트, 문구 정정. 재빌드 2종 rc=0, 배포용 2,529개·567.3 MiB, verify 4회 통과, test_packaging 63 OK, venv 689 OK(건너뜀 5). 사용자 확인 항목에 OpenSSL·Rust 크레이트 원문 승인 여부 추가 |
| 2026-11-06 11:45 | `W9-B`·`W10` 구현 완료(검토 대기): [W9 고지 원문 §11](evidence/w9-고지원문.md), [W10 정보 창](evidence/w10-정보창.md). D17·D18 등록(총괄 결정, 권고안). 원문 63개 추가, 정보 창 고지 안내, 설정 손상 대화상자·비대화형 rc 2, verify 미처리 예외 시험을 창 없는 방식으로. 재빌드 2종 rc=0, 배포용 2,592개·595,326,751 bytes, verify 4회 통과, test_packaging 65 OK·test_app_startup 11 OK, venv 703 OK(건너뜀 5) |
| 2026-11-06 12:05 | `W9-B`·`W10` 재작업 1회차(Claude·Codex 조건부 승인, 총괄 판정 반영): 시험 트리거를 검증용 빌드 표지 훅(`packaging/rthook_verify_build.py`)으로 한정하고 배포용 verify에서 꺼짐 확인, 설정 파일 재확인·OSError 안내·WARNING·BOM 허용, 정보 창 "닫기"·열기 실패 안내, OpenSSL·크레이트 수정 열 정정, verify 단계 4 대역 실행 테스트. D18 개정. HEAD `c155845` 스냅숏 재빌드 2종 rc=0, verify 4회 통과, 스냅숏 전체 708 OK(건너뜀 8). 작업 트리 전체는 722건 중 오류 1(`tests.test_export`, 다른 담당 진행 중 변경) |
| 2026-11-06 13:25 | `W11` 구현 완료(검토 대기): [W11 최종 빌드](evidence/w11-최종빌드.md). D20 등록. HEAD `ad9175b` 스냅숏 재빌드 2종 rc=0, verify 4회 통과, 배포용 zip 230,288,644 bytes·SHA-256 `8be9acf9ccec22235c3a651e02d5388364fb81c5d449929674347e967ebbcdcd`(`%TEMP%\hazop-w11`, 저장소 밖), 스냅숏 841 OK(건너뜀 9). `check_contract`·`compare_criteria`·`clean_outputs`는 묶지 않음(현행 유지) |
