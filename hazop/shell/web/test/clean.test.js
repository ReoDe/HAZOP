// 정리된 보기(2단계 뒤 단위): 기본 보기 규칙, 원본|정리 바꾸기, 다음 미확인, 단추·칩 그리기, 계산 함수.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import * as C from "../js/canvas/clean_ui.js";
import * as V from "../js/canvas/clean_view.js";

const tick = async () => { for (let i = 0; i < 600; i++) await Promise.resolve(); };
const data = (fmt, list) => ({ source_format: fmt, items: {}, text_items: [], unconfirmed: list || [], counts: { total: (list || []).length } });
const U = [{ id: "a", reason: "unknown_symbol" }, { id: "b", reason: "open_end" }, { id: "c", reason: "missing_tag" }];

function reset() {
  C.clean.set({ choice: {}, data: {}, built: {}, bubble: null, cursor: -1 });
  store.set({ sheet: "g1", command: { seq: 0 } });
}

export const tests = [
  { name: "정리된 보기: 기본 보기는 drawio·dexpi는 정리, PDF는 원본, 확정된 쪽은 정리", run(assert) {
    assert.equal([V.defaultView("drawio"), V.defaultView("dexpi"), V.defaultView("pdf_vector"), V.defaultView("pdf_vector", true)], ["clean", "clean", "orig", "clean"]);
    reset();
    C.onClean("g1", data("pdf_vector"));
    assert.equal(C.viewOf(C.clean.get(), "g1"), "orig");
    C.onClean("g1", data("drawio"));
    assert.equal(C.viewOf(C.clean.get(), "g1"), "clean");
    assert.equal(C.viewOf(C.clean.get(), "없는-도면"), "orig");      // 정리 자료가 없으면 원본
  } },
  { name: "정리된 보기: 사람이 바꾼 보기가 기본보다 앞서고 도면마다 따로 기억", run(assert) {
    reset();
    C.onClean("g1", data("drawio"));
    C.onClean("g2", data("drawio"));
    C.toggleView("g1");
    assert.equal([C.viewOf(C.clean.get(), "g1"), C.viewOf(C.clean.get(), "g2")], ["orig", "clean"]);
    C.toggleView("g1");
    assert.equal(C.viewOf(C.clean.get(), "g1"), "clean");
    C.toggleView("자료-없음");                                           // 자료가 없으면 바꾸지 않는다
    assert.equal(C.clean.get().choice["자료-없음"], undefined);
  } },
  { name: "정리된 보기: 다음·앞 미확인은 순서대로 돌고 확대 명령과 말풍선 신호를 보냄", run(assert) {
    reset();
    C.onClean("g1", data("drawio", U));
    const ids = [];
    for (let i = 0; i < 4; i++) { const u = C.stepUnconfirmed("g1", 1); ids.push(u.id); }
    assert.equal(ids, ["a", "b", "c", "a"]);
    assert.equal(C.stepUnconfirmed("g1", -1).id, "c");                  // 앞으로(Shift+N)
    const cmd = store.get().command;
    assert.equal([cmd.type, cmd.id, cmd.reason, cmd.seq], ["inspect", "c", "missing_tag", 5]);
    C.onClean("g1", data("drawio", []));
    assert.equal(C.stepUnconfirmed("g1", 1), null);
  } },
  { name: "정리된 보기: 말풍선 열기·Esc로 닫기(닫았으면 다른 Esc 동작은 하지 않음)", run(assert) {
    reset();
    let cc = null;
    function Probe() { cc = C.useCleanCanvas("g1"); return html`<i></i>`; }
    const host = document.createElement("div");
    document.body.appendChild(host);
    render(html`<${Probe} />`, host);
    assert.equal(cc.closeIfOpen(), false);
    cc.props.onUnconfirmedClick({ id: "a", reason: "unknown_symbol", fragment: null });
    assert.equal(C.clean.get().bubble.reason, "unknown_symbol");
    assert.equal(cc.closeIfOpen(), true);
    assert.equal(C.clean.get().bubble, null);
    render(null, host); host.remove();
  } },
  { name: "정리된 보기: 단추는 자료가 없으면 '정리'가 꺼지고, 칩은 '미확인 n곳'이며 도면에서 온 글은 텍스트로만", async run(assert) {
    reset();
    const host = document.createElement("div");
    document.body.appendChild(host);
    render(html`<${C.CleanOverlay} />`, host);
    await tick();
    const btn = (label) => [...host.querySelectorAll("button")].find((b) => b.textContent.trim() === label);
    assert(btn("정리").disabled && !btn("원본").disabled, "자료 없음");
    C.onClean("g1", data("drawio", U));
    await tick();
    assert(!btn("정리").disabled && btn("정리").getAttribute("aria-pressed") === "true", "정리가 켜짐(drawio 기본)");
    assert(host.textContent.includes("미확인 3곳"), host.textContent);
    btn("원본").click();
    await tick();
    assert.equal(C.viewOf(C.clean.get(), "g1"), "orig");
    C.openBubble({ id: "x", reason: "missing_tag", fragment: { href: "/api/sheet/g1.svg", size: [100, 100], box: { x: 0, y: 0, w: 50, h: 50 } } });
    await tick();
    assert(host.textContent.includes("태그가 없음") && !!host.querySelector(".cleanpop svg image"), "원본 조각 말풍선");
    assert(host.querySelector(".cleanpop svg image").getAttribute("href") === "/api/sheet/g1.svg");
    render(null, host); host.remove();
  } },
  { name: "정리된 보기: 기호 맞추기 계산(keep·stretch·회전·뒤집기·연결점)", run(assert) {
    const keep = { vb: [100, 60], fit: "keep" }, stretch = { vb: [100, 100], fit: "stretch" };
    const p = V.placement(keep, [0, 0, 50, 30], { rot: 0 });
    assert.equal([p.cx, p.cy, p.sx], [25, 15, 0.5]);
    const q = V.placement(keep, [0, 0, 30, 50], { rot: 90 });           // 세로 상자: 가로세로를 바꿔 맞춘다
    assert.equal([q.sx, q.sy], [0.5, 0.5]);
    const [wx, wy] = V.toWorld(q, 100, 30);                              // 오른쪽 연결점은 90° 돌면 상자 아래쪽 끝으로 간다
    assert(Math.abs(wx - 15) < 0.01 && Math.abs(wy - 50) < 0.01, wx + "," + wy);
    const s = V.placement(stretch, [0, 0, 40, 80], { rot: 0, flip_h: true });
    assert.equal([s.sx, s.sy], [-0.4, 0.8]);
    assert.equal(V.fragmentBox([10, 10, 30, 30], [100, 100]), { x: 0, y: 0, w: 54, h: 54 });
  } },
  { name: "정리된 보기: 자료가 늦게 와도 <Sheet>에 줄 view가 바뀜(선택 함수가 처음 도면 ID를 붙들지 않음)", async run(assert) {
    reset();
    let cc = null;
    function Probe() { cc = C.useCleanCanvas("g1"); return html`<i></i>`; }
    const host = document.createElement("div");
    document.body.appendChild(host);
    render(html`<${Probe} />`, host);
    await tick();
    assert.equal(cc.props.view, "orig");
    C.onClean("g1", data("drawio"));
    await tick();
    assert.equal(cc.props.view, "clean");
    C.toggleView("g1");
    await tick();
    assert.equal(cc.props.view, "orig");
    render(null, host); host.remove();
  } },
  { name: "정리된 보기: 모르는 읽은 방법·raster는 원본이 기본, DEXPI는 원본 단추를 숨기고 '원본 그림 없음'", async run(assert) {
    assert.equal([V.defaultView("unknown"), V.defaultView("raster"), V.defaultView("unknown", true), V.defaultView(undefined)], ["orig", "orig", "clean", "orig"]);
    reset();
    C.onClean("g1", data("dexpi"));
    C.setView("g1", "orig");                                          // 원본을 고르려 해도 원본 그림이 없다
    assert.equal(C.viewOf(C.clean.get(), "g1"), "clean");
    const host = document.createElement("div");
    document.body.appendChild(host);
    render(html`<${C.CleanOverlay} />`, host);
    await tick();
    const labels = [...host.querySelectorAll("button")].map((b) => b.textContent.trim());
    assert(!labels.includes("원본") && host.textContent.includes("원본 그림 없음 · DEXPI 변환"), host.textContent);
    C.onClean("g1", data("unknown"));
    await tick();
    assert(host.textContent.includes("읽은 방법 모름") && [...host.querySelectorAll("button")].some((b) => b.textContent.trim() === "원본"), "모르는 방법은 원본 단추가 있고 꼬리표가 호박색");
    render(null, host); host.remove();
  } },
  { name: "정리된 보기: 위치 없음·원본에 남은 것 칩, L 키로 겹치기, 원본 겹쳐 보기", async run(assert) {
    reset();
    const d = data("pdf_vector", U);
    d.counts.unplaced = 2;
    d.leftovers = { counted: false, n: 0, items: [] };
    C.onClean("g1", d);
    const host = document.createElement("div");
    document.body.appendChild(host);
    render(html`<${C.CleanOverlay} />`, host);
    await tick();
    assert(host.textContent.includes("위치 없음 2") && host.textContent.includes("원본에 남은 것: 엔진이 세지 않음"), host.textContent);
    const d2 = data("drawio", []);
    d2.leftovers = { counted: true, n: 3, items: [] };
    C.onClean("g1", d2);
    await tick();
    assert(host.textContent.includes("원본에 남은 것 3"), "센 읽은 방법은 개수");
    let cc = null;
    function Probe() { cc = C.useCleanCanvas("g1"); return html`<i></i>`; }
    const h2 = document.createElement("div");
    document.body.appendChild(h2);
    render(html`<${Probe} />`, h2);
    await tick();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "l", bubbles: true }));
    await tick();
    assert.equal(cc.props.overlays.leftovers, true);
    [...host.querySelectorAll("button")].find((b) => b.textContent.trim() === "원본 겹쳐 보기").click();
    await tick();
    assert.equal(cc.props.overlays.original, true);
    render(null, h2); h2.remove(); render(null, host); host.remove();
  } },
];
