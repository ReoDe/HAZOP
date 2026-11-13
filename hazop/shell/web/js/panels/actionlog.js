// AI가 실행한 일의 기록(완료 목록 2 A12, 채팅 규격 §4.7). 읽기만 한다: 엔진(hazop/shell/api_actionlog.py)이 기록 파일을 화면 줄로 바꿔 주고,
// 여기서는 날짜별·최근 순으로 무엇을 누가(채팅 AI) 언제 어떤 대상에 했는지와 결과·사람 확인 여부를 보인다. 대상을 누르면 그 도면·구간·칸으로 간다.
// 질문 원문은 엔진이 보내지 않는다. 모델이 쓴 글(까닭·대상 이름)은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { on, onChanged, read } from "../bridge.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import { applyDisplay } from "../chat/actions.js";
import * as N from "./nodes_state.js";
import * as R from "./results_state.js";

const EMPTY = { rows: [], total: 0, cut: false, bad: 0, counts: {} };
const RANGES = [[1, "오늘"], [8, "지난 7일"], [31, "지난 30일"]];
const RESULT_KIND = { ok: "ok", candidate: "ai", declined: "plain", rejected: "warn", stale: "warn", failed: "err", undone: "plain" };

export const log = createStore({ days: 8, data: EMPTY, error: null, loading: false });
let seq = 0;

function useLog(selector) {
  const [value, setValue] = useState(() => selector(log.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(log.get());
    return log.subscribe(sync);
  }, []);
  return value;
}

/** 프로젝트가 바뀌었을 때 읽어 둔 것을 버린다(areas.js의 resetAreas가 부를 한 줄). */
export function reset() { seq++; log.set({ data: EMPTY, error: null, loading: false }); }

export async function load(days) {
  const d = days || log.get().days;
  const mine = ++seq;
  log.set({ days: d, loading: true });
  try {
    const data = await read("actionlog?days=" + d);
    if (mine === seq) log.set({ data, error: null, loading: false });
  } catch (e) {
    if (mine === seq) log.set({ error: (e && e.message) || "기록을 읽지 못했습니다.", loading: false });
  }
}

let wired = false;
function wire() {
  if (wired) return;
  wired = true;
  const again = () => { if (store.get().panel === "actionlog") load(); };
  on("chat.actions", again);                 // 채팅이 동작을 실행하거나 거절하면 기록이 늘었다
  on("chat.action.result", again);
  onChanged((topic) => { if (topic === "actionlog") again(); });
}

/** 대상으로 가기: 도면은 열고, 구성요소는 그 도면에서 표시·확대, 구간은 구간 패널, 칸은 분석 결과 칸. */
export function go(t, onOpen) {
  if (t.kind === "sheet") { if (onOpen) onOpen(t.sheet); else applyDisplay({ op: "open", ok: true, sheet: t.sheet }); return true; }
  if (t.kind === "component") {
    const mark = { op: "mark", groups: [{ ids: [t.local_id], style: "focus", label: null }], dim_others: true, center: false };
    applyDisplay({ op: "show", ok: true, sheet: t.sheet, ids: [t.local_id], marks: { [t.sheet]: [mark] } }, "actionlog");
    store.set({ panel: null });
    return true;
  }
  if (t.kind === "node") { store.set({ panel: "nodes" }); if (N.nodes.get().focus !== t.node_id) N.focusNode(t.node_id, { zoom: true }); return true; }
  if (t.kind === "cell") { store.set({ panel: "results" }); R.openCell(t.cell[0], t.cell[1]); return true; }
  return false;
}

function Row({ r, onOpen }) {
  const more = r.targets_total - r.targets.length;
  return html`<div class=${"row al-row " + (r.result || "")} role="listitem">
    <span class="al-time">${r.time}</span>
    <div class="al-main">
      <div class="al-head"><b>${r.title}</b><${Chip} kind=${RESULT_KIND[r.result] || "plain"}>${r.result_label}<//>
        <span class="muted small">${r.by} · ${r.class === "confirm" ? (r.confirmed_by ? "확인: " + r.confirmed_by : "사람 확인 상자") : r.class_label}</span>
        ${r.batch_id ? html`<${Chip} kind="id">묶음 ${r.batch_id}<//>` : null}</div>
      ${r.targets.length ? html`<div class="al-targets" aria-label="대상">${r.targets.map((t) => t.kind === "other"
        ? html`<span class="chip" key=${t.id}>${t.label}</span>`
        : html`<button type="button" class="chip al-go" key=${t.id} title="이 대상으로 가기" aria-label=${t.label + "(으)로 가기"} onClick=${() => go(t, onOpen)}>${t.label}</button>`)}
        ${more > 0 ? html`<span class="muted small">외 ${more}개</span>` : null}</div>` : null}
      ${r.why ? html`<div class="muted small al-why">AI가 적은 까닭: ${r.why}</div>` : null}
      ${r.error ? html`<div class="small al-err">${r.error}</div>` : null}</div></div>`;
}

export function ActionLogPanel({ onClose, onOpen }) {
  wire();
  const days = useLog((s) => s.days);
  const data = useLog((s) => s.data);
  const error = useLog((s) => s.error);
  const loading = useLog((s) => s.loading);
  useLayoutEffect(() => { load(); }, []);
  const byDay = [];
  for (const r of data.rows) {
    const last = byDay[byDay.length - 1];
    if (last && last.day === r.day) last.rows.push(r); else byDay.push({ day: r.day, rows: [r] });
  }
  const c = data.counts || {};
  return html`<section class="panel actionlog" aria-label="AI 실행 기록">
    <div class="panel-h"><h2>AI 실행 기록</h2><span class="acts">
      <${Btn} kind="ghost" sm=${true} icon="refresh" label="다시 읽기" onClick=${() => load()} />
      <${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <div class="acts-row" role="group" aria-label="기간">${RANGES.map(([n, label]) => html`<${Btn} key=${n} sm=${true} kind=${n === days ? "primary" : ""}
        label=${label} onClick=${() => load(n)}>${label}<//>`)}
        <span class="muted small">${data.total}건${c.ok ? " · 실행 " + c.ok : ""}${c.rejected ? " · 거절 " + c.rejected : ""}${c.declined ? " · 하지 않음 " + c.declined : ""}${c.failed ? " · 실패 " + c.failed : ""}</span></div>
      <div class="muted small">채팅이 제안해 앱이 실행·거절한 동작만 남습니다. 대화 내용은 저장하지 않고, 도면 보이기·이동 같은 표시는 남기지 않습니다.</div>
      ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}
      ${data.bad ? html`<${Notice} kind="warn" icon="alert-triangle">읽지 못한 기록 줄 ${data.bad}개는 건너뛰었습니다.<//>` : null}
      ${data.cut ? html`<div class="muted small">최근 ${data.rows.length}건만 보입니다.</div>` : null}
      ${!loading && !error && data.rows.length === 0 ? html`<${Notice}>이 기간에 AI가 실행한 일이 없습니다.<//>` : null}
      ${byDay.map((g) => html`<div class="al-day" key=${g.day}><h3>${g.day}</h3>
        <div class="list" role="list" aria-label=${g.day + " 기록"}>${g.rows.map((r) => html`<${Row} key=${r.key} r=${r} onOpen=${onOpen} />`)}</div></div>`)}
    </div></section>`;
}
