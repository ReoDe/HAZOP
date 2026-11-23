# 구조를 바꾸는 고침: 나누기·배관 지정을 수정 기록에 담고 다시 추출로 적용하기

- 작성: 2026-11-18. 설계(조사·측정)와 U1 구현 결과를 함께 적는다.
- 코드 기준: 설계는 `a766a1d`(`feat/drawing-knowledge`), U1 구현은 그 위의 `feat/fix-input-ops`. 판 이전이 M1~M3로 다시 지어진 뒤 U1 본체를 `44e0c6e` 위로 옮겨 얹었다(`feat/fix-input-ops-2`, 5장 끝).
- 측정 조건: 시험용 venv(Python 3.12, pdfplumber 0.11.9), 한 프로세스, 다른 세션이 같은 기계를 쓰고 있었을 수 있음. 시간 값은 그 조건에서 한 번 잰 값이다. 측정 스크립트는 저장소 밖 시험 폴더(`fixflow`)에 있다.

## 0. 목표와 결론

목표는 APR1400 P&ID 읽기 정확도를 규칙·AI로 더 올리는 대신, 사람이 틀린 곳을 빨리 고치게 하는 것이다(`docs/records/backlog.md` 방향 점검 2). 지금 막힌 곳은 둘이다. split 후보를 수락하면 `add_node`만 생기고 배관 끝은 덩어리에 그대로 붙어 있다(`hazop/extract/ai_review.py` `_op_for`). '이 선은 배관'으로 고치는 연산도 없다.

결론은 다음과 같다.

1. 나누기(`split`)와 배관 지정(`pipe`)은 추출 결과에 덧바르는 연산이 아니라 추출의 입력이다. 수정 기록에는 두 종류 연산을 두고, 적용은 "입력 연산으로 쪽을 다시 추출한 기준 추출(base)을 만든 뒤, 나머지 연산을 그 위에 지금처럼 적용"하는 두 단계로 바꾼다.
2. 지금의 다시 찾기(`_retarget`·`_rematch`, 위치 `at` 지문)는 수정 연산에는 대체로 충분하다. 개발용 134쪽 실측에서 잘못 붙은 연산은 0건이었고, 적용 불가가 3.2%였다. 여기에 pdf 개체 집합 지문(`objs`)을 더하면 그 가운데 절반쯤을 더 살린다.
3. 위험은 수정 연산보다 검토구간 쪽에 있다. 다시 추출하면 `source_object_id`(기호 순번)가 밀리고, 검토구간의 안정 참조(`<graph_id>#<source_object_id>`, `hazop/study/migrate.py`)가 다른 기호를 가리킨다. 134쪽 나눔에서 14개(덩어리를 남길 때)~110개(덩어리가 사라질 때)였다. 그래서 첫 단위의 완료 기준에 "입력 연산이 다른 기호의 번호를 밀지 않는다"를 넣었다.
4. 이 위험은 입력 연산이 없어도 이미 있었다(5장). 규칙 판이 바뀐 뒤 같은 PDF를 다시 추출하면 ⑤ 결과의 대상 참조가 판 이전을 거치지 않아 알림 없이 다른 기기를 가리켰다. U1의 첫 커밋이 이것을 먼저 고쳤고, 지금은 판 이전을 다시 지은 M1~M3(`migration-map-design.md`)가 맡는다.

## 1. 저장 꼴

### 1.1 지금의 수정 기록

`hazop/extract/corrections.py`가 `<작업 루트>/data/drawing-edits/<추출 이름>.json`에 연산 목록을 둔다. 연산 하나는 `{op_id, op, target, base, refs, value, by, at}`이고, `target`은 `source_object_id`, `base`는 만들 때의 대상 지문(노드 `{kind, category, tag, at}`, 관계 `{kind, ends, at}`, `at`은 위치 상자 중심 정수 반올림)이다. 연산 표 `OPS`가 이름마다 대상 종류·값 검사·적용 함수·지우는 미확인을 정한다. 적용할 수 없는 연산은 사유와 함께 `not_applicable`로 남고 나머지는 계속 적용된다(`apply`).

### 1.2 새 연산 두 가지

`OpSpec`에 `stage` 칸을 더했다. 기존 연산은 `"overlay"`, 새 두 연산은 `"input"`이다. 입력 연산은 `apply`가 아니라 기준 추출을 만드는 쪽(2장)이 읽는다. 표 하나에 두면 값 검사, op_id 발급, 기록(log), 되돌리기가 지금 길을 그대로 쓴다. `apply`는 입력 연산을 적용하지 않고 `corrections.input_ops`에 적는다. 그래서 `resolve`로 옮기지 않은 호출 자리가 있으면 결과에서 드러난다.

**덩어리 나누기 `split`.** 덩어리 하나에서 기호 하나를 떼어 내는 연산이다. 기호마다 연산 하나로 둔다. AI 후보가 기호마다 하나이고(`ai_split.candidates`), 되돌리기도 기호 단위가 자연스럽다. 같은 덩어리(`target`)에 걸린 split 연산들은 다시 추출할 때 한 나눔의 `groups`로 모은다.

