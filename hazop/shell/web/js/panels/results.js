// 분석 결과 패널(규격 §2.1·§2.3 ⑤, 시안 4번): 구간×편차 행렬(가상 스크롤), 고른 칸의 워크시트와 행 동작 막대(수용·수정·기각·보류 + 사유),
// 분석 실행·멈춤·한도 표시, 내보내기(Excel·초기사건 인계 묶음), 권고 목록과 추적(INTENT §3.6). 저장하는 자료는 엔진만 쓰고 여기서는 보여 주고 명령만 보낸다.
// 모델·도면에서 온 글(원인·결과·권고·이름)은 ${}로만 넣는다(HTML로 해석되지 않는다).
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { store } from "../store.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import { VirtualGrid } from "../ui/table.js";
import * as R from "./results_state.js";

const STATUS = { proposed: ["AI 초안", "ai"], approved: ["수용", "ok"], revised: ["수정", "accent"], rejected: ["기각", "plain"], on_hold: ["보류", "warn"] };
const RISK_CLASS = (r) => (r == null ? "" : "risk-" + Math.min(5, Math.max(1, r)));
// 항목이 없는 칸의 종류: [표시, 모양, 설명]. 엔진(api_results.cell_kind)이 kind·reason을 준다. 없으면 '아직 분석 안 함'.
const KIND = {
  not_applicable: ["적용 불가", "na", "AI가 이 구간에는 해당하지 않는다고 판단한 칸"],
  no_scenario: ["0건", "ns", "분석했으나 시나리오가 나오지 않은 칸"],
  failed: ["실패", "fail", "마지막 AI 실행이 실패한 칸"],
  excluded: ["제외", "ex", "제외한 칸"],
};
const NOT_YET = "아직 분석 안 함";
const withEn = (ko, en) => (en && en !== ko ? ko + " (" + en + ")" : ko);

// ---------------------------------------------------------------- 머리
function Kpi({ kpi }) {
  if (!kpi) return null;
  return html`<div class="acts-row kpi">
    <${Chip}>분석 ${kpi.analyzed}/${kpi.cells}칸<//>
    <${Chip}>항목 ${kpi.entries}<//>
    <${Chip} kind=${kpi.unreviewed ? "warn" : ""} title="검토하지 않은 항목(AI 초안·보류)">미검토 ${kpi.unreviewed}<//>
    ${kpi.on_hold ? html`<${Chip} kind="warn">보류 ${kpi.on_hold}<//>` : null}
    <${Chip}>수용 ${kpi.approved}<//>
    ${kpi.failed_cells ? html`<${Chip} kind="warn" title="마지막 AI 실행이 실패한 칸">실패 ${kpi.failed_cells}<//>` : null}</div>`;
}

function RunState({ run }) {
  if (!run) return null;
  if (run.running) {
    return html`<${Notice} kind="info" icon="loader-2"><b>AI 분석 중</b> ${run.text} · ${run.done}/${run.total}
      ${run.stopping ? html` · 멈추는 중(진행 중인 호출은 끝까지 받습니다)` : html` <${Btn} sm=${true} label="분석 멈추기" onClick=${R.stopRun}>멈추기<//>`}<//>`;
  }
  const l = run.last;
  if (!l) return null;
  if (l.reason === "halted") {
    const reset = l.limit && l.limit.resets_at ? " 한도는 " + String(l.limit.resets_at).replace("T", " ").replace(/:\d\dZ?$/, "") + "에 풀립니다." : "";
    return html`<${Notice} kind="warn" icon="alert-triangle">AI 분석이 ${l.calls}번째 호출에서 멈췄습니다(${l.error || l.error_kind}).${reset} 받은 칸은 저장했습니다. 한도가 풀리면 '실패 칸 다시 실행'으로 이어 가세요.<//>`;
  }
  return html`<${Notice} kind=${l.reason === "stopped" ? "info" : "ok"} icon="circle-check">AI 분석${l.reason === "stopped" ? "을 멈췄습니다" : "이 끝났습니다"}: 호출 ${l.calls}회, ${l.cells}칸 반영${l.failed_calls ? ", 실패 " + l.failed_calls + "회" : ""}.<//>`;
}

