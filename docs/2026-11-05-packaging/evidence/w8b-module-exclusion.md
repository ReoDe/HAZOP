# W8-B — GPL 전용 Qt 모듈 제외 (T2)

> 1차 2026-11-06 08:20~09:10, 재작업 1회차 09:15~09:40, **재작업 2회차(최종): 09:45~10:10**. 기준 HEAD `5225cc5` + W8-B 미커밋 변경(`scripts/build_package.py`·`tests/test_packaging.py`). 실행 주체: hazop-developer.
> 근거 결정: D13. ① 사용자 결정(GPL 전용 모듈 제외, [W6 라이선스](w6-라이선스.md) §9-2 (가))과 ② 총괄 판정(Qt5Compat.GraphicalEffects·Qt6SpatialAudio를 의존 관계로 함께 제외)으로 나뉜다.
> 비교 기준: W8-A 재작업 2회차 묶음(`%TEMP%\hazop-w8r2`, [W8 경로 통제](w8-경로통제.md) §3). §3~§7의 수치는 재작업 2회차 결과이고, 이전 회차는 §9에 있다.

## 1. 왜 묶음에 들어왔나(PyInstaller 6.22.3 원본·빌드 로그)

- 앱은 `PySide6.QtCore·QtGui·QtWidgets·QtWebChannel·QtWebEngineCore·QtWebEngineWidgets`만 import한다(`hazop/`·`scripts/run_app.py`·`extract_drawio.py`·`build_graph.py` grep). QML·Quick을 직접 쓰지 않는다.
- 그런데 `Qt6WebEngineCore.dll`이 `Qt6Quick.dll`·`Qt6Qml.dll`을, `Qt6WebEngineWidgets.dll`이 `Qt6Quick.dll`·`Qt6QuickWidgets.dll`을 링크한다(PE import, §2.3). 그래서 PyInstaller가 `hook-PySide6.QtQuick`·`hook-PySide6.QtQml`을 실행했다(W8-A 배포용 `build.log` 59·61행).
- `PyInstaller/hooks/hook-PySide6.QtQml.py` 15행은 `collect_qtqml_files()`를 부른다. 이 함수(`PyInstaller/utils/hooks/qt/__init__.py` 916~970행)는 `PySide6/qml` 아래 `qmldir`가 있는 **모든** QML 플러그인 폴더와 그 DLL 의존성을 모은다. Charts·Quick3D·VirtualKeyboard 등은 이 경로로 묶였다.

## 2. 제외 목록과 근거

라이선스 근거는 venv 설치본(`%USERPROFILE%\.hazop\venv-py312\Lib\site-packages\PySide6`) 파일 머리의 SPDX 식별자다.

- GPL 전용 파일 수: `LicenseRef-Qt-Commercial OR GPL-3.0-only`를 가진 파일 수(`WITH Qt-GPL-exception-1.0`이 붙은 파일 포함)
- LGPL 파일 수: `OR LGPL-3.0-only`를 가진 파일 수

### 2.1 ① 사용자 결정(GPL 전용 모듈)

