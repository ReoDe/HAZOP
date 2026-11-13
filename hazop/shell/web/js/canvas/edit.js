// 도면 고치기(INTENT §3.2, 완료 목록 2 A5, 규격 §2.3 '도면 고치기'). 원본 보기·정리된 보기 모두에서 쓴다.
// 늘 떠 있는 것은 작은 '고치기' 단추 하나다(사용자 방침 2026-11-14: 이전 화면의 도구 띠를 옮기지 않고, 고른 것에 맞는 동작만 작은 카드로).
// - 켜면 그 단추가 되돌리기·다시 하기·고친 것 수를 가진 작은 알약이 된다(Ctrl+Z·Ctrl+Shift+Z).
// - 구성요소를 누르면 그 항목의 고치기 카드(태그·종류·위치·흐름 방향·끝 잇기/끊기·연결 추가·경로 다시 그리기·미확인 확정·지우기).
// - 빈 곳을 누르면 그 자리에 기기를 놓는 작은 카드.
// - 여러 번 눌러야 하는 고침(연결 추가·끝 잇기·경로)만 카드 단추로 시작하고, 안내 한 줄과 Esc(그만두기)·Enter(경로 마침)를 쓴다.
// 저장은 엔진(edit.apply·undo·redo, hazop/shell/api_corrections.py)만 한다. 화면이 본 판(ver)을 함께 보내고, 지우기·태그 겹침은 확인을 받는다.
// 도면·모델에서 온 글(태그·사유)은 htm이 이스케이프하는 텍스트로만 넣는다.
import { html } from "../ui/html.js";
import { useLayoutEffect, useRef, useState } from "../../vendor/hooks.module.js";
import { createStore, store as shell, useStore } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Chip, Notice } from "../ui/parts.js";

const cssHref = new URL("edit.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector("link[data-edit-css]")) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-edit-css", "");
  document.head.appendChild(l);
}

const HINT = {
  select: "",
  connect_b: "연결할 다른 기기를 누르세요. Esc: 그만두기",
  endpoint: "그 끝을 이을 기기를 누르세요. Esc: 그만두기",
  path: "꺾이는 점을 차례로 누르고 Enter로 마칩니다(Esc: 그만두기). 첫 점과 끝 점이 배관의 양 끝이 됩니다.",
};

export const edit = createStore({
  on: false,
  tool: "select",          // select | connect | endpoint | path (connect·endpoint·path는 카드 단추로 시작)
  gid: null,
  head: null,              // GET edit/<gid>: {ver, ops, undoable, redo, graph_stale, kinds, relation_kinds}
  item: null,              // GET edit/<gid>/item/<local_id>
  addAt: null,             // 빈 곳을 누른 자리: 그 자리에 기기를 놓는 카드
  first: null,             // connect: 첫 기기
  end: null,               // endpoint: source | target
  points: [],              // path: 찍은 점(그린 좌표, 미리 보기용)
  origPoints: [],          // path: 같은 점의 읽은(원본) 좌표. 정리된 보기에서는 정돈으로 옮긴 만큼 되돌린 값이고, 이것을 저장한다
  newKind: "manual_valve", newTag: "", relKind: "physical_connection",
  busy: false, error: null, notes: [], ask: null,     // ask: {message, run}: 확인을 받아야 하는 고침
  revs: {},                // graph_id → 도면 자료 판: 고침·AI 수락 뒤(changed "sheet") 올려 도면 그림과 정리된 보기 자료를 다시 읽게 한다
});

