# W4 — 첫 PyInstaller one-folder 빌드 (T2)

> 1차 2026-11-05 22:20~22:43(기준 `5fa64ee`), 재작업 1회차 22:50~23:15. **재작업 2회차(최종): 2026-11-05 23:20 ~ 11-06 00:10**(기준 HEAD `f3b309e` + W4 미커밋 변경). 실행 주체: hazop-developer.
> 근거 결정: D1, D5(확정), D6(완료 기준 해석, 확정), D7안(앱 로그). 이 문서의 수치는 모두 2회차 결과다. 이전 회차는 §8에 요약했다.

## 0. 판정 범위(D6)

- ①②④⑤ PNG는 `HAZOP.exe --screenshots`로 찍는다. ③ PNG·③ V1·V2·S1·①~⑤ 함수 흐름은 같은 `_internal`을 쓰는 검증 전용 실행 파일 `HAZOP-check.exe`로 확인한다.
- `HAZOP-check.exe`는 **검증 전용이며 배포본에서 제외한다(check_dist로 확인)**. 받은 임의의 `.py`를 실행할 수 있기 때문이다. `--with-check` 빌드(`dist/HAZOP-verify/`)에만 있고, 배포용 빌드(`dist/HAZOP/`)에 들어 있으면 `build_package.check_dist`가 빌드를 실패시킨다.
- **한계(M1)**: `HAZOP.exe` 자체에서는 importlib 스크립트 로딩(`data.script_module` → `extract_and_graph`)을 실행하지 못했다. ① 화면은 등록 기록이 있을 때만 `extract_drawio`를 읽는데, `run_app.py --screenshots`는 저장 루트를 항상 새 임시 폴더로 바꾼다. 이 경로를 HAZOP.exe에서 실행하려면 `scripts/run_app.py`나 `hazop/app/screenshots.py`를 고쳐야 하고, 둘 다 편집 범위 밖이다(후속 결정 필요). 같은 `_internal`의 스크립트 로딩은 `HAZOP-check.exe` 흐름에서 확인했다.
- 빌드는 저장소 밖 스냅숏(§1)에서 했고, T6 진행 중 파일 5개는 HEAD 내용으로 되돌렸다.
- "저장소 없는 환경"은 같은 PC에서 격리해 확인했다(실행마다 새 폴더, 작업 폴더·`HAZOP_WORK_ROOT`·`APPDATA`·`TEMP` = 임시, `PYTHONPATH`·`HAZOP_*` 제거, 입력 사본에 `hazop/` 없음). 다른 PC에서는 시험하지 않았다.

## 1. 스냅숏 재현

```
python packaging/make_snapshot.py --dest %TEMP%\hazop-w4r2-src ^
  --restore-head hazop/app/tokens.py hazop/app/widgets.py hazop/viewer/template.html scripts/check_design.py tests/test_design.py ^
  --overlay scripts/build_package.py packaging/check_entry.py packaging/w4_flow.py packaging/verify_bundle.py ^
            packaging/rthook_applog.py packaging/make_snapshot.py packaging/netwatch.ps1
```

- 추적 파일 336개는 작업 트리 디스크 바이트 그대로 복사한다. `--restore-head` 5개는 `git show HEAD:` 바이트로 쓴다. `--overlay`는 이번 작업의 미추적 새 파일 7개다. 그 밖의 미추적 파일(예: `참고자료/HAZOP 기법`)은 넣지 않는다.
- 두 옵션의 경로는 `normalize_rel`로 정규화한다. 절대 경로·드라이브·`./`·`../`·`..` 조각은 거부하고, realpath가 저장소 밖이면 거부하며, 링크 때문에 정규화 결과가 달라지는 경우도 거부한다. 추적 여부는 정규화한 경로로 비교하고, 쓰는 위치는 `dest_path`로 목적지 안인지 확인한다. 경로 검사는 git을 부르기 전에 한다.
- 결과: HEAD `f3b309e`, 343개(disk 331·head 5·overlay 7), `SNAPSHOT.json` 목록 해시 `f69348f663ec1796b3b75e6f586bcaae63ede4f0e23b8cef8b448a3582558805`.
- head 파일 sha256(앞 16자, 1회차와 같음): tokens.py `35f8d6cf28a740f9`, widgets.py `76d549cdf69da37e`, viewer/template.html `0a2c93ab8ef19a3f`, check_design.py `c38be7dd694f0dc6`, test_design.py `53e398f1dee013b3`.
- 빌드 뒤 스냅숏 안에서 바꾼 파일은 3개이며 모두 묶음에 들어가지 않는다: `packaging/netwatch.ps1`(경로 정규화, `42a045618f41742b`), `packaging/make_snapshot.py`(경로 검사를 git 호출 앞으로, `6a14871a1247a181`), `tests/test_packaging.py`(`.git` 없는 스냅숏에서 추적 판정 건너뜀, `70001f5cde807c67`). 작업 트리의 같은 파일을 복사했다.

