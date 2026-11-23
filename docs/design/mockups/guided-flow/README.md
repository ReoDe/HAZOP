# mockups/guided-flow — 쉬운 흐름 시안

[쉬운 흐름](../../guided-flow.md)(HZ-DSN-06)의 시안이다. `1-guided-flow.html`을 브라우저로 열면 된다. CSS·아이콘·도면이 파일 안에 들어 있어 네트워크 요청이 없다.

## 무엇을 넣는가

- `1-guided-flow.html`: 시안 파일 하나. 왼쪽 아래 '시안 조작' 상자에서 장면 여덟 개를 바꾸고 남은 일을 켜고 끈다. 주소 끝에 `#scene=queue_ai&cap=1`처럼 장면을 주면 그 장면으로 열리고, `cap=1`이면 시안 조작 상자를 숨긴다
- `template.html`: 시안의 원본. 공통 CSS·아이콘·도면 자리에 표시만 있다
- `<번호>-<장면>-1366.png`: 1366×768(100%) 캡처 여덟 장. `-1920.png`는 1536×864 CSS 픽셀을 125%로 찍은 것 두 장
- `build.py`: `template.html`에 `../app-shell-web/assets/app-shell.css`, Tabler Icons 3.51.0 outline(MIT), SNP-M-101 표본 SVG를 넣어 `1-guided-flow.html`을 쓰고, Chrome 헤드리스로 PNG를 찍으면서 장면마다 넘친 요소가 있는지 검사한다

## 다시 만들기

```
%USERPROFILE%\.hazop\venv-py312\Scripts\python.exe docs\design\mockups\guided-flow\build.py
```

`--no-png`를 주면 HTML만 만든다. 아이콘 원본 폴더는 `HAZOP_TABLER_OUTLINE`, Chrome 경로는 `HAZOP_CHROME`으로 바꿀 수 있다. 넘친 장면이 있으면 그 이름을 찍고 종료 코드 1로 끝난다.

## 값의 출처

- 도면은 `resources/references/pid-samples/`의 SNP-M-101 공개 표본에서 바깥 링크를 지운 것(`../app-shell-web/assets/snp-m-101.svg`)이다. 구성요소 자리는 그 추출 결과의 drawio 좌표에서 19를 뺀 SVG 좌표다(`../app-shell-web/build.py`의 `N`과 같은 값).
- 대기열 항목의 제안·확신·문장, 찾지 못한 구성요소와 그 후보, 남은 일의 수는 화면 표현을 보이기 위한 예시 값이다.
