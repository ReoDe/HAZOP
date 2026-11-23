// 검토 대기열의 화면 상태(규격 HZ-DSN-06 §3.3, 단위 U5). 엔진 읽기 queue/ai·queue/lost(hazop/shell/api_queue.py)로 항목을 받고,
// 판정은 지금 있는 명령을 그대로 부른다(새 저장 길 없음): AI 후보 aireview.accept·reject·revert·accept_bulk, 고쳐서 수락 edit.apply → aireview.reject,
// 찾지 못한 구성요소 nodes.discard_lost·undo. 대기열을 연 동안의 항목 목록(수락·거절·건너뜀 표시)은 여기서 들고, 저장한 뒤에는 엔진을 다시 읽어
// 남은 항목의 판(ver·set_rev·target)만 바꾼다. 같은 도면은 판정마다 판이 바뀌므로 늘 다시 읽은 판으로 보낸다.
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, read } from "../bridge.js";

const START = { open: false, kind: null, gid: null, items: [], i: 0, undo: [], busy: false, error: null, note: null, editing: null, ask: null,
  bulkAsk: false, done: false, setRev: null, projectId: null, bulk: [] };
export const q = createStore(Object.assign({}, START));

export function useQueue(selector) {
  const [value, setValue] = useState(() => selector(q.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const n = selector(s); setValue((p) => (Object.is(p, n) ? p : n)); };
    sync(q.get());
    return q.subscribe(sync);
  }, []);
  return value;
}

export const STALE_TEXT = "그 사이 도면이 바뀌었습니다. 대기열을 다시 만들었습니다.";
export const LINK_LATER = "같은 구성요소로 잇는 기능은 아직 없습니다. 거절(R)로 지워진 것으로 두거나 건너뛰기(Space)를 누르세요.";
const errorText = (e) => (e && e.message) || "처리하지 못했습니다.";

export const current = (s = q.get()) => s.items[s.i] || null;
export function counts(s = q.get()) {
  const c = { accepted: 0, rejected: 0, skipped: 0, open: 0 };
  for (const it of s.items) c[it.state] = (c[it.state] || 0) + 1;
  return c;
}
/** 묶음 수락에 들 항목(열린 것 가운데 엔진이 묶어도 된다고 한 것). */
export const bulkItems = (s = q.get()) => s.items.filter((x) => x.state === "open" && x.bulk);

// ---------------------------------------------------------------- 열기·다시 읽기
let seq = 0;
async function fetchQueue(kind, gid) { return read("queue/" + kind + (gid ? "?graph_id=" + encodeURIComponent(gid) : "")); }

/** 대기열을 연다. AI 후보는 도면별이다(gid가 있으면 그 도면의 후보만). 열 항목이 없으면 열지 않고 false. */
export async function openQueue(kind, gid = null) {
  const mine = ++seq;
  let d = null;
  try { d = await fetchQueue(kind, gid); } catch (e) { d = null; }
  if (mine !== seq) return false;
  if (!d || !d.items || !d.items.length) {
    store.set({ toast: { text: kind === "ai" ? "확인할 AI 후보가 없습니다." : "다시 확인할 구성요소가 없습니다." } });
    return false;
  }
  q.set(Object.assign({}, START, { open: true, kind, gid, items: d.items.map((x) => Object.assign({}, x)), setRev: d.set_rev ?? null,
    projectId: d.project_id || null, bulk: d.bulk || [] }));
  store.set({ panel: null });
  show();
  return true;
}

/** 엔진을 다시 읽어 열린 항목의 판만 바꾼다(판정한 항목은 다음 읽기에서 빠지므로 목록은 그대로 둔다). */
export async function fresh() {
  const s = q.get();
  if (!s.open) return;
  let d = null;
  try { d = await fetchQueue(s.kind, s.gid); } catch (e) { return; }
  const by = new Map((d.items || []).map((x) => [x.qid, x]));
  q.set((cur) => ({ setRev: d.set_rev ?? cur.setRev, bulk: d.bulk || [],
    items: cur.items.map((x) => (by.has(x.qid) ? Object.assign({}, by.get(x.qid), { state: x.state }) : x)) }));
}