function PlanCard() {
  const p = R.useResults((s) => s.plan);
  if (!p) return null;
  return html`<div class="card runplan" role="dialog" aria-label="분석 실행 확인">
    <h3>AI 분석 실행</h3>
    ${p.empty_text ? html`<p>${p.empty_text}</p>` : html`<p>${p.cells}칸을 ${p.calls}번 호출해 분석합니다(약 ${Math.max(1, Math.round(p.seconds / 60))}분). Claude 구독 한도를 씁니다.</p>
      <div class="muted small">사람이 쓴 항목은 바꾸지 않고, 잠긴 구간과 적용됨 구간은 건너뜁니다. 연결: ${p.state || "확인 안 함"}</div>`}
    ${!p.can_start && !p.empty_text ? html`<${Notice} kind="warn" icon="alert-triangle">${p.guide || "AI 연결을 쓸 수 없습니다."}<//>` : null}
    ${p.needs_terms && p.can_start ? html`<${Notice} kind="info">처음 실행입니다. 구독 사용 안내를 확인한 것으로 기록합니다.<//>` : null}
    <div class="acts-row"><${Btn} kind="primary" label="분석 시작" disabled=${!p.can_start || !!p.empty_text || p.running} onClick=${R.startRun}>시작<//><${Btn} label="취소" onClick=${R.closePlan}>취소<//></div></div>`;
}

// Excel 범위: 전체 / 승인 항목만 / 고른 구간만. 저장 위치는 창이 파일 대화상자로 묻고(웹은 경로를 보내지 않는다), 같은 이름이 있으면 덮어쓸지 한 번 더 묻는다.
const SCOPE_TEXT = { all: "전체", approved: "승인 항목만", nodes: "고른 구간만" };
function ExportCard({ s, onDone }) {
  const active = R.useResults((x) => x.active);
  const exporting = R.useResults((x) => x.exporting);
  const [scope, setScope] = useState("all");
  // 구간마다 내보낼 내용이 있는 칸 수(항목이 있거나 적용 불가·실패 같은 표시가 있는 칸). 분석 전 구간은 0이라 파일에 행이 없다.
  const filled = (id) => Object.values((s.matrix || {})[id] || {}).filter((c) => c.scenarios || c.kind).length;
  const [picked, setPicked] = useState(() => (active && filled(active.node_id) ? [active.node_id] : []));
  const toggle = (id) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : picked.concat([id]));
  const ok = scope !== "nodes" || picked.length > 0;
  const empty = scope === "nodes" && picked.length > 0 && picked.every((id) => !filled(id));
  const go = async () => { const r = await R.exportExcel(scope, scope === "nodes" ? picked : null); if (r && !r.cancelled) onDone(); };
  const hint = { all: "모든 항목과 칸 표시 행(적용 불가·실패·제외)을 담습니다.",
    approved: "수용한 항목 " + (s.kpi ? s.kpi.approved : 0) + "개만 담습니다. 칸 표시 행은 넣지 않습니다.",
    nodes: "고른 구간의 항목과 칸 표시 행을 담습니다." };
  return html`<div class="card exportcard" role="dialog" aria-label="Excel 내보내기 범위">
    <h3>Excel로 내보내기</h3>
    <div class="exp-scopes" role="radiogroup" aria-label="범위">${Object.keys(SCOPE_TEXT).map((k) => html`<label key=${k} class="exp-opt">
      <input type="radio" name="exp-scope" checked=${scope === k} onChange=${() => setScope(k)} /> <b>${SCOPE_TEXT[k]}</b></label>`)}</div>
    <div class="muted small">${hint[scope]}</div>
    ${scope === "nodes" ? html`<div class="exp-nodes" role="group" aria-label="구간 고르기">${s.nodes.map((n) => html`<label key=${n.node_id} class="exp-opt">
      <input type="checkbox" checked=${picked.includes(n.node_id)} onChange=${() => toggle(n.node_id)} /> <b>${n.node_id}</b> ${n.name || ""} <span class="muted small">${filled(n.node_id) ? "· " + filled(n.node_id) + "칸" : "· 분석 전"}</span></label>`)}</div>
      ${empty ? html`<div class="small reason">고른 구간은 아직 분석 전이라 파일에 행이 없습니다.</div>` : null}
      ${picked.length ? html`<div class="muted small">${picked.length}개 구간을 담습니다.</div>` : html`<div class="small reason">구간을 하나 이상 고르세요.</div>`}` : null}
    <div class="muted small">저장 위치는 파일 대화상자에서 고릅니다. 같은 이름의 파일이 있으면 덮어쓸지 한 번 더 묻습니다.</div>
    <div class="acts-row"><${Btn} kind="primary" label="Excel로 내보내기" disabled=${!ok || exporting} onClick=${go}>내보내기<//>
      <${Btn} label="취소" onClick=${onDone}>취소<//></div></div>`;
}

