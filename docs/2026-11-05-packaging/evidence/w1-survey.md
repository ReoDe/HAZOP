# W1 조사 — 패키징 사전 조사 (T2)

| 항목 | 내용 |
|---|---|
| 조사 일시 | 2026-11-05 |
| 기준 | 브랜치 `chore/track-workspaces`, 커밋 `d540288` |
| 방법 | 저장소 코드·문서 읽기, 로컬 환경 조회(설치된 패키지 메타데이터 읽기만), 웹 공식 문서·npm 레지스트리 조회 |
| 하지 않은 것 | 패키지 설치, 실행 파일 빌드, 파일 다운로드, 저장소 코드 외부 전송, FAT32·exFAT·네트워크 드라이브 실측 |
| 표기 | 사실은 출처(저장소 경로 또는 §8 출처 번호 [Sn])를 붙인다. `[추론]` = 근거에서 이끈 판단, `[일반지식]` = 출처 미확인 일반 지식, `[미확인]` = 확인하지 못함 |

읽은 범위: `docs/2026-11-05-packaging/README.md` 전부, `기획서/인터페이스.md` §2.2~2.4·§4.2·§7·§8·§9, `기획서/전체기획.md` 신뢰 경계 절, `hazop/paths.py` 전부, `hazop/app/data.py` 1~35행과 `script_module` 호출부, `scripts/run_app.py` 전부, `hazop/kg/vendor/force-graph-1.52.0/SOURCE.md` 전부, `hazop/review/store.py` `write_exclusive` 부분, `hazop/analysis/integrity.py` 1~70행, `hazop/analysis/ai.py` 175~200행. 그 밖의 파일은 grep 결과만 봤다.

## 0. 요약

1. 신뢰 경계는 "기준 자료를 실행 폴더에 고정하고 해시로 대조"(선택지 A)를 권고한다. 카탈로그·적용 판단·기준표는 이미 코드 상수로 고정돼 있다(`hazop/analysis/integrity.py`). 패턴 라이브러리와 지침서는 아직 고정되지 않았으므로 이 둘을 추가로 묶어야 한다.
2. 글꼴은 "Pretendard를 넣지 않고 맑은 고딕 유지"(선택지 A)를 권고한다. Pretendard는 OFL 1.1이라 함께 배포할 수 있다. 다만 웹뷰가 로컬 파일 URL을 막고 있어 글꼴을 넣는 방법을 따로 만들어야 하고, 예약 글꼴 이름(RFN) 조건도 지켜야 한다.
3. force-graph UMD 번들은 의존성을 모두 포함한다(rollup UMD 설정에 `external` 없음). 포함 패키지는 MIT·ISC이고, d3-scale-chromatic에는 ColorBrewer(Apache-2.0) 고지가 있다. 번들 안에서 ColorBrewer `Paired` 색표 문자열도 확인했다. 따라서 제3자 고지 파일이 필요하다.
4. 실행 파일 도구는 PyInstaller one-folder를 권고한다. 막힐 지점은 네 곳이다: 현재 Python이 LibreOffice 내장 Python이라는 점, `scripts/*.py`를 파일 경로로 읽는 importlib 로딩, 패키지 안 HTML·JS·지침서·참고자료 같은 비 Python 자원, 한글이 들어간 경로에서 QtWebEngineProcess가 동작하는지 여부.
5. `os.link` 하드 링크는 NTFS에서만 지원된다는 것이 Microsoft 문서에 명시돼 있다. FAT32·exFAT에서는 실패하며, 현재 코드에서는 저장 실패(OSError)로 나타난다. Windows의 `os.rename`은 대상이 있으면 항상 FileExistsError를 낸다고 Python 문서에 명시돼 있어, 대체 수단으로 쓸 수 있다.

## 1. 인터페이스 §9 미결 2건

### 1.1 패키징 후 신뢰 경계

**사실**

- 전체기획 신뢰 경계 표에서 패턴 라이브러리·구간 정의는 "사람 검토와 버전 관리", 이탈 카탈로그·위험도 기준표는 "내용 해시로 고정하고 지침과 대조"로 대응한다. 고의 변조는 범위 밖이다(`기획서/전체기획.md` 신뢰 경계 절).
- 인터페이스 §7.1은 구간 JSON·고정 응답을 사용자 데이터(작업 루트)로 분류한다. 자원 루트에 두는 것은 카탈로그·적용 판단·패턴·기준표다. 이 분류는 `hazop/paths.py`의 `RESOURCE_INPUT_ROLES = ("candidate_catalog", "applicability", "patterns", "risk_criteria")`와 일치한다.
- 이미 고정된 항목: `hazop/analysis/integrity.py`의 `PINNED_SHA256`이 카탈로그·적용 판단(`applicability-region-SNP-M-102-pzr`)·위험도 기준표 3건을 고정한다. 불일치하면 분석이 차단된다. 지침서 `기획서/HAZOP기법지침.md`도 다시 읽어 대조하므로, 지침서 역시 자원 루트에 있어야 한다(`GUIDE_PARTS`).
- 고정되지 않은 항목: 패턴 라이브러리(`데이터/패턴/pressurizer-patterns.json`)는 `PINNED_SHA256`에 없다. 버전 관리에만 의존하며, 신뢰 경계 절의 "알려진 남은 위험" 첫 줄(패턴 편차 매핑 변경)이 이 항목에 해당한다.
- 적용 판단 파일은 구간별(`applicability-region-…`)로 만들어지지만 자원 루트에 있다. 새 구간을 추가하면 고정 해시도 코드 상수에 추가해야 하므로, 사용자가 구간을 늘리는 흐름과 충돌한다[추론].
- one-folder 배포에서 자원은 `_internal/` 아래 일반 파일이므로 사용자가 고칠 수 있다. 설치 위치가 `Program Files`라면 고칠 때 관리자 권한이 필요하다[일반지식].

