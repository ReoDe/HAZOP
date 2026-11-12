# W10 — 앱 정보 창의 고지 안내, 설정 파일 손상 안내 (T2)

> 1차 2026-11-06 11:15~11:45(기준 HEAD `3231a54`), **재작업 1회차 11:45~12:05(§7, 기준 HEAD `c155845`)**. 실행 주체: hazop-developer.
> §1~§6은 1차 기록이다. 시험 트리거·설정 확인·정보 창 버튼·verify 수치는 §7이 현재 값이다.
> 근거 결정: D18(총괄 결정(권고안, 사용자 위임 2026-11-06)). W9-B 원문은 [w9-notice-text.md](w9-notice-text.md) §11(D17).
> 비교 기준: W9 재작업 1회차 묶음([w9-notice-text.md](w9-notice-text.md) §10.4).

## 1. 동작

### 1.1 도움말 > 버전·데이터 위치(정보 창 보강)

- 기존 메뉴 항목 "버전·데이터 위치"를 보강했다. 이름은 `specs/interface.md` §2.1 메뉴 행("도움말(버전·데이터 위치)")과 맞추려고 바꾸지 않았다(§5 문안 참고).
- 내용: 프로그램 이름·버전(`HAZOP 분석 도구 0.1.0`), 자원·작업·저장 루트, 설정 파일, AI·네트워크 안내(기존) + **제3자 라이선스 고지 위치** + 안내 한 줄 "LGPL 등 제3자 라이선스 의무의 법무 검토 전이므로 내부용으로만 사용하십시오."
- 고지 위치: `paths.licenses_dir()`(추가 API). 묶인 실행이면 실행 파일 옆 `licenses/`(`dirname(sys.executable)`, D15의 복사 위치), 개발 실행이면 저장소 `licenses/`.
- 버튼 "라이선스 고지 열기": `QDesktopServices.openUrl(QUrl.fromLocalFile(<폴더>))`로 탐색기에서 연다. 폴더가 없으면 경고 대화상자만 띄운다. 닫기 버튼은 "Close"(Qt 표준 버튼).
- 색은 쓰지 않았다(`hazop/app/tokens.py`는 건드리지 않음).

### 1.2 설정 파일 손상

- `hazop/app/startup.py`(신규) `check_settings`를 `scripts/run_app.main`이 **MainWindow를 만들기 전**에 부른다. 판정은 `paths.load_settings`를 그대로 쓴다: `ValueError`(JSON 객체 아님)와 그 하위 클래스인 `json.JSONDecodeError`(문법 오류)·`UnicodeDecodeError`(UTF-8 아님)를 같은 손상으로 본다. 파일이 없으면 기본값(기존 동작). 기본값으로 조용히 덮어쓰는 동작은 없다.
- 대화형(기본 실행): `QApplication`을 만든 뒤 한국어 대화상자(제목 "설정 파일을 읽을 수 없음", 파일 경로·원인 표시). 선택지 "기존 파일을 백업하고 기본값으로 시작"(`settings.json` → `settings.json.bad-<YYYYMMDD-HHMMSS>.json` 이름 바꾸기 후 계속, 처음 실행처럼 검토자 이름을 묻는다) / "종료"(기본 버튼, 종료 코드 2). 이름 바꾸기가 실패하면(같은 이름이 이미 있음·권한 등) 덮어쓰지 않고 오류 대화상자 뒤 종료 코드 2.
- 비대화형(`--screenshots`): `QApplication`을 만들기 전에 확인하고, 대화상자 없이 stderr에 "설정 파일을 읽을 수 없어 종료합니다: <경로> / 원인: …"을 쓰고 종료 코드 2. 파일은 그대로 둔다.
- 기록: 로거 `hazop.settings`에 INFO로 남긴다(묶인 실행은 런타임 훅이 `<작업 루트>/logs/app.log`에 씀, D7).
- `OSError`(읽기 권한 등)는 이번 범위가 아니다. 지금처럼 처리되지 않은 예외로 끝난다.

### 1.3 verify의 미처리 예외 시험 교체

