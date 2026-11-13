// 도면 구성요소의 몸통(프레임워크 없는 DOM). sheet.js의 <Sheet>가 이것을 마운트해 쓴다. 이렇게 나눈 이유: Preact 없이도 단독 HTML에서
// 시험할 수 있고(tests/test_shell_canvas.py), 이동·확대 같은 잦은 갱신을 가상 DOM 비교 없이 CSS transform으로 바로 하기 위해서다.
// 규격: docs/design/app-shell-web.md §3.1·§5.4·§5.5, 경계: ./README.md
//
// 보안: 도면·모델에서 온 글(태그, 라벨, 이름)은 textContent로만 넣는다. innerHTML·dangerouslySetInnerHTML을 쓰지 않는다(정적 검사 대상).

import { SpatialIndex, MAX_SELECTION, capSelection, changeSelection, selectionEvent, normRect } from "./index.js";
import { normalizeMarks, drawAll, buildSegments, legendEntries, uncrowdTags, badgeBoxes } from "./marks.js";
import { buildBase, recolor, fragmentBox, layoutLabels, labelDescriptor } from "./clean_view.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const K_MIN = 0.05, K_MAX = 12;
const TAG_MIN_PX = 11;          // 도면 글자가 이 크기 미만이면 겹치지 않는 11px 글자를 따로 얹는다(지금 뷰어 U-13과 같은 기준)
const CLICK_SLOP = 3;           // 이만큼 이하로 움직인 뒤 뗀 것은 누르기
const SETTLE_MS = 120;          // 이동·확대가 멈춘 뒤 표시를 한 번 다시 그린다

const CSS = `
.hz-cv { position: relative; width: 100%; height: 100%; overflow: hidden; background: var(--bg, #f4f5f7); outline: none; }
.hz-cv-vp { position: absolute; inset: 0; overflow: hidden; touch-action: none; user-select: none; cursor: grab; }
.hz-cv[data-mode="pick"] .hz-cv-vp { cursor: crosshair; }
.hz-cv-vp.moving { cursor: grabbing; }
.hz-cv-world { position: absolute; left: 0; top: 0; transform-origin: 0 0; will-change: transform; }
.hz-cv-svg { display: block; overflow: visible; }
.hz-cv-tags { position: absolute; inset: 0; pointer-events: none; }
.hz-cv-tag { position: absolute; font: 11px/13px var(--font, system-ui, sans-serif); color: var(--ink, #0f1419); background: var(--card, #fff);
  border: 1px solid var(--line, #d6d9de); border-radius: 3px; padding: 0 3px; white-space: nowrap; }
.hz-cv-chips { position: absolute; inset: 0; pointer-events: none; }
.hz-cv-chip { position: absolute; pointer-events: auto; cursor: pointer; font: 12px/18px var(--font, system-ui, sans-serif); padding: 0 8px;
  border-radius: 9px; border: 1.2px solid var(--ui, #0a5fc2); background: var(--card, #fff); color: var(--ui, #0a5fc2); font-weight: 700; white-space: nowrap; }
.hz-cv-chip.warn { border-style: dashed; border-color: var(--warn-line, #a8740d); background: var(--warn-bg, #fdf0d2); color: var(--warn-ink, #74430a); }
.hz-cv-rubber { position: absolute; pointer-events: none; z-index: 5; border: 1.5px solid var(--ui, #0a5fc2); background: rgba(10,95,194,.10); box-sizing: border-box; }
.hz-cv-rubber.minus { border-style: dashed; background: rgba(166,30,77,.08); }
.hz-cv-legend { position: absolute; left: 16px; bottom: 64px; z-index: 4; display: none; max-width: calc(100% - 32px); box-sizing: border-box;
  background: var(--card, #fff); border: 1px solid var(--line, #d6d9de); border-radius: 12px; padding: 4px 12px; font: 12px/18px var(--font, system-ui, sans-serif); color: var(--ink-2, #2a313b); }
.hz-cv-legend.on { display: block; }
.hz-cv-legend span.it { display: inline-block; white-space: nowrap; margin-right: 10px; }
.hz-cv-legend i { display: inline-block; width: 16px; height: 0; border-top: 3px solid; vertical-align: middle; margin-right: 4px; }
.hz-cv-legend i.dash { border-top-style: dashed; }
.hz-cv-legend button { font: inherit; border: 0; background: none; color: var(--ui, #0a5fc2); cursor: pointer; text-decoration: underline; padding: 0 4px; }
`;

function build(desc, doc) {
  if (!desc) return null;
  const n = doc.createElementNS(SVG_NS, desc.t);
  for (const [k, v] of Object.entries(desc.a || {})) if (v != null) n.setAttribute(k, String(v));
  if (desc.x != null) n.textContent = String(desc.x);
  for (const c of desc.c || []) { const b = build(c, doc); if (b) n.appendChild(b); }
  return n;
}

