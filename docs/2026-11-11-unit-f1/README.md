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

## F1-3: 검게 칠한 닫힌 밸브를 밸브 몸통으로 읽는다

APR1400은 정상 운전 중 닫힌 밸브의 몸통을 검게 칠한다(범례 1.7-1 1/4 'CLOSED DURING NORMAL OPERATION'). 추출기는 긴 변 7pt 이하인 검은 채움을 화살촉 같은 표식으로 보냈고, 표식 양쪽의 배관 끝을 한 선으로 이었다. 그래서 닫힌 밸브 자리에 밸브 노드 없이 열린 배관이 생겼다. 7pt보다 큰 검은 몸통은 기호가 됐지만 닫힘 표시가 없었다. 이 단위는 그 몸통을 `normal_position: NC`인 밸브로 읽는다(기획서 §4.2 1번, 결정 D5).

### 한 일

| 순서 | 내용 |
| --- | --- |
| 견본 모으는 도구 | `scripts/symbols/cluster_unclassified.py --black-fills`. 기호 대신 검은 채움 도형(표식, 검은 몸체, 점선 조각으로 분류된 둥근 점)을 맞닿은 것끼리 묶어 모양별로 세고 그림판을 만든다. 묶음과 서명은 추출기가 쓰는 함수(`pdf_vector._black_fills`, `_black_fill_groups`, `_black_fill_signature`)를 그대로 부른다. `add_symbols.py`에는 더하는 견본에 속성을 붙이는 `--set-attributes`를 넣었고, 기호에서 뽑은 출처 기록과 검은 채움에서 뽑은 출처 기록이 서로 덮어쓰지 않게 했다 |
| 정답지 | `tests/fixtures/apr1400/answer_key/`의 012쪽·062쪽에 `closed_valves`(몸통 전체를 검게 칠한 밸브 11개, 4개)와 `half_filled_valves`(반만 칠한 LT 밸브 8개, 닫힘이 아님)를 더했다. 그림을 300dpi로 렌더해 눈으로 읽었다. 063쪽은 저장소에 PDF 고정 자료가 없어 넣지 않았다. 사람 확인 전이다 |
| 시험 먼저 | `tests/test_apr1400_extract.py`의 `ClosedValves`: 정답의 닫힌 밸브 자리마다 NC 밸브 노드가 있고, 그 밖의 노드는 NC가 아니어야 한다. 구현 전에는 15개 가운데 0개가 NC였다 |
| 추출기 | `pdf_vector._promote_black_symbols`. 검은 채움 묶음이 사전의 검정 견본에 0.1칸 안으로 맞으면 몸통을 기호 몸체로 표시한다(seed). 표식이던 몸통은 몸체로 올라가 양쪽 배관이 밸브를 거쳐 이어진다 |
| 사전 | `apr1400.gate_valve`에 검정 견본 11개, `apr1400.globe_valve`에 23개(모두 `set_attributes: {"normal_position": "NC"}`, `max_distance: 0.1`). 글로브에 전부터 있던 검은 몸체 견본 2개도 같은 속성·문턱으로 맞췄다. 두 항목의 `revision`은 2다. APR1400 묶음의 판은 `2c997ba7e6ce`에서 `a73ac84f0384`로 바뀌었다 |

### 올린 몸통을 어떻게 다루나

- **묶음과 서명.** 곧은 변으로 된 채움은 검은 몸체(`solid`), 둥근 점은 표식(`markers`)으로 센다. 게이트는 채운 나비 하나(`solid: 1`)나 채운 삼각형 둘(`solid: 2`), 글로브는 거기에 가운데 점이 더해진 꼴이라 구성으로 갈린다. 가운데 점이 1.5pt보다 작으면 점선 조각으로 분류되는데, 이 점도 묶음에 넣고 표식으로 옮긴다(처음에는 빠뜨려서 글로브 95개가 게이트 견본에 맞은 뒤 기호 단계에서 종류를 잃었다).
- **다른 기호와 섞지 않는다.** 올린 몸통은 맞닿은 축소관·구동부 몸체와 한 기호로 묶지 않는다. '몸체 안으로 깊이 들어간 선' 규칙으로도 다른 기호에 합치지 않는다(115쪽에서 밸브가 복수기 큰 기호에 합쳐지고 그 여파로 LT 계기까지 삼켜지는 것을 보고 막았다). 같은 자리에 따로 그린 외곽선은 채움과 같은 도형으로 보고 뺀다(012쪽 418번).
- **종류는 사전이 정한다.** 삼각형 둘이어도 나비 구조 규칙에 넣지 않고, 라벨의 장비 낱말('TURBINE' 등)이나 끝막음 규칙도 쓰지 않는다. 올린 몸통에 맞닿은 기호(밸브에 붙여 그린 축소관)도 끝막음으로 읽지 않는다.
- **장식선이 붙은 몸통.** 몸통에 벨로스 같은 다른 선이 붙으면 묶인 기호 전체는 사전에 없다. 이때는 종류를 비우고(`missing_kind` 미확인) `normal_position: NC`만 남긴다. 근거는 `black_body:<항목 id>`다.
- **문턱.** 올리는 문턱 0.1칸은 견본의 `max_distance`와 따로 코드(`BLACK_SEED_DISTANCE`)에 둔다. `PARAMS`에 넣으면 추출 JSON의 `run.params`가 바뀌어 SNP 추출 바이트가 달라지므로 넣지 않았다.

### 문턱의 근거 (`evidence/f1-3-seed-distance.txt`)

검은 채움 묶음 11,322개(143쪽, `--black-fills --no-library --dist 0.1`)를 173가지 모양으로 묶고, 그림으로 확인해 게이트 4묶음과 글로브 10묶음에 라벨을 붙였다(`evidence/f1-3-black-labels.csv`, 그림 `evidence/f1-3-black-fill-clusters.png`). 견본의 문턱을 무시하고 검정 견본까지의 거리를 재면 다음과 같다(실행: `2ce16b9` + 이 변경, 주 체크아웃).

| 구분 | 수 | 가장 가까운 검정 견본까지 거리 |
| --- | --- | --- |
| 라벨 붙인 묶음의 구성원 | 902 | 최대 0.057칸 |
| 라벨 없는 묶음에서 문턱 안에 드는 것 | 1 | 0.092칸. 066쪽 V2018, 그림으로 보니 점선 위의 닫힌 글로브 밸브다 |
| 그다음 | 1 | 0.117칸. 068쪽 V2015, 같은 종류의 밸브지만 올리지 않는다 |
| 밸브가 아닌 것 가운데 가장 가까운 것 | - | 0.240칸(반만 칠한 LT 밸브), 0.254칸(건물 경계 표시 TGB▶◀AB), 0.43칸 이상(화살촉·연결 표시 끝·다이어프램 밸브) |

같은 143쪽에서 견본을 뽑아 잰 값이라, 다른 도면의 처음 보는 모양은 문턱 밖일 수 있다. 그때는 지금처럼 표식으로 남는다.

### 전후 대조 (`evidence/f1-3-compare-output.txt`)

실행 조건: '전'은 `2ce16b9`(작업트리 깨끗함), '후'는 `2ce16b9`에 이 변경을 넣은 작업 폴더(커밋 전, 그 내용이 그대로 커밋됐다). 주 체크아웃, 시험용 venv, `--update` 없음. 노드 대조의 '전' 추출은 `2ce16b9`를 꺼낸 분리 작업트리에서 만들었다.

