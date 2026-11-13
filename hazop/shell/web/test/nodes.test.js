// 구간(2단계) 웹 시험: 순수 계산, 엔진 잇기(대역 브릿지), 패널·고르기 막대·새 구간 카드 그리기.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as L from "../js/panels/nodes_logic.js";
import * as N from "../js/panels/nodes_state.js";
import { NodesPanel } from "../js/panels/nodes.js";
import { NodeOverlay, useNodeCanvas } from "../js/canvas/nodes_canvas.js";

const sent = [];
const tick = (ms = 200) => new Promise((r) => setTimeout(r, ms));

// ---- 엔진 대역: 읽기(fetch)와 명령(hazopBridge)
let engine;
function resetEngine() {
  engine = {
    list: { available: true, set_rev: 4, graph_version: "v", stale: false, read_only: null, pending_ai: 1, outside: { count: 30, total: 40 }, batches: [
      { batch_id: "B2", origin: "ai", kind: "apply", at: "2026-11-13T01:00:00Z", request_text: "대표 구간 만들어 줘", undone: false, ops: ["add"], node_ids: ["S2"] },
      { batch_id: "B1", origin: "user", kind: "apply", at: "2026-11-13T00:00:00Z", request_text: null, undone: false, ops: ["add"], node_ids: ["S1"] }], ver: "4",
    nodes: [
      { node_id: "S1", name: "저온관 <b>RC-L003</b>", state: "applied", origin: "user", name_by: "user", rev: 2, basis: "x", batch_id: "B1", design_intent: { text: "냉각재를 보냄", by: "user" }, count: 6,
        sheets: [{ graph_id: "graph-A", n: 6 }], overlaps: [{ node_id: "S2", shared: 2 }], confirmed: null, locked: null, screen: null },
      { node_id: "S2", name: "교차관", state: "applied", origin: "ai", name_by: "ai", rev: 1, basis: "y", batch_id: "B2", design_intent: { text: "초안 의도", by: "ai" }, count: 5,
        sheets: [{ graph_id: "graph-A", n: 3 }, { graph_id: "graph-B", n: 2 }], overlaps: [{ node_id: "S1", shared: 2 }], confirmed: null, locked: null, screen: null },
      { node_id: "S3", name: "확정된 구간", state: "confirmed", origin: "user", name_by: "user", rev: 3, basis: "z", batch_id: "B1", design_intent: null, count: 2,
        sheets: [{ graph_id: "graph-B", n: 2 }], overlaps: [], confirmed: { by: "홍길동", at: "2026-11-13T02:00:00Z", rev: 3 }, locked: null, screen: null }] },
    sheet: { graph_id: "graph-A", set_rev: 4, segments: [{ node_id: "S1", name: "a", state: "applied", ids: ["n1", "n2"] }, { node_id: "S2", name: "b", state: "applied", ids: ["n2", "n3"] }], outside_ids: ["n4", "n5"] },
    reply: (name, args) => ({ ok: true, data: { set_rev: 5, batch_id: "B3", node_ids: ["S4"] } }),
  };
  sent.length = 0;
}

function mount(vnode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  render(vnode, host);
  return host;
}

function installStubs() {
  window.hazopBridge = {
    send(text) {
      const m = JSON.parse(text);
      if (m.t !== "cmd") return;
      sent.push(m);
      const r = engine.reply(m.name, m.args);
      setTimeout(() => deliver(JSON.stringify(Object.assign({ t: "reply", id: m.id }, r))), 0);
    },
    setHandler() {},
  };
  window.fetch = async (url) => {
    const u = String(url);
    const body = (data) => ({ ok: true, status: 200, json: async () => data });
    if (u === "/api/nodes") return body(engine.list);
    if (u.startsWith("/api/nodes/sheet/")) return body(engine.sheet);
    if (u.startsWith("/api/nodes/node/")) return body({ node_id: u.split("/").pop(), members: [{ sheet: "graph-A", id: "n1", tag: "RC-RV01", kind: "reactor_vessel", shared: [] }], members_total: 6,
      boundary: ["RC-RV01", "RC-SG01"], majors: ["RC-RV01", "RC-SG01"], majors_total: 2, history: [{ batch_id: "B1", origin: "user", ops: ["add"], undone: false }] });
    return { ok: false, status: 404, json: async () => ({}) };
  };
}

async function setup() {
  installStubs();
  resetEngine();
  store.set({ sheet: "graph-A", drawings: { drawings: [{ graph_id: "graph-A", drawing_number: "SNP-M-101", name: "a" }, { graph_id: "graph-B", drawing_number: "SNP-M-102", name: "b" }], documents: [], project_id: "P", rev: "r" } });
  N.nodes.set({ focus: null, detail: null, selection: [], card: null, mode: "pan", scope: "sheet", checked: [], error: null, needArchive: null, busy: false });
  N.wire();
  await N.refresh();
}

