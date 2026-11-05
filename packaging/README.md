# packaging — 전용 venv와 빌드 준비 (T2)

근거: [`docs/2026-11-05-packaging/decisions.md`](../docs/2026-11-05-packaging/decisions.md) D1·D2, 검증 기록은 [`evidence/w2-venv.md`](../docs/2026-11-05-packaging/evidence/w2-venv.md).

## 파일

| 파일 | 용도 |
|---|---|
| `requirements.txt` | 배포 런타임 3종(버전 고정): PySide6 6.12.0, networkx 3.7, openpyxl 3.1.5 |
| `requirements-build.txt` | 런타임 + pyinstaller 6.22.3 |

anthropic·httpx는 넣지 않는다(D1: 배포본에서 제외). SDK가 필요한 테스트 5건(`tests/test_analysis.py`)은 anthropic이 없으면 건너뛴다(T2 decisions D3). venv 전체 테스트: 478건 OK, 건너뜀 5.

## 경로

| 항목 | 경로 |
|---|---|
| 기반 인터프리터 | `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` (python.org CPython 3.12.10, 등록·PATH 변경 없음) |
| venv | `%LOCALAPPDATA%\HAZOP\venv-py312` (저장소 밖) |

## venv 만들기 (PowerShell)

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv "$env:LOCALAPPDATA\HAZOP\venv-py312"
$py = "$env:LOCALAPPDATA\HAZOP\venv-py312\Scripts\python.exe"
& $py -m pip install -r packaging\requirements-build.txt   # 런타임만이면 requirements.txt
& $py -m unittest discover -s tests                         # 저장소 루트에서
```

## 주의

- 저장소 루트에서 `python`은 LibreOffice 내장 Python 3.12.14다. venv의 `python.exe`를 경로로 직접 지정한다.
- python.org는 3.12.11부터 Windows 설치 파일을 내지 않는다. 그래서 Windows 바이너리가 있는 마지막 판인 3.12.10을 쓴다(LibreOffice는 3.12.14).
- 기반 인터프리터는 Python install manager로 `py install --target=<위 경로> 3.12` 방식으로 풀었다. `py -0p` 목록과 `python3.12` 별칭에는 나타나지 않는다.
- Claude 데스크톱 앱(MSIX) 안에서 만든 venv는 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\HAZOP\venv-py312`로 리디렉션된다. 일반 터미널에서 쓰려면 위 명령으로 다시 만든다.
- `PYTHONIOENCODING`은 설정하지 않는다.
