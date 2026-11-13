# 쪽 확정 명령과 조건 함수 (엔진 단위, 2026-11-14)

도면 한 쪽(추출 결과 하나)을 사람이 확정할 수 있는지 판정하고, '원본과 견줌'·'쪽 확정' 기록을 저장하는 엔진 부품입니다. 새 화면(`s-frame`, `hazop/shell/api.py`)과 DEXPI 내보내기(`c1-tools`)가 같은 함수를 부릅니다. 근거는 [INTENT §3.2·§3.8](../../../../INTENT.md), [화면 규격 §10.4·§10.5·§10.6·§10.7](../../../design/app-shell-web.md), [DEXPI 규격 §6.1](../../../specs/dexpi-exchange.md)입니다.

- 구현: `hazop/extract/confirmation.py`. 자리는 두 규격이 제안한 그대로입니다. 화면 코드(`hazop/shell/`)와 추출 어댑터는 이 모듈을 부르기만 합니다.
- 저장: `<작업 루트>/data/sheet-confirmations/<이름>.json`(`paths.folder("sheet-confirmations")`).
- 시험: `tests/test_sheet_confirmation.py`.

## 1. 함수

| 함수 | 파일을 쓰나 | 하는 일 |
| --- | --- | --- |
| `confirmation.check(extraction, ai_doc=None, ops=())` | 아니오(순수) | 사람 수정을 반영한 추출 결과에서 `{read_method, unconfirmed, unplaced, counts, leftovers}`를 셉니다. 세는 기준은 여기 하나에만 둡니다 |
| `confirmation.sheet_confirmation(name)` | 아니오 | 세 파일을 한 번씩 읽어 `check`의 답에 지문·견줌·확정 기록과 `state`를 붙입니다. 추출 결과가 없으면 `FileNotFoundError`, 파일이 깨졌으면 `ValueError` |
| `confirmation.load_sheet(name)` | 아니오 | `(sheet_confirmation의 답, 원본 추출 결과, 사람 수정을 반영한 추출 결과)`. 판정과 두 추출 결과가 같은 바이트에서 나옵니다. DEXPI 내보내기가 이 추출 결과로 그래프를 만들어, 확정한 지문과 내보내는 내용이 어긋나지 않게 합니다 |
| `confirmation.execute(name, command, args=None, by=None, fingerprint=None, rev=None)` | 쓰는 명령만 | 상태 읽기·견줌·확정·확정 해제(§3) |
| `confirmation.default_view(read_method, state=None)` | 아니오 | 처음 열 때의 보기 `"clean"`·`"original"`(§4) |
| `confirmation.source_format(extraction)` | 아니오 | 읽은 방법 `drawio`·`dexpi`·`pdf_vector`·`raster`·`unknown`(`clean_items.source_format`과 같은 규칙) |
| `confirmation.leftovers(extraction)` | 아니오 | 원본에 남은 것 `{paths, texts, total, source}` 또는 `None`(엔진이 세지 못함) |

`name`은 추출 폴더 이름(`output/extract/<이름>`)입니다. 사람 수정 기록(`corrections`)과 AI 후보 기록(`ai_review`)이 쓰는 이름과 같습니다.

## 2. `sheet_confirmation(name)`의 답

```python
{
  "name": "...", "read_method": "drawio" | "dexpi" | "pdf_vector" | "raster" | "unknown",
  "state": "open" | "ready" | "confirmed",
  "unconfirmed": [{"id": local_id | None, "reason": 사유 코드, "detail": 추출의 미확인 문구 | 후보 ID | None}],
  "unplaced": [{"id", "kind": "node" | "relation", "tag"}],
  "counts": {사유 코드: 수, ..., "total", "unknowns", "unplaced", "open_ends", "ai_pending"},
  "leftovers": {"paths", "texts", "total", "source"} | None,
  "fingerprint": "sha256:…",                       # 세 파일을 합친 지문
  "files": {"extraction", "edits", "ai_review"},    # 파일별 지문("sha256:…", 없으면 null)
  "compared":  {"by", "at", "fingerprint", "files", "mode", "leftovers_seen"} | None,
  "confirmed": {"by", "at", "fingerprint", "files", "leftovers_seen", "compared_at"} | None,
  "released": [{..풀린 기록.., "what": "compared" | "confirmed", "changed": ["extraction" | "edits" | "ai_review"]}],
  "rev": 확정 기록 판(없으면 0),
  "default_view": "clean" | "original",
  "record_error": 확정 기록이 깨졌으면 그 사유 | None,
}
```

