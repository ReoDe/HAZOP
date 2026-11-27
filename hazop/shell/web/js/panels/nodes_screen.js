// 도면 지우기(B2의 '구간 분석에서 빼기'를 쓴다, 도면 패널 위쪽 고르기 도구). 구간 단위 '분석에서 제외'는 없다
// (규격 v2: 분석에 넣지 않을 구간은 확정하지 않는다). 저장은 엔진만 한다(nodes.exclude_drawing). 그 도면 구성요소를 품은 구간이
// 있으면 엔진이 확인 글을 돌려주고(needs_confirm), 사람이 그 글을 보고 누르면 같은 글을 confirm으로 다시 보낸다.
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Notice } from "../ui/parts.js";
import { pushSaved } from "../undo.js";

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

/** 지운(구간 분석에서 뺀) 도면의 graph_id 모음. 도면 목록은 이 도면을 보이지 않는다. 아직 읽지 못했으면 빈 모음이다. */
export function useRemovedDrawings() {
  const [, force] = useState(0);
  useLayoutEffect(() => drawingsStore.subscribe(() => force((x) => x + 1)), []);
  wire();
  const { data } = drawingsStore.get();
  return new Set(((data && data.drawings) || []).filter((d) => d.excluded).map((d) => d.graph_id));
}

const REASON = "범례·기호표 도면";

/** 지운 도면을 되살린다(Ctrl+Z): 하나씩 지금 판으로 보낸다. */
async function restoreDrawings(ids) {
  for (const gid of ids) {
    await loadDrawings();
    const d = ((drawingsStore.get().data || {}).drawings || []).find((x) => x.graph_id === gid);
    if (!d || !d.excluded) continue;
    try { await cmd("nodes.exclude_drawing", { project_id: store.get().app.project_id, graph_id: gid, excluded: false, ver: d.ver }); }
    catch (e) { store.set({ toast: { text: (e && e.message) || "되돌리지 못했습니다.", kind: "err" } }); return false; }
  }
  await loadDrawings();
  return true;
}

/** 도면 목록에서 줄 옆 체크로 고른 도면을 지우는 위쪽 한 줄 도구. 지우기는 엔진의 '구간 분석에서 빼기'를 쓴다(파일은 그대로). 확인 창은 없다:
 *  그 도면 구성요소를 품은 구간이 있어 엔진이 확인 글을 돌려주면(needs_confirm) 그 글을 그대로 confirm으로 다시 보낸다. */
export function DrawingPicks({ ids, onDone }) {
  wire();
  const [, force] = useState(0);
  useLayoutEffect(() => drawingsStore.subscribe(() => force((x) => x + 1)), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const all = (drawingsStore.get().data || {}).drawings || [];
  const mine = ids.map((g) => all.find((d) => d.graph_id === g)).filter(Boolean);
  const out = mine.filter((d) => !d.excluded && d.drawing_number);
  async function remove() {
    setBusy(true); setError(null);
    const gone = [];
    for (const first of out) {
      const d = ((drawingsStore.get().data || {}).drawings || []).find((x) => x.graph_id === first.graph_id) || first;      // 앞 도면을 저장한 뒤의 새 판
      const args = { project_id: store.get().app.project_id, graph_id: d.graph_id, excluded: true, ver: d.ver, reason: REASON };
      try {
        const r = await cmd("nodes.exclude_drawing", args);
        if (r && r.needs_confirm) await cmd("nodes.exclude_drawing", Object.assign({}, args, { confirm: r.needs_confirm }));
        gone.push(d.graph_id);
        if (store.get().sheet === d.graph_id) store.set({ sheet: null, bubble: null, marks: { rid: null, bySheet: {} } });      // 지운 도면은 화면에서도 내린다
        await loadDrawings();
      } catch (e) {
        setError((e && e.message) || "저장하지 못했습니다.");
        if (e && e.code === "stale") await loadDrawings();
        setBusy(false);
        if (gone.length) pushSaved("drawing_delete", () => restoreDrawings(gone));
        return;
      }
    }
    if (gone.length) pushSaved("drawing_delete", () => restoreDrawings(gone));
    setBusy(false);
    onDone();
  }
  return html`<div class="picks" role="toolbar" aria-label="고른 도면에 할 일"><span class="small muted">${mine.length}장 고름</span>
    ${out.length ? html`<${Btn} sm=${true} kind="ghost" icon="trash" label="삭제" disabled=${busy} onClick=${remove} />` : null}
    <${Btn} sm=${true} kind="ghost" label="고르기 해제" disabled=${busy} onClick=${onDone}>해제<//>
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}</div>`;
}
