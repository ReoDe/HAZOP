# 자동 확정 설계(C0): 올리면 읽고, AI가 메우고, 지식그래프에 들어가기

- 작성: 자동 확정 설계 하위 세션(poteto-mode), 2026-11-25(같은 날 검토 지적을 반영한 개정). 코드 기준은 `feat/drawing-knowledge`의 46b973ac. 코드는 고치지 않았다. 아래 행 번호는 모두 이 커밋의 것이다.
- 근거: `INTENT.md` §3.8 끝 '화면 단순화(사용자 결정 2026-11-25)'. 읽기 정확도를 올리는 단위는 다시 열지 않는다(사용자 결정 2026-11-23).
- 앞선 자료: [쪽 확정 명령](sheet-commands.md), [표제란 명령](titleblock-commands.md), [시트 정체](sheet-identity-design.md), [이름 바뀜 잇기](sheet-rename-design.md), [입력 연산](fix-input-ops-design.md), [판 이전](migration-map-design.md), [그림 입력 실측](ai-image-review.md), [읽기 품질 기록](read-quality-log.md)
- 표시: 값 옆의 '실측'은 이 단위에서 돌려 본 것, '기록'은 앞선 문서의 값, '추정'은 확인하지 않은 것이다.

## 0. 결론

1. 지식그래프에 들어가는 길은 지금도 사람 확정을 기다리지 않는다. 추출이 끝나면 그래프와 지식그래프를 바로 짓는다(`hazop/app/data.py` 336, 489). 구간·분석·초기사건도 쪽 확정을 보지 않는다. 쪽 확정을 조건으로 거는 곳은 **DEXPI 내보내기, 정리 보기 기본값, 안내 줄, 채팅 동작 둘**이다(7장 전수 표).
2. 그래서 새로 만들 것은 세 가지다. 추출에 이어 AI 검토를 돌리고 확실한 후보를 수락하는 흐름, 그 결과를 사람 확정과 가르는 표시, 그 표시를 구성요소와 결과물까지 남기는 일이다.
3. 사람 확정(`state`)은 손대지 않고 **확정 수준(`level`)** 을 따로 둔다. 값은 `human`(사람 확정), `auto`(자동 확정), `extracted`(추출만 됨) 셋이다. `auto`는 늘 '미확인 n곳, 자동 수락 m건'과 함께 보인다.
4. 자동 수락은 **표준 기호 판으로 물은 그림 입력의 종류·태그 후보 가운데 확신도 0.70 이상**부터 시작한다. 지금 코드의 표준 판으로 잰 값은 개발용 네 쪽에서 종류 42/44, 태그 8/8뿐이다(4장). 근거가 얇으므로 켜기 전에 총괄이 처음 보는 쪽에서 통과·실패를 한 번 판정한다.
5. 위치(NO·FC 등), 연결, 덩어리 나누기, 다시 확인, 글 입력은 문턱을 정할 자료가 모자라 자동으로 받지 않는다. 글 입력은 받지 않을 것이므로 **부르지도 않는다**.
6. 번호가 **빈** 쪽은 내용을 자동 확정하고 번호만 미확정으로 두기를 권한다(총괄 권장안과 다름, P7). 번호가 **겹친** 쪽은 총괄 권장안대로 자동 확정하지 않고 채팅으로 묻는다(P8).
7. 지금 그대로 자동 실행을 켜면 상한이 새는 곳이 셋이다. 실행당 300회가 파일마다 따로 세이고, 도면당 20회가 실행마다 새로 세이고, 번호를 확정할 때마다 같은 도면을 다시 묻는다(8장).
8. 사용자 확인이 필요한 것이 있다. 올리는 즉시 도면 조각을 AI로 보내는 일(9장)과, '확정된 쪽만 DEXPI로 낸다'는 결정(DEC-0311)을 바꾸는 일(P14)이다.

## 1. 지금 코드가 하는 일

| 사실 | 자리 | 확인 |
| --- | --- | --- |
| 쪽 확정은 미확인 0, 위치 없음 0, 원본에 남은 것을 셈, 지금 지문의 견줌 기록을 모두 요구한다 | `hazop/extract/confirmation.py` 338, 349, 384, 440 | 코드 |
| 가상 도면 SNP-M-401(drawio)도 미확인 5곳(`missing_port` 4, `not_registered` 1)이 남아 확정되지 않는다 | `confirmation.execute`를 직접 돌림 | 실측 |
| 확정 지문은 추출 결과·수정 기록·AI 후보 세 파일과 기준 추출 열쇠다. 하나라도 바뀌면 풀린다 | `confirmation.py` 254, 330, 348 | 코드 |
| 모르는 판의 확정 기록은 읽지 않고 오류를 낸다. 값이 깨진 기록은 빈 기록으로 보고, 확정 해제가 새 기록으로 덮는다 | `confirmation.py` 321, 325, 431 | 실측 |
| AI 수락은 수정 기록에 연산을 넣고 `origin: ai`, `by`, `accepted_by`를 적는다. 사람이 고친 자리는 덮지 않는다 | `hazop/extract/ai_review.py` 1027, 1046, 1067 | 실측 |
| 그래프는 AI 수락 연산이 닿은 것도 모두 `origin: human_edit`로 적는다 | `hazop/graph/build.py` 67 | 실측 |
| 지식그래프의 도면 주장은 AI 수락 값도 `method: manual`, 지식 상태 `confirmed`로 적는다 | `hazop/kg/claims.py` 70~74 | 코드 |
| 범례판 견본은 AI 수락 종류를 사람이 정한 종류로 본다 | `hazop/extract/ai_images.py` 274~285 | 실측(AI 수락 노드가 견본에 들어감) |
| 앱의 범례판은 보통 프로젝트 판이다. 사전 견본에 맞은 기호가 한 자리만 있어도 표준 판을 쓰지 않는다 | `ai_images.py` 274, 345, 405, `ai_image_flow.py` 154, 159 | 실측(개발용 5쪽 모두 `project+symbols`) |
| `match`(높음·보통)는 종류 후보에만 붙는다 | `ai_review.py` 580~583 | 코드 |
| 벡터 PDF 추출은 원본에 남은 것을 내지 않아 사람 확정이 될 수 없다 | `confirmation.py` 134, 338, 394 | 실측(SNP-M-101 PDF, 개발용 5쪽 모두 `None`) |
| 번호를 확정하면 추출 파일 지문과 `extraction_run_id`가 바뀌지만 기호·배관·글자는 같다. 확정 기록은 새 이름으로 옮겨지지 않는다 | `pdf_vector.py` 4395, `titleblock.py` 684 | 실측(SNP-M-101 PDF) |
| 번호가 밀린 추출에서 사람 고침 자리에 AI 수락이 들어간다 | `ai_review.py` 740, 1039 | 실측 |
| 추출 뒤 자동 AI 검토는 설정 `extract_ai_review`가 켜졌을 때만 돌고, 후보만 만들고 수락하지 않는다 | `register_flow.py` 41~79 | 코드 |
| 그림 입력은 종류·태그만 묻는다. 연결 묻기는 앱에서 꺼져 있다(`connect` 기본 0) | `ai_review.py` 381, 644, `ai_image_flow.py` 207 | 코드 |
| 다시 찾기. 연산은 바탕 지문으로 번호가 밀려도 따라가지만, 후보(`cand_id`)는 순번 id(`pdf-p0-sym-…`)라 다시 추출하면 다른 기호를 가리킬 수 있다 | `hazop/extract/corrections.py` 678, 699, `ai_review.py` 433 | 코드 |

**이번에 찾은 기존 결함.** `hazop/shell/api_corrections.py` 217과 403이 `sheet_confirmation(name)["status"]`를 읽는다. 그 답에는 `status`가 없고 `state`만 있어 늘 `None`이다(실측). 그래서 도면 고치기 확인 글의 '쪽 확정이 풀릴 수 있습니다'(`hazop/shell/chat_edits.py` 249, 368)가 한 번도 나오지 않는다. C1이 이 자리를 `level`로 바꾸면서 함께 고친다.

## 2. 상태: 확정 수준을 따로 둔다

### 2.1 두 안

| 안 | 내용 | 판단 |
| --- | --- | --- |
| A | `state`에 값 `auto`를 더한다(open·ready·auto·confirmed) | 버린다. 자동 확정된 쪽이 `ready`를 잃어 채팅의 사람 확정(`hazop/chat/actions.py` 644)과 확정 칩(`hazop/shell/web/js/sheet_confirm.js` 101~103)이 사람 확정을 막는다. `state`를 읽는 모든 곳이 새 값을 알아야 한다 |
| B | `state`는 그대로 두고 `level`(human·auto·extracted)을 더한다 | 권장. `level`을 모르는 코드는 지금처럼 움직인다. 자동을 받을 곳만 `level`을 본다 |

### 2.2 저장 꼴

`data/sheet-confirmations/<이름>.json`(판 0.1 그대로)에 칸 `auto` 하나를 더한다. 사람 확정 칸(`compared`·`confirmed`)과 섞지 않는다.

```json
"auto": {"result": "confirmed | waiting | reverted", "by": "hazop:auto", "at": "…", "policy": "auto-1",
         "read_key": "rk-…", "why": null, "attempts": 1,
         "ai": {"calls": 9, "left": 4, "status": "done | capped | none"},
         "accepted": 12, "unconfirmed": 31}
```

- **`read_key`는 읽은 내용의 열쇠다.** 원본 PDF의 sha256, 쪽 번호, 추출기 판(`run.script_version`), 규칙 판(`run.rules_version`), 기호 자리 목록(`source_object_id`, 반올림한 상자, 추출 종류·태그)을 묶는다. 추출 결과 파일의 지문을 쓰지 않는다. 번호를 확정하면 파일 지문과 `extraction_run_id`가 바뀌지만 기호·배관·글자는 그대로이기 때문이다(실측, SNP-M-101 벡터 PDF: `nodes`·`relations`·`unresolved_connectors`·`texts` 같음, 다른 `source` 칸은 `registration_version`뿐).
- 수정 기록과 AI 후보가 바뀌어도 풀리지 않는다. 자동 확정은 '이 읽기에 스크립트와 AI가 한 번 다 돌았다'는 뜻이지 내용을 보증하는 말이 아니다. 내용은 미확인 수와 자동 수락 수로 말하고, 두 수는 읽을 때마다 다시 센다.
- `level` 계산은 한 함수다. `state == "confirmed"`이면 `human`. 아니면 `auto.result == "confirmed"`이고 `read_key`가 지금 값과 같고 **추출 검증이 `passed`이고 구성요소가 하나 이상**이면 `auto`. 나머지는 `extracted`.
- 검증과 구성요소 수를 조건에 넣는 까닭: 구성요소 0개이고 검증이 `blocked`인 쪽도 지금 `check()`로는 미확인 0곳이다(실측). 이 조건이 없으면 빈 쪽이 '자동 확정(미확인 0)'이 된다.
- 미확인 n은 **서로 다른 대상 수 + 대상 없는 미확인 줄 수**다. 지금 세는 법은 두 곳이 어긋난다. 한 기호를 '종류 미정'과 'AI 후보 남음'으로 두 번 세고(`confirmation.py` 186, 211), 대상 없는 줄은 같은 사유끼리 하나로 뭉친다(217, 실측: `not_registered` 세 줄이 1로 셈). 앞의 것은 대상으로 묶고 뒤의 것은 원래 줄 수로 센다. 묶을 때 id를 하나로 맞춘다. 지금 AI 후보 줄의 id는 `source_object_id`이고 나머지 줄은 `local_id`라(211, 실측: 같은 기호가 `pdf-p0-sym-0001`과 `local-node-001` 두 id로 나옴) 그대로 묶으면 여전히 둘로 세인다. 정리 보기의 AI 후보 표시가 나오지 않는 것도 같은 어긋남이다(`hazop/shell/clean_items.py` 102, 141, 실측 0건).
- n 옆에 '원본에 남은 것'을 함께 보인다. drawio·DEXPI는 수, **벡터 PDF와 스캔은 '셀 수 없음'** 이다. 벡터 PDF 추출은 지금 `leftovers`를 내지 않는다(실측: SNP-M-101 PDF와 개발용 다섯 쪽 모두 `None`). 그래서 벡터 PDF 쪽은 지금 사람 확정도 될 수 없다(`confirmation.py` 338, 394).

