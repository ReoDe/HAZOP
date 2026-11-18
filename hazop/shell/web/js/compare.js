// 견주기 화면(앱 틀 규격 §10.10 V4): '원본과 견줌'은 이 화면을 열어 원본에 남은 것을 끝까지 넘겨 본 사람만 남길 수 있다.
// 나란히(왼쪽 원본 · 오른쪽 정리된 보기) 또는 겹쳐(정리된 보기 위에 원본 30%)로 보고, 원본에 남은 것은 두 쪽 모두에 호박색으로 보인다.
// 원본 그림이 없는 DEXPI는 정리된 보기의 종류별 수 목록을 끝까지 넘겨 본다. 남은 것의 수와 자리는 엔진 값(/api/clean의 leftovers)을 그대로 쓴다.
// 기록의 방식(mode)은 사람이 마지막에 본 한 가지만 적는다(side_by_side · overlay · dexpi_list).
import { html } from "./ui/html.js";
import { useEffect, useLayoutEffect, useRef, useState } from "../vendor/hooks.module.js";
import { createStore, store } from "./store.js";
import { read } from "./bridge.js";
import { clean, setView, useClean } from "./canvas/clean_ui.js";
import { Icon } from "./ui/icon.js";
import { Btn, Notice } from "./ui/parts.js";
import { compare as saveCompare, conf } from "./sheet_confirm.js";

const cssHref = new URL("compare.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector("link[data-compare-css]")) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-compare-css", "");
  document.head.appendChild(l);
}

export const cmp = createStore({ gid: null, mode: "side_by_side", idx: 0, seen: {}, listEnd: false, agreed: false, prev: null, sheet: null });

export function useCmp(selector) {
  const latest = useRef(selector);
  latest.current = selector;                          // 선택 함수가 보는 도면 같은 값을 붙들고 있어도 늘 최신 것으로 고른다
  const [, force] = useState(0);
  useLayoutEffect(() => {
    let last = latest.current(cmp.get());
    return cmp.subscribe((st) => { const n = latest.current(st); if (!Object.is(n, last)) { last = n; force((k) => k + 1); } });
  }, []);
  return selector(cmp.get());
}


/** 이 쪽의 견주기 화면을 연다. 정리된 보기로 바꾸고 원본에 남은 것을 겹쳐 둔다(닫으면 겹치기를 원래대로 돌린다). */
/** 캔버스 너비가 바뀐 뒤(반으로 줄거나 돌아옴) 도면 전체가 다시 맞게 보이도록 한다. */
const fitNow = () => store.set((s) => ({ command: { seq: s.command.seq + 1, type: "fit" } }));
const refit = () => { setTimeout(fitNow, 250); setTimeout(fitNow, 900); };      // 크기 변화가 캔버스에 닿은 뒤에 맞춘다(한 번 더 맞춰 늦게 닿는 경우도 덮는다)

export function openCompare(gid, readMethod) {
  const dexpi = readMethod === "dexpi";
  const prev = Object.assign({}, clean.get().overlay);
  if (!dexpi) {
    setView(gid, "clean");
    clean.set((s) => ({ overlay: Object.assign({}, s.overlay, { leftovers: true, original: false }) }));
  }
  cmp.set({ gid, mode: dexpi ? "dexpi_list" : "side_by_side", idx: 0, seen: {}, listEnd: false, agreed: false, prev, sheet: null });
  refit();
  read("sheet/" + encodeURIComponent(gid)).then((d) => { if (cmp.get().gid === gid) cmp.set({ sheet: d }); }).catch(() => { if (cmp.get().gid === gid) cmp.set({ sheet: false }); });     // 원본 그림 주소·크기·종류별 구성요소
}

export function closeCompare() {
  const c = cmp.get();
  if (c.prev) clean.set({ overlay: c.prev });
  cmp.set({ gid: null, idx: 0, seen: {}, listEnd: false, agreed: false, prev: null, sheet: null });
  refit();
}

export function setMode(mode) {
  if (cmp.get().mode === mode) return;
  clean.set((s) => ({ overlay: Object.assign({}, s.overlay, { original: mode === "overlay", leftovers: true }) }));
  cmp.set({ mode });
  refit();
}

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  store.subscribe((s) => { const g = cmp.get().gid; if (g && s.sheet !== g) closeCompare(); });      // 쪽을 바꾸면 견주기 화면과 체크를 끈다
}

const itemsOf = (data) => ((data && data.leftovers && data.leftovers.items) || []).filter((i) => Array.isArray(i.bbox));

/** 목록을 끝까지 보았는가: 남은 것은 하나씩 넘겨 모두 보였을 때, 목록이 없으면(0개) 곧바로, DEXPI는 목록 스크롤 끝까지. */
export function viewedAll(c, data) {
  if (c.mode === "dexpi_list") return c.listEnd;
  const n = itemsOf(data).length;
  return n === 0 || Object.keys(c.seen).length >= n;
}

