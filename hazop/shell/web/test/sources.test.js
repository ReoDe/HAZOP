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

const MIXED = Object.assign({}, FILE_ROW, { kind: "format", reason: "same_number_other_format", formats: ["drawio", "pdf_vector"], in_use_format: "pdf_vector",
  in_use_material: "m-c", in_use_file: "c.pdf",
  candidates: [{ material_id: "m-a", file: "a.pdf", format: "pdf_vector", in_use: false, recheck: 2, modified: "2026-11-23 10:00" },
    { material_id: "m-b", file: "b.drawio", format: "drawio", in_use: false, recheck: 2, modified: "2026-11-23 10:30" },
    { material_id: "m-c", file: "c.pdf", format: "pdf_vector", in_use: true, recheck: 0, modified: "2026-11-23 11:00" }] });

export const tests = [
  { name: "원본 고르기: 형식 줄에 같은 형식 파일이 둘이면 파일 단추만(형식 단추와 겹치지 않게, 실제 창 5차), 미리 알림은 후보마다", async run(assert) {
    const ch = choicesOf(MIXED);
    const files = ch.filter((x) => x.kind === "file").map((x) => x.args.material_id);
    assert.equal(files, ["m-a", "m-b", "m-c"], "pdf a로 돌아갈 길(검토 지적 1)");
    assert.equal(ch.filter((x) => x.kind === "format").length, 0, "형식 단추는 두지 않는다");
    assert(ch.every((x) => /\((drawio|PDF)/.test(x.label) || x.label.includes("(")), "파일 단추에 형식을 적는다: " + ch.map((x) => x.label).join(" | "));
    const using = ch.find((x) => x.kind === "file" && x.args.material_id === "m-c");
    assert(previewText(MIXED, using).includes("지금 쓰는 원본"), "지금 쓰는 파일은 다시 확인할 것이 없다(검토 지적 3)");
    assert(previewText(MIXED, ch.find((x) => x.args.material_id === "m-a")).includes("구간 2개"));
  } },
  { name: "원본 고르기: 고른 뒤 반영이 실패하면 '도면 변경 반영하기'를 보이고 누르면 nodes.catch_up", async run(assert) {
    sent = [];
    window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return; sent.push([m.name, m.args]);
      const data = m.name === "sources.choose" ? { chosen: {}, applied: false, apply_text: "쓸 파일은 바꿨지만 검토구간에 도면 변경을 반영하지 못했습니다." } : { changed: true };
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data }))); }, setHandler() {} };
    window.fetch = async (u) => (String(u) === "/api/sources" ? { ok: true, status: 200, json: async () => ({ conflicts: [FILE_ROW] }) } : { ok: false, status: 404, json: async () => ({}) });
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${SourceConflicts} />`, host);
    await tick(); await tick();
    [...host.querySelectorAll("button")].find((b) => b.textContent.includes("b.pdf")).click(); await tick();
    [...host.querySelectorAll(".src-ask button")].find((b) => b.textContent.includes("바꾸기")).click(); await tick(); await tick();
    const fix = [...host.querySelectorAll("button")].find((b) => b.textContent.includes("도면 변경 반영하기"));
    assert(fix && host.textContent.includes("반영하지 못했습니다"), host.textContent);
    fix.click(); await tick();
    assert.equal(sent[sent.length - 1][0], "nodes.catch_up");
    host.remove();
  } },
  { name: "원본 고르기: 파일 줄은 파일마다, 형식 줄은 형식마다, 정착이 못 들인 줄은 고를 것 없음", async run(assert) {
    assert.equal(choicesOf(FILE_ROW).map((x) => x.args), [{ drawing_number: "graph-SNP-M-101", material_id: "m-a" }, { drawing_number: "graph-SNP-M-101", material_id: "m-b" }]);
    const fmtRow = Object.assign({}, FILE_ROW, { kind: "format", formats: ["drawio", "pdf_vector"],      // 형식마다 파일 하나: 형식 단추
      candidates: [FILE_ROW.candidates[0], Object.assign({}, FILE_ROW.candidates[1], { file: "b.drawio", format: "drawio" })] });
    assert.equal(choicesOf(fmtRow).filter((x) => x.kind === "format").map((x) => x.args.format), ["drawio", "pdf_vector"]);
    assert.equal(choicesOf(Object.assign({}, FILE_ROW, { reason: "settle_rebuild_failed" })), []);
    assert(previewText(FILE_ROW).includes("구간 2개가 다시 확인 대상"), previewText(FILE_ROW));
    const firm = previewText(FILE_ROW, { recheck: 2, released: 1 });
    assert(firm.includes("확정한 구간 1개는 확정이 풀립니다"), "확정이 풀린다고 미리 밝힌다(실제 창 4차): " + firm);
    assert(!previewText(FILE_ROW, { recheck: 2, released: 0 }).includes("확정이 풀립니다"));
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
  { name: "원본 고르기(검토 ⑥ 나·다): 구간 파일을 못 읽으면 '알 수 없음'을 밝히고 한 번 더 확인해야 바꾼다, 되돌아온다고 약속하지 않는다", async run(assert) {
    const UNKNOWN = Object.assign({}, FILE_ROW, { nodes_on_sheet: 0, nodes_unknown: true,
      candidates: FILE_ROW.candidates.map((x) => Object.assign({}, x, { recheck: x.in_use ? 0 : null, released: x.in_use ? 0 : null })) });
    const t = previewText(UNKNOWN, choicesOf(UNKNOWN).find((x) => !x.using));
    assert(t.includes("알 수 없습니다") && !t.includes("다시 확인할 것이 없습니다"), t);
    sent = [];
    window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return; sent.push([m.name, m.args]);
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: { chosen: {} } }))); }, setHandler() {} };
    window.fetch = async (u) => (String(u) === "/api/sources" ? { ok: true, status: 200, json: async () => ({ conflicts: [UNKNOWN] }) } : { ok: false, status: 404, json: async () => ({}) });
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${SourceConflicts} />`, host);
    await tick(); await tick();
    assert(!host.textContent.includes("바로 되돌아옵니다") && host.textContent.includes("다시 고르세요"), "되돌아온다고 약속하지 않는다");
    [...host.querySelectorAll("button")].find((b) => b.textContent.includes("b.pdf")).click(); await tick();
    const go = [...host.querySelectorAll(".src-ask button")].find((b) => b.textContent.includes("바꾸기"));
    assert(go.disabled, "영향을 모르면 확인 칸을 체크하기 전에는 못 바꾼다");
    const box = host.querySelector(".src-ask input[type=checkbox]");
    box.checked = true; box.dispatchEvent(new Event("change", { bubbles: true })); await tick();
    [...host.querySelectorAll(".src-ask button")].find((b) => b.textContent.includes("바꾸기")).click(); await tick();
    assert.equal(sent[0], ["sources.choose", { drawing_number: "graph-SNP-M-101", material_id: "m-b" }]);
    host.remove();
  } },
];
