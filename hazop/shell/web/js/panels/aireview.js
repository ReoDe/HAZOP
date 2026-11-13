// AI 검토 후보 패널(INTENT.md §3.2, 완료 목록 2 A4): 도면 고르기 · 도면별 예상 호출 수와 상한 · 실행 · 확신 높은 묶음 수락 · 할 일별(못 읽은 기호의 종류,
// 태그·속성, 끊긴 연결, 다시 확인) 후보 목록과 낱개 수락·거절·되돌리기. 후보를 누르면 도면의 그 자리로 가서 강조한다.
// 저장하는 자료는 엔진만 쓰고 여기서는 보여 주고 명령만 보낸다. 모델이 쓴 글(근거·값)은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import * as A from "./aireview_state.js";

const STATUS_KIND = { proposed: "ai", accepted: "ok", rejected: "plain" };

function Estimate() {
  const est = A.useAi((s) => s.estimate);
  const gid = A.useAi((s) => s.graphId);
  const cap = A.useAi((s) => s.cap);
  const busy = A.useAi((s) => s.busy);
  const ov = A.useAi((s) => s.overview);
  const page = est && est.pages.find((p) => p.graph_id === gid);
  const minutes = (calls) => Math.max(1, Math.round(calls * (ov.seconds_per_call || 30) / 60));
  return html`<div class="card ai-est"><h3>AI 검토 실행</h3>
    <div class="kv"><div class="k"><b>도면당 호출 상한</b><span>한 번 실행에 최대 ${ov.run_cap}회까지 부릅니다. 구독 한도를 씁니다.</span></div>
      <input type="number" min="1" max="200" value=${cap || ov.cap} aria-label="도면당 호출 상한" class="ai-cap"
        onChange=${(e) => A.setCap(parseInt(e.target.value, 10))} /></div>
    ${page ? html`<div class="small" aria-live="polite">이 도면: 물을 곳 ${page.items}개 · 예상 호출 <b>${page.calls}회</b>${page.needed > page.calls ? html` <span class="ai-warn">(다 보려면 ${page.needed}회, 상한에서 멈춤)</span>` : null} · 약 ${minutes(page.calls)}분</div>` : null}
    ${est ? html`<div class="muted small">프로젝트 전체 ${est.pages.length}장: 예상 호출 ${est.calls}회${est.capped ? " (상한에 걸림)" : ""}</div>` : null}
    <div class="acts-row"><${Btn} sm=${true} icon="sparkles" label="이 도면 AI 검토 실행" disabled=${busy || !gid || (page && page.calls === 0)} onClick=${A.run}>이 도면 AI 검토<//></div></div>`;
}

