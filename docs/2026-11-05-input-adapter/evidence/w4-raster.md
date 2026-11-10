# W4 래스터(PNG·JPG) 어댑터 MVP — 구현·측정 기록

> 기록 일시: 2026-11-06(총괄 수정 지시 1회 반영) · 기준 커밋: `2758c44`(브랜치 `feat/next-units`, 미커밋 변경) · 작성: hazop-developer
> 근거 결정: [decisions.md](../decisions.md) D1(평가 기준·블라인드 규칙·출력 계약)·D2(설치는 W4 착수 때 결정)·D5(대응 문턱)·D7(설치·OCR) · 완료 기준: [w1-survey.md](w1-survey.md) §8 `W4`
> 표기: **[사실]** 실행·저장소로 확인 · **[추론]** 확인 사실에서 끌어낸 판단 · **[일반지식]** 출처 미대조 일반 지식

## 1. 산출물

| 경로 | 내용 |
|---|---|
| `hazop/extract/adapters/raster.py` | PNG·JPG 한 장 → extraction dict. 영상에서 선·기호·글자를 찾아 `pdf_vector`가 받는 원시 요소 형식으로 바꾼 뒤 `pdf_vector.analyze()`·`build_extraction()`을 그대로 쓰고, PDF 표기(좌표계·ID 접두어·근거 이름)를 래스터 표기로 바꾼다. OpenCV·numpy·rapidocr는 `importlib`로 함수 안에서만 읽는다 |
| `scripts/extract_raster.py` | CLI(`extract_pdf.py`와 같은 형태). 기본 출력 `출력/어댑터/raster/<도면번호>/`. `--samples`는 `.drawio.png`를 뺀다. `--no-ocr`. OpenCV가 없으면 rc=2 |
| `scripts/check_adapter.py` | W4 단계 추가: 샘플 PNG 6장의 구조·스키마·결정성(두 번 추출 비교)·그래프 단계(③) 호환·정렬·평가·샘플별 품질 하한(`RASTER_QUALITY_FLOORS`). OpenCV 또는 rapidocr가 없으면 건너뛰고 마지막 줄에 `(W4 건너뜀)`. `--raster-out 폴더`로 결과 저장 |
| `tests/test_raster.py` | 19건: 배포 제외 4(정적 import·`sys.modules` 차단 상태의 모듈 import·빌드 venv 설치 목록·빌드 TOC), 블라인드 표본 선택 1, 합성 영상 10(OpenCV 필요 — 경계 근처 몸체, ID 접두어 일관성, 처리량 상한 기록 포함), 입력 상한 2(빈·손상·너무 큰 입력), 샘플 2(OpenCV·rapidocr 필요) |
| `tests/test_adapter.py` | `run_checks` 건너뜀 시험이 W4 건너뜀 표시까지 보도록 1건 수정 |
| `packaging/requirements-raster.txt` | 설치 목록(버전·sha256 고정, §3) |

`pdf_vector.py`·`align.py`·`evaluation.py`는 수정하지 않았다(읽기·호출만).

## 2. 규칙 요약

모듈 머리말에 전체 규칙이 있다. 래스터 문턱은 `raster.PARAMS`(pt 단위, 실행 때 px로 환산), `pdf_vector` 문턱 중 래스터에서 바꾼 값은 `PV_OVERRIDES`에 있고, 둘 다 실행마다 `run.settings`에 기록된다. 파일·도면별 분기는 없다.

