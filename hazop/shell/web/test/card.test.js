import { render } from "../vendor/preact.module.js";
import { html } from "../js/ui/html.js";
import { AnswerCard } from "../js/chat/card.js";

const base = { text: "", general: "", no_evidence: false, badges: [], refs: [], paths: [], path_notes: [], warnings: [], model_warnings: [], notes: [],
  dropped: 0, ungrounded: 0 };
const footer = { tools: 1, model: "빠름", seconds: 1.2, calls: [] };

function draw(card) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  render(html`<${AnswerCard} card=${card} footer=${footer} onChip=${() => {}} onSheet=${() => {}} />`, host);
  return host;
}

export const tests = [
  { name: "card: 모델이 낸 글은 HTML로 해석되지 않는다", run(assert) {
    const host = draw(Object.assign({}, base, { text: "<img src=x onerror=window.__pwned=1><b>굵게</b>", general: "<script>window.__pwned=2</script>" }));
    assert.equal(host.querySelectorAll("img, b, script").length, 0, "태그가 요소가 되면 안 됨");
    assert(host.textContent.includes("<img src=x"), "글자 그대로 보여야 함");
    assert.equal(window.__pwned, undefined);
  } },
  { name: "card: 도면 태그와 경고 글도 일반 글로 들어간다", run(assert) {
    const chip = { id: "a", tag: "<i>RC</i>", via: "<u>L1</u>", sheet: "g", warn: true, local_id: "L1" };
    const host = draw(Object.assign({}, base, { text: "t", paths: [{ label: "<b>경로</b>", chips: [chip], sheets: [["g", 1]], sheet_labels: { g: "<s>도면</s>" }, marks: {} }],
      warnings: [{ reason: "unknown_symbol", text: "<em>못 읽은 기호 1개</em>", scope: "highlight", labels: ["<x>"] }] }));
    assert.equal(host.querySelectorAll("i, u, b, s, em, x").length, 0);
    assert(host.textContent.includes("<i>RC</i>"));
  } },
  { name: "card: 근거 없는 답은 '확인한 내용 없음'이고 일반 지식은 따로 보인다", run(assert) {
    const host = draw(Object.assign({}, base, { no_evidence: true, text: "그냥 글", general: "일반 지식" }));
    assert(host.textContent.includes("도면·문서에서 확인한 내용 없음"));
    assert(host.textContent.includes("AI의 일반 지식"));
  } },
  { name: "card: 경로 칩이 12개를 넘으면 앞 5 · 접힘 · 뒤 5로 줄인다", run(assert) {
    const chips = Array.from({ length: 20 }, (_, i) => ({ id: "i" + i, tag: "T" + i, sheet: "g", local_id: "L" + i }));
    const host = draw(Object.assign({}, base, { text: "t", paths: [{ label: "x", chips, sheets: [["g", 20]], sheet_labels: {}, marks: {} }] }));
    assert.equal(host.querySelectorAll(".steps li .chip").length, 10);
    assert(host.textContent.includes("10개 더 보기"));
  } },
  { name: "card: 경고가 경로에서 왔을 때만 '경로에'를 붙인다", run(assert) {
    const mk = (scope) => draw(Object.assign({}, base, { text: "t", warnings: [{ reason: "direction_unknown", text: "흐름 방향 미확인 배관 1개", scope, labels: [] }] })).textContent;
    assert(mk("path").includes("경로에 흐름 방향 미확인 배관 1개"));
    assert(!mk("highlight").includes("경로에 흐름"));
  } },
];
