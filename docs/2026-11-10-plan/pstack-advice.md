# pstack 활용 자문: D 드라이브 이전 뒤 단위 A~E

작성 2026-11-10, pstack 자문 세션(읽기 전용). 기준 커밋 `feat/next-units` @ 5f4e6c3. 근거로 읽은 것은 `CLAUDE.md`, `INTENT.md`, `records/backlog.md`, `docs/2026-11-10-lessons/README.md`, `docs/2026-11-10-lessons/d-drive-move.md`, `~/.claude/rules/pstack-models.md`, pstack 0.15.36 스킬 설명, 그리고 단위 A의 대상 코드다.

## 공통 사항

- 하위 세션은 모두 `/pstack:poteto-mode`로 시작한다. 시작하면 바로 `PYTHONIOENCODING=utf-8 "%USERPROFILE%\.hazop\venv-py312\Scripts\python.exe" scripts/preflight.py`를 한 번 돌린다(규칙 11).
- 시험 명령의 기본형은 아래와 같다. 아래에서 `<py>`는 이 인터프리터 경로를 뜻한다.
  - 전체 시험: `PYTHONIOENCODING=utf-8 <py> -m unittest discover -s tests -t .`
  - 기준값 확인: `<py> scripts/check_snp_baseline.py`. `check_apr1400.py`는 APR1400 작업이 멈춰 있으므로 **기준값 갱신은 하지 않고**, 점수에 닿는 코드(`hazop/extract/*`)를 건드린 단위에서만 확인용으로 돌린다. 디스크 여유가 10GB 미만이면 시작하지 않는다(규칙 14).
- 모델: 세션을 띄울 때의 모델과 강도는 아래 '모델과 추론 강도 고르는 기준'을 보고 총괄이 정한다(규칙 9, 2026-11-11). `pstack-models.md`는 세션 **안에서** pstack 스킬이 띄우는 하위 에이전트의 기본값으로만 남는다. 예를 들어 구현 역할은 `inherit-parent`라서 세션 모델을 그대로 물려받고, `interrogate`·`arena`의 검토자·주자는 `opus high`와 부모 모델을 섞는다. 예산은 medium이다. 그래서 세션 모델을 낮추면 그 세션의 구현 하위 에이전트도 같이 낮아진다.

### 모델과 추론 강도 고르는 기준 (2026-11-11 추가)

쓸 수 있는 모델은 무거운 순서로 Fable 5.2(`claude-fable-5-2`, 총괄), Opus 5.5(`claude-opus-5-5`), Sonnet 5.5(`claude-sonnet-5-5`), Haiku 5.5(`claude-haiku-5-5`)다. 새 세션은 총괄과 같은 모델이나 더 가벼운 모델로, 총괄 이하의 강도로만 띄울 수 있다. 아래 표는 규칙 9의 세 갈래(틀리면 잃는 일은 가장 높게, 정해진 절차는 한 단계 낮게, 기록·단순 실행은 가장 가볍게)를 역할별로 풀어 쓴 것이다. 비용이나 속도 배수는 잰 적이 없어서 적지 않는다.

| 역할 | 권장 모델·강도 | 이유 |
| --- | --- | --- |
| 설계·`architect` (저장 형식, 인터페이스, 입력 지문) | Fable 5.2 · high | 한 번 정하면 되돌리기 비싸고, 뒤 단위가 모두 이 결정을 물려받는다. 되돌릴 수 없는 저장 형식이면 xhigh도 고려한다 |
| 저장·ID·판정 경로 구현 (발급기, 원자적 저장, 사람 확정 보존, 확정·이전) | Fable 5.2 · high | 틀리면 사람 작업을 잃거나 잘못 판정한다(규칙 3의 차단 결함). 경미 11건 중 3건이 차단이었던 이력이 있다 |
| 반복 개선·추출 규칙 (kind·태그·연결을 바꾸는 규칙) | Fable 5.2 · high. 작은 국소 규칙은 Opus 5.5 · high | 틀린 판정은 차단 결함이다. 톱니 검사는 지표가 내려간 것만 잡고, 새 규칙이 왜 맞는지는 잡지 못한다. 143쪽 실행을 기다리는 시간은 강도와 상관없다 |
| 정해진 절차의 이전·정리 (동작 그대로 나누기, 이름 이전, 호출자 옮기기) | Opus 5.5 · medium | 바이트 동일·기준값 동일이 안전망이다. 판단할 일이 적고 절차를 빠짐없이 따르는 것이 중요하다 |
| 문서 (기획서 부분 수정, 범위 문구, 측정 기록) | Opus 5.5 · medium | 자연스러운 한국어 윤문을 중요하게 본다(메모리 korean-writing-polish). 사실 판단이 적어 높은 강도는 필요 없다 |
| 측정 (성능 재측정, 점수 재측정, 정해진 표 채우기) | Sonnet 5.5 · medium | 정해진 명령을 정해진 조건으로 돌리고 표에 출처를 붙이는 일이다. 측정 결과를 보고 원인을 찾아 고쳐야 하면 그 단계부터 한 단계 올린다 |
| 검토 (`hazop-reviewer`, `interrogate` 검토자) | Opus 5.5 · high (에이전트 파일 그대로) | 구현 세션과 다른 모델이 보는 편이 시각이 갈린다. 지적을 차단·경미로 **판정**하는 일은 총괄(Fable 5.2)이 한다 |
| Codex 중계 (`hazop-codex-reviewer`) | Haiku 5.5 · low (에이전트 파일 그대로) | 검토는 Codex(`gpt-6.1-sol`, medium, 규칙 7)가 하고, 이 에이전트는 명령을 돌려 결과를 옮길 뿐이다 |
| QA (`hazop-qa`) | Haiku 5.5 · low (에이전트 파일 그대로). '기존 실패' 재현이 필요하면 Sonnet 5.5 · medium | 시험을 돌려 통과·실패만 보고한다. 분리 작업트리를 만들어 원인을 가리는 일(규칙 11)은 판단이 들어간다 |
| 기록 (`hazop-recorder`) | Haiku 5.5 · low (에이전트 파일 그대로) | 정해진 표에 줄을 더한다. 총괄이 `git diff`로 문장을 확인한다(규칙 5) |
| 자문 (이 세션) | Opus 5.5 · high | 읽기 전용이고 결정은 총괄이 한다. 코드와 문서를 넓게 대조해야 해서 강도는 높게 둔다 |

한 세션 안에서 하위 단위의 성격이 바뀌면 단위마다 세션을 새로 띄우거나, 이미 띄운 세션의 모델을 바꾼다(앱의 세션 모델 설정). 한 세션에 높은 모델을 고정해 두고 낮은 일까지 시키지 않는다.
- 검토는 단위마다 한 번이다(규칙 3). pstack `interrogate`는 hazop-reviewer와 Codex 검토를 **대신하지 않는다**. 둘을 겹쳐 쓰면 사실상 재검토가 된다. 아래에서 `interrogate`를 권하는 곳은 hazop-reviewer 대신 쓰자는 뜻이 아니라, 저장·ID 경로의 지적을 '재현으로 확인'하는 수단으로 쓰자는 뜻이다.
- 커밋은 자기 파일만 경로로 지정한다(규칙 10). 보고와 커밋 메시지 본문은 자연스러운 한국어로 쓰고, 커밋 전에 `unslop`으로 한 번 다듬는다.
- 파일 주인표(규칙 4). 단위는 아래 순서로만 이 파일들을 넘겨받는다.

| 파일 | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| `hazop/paths.py` | 주인 | | | | |
| `hazop/app/project_ctx.py` | 주인 | | | 이어받음 | |
| `hazop/ie/store.py` | 주인 | | | 이어받음 | 이어받음 |
| `hazop/study/migrate.py` | 주인 | | | 이어받음 | |
| `scripts/build_graph.py`, `scripts/devenv.py` | 주인 | | | | |
| `packaging/*`, `scripts/build_package*`, `packaging/verify_bundle.py` | | 주인 | | | |
| `hazop/app/tokens.py`, `hazop/app/startup.py` | | 주인 | 손대지 않음 | | |
| `hazop/app/screens/*`, `hazop/app/explorer.py` | | 손대지 않음 | 주인 | 이어받음 | 이어받음 |
| `hazop/study/corrections.py` 등 저장 공용화 대상 | | | | 주인 | |
| `hazop/ie/*`(store 제외) | | | | | 주인 |
| `records/*.md` | 총괄(hazop-recorder)만 | | | | |

B와 C가 함께 돌 때 겹칠 수 있는 곳은 `tokens.py`(글꼴)와 `startup.py`(단일 실행 잠금)다. 둘 다 B에 주고 C의 작업지시서에 '건드리지 않음'을 적는다. C가 글꼴 문제를 만나면 B 세션에 메시지로 넘기지 말고 총괄에게 보고한다.

---

## 단위 A (0단계): D 드라이브 이전 뒤 경로 결함

### 먼저 확인한 사실 (계획을 바꾸는 것)

1. **'같은 드라이브면 상대, 아니면 절대' 함수는 이미 있다.** `hazop/paths.py:31`의 `rel_or_abs(path, root)`다. `hazop/app/data.py:323`은 같은 `extraction_file`을 이미 이 함수로 적는다. 새 함수를 만들지 말고 `scripts/build_graph.py:31`을 `paths.rel_or_abs(extraction_path, paths.work_root())`로 바꾸면 앱 경로와 스크립트 경로가 같아진다. `build_graph.py:68`은 출력 문구일 뿐이니 같은 함수를 쓴다.
   - `rel_or_abs`는 저장소 전용 폴더(참고자료·APR1400·표본) 아래 파일을 옛 논리 경로로 적는다. 추출 결과는 `작업/출력/추출` 아래라 이 규칙에 걸리지 않는다. 그래도 하위 세션이 시험으로 확인한다.
   - `graph_version` 해시(`hazop/graph/build.py:75`)는 추출 내용만 넣고 `extraction_file`은 넣지 않는다. 그래서 이 수정으로 그래프 판이 바뀌거나 판 이전이 일어나지는 않는다. 읽는 쪽 `hazop/contract/chain.py:153`의 `_resolve`가 절대 경로를 받는지는 확인해야 한다.
