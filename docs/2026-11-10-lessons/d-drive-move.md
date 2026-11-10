# D 드라이브 이전 점검표

작성 2026-11-10. 이 문서는 이전 전에 정리할 것, 함께 옮길 것, 옮긴 뒤 고칠 곳을 적는다. 실제 이전은 하지 않았다. 지우는 일은 모두 사용자 확인을 받은 뒤에 한다.

조사 시점 상태: C 드라이브 465GB 중 남은 공간 11GB, D 드라이브 1.9TB 중 거의 전부 비어 있음. `feat/next-units`는 origin보다 60커밋 앞서 있고 푸시하지 않았다.

## 1. 옮기기 전에

| 할 일 | 이유 | 명령 |
| --- | --- | --- |
| 커밋 묶음 백업 | 60커밋이 이 컴퓨터에만 있다. 옮기다 잘못되면 되살릴 곳이 없다 | `git bundle create D:\HAZOP-backup\feat-next-units.bundle --all` |
| 작업트리 9개 정리 | 작업트리는 `.git` 위치를 절대 경로로 적는다. 저장소를 옮기면 링크가 끊긴다 | `git worktree list`로 확인한 뒤, 남길 것이 없으면 `git worktree remove <경로>`, 남은 찌꺼기는 `git worktree prune` |
| 시험 폴더 분류 | `C:\Users\kim92\HAZOP-trials` 약 15GB. 대부분 다시 만들 수 있다 | 아래 표 |
| 임시 폴더 정리 | `%TEMP%`의 `hazop-*`·`hazop_*` 약 3,000개(2.2GB), `unk-*` 빈 폴더 약 2,100개 | `<venv python> scripts/preflight.py --clean-temp` (2시간 넘은 것만 지움). `unk-*`는 탐색기에서 지운다 |
| 오래된 venv | `%LOCALAPPDATA%\HAZOP\venv-py312`는 pdfplumber가 없는 옛 W2 venv다. 거짓 실패의 원인이었다 | 사용자 확인 뒤 지운다 |

`HAZOP-trials` 하위 폴더(조사 시점 크기):

| 폴더 | 크기 | 판단 |
| --- | --- | --- |
| `apr1400-2026-11-09` | 4.9GB | `work/출력/그래프`(4.1GB)는 다시 만들 수 있다. 쪽별 점수 CSV와 메모만 남기면 된다 |
| `ie-20261109` | 4.6GB | 구독 분석 약 1,690회 호출의 결과다. 다시 만들려면 사용량이 든다. 결과 파일은 D로 옮긴다 |
| `symbols-impl` | 2.3GB | 기호 사전 작업용 사본. 커밋으로 반영됐으면 지워도 된다 |
| `node-seg-20261109` | 2.1GB | 구간 분할 시험. `apr-u1`(1.4GB)은 다시 만들 수 있다 |
| `apr1400-final-2026-11-10` | 0.4GB | 마지막 측정(3ca0bba). 메모·CSV를 남긴다 |
| `u5-20261109`, `manual-1802` | 각 0.3GB | U5 실측과 수동 확인 기록. 메모를 남긴다 |
| `wt-*` 5개 | 각 약 40MB | 분리 작업트리. 위 작업트리 정리로 함께 없앤다 |

## 2. 함께 옮길 것 (git이 추적하지 않음)

`git clone`으로는 아래가 따라오지 않는다. 저장소 폴더를 통째로 복사한다.

- `자원/참고자료/APR1400_DCD/`(약 411MB, `원본/`과 `도면별/`, `계통약어.csv` 포함). `check_apr1400.py`는 이제 `계통약어.csv`가 없으면 멈춘다
- `작업/`(개발 작업 루트, 약 110MB)
- `.claude/`(에이전트·스킬은 추적됨. `worktrees/`는 위에서 정리)

## 3. 이 컴퓨터에 박힌 경로

### 동작에 영향 있음 (옮긴 뒤 확인)

