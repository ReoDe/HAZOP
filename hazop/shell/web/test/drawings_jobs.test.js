// 도면 패널의 작업 카드(실제 창 3차 결함 3·4): 사람이 한 멈춤·취소는 '실패' 카드로 남기지 않고, 끝난 카드는 가장 새 것 둘만·닫을 수 있으며,
// 추출 설정 카드는 도면 목록 뒤에 있어 도면 줄의 단추가 위에서 밀려나지 않는다.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { DrawingsPanel } from "../js/panels/drawings.js";

const tick = async () => { for (let i = 0; i < 400; i++) await Promise.resolve(); };

export const tests = [
  { name: "도면 패널: 멈춘 작업은 카드가 없고, 끝난 카드는 둘만·닫기, 추출 설정은 도면 목록 뒤", async run(assert) {
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ drawings: [] }) });
    window.hazopBridge = { send() {}, setHandler() {} };
    store.set({ drawings: { drawings: [{ graph_id: "G1", display: "SNP-M-101", drawing_number: "SNP-M-101", unknowns: 0 }], documents: [], project_id: "P", rev: "r" },
      jobs: { j1: { label: "등록", state: "done" }, j2: { label: "AI 검토", state: "stopped", message: "중지했습니다" }, j3: { label: "등록", state: "done" },
        j4: { label: "AI 검토", state: "done" }, j5: { label: "AI 검토", state: "running", text: "SNP-M-102 AI 검토 중" } } });
    const host = document.createElement("div"); document.body.appendChild(host);
    render(html`<${DrawingsPanel} onOpen=${() => {}} onClose=${() => {}} />`, host);
    await tick();
    const cards = [...host.querySelectorAll(".card.job")];
    assert.equal(cards.length, 3, "도는 것 하나와 끝난 것 둘");
    assert(!host.textContent.includes("중지했습니다") && !host.textContent.includes("실패"), "멈춤은 실패 카드가 아님");
    const list = host.querySelector(".drow"), settings = [...host.querySelectorAll(".card h3")].find((h) => h.textContent === "추출 설정");
    assert(list && settings && (list.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING), "추출 설정은 도면 줄 뒤");
    cards[1].querySelector("button[aria-label$='알림 닫기']").click();
    await tick();
    assert(!store.get().jobs.j3 && store.get().jobs.j4, "닫은 카드(j3)만 사라짐: " + Object.keys(store.get().jobs).join(","));
    store.set({ jobs: {} });
    host.remove();
  } },
];
