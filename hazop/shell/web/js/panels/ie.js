// 초기사건 패널(규격 §2.1·§2.3 ⑥): 보기 셋 — 그룹(묶이지 않은 후보 + 그룹 목록 + 그룹 상세), 완전성 대조(범주 표), 품질 경고. 머리에 규칙 초안 만들기와
// 인계 묶음 내보내기. 편집(A10)은 이전 화면 ⑥과 같은 엔진 함수를 부른다: 후보 묶기·옮기기·빼기, 그룹 고치기·나누기·지우기, 표제·최종상태·기본사건
// 고치기·받아들이기·지우기, 빈 범주 판정. 저장하는 자료는 엔진만 쓰고 여기서는 보여 주고 명령만 보낸다. 모델·도면에서 온 글은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { store } from "../store.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import * as I from "./ie_state.js";
import { FmeaView, MldSection } from "./ie_p5.js";

const STATUS = { draft: ["초안", "ai"], confirmed: ["확정", "ok"], split: ["나뉨", "plain"], deleted: ["삭제", "plain"] };
const JUDGE = { yes: ["후보", "accent"], no: ["제외", "plain"], undecided: ["보류", "warn"] };
const COVER = { covered: ["대응 그룹 있음", "ok"], gap: ["빈 범주", "warn"], unclassified: ["미분류", "plain"], unmapped: ["범주 없음", "warn"], out_of_scope: ["범위 밖", "plain"], other_method: ["다른 기법", "plain"], not_applicable: ["해당 없음", "plain"] };
const DISPOSITION = { out_of_scope: "범위 밖", other_method: "다른 기법으로 확인 예정", not_applicable: "해당 없음(설계 특성)" };
const WARN_NAME = { safeguard_as_cause: "보호수단이 원인으로 적힘", mitigated_consequence: "완화 결과로 적힘", actuation_unknown: "작동 방식 미확인", boundary_cut: "경계에서 잘림", fmea_pending: "FMEA 대기" };
const KIND_NAME = { heading: "표제", end_state: "최종상태", basic_event: "기본사건" };
// 고치기 칸: [필드, 이름, 모양("text"|"list"|"choice:<choices 키>"|"members")]. 이전 화면 FieldsDialog(EDIT_LABELS)와 같은 필드
const GROUP_FIELDS = [["name", "그룹 이름", "text"], ["definition", "정의", "text"], ["categories", "일반 범주(쉼표로)", "list"],
  ["representative", "대표 후보", "members"], ["representative_reason", "대표 선정 이유", "text"], ["plant_response", "플랜트 반응", "text"],
  ["affected_mitigation", "영향받는 완화계통", "text"], ["support_ie", "지원계통 IE", "choice:support_ie"]];
const RECORD_FIELDS = {
  heading: [["name", "표제 이름", "text"], ["targets", "구현 대상(쉼표로)", "list"], ["systems", "관련 계통", "text"], ["role", "역할", "choice:role"],
    ["actuation", "작동 방식", "choice:actuation"], ["operator_cue", "운전원 조치 단서", "text"]],
  end_state: [["text", "비완화 결과(대표 문장)", "text"], ["category", "결과 범주", "choice:category"]],
  basic_event: [["name", "이름", "text"], ["equipment_kind", "기기 종류", "text"], ["system", "계통", "text"], ["failure_mode", "고장모드 코드", "text"],
    ["failure_text", "고장모드 설명", "text"]],
};
const shown = (v, shape) => (shape === "list" ? (v || []).join(", ") : v == null ? "" : String(v));
const parsed = (v, shape) => (shape === "list" ? v.split(",").map((x) => x.trim()).filter(Boolean) : shape === "members" ? (v || null) : v.trim());

