// 도면 위의 구간 기능(규격 §3.1·§2.3 ④): 고르기 도구 막대, 'n개 고름' 막대, 새 구간 카드, 구간 강조 props.
// SheetHost가 `useNodeCanvas(sheet, {onEsc})`의 props를 <Sheet>에 펼치고 `<NodeOverlay />`를 도면 자리 안에 그린다.
// 도면·모델에서 온 글(태그, 이름)은 htm이 이스케이프하는 텍스트로만 넣는다.
import { html } from "../ui/html.js";
import { useEffect, useMemo } from "../../vendor/hooks.module.js";
import { store as shell } from "../store.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import { escStep, keyAction, canEdit, colorOf, sheetSegments } from "../panels/nodes_logic.js";
import * as N from "../panels/nodes_state.js";

/** <Sheet>에 펼칠 props와 키 처리. 상태는 nodes_state의 저장소에 있다. */
export function useNodeCanvas(sheet, { onEsc } = {}) {
  N.wire();
  const mode = N.useNodes((s) => s.mode);
  const selection = N.useNodes((s) => s.selection);
  const sheetView = N.useNodes((s) => s.sheetView);
  const list = N.useNodes((s) => s.list.nodes);
  const focus = N.useNodes((s) => s.focus);
  const showOutside = N.useNodes((s) => s.showOutside);
  const segments = useMemo(() => (sheetView && sheetView.graph_id === sheet ? sheetSegments(sheetView, list, focus) : []), [sheetView, list, focus, sheet]);
  const outside = useMemo(() => (showOutside && sheetView && sheetView.graph_id === sheet && sheetView.segments.length ? sheetView.outside_ids : []), [sheetView, showOutside, sheet]);

  useEffect(() => {
    function key(e) {
      const t = e.target, tag = (t && t.tagName) || "";
      const typing = tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT" || (t && t.isContentEditable);
      const s = N.nodes.get();
      const act = keyAction(e, { selection: s.selection, typing, panelWide: false });
      if (!act) return;
      e.preventDefault();
      if (act === "pan" || act === "pick") N.setMode(act);
      else if (act === "fit") N.zoomToIds(s.selection);
      else if (act === "card") N.openCard();
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  return {
    props: {
      mode, selection, segments, outside,
      onSelection: (d) => N.setSelection(d.selected),
      onSegmentClick: (d) => { N.focusNode(d.node_id); N.openPanel(); },
      onEsc: () => {
        const s = N.nodes.get(), step = escStep({ card: !!s.card, focus: s.focus, mode: s.mode, selection: s.selection });
        if (step === "card") N.closeCard();
        else if (step === "focus") N.focusNode(s.focus);
        else if (step === "pan") N.setMode("pan");
        else if (onEsc) onEsc();
      },
    },
  };
}

function Toolbar() {
  const mode = N.useNodes((s) => s.mode);
  const b = (m, icon, label, key) => html`<button type="button" class=${mode === m ? "on" : ""} aria-pressed=${mode === m ? "true" : "false"} aria-label=${label + " (" + key + ")"}
    title=${label + " (" + key + ")"} onClick=${() => N.setMode(m)}><${Icon} name=${icon} />${m === "pick" ? html`<span>고르기</span>` : null}</button>`;
  return html`<div class="float toolbar" role="toolbar" aria-label="도면 도구">
    ${b("pan", "arrows-move", "이동", "V")}${b("pick", "select", "네모로 고르기", "S")}<span class="sep"></span>
    <button type="button" aria-label="전체 맞춤" title="전체 맞춤" onClick=${() => shell.set((s) => ({ command: { seq: s.command.seq + 1, type: "fit" } }))}><${Icon} name="zoom-scan" /></button></div>`;
}

function SelectionBar() {
  const selection = N.useNodes((s) => s.selection);
  const focus = N.useNodes((s) => s.focus);
  const list = N.useNodes((s) => s.list.nodes);
  const card = N.useNodes((s) => s.card);
  const busy = N.useNodes((s) => s.busy);
  if (!selection.length || card) return null;
  const node = list.find((n) => n.node_id === focus);
  const edit = canEdit(node);
  return html`<div class="float selbar" role="group" aria-label="고른 것">
    <span class="count">${selection.length}개 고름</span>
    <span class="hint">끌기: 더하기 · Alt+끌기: 빼기 · 클릭: 넣고 빼기 · Esc: 비우기</span>
    ${node ? html`<${Chip} kind="accent" title="강조한 구간"><span class="seg-dot" style=${"background:" + colorOf(list, node.node_id)}></span> ${node.node_id}<//>` : null}
    ${node && edit ? html`<${Btn} sm=${true} disabled=${busy} label=${node.node_id + "에 더하기"} onClick=${() => N.addSelectionTo(node.node_id)}>${node.node_id}에 더하기<//>
      <${Btn} sm=${true} disabled=${busy} label=${node.node_id + "에서 빼기"} onClick=${() => N.removeSelectionFrom(node.node_id)}>빼기<//>` : null}
    <${Btn} kind="primary" icon="plus" label="구간 만들기" onClick=${() => N.openCard()}>구간 만들기 <kbd>Enter</kbd><//>
    <${Btn} kind="ghost" sm=${true} icon="x" label="고른 것 비우기" title="비우기 (Esc)" onClick=${() => N.clearSelection()} /></div>`;
}

function NewNodeCard() {
  const card = N.useNodes((s) => s.card);
  const list = N.useNodes((s) => s.list.nodes);
  if (!card) return null;
  const sg = card.suggest;
  const nextNo = "S" + (Math.max(0, ...list.map((n) => parseInt(String(n.node_id).slice(1), 10) || 0)) + 1);
  const submit = (e) => { e.preventDefault(); N.submitCard(); };
  return html`<form class="float newnode" role="dialog" aria-label="새 구간" onSubmit=${submit}
    onKeyDown=${(e) => { if (e.key === "Escape") { e.stopPropagation(); N.closeCard(); } else if (e.key === "Enter" && (e.ctrlKey || e.target.tagName !== "TEXTAREA")) { e.preventDefault(); N.submitCard(); } }}>
    <div class="nn-h"><span class="seg-dot" style=${"background:" + colorOf(list.concat([{ node_id: nextNo }]), nextNo)}></span><b>새 구간 ${nextNo}</b>
      ${sg ? html`<${Chip}>구성요소 ${sg.count}<//>` : null}<${Btn} kind="ghost" sm=${true} icon="x" label="카드 닫기" title="닫기 (Esc)" onClick=${N.closeCard} /></div>
    <div class="field"><label for="nn-name">이름</label>
      <input id="nn-name" class="textbox" autofocus value=${card.name} maxlength="120" onInput=${(e) => N.editCard({ name: e.target.value })} /></div>
    <div class="field"><label for="nn-intent">설계 의도</label>
      <textarea id="nn-intent" class="textbox" rows="3" maxlength="2000" placeholder="이 구간이 무엇을 하는지(비워 둘 수 있습니다)" value=${card.intent} onInput=${(e) => N.editCard({ intent: e.target.value })}></textarea></div>
    ${sg && sg.boundary.length ? html`<div class="field"><label>경계</label><div class="acts-row">${sg.boundary.map((t, i) => html`${i ? html`<${Icon} name="chevron-right" size=${15} />` : null}<span class="chip id">${t}</span>`)}</div></div>` : null}
    ${sg && sg.overlaps.length ? html`<${Notice} kind="info">${sg.overlaps.map((o) => o.node_id + " 구간과 " + o.shared + "개가 겹칩니다").join(" · ")}. 겹쳐도 만들 수 있습니다.<//>` : null}
    ${sg && sg.asked > sg.count ? html`<${Notice} kind="warn" icon="alert-triangle">고른 ${sg.asked}개 가운데 ${sg.asked - sg.count}개는 같은 구성요소라 합쳤습니다.<//>` : null}
    ${card.error ? html`<${Notice} kind="err" icon="alert-triangle">${card.error}<//>` : null}
    <div class="acts-row"><${Btn} kind="primary" icon="check" label="만들기" disabled=${card.busy || !card.name.trim()} onClick=${submit}>만들기 <kbd>Enter</kbd><//>
      <${Btn} label="취소" onClick=${N.closeCard}>취소<//></div></form>`;
}

function OutsideChip() {
  const view = N.useNodes((s) => s.sheetView);
  const showOutside = N.useNodes((s) => s.showOutside);
  const sheet = shell.get().sheet;
  if (!view || view.graph_id !== sheet || !view.segments.length) return null;
  return html`<div class="float chipbar">
    <button type="button" class="chip" aria-pressed=${showOutside ? "true" : "false"} title="구간에 들지 않은 구성요소를 흐리게 보입니다" onClick=${() => N.nodes.set({ showOutside: !showOutside })}>
      <${Icon} name="eye" size=${14} /> 구간 밖 ${view.outside_ids.length}개</button></div>`;
}

export function NodeOverlay() {
  N.wire();
  return html`<${OutsideChip} /><${SelectionBar} /><${NewNodeCard} /><${Toolbar} />`;
}
