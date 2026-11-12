# resources/samples — 표본

새 작업 루트를 채우는 표본 데이터다(옛 자원/표본/ 폴더). `scripts/seed_samples.py`가 작업 루트로 복사한다.

## 무엇을 넣는가

- `regions/`: 표본 검토구간
- `fixed-responses/`: AI 고정 응답
- `knowledge-graph/`: 표본 지식그래프
- `evaluation-criteria/`: 표본 평가 기준

## 넣지 않는 것

- 읽기 전용 기준 자료는 `resources/library/`에 둔다.
- 이 `README.md`는 표본이 아니다. `seed_samples.py`가 복사하지 않는다.

## 이름 형식

하위 폴더 이름은 `hazop/paths.py`의 `SAMPLE_FOLDERS`와 같다.

## 주인

총괄이 승인한다. 고정 응답은 해시가 묶음에 들어가므로 바꾸면 `scripts/refresh_fixture_hashes.py`로 다시 맞춘다.

## 폐기 기준

표본을 쓰는 시험이 없어지면 함께 지운다.
