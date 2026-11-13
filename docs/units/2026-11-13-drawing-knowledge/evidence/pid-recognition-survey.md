# P&ID 도면 인식 알고리즘 조사 (2026-11-14)

벡터 PDF 추출기(`hazop/extract/adapters/pdf_vector*.py`)의 남은 약점을 풀 방법을 인터넷의 1차 자료(논문, 공식 문서, 저장소)에서 찾고, APR1400 범례(그림 1.7-1)를 기호 사전·종류 목록과 맞대 본 기록입니다. 코드는 고치지 않았습니다. 지금 값과 원인은 [read-quality-log.md](read-quality-log.md)의 '남은 가장 큰 원인'(@2707400)을 기준으로 합니다.

## 결론

1. **선 굵기와 점선 무늬를 원소에 남겨 선 종류로 쓰기**(효과 가장 큼, 품 작음, 새 의존성 없음). 008쪽 꺾인 점선·일점쇄선 배관(놓친 쌍 약 200)과 072쪽 방 경계선(오검출 116)을 겨눕니다. 지금은 선 굵기를 읽지 않고, 점선은 조각으로 나누면서 무늬 종류를 버립니다. 008쪽에는 일점쇄선과 점선이 무늬 배열로 갈리고(§4.1), 072쪽에는 1.08pt 굵은 선 79개가 따로 있습니다.
2. **이름표 짝짓기를 가까운 것부터가 아니라 한 번에 일대일로 배정하기**(품 작음, `networkx`의 `max_weight_matching` 사용, 이미 배포 의존성이고 BSD-3). 수동 밸브 번호 70개, 계기 비석 32개를 놓친 '밸브 번호 짝짓기'를 겨눕니다.
3. **기호 견본을 원소 관계 그래프로 두고, 원소가 남거나 모자라도 맞추는 부분 그래프 맞춤과 투표로 겹친 묶음 가르기**(품 중간, `networkx`). 105·008쪽 안전밸브 29개(번호 원·등급 마름모와 한 묶음)를 겨누고, 새 종류를 들일 때 조건문 대신 견본 하나만 더하는 길이 됩니다.
4. **교차·꺾임 노드를 분명히 하고 끝이 빈 분기를 지우는 그래프 정리**(품 작음, 새 의존성 없음). 105쪽 U자 이음쇠·빈 분기점 오검출 107을 겨눕니다.
5. **학습 모델은 지금 들이지 않습니다.** 벡터 원소를 직접 분류하는 모델(SymPoint·VecFormer)은 평면도로만 학습돼 P&ID 가중치가 없고, 스캔 단계 검출기는 Ultralytics(AGPL-3.0) 대신 RF-DETR(Apache-2.0)을 ONNX Runtime으로 돌리는 쪽이 맞습니다. OCR은 이미 평가용 venv에 있는 `rapidocr-onnxruntime`부터 씁니다.

## 1. 조사 방법과 읽는 법

- 웹 검색과 쪽 읽기만 했습니다. 소프트웨어는 내려받거나 설치하지 않았습니다. 검색어에는 프로젝트·도면 이름을 넣지 않았습니다.
- 넓은 검색은 하위 에이전트 셋(Sonnet 5.5)에 나눠 맡겼습니다: ① 벡터·CAD 기호 인식과 선 추적, ② 래스터 P&ID 인식·데이터 집합·오픈소스, ③ 큰 언어·시각 모델, 상용 제품, DEXPI. 세 에이전트가 읽은 출처는 합쳐 약 80개입니다. 여러 논문은 PDF 본문을 읽지 못해 초록과 소개 쪽으로만 확인했고, 그런 항목은 표에 '초록만'이라고 적었습니다.
- 수치는 논문이 밝힌 지표와 데이터 그대로 옮겼습니다. 논문마다 '맞음'의 정의와 시험 도면 수(5~12장)가 달라 **서로 견줄 수 없습니다.** 우리 `check_read_quality.py` 값과도 견줄 수 없습니다.
- GitHub 저장소의 마지막 갱신일은 읽은 쪽에 나오지 않아 적지 못했습니다(§9).

## 2. 지금 추출기의 순서와 약점

`pdf_vector.analyze`는 이 순서로 일합니다. ① pdfplumber로 글자와 원소(선·사각형·곡선, 채움·흰색 여부, 점선 배열)를 읽음 → ② 원소를 몸체·열린 선·표식·점선 조각으로 가름 → ③ 검게 칠한 견본을 기호로 올림 → ④ 글자 묶음, 등급 경계 표시 → ⑤ 겹침·근접 규칙과 union-find로 기호 묶기(`pdf_vector_grouping`) → ⑥ 실선 배관 사슬, 점선 사슬 → ⑦ 부속 기호 합치기 → ⑧ 화살촉으로 흐름 방향 → ⑨ 손으로 쓴 구조 특징(나비꼴, 원 하나, 비석, 스프링, 평행판)과 견본 격자 맞춤으로 종류 → ⑩ 거리 규칙으로 이름표 붙이기.

'남은 가장 큰 원인'을 이 조사에서 쓸 이름으로 줄이면 다음과 같습니다.

| 약칭 | 원인(read-quality-log, @2707400) | 걸린 값 |
| --- | --- | --- |
| (가) 겹친 묶음 | 105·008쪽 안전밸브가 번호 원·등급 마름모와 한 기호로 묶임 | 기호 종류 29, 태그 36 |
| (나) 꺾인 점선 | 008쪽 점선·일점쇄선 배관이 꺾여 지나가는데 곧은 점선만 배관으로 봄, 패키지 경계 일점쇄선 상자와 갈라야 함 | 연결 놓친 쌍 약 200 |
| (다) 경계선·빈 분기 | 072쪽 HVAC 방 경계선이 덕트와 이어짐, 105쪽 U자 이음쇠·빈 분기점 | 연결 오검출 116 + 107 |
| (라) 번호 짝짓기 | 수동 밸브 번호, 안전밸브 번호, 계기 비석 | 태그 70 + 36 + 32 |
| (마) 목록 밖 종류 | 정답 종류 `unlisted` 155 | 기호 종류 상한 약 88% |

## 3. 방법별 표

'맞는가' 열의 품은 작음(며칠), 중간(1~3주), 큼(몇 달 또는 학습 데이터·GPU 필요)입니다.

### 3.1 벡터 원소에서 직접 기호 찾기

