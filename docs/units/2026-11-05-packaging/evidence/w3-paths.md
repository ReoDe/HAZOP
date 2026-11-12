# W3 — 경로·importlib 로딩 정리 (T2)

> 실행 일시: 2026-11-05 21:00~21:56(1차 21:36, 재작업 1회차 마지막 실행 21:56). 기준 커밋 `ddb9a50`(브랜치 `feat/next-units`, 미커밋 변경). 근거 결정: D1(결정 5 (가) datas+hiddenimports).
> 실행 주체: hazop-developer.

## 0. 판정 범위

W3 결과는 **경로 선택 검증**이다. 개발 실행과 모의 frozen(`sys.frozen`·`sys._MEIPASS` 패치)에서 프로그램·자원·작업 루트와 스크립트 경로가 맞게 고른다는 것만 확인했다.

- 모의 frozen의 한계: 테스트 프로세스에는 저장소의 `hazop` 패키지와 모든 서드파티가 그대로 import돼 있다. 그래서 묶음에서 hiddenimports가 빠지거나 datas(템플릿·vendor·기준 자료)가 빠져도 이 테스트는 통과한다. 이런 누락은 가려진다.
- 저장소가 없는 환경에서 실제 번들로 ①~⑤를 확인하는 것은 **W4의 완료 기준**이다.

## 1. 변경

