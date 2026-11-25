# 자동 확정 설계(C0): 올리면 읽고, AI가 메우고, 지식그래프에 들어가기

- 작성: 자동 확정 설계 하위 세션(poteto-mode), 2026-11-25. 코드 기준은 `feat/drawing-knowledge`의 46b973ac. 코드는 고치지 않았다. 아래 행 번호는 모두 이 커밋의 것이다.
- 근거: `INTENT.md` §3.8 끝 '화면 단순화(사용자 결정 2026-11-25)'. 읽기 정확도를 올리는 단위는 다시 열지 않는다(사용자 결정 2026-11-23).
- 앞선 자료: [쪽 확정 명령](sheet-commands.md), [표제란 명령](titleblock-commands.md), [시트 정체](sheet-identity-design.md), [이름 바뀜 잇기](sheet-rename-design.md), [입력 연산](fix-input-ops-design.md), [판 이전](migration-map-design.md), [그림 입력 실측](ai-image-review.md), [읽기 품질 기록](read-quality-log.md)
- 표시: 값 옆의 '실측'은 이 단위에서 돌려 본 것, '기록'은 앞선 문서의 값, '추정'은 확인하지 않은 것이다.

## 0. 결론

1. 지식그래프에 들어가는 길은 지금도 사람 확정을 기다리지 않는다. 추출이 끝나면 그래프와 지식그래프를 바로 짓는다(`hazop/app/data.py` 336, 489). 구간·분석·초기사건도 쪽 확정을 보지 않는다. 쪽 확정을 조건으로 거는 곳은 **DEXPI 내보내기, 정리 보기 기본값, 안내 줄, 채팅 동작 둘**뿐이다(7장 전수 표).
2. 그래서 새로 만들 것은 세 가지다. 추출에 이어 AI 검토를 돌리고 확실한 후보를 수락하는 흐름, 그 결과를 사람 확정과 가르는 표시, 그 표시를 결과물까지 남기는 일이다.
3. 사람 확정(`state`)은 손대지 않고 **확정 수준(`level`)** 을 따로 둔다. 값은 `human`(사람 확정), `auto`(자동 확정, 미확인 n곳), `extracted`(추출만 됨) 셋이다. 상태 값을 하나 더 넣는 안은 2장에서 버렸다.
4. 자동 수락은 **그림 입력의 종류·태그 후보 가운데 확신도 0.70 이상**부터 시작한다. 개발용 11쪽에서 종류 84/87, 태그 8/8이다(실측, 4장). 위치(NO·FC 등), 연결, 덩어리 나누기, 다시 확인은 문턱을 정할 자료가 모자라 자동으로 받지 않는다.
5. **총괄 권장안 하나를 뒤집어 제안한다.** '번호가 비면 자동 확정하지 않음'을 그대로 쓰면 APR1400 같은 도면은 한 장도 자동 확정되지 않는다. 개발용 8쪽의 표제란 번호 후보가 8쪽 모두 비어 있었다(실측, 6장). 번호만 미확정으로 두고 쪽 내용은 자동 확정하는 편이 사용자 결정의 흐름에 맞는다.
6. 지금 그대로 자동 실행을 켜면 **실행당 300회 상한이 걸리지 않는다.** 파일마다 작업이 따로 생기고(`hazop/shell/api.py` 371) 작업마다 300회를 새로 센다(`hazop/shell/register_flow.py` 69). 상한을 올리기 묶음 전체로 옮기는 일이 C2의 첫 완료 기준이다.
7. 켜기 전에 사용자 확인이 필요한 것이 하나 있다. 지금은 안내를 본 사람의 도면 조각만 자동으로 보낸다(`hazop/shell/ai_image_flow.py` 35). 올리는 즉시 보내면 외부 전송 범위가 넓어진다(9장).

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
| 추출 뒤 자동 AI 검토는 설정 `extract_ai_review`가 켜졌을 때만 돌고, 후보만 만들고 수락하지 않는다 | `register_flow.py` 41~79 | 코드 |
| 그림 입력은 종류·태그만 묻는다. 연결 묻기는 앱에서 꺼져 있다(`connect` 기본 0) | `ai_review.py` 381, 644, `ai_image_flow.py` 207 | 코드 |
| 다시 찾기. 연산은 바탕 지문으로 번호가 밀려도 따라가지만, 후보(`cand_id`)는 순번 id(`pdf-p0-sym-…`)라 다시 추출하면 다른 기호를 가리킬 수 있다 | `hazop/extract/corrections.py` 678, 699, `ai_review.py` 433 | 코드 |

**덤으로 찾은 결함(기존).** `hazop/shell/api_corrections.py` 217과 403이 `sheet_confirmation(name)["status"]`를 읽는다. 그 답에는 `status`가 없고 `state`만 있어 늘 `None`이다(실측). 그래서 도면 고치기 확인 글의 '쪽 확정이 풀릴 수 있습니다'(`hazop/shell/chat_edits.py` 249, 368)가 한 번도 나오지 않는다. C1이 이 자리를 `level`로 바꾸면서 함께 고친다.

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
         "extraction": "sha256:…", "why": null,
         "ai": {"calls": 9, "left": 4, "status": "done | capped | skipped"},
         "accepted": 12, "unconfirmed": 31}
