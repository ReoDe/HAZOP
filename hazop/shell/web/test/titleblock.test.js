// 표제란 확정(web/js/panels/titleblock.js) 시트 정체 U5c: 확정 전에 dry로 옮겨 갈 기록을 보이고 승인받아 보내며,
// 결과의 이름 바뀜으로 열린 도면을 새 이름으로 바꾼다. 구간이 가리키는 도면도 번호 칸을 잠그지 않는다(여러 쪽 자료만 잠금).
import { deliver } from "../js/bridge.js";
import { store } from "../js/store.js";
import * as T from "../js/panels/titleblock.js";

const tick = async () => { for (let i = 0; i < 400; i++) await Promise.resolve(); };
const ROW = { material_id: "m1", ver: "v1", name: "two.pdf", multi_page: false, review_data: ["구간 2곳"], sheets: [{ graph_id: "graph-material-m1-p0", page: 0 }],
  fields: [{ field: "drawing_number", value: null, candidate: "SNP-M-101" }, { field: "design_revision", value: null, candidate: null }, { field: "title", value: null, candidate: null }] };
let sent, reply;

function install() {
  sent = [];
  window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return; sent.push([m.name, m.args]);
    const r = reply(m.name, m.args); Promise.resolve().then(() => deliver(JSON.stringify(Object.assign({ t: "reply", id: m.id }, r)))); }, setHandler() {} };
  window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ rows: [], totals: { confirmed: 0, materials: 0 }, reviewer: "검토자A", fields: [] }) });
}

export const tests = [
  { name: "표제란(시트 정체 U5c): 구간이 가리켜도 번호 칸을 잠그지 않고, 확정 전에 옮겨 갈 기록을 보이고 승인하면 보낸다", async run(assert) {
    install();
    assert.equal(T.numberLocked(ROW), false, "구간이 가리켜도 잠그지 않음");
    assert.equal(T.numberLocked(Object.assign({}, ROW, { multi_page: true })), true, "여러 쪽 자료만 잠금");
    assert.equal(T.fieldsToSend(ROW, {}, true), { drawing_number: "SNP-M-101" }, "후보 그대로 확정에 번호가 실림");
    reply = (name, args) => (args.dry ? { ok: true, data: { dry: true, changed: true, text: "이 도면의 기록(구간 2건)이 바뀐 도면 이름을 따라 옮겨 갑니다: two.pdf · 1쪽 → SNP-M-101.",
      carries: [{ place: "구간", count: 2 }], renames: [{ from: "graph-material-m1-p0", to: "graph-SNP-M-101" }] } }
      : { ok: true, data: { changed: true, renames: [{ from: "graph-material-m1-p0", to: "graph-SNP-M-101" }], row: ROW } });
    T.tb.set({ drafts: {}, reasons: {}, ask: null });
    T.confirmRow(ROW, true);
    await tick();
    assert.equal(sent.map((x) => [x[0], !!x[1].dry]), [["titleblock.confirm", true]], "먼저 검사만");
    assert(T.tb.get().ask && T.tb.get().ask.text.includes("구간 2건"), "승인 전에 보임");
    store.set({ sheet: "graph-material-m1-p0" });
    T.answerAsk(true);
    await tick();
    assert.equal(sent.map((x) => [x[0], !!x[1].dry]), [["titleblock.confirm", true], ["titleblock.confirm", false]]);
    assert.equal(store.get().sheet, "graph-SNP-M-101", "열린 도면을 새 이름으로");
  } },
  { name: "표제란: 옮길 것이 없으면 묻지 않고 바로 보내고, 취소하면 보내지 않는다", async run(assert) {
    install();
    reply = (name, args) => (args.dry ? { ok: true, data: { dry: true, changed: true, text: "" } } : { ok: true, data: { changed: true, row: ROW } });
    T.tb.set({ drafts: { m1: { title: "주 배관" } }, reasons: {}, ask: null });
    T.confirmRow(ROW, false);
    await tick();
    assert.equal(sent.map((x) => !!x[1].dry), [true, false], "바로 보냄");
    install();
    reply = (name, args) => ({ ok: true, data: { dry: true, changed: true, text: "옮겨 갑니다" } });
    T.tb.set({ drafts: { m1: { title: "주 배관" } }, ask: null });
    T.confirmRow(ROW, false);
    await tick();
    T.answerAsk(false);
    await tick();
    assert.equal(sent.length, 1, "취소하면 검사만 하고 끝");
  } },
];