| 파일 | 변경 |
|---|---|
| `hazop/paths.py` | 추가만 했다: `program_root()`(묶인 실행이면 `sys._MEIPASS`, 아니면 `REPO_ROOT`)와 `program_path(*parts)`. 코드 위치이므로 `HAZOP_RESOURCE_ROOT`를 따르지 않는다. 머리 주석에 프로그램 루트 한 줄을 추가했다. `frozen_bundle_dir` docstring에 "frozen 판단은 `_MEIPASS`만 본다(`sys.frozen`만 있으면 개발 실행 취급)"를 명시했다. 기존 `resource_root`·`work_root`와 같은 판단이며 동작은 바꾸지 않았다 |
| `hazop/app/data.py` | importlib 로딩만 바꿨다. ① `script_module`은 호출할 때마다 `paths.program_path("scripts", name + ".py")`를 계산한다. ② 캐시 키는 정규화한 파일 경로(`normcase(realpath)`)다. 그래서 루트가 바뀌면 이전 모듈을 돌려주지 않는다. ③ `name`은 `SCRIPT_NAMES = ("extract_drawio", "build_graph")`로 제한했다(현재 호출부 전부). 경로 구분자(`/` `\` `:`)·`..`·절대 경로·목록 밖 이름은 `ValueError`를 낸다. ④ 파일이 없으면 경로를 담은 `FileNotFoundError`를 낸다(W4에서 datas 누락을 바로 알 수 있게) |
| `SCRIPTS_DIR` | 이름만 남긴 **참고값**이다(가져올 때의 `program_path("scripts")`). 로딩에는 쓰지 않는다. 바깥에서 이 값을 바꿔 로딩 위치를 바꾸던 동작은 이제 통하지 않는다(저장소 안에 그런 사용처는 없음, grep). 즉 이름은 호환되지만 동작까지 완전히 호환되지는 않는다 |
| `tests/test_packaging.py` | 신규 9건(아래) |

결정 5 (가)에 따라 `scripts/extract_drawio.py`·`build_graph.py`는 바꾸지 않았다. W4 spec에서 할 일: 두 파일을 datas `scripts/`로 넣고, `collect_submodules("hazop")`를 hiddenimports에 넣는다.

## 2. 테스트 (`tests/test_packaging.py`)

| 테스트 | 확인 |
|---|---|
| `PathsCompatTest.test_existing_api_unchanged` | 하위 호환 확인 방법. `ddb9a50` 시점 공개 함수 13개의 `inspect.signature` 문자열, 상수 4개(`ENV_*`·`RESOURCE_INPUT_ROLES`), `REPO_ROOT`를 비교한다. `DEFAULT_SETTINGS`는 기존 키·값 포함 여부만 본다. 선택 인자를 추가하면 표도 함께 고친다는 규칙을 주석에 남겼다 |
| `PathsCompatTest.test_program_root_dev_ignores_resource_env` | 개발 실행에서 `HAZOP_RESOURCE_ROOT`를 바꿔도 `program_root()`는 저장소다 |
| `PathsCompatTest.test_frozen_detection_combinations` | `sys.frozen` 있음/없음 × `_MEIPASS` 있음/없음 네 조합. `_MEIPASS`가 있을 때만 묶음으로 판단한다(프로그램·자원 루트 = 묶음, 작업 루트 = `%LOCALAPPDATA%\HAZOP`). `sys.frozen`만 있으면 개발 실행이다 |
| `ScriptLoadingTest.test_dev_loads_repo_scripts` | 개발 실행에서 두 스크립트 모듈의 `__file__`이 `<저장소>/scripts/*.py`다 |
| `ScriptLoadingTest.test_frozen_loads_bundle_scripts` | 모의 frozen(임시 `dist/HAZOP/_internal`에 두 스크립트 복사)에서 모듈 `__file__`이 묶음 `scripts/`다. 자원 루트 = 묶음, 작업 루트 = `%LOCALAPPDATA%\HAZOP`(임시). 끝나면 `sys._MEIPASS`·`sys.path`·캐시를 원복한다 |
| `ScriptLoadingTest.test_frozen_missing_script_reports_path` | 묶음에 `scripts/`가 없으면 경로가 든 `FileNotFoundError`를 내고 캐시에 남기지 않는다 |
| `ScriptLoadingTest.test_cache_keyed_by_path` | 같은 이름이라도 `_MEIPASS`가 바뀌면 새 모듈을 읽는다. 같은 경로는 캐시를 쓴다 |
| `ScriptLoadingTest.test_name_restricted` | 목록 밖 이름(`analyze`), 상대 경로·`..`, 절대 경로, 드라이브 표기, 빈 값, `None`은 모두 `ValueError`이고 캐시를 건드리지 않는다 |
| `SplitRootsFlowTest.test_flow_1_to_5_with_split_roots` | 자원 루트(기준 자료 4종·지침서·샘플 도면)와 작업 루트(구간·고정 응답·그래프·지식 입력)를 서로 다른 임시 폴더로 두고, 화면이 쓰는 함수로 ①~⑤를 돈다. ① 등록→추출→그래프(등록 SVG 사용) ② 추출 목록·뷰어 HTML ③ 지식그래프 빌드·`list_kg_roots`·`screen_data`·HTML ④ `api.run_analysis` 고정 응답(후보 44·시나리오 14·위험도 6·설계보완 11), `list_regions`·`list_runs`·`current_graph` ⑤ 검토 저장 v1·Excel 1개. **④ 음성 단계**: 지침서만 있는 자원 루트로 바꾸면 `run.InputError("candidate_catalog 파일 없음")`이 나고 실행 폴더가 생기지 않는다. 마지막으로 자원 루트 파일 해시와 저장소 `출력/`·`자료저장소/` 파일 목록이 전후 같은지 본다 |

**회귀 검출 확인**(scratchpad 스크립트, 코드 미수정)

- 방법: `run.load_inputs`를 `resource_root=paths.REPO_ROOT` 고정으로 바꾼 변형을 mock으로 끼워 `SplitRootsFlowTest`를 돌렸다.
- 결과: `AssertionError: InputError not raised`로 **실패**했다. 변형을 빼면 통과한다.
- 처음에는 자원 루트를 빈 폴더로 두었다. 이때는 지침서 무결성 검사(`integrity.py`)가 먼저 막아서 위 회귀를 잡지 못했다. 그래서 지침서만 둔 자원 루트로 바꿨다.
- 같은 방식으로 따져 보면, 변경 전 `data.py`(`REPO_ROOT` 고정)에서는 `test_frozen_loads_bundle_scripts`가 실패한다(코드 대조만 했고 실행하지는 않았다).

## 3. 실행 결과

| 실행 | 결과 |
|---|---|
| 1차(21:36) | 전용 venv 562 OK(건너뜀 14). PATH python은 실패 2건(`test_app` 1366 폼 폭, `test_design` 원인 위젯)이 났다. 같은 시간에 T6 W3가 진행 중이었다. `git archive ddb9a50` 사본에 W3 파일 3개만 얹어 돌리면 PATH python 562 OK였다. T6 마무리 뒤 작업 트리를 재실행하자 양쪽 566 OK, `check_app.py` rc=0 |
| 재작업 1회차(21:52~21:56) | 전용 venv(`%USERPROFILE%\.hazop\venv-py312`, 3.12.10) `PYTHONUTF8=1 -m unittest discover -s tests`: 571건 OK(건너뜀 14). PATH python(LibreOffice 3.12.14) 첫 실행: 실패 2건(`test_design.ElidedLabelTest` 2건). T6 파일(`widgets.py`·`test_design.py`)이 수정 중이었다. 바로 두 인터프리터로 그 클래스만 다시 돌리면 OK였다. 21:56 전체 재실행: **571건 OK**. `scripts/check_app.py` rc=0("전부 통과") |
| `scripts/check_desktop_support.py`(패키징 대비 행 포함), `scripts/check_kg_screen.py` | 1차에 rc=0. 재작업은 테스트 파일과 `data.py` 로딩부만 바꿨으므로 다시 돌리지 않았다 |

## 4. W4에서 볼 것

- spec datas: `scripts/extract_drawio.py`·`scripts/build_graph.py` → `scripts/`. `hazop/viewer/template.html`, `hazop/kg/screen_template.html`, `hazop/kg/vendor/**`(패키지 `__file__` 기준). 자원(`데이터/이탈후보·기준표·패턴`, `docs/specs/hazop-method-guide.md`). hiddenimports는 `collect_submodules("hazop")`.
- 저장소가 없는 환경(묶음 폴더만 있는 위치)에서 ①~⑤를 실제 번들로 확인한다. W3 모의 검사가 가린 hiddenimports·datas 누락은 여기서 드러난다.
- 실제 PyInstaller 6.22에서 확인할 것: `hazop/paths.py`의 `__file__`과 `sys._MEIPASS`가 같은 폴더(`_internal`)인지, 묶음 안 `.py`를 `spec_from_file_location`으로 읽을 때 스크립트의 `sys.path.insert(0, REPO_ROOT)`가 문제를 일으키지 않는지.
- 작업 루트 초기 내용(구간·고정 응답·지식 입력)을 첫 실행 때 어떻게 둘지는 미결이다(W1 §3.4-4).
- 인터페이스 §7.1의 프로그램 루트 문구는 W4에서 함께 반영한다(총괄 판단).
- 이 테스트는 화면 위젯이 아니라 화면이 부르는 함수 단위로 ①~⑤를 돈다. 창을 띄운 흐름은 W4 묶인 실행 스크린샷에서 확인한다.
