# 패키징 결정 기록

> 설계·정책·작업 기준에 관한 결정을 근거와 함께 누적한다. 진행 상태는 [`PROGRESS.md`](PROGRESS.md)에만 기록한다.
> 열린 결정이 실행 순서나 게이트에 영향을 주면 [`ROADMAP.md`](ROADMAP.md)와 함께 갱신한다.

## 결정 목록

범위 확장 결정에는 사유, 추가·제외 범위, 관련 작업 ID, 기존 완료 기준·일정·의존성에 미치는 영향과 사용자 요청 또는 결정 근거를 기록한다. 확정되지 않은 선택은 열린 상태로 구분한다.

| ID | 일자 | 결정 | 근거 | 상태 |
|---|---|---|---|---|
| D1 | 2026-11-05 | W1 조사 권고안 채택(사용자 위임 "권고 자동 선택"): 신뢰 경계 A(실행 폴더 고정+SHA-256 대조, 패턴 라이브러리·지침서 추가 고정), 글꼴 A(맑은 고딕 유지, Pretendard 미동봉 — T6 §4.2 반영 인계), 빌드 도구 PyInstaller one-folder 우선, importlib 로딩 (가) 스크립트 자원 포함+숨은 import, `os.link`는 실측 뒤 기본안 "작업 폴더가 NTFS가 아니면 경고·거부", 배포본에서 anthropic·httpx 제외. 설치·다운로드(CPython 3.12, venv, 라이선스 원문)와 배포 자원 범위(보안 등급 확인)는 사용자 승인 대기 | [W1 조사](evidence/w1-조사.md) §6 | 확정(설치·다운로드는 승인 대기) |
| D2 | 2026-11-05 | 사용자 승인: python.org CPython 3.12 설치와 전용 venv(PySide6 6.12.0·networkx 3.7·openpyxl 3.1.5·pyinstaller 6.22) pip 설치, force-graph 번들 의존성 LICENSE 원문 다운로드 | 사용자(2026-11-05 질의 응답) | 확정 |
| D3 | 2026-11-05 | `W2` 판정: ① CPython 3.12.10을 공식 MSI가 아닌 python.org install manager(`py install --target`)로 설치 — MSI 2203 실패, 내려받은 zip SHA-256은 python.org 값과 일치(D2 승인 범위 안의 방식 변경, 사용자 고지) ② anthropic 미설치 venv에서는 SDK가 필요한 테스트만 `skipUnless`로 건너뜀(선택지 나). `tests/test_analysis.py`는 T2 편집 범위 밖이지만 테스트 실행 조건만 바꾸는 변경으로 총괄이 직접 처리 ③ venv 실제 위치가 Claude 앱 MSIX 리디렉션 경로(`AppData\Local\Packages\Claude_…\LocalCache\Local\HAZOP\venv-py312`)일 수 있음 — 일반 터미널에서 다시 만들지는 사용자 결정 ④ 전이 의존성·해시 고정은 `W4` 전에 한다 | W2 Claude 검토(조건부 승인), 총괄 판정 | 확정 |
| D4 | 2026-11-05 | 사용자 결정: ① venv를 가상화되지 않는 `%USERPROFILE%\.hazop\venv-py312`에 다시 만듦(재생성 후 전체 테스트 489 OK·건너뜀 5) ② 배포본 인터프리터는 CPython 3.12.10을 유지하고 패키징을 끝낸 뒤 3.13 등 전환을 재검토 | 사용자(2026-11-05 질의 응답) | 확정 |
| D5 | 2026-11-05 | 배포 묶음에 `참고자료/` 샘플 도면(28 MB)을 넣지 않는다. 묶음 datas는 템플릿 2개·`hazop/kg/vendor`·지침서·데이터 3종(이탈후보·기준표·패턴)·`scripts/extract_drawio.py`·`build_graph.py`로 한정한다. 영향: 묶인 실행에서 `extract_drawio --samples`와 등록 대화상자 시작 위치에 샘플이 없다. 샘플이 필요하면 사용자가 작업 폴더에 둔다 | W1 §6-7(샘플 포함은 사용자 판단·보안 등급 확인 필요), W4 작업지시서 권장안, [W4 빌드](evidence/w4-빌드.md) §6 | 확정(총괄 승인, W4 재작업 1회차) |
| D6 | 2026-11-05 | W4 완료 기준(W1 210행 "`--screenshots`로 5개 화면 PNG, ③ V1·V2·S1이 묶인 실행에서 통과") 해석: ①②④⑤ PNG는 `HAZOP.exe --screenshots`, ③ PNG·③ V1·V2·S1·①~⑤ 함수 흐름은 같은 `_internal`을 쓰는 검증 전용 실행 파일(`HAZOP-check.exe`, `--with-check` 빌드, 배포 제외)로 대체한다. HAZOP.exe 자체의 importlib 스크립트 로딩 실행은 `run_app.py`/`screenshots.py` 편집(범위 밖)이 필요해 한계로 남긴다 | W4 Codex 반려·Claude 조건부 지적 M1, 총괄 판정, [W4 빌드](evidence/w4-빌드.md) §0 | 확정(총괄 판정) |
| D7 | 2026-11-05 | 묶인 실행(`console=False`)의 로그: PyInstaller 런타임 훅 `packaging/rthook_applog.py`가 `<작업 루트>/logs/app.log`에 root logging(INFO 이상)·없는 stdout/stderr·미처리 예외를 남긴다. 앱 코드(`run_app.py`·`hazop/app`)는 바꾸지 않는다. 미정: 로그 보존 기간, 로그 크기 제한 없음(회전·상한 없이 계속 덧붙임), Qt 메시지 핸들러 미연결(`qInstallMessageHandler`를 쓰지 않아 Qt 내부 경고는 로그에 남지 않음), 오류 대화상자 유지(`disable_windowed_traceback` 기본값) | 총괄 L2(권장안), [W4 빌드](evidence/w4-빌드.md) §2·§4 | 확정(총괄 승인, 권고안) |
| D8 | 2026-11-06 | `W4` 판정: 재작업 2회 뒤 Claude 승인·Codex 반려(개발용 하네스 `make_snapshot.py` 경로 2건·테스트 공백). 사용자 위임(권장안 선택)에 따라 총괄이 직접 수정 — 추적 파일도 저장소 밖(링크)이면 거부, `--restore-head`를 Git의 정확한 경로로 맞춤(대소문자 무시 비교 키 통일), `test_restore_head_case_insensitive` 추가 — 하고 완료 처리. 남은 테스트 공백(존재 파일 해시 불일치 후 중단, 해시 수집 실패 뒤 정리 성공, stream 쓰기·flush 실패 시 이전 훅)과 Claude R1(netwatch에 프로세스 이름·pid 미기록)·R2(Stop 이외 예외 때 flow.json 미기록)는 알려진 한계로 [W4 §6](evidence/w4-빌드.md)에 둔다 | Codex 최종 재검토(반려), Claude 최종 재검토(승인), 사용자 운영 지시(2026-11-05) | 확정 |
| D9 | 2026-11-06 | `W6` 편집 범위 확장: 저장소 루트에 `licenses/`(제3자 고지 원문·고지 목록 `licenses/README.md`·줄 끝 변환을 막는 `licenses/.gitattributes`)를 새로 만들고, `scripts/build_package.py` `DATA_DIRS`에 `licenses`를 추가해 묶음 `_internal/licenses/`에 넣는다. 제외: 루트 `.gitattributes`, 앱 정보 대화상자(`hazop/app`) 안내. 영향: 묶음 datas가 46개 늘어난다(재작업 1회차 기준)(W4 검증 하네스는 datas 목록을 그대로 읽으므로 수정 없음). README §8 편집 허용 범위에 `licenses/`를 추가한다 | W6 작업지시서 권장안, W1 §7 W6 완료 기준 | 확정(총괄 승인) |