### 2.3 상태 전이

| 지금 수준 | 사건 | 다음 수준 | 하는 일 |
| --- | --- | --- | --- |
| (없음) | 새 자료 등록, 추출 성공 | extracted | `waiting, why=started`를 먼저 적는다. 중간에 앱이 꺼져도 끝나지 않은 쪽으로 알아본다 |
| extracted | 물을 곳에 모두 답을 받음(물을 곳 없음 포함) | auto | 후보 저장 → 수락 → 기록. 수락은 이때 한 번에 한다 |
| extracted | 자료 누적 상한 20회에 닿아 남은 곳이 있음 | auto | `ai.status=capped`. 남은 것은 미확인 |
| extracted | 일부 호출만 실패(남은 곳 있음, 상한 전), 자동 시도 3번 미만 | extracted | `waiting(error)`. 받은 후보는 저장하고 수락은 하지 않음. 이어 하기 대상 |
| extracted | 같은 실패가 3번째 | extracted | `waiting(error_final)`. 저절로 다시 부르지 않음. 채팅으로 시킬 때만 |
| extracted | 연결 없음·사용 한도·멈춤·실행당 상한 | extracted | `waiting(no_connection·limit·stopped·run_cap)`. 시도 횟수에 넣지 않음 |
| extracted | 번호가 다른 자료와 겹침 | extracted | `waiting(taken)`. AI를 부르지 않고 채팅으로 어느 파일을 쓸지 묻는다 |
| extracted | drawio·DEXPI(글 입력만 되는 도면) | auto | AI를 부르지 않음. `ai.status=none` |
| extracted | 스캔 | extracted | `waiting(scan)`. 자동으로 부르지 않음(P6) |
| auto | 채팅 고침, 실행 취소, 후보 수락·거절 | auto | n과 m만 바뀐다 |
| auto | 번호 확정으로 다시 추출(`read_key` 같음) | auto | 기록을 새 이름으로 옮김(2.5). AI를 다시 부르지 않음 |
| auto | 규칙·추출기가 바뀐 다시 추출(`read_key` 다름) | extracted | 수정 기록과 수락은 남음. 자료 누적 상한 안에서 이어 하기 |
| auto | 이 도면의 자동 수락 되돌리기 | extracted | `reverted`와 한 사람. 다시 추출·번호 확정 뒤에도 남고, 사람이 다시 시키기 전에는 저절로 돌지 않음 |
| auto·extracted | 사람 확정(견줌 + 확정) | human | 지금 명령 그대로 |
| human | 세 파일 가운데 하나가 바뀜, 사람 확정 해제 | auto 또는 extracted | 자동 기록이 유효한지로 정함 |

### 2.4 옛 앱·옛 자료와의 호환(실제로 돌려 봄)

옛 앱이 새 파일을 잘못 다뤄 잃는 일이 있는지 46b973ac 코드를 옛 앱 구실로 돌렸다(임시 작업 루트, SNP 한 장).

| 확인 | 결과 |
| --- | --- |
| `auto` 칸이 든 기록을 옛 코드가 읽음 | 오류 없음. 상태는 open. 자동을 사람 확정으로 보지 않음 |
| 옛 코드가 견줌·확정·해제를 씀 | `auto` 칸이 그대로 남음 |
| 값이 깨진 기록을 옛 코드가 해제 | `auto` 칸이 사라짐. 그 쪽은 extracted로 내려감(덜 확정되는 쪽이라 받아들임) |
| 옛 코드가 번호를 확정해 새 이름으로 다시 추출 | 새 이름에 확정 기록이 없음(실측). 그 쪽은 기록이 없는 옛 쪽과 같아져 저절로 돌지 않음. 되돌린 표시는 잃지만 다시 자동 수락되지도 않음 |
| 기록 판을 0.2로 올림 | 옛 코드가 `ValueError`. 그 쪽을 내보내지도 확정하지도 못함 → **판을 올리지 않는다** |
| `by: hazop:auto`로 수락한 연산을 옛 코드가 되돌리고 사람이 다시 수락 | 같은 `op_id`로 되살고 `by`·`accepted_by`가 사람으로 바뀜 |
| 사람이 고친 자리에 자동 수락 | 번호가 그대로면 거절. **번호가 밀리면 막지 못함**(4.4) |

자동 표시를 새 칸이 아니라 **`by`·`accepted_by`의 예약 값 `hazop:auto`** 에 싣는 까닭도 여기 있다. 두 칸은 이미 누가·언제 칸(`corrections.py` 127 `PROVENANCE`)이라 되살리기 규칙이 그대로 통한다. 연산에 새 칸을 넣으면 옛 앱이 되돌렸다 되살릴 때 사람 수락에도 그 칸이 남는다(`ai_review.py` 1001, 코드).

예약 이름은 사람 이름으로 들어올 수 있는 모든 자리에서 거절한다. 검토자 설정(`hazop/shell/api.py` 533), `corrections.save_fp`·`make_op`, `ai_review.accept`·`reject`·`revert`, `confirmation.execute`, `registry.register`·`clear_metadata`, `titleblock.confirm`의 사람 경로다. 이미 저장된 검토자 이름이 `hazop:`로 시작하면 앱을 열 때 비우고 다시 묻는다.

판 이전 §21의 교훈(옛 앱이 새 꼴을 '모르는 줄'로 보고 잃은 것으로 굳힘)은 이 설계에 걸리지 않는다. 검토구간·판 이전 파일의 꼴은 바꾸지 않는다. 다만 그래프 노드에 자동 표시를 더하면(5장) 자동 연산이 있는 쪽의 `graph_version`이 옛 앱과 새 앱에서 다르다. 앱을 오가면 그 쪽의 판 이전이 한 번 더 돌지만 구성요소 id는 같다(추정, C1 시험에 넣음).

### 2.5 번호 확정 때 기록 옮기기

지금 번호 확정은 수정 기록과 AI 후보만 새 이름으로 옮긴다(`titleblock.py` 684 `_carry`). 확정 기록은 옮기지 않는다(실측). 그대로 두면 사람이 되돌린 쪽이 번호 확정 뒤 다시 자동 수락된다. `_carry`가 `auto` 칸도 옮긴다. 사람 확정 칸은 지금처럼 옮기지 않는다(새 추출을 사람이 다시 보는 것이 옳다). 새 이름에 이미 `auto`가 있으면 `reverted`가 이기고, 아니면 나중 것이 이긴다.

## 3. 흐름(C1 엔진, C2 셸)

```
등록(registry.register)
  → 표제란 번호 자동 확정(비지 않고 겹치지 않을 때만, 6장). 새 등록 파일 경로를 받는다
  → 추출·그래프·지식그래프(data.extract_and_graph(그 경로))
  → 확정 기록 waiting
  → AI 차례(engine.ai_turn)에서 도면마다 묻기(ai_image_flow.run_pages, 표준 판 고정)
  → 도면마다: 자동 수락(ai_review.auto_accept) → 확정 기록(confirmation.record_auto)
  → 그래프 다시 짓기는 api_inputs.note로 모아서
```

단계마다 지금 있는 자료를 보고 할 일을 정한다(다시 돌려도 같은 끝).

- **새 등록 파일을 쓴다.** 지금 `register_flow.py` 34는 `register()`가 준 1판 경로로 추출한다. 번호를 확정하면 2판이 생기는데 `registry.load_for_extraction`(658)은 옛 판을 거절하지 않아, 1판으로 추출한 결과에는 번호가 없다(실측: 확정 판 2, 추출 판 1, 번호 없음). `auto_confirm_number`가 쓸 등록 파일 경로를 돌려주고 시험이 '추출 결과의 번호 = 확정 번호'를 묶는다.
- **다시 묻지 않는다.** 실행 기록(`runs[]`)에 `read_key`를 적고 같은 열쇠로 끝난 실행이 있으면 부르지 않는다. 지금은 실행 시각과 추출 파일 시각만 견줘(`hazop/shell/api_aireview.py` 269 `_after_extract`) 다시 추출하면 늘 '하지 않음'이 된다.

엔진 쪽 함수(서명만, 본문은 C1):

```python
# hazop/extract/confirmation.py
AUTO_BY = "hazop:auto"
def read_key(extraction): ...
def level(status): ...                       # "human" | "auto" | "extracted"
def record_auto(name, result, why=None, ai=None, accepted=0): ...   # 같은 값이면 쓰지 않음, store_io expect로 경합 거절
def carry_auto(old_name, new_name): ...      # titleblock._carry가 부름

# hazop/extract/ai_review.py
AUTO_KIND_MIN = AUTO_TAG_MIN = 0.70
def protected_targets(name, resolved): ...   # 사람 고침·결정 자리를 지금 id로 옮긴 집합(4.4)
def auto_block(c, corrected, protected, pending): ...  # 자동으로 받지 않을 까닭 또는 None(순수 함수)
def auto_accept(name, original_ex): ...      # 잠금 안에서 부름 → {"accepted": [...], "blocked": {까닭: 수}}
def auto_revert(name, by, confirm=None): ...

# hazop/register/titleblock.py
def auto_confirm_number(project_id, material_id): ...
# → {"registration_file": 경로, "confirmed": bool, "why": None|empty|taken|multi_page|reserved|has_records}
```

`auto_accept`는 고르기만 하고 수락은 `accept()`가 한다. 수락 규칙이 두 벌이 되지 않게 하려는 것이다.

### 3.1 AI 차례, 입력 연산 짓기 미루기와의 관계

- AI 차례(`hazop/shell/ai_gate.py`)는 한 번에 하나다. 자동 확정은 지금 추출 뒤 자동 검토와 같은 차례를 쓰고, 같은 스레드에서 다시 잡지 않는다(`Reentry`).
- 자동 수락은 나누기(`split`)를 받지 않으므로 기준 추출 짓기(`corrections.ensure_base`)가 필요 없다. 그래프 다시 짓기는 수락과 같은 길인 `api_inputs.note`(마지막 수락 뒤 10초 조용하면 도면마다 한 번)에 맡긴다. `note`는 낡은 그래프 표시를 디스크에 남기므로(`hazop/shell/sheet_refresh.py` 34 `defer`) 앱이 꺼져도 다음 열기에서 다시 짓는다.
- 여러 쪽을 잇달아 끝낼 때 쪽마다 짓지 않는다. APR1400 143쪽에서 저장 한 번의 판 이전이 3초 남짓(기록, 판 이전 §21, 구간 525개)이라, 쪽마다 지으면 그 시간이 쪽 수만큼 는다.
- 잠금 차례는 AI 차례 → 도면 잠금(`sheet_refresh.lock`) 한 방향만 쓴다. 도면 잠금을 쥔 채 AI 차례를 기다리지 않는다.

## 4. 자동 수락 규칙과 채점

### 4.1 범례판부터 정한다

AI에 싣는 범례판은 셋이다. 어느 판으로 물었는지에 따라 확신도의 눈금이 다르다(4.2).

| 판 | 앱에서 쓰는가 | 저장된 응답 |
| --- | --- | --- |
| 표준 기호 판(`symbols`, 변형 칸 든 새 판) | 프로젝트 도면에 견본이 하나도 없을 때만 | 개발용 5쪽(007·019·099·133·134), @ef93f20 응답 |
| 프로젝트 판(`project+symbols`) | **지금 앱의 보통 조건.** 사전 견본에 맞은 기호(`symbol:`)가 한 자리만 있어도 이 판이 된다(`ai_images.py` 274, 345, 405). 개발용 5쪽은 5쪽 모두 해당한다(실측: 견본 자리 3~78곳) | 없음 |
| 옛 표준 판(변형 칸 없음) | 쓰지 않음. 지금 코드에 없다 | 나머지 개발용 쪽, @a2c1442 응답 |

