// 도면 자리. 도면 구성요소(canvas/sheet.js, s-viewer가 만듦)가 있으면 그것을 쓰고, 아직 없으면 SVG 그림만 보이는 대역을 쓴다.
// 경계는 canvas/README.md: props(sheet, mode, selection, marks, layers, command, viewport)와 이벤트 콜백.
import { html } from "./ui/html.js";
import { useEffect, useMemo, useState } from "../vendor/hooks.module.js";
import { store, useStore } from "./store.js";
import { ui } from "./bridge.js";
import { Icon } from "./ui/icon.js";
import { Btn } from "./ui/parts.js";
import * as R from "./panels/results_state.js";
import { NodeOverlay, useNodeCanvas } from "./canvas/nodes_canvas.js";
import { CleanOverlay, useCleanCanvas } from "./canvas/clean_ui.js";
import { ScanNote } from "./scan_note.js";
import { CompareCard, ComparePane, useCmp } from "./compare.js";
import { ExtractLegend, neighborsOf, segmentsOf, sheetFacts, useExtractCheck } from "./canvas/extract_check.js";
import * as N from "./panels/nodes_state.js";

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

/** 도면에서 구성요소를 누르면 뜨는 속성 카드(화면 단순화): 태그, 종류(한글 이름), 이어진 배관·기기(태그로), 든 구간, 출처 도면·쪽.
 *  영문 종류 이름과 내부 ID는 보이지 않는다. 고치기는 채팅이 한다. */
function ItemBubble() {
  const b = useStore((s) => s.bubble);
  const rev = useStore((s) => s.drawings.rev);
  const row = useStore((s) => s.drawings.drawings.find((d) => b && d.graph_id === b.sheet));
  const view = N.useNodes((s) => s.sheetView);
  const [facts, setFacts] = useState(null);
  useEffect(() => {
    if (!b) return undefined;
    let alive = true;
    setFacts(null);
    sheetFacts(b.sheet, rev).then((f) => { if (alive) setFacts(f); });
    return () => { alive = false; };
  }, [b && b.sheet, b && b.id, rev]);
  if (!b) return null;
  const r = b.rect || {};
  const style = "left:" + Math.max(8, Math.round((r.x || 0) + (r.w || r.width || 0) + 8)) + "px;top:" + Math.max(8, Math.round(r.y || 0)) + "px";
  const trace = () => { store.set({ bubble: null, panel: "results" }); R.loadTrace({ sheet: b.sheet, local: b.id }); };
  const near = facts ? neighborsOf(b.id, facts.sheet, facts.clean) : [];
  const segs = segmentsOf(b.id, view && view.graph_id === b.sheet ? view : null);
  const from = row ? (row.display || row.drawing_number || "") + (row.title ? " " + row.title : "") + (typeof row.page_index === "number" ? " · " + (row.page_index + 1) + "쪽" : "") : "";
  return html`<div class="float bubble props" role="dialog" aria-label="구성요소 속성" style=${style}>
    <div><b>${b.tag || "태그 없음"}</b> ${b.kind_label || "종류 미확인"}</div>
    <dl class="props-list">
      <dt>이어진 곳</dt><dd>${near.length ? near.slice(0, 6).map((t, i) => html`<div key=${i}>${t}</div>`) : "없음"}${near.length > 6 ? html`<div class="muted small">외 ${near.length - 6}곳</div>` : null}</dd>
      <dt>든 구간</dt><dd>${segs.length ? segs.join(", ") : "없음"}</dd>
      ${from ? html`<dt>출처</dt><dd>${from}</dd>` : null}</dl>
    <div class="acts-row"><${Btn} sm=${true} label="분석 결과 추적" title="소속 구간, 그 구간의 칸과 권고를 따라갑니다" onClick=${trace}>분석 결과 추적<//>
      <${Btn} sm=${true} kind="ghost" icon="x" label="말풍선 닫기" onClick=${() => store.set({ bubble: null })} /></div></div>`;
}

export function SheetHost() {
  const sheet = useStore((s) => s.sheet);
  const marks = useStore((s) => s.marks);
  const command = useStore((s) => s.command);
  const split = useCmp((s) => !!s.gid && s.gid === sheet && s.mode === "side_by_side");      // 견주기 화면의 나란히 모드: 캔버스가 오른쪽 반으로 줄어든다
  const layers = useStore((s) => s.layers);        // 채팅의 층 켜고 끄기(symbol·pipe·tag)가 도면에 내려간다
  const [Comp, setComp] = useState(() => SheetComponent);
  const panel = useStore((s) => s.panel);
  const rev = useStore((s) => s.drawings.rev);
  const sv = N.useNodes((s) => s.sheetView);
  const chatMarks0 = marks.bySheet && marks.bySheet[sheet];
  const check = useExtractCheck(sheet, rev, !!sheet && panel === "drawings" && !(chatMarks0 && chatMarks0.length), sv && sv.graph_id === sheet && Array.isArray(sv.links) ? sv.links : undefined);      // 도면 탭에서만, 추적·채팅 강조 같은 다른 표시가 있으면 끈다
  const cc = useCleanCanvas(sheet);          // 원본·정리 보기, 미확인 칩, 못 읽은 곳 말풍선(s-viewer의 clean_ui.js)
  const nc = useNodeCanvas(sheet, { onEsc: () => { if (!cc.closeIfOpen()) store.set({ marks: { rid: null, bySheet: {} } }); } });
  const chatMarks = marks.bySheet && marks.bySheet[sheet];
  const items = useMemo(() => (chatMarks || []).concat(check.mark ? [check.mark] : []).map((m, i) => Object.assign({ id: (marks.rid || "m") + (i ? "#" + i : "") }, m)), [chatMarks, marks.rid, check.mark]);
  useEffect(() => { loadCanvas().then((c) => { if (c) setComp(() => c); store.set({ canvasReady: !!c }); }); }, []);
  if (!sheet) {
    return html`<div class="canvas"><div class="center-empty" style="position:absolute;inset:0;display:grid;place-items:center;color:var(--muted)">
      <div style="text-align:center"><${Icon} name="files" size=${28} /><p>왼쪽 메뉴의 도면에서 도면을 열거나<br />도면 파일을 끌어 놓으세요.</p></div></div></div>`;
  }
  if (!Comp) return html`<${Fallback} sheet=${sheet} />`;
  return html`<div class=${"canvas" + (split ? " cmp-side" : "")}><${Comp} sheet=${{ graph_id: sheet }} ...${nc.props} ...${cc.props} layers=${layers} onReady=${(g) => store.set({ readySheet: g })} marks=${items} dataRev=${rev}
    command=${command} onItemClick=${(d) => { ui("itemClick", { id: d.id }); store.set({ bubble: { sheet, id: d.id, tag: d.tag, kind: d.kind, kind_label: d.kind_label, rect: d.rect } }); }} /><${NodeOverlay} /><${CleanOverlay} /><${ExtractLegend} counts=${check.counts} /><${ScanNote} sheet=${sheet} /><${ComparePane} /><${CompareCard} /><${ItemBubble} /></div>`;
}
