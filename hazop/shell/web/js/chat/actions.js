// 채팅이 제안한 쓰기 동작을 그린다(채팅 규격 §4, 앱 틀 규격 §2.3·시안 3번). 판정·실행은 엔진(hazop/shell/chat_actions.py)이 끝냈고,
// 여기는 받은 항목을 그리고 사람이 누르는 단추(확인 상자의 실행·하지 않음, '이 요청 되돌리기', '나머지도 나누기')를 엔진 명령으로 보낸다.
// 모델이 쓴 글(구간 이름 등)은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useEffect, useRef, useState } from "../../vendor/hooks.module.js";
import { cmd, on } from "../bridge.js";
import { store } from "../store.js";
import { Icon } from "../ui/icon.js";
import { Btn, Notice } from "../ui/parts.js";
import * as N from "../panels/nodes_state.js";
import * as R from "../panels/results_state.js";

export const REST_QUESTION = "방금 만든 대표 구간을 참고해서 나머지 구간도 나눠 주세요.";

// ---------------------------------------------------------------- 표시 동작(chat.display)
// 엔진(hazop/shell/chat_actions.py display_item)이 모델의 show·goto·select·layer·fit을 이미 검사해 도면 ID·도면 안 local_id·패널 이름으로 풀어 보낸다.
// 여기서는 그 값대로 도면을 열고 표시·확대·패널 열기·층 켜기를 한다. 데이터는 바꾸지 않는다.
const ZOOM_RETRY_MS = [350, 900, 1800];    // 다른 도면을 연 뒤에는 그 도면을 다 읽어야 확대가 먹는다. 준비 신호가 저장소에 없어 몇 번 다시 보낸다

function bump(command) { store.set((s) => ({ command: Object.assign({ seq: s.command.seq + 1 }, command) })); }

function openSheet(gid) {
  if (!gid || store.get().sheet === gid) return false;
  store.set({ sheet: gid, panel: null });
  cmd("sheet.open", { graph_id: gid }).catch(() => {});
  return true;
}

function later(command, opened) {
  if (!opened) { bump(command); return; }
  // 도면 부품이 준비를 알리면(readySheet) 바로, 아니면 정해진 간격으로 다시 보낸다
  let done = false;
  const gid = store.get().sheet;
  const stop = store.subscribe((s) => { if (!done && s.readySheet === gid) { done = true; stop(); bump(command); } });
  ZOOM_RETRY_MS.forEach((ms, i) => setTimeout(() => { if (done || store.get().sheet !== gid) return; if (i === ZOOM_RETRY_MS.length - 1) { done = true; stop(); } bump(command); }, ms));
}

function note(text) {
  store.set((s) => ({ chat: Object.assign({}, s.chat, { msgs: [...s.chat.msgs, { key: "disp:" + s.chat.msgs.length + ":" + Date.now(), kind: "notice", text }] }) }));
}

export function applyDisplay(it, rid) {
  if (!it || !it.ok) return;
  if (it.op === "show") {
    const opened = openSheet(it.sheet);
    store.set({ marks: { rid, bySheet: it.marks || {} } });
    later({ type: "zoomTo", ids: (it.ids || []).slice(0, 400), pad: 0.6 }, opened);
  } else if (it.op === "open") {
    later({ type: "fit" }, openSheet(it.sheet));
  } else if (it.op === "fit") {
    later({ type: "fit" }, openSheet(it.sheet));
  } else if (it.op === "layer") {
    store.set((s) => ({ layers: Object.assign({ symbol: true, pipe: true, tag: true }, s.layers, { [it.layer]: !!it.on }) }));
  } else if (it.op === "panel") {
    store.set({ panel: it.panel, backTo: null });
    if (it.node_id && N.nodes.get().focus !== it.node_id) N.focusNode(it.node_id, { zoom: true });
    if (it.cell) R.openCell(it.cell[0], it.cell[1]);
    if (it.panel === "aireview" && it.sheet) import("../panels/aireview_state.js").then((A) => A.pickDrawing(it.sheet)).catch(() => {});
  }
}