**`state`**

- `open`: 미확인이 있거나, 위치 없는 구성요소가 있거나, 원본에 남은 것을 엔진이 세지 못함(`leftovers` 가 `None`).
- `ready`: 위 셋이 다 되었으나 지금 지문으로 '원본과 견줌'과 '사람의 확정'이 아직.
- `confirmed`: 셋 다(지금 지문과 같은 견줌·확정 기록이 있음).

**미확인(`unconfirmed`)의 범위는 추출 미확인 목록 전체입니다(§10.4).** 사람 수정을 반영한 추출 결과에서 아래를 모두 셉니다. 같은 대상·같은 사유는 한 번, 다른 사유는 따로 셉니다. 위치가 없는 구성요소도 다른 사유를 함께 셉니다. 순서는 도면 안 순서(위→아래, 왼→오른)이고, 위치 없는 것과 쪽 전체 미확인은 끝입니다.

| 사유 코드 | 출처 |
| --- | --- |
| `validation.unknowns`의 `check` 코드 그대로 | 추출의 미확인 기록 전체. `target`이 없으면 `id: null`(쪽 전체) |
| `unresolved_connector` | `unresolved_connectors` 전체 |
| `unknown_symbol` | 노드의 `classification`이 `classified`가 아니거나 `kind`가 빔 |
| `missing_tag` | `category`가 설비·밸브·계기인데 태그가 빔 |
| `open_end` | 관계의 끝 가운데 `status`가 `connected`가 아닌 것이 있음 |
| `ai_candidate` | AI 후보 기록에서 `accepted`·`rejected`가 아닌 후보. 대상이 없는 후보는 `id: null`, `detail`에 후보 ID로 후보마다 한 줄 |
| `unplaced` | 노드: `geometry`도 `label_location.bbox`도 없음. 관계: 끝점·꺾이는 점이 둘 미만 |

**사람이 끝내는 법.** 값을 고치거나(사람 수정 연산, AI 후보 수락·거절) '이대로 확인'을 합니다. '이대로 확인'은 사람 수정 기록의 기존 `confirm` 연산(`corrections.make_op(…, "confirm", target, {"items": [{"check", "reason"}]})`)입니다. 추출의 미확인 기록은 `corrections.apply`가 지금처럼 지우고, 이 판정이 정하는 사유(`unknown_symbol`·`missing_tag`·`open_end`·`unresolved_connector`·`unplaced`)는 적용된 `confirm` 연산의 `items[].check`가 그 코드면 그 대상에서 뺍니다. `ai_candidate`는 수락·거절로만 끝납니다. 대상이 없는 쪽 전체 미확인(`missing_drawing_number` 등)은 `confirm` 연산이 대상을 요구하므로 '이대로 확인'할 수 없고 값을 고쳐야 합니다.

**원본에 남은 것(`leftovers`, §10.5)**

| 읽은 방법 | 값 |
| --- | --- |
| 추출 결과에 `leftovers`(`{"paths": [...], "texts": [...]}`)가 있음 | 그 수(`source: "extraction"`). `kind: "frame"`인 경로(도면 테두리·표제란 칸)는 `total`에서 빼고 `frame`에 셈 |
| `drawio` | 분류하지 못한 셀(`unclassified`) 수(`source: "drawio_unclassified"`). 작성자가 일부러 뺀 셀(`drawing.ignored_objects`)은 `frame`에 따로 세고 `total`에서 뺌(정리된 보기와 같음) |
| `dexpi` | 0(`source: "dexpi_no_drawing"`). 원본 그림이 없고, 대응표에 없는 클래스는 미분류 노드와 미확인 `dexpi_unmapped_class`로 들어와 미확인으로 셈 |
| `pdf_vector`(필드 없음), `raster`, `unknown` | `None`. 이 쪽은 확정할 수 없음 |

남은 것이 0이 아니어도 확정을 막지는 않습니다. 견줌·확정 기록에 그때의 수(`leftovers_seen`)가 남습니다.

**지문.** 세 파일의 내용 지문(`sha256`, 없으면 `null`)을 파일별로 두고 합친 값을 `fingerprint`로 씁니다. 판정과 지문은 같은 바이트에서 나옵니다(한 번 읽음).

