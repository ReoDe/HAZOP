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

## F1-1: 형상 규칙과 장비 이름 낱말을 기호 사전으로 (S7)

`pdf_vector.py`의 `_shape_kind`와 `EQUIPMENT_WORDS`를 지우고, 그 규칙을 기호 사전 공통 묶음(`resources/library/symbols/common/`)의 항목으로 옮겼다. 추출 결과는 그대로다.

### 옮긴 방식

두 규칙은 격자 견본으로 옮기지 않았다. `_shape_kind`는 몸체 수와 배치, 선의 방향을 보는 조건이고 `EQUIPMENT_WORDS`는 글자 조건이다. 격자 거리로 바꾸면 크기·구성이 다른 기호마다 견본이 따로 있어야 하고, APR1400 143쪽의 결과가 그대로라는 보장이 없다(재 보지 않은 판단이다). 그래서 조건은 그대로 두고, 견본에 종류를 둘 더해 사전이 그 조건을 가리키게 했다(`hazop/extract/symbols.py`).

| 견본 `shape` | 요구하는 것 | 맞히는 함수 |
| --- | --- | --- |
| `structure` | `requires`: 구조 특징 이름들(모두 있어야 함), `order`, `basis`(노드 근거에 남는 글자) | `Library.shape_rule(특징 집합)` |
| `label_words` | `words`: 라벨에 모두 있어야 하는 영문 대문자 낱말, `order` | `Library.word_rule(낱말 목록)` |

- 여럿이 맞으면 `order`가 가장 작은 견본이 이긴다. 옮기기 전 코드의 `if` 순서와 표의 순서가 그대로 `order`다. 같은 `order`가 둘이면 사전을 읽을 때 오류로 멈춘다.
- 구조 특징 이름과 뜻은 `symbols.STRUCTURE_FEATURES`에 있다(12개). 사전이 여기 없는 이름을 요구하면 읽을 때 오류로 멈춘다.
- 이 견본들은 격자 매칭(`Library.match`)에 끼지 않는다. 그래서 기존 격자 항목의 판정은 그대로다.
- 코드에 남은 것은 기호 하나의 구조 특징을 판정하는 `_shape_features`다(삼각형 둘인지, 사선이 스프링인지 같은 기하 판정). 어느 특징이 어느 종류인지와 보는 순서는 사전에만 있다.
- 근거 글자(`classification_basis`)는 옮기기 전과 같다(`valve_body`, `text_word:PUMP` 등). 구조 규칙으로 정한 노드에는 `evidence.symbol_id`를 남기지 않는다. 남기면 거의 모든 PDF 도면의 `graph_version`이 바뀐다.

### 사전 항목 (공통 묶음에 19개 추가, 모두 `revision` 1)

| 항목 | kind | 견본 (`order`: 요구 → 근거) |
| --- | --- | --- |
| `common.manual_valve_body` | `manual_valve` | 10: `plate_valve:butterfly` → `plates+butterfly` / 11: `plate_valve:ball` → `plates+ball` / 40: `bowtie` → `valve_body` |
| `common.motor_operated_valve_body` | `motor_operated_valve` | 20: `bowtie`+`outside_circle` → `valve_body+circle_actuator` |
| `common.control_valve_body` | `control_valve` | 30: `bowtie`+`outside_body` → `valve_body+diaphragm_actuator` |
| `common.psv_body` | `psv` | 50: `body_with_springs` → `body+spring` |
| `common.check_valve_lines` | `check_valve` | 60: `stroke_only`+`markers` → `lines+marker` |
| `common.orifice_plates` | `orifice` | 70: `parallel_plates` → `parallel_plates` |
| `common.instrument_bubble` | 없음(`kind_from: isa_letters`) | 80: `single_circle` → `circle` / 90: `single_tombstone` → `tombstone` |
| `common.continuation_arrow` | `continuation` | 100: `chevrons` → `chevron_arrow` |
| `common.name_reactor_vessel` | `reactor_vessel` | 10: REACTOR+VESSEL |
| `common.name_steam_generator` | `steam_generator` | 20: STEAM+GENERATOR |
| `common.name_pressurizer` | `pressurizer` | 30: PRESSURIZER |
| `common.name_condenser` | `condenser` | 40: CONDENSER |
| `common.name_turbine` | `turbine` | 50: TURBINE |
| `common.name_demineralizer` | `demineralizer` | 60: DEMINERALIZER |
| `common.name_filter` | `filter` | 70: FILTER |
| `common.name_heat_exchanger` | `heat_exchanger` | 80: EXCHANGER / 90: HX / 100: COOLER |
| `common.name_pump` | `pump` | 110: PUMP |
| `common.name_tank` | `tank` | 120: TANK |
| `common.name_vent` | `vent` | 130: VENT / 140: ATM |

