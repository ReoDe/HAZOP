# W6 첨부 — 배포 묶음 수집 목록(W4 배포용 빌드)

> 대상: `%TEMP%\hazop-w4r2\deploy-build\build\HAZOP\` TOC(읽기 전용), 결과 폴더 `dist\HAZOP\`(3,119개). 2026-11-06 생성.
> 근거 파일 SHA-256: COLLECT-00.toc `4460fa212a71e7e62408715b5013fd15c5d9b4230656ddf2316874e820125c10`, PKG-00.toc `b1d265b8d5761fcd636ea07fb79e54772d5246cf2ef8020203e0696946f9f059`, PYZ-00.toc `475cb790a2c5b455d20f917b65b1f2ca46deda24f3ca1be62a07b5a3bd3421d3`.
> 이 빌드는 licenses/ 추가(D9) 전이다. 고지 판정은 [w6-라이선스.md](w6-라이선스.md) §8.

## 1. 출처·종류별 개수(COLLECT-00.toc)

| 출처 | 종류 | 개수 |
|---|---|---|
| PATH의 다른 프로그램 | BINARY | 45 |
| Python312 | BINARY | 6 |
| Python312 | EXTENSION | 11 |
| venv | BINARY | 284 |
| venv | DATA | 2744 |
| venv | EXTENSION | 14 |
| 빌드·스냅숏 | DATA | 14 |
| 빌드·스냅숏 | EXECUTABLE | 1 |

## 2. venv·Python312·빌드 밖에서 수집된 BINARY(PATH 경유)

| 묶음 안 이름 | 수집 출처 |
|---|---|
| `api-ms-win-core-console-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-console-l1-1-0.dll` |
| `api-ms-win-core-datetime-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-datetime-l1-1-0.dll` |
| `api-ms-win-core-debug-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-debug-l1-1-0.dll` |
| `api-ms-win-core-errorhandling-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-errorhandling-l1-1-0.dll` |
| `api-ms-win-core-fibers-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-fibers-l1-1-0.dll` |
| `api-ms-win-core-fibers-l1-1-1.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-fibers-l1-1-1.dll` |
| `api-ms-win-core-file-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-file-l1-1-0.dll` |
| `api-ms-win-core-file-l1-2-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-file-l1-2-0.dll` |
| `api-ms-win-core-file-l2-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-file-l2-1-0.dll` |
| `api-ms-win-core-handle-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-handle-l1-1-0.dll` |
| `api-ms-win-core-heap-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-heap-l1-1-0.dll` |
| `api-ms-win-core-interlocked-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-interlocked-l1-1-0.dll` |
| `api-ms-win-core-kernel32-legacy-l1-1-1.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-kernel32-legacy-l1-1-1.dll` |
| `api-ms-win-core-libraryloader-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-libraryloader-l1-1-0.dll` |
| `api-ms-win-core-localization-l1-2-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-localization-l1-2-0.dll` |
| `api-ms-win-core-memory-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-memory-l1-1-0.dll` |
| `api-ms-win-core-namedpipe-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-namedpipe-l1-1-0.dll` |
| `api-ms-win-core-processenvironment-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-processenvironment-l1-1-0.dll` |
| `api-ms-win-core-processthreads-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-processthreads-l1-1-0.dll` |
| `api-ms-win-core-processthreads-l1-1-1.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-processthreads-l1-1-1.dll` |
| `api-ms-win-core-profile-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-profile-l1-1-0.dll` |
| `api-ms-win-core-rtlsupport-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-rtlsupport-l1-1-0.dll` |
| `api-ms-win-core-string-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-string-l1-1-0.dll` |
| `api-ms-win-core-synch-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-synch-l1-1-0.dll` |
| `api-ms-win-core-synch-l1-2-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-synch-l1-2-0.dll` |
| `api-ms-win-core-sysinfo-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-sysinfo-l1-1-0.dll` |
| `api-ms-win-core-sysinfo-l1-2-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-sysinfo-l1-2-0.dll` |
| `api-ms-win-core-timezone-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-timezone-l1-1-0.dll` |
| `api-ms-win-core-util-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-core-util-l1-1-0.dll` |
| `api-ms-win-crt-conio-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-conio-l1-1-0.dll` |
| `api-ms-win-crt-convert-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-convert-l1-1-0.dll` |
| `api-ms-win-crt-environment-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-environment-l1-1-0.dll` |
| `api-ms-win-crt-filesystem-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-filesystem-l1-1-0.dll` |
| `api-ms-win-crt-heap-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-heap-l1-1-0.dll` |
| `api-ms-win-crt-locale-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-locale-l1-1-0.dll` |
| `api-ms-win-crt-math-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-math-l1-1-0.dll` |
| `api-ms-win-crt-process-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-process-l1-1-0.dll` |
| `api-ms-win-crt-runtime-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-runtime-l1-1-0.dll` |
| `api-ms-win-crt-stdio-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-stdio-l1-1-0.dll` |
| `api-ms-win-crt-string-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-string-l1-1-0.dll` |
| `api-ms-win-crt-time-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-time-l1-1-0.dll` |
| `api-ms-win-crt-utility-l1-1-0.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\api-ms-win-crt-utility-l1-1-0.dll` |
| `libcrypto-3-x64.dll` | `C:\Program Files\Git\mingw64\bin\libcrypto-3-x64.dll` |
| `libssl-3-x64.dll` | `C:\Program Files\Git\mingw64\bin\libssl-3-x64.dll` |
| `ucrtbase.dll` | `C:\Users\kim92\AppData\Local\Programs\Java\jdk-25.0.4.1+1\bin\ucrtbase.dll` |

## 3. 바이너리 전체(EXECUTABLE·EXTENSION·BINARY, 출처 요약)

| 묶음 안 이름 | 종류 | 출처 |
|---|---|---|
| `HAZOP.exe` | EXECUTABLE | 빌드·스냅숏 |
| `PySide6\MSVCP140.dll` | BINARY | venv |
| `PySide6\MSVCP140_1.dll` | BINARY | venv |
| `PySide6\MSVCP140_2.dll` | BINARY | venv |
| `PySide6\Qt63DAnimation.dll` | BINARY | venv |
| `PySide6\Qt63DCore.dll` | BINARY | venv |
| `PySide6\Qt63DExtras.dll` | BINARY | venv |
| `PySide6\Qt63DInput.dll` | BINARY | venv |
| `PySide6\Qt63DLogic.dll` | BINARY | venv |
| `PySide6\Qt63DQuick.dll` | BINARY | venv |
| `PySide6\Qt63DQuickAnimation.dll` | BINARY | venv |
| `PySide6\Qt63DQuickExtras.dll` | BINARY | venv |
| `PySide6\Qt63DQuickInput.dll` | BINARY | venv |
| `PySide6\Qt63DQuickLogic.dll` | BINARY | venv |
| `PySide6\Qt63DQuickRender.dll` | BINARY | venv |
| `PySide6\Qt63DQuickScene2D.dll` | BINARY | venv |
| `PySide6\Qt63DQuickScene3D.dll` | BINARY | venv |
| `PySide6\Qt63DRender.dll` | BINARY | venv |
| `PySide6\Qt6Charts.dll` | BINARY | venv |
| `PySide6\Qt6ChartsQml.dll` | BINARY | venv |
| `PySide6\Qt6Concurrent.dll` | BINARY | venv |
| `PySide6\Qt6Core.dll` | BINARY | venv |
| `PySide6\Qt6DataVisualization.dll` | BINARY | venv |
| `PySide6\Qt6DataVisualizationQml.dll` | BINARY | venv |
| `PySide6\Qt6Graphs.dll` | BINARY | venv |
| `PySide6\Qt6Gui.dll` | BINARY | venv |
| `PySide6\Qt6LabsAnimation.dll` | BINARY | venv |
| `PySide6\Qt6LabsFolderListModel.dll` | BINARY | venv |
| `PySide6\Qt6LabsPlatform.dll` | BINARY | venv |
| `PySide6\Qt6LabsQmlModels.dll` | BINARY | venv |
| `PySide6\Qt6LabsSettings.dll` | BINARY | venv |
| `PySide6\Qt6LabsSharedImage.dll` | BINARY | venv |
| `PySide6\Qt6LabsStyleKit.dll` | BINARY | venv |
| `PySide6\Qt6LabsStyleKitImpl.dll` | BINARY | venv |
| `PySide6\Qt6LabsSynchronizer.dll` | BINARY | venv |
| `PySide6\Qt6LabsWavefrontMesh.dll` | BINARY | venv |
| `PySide6\Qt6Location.dll` | BINARY | venv |
| `PySide6\Qt6Multimedia.dll` | BINARY | venv |
| `PySide6\Qt6MultimediaQuick.dll` | BINARY | venv |
| `PySide6\Qt6Network.dll` | BINARY | venv |
| `PySide6\Qt6OpenGL.dll` | BINARY | venv |
| `PySide6\Qt6OpenGLWidgets.dll` | BINARY | venv |
| `PySide6\Qt6Pdf.dll` | BINARY | venv |
| `PySide6\Qt6PdfQuick.dll` | BINARY | venv |
| `PySide6\Qt6Positioning.dll` | BINARY | venv |
| `PySide6\Qt6PositioningQuick.dll` | BINARY | venv |
| `PySide6\Qt6PrintSupport.dll` | BINARY | venv |
| `PySide6\Qt6Qml.dll` | BINARY | venv |
| `PySide6\Qt6QmlCore.dll` | BINARY | venv |
| `PySide6\Qt6QmlDesignSupport.dll` | BINARY | venv |
| `PySide6\Qt6QmlLocalStorage.dll` | BINARY | venv |
| `PySide6\Qt6QmlMeta.dll` | BINARY | venv |
| `PySide6\Qt6QmlModels.dll` | BINARY | venv |
| `PySide6\Qt6QmlNetwork.dll` | BINARY | venv |
| `PySide6\Qt6QmlWorkerScript.dll` | BINARY | venv |
| `PySide6\Qt6QmlXmlListModel.dll` | BINARY | venv |
| `PySide6\Qt6Quick.dll` | BINARY | venv |
| `PySide6\Qt6Quick3D.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DAssetImport.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DAssetUtils.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DEffects.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DHelpers.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DHelpersImpl.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DParticleEffects.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DParticles.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DPhysics.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DPhysicsHelpers.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DRuntimeRender.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DSpatialAudio.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DUtils.dll` | BINARY | venv |
| `PySide6\Qt6Quick3DXr.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Basic.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2BasicStyleImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2FluentWinUI3.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2FluentWinUI3StyleImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Fusion.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2FusionStyleImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Imagine.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2ImagineStyleImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Impl.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Material.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2MaterialStyleImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Native.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Universal.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2UniversalStyleImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2Windows.dll` | BINARY | venv |
| `PySide6\Qt6QuickControls2WindowsStyleImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickDialogs2.dll` | BINARY | venv |
| `PySide6\Qt6QuickDialogs2QuickImpl.dll` | BINARY | venv |
| `PySide6\Qt6QuickDialogs2Utils.dll` | BINARY | venv |
| `PySide6\Qt6QuickEffects.dll` | BINARY | venv |
| `PySide6\Qt6QuickLayouts.dll` | BINARY | venv |
| `PySide6\Qt6QuickNativeStyle.dll` | BINARY | venv |
| `PySide6\Qt6QuickParticles.dll` | BINARY | venv |
| `PySide6\Qt6QuickShapes.dll` | BINARY | venv |
| `PySide6\Qt6QuickShapesDesignHelpers.dll` | BINARY | venv |
| `PySide6\Qt6QuickTemplates2.dll` | BINARY | venv |
| `PySide6\Qt6QuickTest.dll` | BINARY | venv |
| `PySide6\Qt6QuickTimeline.dll` | BINARY | venv |
| `PySide6\Qt6QuickTimelineBlendTrees.dll` | BINARY | venv |
| `PySide6\Qt6QuickVectorImage.dll` | BINARY | venv |
| `PySide6\Qt6QuickVectorImageGenerator.dll` | BINARY | venv |
| `PySide6\Qt6QuickVectorImageHelpers.dll` | BINARY | venv |
| `PySide6\Qt6QuickWidgets.dll` | BINARY | venv |
| `PySide6\Qt6RemoteObjects.dll` | BINARY | venv |
| `PySide6\Qt6RemoteObjectsQml.dll` | BINARY | venv |
| `PySide6\Qt6Scxml.dll` | BINARY | venv |
| `PySide6\Qt6ScxmlQml.dll` | BINARY | venv |
| `PySide6\Qt6Sensors.dll` | BINARY | venv |
| `PySide6\Qt6SensorsQuick.dll` | BINARY | venv |
| `PySide6\Qt6SerialPort.dll` | BINARY | venv |
| `PySide6\Qt6ShaderTools.dll` | BINARY | venv |
| `PySide6\Qt6SpatialAudio.dll` | BINARY | venv |
| `PySide6\Qt6Sql.dll` | BINARY | venv |
| `PySide6\Qt6StateMachine.dll` | BINARY | venv |
| `PySide6\Qt6StateMachineQml.dll` | BINARY | venv |
| `PySide6\Qt6Svg.dll` | BINARY | venv |
| `PySide6\Qt6Test.dll` | BINARY | venv |
| `PySide6\Qt6TextToSpeech.dll` | BINARY | venv |
| `PySide6\Qt6VirtualKeyboard.dll` | BINARY | venv |
| `PySide6\Qt6VirtualKeyboardQml.dll` | BINARY | venv |
| `PySide6\Qt6VirtualKeyboardSettings.dll` | BINARY | venv |
| `PySide6\Qt6WebChannel.dll` | BINARY | venv |
| `PySide6\Qt6WebChannelQuick.dll` | BINARY | venv |
| `PySide6\Qt6WebEngineCore.dll` | BINARY | venv |
| `PySide6\Qt6WebEngineQuick.dll` | BINARY | venv |
| `PySide6\Qt6WebEngineQuickDelegatesQml.dll` | BINARY | venv |
| `PySide6\Qt6WebEngineWidgets.dll` | BINARY | venv |
| `PySide6\Qt6WebSockets.dll` | BINARY | venv |
| `PySide6\Qt6WebView.dll` | BINARY | venv |
| `PySide6\Qt6WebViewQuick.dll` | BINARY | venv |
| `PySide6\Qt6Widgets.dll` | BINARY | venv |
| `PySide6\QtCore.pyd` | EXTENSION | venv |
| `PySide6\QtGui.pyd` | EXTENSION | venv |
| `PySide6\QtNetwork.pyd` | EXTENSION | venv |
| `PySide6\QtOpenGL.pyd` | EXTENSION | venv |
| `PySide6\QtPositioning.pyd` | EXTENSION | venv |
| `PySide6\QtPrintSupport.pyd` | EXTENSION | venv |
| `PySide6\QtQml.pyd` | EXTENSION | venv |
| `PySide6\QtQuick.pyd` | EXTENSION | venv |
| `PySide6\QtQuickWidgets.pyd` | EXTENSION | venv |
| `PySide6\QtWebChannel.pyd` | EXTENSION | venv |
| `PySide6\QtWebEngineCore.pyd` | EXTENSION | venv |
| `PySide6\QtWebEngineProcess.exe` | BINARY | venv |
| `PySide6\QtWebEngineWidgets.pyd` | EXTENSION | venv |
| `PySide6\QtWidgets.pyd` | EXTENSION | venv |
| `PySide6\VCRUNTIME140.dll` | BINARY | venv |
| `PySide6\VCRUNTIME140_1.dll` | BINARY | venv |
| `PySide6\opengl32sw.dll` | BINARY | venv |
| `PySide6\plugins\generic\qtuiotouchplugin.dll` | BINARY | venv |
| `PySide6\plugins\iconengines\qsvgicon.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qgif.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qicns.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qico.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qjpeg.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qpdf.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qsvg.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qtga.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qtiff.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qwbmp.dll` | BINARY | venv |
| `PySide6\plugins\imageformats\qwebp.dll` | BINARY | venv |
| `PySide6\plugins\networkinformation\qnetworklistmanager.dll` | BINARY | venv |
| `PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll` | BINARY | venv |
| `PySide6\plugins\platforms\qdirect2d.dll` | BINARY | venv |
| `PySide6\plugins\platforms\qminimal.dll` | BINARY | venv |
| `PySide6\plugins\platforms\qoffscreen.dll` | BINARY | venv |
| `PySide6\plugins\platforms\qwindows.dll` | BINARY | venv |
| `PySide6\plugins\position\qtposition_nmea.dll` | BINARY | venv |
| `PySide6\plugins\position\qtposition_positionpoll.dll` | BINARY | venv |
| `PySide6\plugins\position\qtposition_winrt.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_debugger.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_inspector.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_local.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_messages.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_native.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_nativedebugger.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_preview.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_profiler.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_quick3dprofiler.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_quickeventreplay.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_quickprofiler.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_server.dll` | BINARY | venv |
| `PySide6\plugins\qmltooling\qmldbg_tcp.dll` | BINARY | venv |
| `PySide6\plugins\styles\qmodernwindowsstyle.dll` | BINARY | venv |
| `PySide6\plugins\tls\qcertonlybackend.dll` | BINARY | venv |
| `PySide6\plugins\tls\qopensslbackend.dll` | BINARY | venv |
| `PySide6\plugins\tls\qschannelbackend.dll` | BINARY | venv |
| `PySide6\pyside6.abi3.dll` | BINARY | venv |
| `PySide6\pyside6qml.abi3.dll` | BINARY | venv |
| `PySide6\qml\Qt3D\Animation\quick3danimationplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt3D\Core\quick3dcoreplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt3D\Extras\quick3dextrasplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt3D\Input\quick3dinputplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt3D\Logic\quick3dlogicplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt3D\Render\quick3drenderplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt5Compat\GraphicalEffects\private\qtgraphicaleffectsprivateplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt5Compat\GraphicalEffects\qtgraphicaleffectsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtCharts\qtchartsqml2plugin.dll` | BINARY | venv |
| `PySide6\qml\QtCore\qtqmlcoreplugin.dll` | BINARY | venv |
| `PySide6\qml\QtDataVisualization\datavisualizationqmlplugin.dll` | BINARY | venv |
| `PySide6\qml\QtGraphs\graphsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtLocation\declarative_locationplugin.dll` | BINARY | venv |
| `PySide6\qml\QtMultimedia\quickmultimediaplugin.dll` | BINARY | venv |
| `PySide6\qml\QtNetwork\qmlnetworkplugin.dll` | BINARY | venv |
| `PySide6\qml\QtPositioning\positioningquickplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQml\DesignSupport\qmldesignsupportplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQml\Models\modelsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQml\StateMachine\qtqmlstatemachineplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQml\WorkerScript\workerscriptplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQml\XmlListModel\qmlxmllistmodelplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQml\qmlplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\AssetUtils\qtquick3dassetutilsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\Effects\qtquick3deffectplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\Helpers\impl\qtquick3dhelpersimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\Helpers\qtquick3dhelpersplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\ParticleEffects\qtquick3dparticleeffectsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\Particles3D\qtquick3dparticles3dplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\Physics\Helpers\qtquick3dphysicshelpersplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\Physics\qquick3dphysicsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\SpatialAudio\quick3dspatialaudioplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\Xr\quick3dxrplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick3D\qquick3dplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Basic\impl\qtquickcontrols2basicstyleimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Basic\qtquickcontrols2basicstyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\FluentWinUI3\impl\qtquickcontrols2fluentwinui3styleimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\FluentWinUI3\qtquickcontrols2fluentwinui3styleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Fusion\impl\qtquickcontrols2fusionstyleimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Fusion\qtquickcontrols2fusionstyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Imagine\impl\qtquickcontrols2imaginestyleimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Imagine\qtquickcontrols2imaginestyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Material\impl\qtquickcontrols2materialstyleimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Material\qtquickcontrols2materialstyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Native\qtquickcontrols2nativestyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Universal\impl\qtquickcontrols2universalstyleimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Universal\qtquickcontrols2universalstyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Windows\impl\qtquickcontrols2windowsstyleimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\Windows\qtquickcontrols2windowsstyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\impl\qtquickcontrols2implplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Controls\qtquickcontrols2plugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Dialogs\qtquickdialogsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Dialogs\quickimpl\qtquickdialogs2quickimplplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Effects\effectsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Layouts\qquicklayoutsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\LocalStorage\qmllocalstorageplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\NativeStyle\qtquicknativestyleplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Particles\particlesplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Pdf\pdfquickplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Scene2D\qtquickscene2dplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Scene3D\qtquickscene3dplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Shapes\DesignHelpers\qtquickshapesdesignhelpersplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Shapes\qmlshapesplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Templates\qtquicktemplates2plugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Timeline\BlendTrees\qtquicktimelineblendtreesplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Timeline\qtquicktimelineplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VectorImage\Helpers\qquickvectorimagehelpersplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VectorImage\qquickvectorimageplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Components\qtvkbcomponentsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Core\virtualkeyboardplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Layouts\qtvkblayoutsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Plugins\Hangul\qtvkbhangulplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Plugins\OpenWNN\qtvkbopenwnnplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Plugins\Pinyin\qtvkbpinyinplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Plugins\TCIme\qtvkbtcimeplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Plugins\Thai\qtvkbthaiplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Plugins\qtvkbpluginsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Settings\qtvkbsettingsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Styles\Builtin\qtvkbbuiltinstylesplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\Styles\qtvkbstylesplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\VirtualKeyboard\qtvkbplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\Window\quickwindowplugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\qtquick2plugin.dll` | BINARY | venv |
| `PySide6\qml\QtQuick\tooling\quicktoolingplugin.dll` | BINARY | venv |
| `PySide6\qml\QtRemoteObjects\declarative_remoteobjectsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtScxml\declarative_scxmlplugin.dll` | BINARY | venv |
| `PySide6\qml\QtSensors\sensorsquickplugin.dll` | BINARY | venv |
| `PySide6\qml\QtTest\quicktestplugin.dll` | BINARY | venv |
| `PySide6\qml\QtTextToSpeech\texttospeechqmlplugin.dll` | BINARY | venv |
| `PySide6\qml\QtWebChannel\webchannelquickplugin.dll` | BINARY | venv |
| `PySide6\qml\QtWebEngine\ControlsDelegates\qtwebenginequickdelegatesplugin.dll` | BINARY | venv |
| `PySide6\qml\QtWebEngine\qtwebenginequickplugin.dll` | BINARY | venv |
| `PySide6\qml\QtWebSockets\qmlwebsocketsplugin.dll` | BINARY | venv |
| `PySide6\qml\QtWebView\qtwebviewquickplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\StyleKit\impl\labsstylekitimplplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\StyleKit\labsstylekitplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\animation\labsanimationplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\folderlistmodel\qmlfolderlistmodelplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\platform\labsplatformplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\qmlmodels\labsmodelsplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\settings\qmlsettingsplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\sharedimage\sharedimageplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\synchronizer\labssynchronizerplugin.dll` | BINARY | venv |
| `PySide6\qml\Qt\labs\wavefrontmesh\qmlwavefrontmeshplugin.dll` | BINARY | venv |
| `VCRUNTIME140.dll` | BINARY | Python312 |
| `VCRUNTIME140_1.dll` | BINARY | Python312 |
| `_bz2.pyd` | EXTENSION | Python312 |
| `_decimal.pyd` | EXTENSION | Python312 |
| `_elementtree.pyd` | EXTENSION | Python312 |
| `_hashlib.pyd` | EXTENSION | Python312 |
| `_lzma.pyd` | EXTENSION | Python312 |
| `_queue.pyd` | EXTENSION | Python312 |
| `_socket.pyd` | EXTENSION | Python312 |
| `_ssl.pyd` | EXTENSION | Python312 |
| `libcrypto-3.dll` | BINARY | Python312 |
| `libssl-3.dll` | BINARY | Python312 |
| `pyexpat.pyd` | EXTENSION | Python312 |
| `python3.dll` | BINARY | Python312 |
| `python312.dll` | BINARY | Python312 |
| `select.pyd` | EXTENSION | Python312 |
| `shiboken6\MSVCP140.dll` | BINARY | venv |
| `shiboken6\MSVCP140_1.dll` | BINARY | venv |
| `shiboken6\Shiboken.pyd` | EXTENSION | venv |
| `shiboken6\VCRUNTIME140.dll` | BINARY | venv |
| `shiboken6\VCRUNTIME140_1.dll` | BINARY | venv |
| `shiboken6\shiboken6.abi3.dll` | BINARY | venv |
| `unicodedata.pyd` | EXTENSION | Python312 |

## 4. DATA 폴더별 개수(3단계까지)

| 폴더 | 개수 |
|---|---|
| `.` | 1 |
| `PySide6` | 1 |
| `PySide6/qml/Qt` | 78 |
| `PySide6/qml/Qt3D` | 12 |
| `PySide6/qml/Qt5Compat` | 36 |
| `PySide6/qml/QtCharts` | 52 |
| `PySide6/qml/QtCore` | 2 |
| `PySide6/qml/QtDataVisualization` | 15 |
| `PySide6/qml/QtGraphs` | 37 |
| `PySide6/qml/QtLocation` | 3 |
| `PySide6/qml/QtMultimedia` | 3 |
| `PySide6/qml/QtNetwork` | 2 |
| `PySide6/qml/QtPositioning` | 2 |
| `PySide6/qml/QtQml` | 12 |
| `PySide6/qml/QtQuick` | 1610 |
| `PySide6/qml/QtQuick3D` | 615 |
| `PySide6/qml/QtRemoteObjects` | 2 |
| `PySide6/qml/QtScxml` | 2 |
| `PySide6/qml/QtSensors` | 2 |
| `PySide6/qml/QtTest` | 6 |
| `PySide6/qml/QtTextToSpeech` | 2 |
| `PySide6/qml/QtWebChannel` | 2 |
| `PySide6/qml/QtWebEngine` | 18 |
| `PySide6/qml/QtWebSockets` | 2 |
| `PySide6/qml/QtWebView` | 2 |
| `PySide6/resources` | 11 |
| `PySide6/translations` | 163 |
| `PySide6/translations/qtwebengine_locales` | 53 |
| `hazop/kg` | 1 |
| `hazop/kg/vendor` | 3 |
| `hazop/viewer` | 1 |
| `scripts` | 2 |
| `기획서` | 1 |
| `데이터/기준표` | 1 |
| `데이터/이탈후보` | 2 |
| `데이터/패턴` | 1 |

## 5. PKG-00.toc(실행 파일 안 항목)

- `pyi-contents-directory _internal` (OPTION)
- `PYZ-00.pyz` (PYZ)
- `struct` (PYMODULE)
- `pyimod01_archive` (PYMODULE)
- `pyimod02_importers` (PYMODULE)
- `pyimod03_ctypes` (PYMODULE)
- `pyimod04_pywin32` (PYMODULE)
- `pyiboot01_bootstrap` (PYSOURCE)
- `rthook_applog` (PYSOURCE)
- `pyi_rth_inspect` (PYSOURCE)
- `pyi_rth_pyside6` (PYSOURCE)
- `run_app` (PYSOURCE)

## 6. PYZ-00.toc 최상위 모듈·패키지(679개 모듈)

`PySide6`, `__future__`, `_compat_pickle`, `_compression`, `_markupbase`, `_py_abc`, `_pydatetime`, `_pydecimal`, `_pyi_rth_utils`, `_strptime`, `_threading_local`, `argparse`, `ast`, `base64`, `bisect`, `build_graph`, `bz2`, `calendar`, `contextlib`, `contextvars`, `copy`, `csv`, `dataclasses`, `datetime`, `decimal`, `difflib`, `dis`, `email`, `et_xmlfile`, `extract_drawio`, `fnmatch`, `fractions`, `ftplib`, `getopt`, `getpass`, `gettext`, `glob`, `gzip`, `hashlib`, `hazop`, `html`, `http`, `importlib`, `inspect`, `ipaddress`, `json`, `logging`, `lzma`, `mimetypes`, `netrc`, `networkx`, `nturl2path`, `numbers`, `opcode`, `openpyxl`, `pathlib`, `pickle`, `pprint`, `py_compile`, `queue`, `quopri`, `random`, `selectors`, `shiboken6`, `shlex`, `shutil`, `signal`, `socket`, `ssl`, `statistics`, `string`, `stringprep`, `subprocess`, `tarfile`, `tempfile`, `textwrap`, `threading`, `token`, `tokenize`, `tracemalloc`, `typing`, `urllib`, `xml`, `zipfile`
