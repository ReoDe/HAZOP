// 도면 쪽 확정(앱 틀 규격 §10.6·§10.7): 도면 위 칩에 그 쪽의 확정 상태, 누르면 남은 조건과 '원본과 견주기'·'이 쪽 확정'·'확정 취소'. 조건은 엔진(confirmation.sheet_confirmation)이 센
// 값을 그대로 보이고 여기서 다시 세지 않는다. 쓰기는 읽은 지문(ver)과 기록 판(rev)을 실어 명령으로 보낸 뒤 엔진 답으로 다시 그린다. 도면·모델에서 온 글은 텍스트로만 넣는다.
import { html } from "./ui/html.js";
import { useEffect, useLayoutEffect, useState } from "../vendor/hooks.module.js";
import { createStore, store, useStore } from "./store.js";
import { cmd, onChanged, read } from "./bridge.js";
import { Icon } from "./ui/icon.js";
import { Btn, Notice } from "./ui/parts.js";
import { openCompare } from "./compare.js";
import { ReviewChip } from "./review/review.js";      // 도면별 AI 검토 칩(칩 줄 맨 앞, HZ-DSN-06 §3.7)
import { fixFor } from "./fix_actions.js";

export const conf = createStore({ byGraph: {}, open: false, busy: false, error: null });

const REASON = { unknown_symbol: "종류를 못 읽은 기호", open_end: "끊긴 연결(열린 끝)", missing_tag: "태그가 없음", ai_candidate: "AI 후보(수락 전)", unresolved_connector: "이어지지 않은 연결",
  unplaced: "위치 없음", no_position: "위치 없음",
  // 추출의 미확인 갈래(hazop/extract). 영문 내부 이름이 화면에 나오지 않게 모두 적고, 표에 없는 것은 '그 밖에 확인할 곳'으로 쓴다(실제 창 확인 2026-11-23)
  registration_unknown: "표제란 확인 전", missing_drawing_number: "도면 번호 없음", not_registered: "등록하지 않은 도면", missing_kind: "종류 없음",
  unclassified_kind: "종류를 못 읽은 기호", unclassified_element: "못 읽은 요소", ambiguous_symbol: "기호가 둘 이상으로 보임", ambiguous_port: "이을 자리가 둘 이상",
  missing_port: "이을 자리 없음", missing_geometry: "모양 정보 없음", approximate_geometry: "모양이 어림값", missing_line_type: "선 종류 없음",
  unknown_line_type: "선 종류를 모름", unknown_flow_direction: "흐름 방향을 모름", invalid_flow_direction: "흐름 방향이 맞지 않음",
  node_direction_basis_unresolved: "흐름 방향 근거를 못 찾음", unconnected_endpoint: "끊긴 연결(열린 끝)", endpoint_not_node: "기호에 닿지 않은 끝",
  self_loop: "제자리로 돌아오는 선", dashed_path_no_visible_piece: "점선 조각이 안 보임", position_conflict: "위치 값이 서로 다름",
  position_kind_mismatch: "종류에 맞지 않는 위치 값", actuated_valve_pending: "구동 밸브 종류 확인 전" };
const reasonText = (k) => REASON[k] || "그 밖에 확인할 곳";
const METHOD = { drawio: "읽은 도면 · drawio", dexpi: "변환 도면 · DEXPI", pdf_vector: "PDF에서 읽어 다시 그림", raster: "그림 파일에서 읽음", unknown: "읽은 방법 모름" };

export function useConf(selector) {
  const [value, setValue] = useState(() => selector(conf.get()));
  // 그린 직후 곧바로 구독한다(useEffect는 그림 뒤로 미뤄져 그 사이의 바뀜을 놓칠 수 있다)
  useLayoutEffect(() => { const sync = (s) => { const n = selector(s); setValue((p) => (Object.is(p, n) ? p : n)); }; sync(conf.get()); return conf.subscribe(sync); }, []);
  return value;
}

let seq = 0;
export async function load(gid) {
  if (!gid) return null;
  const mine = ++seq;
  let st = null;
  try { st = await read("sheetconf/" + encodeURIComponent(gid)); } catch (e) { st = { available: false, reason: "쪽 확정 상태를 읽지 못했습니다." }; }
  if (mine !== seq && store.get().sheet !== gid) return null;
  conf.set((s) => ({ byGraph: Object.assign({}, s.byGraph, { [gid]: st }) }));
  return st;
}

export function reset() { seq++; conf.set({ byGraph: {}, open: false, busy: false, error: null }); }

async function run(command, gid, extra) {
  const st = conf.get().byGraph[gid];
  conf.set({ busy: true, error: null });
  try {
    const r = await cmd("sheet." + command, Object.assign({ graph_id: gid, ver: st.ver, rev: st.rev }, extra || {}));
    conf.set((s) => ({ busy: false, byGraph: Object.assign({}, s.byGraph, { [gid]: r.status }) }));
    return r;
  } catch (e) {
    conf.set({ busy: false, error: (e && e.message) || "처리하지 못했습니다." });
    if (e && e.code === "stale") await load(gid);
    return null;
  }
}