```

- 지문은 **추출 결과 하나**(`files.extraction`)만 묶는다. 수정 기록과 AI 후보가 바뀌어도 풀리지 않는다. 자동 확정은 '이 추출에 스크립트와 AI가 한 번 다 돌았다'는 뜻이지 내용을 보증하는 말이 아니기 때문이다. 내용은 미확인 수로 말하고, 그 수는 읽을 때마다 다시 센다. 저장한 `unconfirmed`는 그때의 값을 남기는 기록용이다.
- `level` 계산은 한 함수다: `state == "confirmed"`이면 `human`, 아니면 `auto.result == "confirmed"`이고 `auto.extraction`이 지금 추출 지문과 같으면 `auto`, 나머지는 `extracted`.
- 미확인 n은 `check()`가 센 자리 가운데 **서로 다른 대상 수**로 보인다(`unconfirmed_targets`). 지금 `counts.total`은 한 기호를 '종류 미정'과 'AI 후보 남음'으로 두 번 세므로(`confirmation.py` 186, 211) 그대로 보이면 부풀려진다.

### 2.3 상태 전이

| 지금 수준 | 사건 | 다음 수준 | 하는 일 |
| --- | --- | --- | --- |
| (없음) | 새 자료 등록, 추출 성공 | extracted | `auto.result=waiting, why=started`를 먼저 적는다. 중간에 앱이 꺼져도 끝나지 않은 쪽으로 알아본다 |
| extracted | AI 검토 끝(물을 곳 없음 포함, 도면당 상한에 걸려 남은 것 포함)과 자동 수락 | auto | 후보 저장 → 수락 → 기록 순. 남은 것은 미확인 n |
| extracted | AI 연결 없음, 사용 한도, 멈춤, 실행당 상한 | extracted | `waiting`과 까닭(no_connection·limit·stopped·run_cap·error) |
| auto | 채팅 고침, 실행 취소, 후보 수락·거절 | auto | n만 바뀐다. AI를 다시 부르지 않는다 |
| auto | 다시 추출(추출 지문이 바뀜) | extracted | 이어 하기. 수정 기록과 수락은 남는다(기존 다시 얹기) |
| auto | 이 도면의 자동 수락 되돌리기 | extracted | `auto.result=reverted`와 한 사람. 사람이 다시 시키기 전에는 저절로 돌지 않는다 |
| auto·extracted | 사람 확정(견줌 + 확정) | human | 지금 명령 그대로 |
| human | 세 파일 가운데 하나가 바뀜 | auto 또는 extracted | 사람 확정이 풀리면(지금 규칙) 자동 기록이 유효한지로 정한다 |
| human | 사람 확정 해제 | auto 또는 extracted | 자동 기록은 지우지 않는다 |

### 2.4 옛 앱·옛 자료와의 호환(위험을 실제로 돌려 봄)

옛 앱이 새 파일을 잘못 다뤄 잃는 일이 있는지 46b973ac 코드를 옛 앱 구실로 돌렸다(임시 작업 루트, SNP 한 장).

| 확인 | 결과 |
| --- | --- |
| `auto` 칸이 든 기록을 옛 코드가 읽음 | 오류 없음. 상태는 open. 자동을 사람 확정으로 보지 않음 |
| 옛 코드가 견줌·확정·해제를 씀 | `auto` 칸이 그대로 남음 |
| 값이 깨진 기록을 옛 코드가 해제 | `auto` 칸이 사라짐. 그 쪽은 extracted로 내려감(덜 확정되는 쪽이라 받아들임) |
| 기록 판을 0.2로 올림 | 옛 코드가 `ValueError`. 그 쪽을 내보내지도 확정하지도 못함 → **판을 올리지 않는다** |
| `by: hazop:auto`로 수락한 연산을 옛 코드가 되돌리고 사람이 다시 수락 | 같은 `op_id`로 되살고 `by`·`accepted_by`가 사람으로 바뀜 |
| 사람이 고친 자리에 자동 수락 | 거절(`사람이 고친 자리라 AI 후보로 덮지 않음`) |

자동 표시를 새 칸이 아니라 **`by`·`accepted_by`의 예약 값 `hazop:auto`** 에 싣는 까닭도 여기 있다. 두 칸은 이미 누가·언제 칸(`corrections.py` 127 `PROVENANCE`)이라 되살리기 규칙이 그대로 통한다. 연산에 새 칸(`auto: true`)을 넣으면 옛 앱이 되돌렸다 되살릴 때 사람 수락에도 그 칸이 남아 사람의 것을 자동으로 적는다(`ai_review.py` 1001, 코드). 검토자 이름 설정(`api.py` 533)은 `hazop:`로 시작하는 이름을 거절한다.

판 이전 §21의 교훈(옛 앱이 새 꼴을 '모르는 줄'로 보고 잃은 것으로 굳힘)은 이 설계에 걸리지 않는다. 검토구간·판 이전 파일의 꼴은 바꾸지 않는다. 다만 그래프 노드에 자동 표시를 더하면(5장) 자동 연산이 있는 쪽의 `graph_version`이 옛 앱과 새 앱에서 다르다. 앱을 오가면 그 쪽의 판 이전이 한 번 더 돌지만 구성요소 id는 같다(추정, C1 시험에 넣음).

## 3. 흐름(C1 엔진, C2 셸)

```
등록(registry.register)
  → 표제란 번호 자동 확정(비지 않고 겹치지 않을 때만, 6장)
  → 추출·그래프·지식그래프(data.extract_and_graph)
  → 확정 기록 waiting
  → AI 차례(engine.ai_turn)에서 도면마다 묻기(ai_image_flow.run_pages)
  → 도면마다: 자동 수락(ai_review.auto_accept) → 확정 기록(confirmation.record_auto)
  → 그래프 다시 짓기는 api_inputs.note로 모아서