function Header({ s }) {
  const [menu, setMenu] = useState(false);
  const [exp, setExp] = useState(false);
  const exporting = R.useResults((x) => x.exporting);
  const view = R.useResults((x) => x.view);
  return html`<div class="acts-row res-head">
    <${Kpi} kpi=${s.kpi} />
    <span class="acts">
      <${Btn} sm=${true} label=${view === "recs" ? "행렬 보기" : "권고 " + (s.kpi ? s.kpi.recs : 0) + " 보기"}
        onClick=${() => R.setView(view === "recs" ? "matrix" : "recs")}>${view === "recs" ? "행렬" : "권고 " + (s.kpi ? s.kpi.recs : 0)}<//>
      <${Btn} sm=${true} icon="cpu" label="분석 실행" disabled=${!!(s.run && s.run.running)} onClick=${() => setMenu(!menu)}>분석 실행<//>
      <${Btn} sm=${true} icon="file-export" label="Excel 내보내기 범위 고르기" disabled=${exporting} onClick=${() => setExp(!exp)}>Excel<//>
      <${Btn} sm=${true} icon="file-export" label="초기사건 인계 묶음 내보내기" disabled=${exporting} onClick=${R.exportIe}>초기사건 인계<//></span></div>
    ${exp ? html`<${ExportCard} s=${s} onDone=${() => setExp(false)} />` : null}
    ${menu ? html`<div class="acts-row runmenu" role="menu">
      <${Btn} sm=${true} label="모든 구간 분석" onClick=${() => { setMenu(false); R.planRun("all"); }}>모든 구간<//>
      <${Btn} sm=${true} label="고른 구간 분석" onClick=${() => { setMenu(false); R.planRun("node"); }}>고른 구간<//>
      <${Btn} sm=${true} label="고른 칸 분석" onClick=${() => { setMenu(false); R.planRun("cell"); }}>고른 칸<//>
      <${Btn} sm=${true} label="실패 칸 다시 실행" onClick=${() => { setMenu(false); R.planRun("failed"); }}>실패 칸 다시<//></div>` : null}`;
}

// ---------------------------------------------------------------- 행렬
function Legend() {
  return html`<div class="res-legend muted small" aria-label="행렬 표시 설명">
    <span><span class="faint">·</span> ${NOT_YET}</span>
    ${Object.keys(KIND).map((k) => html`<span key=${k}><span class=${"rk rk-" + KIND[k][1]}>${KIND[k][0]}</span> ${KIND[k][2]}</span>`)}
    <span>칸에 올리면 이유가 보이고, 눌러 열면 워크시트에 적힙니다.</span></div>`;
}

