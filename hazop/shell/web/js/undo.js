// 전체 되돌리기(Ctrl+Z): 사용자가 방금 한 행동을 하나씩 되돌린다. 쌓임은 여기 한 곳이다.
// - 보기 동작(도면 이동·확대, 도면 바꿈, 원본·정리, Ctrl 고름, 구간 고름)은 따로 알리지 않는다. 사용자 조작(누름·휠·키)이 시작될 때의
//   상태를 기억해 두고 조작이 끝나면 견줘, 달라졌으면 그 앞 상태를 한 단계로 쌓는다. 한 번 눌러 도면·구간·자리가 함께 바뀌어도 한 단계다.
//   휠을 이어 굴린 것은 한 묶음이다.
// - 저장되는 행동은 성공한 곳(구간 상태·도면 지우기)이 되돌리는 길을 pushSaved로 쌓는다. 그 조작의 보기 변화는 따로 쌓지 않는다.
// - 입력 칸에 초점이 있으면 그 칸의 글자 되돌리기로 둔다. 다시 하기(Ctrl+Y·Ctrl+Shift+Z)는 보기 동작만이다.
import { store } from "./store.js";
import * as N from "./panels/nodes_state.js";
import { openSheet } from "./panels/results_state.js";
import { clean, setView, viewOf } from "./canvas/clean_ui.js";

export const DEPTH = 50;
const IDLE_MS = 800;          // 조작이 끝났다고 보는 조용한 시간(도면을 다시 읽거나 맞추는 일까지 한 단계에 담는다)
const WHEEL_MS = 600;         // 이 안에 이어진 휠은 한 묶음

let undos = [], redos = [], pending = null, busy = false, lastView = null, timer = null, pointerAt = 0;

export function reset() { undos = []; redos = []; pending = null; clearTimeout(timer); }
export const sizes = () => [undos.length, redos.length];

function push(entry) {
  undos.push(entry);
  if (undos.length > DEPTH) undos.splice(0, undos.length - DEPTH);
}

// ---------------------------------------------------------------- 보기 상태
export function snapshot() {
  const s = store.get(), n = N.nodes.get(), gid = s.sheet;
  return { sheet: gid, view: lastView && lastView.sheet === gid ? lastView : null, mode: gid && clean.get().data[gid] ? viewOf(clean.get(), gid) : null,
    selection: n.selection.slice(), picks: Object.assign({}, n.picks), focus: n.focus, panel: s.panel };
}