SNP 묶음은 만들지 않았다. 옮긴 규칙 가운데 합성 샘플에만 쓰이는 것이 없다.

### 코드에 남긴 것 (이 단위의 범위 밖)

- 구조 특징 판정(`_shape_features`)과 모양 판별 함수 넷(`pdf_vector_common.py`).
- 구동부 안 `M` 표기로 전동 밸브로 올리기, ISA 글자(`_instrument_kind`), TO/FROM 연결 표기(`CONTINUATION_RE`), 끝막음 뒤처리(`pipe_cap`). 이것들은 `_classify`에 그대로 있다.

### 달라진 것

- **사전 판.** `공통` 묶음의 판이 `f80b0f4d94a7`에서 `ac25f22101ce`로 바뀌었다(항목 파일 19개가 늘어서다). `APR1400` 묶음은 `2c997ba7e6ce` 그대로다. 항목 수는 21개(켜짐 17)에서 40개(켜짐 36)가 됐다. 출처는 `scripts/check_symbols.py` 출력이다(주 체크아웃, 시험용 venv, 전은 `4e55e62`, 후는 이 변경을 넣은 작업 폴더).
- **사전 판을 적어 둔 곳.** 저장소에서 두 값을 찾아봤는데(`git grep f80b0f4d94a7`, `2c997ba7e6ce`) 시험·검사·문서 어디에도 적혀 있지 않았다. 그래서 따라 고친 곳은 없다. `tests/test_symbols.py`는 `APR1400` 열쇠가 있는지만 본다. 기획서 §7.1의 '사전 데이터 21항목'은 1단계 때의 기록이라 그대로 둔다.
- **사전을 못 읽을 때.** 전에는 형상 규칙이 모든 기호를 정한 쪽이면 사전이 없어도 추출이 됐다. 이제는 기호가 하나라도 있으면 사전을 읽고, 없거나 깨졌으면 `SymbolLibraryError`로 멈춘다. 나비 모양 밸브 하나만 있는 쪽으로 확인했다(`4e55e62`: `manual_valve`, 이 변경 뒤: `SymbolLibraryError`). 기획서 §4.6의 '사전이 없거나 깨지면 오류로 멈춘다'와 같은 방향이다.
- **배포 묶음.** 자원 파일이 19개 늘었다.

### 전후 대조 (명령과 출력은 `evidence/f1-1-compare-output.txt`)

실행 조건: 커밋 `4e55e62`에 이 단위의 코드·사전·시험 변경을 넣은 작업 폴더(커밋 전, 그 내용이 그대로 커밋됐다), 주 체크아웃, 시험용 venv, `--update` 없음.