| 모듈(규칙 이름) | 라이선스 근거(파일:행) | GPL 전용 / LGPL 파일 수 | 묶음에서 뺀 파일(W8-A 배포용 TOC 기준) |
|---|---|---|---|
| Charts | `qml/QtCharts/designer/ChartViewSpecifics.qml:2` | 17 / 0 | `Qt6Charts.dll`·`Qt6ChartsQml.dll`, `qml/QtCharts/` — 55개, 2,597,384 bytes |
| DataVisualization | `qml/QtDataVisualization/designer/Bars3DSpecifics.qml:2` | 6 / 0 | `Qt6DataVisualization*.dll`, `qml/QtDataVisualization/` — 18개, 1,897,761 bytes |
| Graphs | `qml/QtGraphs/designer/Bars3DSpecifics.qml:2` | 15 / 0 | `Qt6Graphs*.dll`(Graphs2DImpl 포함), `qml/QtGraphs/` — 39개, 3,005,014 bytes |
| Quick3D(Physics·Xr 포함) | `qml/QtQuick3D/Physics/designer/BoxShapeSection.qml:2`, `qml/QtQuick3D/Xr/XrErrorDialog.qml:2`, `qml/QtQuick3D/Helpers/AxisHelper.qml:2` | `qml/QtQuick3D` 아래 305 / 0(그중 17개는 `WITH Qt-GPL-exception-1.0`) | `Qt6Quick3D*.dll` 14개(Physics·Xr·SpatialAudio 등), `qml/QtQuick3D/`, `plugins/qmltooling/qmldbg_quick3dprofiler.dll`, 총괄 판정분 `Qt6SpatialAudio.dll`(§2.2) — 642개, 19,031,955 bytes |
| VirtualKeyboard | `qml/QtQuick/VirtualKeyboard/Components/AlternativeKeys.qml:2` | 41 / 0 | `Qt6VirtualKeyboard*.dll` 3개, `qml/QtQuick/VirtualKeyboard/`(입력기 Hangul·OpenWNN·Pinyin·TCIme·Thai 포함), `plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll` — 84개, 5,681,037 bytes |
| QuickTimeline | 설치본에 SPDX 표기 없음(`qml/QtQuick/Timeline` 0 / 0) | — | `Qt6QuickTimeline*.dll` 2개, `qml/QtQuick/Timeline/` — 8개, 246,716 bytes |
| ShaderTools | 설치본에 SPDX 표기 없음(DLL만 있음) | — | `Qt6ShaderTools.dll` — 1개, 4,480,312 bytes |

- **QuickTimeline·ShaderTools의 라이선스**는 설치본에서 확인하지 못했다. 두 모듈을 GPL 전용으로 본 근거는 W6 §9-2의 [일반지식]과 사용자 결정(D13)이다.
- `qmldbg_quick3dprofiler.dll`은 `Qt6Quick3DUtils.dll`을 import한다. 그래서 Quick3D에 딸린 파일로 다룬다.
- 다음은 현재 묶음에 없지만 들어오지 않게 규칙에 넣었다.
  - `plugins/assetimporters/`: `assimp.dll`이 `Qt6Quick3D*.dll`을 import한다
  - 바인딩 `QtCharts.pyd`·`QtDataVisualization.pyd`·`QtGraphs.pyd`·`QtGraphsWidgets.pyd`·`QtQuick3D.pyd`·`QtSpatialAudio.pyd`
- 번역: 위 모듈 전용 `.qm`은 설치본 `translations/`에 없다(묶음 번역은 `qt`·`qtbase`·`qtdeclarative`·`qtlocation`·`qtwebengine`). 그래서 뺀 번역 파일은 없다.

### 2.2 ② 총괄 판정(의존 관계로 함께 제외)

| 대상 | 근거 | 뺀 파일 |
|---|---|---|
| Qt5Compat.GraphicalEffects(**LGPL**, 0 / 32) | `qml/Qt5Compat/GraphicalEffects/qmldir`가 `depends Qt5Compat.GraphicalEffects.private`이다. private 플러그인 `qtgraphicaleffectsprivateplugin.dll`은 `Qt6ShaderTools.dll`을 import한다. W8-A TOC 전수에서, 남은 QML·qmldir 가운데 이 모듈을 import하는 파일은 0개다 | `qml/Qt5Compat/GraphicalEffects/` 38개, 1,735,338 bytes |
| `Qt6SpatialAudio.dll`·`QtSpatialAudio.pyd`(라이선스 미확인) | W8-A 묶음에서 `Qt6SpatialAudio.dll`을 import하는 것은 `Qt6Quick3DSpatialAudio.dll`(제외 대상)뿐이다. 1차 W8-B 묶음에서는 importer가 0개인 고아였다(§3.4). `QtSpatialAudio.pyd`는 묶음에 없으며, 들어오지 않게 규칙에만 넣었다 | 1개, 779,576 bytes(Quick3D 규칙에 포함) |

### 2.3 남긴 것