export const compare = (gid, mode) => run("compare", gid, { mode });
export const confirm = (gid) => run("confirm", gid);

/** 견줌 기록과 확정을 한 흐름으로(U8: 쪽 확정 8 → 3클릭). 지금 있는 명령 sheet.compare → sheet.confirm을 차례로 부른다(견줌을 건너뛰는 길은 없다).
 *  견줌만 되고 확정이 막히면(조건이 그새 바뀜) 견줌 기록은 남고 까닭을 돌려준다. → {ok, step: "compare"|"confirm", error}. */
export async function compareAndConfirm(gid, mode) {
  const c = await run("compare", gid, { mode });
  if (!c) return { ok: false, step: "compare", error: conf.get().error };
  const st = conf.get().byGraph[gid];
  if (st && st.state === "confirmed") return { ok: true, step: "confirm" };
  const r = await run("confirm", gid);
  return r ? { ok: true, step: "confirm" } : { ok: false, step: "confirm", error: conf.get().error };
}

/** 이 쪽의 다음 할 일 열기(다음에 할 일 '쪽 확정' 단추): 조건이 다 찼고 아직 안 견줬으면 견주기 화면을 바로, 아니면 조건 카드. */
export async function openNext(gid) {
  const st = await load(gid);
  const left = st && st.available ? (st.unconfirmed_total || 0) + (st.unplaced_total || 0) + (st.leftovers === null ? 1 : 0) : 1;
  if (st && st.available && !left && !st.compared && !st.record_error && st.state !== "confirmed") { conf.set({ open: false }); openCompare(gid, st.read_method); return "compare"; }
  conf.set({ open: true, error: null });
  return "card";
}
export const unconfirm = (gid) => run("unconfirm", gid, {});

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "sheetconf" || topic === "drawings") { const g = store.get().sheet; if (g) load(g); } });
  store.subscribe((s) => { if (s.sheet && !conf.get().byGraph[s.sheet]) load(s.sheet); });
}

/** 칩에 쓸 글과 모양: {label, kind, left}. 남은 조건 수는 엔진이 준 값(미확인·위치 없음·원본에 남은 것을 세지 못함)에서만 읽는다. */
export function chipOf(st) {
  if (!st) return { label: "쪽 확정 확인 중", kind: "plain", left: 0 };
  if (!st.available) return { label: "쪽 확정 상태 없음", kind: "plain", left: 0 };
  if (st.record_error) return { label: "확정 기록 깨짐", kind: "warn", left: 1 };
  if (st.state === "confirmed") return { label: "쪽 확정됨", kind: "ok", left: 0 };
  const left = (st.unconfirmed_total || 0) + (st.unplaced_total || 0) + (st.leftovers === null ? 1 : 0);
  if (st.state === "ready" || (!left && st.state !== "confirmed")) return { label: st.compared ? "확정만 남음" : "원본과 견줌 남음", kind: "accent", left: 0 };
  return { label: "확정 조건 " + left + "개 남음", kind: "warn", left };
}

/** 남은 미확인 갈래마다 그것을 푸는 단추(표제란 확정·AI 후보 검토하기·도면 고치기). 같은 단추는 한 번만(HZ-DSN-06 §3.1, U8). */
export function fixesOf(st) {
  const seen = new Set(), out = [];
  for (const u of st.unconfirmed || []) {
    const f = fixFor(u.reason);
    if (f && !seen.has(f.label)) { seen.add(f.label); out.push(f); }
  }
  return out;
}

function Conditions({ st, gid }) {
  const byReason = {};
  for (const u of st.unconfirmed || []) byReason[u.reason] = (byReason[u.reason] || 0) + 1;
  const rows = Object.entries(byReason);
  const fixes = fixesOf(st);
  return html`<ul class="tight conf-list" aria-label="남은 조건">
    <li class=${st.unconfirmed_total ? "bad" : "good"}>미확인 ${st.unconfirmed_total}곳${rows.length ? html`<span class="muted small"> — ${rows.map(([k, n]) => reasonText(k) + " " + n).join(" · ")}${st.unconfirmed_total > st.unconfirmed.length ? " …" : ""}</span>` : null}
      ${fixes.length ? html`<div class="acts-row">${fixes.map((f) => html`<${Btn} sm=${true} key=${f.label} label=${f.label} onClick=${() => { conf.set({ open: false }); f.run(gid); }}>${f.label}<//>`)}</div>` : null}</li>
    <li class=${st.unplaced_total ? "bad" : "good"}>위치 없는 구성요소 ${st.unplaced_total}개${st.unplaced_total ? html`<span class="muted small"> — 위치를 주거나 도면에 없음으로 지워야 합니다</span>` : null}</li>
    <li class=${st.leftovers === null ? "bad" : "good"}>원본에 남은 것 ${st.leftovers === null ? "— 이 방법으로 읽은 도면은 원본에 남은 것을 셀 수 없어 확정할 수 없습니다" : st.leftovers.total + "개(확정을 막지 않습니다)"}</li>
    <li class=${st.compared ? "good" : "todo"}>원본과 견줌 ${st.compared ? st.compared.by + " · 기록됨" : "— 아직"}</li></ul>`;
}