| 지표 | 전 @2ce16b9 | 후 | 비고 |
| --- | --- | --- | --- |
| 태그 정확(`tag_exact`) | 872/1619 | 872/1619 | |
| 텍스트 층에 없는 태그 | 47 | 47 | |
| 연결 표기 검출(`connectors_detected`) | 286/295 | 287/295 | 006쪽. 큰 기호에 묻혀 있던 'CV:RDT / SHEET 5' 화살표가 따로 나왔다 |
| 없는 대상(`connector_bad_target`) | 0 | 0 | |
| 짝(`paired`), 정답 짝, 틀린 짝 | 279, 6/6, 0 | 279, 6/6, 0 | |
| 실패한 쪽 | 0 | 0 | |
| SNP 추출·그래프 JSON 24개, `graph_version` 12건 | - | 바이트 같음 24/24 | `f1-0-before-snp-hashes.json` 기준 |
| `check_snp_baseline.py` | 후퇴 0 | 후퇴 0 | |
| 노드 / 관계 | 23,086 / 23,045 | 23,326 / 23,222 | |
| NC가 붙은 밸브 노드(댐퍼 제외) | 0 | 872 | 같은 자리의 기존 노드 204, 새 노드 668. 101쪽에 걸쳐 있다 |

출발점 값은 총괄이 준 참고값(@16c3536, naming-migrate 세션 실행)과 같다.

NC 밸브 872개의 종류는 수동 650, 전동 67, 공기구동 25, 종류 없음 130이다. 종류 없음 가운데 75개는 구동부가 붙어 구동 방식을 정하지 못한 몸통(`actuated_valve_pending`)이고, 55개는 장식선이 붙은 몸통(`black_body`)이다. 배관 끝이 닿은 수는 0개 26, 1개 112, 2개 422, 3개 이상 362다(댐퍼 50개 포함 922개 기준).

#### 미확인 사유별 (전 → 후 @2ce16b9 + 이 변경)

| 사유 | 전 | 후 | 차 |
| --- | --- | --- | --- |
| `unknown_flow_direction` | 28,340 | 28,803 | +463 |
| `missing_tag` | 11,767 | 12,199 | +432 |
| `unconnected_endpoint` | 9,671 | 9,531 | −140 |
| `missing_kind` | 7,499 | 7,316 | −183 |
| `self_loop` | 5,640 | 5,668 | +28 |
| `not_registered` | 429 | 429 | 0 |
| `actuated_valve_pending` | 170 | 234 | +64 |
| `missing_drawing_number` | 143 | 143 | 0 |
| `duplicate_tag` | 56 | 56 | 0 |
| `dashed_path_no_visible_piece` | 8 | 8 | 0 |
| 합계 | 63,723 | 64,387 | +664 (+1.0%) |

미확인은 줄지 않고 늘었다. 닫힌 밸브 노드가 668개 생기면서 그 밸브의 태그 없음과, 밸브에서 나뉜 배관의 흐름 방향 미확인이 더해졌기 때문이다. 이 단위가 고친 것은 미확인 수가 아니라 '닫힌 밸브 자리가 열린 배관으로 이어지던 판정'이다. 멈춤 기준의 셈으로는 미확인을 줄이지 못했고, HIGHER 지표는 `connectors_detected` 하나가 1 올랐다(부수 효과다).

#### 종류가 바뀌거나 사라진 노드 (같은 자리 기준, `f1-3-node-diff.py compare`)

같은 자리 기호의 종류 변화는 107건, 새로 생긴 기호 노드는 766개, 없어진 기호 노드는 333개다. 없어진 노드 318개는 종류 없는 큰 묶음 기호가 밸브와 나머지로 나뉜 것이다. 종류가 있던 노드가 사라지거나 바뀐 것은 그림으로 하나씩 봤다.

| 변화 | 수 | 본 것 |
| --- | --- | --- |
| 없음 → 수동·전동·공기구동 밸브 | 68 | 검은 몸통이 맞닿은 축소관과 떨어지면서 밸브로 판정됐다 |
| 끝막음 → 없음 | 26 | 배관 끝의 검은 밸브를 끝막음으로 읽던 것이다. 지금은 종류 없음 + NC다 |
| `vent`·`turbine` → 수동 밸브 또는 없음 | 5 | 라벨의 장비 낱말로 정해졌던 검은 밸브다 |
| `control_valve` → `tank`(128쪽), `psv` → 없음(055쪽) | 2 | 쪽의 큰 부분을 덮는 묶음 기호였다. 128쪽은 'AUXILIARY FEEDWATER STORAGE TANK' 글자로 탱크가 됐다 |
| 없어진 `orifice` 5, `control_valve` 1, `check_valve` 1 | 7 | 오리피스 4개는 화살촉이 얹힌 배관·건물 경계 표시를 오리피스로 읽던 것이고 1개는 상자만 줄었다. 나머지도 상자가 줄었거나 검은 밸브가 따로 나온 것이다 |
| 없어진 수동 밸브 8, 새 수동 밸브(NC 아님) 10 | - | 품질 등급 마름모('BI\|AI')를 나비 규칙이 수동 밸브로 읽는 기존 오류다. 전에는 마름모 상자에 검은 밸브가 표식으로 들어 있었고, 지금은 진짜 밸브가 따로 나오고 마름모만 수동 밸브로 남는다. 128쪽·143쪽에서는 큰 기호에 묻혀 있던 마름모 2개가 새로 드러났다 |
| **지시계 → 없음 3, 없음 → `control_valve` 1 (132쪽)** | 4 | **이 변경으로 나빠진 곳이다.** 쪽 절반을 덮는 묶음 기호에서 검은 삼각형이 빠져나가자 남은 흰 삼각형 둘이 나비 규칙에 걸려 그 기호가 제어 밸브가 됐고, 밸브 상자 안 글자를 표기로 가져가는 규칙 때문에 TI·PI 원 3개가 글자를 잃었다. 태그는 원래 없었다 |
| 없음 → 끝막음 2 (001쪽) | 2 | 범례 쪽이다. 범례 그림의 작은 도형이 끝막음 규칙에 걸렸다 |
| 새 `reducer` 17, `drain` 3, `check_valve` 3, `continuation` 1, `pump` 1 | 25 | 큰 묶음에서 떨어져 나와 제 종류를 받았다 |

132쪽과 마름모의 원인은 같다. 나비 구조 규칙은 '삼각형 몸체가 정확히 둘'만 본다. 143쪽에서 이 규칙에 걸린 기호 589개를 세어 보니, 꼭짓점 하나를 맞댄 진짜 나비는 18개이고 479개는 변을 맞댄 마름모, 92개는 서로 떨어진 삼각형이었다(시험 폴더 `probe/bowtie_scan.py`, 실행: `2ce16b9` + 이 변경. SNP 6장은 12개 모두 꼭짓점을 맞댄 나비다). 이 단위 전부터 있던 오판이라 여기서는 고치지 않았다(아래 후속 1).

#### 사람 수정 기록 (`f1-3-node-diff.py carry`)

이 PC의 작업 루트에는 저장된 도면 수정 기록(`data/drawing-edits/`)이 없다. 그래서 실제 기록의 적용 수는 견줄 것이 없다. 대신 앞 단위들처럼 '전' 추출의 모든 기호 노드와 관계에 모의 수정을 하나씩 만들어 '후' 추출에 적용해 봤다.

| 대상 | 수정 | 적용 | 그 가운데 번호가 밀려 자리로 다시 찾음 | 적용 못 함 | 다른 자리에 적용 |
| --- | --- | --- | --- | --- | --- |
| 기호 노드 | 14,770 | 14,433 (97.7%) | 6,624 | 337 | 0 |
| 관계 | 23,045 | 21,791 (94.6%) | 10,768 | 1,254 | 0 |

