---
doc_id: HZ-PLN-08
rev: 0
status: review
author: unknown
reviewed: —
approved: —
---

# 그래프 조사: Obsidian식 화면 + HAZOP용 그래프 알고리즘

작성일 2026-11-05. 조사 도구: `aside-browser` 스킬(Aside CLI 1.26, `aside exec` 4회). WebSearch/WebFetch 대체 사용 없음.

## 0. 자료 읽기 범위

**직접 열어 읽은 자료(Aside 에이전트 보고 기준)**

| 자료 | 읽은 범위 |
| --- | --- |
| https://obsidian.md/help/plugins/graph (help.obsidian.md에서 리다이렉트) | 전부 |
| https://d3js.org/d3-force , https://d3js.org/d3-force/many-body | 전부 |
| https://raw.githubusercontent.com/d3/d3-force/main/LICENSE | 전부 |
| npm registry JSON, bundlephobia API, jsDelivr 파일 목록 (cytoscape, cytoscape-fcose, cytoscape-cola, sigma, graphology, graphology-layout-forceatlas2, vis-network, force-graph, d3-force) | 버전·라이선스·크기·배포 파일명만 |
| 각 라이브러리 GitHub README | 규모·렌더링 관련 키워드 부분만 |
| https://blog.js.cytoscape.org/2025/01/13/webgl-preview/ | 성능 단락 |
| PyPI JSON (networkx, igraph, python-igraph, rustworkx) | 라이선스·wheel 목록 |
| networkx 3.7 레퍼런스 페이지 17개 | 함수 시그니처만 |
| https://www.rustworkx.org/api/algorithm_functions/index.html | 전부 |
| https://www.w3.org/TR/prov-o/ | 핵심 클래스 정의 4개만 |
| https://www.w3.org/TR/rdf12-concepts/ | 초록, triple term·reifier 단락 |
| https://neo4j.com/docs/getting-started/graph-database/ | 전부 |
| https://dexpi.org/ | 첫 화면 |
| 논문 11편(§4.3) | 서지사항·초록만. 본문 미열람 |

**검색 결과로만 본 자료**: §4.3의 "검색만" 4편, rustworkx GitHub issue #1141.

**누락 가능성**: 논문은 초록만 읽었으므로 방법·결과의 세부는 확인하지 않았다. README는 키워드 검색만 했으므로 다른 표현으로 쓴 규모 주장은 빠졌을 수 있다. JS 라이브러리를 `file://`이나 QtWebEngine에서 실제로 띄워 보지는 않았다.

**부수 사항**: Aside의 fetch 도구가 Mani et al.(CVPRW 2020) PDF를 Aside 세션 임시 폴더에 자동 캐시했다. 실행하지 않았고 리포지토리에는 아무것도 저장하지 않았다.

**저장소 맥락(직접 확인)**: `hazop/graph/build.py`, `query.py`는 이미 `networkx`를 쓴다. JS 그래프 라이브러리는 아직 저장소에 없다. `design/output-screen-ax-demo.md` §2.3은 force-directed 캔버스, 작은 점·옅은 선, 호버 시 이웃만 강조를 목표로 적는다.

---

## 1. Obsidian 그래프 뷰가 보여 주는 것

출처: https://obsidian.md/help/plugins/graph (전부 읽음)

| 항목 | 내용 |
| --- | --- |
| 노드·간선 | 원 = 노트, 선 = 노트 사이 내부 링크 |
| 노드 크기 | 그 노드를 참조하는 노드가 많을수록 커진다(링크 수 기반) |
| 호버 | 노드에 마우스를 올리면 그 노트의 연결이 강조된다. 클릭하면 노트를 연다. 우클릭 메뉴 있음 |
| 조작 | 휠·+/− 확대, 드래그·화살표 이동, Shift로 빠르게 이동 |
| 전역 그래프 | 볼트 전체 노트 |
| 로컬 그래프 | 활성 노트에 연결된 노트만. **깊이(depth)** 슬라이더: 한 단계마다 앞 단계에서 드러난 노트에 연결된 노트를 추가 |
| 필터 | 파일 검색어, 태그 표시, 첨부 표시, "존재하는 파일만"(링크만 있고 파일은 없는 노트 제외), 고아(링크 없는 노트) 표시, 제외 파일 패턴 |
| 그룹 | 검색어로 그룹을 만들고 색을 지정 |
| 표시 | 화살표(링크 방향), 텍스트 페이드 임계값, 노드 크기, 링크 두께, Animate(생성 시각 순 타임랩스) |
| 힘(force) | Center force(뭉침 정도, 클수록 원형), Repel force(노드끼리 밀어냄), Link force(링크를 고무줄로 볼 때 당기는 세기), Link distance(링크 길이) |

