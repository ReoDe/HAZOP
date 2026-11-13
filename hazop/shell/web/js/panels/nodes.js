// 구간 패널(규격 §2.1·§2.3 ④): 구간 목록(S 번호 색, 이름, 도면 범위, 상태), 고른 구간의 상세와 고치기·확정·잠금, 묶음 되돌리기.
// 이름·설계 의도·태그는 도면·모델에서 온 글이라 텍스트로만 넣는다. 엔진이 거절하면 그 사유를 그대로 보인다.
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { store, useStore } from "../store.js";
import { cmd } from "../bridge.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import { canEdit, colorOf, rangeText, sheetName, stateChip } from "./nodes_logic.js";
import * as N from "./nodes_state.js";

const cssHref = new URL("nodes.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector('link[data-nodes-css]')) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-nodes-css", "");
  document.head.appendChild(l);
}

const when = (t) => (t ? String(t).replace("T", " ").replace(/:\d\d(\.\d+)?Z?$/, "") : "");
const OP_LABEL = { add: "만듦", edit: "고침", remove: "지움" };
const opsText = (ops) => (ops || []).map((o) => OP_LABEL[o] || o).join("·");

function Row({ n, list, drawings, on, checked }) {
  const chip = stateChip(n);
  return html`<div class=${"row nrow" + (on ? " on" : "")} key=${n.node_id}>
    <input type="checkbox" aria-label=${n.node_id + " 합치기에 고르기"} checked=${checked} onChange=${() => N.toggleChecked(n.node_id)} />
    <button type="button" class="nrow-b" aria-pressed=${on ? "true" : "false"} aria-label=${n.node_id + " " + (n.name || "")} onClick=${() => N.focusNode(n.node_id, { zoom: true })}>
      <span class="seg-dot" style=${"background:" + colorOf(list, n.node_id)}></span>
      <span class="main"><b>${n.node_id} <span class="nm">${n.name || "(이름 없음)"}</span></b><span>${rangeText(n, drawings)}${n.span && n.span.spans ? html` <span class="span-mark" title="여러 도면에 걸친 구간">⇄</span>` : null} · 구성요소 ${n.count}</span></span></button>
    ${n.overlaps.length ? html`<${Chip} kind="warn" title=${"겹치는 구간: " + n.overlaps.map((o) => o.node_id + "(" + o.shared + ")").join(", ")}>겹침 ${n.overlaps.length}<//>` : null}
    <${Chip} kind=${chip.kind} icon=${chip.icon}>${chip.label}<//></div>`;
}