**자동 경로는 `drawings=()`로 물어 표준 기호 판에 고정한다.** 후보마다 `input`(image·text)과 `legend_source`를 저장하고, `legend_source`가 `symbols`가 아니면 수락하지 않는다. 표준 판의 저장 응답은 지금 코드가 그대로 다시 쓴다. 46b973ac에서 5쪽을 고정 응답으로 돌려 오류 0, 후보 147건이 저장본과 모두 같았다(실측). 프로젝트 판으로 재려면 구독 호출이 필요하므로 C1의 선택지로 둔다(P18).

### 4.2 값(실측, 구독 호출 0)

추출은 46b973ac의 `pdf_vector`, 정답지는 저장소 밖 추가 정답지의 개발용 쪽(`keys-dev`·`keys-dev2`), 짝짓기는 `scripts/check_read_quality.py`의 `match_symbols`다. 후보를 하나씩 적용해 맞은 수를 셌다. **보류 6쪽은 열지도 채점에 넣지도 않았다.** 빼 둔 것은 정답지 영역 밖 후보(새 판 1건, 정답지 판 2건)와, 추출이 달라져 상자가 어긋난 141쪽 후보 36건(옛 판)이다. 정답지 판의 141쪽은 재생 오류라 처음부터 없다.

| 확신도 | 새 표준 판 5쪽(문턱의 근거) | 옛 표준 판 나머지 쪽(참고) | 정답지 판(참고, 앱에 없는 조건) |
| --- | --- | --- | --- |
| 0.80 이상 | 27/28 | 7/7 | 75/78 |
| 0.70~0.80 | 15/16 | 35/36 | 22/25 |
| 0.60~0.70 | 6/6 | 13/13 | 15/22 |
| 0.50~0.60 | 6/17 | 7/10 | 18/19 |
| 0.50 미만 | 21/31 | 4/17 | 6/14 |
| **0.70 이상** | **42/44** | 42/43 | 97/103 |

문턱 0.70의 근거는 새 표준 판 값뿐이다. 그 값은 이렇게 모자란다.

- 0.70 이상인 후보 44건은 네 쪽에서 나왔고(007 2/2, 019 18/20, 099 8/8, 134 14/14) 133쪽에서는 하나도 나오지 않았다. 019·099·134쪽에 몰려 있다.
- 묶음을 무시한 Wilson 95% 하한은 85%다. 쪽을 다시 뽑은 부트스트랩(10,000번, 2.5분위)의 하한은 91%지만 쪽이 넷뿐이라 이 구간 자체를 믿기 어렵다. 옛 판까지 합친 84/87(7쪽, 077·080쪽이 40건)의 부트스트랩 하한도 91%다.
- **문턱과 4.3의 규칙을 같은 자료에서 골랐다.** 프롬프트와 범례판도 이 쪽들을 보며 고쳤다. 처음 보는 도면에서는 낮아질 수 있다.
- 0.60이 아니라 0.70인 까닭: 새 판 0.60~0.70은 6건뿐이고 0.50~0.60에서 6/17로 떨어진다. 정답지 판에서는 0.60~0.70이 15/22다. 판에 따라 떨어지는 자리가 움직이므로 한 칸 위를 잡는다.

| 과제(새 표준 판 5쪽) | 0.70 이상 | 전체 | 판단 |
| --- | --- | --- | --- |
| 종류 | 42/44 | 75/98 | 자동 |
| 태그 | 8/8(019·099·134쪽) | 22/22 | 자동. 자료가 적다 |
| 다시 확인 | 15/15 | 19/19 | 받지 않음. 019쪽 manual_valve → damper 한 꼴뿐이고 추출과 모순인 값 |
| 정상 위치 | 6/6 | 6/6 | 받지 않음. 019쪽에서만 나옴 |
| 고장 위치 | 1/1 | 1/1(옛 판까지 3/4) | 받지 않음. 틀리면 고장 시 열림·닫힘이 뒤집혀 원인·결과가 바뀐다 |
| 연결, 종류, 태그(글 입력, 012·063쪽 @dd86ea4) | 자료 없음(확신도가 저장되지 않음) | 연결 18 가운데 새 정답 쌍 5, 종류 29/32, 태그 8/9 | 부르지 않음 |

'높음'(범례 견본과 같다고 답함) 표시는 문턱으로 쓰지 않는다. 새 판 0.70 이상에서 높음 35/37, 보통 7/7이라 더 가려 주는 것이 없다. 일반 논거로도 이 표시는 확신도와 같은 모델의 자기 보고라 따로 선 근거가 아니다.

### 4.3 규칙(`auto_block`)

하나라도 걸리면 수락하지 않고 후보로 남긴다. 남은 후보는 미확인으로 센다.

| 차례 | 조건 | 까닭 |
| --- | --- | --- |
| 1 | `status`가 proposed가 아님 | 이미 정한 것 |
| 2 | 사람이 되돌렸거나 거절한 후보 | 사람이 물린 것을 다시 넣지 않음 |
| 3 | 보호 집합(`protected_targets`)에 든 자리 | 4.4 |
| 4 | 과제·필드가 kind·tag가 아님 | 4.2 |
| 5 | `input`이 image가 아니거나 `legend_source`가 symbols가 아님 | 4.1. 지금 `match` 칸으로 가르면 태그 후보는 하나도 받지 못한다(`match`는 종류에만 붙음, `ai_review.py` 580~583) |
| 6 | 확신도 0.70 미만 | 4.2 |
| 7 | 지금 값과 모순(종류·태그가 이미 있음), 또는 후보의 상자와 지금 대상의 상자가 다름 | 추출·사람 값을 이기지 않음. 번호가 밀린 후보를 거름 |
| 8 | 종류가 글자로 정하는 원(`LETTER_CIRCLE_KINDS`) | 원 모양이 같아 그림이 종류의 근거가 되지 못한다. 개발용 정답지 판 0.70 이상에서 이 종류 3건 가운데 1건만 맞았다. 새 판 0.70 이상에는 해당 후보가 없어 값에 영향이 없다 |
| 9 | 같은 태그가 이 도면의 다른 구성요소에 있거나 다른 후보도 냄 | 태그는 설비 식별자다. 겹치면 지식그래프가 둘을 하나로 잇는다 |
| 10 | 종류가 `WIDE_KINDS`(구동부로 갈리는 밸브)인데 넓혀 묻기를 마치지 않음 | 호출 상한·실패로 첫 답만 남은 밸브는 구동부를 보지 않은 값이다. 후보에 `wide: done`을 적어 가른다 |

앞 판에 있던 `pipe_cap`·`relay_converter`·`test_connection` 제외는 뺐다. 까닭에 보류 쪽 결과를 섞어 썼고, 개발용에서는 이 종류가 0.70 이상에 하나도 없어 규칙이 하는 일이 없다.

**규칙 전부를 넣어 흉내 낸 값**(새 표준 판 5쪽, 46b973ac 재생 후보, 실측):

| 쪽 | 자동 수락(종류·태그) | 막힌 까닭 | 종류 미정 기호 앞 → 뒤 | DEXPI로 나가는 구성요소 앞 → 뒤 |
| --- | --- | --- | --- | --- |
| 007 | 2·0 | 확신도 7 | 23 → 21 | 138 → 140 / 166 |
| 019 | 20·2(종류 2건 틀림, 짝 없는 조각) | 확신도 21, 과제·필드 26 | 71 → 51 | 99 → 104 / 170 |
| 099 | 8·3 | 확신도 7 | 50 → 42 | 35 → 43 / 97 |
| 133 | 0·0 | 확신도 12 | 39 → 39 | 10 → 10 / 53 |
| 134 | 15·3(종류 1건은 정답지 영역 밖) | 확신도 21 | 82 → 67 | 216 → 231 / 356 |

합은 종류 45건(채점된 44건 가운데 42건 맞음), 태그 8건(8건 맞음)이다. 종류 미정 기호 265개 가운데 45개만 준다. **자동 확정 뒤에도 미확인이 대부분 남는다.**

### 4.4 사람 수정, 재추출, 되돌리기

- **보호 집합을 지금 id로 만든다.** 지금 `human_targets`·`decided_targets`(`ai_review.py` 740, 746)와 `accept`의 검사(1039)는 저장된 옛 id를 본다. 번호가 밀린 추출에서 사람 고침은 새 id에 붙는데(`corrections.retargeted`) 보호 집합에는 옛 id만 있어 AI 수락이 막히지 않는다(실측: 태그를 고친 밸브의 번호를 바꾼 추출에서 자동 수락이 거절 없이 들어감). `protected_targets`는 `corrections.resolve`의 `retargeted`로 옮긴 id, 적용하지 못한 사람 연산의 바탕 위치(`base.at`)에 있는 기호, 결정한 후보의 상자와 같은 자리의 기호를 모은다.
- 사람 고침은 나중에 와도 이긴다. 채팅 고침(`drawing.edit`)은 자동 연산 뒤에 놓이고 보호 집합에 들어간다.
- 자동 연산은 바탕 지문으로 다시 찾으므로 재추출에도 남는다(`corrections.py` 699). 찾지 못하면 '적용 불가'로 남고 미확인으로 돌아간다.
- 되돌리기는 도면 한 장 단위다. `auto_revert`가 그 도면에서 `accepted_by == hazop:auto`인 수락을 한 번에 빼고, 기댄 사람 고침이 있으면 지금처럼 미리 알림(`RevertNeedsConfirm`)을 거친다. 지금 채팅의 되돌리기는 AI 수락 연산을 막고 AI 검토 패널로 보낸다(`api_corrections.py` 115, 524). 패널을 없애면 길이 없어지므로 C2에서 채팅 동작 `aireview.auto_revert`를 둔다.
- `confirmed_samples`는 자동 수락 종류를 견본에서 뺀다. 노드의 `human_edit`만으로는 자동인지 모르므로 `corrections._apply_one`이 `human_edit.auto`(자동 연산 이름 목록, 사람이 같은 종류로 덮으면 빠짐)를 적는다. 태그의 근거도 자동이면 `human`이 아니라 `ai_auto`로 적는다(`corrections.py` 379가 지금 `human`으로 적음).

### 4.5 C1이 잴 것과 켜는 판정

- `scripts/check_auto_accept.py`(새 파일): 저장된 후보를 `auto_block`으로 걸러 맞은 수와 새 오검출을 낸다. 개발용 저장 응답으로 호출 없이 돌고, 4.2와 4.3의 수를 그대로 낸다.
- **보류 6쪽은 켜도 되는지 판정하는 데만 쓴다.** 총괄(또는 d-read)이 표준 기호 판 고정으로 한 번 재고 합계만 본다. 미리 정한 기준은 자동 수락 종류 후보 40건 이상이고 정밀도 90% 이상이면 통과, 40건 이상이고 90% 미만이면 실패다. 실패면 자동 수락을 끄고(후보만 남김) C2를 낸다. 40건 미만이면 '판정 못 함'이고 실패처럼 다룬다. 문턱을 그 결과로 고치지 않는다. 그 순간 보류 쪽이 처음 보는 쪽이 아니게 되기 때문이다.
- 문턱을 다시 정하려면 새 개발용 쪽을 고르고 정답지를 만든 뒤 표준 판으로 물어야 한다(구독 호출, 총괄 승인).
- 번호 후보의 정확도는 잰 적이 없다. 자동 번호를 켜기 전에 SNP 6장과 번호 칸이 읽히는 공개 도면에서 읽은 번호와 실제 번호를 맞대어 본다(호출 없음).