- 도움말에는 힘 슬라이더의 기본값·범위가 없다.
- Obsidian이 내부적으로 어떤 레이아웃 엔진을 쓰는지는 도움말에 없다. [미확인]

**HAZOP 화면 대응 [추론]**

- 노트 → 설비·배관 구간·요건·문서 조각·설정치 등 typed 노드, 링크 → typed 관계
- 로컬 그래프 깊이 → k-hop ego graph(§3)
- 그룹 색 → 노드 종류별 색(디자인 문서가 요구하는 "도면과 그래프의 색 체계 공유")
- 고아 토글 → 어떤 P&ID 노드와도 연결되지 않은 요건·문서 조각을 드러내는 검증 기능
- 타임랩스 → 자료 등록 순서나 `graph_version` 변경 이력 재생에 쓸 수 있음

---

## 2. 구현 방식: 레이아웃 알고리즘과 오프라인 JS 라이브러리

### 2.1 force-directed 레이아웃

| 알고리즘 | 요점 | 출처 |
| --- | --- | --- |
| Fruchterman–Reingold (1991) | Eades의 spring embedder를 수정. 직선 간선, 균일한 간선 길이를 목표로 하는 무방향 그래프 배치 | Software: Practice and Experience 21(11):1129–1164, DOI 10.1002/spe.4380211102 |
| ForceAtlas2 (2014) | Gephi 기본 레이아웃. Barnes–Hut 근사, 차수 비례 반발, 적응형 온도. 연속(continuous) 레이아웃 | PLoS ONE 9(6):e98679, DOI 10.1371/journal.pone.0098679 |
| d3-force | velocity Verlet 수치 적분기로 입자에 힘을 적용. tick 이벤트마다 다시 그림 | https://d3js.org/d3-force |
| Barnes–Hut (d3 manyBody) | quadtree로 먼 노드 묶음을 한 덩어리로 근사. 적용당 O(n log n). theta 기본 0.9, strength 기본 −30, distanceMin 1 | https://d3js.org/d3-force/many-body |

Obsidian의 Center/Repel/Link force/Link distance는 d3-force의 `forceCenter`, `forceManyBody`, `forceLink.strength`, `forceLink.distance`와 개념이 일대일로 대응한다. [추론: 이름과 설명이 대응할 뿐, Obsidian이 d3-force를 쓴다는 근거는 찾지 못했다]

### 2.2 오프라인 사용 가능한 JS 라이브러리

크기는 bundlephobia 값(의존성 포함, 바이트). 출처: `https://registry.npmjs.org/<pkg>/latest`, `https://bundlephobia.com/api/size?package=<pkg>@<ver>`, 각 GitHub README.