/** 필드 고치기 칸. 바뀐 필드만 onSave로 넘긴다. */
function FieldForm({ title, fields, values, choices, members, onSave, onCancel }) {
  const [f, setF] = useState(() => Object.fromEntries(fields.map(([k, , shape]) => [k, shown(values[k], shape)])));
  const busy = I.useIe((x) => x.busy);
  const changed = () => {
    const out = {};
    const orig = (k, shape) => (shape === "list" ? values[k] || [] : shape === "members" ? values[k] || null : values[k] == null ? "" : values[k]);
    fields.forEach(([k, , shape]) => { const v = parsed(f[k], shape); if (JSON.stringify(v) !== JSON.stringify(orig(k, shape))) out[k] = v; });
    return out;
  };
  const input = (k, label, shape) => {
    const set = (x) => setF(Object.assign({}, f, { [k]: x.target.value }));
    if (shape.startsWith("choice:")) {
      const ch = (choices || {})[shape.slice(7)] || {};
      return html`<select class="textbox" aria-label=${label} value=${f[k]} onChange=${set}>${Object.keys(ch).map((c) => html`<option value=${c} key=${c}>${ch[c]}</option>`)}</select>`;
    }
    if (shape === "members") {
      return html`<select class="textbox" aria-label=${label} value=${f[k]} onChange=${set}><option value="">없음</option>${(members || []).map((m) => html`<option value=${m.candidate_id} key=${m.candidate_id}>${m.candidate_id} ${m.cause}</option>`)}</select>`;
    }
    return html`<input class="textbox" aria-label=${label} maxlength="2000" value=${f[k]} onInput=${set} />`;
  };
  return html`<div class="card ie-form" role="group" aria-label=${title}>
    <h4>${title}</h4>
    <div class="editgrid">${fields.map(([k, label, shape]) => html`<label key=${k}>${label}${input(k, label, shape)}</label>`)}</div>
    <div class="acts-row"><${Btn} sm=${true} kind="primary" label="저장" disabled=${busy} onClick=${async () => { const c = changed(); if (!Object.keys(c).length) { onCancel(); return; } if (await onSave(c)) onCancel(); }}>저장<//>
      <${Btn} sm=${true} label="취소" onClick=${onCancel}>취소<//></div></div>`;
}

function Ask() {
  const ask = I.useIe((x) => x.ask);
  const busy = I.useIe((x) => x.busy);
  if (!ask) return null;
  return html`<div class="card ie-ask" role="alertdialog" aria-label="확인">
    <p>${ask.message}</p>
    ${ask.groups.length ? html`<div class="small">확정이 풀릴 그룹: <b>${ask.groups.join(", ")}</b></div>` : null}
    <div class="acts-row"><${Btn} sm=${true} kind="primary" label="계속" disabled=${busy} onClick=${I.confirmAsk}>계속<//>
      <${Btn} sm=${true} label="그만두기" onClick=${I.cancelAsk}>그만두기<//></div></div>`;
}