| 열쇠 | 파일 | 바뀌는 때 |
| --- | --- | --- |
| `extraction` | `output/extract/<이름>/extraction.json` | 다시 추출 |
| `edits` | `data/drawing-edits/<이름>.json` | 사람 수정, '이대로 확인', AI 후보 수락(수정 기록을 씀) |
| `ai_review` | `data/ai-review/<이름>.json` | 후보 추가·수락·거절 |

셋 가운데 하나라도 바뀌면 견줌·확정이 함께 풀립니다. 풀린 기록은 지우지 않습니다. 상태 읽기의 `released`에 무엇이 바뀌었는지(`changed`)와 함께 보이고, 그 뒤 처음 쓰는 명령이 기록의 `log`에 `{"action": "released", "what", "changed", "record"}`로 옮겨 남깁니다. 확정 기록 파일은 세 파일 밖에 있으므로 확정을 써도 지문은 바뀌지 않습니다.

## 3. 명령 `execute(name, command, args, by, fingerprint, rev)`

돌려주는 값은 모든 명령이 `{ok, command, changed, rev, status, refused: [{target, code, reason}]}`입니다. `status`는 실행 뒤 `sheet_confirmation`의 답입니다(거절이어도 지금 상태를 담아, 화면이 남은 것을 바로 보일 수 있음). `ok: false`면 아무것도 쓰지 않은 것입니다. 바뀐 것이 없으면(이미 확정, 같은 방식으로 이미 견줌, 풀 것이 없음) 쓰지 않고 `changed: false`입니다.

| 명령 | 인자 | 하는 일 | 거절(주요) |
| --- | --- | --- | --- |
| `status` | — | 읽기만 | 쪽 자료를 읽을 수 없음 |
| `compare` | `mode`(`side_by_side` 기본·`overlay`·`dexpi_list`) | '원본과 견줌' 기록 `{by, at, fingerprint, files, mode, leftovers_seen}`. 견주기 화면의 체크 상자를 켤 때 부름 | 사람 이름 없음 · 미확인·위치 없음·남은 것을 세지 못함(남은 것을 사유별 수와 함께) · 지문·판 다름 · 모르는 방식 |
| `confirm` | — | 쪽 확정 기록 `{by, at, fingerprint, files, leftovers_seen, compared_at}`. 견주기 화면의 '이 쪽 확정' | 위와 같음 · 지금 지문의 견줌 기록 없음 |
| `unconfirm` | `reason`(선택) | 견줌·확정을 함께 풂. 사유는 `log`에 남음 | 사람 이름 없음 · 지문·판 다름 |

- **`by`·`at`.** 쓰는 명령은 `by`(사람 이름)가 있어야 합니다. `at`은 엔진이 채웁니다(UTC).
- **낡은 판.** `fingerprint`(화면이 본 세 파일 지문)와 `rev`(화면이 본 확정 기록 판)를 넘기면 지금 값과 대조해 다르면 `stale`로 거절합니다. `None`은 대조하지 않음(시험용)입니다. 견주기 화면은 열 때 받은 `status.fingerprint`·`status.rev`를 그대로 넘깁니다.
- **원자적 쓰기.** 기록은 `store_io.write_json(…, expect=읽은 지문)`으로 씁니다. 그 사이 다른 창이 기록을 바꿨으면 `conflict`.
- **깨진 기록.** 기록 파일의 JSON이 깨졌거나 값이 틀리면(예: `compared`가 객체가 아님) 예외로 멈추지 않습니다. 그 쪽은 확정되지 않은 것으로 보고 상태 읽기의 `record_error`에 사유를 보입니다. 견줌·확정은 `unreadable`로 거절하고, 확정 해제(`unconfirm`)가 새 기록을 씁니다(`log`에 `reset_bad_record`). 다른 종류의 파일이거나 이 앱이 모르는 판이면 덮지 않도록 `unreadable`로 거절합니다.
- **거절 `code`.** `unknown_command` · `bad_actor`(이름 없음) · `stale` · `conflict` · `unreadable`(추출 결과 없음·파일 깨짐) · `rule`(조건 미충족; `target`은 `unconfirmed`·`unplaced`·`leftovers`·`compared`·`mode`) · `io`(기록을 쓰지 못함). 구간·결과 명령과 같은 갈래입니다.

