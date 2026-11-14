// 표제란 패널(완료 목록 2 A3, INTENT §3.1): 도면 자료마다 도면 번호·개정·제목의 확정값과 표제란에서 읽은 후보·근거(읽은 자리)를 보이고,
// 사람이 후보 그대로 또는 고쳐서 확정하거나 확정을 취소한다. 확정 전 값은 후보일 뿐 도면 번호로 쓰이지 않는다.
// 저장은 엔진(hazop/shell/api_titleblock.py → hazop.register.titleblock)만 한다. 이미 추출한 도면은 확정하면 다시 추출하므로 작업으로 돈다.
// 도면에서 읽은 글자(후보·근거)는 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";
import { Btn, Chip, Notice } from "../ui/parts.js";

const EMPTY = { project_id: null, reviewer: null, rows: [], fields: [], totals: { materials: 0, confirmed: 0 } };
const STATE = { unconfirmed: ["warn", "확정 전"], partial: ["warn", "일부 확정"], confirmed: ["ok", "확정"] };
const FORMAT = { drawio: "drawio", pdf: "PDF", dexpi: "DEXPI" };

export const tb = createStore({ data: EMPTY, error: null, notice: null, busy: null, focus: null, drafts: {}, reasons: {}, jobs: {} });
let seq = 0;

function useTb(selector) {
  const [value, setValue] = useState(() => selector(tb.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(tb.get());
    return tb.subscribe(sync);
  }, []);
  return value;
}

/** 프로젝트가 바뀌었을 때 읽어 둔 것과 고치던 값을 버린다(areas.js의 resetAreas가 부를 한 줄). */
export function reset() { seq++; tb.set({ data: EMPTY, error: null, notice: null, busy: null, focus: null, drafts: {}, reasons: {}, jobs: {} }); }

export async function load() {
  const mine = ++seq;
  try {
    const data = await read("titleblock");
    if (mine === seq) tb.set({ data });
  } catch (e) {
    if (mine === seq) tb.set({ error: (e && e.message) || "표제란 자료를 읽지 못했습니다." });
  }
}

/** 도면 목록 행에서 부른다: 그 도면(그래프 ID)의 자료를 펼쳐 둔 채 패널을 연다. */
export function focusSheet(graphId) { tb.set({ focus: { graph_id: graphId } }); store.set({ panel: "titleblock" }); load(); }
/** 채팅·다른 패널에서 자료 ID로 연다. */
export function focusMaterial(materialId) { tb.set({ focus: { material_id: materialId } }); store.set({ panel: "titleblock" }); load(); }

let wired = false;
function wire() {
  if (wired) return;
  wired = true;
  on("job.done", (d) => {
    const mid = tb.get().jobs[d.id];
    if (!mid) return;
    const jobs = Object.assign({}, tb.get().jobs); delete jobs[d.id];
    const r = d.result || {};
    const carried = (r.carried || []).filter((c) => c.edits || c.ai_review).length;
    const parts = ["확정했습니다(등록 버전 " + r.version + ")."];
    if (r.re_extracted) parts.push("도면을 다시 읽었습니다.");
    if (carried) parts.push("사람 수정·AI 후보 기록을 새 버전으로 옮겼습니다.");
    if ((r.released || []).length) parts.push("쪽 확정이 풀렸습니다. 도면을 다시 보고 쪽 확정을 하세요.");
    if ((r.number_conflicts || []).length) parts.push("같은 도면 번호의 다른 형식 원본이 있습니다. 도면 패널에서 그래프에 쓸 쪽을 고르세요.");
    tb.set({ jobs, notice: parts.join(" "), busy: null });
    load();
  });
  on("job.failed", (d) => {
    const mid = tb.get().jobs[d.id];
    if (!mid) return;
    const jobs = Object.assign({}, tb.get().jobs); delete jobs[d.id];
    tb.set({ jobs, error: d.message || "확정하지 못했습니다.", busy: null });
    load();
  });
  onChanged((topic) => { if ((topic === "titleblock" || topic === "drawings") && store.get().panel === "titleblock") load(); });
}

function shown(row, f) {
  const d = (tb.get().drafts[row.material_id] || {})[f.field];
  return d !== undefined ? d : (f.value ?? f.candidate ?? "");
}

function setDraft(mid, field, v) {
  const drafts = Object.assign({}, tb.get().drafts);
  drafts[mid] = Object.assign({}, drafts[mid], { [field]: v });
  tb.set({ drafts });
}

function clearDraft(mid) {
  const drafts = Object.assign({}, tb.get().drafts); delete drafts[mid];
  const reasons = Object.assign({}, tb.get().reasons); delete reasons[mid];
  tb.set({ drafts, reasons });
}