| 이전(W4~W9) | 지금(W10) |
|---|---|
| `HAZOP.exe --settings bad-settings.json`(`[]`) → MainWindow가 ValueError → PyInstaller 영문 오류 대화상자가 사용자 화면에 뜨고 60초 뒤 강제 종료. 로그에 "미처리 예외"·"설정 파일이 JSON 객체가 아님" | ① 손상 설정(배포용·검증용 모두): JSON 문법 오류 파일(`{ not json`) + `--screenshots` → 종료 코드 2, 출력에 안내·`JSONDecodeError`, `app.log`에 "설정 파일을 읽을 수 없음", 설정 폴더에 원래 파일 하나만(백업·덮어쓰기 없음), PNG 없음. ② 미처리 예외 기록(검증용만): 환경변수 `HAZOP_TEST_EXCEPTHOOK=1` → `run_app.main`이 시험용 `RuntimeError`를 잡아 `sys.excepthook`에 직접 넘기고 종료 코드 70. `app.log`에 "미처리 예외"와 "시험용 미처리 예외(HAZOP_TEST_EXCEPTHOOK)" |

- 대화상자가 뜨지 않는 근거: PyInstaller 6.22.3 Python 쪽에는 `excepthook`이 없다(설치본 `PyInstaller/` 아래 `*.py`에 `excepthook` 문자열 0건). 창 프로그램의 오류 대화상자는 스크립트가 예외로 끝났을 때 부트로더(C)가 띄운다. ②는 예외를 잡아 넘기고 정상 반환하므로 부트로더 경로를 타지 않는다. 실측: ① 0.2초, ② 0.1초에 끝났다(창이 떴다면 60초 시간 제한에 걸림).
- 트리거는 배포용에서도 끌 수 없다(빌드 구분 없이 같은 `run_app.py`). 창을 띄우지 않고 로그 한 줄과 종료 코드 70만 남긴다. 작업지시서에 따라 ② 시험은 검증용 빌드(`--app-only`가 아닐 때)에서만 한다.
- 한계: ②는 런타임 훅의 `excepthook`이 설치되어 기록하는지를 본다. 실제 처리되지 않은 예외가 부트로더를 거쳐 `sys.excepthook`을 부르는 경로는 W4~W9 verify에서 확인했던 것이며 이번에는 다시 실행하지 않았다(그 시험이 사용자 화면에 창을 띄우기 때문).

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `hazop/paths.py` | `licenses_dir()` 추가(기존 API 변경 없음) |
| `hazop/app/startup.py`(신규) | `settings_error`·`backup_name`·`check_settings`·`ask_dialog`·`notify_dialog` |
| `hazop/app/main_window.py` | `LICENSE_NOTE`, `about_text()`, `_about()`(QMessageBox + "라이선스 고지 열기"), `open_licenses()` |
| `scripts/run_app.py` | MainWindow 전 `check_settings`(비대화형은 QApplication 전), `HAZOP_TEST_EXCEPTHOOK` 시험 트리거(종료 코드 70), 머리말 |
| `packaging/verify_bundle.py` | 단계 4의 손상 설정·미처리 예외 시험 교체(§1.3), `bad_settings_ok`·`excepthook_ok`, 판정식(`app_bad_settings`, 검증용만 `app_log_unhandled`), 머리말 |
| `tests/test_app_startup.py`(신규) | §3 |
| `tests/test_packaging.py` | `VerifierTest.test_app_checks_without_window`(+W9-B 고지 테스트) |

## 3. 테스트

| 테스트 | 확인하는 것 |
|---|---|
| `SettingsCheckTest`(6건) | 손상 3종(문법 오류·배열·UTF-8 아님) 원인 문자열, 정상·없는 파일은 묻지 않음, 비대화형 rc 2·대화상자 미호출·파일 그대로·stderr 없는 경우, "종료" rc 2·파일 그대로, "백업" 이름 규칙(`settings.json.bad-YYYYMMDD-HHMMSS.json`)·내용 보존·뒤이어 기본값, 백업 이름이 이미 있으면 덮어쓰지 않고 rc 2 |
| `RunAppStartupTest`(3건) | `run_app.main --screenshots` + 손상 설정 → rc 2, `make_application`·대화상자 미호출, PNG 폴더 없음. 대화형 "종료" → rc 2, MainWindow 미생성. `HAZOP_TEST_EXCEPTHOOK=1` → rc 70, `sys.excepthook` 1회(RuntimeError), QApplication 미생성 |
| `AboutLicensesTest`(2건) | `licenses_dir()` 개발 = 저장소 `licenses/`, 모의 frozen(`_MEIPASS`·`sys.executable` 한글 경로) = 실행 파일 옆. `about_text`에 고지 위치·법무 안내, `open_licenses`가 그 폴더 URL로 `openUrl`(대역), 폴더 없음이면 경고·`openUrl` 미호출 |
| `VerifierTest.test_app_checks_without_window` | 판정 함수의 참·거짓 사례, verify 원본에서 `HAZOP.exe` 실행 3곳이 모두 `--screenshots`·잘못된 옵션·시험 환경변수 중 하나이고 `bad-settings.json` 대화형 실행이 없음 |

