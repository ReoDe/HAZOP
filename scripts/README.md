# scripts — 실행 명령

사람이나 CI가 직접 돌리는 명령(검사, 빌드, 추출, 이전)을 둔다. 앱이 이름으로 불러오는 파일도 있어 이름을 바꾸지 않는다.

## 무엇을 넣는가

- `check_*.py`: 합격·불합격 검사(종료 코드 0이 합격)
- `build_*.py`, `extract_*.py`, `export_*.py`, `shoot_*.py`, `run_*.py`, `analyze_*.py`, `seed_*.py`, `clean_*.py` 같은 명령
- `migrate_*.py`: 한 번 쓰는 이전 도구
- 동사 없는 도구 7개(`devenv`, `preflight`, `desktop_lease`, `codemod_data_paths`, `unknowns_breakdown`, `apr1400_key_overlay`, `degrade_raster`)

## 넣지 않는 것

- 앱 코드는 `hazop/`에 둔다.
- 단위 시험은 `tests/`에 둔다.
- 배포본 검사는 `packaging/`에 둔다.

## 이름 형식

`<동사>_<대상>.py`. 동사는 HZ-GOV-02 §4.4 목록(`check`, `build`, `extract`, `export`, `shoot`, `run`, `analyze`, `migrate`, `seed`, `register`, `clean`, `query`, `link`, `compare`, `bench`, `refresh`, `inventory`). 검사는 `tests/test_naming_rules.py` N4가 한다.

## 주인

구현 담당(`hazop-developer`)이 고치고, 검토 담당(`hazop-reviewer`)의 검토와 시험·검사 통과를 거쳐 총괄이 커밋한다. 회귀 기준값을 바꾸는 `--update`는 그 단위의 주인만 쓴다(`CLAUDE.md` 규칙 12).

## 폐기 기준

한 번 쓰는 이전 도구는 이전이 끝나도 지우지 않고 파일 머리에 끝난 날을 적는다. 쓰지 않는 명령은 그것을 부르는 문서와 시험을 옮긴 뒤 지운다.
