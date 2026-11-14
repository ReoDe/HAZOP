// 도면 구성요소 말풍선에 넣는 한 줄(완료 목록 3 B7, 이전 화면의 '관련 항목' 대신): 지식그래프에서 보기(걸린 지식 수)와
// 이 구성요소를 쓰는 분석 칸 n. 칸 수를 누르면 말풍선 안에 칸 목록을 펼치고, 칸을 누르면 분석 결과 패널에서 그 칸을 연다.
// 말풍선 틀(sheet_host.js ItemBubble)은 틀 담당 파일이라, 그쪽은 이 부품을 한 줄로 넣기만 한다: <${BubbleLinks} sheet=${b.sheet} id=${b.id} />
// 웹은 도면 graph_id와 구성요소 local_id만 보낸다(경로 없음). 칸 이름·지식 이름은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { store } from "../store.js";
import { read } from "../bridge.js";
import * as K from "./kg_state.js";
import * as R from "./results_state.js";

// 글꼴·밑줄 모양은 지식그래프 패널 CSS(kg.css)의 .kg-blink를 쓴다. 패널을 아직 열지 않았어도 읽히게 여기서도 건다
const cssHref = new URL("kg.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector("link[data-kg-css]")) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-kg-css", "");
  document.head.appendChild(l);
}

export function BubbleLinks({ sheet, id }) {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let alive = true;
    setD(null); setOpen(false);
    if (sheet && id) {
      read("kg/component?sheet=" + encodeURIComponent(sheet) + "&local=" + encodeURIComponent(id))
        .then((r) => { if (alive) setD(r); }).catch(() => { if (alive) setD({ found: false }); });
    }
    return () => { alive = false; };
  }, [sheet, id]);
  if (!d || !d.found) return null;
  const k = d.knowledge, c = d.cells;
  const toKg = () => { store.set({ bubble: null, panel: "kg" }); K.wire(); K.loadSummary().then(() => K.focus(d.id)); };
  const toCell = (x) => { store.set({ bubble: null, panel: "results" }); R.openCell(x.node_id, x.deviation_id); };
  const kgTitle = k.count ? "걸린 지식: " + k.text + (k.unchecked ? " (사람 확인 전 " + k.unchecked + ")" : "") : "이 구성요소에 걸린 지식이 아직 없습니다";
  return html`<div class="bubble-links small">
    <div class="acts-row">${d.in_graph ? html`<button type="button" class="kg-blink" title=${kgTitle} onClick=${toKg}>지식그래프에서 보기${k.count ? " · 지식 " + k.count : ""}</button>` : null}
      ${c.count ? html`<button type="button" class="kg-blink" aria-expanded=${open ? "true" : "false"} title="이 구성요소를 원인 위치·영향 대상·보호수단으로 가리키는 분석 칸"
        onClick=${() => setOpen(!open)}>이 구성요소를 쓰는 칸 ${c.count}</button>` : html`<span class="muted">쓰는 분석 칸 없음</span>`}</div>
    ${open ? html`<div class="bubble-cells" role="list">${c.items.map((x) => html`<button type="button" class="kg-blink" role="listitem" key=${x.node_id + x.deviation_id}
      onClick=${() => toCell(x)}>${x.label}<span class="muted"> · ${x.roles.join("·")}</span></button>`)}
      ${c.count > c.items.length ? html`<span class="muted">나머지 ${c.count - c.items.length}칸은 분석 결과에서 보세요.</span>` : null}</div>` : null}</div>`;
}