적용하지 못한 것은 대상이 실제로 달라진 경우다. 노드 337개는 큰 묶음 기호가 나뉘거나 상자가 달라진 것이고(없어진 노드 333개와 맞는다), 관계 1,254개는 닫힌 밸브가 끼어들어 끝이나 자리가 달라졌거나, 같은 자리에 후보가 둘 이상이라 일부러 적용하지 않은 것이다. 새 밸브 노드가 생기면서 기호 번호가 밀려, 적용된 수정의 절반 가까이는 자리로 다시 찾은 것이다. 총괄이 준 멈춤 기준 '수정 기록 적용 수가 준다'를 글자 그대로 읽으면 모의 수정의 적용 수는 줄었다. 배관에 밸브 노드를 끼워 넣는 변경에서는 피할 수 없는 몫이라고 보고 되돌리지 않았다. 판단은 총괄에 넘긴다.

### 시험

- `tests/test_apr1400_extract.py`의 `ClosedValves` 6건: 정답 쪽 012·062에서 닫힌 밸브 15개가 모두 NC 밸브이고, 그 밖의 노드와 반만 칠한 밸브 8개는 NC가 아니다. 418번 밸브는 위아래 배관 사이에 서고, 그 아래 축소관은 끝막음이 아니다.
- `tests/test_symbols.py`의 `ClosedValveTest` 11건: 합성 도형으로 게이트·글로브·같은 자리 외곽선을 본다. 화살촉·건물 경계 표시·반만 칠한 밸브는 올리지 않는다. 맞닿은 축소관과 섞지 않고, 큰 기호에 삼켜지지 않고, 라벨 낱말로 이름이 바뀌지 않는다. 장식선이 붙으면 종류 없이 NC만 남고, 견본이 느슨해도 올리는 문턱은 넘지 않는다.
- `scripts/run_ci.py`: 시험 2115, 실패 0, 오류 0, 건너뜀 20, 검사 스크립트 10개 rc=0(`2ce16b9` + 이 변경, 커밋 전). 시험 수는 `2ce16b9`의 2098에서 17 늘었다.

### 커밋 뒤 확인

| 커밋 | 내용 |
| --- | --- |
| `c311c3a` | 정답지에 닫힌 밸브 목록(012쪽·062쪽) |
| `c65d90b` | 추출기·사전·도구·시험·문서 |
| `d963098` | 기준값 갱신. `c65d90b`에서 작업트리가 깨끗한 채로 `check_apr1400.py --update`를 돌렸다. 톱니 지표는 `connectors_detected`만 286 → 287로 바뀌었다 |

