# W8-A — PATH 경유 DLL 수집 차단 (T2)

> 1차 2026-11-06 01:05~01:35, 재작업 1회차 01:40~02:00. **재작업 2회차(최종): 02:00~02:25**, 기준 HEAD `dbcc855`(T6 W4 커밋) + W8-A 미커밋 변경. 실행 주체: hazop-developer.
> 근거 결정: D10(확정, 총괄 판정 — 사용자 위임 권장안). §3~§6·§8의 수치는 재작업 2회차 결과다. 1차와 1회차의 수치는 §9에 있다.
> 배경: [W6 라이선스](w6-licenses.md) §8·§9-6, [W6 첨부 수집 목록](w6-bundle-collect-list.md) §2. W4 배포 묶음에 DLL 45개가 빌드 PC의 PATH에서 들어왔다.

## 1. 원인(PyInstaller 6.22.3 원본 확인)

- **UCRT는 기본으로 빠지지 않는다.** `PyInstaller/depend/dylib.py`에서 UCRT(`api-ms-win-core.*`·`api-ms-win-crt.*`·`ucrtbase.dll`)는 `_win_includes`에 있다. 그래서 Windows 폴더 제외 규칙보다 우선해, 찾으면 묶는다.
  - 141~145행 주석은 "Windows 10 이상이면 묶을 필요가 없으니 스위치로 둘 것"이라고 적고, Microsoft 문서 "Determining which DLLs to redistribute"의 "UCRT is now a system component in Windows 10 and later, managed by Windows Update"를 인용한다.
  - 실제 동작은 경고만 숨기는 것이다(`api-ms-win-.*`, Windows 10 이상).
