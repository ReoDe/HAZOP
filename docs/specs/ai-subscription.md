---
doc_id: HZ-PLN-18
rev: 0
status: review
author: unknown
reviewed: doc-status 2026-11-12
approved: —
---

# AI 연결: Claude Code 구독제 기술 설계

작성 2026-11-09. 상태: **결정 확정**(2026-11-09, U1~U12 권장안 채택. 화면 설계 D1~D6도 권장안, D1은 '구독 기본'). 구현 전. 관련 문서: [HAZOP 분석 §모델 연결](hazop-analysis.md#모델-연결), [인터페이스 §2.5](interface.md#25-ai-확장-지점), [화면 설계](../design/ai-connection-screens.md), [INTENT.md §3.5·§7 5번](../../INTENT.md).

④ AI 분석은 지금 Anthropic API 키(`hazop/study/claude_http.py`)로만 돈다. 호출할 때마다 요금이 나간다. 사용자는 구독료를 이미 낸 Claude Code 구독(Pro·Max)을 앱에 직접 연결해 쓰기를 원한다(INTENT §3.5, 2026-11-09). 이 문서는 그 방법을 정하고, API 연결과 화면·기록을 나누며, 지금 무엇으로 연결돼 있는지 늘 보이게 하는 데 필요한 상태값을 정한다.

표기: **[확인]**은 이번에 공식 문서·약관·이 PC의 CLI에서 직접 확인한 사실이다. **[실측]**은 §2의 시제품 실행에서 관찰한 사실이다. **[추론]**은 확인한 사실에서 끌어낸 판단이고, 구현 1단계에서 실측으로 확정한다.

---

## 0. 상태값과 오류 종류 (기준 목록)

이 절의 이름이 기준이다. 화면 설계([docs/design/ai-connection-screens.md](../design/ai-connection-screens.md))는 이 이름을 그대로 쓴다. 화면 설계 §12의 제안 이름은 대부분 그대로 받았고, 바꾼 것은 §0.5에 적었다. 이름을 바꾸려면 이 절을 먼저 고친다.

### 0.1 연결 방식 `via`

설정 파일에는 `ai_method`, 결과 기록(칸의 `ai_run`, `ai_log` 한 줄)에는 `via`로 같은 값을 쓴다.

| 값 | 화면 이름 | 과금 `billing` | 비고 |
| --- | --- | --- | --- |
| `subscription` | Claude 구독 | `plan`(구독 한도 안. 초과 사용이 켜져 있으면 `overage`가 될 수 있음, §5.4) | 로컬 `claude` CLI를 부른다. 요금제(예: Max 20x)를 함께 보인다 |
| `api` | API 키 | `per_call`(건마다 과금) | 지금의 `claude_http`. 키 이름을 함께 보인다 |
| `fixed` | 고정 응답(시험) | `none` | 시험·시연용. 배포본 기본 화면에는 숨긴다 |

`via`가 없는 옛 기록은 `api`로 읽는다(구독 연결 전에는 API뿐이었다).

### 0.2 연결 상태 `conn_state`

한 시점에 값은 하나다. 여러 조건이 겹치면 표의 위쪽이 이긴다(우선순위 순). "시작"은 분석을 시작할 수 있는지다.

| 값 | 방식 | 뜻 | 시작 | 사용자가 할 일 |
| --- | --- | --- | --- | --- |
| `checking` | 공통 | 확인 중 | 대기 | - |
| `disabled` | 구독 | 구독 연결이 꺼져 있음(`subscription_enabled` false. 배포본도 개발자 PC와 같이 처음 켤 때 안내를 확인하면 켜진다, U3 2026-11-13 개정) | 막음 | 설정에서 켜기(이용 조건 확인) |
| `not_installed` | 구독 | Claude Code가 이 PC에 없음 | 막음 | 설치 안내 열기 또는 실행 파일 위치 지정 |
| `cli_too_old` | 구독 | Claude Code 버전이 낮음(v2.1.259 미만) | 막음 | `claude update` |
| `cli_unsupported` | 구독 | `.exe`가 아닌 설치 방식만 찾음(npm `claude.cmd` 등) | 막음 | 네이티브 설치로 바꾸기 |
| `login_required` | 구독 | 로그인 안 됨 | 막음 | 터미널에서 `claude auth login` |
| `login_expired` | 구독 | 로그인 기간이 끝남 | 막음 | 다시 로그인 |
| `not_subscription` | 구독 | 구독이 아닌 인증(API 키·Console·외부 제공자)으로 잡힘. 요금이 나가므로 막음 | 막음 | 구독 계정으로 로그인, 환경변수·관리형 설정 확인, 또는 방식을 `api`로 |
| `account_blocked` | 구독 | 계정 정지·조직 불허·결제 문제(`account_on_hold`·`oauth_org_not_allowed`·`billing_error`) | 막음 | claude.ai 계정 확인 |
| `limit_reached` | 구독 | 구독 한도 도달. 재설정 시각까지 못 씀 | 막음(재설정 뒤 됨) | 재설정 시각 뒤 다시 실행 |
| `overage_risk` | 구독 | 한도가 차 가고 초과 사용(유료)이 켜져 있음 | 확인 후 | 초과 사용을 허용할지 고르기(§5.4) |
| `limit_warning` | 구독 | 한도에 가까움(초과 사용은 꺼짐) | 됨(경고) | - |
| `no_key` | API | 키 없음 | 막음 | 키 입력 |
| `key_invalid` | API | 키 형식 오류 또는 거부(401) | 막음 | 키 확인 |
| `no_permission` | API | 키 권한 없음(403) | 막음 | Console 워크스페이스 권한 확인 |
| `no_credit` | API | 크레딧 부족·결제 문제(402) | 막음 | Console > Billing |
| `rate_limited` | API | 요청 제한(429) | 잠시 뒤 됨 | 기다렸다 재시도 |
| `model_unavailable` | 공통 | 고른 모델을 이 계정·키로 못 씀(404, `model_not_found`) | 막음 | 다른 모델 고르기 |
| `no_folder` | 고정 | 응답 폴더 없음 | 막음 | 폴더 지정 |
| `network` | 공통 | 연결하지 못함 | 재시도 | 네트워크·프록시 확인 |
| `error` | 공통 | 그 밖의 확인 실패(세부 문구 함께) | 재시도 | 세부 내용 보기 |
| `unchecked` | 공통 | 아직 확인하지 않음 | 됨(시작 직전에 먼저 확인) | - |
| `ok` | 공통 | 연결됨 | 됨 | - |

지금 API 키 설정의 시험 결과 값과는 이렇게 대응한다: 시험 안 함 → `unchecked`, 성공 → `ok`, 실패 → `_test_message`의 HTTP 코드에 따라 `key_invalid`·`no_permission`·`no_credit`·`rate_limited`·`model_unavailable`·`network`·`error`.

### 0.3 호출 오류 종류 `error_kind`

칸의 `ai_run.error_kind`와 `ai_log[].error_kind`로 남긴다. 지금 칸의 `ai_run.status`(`ok`·`failed`)와 문구는 그대로 둔다.

| 값 | 뜻 | 남은 호출 | 같은 칸 다시 실행 |
| --- | --- | --- | --- |
| `not_ready` | 미설치·로그인·키 등 연결 문제. 함께 남기는 `conn_state`로 원인을 구분 | 멈춤 | 설정 뒤 |
| `auth_mismatch` | 호출 중 인증 출처가 구독이 아님을 감지해 끊음(§5.2) | 멈춤 | 설정 뒤 |
| `limit_reached` | 구독 한도 도달 | 멈춤 | 재설정 시각 뒤 |
| `overage` | 초과 사용(유료)으로 넘어간 것을 감지 | 멈춤 | 사용자 확인 뒤 |
| `rate_limited` | API 429 | 계속(지금 동작 유지) | 잠시 뒤 |
| `transient` | 과부하·서버 오류·일시 네트워크 | 계속 | 바로 |
| `timeout` | 앱이 정한 시간을 넘겨 끊음 | 계속 | 바로 |
| `bad_output` | 출력 형식 위반(스키마 불일치·잘림·JSON 아님) | 계속 | 가능 |
| `refused` | 모델이 응답을 거부 | 계속 | 입력 확인 뒤 |
| `cancelled` | 사용자 취소·창 닫기로 끊음 | 이미 멈춤 | 가능 |
| `other` | 그 밖 | 계속 | 가능 |
| `tool_guard_failed` | 채팅 프로세스가 시작할 때 알린 도구·MCP 서버 목록이 허용한 것과 달라 앱이 끊음([채팅 창 §2.4](chat-panel.md#24-채팅-프로세스-규격)). 채팅에만 쓴다 | 해당 없음 | 앱·CLI 확인 뒤 |

같은 `error_kind`가 3회 이어지면 남은 호출을 멈춘다(화면 설계 §7.4의 "3회 연속" 제안을 받음).

### 0.4 사용량 표시

| 방식 | 실행 확인 대화상자 | 진행 줄 | 기록 |
| --- | --- | --- | --- |
| `subscription` | 호출 수·예상 시간·한도 상태와 재설정 시각(알 때만) | 토큰·한도 상태 | 토큰, `cost_usd: null`, `api_equiv_usd`(§5.5) |
| `api` | 호출 수·예상 시간·예상 비용($) | 토큰·누적 비용 | 토큰, `cost_usd` |
| `fixed` | 호출 수 | 진행 수 | 없음 |

한도 상태 `limit_status`: `limit_unknown`(정보 없음) · `limit_ok` · `limit_warning` · `limit_reached`. 정보가 없을 때 "여유 있음"이라고 쓰지 않는다. 재설정 시각은 KST로 보인다.

### 0.5 화면 설계 제안과 다른 점

| 화면 설계 §12 제안 | 이 문서 | 이유 |
| --- | --- | --- |
| `login_required` | 그대로, `login_expired`를 따로 둠 | `auth status`가 만료 시각을 알려 줘 안내 문구를 다르게 할 수 있다 |
| `error`(사유 `version`·`plan`) | `cli_too_old`, `model_unavailable`로 올림 | 사용자가 할 일이 달라 상태를 나눴다 |
| (없음) | `cli_unsupported`, `account_blocked`, `overage_risk`, `limit_warning`, `no_permission`, `key_invalid`, `model_unavailable` 추가 | §5의 오류 분류를 빠짐없이 덮으려고 |
| `via`, `model_requested`, `model` | 그대로 받음 | |

---

## 1. 결론 요약

- **권장 방식:** 사용자 PC에 설치·로그인된 공식 `claude` CLI(`claude.exe`)를 헤드리스(`claude -p --output-format stream-json --json-schema ...`)로, 도구를 모두 끄고 빈 임시 폴더에서 부른다. 앱은 로그인 정보를 읽거나 저장하지 않는다. 시제품 호출 1회로 구독 인증·구조화 출력·UTF-8 한국어·한도 정보가 모두 동작함을 확인했다(§2).
- **약관 판단:** 본인 PC에서 본인 구독으로 쓰는 것은 문서가 막지 않는 범위로 본다[추론, §4.3]. 배포본에 넣어 동료가 각자 구독으로 쓰게 하는 것은 근거가 불분명하다(§4.3 나). 2026-11-13 사용자가 **내부용 배포본에도 넣기로 정했다**(DEC-0306, U3 개정). 동료는 각자 설치·로그인한 본인 구독만 쓰고, 외부 배포는 법무 검토(U4) 뒤에 한다.
- **구조:** 연결 방식(`via`)마다 같은 `analyze(request)` 계약을 지키는 클라이언트를 둔다. 결과 칸 병합(`ai_cells.apply_unit`)과 사람이 확정한 항목을 남기는 규칙은 그대로 쓴다.
- **사용 한도:** 구독은 건별 비용 대신 한도 상태를 보인다. 호출 중에 오는 `rate_limit_event`에서 사용률·재설정 시각·초과 사용 여부를 읽는다[실측]. 호출 없이 남은 한도를 읽는 공식 방법은 찾지 못했다.
- **요금 새는 길 두 곳을 막는다:** API 키 환경변수가 남아 있으면 `-p` 모드는 구독 대신 키를 쓰고[확인], 초과 사용이 켜져 있으면 한도를 넘은 호출에 요금이 붙는다. 호출마다 인증 출처와 초과 사용 상태를 확인해 끊는다(§5.2, §5.4).

---

## 2. 시제품 실행 결과 (2026-11-09)

마스터 지시로 사용량을 아주 조금 써서 1회 실제 호출했다. 실제 발전소 자료는 쓰지 않았다. 스크립트와 원본 출력은 이 세션 scratchpad `proto/`에 있다(저장소 밖).

### 2.1 조건

- CLI: `C:\Users\kim92\.local\bin\claude.exe` v2.1.319, 네이티브 설치(PE32+ 콘솔 프로그램). 이 PC에는 npm `claude.cmd` 설치가 없다[확인: `where.exe claude`].
- 로그인: `claude auth status --json` → `loggedIn: true`, `authMethod: "claude.ai"`, `apiProvider: "firstParty"`, `subscriptionType: "max"`, `planTier: "max_20x"`[확인].
- 실행 위치: 호출마다 새로 만든 빈 임시 폴더. 저장소 폴더에서 띄우지 않았다.
- 환경: 부모 환경에서 `ANTHROPIC_API_KEY`·`ANTHROPIC_AUTH_TOKEN`·`ANTHROPIC_BASE_URL`·`ANTHROPIC_PROFILE`·`CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY`를 지움.
- 띄우기: Python `subprocess.Popen`, `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`, stdin·stdout·stderr 파이프.
- 권한 우회 플래그(`--dangerously-skip-permissions` 등)는 쓰지 않았다.

명령:

```
claude.exe -p --output-format stream-json --verbose
  --json-schema '{"type":"object","additionalProperties":false,"required":["summary","deviations"],"properties":{...}}'
  --system-prompt-file <임시>\system.txt
  --model claude-haiku-5-5 --effort low
  --tools "" --disallowedTools "mcp__*"
  --strict-mcp-config --mcp-config "{\"mcpServers\":{}}"
  --setting-sources ""
  --disable-slash-commands
  --permission-mode dontAsk --permission-prompts none
  --max-turns 3 --no-session-persistence
stdin: "샘플 문장: 물탱크 수위가 높아지면 넘칠 수 있다. 이 문장의 HAZOP 편차 단어를 고르라."
```

### 2.2 결과

| 시도 | 결과 | 알게 된 것 |
| --- | --- | --- |
| 없는 플래그 추가 | 종료 코드 1, 0.2초. stderr `error: unknown option '--no-such-flag'`, stdout 비어 있음 | 인자 오류는 stderr로만 온다. 모델을 부르지 않는다 |
| 잘못된 스키마(`{"type":"nope"}`) | 종료 코드 1, 1.1초. stderr `Error: --json-schema is not a valid JSON Schema: ...` | 스키마 오류도 시작 전에 걸린다 |
| 로그인 없는 설정 폴더(`CLAUDE_CONFIG_DIR`=빈 폴더) | 종료 코드 1, 1.0초. stdout에 `init` → `assistant` → `result`(`subtype: success`, `is_error: true`, `result: "Not logged in · Please run /login"`), `init.apiKeySource: "none"` | 실행 안의 실패는 stdout `result`로 오고 `subtype`은 success일 수 있다. `is_error`와 종료 코드를 함께 봐야 한다 |
| 실제 호출 1차(입력을 3초 뒤에 씀) | 종료 코드 1. stderr `Warning: no stdin data received in 3s, proceeding without it` + `Error: Input must be provided ...` | **stdin은 띄운 직후 바로 써야 한다.** 3초 안에 입력이 없으면 끝난다 |
| 실제 호출 2차(스키마 키가 한글) | 종료 코드 1, 4.0초. `result.is_error: true`, `api_error_status: 400`, `result: "API Error: 400 tools.1.custom.input_schema.properties: Property keys should match pattern '^[a-zA-Z0-9_.-]{1,64}$'"`, 토큰 0 | **구조화 출력 스키마의 속성 이름은 영문·숫자·`_.-`만 된다.** 지금 `RESPONSE_SCHEMA`의 속성 이름 32개는 모두 이 규칙을 지킨다[확인: 코드 검사]. 값(문자열)은 한국어여도 된다 |
| **실제 호출 3차(영문 키)** | **종료 코드 0, 7.5초.** 이벤트 순서 `system/init` → `system/thinking_tokens`×2 → `assistant`×2 → `user` → `rate_limit_event` → `result`. `result.subtype: success`, `is_error: false`, `stop_reason: "tool_use"`, `structured_output: {"summary": "물탱크 수위가 높아지면 넘칠 수 있다는 문장으로, 수위가 정상보다 높아지는 상황이 넘침 위험으로 이어진다.", "deviations": [{"word": "많음", "grade": null}]}` | 아래 |

3차 호출에서 확인한 것[실측]:

- **구독 인증으로 돈다.** `init.apiKeySource: "none"`(API 키를 쓰지 않음), 한도 이벤트에 구독 창(`seven_day`)이 왔다. API 키 환경변수를 지운 상태였다.
- **구조화 출력이 지켜진다.** `enum`·`anyOf`(정수 또는 null)·`additionalProperties: false`가 모두 지켜졌다. `--tools ""`를 줘도 `init.tools`에 `StructuredOutput` 하나만 남고, 모델은 이 도구로 답했다(`tool_uses: ["StructuredOutput"]`).
- **격리가 동작한다.** `init.mcp_servers: []`, `slash_commands: []`, `skills: []`, `permissionMode: "dontAsk"`, `--setting-sources ""`가 받아졌다. 다만 `plugins`에는 내장 플러그인 4개(`cc-plugin-agents-md`, `cc-plugin-telemetry`, `cc-plugin-privacy`, `cc-plugin-plugin-authoring`, 모두 `path: builtin`)가 남았다. 사용자가 설치한 플러그인은 없었다.
- **UTF-8 한국어 입출력이 된다.** stdin에 UTF-8로 쓴 한국어를 읽었고, stdout은 UTF-8로 바르게 디코드된다(cp949로는 디코드 실패). 화면에 깨져 보인 것은 PowerShell 콘솔 코드 페이지(949) 탓이고 데이터는 정상이다. 앱은 stdout을 바이트로 받아 UTF-8로 디코드해야 한다.
- **한도 정보가 온다.** `rate_limit_event.rate_limit_info` = `{"status": "allowed", "resetsAt": 1794621600, "rateLimitType": "seven_day", "overageStatus": "rejected", "overageDisabledReason": "org_level_disabled", "isUsingOverage": false, "unifiedWindows": {"seven_day": {"utilization": 0.04, "resetsAt": 1794621600, "status": "allowed"}}}`. CLI 원본 필드는 낙타 표기(`resetsAt`)이고 Python SDK 문서의 `resets_at`과 이름이 다르다. `resetsAt`은 **초 단위**다(2026-11-14 11:00 KST, 7일 창과 맞음). 이번 이벤트에는 5시간 창이 없었다.
- **사용량:** `usage.input_tokens 2`, `cache_creation_input_tokens 1688`(1시간 캐시), `output_tokens 453`(그중 생각 토큰 300), `total_cost_usd 0.0005643`(API 단가 환산값이며 청구액이 아님[확인: 비용 문서]).
- **프로세스 트리:** 띄우고 2초 뒤 `claude.exe`의 자식은 `conhost.exe` 하나였다. `CREATE_NO_WINDOW`로 띄워도 콘솔 호스트는 생긴다. 끝난 뒤 임시 폴더에 남은 파일은 없었다(`--no-session-persistence`).

확인하지 못한 것: npm `.cmd → node` 경로(이 PC에 설치가 없음), 5시간 창 이벤트, `limit_reached`·초과 사용 상태의 실제 모양, Opus 5.5·effort high의 소요 시간, 실제 HAZOP 프롬프트 크기(맥락 수천 토큰)에서의 동작.

---

## 3. 현재 구조 (읽은 코드)

| 위치 | 하는 일 |
| --- | --- |
| `hazop/study/claude_http.py` | `ClaudeHttpClient.analyze(request)` → `{status, output, usage, model, error_type, status_code, error}`. urllib로 `POST /v1/messages`, `output_config.format`에 json_schema, `fallbacks "default"`. 단가표 `PRICES`, 모델 목록 `MODELS`, `test_connection()`(토큰 비용 없음) |
| `hazop/study/ai_cells.py` | `build_request()` → `{system, context, user, schema}`. `run_unit(client, ...)`이 `client.analyze`를 부르고 근거 검증·칸 생성. 비용은 `run_unit`이 `claude_http.cost_usd(usage, model)`로 직접 계산. `apply_unit`이 AI 제안(`ai_draft`·`proposed`) 항목만 바꾸고 사람이 손댄 항목은 남김. `usage_total`이 `ai_log`의 `cost_usd`를 모두 더함 |
| `hazop/app/ai_runner.py` | QThread 하나에서 호출 단위를 **차례로** 부름. 취소는 "남은 호출 멈춤, 진행 중 1건은 끝까지 받음" |
| `hazop/app/screens/results.py` | `make_client()`가 `ClaudeHttpClient`를 직접 만듦. `run_ai()`는 API 키가 없으면 키 설정 창을 열고 시작을 막음. 달러 표시: `usage_text()`(93행, 도구 설명 962행), `estimate()`, `request_ai()` 확인 창, `_progress_text()` 진행 줄과 툴팁, `_on_finished()` 끝 문구. `shutdown()`은 진행 중 호출을 끝까지 기다림 |
| `hazop/study/apikey.py`, `hazop/app/settings_dialog.py` | 이름 붙인 키 여러 개(DPAPI), 모델 드롭다운, 연결 시험, 연결 대상 표시. `describe()` 모양은 `tests/test_ai_key.py`가 고정 |
| `hazop/app/main_window.py` | 상태 표시줄 `ai_label`("● AI 연결됨 · <키 이름>"), 누르면 키 설정 창 |
| `hazop/analysis/ai.py` | `FixedResponseClient`(옛 ④ 분석 경로용, `infer()` 계약). `ai_cells`의 `analyze()` 계약과 다르다 |
| `tests/test_app.py` | 전송 모듈 import는 `claude_http.py`만 할 수 있다는 정적 검사 |
| `tests/test_ai_cells.py` 143행 | 가짜 클라이언트로 `run_unit`의 `cost_usd > 0`을 검사 |

구독 연결로 바뀌는 곳: `make_client()`, `run_ai()`의 키 확인, 달러 표시 다섯 곳, 상태 표시줄, 설정 창, `run_unit`의 비용 한 줄, `usage_total`의 합계 규칙. 결과 병합·근거 검증·저장 규칙은 바꾸지 않는다.

---

## 4. 연결 방식 후보와 약관

### 4.1 후보 비교

| 기준 | A. 로컬 CLI 헤드리스 (`claude -p`) | B. Claude Agent SDK(Python) | C. `setup-token` 토큰으로 직접 HTTP | D. 근거 묶음 내보내기 + 고정 응답 |
| --- | --- | --- | --- | --- |
| 구독 인증 | 로그인된 CLI가 처리[확인: 인증 순서 7번, 실측] | SDK가 같은 CLI를 하위 프로세스로 부름[확인: SDK 개요] | 앱이 토큰을 받아 다뤄야 함 | 사용자가 세션에서 직접 만듦 |
| 구조화 출력 | `--json-schema` → `structured_output`, 검증·재시도 내장[확인, 실측] | `output_format` 같은 기능 | API와 같음 | 사람이 형식 맞춤 |
| 병렬 | 프로세스 여러 개. 한도는 계정 하나를 나눠 씀 | 같음 | 같음 | 없음 |
| 시간 초과·취소 | 앱이 프로세스 트리를 끊음(§6.3) | asyncio `interrupt()` | urllib 시간 초과 | 해당 없음 |
| Windows | 네이티브 `claude.exe`로 동작[실측] | 같은 CLI 필요 | 가능 | 가능 |
| 배포본(PyInstaller) | 새 패키지 없음. CLI는 사용자 설치본을 찾음(§6.5) | `claude-agent-sdk`·asyncio 의존 추가 | 새 패키지 없음 | 지금 기능 |
| 앱 종료 시 정리 | Job 객체로 묶음(§6.4) | SDK 안 프로세스, 같은 문제 | 해당 없음 | 해당 없음 |
| 판정 | **채택** | **제외** | **제외** | **유지**(이미 있음, 이번 범위 밖) |

B를 뺀 이유: A와 같은 CLI를 감싸기만 하면서 의존성과 asyncio 경계가 는다. 약관 위험은 A와 같다. SDK 개요는 "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK"라고 적는다([Agent SDK 개요](https://code.claude.com/docs/en/agent-sdk/overview)). 이 문장은 SDK를 쓰는 A에도 똑같이 걸릴 수 있어(헤드리스 문서는 `claude -p`를 "Agent SDK via the CLI"라 부른다), B만 금지된다고 보지 않는다.

C를 뺀 이유: `claude setup-token`은 1년짜리 OAuth 토큰을 출력하고 `CLAUDE_CODE_OAUTH_TOKEN`으로 쓴다[확인, [인증](https://code.claude.com/docs/en/authentication)]. 앱이 이 토큰을 받아 저장하면 "developers may not collect, store, or intermediate Claude.ai credentials or session tokens"에 걸린다[확인, [법률·준수](https://code.claude.com/docs/en/legal-and-compliance)].

### 4.2 확인한 약관·정책 문장

| 번호 | 출처 | 내용(요지) |
| --- | --- | --- |
| T1 | [법률·준수 §Authentication and credential use](https://code.claude.com/docs/en/legal-and-compliance) | OAuth 인증은 구독 구매자가 "ordinary use of Claude Code and other native Anthropic applications"에 쓰라고 있는 것이다. 제품을 만드는 개발자는 API 키를 써야 하고, 제3자 개발자가 자기 앱에 Claude.ai 로그인을 넣거나 사용자 대신 Free·Pro·Max 자격증명으로 요청을 보내는 것을 허용하지 않는다. 로그인 정보·세션 토큰을 모으거나 저장·중개할 수 없다 |
| T2 | 같은 절 끝 | 이 제한은 최종 사용자가 수정하지 않은 Claude Code 바이너리에 본인 구독으로 로그인하는 것("signing in to the unmodified Claude Code binary with their own Claude subscription")을 막지 않는다. 플랫폼이 Claude Code를 실어 주는 경우도 포함한다 |
| T3 | 같은 문서 §Can customers offer Claude Code in their products? | 제품·서비스 안에서 Claude Code를 미리 설치하거나 실행하려면 **상용 약관(Commercial Terms)에 동의**하고 다음을 지켜야 한다: 바이너리 무수정, 내장 인증 방식을 막지 않음, 최종 사용자마다 본인 API 키·본인 구독·본인 외부 제공자 자격증명으로 인증, 사용량을 대신 내거나 재판매·중개하지 않음 |
| T4 | 같은 문서 §Acceptable use | Pro·Max 한도는 "ordinary, individual usage of Claude Code and the Agent SDK"를 전제로 한다 |
| T5 | [소비자 약관 §2](https://www.anthropic.com/legal/consumer-terms) | 계정 로그인 정보·자격증명을 남과 공유하거나 계정을 남에게 줄 수 없다 |
| T6 | 소비자 약관 §3 7항 | API 키로 접속하거나 Anthropic이 명시 허용한 경우를 빼면 봇·스크립트 등 자동화 방식 접속을 금지 |
| T7 | [헤드리스 실행](https://code.claude.com/docs/en/headless) | `claude -p`를 스크립트·CI에서 쓰는 방법을 공식으로 안내한다. 예시 대부분은 `--bare` + API 키이고, `--bare`는 구독 로그인을 읽지 않는다 |
| T8 | [Agent SDK 개요](https://code.claude.com/docs/en/agent-sdk/overview) | 위 SDK 문장. SDK로 남에게 제공하는 제품을 만들면 상용 약관을 따른다 |

### 4.3 판단

**(가) 본인 PC 내부 사용.** 개발자 본인이 본인 PC에서, 본인이 로그인한 공식 CLI를 이 앱이 부르게 하는 경우.

- 판단: **문서가 막지 않는 범위로 본다[추론].**
- 근거: 앱은 로그인 화면을 제공하지 않고 자격증명을 읽지도 저장하지도 않는다(T1의 금지 행위가 없음). 바이너리를 고치지 않는다. 사용자 본인 계정이고 남에게 제공하는 제품이 아니다(T1·T3·T8의 "제품·사용자 대신"에 해당하지 않음). 공식 문서가 `claude -p` 스크립트 사용을 안내한다(T7). T6의 자동화 금지에는 "명시 허용" 예외가 있고 T7을 그 허용으로 읽는다[추론].
- 남는 위험: 한 번에 수십 회를 부르는 일괄 분석이 T4의 "ordinary, individual usage"에 드는지는 문서가 정하지 않는다. 그래서 동시 호출을 낮게 묶고(§6.2) 한도 신호에 따라 멈춘다.

**(나) 배포본에 포함.** 사내 배포 zip에 구독 연결을 넣어 동료가 각자 본인 구독으로 쓰는 경우.

- 판단: **근거가 불분명하다. 법무 검토 전까지 하지 않는다.**
- 근거: 이 앱이 "products or services"(T1·T3)에 해당하면, 앱 안에서 Claude Code를 실행하는 것은 T3의 조건(상용 약관 동의 등)을 갖춰야 한다. 최종 사용자 본인 구독으로 인증하는 것 자체는 T3·T2가 인정하지만, T1은 "on behalf of their users"로 요청을 보내는 것을 막는다. 앱이 동료의 CLI를 자동으로 불러 분석을 돌리는 것이 어느 쪽인지 문서가 정하지 않는다. 회사가 Team·Enterprise 구독이면 상용 약관 쪽이라 판단이 다시 달라진다(HAZOP분석.md 104행 "팀 구독제 활용"도 이 경우다).
- 처리(2026-11-09): 배포본은 내부용으로 두고, 배포본에서는 구독 연결을 숨긴다. 법무 검토 또는 Anthropic 서면 답변으로 확정한다(결정 항목 U2·U3).
- 처리(2026-11-13 개정, DEC-0306): 사용자가 내부용 배포본에도 구독 연결(AI 검토, 채팅)을 넣기로 정했다. 위 판단(근거 불분명)은 바뀌지 않았고 위험은 `INTENT.md` §7에 남긴다. 위험을 줄이려고 다음을 지킨다. (1) 앱은 CLI를 싣거나 설치하지 않고, 로그인 화면을 만들지 않으며, 로그인 정보를 읽지 않는다(T1). (2) 동료가 직접 설치·로그인한 본인 구독만 쓴다(T3의 '최종 사용자마다 본인 구독'). (3) 처음 켤 때 소비자 약관·학습 설정 안내(U11)를 보이고 확인을 받는다. (4) 배포는 사내 내부용에 그치고 외부 배포는 법무 검토(U4) 뒤에 한다. 구독이 없는 PC에서는 안내만 하고 스크립트로 돈다([채팅 창 §8](chat-panel.md#8-배포본과-구독이-없는-pc)).

**(다) 불가.** 하나의 구독을 여러 사람이 나눠 쓰는 것(공용 PC·공용 계정, T5), 앱이 `setup-token` 토큰이나 `.credentials.json`을 읽어 직접 API를 부르는 것(T1).

---

## 5. 연결 방식 구조, 상태, 오류

### 5.1 클라이언트 계약

```python
class AiClient(Protocol):
    def describe(self) -> dict: ...          # 기존 키 유지 + "via", "billing"
    def check(self) -> ConnStatus: ...       # 토큰·한도를 쓰지 않는 확인
    def analyze(self, request) -> dict: ...  # request = {system, context, user, schema}
    def cancel(self) -> None: ...            # 진행 중 호출을 끊음(스레드 안전)
```

자료 모양:

```
ConnStatus  {"via", "state": conn_state, "detail": str, "plan": "max_20x"|None,
             "limit": LimitInfo|None, "checked_at": KST}
LimitInfo   {"status": limit_status, "window": "five_hour"|"seven_day"|...|None,
             "resets_at": epoch 초|None, "utilization": 0.0~1.0|None,
             "overage": "on"|"off"|"in_use"|None, "seen_at": KST}
analyze 결과 = 지금 7필드 {status, output, usage, model, error_type, status_code, error}
            + {"via", "billing", "error_kind", "cost_usd", "api_equiv_usd", "model_requested", "limit"}
```

- `status` 값(`completed`·`refused`·`truncated`·`api_error`·`parse_error`·`no_key`)은 그대로 둔다. `run_unit`이 이 값으로 갈라지기 때문이다.
- `describe()`는 지금 키(`type`·`model`·`effort`·`max_tokens`)를 그대로 두고 `via`·`billing`만 더한다(`tests/test_ai_key.py` 294행이 기존 모양을 고정함).
- 클라이언트 목록은 `hazop/study/providers.py`의 표 하나(`{"subscription": ClaudeCliClient, "api": ClaudeHttpClient, "fixed": FixedCellsClient}`)에 두고, `make_client()`는 설정의 `ai_method`로 이 표를 찾기만 한다.
- `FixedCellsClient`는 새로 만든다. `analysis/ai.FixedResponseClient`는 `infer()` 계약이라 그대로 쓸 수 없다. 응답 폴더의 `<unit_id>.json`을 읽어 `analyze` 결과 모양으로 돌려준다.

**비용 계산 위치.** 지금 `run_unit`이 모든 응답에 API 단가를 곱한다. 바꾼 뒤 규칙:

1. `ClaudeHttpClient.analyze`가 `cost_usd = cost_usd(usage, model)`과 `billing: "per_call"`을 채운다(이 클라이언트에서 바뀌는 곳은 이것과 `check`·`cancel`·`describe`의 `via`뿐이다).
2. `ClaudeCliClient.analyze`는 `cost_usd: None`, `api_equiv_usd`(CLI의 `total_cost_usd`), `billing: "plan"`(초과 사용 감지 시 `"overage"`)을 채운다.
3. `run_unit`은 결과에 `cost_usd` 키가 있으면 그 값을 쓰고, 없으면 지금처럼 `claude_http.cost_usd(usage, model)`로 계산한다. 키가 없는 옛 가짜 클라이언트(`tests/test_ai_cells.py` 143행)는 지금과 같이 통과한다.
4. `usage_total`의 `cost_usd` 합계는 `cost_usd`가 숫자인 기록만 더한다. 구독 기록은 합계에 들어가지 않는다.

### 5.2 연결 확인과 인증 출처 검사

**확인(`check()`).** 토큰을 쓰지 않는다. 앞 단계에서 실패하면 멈춘다. 모든 명령은 §6.1의 정리된 환경으로 돌린다(확인과 호출이 같은 인증을 보게).

1. CLI 찾기(§6.5). 없으면 `not_installed`, `.cmd`만 있으면 `cli_unsupported`.
2. `claude --version`. v2.1.259 미만이면 `cli_too_old`(`--permission-prompts`가 이 버전부터 있음[확인]).
3. `claude auth status --json`[확인: 필드 `loggedIn`, `authMethod`, `apiProvider`, `subscriptionType`, `planTier`, `loginExpiresAt`, `orgId`, `orgName`, `email`].
   - `loggedIn` false → `login_required`
   - `loginExpiresAt`가 지남 → `login_expired`
   - `authMethod`가 `claude.ai`가 아니거나 `apiProvider`가 `firstParty`가 아님 → `not_subscription`
   - 통과하면 `ok`, `plan`에 `planTier`. 이메일·조직 ID는 화면·로그·결과 파일 어디에도 남기지 않는다.
4. 저장해 둔 `LimitInfo`가 재설정 시각 전이면 `limit_reached`·`overage_risk`·`limit_warning`을 반영한다.

확인은 앱 시작, 설정 창 열기, 분석 시작 직전에 한다.

**호출 중 인증 출처 검사.** 환경변수를 지워도 관리형(policy) 설정의 `apiKeyHelper`·`env`는 `--setting-sources`로 끌 수 없을 수 있다[추론]. 그래서 호출마다 stream-json 첫 이벤트 `system/init`의 `apiKeySource`를 읽는다. 구독이면 `"none"`이다[실측]. 다른 값이면 그 자리에서 프로세스 트리를 끝내고 `error_kind: auth_mismatch`로 남긴 뒤 남은 호출을 멈추고 `conn_state`를 `not_subscription`으로 바꾼다. `init`은 첫 모델 요청보다 먼저 온다[실측: 이벤트 순서]. 그래서 이 자리에서 끊으면 API 요청은 나가지 않는다[추론, P1에서 가짜 CLI와 실측으로 확인].

### 5.3 호출 결과 분류

오류는 종료 코드, stderr, stdout의 `system/api_retry`(`error` 범주), 마지막 `result`(`subtype`·`is_error`·`stop_reason`·`result` 문구·`api_error_status`·`errors`)에서 읽는다[확인: 헤드리스 문서, 실측].

| 관찰 | `status` | `error_kind` / `conn_state` |
| --- | --- | --- |
| 종료 코드 0, `subtype: success`, `is_error: false`, `structured_output` 있음 | `completed` | - |
| `success`인데 `structured_output` 없음 | `parse_error` | `bad_output` (문서가 실패로 다루라고 함[확인]) |
| `subtype: error_max_structured_output_retries` | `parse_error` | `bad_output` |
| `api_error_status: 400`이고 문구에 `input_schema` | `parse_error` | `bad_output` (스키마 규칙 위반, 개발 결함으로 기록) |
| `stop_reason: refusal` | `refused` | `refused` |
| `stop_reason: max_tokens`, api_retry `max_output_tokens` | `truncated` | `bad_output` |
| `rate_limit_event` `status: rejected` + 초과 사용 아님 | `api_error` | `limit_reached` (+`resets_at`) |
| `rate_limit_event` `isUsingOverage: true` | 받은 결과는 반영 | `overage`, 남은 호출 멈춤(§5.4) |
| `init.apiKeySource ≠ "none"` | `api_error` | `auth_mismatch` → `not_subscription` |
| `result` 문구 `Not logged in`, api_retry `authentication_failed` | `api_error` | `not_ready` → `login_required` |
| 문구 `Login expired` | `api_error` | `not_ready` → `login_expired` |
| api_retry `account_on_hold`·`oauth_org_not_allowed`·`billing_error` | `api_error` | `not_ready` → `account_blocked` |
| api_retry `model_not_found` | `api_error` | `not_ready` → `model_unavailable` |
| api_retry `overloaded`·`server_error`, 연결 실패 | `api_error` | `transient` |
| 앱이 정한 시간을 넘김 | `api_error` | `timeout` |
| 사용자 취소·창 닫기로 끊음 | `api_error` | `cancelled` |
| 종료 코드 ≠ 0이고 stdout에 `result` 없음(인자·스키마 오류 등, stderr에 문구) | `api_error` | `other` (stderr 앞 200자를 문구로) |
| 그 밖 `is_error: true`, `error_during_execution` | `api_error` | `other` |

API 쪽 대응(지금 `claude_http`의 `error_type`·HTTP 코드 → `error_kind`·`conn_state`):

| API 결과 | `error_kind` | `conn_state` |
| --- | --- | --- |
| `no_key` | `not_ready` | `no_key` |
| `bad_key`, 401 | `not_ready` | `key_invalid` |
| 403 | `not_ready` | `no_permission` |
| 402, 문구에 credit·billing | `not_ready` | `no_credit` |
| 404(모델) | `not_ready` | `model_unavailable` |
| 429 | `rate_limited` | `rate_limited` |
| 529, 5xx, `connection` | `transient` | `network`(연결 실패일 때) |
| `timeout` | `timeout` | - |
| `refused` / `truncated` / `parse_error`·`bad_response` | `refused` / `bad_output` / `bad_output` | - |

CLI가 `structured_output`을 검증해도 앱은 지금처럼 `run_unit`에서 한 번 더 검사한다(`deviations` 목록, 허용 ID). CLI는 JSON Schema draft-07로 검증하고 `format`은 검사하지 않는다[확인].

### 5.4 사용 한도와 초과 사용

- **얻는 것[실측]:** `rate_limit_event.rate_limit_info`의 `status`(`allowed`·`allowed_warning`·`rejected`), `resetsAt`(초), `rateLimitType`, `overageStatus`, `overageDisabledReason`, `isUsingOverage`, `unifiedWindows.<창>.utilization`. 이벤트는 상태가 바뀔 때 온다[확인: Python SDK 참조]. 이번 호출에서는 첫 호출에도 왔다.
- **한계:** 필드가 빠질 수 있고, 호출 없이 남은 한도를 읽는 공식 명령은 찾지 못했다. 남은 호출 수를 예측해 보이지 않는다.
- **저장:** 마지막 `LimitInfo`를 설정 파일 옆 `ai_limits.json`에 둔다(P1). `resets_at`이 지나면 `limit_unknown`으로 되돌린다.
- **초과 사용(요금 새는 길):** 초과 사용(`overage`)이 켜진 사용자는 구독 한도를 넘은 호출에 요금이 붙는다[추론: 필드 이름과 claude.ai "추가 사용량" 안내로 미루어]. 규칙:
  1. 설정 `allow_overage`(기본 false)를 둔다.
  2. 마지막 `LimitInfo`에서 `overageStatus`가 `rejected`가 아니고(초과 사용 가능) 주 창이 `allowed_warning`이거나 사용률 0.9 이상이면 `conn_state: overage_risk`. `allow_overage`가 false면 시작 전에 확인을 받는다.
  3. 호출 중 `isUsingOverage: true`를 보면 그 호출 결과는 반영하되 `billing: "overage"`로 남기고, `allow_overage`가 false면 남은 호출을 멈춘다(`error_kind: overage`).
  4. 그래서 화면 문구는 "구독 한도 안에서는 추가 요금 없음(초과 사용을 켜지 않았을 때)"으로 쓴다.
- **실행 중:** `limit_reached`면 남은 호출을 멈추고 "재설정 HH:MM(KST) 이후 실패 칸 다시 실행"을 안내한다. `limit_warning`은 진행 줄에만 보이고 계속한다.

### 5.5 비용 숫자

CLI의 `total_cost_usd`는 API 단가로 계산한 클라이언트 추정값이다[확인: [비용 추적](https://code.claude.com/docs/en/agent-sdk/cost-tracking)]. 구독 사용자에게 청구되는 돈이 아니므로 화면에 달러로 보이지 않고, 기록에만 `api_equiv_usd`로 남긴다(결정 U6).

### 5.6 모델 선택

| | `api` | `subscription` |
| --- | --- | --- |
| 지정 | 정확한 ID | `--model` 전체 이름(별칭 `opus` 등도 되나 결과 비교를 위해 전체 이름을 쓴다)[확인, 실측: `claude-haiku-5-5`로 지정하자 `init.model`이 같음] |
| 대체 모델 | `fallbacks "default"` | `--fallback-model`을 쓰지 않는다. 실제 모델이 바뀌면 기록이 흐려진다 |
| effort | `output_config.effort` | `--effort`[확인] |
| 기록 | `model` | `model_requested`(보낸 값), `model`(`init.model` 또는 `modelUsage`의 키) |
| 못 쓰는 모델 | 404 → `model_unavailable` | `model_not_found` → `model_unavailable`, 요청과 실제가 다르면 경고 |

구독 모델 드롭다운은 API와 같은 세 모델(Opus 5.5·Sonnet 5.5·Haiku 5.5)이고, 단가 대신 "한도 소모 큼/보통/작음"을 보인다[추론: 공개 수치 없음].

---

## 6. CLI 호출 규격

### 6.1 명령줄과 환경

§2.1의 명령에서 모델·effort만 바꾼다(`--model claude-opus-5-5 --effort high`). 지켜야 할 규칙:

- **입력:** stdin에 `CONTEXT_PREFIX + 구간 맥락 JSON + "\n\n" + USER_PREFIX + 편차 JSON`을 UTF-8 바이트로 쓰고 바로 닫는다. **띄운 직후 3초 안에 써야 한다**[실측]. Windows 명령줄 한도(약 32,000자)를 피하려고 프롬프트를 인자로 넘기지 않는다. stdin은 10MB까지 받는다[확인].
- **시스템 프롬프트:** `--system-prompt-file`(약 4,200자). Claude Code 기본 프롬프트를 빼서 API 호출과 같은 입력이 되게 한다.
- **스키마:** `--json-schema`에 `RESPONSE_SCHEMA`(약 3,000자)를 명령줄로. **속성 이름은 `^[a-zA-Z0-9_.-]{1,64}$`만 된다**[실측]. 이 규칙을 `tests/`에 검사로 넣어 스키마를 고칠 때 깨지지 않게 한다.
- **출력:** stdout을 바이트로 받아 줄마다 UTF-8 JSON으로 읽는다. JSON이 아닌 줄은 건너뛰고 세어 둔다.
- **`--bare`를 쓰지 않는다.** bare는 구독 로그인을 읽지 않는다[확인]. 대신 bare가 끄는 것을 옵션으로 하나씩 끈다(§2.1의 `--tools ""` 등). 내장 플러그인 4개는 남는다[실측]. 사용자가 설치한 플러그인·훅·MCP·CLAUDE.md는 들어오지 않는다[실측].
- **환경:** 부모 환경에서 `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_PROFILE`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY`, `CLAUDE_CODE_OAUTH_TOKEN`을 지운다. `-p` 모드는 `ANTHROPIC_API_KEY`가 있으면 늘 그것을 쓴다[확인]. 이 앱의 시험 규칙이 `ANTHROPIC_API_KEY`를 쓰므로 실제로 겹칠 수 있다. 그리고 처음부터 `DISABLE_TELEMETRY=1`, `DISABLE_ERROR_REPORTING=1`, `CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1`, `DISABLE_FEEDBACK_COMMAND=1`을 준다(§7.1).
- **작업 폴더:** 호출마다 `%LOCALAPPDATA%\HAZOP\cli-run\<uuid>`를 새로 만들고 끝나면 지운다. 저장소·문서 폴더에서 띄우지 않는다.
- **`--no-session-persistence`:** 대화 기록이 `~/.claude/projects/`에 평문으로 남지 않게 한다[확인, 실측: 남은 파일 없음].
- **프롬프트 캐시:** 이번 호출에서 1시간 캐시가 만들어졌다[실측]. 다만 지금 API 호출은 맥락 블록에 캐시 지정을 따로 다는데, CLI는 맥락과 편차를 한 메시지로 받으므로 같은 구간의 다음 호출이 캐시를 다시 쓰는지는 알 수 없다[추론]. P1에서 같은 구간 2회 호출의 `cache_read_input_tokens`로 확인한다.

### 6.2 병렬 호출

지금 `AiRunner`는 차례로 부른다. 구독은 **동시 1개를 기본**으로 하고, 설정에서 2까지 올릴 수 있게 한다(결정 U4). 한도는 계정 전체가 나눠 쓰고, T4의 "개인의 일반적 사용"을 넘지 않게 하려는 것이다. 병렬은 P3에서 넣는다. 작업 스레드 N개가 같은 대기열에서 호출 단위를 꺼내고, `apply_unit`은 지금처럼 UI 스레드에서만 부른다.

### 6.3 시간 초과·취소·창 닫기

상태표(§6.4)를 따른다. 요점:

- 호출 하나의 시간 한도는 API와 같은 600초다. stdout 읽기 스레드와 감시 타이머를 두고, 넘으면 프로세스 트리를 끝낸다(`timeout`).
- 사용자 취소: 지금 의미("남은 호출 멈춤, 진행 중 1건은 받음")를 유지한다. 구독은 끊어도 이미 쓴 한도가 돌아오지 않으므로 받아서 반영하는 편이 낫다. 기다리는 중에 취소를 한 번 더 누르면 바로 끊는다.
- 창 닫기: 진행 중 호출이 있으면 "진행 중인 1건을 기다림(최대 2분) / 바로 끊음"을 묻는다(결정 U5). 2분이 지나면 끊는다. 이미 받은 칸은 어느 쪽이든 저장한다.
- 끊는 방법: stdin은 이미 닫혀 있으므로 정상 종료 신호를 따로 보내지 않는다. 창 없는 프로세스에는 `CTRL_BREAK_EVENT`가 닿지 않을 수 있어서다[추론]. 바로 §6.4의 방법으로 트리를 끝낸다. 끊긴 호출은 결과를 남기지 않는다(`cancelled`·`timeout`).

### 6.4 하위 프로세스 정리

**원칙: 앱이 띄운 프로세스 트리만 끈다. 프로세스 이름(`claude.exe`)으로 찾아 끄는 방식은 쓰지 않는다.** 이 PC에서는 Claude Code 세션이 여러 개 돌고 있어, 이름으로 끄면 사용자의 다른 세션이 죽는다.

1. **Job 객체(기본).** 띄운 직후 `CreateJobObjectW` + `SetInformationJobObject(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)` + `AssignProcessToJobObject(프로세스 핸들)`. 자식(`conhost.exe` 등[실측])은 자동으로 같은 Job에 들어간다. 끌 때는 `TerminateJobObject`. 앱이 비정상 종료해도 OS가 Job 핸들을 닫으며 트리 전체를 끝낸다. `apikey.py`처럼 `ctypes`만 쓴다.
2. **보조: `taskkill /T /F /PID <띄운 PID>`.** Job 할당이 실패했을 때만 쓴다. PID로만 지정하고 `/IM`(이름)은 쓰지 않는다.
3. **할당 전 틈:** `subprocess.Popen`은 일시 정지 상태로 띄울 수 없어, 띄운 순간과 Job 할당 사이에 자식이 생기면 그 자식은 Job 밖에 남는다. `claude.exe`는 stdin을 기다린 뒤에 일을 시작하므로(§2.2), **Job 할당을 마친 다음에 stdin을 쓴다**(3초 한도 안). 이 순서를 시험으로 고정한다.
4. 임시 작업 폴더는 호출이 끝나면 지우고, 앱 시작 때 이전에 남은 폴더를 지운다.

실행 상태표. 검사 스크립트(scratchpad `proto/check_states.py`)로 다음을 확인했다: 도달 가능한 상태 8개, 전이 32개. 어느 상태에서든 `closed`에 닿을 수 있고, 프로세스가 살아 있는 상태에서는 창 닫기·시간 초과가 모두 처리되며, 프로세스가 살아 있는 채로 `closed`가 되는 전이가 없다. 결과: 문제 없음.

| 상태 | 프로세스 | 시작 | 확인 성공 | 확인 실패 | 호출 끝(남음) | 호출 끝(마지막) | 한도 도달 | 시간 초과 | 취소 | 창 닫기(기다림) | 창 닫기(바로) | 종료 완료 | 대기 2분 지남 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `idle` 대기 | 없음 | `preflight` | | | | | | | | `closed` | `closed` | | |
| `preflight` 확인 중 | 없음 | | `calling` | `idle` | | | | | `idle` | `closed` | `closed` | | |
| `calling` 호출 중 | 있음 | | | | `calling` | `idle` | `idle` | `killing` | `draining` | `close_wait` | `killing_close` | | |
| `draining` 취소 대기 | 있음 | | | | `idle` | `idle` | `idle` | `killing` | `killing` | `close_wait` | `killing_close` | | |
| `close_wait` 닫기 대기 | 있음 | | | | `closed` | `closed` | `closed` | `killing_close` | | | `killing_close` | | `killing_close` |
| `killing` 끄는 중 | 있음 | | | | | | | | | `killing_close` | `killing_close` | `idle` | |
| `killing_close` 끄고 닫는 중 | 있음 | | | | | | | | | | | `closed` | |
| `closed` 닫힘 | 없음 | | | | | | | | | | | | |

빈 칸은 그 사건을 무시한다는 뜻이다. "호출 끝"에서 `closed`·`idle`로 갈 때는 받은 결과를 먼저 반영·저장한다.

구현에서 전이 하나를 더했다(2026-11-09, 구현 2 검토). `closed`에서 창이 닫기를 거절하면(다른 화면의 저장 안 한 수정을 묻는 창에서 취소) `close_refused` 사건으로 `idle`로 돌아간다. 창이 열려 있는데 상태가 `closed`에 갇혀 AI 실행이 조용히 막히는 일을 막으려는 것이다. 전이는 모두 33개다.

### 6.5 배포본에서 CLI 찾기

차례로 찾고, `.exe`인 첫 후보를 쓴다. `.exe`가 아니면 건너뛰고 다음 후보를 본다.

1. 설정 `claude_cli_path`(사용자가 지정한 경로)
2. `shutil.which("claude")`. PyInstaller 배포본도 사용자의 PATH를 물려받는다[추론]
3. `%USERPROFILE%\.local\bin\claude.exe`(네이티브 설치 위치[확인])

`.exe`를 하나도 못 찾고 `.cmd`만 있으면 `cli_unsupported`. `.cmd`는 `cmd.exe`가 인자를 다시 해석해 스키마 JSON의 따옴표가 깨지고, 프롬프트가 명령으로 해석될 위험이 있다[추론]. 경로는 호출마다 다시 확인한다. 이 PC의 CLI는 오늘 자동 갱신됐고 옛 파일이 `claude.exe.old.*`로 남아 있다[확인], 실행 중에 파일이 바뀔 수 있다.

**시험용 주입.** `ClaudeCliClient(argv_prefix=[...])` 생성자 인자로만 실행 명령을 바꿀 수 있다(예: `[sys.executable, "tests/fake_claude/fake_claude.py"]`). 이 인자는 설정 파일·화면에서 바꿀 수 없고, 주입하면 `.exe` 검사를 건너뛴다.

### 6.6 정적 검사

`tests/test_app.py`에 규칙을 더한다: `subprocess` import는 `hazop/study/claude_cli.py`만. `QProcess`, `os.startfile`, `os.system`, `os.spawn*`, `os.popen`도 `hazop/` 전체에서 금지한다(우회 경로를 막으려고). 새 파일은 네트워크 모듈을 쓰지 않는다. 채팅의 MCP 서버(`hazop/chat/mcp_server.py`)는 앱이 아니라 CLI가 띄우므로 이 규칙과 부딪히지 않는다. `hazop/chat/` 전체는 `subprocess`·네트워크 모듈·Qt를 import하지 않는다([채팅 창 §9.1](chat-panel.md#91-자동-시험실제-구독-호출-없음)).

---

## 7. 보안과 데이터

### 7.1 데이터가 가는 곳

| | `api` | `subscription` |
| --- | --- | --- |
| 보내는 내용 | 시스템 프롬프트 + 구간 맥락(도면 객체·태그·연결·설계문서 발췌) + 편차 | 같음 |
| 받는 곳 | `api.anthropic.com` | Claude Code가 Anthropic API로 보냄(TLS 1.2 이상)[확인: [데이터 사용](https://code.claude.com/docs/en/data-usage)] |
| 적용 약관 | 상용 약관 | Pro·Max는 **소비자 약관**[확인] |
| 학습 사용 | 상용 약관에서는 학습에 쓰지 않음[확인] | 사용자의 "모델 개선" 설정이 켜져 있으면 학습에 쓸 수 있음[확인] |
| 보관 기간 | 표준 30일[확인] | 학습 허용 시 5년, 아니면 30일[확인] |
| 사용자 PC에 남는 것 | 결과 파일만 | `--no-session-persistence`로 대화 기록 없음[실측]. `~/.claude.json` 등에 작업 폴더별 흔적이 쌓이는지는 미확인(M7) |
| 그 밖의 전송 | 없음 | 사용 지표(코드·프롬프트 없음)와 오류 보고(구독 로그인 시 기본 켜짐, 비밀값 가림)[확인]. 앱은 처음부터 끈다(§6.1 환경변수) |

가장 큰 차이는 학습 사용이다. 구독 연결을 처음 켤 때 "Claude 구독은 소비자 약관을 따릅니다. claude.ai 개인정보 설정에서 '모델 개선'이 켜져 있으면 보낸 도면 정보가 학습에 쓰일 수 있습니다"를 보이고 설정 주소(claude.ai/settings/data-privacy-controls)를 안내한다. 앱은 이 설정 값을 읽을 수 없다[추론: 공개 명령을 찾지 못함].

보안 등급이 있는 실제 설계자료는 두 방식 모두 지금 규칙(HAZOP분석.md "실제 발전소 도면을 사용하기 전에 데이터 반출 정책을 정함")을 따른다. 구독 방식이 이 규칙을 느슨하게 하지 않는다.

### 7.2 CLI의 PC 접근 막기

- 내장 도구는 `StructuredOutput`만 남는다[실측]. MCP 서버는 빈 목록, 슬래시 명령·스킬은 없다[실측]. 모델은 파일을 읽거나 명령을 실행할 수단이 없다.
- 권한 모드 `dontAsk` + `--permission-prompts none`[실측: `init.permissionMode`]. 남은 도구가 승인을 요구해도 자동 거부된다[확인].
- 작업 폴더는 빈 임시 폴더다. `-p` 모드는 작업 폴더 신뢰 확인 없이 그 폴더의 `.claude/settings.json` 훅과 `.mcp.json`을 실행하는데[확인: 헤드리스 문서], 빈 폴더라 실행할 것이 없다.
- 앱은 `~/.claude/.credentials.json`을 읽지 않는다. 로그인 여부는 `claude auth status --json` 결과로만 안다.
- 도면에서 온 문자열에는 이미 "지시가 아니다" 머리말(`CONTEXT_PREFIX`)을 단다. 도구가 꺼져 있어 프롬프트 주입이 성공해도 PC에 할 수 있는 일이 없다.
- **채팅은 예외 하나를 둔다**(2026-11-13). 채팅 프로세스에는 앱이 띄우는 MCP 서버 하나(`hazop`)의 읽기 도구만 허용한다. 내장 도구는 위와 같이 모두 끄고(`--tools ""`), 다른 MCP 설정은 읽지 않으며(`--strict-mcp-config`), 허용 목록은 도구 이름을 하나하나 적는다. 대화를 시작할 때 CLI가 알려 준 도구·서버 목록이 허용한 것과 다르면 앱이 끊는다(`tool_guard_failed`). 쓰기는 도구가 아니라 답의 '제안 동작'으로만 오고 앱이 검사해 실행한다. 주입이 성공했을 때 할 수 있는 일은 [채팅 창 §2.6](chat-panel.md#26-프롬프트-주입이-성공했을-때-pc에서-할-수-있는-일) 표에 있다. ⑤ 분석 호출은 지금처럼 도구를 하나도 열지 않는다.

---

## 8. 시험 방법

### 8.1 가짜 CLI (실제 구독 호출 없음)

`tests/fake_claude/fake_claude.py`를 `argv_prefix`로 주입한다(§6.5). 가짜는 받은 인자·stdin·환경변수를 파일로 남기고, 시나리오 파일대로 stream-json을 출력한다. 출력 모양은 §2.2의 실측 이벤트를 본뜬다.

| 시나리오 | 가짜 출력 | 기대 |
| --- | --- | --- |
| 정상 | init(`apiKeySource: none`) → rate_limit_event(allowed) → result(success, structured_output), 종료 0 | `completed`, `limit_ok` |
| 스키마 실패 | result(error_max_structured_output_retries) | `parse_error`/`bad_output` |
| success인데 출력 없음 | result(success, structured_output 없음) | `parse_error`/`bad_output` |
| 스키마 키 오류 | result(is_error, api_error_status 400, `input_schema` 문구), 종료 1 | `parse_error`/`bad_output` |
| 거부 | result(stop_reason refusal, is_error) | `refused` |
| 한도 도달 | rate_limit_event(rejected, resetsAt) → result(error) | `limit_reached`, 남은 호출 멈춤, 재설정 시각 |
| 한도 경고 | rate_limit_event(allowed_warning) → success | `completed` + `limit_warning` |
| 초과 사용 위험 | 저장된 LimitInfo(overageStatus allowed, utilization 0.95) | 시작 전 `overage_risk` 확인 |
| 초과 사용 중 | rate_limit_event(isUsingOverage true) → success | 결과 반영, `billing: overage`, 남은 호출 멈춤 |
| 인증 출처 불일치 | init(`apiKeySource: "ANTHROPIC_API_KEY"`) 뒤 대기 | 즉시 트리 종료, `auth_mismatch`, `not_subscription`, 가짜가 모델 요청 단계 표시를 남기지 않음 |
| 로그인 안 됨 | result(success, is_error, "Not logged in · Please run /login"), 종료 1 | `not_ready`/`login_required` |
| 계정 문제 | api_retry(account_on_hold) → result(error) | `account_blocked` |
| 일시 오류 | api_retry(overloaded) … → result(error) | `transient` |
| 인자 오류 | stderr만, stdout 비어 있음, 종료 1 | `other`, stderr 문구 |
| 입력 늦음 | stdin을 3초 안에 받지 못하면 종료하는 가짜 | 앱은 늘 3초 안에 씀(실패하면 시험 실패) |
| 멈춤 | 아무것도 내지 않고 대기 | 시간 초과 뒤 `timeout`, 트리 없음 |
| 자식 생성 | 손자 프로세스를 띄우고 대기 | 취소·시간 초과·앱 강제 종료 뒤 손자까지 사라짐. 같은 이름의 다른 프로세스(시험이 따로 띄운 것)는 살아 있음 |
| 깨진 출력 | JSON 아닌 줄, 끼어든 이벤트 | 건너뛰고 정상 처리, 스레드가 죽지 않음 |
| auth status | loggedIn false / authMethod console / 만료 지남 | `login_required` / `not_subscription` / `login_expired` |
| 버전 | `--version` 2.1.200 | `cli_too_old` |
| 찾기 | PATH에 `.cmd`만 / `.cmd` 뒤에 `.exe` | `cli_unsupported` / `.exe` 사용 |

공통 확인: 가짜가 남긴 환경에 `ANTHROPIC_API_KEY`·`CLAUDE_CODE_OAUTH_TOKEN` 등이 없고 `DISABLE_TELEMETRY=1`이 있음, 작업 폴더가 빈 임시 폴더이고 끝나면 지워짐, 인자에 `--tools ""`·`--no-session-persistence`·`--permission-mode dontAsk`가 있고 권한 우회 플래그가 없음, stdin이 UTF-8, 칸 병합 뒤 사람이 확정한 항목이 그대로임(`apply_unit` 시험 재사용), 구독 기록이 `usage_total`의 비용 합계에 들어가지 않음, `RESPONSE_SCHEMA` 속성 이름 규칙 검사.

### 8.2 사용자가 직접 확인할 항목 (실제 구독, 소량)

P1에서 `scripts/check_cli_live.py`(새 파일, 표본 구간 1개·호출 2회)를 만들어 사용자가 한 번 돌린다. M1~M3은 이번 시제품으로 일부 확인했다.

| 번호 | 확인 | 상태 |
| --- | --- | --- |
| M1 | `--tools ""`와 `--json-schema`를 함께 써도 `structured_output`이 나옴 | 확인함(§2.2) |
| M2 | `--setting-sources ""`가 받아지고 사용자 훅·플러그인이 돌지 않음 | 확인함. 내장 플러그인 4개는 남음 |
| M3 | `rate_limit_event`가 오고 `resetsAt`이 초 단위 | 확인함(7일 창). 5시간 창·`rejected`는 미확인 |
| M4 | 실제 HAZOP 프롬프트(Opus 5.5, effort high)로 결과가 나오고, API로 돌린 같은 구간과 칸 수·근거 검증 경고 수가 크게 다르지 않음 | P1 |
| M5 | claude.ai 사용량 화면에 구독 사용으로 잡히고 Console에 API 요금이 생기지 않음 | P1. 요금이 생기면 즉시 중단 |
| M6 | 같은 구간 2회 호출에서 `cache_read_input_tokens`가 0보다 큼 | P1 |
| M7 | 호출 뒤 `~/.claude.json`·`~/.claude/` 아래에 임시 작업 폴더 경로나 프롬프트 흔적이 쌓이지 않음 | P1 |
| M8 | 실행 중 창 닫기 → 작업 관리자에 앱이 띄운 `claude.exe`가 남지 않고, 사용자의 다른 Claude Code 세션은 그대로임 | P3. 남으면 차단 결함 |
| M9 | 배포본(zip)에서 CLI를 찾고 콘솔 창이 깜빡이지 않음 | P4 |

---

## 9. 구현 단계

| 단계 | 내용 | 바뀌는 파일 | 규모 | 완료 기준 |
| --- | --- | --- | --- | --- |
| P1 클라이언트·기록 | `providers.py` 표, `claude_cli.py`(찾기·확인·호출·분류·인증 출처 검사·초과 사용 감지·Job 객체·시간 초과), `FixedCellsClient`, `ClaudeHttpClient`에 `cost_usd`·`billing`·`check`·`cancel`, `run_unit` 비용 규칙(§5.1), `usage_total` 합계 규칙, `plan_units`의 `group` 인자(§11 3번), `ai_log`·`ai_run`에 `via`·`billing`·`error_kind`·`model_requested`·`limit`, `ai_limits.json` 저장, 가짜 CLI·시험, 실측 스크립트 | 새 `hazop/study/providers.py`, 새 `hazop/study/claude_cli.py`, `hazop/study/ai_cells.py`, `hazop/study/claude_http.py`, 새 `tests/fake_claude/`, 새 `tests/test_claude_cli.py`, `tests/test_app.py`, 새 `scripts/check_cli_live.py` | 중 | §8.1 시나리오 전부 통과, 기존 시험(`test_ai_cells` 143행 포함) 통과, 사용자가 M4~M7 확인 |
| P2 화면 | 연결 방식 선택(설정 창), 상태 표시줄 상태(§0.2), 확인 창·진행 줄·툴팁·끝 문구의 비용/한도 분기(§0.4), `run_ai`의 키 확인을 연결 방식별 `check()`로 바꿈, 한도 도달·초과 사용 확인 창, 구독 처음 켤 때 약관·학습 설정 안내, 배포본에서 구독 숨김(2026-11-13 U3 개정으로 숨기지 않음. 배포본 처리는 [채팅 창 §10](chat-panel.md#10-뒤-단위에-넘기는-것) P16이 맡음) | `hazop/app/settings_dialog.py`, `hazop/app/main_window.py`, `hazop/app/screens/results.py`(`make_client`·`run_ai`·`estimate`·`request_ai`·`usage_text`·`_progress_text`·`_on_finished`), `hazop/study/apikey.py`(설정에 `ai_method`·`claude_cli_path`·방식별 모델·`allow_overage`) | 중 | [화면 설계](../design/ai-connection-screens.md)의 상태 화면이 가짜 CLI로 모두 재현됨, `verify-hazop`으로 상태 전환 캡처, 구독 실행에서 달러 표시 없음, 키 없는 구독 사용자가 분석을 시작할 수 있음 |
| P3 병렬·종료 처리 | `AiRunner`를 작업자 N개 구조로, 동시 수 설정(기본 1, 최대 2), §6.4 상태표대로 취소·창 닫기(기다림 2분/바로 끊음) | `hazop/app/ai_runner.py`, `hazop/app/screens/results.py`(`shutdown`·`cancel_ai`) | 소~중 | 동시 2에서 최종 결과 파일이 동시 1과 같음(칸 순서 무관), 상태표 전이를 시험으로 덮음, M8 통과 |
| P4 문서·패키징 | HAZOP분석.md 모델 연결 표, 인터페이스.md §2.5, 결정로그, 배포 안내(내부용. 구독 연결은 2026-11-13 U3 개정으로 포함, 구독 없는 PC는 안내만), `packaging/verify_bundle.py`에 CLI 찾기 검사 추가 | 기획서·메모리·`packaging/verify_bundle.py` | 소 | M9 통과 |

P1은 `results.py`를 건드리지 않는다. P2가 `results.py`를 맡고, P3는 P2 뒤에 한다(`results.py`가 겹친다).

---

## 10. 사용자 결정 항목

권장안은 하나씩만 둔다. 2026-11-09 사용자가 모두 권장안으로 정했다. U3에 따라 배포본은 구독 연결을 숨기고 API만 쓴다. U5에 따라 개발자 PC의 기본은 구독이다. 2026-11-13 사용자 결정(DEC-0306)으로 U3를 고쳐 내부용 배포본에도 구독 연결을 넣는다(아래 표의 '결정' 칸).

| 번호 | 정할 것 | 선택지 | 권장안 | 이유 | 결정 |
| --- | --- | --- | --- | --- | --- |
| U1 | 연결 방식 | ① 로컬 CLI 헤드리스 ② Agent SDK ③ 토큰 직접 사용 | ① | 시제품으로 동작을 확인했다. ②는 같은 CLI를 감싸며 의존성만 늘고, ③은 자격증명 저장·중개 금지(T1)에 걸린다 | 채택(2026-11-09) |
| U2 | 본인 PC 내부 사용 | ① 허용(개발자 PC에서 구독 연결 사용) ② 쓰지 않음 | ① | 문서가 막는 행위(로그인 제공·자격증명 취급·대리 요청)가 없다(§4.3 가). 동시 호출 제한과 한도 신호로 일반적 사용 범위를 지킨다 | 채택(2026-11-09) |
| U3 | 배포본 포함 | ① 법무 검토 전까지 내부용, 구독 연결 숨김 ② 배포본에 넣되 기본 꺼짐 ③ 기본 켜짐 | ① | 앱 안에서 Claude Code를 실행하는 제품은 상용 약관 동의 등 T3 조건이 걸리고, 동료 구독으로 자동 호출하는 것이 T1의 대리 요청인지 문서가 정하지 않는다(§4.3 나) | 채택(2026-11-09) → **개정(2026-11-13, DEC-0306): ④ 내부용 배포본에 넣음.** 앱은 CLI를 설치·로그인시키지 않고, 동료 본인의 설치·로그인만 씀. 처음 켤 때 안내(U11)를 확인해야 켜짐. 구독 없는 PC는 안내만 |
| U4 | 법무 검토 경로 | ① 사내 법무 검토 + 필요하면 Anthropic 영업 창구에 서면 문의 ② 문의하지 않고 U3 ①을 유지 | ① | U3를 넓히려면 서면 근거가 있어야 한다 | 채택(2026-11-09) → **개정(2026-11-13):** 내부용 배포는 서면 근거 없이 사용자 결정으로 진행. 법무 검토와 서면 문의는 **외부 배포 전**에 한다 |
| U5 | 실제 분석의 기본 연결 방식 | ① 구독(확인 통과 시), API는 선택지 ② API 기본, 구독은 선택지 | ① | INTENT §3.5 "건별 과금 API보다 구독제를 원한다"와 맞춘다. 개발자 PC에서만 해당하고, 배포본은 U3에 따라 API다 | 채택(2026-11-09). 2026-11-13 U3 개정으로 배포본도 구독 확인을 통과하면 구독이 기본 |
| U6 | 구독 호출의 API 환산 비용 | ① 기록에만 `api_equiv_usd`로 남김 ② 화면에 "API였다면 $x" 참고 표시 ③ 남기지 않음 | ① | 청구 금액이 아니어서 화면에 보이면 오해를 부른다. 기록은 나중에 API 전환 비용 어림에 쓴다 | 채택(2026-11-09) |
| U7 | 초과 사용(유료) | ① 기본 막음, 넘어가기 전에 확인 ② 허용 ③ 막지 않고 경고만 | ① | "구독이라 요금 없음"이라는 표시가 틀리지 않게 한다(§5.4) | 채택(2026-11-09) |
| U8 | 구독 동시 호출 수 | ① 1 고정 ② 기본 1, 설정으로 2까지 ③ 제한 없음 | ② | 한도는 계정 전체 공유이고 T4 "일반적 사용" 전제를 지킨다. 45구간 일괄은 동시 1이면 오래 걸려 2까지 열어 둔다 | 채택(2026-11-09) |
| U9 | 창 닫을 때 진행 중 호출 | ① 끝까지 기다림 ② 바로 끊음 ③ 묻기(기다림 최대 2분) | ③ | 호출이 수 분 걸릴 수 있다. 이미 받은 칸은 어느 쪽이든 저장된다 | 채택(2026-11-09) |
| U10 | 구독 모드의 모델 | ① API와 같은 세 모델 ② Opus만 ③ CLI 기본 모델 | ① | API 결과와 비교가 쉽다. 못 쓰는 모델은 `model_unavailable`로 알린다 | 채택(2026-11-09) |
| U11 | 학습 사용 안내 | ① 구독 처음 켤 때 한 번 ② 분석 시작마다 ③ 안내 없음 | ① | 도면이 소비자 약관 아래로 가는 것을 알고 고르게 한다. 매번 묻는 것은 피로하다 | 채택(2026-11-09) |
| U12 | INTENT.md §7 5번 정리 | "시험은 고정 응답, 실제 분석은 구독 기본(개발자 PC), API는 선택지이자 배포본 기본. README 순서(① API ② 팀 구독 ③ 로컬 LLM)와 메모리 `ai-results-via-claude-code-subscription`은 이 의도로 대체" | 이대로 정리 | 이 설계는 API를 없애지 않고 나란히 둔다. 팀 구독(상용 약관)은 U4 법무 검토에 함께 올린다 | 채택(2026-11-09) |

---

## 11. 화면 설계 §12에 대한 답 (2026-11-09)

[화면 설계 §12](../design/ai-connection-screens.md#12-기술-설계와-맞출-점) 10건에 대한 기술 설계 쪽 답이다. 구현 세션은 이 표를 그대로 따른다.

| 번호 | 항목 | 답 | 반영 위치 |
| --- | --- | --- | --- |
| 1 | 구독 꺼짐 상태 | `conn_state`에 `disabled`를 더했다. 설정 파일에 `subscription_enabled`(bool)와 `subscription_terms_ack_at`(이용 조건·학습 안내를 확인한 KST 시각)을 둔다. 개발자 PC는 D1·U5에 따라 구독이 기본이므로, 처음 실행 때 안내(U11)를 한 번 보이고 확인하면 `true`가 된다. 확인 전에는 `disabled`. 배포본(U3)은 늘 `false`이고 목록에서도 숨긴다. 배포본 판별은 설정 파일의 개발자 표시가 아니라 빌드 표시(`packaging` 런타임 훅이 넣는 값)로 한다. 사용자가 설정 파일을 고쳐 켜지 못하게 하려는 것이다. **2026-11-13 U3 개정:** 배포본도 개발자 PC와 같이 처음 켤 때 안내를 확인하면 `true`가 된다. 빌드 표시는 남겨 안내 문구(내부용 배포본임)를 고르는 데만 쓴다 | §0.2, P2(`apikey.py` 설정 저장, `settings_dialog.py`) |
| 2 | 요청 모델 | 받아들였다. `ai_run`·`ai_log[]`에 `model_requested`(보낸 값)와 `model`(실제 값)을 둘 다 남긴다. API는 응답 `model`, 구독은 `init.model`을 쓰고 둘이 다르면 `modelUsage` 키로 확인한다 | §5.1, §5.6, P1 |
| 3 | 이어서 실행 범위 | `plan_units(node_set, deviations, cells=None, group=False)`에 `group`을 더한다. `group=True`이면 받은 칸을 구간·변수별로 다시 묶어 지금 일괄 실행과 같은 호출 단위로 만든다(칸 하나당 호출 하나로 늘지 않게). '남은 칸 이어서 실행'의 칸 목록은 (가) 이번 실행에서 `error_kind`가 `limit_reached`·`overage`·`cancelled`·`not_ready`·`auth_mismatch`로 끝난 칸, (나) `AiRunner`가 멈출 때 돌려주는 '아직 부르지 않은 호출 단위'의 칸이다. (나)는 메모리에만 두므로 앱을 다시 켜면 (가)와 '`ai_run`이 없는 칸'으로 대신한다. 단추는 하나로 둔다 | P1(`ai_cells.plan_units`), P3(`AiRunner.remaining`) |
| 4 | 연속 오류 멈춤 | 받아들였다(§0.3 끝). 대상은 `transient`·`timeout`·`bad_output`·`other`이고, 같은 값이 3회 이어지면 남은 호출을 멈춘다. 성공 한 번이면 횟수를 0으로 돌린다. 멈춘 칸은 3번의 이어서 실행 대상에 넣는다(`error_kind`는 마지막 오류 값 그대로) | §0.3, P3 |
| 5 | API 잔액 부족 | 따로 둔다. `conn_state: no_credit`(402 또는 문구에 credit·billing). 지금 `_test_message`의 판별을 그대로 옮긴다 | §0.2, §5.3 API 대응표 |
| 6 | API 429 칩 | 수정본에서 API 429는 `limit_reached`가 아니라 `rate_limited`(`conn_state`·`error_kind` 모두)로 바꿨다. 칩은 '요청 제한 · 잠시 뒤 다시'로 보이고 재설정 시각을 보이지 않는다. 지금 전송 함수(`urllib_opener`)는 상태 코드와 본문만 돌려줘 `retry-after` 헤더를 읽지 못한다. 시각 표시는 후속으로 미룬다. 429는 지금처럼 남은 호출을 멈추지 않는다 | §0.2, §0.3 |
| 7 | 사용량 단위 | 시제품으로 확정했다. `resetsAt`은 초 단위이고, 사용률은 `unifiedWindows.<창>.utilization`(0~1)이다. 이번 호출에는 `seven_day` 창만 왔다. 화면은 `unifiedWindows`에 있는 창만 줄로 보이고, 없는 창(예: `five_hour`)의 줄은 뺀다. 5시간 창 이벤트가 오는지는 M3에서 계속 본다 | §2.2, §5.4 |
| 8 | 요금제 이름 | 아래 표로 바꾼다. 확인한 값은 `max_20x` 하나다. 표에 없는 값은 `subscriptionType`의 첫 글자를 대문자로 바꾸고 `planTier` 원문을 괄호로 붙인다(예: "Team (team_standard)") | P2 |
| 9 | 터미널 열기 | 새 콘솔 창에서 고정 명령(`claude auth login`, `claude update`)만 띄운다. 사용자 입력이나 도면 문자열을 명령에 섞지 않는다. 띄우는 코드는 §6.6 규칙에 따라 `claude_cli.py` 안에 둔다. 회사 PC 정책이 콘솔 실행을 막는지는 알 수 없다[추론]. 실패하면 '방법 보기'(명령을 복사할 수 있는 안내)로 바로 넘어가고, '방법 보기' 단추는 늘 함께 둔다 | P2 |
| 10 | 창 닫을 때 | U9 ③(묻기)으로 정해졌다. 화면 설계에서 확인 창을 따로 그린다. 기술 규칙: 진행 중 호출이 있을 때만 묻는다. 단추는 '기다렸다 닫기(최대 2분)'와 '바로 끊고 닫기'다. 2분이 지나면 끊고 닫는다. 기다리는 동안 남은 시간을 보이고, 어느 쪽이든 이미 받은 칸은 저장한다(§6.4 상태표 `close_wait`·`killing_close`) | §6.3, §6.4, P3 |

요금제 이름 표:

| `planTier` | 화면 이름 | 확인 |
| --- | --- | --- |
| `max_20x` | Max 20x 요금제 | [확인: 이 PC] |
| `max_5x` | Max 5x 요금제 | [추론] |
| `pro` | Pro 요금제 | [추론] |
| 그 밖 | `subscriptionType` 첫 글자 대문자 + 요금제 + (원문) | - |

---

## 12. 채팅과 도구 호출 (2026-11-13)

채팅 창의 구독 연결은 [채팅 창 규격](chat-panel.md)(HZ-PLN-21)이 정한다. 이 문서와 겹치는 점만 적는다.

| 항목 | 채팅 | 이 문서의 해당 절 |
| --- | --- | --- |
| 연결 방식 | 같은 로컬 CLI(U1). 질문마다가 아니라 채팅 창 하나에 프로세스 하나(`--input-format stream-json`) | §6.1 |
| 도구 | 앱의 MCP 서버 하나만 허용, 내장 도구는 끔, 도구 검문 | §7.2 |
| 상태·오류 | `conn_state`·`error_kind`를 그대로 쓰고 `tool_guard_failed`를 더함 | §0.2, §0.3 |
| 동시 호출 | 채팅 1 + 분석 1까지(U8의 상한을 함께 씀) | §6.2 |
| 약관 판단 | 도구를 써도 (가)·(나)의 판단은 바뀌지 않음 | §4.3, [채팅 창 §2.7](chat-panel.md#27-약관-판단-다시-보기) |
| 배포본 | U3 개정으로 포함, 구독 없는 PC는 안내만 | §4.3 (나), §10 U3 |

