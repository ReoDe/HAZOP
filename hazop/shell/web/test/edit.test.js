// 도면 고치기(canvas/edit.js) 웹 시험: 엔진 대역으로 명령 모양·확인 묻기·낡은 판·도구 흐름·카드 그리기를 본다.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as E from "../js/canvas/edit.js";
import * as L from "../js/canvas/link_card.js";

const tick = async () => { for (let i = 0; i < 600; i++) await Promise.resolve(); };
const settle = async () => { await new Promise((r) => setTimeout(r, 30)); await tick(); await new Promise((r) => setTimeout(r, 30)); await tick(); };   // useEffect는 다음 틀에서 돈다
const sent = [];
let replies = [];

const HEAD = { ok: true, graph_id: "graph-A", ver: "v1", ops: [{ op_id: "c-0001", op: "set_tag", label: "태그", local_id: "n1", by: "검토자", at: "t", status: "applied", reason: null }],
  undoable: ["c-0001"], redo: null, graph_stale: false, unknowns: 0,
  kinds: [{ kind: "manual_valve", label: "수동 밸브", category: "valve" }, { kind: "check_valve", label: "체크 밸브", category: "valve" }],
  relation_kinds: [{ kind: "physical_connection", label: "공정 배관" }] };
const NODE = { ok: true, graph_id: "graph-A", local_id: "n1", type: "node", kind: "manual_valve", kind_label: "수동 밸브", tag: "<b>RC-V1</b>", manual: false,
  human_edit: [], unknowns: [{ check: "missing_kind", reason: "종류 미확인" }], ver: "v1", base: "fp-n1", positions: [], impact: { sheet: "confirmed", nodes: [{ node_id: "S2", state: "locked" }] } };
const REL = { ok: true, graph_id: "graph-A", local_id: "p1", type: "relation", kind: "physical_connection", tag: "L1", manual: false, human_edit: [], unknowns: [], ver: "v1",
  impact: { sheet: null, nodes: [] }, relation_kind: "physical_connection", ends: { source: { node: "n1", status: "connected" }, target: { node: "n2", status: "connected" } },
  flow: { from: "n1", to: "n2", basis: "drawio" }, flow_allowed: true };

const CONT = { ok: true, graph_id: "graph-A", local_id: "c1", type: "node", kind: "continuation", kind_label: "도면 연결", tag: null, manual: false,
  human_edit: [], unknowns: [], ver: "v1", base: "fp-c1", positions: [], impact: { sheet: null, nodes: [] } };
const LINK = { ok: true, graph_id: "graph-A", ver: "lv1",
  point: { local_id: "c1", label: "TO <i>B</i>", drawing_number: "A-101", line_no: "RC-L010", status: "unlinked", reason: "no_counterpart", reason_text: "맞은편 없음",
    origin: "auto", op: null, peer: null, base: "pb1" },
  candidates: [{ graph_id: "graph-B", local_id: "c9", drawing_number: "A-102", label: "FROM A-101", line_no: "RC-L010", to_drawing: "A-101", linked: false, peer_drawing: null, warn: [] },
    { graph_id: "graph-C", local_id: "c5", drawing_number: "A-103", label: "FROM X", line_no: "RC-L099", to_drawing: "A-105", linked: true, peer_drawing: "A-105", warn: ["상대 도면이 다름(A-105를 가리킴)"] }],
  more: 0, stale: [{ op_id: "sl-old", reason: "가리키는 연결점이 프로젝트 도면에 없음", op: "unlink", by: "B", at: "t", ends: [{ drawing_number: "A-101", source_object_id: "gone" }] }] };
