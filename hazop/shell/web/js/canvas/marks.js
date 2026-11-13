// 도면 위 표시 계산과 그리기 서술자(순수 함수. DOM·Preact를 쓰지 않는다). 규격: docs/design/app-shell-web.md §3.1, 경계: ./README.md
//
// 표시는 서로 지우지 않는다: 채팅 표시(mark·path)는 요청 ID로 덮어쓰고, 구간 색(segments)·고른 것(selection)은 따로 그린다.
// 그리는 것은 서술자 {t: 태그, a: 속성, x: 글자, c: 자식}뿐이고, DOM으로 바꾸는 일은 core.js가 한다. 글자는 x(textContent)로만 들어간다.

export const STYLE_COLORS = {
  focus: "var(--hl-focus, #0a5fc2)", path: "var(--path, #ea580c)", cause: "var(--hl-cause, #dc2626)",
  safeguard: "var(--hl-safeguard, #c026d3)", warn: "var(--hl-warn, #a8740d)", muted: "var(--hl-muted, #6b7280)",
};
export const SEG_COUNT = 5;   // 지금 구간 색은 seg1~seg5를 돌려 쓴다(채팅 규격 §6의 12색은 실제와 다름 — 보고)
export const DIM_OPACITY = 0.16;   // HL_DIM

export function styleColor(style) {
  const m = /^seg:(\d{1,2})$/.exec(String(style));
  if (m) return `var(--seg${(Number(m[1]) % SEG_COUNT) + 1}, #0b7285)`;
  return STYLE_COLORS[style] || STYLE_COLORS.focus;
}

export function segColor(index) { return `var(--seg${(index % SEG_COUNT) + 1}, #0b7285)`; }

/** 요청 ID의 본체: "q1#2" → "q1". */
export function baseId(id) { return String(id).split("#")[0]; }

/** 같은 ID는 나중 것이 덮어쓴다(순서는 처음 나온 자리). 잘못된 항목은 버린다. */
export function normalizeMarks(marks) {
  const out = new Map();
  for (const m of marks || []) {
    if (!m || typeof m.id !== "string") continue;
    if (m.op !== "mark" && m.op !== "path") continue;
    out.set(m.id, m);
  }
  return Array.from(out.values());
}

/** 표시 지우기: id가 없으면 전부, 있으면 그 요청(과 id#n)만. 구간 색·고른 것은 이 목록에 없으므로 건드리지 않는다. */
export function removeMarks(marks, id) {
  if (id == null) return [];
  return (marks || []).filter((m) => baseId(m.id) !== baseId(id));
}

function recsOf(index, id) { return index.byId.get(id) || []; }

/**
 * 표시 하나를 그릴 항목으로 푼다.
 * @returns {{id: string, op: string, items: Array, missing: string[], dim: boolean, badges: Array, arrows: Array}}
 */
export function resolveMark(mark, index) {
  const out = { id: mark.id, op: mark.op, items: [], missing: [], dim: mark.op === "path" ? true : mark.dim_others !== false, badges: [], arrows: [], labels: [] };
  if (mark.op === "mark") {
    for (const g of mark.groups || []) {
      const color = styleColor(g.style);
      let first = null;
      for (const id of g.ids || []) {
        const recs = recsOf(index, id);
        if (!recs.length) { out.missing.push(id); continue; }
        for (const rec of recs) {
          out.items.push({ id, rec, color, dashed: g.style === "warn" && rec.layer === "pipe" });
          if (!first || (first.layer !== "symbol" && rec.layer === "symbol")) first = rec;
        }
      }
      if (first && g.label) out.badges.push({ rect: first.rect, text: String(g.label), color });
    }
    return out;
  }
  // path: 번호 붙은 단계, 출발 파랑 상자, 확인 못 한 곳 호박색 점선, 흐름이 확인된 배관의 화살표
  const steps = Array.isArray(mark.steps) ? mark.steps : [];
  const color = styleColor(mark.style || "path");
  const found = steps.map((s) => recsOf(index, s.id));
  const objCenter = (j) => {
    const recs = found[j];
    const r = recs && recs.find((x) => x.layer !== "pipe");
    return r ? { x: (r.rect.x0 + r.rect.x1) / 2, y: (r.rect.y0 + r.rect.y1) / 2 } : null;
  };
  let n = 0, startDone = false;
  steps.forEach((s, i) => {
    const recs = found[i];
    if (!recs.length) { out.missing.push(s.id); return; }
    const pipe = recs.find((r) => r.layer === "pipe");
    const objs = recs.filter((r) => r.layer !== "pipe");
    const unknown = s.flow === "unknown" || recs.some((r) => r.unknown);
    for (const rec of recs) out.items.push({ id: s.id, rec, color, dashed: rec.layer === "pipe" && s.flow === "unknown" });
    if (pipe && (s.flow === "with" || s.flow === "against")) {
      const a = arrowOf(pipe, i > 0 ? objCenter(i - 1) : null, i + 1 < steps.length ? objCenter(i + 1) : null, s.flow);
      if (a) out.arrows.push(Object.assign({ color }, a));
    }
    if (objs.length) {
      const first = objs.find((r) => r.layer === "symbol") || objs[0];
      n++;
      if (mark.numbered !== false) out.badges.push({ rect: first.rect, text: String(n), color, round: true });
      if (!startDone) { startDone = true; out.items.push({ id: s.id, rec: first, color: STYLE_COLORS.focus, box: "start" }); }
      else if (unknown) out.items.push({ id: s.id, rec: first, color: STYLE_COLORS.warn, box: "unknown" });
    }
  });
  return out;
}