| 실행 | 결과 |
|---|---|
| 전용 venv `-m unittest tests.test_app_startup` | 11건 OK |
| 전용 venv `-m unittest tests.test_packaging` | 65건 OK(W9 63 + W9-B 1 + W10 1) |
| 전용 venv `-m unittest discover -s tests -t .` | **703건 OK(건너뜀 5)**, rc=0. 작업 트리 기준이며 다른 트랙(T6 W9 등)의 진행 중 변경이 함께 들어 있다 |

## 4. 빌드·verify(W9-B·W10 함께)

- 이전 W9 산출물 `%TEMP%\hazop-w9`·`%TEMP%\hazop-w9-src`를 지웠다(C 드라이브 여유 28 GB → 29 GB). 다른 `hazop-*` 폴더는 건드리지 않았다.
- 스냅숏 `%TEMP%\hazop-w10-src`: HEAD `3231a54`, 577개(disk 501·head 11·overlay 65), 목록 해시 `7f7c52ad2cd358df47fe7d22d01de8aaf7cd8ac3f29f671a59a04ebbb9b12541`. `--restore-head` 11개는 다른 트랙의 진행 중 파일(`README.md`, `units/2026-11-05-design-system/` 4개, `hazop/viewer/template.html`, `scripts/check_design.py`, `tests/test_design.py`, `specs/` 3개)이다. overlay 65개 = `hazop/app/startup.py`·`tests/test_app_startup.py`·W9-B 원문 63개.
- 빌드 조건은 W9와 같다(닫힌 포트 프록시 `127.0.0.1:9`, `PIP_NO_INDEX=1`, PATH 통제 D10).

