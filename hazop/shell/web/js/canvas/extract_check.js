// 도면 탭의 추출 확인 창(화면 단순화, 사용자 결정 2026-11-25): 원본 그림 위에 스크립트와 AI 검토가 읽어 낸 것을 네모로 겹쳐 보인다.
// 도면을 사람이 하나씩 확정하지 않으므로 이 겹침이 읽은 결과를 눈으로 확인하는 유일한 수단이다. 그래서 읽지 못한 곳(종류 미확인 기호)과
// 끊긴 연결(열린 끝 배관·이어지지 않은 도면 연결)은 색이 달라 눈에 띄게 한다. 구간 색 강조는 여기에 없고 구간 탭에서만 한다.
// 그리기는 캔버스의 기존 표시(mark) 길을 쓴다. 이 파일은 도면 자료(/api/sheet, /api/clean)에서 무엇을 어떤 색으로 칠할지만 정한다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { fetchClean, fetchSheet } from "./sheet.js";

export const CHECK_ID = "extract-check";
/** 범례: 칠하는 말(표시 스타일)과 화면 글. 색은 canvas/marks.js의 STYLE_COLORS가 정한다. */
export const LEGEND = [
  { key: "ok", style: "chk-ok", text: "읽음" },
  { key: "link", style: "chk-link", text: "도면 연결" },
  { key: "unknown", style: "chk-unknown", text: "읽지 못함" },
  { key: "broken", style: "chk-broken", text: "끊긴 연결" },
];

const BROKEN_REASONS = new Set(["open_end", "unresolved_connector"]);
const UNREAD_REASONS = new Set(["unknown_symbol", "ai_candidate", "missing_tag"]);

/** 도면 자료(sheet), 정리된 보기 자료(clean, 미확인 목록), 도면 연결(links, 구간 쪽이 읽은 것이 있으면 그것) → 칠할 묶음과 개수.
 *  끊긴 연결: 이어지지 않은 도면 연결, 열린 끝 배관. 읽지 못함: 종류를 못 정한 기호, 태그를 못 읽은 기호, 수락 전 AI 후보. */
export function extractGroups(sheet, clean, links) {
  const items = (sheet && sheet.items) || [];
  const linkOf = new Map((links || (sheet && sheet.links) || []).map((l) => [l.id, l]));
  const reasons = new Map();
  for (const u of (clean && clean.unconfirmed) || []) { if (!reasons.has(u.id)) reasons.set(u.id, new Set()); reasons.get(u.id).add(u.reason); }
  const any = (set, want) => !!set && [...set].some((r) => want.has(r));
  const ids = { ok: [], link: [], unknown: [], broken: [] };
  for (const it of items) {
    if (!it || !it.id || it.layer === "tag") continue;
    const link = linkOf.get(it.id), why = reasons.get(it.id);
    const unread = it.layer !== "pipe" && (it.unknown || any(why, UNREAD_REASONS));      // 무게: 읽지 못함 > 끊긴 연결 > 그 밖
    const broken = (link && link.status !== "linked") || any(why, BROKEN_REASONS) || (it.layer === "pipe" && it.unknown);
    if (unread) ids.unknown.push(it.id);
    else if (broken) ids.broken.push(it.id);
    else if (link) ids.link.push(it.id);
    else if (it.layer !== "pipe") ids.ok.push(it.id);
  }
  const groups = LEGEND.filter((l) => ids[l.key].length).map((l) => ({ ids: ids[l.key], style: l.style, label: null, thin: true }));      // 가는 테두리: 추적·강조 표시와 모양이 다르다
  const counts = Object.fromEntries(LEGEND.map((l) => [l.key, ids[l.key].length]));
  return { groups, counts, mark: groups.length ? { id: CHECK_ID, op: "mark", groups, dim_others: false, center: false } : null };
}

// 도면 자료는 도면과 판(rev)마다 한 번만 읽는다(캔버스가 읽는 것과 같은 주소라 브라우저가 한 번 더 받을 뿐이다)
const cache = new Map();
function load(gid, rev) {
  const key = gid + "@" + rev;
  for (const k of [...cache.keys()]) if (k.startsWith(gid + "@") && k !== key) cache.delete(k);      // 도면 판이 바뀌면 옛 자료는 버린다
  if (!cache.has(key)) {
    if (cache.size > 6) cache.delete(cache.keys().next().value);
    cache.set(key, Promise.all([fetchSheet(gid).catch(() => null), fetchClean(gid)]).then(([sheet, clean]) => ({ sheet, clean })));
  }
  return cache.get(key);
}
export const sheetFacts = load;

/** 추출 확인 창용 표시 하나와 개수. on이 거짓이거나 자료를 못 읽으면 표시가 없다. */
export function useExtractCheck(gid, rev, on, links) {
  const [state, setState] = useState({ gid: null, rev: null, mark: null, counts: null });
  useEffect(() => {
    if (!gid || !on) return undefined;
    let alive = true;
    load(gid, rev).then(({ sheet, clean }) => { if (alive && sheet) setState(Object.assign({ gid, rev }, extractGroups(sheet, clean, links))); });
    return () => { alive = false; };
  }, [gid, rev, on, links]);
  return on && state.gid === gid && state.rev === rev ? state : { mark: null, counts: null };
}

export function ExtractLegend({ counts }) {
  if (!counts) return null;
  const rows = LEGEND.filter((l) => counts[l.key]);
  if (!rows.length) return null;
  return html`<div class="float extract-legend" role="note" aria-label="추출 확인 색">${rows.map((l) => html`<span key=${l.key} class=${"el-item " + l.style}><i></i>${l.text} ${counts[l.key]}</span>`)}</div>`;
}

// ---------------------------------------------------------------- 구성요소 속성(누르면 뜨는 카드)

const label = (it) => (it && (it.tag || it.kind_label)) || null;

/** 이 구성요소에 이어진 배관·기기를 태그로: 기호면 이어진 배관(과 그 배관의 반대쪽 기기), 배관이면 양 끝의 기기. 태그가 없는 것은 뺀다. */
export function neighborsOf(id, sheet, clean) {
  const items = new Map(((sheet && sheet.items) || []).map((i) => [i.id, i]));
  const extras = (clean && clean.items) || {};
  const me = items.get(id);
  if (!me) return [];
  const endsOf = (pid) => ((extras[pid] || {}).ends || []).map((e) => e.node).filter(Boolean);
  const out = [];
  if (me.layer === "pipe") {
    for (const n of endsOf(id)) { const t = label(items.get(n)); if (t) out.push(t); }
  } else {
    for (const it of items.values()) {
      if (it.layer !== "pipe") continue;
      const ends = endsOf(it.id);
      if (!ends.includes(id)) continue;
      const peers = ends.filter((n) => n !== id).map((n) => label(items.get(n))).filter(Boolean);
      const pipe = it.tag || "배관";
      out.push(peers.length ? pipe + " → " + peers.join(", ") : pipe);
    }
  }
  return [...new Set(out)];
}

/** 이 구성요소가 든 구간(구간 탭이 읽은 도면 판 sheetView의 segments에서). */
export function segmentsOf(id, view) {
  return ((view && view.segments) || []).filter((s) => (s.ids || []).includes(id)).map((s) => s.node_id + (s.name ? " " + s.name : ""));
}