| 대상 | 근거 |
|---|---|
| `Qt6Quick.dll`·`Qt6Qml.dll`·`Qt6QuickWidgets.dll` | pefile로 확인한 import 목록은 다음과 같다. `Qt6WebEngineCore.dll`: Core·Gui·Network·Positioning·Qml·Quick·WebChannel. `Qt6WebEngineWidgets.dll`: Core·Gui·PrintSupport·Quick·QuickWidgets·WebEngineCore·Widgets |
| 사용자 목록 밖의 모듈(Quick Controls·Qt3D·Location·Multimedia 등) | 라이선스가 일부 미확인이고, 사용자 결정 범위 밖이다(§7). importer가 0개인 최상위 DLL의 판정은 §3.4에 있다 |

## 3. 변경

### 3.1 판정 방식(재작업 2회차, `scripts/build_package.py`)

`QT_EXCLUDED_MODULES`는 (모듈 이름, 이름 규칙, 폴더 규칙) 8개다. `qt_module_rejected(dest, src, roots)`가 판정한다.

| 규칙 | 적용 대상 | 판정 |
|---|---|---|
| **이름 규칙** | 묶음 안 이름, 출처, 출처 실경로(긴 파일명)의 **파일 이름**. 결과 폴더에서는 각 파일의 이름과 실경로 파일 이름 | 파일 이름 **전체**가 목록과 같으면(대소문자 무시) 위치와 관계없이 걸린다 |
| **폴더 규칙** | PySide6 기준 상대 경로만 본다. 묶음 안 이름은 `PySide6/…`로 시작할 때, 출처는 실경로가 허용 루트(`<루트>/Lib/site-packages/PySide6`) 안일 때, 결과 폴더는 `_internal/PySide6/…`일 때다 | 그 상대 경로가 `qml/QtCharts/` 등 목록 폴더로 시작하면 걸린다. 절대 경로의 상위 폴더 이름이나 `--out` 경로는 보지 않는다 |

- **이름 규칙 목록**은 설치본 PySide6 6.12.0에서 뽑았다. 각 모듈의 DLL·바인딩과, 제외 폴더(`qml/QtCharts/` 등·`plugins/assetimporters/`) 안의 플러그인 DLL 이름 전부(모두 70개: 모듈 DLL·바인딩 36, 단독 플러그인 2, 폴더 안 플러그인 32)다.
  - 단독 플러그인 `qtvirtualkeyboardplugin.dll`·`qmldbg_quick3dprofiler.dll`도 포함한다.
  - 설치본의 다른 파일과 이름이 겹치는 것은 없다(설치본 전수 대조로 확인, 테스트는 폴더 안 충돌만 고정). 디버그·변형 이름(`…d.dll`)은 설치본에 없다.
  - `Qt6Charts-custom.dll`·`Qt6ChartsExtra.dll`처럼 접두사만 같은 이름은 걸리지 않는다.
- **이동된 파일**:
  - 플러그인을 포함해 **목록에 있는 DLL·pyd**는 다른 폴더로 옮겨도 이름으로 걸린다. 예: `_internal/moved/qtvirtualkeyboardplugin.dll`·`qmldbg_quick3dprofiler.dll`·`assimp.dll`, `_internal/Qt6Charts.dll`.
  - **DLL이 아닌 qml 폴더 내용**(`qmldir`·`.qml`·`.qmltypes` 등)은 `_internal/PySide6/` 아래 원래 폴더에 있을 때만 걸린다. 다른 곳으로 옮기면 걸리지 않는다(§7).
- **탐색**: `dist_files`가 결과 폴더를 `os.walk(onerror=…)`로 돈다. 다음 경우는 OSError가 되고, `check_sources`가 "결과 폴더 탐색 오류"로 기록해 rc=3이 된다.
  - 폴더 목록 읽기 실패
  - 결과 폴더 없음
  - 링크·junction 폴더(재작업 2회차)
  - 파일 목록에 들어왔지만 실제로는 폴더인 항목(`os.lstat` 기준, 재작업 2회차)
  - `os.lstat` 실패
- spec의 `drop_binaries`는 D10 TLS 규칙에 더해 이 규칙을 두 Analysis의 binaries·datas에 적용한다. 허용 루트는 빌드 인터프리터의 `sys.prefix`·`sys.base_prefix`다.

