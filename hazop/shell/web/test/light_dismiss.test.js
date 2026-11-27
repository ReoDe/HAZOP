// 바깥을 누르면 닫기: 공용 규칙(ui/light_dismiss.js)과, 도면 위 말풍선·작은 메뉴 종류마다의 시험.
import { html, render } from "../js/ui/html.js";
import { store } from "../js/store.js";
import { useState } from "../vendor/hooks.module.js";
import { options } from "../vendor/preact.module.js";
import { useLightDismiss } from "../js/ui/light_dismiss.js";
import * as C from "../js/canvas/clean_ui.js";
import { ItemBubble } from "../js/sheet_host.js";
import { Header } from "../js/panels/results.js";
import { Detail } from "../js/panels/ie.js";

// 숨은 페이지는 타이머를 1초 간격으로 늦추므로 기다림은 마이크로태스크로 하고, 이 시험 동안만 훅의 효과도 마이크로태스크에 돌린다.
const wait = async () => { for (let i = 0; i < 300; i++) await Promise.resolve(); };
const timer = () => new Promise((r) => setTimeout(r, 0));      // 초점 돌리기(타이머)를 보는 곳만

function mount(v) { const d = document.createElement("div"); document.body.appendChild(d); render(v, d); return d; }
function drop(d) { render(null, d); d.remove(); }

/** 한 번 누르기(끌면 dx만큼 움직인 뒤 뗀다). */
function press(el, { dx = 0, button = 0 } = {}) {
  const at = (type, x) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, composed: true, clientX: 50 + x, clientY: 50, button, pointerId: 3, isPrimary: true }));
  at("pointerdown", 0);
  if (dx) at("pointermove", dx);
  at("pointerup", dx);
}
const esc = () => document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));

/** 말풍선 하나의 규칙 확인: 안을 누르면 그대로, 바깥에서 끌면 그대로, 바깥을 한 번 누르면 닫힘. */
async function rules(assert, isOpen, reopen, inner) {
  const outside = mount(html`<button type="button">바깥</button>`).firstChild;
  press(inner());
  await wait();
  assert(isOpen(), "안을 누르면 닫히지 않는다");
  press(outside, { dx: 30 });
  await wait();
  assert(isOpen(), "바깥에서 끄는 것(도면 이동)은 닫지 않는다");
  press(outside, { button: 2 });
  await wait();
  assert(isOpen(), "오른쪽 단추는 닫기로 치지 않는다");
  let got = 0;
  outside.addEventListener("pointerup", () => got++);
  press(outside);
  await wait();
  assert(!isOpen(), "바깥을 한 번 누르면 닫힌다");
  assert.equal(got, 1, "누름은 아래 요소에도 전해진다");
  if (reopen) { await reopen(); assert(isOpen(), "다시 열림"); }
  outside.parentNode.remove();
}

/** 훅의 효과를 마이크로태스크에서 돌게 하고(숨은 페이지의 늦은 타이머를 피함) 끝나면 되돌린다. */
const quick = (run) => async (assert) => {
  const was = options.requestAnimationFrame;
  const keep = store.get(), kept = C.clean.get();
  options.requestAnimationFrame = (cb) => queueMicrotask(cb);
  try { await run(assert); } finally { C.clean.set(kept); store.set(keep); options.requestAnimationFrame = was; }
};

