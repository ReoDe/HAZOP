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
const SYMBOL_W = 1.4;                             // 기호 선 굵기(화면 픽셀, 확대해도 같게)
const PIPE_W = { process: 1.6, process_secondary: 1.2, instrument_tap: 1.0, signal_electric: 1.0 };
const PIPE_DASH = { instrument_tap: "6 3", signal_electric: "2 2" };
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

function arrow(seg, forward, color) {
  const [a, b] = forward ? [seg.a, seg.b] : [seg.b, seg.a];
  const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, ang = Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI, s = 4;
  return el("polygon", { points: `${-s},${-s * 0.7} ${s},0 ${-s},${s * 0.7}`, transform: `translate(${r(mx)} ${r(my)}) rotate(${r(ang)})`, fill: color, stroke: "none", "pointer-events": "none" });
}

/** 배관 하나: 길 그대로(종류별 굵기·점선) + 흐름 화살촉 + 열린 끝 빈 원. */
export function pipeShapes(rec, extra, style = {}) {
  const line = rec.lines && rec.lines[0] ? rec.lines[0] : null;
  if (!line || line.length < 2) return [];
  const type = (extra && extra.line_type) || "process";
  const color = style.color || INK, width = style.width || PIPE_W[type] || 1.4;
  const out = [el("polyline", Object.assign({ points: line.map((p) => r(p[0]) + "," + r(p[1])).join(" "), fill: "none", "data-id": style.id || null }, strokeAttrs(color, width, { "stroke-dasharray": style.dash || PIPE_DASH[type] || null })))];
  if (!style.recolor) {
    const seg = longest(line);
    if (extra && extra.flow && seg && seg.len > 14) out.push(arrow(seg, extra.flow === "source_to_target", color));
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

/** 정리된 도면 전체(원본 SVG 없이). ctx: {symbols, width, height, items(recs 배열), extras(id → 그리기 자료), unconfirmed(Set), textItems}.
 *  돌려주는 것: {nodes: 서술자 배열, missingKinds: 그림이 없어 generic으로 그린 kind 목록, placeholders: 자리표 수}. */
export function buildBase(ctx) {
  const { symbols, width, height } = ctx, generic = symbols.generic;
  const nodes = [], missing = new Set();
  let placeholders = 0;
  nodes.push(el("rect", { x: 0, y: 0, width, height, fill: "var(--card, #fff)", "pointer-events": "none" }));
  nodes.push(el("rect", { x: 8, y: 8, width: width - 16, height: height - 16, fill: "none", stroke: FRAME, "stroke-width": 1, "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
  const portsByNode = new Map(), tagSeen = new Map();
  for (const rec of ctx.items) {                      // 배관 번호는 같은 번호의 가장 긴 조각 하나에만 쓴다
    if (rec.layer !== "pipe" || !rec.tag) continue;
    const seg = rec.lines && rec.lines[0] ? longest(rec.lines[0]) : null;
    if (seg && (!tagSeen.has(rec.tag) || tagSeen.get(rec.tag).len < seg.len)) tagSeen.set(rec.tag, { id: rec.id, len: seg.len });
  }
  const pipes = [], symbolsOut = [], labels = [];
  for (const rec of ctx.items) {
    const ex = ctx.extras[rec.id] || {};
    if (rec.layer === "pipe") {
      pipes.push(...pipeShapes(rec, ex, { id: rec.id }));
      const seg = rec.lines && rec.lines[0] ? longest(rec.lines[0]) : null;
      if (rec.tag && seg && tagSeen.get(rec.tag) && tagSeen.get(rec.tag).id === rec.id && seg.len > 24) {
        const mx = (seg.a[0] + seg.b[0]) / 2, my = (seg.a[1] + seg.b[1]) / 2, vertical = Math.abs(seg.b[1] - seg.a[1]) > Math.abs(seg.b[0] - seg.a[0]);
        labels.push(vertical ? textEl(mx - 2, my, rec.tag, { anchor: "middle", rotate: -90 }) : textEl(mx, my - 2, rec.tag, { anchor: "middle" }));
      }
      continue;
    }
    if (rec.layer !== "symbol") continue;
    const bb = [rec.rect.x0, rec.rect.y0, rec.rect.x1, rec.rect.y1], kind = rec.kind;
    const unknown = !kind || rec.unknown;
    const ai = ex.review === "ai_candidate";
    if (unknown && !ai) {                              // 미확인 기호: 호박색 점선 자리표 + 가운데 ?
      placeholders++;
      symbolsOut.push(el("rect", { "data-id": rec.id, x: r(bb[0]), y: r(bb[1]), width: r(Math.max(bb[2] - bb[0], 6)), height: r(Math.max(bb[3] - bb[1], 6)), fill: "none", stroke: AMBER, "stroke-width": 1.4, "stroke-dasharray": "4 3", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
      symbolsOut.push(textEl((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, "?", { anchor: "middle", baseline: "central", fill: AMBER, size: Math.min(14, Math.max(8, (bb[3] - bb[1]) * 0.6)) }));
      if (rec.tag) labels.push(textEl(bb[0], bb[3] + FONT + 1, rec.tag, { fill: FAINT, opacity: 0.8 }));
      continue;
    }
    const sym = symbols[kind];
    if (sym && sym.junction) {                         // tee: 그림 없이 분기점의 검은 점
      symbolsOut.push(el("circle", { cx: r((bb[0] + bb[2]) / 2), cy: r((bb[1] + bb[3]) / 2), r: 1.5, fill: INK, "pointer-events": "none" }));
      continue;
    }
    const use = sym || generic;
    if (!sym) {
      missing.add(kind);
      placeholders++;
    }
    const style = ai ? { color: AI_LINE, dash: "3 2", id: rec.id } : { id: rec.id };
    symbolsOut.push(...symbolShapes(use, bb, ex.orient, style));
    if (!sym) symbolsOut.push(textEl((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, String(kind || "?")[0].toUpperCase(), { anchor: "middle", baseline: "central", fill: FAINT, size: Math.min(14, Math.max(8, (bb[3] - bb[1]) * 0.5)) }));
    if (ai) symbolsOut.push(textEl(bb[2], bb[1] - 2, "AI", { anchor: "end", size: 7, fill: AI_LINE }));
    if (use.ports && use.ports.length && ex.orient) {
      const p = placement(use, bb, ex.orient);
      portsByNode.set(rec.id, use.ports.map(([x, y]) => toWorld(p, x, y)));
    }
    // 태그: 계기는 원 안 두 줄, 나머지는 label_bbox 왼쪽 위, 없으면 기호 아래 가운데
    const category = rec.category;
    if (rec.tag) {
      const color = ai ? AI_LINE : INK;
      if (category === "instrument" && !rec.labelRect) {
        const lines = splitTag(rec.tag), cy = (bb[1] + bb[3]) / 2, cx = (bb[0] + bb[2]) / 2;
        lines.forEach((t, i) => labels.push(textEl(cx, cy + (lines.length === 1 ? 3 : i === 0 ? -1 : 8), t, { anchor: "middle", size: 6.5, fill: color })));
      } else if (rec.labelRect) {
        labels.push(textEl(rec.labelRect.x0, rec.labelRect.y0 + FONT, rec.tag, { fill: color }));
      } else if (kind === "continuation") {
        String(rec.tag).split("\n").slice(0, 2).forEach((t, i) => labels.push(textEl((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2 + (i ? 7 : -1), t, { anchor: "middle", size: 6.5, fill: color })));
      } else {
        labels.push(textEl((bb[0] + bb[2]) / 2, bb[3] + FONT + 1, rec.tag, { anchor: "middle", fill: color }));
      }
    } else if (TAGGED.includes(rec.category)) {        // 태그 없음: 호박색 점선 밑줄과 글자
      placeholders++;
      const y = bb[3] + FONT + 3, cx = (bb[0] + bb[2]) / 2;
      labels.push(el("line", { x1: r(cx - 20), y1: r(y + 2), x2: r(cx + 20), y2: r(y + 2), stroke: AMBER, "stroke-width": 1, "stroke-dasharray": "3 2", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
      labels.push(textEl(cx, y, "태그 없음", { anchor: "middle", fill: AMBER, size: 7 }));
    }
  }
  // 기호 연결점과 배관 끝이 4 단위보다 멀면 같은 굵기의 짧은 선으로 잇는다(배관을 옮기지 않는다)
  const stubs = [];
  for (const rec of ctx.items) {
    if (rec.layer !== "pipe") continue;
    const ex = ctx.extras[rec.id] || {}, w = PIPE_W[ex.line_type] || 1.4;
    for (const e of ex.ends || []) {
      const ports = e.node && portsByNode.get(e.node);
      if (!ports || !e.point) continue;
      let best = null;
      for (const q of ports) { const d = Math.hypot(q[0] - e.point[0], q[1] - e.point[1]); if (!best || d < best.d) best = { q, d }; }
      if (best && best.d > STUB_GAP && best.d < 40) stubs.push(el("line", Object.assign({ x1: r(best.q[0]), y1: r(best.q[1]), x2: r(e.point[0]), y2: r(e.point[1]) }, strokeAttrs(INK, w, {}))));
    }
  }
  for (const t of ctx.textItems || []) labels.push(textEl(t.bbox[0], t.bbox[1] + FONT, t.text));
  nodes.push(...pipes, ...stubs, ...symbolsOut, ...labels);
  return { nodes, missingKinds: [...missing].sort(), placeholders };
}

/** 표시가 걸린 객체를 그 색으로 다시 그린다(정리된 보기에서 '객체의 색을 바꾼다', 규격 §10.5). 못 그리면 null. */
export function recolor(ctx, rec, color, width, opts = {}) {
  const ex = ctx.extras[rec.id] || {};
  if (rec.layer === "pipe") return pipeShapes(rec, ex, { color, width: Math.max(width || 2.2, 1.6), recolor: true, dash: opts.dashed ? "6 4" : null });
  if (rec.layer !== "symbol") return null;
  const bb = [rec.rect.x0, rec.rect.y0, rec.rect.x1, rec.rect.y1], sym = ctx.symbols[rec.kind];
  if (!rec.kind || rec.unknown) {
    return [el("rect", { x: r(bb[0]), y: r(bb[1]), width: r(bb[2] - bb[0]), height: r(bb[3] - bb[1]), fill: "none", stroke: color, "stroke-width": width, "stroke-dasharray": "4 3", "vector-effect": "non-scaling-stroke", "pointer-events": "none" })];
  }
  if (sym && sym.junction) return [el("circle", { cx: r((bb[0] + bb[2]) / 2), cy: r((bb[1] + bb[3]) / 2), r: 2.5, fill: color, "pointer-events": "none" })];
  return symbolShapes(sym || ctx.symbols.generic, bb, ex.orient, { color, width: Math.max(width || 2.2, 1.8), fill: opts.fill || null, fillOpacity: opts.fillOpacity, dash: opts.dashed ? "4 3" : null });
}

/** 못 읽은 곳의 원본 조각: bbox를 사방 24 단위 넓힌 viewBox(도면 크기 안으로 자른다). 같은 원본 SVG를 <image>로 넣어 그 부분만 보인다(규격 §10.4). */
export function fragmentBox(bbox, size, pad = 24) {
  const x0 = Math.max(0, bbox[0] - pad), y0 = Math.max(0, bbox[1] - pad);
  const x1 = Math.min(size[0], bbox[2] + pad), y1 = Math.min(size[1], bbox[3] + pad);
  return { x: x0, y: y0, w: Math.max(x1 - x0, 1), h: Math.max(y1 - y0, 1) };
}

/** 기본 보기(규격 §10.5): drawio·dexpi는 정리, pdf_vector는 원본. 쪽이 확정되면 정리. */
export function defaultView(sourceFormat, confirmed = false) {
  if (confirmed) return "clean";
  return sourceFormat === "pdf_vector" ? "orig" : "clean";
}
