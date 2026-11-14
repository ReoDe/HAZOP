// 구간(2단계)의 화면 상태와 엔진 잇기. 저장하는 자료는 엔진만 쓴다: 여기는 읽어 온 판(list·sheetView)과 보기 상태(고른 것·강조·카드)만 들고,
// 쓰기는 명령으로 보낸 뒤 엔진 답과 `changed("nodes")`로 다시 읽는다. 낙관적 갱신을 하지 않는다(규격 §5.3).
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store as shell } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";
import { openSheet as openSheetVia } from "./results_state.js";
import { blankCard, errorText, targetsOf } from "./nodes_logic.js";

const EMPTY_LIST = {project_id: null,  available: false, set_rev: 0, nodes: [], batches: [], outside: { count: 0, total: 0 }, stale: false, read_only: null, pending_ai: 0 };

export const nodes = createStore({
  list: EMPTY_LIST,         // GET nodes
  sheetView: null,          // GET nodes/sheet/<graph_id>: {graph_id, segments, outside_ids}
  detail: null,             // GET nodes/node/<id>
  mode: "pan",              // "pan" | "pick"
  selection: [],            // 지금 도면에서 고른 local_id
  truncated: false,         // 2,000개를 넘겨 골라 앞 2,000개만 남았음
  focus: null,              // 강조한 구간 ID
  card: null,               // 새 구간 카드
  scope: "sheet",           // 목록 범위: "sheet"(이 도면) | "all"
  showOutside: true,        // 구간 밖 구성요소를 흐리게
  checked: [],              // 합치기용으로 체크한 구간
  busy: false,
  error: null,              // 마지막 거절 사유(엔진 문장)
  needArchive: null,        // 지우기가 칸 판정 때문에 거절됨 → 보관 선택지를 보임
});

export function useNodes(selector) {
  const [value, setValue] = useState(() => selector(nodes.get()));
  // 그린 직후 곧바로 구독한다(useEffect는 그림 뒤로 미뤄져 그 사이의 바뀜을 놓칠 수 있다)
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(nodes.get());
    return nodes.subscribe(sync);
  }, []);
  return value;
}

// ---------------------------------------------------------------- 읽기
let seq = 0;

export async function loadList() {
  const mine = ++seq;
  const list = await read("nodes");
  if (mine !== seq) return nodes.get().list;           // 더 늦게 시작한 읽기가 이긴다
  nodes.set((s) => ({ list, focus: s.focus && list.nodes.some((n) => n.node_id === s.focus) ? s.focus : null,
    checked: s.checked.filter((id) => list.nodes.some((n) => n.node_id === id)) }));
  return list;
}

export async function loadSheet(graphId) {
  if (!graphId) { nodes.set({ sheetView: null }); return null; }
  let v = null;
  try { v = await read("nodes/sheet/" + encodeURIComponent(graphId)); } catch (e) { v = null; }
  if (shell.get().sheet !== graphId) return null;
  nodes.set({ sheetView: v });
  return v;
}

export async function loadDetail(nodeId) {
  if (!nodeId) { nodes.set({ detail: null }); return null; }
  let d = null;
  try { d = await read("nodes/node/" + encodeURIComponent(nodeId)); } catch (e) { d = null; }
  if (nodes.get().focus !== nodeId) return null;
  nodes.set({ detail: d });
  return d;
}

export async function refresh() {
  try { await loadList(); } catch (e) { /* 읽기 실패: 이전 판을 그대로 보인다 */ }
  await Promise.all([loadSheet(shell.get().sheet), loadDetail(nodes.get().focus)]);
}

// ---------------------------------------------------------------- 보기 동작
export function setMode(mode) { nodes.set({ mode: mode === "pick" ? "pick" : "pan" }); }
export function setSelection(ids, truncated = false) { nodes.set({ selection: ids, truncated: !!truncated }); }
export function clearSelection() { nodes.set({ selection: [], truncated: false }); }

export function focusNode(id, { zoom = false } = {}) {
  const same = nodes.get().focus === id;
  nodes.set({ focus: same ? null : id, detail: same ? null : nodes.get().detail, error: null, needArchive: null });
  if (same) return;
  loadDetail(id);
  if (zoom) zoomToNode(id);
}

