// 도면 고치기(canvas/edit.js) 웹 시험: 엔진 대역으로 명령 모양·확인 묻기·낡은 판·도구 흐름·카드 그리기를 본다.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as E from "../js/canvas/edit.js";

const tick = async () => { for (let i = 0; i < 600; i++) await Promise.resolve(); };
const sent = [];
let replies = [];

const HEAD = { ok: true, graph_id: "graph-A", ver: "v1", ops: [{ op_id: "c-0001", op: "set_tag", label: "태그", local_id: "n1", by: "검토자", at: "t", status: "applied", reason: null }],
  undoable: ["c-0001"], redo: null, graph_stale: false, unknowns: 0,
  kinds: [{ kind: "manual_valve", label: "수동 밸브", category: "valve" }, { kind: "check_valve", label: "체크 밸브", category: "valve" }],
  relation_kinds: [{ kind: "physical_connection", label: "공정 배관" }] };
const NODE = { ok: true, graph_id: "graph-A", local_id: "n1", type: "node", kind: "manual_valve", kind_label: "수동 밸브", tag: "<b>RC-V1</b>", manual: false,
  human_edit: [], unknowns: [{ check: "missing_kind", reason: "종류 미확인" }], ver: "v1", positions: [], impact: { sheet: "confirmed", nodes: [{ node_id: "S2", state: "locked" }] } };
const REL = { ok: true, graph_id: "graph-A", local_id: "p1", type: "relation", kind: "physical_connection", tag: "L1", manual: false, human_edit: [], unknowns: [], ver: "v1",
  impact: { sheet: null, nodes: [] }, relation_kind: "physical_connection", ends: { source: { node: "n1", status: "connected" }, target: { node: "n2", status: "connected" } },
  flow: { from: "n1", to: "n2", basis: "drawio" }, flow_allowed: true };

function install() {
  sent.length = 0;
  window.hazopBridge = {
    send(text) {
      const m = JSON.parse(text);
      if (m.t !== "cmd") return;
      sent.push(m);
      const r = replies.shift() || { ok: true, data: { ver: "v2", notes: [], recheck: [], graph_stale: false } };
      Promise.resolve().then(() => deliver(JSON.stringify(Object.assign({ t: "reply", id: m.id }, r))));
    },
    setHandler() {},
  };
  window.fetch = async (url) => {
    const u = String(url), body = (d) => ({ ok: true, status: 200, json: async () => d });
    if (u === "/api/edit/graph-A") return body(HEAD);
    if (u === "/api/edit/graph-A/item/n1") return body(NODE);
    if (u === "/api/edit/graph-A/item/p1") return body(REL);
    return { ok: false, status: 404, json: async () => ({}) };
  };
}

async function setup() {
  install();
  replies = [];
  store.set({ sheet: "graph-A", bubble: null });
  E.wire();
  E.setOn(true);
  await tick();
}

function mount(v) { const d = document.createElement("div"); document.body.appendChild(d); render(v, d); return d; }

