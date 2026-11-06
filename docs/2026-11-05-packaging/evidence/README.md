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
| 2026-11-05 | [w4-빌드.md](w4-빌드.md) (기준 `5fa64ee` + W4, 저장소 밖 스냅숏) | PyInstaller 6.22.3 one-folder 빌드 rc=0, 네트워크 연결 0건, 묶음 578.8 MiB·3,126개, `hazop` 65모듈 포함·anthropic·httpx·pdfplumber 제외. ASCII·한글 경로 모두 ①~⑤ 흐름·③ V1·V2·S1·PNG 9장 통과(③은 검증 전용 HAZOP-check.exe) | W4 1차(반려). 재작업 1회차(같은 문서 갱신): 기준 `f3b309e` + W4, 검증용·배포용 두 빌드(배포용 573.1 MiB, 검증 exe 없음), 두 경로 verify 통과(자원 읽기 위치·음성 검사·앱 로그 포함). D5 확정·D6 확정·D7안. 재작업 2회차(같은 문서 갱신): 검증기 기존 폴더 비삭제·흐름 즉시 종료·스냅숏 경로 정규화, 재빌드 2종, 두 경로 verify 통과, 런타임 네트워크 원격 0 → 재검토 대기 |
| 2026-11-06 | [w6-라이선스.md](w6-라이선스.md) (기준 `fa1b748` + W6) | `licenses/` 원문 41개(venv dist-info·CPython·로컬 FSF 사본·force-graph 의존성 30개 다운로드)와 고지 목록 SHA-256, PySide6 휠에 LGPL·GPL 원문 없음, d3-ease는 BSD-3-Clause(W1 정정), 의존성 버전은 추정 | W6 구현 완료(검토 대기). 사용자 확인 7건. 재작업 1회차(같은 문서 갱신): 기준 목록 대조 테스트, 묶음 대비 누락 목록과 첨부 [w6-묶음수집목록.md](w6-묶음수집목록.md)(W4 배포용 TOC), PATH 경유 DLL 45개 발견, verify_bundle licenses 검사 → 고지 초안 완료, 사용자 확인·추가 원문 대기 |
| 2026-11-06 | [w8-경로통제.md](w8-경로통제.md) (기준 `a0df5ef` + W8-A, 저장소 밖 스냅숏) | UCRT는 PyInstaller `_win_includes`라 찾으면 묶임(기본 제외 아님). 빌드 PATH를 venv Scripts·기반 CPython·DLLs·System32로 통제하고 COLLECT TOC 출처 검사 추가 → PATH 경유 DLL 45→0, 배포용 3,120개·564.6 MiB. 묶인 실행 PATH를 System32·Windows로 한정해 두 경로 verify 4회 통과. Qt TLS는 Schannel로 바뀜. venv 611 OK·스냅숏 603 OK | W8-A 구현 완료(검토 대기). D10. 재작업 1회차(같은 문서 갱신): Qt `qopensslbackend.dll` 제외, 허용 루트 venv·기반 CPython과 이름 거부 목록, TOC 형식 검사, 전용 venv 확인 → 배포용 3,119개·564.3 MiB, verify 4회 통과, 사용자 PATH 전체에서도 `libssl-3-x64` 미로드, venv 617 OK → 재검토 대기. 재작업 2회차(같은 문서 갱신, 기준 `dbcc855`): TLS 플러그인 허용 목록·출처 긴 파일명 검사, `packaging/tls_probe.py` 로드 모듈 72개 모두 묶음·Windows 출처, verify 4회 통과, venv 629 OK → 재검토 대기 |
| 2026-11-06 | [w5-신뢰경계.md](w5-신뢰경계.md) (기준 `116195b` + W5) | 패턴 라이브러리(`content_sha256`)·지침서(CRLF→LF 정규화 바이트 해시)를 고정, autocrlf 작업 트리(CRLF)와 git 저장 내용(LF)이 같은 값. 임시 자원 루트 사본 1바이트 변경 5종 모두 입력 차단·사유 표시, 기존 묶음 자원 5개 고정값 일치, 로컬 실행 폴더 resume 영향 없음. venv 655 OK | W5 구현 완료(검토 대기). 기획서 문안(§5) 반영 대기 |
| 2026-11-06 | [w8b-모듈제외.md](w8b-모듈제외.md) (기준 `5225cc5` + W8-B, 저장소 밖 스냅숏) | PyInstaller QtQml 훅이 `PySide6/qml` 전체를 모아 GPL 전용 모듈이 묶였다(WebEngine이 Qt6Quick·Qt6Qml·Qt6QuickWidgets를 링크). 설치본 SPDX로 Charts·DataVisualization·Graphs·VirtualKeyboard·Quick3D가 GPL 전용임을 확인했다(QuickTimeline·ShaderTools는 표기 없음). 제외 규칙 8개(ShaderTools 의존 Qt5Compat.GraphicalEffects 포함)와 빌드 뒤 검사를 추가했다. 배포용 3,119→2,235개·564.3→528.1 MiB, 두 경로 verify 4회 통과, venv 674 OK | W8-B 구현 완료(검토 대기). D13. 재작업 1회차(같은 문서 갱신): 결과 폴더 전체 꼬리 판정(오탐 0)·탐색 오류 실패 처리·고아 DLL 기록·Qt6SpatialAudio 제외(총괄 판정) → 배포용 2,234개·527.4 MiB, 빌드 rc=0 실측, verify 4회 통과, venv 676 OK → 재검토 대기. 재작업 2회차(같은 문서 갱신): 이름 규칙(설치본 전체 이름)·폴더 규칙(PySide6 기준 경로)으로 오탐 원인 제거, 이동 플러그인 검출, spec 모의 실행 테스트, 링크·is_dir 오류 폴더 실패 처리, 오탐 확인(설치본·W8-A 묶음), 재빌드 rc=0, verify 4회 통과, venv 681 OK → 재검토 대기 |
