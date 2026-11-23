// 검토 대기열의 오른쪽 칸 카드와 위 막대 진행 줄(규격 HZ-DSN-06 §3.3). 대기열을 연 동안 채팅 자리에 이 카드가 오고, 닫으면 채팅이 그대로 돌아온다.
import { html } from "../ui/html.js";
import { useEffect, useRef } from "../../vendor/hooks.module.js";
import { Icon } from "../ui/icon.js";
import * as Q from "./queue.js";
import { go as goNext, useNext } from "../next/next.js";

const TITLE = { "ai": "AI 후보 검토", "lost": "다시 확인" };

function pct(c, n) { return n ? Math.round(100 * (n - c.open) / n) : 0; }

/** 위 막대 가운데: "AI 후보 검토 · 12건 중 3번째", 진행 막대, [끝내기 Esc]. */
export function QueueLine() {
  const s = Q.useQueue((x) => x);
  const n = s.items.length, c = Q.counts(s);
  return html`<div class="next" id="next"><div class="line info" role="status">
    <${Icon} name=${s.kind === "ai" ? "sparkles" : "alert-triangle"} size=${15} />
    <span class="txt">${s.gid && s.items[0] ? s.items[0].sheet + " " : ""}${TITLE[s.kind]} · ${s.done ? "끝" : n + "건 중 " + (s.i + 1) + "번째"}</span>
    <span class="bar"><i style=${"width:" + pct(c, n) + "%"}></i></span>
    <button type="button" class="btn sm" aria-keyshortcuts="Escape" onClick=${Q.closeQueue}>끝내기 Esc</button></div></div>`;
}

function Progress({ s }) {
  const n = s.items.length, c = Q.counts(s);
  return html`<div class="qprog"><div class="row"><b>${s.done ? "모두 봤습니다" : n + "건 중 " + (s.i + 1) + "번째"}</b>
    <span class="muted">수락 ${c.accepted} · 거절 ${c.rejected} · 건너뜀 ${c.skipped}</span></div>
    <span class="bar"><i style=${"width:" + pct(c, n) + "%"}></i></span></div>`;
}

function AiBody({ it, s }) {
  const box = useRef(null);
  const editing = s.editing !== null;
  // E: 입력칸으로 포커스를 옮긴다(autofocus 속성은 다른 단추가 포커스를 쥐고 있으면 먹지 않는다. 실제 창 결함 1)
  useEffect(() => { if (editing && box.current) { box.current.focus(); box.current.select(); } }, [editing, it.qid]);
  return html`<div class="qbody">
    <div class="chips"><span class="chip ai">AI 후보</span><span class="chip">${it.task}</span>${it.match_label ? html`<span class="chip">범례 일치 ${it.match_label}</span>` : null}</div>
    <div class="target"><b>${it.label}</b><span class="muted">${it.sheet} · ${it.field_label}</span></div>
    <div class="change"><span class="now">${it.now}</span><${Icon} name="chevron-right" size=${16} /><span class="to">${it.proposal}</span></div>
    <div class="conf">확신 ${Math.round((it.confidence || 0) * 100)}%</div>
    ${it.why ? html`<div class="why"><span class="muted">AI가 본 것</span>${it.why}</div>` : null}
    ${s.editing !== null ? html`<div class="edit">
      <input type="text" class="qedit" ref=${box} value=${s.editing} aria-label=${it.field_label + " 고쳐 쓰기"}
        onInput=${(e) => Q.setEditing(e.target.value)}
        onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); Q.saveEdit(); } if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); Q.cancelEdit(); } }} />
      ${s.ask ? html`<div class="ask">${s.ask} 그래도 저장하려면 Enter를 한 번 더 누르세요.</div>` : html`<div class="muted small">Enter 저장 · Esc 취소</div>`}</div>` : null}
  </div>`;
}

function LostBody({ it }) {
  return html`<div class="qbody">
    <div class="chips"><span class="chip warn">찾지 못한 구성요소</span></div>
    <div class="target"><b>${it.label}</b><span class="muted">${it.sheet || "도면을 알 수 없음"}</span></div>
    <div class="why"><span class="muted">걸린 곳</span>검토구간 ${it.node_name}</div>
    <div class="muted small">다시 추출한 도면에서 같은 구성요소를 찾지 못했습니다. 거절하면 지워진 것으로 두고 이 구간에서 뺍니다.</div>
    ${it.held ? html`<div class="ask">확정한 구간입니다. 거절하려면 구간 확정을 먼저 해제하세요.</div>` : null}
  </div>`;
}

