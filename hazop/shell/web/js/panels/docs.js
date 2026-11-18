// 설계 문서 패널(완료 목록 2 A7): 설계 문서 PDF를 등록하면 설정치·운전조건·요건을 뽑아 지식그래프에 더한다. 화면은 단순하게 둔다:
// 머리에 고르기 단추 하나, 문서마다 한 줄 요약과 꼭 필요한 알림(읽을 수 없음, 지식그래프 반영 전, 옛 판, 같은 문서의 새 판인지 물음)만.
// 뽑힌 항목은 모두 '자동 추출 · 사람 확인 전'이다. 문서 안의 글은 자료일 뿐이라 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { useStore } from "../store.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import * as D from "./docs_state.js";

const cssHref = new URL("docs.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector("link[data-docs-css]")) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-docs-css", "");
  document.head.appendChild(l);
}

const STATE = { pending: ["추출 전", "warn"], blocked: ["읽을 수 없음", "err"], failed: ["등록 실패", "err"] };
const TYPE = { setpoint: "설정치", condition: "운전조건", requirement: "요건" };

function summaryLine(d) {
  const c = d.counts;
  const link = d.linked_candidate || d.linked_confirmed
    ? " · 도면과 이어짐 후보 " + d.linked_candidate + (d.linked_confirmed ? " · 확정 " + d.linked_confirmed : "")
    : " · 도면과 이어진 것 없음";
  return "설정치 " + c.setpoint + " · 운전조건 " + c.condition + " · 요건 " + c.requirement + link;
}

function Items({ detail }) {
  if (!detail) return html`<div class="muted small">불러오는 중…</div>`;
  if (!detail.items.length) return html`<div class="muted small">뽑힌 설정치·운전조건·요건이 없습니다.</div>`;
  return html`<div class="docs-items" role="list" aria-label="뽑힌 항목">${detail.items.map((i) => html`<div class="docs-item" role="listitem" key=${i.id}>
    <div class="main"><b>${TYPE[i.type] || i.type}${i.item ? " · " + i.item : ""}${i.value ? " " + i.value + (i.unit ? " " + i.unit : "") + (i.basis ? " (" + i.basis + ")" : "") : ""}</b>
      <span>${i.text}</span><span class="muted small">${i.locator || ""}</span></div>
    <${Btn} sm=${true} kind="ghost" label=${"지식그래프에서 보기 " + i.id} title="지식그래프에서 보기" onClick=${() => D.showInGraph(i.id)}>${i.linked ? "도면과 이어짐" : "그래프"}<//></div>`)}
    ${detail.items_total > detail.items.length ? html`<div class="muted small">나머지 ${detail.items_total - detail.items.length}개는 지식그래프에서 보세요.</div>` : null}
    <div class="muted small">뽑힌 항목은 자동 추출이라 사람 확인 전입니다.</div></div>`;
}

function Ask({ d }) {
  const busy = D.useDocs((s) => s.busy);
  const [old, setOld] = useState(d.ask_revision[0].material_id);
  return html`<div class="docs-ask"><span>같은 문서의 새 판인가요?</span>
    ${d.ask_revision.length > 1 ? html`<select aria-label="옛 판 고르기" value=${old} onChange=${(e) => setOld(e.target.value)}>
      ${d.ask_revision.map((c) => html`<option key=${c.material_id} value=${c.material_id}>${c.title}</option>`)}</select>`
      : html`<span class="muted">옛 판: ${d.ask_revision[0].title}</span>`}
    <${Btn} sm=${true} kind="primary" label="새 판으로 지정" disabled=${busy} onClick=${() => D.answerRevision(d.material_id, "replace", old)}>새 판으로<//>
    <${Btn} sm=${true} label="다른 문서로 두기" disabled=${busy} onClick=${() => D.answerRevision(d.material_id, "separate")}>다른 문서<//></div>`;
}