| 대조 | 결과 |
| --- | --- |
| SNP 6장 추출 JSON·그래프 JSON(24개 파일)과 `graph_version` 12건 | 바이트 같음 24/24, 다른 것 0/12 (`f1-0-before-snp-hashes.json` 기준) |
| APR1400 143쪽 쪽별 추출·그래프 해시, `graph_version` | 다른 것 0/143 (`f1-0-before-apr1400-hashes.json` 기준) |
| APR1400 쪽별 결과 CSV(걸린 시간 열 제외) | 다른 행 0/143 (`f1-0-before-apr1400-pages.csv` 기준) |
| `check_apr1400.py` 143쪽 | 태그 정확 872/1619(원) · 텍스트 층에 없는 태그 47 · 연결 표기 검출 286/295 · 없는 대상 0 · 짝 279(정답 짝 6/6 · 틀린 짝 0 · 후보 10) · 미확인 63723, rc=0 |
| `check_snp_baseline.py` | 후퇴 0 · 나아짐 6 · drawio 짝 12 · 방향 모순 0 · 도면 drawio 6 · pdf 6 |
| `scripts/run_ci.py` | 시험 2074, 실패 0, 오류 0, 건너뜀 21, 검사 스크립트 10개 rc=0 |

시험 수는 `4e55e62`의 2064에서 10 늘었다(`tests/test_symbols.py`의 `RuleTemplateTest` 6건, `CommonRuleTest` 4건). `CommonRuleTest`는 옮기기 전 표를 기대값으로 두고, 낱말 17개(규칙에 나오는 16개와 무관한 낱말 하나)의 모든 조합(131,072가지)에서 옛 표와 같은 종류가 나오는지 본다.

### 커밋 뒤 확인 (`16c3536`, 작업트리 깨끗함, 시험용 venv)

| 확인 | 결과 |
| --- | --- |
| SNP 추출·그래프 JSON을 다시 만들어 `f1-0-before-snp-hashes.json`과 대조 | 바이트 같음 24/24, `graph_version` 다른 것 0/12 |
| `scripts/build_package.py --with-check --build` | rc=0. datas 78개(`ddb4c46`의 F1-0 빌드는 59개, 사전 항목 19개만큼 늘었다). 결과 폴더 검사·바이너리 검사 통과 |
| 묶음 안 사전 | `_internal/resources/library/symbols/common/`에 항목 파일 20개 |
| `packaging/verify_bundle.py`(`scripts/desktop_lease.py run` 안에서) | rc=0, '오류 없음, 결과 통과'. 묶음 파일 2,660개(F1-0 때 2,641개), `pdf_problems: []` |