- **배율**: 이미지 폭을 공칭 페이지 폭(A3 가로 1190.55pt [일반지식: ISO 216 A3 420mm])에 맞춰 px/pt 배율을 정하고 `pdf_vector` 길이 문턱에 곱한다. 샘플은 2.75 px/pt(벡터 PDF 대비 실측 2.78) [사실].
- **글자**: rapidocr-onnxruntime 줄 단위 결과. 글자 상자 안에 통째로 들어가는 잉크 덩어리는 글자 획으로 보고 뺀다. 상자는 위아래 12%씩 줄여 글자 크기에 맞춘다. 계기 원 안 글자가 두 줄 미만이거나 신뢰도 0.9 미만이면 원 안을 3배로 키워 다시 읽는다(영문 대문자·숫자 줄만 받음).
- **채운 도형**: 2.2pt 원판 열림을 견디는 잉크(화살촉·검은 원). 화살촉은 번짐으로 벡터보다 커서(6.9~8.0pt) 표식 상한을 8.5pt로 넓혔다.
- **기호 몸체**: 잉크로 둘러싸인 흰 구멍 중 짧은 변 3pt 이상, 긴 변 페이지 폭 25% 이하, 볼록도 0.85 이상. 원은 가로·세로 선으로 갈린 두 구멍을 합친 모양이 원이면 합친다. 감싸는 삼각형 대비 넓이 0.85 이상이면 삼각형. 같은 축에서 마주 보지 않는 맞댄 삼각형(안전밸브 몸통)은 한 몸체로 합친다. 글자 없는 축 정렬 사각형끼리 변을 맞대면 한 몸체(열교환기 관 다발)로 합친다(글자가 있는 표제란 칸은 그대로 두어 표로 읽힌다).
- **선**: 몸체 윤곽·채움·글자 잉크를 뺀 나머지에서 6pt 이상 가로·세로 획 → 선분, 남은 가늘고 긴 덩어리 → 사선, 짧은 조각이 이웃과 사슬을 이루면 점선 조각. 꺾임·분기는 선 끝을 상대 선 중심선에 맞춘다. 같은 직선 위 빈칸이 OCR 글자 상자(또는 글자 획 크기 덩어리 3개 이상)로 채워져 있으면 선 라벨로 보고 잇는다. 페이지의 80% 이상인 가로·세로 선(테두리)은 버린다. 선과 화살촉 사이 3.5pt 이하 빈칸은 짧은 잇는 선을 더한다. 두 몸체 사이 12pt 이하 선은 기호 안 축(구동부 축)으로 보고 얇은 몸체로 바꾼다. 가까운 평행 사선(스프링 표시)은 같은 방향 벡터로 맞춘다.
- **출력**: 좌표계 `image_px`/`px`, `source.format` = `raster_png`·`raster_jpeg`, ID 접두어는 모든 문자열 값(`ignored_objects`·근거 목록 포함)에서 `pdf-p0-` → `img-`, `pdf-path-` → `img-prim-`, `line_type` `raster_solid`·`raster_dashed`. OCR이 없으면 미확인 `ocr_unavailable`, `--no-ocr`로 끈 경우 `ocr_disabled`, 해석하지 못한 잉크 덩어리는 `unread_ink_clusters`로 남기고 추출은 막지 않는다. 영상에 아무것도 없으면 blocker `no_image_content`.
- **입력·처리량 상한**: 해독 전 파일 100 MB, 머리말(Pillow, 픽셀은 풀지 않음)과 해독 뒤 픽셀 수 50 MP를 넘거나 빈·손상 파일이면 blocker가 아니라 형식 오류(`RasterInputError`, CLI 종료 코드 2). 몸체 합치기 쌍 비교 후보가 400개, 평행 사선 묶음 후보가 400개를 넘으면 그 단계를 건너뛰고 미확인 `processing_limit`을 남긴다. 잘라내기 좌표는 모두 영상 범위로 제한한다(경계 근처 몸체).

## 3. 설치(결정 D7)

- [사실] 별도 venv `%USERPROFILE%\.hazop\venv-raster-py312`(기반 CPython 3.12.10, 빌드 venv와 같은 기반)에 `pip install --require-hashes --no-deps --only-binary=:all: -r packaging/requirements-raster.txt`. 외부 설치 프로그램 실행 없음. 내려받기 합계 98.3 MB(아래 휠 크기 합), 설치 뒤 venv 290 MB.
- [사실] 지시받은 위치(빌드 venv `venv-py312`)에 넣지 않은 이유: 빌드 venv의 openpyxl `compat/numbers.py`가 `import numpy`를 갖고 있어(확인: `grep`), numpy가 설치되면 PyInstaller가 그것을 따라 numpy를 배포본에 묶는다 [추론: PyInstaller는 `try` 안·함수 안 import도 따라간다]. numpy·OpenCV를 배포본과 고지(licenses/)에서 빼려면 빌드 venv에 넣지 않는 편이 확실하다.