| 방법 | 입력 | 핵심 생각 | 보고된 성능과 조건 | 출처 | 우리에게 맞나 |
| --- | --- | --- | --- | --- | --- |
| Messmer·Bunke 오차 허용 부분 그래프 동형 맞춤 | 벡터(속성 관계 그래프) | 원소를 노드, 닿음·평행·동심·안에 듦을 간선으로 둔 그래프로 견본을 만들고, 도면 그래프에서 원소가 하나 더 있거나 빠져도 맞추는 부분 그래프를 찾음. 견본을 미리 결정 나무로 엮어 빠르게 함 | 읽은 자료에 수치 없음(본문 못 읽음) | [Springer 1996](https://link.springer.com/doi/10.1007/3-540-61226-2_11), IEEE PAMI 1998 | **맞음, 품 중간.** (가)(마). `networkx`의 VF2 계열 맞춤으로 시작할 수 있음(오차 허용은 직접 구현). 새 기호를 조건문이 아닌 견본으로 더함 |
| Rusiñol·Lladós 벡터 서명·관계 색인 | 벡터 | 원소 쌍(종류, 상대 거리, 상대 각도)을 색인해 후보 자리를 찾고, 허프 방식 투표로 확인. 이웃 기호에 일부 가려져도 표가 모임 | '좋은 성능'이라고만 함, 수치 못 읽음(건축 도면) | [GREC 2005, LNCS 3926](https://springerlink.bibliotecabuap.elogim.com/doi/10.1007/11767978_4), Pattern Recognition Letters 31(2010) | **맞음, 품 중간.** (가). 순수 파이썬으로 가능. 부분 그래프 맞춤 앞의 후보 거르기로 좋음 |
| Luqman 등 구조 서명(퍼지 구간) | 벡터 | 관계 그래프를 고정 길이 수치 서명으로 바꿔 거리로 견줌 | 수치 못 얻음 | [arXiv 1004.5427](https://arxiv.org/abs/1004.5427) | 보통. 부분 그래프 맞춤 앞의 값싼 거르기 |
| Dosch·Tombre 건축 도면 분석 | 래스터 → 벡터화 | 벡터화 → 호·닫힌 고리 → 관계 그래프 → 부분 그래프로 기호 | 건축 도면 11장, 정밀도·재현율 없음 | [Tombre 논문 목록](https://members.loria.fr/KTombre/ahsoon-sspr98.pdf) | 순서는 우리와 거의 같음. 닫힌 고리를 독립 노드로 두는 생각만 가져옴 |
| Zernike 모멘트·shape context | 래스터·윤곽 | 회전에 변하지 않는 모양 기술자 | 손그림 기호 7,410개에서 97%(한 연구, 검색 요약) | [기술자 비교](https://core.ac.uk/download/49967358.pdf) | 낮음. 깨끗이 갈린 묶음에만 통하고 (가)에는 소용없음. 지금 견본 격자 맞춤과 겹침 |
| 2015 IEEE, SVG 공학 문서의 구조·연결 객체 인식 | 벡터(SVG/PDF), P&ID 사례 | 벡터 원소에서 기호·주석·연결을 바로 인식 | '믿을 만한 성능', 수치 초록에 없음 | [IEEE 7301510](https://ieeexplore.ieee.org/document/7301510) | 우리와 가장 가까운 선례. 본문을 따로 구해 읽을 값어치 있음 |
| 스탠퍼드 CIFE TR112, DXF 기반 P&ID 인식 | 벡터(DXF) | CAD 원소에서 P&ID 기호 인식 | 다룬 기호 인스턴스의 95%를 한 쪽 전체에서 인식(보고서 표현, 조건 미확인) | [CIFE TR112](https://swap.stanford.edu/was/20160311035101mp_/http://cife.stanford.edu/sites/default/files/TR112.pdf) | 참고. 벡터 P&ID가 풀 만한 문제라는 근거 |

### 3.2 벡터 원소를 학습 모델로 분류(평면도 panoptic symbol spotting)

다섯 방법 모두 FloorPlanCAD(건축 평면도, 문·벽·가구 등 35종)로만 학습·평가했고, P&ID 가중치나 데이터는 찾지 못했습니다. 아래 PQ(panoptic quality)는 모두 FloorPlanCAD 시험 집합 값입니다.

| 방법 | 핵심 생각 | 보고된 성능 | 출처·저장소 | 우리에게 맞나 |
| --- | --- | --- | --- | --- |
| FloorPlanCAD + PanCADNet (ICCV 2021) | 원소 단위로 35종 라벨, CNN + GCN | PQ 55.3(SymPoint 논문의 비교표). 다른 요약은 56.1로 적어 두 값이 어긋남 | [arXiv 2105.07147](https://arxiv.org/abs/2105.07147), [데이터](https://floorplancad.github.io/) | 원소별 정답 형식만 참고 |
| CADTransformer (CVPR 2022) | 원소를 토큰으로, 이웃 인지 주의 | PQ 68.9(SymPoint 표), 초록은 59.5 → 68.5 | [VITA-Group/CADTransformer](https://github.com/VITA-Group/CADTransformer), MIT, Python 3.7·PyTorch 1.9 | 낮음. 낡은 환경, 래스터도 씀 |
| GAT-CADNet (CVPR 2022) | 원소 = 노드, 공간 관계 = 간선, 그래프 주의망이 '같은 기호' 간선을 예측 | PQ 73.7(SymPoint 표) | [arXiv 2201.00625](https://arxiv.org/abs/2201.00625), 저장소 못 찾음 | 생각만: 원소 쌍마다 '같은 기호인가'를 판정하는 것이 (가)의 정확한 문제 정의 |
| SymPoint (ICLR 2024) | 원소를 점(중점·각도·길이·종류)으로, 끝점이 1px 안이면 이음(이음 수 상한 K) | PQ 83.3(1000 epoch), 79.6(300 epoch), 도면당 66ms | [arXiv 2401.10556](https://arxiv.org/abs/2401.10556), [nicehuster/SymPoint](https://github.com/nicehuster/SymPoint)(라이선스 종류 확인 못 함, 공개 코드에서 이음 모듈은 빠졌다고 README가 밝힘) | 규칙 하나만 가져옴: 끝점 이음에 상한을 두는 것 |
| SymPoint-V2 (2024) | CAD 레이어를 원소 특징에 넣음 | 사전 정보(레이어) 있으면 PQ 90.1, 없으면 83.2(VecFormer 논문 비교표) | [arXiv 2407.01928](https://arxiv.org/abs/2407.01928) | **교훈이 큼**: 레이어 하나로 PQ 약 7 상승. PDF에는 레이어 대신 선 굵기·색·점선 무늬·선택 내용 묶음(OCG)이 있음 → 결론 1의 근거 |
| VecFormer (2025) | 원소를 선분 열로 표본화, 묶음 라벨과 원소 라벨을 학습 없이 투표로 맞춤(Branch Fusion Refinement) | PQ 91.1(사전 정보 있음), 88.4(없음). A100 8장, 500 epoch | [arXiv 2505.23395](https://arxiv.org/abs/2505.23395), [WesKwong/VecFormer](https://github.com/WesKwong/VecFormer), Apache-2.0 | 투표 단계는 규칙으로 옮길 수 있음: 묶음 종류를 정한 뒤 어긋나는 원소를 떼어 냄 → (가) |
| CADSpotting (2024), ArchCAD-400k·DPSS (NeurIPS 2025) | 큰 도면을 창으로 나눠 투표 / 이미지·원소 특징 섞기 | PQ 88.9 / 86.2(없음)·89.5(있음), 둘 다 VecFormer 비교표 | [arXiv 2412.07377](https://arxiv.org/abs/2412.07377), [arXiv 2503.22346](https://arxiv.org/abs/2503.22346), [ArchiAI-LAB/ArchCAD](https://github.com/ArchiAI-LAB/ArchCAD)(학술용 표시, 조건 미확인) | 낮음 |

### 3.3 선 종류, 배관 추적, 이름표, 흐름, 도면 간 연결

| 방법 | 입력 | 핵심 생각 | 보고된 성능과 조건 | 출처 | 우리에게 맞나 |
| --- | --- | --- | --- | --- | --- |
| PDF 점선 배열 직접 읽기 | 벡터 | PDF의 점선 연산자(`d`)는 배열과 위상을 경로 전체에 적용하므로, 경로 하나가 꺾여도 무늬는 하나. 배열이 두 값이면 점선, 네 값이면 일점쇄선 | 해당 없음(형식 규격) | [pdfplumber README](https://cdn.jsdelivr.net/gh/jsvine/pdfplumber@stable/README.md)의 `dash` 속성, PDF 규격 8.4.3.6 | **이미 읽고 있으나 반만 씀.** `load_page`가 `dash`를 읽고 `_dash_pieces`가 조각과 원본 경로 ID(`src`)를 남기지만, 무늬 종류와 선 굵기는 버림 → 결론 1 |
| Liu·Dori GILDA, 점선 검출 대회(Kong 등), Agam 등 | 래스터 → 벡터화 | 짧은 선분을 길이·간격이 고른 사슬로 이음. 곡선 점선은 접선 연속성으로 다음 조각을 예측 | 수치 못 읽음(본문 못 구함) | [GILDA](https://www.academia.edu/827410/A_Generic_Integrated_Line_Detection_Algorithm_and_Its_Object_Process_Specification), [대회](https://rd.springer.com/content/pdf/10.1007%2F3-540-61226-2_23.pdf) | 점선이 원소 하나가 아니라 조각마다 따로 그려진 PDF에만 필요. APR1400 008·105쪽은 배열로 그려 있어 덜 급함 |
| Digitize-PID 선 단계 (PAKDD 2021) | 래스터 | 형태학 연산 + DBSCAN, 점선은 길이·간격이 고른 조각 열, 불규칙한 건너뜀 세 번이면 버림 | 합성 데이터에서 온전한 선 99.34%(90,774/91,416), 점선 82.91%(20,620/24,848). 곧은 점선만 | [arXiv 2109.03794](https://arxiv.org/abs/2109.03794) | 점선이 학습 파이프라인에서도 가장 약한 단계라는 근거. 스캔 단계에서 참고 |
| Moon 등 선·흐름 화살표 인식 (Appl. Sci. 2021) | 래스터 | 테두리·표제란을 먼저 지우고, 연속선 → 선 표식(선 종류) → 흐름 화살표 | 시험 도면 9장, 평균 정밀도 96.14%, 재현율 89.59%(세는 규칙 못 읽음). 2023 후속 95.26%·91.25% | [MDPI 11/21/10054](https://mdpi.com/2076-3417/11/21/10054/htm) | 테두리·표제란을 먼저 빼는 순서만 참고(우리는 이미 표제란을 찾음) |
| Kim·Kim GNN 선 기능 분류 (IEEE Access 2023) | 기호·선 그래프 | GraphSAGE로 선 하나하나를 배관/신호선으로 노드 분류. 실제 P&ID 19장으로 학습 | 수치 못 얻음 | [DOAJ](https://doaj.org/article/113230a7d0a64d8597992e9c9ee1f1bd) | (다)를 학습 문제로 본 것. 규칙판(굵기·무늬·차수·끝 종류)이 먼저 |
| Stürmer 등 Relationformer와 PID2Graph (DSAA 2025) | 래스터 | 기호와 간선을 함께 예측. 그래프에 '교차' 노드(선 셋 이상)와 '꺾임(ankle)' 노드를 둠. 글자를 지운 뒤 선 검출 | OPEN100(실제 12장) IoU 0.5: 간선 mAP 76.79(조각)/75.46(이어 붙인 전체), 기호 mAP 73.49/73.14. 같은 조건 모듈식 기준선(Faster R-CNN + CRAFT/EasyOCR + 허프) 간선 mAP 45.89, 기호 mAP 76.99 | [arXiv 2411.13929](https://arxiv.org/abs/2411.13929), [데이터 Zenodo 14803338](https://zenodo.org/records/14803338)(CC BY-SA 4.0, 9.3GB) | 노드 분류(기호·교차·꺾임)를 그래프 정리 규칙으로 가져옴 → 결론 4. 모델은 코드 없음 |
| 이름표 짝짓기: Digitize-PID | 래스터 | 기호마다 가까운 글자 k=5개를 보고 정규식이나 쪽 안에서 가장 많은 꼴로 고름, 겹치면 가까운 쪽. 배관 번호는 BFS로 퍼뜨림 | 별도 수치 없음 | [arXiv 2109.03794](https://arxiv.org/abs/2109.03794) | 정규식 먼저, 거리 다음은 우리와 같음 |
| 이름표 짝짓기: 일대일 배정 | 벡터·래스터 | (글자, 기호) 비용표에 거리 + 꼴 맞음(밸브 번호 꼴 ↔ 밸브, 계기 태그 꼴 ↔ 계기) + 지시선 보너스를 넣고 한 번에 최적 배정 | 견준 논문 없음. 하위 에이전트와 이 보고서의 제안 | — | **맞음, 품 작음.** (라). 지금은 가까운 순서로 하나씩 정해 먼저 차지한 쪽이 이김(개선 13이 그 부작용을 고친 것) |
| Azure 예제 화살표 방향 설계 | 래스터 | 화살표가 닿은 두 선의 기울기가 같으면 방향을 정하지 않음 | 수치 없음 | [arrow-direction-detection-design.md](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams/blob/main/docs/arrow-direction-detection-design.md) | 애매하면 '모름'으로 두는 규칙만 참고. 벡터 화살촉은 꼭짓점으로 방향이 정확함(이미 개선 1·11) |
| 도면 간 연결 | — | 찾은 공개 방법 없음. 2025년 논문(Prusty 등)이 '아직 다루지 않은 문제'로 적음 | — | [arXiv 2505.11976](https://arxiv.org/abs/2505.11976) | 우리 규칙(계통 약어·시트·도면번호)이 앞서 있음 |

### 3.4 큰 언어·시각 모델(2024~2026)

| 방법 | 입력 | 핵심 생각 | 보고된 성능과 조건 | 출처 | 우리에게 맞나 |
| --- | --- | --- | --- | --- | --- |
| AWS 예제 'P&ID digitization' v2 | PDF를 300dpi 그림으로 바꿈 | 모델이 기호·글자 읽기 → 배관 추적 → 검토 에이전트가 고침. 타일·한 번 호출·한 번 + 검토 세 방식 | Digitize-PID 합성 도면 10장, 방식마다 한 번 실행. 글자 F1(정확한 문자열) 93~99%. 연결 F1: 한 번 호출 59~88%, 타일 81~91%, 기본(한 번 + 검토) 91%, 예전 검출기 기반 v1 17%. 같은 쪽도 실행마다 9점까지 흔들림 | [aws-solutions-library-samples/guidance-for-piping-and-instrumentation-diagrams-digitization-on-aws](https://github.com/aws-solutions-library-samples/guidance-for-piping-and-instrumentation-diagrams-digitization-on-aws), MIT-0 | 글자는 쉽고 연결이 약하다는 근거. 타일 + 검토가 효과 큼. 채점기(문자열 정확 일치, 합산 P/R)는 AI 후보 측정에 참고 |
| TU Delft HVAC P&ID 포스터 (BuildSys 2025) | 그림 | GPT-4o 영샷 기호 검출, SAM과 쪽 전체 맥락을 더함 | mAP50 16.99% → 31.05% | [TU Delft 저장소](https://repository.tudelft.nl/record/uuid:9a9fbb50-c77c-4c91-bec4-5f84b54bbeb8) | 모델 혼자 기호를 찾게 하면 안 된다는 근거 |
| AECV-Bench (2026) | 건축 도면 그림 | 세기와 도면 질의응답 | 글자·질의응답 정확도 최대 0.95, 기호 세기 0.40~0.55 | [arXiv 2601.04819](https://arxiv.org/abs/2601.04819) | 작은 기호 세기가 약점 |
| SINA (2026, 회로도 → 넷리스트) | 그림 | 검출기 + 연결 성분 라벨링(배선) + OCR, 모델은 부품 기호 이름만 붙임 | 넷리스트 정확도 96.47%(지표 정의와 비교 대상은 초록에 없음) | [arXiv 2601.22114](https://arxiv.org/abs/2601.22114) | **우리와 같은 나눔**: 기하는 결정적, 모델은 이름만 |
| Zhu 등 (2026) P&ID → 공정 그래프 | 그림 | 태그 읽기와 연결 재구성을 두 단계로 나눔 | 초록만: 나누는 쪽이 끝에서 끝까지보다 낫다고 함, 수치 못 읽음 | [arXiv 2607.19568](https://arxiv.org/abs/2607.19568) | 같은 결론 |
| ChatP&ID (AIChE J. 2026), Talking like P&IDs (2025) | DEXPI → 지식그래프 | 그림 대신 그래프를 모델에 줌 | 초록: 그림보다 정확도 +18%, 토큰 −85%(질문 수·채점 방식 초록에 없음). 앞 논문은 줄인 그래프가 전체 그래프보다 추적 점수 약 20% 높음(P&ID 1장) | [arXiv 2603.22528](https://arxiv.org/abs/2603.22528), [arXiv 2502.18928](https://arxiv.org/abs/2502.18928) | 읽기 뒤 단계(질의, HAZOP 초안)에 그래프를 주는 지금 방향이 맞다는 근거 |
| LLM HAZOP 자동화 (Safety Science 2026) | P&ID 그림 | GPT-4o 등으로 워크시트 생성 | 전문가 기준 유사도 F1 86% 넘음, 그러나 뜻이 맞는 시나리오는 0.19~0.37(검색 요약만, 본문 못 읽음) | [KFUPM 색인](https://pure.kfupm.edu.sa/en/publications/can-large-language-models-automate-the-hazop-process-without-huma/) | 유사도 점수가 높아도 쓸 만한 비율은 낮을 수 있다는 경고 |

### 3.5 상용 제품과 표준(공개된 설명만)

| 이름 | 입력 | 밝힌 처리 단계 | 정확도 | 결과 형식 | 출처 |
| --- | --- | --- | --- | --- | --- |
| 안트로피 AutoPID | CAD, PDF, 스캔 | 공급사마다 다른 기호 표준화 → 설비·배관 연결 분석 → 자연어 검색 결과를 도면 위 배관 경로로 보여 줌, 변환 중 물량(MTO) 추출. 도입은 도면 조사 → 기호 표준 → 일괄 변환 → 검증 후 인도 | 수치 없음(검증 단계에서 시나리오로 확인한다고만 함) | 내보내기 형식은 밝히지 않음, 사내 설치 | [antropy.co.kr](https://antropy.co.kr) 첫 쪽(AutoPID 하위 쪽은 404) |
| Cognite 도면 해석 | PDF·그림. 전체 해석은 벡터 파일만, 첫 쪽만(공개 미리보기) | 기호 사전으로 기호 찾기 → 태그·기호 합치기 → 연결 → 사람 검토(탭별) | 수치 없음, 자동 결과는 모두 사람이 검토하라고 권함 | 데이터 모델 연결 | [Cognite 문서](https://docs.cognite.com/cdf/integration/guides/contextualization/parse_diagrams) |
| Everllence(AWS 사례) | 원본 PDF + 스캔 | 원본 PDF에서 글자·선을 바로 읽음, 견본 맞춤으로 기호, 사람 검토 도구, Neo4j 그래프, 에이전트 | 수치 없음. 100%가 아니면 사람 검토가 메운다고 밝힘 | 그래프 + 자연어 답 | [AWS 블로그](https://aws.amazon.com/blogs/industries/how-everllence-scaled-pid-intelligence-to-improve-plant-operations/) |
| Microsoft Azure 예제 | 그림 | YOLOv5 기호(합성 500장 학습) → OCR → 세선화 + 허프 선 → 끝점 짝 → BFS 흐름 | 자산·연결의 약 80%를 찾음(지표 정의 없음) | SQL 그래프 | [Azure-Samples 저장소](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams)(MIT), [ISE 블로그](https://devblogs.microsoft.com/ise/engineering-document-pid-digitization/) |
| Yokogawa Design Diagram Converter | 2D CAD P&ID | 사용자가 정한 모양·글자·연결 규칙으로 패턴 맞춤 | '노동 60% 감소'(기준·시험 도면 밝히지 않음) | CSV, ISO 15926 XML(Proteus 4.1) | [Yokogawa](https://www.yokogawa.com/kr/solutions/products-and-services/information/connected-intelligence/oprex-data-model-broker/) |
| deepsense.ai, PIDIntel, IOMOSAIC SmartPFID | 그림·PDF | 각자 학습 모델 | '93%', '>90%', 없음. 모두 조건 없음 | DEXPI 등 | 각 회사 쪽 |
| AVEVA, Hexagon, COMOS, Bentley, Aspen, 국내 EPC 도구 | — | PDF 인식 기능을 공개한 쪽을 찾지 못함. AVEVA는 DEXPI를 받는 쪽으로 보임(자료표 미확인) | — | — | — |

DEXPI 쪽에서는 다음을 확인했습니다.

- 최신 규격은 DEXPI 2.0/2.0.1(2025년 말)이고 새 XML·JSON 직렬화를 둡니다. 예전 교환 형식은 Proteus XML 4.0.1(Yokogawa는 4.1을 씀)이며, 4.2판은 찾지 못했습니다. 규격 저장소는 [GitLab](https://gitlab.com/dexpi/Specification)으로 옮겼습니다.
- [pyDEXPI](https://github.com/process-intelligence-research/pyDEXPI)는 PyPI 2.1.0(2026-11-01), **AGPL-3.0**, Python 3.12 이상입니다. Proteus 가져오기는 되지만 내보내기는 1.2.0부터 뺐습니다. NetworkX 그래프, SVG 그리기, 합성 P&ID 생성기, MCP 서버가 있습니다. 앱에 넣으면 AGPL 의무가 생기므로, 바깥에서 우리 내보내기 결과를 검사하는 데만 쓰는 것이 안전합니다.
- 인식 결과를 DEXPI로 표현할 때 확신도·출처를 담는 표준 필드는 찾지 못했습니다. AWS 예제는 DEXPI 1.3 이름과 Proteus 4 배치를 흉내 내지만 XSD 검사는 하지 않는다고 밝힙니다.

## 4. 우리 도면에서 확인한 것

조사 결과가 우리 도면에 통하는지 보려고 APR1400 네 쪽의 원소 속성을 셌습니다(읽기만, 2026-11-14, 시험용 venv의 pdfplumber 0.11.9, `by-drawing/` 각 PDF 첫 쪽, 선·사각형·곡선 전체).

### 4.1 점선 무늬와 선 굵기

| 쪽 | 원소 수 | 점선 무늬(배열, 개수) | 많은 선 굵기(pt, 개수) |
| --- | --- | --- | --- |
| 008 | 1,482 | 일점쇄선 [10.667, 5.333, 1.333, 5.333] 52, 점선 [10.667, 5.333] 28, 그 밖 [4.667, 3.333] 4, [5.333, 2.667] 4 | 0.13 759, 0.25 253, 0 112, 0.55 35 |
| 012 | 269 | 없음 | 0 127, 0.41 39 |
| 072 | 992 | 없음 | 0.13 496, 0 119, **1.08 79**, 0.06 54 |
| 105 | 1,997 | [5.333, 2.667] 34, [10.667, 5.333] 24 | 0 726, 0.13 467, 0.06 201, 0.25 94, 0.31 42, 1.04 18 |

- 008쪽은 일점쇄선과 점선이 **배열 길이로 바로 갈립니다**(4값 대 2값). 한 경로가 꺾이면 그 경로 하나에 무늬가 하나이므로 꺾인 점선 배관을 경로 단위로 다룰 수 있습니다. 지금 코드는 `_dash`로 배열을 읽고 `_dash_pieces`가 원본 경로 ID를 남기지만, 무늬 종류는 사슬까지 가져가지 않습니다.
- 선 굵기는 `load_page`가 읽지 않습니다(`pdf_svg.py`만 그림 그릴 때 씀). 072쪽의 1.08pt 선 79개가 방 경계선인지 덕트인지는 그림으로 확인하지 않았습니다. **방 경계선이 굵은 선이라는 것은 가설입니다.**
- 모든 원소가 `Artifact` 꼬리표이고 선택 내용 묶음(OCG)·색 구분은 없습니다(빨간 원소 2개 빼고). 그래서 SymPoint-V2가 말한 '레이어'에 해당하는 신호는 이 도면에서 선 굵기와 점선 무늬뿐입니다.

### 4.2 이미 하고 있는 것

조사한 방법 가운데 이미 들어 있는 것: 표제란 찾기(Moon 등의 테두리·표제란 제거), 벡터 화살촉 꼭짓점으로 흐름 방향(개선 1·11), 끊어 그린 엇갈림을 교차로(개선 7, Stürmer의 교차 노드와 같은 생각), 정규식 먼저 거리 다음 이름표 붙이기(Digitize-PID와 같음), 견본 격자 맞춤(기술자 맞춤과 같은 무리), 사람 확정을 거치는 AI 후보(Cognite·Everllence와 같은 나눔).

## 5. 바로 해 볼 실험

값은 모두 `check_read_quality.py`의 APR1400 12쪽, 출발점 @2707400(기호 종류 728/1288, 태그 402/755, 연결 1104/2648, 속성 419/634)입니다. **기대 상승은 모두 추정**이고, 근거는 read-quality-log의 원인별 건수입니다. 상한(그 원인을 모두 고쳤을 때)과 추정 범위를 함께 적습니다.

### 실험 1. 점선 경로를 무늬째 배관으로 (나)

- **바꿀 것**: `load_page`에서 점선 배열의 종류(2값 점선, 4값 일점쇄선)를 원소에 남기고 `_build_dashed`까지 넘김. 점선 경로를 조각 사슬이 아니라 **원본 경로 단위**로 보고, 꺾여도 하나의 배관 후보로 둠. 경로가 닫혔거나 거의 직사각형이면 패키지 경계, 열린 경로이면서 두 끝이 밸브 축·배관 끝에 닿으면 배관.
- **기대**: 연결. 008쪽 놓친 쌍 약 200이 상한. 그 가운데 50~150쌍을 되찾는다고 보면 1104/2648(41.7%) → 1154~1254/2648(43.6~47.4%). 패키지 경계 상자가 일점쇄선이 아니라면 오검출 위험은 작음.
- **근거**: §4.1(008쪽 무늬 두 종류), PDF 점선 규격, Digitize-PID에서 점선이 가장 약한 단계였다는 점.
- **품**: 작음. 새 의존성 없음.
- **먼저 볼 것**: 008쪽 패키지 경계 상자의 무늬 배열. 정답지 `limits`(2)는 '범례에서 일점쇄선 뜻을 확인하지 못함'이라고 적었으므로, 범례 4/4쪽의 신호선 무늬와 같은 배열인지도 함께 봐야 합니다.

### 실험 2. 선 굵기로 방 경계선 가르기 (다)

- **바꿀 것**: `load_page`에서 `linewidth`를 원소에 남김. 072쪽에서 굵기별로 선을 그림에 겹쳐(`crop.py`) 방 경계선의 굵기를 확인한 뒤, 그 굵기 사슬에는 기호를 붙이지 않고 다른 굵기 사슬과 분기점에서 잇지 않음.
- **기대**: 연결 오검출. 072쪽 116이 상한. 60~116을 없애면 분모가 줄어 1104/2588~2532(42.7~43.6%). 놓친 쌍을 되찾지는 않으므로 오르는 폭이 작음.
- **근거**: SymPoint-V2의 레이어 특징(PQ 83.2 → 90.1, 평면도), §4.1의 072쪽 1.08pt 선 79개.
- **품**: 작음(굵기 확인이 맞으면). 가설이 틀리면 효과 없음.

### 실험 3. 이름표 일대일 배정 (라)

- **바꿀 것**: `_valve_labels`의 '가까운 것부터 하나씩'을, 쪽 전체의 (번호 글자, 밸브) 비용표 위 최대 가중 짝짓기로 바꿈. 비용은 거리 + 꼴 맞음(밸브 번호 꼴 ↔ 종류가 정해진 밸브, 계기 글자 ↔ 계기 비석) + 지시선이 이으면 보너스. `networkx.max_weight_matching`(순수 파이썬, 이미 배포 의존성)을 씀. `scipy`의 `linear_sum_assignment`가 더 빠르지만 지금 venv에 없고 배포 크기가 늘어남.
- **기대**: 태그. 수동 밸브 번호 70 + 계기 비석 32 = 102가 상한(안전밸브 번호 36은 실험 4가 먼저). 20~40을 되찾으면 402/755(53.2%) → 422~442/755(55.9~58.5%).
- **근거**: Digitize-PID의 정규식 + 일관성 규칙, 개선 13(밸브가 아닌 기호가 가져간 번호를 돌려줌)이 '먼저 차지한 쪽이 이기는' 문제를 이미 한 번 보여 줌. 일대일 배정이 낫다는 비교 논문은 찾지 못했습니다.
- **품**: 작음.

### 실험 4. 안전밸브 묶음 가르기: 견본 그래프 맞춤 (가)

- **바꿀 것**: 안전밸브(몸통 + 스프링 + 출구) 견본을 원소 관계 그래프(닿음·평행·안에 듦)로 적고, 105·008쪽 미분류 묶음 안에서 원소가 남아도 맞는 부분 그래프를 찾음. 맞으면 남은 원소(번호 원, 등급 마름모)를 묶음에서 떼어 각자 기호·표시로 돌림(VecFormer의 '묶음 라벨로 투표하고 어긋나는 원소를 떼기'와 같은 생각).
- **기대**: 기호 종류 상한 +29(728 → 757/1288, 58.8%), 번호 원이 풀리면 태그 상한 +36(실험 3과 합쳐 다시 셈). 추정은 종류 +15~29, 태그 +10~30.
- **근거**: Messmer·Bunke, Rusiñol·Lladós(가림에 강한 투표), GAT-CADNet의 '같은 기호 간선' 문제 정의.
- **품**: 중간. `networkx`의 부분 그래프 맞춤(`isomorphism.GraphMatcher`)은 정확 맞춤이라, 원소 한두 개를 빼고 다시 맞추는 오차 허용은 직접 써야 합니다.

### 실험 5. 끝이 빈 분기와 U자 이음쇠 정리 (다)

- **바꿀 것**: 배관 그래프에 기호·교차·꺾임 노드를 따로 두고(PID2Graph 분류), 기호나 이름표 없이 차수 1로 끝나는 짧은 가지를 지움. U자로 꺾여 같은 배관으로 돌아오는 짧은 고리는 기호 쌍을 만들지 않게 함.
- **기대**: 연결 오검출. 105쪽 107이 상한. 40~80을 없애면 1104/2608~2568(42.3~43.0%).
- **근거**: Stürmer 등의 노드 분류, SymPoint의 '끝점 이음 수 상한'.
- **품**: 작음.

다섯 실험은 모두 `pdf_vector*.py`를 고치므로 한 번에 하나씩, 지금 추출기를 고치는 세션의 순서에 맞춰 해야 합니다(`CLAUDE.md` 규칙 4). 효과 대비 품으로는 1 → 3 → 5 → 2 → 4 순서를 권합니다. 실험 2는 굵기 가설을 그림으로 먼저 확인해야 합니다.

결정이 필요해 실험에서 뺀 것: `unlisted` 종류를 종류 목록에 들일지(§7.2, 기호 종류 상한 약 88% → 결정에 따라 더 높아짐), 모양으로 정한 NC를 속성 단위로 셀지(속성 오검출 약 60, read-quality-log).

## 6. 스캔 이미지 단계에 쓸 후보

벡터 품질을 올린 뒤 할 단계입니다. 평가용 venv(`packaging/requirements-raster.txt`)에 이미 `opencv-python-headless`, `numpy`, `rapidocr-onnxruntime`, `onnxruntime`이 있습니다(배포본에는 넣지 않음).

| 단계 | 후보 | 라이선스 | 보고된 성능과 조건 | 판단 |
| --- | --- | --- | --- | --- |
| 기호 검출 | RF-DETR Nano~Large | 코드·가중치(Nano~Large) Apache-2.0, 다른 크기는 PML 1.0 | COCO AP50:95 48.4~56.5(T4, TensorRT FP16, 자체 측정). P&ID 시험 사례는 못 찾음 | **1순위.** 학습은 따로 하고 ONNX Runtime으로 CPU 추론. ONNX 내보내기는 확인 못 함 |
| 기호 검출 | Ultralytics YOLOv5/v8/11 | AGPL-3.0 또는 유료 | P&ID 논문 다수가 씀. ONNX 내보내기 지원 | 배포 앱에 넣으면 AGPL 의무. 평가에만 |
| 기호 검출 | Faster R-CNN(Detectron2) | Apache-2.0(저장소 미확인) | Stürmer 기준선 기호 mAP 76.99(OPEN100, IoU 0.5) | 무거움 |
| 적은 예시 학습 | Gupta 등 클래스 무관 검출 + 소수 예시 라벨 옮김 | [mgupta70/PID_Symbol_Detection](https://github.com/mgupta70/PID_Symbol_Detection) MIT(YOLO 의존이면 AGPL 확인 필요) | 수치 못 찾음(Autom. Constr. 2024) | 범례 쪽 그림을 예시로 쓰는 길과 잘 맞음 |
| 선 검출 | OpenCV LSD, 허프, 형태학 + DBSCAN | Apache-2.0 | Digitize-PID 온전한 선 99.34%·점선 82.91%(합성) | 가볍고 이미 있음. 점선이 약점 |
| 선 검출 | DeepLSD | MIT | 수치 못 읽음 | torch와 Ceres가 필요해 Windows 설치가 무거움 |
| 글자 | RapidOCR(PaddleOCR 모델의 ONNX판) | Apache-2.0 | 공식 비교 없음. 블로그 한 곳에서 15° 돌린 글자에 PaddleOCR 1.0, EasyOCR 0.22, Tesseract 0.0(정식 시험 아님) | **1순위**(이미 평가 venv에 있음). 우리 도면으로 직접 재야 함 |
| 글자 | Tesseract 5 | Apache-2.0 | 같은 블로그에서 돌린 글자에 약함 | 가장 가벼운 대안 |
| 그래프 | Relationformer(Stürmer) | 코드 공개 못 찾음 | OPEN100 간선 mAP 76.79, 모듈식 45.89 | 연구 단계. 실제 도면 약 60장 라벨 필요(인용 논문 기준) |
| 그래프 | SynthPID(2026) | 논문 CC BY 4.0, 저장소 404 | 합성 도면만 학습해 OPEN100 간선 mAP 63.8 ± 3.1 | 합성 학습으로도 꽤 간다는 근거 |

데이터 집합:

- **Dataset-P&ID**(Paliwal 2021): 합성 500장, 기호 32종, 그래프 라벨 없음, 구글 드라이브 배포(원 라이선스 미확인, PID2Graph 기록은 CC BY-SA 4.0으로 적음).
- **PID2Graph**(2025): 합성 부분 + OPEN100(실제 12장, 기호 2,173, 간선 2,100), 기호 7종 + 교차·꺾임, graphml 정답. [Zenodo 14803338](https://zenodo.org/records/14803338), CC BY-SA 4.0. OPEN100 원본은 원전 설계 도면이라 우리 도면과 성격이 가깝습니다.
- **합성과 실제의 차이**가 큽니다. 브라질 학회 논문은 합성으로만 학습한 DETR이 합성 시험에서 약 91, 실제 도면(IPD 2장, OPEN100)에서 4~35였다고 보고합니다([SBC](https://sol.sbc.org.br/index.php/eramiars/article/download/39477/39249), 지표 이름은 못 읽음).

권하는 순서: 우리 벡터 도면을 래스터로 그려 벡터 추출 결과를 정답 삼아 검출기 학습 데이터를 만들면(벡터 → 그림 짝), 라벨을 손으로 붙이지 않고 스캔 단계 학습 데이터를 얻습니다. 이 길을 쓴 논문은 찾지 못했으므로 제안입니다.

## 7. APR1400 범례 대조

### 7.1 무엇을 맞대었나

- 범례: `resources/references/APR1400_DCD/by-drawing/001~004_Ch01_Fig1.7-1_s1~4of4_Flow_Diagram_Symbols_and_Legend.pdf`(그림 1.7-1, 1.7-9~1.7-12쪽). pdfplumber로 글자만 뽑아 항목 이름을 읽었고, 기호 그림은 보지 않았습니다. 그래서 아래 표는 **범례 글자에 적힌 이름** 기준입니다.
- 종류 목록: `hazop/kg/schema/registry.json`의 `kind` 43개.
- 기호 사전: `resources/library/symbols/APR1400/` 22항목, `common/` 21항목.
- 정답지: `tests/fixtures/read-quality/apr1400/*.json` 12쪽 기호 1,288개 가운데 `kind: unlisted` 155개의 `kind_text`.

### 7.2 범례에 있는데 종류 목록이나 사전에 없는 것

'12쪽 정답지' 열은 그 이름(또는 가장 가까운 이름)으로 `unlisted`에 적힌 수입니다. 범례 이름과 정답지 설명의 짝은 제가 글을 보고 맞춘 것이라 그림으로 확인해야 합니다. '—'는 12쪽에 나오지 않은 것입니다.

| 범례 무리(쪽) | 범례 항목(원문) | 종류 목록 | 사전 견본 | 12쪽 정답지 `unlisted` |
| --- | --- | --- | --- | --- |
| 배관 특수품(1/4) | SPRAY NOZZLE OR SPARGER | 없음(`nozzle`은 있으나 스파저를 담는지 정하지 않음) | 없음 | 스파저 13 |
| 배관 특수품(1/4) | FLEXIBLE HOSE, FLEXIBLE CONNECTION, EXPANSION JOINT | 없음 | 없음 | 호스 5, 신축 이음 4 |
| 배관 특수품(1/4) | SILENCER | 없음 | 없음 | 4 |
| 배관 특수품(1/4) | FLAME ARRESTOR | 없음 | 없음 | 2 |
| 배관 특수품(1/4) | FLOW SIGHT GLASS (FG) | 없음 | 없음 | 1 |
| 배관 특수품(1/4) | DIAPHRAGM SEAL | 없음 | 없음 | 4(섬프 바닥 '상자 + 물결', 짝은 추정) |
| 배관 특수품(1/4) | ELECTRIC HEATER | 없음 | 없음 | 2(가압기 전열기 묶음) |
| 배관 특수품(1/4) | TRAP(ST·AT·DT·RT), CONDENSATE POT, OIL SEAL POT, DESUPERHEATER, PULSATION DAMPENER, CAVITATING VENTURI, DELAY COIL, AIR SEPARATOR, COMPRESSION TANK VENT FITTING, ROOF EXHAUST HOOD, FLOW STRAIGHTENING VANE, MIXING TEE, RESTRICTION DEVICE(CAPILLARY) | 없음 | 없음 | 드레인 포트 8(CONDENSATE POT와 같은지 미확인), 나머지 — |
| 배관 특수품(1/4) | RESTRICTION ORIFICE (SINGLE OR MULTI-STAGE) | `orifice` 있음 | `common.orifice_plates`(평행판)만, 상자형 없음 | 008쪽 압력계 노즐 상자는 정답지에 넣을지 결정 대기(read-quality-log '다음에 할 것' 5) |
| 배관 부품(1/4) | HOSE CONNECTION (COUPLER), (QUICK DISCONNECT) | 없음 | 없음 | 커플러 4, 주입 1 |
| 배관 부품(1/4) | BREATHER CAP, PLUGGED TAP, RESIN FILL, REMOVAL SPOOL, THERMAL SLEEVE, SLIP JOINT, INSULATED FLANGE, DIELECTRIC UNION, FLANGED CONNECTION, LOOP SEAL, RUNNING TRAP, P TRAP, ROOF·FLOOR DRAIN | 없음(`drain`·`pipe_cap`·`blind_flange`만 있음) | `apr1400.equipment_drain`만 | 주입 깔때기 2. 플랜지 '\|\|'는 정답지가 기호로 세지 않음 |
| 배관 부품(1/4) | WELDED CAP, SCREWED CAP, BLIND FLANGE | `pipe_cap`·`blind_flange` 있음 | 없음 | — (정답지 `pipe_cap` 12는 목록 안) |
| 배관 부품(1/4) | ATMOSPHERIC VENT (WITH/WITHOUT SCREEN), RELIEF VALVE VENT PIPE | `vent` 있음 | `common.name_vent`(글자로만) | 드립 팬 엘보 20(배기관 입구, 범례에서 같은 이름 못 찾음) |
| 설비(1/4) | FUME SCRUBBER, PRESSURIZED GAS BOTTLE, CHUTE, CANNED WET PIT SUMP, AMMONIA VAPORIZER, SWING PANEL, HOPPER, MIXER, ELECTRIC MOTOR, DEBRIS FILTER, VAPORIZER, HYDROGEN IGNITER, EJECTOR OR EDUCTOR, STEAM CONVERTER, SAMPLE COOLER, AFTER COOLER, IRWST SUMP STRAINER, GENERIC BOX/CIRCLE EQUIPMENT | 없음(`tank`·`vessel`·`pump`·`compressor`·`heat_exchanger`·`turbine`·`strainer`·`filter`로 넓게 덮을 수 있는 것은 있음) | 이름 글자 견본만(`common.name_*`) | 디젤 기관 1, 공기 건조기 2 |
| 밸브(1/4) | BUTTERFLY, BALL(2·3-WAY), PLUG(3·4-WAY), ANGLE, DIAPHRAGM, PACKLESS, NEEDLE, FOOT, RAM, BACKFLOW PREVENTER, STOP-CHECK, FLOW LIMITING, PLUNGER, QUICK OPENING GATE, KNIFE GATE, FOUR-WAY | `manual_valve`·`check_valve`와 `valve_type` 속성으로 덮임 | APR1400 견본은 게이트·글로브·플러그(2-WAY)·상자형 체크·반쪽 칠한 밸브뿐 | — (정답지는 `manual_valve`로 적음, 미분류 수동 밸브 41의 일부가 여기일 수 있음) |
| 구동부(1/4·4/4) | ELECTRO-HYDRAULIC ACTUATOR 밸브, DOUBLE ACTING CYLINDER, HAND ACTUATOR, MANUAL FLOW CONTROL | E/H 구동 밸브 종류 없음 | `apr1400.eh_operator`(구동부만, 종류를 올리지 않음) | E/H 격리 밸브 8 |
| 자력식 밸브(1/4) | STRAIGHT SAFETY OR RELIEF, PRESSURE REDUCING REGULATOR, VACUUM RELIEF, PILOT OPERATED SAFETY RELIEF, BURSTING PLUG, RUPTURE DISC(압력·진공) | `relief_valve`·`psv`·`rupture_disc` 있음, 감압 조정기 없음 | 앵글 안전밸브(`apr1400.angle_relief_valve`)와 `common.psv_body`, 파열판 견본 없음 | — |
| 경계·표시(1/4) | PENETRATION OF PRIMARY CONTAINMENT / SHIELDED WALL, BUILDING/SYSTEM TRANSITION, QUALITY GROUP ISOLATION, SAFETY CLASSIFICATION, VALVE REACH ROD, ROOF, PROCESS DATA POINT, CONNECTION AT CONDENSER | 없음(기호가 아니라 표시로 다룸) | `apr1400.control_device_box`(PC·IC 상자, 꺼 둠) | 등급 마름모는 정답지가 기호로 세지 않음(개선 10) |
| 배관 선(1/4) | HEAT TRACING, GUARDED LINE, BURIED PIPE, PIPE TRENCH/TUNNEL, SLOPING LINE, SECONDARY PROCESS FLOW | 관계 속성 거리(종류가 아님) | `common.pattern_dot`(매설 배관 점 무늬를 지움) | — |
| HVAC(2/4) | CENTRIFUGAL FAN, VANE AXIAL FAN, ROOF SUPPLY FAN, ROOF VENTILATOR | `fan` 있음 | 없음 | — |
| HVAC(2/4) | HUMIDIFIER, HEATING COIL(HC), COOLING COIL(CC), PREFILTER, HEPA, POSTFILTER, CARBON ADSORBER, MOISTURE SEPARATOR, EVAPORATOR/CONDENSER/CHILLER, CUBICLE COOLER | 없음(`filter`·`heat_exchanger`로 넓게 덮을 수 있음) | 없음 | 활성탄 흡착기 2, 습분 분리기 2, 냉동기 2 |
| HVAC(2/4) | SMOKE DAMPER, PARALLEL BLADE DAMPER, TANDEM LOUVER DAMPER, DOUBLE BLADE DAMPER | `damper` 있음 | 열림·닫힘 댐퍼 2항목만 | — |
| HVAC(2/4) | DUCTED / NON-DUCTED AIR FLOW | 없음 | 없음 | 덕트 열린 끝 13, 비덕트 공기 흐름 1 |
| 소방(2/4) | 옥외·옥내 소화전, ALARM CHECK, POST INDICATOR, DRY·DELUGE·AUTO DRIP VALVE, SPRINKLER, HOSE REEL, FOAM 설비, SIAMESE CONNECTION, PULL STATION, SPEAKER, BELL, WATER MOTOR ALARM | 없음 | 없음 | — (12쪽에 소방 계통 쪽 없음) |
| 시험 연결(2/4) | P·G·T·F·X TEST CONNECTION, ASME TEST POINT | `test_connection` 있음 | `apr1400.test_connection` | — |
| 배관 계기(2/4) | FLOW NOZZLE, VENTURI, METERING ORIFICE, ROTAMETER, PITOT, SINGLE PORT AVERAGING, TURBINE METER, UNCLASSIFIED FLOW ELEMENT | `flow_element`·`orifice` 있음 | `common.orifice_plates`만 | — |
| 배관 계기(2/4) | THERMOWELL(TW), ANALYZER CELL(AE), SAMPLE PROBE(AX), PROCESS RADIATION MONITOR(RE), CONSTANT HEAD CHAMBER, AIR FILTER-PRV SET | 보호관·분석기·시료 탐침·방사선 감시기·정수두 상자 종류 없음(TE·TEW·FS는 ISA 글자로 덮임) | `common.instrument_bubble`(ISA 글자) | TW 4, AX 원 3, AX 상자 3, RX 1, XE 1, LE 4 |
| 계기·제어(3/4·4/4) | OPEN & CLOSE POSITION LIGHTS(ZL), SHARED HSI 경보, SYSTEM LEVEL ACTUATION(ESF-SIAS, DMA-SIAS) | 표시등·작동 신호 종류 없음 | `apr1400.hsi_shared_display`·`tombstone_instrument` | ZL 20, PDAH·XAH·PAL 등 HSI 경보 13 |
| 신호선(4/4) | PNEUMATIC / ELECTRICAL / HYDRAULIC SIGNAL, CAPILLARY TUBING, LINE (NOT) CONNECTED | 관계 종류 문제(기호 아님) | — | — |

정리하면 12쪽 정답지의 `unlisted` 155개 가운데 범례 이름으로 짝이 서는 것이 110여 개(ZL 20, 스파저 13, 덕트 열린 끝 14, HSI 경보 13, 호스·신축 이음 9, E/H 밸브 8, 계기 원·상자 16, 커플러 5, 소음기 4, 다이어프램 실 4, HVAC 기기 6 등)이고, 나머지(드립 팬 엘보 20, 드레인 포트 8, 트럭 연결구로 보이는 반원 4 등)는 범례 글자에서 같은 이름을 찾지 못했습니다.

### 7.3 범례 쪽이 어디까지 쓰였나

근거가 있는 것만 적고, 추측은 추측이라고 적습니다.

1. **사전 항목의 이름 출처로는 거의 다 쓰였습니다.** APR1400 사전 22항목 가운데 20항목의 첫 `sources`가 `legend: "1.7-1 n/4 …"`로 범례 무리를 가리킵니다. 나머지 둘은 `ident_bubble_ellipse`(범례 밖, 도면에서 더함)와 `half_filled_valve_open`(범례 1/4 위치 표기 설명에서 따옴)입니다.
2. **모양 견본으로는 거의 쓰이지 않았습니다.** 견본을 뽑은 쪽 목록(`sources[].pages`)에 범례 쪽 001~004가 들어간 항목은 `angle_relief_valve`(001), `gate_valve`(001), `globe_valve`(001·002) 셋뿐입니다. `docs/specs/pid-symbol-dictionary.md` §5.3과 결정 D13이 '견본은 실제 도면 표본에서, 범례는 이름·그림 출처로'라고 정했습니다(범례 견본만 썼을 때 짝수 쪽 미분류 5,708개 가운데 28.7%만 맞고 1,696개가 애매했다고 그 문서 §5.3이 적음).
3. **정답지 쪽으로는 쓰이지 않았습니다.** 읽기 품질 정답지 12쪽(008·012·016·025·033·046·062·063·072·097·105·128)에 범례 쪽은 없습니다. 다만 정답지를 쓸 때 범례로 모양과 선 종류를 확인했습니다(`apr1400-008.json`의 `method`가 '범례 001~004쪽 overview로 밸브 모양과 선 종류를 확인'이라고 적음). 정답지 파일에서 '범례'가 나오는 횟수는 072쪽 24, 097·105쪽 각 10, 016쪽 9, 062쪽 8, 025쪽 7, 008·128쪽 각 4, 033쪽 2, 046·063쪽 각 1, 012쪽 0입니다.
4. **범례 수집 도구는 저장소에 없습니다.** 규격 §2.1·§6은 `harvest_legend.py`(범례 239항목 짝짓기)와 `legend_eval.py`를 적지만, `git ls-files`와 커밋 이력 어디에도 없습니다. 작업 루트에서만 돌렸던 것으로 보입니다(추측). 그 결과물(`symbol-candidates/<묶음>/범례.csv`)은 작업 루트에 있을 것이라 이 조사에서 열지 않았습니다.
5. **범례가 정한 규칙이 추출기와 기록에 들어간 곳**: TEW를 온도 요소로(개선 4), 위치 약어 LT(개선 9), 등급 마름모를 안전등급 경계로(개선 10), 검게 칠한 몸통 = 정상 닫힘(사전 규격 D5), PC·IC 상자 = 격납 관통부(제어 장치 견본을 끔), 솔레노이드는 파일럿(4/4쪽), 008쪽 임시 기동 스트레이너(정답지 `limits` (9)).

범례를 더 쓸 길: 6절 끝의 '적은 예시 학습'과 실험 4의 견본 그래프는 범례 그림 하나를 견본으로 쓸 수 있습니다. 다만 사전 규격 D10(범례 자동 이름은 후보로만, 사람이 확정)을 따라야 합니다.

## 8. 쓰지 않기로 한 것과 이유

- **벡터 원소 학습 모델(SymPoint, VecFormer 등)**: P&ID 가중치가 없고, 원소 단위 라벨 수천 개와 GPU 학습이 필요합니다. 생각(이음 상한, 레이어 특징, 투표로 떼기)만 실험 2·4·5에 넣었습니다.
- **큰 언어·시각 모델에 연결 추적을 맡기기**: 공개 결과에서 연결이 가장 약하고(AWS 예제의 한 번 호출 연결 F1 59~88%, 합성 10장) 실행마다 흔들립니다. 지금처럼 후보만 내게 두고, 쓰려면 타일 + 쪽 전체 맥락 + 검토 단계를 갖춥니다.
- **pyDEXPI를 앱에 넣기**: AGPL-3.0입니다. 바깥 검사기로만 씁니다.
- **Ultralytics를 배포본에 넣기**: AGPL-3.0입니다.

## 9. 확인하지 못한 것

- **본문을 읽지 못한 논문**: Messmer·Bunke, Rusiñol·Lladós, Liu·Dori, Kong, Agam, Dosch·Tombre, 2015 IEEE 벡터 P&ID 논문, Kim 등 2022(JCDE, 수치는 초록과 검색 요약), Moon 등 2021(쪽이 403), Yu 등 2019(초록만), Theisen 등 2023, Mani 등 2020, Zhu 등 2026, AECV-Bench·AMSbench·OmniSch의 모델별 표, Safety Science 2026 HAZOP 논문. 이 논문들의 '맞음' 세는 규칙은 확인하지 못했습니다.
- **어긋난 수치**: PanCADNet PQ가 출처에 따라 55.3과 56.1로 다릅니다. Relationformer의 OPEN100 간선 mAP는 조각 단위 76.79, 이어 붙인 전체 75.46으로 조건이 다르므로 둘 다 적었습니다.
- **저장소의 마지막 갱신일과 일부 라이선스**: 읽은 GitHub 쪽에 갱신일이 나오지 않았습니다. SymPoint·ArchCAD의 라이선스 종류, Detectron2·RT-DETR 라이선스, RF-DETR의 ONNX 내보내기, SynthPID 저장소(404)도 확인하지 못했습니다.
- **기하 해시(geometric hashing)**: 하위 에이전트가 배경 지식으로만 적었고 1차 자료로 확인하지 못했습니다. 표에서 뺐습니다.
- **안트로피 AutoPID**: 첫 쪽만 읽었고 AutoPID 하위 쪽은 404였습니다. 벡터 PDF를 어떻게 다루는지, 정확도, 내보내기 형식은 밝힌 곳을 찾지 못했습니다.
- **우리 도면의 가설**: 072쪽 1.08pt 선이 방 경계선인지, 008쪽 패키지 경계 상자의 무늬가 배관 일점쇄선과 같은지는 그림으로 확인하지 않았습니다(실험 1·2의 첫 단계).
- **범례 대조의 한계**: 범례 그림은 보지 않고 글자만 읽었습니다. 범례 이름과 정답지 `kind_text`의 짝은 제가 글로 맞춘 것입니다. 범례 수집 결과(`범례.csv`)는 작업 루트에 있을 것으로 보여 열지 않았습니다.
