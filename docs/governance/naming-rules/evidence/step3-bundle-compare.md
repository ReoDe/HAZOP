# 단계 3 전후 대조: 배포본 묶음, 지침서 카탈로그, 시안 그림, 결정로그

이름 이전 단계 3(사람 문서 폴더)을 옮기기 전과 옮긴 뒤에 같은 방법으로 뽑아 맞대어 본 결과다. 2026-11-10, 단위 NAMING N2 하위 세션. 출력은 모두 저장소 밖 `D:\HAZOP-trials\2026-11-10-naming-n2\`에 있다(`keep_until: 2026-11-24`).

- 전: 커밋 `f6fc34a`(지침서 위치를 `paths.FILES`로 모은 직후)의 작업트리. 빌드하는 동안 다른 세션의 커밋 `b5ab66b`(`tests/test_viewer_edit.py` 3줄)가 들어왔다. 시험 파일은 묶음에 들어가지 않는다.
- 후: `git mv` 커밋 `3445500` 위에 링크·코드·머리 수정을 얹은 작업트리(다음 커밋의 내용).

## 1. 배포본 묶음

빌드와 검증은 전후 모두 같은 명령이다.

```
<venv python> scripts/build_package.py --out <시험 폴더>/build-<before|after> --with-check --build
<venv python> packaging/verify_bundle.py --dist <…>/dist/HAZOP-verify --target-base <시험 폴더>/vt --out <시험 폴더>/verify-<before|after>
```

| 무엇 | 전 | 후 |
| --- | --- | --- |
| 빌드 종료 코드 | 0 | 0 |
| `verify_bundle.py` 종료 코드 | 0 (묶음 576.7 MB, 파일 2641개, 오류 없음) | 0 (묶음 576.7 MB, 파일 2641개, 오류 없음) |
| 묶음 파일 수(`list_bundle.py`가 `dist/HAZOP-verify`를 훑어 센 수) | 2641 | 2641 |

파일별 SHA-256 목록(`before.csv`, `after.csv`)을 대응표 stage 3으로 맞대었다(`compare_bundle.py`).

| 구분 | 수 | 파일 |
| --- | --- | --- |
| 경로와 내용이 같음 | 2637 | |
| 대응표대로 옮겨지고 내용도 바뀜 | 1 | `_internal/기획서/HAZOP기법지침.md` → `_internal/specs/hazop-method-guide.md` |
| 경로는 같고 바이트가 다름 | 3 | `HAZOP.exe`, `HAZOP-check.exe`, `_internal/base_library.zip` |
| 빠진 파일 | 0 | |
| 새로 생긴 파일 | 0 | |

바이트가 다른 세 파일은 속을 풀어 다시 대조했다(`compare_exe_parts.py`).

| 파일 | 속 | 결과 |
| --- | --- | --- |
| `HAZOP.exe` | 묶음 항목 15개 | 다른 항목은 `PYZ.pyz` 하나 |
| `HAZOP-check.exe` | 묶음 항목 13개 | 다른 항목은 `PYZ.pyz` 하나 |
| `PYZ-00.pyz`(앱) | 모듈 1021개, 전후 이름 같음 | 코드가 다른 모듈 2개: `hazop.paths`, `hazop.analysis.integrity` |
| `PYZ-01.pyz`(검증 실행 파일) | 모듈 1027개, 전후 이름 같음 | 코드가 다른 모듈 2개: 위와 같음 |
| `_internal/base_library.zip` | 항목 155개 | 내용(CRC)이 다른 항목 0, 이름이 다른 항목 0, 시각이 다른 항목 0 |

- 두 모듈은 이번 단계가 고친 곳이다. `hazop/paths.py`는 지침서 위치 한 줄, `hazop/analysis/integrity.py`는 `GUIDE_SHA256`과 설명글 두 줄이다.
- `base_library.zip`은 안에 든 파일이 모두 같다. 압축 파일을 다시 만들면서 바이트 배치만 달라진 것으로 본다(추정. 같은 소스를 두 번 빌드해 견주어 보지는 않았다).
- 그래서 내용이 바뀐 자료 파일은 지침서 하나이고, 실행 파일의 차이는 지침서 위치와 해시를 적은 코드 두 모듈뿐이다. 대응표 밖의 차이는 없다.

묶인 실행 파일이 새 위치의 지침서를 읽는지는 `verify_bundle.py`의 `w4_flow.py` 단계가 본다. 묶음 안 지침서의 해시가 빌드 때 적은 값과 같은지, 분석이 그 파일을 읽는지, 지침서를 잠시 치우면 분석이 통과하지 못하는지를 확인한다. 후 빌드에서 통과했다.

## 2. 지침서와 카탈로그

| 무엇 | 전 | 후 |
| --- | --- | --- |
| 지침서 경로 | 기획서/HAZOP기법지침.md | `specs/hazop-method-guide.md` |
| `GUIDE_SHA256` | `30dc958af67280efd39bd22b8f4e4b149322f6b03af4b6222445749a0fd7f347` | `6199fbc3bcae50a6cc6002bd7338cf49283991b7c25c24e2fd6b28ca419e039f` |
| 카탈로그 내용 해시 | `9fe31d10…368b` (고정값과 같음) | `9fe31d10…368b` (고정값과 같음) |
| 적용 판단 내용 해시 | `d87b4caf…7cb9` (고정값과 같음) | `d87b4caf…7cb9` (고정값과 같음) |
| `catalog_md`가 뽑은 것 전체(카탈로그·적용 판단·위험도 표)의 덤프 | `catalog-before.json` | `catalog-after.json`, 전과 바이트가 같음(`cmp`) |

지침서 해시가 바뀐 까닭은 둘이다. 문서 머리 9줄(HZ-PLN-07)을 달았고, 다른 문서를 가리키는 링크와 백틱 경로가 든 여섯 줄이 새 이름으로 바뀌었다(`git diff`로 센 값: 더한 줄 15, 뺀 줄 6). 표와 본문 문장은 그대로다. `PINNED_SHA256`은 건드리지 않았다.

## 3. 시안 그림

시안 폴더를 저장소 밖에 복사해 `build.py` 넷을 다시 돌리고(`--shoot`, Chrome 헤드리스), 옮기기 전 사본에서 찍은 그림과 옮긴 뒤 사본에서 찍은 그림을 대응표로 짝지어 견주었다(`compare_png.py`, 결과 `png-compare.csv`).

| 무엇 | 수 |
| --- | --- |
| 그림 | 64 |
| 전후 재실행 결과의 바이트가 같음 | 64 |
| 추적 중인 그림과 바이트가 같음 | 58 |

- 추적본과 다른 6장은 모두 `uiux-detail`이다. 이 폴더의 `build.py`는 `hazop/app/tokens.py`의 색을 읽는데, 시안을 찍은 뒤 색이 바뀌었다. 옮기기 전 재실행에서도 같은 6장이 달랐으므로 이름 이전과 무관하다.
- 추적 중인 그림은 다시 만들지 않았다.
- `build.py`가 다시 만든 HTML과 저장소의 HTML도 견주었다. `uiux-detail`의 화면 5개(위와 같은 색 차이) 말고는 `index.html`까지 모두 같다. 옮기기 전에도 같은 5개만 달랐다.

## 4. 결정로그 번호 열

`scripts/migrate_doc_headers.py`가 넣었다. 넣기 직전 파일(`decision-log-before-ids.md`)과 견준 결과다.

| 무엇 | 값 |
| --- | --- |
| 줄 수(머리 9줄 제외) | 전 245, 후 245 |
| 번호 열을 뺀 글이 넣기 전과 같은가(`strip_decision_ids`) | 같음 |
| 번호가 붙은 줄 | 236 (`DEC-0009` ~ `DEC-0245`, `DEC-0167`은 빈 줄이라 없음) |

## 5. N8이 실제로 켜졌는지

단계 3의 넓은 예외 줄(옛 폴더 다섯 개마다 모든 문서를 봐주던 줄)을 지운 뒤, 추적 문서 하나를 임시로 만들어 `` `기획서/인터페이스.md` ``와 옛 메모리/ 폴더를 가리키는 링크를 적고 `tests.test_naming_rules.RepoTest.test_tracked_files_follow_rules`를 돌렸다. N8 두 건(기획서/, 메모리/)과 N9 한 건으로 실패했다. 임시 문서를 지우니 다시 통과했다. 같은 내용을 시험 `test_n8_is_live_for_folders_moved_in_stage_3`로 고정했다.
