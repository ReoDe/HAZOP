// 범례·기호표 도면을 구간 분석에서 빼기·다시 넣기(B2, 도면 패널의 연 도면 아래와 목록 행의 칩). 구간 단위 '분석에서 제외'는 없다
// (규격 v2: 분석에 넣지 않을 구간은 확정하지 않는다). 저장은 엔진만 한다(nodes.exclude_drawing). 그 도면 구성요소를 품은 구간이
// 있으면 엔진이 확인 글을 돌려주고(needs_confirm), 사람이 그 글을 보고 누르면 같은 글을 confirm으로 다시 보낸다.
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Chip, Notice } from "../ui/parts.js";

const when = (t) => (t ? String(t).replace("T", " ").replace(/:\d\d(\.\d+)?Z?$/, "") : "");

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
        ? html`${d.legend_hint ? html`<div class="small">범례·기호표 도면으로 보입니다. 공정 흐름이 없으면 분석에서 빼세요.</div>` : null}
          <div class="kv"><span class="small muted">${heldText ? "이 도면 구성요소를 품은 구간: " + heldText : "구간 분석에 들어가는 도면"}</span>
            <${Btn} sm=${true} kind="ghost" label=${(d.drawing_number || graphId) + " 분석에서 빼기"} disabled=${busy || !d.drawing_number}
              title=${d.drawing_number ? "범례·기호표 도면을 구간 제안에서 뺍니다" : "표제란에서 도면 번호를 먼저 확정하세요"} onClick=${() => setOpen(true)}>분석에서 빼기<//></div>`
        : html`<div class="field"><label for=${"dx-reason-" + graphId}>빼는 이유</label>
            <input id=${"dx-reason-" + graphId} class="textbox" maxlength="500" value=${reason} onInput=${(e) => { setReason(e.target.value); setAsk(null); }} />
            ${ask ? html`<${Notice} kind="warn" icon="alert-triangle">${ask}<//>` : heldText ? html`<div class="small muted">이 도면 구성요소를 품은 구간: ${heldText}</div>` : null}
            <div class="acts-row"><${Btn} kind="primary" sm=${true} label=${ask ? "확인하고 빼기" : "빼기 실행"} disabled=${busy} onClick=${() => send(true, ask)}>${ask ? "확인하고 빼기" : "빼기"}<//>
              <${Btn} sm=${true} label="취소" onClick=${() => { setOpen(false); setAsk(null); }}>취소<//></div></div>`}</div>`;
}