function Matrix({ s }) {
  const active = R.useResults((x) => x.active);
  const rows = s.nodes, cols = s.deviations;
  const ai = active ? rows.findIndex((n) => n.node_id === active.node_id) : -1;
  const ci = active ? cols.findIndex((d) => d.deviation_id === active.deviation_id) : -1;
  const open = (r, c) => R.openCell(rows[r].node_id, cols[c].deviation_id);
  const h = Math.min(rows.length * 34 + 64 + 4, Math.max(220, Math.round(window.innerHeight * 0.46)));   // 행이 적으면 내용만큼, 많으면 화면의 절반 가까이
  return html`<div class="res-matrix" style=${"height:" + h + "px"}><${VirtualGrid} rows=${rows.length} cols=${cols.length} rowH=${34} colW=${64} headH=${64} headW=${172}
    label=${"구간×편차 행렬 " + rows.length + "행 " + cols.length + "열"}
    active=${ai >= 0 && ci >= 0 ? { r: ai, c: ci } : null} onActive=${open} onOpen=${open}
    corner=${html`<span class="muted small">구간 \\ 편차</span>`}
    renderRowHead=${(r) => html`<span class="vg-rh-in"><b>${rows[r].node_id}</b> ${rows[r].name || ""}${rows[r].range ? html` <span class="muted small">${rows[r].range}${rows[r].spans ? " ⇄" : ""}</span>` : null}</span>`}
    renderColHead=${(c) => html`<span class="vg-ch-in" title=${withEn(cols[c].label, cols[c].label_en)} aria-label=${withEn(cols[c].label, cols[c].label_en)}>${cols[c].label}</span>`}
    renderCell=${(r, c) => {
      const cell = (s.matrix[rows[r].node_id] || {})[cols[c].deviation_id];
      if (!cell) return null;
      const k = KIND[cell.kind];
      if (k && !cell.scenarios) return html`<span class=${"rk rk-" + k[1]} title=${k[0] + ": " + cell.reason} aria-label=${k[0] + ". " + cell.reason}>${k[0]}</span>`;
      if (!cell.scenarios && cell.state !== "analyzed") return html`<span class="faint" title=${NOT_YET} aria-label=${NOT_YET}>·</span>`;
      return html`<span class=${"rc " + RISK_CLASS(cell.max_risk)}><b>${cell.max_risk == null ? "–" : cell.max_risk}</b><small>${cell.scenarios}</small>${cell.unreviewed ? html`<i class="dot-un" title="미검토"></i>` : null}${k ? html`<i class="dot-fail" title=${k[0] + ": " + cell.reason}></i>` : null}</span>`;
    }} /></div>`;
}

// ---------------------------------------------------------------- 워크시트
const text = (v) => (typeof v === "string" ? v : "");
const guard = (g) => (typeof g === "string" ? g : (g && g.text) || "");

function Verdict({ e }) {
  const [st, label] = STATUS[e.status] || [e.status, ""];
  const v = e.verdict || {};
  return html`<div><${Chip} kind=${label}>${st}<//>${v.by ? html` <span class="muted small">${v.by}</span>` : null}
    ${v.reason ? html`<div class="small reason">${v.reason}</div>` : null}</div>`;
}