/** 배관 선의 가운데 점과 진행 각도(라디안). 앞 단계 객체에 가까운 끝에서 반대 끝으로 지나가는 방향이 기준이고, against면 반대. */
export function arrowOf(rec, prevC, nextC, flow) {
  const line = rec.lines && rec.lines[0];
  if (!line || line.length < 2) return null;
  let total = 0;
  const lens = [];
  for (let i = 0; i + 1 < line.length; i++) { const l = Math.hypot(line[i + 1][0] - line[i][0], line[i + 1][1] - line[i][1]); lens.push(l); total += l; }
  if (!(total > 0)) return null;
  let at = total / 2, i = 0;
  while (i < lens.length - 1 && at > lens[i]) { at -= lens[i]; i++; }
  const [ax, ay] = line[i], [bx, by] = line[i + 1], t = lens[i] ? at / lens[i] : 0;
  const x = ax + (bx - ax) * t, y = ay + (by - ay) * t;
  let ang = Math.atan2(by - ay, bx - ax);
  const first = line[0], last = line[line.length - 1];
  const d = (p, q) => Math.hypot(p.x - q[0], p.y - q[1]);
  let fwd = true;
  if (prevC) fwd = d(prevC, first) <= d(prevC, last);
  else if (nextC) fwd = d(nextC, last) <= d(nextC, first);
  if (!fwd) ang += Math.PI;
  if (flow === "against") ang += Math.PI;
  return { x, y, ang };
}

/** 구간 색 모델. segments: [{node_id, ids, color?, active?}]. active가 있으면 그 구간만 진하게 그리고 나머지는 흐리게 한다. */
export function buildSegments(segments, index) {
  const list = (segments || []).filter((s) => s && typeof s.node_id === "string");
  const focused = list.some((s) => s.active);
  const byItem = new Map();      // id → [{node_id, color}] (그리는 구간만, 처음 것이 바탕색)
  const badges = [];
  list.forEach((seg, k) => {
    if (focused && !seg.active) return;
    const color = seg.color || segColor(k);
    let first = null;
    for (const id of seg.ids || []) {
      const recs = recsOf(index, id);
      if (!recs.length) continue;
      if (!byItem.has(id)) byItem.set(id, []);
      byItem.get(id).push({ node_id: seg.node_id, color });
      for (const rec of recs) if (!first || (first.layer !== "symbol" && rec.layer === "symbol")) first = rec;
    }
    if (first) badges.push({ rect: first.rect, text: seg.node_id, color });
  });
  let overlaps = 0;
  for (const v of byItem.values()) if (v.length > 1) overlaps++;
  return { focused, byItem, badges, overlaps };
}

/** 구간 밖 구성요소(어느 구간에도 안 든 것) 수: items 전체 id 중 구간 모델에 없는 것. 흐리게 하는 자료와 개수 표시에 쓴다. */
export function outsideIds(allIds, segModel) {
  return allIds.filter((id) => !segModel.byItem.has(id));
}

