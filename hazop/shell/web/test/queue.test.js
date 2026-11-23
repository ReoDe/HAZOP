// 검토 대기열(web/js/queue/*.js, HZ-DSN-06 §3.3 U5): 키가 지금 있는 명령을 그 차례·그 판으로 부르는지, 되돌리기·묶음 수락·끝 화면.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as Q from "../js/queue/queue.js";
import { QueueCard } from "../js/queue/card.js";
import { RevertGuard } from "../js/review/revert_guard.js";

const tick = async () => { for (let i = 0; i < 400; i++) await Promise.resolve(); };
const aiItem = (n, extra) => Object.assign({ qid: "ai|G|c" + n, kind: "ai", graph_id: "G", sheet: "SNP-M-101", ver: "v0", cand_id: "c" + n, local_id: "n" + n,
  label: "RC-V0" + n, task: "태그·속성", field: "tag", field_label: "태그", now: "(비어 있음)", proposal: "V90" + n, confidence: 0.95, why: "주변 글자",
  bulk: true, edit_op: "set_tag", state: "open" }, extra || {});
let served, sent, verN, holds = [];

function install() {
  sent = [];
  holds = [];
  verN = 0;
  window.hazopBridge = {
    send(text) {
      const m = JSON.parse(text);
      if (m.t !== "cmd") return;
      if (m.name === "inputs.hold") { holds.push(m.args.on); Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: {} }))); return; }
      sent.push([m.name, m.args]);
      verN++;
      const data = { ver: "v" + verN, changed: m.args.cand_ids || (m.name === "aireview.accept_bulk" ? ["c1", "c2"] : []), failed: [], op_id: "op1", batch_id: "B9", set_rev: 8 };
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data })));
    },
    setHandler() {},
  };
  window.fetch = async (url) => {
    const u = String(url);
    const body = (d) => ({ ok: true, status: 200, json: async () => d });
    if (u === "/api/queue/ai" || u === "/api/queue/lost") {
      const open = served.items.filter((x) => !sent.some(([n, a]) => (a.cand_ids || []).includes(x.cand_id) && n !== "aireview.revert"));
      return body(Object.assign({}, served, { items: open.map((x) => Object.assign({}, x, { ver: "v" + verN })) }));
    }
    if (u.startsWith("/api/aireview/")) return body({ ver: "v" + verN });
    return { ok: false, status: 404, json: async () => ({}) };
  };
}

async function start(items, extra) {
  install();
  Q.wire();
  Q.closeQueue();
  served = Object.assign({ kind: "ai", items, bulk: [{ graph_id: "G", task: "tag", ver: "v0", count: 2 }] }, extra || {});
  store.set({ sheet: "G" });
  await Q.openQueue(served.kind);
  await tick();
}
const key = async (k, mods) => { window.dispatchEvent(new KeyboardEvent("keydown", Object.assign({ key: k, bubbles: true }, mods || {}))); await tick(); };

