# 제3자 라이선스 고지

이 폴더는 HAZOP 배포본(PyInstaller one-folder)에 들어가는 제3자 구성요소의 라이선스 원문과 고지 위치를 모은다.
빌드할 때 `scripts/build_package.py`가 이 폴더를 묶음의 `_internal/licenses/`에 넣는다(T2 D9).

- 작성: 2026-11-06, T2 `W6`(고지 초안). 근거와 수집 과정: `docs/2026-11-05-packaging/evidence/w6-라이선스.md`
- 버전: Python 패키지·Qt는 빌드에 쓴 전용 venv의 설치 버전(`packaging/requirements*.txt` 고정)이고, force-graph는 `hazop/kg/vendor/force-graph-1.52.0/`의 버전이다. force-graph 간접 의존성의 버전은 확인할 수 없어 추정값이다([주2]).
- 원문 파일은 출처의 바이트 그대로 복사했다(`.gitattributes`로 줄 끝 변환을 막음). 아래 SHA-256과 다르면 `tests/test_packaging.py`가 실패한다.
- 이 목록은 고지 자료의 정리이며 라이선스 의무 충족 여부에 대한 법적 판단이 아니다. 아직 원문이 없는 묶음 구성요소와 사용자 확인 항목은 근거 문서 §8·§9에 있다.

## Qt 구성요소(배포 패키지 기준)

| 휠 | 버전 | 묶음에 들어간 것 |
|---|---|---|
| `pyside6`(PySide6 바인딩) | 6.12.0 | 바인딩 공통 DLL(`pyside6.abi3.dll`·`pyside6qml.abi3.dll`) |
| `pyside6_essentials` | 6.12.0 | 바인딩 .pyd 9개, Qt 모듈 DLL 65개 |
| `pyside6_addons` | 6.12.0 | 바인딩 .pyd 2개, Qt 모듈 DLL 58개 |
| `pyside6_webengine` | 6.12.0.140 | 바인딩 .pyd 2개, Qt WebEngine 6.140.0(Chromium 140.0.7339.225) |
| `pyside6_pdf` | 6.12.0.140 | Qt 모듈 DLL 2개(Qt6Pdf·Qt6PdfQuick) |
| `shiboken6` | 6.12.0 | `shiboken6/` |