function BulkBox({ s }) {
  const rows = Q.bulkItems(s);
  if (s.bulkAsk) {
    return html`<div class="qbulk open" role="dialog" aria-label="한 번에 수락할 후보"><b>${rows.length}건을 한 번에 수락할까요?</b>
      <ul>${rows.slice(0, 12).map((x) => html`<li key=${x.qid}>${x.label} · ${x.field_label}: ${x.now} → ${x.proposal} <span class="muted">${Math.round(x.confidence * 100)}%</span></li>`)}
      ${rows.length > 12 ? html`<li class="muted">그 밖에 ${rows.length - 12}건</li>` : null}</ul>
      <div class="acts"><button type="button" class="btn primary" onClick=${Q.confirmBulk}>모두 수락 Enter</button><button type="button" class="btn" onClick=${Q.cancelBulk}>취소 Esc</button></div></div>`;
  }
  if (s.kind !== "ai" || !rows.length) return null;
  return html`<div class="qbulk"><span>확신 높은 후보 ${rows.length}건</span><button type="button" class="btn sm" aria-keyshortcuts="Shift+A" onClick=${Q.askBulk}>목록 보고 한 번에 수락 Shift+A</button></div>`;
}

function Done({ s }) {
  const c = Q.counts(s);
  const top = useNext((x) => x.items[0] || null);
  return html`<div class="qdone"><${Icon} name="circle-check" size=${28} /><b>모두 봤습니다</b>
    <div>수락 ${c.accepted} · 거절 ${c.rejected} · 건너뜀 ${c.skipped}</div>
    ${c.skipped ? html`<button type="button" class="btn" onClick=${Q.reviewSkipped}>건너뛴 ${c.skipped}건 다시 보기</button>` : null}
    ${top && top.kind !== "none" && !c.skipped ? html`<div class="qnext"><span class="muted small">다음에 할 일</span><span>${top.text}</span>
      <button type="button" class="btn primary" onClick=${() => { Q.closeQueue(); goNext(top.action); }}>${top.action.label}</button></div>` : null}
    <button type="button" class=${"btn" + (top && top.kind !== "none" && !c.skipped ? "" : " primary")} onClick=${Q.closeQueue}>끝내기</button>
    ${s.undo.length ? html`<div class="muted small">Z를 누르면 바로 앞 판정을 되돌립니다.</div>` : null}</div>`;
}

/** 오른쪽 칸(채팅 자리)의 카드. 머리의 말풍선 단추는 대기열을 닫고 채팅으로 돌아간다. */
export function QueueCard({ onChat }) {
  const s = Q.useQueue((x) => x);
  const it = Q.current(s);
  return html`<aside class="chat queue" tabindex="-1" aria-label=${TITLE[s.kind] + " 대기열"}>
    <div class="chat-h"><${Icon} name=${s.kind === "ai" ? "sparkles" : "alert-triangle"} /><b>${TITLE[s.kind]}</b>
      <span class="acts"><button type="button" class="btn ghost icon" title="채팅으로 (Ctrl+K)" aria-label="채팅으로" onClick=${onChat}><${Icon} name="message-circle" size=${16} /></button></span></div>
    <div class="qwrap">
      <${Progress} s=${s} />
      ${s.done ? html`<${Done} s=${s} />` : it ? html`
        ${it.kind === "ai" ? html`<${AiBody} it=${it} s=${s} />` : html`<${LostBody} it=${it} />`}
        <div class="qacts">
          <button type="button" class="btn primary" disabled=${s.busy || it.kind === "lost"} aria-keyshortcuts="A" onClick=${Q.accept}><${Icon} name="check" size=${16} /> 수락 A</button>
          <button type="button" class="btn" disabled=${s.busy || it.held} aria-keyshortcuts="R" onClick=${Q.reject}><${Icon} name="x" size=${16} /> 거절 R</button>
          <button type="button" class="btn" disabled=${s.busy} aria-keyshortcuts="Space" onClick=${Q.skip}><${Icon} name="chevron-right" size=${16} /> 건너뛰기 Space</button></div>
        <div class="qsub">
          ${it.kind === "ai" ? html`<button type="button" class="btn sm" disabled=${s.busy || !it.edit_op} aria-keyshortcuts="E" onClick=${Q.startEdit}><${Icon} name="pencil" size=${14} /> 고쳐서 수락 E</button>` : null}
          <button type="button" class="btn sm" disabled=${s.busy || !s.undo.length} aria-keyshortcuts="Z" onClick=${Q.undo}><${Icon} name="arrow-back-up" size=${14} /> 되돌리기 Z</button></div>
        <${BulkBox} s=${s} />` : null}
      ${s.error ? html`<div class="qmsg err" role="alert">${s.error}</div>` : null}
      ${s.note ? html`<div class="qmsg" role="status">${s.note}</div>` : null}
      <div class="qkeys muted small">${s.kind === "ai" ? "A 수락 · R 거절 · Space 건너뛰기 · E 고쳐서 수락 · Shift+A 묶음 · Z 되돌리기 · Esc 끝" : "R 거절 · Space 건너뛰기 · Z 되돌리기 · Esc 끝"}</div>
    </div></aside>`;
}