export const tests = [
  { name: "대기열: A는 aireview.accept를 그 항목 판으로, 다음 건은 다시 읽은 판으로", async run(assert) {
    await start([aiItem(1), aiItem(2)]);
    await key("a");
    assert.equal(sent[0], ["aireview.accept", { graph_id: "G", cand_ids: ["c1"], ver: "v0" }]);
    assert.equal(Q.q.get().i, 1, "다음 건");
    await key("r");
    assert.equal(sent[1][0], "aireview.reject");
    assert.equal(sent[1][1].ver, "v1", "앞 판정 뒤 다시 읽은 판");
    assert(Q.q.get().done, "끝 화면");
    assert.equal(Q.counts(), { accepted: 1, rejected: 1, skipped: 0, open: 0 });
  } },
  { name: "대기열(입력 연산 U2 §11.3): AI 대기열이 열려 있는 동안 도면 다시 읽기를 미루고, 닫으면 엔진이 바로 읽게 알린다", async run(assert) {
    await start([aiItem(1)]);
    await tick();
    assert.equal(holds.slice(-1), [true], "열면 미룸");
    Q.closeQueue();
    await tick();
    assert.equal(holds.slice(-2), [true, false], "닫으면 읽기");
  } },
  { name: "대기열: Space는 저장하지 않고, 끝에서 건너뛴 것 다시 보기", async run(assert) {
    await start([aiItem(1), aiItem(2)]);
    await key(" "); await key(" ");
    assert.equal(sent.length, 0, "건너뛰기는 저장하지 않음");
    assert(Q.q.get().done);
    Q.reviewSkipped();
    assert.equal([Q.q.get().i, Q.q.get().done, Q.counts().open], [0, false, 2]);
  } },
  { name: "대기열: Z는 바로 앞 판정을 aireview.revert로 되돌리고 그 건으로 돌아간다", async run(assert) {
    await start([aiItem(1), aiItem(2)]);
    await key("a");
    await key("z");
    const last = sent[sent.length - 1];
    assert.equal([last[0], last[1].cand_ids], ["aireview.revert", ["c1"]]);
    assert.equal([Q.q.get().i, Q.current().state, Q.q.get().undo.length], [0, "open", 0]);
  } },
  { name: "대기열(입력 연산 U2 §11.6): Z는 기댄 사람 고침이 있으면 먼저 알리고, Esc면 보내지 않고 Enter면 확인한 목록을 실어 되돌린다", async run(assert) {
    await start([aiItem(1), aiItem(2)]);
    const base = window.fetch;
    window.fetch = async (u) => (String(u).startsWith("/api/aireview/G/revert?ids=c1")
      ? { ok: true, status: 200, json: async () => ({ confirm: ["h-1"], human: 1, ai: 0, text: "이 수락에 기대 사람이 한 고침 1건(태그 고침 1건)이 함께 빠집니다." }) } : base(u));
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${RevertGuard} />`, host);
    await key("a");
    await key("z");
    assert(host.querySelector(".rg-modal") && host.textContent.includes("태그 고침 1건"), "확인 창: " + host.textContent);
    await key("Escape");
    assert(!sent.some(([n]) => n === "aireview.revert"), "그만두면 보내지 않음");
    assert.equal(Q.q.get().undo.length, 1, "되돌리기 쌓임은 그대로");
    assert(Q.q.get().open, "Esc가 대기열을 닫지 않음");
    await key("z");
    await key("Enter");
    const last = sent[sent.length - 1];
    assert.equal([last[0], last[1].cand_ids, last[1].confirm], ["aireview.revert", ["c1"], ["h-1"]]);
    window.fetch = base;
    host.remove();
  } },
  { name: "대기열: E는 edit.apply 뒤 같은 판 사슬로 aireview.reject, Z는 되돌리기 뒤 edit.undo", async run(assert) {
    await start([aiItem(1)]);
    await key("e");
    assert.equal(Q.q.get().editing, "V901");
    Q.setEditing("V955");
    await Q.saveEdit(); await tick();
    assert.equal(sent.map((x) => x[0]), ["edit.apply", "aireview.reject"]);
    assert.equal(sent[0][1].value, { tag: "V955" });
    assert.equal(sent[1][1].ver, "v1", "고친 뒤 판으로 거절");
    await key("z");
    assert.equal(sent.slice(2).map((x) => x[0]), ["aireview.revert", "edit.undo"]);
    assert.equal(sent[3][1].op_id, "op1");
  } },
  { name: "대기열: Shift+A는 목록을 먼저 보이고 Enter로 도면·할 일마다 accept_bulk, Z는 한꺼번에", async run(assert) {
    await start([aiItem(1), aiItem(2), aiItem(3, { bulk: false, field: "kind", edit_op: null })]);
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${QueueCard} onChat=${() => {}} />`, host);
    await key("A", { shiftKey: true });
    assert(Q.q.get().bulkAsk && host.querySelector(".qbulk.open"), "목록 먼저");
    assert.equal(host.querySelectorAll(".qbulk.open li").length, 2, "묶을 수 있는 것만");
    assert.equal(sent.length, 0, "목록만 보일 때는 저장 안 함");
    await key("Enter");
    assert.equal(sent[0], ["aireview.accept_bulk", { graph_id: "G", task: "tag", ver: "v0" }]);
    assert.equal(Q.counts().accepted, 2);
    await key("z");
    assert.equal([sent[1][0], sent[1][1].cand_ids], ["aireview.revert", ["c1", "c2"]]);
    assert.equal(Q.counts().open, 3);
    host.remove();
  } },
  { name: "대기열: 찾지 못한 구성요소는 R이 nodes.discard_lost(판·대상), A는 저장하지 않고 안내", async run(assert) {
    const it = { qid: "lost|S1|L-1", kind: "lost", node_id: "S1", node_name: "저온관", key: "L-1", label: "밸브 V1", graph_id: "G", sheet: "SNP-M-101",
      target: { node_id: "S1", rev: 2, state: "applied" }, held: false, cands: [], state: "open" };
    await start([it], { kind: "lost", set_rev: 7, project_id: "P", bulk: [] });
    await key("a");
    assert.equal(sent.length, 0);
    assert(Q.q.get().note === Q.LINK_LATER);
    await key("r");
    assert.equal(sent[0], ["nodes.discard_lost", { project_id: "P", set_rev: 7, targets: [it.target], node_id: "S1", keys: ["L-1"] }]);
    await key("z");
    assert.equal(sent[1][0], "nodes.undo");
    assert.equal(sent[1][1].batch_id, "B9");
  } },
  { name: "대기열: 도면 키와 Esc는 대기열이 먹고, 입력칸에서는 먹지 않는다", async run(assert) {
    await start([aiItem(1)]);
    let leaked = 0;
    const spy = () => { leaked++; };
    window.addEventListener("keydown", spy);
    await key("s");
    assert.equal(leaked, 0, "도면의 S는 대기열 동안 막힘");
    const inp = document.createElement("input"); document.body.appendChild(inp);
    inp.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true })); await tick();
    assert.equal(sent.length, 0, "입력칸의 a는 수락이 아님");
    inp.remove();
    await key("Escape");
    assert.equal(Q.q.get().open, false, "Esc로 끝");
    window.removeEventListener("keydown", spy);
  } },
];
