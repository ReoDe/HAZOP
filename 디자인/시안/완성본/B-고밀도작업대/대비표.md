# B안 · 고밀도 작업대 대비 계산

`build.py`가 WCAG 2.1 상대 휘도 공식으로 계산한 값이다. 글자는 4.5:1, 그래픽(테두리·도면 선·구간 색)은 3:1이 기준이다.

| 쌍 | 전경 | 배경 | 대비 | 기준 | 판정 |
| --- | --- | --- | ---: | ---: | --- |
| 본문 글자 / 바탕 | `ink` #0f1419 | `bg` #e9ebee | 15.50 | 4.5 | 통과 |
| 본문 글자 / 패널 | `ink` #0f1419 | `surface` #fbfbfc | 17.90 | 4.5 | 통과 |
| 보조 글자 / 패널 | `ink-2` #2a313b | `surface` #fbfbfc | 12.68 | 4.5 | 통과 |
| 흐린 글자 / 패널 | `muted` #525b67 | `surface` #fbfbfc | 6.66 | 4.5 | 통과 |
| 흐린 글자 / 바탕 | `muted` #525b67 | `bg` #e9ebee | 5.76 | 4.5 | 통과 |
| 흐린 글자 / 보조 패널 | `muted` #525b67 | `surface-2` #f1f2f4 | 6.14 | 4.5 | 통과 |
| 강조 글자(링크) / 패널 | `ui` #0a5fc2 | `surface` #fbfbfc | 5.92 | 4.5 | 통과 |
| 선택 행 글자 / 선택 바탕 | `ui-ink` #0a4a96 | `ui-weak` #e2edfb | 7.29 | 4.5 | 통과 |
| 주 버튼 글자 / 강조 채움 | `on-fill` #ffffff | `ui` #0a5fc2 | 6.12 | 4.5 | 통과 |
| 통과 글자 / 통과 바탕 | `ok-ink` #0f4f28 | `ok-bg` #e2f3e8 | 8.40 | 4.5 | 통과 |
| 승인 칩 글자 / 승인 채움 | `on-ok` #ffffff | `ok` #127238 | 6.02 | 4.5 | 통과 |
| 경고 글자 / 경고 바탕 | `warn-ink` #74430a | `warn-bg` #fdf0d2 | 7.28 | 4.5 | 통과 |
| 경고 글자 / 패널 | `warn-ink` #74430a | `surface` #fbfbfc | 7.96 | 4.5 | 통과 |
| 오류 글자 / 오류 바탕 | `err-ink` #a8201a | `err-bg` #fbe7e6 | 6.12 | 4.5 | 통과 |
| 오류 글자 / 패널 | `err-ink` #a8201a | `surface` #fbfbfc | 7.03 | 4.5 | 통과 |
| AI 초안 글자 / 빗금 진한 칸 | `ai-ink` #3a414b | `ai-b` #e3e6ea | 8.23 | 4.5 | 통과 |
| 위험 수용 글자 / 바탕 | `risk-ok-ink` #374151 | `risk-ok-bg` #eef0f3 | 9.03 | 4.5 | 통과 |
| 위험 조건부 글자 / 바탕 | `risk-cond-ink` #78350f | `risk-cond-bg` #fde68a | 7.28 | 4.5 | 통과 |
| 위험 불허 글자 / 바탕 | `risk-deny-ink` #ffffff | `risk-deny-bg` #991b1b | 8.31 | 4.5 | 통과 |
| 탐색 글자 / 탐색 바탕 | `nav-ink` #e6e9ee | `nav-bg` #23282f | 12.19 | 4.5 | 통과 |
| 탐색 흐린 글자 / 탐색 바탕 | `nav-muted` #aab2bd | `nav-bg` #23282f | 6.93 | 4.5 | 통과 |
| 탐색 선택 글자 / 선택 바탕 | `nav-active-ink` #ffffff | `nav-active-bg` #3b4452 | 9.84 | 4.5 | 통과 |
| 도면 글자 / 도면 바탕 | `draw-ink` #1a1f26 | `canvas` #fdfdfd | 16.28 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간1 | `on-seg` #ffffff | `seg1` #0b7285 | 5.59 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간2 | `on-seg` #ffffff | `seg2` #6d28d9 | 7.10 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간3 | `on-seg` #ffffff | `seg3` #b54708 | 5.43 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간4 | `on-seg` #ffffff | `seg4` #a61e4d | 7.21 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간5 | `on-seg` #ffffff | `seg5` #3f6212 | 7.08 | 4.5 | 통과 |
| 입력란 테두리 / 패널 | `line-strong` #7f8793 | `surface` #fbfbfc | 3.51 | 3 | 통과 |
| 포커스·선택 테두리 / 패널 | `ui` #0a5fc2 | `surface` #fbfbfc | 5.92 | 3 | 통과 |
| AI 초안 점선 / 패널 | `ai-line` #7f8793 | `surface` #fbfbfc | 3.51 | 3 | 통과 |
| 경고 테두리 / 패널 | `warn-line` #a8740d | `surface` #fbfbfc | 3.93 | 3 | 통과 |
| 도면 배관선 / 도면 바탕 | `draw-line` #2f3742 | `canvas` #fdfdfd | 11.82 | 3 | 통과 |
| 도면 신호선 / 도면 바탕 | `draw-sig` #66707c | `canvas` #fdfdfd | 4.95 | 3 | 통과 |
| 노드 equipment / 도면 바탕 | `k-equipment` #1d4ed8 | `canvas` #fdfdfd | 6.59 | 3 | 통과 |
| 노드 valve / 도면 바탕 | `k-valve` #0f766e | `canvas` #fdfdfd | 5.38 | 3 | 통과 |
| 노드 instrument / 도면 바탕 | `k-instrument` #0b7fb5 | `canvas` #fdfdfd | 4.38 | 3 | 통과 |
| 노드 piping / 도면 바탕 | `k-piping` #5b5fe0 | `canvas` #fdfdfd | 4.97 | 3 | 통과 |
| 노드 doc / 도면 바탕 | `k-doc` #9a5b06 | `canvas` #fdfdfd | 5.33 | 3 | 통과 |
| 노드 basis / 도면 바탕 | `k-basis` #7a5c00 | `canvas` #fdfdfd | 6.15 | 3 | 통과 |
| 노드 failure / 도면 바탕 | `k-failure` #c0262d | `canvas` #fdfdfd | 5.80 | 3 | 통과 |
| 관계 physical / 도면 바탕 | `r-physical` #15803d | `canvas` #fdfdfd | 4.93 | 3 | 통과 |
| 관계 signal / 도면 바탕 | `r-signal` #7c3aed | `canvas` #fdfdfd | 5.60 | 3 | 통과 |
| 관계 measurement / 도면 바탕 | `r-measurement` #b86304 | `canvas` #fdfdfd | 4.28 | 3 | 통과 |
| 관계 unresolved / 도면 바탕 | `r-unresolved` #dc2626 | `canvas` #fdfdfd | 4.75 | 3 | 통과 |
| 경로 강조 / 도면 바탕 | `hl-path` #d9480f | `canvas` #fdfdfd | 4.23 | 3 | 통과 |
| 구간1 색 / 도면 바탕 | `seg1` #0b7285 | `canvas` #fdfdfd | 5.49 | 3 | 통과 |
| 구간2 색 / 도면 바탕 | `seg2` #6d28d9 | `canvas` #fdfdfd | 6.98 | 3 | 통과 |
| 구간3 색 / 도면 바탕 | `seg3` #b54708 | `canvas` #fdfdfd | 5.34 | 3 | 통과 |
| 구간4 색 / 도면 바탕 | `seg4` #a61e4d | `canvas` #fdfdfd | 7.08 | 3 | 통과 |
| 구간5 색 / 도면 바탕 | `seg5` #3f6212 | `canvas` #fdfdfd | 6.96 | 3 | 통과 |