export function useEdit(selector) {
  const [value, setValue] = useState(() => selector(edit.get()));
  const latest = useRef(selector);
  latest.current = selector;
  useLayoutEffect(() => {
    const sync = (s) => { const next = latest.current(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(edit.get());
    return edit.subscribe(sync);
  }, []);
  return value;
}

// ---------------------------------------------------------------- 읽기
let seq = 0;
export async function loadHead(gid) {
  const mine = ++seq;
  if (!gid) { edit.set({ head: null }); return null; }
  let h = null;
  try { h = await read("edit/" + encodeURIComponent(gid)); } catch (e) { h = null; }
  if (mine !== seq || shell.get().sheet !== gid) return null;
  edit.set({ head: h, gid });
  return h;
}

export async function loadItem(gid, id) {
  if (!gid || !id) { edit.set({ item: null }); return null; }
  let it = null;
  try { it = await read("edit/" + encodeURIComponent(gid) + "/item/" + encodeURIComponent(id)); } catch (e) { it = null; }
  if (shell.get().sheet !== gid) return null;
  edit.set({ item: it, error: it ? null : "이 항목은 고칠 수 없습니다(도면에 없음)." });
  return it;
}

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  if (typeof window !== "undefined") {          // 키는 한 번만 단다(도면 부품이 여러 번 그려져도 Ctrl+Z가 한 번만 되돌리게)
    function key(e) {
      const s = edit.get();
      if (!s.on) return;
      const t = e.target, tag = (t && t.tagName) || "";
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT") return;
      if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z" || e.key === "y")) {
        e.preventDefault(); e.stopPropagation();
        if (e.key === "y" || e.shiftKey) redo(); else undoLast();
        return;
      }
      if (s.tool === "select") {
        if (e.key === "Escape" && (s.item || s.addAt)) { e.preventDefault(); e.stopPropagation(); edit.set({ item: null, addAt: null, ask: null }); }
        return;
      }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancelTool(); }
      else if (e.key === "Enter" && s.tool === "path") { e.preventDefault(); e.stopPropagation(); finishPath(); }
    }
    window.addEventListener("keydown", key, true);            // 도면의 Esc(고른 것 비우기)보다 먼저 받는다
  }
  onChanged((topic, rev) => {
    if (topic === "sheet" && rev) edit.set((st) => ({ revs: Object.assign({}, st.revs, { [rev]: (st.revs[rev] || 0) + 1 }) }));
    if (topic !== "edit" && topic !== "aireview") return;
    const g = shell.get().sheet;
    if (!g || (topic === "edit" && rev && rev !== g)) return;
    loadHead(g);
    const it = edit.get().item;
    if (it) loadItem(g, it.local_id);
  });
  let last = null;
  shell.subscribe((s) => {
    if (s.sheet !== last) { last = s.sheet; edit.set({ item: null, tool: "select", first: null, end: null, points: [], origPoints: [], ask: null, error: null }); if (edit.get().on) loadHead(s.sheet); }
    if (edit.get().on && s.bubble && s.bubble.sheet === s.sheet && edit.get().tool === "select") {     // 고치기를 켠 채 누른 구성요소는 말풍선 대신 고치기 카드로
      const id = s.bubble.id;
      shell.set({ bubble: null });
      loadItem(s.sheet, id);
    }
  });
}

// ---------------------------------------------------------------- 보기 동작
export function setOn(on) {
  edit.set({ on: !!on, tool: "select", first: null, end: null, points: [], origPoints: [], item: null, ask: null, error: null, notes: [] });
  if (on) loadHead(shell.get().sheet);
}
export function setTool(tool) { edit.set({ tool, first: null, end: tool === "endpoint" ? edit.get().end : null, points: [], origPoints: [], error: null }); }
export function cancelTool() { edit.set({ tool: "select", first: null, end: null, points: [], origPoints: [] }); }
export function closeItem() { edit.set({ item: null, ask: null, error: null }); }
export function setField(patch) { edit.set(patch); }

export function hint(s) {
  if (s.tool === "connect" && s.first) return HINT.connect_b;
  return HINT[s.tool] || "";
}

// ---------------------------------------------------------------- 쓰기
async function send(name, args, { reopen = null } = {}) {
  const g = shell.get().sheet, head = edit.get().head;
  if (!g || !head) return null;
  edit.set({ busy: true, error: null });
  try {
    const r = await cmd(name, Object.assign({ graph_id: g, ver: head.ver }, args));
    edit.set({ busy: false, ask: null, notes: [...(r.notes || []), ...(r.recheck || [])] });
    await loadHead(g);
    const id = reopen === undefined ? null : (reopen || (edit.get().item && edit.get().item.local_id));
    if (id) await loadItem(g, id); else edit.set({ item: null });
    return r;
  } catch (e) {
    edit.set({ busy: false });
    if (e.code === "needs_confirm") edit.set({ ask: { message: e.message, run: () => send(name, Object.assign({}, args, { confirm: e.message }), { reopen }) } });
    else if (e.code === "stale") { await loadHead(g); edit.set({ error: e.message }); }
    else edit.set({ error: e.message || "고치지 못했습니다." });
    return null;
  }
}