function EntryActions({ e, cell }) {
  const [mode, setMode] = useState(null);          // null | "revised" | "rejected" | "on_hold" | "edit"
  const [reason, setReason] = useState("");
  const [f, setF] = useState(null);
  const busy = R.useResults((x) => x.busy);
  const off = !cell.editable;
  const need = (m) => ({ revised: "수정", rejected: "기각", on_hold: "보류" }[m]);
  const startEdit = () => { setF({ cause: text(e.cause), consequence: text(e.consequence), recommendation: text(e.recommendation), severity: e.severity == null ? "" : String(e.severity), frequency: e.frequency == null ? "" : String(e.frequency) }); setMode("edit"); setReason(""); };
  const done = () => { setMode(null); setReason(""); setF(null); };
  async function submit() {
    if (mode === "edit") {
      const fields = { cause: f.cause, consequence: f.consequence, recommendation: f.recommendation, severity: f.severity === "" ? null : Number(f.severity), frequency: f.frequency === "" ? null : Number(f.frequency) };
      if (await R.editEntry(e.entry_id, fields, reason)) done();
    } else if (await R.setStatus(e.entry_id, mode, reason)) done();
  }
  return html`<div class="ent-acts">
    <div class="acts-row">
      <${Btn} sm=${true} kind=${e.status === "approved" ? "primary" : ""} label="수용" disabled=${off || busy} title=${off ? cell.not_editable_reason : "수용 (A)"} onClick=${() => R.setStatus(e.entry_id, "approved", "")}>수용<//>
      <${Btn} sm=${true} label="수정" disabled=${off || busy} onClick=${startEdit}>수정<//>
      <${Btn} sm=${true} label="기각" disabled=${off || busy} onClick=${() => { setMode("rejected"); setReason(""); }}>기각<//>
      <${Btn} sm=${true} label="보류" disabled=${off || busy} onClick=${() => { setMode("on_hold"); setReason(""); }}>보류<//></div>
    ${mode ? html`<div class="field">
      ${mode === "edit" ? html`<div class="editgrid">
        <label>원인<textarea class="textbox" rows="2" value=${f.cause} onInput=${(x) => setF(Object.assign({}, f, { cause: x.target.value }))}></textarea></label>
        <label>결과<textarea class="textbox" rows="2" value=${f.consequence} onInput=${(x) => setF(Object.assign({}, f, { consequence: x.target.value }))}></textarea></label>
        <label>권고<textarea class="textbox" rows="2" value=${f.recommendation} onInput=${(x) => setF(Object.assign({}, f, { recommendation: x.target.value }))}></textarea></label>
        <label>강도<select class="textbox" value=${f.severity} onChange=${(x) => setF(Object.assign({}, f, { severity: x.target.value }))}><option value="">미정</option>${cell.severities.map((v) => html`<option value=${String(v)}>${v}</option>`)}</select></label>
        <label>빈도<select class="textbox" value=${f.frequency} onChange=${(x) => setF(Object.assign({}, f, { frequency: x.target.value }))}><option value="">미정</option>${cell.frequencies.map((v) => html`<option value=${String(v)}>${v}</option>`)}</select></label></div>` : null}
      <label for=${"why-" + e.entry_id}>${mode === "edit" ? "수정" : need(mode)} 사유(필수)</label>
      <input id=${"why-" + e.entry_id} class="textbox" maxlength="1000" value=${reason} onInput=${(x) => setReason(x.target.value)}
        onKeyDown=${(x) => { if (x.key === "Enter") { x.preventDefault(); if (reason.trim()) submit(); } else if (x.key === "Escape") { x.stopPropagation(); done(); } }} />
      <div class="acts-row"><${Btn} sm=${true} kind="primary" label="저장" disabled=${busy || !reason.trim()} onClick=${submit}>저장<//><${Btn} sm=${true} label="취소" onClick=${done}>취소<//></div></div>` : null}</div>`;
}

