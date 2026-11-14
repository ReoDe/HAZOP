// 분석 결과 워크시트의 상세 열(B3, INTENT §3.6): 원인(유형·위치)·결과(비완화·영향 대상)·보호수단(역할·작동 방식·구현 대상)·AI 근거(경로·출처 문서·⚠).
// 보기와 '수정' 칸에 더할 편집. 값은 엔진(api_results.cell_view의 detail)이 만든 이름표를 그대로 보이고, 고치기는 results.edit_entry 하나로 보낸다.
// 사람이 고친 값은 덮지 않는다: 바꾸지 않은 보호수단 줄·참조는 원래 값(작성 표시 포함)을 그대로 돌려보내고, 바뀐 줄만 사람 작성(origin human)이 된다.
// 위험도는 엔진이 강도·빈도로 센 값만 보인다(여기서 다시 세지 않음). 모델·도면에서 온 글은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { Btn, Chip } from "../ui/parts.js";
import * as R from "./results_state.js";

const text = (v) => (typeof v === "string" ? v : "");
const none = html`<span class="muted">-</span>`;
const GONE = " (도면에서 사라짐)";
/** 참조 이름표: 그래프에서 사라진 대상은 지우지 않고 '도면에서 사라짐'을 붙여 보인다. */
const refLabel = (r) => r.label + (r.missing ? GONE : "");
/** 글 비교용: 앞뒤·사이 공백을 같은 방식으로 줄인다(보기 값과 입력 값 모두). */
export const norm = (s) => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");

export function CauseCell({ e, c }) {
  const d = e.detail || {};
  return html`<div>${text(e.cause) || none}
    ${d.cause_kind ? html`<div class="small muted">유형: ${c.cause_kinds[d.cause_kind] || d.cause_kind}</div>` : null}
    ${(d.cause_refs || []).length ? html`<div class="small">위치: ${d.cause_refs.map((r, i) => html`<span key=${i} class=${r.draft ? "draft" : ""}>${i ? ", " : ""}${refLabel(r)}${r.failure_mode ? " · " + r.failure_mode : ""}${r.draft ? " (AI 초안)" : ""}</span>`)}</div>` : null}</div>`;
}