- **PATH에서 의존 DLL을 찾는다.** `PyInstaller/depend/bindepend.py`의 `resolve_library_path`는 의존 DLL을 먼저 그 파일의 폴더와 추가 검색 경로에서 찾고, 없으면 PATH에서 찾는다.
- **이 PC에서 JDK 출처가 된 경위.**
  - `C:\Windows\System32`에는 `ucrtbase.dll`만 있고 `api-ms-win-crt-*.dll`은 `System32\downlevel\`에만 있다.
  - 그래서 `python312.dll` 등이 가져오는 `api-ms-win-crt-*`가 PATH 뒤쪽의 JDK `bin`에서 해석되었다.
  - 이어서 같은 폴더의 `ucrtbase.dll`도 함께 묶였다 [추론: 해석 순서상 의존 파일의 폴더가 먼저].
- **Qt용 OpenSSL도 PATH에서 찾는다.** `PyInstaller/utils/hooks/qt/__init__.py`의 `_collect_qtnetwork_openssl_windows`는 `libssl-3-x64.dll`·`libcrypto-3-x64.dll`을 Qt 폴더와 PATH에서 찾는다. PySide6 휠에는 이 파일이 없어서, PATH의 Git for Windows `mingw64\bin`에서 찾았다.
- **실행 PC에서도 같은 위험이 있다.** Qt `tls/qopensslbackend.dll` 플러그인이 있으면 Qt는 실행 중 PATH에서 `libssl-3-x64.dll`을 찾아 읽는다(1차 측정 §9).

## 2. 변경(재작업 1·2회차 반영 위치)

| 지적 | 반영 위치 |
|---|---|
| Claude 1: Qt OpenSSL TLS 플러그인 제외와 사후 검사 | `scripts/build_package.py`: `EXCLUDED_BINARIES`, spec의 `drop_binaries`(검증용 HAZOP-check Analysis에도 적용), `forbidden_entries`(TOC), `forbidden_files`(결과 폴더). 재측정은 §5.2 |
| Claude 2: 허용 루트를 venv·기반 CPython으로 축소하고 이름 거부 목록 추가 | `allowed_roots()`에서 Windows 폴더를 뺐다. `FORBIDDEN_NAME`(`ucrtbase`, `api-ms-win-*`, `lib(ssl|crypto)-3-x64`)은 묶음 안 이름과 출처 파일 이름 모두에 적용한다 |
| Codex 1: 이름을 바꾼 DATA 바이너리 | `foreign_binaries`가 출처 확장자(.dll·.pyd·.exe)도 본다 |
| Codex 2·Claude 5: 빈·손상 TOC | `read_toc`가 구조(`([...],)`), 3열 문자열, EXECUTABLE `HAZOP.exe` 존재를 확인한다. 실패하면 ValueError를 내고, `check_sources`가 "형식 오류"로 돌려주어 rc=3이 된다 |
| Codex 3: 상대 경로·SYMLINK | 상대 경로 출처는 거부한다. SYMLINK는 출처 검사 대신 링크 대상이 묶음 밖(`..` 탈출·절대 경로)이면 실패로 처리한다 |
| Codex 4: 전용 venv 확인 | `python_problems()`가 sys.prefix = `%USERPROFILE%\.hazop\venv-py312`, venv 여부, CPython 3.12.10을 확인한다. 다르면 `--build`를 rc=2로 중단한다. 우회는 `--allow-other-python` |
| Codex 5·Claude 6: 검증기 환경과 판정 문구 | `packaging/verify_bundle.py`: `child_env`가 PATH 외에 `QT_*`·`OPENSSL_*`·`SSL_CERT_*`를 지운다(`CHILD_DROP_PREFIXES`). 머리말 문구는 "빌드 PC 사용자 PATH 의존 제거, 다른 PC와 같은 조건이라는 보장은 아님"으로 한정했다 |
| Codex 6·Claude 8: 테스트 | `tests/test_packaging.py`: 아래 §6 |
| Claude 7: 지원 OS와 UCRT 근거 출처 | `packaging/README.md`에 지원 OS(Windows 10 이상 64비트)를 적었다. D10에 dylib.py 141~145행 주석 출처를 붙였다 |
| Claude 1: D10 '제외' 서술 | "앱 코드 변경 필요" 서술을 지우고 ③ 플러그인 제외로 바꿨다(decisions.md D10) |

재작업 2회차(1회차 검토: Codex 반려, Claude 승인) 반영 위치는 다음과 같다.

| 지적 | 반영 위치 |
|---|---|
| Codex 1: 다른 이름으로 수집한 TLS 플러그인 | `scripts/build_package.py`: `tls_rejected`가 `plugins/tls/` 아래를 허용 목록(`TLS_ALLOWED` = qschannelbackend·qcertonlybackend)으로만 둔다. 판정은 묶음 안 이름과 출처 실경로의 긴 파일명 양쪽으로 한다. 어느 이름이든 `qopensslbackend.dll`이면 거부한다. spec은 같은 함수(`from build_package import drop_binaries`)를 binaries·datas에 적용하고, 사후 검사는 `forbidden_entries`(TOC)·`forbidden_files`(결과 폴더)로 한다 |
| Codex 2: 8.3 단축명·링크 별칭 | `long_real()`: `os.path.realpath`(junction·링크 해석) 뒤 `GetLongPathNameW`. 이름 거부 목록을 출처 실경로의 긴 파일명에도 적용한다 |
| Codex 3·Claude 3: 인터프리터 경로 비교 | `python_problems`가 sys.prefix·base_prefix·기대 venv를 `long_real`+normcase로 비교한다. `PYTHON_VERSION` 주석과 `packaging/README.md`에 "패치 판을 올릴 때 함께 바꿈"을 적었다 |
| Codex 4: 검증기 문구 | `packaging/verify_bundle.py` 머리말: "사용자 PATH 경유 탐색을 제한한다" |
| Codex 5: 테스트 | `test_tls_plugin_renamed_rejected`, `test_alias_short_name`(실제 8.3 단축명 생성, 못 만들면 skip — 이 PC에서는 실행됨), `test_alias_junction`(실제 junction `mklink /J`, 못 만들면 skip — 실행됨: venv 별칭 허용, 별칭 너머 `plugins/tls/`의 다른 이름 파일 거부), `test_spec_drops_openssl_tls_plugin` 갱신 |
| Claude 6: TLS 측정 스크립트와 원본 출력 | `packaging/tls_probe.py`(신규, 검증 전용, 묶음에 넣지 않음). 결과와 원본 출력은 §8 |
| Claude 7: PROGRESS 완료 기준·상태 문구 | `PROGRESS.md` 19·20·31행: 완료 기준을 "venv·기반 CPython 밖"으로 고치고, 상태를 "재작업 2회차 완료(재검토 대기)"로 맞췄다 |

그 밖의 1차 변경(PATH 통제 4개 경로, build.log에 PATH 기록, 검증기 자식 PATH = `System32;Windows`)은 그대로 유지한다. `licenses/`는 바꾸지 않았다. 고지 목록에 UCRT·OpenSSL `-x64`·`qopensslbackend` 행이 없기 때문이며, 해시 테스트도 그대로다.

## 3. 스냅숏·빌드

```
python packaging/make_snapshot.py --dest %TEMP%\hazop-w8r2-src ^
  --restore-head hazop/app/tokens.py hazop/app/widgets.py hazop/viewer/template.html scripts/check_design.py tests/test_design.py ^
  --overlay packaging/tls_probe.py
