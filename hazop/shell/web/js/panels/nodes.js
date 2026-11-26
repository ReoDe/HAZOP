// 구간 패널(규격 §2.1·§2.3 ④): 구간 목록(S 번호 색, 이름, 도면 범위, 상태), 고른 구간의 상세와 고치기, 묶음 되돌리기.
// 이름·설계 의도·태그는 도면·모델에서 온 글이라 텍스트로만 넣는다. 엔진이 거절하면 그 사유를 그대로 보인다.
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { store, useStore } from "../store.js";
import { cmd } from "../bridge.js";
import { Icon } from "../ui/icon.js";
import { SelectAll } from "../ui/select_all.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import { canEdit, checkText, colorOf, discardLabel, rangeText, sheetName } from "./nodes_logic.js";
import * as N from "./nodes_state.js";
import { locate } from "../locate.js";

const cssHref = new URL("nodes.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector('link[data-nodes-css]')) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-nodes-css", "");
  document.head.appendChild(l);
}

const when = (t) => (t ? String(t).replace("T", " ").replace(/:\d\d(\.\d+)?Z?$/, "") : "");
const OP_LABEL = { add: "만듦", edit: "고침", remove: "지움" };
const KIND_LABEL = { "discard_lost": "찾지 못한 구성요소 버림" };
const opsText = (ops, kind) => KIND_LABEL[kind] || (ops || []).map((o) => OP_LABEL[o] || o).join("·");

/** 구간 한 줄: 색 점·번호·이름·도면 범위·구성요소 수만. 잠긴 구간은 자물쇠, 도면과 어긋난 구간은 경고 아이콘 하나씩만 더한다. */
function Row({ n, list, drawings, on, checked }) {
  const broken = [n.lost ? "찾지 못한 구성요소 " + n.lost + "개" : "", n.broken ? "끊긴 구성원 " + n.broken : ""].filter(Boolean).join(" · ");
  return html`<div class=${"row nrow noderow" + (on ? " on" : "")} key=${n.node_id}>
    <input type="checkbox" aria-label=${n.node_id + " 고르기"} checked=${checked} onChange=${() => N.toggleChecked(n.node_id)} />
    <button type="button" class="nrow-b" aria-pressed=${on ? "true" : "false"} aria-label=${n.node_id + " " + (n.name || "")} onClick=${() => N.focusNode(n.node_id, { show: true })}>
      <span class="seg-dot" style=${"background:" + colorOf(list, n.node_id)}></span>
      <span class="main"><b>${n.node_id} <span class="nm">${n.name || "(이름 없음)"}</span></b><span>${rangeText(n, drawings)} · 구성요소 ${n.count}</span></span></button>
    ${broken ? html`<span class="warn-mark" role="img" title=${broken} aria-label=${n.node_id + ": " + broken}><${Icon} name="alert-triangle" size=${15} /></span>` : null}
    ${n.state === "locked" ? html`<span class="lock-mark" role="img" title="잠긴 구간" aria-label=${n.node_id + ": 잠긴 구간"}><${Icon} name="lock" size=${15} /></span>` : null}</div>`;
}

