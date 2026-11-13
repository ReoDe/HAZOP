// 채팅이 제안한 쓰기 동작을 그린다(채팅 규격 §4, 앱 틀 규격 §2.3·시안 3번). 판정·실행은 엔진(hazop/shell/chat_actions.py)이 끝냈고,
// 여기는 받은 항목을 그리고 사람이 누르는 단추(확인 상자의 실행·하지 않음, '이 요청 되돌리기', '나머지도 나누기')를 엔진 명령으로 보낸다.
// 모델이 쓴 글(구간 이름 등)은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { cmd } from "../bridge.js";
import { store } from "../store.js";
import { Icon } from "../ui/icon.js";
import { Btn, Notice } from "../ui/parts.js";
import * as N from "../panels/nodes_state.js";

export const REST_QUESTION = "방금 만든 대표 구간을 참고해서 나머지 구간도 나눠 주세요.";

/** 항목 목록을 메시지로 받는다(chat.actions 사건). */
export function addActions(setChat, d) {
  setChat((c) => ({ msgs: [...c.msgs, { key: "act:" + d.answer_id, kind: "actions", answer_id: d.answer_id, items: d.items }] }));
}

/** 확인을 누른 뒤 한 항목의 결과(chat.action.result 사건): 같은 표의 항목을 바꾼다. */
export function updateAction(setChat, d) {
  setChat((c) => ({ msgs: c.msgs.map((m) => m.kind !== "actions" ? m
    : Object.assign({}, m, { items: m.items.map((it) => (it.token && it.token === d.token) ? d.item : it) })) }));
}

const ICON = { applied: "circle-check", candidate: "circle-check", confirm: "alert-triangle", rejected: "alert-triangle", failed: "alert-triangle",
  stale: "alert-triangle", declined: "x", duplicate: "info-circle" };

function ConfirmBox({ it }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function press(name) {
    setBusy(true); setErr("");
    try { await cmd(name, { token: it.token }); } catch (e) { setErr(e.message || "처리하지 못했습니다."); setBusy(false); }
  }
  return html`<div class="actbox confirm" role="group" aria-label=${"확인: " + it.title}>
    <div class="actbox-h"><${Icon} name="alert-triangle" size=${15} /><b>${it.title}</b></div>
    <p>${it.text}</p>
    ${it.waiting ? html`<div class="muted" style="font-size:var(--fs-xs)">앞의 확인이 끝나면 이어서 묻습니다.</div>` : html`
      <div class="acts-row">
        <${Btn} kind="primary" sm=${true} disabled=${busy} label="실행" onClick=${() => press("chat.action.approve")}>실행<//>
        <${Btn} sm=${true} disabled=${busy} label="하지 않음" onClick=${() => press("chat.action.decline")}>하지 않음<//></div>`}
    ${err ? html`<${Notice} kind="err" icon="alert-triangle">${err}<//>` : null}</div>`;
}

function AppliedBox({ it, onAsk }) {
  const [undone, setUndone] = useState(false);
  const [err, setErr] = useState("");
  const canUndo = it.action === "nodes.apply" && it.batch_id && it.status === "applied";
  async function undo() {
    setErr("");
    const r = await N.undo(it.batch_id);
    if (r) setUndone(true); else setErr(N.nodes.get().error || "되돌리지 못했습니다.");
  }
  const added = it.action === "nodes.apply" && /만들었습니다/.test(it.text);
  return html`<div class=${"actbox " + it.status} role="group" aria-label=${it.title}>
    <div class="actbox-h"><${Icon} name=${ICON[it.status] || "circle-check"} size=${15} /><b>${it.status === "candidate" ? "후보로 올림" : "적용함"}</b>
      ${it.batch_id ? html`<span class="chip id">묶음 ${it.batch_id}</span>` : null}</div>
    <p>${undone ? "묶음 " + it.batch_id + "을(를) 되돌렸습니다." : it.text}</p>
    ${undone ? null : html`<div class="acts-row">
      ${it.node_ids.length ? html`<${Btn} sm=${true} label="구간 보기" onClick=${() => { store.set({ panel: "nodes" }); N.focusNode(it.node_ids[0], { zoom: true }); }}>구간 보기<//>` : null}
      ${canUndo ? html`<${Btn} sm=${true} label="이 요청 되돌리기" onClick=${undo}>이 요청 되돌리기<//>` : null}
      ${added ? html`<${Btn} sm=${true} label="나머지도 나누기" onClick=${() => onAsk(REST_QUESTION)}>나머지도 나누기<//>` : null}</div>`}
    ${err ? html`<${Notice} kind="err" icon="alert-triangle">${err}<//>` : null}</div>`;
}

function PlainBox({ it }) {
  const kind = it.status === "declined" || it.status === "duplicate" ? "info" : "warn";
  const head = { rejected: "하지 않았습니다", failed: "실행하지 못했습니다", stale: "실행하지 않았습니다", declined: "실행하지 않았습니다", duplicate: "이미 처리했습니다" }[it.status] || it.title;
  return html`<${Notice} kind=${kind} icon=${ICON[it.status] || "info-circle"}><b>${it.title}</b> — ${head}${it.reason ? ". " + it.reason : (it.text ? ". " + it.text : "")}
    ${it.where ? html`<div class="muted">${it.where}</div>` : null}<//>`;
}

export function ActionItems({ items, onAsk }) {
  return html`<div class="acts">${items.map((it) => it.status === "confirm" ? html`<${ConfirmBox} key=${it.key + (it.token || "")} it=${it} />`
    : (it.status === "applied" || it.status === "candidate") ? html`<${AppliedBox} key=${it.key} it=${it} onAsk=${onAsk} />`
    : html`<${PlainBox} key=${it.key} it=${it} />`)}</div>`;
}
