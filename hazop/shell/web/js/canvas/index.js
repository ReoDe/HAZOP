// 공간 색인과 고르기 계산(순수 함수. DOM·Preact를 쓰지 않는다). 규격: docs/design/app-shell-web.md §3.1·§5.4, 경계: ./README.md
//
// 도면 한 장의 구성요소 수천 개를 칸(기본 64px) 격자에 넣어 두고, 누르기·마우스 올림·네모 고르기가 전체를 훑지 않고 찾게 한다.
// 좌표는 모두 SVG 사용자 단위(도면 좌표)다. 자료 항목: {id, layer: "symbol"|"pipe"|"tag", bbox: [x0, y0, x1, y1],
// polyline: [[x, y], …] | null, polylines: [[[x, y], …], …] | null}. 같은 id가 층마다 따로 있을 수 있다(기호와 태그 상자).

export const MAX_SELECTION = 2000;   // 한 번에 알리는 고른 것의 상한(채팅 규격 §6.2). 넘으면 자르고 truncated를 단다
export const LAYER_RANK = { tag: 0, symbol: 1, pipe: 2 };   // 겹쳤을 때 위에 그려진 것이 먼저(태그 > 기호 > 배관)

/** @typedef {{x0: number, y0: number, x1: number, y1: number}} Rect */

export function normRect(r) {
  return { x0: Math.min(r.x0, r.x1), y0: Math.min(r.y0, r.y1), x1: Math.max(r.x0, r.x1), y1: Math.max(r.y0, r.y1) };
}

export function rectsOverlap(a, b) {
  return !(a.x1 < b.x0 || a.x0 > b.x1 || a.y1 < b.y0 || a.y0 > b.y1);
}

/** 선분 (ax,ay)-(bx,by)가 사각형과 만나는가(안에 있어도 참). Liang–Barsky. */
export function segmentHitsRect(ax, ay, bx, by, r) {
  let t0 = 0, t1 = 1;
  const dx = bx - ax, dy = by - ay;
  const p = [-dx, dx, -dy, dy], q = [ax - r.x0, r.x1 - ax, ay - r.y0, r.y1 - ay];
  for (let i = 0; i < 4; i++) {
    if (p[i] === 0) {
      if (q[i] < 0) return false;
    } else {
      const t = q[i] / p[i];
      if (p[i] < 0) { if (t > t1) return false; if (t > t0) t0 = t; }
      else { if (t < t0) return false; if (t < t1) t1 = t; }
    }
  }
  return true;
}

export function distToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
  let t = len2 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function linesOf(it) {
  if (it.polylines && it.polylines.length) return it.polylines;
  return it.polyline && it.polyline.length ? [it.polyline] : [];
}

function boundsOf(it) {
  if (it.bbox && it.bbox.length === 4) return { x0: it.bbox[0], y0: it.bbox[1], x1: it.bbox[2], y1: it.bbox[3] };
  let b = null;
  for (const line of linesOf(it)) for (const [x, y] of line) {
    if (!b) b = { x0: x, y0: y, x1: x, y1: y };
    else { b.x0 = Math.min(b.x0, x); b.y0 = Math.min(b.y0, y); b.x1 = Math.max(b.x1, x); b.y1 = Math.max(b.y1, y); }
  }
  return b;
}

export class SpatialIndex {
  /** @param {Array<object>} items @param {number} cell 칸 크기(도면 좌표) */
  constructor(items, cell = 64) {
    this.cell = cell;
    this.items = [];                // {id, layer, rect, lines, order}
    this.byId = new Map();          // id → 항목 목록(층마다 하나)
    this.grid = new Map();          // "cx,cy" → 항목 번호 목록
    (items || []).forEach((it) => this._add(it));
  }

  _add(it) {
    const rect = boundsOf(it);
    if (!rect || !it || typeof it.id !== "string") return;
    const rec = { id: it.id, layer: it.layer || "symbol", rect: normRect(rect), lines: it.layer === "pipe" ? linesOf(it) : [], order: this.items.length,
                  kind: it.kind || null, tag: it.tag || null, unknown: !!it.unknown };
    this.items.push(rec);
    if (!this.byId.has(rec.id)) this.byId.set(rec.id, []);
    this.byId.get(rec.id).push(rec);
    const c = this.cell;
    for (let cx = Math.floor(rec.rect.x0 / c); cx <= Math.floor(rec.rect.x1 / c); cx++)
      for (let cy = Math.floor(rec.rect.y0 / c); cy <= Math.floor(rec.rect.y1 / c); cy++) {
        const key = cx + "," + cy;
        const list = this.grid.get(key);
        if (list) list.push(rec.order); else this.grid.set(key, [rec.order]);
      }
  }

  get size() { return this.items.length; }

  has(id) { return this.byId.has(id); }

  /** 이 칸들에 걸친 후보(중복 없이). */
  _candidates(r) {
    const c = this.cell, seen = new Set(), out = [];
    // 큰 네모(도면 전체)는 칸을 하나씩 도는 것보다 항목 전체를 한 번 도는 쪽이 빠르다
    const cells = (Math.floor(r.x1 / c) - Math.floor(r.x0 / c) + 1) * (Math.floor(r.y1 / c) - Math.floor(r.y0 / c) + 1);
    if (cells > this.grid.size) return this.items.slice();
    for (let cx = Math.floor(r.x0 / c); cx <= Math.floor(r.x1 / c); cx++)
      for (let cy = Math.floor(r.y0 / c); cy <= Math.floor(r.y1 / c); cy++) {
        const list = this.grid.get(cx + "," + cy);
        if (!list) continue;
        for (const n of list) if (!seen.has(n)) { seen.add(n); out.push(this.items[n]); }
      }
    return out;
  }