/** 체크로 고른 구간에 할 일: 도면 목록과 같은 꼴(n개 고름 · 휴지통 · 해제). 잠긴 구간은 지우지 않는다. */
function NodePicks({ ids, list, busy }) {
  const deletable = ids.filter((id) => list.some((n) => n.node_id === id && n.state !== "locked"));
  return html`<div class="picks" role="toolbar" aria-label="고른 구간에 할 일"><span class="small muted">${ids.length}개 고름</span>
    ${deletable.length ? html`<${Btn} sm=${true} kind="ghost" icon="trash" label="삭제" disabled=${busy} onClick=${() => N.removeMany(deletable)} />` : null}
    <${Btn} sm=${true} kind="ghost" label="고르기 해제" disabled=${busy} onClick=${() => N.setChecked(ids, false)}>해제<//></div>`;
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

/** 찾지 못한 구성요소 목록과 버리기. 사람이 확인하고 버린 것만 버린다(고른 것, 또는 모두). 잠긴 구간이면 단추 대신 까닭을 보인다. */
function LostItems({ n, d, busy }) {
  const [picked, setPicked] = useState([]);
  const items = (d && d.lost_items) || [];
  if (!items.length) return d && d.discarded ? html`<div class="muted small">찾지 못해 버린 구성요소 ${d.discarded}개(되돌리기 묶음으로 되살릴 수 있음)</div>` : null;
  const keys = items.map((x) => x.key).filter((k) => picked.includes(k));
  const toggle = (k) => setPicked(picked.includes(k) ? picked.filter((x) => x !== k) : picked.concat(k));
  const go = async (ks) => { const r = await N.discardLost(n.node_id, ks); if (r) setPicked([]); };
  const held = n.state === "locked";
  return html`<details class="field lost-items" open><summary>찾지 못한 구성요소 ${items.length}개</summary>
    <div class="muted small">다시 추출한 도면에서 같은 자리를 찾지 못한 구성요소입니다. 도면에서 실제로 없어진 것을 확인했으면 버리세요. 버린 것은 되돌리기 묶음으로 되살릴 수 있습니다.</div>
    <ul class="lost-list" aria-label="찾지 못한 구성요소">${items.map((x) => html`<li key=${x.key}><label>
      ${items.length > 1 ? html`<input type="checkbox" disabled=${held || busy} checked=${picked.includes(x.key)} onChange=${() => toggle(x.key)} />` : null} ${x.name}</label></li>`)}</ul>
    ${held ? html`<div class="muted small">잠긴 구간입니다. 잠금을 해제한 뒤에 버릴 수 있습니다.</div>`
      : html`<div class="acts-row">${items.length > 1 ? html`<${Btn} sm=${true} label=${n.node_id + " 찾지 못한 구성요소 " + discardLabel(keys.length, items.length)} disabled=${busy || !keys.length} onClick=${() => go(keys)}>${discardLabel(keys.length, items.length)}<//>` : null}
        <${Btn} sm=${true} kind="ghost" label=${n.node_id + " 찾지 못한 구성요소 모두 버리기"} disabled=${busy} onClick=${() => go(items.map((x) => x.key))}>${discardLabel(items.length, items.length)}<//></div>`}
    ${d.discarded ? html`<div class="muted small">이미 버린 것 ${d.discarded}개</div>` : null}</details>`;
}

function Detail({ n, d, list, drawings, selection, busy, needArchive }) {
  const [reason, setReason] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const edit = canEdit(n);
  const lockedHint = "잠긴 구간입니다. 먼저 잠금을 해제하세요.";
  const di = n.design_intent;
  const latest = d && d.history && d.history.length ? d.history[d.history.length - 1] : null;
  return html`<div class="card ndetail" aria-label=${n.node_id + " 상세"}>
    <div class="nd-h"><span class="seg-dot" style=${"background:" + colorOf(list, n.node_id)}></span><b>${n.node_id}</b>
      <${Chip}>구성요소 ${n.count}<//>
      <span class="muted nd-r">${n.rev > 1 ? "수정 " + (n.rev - 1) + "회" : ""}</span></div>
    <div class="acts-row nd-acts">
      ${n.state === "locked" ? html`<${Btn} icon="lock-open" label=${n.node_id + " 잠금 해제"} disabled=${busy} onClick=${() => setUnlocking(!unlocking)}>잠금 해제<//>` : null}
      ${edit && selection.length ? html`<${Btn} label="고른 것을 떼어 새 구간으로" disabled=${busy} onClick=${() => N.splitSelection(n.node_id)}>고른 ${selection.length}개를 떼어 나누기<//>` : null}
      ${edit ? html`<${Btn} kind="ghost" icon="trash" label=${n.node_id + " 지우기"} disabled=${busy} onClick=${() => N.removeNode(n.node_id, false)}>지우기<//>` : null}</div>
    <${Editable} label="이름" value=${n.name} disabled=${!edit || busy} hint=${lockedHint} onSave=${(t) => N.rename(n.node_id, t)} aiDraft=${n.name_by === "ai" && edit} />
    <${Editable} label="설계 의도" multiline=${true} value=${di && di.text} disabled=${!edit || busy} hint=${lockedHint} onSave=${(t) => N.setIntent(n.node_id, t)} aiDraft=${!!(di && di.by === "ai" && edit)} />
    ${d && d.boundary && d.boundary.length ? html`<div class="field"><label>경계</label><div class="acts-row">${d.boundary.map((t, i) => html`${i ? html`<${Icon} name="chevron-right" size=${15} />` : null}<span class="chip id">${t}</span>`)}</div></div>` : null}
    ${n.span && n.span.spans ? html`<div class="field"><label>도면</label><div class="acts-row" role="group" aria-label="도면별로 보기">${n.sheets.map((sh, i) => html`<button type="button" class="chip id" key=${sh.graph_id}
      title=${"이 구간을 " + sheetName(sh.graph_id, drawings) + " 도면에서 보기"} onClick=${() => N.goToSheet(sh.graph_id)}>${sheetName(sh.graph_id, drawings)} · ${sh.n}</button>`)}</div></div>` : null}
    ${n.span && n.span.continuations && n.span.continuations.length ? html`<div class="field"><label>이어짐</label><div class="acts-row">${n.span.continuations.map((c, i) => html`<span class="chip" key=${i}>${c.chip}</span>`)}</div></div>` : null}
    ${d && d.majors_total > 2 ? html`<div class="muted small">주요 기기 ${d.majors_total}개: ${d.majors.join(", ")}${d.majors_total > d.majors.length ? " …" : ""}</div>` : null}
    ${n.overlaps.length ? html`<div class="field"><label>겹침</label><div class="acts-row">${n.overlaps.map((o) => html`<button type="button" class="chip warn" onClick=${() => N.focusNode(o.node_id, { show: true })} title="이 구간으로 가기">${o.node_id} · ${o.shared}개</button>`)}</div></div>` : null}
    <${LostItems} key=${n.node_id} n=${n} d=${d} busy=${busy} />
    ${d && d.members.length ? html`<details class="field"><summary>구성요소 ${d.members_total}개${d.members_total > d.members.length ? " (앞 " + d.members.length + "개)" : ""}</summary>
      <div class="memlist">${d.members.map((m, i) => html`<button type="button" class="chip id" key=${i} title=${(m.kind_label || "구성요소") + " · " + sheetName(m.sheet, drawings)} aria-label=${(m.tag || m.kind_label || "구성요소") + " · " + (m.kind_label || "구성요소") + " · " + sheetName(m.sheet, drawings)} onClick=${() => locate({ sheet: m.sheet, ids: [m.id] })}>${m.tag || m.kind_label || "구성요소"}</button>`)}</div></details>` : null}
    ${unlocking && n.state === "locked" ? html`<div class="field"><label for="unlock-reason">잠금을 해제하는 이유(필수)</label>
      <input id="unlock-reason" class="textbox" value=${reason} onInput=${(e) => setReason(e.target.value)} />
      <div class="acts-row"><${Btn} kind="primary" sm=${true} disabled=${busy || !reason.trim()} label="잠금 해제 실행" onClick=${async () => { const r = await N.unlock([n.node_id], reason.trim()); if (r) { setUnlocking(false); setReason(""); } }}>해제<//></div></div>` : null}
    ${needArchive === n.node_id ? html`<${Notice} kind="warn" icon="alert-triangle">이 구간의 분석 칸에 판정이 있습니다. 보관하고 지우면 칸은 결과 파일의 보관 목록으로 옮겨집니다.
      <div class="acts-row"><${Btn} sm=${true} label="보관하고 지우기" disabled=${busy} onClick=${() => N.removeNode(n.node_id, true)}>보관하고 지우기<//></div><//>` : null}
    ${d && d.history && d.history.length ? html`<div class="field"><label>이 구간을 건드린 묶음</label>${d.history.slice(-4).reverse().map((h) => html`<div class="kv" key=${h.batch_id}>
      <span class="small"><b>${h.batch_id}</b> ${h.origin === "ai" ? "채팅" : "사람"} · ${opsText(h.ops, h.kind)}${h.undone ? " · 되돌림" : ""}</span></div>`)}</div>` : null}</div>`;
}

function BatchStrip({ list, busy }) {
  const batches = list.batches.filter((b) => !b.undone).slice(0, 3);
  if (!batches.length) return null;
  const askRest = () => cmd("chat.ask", { text: "나머지 구간도 나눠 줘" }).catch((e) => N.nodes.set({ error: e.message }));
  return html`<div class="card"><h3>최근 묶음</h3>${batches.map((b, i) => html`<div class="kv" key=${b.batch_id}>
    <div class="k"><b>${b.batch_id} · ${b.origin === "ai" ? "채팅" : "사람"} ${opsText(b.ops, b.kind)}</b><span>${b.node_ids.join(", ")}${b.request_text ? " · “" + b.request_text + "”" : ""} · ${when(b.at)}</span></div>
    <div class="acts-row">${b.origin === "ai" && i === 0 && list.pending_ai > 0 ? html`<${Btn} sm=${true} label="나머지도 나누기" title="채팅에 나머지 구간을 나누도록 시킵니다" onClick=${askRest}>나머지도 나누기<//>` : null}
      <${Btn} sm=${true} icon="arrow-back-up" label=${b.batch_id + " 되돌리기"} disabled=${busy} onClick=${() => N.undo(b.batch_id)}>되돌리기<//></div></div>`)}</div>`;
}

export function NodesPanel({ onClose }) {
  N.wire();
  useLayoutEffect(() => { N.refresh(); }, []);      // 열 때마다 다시 읽는다(알림을 놓쳤어도 낡은 목록·안내로 시작하지 않게)
  const list = N.useNodes((s) => s.list);
  const detail = N.useNodes((s) => s.detail);
  const focus = N.useNodes((s) => s.focus);
  const scope = N.useNodes((s) => s.scope);
  const checked = N.useNodes((s) => s.checked);
  const busy = N.useNodes((s) => s.busy);
  const error = N.useNodes((s) => s.error);
  const needArchive = N.useNodes((s) => s.needArchive);
  const here = N.useNodes((s) => s.selection);
  const picks = N.useNodes((s) => s.picks);
  const selection = N.pickedIds({ selection: here, picks });
  const sheet = useStore((s) => s.sheet);
  const drawings = useStore((s) => s.drawings.drawings);
  const shown = scope === "sheet" && sheet ? list.nodes.filter((n) => n.sheets.some((x) => x.graph_id === sheet)) : list.nodes;
  const focused = list.nodes.find((n) => n.node_id === focus);
  const removed = N.useNodes((s) => s.removed);
  const picked = shown.filter((n) => checked.includes(n.node_id)).map((n) => n.node_id);      // 지금 보이는 줄 가운데 고른 것
  return html`<section class="panel" aria-label="구간">
    <div class="panel-h"><h2>구간</h2><${Chip}>${list.nodes.length}개<//>
      ${list.outside.total ? html`<${Chip} title="어느 구간에도 속하지 않은 구성요소">구간 밖 ${list.outside.count}<//>` : null}
      </div>
    <div class="panel-b">
      ${error ? html`<${Notice} kind="err" icon="alert-triangle"><span class="errtext">${error}</span> <button type="button" class="linkbtn" onClick=${N.dismissError}>닫기</button><//>` : null}
      ${list.legacy ? html`<${Notice} kind="warn" icon="alert-triangle">이 도면의 구간은 이전 형식으로 저장돼 있습니다. 읽기만 해서는 바꾸지 않습니다. 새 형식으로 바꾸면 한 번 저장합니다.
        <div class="acts-row"><${Btn} sm=${true} label="새 형식으로 바꾸기" disabled=${busy} onClick=${N.migrate}>새 형식으로 바꾸기<//></div><//>` : null}
      ${list.read_only ? html`<${Notice} kind="warn" icon="lock">이 구간 파일은 읽기 전용이라 고칠 수 없습니다: ${list.read_only}<//>` : null}
      ${list.check && list.check.needs_check ? html`<${Notice} kind="warn" icon="alert-triangle">${checkText(list.check)}<//>` : null}
      ${list.stale ? html`<${Notice} kind="warn" icon="alert-triangle">도면이 다시 읽혀 바뀌었는데, 저장된 구간에 그 변경을 아직 반영하지 못했습니다. 반영을 마칠 때까지 초기사건은 열리지 않고, 분석 결과의 실행·Excel 내보내기는 막힙니다.
        <div class="acts-row"><${Btn} sm=${true} kind="primary" icon="refresh" label="도면 변경 반영하기" disabled=${busy || !!list.read_only} onClick=${N.catchUp}>도면 변경 반영하기<//></div><//>` : null}
      ${!list.available ? html`<${Notice}>도면을 먼저 읽어야 합니다.<//>` : null}
      <div class="acts-row"><div class="seg-toggle" role="group" aria-label="목록 범위">
        <button type="button" class=${scope === "sheet" ? "on" : ""} aria-pressed=${scope === "sheet" ? "true" : "false"} onClick=${() => N.nodes.set({ scope: "sheet" })}>이 도면</button>
        <button type="button" class=${scope === "all" ? "on" : ""} aria-pressed=${scope === "all" ? "true" : "false"} onClick=${() => N.nodes.set({ scope: "all" })}>전체</button></div></div>
      ${shown.length ? html`<${SelectAll} ids=${shown.filter((n) => n.state !== "locked").map((n) => n.node_id)} picked=${checked} label="구간 전체 선택" onChange=${N.setChecked} />` : null}
      ${picked.length ? html`<${NodePicks} ids=${picked} list=${list.nodes} busy=${busy} />` : null}
      ${removed ? html`<div class="acts-row"><${Btn} sm=${true} icon="arrow-back-up" label="지운 구간 되돌리기" disabled=${busy} onClick=${N.undoRemoved}>되돌리기<//></div>` : null}
      ${shown.length === 0 ? html`<${Notice}>${list.nodes.length ? "이 도면에는 구간이 없습니다." : "구간이 없습니다."}<//>`
        : html`<div class="list" role="list">${shown.map((n) => html`<${Row} key=${n.node_id} n=${n} list=${list.nodes} drawings=${drawings} on=${n.node_id === focus} checked=${checked.includes(n.node_id)} />`)}</div>`}
      ${focused ? html`<${Detail} n=${focused} d=${detail} list=${list.nodes} drawings=${drawings} selection=${selection} busy=${busy} needArchive=${needArchive} />` : null}
      <${BatchStrip} list=${list} busy=${busy} /></div></section>`;
}
