// 분석 범위(B2): 구간을 분석에서 제외·다시 넣기(구간 카드 안), 도면을 구간 분석에서 빼기·다시 넣기(도면 패널의 연 도면 아래).
// 저장은 엔진만 한다(nodes.screen·nodes.exclude_drawing). 확정·잠긴 구간이나 결과가 있는 구간, 구간이 품은 도면은 엔진이 확인 글을
// 돌려주고(needs_confirm), 사람이 그 글을 보고 누르면 같은 글을 confirm으로 다시 보낸다. 결과는 지우지 않는다.
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import * as N from "./nodes_state.js";

const when = (t) => (t ? String(t).replace("T", " ").replace(/:\d\d(\.\d+)?Z?$/, "") : "");

/** 구간 목록 행의 표시. 제외된 구간에만 칩을 단다. */
export function ScreenChip({ n }) {
  return n.screen === "excluded"
    ? html`<${Chip} title=${"분석에서 제외: " + (n.screen_reason || "")}>분석 제외<//>`
    : null;
}

/** 구간 카드 안: 분석에서 제외(이유 필수) 또는 다시 넣기. key를 구간 ID로 줘 구간을 바꾸면 입력이 비게 한다. */
export function ScreenBox({ n, busy }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [ask, setAsk] = useState(null);
  const excluded = n.screen === "excluded";
  const send = async (status, confirm) => {
    const r = await N.run("screen", Object.assign({ node_id: n.node_id, status }, status === "excluded" ? { reason: reason.trim() } : {},
      confirm ? { confirm } : {}), [n.node_id]);
    if (r && r.needs_confirm) { setAsk(r.needs_confirm); return; }
    if (r) { setAsk(null); setOpen(false); setReason(""); }
  };
  if (excluded) {
    return html`<div class="field nscreen"><label>분석 범위</label>
      <div class="kv"><span class="small">분석에서 제외 · ${n.screen_reason || "이유 없음"}${n.screen_by ? " · " + n.screen_by : ""}${n.screen_at ? " · " + when(n.screen_at) : ""}</span>
        <${Btn} sm=${true} icon="arrow-back-up" label=${n.node_id + " 분석에 다시 넣기"} disabled=${busy} onClick=${() => send("keep")}>다시 넣기<//></div></div>`;
  }
  if (!open) {
    return html`<div class="acts-row"><${Btn} sm=${true} kind="ghost" label=${n.node_id + " 분석에서 제외"}
      title="이 구간을 분석 결과 행렬·일괄 분석·Excel에서 뺍니다(결과는 지우지 않음)" disabled=${busy} onClick=${() => setOpen(true)}>분석에서 제외<//></div>`;
  }
  return html`<div class="field nscreen"><label for=${"screen-reason-" + n.node_id}>분석에서 제외하는 이유(필수)</label>
    <input id=${"screen-reason-" + n.node_id} class="textbox" maxlength="500" value=${reason} onInput=${(e) => { setReason(e.target.value); setAsk(null); }}
      onKeyDown=${(e) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); setAsk(null); } }} />
    ${ask ? html`<${Notice} kind="warn" icon="alert-triangle">${ask}<//>` : null}
    <div class="acts-row">
      <${Btn} kind="primary" sm=${true} label=${ask ? n.node_id + " 확인하고 제외" : n.node_id + " 제외 실행"} disabled=${busy || !reason.trim()}
        onClick=${() => send("excluded", ask)}>${ask ? "확인하고 제외" : "제외"}<//>
      <${Btn} sm=${true} label="취소" onClick=${() => { setOpen(false); setAsk(null); }}>취소<//></div></div>`;
}

// ---------------------------------------------------------------- 도면 빼기

const drawingsStore = createStore({ data: null, error: null });
let seq = 0;
let wired = false;

async function loadDrawings() {
  const mine = ++seq;
  try {
    const data = await read("nodes/drawings");
    if (mine === seq) drawingsStore.set({ data, error: null });
  } catch (e) {
    if (mine === seq) drawingsStore.set({ error: (e && e.message) || "도면 빼기 표시를 읽지 못했습니다." });
  }
}

