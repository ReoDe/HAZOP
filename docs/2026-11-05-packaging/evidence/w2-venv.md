# W2 — 전용 venv 구성 (T2)

> 조사·실행 일시: 2026-11-05 17:50~18:10. 기준 커밋 `b29e5f7`(브랜치 `chore/track-workspaces`). 근거 결정: D1·D2.
> 실행 주체: hazop-developer(Claude Code 데스크톱 앱 안의 Bash).

## 1. 인터프리터: python.org CPython 3.12.10

| 항목 | 내용 |
|---|---|
| 버전 선택 | python.org FTP의 3.12.11~3.12.16 폴더에는 소스(`.tar.xz`·`.tgz`)만 있다. Windows 설치 파일이 있는 마지막 3.12는 **3.12.10**(2025-04-08)이다 |
| 1차 시도: 공식 설치 파일 | `python-3.12.10-amd64.exe`(26,964,224 B). 릴리스 페이지·API는 SHA-256을 주지 않고 MD5만 준다. MD5 `5eddb0b6f12c852725de071ae681dde4` 일치. Authenticode `Valid`, 서명자 `CN=Python Software Foundation`. 참고 SHA-256 `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb` |
| 1차 결과: 실패 | `/quiet InstallAllUsers=0 PrependPath=0 AppendPath=0 Include_launcher=0 InstallLauncherAllUsers=0 AssociateFiles=0 Shortcuts=0 Include_test=0` → 종료 코드 3. core.msi에서 MSI 오류 2203(STG_E_PATHNOTFOUND, `-2147287037`)이 났고 롤백됐다. 샌드박스를 끄고 다시 해도 같았다 |
| 원인(추정) | Claude 데스크톱 앱이 MSIX 패키지로 돌아서 `%LOCALAPPDATA%` 쓰기가 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\`로 리디렉션된다(§2에서 venv로 확인). 설치 파일이 `Package Cache`에 내려놓은 core.msi를 Windows Installer 서비스는 실제 경로에서 찾지 못한 것으로 본다[추론]. 남은 캐시 폴더(`Package Cache\*v3.12.10150.0`)는 지웠다. PATH(HKCU `Environment`)는 바뀌지 않았다 |
| 2차: Python install manager | 이미 설치된 python.org Python install manager 26.4로 `py install --download=<scratchpad>\pymgr-dl 3.12`. 매니저가 `index-windows.json` 서명을 검증했다. 받은 `pythoncore-3.12-64-3.12.10.zip`(= python.org `3.12.10/python-3.12.10-amd64.zip`)의 SHA-256 `8649692de846c56a7189d6dae5c322ab20deb1b5908b6f39426b62a36f39415d`를 python.org `index-windows.json`의 값과 따로 대조했고 **일치**했다 |
| 설치 | `py install --source=<pymgr-dl>\index.json --target=%LOCALAPPDATA%\Programs\Python\Python312 3.12`. `--target`은 압축만 푼다. 설치 뒤 `python.exe` Authenticode `Valid` |
| 기존 환경 영향 | `py -0p`(3.14·3.11), HKCU `Software\Python\PythonCore`(3.11·3.14), `%LOCALAPPDATA%\Python\bin` 별칭 목록, `python` = LibreOffice 3.12.14 모두 그대로 |

## 2. venv

- 명령: `Python312\python.exe -I -m venv %LOCALAPPDATA%\HAZOP\venv-py312`. pip 25.0.1이 함께 설치됐다. `sys.flags.no_user_site=1`이므로 사용자 site-packages(`%APPDATA%\Python\Python312`)가 섞이지 않는다.
- venv가 만들 때 "Actual location: `C:\Users\kim92\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\HAZOP\venv-py312`"라고 경고했다. 즉 venv는 Claude 앱의 MSIX 전용 위치에 있다. Claude 앱 안에서는 `%LOCALAPPDATA%\HAZOP\venv-py312`로 보이지만 일반 터미널에서는 그 경로에 없을 수 있다[추론, 앱 밖 미확인]. 기반 인터프리터(`Programs\Python\Python312`)는 install manager 프로세스가 썼고 Claude `LocalCache`에 없으므로 실제 경로에 있다고 본다.
- 설치(`pip install -r packaging/requirements-build.txt`, 종료 코드 0). `pip freeze`:
  `PySide6==6.12.0`, `PySide6_Essentials==6.12.0`, `PySide6_Addons==6.12.0`, `PySide6_WebEngine==6.12.0.140`, `PySide6_Pdf==6.12.0.140`, `shiboken6==6.12.0`, `networkx==3.7`, `openpyxl==3.1.5`, `et_xmlfile==2.0.0`, `pyinstaller==6.22.3`, `pyinstaller-hooks-contrib==2026.9`, `altgraph==0.17.5`, `pefile==2024.8.26`, `pywin32-ctypes==0.2.3`, `packaging==26.3`, `setuptools==84.2.1`.
- pyinstaller는 PyPI의 6.22 계열 최신 패치 6.22.3으로 고정했다(`pip index versions`: 6.22.3이 최신). anthropic·httpx는 설치하지 않았다.

## 3. 검증 결과 (venv `python.exe`, 저장소 루트, `PYTHONIOENCODING` 미설정)

| 검사 | 결과 |
|---|---|
| `python -m unittest discover -s tests` | 465건 실행, **실패 2·오류 3**(85 s) |
| `scripts/check_app.py` | 종료 0, `[OK]` 10줄, "결과: 전부 통과" |
| `scripts/check_kg_screen.py` | 종료 0, `[OK]` 14줄, "결과: 통과"(V1·V2·S1 포함) |

## 4. 실패 원인 분류

5건 모두 `tests/test_analysis.py`이고 원인은 하나다: **anthropic 미설치**(D1에 따른 의도된 제외). 실제 API 호출은 없다. 테스트는 가짜 클라이언트(`types.SimpleNamespace`)를 넣지만 `hazop/analysis/ai.py` `AnthropicClient.infer`가 223행에서 `import anthropic`을 먼저 실행한다.

| 테스트 | 증상 |
|---|---|
| `AnthropicClientTest.test_request_shape` | ERROR `ModuleNotFoundError: anthropic` |
| `AnthropicClientTest.test_stop_reasons_and_parse` | ERROR 같음 |
| `AnthropicClientTest.test_sdk_errors` | ERROR 같음(테스트 자체가 anthropic·httpx 예외를 만든다) |
| `AnthropicClientTest.test_refusal_keeps_candidates_and_exploration` | FAIL `'client_error' != 'refused'`(import 실패가 client_error로 기록됨) |
| `MergeAndModelTest.test_response_model_mismatch_allowed_by_user_decision_with_warning` | FAIL 응답 모델이 None(같은 이유) |

- 대조: LibreOffice Python(anthropic 0.102.0 있음)으로 `tests.test_analysis`만 돌리면 `OK`.
- LibreOffice Python 의존 때문에 난 실패는 **0건**이다.
- (총괄 후속, 2026-11-05) (나)로 처리했다(D3): SDK를 import하는 테스트 메서드 4개와 모델 불일치 테스트 1개에 `skipUnless(HAS_ANTHROPIC)`. 재실행 결과 venv 전체 478건 OK·건너뜀 5, LibreOffice Python은 건너뜀 없이 통과. 아래는 처리 전 1차 기록이다.
- PROGRESS W2 완료 기준("venv에서 전체 테스트 통과")은 처리 전에는 이 5건 때문에 충족되지 않았다. 해소 방법은 결정이 필요하다: (가) 개발·테스트용으로 anthropic·httpx를 별도 venv나 requirements 파일에 둔다, (나) 테스트가 anthropic이 없으면 건너뛰게 한다, (다) `ai.py`의 import 위치를 바꾼다(편집 허용 범위 밖).

## 5. 주의·미확인

- 실행 중 다른 트랙의 미추적 파일(`tests/test_adapter.py`, `tests/test_design.py` 등)이 작업 트리에 있었다. 465건에는 그 시점에 있던 테스트가 포함됐을 수 있다.
- 3.12.10과 LibreOffice 3.12.14는 패치 버전이 다르다. 이번 테스트에서 차이로 인한 실패는 없었다.
- 일반 터미널(앱 밖)에서 venv 경로가 보이는지는 확인하지 못했다.