/** 고침 하나. 엔진이 확인(needs_confirm)을 물으면 그 글을 카드에 띄우고, '그래도 하기'는 그 글을 그대로 confirm으로 보낸다
 * (엔진이 지금 확인 글과 견줘 걸리는 것이 바뀌었으면 다시 묻는다). 카드에서 본 항목이면 그 지문(base)을 함께 보낸다. */
export async function apply(op, localId, value = {}, { confirm = null, reopen = null } = {}) {
  const g = shell.get().sheet, head = edit.get().head;
  if (!g || !head) return null;
  const it = edit.get().item;
  edit.set({ busy: true, error: null });
  try {
    const args = { graph_id: g, ver: head.ver, op, local_id: localId || null, value };
    if (confirm) args.confirm = confirm;
    if (it && localId && it.local_id === localId && it.base) args.base = it.base;
    const r = await cmd("edit.apply", args);
    edit.set({ busy: false, ask: null, notes: [...(r.notes || []), ...(r.recheck || [])] });
    await loadHead(g);
    const id = op.startsWith("delete_") ? null : (r.created || reopen || localId);
    if (id) await loadItem(g, id); else edit.set({ item: null });
    return r;
  } catch (e) {
    edit.set({ busy: false });
    if (e.code === "needs_confirm") edit.set({ ask: { message: e.message, run: () => apply(op, localId, value, { confirm: e.message, reopen }) } });
    else if (e.code === "stale") { await loadHead(g); edit.set({ error: e.message }); }
    else edit.set({ error: e.message || "고치지 못했습니다." });
    return null;
  }
}

export function undoLast() {
  const h = edit.get().head;
  const id = h && h.undoable && h.undoable[h.undoable.length - 1];
  return id ? send("edit.undo", { op_id: id }) : null;
}
export function undoOp(opId) { return send("edit.undo", { op_id: opId }); }
export function redo() { return send("edit.redo", {}); }

/** 도면을 누름(고치기를 켠 동안): 자리 point(화면 도면 좌표)와 그 자리의 항목 id. */
export function pick({ point, orig, id, layer }) {
  const s = edit.get(), g = shell.get().sheet;
  const r2 = (q) => [Math.round(q[0] * 100) / 100, Math.round(q[1] * 100) / 100];
  const saved = r2(orig || point);              // 저장은 읽은(원본) 좌표: 정리된 보기에서는 정돈으로 옮긴 만큼 되돌린 점
  if (s.tool === "select") {
    if (id) { edit.set({ addAt: null, error: null }); loadItem(g, id); }
    else edit.set({ item: null, addAt: saved, error: null, ask: null });
  } else if (s.tool === "connect") {
    if (!id || layer !== "symbol") { edit.set({ error: "기기를 누르세요(빈 곳·연결선은 고를 수 없습니다)." }); return; }
    if (s.first === id) { edit.set({ error: "같은 기기입니다. 다른 기기를 누르세요." }); return; }
    const from = s.first;
    edit.set({ first: null, tool: "select" });
    apply("add_relation", null, { kind: s.relKind, from, to: id });
  } else if (s.tool === "endpoint") {
    if (!id || layer !== "symbol" || !s.item) { edit.set({ error: "기기를 누르세요." }); return; }
    const rel = s.item.local_id;
    edit.set({ tool: "select" });
    apply("set_endpoint", rel, { end: s.end, node: id });
  } else if (s.tool === "path") {
    edit.set({ points: [...s.points, r2(point)], origPoints: [...s.origPoints, saved], error: null });
  }
}

/** 빈 곳 카드의 '여기에 놓기'. */
export function addNodeHere() {
  const s = edit.get();
  if (!s.addAt) return null;
  const at = s.addAt;
  edit.set({ addAt: null });
  const r = apply("add_node", null, { kind: s.newKind, tag: s.newTag.trim(), at });
  edit.set({ newTag: "" });
  return r;
}

/** 기기 카드의 '연결 추가': 이 기기에서 시작해 다른 기기를 누르면 잇는다. */
export function startConnect(fromId) { edit.set({ tool: "connect", first: fromId, error: null }); }

export function finishPath() {
  const s = edit.get();
  if (s.tool !== "path" || !s.item) return;
  if (s.points.length < 2) { edit.set({ error: "점을 2개 이상 찍으세요." }); return; }
  const pts = s.origPoints.length === s.points.length ? s.origPoints : s.points;
  edit.set({ tool: "select", points: [], origPoints: [] });
  apply("set_path", s.item.local_id, { points: pts });
}

