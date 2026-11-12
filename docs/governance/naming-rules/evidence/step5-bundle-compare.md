# 단계 5 전후 대조: 그래프 판, 고정 응답 해시, 기준값, 배포본 묶음, 창 시나리오

이름 이전 단계 5(자원 폴더를 `resources/`로 옮김)를 옮기기 전과 옮긴 뒤에 같은 방법으로 뽑아 맞대어 본 결과다. 2026-11-10, 단위 NAMING N3 하위 세션. 출력은 모두 저장소 밖 `D:\HAZOP-trials\2026-11-10-naming-n3\`에 있다(`keep_until: 2026-11-24`).

- 전: 커밋 `8f944e5`의 작업트리(깨끗한 상태).
- 후: `git mv` 커밋 `585d0a1` 위에 폴더 표·코드·링크 수정을 얹은 작업트리(다음 커밋의 내용). 추적하지 않는 APR1400 원본·쪽별 PDF도 새 이름으로 옮긴 상태다(`step5-moves.csv`).

멈춤 기준 세 가지(고정값을 고쳐야 통과하는 시험, 기준값 점수 변화, 묶음의 대응표 밖 차이)에 걸린 것은 없다.

## 1. 그래프 판과 고정 응답 해시

`capture_pins.py`가 임시 작업 루트에서 `scripts/extract_drawio.py --samples`, `scripts/build_graph.py`를 실제로 돌리고, 벡터 PDF 6장은 `pdf_vector.extract`로 뽑아 그래프를 만든다. 전후 목록(`pins-before.txt`, `pins-after.txt`)은 고정 응답 폴더 이름 다섯 줄만 다르고 나머지는 글자 하나 다르지 않다.

| 도면 | drawio 판(전 = 후) | PDF 판(전 = 후) |
| --- | --- | --- |
| SNP-M-101 | `v-336f3b0a099c` | `v-46619ea99ad3` |
| SNP-M-102 | `v-f65e4ec1135d` | `v-2794530b0a56` |
| SNP-M-201 | `v-d34244708d8e` | `v-a031b7c5223b` |
| SNP-M-301 | `v-20be8eacd726` | `v-ccf595253369` |
| SNP-M-401 | `v-5fca4d2be3b7` | `v-40738865966b` |
| SNP-M-501 | `v-6c861ce33412` | `v-d0d91bbb52c5` |

- 추출 JSON의 `source.file`과 `svg_file`은 전후 모두 `참고자료/P&ID 도면 샘플/<도면 폴더>/…`다. `graph.json` 6개의 SHA-256도 같다.
- SNP-M-102의 `v-f65e4ec1135d`는 표본 구간 JSON과 시험 입력에 고정된 값과 같다.
- `bundle_sha256`: 다시 계산한 후보 25개의 해시가 전후로 같고, 저장소에 고정된 6개(표본 5개, `tests/fixtures/analysis/bad/` 1개)와도 같다.
- `scripts/refresh_fixture_hashes.py --check`: 전후 모두 종료 코드 0, 6개 파일 모두 '최신'.
- APR1400 두 쪽(순번 005, 061)도 견줬다. `8f944e5`의 분리 작업트리에 PDF를 옛 자리(자원/참고자료/APR1400_DCD/도면별/)로 복사해 뽑은 값과 옮긴 뒤 값이 같다: `v-6c65e2cfedeb`, `v-37b7906608db`, `source.file`은 `데이터/참고자료/APR1400_DCD/도면별/…`(`apr-version-before.txt`, `apr-version-after.txt`).
- 개발 작업 루트(`D:\HAZOP\작업`)에 저장된 기록 경로 357건을 `8f944e5` 코드와 지금 코드로 풀어 봤다(`resolve_records.py`). 풀린 수 254, 안 풀린 수 103이 전후로 같다. 안 풀린 103건은 경로가 아닌 값(해시, ID)이거나 지워진 임시 폴더다.

고정값이 든 파일은 하나도 고치지 않았다. `git diff --stat -M 8f944e5..HEAD -- resources tests/fixtures tests/baselines`에서 `resources/` 아래 162개 가운데 159개는 이름만 바뀌었다(R100). JSON·CSV·도면·그림은 모두 여기에 든다. 내용이 바뀐 셋은 문서 `drawing-list.md`와 그것을 만드는 스크립트 두 개(`APR1400_DCD/scripts/`)다. `tests/baselines/`는 변경 0, `tests/fixtures/`는 `apr1400/SOURCE.md`의 백틱 경로 한 줄뿐이다.

## 2. 기준값

둘 다 `--update` 없이 돌렸다.

| 검사 | 전(`8f944e5`) | 후 |
| --- | --- | --- |
| `scripts/check_snp_baseline.py` | `SNP: 후퇴 0 · 나아짐 6 · drawio 짝 12 · 방향 모순 0 · 도면 drawio 6 · pdf 6`, 종료 코드 0 | 같은 줄, 종료 코드 0. 출력 전체가 같다(`diff snp-before.log snp-after.log`) |
| `scripts/check_apr1400.py` | `APR1400: 태그 정확 872/1619(원) · 텍스트 층에 없는 태그 47 · 연결 표기 검출 286/295 · 없는 대상 0 · 짝 279(정답 짝 6/6 · 틀린 짝 0 · 후보 10) · 미확인 63723`, 종료 코드 0 | 같은 줄, 종료 코드 0. 쪽별 결과 143줄은 걸린 시간 열만 다르다(`apr1400-before.csv`, `apr1400-after.csv`) |

`check_snp_baseline.py`는 '맞은 수/분모'가 아니라 후퇴·나아짐 수를 찍는다. `check_apr1400.py`는 입력 폴더를 주지 않고 돌렸으므로, 후 실행은 새 자리(`resources/references/APR1400_DCD/by-drawing/`, `drawing-list.csv`, `system-codes.csv`)를 스스로 찾은 것이다.

## 3. 배포본 묶음

빌드와 검증은 전후 모두 같은 명령이다.

```
<venv python> scripts/build_package.py --with-check --build --out <시험 폴더>/build-<before|before-2|after>
<venv python> packaging/verify_bundle.py --dist <…>/dist/HAZOP-verify --target-base <시험 폴더>/vt --out <시험 폴더>/verify-<before|after>
```

| 무엇 | 전 | 전(같은 소스 두 번째 빌드) | 후 |
| --- | --- | --- | --- |
| 빌드 종료 코드 | 0 | 0 | 0 |
| `verify_bundle.py` | 0 (묶음 576.7 MB, 파일 2641개, 오류 없음) | 돌리지 않음 | 0 (묶음 576.7 MB, 파일 2641개, 오류 없음) |
| 묶음 파일 수(`list_bundle.py`) | 2641 | 2641 | 2641 |

### 같은 소스를 두 번 빌드한 차이 (빌드 자체의 흔들림)

`before.csv`와 `before-2.csv`는 세 파일의 바이트가 다르다: `HAZOP.exe`, `HAZOP-check.exe`, `_internal/base_library.zip`. 속을 풀면(`compare_exe_parts.py`, `exe-parts-same-source.txt`) 다른 것이 없다. PYZ 모듈 1021개·1027개의 내용이 모두 같고, 실행 파일의 묶음 항목 15개·13개도 모두 같고, `base_library.zip` 항목 155개의 CRC·이름·시각도 같다. 이 세 파일의 바이트는 소스가 같아도 빌드할 때마다 달라진다. N2가 추정으로 남긴 것을 이번에 대조로 확인했다.

### 전후 대조 (`compare_bundle.py`, `bundle-compare.txt`)

| 구분 | 수 | 파일 |
| --- | --- | --- |
| 경로와 내용이 같음 | 2588 | |
| 대응표대로 경로만 바뀜(내용 같음) | 48 | `_internal/자원/기준/…` → `_internal/resources/library/…`. 기준표 2, 기호 사전 43(묶음 목록 1, APR1400 항목 20·그림 20, 공통 항목 1·그림 1), 이탈 후보 2, 패턴 1 |
| 대응표대로 옮겨지고 내용도 바뀜 | 0 | |
| 경로는 같고 바이트가 다름 | 5 | `HAZOP.exe`, `HAZOP-check.exe`, `_internal/base_library.zip`, `_internal/scripts/extract_drawio.py`, `_internal/scripts/extract_pdf.py` |
| 빠진 파일 | 0 | |
| 새로 생긴 파일 | 0 | |

바이트가 다른 다섯 파일의 속(`exe-parts-compare.txt`, `git diff --numstat 585d0a1`):

| 파일 | 다른 곳 | 까닭 |
| --- | --- | --- |
| `scripts/extract_drawio.py`, `scripts/extract_pdf.py` | 각 2줄 | 샘플 폴더 이름(`"P&ID 도면 샘플"` → `"pid-samples"`)과 사용 예의 경로 |
| `HAZOP.exe` | 묶음 항목 15개 중 `PYZ.pyz` 하나 | 아래 모듈 |
| `HAZOP-check.exe` | 묶음 항목 13개 중 `PYZ.pyz` 하나 | 아래 모듈 |
| `PYZ-00.pyz`(앱, 모듈 1021개, 전후 이름 같음) | 모듈 6개 | `hazop.paths`(폴더 표와 옛 이름 표), `hazop.extract.symbols`(묶음 목록 파일 이름, 묶음 폴더·예시 그림 찾기), `hazop.graph.project`(`system-codes.csv`), `hazop.extract.adapters.pdf_vector`(설명글의 사전 위치 한 줄), `extract_drawio`, `extract_pdf` |
| `PYZ-01.pyz`(검증 실행 파일, 모듈 1027개, 전후 이름 같음) | 모듈 7개 | 위에서 `extract_pdf`를 빼고 `check_kg_algo`(표본 폴더 이름 한 줄), `check_kg_screen`(샘플 도면 찾는 자리)을 더한 것 |
| `base_library.zip` | 항목 155개의 CRC·이름·시각 모두 같음 | 빌드 흔들림(위 절) |

다른 모듈은 모두 이번 단계가 고친 파일이고, 고친 줄은 대응표의 이름을 적은 줄이다. 대응표 밖의 차이는 0으로 판단했다. 작업지시서의 기준은 "묶음 안 경로는 대응표대로 바뀐다"였는데, 묶음에 들어가는 스크립트 두 개도 내용이 바뀐 점은 그 문구에 없던 것이라 따로 적는다. 샘플 폴더 이름이 그 스크립트에 문자열로 적혀 있어서 피할 수 없었다.

묶인 실행 파일이 새 자리의 기준 자료를 읽는다는 것은 후 빌드의 `verify_bundle.py`(`w4_flow.py` 단계)가 확인했다. 표본 구간 JSON의 `inputs`는 여전히 `데이터/이탈후보/…` 같은 옛 경로를 적고 있고, 묶인 실행 파일은 그것을 `_internal/resources/library/…`의 파일로 풀어 해시를 맞춘다.

## 4. 실제 창 시나리오 S1~S6

`scripts/check_user_scenarios.py --only S1,S2,S3,S4,S5,S6`(스스로 데스크톱 잠금을 잡는다). 전후 모두 종료 코드 0, 여섯 개 모두 통과, 결함 0. 시험 장치의 실패는 없었다.

| 시나리오 | 전(클릭·키·전환·KLM) | 후 |
| --- | --- | --- |
| S1 | 0 · 14 · 5 · 13.4s | 같음 |
| S2 | 0 · 12 · 2 · 11.5s | 같음 |
| S3 | 1 · 8 · 1 · 13.8s | 같음 |
| S4 | 0 · 10 · 0 · 5.5s | 같음 |
| S5 | 3 · 69 · 4 · 32.9s | 3 · 83 · 4 · 36.8s |
| S6 | 1 · 17 · 1 · 13.6s | 같음 |

S5의 키 수가 14 늘었다. S5는 등록할 샘플 도면의 경로를 글자로 친다. 경로 가운데 '자원\참고자료\P&ID 도면 샘플'(18자)이 `resources\references\pid-samples`(32자)로 바뀌어 꼭 14자가 늘었다. 화면 동작이 달라진 것이 아니다.

## 5. 다시 해 보는 법

시험 폴더의 스크립트를 쓴다. 저장소에 둔 것은 `step5-codemod.py`, `step5-records-body-compare.py` 둘이다.

```
<venv python> capture_pins.py <저장소> <임시 작업 루트> resources/references/pid-samples resources/samples/regions/region-SNP-M-102-pzr.json resources/samples/fixed-responses/region-SNP-M-102-pzr <출력 txt>
<venv python> list_bundle.py <dist 폴더> <출력 csv>
<venv python> compare_bundle.py <저장소> before.csv after.csv
<venv python> compare_exe_parts.py <build-before> <build-after>
```