| 빌드 | 결과 | 경고 | 결과 폴더 |
|---|---|---|---|
| 검증용 `--with-check` | **rc=0**, 114초. 결과 폴더·고지·PDF·바이너리 검사 통과 | WARNING 2(W9와 같음) | `dist\HAZOP-verify\` 2,593개, 602,153,024 bytes |
| 배포용 | **rc=0**, 75초. 네 검사 통과 | WARNING 1(W9와 같음) | `dist\HAZOP\` **2,592개, 595,326,751 bytes(567.7 MiB)**. W9 재작업 1회차 대비 +63개(W9-B 원문)·+485,865 bytes |

| verify | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** rc=0 `results-verify-ascii\run-20261106-113048-7lzgop1n` | **통과** rc=0 `results-verify-korean\run-20261106-113131-picf2c3p` |
| 배포용 `--app-only` | **통과** rc=0 `results-deploy-ascii\run-20261106-113223-84hwgd_w` | **통과** rc=0 `results-deploy-korean\run-20261106-113232-s5cbp9n4` |

- 검증용 두 경로: flow rc=0(①~⑤ 함수 흐름), check_kg_screen rc=0(결과: 통과), pdf_probe rc=0·`pdf_problems` = `[]`, PNG 9장, `licenses_problems` = `[]`(W9-B 원문 포함), 저장소 불변, 잘못된 옵션 rc=2, **손상 설정 rc=2(0.2초)·`app_bad_settings` 참, 시험 트리거 rc=70(0.1초)·`app_log_unhandled` 참**.
- 배포용 두 경로: PNG 4장, `licenses_problems`·`pdf_problems` = `[]`, 저장소 불변, 잘못된 옵션 rc=2, **손상 설정 rc=2·`app_bad_settings` 참**.
- 산출물(저장소 밖): `%TEMP%\hazop-w10\`(`{verify,deploy}-build\`, `*.out`, `results-*\run-*\summary.json`·`app-bad-settings.log`·`app-excepthook.log`·`work-logs-app.log`), `%TEMP%\hazop-w10-src`, `%TEMP%\hazop-w9b-dl\`. 지울지는 총괄이 판단한다.

## 5. 기획서 문안(planner 반영용, 이 작업에서 고치지 않음)

`specs/interface.md`:

- §2.1 창 구성 표 "메뉴 (Qt)" 행: `도움말(버전·데이터 위치)` → `도움말(버전·데이터 위치: 프로그램 이름·버전, 자원·작업·저장 루트, 설정 파일, 제3자 라이선스 고지 위치와 "라이선스 고지 열기"(탐색기), 법무 검토 전 내부용 안내)`. 메뉴 이름을 "정보"로 바꾸려면 이 행과 함께 바꾼다(코드는 `hazop/app/main_window.py` `_menus`의 한 줄).
- §7.1 경로 분리 표 아래에 한 줄 추가: `- 설정 파일을 읽을 수 없으면(JSON 문법 오류·JSON 객체 아님·UTF-8 아님) 기본값으로 덮어쓰지 않습니다. 대화형 실행은 경로·원인을 보여 주고 "기존 파일을 백업하고 기본값으로 시작"(settings.json.bad-<시각>.json으로 이름 바꿈) 또는 "종료"를 고르게 하고, --screenshots 실행은 안내를 표준 오류에 쓰고 종료 코드 2로 끝냅니다.`
- §7.1 표 아래에 한 줄 추가(선택): `- 제3자 라이선스 고지는 묶인 실행에서 실행 파일 옆 licenses/에, 개발 실행에서 저장소 licenses/에 있습니다.`

## 6. 한계

- 대화형 대화상자(손상 설정·정보 창)는 대역으로만 시험했다. 묶인 실행에서 실제로 눌러 보는 시험은 사용자 화면에 창을 띄우므로 하지 않았다.
- `HAZOP_TEST_EXCEPTHOOK`은 배포용에서도 동작한다(창 없음, 종료 코드 70과 로그 한 줄).
- 처리되지 않은 실제 예외의 PyInstaller 영문 대화상자는 그대로다(D7 "오류 대화상자 유지"). 이번에 바뀐 것은 손상 설정이 더 이상 그 경로로 가지 않는다는 점이다.
- 설정 파일 읽기 `OSError`(권한·잠금)는 범위 밖이다.
- 비대화형 판정은 `--screenshots` 하나다(다른 비대화형 옵션은 없다).
- 백업 이름은 초 단위 시각이다. 같은 초에 같은 이름이 있으면 덮어쓰지 않고 종료한다.

## 7. 재작업 1회차(2026-11-06, Claude·Codex 조건부 승인 → 총괄 지시 1~8)

### 7.1 변경

| 지시 | 변경 |
|---|---|
| 총괄 판정(시험 트리거) | `packaging/rthook_verify_build.py`(신규): 검증용 빌드 표지 `sys._hazop_verify_build = True`만 세운다. `scripts/build_package.spec_text`가 `--with-check`일 때만 앱(HAZOP.exe) Analysis의 `runtime_hooks`에 더한다(HAZOP-check.exe·배포용에는 없음). `run_app.main`은 `HAZOP_TEST_EXCEPTHOOK=1`이고 표지가 있을 때만 트리거를 켠다. 실측: 배포용 spec·`build/HAZOP/*.toc`에 훅 0건, 검증용은 spec 1·`Analysis-00`·`EXE-00`·`PKG-00` TOC에 있음 |
| 총괄 판정(verify) | `verify_bundle.app_steps`(단계 4를 함수로 분리). 트리거 실행은 두 빌드 모두 `HAZOP.exe --screenshots <폴더> --settings <손상 설정>` + `HAZOP_TEST_EXCEPTHOOK=1`. 검증용 판정 `app_log_unhandled`(rc 70·"미처리 예외"·시험용 메시지), 배포용 판정 `app_trigger_off`(rc 2·시험용 메시지 없음·설정 실패 기록). 두 경우 모두 설정 파일 그대로·PNG 없음. 트리거가 회귀해도 `--screenshots`라 대화형 창이 뜨지 않는다 |
| 1(Codex 중) | `startup.check_settings`: 판정 때의 지문(크기·`st_mtime_ns`·SHA-256)을 대화상자 응답 뒤 이름 바꾸기 직전에 다시 구해 다르면(바뀜·없어짐) 백업하지 않고 처음부터 다시 판정한다(정상이면 그대로 시작, 다른 손상이면 다시 묻는다) |
| 2(Codex 중) | `settings_error`가 (종류, 원인)을 돌려준다: `CORRUPT`(ValueError 계열), `UNREADABLE`(OSError). 읽기 실패는 대화형이면 "설정 파일을 읽을 수 없음" 안내(버튼 "종료"만, 백업 선택지 없음) 후 rc 2, 비대화형이면 stderr("파일 권한·잠금을 확인…")·rc 2 |
| 3(Claude 3·4) | 기록 수준 INFO → WARNING(`hazop.settings`, 개발 실행에서 logging 기본 출력과 겹치지 않게 NullHandler). `paths.load_settings` 읽기 인코딩 `utf-8` → `utf-8-sig`(BOM 허용). 쓰기(`save_settings`)는 그대로 |
| 4(Claude 5) | 정보 창 닫기 버튼 "닫기"(RejectRole). `openUrl`이 실패하면 "탐색기로 폴더를 열지 못했습니다. 아래 폴더를 직접 여십시오." + 경로 |
| 5(Claude 6) | `licenses/README.md` OpenSSL 1행·크레이트 60행의 수정 열: "휠 파일 미수정(RECORD 대조), 소스 수정 여부 미확인" |
| 6(Codex 하·Claude 7) | 테스트 §7.2 |
| 7(Claude 8) | 완료 기준 문구: verify 중 **모달·오류 창 없음**(`--screenshots` 스크린샷 단계는 비모달 창이 잠깐 뜬다). PROGRESS·ROADMAP·D18 반영. §1.3의 "창을 띄우지 않는다"도 이 뜻이다 |

### 7.2 테스트

| 테스트 | 확인하는 것 |
|---|---|
| `SettingsCheckTest.test_settings_error`(수정) | 손상 3종은 `CORRUPT`, UTF-8 BOM 파일은 정상, OSError는 `UNREADABLE` |
| `test_unreadable_quits_without_backup_choice`(신규) | OSError: 대화형은 `ask` 미호출·`notify` 1회·rc 2, 비대화형은 stderr·rc 2, 백업 없음 |
| `test_failures_logged_as_warning`(신규) | `hazop.settings` WARNING 기록 |
| `test_file_changed_during_dialog_is_rejudged`(신규) | 응답 사이 정상으로 고치면 백업 없이 시작, 다른 손상으로 바뀌면 다시 묻고(원인 JSONDecodeError) 종료 시 파일 그대로 |
| `RunAppStartupTest.test_test_excepthook_trigger_only_in_verify_build`(교체) | 표지 있음 → rc 70·`excepthook` 1회, 표지 없음 → 트리거 무시, 손상 설정 처리로 rc 2. 두 경우 모두 QApplication 미생성 |
| `RunAppStartupTest.test_interactive_backup_then_window_with_defaults`(신규) | 대화형 "백업" → 이름 바꾼 뒤 MainWindow가 같은 설정 경로·`ask_reviewer=True`·기본값 설정으로 만들어짐, 백업 파일 1개(창·이벤트 루프는 대역) |
| `AboutLicensesTest.test_about_text_and_open`(보강) | `openUrl` 실패 시 경로 안내·False, `_about`의 버튼이 "라이선스 고지 열기"·"닫기" |
| `BuildSpecTest.test_spec_text`(보강) | 표지 훅이 검증용 spec에만 1번, 배포용 0번 |
| `VerifierTest.test_app_checks_without_window`(수정) | `bad_settings_ok`·`trigger_ok`(검증용 rc 70만 참, 배포용 rc 2만 참) |
| `VerifierTest.test_app_steps_mock_run`(신규) | verify `app_steps`를 대역 HAZOP.exe로 실행. 대역은 **실제 `scripts/run_app.main`**을 같은 프로세스에서 부르고(정상 설정 스크린샷만 rc 0으로 건너뜀), 런타임 훅처럼 root logging·`sys.excepthook`을 `app.log`에 연결한다. 대화상자·`make_application`이 불리면 실패하고, 모든 실행 인자가 `--screenshots` 또는 잘못된 옵션인지 확인한다. 검증용·배포용 빌드 × 검증·`--app-only` 판정 4조합에서 손상 설정 rc 2, 트리거 rc 70/2, 판정이 맞는 조합에서만 통과 |

| 실행 | 결과 |
|---|---|
| 전용 venv `-m unittest tests.test_app_startup` | 15건 OK |
| 전용 venv `-m unittest tests.test_packaging` | 66건 OK |
| 스냅숏(HEAD `c155845` + 이 작업만) `-m unittest discover -s tests -t .` | **708건 OK(건너뜀 8)**, rc=0. 건너뜀 8은 스냅숏에 없는 미추적 자료 때문으로 보인다(작업 트리 5) [추론] |
| 작업 트리 `-m unittest discover -s tests -t .` | 722건, **오류 1**: `tests.test_export.TestValvePathEvidence.test_closed_valve_on_cited_path_shown`(`KeyError: 'xlsx'`). 다른 담당이 진행 중인 `hazop/export/worksheet.py`·`tests/test_export.py` 변경이며 이 작업 파일과 겹치지 않는다. 그 변경을 HEAD로 둔 스냅숏에서는 통과 |

### 7.3 빌드·verify

- 이전 W10 산출물(`%TEMP%\hazop-w10`, `-src`)을 지우고 다시 만들었다. 스냅숏 `%TEMP%\hazop-w10-src`: HEAD `c155845`, 581개(disk 506·head 9·overlay 66), 목록 해시 `7949a3a3eecba687ec873aecfea860bc86d2bfbf4971809065f4d38defabb0a7`. `--restore-head` 9개 = 다른 담당 진행 중 파일(`hazop/analysis/ai.py`·`run.py`, `hazop/export/worksheet.py`, `scripts/run_samples.py`, `tests/test_analysis.py`·`test_export.py`, `specs/extraction.md`, `design/` 2개). 다른 담당의 미추적 파일(`scripts/clean_outputs.py` 등)은 넣지 않았다. HEAD는 1차 기준 `3231a54` 뒤로 다른 담당 커밋 2개(`61a3984` T6 W9, `c155845` 기획서)가 더해졌고 이 작업 파일과 겹치지 않는다.

| 빌드 | 결과 | 경고 | 결과 폴더 |
|---|---|---|---|
| 검증용 `--with-check` | **rc=0**, 119초, 네 검사 통과 | WARNING 2(이전과 같음) | 2,593개, 602,158,887 bytes |
| 배포용 | **rc=0**, 94초, 네 검사 통과 | WARNING 1(이전과 같음) | **2,592개, 595,330,784 bytes** |

| verify | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** rc=0 `results-verify-ascii\run-20261106-115617-soefo9pp` | **통과** rc=0 `results-verify-korean\run-20261106-115701-gbul7hr6` |
| 배포용 `--app-only` | **통과** rc=0 `results-deploy-ascii\run-20261106-115743-t5tdqvhr` | **통과** rc=0 `results-deploy-korean\run-20261106-115753-gcrp87p0` |

- 검증용: flow rc=0(①~⑤), check_kg_screen rc=0, pdf_probe rc=0, PNG 9장, `licenses_problems`·`pdf_problems` = `[]`, 입력 사본·저장소 불변, 잘못된 옵션 rc 2, 손상 설정 rc 2(0.2·0.3초), **트리거 rc 70(0.1·0.2초)·`app_log_unhandled` 참**.
- 배포용: PNG 4장, 고지·PDF 문제 없음, 저장소 불변, 잘못된 옵션 rc 2, 손상 설정 rc 2, **트리거 실행 rc 2(0.2·0.3초)·`app_trigger_off` 참**(트리거 꺼짐).
- 모든 비대화형 실행이 1초 안에 끝났다(모달·오류 창이 떴다면 60초 시간 제한에 걸림). 스크린샷 단계(5.6~9.5초)는 비모달 창이 잠깐 뜬다.

### 7.4 남은 한계(§6 갱신)

- 지문 재확인과 이름 바꾸기 사이의 아주 짧은 간격은 남는다(같은 프로세스 안 연속 호출). 파일 잠금은 쓰지 않았다.
- 대화형 대화상자를 묶인 실행에서 실제로 누르는 시험은 하지 않았다(사용자 화면에 창이 뜸). 대역 시험만 했다.
- 실제 처리되지 않은 예외가 부트로더를 거쳐 `sys.excepthook`을 부르는 경로는 이번에도 다시 실행하지 않았다(오류 창이 뜨는 시험).
- §6의 "`HAZOP_TEST_EXCEPTHOOK`은 배포용에서도 동작" 한계는 해소했다(배포용에서는 꺼짐, verify로 확인). §6의 "`OSError`는 범위 밖"도 해소했다.