기록 파일의 꼴:

```json
{"kind": "hazop_sheet_confirmation", "schema_version": "0.1", "extraction_name": "...", "rev": 2,
 "compared": {...} , "confirmed": {...},
 "log": [{"at", "by", "action": "compare" | "confirm" | "unconfirm" | "released", "fingerprint", ...}]}
```

## 4. 기본 보기 `default_view(read_method, state)`

| 읽은 방법 | `state` | 처음 열 때 |
| --- | --- | --- |
| `drawio`, `dexpi` | 무엇이든 | `clean` |
| `pdf_vector`, `raster` | `confirmed` | `clean` |
| `pdf_vector`, `raster` | 그 밖 | `original` |
| `unknown`·빈 값·모르는 값 | 무엇이든 | `original` |

`sheet_confirmation`의 답에 `default_view`가 들어 있습니다.

## 5. 부르는 쪽에 넘길 일

- **새 화면(`s-frame`, `hazop/shell/api.py`).** 상태 읽기·견줌·확정·확정 해제를 `confirmation.execute`로 잇습니다. 칩과 견주기 화면은 `status.counts`·`status.unconfirmed`·`status.leftovers`·`status.state`를 씁니다.
- **정리된 보기(`s-viewer`, `hazop/shell/clean_items.py`).** `unconfirmed`·`counts`·`unplaced`·`leftovers`를 직접 세는 대신 `confirmation.check(corrected, ai_doc, ops)`를 부르고, 화면 좌표(오프셋을 뺀 상자)만 그쪽에서 더하는 것을 권합니다. 지금 가상 도면 SNP 6장에서는 두 쪽의 `(대상, 사유)` 목록과 순서가 같습니다(시험 `test_counts_match_the_clean_view_on_all_snp_sheets`). 다른 점은 셋입니다. ① 위치 없는 노드·관계의 다른 사유(분류 안 됨·태그 없음·열린 끝)도 셉니다(`clean_items`는 위치가 없으면 `unplaced`만 셈). ② 대상이 없는 AI 후보도 셉니다. ③ `confirm` 연산의 '이대로 확인'을 반영합니다.
- **DEXPI 내보내기(`c1-tools`).** 쓰기 직전에 `confirmation.sheet_confirmation(name)["state"] == "confirmed"`인 쪽만 냅니다. DEXPI 규격 §6.1은 함수 서명을 `sheet_confirmation(extraction, review_log)`로 적었으나, 지문과 기록이 파일에 매이므로 `sheet_confirmation(name)`으로 했습니다. 순수 판정은 `check(extraction, ai_doc, ops)`입니다. 또 DEXPI 규격 §6.2는 '쪽 확정을 막지 않는 속성 미확인(흐름 방향, `missing_port` 등)'이 확정된 쪽에 남을 수 있다고 적었지만, 화면 규격 §10.4 개정판(미확인 전체)대로 이 함수는 모든 미확인을 막습니다. 확정된 쪽에는 사람이 고치거나 '이대로 확인'한 것만 남으므로, 내보내기의 '속성만 빼고 냄' 길은 확정된 쪽에서는 쓰이지 않습니다.
- **PDF 추출(`r3b-read-quality`).** PDF 쪽은 추출 결과에 `leftovers`가 없어 지금은 확정할 수 없습니다(`leftovers: None`). 필요한 값의 꼴은 화면 규격 §10.5 '엔진에 필요한 것' 그대로입니다: `{"paths": [{"bbox", "pts" 또는 "d", "kind"}], "texts": [local_id …]}`. 이 함수는 두 목록의 길이만 셉니다.
- **연결점 어긋남(`port_gap`, §10.2).** 기호를 맞춘 그리기에서 생기는 틈이라 그래프·DEXPI 자료를 바꾸지 않고, 엔진은 기호 그림의 연결점을 모릅니다. 그래서 쪽 확정 조건에 넣지 않고 정리된 보기에서만 셉니다(화면 규격 §10.4를 이렇게 고침, 2026-11-14).
- **DEXPI 내보내기의 낡은 그래프(검토 R1).** 내보내기는 `load_sheet`가 준 추출 결과로 그래프를 그 자리에서 만들고, 쓰기 직전에 지문을 다시 봅니다. 자세한 것은 [dexpi-commands.md](dexpi-commands.md) §2.
