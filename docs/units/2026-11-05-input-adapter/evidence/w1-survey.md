# W1 조사 — PDF·PNG/JPG 입력 어댑터

> 조사 일시: 2026-11-05 17:30 · 기준 커밋: `d540288`(브랜치 `chore/track-workspaces`) · 작성: 에이전트(조사 전용, 설치·다운로드 없음)
> 표기: **[사실]** 저장소 확인 또는 출처 URL이 있는 내용 · **[추론]** 확인 사실에서 끌어낸 판단 · **[미확인]** 확인하지 못한 내용
> 웹 출처는 공식 문서·논문 초록 위주로 읽었고 논문 본문 전체는 읽지 않았다(각 항목에 읽은 범위 표시).

## 0. 읽은 범위

| 자료 | 읽은 범위 |
|---|---|
| `units/2026-11-05-input-adapter/README.md`, `PROGRESS.md`, `evidence/README.md` | 전부 |
| `specs/extraction.md`, `specs/registration.md` | 전부 |
| `hazop/extract/drawio.py`, `svg_align.py`, `rules.py`, `scripts/extract_drawio.py` | 전부 |
| `hazop/register/fileinfo.py` | 전부 / `registry.py`는 함수 목록과 `register()` 앞부분(324~420행)만 |
| `출력/그래프/SNP-M-102/graph.json`, `entity_mapping.json` | 키·항목 수만(스크립트로 요약) |
| `출력/추출/SNP-M-102/extraction.json` | 노드의 kind·tag·label_text, 관계 3건, 좌표계 블록만 |
| `참고자료/P&ID 도면 샘플/SNP-M-102_*` 의 PDF·PNG | 파일 헤더·PNG 청크·PDF 스트림 연산자 개수(읽기 전용 스크립트) |

## 1. 저장소 현황 (조사의 전제)

1. **[사실] 시험 도면이 이미 있다.** `참고자료/P&ID 도면 샘플/` 6세트(SNP-M-101·102·201·301·401·501)마다 `.drawio`, `.pdf`, `01_*.png`, `01_*.jpg`, `01_*.drawio.png`, `01_*.svg`, `01_*.drawio.svg`, `.html`이 Git으로 추적되어 있다(`git ls-files`).
2. **[사실] 샘플 PDF는 벡터 PDF다.** SNP-M-102 PDF: 1쪽, MediaBox 1191.12×841.92pt(A3 가로), Creator `diagrams.net`, Producer `pdf-lib`. 내용 스트림에 `re` 25·`l` 336·`c` 588개(선·사각형·곡선)와 `BT` 41·`Tj` 82개(텍스트)가 있고 ToUnicode CMap이 있어 문자를 되읽을 수 있다. drawio XML은 들어 있지 않다.
3. **[사실] `01_*.drawio.png`는 PNG `zTXt` 청크에 다이어그램 XML을 담고 있고 `01_*.png`는 IHDR·IDAT·IEND만 있다.** 따라서 래스터 시험에 `.drawio.png`를 쓰면 정답이 입력에 섞인다. `.drawio.svg`도 `data-cell-id`를 담고 있어 블라인드 시험 입력이 될 수 없다.
4. **[사실] PNG 크기는 3274×2304px, drawio SVG viewBox는 1617×1132다.** (1617+2×10)×2=3274, (1132+2×10)×2=2304이므로 **[추론]** 배율 2, 테두리 10으로 내보낸 것으로 보인다. drawio 페이지 크기는 1654×1169(canvas_unit)이고 PDF는 1191.12pt 폭이어서 **[추론]** PDF는 페이지 전체를 약 0.72배로 담았다. 좌표 대응은 형식별 어파인 변환을 따로 구해야 한다.
5. **[사실] 프로젝트 Python 3.12(사용자 site-packages `C:\Users\kim92\AppData\Roaming\Python\Python312`)에 PyMuPDF 1.27.2.3, pdfplumber 0.11.9, pdfminer.six 20251230, pypdf 6.11.0, numpy 2.4.6, Pillow 12.2.0, networkx 3.7이 이미 설치되어 있다.** OpenCV·pytesseract·Tesseract 실행 파일·draw.io 데스크톱은 없다(`where`, 설치 폴더 확인). 저장소 코드는 이 PDF·영상 라이브러리를 하나도 import하지 않는다(`grep`). 설치되어 있다는 사실이 프로젝트 의존성 승인을 뜻하지는 않는다.
6. **[사실] 읽기 전용 시험(PyMuPDF, SNP-M-102 PDF):** `get_drawings()` 65개 경로(항목 `c` 298·`l` 284·`re` 14), `get_text("words")` 84단어. drawio 추출 결과의 `tag` 16개 중 단어와 그대로 일치하는 것은 5개뿐이다. 계기는 `tag`가 `RC-TT110`인데 도면에는 `TT`·`110` 두 줄로 그려지고, tee 4개는 `tag`가 있지만 도면에 글자가 없다(`label_text` 빈 값).
   - **[추론] 정답지의 태그 비교는 속성 `tag`가 아니라 도면에 보이는 `label_text`(정규화)를 기준으로 하고, `tag`는 있으나 화면에 없는 객체(tee 등)는 "시각 정보로 복원 불가" 범주로 따로 집계해야 한다.**

