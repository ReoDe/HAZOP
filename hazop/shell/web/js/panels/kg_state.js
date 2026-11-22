// 지식그래프 패널(완료 목록 2 A6)의 화면 상태와 엔진 잇기. 저장하는 자료(잠재 후보 판단)는 엔진만 쓴다: 읽어 온 요약·그래프·상세와 보기 상태
// (펼친 도면, 고른 노드, 찾기 글, 켠 층)만 들고, 판단은 읽은 판 지문(ver)을 실어 명령으로 보낸 뒤 changed("kg")로 다시 읽는다(낙관적 갱신 없음).
// 웹은 경로를 보내지 않는다: 노드 ID·도면 graph_id·동작 이름·사람이 친 사유와 근거만 보낸다.
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";

const EMPTY = { available: false, reason: "", ver: "none", cap: 1500, total: 0, mode: "full", expand: [], groups: [], layers: {}, expect: { states: [], recheck: 0 }, notes: [] };

export const kg = createStore({
  summary: EMPTY,
  graph: null,            // GET kg/graph: {nodes, links, expanded, count, cap}
  expanded: [],           // 펼친 묶음(도면 graph_id)
  selected: null,         // 고른 노드 ID
  detail: null,           // GET kg/node
  hits: [],               // 찾기 결과
  query: "",
  layers: { pid: true, kn: true, exp: true },
  allStates: false,       // 확인됨·무관도 그릴지(처음엔 엔진이 정한 기본 켬 상태만)
  busy: false,
  error: null,
  notice: null,
  seq: 0,                 // 그래프를 다시 그리라는 신호(맞추기·가운데로)
  center: null,           // 가운데로 옮길 노드 ID
  study: false,           // 검토 층(분석 결과·초기사건 투영)을 켰는지(완료 목록 3 B6)
  explore: null,          // 살펴보기 결과 {what, label, active, reason, ids, count, note, by_group}
  linkId: null,           // 고른 관계(선) ID
  link: null,             // GET kg/link
});

export function useKg(selector) {
  const [value, setValue] = useState(() => selector(kg.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(kg.get());
    return kg.subscribe(sync);
  }, []);
  return value;
}

const errorText = (e) => (e && e.message) || "처리하지 못했습니다.";
// 순번 셋: epoch는 프로젝트가 바뀔 때만(그 전에 시작한 읽기는 모두 버림), sumSeq·graphSeq는 같은 읽기끼리 마지막 것만 쓴다.
// 하나로 묶어 두면 다른 곳(문서 패널·채팅의 패널 열기)이 요약을 다시 읽을 때 패널이 읽던 그래프까지 버려 그림이 비었다.
let epoch = 0;
let sumSeq = 0;
let graphSeq = 0;

export function reset() {
  epoch++;
  kg.set({ summary: EMPTY, graph: null, expanded: [], selected: null, detail: null, hits: [], query: "", busy: false, error: null, notice: null,
    explore: null, linkId: null, link: null });
}

// 검토 층을 켰으면 모든 읽기에 study=1을 붙인다(엔진이 같은 층의 모델로 답한다)
const st = (sep) => (kg.get().study ? sep + "study=1" : "");

export async function loadSummary() {
  const mine = ++sumSeq;
  const ep = epoch;
  let s;
  try { s = await read("kg" + st("?")); } catch (e) { s = Object.assign({}, EMPTY, { reason: "지식그래프를 읽지 못했습니다." }); }
  if (mine !== sumSeq || ep !== epoch) return kg.get().summary;
  const known = new Set((s.groups || []).map((g) => g.id));
  const prev = kg.get().expanded.filter((g) => known.has(g));
  const first = kg.get().summary === EMPTY || kg.get().summary.project_id !== s.project_id;
  kg.set({ summary: s, expanded: first ? (s.expand || []) : prev });
  return s;
}

export async function loadGraph() {
  const s = kg.get().summary;
  if (!s.available) { kg.set({ graph: null }); return null; }
  const mine = ++graphSeq;
  const ep = epoch;
  let g;
  try { g = await read("kg/graph?expand=" + encodeURIComponent(kg.get().expanded.join(",")) + st("&")); } catch (e) { kg.set({ error: "그래프를 읽지 못했습니다." }); return null; }
  if (mine !== graphSeq || ep !== epoch) return null;
  if (g.refused) { kg.set({ error: g.refused }); return null; }
  kg.set({ graph: g });
  return g;
}

