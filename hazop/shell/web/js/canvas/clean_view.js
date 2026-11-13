// 정리된 보기(규격 §10): 읽은 결과(items + clean extras)를 원본과 같은 좌표에 표준 기호로 다시 그리는 계산. DOM이 없다(그리기 서술자만 만든다).
// 서술자는 marks.js와 같은 꼴 {t, a, c, x}이고, core.js가 createElementNS로 요소를 만든다. 도면·모델에서 온 글(태그, 번호)은 x(textContent)로만 넣는다.
// 기호 그림은 symbols.json(resources/library/drawing-symbols/에서 scripts/build_drawing_symbols.py가 만듦)만 쓴다.

const el = (t, a, c, x) => ({ t, a, c, x });

export const INK = "var(--ink, #0f1419)";
export const AMBER = "var(--warn-line, #a8740d)";
export const AI_LINE = "var(--ai-line, #8a929c)";
export const FAINT = "var(--faint, #8a929c)";
export const FRAME = "var(--line-strong, #b8bec6)";
const MONO = "var(--mono, 'Cascadia Mono', Consolas, monospace)";
const FONT = 9;                                   // 태그·번호 글자 크기(도면 단위)
const SYMBOL_W = 1.8;                             // 기호 선 굵기(화면 픽셀, 확대해도 같게)
const PIPE_W = { process: 2.0, process_secondary: 1.6, instrument_tap: 1.2, signal_electric: 1.2 };   // 화면 픽셀(확대해도 같게)
const PIPE_DASH = { instrument_tap: "6 3", signal_electric: "2 2" };
const MIN_LABEL_PX = 11;                          // 글자 크기의 화면 픽셀 하한(맞춤 배율에서도 읽히게)
const PORT_GAP = 8;                               // 연결점과 배관 끝을 잇는 거리 상한(넘으면 잇지 않고 port_gap 눈금)
const STUB_GAP = 4;                               // 기호 연결점과 배관 끝이 이보다 멀면 짧은 선으로 잇는다
const TAGGED = ["equipment", "valve", "instrument"];

const rot90 = (rot) => Math.round((((rot % 360) + 360) % 360) / 90) % 2 === 1;

/** 기호 그림을 bbox에 맞추는 변환(그림 좌표 → 도면 좌표): 가운데 이동 → 회전 → (뒤집기·크기) → 그림 가운데 맞춤. 규격 §10.3 '맞추기'. */
export function placement(sym, bbox, orient) {
  const [vw, vh] = sym.vb;
  const w = Math.max(bbox[2] - bbox[0], 0.5), h = Math.max(bbox[3] - bbox[1], 0.5);
  const rot = (orient && orient.rot) || 0;
  const [W, H] = rot90(rot) ? [h, w] : [w, h];       // 90°·270°면 맞출 때 가로세로를 바꿔 본다
  let sx, sy;
  if (sym.fit === "stretch") { sx = W / vw; sy = H / vh; } else { sx = sy = Math.min(W / vw, H / vh); }
  const fx = orient && orient.flip_h ? -1 : 1, fy = orient && orient.flip_v ? -1 : 1;
  return { cx: (bbox[0] + bbox[2]) / 2, cy: (bbox[1] + bbox[3]) / 2, rot, sx: sx * fx, sy: sy * fy, vw, vh };
}

export const transformOf = (p) => `translate(${r(p.cx)} ${r(p.cy)}) rotate(${p.rot}) scale(${r(p.sx, 5)} ${r(p.sy, 5)}) translate(${-p.vw / 2} ${-p.vh / 2})`;
const r = (v, n = 2) => Math.round(v * 10 ** n) / 10 ** n;