function Card({ gid, st }) {
  const busy = useConf((s) => s.busy);
  const error = useConf((s) => s.error);
  const conditions = (st.unconfirmed_total || 0) + (st.unplaced_total || 0) + (st.leftovers === null ? 1 : 0);
  const why = st.state === "confirmed" ? null : st.record_error ? "확정 기록이 깨져 있습니다. 먼저 '확정 해제'로 새 기록을 시작하세요." : conditions ? "남은 조건을 모두 채워야 합니다." : (!st.compared ? "견주기 화면에서 원본과 견준 뒤에 확정할 수 있습니다." : null);
  return html`<div class="float confcard" role="dialog" aria-label="쪽 확정">
    <div class="nd-h"><b>쪽 확정</b><span class="muted small">${METHOD[st.read_method] || st.read_method}</span>
      <span class="acts"><${Btn} sm=${true} kind="ghost" icon="x" label="쪽 확정 닫기" onClick=${() => conf.set({ open: false })} /></span></div>
    ${st.state === "confirmed" ? html`<${Notice} kind="info" icon="circle-check">${st.confirmed.by}가 확정했습니다. 도면 자료가 바뀌면 확정이 풀립니다.<//>` : null}
    ${(st.released || []).length ? html`<${Notice} kind="warn" icon="alert-triangle">도면 자료가 바뀌어 이전 견줌·확정이 풀렸습니다.<//>` : null}
    <${Conditions} st=${st} gid=${gid} />
    ${st.record_error ? html`<${Notice} kind="err" icon="alert-triangle"><span style="white-space:pre-wrap">확정 기록을 읽을 수 없습니다: ${st.record_error}</span><br />'확정 해제'를 누르면 깨진 기록을 버리고 새 기록을 시작합니다. 견줌·확정은 그 뒤에 다시 합니다.<//>` : null}
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}
    <div class="acts-row">
      ${st.state === "confirmed" ? html`<${Btn} sm=${true} label="확정 취소" disabled=${busy} onClick=${() => unconfirm(gid)}>확정 취소<//>` : html`
        ${!st.compared ? html`<${Btn} sm=${true} kind="primary" label="원본과 견주고 확정" disabled=${busy || conditions > 0 || !!st.record_error} title=${st.record_error ? "깨진 확정 기록부터 해제하세요" : conditions ? "남은 조건을 먼저 채우세요" : "원본과 정리된 보기를 나란히 보고 견준 뒤 그 자리에서 확정합니다"} onClick=${() => { conf.set({ open: false }); openCompare(gid, st.read_method); }}>원본과 견주고 확정<//>`
          : html`<${Btn} sm=${true} kind="primary" label="이 쪽 확정" disabled=${busy || !!why} title=${why || "이 쪽 확정"} onClick=${async () => { if (await confirm(gid)) conf.set({ open: false }); }}>이 쪽 확정<//>`}
        ${st.compared || st.record_error ? html`<${Btn} sm=${true} kind="ghost" label=${st.record_error ? "확정 해제" : "견줌 취소"} disabled=${busy} onClick=${() => unconfirm(gid)}>${st.record_error ? "확정 해제" : "견줌 취소"}<//>` : null}`}</div>
    ${why && st.state !== "confirmed" ? html`<div class="muted small" role="status">${why}</div>` : null}</div>`;
}

export function SheetConfirm() {
  wire();
  const gid = useStore((s) => s.sheet);
  const byGraph = useConf((s) => s.byGraph);
  const open = useConf((s) => s.open);
  useEffect(() => { if (gid && !conf.get().byGraph[gid]) load(gid); }, [gid]);      // 도면을 열 때 그 쪽의 상태를 읽는다
  if (!gid) return null;
  const st = byGraph[gid];
  const chip = chipOf(st);
  return html`<div class="float confbar"><${ReviewChip} gid=${gid} /><button type="button" class=${"chip " + chip.kind} aria-label=${"쪽 확정: " + chip.label} aria-expanded=${open ? "true" : "false"} title="쪽 확정 조건 보기"
      onClick=${() => { conf.set({ open: !open, error: null }); if (!open) load(gid); }}><${Icon} name=${chip.kind === "ok" ? "circle-check" : chip.kind === "warn" ? "alert-triangle" : "check"} size=${14} /> ${chip.label}</button>
    ${open && st && st.available ? html`<${Card} gid=${gid} st=${st} />` : null}
    ${open && st && !st.available ? html`<div class="float confcard"><${Notice} kind="warn">${st.reason}<//></div>` : null}</div>`;
}