**선택지**

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. 실행 폴더 고정 + 해시 대조 | 자원 루트의 기준 자료(카탈로그·적용 판단·기준표·패턴·지침서)를 배포본에 넣고, 빌드 때 만든 해시 목록(manifest)을 시작·분석 시 대조한다. 불일치하면 분석을 차단한다 | 지금의 "버전 관리" 대응을 "배포 버전 + 해시"로 그대로 옮긴다. 기존 `integrity.py` 방식과 같은 원리다 | 기준 자료를 바꾸려면 새 배포본이 필요하다. 구간별 적용 판단 파일을 추가하는 흐름은 막힌다 |
| B. 사용자 수정 허용 | 기준 자료를 작업 루트로 복사해 사용자가 고치게 한다. 실행 기록에 입력 해시만 남긴다 | 유연하다 | 신뢰 경계 표의 "신뢰하는 입력"이 사람 검토 없이 바뀐다. 해시 고정 검사(`integrity.py`)와 정면으로 충돌한다 |
| C. 혼합 | 카탈로그·기준표·지침서·패턴은 A로 고정한다. 구간별 적용 판단은 구간 JSON처럼 작업 루트의 사용자 데이터로 옮기고, 실행 기록에 해시와 "미고정" 경고를 남긴다 | 새 구간 추가가 가능하다 | `integrity.py`와 §7.1 분류 변경이 필요하다(편집 허용 범위 밖, 결정 필요) |

**권고: A** [추론]. 근거는 세 가지다. (1) 현재 코드가 이미 A 방식으로 동작하므로 변경이 가장 적다. (2) 신뢰 경계가 고의 변조를 범위 밖으로 두므로, 해시 대조는 "실수로 바뀐 파일 탐지"로 충분하다. (3) 구간 추가 요구는 MVP(샘플 1구간) 범위 밖이다. 구간을 늘리는 시점에 C로 확장한다.
추가 조치: 패턴 라이브러리와 지침서를 고정 대상에 넣는다. 코드 상수를 늘리는 방법과 빌드 manifest를 쓰는 방법이 있으며, 어느 쪽인지는 W2에서 정한다.

### 1.2 글꼴 (Pretendard 동봉 여부)

**사실**

- Pretendard는 SIL Open Font License로 배포되며, 글꼴만 따로 파는 것 외에는 상업적 사용·수정·재배포가 허용된다[S1]. 최신 릴리스는 v1.3.9다[S2](릴리스 연도는 페이지에 표시되지 않아 [미확인]).
- LICENSE에는 저작권자 4곳과 예약 글꼴 이름(RFN) 4개가 선언돼 있다: Pretendard, Source(Adobe), Inter, M PLUS 1[S3].
- OFL 1.1 조건[S4]: 소프트웨어와 함께 번들·임베드·재배포할 수 있다. 각 사본에 저작권 고지와 라이선스 전문을 넣어야 하고, 글꼴만 단독으로 팔 수 없다. 수정본(Modified Version)은 RFN을 주 글꼴 이름으로 쓸 수 없다.
- 서브셋(글자 삭제)이 수정본에 해당하는지는 문서에 직접 나오지 않는다. 정의상 "deleting"을 포함하므로 해당할 가능성이 높다[추론]. 따라서 직접 서브셋을 만들면 이름을 바꿔야 할 수 있다. 원본 그대로 넣으면 이 문제는 생기지 않는다.
- 현재 코드는 Pretendard를 쓰지 않는다. `hazop/app/tokens.py`는 `FONT_FAMILY = "Malgun Gothic"`이고 주석에 "Pretendard 배포는 미결정(§9)"이라고 적혀 있다. `hazop/kg/screen_template.html`도 "Malgun Gothic"을 직접 쓴다. 이 PC에는 Pretendard가 설치돼 있지 않다(시스템·사용자 글꼴 폴더 조회).
- 웹뷰는 로컬 파일 URL 접근을 끈다. 그래서 force-graph JS도 HTML에 인라인으로 넣었다(인터페이스 §2.2). 허용 스킴은 `file·qrc·data·blob·about`이다(`hazop/app/webview.py` `ALLOWED_SCHEMES`).
- Qt 쪽에서 `QFontDatabase.addApplicationFont`로 등록한 글꼴을 QtWebEngine(Chromium) 렌더링에서 쓸 수 있는지는 [미확인]이다. 쓸 수 없을 가능성이 높다고 본다[일반지식].

**선택지**

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. 동봉하지 않음(맑은 고딕) | 현재 구현 그대로 둔다. 인터페이스 §4.2의 "Pretendard, 없으면 맑은 고딕"을 "맑은 고딕"으로 정리한다(§4.2 반영은 T6) | 라이선스 의무가 없다. 작업이 없다. Windows 전용이라 글꼴이 항상 있다 | 디자인 시안과 서체가 다를 수 있다 |
| B. 원본 그대로 동봉 | Pretendard 정적 OTF/TTF 몇 굵기(예: Regular·SemiBold·Bold)와 `LICENSE`를 넣는다. Qt에는 `addApplicationFont`로, 웹뷰에는 `@font-face`를 base64 `data:` URL 또는 `qrc:`로 넣는다 | 디자인 의도대로 보인다 | 굵기마다 수백 KB~수 MB가 늘어난다(정확한 크기 [미확인]). HTML 인라인은 뷰어 검사(`<script>` 개수 등)와 무관하지만 HTML 크기가 커진다. 고지 파일이 필요하다 |
| C. 서브셋 동봉 | 한글 2,350자 등으로 줄여 넣는다 | 크기가 작다 | OFL 수정본이 되어 RFN 때문에 이름 변경이 필요할 수 있다[추론]. 서브셋 도구와 절차가 필요하다 |

