// 도면 자리. 도면 구성요소(canvas/sheet.js, s-viewer가 만듦)가 있으면 그것을 쓰고, 아직 없으면 SVG 그림만 보이는 대역을 쓴다.
// 경계는 canvas/README.md: props(sheet, mode, selection, marks, layers, command, viewport)와 이벤트 콜백.
import { html } from "./ui/html.js";
import { useEffect, useState } from "../vendor/hooks.module.js";
import { store, useStore } from "./store.js";
import { ui } from "./bridge.js";
import { Icon } from "./ui/icon.js";

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

export function SheetHost() {
  const sheet = useStore((s) => s.sheet);
  const marks = useStore((s) => s.marks);
  const command = useStore((s) => s.command);
  const [Comp, setComp] = useState(() => SheetComponent);
  useEffect(() => { loadCanvas().then((c) => { if (c) setComp(() => c); store.set({ canvasReady: !!c }); }); }, []);
  if (!sheet) {
    return html`<div class="canvas"><div class="center-empty" style="position:absolute;inset:0;display:grid;place-items:center;color:var(--muted)">
      <div style="text-align:center"><${Icon} name="files" size=${28} /><p>왼쪽 메뉴의 도면에서 도면을 열거나<br />도면 파일을 끌어 놓으세요.</p></div></div></div>`;
  }
  if (!Comp) return html`<${Fallback} sheet=${sheet} />`;
  const items = (marks.bySheet && marks.bySheet[sheet]) || [];
  return html`<${Comp} sheet=${{ graph_id: sheet }} mode="pan" selection=${[]} marks=${items.map((m, i) => Object.assign({ id: (marks.rid || "m") + (i ? "#" + i : "") }, m))}
    command=${command} onSelection=${(d) => ui("selectionChanged", d)} onItemClick=${(d) => ui("itemClick", { id: d.id })} onEsc=${() => store.set({ marks: { rid: null, bySheet: {} } })} />`;
}