| 라이브러리 | 라이선스 | 최신 버전 | min / gzip | 공식 규모 표현 | 렌더링 | 로컬 파일 단독 로드 |
| --- | --- | --- | --- | --- | --- | --- |
| cytoscape | MIT | 3.34.4 | 434,954 / 136,810 | 노드 수 명시 없음. WebGL 블로그: 약 1,200노드·16,000간선에서 Canvas 약 20 FPS, WebGL 100 FPS 이상. 약 3,200노드·68,000간선에서 Canvas 3 FPS, WebGL 10 FPS | Canvas(기본), WebGL 미리보기(v3.31~) | 가능. `dist/cytoscape.min.js`, 의존성 없음 |
| cytoscape-fcose | MIT | 2.2.0 | 121,606 / 718(값 이상, 재확인 필요) | "CoSE보다 최대 2배 빠름" | 레이아웃 전용 | 가능. `layout-base.js` → `cose-base.js` → `cytoscape-fcose.js` 순서로 3파일 |
| cytoscape-cola | MIT | 2.5.1 | 84,908 / 24,405 | 명시 없음 | 레이아웃 전용(WebCola) | 가능. WebCola 파일 추가 |
| sigma v3 / v4 | MIT | 3.0.3 / **4.0.4**(2026-10-08) | v3 96,461 / 25,966; v4 375,162 / 96,741 | "WebGL로 수천 노드·간선"(현재 README = v4) | WebGL | `dist/sigma.min.js` 있음. 모듈·워커 사용 시 `file://` 동작 [미확인] |
| graphology | MIT | 0.26.0 | 66,395 / 12,824 | 해당 없음(자료구조) | 없음 | `dist/graphology.umd.min.js` |
| graphology-layout-forceatlas2 | MIT | 0.10.1 | 9,696 / 3,115 | 명시 없음. Web Worker 판 포함 | 레이아웃 전용 | 패키지에 단일 UMD 파일 없음(CommonJS). 직접 번들 필요 |
| vis-network | Apache-2.0 OR MIT | 10.1.4 | 414,225 / 118,363 | "수천 노드·간선까지 부드럽게", 그 이상은 클러스터링 | Canvas | 가능. `standalone/umd/vis-network.min.js` |
| force-graph (vasturiano) | MIT | 1.52.0 | 173,002 / 57,366 | 예제 "중간 규모 약 4k 요소", "대규모 약 75k 요소" | Canvas, 물리는 d3-force | 가능. `dist/force-graph.min.js` |
| d3-force | ISC [일반지식: LICENSE 문구가 ISC 표준문과 같음, 파일에 명칭 없음] | 3.0.1 | 15,619 / 5,811 | 해당 없음 | 없음(좌표만 계산, 그리기는 직접) | `dist/d3-force.min.js` + d3-dispatch, d3-quadtree, d3-timer 필요 |

**주의**

- "로컬 파일 단독 로드"는 배포 파일 이름으로 판단했다. QtWebEngine에서 실제로 띄워 보지 않았다. [미확인]
- 규모 수치는 각 프로젝트의 주장이나 데모 크기이며 벤치마크가 아니다.
- sigma는 v4가 최신이다. v3과 v4의 차이는 조사하지 않았다.

**QtWebEngine 오프라인 적재 [일반지식, 미확인]**: UMD 파일을 앱 리소스(qrc 또는 패키지 폴더)에 넣고 `<script src="...">`로 읽으면 CDN이 필요 없다. ES module이나 Web Worker를 쓰는 라이브러리는 `file://` 제약 때문에 `QWebEngineUrlScheme` 같은 사용자 정의 스킴이 필요할 수 있다.

---

## 3. HAZOP + 지식그래프 통합에 쓸 그래프 알고리즘

networkx 함수 이름·시그니처는 https://networkx.org/documentation/stable/reference/ 의 3.7 페이지에서 확인했다(URL 접두 `.../reference/algorithms/generated/networkx.algorithms.`). HAZOP 활용 예는 모두 [추론]이다.

