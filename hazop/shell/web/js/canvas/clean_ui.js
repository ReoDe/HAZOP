// 정리된 보기의 화면 쪽(규격 §10.4·§10.5): 원본|정리 단추(키 O), '미확인 n곳' 칩(키 N·Shift+N), 못 읽은 곳의 원본 조각 말풍선, 기본 보기 규칙.
// 보기 선택은 앱을 닫을 때까지만 기억한다(프로젝트 파일에 저장하지 않음). SheetHost가 `useCleanCanvas(sheet)`의 props를 <Sheet>에 펼치고
// `<CleanOverlay />`를 도면 자리 안에 그린다. 도면·모델에서 온 글(태그)은 htm이 이스케이프하는 텍스트로만 넣는다.
import { html } from "../ui/html.js";
import { useEffect, useLayoutEffect, useRef, useState } from "../../vendor/hooks.module.js";
import { createStore, store as shell, useStore } from "../store.js";
import { Icon } from "../ui/icon.js";
import { Chip } from "../ui/parts.js";
import { defaultView } from "./clean_view.js";

const cssHref = new URL("clean.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector("link[data-clean-css]")) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-clean-css", "");
  document.head.appendChild(l);
}

export const clean = createStore({
  choice: {},        // graph_id → "orig" | "clean": 사람이 바꾼 보기(앱을 닫을 때까지)
  data: {},          // graph_id → /api/clean 자료(없으면 null)
  built: {},         // graph_id → {ms, elements, missingKinds, placeholders}
  bubble: null,      // {id, reason, fragment}
  cursor: -1,        // 다음 미확인 위치
  overlay: { leftovers: false, original: false, unconfirmed: false },   // 원본에 남은 것 겹치기(L)·원본 겹쳐 보기(30%)
});

