// 가상 스크롤 표(규격 §5.4 큰 표: 525구간 × 44편차 행렬). 화면에 보이는 행·열의 칸만 DOM으로 만든다.
// 머리 줄과 첫 열은 바깥 층에 두고 스크롤 값만큼 옮겨 고정한다. 칸·머리의 모양은 호출하는 쪽이 정한다(글자는 htm이 이스케이프).
// 키보드: 화살표·Home·End·PageUp·PageDown으로 활성 칸을 옮기고 보이는 곳으로 스크롤한다(roving tabindex는 활성 칸 하나만 tab 정지).
import { html } from "./html.js";
import { useEffect, useLayoutEffect, useRef, useState } from "../../vendor/hooks.module.js";

/** 보이는 칸의 [처음, 끝) 번호. overscan은 위아래·좌우로 더 그리는 칸 수. */
export function visibleRange(offset, viewport, size, count, overscan = 3) {
  if (count <= 0 || size <= 0) return [0, 0];
  offset = Math.min(offset, Math.max(0, count * size - viewport));       // 끝을 넘은 스크롤 값은 끝으로
  const first = Math.max(0, Math.floor(offset / size) - overscan);
  const last = Math.min(count, Math.ceil((offset + viewport) / size) + overscan);
  return [first, Math.max(first, last)];
}

/** 활성 칸이 보이도록 스크롤 값을 고른다(이미 보이면 그대로). */
export function scrollFor(index, size, offset, viewport) {
  const start = index * size, end = start + size;
  if (start < offset) return start;
  if (end > offset + viewport) return end - viewport;
  return offset;
}

export function nextActive(key, a, rows, cols, page = 10) {
  const move = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], PageUp: [-page, 0], PageDown: [page, 0] }[key];
  let r = a.r, c = a.c;
  if (move) { r += move[0]; c += move[1]; }
  else if (key === "Home") c = 0;
  else if (key === "End") c = cols - 1;
  else return null;
  return { r: Math.max(0, Math.min(rows - 1, r)), c: Math.max(0, Math.min(cols - 1, c)) };
}

/**
 * props: rows(수), cols(수), rowH, colW, headH, headW, active {r,c}|null, onActive(r,c), onOpen(r,c),
 *        renderCell(r,c) -> 내용, renderColHead(c), renderRowHead(r), corner(내용), label(접근 이름)
 */
export function VirtualGrid({ rows, cols, rowH = 34, colW = 72, headH = 44, headW = 170, active, onActive, onOpen, renderCell, renderColHead, renderRowHead, corner, label }) {
  const box = useRef(null);
  const [view, setView] = useState({ top: 0, left: 0, w: 600, h: 300 });
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const measure = () => setView((v) => (v.w === el.clientWidth && v.h === el.clientHeight ? v : Object.assign({}, v, { w: el.clientWidth, h: el.clientHeight })));
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {      // 활성 칸이 바뀌면 보이는 곳으로
    const el = box.current;
    if (!el || !active) return;
    const top = scrollFor(active.r, rowH, el.scrollTop, el.clientHeight), left = scrollFor(active.c, colW, el.scrollLeft, el.clientWidth);
    if (top !== el.scrollTop) el.scrollTop = top;
    if (left !== el.scrollLeft) el.scrollLeft = left;
  }, [active && active.r, active && active.c]);

  const [r0, r1] = visibleRange(view.top, view.h, rowH, rows);
  const [c0, c1] = visibleRange(view.left, view.w, colW, cols);
  const onScroll = (e) => { const t = e.target; setView((v) => (v.top === t.scrollTop && v.left === t.scrollLeft ? v : Object.assign({}, v, { top: t.scrollTop, left: t.scrollLeft }))); };
  const onKey = (e) => {
    if (!active || !onActive) return;
    const n = nextActive(e.key, active, rows, cols, Math.max(1, Math.floor(view.h / rowH) - 1));
    if (n) { e.preventDefault(); onActive(n.r, n.c); }
    else if (e.key === "Enter" && onOpen) { e.preventDefault(); onOpen(active.r, active.c); }
  };
  const cells = [];
  for (let r = r0; r < r1; r++) {
    for (let c = c0; c < c1; c++) {
      const on = active && active.r === r && active.c === c;
      cells.push(html`<div key=${r + ":" + c} role="gridcell" class=${"vg-cell" + (on ? " on" : "")} aria-selected=${on ? "true" : "false"}
        style=${"top:" + r * rowH + "px;left:" + c * colW + "px;width:" + colW + "px;height:" + rowH + "px"}
        onClick=${() => { if (onActive) onActive(r, c); }} onDblClick=${() => { if (onOpen) onOpen(r, c); }}>${renderCell(r, c)}</div>`);
    }
  }
  const heads = [];
  for (let c = c0; c < c1; c++) heads.push(html`<div key=${"h" + c} class="vg-ch" style=${"left:" + c * colW + "px;width:" + colW + "px;height:" + headH + "px"}>${renderColHead(c)}</div>`);
  const rowHeads = [];
  for (let r = r0; r < r1; r++) rowHeads.push(html`<div key=${"r" + r} class="vg-rh" style=${"top:" + r * rowH + "px;height:" + rowH + "px;width:" + headW + "px"}>${renderRowHead(r)}</div>`);
  return html`<div class="vgrid" role="grid" aria-label=${label || "표"} aria-rowcount=${rows} aria-colcount=${cols} style=${"--vg-headh:" + headH + "px;--vg-headw:" + headW + "px"}>
    <div class="vg-corner" style=${"width:" + headW + "px;height:" + headH + "px"}>${corner}</div>
    <div class="vg-colheads" style=${"left:" + headW + "px;height:" + headH + "px"}><div style=${"position:relative;transform:translateX(" + -view.left + "px)"}>${heads}</div></div>
    <div class="vg-rowheads" style=${"top:" + headH + "px;width:" + headW + "px"}><div style=${"position:relative;transform:translateY(" + -view.top + "px)"}>${rowHeads}</div></div>
    <div class="vg-body" ref=${box} tabindex="0" onScroll=${onScroll} onKeyDown=${onKey}>
      <div class="vg-sizer" style=${"width:" + cols * colW + "px;height:" + rows * rowH + "px"}>${cells}</div></div></div>`;
}
