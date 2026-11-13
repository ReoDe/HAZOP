// 설계 문서 패널(완료 목록 2 A7): 설계 문서 PDF를 등록하고 지식 추출을 돌린 결과를 문서별로 본다(뽑힌 항목 수·상태·도면에 이어진 수·읽을 수 없는 사유).
// 뽑힌 항목은 모두 '자동 추출 · 사람 확인 전'이다. 문서 안의 글은 자료일 뿐이라 ${}로만 넣는다. 지식그래프 패널(A6)에서 도면 구성요소와 이어져 보인다.
import { html } from "../ui/html.js";
import { store, useStore } from "../store.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import * as D from "./docs_state.js";

const cssHref = new URL("docs.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector("link[data-docs-css]")) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-docs-css", "");
  document.head.appendChild(l);
}

const STATE = { ok: ["추출함", "ok"], pending: ["추출 전", "warn"], blocked: ["읽을 수 없음", "err"], failed: ["등록 실패", "err"] };
const TYPE = { setpoint: "설정치", condition: "운전조건", requirement: "요건" };

function Counts({ d, labels }) {
  if (d.state !== "ok") return null;
  return html`<div class="acts-row docs-counts">${labels.map((l) => html`<${Chip} key=${l.id}>${l.label} ${d.counts[l.id] || 0}<//>`)}
    <${Chip} kind=${d.linked_links ? "accent" : ""} title="지식그래프에서 이 문서의 항목과 도면 구성요소를 잇는 관계 수(언급·적용·설정치). 문장 속 태그가 도면에 있어야 이어집니다">도면에 이어짐 ${d.linked_nodes}<//>
    ${d.unknowns ? html`<${Chip} kind="warn" title="단위나 압력 기준을 읽지 못한 값">미확인 값 ${d.unknowns}<//>` : null}</div>`;
}

function Items({ detail, id }) {
  if (!detail) return html`<div class="muted small">불러오는 중…</div>`;
  if (!detail.items.length) return html`<div class="muted small">뽑힌 설정치·운전조건·요건이 없습니다.</div>`;
  return html`<div class="list" role="list" aria-label="뽑힌 항목">${detail.items.map((i) => html`<div class="row docs-item" role="listitem" key=${i.id}>
    <span class="main"><b>${TYPE[i.type] || i.type}${i.item ? " · " + i.item : ""}${i.value ? " " + i.value + (i.unit ? " " + i.unit : "") + (i.basis ? " (" + i.basis + ")" : "") : ""}</b>
      <span>${i.text}</span><span class="muted small">${i.locator || ""} · 자동 추출 · 사람 확인 전</span></span>
    <${Btn} sm=${true} kind="ghost" icon="route" label=${"지식그래프에서 보기 " + i.id} title=${i.linked ? "도면 구성요소와 이어진 항목" : "지식그래프에서 보기"} onClick=${() => D.showInGraph(i.id)}>${i.linked ? "도면과 이어짐" : "그래프"}<//></div>`)}
    ${detail.items_total > detail.items.length ? html`<div class="muted small">나머지 ${detail.items_total - detail.items.length}개는 지식그래프에서 보세요.</div>` : null}</div>`;
}

function DocRow({ d, labels }) {
  const busy = D.useDocs((s) => s.busy);
  const active = D.useDocs((s) => s.active);
  const detail = D.useDocs((s) => s.detail);
  const st = STATE[d.state] || [d.state, ""];
  const open = active === d.material_id;
  return html`<div class="card docs-doc" key=${d.material_id}>
    <div class="nd-h"><b class="docs-name">${d.title || d.name}</b><${Chip} kind=${st[1]}>${st[0]}<//>
      <span class="muted small">${d.name !== d.title ? d.name + " · " : ""}등록 버전 ${d.version}${d.pages ? " · " + d.pages + "쪽" : ""}</span></div>
    <${Counts} d=${d} labels=${labels} />
    ${d.reasons.length ? html`<${Notice} kind="err" icon="alert-triangle"><b>${d.state === "failed" ? "등록하지 못한 이유" : "추출하지 못한 이유"}</b><ul class="tight">${d.reasons.map((r, i) => html`<li key=${i}>${r}</li>`)}</ul><//>` : null}
    ${d.state === "pending" ? html`<div class="muted small">등록은 됐지만 아직 지식 추출을 하지 않았습니다.</div>` : null}
    <div class="acts-row">
      ${d.state === "ok" ? html`<${Btn} sm=${true} label=${"뽑힌 항목 " + (open ? "접기" : "보기") + " " + (d.title || d.name)} onClick=${() => D.toggleItems(d.material_id)}>${open ? "항목 접기" : "뽑힌 항목 보기"}<//>
        <${Btn} sm=${true} icon="route" label="지식그래프에서 보기" onClick=${() => D.showInGraph(null)}>지식그래프에서 보기<//>` : null}
      ${d.state !== "failed" ? html`<${Btn} sm=${true} icon="refresh" label=${"추출 다시 하기 " + (d.title || d.name)} disabled=${busy} onClick=${() => D.extractAgain(d.material_id)}>추출 다시 하기<//>` : null}</div>
    ${open ? html`<${Items} detail=${detail} id=${d.material_id} />` : null}</div>`;
}

export function DocsPanel({ onClose }) {
  D.wire();
  const s = D.useDocs((x) => x.summary);
  const loaded = D.useDocs((x) => x.loaded);
  const kind = D.useDocs((x) => x.kind);
  const busy = D.useDocs((x) => x.busy);
  const error = D.useDocs((x) => x.error);
  const notice = D.useDocs((x) => x.notice);
  const running = useStore((x) => Object.values(x.jobs || {}).filter((j) => j.state === "running"));
  const t = s.totals;
  return html`<section class="panel wide docs" aria-label="설계 문서">
    <div class="panel-h"><h2>설계 문서</h2><span class="muted small">프로젝트 ${s.project_id || ""}</span>
      <span class="acts"><${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <div class="acts-row docs-head">
        <label class="small">자료 종류
          <select class="docs-kind" aria-label="자료 종류" value=${kind} onChange=${(e) => D.setKind(e.target.value)}>
            ${(s.kinds.length ? s.kinds : [{ id: "design_document", label: "설계 문서 (PDF)" }]).map((k) => html`<option key=${k.id} value=${k.id}>${k.label}</option>`)}</select></label>
        <${Btn} kind="primary" icon="upload" label="설계 문서 PDF 고르기" disabled=${busy} onClick=${D.addDocuments}>설계 문서 PDF 고르기<//>
        <span class="muted small">고르면 등록하고 설정치·운전조건·요건을 자동으로 뽑아 지식그래프에 더합니다(AI 호출 없음). 도면은 도면 패널에서 등록하세요.</span></div>
      ${running.length ? html`<${Notice} kind="info" icon="loader-2">진행 중: ${running.map((j) => (j.label || "") + (j.text ? " · " + j.text : "")).join(", ")}<//>` : null}
      ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${D.dismissError}>닫기<//><//>` : null}
      ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice}<//>` : null}
      ${t.docs ? html`<div class="acts-row"><${Chip}>문서 ${t.docs}<//><${Chip} kind="ok">추출함 ${t.ok}<//>${t.problems ? html`<${Chip} kind="err">문제 ${t.problems}<//>` : null}<${Chip}>뽑힌 항목 ${t.items}<//>
        ${s.has_kg ? null : html`<${Chip} kind="warn">지식그래프 없음<//>`}</div>` : null}
      ${!loaded ? html`<div class="muted">불러오는 중…</div>` : t.docs ? s.docs.map((d) => html`<${DocRow} d=${d} labels=${s.count_labels} key=${d.material_id} />`)
        : html`<div class="center-empty"><p>등록한 설계 문서가 없습니다. 설계 설명서 같은 글자 PDF를 고르면 지식을 뽑아 도면과 이어 줍니다. 스캔 PDF는 지원하지 않습니다.</p></div>`}
    </div></section>`;
}