```json
{"op_id": "c-0031", "op": "split", "target": "pdf-p0-sym-0041",
 "base": {"kind": null, "category": null, "tag": null, "at": [<x>, <y>], "objs": "o-3f9a1c"},
 "value": {
   "pdf": {"sha256": "<source.sha256>", "page": 0, "reader": "pdfplumber-0.11.9"},
   "objects": ["pdf-path-0412", "pdf-path-0413", "pdf-path-0420"],
   "shapes": {"pdf-path-0412": [<x0>, <y0>, <x1>, <y1>, <점 수>, <닫힘>], "...": []},
   "kind": "manual_valve"},
 "origin": "ai", "ai_candidate": "split:pdf-p0-sym-0041:<해시>", "by": "...", "at": "..."}
```

- `target`은 덩어리 노드다. `base.objs`는 덩어리의 `evidence.pdf_objects` 지문이다(1.3).
- `objects`는 떼어 낼 pdf 개체 id, `kind`는 떼어 낸 기호의 종류(없으면 null)다. 종류를 같은 연산에 넣으면 사람 동작이 하나로 끝난다.
- 다시 추출로 생긴 새 노드는 `source_object_id`를 `pdf-p<쪽>-split-<op_id>`로 받는다(2.4). `manual-<op_id>`처럼 연산에 묶인 이름이라, 다른 split이 더해지거나 빠져도 바뀌지 않는다.
- 값은 `corrections.input_value(추출, 개체 목록, kind=...)`가 원본 PDF에서 `pdf`·`shapes`를 채워 만든다. 벡터 PDF 도면이 아니면 `make_op`·`input_value`가 거절한다(SNP drawio·DEXPI·스캔 도면).

**배관 지정 `pipe`.** "이 도형들은 배관이다"라는 연산이다. 대상 노드는 없다(`target: null`, `add_node`와 같은 꼴).

```json
{"op_id": "c-0032", "op": "pipe", "target": null, "base": null, "refs": {},
 "value": {
   "pdf": {"sha256": "...", "page": 0, "reader": "pdfplumber-0.11.9"},
   "objects": ["pdf-path-0890"],
   "shapes": {"pdf-path-0890": [<x0>, <y0>, <x1>, <y1>, 64, true]},
   "ring": true, "line_type": "process"}}
```

- `ring`은 만들 때 정해 적는다. 닫힌 곡선(`closed` 또는 첫 점과 끝 점이 같은 4점 넘는 꼴)이면 참이고, 다시 추출 때 고리 헤더 분기점 하나에 닿은 사슬과 기호를 잇는다. 적어 두는 까닭은 pdfplumber 판이 바뀌어 닫힘 판정이 달라져도 연산의 뜻이 바뀌지 않게 하려는 것이다.
- 고리 분기점의 `source_object_id`는 `pdf-p<쪽>-ring-<op_id>`로 준다.
- U1은 연산 꼴과 값 검사까지다. 다시 추출에 넣는 일(사슬 잇기)은 U3이고, 그 전까지 `pipe` 연산은 저장되되 "배관 지정은 아직 다시 읽기에 넣지 않음"으로 적용 불가에 남는다.
- 실험 패치(`_take_pipes`: 기호·틀·표 칸·점선 경로에서 그 도형을 떼어 열린 선은 선 목록에, 닫힌 도형은 고리로, 약 90줄)는 합성 분무 고리에서 정답 쌍이 0%에서 90~100%, 오검출 0이었다(`docs/records/backlog.md`).

### 1.3 path id를 무엇으로 고정하나

`pdf-path-NNNN`은 `load_page`가 `pg.lines + pg.rects + pg.curves`를 차례로 이어 붙인 목록의 순번이고, 하위 경로는 `-k`가 붙는다. 그래서 두 가지에 묶인다.

- PDF 바이트. 추출 결과 `source.sha256`이 파일 전체의 sha256이다. 쪽만 따로 해시할 수단은 없고, 등록 원본은 바뀌지 않으므로 파일 sha로 충분하다. 쪽은 `page`로 적는다.
- pdfplumber·pdfminer 판. 같은 바이트도 판이 바뀌면 개체 순서가 바뀔 수 있다. `reader`에 판을 적는다.

여기에 개체 지문을 더한다. `shapes`는 개체 id마다 `[x0, y0, x1, y1, 점 수, 닫힘]`이다(좌표는 0.1pt 반올림, `pdf_vector.object_shapes`). 노드·관계 지문의 `objs`는 `evidence.pdf_objects`를 정렬해 sha1 앞 6자리로 줄인 값이다.

적용할 때는 이렇게 본다(`corrections._locate`).

1. `sha256`·`reader`가 지금과 같고, `objects`의 id마다 지금 쪽의 그 id 모양이 `shapes`와 같으면 그대로 쓴다.
2. 하나라도 다르면 모양으로 다시 찾는다. 지금 쪽 개체 가운데 상자가 0.2pt 안에서 같고 점 수·닫힘이 같은 것이 정확히 하나면 그 id로 바꾼다. 모두 찾으면 적용하고 `retargeted`에 옛 id와 새 id를 남긴다.
3. 못 찾은 개체가 있으면 그 연산은 적용 불가다. 사유는 "도면이 바뀌어 나눌 개체를 찾지 못함(3개 중 1개)"처럼 몇 개를 못 찾았는지 적는다. 덩어리 노드(`target`)를 못 찾는 것은 적용 불가 사유가 아니다. 나눔 입력은 개체 집합만 쓰고, 다시 추출한 쪽에서 그 개체를 가진 기호를 덩어리로 삼는다(`_carve_splits`의 `node: None`).

## 2. 적용 차례와 ID 다시 찾기

### 2.1 두 단계 적용

