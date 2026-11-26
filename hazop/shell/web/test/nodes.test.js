// 구간(2단계) 웹 시험: 순수 계산, 엔진 잇기(대역 브릿지), 패널·고르기 막대·새 구간 카드 그리기.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as L from "../js/panels/nodes_logic.js";
import * as N from "../js/panels/nodes_state.js";
import { NodesPanel } from "../js/panels/nodes.js";
import { NodeOverlay, useNodeCanvas } from "../js/canvas/nodes_canvas.js";

const sent = [];
// 숨은 페이지는 타이머를 1초 간격으로 늦추므로 기다림은 마이크로태스크로 한다(Preact의 다시 그리기·가짜 엔진 답이 모두 마이크로태스크다)
const tick = async () => { for (let i = 0; i < 600; i++) await Promise.resolve(); };

// ---- 엔진 대역: 읽기(fetch)와 명령(hazopBridge)
let engine;
function resetEngine() {
  engine = {
    list: { project_id: "P", available: true, set_rev: 4, graph_version: "v", stale: false, read_only: null, pending_ai: 1, outside: { count: 30, total: 40 }, batches: [
      { batch_id: "B2", origin: "ai", kind: "apply", at: "2026-11-13T01:00:00Z", request_text: "대표 구간 만들어 줘", undone: false, ops: ["add"], node_ids: ["S2"] },
      { batch_id: "B1", origin: "user", kind: "apply", at: "2026-11-13T00:00:00Z", request_text: null, undone: false, ops: ["add"], node_ids: ["S1"] }], ver: "4",
    nodes: [
      { node_id: "S1", name: "저온관 <b>RC-L003</b>", state: "applied", origin: "user", name_by: "user", rev: 2, basis: "x", batch_id: "B1", design_intent: { text: "냉각재를 보냄", by: "user" }, count: 6,
        sheets: [{ graph_id: "graph-A", n: 6 }], overlaps: [{ node_id: "S2", shared: 2 }], confirmed: null, locked: null, screen: null },
      { node_id: "S2", name: "교차관", state: "applied", origin: "ai", name_by: "ai", rev: 1, basis: "y", batch_id: "B2", design_intent: { text: "초안 의도", by: "ai" }, count: 5,
        sheets: [{ graph_id: "graph-A", n: 3 }, { graph_id: "graph-B", n: 2 }], overlaps: [{ node_id: "S1", shared: 2 }], confirmed: null, locked: null, screen: null,
        span: { range: "[101 → 102]", drawings: ["101", "102"], spans: true, display_name: "S2 교차관 [101 → 102]", by_drawing: { "SNP-M-101": 3, "SNP-M-102": 2 }, count: 5,
          continuations: [{ entity_id: "e1", drawing: "SNP-M-101", to_drawing: "SNP-M-102", to_node_ids: ["S3"], chip: "S3 → SNP-M-102에서 계속" }] } },
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
      Promise.resolve().then(() => deliver(JSON.stringify(Object.assign({ t: "reply", id: m.id }, r))));
    },
    setHandler() {},
  };
  window.fetch = async (url) => {
    const u = String(url);
    const body = (data) => ({ ok: true, status: 200, json: async () => data });
    if (u === "/api/nodes") return body(engine.list);
    if (u.startsWith("/api/nodes/sheet/")) return body(engine.sheet);
    if (u.startsWith("/api/nodes/node/")) return body({ node_id: u.split("/").pop(), members: [{ sheet: "graph-A", id: "n1", tag: "RC-RV01", kind: "reactor_vessel", kind_label: "원자로 용기", shared: [] }, { sheet: "graph-A", id: "n2", tag: null, kind: "manual_valve", kind_label: "수동 밸브", shared: [] }], members_total: 6,
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
  { name: "구간 만들기(U9): 만든 뒤에도 고르기 모드가 그대로다", async run(assert) {
    await setup();
    N.setMode("pick");
    N.setSelection(["n1", "n2"]);
    N.nodes.set({ card: { name: "새 구간", intent: "", busy: false, error: null, suggest: null } });
    const r = await N.submitCard();
    assert(r, "만들기 답");
    assert.equal(N.nodes.get().mode, "pick", "다음 구간을 바로 끌어 고른다");
    assert.equal(N.nodes.get().selection, [], "고른 것은 비운다");
  } },
  { name: "모두 확정(U9): 목록을 먼저 보이고, 한 번에 보내 막히면 하나씩 다시 보내 안 된 것과 까닭을 알린다", async run(assert) {
    await setup();
    const n = N.askConfirmAll();
    assert.equal(N.nodes.get().confirmAsk, ["S1", "S2"], "확정하지 않은 구간만(S3는 이미 확정)");
    assert.equal(n, 2);
    engine.reply = (name, args) => {
      if (name !== "nodes.confirm") return { ok: true, data: {} };
      if (args.node_ids.length > 1 || args.node_ids[0] === "S2") return { ok: false, error: { code: "failed", message: "겹치는 구간이 확정되어 있습니다" } };
      return { ok: true, data: { set_rev: 5, node_ids: args.node_ids } };
    };
    const r = await N.confirmMany(N.nodes.get().confirmAsk);
    assert.equal(r.ok, ["S1"]);
    assert.equal(r.failed.map((f) => f.node_id), ["S2"]);
    assert(N.nodes.get().error && N.nodes.get().error.includes("S2") && N.nodes.get().error.includes("겹치는"), N.nodes.get().error);
    assert.equal(N.nodes.get().confirmAsk, null, "확인 카드는 닫힌다");
    const sentConfirm = sent.filter((m) => m.name === "nodes.confirm").map((m) => m.args.node_ids);
    assert.equal(sentConfirm, [["S1", "S2"], ["S1"], ["S2"]], "한 번에, 그다음 하나씩(지금 있는 nodes.confirm만 씀)");
  } },
  { name: "모두 확정(검토 차단): 카드를 연 뒤 다른 곳에서 바뀐 구간은 사람이 본 판으로만 보내고, 바뀐 것은 확정하지 않는다", async run(assert) {
    await setup();
    N.askConfirmAll();                                                       // 사람이 본 판: set_rev 4, S1 rev 2, S2 rev 1
    engine.list.set_rev = 5;                                                  // 다른 곳에서 S2가 바뀜
    engine.list.nodes = engine.list.nodes.map((n) => (n.node_id === "S2" ? Object.assign({}, n, { rev: 2 }) : n));
    engine.reply = (name, args) => {                                          // 엔진 판 검사(api_nodes._check_targets)와 같은 대역
      if (name !== "nodes.confirm") return { ok: true, data: {} };
      if (args.set_rev !== engine.list.set_rev) return { ok: false, error: { code: "stale", message: "구간이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요." } };
      for (const t of args.targets || []) {
        const n = engine.list.nodes.find((x) => x.node_id === t.node_id);
        if (!n) return { ok: false, error: { code: "not_found", message: t.node_id + " 구간이 이미 없습니다." } };
        if (n.rev !== t.rev || n.state !== t.state) return { ok: false, error: { code: "stale", message: t.node_id + " 구간이 다른 곳에서 바뀌어 저장하지 않았습니다." } };
      }
      engine.list.set_rev += 1;
      engine.list.nodes = engine.list.nodes.map((n) => (args.node_ids.includes(n.node_id) ? Object.assign({}, n, { state: "confirmed" }) : n));
      return { ok: true, data: { set_rev: engine.list.set_rev, node_ids: args.node_ids } };
    };
    const r = await N.confirmMany(N.nodes.get().confirmAsk);
    assert.equal(r.ok, ["S1"], "바뀌지 않은 S1만");
    assert.equal(r.failed.map((f) => f.node_id), ["S2"]);
    const s2 = sent.filter((m) => m.name === "nodes.confirm" && m.args.node_ids.includes("S2")).flatMap((m) => m.args.targets.filter((t) => t.node_id === "S2").map((t) => t.rev));
    assert(s2.every((rev) => rev === 1), "S2는 사람이 본 판(rev 1)으로만 보냄: " + JSON.stringify(s2));
    assert(N.nodes.get().error.includes("바뀐 구간 1개는 확정하지 않았습니다"), N.nodes.get().error);
  } },
  { name: "모두 확정: 카드를 연 뒤 지워진 구간은 '이미 없습니다'로, 체크한 것이 확정된 구간뿐이면 아무것도 고르지 않는다", async run(assert) {
    await setup();
    N.askConfirmAll();
    engine.list.nodes = engine.list.nodes.filter((n) => n.node_id !== "S2");
    engine.list.set_rev = 5;
    engine.reply = (name, args) => {
      if (name !== "nodes.confirm") return { ok: true, data: {} };
      if (args.set_rev !== engine.list.set_rev) return { ok: false, error: { code: "stale", message: "판이 다름" } };
      const gone = (args.targets || []).find((t) => !engine.list.nodes.some((n) => n.node_id === t.node_id));
      if (gone) return { ok: false, error: { code: "not_found", message: gone.node_id + " 구간이 이미 없습니다." } };
      engine.list.set_rev += 1;
      return { ok: true, data: { set_rev: engine.list.set_rev } };
    };
    const r = await N.confirmMany(N.nodes.get().confirmAsk);
    assert.equal(r.failed.map((f) => [f.node_id, f.reason.includes("이미 없습니다")]), [["S2", true]]);
    await setup();
    N.nodes.set({ checked: ["S3"] });                                        // S3는 이미 확정
    assert.equal(N.draftIds(), [], "체크한 것이 모두 확정됐으면 확정하지 않은 구간 전체로 넘어가지 않는다");
  } },
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
    assert.equal([k("v"), k("S"), k("f"), k("Enter"), k("Enter", { ctrlKey: true }), k("x")], [null, null, "fit", "card", null, null], "이동·고르기 방식 단축키는 없다");
    assert.equal(L.keyAction({ key: "v" }, { selection: [], typing: true, panelWide: false }), null);
    assert.equal(L.keyAction({ key: "Enter" }, { selection: [], typing: false, panelWide: false }), null);
    assert.equal(L.keyAction({ key: "Enter" }, { selection: ["a"], typing: false, panelWide: false, card: true }), "submit", "카드가 열려 있으면 Enter는 만들기");
    assert.equal(L.keyAction({ key: "s" }, { selection: ["a"], typing: false, panelWide: false, card: true }), null);
  } },
  { name: "같은 구성요소의 구간을 다시 만들면 알림·카드·토스트 없이 이미 있는 그 구간을 고른 상태가 된다", async run(assert) {
    await setup();
    engine.reply = (name) => (name === "nodes.suggest" ? { ok: true, data: { name: "제안 이름", count: 2, asked: 2, boundary: [], overlaps: [] } }
      : name === "nodes.create" ? { ok: false, error: { code: "refused", message: "구성요소가 같은 구간 S1가 이미 있음" } } : { ok: true, data: { set_rev: 6 } });
    store.set({ toast: null });
    N.setMode("pick");
    N.setSelection(["n1", "n2"]);
    await N.openCard();
    await tick();
    const st = N.nodes.get();
    assert.equal(st.card, null, "빨간 카드가 남지 않는다");
    assert.equal(st.error, null, "패널 알림도 없다");
    assert.equal(store.get().toast, null, "토스트도 없다");
    assert.equal(st.focus, "S1", "이미 있는 구간을 고른 상태");
    assert.equal(st.selection, []);
    engine.reply = (name) => (name === "nodes.suggest" ? { ok: true, data: { name: "x", count: 2, asked: 2, boundary: [], overlaps: [] } }
      : { ok: false, error: { code: "refused", message: "다른 이유로 거절" } });
    N.setSelection(["n3"]);
    await N.openCard();
    await tick();
    assert(N.nodes.get().card && N.nodes.get().card.error.includes("다른 이유"), "다른 거절은 그대로 보인다");
    N.closeCard();
  } },
  { name: "구간 만들기(실제 창 4차): 끌기 → Enter 한 번에 제안 이름으로 만들고, 만든 카드에서 이름을 고쳐 Enter로 저장한다", async run(assert) {
    await setup();
    engine.reply = (name) => (name === "nodes.suggest" ? { ok: true, data: { name: "제안 이름", count: 2, asked: 2, boundary: [], overlaps: [] } }
      : name === "nodes.create" ? { ok: true, data: { set_rev: 5, node_ids: ["S4"], batch_id: "B9" } } : { ok: true, data: { set_rev: 6 } });
    N.setMode("pick");
    N.setSelection(["n1", "n2"]);
    const Keys = () => { useNodeCanvas("graph-A"); return null; };
    const host = mount(html`<${Keys} /><${NodeOverlay} />`);
    await tick();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();
    const created = sent.filter((m) => m.name === "nodes.create");
    assert.equal(created.length, 1, "Enter 한 번이 만들기: " + JSON.stringify(sent.map((m) => m.name)));
    assert.equal(created[0].args.name, "제안 이름");
    const c = N.nodes.get().card;
    assert(c && c.made === "S4" && c.batch === "B9", "만든 구간의 카드: " + JSON.stringify(c));
    assert.equal(N.nodes.get().mode, "pick", "고르기 모드는 그대로");
    N.editCard({ name: "저온관" });
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();
    const ren = sent.filter((m) => m.name === "nodes.rename");
    assert.equal(ren.map((m) => [m.args.node_id, m.args.name]), [["S4", "저온관"]], "고친 이름만 보낸다");
    assert.equal(N.nodes.get().card, null, "저장하면 닫힌다");
    host.remove();
  } },
  { name: "구간 만들기(실제 창 4차): 만든 카드의 되돌리기는 만든 묶음을 되돌리고, 안 고친 카드는 다음 고르기에서 닫힌다", async run(assert) {
    await setup();
    engine.reply = (name) => (name === "nodes.suggest" ? { ok: true, data: { name: "", count: 1, asked: 1, boundary: [], overlaps: [] } }
      : name === "nodes.create" ? { ok: true, data: { set_rev: 5, node_ids: ["S4"], batch_id: "B9" } } : { ok: true, data: { set_rev: 6 } });
    N.setMode("pick");
    N.setSelection(["n1"]);
    await N.openCard();
    assert.equal(sent.find((m) => m.name === "nodes.create").args.name, "구간 S4", "제안 이름이 없으면 기본 이름");
    await N.undoMade();
    assert.equal(sent.filter((m) => m.name === "nodes.undo").map((m) => m.args.batch_id), ["B9"]);
    assert.equal(N.nodes.get().card, null);
    N.setSelection(["n2"]);
    await N.openCard();
    N.setSelection(["n3"]);
    assert.equal(N.nodes.get().card, null, "안 고친 카드는 다음 고르기에서 닫힌다");
    N.setMode("pan");
  } },
  { name: "고르기 모드의 안내 말풍선은 없다(고르기를 끈 뒤에도 남는 것이 없다)", async run(assert) {
    await setup();
    N.setMode("pick");
    const host = mount(html`<${NodeOverlay} />`);
    await tick();
    assert(!host.querySelector(".pickhint") && !host.textContent.includes("네모로 끌어"), host.textContent);
    N.setSelection(["n1"]);
    await tick();
    N.setSelection([]);
    N.setMode("pan");
    await tick();
    assert(!host.textContent.includes("네모로 끌어"), "끈 뒤에도 없다");
    host.remove();
  } },
  { name: "'구간 밖 n개' 칩은 구간 탭에서만: 도면 탭·패널이 닫힌 도면에는 없다", async run(assert) {
    await setup();
    const slow = () => new Promise((r) => setTimeout(r, 60));      // 갈고리의 구독은 그린 뒤에 잇는다
    for (const [panel, want] of [["drawings", false], [null, false], ["nodes", true]]) {
      store.set({ panel, sheet: "graph-A" });
      await N.loadSheet("graph-A");
      const host = mount(html`<${NodeOverlay} />`);
      await slow(); await tick();
      const bar = host.querySelector(".chipbar");
      assert(want ? !!bar && bar.textContent.includes("구간 밖") : !bar, String(panel) + " 칩: " + host.textContent);
      host.remove();
    }
    store.set({ panel: null });
  } },
  { name: "모두 확정(실제 창 3차): 구간 패널을 열지 않고 도면 위 확인 창, Enter로 확정", async run(assert) {
    await setup();
    store.set({ panel: null });
    const { ConfirmAllModal } = await import("../js/panels/nodes_confirm.js");
    const host = mount(html`<${ConfirmAllModal} />`);
    N.askConfirmAll();
    await tick();
    const m = host.querySelector(".na-modal");
    assert(m && m.textContent.includes("2개 구간을 확정할까요?"), "확인 창");
    assert.equal(store.get().panel, null, "패널은 열지 않음");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();
    assert.equal(sent.filter((x) => x.name === "nodes.confirm").map((x) => x.args.node_ids), [["S1", "S2"]]);
    assert(!host.querySelector(".na-modal"), "확정하면 닫힘");
    N.askConfirmAll();
    await tick();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await tick();
    assert.equal(N.nodes.get().confirmAsk, null, "Esc는 취소");
    host.remove();
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
    assert.equal(m.args, { project_id: "P", set_rev: 4, node_id: "S1", name: "새 이름", targets: [{ node_id: "S1", rev: 2, state: "applied" }] });
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
  { name: "구간 패널: 목록은 이 도면 구간만, 줄에는 번호·이름·도면 범위·구성요소 수만(상태 꼬리표 없음), 이름은 글로만", async run(assert) {
    await setup();
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    const rows = host.querySelectorAll(".nrow");
    assert.equal(rows.length, 2);                       // 이 도면(graph-A)의 S1·S2, S3은 graph-B
    const text = host.textContent;
    const rowText = [...rows].map((r) => r.textContent).join(" ");
    assert(!/적용됨|겹침|⇄/.test(rowText) && !host.querySelector(".nrow .chip"), rowText);
    assert(text.includes("[101 → 102]") && text.includes("구간 밖 30") && rowText.includes("구성요소"), text.slice(0, 300));
    assert(text.includes("<b>RC-L003</b>") && !host.querySelector(".nrow b b"), "이름의 태그가 HTML로 해석되지 않음");
    assert(!text.includes("아직 확인 전입니다"), "AI 구간 안내 줄은 없다(화면 단순화)");
    N.nodes.set({ scope: "all" });
    await tick();
    assert.equal(host.querySelectorAll(".nrow").length, 3);
    host.remove();
  } },
  { name: "여러 도면 구간: 목록은 '[101 → 102]', 상세는 도면별 칩·이어짐 칩, 칩을 누르면 그 도면을 연다(확대해 들어가지 않음)", async run(assert) {
    await setup();
    N.nodes.set({ scope: "all" });
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    const text = host.textContent;
    assert(text.includes("[101 → 102]") && !text.includes("SNP-M-101 외 1장"), text.slice(0, 300));
    assert.equal(host.querySelectorAll(".span-mark").length, 0, "여러 도면 기호는 없다(도면 범위 글이 말한다)");
    N.focusNode("S2");
    await tick();
    const chips = [...host.querySelectorAll('[aria-label="도면별로 보기"] button')];
    assert.equal(chips.map((c) => c.textContent.trim()), ["SNP-M-101 · 3", "SNP-M-102 · 2"]);
    assert(host.textContent.includes("S3 → SNP-M-102에서 계속"), "이어짐 칩");
    const opened = [];
    const R = await import("../js/panels/results_state.js");
    R.setOpenSheet((g) => { opened.push(g); store.set({ sheet: g }); });
    const cmds = [];
    const seq0 = store.get().command.seq;
    chips[1].click();
    await tick();
    assert.equal(opened, ["graph-B"]);
    assert(!(store.get().command.seq > seq0 && store.get().command.type === "zoomTo"), "확대해 들어가지 않는다(새 도면은 전체 맞춤으로 열린다)");
    assert.equal(N.nodes.get().focus, "S2", "넘어가도 구간 고름은 그대로");
    host.remove();
  } },
  { name: "다른 도면 연결: 이어진 연결을 따라가면 맞은편 도면을 연다(확대 명령 없음), 미이어짐은 가지 않음", async run(assert) {
    await setup();
    const opened = [];
    const R = await import("../js/panels/results_state.js");
    R.setOpenSheet((g) => { opened.push(g); store.set({ sheet: g }); });
    store.set({ sheet: "graph-A" });
    assert.equal(N.followLink({ id: "c1", status: "unlinked", reason: "짝 없음" }), false);
    assert.equal(N.followLink({ id: "c1", status: "linked", peer_graph_id: "graph-B", peer_id: "p9", label: "SNP-M-102" }), true);
    await tick();
    assert.equal(opened, ["graph-B"]);
    const c = store.get().command;
    assert(!(c.type === "zoomTo" && (c.ids || []).join() === "p9"), JSON.stringify(c));
    let props = null;
    engine.sheet = Object.assign({}, engine.sheet, { graph_id: "graph-A", links: [{ id: "c1", status: "linked", peer_graph_id: "graph-B", peer_id: "p9", label: "SNP-M-102" }] });
    store.set({ sheet: "graph-A" });
    await N.loadSheet("graph-A");
    function Probe() { props = useNodeCanvas("graph-A").props; return html`<i></i>`; }
    const host = mount(html`<${Probe} />`);
    await tick();
    assert.equal(props.links.map((l) => l.id), ["c1"]);
    props.onLinkClick(props.links[0]);
    await tick();
    assert.equal(opened.length, 2);
    host.remove();
  } },
  { name: "구간 패널: 구간을 누르면 강조·상세, 확정 구간은 고치기가 막힘, AI 초안 표시", async run(assert) {
    await setup();
    N.nodes.set({ scope: "all" });
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    host.querySelectorAll(".nrow-b")[1].click();         // S2
    await tick();
    assert.equal(N.nodes.get().focus, "S2");
    const det = host.querySelector(".ndetail");
    assert(det && det.textContent.includes("AI 초안"), "AI 초안 표시");
    assert(det.textContent.includes("RC-RV01") && det.textContent.includes("겹침"), "경계·겹침");
    host.querySelectorAll(".nrow-b")[2].click();         // S3 확정
    await tick();
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
    await tick();
    const by = (label) => [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === label);
    by("이름 고치기").click();
    await tick();
    const input = host.querySelector('input[aria-label="이름"]');
    input.value = "고친 이름";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
    by("이름 저장").click();
    await tick();
    assert.equal([lastCmd().name, lastCmd().args.name], ["nodes.rename", "고친 이름"]);
    engine.reply = () => ({ ok: true, data: { set_rev: 4, batch_id: null, node_ids: ["S1"], needs_archive: true, skipped: 0 } });   // 엔진이 코드로 알림: 아무것도 지우지 않음
    by("S1 지우기").click();
    await tick();
    assert(host.textContent.includes("분석 칸에 판정이 있습니다"), "보관 안내");
    assert(!!by("보관하고 지우기"), "보관 선택지");
    assert(host.querySelectorAll(".nrow").length === 2, "아직 지우지 않음");
    engine.reply = () => ({ ok: true, data: { set_rev: 6, batch_id: "B4", node_ids: ["S1"] } });
    by("보관하고 지우기").click();
    await tick();
    assert.equal([lastCmd().name, lastCmd().args.archive], ["nodes.remove", true]);
    host.remove();
  } },
  { name: "구간 패널: 찾지 못한 구성요소를 골라 버리고, 확정 구간이면 단추 대신 까닭을 보인다", async run(assert) {
    await setup();
    N.nodes.set({ scope: "all" });
    const plain = window.fetch;
    window.fetch = async (url) => {
      const r = await plain(url);
      if (!String(url).startsWith("/api/nodes/node/")) return r;
      const d = await r.json();
      return { ok: true, status: 200, json: async () => Object.assign(d, { lost_items: [{ key: "k1", name: "수동 밸브 RC-V001", lost_at: "2026-11-20T01:02:03Z" }, { key: "k2", name: "이름 없는 구성요소", lost_at: null }], discarded: 0 }) };
    };
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    host.querySelectorAll(".nrow-b")[0].click();         // S1 적용됨
    await tick();
    const list = host.querySelector(".lost-items");
    assert(list && list.textContent.includes("찾지 못한 구성요소 2개") && list.textContent.includes("RC-V001"), "목록");
    assert(!list.textContent.includes("k1") && !list.textContent.includes("lost:"), "key·묘비 id는 보이지 않는다");
    const by = (label) => [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === label);
    assert(by("S1 찾지 못한 구성요소 고른 것 버리기").disabled, "고르기 전에는 꺼짐");
    list.querySelector("input[type=checkbox]").click();
    await tick();
    by("S1 찾지 못한 구성요소 고른 1개 버리기").click();
    await tick();
    assert.equal([lastCmd().name, JSON.stringify(lastCmd().args.keys), lastCmd().args.node_id], ["nodes.discard_lost", '["k1"]', "S1"]);
    assert(lastCmd().args.targets && lastCmd().args.targets[0].node_id === "S1", "판 검사용 대상");
    by("S1 찾지 못한 구성요소 모두 버리기").click();
    await tick();
    assert.equal(JSON.stringify(lastCmd().args.keys), '["k1","k2"]');
    host.querySelectorAll(".nrow-b")[2].click();         // S3 확정
    await tick();
    const held = host.querySelector(".lost-items");
    assert(held.textContent.includes("확정을 해제한 뒤에 버릴 수 있습니다"), "확정 구간 까닭");
    assert(!by("S3 찾지 못한 구성요소 모두 버리기"), "확정 구간에는 버리기 단추가 없다");
    window.fetch = plain;
    host.remove();
  } },
  { name: "구간 패널: 최근 묶음 되돌리기와 나머지도 나누기(채팅)", async run(assert) {
    await setup();
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    const by = (label) => [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === label);
    by("B2 되돌리기").click();
    await tick();
    assert.equal([lastCmd().name, lastCmd().args.batch_id], ["nodes.undo", "B2"]);
    assert(!("targets" in lastCmd().args), "묶음 되돌리기는 대상 판 없이 set_rev만");
    by("나머지도 나누기").click();
    await tick();
    assert.equal(lastCmd().name, "chat.ask");
    host.remove();
  } },
  { name: "도면 고르기: 'n개 고름' 막대 → 구간 만들기(제안 이름으로 바로) → 만든 카드에서 설계 의도 저장", async run(assert) {
    await setup();
    engine.reply = (name) => (name === "nodes.suggest"
      ? { ok: true, data: { count: 3, asked: 3, name: "RC-RV01 → RC-SG01", majors: ["RC-RV01", "RC-SG01"], boundary: ["RC-RV01", "RC-SG01"], overlaps: [{ node_id: "S1", shared: 1 }], set_rev: 4 } }
      : { ok: true, data: { set_rev: 5, batch_id: "B3", node_ids: ["S4"] } });
    const host = mount(html`<${NodeOverlay} />`);
    N.setSelection(["n1", "n2", "n3"]);
    await tick();
    assert(host.textContent.includes("3개 고름"), "막대");
    [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "구간 만들기").click();
    await tick();
    const m = sent.find((x) => x.name === "nodes.create");
    assert(m, "누르면 바로 만든다");
    assert.equal(m.args, { project_id: "P", sheet: "graph-A", ids: ["n1", "n2", "n3"], name: "RC-RV01 → RC-SG01", set_rev: 4 });
    assert.equal(N.nodes.get().selection, []);
    assert.equal(N.nodes.get().focus, "S4");
    const card = host.querySelector(".newnode");
    assert(card && card.textContent.includes("구간 S4을 만들었습니다") && !card.textContent.includes("겹칩니다") && card.querySelector("#nn-name").value === "RC-RV01 → RC-SG01", "카드 " + (card && card.textContent));
    const intent = card.querySelector("#nn-intent");
    intent.value = "원자로 출구를 증기발생기로 보냄";
    intent.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
    [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "이름·설계 의도 저장").click();
    await tick();
    const si = sent.filter((x) => x.name === "nodes.set_intent");
    assert.equal(si.map((x) => [x.args.node_id, x.args.text]), [["S4", "원자로 출구를 증기발생기로 보냄"]]);
    assert(!sent.some((x) => x.name === "nodes.rename"), "이름은 안 고쳤으니 보내지 않음");
    assert(!host.querySelector(".newnode"), "카드가 닫힘");
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
    await tick();
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
    store.set({ panel: "drawings" });
    const host = mount(html`<${Probe} />`);
    await tick();
    assert.equal([props.segments, props.outside], [[], []], "도면 탭에는 구간 색 강조가 없다(화면 단순화)");
    await new Promise((r) => setTimeout(r, 300));      // 구독이 붙을 때까지
    // 구간 탭에서의 값은 그 상태로 새로 얹어 읽는다(숨은 페이지는 구독 효과가 늦게 붙는다)
    const again = async () => { render(null, host); render(html`<${Probe} />`, host); await tick(); };
    store.set({ panel: "nodes" });
    await again();
    assert.equal([props.segments, props.outside], [[], []], "구간을 고르지 않으면 구간 색도 흐림도 없다(도면 기본 모습)");
    assert.equal(props.mode, "pan");
    N.nodes.set({ focus: "S2", mode: "pick" });
    await again();
    assert.equal(props.segments.map((s) => [s.node_id, s.ids, s.active]), [["S2", ["n2", "n3"], true]], "고른 구간만 그린다");
    assert.equal(props.outside, ["n4", "n5"]);
    props.onPlainClick({ hit: true });
    assert.equal(N.nodes.get().focus, "S2", "구성요소를 누른 것은 구간 고름을 풀지 않는다");
    props.onPlainClick({ hit: false });
    assert.equal(N.nodes.get().focus, null, "빈 곳을 누르면 풀린다");
    N.nodes.set({ focus: "S2" });
    await again();
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
  { name: "구간 패널(측정 2): 등록·추출 뒤 도면 알림만 와도 '도면을 먼저 읽어야 합니다'를 거둔다", async run(assert) {
    await setup();
    engine.list = Object.assign({}, engine.list, { available: false, nodes: [], set_rev: 0 });
    await N.refresh();
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    assert(host.textContent.includes("도면을 먼저 읽어야 합니다"), "시험의 전제");
    engine.list = Object.assign({}, engine.list, { available: true, set_rev: 1 });
    deliver(JSON.stringify({ t: "changed", topic: "drawings", rev: null }));      // 등록은 drawings·sources만 알린다
    await tick();
    assert(!host.textContent.includes("도면을 먼저 읽어야 합니다"), "도면이 바뀌면 구간 목록도 다시 읽는다");
    host.remove();
  } },
  { name: "구간 패널(측정 2): 패널을 열 때마다 다시 읽는다(알림을 놓쳤어도 낡은 안내가 남지 않게)", async run(assert) {
    await setup();
    engine.list = Object.assign({}, engine.list, { available: false, nodes: [], set_rev: 0 });
    await N.refresh();
    engine.list = Object.assign({}, engine.list, { available: true, set_rev: 1 });     // 알림 없이 바뀜
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    await tick();
    assert(!host.textContent.includes("도면을 먼저 읽어야 합니다"), "열 때 읽은 목록을 보인다");
    host.remove();
  } },
  { name: "구간 패널(측정 7): 열자마자 누른 확정은 열 때 읽는 목록을 기다려 지금 판으로 보낸다", async run(assert) {
    await setup();
    N.nodes.set({ scope: "all", focus: "S1" });
    engine.list = Object.assign({}, engine.list, { set_rev: 7 });                  // 뒤에서 판 이전이 집합 판을 올렸다(알림 전)
    const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
    N.confirm(["S1"]);                                                               // 그리자마자(열 때 읽기가 끝나기 전) 누름
    await tick();
    const m = sent.filter((x) => x.name === "nodes.confirm").pop();
    assert(m, "명령을 보냄");
    assert.equal(m.args.set_rev, 7, "열 때 읽은 판으로 보낸다");
    host.remove();
  } },
  { name: "구간 패널(측정 7): 거절되면 패널 위 안내와 함께 토스트로도 알린다", async run(assert) {
    await setup();
    store.set({ toast: null });
    engine.reply = () => ({ ok: false, error: { code: "stale", message: "구간이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요." } });
    const r = await N.confirm(["S1"]);
    assert(r === null);
    const t = store.get().toast;
    assert(t && t.text.includes("바뀌어 저장하지 않았습니다") && t.kind === "err", JSON.stringify(t));
  } },
  { name: "구간 연결: 엔진의 changed(nodes) 알림을 받으면 다시 읽는다", async run(assert) {
    await setup();
    engine.list = Object.assign({}, engine.list, { set_rev: 9, nodes: engine.list.nodes.slice(0, 1) });
    deliver(JSON.stringify({ t: "changed", topic: "nodes", rev: 9 }));
    await tick();
    assert.equal([N.nodes.get().list.set_rev, N.nodes.get().list.nodes.length], [9, 1]);
  } },
];

// 525구간 목록 시간(규격 §5.4 방식: 측정값은 window.__nodesTiming에 남기고, 상한은 넉넉히 둔다)
tests.push({ get name() { return "구간 패널: 525구간 목록을 그리고 구간을 바꿔 누르는 시간" + (window.__nodesTiming ? " [525행 · 그리기 " + window.__nodesTiming.render_ms + "ms · 구간 바꿔 누르기 " + window.__nodesTiming.focus_ms.join("/") + "ms · 오프스크린 QtWebEngine, 가상 스크롤 없음]" : ""); }, async run(assert) {
  await setup();
  const many = [];
  for (let k = 0; k < 525; k++) many.push({ node_id: "S" + (k + 1), name: "구간 " + (k + 1), state: k % 7 === 0 ? "confirmed" : "applied", origin: k % 3 ? "user" : "ai", name_by: "user", rev: 1, basis: "x", batch_id: "B1",
    design_intent: null, count: 11, sheets: [{ graph_id: "graph-A", n: 11 }], overlaps: k % 5 === 0 ? [{ node_id: "S" + (k + 2), shared: 1 }] : [], confirmed: null, locked: null, screen: null });
  engine.list = Object.assign({}, engine.list, { nodes: many });
  await N.refresh();
  const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
  let t0 = performance.now();
  N.nodes.set({ scope: "all", checked: [] });
  const until = async (cond) => { for (let i = 0; i < 20000 && !cond(); i++) await Promise.resolve(); };
  await until(() => host.querySelectorAll(".nrow").length === 525);
  const render = performance.now() - t0;
  const times = [];
  for (const k of [10, 200, 400]) {
    t0 = performance.now();
    host.querySelectorAll(".nrow-b")[k].click();
    await until(() => !!host.querySelector(".ndetail") && host.querySelector(".ndetail .nd-h b").textContent === "S" + (k + 1));
    times.push(performance.now() - t0);
  }
  window.__nodesTiming = { render_ms: Math.round(render), focus_ms: times.map(Math.round) };
  assert(host.querySelectorAll(".nrow").length === 525, "525행");
  assert(render < 3000 && Math.max(...times) < 1500, JSON.stringify(window.__nodesTiming));
  host.remove();
} });


tests.push({ name: "구간 연결: 문구가 아니라 엔진 코드로 판단한다(거절 문장이 달라도 보관 선택지는 답의 needs_archive로만 뜬다)", async run(assert) {
  await setup();
  engine.reply = () => ({ ok: false, error: { code: "failed", message: "분석 칸에 판정이 있어 지울 수 없음 보관" } });
  await N.removeNode("S1", false);
  assert.equal(N.nodes.get().needArchive, null);                // 오류 문장에 '판정·보관'이 있어도 선택지를 만들지 않는다
  engine.reply = () => ({ ok: true, data: { set_rev: 4, batch_id: null, node_ids: ["S1"], needs_archive: true } });
  await N.removeNode("S1", false);
  assert.equal(N.nodes.get().needArchive, "S1");
} });

tests.push({ name: "고르기: 2,000개를 넘겨 잘렸다는 사실을 막대에 보이고, 비우면 사라짐", async run(assert) {
  await setup();
  const host = mount(html`<${NodeOverlay} />`);
  N.setSelection(["n1", "n2"], true);
  await tick();
  assert(host.textContent.includes("앞 2개만 골랐습니다"), host.textContent.slice(0, 200));
  N.setSelection(["n1"], false);
  await tick();
  assert(!host.textContent.includes("만 골랐습니다"));
  N.clearSelection();
  host.remove();
} });

tests.push({ name: "구간 연결: 뺀 선(신호선·계측선)이 있으면 답의 문장을 알림으로 보인다", async run(assert) {
  await setup();
  store.set({ toast: null });
  engine.reply = () => ({ ok: true, data: { set_rev: 5, batch_id: "B3", node_ids: ["S1"], skipped: 2, skipped_text: "고른 것 가운데 2개는 구성요소가 아닌 선(신호선·계측선)이라 뺐습니다." } });
  await N.run("add_members", { node_id: "S1", sheet: "graph-A", ids: ["n1", "n2", "s1", "s2"] }, ["S1"]);
  assert.equal(store.get().toast && store.get().toast.text, "고른 것 가운데 2개는 구성요소가 아닌 선(신호선·계측선)이라 뺐습니다.");
  store.set({ toast: null });
} });

tests.push({ name: "구간 패널: 이전 형식 파일은 안내와 '새 형식으로 바꾸기'를 보이고 누르면 nodes.migrate", async run(assert) {
  await setup();
  engine.list = Object.assign({}, engine.list, { legacy: true, nodes: [] });
  await N.refresh();
  const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
  await tick();
  assert(host.textContent.includes("이전 형식으로 저장돼"), "안내");
  engine.reply = () => ({ ok: true, data: { set_rev: 1, read_only: null } });
  [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "새 형식으로 바꾸기").click();
  await tick();
  assert.equal(lastCmd().name, "nodes.migrate");
  host.remove();
} });


tests.push({ name: "구간 연결: 프로젝트가 바뀌면 앞 프로젝트의 목록·고른 것·카드를 비우고 새로 읽으며, 쓰기에는 화면이 본 프로젝트 ID를 보낸다", async run(assert) {
  await setup();
  store.set({ drawings: Object.assign({}, store.get().drawings, { project_id: "P" }) });
  N.nodes.set({ focus: "S2", selection: ["n1"], card: { open: true, name: "x", intent: "", suggest: null, busy: false, error: null }, checked: ["S1"] });
  engine.list = Object.assign({}, engine.list, { project_id: "Q", set_rev: 9, nodes: engine.list.nodes.slice(2) });
  store.set({ drawings: Object.assign({}, store.get().drawings, { project_id: "Q" }) });      // 위 막대에서 프로젝트를 바꿈
  const old = N.nodes.get();
  assert(old.focus === null && old.selection.length === 0 && old.card === null && old.checked.length === 0, "보기 상태를 비움");
  await tick();
  const s2 = N.nodes.get();
  assert.equal([s2.list.project_id, s2.list.set_rev, s2.list.nodes.map((n) => n.node_id)], ["Q", 9, ["S3"]]);
  await N.confirm(["S3"]);
  assert.equal([lastCmd().name, lastCmd().args.project_id, lastCmd().args.set_rev], ["nodes.confirm", "Q", 9]);
  store.set({ drawings: Object.assign({}, store.get().drawings, { project_id: "P" }) });
  engine.list = Object.assign({}, engine.list, { project_id: "P" });
  await tick();
} });

tests.push({ name: "구간 상세(실제 창 3차 D): 구성요소 칩의 글·마우스 올림·접근성 이름에 종류 코드·그래프 이름이 없다", async run(assert) {
  await setup();
  const host = mount(html`<${NodesPanel} onClose=${() => {}} />`);
  N.focusNode("S1");
  await tick(); await tick();
  const chips = [...host.querySelectorAll(".memlist .chip")];
  assert(chips.length >= 2, "칩이 그려짐: " + chips.length);
  const said = chips.flatMap((c) => [c.textContent, c.getAttribute("title") || "", c.getAttribute("aria-label") || ""]);
  for (const t of said) assert(!/graph-|_[a-z]|SCN__/.test(t), "내부 말: " + t);
  assert(said.some((t) => t.includes("원자로 용기 · SNP-M-101")), JSON.stringify(said));
  host.remove();
} });
