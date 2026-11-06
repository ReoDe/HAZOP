# HAZOP

설계도면과 문서에서 설비·연결 관계·운전조건 등을 추출하여 통합 그래프로 관리하고, 그래프 알고리즘과 AI 탐색을 통해 전문가 검토용 HAZOP 분석 초안을 생성하는 프로젝트입니다. 궁극적인 대상은 원자력발전소 계통입니다.

이 프로젝트의 결론은 **HAZOP 결과(워크시트와 구조화 기록)를 만드는 것**입니다. 그 결과를 PSA 초기사건 도출 등에 활용하는 작업은 다른 곳에서 수행하며 이 프로젝트의 범위가 아닙니다.

현재는 기획 단계이며, ①등록·②추출·③그래프·④HAZOP 분석(MVP, 고정 응답 기준)의 1차 구현이 있습니다. 모든 기획서는 초안이며 구현 완료를 의미하지 않습니다. 결정 사항과 남은 작업은 [메모리](메모리/README.md)에서 관리합니다.

## 전체 기획과 워크플로우

- [전체 기획](기획서/전체기획.md): 목적·용어와 단계 구성
- [공통 원칙](기획서/전체기획.md#principles): 모든 단계에 적용하는 근거·미확인·이력·검증·AI 원칙
- [MVP와 후속 범위](기획서/전체기획.md#mvp): 첫 수직 슬라이스와 단계별 후속 기능
- [단계 간 데이터 규격 초안](기획서/전체기획.md#data-contract): ID·버전·상태, 전달 JSON과 변경 알림 예시
  - [단계 연쇄 검사](기획서/단계연쇄검사.md): ①→⑤ 결과의 ID·버전·해시·상태 연속성 검사
- [최상위 플로우차트](<flow chart/00-overview.md>): 단계 간 데이터 흐름
- ① [자료 등록 흐름](<flow chart/01-registration.md>) · [기획](기획서/자료등록.md)
- ② [정보 추출 흐름](<flow chart/02-extraction.md>) · [기획](기획서/정보추출.md): draw.io 원본 읽기, 샘플 작성 규칙, 기호·연결 규칙
- ③ [정보 통합·관리 흐름](<flow chart/03-integration.md>) · [기획](기획서/정보통합관리.md): 그래프 노드·관계·속성 정의
- ④ [HAZOP 분석 흐름](<flow chart/04-hazop-analysis.md>) · [기획](기획서/HAZOP분석.md): 편차 후보, 원인·결과 패턴, 그래프 탐색, AI 추론
  - [HAZOP 기법 지침](기획서/HAZOP기법지침.md): KOSHA P-86-2017(회분식 HAZOP 기술지침) 요약
- ⑤ [검토·결과 관리 흐름](<flow chart/05-review-results.md>) · [기획](기획서/검토결과관리.md): 편차별 확정, 재검토, Excel 출력
  - [평가 기준 비교](기획서/평가기준비교.md): 평가 기준 파일 형식, 대응 규칙, 지표
- [데스크톱 인터페이스](기획서/인터페이스.md): ①②④⑤ 화면, 검토 확정 규격, Excel 출력, 패키징 대비
- [메모리](메모리/README.md): 결정 로그와 남은 작업
- [그래프조사](기획서/그래프조사.md) · [그래프활용](기획서/그래프활용.md): 지식그래프·알고리즘·그래프 화면 조사와 구현 구상
- [지식그래프 작업 공간](docs/2026-11-05-knowledge-graph/README.md): 지식그래프 활용 구현의 문서·결정·진행 현황

전체 흐름은 **자료 등록 → 정보 추출 → 정보 통합·관리 → HAZOP 분석 → 검토·결과 관리**입니다.

## 프로젝트 방향

1. 자료 등록·추출·통합은 Python 자동 처리를 기본으로 하고, 결과는 공통 그래프 구조로 통합합니다.
2. 모든 정보에 원문 근거를 남기고, 미확인 정보와 자료 간 충돌을 표시합니다.
3. 사람이 노드와 관계를 직접 추가·수정할 수 있고, 이 변경도 같은 검증을 거칩니다.
4. 그래프 알고리즘과 원인·결과 패턴 라이브러리가 근거를 찾고, AI가 이를 해석해 HAZOP 초안을 만듭니다. AI 모델은 ① Claude API, ② Claude 팀 구독제 활용, ③ 로컬 LLM 순서로 구현합니다.
5. 각 단계는 다른 단계와 AI 없이 샘플 입력으로 독립 검증할 수 있어야 합니다.

세부 원칙은 [공통 원칙](기획서/전체기획.md#principles)에 한 번만 정의하고, 각 기획서는 단계 고유의 내용만 다룹니다.

## 대상 설계자료

| 자료 | 활용 방향 |
| --- | --- |
| 공정 설계 의도 및 설명서 | 공정 목적, 설비 역할, 분석 범위 정의 |
| PFD 및 물질·열수지 | 공정 흐름과 물질·에너지 정보 연결 |
| P&ID | 설비·배관·계기 및 연결 관계 추출 |
| 물성·위험성 자료 | 물질 특성과 위험성 연결 |
| 운전조건 및 허용 한계 | 정상 조건과 운전·설계 한계 연결 |
| 주요 기기·배관 설계 사양 | 용량·재질·등급 등의 속성 연결 |
| 제어·경보·인터록 설계 | 감지·제어·차단 조건과 동작 연결 |
| 압력 방출 및 비상 배출 설계 | 보호 대상과 방출 경로 연결 |
| 운전모드 및 주요 운전 절차 | 모드별 조건과 작업 절차 연결 |
| 유틸리티 및 외부 연결 조건 | 공급 의존 관계와 외부 설비 연계 |

위 10종은 모두 자료 등록의 대상이며, 확보되는 순서대로 반영합니다. MVP는 P&ID만 사용합니다. 단계별 입력 구분은 [최상위 플로우차트](<flow chart/00-overview.md>)에 정리합니다.

## 첫 개발 목표: 수직 슬라이스

사용자가 draw.io로 직접 만든 소규모 실험용 P&ID 한 장을 ①~⑤ 전 단계에 끝까지 통과시켜, 도면을 데이터로 분리해 HAZOP 초안을 만들 수 있는지 먼저 확인합니다.

**draw.io 샘플 → 등록정보 JSON → 추출 결과 JSON → 그래프·구조 검증 → 편차·탐색·패턴·AI 해석 → Excel 워크시트**

- 등록은 폴더와 Python 스크립트로 시작했습니다. 등록 화면은 [데스크톱 인터페이스](기획서/인터페이스.md)에서 구현할 예정입니다.
- 실제 도면의 자료형(PDF·DWG 등)은 실험 성공 후 형식별 읽기 어댑터를 모듈로 추가합니다.
- 결과는 사용자가 제공할 평가 기준과 비교합니다.

자세한 범위는 [MVP와 후속 범위](기획서/전체기획.md#mvp)를 참고합니다.

## 문서 구성

| 위치 | 역할 |
| --- | --- |
| `README.md` | 프로젝트 소개와 기획 문서의 진입점 |
| `flow chart/` | 전체 및 단계별 플로우차트: 순서·분기·입출력 |
| `기획서/` | 전체 및 단계별 기획서: 목적·요구사항·판단 기준·사례·미결정 사항 |
| `디자인/` | 실제 사용 시 화면·구성·사용 흐름의 뼈대 설계. 참고: ['출력화면 AX' 데모 분석](디자인/출력화면AX-데모분석.md) |
| `데이터/` | ④ 입력 데이터: 검토 구간 정의, 이탈 후보 카탈로그·적용 판단, 원인·결과 패턴, 위험도 임시 기준표, 고정 AI 응답 |
| `자료저장소/` | ① 등록 원본 저장 위치. 저장소에 포함하지 않음 |
| `메모리/` | 결정 로그와 미구현 작업 목록 |
| `hazop/` | Python 패키지: 추출·그래프·뷰어 |
| `scripts/` | 실행·검사 스크립트 |
| `tests/` | unittest 테스트 |
| `참고자료/` | 샘플 P&ID·기호 카탈로그. `참고 사진/`은 로컬 전용이며 저장소에 포함하지 않음. `HAZOP 기법/` PDF는 로컬 전용 |
| `출력/` | 생성 결과물. 저장소에 포함하지 않으며 아래 명령으로 재생성 |

플로우차트와 해당 기획서는 서로 링크합니다. 전체 흐름이 바뀌면 최상위 플로우차트에도 반영합니다.

## 실행 방법

저장소 루트에서 실행합니다. `PYTHONIOENCODING=utf-8` 설정은 권장하나 없어도 동작하며, 필요 패키지는 `networkx`, 검사용으로 `node`가 필요합니다.

1. `python scripts/extract_drawio.py --samples`
2. `python scripts/build_graph.py`
3. `python scripts/build_viewer.py` 후 `출력/뷰어/index.html`을 브라우저로 엽니다.
4. `python -m unittest discover -s tests -t .`
5. `python scripts/check_extract.py`, `python scripts/check_graph.py`, `python scripts/check_viewer.py`
6. `node scripts/check_viewer_paths.js`
7. 질의 예: `python scripts/query_graph.py SNP-M-101 path RC-RV01 RC-PP01 --mode physical`
8. 등록: `python scripts/register.py --project <ID> <파일.drawio> [--drawing-number X --revision 0 --title T --by 이름 --reason 사유]`
9. 등록 자료 추출: `python scripts/extract_drawio.py --registration 자료저장소/<ID>/registrations/<material_id>/<버전>.json`
10. 일괄(등록→추출→그래프→뷰어): `python scripts/run_samples.py` → `출력/samples/추출·그래프·뷰어/`(1~3번 `--samples` 결과와 분리). 앱 ① 화면은 `출력/추출/`만 보므로 이 결과(기본 프로젝트 sample-project)를 미추출로 표시함(데이터 손실 없음, 필요하면 ①에서 다시 추출)
11. HAZOP 분석(고정 응답): `python scripts/analyze.py` → 출력/분석/region-SNP-M-102-pzr/<실행ID>/analysis.json
12. 실제 API: `ANTHROPIC_API_KEY` 설정 후 `python scripts/analyze.py --live [--only p86-d09]`, 재시도 `--resume <실행 폴더>`, 그래프 버전 재연결 `--rebind-graph --confirm --by 이름 --reason 사유`
13. 검사 추가: `python scripts/check_register.py`, `python scripts/check_analysis.py`, `python scripts/refresh_fixture_hashes.py --check`
14. 데스크톱 앱(PySide6 필요): `python scripts/run_app.py [--run <분석 실행 폴더>] [--debug] [--screenshots <폴더>]`. `--screenshots`는 화면별 스크린샷을 저장한 뒤 종료
15. 워크시트 내보내기(openpyxl 필요): `python scripts/export_worksheet.py --run <분석 실행 폴더> [--scope all|accepted_modified] [--store-root <저장 루트>] [--out-root <출력 루트>]`
16. 근거 묶음 내보내기: `python scripts/export_bundles.py [--region <구간 JSON>] [--graph <그래프 JSON>] [--out-root <출력 루트>]`
17. 지식 빌드: `python scripts/build_kg.py <프로젝트 ID>` → `출력/지식그래프/<kg_id>/current.json` 포인터(입력 `데이터/지식/<프로젝트 ID>/`)
18. 엔티티 연결(`--graph-id` 필수, 반복 지정 가능): `python scripts/link_kg.py candidates|confirm-exact|apply <프로젝트 ID> --graph-id <그래프 ID>` (`confirm-exact`는 `--reviewer`·`--reason` 포함)
19. 그래프 알고리즘 A1~A5: `python scripts/analyze_kg.py <프로젝트 ID> --start <노드 ID> [--radius 2] [--region <구간 JSON>] [--graph-id <그래프 ID>]`
20. 지식그래프 검사: `python scripts/check_kg_renderer.py`, `python scripts/check_kg.py`, `python scripts/check_kg_link.py`, `python scripts/check_kg_algo.py`
21. 출력 정리: `python scripts/clean_outputs.py [--keep 5] [--apply] [--out-root <출력 루트> --store-root <저장 루트>] [--no-review-records]`. 기본은 후보 목록만 출력(dry-run). `--apply`일 때만 구간별 최근 N개 밖의 분석 실행(검토 기록·평가 비교 보고서·설정 recent_runs가 참조하는 실행은 보존)과 지식그래프 옛 경로 파일·이전 버전 폴더를 `출력/_보관/<시각>/`으로 옮기고 `manifest.json`에 기록(삭제 안 함). 주의: 앱·`analyze.py`·`build_kg.py`를 끝낸 뒤 `--apply`(이동 직전 재확인은 검토 기록·평가 비교·kg `current.json`만 보며, `recent_runs`와 새 실행의 kg 참조는 이 운영 지침에 의존)