function Bulk({ v }) {
  const asking = A.useAi((s) => s.asking);
  const busy = A.useAi((s) => s.busy);
  if (!v.bulk.length) return html`<div class="muted small">확신 높은 묶음이 없습니다. 후보를 하나씩 보세요.</div>`;
  return html`<div class="ai-bulk" aria-label="확신 높은 묶음">${v.bulk.map((b) => asking === b.task
    ? html`<div class="ai-ask" key=${b.task} role="group" aria-label=${b.label + " 묶음 수락 확인"}><span>${b.label} 후보 ${b.count}건을 한 번에 수락합니다. 수락한 뒤에도 하나씩 되돌릴 수 있습니다.</span>
        <${Btn} sm=${true} kind="primary" label=${b.label + " " + b.count + "건 수락"} disabled=${busy} onClick=${() => A.acceptBulk(b.task)}>수락<//>
        <${Btn} sm=${true} kind="ghost" label="취소" onClick=${() => A.ask(null)}>취소<//></div>`
    : html`<${Btn} key=${b.task} sm=${true} icon="circle-check" label=${"확신 높은 " + b.label + " " + b.count + "건 묶어 수락"} disabled=${busy} onClick=${() => A.ask(b.task)}>${b.label} ${b.count}건 묶어 수락<//>`)}
    <span class="muted small">확신도 ${v.threshold} 이상(기호 종류는 ${v.kind_threshold} 이상이고 이웃 기호에 붙지 않은 것)만 묶습니다.</span></div>`;
}

function Row({ r }) {
  const busy = A.useAi((s) => s.busy);
  const picked = A.useAi((s) => s.picked);
  const alt = r.values.slice(1);
  return html`<div class=${"row ai-row" + (picked === r.cand_id ? " on" : "")} role="listitem">
    <button type="button" class="ai-main" aria-label=${r.field_label + " 후보 " + r.values[0] + " 도면에서 보기"} title="도면에서 이 자리 보기" onClick=${() => A.showOnSheet(r)}>
      <b>${r.field_label} <span class="ai-cur">${r.current || "없음"}</span> → <span class="ai-val">${r.values[0]}</span>${alt.length ? html` <span class="muted small">(차선 ${alt.join(", ")})</span>` : null}</b>
      <span>${r.reason || "근거 없음"}</span>
      ${r.status === "proposed" && r.bulk_block ? html`<span class="muted small">하나씩 볼 것: ${r.bulk_block}</span>` : null}</button>
    <${Chip} title="AI 확신도">${r.confidence.toFixed(2)}<//>
    <${Chip} kind=${STATUS_KIND[r.status]}>${r.status_label}<//>
    <span class="acts">${r.status === "proposed" ? html`
      <${Btn} sm=${true} kind="primary" label=${r.field_label + " " + r.values[0] + " 수락"} disabled=${busy} onClick=${() => A.accept(r.cand_id)}>수락<//>
      <${Btn} sm=${true} label=${r.field_label + " " + r.values[0] + " 거절"} disabled=${busy} onClick=${() => A.reject(r.cand_id)}>거절<//>`
      : html`<${Btn} sm=${true} icon="arrow-back-up" label=${r.field_label + " " + r.values[0] + " 되돌리기"} disabled=${busy} onClick=${() => A.revert(r.cand_id)}>되돌리기<//>`}</span></div>`;
}

export function AiReviewPanel({ onClose }) {
  A.wire();
  const ov = A.useAi((s) => s.overview);
  const gid = A.useAi((s) => s.graphId);
  const v = A.useAi((s) => s.view);
  const error = A.useAi((s) => s.error);
  const notice = A.useAi((s) => s.notice);
  const c = v.counts || {};
  const last = v.last_run;
  return html`<section class="panel wide aireview" aria-label="AI 검토 후보">
    <div class="panel-h"><h2>AI 검토 후보</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      ${ov.drawings.length === 0 ? html`<${Notice}>도면이 없습니다. 도면을 먼저 등록하세요.<//>` : html`
      <div class="acts-row"><label class="small" for="ai-sheet">도면</label>
        <select id="ai-sheet" class="ai-sheet" value=${gid || ""} onChange=${(e) => A.pickDrawing(e.target.value)}>
          ${ov.drawings.map((d) => html`<option key=${d.graph_id} value=${d.graph_id}>${d.drawing_number}${d.proposed ? " · 남은 후보 " + d.proposed : ""}</option>`)}</select>
        ${v.available ? html`<${Chip} kind="ai">남은 ${c.proposed || 0}<//><${Chip} kind="ok">수락 ${c.accepted || 0}<//><${Chip}>거절 ${c.rejected || 0}<//>` : null}</div>
      ${last ? html`<div class="muted small">마지막 실행: 호출 ${last.calls ?? "-"}회 · 묻지 못한 곳 ${last.left ?? "-"}${last.not_symbol ? " · 기호 아님 " + last.not_symbol : ""}${last.halted ? " · 오류로 멈춤" : last.stopped ? " · 중지함" : ""}</div>` : null}
      <div class="muted small">후보는 추출 결과를 바꾸지 않습니다. 수락한 것만 도면 수정 기록에 들어가 그래프에 바로 반영되고, 되돌릴 수 있습니다.</div>
      ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${A.dismiss}>닫기<//><//>` : null}
      ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice}<//>` : null}
      <${Estimate} />
      ${!v.available ? html`<${Notice}>${v.reason || "AI 후보가 없습니다."}<//>` : html`
        <${Bulk} v=${v} />
        ${v.groups.map((g) => html`<div class="ai-group" key=${g.task}><h3>${g.label} <span class="muted small">${g.proposed}/${g.items.length}</span></h3>
          <div class="list" role="list" aria-label=${g.label}>${g.items.map((r) => html`<${Row} key=${r.cand_id} r=${r} />`)}</div></div>`)}`}`}
    </div></section>`;
}