// ---------------------------------------------------------------- 도면 부품에 줄 props
/** <Sheet>에 펼칠 props: 도구가 있을 때만 누르기를 고치기로 돌리고, 경로 점을 미리 보인다. */
export function useEditCanvas(sheet) {
  wire();
  const on = useEdit((s) => s.on);
  const tool = useEdit((s) => s.tool);
  const points = useEdit((s) => s.points);
  const first = useEdit((s) => s.first);
  const rev = useEdit((s) => (sheet ? s.revs[sheet] || 0 : 0));
  const active = on && !!sheet;                // 켜 둔 동안은 누르기를 고치기로(구성요소 → 카드, 빈 곳 → 기기 놓기 카드)
  return {
    ...(rev ? { sheet: { graph_id: sheet, rev } } : {}),        // 바뀐 뒤에만 판을 실어 SheetHost의 sheet를 덮는다(처음 읽기는 그대로)
    editTool: active ? tool : null,
    editPreview: { points: active && tool === "path" ? points : [], first },
    onEditPick: (d) => pick(d),
  };
}

// ---------------------------------------------------------------- 화면
function Strip() {
  const s = useEdit((x) => x);
  const gid = useStore((x) => x.sheet);
  const [open, setOpen] = useState(false);
  if (!gid) return null;
  if (!s.on) {
    return html`<div class="float edit-pill off"><${Btn} sm=${true} kind="ghost" icon="pencil" label="도면 고치기" title="도면 고치기: 구성요소를 누르면 고칠 수 있는 것이 카드로 나옵니다"
      onClick=${() => setOn(true)}>고치기<//></div>`;
  }
  const h = s.head;
  const lastOp = h && h.undoable && h.undoable.length ? h.ops.find((o) => o.op_id === h.undoable[h.undoable.length - 1]) : null;
  const bad = h ? h.ops.filter((o) => o.status !== "applied").length : 0;
  const tip = hint(s);
  return html`<div class="float edit-pill" role="toolbar" aria-label="도면 고치기">
    <div class="ep-row"><span class="ep-on">고치는 중</span>
      <${Btn} sm=${true} kind="ghost" icon="arrow-back-up" label="되돌리기" title=${lastOp ? "되돌리기(Ctrl+Z): " + lastOp.label + " " + (lastOp.local_id || "") : "되돌릴 고침이 없습니다"}
        disabled=${s.busy || !lastOp} onClick=${undoLast} />
      <${Btn} sm=${true} kind="ghost" icon="arrow-forward-up" label="다시 하기" title=${h && h.redo ? "다시 하기(Ctrl+Shift+Z): " + h.redo.label : "다시 할 고침이 없습니다"}
        disabled=${s.busy || !(h && h.redo)} onClick=${redo} />
      ${h && h.ops.length ? html`<button type="button" class="ep-count" aria-expanded=${open ? "true" : "false"} onClick=${() => setOpen(!open)}
        title="고친 것 목록">${h.ops.length}${bad ? html` <span class="warn">· 못 얹음 ${bad}</span>` : null}</button>` : null}
      <${Btn} sm=${true} kind="ghost" icon="x" label="고치기 끝내기" title="고치기 끝내기" onClick=${() => setOn(false)} /></div>
    ${tip ? html`<div class="ep-hint">${tip}${s.tool === "path" ? " · 점 " + s.points.length + "개" : ""}</div>` : null}
    ${h && h.graph_stale ? html`<div class="ep-hint warn">저장했습니다. 그래프를 다시 만드는 중이거나 다시 만들지 못했습니다(못 만들면 다음 동작에서 다시 만듭니다).</div>` : null}
    ${s.notes.length ? html`<div class=${"ep-hint" + (s.notes.some((t) => t.includes("재확인") || t.includes("풀렸")) ? " warn" : "")}>${s.notes.map((t) => html`<div>${t}</div>`)}</div>` : null}
    ${s.error && !s.item && !s.addAt ? html`<div class="ep-hint err" role="alert">${s.error}</div>` : null}
    ${open && h && h.ops.length ? html`<ol class="ep-log">${h.ops.slice().reverse().slice(0, 30).map((o) => html`<li key=${o.op_id}><b>${o.label}</b> ${o.local_id || ""}
        ${o.status !== "applied" ? html` <span class="warn" title=${o.reason || ""}>못 얹음: ${o.reason || ""}</span>` : null}
        ${h.undoable.includes(o.op_id) ? html` <button type="button" class="linkish" onClick=${() => undoOp(o.op_id)}>되돌리기</button>` : null}</li>`)}</ol>` : null}
  </div>`;
}