| 패키지 | 버전 | 휠 | 크기(byte) | 라이선스(PyPI 표기) | sha256 |
|---|---|---|---|---|---|
| opencv-python-headless | 5.0.0.93 | cp37-abi3-win_amd64 | 43,825,962 | Apache 2.0 | `829717b6a95554f273e49e357cee3b3a2a26b6f4842fbc1bed2b45bdd8f87e0e` |
| numpy | 2.5.4 | cp312-win_amd64 | 12,573,091 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | `a7b1b6353e36a7e50de2973a38d705c88ee93adcf120673cee7f45a4a3fa223a` |
| rapidocr-onnxruntime | 1.4.4 | py3-none-any | 14,915,192 | Apache-2.0 | `971d7d5f223a7a808662229df1ef69893809d8457d834e6373d3854bc1782cbf` |
| onnxruntime | 1.31.1 | cp312-win_amd64 | 14,888,466 | MIT | `ae8a9a351efda685cc59a66226cdefaa37a126c1d66872ca23a2de9425326130` |
| flatbuffers | 25.12.19 | py2.py3-none-any | 26,661 | Apache 2.0 | `7634f50c427838bb021c2d66a3d1168e9d199b0607e6329399f04846d42e20b4` |
| protobuf | 7.36.2 | cp310-abi3-win_amd64 | 456,514 | BSD-3-Clause | `a300819d441e078a5608c0d3c709796bb548136058fda017ae51d425b44fd353` |
| packaging | 26.3 | py3-none-any | 129,956 | Apache-2.0 OR BSD-2-Clause | `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c` |
| pyclipper | 1.4.0 | cp312-win_amd64 | 104,619 | MIT | `d1e5498d883b706a4ce636247f0d830c6eb34a25b843a1b78e2c969754ca9037` |
| shapely | 2.2.0 | cp312-win_amd64 | 1,791,280 | BSD-3-Clause | `90895df6542ae039fc6557dec6194e3509e883fbd6f5788e3c3e7a38fe46b257` |
| pyyaml | 6.0.3 | cp312-win_amd64 | 154,003 | MIT | `5fcd34e47f6e0b794d17de1b4ff496c00986e1c83f7ab2fb8fcfe9616ff7477b` |
| pillow | 13.0.0 | cp312-win_amd64 | 7,272,166 | MIT-CMU | `ff3fe9eb621fbb9db4c4be33ab946f6bac5f98ab50ca8d3260503653656c961b` |
| networkx | 3.7 | py3-none-any | 2,142,205 | BSD-3-Clause(배포 런타임과 같은 판, 검사 스크립트용) | `e3fd2c13a7814cee3746340d8d7f8598a67f16a58bf47fb7f8793fab6efca1b0` |

- **OCR 후보 조사(1개)**: rapidocr-onnxruntime 1.4.4(Apache-2.0). 휠 안에 PP-OCRv4 검출·인식 모델과 방향 분류 모델(합계 약 16 MB)이 들어 있어 실행 중 내려받기가 없다 [사실: 휠 목록·코드의 import·URL 확인]. 코드가 import하는 것은 cv2·numpy·onnxruntime·pyclipper·shapely·yaml·PIL뿐이라, 선언 의존성 중 opencv-python(GUI판)은 headless로 대신하고 six·tqdm(MPL-2.0 AND MIT)은 넣지 않았다. 모델 가중치의 라이선스는 PaddleOCR 저장소 표기(Apache-2.0)로 알려져 있으나 원문은 대조하지 않았다 [일반지식].
- 제외한 후보: rapidocr 3.x(실행 때 모델 내려받기), easyocr(torch 의존, 크기 초과·실행 때 모델 내려받기), tesserocr·pytesseract(Tesseract 실행 파일 설치 필요 — 지시로 금지).

## 4. 측정 환경·명령

- [사실] `PYTHONUTF8=1 %USERPROFILE%\.hazop\venv-raster-py312\Scripts\python.exe scripts/check_adapter.py --raster-out <세션 임시 폴더>`(저장소 밖). 정답은 같은 폴더 `.drawio`의 `drawio.extract()`(메모리), 입력은 `01_*.png`(`.drawio.png` 제외 — `raster_samples()`와 시험으로 확인). 샘플 1장당 OCR 포함 약 2~4초.
- 좌표 정렬은 기존 `align.py`(OCR 글자 기준점)를 그대로 썼다. 6장 모두 scale ≈ 0.500, offset ≈ (9.3, 9.2) — W1의 “PNG = 배율 2, 테두리 10” 추정과 맞는다 [추론].

## 5. 6세트 지표 (첫 측정, 목표치 없음)

관계 F1이 주 지표다(D1). 괄호는 TP/FP/FN. 잔차 단위는 정답 좌표 canvas_unit.

