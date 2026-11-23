// '다음에 할 일' 한 줄(web/js/next/next.js, HZ-DSN-06 §3.1 G1 화면): 엔진 목록 맨 앞 것을 줄에, 전부를 펼침에 같은 차례로 그리고,
// 단추·Ctrl+J가 그 자리로 간다. 도면 위 자리로 가는 단추는 열린 패널을 닫는다.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as NX from "../js/next/next.js";
const { NextLine, go, load, next, setGo } = NX;

const tick = async () => { for (let i = 0; i < 400; i++) await Promise.resolve(); };
const item = (kind, text, label, goTo, extra) => Object.assign({ kind, count: 1, text, detail: null, action: { label, go: goTo, target: null }, tone: "" }, extra || {});
const LIST = [
  item("recheck", "도면이 바뀌어 3곳을 다시 확인해야 합니다", "확인하기", "queue:lost", { tone: "warn", count: 3, detail: "검토구간 S1에 걸려 있습니다" }),
  item("titleblock", "표제란을 확정하지 않은 도면이 1장 있습니다", "표제란 확정", "panel:drawings#titleblock"),
  item("nodes_draft", "확정하지 않은 검토구간이 2개 있습니다", "모두 확정", "confirm:nodes.confirm"),
];
let served;

function stub() {
  window.fetch = async (url) => {
    const body = (data) => ({ ok: true, status: 200, json: async () => data });
    if (String(url) === "/api/next") return body(served);
    return { ok: false, status: 404, json: async () => ({}) };
  };
}

async function mount() {
  stub();
  served = { items: LIST, running: null, ver: "a" };
  next.set({ items: [], running: null, open: false, pinned: null });
  const host = document.createElement("div");
  document.body.appendChild(host);
  render(html`<${NextLine} />`, host);
  await load();
  await tick();
  return host;
}