function AddCard() {
  const s = useEdit((x) => x);
  if (!s.on || !s.addAt || s.item) return null;
  const h = s.head;
  return html`<div class="float edit-card add" role="dialog" aria-label="여기에 기기 놓기">
    <div class="ec-h"><b>여기에 기기 놓기</b><${Btn} sm=${true} kind="ghost" icon="x" label="닫기" onClick=${() => setField({ addAt: null })} /></div>
    <div class="field"><label for="ec-newkind">종류</label><select id="ec-newkind" value=${s.newKind} onChange=${(e) => setField({ newKind: e.target.value })}>
      ${(h ? h.kinds : []).map((k) => html`<option value=${k.kind}>${k.label}</option>`)}</select></div>
    <div class="field"><label for="ec-newtag">태그</label><input id="ec-newtag" class="textbox" maxlength="80" value=${s.newTag}
      onInput=${(e) => setField({ newTag: e.target.value })} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); addNodeHere(); } }} /></div>
    ${s.ask ? html`<${Notice} kind="warn" icon="alert-triangle">${s.ask.message}<div class="acts-row"><${Btn} sm=${true} label="그래도 하기" onClick=${s.ask.run}>그래도 하기<//></div><//>` : null}
    ${s.error ? html`<${Notice} kind="err" icon="alert-triangle">${s.error}<//>` : null}
    <div class="acts-row"><${Btn} sm=${true} kind="primary" icon="plus" label="여기에 놓기" disabled=${s.busy} onClick=${addNodeHere}>놓기 <kbd>Enter</kbd><//></div></div>`;
}

