# 조사 요약: 옵시디언식 UI 패턴과 HAZOP 소프트웨어 (2026-11-07)

[README](README.md) · [결함 목록](결함목록.md) · [개선 명세](개선명세.md)

## 조사 방법과 범위

- `/aside-browser`(aside exec, 읽기 전용) 두 작업으로 공식 문서와 공개 자료만 읽었다. 로그인·결제·쿠키 동의·데모 신청 양식에는 아무것도 입력하거나 누르지 않았다.
- help.obsidian.md 주소는 모두 obsidian.md/help/…로 넘어갔다. 아래 표에는 실제로 읽은 주소를 적었다.
- 못 읽은 페이지(404): Obsidian `user-interface/tabs`·`status-bar`·`split-the-workspace`(다른 주소에서 대신 읽음), Linear `docs/keyboard-shortcuts`·`docs/peek`.
- 부분만 읽은 자료: VS Code UI 문서(앞부분과 키워드 부분), Open-PHA 매뉴얼 R5.15(§3.1–3.4, §6.1–6.2, 부록 A), Vizop 사용자 가이드(키워드 쪽과 3·10·16·35–37쪽), RMPCorp 동영상(10:40·14:38·25:25 장면). 빠진 기능이 있을 수 있다.
- "확인 못함"은 기능이 없다는 뜻이 아니라, 연 페이지에서 찾지 못했다는 뜻이다.

## 1. 생산성·엔지니어링 도구 패턴