`tests/test_packaging.py`의 변경은 §6에 있다. `packaging/verify_bundle.py`·`w4_flow.py`는 바꾸지 않았다.

### 3.2 os.walk 동작(Python 3.12.10 `Lib/os.py` 360~432행 확인)

| 상황 | os.walk 동작 | 이번 코드의 처리 |
|---|---|---|
| 폴더를 열 수 없음(`scandir` 실패), 항목 열거 중 오류 | `onerror` 호출 | 예외로 올려 검사 실패 |
| 항목의 `entry.is_dir()`이 OSError | 오류를 삼키고 **파일로 분류**해 `files`에 넣는다. 그 폴더 안은 탐색하지 않는다 | 이름은 파일처럼 이름 판정을 받는다. 그 위에 `os.lstat`으로 폴더인지 다시 확인해 폴더면 "폴더를 탐색하지 못함", `lstat`이 실패하면 그 OSError로 검사 실패. 모의 테스트로 확인했다(실제 ACL 재현은 아님) |
| 심볼릭 링크 폴더 | `followlinks=False`라 `dirs`에는 있으나 안으로 들어가지 않는다(`os.path.islink`) | "링크 폴더(탐색하지 않음)"로 검사 실패 |
| junction 폴더 | 3.12의 `islink`는 junction에 False라 안으로 들어간다 | 묶음 밖을 가리킬 수 있어 같은 방식으로 검사 실패(`os.path.isjunction`). 실제 junction으로 테스트했다 |

PyInstaller one-folder 결과(Windows)에는 링크 폴더가 생기지 않으므로 정상 빌드에는 영향이 없다. 재빌드 2종에서 통과를 확인했다(§4).

### 3.3 오탐 확인(재작업 2회차 규칙)

| 대상 | 걸림 / 전체 | 모듈별 |
|---|---|---|
| **설치본 PySide6 전체**(`analysis\fp-installed.txt`, 묶음 안 이름 `PySide6/<상대 경로>`, 출처 = 실제 파일) | 896 / 3,893 | Charts 56, DataVisualization 19, Graphs 43, Quick3D 647, QuickTimeline 8, ShaderTools 1, VirtualKeyboard 84, Qt5Compat.GraphicalEffects 38 |
| W8-A 배포용 결과 폴더·TOC | 885 / 3,119 | Charts 55, DataVisualization 18, Graphs 39, Quick3D 642, QuickTimeline 8, ShaderTools 1, VirtualKeyboard 84, Qt5Compat.GraphicalEffects 38 |
| W8-A 검증용 결과 폴더·TOC | 885 / 3,126 | 같음 |
| **재작업 2회차 배포용·검증용 결과 폴더·TOC** | **0 / 2,234, 0 / 2,241** | — |

- 설치본에서 폴더 규칙 밖, 곧 이름 규칙으로만 걸린 파일은 38개다. 모두 목록의 최상위 DLL·pyd 36개와 단독 플러그인 2개(`plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll`, `plugins/qmltooling/qmldbg_quick3dprofiler.dll`)이며, 의도 밖 파일은 0개다.
- 나머지 858개는 모두 목록 폴더 안이다.
- 설치본이 W8-A 묶음보다 많은 이유는 묶음에 없는 바인딩 `.pyd` 6개, `Qt6GraphsWidgets.dll`, `plugins/assetimporters/assimp.dll` 등이 설치본에만 있기 때문이다.
- W8-A 묶음의 885개는 재작업 1회차 규칙(경로 꼬리)의 결과와 같다.

### 3.4 고아 DLL(제외 전후, `analysis\orphans-deploy.txt`)

모든 바이너리의 PE import(지연 import 포함)로 묶음 안 importer를 셌다.