```
resolve(name) =
  ops       ← 수정 기록
  inputs    ← ops 가운데 stage == "input"
  base      ← inputs가 없으면 extraction.json 그대로
               있으면 pdf_vector.extract(원본 PDF, page, splits=[{"node": None, "groups": [{"name": "split-<op_id>", "objects": [...]}]}])
               의 내용 칸(nodes, relations, unresolved_connectors, texts, unclassified, source_locations, validation,
               drawing.ignored_objects)만 extraction.json에 옮겨 붙인 것. split의 kind는 나눈 기호에 바로 넣는다
  corrected ← apply(base, overlay ops)          # 지금의 apply 그대로, 지문 비교 기준만 base
```

- `apply`는 순수 함수로 남긴다. 파일·PDF를 읽는 일은 `resolve`·`ensure_base`만 한다.
- 기준 추출은 다시 만드는 데 1~26초가 걸리므로(6장) 파일로 둔다. 자리는 `output/extract/<name>/extraction.inputs.json`이고 꼴은 `{"kind": "hazop_input_extraction", "key", "inputs": {"applied", "not_applicable", "retargeted"}, "extraction"}`이다. 열쇠 `inputs_key = sha256(source.sha256, 쪽, extraction_run_id, RULES_VERSION, 추출 코드 지문, 기호 사전 JSON 해시, 입력 연산(op_id·종류·대상·값))`다. 추출 코드 지문(`corrections.code_fingerprint`)은 `FINGERPRINT_MODULES`(pdf_vector 묶음과 import 닫힘, `corrections.py`)와 `hazop/kg/schema/registry.json`의 내용 해시(줄끝 LF 정규화, 프로세스에서 한 번)다. 개발 실행은 소스 파일을, 묶인 실행(PyInstaller는 .py 없이 PYZ 안 코드만 가짐)은 로더가 주는 코드 개체를 해시한다. 그래서 `RULES_VERSION`을 올리지 않고 추출 코드를 고쳐도 옛 기준 추출을 쓰지 않는다. 열쇠가 맞으면 읽고, 다르면 다시 만든다. 같은 입력이면 같은 결과이므로 두 번 만들어도 결과가 같다.
- 화면 스레드는 다시 추출하지 않는다. `resolve(name)`(기본 `allow_extract=False`)는 파일이 없거나 열쇠가 다르면 `inputs.state = "pending"`으로 표시하고 `extraction.json` 위에 나머지 연산을 적용한 결과를 돌려준다. 다시 추출은 작업(job)과 `scripts/build_graph.build_one`만 한다(`ensure_base(name)` 또는 `allow_extract=True`). `ensure_base`는 다 만든 뒤 수정 기록이 그새 바뀌었으면 한 번 더 만든다.
- 원본 PDF가 `source.file`에 없거나 `source.format`이 `pdf_vector`가 아니면 입력 연산은 모두 적용 불가("원본 PDF 없음", "벡터 PDF 도면만")다.

### 2.2 다시 찾기가 어떻게 동작하나

`corrections.apply`는 기준 추출의 지문표(`_fingerprints`)를 만들고, 연산마다 `_retarget`을 먼저 부른다.

- 대상 지문이 `base`와 다르면 `_rematch`가 다시 찾는다. `objs`가 같은 대상이 정확히 하나면 그것이고, 아니면 같은 `at`·같은 종류·관계 여부가 같은 대상이 정확히 하나일 때만 그 id로 옮긴다. 관계의 `ends`는 노드 번호가 같이 밀리므로 보지 않는다.
- `_same`은 `category`·`objs`를 보지 않는다(조각 하나가 더 붙어도 같은 기호다). `at`이 있으면 없던 kind·tag가 새로 생긴 것은 같은 대상으로 본다. 물리 연결이 측정 연결로 바뀐 것도 같은 대상이다.
- `value` 안의 노드 참조(`from`·`to`·`node`)도 `refs` 지문으로 같은 식으로 옮긴다.
- 연산에 묶인 id(`manual-<op_id>`, `pdf-p<쪽>-split-<op_id>`, `pdf-p<쪽>-ring-<op_id>`)는 다시 찾지 않는다. 그 나누기가 되돌려져 대상이 없으면 "나누기 c-0031이(가) 되돌려져 대상이 없음"으로 적용 불가다(같은 자리의 덩어리로 옮겨 붙지 않는다).

### 2.3 실측: 나눔 다시 추출 뒤 기존 수정이 어떻게 붙나

원본 추출의 노드(종류 있는 것)마다 `set_tag`, 관계마다 `set_tag`(배관 번호)를 만들고, 나눔 입력으로 다시 추출한 결과에 그대로 적용했다. 나눔 묶음은 AI 답 대신 덩어리의 몸체·선을 1.5pt 닿음으로 묶어 만들었다. 붙은 대상이 원래 대상과 pdf 개체 집합이 같은지로 맞고 틀림을 갈랐다(`a766a1d`, 설계 때 측정).

| 쪽·경우 | 연산 | 같은 id에 맞게 | 옮겨서 맞게 | 잘못 붙음 | 적용 불가(같은 개체 짝 있음) | 적용 불가(짝 없음) | 다른 개체를 가리키게 된 `source_object_id` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 134 덩어리 남김(7묶음) | 558 | 226 | 314 | 0 | 8 | 10 | 14 |
| 134 덩어리 사라짐(9묶음) | 558 | 244 | 301 | 0 | 7 | 6 | 110 |
| 030 덩어리 남김(6묶음) | 73 | 73 | 0 | 0 | 0 | 0 | 0 |
| 030 덩어리 사라짐(8묶음) | 73 | 22 | 49 | 0 | 0 | 2 | 40 |