```

단계마다 지금 있는 자료를 보고 할 일을 정한다(다시 돌려도 같은 끝). 번호가 이미 있으면 건너뛰고, 수락은 이미 수락한 것을 건너뛰고, 확정 기록은 같은 값이면 쓰지 않는다. AI를 다시 묻지 않으려고 실행 기록(`runs[]`)에 `source`(추출 지문과 추출기 판)를 적고, 같은 `source`로 끝난 실행이 있으면 묻지 않는다. 번호를 나중에 채팅으로 확정해 다시 추출할 때 이 칸이 호출을 아낀다. 지금은 마지막 실행 시각과 추출 파일 시각만 견줘(`hazop/shell/api_aireview.py` 269 `_after_extract`) 다시 추출하면 늘 '하지 않음'이 된다.

엔진 쪽 함수(서명만, 본문은 C1):

```python
# hazop/extract/confirmation.py
AUTO_BY = "hazop:auto"
def level(status): ...                       # "human" | "auto" | "extracted"
def record_auto(name, result, why=None, ai=None, accepted=0): ...   # 같은 값이면 쓰지 않음, store_io expect로 경합 거절

# hazop/extract/ai_review.py
AUTO_KIND_MIN = AUTO_TAG_MIN = 0.70
def auto_block(c, corrected, human, pending): ...     # 자동으로 받지 않을 까닭 또는 None(순수 함수, bulk_block 옆)
def auto_accept(name, original_ex): ...               # 잠금 안에서 부름 → {"accepted": [...], "blocked": {까닭: 수}}
def auto_revert(name, by, confirm=None): ...          # 이 도면의 자동 수락 전부