function Worksheet() {
  const c = R.useResults((x) => x.cell);
  const active = R.useResults((x) => x.active);
  const mk = R.useResults((x) => (x.summary && x.cell ? ((x.summary.matrix || {})[x.cell.node.node_id] || {})[x.cell.deviation.deviation_id] : null));
  if (!active) return html`<div class="muted res-hint">행렬에서 칸을 고르면 그 칸의 워크시트가 열립니다.</div>`;
  if (!c) return html`<div class="muted res-hint">불러오는 중…</div>`;
  const cell = c.cell;
  return html`<div class="card worksheet" aria-label=${"워크시트 " + c.node.node_id + " " + (c.deviation.label || "")}>
    <div class="nd-h"><b>${c.node.node_id}</b> ${c.node.name || ""} <span class="muted">›</span> <b>${c.deviation.label || c.deviation.deviation_id}</b>${c.deviation.label_en ? html` <span class="muted en">${c.deviation.label_en}</span>` : null}
      <${Chip}>${cell.state === "analyzed" ? "분석함" : cell.state === "excluded" ? "제외" : "분석 전"}<//>
      ${cell.scope_changed ? html`<${Chip} kind="warn" title="구간 범위가 바뀐 뒤 아직 다시 확인하지 않은 칸">범위 바뀜<//>` : null}
      <span class="acts"><${Btn} sm=${true} label="도면에서 보기" title="패널을 닫고 이 구간을 도면에서 봅니다" onClick=${() => R.viewOnSheet(c.node.node_id)}>도면에서 보기<//>
        <${Btn} sm=${true} kind="ghost" icon="x" label="워크시트 닫기" onClick=${() => R.results.set({ active: null, cell: null })} /></span></div>
    ${!c.editable ? html`<${Notice} kind="info">${c.not_editable_reason || "이 칸은 고칠 수 없습니다."}<//>` : null}
    ${cell.ai_run && cell.ai_run.status === "failed" ? html`<${Notice} kind="warn" icon="alert-triangle">마지막 AI 실행이 이 칸에서 실패했습니다: ${cell.ai_run.error}<//>` : null}
    ${mk && KIND[mk.kind] && !cell.entries.length ? html`<${Notice} kind=${mk.kind === "failed" ? "warn" : "info"}><b>${KIND[mk.kind][0]}</b> · ${mk.reason}<//>`
      : cell.ai_run && cell.ai_run.note ? html`<div class="muted small">${cell.ai_run.note}</div>` : null}
    ${cell.entries.length === 0 ? html`<div class="muted">${mk && KIND[mk.kind] ? "항목이 없습니다." : "항목이 없습니다. '분석 실행'으로 AI 초안을 받으세요."}</div>` : cell.entries.map((e) => html`<div class="ent" key=${e.entry_id}>
      <div class="entgrid">
        <div><div class="lbl">원인</div><div>${text(e.cause) || html`<span class="muted">-</span>`}</div></div>
        <div><div class="lbl">결과</div><div>${text(e.consequence) || html`<span class="muted">-</span>`}</div></div>
        <div><div class="lbl">보호수단</div>${(e.safeguards || []).length ? html`<ul class="tight">${e.safeguards.map((g, i) => html`<li key=${i}>${guard(g)}</li>`)}</ul>` : html`<span class="muted">-</span>`}</div>
        <div><div class="lbl">권고</div><div>${text(e.recommendation) || html`<span class="muted">-</span>`}</div></div>
        <div><div class="lbl">강도·빈도·위험도</div><div>${e.severity == null ? "-" : e.severity} · ${e.frequency == null ? "-" : e.frequency} · <b class=${"rc " + RISK_CLASS(e.risk)}>${e.risk == null ? "-" : e.risk}</b></div></div>
        <div><div class="lbl">판정</div><${Verdict} e=${e} /></div></div>
      <${EntryActions} e=${e} cell=${c} /></div>`)}
    ${cell.scope_changed ? html`<div class="acts-row"><${Btn} sm=${true} label="범위 바뀜 확인" onClick=${R.recheck}>범위 바뀜을 확인했습니다<//></div>` : null}</div>`;
}

// ---------------------------------------------------------------- 권고·추적
function TraceBox() {
  const [text, setText] = useState("");
  const go = () => { if (text.trim()) R.loadTrace(text); };
  return html`<div class="acts-row tracebox"><label for="trace-q" class="small muted">구성요소 추적</label>
    <input id="trace-q" class="textbox" maxlength="120" placeholder="태그 또는 구성요소 ID" value=${text} onInput=${(e) => setText(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); go(); } }} />
    <${Btn} sm=${true} label="추적" disabled=${!text.trim()} onClick=${go}>추적<//></div>`;
}