function fit(size) { return { x: 0, y: 0, w: size[0], h: size[1] }; }

/** 왼쪽 원본: 도면 SVG를 그대로(드래그로 옮기고 휠로 확대) 보이고 원본에 남은 것을 호박색으로 겹친다. */
function OriginalPane({ sheet, items, idx }) {
  const size = sheet && sheet.svg && sheet.width && sheet.height ? [sheet.width, sheet.height] : (sheet === false || (sheet && !sheet.svg) ? false : null);
  const [vb, setVb] = useState(null);
  const ref = useRef(null);
  const drag = useRef(null);
  useEffect(() => { if (size) setVb(fit(size)); }, [size && size[0], size && size[1]]);
  useEffect(() => {
    const it = items[idx];
    if (!it || !size) return;
    const [x0, y0, x1, y1] = it.bbox, w = Math.max((x1 - x0) * 8, 360), h = Math.max((y1 - y0) * 8, 260);
    setVb({ x: (x0 + x1) / 2 - w / 2, y: (y0 + y1) / 2 - h / 2, w, h });
  }, [idx, items.length, size && size[0]]);
  if (size === false) return html`<div class="cmp-pane"><${Notice} kind="warn" icon="alert-triangle">원본 그림을 읽지 못했습니다. 겹쳐 보기로 견주세요.<//></div>`;
  if (!size || !vb) return html`<div class="cmp-pane"><div class="muted small" style="padding:12px">원본을 읽는 중…</div></div>`;
  const rect = () => ref.current.getBoundingClientRect();
  const onWheel = (e) => {
    e.preventDefault();
    const r = rect(), k = e.deltaY < 0 ? 0.8 : 1.25;
    const px = vb.x + ((e.clientX - r.left) / r.width) * vb.w, py = vb.y + ((e.clientY - r.top) / r.height) * vb.h;
    setVb({ x: px - (px - vb.x) * k, y: py - (py - vb.y) * k, w: vb.w * k, h: vb.h * k });
  };
  const onDown = (e) => { drag.current = { x: e.clientX, y: e.clientY, vb }; e.currentTarget.setPointerCapture(e.pointerId); };
  const onMove = (e) => {
    const d = drag.current;
    if (!d) return;
    const r = rect();
    setVb({ x: d.vb.x - ((e.clientX - d.x) / r.width) * d.vb.w, y: d.vb.y - ((e.clientY - d.y) / r.height) * d.vb.h, w: d.vb.w, h: d.vb.h });
  };
  return html`<div class="cmp-pane" role="img" aria-label="원본 도면">
    <svg ref=${ref} viewBox=${vb.x + " " + vb.y + " " + vb.w + " " + vb.h} preserveAspectRatio="xMidYMid meet" width="100%" height="100%"
      onWheel=${onWheel} onPointerDown=${onDown} onPointerMove=${onMove} onPointerUp=${() => { drag.current = null; }}>
      <image href=${sheet.svg} x="0" y="0" width=${size[0]} height=${size[1]} />
      ${items.map((it, i) => html`<rect key=${i} x=${it.bbox[0]} y=${it.bbox[1]} width=${Math.max(it.bbox[2] - it.bbox[0], 4)} height=${Math.max(it.bbox[3] - it.bbox[1], 4)}
        fill=${i === idx ? "rgba(168,116,13,.28)" : "rgba(168,116,13,.12)"} stroke="var(--warn-line, #a8740d)" stroke-width=${i === idx ? 2 : 1} stroke-dasharray="4 3" vector-effect="non-scaling-stroke" pointer-events="none" />`)}
    </svg>
    <div class="cmp-cap">원본</div>
    <button type="button" class="btn sm cmp-fit" aria-label="원본 전체 맞춤" onClick=${() => setVb(fit(size))}>전체 보기</button></div>`;
}

/** 캔버스 위에 얹는 왼쪽 칸. 나란히 모드일 때만 그린다(오른쪽 정리된 보기는 도면 캔버스가 반으로 줄어 그대로 쓴다). */
export function ComparePane() {
  wire();
  const c = useCmp((s) => s);
  const sheet = useStoreSheet();
  const data = useClean((s) => (c.gid ? s.data[c.gid] : null));
  if (!c.gid || c.gid !== sheet || c.mode !== "side_by_side") return null;
  return html`<${OriginalPane} sheet=${c.sheet} items=${itemsOf(data)} idx=${c.idx} />`;
}

function useStoreSheet() {
  const [g, setG] = useState(() => store.get().sheet);
  useLayoutEffect(() => { const sync = (s) => setG((p) => (p === s.sheet ? p : s.sheet)); sync(store.get()); return store.subscribe(sync); }, []);
  return g;
}