export function closeQueue() {
  seq++;
  q.set(Object.assign({}, START));
  store.set({ marks: { rid: null, bySheet: {} } });
}

// ---------------------------------------------------------------- 도면에 보이기
function bump(command) { store.set((s) => ({ command: Object.assign({ seq: s.command.seq + 1 }, command) })); }

/** 지금 건의 도면을 열고 그 자리로 확대한다. 지금 건은 파란 테두리와 번호, 같은 도면에서 처리한 것은 옅은 테두리로 남긴다. */
export function show() {
  const s = q.get(), it = current(s);
  if (!it || !it.graph_id) return;
  const gid = it.graph_id;
  const done = s.items.filter((x) => x.graph_id === gid && x.state !== "open" && x.local_id).map((x) => x.local_id);
  const groups = [];
  if (done.length) groups.push({ ids: done, style: "muted" });
  if (it.local_id) groups.push({ ids: [it.local_id], style: "focus", label: String(s.i + 1) });
  const opened = store.get().sheet !== gid;
  store.set({ sheet: gid, panel: null, marks: { rid: "queue", bySheet: { [gid]: groups.length ? [{ id: "queue", op: "mark", groups, dim_others: true }] : [] } } });
  if (opened) cmd("sheet.open", { graph_id: gid }).catch(() => {});
  if (!it.local_id) return;
  if (opened) [350, 900, 1800].forEach((ms) => setTimeout(() => { if (store.get().sheet === gid && current() === it) bump({ type: "zoomTo", ids: [it.local_id], pad: 4 }); }, ms));
  else bump({ type: "zoomTo", ids: [it.local_id], pad: 4 });
}

/** 다음 열린 항목으로(뒤에 없으면 앞에서 찾는다). 열린 것이 없으면 끝 화면. */
function advance() {
  const s = q.get();
  const n = s.items.length;
  for (let k = 1; k <= n; k++) {
    const j = (s.i + k) % n;
    if (s.items[j].state === "open") { q.set({ i: j, done: false, editing: null, ask: null }); show(); return; }
  }
  q.set({ done: true, editing: null, ask: null });
  store.set({ marks: { rid: null, bySheet: {} } });
}

function mark(qids, state) {
  q.set((s) => ({ items: s.items.map((x) => (qids.includes(x.qid) ? Object.assign({}, x, { state }) : x)) }));
}

async function run(fn) {
  if (q.get().busy) return null;
  q.set({ busy: true, error: null, note: null });
  try {
    const r = await fn();
    q.set({ busy: false });
    return r;
  } catch (e) {
    q.set({ busy: false, error: e && e.code === "stale" ? STALE_TEXT : errorText(e) });
    if (e && e.code === "stale") await fresh();
    return null;
  }
}

/** 이 도면 AI 후보의 지금 판(그 도면 항목을 모두 판정해 대기열에 없을 때도 되돌리기에 쓴다). */
async function aiVer(gid) {
  const it = q.get().items.find((x) => x.graph_id === gid && x.state === "open");
  if (it) return it.ver;
  const v = await read("aireview/" + encodeURIComponent(gid));
  return v.ver;
}

// ---------------------------------------------------------------- 판정
export function accept() {
  const it = current();
  if (!it || it.state !== "open" || q.get().done) return null;
  if (it.kind === "lost") { q.set({ note: LINK_LATER }); return null; }
  return run(async () => {
    const r = await cmd("aireview.accept", { graph_id: it.graph_id, cand_ids: [it.cand_id], ver: it.ver });
    if (!r.changed || !r.changed.length) {
      const why = (r.failed && r.failed[0] && r.failed[0].reason) || "바뀐 것이 없습니다.";
      q.set({ error: "수락하지 못했습니다: " + why });
      return r;
    }
    mark([it.qid], "accepted");
    q.set((s) => ({ undo: s.undo.concat([{ type: "ai", qids: [it.qid], parts: [{ graph_id: it.graph_id, cand_ids: [it.cand_id] }] }]) }));
    await fresh();
    advance();
    return r;
  });
}