## 2. 변경 파일(2회차 반영 위치 포함)

| 파일 | 내용 |
|---|---|
| `scripts/build_package.py` | datas 12개·spec·`write_spec`(저장소 안 거부)·`check_dist`(배포용에 검증 exe 있으면 실패, 검증용은 `dist/HAZOP-verify/`). hiddenimports `collect_submodules("hazop")` + 두 스크립트, excludes anthropic·httpx·pdfplumber, `console=False`, UPX 없음, 런타임 훅, Analysis별 경고 파일 복사(`warn-HAZOP-app/check.txt`) |
| `packaging/rthook_applog.py` | 묶인 실행에서 `<작업 루트>/logs/app.log`에 logging·`None`인 stdout/stderr·미처리 예외를 남긴다. **2회차(5)**: 로그 쓰기에서 예외가 나도 이전 훅을 `finally`에서 부른다 |
| `packaging/check_entry.py` | **2회차(6·9)**: docstring에 "검증 전용, 배포본 제외(check_dist로 확인), 임의 `.py` 실행 가능"을 적었다. vendor 교체는 `check_kg_screen.py`만 한다(`check_kg_renderer.py`는 제외: 직접 실행하면 미리 읽은 모듈을 쓰지 않으므로). 대상 스크립트가 바꾼 `sys.path`는 실행이 끝나면 원복한다 |
| `packaging/w4_flow.py` | **2회차(3)**: `ok()`가 실패하면 `Stop`을 던져 그 자리에서 끝낸다. 사전 검사는 복사·분석 전에 한다: 작업 루트 환경변수 → 루트 → 묶음 datas 12개 해시 → 자원 경로(구간 JSON의 기준 자료 4종·지침서가 자원 루트에서 묶음 안이고 빌드 원본 해시와 같음). 그 뒤 ①~⑤, ④ 실행 기록의 읽은 위치·해시, 음성 검사 2건을 한다 |
| `packaging/verify_bundle.py` | **2회차(2·4)**: 기존 폴더를 자동으로 지우는 동작을 없앴다. `--target-base` 아래에 실행마다 새 폴더 `verify-<시각>-<uuid8>`(또는 `--run-name`)를 만들고, 같은 이름이 있으면 실패로 끝낸다. 새 폴더를 만든 뒤의 모든 단계(저장소 해시 `tree_hashes` 포함)는 try 안에서 하고, `finally`에서는 이번 실행 폴더만 지운다. 지우지 못하면 `errors.cleanup`에 남기고 실패 처리한다. 그 밖의 내용은 1회차와 같다: 새 결과 폴더, PNG mtime, 해시 비교, `inputs_unchanged` 통과 조건, `--app-only`, 앱 로그 확인 |
| `packaging/make_snapshot.py` | **2회차(1)**: 위 §1의 경로 정규화 |
| `packaging/netwatch.ps1` | **2회차(8)**: `-PathLike`를 `;`로 구분한 문자열로 받아 나눈다. 프로세스 경로는 `GetFullPath`로 정규화한다(Qt가 `...\PySide6\.\QtWebEngineProcess.exe`로 보고하기 때문). 표본마다 `dt_ms`·`pids`·`tcp_remote`·`udp`를 기록한다 |
| `tests/test_packaging.py` | 29건(빌드 없음). **2회차(7)** 추가·수정: 스냅숏 탈출(`../`·`./`·중간 `..`·절대·드라이브·빈 조각, 목적지 탈출, main이 복사 전에 거부), 해시 실패 시 즉시 종료(작업 루트에 아무것도 복사하지 않고 단계는 `work_root_env·roots·bundle-datas`까지만), 개발 실행이면 루트에서 종료, 자원 경로가 저장소로 폴백하는 경우, 검증기의 기존 폴더 비삭제(위조 표지가 있는 같은 이름 폴더 → 실패하고 지우지 않음), 첫 단계(`tree_hashes`) 예외와 정리 실패 기록, 로그 쓰기 실패 시 이전 훅 호출 |
| `기획서/인터페이스.md` §7.1 | 화면이 읽는 `scripts/extract_drawio.py`·`build_graph.py`는 프로그램 루트에서 읽는다(1회차) |