export function zoomToNode(id) {
  const v = nodes.get().sheetView, seg = v && v.segments.find((s) => s.node_id === id);
  if (seg && seg.ids.length) shell.set((s) => ({ command: { seq: s.command.seq + 1, type: "zoomTo", ids: seg.ids.slice(0, 400), pad: 0.1 } }));
}

export function zoomToIds(ids) {
  if (ids.length) shell.set((s) => ({ command: { seq: s.command.seq + 1, type: "zoomTo", ids: ids.slice(0, 400), pad: 0.15 } }));
}

export function openPanel() { shell.set({ panel: "nodes" }); }

/** 다른 도면으로 가서 그 도면의 구간을 읽고, ids(맞은편 연결·구간)로 확대한다. 도면을 바꾸는 길은 분석 결과의 '도면에서 보기'와 같다. */
export async function goToSheet(graphId, { ids = null, node = null } = {}) {
  if (!graphId) return false;
  if (shell.get().sheet !== graphId) {
    if (!openSheetVia(graphId)) return false;
  }
  await loadSheet(graphId);
  const v = nodes.get().sheetView;
  const target = ids || (node && v && v.segments.find((s) => s.node_id === node) ? v.segments.find((s) => s.node_id === node).ids : null);
  if (target && target.length) {
    const go = () => shell.set((s) => ({ command: { seq: s.command.seq + 1, type: "zoomTo", ids: target.slice(0, 400), pad: ids ? 0.6 : 0.1 } }));
    go();
    setTimeout(go, 500);                      // 새 도면의 그림이 자리 잡은 뒤에도 한 번 더(처음 명령이 도면 자료보다 빠를 수 있다)
  }
  return true;
}

/** 다른 도면 연결(오각형)을 누름: 이어진 연결이면 맞은편 도면의 맞은편 연결로 간다. */
export function followLink(link) {
  if (!link || link.status !== "linked" || !link.peer_graph_id) return false;
  goToSheet(link.peer_graph_id, { ids: link.peer_id ? [link.peer_id] : null });
  return true;
}

export function dismissError() { nodes.set({ error: null, needArchive: null }); }

// ---------------------------------------------------------------- 카드
export async function openCard() {
  const { selection } = nodes.get(), sheet = shell.get().sheet;
  if (!selection.length || !sheet) return;
  nodes.set({ card: blankCard({ busy: true }) });
  try {
    const sg = await cmd("nodes.suggest", { project_id: nodes.get().list.project_id, sheet, ids: selection });
    if (nodes.get().card) nodes.set((s) => ({ card: Object.assign({}, s.card, { busy: false, suggest: sg, name: s.card.name || sg.name }) }));
  } catch (e) {
    if (nodes.get().card) nodes.set((s) => ({ card: Object.assign({}, s.card, { busy: false, error: errorText(e) }) }));
  }
}

export function editCard(patch) { nodes.set((s) => ({ card: s.card ? Object.assign({}, s.card, patch) : s.card })); }
export function closeCard() { nodes.set({ card: null }); }

export async function submitCard() {
  const { card, selection, list } = nodes.get(), sheet = shell.get().sheet;
  if (!card || card.busy) return null;
  if (!card.name.trim()) { editCard({ error: "구간 이름을 입력하세요." }); return null; }
  editCard({ busy: true, error: null });
  try {
    const r = await cmd("nodes.create", { project_id: list.project_id, sheet, ids: selection, name: card.name.trim(), design_intent: card.intent.trim() || undefined, set_rev: list.set_rev });
    nodes.set({ card: null, selection: [], truncated: false, mode: "pan" });
    await refresh();
    if (r.node_ids && r.node_ids[0]) focusNode(r.node_ids[0]);
    return r;
  } catch (e) {
    await afterError(e);
    editCard({ busy: false, error: errorText(e) });
    return null;
  }
}

// ---------------------------------------------------------------- 명령
async function afterError(e) {
  nodes.set({ error: errorText(e), busy: false });
  if (e && (e.code === "stale" || e.code === "not_found")) await refresh();
}