## 5. 하류: 자동 확정을 어디까지 받나

| 하류 | 지금 거는 조건 | 자리 | 판정 |
| --- | --- | --- | --- |
| 지식그래프 | 없음(추출 직후 들어감) | `hazop/app/data.py` 336, 489, `hazop/kg/auto.py` | 받음. 자동 태그·속성 주장은 `origin: ai_auto`, `method: ai`, 지식 상태 `hypothesis`(`hazop/kg/claims.py` 70~78). **종류는 주장이 아니라 그래프 노드 값**이라 이 길로 걸러지지 않는다. 노드에 `auto: ["kind"]`를 적고 화면의 '만든 곳'에 '자동 확정(AI)'을 보인다(`hazop/kg/screen.py` 1146) |
| 검토구간(만들기·확정·잠금) | 쪽 확정을 보지 않음 | `hazop/study/nodes.py` 717, `hazop/study/node_tools.py` 402 | 받음. 막지 않음. 구간 확정 글에 그 구간에 든 '미확인 n, 자동 수락 m' |
| AI 분석 | 쪽 확정을 보지 않음. **도면의 미확인도 맥락에 실리지 않고**(프로젝트 그래프의 `unknowns`가 늘 빈 목록, `hazop/graph/project.py` 541), 구성요소의 종류·태그는 사실처럼 실린다 | `hazop/study/ai_cells.py` 210 `_component`, 217 | 받음. 실행 기록 `ai_log`에 `sheet_levels: {도면: {level, unconfirmed, auto_accepted}}`를 그 실행 때 값으로 남김. 맥락에 자동 표시를 싣는 일은 P16 |
| 워크시트 Excel | 쪽 확정을 보지 않음 | `hazop/export/study_xlsx.py` 38, 113 | 받음. '표지·요약'에 도면별 수준·미확인·자동 수락 수와 고지. 원인 위치·영향 대상 칸의 구성요소에 '(자동)' |
| 초기사건 인계 묶음 | 쪽 확정을 보지 않음 | `hazop/ie/bundle.py` 138, 455, 533 | 받음. `source.sheet_levels`, 후보마다 원인 위치가 자동 수락 구성요소인지(`cause_location_auto`) |
| DEXPI 내보내기 | `state == "confirmed"`와 등록 번호 확정 | `hazop/export/dexpi_export.py` 188, 898, 943, 957, 1020 | `level`이 human·auto면 받음(P14, 새 결정 필요). 미확정 구성요소는 지금처럼 빼고, `manifest.json`에 `level`·`unconfirmed`·`auto_accepted`. 번호 조건은 유지 |
| 정리 보기 기본값 | PDF·래스터는 confirmed면 정리 보기 | `confirmation.py` 55, `hazop/shell/web/js/canvas/clean_view.js` 345 | 바꾸지 않음. 자동 확정은 원본이 기본 |
| 고지 | 없음 | 워크시트 표지, 인계 묶음, 도면 탭 | 새로 둠(아래) |

고지 문구: '이 도면은 자동 확정이며 미확인 n곳과 AI가 자동으로 받은 값 m건이 있습니다. 자동으로 받은 종류·태그는 사람이 보지 않은 값이고, AI 분석은 이것을 확정된 값과 똑같이 읽습니다. 처음 보는 도면의 읽기 정확도는 기호 종류 67.8%, 연결 58.6%(2026-11-18 측정)입니다.' 마지막에서 둘째 문장은 P16을 하기 전까지의 한계다.

틀린 자동 수락을 분석 앞에서 막는 장치는 이 설계에 없다. 4.3의 흉내에서 45건 가운데 2건이 짝 없는 조각에 종류를 붙였다. 종류가 붙은 조각은 구성요소가 되어 구간에 들고, 분석이 그 구성요소의 고장을 다룰 수 있다. 막으려면 P12(지식 상태)와 P16(분석 맥락 표시)을 함께 해야 하므로 둘을 묶어 판정을 다시 청한다(11장).

## 6. 표제란 번호

### 6.1 사실

- 번호 후보는 등록 때 읽는다(`hazop/register/fileinfo.py` 142, 298). 첫 쪽만 본다.
- 번호가 이름(`graph-<번호>`)이 되려면 등록정보의 확정 번호여야 하고 한 쪽 자료여야 한다(`hazop/graph/sheets.py` `usable_number`). 없으면 `graph-<자료>-p<쪽>`, 화면 이름은 '파일 이름 · n쪽'이다.
- 추출하지 않은 자료에 번호를 주는 가드는 새 이름을 가리키는 기록이 있는지 보지 않는다(`titleblock.py` 600~642: 대상이 `(None, 새 이름, None)`이면 주인만 묻는다).
- **APR1400 개발용 8쪽(007·019·037·051·080·103·133·134)의 번호·개정·제목 후보는 8쪽 모두 비어 있다(실측).** SNP 6장은 번호를 읽는다. 번호 후보가 실제 번호와 맞는지는 잰 적이 없다.

### 6.2 규칙

`auto_confirm_number`는 **추출 앞에서** 돈다. 아래가 모두 참일 때만 확정한다.

1. 새로 등록한 자료다(추출 결과가 없다).
2. 번호 후보가 있고 `sheets.number_problem`이 없다(여러 쪽 자료, 임시 이름 꼴 제외).
3. 프로젝트의 다른 자료가 같은 번호를 쓰지 않는다. 형식이 달라도, 대소문자·특수 문자만 달라도 겹친 것으로 본다(`_others`, `_key`). 사람 확정은 형식이 다르면 알리고 통과시키지만(`titleblock.py` 569 `SHARED_NUMBER`) 자동은 멈춘다.
4. 사람이 고른 원본 형식(`drawing-sources`의 `chosen`)이 그 번호에 없다.
5. 새 이름을 가리키는 사람 기록이 없다(`_references(project_id, "graph-<번호>")`가 빔). 지운 도면의 옛 기록에 새 도면이 말없이 붙지 않게 한다. 걸리면 `has_records`.

검사와 새 판 쓰기는 등록 잠금(`hazop/register/registry.py` 45 `INDEX_LOCK`) 하나 안에서 한다. 지금 등록 쓰기는 그 잠금 안이지만 겹침 검사는 밖이라(`titleblock._apply`), 파일 여러 개를 한꺼번에 올리면 작업 스레드 둘이 같은 번호를 함께 통과할 수 있다(코드, 실제 경합은 재현하지 않음).

### 6.3 번호가 빈 쪽과 겹친 쪽

| | 빈 번호 | 겹친 번호 |
| --- | --- | --- |
| 자동 확정 | 내용은 함. 번호만 미확정(P7) | 하지 않음. `waiting(taken)`, AI도 부르지 않음 |
| 사람에게 | 도면 줄은 파일 이름. 채팅으로 번호를 정할 수 있음 | 채팅이 어느 파일을 쓸지 묻는다 |
| 이름 | `graph-<자료>-p<쪽>` | 같음. 번호를 주지 않으므로 **원본 고르기(`sources.conflicts`)에 걸리지 않는다** |

**빈 번호의 위험(실측).** 가상 도면 SNP-M-301을 번호 없이 형식을 바꿔 두 번(drawio, PDF) 올리고, 바이트만 다른 개정판 PDF를 한 번 더 올렸다.

| 올린 것 | 결과 |
| --- | --- |
| 같은 파일을 다시 | 등록이 `reused`. 시트가 늘지 않음 |
| 같은 도면, 다른 형식 | 시트 둘, 원본 고르기 0건, 겹친 태그 13개 |
| 개정판 PDF | 시트 셋, 원본 고르기 0건, 겹친 태그 13개 |

번호가 없으면 앱은 같은 도면인지 알지 못한다. 한 도면이 프로젝트 그래프에 두세 번 들어가고, 같은 태그의 구성요소가 여럿이 되어 문서 연결은 만들어지지 않으며(`hazop/kg/auto.py`의 태그 연결은 정확히 하나일 때만), 구간·분석이 겹친 설비를 따로 다룬다. 번호가 겹쳐 `waiting(taken)`에 둔 쪽도 추출·그래프는 이미 되어 같은 일이 생긴다. 이 위험은 지금도 있고(사람이 번호를 확정하지 않으면 같음) 자동 확정이 사람의 확인 기회를 줄여 더 커진다. 덜어 내는 길은 둘이다. `waiting(taken)` 쪽을 고를 때까지 프로젝트 그래프에서 빼 두는 것(G의 기록을 씀, P17), 그리고 겹친 태그가 많은 두 쪽을 같은 도면일 수 있다고 채팅이 알리는 것이다.

### 6.4 판 이전(ID)에 미치는 영향

- 번호를 추출 앞에서 확정하므로 첫 그래프부터 이름이 `graph-<번호>`다. 이름 바뀜 이전이 생기지 않는다.
- 나중에 채팅으로 번호를 확정하는 길은 지금 가드와 같다. 막음 자리(지식그래프 판단, 도면 연결 지정, 구간 제외 표시 등)에 기록이 있으면 막힌다. 자동 확정은 막음 자리에 아무것도 쓰지 않는다.
- 자동 번호를 사람이 고치면 이름 바뀜 이전이 한 번 돈다. 지금 사람 확정 번호를 고칠 때와 같다.

## 7. 사람 확정을 전제로 한 곳 전수 표

### 7.1 다시 돌리는 방법

```
git grep -nE "sheet_confirmation|confirmation\.(execute|load_sheet|check|file_paths|default_view|COMMANDS)" -- "hazop/*.py" "hazop/*.js" "scripts/*.py"
git grep -nE "CONFIRM_FIRST|confirm_title_block_first" -- "hazop/*.py" "hazop/*.js" "scripts/*.py"
git grep -nE "identification_basis" -- "hazop/*.py" "hazop/*.js" "scripts/*.py"
git grep -nE "extract_ai_review|extract_ai_cap|ai_review_images" -- "hazop/*.py" "hazop/*.js" "scripts/*.py"
git grep -nE "human_edit" -- "hazop/*.py" "hazop/*.js" "scripts/*.py"
git grep -nE "accept_bulk|bulk_block|bulk_groups" -- "hazop/*.py" "hazop/*.js" "scripts/*.py"
git grep -nE "sheetconf" -- "hazop/*.py" "hazop/*.js" "scripts/*.py"
```

46b973ac에서 이 일곱 줄은 차례로 11파일 33행, 4파일 9행, 5파일 6행, 6파일 17행, 13파일 24행, 13파일 40행, 13파일 25행이다(실측, `hazop/`과 `scripts/`의 py·js, 설명 글 포함). 문자열로 묶인 값(토픽 이름, 웹의 `state` 글자)은 검색이 놓치므로 `hazop/shell/web/js`는 `"confirmed"`·`"ready"`를 따로 훑었다.

### 7.2 표