| 알고리즘 | networkx 함수 | HAZOP 활용 |
| --- | --- | --- |
| 도달성 BFS/DFS | `descendants(G, s)`, `ancestors(G, s)`, `bfs_tree` | 편차(예: 유량 없음)를 흐름 방향 하류로 전파해 영향 설비 후보를 찾고, 상류로 거슬러 원인 후보를 찾는다. 관계 종류 필터(`PHYS_FLOWS_TO`만, `DEPENDS_ON` 포함 등)를 먼저 적용 |
| 최단 경로 | `shortest_path(G, s, t, weight=...)` | 원인 설비 → 결과 설비 사이의 대표 경로를 근거(`graph_evidence`)로 제시 |
| 모든 단순 경로 | `all_simple_paths(G, s, t, cutoff=k)` | 원인→결과 경로 열거. 경로 수가 폭증하므로 `cutoff` 필수 |
| 연결 요소 | `connected_components`, `weakly_connected_components` | 도면 간 연결 누락, 끊어진 계통 탐지 |
| 고아 | `isolates(G)` | Obsidian "Orphans"와 같은 개념. P&ID와 연결되지 않은 요건·문서 조각·설정치를 검토 목록으로 출력 |
| 중심성 | `degree_centrality`, `betweenness_centrality(G, k=...)`, `pagerank(G)` | 많은 경로가 지나는 설비(betweenness), 요건·문서가 많이 걸린 설비(degree)를 우선 검토 대상으로 제시. Obsidian의 노드 크기 = degree |
| 커뮤니티 탐지 | `louvain_communities(G, seed=...)`, `label_propagation_communities(G)` | 검토 구간(HAZOP node) 분할 **후보** 제안. 확정은 사람이 함(기획서의 "자동 구간 분할"은 1차 범위 밖) |
| 순환 탐지 | `simple_cycles(G, length_bound=...)` | 재순환·바이패스 루프 식별. 루프는 편차 전파가 되돌아오는 구간이므로 별도 표시 |
| 절단점·브리지 | `articulation_points(G)`, `bridges(G)` | 무방향 관점에서 하나가 막히면 계통이 갈리는 단일 고장점 후보(밸브·배관 구간) |
| 지배자 | `immediate_dominators(G, start)`, `dominance_frontiers` | 공급원에서 어떤 설비로 가는 모든 경로가 반드시 지나는 밸브·펌프 찾기. 방향 그래프용 단일 고장점 분석 |
| k-hop 자아 그래프 | `ego_graph(G, n, radius=k, undirected=True)` (generators 모듈) | Obsidian 로컬 그래프의 depth와 같은 동작. 선택 설비 주변의 요건·설정치·해석 사례 표시 |

**엔티티 해소(entity resolution) / 링크 예측 [추론]**

비P&ID 문서의 언급을 P&ID 태그와 연결하는 단계다. 1차 범위에서는 학습 모델보다 규칙 기반이 적합하다.

1. 태그 정규식: 계통 약어·설비 종류·번호 패턴(예: `PXS-PL-V014A` 형식)을 정규식으로 추출한다. 실제 패턴은 대상 도면의 태그 규칙을 보고 정해야 한다.
2. 정규화 후 완전 일치: 하이픈·공백·대소문자·0 채움 차이를 없앤 뒤 비교한다.
3. 유사 문자열 후보: 표준 라이브러리 `difflib.SequenceMatcher`로 점수를 매기고, 임계값 이상은 "후보"로만 두어 사람이 확인한다(기획서의 수동 병합·분리 원칙과 맞음).
4. 구조 기반 보강: 같은 문서 조각에 함께 언급된 태그끼리 P&ID에서 가까운지(`shortest_path_length`)로 후보 신뢰도를 조정한다.
5. 모든 연결에 근거(문서·페이지·일치 방식·점수)를 남긴다(§4.2).

### 3.1 Python 그래프 라이브러리

출처: PyPI JSON(`https://pypi.org/pypi/<pkg>/json`), GitHub README, rustworkx 알고리즘 색인.

| 라이브러리 | 라이선스 | 최신 | 형태 | Win/Py3.12 wheel | 비고 |
| --- | --- | --- | --- | --- | --- |
| networkx | BSD-3-Clause | 3.7 | 순수 Python(`py3-none-any`) | 있음 | Python ≥3.12 요구(3.14.1 제외). 위 표 알고리즘 모두 포함. 저장소가 이미 사용 중 |
| igraph (python-igraph) | GPL(GitHub 표기 GPL-2.0) | 1.0.0 | C 코어 컴파일 | 있음(`cp39-abi3-win_amd64`) | 배포 시 GPL 조건 검토 필요 [일반지식] |
| rustworkx | Apache-2.0 | 0.18.1 | Rust 컴파일 | 있음(`cp310-abi3-win_amd64`) | **커뮤니티 탐지 없음**(색인에 louvain·modularity·label_propagation 없음). 중심성·경로·절단점·지배자는 있음 |