const linkReads = [];

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
    if (u === "/api/edit/graph-A/item/c1") return body(CONT);
    if (u.startsWith("/api/links/graph-A/c1")) { linkReads.push(u); return body(LINK); }
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
    assert.equal([m.args.graph_id, m.args.ver, m.args.op, m.args.local_id, m.args.value.tag, m.args.confirm, m.args.base], ["graph-A", "v1", "set_tag", "n1", "RC-V9", undefined, "fp-n1"]);
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
    assert.equal([last.args.op, last.args.confirm], ["delete_node", "n1을(를) 지웁니다. 확정·잠금 구간 S2"], "확인한 글을 그대로 보낸다(엔진이 지금 글과 견준다)");
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
    props.onEditPick({ point: [120, 80], orig: [100, 70], id: null, layer: null });
    assert.equal(E.edit.get().addAt, [100, 70], "정리된 보기에서 누른 자리는 읽은 좌표로 저장한다");
    E.setField({ newKind: "check_valve", newTag: "RC-V77" });
    E.addNodeHere();
    await tick();
    let m = sent.filter((x) => x.name === "edit.apply").pop();
    assert.equal([m.args.op, m.args.local_id, m.args.value.kind, m.args.value.tag, m.args.value.at], ["add_node", null, "check_valve", "RC-V77", [100, 70]]);
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
    props.onEditPick({ point: [10, 10], orig: [12, 10], id: null, layer: null });
    props.onEditPick({ point: [10, 50.555], id: "n1", layer: "symbol" });
    await tick();
    assert.equal(props.editPreview.points, [[10, 10], [10, 50.56]], "미리 보기는 그린 자리");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();
    m = sent.filter((x) => x.name === "edit.apply").pop();
    assert.equal([m.args.op, m.args.local_id, m.args.value.points], ["set_path", "p1", [[12, 10], [10, 50.56]]], "저장은 읽은 좌표");
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
  { name: "도면 연결 짝: 오각형의 고치기 카드에 짝 칸이 붙고(라벨은 글자로만, 오래된 지정 표시), 후보를 골라 links.pair를 판·지문과 함께 보낸다", async run(assert) {
    await setup();
    linkReads.length = 0;
    await E.loadItem("graph-A", "c1");
    const host = mount(html`<${E.EditOverlay} />`);
    await settle();
    const sec = host.querySelector(".ec-link");
    assert(sec && sec.textContent.includes("미연결") && sec.textContent.includes("맞은편 없음"), sec ? sec.textContent : "칸 없음");
    assert(sec.textContent.includes("오래된 지정 1"), "원본이 바뀌어 적용하지 못한 지정을 알린다");
    assert(!host.querySelector(".ec-link i"), "도면 글은 글자로만");
    assert(!host.querySelector(".edit-pill .ec-link"), "늘 떠 있는 알약에는 붙지 않는다");
    L.links.set({ picking: true });
    await settle();
    const opts = host.querySelectorAll(".ec-cands li[role=option]");
    assert.equal(opts.length, 2);
    assert(opts[1].textContent.includes("지금 A-105와 짝"));
    opts[1].click();
    await settle();
    assert(host.querySelector(".ec-pick").textContent.includes("고른 후보: 상대 도면이 다름"), "상대 도면·배관 번호가 다른 후보는 고르면 경고");
    opts[0].click();
    await settle();
    assert(!host.querySelector(".ec-pick").textContent.includes("고른 후보:"));
    L.links.set({ reason: " 배관 번호 확인 " });
    await L.pairWith(L.links.get().picked);
    await tick();
    const m = sent.filter((x) => x.name === "links.pair").pop();
    assert.equal([m.args.graph_id, m.args.local_id, m.args.ver, m.args.base, m.args.peer_graph_id, m.args.peer_local_id, m.args.reason],
      ["graph-A", "c1", "lv1", "pb1", "graph-B", "c9", "배관 번호 확인"]);
    assert(!("by" in m.args), "지정한 사람은 엔진이 채운다");
    host.remove();
    E.setOn(false);
  } },
  { name: "도면 연결 짝: 엔진이 확인을 물으면 글을 띄우고 '그래도 하기'는 그 글을 confirm으로, 찾기는 q로 다시 읽고, 오래된 지정 빼기는 links.clear", async run(assert) {
    await setup();
    linkReads.length = 0;
    await L.loadLink("graph-A", "c1", "");
    replies = [{ ok: false, error: { code: "needs_confirm", message: "A-103 FROM X ↔ A-105 Y 짝이 풀립니다." } }];
    await L.pairWith(LINK.candidates[1], "");
    await tick();
    const ask = L.links.get().ask;
    assert(ask && ask.message.includes("풀립니다"), JSON.stringify(ask));
    await ask.run();
    await tick();
    const last = sent.filter((x) => x.name === "links.pair").pop();
    assert.equal(last.args.confirm, "A-103 FROM X ↔ A-105 Y 짝이 풀립니다.");
    await L.clearOp("sl-old");
    await tick();
    assert.equal(sent.filter((x) => x.name === "links.clear").pop().args.op_id, "sl-old");
    replies = [{ ok: false, error: { code: "stale", message: "그 사이 바뀌었습니다" } }];
    await L.unlinkPoint("");
    await tick();
    assert(L.links.get().error.includes("바뀌었습니다"));
    await L.loadLink("graph-A", "c1", "RC L010");
    assert(linkReads.some((u) => u.endsWith("?q=RC%20L010")), linkReads.join(" "));
    E.setOn(false);
  } },
];