| 도면 | 노드 정답/후보 | 관계 정답/후보 | 미해결 | blocker | 관계 F1 (TP/FP/FN) | 객체 F1 (TP/FP/FN) | 태그 F1 (TP/FP/FN) | kind 정확도 | category 정확도 | 기준점 사용/전체 | 잔차 RMS / 최대 | 제외 전 RMS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SNP-M-101_RCS-main-loop | 35/34 | 35/32 | 4 | 0 | 0.9254 (31/1/4) | 0.9565 (33/1/2) | 0.8750 (21/3/3) | 0.8788 | 0.9091 | 16/21 | 0.3349 / 0.8961 | 8.0564 |
| SNP-M-102_RCS-pressurizer | 19/20 | 19/21 | 1 | 0 | 0.8500 (17/4/2) | 0.9744 (19/1/0) | 0.8667 (13/2/2) | 0.9474 | 0.9474 | 11/13 | 0.1595 / 0.3173 | 1.2970 |
| SNP-M-201_CVCS | 22/27 | 23/24 | 5 | 0 | 0.7234 (17/7/6) | 0.8980 (22/5/0) | 0.8947 (17/2/2) | 0.7727 | 0.8182 | 14/17 | 0.2400 / 0.4274 | 7.4973 |
| SNP-M-301_SIS | 21/26 | 21/18 | 8 | 0 | 0.6667 (13/5/8) | 0.8936 (21/5/0) | 0.8235 (14/3/3) | 0.6667 | 0.8095 | 10/14 | 0.1629 / 0.2331 | 6.0410 |
| SNP-M-401_CCW | 24/30 | 24/22 | 7 | 0 | 0.6087 (14/8/10) | 0.8148 (22/8/2) | 0.9333 (14/1/1) | 0.8182 | 0.8182 | 10/14 | 0.2302 / 0.3038 | 11.0115 |
| SNP-M-501_MS-FW | 20/25 | 20/19 | 8 | 0 | 0.7179 (14/5/6) | 0.8889 (20/5/0) | 1.0000 (16/0/0) | 0.8500 | 0.9000 | 11/16 | 0.2231 / 0.4481 | 13.3738 |

- 비교(같은 6세트, W3 벡터 PDF): 관계 F1 0.870~1.0, 객체 F1 0.957~1.0. 래스터는 관계 F1 0.609~0.925로 낮다.
- 제외 전 RMS가 큰 것은 OCR이 일부 글자를 잘못 읽은 기준점(예: 다른 위치의 같은 글자) 때문이며, 합의·제외 뒤 잔차는 0.16~0.33이다 [사실: alignment.json `outliers`].
- **품질 하한(`RASTER_QUALITY_FLOORS`)**: 위 측정값을 0.05 단위로 내린 뒤 0.05를 더 뺀 값(예: 관계 F1 0.9254 → 0.85, 102 kind 0.9474 → 0.85 — 처음 0.9로 잘못 적은 것을 검토 지적으로 고침). OCR(onnxruntime)·영상 처리 결과가 다른 PC·판에서 조금 달라질 여지를 둔 보수적 회귀 방지 장치이며 목표치가 아니다. 같은 PC에서 별도 프로세스 두 번 실행한 CLI 출력은 `diff -r`로 같았다 [사실].
- 문턱 비교(표본 내): 몸체 접속 허용 `attach_tol` 2.5·3.5·4.5pt 중 3.5가 501에서 가장 좋고 나머지는 같거나 나빠 3.5로 정했다. 구멍 찾기 전 잉크 닫힘(전체·화살촉 근처)은 펌프 외곽선 틈을 메우려 시험했으나 지표가 나빠지거나 변화가 없어 넣지 않았다.

## 6. 차이 원인(표본 확인)

[사실: 디버그 그림·평가 대응 목록 확인]
- **펌프**: 펌프 외곽선이 흡입구 쪽에서 열려 있어(화살촉 끝이 닿는 틈) 흰 구멍이 닫히지 않는다. 펌프가 몸체로 잡히지 않고 선 조각으로 흩어져 객체·관계가 함께 어긋난다(201·301·401·501).
- **체크밸브**: 세로 막대 두 개와 사선으로 그린 기호가 세로 막대(선)와 사선으로 나뉘어 기호 둘 또는 분기점이 된다(301·401).
- **선 라벨**: OCR이 읽지 못한 선 라벨은 “글자 획 크기 덩어리 3개 이상” 규칙으로 잇지만, 라벨이 선에 겹쳐 그려진 곳 일부는 여전히 끊긴다.
- **해치 탱크**(301 IRWST, 약어는 §8): 벽 해치가 작은 구멍 여러 개로 나뉘어 기호 종류가 정해지지 않는다.
- **정답지 모델링 차이**: W3 §4와 같은 차수 1·2 tee(102·401)는 래스터에서도 복원할 수 없다.
- **OCR**: `TT`를 `11`로, 짧은 `LI`를 놓치는 등 계기 원 안 짧은 글자가 약하다. 원 안 다시 읽기로 일부 회복했다(태그 F1 0.82~1.0).