| 자리 | 지금 | 판정 | 이유 |
| --- | --- | --- | --- |
| `hazop/extract/confirmation.py` 157 `check` | 미확인·위치 없음·남은 것 세기 | 남음 | 자동 확정의 미확인 수도 이 함수가 센다 |
| 같은 파일 334 `_status` | open·ready·confirmed | 바뀜 | `level`, `unconfirmed_targets`, `auto` 칸을 더함. `state` 규칙은 그대로 |
| 같은 파일 384 `_left`, 400 `execute` | 사람 확정 조건과 명령 | 남음 | 기본 흐름에서 빠질 뿐, 채팅·점검용으로 유지 |
| 같은 파일 330·348 지문으로 풀기 | 세 파일이 바뀌면 사람 확정이 풀림 | 남음 | 사람 확정은 내용을 보증하는 말이라 그대로. 자동 기록은 추출 지문만 본다 |
| 같은 파일 55 `default_view` | confirmed면 정리 보기 | 남음 | 5장 |
| `hazop/export/dexpi_export.py` 861~900, 920, 964, 1018 | confirmed만 내보냄 | 바뀜 | `level`이 human·auto. 쓰기 직전 다시 보기도 `level`과 세 파일 지문으로 |
| 같은 파일 186~190, 943, 957 | 등록 번호 확정 요구 | 남음 | 번호 없는 쪽은 도면 사이 참조를 못 쓴다 |
| `hazop/extract/adapters/pdf_vector.py` 4370, `drawio.py` 822, `dexpi_import.py` 415 | 등록 번호가 있으면 `registration_confirmed` | 남음 | 자동 번호도 등록정보에 들어간다. 누가 정했는지는 등록 이력의 `by`가 안다 |
| `hazop/extract/corrections.py` 1181 | 같은 값으로 기준 추출 이어 받기 | 남음 | 같음 |
| `hazop/register/titleblock.py` 737, 828, 842 | 번호 확정 때 풀리는 쪽 확정 목록 | 바뀜 | 목록을 `human`만으로 유지. 자동은 다시 추출 뒤 이어 하기가 되살림 |
| 같은 파일 788 `_apply`, 856 `confirm` | 사람 이름 필수 | 바뀜 | `hazop:auto`만 받는 별도 진입 `auto_confirm_number`. 사람 경로는 예약 이름을 거절 |
| `hazop/graph/sheets.py` 31, 36, 192 | `confirm_title_block_first` 알림 | 바뀜 | 안내 글을 '번호 미확정(채팅으로 정할 수 있음)'으로. 코드 값은 남김(기록·시험이 씀) |
| `hazop/register/registry.py` 367~368 | 등록된 자료의 번호를 등록 경로로 바꾸지 못함 | 남음 | 자동도 이 길을 쓰지 않는다. 예약 이름만 거절한다 |
| `hazop/shell/api_drawings.py` 69~78 | 번호 미확정 알림 글 | 바뀜 | 도면 줄은 번호와 제목만 보인다(§3.8 3). 알림 줄을 없앰 |
| 같은 파일 88~125, 242, 360~375 | 쪽 확정 읽기·명령 | 바뀜 | `status`에 `level`. 명령은 남기되 화면 단추 없음 |
| 같은 파일 301, 349 | DEXPI 내보내기 | 바뀜 | F1 |
| `hazop/shell/api_next.py` 103~119, 173~192, 193 | 다음에 할 일: 표제란, AI 검토 시작, 후보, 쪽 확정, 구간 만들기 | 없어짐 | §3.8 7. 읽기 토픽 `next`는 s-viewer 단위에서 뺀다. 그 전에 C2가 먼저 들어가면 자동 작업이 도는 동안 이 줄이 사람에게 할 일을 시키므로 `level`을 보게 한다 |
| `hazop/shell/api_queue.py` 56 | AI 후보 대기열 | 없어짐 | 화면에서 빠짐. 엔진 읽기는 채팅이 쓸 때까지 남김 |
| `hazop/shell/api_aireview.py` 291 `_review_state`, 338, 635 | 도면별 AI 상태, 예상, 시작 | 바뀜 | 화면 단추 없음. 채팅 'AI 검토 다시'와 이어 하기용으로 남김 |
| 같은 파일 434, 518 | 수락·거절·되돌리기·묶음 수락 | 바뀜 | 채팅 통로로 남음. 묶음 수락(`bulk_block`)은 '종류는 하나씩'이라는 옛 원칙이라 자동 규칙과 다르다. 같은 이름을 다시 쓰지 않고 `auto_block`을 따로 둠 |
| `hazop/shell/api_titleblock.py` | 표제란 읽기·확정 명령 | 바뀜 | 채팅 통로. 패널은 없어짐 |
| `hazop/shell/api.py` 638~652, 850 | AI 검토 켜기·상한·그림 설정 | 없어짐 | §3.8 10. 연결 때 한 번 안내 |
| 같은 파일 371 | 파일마다 작업 하나 | 바뀜 | 올리기 묶음 하나의 실행 상한(8장) |
| `hazop/shell/register_flow.py` 41 | 켜졌을 때만, 후보만 | 바뀜 | 자동 확정 흐름(C2) |
| `hazop/shell/ai_image_flow.py` 35 | 자동은 설정이 True일 때만 그림 | 바뀜 | 9장의 사용자 확인 뒤 |
| `hazop/shell/api_corrections.py` 217, 403 | 쪽 확정 상태(없는 칸) | 바뀜 | 1장의 결함. `level`로 |
| `hazop/shell/chat_edits.py` 249, 368 | 확정이 풀린다는 안내 | 바뀜 | 사람 확정일 때만 |
| `hazop/chat/actions.py` 209~212, 644, 657 | 채팅 쪽 확정은 ready만, 견줌은 화면에서만, DEXPI는 confirmed만 | 바뀜 | 견줌 화면을 없애면 사람 확정을 할 길이 없어진다. 채팅이 확인 상자에서 견줌을 함께 적게 하거나 사람 확정 동작을 뺀다(선택지 표) |
| `hazop/shell/chat_actions.py` 593, 704, 982 | 다시 추출 안내, 쪽 상태, 쪽 확정 | 바뀜 | 안내에 자동 확정이 이어 돈다는 말 |
| `hazop/chat/card.py` 59~62, `hazop/shell/chat_actions.py` 26·492~507, `hazop/shell/chat_screens.py` 20·151~257, `hazop/shell/chat_edits.py` 20·57~149 | 쪽 확정·AI 후보·표제란을 채팅 동작으로 | 바뀜 | 고치는 통로가 채팅뿐이므로 남긴다. `aireview.auto_revert`와 'AI로 확정' 동작을 더하고, 확인 글에서 패널 이름을 뺀다 |
| `hazop/shell/api_inputs.py`, `api_titleblock.py`, `api_aireview.py`의 `sheetconf` 알림 | 확정 카드를 다시 읽게 함 | 남음 | 알림을 받는 화면이 없어져도 채팅과 도면 탭이 같은 토픽을 쓴다 |
| `hazop/shell/sheet_refresh.py` 85 | 판(`ver`)을 세 파일로 만듦 | 남음 | 확정 기록은 판에 들지 않는다 |
| `hazop/shell/clean_items.py` 102·141 | 검토 표시(human·ai_accepted·script), 수락 전 AI 후보 표시(id가 어긋나 나오지 않음) | 바뀜 | `human_edit.auto`면 `ai_auto`. 지금 `ai_accepted` 가지는 추출 노드의 `origin`을 보는데 그 칸은 그래프에만 있어 타지 않는다(코드) |
| `hazop/graph/build.py` 67, `hazop/kg/claims.py` 70, `hazop/kg/screen.py` 416 | 고친 것은 모두 사람 것 | 바뀜 | 5장 |
| `hazop/extract/corrections.py` 379 | 태그를 고치면 근거를 `human`으로 | 바뀜 | 자동이면 `ai_auto`. 그래야 지식그래프 자동 연결이 추정 태그로 다룬다 |
| `hazop/kg/claims.py` 78 | 태그 근거 `human`·`set_tag`면 사람이 정한 주장 | 바뀜 | 위와 같음. 종류는 주장이 아니라 여기서 걸러지지 않는다 |
| `hazop/kg/screen.py` 1146 | 상세의 '만든 곳' | 바뀜 | 자동 확정(AI)을 보임 |
| `hazop/study/ai_cells.py` 210 | 분석 맥락에 태그·종류를 사실로 실음 | 남음(P16) | 요청 글을 바꾸는 일이라 따로 |
| `hazop/register/titleblock.py` 684 `_carry` | 수정 기록·AI 후보만 새 이름으로 옮김 | 바뀜 | `auto` 칸도 옮긴다(2.5) |
| `hazop/export/dexpi_export.py` 283~285 `_raw_object` | `origin`이 `pid_extract`일 때만 DEXPI 원문 조각을 되살림 | 남음 | 자동으로 종류를 정한 객체는 원문을 되살리지 않고 정한 종류로 낸다. 사람이 고친 것과 같다 |
| `hazop/shell/api_corrections.py` 115, 524 | AI 수락 연산은 AI 검토 패널에서만 되돌림 | 바뀜 | 패널이 없어지므로 채팅 동작으로 |
| `hazop/graph/project.py` 504 | 도면 연결의 사람 지정을 `human_edit`로 | 남음 | 자동 수락은 도면 연결을 만들지 않는다 |
| `hazop/export/dexpi_export.py` 797, `hazop/extract/adapters/dexpi_import.py` 632 | 곁 파일에 `origin`·`human_edit`를 적고 되읽음 | 남음 | 적는 값이 `ai_auto`로 바뀔 뿐 꼴은 같다 |
| `hazop/shell/api_corrections.py` 278, `hazop/shell/web/js/canvas/edit.js` 326·358 | '사람이 고친 항목', 쪽 확정이 풀린다는 알림 | 바뀜 | 자동 수락에 '사람이 고친 항목'이 붙는다. 직접 고치기 화면은 §3.8 5로 없어지지만 채팅 답이 같은 값을 읽는다 |
| `hazop/app/screens/knowledge.py` 885 | 이전 화면의 사람 고침 표시 | 남음 | 이전 화면은 다른 단위가 지운다 |
| `hazop/extract/ai_images.py` 274 | AI 수락도 사람 견본 | 바뀜 | 4.4 |
| `hazop/extract/ai_review.py` 834 `bulk_block` | 종류·다시 확인은 하나씩 | 남음 | 채팅 묶음 수락의 규칙 |
| 같은 파일 740, 746 | 사람 고친 자리 제외 | 남음 | 자동 수락도 같은 집합 |
| `hazop/extract/adapters/raster_scan.py` 358 | 스캔은 확정 판정에서 남은 것을 못 셈 | 남음 | 자동 확정은 남은 것을 요구하지 않는다 |
| `hazop/app/screens/ai_review_panel.py`, `register.py` | 이전 화면의 AI 검토 | 남음 | 이전 화면은 다른 단위가 지운다 |
| `hazop/shell/web/js`: `sheet_confirm.js`, `compare.js`, `panels/titleblock.js`, `panels/aireview.js`, `aireview_state.js`, `queue/`, `review/`, `next/`, `panels/drawings.js` 15·25·55, `main.js` 25~29, `areas.js`, `sheet_host.js`, `store.js`, `fix_actions.js`, `canvas/clean_ui.js` 51 | 확정·견줌·대기열·표제란·안내 화면 | 없어짐 | s-viewer 몫. 파일 주인 표(10장) |
| `scripts/export_dexpi.py`, `scripts/check_shell_scenarios.py` 417, 479, 676, 782 | 확정을 거친 시나리오 | 바뀜 | 시나리오를 자동 흐름으로 다시 씀 |

### 7.3 이 변경이 안전한 한 가지 까닭

**자동 확정 기록은 사람 확정과 다른 칸에 있고, 사람 확정을 묻는 코드는 그 칸을 보지 않는다.** 46b973ac 코드로 돌려 확인했다(2.4 표 1~2행). 그래서 C1만 들어가고 C2가 늦어도 지금 화면은 그대로 움직인다. 남은 위험은 아래와 같다.

| 위험 | 어떻게 깨지나 | 가능성·피해 | 잡는 시험 |
| --- | --- | --- | --- |
| 자동 값이 사람 값으로 남음 | 그래프·지식그래프·범례판이 `human_edit`만 본다 | 높음·중 | 자동 수락 뒤 `origin`, 주장 상태, 견본 목록 |
| 같은 도면을 두 번 처리 | 등록 작업과 이어 하기, 채팅 'AI 검토 다시'가 겹침 | 중·낮음(호출 낭비) | `reserve_review`로 막고 두 스레드 시험 |
| 후보 id가 다시 추출로 밀려 다른 기호에 수락 | `cand_id`가 순번 | 중·높음 | 규칙 7의 상자 견줌. 재추출로 번호를 민 자료로 시험 |
| 사람이 고친 자리에 자동 수락 | 보호 집합이 옛 id(실측) | 중·높음 | 4.4의 `protected_targets`, 10.1 시험 5 |
| 틀린 자동 수락이 분석까지 감 | 분석 맥락이 종류·태그를 사실로 실음 | 높음·높음 | 막지 못한다. 5장의 표시와 고지, P12·P16 |