function KindTable({ sheet }) {
  const ref = useRef(null);
  const counts = {};
  for (const v of (sheet && sheet.items) || []) { const k = (v && (v.kind || v.category)) || "기타"; counts[k] = (counts[k] || 0) + 1; }
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const check = () => { const e = ref.current; if (e && e.scrollTop + e.clientHeight >= e.scrollHeight - 2) cmp.set({ listEnd: true }); };
  useEffect(() => { check(); }, [rows.length]);
  return html`<div class="cmp-list" ref=${ref} onScroll=${check} tabindex="0" aria-label="변환 도면의 종류별 수">
    ${rows.length ? rows.map(([k, n]) => html`<div class="row" key=${k}><span>${k}</span><b>${n}</b></div>`) : html`<div class="muted small">그려진 구성요소가 없습니다.</div>`}</div>`;
}

export function CompareCard() {
  const c = useCmp((s) => s);
  const sheet = useStoreSheet();
  const data = useClean((s) => (c.gid ? s.data[c.gid] : null));
  const busy = useConfBusy();
  const [error, setError] = useState("");
  if (!c.gid || c.gid !== sheet) return null;
  const dexpi = c.mode === "dexpi_list";
  const items = itemsOf(data);
  const total = items.length;
  const counted = !!(data && data.leftovers && data.leftovers.counted);
  const viewed = viewedAll(c, data);
  const go = (d) => {
    if (!total) return;
    const idx = (c.idx + d + total) % total;
    cmp.set((s) => ({ idx, seen: Object.assign({}, s.seen, { [idx]: true }) }));
  };
  // 처음 열 때 첫 항목을 본 것으로 센다
  useEffect(() => { if (total && !c.seen[c.idx]) cmp.set((s) => ({ seen: Object.assign({}, s.seen, { [s.idx]: true }) })); }, [total, c.idx]);
  const done = async () => {
    setError("");
    const r = await saveCompare(c.gid, c.mode);
    if (r) closeCompare(); else setError(conf.get().error || "견줌을 기록하지 못했습니다.");
  };
  const it = items[c.idx];
  return html`<div class="float cmpcard" role="dialog" aria-label="견주기 화면">
    <div class="nd-h"><b>원본과 견주기</b>
      <span class="acts"><${Btn} sm=${true} kind="ghost" icon="x" label="견주기 화면 닫기" onClick=${closeCompare} /></span></div>
    ${dexpi ? html`<div class="muted small">DEXPI는 원본 그림이 없어 변환 도면의 종류별 수를 끝까지 넘겨 견줍니다.</div>` : html`<div class="seg cmp-mode" role="group" aria-label="견주기 방식">
      <button type="button" class=${c.mode === "side_by_side" ? "on" : ""} aria-pressed=${c.mode === "side_by_side" ? "true" : "false"} onClick=${() => setMode("side_by_side")}>나란히</button>
      <button type="button" class=${c.mode === "overlay" ? "on" : ""} aria-pressed=${c.mode === "overlay" ? "true" : "false"} onClick=${() => setMode("overlay")}>겹쳐(원본 30%)</button></div>`}
    ${dexpi ? html`<${KindTable} sheet=${c.sheet} />` : (!counted ? html`<${Notice} kind="warn" icon="alert-triangle">이 읽은 방법은 엔진이 원본에 남은 것을 세지 못해 견줄 수 없습니다.<//>`
      : total === 0 ? html`<div class="muted small" role="status">원본에 남은 것이 없습니다. 두 도면을 훑어 빠진 구성요소가 없는지 본 뒤 아래 체크를 켜세요.</div>`
      : html`<div class="cmp-step" role="group" aria-label="원본에 남은 것">
          <div><b>${c.idx + 1} / ${total}</b> <span class="muted small">${(it && it.kind) === "unclassified" ? "분류하지 못한 셀" : (it && it.kind)}${it && it.text ? " · " + it.text : ""}</span></div>
          <div class="acts-row"><${Btn} sm=${true} label="앞 남은 것" onClick=${() => go(-1)}>앞<//><${Btn} sm=${true} kind="primary" label="다음 남은 것" onClick=${() => go(1)}>다음<//></div>
          <div class="muted small">${viewed ? "남은 것을 모두 보았습니다." : "끝까지 넘겨 보아야 다음 단추가 켜집니다(" + Object.keys(c.seen).length + "/" + total + " 봄)."}</div></div>`)}
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}
    <label class="check"><input type="checkbox" checked=${c.agreed} disabled=${!viewed || (!dexpi && !counted)} onChange=${(e) => cmp.set({ agreed: e.target.checked })} />
      빠진 구성요소가 없음을 원본과 견주어 확인했습니다</label>
    <div class="acts-row"><${Btn} sm=${true} kind="primary" label="견줌 완료" disabled=${busy || !viewed || !c.agreed || (!dexpi && !counted)} onClick=${done}>견줌 완료<//></div></div>`;
}

function useConfBusy() {
  const [busy, setBusy] = useState(() => conf.get().busy);
  useLayoutEffect(() => { const sync = (s) => setBusy((p) => (p === s.busy ? p : s.busy)); sync(conf.get()); return conf.subscribe(sync); }, []);
  return busy;
}