  /**
   * 네모와 겹치는 구성요소 id(문서 순서, 중복 없음). 기호·태그 상자는 외곽 상자가 겹치면, 배관은 선이 네모를 지나면 고른다(규격 §3.1).
   * @param {Rect} rect @param {{layers?: Set<string>|null}} opts layers: 이 층만(꺼 둔 층은 뺀다)
   */
  queryBox(rect, opts = {}) {
    const r = normRect(rect), layers = opts.layers || null, hit = new Set();
    for (const rec of this._candidates(r)) {
      if (layers && !layers.has(rec.layer)) continue;
      if (!rectsOverlap(rec.rect, r)) continue;
      if (rec.layer === "pipe" && rec.lines.length) {
        let cross = false;
        for (const line of rec.lines) {
          for (let i = 0; i + 1 < line.length && !cross; i++) cross = segmentHitsRect(line[i][0], line[i][1], line[i + 1][0], line[i + 1][1], r);
          if (cross) break;
        }
        if (!cross) continue;
      }
      hit.add(rec.id);
    }
    return Array.from(hit).sort((a, b) => this._first(a) - this._first(b));
  }

  _first(id) { return this.byId.get(id)[0].order; }

  /**
   * 점 (x, y)에 있는 가장 위의 구성요소. tol은 배관·작은 상자를 누르기 쉽게 하는 여유(도면 좌표, 보통 6 / 배율).
   * 기호·태그는 상자 안이면, 배관은 선에서 tol 안이면 맞는다. 겹치면 태그 > 기호(작은 것 먼저) > 배관(가까운 것 먼저).
   * @returns {{id: string, layer: string}|null}
   */
  hitTest(x, y, tol = 0, opts = {}) {
    const layers = opts.layers || null;
    const probe = { x0: x - tol, y0: y - tol, x1: x + tol, y1: y + tol };
    let best = null, bestKey = null;
    for (const rec of this._candidates(probe)) {
      if (layers && !layers.has(rec.layer)) continue;
      let key;
      if (rec.layer === "pipe") {
        let d = Infinity;
        for (const line of rec.lines) for (let i = 0; i + 1 < line.length; i++)
          d = Math.min(d, distToSegment(x, y, line[i][0], line[i][1], line[i + 1][0], line[i + 1][1]));
        if (d > tol) continue;
        key = [LAYER_RANK.pipe, d];
      } else {
        const r = rec.rect;
        if (x < r.x0 - tol || x > r.x1 + tol || y < r.y0 - tol || y > r.y1 + tol) continue;
        key = [LAYER_RANK[rec.layer] ?? 1, (r.x1 - r.x0) * (r.y1 - r.y0)];
      }
      if (!bestKey || key[0] < bestKey[0] || (key[0] === bestKey[0] && key[1] < bestKey[1])) { best = rec; bestKey = key; }
    }
    return best ? { id: best.id, layer: best.layer } : null;
  }

  /** ids를 모두 담는 사각형(없으면 null). 확대해 보기(zoomTo)가 쓴다. */
  bounds(ids) {
    let b = null;
    for (const id of ids || []) for (const rec of this.byId.get(id) || []) {
      const r = rec.rect;
      if (!b) b = { x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 };
      else { b.x0 = Math.min(b.x0, r.x0); b.y0 = Math.min(b.y0, r.y0); b.x1 = Math.max(b.x1, r.x1); b.y1 = Math.max(b.y1, r.y1); }
    }
    return b;
  }

  /** id의 대표 사각형(기호 > 배관 > 태그 순). 말풍선 자리와 꼬리표 자리에 쓴다. */
  rectOf(id) {
    const list = this.byId.get(id);
    if (!list) return null;
    const pick = list.find((r) => r.layer === "symbol") || list.find((r) => r.layer === "pipe") || list[0];
    return pick.rect;
  }

  layersOf(id) { return (this.byId.get(id) || []).map((r) => r.layer); }
}

/** 고른 목록을 2,000개로 자른다. 앞에서부터(고른 차례) 남긴다. */
export function capSelection(ids, max = MAX_SELECTION) {
  return ids.length > max ? { ids: ids.slice(0, max), truncated: true } : { ids: ids.slice(), truncated: false };
}

/**
 * 고른 것(배열, 고른 차례)에 변경을 적용해 {selected, added, removed}를 낸다. 바뀐 것이 없으면 null.
 * mode: "add"(더하기) | "remove"(빼기) | "toggle"(없으면 더하고 있으면 빼기, ids는 하나)
 */
export function changeSelection(selected, ids, mode) {
  const have = new Set(selected), added = [], removed = [];
  let out = selected;
  if (mode === "toggle") mode = ids.length && have.has(ids[0]) ? "remove" : "add";
  if (mode === "add") {
    for (const id of ids) if (!have.has(id)) { have.add(id); added.push(id); }
    out = selected.concat(added);
  } else {
    const drop = new Set(ids);
    for (const id of selected) if (drop.has(id)) removed.push(id);
    out = selected.filter((id) => !drop.has(id));
  }
  return added.length || removed.length ? { selected: out, added, removed } : null;
}

/** 알림에 실을 모양 {selected, added, removed, via, truncated}. 2,000개를 넘으면 앞 2,000개만. */
export function selectionEvent(change, via, max = MAX_SELECTION) {
  const sel = capSelection(change.selected, max);
  const add = capSelection(change.added, max), rem = capSelection(change.removed, max);
  return { selected: sel.ids, added: add.ids, removed: rem.ids, via, truncated: sel.truncated || add.truncated || rem.truncated };
}