const idsKey = (x) => JSON.stringify([x.selection.slice().sort(), Object.keys(x.picks).sort().map((g) => [g, x.picks[g].slice().sort()])]);
/** 두 상태가 되돌릴 만큼 다른가. 패널을 바꾼 것만으로는 쌓지 않는다. */
export function differs(a, b) {
  if (a.sheet !== b.sheet || a.focus !== b.focus || idsKey(a) !== idsKey(b)) return true;
  if (a.mode && b.mode && a.mode !== b.mode) return true;
  const u = a.view, v = b.view;
  return !!(u && v && (Math.abs(u.x - v.x) > 0.5 || Math.abs(u.y - v.y) > 0.5 || Math.abs(u.k - v.k) > u.k * 0.002));
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function restore(to) {
  if (to.sheet && store.get().sheet !== to.sheet) {
    if (!openSheet(to.sheet)) store.set({ sheet: to.sheet });
    for (let i = 0; i < 100 && store.get().readySheet !== to.sheet; i++) await wait(50);
  }
  if (to.mode && to.sheet && viewOf(clean.get(), to.sheet) !== to.mode) setView(to.sheet, to.mode);
  const n = N.nodes.get();
  if (n.focus !== to.focus) {
    N.nodes.set({ focus: to.focus, detail: null, members: {} });
    if (to.focus) N.loadDetail(to.focus);
  }
  if ((to.focus || to.selection.length || Object.keys(to.picks).length) && to.panel === "nodes" && store.get().panel !== "nodes") store.set({ panel: "nodes" });
  N.nodes.set({ selection: to.selection.slice(), picks: Object.assign({}, to.picks), truncated: false });
  store.set({ marks: { rid: null, bySheet: {} }, bubble: null });
  if (to.sheet) await N.loadSheet(to.sheet);
  if (to.view) {
    await wait(60);
    const view = { x: to.view.x, y: to.view.y, k: to.view.k };
    store.set((s) => ({ command: { seq: s.command.seq + 1, type: "view", view } }));
  }
}

// ---------------------------------------------------------------- 사용자 조작
/** 모아 둔 조작을 끝낸다: 앞 상태와 달라졌으면 한 단계로 쌓는다. */
export function commit() {
  clearTimeout(timer);
  const p = pending;
  pending = null;
  if (!p || busy) return;
  if (differs(p.before, snapshot())) { push({ kind: "view", state: p.before }); redos = []; }
}

function later() { clearTimeout(timer); timer = setTimeout(commit, IDLE_MS); }

function begin(kind) {
  if (busy) return;
  if (kind === "wheel" && pending && pending.kind === "wheel" && Date.now() - pending.at < WHEEL_MS) { pending.at = Date.now(); later(); return; }
  commit();
  pending = { kind, at: Date.now(), before: snapshot() };
  later();
}

/** 저장되는 행동 하나. back: 되돌리는 비동기 함수(성공하면 참). batches: 그 행동의 엔진 묶음(다른 길로 되돌리면 쌓임에서 뺀다). */
export function pushSaved(label, back, batches = []) {
  if (busy) return;
  pending = null;          // 이 조작의 보기 변화(고름 비움·새 구간 고름)는 저장 행동 한 단계에 든다
  clearTimeout(timer);
  push({ kind: "saved", label, back, batches });
  redos = [];
}

export function forgetBatch(batchId) { undos = undos.filter((e) => !(e.kind === "saved" && e.batches.includes(batchId))); }
N.setHistory({ push: pushSaved, forget: forgetBatch });

export async function undoOne() {
  if (busy) return false;
  commit();
  const entry = undos.pop();
  if (!entry) return false;
  busy = true;
  try {
    if (entry.kind === "view") {
      redos.push({ kind: "view", state: snapshot() });
      await restore(entry.state);
    } else {
      redos = [];          // 저장되는 행동은 다시 하기를 두지 않는다
      await entry.back();
    }
    await wait(150);
  } finally { busy = false; pending = null; }
  return true;
}

export async function redoOne() {
  if (busy) return false;
  commit();
  const entry = redos.pop();
  if (!entry) return false;
  busy = true;
  try {
    push({ kind: "view", state: snapshot() });
    await restore(entry.state);
    await wait(150);
  } finally { busy = false; pending = null; }
  return true;
}

const typing = (t) => !!(t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || "")) && !/^(checkbox|radio|button)$/.test(t.type || ""));

let wired = false;
export function wireUndo() {
  if (wired || typeof document === "undefined") return;
  wired = true;
  document.addEventListener("hz-view", (e) => { lastView = Object.assign({ sheet: store.get().readySheet || store.get().sheet }, e.detail); }, true);
  window.addEventListener("keydown", (e) => {
    const k = (e.key || "").toLowerCase(), mod = e.ctrlKey || e.metaKey;
    if (mod && !e.altKey && (k === "z" || k === "y")) {
      if (typing(e.target)) return;          // 입력 칸의 글자 되돌리기는 그대로
      e.preventDefault();
      e.stopImmediatePropagation();
      if (k === "y" || e.shiftKey) redoOne(); else undoOne();
      return;
    }
    if (e.repeat || ["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
    begin("key");
  }, true);
  document.addEventListener("pointerdown", () => { pointerAt = Date.now(); begin("pointer"); }, true);
  document.addEventListener("pointerup", () => { if (pending && !busy) later(); }, true);
  document.addEventListener("click", () => { if (Date.now() - pointerAt > 1500) begin("click"); }, true);      // 누름 없이 온 누르기(키보드·보조 기기)
  document.addEventListener("wheel", () => begin("wheel"), { capture: true, passive: true });
  let project = store.get().drawings.project_id;
  store.subscribe((s) => { if (s.drawings.project_id !== project) { project = s.drawings.project_id; reset(); } });
}