function Recs() {
  const recs = R.useResults((x) => x.recs);
  const trace = R.useResults((x) => x.trace);
  return html`<div class="res-recs"><${TraceBox} />
    ${trace ? html`<${Notice} kind="info" icon="route">구성요소 <b>${trace.entity || "?"}</b> → ${trace.nodes.length ? trace.nodes.map((n) => n.node_id + " " + (n.name || "")).join(", ") : (trace.entities && trace.entities.length ? "분석 범위의 소속 구간 없음" : "프로젝트에서 찾지 못함")}
      <${Btn} sm=${true} kind="ghost" label="추적 끄기" onClick=${() => R.results.set({ trace: null })}>추적 끄기<//><//>` : null}
    ${trace && trace.nodes.length ? trace.nodes.map((n) => html`<div class="card" key=${n.node_id}><b>${n.node_id}</b> ${n.name || ""}
      ${n.cells.length ? n.cells.map((c) => html`<div key=${c.deviation_id}><span class="muted">${c.deviation}</span>${c.recs.map((r) => html`<div class="rec" key=${r.entry_id}>
        <button type="button" class="linkish" onClick=${() => R.openCell(r.node_id, r.deviation_id)}>${r.text}</button></div>`)}</div>`) : html`<div class="muted">이 구간에는 아직 권고가 없습니다.</div>`}</div>`) : null}
    <div class="list" role="list" aria-label="권고 목록">${recs.length === 0 ? html`<div class="muted">권고가 없습니다.</div>` : recs.map((r) => html`<div class="row rec" role="listitem" key=${r.node_id + r.deviation_id + r.entry_id}>
      <button type="button" class="nrow-b" onClick=${() => R.openCell(r.node_id, r.deviation_id)} aria-label=${r.node_id + " " + (r.deviation || "") + " 권고: " + r.text}>
        <span class="main"><b>${r.text}</b><span>${r.node_id} ${r.node_name || ""} › ${r.deviation}</span></span></button>
      <${Chip} kind=${(STATUS[r.status] || [])[1]}>${(STATUS[r.status] || [r.status])[0]}<//>${r.risk != null ? html`<${Chip}>위험도 ${r.risk}<//>` : null}</div>`)}</div></div>`;
}

// ---------------------------------------------------------------- 패널
export function ResultsPanel({ onClose }) {
  R.wire();
  const s = R.useResults((x) => x.summary);
  const view = R.useResults((x) => x.view);
  const error = R.useResults((x) => x.error);
  const notice = R.useResults((x) => x.notice);
  return html`<section class="panel wide results" aria-label="분석 결과">
    <div class="panel-h"><h2>분석 결과</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      ${!s.available || s.empty ? html`<div class="center-empty"><p>${s.reason || "분석할 구간이 없습니다."}</p>
        <${Btn} kind="primary" label="구간 만들기" onClick=${() => store.set({ panel: "nodes" })}>구간 패널 열기<//></div>` : html`
        <${Header} s=${s} />
        ${s.read_only ? html`<${Notice} kind="warn" icon="alert-triangle">${s.read_only}<//>` : null}
        <${RunState} run=${s.run} /><${PlanCard} />
        ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${R.dismissError}>닫기<//><//>` : null}
        ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice}<//>` : null}
        ${view === "recs" ? html`<${Recs} />` : html`<${Matrix} s=${s} />`}
        ${view === "recs" ? null : html`<${Legend} />`}
        ${view === "recs" ? null : html`<${Worksheet} />`}
        ${view === "recs" ? html`<${Worksheet} />` : null}`}
    </div></section>`;
}