function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "nodes" || topic === "drawings") loadDrawings(); });
  loadDrawings();
}

function useDrawing(graphId) {
  const [, force] = useState(0);
  useLayoutEffect(() => drawingsStore.subscribe(() => force((x) => x + 1)), []);
  wire();
  const { data } = drawingsStore.get();
  return data && (data.drawings || []).find((d) => d.graph_id === graphId);
}

/** 도면 목록 행의 표시: 구간 분석에서 뺀 도면에만 칩을 단다. */
export function DrawingExcludedChip({ graphId }) {
  const d = useDrawing(graphId);
  return d && d.excluded ? html`<${Chip} title=${"구간 분석에서 뺌: " + (d.reason || "")}>분석 제외<//>` : null;
}

/** 연 도면 아래: 구간 분석(구간 제안·후보)에서 빼기·다시 넣기와, 이 도면의 구성요소를 품은 구간. */
export function DrawingExclude({ graphId }) {
  const d = useDrawing(graphId);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("범례·기호표 도면");
  const [ask, setAsk] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (!d) return null;
  const send = async (excluded, confirm) => {
    setBusy(true); setError(null);
    try {
      const r = await cmd("nodes.exclude_drawing", Object.assign({ project_id: store.get().app.project_id, graph_id: graphId, excluded, ver: d.ver },
        excluded ? { reason: reason.trim() } : {}, confirm ? { confirm } : {}));
      if (r && r.needs_confirm) { setAsk(r.needs_confirm); return; }
      setAsk(null); setOpen(false);
      await loadDrawings();
    } catch (e) {
      setError((e && e.message) || "저장하지 못했습니다.");
      if (e && e.code === "stale") await loadDrawings();
    } finally {
      setBusy(false);
    }
  };
  const held = d.nodes || [];
  const heldText = held.length ? held.map((h) => h.node_id + "(" + h.count + ")").join(", ") : null;
  return html`<div class="card dexclude" aria-label=${(d.drawing_number || graphId) + " 분석 범위"}>
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}
    ${d.excluded
      ? html`<div class="kv"><span class="small">구간 분석에서 뺌 · ${d.reason || ""}${d.by ? " · " + d.by : ""}${d.at ? " · " + when(d.at) : ""}</span>
          <${Btn} sm=${true} icon="arrow-back-up" label=${(d.drawing_number || graphId) + " 분석에 다시 넣기"} disabled=${busy} onClick=${() => send(false)}>다시 넣기<//></div>`
      : !open
        ? html`<div class="kv"><span class="small muted">${heldText ? "이 도면 구성요소를 품은 구간: " + heldText : "구간 분석에 들어가는 도면"}</span>
            <${Btn} sm=${true} kind="ghost" label=${(d.drawing_number || graphId) + " 분석에서 빼기"} disabled=${busy || !d.drawing_number}
              title=${d.drawing_number ? "범례·기호표 도면을 구간 제안에서 뺍니다" : "표제란에서 도면 번호를 먼저 확정하세요"} onClick=${() => setOpen(true)}>분석에서 빼기<//></div>`
        : html`<div class="field"><label for=${"dx-reason-" + graphId}>빼는 이유</label>
            <input id=${"dx-reason-" + graphId} class="textbox" maxlength="500" value=${reason} onInput=${(e) => { setReason(e.target.value); setAsk(null); }} />
            ${ask ? html`<${Notice} kind="warn" icon="alert-triangle">${ask}<//>` : heldText ? html`<div class="small muted">이 도면 구성요소를 품은 구간: ${heldText}</div>` : null}
            <div class="acts-row"><${Btn} kind="primary" sm=${true} label=${ask ? "확인하고 빼기" : "빼기 실행"} disabled=${busy} onClick=${() => send(true, ask)}>${ask ? "확인하고 빼기" : "빼기"}<//>
              <${Btn} sm=${true} label="취소" onClick=${() => { setOpen(false); setAsk(null); }}>취소<//></div></div>`}</div>`;
}
