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
