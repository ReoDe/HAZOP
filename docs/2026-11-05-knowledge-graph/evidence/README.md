# 지식그래프 활용 구현 증거

> 조사·검증 결과와 작업 상태 판정의 근거를 보관한다.

## 기록 규칙

- 근거마다 조사 일시, 대상 경로 또는 커밋, 확인한 사실, 판정에 미치는 영향을 기록한다.
- 원문 전체를 복사하지 않고 저장소 경로와 필요한 발췌 위치를 연결한다.
- 비밀번호, 토큰, 개인정보 등 민감정보는 기록하지 않는다.
- 증거가 추가되면 아래 인덱스와 [`PROGRESS.md`](../PROGRESS.md)의 관련 상태를 함께 갱신한다.

## 증거 인덱스

| 일시 | 증거 | 확인한 사실 | 상태 영향 |
|---|---|---|---|
| 2026-11-05 10:28 | [`기획서/그래프조사.md`](../../../기획서/그래프조사.md) | 그래프 알고리즘·Obsidian 그래프 뷰·렌더러 조사(aside-browser, 출처 URL 포함) | `W1` 조사 근거 |
| 2026-11-05 10:28 | [`기획서/그래프활용.md`](../../../기획서/그래프활용.md), [ReoDe/HAZOP#5](https://github.com/ReoDe/HAZOP/pull/5) | 구현 구상 기획. 재작업 2회 후 Claude 검토 승인, Codex 조건부 승인(조건 반영) | `W1` 계획 근거, `W2`~`W8` 등록 |
| 2026-11-05 10:28 | W1 등록 검토(hazop-reviewer) | WP↔W 대응·완료 기준·의존성이 원본과 일치. 지적 9건 중 문서 수정은 총괄이 반영, 편집 범위 공백은 PROGRESS §5 열린 항목으로 기록 | `W1` 완료 |
| 2026-11-05 11:20 | `scripts/check_kg_renderer.py`, `tests/test_kg_renderer.py`, `hazop/kg/vendor/force-graph-1.52.0/SOURCE.md` | force-graph 1.52.0을 앱과 같은 차단 설정의 offscreen 웹뷰에서 인라인 적재 시 40노드 렌더 성공(페이지 오류 0). `<script src>` 적재는 실패(`LocalContentCanAccessFileUrls` 꺼짐). SHA-256 일치. 성능 참고(offscreen·GPU 끔, 합격 기준 아님): 5,000노드 첫 프레임 약 0.1 s, 로드 포함 약 1.5 s | `W2` 판정 근거. `W6`으로 넘길 제약: ① 인라인 필수 ② `template.html` 대신 별도 HTML ③ V2는 D5 해석 ④ 성능 수치는 실제 화면·GPU 값이 아니므로 §7.3 상한 판단에 그대로 쓰지 않음 |
| 2026-11-05 11:25 | `hazop/kg/`(inputs·build), `scripts/build_kg.py`·`check_kg.py`, `tests/test_kg.py`, `tests/fixtures/kg/`, `데이터/지식/SNP-SAMPLE/` | 가상 정상 샘플 passed(차단 0·미확인 5·충돌 1), 차단 픽스처 8종 기대 blockers 일치, K1~K8 통과. 결과는 버전 폴더 + `current.json` 포인터로 원자적 교체. Codex 교차검증 5회차 승인 | `W3` 완료 판정 |