**권고: A** [추론]. 근거: 지금 동작하는 상태 그대로이고, Windows 전용 앱이라 맑은 고딕이 항상 있으며, B·C는 웹뷰 글꼴 주입이라는 별도 구현과 고지 의무를 만든다. 디자인 충실도가 중요하다는 사용자 판단이 있으면 B(원본 그대로, 서브셋 없음)로 간다. 이 결정은 T6(§4.2 반영)에 넘긴다.

## 2. force-graph 1.52.0 UMD 번들 의존성과 라이선스

**사실**

- force-graph 1.52.0 `package.json`[S5]: license MIT, `unpkg`·`jsdelivr` 진입점은 `dist/force-graph.min.js`(저장소에 넣은 파일과 같은 경로, `SOURCE.md`). 런타임 의존성 15개: `@tweenjs/tween.js`, `accessor-fn`, `bezier-js`, `canvas-color-tracker`, `d3-array`, `d3-drag`, `d3-force-3d`, `d3-scale`, `d3-scale-chromatic`, `d3-selection`, `d3-zoom`, `float-tooltip`, `index-array-by`, `kapsule`, `lodash-es`.
- rollup 설정[S6]: UMD 빌드에는 `external` 설정이 없고 node-resolve·commonjs 플러그인을 쓴다. 따라서 모든 의존성과 하위 의존성이 번들에 들어간다. (조회한 설정 파일의 출력 파일명이 `ForceGraph.js`로 보여 `package.json`의 `force-graph.min.js`와 이름이 다르다. 같은 태그를 조회했는지는 [미확인].)
- 번들 안 흔적(로컬 grep): 헤더 주석은 force-graph 1줄뿐이고, 의존성 라이선스 머리말은 없다(`SOURCE.md` 기록과 일치). ColorBrewer `Paired` 색표 16진 문자열(`a6cee31f78b4…`)이 들어 있어, d3-scale-chromatic의 ColorBrewer 데이터가 포함된 것을 확인했다. `float-tooltip` 문자열 2회, `Tween` 18회도 나온다.

**의존성 표** (버전은 npm `latest` 기준. 번들에 실제로 들어간 정확한 버전은 lockfile이 없어 [미확인])

| 패키지 | 직접/하위 | 라이선스 | 출처 |
|---|---|---|---|
| force-graph 1.52.0 | 본체 | MIT | [S5], 저장소 `LICENSE` |
| @tweenjs/tween.js | 직접 | MIT | [S7] |
| accessor-fn | 직접 | MIT | [S8] |
| bezier-js | 직접 | MIT | [S9] |
| canvas-color-tracker → tinycolor2 | 직접 → 하위 | MIT, MIT | [S10], [S11] |
| d3-force-3d → d3-binarytree, d3-octree, d3-quadtree, d3-dispatch, d3-timer | 직접 → 하위 | MIT; binarytree·octree MIT; quadtree·dispatch·timer ISC[일반지식] | [S12], [S13], [S14] |
| d3-scale → d3-array(→ internmap), d3-format, d3-interpolate(→ d3-color), d3-time, d3-time-format | 직접 → 하위 | ISC; 하위 d3 모듈 ISC[일반지식] | [S15] |
| d3-scale-chromatic | 직접 | ISC, **ColorBrewer 부분은 Apache-2.0**(LICENSE에 별도 고지) | [S16], [S17] |
| d3-zoom → d3-drag, d3-selection, d3-transition(→ d3-ease 등), d3-interpolate, d3-dispatch | 직접 → 하위 | ISC; 하위 d3 모듈 ISC[일반지식] | [S18] |
| float-tooltip → preact, kapsule, d3-selection | 직접 → 하위 | MIT; preact MIT | [S19], [S20] |
| kapsule → lodash-es | 직접 → 하위 | MIT; lodash-es MIT | [S21], [S22] |
| index-array-by | 직접 | MIT | [S23] |

- 트리 셰이킹으로 일부 하위 모듈(예: d3-time-format)이 실제로 빠졌을 수 있다. 번들에 남았는지는 함수 이름이 축약돼 있어 확인하지 못했다[미확인]. 고지는 넓게(위 목록 전부) 하는 편이 안전하다[추론].

**배포 시 고지 방법** [추론]

- MIT·ISC는 저작권 고지와 허가 문구를 사본에 포함해야 한다. Apache-2.0(ColorBrewer)은 라이선스 사본 제공과 고지 유지가 필요하다[일반지식].
- 방법: `hazop/kg/vendor/force-graph-1.52.0/THIRD-PARTY-NOTICES.txt`(가칭)에 위 패키지별 저작권 줄과 라이선스 전문을 모으고, 배포본의 `licenses/` 폴더에 복사한다. 앱 "정보" 대화상자에서 이 폴더를 안내한다. 각 패키지 LICENSE 원문 수집은 다운로드에 해당하므로 사용자 승인 후 진행한다.
- 정확한 포함 버전을 확정하려면 force-graph 1.52.0 태그로 `npm ci`를 하거나 배포 tarball의 lockfile을 확인해야 한다. 이번 범위(설치·다운로드 금지) 밖이다.