export function useClean(selector) {
  const [value, setValue] = useState(() => selector(clean.get()));
  const latest = useRef(selector);
  latest.current = selector;               // 선택 함수가 도면 ID 같은 값을 붙들고 있어도 늘 최신 것으로 고른다
  useLayoutEffect(() => {
    const sync = (s) => { const next = latest.current(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(clean.get());
    return clean.subscribe(sync);
  }, []);
  useLayoutEffect(() => { const next = selector(clean.get()); setValue((prev) => (Object.is(prev, next) ? prev : next)); });   // 선택 함수가 바뀌면(도면을 바꾸면) 바로 다시 고른다
  return value;
}

export const REASON_TEXT = {
  unknown_symbol: "종류를 못 읽은 기호", open_end: "끊긴 연결(열린 끝)", missing_tag: "태그가 없음", ai_candidate: "AI 후보(수락 전)",
};

/** 지금 이 도면의 보기. 사람이 바꾼 것이 먼저, 없으면 읽은 방법에 따른 기본(drawio·dexpi는 정리, PDF는 원본). 정리 자료가 없으면 원본. */
export function viewOf(state, gid) {
  const data = state.data[gid];
  if (!data) return "orig";
  if (data.source_format === "dexpi") return "clean";        // 원본 그림이 없다
  return state.choice[gid] || defaultView(data.source_format, !!(data.confirmed && data.confirmed.state === "confirmed"));
}

export function toggleOverlay(name) { clean.set((s) => ({ overlay: Object.assign({}, s.overlay, { [name]: !s.overlay[name] }) })); }

export function setView(gid, view) { clean.set((s) => ({ choice: Object.assign({}, s.choice, { [gid]: view }) })); }

export function toggleView(gid) {
  const s = clean.get();
  if (!s.data[gid]) return;
  setView(gid, viewOf(s, gid) === "clean" ? "orig" : "clean");
}

export function onClean(gid, data) { clean.set((s) => ({ data: Object.assign({}, s.data, { [gid]: data }), cursor: -1, bubble: null })); }

export function openBubble(d) { clean.set({ bubble: { id: d.id, reason: d.reason, fragment: d.fragment || null } }); }
export function closeBubble() { clean.set({ bubble: null }); }

/** 다음(+1)·앞(-1) 미확인으로 옮긴다: 그 자리에 맞춰 확대하고 말풍선을 연다. 순서는 엔진이 준 위→아래, 왼→오른 순서다. */
export function stepUnconfirmed(gid, step = 1) {
  const s = clean.get(), list = (s.data[gid] && s.data[gid].unconfirmed) || [];
  if (!list.length) return null;
  if (!s.overlay.unconfirmed) clean.set({ overlay: Object.assign({}, s.overlay, { unconfirmed: true }) });     // 미확인을 찾아 가면 속성 미확인 자리도 함께 보인다
  const at = ((s.cursor + step) % list.length + list.length) % list.length, u = list[at];
  clean.set({ cursor: at });
  shell.set((st) => ({ command: { seq: st.command.seq + 1, type: "inspect", id: u.id, reason: u.reason, pad: 4 } }));
  return u;
}

/** <Sheet>에 펼칠 props와 키(O·N). */
export function useCleanCanvas(sheet) {
  const view = useClean((s) => (sheet ? viewOf(s, sheet) : "orig"));
  const overlays = useClean((s) => s.overlay);
  useLayoutEffect(() => {
    function key(e) {
      const t = e.target, tag = (t && t.tagName) || "";
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT" || (t && t.isContentEditable) || e.ctrlKey || e.metaKey || e.altKey) return;
      const g = shell.get().sheet;
      if (!g) return;
      const k = (e.key || "").toLowerCase();
      if (k === "o") { e.preventDefault(); toggleView(g); }
      else if (k === "n") { e.preventDefault(); stepUnconfirmed(g, e.shiftKey ? -1 : 1); }
      else if (k === "l") { e.preventDefault(); toggleOverlay("leftovers"); }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  return {
    /** Esc: 열린 말풍선을 닫으면 true(그러면 다른 Esc 동작은 하지 않는다). */
    closeIfOpen: () => { if (!clean.get().bubble) return false; closeBubble(); return true; },
    props: {
      view, overlays,
      onClean: (gid, data) => onClean(gid, data),
      onUnconfirmedClick: (d) => openBubble(d),
      onCleanBuilt: (info) => { const g = shell.get().sheet; if (g) clean.set((s) => ({ built: Object.assign({}, s.built, { [g]: info }) })); },
    },
  };
}

const FORMAT_LABEL = { drawio: "읽은 도면 · drawio", dexpi: "변환 도면 · DEXPI", pdf_vector: "PDF에서 읽어 다시 그림", raster: "이미지에서 읽어 다시 그림", unknown: "읽은 방법 모름" };

function ViewSwitch({ gid }) {
  const view = useClean((s) => viewOf(s, gid));
  const data = useClean((s) => s.data[gid]);
  const built = useClean((s) => s.built[gid]);
  const ov = useClean((s) => s.overlay);
  const [open, setOpen] = useState(false);
  const count = data ? data.counts.total : 0, fmt = data ? data.source_format : null;
  const dexpi = fmt === "dexpi";
  const tip = built && built.missingKinds.length ? "그림이 없는 종류 " + built.missingKinds.length + "개: " + built.missingKinds.join(", ") : "";
  const seg = (v, label) => html`<button type="button" class=${view === v ? "on" : ""} aria-pressed=${view === v ? "true" : "false"} disabled=${v === "clean" && !data}
    title=${v === "clean" && !data ? "정리된 보기 자료를 읽지 못했습니다" : label + " 보기 (O)"} onClick=${() => setView(gid, v)}>${label}</button>`;
  const lo = data && data.leftovers;
  const unplaced = data ? data.counts.unplaced : 0;
  const lit = ov.unconfirmed || ov.leftovers || ov.original;              // 켜 둔 겹쳐 보기가 있으면 '보기' 단추에 점
  const warn = fmt === "unknown" || unplaced > 0;                          // 알아야 할 것(읽은 방법 모름·위치 없음)이 메뉴 안에 있으면 호박색 점
  const check = (on, label, title, onClick) => html`<label class="vm-row" title=${title}>
    <input type="checkbox" checked=${on} onChange=${onClick} /> <span>${label}</span></label>`;
  return html`<div class="float viewswitch" role="group" aria-label="도면 보기">
    ${dexpi ? html`<span class="muted small" title="DEXPI에는 원본 도면 그림이 없습니다">원본 그림 없음 · DEXPI 변환</span>`
      : html`<div class="clean-toggle" role="group" aria-label="원본 또는 정리">${seg("orig", "원본")}${seg("clean", "정리")}</div>`}
    ${data ? html`<button type="button" class=${"chip " + (count ? "warn" : "ok")} title=${"다음 미확인으로 (N)" + (tip ? " · " + tip : "")} aria-label=${"미확인 " + count + "곳. 다음으로 가기"}
      onClick=${() => stepUnconfirmed(gid, 1)}><${Icon} name=${count ? "alert-triangle" : "check"} size=${14} /> 미확인 ${count}곳</button>` : null}
    ${data ? html`<button type="button" class="vm-btn" aria-expanded=${open ? "true" : "false"} aria-haspopup="true" title="보기 설정: 읽은 방법, 겹쳐 보기"
      onClick=${() => setOpen(!open)}>보기 <${Icon} name="chevron-down" size=${14} />${lit || warn ? html`<span class=${"vm-dot" + (warn ? " warn" : "")} aria-label=${warn ? "알릴 것이 있음" : "켜 둔 겹쳐 보기가 있음"}></span>` : null}</button>` : null}
    ${open && data ? html`<div class="float viewmenu" role="menu" aria-label="보기 설정">
      <div class=${"vm-info" + (fmt === "unknown" ? " warn" : "")} title="읽은 방법">${FORMAT_LABEL[fmt] || fmt}</div>
      ${unplaced ? html`<div class="vm-info warn" title="좌표가 없어 도면에 그리지 못한 것. 확정 전에 위치를 주거나 도면에 없음으로 정해야 합니다">위치 없음 ${unplaced}</div>` : null}
      ${count ? check(ov.unconfirmed, "속성 미확인 보기", "호박색 점선 네모: 읽지 못한 것이 아니라 속성만 확인되지 않은 곳(포트·흐름 방향·고장 위치 등)을 도면에 보입니다. 읽지 못한 기호·열린 끝은 늘 보입니다",
        () => toggleOverlay("unconfirmed")) : null}
      ${lo && lo.counted ? check(ov.leftovers, "원본에 남은 것 " + lo.n, "원본에서 어느 구성요소에도 쓰이지 않은 것을 겹쳐 봅니다 (L)", () => toggleOverlay("leftovers"))
        : (lo ? html`<div class="vm-info warn" title="이 읽은 방법에서는 엔진이 원본에 남은 선·글자를 세지 못합니다. 쪽을 확정하기 전에 원본과 견주어야 합니다">원본에 남은 것: 엔진이 세지 않음</div>` : null)}
      ${!dexpi ? check(ov.original, "원본 겹쳐 보기", "원본 도면을 옅게(30%) 겹쳐 어긋난 곳을 찾습니다", () => toggleOverlay("original")) : null}</div>` : null}</div>`;
}

function Bubble({ gid }) {
  const b = useClean((s) => s.bubble);
  const data = useClean((s) => s.data[gid]);
  const cursor = useClean((s) => s.cursor);
  if (!b) return null;
  const total = data ? data.unconfirmed.length : 0, f = b.fragment;
  return html`<div class="float cleanpop" role="dialog" aria-label="못 읽은 곳">
    <div class="cp-h"><b>${REASON_TEXT[b.reason] || "못 읽은 곳"}</b>${total && cursor >= 0 ? html`<${Chip}>${cursor + 1} / ${total}<//>` : null}
      <button type="button" class="btn ghost sm icon" aria-label="닫기" title="닫기 (Esc)" onClick=${closeBubble}><${Icon} name="x" size=${15} /></button></div>
    ${f ? html`<div class="cp-frag" aria-label="원본의 그 자리"><svg viewBox=${f.box.x + " " + f.box.y + " " + f.box.w + " " + f.box.h} width="100%" preserveAspectRatio="xMidYMid meet">
      <image href=${f.href} x="0" y="0" width=${f.size[0]} height=${f.size[1]} /></svg><div class="muted small">원본에서 그 자리 둘레(사방 24 단위)</div></div>` : html`<div class="muted small">원본 조각이 없습니다.</div>`}
    <div class="acts-row"><button type="button" class="btn sm" aria-label="앞 미확인" onClick=${() => stepUnconfirmed(gid, -1)}>앞 <kbd>Shift+N</kbd></button>
      <button type="button" class="btn sm" aria-label="다음 미확인" onClick=${() => stepUnconfirmed(gid, 1)}>다음 <kbd>N</kbd></button></div></div>`;
}

export function CleanOverlay() {
  const gid = useStore((s) => s.sheet);
  if (!gid) return null;
  return html`<${ViewSwitch} gid=${gid} /><${Bubble} gid=${gid} />`;
}