- 잘못 붙은 연산은 네 경우 1,262건 가운데 0건이다. 위치 지문이 지켜 준다.
- 134쪽 덩어리 남김에서 18건(3.2%)이 적용 불가다. 그 가운데 8건은 다시 추출한 결과에 pdf 개체 집합이 똑같은 대상이 하나 있었다. `objs` 지문으로 살릴 수 있는 몫이다. 나머지 10건은 대상의 개체가 실제로 바뀐 것(풀려난 선이 배관 사슬에 다시 묶임)이라 알림이 맞는 처리다.
- 마지막 열은 다시 추출 전과 후에 같은 `source_object_id`가 다른 개체 집합을 가리키는 노드 수다. 수정 연산은 지문이 막아 주지만, 검토구간의 안정 참조와 ⑤ 결과의 참조는 `source_object_id`만으로 옛 구성요소를 찾았다. 이 경로는 저장·ID 경로(CLAUDE.md 규칙 3)라 5장에서 재현하고 고쳤다.
- 합성 묶음은 AI 답과 다르므로 이 표는 경향을 보는 값이다.

### 2.4 번호를 밀지 않기와 연산의 기댐

1. **나눔이 다른 기호의 번호를 밀지 않는다.** 전에는 `_carve_splits`가 살아 있는 기호 뒤에 새 기호를 붙이고, 그 뒤에 배출구·끝막음 기호가 붙으며, `build_extraction`이 목록 순번으로 `pdf-p%d-sym-%04d`를 줬다. 덩어리가 사라지면 그 뒤 기호가 모두 한 칸씩 당겨졌다. 지금은 다음과 같다.
   - 이름 있는 묶음(사람의 split 연산)의 새 기호는 `pdf-p<쪽>-split-<op_id>`를 id로 받는다.
   - 나눔이 있으면 `analyze_bytes`가 같은 쪽의 나눔 없는 분석(캐시에 있으면 그것)의 기호 순서를 번호 기준(`numbering`)으로 넘긴다. `build_extraction`(`_sym_numbers`)은 pdf 개체가 똑같은 기호에만 그 번호를 주고, 개체가 바뀐 기호(조각을 떼인 덩어리, 풀려난 선을 받은 기호, 새 사슬의 배출구·끝막음)는 마지막 번호 뒤 번호를 준다. 옛 번호를 다른 모양에 물려주지 않으므로 같은 id가 다른 기호를 가리키지 않는다(못 찾는 쪽이다). 나눔이 없으면 목록 순번 그대로라 바이트까지 같다.
   - 처음에는 나누기 전 목록의 자리(`slot`)와 없앤 덩어리의 구멍으로 번호를 지키려 했다. 134쪽에서 91개가 밀렸다. 나누기 전 목록의 기호 가운데 나중에 부속으로 합쳐지는 것(`_merge_appendages`)이 나눔 여부에 따라 달라져 자리 수가 맞지 않았다. 그래서 나눔 없는 분석을 기준으로 바꿨다. 대신 나눔 다시 추출이 나눔 없는 분석을 한 번 더 한다(캐시가 없으면 원시 요소 읽기와 분석이 두 번).
2. **지문에 `objs`를 더했다.** `fingerprint`에 `objs`(pdf 개체 집합 지문)를 넣고, `_same`은 그 칸을 견주지 않는다(옛 연산의 `base`에는 `objs`가 없다). `_rematch`는 `objs`가 같은 대상이 정확히 하나면 먼저 그것을 고른다. 분기점처럼 개체가 없는 노드는 `objs`가 없으니 `at`만 쓴다.
3. **연산이 기댄 입력을 적는다.** `make_op`가 대상이나 참조가 입력 연산이 만든 것(`pdf-p0-split-c-0031`, 고리 분기점, 지정한 배관 개체를 근거로 가진 관계)이면 `via: ["c-0031"]`을 적는다. 되돌리기(3장)와 적용 불가 사유가 이 값을 쓴다.
4. **`make_op`의 기준은 base다.** `make_op(추출, …)`의 첫 인자에 기준 추출을 넘기면 나눔으로 생긴 노드도 고칠 수 있다. 부르는 곳(`ai_review.accept`의 `original_ex`, `api_corrections._request`·`_sources`의 `original`)을 `resolve`가 돌려준 base로 바꾸는 일은 U2다.

### 2.5 부르는 곳 옮기기(U2)

`corrections.apply`·`apply_saved`를 부르는 곳은 아홉 군데다(`hazop/app/data.py`, `hazop/app/screens/ai_review_panel.py`, `hazop/extract/confirmation.py`, `hazop/shell/ai_image_flow.py`, `hazop/shell/api_aireview.py`, `hazop/shell/api_corrections.py` 두 곳, `scripts/build_graph.py`, `scripts/check_corrections.py`). 모두 `resolve`로 옮기고 `apply_saved`는 지운다.

### 2.6 재현 시험

먼저 실패를 보이고(HEAD에서 실패, 고친 뒤 통과), 그다음 지킨다. 합성 쪽은 `tests/test_corrections_inputs.py`의 1쪽 PDF다(맞닿은 밸브 셋이 한 덩어리로 읽히고, 양쪽에 배관, 그 뒤 순번에 태그 없는 수동 밸브 둘).

