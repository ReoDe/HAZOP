# Qt·PySide6 구성요소와 소스 코드 위치

이 프로그램의 배포본에는 Qt for Python(PySide6 바인딩·shiboken6)과 Qt 라이브러리가 들어 있다.
이 문서는 배포 패키지별 구성과, 같은 버전의 소스 코드를 받을 수 있는 위치를 적는다. 라이선스 의무 충족 여부는 판단하지 않는다.

## 배포 패키지(빌드에 쓴 전용 venv의 휠)

| 휠 | 버전 | 메타데이터 라이선스 표기 | 묶음에 들어간 것 |
|---|---|---|---|
| `pyside6`(PySide6 바인딩 메타 패키지) | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | `PySide6/pyside6.abi3.dll`·`pyside6qml.abi3.dll` 등 |
| `pyside6_essentials` | 6.12.0 | 위 표기와 같은 문자열 | 바인딩 `QtCore`·`QtGui`·`QtWidgets`·`QtNetwork`·`QtOpenGL`·`QtPrintSupport`·`QtQml`·`QtQuick`·`QtQuickWidgets`(.pyd), 아래 Qt 모듈 |
| `pyside6_addons` | 6.12.0 | 위 표기와 같은 문자열 | 바인딩 `QtPositioning`·`QtWebChannel`(.pyd), 아래 Qt 모듈 |
| `pyside6_webengine` | 6.12.0.140 | 위 표기와 같은 문자열 | 바인딩 `QtWebEngineCore`·`QtWebEngineWidgets`(.pyd), Qt WebEngine 6.140.0, `QtWebEngineProcess.exe`, `resources/` |
| `pyside6_pdf` | 6.12.0.140 | 위 표기와 같은 문자열 | Qt 모듈 `Qt6Pdf`·`Qt6PdfQuick`(바인딩 .pyd는 없음) |
| `shiboken6` | 6.12.0 | 위 표기와 같은 문자열 | `shiboken6/` |

휠 메타데이터의 표기는 패키지 전체에 붙은 것이다. Qt 오픈소스판은 모듈마다 라이선스가 다를 수 있다(일부 모듈은 GPL 전용) [일반지식, 확인 필요: `docs/2026-11-05-packaging/evidence/w6-라이선스.md` §9-2].

## 묶음에 들어간 Qt 모듈(`_internal/PySide6/Qt6*.dll`, 휠별)

- `pyside6_essentials`(65개): Concurrent, Core, Gui, LabsAnimation, LabsFolderListModel, LabsPlatform, LabsQmlModels, LabsSettings, LabsSharedImage, LabsStyleKit, LabsStyleKitImpl, LabsSynchronizer, LabsWavefrontMesh, Network, OpenGL, OpenGLWidgets, PrintSupport, Qml, QmlCore, QmlDesignSupport, QmlLocalStorage, QmlMeta, QmlModels, QmlNetwork, QmlWorkerScript, QmlXmlListModel, Quick, QuickControls2와 QuickControls2Basic·BasicStyleImpl·FluentWinUI3·FluentWinUI3StyleImpl·Fusion·FusionStyleImpl·Imagine·ImagineStyleImpl·Impl·Material·MaterialStyleImpl·Native·Universal·UniversalStyleImpl·Windows·WindowsStyleImpl(16개), QuickDialogs2, QuickDialogs2QuickImpl, QuickDialogs2Utils, QuickEffects, QuickLayouts, QuickNativeStyle, QuickParticles, QuickShapes, QuickShapesDesignHelpers, QuickTemplates2, QuickTest, QuickTimeline, QuickTimelineBlendTrees, QuickVectorImage, QuickVectorImageGenerator, QuickVectorImageHelpers, QuickWidgets, Sql, Svg, Test, Widgets
- `pyside6_addons`(58개): 3DAnimation, 3DCore, 3DExtras, 3DInput, 3DLogic, 3DQuick, 3DQuickAnimation, 3DQuickExtras, 3DQuickInput, 3DQuickLogic, 3DQuickRender, 3DQuickScene2D, 3DQuickScene3D, 3DRender, Charts, ChartsQml, DataVisualization, DataVisualizationQml, Graphs, Location, Multimedia, MultimediaQuick, Positioning, PositioningQuick, Quick3D, Quick3DAssetImport, Quick3DAssetUtils, Quick3DEffects, Quick3DHelpers, Quick3DHelpersImpl, Quick3DParticleEffects, Quick3DParticles, Quick3DPhysics, Quick3DPhysicsHelpers, Quick3DRuntimeRender, Quick3DSpatialAudio, Quick3DUtils, Quick3DXr, RemoteObjects, RemoteObjectsQml, Scxml, ScxmlQml, Sensors, SensorsQuick, SerialPort, ShaderTools, SpatialAudio, StateMachine, StateMachineQml, TextToSpeech, VirtualKeyboard, VirtualKeyboardQml, VirtualKeyboardSettings, WebChannel, WebChannelQuick, WebSockets, WebView, WebViewQuick
- `pyside6_webengine`(4개): WebEngineCore, WebEngineQuick, WebEngineQuickDelegatesQml, WebEngineWidgets
- `pyside6_pdf`(2개): Pdf, PdfQuick

이 밖에 `plugins/`(imageformats·platforms·tls 등)와 `qml/` 아래 QML 플러그인이 들어 있다. 전체 목록은 `docs/2026-11-05-packaging/evidence/w6-묶음수집목록.md`에 있다.
버전은 전용 venv에서 `PySide6.__version__`, `QtCore.qVersion()`, `QtWebEngineCore.qWebEngineVersion()`, `qWebEngineChromiumVersion()`(140.0.7339.225), `qWebEngineChromiumSecurityPatchVersion()`(152.0.7977.83)으로 읽었다.
Qt 라이브러리는 개별 DLL 파일로 들어 있다.

## 소스 위치

| 대상 | 위치 |
|---|---|
| PySide6·shiboken6 6.12.0 | https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/ (`pyside-setup-everywhere-src-6.12.0`), Git: https://code.qt.io/cgit/pyside/pyside-setup.git 태그 `v6.12.0` |
| Qt 6.12.0 | https://download.qt.io/official_releases/qt/6.12/6.12.0/single/ (`qt-everywhere-src-6.12.0`), 모듈별: https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/ |
| Qt WebEngine 6.140.0 | Git: https://code.qt.io/cgit/qt/qtwebengine.git 태그 `v6.140.0` |

2026-11-06에 위 위치가 존재하는지 목록 조회로 확인했다(파일은 내려받지 않음).

## 라이선스 원문

- `LGPL-3.0.txt`: GNU Lesser General Public License v3
- `GPL-3.0.txt`: GNU General Public License v3(LGPL v3가 참조하는 본문)
- `LicenseRef-Qt-Commercial.txt`: PySide6 휠에 들어 있는 상용 라이선스 안내문(원문 그대로)
