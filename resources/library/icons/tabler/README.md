# resources/library/icons/tabler — 화면 아이콘

화면(Qt 위젯·뷰어·채팅 카드)에 쓰는 선 아이콘이다. 코드로 하나하나 그리지 않고 Tabler Icons 3.51.0(MIT)에서 쓰는 것만 골라 원본 그대로 둔다. 배포본에 폴더째 묶인다.

- 출처: https://registry.npmjs.org/@tabler/icons/-/icons-3.51.0.tgz (받은 파일 SHA-256 `b30108713d3fa60aee862c2a133225da8e0f309be0708fe2925763ff810c766c`), `icons/outline/<이름>.svg`
- 가져온 날: 2026-11-13. 아이콘마다 SHA-256은 `manifest.json`에 있다.
- 라이선스 원문: `licenses/tabler-icons/LICENSE`(MIT). 고지 목록은 `licenses/README.md`.
- 불러오기: `hazop/app/icons.py`의 `icon(이름, color, size)`(Qt), `svg_inline(이름)`(웹). 색은 디자인 토큰 이름이나 `#RRGGBB`다.

## 무엇을 넣는가

- 화면에서 실제로 쓰는 Tabler 아이콘 SVG 원본과 목록 `manifest.json`. 아래 표의 모든 이름이 목록에 있고, 표에 없는 아이콘은 두지 않는다.

| 이름 | 쓰는 곳 |
| --- | --- |
| `alert-triangle` | 답 카드의 경고 줄, 경고 배너 |
| `arrow-back-up` | 실행 취소·되돌리기 단추 |
| `arrow-forward-up` | 다시 실행 단추 |
| `arrows-maximize` | 뷰어 도면 전체 맞춤 단추 |
| `arrows-move` | 뷰어 화면 옮기기 모드 |
| `check` | 적용됨·확인 표시, 미확인 확정 단추 |
| `chevron-down` | 펼침 화살표(펼친 상태) |
| `chevron-left` | 이전 |
| `chevron-right` | 펼침 화살표(접힌 상태), 다음 |
| `chevron-up` | 접힘 화살표(위로 접기) |
| `circle-check` | 검증 통과 칩, 확정된 구간 표시 |
| `copy` | 복사 |
| `cpu` | 채팅 모델 고르기(빠름·보통·깊게) |
| `device-floppy` | 저장 단추 |
| `eye` | 보이기 켜고 끄기(층·표시) |
| `file-export` | 내보내기 |
| `file-text` | 답 카드의 문서 칩(근거 문서) |
| `info-circle` | 안내 문구 앞 |
| `layout-sidebar-left-collapse` | 왼쪽 목록 접기 단추 |
| `layout-sidebar-left-expand` | 접힌 왼쪽 목록 펴기 단추 |
| `layout-sidebar-right-collapse` | 오른쪽 채팅 창 접기 단추 |
| `layout-sidebar-right-expand` | 접힌 채팅 창 펴기 단추 |
| `link` | 뷰어 짝 지정, 연결 추가 도구 |
| `link-off` | 뷰어 연결 끊기 |
| `lock` | 잠긴 구간 표시 |
| `lock-open` | 풀린 구간 표시 |
| `map-pin` | 도면 위 위치 표시, 뷰어 끝점 잇기 도구 |
| `message-circle` | 채팅 탭 이름표, 답 카드 머리 |
| `message-plus` | 새 대화 단추 |
| `minus` | 고른 것에서 빼기 |
| `pencil` | 뷰어 편집 단추 |
| `player-stop` | 답 멈추기 단추 |
| `plus` | 고른 것에 더하기, 뷰어 기기 추가 도구 |
| `pointer` | 뷰어 선택 도구 |
| `refresh` | 다시 읽기·새로 고침 |
| `route` | 답 카드의 경로 칩, 뷰어 경로 그리기 도구 |
| `ruler-2` | 답 카드의 도면 칩(근거 도면) |
| `search` | 찾기 입력 칸 |
| `select` | 뷰어 네모로 끌어 고르기 모드 |
| `send` | 채팅 보내기 단추 |
| `settings` | 설정 |
| `sparkles` | AI가 만든 것 표시 |
| `table` | 답 카드의 결과 칸 칩, 표 보기 |
| `trash` | 삭제 단추 |
| `vector-triangle` | 검토구간 칩, 구간 만들기 |
| `x` | 닫기, 입력 지우기 |
| `zoom-in` | 뷰어 확대 단추 |
| `zoom-out` | 뷰어 축소 단추 |
| `zoom-scan` | 도면에서 이 위치 확대해 보기 |

## 넣지 않는 것

- 쓰지 않는 아이콘. 필요하면 받은 원본(Tabler 패키지의 `icons/outline/`)에서 더한다.
- 우리가 그린 아이콘이나 고친 SVG. 원본과 한 바이트라도 다르면 `tests/test_icons.py`가 실패한다. 다른 모양이 필요하면 다른 원본 아이콘을 고른다.
- 라이선스 원문은 `licenses/tabler-icons/`에 둔다.

## 이름 형식

`<원본 이름>.svg`(소문자 kebab-case, 원본 `icons/outline/` 이름 그대로. 예 `layout-sidebar-right-collapse.svg`). 목록은 `manifest.json`, 줄 끝 변환 방지는 `.gitattributes`.

## 주인

총괄이 승인한다. 아이콘을 더하거나 빼면 `manifest.json`(해시)과 아래 사용처 표를 함께 고치고 `tests/test_icons.py`가 통과해야 한다. 판을 올리면 목록의 판·받은 파일 해시·`licenses/` 고지도 함께 바꾼다.

## 폐기 기준

화면 어디에서도 쓰지 않게 된 아이콘은 코드에서 뺀 뒤에 파일·목록·표에서 함께 지운다. 사용처를 모르는 아이콘은 지우지 않고 표의 '쓰는 곳'을 먼저 확인한다.

