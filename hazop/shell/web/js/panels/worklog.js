// 구간 작업 기록(설정 화면): 묶음 목록과 묶음 단위 되돌리기.
import { html } from "../ui/html.js";
import { useLayoutEffect } from "../../vendor/hooks.module.js";
import { cmd } from "../bridge.js";
import { Btn } from "../ui/parts.js";
import * as N from "./nodes_state.js";

const when = (t) => (t ? String(t).replace("T", " ").replace(/:\d\d(\.\d+)?Z?$/, "") : "");
const OP_LABEL = { add: "만듦", edit: "고침", remove: "지움" };
const KIND_LABEL = { "discard_lost": "찾지 못한 구성요소 버림" };
const opsText = (ops, kind) => KIND_LABEL[kind] || (ops || []).map((o) => OP_LABEL[o] || o).join("·");

/** 설정의 '작업 기록': 구간 묶음 목록과 묶음 단위 되돌리기. 평소 되돌리기는 Ctrl+Z다. */
export function WorkLog() {
  N.wire();
  useLayoutEffect(() => { N.refresh(); }, []);
  const list = N.useNodes((s) => s.list);
  const busy = N.useNodes((s) => s.busy);
  const batches = list.batches.filter((b) => !b.undone).slice(0, 3);
  if (!batches.length) return null;
  const askRest = () => cmd("chat.ask", { text: "나머지 구간도 나눠 줘" }).catch((e) => N.nodes.set({ error: e.message }));
  return html`<div class="card"><h3>작업 기록</h3>${batches.map((b, i) => html`<div class="kv" key=${b.batch_id}>
    <div class="k"><b>${b.batch_id} · ${b.origin === "ai" ? "채팅" : "사람"} ${opsText(b.ops, b.kind)}</b><span>${b.node_ids.join(", ")}${b.request_text ? " · “" + b.request_text + "”" : ""} · ${when(b.at)}</span></div>
    <div class="acts-row">${b.origin === "ai" && i === 0 && list.pending_ai > 0 ? html`<${Btn} sm=${true} label="나머지도 나누기" title="채팅에 나머지 구간을 나누도록 시킵니다" onClick=${askRest}>나머지도 나누기<//>` : null}
      <${Btn} sm=${true} icon="arrow-back-up" label=${b.batch_id + " 되돌리기"} disabled=${busy} onClick=${() => N.undo(b.batch_id)}>되돌리기<//></div></div>`)}</div>`;
}
