// 초기사건 패널(규격 §2.1·§2.3 ⑥): 보기 셋 — 그룹(묶이지 않은 후보 + 그룹 목록 + 그룹 상세), 완전성 대조(범주 표), 품질 경고. 머리에 규칙 초안 만들기와
// 인계 묶음 내보내기. 저장하는 자료는 엔진만 쓰고 여기서는 보여 주고 명령만 보낸다. 모델·도면에서 온 글은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { store } from "../store.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import * as I from "./ie_state.js";

const STATUS = { draft: ["초안", "ai"], confirmed: ["확정", "ok"], split: ["나뉨", "plain"], deleted: ["삭제", "plain"] };
const JUDGE = { yes: ["후보", "accent"], no: ["제외", "plain"], undecided: ["보류", "warn"] };
const COVER = { covered: ["대응 그룹 있음", "ok"], gap: ["빈 범주", "warn"], unclassified: ["미분류", "plain"], out_of_scope: ["범위 밖", "plain"], other_method: ["다른 기법", "plain"], not_applicable: ["해당 없음", "plain"] };
const WARN_NAME = { safeguard_as_cause: "보호수단이 원인으로 적힘", mitigated_consequence: "완화 결과로 적힘", actuation_unknown: "작동 방식 미확인", boundary_cut: "경계에서 잘림", fmea_pending: "FMEA 대기" };

const cand = (c) => html`<div class="row cand" role="listitem" key=${c.candidate_id}>
  <span class="main"><b>${c.candidate_id} <span class="nm">${c.cause}</span></b>
    <span>${c.node_id} › ${c.deviation_label}${c.category ? " · 범주 " + c.category : " · 범주 없음"}</span></span>
  <${Chip} kind=${(JUDGE[c.judgement] || [])[1]}>${(JUDGE[c.judgement] || [c.judgement])[0]}<//></div>`;

function Header({ s }) {
  const busy = I.useIe((x) => x.busy);
  const view = I.useIe((x) => x.view);
  const k = s.kpi;
  const tab = (v, label) => html`<${Btn} sm=${true} kind=${view === v ? "primary" : ""} label=${label} onClick=${() => I.setView(v)}>${label}<//>`;
  return html`<div class="acts-row res-head">
    <div class="acts-row kpi">
      <${Chip}>후보 ${k.candidates}<//><${Chip}>그룹 ${k.groups}<//>
      <${Chip} kind=${k.unassigned ? "warn" : ""} title="어느 그룹에도 들지 않은 승인 후보">묶이지 않음 ${k.unassigned}<//>
      <${Chip} kind="ok">확정 ${k.confirmed}<//>
      <${Chip} kind=${k.warnings ? "warn" : ""}>경고 ${k.warnings}<//></div>
    <span class="acts">
      <${Btn} sm=${true} icon="sparkles" label="규칙 초안 만들기" disabled=${busy} title="승인한 후보에서 규칙으로 초안 그룹을 만듭니다(확정하지 않음)" onClick=${I.suggest}>규칙 초안 만들기<//>
      <${Btn} sm=${true} icon="file-export" label="초기사건 인계 묶음 내보내기" disabled=${busy} onClick=${I.exportBundle}>인계 묶음<//></span></div>
    <div class="acts-row" role="tablist" aria-label="보기">${tab("groups", "그룹")}${tab("completeness", "완전성 대조 " + k.gaps)}${tab("warnings", "품질 경고 " + k.warnings)}</div>`;
}