2. **백업 두 곳(`project_ctx.py:257`, `ie/store.py:98`)에는 '절대 경로로 대신'을 쓰면 안 된다.** 이 두 곳은 상대 경로를 백업 폴더 아래 자리로 쓴다(`os.path.join(백업폴더, rel)`). Windows에서 `os.path.join`에 드라이브가 붙은 절대 경로를 주면 앞 인자를 버린다. 그러면 백업 대상 자리가 원본 자신이 되고 `shutil.copy2`가 `SameFileError`를 낸다. `ie/store.backup`은 복사에 실패하면 저장하지 않으니 데이터는 잃지 않지만, 그 경우 ⑥ 저장과 판 이전이 계속 막힌다.
3. **같은 드라이브여도 숨은 결함이 있다.** 파일이 작업 루트 밖에 있으면 `relpath`가 `..\..\x.json`을 돌려주고, 백업이 백업 폴더 밖 임의 위치에 쓰인다. 거기에 같은 이름 파일이 있으면 덮어쓴다. `HAZOP_STORE_ROOT`로 저장 루트를 작업 루트 밖에 둘 수 있으므로 앱에서도 일어날 수 있는 경로다. 실제로 닿는지는 하위 세션이 재현으로 확인한다.
4. **같은 종류의 다섯째 위치가 있다.** `hazop/study/migrate.py:238`의 `_backup`은 `startswith`로 작업 루트 안인지 판단한다. 그래서 `…\작업2\x.json` 같은 형제 폴더를 안쪽으로 잘못 본다. 백업 공용 함수를 만들 때 함께 고친다.
5. **`devenv.py:108,110`은 `paths.folder()`로 바꾸면 안 된다.** `SCORING_PATHS`는 저장소 기준 git 경로 지정자(pathspec)다. `paths.folder("기호")`는 `HAZOP_RESOURCE_ROOT`를 따르는 절대 경로라 뜻이 다르다. 표의 상대 경로를 돌려주는 `paths.folder_rel("기호")`를 쓰면 문자열을 없애면서 뜻도 맞다. `tests/fixtures/apr1400`은 FOLDERS 표에 없으므로 그 줄에는 `# 경로문자열-허용: git 경로 지정자(저장소 기준)`를 단다. 허용 표시는 `tests/test_path_literals.py:28`의 형식을 따른다.
6. **하드코딩된 `C:\` 경로.** 추적 파일을 `git grep`으로 찾아 보니 코드에는 남은 것이 없다. 남은 곳은 시험 속 가짜 경로(`C:\Users\u\…`), 기획서·디자인 시안 문서(점검표가 '급하지 않음'으로 이미 분류함), 당시 증거 기록이다. `tests/test_machine_paths.py`가 재발을 막는다. `작업/` 데이터에도 옛 `C:\Users\kim92\HAZOP` 경로가 없었고, `%APPDATA%\HAZOP\settings.json`의 `work_root`도 비어 있다. 단위 A는 코드 대신 이 확인 결과만 보고에 적으면 된다.

### 1. 스킬

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| 시작 | `poteto-mode`(실행자) | 규칙 10 |
| 재현 | `tdd` | 결함이 분명하고 시험 대상이 값싸다. 이 기계에는 C:와 D:가 다 있으므로 실제 드라이브를 넘는 재현을 먼저 만든다(임시 폴더는 `%TEMP%`=C:, 작업 루트는 D:). CI처럼 드라이브가 하나인 환경을 위해 `tests/test_analysis.py:923`처럼 `relpath`가 ValueError를 내게 바꾸는 시험도 함께 둔다 |
| 수정 전 | `blast-radius` | `rel_or_abs`의 논리 경로 규칙과 `extraction_file`을 읽는 쪽(`contract/chain.py`, 뷰어 경로)에 영향이 없는지 실제 코드를 돌려 한 가지 사실로 증명한다. 백업 경로의 안/밖 판단도 여기서 확인한다 |
| 수정 | (원칙) `principle-fix-root-causes`, `principle-subtract-before-you-add` | 새 공용 함수는 백업용 하나만 둔다. 표시·기록용은 이미 있는 `rel_or_abs`를 쓴다 |
| 재발 방지(선택) | `correct` 축소판 | `os.path.relpath(…, paths.work_root())`나 `store_root()` 형태를 `hazop/`·`scripts/`에서 금지하는 시험 하나. 과거 실수(이번 4곳)에서 실패하는지 증명한다. 범위가 커지면 후속으로 넘긴다 |
| 마무리 | `unslop` | 커밋 메시지와 보고 |
| 생략 | `how`, `architect`, `arena`, `swarm`, `figure-it-out`, `interrogate`, `statechart` | 위치와 고칠 방법이 이미 정해져 있다. 규모는 '중'이고 검토는 hazop-reviewer 한 번이면 된다 |

### 2. 세션 구성

- **하위 세션 1개, 순차.** 파일이 적고(5~6개) 서로 얽혀 있다(`paths.py`가 공용 함수를 갖고 세 호출자가 쓴다). 나누면 오히려 차례 조정이 생긴다.
- 파일 주인: `hazop/paths.py`, `scripts/build_graph.py`, `scripts/devenv.py`, `hazop/app/project_ctx.py`, `hazop/ie/store.py`, `hazop/study/migrate.py`, 그리고 새 시험 파일(예: `tests/test_cross_drive.py`).
- 이 단위가 끝나기 전에는 B·C를 띄우지 않는다. 전체 시험이 깨진 상태에서 B·C가 '기존 실패'를 따로따로 판정하게 되기 때문이다(교훈 2).
- 흐름(규칙 '중'): 하위 세션 구현 → hazop-reviewer 1회 → 총괄 반영 → hazop-qa. Codex 교차검증은 생략해도 된다. 보안 등급 자료와는 관계없지만 규모가 작다.

### 3. 완료 기준

1. 새 백업 경로 함수(이름 예: `paths.backup_rel(path, root)`)는 다음을 만족한다. 루트 안이면 상대 경로를 돌려준다. 루트 밖이거나 다른 드라이브면 백업 폴더 안에 머무는 이름(예: `_외부/<드라이브 문자>/<나머지 경로>`)을 돌려준다. 어떤 입력에서도 결과에 `..`나 드라이브 문자가 남지 않는다. `project_ctx.backup`, `ie/store.backup`, `migrate._backup`이 이 함수를 쓴다.
2. 재현 시험이 수정 전 HEAD에서 실패하고 수정 뒤 통과한다. 경우는 세 가지다. (a) 다른 드라이브(실제 C:↔D:와 ValueError 흉내 둘 다) (b) 같은 드라이브의 루트 밖 파일. 백업 폴더 밖에 아무것도 쓰이지 않아야 한다 (c) `작업2`처럼 이름이 비슷한 형제 폴더.
3. `build_graph.py`가 다른 드라이브의 추출 결과로도 그래프를 만들고, `source.extraction_file`이 절대 경로로 적히며, `contract/chain.py`가 그 경로를 다시 찾는다.
4. `devenv.py`에 경로 문자열이 남지 않거나 허용 표시가 붙어 있고, `tests/test_path_literals.py`와 `tests/test_devenv.py`가 통과한다. `baseline_update_problems`가 기호 사전 폴더의 추적 안 한 새 파일을 여전히 잡는다(교훈 3의 장치가 약해지면 안 된다).
5. 전체 시험 `PYTHONIOENCODING=utf-8 <py> -m unittest discover -s tests -t .`가 실패 0으로 통과한다. 보고에는 실행 수(지난번 1,740개에 새 시험 수를 더한 값)와 인터프리터 경로를 적는다. 실패가 남아 '기존 실패'라 부르려면 HEAD에서 만든 분리 작업트리(`D:\HAZOP-trials\wt-a-head` 등)에서 재현해 보인다(규칙 11).
6. `<py> scripts/check_snp_baseline.py` 후퇴 0. 이 단위는 점수 입력(`hazop/extract/*`, 기호 사전)을 건드리지 않으므로 `check_apr1400.py`는 돌리지 않아도 된다. 돌린다면 기준값 갱신(`--update`)은 하지 않는다.
7. 하드코딩된 `C:\` 경로 확인 결과(위 6번)를 보고에 한 단락으로 적는다.
8. 시험에 쓴 임시 작업 루트와 분리 작업트리를 지우고 `git worktree list`가 깨끗하다(규칙 14).

### 4. 위험과 먼저 확인할 것

- **규칙 3의 재현 조건이 걸린다.** 이 단위는 저장(백업)과 출처 경로(`extraction_file`)를 다룬다. 그래서 검토에서 나온 지적은 재현 스크립트로 확인하기 전에는 경미로 낮추지 않는다. 특히 위 사실 3(같은 드라이브의 루트 밖 백업이 백업 폴더 밖에 쓰임)은 실제로 닿으면 덮어쓰기, 곧 데이터 손실이다. '기존 동작도 같다'는 낮출 이유가 되지 않는다. 반대로 사실 2의 다른 드라이브 경우는 저장을 막는 쪽으로 실패하므로 데이터 손실은 아니다. 다만 ⑥ 저장이 막히므로 차단 결함으로 본다.
- **먼저 확인할 것.** (1) 이전 뒤 전체 시험에서 실패한 시험 이름을 다시 뽑아 이번 4곳과 정확히 맞는지 본다. 다른 원인이 섞였으면 범위를 넓히지 말고 총괄에게 보고한다. (2) `HAZOP_STORE_ROOT`를 작업 루트 밖에 둔 상태에서 `project_ctx.backup`에 실제로 저장 루트 파일이 들어가는지 본다. 사실 3이 앱에서 닿는지가 여기서 갈린다. (3) `contract/chain._resolve`가 절대 경로를 받는지 본다.
- **하지 말 것.** `rel_or_abs`를 백업 자리에 그대로 쓰기. `devenv.py`를 `paths.folder()`로 바꾸기. 저장소 전체를 훑어 `relpath`를 일괄 치환하기. `scripts/build_package.py`·`check_*.py`의 `relpath`는 같은 루트 안에서만 쓰여 문제가 없다.

---

## 단위 B (1단계): 패키징 마무리

### 1. 스킬

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| 시작 | `poteto-mode` | |
| 묶음 범위 확인 | `blast-radius` | spec의 sys.path 정리가 빌드본의 `importlib` 경로(`paths.program_root()`, 화면이 `scripts/*.py`를 읽음)를 깨지 않는지 빌드본을 실제로 돌려 확인 |
| 스크린샷 확장 | (원칙) `principle-prove-it-works` | `verify_bundle`에 ②편집·④·⑤·⑥ 화면을 더하고, 찍힌 그림을 보고서에 남긴다 |
| 점검표 | `technical-writing` + `unslop` | '다른 PC 점검표'는 사람이 따라 하는 절차 문서다 |
| 생략 | `arena`, `swarm`, `architect`, `interrogate` | 정해진 작업 목록이다 |

### 2. 세션 구성

- **하위 세션 1개.** C와 병렬로 돌린다. 파일 주인: `packaging/*`, `scripts/build_package*`, `packaging/verify_bundle.py`, `hazop/app/tokens.py`, `hazop/app/startup.py`(잠금을 고쳐야 할 때만).
- 빌드는 오래 걸리므로 백그라운드로 돌리고, 빌드 출력은 `D:\HAZOP-trials\pkg-<날짜>\`에 README와 함께 둔다.
- 흐름은 '대'로 본다(배포본 규격 변경). hazop-reviewer와 Codex를 병렬로 한 번 돌리고 hazop-qa로 마친다.

### 3. 완료 기준

1. 빌드가 성공하고 `verify_bundle`이 ①②(편집 포함)③④⑤⑥ 스크린샷을 남긴다.
2. 빌드본을 두 번 실행해 두 번째가 잠금 안내를 띄우고 끝난다. 이것은 실제 데스크톱 조작이므로 `scripts/desktop_lease.py run --purpose "B 단일 실행 잠금" -- <명령>` 안에서 한다(규칙 13). 남은작업의 '빌드 실행본에서 단일 실행 잠금을 직접 확인하지 못함'을 닫는다.
3. 빌드본에서 `tests/test_packaging.py`와 전체 시험이 통과한다(`<py>`, `PYTHONIOENCODING=utf-8`).
4. 다른 PC 점검표가 `packaging/README.md`나 그 옆 문서에 있고, venv 경로는 `HAZOP_VENV` 기준으로 적혀 있다.

### 4. 위험과 먼저 확인할 것

- **Pretendard는 사용자 결정이 먼저다.** `hazop/app/tokens.py:7`에 'Pretendard 배포는 미결정(§9)'이라 적혀 있고, `tests/test_app.py:163`은 앱 CSS·QSS에 Pretendard가 **없음**을 확인한다. 배포본에 글꼴 파일을 넣는 일은 라이선스 파일 동봉(`paths.licenses_dir()`)과 외부 배포 정책(INTENT: 내부용만)에 닿는다. 총괄은 배정 전에 사용자에게 넣을지를 묻는다(규칙 8). 넣는다면 시험을 바꾸는 것도 이 단위의 범위다.
- 디스크: 빌드 출력이 크다. 시작 전에 `preflight.py`로 여유를 확인한다.
- `packaging/netwatch.ps1`의 venv 경로 패턴은 venv를 옮기지 않았으니 그대로 둔다.

---

## 단위 C (1단계, B와 병렬): 화면 결함 묶음

### 1. 스킬

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| 시작 | `poteto-mode` | |
| 원인 찾기 | `how`(필요한 결함에만) | Ctrl+5 직후 J, 등록 뒤 ②가 바뀌지 않는 문제는 신호 흐름을 먼저 봐야 한다 |
| 재현과 확인 | 프로젝트 스킬 `verify-hazop` | 실제 창을 키보드·마우스로 움직여 증거를 남긴다. 반드시 `desktop_lease.py run` 안에서 한다 |
| 회귀 시험 | `tdd`(값싼 것만) | ⑤ 탐색기 Sx → ④ 이동, 접근성 이름은 단위 시험으로 고정할 수 있다. 한글 IME는 단위 시험으로 흉내 내기 어려우니 `verify-hazop` 증거로 대신한다 |
| 생략 | `arena`, `architect`, `swarm` | 결함마다 범위가 좁다 |

### 2. 세션 구성

- **하위 세션 1개, 결함 다섯 개를 순서대로.** 다섯 결함이 모두 `hazop/app/screens/*`와 `explorer.py`에 모이므로 세션을 나누면 같은 파일에서 부딪힌다. 결함마다 따로 커밋한다.
- 파일 주인: `hazop/app/screens/*`, `hazop/app/explorer.py`, 관련 시험. `tokens.py`·`startup.py`는 B 소유이니 건드리지 않는다.
- 흐름은 '중'이다. hazop-reviewer 한 번, hazop-qa.

### 3. 완료 기준

1. 결함 다섯 개마다 재현 증거(수정 전)와 통과 증거(수정 뒤)가 있다. 실제 창 증거는 `verify-hazop`의 결과물로 남긴다.
2. `<py> scripts/check_user_scenarios.py`(스스로 데스크톱 잠금을 잡음)의 S1~S6이 통과한다. 남은작업의 'S6 전체 연속 실행에서만 실패'가 다시 나오면 따로 적는다.
3. 전체 시험 통과(규칙 11 형식).

### 4. 위험과 먼저 확인할 것

- **앞 창이 앱이 아니면 시험 장치 실패다**(규칙 13, 교훈 6). IME 결함은 특히 Claude 창으로 키가 새는 일과 헷갈리기 쉽다. 스크린샷으로 앞 창을 함께 남긴다.
- B의 빌드 확인도 데스크톱 잠금을 쓴다. 두 세션이 잠금을 두고 기다리는 것은 정상이며, 메시지로 차례를 넘기지 않는다.
- '등록 뒤 ②가 새 도면으로 안 바뀜'은 `project_ctx.py`(A 소유였음)와 닿을 수 있다. A가 커밋된 뒤에 시작하므로 문제는 없지만, 고쳐야 할 곳이 `project_ctx.py`라면 C가 이어받는다고 작업지시서에 적는다.

---

## 단위 D (2단계): 저장 공용화 묶음 B·C·D

### 1. 스킬

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| 시작 | `poteto-mode` | |
| 설계 | `architect` | 원자적 저장 함수, ID 발급기, history 기록 함수의 서명과 놓을 모듈을 코드 전에 정한다. 호출자가 여러 화면에 흩어져 있어 모양을 잘못 잡으면 되돌리기 비싸다 |
| 이전 순서 | (원칙) `principle-migrate-callers-then-delete-legacy-apis`, `principle-make-operations-idempotent` | 호출자를 옮긴 뒤 옛 함수를 지운다 |
| 상태 검증(선택) | `statechart` | '읽기 → 지문 → 교체' 경합을 경로로 보이고 싶을 때. 남은작업에 TLC 모델이 세션 임시 폴더에만 있다는 기록이 있다 |
| 검토 | `interrogate` | 저장·ID 경로라 지적을 실행으로 증명해야 한다(규칙 3). hazop-reviewer와 Codex 검토의 지적을 재현할 때 쓴다 |
| 생략 | `arena` | 모양은 `architect`로 정한다. 후보를 여러 개 만들 만큼 열린 문제가 아니다 |

### 2. 세션 구성

- **순차 세션 3개**(B 저장 → C 발급기 → D history). C와 D는 B의 저장 함수를 쓰므로 병렬로 돌리면 같은 호출자 파일(`screens/study.py`, `screens/viewer.py`, `screens/initiating.py`, `ie/store.py`, `project_ctx.py`)에서 부딪힌다. 처음 세션에서 `architect`로 세 함수의 모양을 한꺼번에 정해 두고, 구현만 셋으로 나눈다. 한 세션으로 묶어도 되지만, 그러면 검토 범위가 커져 검토 한 번에 다 보기 어렵다.
- 파일 주인: 새 공용 모듈(예: `hazop/store_io.py`)과 각 세션이 옮기는 호출자. C 단위가 끝난 뒤에 시작하므로 `screens/*`를 이어받는다.
- 흐름은 '대'다(단계 간 규격 변경). 세션마다 hazop-reviewer와 Codex를 병렬로 한 번 돌린다.

### 3. 완료 기준

1. 남은작업 '저장·이력 경미 후속'의 항목이 각각 닫히거나, 닫지 않은 이유가 적혀 있다. 지문 확인과 교체의 원자성, `_save` 끝의 OSError, `_check_shape`의 members 자료형, `make_op`의 used_ids 기본값이 대상이다.
2. 공용 저장 함수로 쓴 파일이 쓰는 도중 프로세스를 죽여도 깨지지 않는다. 쓰다 만 임시 파일을 남기지 않는 재현 시험이 있다.
3. 발급기가 지운 번호를 다시 주지 않음을 앱 경로와 스크립트 직접 호출 둘 다로 시험한다.
4. 전체 시험, `check_version_migration.py`, `check_study_nodes.py`, `check_corrections.py`가 통과한다.

### 4. 위험

- ID 발급을 바꾸면 기존 저장 파일의 번호와 이어져야 한다. 옛 파일을 읽어 다음 번호를 정하는 이전 시험을 먼저 만든다.
- A에서 만든 백업 함수와 이 단위의 원자적 저장 함수가 같은 모듈에 있어야 하는지 `architect` 단계에서 정한다.

---

## 단위 E (3단계, D 뒤): IE P5와 빠진 품질 경고

### 먼저 정할 것

이 단위는 성격이 다른 둘을 묶었다. 나누기를 권한다.

- **E1 품질 경고 3종.** 보호설비 고장이 원인 칸에 있음, 구간 경계 결과 끊김, 전기·제어 구간인데 FMEA 없음. 설계서(`specs/ie-output-design.md` 시트 8)에 정의가 있어 바로 구현할 수 있다. 다만 'FMEA 없음' 경고는 FMEA 입력(P5의 D5)이 없으면 항상 뜬다. E2보다 먼저 넣을지, 문구를 'FMEA 입력 기능 없음'으로 둘지 총괄이 정한다.
- **E2 P5(FMEA 입력·MLD 가지 대조).** 설계서 §표에서 규모가 '대'다. FMEA 입력 형식(D5)이 아직 정해지지 않았고, MLD 분류는 E9(결정 보류)와 닿는다. 구현 전에 기획 단계(hazop-planner)와 사용자 질의가 필요하다. 그리고 INTENT의 지금 우선순위('쓸 수 있는 완성본과 패키징 먼저')와 맞대어 보면, P5는 새 기능 확장이다. 총괄은 규칙 8에 따라 지금 범위에 넣을지 사용자에게 먼저 묻는다.

### 1. 스킬

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| E1 | `poteto-mode` + `tdd` | 경고마다 걸리는 예와 안 걸리는 예를 시험으로 둔다 |
| E2 기획 | `figure-it-out` 또는 `architect` | 입력 형식, ⑥ 화면, 묶음 시트 7 열 추가를 한 번에 설계 |
| E2 사용자 질의 | `in-your-own-words` | 총괄이 목표를 되짚어 사용자 확인을 받을 때 |
| 생략 | `arena`, `swarm` | |

### 2. 세션 구성

- E1: 하위 세션 1개. 파일 주인은 `hazop/ie/bundle.py`, `hazop/ie/bundle_xlsx.py`, 관련 시험. 묶음 '읽는 법' 시트 안내도 함께 고친다.
- E2: 기획이 승인된 뒤 구현 세션 1개. `hazop/ie/*`와 `screens/initiating.py`를 쓴다. E1과 파일이 겹치므로 E1 다음에 순서대로 돌린다.

### 3. 완료 기준

- E1: 시트 8의 경고가 5종이 되고, 경고마다 시험이 있고, '읽는 법' 시트에 안내가 있으며, 전체 시험이 통과한다. `scripts/export_ie_bundle.py`로 만든 예시 묶음에서 경고가 보인다(가상 데이터만 쓴다).
- E2: 기획서에서 정한 완료 목록을 따른다(시작할 때 번호 붙인 목록으로 만든다. 규칙 8).

### 4. 위험

- 실제 설계자료를 쓰면 Codex 교차검증에 사용자 확인이 필요하다(규칙 7). 예시는 가상 데이터로 만든다.
- 품질 경고가 많아지면 사람이 볼 양이 늘어난다(교훈: 초안 3,440개). 경고는 묶음별로 세어 요약에 보인다.

---

## 순서 요약

```
A (1세션) ──► B (1세션) ┐
            └► C (1세션) ┴──► D (3세션, 순차) ──► E1 (1세션) ──► [사용자 결정] ──► E2 기획 ──► E2 구현
```

- A가 커밋된 뒤에 B·C를 함께 띄운다. 자동 알림으로 시작한 차례에는 새 세션을 띄울 수 없으니(규칙 10), B·C는 사용자가 시작한 차례에 함께 띄우거나 새 작업 제안 카드로 남긴다.
- 사용자에게 먼저 물을 것: Pretendard를 배포본에 넣을지(B), P5를 지금 범위에 넣을지(E2).

---

## 단위 CI: 가벼운 CI 도입 (2026-11-10 추가)

기준 커밋 9154143. 근거로 읽은 것은 `docs/2026-11-10-ci-review/README.md`(§2·§4·§5), `docs/2026-11-10-naming-rules/README.md`(초안), `tests/__init__.py`, `scripts/devenv.py`, `scripts/preflight.py`, `packaging/requirements*.txt`, 시험의 건너뛰기 조건, `scripts/check_*.py`의 import다.

### 먼저 확인한 사실 (계획을 바꾸는 것)

1. **세 requirements 파일은 한 venv에 함께 깔리지 않는다.** 검토 보고서 §5의 첫 단계 2번은 `requirements.txt`, `requirements-pdf.txt`, `requirements-raster.txt`를 함께 설치하라고 했다. 그런데 `requirements-pdf.txt`는 `pillow==12.2.0`, `requirements-raster.txt`는 `pillow==13.0.0`을 해시로 고정한다. raster 파일 머리말도 '별도 venv(`venv-raster-py312`)'라고 적는다. 그래서 CI의 기본 작업은 로컬 시험용 venv와 같은 조합(`requirements.txt` + `requirements-pdf.txt`)으로 꾸린다. OpenCV·OCR 시험은 원래 `HAS_CV`로 건너뛰게 되어 있다. raster를 돌리려면 나중에 따로 작업(job)을 하나 더 둔다.
2. **패키지가 빠져도 시험은 실패하지 않고 조용히 건너뛴다.** `tests/__init__.py`는 인터프리터 종류만 보고 패키지는 보지 않는다. 그리고 pdfplumber 시험 10여 개는 `skipUnless(HAS_PDFPLUMBER)`다. 설치가 반쯤 실패해도 CI는 초록불이 된다. 그러므로 unittest 전에 `scripts/preflight.py --profile test`를 꼭 돌린다. 이 명령은 빠진 패키지가 있으면 rc=2로 멈춘다. 그리고 건너뛴 시험과 이유를 실행 요약에 찍는다.
3. **APR1400 시험은 CI에서도 돈다.** `test_apr1400_extract`·`test_apr1400_connectors`는 저장소 밖 DCD 원본이 아니라 추적 파일 `tests/fixtures/apr1400/`(7개)를 쓴다. 검토 보고서 §2의 '돌 수 없는 것'에 든 것은 `check_apr1400.py`·`check_project_kg.py`뿐이다.
4. **`scripts/ci_*.py`는 이름 규칙에 어긋난다.** 엄격안에서 새 스크립트 이름은 `<동사>_<대상>.py`이고, 동사 목록에 `ci`는 없고 `run`은 있다(naming-rules §3 표). 그래서 진입점은 `scripts/run_ci.py`로 짓는다.
5. **실행이 두 번 겹칠 수 있다.** 총괄이 단위마다 `feat/next-units`로 푸시하고 그 브랜치에 PR #15가 열려 있으면, `push`와 `pull_request` 두 이벤트가 같은 커밋을 두 번 돌린다. 트리거는 `push`(모든 브랜치) + `workflow_dispatch`로 둔다. PR 화면에는 머리 커밋의 push 결과가 그대로 보인다. 남의 저장소에서 온 PR(fork)을 받게 되면 그때 `pull_request`를 더한다.
6. **비밀값은 필요 없다.** `anthropic` SDK는 requirements에 없어서 `test_analysis`의 SDK 시험은 건너뛴다. 실제 Claude를 부르는 `check_cli_live.py`·`check_ai_analysis.py`는 CI 목록에서 뺀다. 러너에는 `~/.local/bin/claude.exe`가 없으므로 가짜 CLI(`tests/fake_claude`)만 쓰인다.

### 1. 스킬

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| 시작 | `poteto-mode` | 규칙 10 |
| 설정 모양 | (원칙) `principle-build-the-lever`, `principle-boundary-discipline` | 워크플로 YAML에는 '어디서, 어떤 Python으로, 무엇 하나를 부른다'만 적는다. 무엇을 돌릴지는 `scripts/run_ci.py`가 정한다. 이름 이전이 오면 Python 한 곳만 고치면 된다 |
| 재발 방지 | `correct` 축소판 | `tests/test_ci_config.py` 하나를 둔다. 워크플로가 가리키는 파일(`scripts/run_ci.py`, requirements 파일)이 있는지, 워크플로에 한글 경로나 `scripts/check_*` 이름이 직접 적혀 있지 않은지, `run_ci.py` 목록의 스크립트가 모두 있는지를 본다. 이름 이전 단위가 경로를 바꾸면 로컬 시험이 먼저 깨진다 |
| 시간·수치 | `benchmark-checklist` | 설치 시간과 시험 시간을 보고할 때 '어느 실행(run id), 어떤 조건'을 붙인다(규칙 16). 로컬 6분과 러너 시간을 섞지 않는다 |
| 마무리 | `technical-writing` + `unslop` | 검토 보고서에 '첫 실행 결과' 절을 더하고 커밋 메시지를 쓴다 |
| 생략 | `arena`, `architect`, `swarm`, `figure-it-out`, `interrogate`, `tdd`, `create-verification-skill` | 설정 파일 하나와 진입점 하나다. 정답 모양이 정해져 있고, 증명은 GitHub의 첫 실행이 한다 |

### 2. 세션 구성과 파일 주인

- **하위 세션 1개.** 이 세션이 첫 실행 뒤 고치는 차례까지 맡는다. 고칠 때 새 세션을 띄우지 말고 같은 세션에 `SendMessage`로 실행 로그를 넘긴다. 맥락이 그 세션에 있다.
- 파일 주인:
  - `.github/workflows/tests.yml`(새 파일)
  - `scripts/run_ci.py`(새 파일)
  - `tests/test_ci_config.py`(새 파일)
  - 첫 실행에서 실패한 시험의 **건너뛰기 표시 줄만**. 시험 본문 논리는 고치지 않는다. 앱 코드의 결함이 드러나면 고치지 말고 남은작업으로 넘긴다.
  - `docs/2026-11-10-ci-review/README.md`의 '첫 실행 결과' 절
- 손대지 않을 것: `CLAUDE.md`(CI 규칙 문구는 총괄이 쓴다), `records/*.md`(hazop-recorder), `packaging/requirements*.txt`(B 소유였다. 판을 바꾸면 배포본에 닿는다).
- **단위 D와 겹치지 않게 한다.** 건너뛰기 표시가 시험 파일 여러 곳을 건드리므로, D가 시작되기 전에 CI를 끝내거나 D 세션이 아직 손대지 않은 시험만 고친다. 권장 순서는 CI를 먼저 끝내고 D를 시작하는 것이다. 그러면 D부터 CI의 보호를 받는다.
- **이름 이전은 CI 다음이다.** 이전 단위는 `.github/`와 `scripts/run_ci.py`도 대상에 넣고, `tests/test_ci_config.py`가 통과해야 끝난 것으로 본다. 이 조건을 이전 단위의 작업지시서에 적는다.

### 3. 설정에 넣을 것 (하위 세션 작업지시서용)

- 러너: `windows-2025`처럼 판 번호를 고정한다. `windows-latest`는 쓰지 않는다. 판이 바뀌면 글꼴·드라이브가 말없이 달라진다.
- 권한: 최상단에 `permissions: contents: read`. 외부 액션(`actions/checkout`, `actions/setup-python`)은 태그가 아니라 커밋 SHA로 고정하고, 옆에 판 번호를 주석으로 단다.
- 같은 브랜치에 새 푸시가 오면 앞 실행을 취소한다(`concurrency`, `cancel-in-progress: true`). 제한 시간은 `timeout-minutes: 45`.
- 환경변수: `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`, `QT_QPA_PLATFORM=offscreen`, `HAZOP_WORK_ROOT=${{ runner.temp }}\hazop-work`. 작업 루트를 저장소 밖 임시 폴더에 둬야 로컬 `작업/`이 없다는 사실이 그대로 드러난다.
- 받아오기: 한글·`&`·공백이 든 경로(`자원/참고자료/P&ID 도면 샘플/`)와 긴 경로(`licenses/`)를 위해 `git config --global core.longpaths true`를 먼저 하고 `core.quotepath=false`로 로그를 찍는다.
- 설치: Python 3.12(로컬 venv와 같은 3.12.x). `pip install -r packaging/requirements.txt`. 그다음 `pip install --require-hashes --no-deps --only-binary=:all: -r packaging/requirements-pdf.txt`로 파일 머리말의 설치 방식을 그대로 쓴다. pip 캐시는 `setup-python`의 `cache: pip`.
- 단계는 셋이다.
  1. `python scripts/preflight.py --profile test`
  2. `python scripts/run_ci.py`. 이 안에서 unittest 전체와 headless 검사 목록을 돌린다
  3. 진단 출력. 맑은 고딕 파일 유무, `tempfile.gettempdir()`와 작업 디렉터리의 드라이브, Python·PySide6 판, 단계별 걸린 시간을 찍는다
- `run_ci.py`는 다음을 한다.
  - 건너뛴 시험 수와 이유별 집계를 `$GITHUB_STEP_SUMMARY`에 쓴다(없으면 표준 출력).
  - 검사 스크립트마다 rc와 걸린 시간을 표로 남긴다.
  - 하나가 실패해도 나머지를 끝까지 돌리고, 마지막에 실패가 하나라도 있으면 rc≠0으로 끝낸다.
- **실패를 감추지 않는다.** `continue-on-error`는 쓰지 않는다. '병합을 막지 않음'은 `main` 보호 규칙을 켜지 않는 것으로 이미 이루어진다. 작업은 실패하면 빨간불로 보여야 알림이 온다(GitHub는 실패하면 푸시한 사람에게 메일을 보낸다).

#### CI에 넣을 `check_*` 목록 (첫 단계)

import를 보고 나눈 것이다. 하위 세션이 아래 '깨끗한 복제 리허설'에서 실제로 통과하는지 확인하고 목록을 확정한다.

| 묶음 | 스크립트 | 비고 |
| --- | --- | --- |
| 넣음(화면 없음) | `check_adapter`, `check_analysis`, `check_compare`, `check_corrections`, `check_expect`, `check_export`, `check_extract`, `check_graph`, `check_kg`, `check_kg_context`, `check_register`, `check_review`, `check_study_nodes`, `check_symbols`, `check_version_migration`, `check_viewer`, `check_snp_baseline` | `check_snp_baseline`은 PySide6를 import하지만 offscreen으로 돈다(검토 보고서 §2) |
| 리허설 뒤 결정 | `check_contract`, `check_kg_algo` | `paths.work_root()` 아래 출력물을 읽는다. 앞 단계가 만들지 않으면 실패하니, 순서를 정하거나 뺀다 |
| 둘째 단계(QtWebEngine 확인 뒤) | `check_app`, `check_edit_screen`, `check_kg_link`, `check_kg_renderer`, `check_kg_screen`, `check_design` | `check_design`은 하위 프로세스로 렌더한다. 남은작업에 '이 환경에서 PermissionError'가 기록되어 있다 |
| 뺌 | `check_user_scenarios`, `check_desktop_support`(실제 데스크톱), `check_apr1400`, `check_project_kg`(DCD 원본), `check_cli_live`, `check_ai_analysis`(실제 Claude) | 로컬에서만 돈다 |

#### 건너뛰기 표시 원칙

- **CI라는 이유로 건너뛰지 말고, 없는 것을 이유로 건너뛴다.** 예: `skipUnless(os.path.isfile(MALGUN))`, `skipUnless(CROSS)`. 환경 이름(`if CI`)으로 건너뛰면 로컬에서도 같은 원인을 놓친다.
- 러너 고유의 한계 때문에 정말 `CI` 조건이 필요하면 `tests/` 안 공용 상수 하나(예: `ON_CI = os.environ.get("GITHUB_ACTIONS") == "true"`)를 쓰고, 이유와 확인한 run id를 줄에 적는다. 이런 표시는 검토 보고서 '첫 실행 결과' 절에 모두 나열한다.

### 4. 완료 기준과 푸시 순서

하위 세션은 푸시하지 않는다. 그래서 '로컬 리허설 → 커밋 → 검토 → 총괄 푸시 → 결과 확인 → 고침 1차 → 다시 푸시'로 나눈다.

1. **로컬 리허설(하위 세션).** 저장소 밖 `D:\HAZOP-trials\ci-rehearsal-20261110\`(README에 주인·목적·지워도 되는 하위 폴더를 적는다. 규칙 14)을 만든다. 거기에 커밋한 HEAD를 `git clone --no-local`로 받아 추적 파일만 있는 상태를 만든다. 새 venv를 만들고 위 설치 단계를 그대로 밟아 설치 시간을 잰다. 그다음 `HAZOP_WORK_ROOT`를 그 폴더 아래 빈 폴더로 두고 `preflight.py --profile test`와 `run_ci.py`를 돌린다. 여기서 `작업/`이나 `resources/references/APR1400_DCD`가 없어서 나는 실패가 대부분 드러난다. 리허설 결과(통과·실패·건너뜀 수, 걸린 시간)를 보고에 적는다.
2. **로컬 시험(하위 세션).** 평소 venv(`<py>`)로 전체 unittest와 새 `tests/test_ci_config.py`가 통과한다(규칙 11).
3. **커밋 → 검토 1회.** hazop-reviewer와 hazop-codex-reviewer를 병렬로 한 번 돌린다. 규모는 '대'로 본다(저장소 전체 인프라이고, 공개 저장소의 보안과 닿는다). 저장소가 공개이고 공개 자료만 쓰니 Codex 사용에 규칙 7의 사용자 확인은 필요 없다. 검토 항목은 권한, SHA 고정, 비밀값 0, 로그에 이 PC 경로가 찍히지 않는지다.
4. **총괄 푸시와 결과 확인.** 총괄이 푸시하면 워크플로가 처음 돈다. PR #15에 묶어 `ccd_pr`의 `get_status`로 결과를 보고, 끝난 뒤 실패한 단계 로그만 `gh run view <run id> --log-failed`로 한 번 받는다. 반복해서 묻거나 깨우기 예약을 걸지 않는다. Auto-fix를 켜면 실패 알림으로 깨어난다. **첫 실행이 GitHub에서 끝까지 돌고 요약에 건너뜀·검사표·진단 줄이 보이면 이 단계는 통과다. 결과가 초록불이 아니어도 된다.**
5. **고침 1차(같은 하위 세션).** 총괄이 run id와 실패 로그를 하위 세션에 넘긴다. 하위 세션은 러너 고유 원인(글꼴, QtWebEngine, 드라이브, 시간)에 건너뛰기 표시를 하거나 목록에서 빼고, 이유와 run id를 적는다. 앱 결함이면 고치지 말고 남은작업으로 보낸다. 커밋 뒤 총괄이 다시 푸시한다.
6. **끝.** 두 번째 실행이 초록불이고, 건너뜀 목록과 이유가 검토 보고서에 있으면 끝이다. 실행 시간은 run id와 함께 적는다. 그다음 hazop-recorder가 `ci-deferred` 메모리와 남은작업을 고친다.

**멈춤 기준(규칙 17).** 세는 것은 '러너에서만 실패하는 시험 수'다. 푸시-고침은 2차까지만 한다. 2차 뒤에도 빨간불이면, 남은 실패를 목록으로 만들어 사용자에게 '건너뛰기로 둘지, 더 고칠지'를 묻는다. 시험 시간이 45분 제한에 닿아도 같은 방식으로 멈추고 묻는다.

### 5. 위험과 먼저 확인할 것

| 위험 | 먼저 할 일 |
| --- | --- |
| QtWebEngine이 offscreen 러너에서 뜨지 않거나 멈춤 | 첫 단계에서는 WebEngine을 쓰는 검사 스크립트를 빼고 unittest만으로 본다. unittest 안의 WebEngine 시험이 멈추면 제한 시간이 다 쓰이므로, `run_ci.py`가 시험 모듈별 걸린 시간을 찍게 해 어느 모듈인지 바로 보이게 한다. 필요하면 `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`, `QT_OPENGL=software`를 시도한다(미확인, 첫 실행으로 확인) |
| 한글 경로·한글 출력 | `core.longpaths`, `PYTHONUTF8=1`. 셸은 `pwsh`나 `bash` 하나로 고정한다. 리허설에서 한글 경로 복제가 되는지 먼저 본다 |
| 드라이브가 하나인 환경 | GitHub Windows 러너는 작업 폴더가 보통 `D:\a\…`, 임시 폴더가 `C:\…`라서 `test_cross_drive`는 돌 가능성이 높다(미확인). 진단 줄로 확인한다. 같은 드라이브여도 ValueError 흉내 시험은 돌므로 결함은 계속 잡힌다 |
| 패키지 누락이 건너뜀으로 숨음 | `preflight.py --profile test`를 앞에 둔다. 건너뜀 수를 요약에 찍는다. 로컬 실행의 건너뜀(단위 A 보고 1,748개 중 20개)보다 크게 늘면 원인을 적는다 |
| 시험 시간 | 로컬 약 6분(작업지시서 값). 러너는 4코어라 더 걸릴 수 있다. 설치 포함 15~25분은 추정이다. 첫 실행 시간을 run id와 함께 적는다 |
| Actions 권한 | 저장소 설정은 '모든 액션 허용'이다(검토 보고서 §1). 워크플로 쪽에서 `contents: read`와 SHA 고정으로 좁힌다. 저장소 설정을 바꾸는 일은 사용자 몫이니 권하기만 한다 |
| 비밀값 | 워크플로에 `secrets.`가 한 번도 나오지 않는지 `tests/test_ci_config.py`가 확인한다. 저장된 비밀값 0개(검토 보고서 §1) |
| 공개 로그 | 로그는 누구나 본다. 이 PC 경로가 찍히지 않는지 확인한다(러너에는 원래 없다). 시험이 `%USERPROFILE%`를 찍는 곳은 러너 경로라 문제없다 |
| 맑은 고딕 | 없으면 `test_design`이 건너뛴다. 1366 폭 측정이 다른 글꼴로 될 수 있으니, 글꼴이 없을 때 폭 시험이 통과해도 '확인 아님'으로 보고한다 |
| 이름 이전과 충돌 | 워크플로에는 `scripts/run_ci.py`와 `packaging/requirements*.txt`만 적는다. 경로 필터(`paths:`)는 쓰지 않는다. `tests/test_ci_config.py`가 이전 단위의 안전망이 된다 |
| 여러 세션의 커밋이 한 푸시에 섞임 | 단위마다 푸시하므로 실패하면 그 단위의 커밋부터 본다. 원인 커밋을 가리기 어려우면 `workflow_dispatch`로 앞 커밋을 다시 돌린다 |

---

## 단위 NAMING: 이름 규칙 이전 (2026-11-10 추가)

기준 커밋 90b9cf6. 근거로 읽은 것은 `docs/2026-11-10-naming-rules/README.md`(HZ-GOV-02 개정 1) §5~§9이다. 계획서의 세 약속은 다음 코드와 맞대어 보았다. `hazop/paths.py`(`rel_or_abs`, `resolve_rel`, `LEGACY_PREFIXES`, `backup_rel`), `hazop/graph/build.py:75`, `hazop/analysis/run.py`(`load_inputs`, `build_bundle`), `hazop/analysis/ai.py:115`, `scripts/build_package.py:74,80`, 표본·시험 입력에 고정된 `graph_version`, `.github/workflows/tests.yml`, `scripts/run_ci.py`, 옛 경로가 남은 `.claude/`·운영 문서·사용자 메모리.

### 먼저 확인한 사실 (계획을 바꾸거나 보강하는 것)

1. **'샘플 기록 경로 고정'은 접두 한 줄로는 안 되고, 하위 폴더 단위로 대응시켜야 한다.** 지금 `rel_or_abs`는 `"참고자료/" + relpath(path, folder("참고"))`로 적는다(`paths.py` 37~39행). `자원/참고자료/`를 `resources/references/`로 옮기는 것만이면 결과가 같다. 하지만 `P&ID 도면 샘플/`을 `pid-samples/`로 바꾸면 뒷부분이 `pid-samples/…`로 바뀌고, 그만큼 `source.file`이 달라져 그래프 판도 바뀐다. 그래서 대응은 `references/pid-samples/` ↔ `참고자료/P&ID 도면 샘플/`처럼 **하위 폴더 단위로 양방향**이어야 한다. 쓰기(`rel_or_abs`)와 읽기(`resolve_rel`의 긴 접두를 먼저 보는 순서, `is_reference_rel`)를 함께 고친다. `P&ID 기호 카탈로그/`도 같다.
2. **그래프 판이 바뀌면 바로 걸리는 장치가 이미 있다.** SNP-M-102 판 `v-f65e4ec1135d`가 `자원/표본/구간/region-SNP-M-102-pzr.json`, `tests/fixtures/kg_algo/expected_SNP-SAMPLE.json`, `tests/fixtures/kg/*/knowledge_links.csv` 8개, `tests/fixtures/kg_context/c1_pre_w7.json`에 고정되어 있다. 고정 응답의 `bundle_sha256`도 그래프 내용을 품은 근거 묶음의 해시다(`ai.py:115`). 단계 5의 완료 기준은 '이 고정값을 하나도 고치지 않고 시험이 통과한다'로 둔다. **고정값을 고쳐 시험을 맞추면 그 자체가 결함이다.**
3. **기준 자료 JSON 안의 출처 문자열은 고치면 안 된다.** `자원/기준/` 아래 4개 파일이 `기획서/…`를 출처로 적는다(예: `applicability-region-SNP-M-102-pzr.json`의 `"source"`). 이 파일들은 `integrity.py`의 `PINNED_SHA256`로 고정되어 있다. 계획 §6.2의 '고치지 않는다'가 맞다. 그런데 `migrate_names.py --rewrite-links`가 `.md`·`.html`만 본다는 범위를 지켜야 한다. JSON·CSV는 대상에서 빼는 것을 시험으로 고정한다.
4. **배포본의 '묶음 경로 유지'는 '같은 경로'가 아니라 '코드와 묶음이 같은 경로를 본다'는 뜻이다.** `build_package.py:80`의 `DATA_DIRS`는 `FOLDERS`의 resource 행에서 만들어져 따라 바뀐다. 묶음 안 경로는 `자원/기준/…`에서 `resources/library/…`로 바뀌고, 앱도 같은 표를 읽는다. 하지만 지침서는 네 곳에 문자열로 적혀 있다(`build_package.py:74`, `integrity.py`, `catalog_md.py`, `packaging/w4_flow.py`). 앱이 이름으로 부르는 `scripts/<이름>.py`는 질문 2 결정으로 바뀌지 않는다. 그래서 확인 방법은 이렇다. 단계 3·5 전후로 배포본 파일 목록과 내용 해시를 뽑아 대조하고, 대응표 밖의 차이가 0인지 본다(빠진 파일 0, 내용이 바뀐 파일은 지침서 하나).
5. **사용자 데이터 호환은 계획서에 빠진 곳이 있다.** 사용자 파일은 작업 루트 기준 상대 경로를 적는다. 분석 결과의 `input_files[].path`(`run.py:70`, 예: `출력/그래프/<이름>/graph.json`), 구간의 `graph_ref.graph_file`, 지식그래프 경로가 그렇다. 지금 `LEGACY_PREFIXES`에는 자원 쪽 접두와 `참고자료/`만 있다. 단계 6에서 `출력/`·`데이터/…` 아래가 이름을 바꾸고 옛 폴더가 `_before-0.2.0`으로 밀려나면, 이 기록들은 `resolve_rel`의 '바로 찾기'에 실패한다. 그래서 **작업 루트 쪽 옛 접두(`출력/그래프/`, `데이터/구간/` 등)도 `LEGACY_PREFIXES`에 넣어야 한다.** 계획의 '출력 하위 폴더를 `FOLDERS`로 모으는 정리 단위'가 바로 이 일의 전제다. 다행히 분석 실행 ID의 해시(`files_sha`, `run.py:408`)는 내용 해시만 쓰고 경로는 쓰지 않는다. 그래도 기록 경로를 문자열 그대로 비교하는 곳(예: 같은 결과 찾기, 탐색기 키)이 있는지는 아직 전수로 보지 않았다(미확인).
6. **이 PC의 배포본 작업 루트(`%LOCALAPPDATA%\HAZOP`)에는 `venv-py312`(옛 venv)도 들어 있다.** 이전 도구가 '모르는 폴더'를 건드리지 않게, 옮길 대상은 대응표의 폴더로만 한정한다.
7. **단위 A에서 생긴 `paths.EXTERNAL_BACKUP_DIR = "_외부"`도 대상이다.** 계획 §5.6 표에 이미 있다(`backup/_external/`).
8. **CI 설정은 이름 이전에 안전하다.** 워크플로는 `scripts/run_ci.py`와 `packaging/requirements*.txt`만 가리킨다. `run_ci.py`의 한글은 건너뜀 이유 문장(`출력/그래프`, `데이터/구간` 등)뿐이다. 단계 6에서 이 문장만 고친다.
9. **§9에는 질문이 넷 있다.** 총괄이 받은 세 결정 말고, 4번 '배포본 옛 작업 폴더를 물어보고 복사할지, 자동으로 옮길지'가 남아 있다. 권장안 자동 선택 방침이면 '물어보고 복사(옛 폴더는 `_before-0.2.0`로 남김)'다. 이 결정을 결정로그에 남긴 뒤 단계 6을 시작한다.
10. **브랜치.** 계획 §7은 `chore/naming-migration` 브랜치를 쓰라고 한다. 그런데 지금은 총괄이 단위마다 `feat/next-units`로 푸시하고 PR #15에서 CI를 본다. 새 브랜치로 가면 CI는 그 브랜치에서도 돌지만, 끝에 `feat/next-units`로 합치는 단계가 하나 더 생긴다. 이전하는 동안 다른 세션이 돌지 않으니, 같은 체크아웃에서 브랜치를 바꾸는 위험은 작다. 어느 쪽이든 되돌리기는 커밋 단위 `git revert`로 같다. **권장은 `feat/next-units`에 그대로 쌓는 것이다.** N11 검사도 이 브랜치 이름을 통과시킨다. 계획서와 다르게 가면 그 이유를 결정로그에 한 줄 남긴다.

### 1. 세션 나누기

총괄이 권한 '세션 1개로 7단계'는 맥락 창(context window)에 맞지 않는다. 문서 링크 480곳, 파일 약 650개를 옮기는 동안 앞 단계의 출력이 쌓여, 위험이 가장 큰 단계 5·6에 이를 때 맥락이 가장 나빠진다. 위험 등급에 맞춰 **순차 세션 4개**로 나눈다. 각 세션 안에서는 총괄 권장대로 단계마다 ①② 커밋을 하고, 단계가 끝날 때마다 총괄이 푸시해 CI로 확인한다. 이 4개를 규칙 3의 '작업 단위'로 본다. 검토는 세션마다 한 번이다.

| 세션 | 단계 | 규모 | 비고 |
| --- | --- | --- | --- |
| N1 | 0(규칙·`test_naming_rules`), 1(저장소 밖·브랜치), 2(`docs/`), 4(시험 입력 1개) | 중 | 코드가 거의 읽지 않는 곳. 여기서 `scripts/migrate_names.py`의 링크 바꾸기(`--rewrite-links`)와 이동 기록(`moves.csv`)을 만들어 단계 2에서 처음 검증한다 |
| N2 | 지침서 경로를 `FOLDERS`로 모으는 정리 → 3(사람 문서 폴더) | 대 | 지침서 해시, 배포본, `.claude/`, 링크 480곳 |
| N3 | 5(`자원/` → `resources/`) | 대 | 그래프 판, 기준값, 기호 사전, 배포본 |
| N4 | 출력 하위 폴더를 `FOLDERS`로 모으는 정리 → 6(`작업/` → `work/`, 이전 도구, 앱 시작 때 감지, 0.2.0) | 대 | 사용자 데이터. 정리 단위가 크면(계획서는 '수십 개 파일, 정리 단위에서 셈') 정리를 N4a, 단계 6을 N4b로 나눈다. 판단 기준: 정리 단위가 바꾸는 파일이 30개를 넘으면 나눈다 |

- 단계 1의 지우기(병합된 로컬 브랜치 16개 삭제, 작업트리 5개 제거, 시험 폴더 이름 바꾸기)는 되돌리기 어렵거나 저장소 밖 일이다. 총괄이 목록을 받아 사용자 확인을 한 번 받은 뒤 진행한다(이전 점검표의 '지우는 일은 사용자 확인 뒤' 원칙). 확인을 기다리는 동안 N1은 단계 2·4를 먼저 한다.
- 이전 단위가 도는 동안 D·E는 대기한다(규칙 4). N1은 코드와 거의 겹치지 않는다. 계획 §6.10대로라면 다른 세션과 함께 돌 수도 있지만, 이미 대기하기로 했으니 그대로 순차로 간다.

#### 단계별 스킬

| 단계 | 쓸 스킬 | 생략 |
| --- | --- | --- |
| 0 | `poteto-mode`, `correct`(N1~N11이 과거 실제 위반에서 실패함을 보인다. 예: `docs/screenshots-pdf`, 손 버전 `계통약어_v2.csv`), `unslop`(CLAUDE.md 규칙 18 문안. 문안은 총괄에게 넘긴다) | `tdd`, `architect` |
| 1 | `poteto-mode`, `show-me-your-work`(`moves.csv`가 곧 결정 기록. 저장소 밖이라 git이 되돌려 주지 않는다) | 나머지 |
| 2 | `poteto-mode`, `tdd`(링크 바꾸기 도구. 상대 링크, 백틱 경로, 바꾸면 안 되는 결정로그 본문 문장, JSON·CSV 제외), (원칙) `principle-make-operations-idempotent`(두 번 돌려도 같은 결과) | `arena`, `swarm` |
| 3 | `poteto-mode`, `blast-radius`(지침서를 옮긴 뒤 `catalog_md`가 같은 카탈로그를 내는지, 배포본 지침서 경로를 실제 빌드로 증명) | `how`, `architect` |
| 4 | `poteto-mode` | 나머지 |
| 5 | `poteto-mode`, `blast-radius`(사실 1·2: 샘플 6장의 `graph_version`을 옮기기 전후로 실제로 뽑아 같음을 증명), `benchmark-checklist`는 쓰지 않는다(점수는 '맞은 수/분모 @커밋'으로 충분) | `arena`, `swarm`, `tdd` |
| 6 | `poteto-mode`, `architect`(이전 도구·앱 시작 감지·설정 경로 변환·`LEGACY_PREFIXES` 작업 루트 접두의 서명을 코드 전에), `tdd`(`--apply`/`--undo` 왕복, 중간에 끊긴 이전, 두 번 실행), `interrogate`(검토 지적의 재현 수단. 사용자 데이터 경로라 규칙 3), 프로젝트 스킬 `verify-hazop`(S1~S6, 데스크톱 잠금 안) | `arena`, `figure-it-out`(계획서가 이미 있다) |
| 모든 단계 | `unslop`(커밋 메시지·보고) | |

`swarm`은 쓰지 않는다. 같은 파일을 여러 일꾼이 동시에 고치게 되기 때문이다. 다만 단계 6을 시작하기 전의 읽기 전용 조사, 곧 '기록 경로를 문자열 그대로 비교하는 곳 찾기'(사실 5의 미확인)는 `Explore` 하위 에이전트 하나에 맡기면 된다.

### 2. 단계별 완료 기준과 되돌리기

공통 완료 기준:
- 전체 unittest(`PYTHONIOENCODING=utf-8 <py> -m unittest discover -s tests -t .`)
- `test_naming_rules`의 그 단계 예외 줄 삭제
- 총괄 푸시 뒤 CI 초록불(run id 기록)
- 단계 전 `git bundle` 백업

공통 되돌리기: 그 단계의 ②, ① 커밋 순서로 `git revert`한다. **단계는 뒤에서부터만 되돌린다**(5를 둔 채 3만 되돌리면 링크 표가 어긋난다).

| 단계 | 그 밖의 완료 기준 | 되돌리기에 더할 것 |
| --- | --- | --- |
| 0 | `test_naming_rules`가 HEAD에서 통과하고, 일부러 넣은 위반 예에서 실패 | — |
| 1 | `preflight.py` 경고 0, `git worktree list` 정리, 지운 브랜치 목록과 그 끝 커밋 SHA 기록 | `moves.csv` 역순으로 이름 되돌림. 브랜치는 기록한 SHA로 `git branch <이름> <SHA>` |
| 2 | 링크 대상 검사(N9) 실패 0, 도구의 바꾼 줄 목록 저장 | — |
| 3 | `test_integrity_pins`, `test_packaging` 통과. 새 `GUIDE_SHA256`과 이유가 같은 커밋에 있음. 시안 `build.py` 재실행 결과 같은 그림. 배포본 빌드 + `verify_bundle.py` 통과. 묶음 파일 목록·해시 대조(사실 4)에서 대응표 밖 차이 0. `.claude/agents/hazop-recorder.md`가 새 `records/`를 가리킴 | 지침서 해시는 ②에 같이 있어 함께 돌아감 |
| 4 | 해당 시험 통과, `make_design_doc.py`가 같은 PDF를 만듦(바이트 비교 또는 추출 결과 비교) | — |
| 5 | (1) 고정 `graph_version`·`bundle_sha256` 파일 수정 0(`git diff --stat`로 보임) (2) `refresh_fixture_hashes.py --check` 차이 0 (3) `check_snp_baseline.py` 후퇴 0과 `check_apr1400.py` 점수 동일(둘 다 `--update` 없이, '맞은 수/분모 @커밋') (4) 배포본 빌드·`verify_bundle.py`·묶음 대조 (5) S1~S6 | 추적 안 하는 APR1400 원본·도면별은 `moves.csv`로 되돌림. 저장소 밖 시험 폴더 사본도 같은 표로 |
| 6 | (1) 재현 스크립트(아래)에서 이전 전후 화면 데이터 수 동일 (2) `--apply`→`--undo` 왕복 뒤 해시 동일 (3) 같은 작업 루트에 두 번 `--apply`해도 변화 없음 (4) 기준값 두 개 그대로 (5) 이 PC 배포본 작업 루트 **사본**으로 새 배포본을 열어 등록 자료·분석 결과가 보임 (6) S1~S6 | 코드는 revert. 사용자 데이터는 `migrate_names.py --undo <manifest>`. 개발 `작업/`은 시작 전 통째 사본(`D:\HAZOP-trials\<날짜>-naming-n4\work-before\`)으로도 되돌릴 수 있게 한다 |

**단계 6 재현 스크립트(규칙 3).** 이 PC의 `%LOCALAPPDATA%\HAZOP`(`venv-py312` 제외)와 `D:\HAZOP\작업\`을 저장소 밖 시험 폴더에 복사한다. 그 사본을 작업 루트로 두고, 화면 없이 `hazop.app.data`와 탐색기가 보는 목록(등록 자료 수, 추출·그래프 수, 구간 수, 분석 결과 수, 검토 기록 수, 초기사건 그룹 수)을 센다. 이전 전 HEAD 코드, 이전 뒤 새 코드에서 각각 세어 같아야 한다. 수가 맞아도 '경로를 못 찾음' 경고가 하나라도 새로 생기면 실패로 본다.

### 3. 검토 강도

| 세션 | 검토 | 이유 |
| --- | --- | --- |
| N1 | hazop-reviewer 1회(세션 끝, 단계 0·1·2·4 묶어서) | 코드가 거의 읽지 않는 곳이다. `test_naming_rules`와 링크 검사가 기계적으로 지킨다 |
| N2 | hazop-reviewer 1회 | 지침서 해시와 배포본은 시험과 빌드가 직접 증명한다. Codex는 생략해도 된다 |
| N3 | hazop-reviewer + hazop-codex-reviewer 병렬 1회 | 그래프 판·기준값·기호 사전. 공개 자료라 Codex에 사용자 확인은 필요 없다(규칙 7) |
| N4 | hazop-reviewer + hazop-codex-reviewer 병렬 1회. 지적의 재현은 `interrogate`로 | 사용자 데이터 경로라 지적은 재현 전에는 경미로 낮추지 않는다(규칙 3) |

단계마다 검토하지 않는다. 단계마다 지켜야 할 것은 CI와 위 완료 기준이 지킨다. 검토는 세션 끝의 diff 전체를 한 번 본다. 검토 지적을 고쳐 다시 커밋하면, 총괄이 다시 푸시해 CI를 확인한다.

### 4. 가장 위험한 단계, 먼저 확인할 것, 멈춤 기준

- **가장 위험한 것은 단계 6이다.** 저장소 밖 사용자 데이터를 옮기고, 이미 깔린 배포본이 다음에 켜질 때 동작이 바뀐다. git으로 되돌릴 수 없는 유일한 단계다. 그다음은 단계 5다. 그래프 판이 바뀌면 고정 응답·지식그래프 연결·구간이 줄줄이 어긋난다.
- **단계 6 전에 먼저 확인할 것.**
  1. 사실 5의 미확인 사항, 곧 기록 경로를 문자열로 비교하는 곳을 전수로 찾는다.
  2. 위 재현 스크립트를 **이전 코드를 쓰기 전에** 먼저 만들어, HEAD에서 기준 수를 뽑아 둔다.
  3. `settings.json`의 `recent_runs`·`recent_regions` 절대 경로가 실제로 어떤 모양인지 본다. 이 PC는 지금 비어 있으니 시험 자료로 만든다.
  4. §9 질문 4를 결정로그에 확정한다.
- **단계 5 전에 먼저 확인할 것.** 옮기기 전 샘플 6장의 `graph_version`과 고정 응답 `bundle_sha256` 목록을 뽑아 저장소 밖에 둔다. 디스크 여유가 10GB 이상인지 본다(`check_apr1400.py`, 규칙 14). APR1400 원본은 손으로 옮겨야 하므로, `check_apr1400.py`의 입력 존재 확인이 새 이름을 보는지 먼저 돌려 본다.
- **멈춤 기준(규칙 17).** 세는 것은 '대응표 밖의 차이'다. 아래 중 하나라도 나오면 그 단계를 되돌리고 총괄이 사용자에게 보고한다. 고쳐서 밀고 나가지 않는다.
  - 고정 `graph_version`·`bundle_sha256`·`PINNED_SHA256`을 고쳐야만 통과하는 시험
  - 기준값 점수 1이라도 변화
  - 배포본 묶음 대조에서 대응표 밖 차이
  - 단계 6 재현의 수 차이나 새 경고
- **CI 멈춤.** 한 단계의 푸시 뒤 CI가 빨간불이면 같은 세션이 한 번 고친다. 두 번째도 빨간불이면 멈추고 묻는다.

### 5. 옛 경로가 적힌 운영 파일은 누가 언제 고치나

옛 경로가 남은 곳을 찾아 보니 `.claude/agents/` 4개(designer·developer·planner·recorder), `CLAUDE.md`, `INTENT.md`, 사용자 메모리 8개(`completion-target-scope`, `init-work-track-rollout`, `kg-schema-ie-decisions`, `korean-writing-polish`, `move-to-d-drive`, `parallel-when-possible`, `ultimate-goal-initiating-events`, `use-pstack-for-work`)였다. `.claude/skills/`와 `~/.claude/skills/init-work`에서는 찾지 못했다.

| 대상 | 누가 | 언제 | 방법 |
| --- | --- | --- | --- |
| `.claude/agents/*.md`, `.claude/skills/*` | 그 단계의 하위 세션 | 그 폴더를 옮기는 단계의 ② 커밋(`디자인/`·`기획서/`·`메모리/`는 단계 3, `자원/`은 5, `작업/`은 6) | `migrate_names.py --rewrite-links`로 기계적으로 바꾼다. 특히 `hazop-recorder.md`는 단계 3과 같은 커밋이어야 한다. 늦으면 기록 담당이 없는 `메모리/`에 새 파일을 만든다. N8이 지킨다 |
| `CLAUDE.md` | **총괄** | 단계 0에 규칙 18을 넣고, 단계 3·5·6이 끝날 때마다 경로(규칙 4의 `메모리/*.md`, 규칙 12의 `자원/기준/기호/` 등)를 고친다. 하위 세션의 ② 커밋 뒤, 푸시 전에 | 운영 규칙이라 하위 세션이 고치지 않는다. 도구의 바꾼 줄 목록을 받아 총괄이 직접 적용하고 따로 커밋한다 |
| `INTENT.md` | 하위 세션의 도구가 **링크와 백틱 경로만** 바꾸고, 총괄이 diff를 확인 | 단계 3·5·6의 ② 커밋 | 의도 관리 세션의 문서라 본문 문장은 건드리지 않는다. 끝나면 의도 관리 세션에 바뀐 줄을 알린다 |
| `메모리/결정로그.md`, `남은작업.md` | hazop-recorder | 단계 3이 옮긴 뒤(`records/`) | 링크만 도구로 바꾸고 본문 문장의 옛 이름은 기록이라 둔다(계획 §6.9) |
| 사용자 메모리 `~/.claude/projects/D--HAZOP/memory/*.md` | **총괄** | 단계 3 끝(`메모리/`·`기획서/`), 단계 6 끝(`자원/`·`작업/`). git 밖이라 CI가 보지 않는다 | 먼저 폴더를 통째 복사해 둔다. 앞으로의 행동을 지시하는 경로만 고치고(예: '기록은 `메모리/…`에'), 지난 일을 적은 문장은 둔다. `MEMORY.md` 색인도 확인한다 |
| 작업지시서 머리말(§8.3) | 총괄 | 단계마다 '지금 이전 단계: n'을 갱신 | 이전 중 새로 띄우는 세션이 옛 이름과 새 이름을 헷갈리지 않게 한다 |



---

## 단위 DOC·G·F: INTENT 남은 항목 실행 (2026-11-10 추가)

기준: `feat/next-units` @ 2f769b9. 이미 계획된 N4 → D → E 뒤에 붙인다.

### 먼저 확인한 사실 (계획을 바꾸는 것)

1. **단위 G의 본체는 이미 들어가 있다.** AI 구간 검토 S6이 S6a(b0d016a), S6b(c15bf52), ④ 속도 정리(4816182)로 커밋되어 있다. `hazop/study/node_review.py`(479줄), ④ '스크리닝' 메뉴의 'AI 구간 검토…', 받아들이기·고쳐서 받기·기각, 가짜 클라이언트와 가짜 CLI(`tests/fake_claude`)로 돌리는 `tests/test_node_review.py`·`tests/test_study_review_ui.py`가 있다. INTENT §3.4 마지막 항목('그래프로 먼저 자르고 AI가 검토, 사람이 확정')은 기능으로는 이미 채워졌다. 남은 것은 `specs/study-node-segmentation.md` §4.7에 '후속(이번에 하지 않음)'으로 적힌 다섯 가지다. G는 새 기능이 아니라 후속을 마무리하는 단위로 다시 잡아야 한다.
2. **성능 계획(§5.4)도 대부분 끝났다.** N2, N3(f9a3b29), N4(ddb9c03), N5가 커밋됐다. §5.6·§5.7 측정으로 ②③④⑤ 화면 전환은 0.35~1.10초, 시작은 2.9~3.8초다. 다른 세션이 CPU를 80% 안팎으로 쓰던 때 번갈아 잰 범위다. 남은 것은 부하 없는 기계에서 5회 중앙값으로 목표(D7)를 다시 재는 일과 gc 수명 관리 후속(§5.7)이다. F 안의 '성능'은 새 최적화가 아니라 재측정과 gc 후속이다.
3. **기호 사전 계획에서 남은 단위가 있다.** `specs/pid-symbol-dictionary.md` §7의 S7(기존 규칙을 사전으로 옮기고 `_shape_kind`·`EQUIPMENT_WORDS` 삭제)과 D8(사전 판을 등록 기록에 남김)이 아직 안 됐다. 검정(닫힘) 밸브 씨앗(§4.2 1번)도 견본이 없어 미뤄져 있다. 미확인 줄이기의 다음 후보 네 개는 `docs/2026-11-10-apr1400-unknowns/README.md` §3 끝에 있다(모두 측정 전 추정).
4. **`overview.md`와 README 본문에 `출력/…`·`작업/` 같은 작업 루트 경로가 있다**(overview 282행, README 80·102행). N4 단계 6이 이 줄들을 고치므로 DOC는 N4 뒤에 해야 한다.
5. **INTENT §7 1번은 이미 결정됐다**(DEC-0188의 D7 'README 범위 문구 수정'). 다시 물을 필요가 없다. 5번은 아직 사용자 답이 없다. README '프로젝트 방향' 4번의 AI 순서를 고칠지가 걸려 있다. 권장안(구독제 기본, API는 따로 둔 선택지, 로컬 LLM은 나중)을 자동 채택할지는 총괄이 정한다(메모리 auto-pick-recommended).
6. **`check_apr1400.py --update` 잠금은 체크아웃 전체를 본다.** `scripts/devenv.py`의 `SCORING_PATHS`는 `hazop`·`scripts`·기호 사전·`tests/fixtures/apr1400`이다. 같은 체크아웃에서 D·E·G 세션이 `hazop/`을 고치고 있으면 F의 기준값 갱신이 막힌다. F는 자기 작업트리에서 돌아야 한다.
7. **'INTENT에 있는 것 다 실행'은 끝이 열린 목표다.** 규칙 8대로 시작할 때 번호 붙인 완료 목록으로 바꿔 사용자 확인을 받는다. INTENT §6(보류)과 §7의 2·3·4·6~12번은 실행할 일이 아니라 사용자 답을 기다리는 질문이라 아래 초안에 넣지 않고 따로 묶었다.

### 완료 목록 초안 (총괄이 사용자 확인을 받을 것)

| 번호 | 항목 | INTENT 근거 | 단위 |
| --- | --- | --- | --- |
| 1 | overview·README 범위 문구를 IE 최종 목표(D7·E1~E10)에 맞춤 | §7-1, DEC-0188 | DOC |
| 2 | 지금 앱을 말하는 문장의 ①~⑤를 ①~⑥으로 | §3.7, P3 | DOC |
| 3 | README AI 연결 순서 문구(§7-5 답을 받은 뒤) | §7-5 | DOC |
| 4 | AI 구간 검토 후속 중 사용자가 고른 것 + 실제 구독 소량 실측 | §3.4 끝 | G |
| 5 | 기호 사전 S7 이관, D8 판 기록 | §3.2 | F1 |
| 6 | 미확인 줄이기 다음 후보(멈춤 기준 안에서) | §3.2 | F1 |
| 7 | 143쪽 성능 재측정(부하 없는 기계), gc 후속 | §3.8, D7 | F2 |

따로 물을 것: INTENT §7 2·3·4·6~12번과 §6 보류 항목을 이번 목표에 넣을지. 넣지 않으면 '이번 범위 밖'으로 보고한다.

### 파일 겹침과 순서

| 단위 | 주로 고치는 파일 | 겹치는 단위 |
| --- | --- | --- |
| D | `screens/study.py`, `screens/viewer.py`, `screens/initiating.py`, `ie/store.py`, `app/project_ctx.py`, 새 공용 저장 모듈 | G(`study.py`·`viewer.py`), F2(`project_ctx.py`), E(`initiating.py`) |
| E | `ie/bundle.py`, `ie/bundle_xlsx.py`, `ie/*`, `screens/initiating.py` | D |
| DOC | `README.md`, `specs/overview.md` | N4(같은 두 파일의 경로 줄) |
| G | `study/node_review.py`, `screens/study.py`, `screens/viewer.py`(점선을 넣을 때만), `app/explorer.py`(④ 묶음), `specs/study-node-segmentation.md` | D(`study.py`·`viewer.py`) |
| F1 | `extract/adapters/pdf_vector.py`, `extract/symbols.py`, `resources/library/symbols/`, `kg/schema/registry.json`, `scripts/check_apr1400.py`, `tests/fixtures/apr1400/`, `tests/baselines/apr1400_score.json`, `register/` 실행 정보(D8) | 없음 |
| F2 | `app/main_window.py`, `app/project_ctx.py`, `graph/project.py` | D(`project_ctx.py`) |
| 모두 | `records/decision-log.md`, `records/backlog.md` | hazop-recorder 한 명이 차례로 쓴다 |

`hazop/study/nodes.py`는 세 단위 중 G만 건드릴 수 있다('고쳐서 받기'가 편집 연산을 새로 부를 때). D가 `nodes.py`의 저장 경로를 공용 함수로 옮기므로 G는 D 뒤다. `screens/results.py`는 세 단위 모두 건드리지 않는 것이 맞다. 받아들인 설계 의도는 이미 ⑤에 'AI 초안'으로 보인다.

```
N4 ──► DOC (1세션, 문서만)
   ├─► D (3세션 순차) ──► G (1세션)
   │                  ├─► E1 ──► [사용자 결정] ──► E2
   │                  └─► F2 (1세션, 다른 세션이 하나도 안 돌 때 측정)
   └─► F1 (자기 작업트리, 하위 단위마다 세션 1개, 순차)
```

- DOC은 N4가 커밋되자마자 D와 나란히 돌려도 된다. 문서 두 개만 고친다.
- F1은 D·E·G와 파일이 겹치지 않아 N4 뒤 곧바로 나란히 돌릴 수 있다. 조건은 셋이다.
  - 자기 작업트리(`use_worktree: true`)에서 돈다. 브랜치를 `feat/next-units`에 합치는 일은 총괄이 한다.
  - `check_apr1400.py` 전체 실행은 CPU를 최대 8개 쓴다. 다른 세션이 시간을 재는 동안에는 돌리지 않는다.
  - 디스크 여유가 10GB 이상이어야 한다.
- G는 D 뒤에 한다(`screens/study.py`·`viewer.py`). E와는 겹치지 않아 나란히 돌려도 된다.
- F2는 D 뒤에 한다(`project_ctx.py`). 시간 측정은 다른 세션이 하나도 돌지 않을 때만 한다(교훈: CPU 부하 80~99%에서 잰 값이 넓게 흔들렸다).

---

### 단위 DOC: 범위 문구와 ⑥ 표기

**스킬.**

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| 시작 | `poteto-mode` | 규칙 10. '중'이라 hazop-planner를 총괄이 직접 불러도 되지만, INTENT §7-3('planner를 계속 쓰나')이 열려 있어 pstack 세션으로 통일하기를 권한다 |
| 쓰기 | `technical-writing` | 범위 문단은 결론을 앞에 둔다: 'HAZOP 결과를 만들고, IE 후보와 추적 근거를 인계 묶음으로 넘긴다. 빈도는 다루지 않는다' |
| 윤문 | `unslop` | 메모리 korean-writing-polish. 커밋 전에 바뀐 문단만 |
| 생략 | `architect`, `tdd`, `interrogate`, `arena` | 코드가 없다 |

**세션.** 1개. 파일 주인은 `README.md`와 `specs/overview.md`뿐이다. `INTENT.md`는 고치지 않는다. 끝나면 의도 관리 세션에 '§7-1 이행, 5번은 이렇게 반영'을 알린다.

**고칠 곳(2f769b9에서 찾은 줄).**
- `specs/overview.md` 17행 "HAZOP 결과를 만드는 것까지를 범위로 하며 … 다른 곳에서 수행합니다(2026-11-03)"를 2026-11-08 결정으로 바꾸고, 바뀐 경위를 한 줄 남긴다.
- `specs/overview.md` 29~33행 '전체 구성' 1~5번에 6번 '초기사건 인계'(`ie-output-design.md`)를 더한다. 37행 "①~⑤ 화면"을 ①~⑥으로 바꾼다.
- `README.md` 5행 "IE 도출은 조사 단계", 7행 "현재는 기획 단계이며 … 1차 구현"을 지금 상태로 바꾼다. 25행 "①②④⑤ 화면"도 확인한다.
- `README.md` 38행 AI 순서는 §7-5 답이 오면 고친다. 답이 없으면 그대로 두고 보고에 적는다.
- 지난 일을 적은 문장은 고치지 않는다(README 62행, overview 115행의 첫 수직 슬라이스 ①~⑤). `stage-chain-check`의 '①→⑤'는 연쇄 검사가 실제로 ⑥까지 보는지 코드로 확인한 뒤에만 바꾼다.
- 범위 밖: 다른 문서의 ①~⑤(`design/screen-spec.md`, `packaging/README.md`, `.claude/skills/verify-hazop/features/README.md` 등 7곳)는 목록만 남긴다.

**완료 기준.**
1. 두 파일에서 "다른 곳에서 수행", "조사 단계", "현재는 기획 단계"가 사라지고, 새 문장마다 출처(DEC-0188·DEC-0199)가 있다.
2. 지금 앱을 말하는 문장은 ①~⑥이고 지난 일을 적은 문장은 그대로다. diff로 한 줄씩 판정해 보고한다.
3. `overview.md` 머리말 rev를 HZ-GOV-02 개정 규칙대로 올리고, status는 `draft`로 둔다(`approved`는 총괄만).
4. 시험용 venv로 `tests/test_naming_rules.py`와 링크 검사 시험이 통과한다.

**검토.** hazop-reviewer 1회. Codex는 쓰지 않는다(문서 두 개, '중'). QA는 링크 시험만 본다. 멈춤 기준은 따로 두지 않고, 고칠 곳이 두 파일을 넘으면 넘는 부분은 목록으로 남긴다.

---

### 단위 G: AI 구간 검토 후속

**범위를 먼저 정한다.** §4.7 후속 가운데 무엇을 넣을지 사용자 확인을 받는다(완료 목록 4번). 권장은 g1~g3을 넣고 g4·g5는 뒤로 두는 것이다.

| | 후속 | 크기 | 권장 |
| --- | --- | --- | --- |
| g1 | 실제 구독 소량 실측: SNP 6장 전체(호출 3회). 구간 검토 호출의 시간과 응답 형식을 직접 잰다 | 작음, 사용자 실행 | **넣음.** 지금 §4.7의 호출당 시간은 ⑤ 칸 분석 값을 빌린 추정이다 |
| g2 | 지식그래프의 기기 설명·운전 조건을 요청 맥락에 넣기 | 중간, 요청 형식과 입력 지문이 바뀜 | **넣음.** INTENT §3.3 '도면 밖 자료를 묶어 활용'과 바로 이어진다 |
| g3 | '고쳐서 받기'에서 병합 대상·떼어 낼 구성요소 고치기 | 중간, ④ 화면 | **넣음.** 지금은 고쳐서 받아도 설계 의도만 고칠 수 있다 |
| g4 | 도면 위 제안 경계 점선 | 중간, `viewer.py`·웹뷰 JS | 뒤로. ④ 카드에서 나란히 보기가 이미 된다 |
| g5 | 제외 묶음의 조각(parts) 경계까지 보내기 | 작음 | 뒤로. 제외 묶음 질문은 '꺼낼 조각이 있는가'뿐이다 |

**설계가 먼저 필요한가.** 새 설계 문서는 필요 없다. 다만 g2는 세션 안에서 코드 전에 `architect`로 세 가지를 정한다.
- 맥락에 넣을 지식그래프 항목과 구간당 상한(글자 수, 항목 수).
- 입력 지문에 무엇을 넣을지. `kg_version`을 통째로 넣으면 지식그래프를 다시 지을 때 제안이 모두 '오래됨'이 된다. 권장은 '구간 구성요소에 닿는 지식 노드의 내용 해시만'이다.
- 근거 `evidence`가 지식 노드 ID를 가리켜도 되게 할지. 지금 검증은 구성요소 ID만 받는다.

정한 것은 `specs/study-node-segmentation.md` §4.7에 몇 줄로 더한다. g3은 이미 있는 `merge`·`split` 연산을 부르는 화면 일이라 설계가 따로 필요 없다.

**고정 응답 시험.** 지금 방식(가짜 클라이언트 + `tests/fake_claude`)을 그대로 넓힌다. 실제 구독 호출은 시험에 넣지 않는다.
1. 요청 고정본: SNP 표본 구간 하나에 지식 맥락을 붙인 요청 JSON을 `tests/fixtures/`에 두고 바이트로 비교한다. 순서·상한·잘라 내기가 결정적인지 본다.
2. 근거 검증: 지식 노드 ID를 근거로 든 응답은 받고, 없는 지식 ID를 든 응답은 버리고 이유를 남긴다.
3. 오래됨: 구간 밖 지식 노드만 바뀌면 제안이 살아 있고, 구간에 닿는 지식이 바뀌면 '오래됨'이 된다.
4. g3 화면: 오프스크린 Qt에서 '고쳐서 받기'로 병합 대상 하나를 빼고 받으면 `history`에 `ai_review_accept`(제안 ID, 고친 내용)가 남고, 결과가 같은 편집을 손으로 한 것과 같다.
5. CI: 러너에는 `claude` CLI가 없다. 이 시험들이 CLI를 찾지 않고 가짜만 쓰는지 확인한다.

g1 실측은 `specs/ai-subscription.md` §8.2 방식으로 사용자가 직접 소량 돌린다. 시간은 호출별 로그로 재고, 비용은 구독 사용률 계기로 재지 않는다(규칙 16). 결과는 §4.7 표 옆에 '구간 검토 실측 @커밋, 조건'으로 적는다.

**스킬.** `poteto-mode` + `tdd`, g2 앞에 `architect`. 검토 지적 재현에는 `interrogate`를 쓴다. 받아들이기가 `merge`·`split`과 `history`를 쓰는 저장·ID 경로라 규칙 3이 걸린다. g3 실제 창 확인은 `verify-hazop`를 `desktop_lease.py run` 안에서 쓴다. `arena`·`swarm`은 쓰지 않는다.

**세션.** 1개, D 뒤. E와는 나란히 돌려도 된다.

**완료 기준.**
1. 위 시험 1~5가 있고, 시험용 venv로 전체 시험이 통과한다.
2. `check_snp_baseline.py`(`--update` 없이)가 그대로다. G는 구간 제안을 바꾸지 않는다.
3. `check_user_scenarios.py` S9·S11이 잠금 안에서 통과한다.
4. g1 실측값이 출처와 함께 §4.7에 있다. 호출당 시간이 추정(중앙 31.7초)의 두 배를 넘으면 143쪽 호출 규모 표를 다시 계산해 적는다.
5. §4.7 '후속'에서 한 것은 지우고 안 한 것은 남는다.

**멈춤 기준.** 143쪽 전체 AI 구간 검토(약 320회, 7일 사용률 +4~9%p 추정)는 이 단위에서 돌리지 않는다. 돌리려면 사용자 결정을 받는다. g1에서 응답 형식 오류가 3회 중 1회라도 나오면 g2·g3로 가지 말고 요청 형식부터 보고한다.

**검토.** '대'(저장의 입력 지문과 ④ 화면이 바뀐다). hazop-reviewer와 Codex 병렬 1회. 자료는 SNP 가상 도면이라 Codex에 보내도 된다.

---

### 단위 F: 기호 사전 재개(F1)와 큰 도면 성능 마무리(F2)

F1과 F2는 파일도 성격도 달라 나눠서 돌린다.

#### F1 기호 사전·추출 (반복 개선 단위)

**시작 전에 정할 것.**
- INTENT §1의 지금 우선순위('쓸 수 있는 완성본과 패키징 먼저')와 부딪힌다. 2026-11-10에 APR1400 작업을 멈춘 것도 사용자 결정이었다(메모리 move-to-d-drive). '다 실행'이 이 재개까지 뜻하는지 아래 멈춤 기준과 함께 사용자 확인을 받는다(규칙 8·17).
- 메모리 repo-public-ok는 '모든 자료가 공개판'이다. 그래도 규칙 7에 따라 APR1400 그림을 Codex에 보낼 때는 그 확인을 작업지시서에 적어 둔다.

**하위 단위(모두 `pdf_vector.py`를 고치므로 순서대로).**

| 순서 | 하위 단위 | 근거 | 완료 기준 |
| --- | --- | --- | --- |
| F1-0 | `pdf_vector.py`(2,265줄) 나누기, 동작 그대로. 기호 묶기·라벨 고르기·연결 표시를 각각 모듈로 뺀다 | 규칙 4 '같은 파일 차례 조정이 두 번이면 나누는 단위를 먼저'. 이 파일은 하루에 1,466줄에서 2,265줄로 늘었고 11커밋이 들어갔다 | SNP 추출 JSON·`graph_version` 바이트 동일, APR1400 점수 동일, 기준값 손대지 않음 |
| F1-1 | S7 기존 규칙 이관(`_shape_kind`·`EQUIPMENT_WORDS` → `common/`·`SNP/` 사전) | 사전 기획 §7 | SNP 바이트 동일, 옛 분기 삭제 |
| F1-2 | D8 사전 판을 등록 기록의 실행 정보에 남김 | 사전 기획 D8 | 추출 JSON 바이트 동일(판은 등록 기록에만), 시험 |
| F1-3 | 작은 검은 채움 밸브를 몸통으로 읽기(검정 견본, NC). 견본을 모으는 도구 모드가 먼저다 | 미확인 문서 §3 다음 후보 1, 사전 §4.2 1번 | 아래 공통 |
| F1-4 | 신호선 외톨이 빗금과 안전밸브 스프링선 가르기 | 다음 후보 2(3f에서 되돌린 이력) | 아래 공통 + 안전밸브 표본 쪽 새로 틀린 노드 0 |
| F1-5 | 밸브 라벨 고르기(위치 약어보다 밸브 번호 우선) | 다음 후보 3 | 아래 공통 |
| F1-6 | §6 절차로 사전 항목 추가(묶기 → 이름 → 항목 → 검사) | 다음 후보 4 | 아래 공통 + `check_symbols.py` |

F1-0~F1-2는 점수를 바꾸지 않는 정리 단위다. 반복 개선은 F1-3부터 센다.

**F1-3~F1-6 공통 완료 기준.**
- `check_apr1400.py`(`--update` 없이)의 톱니 검사가 통과한다. HIGHER(`tag_exact`, `connectors_detected`, `paired`, `pair_key_hit`)는 내려가지 않고, LOWER(`tag_not_in_text`, `connector_bad_target`, `pair_key_wrong`)와 `failed_pages`는 늘지 않는다. 쪽별 검사도 같다.
- `check_snp_baseline.py`가 그대로이고, SNP 추출 JSON과 `graph_version`이 바이트로 같다.
- 사람 수정 기록 적용 수가 줄지 않는다(D14).
- 미확인 수를 사유별로 '시작 → 끝 @커밋'으로 보고한다.

**세션.** 자기 작업트리에서 하위 단위마다 세션 1개를 순서대로 띄운다. 한 세션에 몰면 143쪽 실행 출력이 쌓여 뒤 단위의 맥락이 나빠진다. F1-1과 F1-2는 작아서 한 세션에 묶어도 된다. 하위 세션은 푸시하지 않고, 브랜치 합치기와 푸시는 총괄이 한다.

**스킬.**

| 단계 | 스킬 | 이유 |
| --- | --- | --- |
| 모든 하위 단위 | `poteto-mode` + `tdd` | 정답지(`tests/fixtures/apr1400/answer_key/`)의 노드별 기대를 먼저 시험으로 둔다 |
| F1-0 | `blast-radius` | 모듈을 나누면 import 경로가 바뀌어 `scripts/`·`packaging/verify_bundle.py`·시험이 걸린다. 호출자를 먼저 센다 |
| F1-3·F1-4 규칙 후보 비교 | (스킬 없이) 측정 스크립트에 후보를 나란히 돌림 | 구간 분할 §3에서 쓴 방식이다. `arena`보다 싸고 같은 표로 비교된다 |
| 숫자 보고 | `show-me-your-work` | 점수·미확인 수마다 실행 커밋과 조건을 붙인다(규칙 16) |
| 검토 지적 재현 | `interrogate` | HEAD에서 만든 분리 작업트리(`HAZOP-trials\adv*`)에서 패치를 따로 적용해 재현한다 |
| 생략 | `swarm`, `arena`, `architect` | 한 파일을 순서대로 고친다. 형식 결정은 사전 기획에서 이미 끝났다 |

**기준값 갱신 절차(규칙 12, 이 단위의 주인만).**
1. 시작할 때 자기 작업트리에서 `scripts/preflight.py`를 돌리고, `check_apr1400.py`와 `check_snp_baseline.py`를 `--update` 없이 돌려 출발점을 다시 잰다. 지금 손에 있는 872/1619·286/295·6/6 @d74c0aa는 다른 세션(naming-migrate)이 잰 값이다. 다시 잰 값과 다르면 둘 다 적는다(규칙 16).
2. 점수가 좋아지는 변경:
   - 코드를 경로 지정으로 먼저 커밋한다.
   - 깨끗한 트리에서 `--update`를 돌린다.
   - `tests/baselines/apr1400_score.json`만 따로 커밋한다. 메시지는 `test(apr1400): 기준값 갱신 — tag_exact 872→N/1619 @<코드 커밋>` 꼴이다.
3. 점수가 의도대로 내려가거나 분모가 바뀌는 변경(정답지 수정, 채점기 수정, 잘못 맞던 것을 미확인으로 돌림):
   - HEAD에서 분리 작업트리를 만들고 그 변경만 적용한다.
   - `--update --force`로 매긴다.
   - 코드와 기준값을 한 커밋에 넣고 이유를 메시지에 쓴다.
   - 분모가 바뀌면 보고에 '옛 분모 → 새 분모, 이유'를 적는다. `--force`는 이 경우에만 쓴다.
4. `tests/baselines/snp_baseline.json`은 이 단위에서 바뀌면 안 된다. 바뀌어야 통과한다면 멈춤 기준에 걸린 것이다.
5. 정답지(`tests/fixtures/apr1400/`)를 고치는 커밋은 코드 커밋과 나누고 검토자에게 따로 보인다.

**멈춤 기준(규칙 17, 시작할 때 사용자 확인).** 셀 것은 미확인 총수(출발 63,723 @S5 뒤, 다시 잰 값으로 바꿈), HIGHER·LOWER 지표, SNP 바이트, 수정 기록 적용 수다.
- **곧바로 멈추고 되돌린 뒤 보고:**
  - `pair_key_wrong`이나 `connector_bad_target`이 1이라도 는다(틀린 짝).
  - SNP 추출 바이트나 `graph_version`이 바뀐다.
  - 수정 기록 적용 수가 준다.
  - 통과하려면 `--force`가 필요한데 '의도된 하락'이라는 이유를 댈 수 없다.
- **수확 체감:** 하위 단위 하나가 미확인을 1%(약 640개) 미만으로 줄이고 HIGHER 지표도 하나 올리지 못하면 '효과 작음'으로 센다. 두 번 연달아 효과가 작으면 F1-3~F1-6 반복을 멈추고 보고한다.
- **상한:** F1-6을 넘는 새 하위 단위는 사용자 결정 없이 시작하지 않는다. 지난번 미확인 문서에 남은 '−1.8%… 총괄 지시로 진행' 같은 넘김은 하지 않는다.
- **환경:** 디스크 여유가 10GB 미만이면 시작하지 않는다(`HAZOP_MIN_FREE_GB`). 다른 세션이 시간을 재는 중이면 143쪽 전체 실행을 미룬다.

**검토.** F1-0~F1-2는 hazop-reviewer 1회(동작 그대로이고 바이트 비교가 증거다). F1-3~F1-6은 '대'다. 추출 판정이 바뀌므로 hazop-reviewer와 Codex 병렬 1회, 지적은 `interrogate`로 분리 작업트리에서 재현한다. 틀린 판정은 차단 결함이다(사전 기획 D7).

#### F2 큰 도면 성능 마무리

**스킬.** `poteto-mode`, `benchmark-checklist`(측정 조건·반복·중앙값·부하를 적는 틀). gc 후속은 `tdd`로 오래 켜 둔 앱의 회수 시험을 먼저 만든다. `arena`는 쓰지 않는다.

**세션.** 1개, D 뒤(`project_ctx.py`). 측정은 다른 세션이 하나도 돌지 않을 때만 한다.

**하는 일.**
1. 143쪽 APR1400에서 D7 목표를 재측정한다. offscreen, 5회 중앙값, 부하 없는 기계. 목표는 화면 전환 1초 이하, 처음 들어갈 때 3초 이하, 시작 3초 이하다.
2. 목표를 넘는 화면만 손본다. §5.7의 gc 후속(도면·프로젝트를 바꿀 때 `unfreeze → collect → freeze`, 또는 임계값 조정)은 반복 재추출·UI 폐기 회수 시험이 먼저 있어야 넣는다. Codex가 재현한 '얼린 순환 참조가 회수되지 않음'이 그 시험에서 나오지 않아야 한다.

**완료 기준.** 측정표가 '값 @커밋, 조건(부하, 회수)'으로 §5 새 절에 들어간다. 목표를 넘는 항목은 원인과 함께 남는다. 전체 시험과 `tests/test_app.py`가 통과한다.

**멈춤 기준.** 부하 없는 기계에서 목표를 모두 채우면 고치지 않고 측정만 남기고 끝낸다. gc 후속이 회수 시험을 통과하지 못하면 넣지 않고 기록만 남긴다(§5.7에서 freeze를 뺀 것과 같은 판단).

**검토.** hazop-reviewer 1회. gc 수명 관리를 넣을 때만 Codex를 더한다. 오래 켜진 앱의 메모리 문제는 Claude 측 검토만으로는 놓친 이력이 있다.

---

### 세 단위의 위험 요약

- **G를 새 기능으로 착각하고 다시 만드는 것.** 작업지시서에 S6a·S6b 커밋과 `node_review.py`를 적고 '후속만'이라고 박아 둔다.
- **F1이 같은 체크아웃에서 돌아 기준값 잠금에 걸리거나 남의 수정으로 점수를 매기는 것.** 자기 작업트리가 필수다.
- **F1이 끝없이 이어지는 것.** 지난번에 실제로 그랬다. 멈춤 기준을 시작할 때 사용자에게 받고, 걸리면 멈춘다.
- **DOC가 N4보다 먼저 가는 것.** 같은 두 파일의 경로 줄이 부딪힌다.
- **`records/*.md` 동시 쓰기.** 세 단위가 모두 결정로그와 남은작업을 고친다. hazop-recorder가 단위가 끝난 순서대로 한 번씩 쓴다(교훈 20).

---

## 모델 추천: F1b·F2 (2026-11-11 추가)

기준: `feat/next-units` @ 146223b. F1-0(ddb4c46), F1-1(16c3536), F1-2(c934ceb)는 이미 커밋됐다. 두 세션은 준비돼 있고 지금은 총괄 모델(Fable 5.2)을 물려받고 있다.

### F1b: APR1400 미확인 줄이기 F1-3~F1-6

하위 단위마다 성격이 달라서 모델도 단위마다 바꾸기를 권한다. 준비된 세션은 F1-3에 그대로 쓰고, 그 뒤 단위는 앞 절의 권고대로 세션을 새로 띄우면서 모델을 정한다. 한 세션으로 이어 가겠다면 단위가 바뀔 때 세션 모델을 바꾼다.

| 하위 단위 | 모델·강도 | 이유 |
| --- | --- | --- |
| F1-3 작은 검은 채움 밸브를 몸통으로(검정 견본, NC) | Fable 5.2 · high | 견본을 모으는 도구 모드를 새로 만들고, 표식과 밸브 몸통을 가르는 규칙을 정한다. 잘못 읽으면 열린 배관이 닫힌 밸브가 되거나 그 반대가 된다. 정상 위치가 바뀌면 HAZOP 원인이 바뀌므로 판정 경로다 |
| F1-4 신호선 외톨이 빗금과 안전밸브 스프링선 가르기 | Fable 5.2 · xhigh | 3f에서 같은 시도를 안전밸브 스프링선을 지운 탓에 되돌렸다. 실패 이력이 있는 문제라서 강도를 가장 높게 둔다. 총괄 강도가 xhigh보다 낮으면 high로 둔다 |
| F1-5 밸브 라벨 고르기(위치 약어보다 밸브 번호 우선) | Opus 5.5 · high | 라벨 고르기 한 곳만 바꾸는 국소 규칙이다. `tag_exact`·`tag_not_in_text` 톱니가 바로 잡는다. 다만 틀린 태그도 틀린 판정이라 강도는 높게 둔다 |
| F1-6 §6 절차로 사전 항목 추가 | Opus 5.5 · medium | 묶기 → 이름 → 항목 → 검사 절차가 정해져 있다. `check_symbols.py`와 정답지 톱니가 안전망이다. 이름은 후보로만 두고 사람이 확정한다(D10) |

- 세션 안의 검토자: `interrogate` 검토자는 `pstack-models.md` 그대로 둔다(`opus high`와 부모 모델). F1-5·F1-6 세션을 Opus 5.5로 띄우면 검토자가 모두 Opus가 되어 시각이 덜 갈린다. 그래도 바깥 검토에 Codex가 있으니 따로 올리지 않는다.
- 바깥 검토: 하위 단위마다 hazop-reviewer(Opus 5.5 · high)와 Codex 병렬 1회. 지적 판정은 총괄이 한다.
- 멈춤 기준을 검사할 때(수확 체감 두 번, 틀린 짝 1개)는 모델과 상관없이 세션이 멈추고 보고한다. 멈춤 판단을 모델 강도로 대신하지 않는다.

### F2: 143쪽 성능 재측정과 gc 후속

두 단계로 나누고 모델을 바꾼다.

| 단계 | 모델·강도 | 이유 |
| --- | --- | --- |
| F2a 재측정(offscreen, 5회 중앙값, 부하 없는 기계, `benchmark-checklist`) | Sonnet 5.5 · medium | 정해진 명령과 조건으로 표를 채우는 일이다. 목표를 모두 채우면 여기서 끝난다(멈춤 기준) |
| F2b 목표를 넘을 때만: 원인 찾기와 gc 수명 관리(회수 시험 먼저) | Fable 5.2 · high | §5.7에서 `gc.freeze`가 Qt 래퍼를 얼려 순환 참조를 회수하지 못하는 문제를 Codex가 재현해 뺐다. 오래 켜 둔 앱에서만 드러나는 문제라 놓치기 쉽다. 수명 관리 지점이 도면·프로젝트를 바꾸는 저장 흐름 옆에 있다 |

- 준비된 F2 세션이 Fable 5.2를 물려받았다면, F2a를 시작하기 전에 Sonnet 5.5 · medium으로 바꾼다. F2b로 넘어가면 다시 올린다. 총괄이 이렇게 번갈아 바꾸기 번거롭다고 보면, 처음부터 Opus 5.5 · medium 하나로 F2a를 하고 F2b는 새 세션(Fable 5.2 · high)으로 띄운다.
- 검토: F2a는 측정 기록뿐이라 hazop-reviewer 1회. F2b는 gc를 넣을 때만 Codex를 더한다(앞 절과 같음).