| 번호 | 시험 | 먼저 보인 실패(HEAD `a766a1d`) | 고친 뒤 |
| --- | --- | --- | --- |
| R1 | 덩어리가 사라지는 나눔 | 뒤 밸브 `sym-0002`가 다른 밸브의 개체를, `sym-0003`이 떼어 낸 개체를 가리킴 | 뒤 밸브 id 그대로, 나눈 기호 셋, 양쪽 배관 끝이 바깥 나눈 기호에 붙음 |
| R2 | R1 + 검토구간 | 구성요소가 옆 밸브로 옮겨 감 | 같은 밸브(같은 상자)를 가리킴 |
| R3 | 나눈 기호에 `set_tag` | `make_op`·입력 연산 없음 | 연산이 만들어지고 `via`가 적힘, 태그가 붙음 |
| R4 | R3 뒤 split 되돌리기 | (새 시험) | 기준 추출이 원본과 같은 바이트, `set_tag`는 "나누기 …이(가) 되돌려져 대상이 없음", `dependents`가 그 연산을 돌려줌. 입력 연산을 모두 빼면 원래대로 |
| R5 | pdf 개체 순번이 밀린 PDF / 개체를 옮긴 PDF | (새 시험) | 모양으로 다시 찾음(`retargeted` 6) / "도면이 바뀌어 나눌 개체를 찾지 못함(2개 중 2개)" |
| R6 | 개발용 134쪽 replay(시험 폴더 스크립트) | 다른 개체를 가리키게 된 `source_object_id` 14 / 110 | 7장 |
| R7 | 입력 연산 없는 도면 | (지키기) | 기준 추출이 `extraction.json` 그대로, 결과가 `apply`와 같은 바이트, 기준 추출 파일 없음, 나누기 없는 추출은 예전과 같음. drawio 도면은 입력 연산을 거절 |
| R8 | 합성 분무 고리 | `pipe` 연산 없으면 정답 쌍 0% | U3 |

이미 수락된 AI split(`add_node`, `origin: ai`)은 지금처럼 `manual-<op_id>` 노드로 읽힌다(시험으로 지킴). 이것을 `split` 연산으로 바꾸는 이전은 U2다.

## 3. 되돌리기

- 기준 추출은 입력 연산의 순수 함수다. 입력 연산을 지우면 열쇠가 바뀌어 기준 추출을 다시 만든다. 입력 연산이 하나도 남지 않으면 `extraction.json`을 그대로 쓰므로 다시 추출이 없다(즉시, 바이트까지 같음).
- 그 사이 새 노드에 한 수정. 대상이 `pdf-p0-split-c-0031`이면 그 id가 없어져 "나누기 c-0031이(가) 되돌려져 대상이 없음"이 된다. 순번 id였다면 다른 기호에 붙을 수 있었는데, 이름을 연산에 묶었기 때문에 그런 일이 없다.
- 알림. `corrections.dependents(ops, op_id)`가 `manual-`·`split-`·`ring-` 대상을 가리키거나 `via`에 그 op_id를 적은 연산을 이어서 모두 돌려준다. 셸의 `api_corrections._depends`를 이 함수로 바꾸고 "이 나누기 위에 한 수정 3건이 함께 빠집니다"를 보이는 일은 U2다. 기록(log)의 `removed_ops`에 모두 남으므로 다시 하기(redo)로 함께 되살린다.

## 4. 검토구간·그래프·지식그래프 쪽 영향

- `graph_version`은 고친 추출 전체의 해시다. 어떤 연산이든 바뀌면 판이 바뀌고, 검토구간 `is_stale`이 참이 되어 화면이 재확인을 알린다.
- 판 이전(`hazop/study/idmap.py` 대응표, `hazop/study/migrate.py`)은 그래프 노드의 `id_basis`(`hazop/extract/ids.py`)를 보고 구성요소를 다시 찾는다. 나눈 기호 `pdf-p<쪽>-split-<op_id>`는 연산에 묶인 id라 `source`이고 참조로 잇는다. 순번 기호는 표시(종류·도면·기호 종류·태그·상자)로 잇는다. 덩어리가 사라지면 그 덩어리를 구성요소로 가진 구간은 그 자리를 `nodes[].lost`의 묘비(`lost:<graph_id>:<판>:t-<지문>`)로 옮기고 재확인 대상이 된다. 나누기를 되돌리면 나눈 기호 자리도 묘비가 되며, 돌아온 덩어리가 그 자리를 받지 않는다. 나눈 기호를 구간에 넣는 일은 사람이 한다.
- 구간 지문(`md3-`)은 닿는 관계의 종류·태그·흐름을 본다. 나눔으로 배관 끝이 덩어리에서 새 기호로 옮겨지면 그 구간의 지문이 바뀌어 재확인이 뜬다.
- 기준값. `check_apr1400.py`·`check_snp_baseline.py`·`check_read_quality.py`(스크립트만)는 수정 기록 없이 추출하므로 입력 연산과 닿지 않는다. `check_read_quality`의 '스크립트 + AI 후보'(`apply_with_splits`)는 이름 없는 나눔을 쓰는데, 구멍을 비워 두는 번호 규칙 때문에 그 길의 id가 바뀔 수 있다(기준값 파일에는 없는 값). 입력이 없을 때 결과가 바이트 같음을 R7로 지키므로 `RULES_VERSION`은 올리지 않았다.

