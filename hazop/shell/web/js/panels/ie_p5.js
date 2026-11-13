// 초기사건 패널 P5(설계 HZ-PLN-17 §8.2): FMEA 보기와 완전성 대조 보기의 주논리도(MLD) 가지. 늘 떠 있는 단추를 늘리지 않는다:
// 가져오기·양식 내보내기는 FMEA 보기 안에, 행 승인·고치기·구성요소 고르기는 고른 행의 카드 안에, MLD 가져오기와 가지 판정·그룹 잇기는
// 완전성 대조 보기 안에서 연다. 저장하는 자료는 엔진만 쓰고 여기서는 보여 주고 명령만 보낸다. 표에서 온 글은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { Btn, Chip } from "../ui/parts.js";
import * as I from "./ie_state.js";

const STATUS_KIND = { imported: "ai", approved: "ok", excluded: "plain" };
const MLD_KIND = { covered: "ok", gap: "warn", unmapped: "warn", not_applicable: "plain" };
const DISPOSITION = { out_of_scope: "범위 밖", other_method: "다른 기법으로 확인 예정", not_applicable: "해당 없음(설계 특성)" };
const EDIT_FIELDS = [["failure_mode", "고장모드"], ["failure_code", "고장모드 코드"], ["cause", "원인"], ["op_mode", "운전 모드"],
  ["effect", "고장 영향"], ["detection", "탐지 방법"], ["compensation", "보상 수단"], ["remark", "비고·조치"], ["hazop_entry", "관련 HAZOP 항목"]];

