// 도면 패널의 작업 카드(실제 창 3차 결함 3·4): 사람이 한 멈춤·취소는 '실패' 카드로 남기지 않고, 끝난 카드는 가장 새 것 둘만·닫을 수 있으며,
// 추출 설정 카드는 도면 목록 뒤에 있어 도면 줄의 단추가 위에서 밀려나지 않는다.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import { DrawingsPanel } from "../js/panels/drawings.js";

const tick = async () => { for (let i = 0; i < 400; i++) await Promise.resolve(); };

export const tests = [
  { name: "도면 패널(실제 창 4차 결함 4): AI 검토 작업은 칩이 보이니 줄이 없고, 도는 작업은 한 줄, 끝난 작업은 접힌 묶음·닫기, 추출 설정은 목록 뒤", async run(assert) {
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ drawings: [] }) });
    window.hazopBridge = { send() {}, setHandler() {} };
    store.set({ drawings: { drawings: [{ graph_id: "G1", display: "SNP-M-101", drawing_number: "SNP-M-101", unknowns: 0 }], documents: [], project_id: "P", rev: "r" },
      jobs: { j1: { label: "등록", state: "done" }, j2: { label: "AI 검토", state: "stopped", message: "중지했습니다" }, j3: { label: "등록", state: "done" },
        j4: { label: "AI 검토", state: "done" }, j5: { label: "AI 검토", state: "running", text: "SNP-M-102 AI 검토 중" } } });
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${DrawingsPanel} onOpen=${() => {}} onClose=${() => {}} />`, host);
    await tick();
    assert.equal(host.querySelectorAll(".job-line[role=status]").length, 0, "도는 AI 검토는 도면 줄 칩이 보인다(작업 줄 없음)");
    const fold = host.querySelector("details.jobs-done");
    assert(fold && !fold.open && fold.textContent.includes("끝난 작업 2개"), "끝난 작업은 접힌 묶음(AI 검토 작업은 뺌)");
    assert(!host.textContent.includes("중지했습니다") && !host.textContent.includes("실패"), "멈춤은 실패 카드가 아님");
    const cards = [...fold.querySelectorAll(".job-line")];
    assert(host.querySelector(".drow"), "도면 줄");
    assert(![...host.querySelectorAll(".card h3")].some((h) => h.textContent === "추출 설정"), "추출 설정 카드는 화면에서 내렸다");
    cards[1].querySelector("button[aria-label$='알림 닫기']").click();
    await tick();
    assert(!store.get().jobs.j3 && store.get().jobs.j1, "닫은 것(j3)만 사라짐: " + Object.keys(store.get().jobs).join(","));
    store.set({ jobs: { r1: { label: "등록", state: "running", text: "SNP-M-101 읽는 중", done: 1, total: 3 } } });
    host.remove();
    const host2 = document.createElement("div"); document.body.appendChild(host2);      // 새로 그린다(숨은 페이지는 구독 효과가 늦다)
    render(html`<${DrawingsPanel} onOpen=${() => {}} onClose=${() => {}} />`, host2);
    await tick();
    const line = host2.querySelector(".job-line[role=status]");
    assert(line && line.textContent.includes("SNP-M-101 읽는 중") && line.textContent.includes("(1/3)"), "다른 도는 작업은 한 줄");
    store.set({ jobs: {} });
    host2.remove();
  } },
  { name: "도면 패널(화면 단순화): 요약 줄 없음, 줄은 번호와 제목만, 줄을 누르면 열림, 설정 카드 없음", async run(assert) {
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ drawings: [], conflicts: [] }) });
    window.hazopBridge = { send() {}, setHandler() {} };
    store.set({ jobs: {}, sheet: null, drawings: { drawings: [
      { graph_id: "G1", display: "SNP-M-101", drawing_number: "SNP-M-101", title: "냉각수 계통", unknowns: 3 },
      { graph_id: "G2", display: "SNP-M-102", drawing_number: "SNP-M-102", title: "", unknowns: 0 }], documents: [], project_id: "P", rev: "r" } });
    const opened = [];
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${DrawingsPanel} onOpen=${(g) => opened.push(g)} onClose=${() => {}} />`, host);
    await tick();
    const text = host.textContent;
    assert(!/도면 2장|프로젝트 P|AI 검토 전/.test(text), "요약 줄 없음: " + text);
    assert(!/미확인|읽음|열기/.test(text), "미확인 수·읽음 칩·열기 단추 없음: " + text);
    assert(!text.includes("추출 설정") && !host.querySelector(".ai-foot"), "AI 검토 설정 카드 없음");
    assert(!text.includes("이 도면 구성요소를 품은 구간"), "펼침 줄 없음");
    const rows = [...host.querySelectorAll(".drow")];
    assert.equal(rows.length, 2);
    assert(rows[0].querySelector(".main b").textContent === "SNP-M-101" && rows[0].querySelector(".main span").textContent === "냉각수 계통", "번호와 제목");
    rows[1].querySelector(".main").click(); await tick();
    assert.equal(opened, ["G2"], "줄을 누르면 그 도면이 열림");
    store.set({ drawings: { drawings: [], documents: [], project_id: null, rev: null } });
    host.remove();
  } },
  { name: "도면 패널(화면 단순화): 줄의 체크로 고른 도면을 분석에서 빼고, 뺀 도면은 다시 넣는다", async run(assert) {
    const sent = [];
    const nd = { drawings: [{ graph_id: "G1", display: "SNP-M-101", drawing_number: "SNP-M-101", excluded: false, ver: "v1", nodes: [] },
      { graph_id: "G2", display: "SNP-M-102", drawing_number: "SNP-M-102", excluded: true, ver: "v2", nodes: [] }] };
    window.fetch = async (u) => (String(u).includes("nodes/drawings") ? { ok: true, status: 200, json: async () => nd } : { ok: true, status: 200, json: async () => ({ conflicts: [] }) });
    window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return; sent.push([m.name, m.args]);
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: {} }))); }, setHandler() {} };
    store.set({ jobs: {}, sheet: null, app: Object.assign({}, store.get().app, { project_id: "P" }), drawings: { drawings: [
      { graph_id: "G1", display: "SNP-M-101", drawing_number: "SNP-M-101", title: "a" }, { graph_id: "G2", display: "SNP-M-102", drawing_number: "SNP-M-102", title: "b" }],
      documents: [], project_id: "P", rev: "r" } });
    const host = document.createElement("div"); document.body.appendChild(host);
    deliver(JSON.stringify({ t: "changed", topic: "drawings", rev: "r2" }));      // 도면 빼기 표시를 새로 읽는다(앞 시험이 빈 값으로 굳혀 둠)
    render(html`<${DrawingsPanel} onOpen=${() => {}} onClose=${() => {}} />`, host);
    await tick(); await tick();
    assert(!host.querySelector(".picks"), "고르기 전에는 도구 줄이 없다");
    const boxes = [...host.querySelectorAll(".drow input[type=checkbox]")];
    assert.equal(boxes.length, 2, "줄마다 고르기 표시");
    boxes[0].click(); await tick();
    const tool = host.querySelector(".picks");
    assert(tool, "고르면 위쪽에 도구 한 줄");
    const out = [...tool.querySelectorAll("button")].find((b) => b.textContent.includes("분석에서 빼기"));
    assert(out && ![...tool.querySelectorAll("button")].some((b) => b.textContent.includes("다시 넣기")), "고른 것이 분석에 들어간 도면이면 빼기만");
    out.click(); await tick(); await tick();
    assert.equal(sent[0][0], "nodes.exclude_drawing");
    assert(sent[0][1].graph_id === "G1" && sent[0][1].excluded === true && sent[0][1].ver === "v1", JSON.stringify(sent[0]));
    assert(!host.querySelector(".picks"), "처리하고 나면 고르기가 풀린다");
    boxes[1].click(); await tick();
    const back = [...host.querySelector(".picks").querySelectorAll("button")].find((b) => b.textContent.includes("다시 넣기"));
    assert(back, "뺀 도면을 고르면 다시 넣기");
    back.click(); await tick(); await tick();
    assert(sent[1][1].graph_id === "G2" && sent[1][1].excluded === false, JSON.stringify(sent[1]));
    store.set({ drawings: { drawings: [], documents: [], project_id: null, rev: null } });
    host.remove();
  } },
];