## 3. PySide6 + QtWebEngine 실행 파일 묶기

### 3.1 현재 환경 (로컬 조회 사실)

- `python`은 LibreOffice 내장 Python 3.12.14다: `sys.executable` = `C:\Program Files\LibreOffice\program\python-core-3.12.14`(실행 파일이 아니라 폴더). 테스트 코드도 이 점을 우회한다(`tests/run_fixture.py` `python_exe()`, `tests/test_desktop_support.py` `PYTHON`).
- 서드파티 패키지는 LibreOffice 폴더가 아니라 사용자 site-packages(`%APPDATA%\Python\Python312\site-packages`)에 있다: PySide6 6.12.0(= PySide6_Essentials 6.12.0 + PySide6_Addons 6.12.0 + **PySide6_WebEngine 6.12.0.140** + PySide6_Pdf 6.12.0.140 + shiboken6 6.12.0), networkx 3.7, openpyxl 3.1.5(et_xmlfile 2.0.0), anthropic 0.102.0, httpx 0.28.1. PyInstaller·Nuitka는 설치돼 있지 않다.
- PySide6 폴더 크기는 약 656 MB다. `QtWebEngineProcess.exe`, `resources/`(icudtl.dat, qtwebengine_*.pak, v8_context_snapshot.bin, `.debug.*` 변형 포함), `translations/qtwebengine_locales/`(53개)가 있다.
- PySide6 계열 메타데이터의 라이선스 표기는 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`다.
- `py` 런처에는 3.14와 3.11만 등록돼 있고, python.org CPython 3.12는 없다.
- LibreOffice Python에 `venv`·`ensurepip` 모듈은 있다. 앱 코드는 LibreOffice(uno 등)를 import하지 않는다(grep: `uno`·`soffice` 0건). 즉 LibreOffice에 대한 의존은 인터프리터뿐이다.

### 3.2 PyInstaller 요구사항·함정

| 항목 | 내용 | 근거 |
|---|---|---|
| 지원 버전 | PyInstaller 6.22.3(2026-09-12), Python 3.8~3.15, Windows 8 이상 공식 지원 | [S24] |
| 라이선스 | GPL 2.0(예외 조항)+Apache 2.0. 만든 실행 파일 묶음은 의존 라이선스와 호환되는 한 원하는 라이선스로 배포할 수 있고, PyInstaller 고지 의무는 없다 | [S25] |
| QtWebEngine 수집 | PyInstaller Qt 훅이 모듈별 플러그인·번역을 모으고, QtWebEngineCore 훅이 보조 실행 파일·번역·리소스를 모은다. Qt 6.2.2 미만은 지원하지 않는다(소스 기준, 공식 문서 아님) | [S26] |
| QtWebEngine 필수 파일 | `QtWebEngineProcess.exe`; `resources/`의 `qtwebengine_resources*.pak`·`qtwebengine_devtools_resources.pak`·`icudtl.dat`·`v8_context_snapshot.bin`; `qtwebengine_locales/`. 경로는 `qt.conf` 또는 `QTWEBENGINEPROCESS_PATH`·`QTWEBENGINE_RESOURCES_PATH`·`QTWEBENGINE_LOCALES_PATH`로 바꿀 수 있다. Visual C++ 재배포 패키지 14.28 이상이 필요하다 | [S27] |
| one-folder | one-file은 실행할 때마다 임시 폴더에 풀기 때문에 QtWebEngine처럼 큰 묶음에는 느리고 불안정하다[일반지식]. 인터페이스 §7.2의 one-folder 판단과 같다 | §7.2 |
| 한글 경로 | Windows에서 `QTWEBENGINEPROCESS_PATH`를 ANSI로 읽어 일본어 폴더명에서 실패한 버그(QTBUG-85054, 해결됨으로 표시)와, 키릴·중국어 경로에서 `QtWebEngineProcess.exe`를 못 찾은 보고가 있다. Qt 6.12에서 재현되는지는 [미확인]이다. 사용자 이름이 한글이면 `%LOCALAPPDATA%` 경로에 한글이 들어간다 | [S28], [S29] |
| 번역 파일 | `PySide6/translations`에 `.qm` 314개가 있다. 앱이 한국어 Qt 번역을 쓰지 않으면 제외해 크기를 줄일 수 있다[추론]. 제외 방법(훅 설정)은 공식 문서에서 찾지 못해 [미확인] | 로컬 조회 |
| 디버그 리소스 | `.debug.pak`·`.debug.bin`은 배포에 불필요할 가능성이 크다[추론] | 로컬 조회 |
| LGPL 고지 | Qt 측 FAQ: 동적 링크를 권장하고, 사용자가 다른 Qt 라이브러리로 다시 링크(교체)할 수 있어야 하며, 정적 링크하면 앱이 LGPL 적용 대상이 될 수 있다. 메일링 리스트 의견(법적 판단 아님): 묶어 배포하면 Qt 소스 제공 또는 서면 제안이 필요하다. one-folder는 Qt DLL이 개별 파일로 남아 교체가 가능하다[추론] | [S30], [S31] |
| QtWebEngine 제3자 | Qt 부분은 LGPLv3/GPL, Chromium 부분은 BSD·MIT·Apache-2.0·LGPL 2.1(ffmpeg 등) 등 많은 항목을 포함한다. 배포자는 두 쪽 라이선스를 모두 지켜야 한다 | [S32] |
| 백신 오탐 | 서명하지 않은 PyInstaller 실행 파일은 오탐될 수 있다[일반지식] | §7.2 |

### 3.3 대안 비교

Qt for Python 공식 배포 문서의 비교표[S33]: PyInstaller(GPL, Qt6 "partial"), cx_Freeze(MIT, Qt6 yes), briefcase(BSD3, Qt6 partial), Nuitka(MIT, Qt6 yes), py2exe(Qt6 partial). 이 문서는 pyside6-deploy가 가장 쉽고 가장 최적화된 실행 파일을 만든다고 권한다.

| 도구 | 방식 | 이 저장소 기준 장점 | 단점·위험 |
|---|---|---|---|
| PyInstaller one-folder | 바이트코드 + 부트로더 | 인터페이스 §7.2와 `paths.py`가 이미 `sys._MEIPASS` 감지를 전제로 한다. QtWebEngine 훅이 있다. 컴파일러가 필요 없다 | 공식 표는 Qt6 지원을 "partial"로 적었다. 백신 오탐 |
| pyside6-deploy (Nuitka) | Python → C 컴파일 | Qt 공식 도구. 6.12부터 기본 모드가 standalone(폴더)이다. 기본 인자에 `--noinclude-qt-translations=True` | 첫 실행 때 Nuitka 등을 현재 환경에 설치한다. Windows에서 `dumpbin`(MSVC)이 필요하다. C 컴파일러가 필요하다[일반지식]. 빌드가 느리다. `paths.py`의 `sys._MEIPASS` 감지가 동작하지 않아 frozen 감지를 추가해야 한다[추론] |
| cx_Freeze | 바이트코드 + 실행 파일 | MIT, Qt6 yes | 저장소에 준비된 것이 없다. QtWebEngine 훅 수준은 [미확인] |
| briefcase | 설치 관리자까지 생성 | MSI 생성 | Qt6 partial. 프로젝트 구조(pyproject)를 바꿔야 한다 |

[S34]: pyside6-deploy 문서는 빌드 중 프로젝트의 모듈 수준 코드를 실행하므로 신뢰하는 프로젝트만 배포하라고 경고한다.

**권고: PyInstaller one-folder** [추론]. 기존 설계(§7.2, `paths.frozen_bundle_dir`)와 맞고 컴파일러가 필요 없다. W2에서 결과가 나쁘면(QtWebEngine 기동 실패 등) pyside6-deploy를 2순위로 시험한다.

### 3.4 이 저장소에서 막힐 지점

1. **인터프리터**: LibreOffice 내장 Python은 `sys.executable`이 폴더이고 배치가 표준 CPython과 다르다. PyInstaller가 python DLL과 표준 라이브러리를 제대로 찾을지 [미확인]이며, 위험이 크다고 본다[추론]. 또 패키지가 사용자 site-packages에 있어서, 같은 사용자의 다른 Python 3.12에도 섞여 보인다. → 전용 venv(§5)로 해결한다.
2. **importlib 로딩** (`hazop/app/data.py` `script_module`): `SCRIPTS_DIR = os.path.join(paths.REPO_ROOT, "scripts")`에서 `extract_drawio.py`·`build_graph.py`를 파일 경로로 읽는다(호출부: `data.py` 61·74·75행). PyInstaller는 이 경로를 정적 분석으로 따라가지 못한다. 그래서 (a) `scripts/*.py` 파일이 묶음에 들어가지 않고, (b) 그 스크립트만 import하는 `hazop` 하위 모듈이 빠질 수 있다[일반지식]. 묶인 실행에서 `paths.REPO_ROOT`는 `hazop/paths.py`의 위치 기준이므로 `_internal/`(= `sys._MEIPASS`)이 될 것으로 본다[추론, W2 확인]. 해결 선택지:
   - (가) 편집 허용 범위 안: 두 스크립트를 datas로 `scripts/`에 넣고 `hiddenimports`에 `hazop` 하위 모듈 전체(`collect_submodules("hazop")`)를 넣는다. `data.py`는 바꾸지 않거나 경로 결정만 정리한다.
   - (나) 범위 밖: `run_one`·`build_one`·`registered_out_name`을 `hazop/` 패키지로 옮기고 스크립트는 얇은 래퍼로 만든다. `scripts/extract_drawio.py`·`build_graph.py` 편집이 필요해 결정이 필요하다.
   - 권고: W2에서는 (가) [추론]. 근본 정리인 (나)는 별도 결정 사항으로 남긴다.
3. **비 Python 자원**: 패키지 안 `hazop/viewer/template.html`, `hazop/kg/screen_template.html`, `hazop/kg/vendor/force-graph-1.52.0/*`는 `__file__` 기준으로 읽는다(`hazop/viewer/build.py`, `hazop/kg/screen.py`). 자원 루트 기준으로 읽는 것은 `데이터/이탈후보·기준표·패턴`, `기획서/HAZOP기법지침.md`(`integrity.py`)이고, `참고자료/P&ID 도면 샘플`은 `scripts/extract_drawio.py` `SAMPLE_GLOB`과 등록 화면 파일 대화상자 시작 위치에서 쓴다. 모두 datas로 명시해야 한다. `참고자료/`는 28 MB이고 git 추적 파일이 약 97개다. 배포본에 넣을지는 결정이 필요하다.
4. **작업 루트 초기 내용**: frozen 실행에서 작업 루트는 `%LOCALAPPDATA%\HAZOP`(`paths.work_root`)다. 그런데 구간 JSON(`데이터/구간`)·고정 응답(`데이터/고정응답`)·지식 입력(`데이터/지식`, `scripts/build_kg.py` `DEFAULT_INPUT_ROOT`)은 작업 루트 기준으로 읽는다. 첫 실행 때 샘플을 작업 루트로 복사할지, 비워 둘지 정해야 한다[추론].
5. **스크립트의 기본 인자**: `paths.py` 주석대로 스크립트의 `DEFAULT_*`는 import 시점에 한 번 정해진다. 환경변수를 import 전에 설정해야 한다.
6. **네트워크 모듈**: `hazop/analysis/ai.py`는 함수 안에서 `anthropic`을 import한다. PyInstaller는 함수 안 import도 수집하므로[일반지식], venv에 anthropic·httpx가 있으면 묶음에 들어간다. 인터페이스 §8 공통 항목(프로그램 코드가 네트워크 모듈을 쓰지 않음)과 메모리 결정(지금은 실시간 API 없음)을 고려하면, 배포 venv에서 빼거나 `excludes`로 막는 것이 맞다[추론].

## 4. `os.link` 배타적 생성 — NTFS 외 파일시스템

**사실**

- `hazop/review/store.py` `write_exclusive`: 같은 폴더 임시 파일에 쓰고 fsync한 뒤 `os.link(tmp, path)`를 호출한다. `FileExistsError`면 ReviewError(덮어쓰지 않음)를 내고, 그 밖의 OSError는 그대로 올라간다. 임시 파일은 `finally`에서 지운다. 사용처는 검토 기록 버전 파일(`store.py` 173행)과 Excel 출력·출력 기록(`hazop/export/worksheet.py` 504·510행)이다.
- Microsoft 문서: `CreateHardLinkW`는 "NTFS 파일 시스템에서만, 파일에만" 지원되고 모든 링크는 같은 볼륨에 있어야 한다. 표(Windows 8/Server 2012 기준)에 따르면 SMB 3.0은 지원하지만 Transparent Failover·Scale-out 공유는 지원하지 않고, ReFS도 지원하지 않는다. 연속 가용성(continuous availability) 공유에서는 하드 링크를 만들 수 없다[S35]. 하드 링크 개요 문서도 NTFS 기준으로 설명한다[S36].
- 따라서 FAT32·exFAT에서는 `os.link`가 실패하며, 그 OSError가 `FileExistsError`가 아니므로 저장 실패가 된다. 이때 최종 파일은 생기지 않는다(코드 구조상). 정확한 오류 코드(예: winerror 1 또는 50)는 실측하지 않아 [미확인]이다.
- 네트워크 드라이브는 서버 쪽 파일시스템과 공유 설정에 달려 있다. NTFS 기반 일반 SMB 공유는 동작하고, NAS(Samba 등)·CA 공유는 실패할 수 있다. NAS 동작은 [미확인]이다. 최근 Windows 버전 ReFS의 하드 링크 지원 여부도 [미확인]이다(MS 표는 Win8/2012 기준).
- Python 문서: Windows에서 `os.rename`은 대상이 있으면 항상 `FileExistsError`를 낸다. `os.replace`의 원자성 문장은 POSIX 요구사항으로만 적혀 있다[S37]. `os.open`의 `O_EXCL`은 Windows에서도 사용할 수 있고, 동작은 MSDN을 보라고 안내한다[S37].

**대체 방법**

| 방법 | 배타성 | 내용 원자성(중간 상태 노출) | 비고 |
|---|---|---|---|
| 현재: 임시 파일 + `os.link` | 있음 | 있음(완성된 파일만 이름을 얻음) | NTFS·일반 SMB 한정 |
| 임시 파일 + `os.rename`(Windows) | 있음(대상 있으면 FileExistsError, [S37]) | 이름 변경은 한 번의 디렉터리 연산. 전원 차단 시 일관성은 파일시스템 저널 여부에 따른다[추론] | FAT·exFAT·SMB 모두에서 동작할 것으로 본다[추론]. POSIX에서는 덮어쓰므로 Windows 전용 전제 필요 |
| `open(path, "xb")`(O_CREAT\|O_EXCL)로 바로 쓰기 | 있음 | 없음(쓰는 중 실패하면 부분 파일이 남음) | 읽는 쪽에서 부분 파일을 걸러야 한다 |
| O_EXCL 빈 파일 선점 + 임시 파일 `os.replace` | 있음 | 대체로 있음. 선점 직후 중단되면 빈 파일이 남는다 | 버전 목록(`list_versions`)이 빈 파일을 버전으로 셀 위험 |

**권고** [추론]: 기본 동작은 `os.link`로 유지하고, `os.link`가 "지원하지 않음" 계열 OSError로 실패할 때만 `os.rename`(Windows)으로 넘어가는 대체 경로를 둔다. 또는 대체 경로를 만들지 않고, 작업 루트를 고를 때 파일시스템을 확인해(`GetVolumeInformationW`) NTFS가 아니면 경고·거부할 수도 있다. 두 방법 모두 `hazop/review/store.py` 편집이 필요하다. README §8에 따라 `store.py`는 결정이 있어야 범위에 들어가므로 사용자 결정 사항이다. W2 이후에 FAT32·exFAT(USB)와 네트워크 공유에서 실측 검사를 먼저 하기를 권한다.

## 5. 전용 venv 구성 제안

**실제 import 확인**(grep, `hazop`·`scripts`·`tests`): 표준 라이브러리를 빼면 서드파티는 PySide6(QtCore·QtGui·QtWidgets·QtWebChannel·QtWebEngineCore·QtWebEngineWidgets), shiboken6(`hazop/app/webview.py`), networkx(`hazop/graph/*`, `hazop/kg/*`, `scripts/check_kg_algo.py`), openpyxl(`hazop/export/worksheet.py`, 검사·테스트), anthropic(`hazop/analysis/ai.py` 함수 안, 테스트), httpx(`tests/test_analysis.py`만)다. `_winapi`(테스트)는 CPython 내장이다.

| 구분 | 패키지 | 고정 버전(현재 환경 기준) | 비고 |
|---|---|---|---|
| 배포 런타임 | PySide6 | 6.12.0 | Essentials·Addons·WebEngine(6.12.0.140)·Pdf(6.12.0.140)·shiboken6가 따라온다. 메타 패키지 대신 `PySide6_Essentials`+`PySide6_WebEngine`만 설치하면 Addons 전체를 피할 수 있는지는 [미확인]이다(WebEngine이 Addons를 요구함: 메타데이터 `Requires-Dist: PySide6_Addons==6.12.0`). Pdf는 쓰지 않는다 |
| 배포 런타임 | networkx | 3.7 | |
| 배포 런타임 | openpyxl | 3.1.5 | et_xmlfile 2.0.0 |
| 빌드 | pyinstaller | 6.22.x | [S24]. 설치는 W2(승인 후) |
| 개발·테스트(선택) | anthropic, httpx | 0.102.0, 0.28.1 | 배포 venv에서는 제외 권고(§3.4-6). 테스트의 AI 관련 항목이 이 둘을 요구하면 별도 개발 venv 또는 extras로 둔다 |

**인터프리터**: python.org CPython 3.12.x(현재 3.12.14와 같은 부 버전)를 권고한다[추론]. LibreOffice Python으로 venv를 만들면 기반 인터프리터가 여전히 LibreOffice 배치다. 기존 3.11·3.14로 바꾸면 테스트를 다시 검증해야 한다. 설치는 사용자 승인이 필요하다.
**구성안**: 저장소 밖(또는 `.gitignore`된) `.venv-pkg\`에 `requirements-runtime.txt`(위 런타임 3종 고정)와 `requirements-build.txt`(+pyinstaller)를 둔다. 파일 위치는 편집 허용 범위의 `packaging/` 아래를 권고한다. venv는 기본으로 사용자 site-packages를 보지 않으므로 지금의 `%APPDATA%\Python\Python312` 섞임이 사라진다[일반지식].

## 6. 사용자 결정이 필요한 항목

| # | 결정 | 권고 |
|---|---|---|
| 1 | 신뢰 경계: A 고정+해시 / B 수정 허용 / C 혼합 | A, 패턴·지침서 고정 추가 |
| 2 | 글꼴: A 맑은 고딕 / B Pretendard 원본 동봉 / C 서브셋 | A (T6에 §4.2 반영 인계) |
| 3 | python.org CPython 3.12 설치와 전용 venv 생성(설치 행위 승인) | 승인 요청 |
| 4 | 빌드 도구: PyInstaller one-folder 우선, pyside6-deploy는 차선 | PyInstaller |
| 5 | importlib 로딩: (가) datas+hiddenimports / (나) 함수를 `hazop/`로 이동(편집 범위 확대 필요) | (가) |
| 6 | `os.link`: 대체 경로 추가 / NTFS 아니면 거부 / 현 상태 유지. 모두 `store.py` 범위 확대 결정 필요 | 실측 후 결정. 기본은 "NTFS 아니면 경고·거부" |
| 7 | 배포본 자원 범위: `참고자료/` 샘플 도면(28 MB)·지침서·샘플 구간·고정 응답 포함 여부 | 지침서는 필수. 샘플은 사용자 판단(보안 등급 자료 여부 확인 필요) |
| 8 | anthropic·httpx를 배포본에서 제외 | 제외 |
| 9 | 제3자 고지용 LICENSE 원문 수집(npm 패키지·Qt 소스 제공 방식 포함 다운로드) | 승인 요청 |

## 7. W2 이후 작업 단위 제안

| ID(안) | 작업 | 완료 기준 |
|---|---|---|
| W2 | 전용 venv 구성(결정 3·8 후) | `packaging/requirements-runtime.txt`·`requirements-build.txt`가 버전을 고정한다. 새 venv에서 기존 `tests/` 전체와 `scripts/check_analysis.py`·`check_register.py`가 통과한다. venv 안 `pip list`에 anthropic·httpx가 없고(런타임) `sys.flags`/`site.ENABLE_USER_SITE`로 사용자 site 미사용을 확인한다. 결과는 `evidence/`에 기록한다 |
| W3 | 경로·로딩 정리(결정 5 후) | `paths.py` API의 하위 호환을 유지한다(기존 이름·인자 그대로, 추가만). `data.py`의 스크립트 경로가 frozen·개발 실행에서 모두 맞다. `HAZOP_RESOURCE_ROOT`·`HAZOP_WORK_ROOT`를 서로 다른 임시 폴더로 바꿔 ①~⑤ 흐름 검사가 통과한다(인터페이스 §8 "패키징 대비" 행). `tests/test_packaging.py`에 이 검사를 추가한다 |
| W4 | 첫 빌드(PyInstaller one-folder) | `scripts/build_package.py`가 spec과 datas 목록(템플릿·vendor·지침서·데이터·선택 샘플)을 만든다. ASCII 경로와 한글 경로(예: `C:\테스트\HAZOP`) 두 곳에서 `--screenshots`로 5개 화면 PNG가 생성되고, ③ V1·V2·S1 검사가 묶인 실행에서 통과한다. 묶음 크기와 빌드 로그를 `evidence/`에 기록한다 |
| W5 | 신뢰 경계 구현(결정 1 후) | 자원 해시 manifest(또는 `PINNED_SHA256` 확장)가 패턴·지침서를 포함한다. 자원 파일 1바이트 변경 시 분석이 차단되고 사유가 표시되는 테스트가 있다. 인터페이스 §7·§9가 갱신된다 |
| W6 | 라이선스 고지(결정 2·9 후) | `licenses/`에 PySide6/Qt(LGPLv3·GPL 텍스트, Qt 소스 제공 방법), QtWebEngine 제3자 목록, force-graph와 §2 의존성 전체(ColorBrewer Apache-2.0 포함), networkx·openpyxl·et_xmlfile, (B·C 선택 시) Pretendard OFL이 들어간다. 앱 정보 대화상자에서 안내한다. 누락 검사 스크립트가 통과한다 |
| W7 | `os.link` 실측과 대응(결정 6 후) | FAT32 또는 exFAT USB와 네트워크 공유 각각에서 `write_exclusive` 동작(성공/오류 코드)을 기록한다. 선택한 대응(대체 경로 또는 거부)이 테스트로 확인되고, NTFS 동작이 바이트 단위로 기존과 같다 |

순서 [추론]: W2 → W3 → W4가 핵심 경로다. W5·W6·W7은 W4 뒤에 서로 독립이므로 같은 파일을 다루지 않는 한 병렬로 할 수 있다. W3·W5는 `hazop/app/data.py`·`기획서/인터페이스.md`를 다루므로 T1·T6와 순차로 진행해야 한다(README §8).

## 8. 출처

- [S1] https://github.com/orioncactus/pretendard
- [S2] https://github.com/orioncactus/pretendard/releases/latest
- [S3] https://raw.githubusercontent.com/orioncactus/pretendard/main/LICENSE
- [S4] https://openfontlicense.org/open-font-license-official-text/
- [S5] https://cdn.jsdelivr.net/npm/force-graph@1.52.0/package.json
- [S6] https://raw.githubusercontent.com/vasturiano/force-graph/v1.52.0/rollup.config.js
- [S7] https://registry.npmjs.org/@tweenjs/tween.js/latest
- [S8] https://registry.npmjs.org/accessor-fn/latest
- [S9] https://registry.npmjs.org/bezier-js/latest
- [S10] https://registry.npmjs.org/canvas-color-tracker/latest
- [S11] https://registry.npmjs.org/tinycolor2/latest
- [S12] https://registry.npmjs.org/d3-force-3d/latest
- [S13] https://registry.npmjs.org/d3-octree/latest
- [S14] https://registry.npmjs.org/d3-binarytree/latest
- [S15] https://registry.npmjs.org/d3-scale/latest
- [S16] https://registry.npmjs.org/d3-scale-chromatic/latest
- [S17] https://raw.githubusercontent.com/d3/d3-scale-chromatic/main/LICENSE
- [S18] https://registry.npmjs.org/d3-zoom/latest
- [S19] https://registry.npmjs.org/float-tooltip/latest
- [S20] https://registry.npmjs.org/preact/latest
- [S21] https://registry.npmjs.org/kapsule/latest
- [S22] https://registry.npmjs.org/lodash-es/latest
- [S23] https://registry.npmjs.org/index-array-by/latest
- [S24] https://pypi.org/project/pyinstaller/
- [S25] https://pyinstaller.org/en/stable/license.html
- [S26] https://sources.debian.org/src/pyinstaller/6.18.0%2Bds-3/PyInstaller/hooks/hook-PyQt6.QtWebEngineCore.py , https://sources.debian.org/src/pyinstaller/6.18.0%2Bds-2/PyInstaller/utils/hooks/qt/__init__.py (검색 요약으로만 확인, 원문 미열람)
- [S27] https://doc-snapshots.qt.io/qtwebengine/qtwebengine-deploying.html (Qt WebEngine 6.140 기준 문서)
- [S28] https://bugreports.qt.io/browse/QTBUG-85054 (검색 요약으로만 확인)
- [S29] https://riverbankcomputing.com/pipermail/pyqt/2019-November/042362.html , https://forum.qt.io/post/564123 (검색 요약으로만 확인)
- [S30] https://www.qt.io/faq/3.7.-what-are-my-obligations-when-using-qt-under-the-lgpl , https://qt.io/licensing/open-source-lgpl-obligations (검색 요약으로만 확인)
- [S31] https://lists.qt-project.org/pipermail/pyside/2023-January/003256.html (검색 요약으로만 확인, 법적 판단 아님)
- [S32] https://doc-snapshots.qt.io/qtwebengine/qtwebengine-licensing.html
- [S33] https://doc.qt.io/qtforpython-6/deployment/index.html
- [S34] https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html
- [S35] https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createhardlinkw
- [S36] https://learn.microsoft.com/en-us/windows/win32/fileio/hard-links-and-junctions
- [S37] https://docs.python.org/3.12/library/os.html

라이선스 해석은 공개 문서 요약이며 법률 검토가 아니다. 배포 전에 조직의 법무·라이선스 담당 확인을 권한다.
