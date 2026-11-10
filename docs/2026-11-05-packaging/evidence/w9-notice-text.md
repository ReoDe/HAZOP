# W9 — 라이선스 고지 원문 동봉, pdfplumber 포함, 고지를 실행 파일 옆으로 (T2)

> 1차 2026-11-06 10:05~10:45, **재작업 1회차 10:45~11:10**(§10). 기준 HEAD `cd3194d` + W9 미커밋 변경. 실행 주체: hazop-developer.
> §1~§8은 1차 기록이다. 재작업 1회차의 추가 원문·변경·빌드·verify·테스트 수치는 §10이 현재 값이다.
> **W9-B(2026-11-06 11:15~11:40, D17)**: VS 2022 사용 조건 .docx, cryptography 안 OpenSSL·Rust 크레이트 원문은 §11이다. §7의 해당 한계 2건은 §11로 해소했다. 빌드·verify 수치는 W10과 함께 [w10-정보창.md](w10-정보창.md) §4에 있다.
> 근거 결정: D15(사용자 결정 2026-11-06 — `메모리/결정로그.md` 마지막 8행 중 고지 원문 동봉·VC++ 런타임 포함·고지 위치·pdfplumber 포함).
> 비교 기준: W8-B 재작업 2회차 묶음(`%TEMP%\hazop-w8b3`, [W8-B 모듈 제외](w8b-모듈제외.md) §4).

## 1. 내려받기·설치(사용자 승인 목록 A·B)

