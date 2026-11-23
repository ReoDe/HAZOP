// 도면 패널의 작업 카드(실제 창 3차 결함 3·4): 사람이 한 멈춤·취소는 '실패' 카드로 남기지 않고, 끝난 카드는 가장 새 것 둘만·닫을 수 있으며,
// 추출 설정 카드는 도면 목록 뒤에 있어 도면 줄의 단추가 위에서 밀려나지 않는다.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
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
    const list = host.querySelector(".drow"), settings = [...host.querySelectorAll(".card h3")].find((h) => h.textContent === "추출 설정");
    assert(list && settings && (list.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING), "추출 설정은 도면 줄 뒤");
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
];
