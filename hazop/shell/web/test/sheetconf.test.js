// 쪽 확정 한 흐름(web/js/sheet_confirm.js·compare.js, HZ-DSN-06 U8) 검토 지적: 견주기 화면을 연 때의 판(ver·rev)으로 견줌·확정을 보낸다,
// 견줌은 됐는데 확정이 막히면 카드에 까닭, openNext는 견줌만 된 쪽·확정된 쪽에서 견주기 화면을 열지 않는다.
import { deliver } from "../js/bridge.js";
import { store } from "../js/store.js";
import * as C from "../js/sheet_confirm.js";
import { cmp, openCompare, closeCompare } from "../js/compare.js";

const tick = async () => { await new Promise((r) => setTimeout(r, 20)); for (let i = 0; i < 200; i++) await Promise.resolve(); };
const ST = (extra) => Object.assign({ available: true, graph_id: "G", ver: "v1", rev: 1, state: "open", unconfirmed_total: 0, unconfirmed: [], unplaced_total: 0,
  leftovers: { total: 0 }, compared: null, record_error: null, read_method: "drawio" }, extra || {});
let sent, served, reply;

function install() {
  sent = [];
  window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return; sent.push([m.name, m.args]);
    const r = reply(m.name, m.args); Promise.resolve().then(() => deliver(JSON.stringify(Object.assign({ t: "reply", id: m.id }, r)))); }, setHandler() {} };
  window.fetch = async (u) => (String(u).startsWith("/api/sheetconf/") ? { ok: true, status: 200, json: async () => served } : { ok: true, status: 200, json: async () => ({}) });
}

export const tests = [
  { name: "쪽 확정(검토 지적): 견주기 화면을 연 때의 판으로 견줌을 보낸다(그새 바뀐 판으로 넘어가지 않음)", async run(assert) {
    install();
    store.set({ sheet: "G" });
    C.conf.set({ byGraph: { G: ST() }, open: false, busy: false, error: null });
    openCompare("G", "drawio");
    assert.equal(cmp.get().pin, { ver: "v1", rev: 1 }, "열 때의 판을 붙잡음");
    C.conf.set({ byGraph: { G: ST({ ver: "v2", rev: 2 }) } });               // 그새 도면 자료가 바뀌어 다시 읽힘
    reply = (name) => ({ ok: false, error: { code: "stale", message: "도면 자료가 바뀌었습니다" } });
    const r = await C.compareAndConfirm("G", "side_by_side", cmp.get().pin);
    assert.equal(sent[0], ["sheet.compare", { graph_id: "G", ver: "v1", rev: 1, mode: "side_by_side" }]);
    assert.equal([r.ok, r.step], [false, "compare"]);
    assert.equal(sent.length, 1, "확정은 보내지 않음");
    closeCompare();
  } },
  { name: "쪽 확정: 견줌은 됐는데 확정이 막히면 카드를 다시 열고 까닭을 보인다", async run(assert) {
    install();
    store.set({ sheet: "G" });
    C.conf.set({ byGraph: { G: ST() }, open: false, busy: false, error: null });
    reply = (name) => (name === "sheet.compare" ? { ok: true, data: { status: ST({ ver: "v1", rev: 2, compared: { by: "검토자A" }, state: "ready" }) } }
      : { ok: false, error: { code: "failed", message: "미확인 1곳이 새로 생겨 확정할 수 없습니다" } });
    const r = await C.compareAndConfirm("G", "side_by_side", { ver: "v1", rev: 1 });
    assert.equal([r.ok, r.step], [false, "confirm"]);
    assert.equal(sent.map((x) => x[0]), ["sheet.compare", "sheet.confirm"]);
    assert.equal(sent[1][1].rev, 2, "확정은 견줌이 남긴 새 기록 판으로");
    assert(C.conf.get().error.includes("미확인 1곳"), C.conf.get().error);
  } },
  { name: "쪽 확정: openNext는 견줌만 된 쪽·확정된 쪽에서는 카드를 열고, 조건이 찬 쪽에서만 견주기 화면", async run(assert) {
    install();
    store.set({ sheet: "G" });
    for (const [st, want] of [[ST({ compared: { by: "검토자A" }, state: "ready" }), "card"], [ST({ state: "confirmed", confirmed: { by: "검토자A" } }), "card"],
      [ST({ unconfirmed_total: 2 }), "card"], [ST(), "compare"]]) {
      served = st;
      C.conf.set({ byGraph: {}, open: false });
      const got = await C.openNext("G");
      assert.equal(got, want, JSON.stringify(st).slice(0, 80));
      closeCompare();
    }
  } },
];
