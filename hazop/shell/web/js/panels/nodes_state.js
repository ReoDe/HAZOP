// 구간(2단계)의 화면 상태와 엔진 잇기. 저장하는 자료는 엔진만 쓴다: 여기는 읽어 온 판(list·sheetView)과 보기 상태(고른 것·강조·카드)만 들고,
// 쓰기는 명령으로 보낸 뒤 엔진 답과 `changed("nodes")`로 다시 읽는다. 낙관적 갱신을 하지 않는다(규격 §5.3).
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store as shell } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";
import { openSheet as openSheetVia } from "./results_state.js";
import { blankCard, catchUpText, errorText, targetsOf } from "./nodes_logic.js";

const EMPTY_LIST = {project_id: null,  available: false, set_rev: 0, nodes: [], batches: [], outside: { count: 0, total: 0 }, stale: false, read_only: null, pending_ai: 0 };

export const nodes = createStore({
  list: EMPTY_LIST,         // GET nodes
  sheetView: null,          // GET nodes/sheet/<graph_id>: {graph_id, segments, outside_ids}
  detail: null,             // GET nodes/node/<id>
  mode: "pan",              // "pan" | "pick"
  selection: [],            // 지금 도면에서 고른 local_id
  picks: {},                // 다른 도면에서 묶어 둔 고름: graph_id → local_id 목록(도면을 넘어가도 남는다)
  truncated: false,         // 2,000개를 넘겨 골라 앞 2,000개만 남았음
  focus: null,              // 강조한 구간 ID
  card: null,               // 새 구간 카드
  scope: "sheet",           // 목록 범위: "sheet"(이 도면) | "all"
  showOutside: true,        // 구간 밖 구성요소를 흐리게
  checked: [],              // 줄 옆 체크로 고른 구간(지우기·모두 확정)
  members: {},              // 고른 구간의 구성원: graph_id → local_id 목록(Ctrl로 고칠 때 더함·뺌을 가른다)
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
let reading = null;          // 지금 도는 목록 읽기(명령이 그 판을 기다렸다 보낸다)

export function loadList() {
  const p = loadListNow();
  reading = p;
  p.catch(() => {}).then(() => { if (reading === p) reading = null; });
  return p;
}

async function loadListNow() {
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
  nodes.set((s) => ({ sheetView: v, members: membersWith(s.members, v, s.focus) }));
  return v;
}

/** 도면 하나의 구간 보기에서 고른 구간의 구성원을 적는다. */
function membersWith(members, view, focus) {
  if (!view || !focus) return members;
  const seg = (view.segments || []).find((x) => x.node_id === focus);
  return Object.assign({}, members, { [view.graph_id]: seg ? seg.ids : [] });
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
export function setSelection(ids, truncated = false) {
  // 다음 구간을 고르기 시작하면 앞서 만든 구간의 카드는 닫는다(고친 것이 없으면 잃을 것이 없고, 고친 것은 저장을 눌러야 남는다)
  nodes.set((s) => ({ selection: ids, truncated: !!truncated, card: s.card && s.card.made && ids.length && s.card.name === s.card.saved.name && (s.card.intent || "") === (s.card.saved.intent || "") ? null : s.card }));
}
export function clearSelection() { nodes.set({ selection: [], picks: {}, truncated: false }); }

/** 묶어 둔 고름 전부 [{sheet, ids}]: 지금 도면 것이 앞이다. */
export function pickParts(s = nodes.get()) {
  const here = shell.get().sheet;
  return (here && s.selection.length ? [{ sheet: here, ids: s.selection }] : [])
    .concat(Object.entries(s.picks).filter(([g, ids]) => g !== here && ids.length).map(([sheet, ids]) => ({ sheet, ids })));
}
export const pickedIds = (s = nodes.get()) => pickParts(s).flatMap((p) => p.ids);

/** 명령에 싣는 고름: 첫 도면은 sheet·ids, 나머지 도면은 more. 고름이 없으면 null. */
function pickArgs() {
  const [first, ...more] = pickParts();
  return first ? Object.assign({ sheet: first.sheet, ids: first.ids }, more.length ? { more } : {}) : null;
}

/** 도면이 바뀔 때: 떠나는 도면의 고름은 남겨 두고, 여는 도면에서 묶던 것을 되살린다. */
function swapPicks(from, to) {
  nodes.set((s) => {
    const picks = Object.assign({}, s.picks);
    if (from) { if (s.selection.length) picks[from] = s.selection; else delete picks[from]; }
    const selection = (to && picks[to]) || [];
    if (to) delete picks[to];
    return { picks, selection, card: null, sheetView: null };
  });
}

/** 구간을 고른다(다시 고르면 푼다). show: 그 구간의 구성요소가 가장 많은 도면을 열고 도면 전체를 보이는 채로 강조한다(확대해 들어가지 않는다). */
export function focusNode(id, { show = false } = {}) {
  const same = nodes.get().focus === id;
  if (nodes.get().focus && pickParts().length) clearSelection();
  const next = same ? null : id;
  nodes.set((s) => ({ focus: next, detail: same ? null : s.detail, error: null, needArchive: null, members: membersWith({}, s.sheetView, next) }));
  if (same) return;
  loadDetail(id);
  if (show) showNode(id);
}

export function unfocus() {
  if (!nodes.get().focus) return;
  if (pickParts().length) clearSelection();
  nodes.set({ focus: null, detail: null, members: {} });
}

/** Ctrl로 바로 고칠 구간: 구간 탭에서 고른, 잠기지 않은 구간. 없으면 null(그때의 Ctrl 고름은 '구간 만들기'). */
export function editTarget(s = nodes.get()) {
  if (shell.get().panel !== "nodes" || !s.focus) return null;
  const row = s.list.nodes.find((n) => n.node_id === s.focus);
  return row && row.state !== "locked" ? row : null;
}

/** 묶어 둔 고름을 고른 구간에 대한 변경으로 가른다: 구간에 없던 것은 더함, 이미 든 것은 뺌. */
export function pickDiff(s = nodes.get()) {
  const add = [], remove = [];
  for (const part of pickParts(s)) {
    const have = new Set(s.members[part.sheet] || []);
    const fresh = part.ids.filter((i) => !have.has(i)), old = part.ids.filter((i) => have.has(i));
    if (fresh.length) add.push({ sheet: part.sheet, ids: fresh });
    if (old.length) remove.push({ sheet: part.sheet, ids: old });
  }
  const count = (parts) => parts.reduce((n, x) => n + x.ids.length, 0);
  return { add, remove, added: count(add), removed: count(remove) };
}

/** 고치던 것을 한 번에 저장한다(nodes.edit_members). 보내기 전에 고른 도면마다 구성원을 다시 읽는다. 거절되면 아무것도 바뀌지 않고 고름이 남는다. */
export async function applyEdit() {
  const target = editTarget();
  if (!target || nodes.get().busy || !pickParts().length) return null;
  const id = target.node_id;
  for (const part of pickParts()) {
    let v = null;
    try { v = await read("nodes/sheet/" + encodeURIComponent(part.sheet)); } catch (e) { v = null; }
    if (nodes.get().focus !== id) return null;
    if (v) nodes.set((s) => ({ members: membersWith(s.members, v, id) }));
  }
  const { add, remove } = pickDiff();
  const r = await run("edit_members", Object.assign({ node_id: id }, add.length ? { add } : {}, remove.length ? { remove } : {}), [id]);
  if (r) { clearSelection(); loadDetail(id); }
  return r;
}

export const fitSheet = () => shell.set((s) => ({ command: { seq: s.command.seq + 1, type: "fit" } }));

/** 구성요소가 가장 많은 도면(같으면 지금 도면, 그다음 앞의 것). */
export function mainSheetOf(row, current) {
  const sheets = (row && row.sheets) || [];
  let best = null;
  for (const x of sheets) if (!best || x.n > best.n || (x.n === best.n && x.graph_id === current)) best = x;
  return best ? best.graph_id : null;
}

export function showNode(id) {
  const target = mainSheetOf(nodes.get().list.nodes.find((n) => n.node_id === id), shell.get().sheet);
  if (target) goToSheet(target);
}

export function openPanel() { shell.set({ panel: "nodes" }); }

/** 도면으로 간다(같은 도면이면 전체 맞춤). 도면을 바꾸는 길은 분석 결과의 '도면에서 보기'와 같고, 새 도면은 늘 전체 맞춤으로 열린다.
 *  고른 구간은 그대로라 넘어간 도면에서도 강조가 보인다. */
export async function goToSheet(graphId) {
  if (!graphId) return false;
  if (shell.get().sheet !== graphId) {
    if (!openSheetVia(graphId)) return false;
  } else fitSheet();
  await loadSheet(graphId);
  return true;
}

/** 다른 도면 연결(오각형)을 누름: 이어진 연결이면 맞은편 도면으로 간다. */
export function followLink(link) {
  if (!link || link.status !== "linked" || !link.peer_graph_id) return false;
  const from = shell.get().sheet, target = link.peer_graph_id, picking = pickParts().length > 0 && !editTarget();      // 고치는 중에는 저절로 더하지 않는다
  goToSheet(target).then((ok) => { if (ok && picking && from && from !== target) markCameFrom(from, target); });
  return true;
}

/** 묶던 중에 넘어온 도면에서는 떠나온 도면을 가리키는 연결 기호를 묶음에 넣어, 어디서 왔는지 보이게 한다(구간에 넣을지는 엔진이 정한다). */
function markCameFrom(from, target) {
  const view = nodes.get().sheetView;
  if (shell.get().sheet !== target || !view || view.graph_id !== target) return;
  const back = (view.links || []).filter((l) => l.status === "linked" && l.peer_graph_id === from).map((l) => l.id);
  if (back.length) nodes.set((s) => ({ selection: Array.from(new Set(s.selection.concat(back))) }));
}

export function dismissError() { nodes.set({ error: null, needArchive: null }); }

// ---------------------------------------------------------------- 카드
/** '구간 만들기'(또는 고른 뒤 Enter): 제안 이름으로 바로 만들고, 만든 구간의 이름·설계 의도를 고치는 카드를 연다(실제 창 4차: 2단 → 1단).
 *  잘못 만들었으면 그 카드의 '되돌리기'(만든 묶음 되돌리기)나 구간 패널의 지우기로 푼다. 제안 이름이 없으면 '구간 S<n>'. */
export async function openCard() {
  const args = pickArgs();
  if (!args) return;
  if (nodes.get().card && !nodes.get().card.made) return;      // 만드는 중
  nodes.set({ card: blankCard({ busy: true, loading: true }) });
  try {
    const sg = await cmd("nodes.suggest", Object.assign({ project_id: nodes.get().list.project_id }, args));
    if (!nodes.get().card) return null;                          // 그새 Esc로 닫음: 만들지 않는다
    const list = nodes.get().list.nodes;
    const fallback = "구간 S" + (Math.max(0, ...list.map((n) => parseInt(String(n.node_id).slice(1), 10) || 0)) + 1);
    nodes.set((s) => ({ card: Object.assign({}, s.card, { busy: false, loading: false, suggest: sg, name: s.card.name || sg.name || fallback }) }));
    return submitCard();
  } catch (e) {
    if (await selectExisting(e)) return null;
    if (nodes.get().card) nodes.set((s) => ({ card: Object.assign({}, s.card, { busy: false, loading: false, submitWhenReady: false, error: errorText(e) }) }));
  }
  return null;
}

export function editCard(patch) { nodes.set((s) => ({ card: s.card ? Object.assign({}, s.card, patch) : s.card })); }
export function closeCard() { nodes.set({ card: null }); }

/** 만든 구간 카드의 '되돌리기': 만든 묶음을 되돌린다(구간이 사라진다). */
export async function undoMade() {
  const c = nodes.get().card;
  if (!c || !c.made || c.busy) return null;
  editCard({ busy: true });
  const r = c.batch ? await undo(c.batch) : null;
  nodes.set({ card: null });
  return r;
}

export async function submitCard() {
  const { card, selection, picks, list } = nodes.get(), args = pickArgs();
  if (card && card.loading) return null;                          // 만드는 중(제안 이름이 오면 저절로 만든다)
  if (!card || card.busy) return null;
  if (card.made) return saveMade(card);
  if (!card.name.trim()) { editCard({ error: "구간 이름을 입력하세요." }); return null; }
  editCard({ busy: true, error: null });
  try {
    const r = await cmd("nodes.create", Object.assign({ project_id: list.project_id }, args, { name: card.name.trim(), design_intent: card.intent.trim() || undefined, set_rev: list.set_rev }));
    remember("create", [r && r.batch_id]);
    // 고르기 모드는 그대로: 다음 구간을 바로 끌어 고른다(HZ-DSN-06 U9, Esc·이동 단추로 끈다). 응답을 기다리는 사이 새로 고른 것은 남긴다
    const made = r.node_ids && r.node_ids[0];
    const after = made ? Object.assign(blankCard({ made, batch: r.batch_id, name: card.name.trim(), intent: card.intent || "", suggest: card.suggest }), { saved: { name: card.name.trim(), intent: card.intent || "" } }) : null;
    nodes.set((s) => (s.selection === selection && s.picks === picks ? { card: after, selection: [], picks: {}, truncated: false } : { card: after }));
    await refresh();
    if (made) focusNode(made);
    return r;
  } catch (e) {
    if (await selectExisting(e)) return null;
    await afterError(e);
    editCard({ busy: false, error: errorText(e) });
    return null;
  }
}

/** 같은 구성요소의 구간이 이미 있어서 만들지 않은 것은 사용자가 할 일이 없다: 아무 알림 없이 카드를 닫고 그 구간을 고른 상태로 둔다. 맞으면 참. */
const DUPLICATE = /^(?:.*?: )?구성요소가 같은 구간 (\S+?)가 이미 있음$/;
async function selectExisting(e) {
  const m = DUPLICATE.exec(String(errorText(e) || "").trim());
  if (!m) return false;
  nodes.set({ card: null, selection: [], picks: {}, truncated: false, error: null, busy: false });
  await refresh();
  if (nodes.get().focus !== m[1]) focusNode(m[1]);
  return true;
}

/** 만든 구간 카드의 저장(Enter): 고친 이름·설계 의도만 보내고 카드를 닫는다. 안 고쳤으면 닫기만. */
async function saveMade(card) {
  const name = card.name.trim(), intent = (card.intent || "").trim();
  if (!name) { editCard({ error: "구간 이름을 입력하세요." }); return null; }
  editCard({ busy: true, error: null });
  let ok = true;
  if (name !== card.saved.name) ok = !!(await rename(card.made, name));
  if (ok && intent !== (card.saved.intent || "").trim()) ok = !!(await setIntent(card.made, intent));
  if (!ok) { editCard({ busy: false, error: nodes.get().error }); return null; }
  nodes.set({ card: null });
  return true;
}

// ---------------------------------------------------------------- 되돌리기 잇기(undo.js가 건다)
let history = null;
export function setHistory(h) { history = h; }
/** 저장에 성공한 묶음들을 한 단계의 '되돌리기'로 쌓는다: 뒤 묶음부터 되돌린다. */
function remember(label, batches) {
  const list = batches.filter(Boolean);
  if (!history || !list.length) return;
  history.push(label, async () => { for (const b of list.slice().reverse()) if (!(await undo(b))) return false; return true; }, list);
}

// ---------------------------------------------------------------- 명령
async function afterError(e) {
  nodes.set({ error: errorText(e), busy: false });
  shell.set({ toast: { text: errorText(e), kind: "err" } });      // 패널 위 안내는 목록을 내려 본 사람에게 안 보일 수 있다: 토스트로도 알린다
  if (e && (e.code === "stale" || e.code === "not_found")) await refresh();
}

/** 구간 명령 하나. 화면이 본 판(set_rev, 대상 rev·state)을 함께 보낸다. 거절되면 엔진 사유를 error에 둔다. */
export async function run(name, args, targetIds, { keep = true } = {}) {
  nodes.set({ busy: true, error: null, needArchive: null });
  if (reading) { try { await reading; } catch (e) { /* 읽기 실패: 가진 판으로 보낸다(엔진이 판을 대조한다) */ } }   // 패널을 열며 읽는 중이면 그 판으로 보낸다
  const { list } = nodes.get();
  try {
    const r = await cmd("nodes." + name, Object.assign({ project_id: list.project_id, set_rev: list.set_rev }, args, targetIds && targetIds.length ? { targets: targetsOf(list.nodes, targetIds) } : {}));
    nodes.set({ busy: false });
    if (r && r.skipped_text) shell.set({ toast: { text: r.skipped_text, kind: "info" } });   // 구성요소가 아니라 뺀 선이 있으면 알린다
    if (keep && name !== "undo" && r && r.batch_id) remember(name, [r.batch_id]);
    await refresh();
    return r;
  } catch (e) {
    await afterError(e);
    return null;
  }
}

export const rename = (id, name) => run("rename", { node_id: id, name }, [id]);
export const setIntent = (id, text) => run("set_intent", { node_id: id, text }, [id]);
export const unlock = (ids, reason) => run("unlock", { node_ids: ids, reason }, ids);
export async function undo(batchId) {
  const r = await run("undo", { batch_id: batchId });
  if (r && history) history.forget(batchId);      // 작업 기록·카드에서 되돌린 묶음은 Ctrl+Z 쌓임에서도 뺀다
  return r;
}
/** 찾지 못한 구성요소를 사람이 확인하고 버린다(keys는 상세의 lost_items key). 되돌리기 묶음으로 남는다. */
export const discardLost = (id, keys) => run("discard_lost", { node_id: id, keys }, [id]);

/** 줄 옆 체크로 여러 구간을 한 번에 고르거나 해제한다. */
export function setChecked(ids, on) {
  nodes.set((s) => ({ checked: on ? Array.from(new Set(s.checked.concat(ids))) : s.checked.filter((x) => !ids.includes(x)) }));
}

/** 고른 구간을 확인 창 없이 지운다. 잠긴 구간은 건드리지 않는다. 분석 칸에 판정이 있으면 엔진의 '보관하고 지우기'를 쓴다(칸은 결과 파일의
 *  보관 목록으로 간다). → 지운 묶음 ID 목록. */
export async function removeMany(ids) {
  const batches = [];
  for (const id of ids) {
    const row = nodes.get().list.nodes.find((n) => n.node_id === id);
    if (!row || row.state === "locked") continue;
    let r = await run("remove", { node_id: id }, [id], { keep: false });
    if (r && r.needs_archive) r = await run("remove", { node_id: id, archive: true }, [id], { keep: false });
    if (!r) break;
    if (r.batch_id) batches.push(r.batch_id);
  }
  nodes.set((s) => ({ checked: s.checked.filter((x) => s.list.nodes.some((n) => n.node_id === x && n.state === "locked")) }));
  if (!nodes.get().list.nodes.some((n) => n.node_id === nodes.get().focus)) nodes.set({ focus: null, detail: null, members: {} });
  remember("remove", batches);
  return batches;
}

export async function splitSelection(id, name) {
  const r = await run("split", Object.assign({ node_id: id, name: name || undefined }, pickArgs()), [id]);
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

/** 다시 추출 뒤 판 이전을 지금 한다(읽기는 파일을 바꾸지 않으므로 사용자가 누른다). 끝나면 이어진 수와 되찾지 못한 묘비 수를 알린다. */
export async function catchUp() {
  nodes.set({ busy: true, error: null });
  try {
    const r = await cmd("nodes.catch_up", { project_id: nodes.get().list.project_id });
    nodes.set({ busy: false });
    if (r && r.changed && r.tombstones) shell.set({ toast: { text: catchUpText(r), kind: "info" } });      // 찾지 못한 구성요소가 있을 때만 알린다
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
  nodes.set({ list: EMPTY_LIST, sheetView: null, detail: null, selection: [], picks: {}, truncated: false, focus: null, members: {}, card: null, checked: [], error: null, needArchive: null, busy: false });
  refresh();
}

// ---------------------------------------------------------------- 엔진 알림 연결(한 번만)
let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  // 구간 목록은 프로젝트 그래프에서 나온다: 도면 등록·원본 선택·도면 연결이 바뀌어도 다시 읽는다('프로젝트 그래프가 아직 없습니다'가 남지 않게)
  onChanged((topic) => { if (topic === "nodes" || topic === "drawings" || topic === "sources" || topic === "links") refresh(); });
  on("chat.answer", () => { setTimeout(refresh, 150); });   // 채팅이 구간을 만들었을 수 있다
  let lastProject = shell.get().drawings.project_id;
  let last = shell.get().sheet;
  if (last) loadSheet(last);
  let lastPanel = shell.get().panel;
  shell.subscribe((s) => {
    if (s.panel !== lastPanel) {
      const left = lastPanel === "nodes" && s.panel !== "nodes";
      lastPanel = s.panel;
      if (left && nodes.get().focus && pickParts().length) clearSelection();
    }
    const pid = s.drawings.project_id;
    if (pid !== lastProject) { lastProject = pid; resetForProject(); }
    if (s.sheet !== last) { const from = last; last = s.sheet; swapPicks(from, s.sheet); loadSheet(s.sheet); }
  });
  refresh();
}
