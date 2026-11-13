# mockups/app-shell-web — 도면 중심 웹 화면 시안

[도면 중심 웹 화면](../../app-shell-web.md)(HZ-DSN-05) §7의 시안이다. `index.html`을 브라우저로 열면 시안 목록과 '지금 → 새' 비교가 보인다. 네트워크 요청은 없다.

## 무엇을 넣는가

- `<번호>-<화면>.html`과 그 PNG(`-1920`은 1536×864 CSS 픽셀을 125%로 찍은 것, `-1366`은 100%)
- `0-current-1920.png`: 지금 화면 캡처(2026-11-13 첫 이정표 실행, `D:\HAZOP-trials\2026-11-13-first-milestone\run-1920-125\01-start-open.png`)
- `assets/app-shell.css`: 시안 공통 CSS. 토큰 값은 HZ-DSN-05 §4.1과 같다
- `assets/icons/`: 시안에 쓴 Tabler Icons 3.51.0 outline 원본(MIT, 라이선스는 `licenses/tabler-icons/LICENSE`)
- `assets/snp-m-101.svg`, `assets/snp-m-102.svg`: `resources/references/pid-samples/`의 SNP 표본 SVG에서 바깥 링크만 지운 것
- `build.py`: 위 파일을 모두 다시 만든다

## 다시 만들기

```
%USERPROFILE%\.hazop\venv-py312\Scripts\python.exe docs\design\mockups\app-shell-web\build.py
```

PNG는 `C:\Program Files\Google\Chrome\Application\chrome.exe` 헤드리스로 찍는다. `--no-png`를 주면 HTML만 만든다. 아이콘 원본 폴더가 다르면 `HAZOP_TABLER_OUTLINE`으로 준다.

## 값의 출처

- 도면 위 경로·고른 것 표시의 좌표는 SNP-M-101 추출 결과의 drawio 좌표에서 19를 뺀 SVG 좌표다(`build.py`의 `N`, `PATH_*`).
- 구간 이름, 분석 결과, 대화 문장, 호출 수는 화면 표현을 보이기 위한 예시 값이다.