## 8. 과금과 실패

| 항목 | 규칙 |
| --- | --- |
| 자료당 상한 20 | 같은 원본(sha256·쪽)에 대해 실행을 넘어 **누적** 20회다. 지금 20회는 실행마다 새로 세인다(`ai_review.run`의 `cap`). 누적은 `runs[].calls` 합으로 세고 번호 확정 때 함께 옮겨진다. 자동 경로는 설정값과 관계없이 20을 넘지 않는다(설정은 지금 200까지 받음, `api_aireview.py` 702) |
| 자동 시도 | 자료당 3번(호출 오류로 끝난 것만 셈). 넘으면 `waiting(error_final)` |
| 실행당 상한 300 | **올리기 묶음 전체**에 건다. 지금은 파일마다 작업이 생기고(`api.py` 371) 작업마다 300을 새로 센다(`register_flow.py` 69). 자동 작업이 하나도 없을 때 새 예산 300을 만들고, 도는 동안 들어온 등록 작업은 그 예산을 나눠 쓴다. 다 쓰면 남은 쪽은 `waiting(run_cap)` |
| 그림 입력만 | drawio·DEXPI·스캔은 자동 경로에서 부르지 않는다. 받지 않을 후보에 호출을 쓰지 않고, 자동으로 밖에 나가는 자료도 그만큼 준다. 원본 PDF가 없는 쪽은 `waiting(no_image)` |
| 구독만 | `ai_image_flow.subscription_client` 그대로. API 연결이면 `waiting(no_connection)` |
| 한도·멈춤 | `waiting`과 까닭. 추출·그래프는 완료. 받은 답은 저장(`ai_image_flow.py` 168 `_tolerant`) |
| 이어 하기 | 앱을 열 때, AI 연결이 준비될 때, 다음 올리기 때 `waiting`(taken·scan·error_final 제외) 쪽을 등록 차례대로 한 번에 300회까지. 같은 `read_key`로 끝난 실행이 있으면 부르지 않고 수락만 |
| 소급 없음 | `auto` 기록이 없는 옛 쪽은 이어 하기 대상이 아니다. 사람이 채팅으로 'AI로 확정해 줘'라고 시킬 때만. 같은 파일을 다시 올려 `reused`가 된 옛 자료도 마찬가지다 |
| 예상 크기 | 쪽마다 10.75회(기록, 실측 14: 12쪽 129응답) → APR1400 143쪽이면 1,540회 안팎(추정). 300회 상한이면 다섯 번 남짓에 나눠 끝난다 |

## 9. 사용자 승인이 꼭 필요한 것

| 일 | 왜 | 승인 전 기본값 |
| --- | --- | --- |
| 올리는 즉시 도면 조각 그림을 AI에 보냄 | 지금 자동 검토는 안내를 보고 켠 사람만 보낸다(`ai_image_flow.py` 35). 사용자 결정은 'AI 검토가 곧바로 메운다'와 'AI는 처음에 한 번 연결한다'이고 보내는 범위 안내는 정하지 않았다 | 연결 화면에서 '올린 도면의 기호 조각과 주변 글자를 이 구독으로 보냅니다'를 한 번 보이고 연결하면 동의로 적는다. 동의 기록이 없으면 자동으로 보내지 않고 '추출만 됨' |
| 보안 등급 자료 | 자동이라 사람이 막을 틈이 없다 | 프로젝트마다 '자동 AI 검토 안 함' 하나(화면 단추가 아니라 채팅·설정 파일) |
| DEXPI 내보내기 조건 바꾸기 | DEC-0311과 HZ-PLN-22 §6.1의 '확정된 쪽만'(사용자 결정은 '사람이 확정한 결과를 내보낸다')을 '자동 확정된 쪽도'로 바꾼다 | 새 결정 줄을 얻기 전에는 F1이 사람 확정 쪽만 낸다. 다만 벡터 PDF는 지금 사람 확정이 될 수 없어(2.2) 낼 쪽이 없다 |
| 도면 영구 삭제 | 되돌릴 수 없음 | G는 '목록에서 빼기(복구 가능)'까지 |

## 10. 구현 단위

### 10.1 C1 엔진(Opus medium, 저장·ID 경로)

- 파일: `hazop/extract/confirmation.py`, `ai_review.py`(후보의 `input`·`legend_source`·`wide`, 보호 집합), `ai_images.py`, `corrections.py`(`human_edit.auto`, 태그 근거, 예약 이름), `hazop/register/titleblock.py`(`auto_confirm_number`, `_carry`), `hazop/register/registry.py`(예약 이름), `hazop/graph/build.py`, `hazop/kg/claims.py`, `hazop/kg/screen.py`, `scripts/check_auto_accept.py`
- 완료 기준: 2.3 전이 표, 2.4 호환 표, 4.3 규칙 표, 6.2 규칙의 시험이 모두 있고, 4.2·4.3의 개발용 값이 `check_auto_accept.py`에서 같은 수로 나온다. `state`를 쓰는 기존 시험은 고치지 않고 통과한다.
- 재현 시험
  1. 추출만 → 자동 → 채팅 고침 → 자동 그대로
  2. 번호 확정(다시 추출) → `read_key` 같음, 자동 그대로, 새 호출 0
  3. **되돌리기 → 번호 확정 → 다시 자동 수락되지 않음**
  4. 규칙이 바뀐 다시 추출 → 추출만, 수락 연산은 남음
  5. 번호가 밀린 추출에서 사람 고침·거절한 자리에 자동 수락이 들어가지 않음
  6. 번호가 밀린 후보가 다른 기호에 수락되지 않음(상자 견줌)
  7. 구성요소 0개, 검증 blocked → 자동이 되지 않음. 대상 없는 미확인 세 줄이 3으로 셈
  8. AI 후보가 남은 미분류 기호 하나를 미확인 1곳으로 셈. 태그 후보도 규칙 5를 지남, 프로젝트 판으로 물은 후보는 막힘, 넓혀 묻지 못한 밸브는 막힘
  9. 도면 단위 되돌리기와 기댄 사람 고침 알림
  10. 자동 종류가 범례판 견본에 들지 않음, 태그 근거가 `ai_auto`
  11. 그래프 노드의 자동 표시, 주장 `hypothesis`
  12. 자동 번호를 확정한 뒤 추출 결과에 그 번호가 들어 있음
  13. 같은 번호 동시 등록 두 스레드 → 하나만 확정. 새 이름에 옛 기록이 있으면 `has_records`
  14. 예약 이름이 모든 진입에서 거절됨
  15. 46b973ac 고정 코드로 읽는 옛 앱 시험(2.4 표 전부)
  16. 단계마다 중간에 끊긴 뒤 다시 돌리면 같은 끝

### 10.2 C2 셸 흐름(Sonnet high)

- 파일: `hazop/shell/register_flow.py`, `api_aireview.py`, `ai_image_flow.py`(자동 경로 `drawings=()`), `api_titleblock.py`, `api.py`(실행 예산, 예약 이름), `api_drawings.py`(`level`), `api_corrections.py` 217·403, 채팅 동작(`hazop/chat/actions.py`, `hazop/shell/chat_actions.py`)
- 완료 기준: 올리기 한 번으로 자동 확정까지 사람 동작 0. 143파일을 한꺼번에 올려도 호출 300회를 넘지 않고, 같은 자료를 다섯 번 이어 해도 누적 20회를 넘지 않는다(고정 응답). 연결 없음·한도·멈춤·일부 실패에서 2.3의 상태가 남고 이어 하기로 끝난다. drawio·DEXPI·스캔은 호출 0. 동의 기록이 없으면 아무것도 보내지 않는다.
- 재현 시험: 파일 30개와 도면당 20회 고정 응답으로 300에서 멈춤, 작업 중 앱 닫기, 이어 하기 두 번이 호출을 두 번 쓰지 않음, 번호 확정 뒤 호출 0, 같은 도면에 수동 실행이 겹침.

### 10.3 G 도면 빼기(Opus medium)

- `data/drawing-removed/<프로젝트>.json`에 `{자료, 쪽, by, at, why}`을 적는다. 원본·추출·그래프 파일은 지우지 않는다. `graph.json`을 비켜 두는 길은 쓰지 않는다(비켜 둔 그래프는 '번호 확정 중 끊긴 자리'로 읽힌다, `hazop/app/data.py` 403).
- **거르는 자리는 후보 모으기 한 곳이다.** `sources.pick`(285) 앞만 거르면 `owner_if`(305)·`keep_owner`(335)·`conflicts`(404)가 뺀 도면을 여전히 주인으로 센다. 이들이 함께 쓰는 `_candidates`와 프로젝트 그래프·지식그래프의 후보 모으기(`hazop/kg/auto.py`)를 같은 함수로 거른다. 프로젝트 그래프 입력 지문(`hazop/app/project_ctx.py` 134)에 이 파일을 넣고 빼거나 되돌리면 지식그래프를 다시 짓는다.
- 뺀 자료의 파일을 다시 올리면 등록은 `reused`다. 이때 '목록에 되돌릴까요'를 채팅으로 묻고, 말없이 되돌리지 않는다. 개정판은 새 자료라 빼기와 상관없이 들어온다.
- 빼기 전에 그 도면에 걸린 구간·분석 결과·초기사건 수를 보인다. 빼면 판 이전이 그 구성요소를 묘비로 두고 되돌리면 되찾는다(추정). 시트 정체의 무작위 동작 시험에 '빼기·되돌리기'를 더해 먼저 재현한다.
- 옛 앱은 이 파일을 몰라 도면이 다시 보인다(잃는 것 없음). 영구 삭제는 만들지 않는다.

### 10.4 F1 DEXPI 한 번에(Sonnet medium)

- 웹 내보내기가 폴더를 묻지 않고 채팅과 같은 시각 폴더(`output/exports`)에 쓴다(`hazop/shell/chat_actions.py` 993의 `_AutoSave`).
- **쪽별로 뺀다.** 지금은 한 쪽이라도 `ExportError`면 아무 파일도 쓰지 않는다(`dexpi_export.py` 1006, 1010). 걸린 쪽만 까닭과 함께 `not_exported`에 넣고 나머지를 낸다.
- 끝나면 낸 쪽 수, 뺀 쪽과 까닭(번호 없음, 추출만 됨, 검사 실패), 구성요소를 몇 개 뺐는지 한 줄로 보인다.
- `level` 조건은 P14의 새 결정 뒤에 넣는다.

### 10.5 파일 주인 표

| 파일 | C1 | C2 | G | F1 | s-viewer(화면) |
| --- | --- | --- | --- | --- | --- |
| `hazop/extract/*`, `hazop/register/titleblock.py`, `hazop/register/registry.py`, `hazop/graph/build.py`, `hazop/kg/claims.py`, `hazop/kg/screen.py` | 주인 | | | | |
| `hazop/graph/sources.py`, `hazop/app/project_ctx.py`, `hazop/kg/auto.py` | | | 주인 | | |
| `hazop/export/dexpi_export.py` | | | | 주인 | |
| `hazop/export/study_xlsx.py`, `hazop/ie/bundle.py`, `hazop/study/ai_cells.py`(실행 기록) | C1 뒤 따로(결과물 표시 단위) | | | | |
| `hazop/shell/register_flow.py`, `ai_image_flow.py`, `api_aireview.py`, `api_titleblock.py`, `api.py` | | 주인 | | | 읽기만 |
| `hazop/shell/api_drawings.py` | | `status`의 `level` | 빼기 명령 | `_export` | C2 → G → F1 뒤 |
| `hazop/shell/api_next.py`, `api_queue.py`, `hazop/shell/web/**` | | | | | 주인 |
| `hazop/chat/actions.py`, `hazop/shell/chat_actions.py` | | 주인 | C2 뒤 | C2 뒤 | 읽기만 |

