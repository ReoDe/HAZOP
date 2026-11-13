// 도면 자리. 도면 구성요소(canvas/sheet.js, s-viewer가 만듦)가 있으면 그것을 쓰고, 아직 없으면 SVG 그림만 보이는 대역을 쓴다.
// 경계는 canvas/README.md: props(sheet, mode, selection, marks, layers, command, viewport)와 이벤트 콜백.
import { html } from "./ui/html.js";
import { useEffect, useState } from "../vendor/hooks.module.js";
import { store, useStore } from "./store.js";
import { ui } from "./bridge.js";
import { Icon } from "./ui/icon.js";
import { Btn } from "./ui/parts.js";
import * as R from "./panels/results_state.js";
import { NodeOverlay, useNodeCanvas } from "./canvas/nodes_canvas.js";
import { CleanOverlay, useCleanCanvas } from "./canvas/clean_ui.js";
import { SheetConfirm } from "./sheet_confirm.js";

let SheetComponent = null;
let tried = false;

async function loadCanvas() {
  if (tried) return SheetComponent;
  tried = true;
  try {
    const mod = await import("./canvas/sheet.js");
    SheetComponent = mod.Sheet || mod.default || null;
  } catch (e) {
    SheetComponent = null;
  }
  return SheetComponent;
}

function Fallback({ sheet }) {
  return html`<div class="canvas" aria-label="도면"><img class="sheet-img" alt="도면" src=${"/api/sheet/" + sheet + ".svg"}
    style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain" />
    <div class="float chipbar"><span class="muted" style="font-size:var(--fs-sm)">도면 구성요소를 준비 중이라 그림만 보입니다.</span></div></div>`;
}

/** 도면에서 구성요소를 누르면 뜨는 말풍선: 태그와 종류, 그 구성요소의 소속 구간 -> 칸 -> 권고 추적(INTENT §3.6)으로 가는 단추. */
function ItemBubble() {
  const b = useStore((s) => s.bubble);
  if (!b) return null;
  const r = b.rect || {};
  const style = "left:" + Math.max(8, Math.round((r.x || 0) + (r.w || r.width || 0) + 8)) + "px;top:" + Math.max(8, Math.round(r.y || 0)) + "px";
  const trace = () => { store.set({ bubble: null, panel: "results" }); R.loadTrace({ sheet: b.sheet, local: b.id }); };
  return html`<div class="float bubble" role="dialog" aria-label="구성요소" style=${style}>
    <div><b>${b.tag || b.id}</b>${b.kind ? html` <span class="muted small">${b.kind}</span>` : null}</div>
    <div class="acts-row"><${Btn} sm=${true} label="분석 결과 추적" title="소속 구간, 그 구간의 칸과 권고를 따라갑니다" onClick=${trace}>분석 결과 추적<//>
      <${Btn} sm=${true} kind="ghost" icon="x" label="말풍선 닫기" onClick=${() => store.set({ bubble: null })} /></div></div>`;
}

export function SheetHost() {
  const sheet = useStore((s) => s.sheet);
  const marks = useStore((s) => s.marks);
  const command = useStore((s) => s.command);
  const layers = useStore((s) => s.layers);        // 채팅의 층 켜고 끄기(symbol·pipe·tag)가 도면에 내려간다
  const [Comp, setComp] = useState(() => SheetComponent);
  const cc = useCleanCanvas(sheet);          // 원본·정리 보기, 미확인 칩, 못 읽은 곳 말풍선(s-viewer의 clean_ui.js)
  const nc = useNodeCanvas(sheet, { onEsc: () => { if (!cc.closeIfOpen()) store.set({ marks: { rid: null, bySheet: {} } }); } });
  useEffect(() => { loadCanvas().then((c) => { if (c) setComp(() => c); store.set({ canvasReady: !!c }); }); }, []);
  if (!sheet) {
    return html`<div class="canvas"><div class="center-empty" style="position:absolute;inset:0;display:grid;place-items:center;color:var(--muted)">
      <div style="text-align:center"><${Icon} name="files" size=${28} /><p>왼쪽 메뉴의 도면에서 도면을 열거나<br />도면 파일을 끌어 놓으세요.</p></div></div></div>`;
  }
  if (!Comp) return html`<${Fallback} sheet=${sheet} />`;
  const items = (marks.bySheet && marks.bySheet[sheet]) || [];
  return html`<div class="canvas"><${Comp} sheet=${{ graph_id: sheet }} ...${nc.props} ...${cc.props} layers=${layers} onReady=${(g) => store.set({ readySheet: g })} marks=${items.map((m, i) => Object.assign({ id: (marks.rid || "m") + (i ? "#" + i : "") }, m))}
    command=${command} onItemClick=${(d) => { ui("itemClick", { id: d.id }); store.set({ bubble: { sheet, id: d.id, tag: d.tag, kind: d.kind, rect: d.rect } }); }} /><${NodeOverlay} /><${CleanOverlay} /><${SheetConfirm} /><${ItemBubble} /></div>`;
}