/** 구간 명령 하나. 화면이 본 판(set_rev, 대상 rev·state)을 함께 보낸다. 거절되면 엔진 사유를 error에 둔다. */
export async function run(name, args, targetIds) {
  const { list } = nodes.get();
  nodes.set({ busy: true, error: null, needArchive: null });
  try {
    const r = await cmd("nodes." + name, Object.assign({ project_id: list.project_id, set_rev: list.set_rev }, args, targetIds && targetIds.length ? { targets: targetsOf(list.nodes, targetIds) } : {}));
    nodes.set({ busy: false });
    if (r && r.skipped_text) shell.set({ toast: { text: r.skipped_text, kind: "info" } });   // 구성요소가 아니라 뺀 선이 있으면 알린다
    await refresh();
    return r;
  } catch (e) {
    await afterError(e);
    return null;
  }
}

export const rename = (id, name) => run("rename", { node_id: id, name }, [id]);
export const setIntent = (id, text) => run("set_intent", { node_id: id, text }, [id]);
export const confirm = (ids) => run("confirm", { node_ids: ids }, ids);
export const unconfirm = (ids) => run("unconfirm", { node_ids: ids }, ids);
export const lock = (ids) => run("lock", { node_ids: ids }, ids);
export const unlock = (ids, reason) => run("unlock", { node_ids: ids, reason }, ids);
export const undo = (batchId) => run("undo", { batch_id: batchId });

export async function mergeChecked() {
  const ids = nodes.get().checked.slice();
  if (ids.length < 2) return null;
  const r = await run("merge", { node_ids: ids }, ids);
  if (r) nodes.set({ checked: [] });
  return r;
}

export async function addSelectionTo(id) {
  const { selection } = nodes.get();
  const r = await run("add_members", { node_id: id, sheet: shell.get().sheet, ids: selection }, [id]);
  if (r) clearSelection();
  return r;
}

export async function removeSelectionFrom(id) {
  const { selection } = nodes.get();
  const r = await run("remove_members", { node_id: id, sheet: shell.get().sheet, ids: selection }, [id]);
  if (r) clearSelection();
  return r;
}

export async function splitSelection(id, name) {
  const { selection } = nodes.get();
  const r = await run("split", { node_id: id, sheet: shell.get().sheet, ids: selection, name: name || undefined }, [id]);
  if (r) { clearSelection(); if (r.node_ids && r.node_ids[0]) focusNode(r.node_ids[0]); }
  return r;
}

export async function removeNode(id, archive) {
  const r = await run("remove", archive ? { node_id: id, archive: true } : { node_id: id }, [id]);
  if (r && r.needs_archive) { nodes.set({ needArchive: id }); return null; }   // 엔진이 코드로 알림: 분석 칸에 판정이 있어 아무것도 지우지 않았다
  if (r) nodes.set({ focus: null, detail: null });
  return r;
}

/** 0.1 구간 파일을 새 판으로 바꾼다(읽기는 파일을 바꾸지 않으므로 사용자가 눌렀을 때 한 번). */
export async function migrate() {
  nodes.set({ busy: true, error: null });
  try {
    await cmd("nodes.migrate", { project_id: nodes.get().list.project_id });
    nodes.set({ busy: false });
    await refresh();
  } catch (e) {
    await afterError(e);
  }
}

export function toggleChecked(id) {
  nodes.set((s) => ({ checked: s.checked.includes(id) ? s.checked.filter((x) => x !== id) : s.checked.concat(id) }));
}

/** 프로젝트가 바뀌었다: 앞 프로젝트의 목록·고른 것·카드를 모두 비우고 새로 읽는다(낡은 판으로 쓰지 않게). */
export function resetForProject() {
  seq++;                                  // 아직 오지 않은 앞 읽기의 답은 버린다
  nodes.set({ list: EMPTY_LIST, sheetView: null, detail: null, selection: [], truncated: false, focus: null, card: null, checked: [], error: null, needArchive: null, busy: false });
  refresh();
}

// ---------------------------------------------------------------- 엔진 알림 연결(한 번만)
let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "nodes") refresh(); });
  on("chat.answer", () => { setTimeout(refresh, 150); });   // 채팅이 구간을 만들었을 수 있다
  let lastProject = shell.get().drawings.project_id;
  let last = null;
  shell.subscribe((s) => {
    const pid = s.drawings.project_id;
    if (pid !== lastProject) { lastProject = pid; resetForProject(); }
    if (s.sheet !== last) { last = s.sheet; nodes.set({ selection: [], truncated: false, card: null, sheetView: null }); loadSheet(s.sheet); }
  });
  refresh();
}