export async function loadDetail(id) {
  if (!id) { kg.set({ detail: null }); return null; }
  let d = null;
  try { d = await read("kg/node?id=" + encodeURIComponent(id) + st("&")); } catch (e) { d = null; }
  if (kg.get().selected !== id) return null;
  kg.set({ detail: d });
  return d;
}

export async function refresh() {
  await loadSummary();
  await loadGraph();
  const sel = kg.get().selected;
  if (sel) await loadDetail(sel);
  const lk = kg.get().linkId;
  if (lk) await loadLink(lk);
  const x = kg.get().explore;
  if (x) await explore(x.what, x.start);       // 자료가 바뀌었으면 같은 살펴보기를 다시 센다
}

// ---------------------------------------------------------------- 살펴보기·검토 층·관계(완료 목록 3 B6)
export const EXPLORES = [["reach", "도달 범위", "고른 도면 구성요소가 든 검토구간 안에서 닿는 곳"],
  ["orphans", "고아 지식", "설비에 적용되지 않았거나 도면과 이어지지 않은 지식"],
  ["gaps", "근거 공백", "문서가 언급하지만 설정치·요건이 걸리지 않은 구성요소"]];

let exploreSeq = 0;
/** 엔진 알고리즘(도달 범위·고아·근거 공백)으로 셀 것을 강조한다. 도달 범위는 고른 노드에서 센다. */
export async function explore(what, start) {
  if (!what) { kg.set({ explore: null }); return null; }
  const mine = ++exploreSeq;
  const ep = epoch;
  const from = what === "reach" ? (start !== undefined ? start : kg.get().selected) : null;
  let r;
  try { r = await read("kg/explore?what=" + encodeURIComponent(what) + (from ? "&start=" + encodeURIComponent(from) : "") + st("&")); }
  catch (e) { r = null; }
  if (mine !== exploreSeq || ep !== epoch) return null;
  if (!r) { kg.set({ explore: null, error: "살펴보기를 셀 수 없었습니다." }); return null; }
  kg.set({ explore: r });
  return r;
}
export function clearExplore() { exploreSeq++; kg.set({ explore: null }); }

/** 검토 층 켜기·끄기: 분석 결과의 시나리오·보호수단·초기사건 후보를 그래프에 얹는다(읽기 전용). */
export async function setStudy(on) {
  kg.set({ study: !!on, linkId: null, link: null });
  if (!on && kg.get().selected && kg.get().selected.startsWith("st-")) kg.set({ selected: null, detail: null });
  await refresh();
}

export async function loadLink(id) {
  let d = null;
  try { d = await read("kg/link?id=" + encodeURIComponent(id) + st("&")); } catch (e) { d = null; }
  if (kg.get().linkId !== id) return null;
  kg.set({ link: d });
  return d;
}

/** 관계(선)를 고르면 오른쪽에 그 선이 어디서 왔는지(근거)를 보인다. 노드 고르기는 푼다. */
export function selectLink(id) {
  if (!id) { kg.set({ linkId: null, link: null }); return null; }
  kg.set({ linkId: id, link: null, selected: null, detail: null, error: null, notice: null });
  return loadLink(id);
}

// ---------------------------------------------------------------- 보기 동작
const groupOf = (gid) => kg.get().summary.groups.find((g) => g.id === gid);
const countOf = (ids) => ids.reduce((n, id) => n + ((groupOf(id) || {}).count || 0), 0);

/** 도면 묶음을 펼친다. 합이 상한을 넘으면 펼친 것 가운데 오래된 것부터 접는다. */
export async function expand(gid) {
  const cap = kg.get().summary.cap;
  if (!groupOf(gid)) return false;
  let next = kg.get().expanded.filter((x) => x !== gid).concat([gid]);
  while (next.length > 1 && countOf(next) > cap) next = next.slice(1);
  if (countOf(next) > cap) { kg.set({ error: "이 도면 하나의 노드가 상한을 넘습니다. 찾기로 노드를 고르세요." }); return false; }
  kg.set({ expanded: next, error: null });
  await loadGraph();
  return true;
}

export async function collapse(gid) {
  kg.set({ expanded: kg.get().expanded.filter((x) => x !== gid) });
  await loadGraph();
}

export async function collapseAll() { kg.set({ expanded: [], selected: null, detail: null }); await loadGraph(); }

export function select(id) {
  if (!id) { kg.set({ selected: null, detail: null }); return null; }
  kg.set({ selected: id, detail: null, error: null, notice: null, linkId: null, link: null });
  return loadDetail(id);
}

