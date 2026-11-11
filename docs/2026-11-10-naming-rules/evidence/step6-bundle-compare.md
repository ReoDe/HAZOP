# 단계 6 전후 대조: 배포본 묶음과 그 밖의 값

- 작성 2026-11-11, 단위 NAMING N4b. '전'은 `d86bd89`, '후'는 `51104e5`. 둘 다 작업트리가 깨끗한 상태에서 뽑았다.
- 뽑은 파일은 저장소 밖 `D:\HAZOP-trials\2026-11-10-naming-n4\n4b\`에 있다(`keep_until: 2026-11-25`). 아래 명령은 저장소 루트에서 시험용 venv로 돌렸다.

## 1. 배포본 묶음

| 무엇 | 전(`d86bd89`) | 후(`51104e5`) |
| --- | --- | --- |
| `scripts/build_package.py --with-check --build` | rc=0 | rc=0 |
| `packaging/verify_bundle.py` | 이번에 다시 돌리지 않았다(N4a가 `a810b99`에서 rc=0) | rc=0, 묶음 576.7 MB, 파일 2641개 |
| 묶음 파일 수 | 2641 | 2641 |

묶음 목록(경로·크기·SHA-256)을 `list_bundle.py`로 뽑아 `compare_bundle6.py`로 견줬다.

| 구분 | 수 | 내용 |
| --- | --- | --- |
| 경로와 내용이 같음 | 2635 | |
| 전에만 있음 | 0 | |
| 후에만 있음 | 0 | |
| 내용이 바뀜 | 6 | 아래 둘로 모두 설명된다 |
| 빌드할 때마다 달라지는 것 | 3 | `HAZOP.exe`, `HAZOP-check.exe`, `_internal/base_library.zip`(단계 5에서 같은 커밋을 두 번 빌드해 확인한 흔들림) |
| 기준 커밋 뒤 git에서 바뀐 파일 | 3 | `_internal/scripts/build_graph.py`, `extract_drawio.py`, `extract_pdf.py`(앱이 이름으로 불러오는 스크립트. 열쇠 이름과 `plain_rel`로 바뀌었다) |
| 설명되지 않는 것 | 0 | |

묶음에는 작업 루트가 들어가지 않으므로 경로가 바뀐 파일은 없다. `hazop/` 패키지는 실행 파일 안에 들어 있어 실행 파일의 차이로만 보인다.

`a810b99`의 목록(N4a의 `before.csv`)과 `d86bd89`의 목록은 실행 파일 둘과 `base_library.zip`만 달랐다.

## 2. 그래프 판과 기준값

| 무엇 | 결과 |
| --- | --- |
| 샘플 6장 그래프 판 12개(drawio 6, PDF 6), `source.file`·`svg_file`, `graph.json` SHA-256, 고정 응답 `bundle_sha256` 25개 | `pins-before.txt`(`a810b99`)와 `pins-after.txt`(`51104e5`)가 58줄 모두 같다(`diff` rc=0) |
| `scripts/refresh_fixture_hashes.py --check` | 모두 '최신', rc=0 |
| `scripts/check_snp_baseline.py` | `SNP: 후퇴 0 · 나아짐 6 · drawio 짝 12 · 방향 모순 0 · 도면 drawio 6 · pdf 6`, rc=0. 출력이 전과 한 줄도 다르지 않다 |
| `scripts/check_apr1400.py`(`--update` 없이) | `태그 정확 872/1619(원) · 텍스트 층에 없는 태그 47 · 연결 표기 검출 286/295 · 없는 대상 0 · 짝 279(정답 짝 6/6 · 틀린 짝 0 · 후보 10) · 미확인 63723`, rc=0. 출력이 전과 같고, 도면별 CSV는 걸린 시간 열(`seconds`)만 다르다 |
| 고정값(`graph_version`, `bundle_sha256`, `PINNED_SHA256`, `GUIDE_SHA256`), `tests/baselines/`, `resources/` | `git diff --stat d86bd89 51104e5 -- tests/baselines hazop/analysis/integrity.py resources tests/fixtures`가 비어 있다 |
| 등록한 자료를 옮긴 뒤 다시 추출 | 0.1.x 코드(`d86bd89`)로 만든 작업 루트를 옮긴 사본에서 `extract_drawio.py --registration`과 `build_graph.py`를 다시 돌렸다. 판 `v-0c3f7251efc9` 그대로이고 `graph.json`이 바이트까지 같다 |

## 3. 작업 루트 사본으로 한 재현

`scripts/migrate_names.py --work-root <사본> --apply` → `scripts/check_work_root_counts.py --compare` → `--apply` 한 번 더 → `--undo` → 폴더 해시 대조 순서로 했다. 폴더 해시는 (상대 경로, SHA-256) 목록 전체의 해시다(`tree_hash.py`).

| 사본 | 옮긴 뒤 화면이 보는 수 | 기록 경로 | 되돌린 뒤 |
| --- | --- | --- | --- |
| 개발 작업 루트(`work-before`, 파일 675개) | 기준 수(`step6-counts-before.json`의 `dev_work_root`)와 같음 | 348건 중 풀림 336, 안 풀림 12(원래 있던 12건 그대로) | 원래 사본과 해시가 같음 |
| 이 PC 배포본 작업 루트(`localappdata-before`, 14개) | 기준 수(`localappdata`)와 같음 | 3건 모두 풀림 | 같음 |
| 보강 자료(`rich-before`, 123개): 등록 자료 1, 검토 기록 1, 확정한 검토구간 1, ⑤ 결과 1, 초기사건 그룹 3·후보 7 | `d86bd89` 코드로 센 수와 같음 | 47건 모두 풀림 | 같음 |

- 보강 자료는 `d86bd89` 코드로 만들었다(`make_rich_root.py`, 폴더 이름을 바꾸기 전). 얇던 두 사본에 없던 검토 기록·확정본·⑤ 결과·⑥ 그룹이 들어 있다.
- 한글 열쇠로 적힌 이전 결과(`counts-rich-before-oldkeys.json`)와 견줘도 '같음'이다.
- 기준 수 파일은 `files`의 열쇠만 영어로 옮겼다. 수는 바꾸지 않았다(바뀐 66줄에서 뺀 값과 더한 값의 묶음이 같다).
- 같은 내용을 화면 모델 수준에서 보는 시험이 `tests/test_workroot_app.py`의 `MovedRootIsReadByTheAppTest`다.

## 4. 실제 창과 그 밖의 검사

| 무엇 | 결과 |
| --- | --- |
| S1~S6(`desktop_lease.py run --purpose naming-n4b -- check_user_scenarios.py --only S1,…,S6`) | 여섯 시나리오 통과, rc=0. 한 번에 통과했다 |
| `check_desktop_support.py`(데스크톱 잠금 안) | 통과, rc=0 |
| CI에 없는 검사: `check_analysis`, `check_expect`, `check_kg`, `check_kg_algo`, `check_contract`, `check_project_kg`, `check_kg_screen --skip-tests` | 모두 rc=0(옮긴 개발 작업 루트 `work/`에서) |
| `evidence/step5-records-body-compare.py D:/HAZOP --base d86bd89` | 결정로그 254줄, 남은작업 367줄, 다른 줄 0 |
| `scripts/run_ci.py` | 시험 1943개, 실패 0, 오류 0, 건너뜀 20. 검사 10개 rc=0 |

돌려 보지 않은 것: `check_design.py`, `check_edit_screen.py`, `check_app.py`, `shoot_*.py`, Linux에서의 실행.