휠 메타데이터의 라이선스 표기는 모두 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`다. 그러나 Qt 오픈소스판은 모듈마다 라이선스가 다를 수 있다(일부 모듈은 GPL 전용) [일반지식]. 모듈 목록과 소스 위치는 `qt/QT-SOURCE.md`에 있다.

## 고지 목록

"수정" 열은 묶음에 들어간 구성요소를 원본에서 바꿨는지 표시한다(근거는 [주6]·[주7]과 근거 문서 §5).

| 구성요소 | 버전 | 라이선스 | 수정 | 원문 파일 | 출처 | SHA-256 |
|---|---|---|---|---|---|---|
| PySide6 바인딩·shiboken6·Qt 모듈 | 6.12.0 [주5] | LGPL-3.0-only | 미수정(RECORD 대조) | `qt/LGPL-3.0.txt` | 로컬 사본(Git for Windows `mingw64/share/licenses/libunistring/LICENSE.LIB`) [주1] | `a853c2ffec17057872340eee242ae4d96cbf2b520ae27d903e1b2fef1a5f9d1c` |
| PySide6 바인딩·shiboken6·Qt 모듈 | 6.12.0 [주5] | GPL-3.0-only | 미수정(RECORD 대조) | `qt/GPL-3.0.txt` | 로컬 사본(Git for Windows `mingw64/share/licenses/libtasn1/COPYING`) [주1] | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` |
| PySide6 바인딩·shiboken6·Qt 모듈 | 6.12.0 [주5] | LicenseRef-Qt-Commercial | 미수정(RECORD 대조) | `qt/LicenseRef-Qt-Commercial.txt` | 전용 venv `site-packages/pyside6-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt` | `4f54763ac0fe2abd8f7f8d8fe370a94a08ebf84786aa0b91045bd6628deb08a3` |
| Qt 구성요소·소스 위치 | Qt 6.12.0, Qt WebEngine 6.140.0 | - | - | `qt/QT-SOURCE.md` | 이 저장소 작성 | `1eca25e6a041631d5a176cb62f05668d58fd3c58bfeb83102f79a93ea77cd53e` |
| Qt WebEngine 제3자(Chromium 140.0.7339.225) | 6.140.0 | 목록 위치 | 미수정(RECORD 대조) | `qt/QTWEBENGINE-THIRD-PARTY.md` | 이 저장소 작성 | `e89d191d5138095a71bb6825c95156e314337497cf0ce9259c1d561bcef63244` |
| CPython | 3.12.10 | PSF-2.0 | 미확인(설치 원본은 해시 일치) [주6] | `python/CPython-LICENSE.txt` | python.org CPython 3.12.10 설치 폴더 `LICENSE.txt`(전용 venv의 기반 인터프리터) | `e502c6b880ff58d614901495a9009c136539cd0b1e2a2abb8fc00b934c203419` |
| CPython 포함 소프트웨어(OpenSSL·expat·libffi·zlib·libmpdec 등) | 3.12.10 | 구성요소별(파일 안) | 미확인(설치 원본은 해시 일치) [주6] | `python/CPython-license-acknowledgements.rst.txt` | 같은 설치 폴더 `Doc/html/_sources/license.rst.txt` | `40e3623b07603a84c5993c0726c54a523511284110f22e5bb827c005edeb1bd8` |
| networkx | 3.7 | BSD-3-Clause | 미수정(RECORD 대조) | `python/networkx-LICENSE.txt` | 전용 venv `site-packages/networkx-3.7.dist-info/licenses/LICENSE.txt` | `6025f323ea29dc2f0ee0abd9523bf910186f55b0e148e6ebf646c55566278e2e` |
| openpyxl | 3.1.5 | MIT | 미수정(RECORD 대조) | `python/openpyxl-LICENCE.rst` | 전용 venv `site-packages/openpyxl-3.1.5.dist-info/LICENCE.rst` | `0c84bb42f5d367e5ebf9fc2dde35b16141df5ee0fdc189250858bc6c5560f69e` |
| et_xmlfile | 2.0.0 | MIT | 미수정(RECORD 대조) | `python/et_xmlfile-LICENCE.rst` | 전용 venv `site-packages/et_xmlfile-2.0.0.dist-info/LICENCE.rst` | `0c84bb42f5d367e5ebf9fc2dde35b16141df5ee0fdc189250858bc6c5560f69e` |
| et_xmlfile(표준 라이브러리 유래 부분) | 2.0.0 | PSF-2.0 | 미수정(RECORD 대조) | `python/et_xmlfile-LICENCE.python` | 전용 venv `site-packages/et_xmlfile-2.0.0.dist-info/LICENCE.python` | `4ccdaaebc0f44b83720ec0399bb7ab329adce067dd62f73c5535a2dc05628ab2` |
| PyInstaller 부트로더·런타임 | 6.22.3 | GPL-2.0-or-later WITH Bootloader-exception | 미수정(RECORD 대조) | `pyinstaller/COPYING.txt` | 전용 venv `site-packages/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt` | `0598064c7d2718e38d7914a7d08343b2fa008e3bea9ebba2aa7a6ffa5900dd64` |
| force-graph | 1.52.0(vendor) | MIT | 미수정(SOURCE.md 해시 일치) [주7] | `force-graph/force-graph-LICENSE` | `hazop/kg/vendor/force-graph-1.52.0/LICENSE`(SOURCE.md: jsDelivr npm 경로) | `5b6dc9ce44c7b73620b191c567339212bd00537af46fdedaf98304c34214cc9c` |
| accessor-fn | 1.5.3(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/accessor-fn-LICENSE` | https://cdn.jsdelivr.net/npm/accessor-fn@1.5.3/LICENSE | `7262e566e874d1ce8cfadace01d4f635f8d704b6bdf7b4345cc028e5faeafded` |
| bezier-js | 6.1.4(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/bezier-js-LICENSE.md` | https://raw.githubusercontent.com/Pomax/bezierjs/4e767299184ab4079dc8d7c970020103db14f431/LICENSE.md [주3] | `4fb7b04152f7b3a7c48c98c638aba80fc1f221e915d605d45d016d87d8e2cc9f` |
| canvas-color-tracker | 1.3.2(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/canvas-color-tracker-LICENSE` | https://cdn.jsdelivr.net/npm/canvas-color-tracker@1.3.2/LICENSE | `5b6dc9ce44c7b73620b191c567339212bd00537af46fdedaf98304c34214cc9c` |
| d3-array | 3.2.4(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-array-LICENSE` | https://cdn.jsdelivr.net/npm/d3-array@3.2.4/LICENSE | `3e6849627f74ff73c257a3ae1efb574015d94fc1035c05ec3c15805165efcbc4` |
| d3-binarytree | 1.0.2(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-binarytree-LICENSE` | https://cdn.jsdelivr.net/npm/d3-binarytree@1.0.2/LICENSE | `7262e566e874d1ce8cfadace01d4f635f8d704b6bdf7b4345cc028e5faeafded` |
| d3-color | 3.1.0(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-color-LICENSE` | https://cdn.jsdelivr.net/npm/d3-color@3.1.0/LICENSE | `faa682e3e430941f958d26180458f5934a62f58dac4d70ccdd15608c15d0f884` |
| d3-dispatch | 3.0.1(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-dispatch-LICENSE` | https://cdn.jsdelivr.net/npm/d3-dispatch@3.0.1/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-drag | 3.0.0(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-drag-LICENSE` | https://cdn.jsdelivr.net/npm/d3-drag@3.0.0/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-ease | 3.0.1(추정) [주2] | BSD-3-Clause | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-ease-LICENSE` | https://cdn.jsdelivr.net/npm/d3-ease@3.0.1/LICENSE | `b989d9085148d21ff64a75e14462aefa06b2589a55553b07b1460c70081c7d08` |
| d3-force-3d | 3.0.6(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-force-3d-LICENSE` | https://cdn.jsdelivr.net/npm/d3-force-3d@3.0.6/LICENSE | `7262e566e874d1ce8cfadace01d4f635f8d704b6bdf7b4345cc028e5faeafded` |
| d3-format | 3.1.2(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-format-LICENSE` | https://cdn.jsdelivr.net/npm/d3-format@3.1.2/LICENSE | `2a6d2d5f32ba0b755ddbc1c833f766e30cdbe6ebe9a6d4e3e24427721f0b63d3` |
| d3-interpolate | 3.0.1(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-interpolate-LICENSE` | https://cdn.jsdelivr.net/npm/d3-interpolate@3.0.1/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-octree | 1.1.0(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-octree-LICENSE` | https://cdn.jsdelivr.net/npm/d3-octree@1.1.0/LICENSE | `7262e566e874d1ce8cfadace01d4f635f8d704b6bdf7b4345cc028e5faeafded` |
| d3-quadtree | 3.0.1(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-quadtree-LICENSE` | https://cdn.jsdelivr.net/npm/d3-quadtree@3.0.1/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-scale | 4.0.2(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-scale-LICENSE` | https://cdn.jsdelivr.net/npm/d3-scale@4.0.2/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-scale-chromatic | 3.1.0(추정) [주2] | ISC AND Apache-2.0 | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-scale-chromatic-LICENSE` | https://cdn.jsdelivr.net/npm/d3-scale-chromatic@3.1.0/LICENSE | `0986d93944902cca9af86824b6a641b4b7c2d10602fc510c433a8bcd443919fe` |
| d3-selection | 3.0.0(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-selection-LICENSE` | https://cdn.jsdelivr.net/npm/d3-selection@3.0.0/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-time | 3.1.0(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-time-LICENSE` | https://cdn.jsdelivr.net/npm/d3-time@3.1.0/LICENSE | `faa682e3e430941f958d26180458f5934a62f58dac4d70ccdd15608c15d0f884` |
| d3-time-format | 4.1.0(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-time-format-LICENSE` | https://cdn.jsdelivr.net/npm/d3-time-format@4.1.0/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-timer | 3.0.1(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-timer-LICENSE` | https://cdn.jsdelivr.net/npm/d3-timer@3.0.1/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-transition | 3.0.1(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-transition-LICENSE` | https://cdn.jsdelivr.net/npm/d3-transition@3.0.1/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| d3-zoom | 3.0.0(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/d3-zoom-LICENSE` | https://cdn.jsdelivr.net/npm/d3-zoom@3.0.0/LICENSE | `e008c5e25a6be382593089c29bfabbc553c6378eee02895aec46ce396cc404ee` |
| float-tooltip | 1.7.5(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/float-tooltip-LICENSE` | https://cdn.jsdelivr.net/npm/float-tooltip@1.7.5/LICENSE | `07e7bf38169a0e26e088a0a6e6ba7f60704b2d0442c4433044169924c68ba732` |
| index-array-by | 1.4.2(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/index-array-by-LICENSE` | https://cdn.jsdelivr.net/npm/index-array-by@1.4.2/LICENSE | `5b6dc9ce44c7b73620b191c567339212bd00537af46fdedaf98304c34214cc9c` |
| internmap | 2.0.3(추정) [주2] | ISC | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/internmap-LICENSE` | https://cdn.jsdelivr.net/npm/internmap@2.0.3/LICENSE | `9ea8903938dab5f12c4572d60725069bec2d1b0dc3bcc210b09bae946a5ebb1f` |
| kapsule | 1.16.3(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/kapsule-LICENSE` | https://cdn.jsdelivr.net/npm/kapsule@1.16.3/LICENSE | `7262e566e874d1ce8cfadace01d4f635f8d704b6bdf7b4345cc028e5faeafded` |
| lodash-es | 4.18.1(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/lodash-es-LICENSE` | https://cdn.jsdelivr.net/npm/lodash-es@4.18.1/LICENSE | `f71e8ed126b46346494aad5486874cd8f0aafe95092ed67d2e3cb6110f939abc` |
| preact | 10.29.8(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/preact-LICENSE` | https://cdn.jsdelivr.net/npm/preact@10.29.8/LICENSE | `1fe6958409c8c257a70c587a18b6f7f412b179b456630790d30b2ec9a8e4b7d4` |
| tinycolor2 | 1.6.0(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/tinycolor2-LICENSE` | https://cdn.jsdelivr.net/npm/tinycolor2@1.6.0/LICENSE | `c6cb470a9ba0a50d57611aeec1f31da609c5aefdbee8eac7f289bcb0e30625fa` |
| @tweenjs/tween.js | 25.0.0(추정) [주2] | MIT | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/tweenjs-tween.js-LICENSE` | https://cdn.jsdelivr.net/npm/@tweenjs/tween.js@25.0.0/LICENSE | `c95fecd88f2709bfc34e4d1f1ccc36d17048990e6ba26c283cfecdef0432936b` |
| ColorBrewer(d3-scale-chromatic 안) | - | Apache-2.0 | 미확인(upstream 미대조, 묶음 파일은 SOURCE.md 해시 일치) [주7] | `force-graph/Apache-2.0.txt` | 전용 venv `site-packages/packaging-26.3.dist-info/licenses/LICENSE.APACHE` [주4] | `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594` |

## 주

- [주1] PySide6 6.12.0 휠에는 LGPL·GPL 원문 파일이 없다(`*.dist-info/licenses/`에는 `LicenseRef-Qt-Commercial.txt`만 있음). 그래서 이 PC에 설치된 다른 프로그램(Git for Windows)에 들어 있는 FSF 원문 사본을 복사했다. LGPL-3.0 사본은 다른 설치본(한컴오피스)의 사본과, GPL-3.0 사본은 같은 설치본 안의 다른 사본(`xz/COPYING.GPLv3`)과 해시가 같다. FSF 배포 원문과 직접 대조하지는 않았다. LGPL-3.0 사본은 저작권 줄의 FSF 주소가 `http://fsf.org/`인 이전 판이고, GPL-3.0 사본은 `https://` 판이다. PySide6의 GPL-2.0 선택지 원문은 따로 두지 않았다(GPL-2.0 본문은 `pyinstaller/COPYING.txt` 안에도 있음).
- [주2] force-graph 1.52.0 묶음(min.js)에는 의존성 버전 정보가 없다. 버전은 force-graph 1.52.0 `package.json`의 의존성 범위를 npm 레지스트리 메타데이터로 해석한 값이다. force-graph 1.52.0 게시 시각(2026-09-28T23:16:07Z) 이전에 범위를 만족한 가장 높은 버전을 골랐다. 실제 묶음에 들어간 버전과 다를 수 있다.
- [주3] bezier-js 6.1.4의 npm 묶음과 저장소 태그 `v6.1.4`에는 LICENSE 파일이 없다. `package.json`의 license는 MIT이고, README와 소스 머리말에는 "This code is MIT licensed."라고만 적혀 있다(저작권자 줄과 허가 문구 없음). 그래서 공식 저장소에 나중(2023-11-17, 6.1.4 게시 4개월 뒤)에 추가된 `LICENSE.md`(Copyright (c) 2023 Pomax)를 커밋 고정 경로로 받았다. 6.1.4 시점의 원문이 아니므로 저작권 연도·문구가 그때와 같다는 보장은 없다.
- [주4] d3-scale-chromatic LICENSE는 ColorBrewer 부분이 Apache-2.0이라고 적고, 전문은 URL로만 가리킨다. Apache-2.0 전문은 전용 venv의 `packaging` 패키지에 들어 있는 사본을 복사했다(`packaging` 자체는 묶음에 들어가지 않음).
- [주5] 휠 버전이다. `pyside6_webengine`·`pyside6_pdf`는 6.12.0.140이다. Qt 모듈별 라이선스는 위 "Qt 구성요소" 절을 본다.
- [주6] CPython은 python.org install manager 압축 파일의 SHA-256이 python.org 값과 같음을 W2에서 확인했다. 설치된 파일 하나하나의 대조는 하지 않았다. 묶음의 `python312.dll` 등은 설치 폴더 파일과 바이트 단위로 같다.
- [주7] vendor `force-graph.min.js`의 SHA-256(`f59db59b…a629`)이 `SOURCE.md`에 반입 시 기록한 값과 같다. 의존성은 이 파일 안에 묶여 있어 따로 수정되지 않았다. 다만 npm 배포본 자체를 지금 다시 받아 대조하지는 않았다.
