// AI 검토 후보 행: match(범례 견본과 맞음)가 있는 후보에만 높음·보통 칩과 뜻 한 줄이 붙는다.
import { render } from "../vendor/preact.module.js";
import { html } from "../js/ui/html.js";
import { Row } from "../js/panels/aireview.js";

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
    const host = draw(Object.assign({}, base, { task: "recheck", cand_id: "rr-a:kind", values: ["check_valve"], script_value: "manual_valve", current: "manual_valve", bulk_block: "다시 확인에서 스크립트와 다른 값이 나와 하나씩 봄" }));
    const line = host.querySelector(".ai-main b").textContent.replace(/\s+/g, " ").trim();
    assert.equal(line, "다시 확인: 기호 종류 스크립트 manual_valve → AI check_valve");
    assert(host.textContent.includes("하나씩 볼 것"), "묶음에서 빠지는 까닭");
  } },
];
