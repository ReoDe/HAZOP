# W2 평가 하네스 — 구현·검증 기록

> 기록 일시: 2026-11-05 (재작업 1회차 반영) · 기준 커밋: `b29e5f7`(브랜치 `chore/track-workspaces`, 미커밋 변경) · 작성: hazop-developer
> 근거 결정: [decisions.md](../decisions.md) D1 · 조사: [w1-survey.md](w1-survey.md) §4·§6

## 1. 산출물

| 경로 | 내용 |
|---|---|
| `hazop/extract/adapters/evaluation.py` | `evaluate(truth, candidate, transform=None, params=None)` → 결정적 dict, `dumps()`(키 정렬 JSON), `render_report()`(Markdown) |
| `scripts/check_adapter.py` | 인자 없음: 검사(픽스처 + 샘플 6세트). `--truth --candidate [--transform] [--out]`: `evaluation.json`·`evaluation.md` 저장 |
| `tests/test_adapter.py` | 단위·픽스처·샘플(SNP-M-102)·반려 재현 사례 테스트 23건 |
| `tests/fixtures/adapter/truth_small.json` | 가상 소형 정답지(노드 6, 관계 5, tee 1개 포함) |

## 2. 평가 규칙 (D1 구현 방식)

- **보이는 글자**: `label_text`를 NFKC·공백/줄바꿈 제거·대문자로 정규화. 태그는 P/R/F1로 낸다. TP는 대응 쌍의 글자 일치, FN은 보이는 글자가 있는 정답 노드 중 TP가 아닌 것, FP는 글자가 있는 후보 노드 중 TP가 아닌 것(허위 글자 노드 포함)이다.
- **객체 대응** 자격(하나라도 만족): ① 글자 일치 + bbox 중심 거리 ≤ 50, ② IoU ≥ 0.5, ③ 작은 기호(정답 bbox 짧은 변 ≤ 10) + 중심 거리 ≤ 10. 비용 = 글자 불일치 1000 + 10×(1−IoU) + (IoU=0일 때만) 정규화 중심 거리 0~1 + kind 불일치 0.001이다. D1 순서(글자 → IoU → kind)를 따르고, 헝가리안 1:1 할당은 직접 구현했다. 가중 합이므로 IoU 차가 0.0001 미만인 경우에는 kind가 순서를 바꿀 수 있다. 객체 P/R/F1은 대응 수 기준이고 kind·category 정확도는 대응 쌍에서 따로 낸다.
- **관계**: 양 끝을 대응된 정답 id로 바꾼 무방향 쌍 + 관계 kind가 같아야 일치(중복은 개수로 셈). 끝 표식은 튜플이라(`("node", id)`, `("cand", "unmatched", id)`) 실제 id 문자열과 충돌하지 않는다.
- **P/R/F1**: 정답·후보가 모두 비었을 때만 null이다. 한쪽만 비면 0이다.
- **화면 근거 없는 속성**: 정답 노드 속성(kind 제외) 값의 토큰열이 보이는 글자의 토큰열(공백·줄바꿈 기준 단어)에 연속으로 없으면 non_visual로 키별 집계. 주 지표에 넣지 않는다. tag는 있지만 글자가 없는 노드(tee) 목록도 따로 둔다.
- **좌표 정규화**: 추정하지 않는다. `transform = {"scale": s 또는 [sx, sy], "offset": [ox, oy]}`(정답 = 후보 × scale + offset)을 입력으로 받는다. 축별 scale은 0이 아닌 유한한 수이고, 음수는 축 반전(예: PDF y 위쪽 증가)이다.
- **blocked**: 좌표계(`coordinate_space`·`unit`)가 다른데 transform이 없을 때, 정답의 coordinate_system이 없을 때, 후보의 coordinate_system이 없는데 transform도 없을 때, nodes·source_locations에 같은 local_id가 중복될 때 blocked가 된다.
- **CLI `--out`**: 폴더 자체나 그 안에 쓸 `evaluation.json`·`evaluation.md`가 입력 파일과 같은 경로면 거부한다(rc=2).
- **GED**: 노드·관계 label = kind. 동형(VF2)이면 0(exact). 아니면 `networkx.graph_edit_distance`(시간 제한 5초)를 시도하고, 실패하면 `not_computed`와 사유를 남긴다.