---

## 4. 지식그래프 모델링 패턴

### 4.1 속성 그래프 vs RDF

| 구분 | 속성 그래프(labeled property graph) | RDF |
| --- | --- | --- |
| 구조 | 노드(0개 이상 라벨) + 관계(시작·끝 노드, 정확히 한 타입, 방향) + 키-값 속성 | 주어–술어–목적어 트리플 |
| 관계에 속성 달기 | 관계에 직접 속성 | RDF 1.2: triple term을 목적어로 쓰고 `rdf:reifies`로 진술을 가리키는 reifier에 설명을 붙임 |
| 출처 | https://neo4j.com/docs/getting-started/graph-database/ | https://www.w3.org/TR/rdf12-concepts/ (2026-04-07 Candidate Recommendation, 확정 권고안은 아직 RDF 1.1) |

두 페이지 모두 서로를 직접 비교하지는 않는다. 위 대비는 정리한 해석이다.

**이 프로젝트에의 적용 [추론]**: networkx `MultiDiGraph`는 속성 그래프 모델과 같다(노드·간선 속성 dict, 같은 쌍 사이 여러 타입 관계). 데모 화면의 `HAS_ENDPOINT`, `GOVERNED_BY`, `SPECIFIED_IN` 같은 대문자 관계 타입도 속성 그래프 관례를 따른다. 외부 추론기(OWL)를 쓸 계획이 없으면 RDF 도입 이득이 작다.

### 4.2 타입·근거(provenance) 표현