| 위치 | 경로 | 조치 |
| --- | --- | --- |
| `scripts/build_package.py` `VENV_DIR`, `tests/test_raster.py` `BUILD_VENV`, `scripts/devenv.py` | `~/.hazop/venv-py312` | venv를 그대로 두면 고칠 것 없다. D로 옮기면 환경변수 `HAZOP_VENV`를 새 경로로 둔다(이번에 세 곳 모두 이 변수를 읽게 바꿨다) |
| `packaging/netwatch.ps1:3,12` | `*\.hazop\venv-py312\*` | venv를 옮기면 `-PathLike`로 새 경로를 넘긴다 |
| `packaging/README.md:37-55`, `packaging/requirements-raster.txt:2` | `%USERPROFILE%\.hazop\venv-py312`, `venv-raster-py312` | venv를 옮기면 문서를 고친다 |
| `.claude/skills/verify-hazop/SKILL.md` Launch | `%USERPROFILE%\.hazop\venv-py312\Scripts\python.exe` | 같음 |
| `CLAUDE.md` 규칙 11, `.claude/agents/hazop-developer.md`·`hazop-qa.md`·`hazop-reviewer.md` | 같은 venv 경로 | 같음 |
| `design/mockups/ai-connection/build.py:520`, `design/mockups/uiux-detail/build.py:430` | Chrome 설치 경로, `~/AppData/Local/Temp/hazop-uiux-shoot-profile` | 시안 촬영용. 이전과 관계없다 |
| `hazop/study/claude_cli.py:92` | `~/.local/bin/claude.exe` | 홈 기준이라 그대로 동작 |
| `hazop/paths.py` | 개발 작업 루트 `<저장소>/작업`, 배포본 `%LOCALAPPDATA%\HAZOP`, 설정 `%APPDATA%\HAZOP\settings.json` | 저장소 기준·사용자 폴더 기준이라 그대로 동작 |

이번에 고친 곳: `tests/test_ie_bundle.py`의 예시 Excel 기본값(세션 임시 폴더 경로였음 → 비워 두고 `HAZOP_IE_EXAMPLE_XLSX`로만 받음), `scripts/bench_results_screen.py` 사용법의 시험 폴더 경로. 재발은 `tests/test_machine_paths.py`가 막는다(추적 파일에 사용자 폴더·`HAZOP-trials`·Claude 임시 폴더 경로가 있으면 실패).

### 문서에만 있음 (급하지 않음)

- `specs/ai-subscription.md:116`(`claude.exe` 경로 예)
- `specs/pid-symbol-dictionary.md:207`, `specs/study-node-segmentation.md:6`, `docs/2026-11-09-symbol-library/README.md:64`(`HAZOP-trials` 경로)
- `specs/ie-output-design.md:173`(세션 임시 폴더 경로)
- `docs/2026-11-05-input-adapter/evidence/w1-survey.md:25`, `docs/2026-11-05-packaging/evidence/w2-venv.md:21`, `w6-bundle-collect-list.md:24-68`, `docs/2026-11-09-data-consolidation/inventory/references.csv:233-235`: 당시 증거 기록이라 고치지 않는다

### 저장소 밖

- Claude Code 프로젝트 메모리는 프로젝트 경로로 폴더 이름을 정한다. 지금은 `%USERPROFILE%\.claude\projects\C--Users-kim92-HAZOP\memory\`다. D로 옮기면 새 폴더(예: `D--HAZOP`)가 생기므로 `memory\` 안의 파일을 그대로 복사한다. 대화 원문(`*.jsonl`)은 옮기지 않아도 된다
- `.claude/worktrees/agent-*/.redteam/*.py`는 `C:/Users/kim92/HAZOP`를 박아 둔 추적 안 한 파일이다. 작업트리와 함께 지운다
- 사용자 전역 `~/.claude/settings.json`의 훅 경로는 사용자 폴더 기준이라 영향 없다

## 4. 옮긴 뒤

1. D의 저장소에서 `git status`, `git log -1`, `git remote -v`(`https://github.com/ReoDe/HAZOP.git`)를 확인한다. `gh auth status`로 GitHub 인증을 확인한다.
2. 작업트리를 남겨 옮겼다면 `git worktree repair`를 돌린다.
3. 메모리 폴더를 새 키로 복사하고, `move-to-d-drive.md`의 상태를 갱신한다.
4. `PYTHONIOENCODING=utf-8 <venv python> scripts/preflight.py`로 인터프리터·패키지·디스크를 확인한다.
5. 전체 시험: `PYTHONIOENCODING=utf-8 <venv python> -m unittest discover -s tests -t .`
6. 기준값 확인: `<venv python> scripts/check_snp_baseline.py`, `<venv python> scripts/check_apr1400.py`(후퇴 0이어야 한다).
7. 시험 폴더는 `D:\HAZOP-trials`처럼 저장소 밖에 두고, 폴더마다 주인·목적을 적은 `README.md`를 둔다(CLAUDE.md 규칙 14).
8. 푸시와 PR은 사용자가 하라고 할 때 한다.
