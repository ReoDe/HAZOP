// '다음에 할 일' 한 줄(규격 HZ-DSN-06 §3.1, 단위 U4). 위 막대 가운데에 지금 먼저 할 일 하나와 단추 하나, '그 밖에 n건' 펼침.
// 차례·문장·가는 곳은 엔진(읽기 토픽 next, hazop/shell/api_next.py)이 정한다. 여기서는 받은 대로 그리고, 단추를 그 자리로 잇는다.
// 단추가 도면 위 자리로 갈 때는 열린 패널을 닫는다(가리는 것을 치운다, §3.1 측정 규칙).
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { onChanged, read } from "../bridge.js";
import { Icon } from "../ui/icon.js";

export const next = createStore({ items: [], running: null, open: false, pinned: null });

/** 줄에 보일 차례: 사람이 '그 밖에'에서 고른 일(pinned)이 아직 남아 있으면 맨 앞(엔진의 맨 위 것이 그 흐름을 가로막지 않게, 실제 창 3차). */
export function shown(s) {
  const i = s.pinned ? s.items.findIndex((x) => x.kind === s.pinned) : -1;
  return i > 0 ? [s.items[i]].concat(s.items.slice(0, i), s.items.slice(i + 1)) : s.items;
}

/** 이 영역 store를 읽는다(store.js의 useStore와 같은 꼴). */
export function useNext(selector) {
  const [value, setValue] = useState(() => selector(next.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const n = selector(s); setValue((p) => (Object.is(p, n) ? p : n)); };
    sync(next.get());
    return next.subscribe(sync);
  }, []);
  return value;
}

let seq = 0;
export async function load() {
  const mine = ++seq;
  try {
    const d = await read("next");
    if (mine !== seq || !d) return;
    const items = d.items || [];
    next.set((s) => ({ items, running: d.running || null, pinned: s.pinned && items.some((x) => x.kind === s.pinned) ? s.pinned : null }));
  } catch (e) { /* 안내 한 줄: 읽기 실패는 앞 줄을 그대로 둔다 */ }
}

let timer = null;
function soon() { clearTimeout(timer); timer = setTimeout(load, 120); }      // 영역 알림이 몰려와도 한 번만 읽는다

// ---------------------------------------------------------------- 가는 곳
const handlers = {};
/** 패널 쪽에서 가는 길을 붙인다(순환 가져오기를 피하려고 main.js가 이어 준다): name → fn(target). */
export function setGo(name, fn) { handlers[name] = fn; }

/** 펼친 목록에서 고른 일: 그 일을 줄 맨 앞에 붙잡아 두고 간다. */
export function pick(it) {
  next.set({ pinned: it.kind });
  return go(it.action);
}

export function go(action) {
  if (!action) return;
  next.set({ open: false });
  const g = String(action.go || "");
  const [kind, rest] = [g.slice(0, g.indexOf(":")), g.slice(g.indexOf(":") + 1)];
  const [name, spot] = rest.split("#");
  const key = kind + ":" + name + (spot ? "#" + spot : "");
  if (handlers[key]) return handlers[key](action.target || null);
  if (kind === "panel") return store.set({ panel: name });
  if (kind === "queue") return store.set({ panel: name === "ai" ? "aireview" : "nodes" });     // 대기열(U5) 전에는 그 패널로
  if (handlers[kind + ":" + name]) return handlers[kind + ":" + name](action.target || null);
  return undefined;
}

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "next" || topic === "state") soon(); });
  let lastProject = store.get().drawings.project_id;
  store.subscribe((s) => { if (s.drawings.project_id !== lastProject) { lastProject = s.drawings.project_id; next.set({ items: [], running: null, open: false, pinned: null }); soon(); } });
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && !e.altKey && !e.shiftKey && (e.key === "j" || e.key === "J")) {
      const top = shown(next.get())[0];
      if (top && top.kind !== "none") { e.preventDefault(); go(top.action); }
    }
  });
  window.addEventListener("keydown", (e) => {          // Esc로 펼침을 닫는다(패널 닫기보다 먼저)
    if (e.key === "Escape" && next.get().open) { e.preventDefault(); e.stopImmediatePropagation(); next.set({ open: false }); }
  }, true);
  document.addEventListener("click", (e) => { if (next.get().open && !(e.target.closest && e.target.closest(".next"))) next.set({ open: false }); });
  load();
}

const ICON = { apply_failed: "alert-triangle", recheck: "alert-triangle", no_sheets: "upload", titleblock: "file-text", ai_candidates: "sparkles",
  sheet_confirm: "check", nodes_none: "vector-triangle", nodes_draft: "vector-triangle", nodes_unrun: "sparkles", results_unjudged: "table",
  ie_none: "route", ie_draft: "route", none: "circle-check" };

export function NextLine() {
  wire();
  const engineItems = useNext((s) => s.items);
  const pinned = useNext((s) => s.pinned);
  const items = shown({ items: engineItems, pinned });
  const running = useNext((s) => s.running);
  const open = useNext((s) => s.open);
  if (!items.length && !running) return html`<div class="next" id="next"></div>`;
  const top = items[0];
  const rest = items.length - 1;
  const line = running
    ? html`<div class="line info" role="status"><${Icon} name="loader-2" size=${15} /><span class="txt">${running.label}${running.total ? " · " + running.total + " 중 " + (running.done || 0) : ""}</span>
        ${running.total ? html`<span class="bar"><i style=${"width:" + Math.round(100 * (running.done || 0) / running.total) + "%"}></i></span>` : null}
        ${items.length && top.kind !== "none" ? html`<button type="button" class="more" aria-label="남은 일 보기" aria-expanded=${open} onClick=${(e) => { e.stopPropagation(); next.set({ open: !open }); }}>남은 일 ${items.length}건 <${Icon} name="chevron-down" size=${14} /></button>` : null}</div>`
    : html`<div class=${"line " + (top.tone === "warn" ? "warn" : top.kind === "none" ? "calm" : "")}>
        <${Icon} name=${ICON[top.kind] || "info-circle"} size=${15} /><span class="txt" title=${top.detail || top.text}>${top.text}</span>
        <button type="button" class=${"btn sm" + (top.kind === "none" ? "" : " primary")} aria-keyshortcuts=${top.kind === "none" ? null : "Control+J"}
          title=${top.kind === "none" ? null : top.action.label + " (Ctrl+J)"} onClick=${() => go(top.action)}>${top.action.label}</button>
        ${rest > 0 ? html`<button type="button" class="more" aria-label=${"그 밖에 " + rest + "건 보기"} aria-expanded=${open} onClick=${(e) => { e.stopPropagation(); next.set({ open: !open }); }}>그 밖에 ${rest}건 <${Icon} name="chevron-down" size=${14} /></button>` : null}</div>`;
  return html`<div class="next" id="next">${line}
    ${open ? html`<div class="next-list" role="menu" aria-label="남은 일"><div class="h"><span>남은 일 · 앞에 있는 것부터</span><span>Ctrl+J = 맨 위 것 하기</span></div>
      ${engineItems.map((it, j) => html`<button type="button" role="menuitem" key=${it.kind} class=${"item" + (j === 0 ? " top" : "") + (it.tone === "warn" ? " warn" : "")} onClick=${() => pick(it)}>
        <span class="n">${j + 1}</span><${Icon} name=${ICON[it.kind] || "info-circle"} size=${14} /><span class="t">${it.text}${it.detail ? html`<span>${it.detail}</span>` : null}</span>
        <span class="go">${it.action.label} ›</span></button>`)}</div>` : null}</div>`;
}