/** 그림 좌표의 한 점이 도면에서 놓이는 자리. */
export function toWorld(p, x, y) {
  const lx = (x - p.vw / 2) * p.sx, ly = (y - p.vh / 2) * p.sy;
  const a = (p.rot * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  return [p.cx + lx * c - ly * s, p.cy + lx * s + ly * c];
}

const strokeAttrs = (color, width, extra) => Object.assign({ stroke: color, "stroke-width": width, "vector-effect": "non-scaling-stroke", "stroke-linecap": "round", "stroke-linejoin": "round" }, extra);

function textEl(x, y, text, o = {}) {
  return el("text", { x: r(x), y: r(y), "text-anchor": o.anchor || "start", "font-family": MONO, "font-size": o.size || FONT, fill: o.fill || INK, "dominant-baseline": o.baseline || "auto",
    transform: o.rotate ? `rotate(${o.rotate} ${r(x)} ${r(y)})` : null, opacity: o.opacity, "pointer-events": "none" }, null, text);
}

/** 기호 하나의 그림 서술자. style: {color, width, fill(채움 색), fillOpacity, dash}. 그림이 없는 kind는 generic. */
export function symbolShapes(sym, bbox, orient, style = {}) {
  if (!sym || sym.junction) return [];
  const p = placement(sym, bbox, orient);
  const common = strokeAttrs(style.color || INK, style.width || SYMBOL_W, { "stroke-dasharray": style.dash || null, fill: style.fill || "none", "fill-opacity": style.fill ? style.fillOpacity : null });
  const kids = sym.shapes.map(([tag, attrs]) => el(tag, Object.assign({}, attrs, common)));
  return [el("g", { transform: transformOf(p), "data-id": style.id || null }, kids)];
}

function longest(line) {
  let best = null;
  for (let i = 0; i + 1 < line.length; i++) {
    const [a, b] = [line[i], line[i + 1]], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (!best || len > best.len) best = { a, b, len };
  }
  return best;
}

function arrowAt(a, b, t, color) {
  const x = a[0] + (b[0] - a[0]) * t, y = a[1] + (b[1] - a[1]) * t, ang = Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI, s = 5;
  return el("polygon", { points: `${-s},${-s * 0.7} ${s},0 ${-s},${s * 0.7}`, transform: `translate(${r(x)} ${r(y)}) rotate(${r(ang)})`, fill: color, stroke: "none", "pointer-events": "none" });
}

/** 흐름 화살촉: 40 단위 넘는 선분마다 가운데에, 긴 선분은 110 단위 간격으로 더 둔다(시안 7번처럼 일정 간격). */
function arrowsAlong(line, forward, color) {
  const out = [];
  for (let i = 0; i + 1 < line.length; i++) {
    const [a, b] = forward ? [line[i], line[i + 1]] : [line[line.length - 1 - i], line[line.length - 2 - i]];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (len < 40) continue;
    const n = Math.max(1, Math.round(len / 110));
    for (let j = 0; j < n; j++) out.push(arrowAt(a, b, (j + 0.5) / n, color));
  }
  return out;
}

/** 배관 하나: 길 그대로(종류별 굵기·점선) + 흐름 화살촉 + 열린 끝 빈 원. */
export function pipeShapes(rec, extra, style = {}) {
  const line = rec.lines && rec.lines[0] ? rec.lines[0] : null;
  if (!line || line.length < 2) return [];
  const type = (extra && extra.line_type) || "process";
  const color = style.color || INK, width = style.width || PIPE_W[type] || 1.4;
  const out = [el("polyline", Object.assign({ points: line.map((p) => r(p[0]) + "," + r(p[1])).join(" "), fill: "none", "data-id": style.id || null }, strokeAttrs(color, width, { "stroke-dasharray": style.dash || PIPE_DASH[type] || null })))];
  if (extra && extra.flow) out.push(...arrowsAlong(line, extra.flow === "source_to_target", color));   // 경로 위에서는 경로 색
  if (!style.recolor) {
    for (const e of (extra && extra.ends) || []) {
      if (e.status === "open" && e.point) out.push(el("circle", { cx: r(e.point[0]), cy: r(e.point[1]), r: 3, fill: "var(--card, #fff)", stroke: AMBER, "stroke-width": 1.4, "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
    }
  }
  return out;
}

function splitTag(tag) {
  const m = String(tag).split(/[-\s]/).filter(Boolean);
  return m.length > 1 ? [m[0], m.slice(1).join("-")] : [String(tag)];
}

/** 글자 한 줄의 자리 후보. 보이는 글자 크기는 화면 확대 값에 따라 layoutLabels가 정한다(화면 픽셀 하한). pri: 작을수록 먼저 자리를 잡는다. */
function labelSpec(x, y, text, o = {}) {
  return { x, y, text: String(text), anchor: o.anchor || "start", size: o.size || FONT, rotate: o.rotate || 0, fill: o.fill || INK, opacity: o.opacity, pri: o.pri == null ? 5 : o.pri,
    owner: o.owner || null, always: !!o.always, fixed: !!o.fixed, showFrom: o.showFrom || 0, hideFrom: o.hideFrom || 0, baseline: o.baseline || "auto" };
}

const amberTick = (x, y) => el("line", { x1: r(x - 3), y1: r(y - 3), x2: r(x + 3), y2: r(y + 3), stroke: AMBER, "stroke-width": 1.6, "vector-effect": "non-scaling-stroke", "pointer-events": "none" });
const attrDot = (x, y) => el("circle", { cx: r(x), cy: r(y), r: 2.5, fill: AMBER, stroke: "var(--card, #fff)", "stroke-width": 0.8, "vector-effect": "non-scaling-stroke", "pointer-events": "none" });
const PLACEMENT_REASONS = new Set(["unknown_symbol", "open_end", "missing_tag", "ai_candidate", "unplaced", "unresolved_connector"]);

/** 정리된 도면 전체(원본 SVG 없이). ctx: {symbols, width, height, items(recs 배열), extras(id → 그리기 자료), unconfirmed([{id, reason}]), textItems}.
 *  돌려주는 것: {nodes: 바탕 서술자, top: 불확실 표시(흐리기·표시 위에 그린다), labels: 글자 자리 후보, obstacles: 글자가 피할 기호 상자,
 *  missingKinds: 그림이 없어 generic으로 그린 kind, placeholders: 자리표 수}. */
export function buildBase(ctx) {
  const { symbols, width, height } = ctx, generic = symbols.generic;
  const nodes = [], top = [], missing = new Set(), labels = [], obstacles = [];
  let placeholders = 0;
  nodes.push(el("rect", { x: 0, y: 0, width, height, fill: "var(--card, #fff)", "pointer-events": "none" }));
  nodes.push(el("rect", { x: 8, y: 8, width: width - 16, height: height - 16, fill: "none", stroke: FRAME, "stroke-width": 1, "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
  const portsByNode = new Map(), tagSeen = new Map(), attrReasons = new Map();
  for (const u of ctx.unconfirmed || []) if (u.id && !PLACEMENT_REASONS.has(u.reason)) { if (!attrReasons.has(u.id)) attrReasons.set(u.id, []); attrReasons.get(u.id).push(u.reason); }
  for (const rec of ctx.items) {                      // 배관 번호는 같은 번호의 가장 긴 조각 하나에만 쓴다
    if (rec.layer !== "pipe" || !rec.tag) continue;
    const seg = rec.lines && rec.lines[0] ? longest(rec.lines[0]) : null;
    if (seg && (!tagSeen.has(rec.tag) || tagSeen.get(rec.tag).len < seg.len)) tagSeen.set(rec.tag, { id: rec.id, len: seg.len });
  }
  const pipes = [], symbolsOut = [];
  for (const rec of ctx.items) {
    const ex = ctx.extras[rec.id] || {};
    if (rec.layer === "pipe") {
      pipes.push(...pipeShapes(rec, ex, { id: rec.id }));
      const seg = rec.lines && rec.lines[0] ? longest(rec.lines[0]) : null;
      for (const e of ex.ends || []) if (e.status === "open" && e.point) top.push(el("circle", { cx: r(e.point[0]), cy: r(e.point[1]), r: 3, fill: "var(--card, #fff)", stroke: AMBER, "stroke-width": 1.4, "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
      if (seg && attrReasons.has(rec.id)) top.push(attrDot((seg.a[0] + seg.b[0]) / 2 + 6, (seg.a[1] + seg.b[1]) / 2 - 6));
      if (rec.tag && seg && tagSeen.get(rec.tag) && tagSeen.get(rec.tag).id === rec.id && seg.len > 24) {
        const mx = (seg.a[0] + seg.b[0]) / 2, my = (seg.a[1] + seg.b[1]) / 2, vertical = Math.abs(seg.b[1] - seg.a[1]) > Math.abs(seg.b[0] - seg.a[0]);
        labels.push(vertical ? labelSpec(mx - 2, my, rec.tag, { anchor: "middle", rotate: -90, pri: 4, owner: rec.id }) : labelSpec(mx, my - 2, rec.tag, { anchor: "middle", pri: 4, owner: rec.id }));
      }
      continue;
    }
    if (rec.layer !== "symbol") continue;
    const bb = [rec.rect.x0, rec.rect.y0, rec.rect.x1, rec.rect.y1], kind = rec.kind;
    const unknown = !kind || rec.unknown;
    const ai = ex.review === "ai_candidate";
    obstacles.push({ x0: bb[0], y0: bb[1], x1: bb[2], y1: bb[3], owner: rec.id });
    if (unknown && !ai) {                              // 미확인 기호: 호박색 점선 자리표 + 가운데 ? (흐리기 위에 그린다)
      placeholders++;
      top.push(el("rect", { "data-id": rec.id, x: r(bb[0]), y: r(bb[1]), width: r(Math.max(bb[2] - bb[0], 6)), height: r(Math.max(bb[3] - bb[1], 6)), fill: "var(--card, #fff)", "fill-opacity": 0.6, stroke: AMBER, "stroke-width": 1.4, "stroke-dasharray": "4 3", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
      top.push(textEl((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, "?", { anchor: "middle", baseline: "central", fill: AMBER, size: Math.min(14, Math.max(8, (bb[3] - bb[1]) * 0.6)) }));
      if (rec.tag) labels.push(labelSpec(bb[0], bb[3] + FONT + 1, rec.tag, { fill: AMBER, opacity: 0.85, pri: 0, owner: rec.id, always: true }));
      continue;
    }
    const sym = symbols[kind];
    if (sym && sym.junction) {                         // tee: 그림 없이 분기점의 검은 점
      symbolsOut.push(el("circle", { cx: r((bb[0] + bb[2]) / 2), cy: r((bb[1] + bb[3]) / 2), r: 1.5, fill: INK, "pointer-events": "none" }));
      continue;
    }
    const use = sym || generic;
    if (!sym) { missing.add(kind); placeholders++; }
    const style = ai ? { color: AI_LINE, dash: "3 2", id: rec.id } : { id: rec.id };
    symbolsOut.push(...symbolShapes(use, bb, ex.orient, style));
    if (!sym) top.push(textEl((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, String(kind || "?")[0].toUpperCase(), { anchor: "middle", baseline: "central", fill: FAINT, size: Math.min(14, Math.max(8, (bb[3] - bb[1]) * 0.5)) }));
    if (ai) top.push(textEl(bb[2], bb[1] - 2, "AI", { anchor: "end", size: 7, fill: AI_LINE }));
    if (attrReasons.has(rec.id)) top.push(attrDot(bb[2] + 3, bb[1] - 3));     // 속성만 미확인(흐름·체크밸브 방향·고장 시 위치·포트 등)
    if (use.ports && use.ports.length && ex.orient) {
      const p = placement(use, bb, ex.orient);
      portsByNode.set(rec.id, use.ports.map(([x, y]) => toWorld(p, x, y)));
    }
    const cx = (bb[0] + bb[2]) / 2, cy = (bb[1] + bb[3]) / 2, bw = bb[2] - bb[0], bh = bb[3] - bb[1];
    const color = ai ? AI_LINE : INK;
    if (kind === "continuation" && ex.label && ex.label.length) {        // 다른 도면 연결: 오각형 안에 원본 글자(안에 들어갈 만큼 크게 보일 때만)
      const big = Math.max(7 / 5.5, 38 / Math.max(bw, 1));      // 오각형 안 글자가 화면에서 7px 이상이 되는 확대 값부터 안쪽에, 그 전에는 아래에 한 줄(읽을 수 있는 크기)
      ex.label.forEach((t, i) => labels.push(labelSpec(cx, cy + (ex.label.length === 1 ? 2 : i ? 6 : -2), t, { anchor: "middle", size: 5.5, fixed: true, showFrom: big, pri: 3, owner: rec.id })));
      labels.push(labelSpec(cx, bb[3] + FONT + 1, ex.label[0], { anchor: "middle", pri: 3, owner: rec.id, hideFrom: big }));
    } else if (rec.tag) {
      if (rec.category === "instrument") {                // 계기: 원이 화면에서 충분히 크면 원 안 두 줄, 작으면 오른쪽 옆에 한 줄
        const lines = splitTag(rec.tag), minK = 24 / Math.max(bw, 1);
        lines.forEach((t, i) => labels.push(labelSpec(cx, cy + (lines.length === 1 ? 3 : i === 0 ? -1 : 8), t, { anchor: "middle", size: 8.5, fixed: true, showFrom: minK, fill: color, pri: 2, owner: rec.id })));
        labels.push(labelSpec(bb[2] + 2, cy + 3, rec.tag, { fill: color, pri: 2, owner: rec.id, hideFrom: minK }));
      } else if (rec.category === "equipment") {         // 설비: 설비 바로 옆(오른쪽 위)에 둔다. 원본에서 멀리 떨어진 글자 자리는 따르지 않는다
        labels.push(labelSpec(bb[2] + 3, bb[1] + FONT + 1, rec.tag, { fill: color, pri: 0, owner: rec.id }));
      } else {
        labels.push(labelSpec(cx, bb[3] + FONT + 1, rec.tag, { anchor: "middle", fill: color, pri: 1, owner: rec.id }));
      }
    } else if (TAGGED.includes(rec.category)) {          // 태그 없음: 호박색 점선 밑줄과 글자(늘 보인다)
      placeholders++;
      const y = bb[3] + FONT + 3;
      top.push(el("line", { x1: r(cx - 20), y1: r(y + 2), x2: r(cx + 20), y2: r(y + 2), stroke: AMBER, "stroke-width": 1, "stroke-dasharray": "3 2", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
      labels.push(labelSpec(cx, y, "태그 없음", { anchor: "middle", fill: AMBER, size: 7, pri: 0, always: true, owner: rec.id }));
    }
  }
  // 기호 연결점과 배관 끝: 그 배관 끝이 그 기호에 실제로 이어져 있고(그래프 연결) 8 단위 안이면 같은 굵기의 짧은 선으로 잇는다. 8 단위를 넘으면 잇지 않고
  // 호박색 눈금(port_gap)을 둔다. 이어지지 않은 끝은 위에서 열린 끝 원으로 그린다(이어진 것처럼 보이게 하지 않는다)
  const stubs = [];
  for (const rec of ctx.items) {
    if (rec.layer !== "pipe") continue;
    const ex = ctx.extras[rec.id] || {}, w = PIPE_W[ex.line_type] || 1.4;
    for (const e of ex.ends || []) {
      const ports = e.status === "connected" && e.node && portsByNode.get(e.node);
      if (!ports || !e.point) continue;
      let best = null;
      for (const q of ports) { const d = Math.hypot(q[0] - e.point[0], q[1] - e.point[1]); if (!best || d < best.d) best = { q, d }; }
      if (!best || best.d <= STUB_GAP) continue;
      if (best.d <= PORT_GAP) stubs.push(el("line", Object.assign({ x1: r(best.q[0]), y1: r(best.q[1]), x2: r(e.point[0]), y2: r(e.point[1]) }, strokeAttrs(INK, w, {}))));
      else top.push(amberTick(e.point[0], e.point[1]));
    }
  }
  for (const t of ctx.textItems || []) labels.push(labelSpec(t.bbox[0], t.bbox[1] + FONT, t.text, { pri: 5 }));
  nodes.push(...pipes, ...stubs, ...symbolsOut);
  return { nodes, top, labels, obstacles, missingKinds: [...missing].sort(), placeholders };
}

const wide = (ch) => (ch.charCodeAt(0) >= 0x2e80 ? 1 : 0.6);
const textWidth = (text, size) => { let w = 0; for (const ch of text) w += wide(ch); return w * size; };

/** 글자 자리 정하기(원본 뷰어의 uncrowdTags가 하던 일): 확대 값 k에서 글자 크기를 화면 픽셀 하한(minPx) 이상으로 하고, 먼저 자리를 잡는 글자(설비 → 밸브 →
 *  계기 → 배관 번호)부터 서로·기호 상자(자기 것은 빼고)와 겹치면 그 글자를 숨긴다. 호박색 '태그 없음'·미확인 글자는 늘 보인다.
 *  돌려주는 것: labels와 같은 순서의 [{visible, size}]. 순수 함수라 DOM 없이 시험한다. */
export function layoutLabels(labels, k, obstacles, minPx = MIN_LABEL_PX) {
  const out = labels.map(() => ({ visible: false, size: 0 }));
  const order = labels.map((l, i) => i).sort((a, b) => labels[a].pri - labels[b].pri || a - b);
  const cell = 60, grid = new Map();
  const cells = (b) => { const c = []; for (let x = Math.floor(b.x0 / cell); x <= Math.floor(b.x1 / cell); x++) for (let y = Math.floor(b.y0 / cell); y <= Math.floor(b.y1 / cell); y++) c.push(x + "," + y); return c; };
  const put = (b, tag) => { for (const c of cells(b)) { if (!grid.has(c)) grid.set(c, []); grid.get(c).push(Object.assign({ tag }, b)); } };
  for (const o of obstacles) put(o, o.owner);
  const hit = (b, owner) => { for (const c of cells(b)) for (const o of grid.get(c) || []) if (o.tag !== owner && !(b.x1 <= o.x0 || b.x0 >= o.x1 || b.y1 <= o.y0 || b.y0 >= o.y1)) return true; return false; };
  for (const i of order) {
    const l = labels[i];
    if (k < l.showFrom || (l.hideFrom && k >= l.hideFrom)) continue;               // 확대 값 조건(원 안 글자 등)
    const size = l.fixed ? l.size : Math.max(l.size, minPx / k);
    let w = textWidth(l.text, size), h = size;
    if (l.rotate) [w, h] = [h, w];
    const x0 = l.anchor === "middle" ? l.x - w / 2 : l.anchor === "end" ? l.x - w : l.x;
    const box = l.rotate ? { x0: l.x - w, y0: l.y - h / 2, x1: l.x, y1: l.y + h / 2 } : { x0, y0: l.y - h * 0.85, x1: x0 + w, y1: l.y + h * 0.2 };
    if (!l.always && !l.fixed && hit(box, l.owner)) continue;
    out[i] = { visible: true, size };
    if (!l.fixed) put(box, "label:" + i);
  }
  return out;
}

/** 표시가 걸린 객체를 그 색으로 다시 그린다(정리된 보기에서 '객체의 색을 바꾼다', 규격 §10.5). 못 그리면 null. */
export function recolor(ctx, rec, color, width, opts = {}) {
  const ex = ctx.extras[rec.id] || {};
  if (rec.layer === "pipe") return pipeShapes(rec, ex, { color, width: Math.max(width || 2.2, 1.6), recolor: true, dash: opts.dashed ? "6 4" : null });
  if (rec.layer !== "symbol") return null;
  const bb = [rec.rect.x0, rec.rect.y0, rec.rect.x1, rec.rect.y1], sym = ctx.symbols[rec.kind];
  if (!rec.kind || rec.unknown) return [];          // 미확인 자리표는 표시 색으로 바꾸지 않는다(점선 네모·?가 그대로 위에 보인다)
  if (ex.review === "ai_candidate") return [];
  if (sym && sym.junction) return [el("circle", { cx: r((bb[0] + bb[2]) / 2), cy: r((bb[1] + bb[3]) / 2), r: 2.5, fill: color, "pointer-events": "none" })];
  // 경로·표시에 든 밸브는 몸통을 채워 눈에 띄게 한다(시안 7번)
  const filled = !opts.fill && rec.category === "valve" && (width || 0) >= 2.6;
  return symbolShapes(sym || ctx.symbols.generic, bb, ex.orient, { color, width: Math.max(width || 2.2, 2.4), fill: filled ? color : (opts.fill || null), fillOpacity: filled ? 0.9 : opts.fillOpacity, dash: opts.dashed ? "4 3" : null });
}

/** 못 읽은 곳의 원본 조각: bbox를 사방 24 단위 넓힌 viewBox(도면 크기 안으로 자른다). 같은 원본 SVG를 <image>로 넣어 그 부분만 보인다(규격 §10.4). */
export function fragmentBox(bbox, size, pad = 24) {
  const x0 = Math.max(0, bbox[0] - pad), y0 = Math.max(0, bbox[1] - pad);
  const x1 = Math.min(size[0], bbox[2] + pad), y1 = Math.min(size[1], bbox[3] + pad);
  return { x: x0, y: y0, w: Math.max(x1 - x0, 1), h: Math.max(y1 - y0, 1) };
}

/** 기본 보기(규격 §10.5): drawio·dexpi는 정리, pdf_vector는 원본. 쪽이 확정되면 정리. */
export function defaultView(sourceFormat, confirmed = false) {
  if (sourceFormat === "drawio" || sourceFormat === "dexpi") return "clean";
  return confirmed ? "clean" : "orig";               // PDF·raster·모르는 값은 원본이 기본(확정된 쪽만 정리)
}

/** 글자 한 줄의 그리기 서술자(글자 크기는 layoutLabels가 정한 값). */
export function labelDescriptor(l, size) {
  return textEl(l.x, l.y, l.text, { anchor: l.anchor, size, fill: l.fill, opacity: l.opacity, rotate: l.rotate, baseline: l.baseline });
}