function RowCard({ r, f }) {
  const busy = I.useIe((x) => x.busy);
  const [edit, setEdit] = useState(false);
  const [vals, setVals] = useState(() => Object.fromEntries(EDIT_FIELDS.map(([k]) => [k, r[k] || ""])));
  const [q, setQ] = useState(r.tag || "");
  const [pick, setPick] = useState("");
  const qn = q.trim().toUpperCase();
  const comps = qn ? f.components.filter((c) => c.tag.toUpperCase().includes(qn)).slice(0, 30) : [];
  const save = async () => {
    const out = {};
    EDIT_FIELDS.forEach(([k]) => { if ((vals[k] || "") !== (r[k] || "")) out[k] = vals[k]; });
    if (!Object.keys(out).length || (await I.fmeaEdit(r.row_id, out))) setEdit(false);
  };
  return html`<div class="card ie-frow" aria-label=${r.row_id + " 카드"}>
    <div class="small"><b>${r.row_id}</b> ${r.tag} · ${r.failure_mode}${r.failure_code ? " (" + r.failure_code + ")" : " · 코드 미정"}
      ${r.node_id ? html` · <span class="muted">${r.node_id}</span>` : null}</div>
    <div class="small muted">${[r.cause && "원인 " + r.cause, r.effect && "영향 " + r.effect, r.detection && "탐지 " + r.detection].filter(Boolean).join(" · ")}</div>
    ${!r.ref ? html`<div class="ie-judge acts-row" role="group" aria-label="구성요소 고르기">
        <input class="textbox" aria-label=${r.row_id + " 구성요소 찾기"} placeholder="태그로 찾기" value=${q} onInput=${(e) => setQ(e.target.value)} />
        <select class="textbox" aria-label=${r.row_id + " 구성요소"} value=${pick} onChange=${(e) => setPick(e.target.value)}><option value="">구성요소 고르기</option>
          ${comps.map((c) => html`<option value=${c.entity_id} key=${c.entity_id}>${c.tag} · ${c.kind}${c.nodes.length ? " · " + c.nodes.join(",") : ""}</option>`)}</select>
        <${Btn} sm=${true} kind="primary" label=${r.row_id + " 구성요소 저장"} disabled=${busy || !pick} onClick=${() => I.fmeaEdit(r.row_id, { entity_id: pick })}>잇기<//></div>` : null}
    <div class="acts-row">
      ${r.status !== "approved" ? html`<${Btn} sm=${true} kind="primary" label=${r.row_id + " 승인"} disabled=${busy || !r.ref} title=${r.ref ? "기본사건 후보의 출처가 됩니다" : "구성요소를 먼저 이으세요"} onClick=${() => I.fmeaStatus([r.row_id], "approved")}>승인<//>` : null}
      ${r.status !== "excluded" ? html`<${Btn} sm=${true} label=${r.row_id + " 제외"} disabled=${busy} onClick=${() => I.fmeaStatus([r.row_id], "excluded")}>제외<//>` : null}
      ${r.status !== "imported" ? html`<${Btn} sm=${true} kind="ghost" label=${r.row_id + " 되돌리기"} disabled=${busy} onClick=${() => I.fmeaStatus([r.row_id], "imported")}>되돌리기<//>` : null}
      <${Btn} sm=${true} kind="ghost" label=${r.row_id + " 고치기"} disabled=${busy} onClick=${() => setEdit(!edit)}>고치기<//></div>
    ${edit ? html`<div class="ie-form"><div class="editgrid">${EDIT_FIELDS.map(([k, label]) => html`<label key=${k}>${label}
        <input class="textbox" aria-label=${label} maxlength="2000" value=${vals[k]} onInput=${(e) => setVals(Object.assign({}, vals, { [k]: e.target.value }))} /></label>`)}</div>
      <div class="acts-row"><${Btn} sm=${true} kind="primary" label="저장" disabled=${busy} onClick=${save}>저장<//><${Btn} sm=${true} label="취소" onClick=${() => setEdit(false)}>취소<//></div></div>` : null}</div>`;
}

function EcNodes({ f }) {
  const busy = I.useIe((x) => x.busy);
  const [open, setOpen] = useState(false);
  const ec = f.ec_nodes.filter((n) => n.ec);
  const pending = ec.filter((n) => n.analysed && !n.fmea_done);
  return html`<div class="ie-ec">
    <button type="button" class="linkish small" aria-expanded=${open ? "true" : "false"} aria-label="전기·제어 구간" onClick=${() => setOpen(!open)}>
      전기·제어 구간 ${ec.length}개${pending.length ? " · FMEA 대조 전 " + pending.map((n) => n.node_id).join(", ") : ""}</button>
    ${open ? html`<div class="list" role="list" aria-label="전기·제어 구간 목록">${f.ec_nodes.map((n) => html`<div class="row" role="listitem" key=${n.node_id}>
        <span class="main"><b>${n.node_id}</b> ${n.name || ""} <span class="muted small">${n.rule ? "규칙" : ""}${n.mark ? " · 사람 표시" : ""}${n.fmea_done ? " · FMEA 있음" : ""}</span></span>
        <select class="textbox" aria-label=${n.node_id + " 전기·제어 표시"} disabled=${busy} value=${n.mark || ""} onChange=${(e) => I.fmeaMark(n.node_id, e.target.value)}>
          <option value="">규칙대로</option><option value="include">넣음</option><option value="exclude">뺌</option></select></div>`)}</div>` : null}</div>`;
}

export function FmeaView() {
  const f = I.useIe((x) => x.fmea);
  const frow = I.useIe((x) => x.frow);
  const busy = I.useIe((x) => x.busy);
  if (!f) return html`<div class="muted">불러오는 중…</div>`;
  const c = f.counts;
  return html`<div class="ie-fmea">
    <div class="acts-row res-head"><span class="small">고장모드 및 영향 분석(FMEA) 행 ${f.rows.length} · 승인 ${c.approved} · 제외 ${c.excluded}
        ${c.unmatched ? html` · <b>대응 실패 ${c.unmatched}</b>` : null}</span>
      <span class="acts"><${Btn} sm=${true} label="FMEA 양식 내보내기" disabled=${busy} title="지금 행을 채운 양식(.xlsx). 다시 가져와도 같은 행 ID" onClick=${I.fmeaTemplate}>양식<//>
        <${Btn} sm=${true} kind="primary" label="FMEA 가져오기" disabled=${busy} onClick=${I.fmeaImport}>가져오기<//></span></div>
    <${EcNodes} f=${f} />
    ${f.rows.length ? html`<div class="list" role="list" aria-label="FMEA 행">${f.rows.map((r) => html`<div key=${r.row_id}>
        <div class=${"row nrow" + (frow === r.row_id ? " on" : "")} role="listitem">
          <button type="button" class="nrow-b" aria-pressed=${frow === r.row_id ? "true" : "false"} aria-label=${r.row_id + " " + r.tag} onClick=${() => I.pickRow(r.row_id)}>
            <span class="main"><b>${r.row_id} <span class="nm">${r.tag}</span></b><span>${r.failure_mode}${r.failure_code ? " (" + r.failure_code + ")" : ""}${r.in_last_import === false ? " · 이번 가져오기에 없음" : ""}</span></span></button>
          ${r.ref ? null : html`<${Chip} kind="warn">${f.matches[r.match]}<//>`}<${Chip} kind=${STATUS_KIND[r.status]}>${f.statuses[r.status]}<//></div>
        ${frow === r.row_id ? html`<${RowCard} r=${r} f=${f} key=${r.row_id + r.fp} />` : null}</div>`)}</div>`
      : html`<div class="muted">FMEA를 아직 가져오지 않았습니다. 양식을 내보내 채운 뒤 가져오세요. 승인한 행만 기본사건 후보의 출처가 됩니다.</div>`}</div>`;
}

function MldRow({ b, m }) {
  const busy = I.useIe((x) => x.busy);
  const [open, setOpen] = useState(false);
  const [disp, setDisp] = useState(b.disposition ? b.disposition.disposition : "out_of_scope");
  const [reason, setReason] = useState(b.disposition ? b.disposition.reason : "");
  const [links, setLinks] = useState(b.group_ids);
  const code = "MLD:" + b.id;
  const toggle = (g) => setLinks(links.includes(g) ? links.filter((x) => x !== g) : links.concat([g]));
  return html`<div class="row ie-cov" role="listitem" key=${b.id}>
    <span class="main"><button type="button" class="linkish" aria-expanded=${open ? "true" : "false"} aria-label=${"MLD 가지 " + b.id} onClick=${() => setOpen(!open)}>
        <b>${b.id} ${b.name}</b></button><span class="small muted">${b.path}${b.categories.length ? " · 범주 " + b.categories.join(", ") : " · 대응 범주 없음"}${b.group_ids.length ? " · 이은 그룹 " + b.group_ids.join(", ") : ""}</span>
      ${b.disposition ? html`<span class="small">판정: <b>${DISPOSITION[b.disposition.disposition]}</b> · ${b.disposition.reason}</span>` : null}
      ${open ? html`<span class="ie-judge acts-row" role="group" aria-label=${b.id + " 판정·잇기"}>
          ${m.groups.length ? html`<span class="small">그룹 잇기:</span>${m.groups.map((g) => html`<label class="small" key=${g.group_id}><input type="checkbox" checked=${links.includes(g.group_id)} onChange=${() => toggle(g.group_id)} /> ${g.group_id}</label>`)}
            <${Btn} sm=${true} label=${b.id + " 그룹 잇기 저장"} disabled=${busy} onClick=${() => I.mldLink(b.id, links)}>잇기 저장<//>` : null}
          ${b.status !== "covered" ? html`<select class="textbox" aria-label=${code + " 처리"} value=${disp} onChange=${(e) => setDisp(e.target.value)}>${Object.keys(DISPOSITION).map((k) => html`<option value=${k} key=${k}>${DISPOSITION[k]}</option>`)}</select>
            <input class="textbox" aria-label=${code + " 사유"} placeholder="사유(필수)" maxlength="1000" value=${reason} onInput=${(e) => setReason(e.target.value)} />
            <${Btn} sm=${true} kind="primary" label=${code + " 판정 저장"} disabled=${busy || !reason.trim()} onClick=${() => I.setCoverage(code, disp, reason)}>판정 저장<//>
            ${b.disposition ? html`<${Btn} sm=${true} kind="ghost" label=${code + " 판정 지우기"} disabled=${busy} onClick=${() => I.setCoverage(code, "", "")}>판정 지우기<//>` : null}` : null}</span>` : null}</span>
    <${Chip} kind=${MLD_KIND[b.status]}>${m.statuses[b.status]}<//></div>`;
}

/** 완전성 대조 보기 아래의 주논리도(MLD) 가지 대조. MLD는 노형마다 달라 앱에 예시를 넣지 않는다(받은 파일만 대조). */
export function MldSection() {
  const m = I.useIe((x) => x.mld);
  const busy = I.useIe((x) => x.busy);
  if (!m) return null;
  const gaps = m.branches.filter((b) => b.status === "gap" || b.status === "unmapped").length;
  return html`<div class="ie-mld">
    <div class="acts-row res-head"><span class="small">${m.loaded ? html`주논리도(MLD) <b>${m.source.title || m.source.mld_id}</b> 판 ${m.source.revision || "-"} · 잎 가지 ${m.branches.length} · 공백·범주 없음 ${gaps}`
      : "주논리도(MLD)를 받지 않았습니다. 대상 노형의 MLD 파일을 가져오면 잎 가지마다 후보가 있는지 대조합니다."}</span>
      <span class="acts"><${Btn} sm=${true} label="MLD 가져오기" disabled=${busy} onClick=${I.mldImport}>${m.loaded ? "MLD 다시 가져오기" : "MLD 가져오기"}<//></span></div>
    ${m.gone_links.length ? html`<div class="small reason">MLD에 없어진 가지에 남은 연결: ${m.gone_links.join(", ")}</div>` : null}
    ${m.loaded ? html`<div class="list" role="list" aria-label="MLD 잎 가지">${m.branches.map((b) => html`<${MldRow} b=${b} m=${m} key=${b.id + (b.fp || "")} />`)}</div>` : null}</div>`;
}