받은 파일은 저장소 밖 새 폴더 `%TEMP%\hazop-w9-dl\`에 먼저 받았다. HTTP 상태·형식·앞부분 내용(로그인·오류 페이지가 아닌지)을 확인한 뒤 `licenses/`로 바이트 그대로 복사했다. 파일별 출처 URL·받은 날짜·크기·SHA-256은 [`licenses/README.md`](../../../licenses/README.md) "내려받은 원문(W9)" 표에 있다(52개 받음, 1개 받지 못함).

### 1.1 A. 라이선스 원문

| 항목 | 결과 |
|---|---|
| VC++ 재배포 안내(Microsoft Learn) | 받음(HTML 62,616 bytes). "Visual C++ Runtime Files" 절에 재배포할 수 있는 파일 범위와 "Subject to the License Terms for the software"가 있다 |
| VS 2022 Professional·Enterprise 사용 조건 | **받지 못함**. 페이지(236,577 bytes)에 본문이 없다. 본문은 `Visual-Studio-2022-Enterprise-Professional-License-EN.docx`를 Office 뷰어로 끼워 보여 준다. .docx는 승인 범위(텍스트·HTML) 밖이라 받지 않았다. 받은 페이지는 `licenses/`에 넣지 않았다 |
| liblzma(xz v5.2.5 `COPYING`) | 받음 |
| Qt LGPL-3.0·GPL-3.0·GPL-2.0(qtbase `v6.12.0`) | 받음. 기존 `qt/LGPL-3.0.txt`·`qt/GPL-3.0.txt`(Git for Windows 사본)를 같은 이름으로 덮어썼고, `qt/GPL-2.0.txt`를 추가했다. 해시가 바뀌었다(이전 사본과 다른 판) |
| Qt 내부 제3자(qtbase `LICENSES/` SPDX 본문 16개, `qt_attribution.json` 23개, qtimageformats libtiff·libwebp `qt_attribution.json` 2개와 원문 2개) | 받음. 고른 기준은 §2 |
| PDFium(qtwebengine-chromium `140-based`) | 받음. 받은 시점 브랜치 커밋 `8535a56a09b59838a92dc4d9eb57f434a324c3b2`(`git ls-remote`) |
| Qt WebEngine 6.140 제3자 목록 | 받음(HTML 44,810 bytes, 제목 "Qt WebEngine Licensing \| Qt WebEngine 6.140.0") |
| Mesa 11.2.2 `docs/license.html`, LLVM 3.6.0 `LICENSE.TXT` | 받음. `opengl32sw.dll` 안 문자열은 `Mesa 11.2.2`·`LLVM 3.6.2`다. LLVM은 승인 목록의 3.6.0 태그 파일이다(3.6.2와 같은지 미대조) |

목록 밖이거나 목록 해석이 필요했던 조회(모두 메타데이터·목록이며 `licenses/`에 넣지 않음):

- qtbase `LICENSES` 트리 페이지(`.../tree/LICENSES?h=v6.12.0`, 24,462 bytes): 승인 목록의 URL이며, `LICENSES/<이름>` 목록을 알기 위해 받았다.
- qtbase `src/3rdparty` 트리 페이지(`.../tree/src/3rdparty?h=v6.12.0`, 22,766 bytes)와 qtimageformats `src/3rdparty` 트리 페이지(8,078 bytes): 승인 목록의 `src/3rdparty/*/`의 `*`를 알기 위해 받았다.
- `qt_attribution.json` 조회 가운데 forkfd·pixman·sqlite는 받았으나 넣지 않았다(§2). iaccessible2·dbus-ifaces는 HTTP 404(파일 없음)였다.
- `git ls-remote`: qtwebengine-chromium `refs/heads/140-based`, qtbase·qtimageformats `refs/tags/v6.12.0*`(커밋 기록용).
- PyPI JSON 8개(B의 해시 조회, 승인 목록 B).

### 1.2 B. pdfplumber 설치

- `packaging/requirements-pdf.txt`: 8개 패키지마다 PyPI JSON에서 고른 휠 하나의 sha256 전체를 `--hash=sha256:`로 적었다.
- **휠 태그 해석**: cryptography 48.0.0에는 cp312 전용 휠이 없다. CPython 3.12 x64에 설치할 수 있는 휠은 `cp311-abi3-win_amd64`와 `cp39-abi3-win_amd64` 두 가지이고, pip가 cp312에서 먼저 고르는(더 높은 abi3 기준) `cp311-abi3-win_amd64`를 골랐다. pypdfium2 5.8.0의 Windows x64 휠은 `py3-none-win_amd64`뿐이다. 작업지시서의 "cp312 win_amd64 또는 py3-none-any"와 글자가 다르므로 기록한다. charset-normalizer는 `cp312-cp312-win_amd64`와 `py3-none-any`가 모두 있어 앞의 것을 골랐다.
- 명령: `<venv python> -m pip install --require-hashes --no-deps --only-binary=:all: --no-cache-dir -r packaging/requirements-pdf.txt` → 8개 설치, 다른 패키지는 끌려오지 않았다. `pip check` "No broken requirements found."
- `pip freeze --all` 차이(설치 전 → 뒤): `+cffi==2.0.0 +charset-normalizer==3.4.7 +cryptography==48.0.0 +pdfminer.six==20251230 +pdfplumber==0.11.9 +pillow==12.2.0 +pycparser==3.0 +pypdfium2==5.8.0`. 다른 줄 변화 없음(원본: `%TEMP%\hazop-w9-dl\pip\freeze-{before,after}.txt`).
- 설치본 대조: 8개 패키지의 RECORD 해시가 있는 파일 598개가 모두 일치했다(불일치 0).
- 휠 동봉 고지: Pillow `LICENSE`, pdfplumber·pdfminer.six·charset-normalizer·pycparser `LICENSE`, cryptography `LICENSE`·`LICENSE.APACHE`·`LICENSE.BSD`, cffi `LICENSE`·`AUTHORS`, pypdfium2 `LICENSES/` 3개와 `data/windows_x64/BUILD_LICENSES/` 16개를 `licenses/python/`에 복사했다. cryptography의 `sboms/`는 1차에서 넣지 않았고, 재작업 1회차에서 `licenses/python/cryptography-sboms/`에 넣었다(§10).

## 2. Qt 내부 제3자 구성요소 선택

Qt 6.12.0 qtbase `src/3rdparty/`의 `qt_attribution.json`에 적힌 사용처(QtUsage)와 묶음 DLL 문자열로 골랐다.

| 판정 | 구성요소 | 근거 |
|---|---|---|
| 넣음 | D3D12MemoryAllocator·VulkanMemoryAllocator(QRhi), blake2·md4·md5·rfc6234·sha1·sha3·siphash(Qt Core 해시), double-conversion·easing·tinycbor·pcre2·zlib(Qt Core), emoji-segmenter·freetype·harfbuzz-ng·icc·md4c(Qt Gui), libpsl(Qt Network), libjpeg(qjpeg), libpng(Qt Gui), wintab(windows 플랫폼 플러그인), qtimageformats libtiff(qtiff)·libwebp(qwebp) | QtUsage가 묶음에 있는 모듈·플러그인을 가리킨다. 문자열 확인(일부): `Qt6Gui.dll`에 FreeType·harfbuzz·libpng·D3D12·sRGB2014·markdown, `Qt6Core.dll`에 PCRE2·BLAKE2, `qwindows.dll`에 wintab, `qjpeg.dll`에 libjpeg-turbo, `qtiff.dll`에 LibTIFF, `qwebp.dll`에 WebP |
| 뺌 | forkfd | "Used on most Unix platforms" |
| 뺌 | pixman | "Used in Qt GUI on ARM NEON" |
| 뺌 | sqlite | Qt SQLite 플러그인(`sqldrivers`)이 묶음에 없다 |

- 문자열 확인은 보조 근거다. 해시 구현(md4·md5·sha1 등)처럼 문자열이 남지 않는 구성요소는 QtUsage만으로 넣었다 [추론].
- 받지 않은 것: Qt Declarative·Svg·Multimedia·3D·Location 등 qtbase·qtimageformats 밖 Qt 저장소의 제3자 구성요소(승인 목록 밖).

## 3. 변경

| 파일 | 변경 |
|---|---|
| `scripts/build_package.py` | `DATA_DIRS`에서 `licenses` 제거. `EXCLUDES`에서 `pdfplumber` 제거, hiddenimports에 `pdfplumber`·`pypdfium2`(두 Analysis). 빌드 뒤 `finish_bundle`: `copy_licenses`(결과 폴더의 실행 파일 옆 `licenses/`로 복사) → `licenses_problems`(저장소와 파일 목록·SHA-256 같음, `_internal/licenses/` 없음) → `pdf_problems`(앱 PYZ `PYZ-00.toc`에 `pdfplumber`·`pdfminer`·`pypdfium2`·`pypdfium2_raw`·`PIL.Image`·`charset_normalizer`·`cryptography`, 결과 폴더에 `_internal/pypdfium2_raw/pdfium.dll`). 하나라도 걸리면 rc=3. 바이너리 검사(D10·D13)는 그 뒤 고지 사본이 있는 결과 폴더 전체로 돈다 |
| `packaging/verify_bundle.py` | `licenses_problems`가 `build_package.licenses_problems`를 쓴다(실행 파일 옆). 단계 3b: 검증용은 `HAZOP-check.exe pdf_probe.py`로 샘플 PDF 사본(`SNP-M-102`, 가상 샘플)을 추출·렌더링하고, 결과 요약이 전용 venv에서 같은 파일을 추출한 결과와 같은지, 모듈 7개와 `pdfium.dll`이 묶음 안에서 읽혔는지 본다. 배포용(`--app-only`)은 `pdfium.dll`이 있는지만 본다. 판정에 `pdf_problems`를 더했다 |
| `packaging/pdf_probe.py`(신규) | 묶인 실행용 PDF 확인 스크립트(결과 JSON, 판정은 verify_bundle) |
| `packaging/requirements-pdf.txt`(신규) | §1.2 |
| `packaging/README.md` | 파일 표에 두 파일 추가 |
| `tests/test_packaging.py` | §6 |
| `licenses/` | 원문 79개 추가, 2개 교체, `README.md`(머리말·Qt LGPL·GPL 행 출처·W9 행 79개·내려받은 원문 표·주8~주13), `qt/QT-SOURCE.md`·`qt/QTWEBENGINE-THIRD-PARTY.md`(원문 위치 문장) |

`hazop/`는 바꾸지 않았다(앱 정보 창 안내는 W10).

## 4. 스냅숏·빌드

- 스냅숏 `%TEMP%\hazop-w9-src`: HEAD `cd3194d`, 484개(disk 403·overlay 81), 목록 해시 `924dcb69d36cd0f5bed52fa90b0cce25e1a7b8042354180f18e646984bb12dd7`. 진행 중인 다른 트랙 파일은 없었다(`--restore-head` 없음).
- 첫 시도는 무효로 처리하고 지웠다. `--overlay`를 파일마다 따로 줘서 마지막 하나만 들어갔기 때문이다(`nargs="*"`). 그 빌드는 새 고지 파일 없이 서로 맞는 상태로 통과했으므로 결과로 쓰지 않았다.
- 실행기(Python, 종료 코드 직접 받음), 닫힌 포트 프록시 `127.0.0.1:9`, `PIP_NO_INDEX=1`, PATH 통제(D10).

| 빌드 | 결과 | 경고 | 결과 폴더 |
|---|---|---|---|
| 검증용 `--with-check` | **rc=0**, 97.7초. 결과 폴더·고지·PDF·바이너리 검사 통과 | WARNING 2(W8-B와 같은 `qmlassetdownloaderprivateplugin.dll`) | `dist\HAZOP-verify\` 2,503개, 601,492,043 bytes(573.6 MiB) |
| 배포용 | **rc=0**, 68.5초. 네 검사 통과 | WARNING 1(같은 경고) | `dist\HAZOP\` **2,502개, 594,669,767 bytes(567.1 MiB)** |

### 4.1 새 바이너리와 D10·W8-B 검사

배포용 COLLECT TOC의 새 바이너리와 출처(모두 venv 또는 기반 CPython `DLLs`):

- venv: `pypdfium2_raw\pdfium.dll`(BINARY), `cryptography\hazmat\bindings\_rust.pyd`, `_cffi_backend.cp312-win_amd64.pyd`, `PIL\_imaging`·`_imagingcms`·`_imagingft`·`_imagingmath`·`_imagingtk`·`_webp`·`_avif` `.pyd` 7개, `charset_normalizer\cd`·`md` `.pyd`, `81d243bd2c585b0f4821__mypyc.cp312-win_amd64.pyd`(charset-normalizer)
- 기반 CPython `DLLs`: `_ctypes.pyd`·`libffi-8.dll`(pypdfium2가 ctypes 사용), `_asyncio`·`_overlapped`·`_multiprocessing`·`_uuid`·`_wmi` `.pyd`

D10 출처·이름 거부 검사와 W8-B 제외 모듈 검사(이름·폴더 규칙, TOC와 결과 폴더 전체)는 두 빌드 모두 0건이었다. `tkinter`는 PYZ에 0개다(`_imagingtk.pyd`만 들어옴). `cffi`·`pycparser`의 Python 모듈은 PYZ에 없다(`_cffi_backend`만 cryptography가 씀). 그래도 두 휠의 고지는 설치 목록에 맞춰 넣었다.

### 4.2 크기 변화(배포용, W8-B 대비)

| | W8-B | **W9** | 차이 |
|---|---|---|---|
| 배포용 | 2,234개, 553,023,605 bytes(527.4 MiB) | **2,502개, 594,669,767 bytes(567.1 MiB)** | +268개, +41,646,162 bytes(+39.7 MiB, +7.5%) |
| 검증용 | 2,241개, 558,992,308 bytes(533.1 MiB) | 2,503개, 601,492,043 bytes(573.6 MiB) | +262개, +42,499,735 bytes |

배포용 차이 내역(추가 314개 +40,036,489 bytes, 삭제 46개 −250,209 bytes, 크기 변경 2개 +1,859,882 bytes):

| 항목 | 파일 | bytes |
|---|---|---|
| `_internal/PIL/` | 7 | 13,368,320 |
| `_internal/cryptography/`(+dist-info 10개 81,913) | 1 | 9,903,104 |
| `_internal/pdfminer/`(cmap 등, +dist-info 7개 24,187) | 150 | 7,889,230 |
| `_internal/pypdfium2_raw/` | 2 | 7,178,383 |
| 실행 파일 옆 `licenses/` | 125 | 765,896 |
| `_internal/licenses/`(삭제) | −46 | −250,209 |
| CPython 확장(`_ctypes`·`libffi-8`·`_asyncio`·`_overlapped`·`_wmi`·`_multiprocessing`·`_uuid`) | 7 | 403,408 |
| charset-normalizer(`.pyd` 2 + mypyc 1), `_cffi_backend`, `pypdfium2/`(version.json) | 5 | 422,048 |
| 크기 변경: `HAZOP.exe`(PYZ에 PDF 모듈), `hazop/viewer/template.html`(T6 W8 커밋 `add9f98` 반영) | 2 | +1,859,882 |

## 5. 실행 확인

`verify_bundle.py`를 스냅숏에서 Python 실행기로 4회 실행했다(조건은 W8-B와 같음).

| 실행 | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** rc=0 `results-verify-ascii\run-20261106-102920-w9rpmd1i` | **통과** rc=0 `results-verify-korean\run-20261106-103103-qwe922zl` |
| 배포용 `--app-only` | **통과** rc=0 `results-deploy-ascii\run-20261106-103244-fxwsne80` | **통과** rc=0 `results-deploy-korean\run-20261106-103301-fqvilw4h` |

- 검증용 두 경로: `w4_flow` rc=0(16단계, ①~⑤), check_kg_screen rc=0([OK] 13·[FAIL] 0), **pdf_probe rc=0·`pdf_problems` = `[]`**(추출 `extract-pdf-SNP-M-102-p0-pdf-vector-rules-0.3.0-401c4822849a`, 노드 19·관계 20·blocker 0, 개발 실행과 같음, pypdfium2 렌더링 298×211, 모듈 7개와 `pdfium.dll` 모두 `…\HAZOP\_internal\` 아래), 앱 PNG 9장, `licenses_problems` = `[]`, 저장소 불변, 앱 로그·잘못된 옵션 rc=2.
- 배포용 두 경로: 앱 PNG 4장, `licenses_problems` = `[]`(실행 파일 옆), `pdf_problems` = `[]`, 앱 로그·rc=2·저장소 불변.
- 첫 4회 실행은 C 드라이브 공간 부족(`WinError 112`)으로 복사 단계에서 실패했다(`*.diskfull.out`). 무효 처리한 첫 빌드 폴더(§4)를 지운 뒤 다시 실행했다.

## 6. 테스트

| 테스트 | 확인하는 것 |
|---|---|
| `BuildSpecTest.test_spec_text`(수정) | `EXCLUDES = ['anthropic', 'httpx']`, PDF hiddenimports가 Analysis마다 있음 |
| `LicenseNoticeTest.test_licenses_copied_next_to_exe`(기존 `test_spec_includes_licenses` 대체) | `licenses`가 datas·spec DATAS에 없고, `copy_licenses`가 실행 파일 옆에 고지 목록과 같은 파일을 만들며, `_internal/licenses/`가 있으면 실패 |
| `REQUIRED_NOTICES`(확장) | W9 원문 79개의 경로·라이선스 식별자. 표 행과 파일을 함께 지워도 실패 |
| `test_notice_versions_match_pins`(확장) | PDF 휠 8개의 고지 버전 = `requirements-pdf.txt` 고정 |
| `BundleLicensesTest`(수정) | verify의 대조가 실행 파일 옆 기준이고 `_internal/licenses/`만 있으면 실패 |
| `PdfBundleTest`(신규 5건) | requirements-pdf 8개·휠 해시 1개씩, `pdf_problems`(모듈 없음·dll 없음·TOC 없음), `finish_bundle`(결과 폴더 없음·복사 실패), `pdf_probe_problems`(오류·비묶음·요약 불일치·크기·묶음 밖 모듈), 개발 venv에서 `pdf_probe` 실행(pdfplumber 있을 때) |
| D10·D13 main 모의 테스트 3곳 | `finish_bundle`을 대역으로 바꿈(빌드 뒤 마무리는 위에서 따로 시험) |

| 실행 | 결과 |
|---|---|
| 전용 venv `-m unittest tests.test_packaging` | **60건 OK**(W8-B 55 + 5) |
| 전용 venv `-m unittest discover -s tests` | **686건 OK(건너뜀 5)**, rc=0. W8-B(681건, 건너뜀 14) 대비 이번 추가 5건, pdfplumber 설치로 건너뜀에서 실행으로 바뀐 PDF 테스트 9건 |
| 전용 venv `scripts/check_adapter.py` | rc=0, `[통과] W3 PDF`, "전부 통과"(pdfplumber 설치로 W3 단계 실행) |

## 7. 한계·남은 일

- **VS 2022 사용 조건 본문 없음**: .docx라 받지 못했다. VC++ 런타임 재배포 조건은 안내 페이지만 있다. 승인 범위를 넓힐지(.docx 받기 또는 PDF 등) 사용자 판단이 필요하다.
- 휠 태그(§1.2): cryptography·pypdfium2는 작업지시서 문구와 다른 태그의 휠이다.
- PDFium 원문은 받은 시점의 브랜치 머리이며, 휠을 만든 커밋과의 일치는 확인하지 않았다. LLVM 원문은 3.6.0 태그(DLL은 3.6.2).
- liblzma 판(5.2.5)은 `_lzma.pyd`에서 확인하지 못했다(승인 목록의 판).
- Qt 제3자 선택은 QtUsage와 문자열 보조 근거다(§2). qtbase·qtimageformats 밖 Qt 저장소의 제3자 구성요소(Declarative·Svg·Multimedia·3D 등)는 받지 않았다.
- cryptography `_rust.pyd`에 들어간 OpenSSL·Rust 크레이트의 원문은 휠에 없고 승인 목록 밖이라 받지 않았다. 재작업 1회차에서 휠 동봉 SBOM 2개를 넣고 구성요소·라이선스 목록을 §10.2에 적었다. 원문을 받을지는 사용자 확인 항목이다.
- 배포용 PDF 확인은 빌드 뒤 PYZ·`pdfium.dll` 존재 검사와 verify의 `pdfium.dll` 확인뿐이다. 실제 PDF 처리는 검증용(`HAZOP-check.exe`)에서만 했다. 두 빌드의 앱 Analysis는 같은 spec이다.
- 앱 화면에는 PDF 등록 경로가 아직 없다(입력 어댑터 트랙 D1 열린 결정). 이번 작업은 묶음에 넣고 묶인 인터프리터에서 동작함을 확인한 것이다.
- 앱 정보 창의 고지 위치 안내는 W10이다. `ROADMAP.md`는 PROGRESS 기준일·현재 단계·지금 할 일만 맞췄다(README 상태 갱신 규칙). `README.md` §6 결정 인덱스(빈 표)는 고치지 않았다.
- LGPL 요건 충족 여부는 법무 검토 전까지 판단 보류(사용자 결정)이며 이 문서는 법적 판단이 아니다.

## 8. 산출물(저장소 밖)

- `%TEMP%\hazop-w9-dl\`: 내려받은 원문·목록 페이지·PyPI JSON, `pip\freeze-{before,after}.txt`
- `%TEMP%\hazop-w9\`: `snapshot.out`, `{verify,deploy}-build\`(spec·datas.json·build.log·build\·dist\), `{verify,deploy}-build.out`, `builds.json`, `{verify,deploy}-{ascii,korean}.out`(성공 회차)·`.diskfull.out`(공간 부족 회차), `results-*\run-*\`, `verify.json`, `ut-tree.txt`, `check_adapter.txt`
- `%TEMP%\hazop-w9-src`: 스냅숏
- 지울지는 총괄이 판단한다.

## 9. (결번: 재작업 기록은 §10)

## 10. 재작업 1회차(2026-11-06 10:45~11:10)

검토: Claude 조건부 승인, Codex 조건부 승인. 총괄 지시 1~8을 반영했다.

### 10.1 추가로 받은 파일(qtbase `v6.12.0`, 승인 범위 "Qt v6.12.0 qtbase 제3자 원문")

이미 받은 `qt_attribution.json`의 `LicenseFile`·`CopyrightFile`이 가리키는 파일을 모두 받았다(25개, 모두 HTTP 200·text/plain, 앞부분 내용 확인). 출처 URL은 `https://code.qt.io/cgit/qt/qtbase.git/plain/src/3rdparty/<경로>?h=v6.12.0`이다. `licenses/qt/third-party/files/<경로>`에 바이트 그대로 넣었다. 파일별 SHA-256 전체는 `licenses/README.md` "내려받은 원문(W9)" 표에 있다.

| 경로(`src/3rdparty/`) | bytes | SHA-256 앞 12자리 | 종류 |
|---|---|---|---|
| `D3D12MemoryAllocator/LICENSE.txt` | 1,099 | `5478a2f36b73` | LicenseFile |
| `VulkanMemoryAllocator/LICENSE.txt` | 1,099 | `846d97c8b74c` | LicenseFile |
| `blake2/COPYING` | 17,914 | `4103f471877e` | LicenseFile |
| `double-conversion/LICENSE` | 1,527 | `4af93c12062c` | LicenseFile |
| `easing/LICENSE` | 1,505 | `92fac99458f1` | LicenseFile |
| `freetype/LICENSE.txt` | 26,234 | `bf543cdda118` | LicenseFile |
| `freetype/ZLIB-LICENSE.txt` | 962 | `2b1f5d615382` | LicenseFile |
| `freetype/BDF-LICENSE.txt` | 2,305 | `e4e792f29e66` | LicenseFile |
| `freetype/PCF-LICENSE.txt` | 2,218 | `6938597bfdec` | LicenseFile |
| `harfbuzz-ng/COPYING` | 1,971 | `ba8f810f2455` | LicenseFile |
| `icc/LICENSE.txt` | 463 | `9e34ff47b3a4` | LicenseFile |
| `libjpeg/LICENSE` | 6,077 | `ba6bceebcba0` | LicenseFile |
| `libjpeg/ijg-license.txt` | 1,815 | `1cb448f5e2e6` | LicenseFile |
| **`libjpeg/COPYRIGHT.txt`** | 606 | `e5b349c6a98d` | **CopyrightFile**(libjpeg-turbo 저작권자 15줄) |
| `libpng/LICENSE` | 5,345 | `bdb0a645ea18` | LicenseFile |
| `libpsl/PSL-LICENSE.txt` | 16,726 | `3f3d9e0024b1` | LicenseFile |
| `libpsl/src/LICENSE.chromium` | 1,664 | `1d7f52747a91` | LicenseFile |
| `md4c/LICENSE.md` | 1,096 | `d30937367d54` | LicenseFile |
| `pcre2/LICENCE.md` | 4,011 | `197d8a73ffee` | LicenseFile |
| `pcre2/LICENSE-SLJIT` | 1,444 | `5f216505c0f6` | LicenseFile |
| `rfc6234/LICENSE` | 1,568 | `7ccebd514aaa` | LicenseFile |
| `sha3/BRG_ENDIAN_LICENSE` | 645 | `2fed6f252ca4` | LicenseFile |
| `sha3/CC0_LICENSE` | 7,013 | `1f2786e2c5be` | LicenseFile |
| `tinycbor/LICENSE` | 1,074 | `3c6ba0b5bfa7` | LicenseFile |
| `zlib/LICENSE` | 1,465 | `d7e313997287` | LicenseFile |

- `LicenseFile`·`CopyrightFile`이 없는 구성요소(emoji-segmenter·md4·md5·sha1·siphash·wintab)는 `qt_attribution.json`의 Copyright 문구와 SPDX 본문으로 고지한다. qtimageformats의 libtiff·libwebp 원문은 1차에서 받았다.
- 다른 저장소(qtbase·qtimageformats 밖)에서 받은 파일은 없다.

### 10.2 cryptography SBOM(휠 동봉, 설치 승인 범위)

`cryptography-48.0.0.dist-info/sboms/`의 두 파일을 `licenses/python/cryptography-sboms/`에 복사했다. `sbom.json`은 1,223 bytes(`e6cc12d0c30a…`), `cryptography-rust.cyclonedx.json`은 45,557 bytes(`e36672336b2a…`)다. `licenses/README.md` [주13]의 근거를 SBOM으로 바꿨다.

- `sbom.json`(CycloneDX 1.5): 구성요소 1개(**openssl 4.0.0**). 라이선스 표기는 없다. OpenSSL 3 이후는 Apache-2.0이다 [일반지식].
- `cryptography-rust.cyclonedx.json`(cargo-cyclonedx 0.5.9): 크레이트 39개.

| 라이선스 식별자(SBOM) | 크레이트 |
|---|---|
| Apache-2.0 OR BSD-3-Clause | cryptography-cffi·crypto·keepalive·key-parsing·openssl·x509·x509-verification(각 0.1.0) |
| BSD-3-Clause | asn1 0.24.1, asn1_derive 0.24.1 |
| MIT OR Apache-2.0(또는 Apache-2.0 OR MIT) | base64 0.22.1, bitflags 2.11.1, cc 1.2.61, cfg-if 1.0.4, find-msvc-tools 0.1.9, foreign-types-shared 0.1.1, foreign-types 0.3.2, heck 0.5.0, itoa 1.0.18, libc 0.2.186, once_cell 1.21.4, openssl-macros 0.1.1, pkg-config 0.3.33, portable-atomic 1.13.1, proc-macro2 1.0.106, pyo3-build-config·pyo3-ffi·pyo3-macros-backend·pyo3-macros·pyo3 0.28.3, quote 1.0.45, shlex 1.3.0, syn 2.0.117, vcpkg 0.2.15 |
| MIT | openssl-sys 0.9.115, pem 3.0.6 |
| Apache-2.0 | openssl 0.10.79 |
| Apache-2.0 OR GPL-2.0-only | self_cell 1.2.2 |
| Apache-2.0 WITH LLVM-exception | target-lexicon 0.13.5 |
| (MIT OR Apache-2.0) AND Unicode-3.0 | unicode-ident 1.0.24 |

- SBOM은 빌드 도구 크레이트(cc·syn·quote·proc-macro2·pkg-config·vcpkg 등)와 실행 파일에 들어간 크레이트를 구분하지 않는다. 어느 것이 `_rust.pyd`에 실제로 들어갔는지는 확인하지 않았다 [추론: 매크로·빌드 크레이트는 실행 코드에 남지 않음].
- OpenSSL·크레이트 원문은 승인 목록 밖이라 받지 않았다. 받을지는 PROGRESS의 사용자 확인 항목으로 등록했다.

### 10.3 변경

| 지시 | 변경 |
|---|---|
| 1 | `verify_bundle.pdf_probe_problems`: 필수 모듈 7개(`PDF_PROBE_MODULES`) 키나 `pdfium_dll` 키가 결과에 없으면 "결과에 없음"으로 실패한다. `PDF_PROBE_MODULES`가 `pdf_probe.PROBE_MODULES`와 같음은 테스트로 고정했다 |
| 2 | `build_package._tree_hashes`가 `os.walk(onerror=…)`로 탐색 오류를 올린다. `licenses_problems`는 탐색·읽기 오류를 "고지 대조 중 탐색 오류"로 실패 처리한다 |
| 3 | §10.1 원문 25개, README 행 25개(구성요소 이름, LicenseFile·CopyrightFile 구분), REQUIRED_NOTICES |
| 4 | §10.2 SBOM 2개, README 행 2개와 [주13], PROGRESS 사용자 확인 항목 |
| 5 | README 고지 목록 표의 빈 줄(1차 75행)을 지우고 Qt GPL-2.0 행을 GPL-3.0 행 뒤로 옮겼다. `_table_problems`는 빈 줄로 끊겨 머리행 없이 시작하는 표와 칸 수 불일치를 잡는다. 1차 README에 적용하면 "76행: 머리행·구분행 없이 시작하는 표"를 잡는다 |
| 6 | `test_main_rc3_when_finish_bundle_fails`: finish_bundle이 `["x"]`를 돌려주면 main rc=3이고, 결과 폴더 경로·with_check로 한 번 불린다 |
| 7 | 문구: 휠 태그 설명(§1.2), 목록 밖 조회에 qtbase LICENSES 트리 페이지 추가(§1.1). `pdf_probe`는 pypdfium2_raw가 실제로 읽은 pdfium 모듈의 경로(읽은 핸들의 `GetModuleFileNameW`)를 기록한다. LicenseNoticeTest 설명, `out = tempfile` 띄어쓰기, `packaging/README.md` venv 절차에 `requirements-pdf.txt` 설치 |

### 10.4 빌드·verify·테스트

- 이전 W9 산출물(`%TEMP%\hazop-w9`, `-src`)은 작은 로그만 `%TEMP%\hazop-w9-r0-logs`에 남기고 지웠다.
- 스냅숏 `%TEMP%\hazop-w9-src`: HEAD `cd3194d`, 511개(disk 403·overlay 108), 목록 해시 `499b92f8c2a3e3221433ce81eed431ba4c52883515afbb2aa027b4627ed1e22f`. 작업 트리의 코드·`licenses/`와 같은 바이트다(cmp·diff).
- 빌드: 검증용 **rc=0**(115.9초, WARNING 2), 배포용 **rc=0**(71.1초, WARNING 1). 경고는 1차와 같은 `qmlassetdownloaderprivateplugin.dll`이다. 결과 폴더·고지·PDF·바이너리(D10·D13) 검사를 통과했다.

| | W8-B | 1차 | **재작업 1회차** |
|---|---|---|---|
| 배포용 | 2,234개, 553,023,605 bytes(527.4 MiB) | 2,502개, 594,669,767 bytes | **2,529개, 594,840,886 bytes(567.3 MiB)**. W8-B 대비 +295개, +41,817,281 bytes(+39.9 MiB) |
| 검증용 | 2,241개, 558,992,308 bytes | 2,503개, 601,492,043 bytes | 2,530개, 601,663,162 bytes(573.8 MiB) |

1차 대비 +27개·+171,119 bytes는 `licenses/`의 추가 원문 25개와 SBOM 2개다.

| verify | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** rc=0 `results-verify-ascii\run-20261106-105708-wt16rvxy` | **통과** rc=0 `results-verify-korean\run-20261106-105849-39101uw_` |
| 배포용 `--app-only` | **통과** rc=0 `results-deploy-ascii\run-20261106-110031-qhrj1j6w` | **통과** rc=0 `results-deploy-korean\run-20261106-110139-iq12mjtr` |

- 검증용: w4_flow rc=0(16단계, ①~⑤), check_kg_screen [OK] 13·[FAIL] 0, pdf_probe rc=0·`pdf_problems` = `[]`, PNG 9장, `licenses_problems` = `[]`, 저장소 불변, 앱 로그·rc=2. 실제로 읽힌 `pdfium.dll` 경로는 `…\HAZOP\_internal\pypdfium2_raw\pdfium.dll`이다.
- 배포용: PNG 4장, `licenses_problems`·`pdf_problems` = `[]`, 앱 로그·rc=2·저장소 불변.

| 테스트 | 결과 |
|---|---|
| 전용 venv `-m unittest tests.test_packaging` | **63건 OK**(1차 60 + 3: 표 연속성, 고지 탐색 오류, finish_bundle rc=3. pdf_probe 키 누락은 기존 테스트에 추가) |
| 전용 venv `-m unittest discover -s tests` | **689건 OK(건너뜀 5)**, rc=0 |
| 전용 venv `scripts/check_adapter.py` | rc=0 |

## 11. W9-B — 남은 고지 원문(2026-11-06, D17)

근거: 총괄 결정(권고안, 사용자 위임 2026-11-06 "프로젝트를 끝까지, 모두 권장사항으로 진행"). 기준 HEAD `3231a54`. 실행 주체: hazop-developer.
받은 파일은 저장소 밖 새 빈 폴더 `%TEMP%\hazop-w9b-dl\`에 먼저 받아 형식·내용을 확인한 뒤 `licenses/`로 바이트 그대로 복사했다. 파일별 출처 URL·크기·SHA-256 전체는 [`licenses/README.md`](../../../licenses/README.md) "내려받은 원문(W9-B)" 표(62행)에 있다. 받지 못한 파일은 없다.

### 11.1 받은 파일

| 항목 | 출처 | 결과 |
|---|---|---|
| VS 2022 Professional·Enterprise 사용 조건 | 사용 조건 페이지(`visualstudio.microsoft.com/license-terms/vs2022-ga-proenterprise/`, 236,577 bytes, `licenses/`에 넣지 않음)가 가리키는 `https://visualstudio.microsoft.com/wp-content/uploads/2021/11/Visual-Studio-2022-Enterprise-Professional-License-EN.docx` | HTTP 200, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, 63,513 bytes, `9c0cd52b20db…`. zip 항목 25개(매크로 `vbaProject.bin` 없음). `msvc/vs2022-license-terms.docx`로 그대로 넣음. 재배포 조건은 본문 §5 "DISTRIBUTABLE CODE"(Distributable List = `https://aka.ms/vs/17/redistribution`) |
| 위 .docx의 텍스트 사본 | `word/document.xml`의 문단(`w:p`)마다 `w:t`·`w:tab`·`w:br`를 이어 붙임(python-docx 없이 표준 라이브러리 `zipfile`·`xml.etree`, `python -I`, 스크립트는 저장소 밖) | `msvc/vs2022-license-terms.txt`, 101문단, 27,040 bytes(UTF-8, LF), `217fff972ce3…`. 목록 번호·서식·각주는 빠진다. 받은 파일이 아니므로 고지 목록에만 있고 내려받은 원문 표에는 없다 |
| OpenSSL 4.0.0 `LICENSE.txt` | `https://raw.githubusercontent.com/openssl/openssl/openssl-4.0.0/LICENSE.txt`. 태그 확인 `git ls-remote`: 태그 객체 `d2a596365b43…`, 커밋 `11b7b6ea3b65…` | HTTP 200, text/plain, 10,175 bytes, `7d5450cb2d14…`, Apache License 2.0 본문. `python/openssl-4.0.0-LICENSE.txt` |
| Rust 크레이트 원문 60개(32개 크레이트) | `https://static.crates.io/crates/<이름>/<이름>-<버전>.crate`(tar.gz)에서 최상위 `LICENSE*`·`LICENCE*`·`COPYING*`·`NOTICE*`·`COPYRIGHT*`·`UNLICENSE*`·`AUTHORS*` 파일만 메모리에서 읽어 저장. 코드는 풀지 않았고 `.crate`는 해시 기록 뒤 지움 | 32개 모두 HTTP 200. **`.crate` 32개의 SHA-256이 모두 SBOM(`cryptography-rust.cyclonedx.json`) 구성요소의 SHA-256과 같음**(불일치 0·해시 없음 0). 32개 모두 LICENSE 파일이 있었다. `python/cryptography-rust-crates/<이름>-<버전>/` |

### 11.2 크레이트 범위(런타임·빌드 구분 시도)

- SBOM 39개 중 7개(`cryptography-cffi`·`-crypto`·`-keepalive`·`-key-parsing`·`-openssl`·`-x509`·`-x509-verification`)는 `download_url=file`인 cryptography 소스 안 경로 크레이트다. 라이선스가 cryptography와 같아(SBOM `Apache-2.0 OR BSD-3-Clause`) 기존 `python/cryptography-LICENSE*`로 고지한다.
- 나머지 crates.io 크레이트 32개 중 SBOM scope `excluded`는 빌드 스크립트 전용 5개(cc·find-msvc-tools·pkg-config·shlex·vcpkg)다. proc-macro·빌드 설정 크레이트(syn·quote·proc-macro2·asn1_derive·openssl-macros·pyo3-macros·pyo3-macros-backend·pyo3-build-config·heck·target-lexicon·unicode-ident 등)는 `required`로 적혀 있어 SBOM으로 구분할 수 없다. 휠에는 `Cargo.lock`·`Cargo.toml`이 없다.
- 따라서 작업지시서의 "구분 못하면 전부"에 따라 **32개 전부**의 원문을 넣었다. README 고지 목록의 구성요소 칸에 SBOM scope를 그대로 적었다(`빌드 전용, SBOM scope excluded` / `SBOM scope required`). 어느 크레이트가 실제로 `_rust.pyd`에 링크됐는지는 확인하지 않았다.
- 크레이트별 원문: MIT·Apache-2.0 두 원문 25개 크레이트(50개), asn1·asn1_derive `LICENSE`(BSD-3-Clause), openssl `LICENSE`(저작권 고지와 Apache-2.0 안내)·`LICENSE-APACHE`, openssl-sys `LICENSE-MIT`, pem `LICENSE.md`(MIT), self_cell `LICENSE-APACHE`·`LICENSE-GPLv2`(Apache-2.0 OR GPL-2.0-only 선택), target-lexicon `LICENSE`(Apache-2.0 WITH LLVM-exception), unicode-ident `LICENSE-UNICODE`(Unicode-3.0). 합계 60개.

### 11.3 목록 밖 조회(메타데이터, `licenses/`에 넣지 않음)

- VS 2022 사용 조건 페이지(.docx 링크를 찾기 위해, 작업지시서가 지정한 페이지).
- `git ls-remote https://github.com/openssl/openssl refs/tags/openssl-4.0.0`(태그 커밋 기록용).
- crates.io 색인(index.crates.io)은 조회하지 않았다. `.crate`의 무결성은 휠 동봉 SBOM 해시로 대조했다.

### 11.4 변경

| 파일 | 변경 |
|---|---|
| `licenses/` | 원문 63개 추가(.docx 1·텍스트 사본 1·OpenSSL 1·크레이트 60). `README.md`: 머리말 갱신 줄·근거 문서 안내(w9 §11), 고지 목록 63행, "내려받은 원문(W9-B)" 표 62행, W9 표의 VS 2022 "받지 못함" 행에 W9-B 안내, [주11]·[주13] 갱신, [주14] 신규 |
| `tests/test_packaging.py` | `REQUIRED_NOTICES`에 63개(`_CRATES_MIT_APACHE` 25개 × 2 + 개별 10 + .docx·.txt·OpenSSL), `LicenseNoticeTest.test_rust_crates_cover_sbom`(SBOM의 crates.io 크레이트 32개 = 원문 폴더 32개) |
| `evidence/w6-라이선스.md` §8 | Visual C++ 런타임 행, PDF 어댑터 행 상태를 "있음(W9-B, D17)"으로 |

### 11.5 남은 한계

- .docx는 업로드 경로가 2021년 11월(VS 2022 GA)이다. 이후 판 변경 여부와 Microsoft의 최신 사용 조건과의 차이는 확인하지 않았다. 텍스트 사본은 읽기용이며 원문은 .docx다.
- OpenSSL 원문은 태그 `openssl-4.0.0` 파일이다. 휠을 만들 때 쓴 OpenSSL 소스가 이 태그와 같은지는 SBOM의 판 표기(4.0.0)만 근거다.
- 크레이트 원문은 링크 여부와 관계없이 32개 전부다(빌드 전용 5개 포함). 고지가 남는 쪽(과다 고지)이며 누락은 없다.
- 이 문서는 법적 판단이 아니다(LGPL 등 법무 검토 전).