export function ConsequenceCell({ e }) {
  const d = e.detail || {};
  return html`<div>${text(e.consequence) || none}
    <div class="small">${d.consequence_basis === "unmitigated" ? html`<${Chip} kind="ok">비완화<//>` : html`<${Chip} kind="warn" title="보호수단이 모두 실패했다고 보고 쓴 결과인지 확인하지 않았습니다">비완화 여부 미확인<//>`}</div>
    ${(d.consequence_refs || []).length ? html`<div class="small">영향 대상: ${d.consequence_refs.map((r) => refLabel(r) + (r.draft ? " (AI 초안)" : "")).join(", ")}</div>` : null}</div>`;
}

export function SafeguardCell({ e, c }) {
  const items = (e.detail || {}).safeguards || [];
  if (!items.length) return none;
  return html`<ul class="tight">${items.map((s, i) => {
    const bits = [s.role !== "unknown" ? c.roles[s.role] : null, s.actuation !== "unknown" ? c.actuations[s.actuation] : "작동 방식 미확인"]
      .concat(s.refs.map(refLabel)).filter(Boolean);
    return html`<li key=${i}>${s.text}<span class="small muted"> — ${bits.join(" · ") || "미정"}${s.draft ? " · AI 초안" : ""}</span></li>`;
  })}</ul>`;
}

/** AI 근거(경로·출처 문서·⚠). 접어 두고, 펼치면 경로는 눌러 도면에서 강조하고 출처 문서는 문서 패널의 그 자료로 간다. */
export function BasisBlock({ e }) {
  const [open, setOpen] = useState(false);
  const b = Object.assign({ paths: [], sources: [], warnings: [], clues: [] }, (e.detail || {}).basis || {});
  const n = b.paths.length + b.sources.length;
  if (!n && !b.warnings.length && !b.clues.length) return null;
  return html`<div class="basis">
    <button type="button" class="linkish small" aria-expanded=${open ? "true" : "false"} aria-label=${e.entry_id + " AI 근거"} onClick=${() => setOpen(!open)}>
      AI 근거 ${n}${b.warnings.length ? html` · <span class="warn-t">⚠ ${b.warnings.length}</span>` : null}${b.clues.length ? " · 단서 " + b.clues.length : ""} ${open ? "▾" : "▸"}</button>
    ${open ? html`<div class="basis-b">
      ${b.paths.map((p, i) => html`<div key=${"p" + i}><button type="button" class="linkish" disabled=${!p.sheet} title=${p.sheet ? "도면에서 이 경로를 강조합니다" : "도면에 그릴 구성요소가 없습니다"}
          aria-label=${"근거 경로 " + (i + 1)} onClick=${() => R.showBasisPath(p)}>경로 ${i + 1}: ${p.labels.join(" → ")}</button>${p.missing ? html` <span class="small warn-t">(구성요소 ${p.missing}개가 도면에서 사라짐)</span>` : null}</div>`)}
      ${b.sources.map((s, i) => html`<div key=${"s" + i}>${s.material_id ? html`<button type="button" class="linkish" aria-label=${"출처 문서 " + s.doc}
          onClick=${() => R.openDocument(s.material_id)}>문서 ${s.doc}${s.where ? " " + s.where : ""}</button>` : html`<span>문서 ${s.doc}${s.where ? " " + s.where : ""} <span class="muted small">(문서 패널에 없음)</span></span>`}</div>`)}
      ${b.warnings.map((w, i) => html`<div key=${"w" + i} class="small warn-t">⚠ ${w}</div>`)}
      ${b.clues.length ? html`<div class="sub-h small" aria-label="확인할 단서">확인할 단서(근거 아님)</div>
        ${b.clues.map((t, i) => html`<div key=${"q" + i} class="small muted">${t}</div>`)}` : null}</div>` : null}</div>`;
}

// ---------------------------------------------------------------- 수정 칸(더한 부분)
/** 고치기 시작 때의 값. 보호수단·참조 줄은 원래 위치(i0)를 기억해 바뀌지 않은 줄을 그대로 돌려보낸다. */
export function editState(e) {
  const d = e.detail || {};
  const known = {};  // 지금 값의 이름표(대상 목록에 없어도 맨 위에 보이려고)
  for (const r of [].concat(d.cause_refs || [], d.consequence_refs || [], ...(d.safeguards || []).map((s) => s.refs))) known[r.ref] = r;
  return {
    known,
    cause_kind: d.cause_kind || "",
    basis: d.consequence_basis === "unmitigated",
    sg: (d.safeguards || []).map((s, i) => ({ i0: i, text: s.text, role: s.role, actuation: s.actuation, refs: s.refs.map((r) => r.ref) })),
    causeRefs: (d.cause_refs || []).map((r, i) => ({ i0: i, ref: r.ref, failure_mode: r.failure_mode })),
    consRefs: (d.consequence_refs || []).map((r, i) => ({ i0: i, ref: r.ref })),
  };
}

function rawRefs(list) { return (list || []).filter((r) => r && typeof r === "object" && r.ref); }

/** 바뀐 것만 필드로. 바뀌지 않은 보호수단 줄·참조는 원래 값 그대로(작성 표시·나머지 키 보존). */
export function changedFields(e, st) {
  const d = e.detail || {};
  const out = {};
  if ((st.cause_kind || null) !== (d.cause_kind || null)) out.cause_kind = st.cause_kind || null;
  if ((st.basis ? "unmitigated" : null) !== (d.consequence_basis || null)) out.consequence_basis = st.basis ? "unmitigated" : null;
  const rawSg = (e.safeguards || []).filter((s) => typeof s === "string" || (s && typeof s === "object"));
  const sg = st.sg.filter((r) => r.text.trim()).map((r) => {
    const raw = r.i0 != null ? rawSg[r.i0] : undefined;
    const old = r.i0 != null ? d.safeguards[r.i0] : null;
    const want = [...new Set(r.refs.filter(Boolean))];
    const sameText = !!old && norm(old.text) === norm(r.text);
    const sameRefs = !!old && JSON.stringify(old.refs.map((x) => x.ref)) === JSON.stringify(want);
    if (old && sameText && old.role === r.role && old.actuation === r.actuation && sameRefs) return raw;
    // 바꾸지 않은 참조는 원래 값(작성 표시 포함) 그대로, 새로 고른 것만 사람 작성. 글이 같으면(공백만 다르면) 원래 글을 둔다.
    const keepRefs = raw && typeof raw === "object" ? rawRefs(raw.refs) : [];
    const refsNew = sameRefs ? keepRefs : want.map((ref) => keepRefs.find((x) => x.ref === ref) || { ref, origin: "human" });
    const base = raw && typeof raw === "object" ? raw : { ipl: null };
    const txt = sameText ? (typeof raw === "string" ? raw : old.text) : r.text.trim();
    const obj = Object.assign({}, base, { text: txt, role: r.role, refs: refsNew, origin: "human" });
    if (r.actuation !== "unknown" || (raw && typeof raw === "object" && "actuation" in raw)) obj.actuation = r.actuation; else delete obj.actuation;
    return obj;
  });
  if (JSON.stringify(sg) !== JSON.stringify(rawSg)) out.safeguards = sg;
  const rawCause = rawRefs(e.cause_refs);
  const cause = st.causeRefs.filter((r) => r.ref).map((r) => {
    const raw = r.i0 != null ? rawCause[r.i0] : null;
    if (raw && raw.ref === r.ref && (raw.failure_mode || "") === (r.failure_mode || "")) return raw;
    return Object.assign({ ref: r.ref, origin: "human" }, r.failure_mode ? { failure_mode: r.failure_mode } : {});
  });
  if (JSON.stringify(cause) !== JSON.stringify(rawCause)) out.cause_refs = cause;
  const rawCons = rawRefs(e.consequence_refs);
  const cons = st.consRefs.filter((r) => r.ref).map((r) => {
    const raw = r.i0 != null ? rawCons[r.i0] : null;
    return raw && raw.ref === r.ref ? raw : { ref: r.ref, origin: "human" };
  });
  if (JSON.stringify(cons) !== JSON.stringify(rawCons)) out.consequence_refs = cons;
  return out;
}

/** 대상 고르기. 지금 값이 목록(구간·이웃 대상)에 없으면 맨 위에 보이고, 그래프에서 사라졌으면 그렇게 적는다(값을 몰래 바꾸지 않음). */
export function TargetSelect({ value, c, label, known, onChange }) {
  const listed = !value || c.targets.some((t) => t.ref === value);
  const cur = !listed ? (known && known[value]) || { ref: value, label: value, missing: false } : null;
  return html`<select class="textbox" aria-label=${label} value=${value} onChange=${(x) => onChange(x.target.value)}>
    ${cur ? html`<option value=${value} key=${"cur:" + value}>${cur.label}${cur.missing ? GONE : " (지금 값)"}</option>` : null}
    <option value="">대상 없음</option>
    ${c.targets.map((t) => html`<option value=${t.ref} key=${t.ref}>${t.label}${t.in_node ? "" : " (다른 구간)"}</option>`)}</select>`;
}

/** 보호수단 한 줄의 구현 대상 여럿: 다 보이고, 하나씩 바꾸거나 빼고 더한다. */
function SgTargets({ r, i, c, known, onChange }) {
  const set = (j, v) => onChange(r.refs.map((x, k) => (k === j ? v : x)));
  return html`<div class="sg-targets" role="group" aria-label=${"구현 대상 " + (i + 1)}>
    ${r.refs.map((ref, j) => html`<span class="acts-row" key=${j}><${TargetSelect} value=${ref} c=${c} known=${known} label=${"구현 대상 " + (i + 1) + "-" + (j + 1)} onChange=${(v) => set(j, v)} />
      <${Btn} sm=${true} kind="ghost" label=${"구현 대상 " + (i + 1) + "-" + (j + 1) + " 빼기"} onClick=${() => onChange(r.refs.filter((_x, k) => k !== j))}>×<//></span>`)}
    <${Btn} sm=${true} kind="ghost" label=${"구현 대상 " + (i + 1) + " 더하기"} onClick=${() => onChange(r.refs.concat([""]))}>+ 대상<//></div>`;
}

