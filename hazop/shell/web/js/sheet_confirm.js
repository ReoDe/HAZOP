// 도면 쪽 확정(앱 틀 규격 §10.6·§10.7): 도면 위 칩에 그 쪽의 확정 상태, 누르면 남은 조건과 '원본과 견주기'·'이 쪽 확정'·'확정 취소'. 조건은 엔진(confirmation.sheet_confirmation)이 센
// 값을 그대로 보이고 여기서 다시 세지 않는다. 쓰기는 읽은 지문(ver)과 기록 판(rev)을 실어 명령으로 보낸 뒤 엔진 답으로 다시 그린다. 도면·모델에서 온 글은 텍스트로만 넣는다.
import { html } from "./ui/html.js";
import { useEffect, useLayoutEffect, useState } from "../vendor/hooks.module.js";
import { createStore, store, useStore } from "./store.js";
import { cmd, onChanged, read } from "./bridge.js";
import { Icon } from "./ui/icon.js";
import { Btn, Notice } from "./ui/parts.js";
import { openCompare } from "./compare.js";

export const conf = createStore({ byGraph: {}, open: false, busy: false, error: null });

const REASON = { unknown_symbol: "종류를 못 읽은 기호", open_end: "끊긴 연결(열린 끝)", missing_tag: "태그가 없음", ai_candidate: "AI 후보(수락 전)", unresolved_connector: "이어지지 않은 연결",
  unplaced: "위치 없음", no_position: "위치 없음" };
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

function Conditions({ st }) {
  const byReason = {};
  for (const u of st.unconfirmed || []) byReason[u.reason] = (byReason[u.reason] || 0) + 1;
  const rows = Object.entries(byReason);
  return html`<ul class="tight conf-list" aria-label="남은 조건">
    <li class=${st.unconfirmed_total ? "bad" : "good"}>미확인 ${st.unconfirmed_total}곳${rows.length ? html`<span class="muted small"> — ${rows.map(([k, n]) => (REASON[k] || k) + " " + n).join(" · ")}${st.unconfirmed_total > st.unconfirmed.length ? " …" : ""}</span>` : null}</li>
    <li class=${st.unplaced_total ? "bad" : "good"}>위치 없는 구성요소 ${st.unplaced_total}개${st.unplaced_total ? html`<span class="muted small"> — 위치를 주거나 도면에 없음으로 지워야 합니다</span>` : null}</li>
    <li class=${st.leftovers === null ? "bad" : "good"}>원본에 남은 것 ${st.leftovers === null ? "— 이 읽은 방법은 엔진이 세지 못해 확정할 수 없습니다" : st.leftovers.total + "개(확정을 막지 않습니다)"}</li>
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
    <${Conditions} st=${st} />
    ${st.record_error ? html`<${Notice} kind="err" icon="alert-triangle"><span style="white-space:pre-wrap">확정 기록을 읽을 수 없습니다: ${st.record_error}</span><br />'확정 해제'를 누르면 깨진 기록을 버리고 새 기록을 시작합니다. 견줌·확정은 그 뒤에 다시 합니다.<//>` : null}
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}
    <div class="acts-row">
      ${st.state === "confirmed" ? html`<${Btn} sm=${true} label="확정 취소" disabled=${busy} onClick=${() => unconfirm(gid)}>확정 취소<//>` : html`
        <${Btn} sm=${true} label="견주기 화면 열기" disabled=${busy || conditions > 0 || !!st.compared || !!st.record_error} title=${st.record_error ? "깨진 확정 기록부터 해제하세요" : conditions ? "남은 조건을 먼저 채우세요" : st.compared ? "이미 견줌을 기록했습니다" : "원본과 정리된 보기를 나란히 보고 견줍니다"} onClick=${() => { conf.set({ open: false }); openCompare(gid, st.read_method); }}>견주기 화면 열기<//>
        <${Btn} sm=${true} kind="primary" label="이 쪽 확정" disabled=${busy || !!why} title=${why || "이 쪽 확정"} onClick=${() => confirm(gid)}>이 쪽 확정<//>
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
  return html`<div class="float confbar"><button type="button" class=${"chip " + chip.kind} aria-label=${"쪽 확정: " + chip.label} aria-expanded=${open ? "true" : "false"} title="쪽 확정 조건 보기"
      onClick=${() => { conf.set({ open: !open, error: null }); if (!open) load(gid); }}><${Icon} name=${chip.kind === "ok" ? "circle-check" : chip.kind === "warn" ? "alert-triangle" : "check"} size=${14} /> ${chip.label}</button>
    ${open && st && st.available ? html`<${Card} gid=${gid} st=${st} />` : null}
    ${open && st && !st.available ? html`<div class="float confcard"><${Notice} kind="warn">${st.reason}<//></div>` : null}</div>`;
}
