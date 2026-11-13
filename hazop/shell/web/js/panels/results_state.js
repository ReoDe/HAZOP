// 분석 결과(3단계 ⑤)의 화면 상태와 엔진 잇기. 저장하는 자료는 엔진만 쓴다: 여기는 읽어 온 판(summary·cell)과 보기 상태(고른 칸·보기)만 들고,
// 쓰기는 명령으로 보낸 뒤 엔진 답과 `changed("results")`로 다시 읽는다(낙관적 갱신 없음, 규격 §5.3). 쓰기 명령은 읽은 결과 파일 지문(ver)을 들고 간다.
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";

const EMPTY = { available: false, empty: true, nodes: [], deviations: [], matrix: {}, ver: "none", kpi: null, run: { running: false }, reason: "" };

export const results = createStore({
  summary: EMPTY,
  view: "matrix",          // "matrix" | "recs"
  active: null,            // {node_id, deviation_id}: 고른 칸
  cell: null,              // GET results/cell/...
  recs: [],                // GET results/recs
  trace: null,             // GET results/trace?entity=...
  busy: false,
  error: null,
  plan: null,              // 분석 실행 확인 카드
  exporting: false,
  notice: null,            // 내보낸 결과 등 한 줄
});

export function useResults(selector) {
  const [value, setValue] = useState(() => selector(results.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(results.get());
    return results.subscribe(sync);
  }, []);
  return value;
}

export const errorText = (e) => (e && e.message) || "처리하지 못했습니다.";

/** 프로젝트가 바뀌었을 때: 읽어 둔 것과 진행 중인 읽기 결과를 모두 버린다. */
export function reset() {
  seq++;
  results.set({ summary: EMPTY, view: "matrix", active: null, cell: null, recs: [], trace: null, busy: false, error: null, plan: null, exporting: false, notice: null });
}

// ---------------------------------------------------------------- 읽기
let seq = 0;
export async function loadSummary() {
  const mine = ++seq;
  let s = null;
  try { s = await read("results"); } catch (e) { s = Object.assign({}, EMPTY, { reason: "분석 결과를 읽지 못했습니다." }); }
  if (mine !== seq) return results.get().summary;
  results.set({ summary: s });
  return s;
}

/** 분석 진행 상태만 다시 읽는다(작다). 행렬 전체를 호출마다 다시 읽지 않는다. */
export async function loadRun() {
  try { const run = await read("results/run"); results.set((s) => ({ summary: Object.assign({}, s.summary, { run }) })); } catch (e) { /* 다음 알림에 다시 읽는다 */ }
}

/** 호출 하나가 바꾼 칸만 행렬에 끼워 넣는다(results.cells 사건). 고른 칸이 그 구간이면 워크시트도 다시 읽는다. */
export function mergeCells(d) {
  results.set((s) => {
    const m = Object.assign({}, s.summary.matrix);
    m[d.node_id] = Object.assign({}, m[d.node_id], d.cells);
    return { summary: Object.assign({}, s.summary, { matrix: m, kpi: d.kpi, ver: d.ver }) };
  });
  const a = results.get().active;
  if (a && a.node_id === d.node_id && d.cells[a.deviation_id]) loadCell(a.node_id, a.deviation_id);
}

export async function loadCell(nodeId, deviationId) {
  if (!nodeId) { results.set({ cell: null }); return null; }
  let c = null;
  try { c = await read("results/cell/" + encodeURIComponent(nodeId) + "/" + encodeURIComponent(deviationId)); } catch (e) { c = null; }
  const a = results.get().active;
  if (!a || a.node_id !== nodeId || a.deviation_id !== deviationId) return null;
  results.set({ cell: c });
  return c;
}

export async function loadRecs() {
  try { results.set({ recs: (await read("results/recs")).recs }); } catch (e) { results.set({ recs: [] }); }
}

/** 구성요소 -> 소속 구간 -> 칸 -> 권고(INTENT §3.6). query: 태그·ID 글, 또는 {sheet, local}(도면에서 누른 구성요소). */
export async function loadTrace(query) {
  const q = typeof query === "string" ? { entity: query.trim() } : query;
  if (!q || !(q.entity || (q.sheet && q.local))) { results.set({ trace: null }); return null; }
  const qs = q.entity ? "entity=" + encodeURIComponent(q.entity) : "sheet=" + encodeURIComponent(q.sheet) + "&local=" + encodeURIComponent(q.local);
  let t = null;
  try { t = await read("results/trace?" + qs); } catch (e) { t = null; }
  results.set({ trace: t, view: "recs", error: t ? null : "추적하지 못했습니다." });
  loadRecs();
  return t;
}

// ---------------------------------------------------------------- 도면에서 보기 · 돌아가기
let openSheetFn = null;
export function setOpenSheet(fn) { openSheetFn = fn; }