export class SheetCore {
  /**
   * @param {HTMLElement} host 마운트할 상자
   * @param {object} cb 콜백: onReady, onItemClick, onItemDblClick, onHover, onSelection, onViewport, onMarkResult, onEsc, onLinkClick, onClearMarks, onSegmentClick, onUnconfirmedClick, onCleanBuilt
   */
  constructor(host, cb = {}) {
    this.host = host;
    this.cb = cb;
    this.doc = host.ownerDocument;
    this.data = null;
    this.index = new SpatialIndex([]);
    this.view = { x: 0, y: 0, k: 1 };
    this.mode = "pan";
    this.sel = [];
    this.marks = [];
    this.segments = [];
    this.outside = [];
    this.viewWanted = "orig";        // 'orig' | 'clean'(정리된 보기). 정리된 자료·기호가 아직 없으면 원본으로 그린다
    this.clean = null;               // /api/clean 자료 {items, text_items, unconfirmed, ...}
    this.symbols = null;             // symbols.json의 symbols
    this._cleanBuilt = false;
    this.cleanInfo = null;
    this.layers = { symbol: true, pipe: true, tag: true };
    this.lastCmd = null;
    this.size = [1, 1];
    this.pointer = null;
    this.space = false;
    this.hoverId = null;
    this.markObjs = new Map();
    this._timers = { settle: 0, raf: 0 };
    this.truncated = false;
    this._mount();
  }

