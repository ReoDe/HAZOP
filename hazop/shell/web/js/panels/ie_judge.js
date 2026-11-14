// 초기사건 후보 카드(B5): 한 줄 추적(구간·편차 → 원인 → 위치·고장모드 → IE 판정 → 그룹 → 최종상태 → 근거 경로)과 후보별 IE 판정.
// 판정은 ⑤ 결과 파일의 ie_hint에 저장한다(설계 E4). 화면이 본 ⑤ 판(rver)과 후보 지문(seen)을 실어 ie.judge로 보내고, 겹친 구간에서 한 후보로
// 묶인 같은 원인 항목은 엔진이 한 번에 같은 판정으로 저장한다. 마디를 누르면 그 칸(분석 결과)·도면 강조·그룹으로 간다. 글은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { store } from "../store.js";

import { Btn } from "../ui/parts.js";
import * as I from "./ie_state.js";

const KIND_NAME = { cell: "구간·편차", cause: "원인", location: "위치·고장모드", judgement: "IE 판정", group: "그룹", end_state: "최종상태", path: "근거" };

async function go(node, d) {
  if ((node.kind === "cell" || node.kind === "cause") && node.node_id) {
    const R = await import("./results_state.js");
    store.set({ panel: "results", backTo: "ie" });
    R.openCell(node.node_id, node.deviation_id);
  } else if ((node.kind === "location" || node.kind === "path") && node.sheet) {
    const R = await import("./results_state.js");
    R.openSheet(node.sheet);
    store.set({ sheet: node.sheet, panel: null, backTo: "ie", marks: { rid: "ie-trace", bySheet: node.marks || {} } });
  } else if ((node.kind === "group" || node.kind === "end_state") && node.group_id) {
    I.ie.set({ view: "groups" });
    I.openGroup(node.group_id);
  }
}

const goable = (n) => ((n.kind === "cell" || n.kind === "cause") && n.node_id) || ((n.kind === "location" || n.kind === "path") && n.sheet)
  || ((n.kind === "group" || n.kind === "end_state") && n.group_id);

function Trace({ d }) {
  return html`<div class="ie-trace" role="list" aria-label="추적">${d.trace.map((n, i) => html`<span class="tr-node" role="listitem" key=${i}>
    ${i ? html`<span class="tr-arrow" aria-hidden="true">→</span>` : null}
    ${goable(n) ? html`<button type="button" class="linkish" aria-label=${KIND_NAME[n.kind] + ": " + n.label} onClick=${() => go(n, d)}><span class="muted small">${KIND_NAME[n.kind]}</span> ${n.label}</button>`
      : html`<span><span class="muted small">${KIND_NAME[n.kind]}</span> ${n.label}</span>`}
    ${(n.twins || []).length ? html`<span class="muted small"> (${n.twins.map((t, j) => html`<button type="button" class="linkish" key=${j} aria-label=${"겹친 구간: " + t.label}
        onClick=${() => go(Object.assign({ kind: "cell" }, t), d)}>${j ? ", " : ""}${t.label}</button>`)})</span>` : null}</span>`)}</div>
    ${d.choices.terms ? html`<div class="muted small" aria-label="용어">${d.choices.terms.disturbs}·${d.choices.terms.challenges}: ${d.choices.terms.source}</div>` : null}`;
}

function JudgeForm({ d, onSaved }) {
  const busy = I.useIe((x) => x.busy);
  const h = d.hint || {};
  const [f, setF] = useState(() => ({ candidate: h.candidate || "undecided", disturbs: h.disturbs || "unknown", challenges: h.challenges || "unknown",
    category: h.category || "", functions: (h.safety_functions || []).join(", "), reason: h.reason || "" }));
  const set = (k) => (x) => setF(Object.assign({}, f, { [k]: x.target.value }));
  const sel = (k, label, choices) => html`<label>${label}<select class="textbox" aria-label=${label} value=${f[k]} onChange=${set(k)}>
    ${Object.keys(choices).map((c) => html`<option value=${c} key=${c}>${choices[c]}</option>`)}</select></label>`;
  const save = async () => {
    const hint = { candidate: f.candidate, disturbs: f.disturbs, challenges: f.challenges, category: f.category || null,
      safety_functions: f.functions.split(",").map((x) => x.trim()).filter(Boolean), reason: f.reason };
    if (await I.judgeCandidate(d, hint)) onSaved();
  };
  return html`<div class="ie-form" role="group" aria-label="IE 판정">
    <div class="editgrid">
      ${sel("candidate", "초기사건 후보", d.choices.candidate)}${sel("disturbs", "정상운전 교란", d.choices.answer)}${sel("challenges", "안전기능 도전", d.choices.answer)}
      <label>일반 범주<select class="textbox" aria-label="일반 범주" value=${f.category} onChange=${set("category")}><option value="">미분류</option>
        ${d.choices.categories.map((c) => html`<option value=${c.code} key=${c.code}>${c.label}</option>`)}</select></label>
      <label>도전받는 안전기능(쉼표로)<input class="textbox" aria-label="도전받는 안전기능" maxlength="500" value=${f.functions} onInput=${set("functions")} /></label>
      <label>판정 이유<input class="textbox" aria-label="판정 이유" maxlength="1000" value=${f.reason} onInput=${set("reason")} /></label></div>
    <div class="muted small">항목 승인과 따로 확정합니다. 사람이 정한 판정으로 ⑤ 결과에 저장되고${d.targets.length > 1 ? ", 겹친 구간의 같은 원인 항목 " + d.targets.length + "개에 함께 적힙니다" : ""}. 맞는 범주가 없으면 미분류로 두세요.</div>
    <div class="acts-row"><${Btn} sm=${true} kind="primary" label="판정 확정" disabled=${busy} onClick=${save}>판정 확정<//></div></div>`;
}

/** 고른 후보의 카드: 추적 한 줄 + 판정. 판정 칸은 눌러서 연다(늘 떠 있는 칸을 줄임). */
export function CandidateCard({ iec }) {
  const d = I.useIe((x) => (x.cand && x.cand.iec === iec ? x.cand.data : null));
  const [open, setOpen] = useState(false);
  if (!d) return html`<div class="muted small">불러오는 중…</div>`;
  return html`<div class="card ie-cand" aria-label=${iec + " 카드"}>
    <${Trace} d=${d} />
    <div class="acts-row"><${Btn} sm=${true} label=${iec + " IE 판정"} onClick=${() => setOpen(!open)}>${open ? "판정 닫기" : "IE 판정"}<//></div>
    ${open ? html`<${JudgeForm} d=${d} onSaved=${() => setOpen(false)} key=${d.fp} />` : null}</div>`;
}


