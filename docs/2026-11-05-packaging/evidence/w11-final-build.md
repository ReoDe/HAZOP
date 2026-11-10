# W11 최종 빌드 (배포본, T2)

> 일시: 2026-11-06 13:05~13:20. 기준 커밋: `ad9175b`(브랜치 `feat/next-units`, 작업 트리 깨끗함). 새 기능 없이 현재 코드로 빌드·검증만 했다.
> 산출물은 모두 저장소 밖 `%TEMP%\hazop-w11*`에 있고 저장소에 넣지 않았다.

## 1. 스냅숏

```
<전용 venv python> packaging/make_snapshot.py --dest %TEMP%\hazop-w11-src
```

- 결과: HEAD `ad9175bb7e305cd0560d38c35b36d21f7c4fe976`, 603개(disk 603·head 0·overlay 0), 목록 해시 `e75368358ad3acec6a01607edbf821f49a1f8fe61a59ca304019b709c48d0087`.
- 작업 트리에 변경·미추적 파일이 없어 `--restore-head`·`--overlay`를 쓰지 않았다. 따라서 스냅숏 = HEAD.
- 시작 전 지울 `%TEMP%\hazop-w11*` 산출물은 없었다. 다른 `%TEMP%\hazop-*` 폴더는 건드리지 않았다.

## 2. 빌드(전용 venv `%USERPROFILE%\.hazop\venv-py312`, CPython 3.12.10)

출력 폴더는 W10과 같이 나눈다: `%TEMP%\hazop-w11\verify-build`(`--with-check`), `%TEMP%\hazop-w11\deploy-build`.

| 빌드 | rc | 시간 | WARNING | 결과 폴더 |
|---|---|---|---|---|
| 검증용 `--with-check` | **0** | 89초 | 2(`qmlassetdownloaderprivateplugin.dll`, W10과 같은 유형) | `dist\HAZOP-verify` 2,593개, 602,360,509 bytes |
| 배포용 | **0** | 64초 | 1(같은 유형) | `dist\HAZOP` **2,592개, 595,431,756 bytes** |

- 두 빌드 모두 고지 복사, 결과 폴더 검사, 바이너리 검사(`COLLECT-00.toc`)가 통과했다.
- 절차 메모: 처음에는 두 빌드를 같은 `--out`에 넣어 배포용이 rc=3("배포용 출력 폴더에 검증용 결과(HAZOP-verify)가 함께 있음")으로 거부됐다. 이 결과는 `check_dist`가 의도한 동작이다. 이어서 셸 따옴표 실수로 `%TEMP%\hazop-w11$k-build` 폴더가 생겼다. 두 폴더를 모두 지우고 위 배치로 다시 빌드했다. 빌드 결함이 아니므로 `packaging/`는 고치지 않았다.

## 3. verify_bundle(스냅숏에서 실행)

| 실행 | `%TEMP%\hz_ascii` | `%TEMP%\한글테스트` |
|---|---|---|
| 검증용 | **통과** rc=0, 42초 `results-verify-ascii\run-20261106-131341-4ny5kmq0` | **통과** rc=0, 41초 `results-verify-korean\run-20261106-131423-_nxncg_q` |
| 배포용 `--app-only` | **통과** rc=0, 9초 `results-deploy-ascii\run-20261106-131504-d55foki5` | **통과** rc=0, 8초 `results-deploy-korean\run-20261106-131513-ceq6cv8x` |

- 검증용(두 경로 같음): flow rc=0이며 16줄이 모두 `[OK]`다(①~⑤, `bundle-datas` 12개 해시, graph_version `v-f65e4ec1135d`, ④ `passed` 44·14·6·11, 음성 검사 포함). check_kg_screen rc=0, pdf_probe rc=0, PNG 9장. `licenses_problems`·`pdf_problems`·`png_fresh_problems` = `[]`이고 `inputs_unchanged_by_kg_check`·`repo_unchanged` = 참이다. 잘못된 옵션 rc 2, 손상 설정 rc 2(0.1·0.2초), 시험 트리거 rc 70(0.2·0.1초), `app_log_unhandled` = 참.
- 배포용(두 경로 같음): PNG 4장, 고지·PDF 문제 없음, 저장소 불변, 잘못된 옵션 rc 2, 손상 설정 rc 2, 트리거 실행 rc 2·`app_trigger_off` = 참(시험 트리거 꺼짐).
- graph_version이 W4 기록(`v-7ed95b0c74f1`)과 다른 것은 기준 커밋의 추출 빌더 0.3.0(`ad9175b`) 때문으로 본다 [추론]. 검사 판정에는 영향이 없다.