const lastCmd = () => sent[sent.length - 1];

export const tests = [
  { name: "구간 계산: 상태 칩(AI 적용됨·적용됨·확정·잠금)과 수정 가능 여부", run(assert) {
    assert.equal(L.stateChip({ state: "applied", origin: "ai" }).label, "AI 적용됨");
    assert.equal(L.stateChip({ state: "applied", origin: "user" }).label, "적용됨");
    assert.equal(L.stateChip({ state: "confirmed", origin: "ai" }).label, "확정");
    assert.equal(L.stateChip({ state: "locked" }).label, "잠금");
    assert(L.canEdit({ state: "applied" }) && !L.canEdit({ state: "confirmed" }) && !L.canEdit({ state: "locked" }) && !L.canEdit(null));
  } },
  { name: "구간 계산: 도면에 칠할 구간은 강조한 것만 active, 색은 목록 자리 기준", run(assert) {
    const list = [{ node_id: "S1" }, { node_id: "S2" }];
    const segs = L.sheetSegments({ segments: [{ node_id: "S2", ids: ["a"] }, { node_id: "S1", ids: ["b"] }] }, list, "S1");
    assert.equal(segs.map((s) => [s.node_id, s.active]), [["S2", false], ["S1", true]]);
    assert(segs[0].color.includes("--seg2") && segs[1].color.includes("--seg1"), "색 " + segs[0].color + segs[1].color);
    assert.equal(L.sheetSegments(null, list, null), []);
  } },
  { name: "구간 계산: 도면 범위 글, 대상의 판, Esc 단계, 한 글자 키", run(assert) {
    const dr = [{ graph_id: "graph-A", drawing_number: "SNP-M-101" }];
    assert.equal(L.rangeText({ sheets: [{ graph_id: "graph-A", n: 1 }] }, dr), "SNP-M-101");
    assert.equal(L.rangeText({ sheets: [{ graph_id: "graph-A", n: 1 }, { graph_id: "graph-X", n: 1 }] }, dr), "SNP-M-101 외 1장");
    assert.equal(L.targetsOf([{ node_id: "S1", rev: 2, state: "applied", name: "x" }], ["S1", "S9"]), [{ node_id: "S1", rev: 2, state: "applied" }]);
    assert.equal(L.escStep({ card: true, focus: "S1", mode: "pick", selection: [] }), "card");
    assert.equal(L.escStep({ card: false, focus: "S1", mode: "pick", selection: ["a"] }), "focus");
    assert.equal(L.escStep({ card: false, focus: null, mode: "pick", selection: ["a"] }), null);
    assert.equal(L.escStep({ card: false, focus: null, mode: "pick", selection: [] }), "pan");
    const k = (key, extra) => L.keyAction(Object.assign({ key }, extra), { selection: ["a"], typing: false, panelWide: false });
    assert.equal([k("v"), k("S"), k("f"), k("Enter"), k("Enter", { ctrlKey: true }), k("x")], ["pan", "pick", "fit", "card", null, null]);
    assert.equal(L.keyAction({ key: "v" }, { selection: [], typing: true, panelWide: false }), null);
    assert.equal(L.keyAction({ key: "Enter" }, { selection: [], typing: false, panelWide: false }), null);
  } },
  { name: "구간 연결: 명령은 set_rev와 대상의 rev·state를 함께 보내고, 성공하면 다시 읽는다", async run(assert) {
    await setup();
    const reads = [];
    const orig = window.fetch;
    window.fetch = async (u) => { reads.push(String(u)); return orig(u); };
    const r = await N.rename("S1", "새 이름");
    window.fetch = orig;
    const m = lastCmd();
    assert.equal(m.name, "nodes.rename");
    assert.equal(m.args, { set_rev: 4, node_id: "S1", name: "새 이름", targets: [{ node_id: "S1", rev: 2, state: "applied" }] });
    assert(r && r.batch_id === "B3", "답");
    assert(reads.includes("/api/nodes") && reads.some((u) => u.startsWith("/api/nodes/sheet/")), "다시 읽음 " + reads.join(","));
    assert(!("by" in m.args) && !("at" in m.args) && !("author" in m.args), "웹은 by·at·author를 보내지 않음");
  } },
  { name: "구간 연결: 거절 사유(엔진 문장)가 error에 남고 stale이면 다시 읽는다", async run(assert) {
    await setup();
    engine.reply = () => ({ ok: false, error: { code: "locked", message: "S3 확정 구간은 고칠 수 없음(사람이 확정을 해제한 뒤)" } });
    const r = await N.rename("S3", "x");
    assert(r === null, "실패는 null");
    assert.equal(N.nodes.get().error, "S3 확정 구간은 고칠 수 없음(사람이 확정을 해제한 뒤)");
    let reads = 0;
    const orig = window.fetch;
    window.fetch = async (u) => { if (String(u) === "/api/nodes") reads++; return orig(u); };
    engine.reply = () => ({ ok: false, error: { code: "stale", message: "구간이 다른 곳에서 바뀌어 저장하지 않았습니다." } });
    await N.rename("S1", "x");
    window.fetch = orig;
    assert(reads >= 1, "stale이면 다시 읽음");
    assert(N.nodes.get().error.includes("바뀌어 저장하지 않았습니다"));
  } },
  { name: "구간 패널: 목록(상태 칩·겹침·도면 범위)이 이 도면 구간만, 이름은 글로만", async run(assert) {
    await setup();
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    const rows = host.querySelectorAll(".nrow");
    assert.equal(rows.length, 2);                       // 이 도면(graph-A)의 S1·S2, S3은 graph-B
    const text = host.textContent;
    assert(text.includes("AI 적용됨") && text.includes("겹침 1") && text.includes("SNP-M-101 외 1장") && text.includes("구간 밖 30"), text.slice(0, 300));
    assert(text.includes("<b>RC-L003</b>") && !host.querySelector(".nrow b b"), "이름의 태그가 HTML로 해석되지 않음");
    assert(text.includes("채팅이 만든 구간 1개가 아직 확인 전"), "AI 구간 안내");
    N.nodes.set({ scope: "all" });
    await tick();
    assert.equal(host.querySelectorAll(".nrow").length, 3);
    host.remove();
  } },
  { name: "구간 패널: 구간을 누르면 강조·상세, 확정 구간은 고치기가 막힘, AI 초안 표시", async run(assert) {
    await setup();
    N.nodes.set({ scope: "all" });
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    host.querySelectorAll(".nrow-b")[1].click();         // S2
    await tick(220);
    assert.equal(N.nodes.get().focus, "S2");
    const det = host.querySelector(".ndetail");
    assert(det && det.textContent.includes("AI 초안"), "AI 초안 표시");
    assert(det.textContent.includes("RC-RV01") && det.textContent.includes("겹침"), "경계·겹침");
    host.querySelectorAll(".nrow-b")[2].click();         // S3 확정
    await tick(220);
    const edit = [...host.querySelectorAll(".ndetail button")].find((b) => b.getAttribute("aria-label") === "이름 고치기");
    assert(edit && edit.disabled, "확정 구간은 이름 고치기가 꺼짐");
    assert(host.textContent.includes("확정 해제") && host.textContent.includes("분석 마침"), "확정 구간 동작");
    host.remove();
  } },
  { name: "구간 패널: 이름 고치기 → 명령, 지우기가 판정 때문에 거절되면 보관 선택지", async run(assert) {
    await setup();
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    host.querySelectorAll(".nrow-b")[0].click();
    await tick(220);
    const by = (label) => [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === label);
    by("이름 고치기").click();
    await tick();
    const input = host.querySelector('input[aria-label="이름"]');
    input.value = "고친 이름";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
    by("이름 저장").click();
    await tick(220);
    assert.equal([lastCmd().name, lastCmd().args.name], ["nodes.rename", "고친 이름"]);
    engine.reply = () => ({ ok: false, error: { code: "rejected", message: "S1: 분석 칸에 판정이 있어 지울 수 없음(보관을 고를 것)" } });
    by("S1 지우기").click();
    await tick(220);
    assert(host.textContent.includes("분석 칸에 판정이 있어 지울 수 없음"), "사유 표시");
    assert(!!by("보관하고 지우기"), "보관 선택지");
    engine.reply = () => ({ ok: true, data: { set_rev: 6, batch_id: "B4", node_ids: ["S1"] } });
    by("보관하고 지우기").click();
    await tick(220);
    assert.equal([lastCmd().name, lastCmd().args.archive], ["nodes.remove", true]);
    host.remove();
  } },
  { name: "구간 패널: 최근 묶음 되돌리기와 나머지도 나누기(채팅)", async run(assert) {
    await setup();
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    const by = (label) => [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === label);
    by("B2 되돌리기").click();
    await tick(220);
    assert.equal([lastCmd().name, lastCmd().args.batch_id], ["nodes.undo", "B2"]);
    assert(!("targets" in lastCmd().args), "묶음 되돌리기는 대상 판 없이 set_rev만");
    by("나머지도 나누기").click();
    await tick(220);
    assert.equal(lastCmd().name, "chat.ask");
    host.remove();
  } },
  { name: "도면 고르기: 'n개 고름' 막대 → 구간 만들기 카드 → 만들기 명령(sheet·local_id)", async run(assert) {
    await setup();
    engine.reply = (name) => (name === "nodes.suggest"
      ? { ok: true, data: { count: 3, asked: 3, name: "RC-RV01 → RC-SG01", majors: ["RC-RV01", "RC-SG01"], boundary: ["RC-RV01", "RC-SG01"], overlaps: [{ node_id: "S1", shared: 1 }], set_rev: 4 } }
      : { ok: true, data: { set_rev: 5, batch_id: "B3", node_ids: ["S4"] } });
    const host = mount(html`<${NodeOverlay} />`);
    N.setSelection(["n1", "n2", "n3"]);
    await tick();
    assert(host.textContent.includes("3개 고름"), "막대");
    [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "구간 만들기").click();
    await tick(220);
    assert.equal(lastCmd().name, "nodes.suggest");
    const card = host.querySelector(".newnode");
    assert(card && card.textContent.includes("새 구간 S4") && card.textContent.includes("S1 구간과 1개가 겹칩니다") && card.querySelector("#nn-name").value === "RC-RV01 → RC-SG01", "카드 " + (card && card.textContent));
    const intent = card.querySelector("#nn-intent");
    intent.value = "원자로 출구를 증기발생기로 보냄";
    intent.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
    [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "만들기").click();
    await tick(260);
    const m = lastCmd();
    assert.equal(m.name, "nodes.create");
    assert.equal(m.args, { sheet: "graph-A", ids: ["n1", "n2", "n3"], name: "RC-RV01 → RC-SG01", design_intent: "원자로 출구를 증기발생기로 보냄", set_rev: 4 });
    assert.equal(N.nodes.get().selection, []);
    assert(!host.querySelector(".newnode"), "카드가 닫힘");
    assert.equal(N.nodes.get().focus, "S4");
    host.remove();
  } },
  { name: "도면 고르기: 강조한 구간에 더하기·빼기는 적용됨 구간에서만, 확정이면 숨김", async run(assert) {
    await setup();
    const host = mount(html`<${NodeOverlay} />`);
    N.nodes.set({ focus: "S1" });
    N.setSelection(["n9"]);
    await tick();
    const labels = () => [...host.querySelectorAll("button")].map((b) => b.getAttribute("aria-label"));
    assert(labels().includes("S1에 더하기") && labels().includes("S1에서 빼기"));
    [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "S1에 더하기").click();
    await tick(220);
    assert.equal([lastCmd().name, lastCmd().args.node_id, lastCmd().args.ids, lastCmd().args.sheet], ["nodes.add_members", "S1", ["n9"], "graph-A"]);
    N.nodes.set({ focus: "S3" });
    N.setSelection(["n9"]);
    await tick();
    assert(!labels().includes("S3에 더하기"), "확정 구간에는 더하기가 없음");
    host.remove();
  } },
  { name: "도면 연결: 구간 칠하기는 이 도면의 구간·구간 밖을 <Sheet> props로, Esc는 카드→강조→이동 모드 순", async run(assert) {
    await setup();
    let props = null;
    function Probe() { props = useNodeCanvas("graph-A").props; return html`<i></i>`; }
    const host = mount(html`<${Probe} />`);
    await tick();
    assert.equal(props.segments.map((s) => [s.node_id, s.ids, s.active]), [["S1", ["n1", "n2"], false], ["S2", ["n2", "n3"], false]]);
    assert.equal(props.outside, ["n4", "n5"]);
    assert.equal(props.mode, "pan");
    N.nodes.set({ focus: "S2", mode: "pick" });
    await tick();
    assert.equal(props.segments.map((s) => s.active), [false, true]);
    props.onEsc();                                  // 강조를 끈다
    assert.equal(N.nodes.get().focus, null);
    props.onEsc();                                  // 고른 것이 없으니 이동 모드로
    assert.equal(N.nodes.get().mode, "pan");
    props.onSegmentClick({ node_id: "S1" });
    assert.equal([N.nodes.get().focus, store.get().panel], ["S1", "nodes"]);
    props.onSelection({ selected: ["n1"], via: "box" });
    assert.equal(N.nodes.get().selection, ["n1"]);
    store.set({ panel: null });
    host.remove();
  } },
  { name: "구간 연결: 엔진의 changed(nodes) 알림을 받으면 다시 읽는다", async run(assert) {
    await setup();
    engine.list = Object.assign({}, engine.list, { set_rev: 9, nodes: engine.list.nodes.slice(0, 1) });
    deliver(JSON.stringify({ t: "changed", topic: "nodes", rev: 9 }));
    await tick(220);
    assert.equal([N.nodes.get().list.set_rev, N.nodes.get().list.nodes.length], [9, 1]);
  } },
];
