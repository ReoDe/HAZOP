# tests/baselines — 회귀 기준값

검사 스크립트가 비교하는 점수 파일을 둔다.

## 무엇을 넣는가

- `snp_baseline.json`: 샘플 도면 6장의 기준값(`scripts/check_snp_baseline.py`)
- `apr1400_score.json`: APR1400 정답지 점수(`scripts/check_apr1400.py`)

## 넣지 않는 것

- 시험 입력은 `tests/fixtures/`에 둔다.

## 이름 형식

`<대상>.json`. 점수는 '맞은 수/분모 @커밋'으로 보고한다.

## 주인

기준값은 그 단위의 주인만 `--update`로 갱신한다. 기준값이나 점수에 닿는 입력에 커밋하지 않은 수정이 있으면 스크립트가 거부한다(`CLAUDE.md` 규칙 12).

## 폐기 기준

검사 스크립트를 지울 때 같은 커밋에서 지운다.