## 4. 테스트(스냅숏, 전용 venv)

| 실행 | 결과 |
|---|---|
| `-m unittest tests.test_packaging tests.test_app_startup` | 82건 OK(건너뜀 1) |
| `-m unittest discover -s tests -t .` | **841건 OK(건너뜀 9)**, rc=0, 147초 |

## 5. 배포 zip

- 대상: 배포용 `deploy-build\dist\HAZOP`(검증 exe 없음). zip 안의 최상위 폴더는 `HAZOP/`이며 Python `zipfile` DEFLATE(수준 6)로 압축했다.
- 경로: `%TEMP%\hazop-w11\HAZOP-0.1.0-20261106.zip`(버전 = `hazop/app/main_window.py` `APP_VERSION`).
- 크기 **230,288,644 bytes**, 항목 2,592개(원본 파일 수와 같음), `testzip` 오류 없음.
- SHA-256 **`8be9acf9ccec22235c3a651e02d5388364fb81c5d449929674347e967ebbcdcd`**(Python hashlib·certutil 일치).
- zip을 `%TEMP%\hazop-w11\unzip`에 풀어 배포용 verify(`--app-only`, `hz_ascii`)를 실행했고 **통과**했다(rc=0, `results-zip-ascii\run-20261106-131913-ij4ygd8o`, 검사 항목은 §3 배포용과 같음). 확인 뒤 푼 폴더는 지웠다.

## 6. 새 스크립트의 묶음 포함 여부(판단만)

대상: `scripts/check_contract.py`, `scripts/compare_criteria.py`, `scripts/clean_outputs.py`.

- 빌드 설정(`scripts/build_package.py` `DATA_FILES`)은 화면이 importlib로 읽는 `extract_drawio.py`·`build_graph.py`만 묶는다(D5). 세 스크립트는 묶음 datas에 없다. 이들이 쓰는 `hazop.contract`·`hazop.evaluate`·`hazop.kg` 모듈은 `collect_submodules("hazop")`로 PYZ에 들어간다.
- 배포 실행 파일 `HAZOP.exe`는 창 프로그램(①~⑤)이며 임의 스크립트를 실행하는 입구가 없다. 파일 경로로 받은 .py를 실행하는 `HAZOP-check.exe`는 검증 전용이라 배포하지 않는다(`packaging/README.md`). `hazop/app`에는 contract·evaluate를 부르는 코드가 없다.
- 세 스크립트는 개발·검토용 명령줄 도구다. 예를 들어 `기획서/평가기준비교.md` 342행은 `python scripts/compare_criteria.py …` 명령으로 정의한다. 따라서 앱 사용 범위 ①~⑤에 필요하지 않다.
- **판단: 묶지 않는 현행 구성을 유지한다.** 배포본에서 이 명령을 쓰려면 별도 입구 exe가 있어야 하며, 이는 새 기능이므로 이번 범위 밖이다.

## 7. 남은 한계

- 같은 PC에서 경로만 바꿔 시험했다. 다른 PC나 깨끗한 Windows 10에서는 시험하지 않았다.
- 이번 빌드에서는 `netwatch.ps1` 네트워크 관찰을 다시 하지 않았다. 빌드 설정은 W10과 같다.
- zip과 exe에는 코드 서명이 없다. SmartScreen 경고가 뜰 수 있다 [일반지식].
- W6 사용자 확인 항목(LGPL 요건·소스 제공 방식 등)과 `W7`(비NTFS `os.link`)은 남아 있다. 고지는 법무 검토 전 내부용이다(정보 창 안내).
- 대화형 설정 손상 대화상자와 부트로더 경유 실제 미처리 예외는 이번에도 묶인 실행에서 누르지 않았다(W10 §7.4와 같음).