| 패턴 | 확인한 동작 | 출처 | 이 앱에 쓸 점 |
| --- | --- | --- | --- |
| 왼쪽 탐색기 | Obsidian: 정렬, 활성 파일 자동 표시, 모두 펼치기·접기, Alt·Shift 다중 선택. VS Code: Ctrl+B로 숨김, Ctrl+Alt+F로 트리 필터. Notion: 오른쪽 경계를 끌어 너비 조절 | obsidian.md/help/plugins/file-explorer · code.visualstudio.com/docs/getstarted/userinterface · notion.com/help/navigate-with-the-sidebar | 트리 필터, 너비 조절, 현재 탭 항목 자동 강조(U-04) |
| 탭·분할 | Obsidian: Ctrl+T 새 탭, Ctrl+클릭 새 탭, 오른쪽·아래 분할, Ctrl+Tab·Ctrl+1~8 전환, Ctrl+Shift+T 닫은 탭 복원. VS Code: Ctrl+\ 분할, Ctrl+1/2/3 그룹 전환 | obsidian.md/help/tabs · code.visualstudio.com/docs/configure/custom-layout | 도면·구간·결과·그래프를 탭으로 열고 오른쪽 분할(U-03) |
| 명령 팔레트·빠른 전환 | Obsidian: Ctrl+P 명령(퍼지 매칭, 최근 명령 우선), Ctrl+O 빠른 전환(빈 검색어면 최근 항목, Ctrl+Enter 새 탭). VS Code: `?` 입력 시 명령 목록. Linear: Cmd/Ctrl+K 전체 명령 | obsidian.md/help/plugins/command-palette · obsidian.md/help/plugins/quick-switcher · linear.app/docs/joining-your-team-on-linear | 구성요소·구간·칸·명령을 한 상자에서 찾기, 단축키를 결과 옆에 표시(U-01) |
| 백링크·오른쪽 패널 | Obsidian: 오른쪽 사이드바 Backlinks에 Linked/Unlinked mentions, 결과 접기·문맥 더 보기·정렬·필터. Notion: 제목 아래 "{#} backlinks" | obsidian.md/help/plugins/backlinks · notion.com/help/create-links-and-backlinks | 고른 칸·구성요소의 도면 위치, 근거, 같은 구성요소를 쓰는 다른 칸을 모으는 "관련 항목" 패널(U-14) |
| 마우스 오버 미리보기 | Obsidian Page preview: 탐색기·검색·백링크의 링크에 올리면 미리보기, 편집 화면에서는 Ctrl+호버. Linear: Space로 Peek | obsidian.md/help/plugins/page-preview · linear.app/docs/custom-views | 탐색기·관련 패널의 구간·구성요소에 미리보기 카드(U-08) |
| 그래프 필터·로컬 그래프 | Obsidian: Search·Tags·Attachments·Orphans 필터, 그룹 색, "Open local graph"와 depth 슬라이더(최대값은 문서에 없음) | obsidian.md/help/plugins/graph | ③ 로컬 그래프에 깊이 1~3 선택(U-17) |
| 상태 표시줄 | Obsidian: 오른쪽 아래 백링크 수·보기 모드·글자 수, Sync 아이콘 누르면 로그. Figma: 알릴 것이 있을 때만 표시 | obsidian.md/help/status-bar · help.figma.com/hc/en-us/articles/360039831974 | 값이 없으면 숨기고, 저장 상태·실패 수·진행률만(U-06) |
| 키보드 우선 | Linear: `?` 도움말, 한 글자 단축키(c 생성 등). Obsidian: 한 명령에 여러 단축키, 팔레트에 단축키 표시. Figma: Ctrl+Shift+? 단축키 패널 | linear.app/docs/joining-your-team-on-linear · obsidian.md/help/hotkeys · help.figma.com/hc/en-us/articles/360040328653 | 칸 이동·승인·기각을 한 글자 키로, `?`로 단축키 표(U-02) |
| 빈·오류 상태 | Notion: 백링크가 없으면 아무것도 안 보임, "Hide when empty". VS Code: 빈 창에서 보조 사이드바 숨김. 로딩 화면(스켈레톤)은 5개 도구 모두 문서에서 찾지 못함 | notion.com/help/intro-to-databases · code.visualstudio.com/docs/configure/custom-layout | 빈 목록 상자를 없애고 한 줄 안내 + 다음 동작 버튼(U-09) |
| 토스트·실행 취소 | VS Code: 알림 토스트 오른쪽 아래, 위치 변경 가능. Linear: Cmd/Ctrl+Z로 이동 되돌리기(일부 필드는 복원 안 됨). Obsidian: Ctrl+Z / Ctrl+Shift+Z | code.visualstudio.com/docs/configure/custom-layout · linear.app/docs/creating-issues · obsidian.md/help/editing-shortcuts | 승인·기각·병합 뒤 "실행 취소" 토스트(U-07) |
| 밝은·어두운 테마 | Obsidian: light/dark, 기본은 OS. VS Code: Ctrl+K Ctrl+T, OS 따라 자동 전환. Figma: light/dark/system, 기기별 저장 | obsidian.md/help/appearance · code.visualstudio.com/docs/configure/themes · help.figma.com/hc/en-us/articles/5576781786647 | 지금은 밝은 테마 유지, 어두운 테마는 C안 토큰으로 나중에(U-22) |
| 최소 장식 | VS Code: Zen 모드, Compact 밀도. Figma: Ctrl+Shift+\로 양쪽 패널 접기. Notion: 인라인 컨트롤은 마우스를 올려야 보임 | code.visualstudio.com/docs/getstarted/userinterface · help.figma.com/hc/en-us/articles/360039831974 · notion.com/help/intro-to-databases | 도면 위 떠 있는 상자를 접힌 칩으로, 행 동작은 선택한 행에만(U-12, U-21) |

## 2. HAZOP·PHA 소프트웨어 공개 화면