/** 찾기·이웃·채팅에서 고른 노드: 그 노드의 도면을 펼치고 고른 뒤 가운데로 옮긴다. */
export async function focus(id, group) {
  let g = group;
  if (!g) {
    const d = await read("kg/node?id=" + encodeURIComponent(id) + st("&")).catch(() => null);
    if (!d) { kg.set({ error: "그래프에서 그 노드를 찾지 못했습니다." }); return false; }
    g = d.group;
  }
  // 그 도면 하나가 상한보다 커서 그림에 펼치지 못해도 상세는 보인다(찾기로 고른 노드의 무엇·근거·판단은 그림 없이도 쓸 수 있다)
  const drawn = kg.get().expanded.includes(g) || await expand(g);
  if (drawn && !kg.get().graph) await loadGraph();
  await select(id);
  kg.set((s) => (drawn ? { center: id, seq: s.seq + 1, hits: [] }
    : { hits: [], error: null, notice: "이 도면은 노드가 많아 그림에는 펼치지 않았습니다. 오른쪽 상세는 그대로 볼 수 있습니다." }));
  return true;
}

let searchSeq = 0;
export async function search(q) {
  kg.set({ query: q });
  const mine = ++searchSeq;
  const text = (q || "").trim();
  if (!text) { kg.set({ hits: [] }); return []; }
  let r = { hits: [] };
  try { r = await read("kg/search?q=" + encodeURIComponent(text.slice(0, 100))); } catch (e) { r = { hits: [] }; }
  if (mine !== searchSeq) return kg.get().hits;
  kg.set({ hits: r.hits || [] });
  return r.hits;
}

export function fit() { kg.set((s) => ({ center: null, seq: s.seq + 1 })); }
export function dismissError() { kg.set({ error: null }); }

/** 잠재 후보 판단(후보 확인·후보 기각·부재 확정·무관·판단 되돌리기). 판단자는 엔진이 설정의 검토자 이름으로 채운다. */
/** 판단: 사람이 상세에서 본 그 항목의 내용 지문(digest)과 상태를 함께 보낸다. 그사이 도면을 다시 추출해 후보가 바뀌었으면 엔진이 stale로 거절한다. */
export async function judge(id, action, reason, evidence) {
  const d0 = kg.get().detail;
  if (!d0 || d0.id !== id || !d0.expectation) { kg.set({ error: "잠재 후보 상세를 다시 읽은 뒤 판단하세요." }); return null; }
  kg.set({ busy: true, error: null, notice: null });
  try {
    const args = { id, action, ver: d0.ver, digest: d0.expectation.digest, state: d0.expectation.state };
    if (reason) args.reason = reason;
    if (evidence) args.evidence = evidence;
    const r = await cmd("kg.judge", args);
    await refresh();
    const d = kg.get().detail;      // 되돌리면 엔진이 자동 판정을 다시 매기므로 다시 읽은 상태를 알린다
    const shown = d && d.id === id && d.expectation ? d.expectation.state_label : r.state_label;
    kg.set((s) => ({ busy: false, notice: "판단을 저장했습니다. 지금 상태: " + shown, center: id, seq: s.seq + 1 }));
    return r;
  } catch (e) {
    kg.set({ busy: false, error: errorText(e) });
    if (e && e.code === "stale") await refresh();
    return null;
  }
}

/** 도면에서 보기: 그 도면을 열고 패널을 닫은 뒤 구성요소에 맞춰 확대한다(main.js의 답 카드 ID 칩과 같은 길). */
export function showOnSheet(at) {
  if (!at || !at.sheet) return false;
  const cur = store.get().sheet;
  if (at.sheet !== cur) {
    store.set({ sheet: at.sheet, marks: { rid: null, bySheet: {} } });
    cmd("sheet.open", { graph_id: at.sheet }).catch(() => {});
  }
  store.set({ panel: null });
  if (at.local_id) setTimeout(() => store.set((s) => ({ command: { seq: s.command.seq + 1, type: "zoomTo", ids: [at.local_id], pad: 0.15 } })), 0);
  return true;
}

// ---------------------------------------------------------------- 엔진 알림
let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "kg" || topic === "drawings" || topic === "nodes" || topic === "results") refresh(); });
  on("project.changed", () => { reset(); refresh(); });
  refresh();
}

// 채팅이 '패널 열기'를 부르면 엔진이 kg.open 사건을 보낸다. 모듈을 읽은 때부터 듣는다(패널이 닫혀 있어도 연다).
on("kg.open", (d) => {
  store.set({ panel: "kg" });
  wire();
  if (d && d.focus) loadSummary().then(() => focus(d.focus));
});
