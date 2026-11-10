# 단위 F1: 기호 사전·추출 재개 (2026-11-11)

계획은 `docs/2026-11-10-plan/pstack-advice.md`의 'F1 기호 사전·추출' 절에 있다. 이 폴더에는 하위 단위마다 남긴 근거를 둔다.

## F1-0: `pdf_vector.py` 나누기 (동작 그대로)

`hazop/extract/adapters/pdf_vector.py`(2,265줄)에서 기호 묶기, 라벨 고르기, 연결 표시를 각각 모듈로 뺐다. 세 모듈이 함께 쓰는 보조 함수는 넷째 모듈에 모았다. 함수·클래스·상수의 원문은 한 글자도 고치지 않고 옮겼다.

| 파일 | 줄 수 | 내용 |
| --- | --- | --- |
| `pdf_vector.py` | 1,511 | PDF 읽기, 원시 요소 분류, 선 위 빗금·점, 연결, 종류, 합치기, 조립(`build_extraction`), `extract` |
| `pdf_vector_common.py` | 196 | 상자·선분 기하, 몸체 모양 판별, 묶음 찾기(`_uf_groups`), `_issue` |
| `pdf_vector_grouping.py` | 424 | 기호 묶기(`_Sym`, `_group_symbols`, `_plate_assemblies`, `_merge_appendages` 등) |
| `pdf_vector_connectors.py` | 60 | 연결 표시 글자 정규식과 `_continuation_attributes` |
| `pdf_vector_labels.py` | 138 | `_text_blocks`, `_upright_blocks`, `_assign_tags` 등 |

옮긴 이름 40개는 `pdf_vector`가 모두 다시 내보낸다. 그래서 `pdf_vector._is_chevron`처럼 예전 경로로 쓰던 코드와 시험은 그대로 돈다.

### 근거 파일 (`evidence/`)

| 파일 | 내용 |
| --- | --- |
| `f1-0-callers.py`, `f1-0-callers.csv` | 나누기 전에 센 호출자. `pdf_vector`의 이름을 밖에서 쓰는 곳 108곳(파일 20개, 이름 20개) @072d5c0 |
| `f1-0-split.py` | 나누는 스크립트(`apply`)와 검사(`check`). 검사는 기준 커밋의 최상위 문장 99개가 다섯 파일에 글자 그대로 한 번씩 있는지, 예전 이름이 `pdf_vector`에서 모두 보이는지, 빠뜨린 import가 없는지 본다 |
| `f1-0-extract-compare.py` | 추출 결과를 전후로 견주는 스크립트(`snp`, `apr1400`, `compare`) |
| `f1-0-before-snp-hashes.json` | 나누기 전 SNP 샘플 6장(drawio·pdf 12건)의 추출 JSON·그래프 JSON 해시와 `graph_version` @072d5c0 |
| `f1-0-before-apr1400-hashes.json` | 나누기 전 APR1400 143쪽의 쪽별 추출·그래프 해시와 `graph_version` @072d5c0 |
| `f1-0-before-apr1400-pages.csv` | 나누기 전 `check_apr1400.py --out`의 쪽별 결과(걸린 시간 열 제외) @072d5c0 |
| `f1-0-compare-output.txt` | 전후 대조 명령과 출력 |

추출 JSON 원문 같은 큰 산출물은 저장소 밖 시험 폴더 `D:\HAZOP-trials\2026-11-11-unit-f1\`에 있다(`keep_until: 2026-11-25`).

### 다시 돌리는 법

시험용 venv의 `python.exe`로 저장소 루트에서 돌린다(`PYTHONIOENCODING=utf-8`).

```
python docs/2026-11-11-unit-f1/evidence/f1-0-split.py check
python docs/2026-11-11-unit-f1/evidence/f1-0-extract-compare.py snp --out <시험 폴더>/after
python docs/2026-11-11-unit-f1/evidence/f1-0-extract-compare.py apr1400 --out <시험 폴더>/after
python scripts/check_apr1400.py --out <시험 폴더>/after/apr1400_pages.csv
python docs/2026-11-11-unit-f1/evidence/f1-0-extract-compare.py compare <시험 폴더>/before <시험 폴더>/after --csv <전 CSV> <후 CSV>
```

`before` 폴더를 다시 만들려면 `072d5c0`을 꺼낸 작업 폴더에서 같은 명령을 돌린다. 이 PC는 `core.autocrlf=true`라, 줄 끝이 CRLF로 풀린 사본에서는 기호 사전 판 해시가 달라 보인다. 판 대조는 주 체크아웃에서 한다.

### F1-0 뒤에 고친 것 (검토 지적 경미 둘)

- `pdf_vector.TAG_RE`가 다시 보인다. 나누기 전에는 `from hazop.kg.docextract import TAG_RE`가 `pdf_vector.py`에 있어 그 이름이 `pdf_vector`에서도 보였는데, 나누면서 그 줄이 `pdf_vector_labels.py`로만 갔다. 원래 줄을 `pdf_vector.py`에 되돌렸다. 저장소 안에서 `pdf_vector.TAG_RE`를 쓰는 곳은 없다(`git grep`).
- `f1-0-split.py check`가 이것을 못 잡았다. 최상위 문장(함수·클래스·대입)이 만든 이름만 봤기 때문이다. 이제 기준 커밋의 모듈 수준 import로 들어온 이름까지 본다. `072d5c0`의 `pdf_vector`를 따로 읽어 `dir()`을 견준 결과도 같았다(빠진 이름은 `TAG_RE` 하나, 더해진 이름 없음).
- `f1-0-compare-output.txt` 맨 위에 실행 조건을 적었다. F1-0 세션이 남긴 것과 총괄이 `ddb4c46`에서 따로 잰 값을 출처별로 나눴다.

고친 뒤 출력(작업 폴더: `ddb4c46` + 이 수정, 인터프리터는 시험용 venv):

```
$ python docs/2026-11-11-unit-f1/evidence/f1-0-split.py check
최상위 문장 99개 중 글자 그대로 옮겨진 것 99개
pdf_vector에서 보이는 예전 이름 99/99, 옮긴 이름 40개 중 같은 객체 40개
기준 커밋에서 모듈 수준으로 보이던 이름(import 포함) 111개 중 지금도 보이는 것 111개
결과: 통과
```

고치기 전(`ddb4c46`)에 넓힌 검사를 돌리면 `문제: pdf_vector에서 안 보이는 이름(import로 들어왔던 것): TAG_RE`가 나온다. SNP 12건의 추출 JSON·그래프 JSON은 이 수정 뒤에도 `f1-0-before-snp-hashes.json`과 바이트로 같다(24개 중 24개).

이 검사는 F1-0의 내용(`ddb4c46`과 이 수정)에만 맞는다. F1-1이 `_shape_kind`와 `EQUIPMENT_WORDS`를 지운 뒤에는 '빠진 문장'으로 걸리는 것이 맞다.
