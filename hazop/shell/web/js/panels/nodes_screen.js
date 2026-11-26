// 범례·기호표 도면을 구간 분석에서 빼기·다시 넣기(B2, 도면 패널 목록 행의 칩과 위쪽 고르기 도구). 구간 단위 '분석에서 제외'는 없다
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

const REASON = "범례·기호표 도면";

/** 도면 목록에서 줄 옆 체크로 고른 도면을 구간 분석에서 빼거나 다시 넣는 위쪽 한 줄 도구. 그 도면 구성요소를 품은 구간이 있으면
 *  엔진이 확인 글을 돌려주고(needs_confirm), 사람이 누르면 같은 글을 confirm으로 다시 보낸다. 도면 지우기는 엔진 명령이 없어 잇지 않는다. */
export function DrawingPicks({ ids, onDone }) {
  wire();
  const [, force] = useState(0);
  useLayoutEffect(() => drawingsStore.subscribe(() => force((x) => x + 1)), []);
  const [ask, setAsk] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const all = (drawingsStore.get().data || {}).drawings || [];
  const mine = ids.map((g) => all.find((d) => d.graph_id === g)).filter(Boolean);
  const out = mine.filter((d) => !d.excluded && d.drawing_number), back = mine.filter((d) => d.excluded);
  async function run(list, excluded, confirms) {
    setBusy(true); setError(null);
    const asking = [];
    for (const first of list) {
      const d = ((drawingsStore.get().data || {}).drawings || []).find((x) => x.graph_id === first.graph_id) || first;      // 앞 도면을 저장한 뒤의 새 판
      try {
        const r = await cmd("nodes.exclude_drawing", Object.assign({ project_id: store.get().app.project_id, graph_id: d.graph_id, excluded, ver: d.ver },
          excluded ? { reason: REASON } : {}, confirms && confirms[d.graph_id] ? { confirm: confirms[d.graph_id] } : {}));
        if (r && r.needs_confirm) asking.push({ d, text: r.needs_confirm }); else await loadDrawings();
      } catch (e) {
        setError((e && e.message) || "저장하지 못했습니다.");
        if (e && e.code === "stale") await loadDrawings();
        setBusy(false); setAsk(asking);
        return;
      }
    }
    setBusy(false); setAsk(asking);
    if (!asking.length) onDone();
  }
  const confirms = () => Object.fromEntries(ask.map((a) => [a.d.graph_id, a.text]));
  return html`<div class="picks" role="toolbar" aria-label="고른 도면에 할 일"><span class="small muted">${mine.length}장 고름</span>
    ${out.length ? html`<${Btn} sm=${true} label="고른 도면 분석에서 빼기" disabled=${busy} onClick=${() => run(out, true)}>분석에서 빼기<//>` : null}
    ${back.length ? html`<${Btn} sm=${true} icon="arrow-back-up" label="고른 도면 분석에 다시 넣기" disabled=${busy} onClick=${() => run(back, false)}>다시 넣기<//>` : null}
    <${Btn} sm=${true} kind="ghost" label="고르기 풀기" disabled=${busy} onClick=${onDone}>풀기<//>
    ${ask.length ? html`<${Notice} kind="warn" icon="alert-triangle">${ask.map((a) => html`<div key=${a.d.graph_id}>${a.text}</div>`)}
      <div class="acts-row"><${Btn} sm=${true} kind="primary" label="확인하고 빼기" disabled=${busy} onClick=${() => run(ask.map((x) => x.d), true, confirms())}>확인하고 빼기<//></div><//>` : null}
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}</div>`;
}