차례는 C1 → 처음 보는 쪽 통과 판정(4.5) → C2 → 결과물 표시 → G → F1이다. F2(DEXPI 중심 구조)는 [dexpi-core-review.md](dexpi-core-review.md)에서 따로 판정한다.

## 11. 총괄이 판정할 선택지

'뒤집음'은 앞서 낸 권장안이나 총괄 권장안과 다른 것이다.

| 번호 | 선택지 | 권장안 | 근거 | 뒤집는 비용 |
| --- | --- | --- | --- | --- |
| P1 | 상태 표현: `state`에 auto 추가 / `level`을 따로 | `level` | 2.1, 2.4 실측 | 낮음 |
| P2 | 자동 표시: 새 칸 / `by`의 예약 값 | 예약 값 `hazop:auto`, 모든 진입에서 거절 | 2.4 | 중 |
| P3 | 종류 문턱 0.60 / 0.70 / 0.80 | 0.70, 새 표준 판 42/44(네 쪽). 처음 보는 쪽 통과 판정 뒤에 켬 | 4.2, 4.5 | 낮음(상수 하나) |
| P4 | 태그 자동 수락 | 0.70으로 받음 | 8/8(세 쪽) | 낮음 |
| P5 | 위치·연결·나누기·다시 확인 | 받지 않음 | 4.2 | 낮음 |
| P6 | 글 입력(drawio·DEXPI·스캔) | **부르지 않음(앞 권장안 '후보만'을 뒤집음).** drawio·DEXPI는 AI 없이 자동 확정, 스캔은 추출만 | 8장. 자동 외부 전송이 준다 | 낮음 |
| P7 | 번호가 빈 쪽 | **내용은 자동 확정, 번호만 미확정(총괄 권장안을 뒤집음)** | 개발용 8쪽 모두 번호 후보 없음. 대신 같은 도면이 여러 번 들어가는 위험(6.3) | 낮음(규칙 한 줄) |
| P8 | 번호가 겹친 쪽 | **총괄 권장안대로 `waiting(taken)`, 채팅으로 물음(앞 권장안을 뒤집음)** | 6.3 | 낮음 |
| P9 | 자동 확정 뒤 기본 보기 | 원본 | §3.8 4 | 낮음 |
| P10 | 실행당 300회의 단위 | 올리기 묶음 전체, 자료 누적 20, 시도 3 | 8장 | 중 |
| P11 | 사람 확정 기능 | 엔진에 남기고 화면에서 뺌. 채팅 확정은 확인 상자가 견줌을 함께 적게. 다만 벡터 PDF는 남은 것을 세지 못해 지금 확정할 수 없음 | 2.2, 7.2 | 중 |
| P12 | 자동 값의 지식 상태(P16과 묶어 다시 판정) | 태그·속성 주장은 `hypothesis`, 종류는 노드 표시 | 5장. 주장만 바꾸면 종류가 빠진다 | 중 |
| P13 | 이어 하기 시점 | 앱 열기·연결 준비·다음 올리기 | 조용히 되풀이 호출하지 않음 | 낮음 |
| P14 | DEXPI가 자동 확정을 받음 | 받음. **새 결정 줄과 HZ-PLN-22 §6.1 개정이 먼저(앞 권장안은 조건 없이 받음)** | 9장 | 낮음 |
| P15 | G에서 빼기 표시의 자리 | 새 기록 파일, 거르기는 후보 모으기 한 곳 | 10.3 | 중 |
| P16 | 자동 값·미확인을 AI 분석 맥락에 싣기(P12와 묶어 다시 판정) | 결과물 표시 단위 다음에 함. 그 전까지 5장 고지로 한계를 알림 | 틀린 자동 수락이 분석까지 흔적 없이 간다. 요청 글이 바뀌면 고정 응답 열쇠와 앞선 측정이 어긋난다 | 중 |
| P17 | 겹친 번호 쪽을 고를 때까지 프로젝트 그래프에서 빼 둠 | G가 들어온 뒤 함. 그 전에는 고지 | 6.3 실측(겹친 태그 13) | 중 |
| P18 | 범례판: 표준 판 고정 / 프로젝트 판으로 재서 씀 | 표준 판 고정. 프로젝트 판은 구독 호출로 재야 하므로 총괄 승인 뒤 | 4.1 | 낮음 |

**사용자 승인이 꼭 필요한 것**(9장): 올리는 즉시 외부 전송, 보안 등급 자료의 자동 전송, DEXPI 내보내기 조건 바꾸기(P14), 영구 삭제.

## 12. 쓴 원칙, 하지 않은 것

- 쓴 원칙: 도메인 모델링(`level`을 상태에서 떼어 냄), 멱등(단계마다 지금 자료를 보고 정하고 `read_key`로 다시 부르지 않음), 경계(자동 규칙을 순수 함수 `auto_block` 한 곳에 둠), 수의 설명(4.2 판별로 분모를 나누고 쪽 묶음을 봄).
- 검토(hazop-reviewer, 2026-11-25) 지적을 반영한 판이다. 지적한 사실은 46b973ac 코드로 다시 돌려 확인했다(번호 확정 앞뒤, 옛 판 추출, 빈 번호 중복, 빈 쪽, 번호 밀림, 표준 판 재생).
- 자동 수락을 켠 도면 한 장의 끝에서 끝까지를 앱으로 돌려 보지 않았다(코드 변경이 없는 단위). 여러 모델을 견주는 설계 경쟁(arena)은 하지 않았다.
- 글 입력·프로젝트 판·처음 보는 쪽의 확신도별 정밀도, 번호 후보 정확도, 같은 번호 동시 등록의 실제 경합, 도면 빼기·되돌리기의 판 이전은 재지 못했다.

## 13. C1에서 만든 것(2026-11-25, 브랜치 feat/auto-confirm)

총괄 판정은 P1~P18 모두 권장대로다(P7 내용만 자동 확정, P8 `waiting(taken)`, P6 글 입력은 부르지 않음). 자동 수락은 `ai_review.AUTO_ACCEPT_ENABLED = False`, 번호 자동 확정은 `titleblock.AUTO_NUMBER_ENABLED = False`로 꺼 둔 채 들였다. 켜는 것은 총괄 몫이다.

### 13.1 C2가 부를 함수

| 함수 | 하는 일 |
| --- | --- |
| `titleblock.auto_confirm_number(project_id, material_id, store_root=None)` → `{"registration_file", "confirmed", "why"}` | 등록 바로 뒤, 추출 앞에서 부른다. 추출은 돌려준 `registration_file`로 한다. `why`는 None·`off`·`not_ready`·`extracted`·`empty`·`multi_page`·`reserved`·`taken`·`has_records`. `taken`이면 `record_auto(이름, "waiting", "taken")`을 적고 AI를 부르지 않는다 |
| `confirmation.record_auto(name, result, why=None, ai=None, accepted=0, unconfirmed=None, attempts=0, by="hazop:auto", key=None, restart=False)` | 새 자료를 추출하면 `("waiting", "started")`를 먼저 적는다. 사람이 다시 시키면 `by=사람, restart=True`. 되돌린 쪽에 그냥 적으면 `AutoReverted` |
| `confirmation.sheet_confirmation(name)` | `level`·`auto`·`read_key`·`unconfirmed_targets`·`auto_accepted`·`components`·`validation_status`가 더해짐. `state`는 그대로 |
| `confirmation.auto_resumable(status)` | 이어 하기 대상인가. `auto` 기록이 없는 옛 쪽은 아니다 |
| `ai_review.auto_asked(doc, read_key)`, `ai_review.auto_calls_left(doc)` | 이 읽기에 다 물었는가(참이면 부르지 않고 `auto_finish`만), 자료 누적 20회에서 남은 호출 |
| `ai_review.merge_and_save(name, ex, result, via, model, auto=True)` | 자동 실행은 `auto=True`로 저장한다. `image_input_for(…, drawings=())`로 물은 실행만 '물음'으로 센다 |
| `ai_review.auto_finish(name, original_ex)` → `{"result", "why", "accepted", "blocked"}` | 실행을 저장한 뒤 도면 잠금 안에서 부른다. 결과 정하기(2.3) → 수락 → 기록. 어디서 끊겨도 다시 부르면 같은 끝 |
| `ai_review.auto_revert(name, by, confirm=None)` → 지운 `op_id` | 도면 한 장 되돌리기. 기댄 사람 고침이 있으면 `RevertNeedsConfirm` |
| `ai_review.send_policy(project_id)` → `"deny"`·`"allow"`·None | 프로젝트의 'AI로 보내지 않음'. None은 정하지 않음(지금까지의 동작). `ai_review.run`은 `deny`면 한 번도 부르지 않고 `refused`를 낸다(자동·수동 모두) |

저장 꼴은 2.2의 `auto` 칸(더해진 칸: `attempts`는 실행 기록에서 셈), `runs[]`의 `read_key`·`auto`, 후보의 `input`·`legend_source`·`wide`, 노드 `human_edit.auto`(연산 이름), 그래프 노드 `auto`(`kind`·`tag`)와 `origin: ai_auto`, `data/ai-review/send-policy/<프로젝트>.json`이다. 보내기 정책 파일은 `{"kind": "hazop_ai_send_policy", "schema_version": "0.1", "project_id", "send": "deny"|"allow", "by", "at", "reason"}`이고, 읽을 수 없으면 `deny`로 본다. 기본값은 정하지 않았다.

### 13.2 설계와 달라진 것

| 자리 | 달라진 것 | 까닭 |
| --- | --- | --- |
| 4.4 태그 근거 | 추출 노드는 `ai_auto`, 그래프 노드는 `ai_auto [추론]` | `hazop/kg/auto.py`가 추정 태그를 `[추론]` 글자로만 가린다. 그 파일은 G 몫이라 그래프가 글자를 붙인다. 화면에 나오는 '계통 접두를 추정한 값'이라는 설명은 자동 태그에는 맞지 않는다(G에서 고칠 것) |
| 2.2 `attempts` | 기록에 더하지 않고 자동 실행 기록에서 셈(자료 전체) | 같은 일을 두 번 마무리해도 한 번으로 세려고 |
| 2.2 미확인 줄의 id | 줄의 id는 그대로, 수(`unconfirmed_targets`)만 맞춤 | 줄을 바꾸면 끈 상태에서 정리 보기 동작이 바뀐다. 줄은 C2 |
| 3장 | 물음·수락·기록을 잇는 `auto_finish`와 `auto_outcome`(2.3 전이를 정하는 순수 함수)을 더함 | 차례가 셸과 엔진에 나뉘면 끊겼을 때 같은 끝이 되지 않는다 |
| 3장 | 이미 이 읽기로 자동 확정된 쪽은 다시 수락하지 않음 | 꺼진 채 확정된 쪽이 켠 뒤 소급해 수락되지 않게 |
| 2.3 되돌림 뒤 다시 시킴 | 다시 물을 수는 있으나 되돌린 자리는 자동으로 다시 받지 않음 | 사람이 물린 것을 다시 넣지 않음. 사람이 하나씩 수락하는 길은 열려 있음 |
| 4.3 규칙 3 | 사람이 수정 기록에서 바로 지운 AI 연산의 자리도 보호 | 옛 앱이 후보 문서를 거치지 않고 지울 수 있음 |
| 4.3 | 문턱·과제·필드·입력·범례판은 `AUTO_RULES` 한 곳. 사람 값 보호·되돌림·모순·상자·태그 겹침·글자 원·넓혀 묻기는 풀 수 없음 | 총괄 추가 지시 2026-11-25 |
| 4.1 | 자동 실행은 아무도 정하지 않은 옛 후보를 새 답으로 갈아 끼움. 사람이 한 번이라도 정한 후보와 사람이 시킨 실행은 지금처럼 덮지 않음 | 프로젝트 판으로 물은 옛 후보나 번호가 밀린 후보가 같은 `cand_id`로 새 답을 막는다 |
| 6.2 | 까닭 코드 `off`·`not_ready`·`extracted`를 더하고, 원본 고르기가 걸린 번호는 `has_records` | 코드를 나눠야 C2가 다음 일을 정한다 |
| 7.2 | `hazop/graph/sheets.py`의 안내 글과 `api_corrections`의 `status` 결함은 고치지 않음 | 10.1의 파일이 아님(C2) |
| 5장 DEXPI | 내보내기 코드는 그대로. 결정 줄과 HZ-PLN-22 §6.1 초안은 [auto-confirm-dexpi-draft.md](auto-confirm-dexpi-draft.md) | 10.4가 F1 몫으로 둠 |