## 5. 이미 있던 결함: 규칙 판이 바뀐 다시 추출과 판 이전

입력 연산이 없어도 앱을 올려 추출 규칙이 바뀐 뒤 같은 PDF를 다시 추출하면 같은 위험이 있었다. 옛 판 코드로 추출 → 그 위에 검토구간 제안·확정·저장 → 지금 코드로 다시 추출 → `nodes.load_fp`(판 이전)으로 세었다. 구성요소마다 옛·새 대상의 pdf 개체 집합을 견줬다.

| 옛 판(날짜) | 쪽 | 구간 구성요소 | 같은 기호(고치기 전 → 뒤) | 다른 기호(구간은 재확인으로 걸림) | 다른 기호를 가리키는 ⑤ 참조(고치기 전 → 뒤) |
| --- | --- | --- | --- | --- | --- |
| `18c58c9`(11-16) | 134 | 812 | 39 → 632 | 514 → 1 | 514 → 1 |
| `223dc71`(11-15) | 134 | 645 | 25 → 409 | 448 → 4 | 448 → 4 |
| `085cd91`(11-13) | 134 | 643 | 18 → 321 | 471 → 4 | 471 → 4 |
| `18c58c9` | 030 | 138 | 103 → 122 | 18 → 0 | 18 → 0 |
| `223dc71`·`085cd91` | 030 | 110 | 76 → 102 | 30 → 0 | 30 → 0 |
| 11-16 뒤 판 셋, 모든 판 | SNP 6장(PDF·drawio) | | 모두 같음 | 0 | 0 |

- 검토구간은 실측에서 조용히 넘어간 것이 없었다. 큰 규칙 변경은 같은 구간의 종류·태그·연결도 바꿔 구간 지문이 늘 달라졌기 때문이다. 조용히 넘어가는 조건(태그 없는 같은 종류 밸브끼리 순번이 밀리고 연결도 같은 꼴)은 합성 시험으로 재현했다(`tests/test_study_migrate.py` `ShiftedSymbolTest`).
- ⑤ 결과 항목의 원인 위치·영향 대상·보호수단 구현 대상 참조와 잠재 후보 ID는 판 이전을 거치지 않아 위 '다른 기호' 수만큼 알림 없이 다른 기기 이름으로 보였다.
- 고침. U1 첫 판에서는 커밋 두 개(`e992876`·`32017ca`, 검토 차단 고침 `c8740cc`)로 순번 꼴 구성요소에 위치 표시를 남기고 찾지 못한 참조 끝에 `~lost`를 붙였다. 이 방식은 판 이전을 다시 지은 M1~M3로 대체되었다(`migration-map-design.md`). 지금 꼴은 다음과 같다. M1은 그래프 노드에 `id_basis`(sequence·source)를 적는다. M2는 대응표 하나(`idmap.compute`)를 먼저 계산해 등록부 `FIELDS`의 모든 id 자리에 `idmap.apply`로 적용한다. 옛 구성요소는 새 구성요소 하나나 묘비 하나로 가고, 구간의 잃은 자리는 `nodes[].lost`에 둔다. M3는 초기사건 문서·FMEA·잠재 후보 판단을 같은 표로 옮긴다(`hazop/study/follow.py`). 지식 입력 `links.csv`는 사람이 쓴 입력이라 고쳐 쓰지 않고 `kg.link`의 재확인에 맡긴다.
- 표 숫자는 첫 커밋(종류·태그를 보지 않던 표시) 기준이다. 지금 판 이전은 종류·태그가 달라진 기호도 묘비로 돌리므로 '같은 기호'가 그보다 줄어든다(놓치는 쪽).
- 옮겨 얹기(`feat/fix-input-ops-2`). U1 본체 두 커밋은 판 이전 코드를 건드리지 않아 충돌 없이 얹혔다. R2 시험이 읽는 이력 detail의 `renamed`는 M2가 그대로 남긴다(`idmap.record`). 나눈 기호가 `source`로 판단되는지, 나누기를 되돌리면 그 자리가 묘비가 되는지를 실제 추출로 확인하는 시험을 `tests/test_corrections_inputs.py`에 더했고, 판 이전 퍼즈(`tests/test_study_migrate_fuzz.py`)에 나누기와 그 되돌림을 넣었다.

## 6. 다시 추출 비용과 화면 흐름

### 6.1 실측(`a766a1d`, 설계 때 측정)

| 값 | 범위 | 비고 |
| --- | --- | --- |
| 쪽 추출(캐시 없음), 정답지 12쪽 | 0.7~21.7초 | 프로세스 첫 쪽은 준비 시간이 붙는다 |
| 쪽 추출(캐시 없음), 나눔 대상 쪽 | 134쪽 26.3초, 030쪽 7.8초 | |
| 나눔 입력으로 다시 추출 | 134쪽 19.1~19.4초, 030쪽 7.7~7.9초 | 원시 요소 읽기부터 다시 한다 |
| 같은 분석으로 결과만 다시 짓기(캐시 적중) | 0.3~2.9초 | `build_extraction`만 |
| 수정 연산 적용(86~716개) | 3~64밀리초 | `apply` |

한 번 나누는 데 쪽에 따라 1초 안팎에서 30초 가까이 걸린다. 화면을 멈출 수 없으므로 작업으로 돌린다. 원시 요소 읽기(`load_page`)를 따로 캐시하면 나눔 다시 추출이 그만큼 줄겠지만 몫을 따로 재지 않았다(U2).

