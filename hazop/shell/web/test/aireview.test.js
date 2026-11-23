// AI 검토 후보 행: match(범례 견본과 맞음)가 있는 후보에만 높음·보통 칩과 뜻 한 줄이 붙는다.
import { render } from "../vendor/preact.module.js";
import { html } from "../js/ui/html.js";
import { Row } from "../js/panels/aireview.js";
import * as A from "../js/panels/aireview_state.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";

const base = { cand_id: "c1:kind", task: "kind", field: "kind", field_label: "기호 종류", current: "", values: ["manual_valve"], confidence: 0.9, reason: "모양",
  status: "proposed", status_label: "남음", local_id: "L1", bulk_ok: false, bulk_block: null, decided_by: null, match: null, match_label: null, match_hint: null };

function draw(r) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  render(html`<${Row} r=${r} />`, host);
  return host;
}

export const tests = [
  { name: "AI 검토: match가 있는 후보 행에 높음·보통 칩과 뜻 한 줄(title)이 붙는다", run(assert) {
    const hi = draw(Object.assign({}, base, { match: "legend", match_label: "높음", match_hint: "범례 견본과 맞는 후보" }));
    const lo = draw(Object.assign({}, base, { match: "other", match_label: "보통", match_hint: "범례에 없는 꼴이라 확인이 필요한 후보" }));
    const chip = (h, t) => [...h.querySelectorAll(".chip")].find((c) => c.textContent.trim() === t);
    assert(chip(hi, "높음"), "높음 칩");
    assert.equal(chip(hi, "높음").getAttribute("title"), "범례 견본과 맞는 후보");
    assert(chip(lo, "보통"), "보통 칩");
    assert.equal(chip(lo, "보통").getAttribute("title"), "범례에 없는 꼴이라 확인이 필요한 후보");
  } },
  { name: "AI 검토: match가 없는 후보(스크립트·글 입력·옛 저장본)는 칩 없이 그대로다", run(assert) {
    const host = draw(base);
    assert.equal([...host.querySelectorAll(".chip")].map((c) => c.textContent.trim()), ["0.90", "남음"]);
    const old = draw(Object.assign({}, base, { match: undefined, match_label: undefined, match_hint: undefined }));       // match 필드가 아예 없는 응답
    assert.equal([...old.querySelectorAll(".chip")].length, 2);
  } },
  { name: "AI 검토: 다시 확인 후보는 '다시 확인: 스크립트 X → AI Y' 꼴로 보인다", run(assert) {
    const host = draw(Object.assign({}, base, { task: "recheck", cand_id: "rr-a:kind", values: ["check_valve"], script_value: "manual_valve", current: "manual_valve",
      values_text: ["체크 밸브"], script_text: "수동 밸브", current_text: "수동 밸브", bulk_block: "다시 확인에서 스크립트와 다른 값이 나와 하나씩 봄" }));
    const line = host.querySelector(".ai-main b").textContent.replace(/\s+/g, " ").trim();
    assert.equal(line, "다시 확인: 기호 종류 스크립트 수동 밸브 → AI 체크 밸브", "영문 내부 종류 이름 대신 엔진이 준 한글");
    assert(host.textContent.includes("하나씩 볼 것"), "묶음에서 빠지는 까닭");
  } },
  { name: "AI 검토(실제 창 4차): 결정 알림·거절은 패널 맨 위만이 아니라 화면 아래 알림으로도 뜬다(목록 아래에서 누른 사람에게 보이게)", async run(assert) {
    window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return;
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: false, error: { code: "failed", message: "이 수락에 기대 사람이 한 고침 1건이 함께 빠집니다." } }))); }, setHandler() {} };
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
    A.ai.set({ graphId: "G", view: { ver: "v1" } });
    store.set({ toast: null });
    await A.accept("c1:kind");
    for (let i = 0; i < 200; i++) await Promise.resolve();
    const t = store.get().toast;
    assert(t && t.kind === "err" && t.text.includes("함께 빠집니다"), JSON.stringify(t));
  } },
];