// ---------------------------------------------------------------- 그리기 서술자

const el = (t, a, c, x) => ({ t, a, c, x });
const PAD = 2;

function shapeOf(item, k, widthPx, extra = {}) {
  const { rec, color } = item;
  const common = Object.assign({ stroke: color, "vector-effect": "non-scaling-stroke", fill: "none", "stroke-width": widthPx, "pointer-events": "none" }, extra);
  if (item.dashed) common["stroke-dasharray"] = "7 5";
  if (rec.layer === "pipe" && rec.lines.length) {
    return rec.lines.map((line) => el("polyline", Object.assign({ points: line.map((p) => p[0] + "," + p[1]).join(" "), "stroke-linejoin": "round", "stroke-linecap": "round" }, common)));
  }
  const r = rec.rect, pad = PAD / k;
  return [el("rect", Object.assign({ x: r.x0 - pad, y: r.y0 - pad, width: r.x1 - r.x0 + 2 * pad, height: r.y1 - r.y0 + 2 * pad, rx: 2 / k,
    fill: rec.layer === "tag" ? "none" : color, "fill-opacity": rec.layer === "tag" ? 0 : 0.16 }, common))];
}

function badgeEl(b, k) {
  const r = b.rect, h = 15 / k, w = (b.round ? 15 : Math.max(15, b.text.length * 8 + 8)) / k;
  const x = r.x0 - 4 / k, y = r.y0 - h - 3 / k;
  return el("g", { "pointer-events": "none" }, [
    el("rect", { x, y, width: w, height: h, rx: (b.round ? 7.5 : 3) / k, fill: b.color }),
    el("text", { x: x + w / 2, y: y + h * 0.75, "text-anchor": "middle", fill: "var(--on-seg, #fff)", "font-size": 11 / k, "font-weight": 700 }, null, b.text),
  ]);
}

function arrowEl(a, k) {
  const s = 8 / k;
  return el("polygon", { points: `${-s},${-s * 0.75} ${s},0 ${-s},${s * 0.75}`, transform: `translate(${a.x},${a.y}) rotate(${(a.ang * 180) / Math.PI})`,
    fill: a.color, stroke: "var(--card, #fff)", "stroke-width": 1, "vector-effect": "non-scaling-stroke", "pointer-events": "none" });
}

/**
 * 모든 표시를 한 서술자 목록으로 그린다. 순서: 흐림막 → 구간 색 → 채팅 표시 → 고른 것 → 꼬리표·화살표.
 * @param {{marks: Array, seg: object, selection: string[], index: object, k: number, dimOthers: boolean}} s
 * @returns {{nodes: Array, missing: Map<string, string[]>, dim: boolean}}
 */
export function drawAll({ marks, seg, selection, index, k = 1, size }) {
  const nodes = [], missing = new Map();
  const resolved = (marks || []).map((m) => resolveMark(m, index));
  const dimByMark = resolved.some((m) => m.dim);
  const dim = dimByMark || !!(seg && seg.focused);
  if (dim && size) nodes.push(el("rect", { x: 0, y: 0, width: size[0], height: size[1], fill: "var(--bg, #f4f5f7)", "fill-opacity": 1 - DIM_OPACITY, "pointer-events": "none" }));
  const badges = [], arrows = [];
  // 구간 색
  if (seg) {
    for (const [id, owners] of seg.byItem) {
      for (const rec of recsOf(index, id)) {
        nodes.push(...shapeOf({ rec, color: owners[0].color, dashed: false }, k, seg.focused ? 3 : 2.2));
        for (let i = 1; i < owners.length; i++)   // 겹침: 둘째 구간 색 줄무늬
          nodes.push(...shapeOf({ rec, color: owners[i].color, dashed: false }, k, seg.focused ? 3 : 2.2, { "stroke-dasharray": "6 6", "stroke-dashoffset": 6 }));
      }
    }
    badges.push(...seg.badges);
    for (const [id, owners] of seg.byItem) {
      if (owners.length < 2) continue;
      const rec = recsOf(index, id).find((r) => r.layer === "symbol");
      if (rec && badges.length < 400) badges.push({ rect: rec.rect, text: owners.map((o) => o.node_id).join("·"), color: "var(--ui, #0a5fc2)" });
    }
  }
  // 채팅 표시(요청마다)
  for (const m of resolved) {
    if (m.missing.length) missing.set(m.id, m.missing);
    for (const it of m.items) {
      if (it.box) {
        const r = it.rec.rect, pad = 5 / k;
        nodes.push(el("rect", { x: r.x0 - pad, y: r.y0 - pad, width: r.x1 - r.x0 + 2 * pad, height: r.y1 - r.y0 + 2 * pad, rx: 3 / k, fill: "none", stroke: it.color,
          "stroke-width": 2.2, "vector-effect": "non-scaling-stroke", "stroke-dasharray": it.box === "unknown" ? "6 4" : null, "pointer-events": "none" }));
      } else nodes.push(...shapeOf(it, k, it.rec.layer === "pipe" ? 4 : 2.6));
    }
    badges.push(...m.badges);
    arrows.push(...m.arrows);
  }
  // 고른 것(파랑)
  const seen = new Set();
  for (const id of selection || []) {
    if (seen.has(id)) continue;
    seen.add(id);
    for (const rec of recsOf(index, id)) nodes.push(...shapeOf({ rec, color: STYLE_COLORS.focus, dashed: false }, k, 3));
  }
  for (const a of arrows) nodes.push(arrowEl(a, k));
  for (const b of badges) nodes.push(badgeEl(b, k));
  return { nodes, missing, dim };
}