export const tests = [
  { name: "다음에 할 일: 맨 앞 것을 줄에, 경고 꼴, '그 밖에 n건'", async run(assert) {
    const host = await mount();
    const line = host.querySelector(".next .line");
    assert(line && line.classList.contains("warn"), "다시 확인은 경고 꼴");
    assert(line.textContent.includes("도면이 바뀌어 3곳을 다시 확인해야 합니다") && line.textContent.includes("확인하기"), line.textContent);
    assert(line.textContent.includes("그 밖에 2건"), "남은 수");
    host.remove();
  } },
  { name: "다음에 할 일: 펼치면 엔진 차례 그대로 전부 보인다", async run(assert) {
    const host = await mount();
    host.querySelector(".next .more").click();
    await tick();
    const rows = [...host.querySelectorAll(".next-list .item .t")].map((x) => x.firstChild.textContent);
    assert.equal(rows, LIST.map((x) => x.text));
    host.remove();
  } },
  { name: "다음에 할 일: 할 일이 없으면 조용한 꼴, 작업 중이면 진행 막대", async run(assert) {
    const host = await mount();
    served = { items: [item("none", "지금 할 일이 없습니다", "Excel로 내보내기", "confirm:results.export_excel", { tone: "quiet" })], running: null };
    await load(); await tick();
    assert(host.querySelector(".next .line.calm"), "조용한 꼴");
    served = { items: LIST, running: { what: "register", label: "SNP-M-102를 읽고 있습니다", done: 2, total: 3 } };
    await load(); await tick();
    const l = host.querySelector(".next .line.info");
    assert(l && l.textContent.includes("SNP-M-102를 읽고 있습니다") && host.querySelector(".next .bar i"), "진행 줄");
    host.remove();
  } },
  { name: "다음에 할 일: 엔진이 next가 바뀌었다고 알리면 다시 읽는다", async run(assert) {
    const host = await mount();
    served = { items: [LIST[1]], running: null };
    deliver(JSON.stringify({ t: "changed", topic: "next", rev: null }));
    await new Promise((r) => setTimeout(r, 200));
    await tick();
    assert(host.querySelector(".next .line .txt").textContent.includes("표제란"), "새 맨 앞 것");
    host.remove();
  } },
  { name: "다음에 할 일(실제 창 4차): 바뀜 알림의 첫 것은 타이머를 기다리지 않고 바로 다시 읽는다(수가 한 박자 늦지 않게)", async run(assert) {
    const host = await mount();
    await new Promise((r) => setTimeout(r, 400));                 // 앞 시험의 읽기와 떨어뜨린다
    served = { items: [LIST[2]], running: null };
    deliver(JSON.stringify({ t: "changed", topic: "next", rev: null }));
    await tick();
    assert(host.querySelector(".next .line .txt").textContent.includes("검토구간이 2개"), "바로 읽음: " + host.querySelector(".next .line .txt").textContent);
    host.remove();
  } },
  { name: "다음에 할 일(실제 창 5차): 맨 위 줄에 곁 단추(alt)가 있으면 나란히 보이고 그 자리로 간다", async run(assert) {
    const host = await mount();
    const seen = [];
    setGo("confirm:aireview.run", (t) => seen.push(["ai", t]));
    served = { items: [item("sheet_confirm", "원본과 견주어 확정할 쪽이 1장 있습니다. 확정 전에 AI 검토를 먼저 돌릴 수도 있습니다", "쪽 확정", "panel:drawings#sheetconf",
      { alt: { label: "AI 검토 시작", go: "confirm:aireview.run", target: "G1" } })], running: null };
    await load(); await tick();
    const btns = [...host.querySelectorAll(".next .line button.btn")];
    assert.equal(btns.map((b) => b.textContent.trim()), ["쪽 확정", "AI 검토 시작"]);
    btns[1].click();
    assert.equal(seen, [["ai", "G1"]]);
    host.remove();
  } },
  { name: "다음에 할 일(실제 창 5차): 구간을 만들거나 확정한 직후 수를 바로 고치고, 엔진 읽기가 그 값을 덮는다", async run(assert) {
    next.set({ items: [item("nodes_none", "검토구간을 만들 차례입니다", "구간 만들기", "panel:nodes#pick")] });
    NX.adjustDrafts(1);
    assert.equal(next.get().items.map((x) => [x.kind, x.count]), [["nodes_draft", 1]], "구간 없음 → 확정 안 한 구간 1개");
    NX.adjustDrafts(1);
    assert(next.get().items[0].text.includes("2개"), next.get().items[0].text);
    NX.adjustDrafts(-2);
    assert.equal(next.get().items.length, 1, "0개가 되면 줄을 빼되 목록을 비우지 않는다");
  } },
  { name: "다음에 할 일: 단추와 Ctrl+J가 같은 자리로 가고, 도면 위 자리로 갈 때 패널을 닫는다", async run(assert) {
    const host = await mount();
    const seen = [];
    setGo("queue:lost", (t) => seen.push(["lost", t]));
    host.querySelector(".next .line .btn").click();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "j", ctrlKey: true, bubbles: true }));
    assert.equal(seen.length, 2, "단추·Ctrl+J");
    store.set({ panel: "ie" });
    go({ go: "panel:results" });
    assert.equal(store.get().panel, "results", "패널로 가기");
    go({ go: "queue:ai" });
    assert.equal(store.get().panel, "aireview", "대기열 전에는 AI 검토 패널로");
    host.remove();
  } },
  { name: "다음에 할 일(실제 창 3차): '그 밖에'에서 고른 일은 그 일이 남아 있는 동안 줄 맨 앞, 없어지면 엔진 차례로", async run(assert) {
    const host = await mount();
    const seen = [];
    setGo("confirm:nodes.confirm", () => seen.push("nodes"));
    host.querySelector(".next .more").click();
    await tick();
    host.querySelectorAll(".next-list .item")[2].click();
    await tick();
    assert.equal(seen, ["nodes"]);
    assert(host.querySelector(".next .line .txt").textContent.includes("확정하지 않은 검토구간"), "고른 일이 줄 맨 앞: " + host.querySelector(".next .line .txt").textContent);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "j", ctrlKey: true, bubbles: true }));
    assert.equal(seen, ["nodes", "nodes"], "Ctrl+J도 고른 일");
    served = { items: [LIST[0], LIST[1]], running: null };
    await load(); await tick();
    assert(host.querySelector(".next .line .txt").textContent.includes("다시 확인"), "고른 일이 끝나면 엔진 맨 위 것");
    assert.equal(next.get().pinned, null);
    host.remove();
  } },
];