## 2. 조사 항목 1 — 벡터 PDF 추출 라이브러리

| 후보 | 기능(좌표) | 라이선스 | Windows wheel | 오프라인 |
|---|---|---|---|---|
| PyMuPDF(MuPDF) | `get_drawings()`로 선·곡선·사각형 경로와 색·선폭, `get_text("words"/"dict")`로 글자·단어 bbox, 페이지 렌더링(PNG 생성) 가능 [사실: 위 1-6 시험] | **AGPL 또는 상용 이중 라이선스** [사실](https://pymupdf.readthedocs.io/en/latest/about.html) | 32·64비트 wheel, 필수 외부 의존성 없음 [사실](https://pymupdf.readthedocs.io/en/latest/installation.html) | 가능. OCR 기능은 별도 Tesseract 필요 [사실](같은 출처) |
| pdfplumber(+pdfminer.six) | `chars`·`lines`·`rects`·`curves`(점 목록·경로) 모두 좌표 포함 [사실](https://github.com/jsvine/pdfplumber) | MIT(둘 다) [사실: 저장소 표기, LICENSE 원문은 미열람] | 순수 Python [추론: pdfminer.six 기반] | 가능 |
| pypdf | 텍스트·메타데이터 추출, 분할·병합 등. 벡터 경로 추출 기능은 PyPI 설명에 없음 [사실](https://pypi.org/project/pypdf/) | BSD-3-Clause [사실](같은 출처) | 순수 Python [사실] | 가능 |

- **[추론] MVP 권고는 pdfplumber(MIT)다.** 선·곡선·글자 좌표를 모두 주고 라이선스 부담이 없다. 성능은 PyMuPDF보다 느릴 수 있으나 샘플 6쪽 규모에서는 문제가 아니다 [추론, 미측정].
- **[추론] PyMuPDF는 기능상 가장 편하지만 AGPL이다.** 데스크톱 프로그램을 배포(T2 패키징 트랙)하면 AGPL 소스 공개 의무가 걸릴 수 있다. 라이선스 판단은 사용자·법무 결정 사항이며, 결정 전에는 평가·시험 도구(배포물 밖)로만 쓰는 것을 권한다.
- **[미확인]** pdfplumber가 샘플 PDF에서 PyMuPDF와 같은 수의 경로·글자를 되읽는지는 측정하지 않았다(W2 첫 확인 항목).
- **[추론] 벡터 PDF의 한계:** PDF에는 객체 단위 경계가 없고 선분·곡선의 모음일 뿐이다. 기호(밸브·계기 원)는 경로 묶음을 형상 규칙으로 다시 묶어야 하고, 배관 선과 기호 외곽선의 구분도 규칙이 필요하다. 샘플은 같은 도구가 같은 스타일로 그렸으므로 규칙 기반이 잘 맞지만, 실제 도면 일반화는 보장하지 않는다.

## 3. 조사 항목 2 — 래스터(PNG/JPG) 인식 접근

| 접근 | 내용 | 라이선스·배포 | MVP 적합성 [추론] |
|---|---|---|---|
| OCR: Tesseract | 오프라인 OCR 엔진, Windows 설치본은 UB Mannheim 제공 [사실](https://github.com/UB-Mannheim/tesseract) | Apache 2.0, Leptonica는 BSD-2 계열 [사실: 같은 출처 검색 요약, 원문 미열람] | 별도 실행 파일 설치가 필요(사용자 승인). 계기 원 안의 `TT`/`110` 같은 짧은 문자열은 영역을 잘라 줘야 정확도가 오른다 [추론] |
| 고전 영상처리: OpenCV | 이진화·허프 변환·연결 성분·윤곽선·템플릿 매칭 | `opencv-python(-headless)` Apache 2.0, Windows 분류자 있음. wheel에 제3자 바이너리 포함(별도 라이선스 파일) [사실: PyPI 미러 요약, 원문 미열람] | 샘플처럼 깨끗한 합성 도면의 직선·원·사각형 검출에 적합. 미설치이므로 승인 필요. numpy·Pillow만으로 수평·수직 선 검출 시작도 가능 [추론] |
| 딥러닝 디지털화 연구 | 아래 표 | 대부분 학습 데이터·GPU 필요 | MVP 부적합. 기호 클래스가 30종 남짓이고 학습 데이터가 없음 |

딥러닝 기반 P&ID 디지털화 연구(초록·요약만 읽음):

| 연구 | 방법 | 보고 수치(저자 자체 보고) | 출처 |
|---|---|---|---|
| Paliwal 외, Digitize-PID (PAKDD 2021) | 커널 기반 선 검출, 2단계 기호 인식, CRAFT+Tesseract 문자 | 합성 데이터: 실선 99.34%, 점선 82.91%, 문자 검출 87.18%·인식 79.21%, 기호 F1 0.82~0.98 | https://arxiv.org/abs/2109.03794 , https://ar5iv.labs.arxiv.org/html/2109.03794 |
| Kim·Mun 외 (JCDE 9(4), 2022) | 기호·문자·선 DNN, 위상 복원은 규칙 기반. 키워드에 DEXPI | 정밀도/재현율: 기호 96.65/96.40, 문자 90.65/92.16, 선 95.25/87.91, 위상 99.56/96.07 (시험 도면 5장) | https://pure.korea.ac.kr/en/publications/end-to-end-digitization-of-image-format-piping-and-instrumentatio/ (DOI 10.1093/jcde/qwac056) |
| Stürmer 외 (arXiv 2024) | Relationformer로 기호와 연결을 그래프로 동시 추출, 그래프 정답 공개 데이터셋 | 실제 도면에서 모듈형 기준 대비 엣지 검출 정확도 25% 이상 향상(절대값은 초록에 없음) | https://arxiv.org/abs/2411.13929 |
| Mani 외 (CVPRW 2020) | CNN 기호 검출 + 그래프 탐색 | [미확인] | https://mlanthology.org/cvprw/2020/mani2020cvprw-automatic |

- **[추론] 수치 해석:** 논문 수치는 학습된 모델과 저자 데이터 기준이다. 이 저장소의 가상 도면에 그대로 옮길 수 없다. 공통 시사점은 (1) 선·기호 검출보다 **문자 인식과 위상(연결) 복원이 약점**이고 (2) 위상 복원은 규칙 기반이 많이 쓰인다는 점이다.
- **[미확인]** DEXPI 출력 여부(Kim 외)와 Stürmer 외 데이터셋 라이선스는 본문을 보지 않아 확인하지 못했다.
- **[추론] MVP 권고:** 래스터는 "PDF 어댑터의 기하 규칙을 재사용하는 고전 영상처리 + Tesseract OCR"로 시작하고, 딥러닝은 후속으로 미룬다. 기획서의 "생성형 AI 자유 해석은 기본 경로로 두지 않음" 원칙(정보추출.md 72행)과도 맞는다.

## 4. 조사 항목 3 — drawio 정답지 기반 정확도 평가

### 4.1 정답지 구성 [추론]

- 정답지 = 같은 도면의 `extraction.json`(drawio 경로)을 "시각 정답"으로 변환한 것. 각 노드에 `kind`, `category`, 보이는 문자(`label_text` 정규화: 줄바꿈·공백 제거, 대문자), bbox(drawio 좌표)를 둔다.
- 화면에 근거가 없는 정보(속성 `tag`만 있고 글자가 없는 tee, `normal_position`, `flow_direction` 속성 등)는 **"비시각 속성"** 으로 표시해 재현율 분모에서 빼고 별도 집계한다. 1-6의 tee 사례가 근거다.
- `pidIgnore` 객체(도면 틀·표제란)는 평가 대상에서 제외하되, 표제란 문자는 등록 단계 "자동 후보" 비교용으로 따로 둔다.

### 4.2 좌표 정렬

- drawio 좌표 → 형식 좌표 변환을 먼저 구한다. SVG는 `svg_align.align`이 offset을 검증하는 방식이 이미 있다 [사실: svg_align.py]. PDF·PNG는 배율+이동(어파인)으로, 표제란 글자처럼 양쪽에서 확실히 대응되는 기준점으로 최소제곱 추정하고 잔차를 보고서에 남긴다 [추론].
- 정렬 실패(잔차가 문턱 초과) 시 평가를 `blocked`로 둔다. 조용히 0으로 처리하지 않는 기존 원칙(drawio.py `invalid_number`)과 같다.

### 4.3 객체 대응 기준 (우선순위)

1. **문자 일치:** 정규화한 보이는 문자가 같고 bbox 중심 거리가 문턱 이내.
2. **좌표 IoU:** 기호 bbox IoU ≥ 0.5(제안값, W2에서 샘플로 조정). 작은 기호는 IoU가 민감하므로 중심 거리 기준을 보조로 둔다.
3. **종류 일치:** `kind` 또는 최소한 `category`(equipment·valve·instrument·piping_element).
- 한 정답에 한 예측만 대응하도록 헝가리안 방식 1:1 할당(비용 = 1−IoU 등)을 쓴다 [일반지식]. 결정적 결과를 위해 동점은 `source_object_id` 순으로 정한다.

### 4.4 지표

| 층위 | 지표 | 비고 |
|---|---|---|
| 기호 검출 | 정밀도·재현율·F1 (IoU 기준 대응) | 기획서의 "정밀도·재현율로 평가"(정보추출.md 148행)와 일치 |
| 분류 | 대응된 쌍의 kind 정확도, category 정확도, 혼동 행렬 | |
| 문자 | 태그 완전 일치율, 문자 단위 편집 거리(CER) | 계기 두 줄 표기는 합쳐서 비교 |
| 연결(위상) | 관계 정밀도·재현율·F1: 양 끝 노드가 모두 대응된 경우 무방향 쌍 `{a,b}`와 `kind`(physical/signal/measurement) 일치 | 교차 비연결을 연결로 만든 경우는 오탐으로 따로 집계 |
| 그래프 전체 | 그래프 편집 거리(GED) | networkx `graph_edit_distance`는 정확 알고리즘이며 `timeout` 시 현재 최선값을 돌려준다 [사실](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.similarity.graph_edit_distance.html). 노드 30개 규모에서도 오래 걸릴 수 있어 [추론] 보조 지표로만 쓰고 시간 제한과 "근사" 표시를 함께 남긴다 |

- **[추론] 주 지표는 관계 F1**이다. HAZOP 경로 탐색 품질은 기호 개수보다 연결 정확도에 좌우되기 때문이다.
- 결과는 `report.py`와 같은 Markdown 보고서와 JSON 지표 파일로 남긴다(형식은 W2에서 확정).

## 5. 조사 항목 4 — 가상 시험 도면 만들기

- **[사실]** 샘플 6세트의 PDF·PNG·JPG가 이미 저장소에 있다(1절). W2 이후 시험은 **추가 생성 없이 이것으로 시작할 수 있다.** 다만 이 파일들이 현재 `.drawio`와 같은 판에서 내보낸 것인지는 **[미확인]**(파일 시각은 모두 2026-11-03 17:07로 같음).
- **[사실]** draw.io 데스크톱(Electron)은 편집기를 오프라인으로 실행하며 `--export`, `--format`(png·jpg·pdf·svg 등), `--scale`, `--border`, `--crop`, `--page-index`, `--embed-diagram`, `--transparent`, `--quality` 등의 내보내기 옵션이 있다(소스 코드의 옵션 처리 부분 기준, 일부 플래그 철자는 `--help`로 재확인 필요) — https://github.com/jgraph/drawio-desktop (`src/main/electron.js`), https://github.com/jgraph/drawio/wiki/Desktop-App
- **[사실]** 이 PC에는 draw.io 데스크톱이 설치되어 있지 않다. 설치는 사용자 승인 사항이다.
- **[추론] 생성 규칙 제안:** 블라인드 시험용 PNG·PDF는 `--embed-diagram`을 쓰지 않고 내보낸다. 배율·테두리·해상도를 파일명이나 사이드카 JSON에 기록해 정렬을 검증할 수 있게 한다. 열화 시험(JPG 품질 저하, 회전, 노이즈, 저해상도)은 Pillow로 원본 PNG에서 파생해 만든다.
- **[추론] 대안:** draw.io를 설치하지 않으면 기존 6세트만으로 시험하고, 열화 변형은 Pillow(이미 설치)로 만든다. 이 경우 새 도면 추가는 사용자가 draw.io로 직접 내보내야 한다.

## 6. 조사 항목 5 — 어댑터 연결 지점(공통 출력 계약) 제안

현재 구조 [사실]:
- `drawio.extract()`가 `extraction.json`을 만들며 최상위 키는 `schema_version`, `extraction_run_id`, `run`, `source`(`format: "drawio"`), `source_context`, `drawing`, `coordinate_system`(`page_local_2d`, `canvas_unit`), `nodes`, `relations`, `unresolved_connectors`, `texts`, `unclassified`, `source_locations`, `validation`, `summary`다.
- 노드·관계·위치의 원본 근거는 `source_object_id`(drawio 셀 ID)다. ③ 그래프는 `entity_mapping`(`extraction_run_id`·`local_id` → `entity_id`, `source_object_id`)으로 이를 잇는다(graph.json: nodes 30, edges 30, entity_mapping 38).
- 등록 단계 `fileinfo.inspect`는 PDF·PNG·JPEG 매직 바이트를 이미 판별하지만 `.drawio` 외 확장자는 `unsupported_extension`으로 막는다.

제안 [추론]:
1. **같은 `extraction.json` 스키마를 출력한다.** 기획서 결정("어댑터 출력은 같은 추출 결과 JSON", 정보추출.md 14행)과 같다. 그래프 단계(③) 이후는 수정하지 않는 것이 목표다.
2. **어댑터별로 달라지는 필드:** `source.format`(`pdf_vector`·`raster_png`·`raster_jpeg`), `run.script`, `coordinate_system`(PDF는 `pdf_page_pt`, 래스터는 `image_px` + drawio 좌표로의 변환), `source_object_id`(drawio ID가 없으므로 어댑터가 만든 결정적 ID, 예: `pdf-p0-path-0123`, `img-sym-0007`).
3. **추가 필드(선택):** 노드·관계에 `confidence`(0~1)와 `evidence`(근거 경로·글자 ID 목록). 기존 소비자가 모르는 키는 무시하는지 W2에서 확인 필요 [미확인].
4. **분류 규칙:** drawio 경로는 속성으로 `kind`를 읽지만 어댑터는 형상·문자로 추정한다. 추정 근거가 약하면 `classification: "unclassified"`로 두고 `unknowns`에 남겨 "근거 없으면 미분류" 원칙을 지킨다. 연결은 선 끝점이 기호 경계에 닿은 경우만 `relations`, 나머지는 `unresolved_connectors`.
5. **배치:** `hazop/extract/adapters/`(편집 허용 경로) 아래 `pdf_vector.py`, `raster.py`, 공통 `base.py`(스키마 조립·검증 재사용). 실행은 `scripts/extract_pdf.py`, 평가는 `scripts/check_adapter.py`.
6. **등록 단계 확장은 별도 결정 필요:** `hazop/register/`는 이 트랙의 편집 허용 범위 밖이다. MVP 평가는 등록 없이(`not_registered` 미확인 기록) 파일 경로로 실행하고, PDF·PNG 등록 허용은 자료등록 소유 트랙과 협의한다.

## 7. 권고 스택 [추론]

| 용도 | 권고 | 상태 |
|---|---|---|
| 벡터 PDF 읽기 | pdfplumber(+pdfminer.six), MIT | 이미 설치. 프로젝트 의존성 채택 승인 필요 |
| PDF 비교·렌더링(평가 전용) | PyMuPDF — AGPL 판단 전에는 배포물에 넣지 않음 | 이미 설치. 사용 범위 결정 필요 |
| 래스터 기하 | numpy + Pillow로 시작, 부족하면 OpenCV(headless, Apache 2.0) | numpy·Pillow 설치됨, OpenCV 미설치 |
| 래스터 문자 | Tesseract(Apache 2.0) + 기호 내부 영역 잘라 읽기 | 미설치(실행 파일 설치 필요) |
| 평가 | 표준 라이브러리 + networkx(이미 그래프 단계에서 사용), 1:1 할당은 간단한 헝가리안 직접 구현 또는 scipy | scipy 미설치 — 직접 구현 권고 |
| 시험 도면 | 기존 6세트의 `.pdf`·`01_*.png`·`01_*.jpg` (`.drawio.png`·`.drawio.svg`는 정답 누출로 제외) | 사용 가능 |
| 딥러닝 | 후속(MVP 제외) | — |

## 8. W2 이후 작업 단위 제안

| ID(안) | 작업 | 완료 기준 | 의존성 |
|---|---|---|---|
| `W2` | 정답지 변환과 평가 하네스 | `scripts/check_adapter.py`가 drawio `extraction.json`을 시각 정답지로 바꾸고, drawio 결과 자신을 입력으로 넣었을 때 기호·관계 F1=1.0, 비시각 속성 분리 집계, 결정적 출력(두 번 실행 결과 동일). `tests/test_adapter.py` 통과 | 사용자 결정 1(지표·대응 기준) |
| `W3` | 벡터 PDF 어댑터 MVP | `hazop/extract/adapters/pdf_vector.py`가 샘플 6쪽에서 같은 스키마의 `extraction.json`을 만들고 구조 검증 통과(blocker 0), 좌표 정렬 잔차 보고. W2 하네스로 6세트 지표 표를 `evidence/`에 기록(목표치는 첫 측정 후 결정) | W2, 사용자 결정 2 |
| `W4` | 래스터 어댑터 MVP | PNG·JPG 6세트에서 같은 스키마 출력, OCR 미설치 시 문자 항목을 미확인으로 남기며 실패하지 않음. 지표 표 기록 | W2, 사용자 결정 3 |
| `W5` | 열화 시험과 결과 정리 | Pillow로 만든 변형(JPG 품질·해상도·회전·노이즈) 지표 비교표, 한계와 후속(실제 도면·딥러닝) 권고를 `evidence/`에 기록, `specs/extraction.md` 다른 자료형 절 갱신안 | W3, W4 |

## 9. 사용자 결정이 필요한 항목

1. **평가 기준 승인:** 태그 비교를 속성 `tag`가 아닌 보이는 문자 기준으로 하고, 비시각 속성을 분모에서 빼는 방식, IoU 0.5 시작값, 주 지표를 관계 F1로 하는 안.
2. **PDF 라이브러리 채택:** pdfplumber(MIT)를 어댑터 의존성으로 채택할지. PyMuPDF(AGPL)는 평가 도구로만 쓸지, 아예 쓰지 않을지.
3. **래스터 도구 설치:** OpenCV(`opencv-python-headless`) pip 설치, Tesseract 실행 파일(UB Mannheim 설치본) 설치 여부. 설치하지 않으면 numpy·Pillow만으로 범위를 줄인다.
4. **draw.io 데스크톱 설치 여부:** 새 시험 도면을 CLI로 일괄 내보낼지, 기존 6세트와 사용자 수동 내보내기로 충분한지.
5. **기존 샘플 PDF·PNG의 판 일치 확인:** 2026-11-03 내보낸 파일이 현재 `.drawio`와 같은 판인지 사용자가 확인하거나, 재내보내기를 허용할지.
6. **등록 단계 연계:** PDF·PNG 등록 허용(`hazop/register/`, 이 트랙 편집 범위 밖)을 이 트랙 범위에 넣을지, 소유 트랙에 요청할지.

## 10. 직접 검증할 부분

- 라이선스: PyMuPDF·pdfplumber·OpenCV·Tesseract의 LICENSE 원문(이 조사는 문서 페이지·요약 기준).
- 논문 수치: 초록·요약만 읽었으므로 인용 전에 원문 확인.
- draw.io CLI 플래그 철자: 설치 후 `--help`로 확인.
- 1-4의 배율 추정(PNG 2배·테두리 10, PDF 약 0.72배)은 산술 추정이며 W3·W4 정렬 결과로 확인.