## 3. 검증 결과 (2026-11-05 실행)

- `python scripts/check_adapter.py` → rc=0. 픽스처 1건과 샘플 6세트 모두 통과.
- `python -m unittest tests.test_adapter` → 23건 OK. `python -m unittest discover -s tests -t .` → 488건 OK, rc=0.
- 결정성: 같은 입력을 두 번 실행한 결과와 입력 목록 순서를 뒤집은 결과의 JSON이 같다. 별도 프로세스로 두 번 CLI를 실행한 결과도 바이트 단위로 같다.

시나리오별 관계 F1(주 지표) / 객체 F1:

| 시나리오 | 픽스처 | 101 | 102 | 201 | 301 | 401 | 501 |
|---|---|---|---|---|---|---|---|
| 정답지끼리 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| 태그 오타(태그 정확도만 1건 감점) | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| 객체 누락(연결 k개 함께 제거) | 0.889 / 0.909 | 0.923 / 0.986 | 0.848 / 0.973 | 0.978 / 0.977 | 0.895 / 0.976 | 0.957 / 0.979 | 0.974 / 0.974 |
| 연결 뒤바꿈(2건) | 0.600 / 1 | 0.943 / 1 | 0.895 / 1 | 0.913 / 1 | 0.905 / 1 | 0.917 / 1 | 0.900 / 1 |
| 객체 1개 이동(페이지 밖) | 0.800 / 0.833 | 0.857 / 0.971 | 0.737 / 0.947 | 0.957 / 0.955 | 0.810 / 0.952 | 0.917 / 0.958 | 0.950 / 0.950 |
| 전체 이동, transform 없음 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 전체 이동·배율 2(+20), transform 있음 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| y 반전(scale [1, −1], offset 1200), transform 있음 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| 좌표계 다름, transform 없음 | blocked | blocked | blocked | blocked | blocked | blocked | blocked |

검사는 객체·관계·태그의 TP·FP·FN·P·R·F1을 기대값과 정확히 비교한다. 기대값은 오류 주입 내용에서 `ev.prf`와 독립적으로 직접 나눠 계산한다. 예를 들어 객체 누락은 객체 (N−1, 0, 1), 관계 (E−k, 0, k)이다. 태그는 오타·객체 이동이 (V−1, 1, 1), 객체 누락이 (V−1, 0, 1), transform 없는 전체 이동이 (0, V, V)이다.

## 4. 한계·확인 필요

- **[사실] networkx GED는 scipy가 필요한데 scipy가 설치되어 있지 않다**(`ModuleNotFoundError: scipy`, networkx 3.7). 그래서 동형이 아닌 경우의 GED는 현재 모두 `not_computed`(사유 `dependency_missing: scipy`)로 나온다. 동형 판정(GED=0)은 scipy 없이 동작한다. GED 값을 실제로 내려면 scipy 설치 승인이 필요하다(사용자 결정 사항).
- **[사실] kind만 label로 쓰는 GED는 객체 대응과 무관하다.** 태그 오타, 객체 이동, 전체 이동에서는 GED가 0이다. 102·401의 연결 뒤바꿈도 kind 기준으로 동형이어서 GED가 0으로 나온다. 연결 오류는 관계 F1(주 지표)로 판단해야 한다.
- **[추론] scipy가 있을 때 시간 제한에 걸리면** 값이 실행 속도에 따라 달라질 수 있다(`upper_bound_timeout` 표시). 그 경우 GED 필드는 결정성 비교 대상에서 빼야 한다.
- **[추론] 문턱값**(글자 중심 거리 50, 작은 기호 10)은 drawio canvas_unit 기준 시작값이다. W3·W4의 첫 측정 후 조정해야 한다. IoU 0.5는 D1을 그대로 따른다.
- 관계의 화면 근거 없는 속성(`flow_direction`·`line_no` 등)은 집계하지 않는다. 노드 속성만 집계한다.
- 교차하지만 연결되지 않은 선을 연결로 만든 오탐을 따로 집계하는 기능(W1 §4.4 비고)은 구현하지 않았다. 지금은 일반 관계 FP로 셈한다.
- 평가 입력은 W1 §6의 extraction.json 계약에서 쓰는 키 일부만 읽는다(evaluation.py 머리말). 후보의 전체 스키마 검증은 하지 않는다.