function ItemCard() {
  const s = useEdit((x) => x);
  const it = s.item;
  const [tag, setTag] = useState(null);
  if (!s.on || !it) return null;
  const head = s.head;
  const node = it.type === "node";
  const tagValue = tag === null ? (it.tag || "") : tag;
  const im = it.impact || {};
  const held = (im.nodes || []).filter((n) => n.state !== "applied");
  return html`<div class="float edit-card" role="dialog" aria-label=${(node ? "기기 " : "연결 ") + (it.tag || it.local_id) + " 고치기"}>
    <div class="ec-h"><b>${it.tag || it.local_id}</b> <span>${it.kind_label || ""}</span> <span class="muted small">${it.kind || ""}</span>
      <${Btn} sm=${true} kind="ghost" icon="x" label="고치기 카드 닫기" onClick=${() => { setTag(null); closeItem(); }} /></div>
    ${im.sheet === "confirmed" || im.sheet === "compared" ? html`<${Notice} kind="warn" icon="alert-triangle">이 쪽은 ${im.sheet === "confirmed" ? "확정" : "견줌"} 상태입니다. 고치면 풀립니다.<//>` : null}
    ${held.length ? html`<${Notice} kind="warn" icon="lock">확정·잠금 구간 ${held.map((n) => n.node_id).join(", ")}에 든 구성요소입니다. 고치면 그 구간을 재확인해야 합니다.<//>` : null}
    <div class="field"><label for="ec-tag">${node ? "태그" : "배관 번호"}</label>
      <div class="acts-row"><input id="ec-tag" class="textbox" maxlength="80" value=${tagValue} onInput=${(e) => setTag(e.target.value)}
        onKeyDown=${(e) => { if (e.key === "Enter" && tagValue.trim()) { e.preventDefault(); apply("set_tag", it.local_id, { tag: tagValue.trim() }); setTag(null); } }} />
      <${Btn} sm=${true} label="태그 저장" disabled=${s.busy || !tagValue.trim() || tagValue.trim() === (it.tag || "")} onClick=${() => { apply("set_tag", it.local_id, { tag: tagValue.trim() }); setTag(null); }}>저장<//></div></div>
    ${node ? html`<div class="field"><label for="ec-kind">종류</label>
      <select id="ec-kind" value=${it.kind || ""} disabled=${s.busy} onChange=${(e) => apply("set_kind", it.local_id, { kind: e.target.value })}>
        ${it.kind && !(head && head.kinds.some((k) => k.kind === it.kind)) ? html`<option value=${it.kind}>${it.kind}</option>` : null}
        ${(head ? head.kinds : []).map((k) => html`<option value=${k.kind}>${k.label} (${k.kind})</option>`)}</select></div>
      <div class="acts-row"><${Btn} sm=${true} icon="link" label="이 기기에서 연결 추가" title="이 기기에서 시작해 다른 기기를 누르면 공정 배관으로 잇습니다" disabled=${s.busy}
        onClick=${() => startConnect(it.local_id)}>연결 추가<//></div>
      ${(it.positions || []).map((p) => html`<div class="field"><label>${p.label}</label>
        <select aria-label=${p.label} value=${p.value || ""} disabled=${s.busy} onChange=${(e) => e.target.value && apply(p.op, it.local_id, { value: e.target.value })}>
          <option value="">(미확인)</option>${p.values.map((v) => html`<option value=${v}>${v}</option>`)}</select></div>`)}` : null}
    ${!node ? html`<div class="field"><label>흐름 방향</label><div class="acts-row">
        <span class="muted small">${it.flow ? it.flow.from + " → " + it.flow.to + (it.flow.basis === "human" ? " (사람이 정함)" : "") : "정하지 않음"}</span>
        <${Btn} sm=${true} icon="arrow-back-up" label="흐름 방향 뒤집기" disabled=${s.busy || !it.flow_allowed} title=${it.flow_allowed ? (it.flow ? "흐름 방향 뒤집기" : "끝(target) → 끝(source)로 정하기") : "물리 배관에만 흐름 방향을 정합니다"}
          onClick=${() => apply("set_flow", it.local_id, { flip: true })}>${it.flow ? "뒤집기" : "방향 정하기"}<//></div></div>
      <div class="field"><label>끝</label>${["source", "target"].map((end) => html`<div class="acts-row">
        <span class="muted small">${end === "source" ? "시작" : "끝"}: ${it.ends[end].node || "열린 끝"}</span>
        <${Btn} sm=${true} label=${end + " 끝 잇기"} disabled=${s.busy} onClick=${() => { setField({ end }); setTool("endpoint"); }}>잇기<//>
        ${it.ends[end].node ? html`<${Btn} sm=${true} label=${end + " 끝 끊기"} disabled=${s.busy} onClick=${() => apply("clear_endpoint", it.local_id, { end })}>끊기<//>` : null}</div>`)}</div>
      <div class="acts-row"><${Btn} sm=${true} icon="route" label="경로 다시 그리기" disabled=${s.busy} onClick=${() => setTool("path")}>경로 다시 그리기<//></div>` : null}
    ${it.unknowns.length ? html`<div class="field"><label>미확인 ${it.unknowns.length}</label><ul class="ec-unk">${it.unknowns.map((u) => html`<li>${u.reason || u.check}</li>`)}</ul>
      <${Btn} sm=${true} icon="check" label="미확인 확정" title="보이는 미확인을 '이대로 맞음'으로 확정합니다" disabled=${s.busy}
        onClick=${() => apply("confirm", it.local_id, { items: it.unknowns.map((u) => ({ check: u.check, reason: u.reason })) })}>이대로 확인<//></div>` : null}
    ${s.ask ? html`<${Notice} kind="warn" icon="alert-triangle">${s.ask.message}<div class="acts-row"><${Btn} sm=${true} kind="danger" label="그래도 하기" onClick=${s.ask.run}>그래도 하기<//>
      <${Btn} sm=${true} label="취소" onClick=${() => setField({ ask: null })}>취소<//></div><//>` : null}
    ${s.error ? html`<${Notice} kind="err" icon="alert-triangle">${s.error}<//>` : null}
    <div class="acts-row ec-foot"><${Btn} sm=${true} kind="ghost" icon="trash" label=${(node ? "기기" : "연결") + " 지우기"} disabled=${s.busy}
      onClick=${() => apply(node ? "delete_node" : "delete_relation", it.local_id)}>지우기<//>
      ${it.human_edit.length ? html`<span class="muted small">사람이 고친 항목</span>` : null}</div>
  </div>`;
}

export function EditOverlay() {
  return html`<${Strip} /><${ItemCard} /><${AddCard} />`;
}
