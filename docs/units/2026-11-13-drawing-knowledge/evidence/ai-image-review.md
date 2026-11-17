# 그림 입력 AI 검토: 실행 방법과 실측 (R3, 2026-11-17)

스크립트가 종류를 못 정한 노드(kind)와 태그가 빈 밸브·계기·설비(tag)에 대해, 노드 조각 그림과 범례판을 AI에 보여 후보를 받는다. 선·연결·좌표는 스크립트가 정하고, AI 후보는 따로 저장해 채점의 '스크립트 + AI 후보' 줄에만 합친다. 기준값은 '스크립트만'이다. 계획은 `D:\HAZOP-trials\2026-11-14-r3-read-quality\aiplan\plan.md`, 규칙은 [`docs/specs/extraction.md`](../../../specs/extraction.md#ai-review) 'AI 검토'를 따른다.

## 무엇이 어떻게 가나

| 단계 | 하는 일 | 코드 |
| --- | --- | --- |
| 조각 | 노드 상자 둘레 25pt, 2배, PNG. 상자 테두리를 빨갛게 긋는다 | `hazop/extract/ai_images.py` `PageImages.crop_png` |
| 범례판 | 보기 그림이 있는 종류(tee 뺌)마다 견본 하나, 칸 아래 kind 이름. 20칸씩 한 장 | `ai_images.legend_boards` |
| 견본 출처 | SNP: SNP 6쪽 추출 결과. APR1400: 범례 쪽 001~004를 먼저, 거기서 못 정한 종류는 저장소 정답지 12쪽에서. 개발용·보류 쪽은 견본으로 쓰지 않는다. 묶음을 섞지 않는다 | `scripts/check_read_quality.py` `legend_sources` |
| 과제 | kind, tag만(`ai_review.IMAGE_TASKS`). 호출 하나에 10항목(`IMAGE_BATCH`), 도면당 20호출 | `hazop/extract/ai_review.py` |
| 답 검사 | kind는 보기 그림이 있는 종류 또는 `not_symbol`(버림). tag는 주변 글자에 실제로 있는 값만 | `ai_review._valid` |
| 전달 | 구독 CLI에 `--input-format stream-json`으로 사용자 메시지 한 줄(이름표 글 + 그림 블록 + 글). 도구는 끈 채(`--tools ""`), 권한 방식·설정 파일은 바꾸지 않음 | `hazop/study/claude_cli.py` `request_stdin` |
| 저장 | `--ai-save <폴더>`면 응답을 `<폴더>/responses/<요청 해시>.json`(고정 응답 꼴)으로 남긴다. 같은 폴더로 다시 돌리면 이미 받은 응답은 부르지 않고 쓴다(한도에 걸린 뒤 이어 가기) | `hazop/study/providers.py` `RecordingClient` |
| 재현 | `--ai-run fixed --ai-fixed-dir <폴더>/responses --ai-images`로 같은 후보·같은 두 줄 | `providers.FixedCellsClient` |

다시 확인(recheck) 과제는 그림 입력에서 뺐다. SNP 첫 실행(`aisnp\run0-recheck`)에서 스크립트가 맞게 읽은 SNP-M-301 SURGE TANK(tank)를 확신도 0.55로 vessel이라 답해, 채점 줄에서 맞던 값이 틀린 값으로 바뀌었기 때문이다.

## 실행 방법 (d-read가 보류 6쪽을 잴 때 그대로 따른다)

1. 같은 커밋을 분리 작업트리로 꺼낸다. 쪽 PDF는 연결 고리로 붙인다.
   `cmd /c mklink /J <작업트리>\resources\references\APR1400_DCD\by-drawing D:\HAZOP\resources\references\APR1400_DCD\by-drawing`
2. 인터프리터는 `%USERPROFILE%\.hazop\venv-py312\Scripts\python.exe`, `PYTHONIOENCODING=utf-8`. 먼저 `scripts/preflight.py`.
3. 구독 연결만 쓴다. `claude auth status`가 구독(`claude.ai`, `firstParty`)이어야 한다. API 키 환경변수는 클라이언트가 지운다. 다른 구독 사용 세션과 겹치지 않게 돌린다.
4. 명령(정답지 폴더 하나씩. 저장 폴더는 실행마다 새로):

   ```
   python scripts/check_read_quality.py --extra-keys <정답지 폴더> --ai-run subscription --ai-images --ai-cap 20 --ai-save <저장 폴더> --json <저장 폴더>\result.json
   ```

   - 모델은 연결 기본값 `claude-opus-5-5`, 추론 강도 `medium`(`--ai-effort` 기본값). 바꾸지 않는다.
   - 사용 한도에 걸려 멈추면(`멈춤(limit_reached)`) 재설정 뒤 **같은 명령, 같은 저장 폴더**로 다시 돌린다. 받은 응답은 `responses/`에서 다시 쓰고 부르지 않는다(출력의 '실제 호출' 수로 확인).
5. 저장 위치 규칙: 조각 그림과 응답 저장본은 저장소 밖 시험 폴더에만 둔다(`D:\HAZOP-trials\<날짜>-<주제>\...`, 폴더 README에 주인·목적·keep_until). 저장소에는 코드와 SNP 고정 응답(`tests/fixtures/ai-review/snp-images`)만 넣는다.
6. 다시 재기: `python scripts/check_read_quality.py --extra-keys <정답지 폴더> --ai-run fixed --ai-fixed-dir <저장 폴더>\responses --ai-images`.
7. 후보별 판정(맞게 바꿈·틀리게 바꿈·없던 자리에 틀리게 붙임): `D:\HAZOP-trials\2026-11-14-r3-read-quality\aisnp\diffcheck.py <저장소> <정답지 폴더> <저장 폴더>`.
8. 보류 쪽은 그림을 열어 원인을 찾지 않는다. 합계만 적는다.

## 실측 1: SNP 6쪽 (가상 도면, 경로 확인)

| 항목 | 조건 |
| --- | --- |
| 코드 | 이 문서를 넣은 커밋(작업트리 R3, 7289dd2 위) |
| 명령 | `check_read_quality.py --only SNP-M-101,SNP-M-102,SNP-M-201,SNP-M-301,SNP-M-401,SNP-M-501 --ai-run subscription --ai-images --ai-cap 20 --ai-save <run1·run2>` |
| 연결 | 구독(Claude Code 2.1.323), `claude-opus-5-5`, medium, 도구 끔, stream-json 그림 블록 |
| 저장본 | `D:\HAZOP-trials\2026-11-14-r3-read-quality\aisnp\run1`, `run2`(응답 `responses/`), 다시 재기 `replay.log`. 저장소 고정 응답은 run1 응답 6개(`tests/fixtures/ai-review/snp-images`) |

| 쪽 | 호출 | 초(run1 / run2) | 항목(kind·tag) | 후보 | 스크립트만 종류 | 스크립트 + AI 종류 |
| --- | --- | --- | --- | --- | --- | --- |
| SNP-M-101 | 1 | 8 / 6 | 0·3 | 0 | 26/26 | 26/26 |
| SNP-M-102 | 1 | 3 / 5 | 0·4 | 0 | 15/15 | 15/15 |
| SNP-M-201 | 1 | 4 / 6 | 0·2 | 0 | 19/19 | 19/19 |
| SNP-M-301 | 1 | 2 / 4 | 0·3 | 0 | 17/17 | 17/17 |
| SNP-M-401 | 1 | 5 / 4 | 2·0 | 2(pump, 둘 다 맞음) | 13/15 | 15/15 |
| SNP-M-501 | 1 | 3 / 3 | 0·3 | 0 | 15/16 | 15/16 |
| 합계 | 6 | 25 / 28 | 2·15 | 2 | 105/108(97.2%) | 107/108(99.1%) |

- 태그·연결·속성은 두 줄이 같다(태그 79/79, 연결 184/193, 속성 47/47). 오검출은 두 줄 모두 0.
- 맞던 값을 틀리게 바꾼 후보 0, 없던 자리에 틀린 값을 붙인 후보 0(`diffcheck.py`). 태그 항목 15개에는 답이 오지 않았다(그림에도 글자에도 태그가 없는 자리).
- 흔들림: run1과 run2는 응답 글(근거 문장·차선 값)은 다르지만 후보 2개와 두 줄 값은 같다.
- 다시 재기: run1 응답을 고정 응답으로 돌린 값이 run1과 같다(`replay.log`, `SnpImageReplayTest`).
- 스크립트만 값은 AI를 켜도 바뀌지 않는다(같은 실행의 '스크립트만' 줄 = 기준값 검사 값).

## 실측 2: APR1400 개발용 12쪽 (사용자 승인 2026-11-17, backlog fb117ec)

| 항목 | 조건 |
| --- | --- |
| 코드 | 6919c29 |
| 명령 | `D:\HAZOP-trials\2026-11-14-r3-read-quality\aisnp\apr_dev.sh`: 정답지 폴더 `keys-dev`, `keys-dev2`(`D:\HAZOP-trials\2026-11-16-read-quality-extra`)마다 `check_read_quality.py --extra-keys <폴더> --ai-run subscription --ai-images --ai-cap 20 --ai-save aisnp\apr-run1` |
| 연결 | 구독(Claude Code 2.1.323), `claude-opus-5-5`, medium, 도구 끔, stream-json 그림 블록 |
| 범례판 | 2장(109KB, 119KB), 견본 39종. 범례 쪽 001~004에서 22종, 나머지는 정답지 12쪽에서. 견본 없는 보기 종류 12개: chiller, control_valve, demineralizer, electric_heater, humidifier, isolation_valve, reactor_vessel, relay_converter, silencer, steam_generator, test_connection, turbine |
| 조각 | 정답지 12쪽 기준 중앙값 1.9~5.9KB, 최대 17.6KB(`aisnp\apr-crops\summary.json`). 호출 하나에 범례판 2장(종류 항목이 있을 때) + 조각 10장 |
| 저장본 | `aisnp\apr-run1`(후보·`responses/` 116개), 흔들림 `aisnp\apr-run2`(133쪽), 후보 판정 `aisnp\diff-apr.txt` |
| 보류 6쪽 | 돌리지 않았다 |

맞은 수/분모(오검출). 분모 = 정답 단위 + 오검출이라 후보가 오검출을 늘리면 분모도 는다.

| 쪽 | 호출 | 초 | 후보 | 기호 아님 | 종류: 스크립트만 → +AI | 태그 | 속성 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 007 | 6 | 79 | 9 | 16 | 57/85(2) → 62/86(3) | 19/29 → 21/29 | 같음 |
| 051 | 17 | 112 | 1 | 43 | 129/142 → 130/142 | 0/2 → 0/2 | 같음 |
| 080 | 9 | 122 | 37 | 35 | 65/134(9) → 93/138(13) | 14/40 → 14/40 | 같음 |
| 103 | 9 | 92 | 9 | 29 | 50/72(10) → 53/76(14) | 0/0 | 같음 |
| 133 | 5 | 62 | 16 | 17 | 7/30 → 11/36(6) | 0/0 | 같음 |
| 134 | 12 | 192 | 37 | 49 | 154/204 → 171/204 | 89/120 → 93/120 | 같음 |
| 019 | 14 | 154 | 48 | 41 | 35/97 → 54/107(10) | 9/58 → 14/61(3) | 20/64 → 27/64 |
| 037 | 6 | 79 | 18 | 15 | 100/116(7) → 101/124(15) | 82/89 → 82/93(4) | 22/27 → 25/27 |
| 077 | 7 | 80 | 28 | 19 | 42/96(4) → 67/96(4) | 6/20 → 6/20 | 같음 |
| 099 | 7 | 100 | 26 | 27 | 27/50 → 31/59(9) | 10/27 → 13/27 | 같음 |
| 117 | 6 | 56 | 6 | 7 | 40/55(1) → 43/56(2) | 0/0 | 같음 |
| 141 | 18 | 195 | 33 | 56 | 109/170(8) → 131/172(10) | 22/43 → 26/43 | 같음 |
| 합계 | 116 | 1324 | 268 | 354 | **815/1251(65.1%, 41) → 947/1296(73.1%, 86)** | **251/428(58.6%) → 269/435(61.8%, 7)** | **406/496(81.9%) → 416/496(83.9%)** |

- 연결은 134쪽만 381/461(22) → 381/459(20)으로 오검출 2개가 줄었고(종류가 정해져 짝이 바뀜) 나머지는 같다. 합계 1295/2576 → 1295/2574.
- 호출 116회(상한 20에 걸린 쪽 없음, 오류 0, 멈춤 0), 걸린 시간 합계 1324초(호출당 평균 11.4초). 응답 버림 1, `not_symbol` 354.
- 후보 268개 판정(`diffcheck.py`, 후보를 하나씩 적용): 맞게 바꿈 160, **맞던 값을 틀리게 0**, 정답에 없는 자리에 붙여 오검출 49, 점수 그대로(빈 자리에 붙였으나 정답과 짝이 없거나 틀림) 59.
- 과제별 정밀도(맞게 바꿈/후보): 종류 132/233(56.7%), 태그 18/25(72%), 정상·고장 위치 10/10.
- 종류 값별: fan 25/25, transmitter 21/22, manual_valve 18/23, damper 13/16, air_flow_arrow 22/35, heat_exchanger 6/6, humidifier 6/6, flow_element 4/5, drain 4/6, control_valve 4/12, isolation_valve 0/10, vessel 1/9, continuation 0/9, electric_heater 0/9, test_connection 0/6, chiller 1/5, controller 0/5, sample_probe 0/4, 나머지 1~3개씩.
- 흔들림(133쪽 두 번): 후보 16개가 두 번 모두 같다(값까지). `not_symbol` 답은 17 → 22로 달랐다.
- 다시 재기: 019·117쪽을 저장한 응답으로 다시 돌린 두 줄이 첫 실행과 같다.
- 스크립트만 줄은 AI를 켜도 그대로다.

### 읽은 점과 다음 결정

- 종류 정밀도 56.7%는 계획의 끄는 선(80%) 아래다. 오답은 범례판에 견본이 없는 종류(isolation_valve 0/10, electric_heater 0/9, test_connection 0/6, control_valve 4/12)와 견본이 있어도 모양이 넓은 종류(vessel, continuation, air_flow_arrow)에 몰린다. 견본 없는 종류를 답 목록에서 빼면 같은 저장본 기준 121/184(65.8%)로 추정한다(다시 돌리지 않은 계산).
- 태그·위치는 후보가 적지만 정밀도가 높다(28/35).
- 총괄 결정이 필요한 것: (1) 종류 과제를 끌지, 견본 있는 종류만 받게 좁혀 다시 잴지, (2) 범례판 견본 고르기(가장 큰 상자를 고르니 check_valve·manual_valve 견본이 기호 일부만 보이는 칸이 있다).

### 보류 6쪽 예상(돌리지 않음)

항목 623개(종류 347, 태그 276), 호출 64회(상한에 걸리는 쪽 없음), 실측 호출당 11.4초로 약 12분. 쪽별: 013 16회, 047 6회, 084 7회, 088 14회, 113 16회, 143 5회(`aisnp\apr-crops\summary.json`, 6919c29의 묶음 10·상한 20으로 셈).