function Editable({ label, value, multiline, disabled, onSave, hint, aiDraft }) {
  const [text, setText] = useState(null);
  const editing = text !== null;
  const save = () => { const t = text; setText(null); if (t !== (value || "")) onSave(t); };
  return html`<div class="field"><label>${label}${aiDraft ? html` <${Chip} kind="ai" icon="sparkles">AI 초안<//>` : null}</label>
    ${editing ? html`<div class="acts-col">${multiline
      ? html`<textarea class="textbox" rows="3" maxlength="2000" value=${text} aria-label=${label} onInput=${(e) => setText(e.target.value)}></textarea>`
      : html`<input class="textbox" maxlength="120" value=${text} aria-label=${label} onInput=${(e) => setText(e.target.value)}
          onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); save(); } else if (e.key === "Escape") { e.stopPropagation(); setText(null); } }} />`}
      <div class="acts-row"><${Btn} sm=${true} kind="primary" label=${label + " 저장"} onClick=${save}>저장<//><${Btn} sm=${true} label="취소" onClick=${() => setText(null)}>취소<//></div></div>`
    : html`<div class="kv"><span class=${"val" + (aiDraft ? " draft" : "")}>${value || html`<span class="muted">비어 있음</span>`}</span>
        <${Btn} sm=${true} kind="ghost" icon="pencil" label=${label + " 고치기"} disabled=${disabled} title=${disabled ? hint : label + " 고치기"} onClick=${() => setText(value || "")} /></div>`}</div>`;
}

function Detail({ n, d, list, drawings, selection, busy, needArchive }) {
  const [reason, setReason] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const edit = canEdit(n);
  const lockedHint = n.state === "locked" ? "잠긴 구간입니다. 먼저 잠금을 푸세요." : "확정한 구간입니다. 먼저 확정을 푸세요.";
  const chip = stateChip(n);
  const di = n.design_intent;
  const latest = d && d.history && d.history.length ? d.history[d.history.length - 1] : null;
  return html`<div class="card ndetail" aria-label=${n.node_id + " 상세"}>
    <div class="nd-h"><span class="seg-dot" style=${"background:" + colorOf(list, n.node_id)}></span><b>${n.node_id}</b>
      <${Chip} kind=${chip.kind} icon=${chip.icon}>${chip.label}<//><${Chip}>구성요소 ${n.count}<//>
      <span class="muted nd-r">판 ${n.rev}</span></div>
    ${n.confirmed ? html`<div class="muted small">확정: ${n.confirmed.by} · ${when(n.confirmed.at)}</div>` : null}
    ${n.locked ? html`<div class="muted small">잠금: ${n.locked.by} · ${when(n.locked.at)}</div>` : null}
    <${Editable} label="이름" value=${n.name} disabled=${!edit || busy} hint=${lockedHint} onSave=${(t) => N.rename(n.node_id, t)} aiDraft=${n.name_by === "ai" && n.state === "applied"} />
    <${Editable} label="설계 의도" multiline=${true} value=${di && di.text} disabled=${!edit || busy} hint=${lockedHint} onSave=${(t) => N.setIntent(n.node_id, t)} aiDraft=${!!(di && di.by === "ai" && n.state === "applied")} />
    ${d && d.boundary && d.boundary.length ? html`<div class="field"><label>경계</label><div class="acts-row">${d.boundary.map((t, i) => html`${i ? html`<${Icon} name="chevron-right" size=${15} />` : null}<span class="chip id">${t}</span>`)}</div></div>` : null}
    ${n.span && n.span.spans ? html`<div class="field"><label>도면</label><div class="acts-row" role="group" aria-label="도면별로 보기">${n.sheets.map((sh, i) => html`<button type="button" class="chip id" key=${sh.graph_id}
      title=${"이 구간을 " + sheetName(sh.graph_id, drawings) + " 도면에서 보기"} onClick=${() => N.goToSheet(sh.graph_id, { node: n.node_id })}>${sheetName(sh.graph_id, drawings)} · ${sh.n}</button>`)}</div></div>` : null}
    ${n.span && n.span.continuations && n.span.continuations.length ? html`<div class="field"><label>이어짐</label><div class="acts-row">${n.span.continuations.map((c, i) => html`<span class="chip" key=${i}>${c.chip}</span>`)}</div></div>` : null}
    ${d && d.majors_total > 2 ? html`<div class="muted small">주요 기기 ${d.majors_total}개: ${d.majors.join(", ")}${d.majors_total > d.majors.length ? " …" : ""}</div>` : null}
    ${n.overlaps.length ? html`<div class="field"><label>겹침</label><div class="acts-row">${n.overlaps.map((o) => html`<button type="button" class="chip warn" onClick=${() => N.focusNode(o.node_id, { zoom: true })} title="이 구간으로 가기">${o.node_id} · ${o.shared}개</button>`)}</div></div>` : null}
    ${d && d.members.length ? html`<details class="field"><summary>구성요소 ${d.members_total}개${d.members_total > d.members.length ? " (앞 " + d.members.length + "개)" : ""}</summary>
      <div class="memlist">${d.members.map((m, i) => html`<button type="button" class="chip id" key=${i} title=${(m.kind || "") + " · " + m.sheet} onClick=${() => { if (m.sheet === store.get().sheet) N.zoomToIds([m.id]); }}>${m.tag || m.kind || m.id}</button>`)}</div></details>` : null}
    <div class="acts-row">
      ${n.state === "applied" ? html`<${Btn} kind="primary" icon="check" label=${n.node_id + " 확정"} disabled=${busy} onClick=${() => N.confirm([n.node_id])}>확정 <kbd>Ctrl+Enter</kbd><//>` : null}
      ${n.state === "confirmed" ? html`<${Btn} label=${n.node_id + " 확정 해제"} disabled=${busy} onClick=${() => N.unconfirm([n.node_id])}>확정 해제<//>
        <${Btn} icon="lock" label=${n.node_id + " 잠금"} disabled=${busy} onClick=${() => N.lock([n.node_id])}>분석 마침 · 잠금<//>` : null}
      ${n.state === "locked" ? html`<${Btn} icon="lock-open" label=${n.node_id + " 잠금 풀기"} disabled=${busy} onClick=${() => setUnlocking(!unlocking)}>잠금 풀기<//>` : null}
      ${edit && selection.length ? html`<${Btn} label="고른 것을 떼어 새 구간으로" disabled=${busy} onClick=${() => N.splitSelection(n.node_id)}>고른 ${selection.length}개를 떼어 나누기<//>` : null}
      ${edit ? html`<${Btn} kind="ghost" icon="trash" label=${n.node_id + " 지우기"} disabled=${busy} onClick=${() => N.removeNode(n.node_id, false)}>지우기<//>` : null}</div>
    ${unlocking && n.state === "locked" ? html`<div class="field"><label for="unlock-reason">잠금을 푸는 이유(필수)</label>
      <input id="unlock-reason" class="textbox" value=${reason} onInput=${(e) => setReason(e.target.value)} />
      <div class="acts-row"><${Btn} kind="primary" sm=${true} disabled=${busy || !reason.trim()} label="잠금 풀기 실행" onClick=${async () => { const r = await N.unlock([n.node_id], reason.trim()); if (r) { setUnlocking(false); setReason(""); } }}>풀기<//></div></div>` : null}
    ${needArchive === n.node_id ? html`<${Notice} kind="warn" icon="alert-triangle">이 구간의 분석 칸에 판정이 있습니다. 보관하고 지우면 칸은 결과 파일의 보관 목록으로 옮겨집니다.
      <div class="acts-row"><${Btn} sm=${true} label="보관하고 지우기" disabled=${busy} onClick=${() => N.removeNode(n.node_id, true)}>보관하고 지우기<//></div><//>` : null}
    ${d && d.history && d.history.length ? html`<div class="field"><label>이 구간을 건드린 묶음</label>${d.history.slice(-4).reverse().map((h) => html`<div class="kv" key=${h.batch_id}>
      <span class="small"><b>${h.batch_id}</b> ${h.origin === "ai" ? "채팅" : "사람"} · ${opsText(h.ops)}${h.undone ? " · 되돌림" : ""}</span></div>`)}</div>` : null}</div>`;
}

function BatchStrip({ list, busy }) {
  const batches = list.batches.filter((b) => !b.undone).slice(0, 3);
  if (!batches.length) return null;
  const askRest = () => cmd("chat.ask", { text: "나머지 구간도 나눠 줘" }).catch((e) => N.nodes.set({ error: e.message }));
  return html`<div class="card"><h3>최근 묶음</h3>${batches.map((b, i) => html`<div class="kv" key=${b.batch_id}>
    <div class="k"><b>${b.batch_id} · ${b.origin === "ai" ? "채팅" : "사람"} ${opsText(b.ops)}</b><span>${b.node_ids.join(", ")}${b.request_text ? " · “" + b.request_text + "”" : ""} · ${when(b.at)}</span></div>
    <div class="acts-row">${b.origin === "ai" && i === 0 && list.pending_ai > 0 ? html`<${Btn} sm=${true} label="나머지도 나누기" title="채팅에 나머지 구간을 나누도록 시킵니다" onClick=${askRest}>나머지도 나누기<//>` : null}
      <${Btn} sm=${true} icon="arrow-back-up" label=${b.batch_id + " 되돌리기"} disabled=${busy} onClick=${() => N.undo(b.batch_id)}>되돌리기<//></div></div>`)}</div>`;
}

export function NodesPanel({ onClose }) {
  N.wire();
  const list = N.useNodes((s) => s.list);
  const detail = N.useNodes((s) => s.detail);
  const focus = N.useNodes((s) => s.focus);
  const scope = N.useNodes((s) => s.scope);
  const checked = N.useNodes((s) => s.checked);
  const busy = N.useNodes((s) => s.busy);
  const error = N.useNodes((s) => s.error);
  const needArchive = N.useNodes((s) => s.needArchive);
  const selection = N.useNodes((s) => s.selection);
  const sheet = useStore((s) => s.sheet);
  const drawings = useStore((s) => s.drawings.drawings);
  const shown = scope === "sheet" && sheet ? list.nodes.filter((n) => n.sheets.some((x) => x.graph_id === sheet)) : list.nodes;
  const focused = list.nodes.find((n) => n.node_id === focus);
  const open = (e) => { if (e.key === "Enter" && e.ctrlKey && focused && focused.state === "applied") { e.preventDefault(); N.confirm([focused.node_id]); } };
  return html`<section class="panel" aria-label="구간" onKeyDown=${open}>
    <div class="panel-h"><h2>구간</h2><${Chip}>${list.nodes.length}개<//>
      ${list.outside.total ? html`<${Chip} title="어느 구간에도 속하지 않은 구성요소(확정을 막지 않습니다)">구간 밖 ${list.outside.count}<//>` : null}
      <span class="acts"><${Btn} kind="ghost" icon="x" label="패널 닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      ${error ? html`<${Notice} kind="err" icon="alert-triangle"><span class="errtext">${error}</span> <button type="button" class="linkbtn" onClick=${N.dismissError}>닫기</button><//>` : null}
      ${list.legacy ? html`<${Notice} kind="warn" icon="alert-triangle">이 도면은 옛 판(0.1) 구간 파일입니다. 읽기만 해서는 바꾸지 않습니다. 새 판으로 바꾸면 한 번 저장합니다.
        <div class="acts-row"><${Btn} sm=${true} label="새 판으로 바꾸기" disabled=${busy} onClick=${N.migrate}>새 판으로 바꾸기<//></div><//>` : null}
      ${list.read_only ? html`<${Notice} kind="warn" icon="lock">이 구간 파일은 읽기 전용이라 고칠 수 없습니다: ${list.read_only}<//>` : null}
      ${list.stale ? html`<${Notice} kind="warn" icon="alert-triangle">도면 그래프가 바뀌어 저장된 구간과 어긋날 수 있습니다. 확정하기 전에 구성요소를 확인하세요.<//>` : null}
      ${!list.available ? html`<${Notice}>프로젝트 그래프가 아직 없습니다. 도면을 추출하면 구간을 만들 수 있습니다.<//>` : null}
      ${list.pending_ai ? html`<${Notice} kind="info" icon="sparkles">채팅이 만든 구간 ${list.pending_ai}개가 아직 확인 전입니다. 이름과 설계 의도는 초안입니다.<//>` : null}
      <div class="acts-row"><div class="seg-toggle" role="group" aria-label="목록 범위">
        <button type="button" class=${scope === "sheet" ? "on" : ""} aria-pressed=${scope === "sheet" ? "true" : "false"} onClick=${() => N.nodes.set({ scope: "sheet" })}>이 도면</button>
        <button type="button" class=${scope === "all" ? "on" : ""} aria-pressed=${scope === "all" ? "true" : "false"} onClick=${() => N.nodes.set({ scope: "all" })}>전체</button></div>
        ${checked.length >= 2 ? html`<${Btn} sm=${true} icon="plus" label="체크한 구간 합치기" disabled=${busy} onClick=${N.mergeChecked}>${checked.length}개 합치기<//>` : null}</div>
      ${shown.length === 0 ? html`<${Notice}>${list.nodes.length ? "이 도면에는 구간이 없습니다. '전체'로 바꾸면 다른 도면의 구간이 보입니다." : "구간이 없습니다. 도면에서 구성요소를 네모로 끌어 고르고 '구간 만들기'를 누르거나, 채팅에 '대표 구간 3개 만들어 줘'라고 하세요."}<//>`
        : html`<div class="list" role="list">${shown.map((n) => html`<${Row} key=${n.node_id} n=${n} list=${list.nodes} drawings=${drawings} on=${n.node_id === focus} checked=${checked.includes(n.node_id)} />`)}</div>`}
      ${focused ? html`<${Detail} n=${focused} d=${detail} list=${list.nodes} drawings=${drawings} selection=${selection} busy=${busy} needArchive=${needArchive} />` : null}
      <${BatchStrip} list=${list} busy=${busy} /></div></section>`;
}