  _mount() {
    const d = this.doc, h = this.host;
    h.classList.add("hz-cv");
    h.tabIndex = 0;
    h.setAttribute("data-mode", this.mode);
    this.style = d.createElement("style");
    this.style.textContent = CSS;
    h.appendChild(this.style);
    this.vp = d.createElement("div"); this.vp.className = "hz-cv-vp"; h.appendChild(this.vp);
    this.world = d.createElement("div"); this.world.className = "hz-cv-world"; this.vp.appendChild(this.world);
    this.svg = d.createElementNS(SVG_NS, "svg"); this.svg.setAttribute("class", "hz-cv-svg"); this.world.appendChild(this.svg);
    this.image = d.createElementNS(SVG_NS, "image"); this.svg.appendChild(this.image);
    this.cleanG = d.createElementNS(SVG_NS, "g"); this.cleanG.setAttribute("class", "hz-cv-clean"); this.cleanG.style.display = "none"; this.svg.appendChild(this.cleanG);
    this.ghost = d.createElementNS(SVG_NS, "image"); this.ghost.setAttribute("class", "hz-cv-ghost"); this.ghost.style.display = "none"; this.ghost.style.opacity = "0.3"; this.ghost.setAttribute("pointer-events", "none");   // 원본 겹쳐 보기를 켤 때만 붙인다
    this.marksG = d.createElementNS(SVG_NS, "g"); this.marksG.setAttribute("class", "hz-cv-marks"); this.svg.appendChild(this.marksG);
    this.topG = d.createElementNS(SVG_NS, "g"); this.topG.setAttribute("class", "hz-cv-top"); this.topG.style.display = "none"; this.svg.appendChild(this.topG);
    this.attrG = d.createElementNS(SVG_NS, "g"); this.attrG.setAttribute("class", "hz-cv-attr"); this.attrG.style.display = "none"; this.svg.appendChild(this.attrG);
    this.leftG = d.createElementNS(SVG_NS, "g"); this.leftG.setAttribute("class", "hz-cv-left"); this.leftG.style.display = "none"; this.svg.appendChild(this.leftG);
    this.tagsDiv = d.createElement("div"); this.tagsDiv.className = "hz-cv-tags"; this.vp.appendChild(this.tagsDiv);
    this.chipsDiv = d.createElement("div"); this.chipsDiv.className = "hz-cv-chips"; this.vp.appendChild(this.chipsDiv);
    this.legendDiv = d.createElement("div"); this.legendDiv.className = "hz-cv-legend"; h.appendChild(this.legendDiv);
    this.rubber = null;
    this._on = [];
    const on = (t, ev, fn, opt) => { t.addEventListener(ev, fn, opt); this._on.push([t, ev, fn, opt]); };
    on(this.vp, "pointerdown", (e) => this._down(e));
    on(this.vp, "pointermove", (e) => this._move(e));
    on(this.vp, "pointerup", (e) => this._up(e));
    on(this.vp, "pointercancel", () => this._cancel());
    on(this.vp, "wheel", (e) => this._wheel(e), { passive: false });
    on(this.vp, "dblclick", (e) => this._dbl(e));
    on(this.vp, "pointerleave", () => this._hover(null));
    on(d, "keydown", (e) => this._key(e, true));
    on(d, "keyup", (e) => this._key(e, false));
    this._ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => this._resized()) : null;
    if (this._ro) this._ro.observe(h);
  }

  destroy() {
    for (const [t, ev, fn, opt] of this._on) t.removeEventListener(ev, fn, opt);
    this._on = [];
    if (this._ro) this._ro.disconnect();
    clearTimeout(this._timers.settle);
    cancelAnimationFrame(this._timers.raf);
    this.host.textContent = "";
    this.host.classList.remove("hz-cv");
  }

  // ------------------------------------------------------------ 자료
  /** 도면 자료(JSON)를 넣는다. 그리기를 마치면 onReady(graph_id). */
  setData(data) {
    this.data = data;
    this.size = [Number(data.width) || 1, Number(data.height) || 1];
    this.index = new SpatialIndex(Array.isArray(data.items) ? data.items : []);
    this._unconf = null;
    this.svg.setAttribute("width", this.size[0]); this.svg.setAttribute("height", this.size[1]);
    this.svg.setAttribute("viewBox", `0 0 ${this.size[0]} ${this.size[1]}`);
    this.world.style.width = this.size[0] + "px"; this.world.style.height = this.size[1] + "px";
    this.image.setAttribute("width", this.size[0]); this.image.setAttribute("height", this.size[1]);
    this.sel = this.sel.filter((id) => this.index.has(id));
    this._cleanBuilt = false;        // 새 도면: 정리된 그림은 다시 만든다(자료는 update의 props로 새로 들어온다)
    this._leftBuilt = false;
    const finish = () => { this._viewChanged(true); this._renderMarks(); if (this.cb.onReady) this.cb.onReady(data.graph_id); };
    const href = typeof data.svg === "string" ? data.svg : "";
    let done = false;
    const once = () => { if (!done) { done = true; finish(); } };
    this.image.addEventListener("load", once, { once: true });
    this.image.addEventListener("error", once, { once: true });
    if (href) this.image.setAttribute("href", href); else once();
    if (!this._viewGiven) this.fit();
    this._renderChips();
  }

  _rect() { return this.vp.getBoundingClientRect(); }

  _resized() { if (this.data && !this._viewGiven) this.fit(); else this._scheduleSettle(); }

  // ------------------------------------------------------------ 정리된 보기
  /** 실제로 그리는 보기: 정리를 원해도 자료·기호가 아직 없으면 원본. */
  _effective() { return this.viewWanted === "clean" && this.clean && this.symbols && this.data ? "clean" : "orig"; }

  _cleanCtx() {
    if (!this._ctx || this._ctxFor !== this.clean) {
      this._ctxFor = this.clean;
      const extras = (this.clean && this.clean.items) || {};
      // 정돈한 좌표(tbox·tline)가 있으면 그것으로 그린다(원본 위치와 같은 자리, 작은 어긋남만 바로잡음). 누르기·고르기는 원본 좌표 색인을 그대로 쓴다
      const tidyMap = new Map(), items = this.index.items.map((rec) => {
        const ex = extras[rec.id];
        let t = rec;
        if (ex && rec.layer === "symbol" && ex.tbox) t = Object.assign({}, rec, { rect: { x0: ex.tbox[0], y0: ex.tbox[1], x1: ex.tbox[2], y1: ex.tbox[3] } });
        else if (ex && rec.layer === "pipe" && ex.tline && ex.tline.length >= 2) {
          const xs = ex.tline.map((q) => q[0]), ys = ex.tline.map((q) => q[1]);
          t = Object.assign({}, rec, { lines: [ex.tline], rect: { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) } });
        }
        if (t !== rec) tidyMap.set(rec.layer + ":" + rec.id, t);
        return t;
      });
      this._ctx = { symbols: this.symbols, extras, width: this.size[0], height: this.size[1], textItems: (this.clean && this.clean.text_items) || [],
        items, tidyMap, hops: (this.clean && this.clean.hops) || [], unconfirmed: (this.clean && this.clean.unconfirmed) || [] };
    }
    return this._ctx;
  }

  /** 보기(원본·정리)를 바꾼다. 같은 viewBox·같은 이동·확대 값을 쓰므로 화면이 움직이지 않는다. 정리된 그림은 처음 필요할 때 한 번 만든다. */
  _applyViewMode() {
    const eff = this._effective();
    if (eff === "clean" && !this._cleanBuilt) this._buildClean();
    this.image.style.display = eff === "clean" ? "none" : "";
    this.cleanG.style.display = eff === "clean" ? "" : "none";
    this.topG.style.display = eff === "clean" ? "" : "none";
    this._applyOverlays(eff);
    this.tagsDiv.style.display = eff === "clean" ? "none" : "";
    this.host.setAttribute("data-view", eff);
    this._unconf = null;
  }

  _buildClean() {
    const t0 = performance.now();
    this._ctxFor = null;
    const ctx = this._cleanCtx();
    const base = buildBase(ctx);
    while (this.cleanG.firstChild) this.cleanG.removeChild(this.cleanG.firstChild);
    const frag = this.doc.createDocumentFragment();
    for (const n of base.nodes) { const b = build(n, this.doc); if (b) frag.appendChild(b); }
    this.cleanG.appendChild(frag);
    this._labels = base.labels; this._obstacles = base.obstacles;
    this._labelEls = base.labels.map((l) => build(labelDescriptor(l, l.size), this.doc));   // 글자는 한 번 만들고 확대 값마다 크기·보임만 바꾼다
    const lf = this.doc.createDocumentFragment();
    for (const e of this._labelEls) lf.appendChild(e);
    this.cleanG.appendChild(lf);
    while (this.topG.firstChild) this.topG.removeChild(this.topG.firstChild);
    const tf = this.doc.createDocumentFragment();
    for (const n of base.top) { const b = build(n, this.doc); if (b) tf.appendChild(b); }
    this.topG.appendChild(tf);
    while (this.attrG.firstChild) this.attrG.removeChild(this.attrG.firstChild);   // 속성만 미확인인 자리: 평소에는 숨기고 미확인 칩을 누르면 보인다
    const af = this.doc.createDocumentFragment();
    for (const n of base.attr || []) { const b = build(n, this.doc); if (b) af.appendChild(b); }
    this.attrG.appendChild(af);
    this._cleanBuilt = true;
    this._layoutCleanLabels();
    this.cleanInfo = { ms: performance.now() - t0, elements: base.nodes.length, missingKinds: base.missingKinds, placeholders: base.placeholders };
    if (this.cb.onCleanBuilt) this.cb.onCleanBuilt(this.cleanInfo);
  }

  /** 새로 온 경로(path) 표시가 화면 밖에 걸치면 경로가 들어오게 맞춘다(같은 경로는 한 번만). */
  _fitNewPath() {
    this._pathSeen = this._pathSeen || new Set();
    for (const m of this.marks) {
      if (m.op !== "path" || this._pathSeen.has(m.id)) continue;
      this._pathSeen.add(m.id);
      const ids = (m.steps || []).map((s) => s.id).filter((id) => this.index.has(id));
      const b = ids.length ? this.index.bounds(ids) : null, r = this._rect();
      if (!b || !r.width) continue;
      const k = this.view.k, vx0 = -this.view.x / k, vy0 = -this.view.y / k, vx1 = vx0 + r.width / k, vy1 = vy0 + r.height / k;
      const inside = b.x0 >= vx0 && b.y0 >= vy0 && b.x1 <= vx1 && b.y1 <= vy1;
      if (!inside) this.zoomTo(ids, 0.15);
    }
  }

  /** 확대 값에 맞춰 글자 크기(화면 픽셀 하한)와 보임(겹치면 숨김)을 정한다. */
  _layoutCleanLabels() {
    if (!this._labels || !this._labelEls) return;
    // 경로·구간 표시의 번호 원·꼬리표도 글자가 피할 자리로 본다
    const extra = this.lastDraw && this.lastDraw.badges ? badgeBoxes(this.lastDraw.badges, this.view.k) : [];
    const res = layoutLabels(this._labels, this.view.k, extra.length ? this._obstacles.concat(extra) : this._obstacles);
    for (let i = 0; i < res.length; i++) {
      const el = this._labelEls[i], o = res[i];
      if (!el) continue;
      if (!o.visible) { if (el.style.display !== "none") el.style.display = "none"; continue; }
      if (el.style.display === "none") el.style.display = "";
      const s = String(Math.round(o.size * 100) / 100);
      if (el.getAttribute("font-size") !== s) el.setAttribute("font-size", s);
      const l = this._labels[i];
      if (l.place) {                                  // 자리 후보에서 고른 자리를 적용한다
        el.setAttribute("x", Math.round(o.x * 100) / 100); el.setAttribute("y", Math.round(o.y * 100) / 100);
        el.setAttribute("text-anchor", o.anchor);
        if (o.rotate) el.setAttribute("transform", `rotate(${o.rotate} ${Math.round(o.x * 100) / 100} ${Math.round(o.y * 100) / 100})`); else el.removeAttribute("transform");
      }
      el.setAttribute("stroke-width", String(Math.round((3 / this.view.k) * 100) / 100));
    }
  }

  /** 원본 겹쳐 보기(30%)·원본에 남은 것 겹치기: 정리된 보기 위에 옅게 얹는다(엔진 값이 없어도 원본 겹쳐 보기는 된다). */
  _applyOverlays(eff) {
    const o = this.overlays || {};
    const ghost = eff === "clean" && !!o.original && !!(this.data && this.data.svg);
    if (ghost && !this.ghost.parentNode) this.svg.insertBefore(this.ghost, this.marksG);
    this.attrG.style.display = eff === "clean" && o.unconfirmed ? "" : "none";
    this.ghost.style.display = ghost ? "" : "none";
    if (ghost) { this.ghost.setAttribute("href", this.data.svg); this.ghost.setAttribute("width", this.size[0]); this.ghost.setAttribute("height", this.size[1]); }
    const show = !!o.leftovers && !!(this.clean && this.clean.leftovers && this.clean.leftovers.counted);
    this.leftG.style.display = show ? "" : "none";
    if (show && !this._leftBuilt) {
      this._leftBuilt = true;
      for (const it of this.clean.leftovers.items) {
        if (!it.bbox) continue;
        const b = build({ t: "rect", a: { x: it.bbox[0], y: it.bbox[1], width: Math.max(it.bbox[2] - it.bbox[0], 4), height: Math.max(it.bbox[3] - it.bbox[1], 4), fill: "var(--warn-line, #a8740d)", "fill-opacity": 0.4,
          stroke: "var(--warn-line, #a8740d)", "stroke-dasharray": "4 3", "vector-effect": "non-scaling-stroke", "pointer-events": "none" } }, this.doc);
        this.leftG.appendChild(b);
      }
    }
  }

  /** 못 읽은 곳의 원본 조각: 같은 도면 SVG 주소와 잘라 보일 viewBox. 자료가 없으면 null. */
  fragmentOf(id) {
    const r = this.index.rectOf(id);
    if (!r || !this.data || !this.data.svg) return null;
    return { href: this.data.svg, size: this.size.slice(), box: fragmentBox([r.x0, r.y0, r.x1, r.y1], this.size) };
  }

  _unconfirmedAt(id) {
    if (!this._unconf) this._unconf = new Map(((this.clean && this.clean.unconfirmed) || []).map((u) => [u.id, u.reason]));
    return this._unconf.get(id) || null;
  }

  // ------------------------------------------------------------ 입력(props)
  update(p) {
    let marksDirty = false;
    if (p.mode && p.mode !== this.mode) { this.mode = p.mode === "pick" ? "pick" : "pan"; this.host.setAttribute("data-mode", this.mode); }
    if (p.symbols && p.symbols !== this._symProp) { this._symProp = p.symbols; this.symbols = p.symbols; this._cleanBuilt = false; marksDirty = true; }
    if (p.clean !== undefined && p.clean !== this._cleanProp) { this._cleanProp = p.clean; this.clean = p.clean; this._cleanBuilt = false; marksDirty = true; }
    if (p.overlays && p.overlays !== this._ovProp) { this._ovProp = p.overlays; this.overlays = p.overlays; this._leftBuilt = false; while (this.leftG.firstChild) this.leftG.removeChild(this.leftG.firstChild); marksDirty = true; }
    if (p.view && p.view !== this.viewWanted) { this.viewWanted = p.view === "clean" ? "clean" : "orig"; marksDirty = true; }
    if (marksDirty) this._applyViewMode();
    if (p.layers && p.layers !== this._layersProp) {
      this._layersProp = p.layers;
      this.layers = Object.assign({ symbol: true, pipe: true, tag: true }, p.layers);
      this._scheduleSettle();
    }
    if (p.selection && p.selection !== this._selProp) {
      this._selProp = p.selection;
      this.sel = capSelection(p.selection.filter((id) => this.index.has(id))).ids;
      marksDirty = true;
    }
    if (p.marks && p.marks !== this._marksProp) {
      this._marksProp = p.marks;
      this.marks = normalizeMarks(p.marks);
      marksDirty = true;
      this._fitNewPath();
    }
    if (p.outside && p.outside !== this._outProp) { this._outProp = p.outside; this.outside = p.outside; marksDirty = true; }
    if (p.segments && p.segments !== this._segProp) { this._segProp = p.segments; this.segments = p.segments; marksDirty = true; }
    if (p.viewport && p.viewport !== this._vpProp) {
      this._vpProp = p.viewport;
      const v = p.viewport;
      if ([v.x, v.y, v.k].every(Number.isFinite) && v.k > 0 && (v.x !== this.view.x || v.y !== this.view.y || v.k !== this.view.k)) {
        this._viewGiven = true;
        this.view = { x: v.x, y: v.y, k: Math.min(Math.max(v.k, K_MIN), K_MAX) };
        this._applyView();
        this._scheduleSettle();
      }
    }
    if (marksDirty) this._renderMarks();
    if (p.command && p.command.seq !== this.lastCmd) {
      this.lastCmd = p.command.seq;
      this._command(p.command);
    }
  }

  _command(c) {
    if (c.type === "zoomTo") this.zoomTo(c.ids || [], c.pad);
    else if (c.type === "inspect") {          // 미확인 자리로 가서 원본 조각 말풍선을 연다(N 키)
      this.zoomTo([c.id], c.pad);
      if (this.cb.onUnconfirmedClick) this.cb.onUnconfirmedClick({ id: c.id, reason: this._unconfirmedAt(c.id) || c.reason, fragment: this.fragmentOf(c.id), rect: null });
    }
    else if (c.type === "fit") this.fit();
    else if (c.type === "clearMarks") {
      this.marks = c.id == null ? [] : this.marks.filter((m) => String(m.id).split("#")[0] !== String(c.id).split("#")[0]);
      this._renderMarks();
    }
  }

  // ------------------------------------------------------------ 보기(이동·확대)
  /** 그려진 내용(기호·배관)의 범위 + 여백. 도면 용지의 여백이 커도 내용이 화면을 채우게 맞추는 기준이다. 내용이 없으면 도면 전체. */
  _contentRect() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const rec of this.index.items) {
      if (rec.layer === "tag") continue;
      x0 = Math.min(x0, rec.rect.x0); y0 = Math.min(y0, rec.rect.y0); x1 = Math.max(x1, rec.rect.x1); y1 = Math.max(y1, rec.rect.y1);
    }
    if (!isFinite(x0)) return { x0: 0, y0: 0, x1: this.size[0], y1: this.size[1] };
    const pad = 16;
    return { x0: Math.max(0, x0 - pad), y0: Math.max(0, y0 - pad), x1: Math.min(this.size[0], x1 + pad), y1: Math.min(this.size[1], y1 + pad) };
  }

  fit() {
    const r = this._rect();
    if (!r.width || !r.height || !this.data) return;
    const c = this._contentRect(), cw = Math.max(c.x1 - c.x0, 1), ch = Math.max(c.y1 - c.y0, 1);
    // 겹치는 화면 요소(위 보기 단추 줄, 아래 도구 막대, 표시가 있을 때의 범례)가 차지하는 자리만 빼고 그려진 내용의 둘레에 맞춘다
    const top = Math.min(60, r.height * 0.09), bottom = Math.min(this.marks.length ? 108 : 64, r.height * 0.15);
    const availH = Math.max(r.height - top - bottom, 1);
    const k = Math.min(r.width / cw, availH / ch) * 0.985;
    this.view = { k, x: (r.width - cw * k) / 2 - c.x0 * k, y: top + (availH - ch * k) / 2 - c.y0 * k };
    this._applyView();
    this._viewChanged(true);
  }

  zoomTo(ids, pad = 0.15) {
    const b = this.index.bounds(ids);
    const r = this._rect();
    if (!b || !r.width) return false;
    pad = typeof pad === "number" && pad >= 0 && pad < 5 ? pad : 0.15;
    const w = Math.max(b.x1 - b.x0, 20), h = Math.max(b.y1 - b.y0, 20);
    const k = Math.min(Math.max(Math.min(r.width / (w * (1 + 2 * pad)), r.height / (h * (1 + 2 * pad))), K_MIN), K_MAX);
    this.view = { k, x: r.width / 2 - ((b.x0 + b.x1) / 2) * k, y: r.height / 2 - ((b.y0 + b.y1) / 2) * k };
    this._applyView();
    this._viewChanged(true);
    return true;
  }

  _applyView() {
    const v = this.view;
    this.world.style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.k})`;
  }

  _scheduleSettle() {
    clearTimeout(this._timers.settle);
    this._timers.settle = setTimeout(() => this._viewChanged(true), SETTLE_MS);
  }

  /** 움직임이 멈춘 뒤: 표시를 현재 배율로 다시 그리고(꼬리표·화살표 크기), 태그 글자·칩 자리를 맞추고, 보기를 알린다. */
  _viewChanged(settled) {
    this._renderTags();
    this._renderChips();
    if (settled) {
      this._renderMarks(true);
      if (this.cb.onViewport) this.cb.onViewport({ x: this.view.x, y: this.view.y, k: this.view.k });
    }
  }

  _toSheet(clientX, clientY) {
    const r = this._rect(), v = this.view;
    return { x: (clientX - r.left - v.x) / v.k, y: (clientY - r.top - v.y) / v.k };
  }

  _toScreenRect(rect) {
    const v = this.view;
    return { x: rect.x0 * v.k + v.x, y: rect.y0 * v.k + v.y, w: (rect.x1 - rect.x0) * v.k, h: (rect.y1 - rect.y0) * v.k };
  }

  _layerSet() { return new Set(Object.entries(this.layers).filter(([, on]) => on).map(([k]) => k)); }

  // ------------------------------------------------------------ 포인터
  _wantsPan(e) {
    if (e.button === 1 || this.space) return true;
    if (this.mode === "pan" && !e.shiftKey && !e.altKey) return true;
    return false;
  }

  _down(e) {
    if (e.button !== 0 && e.button !== 1) return;
    if (e.target.closest && e.target.closest(".hz-cv-chip")) return;
    this.host.focus({ preventScroll: true });
    try { this.vp.setPointerCapture(e.pointerId); } catch (x) { /* 합성 이벤트는 캡처할 수 없다 */ }
    const pan = this._wantsPan(e);
    this.pointer = { x: e.clientX, y: e.clientY, vx: this.view.x, vy: this.view.y, pan, moved: false, alt: e.altKey, id: e.pointerId };
    if (pan) this.vp.classList.add("moving");
  }

  _move(e) {
    const p = this.pointer;
    if (!p) { this._hoverSoon(e); return; }
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (Math.abs(dx) + Math.abs(dy) > CLICK_SLOP) p.moved = true;
    if (!p.moved) return;
    if (p.pan) {
      this.view = { k: this.view.k, x: p.vx + dx, y: p.vy + dy };
      this._applyView();
    } else {
      this._drawRubber(p.x, p.y, e.clientX, e.clientY, p.alt || e.altKey);
    }
  }

  _up(e) {
    const p = this.pointer;
    if (!p) return;
    this.pointer = null;
    this.vp.classList.remove("moving");
    this._clearRubber();
    try { this.vp.releasePointerCapture(e.pointerId); } catch (x) { /* 무시 */ }
    if (p.moved && p.pan) { this._viewChanged(true); return; }
    if (p.moved) {
      const a = this._toSheet(p.x, p.y), b = this._toSheet(e.clientX, e.clientY);
      const ids = this.index.queryBox({ x0: a.x, y0: a.y, x1: b.x, y1: b.y }, { layers: this._layerSet() });
      const remove = p.alt || e.altKey;
      this._change(ids, remove ? "remove" : "add", remove ? "box_remove" : "box");
      return;
    }
    this._click(e);
  }

  _cancel() { this.pointer = null; this.vp.classList.remove("moving"); this._clearRubber(); }

  /** 구간 꼬리표(S1 등)를 눌렀는가: 꼬리표 자리는 marks.js의 badgeEl과 같은 계산이다. */
  _badgeAt(s) {
    const k = this.view.k;
    for (const b of (this.lastDraw && this.lastDraw.badges) || []) {
      if (!b.node_id) continue;
      const h = 15 / k, w = Math.max(15, b.text.length * 8 + 8) / k, x = b.rect.x0 - 4 / k, y = b.rect.y0 - h - 3 / k;
      if (s.x >= x && s.x <= x + w && s.y >= y && s.y <= y + h) return b;
    }
    return null;
  }

  _click(e) {
    const s = this._toSheet(e.clientX, e.clientY);
    const badge = this.cb.onSegmentClick ? this._badgeAt(s) : null;
    if (badge) { this.cb.onSegmentClick({ node_id: badge.node_id }); return; }
    const hit = this.index.hitTest(s.x, s.y, 6 / this.view.k, { layers: this._layerSet() });
    if (this.mode === "pick") {
      if (hit) this._change([hit.id], "toggle", "click");
      return;
    }
    if (!hit) return;
    const reason = this.cb.onUnconfirmedClick ? this._unconfirmedAt(hit.id) : null;
    if (reason) { const rr = this.index.rectOf(hit.id); this.cb.onUnconfirmedClick({ id: hit.id, reason, fragment: this.fragmentOf(hit.id), rect: rr ? this._toScreenRect(rr) : null }); }
    const rect = this.index.rectOf(hit.id), rec = (this.index.byId.get(hit.id) || [])[0];
    if (this.cb.onItemClick) this.cb.onItemClick({ id: hit.id, kind: rec && rec.kind, tag: rec && rec.tag, rect: rect ? this._toScreenRect(rect) : null, via: "click" });
  }

  _dbl(e) {
    const s = this._toSheet(e.clientX, e.clientY);
    const hit = this.index.hitTest(s.x, s.y, 6 / this.view.k, { layers: this._layerSet() });
    if (!hit) return;
    this.zoomTo([hit.id], 1.5);
    if (this.cb.onItemDblClick) this.cb.onItemDblClick({ id: hit.id });
  }

  _wheel(e) {
    e.preventDefault();
    const r = this._rect(), f = e.deltaY < 0 ? 1.15 : 1 / 1.15, v = this.view;
    const k = Math.min(Math.max(v.k * f, K_MIN), K_MAX), mx = e.clientX - r.left, my = e.clientY - r.top;
    this.view = { k, x: mx - ((mx - v.x) * k) / v.k, y: my - ((my - v.y) * k) / v.k };
    this._applyView();
    this._scheduleSettle();
  }

  _hoverSoon(e) {
    this._lastMove = e;
    if (this._timers.raf) return;
    this._timers.raf = requestAnimationFrame(() => {
      this._timers.raf = 0;
      const m = this._lastMove;
      if (!m || this.pointer) return;
      const s = this._toSheet(m.clientX, m.clientY);
      const hit = this.index.hitTest(s.x, s.y, 6 / this.view.k, { layers: this._layerSet() });
      this._hover(hit ? hit.id : null);
    });
  }

  _hover(id) {
    if (id === this.hoverId) return;
    this.hoverId = id;
    if (!this.cb.onHover) return;
    const rect = id ? this.index.rectOf(id) : null;
    this.cb.onHover(id && rect ? { id, rect: this._toScreenRect(rect) } : null);
  }

  _key(e, down) {
    const t = e.target;
    if (t && t.closest && t.closest("input, textarea, select, [contenteditable]")) return;
    if (e.code === "Space") { this.space = down; return; }
    if (!down || e.key !== "Escape") return;
    if (this.cb.onEsc) this.cb.onEsc();
    if (this.mode === "pick" && this.sel.length) this._change(this.sel.slice(), "remove", "clear");
  }

  // ------------------------------------------------------------ 고르기
  /** mode: "add" | "remove" | "toggle". 사용자 조작에서만 부른다(props.selection으로 바뀐 것은 알리지 않는다). */
  _change(ids, mode, via) {
    const ch = changeSelection(this.sel, ids, mode);
    if (!ch) return null;
    const capped = capSelection(ch.selected);
    this.sel = capped.ids;
    const ev = selectionEvent({ selected: ch.selected, added: ch.added, removed: ch.removed }, via);
    if (capped.truncated) ev.truncated = true;
    this._renderMarks();
    if (this.cb.onSelection) this.cb.onSelection(ev);
    return ev;
  }

  getSelection() { return this.sel.slice(); }

  _drawRubber(x0, y0, x1, y1, minus) {
    const r = this._rect();
    if (!this.rubber) { this.rubber = this.doc.createElement("div"); this.rubber.className = "hz-cv-rubber"; this.vp.appendChild(this.rubber); }
    this.rubber.classList.toggle("minus", !!minus);
    Object.assign(this.rubber.style, { left: Math.min(x0, x1) - r.left + "px", top: Math.min(y0, y1) - r.top + "px",
      width: Math.abs(x1 - x0) + "px", height: Math.abs(y1 - y0) + "px" });
  }

  _clearRubber() { if (this.rubber && this.rubber.parentNode) this.rubber.parentNode.removeChild(this.rubber); this.rubber = null; }

  // ------------------------------------------------------------ 그리기
  _renderMarks() {
    if (!this.data) return;
    const seg = this.segments.length ? buildSegments(this.segments, this.index) : null;
    const ctx = this._effective() === "clean" ? this._cleanCtx() : null;
    const out = drawAll({ marks: this.marks, seg, outside: this.outside, selection: this.sel, index: this.index, k: this.view.k, size: this.size,
      recolor: ctx ? (rec, color, width, opts) => recolor(ctx, rec, color, width, opts) : null, veil: ctx ? 0.62 : null });
    const g = this.marksG;
    while (g.firstChild) g.removeChild(g.firstChild);
    const frag = this.doc.createDocumentFragment();
    for (const n of out.nodes) { const b = build(n, this.doc); if (b) frag.appendChild(b); }
    g.appendChild(frag);
    this.lastDraw = out;
    this._legend(seg);
    this._renderTags();
    // 표시 결과 알림: 바뀐(또는 새) 표시만
    if (this.cb.onMarkResult) {
      const now = new Map(this.marks.map((m) => [m.id, m]));
      for (const [id, m] of now) if (this.markObjs.get(id) !== m) this.cb.onMarkResult({ id, missing: out.missing.get(id) || [] });
      this.markObjs = now;
    } else this.markObjs = new Map(this.marks.map((m) => [m.id, m]));
    this.lastDraw = out;
    return out;
  }

  _legend(seg) {
    const items = legendEntries(this.marks, seg);
    const d = this.legendDiv;
    d.textContent = "";
    d.classList.toggle("on", items.length > 0);
    for (const it of items) {
      const span = this.doc.createElement("span"); span.className = "it";
      const i = this.doc.createElement("i"); if (it.dashed) i.className = "dash"; i.style.borderTopColor = it.color;
      span.appendChild(i); span.appendChild(this.doc.createTextNode(it.text)); d.appendChild(span);
    }
    if (items.length) {
      const b = this.doc.createElement("button"); b.type = "button"; b.textContent = "지우기 (Esc)";
      b.addEventListener("click", () => { if (this.cb.onClearMarks) this.cb.onClearMarks(); else if (this.cb.onEsc) this.cb.onEsc(); });
      d.appendChild(b);
    }
  }

  /** 도면 글자가 11px보다 작게 보이면(확대 전) 겹치지 않게 11px 태그 글자를 얹는다. 글자는 textContent로만. */
  _renderTags() {
    if (this._effective() === "clean") { while (this.tagsDiv.firstChild) this.tagsDiv.removeChild(this.tagsDiv.firstChild); this._layoutCleanLabels(); return; }
    const box = this.tagsDiv;
    box.textContent = "";
    if (!this.data || !this.layers.tag) return;
    const v = this.view, labels = [], byId = new Map();
    const selected = new Set(this.sel);
    for (const rec of this.index.items) {
      if (rec.layer !== "tag" || !rec.tag) continue;
      const fs = (rec.rect.y1 - rec.rect.y0) / 1.2;
      if (fs * v.k >= TAG_MIN_PX) continue;      // 도면 글자가 읽히는 크기면 얹지 않는다
      const sr = this._toScreenRect(rec.rect);
      const w = Math.max(rec.tag.length * 7 + 8, 14);
      const l = { id: rec.id, x: sr.x, y: sr.y, w, h: 15, rank: selected.has(rec.id) ? 0 : 2, text: rec.tag };
      labels.push(l); byId.set(rec.id + "|" + rec.order, l);
    }
    const r = this._rect();
    const visible = labels.filter((l) => l.x + l.w >= 0 && l.y + l.h >= 0 && l.x <= r.width && l.y <= r.height);
    const shown = uncrowdTags(visible);
    const frag = this.doc.createDocumentFragment();
    for (const l of visible) {
      if (!shown.has(l.id)) continue;
      const s = this.doc.createElement("span"); s.className = "hz-cv-tag"; s.textContent = l.text;
      s.style.left = l.x + "px"; s.style.top = l.y + "px"; frag.appendChild(s);
    }
    box.appendChild(frag);
    this.tagCount = shown.size;
  }

  _renderChips() {
    const box = this.chipsDiv;
    box.textContent = "";
    if (!this.data || !Array.isArray(this.data.links)) return;
    const rows = new Map();
    for (const link of this.data.links) {
      if (!link || typeof link.id !== "string") continue;
      const rect = this.index.rectOf(link.id);
      if (!rect) continue;
      const sr = this._toScreenRect(rect), row = rows.get(link.id) || 0;
      rows.set(link.id, row + 1);
      const b = this.doc.createElement("button");
      b.type = "button"; b.className = "hz-cv-chip" + (link.status === "linked" ? "" : " warn");
      b.textContent = link.status === "linked" ? "→ " + (link.label || link.peer_graph_id || "") : "미연결" + (link.reason ? " · " + link.reason : "");
      b.style.left = sr.x + "px"; b.style.top = sr.y + sr.h + 4 + row * 20 + "px";
      b.addEventListener("click", (ev) => { ev.stopPropagation(); if (this.cb.onLinkClick) this.cb.onLinkClick(link); });
      box.appendChild(b);
    }
  }
}