| DLL | W8-A importer | 제외 뒤 importer | 판정 |
|---|---|---|---|
| `PySide6/Qt6SpatialAudio.dll` | `Qt6Quick3DSpatialAudio.dll`(제외) | 0 | **제외**(총괄 판정, §2.2) |
| `PySide6/Qt6OpenGLWidgets.dll` | `Qt6Charts.dll`(제외)뿐 | 0 | **남김**. 사용자 목록 밖이고 Qt Base 모듈이라 LGPL로 추정한다 [일반지식, 설치본 SPDX 표기 없음]. 빼도 크기만 줄 뿐 라이선스 목적과 관계가 없어 총괄 판정 범위 밖이다. 후속 정리 후보 |
| `PySide6/opengl32sw.dll` | 없음(제외 전에도 0) | 0 | **남김**. Mesa 소프트웨어 OpenGL로, Qt가 하드웨어 OpenGL을 쓸 수 없을 때 실행 중 동적으로 읽는다 [일반지식]. PyInstaller가 일부러 모으며, import로 연결되지 않는 것이 정상이다 |

- 재작업 2회차 묶음에서 최상위 DLL(`_internal/` 또는 `PySide6/` 바로 아래) 가운데 importer가 0개인 것은 위 두 개뿐이다.
- QML·Qt 플러그인 DLL은 실행 중에 읽히므로 집계에서 뺐다.
- 남은 바이너리 가운데 묶음에 없는 PySide6 폴더 DLL을 import하는 것은 0개다(`analysis\compare-*.txt`).

## 4. 스냅숏·빌드(재작업 2회차)

```
python packaging/make_snapshot.py --dest %TEMP%\hazop-w8b3-src ^
  --restore-head hazop/viewer/template.html scripts/check_design.py tests/test_design.py ^
  docs/2026-11-05-design-system/PROGRESS.md docs/2026-11-05-design-system/decisions.md docs/2026-11-05-design-system/evidence/README.md
```

- 스냅숏 결과: HEAD `5225cc5`, 401개(disk 395·head 6), 목록 해시 `4c71d46e5f1a307b53bc8fcd242ee80ad1f77bbfa15b867d67a619289c2674c0`.
- `--restore-head`는 다른 담당(T6 W8)이 고치는 중인 파일이다. 그 뒤 수정된 `docs/2026-11-05-design-system/ROADMAP.md`는 디스크 내용 그대로 들어갔지만 묶음 datas가 아니다.
- 스냅숏의 `scripts/build_package.py`·`tests/test_packaging.py`는 작업 트리와 같은 바이트다(cmp).
- 빌드는 Python 실행기(`analysis\run_build3.py`)로 했고 종료 코드를 직접 받았다. 환경은 닫힌 포트 프록시 `127.0.0.1:9`, `PIP_NO_INDEX=1`, PATH 통제(D10)다.

