# pstack 활용 자문: D 드라이브 이전 뒤 단위 A~E

작성 2026-11-10, pstack 자문 세션(읽기 전용). 기준 커밋 `feat/next-units` @ 5f4e6c3. 근거로 읽은 것은 `CLAUDE.md`, `INTENT.md`, `메모리/남은작업.md`, `docs/2026-11-10-lessons/README.md`, `docs/2026-11-10-lessons/D드라이브-이전.md`, `~/.claude/rules/pstack-models.md`, pstack 0.15.36 스킬 설명, 그리고 단위 A의 대상 코드다.

## 공통 사항

- 하위 세션은 모두 `/pstack:poteto-mode`로 시작한다. 시작하면 바로 `PYTHONIOENCODING=utf-8 "%USERPROFILE%\.hazop\venv-py312\Scripts\python.exe" scripts/preflight.py`를 한 번 돌린다(규칙 11).
- 시험 명령의 기본형은 아래와 같다. 아래에서 `<py>`는 이 인터프리터 경로를 뜻한다.
  - 전체 시험: `PYTHONIOENCODING=utf-8 <py> -m unittest discover -s tests -t .`
  - 기준값 확인: `<py> scripts/check_snp_baseline.py`. `check_apr1400.py`는 APR1400 작업이 멈춰 있으므로 **기준값 갱신은 하지 않고**, 점수에 닿는 코드(`hazop/extract/*`)를 건드린 단위에서만 확인용으로 돌린다. 디스크 여유가 10GB 미만이면 시작하지 않는다(규칙 14).
- 모델은 `pstack-models.md`를 따른다. 구현 세션은 부모 모델을 쓰고(`feature/bug-fix: inherit-parent`), `interrogate`·`arena`를 쓰면 검토자·주자는 `opus high`와 부모 모델을 섞는다. 예산은 medium이다.
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
| `메모리/*.md` | 총괄(hazop-recorder)만 | | | | |

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

- **E1 품질 경고 3종.** 보호설비 고장이 원인 칸에 있음, 구간 경계 결과 끊김, 전기·제어 구간인데 FMEA 없음. 설계서(`기획서/초기사건-출력설계.md` 시트 8)에 정의가 있어 바로 구현할 수 있다. 다만 'FMEA 없음' 경고는 FMEA 입력(P5의 D5)이 없으면 항상 뜬다. E2보다 먼저 넣을지, 문구를 'FMEA 입력 기능 없음'으로 둘지 총괄이 정한다.
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