/** 고른 칸의 구간을 도면에서 보인다: 패널을 닫고(위 막대에 '분석 결과로 돌아가기' 칩) 그 구간을 강조·확대한다. 구간의 구성요소가 놓인 도면이 지금 도면이 아니면 그 도면을 연다. */
export async function viewOnSheet(nodeId) {
  const N = await import("./nodes_state.js");
  const row = N.nodes.get().list.nodes.find((n) => n.node_id === nodeId);
  const sheets = (row && row.sheets) || [];
  if (!sheets.length) { results.set({ error: "이 구간의 구성요소가 놓인 도면을 찾지 못했습니다." }); return false; }
  const cur = store.get().sheet;
  const target = sheets.some((s) => s.graph_id === cur) ? cur : sheets[0].graph_id;
  if (target !== cur && openSheetFn) openSheetFn(target);
  store.set({ panel: null, backTo: "results" });
  N.nodes.set({ focus: null, detail: null });
  await N.loadSheet(target);
  N.focusNode(nodeId, { zoom: true });
  return true;
}

export async function refresh() {
  const s = results.get();
  await Promise.all([loadSummary(), s.active ? loadCell(s.active.node_id, s.active.deviation_id) : null, s.view === "recs" ? loadRecs() : null]);
}

// ---------------------------------------------------------------- 보기 동작
export function setView(view) { results.set({ view }); if (view === "recs") loadRecs(); }

export function openCell(nodeId, deviationId) {
  results.set({ active: { node_id: nodeId, deviation_id: deviationId }, cell: null, error: null, view: "matrix" });
  return loadCell(nodeId, deviationId);
}

export function dismissError() { results.set({ error: null }); }

// ---------------------------------------------------------------- 쓰기(판정)
async function write(name, args) {
  const c = results.get().cell;
  results.set({ busy: true, error: null });
  try {
    const r = await cmd(name, Object.assign({ ver: c ? c.ver : results.get().summary.ver, set_rev: results.get().summary.set_rev }, args));
    results.set({ busy: false });
    await refresh();
    return r;
  } catch (e) {
    results.set({ busy: false, error: errorText(e) });
    if (e && e.code === "stale") await refresh();
    return null;
  }
}

const where = () => { const a = results.get().active; return { node_id: a.node_id, deviation_id: a.deviation_id }; };

export const setStatus = (entryId, status, reason) => write("results.set_status", Object.assign(where(), { entry_id: entryId, status }, reason && reason.trim() ? { reason: reason.trim() } : {}));
export const editEntry = (entryId, fields, reason) => write("results.edit_entry", Object.assign(where(), { entry_id: entryId, fields, reason: (reason || "").trim() }));
export const recheck = () => write("results.recheck", where());

// ---------------------------------------------------------------- 내보내기
export async function exportExcel(scope, nodeIds) {
  results.set({ exporting: true, error: null, notice: null });
  try {
    const r = await cmd("results.export_excel", Object.assign({ scope }, nodeIds && nodeIds.length ? { node_ids: nodeIds } : {}));
    results.set({ exporting: false, notice: r.cancelled ? null : "Excel로 내보냈습니다: " + r.path + " · 워크시트 " + r.rows + "행" });
    return r;
  } catch (e) { results.set({ exporting: false, error: errorText(e) }); return null; }
}

export async function exportIe() {
  results.set({ exporting: true, error: null, notice: null });
  try {
    const r = await cmd("results.export_ie");
    results.set({ exporting: false, notice: r.cancelled ? null : "초기사건 인계 묶음을 내보냈습니다: " + r.path + " · 후보 " + r.candidates + "개" });
    return r;
  } catch (e) { results.set({ exporting: false, error: errorText(e) }); return null; }
}

// ---------------------------------------------------------------- 분석 실행
export async function planRun(scope) {
  const a = results.get().active;
  const args = { scope };
  if (scope === "node" || scope === "cell") { if (!a) { results.set({ error: "행렬에서 분석할 칸을 먼저 고르세요." }); return null; } args.node_id = a.node_id; }
  if (scope === "cell") args.deviation_id = a.deviation_id;
  try {
    const p = await cmd("results.run_plan", args);
    results.set({ plan: Object.assign({ scope, args }, p), error: null });
    return p;
  } catch (e) { results.set({ error: errorText(e) }); return null; }
}

export function closePlan() { results.set({ plan: null }); }

export async function startRun() {
  const p = results.get().plan;
  if (!p) return null;
  try {
    if (p.needs_terms) await cmd("results.ack_terms");
    const r = await cmd("results.run", p.args.scope ? Object.assign({ scope: p.scope }, p.args) : { scope: p.scope });
    results.set({ plan: null, error: null });
    return r;
  } catch (e) { results.set({ error: errorText(e) }); return null; }
}

export async function stopRun() {
  try { await cmd("results.stop"); } catch (e) { results.set({ error: errorText(e) }); }
}

// ---------------------------------------------------------------- 엔진 알림 연결(한 번만)
let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => {
    if (topic === "results") refresh();
    else if (topic === "results.run") loadRun();
    else if (topic === "nodes") loadSummary();
  });
  on("results.cells", mergeCells);
  refresh();
}