| 빌드 | `--out` | 결과 | 로그 | 결과 폴더 |
|---|---|---|---|---|
| 검증용 | `%TEMP%\hazop-w8b3\verify-build --with-check` | **rc=0**(실측), 97초, 결과 폴더 검사·바이너리 검사 통과 | WARNING 2(W8-A와 같은 `qmlassetdownloaderprivateplugin.dll` 경고) | `dist\HAZOP-verify\` 558,992,308 bytes(533.1 MiB), 2,241개 |
| 배포용 | `%TEMP%\hazop-w8b3\deploy-build` | **rc=0**(실측), 79초, 두 검사 통과 | WARNING 1(같은 경고) | `dist\HAZOP\` **553,023,605 bytes(527.4 MiB), 2,234개** |

TOC SHA-256: 배포용 `465abb1c…3087`, 검증용 `ffd264f7…66b6`. 묶음 구성과 크기는 재작업 1회차와 같다. 이번 회차의 규칙 변경은 판정 방식을 고친 것이며, 걸리는 파일 집합은 바꾸지 않았다.

### 크기 변화(W8-A 재작업 2회차 대비)

| 묶음 | W8-A | **W8-B(최종)** | 차이 |
|---|---|---|---|
| 배포용 | 3,119개, 591,693,665 bytes(564.3 MiB) | **2,234개, 553,023,605 bytes(527.4 MiB)** | −885개, −38,670,060 bytes(−36.9 MiB, −6.5%) |
| 검증용 | 3,126개, 597,658,749 bytes(570.0 MiB) | **2,241개, 558,992,308 bytes(533.1 MiB)** | −885개, −38,666,441 bytes |

- 빠진 885개(BINARY 59·DATA 826)는 모두 §2 규칙으로 설명된다. 규칙 밖에서 빠진 항목과 새로 들어온 항목은 0개다.
- 빠진 파일의 출처 크기 합은 38,675,517 bytes다. 결과 폴더 차이와 수천 bytes 다른데, 이는 스냅숏 차이(W8-A `dbcc855` ↔ `5225cc5`, 템플릿 등) 때문이다 [추론: datas 파일별로 대조하지는 않음].

## 5. 실행 확인(재작업 2회차)

`verify_bundle.py`를 스냅숏에서 Python 실행기(`analysis\run_verify3.py`, 경로를 인자 목록으로 전달)로 4회 실행했다. 조건은 W8-A와 같다(묶인 실행 PATH = `System32;Windows`, `QT_*`·`OPENSSL_*`·`SSL_CERT_*` 제거).

| 실행 | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** rc=0 `results-verify-ascii\run-20261106-094708-*` | **통과** rc=0 `results-verify-korean\run-20261106-094850-*` |
| 배포용 `--app-only` | **통과** rc=0 `results-deploy-ascii\run-*` | **통과** rc=0 `results-deploy-korean\run-*` |

- **검증용 두 경로**:
  - `w4_flow` rc=0(16단계: ①~⑤ 함수 흐름·자원 읽기 위치·음성 검사).
  - check_kg_screen rc=0, [OK] 13·[FAIL] 0(QtWebEngine 렌더링 포함).
  - 앱 PNG 9장, `licenses_problems` = `[]`, 입력 사본·저장소 불변, 앱 로그 시작·미처리 예외 기록, 잘못된 옵션 rc=2.
- **배포용 두 경로**: 앱 PNG 4장, `licenses_problems` = `[]`, 앱 로그·rc=2·저장소 불변.

## 6. 테스트

| 테스트 | 확인하는 것 |
|---|---|
| `test_qt_module_exclusion_rules` | 규칙마다 대표 이름(대소문자·구분자 섞음, `Qt6SpatialAudio.dll` 포함)이 해당 모듈로 판정되고 spec 필터에서 빠진다. `Qt6Quick`·`Qt6Qml`·`Qt6QuickWidgets`·WebEngine·Qt3D·Quick Controls·`Qt6OpenGLWidgets`·`opengl32sw`·`Qt6Multimedia`·번역·`licenses/`는 남는다. 이름을 바꾼 항목은 출처로 잡힌다. 결과 폴더에서는 다음을 확인한다. **걸림**: 옮긴 DLL과 이동된 플러그인(`_internal/moved/qtvirtualkeyboardplugin.dll`·`qmldbg_quick3dprofiler.dll`·`assimp.dll`·`QTVKBHANGULPLUGIN.dll` 등). **안 걸림**: `_internal/docs/plugins/assetimporters/readme.txt`, `_internal/other/qml/QtCharts/qmldir`, `Qt6Charts-custom.dll`, `Qt6ChartsExtra.dll`, `qml/QtChartsFake/` |
| `test_qt_rules_ignore_absolute_ancestors`(신규) | 출처가 `…\qml\QtCharts\project\venv\Lib\site-packages\PySide6\Qt6Core.dll`(허용 루트가 그 venv이든 아니든)이어도 `Qt6Core`·Quick Controls `qmldir`는 걸리지 않는다. 무관한 `docs/plugins/assetimporters/readme.txt`, 접두사만 같은 `Qt6Charts-custom.dll`·`Qt6QuickTimelineX.dll`도 걸리지 않는다. 허용 루트 안 출처는 묶음 안 이름을 바꿔도 PySide6 기준 경로로 걸리고, 허용 루트 밖이면 상위 이름을 무시한다. 출력 폴더가 `…\qml\QtCharts`여도 정상 묶음은 `check_sources` = `[]`다 |
| `test_spec_applies_filter_to_both_analyses`(신규) | 생성한 spec을 PyInstaller 없이 모의 실행한다(Analysis·PYZ·EXE·COLLECT 대역). 배포용·검증용 모두 COLLECT로 가는 binaries·datas 목록(2개·4개)에 제외 대상(Charts DLL·Quick3D qmldir·OpenSSL TLS 플러그인)이 없음을 확인한다. **음성 확인**: spec에서 필터 연결 4줄(`a/c.binaries·datas = drop_binaries(…)`)을 하나씩 지우면 4건 모두 이 테스트가 실패했다(메모리 변형, `analysis\mutate_spec.py`) |
| `test_check_sources_qt_modules` | TOC의 VirtualKeyboard와 결과 폴더의 `qml/QtQuick3D/qmldir`를 각각 잡는다. main은 새 출력 폴더에서 결과 폴더 위반 없이 TOC 위반 1건만으로 rc=3이고, TOC가 깨끗하면 rc=0이다 |
| `test_result_folder_unwalked_dirs`(신규) | `is_dir()` 오류로 파일 목록에 들어온 폴더(모의 walk)는 "폴더를 탐색하지 못함"이 되고, 실제 junction 폴더(`mklink /J`, 못 만들면 건너뜀 — 이 PC에서는 실행됨)는 "링크 폴더"가 된다 |
| `test_result_folder_walk_errors` | 결과 폴더가 없으면 실패한다. 결과 폴더 탐색에서 `PermissionError`가 onerror로 오면(모의) `dist_files`가 예외를 내고 `check_sources`가 1건을 기록하며, `main --build`는 rc=3이다 |
| `test_qt_exclusion_against_installed_pyside6` | 설치본에 대해 다음을 확인한다. 이름 규칙의 모든 이름이 설치본에 있고 다른 모듈 파일과 이름이 겹치지 않는다. 폴더 규칙의 모든 폴더가 있다. 앱이 import하는 모듈 DLL에서 PE import를 따라간 의존 DLL은 하나도 걸리지 않으며, 그 안에 Quick·Qml·QuickWidgets가 있다 |

| 실행 | 결과 |
|---|---|
| 전용 venv `-m unittest tests.test_packaging`(작업 트리) | **55건 OK**(W8-A까지 48 + D13 7), 건너뜀 없음 |
| 전용 venv 작업 트리 `-m unittest` | **681건 OK(건너뜀 14)**, rc=0. 다른 담당(T6 W8)의 진행 중 변경이 함께 있는 작업 트리다 |

## 7. 한계·남은 일

- QuickTimeline·ShaderTools·`Qt6SpatialAudio`의 라이선스는 설치본으로 확인하지 못했다([일반지식] 또는 미확인, 사용자 결정·총괄 판정으로 제외).
- **결과 폴더 검사가 잡지 못하는 범위**:
  - 이름 규칙에 없는 이름으로 바꾼 파일(예: `_internal/PySide6/renamed.dll`에 `Qt6Charts.dll` 내용).
  - `_internal/PySide6/` 밖으로 옮긴 qml 폴더 내용(`qmldir`·`.qml`·`.qmltypes` 등 DLL이 아닌 파일).
  - 하드 링크로 실경로 이름이 다른 경우.
  - PyInstaller가 수집한 항목이면 TOC 검사가 출처의 파일 이름·PySide6 기준 경로로 잡는다. 파일 내용(해시)으로는 판정하지 않는다.
- **탐색**: 결과 폴더 검사는 §3.2의 경우를 실패로 처리한다. 다만 `is_dir()` 오류 경로는 모의로만 확인했고, 실제 ACL·권한 오류를 재현하지는 않았다.
- 남은 바이너리가 빠진 DLL을 import하는지는 분석 스크립트로 확인했을 뿐(§3.4), 빌드 검사에는 넣지 않았다. PySide6 판을 올리면 다시 확인해야 한다.
- 설치본 대조 테스트는 이름·폴더가 설치본에 있는지와 앱·WebEngine 의존 경로만 본다. PySide6 판이 바뀌어 새로 생긴 제외 모듈 파일(새 플러그인 이름 등)을 찾아내지는 못한다. 그래서 판을 올릴 때 이름 목록을 다시 뽑아야 한다(Codex 재검토 지적, 한계로 둠).
- 검토용으로 제공된 스냅숏에는 빌드·verify 원본 산출물이 없어 독립 재검증이 어렵다. 원본은 저장소 밖 `%TEMP%\hazop-w8b3`에만 있다(§8; Codex 재검토 지적, 한계로 둠).
- 사용자 목록 밖에도 GPL 전용일 수 있는 모듈이 있다. 예를 들어 Lottie(`Qt6Lottie*.dll`), `Qt6LabsStyleKit*`, `Qt6CanvasPainter` 등은 설치본에 SPDX 표기가 없어 판단하지 못했다 [미확인].
- `licenses/`(편집 범위 밖)는 바꾸지 않았다 [미확인, licenses/ 미열람].
- 빌드 네트워크 표본 조사(netwatch)는 하지 않았다.

- 링크 폴더 판정의 `os.path.isjunction`은 Python 3.12 이상에만 있다. 전용 venv(3.12.10)에서는 해당 없고, `--allow-other-python`으로 3.11 이하에서 빌드하면 AttributeError로 멈춘다(총괄 최종 판정에서 한계로 기록).
- 이름 규칙의 `assimp.dll`은 Qt 밖에서도 쓰는 이름이다. 다른 의존성이 같은 이름의 파일을 가져오면 빌드가 rc=3으로 멈춘다(실패하는 쪽이라 반입 위험은 없음).
- W8-A의 `tls_rejected`는 아직 출처 절대 경로 안의 `/plugins/tls/`로 판정한다(같은 유형, 실패하는 쪽). 후속 후보.

## 8. 산출물(저장소 밖)

- `%TEMP%\hazop-w8b3\`(재작업 2회차)
  - `verify-build\`·`deploy-build\`(spec·datas.json·build.log·build\·dist\), `verify-build.out`·`deploy-build.out`(RC·시간 포함)
  - `{verify,deploy}-{ascii,korean}.out`, `results-{verify,deploy}-{ascii,korean}\run-*\`
  - `analysis\`
    - 스크립트: `compare.py`·`orphans.py`·`fp_check.py`·`fp_installed.py`·`names.py`·`mutate_spec.py`·`run_build3.py`·`run_verify3.py` 등
    - 출력: `compare-{deploy,verify}.txt`·`orphans-deploy.txt`·`fp-check.txt`·`fp-installed.txt`
  - `ut-tree.txt`(전체 테스트 출력)
- `%TEMP%\hazop-w8b3-src`: 스냅숏이다.
- 이전 회차: `%TEMP%\hazop-w8b2`(-src)는 재작업 1회차, `%TEMP%\hazop-w8b`(-src)는 1차다.
- 지울지는 총괄이 판단한다.

## 9. 이전 회차 요약

- **1차**(스냅숏 목록 해시 `2e1936ca…2dfc`):
  - 규칙을 PySide6 상대 이름 정규식(접두사)으로 판정했고, `Qt6SpatialAudio.dll`은 제외 대상이 아니었다.
  - 배포용 2,235개·553,803,181 bytes, 빠진 것 884개.
  - verify 4회 통과, test_packaging 51 OK, 전체 674 OK. 검증용 빌드 rc는 실측하지 않았다.
  - 첫 verify 4회는 셸 인용 오류로 target-base가 `Temp$tb`가 되어 무효 처리했다.
  - 검토: Codex 반려, Claude 조건부 승인.
- **재작업 1회차**(스냅숏 `5642675c…e02a`):
  - 경로의 모든 꼬리로 판정해 결과 폴더 전체를 보게 했다.
  - `os.walk` onerror, main rc=3 테스트 분리, 고아 DLL 기록, `Qt6SpatialAudio.dll` 제외(총괄 판정).
  - 배포용 2,234개·527.4 MiB, 빌드 rc=0 실측, verify 4회 통과, test_packaging 52 OK, 전체 676 OK.
  - 재검토: Claude 조건부 승인, Codex 반려. 지적은 다음과 같았다.
    - 절대 경로의 상위 폴더 이름으로 정상 파일이 걸림
    - 접두사 과매칭
    - 이동한 플러그인 미검출
    - `is_dir()` 오류
    - spec 연결 미검증
    - 문서 범위
  - 반영 위치: §3.1·§3.2·§6.