on("chat.display", (d) => {
  const items = (d && d.items) || [];
  items.forEach((it, i) => { try { applyDisplay(it, "disp:" + d.answer_id + (i ? "#" + i : "")); } catch (e) { /* 보이지 못해도 대화는 이어진다 */ } });
  items.forEach((it) => { if (it && it.text) note(it.text); });
  if (store.get().chatCollapsed) store.set((s) => ({ chat: Object.assign({}, s.chat, { unread: true }) }));
});

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

const SHOWN = 6;      // 대상 목록은 처음 이만큼만 보이고 '모두 보기'로 펼친다

function Targets({ it }) {
  const [all, setAll] = useState(false);
  const list = it.targets || [];
  if (!list.length) return null;
  const rows = all ? list : list.slice(0, SHOWN);
  const cut = it.targets_total > list.length;      // 엔진이 보낼 수 있는 수를 넘어 잘렸다
  return html`<div class="tgts" aria-label=${"대상 " + it.targets_total + "개"}>
    <div class="muted small">대상 ${it.targets_total}개</div>
    <ul class="tight">${rows.map((t) => html`<li key=${t.id}>${t.label}</li>`)}</ul>
    ${list.length > SHOWN ? html`<${Btn} sm=${true} kind="ghost" label=${all ? "접기" : "대상 모두 보기"} onClick=${() => setAll(!all)}>${all ? "접기" : "외 " + (list.length - SHOWN) + "개 모두 보기"}<//>` : null}
    ${cut ? html`<div class="small warnline">대상이 너무 많아 처음 ${list.length}개만 보입니다(전체 ${it.targets_total}개를 실행합니다).</div>` : null}</div>`;
}

// 확인 상자 줄의 모양(채팅 모듈 전용. 공용 shell.css를 건드리지 않으려고 여기서 한 번 붙인다)
if (typeof document !== "undefined" && !document.getElementById("chat-actions-css")) {
  const st = document.createElement("style");
  st.id = "chat-actions-css";
  st.textContent = ".act-fold{margin:6px 0;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--surface)}"
    + ".act-fold>summary{cursor:pointer;padding:4px 8px;font-size:var(--fs-xs);color:var(--muted);list-style-position:inside}"
    + ".act-fold[open]>summary{border-bottom:1px solid var(--line)}.act-fold .act-body{padding:4px 8px 6px;display:grid;gap:6px;max-height:40vh;overflow:auto}"
    + ".act-table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}.act-table th{text-align:left;font-weight:500;color:var(--muted);"
    + "padding:3px 6px 3px 0;vertical-align:top;white-space:nowrap;width:1%}.act-table td{padding:3px 0;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}"
    + ".act-table .before{color:var(--muted)}.act-table .arrow{color:var(--muted);padding:0 4px}.act-table .after{font-weight:600}"
    + ".act-need{font-size:var(--fs-xs);color:var(--muted)}";
  document.head.appendChild(st);
}

/** 확인 상자의 '저장될 값'과 대상을 접을 수 있는 한 덩이로: 항목 | 앞값 → 새값 표. 엔진이 지금 상태에서 만든 줄을 빠짐없이, 값은 늘 전문으로 보인다
 * (길면 상자 안에서 스크롤). onSeen(참·거짓): 펼쳐져 있고 끝까지 본 적이 있는지. 접었거나 끝까지 내려 보지 않았으면 '실행'을 끈다. */
function Fold({ it, onSeen }) {
  const rows = it.details || [];
  const ops = it.ops || [];
  const tgt = (it.targets || []).length;
  const body = useRef(null);
  const box = useRef(null);
  const bottom = useRef(false);
  function look() {
    const el = body.current;
    const open = !!(box.current && box.current.open);
    if (el && open && el.scrollTop + el.clientHeight >= el.scrollHeight - 4) bottom.current = true;
    if (onSeen) onSeen(open && bottom.current);
  }
  useEffect(() => { look(); }, [it.token, rows.length]);
  if (!rows.length && !ops.length && !tgt) return null;
  const head = [rows.length ? "저장될 값 " + rows.length + "줄" : null, ops.length ? "바꿀 내용 " + ops.length + "줄" : null,
    tgt ? "대상 " + it.targets_total + "개" : null].filter(Boolean).join(" · ");
  const cell = (cls, v) => html`<span class=${cls}>${v == null ? "" : String(v)}</span>`;
  return html`<details class="act-fold" open ref=${box} onToggle=${look}>
    <summary>${head}</summary>
    <div class="act-body" ref=${body} onScroll=${look}>
      ${rows.length ? html`<table class="act-table" aria-label="저장될 값"><tbody>${rows.map((r, i) => html`<tr key=${i}>
        <th scope="row">${r.label}</th>
        <td>${r.before !== undefined && r.before !== null
          ? html`${cell("before", r.before)}<span class="arrow" aria-label="에서">→</span>${cell("after", r.after)}`
          : cell("after", r.after)}</td></tr>`)}</tbody></table>` : null}
      ${ops.length ? html`<ul class="tight" aria-label="바꿀 내용">${ops.map((o, i) => html`<li key=${i}>${o}</li>`)}</ul>` : null}
      <${Targets} it=${it} /></div></details>`;
}

function LogError({ it }) {
  return it.log_error ? html`<div class="small warnline" role="alert">${it.log_error}</div>` : null;
}

function ConfirmBox({ it }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const hasFold = !!((it.details || []).length || (it.ops || []).length || (it.targets || []).length);
  const [seen, setSeen] = useState(!hasFold);
  async function press(name) {
    setBusy(true); setErr("");
    try { await cmd(name, { token: it.token }); } catch (e) { setErr(e.message || "처리하지 못했습니다."); setBusy(false); }
  }
  return html`<div class="actbox confirm" role="group" aria-label=${"확인: " + it.title}>
    <div class="actbox-h"><${Icon} name="alert-triangle" size=${15} /><b>${it.title}</b></div>
    <p>${it.text}</p>
    <${Fold} it=${it} onSeen=${(v) => setSeen(!hasFold || v)} />
    ${it.waiting ? html`<div class="muted" style="font-size:var(--fs-xs)">앞의 확인이 끝나면 이어서 묻습니다.</div>` : html`
      <div class="acts-row">
        <${Btn} kind="primary" sm=${true} disabled=${busy || !seen} label="실행" onClick=${() => press("chat.action.approve")}>실행<//>
        <${Btn} sm=${true} disabled=${busy} label="하지 않음" onClick=${() => press("chat.action.decline")}>하지 않음<//>
        ${seen ? null : html`<span class="act-need" role="status">저장될 값을 펼쳐 끝까지 보면 실행할 수 있습니다.</span>`}</div>`}
    <${LogError} it=${it} />
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
    <${LogError} it=${it} />
    ${err ? html`<${Notice} kind="err" icon="alert-triangle">${err}<//>` : null}</div>`;
}

function PlainBox({ it }) {
  const kind = it.status === "declined" || it.status === "duplicate" ? "info" : "warn";
  const head = { rejected: "하지 않았습니다", failed: "실행하지 못했습니다", stale: "실행하지 않았습니다", declined: "실행하지 않았습니다", duplicate: "이미 처리했습니다" }[it.status] || it.title;
  return html`<${Notice} kind=${kind} icon=${ICON[it.status] || "info-circle"}><b>${it.title}</b> — ${head}${it.reason ? ". " + it.reason : (it.text ? ". " + it.text : "")}
    ${it.where ? html`<div class="muted">${it.where}</div>` : null}${it.log_error ? html`<div class="small warnline" role="alert">${it.log_error}</div>` : null}<//>`;
}

export function ActionItems({ items, onAsk }) {
  return html`<div class="actlist">${items.map((it) => it.status === "confirm" ? html`<${ConfirmBox} key=${it.key + (it.token || "")} it=${it} />`
    : (it.status === "applied" || it.status === "candidate") ? html`<${AppliedBox} key=${it.key} it=${it} onAsk=${onAsk} />`
    : html`<${PlainBox} key=${it.key} it=${it} />`)}</div>`;
}