function CandRow({ c, pick = true }) {
  const picked = I.useIe((x) => x.picked);
  const on = picked.includes(c.candidate_id);
  return html`<div class=${"row cand" + (on ? " on" : "")} role="listitem" key=${c.candidate_id}>
    ${pick ? html`<input type="checkbox" checked=${on} aria-label=${c.candidate_id + " 고르기"} onChange=${() => I.togglePick(c.candidate_id)} />` : null}
    <span class="main"><b>${c.candidate_id} <span class="nm">${c.cause}</span></b>
      <span>${(c.node_ids && c.node_ids.length > 1 ? c.node_ids.join("·") + " (겹친 구간 " + c.node_ids.length + "곳)" : c.node_id)} › ${c.deviation_label}${c.category ? " · 범주 " + c.category : " · 범주 없음"}</span></span>
    <${Chip} kind=${(JUDGE[c.judgement] || [])[1]}>${(JUDGE[c.judgement] || [c.judgement])[0]}<//></div>`;
}

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
      <${Btn} sm=${true} icon="file-export" label="초기사건 인계 묶음 내보내기" disabled=${busy} title="승인 항목만, Excel과 같은 이름의 JSON" onClick=${I.exportBundle}>인계 묶음<//></span></div>
    <div class="acts-row" role="tablist" aria-label="보기">${tab("groups", "그룹")}${tab("completeness", "완전성 대조 " + k.gaps)}${tab("warnings", "품질 경고 " + k.warnings)}${tab("fmea", "FMEA")}</div>`;
}

/** 고른 후보로 할 일. 고른 것이 있을 때만 보인다. 묶이지 않은 후보: 새 그룹으로 묶기·열어 둔 그룹에 넣기. 소속 후보: 빼기·나누기·옮기기·소속 확인. */
function PickBar({ s, members }) {
  const picked = I.useIe((x) => x.picked);
  const busy = I.useIe((x) => x.busy);
  const active = I.useIe((x) => x.active);
  const [name, setName] = useState("");
  const [to, setTo] = useState("");
  const mine = (members || []).map((m) => m.candidate_id);
  const sel = picked.filter((id) => (members ? mine.includes(id) : !mine.length || !mine.includes(id)));
  if (!sel.length) return null;
  const targets = s.groups.filter((g) => g.group_id !== (members ? active : null));
  const move = targets.length ? html`<select class="textbox" aria-label="옮길 그룹" value=${to} onChange=${(e) => setTo(e.target.value)}><option value="">다른 그룹으로…</option>
      ${targets.map((g) => html`<option value=${g.group_id} key=${g.group_id}>${g.group_id} ${g.name}</option>`)}</select>
    <${Btn} sm=${true} label="그룹으로 옮기기" disabled=${busy || !to} onClick=${() => I.moveTo(sel, to)}>옮기기<//>` : null;
  return html`<div class="ie-pick" role="group" aria-label="고른 후보로 할 일">
    <span class="small"><b>${sel.length}개</b> 고름</span>
    ${members ? html`<${Btn} sm=${true} label="그룹에서 빼기" disabled=${busy} onClick=${() => I.moveTo(sel, "")}>빼기<//>
      <${Btn} sm=${true} label="고른 후보를 새 그룹으로 나누기" disabled=${busy || sel.length >= mine.length} onClick=${() => I.splitGroup(active, sel)}>나누기<//>
      <${Btn} sm=${true} label="소속 확인" title="규칙이 배정한 소속을 사람이 확인합니다" disabled=${busy} onClick=${() => I.acceptMembers(sel)}>소속 확인<//>${move}`
    : html`${active ? html`<${Btn} sm=${true} kind="primary" label="열린 그룹에 넣기" disabled=${busy} onClick=${() => I.moveTo(sel, active)}>${active}에 넣기<//>` : null}
      <input class="textbox" aria-label="새 그룹 이름" placeholder="새 그룹 이름" maxlength="200" value=${name} onInput=${(e) => setName(e.target.value)} />
      <${Btn} sm=${true} kind=${active ? "" : "primary"} label="새 그룹으로 묶기" disabled=${busy || !name.trim()} onClick=${async () => { if (await I.createGroup(name.trim(), sel)) setName(""); }}>새 그룹<//>${move}`}
    <${Btn} sm=${true} kind="ghost" label="고르기 풀기" onClick=${I.clearPicked}>풀기<//></div>`;
}

