# C안 · 다크 대시보드 대비 계산

`build.py`가 WCAG 2.1 상대 휘도 공식으로 계산한 값이다. 글자는 4.5:1, 그래픽(테두리·도면 선·구간 색)은 3:1이 기준이다.

| 쌍 | 전경 | 배경 | 대비 | 기준 | 판정 |
| --- | --- | --- | ---: | ---: | --- |
| 본문 글자 / 바탕 | `ink` #e9eef4 | `bg` #0e1217 | 16.11 | 4.5 | 통과 |
| 본문 글자 / 패널 | `ink` #e9eef4 | `surface` #151b22 | 14.86 | 4.5 | 통과 |
| 보조 글자 / 패널 | `ink-2` #c5cdd8 | `surface` #151b22 | 10.81 | 4.5 | 통과 |
| 흐린 글자 / 패널 | `muted` #95a1b1 | `surface` #151b22 | 6.61 | 4.5 | 통과 |
| 흐린 글자 / 바탕 | `muted` #95a1b1 | `bg` #0e1217 | 7.17 | 4.5 | 통과 |
| 흐린 글자 / 보조 패널 | `muted` #95a1b1 | `surface-2` #1c242d | 5.98 | 4.5 | 통과 |
| 강조 글자(링크) / 패널 | `ui` #5ba4ff | `surface` #151b22 | 6.77 | 4.5 | 통과 |
| 선택 행 글자 / 선택 바탕 | `ui-ink` #a9cdff | `ui-weak` #14263d | 9.36 | 4.5 | 통과 |
| 주 버튼 글자 / 강조 채움 | `on-fill` #07111d | `ui` #5ba4ff | 7.41 | 4.5 | 통과 |
| 통과 글자 / 통과 바탕 | `ok-ink` #86e0a8 | `ok-bg` #10271a | 9.98 | 4.5 | 통과 |
| 승인 칩 글자 / 승인 채움 | `on-ok` #06130b | `ok` #3dbb6d | 7.71 | 4.5 | 통과 |
| 경고 글자 / 경고 바탕 | `warn-ink` #f2c063 | `warn-bg` #2c2009 | 9.48 | 4.5 | 통과 |
| 경고 글자 / 패널 | `warn-ink` #f2c063 | `surface` #151b22 | 10.31 | 4.5 | 통과 |
| 오류 글자 / 오류 바탕 | `err-ink` #ff9d96 | `err-bg` #2d1416 | 8.60 | 4.5 | 통과 |
| 오류 글자 / 패널 | `err-ink` #ff9d96 | `surface` #151b22 | 8.68 | 4.5 | 통과 |
| AI 초안 글자 / 빗금 진한 칸 | `ai-ink` #c2cad5 | `ai-b` #232b35 | 8.65 | 4.5 | 통과 |
| 위험 수용 글자 / 바탕 | `risk-ok-ink` #d4dbe4 | `risk-ok-bg` #232c37 | 10.12 | 4.5 | 통과 |
| 위험 조건부 글자 / 바탕 | `risk-cond-ink` #ffd98a | `risk-cond-bg` #4a3510 | 8.60 | 4.5 | 통과 |
| 위험 불허 글자 / 바탕 | `risk-deny-ink` #ffffff | `risk-deny-bg` #a32020 | 7.54 | 4.5 | 통과 |
| 탐색 글자 / 탐색 바탕 | `nav-ink` #e9eef4 | `nav-bg` #0a0d11 | 16.69 | 4.5 | 통과 |
| 탐색 흐린 글자 / 탐색 바탕 | `nav-muted` #95a1b1 | `nav-bg` #0a0d11 | 7.43 | 4.5 | 통과 |
| 탐색 선택 글자 / 선택 바탕 | `nav-active-ink` #ffffff | `nav-active-bg` #1d2b3c | 14.35 | 4.5 | 통과 |
| 도면 글자 / 도면 바탕 | `draw-ink` #dfe5ec | `canvas` #10161c | 14.35 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간1 | `on-seg` #0b0f14 | `seg1` #2dd4bf | 10.32 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간2 | `on-seg` #0b0f14 | `seg2` #a78bfa | 7.06 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간3 | `on-seg` #0b0f14 | `seg3` #fb923c | 8.49 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간4 | `on-seg` #0b0f14 | `seg4` #f472b6 | 7.26 | 4.5 | 통과 |
| 구간 꼬리표 글자 / 구간5 | `on-seg` #0b0f14 | `seg5` #a3e635 | 12.75 | 4.5 | 통과 |
| 입력란 테두리 / 패널 | `line-strong` #64748a | `surface` #151b22 | 3.64 | 3 | 통과 |
| 포커스·선택 테두리 / 패널 | `ui` #5ba4ff | `surface` #151b22 | 6.77 | 3 | 통과 |
| AI 초안 점선 / 패널 | `ai-line` #6b788a | `surface` #151b22 | 3.86 | 3 | 통과 |
| 경고 테두리 / 패널 | `warn-line` #c8922a | `surface` #151b22 | 6.27 | 3 | 통과 |
| 도면 배관선 / 도면 바탕 | `draw-line` #a3afbd | `canvas` #10161c | 8.17 | 3 | 통과 |
| 도면 신호선 / 도면 바탕 | `draw-sig` #7f8b9a | `canvas` #10161c | 5.26 | 3 | 통과 |
| 노드 equipment / 도면 바탕 | `k-equipment` #6ea6ff | `canvas` #10161c | 7.42 | 3 | 통과 |
| 노드 valve / 도면 바탕 | `k-valve` #2ccdb4 | `canvas` #10161c | 9.10 | 3 | 통과 |
| 노드 instrument / 도면 바탕 | `k-instrument` #4fc3f7 | `canvas` #10161c | 9.09 | 3 | 통과 |
| 노드 piping / 도면 바탕 | `k-piping` #a5a8ff | `canvas` #10161c | 8.36 | 3 | 통과 |
| 노드 doc / 도면 바탕 | `k-doc` #e7b157 | `canvas` #10161c | 9.38 | 3 | 통과 |
| 노드 basis / 도면 바탕 | `k-basis` #d9c36a | `canvas` #10161c | 10.37 | 3 | 통과 |
| 노드 failure / 도면 바탕 | `k-failure` #ff8a80 | `canvas` #10161c | 7.97 | 3 | 통과 |
| 관계 physical / 도면 바탕 | `r-physical` #4ade80 | `canvas` #10161c | 10.45 | 3 | 통과 |
| 관계 signal / 도면 바탕 | `r-signal` #b794f6 | `canvas` #10161c | 7.44 | 3 | 통과 |
| 관계 measurement / 도면 바탕 | `r-measurement` #f6ad55 | `canvas` #10161c | 9.56 | 3 | 통과 |
| 관계 unresolved / 도면 바탕 | `r-unresolved` #ff6b6b | `canvas` #10161c | 6.56 | 3 | 통과 |
| 경로 강조 / 도면 바탕 | `hl-path` #ff9a3c | `canvas` #10161c | 8.62 | 3 | 통과 |
| 구간1 색 / 도면 바탕 | `seg1` #2dd4bf | `canvas` #10161c | 9.78 | 3 | 통과 |
| 구간2 색 / 도면 바탕 | `seg2` #a78bfa | `canvas` #10161c | 6.69 | 3 | 통과 |
| 구간3 색 / 도면 바탕 | `seg3` #fb923c | `canvas` #10161c | 8.04 | 3 | 통과 |
| 구간4 색 / 도면 바탕 | `seg4` #f472b6 | `canvas` #10161c | 6.87 | 3 | 통과 |
| 구간5 색 / 도면 바탕 | `seg5` #a3e635 | `canvas` #10161c | 12.07 | 3 | 통과 |