## 7. 배포 제외 확인

- [사실] `hazop/**`·`scripts/run_app.py`·`packaging/check_entry.py`·`scripts/extract_drawio.py`·`scripts/build_graph.py` 어디에도 cv2·numpy·rapidocr_onnxruntime·onnxruntime import 문이 없다(함수 안 포함, AST 검사 — `test_no_static_import_of_raster_dependencies`). `raster.py`는 `importlib.import_module`로만 읽는다.
- [사실] 빌드 venv(`venv-py312`)에는 이 패키지들이 없다(`test_build_venv_has_no_raster_dependencies`).
- [사실] 이 변경을 포함한 작업 트리로 빌드 venv에서 `scripts/build_package.py --build`를 세션 임시 폴더에 실행했다(rc=0, 출처·바이너리 검사 통과). `PYZ-00.toc`에 `hazop.extract.adapters.raster`는 있고 cv2·numpy·onnxruntime·rapidocr는 0건, `COLLECT-00.toc`도 0건이었다. `HAZOP_BUILD_OUT=<그 폴더>`로 `test_build_tocs_have_no_raster_dependencies`가 통과했다(환경 변수가 없고 임시 폴더에 빌드가 없으면 건너뜀).

## 8. 한계·확인 필요

- **해치 탱크 표기**: IRWST = In-containment Refueling Water Storage Tank(격납건물 내 재장전수 저장탱크) — APR1400 설계 용어로 알려져 있으나 정의 원문(APR1400 DCD·NRC 문서)은 대조하지 않았다 [일반지식]. POSRV = Pilot Operated Safety Relief Valve, PSV = Pressure Safety Valve, MOV = Motor Operated Valve [일반지식, 원문 미대조].
- **[중요] 표본 내 측정이다.** 규칙·문턱을 같은 6장을 보며 정했다. 모두 draw.io가 같은 스타일·배율로 내보낸 깨끗한 합성 도면이므로, 스캔본·다른 도구 도면에서는 훨씬 낮을 것이다 [추론]. 열화(해상도·잡음·회전·JPG) 영향은 `W5`에서 잰다. JPG는 형식만 받으며 이번에 지표를 재지 않았다.
- 배율은 “이미지 폭 = A3 가로” 가정이다. 페이지 일부를 자른 그림이나 다른 용지에서는 문턱이 맞지 않는다.
- 흐름 방향·`tag` 속성은 PDF와 같이 만들지 않는다(미확인 기록). `line_type` `raster_*`는 `rules.LINE_TYPE_RELATION`에 없다.
- OCR 모델은 중국어·영어 혼합 모델이라 영문 대문자·숫자 외 글자가 섞여 나올 수 있다. 결과가 실행 환경(onnxruntime 판·CPU)에 따라 조금 달라질 수 있다 [추론].
- 래스터 결과는 `출력/어댑터/raster/`에 따로 쓰며 등록(`hazop/register`)과 화면 경로에는 연결하지 않았다(`not_registered` 미확인).
- 체크밸브·펌프·해치 탱크 규칙은 넣지 않았다(§6). 개선은 `W5` 결과와 실제 도면 확보 뒤 우선순위를 정한다.

## 9. 직접 검증할 부분

- `scripts/extract_raster.py --samples` 결과를 PNG와 겹쳐 보며 기호 bbox·관계를 표본 확인할 것(이 기록은 지표·자동 검사와 개발 중 디버그 그림으로만 판정했다).
- §3 라이선스는 PyPI 표기 기준이다. 배포본에 넣지 않으므로 고지를 만들지 않았지만, 배포에 넣게 되면 각 휠의 LICENSE 원문(특히 opencv 휠 안 제3자 바이너리, rapidocr 모델 가중치)을 대조해야 한다.