# hazop/register/titleblock.py
def auto_confirm_number(project_id, material_id): ... # → {"confirmed": bool, "why": None|empty|taken|multi_page|reserved|has_records}
```

`auto_accept`는 `accept()`를 그대로 부르되 고르기만 한다. 수락 규칙이 두 벌이 되지 않게 하려는 것이다.

### 3.1 AI 차례, 입력 연산 짓기 미루기와의 관계

- AI 차례(`hazop/shell/ai_gate.py`)는 한 번에 하나다. 자동 확정은 지금 추출 뒤 자동 검토와 같은 차례를 쓰고, 같은 스레드에서 다시 잡지 않는다(`Reentry`).
- 자동 수락은 나누기(`split`)를 받지 않으므로 기준 추출 짓기(`corrections.ensure_base`)가 필요 없다. 그래프 다시 짓기는 수락과 같은 길인 `api_inputs.note`(마지막 수락 뒤 10초 조용하면 도면마다 한 번)에 맡긴다. `note`는 낡은 그래프 표시를 디스크에 남기므로(`hazop/shell/sheet_refresh.py` 34 `defer`) 앱이 꺼져도 다음 열기에서 다시 짓는다.
- 여러 쪽을 잇달아 끝낼 때 쪽마다 짓지 않는다. APR1400 143쪽에서 저장 한 번의 판 이전이 3초 남짓(기록, 판 이전 §21, 구간 525개)이라, 쪽마다 지으면 그 시간이 쪽 수만큼 는다.
- 잠금 차례는 AI 차례 → 도면 잠금(`sheet_refresh.lock`) 한 방향만 쓴다. 도면 잠금을 쥔 채 AI 차례를 기다리지 않는다.

## 4. 자동 수락 규칙과 채점

### 4.1 채점 자료와 조건

| 자료 | 무엇 | 만든 조건(기록) |
| --- | --- | --- |
| 표준 판 5쪽 | 개발용 007·019·099·133·134, 그림 입력, 앱이 쓰는 표준 판(변형 칸 든 새 판) | @ef93f20 응답, 저장소 밖 시험 폴더 `highchip` |
| 표준 판 나머지 7쪽 | 037·051·077·080·103·117·141, 옛 표준 판 | @a2c1442 응답, 같은 폴더 |
| 정답지 판 11쪽 | 정답지로 만든 범례판(앱에는 없는 조건, 견줌용). 141쪽은 재생 오류라 빠짐 | 같은 폴더 |
| 글 입력 2쪽 | 012·063쪽, 확신도가 저장되지 않음 | @dd86ea4 |

채점은 이 단위에서 새로 했다(실측, 구독 호출 0). 추출은 46b973ac의 `pdf_vector`, 정답지는 저장소 밖 추가 정답지의 개발용 12쪽(`keys-dev`·`keys-dev2`), 짝짓기는 `scripts/check_read_quality.py`의 `match_symbols`다. 후보를 하나씩 적용해 맞은 수를 셌다. 추출이 바뀌어 상자가 0.6pt 넘게 달라진 후보(141쪽 36건)와 정답지 영역 밖 1건은 뺐다. 글 입력은 그 커밋의 코드와 정답지로 쟀다. **보류 6쪽(013·047·084·088·113·143)은 열지도 채점에 넣지도 않았다.** 개발용 쪽은 프롬프트와 범례판을 고치며 본 쪽이라 처음 보는 도면보다 좋게 나올 수 있다.

### 4.2 값(표준 판 11쪽)

| 확신도 | 종류 맞음/후보 | 95% 하한(Wilson) |
| --- | --- | --- |
| 0.80 이상 | 34/35 | 85% |
| 0.70~0.80 | 50/52 | 87% |
| 0.60~0.70 | 19/19 | 83% |
| 0.50~0.60 | 13/27 | 31% |
| 0.50 미만 | 25/48 | 38% |
| **0.70 이상** | **84/87** | 90% |
| 0.60 이상 | 103/106 | 92% |
| 전체 | 141/181 | 71% |

- 문턱 0.70에서 틀린 3건은 짝 없는 조각에 붙인 air_flow_arrow 2, damper 1이다. 맞던 값을 망친 것은 없다(묻는 곳이 종류 없는 기호뿐).
- 쪽 묶음을 갈라도 같다. 0.70 이상에서 `keys-dev` 35/36, `keys-dev2` 49/51.
- 정답지 판에서는 0.70 이상 97/103이지만 **0.60~0.70이 15/22**다. 확신도 눈금이 범례판에 따라 흔들리므로 0.60이 아니라 0.70을 권한다.
- '높음'(범례 견본과 같음) 표시는 문턱으로 쓰지 않는다. 개발용에서는 50/55였지만 보류 6쪽에서는 6/20이었다(기록, 실측 20).
- 표준 판 전체 정밀도 141/181(78%)과 보류 6쪽 108/145(74%, 기록: 높음 6/20 + 보통 102/125)는 비슷하다. 확신도별 값은 보류에서 잰 적이 없다.

| 과제 | 0.70 이상 | 전체 | 판단 |
| --- | --- | --- | --- |
| 종류(그림 입력) | 84/87 | 141/181 | 자동 |
| 태그(그림 입력) | 8/8(0.60 이상 17/17) | 22/26 | 자동. 다만 자료가 적다(0.70 이상 하한 68%) |
| 다시 확인(스크립트 값과 다른 종류) | 15/15 | 19/19 | 받지 않음. 19건이 모두 019쪽 manual_valve → damper 하나의 꼴이고 추출과 모순인 값이다 |
| 정상 위치 | 6/6 | 6/6 | 받지 않음. 한 쪽에서만 나옴 |
| 고장 위치 | 1/1 | 3/4 | 받지 않음. 틀리면 고장 시 열림·닫힘이 뒤집혀 원인·결과가 바뀐다 |
| 연결(글 입력) | 자료 없음(확신도 없음) | 18 가운데 새 정답 쌍 5, 정답과 오검출 1, 변화 없음 12 | 받지 않음 |
| 종류(글 입력) | 자료 없음 | 29/32(확신도 없음) | 받지 않음 |
| 태그(글 입력) | 자료 없음 | 8/9(확신도 없음) | 받지 않음 |
| 덩어리 나누기, 도면 밖 계통 | 자료 없음 | - | 받지 않음(나누기는 앱에서 꺼져 있음) |

### 4.3 규칙(`auto_block`)

하나라도 걸리면 수락하지 않고 후보로 남긴다. 남은 후보는 미확인으로 센다.

| 차례 | 조건 | 까닭 |
| --- | --- | --- |
| 1 | `status`가 proposed가 아님 | 이미 정한 것 |
| 2 | 사람이 되돌렸거나 거절한 후보(`decided_by`가 있고 `hazop:auto`가 아님) | 사람이 물린 것을 다시 넣지 않음 |
| 3 | 사람이 고친 자리(`human_targets`) | 지금 규칙 |
| 4 | 과제가 kind·tag가 아님, 또는 필드가 kind·tag가 아님 | 4.2 |
| 5 | 그림 입력으로 받은 후보가 아님(`match` 칸이 없음) | 확신도별 자료가 없음 |
| 6 | 확신도 0.70 미만 | 4.2 |
| 7 | 지금 값과 모순. 종류 후보인데 종류가 있거나, 태그 후보인데 태그가 있음 | 추출·사람 값을 이기지 않음 |
| 8 | 종류가 `LETTER_CIRCLE_KINDS`, `relay_converter`, `test_connection`, `pipe_cap` | 개발용 전체에서 transmitter 5/17, relay_converter 0/4, test_connection 0/4. pipe_cap은 옛 판 2/4이고 보류에서 4건 틀림(기록) |
| 9 | 태그가 같은 도면의 다른 구성요소에 이미 있거나, 다른 후보도 같은 태그를 냄 | 태그는 설비 식별자다. 겹치면 지식그래프가 둘을 하나로 잇는다 |

태그 후보가 그 자리 주변 글자에 실제로 있어야 하는 것은 이미 받을 때 검사한다(`ai_review.py` `_valid`·`_in_texts`).

### 4.4 사람 수정, 재추출, 되돌리기

- 사람 고침은 나중에 와도 이긴다. 채팅 고침(`drawing.edit`)은 자동 연산 뒤에 놓이고, 그 자리는 `human_targets`에 들어가 다시 자동 수락되지 않는다.
- 자동 연산은 바탕 지문으로 다시 찾으므로 재추출에도 남는다(`corrections.py` 699). 찾지 못하면 '적용 불가'로 남고 미확인으로 돌아간다.
- 되돌리기는 도면 한 장 단위다. `auto_revert`가 그 도면에서 `accepted_by == hazop:auto`인 수락을 한 번에 빼고, 기댄 사람 고침이 있으면 지금처럼 미리 알림(`RevertNeedsConfirm`)을 거친다. 지금 채팅의 되돌리기는 AI 수락 연산을 막고 AI 검토 패널로 보낸다(`api_corrections.py` 112, 524). 패널을 없애면 길이 없어지므로 C2에서 채팅 동작 `aireview.auto_revert`를 둔다.
- `confirmed_samples`는 자동 수락 종류를 견본에서 뺀다. 노드의 `human_edit`만으로는 자동인지 모르므로 `corrections._apply_one`이 `human_edit.auto`(자동 연산 이름 목록, 사람이 같은 종류로 덮으면 빠짐)를 적는다.

### 4.5 C1이 잴 것(자료가 모자란 곳)

- `scripts/check_auto_accept.py`(새 파일): 저장된 후보를 `auto_block`으로 걸러 '자동 수락 전/후' 맞은 수와 새 오검출을 낸다. 개발용 저장 응답으로 호출 없이 돈다.
- 보류 6쪽은 C1 세션이 돌리지 않는다. 총괄(또는 d-read)이 합계만 한 번 잰다(`CLAUDE.md` 규칙 19). 기준: 자동 수락 종류 정밀도 90% 이상이면 0.70 유지, 아니면 0.80으로 올린다.
- 글 입력(drawio·DEXPI·스캔)은 확신도가 든 저장본이 없다. 가상 도면 SNP의 글 입력 실행에서 확신도를 저장해 먼저 센다(구독 호출 6회 안팎, 총괄 승인 뒤).

## 5. 하류: 자동 확정을 어디까지 받나

| 하류 | 지금 거는 조건 | 자리 | 판정 |
| --- | --- | --- | --- |
| 지식그래프 | 없음(추출 직후 들어감) | `hazop/app/data.py` 336, 489, `hazop/kg/auto.py` | 받음. **출처를 고친다.** 자동 값은 `origin: ai_auto`, `method: ai`, 지식 상태 `hypothesis`로(`hazop/kg/claims.py` 70, `hazop/graph/build.py` 67). 지금처럼 두면 AI가 고른 태그가 '사람이 확정한 태그'로 남는다 |
| 검토구간(만들기·확정·잠금) | 쪽 확정을 보지 않음 | `hazop/study/nodes.py` 717, `hazop/study/node_tools.py` 402 | 받음. 막지 않음. 구간 확정 글에 그 구간이 든 도면의 수준과 미확인 수를 한 줄 |
| AI 분석 | 쪽 확정을 보지 않음. **도면의 미확인도 맥락에 실리지 않는다**(프로젝트 그래프의 `unknowns`가 늘 빈 목록, `hazop/graph/project.py` 541) | `hazop/study/ai_cells.py` 217 | 받음. 실행 기록 `ai_log`에 `sheet_levels: {도면: {level, unconfirmed}}`를 그 실행 때 값으로 남김. 구간에 든 구성요소의 미확인을 맥락에 싣는 일은 분석 요청이 바뀌는 것이라 따로 판정(P16) |
| 워크시트 Excel | 쪽 확정을 보지 않음 | `hazop/export/study_xlsx.py` 38 | 받음. '표지·요약'에 도면별 수준·미확인 수와 아래 고지 |
| 초기사건 인계 묶음 | 쪽 확정을 보지 않음 | `hazop/ie/bundle.py` 455, 533 | 받음. `source.sheet_levels`를 더함 |
| DEXPI 내보내기 | `state == "confirmed"`와 등록 번호 확정 | `hazop/export/dexpi_export.py` 188, 898, 943, 957, 1020 | `level`이 human·auto면 받음. 미확정 구성요소는 지금처럼 빼고 냄. `manifest.json`에 `level`·`unconfirmed`를 적음. 번호 조건은 유지 |
| 정리 보기 기본값 | PDF·래스터는 confirmed면 정리 보기 | `confirmation.py` 55, `hazop/shell/web/js/canvas/clean_view.js` 345 | 바꾸지 않음. 자동 확정은 원본이 기본. 도면 탭은 원본 위 확인 창이라는 결정(§3.8 4)과도 맞음 |
| 보고용 결과물 고지 | 없음 | 워크시트 표지, 인계 묶음 | 새로 둠. '이 도면은 자동 확정이며 미확인 n곳이 남아 있음. 처음 보는 도면의 읽기 정확도는 기호 종류 67.8%, 연결 58.6%(2026-11-18 측정)' |

## 6. 표제란 번호

### 6.1 사실

- 번호 후보는 등록 때 읽는다(`hazop/register/fileinfo.py` 142, 298). 첫 쪽만 본다.
- 번호가 이름(`graph-<번호>`)이 되려면 등록정보의 확정 번호여야 하고 한 쪽 자료여야 한다(`hazop/graph/sheets.py` `usable_number`). 없으면 `graph-<자료>-p<쪽>`, 화면 이름은 '파일 이름 · n쪽'이다.
- 번호를 바꾸는 가드는 `hazop/register/titleblock.py` 573 `_guard_number`다. 추출하지 않은 자료(`sheets`가 빔)에 번호를 주면 기록을 옮길 일이 없다.
- **APR1400 개발용 8쪽(007·019·037·051·080·103·133·134)의 번호·개정·제목 후보는 8쪽 모두 비어 있다(실측).** 그 도면은 번호 칸이 이 추출기가 읽는 표제란 꼴이 아니다. SNP 6장은 번호를 읽는다.

### 6.2 규칙

`auto_confirm_number`는 **추출 앞에서** 돈다. 아래가 모두 참일 때만 `titleblock.confirm(by=hazop:auto)`을 부른다.

1. 새로 등록한 자료다(추출 결과가 없다).
2. 번호 후보가 있고 `sheets.number_problem`이 없다(여러 쪽 자료, 임시 이름 꼴 제외).
3. 프로젝트의 다른 자료가 같은 번호를 쓰지 않는다. 형식이 달라도, 대소문자·특수 문자만 달라도 겹친 것으로 본다(`_others`, `_key`). 사람 확정은 형식이 다르면 알리고 통과시키지만(`titleblock.py` 569 `SHARED_NUMBER`) 자동은 멈춘다.
4. 사람이 고른 원본 형식(`drawing-sources`의 `chosen`)이 그 번호에 없다.

개정·제목 후보는 이름에 쓰이지 않으므로 번호와 따로, 있으면 함께 적는다. 검사와 새 판 쓰기는 프로젝트 잠금 하나 안에서 한다. 파일 여러 개를 한꺼번에 올리면 작업 스레드 둘이 같은 번호를 동시에 통과할 수 있다(`hazop/register/registry.py`에 잠금이 없음, 코드. 실제 경합은 재현하지 않음).

### 6.3 번호를 확정하지 못한 쪽

| 선택 | 얻는 것 | 잃는 것 |
| --- | --- | --- |
| 쪽 전체를 자동 확정하지 않음(총괄 권장안) | 이름이 굳기 전에 확정이라는 말을 쓰지 않음 | APR1400 같은 도면은 한 장도 자동 확정되지 않음. 흐름 ②③이 끊김 |
| **내용은 자동 확정, 번호만 미확정(권장)** | 올리면 끝나는 흐름이 유지됨. 임시 이름으로도 지식그래프·구간·분석이 돌고(지금도 그렇다), 번호는 채팅으로 정하면 판 이전이 이름을 따라 옮긴다(시트 정체 U5) | 번호 없는 쪽은 도면 사이 연결과 DEXPI 내보내기에서 빠짐. 나중에 번호를 확정하면 다시 추출 한 번 |

번호가 비면 `auto.why`가 아니라 도면 줄의 번호 상태로 보인다. 번호가 겹친 쪽도 같다. 겹친 두 파일 가운데 어느 것을 쓸지는 지금 원본 고르기(`sources.conflicts`)가 맡고, 사람이 정하기 전에는 먼저 등록한 자료를 쓴다.

### 6.4 판 이전(ID)에 미치는 영향

- 번호를 추출 앞에서 확정하므로 첫 그래프부터 이름이 `graph-<번호>`다. 이름 바뀜 이전이 생기지 않는다.
- 나중에 채팅으로 번호를 확정하는 길은 지금 가드와 같다. 막음 자리(지식그래프 판단, 도면 연결 지정, 구간 제외 표시 등, `titleblock.py` `TODO`)에 기록이 있으면 막힌다. 자동 확정은 막음 자리에 아무것도 쓰지 않는다.
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
| `hazop/register/registry.py` 367~368 | 등록된 자료의 번호를 등록 경로로 바꾸지 못함 | 남음 | 자동도 이 길을 쓰지 않는다 |
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
| `hazop/shell/clean_items.py` 141 | 검토 표시(human·ai_accepted·script) | 바뀜 | `human_edit.auto`면 `ai_auto`. 지금 `ai_accepted` 가지는 추출 노드의 `origin`을 보는데 그 칸은 그래프에만 있어 타지 않는다(코드) |
| `hazop/graph/build.py` 67, `hazop/kg/claims.py` 70, `hazop/kg/screen.py` 416 | 고친 것은 모두 사람 것 | 바뀜 | 5장 |
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

**자동 확정 기록은 사람 확정과 다른 칸에 있고, 사람 확정을 묻는 코드는 그 칸을 보지 않는다.** 46b973ac 코드로 돌려 확인했다(2.4 표 1~2행). 그래서 C1만 들어가고 C2가 늦어도 지금 화면은 그대로 움직인다. 남은 위험은 아래 셋이다.

| 위험 | 어떻게 깨지나 | 가능성·피해 | 잡는 시험 |
| --- | --- | --- | --- |
| 자동 값이 사람 값으로 남음 | 그래프·지식그래프·범례판이 `human_edit`만 본다 | 높음·중 | 자동 수락 뒤 `origin`, 주장 상태, 견본 목록 |
| 같은 도면을 두 번 처리 | 등록 작업과 이어 하기, 채팅 'AI 검토 다시'가 겹침 | 중·낮음(호출 낭비) | `reserve_review`로 막고 두 스레드 시험 |
| 후보 id가 다시 추출로 밀려 다른 기호에 수락 | `cand_id`가 순번 | 중·높음 | 수락 직전 후보의 상자와 지금 대상의 상자를 견줘 다르면 건너뜀. 재추출로 번호를 민 자료로 시험 |

## 8. 과금과 실패

| 항목 | 규칙 |
| --- | --- |
| 도면당 상한 20 | 자동 경로는 설정값과 관계없이 `min(설정, 20)`. 지금 설정은 200까지 받는다(`api_aireview.py` 702, `api.py` 643) |
| 실행당 상한 300 | **올리기 묶음 전체**에 건다. 자동 작업이 하나도 없을 때 새 예산 300을 만들고, 도는 동안 들어온 등록 작업은 그 예산을 나눠 쓴다. 다 쓰면 남은 쪽은 `waiting(run_cap)` |
| 구독만 | `ai_image_flow.subscription_client` 그대로. API 연결이면 `waiting(no_connection)` |
| 연결 없음·한도·멈춤 | `waiting`과 까닭. 추출·그래프는 완료. 받은 답은 저장(`ai_image_flow.py` 168 `_tolerant`) |
| 이어 하기 | 앱을 열 때, AI 연결이 준비될 때, 다음 올리기 때 `waiting` 쪽을 등록 차례대로 한 번에 300회까지. 같은 추출에 끝난 실행이 있으면 그 쪽은 부르지 않고 수락만 |
| 소급 없음 | `auto` 기록이 없는 옛 쪽은 이어 하기 대상이 아니다. 사람이 채팅으로 'AI로 확정해 줘'라고 시킬 때만. 같은 파일을 다시 올려 `reused`가 된 옛 자료도 마찬가지다 |
| 예상 크기 | 쪽마다 10.75회(기록, 실측 14: 12쪽 129응답) → APR1400 143쪽이면 1,540회 안팎(추정). 300회 상한이면 다섯 번 남짓에 나눠 끝난다 |

## 9. 사용자 승인이 꼭 필요한 것

| 일 | 왜 | 하지 않고 적어 두는 방법 |
| --- | --- | --- |
| 올리는 즉시 도면 조각 그림을 AI에 보냄 | 지금 자동 검토는 안내를 보고 켠 사람만 보낸다(`ai_image_flow.py` 35). 사용자 결정은 'AI 검토가 곧바로 메운다'와 'AI는 처음에 한 번 연결한다'이고 보내는 범위 안내는 정하지 않았다 | 권장: 연결 화면에서 '올린 도면의 기호 조각과 주변 글자를 이 구독으로 보냅니다'를 한 번 보이고, 연결하면 동의로 적는다. 동의 기록이 없으면 글도 그림도 자동으로 보내지 않고 '추출만 됨'. 승인 전에는 C2를 이 기본값으로 만든다 |
| 보안 등급 자료 | 자동이라 사람이 막을 틈이 없다 | 프로젝트마다 '자동 AI 검토 안 함' 하나를 둔다(화면 단추가 아니라 채팅·설정 파일) |
| 도면 영구 삭제 | 되돌릴 수 없음 | G는 '목록에서 빼기(복구 가능)'까지 |

## 10. 구현 단위

### 10.1 C1 엔진(Opus medium, 저장·ID 경로)

- 파일: `hazop/extract/confirmation.py`, `ai_review.py`, `ai_images.py`, `corrections.py`(`human_edit.auto`, 예약 이름), `hazop/register/titleblock.py`, `hazop/graph/build.py`, `hazop/kg/claims.py`, `hazop/kg/screen.py`, `scripts/check_auto_accept.py`
- 완료 기준: 2.3 전이 표, 2.4 호환 표, 4.3 규칙 표, 6.2 규칙의 시험이 모두 있고, 4.2의 개발용 값이 `check_auto_accept.py`에서 같은 수로 나온다. `state`를 쓰는 기존 시험은 고치지 않고 통과한다.
- 재현 시험: (1) 추출만 → 자동 → 채팅 고침 → 자동 그대로, (2) 다시 추출 → 추출만, 수락 연산은 남음, (3) 번호가 밀린 재추출에서 다른 기호에 수락하지 않음, (4) 사람이 되돌린 후보를 다시 자동 수락하지 않음, (5) 사람이 고친 자리 보호, (6) 도면 단위 되돌리기와 기댄 사람 고침 알림, (7) 자동 종류가 범례판 견본에 들지 않음, (8) 그래프 `origin`·주장 `hypothesis`, (9) 같은 번호 동시 등록 두 스레드 → 하나만 확정, (10) 46b973ac 고정 코드로 읽는 옛 앱 시험(`auto` 칸이 남고 상태는 사람 확정이 아님), (11) 단계마다 중간에 끊긴 뒤 다시 돌리면 같은 끝.

### 10.2 C2 셸 흐름(Sonnet high)

- 파일: `hazop/shell/register_flow.py`, `api_aireview.py`, `ai_image_flow.py`, `api_titleblock.py`, `api.py`(실행 예산), `api_drawings.py`(`level`), `api_corrections.py` 217·403, 채팅 동작(`hazop/chat/actions.py`, `hazop/shell/chat_actions.py`)
- 완료 기준: 올리기 한 번으로 자동 확정까지 사람 동작 0. 143파일을 한꺼번에 올려도 호출 300회를 넘지 않는다(고정 응답 시험). 연결 없음·한도·멈춤에서 '추출만 됨'이 남고 이어 하기로 끝난다. 동의 기록이 없으면 아무것도 보내지 않는다.
- 재현 시험: 파일 30개와 도면당 20회 고정 응답으로 300에서 멈춤, 작업 중 앱 닫기, 이어 하기 두 번이 호출을 두 번 쓰지 않음, 같은 도면에 수동 실행이 겹침.

### 10.3 G 도면 빼기(Opus medium)

- `data/drawing-removed/<프로젝트>.json`에 `{자료, 쪽, by, at}`을 적고 `sources.pick` 앞에서 거른다(`hazop/graph/sources.py` 285). 프로젝트 그래프 입력 지문(`hazop/app/project_ctx.py` 134)에 이 파일을 넣는다. 원본·추출·그래프 파일은 지우지 않는다. `graph.json`을 비켜 두는 길은 쓰지 않는다. 비켜 둔 그래프는 '번호 확정 중 끊긴 자리'로 읽힌다(`hazop/app/data.py` 403).
- 빼기 전에 그 도면에 걸린 구간·분석 결과·초기사건 수를 보인다. 빼면 판 이전이 그 구성요소를 묘비로 두고, 되돌리면 되찾는다(추정. 시트 정체 퍼즈에 '빼기·되돌리기' 동작을 더해 먼저 재현).
- 옛 앱은 이 파일을 몰라 도면이 다시 보인다(잃는 것 없음).
- 영구 삭제는 만들지 않는다(사용자 승인 대기).

### 10.4 F1 DEXPI 한 번에(Sonnet medium)

- 웹 내보내기가 폴더를 묻지 않고 채팅과 같은 시각 폴더(`output/exports`)에 쓴다(`hazop/shell/chat_actions.py` 993의 `_AutoSave`). 끝나면 낸 쪽 수, 뺀 쪽과 까닭(번호 없음, 추출만 됨), 구성요소를 몇 개 뺐는지 한 줄로 보인다.
- `level` 조건과 `manifest.json`의 `level`·`unconfirmed`.

### 10.5 파일 주인 표

| 파일 | C1 | C2 | G | F1 | s-viewer(화면) |
| --- | --- | --- | --- | --- | --- |
| `hazop/extract/*`, `hazop/register/titleblock.py`, `hazop/graph/build.py`, `hazop/kg/*` | 주인 | | | | |
| `hazop/graph/sources.py`, `hazop/app/project_ctx.py` | | | 주인 | | |
| `hazop/export/dexpi_export.py` | | | | 주인 | |
| `hazop/shell/register_flow.py`, `ai_image_flow.py`, `api_aireview.py`, `api_titleblock.py`, `api.py` | | 주인 | | | 읽기만 |
| `hazop/shell/api_drawings.py` | | `status`의 `level` | 빼기 명령 | `_export` | C2 → G → F1 뒤 |
| `hazop/shell/api_next.py`, `api_queue.py`, `hazop/shell/web/**` | | | | | 주인 |
| `hazop/chat/actions.py`, `hazop/shell/chat_actions.py` | | 주인 | C2 뒤 | C2 뒤 | 읽기만 |

차례는 C1 → C2 → G → F1이다. F2(DEXPI 중심 구조)는 다음 문서에서 따로 판정한다.

## 11. 총괄이 판정할 선택지

| 번호 | 선택지 | 권장안 | 근거 | 뒤집는 비용 |
| --- | --- | --- | --- | --- |
| P1 | 상태 표현: `state`에 auto 추가 / `level`을 따로 | `level` | 2.1, 2.4 실측 | 낮음(C1 안) |
| P2 | 자동 표시: 새 칸 / `by`의 예약 값 | 예약 값 `hazop:auto` | 되살리기 규칙(2.4) | 중(쓴 연산을 바꿔야 함) |
| P3 | 종류 문턱 0.60 / 0.70 / 0.80 | 0.70 | 84/87, 정답지 판 0.60~0.70이 15/22 | 낮음(상수 하나) |
| P4 | 태그 자동 수락 | 0.70으로 받음 | 8/8(0.60 이상 17/17). 자료가 적어 C1에서 다시 셈 | 낮음 |
| P5 | 위치·연결·나누기·다시 확인 | 받지 않음 | 4.2 자료 부족. 고장 위치는 안전 쪽 | 낮음 |
| P6 | 글 입력(drawio·DEXPI·스캔) 자동 수락 | 받지 않음(후보만) | 확신도 저장본이 없음 | 낮음 |
| P7 | 번호 없는 쪽 | 내용은 자동 확정, 번호만 미확정 | 개발용 8쪽 모두 번호 후보 없음. 총괄 권장안과 다름 | 낮음(규칙 한 줄) |
| P8 | 번호 겹침(형식이 다른 파일 포함) | 번호를 자동으로 정하지 않음 | 6.2 | 낮음 |
| P9 | 자동 확정 뒤 기본 보기 | 원본 | §3.8 4 | 낮음 |
| P10 | 실행당 300회의 단위 | 올리기 묶음 전체 | 0장 6 | 중 |
| P11 | 사람 확정(견줌·확정) 기능 | 엔진에 남기고 화면에서 뺌. 채팅 확정은 확인 상자가 견줌을 함께 적게 | 7.2 | 중 |
| P12 | 자동 값의 지식 상태 | `hypothesis` | 지금은 AI 값이 사람 확정으로 남음(1장) | 중(지식그래프 다시 지음) |
| P13 | 이어 하기 시점 | 앱 열기·연결 준비·다음 올리기 | 조용히 되풀이 호출하지 않음 | 낮음 |
| P14 | DEXPI가 자동 확정을 받음 | 받음(뺀 수와 수준을 적음) | §3.8 11 | 낮음 |
| P15 | G에서 빼기 표시의 자리 | 새 기록 파일, graph.json은 그대로 | 비켜 둔 그래프는 다른 뜻(10.3) | 중 |
| P16 | 구간에 든 구성요소의 미확인을 AI 분석 맥락에 싣기 | 이번 범위 밖, 후속 | 요청 글이 바뀌면 고정 응답 열쇠와 앞선 측정이 어긋난다 | 중 |

사용자 승인이 꼭 필요한 것은 9장에 따로 적었다: **올리는 즉시 외부 전송**, **보안 등급 자료의 자동 전송**, **영구 삭제**.

## 12. 쓴 원칙, 하지 않은 것

- 쓴 원칙: 도메인 모델링(`level`을 상태에서 떼어 냄, 2장), 멱등(3장의 단계마다 지금 자료를 보고 정함), 경계(자동 규칙을 순수 함수 `auto_block` 한 곳에 둠, 4.3), 수의 설명(4.1 조건, 4.2 쪽 묶음과 범례판을 갈라 봄).
- 자동 수락을 켠 도면 한 장의 끝에서 끝까지를 앱으로 돌려 보지 않았다(코드 변경이 없는 단위).
- 여러 모델을 견주는 설계 경쟁(arena)은 하지 않았다. 구조 안 둘을 문서에서 직접 견줬다(2.1).
- 글 입력 후보의 확신도별 정밀도, 보류 쪽의 확신도별 정밀도, 같은 번호 동시 등록의 실제 경합, 도면 빼기·되돌리기의 판 이전은 재지 못했다.