export function reject() {
  const s = q.get(), it = current(s);
  if (!it || it.state !== "open" || s.done) return null;
  return run(async () => {
    if (it.kind === "ai") {
      const r = await cmd("aireview.reject", { graph_id: it.graph_id, cand_ids: [it.cand_id], ver: it.ver });
      mark([it.qid], "rejected");
      q.set((c) => ({ undo: c.undo.concat([{ type: "ai", qids: [it.qid], parts: [{ graph_id: it.graph_id, cand_ids: [it.cand_id] }] }]) }));
      await fresh(); advance();
      return r;
    }
    const r = await cmd("nodes.discard_lost", { project_id: s.projectId, set_rev: s.setRev, targets: [it.target], node_id: it.node_id, keys: [it.key] });
    mark([it.qid], "rejected");
    q.set((c) => ({ undo: c.undo.concat([{ type: "lost", qids: [it.qid], batch_id: r.batch_id }]) }));
    await fresh(); advance();
    return r;
  });
}

export function skip() {
  const it = current();
  if (!it || it.state !== "open" || q.get().done) return;
  mark([it.qid], "skipped");
  q.set({ error: null, note: null });
  advance();
}

/** E: 값 고쳐서 수락. 태그·정상 위치·고장 위치만(다른 필드는 도면 고치기에서). */
export function startEdit() {
  const it = current();
  if (!it || it.kind !== "ai" || it.state !== "open" || q.get().done) return;
  if (!it.edit_op) { q.set({ note: "이 항목은 값을 바로 고칠 수 없습니다. 거절한 뒤 도면 고치기에서 고치세요." }); return; }
  q.set({ editing: it.proposal || "", ask: null, error: null, note: null });
}
export function setEditing(v) { q.set({ editing: v }); }
export function cancelEdit() { q.set({ editing: null, ask: null }); }

export function saveEdit() {
  const s = q.get(), it = current(s);
  const v = (s.editing || "").trim();
  if (!it || !v) return null;
  const value = it.edit_op === "set_tag" ? { tag: v } : { value: v };
  return run(async () => {
    const args = { graph_id: it.graph_id, op: it.edit_op, local_id: it.local_id, value, ver: it.ver };
    if (s.ask) args.confirm = s.ask;
    let made;
    try { made = await cmd("edit.apply", args); } catch (e) {
      if (e && e.code === "needs_confirm") { q.set({ ask: e.message }); return null; }    // 태그 겹침 같은 확인: 한 번 더 Enter면 그대로 저장
      throw e;
    }
    await cmd("aireview.reject", { graph_id: it.graph_id, cand_ids: [it.cand_id], ver: made.ver });
    mark([it.qid], "accepted");
    q.set((c) => ({ editing: null, ask: null,
      undo: c.undo.concat([{ type: "edit", qids: [it.qid], graph_id: it.graph_id, cand_ids: [it.cand_id], op_id: made.op_id }]) }));
    await fresh(); advance();
    return made;
  });
}

/** Shift+A: 확신 높은 묶음 수락. 먼저 목록을 보이고(bulkAsk), Enter로 확정한다. 묶음은 엔진이 도면·할 일마다 다시 센다. */
export function askBulk() {
  const s = q.get();
  if (s.kind !== "ai" || s.done) return;
  if (!bulkItems(s).length) { q.set({ note: "한 번에 수락할 만큼 확신이 높은 후보가 없습니다." }); return; }
  q.set({ bulkAsk: true, editing: null, error: null, note: null });
}
export function cancelBulk() { q.set({ bulkAsk: false }); }

