// 도면 패널의 작업 카드(실제 창 3차 결함 3·4): 사람이 한 멈춤·취소는 '실패' 카드로 남기지 않고, 끝난 카드는 가장 새 것 둘만·닫을 수 있으며,
// 추출 설정 카드는 도면 목록 뒤에 있어 도면 줄의 단추가 위에서 밀려나지 않는다.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import { DrawingsPanel } from "../js/panels/drawings.js";

const tick = async () => { for (let i = 0; i < 400; i++) await Promise.resolve(); };

export const tests = [
  { name: "번호가 빈 도면 줄은 파일 이름 한 줄(굵게)이고 '· 1쪽' 꼬리와 주황 점이 없다. 같은 파일에 여러 쪽이면 쪽은 남는다", async run(assert) {
    const real = window.fetch;
    const auto = { consent: { allow: false, asked: false }, ask: false, sheets: [{ graph_id: "g-new", result: "waiting", why: "no_consent" }] };
    window.fetch = async (u) => (String(u) === "/api/aireview/auto" ? { ok: true, status: 200, json: async () => auto } : { ok: false, status: 404, json: async () => ({}) });
    window.hazopBridge = { send() {}, setHandler() {} };
    const rows = [{ graph_id: "g-new", display: "SNP-M-101_RCS-main-loop.drawio · 1쪽", drawing_number: null, number_state: "unconfirmed", title: null, material_id: "m1", unknowns: 0 },
      { graph_id: "g-p1", display: "manual.pdf · 1쪽", drawing_number: null, number_state: "unconfirmed", material_id: "m2", unknowns: 0 },
      { graph_id: "g-p2", display: "manual.pdf · 2쪽", drawing_number: null, number_state: "unconfirmed", material_id: "m2", unknowns: 0 }];
    store.set({ jobs: {}, drawings: { drawings: rows, documents: [], project_id: "P", rev: "r" } });
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${DrawingsPanel} onOpen=${() => {}} onClose=${() => {}} />`, host);
    try {
      await new Promise((r) => setTimeout(r, 80));
      const lines = [...host.querySelectorAll(".drow")];
      assert.equal(lines[0].querySelector("b").textContent, "SNP-M-101_RCS-main-loop.drawio");
      assert.equal(lines[0].querySelectorAll(".drow-open span").length, 0, "한 줄");
      assert.equal(lines[0].querySelectorAll(".drow-dot").length, 0, "주황 점 없음");
      assert.equal([lines[1].querySelector("b").textContent, lines[2].querySelector("b").textContent], ["manual.pdf · 1쪽", "manual.pdf · 2쪽"]);
    } finally {
      window.fetch = real; render(null, host); host.remove();
      store.set({ drawings: { drawings: [], documents: [], project_id: null, rev: null } });
    }
  } },
  { name: "도면 패널(실제 창 4차 결함 4): AI 검토 작업은 칩이 보이니 줄이 없고, 도는 작업은 한 줄, 끝난 작업은 접힌 묶음·닫기, 추출 설정은 목록 뒤", async run(assert) {
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ drawings: [], nodes: [], batches: [], outside: { count: 0, total: 0 } }) });
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
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ drawings: [], conflicts: [], nodes: [], batches: [], outside: { count: 0, total: 0 } }) });
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
  { name: "도면 패널: 고른 도면은 휴지통 '삭제'로 목록에서 없어지고(확인 창 없음), 지운 도면은 보이지 않는다", async run(assert) {
    const sent = [];
    const nd = { drawings: [{ graph_id: "G1", display: "SNP-M-101", drawing_number: "SNP-M-101", excluded: false, ver: "v1", nodes: [] },
      { graph_id: "G2", display: "SNP-M-102", drawing_number: "SNP-M-102", excluded: true, ver: "v2", nodes: [] }] };
    window.fetch = async (u) => (String(u).includes("nodes/drawings") ? { ok: true, status: 200, json: async () => nd } : { ok: true, status: 200, json: async () => ({ conflicts: [], drawings: [], nodes: [], batches: [], outside: { count: 0, total: 0 } }) });      // 앞 시험이 남긴 구간 패널도 읽는다
    window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return; sent.push([m.name, m.args]);
      const ask = !m.args.confirm;                       // 첫 답: 그 도면 구성요소를 품은 구간이 있다는 확인 글
      if (!ask) nd.drawings[0] = Object.assign({}, nd.drawings[0], { excluded: true, ver: "v3" });
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: ask ? { needs_confirm: "구간 S1이 이 도면을 품습니다" } : {} }))); }, setHandler() {} };
    store.set({ jobs: {}, sheet: null, app: Object.assign({}, store.get().app, { project_id: "P" }), drawings: { drawings: [
      { graph_id: "G1", display: "SNP-M-101", drawing_number: "SNP-M-101", title: "a" }, { graph_id: "G2", display: "SNP-M-102", drawing_number: "SNP-M-102", title: "b" }],
      documents: [], project_id: "P", rev: "r" } });
    const host = document.createElement("div"); document.body.appendChild(host);
    deliver(JSON.stringify({ t: "changed", topic: "drawings", rev: "r2" }));      // 도면 빼기 표시를 새로 읽는다(앞 시험이 빈 값으로 굳혀 둠)
    render(html`<${DrawingsPanel} onOpen=${() => {}} onClose=${() => {}} />`, host);
    await tick(); await tick();
    assert(!host.querySelector(".picks"), "고르기 전에는 도구 줄이 없다");
    const boxes = [...host.querySelectorAll(".drow input[type=checkbox]")];
    assert.equal(boxes.length, 1, "이미 지운 도면(G2)은 목록에 없다");
    assert(!host.textContent.includes("SNP-M-102"), host.textContent);
    boxes[0].click(); await tick();
    const tool = host.querySelector(".picks");
    assert(tool, "고르면 위쪽에 도구 한 줄");
    const trash = tool.querySelector('button[aria-label="삭제"]');
    assert(trash && trash.title === "삭제" && !trash.textContent.trim() && !!trash.querySelector("svg"), "삭제는 휴지통 아이콘만(접근성 이름·도움말 '삭제')");
    assert(![...tool.querySelectorAll("button")].some((b) => /빼기|다시 넣기|풀기/.test(b.textContent + b.title)), "옛 단추는 없다");
    const clear = tool.querySelector('button[aria-label="고르기 해제"]');
    assert(clear && clear.textContent.trim() === "해제", "고른 것은 '해제'로 푼다");
    trash.click(); await tick(); await tick();
    assert.equal(sent[0][0], "nodes.exclude_drawing");
    assert(sent[0][1].graph_id === "G1" && sent[0][1].excluded === true && sent[0][1].ver === "v1", JSON.stringify(sent[0]));
    await tick(); await tick();
    assert.equal(sent.length, 2, "확인 글은 사람에게 묻지 않고 그대로 되돌려 보낸다");
    assert.equal(sent[1][1].confirm, "구간 S1이 이 도면을 품습니다");
    assert(!host.querySelector(".picks") && !host.textContent.includes("구간 S1이"), "확인 창·안내 글 없이 끝난다");
    assert.equal(host.querySelectorAll(".drow").length, 0, "지운 도면은 목록에서 없어진다");
    assert(![...host.querySelectorAll(".drow")].some((r) => r.textContent.includes("분석 제외")), "분석 제외 칩은 없다");
    store.set({ drawings: { drawings: [], documents: [], project_id: null, rev: null } });
    host.remove();
  } },
];