function DocRow({ d }) {
  const busy = D.useDocs((s) => s.busy);
  const active = D.useDocs((s) => s.active);
  const detail = D.useDocs((s) => s.detail);
  const open = active === d.material_id;
  const st = STATE[d.state];
  const meta = [d.doc_number, d.revision != null ? "개정 " + d.revision : null, d.pages ? d.pages + "쪽" : null].filter(Boolean).join(" · ");
  return html`<div class=${"docs-doc" + (d.replaced_by ? " old" : "")} key=${d.material_id}>
    <div class="docs-top"><b class="docs-name">${d.title}</b>
      ${st ? html`<${Chip} kind=${st[1]}>${st[0]}<//>` : null}
      ${d.replaced_by ? html`<${Chip} title=${d.replaced_by.reason || ""}>옛 판<//>` : d.state === "ok" && !d.in_kg ? html`<${Chip} kind="warn" title="지금 지식그래프에 이 판의 지식이 들어 있지 않습니다">지식그래프 반영 전<//>` : null}
      <span class="docs-acts">
        ${d.state === "ok" ? html`<${Btn} sm=${true} kind="ghost" label=${(open ? "항목 접기 " : "뽑힌 항목 보기 ") + d.title} onClick=${() => D.toggleItems(d.material_id)}>${open ? "접기" : "항목"}<//>` : null}
        ${d.state !== "failed" ? html`<${Btn} sm=${true} kind="ghost" icon="refresh" label=${"추출 다시 하기 " + d.title} title="추출 다시 하기" disabled=${busy} onClick=${() => D.extractAgain(d.material_id)} />` : null}</span></div>
    <div class="muted small">${meta || d.name}${d.replaced_by ? " · " + d.replaced_by.title + "이(가) 대신함" : ""}</div>
    ${d.state === "ok" && !d.replaced_by ? html`<div class="small">${summaryLine(d)}</div>` : null}
    ${d.reasons.length ? html`<div class="small err-text">${d.reasons.join(" · ")}</div>` : null}
    ${d.ask_revision.length ? html`<${Ask} d=${d} />` : null}
    ${open ? html`<${Items} detail=${detail} />` : null}</div>`;
}

function KgBand({ kg }) {
  const out = [];
  if (kg.build_error) out.push(html`<${Notice} kind="err" icon="alert-triangle" key="b">지식그래프를 다시 만들지 못했습니다: ${kg.build_error}. 문서의 '추출 다시 하기'로 다시 만드세요.<//>`);
  if (kg.state === "unreadable" || kg.state === "blocked") out.push(html`<${Notice} kind="warn" icon="alert-triangle" key="s">${kg.text}<//>`);
  (kg.recheck || []).forEach((t, i) => out.push(html`<${Notice} kind="warn" icon="alert-triangle" key=${"r" + i}>${t}<//>`));
  return out;
}

export function DocsPanel({ onClose }) {
  D.wire();
  const s = D.useDocs((x) => x.summary);
  const loaded = D.useDocs((x) => x.loaded);
  const busy = D.useDocs((x) => x.busy);
  const error = D.useDocs((x) => x.error);
  const notice = D.useDocs((x) => x.notice);
  const running = useStore((x) => Object.values(x.jobs || {}).filter((j) => j.state === "running"));
  return html`<section class="panel wide docs" aria-label="설계 문서">
    <div class="panel-h"><h2>설계 문서</h2>
      <span class="acts"><${Btn} sm=${true} kind="primary" icon="upload" label="설계 문서 PDF 고르기" disabled=${busy} onClick=${D.addDocuments}>PDF 고르기<//>
        <${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      ${running.length ? html`<div class="muted small">진행 중: ${running.map((j) => (j.label || "") + (j.text ? " · " + j.text : "")).join(", ")}</div>` : null}
      ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${D.dismissError}>닫기<//><//>` : null}
      ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${D.dismissNotice}>닫기<//><//>` : null}
      <${KgBand} kg=${s.kg} />
      ${!loaded ? html`<div class="muted">불러오는 중…</div>` : s.docs.length ? html`<div class="docs-list">${s.docs.map((d) => html`<${DocRow} d=${d} key=${d.material_id} />`)}</div>`
        : html`<div class="center-empty"><p>설계 설명서 같은 글자 PDF를 고르면 설정치·운전조건·요건을 뽑아 도면과 이어 줍니다. AI는 쓰지 않으며 스캔 PDF는 읽지 못합니다.</p></div>`}
    </div></section>`;
}