/** 범례 항목. 표시가 없으면 빈 목록. */
export function legendEntries(marks, seg) {
  const out = [];
  const m = marks || [];
  if (m.some((x) => x.op === "path")) {
    out.push({ text: "경로(굵은 선, 단계 번호)", color: STYLE_COLORS.path, dashed: false });
    out.push({ text: "출발", color: STYLE_COLORS.focus, dashed: false, box: true });
    out.push({ text: "확인 못 한 곳(점선)", color: STYLE_COLORS.warn, dashed: true });
  }
  const groups = m.filter((x) => x.op === "mark").flatMap((x) => x.groups || []);
  const styles = new Set(groups.map((g) => String(g.style).replace(/^seg:\d+$/, "seg")));
  const names = { focus: "고른 대상", path: "경로", cause: "원인", safeguard: "보호수단", warn: "확인 필요", muted: "참고", seg: "구간 색" };
  for (const s of styles) if (names[s]) out.push({ text: names[s], color: s === "seg" ? segColor(0) : STYLE_COLORS[s], dashed: s === "warn" });
  if (seg && seg.byItem && seg.byItem.size) out.push({ text: seg.focused ? "고른 구간만 진하게" : "구간 색(겹치면 줄무늬)", color: segColor(0), dashed: false });
  return out;
}

/**
 * 태그 글자 겹침 풀기(uncrowdTags). labels: [{id, x, y, w, h, rank}] 화면 좌표. rank가 작을수록 먼저 둔다(고른 것 0, 구간 안 1, 나머지 2).
 * 앞에 놓인 글자와 겹치면 숨긴다. 보이는 id 집합을 낸다.
 */
export function uncrowdTags(labels, cell = 48) {
  const order = labels.map((l, i) => [l, i]).sort((a, b) => (a[0].rank - b[0].rank) || (a[1] - b[1]));
  const grid = new Map(), shown = new Set();
  for (const [l] of order) {
    const x0 = l.x, y0 = l.y, x1 = l.x + l.w, y1 = l.y + l.h;
    const cells = [];
    for (let cx = Math.floor(x0 / cell); cx <= Math.floor(x1 / cell); cx++)
      for (let cy = Math.floor(y0 / cell); cy <= Math.floor(y1 / cell); cy++) cells.push(cx + "," + cy);
    let clash = false;
    for (const key of cells) {
      for (const o of grid.get(key) || []) if (!(x1 <= o.x0 || x0 >= o.x1 || y1 <= o.y0 || y0 >= o.y1)) { clash = true; break; }
      if (clash) break;
    }
    if (clash) continue;
    shown.add(l.id);
    for (const key of cells) { if (!grid.has(key)) grid.set(key, []); grid.get(key).push({ x0, y0, x1, y1 }); }
  }
  return shown;
}