알아 둘 것. `corrections.py`가 기준 추출의 코드 지문에 들어 있어(`FINGERPRINT_MODULES`), 나누기가 든 쪽은 기준 추출을 한 번 다시 짓고 그 쪽의 사람 확정이 풀린다. 그래프 판·규칙 판·기준값은 바꾸지 않았다.

## 14. 자동을 더 넓히는 선택지(총괄 추가 지시, 2026-11-25)

**표를 읽는 조건.** 저장된 응답을 지금 코드로 재생한 값이고 새 호출은 0이다. 자료는 개발용 쪽뿐이며 보류 6쪽은 열지 않았다. 문턱을 고른 자료와 잰 자료가 같고 프롬프트·범례판도 이 쪽들을 보며 고쳤으므로 처음 보는 도면에서는 낮아질 수 있다. 부트스트랩 하한이 100%로 나온 줄은 쪽이 넷 이하이고 틀린 것이 없어서 그렇게 나온 것이지 100%를 뜻하지 않는다. 보류 쪽은 총괄의 통과·실패 판정(4.5)에만 쓰고 문턱을 고르는 데 쓰지 않는다. 다시 내기: `scripts/check_auto_accept.py`와 시험 폴더 `fixflow\autoconfirm-c1\options.py`(결과 `options.out`).

### 14.1 문턱(새 표준 판 5쪽, 4.3 규칙 전부)

| 문턱 | 종류 채움 | 종류 맞음 | Wilson 하한 | 쪽 부트스트랩 하한 | 쪽별(007·019·099·133·134) | 태그 채움·맞음 |
| --- | --- | --- | --- | --- | --- | --- |
| 0.70 | 45 | 42/44 | 85% | 91%(네 쪽) | 2/2 · 18/20 · 8/8 · 없음 · 14/14 | 8 · 8/8 |
| 0.60 | 51 | 48/50 | 87% | 92%(다섯 쪽) | 2/2 · 19/21 · 8/8 · 4/4 · 15/15 | 17 · 17/17 |
| 0.50 | 67 | 54/66 | 71% | 69%(다섯 쪽) | 2/2 · 19/29 · 10/12 · 5/5 · 18/18 | 18 · 18/18 |

채움과 분모의 차이 1은 정답지 영역 밖(134쪽)이다. 문턱을 낮출 때 새로 생기는 틀린 종류 채움은 이렇다.

| 문턱 | 틀린 채움(누적) | 달라지는 것 |
| --- | --- | --- |
| 0.70 | 짝 없는 조각 → air_flow_arrow 2(019쪽) | 없는 구성요소가 그래프에 생긴다. 흐름 화살표라 고장 원인 후보는 되지 않을 가능성이 크다(추정) |
| 0.60 | 위와 같음(새로 늘지 않음) | — |
| 0.50 | air_flow_arrow 8, 짝 없는 조각 → relay_converter 2, 정답 check_valve → damper 2(099쪽) | **체크밸브를 댐퍼로 읽으면 역류 방지 기기가 사라진다.** 역류 편차의 방호와 원인이 바뀌어 판정을 뒤집을 수 있다. 없는 변환기는 계기 고장 원인을 만든다 |

참고로 다른 판의 값(합치지 않음, 확신도만):

| 판 | 0.70 종류 | 0.60 종류 | 0.50 종류 | 0.70 태그 | 0.60 태그 | 0.50 태그 |
| --- | --- | --- | --- | --- | --- | --- |
| 옛 표준 판 나머지 쪽 | 42/43(하한 88%·67%) | 55/56(91%·83%) | 62/66(85%·58%) | 0/0 | 0/0 | 0/4 |
| 정답지 판(앱에 없는 조건) | 97/103(88%·84%) | 112/125(83%·76%) | 130/144(84%·79%) | 8/8 | 19/23(63%·43%) | 21/25(65%·45%) |

괄호는 Wilson 하한과 쪽 부트스트랩 하한이다. 옛 판과 정답지 판의 037쪽은 0.50에서 종류 0/3·1/3, 태그 0/4로 나빠졌다. 정답지 판은 0.60에서 019쪽이 18/26이다. 새 표준 판의 0.60이 좋아 보이지만 새로 더 채운 것은 종류 6, 태그 9뿐이다.

**권고.** 0.70을 그대로 둔다. 0.60은 새 표준 판에서 틀린 것이 늘지 않았으나 다른 두 판에서 구간 값이 낮다. 총괄이 더 넓히고 싶으면 0.60까지이고, 0.50은 체크밸브를 댐퍼로 바꾸므로 권하지 않는다.

### 14.2 남는 220개의 까닭

| 쪽 | 종류 미정 | 채움 | 남음 | 기호 아님이라고 답함 | 모른다고 답함 | 문턱 미만 | 답 없음 | 상한 20회로 못 물음 | 묻는 대상이 아님 | 모순·태그 겹침 등 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 007 | 23 | 2 | 21 | 13 | 6 | 2 | 0 | 0 | 0 | 0 |
| 019 | 71 | 20 | 51 | 30 | 7 | 14 | 0 | 0 | 0 | 0 |
| 099 | 50 | 8 | 42 | 32 | 3 | 7 | 0 | 0 | 0 | 0 |
| 133 | 39 | 0 | 39 | 17 | 8 | 12 | 2 | 0 | 0 | 0 |
| 134 | 82 | 15 | 67 | 44 | 4 | 19 | 0 | 0 | 0 | 0 |
| **합** | **265** | **45** | **220** | **136** | **28** | **54** | **2** | **0** | **0** | **0** |

합은 136 + 28 + 54 + 2 = 220으로 맞는다. **상한 때문에 못 물은 기호는 하나도 없다.** 가장 큰 몫은 '기호 아님'(136)이다. 그 가운데 정답지 영역 안이 132이고 34는 정답 기호와 짝지어지는 자리였다(AI가 조각으로 잘못 보았거나, 위치로만 짝지어진 것이다). 나머지 98은 실제로 기호가 아닌 선 조각·글자 상자라, 종류를 채우는 것이 아니라 '기호 아님'으로 닫아야 미확인이 준다. 지금은 '기호 아님' 답이 후보로 저장되지 않아 닫을 길이 없다(새 과제이며 이 단위에서 하지 않음).

### 14.3 P5에서 뺀 후보를 받으면

| 과제 | 저장된 답 | 실제로 더 채워지는 수 | 틀렸을 때 |
| --- | --- | --- | --- |
| 다시 확인(종류) | 새 판 19/19(0.70 이상 15/15, 019쪽만), 정답지 판 20/21(117쪽 하나 틀림) | **0.** 추출이 읽은 값과 모순이라 안전 규칙이 막는다. 받으려면 '추출과 모순' 규칙을 풀어야 하므로 문턱 문제가 아니다 | 스크립트가 맞게 읽은 종류를 AI가 덮는다 |
| 정상 위치 | 새 판 6/6(019쪽만), 정답지 판 6/6(019쪽만) | 6 | 열림·닫힘이 뒤집히면 정상 유로와 격리 상태가 바뀌어 편차의 원인·결과가 뒤집힌다 |
| 고장 위치 | 새 판 1/1(019쪽만), 옛 판 2/3(037쪽), 정답지 판 3/4 | 1 | **고장 시 열림·닫힘이 뒤집힌다.** 공기·전원 상실 때 밸브가 어느 쪽으로 가는지가 반대가 되어 안전측·비안전측 판정이 바뀐다. 저장된 답에서 이미 4건 가운데 1건이 틀렸다 |
| 연결(그림 입력) | 자료 없음(앱에서 꺼져 있고 저장 응답이 없다) | 자료 없음 | 없는 배관을 이으면 전파 경로가 생기고, 있는 배관을 놓으면 원인이 끊긴다. 구간 나누기와 판정이 함께 바뀐다 |
| 연결(글 입력 012·063쪽 @dd86ea4) | 18건 가운데 새 정답 쌍 5(4.2, 확신도 저장 안 됨) | 문턱을 걸 수 없음 | 위와 같음 |
| 종류·태그(글 입력 같은 실행) | 종류 29/32, 태그 8/9(4.2, 확신도 저장 안 됨) | 문턱을 걸 수 없음 | 종류 3·태그 1이 틀렸다. 벡터 PDF에서는 그림 입력과 같은 자리를 묻는다. drawio에서 잰 자료는 없다 |
| 덩어리 나누기 | 기록(실측 9, 개발용 12쪽 136호출, 정답지 판): 종류 +8, 태그 +6, 연결 +12, 맞음→틀림 0, 새 오검출 종류 2·태그 1. 확신도별 값은 자료 없음 | 후보 13 | 없는 기호가 생기고 배관 끝이 그리로 옮겨 간다. 기준 추출을 다시 지어야 해 도면 한 장에 수십 초가 더 든다 |

**권고.** 어느 것도 더하지 않는다. 정상 위치는 값이 좋지만 한 쪽에서만 나왔고 틀렸을 때의 영향이 크다. 자료가 있는 쪽을 늘린 뒤 다시 판정한다.

### 14.4 상한을 올리거나 묶음을 키우면

| 조건 | 물은 항목(개발용 12쪽 1,056개) | 첫 묻기 호출 | 상한에 걸린 쪽 |
| --- | --- | --- | --- |
| 묶음 10, 상한 20(지금) | 1,056 | 112 | 없음(가장 많은 141쪽이 19) |
| 묶음 10, 상한 30·40·없음 | 1,056 | 112 | 없음 |
| 묶음 15(상한 무관) | 1,056 | 75 | 없음 |
| 묶음 20(상한 무관) | 1,056 | 60 | 없음 |

- 개발용 12쪽에서는 상한을 올려도 **더 묻는 기호가 0개**다. 다만 141쪽은 첫 묻기만 19회라 넓혀 묻기와 다시 확인 몫이 1회만 남는다. 넓혀 묻지 못한 밸브는 규칙 10이 막으므로, 그런 쪽에서는 상한 30이 수락을 조금 늘릴 수 있다(추정, 밸브 종류 후보 수에 달림).
- 시간: 저장된 실행 기록(개발용 쪽, 모두 새로 부른 실행 145건, 오류 0)에서 호출당 평균 12.4초(1,503호출 18,567초), 중앙 12.8초, 최소 6.6·최대 19.2초다. 여러 실행이 나란히 돌았을 수 있어 혼자 돌 때와 다를 수 있다. 12쪽 112호출이면 약 23분, 묶음 15는 약 16분, 묶음 20은 약 12분이다(호출당 시간이 같다고 본 추정. 조각이 늘면 호출당 시간도 늘 수 있다).
- 한 호출에 더 많은 조각을 묻는 꼴은 잰 적이 없다. 묻는 꼴이 바뀌면 확신도 눈금과 정확도가 달라지고 저장 응답도 다시 쓸 수 없어, 4장의 문턱 근거가 사라진다.

**권고.** 상한 20과 묶음 10을 그대로 둔다. 남는 220개는 호출이 모자라서가 아니라 답의 내용 때문이다.