async function send(name, row, args) {
  tb.set({ busy: row.material_id, error: null, notice: null });
  try {
    const out = await cmd(name, Object.assign({ material_id: row.material_id, ver: row.ver }, args));
    clearDraft(row.material_id);
    if (out && out.job) {
      tb.set({ jobs: Object.assign({}, tb.get().jobs, { [out.job]: row.material_id }), notice: "저장하고 도면을 다시 읽는 중입니다…" });
      return;
    }
    tb.set({ busy: null, notice: out && out.changed === false ? "바뀐 값이 없습니다." : "확정했습니다." });
    load();
  } catch (e) {
    tb.set({ busy: null, error: (e && e.message) || "확정하지 못했습니다." });
    if (e && e.code === "stale") load();
  }
}

/** 도면 번호를 바꿀 수 없는 도면(구간·결과 등이 걸렸거나 여러 쪽 자료)인가. 그때는 번호 칸을 잠그고 보내지도 않는다. */
export function numberLocked(row) { return row.review_data.length > 0 || row.multi_page; }

/** 보낼 값 {항목: 값}. asIs면 확정 전 항목의 후보를, 아니면 사람이 입력칸에서 고친 항목만 보낸다(손대지 않은 칸은 보내지 않음).
 * 잠긴 번호 칸은 어느 쪽이든 보내지 않는다(개정·제목만 확정할 수 있게). drafts는 {항목: 입력한 글}. */
export function fieldsToSend(row, drafts, asIs) {
  const fields = {};
  for (const f of row.fields) {
    if (f.field === "drawing_number" && numberLocked(row)) continue;
    const raw = asIs ? (f.value == null ? f.candidate : null) : (drafts || {})[f.field];
    const v = raw == null ? "" : String(raw).trim();
    if (v && v !== f.value) fields[f.field] = v;
  }
  return fields;
}

/** asIs면 확정 전 항목을 후보 그대로, 아니면 고친 항목만 확정한다. */
export function confirmRow(row, asIs) {
  const fields = fieldsToSend(row, tb.get().drafts[row.material_id], asIs);
  if (!Object.keys(fields).length) {
    tb.set({ notice: asIs ? "확정할 후보가 없습니다." : "고친 칸이 없습니다. 후보를 그대로 확정하려면 '후보 그대로 확정'을 누르세요.", error: null });
    return;
  }
  const reason = (tb.get().reasons[row.material_id] || "").trim();
  send("titleblock.confirm", row, reason ? { fields, reason } : { fields });
}

export function cancelField(row, field) { send("titleblock.unconfirm", row, { fields: [field] }); }

/** 앞서 다시 읽기가 실패한 자료: 지금 확정값 그대로 다시 보내면 엔진이 새 버전 없이 다시 읽는다(확정값이 없으면 취소로). */
export function rereadRow(row) {
  const fields = {};
  for (const f of row.fields) if (f.value != null) fields[f.field] = f.value;
  if (Object.keys(fields).length) send("titleblock.confirm", row, { fields });
  else send("titleblock.unconfirm", row, {});
}

/** 엔진의 UTC 시각을 이 PC 시각으로(읽지 못하면 받은 글 그대로). */
function when(at) {
  if (!at) return "";
  const d = new Date(at);
  if (isNaN(d.getTime())) return String(at);
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
}

function Field({ row, f, locked }) {
  const busy = useTb((s) => s.busy) === row.material_id;
  const val = useTb(() => shown(row, f));
  const id = "tb-" + row.material_id + "-" + f.field;
  const lockNumber = f.field === "drawing_number" && locked;
  return html`<div class="tb-field" role="group" aria-label=${f.label}>
    <label class="tb-label" for=${id}>${f.label}</label>
    <div class="tb-now">${f.value != null
      ? html`<b>${f.value}</b><span class="muted small">${f.confirmed_by || "?"} · ${when(f.confirmed_at)}</span>`
      : html`<span class="tb-none">확정 전</span>`}</div>
    <div class="tb-cand">${f.candidate != null
      ? html`<span class="tb-cand-chip" title=${f.evidence ? "읽은 자리: " + f.evidence.text : "표제란 후보"}>후보 <b>${f.candidate}</b></span>
        ${f.evidence ? html`<span class="muted small">${f.evidence.text}</span>` : null}`
      : html`<span class="muted small">후보 없음</span>`}</div>
    <input id=${id} class="tb-input" value=${val} maxlength="200" disabled=${busy || lockNumber}
      aria-label=${f.label + " 확정할 값"} onInput=${(e) => setDraft(row.material_id, f.field, e.target.value)} />
    <span class="tb-acts">${f.value != null ? html`<${Btn} sm=${true} kind="ghost" label=${f.label + " 확정 취소"} disabled=${busy}
      onClick=${() => cancelField(row, f.field)}>확정 취소<//>` : null}</span></div>`;
}

