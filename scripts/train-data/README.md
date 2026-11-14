# scripts/train-data — 기호 검출 학습 자료 만들기

P&ID 기호·글자·연결을 읽는 학습 모델의 학습 자료(COCO 검출 JSON, 연결 그래프)를 만드는 시험 스크립트를 둔다.
설계와 시험 값은 `docs/units/2026-11-13-drawing-knowledge/evidence/training-data-plan.md`에 있다.

## 무엇을 넣는가

- `coco_format.py`: 세 길이 함께 쓰는 형식(종류 목록, COCO 쓰기, 쪽 그림 그리기)
- `export_snp_training.py`: 가상 도면 drawio 원본 → 쪽 그림 + 정답
- `build_synthetic_pages.py`: 기호 사전 그림으로 가상 쪽을 무작위로 그리고 정답을 함께 씀
- `build_vector_labels.py`: 벡터 PDF 후보 상자 + 구독 AI 종류(그림 조각), `vision_client.py`가 그림을 보냄
- `compare_vector_labels.py`: 만든 정답을 읽기 품질 정답지(시험 집합)와 견줌

## 넣지 않는 것

- 만든 자료(쪽 그림, 조각, COCO JSON, AI 답). 저장소 밖 시험 폴더(`<날짜>-train-data`, 위치는 설계 문서 부록)에 둔다. APR1400에서 나온 것은 저작권 표시 때문에 저장소에 넣지 않는다(설계 문서 §5).
- 학습 코드와 가중치. 학습은 GPU가 있는 다른 환경에서 한다.
- 보안 등급이 있는 실제 설계자료를 읽는 설정.

## 이름 형식

`<동사>_<대상>.py`(HZ-GOV-02 §4.4). 같은 폴더 안에서만 쓰는 모듈은 동사 없이 `<대상>_<꼴>.py`로 둔다(`coco_format.py`, `vision_client.py`).

## 주인

도면 읽기 단위(`docs/units/2026-11-13-drawing-knowledge/`). 총괄이 승인한다.

## 폐기 기준

학습 길을 멈추기로 하면(설계 문서 §6 멈춤 기준) 이 폴더를 지운다. 앱이 이 폴더를 불러오지 않으므로 지워도 앱에 영향이 없다.
