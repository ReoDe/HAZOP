// 분석 결과 '수정' 칸(panels/results_detail.js) 웹 시험: 바꾸지 않은 보호수단 줄·구현 대상이 원래 값 그대로 돌아가는지(B3 반려 재현),
// 공백만 다른 AI 문장을 사람 작성으로 바꾸지 않는지, 목록에 없는 지금 값을 숨기거나 바꾸지 않는지.
import { html, render } from "../js/ui/html.js";
import { editState, changedFields, TargetSelect, BasisBlock } from "../js/panels/results_detail.js";

const tick = async () => { for (let i = 0; i < 200; i++) await Promise.resolve(); };
function mount(v) { const d = document.createElement("div"); document.body.appendChild(d); render(v, d); return d; }

const RAW = () => ({ text: "PSV-101·PSV-102 과압 방출", role: "mitigative", actuation: "passive", ipl: null, origin: "ai_draft",
  refs: [{ ref: "G1#psv101", origin: "ai_draft" }, { ref: "G1#psv102", origin: "ai_draft" }] });
const ENTRY = () => {
  const raw = RAW();
  return { entry_id: "e1", safeguards: [raw], cause_refs: [], consequence_refs: [],
    detail: { cause_kind: null, consequence_basis: null, cause_refs: [], consequence_refs: [],
      safeguards: [{ text: raw.text, role: "mitigative", actuation: "passive", draft: true,
        refs: [{ ref: "G1#psv101", label: "PSV-101", missing: false }, { ref: "G1#psv102", label: "PSV-102", missing: true }] }] } };
};
const C = { targets: [{ ref: "G1#psv101", label: "PSV-101", in_node: true }, { ref: "G1#v7", label: "V-7", in_node: false }] };

export const tests = [
  { name: "B3: 보호수단 줄의 구현 대상을 모두 들고, 역할만 바꿔도 둘째 대상이 남는다", run(assert) {
    const e = ENTRY();
    const st = editState(e);
    assert.equal(st.sg[0].refs, ["G1#psv101", "G1#psv102"]);
    st.sg[0] = Object.assign({}, st.sg[0], { role: "preventive" });
    const out = changedFields(e, st);
    assert.equal(out.safeguards[0].refs, [{ ref: "G1#psv101", origin: "ai_draft" }, { ref: "G1#psv102", origin: "ai_draft" }], "건드리지 않은 대상은 원래 값(작성 표시 포함)");
    assert.equal([out.safeguards[0].role, out.safeguards[0].origin, out.safeguards[0].text], ["preventive", "human", RAW().text]);
  } },
  { name: "B3: 원인 유형만 바꾸면 보호수단은 보내지 않는다", run(assert) {
    const e = ENTRY();
    const st = editState(e);
    st.cause_kind = "equipment";
    const out = changedFields(e, st);
    assert(!("safeguards" in out), "보호수단을 보냄");
    assert.equal(out.cause_kind, "equipment");
  } },
  { name: "B3: 대상 하나를 빼거나 더하면 그것만 바뀌고 나머지는 원래 값", run(assert) {
    const e = ENTRY();
    let st = editState(e);
    st.sg[0] = Object.assign({}, st.sg[0], { refs: ["G1#psv102"] });
    assert.equal(changedFields(e, st).safeguards[0].refs, [{ ref: "G1#psv102", origin: "ai_draft" }]);
    st = editState(e);
    st.sg[0] = Object.assign({}, st.sg[0], { refs: ["G1#psv101", "G1#psv102", "G1#v7", ""] });
    assert.equal(changedFields(e, st).safeguards[0].refs,
      [{ ref: "G1#psv101", origin: "ai_draft" }, { ref: "G1#psv102", origin: "ai_draft" }, { ref: "G1#v7", origin: "human" }]);
  } },
  { name: "B3: 공백만 다른 AI 문장은 손대지 않으면 보내지 않고, 역할만 바꾸면 원래 글을 둔다", run(assert) {
    const raw = { text: "PSV  방출 ", role: "mitigative", actuation: "passive", ipl: null, origin: "ai_draft", refs: [{ ref: "G1#psv101", origin: "ai_draft" }] };
    const e = { entry_id: "e2", safeguards: [raw], cause_refs: [], consequence_refs: [],
      detail: { safeguards: [{ text: raw.text, role: "mitigative", actuation: "passive", refs: [{ ref: "G1#psv101", label: "PSV-101" }], draft: true }], cause_refs: [], consequence_refs: [] } };
    const st = editState(e);
    assert(!("safeguards" in changedFields(e, st)), "손대지 않았는데 보냄");
    st.sg[0] = Object.assign({}, st.sg[0], { text: "PSV 방출" });
    assert(!("safeguards" in changedFields(e, st)), "공백만 고쳤는데 보냄");
    st.sg[0] = Object.assign({}, st.sg[0], { role: "preventive" });
    assert.equal(changedFields(e, st).safeguards[0].text, "PSV  방출 ");
  } },
  { name: "B3: 지금 값이 대상 목록에 없으면 맨 위에 보이고, 그래프에서 사라졌으면 그렇게 적는다", async run(assert) {
    const st = editState(ENTRY());
    const d = mount(html`<${TargetSelect} value="G1#psv102" c=${C} known=${st.known} label="t" onChange=${() => {}} />`);
    await tick();
    const opts = [...d.querySelectorAll("option")];
    assert.equal(opts[0].value, "G1#psv102");
    assert(opts[0].textContent.includes("도면에서 사라짐"), opts[0].textContent);
    assert.equal(d.querySelector("select").value, "G1#psv102", "값을 몰래 바꾸지 않음");
    const d2 = mount(html`<${TargetSelect} value="G1#psv101" c=${C} known=${st.known} label="t" onChange=${() => {}} />`);
    await tick();
    assert.equal(d2.querySelectorAll("option").length, 3, "목록에 있으면 따로 더하지 않음");
    d.remove(); d2.remove();
  } },
  { name: "B3: AI 근거 칸에 '확인할 단서(근거 아님)'을 근거와 따로 보인다", async run(assert) {
    const e = { entry_id: "e3", detail: { basis: { paths: [], sources: [], warnings: [], clues: ["잠재 후보 X-1: 펌프 정지"] } } };
    const d = mount(html`<${BasisBlock} e=${e} />`);
    await tick();
    d.querySelector("button").click();
    await tick();
    assert(d.textContent.includes("확인할 단서(근거 아님)") && d.textContent.includes("X-1"), d.textContent);
    d.remove();
  } },
];