### 6.2 화면 흐름(U2·U4)

1. 사람이 split 후보를 수락하거나 덩어리 안을 끌어 상자를 그린다. 또는 선을 누르고 '이 선은 배관'을 고른다.
2. 셸이 도면 잠금 안에서 수정 기록에 연산을 쓴다. 바로 답하고, 도면에는 그 자리에 흐린 상자나 선 강조를 '다시 읽기 대기'로 덧그린다(`resolve`의 `inputs.state == "pending"`).
3. 작업 줄에 '도면 다시 읽는 중'이 뜬다. 작업은 `corrections.ensure_base(name)` → `sheet_refresh.refresh(name)` → 알림 차례로 돈다.
4. 끝나면 도면이 새 노드·옮겨진 배관 끝으로 다시 그려지고, 적용 불가가 생겼으면 사유와 함께 고치기 패널에 보인다.
5. 그새 다른 고침이 들어오면 그 고침은 기다리지 않고 저장된다. `ensure_base`는 끝날 때 열쇠를 다시 보고, 바뀌었으면 한 번 더 돈다.

### 6.3 경계와 함수 서명

```python
# hazop/extract/corrections.py
def resolve(name, original=None, ops=None, *, allow_extract=False) -> dict
    # {"original", "base", "corrected", "ops", "inputs": {"key", "state": "none|ready|pending", "applied", "not_applicable", "retargeted"}}
def ensure_base(name, original=None) -> str         # 작업에서 부름. none|ready|pending
def apply(base, ops) -> dict                         # 입력 연산은 corrections.input_ops로 건너뜀
def make_op(base, op, target, value, by, ...) -> dict   # via를 적음. 입력 연산은 벡터 PDF만
def input_value(extraction, objects, **extra) -> dict   # split·pipe 값(pdf·shapes)을 원본 PDF에서 채움
def dependents(ops, op_id) -> list[str]              # manual-·split-·ring-·via, 이어서

# hazop/extract/adapters/pdf_vector.py
def extract(path, page=0, repo_root=None, params=None, registration=None, splits=None) -> dict
    # splits: [{"node": [...] 또는 None, "groups": [[...]] 또는 [{"name": "split-c-0031", "objects": [...]}]}]
def object_shapes(path, page=0) -> dict   # {id: [x0, y0, x1, y1, 점 수, 닫힘]}
def reader_version() -> str
```

셸 쪽(`hazop/shell`)은 `pdf_vector`를 직접 부르지 않고 `corrections`만 부른다.

## 7. U1 측정

이름 있는 나눔(사람의 split 연산 꼴)으로 다시 추출해 잰 값이다(2.3과 같은 닿음 묶음, 시험 폴더 `replay_u1.py`·`renumber_size.py`).

| 쪽·경우 | 연산 | 맞게 붙음 | 잘못 붙음 | 적용 불가(같은 개체 짝 있음) | 적용 불가(짝 없음) | 다른 개체를 가리키게 된 `sym` id(덩어리 제외) | 옛 번호를 잃은 기호(새 번호를 받음) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 134 덩어리 남김(7묶음) | 558 | 548 | 0 | 0 | 10 | 0(설계 측정 14) | 1 |
| 134 덩어리 사라짐(9묶음) | 558 | 556 | 0 | 0 | 2 | 0(설계 측정 110) | 1 |
| 030 덩어리 남김(6묶음) | 73 | 73 | 0 | 0 | 0 | 0(0) | 0 |
| 030 덩어리 사라짐(8묶음) | 73 | 71 | 0 | 0 | 2 | 0(40) | 2 |

- 적용 불가 가운데 '같은 개체 짝 있음'은 0이다(설계 측정 8·7). `objs` 다시 찾기가 살렸다.
- 남은 적용 불가(134쪽 10·2, 030쪽 2)는 대상의 개체가 실제로 바뀐 것(풀려난 선이 사슬에 다시 묶임)이라 알림이 맞는 처리다.
- 사슬에서 나오는 기호(배출구·끝막음 등)는 개체가 바뀌면 옛 번호를 잃고 새 번호를 받는다. 134쪽 1개, 030쪽 0~2개다. 옛 번호는 다른 기호에 넘어가지 않는다.

## 8. 단위 나누기

| 단위 | 하는 일 | 주인 파일 | 완료 기준 |
| --- | --- | --- | --- |
| U1 저장 꼴·적용·ID | `OpSpec.stage`, `split`·`pipe` 값 검사, `resolve`·`ensure_base`·기준 추출 파일, `objs` 지문과 `_rematch`, `via`, 나눔 새 기호 이름·번호 유지, `object_shapes`. `pipe`는 연산 꼴과 검사만 | `hazop/extract/corrections.py`, `hazop/extract/adapters/pdf_vector.py`, `tests/test_corrections_inputs.py` | R1~R5·R7 통과(HEAD에서 실패를 먼저 보임). 기존 시험 통과. SNP `graph_version` 그대로 |
| U2 split 수락 연결 | 부르는 곳 아홉 군데를 `resolve`로, `apply_saved` 지움, `ai_review._op_for`가 split 후보를 `split` 연산으로, 수락이 작업으로 다시 읽기, 되돌리기의 `dependents`, 이미 있는 split `add_node` 이전 | `hazop/extract/ai_review.py`, `confirmation.py`, `hazop/app/*`, `hazop/shell/*`, `scripts/build_graph.py`, `scripts/check_corrections.py`, `scripts/check_read_quality.py` | 합성 쪽에서 split 후보 수락 → 작업 끝 → 배관 끝이 새 노드에 붙음, 되돌리면 원래 바이트 |
| U3 배관 입력과 '이 선은 배관' | `_take_pipes`·`_ring_headers`를 이름 붙은 고리 분기점과 함께 옮김, `pipe` 적용, `objects_at`, 셸 요청 | `pdf_vector.py`, `corrections.py`, `hazop/shell/api_corrections.py` | R8 통과. 입력 없는 쪽 결과 바이트 같음 |
| U4 화면 | 덩어리 안 상자 그리기, '이 선은 배관', 작업 줄, 대기 덧그림, 적용 불가 표시 | `hazop/shell/web/` | 실제 창 시나리오 |
| U5 고치는 동작 수 지표 | 동작 수 정의를 `check_read_quality.py`의 보고용 값으로(기준값 아님) | `scripts/check_read_quality.py` | 개발용 12쪽 값이 같은 정의로 나옴 |

