// 같은 도면 자리의 원본 고르기 카드(web/js/panels/drawings_sources.js, 시트 정체 U4): 파일 줄은 파일로 고르고, 바꾸기 전에 다시 확인할 구간 수를 보인다.
import { html, render } from "../js/ui/html.js";
import { deliver } from "../js/bridge.js";
import { SourceConflicts, choicesOf, previewText } from "../js/panels/drawings_sources.js";

const tick = async () => { await new Promise((r) => setTimeout(r, 30)); for (let i = 0; i < 400; i++) await Promise.resolve(); };
const FILE_ROW = { kind: "file", reason: "same_number_other_file", text: "같은 번호 SNP-M-101의 다른 PDF 파일이 있습니다", display: "SNP-M-101",
  drawing_number: "SNP-M-101", graph_id: "graph-SNP-M-101", formats: ["pdf_vector"], in_use_format: "pdf_vector", in_use_material: "m-a",
  in_use_file: "a.pdf", chosen: null, chosen_material: null, nodes_on_sheet: 2,
  candidates: [{ material_id: "m-a", file: "a.pdf", format: "pdf_vector", in_use: true, modified: "2026-11-23 10:00" },
    { material_id: "m-b", file: "b.pdf", format: "pdf_vector", in_use: false, modified: "2026-11-23 11:00" }] };
let sent;

export const tests = [
  { name: "원본 고르기: 파일 줄은 파일마다, 형식 줄은 형식마다, 정착이 못 들인 줄은 고를 것 없음", async run(assert) {
    assert.equal(choicesOf(FILE_ROW).map((x) => x.args), [{ drawing_number: "graph-SNP-M-101", material_id: "m-a" }, { drawing_number: "graph-SNP-M-101", material_id: "m-b" }]);
    const fmtRow = Object.assign({}, FILE_ROW, { kind: "format", formats: ["drawio", "pdf_vector"] });
    assert.equal(choicesOf(fmtRow).map((x) => x.args.format), ["drawio", "pdf_vector"]);
    assert.equal(choicesOf(Object.assign({}, FILE_ROW, { reason: "settle_rebuild_failed" })), []);
    assert(previewText(FILE_ROW).includes("구간 2개가 다시 확인 대상"), previewText(FILE_ROW));
  } },
  { name: "원본 고르기: 쓰기 → 미리 알림 → 바꾸기에서만 sources.choose(material_id)", async run(assert) {
    sent = [];
    window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return; sent.push([m.name, m.args]);
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: { chosen: {} } }))); }, setHandler() {} };
    window.fetch = async (u) => (String(u) === "/api/sources" ? { ok: true, status: 200, json: async () => ({ conflicts: [FILE_ROW] }) } : { ok: false, status: 404, json: async () => ({}) });
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${SourceConflicts} />`, host);
    await tick(); await tick();
    const btn = [...host.querySelectorAll("button")].find((b) => b.textContent.includes("b.pdf"));
    assert(btn, host.textContent);
    btn.click(); await tick();
    assert(host.querySelector(".src-ask") && host.textContent.includes("구간 2개가 다시 확인 대상"), "바꾸기 전 미리 알림");
    assert.equal(sent.length, 0, "미리 알림만으로는 바꾸지 않음");
    [...host.querySelectorAll(".src-ask button")].find((b) => b.textContent.includes("바꾸기")).click();
    await tick();
    assert.equal(sent[0], ["sources.choose", { drawing_number: "graph-SNP-M-101", material_id: "m-b" }]);
    host.remove();
  } },
];