export const tests = [
  { name: "도면 고치기: 켜면 판을 읽고, 고치기를 켠 채 누른 구성요소는 말풍선 대신 고치기 카드(태그는 글자로만, 확정·잠금 영향 표시)", async run(assert) {
    await setup();
    assert.equal(E.edit.get().head.ver, "v1");
    store.set({ bubble: { sheet: "graph-A", id: "n1", tag: "x" } });
    await tick();
    assert.equal(store.get().bubble, null);
    const host = mount(html`<${E.EditOverlay} />`);
    await tick();
    const card = host.querySelector(".edit-card");
    assert(card && card.querySelector("#ec-tag").value === "<b>RC-V1</b>" && !card.querySelector(".ec-h b b"), "태그는 글자로만");
    assert(card.textContent.includes("확정 상태입니다") && card.textContent.includes("S2"), card.textContent.slice(0, 200));
    assert(host.querySelector(".edit-pill") && !host.querySelector(".edit-pill .tbtn"), "늘 떠 있는 것은 작은 알약 하나");
    host.remove();
    E.setOn(false);
  } },
  { name: "도면 고치기: 태그 고침은 화면이 본 판(ver)과 도면 안 id로 edit.apply를 보내고, 답 뒤 판을 다시 읽는다", async run(assert) {
    await setup();
    await E.loadItem("graph-A", "n1");
    await E.apply("set_tag", "n1", { tag: "RC-V9" });
    await tick();
    const m = sent.find((x) => x.name === "edit.apply");
    assert.equal([m.args.graph_id, m.args.ver, m.args.op, m.args.local_id, m.args.value.tag, m.args.confirm], ["graph-A", "v1", "set_tag", "n1", "RC-V9", false]);
    assert(!("by" in m.args) && !("at" in m.args), "누가·언제는 엔진이 채운다");
    E.setOn(false);
  } },
  { name: "도면 고치기: 엔진이 확인을 물으면(지우기·태그 겹침) 글을 띄우고, '그래도 하기'는 confirm으로 다시 보낸다", async run(assert) {
    await setup();
    await E.loadItem("graph-A", "n1");
    replies = [{ ok: false, error: { code: "needs_confirm", message: "n1을(를) 지웁니다. 확정·잠금 구간 S2" } }];
    await E.apply("delete_node", "n1");
    await tick();
    const ask = E.edit.get().ask;
    assert(ask && ask.message.includes("S2"), JSON.stringify(ask));
    await ask.run();
    await tick();
    const last = sent.filter((x) => x.name === "edit.apply").pop();
    assert.equal([last.args.op, last.args.confirm], ["delete_node", true]);
    assert.equal(E.edit.get().item, null);
    E.setOn(false);
  } },
  { name: "도면 고치기: 낡은 판이면 다시 읽고 오류 글을 보인다", async run(assert) {
    await setup();
    replies = [{ ok: false, error: { code: "stale", message: "다른 곳에서 바뀌어 저장하지 않았습니다" } }];
    await E.apply("set_tag", "n1", { tag: "X" });
    await tick();
    assert(E.edit.get().error.includes("바뀌어"));
    E.setOn(false);
  } },
  { name: "도면 고치기: 켜 둔 동안 누르기는 고치기로(구성요소 → 카드, 빈 곳 → 기기 놓기 카드), 연결 추가·끝 잇기·경로 다시 그리기 Enter/Esc", async run(assert) {
    await setup();
    let props = null;
    function Probe() { props = E.useEditCanvas("graph-A"); return html`<i></i>`; }
    const host = mount(html`<${Probe} />`);
    await tick();
    assert.equal(props.editTool, "select");
    props.onEditPick({ point: [120, 80], id: null, layer: null });
    assert.equal(E.edit.get().addAt, [120, 80]);
    E.setField({ newKind: "check_valve", newTag: "RC-V77" });
    E.addNodeHere();
    await tick();
    let m = sent.filter((x) => x.name === "edit.apply").pop();
    assert.equal([m.args.op, m.args.local_id, m.args.value.kind, m.args.value.tag, m.args.value.at], ["add_node", null, "check_valve", "RC-V77", [120, 80]]);
    props.onEditPick({ point: [0, 0], id: "n1", layer: "symbol" });
    await tick();
    assert.equal(E.edit.get().item.local_id, "n1");
    E.startConnect("n1");
    props.onEditPick({ point: [0, 0], id: "p1", layer: "pipe" });
    assert(E.edit.get().error.includes("기기를 누르세요"));
    props.onEditPick({ point: [0, 0], id: "n2", layer: "symbol" });
    await tick();
    m = sent.filter((x) => x.name === "edit.apply").pop();
    assert.equal([m.args.op, m.args.value.from, m.args.value.to], ["add_relation", "n1", "n2"]);
    await E.loadItem("graph-A", "p1");
    E.setField({ end: "target" }); E.setTool("endpoint");
    props.onEditPick({ point: [0, 0], id: "n3", layer: "symbol" });
    await tick();
    m = sent.filter((x) => x.name === "edit.apply").pop();
    assert.equal([m.args.op, m.args.local_id, m.args.value.end, m.args.value.node], ["set_endpoint", "p1", "target", "n3"]);
    await E.loadItem("graph-A", "p1");
    E.setTool("path");
    props.onEditPick({ point: [10, 10], id: null, layer: null });
    props.onEditPick({ point: [10, 50.555], id: "n1", layer: "symbol" });
    await tick();
    assert.equal(props.editPreview.points, [[10, 10], [10, 50.56]]);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();
    m = sent.filter((x) => x.name === "edit.apply").pop();
    assert.equal([m.args.op, m.args.local_id, m.args.value.points], ["set_path", "p1", [[10, 10], [10, 50.56]]]);
    E.setTool("path");
    props.onEditPick({ point: [1, 1], id: null, layer: null });
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await tick();
    assert.equal([E.edit.get().tool, E.edit.get().points], ["select", []]);
    const undos = sent.filter((x) => x.name === "edit.undo").length;
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true }));
    await tick();
    assert.equal(sent.filter((x) => x.name === "edit.undo").length, undos + 1, "Ctrl+Z는 되돌리기");
    host.remove();
    E.setOn(false);
  } },
  { name: "도면 고치기: 되돌리기는 되돌릴 수 있는 마지막 고침, 다시 하기는 edit.redo", async run(assert) {
    await setup();
    await E.undoLast();
    await tick();
    let m = sent.filter((x) => x.name === "edit.undo").pop();
    assert.equal([m.args.op_id, m.args.ver], ["c-0001", "v1"]);
    await E.redo();
    await tick();
    m = sent.filter((x) => x.name === "edit.redo").pop();
    assert.equal(m.args.graph_id, "graph-A");
    E.setOn(false);
  } },
];