| 도구 | 워크시트 열 | 검토구간(HAZOP 노드) 탐색 | P&ID 연동 | 생산성 기능 | 출처 |
| --- | --- | --- | --- | --- | --- |
| Sphera PHA-Pro 8 | Deviations → Causes → Consequences → CAT → S → Safeguards → Current Risk(L, RR) → Recommendations. 상단에 Node 드롭다운, 도면 번호, 설계조건 칸 | 왼쪽 세로 메뉴 + 상단 탭. 트리는 확인 못함 | 공식 문구는 "Dynamic linking between diagrams and worksheets". 공개 화면에서는 도면 번호 칸만 확인 | AutoType, 복사, 체크리스트 2,500개, 과거 평가 재사용. 권고 요약에 "Place(s) Used"(권고가 나온 행) 열 | youtube.com/watch?v=jfCmCVNGgaU(RMPCorp, 25:25) · sphera.com 2025 브로셔 PDF 3쪽 |
| Primatech PHAWorks RA | Causes(Frequency) → Consequences → Safeguards(보호수단: Type, IPL, PFD) → Enablers → Risk After Safeguards(S, L, R) → Scenario Risk. 권고는 별도 탭 | 왼쪽 Navigation 패널(HAZOP 노드(이 앱의 검토구간)·변수·가이드워드·편차 목록), 상단 탭 15개 | "Drawings: click to choose drawings" 선택 칸, 하이퍼링크 | Quick Entry, Quick Copy, 드래그 앤 드롭, Linked entries, 찾기·바꾸기, 실행 취소 | primatech.com/images/docs/phaworks-ra-edition-overview.pdf |
| Kenexis Open-PHA | Deviation → Cause → Consequence → CAT → Safeguards(Type, Tag, IPL) → S → L → RR → LOPA/ALARP Required → Recommendation | 탭 이동, 행 번호 계층형(1.2.3). 권고·보호수단 목록의 참조를 누르면 해당 시나리오로 이동 | 문서 목록에 도면 번호·개정·링크를 두고 노드에 연결 | Deep Copy, 라이브러리, 실행 취소 100단계. 단축키 표 공개: F1–F10 탭 이동, Ctrl+Enter 새 행, Ctrl+↑/↓ 행 이동, Ctrl+H 단축키 지도 | kenexis.com/software/openpha · Open-PHA User Manual R5.15 부록 A |
| xSeriCon Vizop | Causes → Consequences → Safeguards → 위험순위. 권고는 각 항목에 붙는 주석 | 상단 드롭다운 + 좌우 화살표로 편차 이동, 여러 창 실시간 동기화 | P&ID 위 장치를 누르면 태그가 워크시트로 들어감. 도면 ↔ 워크시트 양방향 찾기 | 기본 시나리오 DB 1,000개, Excel 입출력, 자동 저장, 실행 취소 | xsericon.com/vizop · VIZOP User Guide H6장 |

## 3. 이 앱에 주는 시사점

1. 네 HAZOP 도구 모두 워크시트를 넓은 표로 쓰고, 위험도·권고를 행 단위로 둔다. 이 앱의 ⑤처럼 행렬과 워크시트를 좌우로 나누면 둘 다 좁아진다(W-2). 위아래 배치가 맞다 [추론].
2. "같은 항목이 어디에 쓰였는가"를 보여 주는 기능이 공통이다. PHA-Pro의 Place(s) Used, PHAWorks의 Linked entries, Open-PHA의 참조 이동이 그 예다. 옵시디언 백링크와 같은 발상이므로 "관련 항목" 패널 근거로 쓴다.
3. 키보드 조작은 Open-PHA만 단축키 표를 공개했다. Linear·Obsidian 방식(팔레트 + 한 글자 키 + `?` 표)을 HAZOP 워크시트에 적용한 공개 사례는 찾지 못했다. 이 앱이 차별화할 수 있는 부분이다 [추론].
4. 도면과 워크시트를 양방향으로 오가는 기능은 Vizop만 공개 화면으로 확인했다. 이 앱은 이미 도면·구간·지식그래프 자료를 가지고 있어서 같은 연결을 만들 재료가 있다.

## 직접 확인할 부분

- PHA-Pro 열 구성은 컨설팅사 템플릿 화면이다. 기본 템플릿과 다를 수 있다.
- Figma Actions 메뉴 단축키는 문서마다 Ctrl+K와 Ctrl+/로 다르게 적혀 있다. 이 앱 결정에는 쓰지 않았다.
- 2026-11-07 기준 문서다. 이후 바뀔 수 있다.