```

- 스냅숏 결과는 HEAD `dbcc855`, 394개(disk 388·head 5·overlay 1), 목록 해시 `3e2c5517d3ca27d7415391d38db931746f3568049e2379ff4e792b8ea983b5ad`다.
- 작업 중에 T6 W4가 커밋되어 HEAD가 `a0df5ef`에서 `dbcc855`로 바뀌었다. 그래서 `--restore-head` 5개는 새 HEAD 내용이며, head 파일 sha256 앞 16자도 W4 값과 다르다(`c6183ffe7d6bf73f`·`c75669690538b401`·`d2164bda14545b3e`·`9135a935871e1957`·`3643e9e314574b71`). 묶음에는 커밋된 T6 `hazop/viewer/template.html`이 들어간다.
- 스냅숏 뒤 작업 트리에서 바꾼 파일은 `packaging/README.md`와 `docs/` 문서뿐이다. 모두 묶음에 들어가지 않는다.
- 빌드 환경은 닫힌 포트 프록시와 `PIP_NO_INDEX=1`이다. netwatch는 돌리지 않았다.
- 인터프리터 확인은 두 빌드 모두 통과했다(중단·경고 출력 없음).

| 빌드 | 명령(`--out`) | 결과 | 로그 | 결과 폴더 |
|---|---|---|---|---|
| 검증용 | `%TEMP%\hazop-w8r2\verify-build --with-check --build` | rc=0, 67초, check_dist 통과, **바이너리 검사 통과** | WARNING 2(W4와 같은 qml 경고) | `dist\HAZOP-verify\` 597,658,749 bytes(570.0 MiB), 3,126개 |
| 배포용 | `%TEMP%\hazop-w8r2\deploy-build --build` | rc=0, 52초, check_dist 통과, **바이너리 검사 통과** | WARNING 1 | `dist\HAZOP\` **591,693,665 bytes(564.3 MiB), 3,119개** |

두 결과 폴더의 `_internal\PySide6\plugins\tls\`에는 `qcertonlybackend.dll`·`qschannelbackend.dll`만 있다.

## 4. 출처별 집계(COLLECT-00.toc, 이전 대비)

| 출처 | 종류 | W4 배포용 | **W8-A 배포용** | W4 검증용 | **W8-A 검증용** |
|---|---|---|---|---|---|
| PATH의 다른 프로그램(JDK UCRT 43, Git OpenSSL 2) | BINARY | 45 | **0** | 45 | **0** |
| Windows 폴더 | BINARY | 0 | **0** | 0 | **0** |
| Python312 | BINARY | 6 | 6 | 7 | 7 |
| Python312 | EXTENSION | 11 | 11 | 16 | 16 |
| venv | BINARY | 284 | **283**(`qopensslbackend.dll` 제외) | 284 | **283** |
| venv | EXTENSION | 14 | 14 | 14 | 14 |
| venv | DATA | 2,744 | 2,744 | 2,744 | 2,744 |
| 빌드(`<out>/build`) | EXECUTABLE·DATA | 1·2 | 1·2 | 2·2 | 2·2 |
| 스냅숏(datas) | DATA | 12 | 58(licenses 46 추가, D9) | 12 | 58 |
| 합계 | | 3,119 | **3,119** | 3,126 | 3,126 |

- 배포용 합계는 W6 재빌드 3,165(W4 + licenses 46)에서 46을 뺀 3,119다. 빠진 46개는 `api-ms-win-*` 42, `ucrtbase.dll`, `libssl-3-x64.dll`, `libcrypto-3-x64.dll`, `qopensslbackend.dll`이다.
- 앞의 45개는 W4 묶음에서 합계 9,144,048 bytes였고, `qopensslbackend.dll`은 317,752 bytes다.
- `System32\ucrtbase.dll`도 묶이지 않았다. TOC에 Windows 출처가 0건이다.
- CPython용 OpenSSL `libssl-3.dll`·`libcrypto-3.dll`은 그대로 Python312 `DLLs`에서 온다.

## 5. 실행 확인

### 5.1 묶음 검증

`verify_bundle.py`를 스냅숏에서 실행했다. 묶인 실행의 PATH는 `C:\WINDOWS\System32;C:\WINDOWS`이고, `QT_*`·`OPENSSL_*`·`SSL_CERT_*` 변수는 지웠다.

| 실행 | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** `results-verify-ascii\run-20261106-020816-*` (100초) | **통과** `results-verify-korean\run-20261106-020956-*` (101초) |
| 배포용 `--app-only` | **통과** `results-deploy-ascii\run-20261106-021137-*` (69초) | **통과** `results-deploy-korean\run-20261106-021246-*` (68초) |

- **검증용 두 경로**:
  - flow rc=0(16단계).
  - check_kg_screen rc=0이며 [OK] 13·[FAIL] 0이다. V2·렌더링·V1·S1·③ 탭을 확인했고 QtWebEngine 렌더링도 포함한다.
  - 앱 PNG 9장, `licenses_problems` = `[]`.
  - 입력 사본·저장소가 바뀌지 않았다.
  - 앱 로그에 시작과 미처리 예외가 기록되었고, 잘못된 옵션은 rc=2였다.
  - 실행 폴더를 삭제했다.
- **배포용 두 경로**: 앱 PNG 4장, `licenses_problems` = `[]`. 앱 로그·rc=2·저장소 불변을 확인했고 검증 exe는 없다.
- `app_unhandled`가 `timeout`인 것은 W4와 같다. 오류 대화상자 때문에 60초 뒤 강제 종료하며, 판정은 로그 기록으로 한다.
- 판정 범위는 빌드 PC 사용자 PATH에 대한 의존 제거다. 이 PC(Windows 11 Pro 10.0.26200)에서 System32 UCRT와 Schannel로 실행됨을 확인했다. 다른 PC나 다른 Windows 판에서 같다는 보장은 아니다.

### 5.2 TLS·UCRT 측정(재작업 2회차, 사용자 PATH 전체 1회)

- 방법: `packaging/tls_probe.py`를 썼다(검증 전용, 묶음에 넣지 않음, 네트워크 접속 없음). 실행 명령은 아래와 같다.
  ```
  python packaging/tls_probe.py --exe %TEMP%\hazop-w8r2\verify-build\dist\HAZOP-verify\HAZOP-check.exe --path-mode user --out %TEMP%\hazop-w8r2\tls-user.json
  ```
- 측정 과정: 검증용 `HAZOP-check.exe`가 이 스크립트를 묶인 인터프리터로 실행해 다음을 기록한다.
  - `QSslSocket`의 백엔드 목록, 활성 백엔드, `supportsSsl`, 라이브러리 판
  - CPython `ssl` 판
  - `QNetworkAccessManager`로 로컬 파일 읽기
  - `K32EnumProcessModules`로 얻은 **로드 모듈 전체 경로**
- 원본 출력은 §8의 `tls-user.raw.txt`, 판독 결과는 `tls-user.json`이다.

| 항목 | 결과(PATH = 이 PC 사용자 PATH 전체, Git `mingw64\bin`·JDK `bin` 포함 확인) |
|---|---|
| Qt TLS 백엔드(`availableBackends`) | `cert-only`, `schannel` |
| 활성 백엔드·`supportsSsl` | `schannel`, true("Secure Channel, Windows 10.0.26200") |
| CPython `ssl` | OpenSSL 3.0.16(묶음 `_internal\libssl-3.dll`) |
| 로드 모듈 | 72개. **모두 묶음 폴더 또는 `C:\WINDOWS` 아래**이며 Git·JDK 등 다른 출처는 0개 |
| `libssl-3-x64.dll`·`libcrypto-3-x64.dll`·`qopensslbackend.dll` | 로드되지 않음 |
| `ucrtbase.dll` | `C:\WINDOWS\System32\ucrtbase.dll` |
| TLS 플러그인 | `_internal\PySide6\plugins\tls\qschannelbackend.dll`·`qcertonlybackend.dll` |
| `QNetworkAccessManager`로 로컬 파일 읽기 | 성공 |

- 1차에서는 사용자 PATH 전체를 주면 Qt가 Git의 `libssl-3-x64.DLL`을 읽고 `openssl` 백엔드를 활성으로 썼다(§9). TLS 플러그인을 허용 목록으로 제한한 뒤에는 같은 조건에서 읽지 않는다.
- 묶음 검증(§5.1)은 PATH = `System32;Windows`로 실행했다. 그 조건의 TLS 측정은 1회차에 했으며 결과가 같았다(§9).
- 앱은 외부망을 쓰지 않으므로 Schannel 전환의 영향은 없다고 판단한다 [추론: 근거는 D1(배포본에서 anthropic·httpx 제외)과 W4 런타임 netwatch 원격 0건이다. 앱 코드 전체를 TLS 사용 여부로 따로 조사하지는 않았다].

## 6. 테스트

새로 넣은 테스트 사례는 다음과 같다(`BuildSpecTest` D10 절과 `VerifierTest`).

| 테스트 | 확인하는 것 |
|---|---|
| `test_build_path_dirs_and_roots` | PATH 4개, 기본값이 sys.executable·base_prefix·prefix에서 옴, 허용 루트 2개 |
| `test_build_replaces_path` | `os.environ`을 일반 dict로 바꿔 `Path`·`PATH`·`path`가 모두 지워짐, 다른 변수 유지, 로그 기록 |
| `test_spec_drops_openssl_tls_plugin` | spec이 `build_package.drop_binaries`를 두 Analysis의 binaries·datas에 적용, 대소문자·구분자 무관, Schannel·cert-only 유지 |
| `test_tls_plugin_renamed_rejected` | `plugins/tls/renamed.dll`(출처 qopensslbackend), 허용 목록 밖 다른 파일, 다른 위치로 옮긴 qopensslbackend, 출처가 `plugins/tls/`의 다른 이름, DATA로 분류된 qopensslbackend를 spec 필터·TOC 검사 모두 거부. 결과 폴더의 `renamed.dll`도 거부 |
| `test_alias_short_name` | 임시 폴더에 실제 8.3 단축명을 만들어(`GetShortPathNameW`) `libssl-3-x64.dll`·`qopensslbackend.dll` 단축명 출처를 긴 이름으로 판정해 거부. 못 만들면 skip(이 PC에서는 실행됨) |
| `test_alias_junction` | 실제 junction(`mklink /J`)으로 venv 별칭 출처·sys.prefix 별칭을 허용, 이름이 평범한 별칭 폴더 너머 `plugins/tls/renamed.dll`은 거부. 못 만들면 skip(실행됨) |
| `test_foreign_binaries` | Windows 폴더 출처, JDK·Git 출처, 다른 폴더, 이름이 바이너리인 DATA, **이름을 바꾼 DATA(`payload.bin` ← `evil.dll`)**, **상대 경로**, build 밖 EXECUTABLE, 형제 폴더, **SYMLINK 탈출**은 실패. **대소문자가 다른 venv 경로**와 묶음 안 SYMLINK는 통과 |
| `test_forbidden_names` | 허용 루트 출처여도 거부 이름이면 실패(출처 이름만 거부 이름인 경우 포함), 결과 폴더 파일 검사 |
| `test_read_toc_rejects_malformed` | 빈 파일, 파싱 불가, `[]`, `([],)`, 튜플 아님, 원소 2개, 2열, 숫자 열, EXECUTABLE 없음, HAZOP.exe가 BINARY인 경우 |
| `test_check_sources` | TOC 없음, 통과, 위반 건수, 결과 폴더의 제외 플러그인 |
| `test_python_problems` | 통과, 대소문자 무시, 다른 venv, venv 아님, 다른 판, 다른 구현 |
| `test_main_exit_codes` | 위반·빈 TOC·손상 TOC는 rc=3, 정상은 0, 인터프리터 문제는 빌드 전 rc=2, `--allow-other-python`이면 진행 |
| `test_child_env_path_is_system_only` | PATH 한정, `QT_*`·`OPENSSL_*`·`SSL_CERT_*`·`HAZOP_*` 제거, 다른 변수 유지 |

| 실행 | 결과 |
|---|---|
| 전용 venv `-m unittest tests.test_packaging`(작업 트리) | 48건 OK(W6 35, W8-A 13), 건너뜀 없음 |
| 전용 venv 작업 트리 `-m unittest discover -s tests` | **629건 OK(건너뜀 14)**, rc=0. T6 W4 커밋 포함, test_design 실패 없음 |
| 전용 venv 스냅숏 `hazop-w8r2-src` 같은 명령 | **625건 OK(건너뜀 16)**, rc=0. 작업 트리와의 건수 차이는 1차부터 있던 것(스냅숏에 없는 파일·`.git` 의존 건너뜀)이며 이번 변경과 무관하다 [추론: 원인 파일을 하나씩 대조하지는 않음] |

## 7. 한계·남은 일

- 지원 OS는 Windows 10 이상이다. Windows 8.1 이하와 다른 PC에서는 시험하지 않았다.
- 출처 검사는 `COLLECT-00.toc`와 결과 폴더(이름 거부 목록·TLS 허용 목록)만 본다. `PKG-00.toc`(실행 파일 안 항목)는 바이너리를 담지 않아 보지 않았다 [W6 첨부 §5 기준].
- 이름 거부 목록은 알려진 이름(UCRT·OpenSSL `-x64`)만 막는다. 다른 이름의 DLL은 출처 검사로만 막는다. 하드 링크(다른 이름, 같은 파일)는 실경로로 원래 이름을 알 수 없어 이름 판정을 피할 수 있다. 다만 출처 검사(venv·기반 CPython 안)는 그대로 적용된다.
- TLS 플러그인 판정은 `plugins/tls/` 폴더 이름과 파일 이름에 기댄다. 파일 내용(해시)으로는 판정하지 않는다.
- 빌드 네트워크 표본 조사(netwatch)는 하지 않았다. 닫힌 프록시만 지정했다.
- `W8-B`(GPL 전용 Qt 모듈 제외)는 사용자 결정 대기다.

- **총괄 마무리(D11)**: `tls_probe.py` 결함 3건 직접 수정 후 r2 검증용 묶음으로 재측정(사용자 PATH 전체) — rc 0, 모듈 72개, `module_errors` 0, 활성 schannel, `libssl-3-x64` 미로드, 임시 파일 잔존 없음. 남은 한계: 생성 spec이 `scripts/`를 `sys.path` 맨 앞에 넣고 `build_package`를 import한다(현재 이름 충돌 없음, 후속 후보: `spec_from_file_location`).

## 8. 산출물(저장소 밖)

- `%TEMP%\hazop-w8r2\`(재작업 2회차) 아래에 다음이 있다.
  - `verify-build\`·`deploy-build\`: spec·datas.json·build.log·build\·dist\
  - `results-{verify,deploy}-{ascii,korean}\run-*\`, `verify4.json`
  - **TLS 측정**: `tls-user.json`(판독 결과, 로드 모듈 72개 전체 경로 포함), `tls-user.raw.txt`(원본 표준 출력·오류, 종료 코드, 실행 파일, PATH 방식)
  - `ut-tree.txt`·`ut-snap.txt`
- `%TEMP%\hazop-w8r2-src`: 스냅숏이다.
- 이전 회차 산출물도 이름을 붙여 남겼다.
  - 1회차: `hazop-w8r1`·`hazop-w8r1-src`(같은 묶음에 `tls_probe.py`를 미리 시험한 `tls-trial.json` 포함)
  - 1차: `hazop-w8r0`·`hazop-w8r0-src`
  - 시험 빌드: `hazop-w8-pre`·`hazop-w8-pre-src`
- 지울지는 총괄이 판단한다.

## 9. 이전 회차 요약

- 1차는 PATH 통제와 출처 검사만 했다. 허용 루트는 venv·기반 CPython·Windows 폴더였다.
- 배포용 3,120개(592,011,201 bytes), 검증용 3,127개였고 PATH 경유 DLL은 45개에서 0개가 되었다. verify 4회 모두 통과했고, venv 611 OK·스냅숏 603 OK였다.
- TLS 측정(1차 묶음, `qopensslbackend.dll` 포함):
  - PATH가 `System32;Windows`이면 Schannel을 썼다.
  - **사용자 PATH 전체**를 주면 `openssl` 백엔드가 활성이었다("OpenSSL 3.5.6 7 Apr 2026"). 이때 `C:\Program Files\Git\mingw64\bin\libssl-3-x64.DLL`을 읽었다.
- 검토 결과는 Claude·Codex 모두 조건부 승인이었고, 반영 위치는 §2에 있다.
- 재작업 1회차(기준 `a0df5ef`): Qt OpenSSL TLS 플러그인을 묶음 안 이름으로 제외했고, 허용 루트를 venv·기반 CPython으로 줄였으며, 이름 거부 목록·TOC 형식 검사·전용 venv 확인을 넣었다.
  - 배포용 3,119개(591,693,449 bytes), 검증용 3,126개. verify 4회 통과, venv 617 OK·스냅숏 607 OK.
  - 스크래치 스크립트로 TLS를 측정했다. 사용자 PATH 전체와 `System32;Windows` 두 조건 모두 Schannel이었고 `libssl-3-x64`는 로드되지 않았다.
  - 검토 결과는 Codex 반려(이름 바꾸기·별칭 우회 등), Claude 승인이었다.