- `c65d90b`에서 다시 돌린 `check_apr1400.py` 143쪽의 쪽별 결과(걸린 시간 열 제외)는 커밋 전 실행과 같다(다른 행 0/143). 합계도 같다: 태그 정확 872/1619 · 연결 표기 검출 287/295 · 짝 279(정답 짝 6/6 · 틀린 짝 0) · 미확인 64,387.
- 기준값 파일의 참고값(노드 수, 종류 없음, 미확인)은 톱니에 쓰이지 않아 전에 갱신되지 않은 채였다(미확인 71,203은 3c 때 값). 이번 갱신으로 지금 값이 됐다.
- 노드 대조에 쓴 분리 작업트리(`wt-before`, `2ce16b9`)는 확인 뒤 `git worktree remove`로 지웠다. 추출 JSON과 로그는 시험 폴더 `D:\HAZOP-trials\2026-11-11-unit-f1b\`에 있다(`keep_until: 2026-11-25`).

### 남긴 것과 후속

1. **나비 구조 규칙이 마름모를 밸브로 읽는다(기존 오판, 차단급).** 위 표의 132쪽 4건과 마름모가 여기서 나온다. 규칙에 '두 삼각형이 꼭짓점 하나를 맞댄다'는 조건을 넣으면 APR1400에서 가짜 밸브 571개(마름모 479, 떨어진 삼각형 92)가 빠지고 SNP 12개는 그대로일 것으로 본다(세어 본 값에서 나온 예상이고, 고쳐서 돌려 보지는 않았다). 마름모 안 글자('BI', 'AI')가 풀려 다른 판정에 번질 수 있으니 따로 한 단위로 재야 한다.
2. **검게 칠한 다른 밸브.** 플러그(채운 마름모, 123개와 14개 묶음), 다이어프램(홈이 파인 사각형, 23개 묶음 등), 볼 밸브는 사전 항목이 없어 그대로 표식이거나 종류 없는 몸체다. 항목 추가 단위(F1-6)에서 흰 것과 함께 넣는다.
3. **장식선이 붙은 닫힌 밸브 55개**는 종류 없이 NC만 있다. 벨로스 밀봉(패킹리스) 밸브가 대부분이다. 흰 것도 사전에 없다.
4. **배관이 끊기지 않고 몸통 밑을 지나가는 닫힌 밸브.** NC 밸브 가운데 배관 끝이 하나도 닿지 않은 것이 26개다(범례 쪽 포함). 밸브 노드는 생기지만 배관은 전처럼 밸브를 건너 이어진다. 선을 몸통에서 나누는 일은 하지 않았다.
5. **글자 'NC'로만 닫힘을 나타낸 밸브**(버터플라이 등)는 다루지 않았다.
6. **라벨의 장비 낱말이 사전보다 앞선다.** 올린 몸통에는 적용하지 않게 했지만, 흰 밸브는 여전히 'PUMP' 같은 낱말이 가까우면 그 종류가 된다(기존 동작).
7. **범례 쪽(001~004).** 범례 그림의 도형도 밸브·끝막음으로 읽힌다. 범례 쪽을 추출에서 빼는 일은 이 단위 밖이다.
8. **정답지.** 063쪽은 PDF 고정 자료가 저장소에 없어 닫힌 밸브 목록을 넣지 않았다. 새 목록은 사람 확인 전이다.
9. **견본의 범위.** 견본은 143쪽 전체에서 뽑았다. 따로 떼어 둔 쪽으로 잰 일반화 값은 없다.

## F1-3 검토 지적 수정 (Codex 교차검증, 차단 여섯)

`c65d90b`를 Codex가 실제로 돌려 재현한 지적이다. 여섯 모두 '닫힌 밸브가 있는데 열린 길로 읽히는' 경로라 차단으로 판정됐다. 합성 도형과 실제 쪽으로 재현 시험을 먼저 쓰고 고쳤다. 위 F1-3 절의 '남긴 것과 후속' 1번(132쪽)과 4번(관통 배관)은 이 수정으로 달라졌다.

### 차단 지적과 고친 것

| | 지적 | 재현 | 고친 것 |
| --- | --- | --- | --- |
| 1 | 종류가 비고 NC만 있는 노드를 경로 분석이 밸브로 보지 않는다 | 검은 게이트 몸통에 장식선 둘과 양쪽 배관을 붙이면 `category`가 없고, 양옆 밸브 사이 경로가 `no_valves`, 정상 유로 `True`로 나왔다 | 몸통이 밸브인 것은 알지만 종류를 정하지 못한 노드는 `kind`만 비우고 `category`를 `valve`로 둔다. 장식선이 붙은 검은 몸통(`black_body`)과 구동 방식을 정하지 못한 몸통(`actuated_valve_pending`, 흰 몸통 포함)이 해당한다. `missing_kind`·보류 미확인과 `classification: unclassified`는 그대로다. 경로 분석(`hazop/analysis/explore.py`)은 `category`로 밸브를 가리므로 `closed_valve_on_path`, 정상 유로 `False`가 된다 |
| 2 | 같은 노드가 검토구간 나누기의 밸브 집계와 편차원에서 빠진다 | `segment.part_of`가 `Part.PLAIN`(점수 0)이었다 | 1번과 같은 뿌리다. `Part.VALVE`가 된다. 하류 코드는 고치지 않았다 |
| 3 | 몸통 밑을 끊지 않고 그린 배관이 NC 밸브를 건너 이어진다 | 검은 몸통 위로 연속선 하나를 지나가게 하면 양 끝 밸브가 직접 이어지고 가운데 NC가 고립됐다 | 올린 몸통의 긴 축 방향으로 몸통을 끊기지 않고 지나가는 실선을 몸통 양 끝에서 나눈다(`_cut_at_boxes`). 기호를 묶기 전에 나눈다. 뒤에 나누면 큰 기호 상자 안을 지나는 선이 그 기호의 내부선으로 먼저 흡수된다(128쪽). 옆으로 가로지르는 선은 나누지 않는다. 점선은 몸통 안에 든 조각을 빼서 사슬이 몸통에서 끊기게 한다. 선 끝이 올린 몸통에 닿았는데 그 몸통이 큰 묶음 기호의 상자 안에 있으면, 큰 기호가 아니라 그 밸브에 붙인다(023쪽) |
| 4 | 마지막 부속 합치기가 올린 몸통을 큰 기호에 합쳐 NC가 사라진다 | 검은 몸통을 큰 외곽 사각형 안에 겹치고 배관을 빼면 NC 노드가 없어졌다 | 올린 몸통은 배관이 닿지 않아도 옆 기호의 부속으로 합치지 않고, 다른 기호를 부속으로 받지도 않는다 |
| 5 | 몸통을 네 조각으로 나눠 칠하면 조각마다 점선 조각이 되어 견본에 대 보지 않고, 배관이 끊긴 채 남는다 | 재현됐다 | 고치지 않았다. APR1400 143쪽에서 곧은 채움 점선 조각까지 넣어 묶어 본 결과 검정 견본에 맞는 묶음은 0개다(시험 폴더 `probe/variants_scan.py`). 지금 동작(밸브로 읽지 못하고, 그 자리를 건너 배관을 잇지도 않는다)을 시험으로 고정했다 |
| 6 | 132쪽에서 지시계 3개가 종류를 잃고 큰 묶음 기호가 제어 밸브가 된다 | 실제 쪽으로 재현했다 | 부모(`2ce16b9`)에서는 그 큰 기호에 삼각형이 셋이라 나비 규칙에 걸리지 않았다. 검은 삼각형 하나가 빠진 뒤 240pt 떨어진 삼각형 둘이 '나비 몸통'으로 읽혔다. 나비 구조 특징에 '두 삼각형 사이 간격이 삼각형 긴 변 이하'라는 조건을 넣었다. 132쪽은 부모와 같은 판정으로 돌아왔다(지시계 3개, 큰 기호는 종류 없음) |

### 6번 조건이 다른 쪽에 미친 것

간격 조건은 132쪽만이 아니라 같은 꼴의 기존 오판에도 걸린다. 143쪽에서 나비 규칙에 걸린 기호 589개의 '간격 ÷ 삼각형 긴 변'을 재면 568개가 0(붙어 있음), 5개가 0.61 이하(글로브·볼의 점이 낀 진짜 밸브), 16개가 2.36 이상이다(시험 폴더 `probe/bowtie_scan.py`, 실행: `68c468d`). 그 16개가 종류를 잃었다.

| 쪽 | 부모의 종류 | 수 | 무엇이었나 |
| --- | --- | --- | --- |
| 132 | 없음(c65d90b에서 제어 밸브) | 1 | 6번 |
| 010 | 제어 밸브 | 2 | 정지냉각 열교환기 2대. 화살촉 삼각형 둘이 43pt 떨어져 있다(그림으로 확인) |
| 098 | 전동 밸브 | 1 | 수처리 설비 상자. 연결 표시 깃발 끝의 삼각형 둘이 107pt 떨어져 있다(그림으로 확인) |
| 103 | 제어 밸브 | 1 | 연결 표시 깃발과 배관. 46pt(그림으로 확인) |
| 045 | 제어 밸브 | 3 | 도형 678개가 묶인 큰 기호 |
| 072, 083 | 제어 밸브 | 2씩 | 도형 86개·92개 묶음 안의 0.2pt짜리 삼각형 둘 |
| 081 | 제어 밸브 | 1 | 도형 85개 묶음 안의 0.2pt짜리 삼각형 둘 |
| 002, 004 | 전동 밸브 | 1씩 | 범례 쪽 전체를 덮는 묶음 기호(도형 601개, 316개) |
| 073 | 전동 밸브 | 1 | 도형 132개 묶음, 628pt 떨어진 삼각형 |

부모에 종류가 있던 15개는 붙어 있지 않은 삼각형 둘을 밸브 몸통으로 읽던 것이다. 작은 묶음 4개(010 둘, 098, 103)는 그림으로 보고 밸브가 아님을 확인했다. 나머지 11개는 도형 85개 이상이 묶인 큰 기호라 간격 수치와 묶음 크기로만 판단했다. 변을 맞댄 마름모 479개를 밸브로 읽는 문제는 이 조건으로 풀리지 않는다. 여전히 후속이다.

'부모(`2ce16b9`)에 종류가 있던 기호가 같은 자리에서 종류를 잃거나 다른 종류가 된 수'는 143쪽 전체에서 다음과 같다(`f1-3-node-diff.py compare`).

| | c65d90b | 고친 뒤 | 고친 뒤의 내역 |
| --- | --- | --- | --- |
| 같은 자리에서 종류를 잃음 | 32 | 44 | 끝막음 → 없음 26(배관 끝의 닫힌 밸브를 끝막음으로 읽던 것. 지금은 분류 밸브 + NC), 제어 밸브 → 없음 11과 전동 밸브 → 없음 4(위 표), `turbine` → 없음 2(라벨 낱말로 터빈이 됐던 닫힌 밸브. 분류 밸브 + NC), `psv` → 없음 1(055쪽 큰 묶음) |
| 다른 종류가 됨 | 4 | 3 | `vent` → 수동 밸브 2, `turbine` → 수동 밸브 1(라벨 낱말로 정해졌던 닫힌 밸브) |
| 같은 자리에 없음 | 15 | 17 | 수동 밸브 8(마름모와 검은 밸브가 한 상자였던 것이 나뉨), 오리피스 5, 제어 밸브 3, 체크 밸브 1. 상자가 달라졌거나 큰 묶음이 나뉜 것이다 |

c65d90b에 있던 '지시계 → 없음 3'과 '없음 → 제어 밸브 1'(132쪽)은 없어졌다. 범례 쪽에서 종류 없음이 끝막음이 된 것은 5건이다(001쪽 2, 002쪽 3). 002쪽 3건은 쪽 전체를 덮던 '전동 밸브' 묶음이 종류를 잃으면서 그 안의 작은 도형이 끝막음 규칙에 걸린 것이다.

### 3번: 배관이 닿지 않는 닫힌 밸브

NC 밸브 노드에 닿은 물리 배관 끝의 수다(`f1-3-node-diff.py compare`, 댐퍼 제외).

| | c65d90b | 고친 뒤 |
| --- | --- | --- |
| NC 밸브 노드 | 872 | 903 |
| 배관 끝 0개 | 34 | 29 |
| 배관 끝 1개 | 79 | 24 |
| 배관 끝 2개 이상 | 759 | 850 |

- NC 노드가 31개 늘었다. c65d90b에서는 배관이 닿지 않은 올린 몸통이 옆 기호의 부속으로 합쳐져 사라졌다(4번). 063쪽 V350·V716·V715가 그 예다.
- 위 F1-3 절에 적은 '0개 26'은 댐퍼를 넣고 관계 종류를 가리지 않고 센 값이다. 여기서는 물리 배관만 센다.
- 남은 29개 가운데 실선이 몸통 밑을 지나가는 경우는 없다. 내역은 범례 쪽 001의 4개, 점선 위의 밸브 24개(008쪽 7개는 점선 관계가 닿아 있고, 141쪽 17개는 관계가 하나도 없다), 029쪽 1개(올린 몸통이 장식선 288개를 흡수한 큰 기호가 됨)다.
- 141쪽의 17개는 이 수정으로 풀지 못했다. 그 쪽의 공정 배관은 점선으로 그려져 있는데, 추출기는 점선을 신호선으로 다루고 점선 사슬은 양 끝이 서로 다른 기호에 붙을 때만 관계가 된다. 점선 분기를 다루지 않는 기존 한계다.

### 경미 지적

| 지적 | 처리 |
| --- | --- |
| 마주 보는 화살촉 둘이 거리 0으로 NC가 된다 | 밸브와 같은 크기·비율로 꼭짓점을 맞댄 삼각형 둘은 모양으로 가를 수 없다. 143쪽에서 삼각형 둘로만 된 묶음은 19개(055쪽 13, 052쪽 4, 127쪽 2)이고 그림으로 보니 모두 밸브였다. 조건을 더하지 않았고, 이 동작을 시험으로 적어 두었다. 가는 화살촉(건물 경계 표시)은 전처럼 올리지 않는다 |
| 45° 돌린 검은 몸통을 놓친다 | 143쪽에서 견본에 맞지 않은 묶음을 ±45° 돌려 다시 대 보니 맞는 것이 0개였다. 고치지 않았다 |
| 실제 쪽 시험이 위치 근처의 NC만 본다 | `ClosedValves`에 일대일 대응·분류(밸브)·모든 닫힌 밸브의 배관 끝 2개 이상을 더했다. 132쪽은 `LargeSymbolRegression`으로 넣었다. 132쪽 PDF는 저장소에 없는 자료라, 쪽별 PDF 폴더가 없는 곳(GitHub CI)에서는 건너뛴다 |
| 도구의 캐시 지문에 묶기 모듈이 빠졌다 | `cluster_unclassified.py`의 지문에 `pdf_vector_common`·`pdf_vector_grouping`을 넣었다 |
| `add_symbols.py`가 속성만 다른 같은 견본을 조용히 건너뛴다 | 건너뛸 때 '같은 격자의 견본이 이미 있고 속성이 다름' 경고를 찍는다. 이번에 손으로 고친 글로브 견본 2개의 NC 속성은 `ClosedValves`의 큰 검은 글로브(012쪽 10개)가 확인한다 |
| 앱 경로가 곁 파일 경고를 전달하지 않고, 옛 곁 파일이 남는다 | `data.extract_and_graph`가 `warnings`를 돌려주고 ① 등록 화면이 추출 결과에 그 문구를 보여 준다. 쓰기에 실패하면 지난 실행의 곁 파일을 지운다. 지우지도 못하면 경고에 그 사실을 적는다 |

### 다시 잰 값 (`evidence/f1-3-fix-compare-output.txt`)

실행 조건: 주 체크아웃, 시험용 venv, `--update` 없음. '고친 뒤'는 `68c468d`에 이 수정을 넣은 작업 폴더(커밋 전, 그 내용이 그대로 커밋됐다)다.

| 지표 | 시작 @2ce16b9 | @c65d90b | 고친 뒤 |
| --- | --- | --- | --- |
| 태그 정확 | 872/1619 | 872/1619 | 872/1619 |
| 텍스트 층에 없는 태그 | 47 | 47 | 47 |
| 연결 표기 검출 | 286/295 | 287/295 | 287/295 |
| 없는 대상 | 0 | 0 | 0 |
| 짝 (정답 짝, 틀린 짝) | 279 (6/6, 0) | 279 (6/6, 0) | 281 (6/6, 0) |
| SNP 추출·그래프 JSON 24개 | - | 바이트 같음 | 바이트 같음 24/24 |
| `check_snp_baseline.py` | 후퇴 0 | 후퇴 0 | 후퇴 0 |
| 노드 / 관계 | 23,086 / 23,045 | 23,326 / 23,222 | 23,346 / 23,328 |
| NC 밸브 노드(댐퍼 제외) | 0 | 872 | 903 |
| 그 가운데 종류 없이 분류만 밸브 | - | 0(130개가 분류도 없었다) | 130 |

| 미확인 사유 | 시작 @2ce16b9 | @c65d90b | 고친 뒤 |
| --- | --- | --- | --- |
| `unknown_flow_direction` | 28,340 | 28,803 | 28,859 |
| `missing_tag` | 11,767 | 12,199 | 12,219 |
| `unconnected_endpoint` | 9,671 | 9,531 | 9,537 |
| `missing_kind` | 7,499 | 7,316 | 7,314 |
| `self_loop` | 5,640 | 5,668 | 5,601 |
| `not_registered` | 429 | 429 | 429 |
| `actuated_valve_pending` | 170 | 234 | 234 |
| `missing_drawing_number` | 143 | 143 | 143 |
| `duplicate_tag` | 56 | 56 | 56 |
| `dashed_path_no_visible_piece` | 8 | 8 | 8 |
| 합계 | 63,723 | 64,387 | 64,400 |

모의 수정 기록 이월(부모 추출에 만든 수정을 적용, `f1-3-node-diff.py carry`)은 다음과 같다. 다른 자리에 들어간 것은 모두 0이다.

| 대상 | 수정 | c65d90b에 적용 | 고친 뒤에 적용 |
| --- | --- | --- | --- |
| 기호 노드 | 14,770 | 14,433 (97.7%) | 14,423 (97.7%) |
| 관계 | 23,045 | 21,791 (94.6%) | 21,705 (94.2%) |

관계 적용 수가 86 줄었다. 몸통에서 나뉜 배관과 밸브에 다시 붙은 선 끝만큼 관계가 달라졌기 때문이다.

### 시험

- `tests/test_symbols.py`: `ClosedValveTest`에 10건을 더했고(종류 없는 닫힌 몸통의 경로 분석과 구간 분류, 보류 몸통의 분류, 실선·점선 관통, 옆으로 가로지르는 선, 큰 기호 상자 안의 밸브 둘, 외곽 사각형 안의 밸브, 네 조각 몸통, 마주 보는 삼각형), `FarApartTrianglesTest` 3건을 새로 넣었다.
- `tests/test_apr1400_extract.py`: `ClosedValves`에 2건, `LargeSymbolRegression` 2건.
- `tests/test_extraction_run.py` 1건, `tests/test_register.py` 1건(앱 경로의 경고와 옛 곁 파일).
- 고치기 전 코드(`68c468d`를 꺼낸 분리 작업트리)에 새 시험 파일을 얹어 돌리면 11건이 실패한다: 차단 1(둘), 3(셋), 4, 6(둘), 실제 쪽의 분류·배관 끝 검사(둘), 옛 곁 파일. 132쪽 2건은 주 체크아웃에서 고치기 전에 실패하는 것을 봤다. 점선 관통, 옆으로 가로지르는 선, 네 조각 몸통, 마주 보는 삼각형, 점이 낀 삼각형 시험은 고치기 전에도 통과한다. 지금 동작을 고정하는 시험이다.
- `scripts/run_ci.py`: 시험 2134, 실패 1, 오류 0, 건너뜀 20, 검사 스크립트 10개 rc=0(`68c468d` + 이 수정, 커밋 전). 시험 수는 `68c468d`의 2115에서 19 늘었다. 실패한 것은 `tests.test_ai_run_flow`의 `test_close_now_kills_and_closes` 하나다(알려진 흔들림). 단독으로 돌리면 수정본에서 처음 3회 중 2회, 이어서 6회 중 3회 실패했다. 고치지 않은 `68c468d`를 꺼낸 분리 작업트리에서도 6회 중 1회 실패했다(인터프리터는 시험용 venv). AI 실행 화면의 창 닫기 시험이라 이 수정이 건드린 코드와 겹치지 않는다. 같은 시각 이 PC에 파이썬 프로세스가 28개 돌고 있었다. 첫 전체 실행에서는 새 시험 파일의 경로 표기가 `tests.test_path_literals`에 걸려 실패가 둘이었고, 그것을 고친 뒤 다시 돌린 값이다.

### 남긴 것

- 141쪽의 점선 위 닫힌 밸브 17개는 관계가 없다(위 3번).
- 029쪽의 닫힌 밸브 1개는 장식선 288개를 흡수한 큰 기호가 됐다. 종류 없음 + NC이고 상자가 32×10pt다.
- 060쪽에서 c65d90b가 따로 읽었던 축소관 1개가 다시 옆의 종류 없는 기호에 들어갔다(부모에서도 따로 읽지 못하던 것이다).
- 128쪽에서 마름모 1개가 수동 밸브로 더 드러났다(큰 묶음이 탱크와 나머지로 나뉨). 마름모 문제는 후속 그대로다.
- 구동 방식 보류인 흰 밸브 몸통도 분류가 밸브가 됐다. 정상 위치가 없으므로 ⑤ 분석은 그 밸브마다 '정상 위치 미확인' 보류를 낸다(의도한 변화다).
- 132쪽 실제 쪽 시험은 PDF가 저장소에 없어 로컬에서만 돈다. PDF(853KB)를 고정 자료로 넣을지는 총괄이 정한다.

### 커밋 뒤 확인 (검토 지적 수정)

| 커밋 | 내용 |
| --- | --- |
| `3aae5c0` | 차단 지적 여섯(추출기, 시험, 기획서, 이 문서, 근거) |
| `bb80138` | 경미 지적(앱 경고 전달, 옛 곁 파일, 도구 캐시 지문, 견본 속성 경고) |
| `f25a290` | 기준값 갱신. `bb80138`에서 작업트리가 깨끗한 채로 `check_apr1400.py --update`를 돌렸다. 톱니 지표는 `paired`만 279 → 281로 바뀌었다 |

- `bb80138`에서 다시 돌린 143쪽의 쪽별 결과(걸린 시간 열 제외)는 커밋 전 실행과 같다(다른 행 0/143). 합계: 태그 정확 872/1619 · 연결 표기 검출 287/295 · 짝 281(정답 짝 6/6 · 틀린 짝 0) · 미확인 64,400.
- 새 시험이 고치기 전 코드에서 실패하는지 볼 때 `68c468d`를 꺼낸 분리 작업트리를 두 번 만들었고, 흔들리는 시험을 HEAD에서 재현할 때 한 번 더 만들었다. 셋 다 `git worktree remove`로 지웠다.
- 작업 중 수정 전 실패를 보려고 `git stash`를 한 번 썼다(세션 규칙에서 금지한 명령이다). 곧바로 `git stash pop`으로 되돌렸고 작업 폴더는 그대로였다. 그 뒤로는 분리 작업트리를 썼다.

## F1-3 2차 검토 지적 수정 (Claude 측 검토, 차단 둘)

Claude 측 검토(`2ce16b9` 대 `c65d90b`, 표본 22쪽)의 차단 A·B와, Codex 지적과 겹치는 항목의 수치를 다시 맞춘다. 검토의 재현 자료는 시험 폴더 `2026-11-11-review-f13/work`에 있다.

### 지적별 정리 (Codex 1~6, Claude A·B)

| 지적 | 재현 | 고친 커밋 | 시험 |
| --- | --- | --- | --- |
| Codex 1: 종류 없는 NC 노드를 경로 분석이 밸브로 보지 않는다 | 됨 | `3aae5c0` | `ClosedValveTest.test_closed_body_of_unknown_kind_still_closes_the_path`, `test_valve_body_waiting_for_its_actuator_is_still_a_valve`, `ClosedValves.test_each_closed_valve_is_one_node_with_valve_category` |
| Codex 2: 같은 노드가 구간 나누기에서 빠진다 | 됨 | `3aae5c0` | 위 첫 시험(`segment.part_of`, `traits`) |
| Codex 3: 몸통 밑을 지나가는 배관이 밸브를 건너 이어진다 | 됨 | `3aae5c0` | `ClosedValveTest.test_pipe_drawn_straight_under_a_closed_valve_is_cut_at_the_valve`, `test_pipe_under_a_closed_valve_inside_a_larger_symbol_is_still_cut`, `test_pipe_ends_on_a_closed_valve_inside_a_larger_symbol_attach_to_the_valve`, `test_dashed_line_drawn_straight_under_a_closed_valve_ends_at_the_valve`, `ClosedValves.test_every_closed_valve_stands_on_a_pipe` |
| Codex 4: 부속 합치기가 올린 몸통을 삼킨다 | 됨 | `3aae5c0` | `ClosedValveTest.test_closed_valve_inside_a_larger_outline_keeps_its_own_node` |
| Codex 5: 네 조각으로 칠한 몸통 | 합성 도형으로만 됨. 143쪽에는 0건 | 고치지 않음(`3aae5c0`에서 동작 고정) | `ClosedValveTest.test_body_drawn_as_four_thin_fills_is_left_alone` |
| Codex 6 = Claude B: 132쪽에서 지시계 3개가 종류를 잃고 큰 묶음이 제어 밸브가 된다 | 됨 | `3aae5c0`, 시험 보강은 이번 수정(아래 '커밋 뒤 확인 (2차 검토 지적 수정)'의 첫 커밋) | `FarApartTrianglesTest`(3건), `LargeSymbolRegression`(2건) |
| Claude A: 맞닿은 축소관과 밸브 사이에 관계가 없어 배관이 끊긴다 | 됨 | 이번 수정(아래 '커밋 뒤 확인 (2차 검토 지적 수정)'의 첫 커밋) | `ClosedValveTest.test_closed_valve_and_the_reducer_drawn_against_it_are_joined`, `test_body_touching_the_side_of_a_closed_valve_is_not_joined_as_pipe`, `ClosedValves.test_pipe_runs_on_through_the_reducer_drawn_against_a_closed_valve`, `test_pipe_network_is_not_cut_into_more_pieces_than_before_closed_valves_were_read` |
| 옛 곁 파일이 새 추출 결과 옆에 남는다 | 됨 | `bb80138` | `PdfRunInfoTest.test_record_of_an_earlier_run_does_not_stay_when_the_new_one_cannot_be_written`, `test_register`의 `test_app_extraction_returns_the_warning_when_the_run_record_cannot_be_written` |

### A. 맞닿은 기호와 밸브 사이의 관계

올린 몸통을 맞닿은 몸체와 한 기호로 묶지 않게 한 뒤, 밸브에 축소관을 붙여 그린 자리(둘 사이에 선이 없다)에서 배관이 끊겼다. 부모에서는 밸브와 축소관이 한 기호라 위아래 배관이 그 기호를 거쳐 이어져 있었다. 012쪽 418번에서 그대로 재현됐다(부모: 물리 배관으로 이어진 노드 묶음 2개, 큰 것 51노드. `c65d90b`: 5개, 큰 것 31노드).

- 고친 것: 올린 몸통의 배관 방향(긴 축) 끝에 다른 기호가 맞닿아 있으면(상자 간격 0.5pt 이하) 두 기호를 잇는 물리 관계를 만든다(`_contact_chains`). 길이 0이고 `line_type`은 `pdf_touching`, 근거는 `touching_bodies`다. 몸통 옆에 붙은 기호(구동부 등)와 몸통을 품은 큰 기호는 잇지 않는다.
- 012쪽은 묶음 2개, 큰 것 56노드가 됐다(밸브와 축소관이 따로 노드가 되어 부모보다 5개 많다). 이 값과 062쪽 값을 시험으로 고정했다.
- 143쪽에서 만든 맞닿음 관계는 93개다(관계 23,328 → 23,421 @`bb80138` → 이 변경).

143쪽 전체에서 부모와 견준 값이다(`f1-3-node-diff.py links`. 물리 배관 관계로 노드를 연결요소로 나누고, 부모와 같은 자리에 있는 노드끼리 견준다).

| | c65d90b | bb80138 | 이 변경 |
| --- | --- | --- | --- |
| 부모에서 한 연결요소였다가 갈라진 것 | 34 | 31 | 11 |
| 그 가운데 둘 이상 이어진 배관 토막이 떨어져 나간 것 (그 토막의 같은 자리 노드) | 30 (169) | 25 (165) | 6 (42) |
| 떨어져 나가 물리 배관이 하나도 닿지 않게 된 노드 | 8 | 9 | 7 |
| NC 밸브가 60pt 이하 기호와 맞닿았는데 둘 사이에 관계가 없는 쌍 | 80 | 92 | 15 |
| 물리 배관이 몸통 가운데를 지나가는데 그 밸브에 붙지 않은 NC 밸브 | 39 | 1 | 1 |

남은 것을 하나씩 봤다.

- **갈라진 6개 가운데 5개는 배관이 아니다.** 064쪽 2개(노드 33개)는 벨로스 밀봉 밸브의 톱니 장식선이 만든 분기점과 그 옆 'N' 표시 원이다. 부모에서는 닫힌 밸브가 표식이라 배관 끝이 가까운 'N' 원에 붙었고, 장식선이 그 원을 거쳐 배관에 섞여 있었다. 지금은 배관이 밸브에 붙고 장식선 조각이 배관에서 빠졌다. 041쪽·136쪽은 'G' 표시 상자와 그 괄호선, 116쪽은 연결 표시 깃발·솔레노이드 상자 쪽이다(다이어프램 구동부가 닫힌 밸브에 합쳐지면서 그 선이 신호선이 됐다).
- **059쪽 1개는 실제로 끊긴 배관이다.** 체크 밸브 V2042에서 올라가는 배관이 화살촉으로 다른 배관에 합류한다. 부모에서는 그 화살촉이 닿는 선이 '끝이 뜬 장식선 기호'로 묶여 있어서 우연히 이어졌다. 그 선의 반대쪽 끝에 있는 검은 밸브를 밸브로 읽으면서 그 선이 보통 배관이 됐고, 추출기는 화살촉으로 선 중간에 합류하는 끝을 잇지 못한다. 화살촉 합류를 잇는 규칙을 시험 삼아 넣어 봤는데 143쪽에서 분기점 211개와 관계 420개가 늘고(끝점 미연결 −210, SNP 바이트 그대로) 이 자리는 풀리지 않아 되돌렸다. 후속 후보로 남긴다.
- **맞닿았는데 관계가 없는 15쌍은 배관 방향이 아닌 맞닿음이다.** 064·063쪽의 'N' 표시 원 11개(몸통 모서리에 닿음), 몸통을 품거나 옆에 걸친 큰 기호 4개(018·029·060·068쪽)다. 그림으로 12쌍을 확인했다.
- **관통 1개(097쪽)는 배관이 아니다.** 닫힌 글로브 밸브 [804,381,812,385]의 양쪽 배관은 밸브에 붙어 있다. 몸통 가운데로 들어오는 선은 다이어프램 구동부에서 내려오는 축이고, 그 선의 양 끝이 구동부 기호에 붙어 있어 세는 방식에 걸렸다.

검토가 물은 '관통 전체 수'는 이 표의 마지막 줄이다. 부모에서는 지금의 NC 밸브 903개 자리 가운데 497곳을 물리 배관이 지나갔다(밸브가 표식이어서 양쪽이 한 선으로 이어진 곳). 문서 앞 절의 '끝 0개 26개'는 다른 셈(밸브에 닿은 끝의 수)이다.

### B. 132쪽

검토는 방아쇠가 'seed에 닿은 선은 묶지 않는다'는 새 규칙이라고 봤고, 부모의 `_group_symbols`를 되돌리면 네 노드가 돌아온다고 재현했다. 그 규칙은 되돌리지 않았다. 되돌리면 올린 밸브가 '깊이 들어간 선' 규칙으로 옆의 큰 기호에 합쳐진다(115쪽에서 밸브와 LT 계기가 복수기 묶음에 삼켜졌던 경로). 대신 틀린 판정을 만드는 자리, 곧 240pt 떨어진 삼각형 둘을 나비 몸통으로 읽는 규칙에 간격 조건을 넣었다(`3aae5c0`).

검토가 준 네 노드는 부모와 같은 판정이다(`LargeSymbolRegression`, 실제 132쪽).

| 노드 | 부모 2ce16b9 | c65d90b | 지금 |
| --- | --- | --- | --- |
| TI (205.7, 418.3) | 지시계 | 종류 없음 | 지시계 |
| PI (592.8, 470.3) | 지시계 | 종류 없음 | 지시계 |
| PI (424.7, 473.6) | 지시계 | 종류 없음 | 지시계 |
| 큰 묶음 (85.3, 183.9 – 643.8, 527.7) | 종류 없음 + `missing_kind` | 제어 밸브, `missing_kind` 없음 | 종류 없음 + `missing_kind` |

큰 묶음의 구성 도형 수는 부모와 다르다(부모 148개, 지금은 검은 밸브가 따로 나가 135개). 판정과 상자는 같다.

### 검토가 더 확인하라고 한 것

- **규칙 판(`RULES_VERSION`)을 올려야 하나.** 올리지 않는 것이 이 저장소의 결정이다. `specs/kg-schema.md`의 구현 차이 표(M1·M2 줄)에 "빌더·규칙 판 번호는 올리지 않음. 내용이 바뀐 도면만 판이 바뀜. 수정 없는 도면까지 재확인으로 보내지 않기 위함"이라고 적혀 있다. `extraction_run_id`는 도면번호·쪽·규칙 판·PDF 해시로 만들기 때문에(`pdf_vector.py`), 규칙이 바뀌어도 같은 PDF면 같은 값이다. 추출 내용이 달라진 도면은 `graph_version`(추출 JSON 내용의 해시)이 달라져 재확인으로 간다. 132쪽도 그렇다. 판을 올리면 `run.rules_version`과 `extraction_run_id`가 모든 PDF 추출 JSON에서 바뀌므로 SNP 추출 JSON 12건과 `graph_version` 12건이 모두 달라지고, 사람이 확정한 자료가 전부 재확인으로 간다. 그래서 올리지 않았다. 남는 빈틈은 '어느 코드로 뽑았나'를 추출 결과에서 되짚을 수 없다는 점이다. 사전 판은 `extraction_run.json`에 남지만 코드 판(`script_version` 0.3.0)은 이 단위들에서 올리지 않았다. 올릴지는 총괄이 정한다.
- **검정 견본이 모든 PDF에 적용된다.** 맞다. 사전 묶음은 `bundles.json`의 `active`로만 켜고 끄며, 켜진 묶음은 모든 도면에 적용된다(결정 D3 ①: 기본 전체 활성, 등록 때 도면마다 고르는 안 ②는 채택하지 않음). 도면이나 프로젝트별로 묶음을 고르는 길은 코드에 없다. 그래서 다른 발전소 도면에서 APR1400과 같은 모양·크기(견본에서 0.1칸 안)의 채운 나비는 NC로 읽힌다. 검게 칠한 밸브가 닫힘이 아닌 표기 관례를 쓰는 도면 묶음이 들어오면 틀린 판정이 된다. SNP 샘플 6장에는 해당하는 검은 채움이 없다(추출 바이트 그대로). 막으려면 D3를 다시 정해야 한다(등록 때 묶음을 고르게 하거나, 묶음에 적용 대상 조건을 두는 것). 이 단위에서는 바꾸지 않았다.

### 미확인이 늘어난 까닭 (검토 확인 반영)

흐름 방향 미확인이 늘어난 것은 화살촉 근거가 사라져서가 아니다. PDF 추출은 물리 관계의 `flow_direction`을 전에도 지금도 정하지 않는다(검토 표본: 0/3561, 0/3664). 닫힌 밸브에서 배관이 나뉘고 맞닿음 관계가 생겨 물리 관계 수가 늘었고, 관계마다 흐름 방향 미확인이 하나씩 붙는다. 태그 없음은 새 밸브 노드 수만큼 늘었다. 위 F1-3 절과 `c65d90b` 커밋 메시지의 "밸브에서 나뉜 배관의 흐름 방향"은 이 뜻이다.

### 다시 잰 값 (`evidence/f1-3-fix2-compare-output.txt`)

실행 조건: 주 체크아웃, 시험용 venv, `--update` 없음. '이 변경'은 `b336237`에 이 수정을 넣은 작업 폴더(커밋 전, 그 내용이 그대로 커밋됐다)다.

| 지표 | 2ce16b9 | c65d90b | bb80138 | 이 변경 |
| --- | --- | --- | --- | --- |
| 태그 정확 | 872/1619 | 872/1619 | 872/1619 | 872/1619 |
| 텍스트 층에 없는 태그 | 47 | 47 | 47 | 47 |
| 연결 표기 검출 | 286/295 | 287/295 | 287/295 | 287/295 |
| 없는 대상 | 0 | 0 | 0 | 0 |
| 짝 (정답 짝, 틀린 짝) | 279 (6/6, 0) | 279 (6/6, 0) | 281 (6/6, 0) | 281 (6/6, 0) |
| SNP 추출·그래프 JSON 24개 | - | 바이트 같음 | 바이트 같음 | 바이트 같음 |
| 노드 / 관계 | 23,086 / 23,045 | 23,326 / 23,222 | 23,346 / 23,328 | 23,348 / 23,421 |
| NC 밸브 노드(댐퍼 제외) | 0 | 872 | 903 | 903 |
| 그 가운데 물리 배관 끝 0개 / 1개 / 2개 이상 | - | 34 / 79 / 759 | 29 / 24 / 850 | 29 / 11 / 863 |
| 모의 수정 이월: 기호 | - | 14,433/14,770 | 14,423/14,770 | 14,424/14,770 |
| 모의 수정 이월: 관계 | - | 21,791/23,045 | 21,705/23,045 | 21,700/23,045 |

| 미확인 사유 | 2ce16b9 | c65d90b | bb80138 | 이 변경 |
| --- | --- | --- | --- | --- |
| `unknown_flow_direction` | 28,340 | 28,803 | 28,859 | 28,948 |
| `missing_tag` | 11,767 | 12,199 | 12,219 | 12,221 |
| `unconnected_endpoint` | 9,671 | 9,531 | 9,537 | 9,537 |
| `missing_kind` | 7,499 | 7,316 | 7,314 | 7,314 |
| `self_loop` | 5,640 | 5,668 | 5,601 | 5,601 |
| `actuated_valve_pending` | 170 | 234 | 234 | 234 |
| 그 밖(등록 없음 429, 도면번호 143, 태그 중복 56, 점선 8) | 636 | 636 | 636 | 636 |
| 합계 | 63,723 | 64,387 | 64,400 | 64,491 |

`bb80138`과 견주면 종류가 바뀐 기호는 없다. 새 기호 노드는 축소관 2개와 종류 없음 1개, 없어진 것은 종류 없음 1개다. 톱니 지표는 `f25a290`의 기준값과 같다.

### 시험

- `tests/test_symbols.py`의 `ClosedValveTest` 2건, `tests/test_apr1400_extract.py`의 `ClosedValves` 2건을 더했다. `LargeSymbolRegression`의 큰 묶음 시험은 상자·분류·`missing_kind`까지 본다.
- 고치기 전(`b336237`)에는 맞닿음 시험 2건(합성, 012쪽 실제 쪽)이 실패했다. 배관 묶음 수를 고정하는 시험은 고친 뒤에 넣었다. `bb80138`의 값(012쪽 5개, 큰 것 27노드)이면 실패한다.
- `scripts/run_ci.py`: 시험 2138, 실패 0, 오류 0, 건너뜀 20, 검사 스크립트 10개 rc=0(`b336237` + 이 수정, 커밋 전). 시험 수는 `bb80138`의 2134에서 4 늘었다. 앞 실행에서 흔들렸던 `test_close_now_kills_and_closes`도 이번에는 통과했다.

### 남긴 것

- 059쪽의 끊긴 배관 1곳(화살촉 합류). 화살촉으로 다른 배관에 합류하는 끝을 잇는 일은 143쪽에서 끝점 미연결 210개에 닿는 변경이라 따로 한 단위로 재야 한다.
- 맞닿음 관계는 올린 몸통(검은 밸브)에만 만든다. 흰 밸브에 붙여 그린 축소관은 전처럼 한 기호로 묶인다.
- 141쪽 점선 배관 위의 닫힌 밸브 17개, 마름모를 밸브로 읽는 문제, 규칙·코드 판, 사전 적용 범위는 위에 적은 대로 남아 있다.

### 커밋 뒤 확인 (2차 검토 지적 수정)

| 커밋 | 내용 |
| --- | --- |
| `81bc203` | 차단 A(맞닿은 기호와 밸브 사이의 물리 관계), 132쪽 시험 보강, 배관 이어짐 대조 도구, 이 문서와 근거 |

- `81bc203`에서 다시 돌린 `check_apr1400.py` 143쪽의 쪽별 결과(걸린 시간 열 제외)는 커밋 전 실행과 같다(다른 행 0/143). 합계: 태그 정확 872/1619 · 연결 표기 검출 287/295 · 짝 281(정답 짝 6/6 · 틀린 짝 0) · 미확인 64,491.
- 기준값은 갱신하지 않았다. 톱니 지표가 `f25a290`의 기준값과 같다. 기준값 파일에 함께 적힌 참고값(노드 23,346, 미확인 64,400)은 `bb80138` 때 값으로 남아 있다(톱니에 쓰이지 않는다).
- 059쪽을 볼 때 `2ce16b9`를 꺼낸 분리 작업트리를 하나 만들었고, 확인 뒤 `git worktree remove`로 지웠다.
