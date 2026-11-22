import { render } from "../vendor/preact.module.js";
import { html } from "../js/ui/html.js";
import { VirtualGrid, visibleRange, scrollFor, nextActive } from "../js/ui/table.js";

function css() {
  if (document.querySelector("link[data-t-css]")) return Promise.resolve();
  return new Promise((ok) => {
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = "../shell.css"; l.setAttribute("data-t-css", "");
    l.onload = ok; l.onerror = ok;
    document.head.appendChild(l);
  });
}

const tick = () => new Promise((r) => setTimeout(r, 50));

async function draw(rows, cols, props) {
  await css();
  const host = document.createElement("div");
  host.style.cssText = "width:900px;height:400px;position:relative";
  document.body.appendChild(host);
  render(html`<${VirtualGrid} rows=${rows} cols=${cols} rowH=${34} colW=${64} headH=${64} headW=${172} label="시험 표"
    renderCell=${(r, c) => html`<span>${r}:${c}</span>`} renderColHead=${(c) => "c" + c} renderRowHead=${(r) => "S" + (r + 1)} ...${props || {}} />`, host);
  await tick();
  return host;
}

export const tests = [
  { name: "table: 보이는 범위와 스크롤 값 계산", run(assert) {
    assert.equal(visibleRange(0, 100, 10, 1000, 2), [0, 12]);
    assert.equal(visibleRange(500, 100, 10, 1000, 2), [48, 62]);
    assert.equal(visibleRange(99999, 100, 10, 100, 2), [88, 100]);
    assert.equal(visibleRange(0, 100, 10, 0), [0, 0]);
    assert.equal(scrollFor(5, 10, 0, 100), 0);
    assert.equal(scrollFor(20, 10, 0, 100), 110);
    assert.equal(scrollFor(1, 10, 50, 100), 10);
  } },
  { name: "table: 화살표·Home·End·페이지 키가 활성 칸을 옮기고 가장자리에서 멈춘다", run(assert) {
    const a = { r: 0, c: 0 };
    assert.equal(nextActive("ArrowUp", a, 5, 5), { r: 0, c: 0 });
    assert.equal(nextActive("ArrowDown", a, 5, 5), { r: 1, c: 0 });
    assert.equal(nextActive("End", { r: 2, c: 1 }, 5, 5), { r: 2, c: 4 });
    assert.equal(nextActive("PageDown", { r: 1, c: 1 }, 5, 5, 10), { r: 4, c: 1 });
    assert.equal(nextActive("a", a, 5, 5), null);
  } },
  { name: "table: 525×44 표는 보이는 칸만 DOM으로 만들고 스크롤하면 바뀐다", async run(assert) {
    const t0 = performance.now();
    const host = await draw(525, 44);
    const cells = host.querySelectorAll(".vg-cell").length;
    assert(cells > 0 && cells < 400, "보이는 칸만: " + cells);
    assert.equal(host.querySelector("[role=grid]").getAttribute("aria-rowcount"), "525");
    assert(host.querySelector(".vg-rh").textContent === "S1" || host.querySelector(".vg-rh").textContent.startsWith("S"), "행 머리");
    const body = host.querySelector(".vg-body");
    body.scrollTop = 34 * 400; body.scrollLeft = 64 * 30;
    body.dispatchEvent(new Event("scroll"));
    await tick();
    const heads = [...host.querySelectorAll(".vg-rh")].map((e) => e.textContent);
    assert(heads.includes("S401"), "스크롤한 곳의 행 머리: " + heads.slice(0, 3));
    assert(host.querySelectorAll(".vg-cell").length < 400, "스크롤 뒤에도 보이는 칸만");
    assert(performance.now() - t0 < 4000, "그리기가 너무 느림");
  } },
  { name: "table: 525×44 표의 스크롤 한 번 갱신 시간이 프레임 한도(50ms) 안이다", async run(assert) {
    const host = await draw(525, 44);
    const body = host.querySelector(".vg-body");
    const flush = async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); };    // 조정(Preact 렌더)은 마이크로태스크로 돈다
    const times = [];
    for (let i = 1; i <= 60; i++) {
      const t0 = performance.now();
      body.scrollTop = i * 34 * 7;
      body.scrollLeft = (i % 30) * 64;
      body.dispatchEvent(new Event("scroll"));
      await flush();
      host.querySelectorAll(".vg-cell").length;      // 그린 결과를 읽어 배치까지 끝나게 한다
      times.push(performance.now() - t0);
    }
    times.sort((a, b) => a - b);
    const p95 = times[Math.floor(times.length * 0.95)], max = times[times.length - 1], avg = times.reduce((x, y) => x + y, 0) / times.length;
    (window.__measures = window.__measures || []).push({ what: "525×44 스크롤 갱신(ms)", steps: times.length, avg: +avg.toFixed(2), p95: +p95.toFixed(2), max: +max.toFixed(2),
      cells: host.querySelectorAll(".vg-cell").length, viewport: "900×400", cond: "오프스크린 QtWebEngine, GPU 끔, 숨은 페이지" });
    assert(p95 <= 50, "스크롤 갱신 p95 " + p95.toFixed(1) + "ms > 50ms");
  } },
  { name: "table: 칸 글자는 HTML로 해석되지 않고, 클릭은 활성 칸·열기 콜백을 부른다", async run(assert) {
    const calls = [];
    const host = await draw(3, 3, { renderCell: (r, c) => "<b>x" + r + c + "</b>", onActive: (r, c) => calls.push(["a", r, c]), onOpen: (r, c) => calls.push(["o", r, c]) });
    assert.equal(host.querySelectorAll(".vg-cell b").length, 0);
    const cell = host.querySelectorAll(".vg-cell")[4];
    cell.click();
    cell.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    assert.equal(calls, [["a", 1, 1], ["o", 1, 1]]);
  } },
];