차례는 U1 → U2 → U3 → U4다. `pdf_vector.py`·`corrections.py`는 U1과 U3이, `api_corrections.py`는 U2와 U3이 함께 쓰므로 동시에 돌리지 않는다(CLAUDE.md 규칙 4).

## 9. 사람이 고치는 데 드는 동작 수

정답지와 스크립트만 추출 결과를 `check_read_quality.py`와 같은 짝짓기로 견주고, 차이를 지금 있는 연산과 이 문서의 새 연산으로 메우는 수를 센다. 연산 하나 = 1동작이다.

| 항목 | 1동작으로 세는 것 |
| --- | --- |
| 종류 | 짝 있는 노드의 종류가 틀리거나 없음 → `set_kind` 1. 짝 없는 정답 기호가 긴 변 100pt 넘는 미분류 노드 안에 있음 → `split` 1(종류 포함). 그 밖의 짝 없는 기호 → `add_node` 1. 영역 안의 짝 없는 종류 있는 노드 → `delete_node` 1 |
| 태그 | 짝 있는 기호(또는 나눈 기호)의 태그가 틀리거나 없음 → `set_tag` 1. `add_node`로 더한 기호의 태그는 0 |
| 연결 | 놓친 정답 쌍. 위 한계 = 쌍마다 `add_relation` 1. 아래 한계 = 놓친 쌍이 이루는 무리마다 1. 나눈 기호가 낀 쌍은 아래 한계에서 0 |
| 흐름 | 맞은 쌍인데 방향이 없거나 틀림 → `set_flow` 1. 새로 이은 쌍의 방향 → 1 |
| 속성 | 정상·고장 위치 틀림 → 1. 배관 번호 틀림 → 관계 `set_tag` 1. 구경·재질·설계압력, 도면 밖 연결의 계통은 연산이 없다 |

개발용 정답지 12쪽(스크립트만, `a766a1d`)에서 정답 단위 4,141개에 동작 517~583, 연산 없음 48건이었다(정답 단위 100개당 12.5~14.1동작). 가장 많이 드는 동작은 종류 바꾸기(143)와 흐름(111)이다. 이 12쪽에는 정답 기호가 큰 덩어리 안에 든 경우가 없어 나누기 효과는 다른 개발용 쪽(134·030쪽 등)에서 나온다. 지표는 개발용 추가 쪽도 함께 내야 한다.

## 10. 막힐 곳

1. **번호 유지의 남은 몫.** 배출구·끝막음처럼 사슬에서 나오는 기호는 그 수가 바뀌면 서로 밀릴 수 있다. 7장에서 재고, 0이 아니면 그 기호의 id를 위치 지문 이름으로 바꿔야 한다. 그 변경은 입력 없는 쪽의 id까지 바꾸므로 기준값 갱신 절차(CLAUDE.md 규칙 12)를 따라야 한다.
2. **원본 PDF와 판.** 다시 추출은 `source.file`의 원본이 있어야 한다. 배포본 묶음의 pdfplumber 판을 고정해야 모양 다시 찾기로 넘어가는 일이 적다.
3. **규칙 판 열쇠.** 기준 추출 열쇠의 `RULES_VERSION`은 규칙을 고칠 때마다 오르지 않는다. 원본 추출의 `extraction_run_id`가 함께 들어가 다시 추출하면 열쇠가 바뀌지만, 앱만 올리고 다시 추출하지 않으면 옛 기준 추출 파일을 그대로 쓴다. (해소: 열쇠에 추출 코드 지문을 넣었다. 코드나 레지스트리가 바뀌면 기준 추출을 다시 만든다.)
4. **큰 쪽의 기다림.** 134쪽 19초. 연달아 수락하면 작업이 한 번 더 도는 것으로 묶지만, 사람이 결과를 보려면 그만큼 기다린다.
5. **AI split 후보의 남은 결함.** 후보 하나를 정하면 덩어리 전체를 다시 묻지 않는 문제(backlog)는 따로 고쳐야 수락 흐름이 쓸모 있다.
6. **합성 묶음의 대표성.** 2.3의 표는 AI 답이 아니라 닿음 묶음으로 잰 것이다.
7. **사용자 자료.** 이미 수락된 split `add_node`가 사용자 작업 루트에 있는지 보지 않았다. U2가 이전 스크립트를 넣고 실제 자료에서 센다.
