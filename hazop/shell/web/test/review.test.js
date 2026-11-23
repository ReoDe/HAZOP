// 도면별 AI 검토(web/js/review/review.js, HZ-DSN-06 §3.7 U10): 상태 여덟 가지의 글자·단추, 칩 → 확인 창 → aireview.run, 끝난 뒤 알림 → 대기열.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as R from "../js/review/review.js";

const tick = async () => { for (let i = 0; i < 400; i++) await Promise.resolve(); };
let sent, est;
const ROW = (review, extra) => Object.assign({ graph_id: "G1", drawing_number: "SNP-M-101", proposed: 0, review, ahead: null, progress: null, left: null }, extra || {});

function install(rows) {
  sent = [];
  est = { cap: 20, run_cap: 300, calls: 4, seconds: 120, pages: [{ graph_id: "G1", items: 37, calls: 4, needed: 4, image: true }],
    conn: { can_start: true, method_name: "구독", model_name: "Opus", cost_text: "구독 한도 안", conn_ver: "cv1" }, images: { on: true } };
  window.hazopBridge = {
    send(text) {
      const m = JSON.parse(text);
      if (m.t !== "cmd") return;
      sent.push([m.name, m.args]);
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: { job: "j1" } })));
    },
    setHandler() {},
  };
  window.fetch = async (url) => {
    const u = String(url);
    const body = (d) => ({ ok: true, status: 200, json: async () => d });
    if (u === "/api/aireview") return body({ drawings: rows });
    if (u.startsWith("/api/aireview/estimate")) return body(est);
    return { ok: false, status: 404, json: async () => ({}) };
  };
}

export const tests = [
  { name: "AI 검토 칩: 상태 여덟 가지의 글자와 단추(세 자리가 같은 함수를 쓴다)", async run(assert) {
    const cases = [
      [ROW("not_run"), "AI 검토 전", "AI 검토 시작"], [ROW("nothing"), "AI에 물을 곳 없음", null],
      [ROW("waiting", { ahead: 1 }), "AI 검토 기다리는 중 · 앞에 1장", null], [ROW("running", { progress: { done: 5, total: 12 } }), "AI 검토 중 · 호출 5/12회", null],
      [ROW("candidates", { proposed: 9 }), "AI 후보 9건 남음", "검토하기"], [ROW("partial", { left: 3 }), "AI 검토 일부만 함 · 남은 곳 3", "이어서 검토"],
      [ROW("failed"), "AI 검토를 마치지 못했습니다", "다시 시도"], [ROW("done"), "AI 검토 끝", null]];
    for (const [row, text, label] of cases) {
      const v = R.reviewView(row);
      assert.equal([v.text, v.label], [text, label], row.review);
    }
    assert.equal(R.summaryText([ROW("not_run"), ROW("failed"), ROW("running"), ROW("candidates", { proposed: 2 }), ROW("done")]),
      "AI 검토 전 2장 · 검토 중 1장 · 후보 남음 1장");
  } },
  { name: "AI 검토 칩: 시작 → 확인 창(그 도면 예상·연결) → Enter로 aireview.run", async run(assert) {
    install([ROW("not_run")]);
    R.wire();
    await R.load(); await tick();
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<div><${R.ReviewChip} gid="G1" /><${R.ReviewConfirm} /></div>`, host);
    await tick();
    host.querySelector(".chip.review.act").click();
    await tick(); await tick();
    const modal = host.querySelector(".rv-modal");
    assert(modal && modal.textContent.includes("SNP-M-101 AI 검토"), "확인 창 제목");
    assert(modal.textContent.includes("37곳") && modal.textContent.includes("약 4회") && modal.textContent.includes("구독"), modal.textContent);
    assert(modal.textContent.includes("도면 조각 그림과 범례판"), "보내는 것 안내");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await tick();
    assert.equal(sent[0], ["aireview.run", { graph_ids: ["G1"], cap: 20, conn_ver: "cv1" }]);
    assert.equal(R.rv.get().confirm, null, "시작하면 창이 닫힌다");
    host.remove();
  } },
  { name: "AI 검토 칩: 연결이 준비되지 않으면 검토 시작을 끄고 안내, Esc로 닫는다", async run(assert) {
    install([ROW("not_run")]);
    est.conn = { can_start: false, guide: "설정에서 구독 연결을 확인하세요.", conn_ver: "x" };
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${R.ReviewConfirm} />`, host);
    await R.startReview("G1"); await tick();
    assert(host.querySelector(".rv-modal .btn.primary").disabled, "시작 꺼짐");
    assert(host.textContent.includes("설정에서 구독 연결을 확인하세요."));
    await R.confirmStart();
    assert.equal(sent.length, 0);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await tick();
    assert.equal(R.rv.get().confirm, null);
    host.remove();
  } },
  { name: "AI 검토 칩: 후보가 남은 도면은 그 도면 대기열을 연다, 끝 알림의 검토하기도", async run(assert) {
    install([ROW("candidates", { proposed: 9 })]);
    await R.load(); await tick();
    const opened = [];
    R.setOpeners((kind, gid) => opened.push([kind, gid]), () => {});
    R.press("G1");
    assert.equal(opened, [["ai", "G1"]]);
    store.set({ notices: [] });
    deliver(JSON.stringify({ t: "event", name: "job.done", data: { id: "j1", label: "AI 검토", result: { drawings: [{ graph_id: "G1", candidates: 9 }], estimate: 4 } } }));
    await tick();
    const n = store.get().notices.find((x) => x.id === "review:G1");
    assert(n && n.text === "SNP-M-101 AI 검토가 끝났습니다 · 후보 9건" && n.action.label === "검토하기", JSON.stringify(store.get().notices));
    n.action.run();
    assert.equal(opened[1], ["ai", "G1"]);
    deliver(JSON.stringify({ t: "event", name: "job.done", data: { id: "j2", label: "AI 검토", result: { drawings: [{ graph_id: "G1", candidates: 0 }], estimate: 2 } } }));
    await tick();
    assert(store.get().toast && store.get().toast.text === "SNP-M-101 AI 검토가 끝났습니다. 새 후보는 없습니다.");
  } },
];
