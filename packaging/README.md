# packaging — 전용 venv와 빌드 준비 (T2)

근거: [`docs/2026-11-05-packaging/decisions.md`](../docs/2026-11-05-packaging/decisions.md) D1·D2, 검증 기록은 [`evidence/w2-venv.md`](../docs/2026-11-05-packaging/evidence/w2-venv.md).

## 파일

| 파일 | 용도 |
|---|---|
| `requirements.txt` | 배포 런타임 3종(버전 고정): PySide6 6.12.0, networkx 3.7, openpyxl 3.1.5 |
| `requirements-build.txt` | 런타임 + pyinstaller 6.22.3 |
| `requirements-pdf.txt` | PDF 어댑터 8종(pdfplumber 0.11.9와 의존성, 휠 sha256 고정). `pip install --require-hashes --no-deps --only-binary=:all: -r`(T2 D15) |
| `pdf_probe.py` | 묶인 실행(`HAZOP-check.exe`)에서 PDF 어댑터 추출·pypdfium2 렌더링 확인(verify 단계 3b, 검증 전용) |
| `rthook_applog.py` | `HAZOP.exe` 런타임 훅: 묶인 실행 로그를 `<작업 루트>/logs/app.log`에 남김(D7안) |
| `rthook_verify_build.py` | 검증용 빌드(`--with-check`)의 `HAZOP.exe`에만 넣는 런타임 훅: 시험 트리거 표지(`sys._hazop_verify_build`). 배포용에는 없음(T2 D18) |
| `check_entry.py` | 검증 전용 `HAZOP-check.exe` 입구(`scripts/build_package.py --with-check`). 배포본에 넣지 않는다 |
| `w4_flow.py` | 묶인 실행에서 ①~⑤ 함수 흐름·자원 읽기 위치·음성 검사(`HAZOP-check.exe`로 실행) |
| `verify_bundle.py` | 묶음을 저장소 밖 경로에 복사해 ①~⑤·③ V1·V2·S1·스크린샷(② 편집 모드, 레일 단계 ①~⑥)·앱 로그 확인. 배포용은 `--app-only` |
| `lock_probe.py` | 빌드한 `HAZOP.exe`를 두 번 띄워 두 번째가 잠금 안내를 띄우고 종료 코드 3으로 끝나는지 확인. 실제 창을 띄우므로 `scripts/desktop_lease.py run` 안에서 돌린다 |
| `다른PC-점검표.md` | 다른 PC·Windows 10에서 배포본을 사람이 확인하는 절차와 결과 표 |
| `make_snapshot.py` | 저장소 밖 빌드용 스냅숏(다른 트랙 진행 중 파일은 HEAD로), `SNAPSHOT.json` 해시 목록 |
| `netwatch.ps1` | 빌드 중 네트워크 연결 표본 조사(관찰만) |
| `tls_probe.py` | D10 측정(검증 전용): 검증용 묶음의 `HAZOP-check.exe`로 Qt TLS 백엔드와 로드된 모듈 목록을 기록(`--path-mode user|system`). 네트워크 접속 없음 |

빌드: `<venv python> scripts/build_package.py --out <저장소 밖 폴더> [--with-check] --build` → 배포용 `<out>/dist/HAZOP/`(검증 exe 없음을 빌드 뒤 검사), 검증용 `<out>/dist/HAZOP-verify/`. 출력 폴더가 저장소 안이면 거부한다. 절차·결과는 [W4 빌드](../docs/2026-11-05-packaging/evidence/w4-build.md).
D10([W8 경로 통제](../docs/2026-11-05-packaging/evidence/w8-path-control.md)) 기준은 다음과 같다.

- `--build`는 전용 venv에서만 한다. 다른 인터프리터면 rc=2로 중단하며 `--allow-other-python`으로만 우회한다. 기반 CPython 판(3.12.10)은 `scripts/build_package.py`의 `PYTHON_VERSION`에 고정되어 있으니, 패치 판을 올릴 때 함께 바꾼다.
- PyInstaller는 PATH를 venv `Scripts`·기반 CPython·`DLLs`·`System32`로만 두고 실행한다.
- Qt TLS 플러그인은 허용 목록(`qschannelbackend`·`qcertonlybackend`)만 묶는다. OpenSSL 백엔드(`qopensslbackend.dll`)는 묶음 안 이름과 출처 실경로의 긴 파일명 양쪽으로 걸러 빼고, Schannel을 쓴다.
- 빌드 뒤 묶음 바이너리 출처가 venv·기반 CPython 밖이거나, 이름 거부 목록(`ucrtbase`·`api-ms-win-*`·`lib(ssl|crypto)-3-x64`)에 걸리면 rc=3으로 실패한다.
- **지원 OS: Windows 10 이상(64비트).** UCRT를 묶지 않고 시스템 구성요소를 쓰므로 Windows 8.1 이하는 지원하지 않는다.

anthropic·httpx는 넣지 않는다(D1: 배포본에서 제외). SDK가 필요한 테스트 5건(`tests/test_analysis.py`)은 anthropic이 없으면 건너뛴다(T2 decisions D3). venv 전체 테스트: 478건 OK, 건너뜀 5.

## 경로

| 항목 | 경로 |
|---|---|
| 기반 인터프리터 | `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` (python.org CPython 3.12.10, 등록·PATH 변경 없음) |
| venv | `%USERPROFILE%\.hazop\venv-py312` (저장소 밖, Claude 앱 가상화 경로 밖 — T2 D4) |

## venv 만들기 (PowerShell)

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv "$env:USERPROFILE\.hazop\venv-py312"
$py = "$env:USERPROFILE\.hazop\venv-py312\Scripts\python.exe"
& $py -m pip install -r packaging\requirements-build.txt   # 런타임만이면 requirements.txt
& $py -m pip install --require-hashes --no-deps --only-binary=:all: -r packaging\requirements-pdf.txt   # PDF 어댑터(T2 D15)
& $py -m unittest discover -s tests                         # 저장소 루트에서
```

## 주의

- 저장소 루트에서 `python`은 LibreOffice 내장 Python 3.12.14다. venv의 `python.exe`를 경로로 직접 지정한다.
- python.org는 3.12.11부터 Windows 설치 파일을 내지 않는다. 그래서 Windows 바이너리가 있는 마지막 판인 3.12.10을 쓴다(LibreOffice는 3.12.14).
- 기반 인터프리터는 Python install manager로 `py install --target=<위 경로> 3.12` 방식으로 풀었다. `py -0p` 목록과 `python3.12` 별칭에는 나타나지 않는다.
- Claude 데스크톱 앱(MSIX) 안에서 만든 venv는 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\HAZOP\venv-py312`로 리디렉션된다. 그래서 venv는 `%USERPROFILE%\.hazop\venv-py312`에 둔다(2026-11-05 재생성, 전체 테스트 489 OK·건너뜀 5). 앱 안에서 처음 만든 리디렉션 위치의 venv는 쓰지 않는다.
- 시험·검사·빌드는 `PYTHONIOENCODING=utf-8`을 붙여 돌린다(`CLAUDE.md` 규칙 11). venv를 옮겼으면 환경변수 `HAZOP_VENV`에 새 경로를 둔다(`scripts/build_package.py` `VENV_DIR`).