/** '수정' 칸에 더하는 원인 유형·비완화·원인 위치·영향 대상·보호수단 편집. 보호수단·참조가 많아도 칸 카드 안에서 접힌다. */
export function EditMore({ st, setSt, c, id }) {
  const [open, setOpen] = useState(true);
  const put = (k, v) => setSt(Object.assign({}, st, { [k]: v }));
  const row = (k, i, patch) => put(k, st[k].map((r, j) => (j === i ? Object.assign({}, r, patch) : r)));
  const drop = (k, i) => put(k, st[k].filter((_r, j) => j !== i));
  return html`<div class="edit-more">
    <button type="button" class="linkish small" aria-expanded=${open ? "true" : "false"} onClick=${() => setOpen(!open)}>원인 위치·결과 기준·보호수단 ${open ? "▾" : "▸"}</button>
    ${open ? html`<div class="editgrid">
      <label>원인 유형<select class="textbox" aria-label="원인 유형" value=${st.cause_kind} onChange=${(x) => put("cause_kind", x.target.value)}><option value="">미확인</option>
        ${Object.keys(c.cause_kinds).map((k) => html`<option value=${k} key=${k}>${c.cause_kinds[k]}</option>`)}</select></label>
      <label class="chk"><input type="checkbox" aria-label="비완화 결과" checked=${st.basis} onChange=${(x) => put("basis", x.target.checked)} /> 보호수단이 모두 실패했다고 보고 쓴 결과(비완화)</label></div>
    <div class="sub-h small">원인 위치</div>
    ${st.causeRefs.map((r, i) => html`<div class="acts-row" key=${"c" + i}><${TargetSelect} value=${r.ref} c=${c} known=${st.known} label=${"원인 위치 " + (i + 1)} onChange=${(v) => row("causeRefs", i, { ref: v })} />
      <input class="textbox fm" aria-label=${"고장모드 " + (i + 1)} placeholder="고장모드(예: FTO)" maxlength="40" value=${r.failure_mode || ""} onInput=${(x) => row("causeRefs", i, { failure_mode: x.target.value })} />
      <${Btn} sm=${true} kind="ghost" label=${"원인 위치 " + (i + 1) + " 빼기"} onClick=${() => drop("causeRefs", i)}>빼기<//></div>`)}
    <${Btn} sm=${true} kind="ghost" label="원인 위치 더하기" onClick=${() => put("causeRefs", st.causeRefs.concat([{ i0: null, ref: "", failure_mode: "" }]))}>+ 원인 위치<//>
    <div class="sub-h small">영향 대상</div>
    ${st.consRefs.map((r, i) => html`<div class="acts-row" key=${"q" + i}><${TargetSelect} value=${r.ref} c=${c} known=${st.known} label=${"영향 대상 " + (i + 1)} onChange=${(v) => row("consRefs", i, { ref: v })} />
      <${Btn} sm=${true} kind="ghost" label=${"영향 대상 " + (i + 1) + " 빼기"} onClick=${() => drop("consRefs", i)}>빼기<//></div>`)}
    <${Btn} sm=${true} kind="ghost" label="영향 대상 더하기" onClick=${() => put("consRefs", st.consRefs.concat([{ i0: null, ref: "" }]))}>+ 영향 대상<//>
    <div class="sub-h small">보호수단</div>
    ${st.sg.map((r, i) => html`<div class="acts-row sg-row" key=${"g" + i}>
      <input class="textbox" aria-label=${"보호수단 " + (i + 1)} maxlength="500" value=${r.text} onInput=${(x) => row("sg", i, { text: x.target.value })} />
      <select class="textbox" aria-label=${"역할 " + (i + 1)} value=${r.role} onChange=${(x) => row("sg", i, { role: x.target.value })}>${Object.keys(c.roles).map((k) => html`<option value=${k} key=${k}>${c.roles[k]}</option>`)}</select>
      <select class="textbox" aria-label=${"작동 방식 " + (i + 1)} value=${r.actuation} onChange=${(x) => row("sg", i, { actuation: x.target.value })}>${Object.keys(c.actuations).map((k) => html`<option value=${k} key=${k}>${c.actuations[k]}</option>`)}</select>
      <${SgTargets} r=${r} i=${i} c=${c} known=${st.known} onChange=${(v) => row("sg", i, { refs: v })} />
      <${Btn} sm=${true} kind="ghost" label=${"보호수단 " + (i + 1) + " 빼기"} onClick=${() => drop("sg", i)}>빼기<//></div>`)}
    <${Btn} sm=${true} kind="ghost" label="보호수단 더하기" onClick=${() => put("sg", st.sg.concat([{ i0: null, text: "", role: "unknown", actuation: "unknown", refs: [] }]))}>+ 보호수단<//>` : null}</div>`;
}