- W3C PROV-O(https://www.w3.org/TR/prov-o/, 2013-04-30 Recommendation): Entity(고정된 측면을 가진 물리·디지털·개념적 대상), Activity(시간에 걸쳐 일어나며 Entity에 작용), Agent(활동·존재에 책임을 지는 주체), `prov:wasDerivedFrom`(한 Entity가 다른 Entity로 변환됨).
- 적용 예 [추론]: 관계 속성에 `source_material_id`, `page`, `object_id`, `extractor`(Activity에 해당), `method`(정규식/완전일치/유사도/수동), `confidence`, `reviewed_by`(Agent)를 둔다. 기획서의 `evidence_ids`, `graph_version` 고정 방식과 겹치므로 새 스키마보다 기존 근거 묶음에 위 필드를 맞추는 편이 단순하다.
- 노드 타입은 고정 열거(설비, 배관 구간, 요건, 문서, 문서 조각, 신호, 설정치, 지지물, 해석 사례)로 두고, 관계 타입도 화이트리스트로 두어 타입 쌍 제약(예: `SPECIFIED_IN`은 설비→문서 조각)을 검증한다. 타입 이름은 데모 화면 분석 문서에서 가져왔다.

### 4.3 문헌·산업 사례

모두 초록·서지 페이지만 읽었다. 본문 방법은 확인하지 않았다.

**(a) 그래프·지식그래프·온톨로지 기반 HAZOP**

1. Single, Schmidt, Denecke (2020). "Ontology-based computer aid for the automation of HAZOP studies." *J. Loss Prev. Process Ind.* 68:104321. DOI 10.1016/j.jlp.2020.104321. https://pmc.ncbi.nlm.nih.gov/articles/PMC7581379/ — 온톨로지에 HAZOP 전문가 지식을 담고 의미 추론기로 워크시트를 자동 생성. 사례: 헥산 저장탱크.
2. Oeing, Holtermann, Welscher, Severins, Vogel, Kockmann (2023). "preHAZOP: Graph-Based Safety Analysis for Early Integration into Automated Engineering Workflows." *Chemie Ingenieur Technik*. DOI 10.1002/cite.202200222 — DEXPI P&ID를 `DEXPI2graph`로 그래프화하고 탐색 알고리즘으로 안전 관련 편차를 위험도와 함께 표시. **이 프로젝트와 가장 가까운 사례.**
3. Li, Zhao (2025). "HAZOPCT: A HAZOP analysis completeness tool based on knowledge graph reasoning." *Process Saf. Environ. Prot.* DOI 10.1016/j.psep.2025.107025 — 여러 공정안전 자료로 온톨로지 기반 HAZOP 지식그래프를 만들고 유사 사례로 결론을 추천.
4. Yan, Wu, Yuan, Wang, Cao (2023). "A New HAZOP Automated Method for the Oil and Gas Complex Equipment." *Chem. Technol. Fuels Oils* 59:872–879. DOI 10.1007/s10553-023-01592-8 — 공정을 부호 방향 그래프(SDG)로 모델링하고 온톨로지·추론 엔진으로 HAZOP 표 생성.

**(b) P&ID 디지털화 → 그래프**

5. Kim, Kim, Moon, Lee, Mun (2022). "End-to-end digitization of image format piping and instrumentation diagrams at an industrially applicable level." *J. Comput. Des. Eng.* 9(4):1298. DOI 10.1093/jcde/qwac056 — 이미지 P&ID의 심볼·문자·선을 딥러닝으로 인식해 객체 그래프와 DEXPI 호환 출력 생성. 게재일 표기(2022-06-20 / 2022-08-27)가 출처마다 다름.
6. Oeing, Welscher, Krink, Jansen, Henke, Kockmann (2022). "Using artificial intelligence to support the drawing of P&IDs using DEXPI standard." *Digital Chemical Engineering*. DOI 10.1016/j.dche.2022.100038 — DEXPI P&ID를 방향 그래프(GraphML)로 변환, RNN으로 설비 예측, GNN으로 일관성 검사.
7. Mani 외 (C3.ai, 2020). "Automatic Digitization of Engineering Diagrams using Deep Learning and Graph Search." CVPR Workshops 2020. https://openaccess.thecvf.com/content_CVPRW_2020/papers/w8/Mani_Automatic_Digitization_of_Engineering_Diagrams_Using_Deep_Learning_and_Graph_CVPRW_2020_paper.pdf — CNN 심볼 검출 + 선을 따라가는 그래프 탐색으로 연결 관계 추출.
- DEXPI(https://dexpi.org/): 공정플랜트 수명주기 전반의 공통 데이터 교환 표준을 목표로 하며 현재 초점은 P&ID 교환. 최근 소식에 DEXPI 2.0.1 사양 공개가 있다(해당 글 미열람).

**(c) 알고리즘 원 논문**

8. Blondel 외 (2008). "Fast unfolding of communities in large networks." *J. Stat. Mech.* P10008. DOI 10.1088/1742-5468/2008/10/P10008 (Louvain). 저자 전체 목록은 열람 페이지에서 확인 못 함 [일반지식: Blondel, Guillaume, Lambiotte, Lefebvre].
9. Traag, Waltman, van Eck (2019). "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports*. DOI 10.1038/s41598-019-41695-z — Louvain이 끊어진 커뮤니티를 만들 수 있음을 보이고 연결성을 보장하는 Leiden 제시. 제목·저자·학술지는 [일반지식], 내용은 열람 확인.
10. ForceAtlas2, 11. Fruchterman–Reingold: §2.1 참조.

**검색만 하고 열지 않은 자료 [미확인]**: Deep-HAZOP(지식그래프 강화 LLM HAZOP 결론 생성, AIChE 2025); Han, Roh, Kong(2025) 조선 P&ID → 구조화 그래프 변환; Han 외 ContLineNet(GNN 기반 P&ID 연속선 분류, *Adv. Eng. Inform.*); Oeing 외 "Graph Learning in Machine-Readable Plant Topology Data"(*Chemie Ingenieur Technik* 2023).

원자력 분야(NRC·원전 개발사)에 한정한 그래프 기반 HAZOP 사례는 이번 조사에서 찾지 못했다. 위 사례는 모두 화학·석유·조선 공정이다.

---

## 5. HAZOP 적용 권고(요약)

### 권장 스택

| 역할 | 권장 | 대안 |
| --- | --- | --- |
| Python 그래프 계산 | **networkx 3.x** | rustworkx(대규모에서 속도가 필요할 때 계산 일부만) |
| 화면 레이아웃·렌더링 | **force-graph (vasturiano)** | Cytoscape.js + fcose |

### 근거

**networkx [추론 포함]**
- 이미 `hazop/graph/build.py`, `query.py`가 쓰고 있어 추가 의존성이 없다.
- BSD-3, 순수 Python wheel이라 Windows 패키징(PyInstaller 등)에서 네이티브 확장 문제가 없다.
- §3의 알고리즘(도달성, 경로, 고아, 중심성, Louvain, 순환, 절단점, 지배자, ego graph)을 한 라이브러리로 모두 덮는다. rustworkx는 커뮤니티 탐지가 없고, igraph는 GPL이다.
- 도면 수 장 + 문서 조각 규모(수천~수만 노드)는 순수 Python으로 감당 가능한 범위로 본다. [추론, 실측 필요]

**force-graph**
- d3-force 물리를 그대로 써서 Obsidian의 Center/Repel/Link force/Link distance 슬라이더를 d3 파라미터에 직접 연결할 수 있다.
- Canvas 렌더링, MIT, 단일 UMD 파일(`dist/force-graph.min.js`, gzip 약 57KB)이라 QtWebEngine에 오프라인으로 넣기 쉽다.
- 데모 규모 예제가 수천~7.5만 요소로, 예상 규모보다 여유가 있다.
- 호버 시 이웃 강조, 노드 크기=링크 수, 그룹 색은 노드·링크 콜백으로 구현한다. [미확인: 내장 옵션 여부는 README에서 확인하지 않았다]

**Cytoscape.js를 대안으로 두는 이유**
- 장점: 선택자 기반 스타일, 복합 노드(검토 구간 묶음 표시), 풍부한 그래프 질의 API가 있다.
- 단점: 크기가 크고(gzip 약 137KB), 기본 레이아웃이 일회성 배치라 Obsidian처럼 계속 움직이는 물리감을 내려면 cola 같은 추가 레이아웃이 필요하다. Canvas 성능은 1,200노드·16,000간선에서 약 20 FPS로 보고됐다.
- 검토 구간 묶음 표시나 편집 기능이 Obsidian식 탐색보다 중요해지면 Cytoscape.js로 바꾸는 편이 낫다.

**sigma.js + graphology를 1순위로 두지 않은 이유**: WebGL이라 대규모에 가장 유리하지만, v4가 막 나왔고(2026-10) ForceAtlas2 레이아웃 패키지가 단일 UMD 파일로 제공되지 않아 오프라인 번들 작업이 추가된다. 수만 노드 이상이 실제로 필요해질 때 재검토한다.

### 역할 분담 원칙 [추론]
- 계산(경로, 고아, 중심성, 커뮤니티, 엔티티 매칭)은 Python에서 하고, 결과를 JSON(노드·링크·속성·근거 ID)으로 넘긴다. JS는 그리기와 상호작용만 맡는다.
- 이렇게 하면 HAZOP 근거(`graph_evidence`)가 Python 쪽 결정적 계산에서 나오므로 재현성과 검증이 쉽다.
- 커뮤니티 탐지 결과는 검토 구간 "후보"로만 쓰고 `seed`를 고정해 재현성을 확보한다.

### 직접 검증해야 할 부분
1. force-graph와 Cytoscape.js UMD 파일을 실제 QtWebEngine(외부망 차단)에서 띄워 동작을 확인할 것.
2. 실제 도면·문서 규모로 networkx 계산 시간과 force-graph 프레임률을 측정할 것.
3. cytoscape-fcose gzip 값(718B)은 bundlephobia가 낸 이상값이다.
4. Obsidian 힘 슬라이더의 기본값·범위는 공식 문서에 없다.
5. 논문 내용은 초록 기준이다. 인용 전 본문과 서지(권·호·쪽)를 확인할 것. Louvain·Leiden 저자는 [일반지식]이다.
6. igraph를 쓰게 되면 GPL 배포 조건을 검토할 것.