## 3. 빌드(스냅숏 `%TEMP%\hazop-w4r2-src`)

재빌드 판단: 묶음에 들어가는 `rthook_applog.py`(HAZOP.exe)와 `check_entry.py`(HAZOP-check.exe)가 바뀌었으므로 두 빌드를 모두 다시 했다.

| 빌드 | 명령(`--out`) | 결과 | 로그 | 결과 폴더 |
|---|---|---|---|---|
| 검증용 | `scripts/build_package.py --out %TEMP%\hazop-w4r2\verify-build --with-check --build` | rc=0, 약 76초, `check_dist` 통과 | 201줄, WARNING 2 | `dist\HAZOP-verify\` 606,870,037 bytes, 3,126개 |
| 배포용 | `scripts/build_package.py --out %TEMP%\hazop-w4r2\deploy-build --build` | rc=0, 약 58초, `check_dist` 통과 | 99줄, WARNING 1 | `dist\HAZOP\` **600,905,040 bytes(573.1 MiB), 3,119개**, HAZOP-check.exe 없음 |

- 경고는 두 빌드 모두 같은 종류다: `qmlassetdownloaderprivateplugin.dll does not exist`. 앱은 QML을 쓰지 않는다[추론: 영향 없음].
- **네트워크**: 빌드 환경에 닫힌 포트 프록시와 `PIP_NO_INDEX=1`을 지정했다. `packaging/netwatch.ps1`로 표본 조사했다(지정 간격 1초).

| 기록 | 대상 | 표본 | 대상 프로세스가 잡힌 표본 | 실제 간격 평균·최대 | 원격 TCP·UDP |
|---|---|---|---|---|---|
| `netwatch-build.log` | venv·기반 python(두 빌드) | 96 | 94 | 1,422 · 2,197 ms | 0 · 0 |
| `netwatch-runtime.log` | 검증 사본의 `HAZOP.exe`·`HAZOP-check.exe`·`_internal\PySide6\QtWebEngineProcess.exe`(검증 4회 실행 동안) | 242 | 230(그중 2개 동시 40) | 1,402 · 2,247 ms | 0 · 0 |

- 런타임 측정 경과: 1차 런타임 표본(`netwatch-runtime-1st.log`, 243회)에서는 동시에 잡힌 프로세스가 1개뿐이었다. 진단해 보니 `QtWebEngineProcess.exe` 경로가 `...\PySide6\.\QtWebEngineProcess.exe`로 보고되어 패턴과 맞지 않았다. 경로 정규화를 넣은 뒤 다시 측정하자 2개 동시(메인과 QtWebEngineProcess로 판단[추론: 두 exe는 동시에 실행되지 않음])가 잡혔다. 한계: 1초 표본 사이의 짧은 연결은 놓칠 수 있다. 배포용 `--app-only` 실행은 웹뷰가 내용을 그리지 않아 QtWebEngineProcess가 뜨지 않았다(진단에서 자식 프로세스 0).

## 4. 묶인 실행 검증(`packaging/verify_bundle.py`, 스냅숏에서 실행)

명령: `--dist <검증용 dist\HAZOP-verify> --target-base <base> --out <결과>`, 배포용은 `--dist <dist\HAZOP> ... --app-only`. base는 `%TEMP%\hz_ascii`와 `%TEMP%\한글테스트`다. 마지막 실행(런타임 측정과 함께 한 회) 결과:

| 실행 | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** `results-verify-ascii\run-20261105-235626-*` | **통과** `results-verify-korean\run-20261105-235915-*` |
| 배포용 `--app-only` | **통과** `results-deploy-ascii\run-20261105-235806-*` | **통과** `results-deploy-korean\run-20261106-000054-*` |

바로 앞 회차(23:48~23:53)도 4건 모두 통과했다. 모든 실행에서 `run_root_removed`가 true였다(이번 실행 폴더만 삭제). base 아래에 남은 `HAZOP`·`HAZOP-deploy`는 1회차 검증 사본이며, 2회차 규칙(기존 폴더 비삭제)에 따라 지우지 않았다.

검증용 실행 결과(두 경로 같음):

- **흐름**: `work_root_env`, `roots`(프로그램 = 자원 = 사본 `_internal`), `bundle-datas` 12개 해시, `resource_paths`(분석 전)가 모두 OK다. 이어서 graph_version `v-7ed95b0c74f1`, ① 등록·스크립트 모듈 `_internal\scripts\`·`registered_derived`, ② 뷰어, ③ HTML(vendor = 묶음), ④ `passed` 44·14·6·11과 실행 기록의 기준 자료 4종·지침서 = 묶음 파일·해시 일치를 확인했다.
  - 음성 검사: 패턴 파일을 치우면 `InputError`, 지침서를 치우면 `input_blocked`가 난다.
  - ⑤ 검토 v1과 Excel 1개를 만들었다.
- **③ 검사**: V2(vendor SHA-256 `f59db59b…a629` = SOURCE.md, LICENSE, 외부 URL·`<script src>` 없음), 렌더링(오류 0), V1(15건, 프로토타입 ID 11건, 표시 토글), S1(5,001 경고, 5,000 없음), ③ 탭(1366×768, S1 띠) 모두 OK다. 입력 사본은 해시 기준으로 바뀌지 않았다.
- **앱**: PNG 9장이 이번 실행에서 생겼다(HAZOP.exe 7장, HAZOP-check.exe ③ 2장). 앱 로그에 시작 기록이 있고, JSON 배열 설정으로 낸 실제 미처리 `ValueError`가 "미처리 예외"와 함께 로그에 남았다(오류 대화상자 때문에 60초 뒤 강제 종료). 잘못된 옵션의 종료 코드는 2다.
- **저장소**: `출력/`·`자료저장소/` 파일 해시가 전후 같다. 바깥 sha256 목록 비교도 `ef7c06c8…b261`로 전후 동일했다.

배포용 `--app-only` 실행: HAZOP-check.exe 없음을 확인했다. ①②④⑤ PNG 4장(빈 상태), 앱 로그 시작·미처리 예외 기록, rc=2, 저장소 불변도 확인했다.

### 검증 하네스 조정(코드 결함 아님)

1. ③ 검사만 `HAZOP_WORK_ROOT`를 입력 사본으로 둔다. `run_one`이 도면 경로를 작업 루트 기준으로 기록하기 때문이다.
2. ③ 검사는 `QT_QPA_PLATFORM=windows`로 실행한다. offscreen에서는 위젯 한글이 빈 상자로 찍히는데 개발 실행도 같다. T1에 전달할 사항이다.
3. 로그 파일 연결은 stdout·stderr가 `None`일 때만 한다. 하위 프로세스 실행에서는 핸들이 있어서 사용법 오류는 표준 출력 사본으로 간다. 더블클릭 실행은 직접 확인하지 않았다[추론].
4. 2회차 작업 중 실수가 하나 있었다: 런타임 측정 대기 루프가 netwatch 로그 첫 줄의 BOM 때문에 끝나지 않아 약 20분을 허비했다. 검증은 실행되지 않았고, 멈춘 루프를 종료한 뒤 다시 실행했다.

## 5. 실행한 테스트

| 실행 | 결과 |
|---|---|
| 전용 venv 작업 트리 `-m unittest discover -s tests`(문서 갱신 전 마지막 실행) | **599건 OK**(건너뜀 14). T6 진행 중 변경 포함 |
| 전용 venv 스냅숏 `hazop-w4r2-src` 같은 명령 | **591건 OK**(건너뜀 14) |
| `tests.test_packaging`(작업 트리·스냅숏) | 29건 OK |

## 6. 한계·남은 일

- HAZOP.exe 자체의 importlib 스크립트 로딩은 실행하지 못했다(§0, 후속 결정 필요).
- 런타임 네트워크는 1초 표본 조사이므로 짧은 연결은 놓칠 수 있다. 배포용 실행에서는 웹뷰 자식 프로세스가 뜨지 않았다.
- `check_kg_screen` 6단계(tests)는 건너뛰었다(개발 실행 전체 테스트에서 통과).
- 앱 로그 미정 항목은 D7을 따른다(Qt 메시지 핸들러 미연결, 로그 크기 제한 없음 등).
- 묶음 크기를 줄이지 않았다(Qt3D·Charts·QML DLL, `.debug.pak`, 번역 파일 포함).
- 참고자료 제외(D5)로 묶음에서 `extract_drawio --samples`가 찾는 파일이 없다. PDF 어댑터는 범위 밖이다.
- 작업 루트 초기 내용, 서명·백신 오탐, 라이선스 고지(W6), 다른 PC 시험은 하지 않았다.

- **알려진 한계(D8)**: Codex 최종 재검토의 테스트 공백 — 존재하는 파일의 해시 불일치 후 중단, 해시 수집 실패 뒤 정리 성공, stream 쓰기·flush 실패 시 이전 훅 호출을 각각 직접 검사하지 않음(현재 테스트는 파일 누락·getLogger 실패로 대신). Claude R1: `netwatch.ps1`은 표본마다 프로세스 수만 기록(이름·pid 없음) — 동시 2개가 메인+QtWebEngineProcess라는 해석은 [추론]. Claude R2: `w4_flow.py`에서 Stop 이외 예외가 나면 flow.json·RUN_DIR이 남지 않음(판정은 rc≠0으로 실패). 총괄 직접 수정: `make_snapshot.py`가 추적 파일도 저장소 밖을 가리키면 거부하고, `--restore-head`를 Git의 정확한 경로로 맞춤.

## 7. 산출물(저장소 밖)

`%TEMP%\hazop-w4r2\`: `verify-build\`·`deploy-build\`(spec·datas.json·build.log·build\warn-*·dist), `netwatch-build.log`·`netwatch-runtime.log`·`netwatch-runtime-1st.log`, `results-{verify,deploy}-{ascii,korean}\run-*\`(summary.json·flow.json·로그·png·work-logs-app.log), `console*-*.txt`. `%TEMP%\hazop-w4r2-src`(스냅숏). 1회차 산출물(`%TEMP%\hazop-w4r1*`, base 아래 `HAZOP`·`HAZOP-deploy`)은 남아 있다. 지울지는 총괄이 판단한다.

## 8. 이전 회차 요약

- 1차(기준 `5fa64ee`): `--with-check` 빌드 1회, 두 경로 통과. Codex 반려, Claude 조건부.
- 재작업 1회차(기준 `f3b309e`): Codex 1~10, Claude M2·M3·L1·L4·L5, 총괄 M1·L2를 반영했다. 검증용·배포용 빌드를 만들어 두 경로에서 통과했다(배포용 573.1 MiB). 런타임 네트워크는 `-PathLike` 전달 문제로 측정하지 못했다. Codex 반려, Claude 조건부.
- 재작업 2회차(이 문서): Codex 1~7, Claude N1~N3를 반영했다.