const cases = [
  { name: "바깥 누르면 닫기: 공용 함수는 Esc로도 닫고 초점을 연 자리로 돌리며, 다른 입력 칸을 눌러 닫으면 초점을 뺏지 않는다", async run(assert) {
    let set = null;
    function Probe() {
      const [open, setOpen] = useState(false);
      set = setOpen;
      let box = null;
      useLightDismiss(open, () => [box], () => setOpen(false), { esc: true });
      return html`<div><button type="button" class="opener">열기</button><input class="other" />${open ? html`<div class="pop" ref=${(e) => { box = e; }}><button type="button" class="in">안</button></div>` : null}</div>`;
    }
    const host = mount(html`<${Probe} />`);
    const q = (s) => host.querySelector(s);
    q(".opener").focus();
    set(true);
    await wait();
    q(".in").focus();
    esc();
    await wait();
    await timer();
    assert(!q(".pop"), "Esc로 닫힘");
    assert(document.activeElement === q(".opener"), "초점이 연 자리로");
    q(".opener").focus();
    set(true);
    await wait();
    q(".other").focus();
    press(q(".other"));
    await wait();
    await timer();
    assert(!q(".pop") && document.activeElement === q(".other"), "다른 입력 칸의 초점은 그대로");
    drop(host);
  } },
  { name: "바깥 누르면 닫기: 구성요소 속성 말풍선(바깥·Esc·X)", async run(assert) {
    const open = async () => { store.set({ sheet: "g1", bubble: { sheet: "g1", id: "n1", tag: "T-1", kind: "valve", kind_label: "밸브", rect: { x: 100, y: 100, w: 10, h: 10 } } }); await wait(); };
    const real = window.fetch;
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ items: [] }) });
    store.set({ bubble: null, drawings: { rev: 0, project_id: "P", drawings: [] } });      // 앞 시험이 남긴 상태를 비운다
    const host = mount(html`<${ItemBubble} />`);
    try {
      await wait();      // 화면이 상태를 듣기 시작한 뒤에 연다
      await open();
      await rules(assert, () => !!store.get().bubble && !!host.querySelector(".bubble.props"), open, () => host.querySelector(".bubble.props dl"));
      esc();
      await wait();
      assert(!store.get().bubble, "Esc");
      await open();
      host.querySelector('button[aria-label="말풍선 닫기"]').click();
      await wait();
      assert(!store.get().bubble, "X");
    } finally { window.fetch = real; store.set({ bubble: null }); drop(host); }
  } },
  { name: "바깥 누르면 닫기: 보기 설정 메뉴(원본·정리 단추를 눌러도 닫힘)", async run(assert) {
    store.set({ sheet: "g-vm" });
    C.onClean("g-vm", { source_format: "drawio", counts: { total: 0, unplaced: 0 }, unconfirmed: [], leftovers: null });
    const host = mount(html`<${C.CleanOverlay} />`);
    await wait();
    const open = async () => { host.querySelector(".vm-btn").click(); await wait(); };
    await open();
    await rules(assert, () => !!host.querySelector(".viewmenu"), open, () => host.querySelector(".viewmenu .vm-info"));
    press(host.querySelector(".clean-toggle button"));
    await wait();
    assert(!host.querySelector(".viewmenu"), "메뉴 바깥의 보기 단추를 눌러도 닫힌다");
    await open();
    press(host.querySelector(".vm-btn"));
    host.querySelector(".vm-btn").click();
    await wait();
    assert(!host.querySelector(".viewmenu"), "여닫는 단추는 누를 때마다 한 번만 뒤집는다");
    await open();
    esc();
    await wait();
    assert(!host.querySelector(".viewmenu"), "Esc");
    drop(host);
  } },
  { name: "바깥 누르면 닫기: 분석 실행 범위 메뉴", async run(assert) {
    const host = mount(html`<${Header} s=${{ kpi: { failed_cells: 1, recs: 0, cells: 0, done: 0 }, run: null, stale: false }} />`);
    await wait();
    const open = async () => { host.querySelector('button[aria-label="분석 실행"]').click(); await wait(); };
    await open();
    await rules(assert, () => !!host.querySelector(".runmenu"), open, () => host.querySelector(".runmenu"));
    esc();
    await wait();
    assert(!host.querySelector(".runmenu"), "Esc");
    drop(host);
  } },
  { name: "바깥 누르면 닫기: 초기사건 그룹 동작 더 보기", async run(assert) {
    const d = { group: { group_id: "G1", name: "n", status: "draft", problems: [], definition: "", members: [], headings: [], end_states: [], categories: [] }, stored_status: "draft", members: [], editable: {}, choices: {}, headings: [], end_states: [], basic_events: [] };
    const host = mount(html`<${Detail} s=${{ read_only: null }} d=${d} gid="G1" />`);
    await wait();
    const open = async () => { host.querySelector('button[aria-label="그룹 동작 더 보기"]').click(); await wait(); };
    await open();
    await rules(assert, () => !!host.querySelector(".ie-more"), open, () => host.querySelector(".ie-more"));
    esc();
    await wait();
    assert(!host.querySelector(".ie-more"), "Esc");
    drop(host);
  } },
];

export const tests = cases.map((c) => ({ name: c.name, run: quick(c.run) }));
