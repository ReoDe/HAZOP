# A안 · 밝은 미니멀 대비 계산

`build.py`가 WCAG 2.1 상대 휘도 공식으로 계산한 값이다. 글자는 4.5:1, 그래픽(테두리·도면 선·구간 색)은 3:1이 기준이다.

| 쌍 | 전경 | 배경 | 대비 | 기준 | 판정 |
| --- | --- | --- | ---: | ---: | --- |
| 본문 글자 / 바탕 | `ink` #111827 | `bg` #f5f6f8 | 16.41 | 4.5 | 통과 |
| 본문 글자 / 패널 | `ink` #111827 | `surface` #ffffff | 17.74 | 4.5 | 통과 |
| 보조 글자 / 패널 | `ink-2` #374151 | `surface` #ffffff | 10.31 | 4.5 | 통과 |
| 흐린 글자 / 패널 | `muted` #5b6472 | `surface` #ffffff | 5.98 | 4.5 | 통과 |
| 흐린 글자 / 바탕 | `muted` #5b6472 | `bg` #f5f6f8 | 5.53 | 4.5 | 통과 |
| 흐린 글자 / 보조 패널 | `muted` #5b6472 | `surface-2` #f2f4f7 | 5.43 | 4.5 | 통과 |
| 강조 글자(링크) / 패널 | `ui` #2556c8 | `surface` #ffffff | 6.47 | 4.5 | 통과 |
| 선택 행 글자 / 선택 바탕 | `ui-ink` #1b3f94 | `ui-weak` #edf2fd | 8.57 | 4.5 | 통과 |
| 주 버튼 글자 / 강조 채움 | `on-fill` #ffffff | `ui` #2556c8 | 6.47 | 4.5 | 통과 |
| 통과 글자 / 통과 바탕 | `ok-ink` #14532d | `ok-bg` #e6f5eb | 8.08 | 4.5 | 통과 |
| 승인 칩 글자 / 승인 채움 | `on-ok` #ffffff | `ok` #15803d | 5.02 | 4.5 | 통과 |
| 경고 글자 / 경고 바탕 | `warn-ink` #7c4a03 | `warn-bg` #fff3d6 | 6.71 | 4.5 | 통과 |
| 경고 글자 / 패널 | `warn-ink` #7c4a03 | `surface` #ffffff | 7.40 | 4.5 | 통과 |
| 오류 글자 / 오류 바탕 | `err-ink` #b42318 | `err-bg` #fdeceb | 5.75 | 4.5 | 통과 |
| 오류 글자 / 패널 | `err-ink` #b42318 | `surface` #ffffff | 6.57 | 4.5 | 통과 |
| AI 초안 글자 / 빗금 진한 칸 | `ai-ink` #3f4753 | `ai-b` #e8eaee | 7.79 | 4.5 | 통과 |
| 위험 수용 글자 / 바탕 | `risk-ok-ink` #374151 | `risk-ok-bg` #eef0f3 | 9.03 | 4.5 | 통과 |
| 위험 조건부 글자 / 바탕 | `risk-cond-ink` #78350f | `risk-cond-bg` #fde68a | 7.28 | 4.5 | 통과 |
| 위험 불허 글자 / 바탕 | `risk-deny-ink` #ffffff | `risk-deny-bg` #991b1b | 8.31 | 4.5 | 통과 |
| 탐색 글자 / 탐색 바탕 | `nav-ink` #111827 | `nav-bg` #ffffff | 17.74 | 4.5 | 통과 |
| 탐색 흐린 글자 / 탐색 바탕 | `nav-muted` #5b6472 | `nav-bg` #ffffff | 5.98 | 4.5 | 통과 |
| 탐색 선택 글자 / 선택 바탕 | `nav-active-ink` #ffffff | `nav-active-bg` #2556c8 | 6.47 | 4.5 | 통과 |
| 도면 글자 / 도면 바탕 | `draw-ink` #1f2937 | `canvas` #ffffff | 14.68 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간1 | `on-seg` #ffffff | `seg1` #0e7490 | 5.36 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간2 | `on-seg` #ffffff | `seg2` #7c3aed | 5.70 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간3 | `on-seg` #ffffff | `seg3` #c2410c | 5.18 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간4 | `on-seg` #ffffff | `seg4` #be185d | 6.04 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간5 | `on-seg` #ffffff | `seg5` #4d7c0f | 4.99 | 4.5 | 통과 |
| 입력란 테두리 / 패널 | `line-strong` #858d9b | `surface` #ffffff | 3.34 | 3 | 통과 |
| 포커스·선택 테두리 / 패널 | `ui` #2556c8 | `surface` #ffffff | 6.47 | 3 | 통과 |
| AI 초안 점선 / 패널 | `ai-line` #858d9b | `surface` #ffffff | 3.34 | 3 | 통과 |
| 경고 테두리 / 패널 | `warn-line` #b7791f | `surface` #ffffff | 3.64 | 3 | 통과 |
| 도면 배관선 / 도면 바탕 | `draw-line` #3b4351 | `canvas` #ffffff | 9.96 | 3 | 통과 |
| 도면 신호선 / 도면 바탕 | `draw-sig` #6b7280 | `canvas` #ffffff | 4.83 | 3 | 통과 |
| 노드 equipment / 도면 바탕 | `k-equipment` #1d4ed8 | `canvas` #ffffff | 6.70 | 3 | 통과 |
| 노드 valve / 도면 바탕 | `k-valve` #0f766e | `canvas` #ffffff | 5.47 | 3 | 통과 |
| 노드 instrument / 도면 바탕 | `k-instrument` #0b7fb5 | `canvas` #ffffff | 4.45 | 3 | 통과 |
| 노드 piping / 도면 바탕 | `k-piping` #5b5fe0 | `canvas` #ffffff | 5.05 | 3 | 통과 |
| 노드 doc / 도면 바탕 | `k-doc` #9a5b06 | `canvas` #ffffff | 5.42 | 3 | 통과 |
| 노드 basis / 도면 바탕 | `k-basis` #7a5c00 | `canvas` #ffffff | 6.25 | 3 | 통과 |
| 노드 failure / 도면 바탕 | `k-failure` #c0262d | `canvas` #ffffff | 5.90 | 3 | 통과 |
| 관계 physical / 도면 바탕 | `r-physical` #15803d | `canvas` #ffffff | 5.02 | 3 | 통과 |
| 관계 signal / 도면 바탕 | `r-signal` #7c3aed | `canvas` #ffffff | 5.70 | 3 | 통과 |
| 관계 measurement / 도면 바탕 | `r-measurement` #b86304 | `canvas` #ffffff | 4.35 | 3 | 통과 |
| 관계 unresolved / 도면 바탕 | `r-unresolved` #dc2626 | `canvas` #ffffff | 4.83 | 3 | 통과 |
| 경로 강조 / 도면 바탕 | `hl-path` #d9480f | `canvas` #ffffff | 4.30 | 3 | 통과 |
| 구간1 색 / 도면 바탕 | `seg1` #0e7490 | `canvas` #ffffff | 5.36 | 3 | 통과 |
| 구간2 색 / 도면 바탕 | `seg2` #7c3aed | `canvas` #ffffff | 5.70 | 3 | 통과 |
| 구간3 색 / 도면 바탕 | `seg3` #c2410c | `canvas` #ffffff | 5.18 | 3 | 통과 |
| 구간4 색 / 도면 바탕 | `seg4` #be185d | `canvas` #ffffff | 6.04 | 3 | 통과 |
| 구간5 색 / 도면 바탕 | `seg5` #4d7c0f | `canvas` #ffffff | 4.99 | 3 | 통과 |