function Groups({ s }) {
  const active = I.useIe((x) => x.active);
  const detail = I.useIe((x) => x.detail);
  return html`<div class="ie-cols">
    <div class="ie-left"><h3>묶이지 않은 후보 ${s.unassigned.length}</h3>
      <${PickBar} s=${s} />
      <div class="list" role="list" aria-label="묶이지 않은 후보">${s.unassigned.length ? s.unassigned.map((c) => html`<${CandRow} c=${c} key=${c.candidate_id} />`) : html`<div class="muted">모든 후보가 그룹에 들어 있습니다.</div>`}</div></div>
    <div class="ie-right"><h3>그룹 ${s.groups.length}</h3>
      <div class="list" role="list" aria-label="그룹 목록">${s.groups.length ? s.groups.map((g) => html`<div class=${"row nrow" + (active === g.group_id ? " on" : "")} role="listitem" key=${g.group_id}>
        <button type="button" class="nrow-b" aria-pressed=${active === g.group_id ? "true" : "false"} aria-label=${g.group_id + " " + g.name} onClick=${() => I.openGroup(g.group_id)}>
          <span class="main"><b>${g.group_id} <span class="nm">${g.name}</span></b><span>소속 후보 ${g.member_count}${g.categories.length ? " · " + g.categories.join(", ") : ""}</span></span></button>
        <${Chip} kind=${(STATUS[g.status] || [])[1]}>${(STATUS[g.status] || [g.status])[0]}<//></div>`) : html`<div class="muted">그룹이 없습니다. 규칙 초안 만들기로 시작하거나, 후보를 골라 새 그룹으로 묶으세요.</div>`}</div>
      ${active ? html`<${Detail} s=${s} d=${detail} gid=${active} />` : null}</div></div>`;
}

/** 표제·최종상태·기본사건 한 줄. 줄을 누르면 그 줄의 동작(받아들이기·고치기·지우기)이 열린다. */
function RecordRow({ kind, id, label, sub, d }) {
  const busy = I.useIe((x) => x.busy);
  const [open, setOpen] = useState(false);
  const [edit, setEdit] = useState(false);
  const rec = d.records[kind + ":" + id] || {};
  return html`<div class=${"ie-rec" + (open ? " on" : "")} key=${id}>
    <button type="button" class="linkish small" aria-expanded=${open ? "true" : "false"} aria-label=${id + " " + KIND_NAME[kind]} onClick=${() => { setOpen(!open); setEdit(false); }}>
      <b>${id}</b> ${label} <span class="muted">${sub} · ${rec.origin === "human" ? "사람" : "AI 초안"}</span></button>
    ${open ? html`<span class="acts">
        ${rec.origin !== "human" ? html`<${Btn} sm=${true} kind="ghost" label=${id + " 받아들이기"} disabled=${busy} onClick=${() => I.acceptRecord(kind, id)}>받아들이기<//>` : null}
        <${Btn} sm=${true} kind="ghost" label=${id + " 고치기"} disabled=${busy} onClick=${() => setEdit(!edit)}>고치기<//>
        <${Btn} sm=${true} kind="ghost" label=${id + " 지우기"} disabled=${busy} onClick=${() => I.removeRecord(kind, id)}>지우기<//></span>` : null}
    ${edit ? html`<${FieldForm} title=${id + " 고치기"} fields=${RECORD_FIELDS[kind]} values=${rec} choices=${d.choices} onSave=${(f) => I.editRecord(kind, id, f)} onCancel=${() => setEdit(false)} />` : null}</div>`;
}

function Detail({ s, d, gid }) {
  const busy = I.useIe((x) => x.busy);
  const [mode, setMode] = useState(null);       // null | "edit" | "heading" | "end_state"
  const [more, setMore] = useState(false);
  if (!d) return html`<div class="muted">불러오는 중…</div>`;
  const g = d.group;
  const st = STATUS[g.status] || [g.status, ""];
  const draft = d.stored_status === "draft";
  const pick = (m) => { setMode(mode === m ? null : m); setMore(false); };
  return html`<div class="card ndetail" aria-label=${gid + " 상세"}>
    <div class="nd-h"><b>${g.group_id}</b> ${g.name} <${Chip} kind=${st[1]}>${st[0]}<//>${g.confirmed_by ? html` <span class="muted small">${g.confirmed_by}</span>` : null}
      <span class="acts">
        ${g.status === "confirmed" ? html`<${Btn} sm=${true} label="확정 풀기" disabled=${busy} onClick=${() => I.reopenGroup(gid)}>확정 풀기<//>`
          : html`<${Btn} sm=${true} kind="primary" label="그룹 확정" disabled=${busy || g.problems.length > 0} title=${g.problems.length ? "확정할 수 없는 이유가 있습니다" : "검토자 이름으로 그룹을 확정합니다"} onClick=${() => I.confirmGroup(gid)}>확정<//>`}
        <${Btn} sm=${true} label="그룹 고치기" disabled=${busy} onClick=${() => pick("edit")}>고치기<//>
        <${Btn} sm=${true} kind="ghost" label="그룹 동작 더 보기" aria-expanded=${more ? "true" : "false"} onClick=${() => setMore(!more)}>더 보기<//>
        <${Btn} sm=${true} kind="ghost" icon="x" label="그룹 상세 닫기" onClick=${() => I.ie.set({ active: null, detail: null, picked: [] })} /></span></div>
    ${more ? html`<div class="acts-row ie-more" role="menu" aria-label="그룹 동작">
      <${Btn} sm=${true} label="표제 더하기" onClick=${() => pick("heading")}>표제 더하기<//>
      <${Btn} sm=${true} label="최종상태 더하기" onClick=${() => pick("end_state")}>최종상태 더하기<//>
      <${Btn} sm=${true} label="그룹 지우기" disabled=${busy || !draft} title=${draft ? "초안 그룹을 지웁니다(확인을 받습니다)" : "확정한 그룹은 먼저 확정을 풀어야 지울 수 있습니다"} onClick=${() => { setMore(false); I.deleteGroup(gid); }}>그룹 지우기<//></div>` : null}
    ${g.problems.length ? html`<${Notice} kind="warn" icon="alert-triangle"><b>확정할 수 없는 이유</b><ul class="tight">${g.problems.map((p, i) => html`<li key=${i}>${p}</li>`)}</ul><//>` : null}
    ${mode === "edit" ? html`<${FieldForm} title=${gid + " 고치기"} fields=${GROUP_FIELDS} values=${d.editable} choices=${d.choices} members=${d.members} onSave=${(f) => I.editGroup(gid, f)} onCancel=${() => setMode(null)} />` : null}
    ${mode === "heading" ? html`<${FieldForm} title="표제 더하기" fields=${RECORD_FIELDS.heading} values=${{ role: "mitigative", actuation: "unknown" }} choices=${d.choices} onSave=${(f) => I.addRecord("heading", gid, Object.assign({ role: "mitigative", actuation: "unknown" }, f))} onCancel=${() => setMode(null)} />` : null}
    ${mode === "end_state" ? html`<${FieldForm} title="최종상태 더하기" fields=${RECORD_FIELDS.end_state} values=${{ category: "unclassified" }} choices=${d.choices} onSave=${(f) => I.addRecord("end_state", gid, Object.assign({ category: "unclassified" }, f))} onCancel=${() => setMode(null)} />` : null}
    ${g.definition ? html`<p>${g.definition}</p>` : null}
    ${g.categories.length ? html`<div class="small">범주: ${g.categories.join(", ")} <span class="muted">(${g.category_source})</span></div>` : null}
    ${g.plant_response ? html`<div class="small"><span class="muted">플랜트 반응</span> ${g.plant_response}</div>` : null}
    <h4>소속 후보 ${d.members.length}</h4>
    <${PickBar} s=${s} members=${d.members} />
    <div class="list" role="list" aria-label="소속 후보">${d.members.map((c) => html`<${CandRow} c=${c} key=${c.candidate_id} />`)}</div>
    ${d.headings.length ? html`<h4>사건수목 표제 ${d.headings.length}</h4>${d.headings.map((h) => html`<${RecordRow} kind="heading" id=${h.heading_id} label=${h.name} sub=${(h.role || "") + " " + (h.actuation || "")} d=${d} key=${h.heading_id} />`)}` : null}
    ${d.end_states.length ? html`<h4>최종상태 ${d.end_states.length}</h4>${d.end_states.map((e) => html`<${RecordRow} kind="end_state" id=${e.end_state_id} label=${e.text} sub=${e.category} d=${d} key=${e.end_state_id} />`)}` : null}
    ${d.basic_events.length ? html`<h4>기본사건 ${d.basic_events.length}</h4>${d.basic_events.map((b) => html`<${RecordRow} kind="basic_event" id=${b.be_id} label=${b.name} sub=${b.failure_text || b.failure_mode || ""} d=${d} key=${b.be_id} />`)}` : null}</div>`;
}

function CoverageRow({ c }) {
  const busy = I.useIe((x) => x.busy);
  const [open, setOpen] = useState(false);
  const [disp, setDisp] = useState(c.disposition ? c.disposition.disposition : "out_of_scope");
  const [reason, setReason] = useState(c.disposition ? c.disposition.reason : "");
  const judgeable = c.code && c.status !== "covered";
  return html`<div class="row ie-cov" role="listitem" key=${(c.code || "none") + c.name_ko}>
    <span class="main"><b>${c.code ? c.code + " " : ""}${c.name_ko}</b><span>${c.source_label || ""}${c.note ? " · " + c.note : ""}</span>
      ${c.disposition ? html`<span class="small">판정: <b>${DISPOSITION[c.disposition.disposition]}</b> · ${c.disposition.reason} <span class="muted">${c.disposition.by}</span></span>` : null}
      ${open ? html`<span class="acts-row ie-judge"><select class="textbox" aria-label=${c.code + " 처리"} value=${disp} onChange=${(e) => setDisp(e.target.value)}>${Object.keys(DISPOSITION).map((k) => html`<option value=${k} key=${k}>${DISPOSITION[k]}</option>`)}</select>
        <input class="textbox" aria-label=${c.code + " 사유"} placeholder="사유(필수)" maxlength="1000" value=${reason} onInput=${(e) => setReason(e.target.value)} />
        <${Btn} sm=${true} kind="primary" label=${c.code + " 판정 저장"} disabled=${busy || !reason.trim()} onClick=${async () => { if (await I.setCoverage(c.code, disp, reason)) setOpen(false); }}>저장<//>
        ${c.disposition ? html`<${Btn} sm=${true} kind="ghost" label=${c.code + " 판정 지우기"} disabled=${busy} onClick=${async () => { if (await I.setCoverage(c.code, "", "")) setOpen(false); }}>판정 지우기<//>` : null}
        <${Btn} sm=${true} kind="ghost" label="취소" onClick=${() => setOpen(false)}>취소<//></span>` : null}</span>
    <${Chip} kind=${(COVER[c.status] || [])[1]}>${(COVER[c.status] || [c.status])[0]}<//>${c.candidate_count ? html`<${Chip}>후보 ${c.candidate_count}<//>` : null}
    ${judgeable && !open ? html`<${Btn} sm=${true} kind="ghost" label=${c.code + " 판정"} disabled=${busy} onClick=${() => setOpen(true)}>${c.disposition ? "판정 고치기" : "판정"}<//>` : null}</div>`;
}

function Completeness({ s }) {
  return html`<div class="list" role="list" aria-label="완전성 대조">${s.completeness.map((c) => html`<${CoverageRow} c=${c} key=${(c.code || "none") + c.name_ko} />`)}</div>
    <${MldSection} />`;
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
  const unreadable = !s.available && /초기사건 파일을 읽을 수 없습니다/.test(s.reason || "");
  return html`<section class="panel wide ie" aria-label="초기사건">
    <div class="panel-h"><h2>초기사건</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <${Ask} />
      ${!s.available ? html`<div class="center-empty"><p>${s.reason || "초기사건을 볼 자료가 없습니다."}</p>
        ${unreadable ? html`<${Btn} kind="primary" label="원본을 백업하고 새로 시작" onClick=${I.replaceUnreadable}>원본 백업 뒤 새로 시작<//>`
          : html`<${Btn} kind="primary" label="분석 결과 열기" onClick=${() => store.set({ panel: "results" })}>분석 결과 패널 열기<//>`}
        ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}</div>` : html`
        <${Header} s=${s} />
        ${(s.side_unreadable || []).length ? html`<${Notice} kind="warn" icon="alert-triangle">읽을 수 없는 파일: ${s.side_unreadable.join(", ")}. 이 파일 없이 보이고 내보냅니다. FMEA 보기나 완전성 대조 보기에서 백업 뒤 새로 시작할 수 있습니다.<//>` : null}
        ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${I.dismissError}>닫기<//><//>` : null}
        ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice}<//>` : null}
        ${view === "groups" ? html`<${Groups} s=${s} />` : view === "completeness" ? html`<${Completeness} s=${s} />` : view === "fmea" ? html`<${FmeaView} />` : html`<${Warnings} s=${s} />`}`}
    </div></section>`;
}
