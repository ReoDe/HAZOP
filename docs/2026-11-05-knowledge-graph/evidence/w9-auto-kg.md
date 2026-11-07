# W9 증거: 지식그래프 자동 생성과 문서 지식 추출 (2026-11-07)

규격: [그래프활용 §9](../../../기획서/그래프활용.md#9-지식그래프-자동-생성과-문서-지식-추출). 결정: [decisions D12](../decisions.md).
입력 자료는 저장소의 가상 샘플만 썼다(SNP-M-101·SNP-M-102 도면, `tests/fixtures/docextract/`의 가상 설계 문서). 실제 설계자료는 쓰지 않았다.

## 커밋

| 커밋 | 내용 |
| --- | --- |
| `79b258f` | `hazop/kg/docextract.py`(규칙 기반 문서 지식 추출), `hazop/kg/auto.py`(프로젝트 조립), `build_kg`의 `pid_graphs`, 가상 문서 PDF와 생성기 |
| `31ba215` | ① 설계 문서 등록·자동 추출, 도면 추출 뒤 지식그래프 자동 빌드, ③ 자동 빌드·안내 문구·배지·기본 표시, 다른 자료 종류 재등록 보류 |
| `bd0acc3` | 검토 1회 지적 반영: 값마다 자기 마디만 사용, 프로젝트 전체에서 하나뿐인 태그만 연결, 지수 표기 거부, 조립 안내 표시 |

## 검토 1회 (총괄 규칙 3)

- Claude 검토: 조건부 승인. 차단 2건(설정치 낱말이 뒤 값까지 바꿈, 낱말·값 거리 제한 없음과 `trip` 단어 경계)은 `bd0acc3`에서 수정. 차단 경계 2건 중 여러 도면 태그 연결은 수정, `graph-drawing` 합침은 조립 안내 표시로 드러내고 근본 원인(1단계 PDF 도면번호·태그)은 후속. 문서 지적(증거 파일 없음, 날짜 불일치, 용어)은 반영.
- Codex 교차검증(`gpt-6.1-sol`, medium): 반려 4건(지수 표기, 앞 값 낱말 재사용, 여러 도면 태그 연결, 문장 안 태그·값 교차 연결). 모두 재현 확인 뒤 `bd0acc3`에서 수정하고 재현 문장을 `tests/test_kg_auto.py`에 넣음.
- 재검토는 하지 않음(규칙 3). 수정 뒤 전체 검사를 다시 돌림(아래).

## 검사 (전용 venv `%USERPROFILE%\.hazop\venv-py312`, `bd0acc3` 기준)

| 명령 | 결과 |
| --- | --- |
| `python -m unittest discover -s tests -t .` | `Ran 897 tests` · `OK (skipped=19)` |
| `python scripts/check_kg.py` | `결과: 통과` |
| `python scripts/check_kg_screen.py` | `[OK] 단위·Qt 테스트 33개` · `결과: 통과` |
| `python scripts/check_contract.py` | `PASS 22 · FAIL 0 · WARN 0 · SKIP 15` |
| `python scripts/check_app.py` | `[OK] 단위 테스트 34개` · `결과: 전부 통과` |
| `python scripts/build_package.py --build --out <저장소 밖>` | 종료 코드 0, 결과 폴더 검사·바이너리 검사 통과 |
| `python packaging/verify_bundle.py --dist <dist\HAZOP> --target-base … --out … --app-only` | `오류 없음, 결과 통과`(`repo_unchanged: True`, `pdf_problems: []`) |

## 배포본 실측

방법: `bd0acc3`로 검증용 묶음(`build_package.py --build --with-check`, 배포용과 같은 앱 코드)을 만들고, 묶음의 `HAZOP-check.exe`로 저장소 밖 구동 스크립트를 실행했다. 스크립트는 주 창(`MainWindow`)을 열고 ① 화면 함수(파일 지정·자료 종류·등록·추출)를 사람이 누르는 순서대로 부른 뒤 화면을 찍는다. 작업 루트·저장 루트는 임시 폴더다. 배포용 `HAZOP.exe` 창을 사람이 직접 조작한 것은 아니다.

| 단계 | 결과 |
| --- | --- |
| drawio 도면 SNP-M-102 등록 → 추출 | `kg-accept-demo` `passed`, `graph_refs` = graph-SNP-M-102, ③ 노드 30(지식 입력 없음, 도면 기반) |
| PDF 도면 SNP-M-101 등록(표제란 도면번호 후보 확정) → 자동 추출 | `passed`, `graph_refs` 2개, ③ 노드 61 |
| 가상 설계 문서 PDF 등록(설계 문서) → 자동 지식 추출 → ③ | `passed`, 추출 15항목(설계 의도·요건 4, 운전조건 3, 설정치 3, 문서 조각 5) 모두 ③ 표시, 후보 관계 6개(RC-PIC110·RC-PSV101 `has_setpoint`, RC-PIC110·RC-PV101·RC-LT110 `governed_by`), 상세 패널에 '자동 추출 · 사람 확인 전' 배지와 근거 `2쪽 · '3. 설정치' · 줄 1–4` |

화면 캡처(저장소에는 넣지 않음, 세션 공유 노트 폴더 `stage2-screens/`): `03-kg-after-drawio.png`, `03-kg-pdf-drawing-SNP-M-101.png`, `03-kg-setpoint-detail.png`, `01-register-design-doc.png`, `report.json`.

## 남은 일(후속)

1. 1단계 PDF 어댑터가 객체의 `tag`를 채우지 않는다(SNP-M-101 PDF에서 `missing_tag` 16건, 라벨 원문에는 `RC-PV101` 등이 있음). 그래서 PDF 도면에는 문서 태그가 연결되지 않는다.
2. PDF 도면번호를 확정하지 않으면 `graph_id`가 `graph-drawing`이 되어, 같은 프로젝트의 그런 도면 여러 장 중 가장 최근 것만 지식그래프에 들어간다. 지금은 ① 조립 안내로만 알린다.
3. 자동 추출 항목을 사람이 확인(confirmed)하는 화면이 없다. 지금은 지식 CSV로 옮겨 적어야 한다.
4. 표 안의 값, 여러 줄 표 행, 낱말 목록 밖 표현은 추출하지 않는다(§9.2 한계).
