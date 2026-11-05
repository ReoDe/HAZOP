# 패키징 증거

> 조사·검증 결과와 작업 상태 판정의 근거를 보관한다.

## 기록 규칙

- 근거마다 조사 일시, 대상 경로 또는 커밋, 확인한 사실, 판정에 미치는 영향을 기록한다.
- 원문 전체를 복사하지 않고 저장소 경로와 필요한 발췌 위치를 연결한다.
- 비밀번호, 토큰, 개인정보 등 민감정보는 기록하지 않는다.
- 증거가 추가되면 아래 인덱스와 [`PROGRESS.md`](../PROGRESS.md)의 관련 상태를 함께 갱신한다.

## 증거 인덱스

| 일시 | 증거 | 확인한 사실 | 상태 영향 |
|---|---|---|---|
| 2026-11-05 | [w1-조사.md](w1-조사.md) (기준 `d540288`) | §9 미결 2건 선택지·권고, force-graph 번들 의존성(MIT·ISC, ColorBrewer Apache-2.0 포함), PyInstaller·대안 비교와 막힐 지점, `os.link`는 NTFS 전용(MS 문서), 전용 venv 패키지 목록 | W1 조사 결과. 사용자 결정 9건 대기 |
| 2026-11-05 | [w2-venv.md](w2-venv.md) (기준 `b29e5f7`) | CPython 3.12.10(3.12 마지막 Windows 바이너리, SHA-256 대조 일치)을 install manager `--target`으로 설치(MSI 설치는 MSIX 리디렉션 추정 원인으로 실패), venv `%LOCALAPPDATA%\HAZOP\venv-py312`에 PySide6 6.12.0·networkx 3.7·openpyxl 3.1.5·pyinstaller 6.22.3. unittest 465건 중 실패 2·오류 3(모두 anthropic 미설치), check_app·check_kg_screen 통과 | W2 1차 실행 기록. 총괄이 (나) 건너뛰기로 처리(D3) 후 venv 전체 테스트 478건 OK·건너뜀 5 → `W2` 완료 |
| 2026-11-05 | [w3-경로.md](w3-경로.md) (기준 `ddb9a50`) | `paths.program_root()`·`program_path()` 추가(기존 API 서명 고정 테스트), `data.script_module`이 묶음 폴더 `scripts/`를 읽음(모의 frozen), 자원·작업 루트 분리 ①~⑤ 함수 흐름과 ④ 음성 단계 통과, 스크립트 이름 허용 목록·경로 키 캐시. 경로 선택 검증에 한정(실번들은 W4). 최종 venv·PATH python 571 OK | W3 구현 완료(재작업 1회차), 재검토 대기 |