function Groups({ s }) {
  const active = I.useIe((x) => x.active);
  const detail = I.useIe((x) => x.detail);
  return html`<div class="ie-cols">
    <div class="ie-left"><h3>묶이지 않은 후보 ${s.unassigned.length}</h3>
      <div class="list" role="list" aria-label="묶이지 않은 후보">${s.unassigned.length ? s.unassigned.map(cand) : html`<div class="muted">모든 후보가 그룹에 들어 있습니다.</div>`}</div></div>
    <div class="ie-right"><h3>그룹 ${s.groups.length}</h3>
      <div class="list" role="list" aria-label="그룹 목록">${s.groups.length ? s.groups.map((g) => html`<div class=${"row nrow" + (active === g.group_id ? " on" : "")} role="listitem" key=${g.group_id}>
        <button type="button" class="nrow-b" aria-pressed=${active === g.group_id ? "true" : "false"} aria-label=${g.group_id + " " + g.name} onClick=${() => I.openGroup(g.group_id)}>
          <span class="main"><b>${g.group_id} <span class="nm">${g.name}</span></b><span>소속 후보 ${g.member_count}${g.categories.length ? " · " + g.categories.join(", ") : ""}</span></span></button>
        <${Chip} kind=${(STATUS[g.status] || [])[1]}>${(STATUS[g.status] || [g.status])[0]}<//></div>`) : html`<div class="muted">그룹이 없습니다. 규칙 초안 만들기로 시작하세요.</div>`}</div>
      ${active ? html`<${Detail} d=${detail} gid=${active} />` : null}</div></div>`;
}

function Detail({ d, gid }) {
  const busy = I.useIe((x) => x.busy);
  if (!d) return html`<div class="muted">불러오는 중…</div>`;
  const g = d.group;
  const st = STATUS[g.status] || [g.status, ""];
  return html`<div class="card ndetail" aria-label=${gid + " 상세"}>
    <div class="nd-h"><b>${g.group_id}</b> ${g.name} <${Chip} kind=${st[1]}>${st[0]}<//>${g.confirmed_by ? html` <span class="muted small">${g.confirmed_by}</span>` : null}</div>
    ${g.definition ? html`<p>${g.definition}</p>` : html`<div class="muted small">정의가 비어 있습니다.</div>`}
    ${g.categories.length ? html`<div class="small">범주: ${g.categories.join(", ")} <span class="muted">(${g.category_source})</span></div>` : null}
    ${g.plant_response ? html`<div class="small"><span class="muted">플랜트 반응</span> ${g.plant_response}</div>` : null}
    <h4>소속 후보 ${d.members.length}</h4><div class="list" role="list">${d.members.map(cand)}</div>
    <h4>사건수목 표제 ${d.headings.length}</h4>${d.headings.length ? d.headings.map((h) => html`<div class="small" key=${h.heading_id}><b>${h.heading_id}</b> ${h.name} <span class="muted">${h.role || ""} ${h.actuation || ""} · ${h.origin === "human" ? "사람" : "AI 초안"}</span></div>`) : html`<div class="muted small">없음</div>`}
    <h4>최종상태 ${d.end_states.length}</h4>${d.end_states.length ? d.end_states.map((e) => html`<div class="small" key=${e.end_state_id}><b>${e.end_state_id}</b> ${e.text} <span class="muted">${e.category} · ${e.origin === "human" ? "사람" : "AI 초안"}</span></div>`) : html`<div class="muted small">없음</div>`}
    <h4>기본사건 ${d.basic_events.length}</h4>${d.basic_events.length ? d.basic_events.map((b) => html`<div class="small" key=${b.be_id}><b>${b.be_id}</b> ${b.name} <span class="muted">${b.failure_text || b.failure_mode || ""}</span></div>`) : html`<div class="muted small">없음</div>`}
    ${g.problems.length ? html`<${Notice} kind="warn" icon="alert-triangle"><b>확정할 수 없는 이유</b><ul class="tight">${g.problems.map((p, i) => html`<li key=${i}>${p}</li>`)}</ul><//>` : null}
    <div class="acts-row">
      ${g.status === "confirmed" ? html`<${Btn} sm=${true} label="확정 풀기" disabled=${busy} onClick=${() => I.reopenGroup(gid)}>확정 풀기<//>`
        : html`<${Btn} sm=${true} kind="primary" label="그룹 확정" disabled=${busy || g.problems.length > 0} title=${g.problems.length ? "확정할 수 없는 이유가 있습니다" : "그룹 확정"} onClick=${() => I.confirmGroup(gid)}>확정<//>`}</div></div>`;
}

function Completeness({ s }) {
  return html`<div class="list" role="list" aria-label="완전성 대조">${s.completeness.map((c) => html`<div class="row" role="listitem" key=${(c.code || "none") + c.name_ko}>
    <span class="main"><b>${c.code ? c.code + " " : ""}${c.name_ko}</b><span>${c.source_label || ""}${c.note ? " · " + c.note : ""}</span></span>
    <${Chip} kind=${(COVER[c.status] || [])[1]}>${(COVER[c.status] || [c.status])[0]}<//>${c.candidate_count ? html`<${Chip}>후보 ${c.candidate_count}<//>` : null}</div>`)}</div>`;
}

function Warnings({ s }) {
  return html`<div>
    <div class="acts-row">${s.warning_summary.map((w) => html`<${Chip} key=${w.kind} kind=${w.count ? "warn" : ""}>${WARN_NAME[w.kind] || w.kind} ${w.count}<//>`)}</div>
    <div class="list" role="list" aria-label="품질 경고">${s.warnings.length ? s.warnings.map((w, i) => html`<div class="row" role="listitem" key=${i}>
      <span class="main"><b>${WARN_NAME[w.kind] || w.kind}</b><span>${w.text}</span><span class="muted small">${w.basis || ""}</span></span></div>`) : html`<div class="muted">품질 경고가 없습니다.</div>`}</div></div>`;
}

export function IePanel({ onClose }) {
  I.wire();
  const s = I.useIe((x) => x.summary);
  const view = I.useIe((x) => x.view);
  const error = I.useIe((x) => x.error);
  const notice = I.useIe((x) => x.notice);
  return html`<section class="panel wide ie" aria-label="초기사건">
    <div class="panel-h"><h2>초기사건</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      ${!s.available ? html`<div class="center-empty"><p>${s.reason || "초기사건을 볼 자료가 없습니다."}</p>
        <${Btn} kind="primary" label="분석 결과 열기" onClick=${() => store.set({ panel: "results" })}>분석 결과 패널 열기<//></div>` : html`
        <${Header} s=${s} />
        ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${I.dismissError}>닫기<//><//>` : null}
        ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice}<//>` : null}
        ${view === "groups" ? html`<${Groups} s=${s} />` : view === "completeness" ? html`<${Completeness} s=${s} />` : html`<${Warnings} s=${s} />`}`}
    </div></section>`;
}
