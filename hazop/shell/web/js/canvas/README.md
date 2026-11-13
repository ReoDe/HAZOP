# 도면 구성요소 경계 (1단계, 2026-11-13)

틀 세션(`s-frame`)과 도면 세션(`s-viewer`)이 맞추는 한 쪽짜리 약속이다. 규격은 [`app-shell-web.md`](../../../../../docs/design/app-shell-web.md) §3.1·§5.2~5.4, 채팅 쪽 표시 함수 이름은 [`chat-panel.md`](../../../../../docs/specs/chat-panel.md) §6이다. 경계를 바꾸려면 이 파일을 먼저 고치고 보고에 적는다.

## 파일과 주인

| 파일 | 내용 | 주인 |
| --- | --- | --- |
| `sheet.js` | `Sheet` 구성요소(Preact). 도면 한 장을 그리고 입력을 받는다 | s-viewer |
| `index.js` | 공간 색인 `SpatialIndex`(칸 64px). 누르기·네모 고르기·마우스 올림이 쓴다 | s-viewer |
| `marks.js` | 표시 그리기(`mark`·`path`), 네모 고르기 막대, 범례 | s-viewer |
| `../store.js` · `../bridge.js` | 저장소·엔진 잇기(아래 '저장소 키') | s-frame |

구현은 Preact + htm이다(`vendor/`의 `preact.module.js`, `hooks.module.js`, `htm.module.js`). 상태 관리 라이브러리는 없다.

## 입력 자료: `hazop-app://api/sheet/<graph_id>`

엔진(`hazop/shell/api.py`)이 JSON 한 개를 준다. 도면 SVG는 `<image>`로 넣는다(구성요소마다 DOM을 두지 않는다).

```json
{"graph_id": "graph-SNP-M-102", "rev": 7, "width": 1684, "height": 1190,
 "svg": "hazop-app://api/sheet/graph-SNP-M-102.svg",
 "items": [{"id": "n17", "kind": "pressurizer", "category": "equipment", "tag": "RC-PZ01",
            "layer": "symbol", "bbox": [x0, y0, x1, y1], "polyline": null,
            "classification": "classified", "unknown": false, "node_id": "S1"}],
 "links": [{"id": "n40", "peer_graph_id": "graph-SNP-M-101", "peer_id": "n12", "status": "linked"}]}
```

- `id`는 **도면 안 `local_id`**다(채팅 규격 §6.1과 같다). 프로젝트 ID로의 변환은 엔진(`hazop/chat/view.py`)이 한다. 웹은 프로젝트 ID를 모른다.
- `layer`는 `symbol`·`pipe`·`tag`. 배관(`pipe`)은 `polyline`([[x,y],…])을 가진다. 좌표는 모두 SVG 사용자 단위다.
- `items` 모양이 지금 `hazop/viewer/template.html`이 읽는 자료와 다르면 s-viewer가 이 파일에 실제 모양을 적고 알린다. 엔진 쪽이 그 모양으로 맞춘다.

## `<Sheet>` 입력(props)

| 이름 | 형 | 뜻 |
| --- | --- | --- |
| `sheet` | `{graph_id, rev}` | 보여 줄 도면. 바뀌면 `api/sheet/<id>`를 다시 읽는다 |
| `mode` | `"pan"` \| `"pick"` | 이동(V, 기본) / 네모로 고르기(S) |
| `selection` | `string[]` | 고른 local_id(제어 입력). 바꾸는 것은 `onSelection`으로 알린다 |
| `marks` | `Mark[]` | 겹쳐 그릴 표시(아래). 요청 ID(`id`)가 같으면 덮어쓴다 |
| `segments` | `{node_id, ids, color}[]` | 구간 강조(2단계). 없으면 비움 |
| `layers` | `{symbol, pipe, tag}` 불리언 | 층 켜고 끄기 |
| `command` | `{seq, type, ids?, pad?}` | 한 번 하는 명령. `type`은 `zoomTo`·`fit`·`clearMarks`. `seq`가 바뀌면 실행 |
| `viewport` | `{x, y, k}` | 이동·확대(제어 입력). 바꾸는 것은 `onViewport`로 알린다 |

`Mark`는 채팅 규격 §6.1·§6.2와 같은 뜻이다.

```js
{id: "chat-q1", op: "mark", groups: [{ids: [...], style: "focus|path|cause|safeguard|warn|muted|seg:<0-11>", label: null}],
 dim_others: true, center: false}
{id: "chat-q1", op: "path", steps: [{id: "n1", flow: "with|against|unknown|null"}], style: "path", numbered: true}
```

한 요청에 항목이 여럿이면 `id`에 `#1`, `#2`를 붙여 보낸다(`ViewerHost`와 같다). 그릴 수 없는 ID는 `onMarkResult`로 알린다.

## `<Sheet>` 이벤트(콜백 props)

| 이름 | 인자 | 언제 |
| --- | --- | --- |
| `onReady` | `graph_id` | 자료를 읽고 첫 그리기를 마쳤을 때(`sheetReady`와 같다) |
| `onItemClick` | `{id, kind, tag, rect: {x,y,w,h}(화면 좌표), via: "click"}` | 이동 모드에서 구성요소를 눌렀다. 말풍선을 여는 쪽이 받는다 |
| `onItemDblClick` | `{id}` | 두 번 눌렀다(그 구성요소에 맞춰 확대는 `Sheet`가 직접 한다) |
| `onHover` | `{id, rect}` 또는 `null` | 마우스 올림 |
| `onSelection` | `{selected, added, removed, via: "click"\|"box"\|"box_remove"\|"clear", truncated}` | 고른 것이 바뀌었다. 사용자 조작에서만(`selection` 속성으로 바꾼 것은 알리지 않는다). 2,000개를 넘으면 앞 2,000개만 보내고 `truncated: true` |
| `onViewport` | `{x, y, k}` | 이동·확대가 멈춘 뒤 |
| `onMarkResult` | `{id, missing: string[]}` | `marks` 처리 결과(`highlightResult`와 같다) |
| `onEsc` | 없음 | Esc를 눌렀다. 순서는 말풍선 닫기 → 표시 지우기 → 고른 것 비우기 → 이동 모드(규격 §3.1) |

고르기 기준은 규격 §3.1과 같다. 구성요소는 외곽 상자가 네모와 겹치면 고르고, 배관은 선이 네모를 지나면 고른다.

## 저장소 키 (`store.js`, 웹이 주인)

`canvas.sheet`, `canvas.mode`, `canvas.selection`, `canvas.marks`, `canvas.layers`, `canvas.viewport`, `canvas.command`. 틀(`main.js`)이 이 값들을 `<Sheet>`의 props로 내려보내고 콜백으로 올라온 값을 저장소에 쓴다. `Sheet`는 저장소를 직접 읽지 않는다(시험을 쉽게 하려는 것이다).

## 엔진으로 가는 길

`Sheet`는 엔진을 직접 부르지 않는다. 틀이 콜백을 받아 `bridge.js`로 `{"t":"ui","name":"selectionChanged","data":…}` 같은 메시지를 보낸다. 엔진이 웹으로 보내는 표시 요청(`mark`·`clear_marks`·`draw_path`·`set_select_mode`·`set_selection`·`selection`·`zoom_to`)은 틀이 위 props(`marks`·`command`·`mode`·`selection`)로 바꿔 내려보낸다.

## 시험

`hazop/shell/web/test/`의 `*.test.js`에 두고 `run.html`이 모은다. 공간 색인·네모 고르기 기준·표시 덮어쓰기·2,000개 자르기는 DOM 없이 부를 수 있게 순수 함수로 만든다.