function Row({ row, onOpen, open, noReviewer }) {
  const busy = useTb((s) => s.busy) === row.material_id;
  const reason = useTb((s) => s.reasons[row.material_id] || "");
  const [kind, label] = STATE[row.state] || ["plain", row.state];
  const locked = numberLocked(row);
  const missing = row.fields.some((f) => f.value == null && f.candidate != null);
  return html`<details class=${"tb-row " + row.state} open=${open} key=${row.material_id}>
    <summary class="tb-sum"><b>${row.fields[0].value || row.fields[0].candidate || row.name}</b>
      <span class="muted small tb-name">${row.name}</span>
      <${Chip}>${FORMAT[row.format] || row.format}<//><${Chip} kind=${kind}>${label}<//></summary>
    <div class="tb-body">
      ${row.sheets.length ? html`<div class="acts-row">${row.sheets.map((s) => html`<${Btn} key=${s.name} sm=${true} icon="files"
        label=${"도면 보기 " + (s.graph_id || s.name)} disabled=${!s.graph_id} onClick=${() => onOpen && onOpen(s.graph_id)}>도면 보기${row.sheets.length > 1 ? " " + (s.page + 1) + "쪽" : ""}<//>`)}</div>`
        : html`<div class="muted small">아직 추출하지 않았습니다. 확정해 두면 추출할 때 이 값을 씁니다.</div>`}
      ${row.needs_reextract ? html`<${Notice} kind="warn" icon="refresh">확정은 저장했지만 도면을 다시 읽지 못했습니다. 지금 보이는 도면은 앞 값으로 읽은 것입니다.
        <${Btn} sm=${true} label="도면 다시 읽기" disabled=${busy || noReviewer} onClick=${() => rereadRow(row)}>다시 읽기<//><//>` : null}
      ${row.multi_page ? html`<${Notice} kind="warn" icon="alert-triangle">여러 쪽 자료(${row.pages}쪽)는 쪽마다 도면 번호가 달라 자료 하나에 번호를 확정하지 않습니다.<//>` : null}
      ${row.review_data.length ? html`<${Notice} kind="warn" icon="lock">이 도면의 구성요소를 ${row.review_data.join("·")}이 가리키고 있어 도면 번호를 바꾸면 끊깁니다. 번호는 바꿀 수 없고 개정·제목은 확정할 수 있습니다.<//>` : null}
      <div class="tb-grid">${row.fields.map((f) => html`<${Field} key=${f.field} row=${row} f=${f} locked=${locked} />`)}</div>
      <div class="tb-foot">
        <input class="tb-reason" placeholder="까닭(선택, 기록에 남음)" maxlength="300" value=${reason} aria-label="확정 까닭"
          onInput=${(e) => tb.set({ reasons: Object.assign({}, tb.get().reasons, { [row.material_id]: e.target.value }) })} />
        ${missing ? html`<${Btn} sm=${true} label="확정 전 항목을 후보 그대로 확정" disabled=${busy || noReviewer} onClick=${() => confirmRow(row, true)}>후보 그대로 확정<//>` : null}
        <${Btn} sm=${true} kind="primary" label="입력한 값으로 확정" disabled=${busy || noReviewer} onClick=${() => confirmRow(row, false)}>확정<//></div>
    </div></details>`;
}

export function TitleblockPanel({ onClose, onOpen }) {
  wire();
  const data = useTb((s) => s.data);
  const error = useTb((s) => s.error);
  const notice = useTb((s) => s.notice);
  const focus = useTb((s) => s.focus);
  useLayoutEffect(() => { load(); }, []);
  const isOpen = (r) => !!focus && (focus.material_id === r.material_id || r.sheets.some((s) => s.graph_id === focus.graph_id));
  const noReviewer = !data.reviewer;
  return html`<section class="panel wide titleblock" aria-label="표제란 확정">
    <div class="panel-h"><h2>표제란 확정</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <div class="muted small">표제란에서 읽은 값은 후보입니다. 사람이 확정한 값만 도면 번호·개정·제목으로 쓰고, 확정 전 도면은 쪽 확정과 DEXPI 내보내기를 할 수 없습니다.
        이미 읽은 도면은 확정하면 다시 읽고, 사람 수정과 AI 후보 기록은 그대로 옮겨 갑니다.</div>
      <div class="acts-row"><${Chip} kind="ok">확정 ${data.totals.confirmed}<//><${Chip}>자료 ${data.totals.materials}<//></div>
      ${noReviewer ? html`<${Notice} kind="warn" icon="pencil">설정에서 검토자 이름을 먼저 입력하세요. 누가 확정했는지 기록에 남습니다.<//>` : null}
      ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${() => tb.set({ error: null })}>닫기<//><//>` : null}
      ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice}<//>` : null}
      ${data.rows.length === 0 ? html`<${Notice}>등록된 도면이 없습니다. 도면 패널에서 도면 파일을 먼저 넣으세요.<//>`
        : html`<div class="tb-list">${data.rows.map((r) => html`<${Row} key=${r.material_id} row=${r} onOpen=${onOpen}
            open=${isOpen(r) || (!focus && r.state !== "confirmed")} noReviewer=${noReviewer} />`)}</div>`}
    </div></section>`;
}