로그는 시험 폴더 `D:\HAZOP-trials\2026-11-11-unit-f1\f1-1\`의 `build.log`, `verify.log`, `verify-out/`에 있다. 빌드 폴더는 확인 뒤 지웠다. 배포용(`--with-check` 없는) 빌드는 돌리지 않았다.

## F1-1 검토 지적 수정

검토에서 차단 하나와 경미 넷이 나왔다. 추출 결과는 그대로다.

### 차단: 코드보다 옛 판 사전을 읽으면 오류 없이 분류가 빠진다

F1-1 뒤의 코드는 밸브·계기·설비를 사전의 `structure`·`label_words` 견본으로만 정한다. 그 견본이 없는 사전(F1-1 이전 판)을 읽어도 형식은 맞으므로 멈추지 않았고, 구조 규칙과 이름 낱말 분류가 통째로 빠졌다.

- 재현(`evidence/f1-1-fix-old-dictionary-repro.txt`): `8b415bb`의 코드에 `HAZOP_RESOURCE_ROOT`를 `ddb4c46`의 사전으로 두고 SNP 샘플 PDF 6장을 추출하면 종료 코드 0, 6장 모두 passed인데 노드 종류가 `continuation` 26, 종류 없음 80, `pipe_cap` 2, `tee` 31뿐이다. 밸브·계기·설비가 하나도 없다.
- 고친 것: `Library.missing_rule_shapes()`가 켜진 견본이 하나도 없는 규칙 종류를 돌려주고, 추출기가 사전을 읽는 자리(`pdf_vector.symbol_library()`)에서 하나라도 비면 `SymbolLibraryError`로 멈춘다. 메시지는 어느 견본이 없는지, 사전 폴더, '코드보다 옛 판 사전'임을 알린다. 여러 쪽 추출(`extract_pdf.run_pages`)은 쪽을 처리하기 전에 사전을 읽으므로 이전 결과를 지우기 전에 멈춘다.
- 검사를 사전 읽기(`Library.load`)가 아니라 추출기 쪽에 둔 까닭: 견본이 꼭 있어야 하는 것은 추출기다. 묶기 도구(`scripts/symbols/cluster_unclassified.py`)와 사전 시험은 격자 견본만 든 사전도 읽는다.
- 같은 재현 뒤: 종료 코드 1, `SymbolLibraryError`, 출력 폴더는 생기지 않는다.
- 시험(`tests/test_symbols.py`의 `OldDictionaryTest` 4건): 저장소 사전 사본에서 규칙 견본이 든 항목을 빼 옛 꼴 사전을 만들고 추출이 멈추는지 본다(둘 다 없음, 구조만 없음, 낱말만 없음, 여러 쪽 추출이 이전 결과를 건드리지 않음). 고치기 전 코드에서 4건 모두 실패하는 것을 먼저 확인했다.

### 경미

| 지적 | 처리 |
| --- | --- |
| 기획서가 새 구조와 어긋남 | `specs/pid-symbol-dictionary.md`에 문장을 더했다. §1(표 아래), §3.1 폴더 그림의 `common/`·`SNP/` 줄, §3.2(견본 종류 넷과 `order`·`requires`·`basis` 규칙), §4.2 2·5번, §4.4(`symbol_id` 예외와 이유), §7 표 아래, §7.1 구현 기록. §8 결정 행과 '결정 상태' 표의 글자는 그대로다. `status`는 `draft` 그대로다. 이 기획서는 고정 해시에 걸려 있지 않다(`GUIDE_SHA256`은 `specs/hazop-method-guide.md`의 것이다) |
| 구조 견본의 `basis`가 겹치면 출처 항목을 되짚을 수 없음 | 켜진 `structure` 견본의 `basis`가 겹치면 사전을 읽을 때 `SymbolLibraryError`로 멈춘다. 시험 `RuleTemplateTest.test_same_basis_twice_fails_loudly`(다른 항목끼리, 한 항목 안, 꺼진 항목은 세지 않음). 지금 사전의 `basis` 11개는 서로 다르다 |
| 구조 판정과 옛 코드의 일치를 한 경우만 봄 | `OldShapeBranchTest.test_every_old_branch`가 옛 `_shape_kind`의 가지마다 기호를 하나씩 만들어(16가지: 판 2종, 전동, 제어, 나비 몸통 둘, 안전밸브와 그 반례, 체크밸브, 오리피스 둘과 반례, 원, 비석, 화살표, 해당 없음) 추출기와 사전이 함께 내는 (종류, 근거)를 본다. 기대값은 `ddb4c46`의 return 값을 글자로 적었다 |
| 묶음 검사가 사전을 보지 않음 | `packaging/verify_bundle.py`에 `symbols_problems`를 더했다. 묶음 안 사전이 읽히고 두 규칙 견본이 모두 있는지 보고, 문제가 있으면 결과가 실패다. 시험 `tests/test_packaging.py`의 `BundleSymbolsTest` |
| `.gitattributes`에 사전 폴더가 없음 | 따로 커밋했다(아래 절) |

### 전후 대조 (명령과 출력은 `evidence/f1-1-fix-compare-output.txt`)

실행 조건: `8b415bb`에 이 수정을 넣은 작업 폴더(커밋 전, `git diff HEAD` sha256 앞 16자 `4245642987173510`, 그 내용이 그대로 커밋됐다), 주 체크아웃, 시험용 venv, `--update` 없음.

| 대조 | 결과 |
| --- | --- |
| SNP 6장 추출 JSON·그래프 JSON(24개 파일)과 `graph_version` 12건 | 바이트 같음 24/24, 다른 것 0/12 (`f1-0-before-snp-hashes.json` 기준) |
| APR1400 143쪽 쪽별 추출·그래프 해시, `graph_version` | 다른 것 0/143 |
| APR1400 쪽별 결과 CSV(걸린 시간 열 제외) | 다른 행 0/143 |
| `check_apr1400.py` 143쪽 | 태그 정확 872/1619(원) · 텍스트 층에 없는 태그 47 · 연결 표기 검출 286/295 · 없는 대상 0 · 짝 279(정답 짝 6/6 · 틀린 짝 0 · 후보 10) · 미확인 63723, rc=0 |
| `check_snp_baseline.py` | 후퇴 0 · 나아짐 6 · drawio 짝 12 · 방향 모순 0 · 도면 drawio 6 · pdf 6 |
| 사전 판(`check_symbols.py` 첫 줄) | APR1400 `2c997ba7e6ce`, 공통 `ac25f22101ce`, 항목 40(켜짐 36). 그대로다 |
| `scripts/run_ci.py` | 시험 2082, 실패 0, 오류 0, 건너뜀 20, 검사 스크립트 10개 rc=0 |

시험 수는 `8b415bb`의 2074에서 8 늘었다(`tests/test_symbols.py` 7건, `tests/test_packaging.py` 1건).

### 사전 폴더의 줄 끝 (`9d51869`)

`.gitattributes`에 `resources/library/symbols/** -text`를 더했다. 사전 판은 사전 파일 바이트의 해시라, `core.autocrlf=true`인 PC에서 새로 뽑은 사본의 JSON이 CRLF로 풀리면 같은 사전이 다른 판으로 나온다. F1-2가 판을 추출 결과 옆에 적기 전에 막았다. 확인한 것은 다음과 같다(`evidence/f1-1-fix-gitattributes.txt`).

- 색인에 든 바이트는 바뀌지 않는다. 규칙을 더하고 `git add --renormalize`를 해도 `git status`에 사전 파일이 나오지 않는다.
- 주 체크아웃의 사전 판은 그대로다(APR1400 `2c997ba7e6ce`, 공통 `ac25f22101ce`).
- `9d51869`를 `core.autocrlf=true`로 새로 뽑은 분리 작업트리에서도 같은 판이 나온다. 그 사본에서 다른 파일(`hazop/extract/symbols.py`)은 CRLF로 풀렸고 사전 JSON 41개는 LF로 풀렸다. 작업트리는 확인 뒤 지웠다.
- 그림(`.png`) 21개는 규칙을 더하기 전에도 git이 내용으로 바이너리라고 판정해 줄 끝을 바꾸지 않았다(`i/-text w/-text`). 이제는 속성으로도 `text: unset`이다.

## F1-2: 사전 판을 추출 결과 폴더에 남긴다 (D8)

기획서 D8은 사전 판을 '등록 기록의 실행 정보'에 둔다고 적었는데, 그 자리가 코드에 없었다. 총괄이 추출 결과 폴더의 곁 파일로 정했다(2026-11-11). 기획서에는 `specs/pid-symbol-dictionary.md` §8 표 아래 'D8의 실제 저장 자리'로 적었다(결정 행의 글자는 그대로다).

### 정한 것

| 항목 | 결정 |
| --- | --- |
| 자리 | 추출 결과 폴더(`<작업 루트>/output/extract/<이름>/`)의 `extraction_run.json`. 이름은 같은 폴더의 `not_extracted.json`에 맞췄다 |
| 쓰는 곳 | 추출 단계. `hazop/extract/runinfo.py`의 `write`를 `scripts/extract_pdf.py`·`extract_drawio.py`·`extract_raster.py`의 `run_one`이 `extraction.json`을 쓴 뒤에 부른다. PDF는 추출하지 못한 쪽(`not_extracted.json`)에도 쓴다 |
| 내용 | `extractor`(추출기 종류), `extracted`(추출했는지), `extraction_run_id`(추출하지 못했으면 `null`), `symbol_dictionary_versions`(묶음 이름 → 판), `written_at`(UTC), `schema_version`(`"1"`) |
| 사전을 쓰지 않는 추출기 | drawio는 파일을 남기되 `symbol_dictionary_versions`를 `null`로 둔다. 래스터는 `pdf_vector.build_extraction`으로 기호를 정하므로 사전 판을 적는다 |
| 다시 추출 | 덮어쓴다. `store_io.write_json`으로 원자적으로 쓴다 |
| 등록 없이 돌린 추출 | `output/adapter/pdf_vector/` 같은 폴더에도 같은 이름으로 남는다. 결과 폴더를 쓰는 함수가 같아서 따로 가르지 않았다 |
| 파일 이름을 둔 곳 | `runinfo.FILE_NAME` 한 곳. 폴더는 지금처럼 `paths.output_root`·`paths.safe_join`으로 연다. `extraction.json`·`not_extracted.json`도 `paths.py` 표에 없는 파일 이름이라 같은 관례를 따랐다 |
| 기록 경로 관례 | 해당 없음. 파일 안에 경로가 없다 |
| 화면·탐색기 표시 | 하지 않았다(후속) |

등록 기록에 두지 않은 까닭: 등록정보(`registrations/<자료 ID>/<버전>.json`)는 추출 전에 쓰고 끝난 버전은 고치지 않는다. 자료 목록(`registry.json`)은 등록 모듈만 쓴다. 그래프는 `extraction.json`만 읽으므로 곁 파일은 `graph_version`에 들어가지 않는다.

### 달라진 동작

- 추출 결과 폴더마다 파일이 하나 늘었다. 추출하지 못한 쪽 폴더에는 이제 `not_extracted.json`과 `extraction_run.json` 둘이 있다. 그 폴더의 파일 목록을 적어 둔 시험 두 줄(`tests/test_adapter.py`)을 맞췄다.
- `extract_pdf.run_one`은 쪽 폴더를 건드리기 전에 사전을 읽는다. 전에는 기호가 하나도 없는 쪽을 `run_one`으로 직접 추출하면 사전 없이도 됐다. `run_pages`(앱과 명령줄이 쓰는 길)는 전부터 사전을 먼저 읽었으므로 그 길은 그대로다.
- 래스터 추출도 기호가 없는 그림에서 사전을 읽게 됐다. OpenCV가 없어 실제 래스터 추출로는 돌려 보지 못했고, 대역 시험으로만 확인했다.

### 영향 확인

| 본 것 | 결과 |
| --- | --- |
| 단계 연쇄 검사(`hazop/contract/chain.py`) | 추출 폴더를 훑지 않는다. 그래프 사본의 `source.extraction_file`이 가리키는 `extraction.json`과 그래프 폴더의 `graph.json`·`entity_mapping.json`만 이름으로 연다. 영향 없음 |
| 근거 묶음 해시(`bundle_sha256`), 분석 묶음 내보내기(`hazop/analysis/bundle_export.py`) | 해시는 구간·그래프에서 만든 묶음 dict로 계산한다. 내보내기는 추출 폴더를 복사하지 않는다. 영향 없음. `tests.test_packaging`·`check_export`가 `run_ci.py`에서 통과했다 |
| `scripts/clean_outputs.py` | 대상이 `output/analysis`와 `output/knowledge-graph` 둘뿐이다. 추출 폴더는 보지 않는다 |
| 작업 루트 이전 도구(`hazop/workroot.py`) | 옛 이름 폴더 아래 파일을 이름과 상관없이 모두 옮긴다(`_walk`). 파일 이름 목록이 없어 새 파일도 같이 간다. `tests.test_workroot`·`test_workroot_app`·`test_workroot_review` 71건 통과 |
| `scripts/check_work_root_counts.py` | 폴더별 파일 수를 세어 같은 사본의 이전 전후를 견준다. 코드에 고정된 기대 수는 없다. 전후 사이에 다시 추출하면 추출 폴더의 파일 수가 폴더당 하나 늘어난 것으로 나온다. `docs/2026-11-10-naming-rules/evidence/step6-counts-before.json`은 지난 측정 기록이라 고치지 않았다 |
| 0.1.x 기록 경로 표(`OLD_OUTPUT_NAMES`) | 폴더 이름 표다. 새 폴더가 없고 새 파일 안에 경로가 없어 더할 줄이 없다 |
| 추출 폴더의 파일을 세거나 통째로 해시하는 다른 코드 | `hazop/app/data.py`(`list_extractions`, `_pdf_page_state`), `hazop/app/runctx.py`, `hazop/viewer/build.py`, `scripts/build_graph.py`, `check_extract.py`·`check_graph.py`·`check_viewer.py`·`check_register.py`를 읽었다. 모두 `extraction.json`, `not_extracted.json`, `validation_report.md`를 이름으로 찾는다. 통째로 해시하는 곳은 없었다(`git grep`으로 `listdir`·`os.walk`·`copytree` 가운데 추출 폴더에 닿는 곳을 봤다). `verify_bundle.py`의 저장소 `output/`·`store/` 전후 해시는 검증이 임시 작업 루트를 써서 걸리지 않는다 |

고정값(`tests/baselines/`, `PINNED_SHA256`, `bundle_sha256`, `GUIDE_SHA256`)은 손대지 않았다.

### 시험 (`tests/test_extraction_run.py` 9건)

구현 전에 먼저 쓰고, 모듈만 있고 추출 단계가 부르지 않는 상태에서 8건이 실패하는 것을 확인했다(나머지 한 건은 drawio 추출 JSON 바이트가 같은지 보는 것이라 그 상태에서도 통과한다).

- 추출 뒤 파일이 생기고 내용이 맞다(키 여섯, 추출기 종류, 실행 ID, 사전 판이 추출기가 읽은 사전의 것과 같음).
- 다시 추출하면 덮어쓴다(시각과 사전 판이 새 값, 임시 파일이 남지 않음).
- 추출하지 못한 쪽에도 남는다. 추출됨 → 못 함 → 다시 추출됨으로 바뀔 때마다 그 실행의 값이 된다.
- `extraction.json` 바이트와 `graph_version`이 곁 파일 유무와 무관하다(PDF, drawio).
- 곁 파일이 없는 옛 추출 폴더를 앱 목록(`data.list_extractions`)과 그래프 빌드가 그대로 읽는다.
- drawio는 사전 판이 `null`, 래스터는 사전 판을 적는다(대역).

### 전후 대조 (명령과 출력, 곁 파일 예는 `evidence/f1-2-compare-output.txt`)

실행 조건: `82f9e0e`에 이 변경을 넣은 작업 폴더(커밋 전, `git diff HEAD` sha256 앞 16자 `715ab7688a25ffb2`, 그 내용이 그대로 커밋됐다), 주 체크아웃, 시험용 venv, `--update` 없음.

| 대조 | 결과 |
| --- | --- |
| SNP 6장 추출 JSON·그래프 JSON(24개 파일)과 `graph_version` 12건 | 바이트 같음 24/24, 다른 것 0/12 (`f1-0-before-snp-hashes.json` 기준) |
| APR1400 143쪽 쪽별 추출·그래프 해시, `graph_version` | 다른 것 0/143 |
| APR1400 쪽별 결과 CSV(걸린 시간 열 제외) | 다른 행 0/143 |
| `check_apr1400.py` 143쪽 | 태그 정확 872/1619(원) · 텍스트 층에 없는 태그 47 · 연결 표기 검출 286/295 · 없는 대상 0 · 짝 279(정답 짝 6/6 · 틀린 짝 0 · 후보 10) · 미확인 63723, rc=0 |
| `check_snp_baseline.py` | 후퇴 0 · 나아짐 6 · drawio 짝 12 · 방향 모순 0 · 도면 drawio 6 · pdf 6 |
| 사전 판 | APR1400 `2c997ba7e6ce`, 공통 `ac25f22101ce`. 그대로다 |
| `scripts/run_ci.py` | 시험 2091, 실패 0, 오류 0, 건너뜀 20, 검사 스크립트 10개 rc=0 |

시험 수는 `82f9e0e`의 2082에서 9 늘었다(`tests/test_extraction_run.py`).

## F1-2 검토 지적 수정 (경미 셋)

추출 결과는 그대로다. 곁 파일(`extraction_run.json`)은 기록일 뿐인데, 그 파일 쓰기가 추출 결과를 망가뜨리는 길이 셋 있었다.

| 지적 | 고치기 전 | 고친 것 |
| --- | --- | --- |
| 곁 파일만 쓰지 못해도 정상 추출된 쪽이 '미추출'이 된다 | `run_pages`의 `except Exception`이 곁 파일 쓰기 실패(`PermissionError`)를 받아 `_skip`으로 넘겼고, `_skip`이 방금 쓴 `extraction.json`을 지웠다. 실패가 이어지면 `_skip` 안의 쓰기도 실패해 예외가 밖으로 나가 남은 쪽을 처리하지 못했다. 앱 경로에서는 옛 `graph.json` 정리(`hazop/app/data.py`의 `_extract_pdf_pages`)를 건너뛰었다 | 추출 단계는 `runinfo.record`로 쓴다. 쓰지 못하면(OSError) 추출 결과를 그대로 두고 경고를 로그(`hazop.extract.runinfo`)에 남기며, 명령줄 추출 요약에도 '경고: …' 줄로 찍는다. drawio·래스터 추출도 같다 |
| 래스터 추출이 사전을 `extraction.json`을 쓴 뒤에 읽는다 | 옛 판 사전이면 `extraction.json`은 남고 곁 파일 없이 멈췄다 | 사전을 결과를 쓰기 전에 읽는다. 읽지 못하면 아무것도 쓰지 않고 멈춘다 |
| 옛 판 사전 오류 문구의 경로 | 실제로 읽은 폴더가 아니라 오류를 낼 때 다시 계산한 `paths.folder("symbols")`였다 | `Library.load`가 읽은 폴더를 `Library.root`에 남기고, 문구에 그 값을 적는다 |

- 재현: 검토가 쓴 `D:\HAZOP-trials\2026-11-11-review-f1\r3\scripts\fail_modes.py`(곁 파일 이름에서만 `store_io.write_json`이 `PermissionError`를 내게 함)를 시험으로 옮겼다. `tests/test_extraction_run.py`에 6건, `tests/test_symbols.py`에 1건을 더했고, 고치기 전 코드에서 7건 모두 실패하는 것을 먼저 확인했다.
- 같은 재현 스크립트를 고친 코드에 돌린 출력(B: 쓰기 실패가 이어짐, B2: 한 번만 실패, B3: 명령줄, C: drawio)은 넷 모두 `extraction.json`과 `validation_report.md`가 남고 종료 코드 0이다. 고치기 전 출력은 검토 폴더의 `r3\fm`에 있다.
- 남긴 것: 곁 파일을 쓰지 못했는데 전에 쓴 곁 파일이 있으면 그 파일이 그대로 남는다. 그 안의 `extraction_run_id`가 지금 `extraction.json`과 달라 옛 기록임을 알 수 있다. 앱 화면에는 이 경고를 띄우지 않았다(로그에만 남는다).

실행 조건: `5ed8d3b`에 이 수정을 넣은 작업 폴더(커밋 전, 그 내용이 그대로 커밋됐다), 주 체크아웃, 시험용 venv, `--update` 없음. 도는 동안 다른 세션의 문서 커밋 둘(`92453b4`, `9091bce`)이 들어왔다. 코드와 시험은 건드리지 않은 커밋이다.

| 대조 | 결과 |
| --- | --- |
| SNP 6장 추출 JSON·그래프 JSON(24개 파일)과 해시 목록 | 바이트 같음 24/24, 해시 목록은 `f1-0-before-snp-hashes.json`과 바이트로 같다 |
| `scripts/run_ci.py` | 시험 2098, 실패 0, 오류 0, 건너뜀 20, 검사 스크립트 10개 rc=0 |

시험 수는 `5ed8d3b`의 2091에서 7 늘었다. APR1400 143쪽은 이 수정으로 다시 돌리지 않았다(추출기 판정 코드는 오류 문구 한 줄만 바뀌었다). F1-3의 출발점 측정이 이 커밋에서 돈다.
