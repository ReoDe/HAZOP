# 지식그래프 활용 구현 결정 기록

> 설계·정책·작업 기준에 관한 결정을 근거와 함께 누적한다. 진행 상태는 [`PROGRESS.md`](PROGRESS.md)에만 기록한다.
> 열린 결정이 실행 순서나 게이트에 영향을 주면 [`ROADMAP.md`](ROADMAP.md)와 함께 갱신한다.

## 결정 목록

범위 확장 결정에는 사유, 추가·제외 범위, 관련 작업 ID, 기존 완료 기준·일정·의존성에 미치는 영향과 사용자 요청 또는 결정 근거를 기록한다. 확정되지 않은 선택은 열린 상태로 구분한다.

| ID | 일자 | 결정 | 근거 | 상태 |
|---|---|---|---|---|
| D1 | 2026-11-05 | ③ 지식그래프 탭 신설([그래프활용 §8.2 D1](../../기획서/그래프활용.md)). 기존 '화면 ①②④⑤' 사용자 결정을 개정함 | 그래프활용.md 검토 시 총괄이 위임 승인으로 채택, 2026-11-05 사용자 재확인으로 확정 | 확정 |
| D2 | 2026-11-05 | 편집 허용 범위에 `기획서/인터페이스.md`·`기획서/전체기획.md` 추가. 용도는 D1(③ 화면)의 본문 반영으로 한정, `W6`에서 수행 | D1 확정 시 두 문서 갱신이 구현 시점 작업으로 정해짐(그래프활용 §5.3). 총괄 판정 | 확정 |
| D3 | 2026-11-05 | `W3` 편집 허용 범위에 `데이터/지식/`(가상 정상 샘플)과 `tests/fixtures/kg/`(차단 픽스처) 추가. 결과는 gitignore 대상인 `출력/지식그래프/` | 그래프활용 §2.6 저장 위치 [제안]과 §7.1 픽스처 분리. 사용자 목표 지시(2026-11-05 "끝까지 진행")에 따른 총괄 판정 | 확정 |
| D4 | 2026-11-05 | `W2`: force-graph 1.52.0 UMD를 `hazop/kg/vendor/force-graph-1.52.0/`에 반입(사용자 다운로드 승인). 편집 범위에 `scripts/check_kg_renderer.py`·`tests/test_kg_renderer.py` 추가 | 사용자 승인(2026-11-05), 그래프활용 §5.2 vendoring | 확정 |
| D5 | 2026-11-05 | `W2` 완료 기준을 force-graph 단독 확인으로 조정(사용자가 force-graph 다운로드만 승인, Cytoscape.js 비교 생략). 렌더러는 force-graph로 확정(그래프활용 D8), 조건은 vendor 인라인 적재. `W6`에서 force-graph가 요구를 못 채우면 대안 반입을 새 결정으로 연다. V2의 '외부 URL 참조'는 생성 부분 기준으로 해석하고 vendor 본문은 SHA 고정·허용 목록으로 판정(그래프활용 §7.2 V2 문구 개정) | 사용자 승인 범위(D4), W2 검토 지적 | 확정 |
| D6 | 2026-11-05 | `W3` 검토 판정: ① `scripts/build_kg.py`(CLI)를 편집 범위에 추가 ② 기획서에 없던 차단 규칙 수용 — confirmed 관계에 `reviewed_by` 없음(K1), 필수값 빈 칸, 양 끝 지식 노드 관계는 `from` 쪽 근거 상속 ③ K7 충돌 비교에서 운전 모드 빈 칸은 모든 모드와 비교(추정 금지) ④ mentions 근거는 조각 ID·원문 해시·일치 위치가 모두 있어야 인정 ⑤ 재추출로 태그가 사라지면 `graph_version` 변경 시 재확인 필요, 같으면 K2 차단 ⑥ 재확인 비교에 `target_source_object_id` 포함 ⑦ `knowledge_links.csv`에 처리기 이름·점수 열은 두지 않음(§2.6 열 규격, `W4`의 `link_candidates.csv`에서 보존) — Codex 지적 반려 | `W3` Claude 검토(조건부 승인)·Codex 교차검증(반려) 총괄 판정, 그래프활용 §2.4·§3.2 개정 | 확정 |
| D7 | 2026-11-05 | `W3` 재작업 3회차는 사용자 허용, 4차 Codex 지적(후보 키·행 불일치 우회) 1건은 총괄이 직접 수정. `W4`·`W5`는 파일이 겹치지 않게 나눠 병행: `W4` 범위 `hazop/kg/link.py`·`scripts/link_kg.py`·`scripts/check_kg_link.py`·`tests/test_kg_link.py`·`tests/fixtures/kg_link/`·`데이터/지식/`(후보 CSV), `W5` 범위 `hazop/kg/algo.py`·`scripts/analyze_kg.py`·`scripts/check_kg_algo.py`·`tests/test_kg_algo.py`·`tests/fixtures/kg_algo/`. 두 작업 모두 `hazop/kg/build.py`·`inputs.py`는 읽기만 | 사용자 목표 지시(2026-11-05 "W5까지 끝까지"), 병렬 원칙 | 확정 |