export function confirmBulk() {
  const s = q.get();
  if (!s.bulkAsk) return null;
  q.set({ bulkAsk: false });
  return run(async () => {
    const parts = [];
    const vers = {};
    for (const g of s.bulk) {
      const r = await cmd("aireview.accept_bulk", { graph_id: g.graph_id, task: g.task, ver: vers[g.graph_id] || g.ver });
      vers[g.graph_id] = r.ver;
      if (r.changed && r.changed.length) parts.push({ graph_id: g.graph_id, cand_ids: r.changed });
    }
    const qids = parts.flatMap((p) => p.cand_ids.map((c) => "ai|" + p.graph_id + "|" + c));
    mark(qids, "accepted");
    if (qids.length) q.set((c) => ({ undo: c.undo.concat([{ type: "ai", qids, parts }]), note: qids.length + "건을 한 번에 수락했습니다. Z로 한꺼번에 되돌릴 수 있습니다." }));
    await fresh();
    if (current() && current().state !== "open") advance(); else show();
    return parts;
  });
}

/** Z: 바로 앞 판정 되돌리기(대기열을 닫기 전까지 몇 번이든). 건너뛰기는 저장하지 않으므로 되돌리기 쌓임에 없다. */
export function undo() {
  const s = q.get();
  const last = s.undo[s.undo.length - 1];
  if (!last || s.busy) return null;
  return run(async () => {
    if (last.type === "lost") {
      await cmd("nodes.undo", { project_id: s.projectId, set_rev: q.get().setRev, batch_id: last.batch_id });
    } else if (last.type === "edit") {
      const r = await cmd("aireview.revert", { graph_id: last.graph_id, cand_ids: last.cand_ids, ver: await aiVer(last.graph_id) });
      await cmd("edit.undo", { graph_id: last.graph_id, op_id: last.op_id, ver: r.ver });
    } else {
      for (const p of last.parts) await cmd("aireview.revert", { graph_id: p.graph_id, cand_ids: p.cand_ids, ver: await aiVer(p.graph_id) });
    }
    mark(last.qids, "open");
    const j = q.get().items.findIndex((x) => x.qid === last.qids[0]);
    q.set((c) => ({ undo: c.undo.slice(0, -1), i: j < 0 ? c.i : j, done: false, note: "되돌렸습니다." }));
    await fresh();
    show();
    return true;
  });
}

/** 끝 화면의 '건너뛴 n건 다시 보기'. */
export function reviewSkipped() {
  const s = q.get();
  const j = s.items.findIndex((x) => x.state === "skipped");
  if (j < 0) return;
  q.set({ items: s.items.map((x) => (x.state === "skipped" ? Object.assign({}, x, { state: "open" }) : x)), i: j, done: false });
  show();
}

// ---------------------------------------------------------------- 키(§3.3): 대기열이 열려 있고 입력칸에 포커스가 없을 때만
const SHEET_KEYS = new Set(["v", "s", "o", "n", "l", "p", "f"]);
let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  window.addEventListener("keydown", (e) => {
    const s = q.get();
    if (!s.open) return;
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;       // 고치기 입력칸은 자기 Enter·Esc를 쓴다
    const k = e.key, low = k.length === 1 ? k.toLowerCase() : k;
    let hit = true;
    if (s.bulkAsk) {
      if (k === "Enter") confirmBulk(); else if (k === "Escape") cancelBulk(); else hit = false;
    } else if (k === "Escape") closeQueue();
    else if ((low === "z" && !e.altKey) || (e.ctrlKey && low === "z")) undo();
    else if (e.ctrlKey || e.altKey || e.metaKey) hit = false;
    else if (low === "a" && e.shiftKey) askBulk();
    else if (low === "a") accept();
    else if (low === "r") reject();
    else if (k === " ") skip();
    else if (low === "e") startEdit();
    else if (["1", "2", "3"].includes(k)) hit = s.kind === "lost";              // 후보 고르기는 잇기와 함께 들어온다
    else if (SHEET_KEYS.has(low)) hit = true;                                    // 도면 키는 대기열 동안 먹지 않는다
    else hit = false;
    if (hit) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
}
