# 그리는 기호 한 벌 (drawing-symbols)

정리된 보기(`docs/design/app-shell-web.md` §10)가 읽은 결과를 다시 그릴 때 쓰는 기호 그림이다. 인식 규칙인 기호 사전(`../symbols/`)과는 다르다. 사전은 '무엇이 이 `kind`인가'를 정하고, 여기는 그 `kind`를 '어떻게 그리는가'를 정한다. 둘을 잇는 고리는 `kind` 이름이다.

| 파일 | 내용 |
| --- | --- |
| `manifest.json` | 기호 목록. `kind`, `file`, `fit`(`keep` 가로세로 비 유지·상자 가운데 / `stretch` 상자에 꽉 채움), `ports`(연결점, 그림 좌표), `label`(태그 기본 자리), `flow_axis`(회전 0°일 때 흐름 방향) |
| `<kind>.svg` | 기호 하나. 밑줄은 하이픈으로 쓴다(`check_valve` → `check-valve.svg`) |

## 규칙

- **직접 그린 것만 둔다.** ISA-5.1·ISO 10628-2의 뜻(나비꼴 밸브 몸통, 원 계기, 체크밸브 삼각 등)을 따르되 다른 곳의 기호 파일을 복사하지 않는다. draw.io 기호는 참고로 볼 수는 있으나 파일 단위 라이선스를 확인하지 않았으므로 옮기지 않는다(규격 §10.3).
- SVG는 `viewBox="0 0 가로 세로"`에 `path`·`line`·`polyline`·`polygon`·`circle`·`rect`만 쓴다. 모두 `fill="none" stroke="currentColor"`다. 글자·그림·스크립트·외부 참조·`style`은 쓰지 않는다. 선 굵기는 그릴 때 정한다(확대해도 같게).
- 가로 흐름을 기본으로 그린다. 세로나 거꾸로는 그릴 때 `orient`로 돌린다.
- `tee`는 그림이 없다(`junction: true`). 배관이 셋 이상 만나는 점에 점을 찍는다.
- `generic`은 그림이 없는 `kind`의 자리표다(둥근 네모, 머리글자는 그릴 때 얹는다).
- 새 `kind`가 기호 사전에 생기면 같은 날 그림 하나를 더한다. `tests/test_drawing_symbols.py`가 사전의 `kind`와 이 목록을 대조해 빠진 것을 알린다.

## 만들기

웹은 이 폴더를 직접 읽지 않고 `hazop/shell/web/js/canvas/symbols.json`을 읽는다. 그림이나 목록을 고치면 다시 만든다.

```bash
python scripts/build_drawing_symbols.py
```
